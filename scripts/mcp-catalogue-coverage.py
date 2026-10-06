#!/usr/bin/env python3
"""Konnect MCP 공개 도구 카탈로그를 실패 폐쇄 방식으로 감사한다.

이 검증기는 두 사실을 의도적으로 분리한다.

1. 실행 중 서버가 도구와 JSON Schema를 실제로 광고했고, 잘못된 입력을
   handler 실행 전에 거부했다는 사실.
2. 각 도구의 정상 동작, 쓰기 readback, 원본 보존, GUI/IPC/CLI/외부 서비스
   동작이 독립 증거로 입증됐다는 사실.

1번이 통과해도 2번을 자동으로 통과시키지 않는다. 따라서 전체 기능 무결성
주장은 행렬의 모든 필수 증거가 채워진 경우에만 가능하다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
UNKNOWN_PROBE = "__konnect_catalogue_probe__"
SCHEMA_VERSION = 1


class CoverageError(RuntimeError):
    """검증을 계속하면 누락을 성공으로 오인할 수 있을 때 발생한다."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(base: Path, paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise CoverageError(f"지원하지 않는 JSON 값 형식: {type(value).__name__}")


def _allowed_types(schema: dict[str, Any]) -> set[str]:
    declared = schema.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list) and all(isinstance(item, str) for item in declared):
        return set(declared)
    if "enum" in schema:
        return {_json_type(value) for value in schema["enum"]}
    if "const" in schema:
        return {_json_type(schema["const"])}
    for keyword in ("oneOf", "anyOf"):
        choices = schema.get(keyword)
        if isinstance(choices, list):
            union: set[str] = set()
            for choice in choices:
                if isinstance(choice, dict):
                    union.update(_allowed_types(choice))
            if union:
                return union
    return set()


def _valid_placeholder(schema: dict[str, Any]) -> Any:
    """다른 필드가 표적 필드의 오류를 가리지 않도록 보수적 예시를 만든다.

    완전한 JSON Schema 생성기가 아니다. 생성값이 다른 제약에 걸리면 runtime
    결과에서 표적 필드 불일치로 드러나며 정상 증거로 승격되지 않는다.
    """

    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "default" in schema:
        return schema["default"]
    for keyword in ("oneOf", "anyOf"):
        choices = schema.get(keyword)
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            return _valid_placeholder(choices[0])

    allowed = _allowed_types(schema)
    kind = next(iter(allowed), "string")
    if kind == "string":
        minimum = int(schema.get("minLength", 1))
        return "x" * max(1, minimum)
    if kind == "integer":
        minimum = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        value = int(minimum)
        if "exclusiveMinimum" in schema:
            value += 1
        return value
    if kind == "number":
        minimum = float(schema.get("minimum", schema.get("exclusiveMinimum", 0.0)))
        if "exclusiveMinimum" in schema:
            minimum += 1.0
        return minimum
    if kind == "boolean":
        return False
    if kind == "array":
        count = max(0, int(schema.get("minItems", 0)))
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return [_valid_placeholder(item_schema) for _ in range(count)]
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        return {
            key: _valid_placeholder(properties.get(key, {}))
            for key in required
            if isinstance(key, str)
        }
    if kind == "null":
        return None
    return "x"


def _invalid_type_value(schema: dict[str, Any]) -> Any:
    allowed = _allowed_types(schema)
    if not allowed:
        raise CoverageError("명시적 type/enum/const가 없어 안전한 wrong-type 값을 만들 수 없습니다")
    for candidate in ({}, [], "wrong-type", 1, True, None):
        actual = _json_type(candidate)
        compatible = actual in allowed or (actual == "integer" and "number" in allowed)
        if not compatible:
            return candidate
    raise CoverageError(f"모든 JSON 형식을 허용해 wrong-type probe를 만들 수 없습니다: {allowed}")


def plan_refusal_probes(tool: dict[str, Any]) -> list[dict[str, Any]]:
    """handler에 도달하지 않는 required 누락/미지 키 probe를 만든다."""

    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise CoverageError(f"{tool.get('name')}: 최상위 inputSchema가 object가 아닙니다")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
        raise CoverageError(f"{tool.get('name')}: required가 문자열 배열이 아닙니다")
    if required:
        probes = []
        for missing in required:
            # first_missing_required는 존재 여부를 handler/validator보다 먼저 본다.
            # 다른 required는 non-null sentinel로 채워 표적 하나만 누락한다.
            arguments = {key: "__present_only__" for key in required if key != missing}
            probes.append(
                {
                    "probe_kind": "missing_required",
                    "field": missing,
                    "arguments": arguments,
                    "expected_kind": "invalid_argument",
                    "expected_field": missing,
                }
            )
        return probes

    if schema.get("additionalProperties") is not False:
        raise CoverageError(
            f"{tool.get('name')}: required가 없고 최상위 record가 닫혀 있지 않아 "
            "안전한 거부 probe를 만들 수 없습니다"
        )
    return [
        {
            "probe_kind": "unknown_property",
            "field": UNKNOWN_PROBE,
            "arguments": {UNKNOWN_PROBE: True},
            "expected_kind": "invalid_argument",
            "expected_field": UNKNOWN_PROBE,
        }
    ]


