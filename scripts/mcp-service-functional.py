#!/usr/bin/env python3
"""Konnect의 service 계열 공개 MCP 도구를 격리 fixture에서 시험한다.

담당 범위는 meta, project, config, design_review, manufacturing, integration이다.
GUI, 실제 KiCad IPC, 네트워크 다운로드, Freerouting service는 환경 의존 결과로
분리하며 mock/fixture 통과를 실제 서비스 통과로 승격하지 않는다.
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
import sqlite3
import subprocess
import sys
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
OWNED_TOOLSETS = ("project", "config", "design_review", "manufacturing", "integration")
META_TOOLS = (
    "list_toolboxes",
    "load_toolset",
    "unload_toolset",
    "get_active_toolsets",
    "get_recent_calls",
    "server_stats",
    "get_installation_info",
    "reload_server",
)
RECORD_FIELDS = (
    "schema_version",
    "seq",
    "lane",
    "toolset",
    "tool",
    "case_id",
    "behavior",
    "request",
    "response",
    "body",
    "is_error",
    "error_kind",
    "started_at_unix_ms",
    "elapsed_ms",
    "process_rc",
    "binary_sha256",
    "source_commit",
    "source_worktree_sha256",
    "fixture_before_sha256",
    "fixture_after_sha256",
    "postconditions",
    "source_authority",
    "external_conditions",
    "verdict",
    "caveats",
)


class FunctionalError(RuntimeError):
    """coverage나 안전 경계가 불완전할 때 발생한다."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        digest.update(b"absent")
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"F")
            digest.update(bytes.fromhex(sha256_file(path)))
        elif path.is_dir():
            digest.update(b"D")
    return digest.hexdigest()


