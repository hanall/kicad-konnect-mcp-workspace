#!/usr/bin/env python3
# 용도: 계획 선행 계약과 증거 보존을 강제해 Konnect STDIO 요청을 안전하게 전달한다.
"""계획 선행 계약을 강제하는 이식 가능한 Konnect STDIO 어댑터.

CAD 파일을 직접 쓰지 않는다. 호출자가 명시한 workspace/project와 backend
환경을 검증하고, 허용된 변경만 정식 launcher가 띄운 MCP의 ``tools/call``로
전달한다. 외부 패키지나 원본 프로젝트 모듈을 import하지 않는다.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Iterable, TextIO

import package_identity


PROTOCOL_VERSION = "2025-06-18"
PLAN_INDEX_NAME = "plan-index.json"
MIN_PLAN_CHARS = 500
MODES = {"design", "rewrite", "change", "review"}
EXACT_READ_ONLY_PREVIEWS = {
    "annotate_schematic",
    "reset_schematic_field_positions",
    "update_symbols_from_library",
}
SAVED_READBACK_OUTCOME_MUTATIONS = {
    "add_schematic_component",
    "annotate_schematic",
    "batch_place_components",
}
PROTECTED_SUFFIXES = {".kicad_sch", ".kicad_sym", ".kicad_pro", ".kicad_pcb"}
PROTECTED_BASENAMES = {"sym-lib-table", "fp-lib-table"}


SCHEMATIC_MUTATIONS = {
    "add_component_annotation",
    "add_junction",
    "add_no_connect",
    "add_power_symbol",
    "add_schematic_component",
    "add_schematic_connection",
    "add_schematic_net_label",
    "add_schematic_text",
    "add_sheet_pin",
    "annotate_schematic",
    "batch_add_junction",
    "batch_add_no_connect",
    "batch_add_wire",
    "batch_connect_pins",
    "batch_connect_to_net",
    "batch_delete",
    "batch_delete_no_connect",
    "batch_delete_schematic_components",
    "batch_delete_schematic_wire",
    "batch_edit_schematic_components",
    "batch_place_components",
    "batch_rotate_labels",
    "bulk_move_schematic_components",
    "connect_passthrough",
    "connect_pins",
    "connect_to_net",
    "delete_no_connect",
    "delete_schematic_component",
    "delete_schematic_net_label",
    "delete_schematic_wire",
    "delete_sheet",
    "delete_sheet_pin",
    "edit_schematic_component",
    "edit_sheet_pin",
    "group_components",
    "import_sheet_pins",
    "move_connected",
    "move_labels_by_offset",
    "move_region",
    "move_schematic_component",
    "move_sheet",
    "renumber_sheet_pages",
    "replace_component",
    "reset_schematic_field_positions",
    "rotate_schematic_component",
    "rotate_schematic_label",
    "set_schematic_page",
    "split_wire_at_point",
    "update_symbols_from_library",
}

SPECIAL_MUTATIONS = {
    "create_project",
    "create_schematic",
    "add_hierarchical_sheet",
    "edit_sheet",
    "duplicate_sheet",
    "create_symbol",
    "delete_symbol",
    "register_symbol_library",
}

READ_TOOLS = {
    "audit_connections",
    "audit_decoupling",
    "audit_power_rails",
    "batch_get_schematic_pin_locations",
    "check_bom_health",
    "check_schematic_overlaps",
    "compare_visual_baseline",
    "export_netlist_summary",
    "export_schematic_pdf",
    "export_schematic_svg",
    "find_orphan_items",
    "find_shorted_nets",
    "find_single_pin_nets",
    "generate_netlist",
    "get_component_nets",
    "get_connected_items",
    "get_net_components",
    "get_net_connections",
    "get_net_connectivity",
    "get_pin_connections",
    "get_pin_net_name",
    "get_project_info",
    "get_schematic_component",
    "get_schematic_layout",
    "get_schematic_pin_locations",
    "get_schematic_view",
    "get_sheet_hierarchy",
    "get_symbol_info",
    "list_schematic_components",
    "list_schematic_labels",
    "list_schematic_nets",
    "list_schematic_wires",
    "list_symbols_in_library",
    "render_schematic_png",
    "run_design_review",
    "run_erc",
    "snapshot_project",
    "trace_from_point",
    "validate_component_connections",
    "validate_sheet_pins",
    "validate_wire_connections",
}

META_READ_TOOLS = {
    "get_active_toolsets",
    "get_installation_info",
    "get_recent_calls",
    "list_toolboxes",
    "server_stats",
}
READ_TOOLS.update(META_READ_TOOLS)

OUTPUT_PATH_KEYS = {"output", "output_dir"}

TOOLSET_BY_TOOL: dict[str, str] = {
    "create_project": "project",
    "get_project_info": "project",
    "snapshot_project": "project",
    "create_symbol": "library",
    "delete_symbol": "library",
    "register_symbol_library": "library",
    "get_symbol_info": "library",
    "list_symbols_in_library": "library",
    "add_hierarchical_sheet": "sch_hierarchy",
    "create_schematic": "sch_hierarchy",
    "edit_sheet": "sch_hierarchy",
    "duplicate_sheet": "sch_hierarchy",
    "add_sheet_pin": "sch_hierarchy",
    "delete_sheet": "sch_hierarchy",
    "delete_sheet_pin": "sch_hierarchy",
    "edit_sheet_pin": "sch_hierarchy",
    "get_sheet_hierarchy": "sch_hierarchy",
    "import_sheet_pins": "sch_hierarchy",
    "move_sheet": "sch_hierarchy",
    "renumber_sheet_pages": "sch_hierarchy",
    "set_schematic_page": "sch_hierarchy",
    "validate_sheet_pins": "sch_hierarchy",
}

for _tool in {
    "add_component_annotation", "add_schematic_component", "annotate_schematic",
    "batch_get_schematic_pin_locations", "delete_schematic_component",
    "edit_schematic_component", "get_schematic_component", "get_schematic_pin_locations",
    "get_schematic_view", "group_components", "list_schematic_components",
    "move_connected", "move_region", "move_schematic_component", "replace_component",
    "reset_schematic_field_positions", "rotate_schematic_component",
    "update_symbols_from_library",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "sch_components")

for _tool in {
    "add_junction", "add_no_connect", "add_power_symbol", "add_schematic_connection",
    "add_schematic_net_label", "add_wire", "batch_add_junction", "batch_add_no_connect",
    "batch_add_wire", "batch_delete_no_connect", "batch_delete_schematic_wire",
    "batch_rotate_labels", "connect_pins", "connect_to_net", "delete_no_connect",
    "delete_schematic_net_label", "delete_schematic_wire", "move_labels_by_offset",
    "rotate_schematic_label", "split_wire_at_point",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "sch_wiring")

for _tool in {
    "check_schematic_overlaps", "find_orphan_items", "find_shorted_nets",
    "find_single_pin_nets", "get_component_nets", "get_connected_items",
    "get_net_components", "get_net_connections", "get_net_connectivity",
    "get_pin_connections", "get_pin_net_name", "list_schematic_labels",
    "list_schematic_nets", "list_schematic_wires", "trace_from_point",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "sch_analysis")

for _tool in {
    "add_schematic_text", "batch_connect_pins", "batch_connect_to_net", "batch_delete",
    "batch_delete_schematic_components", "batch_edit_schematic_components",
    "batch_place_components", "bulk_move_schematic_components", "connect_passthrough",
    "get_schematic_layout", "validate_component_connections", "validate_wire_connections",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "sch_batch")

for _tool in {
    "compare_visual_baseline", "export_netlist_summary", "export_schematic_pdf",
    "export_schematic_svg", "generate_netlist", "render_schematic_png", "run_erc",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "sch_export")

for _tool in {
    "audit_connections", "audit_decoupling", "audit_power_rails", "check_bom_health",
    "run_design_review",
}:
    TOOLSET_BY_TOOL.setdefault(_tool, "design_review")


class AdapterError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def library_source_evidence(path: Path) -> dict[str, Any]:
    """등록할 읽기 전용 symbol library의 형식과 내용을 결정적으로 해시한다."""
    if path.is_symlink():
        raise AdapterError(f"resolve 뒤 library source가 symlink일 수 없습니다: {path}")
    if path.is_file() and path.suffix == ".kicad_sym":
        digest = sha256_file(path)
        assert digest is not None
        return {"source_type": "kicad_sym", "content_sha256": digest, "file_count": 1}
    if path.is_dir() and path.name.endswith(".kicad_symdir"):
        files = sorted(path.rglob("*"))
        symbol_files: list[Path] = []
        for item in files:
            if item.is_symlink():
                raise AdapterError(f"read_only_library_refs 내부 symlink는 허용하지 않습니다: {item}")
            if item.is_file():
                if item.suffix != ".kicad_sym":
                    raise AdapterError(f".kicad_symdir에 예상 밖 파일이 있습니다: {item}")
                symbol_files.append(item)
        if not symbol_files:
            raise AdapterError(f".kicad_symdir에 symbol 파일이 없습니다: {path}")
        digest = hashlib.sha256()
        for item in symbol_files:
            relative = item.relative_to(path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with item.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            digest.update(b"\0")
        return {
            "source_type": "kicad_symdir",
            "content_sha256": digest.hexdigest(),
            "file_count": len(symbol_files),
        }
    raise AdapterError(
        f"read_only_library_refs source는 기존 .kicad_sym 파일 또는 .kicad_symdir 디렉터리여야 합니다: {path}"
    )


def is_protected_path(path: Path) -> bool:
    return path.suffix.lower() in PROTECTED_SUFFIXES or path.name in PROTECTED_BASENAMES


@dataclass(frozen=True)
class PreparedRequest:
    tool: str
    arguments: dict[str, Any]
    mutating: bool
    affected_schematics: tuple[str, ...] = ()
    registered_read_only_library_ref: dict[str, Any] | None = None
    write_targets: tuple[str, ...] = ()


class ProjectPolicy:
    """plan-index.json과 경로·도구 allowlist를 검증한다."""

    def __init__(self, project_dir: Path, *, workspace_root: Path):
        try:
            self.workspace_root = workspace_root.resolve(strict=True)
            self.project_dir = project_dir.resolve(strict=True)
        except OSError as error:
            raise AdapterError(f"workspace/project 경로를 확인할 수 없습니다: {error}") from error
        if not self.workspace_root.is_dir():
            raise AdapterError(f"workspace-root가 디렉터리가 아닙니다: {self.workspace_root}")
        try:
            self.project_dir.relative_to(self.workspace_root)
        except ValueError as error:
            raise AdapterError(
                f"project-dir은 workspace-root 안이어야 합니다: {self.project_dir}"
            ) from error
        if not self.project_dir.is_dir():
            raise AdapterError(f"project-dir이 존재하는 디렉터리가 아닙니다: {self.project_dir}")

        self.index_path = self.project_dir / PLAN_INDEX_NAME
        try:
            self.index_bytes = self.index_path.read_bytes()
        except OSError as error:
            raise AdapterError(f"{PLAN_INDEX_NAME}을 읽을 수 없습니다: {error}") from error
        self.index_sha256 = sha256_bytes(self.index_bytes)
        try:
            index = json.loads(self.index_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AdapterError(f"{PLAN_INDEX_NAME} JSON이 올바르지 않습니다: {error}") from error
        if (
            not isinstance(index, dict)
            or type(index.get("schema_version")) is not int
            or index["schema_version"] != 1
        ):
            raise AdapterError("plan-index.json schema_version은 1이어야 합니다")
        mode = index.get("mode")
        if mode not in MODES:
            raise AdapterError(
                "plan-index.json mode는 design/rewrite/change/review 중 하나여야 합니다"
            )
        self.mode = mode
        project_stem = index.get("project_stem")
        if not isinstance(project_stem, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", project_stem):
            raise AdapterError("project_stem은 안전한 파일 stem 문자열이어야 합니다")
        self.project_stem = project_stem
        self.root_schematic = f"{project_stem}.kicad_sch"

        allowed = index.get("allowed_files")
        plans = index.get("plans")
        if not isinstance(allowed, list) or not allowed:
            raise AdapterError("allowed_files는 비어 있지 않은 문자열 배열이어야 합니다")
        if not isinstance(plans, dict):
            raise AdapterError("plans는 객체여야 합니다")
        self.allowed_files: set[str] = set()
        self.allowed_canonical: dict[Path, str] = {}
        for raw in allowed:
            rel = self._clean_relative(raw, "allowed_files")
            raw_target = self.project_dir / rel
            if raw_target.is_symlink():
                raise AdapterError(f"allowed_files의 symlink는 허용하지 않습니다: {raw}")
            target = raw_target.resolve()
            self._assert_under_project(target, "allowed_files")
            if target in self.allowed_canonical:
                raise AdapterError(f"allowed_files의 정규화 결과가 중복됩니다: {raw}")
            self.allowed_files.add(rel)
            self.allowed_canonical[target] = rel

        raw_read_only_files = index.get("read_only_files", [])
        if not isinstance(raw_read_only_files, list):
            raise AdapterError("read_only_files는 allowed_files 부분집합인 배열이어야 합니다")
        self.read_only_files: set[str] = set()
        for raw in raw_read_only_files:
            rel = self._clean_relative(raw, "read_only_files")
            if rel not in self.allowed_files:
                raise AdapterError(f"read_only_files가 allowed_files에 없습니다: {rel}")
            if rel in self.read_only_files:
                raise AdapterError(f"read_only_files가 중복됩니다: {rel}")
            self.read_only_files.add(rel)
        require_all = index.get("require_all_plans_before_write", False)
        if not isinstance(require_all, bool):
            raise AdapterError("require_all_plans_before_write는 boolean이어야 합니다")
        self.require_all_plans_before_write = require_all

        self.plans: dict[str, str] = {}
        for raw_schematic, raw_plan in plans.items():
            schematic = self._clean_relative(raw_schematic, "plans schematic")
            plan = self._clean_relative(raw_plan, "plans plan")
            if not schematic.endswith(".kicad_sch"):
                raise AdapterError(f"plans key는 .kicad_sch여야 합니다: {schematic}")
            if schematic not in self.allowed_files:
                raise AdapterError(f"plans의 회로도가 allowed_files에 없습니다: {schematic}")
            plan_path = (self.project_dir / plan).resolve()
            self._assert_under_project(plan_path, "계획 파일")
            self.plans[schematic] = plan
        raw_common_plan = index.get("common_plan")
        self.common_plan: str | None = None
        if raw_common_plan is not None:
            self.common_plan = self._clean_relative(raw_common_plan, "common_plan")
            self._assert_under_project(
                (self.project_dir / self.common_plan).resolve(), "common_plan"
            )

        raw_read_refs = index.get("read_only_library_refs", {})
        if not isinstance(raw_read_refs, dict):
            raise AdapterError("read_only_library_refs는 nickname→절대경로 객체여야 합니다")
        self.read_only_library_refs_mapping: dict[str, str] = {}
        self.read_only_library_refs: dict[str, Path] = {}
        self.read_only_library_ref_entries: dict[str, dict[str, Any]] = {}
        seen_resolved: set[Path] = set()
        for nickname, declared_value in raw_read_refs.items():
            if not isinstance(nickname, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+", nickname):
                raise AdapterError(f"read_only_library_refs nickname이 올바르지 않습니다: {nickname!r}")
            if not isinstance(declared_value, str) or not Path(declared_value).is_absolute():
                raise AdapterError(f"read_only_library_refs 경로는 절대경로여야 합니다: {nickname}")
            declared = Path(declared_value)
            try:
                resolved = declared.resolve(strict=True)
            except OSError as error:
                raise AdapterError(
                    f"read_only_library_refs source가 존재하지 않습니다: {nickname}={declared}: {error}"
                ) from error
            try:
                resolved.relative_to(self.project_dir)
            except ValueError:
                pass
            else:
                raise AdapterError(
                    f"read_only_library_refs는 프로젝트 밖의 읽기 전용 참조에만 사용합니다: {resolved}"
                )
            if resolved in seen_resolved:
                raise AdapterError(f"read_only_library_refs resolved 경로가 중복됩니다: {resolved}")
            seen_resolved.add(resolved)
            source = library_source_evidence(resolved)
            self.read_only_library_refs_mapping[nickname] = declared_value
            self.read_only_library_refs[nickname] = resolved
            self.read_only_library_ref_entries[nickname] = {
                "nickname": nickname,
                "declared_path": declared_value,
                "resolved_path": str(resolved),
                **source,
            }
        self.read_only_library_refs_mapping_sha256 = sha256_bytes(
            json.dumps(
                self.read_only_library_refs_mapping,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        self._write_plan_baselines: dict[str, dict[str, Any]] | None = None
        self._common_plan_baseline: dict[str, Any] | None = None

    @staticmethod
    def _clean_relative(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"{label}에는 비어 있지 않은 문자열 경로가 필요합니다")
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise AdapterError(f"{label}은 프로젝트 상대경로여야 합니다: {value}")
        normalized = Path(*[part for part in path.parts if part not in {"", "."}]).as_posix()
        if not normalized or normalized == ".":
            raise AdapterError(f"{label} 경로가 비어 있습니다")
        return normalized

    def _assert_under_project(self, target: Path, label: str) -> None:
        try:
            target.relative_to(self.project_dir)
        except ValueError as error:
            raise AdapterError(f"{label} 경로가 프로젝트 밖으로 탈출합니다: {target}") from error

    def _resolve(self, value: Any, label: str, *, base: Path | None = None) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise AdapterError(f"{label}에는 비어 있지 않은 문자열 경로가 필요합니다")
        raw = Path(value)
        target = raw.resolve() if raw.is_absolute() else ((base or self.project_dir) / raw).resolve()
        self._assert_under_project(target, label)
        return target

    def _require_allowed(self, value: Any, label: str, *, base: Path | None = None) -> str:
        target = self._resolve(value, label, base=base)
        try:
            return self.allowed_canonical[target]
        except KeyError as error:
            raise AdapterError(f"{label}이 allowed_files에 정확히 포함되지 않았습니다: {target}") from error

    def _require_output(self, value: Any, label: str) -> Path:
        target = self._resolve(value, label)
        if is_protected_path(target) or target in self.allowed_canonical:
            raise AdapterError(f"export 출력이 CAD/라이브러리 원본을 덮을 수 없습니다: {target}")
        return target

    def read_only_library_refs_manifest_evidence(self) -> dict[str, Any]:
        return {
            "mapping": dict(self.read_only_library_refs_mapping),
            "mapping_sha256": self.read_only_library_refs_mapping_sha256,
            "entries": [
                dict(self.read_only_library_ref_entries[nickname])
                for nickname in sorted(self.read_only_library_ref_entries)
            ],
        }

    def _match_read_only_library_ref(self, nickname: Any, value: Any) -> dict[str, Any]:
        if not isinstance(nickname, str) or nickname not in self.read_only_library_refs:
            raise AdapterError(
                "외부 symbol library 등록은 plan-index read_only_library_refs의 nickname/path exact mapping만 허용합니다"
            )
        if not isinstance(value, str) or not value.strip():
            raise AdapterError("register_symbol_library.library_path 문자열이 필요합니다")
        declared_value = self.read_only_library_refs_mapping[nickname]
        if value != declared_value:
            raise AdapterError(
                "외부 symbol library 등록 경로는 read_only_library_refs의 declared path와 exact 일치해야 합니다"
            )
        raw = Path(value)
        candidate = raw.resolve() if raw.is_absolute() else (self.project_dir / raw).resolve()
        expected = self.read_only_library_refs[nickname]
        if candidate != expected:
            raise AdapterError(
                "외부 symbol library 등록 경로가 read_only_library_refs의 resolved path와 일치하지 않습니다: "
                f"nickname={nickname}, requested={candidate}, expected={expected}"
            )
        declared_now = Path(self.read_only_library_refs_mapping[nickname]).resolve(strict=True)
        if declared_now != expected:
            raise AdapterError(
                f"read_only_library_refs declared path의 resolved 대상이 변경되었습니다: {nickname}"
            )
        return {
            "nickname": nickname,
            "declared_path": self.read_only_library_refs_mapping[nickname],
            "resolved_path": str(expected),
            **library_source_evidence(expected),
        }

    def _assert_index_unchanged(self) -> None:
        try:
            current = self.index_path.read_bytes()
        except OSError as error:
            raise AdapterError(f"mutation 직전 plan-index.json을 다시 읽지 못했습니다: {error}") from error
        if current != self.index_bytes:
            raise AdapterError("실행 중 plan-index.json이 변경되어 mutation을 중단합니다")

    def _assert_no_editor_locks(self) -> None:
        locks = sorted(
            path
            for path in self.project_dir.rglob("*.lck")
            if path.name != ".schematic-quality-mcp.lock"
        )
        if locks:
            raise AdapterError(
                "KiCad editor lock이 있어 mutation을 중단합니다(삭제·우회하지 않음): "
                + ", ".join(str(path) for path in locks)
            )

    @staticmethod
    def _validate_symbol_units(value: Any, *, trail: str = "arguments") -> None:
        """중첩 batch 요청도 unit을 양의 정수로만 전달한다."""
        if isinstance(value, dict):
            for key, child in value.items():
                child_trail = f"{trail}.{key}"
                if key == "unit" and (type(child) is not int or child < 1):
                    raise AdapterError(f"{child_trail}은 1 이상의 정수여야 합니다")
                ProjectPolicy._validate_symbol_units(child, trail=child_trail)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                ProjectPolicy._validate_symbol_units(child, trail=f"{trail}[{index}]")

    @staticmethod
    def _require_nonempty_fields(tool: str, args: dict[str, Any], fields: Iterable[str]) -> None:
        missing = [key for key in fields if not isinstance(args.get(key), str) or not args[key]]
        if missing:
            raise AdapterError(f"{tool} current schema 필수 문자열 누락: {', '.join(missing)}")

    @staticmethod
    def _contains_unapproved_power_flag(value: Any) -> bool:
        if isinstance(value, dict):
            if any(
                value.get(key) == "power:PWR_FLAG"
                for key in ("lib_id", "new_lib_id")
            ):
                return True
            return any(ProjectPolicy._contains_unapproved_power_flag(item) for item in value.values())
        if isinstance(value, list):
            return any(ProjectPolicy._contains_unapproved_power_flag(item) for item in value)
        return False

    def _validate_critical_mutation_contract(self, tool: str, args: dict[str, Any]) -> None:
        """legacy 서명과 품질상 wire 없는 batch 연결을 MCP 호출 전에 거부한다."""
        if self._contains_unapproved_power_flag(args):
            raise AdapterError(
                "power:PWR_FLAG는 machine-readable source 승인 계약이 없어 자동 삽입을 거부합니다"
            )
        if tool == "connect_pins":
            self._require_nonempty_fields(tool, args, ("ref1", "pin1", "ref2", "pin2"))
        elif tool == "connect_to_net":
            self._require_nonempty_fields(tool, args, ("net",))
            by_reference = all(
                isinstance(args.get(key), str) and bool(args[key])
                for key in ("reference", "pin_number")
            )
            by_coordinate = all(
                type(args.get(key)) in {int, float} and math.isfinite(args[key])
                for key in ("pin_x", "pin_y")
            )
            if by_reference == by_coordinate:
                raise AdapterError(
                    "connect_to_net은 reference+pin_number 또는 pin_x+pin_y 중 정확히 하나가 필요합니다"
                )
        elif tool == "add_power_symbol":
            self._require_nonempty_fields(tool, args, ("power_net",))
            if args["power_net"] == "PWR_FLAG":
                raise AdapterError(
                    "PWR_FLAG는 machine-readable source 승인 계약이 없어 자동 삽입을 거부합니다"
                )
            if any(
                type(args.get(key)) not in {int, float} or not math.isfinite(args[key])
                for key in ("x", "y")
            ):
                raise AdapterError("add_power_symbol current schema에는 숫자 x/y가 필요합니다")
        elif tool == "batch_connect_to_net":
            stub_length = args.get("stub_length")
            if (
                type(stub_length) not in {int, float}
                or not math.isfinite(stub_length)
                or stub_length <= 0
            ):
                raise AdapterError(
                    "batch_connect_to_net은 품질 모드에서 0보다 큰 명시적 stub_length가 필요합니다"
                )
            pins = args.get("pins")
            if not isinstance(pins, list) or not pins:
                raise AdapterError("batch_connect_to_net.pins는 비어 있지 않은 배열이어야 합니다")
            for index, pin in enumerate(pins):
                if not isinstance(pin, dict):
                    raise AdapterError(f"batch_connect_to_net.pins[{index}]는 object여야 합니다")
                self._require_nonempty_fields(
                    f"batch_connect_to_net.pins[{index}]", pin, ("reference", "pin_number")
                )

    def cad_hash_evidence(self) -> tuple[str, dict[str, str | None]]:
        """allowed 보호 파일 전체의 현재 bytes를 읽어 파일별·결합 SHA를 반환한다."""
        file_hashes: dict[str, str | None] = {}
        for rel in sorted(self.allowed_files):
            path = (self.project_dir / rel).resolve()
            if is_protected_path(path):
                file_hashes[rel] = sha256_file(path)
        combined = sha256_bytes(
            json.dumps(
                file_hashes,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        return combined, file_hashes

    def _plan_evidence(self, schematic: str) -> dict[str, Any]:
        plan_rel = self.plans.get(schematic)
        if plan_rel is None:
            raise AdapterError(f"대상 회로도의 사전 계획 mapping이 없습니다: {schematic}")
        raw_plan_path = self.project_dir / plan_rel
        if raw_plan_path.is_symlink():
            raise AdapterError(f"계획 파일 symlink는 허용하지 않습니다: {raw_plan_path}")
        plan_path = raw_plan_path.resolve()
        self._assert_under_project(plan_path, "계획 파일")
        try:
            data = plan_path.read_bytes()
            stat = plan_path.stat()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise AdapterError(f"계획 파일을 읽을 수 없습니다: {plan_path}: {error}") from error
        headings = re.findall(r"(?m)^#{1,6}\s+\S.*$", text)
        missing_topics = [topic for topic in ("실선", "포트", "반환", "검증") if topic not in text]
        if len(text) < MIN_PLAN_CHARS or len(headings) < 4 or missing_topics:
            details = []
            if len(text) < MIN_PLAN_CHARS:
                details.append(f"{MIN_PLAN_CHARS}자 미만")
            if len(headings) < 4:
                details.append("Markdown section 4개 미만")
            if missing_topics:
                details.append("누락 주제=" + ",".join(missing_topics))
            raise AdapterError(f"사전 계획 기본 계약 미충족: {plan_path} ({'; '.join(details)})")
        return {
            "schematic": schematic,
            "plan": plan_rel,
            "sha256": sha256_bytes(data),
            "mtime_ns": stat.st_mtime_ns,
            "size": len(data),
        }

    def _common_plan_evidence(self) -> dict[str, Any] | None:
        if self.common_plan is None:
            return None
        raw_plan_path = self.project_dir / self.common_plan
        if raw_plan_path.is_symlink():
            raise AdapterError(f"common_plan symlink는 허용하지 않습니다: {raw_plan_path}")
        plan_path = raw_plan_path.resolve()
        self._assert_under_project(plan_path, "common_plan")
        try:
            data = plan_path.read_bytes()
            stat = plan_path.stat()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise AdapterError(f"공통 작성 계획을 읽을 수 없습니다: {plan_path}: {error}") from error
        headings = re.findall(r"(?m)^#{1,6}\s+\S.*$", text)
        if len(text) < MIN_PLAN_CHARS or len(headings) < 3:
            raise AdapterError(
                f"공통 작성 계획 기본 계약 미충족: {plan_path} "
                f"(chars={len(text)}, sections={len(headings)})"
            )
        return {
            "plan": self.common_plan,
            "sha256": sha256_bytes(data),
            "mtime_ns": stat.st_mtime_ns,
            "size": len(data),
        }

    def _require_plan(self, schematic: str) -> None:
        self._plan_evidence(schematic)

    def _capture_all_write_plans(self) -> None:
        """첫 mutation 준비 시 common/root/전 페이지 계획의 원문 SHA를 고정한다."""
        if not self.require_all_plans_before_write:
            raise AdapterError("mutation에는 require_all_plans_before_write=true가 필수입니다")
        schematics = sorted(rel for rel in self.allowed_files if rel.endswith(".kicad_sch"))
        if self.root_schematic not in schematics:
            raise AdapterError("allowed_files에 project_stem의 루트 회로도가 필요합니다")
        missing = [item for item in schematics if item not in self.plans]
        if missing:
            raise AdapterError(
                "require_all_plans_before_write=true이지만 모든 회로도의 사전 계획이 없습니다: "
                + ", ".join(missing)
            )
        if self.common_plan is None:
            raise AdapterError(
                "require_all_plans_before_write=true이면 common_plan 선언과 유효한 원문이 필요합니다"
            )
        if self._write_plan_baselines is None:
            self._write_plan_baselines = {
                schematic: self._plan_evidence(schematic) for schematic in schematics
            }
            self._common_plan_baseline = self._common_plan_evidence()

    def _assert_write_plans_unchanged(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self._capture_all_write_plans()
        assert self._write_plan_baselines is not None
        assert self._common_plan_baseline is not None
        current = [self._plan_evidence(item) for item in sorted(self._write_plan_baselines)]
        for item in current:
            before = self._write_plan_baselines[item["schematic"]]
            if item["sha256"] != before["sha256"] or item["size"] != before["size"]:
                raise AdapterError(
                    f"mutation 준비 후 페이지 계획 원문이 변경되었습니다: {item['plan']}"
                )
        common = self._common_plan_evidence()
        assert common is not None
        if (
            common["sha256"] != self._common_plan_baseline["sha256"]
            or common["size"] != self._common_plan_baseline["size"]
        ):
            raise AdapterError("mutation 준비 후 common_plan 원문이 변경되었습니다")
        return current, common

    def _finalize_mutation(
        self,
        tool: str,
        args: dict[str, Any],
        affected: Iterable[str],
        write_targets: Iterable[str],
        registered_read_ref: dict[str, Any] | None = None,
    ) -> PreparedRequest:
        normalized_targets = tuple(dict.fromkeys(write_targets))
        blocked = sorted(set(normalized_targets) & self.read_only_files)
        if blocked:
            raise AdapterError(
                f"mutation 실제 쓰기 대상이 plan-index read_only_files에 포함됩니다: {', '.join(blocked)}"
            )
        return PreparedRequest(
            tool=tool,
            arguments=args,
            mutating=True,
            affected_schematics=tuple(dict.fromkeys(affected)),
            registered_read_only_library_ref=registered_read_ref,
            write_targets=normalized_targets,
        )

    def _prepare_mutation(self, tool: str, args: dict[str, Any]) -> PreparedRequest:
        affected: list[str] = []
        write_targets: list[str] = []
        if tool == "create_project":
            path = self._resolve(args.get("path"), "create_project.path")
            if path != self.project_dir:
                raise AdapterError("create_project.path는 선택한 project-dir과 같아야 합니다")
            if args.get("name") != self.project_stem:
                raise AdapterError("create_project.name은 plan-index project_stem과 같아야 합니다")
            args["path"] = str(path)
            for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
                target = self._require_allowed(
                    str(self.project_dir / f"{self.project_stem}{suffix}"),
                    "create_project 산출물",
                )
                write_targets.append(target)
            self._require_plan(self.root_schematic)
            affected.append(self.root_schematic)
        elif tool == "create_schematic":
            schematic = self._require_allowed(args.get("path"), "create_schematic.path")
            if not schematic.endswith(".kicad_sch"):
                raise AdapterError("create_schematic.path는 .kicad_sch여야 합니다")
            self._require_plan(schematic)
            args["path"] = str(self.project_dir / schematic)
            affected.append(schematic)
            write_targets.append(schematic)
        elif tool == "add_hierarchical_sheet":
            parent = self._require_allowed(args.get("schematic"), "add_hierarchical_sheet.schematic")
            if not parent.endswith(".kicad_sch"):
                raise AdapterError("hierarchy parent는 .kicad_sch여야 합니다")
            parent_path = self.project_dir / parent
            child = self._require_allowed(
                args.get("sheet_file"), "add_hierarchical_sheet.sheet_file", base=parent_path.parent
            )
            if not child.endswith(".kicad_sch"):
                raise AdapterError("hierarchy child는 .kicad_sch여야 합니다")
            self._require_plan(parent)
            self._require_plan(child)
            args["schematic"] = str(parent_path)
            args["sheet_file"] = os.path.relpath(
                self.project_dir / child, start=parent_path.parent
            )
            affected.extend((parent, child))
            write_targets.extend((parent, child))
        elif tool in {"edit_sheet", "duplicate_sheet"}:
            parent = self._require_allowed(args.get("schematic"), f"{tool}.schematic")
            self._require_plan(parent)
            parent_path = self.project_dir / parent
            args["schematic"] = str(parent_path)
            affected.append(parent)
            write_targets.append(parent)
            new_file = args.get("new_file")
            if tool == "duplicate_sheet" or new_file is not None:
                child = self._require_allowed(new_file, f"{tool}.new_file", base=(self.project_dir / parent).parent)
                if not child.endswith(".kicad_sch"):
                    raise AdapterError(f"{tool}.new_file은 .kicad_sch여야 합니다")
                self._require_plan(child)
                args["new_file"] = os.path.relpath(
                    self.project_dir / child, start=parent_path.parent
                )
                affected.append(child)
                write_targets.append(child)
        elif tool in {"create_symbol", "delete_symbol"}:
            library = self._require_allowed(args.get("library_path"), f"{tool}.library_path")
            if not library.endswith(".kicad_sym"):
                raise AdapterError(f"{tool}.library_path는 .kicad_sym이어야 합니다")
            args["library_path"] = str(self.project_dir / library)
            self._require_plan(self.root_schematic)
            affected.append(self.root_schematic)
            write_targets.append(library)
        elif tool == "register_symbol_library":
            scope = args.get("scope", "project")
            if scope != "project":
                raise AdapterError("global library 등록은 금지되며 scope='project'만 허용합니다")
            registered_read_ref: dict[str, Any] | None = None
            raw_library = args.get("library_path")
            if not isinstance(raw_library, str) or not raw_library.strip():
                raise AdapterError("register_symbol_library.library_path 문자열이 필요합니다")
            raw_path = Path(raw_library)
            candidate = (
                raw_path.resolve()
                if raw_path.is_absolute()
                else (self.project_dir / raw_path).resolve()
            )
            library = self.allowed_canonical.get(candidate)
            if library is None:
                registered_read_ref = self._match_read_only_library_ref(
                    args.get("nickname"), raw_library
                )
            project = self._require_allowed(args.get("project"), "register_symbol_library.project")
            if not project.endswith(".kicad_pro"):
                raise AdapterError("register_symbol_library.project는 allowed .kicad_pro 파일이어야 합니다")
            if "sym-lib-table" not in self.allowed_files:
                raise AdapterError("sym-lib-table이 allowed_files에 정확히 포함되어야 합니다")
            args["library_path"] = (
                str(self.project_dir / library)
                if library is not None
                else registered_read_ref["resolved_path"]
            )
            args["project"] = str(self.project_dir / project)
            self._require_plan(self.root_schematic)
            affected.append(self.root_schematic)
            write_targets.append("sym-lib-table")
            return self._finalize_mutation(
                tool,
                args,
                affected,
                write_targets,
                registered_read_ref,
            )
        else:
            schematic = self._require_allowed(args.get("schematic"), f"{tool}.schematic")
            if not schematic.endswith(".kicad_sch"):
                raise AdapterError(f"{tool}.schematic은 .kicad_sch여야 합니다")
            self._require_plan(schematic)
            args["schematic"] = str(self.project_dir / schematic)
            affected.append(schematic)
            write_targets.append(schematic)
            if "project" in args:
                project = self._require_allowed(args["project"], f"{tool}.project")
                if not project.endswith(".kicad_pro"):
                    raise AdapterError(f"{tool}.project는 allowed .kicad_pro여야 합니다")
                args["project"] = str(self.project_dir / project)
        return self._finalize_mutation(tool, args, affected, write_targets)

    def _prepare_read(self, tool: str, args: dict[str, Any]) -> PreparedRequest:
        if tool == "get_symbol_info":
            project_value = args.get("project_dir")
            if project_value is not None and self._resolve(project_value, "get_symbol_info.project_dir") != self.project_dir:
                raise AdapterError("get_symbol_info.project_dir는 선택한 project-dir이어야 합니다")
            args["project_dir"] = str(self.project_dir)
        if "project_dir" in args and tool != "get_symbol_info":
            if self._resolve(args["project_dir"], f"{tool}.project_dir") != self.project_dir:
                raise AdapterError(f"{tool}.project_dir는 선택한 project-dir이어야 합니다")
        if "schematic" in args:
            schematic = self._require_allowed(args["schematic"], f"{tool}.schematic")
            if not schematic.endswith(".kicad_sch"):
                raise AdapterError(f"{tool}.schematic은 .kicad_sch여야 합니다")
            args["schematic"] = str(self.project_dir / schematic)
            if tool == "run_erc" and schematic != self.root_schematic:
                raise AdapterError("run_erc는 hierarchy owning root schematic에서만 허용합니다")
        if "board" in args:
            board = self._require_allowed(args["board"], f"{tool}.board")
            if not board.endswith(".kicad_pcb"):
                raise AdapterError(f"{tool}.board는 allowed .kicad_pcb 파일이어야 합니다")
            args["board"] = str(self.project_dir / board)
        if tool == "get_project_info":
            project = self._require_allowed(args.get("path"), "get_project_info.path")
            if not project.endswith(".kicad_pro"):
                raise AdapterError("get_project_info.path는 allowed .kicad_pro여야 합니다")
            args["path"] = str(self.project_dir / project)
        if "project" in args:
            project = self._require_allowed(args["project"], f"{tool}.project")
            if not project.endswith(".kicad_pro"):
                raise AdapterError(f"{tool}.project는 allowed .kicad_pro여야 합니다")
            args["project"] = str(self.project_dir / project)
        if tool == "list_symbols_in_library":
            library = self._require_allowed(
                args.get("library_path"), "list_symbols_in_library.library_path"
            )
            args["library_path"] = str(self.project_dir / library)
        if tool == "snapshot_project" and args.get("pcb") is not None:
            raise AdapterError("평가 어댑터는 PCB snapshot을 허용하지 않습니다")
        for key in OUTPUT_PATH_KEYS:
            if key in args:
                args[key] = str(self._require_output(args[key], f"{tool}.{key}"))
        if tool in {"export_schematic_pdf", "export_schematic_svg", "generate_netlist", "render_schematic_png"}:
            if "output" not in args:
                raise AdapterError(f"{tool}은 project-dir 아래의 명시적 output 경로가 필요합니다")
        if tool == "run_erc" and "output" in args:
            self._require_output(args["output"], "run_erc.output")
        return PreparedRequest(tool, args, False)

    def prepare_request(self, tool: Any, arguments: Any) -> PreparedRequest:
        if not isinstance(tool, str) or not tool:
            raise AdapterError("각 요청에는 문자열 tool이 필요합니다")
        if not isinstance(arguments, dict):
            raise AdapterError(f"{tool}.arguments는 JSON object여야 합니다")
        # 호출자가 보유한 객체를 수정하지 않도록 JSON 호환 깊은 복사를 만든다.
        try:
            args = json.loads(json.dumps(arguments, ensure_ascii=False))
        except (TypeError, ValueError) as error:
            raise AdapterError(f"{tool}.arguments는 JSON 직렬화 가능해야 합니다: {error}") from error
        self._validate_symbol_units(args)
        if tool in SCHEMATIC_MUTATIONS or tool in SPECIAL_MUTATIONS:
            if tool in EXACT_READ_ONLY_PREVIEWS and "dry_run" in args:
                if type(args["dry_run"]) is not bool:
                    raise AdapterError(f"{tool}.dry_run은 boolean이어야 합니다")
                if args["dry_run"] is True:
                    return self._prepare_read(tool, args)
            if self.mode == "review":
                raise AdapterError("mode='review'는 읽기 전용이며 모든 mutation을 거부합니다")
            prepared = self._prepare_mutation(tool, args)
            self._validate_critical_mutation_contract(tool, prepared.arguments)
            self._capture_all_write_plans()
            return prepared
        if tool in READ_TOOLS:
            return self._prepare_read(tool, args)
        raise AdapterError(
            f"허용되지 않은 도구입니다(PCB/제조/설정/자동 source rewrite 포함): {tool}"
        )

    def mutation_intent(self, request: PreparedRequest) -> dict[str, Any]:
        if not request.mutating:
            return {}
        self._assert_index_unchanged()
        self._assert_no_editor_locks()
        plan_evidence, common_plan_evidence = self._assert_write_plans_unchanged()
        combined, file_hashes = self.cad_hash_evidence()
        return {
            "plan_index": {
                "path": str(self.index_path),
                "sha256": self.index_sha256,
            },
            "plans": plan_evidence,
            "common_plan": common_plan_evidence,
            "read_only_library_refs_manifest": self.read_only_library_refs_manifest_evidence(),
            "registered_read_only_library_ref": request.registered_read_only_library_ref,
            "read_only_files": sorted(self.read_only_files),
            "mode": self.mode,
            "require_all_plans_before_write": self.require_all_plans_before_write,
            "write_targets": list(request.write_targets),
            "before_cad_hash": combined,
            "before_cad_hashes": file_hashes,
        }

    def assert_mutation_ready(
        self, request: PreparedRequest, intent: dict[str, Any]
    ) -> None:
        """MCP 호출 직전 TOCTOU와 실제 editor lock을 한 번 더 거부한다."""
        if not request.mutating:
            return
        self._assert_index_unchanged()
        self._assert_no_editor_locks()
        plans, common = self._assert_write_plans_unchanged()
        expected_plans = {
            (item["schematic"], item["sha256"]) for item in intent.get("plans", [])
        }
        actual_plans = {(item["schematic"], item["sha256"]) for item in plans}
        expected_common = intent.get("common_plan") or {}
        if expected_plans != actual_plans or expected_common.get("sha256") != common["sha256"]:
            raise AdapterError("pre_dispatch 증거 이후 계획 원문이 변경되어 mutation을 중단합니다")
        current_hash, current_hashes = self.cad_hash_evidence()
        if (
            intent.get("before_cad_hash") != current_hash
            or intent.get("before_cad_hashes") != current_hashes
        ):
            raise AdapterError(
                "mutation intent 이후 실제 CAD bytes가 변경되어 dispatch를 중단합니다"
            )


class ProjectWriterLock:
    def __init__(self, project_dir: Path):
        self.path = project_dir / ".schematic-quality-mcp.lock"
        self.handle: TextIO | None = None

    def acquire(self) -> None:
        if self.handle is not None:
            return
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise AdapterError(f"writer lock을 안전하게 열 수 없습니다: {self.path}: {error}") from error
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
            os.close(descriptor)
            raise AdapterError(f"writer lock은 hardlink 없는 일반 파일이어야 합니다: {self.path}")
        self.handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.handle.close()
            self.handle = None
            raise AdapterError(f"같은 project-dir을 다른 작성자가 사용 중입니다: {self.path}") from error
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(json.dumps({"pid": os.getpid(), "acquired_at": now_iso()}, ensure_ascii=False) + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None

    def __enter__(self) -> "ProjectWriterLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class EvidenceWriter:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.responses_dir = self.directory / "responses"
        self.journal: TextIO | None = None
        self.response_seq = 0

    def __enter__(self) -> "EvidenceWriter":
        self.directory.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(exist_ok=True)
        journal_path = self.directory / "mcp-journal.jsonl"
        self.journal = journal_path.open("a", encoding="utf-8", buffering=1)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.journal is not None:
            self.journal.flush()
            os.fsync(self.journal.fileno())
            self.journal.close()
            self.journal = None

    def append(self, payload: dict[str, Any], *, durable: bool = True) -> None:
        if self.journal is None:
            raise RuntimeError("EvidenceWriter가 열려 있지 않습니다")
        self.journal.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        self.journal.flush()
        if durable:
            os.fsync(self.journal.fileno())

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.directory / name
        temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with temp.open("x", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return path

    def write_response(self, payload: Any) -> Path:
        self.response_seq += 1
        path = self.responses_dir / f"response-{self.response_seq:04d}.json"
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def snapshot_plan(self, source: Path, expected_sha256: str) -> str:
        """계획 원문을 내용 SHA 이름으로 최초 한 번만 무수정 보존한다."""
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise AdapterError(f"plan snapshot SHA-256 형식이 올바르지 않습니다: {expected_sha256}")
        try:
            data = source.read_bytes()
        except OSError as error:
            raise AdapterError(f"plan snapshot 원문을 읽을 수 없습니다: {source}: {error}") from error
        actual_sha256 = sha256_bytes(data)
        if actual_sha256 != expected_sha256:
            raise AdapterError(
                f"plan snapshot 직전 원문 SHA가 변경되었습니다: {source} "
                f"(expected={expected_sha256}, actual={actual_sha256})"
            )

        plans_dir = self.directory / "plans"
        plans_dir.mkdir(exist_ok=True)
        destination = plans_dir / f"{expected_sha256}.md"

        def verify_existing() -> None:
            if destination.is_symlink() or not destination.is_file():
                raise AdapterError(f"plan snapshot 대상이 일반 파일이 아닙니다: {destination}")
            try:
                existing = destination.read_bytes()
            except OSError as error:
                raise AdapterError(f"기존 plan snapshot을 읽을 수 없습니다: {destination}: {error}") from error
            existing_sha256 = sha256_bytes(existing)
            if destination.stem != existing_sha256 or existing_sha256 != expected_sha256 or existing != data:
                raise AdapterError(
                    f"기존 plan snapshot의 파일명·내용 SHA 또는 원문이 일치하지 않습니다: {destination}"
                )

        if destination.exists() or destination.is_symlink():
            verify_existing()
            return str(destination)
        try:
            with destination.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            # 같은 evidence-dir의 동시·중복 요청은 기존 내용이 완전히 같을 때만 허용한다.
            verify_existing()
        directory_fd = os.open(plans_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        verify_existing()
        return str(destination)


def mcp_response_is_error(response: dict[str, Any]) -> bool:
    if "error" in response:
        return True
    result = response.get("result")
    return isinstance(result, dict) and result.get("isError") is True


def response_quality_error(
    tool: str,
    response: dict[str, Any],
    arguments: dict[str, Any] | None = None,
    *,
    mutating: bool = False,
) -> str | None:
    """MCP 성공 flag만으로 false-green이 되는 불완전 응답을 거부한다."""
    if mcp_response_is_error(response):
        return None
    try:
        body = parse_tool_json_body(response, tool)
    except AdapterError as error:
        return str(error)
    if mutating:
        if not body:
            return f"{tool} mutation 응답 JSON object가 비어 있어 결과를 검증할 수 없습니다"
        outcome = body.get("outcome")
        status = outcome.get("status") if isinstance(outcome, dict) else body.get("status")
        if isinstance(status, str) and status.lower() in {
            "partial", "failed", "failure", "error", "incomplete", "uncertain"
        }:
            return f"{tool} mutation outcome이 완료가 아닙니다: {status}"
        for key in ("errors", "failures"):
            if body.get(key):
                return f"{tool} mutation 응답의 {key}가 비어 있지 않습니다"
        failed_count = body.get("failed_count")
        if type(failed_count) is int and failed_count > 0:
            return f"{tool} mutation failed_count가 0보다 큽니다"
        if body.get("success") is False:
            return f"{tool} mutation success=false입니다"
        if isinstance(outcome, dict):
            failed = outcome.get("failed")
            if type(failed) is int and failed > 0:
                return f"{tool} mutation outcome.failed가 0보다 큽니다"
            requested, completed = outcome.get("requested"), outcome.get("completed")
            if all(type(value) is int for value in (requested, completed, failed)):
                if requested != completed + failed:
                    return f"{tool} mutation outcome count accounting이 불일치합니다"
        if tool in SAVED_READBACK_OUTCOME_MUTATIONS:
            if not isinstance(outcome, dict) or outcome.get("status") != "complete":
                return f"{tool}은 source-confirmed complete outcome이 필요합니다"
            if outcome.get("source") != "saved_file_readback":
                return f"{tool} outcome source가 saved_file_readback이 아닙니다"
    if tool == "get_symbol_info":
        expected_lib_id = (arguments or {}).get("lib_id")
        if not isinstance(expected_lib_id, str) or not expected_lib_id:
            return "get_symbol_info 요청의 expected lib_id가 없습니다"
        if body.get("lib_id") != expected_lib_id:
            return "get_symbol_info 응답 lib_id가 요청 expected lib_id와 다릅니다"
        pin_count = body.get("pin_count")
        pins = body.get("pins")
        if type(pin_count) is not int or pin_count < 1:
            return "get_symbol_info pin_count가 1 이상의 정수가 아닙니다"
        if not isinstance(pins, list) or len(pins) != pin_count:
            return "get_symbol_info pin_count와 pins expected coverage가 다릅니다"
        endpoints: set[tuple[int, str]] = set()
        for index, pin in enumerate(pins):
            if not isinstance(pin, dict):
                return f"get_symbol_info pins[{index}]가 object가 아닙니다"
            if not isinstance(pin.get("number"), str) or not pin["number"]:
                return f"get_symbol_info pins[{index}]의 pin number가 불완전합니다"
            if "name" not in pin or not isinstance(pin["name"], str):
                return f"get_symbol_info pins[{index}]의 name field가 불완전합니다"
            if not isinstance(pin.get("type"), str) or not pin["type"]:
                return f"get_symbol_info pins[{index}]의 type field가 불완전합니다"
            if type(pin.get("unit")) is not int or pin["unit"] < 1:
                return (
                    "get_symbol_info 응답은 unit coverage를 제공하지 않아 "
                    "multi-unit/상속 pin 완전성이 미확인입니다"
                )
            endpoint = (pin["unit"], pin["number"])
            if endpoint in endpoints:
                return "get_symbol_info unit+pin expected coverage에 중복이 있습니다"
            endpoints.add(endpoint)
    return None


Caller = Callable[[str, dict[str, Any], dict[str, Any]], tuple[dict[str, Any], float, dict[str, Any]]]


def dispatch_prepared_requests(
    policy: ProjectPolicy,
    requests: Iterable[PreparedRequest],
    caller: Caller,
    evidence: EvidenceWriter,
    *,
    emit: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """첫 MCP 오류에서 중단하며 모든 요청·응답을 증거화한다."""
    records: list[dict[str, Any]] = []
    for index, prepared in enumerate(requests, start=1):
        intent = policy.mutation_intent(prepared) if prepared.mutating else {}
        if prepared.mutating:
            common_plan = intent.get("common_plan")
            if isinstance(common_plan, dict):
                common_plan["snapshot_path"] = evidence.snapshot_plan(
                    policy.project_dir / common_plan["plan"], common_plan["sha256"]
                )
            for plan in intent.get("plans", []):
                plan["snapshot_path"] = evidence.snapshot_plan(
                    policy.project_dir / plan["plan"], plan["sha256"]
                )
        started_at = now_iso()
        evidence.append(
            {
                "event": "pre_dispatch",
                "request_index": index,
                "started_at": started_at,
                "tool": prepared.tool,
                "arguments": prepared.arguments,
                "mutating": prepared.mutating,
                **intent,
            },
            durable=True,
        )
        try:
            policy.assert_mutation_ready(prepared, intent)
            response, duration_ms, raw_request = caller(prepared.tool, prepared.arguments, intent)
        except Exception as error:
            after_fields: dict[str, Any] = {}
            if prepared.mutating:
                try:
                    after_hash, after_hashes = policy.cad_hash_evidence()
                    after_fields = {
                        "after_cad_hash": after_hash,
                        "after_cad_hashes": after_hashes,
                    }
                except Exception as hash_error:
                    after_fields = {
                        "after_cad_hash_error": f"{type(hash_error).__name__}: {hash_error}"
                    }
            evidence.append(
                {
                    "event": "transport_error",
                    "request_index": index,
                    "ended_at": now_iso(),
                    "tool": prepared.tool,
                    "error": f"{type(error).__name__}: {error}",
                    "logical_rc": 1,
                    **after_fields,
                }
            )
            records.append(
                {
                    "request_index": index,
                    "tool": prepared.tool,
                    "ok": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            if emit:
                emit(records[-1])
            return records, True
        mcp_failed = mcp_response_is_error(response)
        quality_errors: list[str] = []
        response_error = response_quality_error(
            prepared.tool,
            response,
            prepared.arguments,
            mutating=prepared.mutating,
        )
        if response_error is not None:
            quality_errors.append(response_error)
        after_fields = {}
        after_hash_failed = False
        mutation_readback: dict[str, Any] | None = None
        if prepared.mutating:
            try:
                after_hash, after_hashes = policy.cad_hash_evidence()
                before_hashes = intent.get("before_cad_hashes")
                if not isinstance(before_hashes, dict):
                    raise AdapterError("mutation intent에 before_cad_hashes가 없습니다")
                changed_targets = sorted(
                    key
                    for key in set(before_hashes) | set(after_hashes)
                    if before_hashes.get(key) != after_hashes.get(key)
                )
                allowed_targets = set(intent.get("write_targets", []))
                unexpected = sorted(set(changed_targets) - allowed_targets)
                mutation_readback = {
                    "changed_targets": changed_targets,
                    "declared_write_targets": sorted(allowed_targets),
                    "unexpected_changes": unexpected,
                }
                if unexpected:
                    quality_errors.append(
                        "mutation이 선언하지 않은 CAD target을 변경했습니다: "
                        + ", ".join(unexpected)
                    )
                if not changed_targets:
                    quality_errors.append(
                        "mutation 뒤 CAD bytes 변경이 없어 작성 성공 증거로 인정할 수 없습니다"
                    )
                after_fields = {
                    "after_cad_hash": after_hash,
                    "after_cad_hashes": after_hashes,
                }
            except Exception as hash_error:
                after_hash_failed = True
                after_fields = {
                    "after_cad_hash_error": f"{type(hash_error).__name__}: {hash_error}"
                }
        quality_error = "; ".join(quality_errors) if quality_errors else None
        failed = mcp_failed or quality_error is not None or after_hash_failed
        exchange = {
            "event": "rpc_exchange",
            "request_index": index,
            "started_at": started_at,
            "ended_at": now_iso(),
            "duration_ms": duration_ms,
            "tool": prepared.tool,
            "request": raw_request,
            "response": response,
            "mcp_logical_rc": 1 if mcp_failed else 0,
            "quality_contract_error": quality_error,
            "mutation_readback": mutation_readback,
            "logical_rc": 1 if failed else 0,
            **after_fields,
        }
        response_path = evidence.write_response(exchange)
        evidence.append(exchange)
        record = {
            "request_index": index,
            "tool": prepared.tool,
            "ok": not failed,
            "duration_ms": duration_ms,
            "response": response,
            "response_file": str(response_path),
        }
        records.append(record)
        if emit:
            emit(record)
        if failed:
            return records, True
    return records, False


def file_identity(path: Path, label: str, *, executable: bool = False) -> dict[str, Any]:
    """명시 파일의 canonical 경로와 변경 탐지용 identity를 반환한다."""
    try:
        declared = path.absolute()
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError as error:
        raise AdapterError(f"{label}을 확인할 수 없습니다: {path}: {error}", exit_code=1) from error
    if not resolved.is_file():
        raise AdapterError(f"{label}은 일반 파일이어야 합니다: {resolved}", exit_code=1)
    if executable and not os.access(resolved, os.X_OK):
        raise AdapterError(f"{label}은 실행 가능해야 합니다: {resolved}", exit_code=1)
    digest = sha256_file(resolved)
    assert digest is not None
    return {
        "declared_path": str(declared),
        "resolved_path": str(resolved),
        "sha256": digest,
        "size": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "mode": stat.st_mode,
    }


@dataclass(frozen=True)
class BackendEnvironment:
    launcher: Path
    config: Path
    server_cwd: Path
    launcher_identity: dict[str, Any]
    config_identity: dict[str, Any]
    cwd_identity: dict[str, Any]

    @classmethod
    def capture(cls, launcher: Path, config: Path, server_cwd: Path) -> "BackendEnvironment":
        launcher_identity = file_identity(launcher, "launcher", executable=True)
        config_identity = file_identity(config, "config")
        try:
            cwd = server_cwd.resolve(strict=True)
            stat = cwd.stat()
        except OSError as error:
            raise AdapterError(f"server-cwd를 확인할 수 없습니다: {error}", exit_code=1) from error
        if not cwd.is_dir():
            raise AdapterError(f"server-cwd가 디렉터리가 아닙니다: {cwd}", exit_code=1)
        cwd_identity = {
            "declared_path": str(server_cwd.absolute()),
            "resolved_path": str(cwd),
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "mode": stat.st_mode,
        }
        cwd_identity["identity_sha256"] = sha256_bytes(
            json.dumps(cwd_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        return cls(
            launcher=Path(launcher_identity["resolved_path"]),
            config=Path(config_identity["resolved_path"]),
            server_cwd=cwd,
            launcher_identity=launcher_identity,
            config_identity=config_identity,
            cwd_identity=cwd_identity,
        )

    def evidence(self) -> dict[str, Any]:
        evidence = {
            "launcher": dict(self.launcher_identity),
            "config": dict(self.config_identity),
            "server_cwd": dict(self.cwd_identity),
            "argv": [str(self.launcher), "--config", str(self.config)],
            "shell": False,
        }
        evidence["environment_sha256"] = sha256_bytes(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        return evidence

    def assert_unchanged(self) -> None:
        launcher_now = file_identity(self.launcher, "launcher", executable=True)
        config_now = file_identity(self.config, "config")
        for label, before, after in (
            ("launcher", self.launcher_identity, launcher_now),
            ("config", self.config_identity, config_now),
        ):
            for key in ("resolved_path", "sha256", "size", "device", "inode", "mode"):
                if before[key] != after[key]:
                    raise AdapterError(f"실행 중 {label} identity가 변경되었습니다: {key}", exit_code=1)
        try:
            stat = self.server_cwd.stat()
        except OSError as error:
            raise AdapterError(f"실행 중 server-cwd를 확인할 수 없습니다: {error}", exit_code=1) from error
        if (
            stat.st_dev != self.cwd_identity["device"]
            or stat.st_ino != self.cwd_identity["inode"]
            or stat.st_mode != self.cwd_identity["mode"]
        ):
            raise AdapterError("실행 중 server-cwd identity가 변경되었습니다", exit_code=1)


class StdioMcp:
    def __init__(
        self,
        stderr_path: Path,
        *,
        launcher: Path,
        config: Path,
        server_cwd: Path,
        timeout: float = 180.0,
    ):
        self.launcher = launcher.resolve(strict=True)
        self.config = config.resolve(strict=True)
        self.server_cwd = server_cwd.resolve(strict=True)
        if not self.launcher.is_file() or not os.access(self.launcher, os.X_OK):
            raise AdapterError(f"launcher가 실행 가능한 일반 파일이 아닙니다: {self.launcher}", exit_code=1)
        if not self.config.is_file():
            raise AdapterError(f"config가 일반 파일이 아닙니다: {self.config}", exit_code=1)
        if not self.server_cwd.is_dir():
            raise AdapterError(f"server-cwd가 디렉터리가 아닙니다: {self.server_cwd}", exit_code=1)
        self.stderr_handle = stderr_path.open("x", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                [str(self.launcher), "--config", str(self.config)],
                cwd=self.server_cwd,
                env=os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr_handle,
                text=True,
                bufsize=1,
                start_new_session=True,
                shell=False,
            )
        except Exception:
            self.stderr_handle.close()
            raise
        if os.getpgid(self.process.pid) != self.process.pid:
            self.process.kill()
            self.process.wait(timeout=5)
            self.stderr_handle.close()
            raise AdapterError("Konnect 전용 process group을 만들지 못했습니다", exit_code=1)
        self.timeout = timeout
        self.next_id = 1
        assert self.process.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.notifications: list[dict[str, Any]] = []

    def _send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise AdapterError("Konnect stdin이 없습니다", exit_code=1)
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], float, dict[str, Any]]:
        identifier = self.next_id
        self.next_id += 1
        raw: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            raw["params"] = params
        started = time.monotonic()
        self._send(raw)
        deadline = started + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AdapterError(
                    f"Konnect 서버가 응답 전에 종료했습니다: rc={self.process.returncode}, method={method}",
                    exit_code=1,
                )
            events = self.selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            assert self.process.stdout is not None
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise AdapterError(f"Konnect stdout JSON 오염: {line!r}", exit_code=1) from error
            if response.get("id") == identifier:
                return response, round((time.monotonic() - started) * 1000, 3), raw
            self.notifications.append(response)
        raise AdapterError(f"Konnect MCP timeout: method={method}, id={identifier}", exit_code=1)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raw: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            raw["params"] = params
        self._send(raw)
        return raw

    def call_tool(self, tool: str, arguments: dict[str, Any], _intent: dict[str, Any]) -> tuple[dict[str, Any], float, dict[str, Any]]:
        return self.request("tools/call", {"name": tool, "arguments": arguments})

    def close(self) -> int | None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                # 서버 조기종료 뒤 pipe flush/close 실패는 이미 process rc가 증명한다.
                # cleanup과 session-summary를 건너뛰게 하지 않는다.
                pass
        try:
            return self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if self.process.poll() is None and os.getpgid(self.process.pid) == self.process.pid:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                return self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if self.process.poll() is None and os.getpgid(self.process.pid) == self.process.pid:
                    os.killpg(self.process.pid, signal.SIGKILL)
                return self.process.wait(timeout=5)
        finally:
            self.selector.close()
            self.stderr_handle.close()


def load_requests(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise AdapterError(f"requests JSONL을 읽을 수 없습니다: {error}") from error
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise AdapterError(f"requests JSONL {line_no}행 JSON 오류: {error}") from error
        if not isinstance(item, dict) or set(item) - {"tool", "arguments"}:
            raise AdapterError(f"requests JSONL {line_no}행은 tool/arguments만 가진 객체여야 합니다")
        items.append(item)
    if not items:
        raise AdapterError("requests JSONL에 요청이 없습니다")
    return items, raw


def validate_evidence_dir(path: Path, policy: ProjectPolicy) -> Path:
    if path.is_symlink():
        raise AdapterError(f"evidence-dir symlink는 허용하지 않습니다: {path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(policy.workspace_root)
    except ValueError as error:
        raise AdapterError("evidence-dir은 workspace-root 안이어야 합니다") from error
    if resolved.exists() or resolved.is_symlink():
        raise AdapterError(f"evidence-dir은 존재하지 않는 새 경로여야 합니다: {resolved}")
    for target in policy.allowed_canonical:
        if target == resolved or target in resolved.parents or resolved in target.parents:
            raise AdapterError(f"evidence-dir이 CAD allowed_files 경계와 충돌합니다: {target}")
    return resolved


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def record_internal_rpc(
    evidence: EvidenceWriter,
    transport: StdioMcp,
    method: str,
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    started_at = now_iso()
    response, duration_ms, raw_request = transport.request(method, params)
    failed = mcp_response_is_error(response)
    exchange = {
        "event": "internal_rpc",
        "started_at": started_at,
        "ended_at": now_iso(),
        "duration_ms": duration_ms,
        "request": raw_request,
        "response": response,
        "logical_rc": 1 if failed else 0,
    }
    evidence.write_response(exchange)
    evidence.append(exchange)
    if failed:
        raise AdapterError(f"내부 MCP 요청 실패: {method}", exit_code=1)
    return response


def parse_tool_json_body(response: dict[str, Any], tool: str) -> dict[str, Any]:
    """MCP tool result의 첫 JSON text object를 엄격히 해석한다."""
    if mcp_response_is_error(response):
        raise AdapterError(f"{tool} MCP 응답이 오류입니다", exit_code=1)
    result = response.get("result")
    content = result.get("content") if isinstance(result, dict) else None
    if not isinstance(content, list):
        raise AdapterError(f"{tool} 응답 content가 배열이 아닙니다", exit_code=1)
    if len(content) != 1:
        raise AdapterError(f"{tool} 응답은 단일 JSON text content여야 합니다", exit_code=1)
    item = content[0]
    if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
        raise AdapterError(f"{tool} 응답에 단일 JSON text content가 없습니다", exit_code=1)
    try:
        body = json.loads(item["text"])
    except json.JSONDecodeError as error:
        raise AdapterError(f"{tool} 응답 text가 JSON이 아닙니다: {error}", exit_code=1) from error
    if not isinstance(body, dict):
        raise AdapterError(f"{tool} 응답 JSON이 object가 아닙니다", exit_code=1)
    return body


def runtime_identity_evidence(
    response: dict[str, Any],
    *,
    process_pid: int,
    expected_config: Path,
    expected_version: str,
    expected_commit: str,
) -> tuple[dict[str, Any], bool]:
    """serving build/config/binary를 실제 파일 identity와 결속한다."""
    body = parse_tool_json_body(response, "get_installation_info")
    build = body.get("build")
    runtime = body.get("runtime")
    configuration = body.get("configuration")
    if not isinstance(build, dict) or not isinstance(runtime, dict) or not isinstance(configuration, dict):
        raise AdapterError("get_installation_info에 build/runtime/configuration이 없습니다", exit_code=1)
    version = build.get("version")
    commit = build.get("commit")
    executable_raw = runtime.get("executable_path")
    selected_raw = configuration.get("selected_path")
    if not isinstance(version, str) or not version:
        raise AdapterError("get_installation_info build.version이 없습니다", exit_code=1)
    if not isinstance(commit, str) or not commit:
        raise AdapterError("get_installation_info build.commit이 없습니다", exit_code=1)
    if not isinstance(executable_raw, str) or not Path(executable_raw).is_absolute():
        raise AdapterError("get_installation_info runtime.executable_path가 절대경로가 아닙니다", exit_code=1)
    if not isinstance(selected_raw, str) or not Path(selected_raw).is_absolute():
        raise AdapterError("get_installation_info configuration.selected_path가 절대경로가 아닙니다", exit_code=1)
    try:
        selected = Path(selected_raw).resolve(strict=True)
    except OSError as error:
        raise AdapterError(f"serving config 경로를 확인할 수 없습니다: {error}", exit_code=1) from error
    expected_config = expected_config.resolve(strict=True)
    if selected != expected_config:
        raise AdapterError(
            f"serving config가 --config와 다릅니다: actual={selected}, expected={expected_config}",
            exit_code=1,
        )
    binary = file_identity(Path(executable_raw), "runtime executable", executable=True)
    proc_executable: dict[str, Any] | None = None
    proc_link = Path(f"/proc/{process_pid}/exe")
    if proc_link.exists():
        try:
            proc_target = proc_link.resolve(strict=True)
        except OSError as error:
            raise AdapterError(f"서버 /proc executable을 확인할 수 없습니다: {error}", exit_code=1) from error
        proc_executable = file_identity(proc_target, "server /proc executable", executable=True)
        if proc_executable["resolved_path"] != binary["resolved_path"]:
            raise AdapterError(
                "get_installation_info executable과 실제 서버 /proc executable이 다릅니다",
                exit_code=1,
            )
    matches = version == expected_version and commit == expected_commit
    return (
        {
            "build": {"version": version, "commit": commit},
            "expected": {"version": expected_version, "commit": expected_commit},
            "matches_expected": matches,
            "configuration": {
                "selected_path": str(selected),
                "sha256": sha256_file(selected),
            },
            "runtime_executable": binary,
            "process": {"pid": process_pid, "proc_executable": proc_executable},
        },
        matches,
    )


def run(args: argparse.Namespace) -> int:
    try:
        package_start = package_identity.capture()
    except ValueError as error:
        raise AdapterError(f"스킬 package identity를 생성할 수 없습니다: {error}", exit_code=1) from error
    policy = ProjectPolicy(args.project_dir, workspace_root=args.workspace_root)
    request_items, request_bytes = load_requests(args.requests)
    prepared = [policy.prepare_request(item.get("tool"), item.get("arguments", {})) for item in request_items]
    has_mutations = any(item.mutating for item in prepared)
    needed_toolsets = sorted({TOOLSET_BY_TOOL[item.tool] for item in prepared if item.tool in TOOLSET_BY_TOOL})
    missing_mapping = sorted(
        item.tool
        for item in prepared
        if item.tool not in TOOLSET_BY_TOOL and item.tool not in META_READ_TOOLS
    )
    if missing_mapping:
        raise AdapterError(f"도구의 toolset mapping이 없습니다: {', '.join(missing_mapping)}")
    if not isinstance(args.expected_version, str) or not args.expected_version:
        raise AdapterError("expected-version은 비어 있지 않아야 합니다")
    if not isinstance(args.expected_commit, str) or not args.expected_commit:
        raise AdapterError("expected-commit은 비어 있지 않아야 합니다")
    if not isinstance(args.timeout, float) or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise AdapterError("timeout은 0보다 큰 유한 초여야 합니다")
    backend = BackendEnvironment.capture(args.launcher, args.config, args.server_cwd)
    evidence_dir = validate_evidence_dir(args.evidence_dir, policy)
    lock_context = ProjectWriterLock(policy.project_dir) if has_mutations else nullcontext()
    with lock_context, EvidenceWriter(evidence_dir) as evidence:
        evidence.write_json("plan-index.snapshot.json", json.loads(policy.index_bytes))
        (evidence.directory / "requests.snapshot.jsonl").write_bytes(request_bytes)
        session = {
            "schema_version": 1,
            "started_at": now_iso(),
            "pid": os.getpid(),
            "workspace_root": str(policy.workspace_root),
            "project_dir": str(policy.project_dir),
            "mode": policy.mode,
            "requests_path": str(args.requests.resolve()),
            "requests_sha256": sha256_bytes(request_bytes),
            "plan_index_sha256": policy.index_sha256,
            "read_only_files": sorted(policy.read_only_files),
            "require_all_plans_before_write": policy.require_all_plans_before_write,
            "read_only_library_refs_manifest": policy.read_only_library_refs_manifest_evidence(),
            "package_identity": package_start,
            "backend_environment": backend.evidence(),
            "expected_version": args.expected_version,
            "expected_commit": args.expected_commit,
            "timeout_seconds": args.timeout,
            "toolsets": needed_toolsets,
        }
        evidence.write_json("session-start.json", session)
        transport: StdioMcp | None = None
        session_rc = 1
        server_exit_rc: int | None = None
        runtime_identity: dict[str, Any] | None = None
        backend_final_error: str | None = None
        package_identity_error: str | None = None
        package_identity_final: dict[str, Any] | None = None
        server_close_error: str | None = None

        def assert_package_unchanged() -> None:
            try:
                package_identity.assert_unchanged(package_start)
            except ValueError as error:
                raise AdapterError(f"실행 중 스킬 package identity가 변경되었습니다: {error}") from error

        try:
            assert_package_unchanged()
            backend.assert_unchanged()
            transport = StdioMcp(
                evidence.directory / "server-stderr.log",
                launcher=backend.launcher,
                config=backend.config,
                server_cwd=backend.server_cwd,
                timeout=args.timeout,
            )
            initialized = record_internal_rpc(
                evidence,
                transport,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "schematic-quality-mcp", "version": "1.0.0"},
                },
            )
            init_result = initialized.get("result", {})
            if not isinstance(init_result, dict) or "serverInfo" not in init_result:
                raise AdapterError("initialize 응답에 serverInfo가 없습니다", exit_code=1)
            notification = transport.notify("notifications/initialized", {})
            evidence.append({"event": "notification", "sent_at": now_iso(), "request": notification})
            installation = record_internal_rpc(
                evidence,
                transport,
                "tools/call",
                {"name": "get_installation_info", "arguments": {}},
            )
            runtime_identity, runtime_matches = runtime_identity_evidence(
                installation,
                process_pid=transport.process.pid,
                expected_config=backend.config,
                expected_version=args.expected_version,
                expected_commit=args.expected_commit,
            )
            evidence.write_json("runtime-identity.json", runtime_identity)
            evidence.append({"event": "runtime_identity", **runtime_identity})
            if not runtime_matches:
                raise AdapterError(
                    "serving Konnect version/commit이 expected 값과 달라 session을 거부합니다",
                    exit_code=1,
                )
            if needed_toolsets:
                record_internal_rpc(
                    evidence,
                    transport,
                    "tools/call",
                    {"name": "load_toolset", "arguments": {"name": needed_toolsets}},
                )
            listed = record_internal_rpc(evidence, transport, "tools/list", {})
            tools = listed.get("result", {}).get("tools", [])
            if not isinstance(tools, list):
                raise AdapterError("tools/list 응답 schema가 올바르지 않습니다", exit_code=1)
            evidence.write_json("runtime-tool-schemas.json", tools)
            runtime_name_list: list[str] = []
            for item in tools:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("name"), str)
                    or not item["name"]
                    or not isinstance(item.get("inputSchema"), dict)
                ):
                    raise AdapterError("tools/list에 오염된 tool schema가 있습니다", exit_code=1)
                runtime_name_list.append(item["name"])
            if len(runtime_name_list) != len(set(runtime_name_list)):
                raise AdapterError("tools/list에 중복된 tool 이름이 있습니다", exit_code=1)
            runtime_names = set(runtime_name_list)
            unavailable = [item.tool for item in prepared if item.tool not in runtime_names]
            if unavailable:
                raise AdapterError(f"현재 Konnect에 요청 도구가 없습니다: {', '.join(unavailable)}", exit_code=1)

            def guarded_call(tool: str, arguments: dict[str, Any], intent: dict[str, Any]):
                assert_package_unchanged()
                backend.assert_unchanged()
                return transport.call_tool(tool, arguments, intent)

            records, failed = dispatch_prepared_requests(
                policy, prepared, guarded_call, evidence, emit=emit_json
            )
            session_rc = 1 if failed else 0
            evidence.write_json("dispatch-records.json", records)
        except AdapterError:
            raise
        except Exception as error:
            raise AdapterError(f"어댑터 실행 오류: {type(error).__name__}: {error}", exit_code=1) from error
        finally:
            if transport is not None:
                try:
                    server_exit_rc = transport.close()
                except Exception as close_error:
                    session_rc = 1
                    server_close_error = f"{type(close_error).__name__}: {close_error}"
                else:
                    if server_exit_rc != 0:
                        session_rc = 1
            try:
                backend.assert_unchanged()
            except AdapterError as backend_error:
                session_rc = 1
                backend_final_error = str(backend_error)
            try:
                package_identity_final = package_identity.assert_unchanged(package_start)
            except ValueError as package_error:
                session_rc = 1
                package_identity_error = str(package_error)
            final_hash_fields: dict[str, Any]
            try:
                final_cad_hash, final_cad_hashes = policy.cad_hash_evidence()
                final_hash_fields = {
                    "final_cad_hash": final_cad_hash,
                    "final_cad_hashes": final_cad_hashes,
                }
            except Exception as hash_error:
                session_rc = 1
                final_hash_fields = {
                    "final_cad_hash_error": f"{type(hash_error).__name__}: {hash_error}"
                }
            summary = {
                **session,
                "ended_at": now_iso(),
                "session_rc": session_rc,
                "server_exit_rc": server_exit_rc,
                "server_close_error": server_close_error,
                "evidence_dir": str(evidence.directory),
                "runtime_identity": runtime_identity,
                "backend_final_error": backend_final_error,
                "package_identity_final": package_identity_final,
                "package_identity_error": package_identity_error,
                **final_hash_fields,
            }
            evidence.write_json("session-summary.json", summary)
            evidence.append({"event": "session_end", **summary})
        emit_json(
            {
                "ok": session_rc == 0,
                "session_rc": session_rc,
                "server_exit_rc": server_exit_rc,
                "evidence_dir": str(evidence.directory),
                "summary_file": str(evidence.directory / "session-summary.json"),
            }
        )
        return session_rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="계획 선행·경로 allowlist·backend identity를 강제하는 Konnect STDIO 어댑터"
    )
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server-cwd", type=Path, required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--requests", type=Path, required=True, help="tool/arguments JSONL")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except AdapterError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