def plan_wrong_type_probes(tool: dict[str, Any]) -> list[dict[str, Any]]:
    """모든 top-level required 필드별 wrong-type probe를 만든다."""

    schema = tool["inputSchema"]
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    probes = []
    for field in required:
        property_schema = properties.get(field)
        if not isinstance(property_schema, dict):
            probes.append(
                {
                    "probe_kind": "wrong_type",
                    "field": field,
                    "status": "not_applicable",
                    "reason": "required 필드의 property schema가 없습니다",
                }
            )
            continue
        try:
            arguments = {
                key: _valid_placeholder(properties.get(key, {})) for key in required
            }
            arguments[field] = _invalid_type_value(property_schema)
        except CoverageError as error:
            probes.append(
                {
                    "probe_kind": "wrong_type",
                    "field": field,
                    "status": "not_applicable",
                    "reason": (
                        "JSON Schema 빈 schema는 모든 non-null JSON 값 형식을 의도적으로 "
                        f"허용하므로 wrong-type 범주가 없습니다: {error}"
                    ),
                }
            )
            continue
        probes.append(
            {
                "probe_kind": "wrong_type",
                "field": field,
                "arguments": arguments,
                "expected_kind": "invalid_argument",
                "expected_field": field,
            }
        )
    return probes


def validate_inventory(inventory: dict[str, Any]) -> None:
    if inventory.get("schema_version") != SCHEMA_VERSION:
        raise CoverageError("지원하지 않는 inventory schema_version입니다")
    tools = inventory.get("tools")
    toolsets = inventory.get("toolsets")
    meta_tools = inventory.get("meta_tools")
    if not isinstance(tools, list) or not isinstance(toolsets, dict) or not isinstance(meta_tools, list):
        raise CoverageError("inventory의 tools/toolsets/meta_tools 형식이 잘못되었습니다")

    names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
    if len(names) != len(tools) or not all(isinstance(name, str) for name in names):
        raise CoverageError("이름이 없는 domain tool이 있습니다")
    if len(set(names)) != len(names):
        raise CoverageError("중복 domain tool 이름이 있습니다")

    owned: list[str] = []
    for toolset, members in toolsets.items():
        if not isinstance(toolset, str) or not isinstance(members, list):
            raise CoverageError("toolsets mapping 형식이 잘못되었습니다")
        owned.extend(members)
    if len(owned) != len(set(owned)):
        raise CoverageError("두 toolset이 같은 domain tool을 소유합니다")
    if set(owned) != set(names):
        missing = sorted(set(names) - set(owned))
        extra = sorted(set(owned) - set(names))
        raise CoverageError(f"toolset 소유권 불일치: 미소유={missing}, runtime 미광고={extra}")

    meta_names = [tool.get("name") for tool in meta_tools if isinstance(tool, dict)]
    if len(meta_names) != len(meta_tools) or len(set(meta_names)) != len(meta_names):
        raise CoverageError("meta tool 이름이 없거나 중복되었습니다")
    collision = sorted(set(names) & set(meta_names))
    if collision:
        raise CoverageError(f"domain/meta tool 이름 충돌: {collision}")

    for tool in tools + meta_tools:
        plan_refusal_probes(tool)


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _matching_delimiter(text: str, opening: int, left: str, right: str) -> int | None:
    depth = 0
    index = opening
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "/" and nxt == "*":
                block_comment += 1
                index += 2
                continue
            if char == "*" and nxt == "/":
                block_comment -= 1
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and nxt == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and nxt == "*":
            block_comment = 1
            index += 2
            continue
        if char in ('"', "'"):
            quote = char
            index += 1
            continue
        if char == left:
            depth += 1
        elif char == right:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _rust_files(source_root: Path) -> list[Path]:
    if not source_root.exists():
        return []
    return sorted(
        path
        for path in source_root.rglob("*.rs")
        if "target" not in path.parts and ".git" not in path.parts
    )


def extract_tool_registrations(source_root: Path) -> dict[str, dict[str, Any]]:
    registrations: dict[str, dict[str, Any]] = {}
    for path in _rust_files(source_root):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"tool!\s*\(\s*\"([a-z0-9_]+)\"", text):
            opening = text.find("(", match.start())
            closing = _matching_delimiter(text, opening, "(", ")")
            if closing is None:
                continue
            body = text[opening + 1 : closing]
            handler = re.search(r"\b(handle_[a-z0-9_]+)\b", body)
            name = match.group(1)
            registrations[name] = {
                "path": path,
                "line": _line_number(text, match.start()),
                "handler": handler.group(1) if handler else None,
            }
    return registrations


def extract_test_evidence(source_root: Path) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    pattern = re.compile(
        r"#\[(?:tokio::)?test(?:\([^\]]*\))?\]\s*(?:#\[[^\]]+\]\s*)*"
        r"(?:async\s+)?fn\s+([a-zA-Z0-9_]+)[^{]*\{",
        re.MULTILINE,
    )
    for path in _rust_files(source_root):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            opening = text.find("{", match.start(), match.end())
            closing = _matching_delimiter(text, opening, "{", "}")
            if closing is None:
                continue
            tests.append(
                {
                    "path": path,
                    "line": _line_number(text, match.start()),
                    "name": match.group(1),
                    "body": text[opening + 1 : closing],
                }
            )
    return tests


NEGATIVE_TEST_WORDS = (
    "invalid",
    "reject",
    "refus",
    "missing",
    "malformed",
    "wrong",
    "error",
    "fail",
    "conflict",
    "lock",
    "schema",
    "required",
    "unsupported",
    "unchanged",
    "preserv",
    "no_write",
    "does_not",
)

READBACK_WORDS = (
    "readback",
    "round_trip",
    "roundtrip",
    "persist",
    "reparse",
    "reload",
    "applied",
    "writes",
    "written",
    "output_exists",
)

