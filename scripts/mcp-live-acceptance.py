#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts/run-konnect.sh"
CONFIG = ROOT / "config/konnect.toml"


class McpClient:
    def __init__(self, timeout: float, *, command: list[str] | None = None) -> None:
        self.timeout = timeout
        self.next_id = 1
        self.process = subprocess.Popen(
            command or [str(LAUNCHER), "--config", str(CONFIG)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
        )
        assert self.process.stdout is not None
        self.responses: queue.Queue = queue.Queue(maxsize=1024)
        self.stderr_lines: deque[str] = deque(maxlen=1000)

        def read_stdout() -> None:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                try:
                    self.responses.put(json.loads(line))
                except json.JSONDecodeError:
                    self.responses.put({"protocol_error": line})
            self.responses.put(None)

        def read_stderr() -> None:
            assert self.process.stderr is not None
            for line in self.process.stderr:
                self.stderr_lines.append(line)

        self.stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

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
            try:
                response = self.responses.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                break
            if response is None:
                raise AssertionError(f"Konnect 응답 전에 종료: {''.join(self.stderr_lines)[-4000:]}")
            if "protocol_error" in response:
                raise AssertionError(f"MCP JSON 응답 형식 오류: {response['protocol_error'][:1000]}")
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
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.stdout_thread.join(timeout=1)
        self.stderr_thread.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream:
                stream.close()
        return "".join(self.stderr_lines)


def summarize_drc_report(report: object) -> dict[str, Any]:
    """실제 저장된 DRC 세 범주를 누락 없이 집계한다."""
    assert isinstance(report, dict), "DRC report는 범주별 객체여야 합니다."
    counts: dict[str, Any] = {"error": 0, "warning": 0, "total": 0, "categories": {}}
    for category in ("violations", "unconnected_items", "schematic_parity"):
        assert category in report, f"DRC 범주 누락: {category}"
        values = report[category]
        assert isinstance(values, list), f"DRC 범주 형식 불일치: {category}"
        counts["categories"][category] = len(values)
        for item in values:
            assert isinstance(item, dict), f"DRC 위반 항목 형식 불일치: {category}"
            severity = item.get("severity")
            assert severity in ("error", "warning", "info"), f"DRC severity 불일치: {severity}"
            counts["total"] += 1
            if severity in ("error", "warning"):
                counts[severity] += 1
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="실행 중인 KiCad 10 GUI와 Konnect MCP의 실제 IPC/CLI 통합을 검증합니다."
    )
    parser.add_argument("--project", type=Path, required=True, help="열려 있는 .kicad_pro")
    parser.add_argument("--board", type=Path, required=True, help="열려 있는 .kicad_pcb")
    parser.add_argument("--evidence", type=Path, required=True, help="검증 증거 JSON 출력")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--require-clean-design", action="store_true", help="실행 성공뿐 아니라 모든 DRC 범주 0건을 요구")
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
    lock = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))
    assert cli_version == lock["components"]["kicad"]["tag"], f"KiCad CLI 버전 불일치: {cli_version}"

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
        expected_server_version = lock["components"]["konnect"].get(
            "version", lock["components"]["konnect"]["upstream_tag"].removeprefix("v")
        )
        assert initialized["serverInfo"]["version"] == expected_server_version, initialized
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        opened = client.call("open_project", {"path": str(project)})
        assert opened["kicad_ui_running"] is True, opened
        assert opened["ipc_address"].startswith("ipc://"), opened

        client.call("load_toolset", {"name": "verification"})
        ui = client.call("check_kicad_ui", {})
        assert ui["ipc_responsive"] is True and ui["running"] is True, ui
        assert ui.get("timed_out") is False and ui.get("ipc_failure") is None, ui

        client.call("load_toolset", {"name": "pcb_board"})
        board_info = client.call("get_board_info", {"board": str(board)})
        assert board_info["source"] == "ipc", board_info
        assert Path(board_info["file"]).resolve() == board, board_info

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
                "severity": "info",
                "limit": 50,
                "sync_live_board": True,
                "refill_zones": True,
            },
        )
        assert isinstance(drc.get("total_violations"), int), drc
        assert drc["live_board_synced"] is True, drc
        assert drc["source"] == "saved_file", drc
        assert drc["categories_not_reported"] == [], drc
        assert drc_output.is_file(), f"DRC JSON 누락: {drc_output}"
        drc_report = json.loads(drc_output.read_text(encoding="utf-8"))
        severity_counts = summarize_drc_report(drc_report)
        assert severity_counts["total"] == drc["total_violations"], (
            f"DRC 위반 수 불일치: tool={drc['total_violations']} "
            f"report={severity_counts['total']}"
        )
        assert severity_counts["error"] == drc.get("errors"), severity_counts
        assert severity_counts["warning"] == drc.get("warnings"), severity_counts
        drc_sha256 = hashlib.sha256(drc_output.read_bytes()).hexdigest()

        evidence = {
            "schema_version": 2,
            "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kicad_cli_version": cli_version,
            "mcp_server": initialized["serverInfo"],
            "mcp_protocol_version": initialized["protocolVersion"],
            "project": str(project),
            "board": str(board),
            "ipc": opened,
            "ui": ui,
            "board_info": board_info,
            "component_count": components["count"],
            "component_references": [
                item.get("reference") for item in components["components"]
            ],
            "drc": {
                "errors": drc.get("errors"),
                "warnings": drc.get("warnings"),
                "total_violations": drc["total_violations"],
                "categories": severity_counts["categories"],
                "live_board_synced": drc["live_board_synced"],
                "report": str(drc_output),
                "report_sha256": drc_sha256,
            },
            "design_clean": severity_counts["total"] == 0,
        }
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if args.require_clean_design:
            assert severity_counts["total"] == 0, (
                f"엄격 설계 gate 실패: errors={severity_counts['error']} "
                f"warnings={severity_counts['warning']} total={severity_counts['total']}; "
                f"증거={args.evidence}"
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