def source_identity(source_root: Path) -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    digest = hashlib.sha256()
    source_paths = list(
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and "target" not in path.parts
        and ".git" not in path.parts
        and "schematic-viewer" not in path.parts
        and path.suffix in {".rs", ".toml", ".proto"}
    )
    lock = source_root / "Cargo.lock"
    if lock.is_file():
        source_paths.append(lock)
    for path in sorted(set(source_paths)):
        digest.update(path.relative_to(source_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return commit, digest.hexdigest()


def planned_verdict(tool: str) -> str:
    if tool == "open_schematic_viewer":
        return "deferred_gui"
    if tool == "download_jlcpcb_database":
        return "deferred_network"
    if tool == "route_specctra_dsn":
        return "execute_no_egress_autoroute"
    if tool == "reload_server":
        return "execute_disposable_handoff"
    if tool == "save_project":
        return "execute_disposable_refusal"
    if tool == "open_project":
        return "execute_isolated_observation"
    if tool == "check_freerouting":
        return "execute_no_egress_probe"
    if tool == "enrich_datasheets":
        return "execute_public_network_write"
    if tool == "get_datasheet_url":
        return "execute_public_network_read"
    return "execute_local"


def build_plan(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    plan = []
    for toolset in OWNED_TOOLSETS:
        for tool in inventory.get("toolsets", {}).get(toolset, []):
            plan.append(
                {
                    "toolset": toolset,
                    "tool": tool,
                    "planned_verdict": planned_verdict(tool),
                }
            )
    advertised_meta = {item.get("name") for item in inventory.get("meta_tools", [])}
    for tool in META_TOOLS:
        if tool in advertised_meta:
            plan.append(
                {"toolset": "meta", "tool": tool, "planned_verdict": planned_verdict(tool)}
            )
    validate_plan(inventory, plan)
    return plan


def validate_plan(inventory: dict[str, Any], plan: list[dict[str, Any]]) -> None:
    expected = {
        tool
        for toolset in OWNED_TOOLSETS
        for tool in inventory.get("toolsets", {}).get(toolset, [])
    }
    advertised_meta = {item.get("name") for item in inventory.get("meta_tools", [])}
    expected.update(tool for tool in META_TOOLS if tool in advertised_meta)
    actual = [case.get("tool") for case in plan]
    if len(actual) != len(set(actual)):
        raise FunctionalError("기능 plan에 중복 tool이 있습니다")
    if set(actual) != expected:
        raise FunctionalError(
            f"기능 plan coverage 불일치: 누락={sorted(expected-set(actual))}, "
            f"초과={sorted(set(actual)-expected)}"
        )


def validate_case_arguments(
    inventory: dict[str, Any], plan: list[dict[str, Any]], paths: dict[str, Path]
) -> None:
    schemas = {
        item["name"]: item.get("inputSchema", {})
        for item in inventory.get("tools", []) + inventory.get("meta_tools", [])
    }
    skipped = {
        "deferred_gui",
        "deferred_network",
        "deferred_external_service",
        "debug_dispatch_evidence",
    }
    failures = []
    for case in plan:
        if case["planned_verdict"] in skipped:
            continue
        arguments = arguments_for(case["tool"], paths, {})
        required = schemas.get(case["tool"], {}).get("required", [])
        missing = [field for field in required if field not in arguments]
        if missing:
            failures.append(f"{case['tool']}: {missing}")
    if failures:
        raise FunctionalError("실행 case required argument 누락: " + "; ".join(failures))


def _condition(name: str, expected: Any, actual: Any, passed: bool) -> dict[str, Any]:
    return {"name": name, "expected": expected, "actual": actual, "passed": bool(passed)}


def artifact_parse_evidence(path: Path) -> tuple[str, bool]:
    suffix = path.suffix.lower()
    try:
        if suffix in {".gbr", ".gtl", ".gbl", ".gto", ".gbo", ".gm1"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            return "Gerber header/terminator", ("G04" in text or "%FS" in text) and "M02" in text
        if suffix in {".drl", ".xnc"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            return "Excellon header/terminator", "M48" in text and ("M30" in text or "M00" in text)
        if suffix == ".csv":
            with path.open(newline="", encoding="utf-8-sig") as stream:
                rows = list(csv.reader(stream))
            return "CSV header", bool(rows and rows[0])
        if suffix == ".pdf":
            return "PDF signature", path.read_bytes().startswith(b"%PDF")
        return "non-empty binary/text", path.stat().st_size > 0
    except (OSError, UnicodeError, csv.Error):
        return "parse failed", False


def evaluate_postconditions(tool: str, body: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    """응답 echo가 아닌 독립 파일/readback 조건을 도구별로 검사한다."""

    conditions: list[dict[str, Any]] = []
    if tool in {"load_toolset", "unload_toolset"}:
        return [
            _condition(
                "router_state_response",
                "non-empty text or object",
                body,
                (isinstance(body, str) and bool(body))
                or (isinstance(body, dict) and bool(body)),
            )
        ]
    if not isinstance(body, dict):
        return [_condition("json_object_body", "object", type(body).__name__, False)]

    if tool == "export_manufacturing_package":
        output = Path(context["output_dir"])
        files = body.get("files") if isinstance(body.get("files"), list) else []
        conditions.append(_condition("advertised_file_count", ">0", len(files), bool(files)))
        for relative in files:
            path = output / relative
            regular = path.is_file()
            size = path.stat().st_size if regular else 0
            conditions.append(
                _condition(f"artifact:{relative}", "regular non-empty file", size, regular and size > 0)
            )
            parse_kind, parse_ok = artifact_parse_evidence(path) if regular and size > 0 else ("not attempted", False)
            conditions.append(_condition(f"parse:{relative}", parse_kind, parse_ok, parse_ok))
        conditions.append(
            _condition("complete_matches_warnings", True, body.get("warnings") == [], body.get("complete") is True and body.get("warnings") == [])
        )
    elif tool == "validate_for_manufacturing":
        verdict = body.get("verdict")
        conditions.append(
            _condition("verdict", ["READY", "NEEDS REVIEW", "NOT READY"], verdict, verdict in {"READY", "NEEDS REVIEW", "NOT READY"})
        )
        if verdict == "READY":
            conditions.append(_condition("ready_has_drc", "non-null", body.get("drc"), body.get("drc") is not None))
    elif tool == "estimate_cost":
        total = body.get("cost_estimate", {}).get("total_estimate")
        conditions.append(_condition("total_estimate", "currency string", total, isinstance(total, str) and total.startswith("$")))
        conditions.append(_condition("board_layers", ">0", body.get("board", {}).get("board_copper_layers"), isinstance(body.get("board", {}).get("board_copper_layers"), int)))
    elif tool == "create_project":
        for key in ("project_file", "schematic", "pcb"):
            path = Path(str(body.get(key, "")))
            conditions.append(_condition(key, "existing non-empty file", str(path), path.is_file() and path.stat().st_size > 0))
    elif tool == "get_project_info":
        conditions.append(_condition("project_name", context.get("expected_name"), body.get("name"), body.get("name") == context.get("expected_name")))
        conditions.append(_condition("siblings_exist", True, [body.get("schematic_exists"), body.get("pcb_exists")], body.get("schematic_exists") is True and body.get("pcb_exists") is True))
    elif tool == "rename_project":
        expected = context.get("expected_paths", [])
        conditions.extend(_condition(f"renamed:{path}", True, Path(path).exists(), Path(path).exists()) for path in expected)
        conditions.extend(_condition(f"old_absent:{path}", False, Path(path).exists(), not Path(path).exists()) for path in context.get("old_paths", []))
    elif tool == "snapshot_project":
        path = Path(str(body.get("snapshot", "")))
        conditions.append(_condition("schematic_snapshot", "non-empty PDF", str(path), path.is_file() and path.stat().st_size > 0 and path.read_bytes()[:4] == b"%PDF"))
    elif tool in {"load_project_config", "load_user_config"}:
        conditions.append(_condition("config_source", context.get("expected_source"), body.get("source"), body.get("source") == context.get("expected_source")))
        if tool == "load_user_config":
            conditions.append(_condition("persisted_defaults", True, context.get("config_file_exists"), context.get("config_file_exists") is True))
    elif tool == "get_effective_config":
        actual = body.get("effective_config", {}).get("service", {}).get("value")
        conditions.append(_condition("merged_project_value", context.get("expected_value"), actual, actual == context.get("expected_value")))
    elif tool == "list_design_rules":
        actual = body.get("project_rules", [])
        conditions.append(_condition("project_rule_readback", context.get("expected_rule"), actual, context.get("expected_rule") in actual))
    elif tool in {"save_project_config", "save_user_config", "add_design_rule"}:
        readback = context.get("readback")
        conditions.append(_condition("independent_readback", context.get("expected_value"), readback, readback == context.get("expected_value")))
    elif tool == "audit_manufacturing":
        conditions.append(_condition("audit_name", "manufacturing", body.get("audit"), body.get("audit") == "manufacturing"))
        conditions.append(_condition("findings", "array", type(body.get("findings")).__name__, isinstance(body.get("findings"), list)))
    elif tool.startswith("audit_") or tool in {"check_bom_health", "run_design_review"}:
        status = body.get("status") or body.get("design_review", {}).get("status") or body.get("outcome", {}).get("status")
        conditions.append(_condition("audit_status", "reported", status, isinstance(status, str) and bool(status)))
        conditions.append(_condition("audit_coverage", "present", body.get("coverage") or body.get("design_review", {}).get("coverage"), bool(body.get("coverage") or body.get("design_review", {}).get("coverage"))))
    elif tool == "get_jlcpcb_database_stats":
        conditions.append(_condition("fixture_part_count", 2, body.get("part_count"), body.get("part_count") == 2))
    elif tool == "search_jlcpcb_parts":
        ids = [item.get("lcsc") for item in body.get("results", [])]
        conditions.append(_condition("search_hit", "C14663", ids, "C14663" in ids))
    elif tool == "get_jlcpcb_part":
        conditions.append(_condition("part_identity", "C14663", body.get("lcsc"), body.get("lcsc") == "C14663"))
        conditions.append(_condition("catalog_datasheet_url", "https URL", body.get("datasheet_url"), str(body.get("datasheet_url", "")).startswith("https://")))
    elif tool == "suggest_jlcpcb_alternatives":
        conditions.append(_condition("alternatives_array", "array", type(body.get("alternatives")).__name__, isinstance(body.get("alternatives"), list)))
    elif tool == "get_datasheet_url":
        expected_source = context.get("expected_source", "lcsc_api")
        conditions.append(_condition("datasheet_source", expected_source, body.get("source"), body.get("source") == expected_source))
        conditions.append(_condition("datasheet_url", "https URL", body.get("datasheet_url"), str(body.get("datasheet_url", "")).startswith("https://")))
    elif tool == "enrich_datasheets":
        updated = body.get("datasheets_enriched")
        conditions.append(_condition("network_enrichment_count", ">0", updated, isinstance(updated, int) and updated > 0))
        conditions.append(_condition("schematic_changed", "different sha256", context.get("after_sha256"), context.get("before_sha256") != context.get("after_sha256")))
        conditions.append(_condition("datasheet_readback", "https URL persisted", context.get("has_https_datasheet"), context.get("has_https_datasheet") is True))
    elif tool == "check_freerouting":
        conditions.append(_condition("engine_available", True, body.get("available"), body.get("available") is True))
        conditions.append(_condition("native_mcp_available", True, body.get("native_mcp_available"), body.get("native_mcp_available") is True))
        conditions.append(_condition("bridge_available", True, body.get("bridge_available"), body.get("bridge_available") is True))
    elif tool == "route_specctra_dsn":
        conditions.append(_condition("route_success", True, body.get("success"), body.get("success") is True))
        conditions.append(_condition("local_native_mcp", "local_freerouting_native_mcp", body.get("method"), body.get("method") == "local_freerouting_native_mcp"))
        conditions.append(_condition("cloud_not_used", False, body.get("bridge", {}).get("cloud_used"), body.get("bridge", {}).get("cloud_used") is False))
        conditions.append(_condition("final_state", "COMPLETED", body.get("final_state"), body.get("final_state") == "COMPLETED"))
        ses = Path(context.get("ses_path", ""))
        ses_ok = ses.is_file() and ses.stat().st_size > 0
        ses_text = ses.read_text(encoding="utf-8", errors="replace") if ses_ok else ""
        conditions.append(_condition("ses_nonempty", ">0", ses.stat().st_size if ses_ok else 0, ses_ok))
        conditions.append(_condition("ses_parse_root", "session", "session" if ses_text.lstrip().startswith("(session") else None, ses_text.lstrip().startswith("(session")))
        conditions.append(_condition("dsn_unchanged", context.get("dsn_before_sha256"), context.get("dsn_after_sha256"), context.get("dsn_before_sha256") == context.get("dsn_after_sha256")))
        conditions.append(_condition("no_external_network_namespace", True, context.get("network_namespace"), context.get("network_namespace") is True))
    elif tool == "list_toolboxes":
        expected_toolsets = context.get("expected_toolsets")
        expected_tools = context.get("expected_domain_tools")
        conditions.append(_condition("toolset_count", expected_toolsets, len(body.get("toolsets", [])), len(body.get("toolsets", [])) == expected_toolsets))
        conditions.append(_condition("domain_tool_count", expected_tools, body.get("total_tools"), body.get("total_tools") == expected_tools))
    elif tool == "get_active_toolsets":
        conditions.append(_condition("active_toolsets", "non-empty", body, bool(body)))
    elif tool in {"load_toolset", "unload_toolset"}:
        conditions.append(_condition("router_state_response", "non-empty", body, bool(body)))
    elif tool == "get_recent_calls":
        calls = body.get("calls", body if isinstance(body, list) else [])
        conditions.append(_condition("recent_calls", "non-empty", len(calls) if isinstance(calls, list) else None, isinstance(calls, list) and len(calls) > 0))
    elif tool == "server_stats":
        conditions.append(_condition("total_calls", ">0", body.get("total_calls"), isinstance(body.get("total_calls"), int) and body.get("total_calls") > 0))
    elif tool == "get_installation_info":
        version = body.get("build", {}).get("version")
        conditions.append(_condition("serving_version", "present", version, isinstance(version, str) and bool(version)))
    elif tool == "open_project":
        conditions.append(_condition("ipc_unavailable_is_explicit", False, body.get("ipc_available"), body.get("ipc_available") is False))
    else:
        conditions.append(_condition("nonempty_response", True, bool(body), bool(body)))
    if "source_before_sha256" in context:
        conditions.append(
            _condition(
                "source_fixture_unchanged",
                context["source_before_sha256"],
                context.get("source_after_sha256"),
                context["source_before_sha256"] == context.get("source_after_sha256"),
            )
        )
    return conditions


def make_record(**values: Any) -> dict[str, Any]:
    record = {
        "schema_version": SCHEMA_VERSION,
        "started_at_unix_ms": values.pop("started_at_unix_ms", int(time.time() * 1000)),
        "process_rc": values.pop("process_rc", None),
        "is_error": values.get("response", {}).get("isError") if isinstance(values.get("response"), dict) else None,
        "error_kind": None,
        **values,
    }
    body = record.get("body")
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        record["error_kind"] = body["error"].get("kind")
    for field in RECORD_FIELDS:
        record.setdefault(field, None)
    return {field: record[field] for field in RECORD_FIELDS}


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
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": identifier, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise FunctionalError(f"MCP 서버가 응답 전에 종료했습니다: rc={self.process.poll()}")
            response = json.loads(line)
            if response.get("id") == identifier:
                return response

    def notify(self, method: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
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


def parse_tool_response(response: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    result = response.get("result", {})
    content = result.get("content", [])
    if not content or not isinstance(content[0], dict):
        return result, None
    text = content[0].get("text")
    if not isinstance(text, str):
        return result, text
    try:
        return result, json.loads(text)
    except json.JSONDecodeError:
        return result, text


def _proc_executable_identity(pid: int) -> dict[str, Any]:
    path = Path(f"/proc/{pid}/exe")
    stat = path.stat()
    return {
        "pid": pid,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "target": os.readlink(path),
    }


def run_reload_handoff_case(
    *,
    command: list[str],
    root: Path,
    env: dict[str, str],
    output: Path,
    seq: int,
    binary_sha256: str,
    source_commit: str,
    source_worktree_sha256: str,
    fixture_sha256: str,
) -> dict[str, Any]:
    """별도 disposable server의 same-version exec와 pipe 유지성을 입증한다."""

    session = StdioMcp(command, root, env, output / "reload-server.stderr.log")
    started = int(time.time() * 1000)
    clock = time.perf_counter()
    process_rc: int | None = None
    response_bundle: dict[str, Any] = {}
    postconditions: list[dict[str, Any]] = []
    try:
        init_before = session.request(
            8000,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-reload-functional", "version": "1"},
            },
        )
        session.notify("notifications/initialized")
        before_identity = _proc_executable_identity(session.process.pid)
        _, installation_before = parse_tool_response(
            session.request(
                8001,
                "tools/call",
                {"name": "get_installation_info", "arguments": {}},
            )
        )
        # Diverge from eager startup state so the replacement must rebuild it.
        session.request(
            8002,
            "tools/call",
            {"name": "unload_toolset", "arguments": {"name": "placement"}},
        )
        _, active_before = parse_tool_response(
            session.request(
                8003,
                "tools/call",
                {"name": "get_active_toolsets", "arguments": {}},
            )
        )
        time.sleep(0.15)
        _, stats_before = parse_tool_response(
            session.request(8004, "tools/call", {"name": "server_stats", "arguments": {}})
        )

        reload_response = session.request(
            8005,
            "tools/call",
            {
                "name": "reload_server",
                "arguments": {"confirm": True, "allow_same_version": True},
            },
        )
        reload_result, reload_body = parse_tool_response(reload_response)

        # This request uses the same stdin/stdout pipes after exec.
        init_after = session.request(
            8006,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-reload-functional", "version": "1"},
            },
        )
        session.notify("notifications/initialized")
        after_identity = _proc_executable_identity(session.process.pid)
        _, active_after = parse_tool_response(
            session.request(
                8007,
                "tools/call",
                {"name": "get_active_toolsets", "arguments": {}},
            )
        )
        _, stats_after = parse_tool_response(
            session.request(8008, "tools/call", {"name": "server_stats", "arguments": {}})
        )
        _, installation_after = parse_tool_response(
            session.request(
                8009,
                "tools/call",
                {"name": "get_installation_info", "arguments": {}},
            )
        )
        before_names = {
            item.get("name") for item in active_before.get("active_toolsets", [])
        }
        after_names = {
            item.get("name") for item in active_after.get("active_toolsets", [])
        }
        postconditions = [
            _condition("pre_initialize", "success", "error" not in init_before, "error" not in init_before),
            _condition("reload_response", False, reload_result.get("isError"), reload_result.get("isError") is not True),
            _condition("request_pipe_survived", "new initialize response", "error" not in init_after, "error" not in init_after),
            _condition("pid_preserved", before_identity["pid"], after_identity["pid"], before_identity["pid"] == after_identity["pid"]),
            _condition("executable_identity_preserved", before_identity, after_identity, before_identity == after_identity),
            _condition("pre_reload_state_diverged", "placement absent", sorted(before_names), "placement" not in before_names),
            _condition("toolsets_reinitialized", "placement restored by eager startup", sorted(after_names), "placement" in after_names),
            _condition("call_counters_reset", f"less than {stats_before.get('total_calls')}", stats_after.get("total_calls"), isinstance(stats_after.get("total_calls"), int) and stats_after.get("total_calls") < stats_before.get("total_calls", 0)),
            _condition("uptime_reset", f"less than {stats_before.get('uptime_ms')}", stats_after.get("uptime_ms"), isinstance(stats_after.get("uptime_ms"), int) and stats_after.get("uptime_ms") < stats_before.get("uptime_ms", 0)),
            _condition("serving_build_same", installation_before.get("build"), installation_after.get("build"), installation_before.get("build") == installation_after.get("build")),
            _condition("binary_sha_readback", binary_sha256, sha256_file(Path(after_identity["target"])), sha256_file(Path(after_identity["target"])) == binary_sha256),
        ]
        response_bundle = {
            "reload": reload_response,
            "initialize_after": init_after,
            "active_before": active_before,
            "active_after": active_after,
            "stats_before": stats_before,
            "stats_after": stats_after,
            "installation_before": installation_before,
            "installation_after": installation_after,
            "identity_before": before_identity,
            "identity_after": after_identity,
        }
        verdict = "passed" if all(item["passed"] for item in postconditions) else "failed"
        body = reload_body
        is_error = reload_result.get("isError")
        error_kind = body.get("error", {}).get("kind") if isinstance(body, dict) else None
    except Exception as error:  # preserve evidence from a failed one-way handoff
        verdict = "failed"
        body = {"exception": f"{type(error).__name__}: {error}"}
        is_error = True
        error_kind = "harness_exception"
        response_bundle["exception"] = body["exception"]
    finally:
        process_rc = session.close()
    elapsed = (time.perf_counter() - clock) * 1000
    return make_record(
        seq=seq,
        lane="services-reload",
        toolset="meta",
        tool="reload_server",
        case_id="reload-server-same-version-exec",
        behavior="exec_handoff",
        request={"name": "reload_server", "arguments": {"confirm": True, "allow_same_version": True}},
        response={"isError": is_error, "evidence": response_bundle},
        body=body,
        error_kind=error_kind,
        started_at_unix_ms=started,
        elapsed_ms=round(elapsed, 3),
        process_rc=process_rc,
        binary_sha256=binary_sha256,
        source_commit=source_commit,
        source_worktree_sha256=source_worktree_sha256,
        fixture_before_sha256=fixture_sha256,
        fixture_after_sha256=fixture_sha256,
        postconditions=postconditions,
        source_authority="same_binary_exec_and_server_readback",
        external_conditions=[],
        verdict=verdict,
        caveats=[] if verdict == "passed" else ["same-version disposable exec handoff failed"],
    )


def call_in_no_egress_namespace(
    *,
    server_command: list[str],
    root: Path,
    env: dict[str, str],
    output: Path,
    tool: str,
    arguments: dict[str, Any],
    identifier: int,
) -> tuple[dict[str, Any], float, int, int]:
    namespace_command = [
        "unshare",
        "--user",
        "--map-root-user",
        "--net",
        "sh",
        "-c",
        'set -eu; ip link set lo up; exec "$@"',
        "sh",
        *server_command,
    ]
    session = StdioMcp(
        namespace_command,
        root,
        env,
        output / f"{tool}-namespace.stderr.log",
    )
    pid = session.process.pid
    clock = time.perf_counter()
    try:
        init = session.request(
            identifier,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "konnect-no-egress-functional", "version": "1"},
            },
        )
        if "error" in init:
            raise FunctionalError(f"no-egress initialize 실패: {init}")
        session.notify("notifications/initialized")
        response = session.request(
            identifier + 1,
            "tools/call",
            {"name": tool, "arguments": arguments},
        )
    finally:
        rc = session.close()
    elapsed = (time.perf_counter() - clock) * 1000
    return response, elapsed, rc, pid
def seed_jlcpcb_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE components (
            LCSC TEXT, MFR_Part TEXT, Package TEXT, Manufacturer TEXT,
            Library_Type TEXT, Description TEXT, Datasheet TEXT,
            Price REAL, Stock INTEGER, Category TEXT
        );
        INSERT INTO components VALUES
          ('C14663','RC0402FR-0710KL','0402','YAGEO','Basic',
           '10k resistor 0402','https://www.lcsc.com/datasheet/C14663.pdf',0.01,5000,'Resistors'),
          ('C1525','CL05B104KO5NNNC','0402','Samsung','Basic',
           '100nF capacitor 0402','https://www.lcsc.com/datasheet/C1525.pdf',0.02,4000,'Capacitors');
        """
    )
    connection.commit()
    connection.close()


def prepare_workspace(root: Path, output: Path) -> dict[str, Path]:
    for transient in (
        output / "state",
        output / "runtime-home",
        output / "reload-state",
        output / "reload-runtime-home",
        output / "check_freerouting-state",
        output / "check_freerouting-runtime-home",
        output / "route_specctra_dsn-state",
        output / "route_specctra_dsn-runtime-home",
    ):
        if transient.exists():
            shutil.rmtree(transient)
    work = output / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    fixtures = root / "upstream/konnect/crates/konnect-core/tests/fixtures"
    review = work / "review"
    shutil.copytree(fixtures / "project_ownership", review)
    board = work / "manufacturing" / "two-resistors.kicad_pcb"
    schematic = work / "manufacturing" / "bom-source.kicad_sch"
    board.parent.mkdir(parents=True)
    shutil.copy2(fixtures / "specctra_two_resistors.kicad_pcb", board)
    shutil.copy2(fixtures / "test.kicad_sch", schematic)
    enrich = work / "enrich-public-lcsc.kicad_sch"
    shutil.copy2(fixtures / "structural_scans_kicad10.kicad_sch", enrich)
    enrich_source = enrich.read_text(encoding="utf-8")
    if '(property "LCSC" "C25804"' not in enrich_source or '(property "Datasheet" ""' not in enrich_source:
        raise FunctionalError("network enrich fixture가 C25804/빈 Datasheet 계약과 다릅니다")
    database = work / "jlcpcb.db"
    seed_jlcpcb_database(database)
    freerouting_dir = work / "freerouting"
    freerouting_dir.mkdir()
    freerouting_dsn = freerouting_dir / "two-resistors.dsn"
    shutil.copy2(fixtures / "specctra_two_resistors.native-kicad-10.dsn", freerouting_dsn)
    return {
        "work": work,
        "review_schematic": review / "complex_hierarchy.kicad_sch",
        "board": board,
        "schematic": schematic,
        "enrich": enrich,
        "database": database,
        "projects": work / "projects",
        "snapshots": work / "snapshots",
        "package": work / "package",
        "state": output / "state",
        "runtime_home": output / "runtime-home",
        "freerouting_dsn": freerouting_dsn,
        "freerouting_ses": freerouting_dir / "two-resistors.ses",
        "freerouting_jar": root / ".artifacts/20261006-improvement/services/freerouting-runtime/bin/freerouting-2.5.0.jar",
        "freerouting_java_bin": root / ".artifacts/20261006-improvement/services/freerouting-runtime/jre25/usr/lib/jvm/java-25-openjdk-amd64/bin",
    }


def arguments_for(tool: str, paths: dict[str, Path], state: dict[str, Any]) -> dict[str, Any]:
    project_dir = paths["projects"]
    old_pro = project_dir / "service_probe.kicad_pro"
    new_pro = project_dir / "service_renamed.kicad_pro"
    mapping: dict[str, dict[str, Any]] = {
        "list_toolboxes": {},
        "load_toolset": {"name": "placement"},
        "unload_toolset": {"name": "placement"},
        "get_active_toolsets": {},
        "get_recent_calls": {"limit": 20},
        "server_stats": {},
        "get_installation_info": {},
        "reload_server": {"confirm": False},
        "create_project": {"path": str(project_dir), "name": "service_probe"},
        "get_project_info": {"path": str(new_pro if new_pro.exists() else old_pro)},
        "open_project": {"path": str(new_pro if new_pro.exists() else old_pro)},
        "save_project": {},
        "snapshot_project": {
            "schematic": str(project_dir / "service_renamed.kicad_sch"),
            "output_dir": str(paths["snapshots"]),
            "label": "service",
        },
        "rename_project": {"project": str(old_pro), "new_name": "service_renamed"},
        "load_user_config": {},
        "save_user_config": {"key_path": "service.user", "value": {"nested": [1, True]}},
        "load_project_config": {"project_dir": str(project_dir)},
        "save_project_config": {"project_dir": str(project_dir), "key_path": "service.value", "value": {"nested": [1, True]}},
        "get_effective_config": {"project_dir": str(project_dir)},
        "add_design_rule": {"project_dir": str(project_dir), "scope": "project", "rule": "service fixture rule"},
        "list_design_rules": {"project_dir": str(project_dir)},
        "audit_decoupling": {"schematic": str(paths["review_schematic"]), "schematic_scope": "hierarchy"},
        "audit_connections": {"schematic": str(paths["review_schematic"]), "schematic_scope": "hierarchy"},
        "audit_power_rails": {"schematic": str(paths["review_schematic"]), "schematic_scope": "hierarchy"},
        "audit_manufacturing": {"board": str(paths["board"]), "fab_house": "pcbway"},
        "check_bom_health": {"schematic": str(paths["review_schematic"]), "schematic_scope": "hierarchy"},
        "run_design_review": {"schematic": str(paths["review_schematic"]), "severity_filter": "info"},
        "export_manufacturing_package": {
            "board": str(paths["board"]),
            "output_dir": str(paths["package"]), "fab_house": "pcbway", "include_assembly": False,
        },
        "validate_for_manufacturing": {"board": str(paths["board"]), "fab_house": "pcbway"},
        "estimate_cost": {"board": str(paths["board"]), "fab_house": "pcbway", "quantity": 5},
        "enrich_datasheets": {"schematic": str(paths["enrich"]), "overwrite_existing": False},
        "search_jlcpcb_parts": {"query": "10k", "limit": 10},
        "get_jlcpcb_part": {"lcsc_id": "C14663"},
        "suggest_jlcpcb_alternatives": {"value": "10k", "footprint": "Resistor_SMD:R_0402_1005Metric"},
        "get_jlcpcb_database_stats": {},
        "get_datasheet_url": {"lcsc_id": "C25804"},
        "check_freerouting": {"jar_path": str(paths["freerouting_jar"])},
        "route_specctra_dsn": {
            "dsn_path": str(paths["freerouting_dsn"]),
            "ses_output_path": str(paths["freerouting_ses"]),
            "jar_path": str(paths["freerouting_jar"]),
            "max_passes": 2,
            "optimizer_enabled": False,
            "job_timeout_seconds": 300,
            "overall_timeout_seconds": 300,
        },
    }
    return mapping.get(tool, {})


def context_for(tool: str, paths: dict[str, Path], body: Any) -> dict[str, Any]:
    project_dir = paths["projects"]
    context: dict[str, Any] = {}
    if tool == "create_project":
        context["expected_name"] = "service_probe"
    elif tool == "list_toolboxes":
        context["expected_toolsets"] = paths["expected_toolsets"]
        context["expected_domain_tools"] = paths["expected_domain_tools"]
    elif tool == "get_project_info":
        context["expected_name"] = "service_renamed" if (project_dir / "service_renamed.kicad_pro").exists() else "service_probe"
    elif tool == "rename_project":
        context["expected_paths"] = [str(project_dir / f"service_renamed.{ext}") for ext in ("kicad_pro", "kicad_sch", "kicad_pcb")]
        context["old_paths"] = [str(project_dir / f"service_probe.{ext}") for ext in ("kicad_pro", "kicad_sch", "kicad_pcb")]
    elif tool == "export_manufacturing_package":
        context["output_dir"] = str(paths["package"])
    elif tool in {"load_project_config", "load_user_config"}:
        context["expected_source"] = "defaults"
        if tool == "load_user_config":
            context["config_file_exists"] = (paths["runtime_home"] / ".konnect/config.json").is_file()
    elif tool == "get_effective_config":
        context["expected_value"] = {"nested": [1, True]}
    elif tool == "get_datasheet_url":
        context["expected_source"] = "lcsc_api"
    elif tool == "list_design_rules":
        context["expected_rule"] = "service fixture rule"
    elif tool == "save_project_config":
        config = project_dir / ".konnect/project.json"
        try:
            context["readback"] = json.loads(config.read_text())["service"]["value"]
        except (OSError, KeyError, json.JSONDecodeError):
            context["readback"] = None
        context["expected_value"] = {"nested": [1, True]}
    elif tool == "save_user_config":
        config = paths["runtime_home"] / ".konnect/config.json"
        try:
            context["readback"] = json.loads(config.read_text())["service"]["user"]
        except (OSError, KeyError, json.JSONDecodeError):
            context["readback"] = None
        context["expected_value"] = {"nested": [1, True]}
    elif tool == "add_design_rule":
        config = project_dir / ".konnect/project.json"
        try:
            context["readback"] = "service fixture rule" in json.loads(config.read_text()).get("design_rules", [])
        except (OSError, json.JSONDecodeError):
            context["readback"] = False
        context["expected_value"] = True
    elif tool == "enrich_datasheets":
        context["before_sha256"] = paths["enrich_before"]
        context["after_sha256"] = sha256_file(paths["enrich"])
        source = paths["enrich"].read_text(encoding="utf-8")
        context["has_https_datasheet"] = bool(
            re.search(r'\(property "Datasheet" "https://[^\"]+"', source)
        )
    elif tool == "route_specctra_dsn":
        context["ses_path"] = str(paths["freerouting_ses"])
        context["dsn_before_sha256"] = paths["freerouting_dsn_before"]
        context["dsn_after_sha256"] = sha256_file(paths["freerouting_dsn"])
        context["network_namespace"] = True
    if tool in {
        "audit_manufacturing",
        "estimate_cost",
        "validate_for_manufacturing",
        "export_manufacturing_package",
    }:
        context["source_before_sha256"] = paths["manufacturing_source_before"]
        digest = hashlib.sha256()
        digest.update(bytes.fromhex(sha256_file(paths["board"])))
        digest.update(bytes.fromhex(sha256_file(paths["schematic"])))
        context["source_after_sha256"] = digest.hexdigest()
    elif tool in {
        "audit_decoupling",
        "audit_connections",
        "audit_power_rails",
        "check_bom_health",
        "run_design_review",
    }:
        context["source_before_sha256"] = paths["review_before"]
        context["source_after_sha256"] = tree_sha256(paths["review_schematic"].parent)
    return context


def _source_authority(tool: str) -> str:
    if tool == "enrich_datasheets":
        return "actual_network_service_and_saved_file"
    if tool == "get_datasheet_url":
        return "actual_network_service"
    if tool == "route_specctra_dsn":
        return "local_freerouting_native_mcp"
    if tool == "check_freerouting":
        return "local_freerouting_native_mcp_probe"
    if tool in {"validate_for_manufacturing", "export_manufacturing_package", "snapshot_project"}:
        return "kicad_cli_and_saved_file"
    if tool in {"search_jlcpcb_parts", "get_jlcpcb_part", "suggest_jlcpcb_alternatives", "get_jlcpcb_database_stats"}:
        return "local_sqlite_fixture"
    if tool in META_TOOLS:
        return "server_runtime_state"
    return "saved_file"


def run_functional(root: Path, output: Path, inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    artifacts_root = (root / ".artifacts").resolve()
    if not output.resolve().is_relative_to(artifacts_root):
        raise FunctionalError("service output/runtime HOME은 프로젝트 .artifacts 하위여야 합니다")
    plan = build_plan(inventory)
    output.mkdir(parents=True, exist_ok=True)
    paths = prepare_workspace(root, output)
    if not paths["freerouting_jar"].is_file():
        raise FunctionalError(f"고정 Freerouting JAR가 없습니다: {paths['freerouting_jar']}")
    java = paths["freerouting_java_bin"] / "java"
    if not java.is_file() or not os.access(java, os.X_OK):
        raise FunctionalError(f"격리 Java 25가 없습니다: {java}")
    paths["expected_toolsets"] = len(inventory.get("toolsets", {}))  # type: ignore[assignment]
    paths["expected_domain_tools"] = len(inventory.get("tools", []))  # type: ignore[assignment]
    validate_case_arguments(inventory, plan, paths)
    paths["state"].mkdir(parents=True, exist_ok=True)
    paths["enrich_before"] = sha256_file(paths["enrich"])  # type: ignore[assignment]
    paths["freerouting_dsn_before"] = sha256_file(paths["freerouting_dsn"])  # type: ignore[assignment]
    paths["review_before"] = tree_sha256(paths["review_schematic"].parent)  # type: ignore[assignment]
    manufacturing_digest = hashlib.sha256()
    manufacturing_digest.update(bytes.fromhex(sha256_file(paths["board"])))
    manufacturing_digest.update(bytes.fromhex(sha256_file(paths["schematic"])))
    paths["manufacturing_source_before"] = manufacturing_digest.hexdigest()  # type: ignore[assignment]

    source_root = root / "upstream/konnect"
    binary = source_root / "target/release/konnect"
    wrapper = root / "scripts/run-konnect.sh"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise FunctionalError(f"release binary를 실행할 수 없습니다: {binary}")
    source_files = [
        path
        for path in source_root.rglob("*")
        if path.is_file()
        and "target" not in path.parts
        and ".git" not in path.parts
        and "schematic-viewer" not in path.parts
        and path.suffix in {".rs", ".toml", ".proto"}
    ]
    if (source_root / "Cargo.lock").is_file():
        source_files.append(source_root / "Cargo.lock")
    newest = max(source_files, key=lambda path: path.stat().st_mtime_ns)
    if binary.stat().st_mtime_ns < newest.stat().st_mtime_ns:
        raise FunctionalError(f"release binary가 source보다 오래되었습니다: {newest}")
    binary_sha = sha256_file(binary)
    commit, worktree_sha = source_identity(source_root)
    fixture_before = tree_sha256(paths["work"])

    cli = Path("/usr/local/bin/kicad-cli")
    cli_value = str(cli) if cli.is_file() else "kicad-cli"
    config = output / "service-konnect.toml"
    config.write_text(
        "\n".join(
            [
                f"kicad_cli = {json.dumps(cli_value)}",
                'kicad_binary = "/nonexistent/service-kicad-gui"',
                f"project_dir = {json.dumps(str(paths['projects']))}",
                'ipc_address = "ipc:///tmp/konnect-service-no-such.sock"',
                f"jlcpcb_db_path = {json.dumps(str(paths['database']))}",
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
    env["KICAD_API_SOCKET"] = "ipc:///tmp/konnect-service-no-such.sock"
    env["KONNECT_STATE_DIR"] = str(paths["state"])
    env["KONNECT_RUNTIME_HOME"] = str(paths["runtime_home"])
    server_command = [str(wrapper), "--config", str(config)]
    session = StdioMcp(server_command, root, env, output / "server.stderr.log")
    records: list[dict[str, Any]] = []
    identifier = 1
    process_rc: int | None = None
    try:
        init = session.request(identifier, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "konnect-service-functional", "version": "1"}})
        identifier += 1
        if "error" in init:
            raise FunctionalError(f"initialize 실패: {init}")
        session.notify("notifications/initialized")

        # Dependency order matters: create -> rename -> info/snapshot.
        order = {tool: index for index, tool in enumerate([
            "list_toolboxes", "unload_toolset", "load_toolset", "get_active_toolsets", "get_recent_calls", "server_stats", "get_installation_info", "reload_server",
            "create_project", "rename_project", "get_project_info", "snapshot_project", "open_project", "save_project", "open_schematic_viewer",
            "load_user_config", "save_user_config", "load_project_config", "save_project_config", "add_design_rule", "list_design_rules", "get_effective_config",
            "audit_decoupling", "audit_connections", "audit_power_rails", "audit_manufacturing", "check_bom_health", "run_design_review",
            "estimate_cost", "validate_for_manufacturing", "export_manufacturing_package",
            "get_jlcpcb_database_stats", "search_jlcpcb_parts", "get_jlcpcb_part", "suggest_jlcpcb_alternatives", "get_datasheet_url", "enrich_datasheets", "check_freerouting", "download_jlcpcb_database", "route_specctra_dsn",
        ])}
        plan.sort(key=lambda case: order.get(case["tool"], 10_000))
        for seq, case in enumerate(plan, 1):
            tool = case["tool"]
            planned = case["planned_verdict"]
            external = []
            if planned.startswith("deferred_"):
                external = [planned.removeprefix("deferred_")]
            elif planned == "execute_public_network_write":
                external = ["public_lcsc_read_only_api"]
            elif planned == "execute_public_network_read":
                external = ["public_lcsc_read_only_api"]
            elif planned in {"execute_no_egress_probe", "execute_no_egress_autoroute"}:
                external = ["user_network_namespace_loopback_only"]
            if planned in {"deferred_gui", "deferred_network", "deferred_external_service", "debug_dispatch_evidence"}:
                records.append(make_record(
                    seq=seq, lane="services", toolset=case["toolset"], tool=tool,
                    case_id=f"{tool}-{planned}", behavior="deferred", request=None, response=None,
                    body=None, elapsed_ms=0.0, binary_sha256=binary_sha, source_commit=commit,
                    source_worktree_sha256=worktree_sha, fixture_before_sha256=fixture_before,
                    fixture_after_sha256=tree_sha256(paths["work"]), postconditions=[],
                    source_authority="not_executed", external_conditions=external,
                    verdict=planned, caveats=["현재 환경 결과를 기능 성공으로 대체하지 않습니다."],
                ))
                continue
            if tool == "reload_server":
                reload_env = env.copy()
                reload_env["KONNECT_RUNTIME_HOME"] = str(output / "reload-runtime-home")
                reload_env["KONNECT_STATE_DIR"] = str(output / "reload-state")
                records.append(
                    run_reload_handoff_case(
                        command=server_command,
                        root=root,
                        env=reload_env,
                        output=output,
                        seq=seq,
                        binary_sha256=binary_sha,
                        source_commit=commit,
                        source_worktree_sha256=worktree_sha,
                        fixture_sha256=tree_sha256(paths["work"]),
                    )
                )
                continue
            arguments = arguments_for(tool, paths, {})
            request = {"name": tool, "arguments": arguments}
            started = int(time.time() * 1000)
            special_process_rc: int | None = None
            namespace_pid: int | None = None
            if planned in {"execute_no_egress_probe", "execute_no_egress_autoroute"}:
                no_egress_env = env.copy()
                no_egress_env["KONNECT_RUNTIME_HOME"] = str(output / f"{tool}-runtime-home")
                no_egress_env["KONNECT_STATE_DIR"] = str(output / f"{tool}-state")
                no_egress_env["PATH"] = f"{paths['freerouting_java_bin']}:{env.get('PATH', '')}"
                no_egress_env[
                    "FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS"
                ] = "true"
                response, elapsed, special_process_rc, namespace_pid = call_in_no_egress_namespace(
                    server_command=server_command,
                    root=root,
                    env=no_egress_env,
                    output=output,
                    tool=tool,
                    arguments=arguments,
                    identifier=9000 + seq * 10,
                )
            else:
                clock = time.perf_counter()
                response = session.request(identifier, "tools/call", request)
                identifier += 1
                elapsed = (time.perf_counter() - clock) * 1000
            result, body = parse_tool_response(response)
            context = context_for(tool, paths, body)
            postconditions = evaluate_postconditions(tool, body, context)
            if namespace_pid is not None:
                postconditions.append(
                    _condition(
                        "namespace_server_pid",
                        ">0 and exited rc0",
                        {"pid": namespace_pid, "rc": special_process_rc},
                        namespace_pid > 0 and special_process_rc == 0,
                    )
                )
            is_error = result.get("isError") is True
            expected_environment_refusal = planned == "execute_disposable_refusal"
            passed = (
                (not is_error and all(item["passed"] for item in postconditions))
                or (expected_environment_refusal and is_error)
            )
            verdict = "passed" if passed and not expected_environment_refusal else (
                "environment_refusal_observed" if passed else "failed"
            )
            records.append(make_record(
                seq=seq, lane="services", toolset=case["toolset"], tool=tool,
                case_id=f"{tool}-isolated", behavior="success" if not expected_environment_refusal else "refusal",
                request=request, response=result, body=body, started_at_unix_ms=started,
                elapsed_ms=round(elapsed, 3), binary_sha256=binary_sha, source_commit=commit,
                source_worktree_sha256=worktree_sha, fixture_before_sha256=fixture_before,
                fixture_after_sha256=tree_sha256(paths["work"]), postconditions=postconditions,
                source_authority=_source_authority(tool), external_conditions=external,
                verdict=verdict, caveats=[] if verdict == "passed" else ["실제 GUI/IPC/외부 service 성공이 아닙니다."],
                process_rc=special_process_rc,
            ))
    finally:
        process_rc = session.close()
    for record in records:
        if record["process_rc"] is None:
            record["process_rc"] = process_rc
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "owned_toolsets": list(OWNED_TOOLSETS),
        "expected_tools": sorted(case["tool"] for case in plan),
        "observed_tools": sorted(record["tool"] for record in records),
        "missing": sorted({case["tool"] for case in plan} - {record["tool"] for record in records}),
        "extra": sorted({record["tool"] for record in records} - {case["tool"] for case in plan}),
        "duplicates": len(records) != len({record["tool"] for record in records}),
        "verdict_counts": {verdict: sum(record["verdict"] == verdict for record in records) for verdict in sorted({record["verdict"] for record in records})},
        "binary_sha256": binary_sha,
        "source_commit": commit,
        "source_worktree_sha256": worktree_sha,
        "process_rc": process_rc,
        "all_local_cases_passed": all(record["verdict"] in {"passed", "environment_refusal_observed", "deferred_gui", "deferred_network", "deferred_external_service", "debug_dispatch_evidence"} for record in records),
        "all_features_integrity_claim_supported": all(record["verdict"] == "passed" for record in records),
    }
    return records, manifest


def write_outputs(output: Path, plan: list[dict[str, Any]], records: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (output / "evidence.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest["evidence_jsonl_sha256"] = sha256_file(output / "evidence.jsonl")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def command_plan(args: argparse.Namespace) -> int:
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    plan = build_plan(inventory)
    Path(args.output).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"planned_tools": len(plan)}, ensure_ascii=False))
    return 0


def command_run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = Path(args.output_dir).resolve()
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    plan = build_plan(inventory)
    records, manifest = run_functional(root, output, inventory)
    write_outputs(output, plan, records, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if manifest["all_local_cases_passed"] else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--inventory", required=True)
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=command_plan)
    run = sub.add_parser("run")
    run.add_argument("--root", default=str(ROOT))
    run.add_argument("--inventory", required=True)
    run.add_argument("--output-dir", required=True)
    run.set_defaults(func=command_run)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return args.func(args)
    except FunctionalError as error:
        print(f"service 기능 검증 실패: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