PRESERVATION_WORDS = (
    "unchanged",
    "byte_identical",
    "byte-identical",
    "preserv",
    "no_write",
    "does_not_modify",
    "original",
    "rollback",
)


def _evidence_for_tool(
    tool: str,
    registration: dict[str, Any] | None,
    tests: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    handler = registration.get("handler") if registration else None
    found: list[dict[str, Any]] = []
    for test in tests:
        body = test["body"]
        name = test["name"]
        if (
            tool in name
            or f'"{tool}"' in body
            or (handler is not None and re.search(rf"\b{re.escape(handler)}\b", body))
        ):
            found.append(
                {
                    "file": str(test["path"]),
                    "line": test["line"],
                    "test": name,
                }
            )
    normal = [
        item
        for item in found
        if not any(word in item["test"].lower() for word in NEGATIVE_TEST_WORDS)
    ]
    readback = [
        item
        for item in found
        if any(word in item["test"].lower() for word in READBACK_WORDS)
    ]
    preservation = [
        item
        for item in found
        if any(word in item["test"].lower() for word in PRESERVATION_WORDS)
    ]
    return {
        "all_candidates": found,
        "normal_candidates": normal,
        "readback_candidates": readback,
        "preservation_candidates": preservation,
    }


DESIGN_WRITE_PREFIXES = (
    "add_",
    "set_",
    "edit_",
    "move_",
    "rotate_",
    "delete_",
    "place_",
    "connect_",
    "batch_",
    "create_",
    "rename_",
    "apply_",
    "fix_",
    "import_",
    "route_",
    "refill_",
    "assign_",
    "duplicate_",
    "update_",
    "repair_",
    "mutate_",
    "save_",
    "write_",
)


def classify_operation(name: str) -> str:
    if name.startswith("batch_get_") or name.startswith(
        (
            "get_",
            "list_",
            "search_",
            "check_",
            "audit_",
            "validate_",
            "score_",
            "estimate_",
            "compare_",
            "resolve_",
            "suggest_",
            "run_",
        )
    ):
        return "read_or_check"
    if name in {"load_project_config", "get_effective_config"}:
        return "read_or_check"
    if name == "load_user_config":
        return "state_or_design_write"  # absent-file first load persists defaults
    if name.startswith(DESIGN_WRITE_PREFIXES):
        return "state_or_design_write"
    if name.startswith(("export_", "generate_", "render_", "snapshot_", "download_")):
        return "artifact_or_cache_write"
    if name.startswith(("open_",)):
        return "external_process_or_state"
    return "read_or_check"


def classify_external_requirements(toolset: str, name: str, description: str) -> list[str]:
    haystack = f"{name} {description}".lower()
    requirements: set[str] = set()
    if toolset.startswith("pcb_") or toolset in {"editor_navigation", "placement", "verification"}:
        if any(word in haystack for word in ("ipc", "live", "running kicad", "editor", "board")):
            requirements.add("ipc")
    if any(word in haystack for word in ("kicad-cli", " gerber", " pdf", " svg", "drc", "erc")):
        requirements.add("kicad_cli")
    if any(word in haystack for word in ("viewer", "launch", "ui control", "window")):
        requirements.add("gui_display")
    if toolset == "integration" or any(
        word in haystack for word in ("jlcpcb", "freerouting", "datasheet", "download")
    ):
        requirements.add("network_or_external_service")
    if "jlcpcb" in haystack:
        requirements.add("jlcpcb_catalogue")
    if toolset == "library" or "library" in haystack or "footprint" in haystack or "symbol" in haystack:
        requirements.add("kicad_libraries")
    if classify_operation(name) != "read_or_check" or any(
        word in haystack for word in ("path", "file", "saved")
    ):
        requirements.add("filesystem")
    return sorted(requirements)


def build_matrix(inventory: dict[str, Any], source_root: Path) -> list[dict[str, Any]]:
    validate_inventory(inventory)
    owner = {
        tool: toolset
        for toolset, members in inventory["toolsets"].items()
        for tool in members
    }
    registrations = extract_tool_registrations(source_root)
    tests = extract_test_evidence(source_root)
    rows = []
    for tool in sorted(inventory["tools"], key=lambda item: item["name"]):
        name = tool["name"]
        toolset = owner[name]
        operation = classify_operation(name)
        evidence = _evidence_for_tool(name, registrations.get(name), tests)
        normal = evidence["normal_candidates"]
        readback = evidence["readback_candidates"]
        preservation = evidence["preservation_candidates"]
        needs_write_evidence = operation in {"state_or_design_write", "artifact_or_cache_write"}
        properties = tool["inputSchema"].get("properties", {})
        non_null_json_types = {"string", "number", "boolean", "array", "object"}
        any_value_fields = []
        for field in tool["inputSchema"].get("required", []):
            field_schema = properties.get(field)
            if not isinstance(field_schema, dict):
                continue
            allowed = _allowed_types(field_schema)
            if not allowed or allowed == non_null_json_types:
                any_value_fields.append(field)
        any_value_contract: dict[str, Any]
        if any_value_fields:
            any_value_contract = {
                "status": "intentional_any_non_null_json",
                "fields": any_value_fields,
                "allowed_by_schema_and_handler": [
                    "string",
                    "number",
                    "boolean",
                    "array",
                    "object",
                ],
                "null_semantics": "required 값 누락으로 거부",
                "normal_acceptance_evidence": "static_candidates_only",
                "static_candidates": evidence["all_candidates"],
                "explicit_kind_test_gaps": (
                    []
                    if name in {"save_user_config", "save_project_config"}
                    and any(
                        candidate["test"]
                        in {
                            "save_user_config_accepts_each_non_null_json_kind_and_reads_it_back",
                            "save_project_config_accepts_each_non_null_json_kind_and_reads_it_back",
                        }
                        for candidate in evidence["all_candidates"]
                    )
                    else ["number", "boolean", "array"]
                ),
                "known_key_domain_validation": (
                    "not_implemented_generic_dot_path_store"
                    if name in {"save_user_config", "save_project_config"}
                    else "not_assessed"
                ),
                "warning": (
                    "정적 테스트 후보는 현재 실행 성공을 단독 증명하지 않습니다."
                ),
            }
        else:
            any_value_contract = {"status": "not_applicable", "fields": []}
        rows.append(
            {
                "tool": name,
                "toolset": toolset,
                "operation": operation,
                "schema_registered": True,
                "required_fields": list(tool["inputSchema"].get("required", [])),
                "refusal_validation": {"status": "not_run", "probes": 0},
                "wrong_type_validation": {"status": "not_run", "probes": 0},
                "any_value_contract": any_value_contract,
                "normal_behavior": {
                    "status": "static_candidate_only" if normal else "missing",
                    "evidence": normal,
                    "warning": "테스트명/본문의 정적 연결 후보이며 이번 실행 성공 증거가 아닙니다",
                },
                "write_readback": {
                    "required": needs_write_evidence,
                    "status": (
                        "static_candidate_only"
                        if readback
                        else ("missing" if needs_write_evidence else "not_applicable")
                    ),
                    "evidence": readback,
                },
                "original_preservation": {
                    "required": operation == "state_or_design_write",
                    "status": (
                        "static_candidate_only"
                        if preservation
                        else ("missing" if operation == "state_or_design_write" else "not_applicable")
                    ),
                    "evidence": preservation,
                },
                "external_requirements": classify_external_requirements(
                    toolset, name, tool.get("description", "")
                ),
                "external_runtime_validation": "not_run",
                "all_test_candidates": evidence["all_candidates"],
            }
        )
    return rows


def apply_probe_results(rows: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        if not result.get("meta_tool"):
            by_tool.setdefault(result["tool"], []).append(result)
    for row in rows:
        probes = by_tool.get(row["tool"], [])
        refusal = [p for p in probes if p["probe_kind"] != "wrong_type"]
        wrong = [p for p in probes if p["probe_kind"] == "wrong_type"]
        row["refusal_validation"] = {
            "status": "passed" if refusal and all(p["passed"] for p in refusal) else "failed",
            "probes": len(refusal),
            "failed": [p for p in refusal if not p["passed"]],
        }
        if not row["required_fields"]:
            wrong_status = "not_applicable"
        elif wrong and all(p["passed"] for p in wrong):
            wrong_status = (
                "passed_with_any_value_fields"
                if any(p.get("not_applicable") for p in wrong)
                else "passed"
            )
        else:
            wrong_status = "failed"
        row["wrong_type_validation"] = {
            "status": wrong_status,
            "probes": len(wrong),
            "failed": [p for p in wrong if not p["passed"]],
            "not_applicable_fields": [
                p["field"] for p in wrong if p.get("not_applicable")
            ],
        }


def merge_functional_evidence(
    rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    source: str,
    *,
    expected_binary_sha256: str,
) -> None:
    """실제 postcondition이 모두 통과한 case만 정상행동 ledger로 승격한다."""

    by_tool = {row["tool"]: row for row in rows}
    for record in records:
        tool = record.get("tool")
        row = by_tool.get(tool)
        if row is None:
            continue
        verdict = str(record.get("verdict", "")).lower()
        if (
            verdict in {"pass", "passed"}
            and record.get("binary_sha256") != expected_binary_sha256
        ):
            raise CoverageError(
                "정상 기능 증거의 binary SHA-256이 inventory와 다릅니다: "
                f"tool={tool}, source={source}, "
                f"expected={expected_binary_sha256}, "
                f"actual={record.get('binary_sha256')}"
            )
        compact = {
            "source": source,
            "case_id": record.get("case_id"),
            "verdict": record.get("verdict"),
            "source_authority": record.get("source_authority"),
            "binary_sha256": record.get("binary_sha256"),
            "postconditions": record.get("postconditions", []),
            "caveats": record.get("caveats", []),
        }
        row.setdefault("functional_evidence", []).append(compact)
        postconditions = record.get("postconditions")
        passed = (
            verdict in {"pass", "passed"}
            and record.get("is_error") is not True
            and isinstance(postconditions, list)
            and bool(postconditions)
            and all(item.get("passed") is True for item in postconditions)
        )
        if not passed:
            continue
        row["normal_behavior"] = {
            "status": "passed",
            "evidence": [compact],
            "warning": None,
        }
        names = [str(item.get("name", "")).lower() for item in postconditions]
        if row["write_readback"]["required"] and any(
            any(
                token in name
                for token in (
                    "readback",
                    "artifact",
                    "renamed",
                    "created",
                    "snapshot",
                    "project_file",
                    "siblings_exist",
                    "old_absent",
                )
            )
            for name in names
        ):
            row["write_readback"] = {
                "required": True,
                "status": "passed",
                "evidence": [compact],
            }
        if row["original_preservation"]["required"] and any(
            any(token in name for token in ("unchanged", "preserv", "unrelated", "보존"))
            for name in names
        ):
            row["original_preservation"] = {
                "required": True,
                "status": "passed",
                "evidence": [compact],
            }
        authority = record.get("source_authority")
        covered_by_authority = {
            "saved_file": {"filesystem"},
            "file": {"filesystem"},
            "local_sqlite_fixture": {"filesystem", "jlcpcb_catalogue"},
            "kicad_cli": {"filesystem", "kicad_cli"},
            "kicad-cli": {"filesystem", "kicad_cli"},
            "actual_kicad_cli": {"filesystem", "kicad_cli"},
            "kicad_cli_and_saved_file": {"filesystem", "kicad_cli"},
            "kicad_cli_validated_saved_file": {"filesystem", "kicad_cli"},
            "ipc": {"ipc", "gui_display"},
            "live_ipc": {"ipc", "gui_display"},
            "live_kicad_ipc": {"ipc", "gui_display"},
            "live_ipc_or_saved_file_as_handler_reports": {
                "ipc",
                "gui_display",
                "filesystem",
            },
            "actual_network_service": {"network_or_external_service"},
            "actual_network_service_and_saved_file": {
                "network_or_external_service",
                "filesystem",
            },
            "local_freerouting_native_mcp": {
                "network_or_external_service",
                "filesystem",
            },
            "local_freerouting_native_mcp_probe": {"network_or_external_service"},
        }.get(authority, set())
        covered = set(row.get("external_runtime_covered", []))
        covered.update(covered_by_authority)
        row["external_runtime_covered"] = sorted(covered)
        required = set(row["external_requirements"])
        missing = sorted(required - covered)
        row["external_runtime_missing"] = missing
        if not required or not missing:
            row["external_runtime_validation"] = "passed"
        elif covered:
            row["external_runtime_validation"] = "partial"


def verify_matrix(
    inventory: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    require_refusal_pass: bool = False,
    require_wrong_type_pass: bool = False,
) -> None:
    validate_inventory(inventory)
    expected = {tool["name"] for tool in inventory["tools"]}
    actual = [row.get("tool") for row in rows]
    if len(actual) != len(set(actual)):
        raise CoverageError("행렬에 중복 tool row가 있습니다")
    if set(actual) != expected:
        raise CoverageError(
            f"행렬 coverage 불일치: 누락={sorted(expected - set(actual))}, "
            f"초과={sorted(set(actual) - expected)}"
        )
    if require_refusal_pass:
        failed = [
            row["tool"]
            for row in rows
            if row.get("refusal_validation", {}).get("status") != "passed"
        ]
        if failed:
            raise CoverageError(f"거부 입력 runtime probe 미통과: {failed}")
    if require_wrong_type_pass:
        failed = [
            row["tool"]
            for row in rows
            if row.get("wrong_type_validation", {}).get("status")
            not in {"passed", "passed_with_any_value_fields", "not_applicable"}
        ]
        if failed:
            raise CoverageError(f"wrong-type runtime probe 미통과: {failed}")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = {
        "normal_behavior": sum(row["normal_behavior"]["status"] != "passed" for row in rows),
        "write_readback": sum(
            row["write_readback"]["required"]
            and row["write_readback"]["status"] != "passed"
            for row in rows
        ),
        "original_preservation": sum(
            row["original_preservation"]["required"]
            and row["original_preservation"]["status"] != "passed"
            for row in rows
        ),
        "external_runtime": sum(
            bool(row["external_requirements"])
            and row["external_runtime_validation"] != "passed"
            for row in rows
        ),
        "refusal_validation": sum(
            row["refusal_validation"]["status"] not in {"passed"} for row in rows
        ),
        "wrong_type_validation": sum(
            row["wrong_type_validation"]["status"]
            not in {"passed", "passed_with_any_value_fields", "not_applicable"}
            for row in rows
        ),
    }
    return {
        "domain_tool_count": len(rows),
        "gaps": gaps,
        "all_features_integrity_claim_supported": not any(gaps.values()),
        "interpretation": (
            "도구 등록 및 거부 입력 통과는 정상 동작/GUI/IPC/CLI/외부 서비스 성공을 뜻하지 않습니다."
        ),
    }


def _registry_ownership(source_root: Path) -> dict[str, list[str]]:
    registry = source_root / "crates/konnect-core/src/router/registry.rs"
    tools_dir = source_root / "crates/konnect-core/src/tools"
    text = registry.read_text(encoding="utf-8")
    mappings = re.findall(
        r'"([a-z0-9_]+)"\s*=>\s*Some\(([a-z0-9_]+)::tools\(\)\)', text
    )
    if not mappings:
        raise CoverageError("registry.rs에서 toolset builder mapping을 찾지 못했습니다")
    registrations = extract_tool_registrations(source_root)
    by_file = {name: Path(data["path"]).stem for name, data in registrations.items()}
    ownership: dict[str, list[str]] = {}
    for toolset, module in mappings:
        main_path = tools_dir / f"{module}.rs"
        main_text = main_path.read_text(encoding="utf-8")
        modules = {module}
        modules.update(
            re.findall(r"super::([a-z0-9_]+)::tool\(\)", main_text)
        )
        ownership[toolset] = sorted(name for name, source_module in by_file.items() if source_module in modules)
    return ownership


def _audit_refusal_guard(source_root: Path) -> dict[str, Any]:
    path = source_root / "crates/konnect-core/src/mcp/handler.rs"
    text = path.read_text(encoding="utf-8")
    domain_start = text.find("if let Some(tool_def) = tool_def")
    missing = text.find("first_missing_required", domain_start)
    validator = text.find("tool_def.input_validator.validate", missing)
    handler = text.find("(tool_def.handler)", validator)
    meta_validator = text.find("self.meta_input_validators.get")
    meta_handler = text.find("handle_meta_tool_with_reload", meta_validator)
    if not (0 <= domain_start < missing < validator < handler):
        raise CoverageError("domain refusal guard가 handler보다 먼저 실행됨을 source에서 증명하지 못했습니다")
    if not (0 <= meta_validator < meta_handler):
        raise CoverageError("meta schema validator가 handler보다 먼저 실행됨을 source에서 증명하지 못했습니다")
    return {
        "handler_source": str(path),
        "handler_source_sha256": sha256_file(path),
        "domain_guard_order": [
            "first_missing_required",
            "input_validator.validate",
            "tool_def.handler",
        ],
        "meta_guard_order": ["meta_input_validator.validate", "handle_meta_tool"],
    }


def _tool_error(result: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    body = result.get("result", result)
    is_error = body.get("isError") is True
    content = body.get("content", [])
    if not content or not isinstance(content[0], dict):
        return is_error, None, None
    text = content[0].get("text")
    if not isinstance(text, str):
        return is_error, None, None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return is_error, None, None
    error = parsed.get("error", {})
    return is_error, error.get("kind"), error.get("field")


def filesystem_manifest(paths: list[Path]) -> dict[str, Any]:
    """거부 probe가 보호 대상 파일을 바꾸지 않았음을 digest로 비교한다."""

    manifest: dict[str, Any] = {}
    for root in paths:
        key = str(root)
        if not root.exists() and not root.is_symlink():
            manifest[key] = {"kind": "absent"}
            continue
        if root.is_symlink():
            manifest[key] = {"kind": "symlink", "target": os.readlink(root)}
            continue
        if root.is_file():
            manifest[key] = {
                "kind": "file",
                "size": root.stat().st_size,
                "sha256": sha256_file(root),
            }
            continue
        entries: dict[str, Any] = {}
        for path in sorted(root.rglob("*")):
            relative = str(path.relative_to(root))
            if path.is_symlink():
                entries[relative] = {"kind": "symlink", "target": os.readlink(path)}
            elif path.is_file():
                entries[relative] = {
                    "kind": "file",
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            elif path.is_dir():
                entries[relative] = {"kind": "dir"}
        manifest[key] = {"kind": "directory", "entries": entries}
    return manifest


class StdioMcp:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str], stderr_path: Path):
        self._stderr = stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            bufsize=1,
        )

    def request(self, identifier: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.process.stdin is not None and self.process.stdout is not None
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            request["params"] = params
        self.process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise CoverageError(
                    f"MCP 서버가 응답 전에 종료했습니다: rc={self.process.poll()} method={method}"
                )
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise CoverageError(f"stdout protocol 오염: {error}: {line!r}") from error
            if response.get("id") == identifier:
                return response

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        assert self.process.stdin is not None
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def close(self) -> int:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            return self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                return self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                return self.process.wait(timeout=5)
        finally:
            self._stderr.close()


def capture_runtime(root: Path, output_dir: Path, execute_probes: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_root = root / "upstream/konnect"
    wrapper = root / "scripts/run-konnect.sh"
    binary = source_root / "target/release/konnect"
    if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
        raise CoverageError(f"안전 wrapper를 실행할 수 없습니다: {wrapper}")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise CoverageError(f"release binary를 실행할 수 없습니다: {binary}")

    build_inputs = [source_root / "Cargo.toml", source_root / "Cargo.lock"]
    build_inputs.extend(
        path
        for path in (source_root / "crates").rglob("*")
        if path.is_file()
        and "schematic-viewer" not in path.parts
        and path.suffix in {".rs", ".toml", ".proto"}
    )
    newest_input = max(build_inputs, key=lambda path: path.stat().st_mtime_ns)
    if binary.stat().st_mtime_ns < newest_input.stat().st_mtime_ns:
        raise CoverageError(
            "release binary가 현재 source보다 오래되었습니다: "
            f"binary={binary}, newest_input={newest_input}. --locked release build 후 재시도하세요"
        )

    guard = _audit_refusal_guard(source_root)
    ownership = _registry_ownership(source_root)
    worktree_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=source_root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir = output_dir / "state"
    project_dir = output_dir / "empty-project"
    runtime_home = output_dir / "runtime-home"
    for transient in (state_dir, project_dir, runtime_home):
        if transient.exists():
            shutil.rmtree(transient)
    state_dir.mkdir(exist_ok=True)
    project_dir.mkdir(exist_ok=True)
    config = output_dir / "catalogue-konnect.toml"
    config.write_text(
        "\n".join(
            [
                'kicad_cli = "/nonexistent/konnect-catalogue-kicad-cli"',
                'kicad_binary = "/nonexistent/konnect-catalogue-kicad"',
                f'project_dir = {json.dumps(str(project_dir))}',
                'ipc_address = "ipc:///tmp/konnect-catalogue-no-such.sock"',
                'transport = "stdio"',
                'log_level = "error"',
                "auto_load_toolsets = false",
                "eager_toolsets = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    env["KICAD_API_SOCKET"] = "ipc:///tmp/konnect-catalogue-no-such.sock"
    env["KONNECT_STATE_DIR"] = str(state_dir)
    env["KONNECT_RUNTIME_HOME"] = str(runtime_home)

    server = StdioMcp(
        [str(wrapper), "--config", str(config)], root, env, output_dir / "server.stderr.log"
    )
    probes: list[dict[str, Any]] = []
    try:
        initialized = server.request(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-catalogue-auditor", "version": "1"},
            },
        )
        if "error" in initialized:
            raise CoverageError(f"initialize 실패: {initialized['error']}")
        server.notify("notifications/initialized")
        listing = server.request(2, "tools/list", {})
        listed = listing.get("result", {}).get("tools")
        if not isinstance(listed, list):
            raise CoverageError("tools/list에 tools 배열이 없습니다")
        toolbox_response = server.request(
            3,
            "tools/call",
            {"name": "list_toolboxes", "arguments": {}},
        )
        toolbox_result = toolbox_response.get("result", {})
        toolbox_content = toolbox_result.get("content", [])
        try:
            runtime_toolboxes = json.loads(toolbox_content[0]["text"])
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise CoverageError(f"list_toolboxes 응답을 해석할 수 없습니다: {error}") from error
        if toolbox_result.get("isError") is True:
            raise CoverageError(f"list_toolboxes가 실패했습니다: {runtime_toolboxes}")

        registered_names = {name for members in ownership.values() for name in members}
        domain = [tool for tool in listed if tool.get("name") in registered_names]
        meta = [tool for tool in listed if tool.get("name") not in registered_names]
        inventory = {
            "schema_version": SCHEMA_VERSION,
            "captured_at_unix_ms": int(time.time() * 1000),
            "source": {
                "commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=source_root,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip(),
                "binary": str(binary),
                "binary_sha256": sha256_file(binary),
                "binary_mtime_ns": binary.stat().st_mtime_ns,
                "newest_build_input": str(newest_input),
                "newest_build_input_mtime_ns": newest_input.stat().st_mtime_ns,
                "build_inputs_sha256": sha256_paths(source_root, build_inputs),
                "worktree_status": worktree_status,
                **guard,
            },
            "toolsets": ownership,
            "runtime_toolboxes": runtime_toolboxes,
            "tools": domain,
            "meta_tools": meta,
            "counts": {
                "toolsets": len(ownership),
                "domain_tools": len(domain),
                "meta_tools": len(meta),
                "tools_list_total": len(listed),
            },
            "isolation": {
                "launcher": str(wrapper),
                "state_dir": str(state_dir),
                "project_dir": str(project_dir),
                "runtime_home": str(runtime_home),
                "ipc_address": "ipc:///tmp/konnect-catalogue-no-such.sock",
                "display": "unset",
            },
        }
        declared = {
            item["name"]: item["tool_count"]
            for item in runtime_toolboxes.get("toolsets", [])
            if isinstance(item, dict) and "name" in item and "tool_count" in item
        }
        source_counts = {name: len(members) for name, members in ownership.items()}
        if declared != source_counts or runtime_toolboxes.get("total_tools") != len(domain):
            raise CoverageError(
                "list_toolboxes/tools-list/source registry count가 다릅니다: "
                f"runtime={declared}, source={source_counts}, "
                f"runtime_total={runtime_toolboxes.get('total_tools')}, tools_list={len(domain)}"
            )
        validate_inventory(inventory)

        if execute_probes:
            protected_paths = [
                project_dir,
                runtime_home / ".konnect/config.json",
                runtime_home / ".config/konnect/config.json",
            ]
            protected_before = filesystem_manifest(protected_paths)
            identifier = 1000
            for meta_tool, tool in [(False, t) for t in domain] + [(True, t) for t in meta]:
                planned = plan_refusal_probes(tool) + plan_wrong_type_probes(tool)
                for probe in planned:
                    result = {
                        "tool": tool["name"],
                        "meta_tool": meta_tool,
                        "probe_kind": probe["probe_kind"],
                        "field": probe.get("field"),
                    }
                    if probe.get("status") == "not_applicable":
                        result.update(
                            {
                                "passed": True,
                                "not_applicable": True,
                                "reason": probe["reason"],
                                "executed": False,
                                "arguments": None,
                                "response": None,
                            }
                        )
                        probes.append(result)
                        continue
                    response = server.request(
                        identifier,
                        "tools/call",
                        {
                            "name": tool["name"],
                            "arguments": probe["arguments"],
                        },
                    )
                    identifier += 1
                    is_error, kind, field = _tool_error(response)
                    expected_field = probe.get("expected_field")
                    result.update(
                        {
                            "executed": True,
                            "passed": bool(
                                is_error
                                and kind == probe["expected_kind"]
                                and field == expected_field
                            ),
                            "observed_is_error": is_error,
                            "observed_kind": kind,
                            "observed_field": field,
                            "expected_kind": probe["expected_kind"],
                            "expected_field": expected_field,
                            "arguments": probe["arguments"],
                            "response": response,
                        }
                    )
                    probes.append(result)
            protected_after = filesystem_manifest(protected_paths)
            inventory["refusal_probe_preservation"] = {
                "protected_paths": [str(path) for path in protected_paths],
                "before": protected_before,
                "after": protected_after,
                "unchanged": protected_before == protected_after,
                "observer_state_note": (
                    "KONNECT_STATE_DIR의 calls.jsonl은 observability 계약상 증가하므로 "
                    "보호 대상 digest에서 제외했습니다."
                ),
            }
            if protected_before != protected_after:
                raise CoverageError("거부 probe 전후 보호 대상 filesystem digest가 달라졌습니다")
        else:
            inventory["refusal_probe_preservation"] = {"status": "not_run"}
    finally:
        rc = server.close()
        if rc != 0 and sys.exc_info()[0] is None:
            raise CoverageError(f"MCP 서버 종료 코드가 0이 아닙니다: {rc}")
    return inventory, probes


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "toolset",
        "tool",
        "operation",
        "required_fields",
        "refusal_validation",
        "wrong_type_validation",
        "normal_behavior",
        "write_readback",
        "original_preservation",
        "external_requirements",
        "external_runtime_validation",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "toolset": row["toolset"],
                    "tool": row["tool"],
                    "operation": row["operation"],
                    "required_fields": ",".join(row["required_fields"]),
                    "refusal_validation": row["refusal_validation"]["status"],
                    "wrong_type_validation": row["wrong_type_validation"]["status"],
                    "normal_behavior": row["normal_behavior"]["status"],
                    "write_readback": row["write_readback"]["status"],
                    "original_preservation": row["original_preservation"]["status"],
                    "external_requirements": ",".join(row["external_requirements"]),
                    "external_runtime_validation": row["external_runtime_validation"],
                }
            )


def write_markdown(path: Path, inventory: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Konnect MCP 공개 도구 coverage 감사",
        "",
        "## 판정",
        "",
        f"- 공개 domain tool: {summary['domain_tool_count']}",
        f"- toolset: {inventory['counts']['toolsets']}",
        f"- meta tool: {inventory['counts']['meta_tools']}",
        f"- 전체 기능 무결성 주장 가능: `{str(summary['all_features_integrity_claim_supported']).lower()}`",
        f"- 해석: {summary['interpretation']}",
        "",
        "## 미충족 수",
        "",
        "| 항목 | 수 |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in summary["gaps"].items())
    lines.extend(
        [
            "",
            "## 범위 경고",
            "",
            "- runtime probe는 schema 경계의 거부를 확인하며 정상 handler 동작을 실행하지 않습니다.",
            "- 정적 test 후보는 이번 실행의 성공 증거가 아닙니다.",
            "- GUI, 실제 KiCad IPC, kicad-cli, 네트워크, JLCPCB/Freerouting은 별도 acceptance가 필요합니다.",
            "",
            "## 도구별 행렬",
            "",
            "| toolset | tool | 동작 | 거부 | wrong type | 정상 후보 | readback | 원본 보존 | 외부 조건 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| {toolset} | `{tool}` | {operation} | {refusal} | {wrong} | {normal} | "
            "{readback} | {preserve} | {external} |".format(
                toolset=row["toolset"],
                tool=row["tool"],
                operation=row["operation"],
                refusal=row["refusal_validation"]["status"],
                wrong=row["wrong_type_validation"]["status"],
                normal=row["normal_behavior"]["status"],
                readback=row["write_readback"]["status"],
                preserve=row["original_preservation"]["status"],
                external=",".join(row["external_requirements"]) or "없음",
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_capture(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = Path(args.output_dir).resolve()
    inventory, probes = capture_runtime(root, output, args.execute_refusal_probes)
    rows = build_matrix(inventory, root / "upstream/konnect")
    if args.execute_refusal_probes:
        apply_probe_results(rows, probes)
    verify_matrix(inventory, rows)
    summary = summarize(rows)
    output.mkdir(parents=True, exist_ok=True)
    (output / "inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "probe-results.json").write_text(
        json.dumps(probes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "coverage-matrix.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv(output / "coverage-matrix.csv", rows)
    write_markdown(output / "README.md", inventory, rows, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.execute_refusal_probes and any(not result["passed"] for result in probes):
        return 4
    return 3 if args.require_complete_behavior and not summary["all_features_integrity_claim_supported"] else 0


def command_verify(args: argparse.Namespace) -> int:
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    rows = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    verify_matrix(
        inventory,
        rows,
        require_refusal_pass=args.require_refusal_pass,
        require_wrong_type_pass=args.require_wrong_type_pass,
    )
    summary = summarize(rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 3 if args.require_complete_behavior and not summary["all_features_integrity_claim_supported"] else 0


def command_merge(args: argparse.Namespace) -> int:
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    rows = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    verify_matrix(inventory, rows)
    for evidence_path in args.evidence_jsonl:
        records = [
            json.loads(line)
            for line in Path(evidence_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        merge_functional_evidence(
            rows,
            records,
            evidence_path,
            expected_binary_sha256=inventory["source"]["binary_sha256"],
        )
    summary = summarize(rows)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage-matrix.merged.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (output / "summary.merged.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv(output / "coverage-matrix.merged.csv", rows)
    write_markdown(output / "MERGED.md", inventory, rows, summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="격리된 runtime inventory와 coverage 행렬 생성")
    capture.add_argument("--root", default=str(ROOT))
    capture.add_argument("--output-dir", required=True)
    capture.add_argument("--execute-refusal-probes", action="store_true")
    capture.add_argument("--require-complete-behavior", action="store_true")
    capture.set_defaults(func=command_capture)

    verify = subparsers.add_parser("verify", help="저장된 inventory와 행렬의 누락 검사")
    verify.add_argument("--inventory", required=True)
    verify.add_argument("--matrix", required=True)
    verify.add_argument("--require-refusal-pass", action="store_true")
    verify.add_argument("--require-wrong-type-pass", action="store_true")
    verify.add_argument("--require-complete-behavior", action="store_true")
    verify.set_defaults(func=command_verify)
    merge = subparsers.add_parser("merge", help="기능 JSONL을 fail-closed 카탈로그 ledger에 합성")
    merge.add_argument("--inventory", required=True)
    merge.add_argument("--matrix", required=True)
    merge.add_argument("--evidence-jsonl", action="append", required=True)
    merge.add_argument("--output-dir", required=True)
    merge.set_defaults(func=command_merge)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except CoverageError as error:
        print(f"카탈로그 검증 실패: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
