#!/usr/bin/env python3
"""격리된 실제 STDIO MCP와 KiCad CLI로 headless 정상행동을 전수 검증한다.

회로 및 라이브러리 파일은 이 스크립트가 직접 생성하거나 편집하지 않는다.
모든 ``*.kicad_*`` 쓰기는 ``tools/call``을 통해 Konnect에 맡기며, Python은
격리 디렉터리·TOML·증거 JSON만 관리한다. 공식 fixture가 필요한 경우에는
바이트 그대로 복제한 뒤 복제본의 모든 변경을 다시 MCP로만 수행한다.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Any, Callable, Iterable
import uuid


ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / "upstream/konnect"
BINARY = SOURCE_ROOT / "target/release/konnect"
LAUNCHER = ROOT / "scripts/run-konnect.sh"
SCHEMA_VERSION = 1

TARGET_TOOLSETS: dict[str, tuple[str, ...]] = {
    "sch_components": (
        "add_component_annotation", "add_schematic_component", "annotate_schematic",
        "batch_get_schematic_pin_locations", "delete_schematic_component",
        "edit_schematic_component", "get_schematic_component",
        "get_schematic_pin_locations", "get_schematic_view", "group_components",
        "list_schematic_components", "move_connected", "move_region",
        "move_schematic_component", "replace_component",
        "reset_schematic_field_positions", "rotate_schematic_component",
        "update_symbols_from_library",
    ),
    "sch_wiring": (
        "add_junction", "add_no_connect", "add_power_symbol",
        "add_schematic_connection", "add_schematic_net_label", "add_wire",
        "batch_add_junction", "batch_add_no_connect", "batch_add_wire",
        "batch_delete_no_connect", "batch_delete_schematic_wire",
        "batch_rotate_labels", "connect_pins", "connect_to_net",
        "delete_no_connect", "delete_schematic_net_label",
        "delete_schematic_wire", "move_labels_by_offset",
        "rotate_schematic_label", "split_wire_at_point",
    ),
    "sch_analysis": (
        "check_schematic_overlaps", "find_orphan_items", "find_shorted_nets",
        "find_single_pin_nets", "get_component_nets", "get_connected_items",
        "get_net_components", "get_net_connections", "get_net_connectivity",
        "get_pin_connections", "get_pin_net_name", "list_schematic_labels",
        "list_schematic_nets", "list_schematic_wires", "trace_from_point",
    ),
    "sch_batch": (
        "add_schematic_text", "batch_connect_pins", "batch_connect_to_net",
        "batch_delete", "batch_delete_schematic_components",
        "batch_edit_schematic_components", "batch_place_components",
        "bulk_move_schematic_components", "connect_passthrough",
        "get_schematic_layout", "validate_component_connections",
        "validate_wire_connections",
    ),
    "sch_bus": ("add_bus", "add_bus_entry", "batch_add_bus", "connect_pins_to_bus"),
    "sch_hierarchy": (
        "add_hierarchical_sheet", "add_sheet_pin", "create_schematic",
        "delete_sheet", "delete_sheet_pin", "duplicate_sheet", "edit_sheet",
        "edit_sheet_pin", "get_sheet_hierarchy", "import_sheet_pins",
        "move_sheet", "renumber_sheet_pages", "set_schematic_page",
        "validate_sheet_pins",
    ),
    "library": (
        "create_footprint", "create_symbol", "delete_symbol", "edit_footprint_pad",
        "get_footprint_info", "get_symbol_info", "list_footprint_libraries",
        "list_library_footprints", "list_symbol_libraries",
        "list_symbols_in_library", "register_footprint_library",
        "register_symbol_library", "search_footprints", "search_symbols",
        "set_footprint_graphics", "set_footprint_metadata", "set_footprint_models",
    ),
    "templates": ("apply_template", "get_template", "list_template_categories", "search_templates"),
    "sch_export": (
        "compare_visual_baseline", "export_netlist_summary", "export_schematic_pdf",
        "export_schematic_svg", "fix_connectivity", "generate_netlist",
        "render_schematic_png", "run_erc", "set_visual_baseline",
        "update_pcb_from_schematic",
    ),
}

EXCLUDED_TOOLS = {
    "update_pcb_from_schematic": "실행 중인 KiCad PCB IPC가 필요한 라이브 전용 도구"
}


class FunctionalError(RuntimeError):
    pass


def expected_tool_names() -> set[str]:
    return {tool for tools in TARGET_TOOLSETS.values() for tool in tools}


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def filesystem_digest(paths: Iterable[Path]) -> str:
    """입력 순서와 무관한 경로·내용 결합 SHA-256을 계산한다."""
    entries: list[tuple[str, Path | None]] = []
    for raw in paths:
        path = Path(raw).resolve()
        if path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file())
            entries.extend((str(item), item) for item in files)
            if not files:
                entries.append((str(path) + "/", None))
        elif path.is_file():
            entries.append((str(path), path))
        else:
            entries.append((str(path), None))
    digest = hashlib.sha256()
    for label, path in sorted(entries, key=lambda item: item[0]):
        digest.update(label.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        if path is None:
            digest.update(b"MISSING")
        else:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def source_worktree_digest() -> str:
    inputs = [SOURCE_ROOT / "Cargo.toml", SOURCE_ROOT / "Cargo.lock"]
    inputs.extend(
        path
        for path in (SOURCE_ROOT / "crates").rglob("*")
        if path.is_file() and path.suffix in {".rs", ".toml", ".proto"}
    )
    return filesystem_digest(inputs)


def write_runtime_config(path: Path, project_dir: Path, ipc_address: str) -> None:
    path.write_text(
        "\n".join(
            [
                'transport = "stdio"',
                'kicad_cli = "/usr/local/bin/kicad-cli"',
                'kicad_binary = "/nonexistent/konnect-headless-kicad"',
                f"project_dir = {json.dumps(str(project_dir.resolve()))}",
                f"ipc_address = {json.dumps(ipc_address)}",
                'log_level = "error"',
                "auto_load_toolsets = false",
                "eager_toolsets = true",
                "",
            ]
        ),
        encoding="utf-8",
    )


def validate_case_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("verdict") == "passed":
        postconditions = record.get("postconditions")
        if not isinstance(postconditions, list) or not postconditions:
            errors.append("passed에는 독립 postcondition이 하나 이상 필요합니다")
        elif any(item.get("passed") is not True for item in postconditions):
            errors.append("실패한 postcondition이 있는데 passed로 기록했습니다")
        if record.get("is_error") is not False:
            errors.append("passed인데 is_error가 false가 아닙니다")
    return errors


def postcondition(
    name: str,
    expected: Any,
    actual: Any,
    *,
    passed: bool | None = None,
    evidence_path: Path | str | None = None,
) -> dict[str, Any]:
    if passed is None:
        passed = actual == expected
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": bool(passed),
        "evidence_path": str(evidence_path) if evidence_path is not None else None,
    }


def parse_tool_content(response: dict[str, Any]) -> tuple[bool, Any, str | None]:
    if "error" in response:
        return True, response["error"], "json_rpc"
    result = response.get("result", {})
    is_error = bool(result.get("isError", False))
    content = result.get("content", [])
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        parsed = {"text": text}
    kind = None
    if isinstance(parsed, dict):
        kind = parsed.get("error", {}).get("kind") if isinstance(parsed.get("error"), dict) else None
    return is_error, parsed, kind


class StdioMcp:
    def __init__(self, config: Path, state_dir: Path, ipc_address: str, stderr_path: Path, timeout: float):
        env = os.environ.copy()
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        env["KONNECT_STATE_DIR"] = str(state_dir.resolve())
        runtime_home = state_dir.parent / "runtime-home"
        runtime_home.mkdir(parents=True, exist_ok=True)
        env["KONNECT_RUNTIME_HOME"] = str(runtime_home.resolve())
        env["KICAD_API_SOCKET"] = ipc_address
        self.timeout = timeout
        self.next_id = 1
        self.stderr_handle = stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(LAUNCHER), "--config", str(config)],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr_handle,
            text=True,
            bufsize=1,
        )
        assert self.process.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], float, dict[str, Any]]:
        identifier = self.next_id
        self.next_id += 1
        request: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            request["params"] = params
        started = time.monotonic()
        self.send(request)
        deadline = started + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise FunctionalError(f"MCP 서버 조기 종료: rc={self.process.returncode}, method={method}")
            events = self.selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = self.process.stdout.readline()
            if not line:
                break
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise FunctionalError(f"stdout JSON-RPC 오염: {line!r}") from error
            if response.get("id") == identifier:
                return response, round((time.monotonic() - started) * 1000, 3), request
        raise FunctionalError(f"MCP timeout: method={method}, id={identifier}")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self.send(payload)

    def close(self) -> int:
        if self.process.stdin is not None and not self.process.stdin.closed:
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
            self.stderr_handle.close()


Postcheck = Callable[[Any], list[dict[str, Any]]]


class FunctionalRunner:
    def __init__(self, client: StdioMcp, output_dir: Path, identity: dict[str, Any], tools: dict[str, dict[str, Any]]):
        self.client = client
        self.output_dir = output_dir
        self.identity = identity
        self.tools = tools
        self.rows: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.seq = 0

    def validate_arguments(self, tool: str, arguments: dict[str, Any]) -> None:
        definition = self.tools.get(tool)
        if definition is None:
            raise FunctionalError(f"tools/list에 없는 도구: {tool}")
        schema = definition.get("inputSchema", {})
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        missing = sorted(required - set(arguments))
        extra = sorted(set(arguments) - set(properties))
        if missing or extra:
            raise FunctionalError(f"{tool} 실측 schema 불일치: missing={missing}, extra={extra}")

    def _exchange(self, method: str, params: dict[str, Any], lane: str) -> tuple[dict[str, Any], float, dict[str, Any]]:
        started_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        response, elapsed, request = self.client.request(method, params)
        self.transcript.append(
            {
                "schema_version": SCHEMA_VERSION,
                "lane": lane,
                "started_at": started_at,
                "elapsed_ms": elapsed,
                "request": request,
                "response": response,
            }
        )
        return response, elapsed, request

    def probe(self, tool: str, arguments: dict[str, Any]) -> Any:
        self.validate_arguments(tool, arguments)
        response, _, _ = self._exchange("tools/call", {"name": tool, "arguments": arguments}, "postcondition")
        is_error, parsed, _ = parse_tool_content(response)
        if is_error:
            raise FunctionalError(f"readback tool 실패: {tool}: {parsed}")
        return parsed

    def setup(self, tool: str, arguments: dict[str, Any]) -> Any:
        self.validate_arguments(tool, arguments)
        response, _, _ = self._exchange("tools/call", {"name": tool, "arguments": arguments}, "setup")
        is_error, parsed, _ = parse_tool_content(response)
        if is_error:
            raise FunctionalError(f"setup tool 실패: {tool}: {parsed}")
        return parsed

    def run_case(
        self,
        toolset: str,
        tool: str,
        case_id: str,
        arguments: dict[str, Any],
        tracked_paths: Iterable[Path],
        check: Postcheck,
        *,
        source_authority: str = "saved_file",
        expect_change: bool | None = None,
        caveats: list[str] | None = None,
        external_conditions: dict[str, Any] | None = None,
    ) -> Any:
        self.seq += 1
        started_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        tracked = [Path(path) for path in tracked_paths]
        before = filesystem_digest(tracked)
        response: dict[str, Any] | None = None
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        elapsed = 0.0
        parsed: Any = None
        error_kind: str | None = None
        is_error = True
        checks: list[dict[str, Any]] = []
        local_caveats = list(caveats or [])
        try:
            self.validate_arguments(tool, arguments)
            response, elapsed, request = self._exchange(
                "tools/call", {"name": tool, "arguments": arguments}, "normal_behavior"
            )
            is_error, parsed, error_kind = parse_tool_content(response)
            if is_error:
                checks = [postcondition("MCP 정상 응답", False, True, passed=False)]
            else:
                checks = check(parsed)
        except Exception as error:  # 각 도구의 실패를 보존하고 다음 사례를 계속한다.
            parsed = {"harness_exception": f"{type(error).__name__}: {error}"}
            response = {"harness_exception": parsed["harness_exception"]}
            checks = [postcondition("하네스 예외 없음", True, False, passed=False)]
            error_kind = "harness_exception"
            local_caveats.append(parsed["harness_exception"])
        after = filesystem_digest(tracked)
        if expect_change is not None:
            checks.append(
                postcondition(
                    "추적 fixture 내용 변경" if expect_change else "추적 fixture 원본 보존",
                    expect_change,
                    before != after,
                )
            )
        verdict = "passed" if not is_error and checks and all(item["passed"] for item in checks) else "failed"
        row = {
            "schema_version": SCHEMA_VERSION,
            "seq": self.seq,
            "lane": "headless_stdio_kicad_cli",
            "toolset": toolset,
            "tool": tool,
            "case_id": case_id,
            "behavior": "success",
            "request": request,
            "response": response,
            "parsed_content": parsed,
            "is_error": is_error,
            "error_kind": error_kind,
            "started_at": started_at,
            "elapsed_ms": elapsed,
            "process_rc": None,
            "binary_sha256": self.identity["binary_sha256"],
            "source_commit": self.identity["source_commit"],
            "source_worktree_sha256": self.identity["source_worktree_sha256"],
            "fixture_before_sha256": before,
            "fixture_after_sha256": after,
            "postconditions": checks,
            "source_authority": source_authority,
            "external_conditions": external_conditions
            or (
                {"kicad_cli_version": self.identity.get("kicad_cli_version")}
                if source_authority == "kicad_cli"
                else {}
            ),
            "verdict": verdict,
            "caveats": local_caveats,
        }
        validation_errors = validate_case_record(row)
        if validation_errors:
            row["verdict"] = "failed"
            row["caveats"].extend(validation_errors)
        self.rows.append(row)
        return parsed

    def mark_unverified(self, toolset: str, tool: str, case_id: str, reason: str) -> None:
        self.seq += 1
        self.rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "seq": self.seq,
                "lane": "headless_stdio_kicad_cli",
                "toolset": toolset,
                "tool": tool,
                "case_id": case_id,
                "behavior": "success",
                "request": None,
                "response": None,
                "parsed_content": None,
                "is_error": None,
                "error_kind": None,
                "started_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "elapsed_ms": 0.0,
                "process_rc": None,
                "binary_sha256": self.identity["binary_sha256"],
                "source_commit": self.identity["source_commit"],
                "source_worktree_sha256": self.identity["source_worktree_sha256"],
                "fixture_before_sha256": None,
                "fixture_after_sha256": None,
                "postconditions": [postcondition("정상행동 구현", True, False, passed=False)],
                "source_authority": "saved_file",
                "external_conditions": {},
                "verdict": "unverified",
                "caveats": [reason],
            }
        )

    def mark_not_applicable(self, toolset: str, tool: str, case_id: str, reason: str) -> None:
        self.seq += 1
        self.rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "seq": self.seq,
                "lane": "headless_stdio_kicad_cli",
                "toolset": toolset,
                "tool": tool,
                "case_id": case_id,
                "behavior": "external",
                "request": None,
                "response": None,
                "parsed_content": None,
                "is_error": None,
                "error_kind": None,
                "started_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "elapsed_ms": 0.0,
                "process_rc": None,
                "binary_sha256": self.identity["binary_sha256"],
                "source_commit": self.identity["source_commit"],
                "source_worktree_sha256": self.identity["source_worktree_sha256"],
                "fixture_before_sha256": None,
                "fixture_after_sha256": None,
                "postconditions": [],
                "source_authority": "live",
                "external_conditions": {"requires_live_kicad_pcb_ipc": True},
                "verdict": "not_applicable",
                "caveats": [reason],
            }
        )


def list_field(value: Any, *names: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for name in names:
            candidate = value.get(name)
            if isinstance(candidate, list):
                return candidate
    return []


def dict_field(value: Any, name: str) -> dict[str, Any]:
    candidate = value.get(name) if isinstance(value, dict) else None
    return candidate if isinstance(candidate, dict) else {}


def response_has(value: Any, key: str) -> list[dict[str, Any]]:
    return [postcondition(f"응답 필드 {key}", True, isinstance(value, dict) and key in value)]


def component_by_reference(value: Any, reference: str) -> dict[str, Any] | None:
    for item in list_field(value, "components", "symbols"):
        if isinstance(item, dict) and item.get("reference") == reference:
            return item
    return None


def netlist_summary_semantics(value: Any) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
    semantics = []
    for component in list_field(value, "components"):
        if not isinstance(component, dict) or not isinstance(component.get("reference"), str):
            continue
        pins = []
        for pin in list_field(component, "pins"):
            if isinstance(pin, dict):
                pins.append((str(pin.get("number", "")), str(pin.get("net", ""))))
        semantics.append((component["reference"], tuple(sorted(pins))))
    return sorted(semantics)


def suite_library(runner: FunctionalRunner, project: Path) -> dict[str, Path]:
    library_dir = project / "libraries"
    pretty = library_dir / "Headless.pretty"
    library_dir.mkdir(parents=True, exist_ok=True)
    pretty.mkdir(parents=True, exist_ok=True)
    symbol_lib = library_dir / "Headless.kicad_sym"
    footprint = pretty / "Headless_2Pin.kicad_mod"
    lock = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))
    kicad_version = lock["components"]["kicad"]["tag"]
    connector_symdir = Path(f"/opt/kicad/{kicad_version}/share/kicad/symbols/Connector_Generic.kicad_symdir")
    if not connector_symdir.is_dir():
        raise FunctionalError(f"설치된 KiCad 10 symdir 누락: {connector_symdir}")

    footprint_args = {
        "output": str(footprint),
        "name": "Headless_2Pin",
        "description": "Konnect headless functional fixture",
        "body_width": 5.0,
        "body_height": 3.0,
        "package_type": "smd",
        "pads": [
            {"number": "1", "type": "smd", "shape": "rect", "x": -2.0, "y": 0.0, "width": 1.5, "height": 1.2},
            {"number": "2", "type": "smd", "shape": "rect", "x": 2.0, "y": 0.0, "width": 1.5, "height": 1.2},
        ],
    }
    runner.run_case(
        "library", "create_footprint", "library.create_footprint", footprint_args,
        [footprint],
        lambda value: [
            postcondition("파일 생성", True, footprint.is_file(), evidence_path=footprint),
            postcondition("pad_count 응답", 2, value.get("pad_count") if isinstance(value, dict) else None),
        ],
        expect_change=True,
    )

    symbol_args = {
        "library_path": str(symbol_lib),
        "name": "TwoPin",
        "reference_prefix": "R",
        "value": "TwoPin",
        "pins": [
            {"number": "1", "name": "A", "type": "passive", "x": -5.08, "y": 0.0, "angle": 0, "length": 2.54},
            {"number": "2", "name": "B", "type": "passive", "x": 5.08, "y": 0.0, "angle": 180, "length": 2.54},
        ],
    }
    runner.run_case(
        "library", "create_symbol", "library.create_symbol", symbol_args, [symbol_lib],
        lambda value: [
            postcondition("심볼 파일 생성", True, symbol_lib.is_file(), evidence_path=symbol_lib),
            postcondition("작성 심볼 이름", "TwoPin", value.get("symbol") if isinstance(value, dict) else None),
        ],
        expect_change=True,
    )
    runner.setup(
        "create_symbol",
        {
            "library_path": str(symbol_lib), "name": "FourPin", "reference_prefix": "U", "value": "FourPin",
            "pins": [
                {"number": "1", "name": "D0", "type": "bidirectional", "x": -5.08, "y": -2.54, "angle": 0},
                {"number": "2", "name": "D1", "type": "bidirectional", "x": -5.08, "y": 2.54, "angle": 0},
                {"number": "3", "name": "D2", "type": "bidirectional", "x": 5.08, "y": 2.54, "angle": 180},
                {"number": "4", "name": "D3", "type": "bidirectional", "x": 5.08, "y": -2.54, "angle": 180},
            ],
        },
    )
    runner.setup(
        "create_symbol",
        {
            "library_path": str(symbol_lib), "name": "DeleteMe", "reference_prefix": "X", "value": "DeleteMe",
            "pins": [{"number": "1", "name": "P", "type": "passive", "x": -5.08, "y": 0.0, "angle": 0}],
        },
    )

    project_arg = str(project)
    runner.run_case(
        "library", "register_symbol_library", "library.register_symbol_library",
        {"library_path": str(connector_symdir), "nickname": "Connector_Generic", "scope": "project", "project": project_arg, "replace_existing": True},
        [project / "sym-lib-table"],
        lambda value: [
            postcondition("등록 nickname", "Connector_Generic", value.get("nickname") if isinstance(value, dict) else None),
            postcondition("project sym-lib-table 생성", True, (project / "sym-lib-table").is_file()),
        ],
        expect_change=True,
    )
    runner.setup(
        "register_symbol_library",
        {"library_path": str(symbol_lib), "nickname": "Headless", "scope": "project", "project": project_arg, "replace_existing": True},
    )
    # search_footprints는 project 인자가 없으므로 프로젝트 격리 HOME의 전역 표에
    # 고정 nickname 한 개를 MCP로 등록한다. 반복 실행은 replace_existing으로 갱신한다.
    runner.run_case(
        "library", "register_footprint_library", "library.register_footprint_library",
        {"library_path": str(pretty), "nickname": "KonnectHeadlessFunctional", "scope": "global", "replace_existing": True},
        [pretty],
        lambda value: [
            postcondition("등록 nickname", "KonnectHeadlessFunctional", value.get("nickname") if isinstance(value, dict) else None),
            postcondition("등록 scope", "global", value.get("scope") if isinstance(value, dict) else None),
        ],
        expect_change=False,
        caveats=["전역은 실제 사용자 HOME이 아닌 scripts/run-konnect.sh의 격리 .runtime-home입니다"],
    )

    runner.run_case(
        "library", "get_footprint_info", "library.get_footprint_info",
        {"footprint_path": str(footprint), "include_pads": True, "include_graphics": True},
        [footprint],
        lambda value: [
            postcondition("pad_count", 2, value.get("pad_count") if isinstance(value, dict) else None),
            postcondition("pads 배열", True, len(list_field(value, "pads")) == 2),
        ],
        expect_change=False,
    )
    runner.run_case(
        "library", "edit_footprint_pad", "library.edit_footprint_pad",
        {"footprint_path": str(footprint), "pad_number": "1", "width": 2.0, "height": 1.4},
        [footprint],
        lambda value: [
            postcondition("updated_count", 1, value.get("updated_count") if isinstance(value, dict) else None),
            postcondition("pad 수 보존", 2, runner.probe("get_footprint_info", {"footprint_path": str(footprint), "include_pads": True}).get("pad_count")),
        ],
        expect_change=True,
    )
    graphics = [{
        "type": "line", "start": {"x": -2.5, "y": -2.0}, "end": {"x": 2.5, "y": -2.0}, "stroke_width_mm": 0.2
    }]
    runner.run_case(
        "library", "set_footprint_graphics", "library.set_footprint_graphics",
        {"footprint_path": str(footprint), "selector": {"layer": "F.SilkS"}, "mode": "replace", "graphics": graphics},
        [footprint],
        lambda value: [
            postcondition("graphics 변경 count", True, isinstance(value, dict) and any(isinstance(value.get(k), int) for k in ("added_count", "matched_count", "graphic_count", "written_count", "count"))),
            postcondition("F.SilkS 그래픽 readback", True, len(list_field(runner.probe("get_footprint_info", {"footprint_path": str(footprint), "include_graphics": True, "graphics_layer": "F.SilkS"}), "graphics")) >= 1),
        ],
        expect_change=True,
    )
    runner.run_case(
        "library", "set_footprint_metadata", "library.set_footprint_metadata",
        {"footprint_path": str(footprint), "description": "Headless metadata verified", "tags": ["headless", "functional"], "attributes": ["smd"]},
        [footprint],
        lambda value: [
            postcondition("description readback", "Headless metadata verified", runner.probe("get_footprint_info", {"footprint_path": str(footprint)}).get("description")),
            postcondition("도구 성공 필드", True, isinstance(value, dict)),
        ],
        expect_change=True,
    )
    model = {"path": "${KICAD10_3DMODEL_DIR}/Connector.3dshapes/PinHeader_1x02_P2.54mm_Vertical.step"}
    runner.run_case(
        "library", "set_footprint_models", "library.set_footprint_models",
        {"footprint_path": str(footprint), "mode": "replace", "models": [model]},
        [footprint],
        lambda value: [
            postcondition("3D model readback", True, runner.probe("get_footprint_info", {"footprint_path": str(footprint)}).get("has_3d_model")),
            postcondition("도구 성공 필드", True, isinstance(value, dict)),
        ],
        expect_change=True,
    )
    runner.run_case(
        "library", "get_symbol_info", "library.get_symbol_info",
        {"lib_id": "Headless:TwoPin", "project_dir": str(project)}, [symbol_lib, project / "sym-lib-table"],
        lambda value: [
            postcondition("심볼 이름", "TwoPin", value.get("name") if isinstance(value, dict) else None),
            postcondition("pin_count", 2, value.get("pin_count") if isinstance(value, dict) else None),
        ], expect_change=False,
    )
    runner.run_case(
        "library", "list_symbols_in_library", "library.list_symbols_in_library",
        {"library_path": str(connector_symdir), "limit": 500}, [connector_symdir],
        lambda value: [postcondition("Conn_01x02 포함", True, "Conn_01x02" in list_field(value, "symbols"))],
        expect_change=False,
    )
    runner.run_case(
        "library", "search_symbols", "library.search_symbols",
        {"query": "Conn_01x02", "project_dir": str(project), "limit": 20}, [connector_symdir, project / "sym-lib-table"],
        lambda value: [postcondition("Connector_Generic:Conn_01x02 검색", True, any(item.get("id") == "Connector_Generic:Conn_01x02" for item in list_field(value, "results") if isinstance(item, dict)))],
        expect_change=False,
    )
    runner.run_case(
        "library", "list_symbol_libraries", "library.list_symbol_libraries",
        {"scope": "project", "project": str(project / "headless.kicad_pro")}, [project / "sym-lib-table"],
        lambda value: [
            postcondition("Headless 등록 readback", True, any(item.get("nickname") == "Headless" for item in list_field(value, "libraries") if isinstance(item, dict)),),
            postcondition("Connector_Generic 등록 readback", True, any(item.get("nickname") == "Connector_Generic" for item in list_field(value, "libraries") if isinstance(item, dict))),
        ],
        expect_change=False,
    )
    runner.run_case(
        "library", "list_library_footprints", "library.list_library_footprints",
        {"library_path": str(pretty)}, [pretty],
        lambda value: [postcondition("Headless_2Pin 포함", True, "Headless_2Pin" in list_field(value, "footprints"))],
        expect_change=False,
    )
    runner.run_case(
        "library", "search_footprints", "library.search_footprints",
        {"query": "Headless_2Pin", "limit": 20}, [pretty],
        lambda value: [postcondition("footprint 검색 결과", True, any(item.get("name") == "Headless_2Pin" for item in list_field(value, "results") if isinstance(item, dict)))],
        expect_change=False,
    )
    runner.run_case(
        "library", "list_footprint_libraries", "library.list_footprint_libraries",
        {"scope": "global"}, [pretty],
        lambda value: [postcondition("격리 전역 등록 readback", True, any(item.get("nickname") == "KonnectHeadlessFunctional" for item in list_field(value, "libraries") if isinstance(item, dict)))],
        expect_change=False,
    )
    runner.run_case(
        "library", "delete_symbol", "library.delete_symbol",
        {"library_path": str(symbol_lib), "symbol_name": "DeleteMe"}, [symbol_lib],
        lambda value: [postcondition("DeleteMe 제거 readback", False, "DeleteMe" in list_field(runner.probe("list_symbols_in_library", {"library_path": str(symbol_lib)}), "symbols"))],
        expect_change=True,
    )
    return {"symbol_lib": symbol_lib, "pretty": pretty, "footprint": footprint}


def json_contains(value: Any, needle: str) -> bool:
    return needle in json.dumps(value, ensure_ascii=False, sort_keys=True)


def suite_hierarchy(runner: FunctionalRunner, project: Path) -> dict[str, Path]:
    main = project / "main.kicad_sch"
    child = project / "child.kicad_sch"
    duplicate = project / "child-copy.kicad_sch"
    runner.run_case(
        "sch_hierarchy", "create_schematic", "hierarchy.create_schematic",
        {"path": str(main), "size": "A4", "portrait": False}, [main],
        lambda value: [
            postcondition("blank schematic 생성", True, main.is_file(), evidence_path=main),
            postcondition("생성 경로 응답", True, json_contains(value, str(main))),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "set_schematic_page", "hierarchy.set_schematic_page",
        {"schematic": str(main), "size": "A3", "portrait": True}, [main],
        lambda value: [
            postcondition("A3 응답", True, json_contains(value, "A3")),
            postcondition("portrait 응답", True, json_contains(value, "portrait")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "add_hierarchical_sheet", "hierarchy.add_hierarchical_sheet",
        {
            "schematic": str(main), "sheet_file": "child.kicad_sch", "sheet_name": "Child",
            "x": 50.8, "y": 50.8, "width": 50.8, "height": 25.4,
        }, [main, child],
        lambda value: [
            postcondition("child 파일 생성", True, child.is_file(), evidence_path=child),
            postcondition("Child sheet readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "Child")),
        ], expect_change=True,
    )
    # import_sheet_pins의 실제 정상 입력은 child의 hierarchical_label이다.
    runner.setup(
        "add_schematic_net_label",
        {"schematic": str(child), "net": "CHILD_IO", "x": 25.4, "y": 25.4, "label_type": "hierarchical_label", "shape": "bidirectional"},
    )
    runner.run_case(
        "sch_hierarchy", "import_sheet_pins", "hierarchy.import_sheet_pins",
        {"schematic": str(main), "sheet_name": "Child", "side": "right"}, [main, child],
        lambda value: [
            postcondition("CHILD_IO import 응답", True, json_contains(value, "CHILD_IO")),
            postcondition("CHILD_IO hierarchy readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "CHILD_IO")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "add_sheet_pin", "hierarchy.add_sheet_pin",
        {"schematic": str(main), "sheet_name": "Child", "pin_name": "MANUAL", "pin_type": "input", "side": "right", "x": 101.6, "y": 63.5},
        [main],
        lambda value: [postcondition("MANUAL pin readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "MANUAL"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "edit_sheet_pin", "hierarchy.edit_sheet_pin",
        {"schematic": str(main), "sheet_name": "Child", "pin_name": "MANUAL", "new_name": "MANUAL_EDITED", "pin_type": "bidirectional"},
        [main],
        lambda value: [postcondition("편집 pin readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "MANUAL_EDITED"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "delete_sheet_pin", "hierarchy.delete_sheet_pin",
        {"schematic": str(main), "sheet_name": "Child", "pin_name": "MANUAL_EDITED"}, [main],
        lambda value: [postcondition("삭제 pin 부재", False, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "MANUAL_EDITED"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "move_sheet", "hierarchy.move_sheet",
        {"schematic": str(main), "sheet_name": "Child", "x": 76.2, "y": 50.8}, [main],
        lambda value: [
            postcondition("이동 x 응답", True, json_contains(value, "76.2")),
            postcondition("Child 유지", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "Child")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "edit_sheet", "hierarchy.edit_sheet",
        {"schematic": str(main), "sheet_name": "Child", "new_name": "ChildRenamed", "width": 55.88, "height": 30.48}, [main],
        lambda value: [postcondition("renamed sheet readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "ChildRenamed"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "duplicate_sheet", "hierarchy.duplicate_sheet",
        {"schematic": str(main), "source_sheet_name": "ChildRenamed", "new_sheet_name": "ChildCopy", "new_file": "child-copy.kicad_sch"},
        [main, child, duplicate],
        lambda value: [
            postcondition("duplicate 파일 생성", True, duplicate.is_file(), evidence_path=duplicate),
            postcondition("ChildCopy hierarchy readback", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "ChildCopy")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "renumber_sheet_pages", "hierarchy.renumber_sheet_pages",
        {"schematic": str(main), "project_name": "headless"}, [main, child, duplicate],
        lambda value: [
            postcondition("페이지 배정 응답", True, isinstance(value, dict)),
            postcondition("두 child 유지", True, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main), "project_name": "headless"}), "ChildCopy")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_hierarchy", "get_sheet_hierarchy", "hierarchy.get_sheet_hierarchy",
        {"schematic": str(main), "project_name": "headless"}, [main, child, duplicate],
        lambda value: [
            postcondition("ChildRenamed 포함", True, json_contains(value, "ChildRenamed")),
            postcondition("ChildCopy 포함", True, json_contains(value, "ChildCopy")),
        ], expect_change=False,
    )
    runner.run_case(
        "sch_hierarchy", "validate_sheet_pins", "hierarchy.validate_sheet_pins",
        {"schematic": str(main)}, [main, child, duplicate],
        lambda value: [postcondition("검증 구조 응답", True, isinstance(value, dict))],
        expect_change=False,
    )
    child_hash = sha256_file(child)
    runner.run_case(
        "sch_hierarchy", "delete_sheet", "hierarchy.delete_sheet",
        {"schematic": str(main), "sheet_name": "ChildRenamed"}, [main, child],
        lambda value: [
            postcondition("parent에서 sheet 제거", False, json_contains(runner.probe("get_sheet_hierarchy", {"schematic": str(main)}), "ChildRenamed")),
            postcondition("child 파일 보존", child_hash, sha256_file(child), evidence_path=child),
        ], expect_change=True,
    )

    fixtures = {"main": main, "child": child, "duplicate": duplicate}
    for name in ("components", "wiring", "batch", "bus", "templates", "export"):
        path = project / f"{name}.kicad_sch"
        runner.setup("create_schematic", {"path": str(path), "size": "A4"})
        fixtures[name] = path
    return fixtures


def first_existing_path(value: Any) -> Path | None:
    if isinstance(value, str):
        path = Path(value)
        return path if path.is_file() else None
    if isinstance(value, dict):
        for key in ("path", "output", "svg", "svg_path", "png", "png_path", "pdf", "pdf_path", "file"):
            candidate = value.get(key)
            if isinstance(candidate, str) and Path(candidate).is_file():
                return Path(candidate)
        for candidate in value.values():
            found = first_existing_path(candidate)
            if found is not None:
                return found
    if isinstance(value, list):
        for candidate in value:
            found = first_existing_path(candidate)
            if found is not None:
                return found
    return None


def suite_components(runner: FunctionalRunner, schematic: Path) -> None:
    add_r1 = {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": "R1", "value": "1k", "x": 50.8, "y": 50.8}
    runner.run_case(
        "sch_components", "add_schematic_component", "components.add",
        add_r1, [schematic],
        lambda value: [
            postcondition("R1 응답", True, json_contains(value, "R1")),
            postcondition("R1 readback", True, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "R1") is not None),
        ], expect_change=True,
    )
    runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": "R2", "value": "2k", "x": 76.2, "y": 50.8})
    runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": "R?", "value": "3k", "x": 101.6, "y": 50.8})

    runner.setup("connect_pins", {"schematic": str(schematic), "ref1": "R1", "pin1": "2", "ref2": "R2", "pin2": "1"})
    runner.setup("connect_to_net", {"schematic": str(schematic), "reference": "R1", "pin_number": "1", "net": "HEADLESS_MOVE_NET", "stub_length": 0})
    move_summary_before = netlist_summary_semantics(
        runner.probe("export_netlist_summary", {"schematic": str(schematic)})
    )
    original_wires = {
        item.get("uuid"): (item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2"))
        for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")
        if isinstance(item, dict) and isinstance(item.get("uuid"), str)
    }
    runner.run_case(
        "sch_components", "move_connected", "components.move_connected",
        {"schematic": str(schematic), "reference": "R1", "x": 53.34, "y": 53.34}, [schematic],
        lambda value: [
            postcondition("R1 connected move readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "53.34")),
            postcondition("handler connectivity proof", True, isinstance(value, dict) and value.get("connectivity_preserved") is True and value.get("kicad_cli_netlist_preserved") is True),
            postcondition("KiCad netlist semantic equivalence", move_summary_before, netlist_summary_semantics(runner.probe("export_netlist_summary", {"schematic": str(schematic)}))),
            postcondition(
                "기존 wire UUID와 remote endpoint 보존",
                original_wires,
                {
                    item.get("uuid"): (item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2"))
                    for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")
                    if isinstance(item, dict) and item.get("uuid") in original_wires
                },
            ),
        ],
        expect_change=True,
        source_authority="kicad_cli",
    )

    runner.run_case(
        "sch_components", "list_schematic_components", "components.list",
        {"schematic": str(schematic)}, [schematic],
        lambda value: [
            postcondition("R1 포함", True, component_by_reference(value, "R1") is not None),
            postcondition("R2 포함", True, component_by_reference(value, "R2") is not None),
            postcondition("미주석 R? 포함", True, component_by_reference(value, "R?") is not None),
        ], expect_change=False,
    )
    runner.run_case(
        "sch_components", "get_schematic_component", "components.get",
        {"schematic": str(schematic), "reference": "R1"}, [schematic],
        lambda value: [postcondition("R1 reference", True, json_contains(value, "R1"))],
        expect_change=False,
    )
    runner.run_case(
        "sch_components", "get_schematic_pin_locations", "components.pin_locations",
        {"schematic": str(schematic), "reference": "R1"}, [schematic],
        lambda value: [postcondition("두 핀 좌표", 2, len(list_field(value, "pins")))],
        expect_change=False,
    )
    runner.run_case(
        "sch_components", "batch_get_schematic_pin_locations", "components.batch_pin_locations",
        {"schematic": str(schematic), "references": ["R1", "R2"]}, [schematic],
        lambda value: [
            postcondition("R1 batch 좌표", True, json_contains(value, "R1")),
            postcondition("R2 batch 좌표", True, json_contains(value, "R2")),
        ], expect_change=False,
    )
    runner.run_case(
        "sch_components", "annotate_schematic", "components.annotate",
        {"schematic": str(schematic), "resolve_duplicates": True, "dry_run": False}, [schematic],
        lambda value: [
            postcondition("R? 제거", False, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "R?") is not None),
            postcondition("R3 생성", True, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "R3") is not None),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_components", "add_component_annotation", "components.annotation",
        {"schematic": str(schematic), "reference": "R1", "key": "MPN", "value": "HEADLESS-001"}, [schematic],
        lambda value: [postcondition("MPN readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "HEADLESS-001"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_components", "group_components", "components.group",
        {"schematic": str(schematic), "references": ["R1", "R2"], "group_name": "HEADLESS_GROUP"}, [schematic],
        lambda value: [
            postcondition("R1 group readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "HEADLESS_GROUP")),
            postcondition("R2 group readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R2"}), "HEADLESS_GROUP")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_components", "edit_schematic_component", "components.edit",
        {"schematic": str(schematic), "reference": "R1", "value": "4.7k", "footprint": "KonnectHeadlessFunctional:Headless_2Pin"}, [schematic],
        lambda value: [
            postcondition("Value readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "4.7k")),
            postcondition("Footprint readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "Headless_2Pin")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_components", "move_schematic_component", "components.move",
        {"schematic": str(schematic), "reference": "R1", "x": 55.88, "y": 55.88}, [schematic],
        lambda value: [postcondition("이동 위치 readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "55.88"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_components", "rotate_schematic_component", "components.rotate",
        {"schematic": str(schematic), "reference": "R1", "rotation": 90}, [schematic],
        lambda value: [postcondition("rotation readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R1"}), "90"))],
        expect_change=True,
    )
    before_r2 = runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R2"})
    runner.run_case(
        "sch_components", "move_region", "components.move_region",
        {"schematic": str(schematic), "x1": 70.0, "y1": 45.0, "x2": 82.0, "y2": 56.0, "dx": 5.08, "dy": 5.08}, [schematic],
        lambda value: [postcondition("R2 위치 변경", False, runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R2"}) == before_r2)],
        expect_change=True,
    )
    runner.run_case(
        "sch_components", "replace_component", "components.replace",
        {"schematic": str(schematic), "reference": "R2", "new_lib_id": "Headless:FourPin"}, [schematic],
        lambda value: [
            postcondition("FourPin lib readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "R2"}), "FourPin")),
            postcondition("네 핀 readback", 4, len(list_field(runner.probe("get_schematic_pin_locations", {"schematic": str(schematic), "reference": "R2"}), "pins"))),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_components", "reset_schematic_field_positions", "components.reset_fields_dry_run",
        {"schematic": str(schematic), "references": ["R1", "R2"], "dry_run": True}, [schematic],
        lambda value: [postcondition("dry_run 결과 구조", True, isinstance(value, dict))],
        expect_change=False,
    )
    runner.run_case(
        "sch_components", "update_symbols_from_library", "components.update_symbols_dry_run",
        {"schematic": str(schematic), "references": ["R1", "R2"], "dry_run": True, "allow_pin_moves": False}, [schematic],
        lambda value: [postcondition("library update 평가 구조", True, isinstance(value, dict))],
        expect_change=False,
    )
    runner.run_case(
        "sch_components", "get_schematic_view", "components.view",
        {"schematic": str(schematic)}, [schematic],
        lambda value: [
            postcondition("SVG 생성", True, first_existing_path(value) is not None, evidence_path=first_existing_path(value)),
            postcondition("원본 회로 보존", True, schematic.is_file()),
        ], expect_change=False, source_authority="kicad_cli",
        external_conditions={"kicad_cli": "/usr/local/bin/kicad-cli"},
    )
    runner.run_case(
        "sch_components", "delete_schematic_component", "components.delete",
        {"schematic": str(schematic), "reference": "R3"}, [schematic],
        lambda value: [postcondition("R3 부재 readback", False, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "R3") is not None)],
        expect_change=True,
    )


def pin_xy(runner: FunctionalRunner, schematic: Path, reference: str, number: str) -> tuple[float, float]:
    value = runner.probe(
        "get_schematic_pin_locations",
        {"schematic": str(schematic), "reference": reference},
    )
    for pin in list_field(value, "pins"):
        if isinstance(pin, dict) and str(pin.get("number")) == str(number):
            x, y = pin.get("x"), pin.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return float(x), float(y)
    raise FunctionalError(f"핀 좌표를 찾을 수 없습니다: {reference}.{number}: {value}")


def wire_matches(item: dict[str, Any], points: tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = points
    values = (item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2"))
    reverse = (item.get("x2"), item.get("y2"), item.get("x1"), item.get("y1"))
    return values == points or reverse == points


def suite_wiring(runner: FunctionalRunner, schematic: Path) -> dict[str, Any]:
    for reference, x, y in (("W1", 50.8, 50.8), ("W2", 76.2, 50.8), ("W3", 50.8, 76.2)):
        runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": reference, "x": x, "y": y})
    w1p1 = pin_xy(runner, schematic, "W1", "1")
    w1p2 = pin_xy(runner, schematic, "W1", "2")
    w2p1 = pin_xy(runner, schematic, "W2", "1")
    w3p1 = pin_xy(runner, schematic, "W3", "1")
    w3p2 = pin_xy(runner, schematic, "W3", "2")

    runner.run_case(
        "sch_wiring", "add_wire", "wiring.add_wire",
        {"schematic": str(schematic), "x1": 20.32, "y1": 20.32, "x2": 30.48, "y2": 20.32}, [schematic],
        lambda value: [postcondition("wire readback", True, any(wire_matches(item, (20.32, 20.32, 30.48, 20.32)) for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires") if isinstance(item, dict)))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "add_schematic_connection", "wiring.add_connection",
        {"schematic": str(schematic), "x1": 20.32, "y1": 30.48, "x2": 30.48, "y2": 40.64}, [schematic],
        lambda value: [postcondition("자동 경로 segment", True, len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")) >= 3)],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "add_schematic_net_label", "wiring.add_label",
        {"schematic": str(schematic), "net": "LABEL_FLOW", "x": 20.32, "y": 20.32, "label_type": "net_label", "rotation": 0}, [schematic],
        lambda value: [postcondition("LABEL_FLOW readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "LABEL_FLOW"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "move_labels_by_offset", "wiring.move_labels",
        {"schematic": str(schematic), "net": "LABEL_FLOW", "dx": 2.54, "dy": 0.0}, [schematic],
        lambda value: [postcondition("이동 label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "22.86"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "rotate_schematic_label", "wiring.rotate_label",
        {"schematic": str(schematic), "net": "LABEL_FLOW", "x": 22.86, "y": 20.32, "rotation": 90}, [schematic],
        lambda value: [postcondition("90도 label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "90"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "batch_rotate_labels", "wiring.batch_rotate_labels",
        {"schematic": str(schematic), "labels": [{"net": "LABEL_FLOW", "x": 22.86, "y": 20.32, "rotation": 180}]}, [schematic],
        lambda value: [postcondition("180도 label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "180"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "connect_pins", "wiring.connect_pins",
        {"schematic": str(schematic), "ref1": "W1", "pin1": "2", "ref2": "W2", "pin2": "1"}, [schematic],
        lambda value: [postcondition("W1.2-W2.1 wire readback", True, any(wire_matches(item, (w1p2[0], w1p2[1], w2p1[0], w2p1[1])) for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires") if isinstance(item, dict)))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "connect_to_net", "wiring.connect_to_net",
        {"schematic": str(schematic), "reference": "W1", "pin_number": "1", "net": "HEADLESS_NET", "stub_length": 2.54, "direction": "left", "label_type": "net_label"}, [schematic],
        lambda value: [postcondition("HEADLESS_NET pin readback", "HEADLESS_NET", runner.probe("get_pin_net_name", {"schematic": str(schematic), "reference": "W1", "pin_number": "1"}).get("net"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "add_power_symbol", "wiring.add_power",
        {"schematic": str(schematic), "power_net": "GND", "x": 25.4, "y": 50.8, "rotation": 0}, [schematic],
        lambda value: [postcondition("GND symbol readback", True, json_contains(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "GND"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "add_no_connect", "wiring.add_no_connect",
        {"schematic": str(schematic), "x": w3p1[0], "y": w3p1[1]}, [schematic],
        lambda value: [postcondition("no-connect 좌표 응답", True, json_contains(value, str(w3p1[0])))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "delete_no_connect", "wiring.delete_no_connect",
        {"schematic": str(schematic), "x": w3p1[0], "y": w3p1[1]}, [schematic],
        lambda value: [postcondition("삭제 확인 응답", True, json_contains(value, "deleted"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "batch_add_no_connect", "wiring.batch_add_no_connect",
        {"schematic": str(schematic), "positions": [{"x": w3p1[0], "y": w3p1[1]}, {"x": w3p2[0], "y": w3p2[1]}]}, [schematic],
        lambda value: [postcondition("batch add count", True, json_contains(value, "2"))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "batch_delete_no_connect", "wiring.batch_delete_no_connect",
        {"schematic": str(schematic), "positions": [{"x": w3p1[0], "y": w3p1[1]}, {"x": w3p2[0], "y": w3p2[1]}]}, [schematic],
        lambda value: [postcondition("batch delete count", True, json_contains(value, "2"))],
        expect_change=True,
    )
    # junction의 의미 있는 입력을 위해 두 직교 wire를 먼저 만든다.
    runner.setup("batch_add_wire", {"schematic": str(schematic), "wires": [
        {"x1": 30.48, "y1": 70.0, "x2": 40.64, "y2": 70.0},
        {"x1": 35.56, "y1": 65.0, "x2": 35.56, "y2": 75.0},
    ]})
    runner.run_case(
        "sch_wiring", "add_junction", "wiring.add_junction",
        {"schematic": str(schematic), "x": 35.56, "y": 70.0}, [schematic],
        lambda value: [postcondition("junction trace readback", True, json_contains(runner.probe("trace_from_point", {"schematic": str(schematic), "x": 35.56, "y": 70.0}), "junction"))],
        expect_change=True,
    )
    runner.setup("batch_add_wire", {"schematic": str(schematic), "wires": [
        {"x1": 45.72, "y1": 70.0, "x2": 55.88, "y2": 70.0},
        {"x1": 50.8, "y1": 65.0, "x2": 50.8, "y2": 75.0},
        {"x1": 60.96, "y1": 70.0, "x2": 71.12, "y2": 70.0},
        {"x1": 66.04, "y1": 65.0, "x2": 66.04, "y2": 75.0},
    ]})
    runner.run_case(
        "sch_wiring", "batch_add_junction", "wiring.batch_add_junction",
        {"schematic": str(schematic), "positions": [{"x": 50.8, "y": 70.0}, {"x": 66.04, "y": 70.0}]}, [schematic],
        lambda value: [postcondition("두 junction 응답", True, json_contains(value, "2"))],
        expect_change=True,
    )
    before_batch = len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires"))
    runner.run_case(
        "sch_wiring", "batch_add_wire", "wiring.batch_add_wire",
        {"schematic": str(schematic), "wires": [
            {"x1": 80.0, "y1": 80.0, "x2": 90.0, "y2": 80.0},
            {"x1": 80.0, "y1": 85.0, "x2": 90.0, "y2": 85.0},
        ]}, [schematic],
        lambda value: [postcondition("wire 수 +2", before_batch + 2, len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")))],
        expect_change=True,
    )
    wires_after_batch = list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")
    batch_wires = [item for item in wires_after_batch[before_batch:] if isinstance(item, dict)]
    batch_uuids = [item.get("uuid") for item in batch_wires if isinstance(item.get("uuid"), str)]
    runner.run_case(
        "sch_wiring", "batch_delete_schematic_wire", "wiring.batch_delete_wire",
        {"schematic": str(schematic), "uuids": batch_uuids}, [schematic],
        lambda value: [postcondition("batch wire UUID 제거", 0, sum(1 for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires") if isinstance(item, dict) and item.get("uuid") in batch_uuids))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "delete_schematic_wire", "wiring.delete_wire",
        {"schematic": str(schematic), "x1": 20.32, "y1": 20.32, "x2": 30.48, "y2": 20.32}, [schematic],
        lambda value: [postcondition("지정 wire 부재", False, any(wire_matches(item, (20.32, 20.32, 30.48, 20.32)) for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires") if isinstance(item, dict)))],
        expect_change=True,
    )
    runner.setup("add_wire", {"schematic": str(schematic), "x1": 100.33, "y1": 100.33, "x2": 119.38, "y2": 100.33})
    before_split = len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires"))
    runner.run_case(
        "sch_wiring", "split_wire_at_point", "wiring.split_wire",
        {"schematic": str(schematic), "x": 109.22, "y": 100.33}, [schematic],
        lambda value: [postcondition("split 후 wire +1", before_split + 1, len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")))],
        expect_change=True,
    )
    runner.run_case(
        "sch_wiring", "delete_schematic_net_label", "wiring.delete_label",
        {"schematic": str(schematic), "net": "LABEL_FLOW", "x": 22.86, "y": 20.32}, [schematic],
        lambda value: [postcondition("LABEL_FLOW 부재", False, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "LABEL_FLOW"))],
        expect_change=True,
    )
    return {"w1p1": w1p1, "w1p2": w1p2, "w2p1": w2p1}


def suite_analysis(runner: FunctionalRunner, schematic: Path, points: dict[str, Any]) -> None:
    read_cases: list[tuple[str, dict[str, Any], Callable[[Any], bool], str]] = [
        ("list_schematic_wires", {"schematic": str(schematic)}, lambda v: len(list_field(v, "wires")) > 0, "wire 목록 비어 있지 않음"),
        ("list_schematic_labels", {"schematic": str(schematic)}, lambda v: json_contains(v, "HEADLESS_NET"), "HEADLESS_NET label 포함"),
        ("list_schematic_nets", {"schematic": str(schematic)}, lambda v: json_contains(v, "HEADLESS_NET"), "HEADLESS_NET 목록 포함"),
        ("get_pin_net_name", {"schematic": str(schematic), "reference": "W1", "pin_number": "1"}, lambda v: json_contains(v, "HEADLESS_NET"), "W1.1 net 이름"),
        ("get_pin_connections", {"schematic": str(schematic), "reference": "W1", "pin_number": "2"}, lambda v: isinstance(v, dict) and v.get("reference") == "W1" and v.get("pin") == "2", "W1.2 pin 추적 구조"),
        ("get_component_nets", {"schematic": str(schematic), "reference": "W1"}, lambda v: json_contains(v, "HEADLESS_NET"), "W1 net 집합"),
        ("get_connected_items", {"schematic": str(schematic), "reference": "W1"}, lambda v: isinstance(v, dict), "연결 항목 구조"),
        ("get_net_components", {"schematic": str(schematic), "net": "HEADLESS_NET"}, lambda v: json_contains(v, "W1"), "HEADLESS_NET W1 포함"),
        ("get_net_connections", {"schematic": str(schematic), "net": "HEADLESS_NET"}, lambda v: isinstance(v, dict) and v.get("net") == "HEADLESS_NET" and v.get("connected_points", 0) >= 1, "HEADLESS_NET 연결점 포함"),
        ("get_net_connectivity", {"schematic": str(schematic), "net": "HEADLESS_NET"}, lambda v: isinstance(v, dict), "connectivity graph 구조"),
        ("trace_from_point", {"schematic": str(schematic), "x": points["w1p1"][0], "y": points["w1p1"][1]}, lambda v: json_contains(v, "HEADLESS_NET"), "핀 위치 trace"),
        ("find_single_pin_nets", {"schematic": str(schematic)}, lambda v: isinstance(v, dict), "single-pin 분석 구조"),
        ("find_shorted_nets", {"schematic": str(schematic)}, lambda v: isinstance(v, dict), "short 분석 구조"),
        ("find_orphan_items", {"schematic": str(schematic)}, lambda v: isinstance(v, dict), "orphan 분석 구조"),
        ("check_schematic_overlaps", {"schematic": str(schematic)}, lambda v: isinstance(v, dict), "overlap 분석 구조"),
    ]
    for tool, arguments, predicate, label in read_cases:
        runner.run_case(
            "sch_analysis", tool, f"analysis.{tool}", arguments, [schematic],
            lambda value, predicate=predicate, label=label: [postcondition(label, True, predicate(value))],
            expect_change=False,
        )


def suite_batch(runner: FunctionalRunner, schematic: Path, output_dir: Path) -> None:
    placements = [
        {"lib_id": "Headless:TwoPin", "reference": "B1", "value": "10k", "x": 40.64, "y": 40.64},
        {"lib_id": "Headless:TwoPin", "reference": "B2", "value": "20k", "x": 66.04, "y": 40.64},
        {"lib_id": "Headless:TwoPin", "reference": "B3", "value": "30k", "x": 91.44, "y": 40.64},
    ]
    runner.run_case(
        "sch_batch", "batch_place_components", "batch.place",
        {"schematic": str(schematic), "components": placements}, [schematic],
        lambda value: [
            postcondition("B1 readback", True, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "B1") is not None),
            postcondition("B2 readback", True, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "B2") is not None),
            postcondition("B3 readback", True, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "B3") is not None),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_batch", "get_schematic_layout", "batch.layout",
        {"schematic": str(schematic), "include_labels": True, "include_wires": True}, [schematic],
        lambda value: [
            postcondition("B1 layout 포함", True, json_contains(value, "B1")),
            postcondition("B2 layout 포함", True, json_contains(value, "B2")),
        ], expect_change=False,
    )
    runner.run_case(
        "sch_batch", "batch_edit_schematic_components", "batch.edit",
        {"schematic": str(schematic), "create_missing": True, "edits": [
            {"reference": "B1", "value": "11k", "fields": {"MPN": "BATCH-1"}},
            {"reference": "B2", "value": "22k", "fields": {"MPN": "BATCH-2"}},
        ]}, [schematic],
        lambda value: [
            postcondition("B1 value/field readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "B1"}), "BATCH-1")),
            postcondition("B2 value/field readback", True, json_contains(runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "B2"}), "22k")),
        ], expect_change=True,
    )
    b1_before = runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "B1"})
    runner.run_case(
        "sch_batch", "bulk_move_schematic_components", "batch.bulk_move",
        {"schematic": str(schematic), "references": ["B1", "B2"], "dx": 5.08, "dy": 5.08}, [schematic],
        lambda value: [postcondition("B1 위치 변경", False, runner.probe("get_schematic_component", {"schematic": str(schematic), "reference": "B1"}) == b1_before)],
        expect_change=True,
    )

    b1p2 = pin_xy(runner, schematic, "B1", "2")
    b2p1 = pin_xy(runner, schematic, "B2", "1")
    runner.run_case(
        "sch_batch", "batch_connect_pins", "batch.connect_pins",
        {"schematic": str(schematic), "connections": [{"ref1": "B1", "pin1": "2", "ref2": "B2", "pin2": "1"}]}, [schematic],
        lambda value: [postcondition("B1.2-B2.1 wire readback", True, any(wire_matches(item, (b1p2[0], b1p2[1], b2p1[0], b2p1[1])) for item in list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires") if isinstance(item, dict)))],
        expect_change=True,
    )
    runner.run_case(
        "sch_batch", "batch_connect_to_net", "batch.connect_to_net",
        {"schematic": str(schematic), "net_name": "BATCH_NET", "pins": [
            {"reference": "B1", "pin_number": "1"},
            {"reference": "B2", "pin_number": "2"},
        ], "stub_length": 2.54, "direction": "auto", "label_type": "net_label"}, [schematic],
        lambda value: [
            postcondition("B1.1 BATCH_NET", True, json_contains(runner.probe("get_pin_net_name", {"schematic": str(schematic), "reference": "B1", "pin_number": "1"}), "BATCH_NET")),
            postcondition("B2.2 BATCH_NET", True, json_contains(runner.probe("get_pin_net_name", {"schematic": str(schematic), "reference": "B2", "pin_number": "2"}), "BATCH_NET")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_batch", "connect_passthrough", "batch.passthrough",
        {"schematic": str(schematic), "net_name": "PASS_NET", "x": 120.0, "y": 60.0, "direction": "right"}, [schematic],
        lambda value: [
            postcondition("PASS_NET label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "PASS_NET")),
            postcondition("wire readback", True, len(list_field(runner.probe("list_schematic_wires", {"schematic": str(schematic)}), "wires")) >= 2),
        ], expect_change=True,
    )
    text_svg = output_dir / f"{schematic.stem}.svg"
    runner.run_case(
        "sch_batch", "add_schematic_text", "batch.add_text",
        {"schematic": str(schematic), "text": "HEADLESS_FUNCTIONAL_TEXT", "x": 30.48, "y": 25.4, "size": 1.27, "bold": True}, [schematic, text_svg],
        lambda value: [
            postcondition("text 응답", True, json_contains(value, "HEADLESS_FUNCTIONAL_TEXT")),
            postcondition(
                "SVG text readback",
                True,
                (lambda exported: exported.is_file() and "HEADLESS_FUNCTIONAL_TEXT" in exported.read_text(encoding="utf-8", errors="replace"))(
                    Path(runner.probe("export_schematic_svg", {"schematic": str(schematic), "output": str(output_dir / "batch-text-readback.svg")}).get("exported", text_svg))
                ),
                evidence_path=text_svg,
            ),
        ], expect_change=True, source_authority="kicad_cli",
    )
    runner.run_case(
        "sch_batch", "validate_component_connections", "batch.validate_components",
        {"schematic": str(schematic), "references": ["B1", "B2", "B3"], "ignore_power_pins": True}, [schematic],
        lambda value: [postcondition("검증 결과 구조", True, isinstance(value, dict))],
        expect_change=False,
    )
    runner.run_case(
        "sch_batch", "validate_wire_connections", "batch.validate_wires",
        {"schematic": str(schematic), "tolerance": 0.01}, [schematic],
        lambda value: [postcondition("wire 검증 결과 구조", True, isinstance(value, dict))],
        expect_change=False,
    )
    runner.run_case(
        "sch_batch", "batch_delete_schematic_components", "batch.delete_components",
        {"schematic": str(schematic), "references": ["B3"]}, [schematic],
        lambda value: [postcondition("B3 부재", False, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "B3") is not None)],
        expect_change=True,
    )
    runner.run_case(
        "sch_batch", "batch_delete", "batch.delete_mixed",
        {"schematic": str(schematic), "references": ["B2"], "uuids": []}, [schematic],
        lambda value: [postcondition("B2 부재", False, component_by_reference(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "B2") is not None)],
        expect_change=True,
    )


def suite_bus(runner: FunctionalRunner, schematic: Path, output_dir: Path) -> None:
    runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:FourPin", "reference": "U1", "x": 50.8, "y": 50.8})
    runner.run_case(
        "sch_bus", "add_bus", "bus.add",
        {"schematic": str(schematic), "x1": 76.2, "y1": 30.48, "x2": 76.2, "y2": 71.12}, [schematic],
        lambda value: [
            postcondition("bus 응답", "bus", value.get("added") if isinstance(value, dict) else None),
            postcondition("수직 bus 끝점", True, json_contains(value, "71.12")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_bus", "batch_add_bus", "bus.batch_add",
        {"schematic": str(schematic), "buses": [
            {"x1": 30.48, "y1": 81.28, "x2": 60.96, "y2": 81.28},
            {"x1": 30.48, "y1": 86.36, "x2": 60.96, "y2": 86.36},
        ]}, [schematic],
        lambda value: [postcondition("두 bus 추가", 2, value.get("added_count") if isinstance(value, dict) else None)],
        expect_change=True,
    )
    runner.setup("add_wire", {"schematic": str(schematic), "x1": 68.58, "y1": 40.64, "x2": 73.66, "y2": 40.64})
    runner.run_case(
        "sch_bus", "add_bus_entry", "bus.add_entry",
        {"schematic": str(schematic), "x": 73.66, "y": 40.64, "direction": "down_right"}, [schematic],
        lambda value: [
            postcondition("entry 응답", "bus_entry", value.get("added") if isinstance(value, dict) else None),
            postcondition("bus side x", True, json_contains(value, "76.2")),
        ], expect_change=True,
    )
    runner.run_case(
        "sch_bus", "connect_pins_to_bus", "bus.connect_pins",
        {"schematic": str(schematic), "bus_x": 76.2, "connections": [
            {"reference": "U1", "pin_number": "1", "net": "DATA0"},
            {"reference": "U1", "pin_number": "2", "net": "DATA1"},
        ]}, [schematic],
        lambda value: [
            postcondition("DATA0 label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "DATA0")),
            postcondition("DATA1 label readback", True, json_contains(runner.probe("list_schematic_labels", {"schematic": str(schematic)}), "DATA1")),
            postcondition("두 pin fanout 응답", True, json_contains(value, "DATA0") and json_contains(value, "DATA1")),
        ], expect_change=True,
    )
    bus_svg = output_dir / f"{schematic.stem}.svg"
    exported = runner.probe("export_schematic_svg", {"schematic": str(schematic), "output": str(output_dir / "bus-readback.svg")})
    exported_path = Path(exported.get("exported", bus_svg)) if isinstance(exported, dict) else bus_svg
    if not exported_path.is_file() or exported_path.stat().st_size == 0:
        # 별도 case가 아니라 전체 bus lane의 외부 확인이므로 네 case에 caveat를
        # 추가하지 않고 manifest 외부 조건에서 최종 집계한다.
        raise FunctionalError(f"bus KiCad CLI SVG readback 누락: {exported_path}")


def suite_templates(runner: FunctionalRunner, schematic: Path) -> None:
    runner.run_case(
        "templates", "list_template_categories", "templates.categories", {}, [schematic],
        lambda value: [postcondition("category 목록", True, len(list_field(value, "categories")) > 0)],
        expect_change=False,
    )
    search = runner.run_case(
        "templates", "search_templates", "templates.search",
        {"query": "i2c", "category": "connectivity"}, [schematic],
        lambda value: [postcondition("i2c_pullups 검색", True, json_contains(value, "i2c_pullups"))],
        expect_change=False,
    )
    template_id = "i2c_pullups" if json_contains(search, "i2c_pullups") else "i2c_pullups"
    runner.run_case(
        "templates", "get_template", "templates.get",
        {"template_id": template_id}, [schematic],
        lambda value: [
            postcondition("template id", True, json_contains(value, template_id)),
            postcondition("components 존재", True, len(list_field(value, "components")) > 0),
        ], expect_change=False,
    )
    runner.run_case(
        "templates", "apply_template", "templates.apply",
        {"schematic": str(schematic), "template_id": template_id, "position_x": 60.96, "position_y": 60.96, "ref_start": 10, "net_mappings": {"VCC_3V3": "HEADLESS_3V3"}},
        [schematic],
        lambda value: [
            postcondition("template 적용 응답", True, json_contains(value, template_id)),
            postcondition("component 생성 readback", True, len(list_field(runner.probe("list_schematic_components", {"schematic": str(schematic)}), "components")) >= 2),
        ], expect_change=True,
    )


def suite_export(runner: FunctionalRunner, schematic: Path, output_dir: Path, project: Path) -> None:
    runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": "E1", "value": "1k", "x": 50.8, "y": 50.8})
    runner.setup("add_schematic_component", {"schematic": str(schematic), "lib_id": "Headless:TwoPin", "reference": "E2", "value": "2k", "x": 76.2, "y": 50.8})
    runner.setup("connect_pins", {"schematic": str(schematic), "ref1": "E1", "pin1": "2", "ref2": "E2", "pin2": "1"})
    runner.setup("connect_to_net", {"schematic": str(schematic), "reference": "E1", "pin_number": "1", "net": "EXPORT_IN", "stub_length": 2.54})
    runner.setup("connect_to_net", {"schematic": str(schematic), "reference": "E2", "pin_number": "2", "net": "EXPORT_OUT", "stub_length": 2.54})

    runner.run_case(
        "sch_export", "export_netlist_summary", "export.summary",
        {"schematic": str(schematic)}, [schematic],
        lambda value: [
            postcondition("E1 summary 포함", True, json_contains(value, "E1")),
            postcondition("E2 summary 포함", True, json_contains(value, "E2")),
        ], expect_change=False,
    )
    svg = output_dir / f"{schematic.stem}.svg"
    runner.run_case(
        "sch_export", "export_schematic_svg", "export.svg",
        {"schematic": str(schematic), "output": str(output_dir / "functional.svg"), "black_and_white": False}, [schematic, svg],
        lambda value: [
            postcondition("SVG 파일", True, svg.is_file() and svg.stat().st_size > 0, evidence_path=svg),
            postcondition("SVG root", True, svg.is_file() and "<svg" in svg.read_text(encoding="utf-8", errors="replace")),
        ], expect_change=True, source_authority="kicad_cli",
    )
    pdf = output_dir / "functional.pdf"
    runner.run_case(
        "sch_export", "export_schematic_pdf", "export.pdf",
        {"schematic": str(schematic), "output": str(pdf), "all_sheets": False, "black_and_white": True}, [schematic, pdf],
        lambda value: [
            postcondition("PDF 파일", True, pdf.is_file() and pdf.stat().st_size > 0, evidence_path=pdf),
            postcondition("PDF magic", "%PDF", pdf.read_bytes()[:4].decode("ascii", errors="replace") if pdf.is_file() else None),
        ], expect_change=True, source_authority="kicad_cli",
    )
    netlist = output_dir / "functional.net"
    runner.run_case(
        "sch_export", "generate_netlist", "export.netlist",
        {"schematic": str(schematic), "output": str(netlist), "format": "kicad"}, [schematic, netlist],
        lambda value: [
            postcondition("netlist 파일", True, netlist.is_file() and netlist.stat().st_size > 0, evidence_path=netlist),
            postcondition("E1 netlist 포함", True, netlist.is_file() and "E1" in netlist.read_text(encoding="utf-8", errors="replace")),
        ], expect_change=True, source_authority="kicad_cli",
    )
    png = output_dir / "functional.png"
    runner.run_case(
        "sch_export", "render_schematic_png", "export.png",
        {"schematic": str(schematic), "output": str(png), "width_px": 900, "monochrome": False, "inline": False}, [schematic, png],
        lambda value: [
            postcondition("PNG 파일", True, png.is_file() and png.stat().st_size > 0, evidence_path=png),
            postcondition("PNG magic", "89504e470d0a1a0a", png.read_bytes()[:8].hex() if png.is_file() else None),
        ], expect_change=True, source_authority="kicad_cli",
    )
    erc = output_dir / "functional-erc.json"
    runner.run_case(
        "sch_export", "run_erc", "export.erc",
        {"schematic": str(schematic), "output": str(erc), "severity": "warning"}, [schematic, erc],
        lambda value: [
            postcondition("ERC JSON 파일", True, erc.is_file() and erc.stat().st_size > 0, evidence_path=erc),
            postcondition("ERC 결과 구조", True, isinstance(value, dict) and any(key in value for key in ("violations", "total_violations", "errors"))),
        ], expect_change=True, source_authority="kicad_cli",
    )
    runner.run_case(
        "sch_export", "fix_connectivity", "export.fix_connectivity_dry_run",
        {"schematic": str(schematic), "dry_run": True, "snap_tolerance": 0.2}, [schematic],
        lambda value: [postcondition("dry-run 결과 구조", True, isinstance(value, dict))],
        expect_change=False,
    )
    baseline_dir = project / ".konnect/baselines"
    runner.run_case(
        "sch_export", "set_visual_baseline", "export.set_visual_baseline",
        {"schematic": str(schematic), "width_px": 900}, [schematic, baseline_dir],
        lambda value: [
            postcondition("baseline 응답", True, isinstance(value, dict)),
            postcondition("baseline 파일 생성", True, baseline_dir.is_dir() and any(path.is_file() for path in baseline_dir.rglob("*")), evidence_path=baseline_dir),
        ], expect_change=True, source_authority="kicad_cli",
    )
    runner.run_case(
        "sch_export", "compare_visual_baseline", "export.compare_visual_baseline",
        {"schematic": str(schematic), "inline_diff": False}, [schematic, baseline_dir],
        lambda value: [
            postcondition("비교 결과 구조", True, isinstance(value, dict)),
            postcondition("동일 원본 drift 통과", True, value.get("status") == "PASS" or value.get("passed") is True or value.get("within_threshold") is True or value.get("changed_pct_of_page") in (0, 0.0)),
        ], expect_change=False, source_authority="kicad_cli",
    )
    runner.mark_not_applicable(
        "sch_export", "update_pcb_from_schematic", "export.update_pcb_from_schematic",
        EXCLUDED_TOOLS["update_pcb_from_schematic"],
    )


def newest_build_input() -> Path:
    candidates = [SOURCE_ROOT / "Cargo.toml", SOURCE_ROOT / "Cargo.lock"]
    candidates.extend(
        path
        for path in (SOURCE_ROOT / "crates").rglob("*")
        if path.is_file() and path.suffix in {".rs", ".toml", ".proto"}
    )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def git_output(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=SOURCE_ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="격리된 실제 Konnect STDIO MCP와 KiCad CLI의 headless 정상행동 전수 검증"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--allow-stale-binary",
        action="store_true",
        help="개발 중 구 release baseline에만 사용합니다. 최종 증거에서는 금지합니다.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FunctionalError(f"증거 디렉터리가 비어 있지 않습니다: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not LAUNCHER.is_file() or not os.access(LAUNCHER, os.X_OK):
        raise FunctionalError(f"안전 wrapper 실행 불가: {LAUNCHER}")
    if not BINARY.is_file() or not os.access(BINARY, os.X_OK):
        raise FunctionalError(f"release binary 실행 불가: {BINARY}")
    newest = newest_build_input()
    stale = BINARY.stat().st_mtime_ns < newest.stat().st_mtime_ns
    if stale and not args.allow_stale_binary:
        raise FunctionalError(
            f"release binary가 source보다 오래되었습니다: binary={BINARY}, newest={newest}"
        )

    cli = subprocess.run(
        ["/usr/local/bin/kicad-cli", "--version"], text=True, capture_output=True, timeout=30
    )
    if cli.returncode != 0:
        raise FunctionalError(f"kicad-cli 실행 실패: {cli.stdout}{cli.stderr}")
    project = output_dir / "fixture-project"
    state_dir = output_dir / "state"
    project.mkdir()
    state_dir.mkdir()
    ipc_address = f"ipc:///tmp/konnect-headless-{os.getpid()}-{uuid.uuid4().hex}.sock"
    config = output_dir / "konnect-headless.toml"
    write_runtime_config(config, project, ipc_address)

    identity = {
        "binary": str(BINARY),
        "binary_sha256": sha256_file(BINARY),
        "binary_mtime_ns": BINARY.stat().st_mtime_ns,
        "source_commit": git_output("rev-parse", "HEAD"),
        "source_worktree_sha256": source_worktree_digest(),
        "newest_build_input": str(newest),
        "newest_build_input_mtime_ns": newest.stat().st_mtime_ns,
        "binary_stale": stale,
        "kicad_cli_version": cli.stdout.strip().splitlines()[0],
    }
    client = StdioMcp(config, state_dir, ipc_address, output_dir / "server.stderr.log", args.timeout)
    runner: FunctionalRunner | None = None
    process_rc = -999
    initialization: dict[str, Any] = {}
    tools_list_response: dict[str, Any] = {}
    suite_errors: list[dict[str, str]] = []
    try:
        initialization, init_ms, init_request = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-headless-functional", "version": "1"},
            },
        )
        if "error" in initialization:
            raise FunctionalError(f"initialize 실패: {initialization['error']}")
        client.notify("notifications/initialized", {})
        tools_list_response, list_ms, list_request = client.request("tools/list", {})
        listed = tools_list_response.get("result", {}).get("tools")
        if not isinstance(listed, list):
            raise FunctionalError("tools/list에 tools 배열이 없습니다")
        tools = {
            item["name"]: item
            for item in listed
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        missing_schema = sorted(expected_tool_names() - set(tools))
        if missing_schema:
            raise FunctionalError(f"대상 도구가 tools/list에 없습니다: {missing_schema}")
        write_json(
            output_dir / "runtime-inventory.json",
            {
                "initialize": initialization,
                "initialize_request": init_request,
                "initialize_elapsed_ms": init_ms,
                "tools_list": tools_list_response,
                "tools_list_request": list_request,
                "tools_list_elapsed_ms": list_ms,
                "identity": identity,
            },
        )
        runner = FunctionalRunner(client, output_dir, identity, tools)

        context: dict[str, Any] = {}
        suites: list[tuple[str, Callable[[], Any]]] = [
            ("library", lambda: context.update(suite_library(runner, project))),
            ("sch_hierarchy", lambda: context.update(suite_hierarchy(runner, project))),
            ("sch_components", lambda: suite_components(runner, context["components"])),
            ("sch_wiring", lambda: context.update({"wiring_points": suite_wiring(runner, context["wiring"])})),
            ("sch_analysis", lambda: suite_analysis(runner, context["wiring"], context["wiring_points"])),
            ("sch_batch", lambda: suite_batch(runner, context["batch"], output_dir)),
            ("sch_bus", lambda: suite_bus(runner, context["bus"], output_dir)),
            ("templates", lambda: suite_templates(runner, context["templates"])),
            ("sch_export", lambda: suite_export(runner, context["export"], output_dir, project)),
        ]
        for name, suite in suites:
            try:
                suite()
            except Exception as error:
                suite_errors.append({"toolset": name, "error": f"{type(error).__name__}: {error}"})
    finally:
        process_rc = client.close()

    rows = runner.rows if runner is not None else []
    transcript = runner.transcript if runner is not None else []
    for row in rows:
        row["process_rc"] = process_rc
    cases_path = output_dir / "normal-behavior.jsonl"
    cases_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    transcript_path = output_dir / "mcp-transcript.jsonl"
    transcript_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in transcript),
        encoding="utf-8",
    )

    expected = expected_tool_names()
    observed_counts = Counter(row["tool"] for row in rows)
    observed = set(observed_counts)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    duplicate = {tool: count for tool, count in sorted(observed_counts.items()) if count != 1}
    verdict_counts = Counter(row["verdict"] for row in rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "lane": "headless_stdio_kicad_cli",
        "identity": identity,
        "server": initialization.get("result", {}).get("serverInfo"),
        "protocol_version": initialization.get("result", {}).get("protocolVersion"),
        "isolation": {
            "launcher": str(LAUNCHER),
            "config": str(config),
            "project_dir": str(project),
            "state_dir": str(state_dir),
            "runtime_home": str(output_dir / "runtime-home"),
            "ipc_address": ipc_address,
            "display": "unset",
        },
        "expected_tools": sorted(expected),
        "observed_tools": sorted(observed),
        "missing": missing,
        "extra": extra,
        "duplicate": duplicate,
        "excluded_tools": EXCLUDED_TOOLS,
        "per_tool_case_counts": dict(sorted(observed_counts.items())),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "failed_cases": [row["case_id"] for row in rows if row["verdict"] == "failed"],
        "unverified_cases": [row["case_id"] for row in rows if row["verdict"] == "unverified"],
        "not_applicable_cases": [row["case_id"] for row in rows if row["verdict"] == "not_applicable"],
        "suite_errors": suite_errors,
        "process_rc": process_rc,
        "jsonl": str(cases_path),
        "jsonl_sha256": sha256_file(cases_path),
        "transcript": str(transcript_path),
        "transcript_sha256": sha256_file(transcript_path),
        "fixture_final_sha256": filesystem_digest([project]),
        "complete": not missing and not extra and not duplicate and not suite_errors,
        "passed": (
            not missing
            and not extra
            and not duplicate
            and not suite_errors
            and verdict_counts.get("failed", 0) == 0
            and verdict_counts.get("unverified", 0) == 0
            and process_rc == 0
            and not stale
        ),
        "caveats": [
            "isError=false 단독으로 PASS하지 않고 모든 passed row에 독립 postcondition을 요구합니다.",
            "update_pcb_from_schematic은 root 지시로 live IPC lane에 남겨 not_applicable입니다.",
        ] + (["구 release baseline: source보다 binary가 오래되었습니다"] if stale else []),
    }
    manifest_path = output_dir / "manifest.json"
    write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "expected": len(expected),
                "observed": len(observed),
                "verdict_counts": manifest["verdict_counts"],
                "missing": missing,
                "suite_errors": suite_errors,
                "passed": manifest["passed"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FunctionalError, AssertionError, KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"headless functional 실패: {error}", file=sys.stderr)
        raise SystemExit(2)
