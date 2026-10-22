#!/usr/bin/env python3
# 용도: 명시 project root의 저장된 회로도에서 native·MCP 증거를 새 경로에 수집하고 표준 검증기를 실행한다.
"""이식 가능한 회로도 정적 증거 수집기.

이 수집기는 CAD 원문을 생성하거나 수정하지 않는다. GUI 저장·재열기 영수증,
전페이지 육안 검토, 동적 전기 성능, PCB·제조·통전 합격도 만들지 않는다.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
import xml.etree.ElementTree as ET

import verify_quality as verifier
import package_identity
from guarded_mcp import AdapterError as GuardedPolicyError, ProjectPolicy


class CollectorError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectorError(message)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strict_loads(text: str, *, context: str, reject_null: bool = True) -> Any:
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise CollectorError(f"{context} JSON duplicate key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise CollectorError(f"{context} JSON nonfinite number: {value}")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise CollectorError(f"{context} JSON 해석 실패: {exc}") from exc

    def walk(item: Any, location: str) -> None:
        if item is None and reject_null:
            raise CollectorError(f"{context} JSON null/unknown 금지: {location}")
        if isinstance(item, float) and not math.isfinite(item):
            raise CollectorError(f"{context} JSON nonfinite number: {location}")
        if isinstance(item, dict):
            for key, child in item.items():
                walk(child, f"{location}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{location}[{index}]")

    walk(value, "$")
    return value


def write_json(path: Path, value: Any) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def write_text(path: Path, value: str) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def resolve_executable(raw: str, *, label: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute() or len(candidate.parts) > 1:
        require(candidate.is_absolute(), f"{label} path는 absolute여야 함")
        path = candidate
    else:
        found = shutil.which(raw)
        require(found is not None, f"{label}를 PATH에서 찾지 못함: {raw}")
        path = Path(found)
    require(path.is_file() and os.access(path, os.X_OK), f"{label} 실행 파일 누락/비실행: {path}")
    return path.resolve()


def absolute_file(raw: Path, *, label: str, executable: bool = False) -> Path:
    require(raw.is_absolute(), f"{label}는 absolute path여야 함")
    require(raw.is_file() and not raw.is_symlink(), f"{label} 파일 누락 또는 symbolic link: {raw}")
    if executable:
        require(os.access(raw, os.X_OK), f"{label}가 실행 가능하지 않음: {raw}")
    return raw.resolve()


def absolute_directory(raw: Path, *, label: str) -> Path:
    require(raw.is_absolute(), f"{label}는 absolute path여야 함")
    require(raw.is_dir() and not raw.is_symlink(), f"{label} directory 누락 또는 symbolic link: {raw}")
    return raw.resolve()


def parse_metadata(path: Path) -> tuple[list[list[float]], list[dict[str, Any]]]:
    """정식 조회가 없는 top-level junction/text만 source에서 읽는다."""
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+',
                        path.read_text(encoding="utf-8"))
    stack: list[list[Any]] = []
    roots: list[list[Any]] = []
    for token in tokens:
        if token == "(":
            node: list[Any] = []
            if stack:
                stack[-1].append(node)
            else:
                roots.append(node)
            stack.append(node)
        elif token == ")":
            require(bool(stack), f"source metadata 괄호 불일치: {path}")
            stack.pop()
        else:
            require(bool(stack), f"source metadata 토큰 위치 오류: {path}")
            stack[-1].append(json.loads(token) if token.startswith('"') else token)
    require(not stack and len(roots) == 1 and roots[0] and roots[0][0] == "kicad_sch",
            f"source metadata root 불일치: {path}")
    junctions: list[list[float]] = []
    texts: list[dict[str, Any]] = []
    for node in roots[0][1:]:
        if not isinstance(node, list) or not node or node[0] not in {"junction", "text"}:
            continue
        fields = {item[0]: item[1:] for item in node[1:] if isinstance(item, list) and item}
        if node[0] == "junction":
            require("at" in fields and len(fields["at"]) >= 2,
                    f"junction at 누락: {path}")
            junctions.append([float(value) for value in fields["at"][:2]])
        else:
            require(len(node) >= 2 and "at" in fields, f"text 필드 누락: {path}")
            texts.append({"text": node[1],
                          "at": [float(value) for value in fields["at"]],
                          "uuid": fields.get("uuid", [""])[0]})
    return junctions, texts


def editor_locks(project_root: Path) -> list[Path]:
    patterns = ("~*.lck", "*.kicad_sch.lck", "*.kicad_pcb.lck")
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in project_root.rglob(pattern)
                     if path.exists() or path.is_symlink())
    return sorted(found)


def source_hashes(project_root: Path, semantic: dict[str, Any]) -> dict[str, str]:
    items = semantic["required_source_files"]
    require(isinstance(items, list) and items and len(items) == len(set(items)),
            "required_source_files 누락/중복")
    result = {}
    for raw in items:
        require(isinstance(raw, str) and raw, "required_source_files 항목 타입 불일치")
        path = verifier.safe_project_path(project_root, raw, label="required source")
        result[raw] = digest(path)
    return result


def assert_stable(project_root: Path, semantic: dict[str, Any], before: dict[str, str],
                  *, phase: str) -> None:
    after = source_hashes(project_root, semantic)
    require(after == before, f"{phase} 도중 required_source_files 변경: before={before}, after={after}")
    locks = editor_locks(project_root)
    require(not locks, f"{phase} 도중 active editor lock 발견: {', '.join(map(str, locks))}")


def capture_plan_binding(project_root: Path) -> tuple[ProjectPolicy, dict[str, Any]]:
    try:
        policy = ProjectPolicy(project_root, workspace_root=project_root)
        policy._capture_all_write_plans()
        plans, common = policy._assert_write_plans_unchanged()
    except GuardedPolicyError as exc:
        raise CollectorError(f"plan-index/plan preflight 실패: {exc}") from exc
    require(common is not None, "plan-index common_plan 증거 누락")
    binding = {
        "schema_version": 1,
        "plan_index": {
            "path": "plan-index.json",
            "sha256": policy.index_sha256,
            "size": len(policy.index_bytes),
        },
        "mode": policy.mode,
        "project_stem": policy.project_stem,
        "require_all_plans_before_write": policy.require_all_plans_before_write,
        "allowed_files": sorted(policy.allowed_files),
        "read_only_files": sorted(policy.read_only_files),
        "plans": [{"schematic": row["schematic"], "path": row["plan"],
                   "sha256": row["sha256"], "size": row["size"]} for row in plans],
        "common_plan": {"path": common["plan"], "sha256": common["sha256"],
                        "size": common["size"]},
    }
    return policy, binding


def assert_plan_binding(policy: ProjectPolicy, before: dict[str, Any], *, phase: str) -> None:
    try:
        policy._assert_index_unchanged()
        plans, common = policy._assert_write_plans_unchanged()
    except GuardedPolicyError as exc:
        raise CollectorError(f"{phase} 도중 plan-index/plan 변경 또는 무효화: {exc}") from exc
    current_plans = [{"schematic": row["schematic"], "path": row["plan"],
                      "sha256": row["sha256"], "size": row["size"]} for row in plans]
    current_common = {"path": common["plan"], "sha256": common["sha256"],
                      "size": common["size"]} if common is not None else None
    require(current_plans == before["plans"] and current_common == before["common_plan"],
            f"{phase} 도중 plan source SHA/size 변경")


def verify_native_source(project_root: Path, artifact: Path, root_schematic: Path,
                         *, kind: str) -> str:
    if kind == "netlist":
        try:
            source_text = ET.parse(artifact).findtext("./design/source")
        except ET.ParseError as exc:
            raise CollectorError(f"native XML 해석 실패: {exc}") from exc
    elif kind == "erc":
        document = verifier.load_json(artifact)
        source_text = document.get("source")
    else:
        raise CollectorError(f"알 수 없는 native source kind: {kind}")
    require(isinstance(source_text, str) and source_text.strip(),
            f"native {kind} source identity 누락")
    source = verifier.safe_project_path(
        project_root, source_text.strip(), label=f"native {kind} source")
    require(source == root_schematic,
            f"native {kind} source가 root-schematic과 불일치: {source}!={root_schematic}")
    return str(source.relative_to(project_root))


def load_profile(project_root: Path, registry_path: Path, expected_sha: str,
                 profile_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha) is not None,
            "registry SHA256 형식 불일치")
    require(digest(registry_path) == expected_sha, "registry SHA256 불일치")
    registry = verifier.load_json(registry_path)
    require(type(registry.get("schema_version")) is int
            and registry.get("schema_version") == 1,
            "registry schema_version은 integer 1이어야 함")
    require(isinstance(registry.get("profiles"), dict), "registry 구조 불일치")
    require(profile_id in registry["profiles"], f"registry에 없는 profile-id: {profile_id}")
    seal = registry["profiles"][profile_id]
    require(isinstance(seal, dict) and set(seal) == {"semantic_contract", "sha256"},
            "registry profile seal 구조 불일치")
    semantic_path = verifier.safe_project_path(
        project_root, seal["semantic_contract"], label="semantic contract")
    require(digest(semantic_path) == seal["sha256"], "semantic contract SHA 불일치")
    semantic = verifier.load_json(semantic_path)
    require(type(semantic.get("schema_version")) is int
            and semantic.get("schema_version") == 2
            and semantic.get("contract_kind") == "schematic-quality-semantic"
            and semantic.get("profile_id") == profile_id,
            "semantic schema_version/contract 정체성 불일치")
    for key in ["required_source_files", "sheet_sources", "component_sheets", "erc"]:
        require(key in semantic, f"semantic contract 필수 필드 누락: {key}")
    require(isinstance(semantic["sheet_sources"], dict) and semantic["sheet_sources"],
            "sheet_sources 누락")
    return semantic, {"semantic_path": semantic_path, "seal": seal,
                      "registry_sha256": expected_sha}


def run_command(argv: list[str], log_path: Path, records: list[dict[str, Any]],
                *, phase: str, allowed_rc: set[int]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(argv, text=True, capture_output=True, timeout=300, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectorError(f"{phase} 실행 실패: {exc}") from exc
    write_text(log_path, completed.stdout + completed.stderr)
    records.append({"phase": phase, "argv": argv, "rc": completed.returncode,
                    "log": str(log_path), "log_sha256": digest(log_path)})
    require(completed.returncode in allowed_rc,
            f"{phase} 원 rc 실패: {completed.returncode}")
    return completed


def extract_mcp_results(evidence_dir: Path, expected_count: int) -> dict[tuple[str, str], Any]:
    response_dir = evidence_dir / "responses"
    require(response_dir.is_dir(), "guarded MCP responses directory 누락")
    files = sorted(response_dir.glob("*.json"))
    results: dict[tuple[str, str], Any] = {}
    selected = 0
    for path in files:
        document = strict_loads(
            path.read_text(encoding="utf-8"), context=f"MCP protocol response {path.name}",
            reject_null=False)
        if document.get("event") != "rpc_exchange":
            continue
        selected += 1
        request = document.get("request", {})
        params = request.get("params", request)
        name = params.get("name", params.get("tool"))
        arguments = params.get("arguments")
        response = document.get("response", {})
        require(isinstance(name, str) and isinstance(arguments, dict),
                f"MCP response request 구조 불일치: {path}")
        logical_rc = document.get("logical_rc")
        require(type(logical_rc) is int and logical_rc == 0 and "error" not in response,
                f"MCP logical rc 타입/실패: {path}:{logical_rc}")
        result = response.get("result", {})
        require(isinstance(result, dict) and result.get("isError") is not True,
                f"MCP tool 오류: {path}")
        content = result.get("content")
        require(isinstance(content, list), f"MCP content 누락: {path}")
        texts = [item.get("text") for item in content
                 if isinstance(item, dict) and item.get("type") == "text"]
        require(len(texts) == 1 and isinstance(texts[0], str),
                f"MCP text result 단일성 불일치: {path}")
        payload = strict_loads(texts[0], context=f"MCP payload {name}")
        schematic = arguments.get("schematic")
        require(isinstance(schematic, str), f"MCP schematic argument 누락: {path}")
        key = (schematic, name)
        require(key not in results, f"MCP result 중복: {key}")
        results[key] = payload
    require(selected == expected_count,
            f"guarded MCP response 개수 불일치: {selected}!={expected_count}")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--root-schematic", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kicad-cli", required=True)
    parser.add_argument("--pdf-text-tool", required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server-cwd", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--companion-receipts", default="{}",
                        help="runtime envelope에 넣을 JSON mapping")
    return parser


def collect(args: argparse.Namespace) -> int:
    try:
        project_root = verifier.validate_project_root(args.project_root)
        registry_path = verifier.select_registry_path(
            project_root, args.registry, args.registry_sha256)
        output = verifier.safe_project_path(
            project_root, args.output_dir, label="output-dir", must_exist=False, output_new=True)
        root_schematic = verifier.safe_project_path(
            project_root, args.root_schematic, label="root-schematic")
        plan_policy, plan_binding = capture_plan_binding(project_root)
        if root_schematic.suffix == ".kicad_sch":
            require(plan_policy.root_schematic == root_schematic.name,
                    "plan-index project_stem root와 --root-schematic 불일치")
        package_start = package_identity.capture()
        semantic, profile = load_profile(
            project_root, registry_path, args.registry_sha256, args.profile_id)
        required_paths = {
            verifier.safe_project_path(project_root, value, label="required source")
            for value in semantic["required_source_files"]
        }
        require(root_schematic in required_paths,
                "root-schematic이 required_source_files에 포함되지 않음")
        sheet_paths = {
            sheet: verifier.safe_project_path(project_root, raw, label=f"sheet source {sheet}")
            for sheet, raw in semantic["sheet_sources"].items()
        }
        require(set(sheet_paths.values()) <= required_paths,
                "sheet_sources가 required_source_files 밖을 가리킴")
        locks = editor_locks(project_root)
        require(not locks, f"active editor lock 때문에 수집 거부: {', '.join(map(str, locks))}")
        kicad_cli = resolve_executable(args.kicad_cli, label="kicad-cli")
        pdf_tool = resolve_executable(args.pdf_text_tool, label="pdf-text-tool")
        launcher = absolute_file(args.launcher, label="launcher", executable=True)
        config = absolute_file(args.config, label="config")
        server_cwd = absolute_directory(args.server_cwd, label="server-cwd")
        require(bool(args.expected_version.strip()), "expected-version 빈 값")
        require(bool(args.expected_commit.strip()), "expected-commit 빈 값")
        companions = strict_loads(args.companion_receipts, context="companion-receipts")
        require(isinstance(companions, dict), "companion-receipts는 JSON mapping이어야 함")
    except (CollectorError, verifier.VerificationError, GuardedPolicyError,
            OSError, ValueError, KeyError, TypeError) as exc:
        print("[FAIL]", str(exc))
        return 2

    output.mkdir(parents=True, exist_ok=False)
    commands: list[dict[str, Any]] = []
    phase = "preflight"
    try:
        before = source_hashes(project_root, semantic)
        assert_plan_binding(plan_policy, plan_binding, phase="pre-native")
        native = {
            "netlist": output / "netlist.xml",
            "pdf": output / "schematic.pdf",
            "erc": output / "erc.json",
        }
        native_commands = [
            ("native-netlist", [str(kicad_cli), "sch", "export", "netlist", "--format",
                                "kicadxml", "-o", str(native["netlist"]), str(root_schematic)], {0}),
            ("native-pdf", [str(kicad_cli), "sch", "export", "pdf", "-o",
                            str(native["pdf"]), str(root_schematic)], {0}),
            ("native-erc", [str(kicad_cli), "sch", "erc", "--format", "json",
                            "--severity-all", "--exit-code-violations", "-o",
                            str(native["erc"]), str(root_schematic)], {0, 5}),
        ]
        for name, command, allowed in native_commands:
            phase = name
            run_command(command, output / f"{name}.log", commands,
                        phase=name, allowed_rc=allowed)
            target = native[{"native-netlist": "netlist", "native-pdf": "pdf",
                             "native-erc": "erc"}[name]]
            require(target.is_file() and target.stat().st_size > 0,
                    f"{name} 산출물 누락/빈 파일: {target}")
            commands[-1]["source_class"] = (
                "kicad-cli sch export netlist --format kicadxml"
                if name == "native-netlist" else
                "kicad-cli sch export pdf"
                if name == "native-pdf" else
                "kicad-cli sch erc --severity-all --exit-code-violations"
            )
            if name in {"native-netlist", "native-erc"}:
                commands[-1]["owning_source"] = verify_native_source(
                    project_root, target, root_schematic,
                    kind="netlist" if name == "native-netlist" else "erc")
            if name == "native-erc":
                commands[-1]["rc_interpretation"] = (
                    "rc 5는 violation 존재 신호이며 PASS가 아님; exact content는 표준 검증기가 판정"
                    if commands[-1]["rc"] == 5 else
                    "rc 0은 명령 성공일 뿐 모든 ERC 규칙·전기·PCB·정격 합격이 아님"
                )
            assert_stable(project_root, semantic, before, phase=name)
            assert_plan_binding(plan_policy, plan_binding, phase=name)

        requests: list[dict[str, Any]] = []
        for sheet, path in sheet_paths.items():
            refs = [ref for ref, owner in semantic["component_sheets"].items() if owner == sheet]
            requests.extend([
                {"tool": "get_schematic_layout", "arguments": {"schematic": str(path)}},
                {"tool": "batch_get_schematic_pin_locations",
                 "arguments": {"schematic": str(path), "references": refs}},
                {"tool": "find_orphan_items", "arguments": {"schematic": str(path)}},
                {"tool": "find_shorted_nets", "arguments": {"schematic": str(path)}},
            ])
        request_path = output / "mcp-requests.jsonl"
        write_text(request_path, "".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in requests))
        mcp_evidence = output / "mcp-evidence"
        guarded = Path(__file__).resolve().with_name("guarded_mcp.py")
        require(guarded.is_file() and not guarded.is_symlink(), "sibling guarded_mcp.py 누락")
        command = [
            sys.executable, str(guarded),
            "--workspace-root", str(project_root),
            "--project-dir", str(project_root),
            "--launcher", str(launcher),
            "--config", str(config),
            "--server-cwd", str(server_cwd),
            "--expected-version", args.expected_version,
            "--expected-commit", args.expected_commit,
            "--requests", str(request_path),
            "--evidence-dir", str(mcp_evidence),
        ]
        phase = "guarded-mcp"
        run_command(command, output / "guarded-mcp.log", commands,
                    phase=phase, allowed_rc={0})
        assert_stable(project_root, semantic, before, phase=phase)
        assert_plan_binding(plan_policy, plan_binding, phase=phase)
        results = extract_mcp_results(mcp_evidence, len(requests))

        snapshot = {
            "schema_version": 1,
            "files": before,
            "sheets": {},
            "metadata_read_fallback": (
                "정식 조회가 없는 source top-level junction/text만 읽기 전용 보완; "
                "geometry/pins/orphan/short는 MCP 관측; 수집 전후 required source hash 동일 강제"
            ),
            "collection_scope": "저장본 native 정적 검증 범위; GUI 왕복 영수증이 아님",
        }
        for sheet, path in sheet_paths.items():
            key = str(path)
            junctions, texts = parse_metadata(path)
            snapshot["sheets"][sheet] = {
                "layout": results[(key, "get_schematic_layout")],
                "pins": results[(key, "batch_get_schematic_pin_locations")],
                "junctions": junctions,
                "texts": texts,
                "orphans": results[(key, "find_orphan_items")],
                "shorts": results[(key, "find_shorted_nets")],
            }
        phase = "source-read-fallback"
        assert_stable(project_root, semantic, before, phase=phase)
        assert_plan_binding(plan_policy, plan_binding, phase=phase)
        layout_path = output / "layout.json"
        write_json(layout_path, snapshot)
        runtime = {
            "schema_version": 2,
            "contract_kind": "schematic-quality-runtime",
            "sealed": True,
            "profile_id": args.profile_id,
            "candidate": {
                "inputs_sha256": {
                    "netlist": digest(native["netlist"]),
                    "layout": digest(layout_path),
                    "erc": digest(native["erc"]),
                    "pdf": digest(native["pdf"]),
                },
                "source_files": before,
            },
            "companion_receipts": companions,
            "producer_plan_binding": plan_binding,
            "producer_package_identity": package_start,
        }
        runtime_path = output / "runtime.json"
        write_json(runtime_path, runtime)

        report_path = output / "static-report.json"
        verify_command = [
            sys.executable, str(Path(__file__).resolve().with_name("verify_quality.py")),
            "--project-root", str(project_root),
            "--registry", str(registry_path),
            "--registry-sha256", args.registry_sha256,
            "--contract", str(runtime_path),
            "--netlist", str(native["netlist"]),
            "--layout", str(layout_path),
            "--erc", str(native["erc"]),
            "--pdf", str(native["pdf"]),
            "--report", str(report_path),
            "--pdf-text-tool", str(pdf_tool),
        ]
        phase = "standard-verifier"
        completed = run_command(
            verify_command, output / "standard-verifier.log", commands,
            phase=phase, allowed_rc={0, 1})
        assert_stable(project_root, semantic, before, phase=phase)
        assert_plan_binding(plan_policy, plan_binding, phase=phase)
        require(report_path.is_file(), "standard verifier report 누락")
        report = verifier.load_json(report_path)
        require((completed.returncode == 0) == (report.get("status") == "PASS"),
                "standard verifier rc-report status 불일치")

        package_end = package_identity.assert_unchanged(package_start)
        command_report = {
            "schema_version": 1,
            "at": now_iso(),
            "profile_id": args.profile_id,
            "registry": {"path": str(registry_path), "sha256": args.registry_sha256},
            "semantic": {"path": str(profile["semantic_path"]),
                         "sha256": profile["seal"]["sha256"]},
            "source_files_before_after_equal": True,
            "source_files": before,
            "plan_binding": plan_binding,
            "package_identity": {"start": package_start, "end": package_end,
                                 "unchanged": True},
            "commands": commands,
            "scope": {
                "native_static_collection": "checked",
                "gui_roundtrip_receipt": "not_checked_not_synthesized",
                "all_pages_visual_review": "not_checked",
                "native_erc": (
                    "owning root의 --severity-all JSON과 원 rc를 보존; configured policy·identity만 검증; "
                    "all-checks·PCB 거리·전압/전류 정격을 주장하지 않음"
                ),
                "protocol_page": "not_collected; 별도 운영자가 외부 증거로 결속",
                "pdf_page_png": "not_generated; 필요 시 pdftoppm을 별도 명시 실행해 결속",
                "electrical_dynamic_manufacturing_energization": "not_checked",
            },
        }
        write_json(output / "commands.json", command_report)
        print(json.dumps({"status": report["status"], "profile_id": args.profile_id,
                          "output_dir": str(output), "source_files": len(before),
                          "sheets": len(sheet_paths)}, ensure_ascii=False))
        return completed.returncode
    except (CollectorError, verifier.VerificationError, OSError, ValueError, KeyError,
            TypeError, json.JSONDecodeError) as exc:
        package_failure = {}
        if "package_start" in locals():
            package_failure["start"] = package_start
            try:
                package_failure["current"] = package_identity.capture()
                package_failure["unchanged"] = package_failure["current"] == package_start
            except (OSError, ValueError) as identity_exc:
                package_failure["current_error"] = str(identity_exc)
        failure = {
            "schema_version": 1, "status": "FAIL", "at": now_iso(),
            "phase": phase, "error": str(exc), "commands": commands,
            "plan_binding": plan_binding if "plan_binding" in locals() else "not_captured",
            "package_identity": package_failure if package_failure else "not_captured",
            "scope": "수집 실패; 누락을 0 또는 PASS로 합성하지 않음",
        }
        failure_path = output / "collection-failure.json"
        if not failure_path.exists():
            write_json(failure_path, failure)
        print("[FAIL]", str(exc))
        return 1


def main(argv: list[str] | None = None) -> int:
    return collect(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
