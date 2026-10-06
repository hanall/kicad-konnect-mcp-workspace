#!/usr/bin/env python3
"""새 Konnect STDIO 서버에 연결하고 모든 요청과 응답을 증거로 보존한다.

입력은 {"tool": 이름, "arguments": 객체} 형식의 JSONL이다.
{"method":"tools/list"} 또는 {"method":"initialize", "params":...}도 지원한다.
회로 파일을 직접 읽거나 수정하지 않는다. 회로 변경은 MCP tools/call만 사용한다.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Konnect MCP 시연 및 응답 기록")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.evidence_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stderr = (out / "server-stderr.log").open("a")
    journal = (out / "mcp-session.jsonl").open("a", buffering=1)
    process = subprocess.Popen(
        [str(ROOT / "scripts/run-konnect.sh"), "--config", str(ROOT / "config/konnect.toml")],
        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
        text=True, bufsize=1, env=os.environ.copy(),
    )
    responses = queue.Queue()

    def read_responses():
        for line in process.stdout:
            try:
                responses.put(json.loads(line))
            except json.JSONDecodeError:
                responses.put({"parse_error": line})
        responses.put({"server_eof": True})

    threading.Thread(target=read_responses, daemon=True).start()
    seq = 0

    def request(method, params):
        nonlocal seq
        seq += 1
        payload = {"jsonrpc": "2.0", "id": seq, "method": method, "params": params}
        start = time.monotonic()
        record = {"id": seq, "started_at": datetime.now().astimezone().isoformat(), "request": payload}
        journal.write(json.dumps({"event": "request", **record}, ensure_ascii=False) + "\n")
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()
        deadline = start + 180
        while True:
            response = responses.get(timeout=max(.01, deadline - time.monotonic()))
            if response.get("server_eof") or "parse_error" in response:
                raise RuntimeError(response)
            if response.get("id") == seq:
                break
            journal.write(json.dumps({"event": "notification", "response": response}, ensure_ascii=False) + "\n")
        record.update(response=response, duration_ms=round((time.monotonic()-start)*1000, 3))
        journal.write(json.dumps({"event": "response", **record}, ensure_ascii=False) + "\n")
        (out / f"response-{seq:04d}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n")
        return record

    try:
        init = request("initialize", {"protocolVersion":"2025-06-18", "capabilities":{},
                                     "clientInfo":{"name":"hanol-visible-demo", "version":"1.0.0"}})
        info = init["response"]["result"]["serverInfo"]
        lock = json.loads((ROOT / "upstreams.lock.json").read_text())
        expected_version = lock["components"]["konnect"].get(
            "version", lock["components"]["konnect"]["upstream_tag"].removeprefix("v")
        )
        assert info["version"] == expected_version, info
        process.stdin.write(json.dumps({"jsonrpc":"2.0", "method":"notifications/initialized", "params":{}})+"\n")
        process.stdin.flush()
        print(json.dumps({"연결":info, "PID":process.pid, "증거":str(out)}, ensure_ascii=False), flush=True)
        for line in sys.stdin:
            if not line.strip():
                continue
            item = json.loads(line)
            if item.get("close"):
                break
            method = item.get("method", "tools/call")
            params = item.get("params", {"name":item.get("tool"), "arguments":item.get("arguments", {})})
            record = request(method, params)
            response = record["response"]
            result = response.get("result", response)
            if item.get("summary"):
                result = {"isError":result.get("isError",False), "응답파일":str(out/f"response-{seq:04d}.json")}
            print(json.dumps({"id":seq,"duration_ms":record["duration_ms"],"result":result},ensure_ascii=False), flush=True)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        journal.close()
        stderr.close()


if __name__ == "__main__":
    main()
