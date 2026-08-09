#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts/run-konnect.sh"
CONFIG = ROOT / "config/konnect.toml"


class McpClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.next_id = 1
        self.process = subprocess.Popen(
            [str(LAUNCHER), "--config", str(CONFIG)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        assert self.process.stdout is not None
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise AssertionError(
                    f"Konnect 조기 종료({self.process.returncode}): {stderr[-4000:]}"
                )
            events = self.selector.select(max(0.0, deadline - time.monotonic()))
            if not events:
                break
            line = self.process.stdout.readline()
            if not line:
                break
            response = json.loads(line)
            if response.get("id") == request_id:
                if "error" in response:
                    raise AssertionError(f"MCP 오류: {response['error']}")
                return response
        raise AssertionError(f"MCP 응답 timeout: method={method}")

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        result = response["result"]
        if result.get("isError"):
            raise AssertionError(f"MCP tool 실패({name}): {result}")
        content = result.get("content", [])
        if not content or "text" not in content[0]:
            raise AssertionError(f"MCP tool 응답 형식 불일치({name}): {result}")
        text = content[0]["text"]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"text": text}
        return parsed

    def close(self) -> str:
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        return self.process.stderr.read() if self.process.stderr else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="실행 중인 KiCad 10 GUI와 Konnect MCP의 실제 IPC/CLI 통합을 검증합니다."
    )
    parser.add_argument("--project", type=Path, required=True, help="열려 있는 .kicad_pro")
    parser.add_argument("--board", type=Path, required=True, help="열려 있는 .kicad_pcb")
    parser.add_argument("--evidence", type=Path, required=True, help="검증 증거 JSON 출력")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = args.project.resolve()
    board = args.board.resolve()
    assert project.is_file(), f"프로젝트 파일 누락: {project}"
    assert board.is_file(), f"보드 파일 누락: {board}"

    cli = subprocess.run(
        ["kicad-cli", "--version"], text=True, capture_output=True, timeout=30
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    cli_version = cli.stdout.strip().splitlines()[0]
    assert cli_version == "10.0.5", f"KiCad CLI 버전 불일치: {cli_version}"

    client = McpClient(args.timeout)
    stderr = ""
    try:
        initialized = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "kicad-live-acceptance", "version": "1.0.0"},
            },
        )["result"]
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        opened = client.call("open_project", {"path": str(project)})
        assert opened["kicad_ui_running"] is True, opened
        assert opened["ipc_address"].startswith("ipc://"), opened

        client.call("load_toolset", {"name": "verification"})
        ui = client.call("check_kicad_ui", {})
        assert ui == {"ipc_responsive": True, "running": True}, ui

        client.call("load_toolset", {"name": "pcb_components"})
        components = client.call("get_component_list", {"board": str(board)})
        assert isinstance(components.get("components"), list), components
        assert components.get("count") == len(components["components"]), components

        drc_output = args.evidence.with_suffix(".drc.json").resolve()
        drc = client.call(
            "run_drc",
            {
                "board": str(board),
                "output": str(drc_output),
                "severity": "warning",
                "limit": 50,
            },
        )
        assert isinstance(drc.get("total_violations"), int), drc
        assert drc_output.is_file(), f"DRC JSON 누락: {drc_output}"
        drc_report = json.loads(drc_output.read_text(encoding="utf-8"))
        assert isinstance(drc_report, list), "DRC report 최상위 형식은 배열이어야 합니다."
        assert len(drc_report) == drc["total_violations"], (
            f"DRC 위반 수 불일치: tool={drc['total_violations']} "
            f"report={len(drc_report)}"
        )
        severity_counts = {"error": 0, "warning": 0}
        for violation in drc_report:
            assert isinstance(violation, dict), violation
            severity = violation.get("severity")
            if severity in severity_counts:
                severity_counts[severity] += 1
        assert severity_counts["error"] == drc.get("errors"), severity_counts
        assert severity_counts["warning"] == drc.get("warnings"), severity_counts
        drc_sha256 = hashlib.sha256(drc_output.read_bytes()).hexdigest()

        evidence = {
            "schema_version": 1,
            "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kicad_cli_version": cli_version,
            "mcp_server": initialized["serverInfo"],
            "mcp_protocol_version": initialized["protocolVersion"],
            "project": str(project),
            "board": str(board),
            "ipc": opened,
            "ui": ui,
            "component_count": components["count"],
            "component_references": [
                item.get("reference") for item in components["components"]
            ],
            "drc": {
                "errors": drc.get("errors"),
                "warnings": drc.get("warnings"),
                "total_violations": drc["total_violations"],
                "report": str(drc_output),
                "report_sha256": drc_sha256,
            },
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("KiCad + Konnect live acceptance 통과")
        print(f"  KiCad CLI: {cli_version}")
        print(f"  MCP: {initialized['serverInfo']['name']} {initialized['serverInfo']['version']}")
        print(f"  IPC: {opened['ipc_address']}")
        print(f"  live components: {components['count']}")
        print(f"  DRC 실행: errors={drc.get('errors')} warnings={drc.get('warnings')}")
        print(f"  증거: {args.evidence}")
        return 0
    finally:
        stderr = client.close()
        if stderr and os.environ.get("KICAD_ACCEPTANCE_SHOW_STDERR") == "1":
            print(stderr, file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"KiCad + Konnect live acceptance 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
