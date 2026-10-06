#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts/run-konnect.sh"
CONFIG = ROOT / "config/konnect.toml"


def read_json_line(process: subprocess.Popen[str], timeout: float = 30.0) -> dict:
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"MCP server 조기 종료({process.returncode}): {stderr}")
        events = selector.select(max(0.0, deadline - time.monotonic()))
        if not events:
            break
        line = process.stdout.readline()
        if line:
            return json.loads(line)
    raise AssertionError("MCP 응답 timeout")


def send(process: subprocess.Popen[str], payload: dict) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def main() -> int:
    if not LAUNCHER.is_file():
        raise AssertionError(f"launcher 누락: {LAUNCHER}")

    # 0.13은 시작 시 guidance를 자동 설치하지 않는다. 구 marker를 버전
    # 증거로 사용하지 않고, 시작 전후 보존 여부와 initialize를 각각 검증한다.
    runtime_marker = ROOT / ".runtime-home/.konnect/.installed"
    marker_before = runtime_marker.read_bytes() if runtime_marker.exists() else None
    process = subprocess.Popen(
        [str(LAUNCHER), "--config", str(CONFIG)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
        bufsize=1,
    )
    try:
        send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "hanol-project-smoke", "version": "1.0.0"},
                },
            },
        )
        initialized = read_json_line(process)
        assert initialized["id"] == 1
        result = initialized["result"]
        assert result["serverInfo"]["name"].lower() == "konnect"
        lock = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))
        expected_version = lock["components"]["konnect"].get(
            "version", lock["components"]["konnect"]["upstream_tag"].removeprefix("v")
        )
        assert result["serverInfo"]["version"] == expected_version

        send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = read_json_line(process)
        assert listed["id"] == 2
        tools = listed["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert "list_toolboxes" in names
        assert "load_toolset" in names
        assert len(tools) >= 10

        marker_after = runtime_marker.read_bytes() if runtime_marker.exists() else None
        assert marker_after == marker_before, "MCP 시작이 기존 guidance marker를 변경함"

        print("MCP smoke 통과")
        print(f"  protocolVersion: {result['protocolVersion']}")
        print(f"  server: {result['serverInfo']['name']} {result['serverInfo']['version']}")
        print(f"  starter tools: {len(tools)}")
        print(f"  기존 guidance marker 보존: {runtime_marker}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"MCP smoke 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
