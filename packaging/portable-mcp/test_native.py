#!/usr/bin/env python3
"""별도 HOME과 새 경로에서 번들 stdio를 읽기 전용 검사한다. CAD는 열지 않는다."""
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def main():
    bundle = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="portable 한글 path ", dir=out) as temporary:
        root = Path(temporary)
        copied = root / "moved bundle"
        shutil.copytree(bundle, copied)
        home = root / "private-home"
        project = root / "empty-project"
        home.mkdir()
        project.mkdir()
        cli = shutil.which("kicad-cli")
        assert cli, "설치된 KiCad CLI가 없습니다"
        config = {"transport": "stdio", "project_dir": str(project), "kicad_cli": cli,
                  "kicad_binary": shutil.which("kicad") or "/usr/bin/kicad", "ipc_address": "",
                  "log_level": "info"}
        (copied / "config/active.toml").write_text(
            "\n".join(k + " = " + json.dumps(v, ensure_ascii=False) for k, v in config.items()) + "\n")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("KONNECT_", "KICAD_", "ACUW_"))}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
                   XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"))
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(key, None)
        launcher = copied / "Start-Konnect"
        os.chmod(launcher, 0o755)
        os.chmod(copied / "bin/linux-x86_64/konnect", 0o755)
        for option in ("--version", "--check"):
            result = subprocess.run([str(launcher), option], env=env, capture_output=True, timeout=15)
            assert result.returncode == 0 and not result.stderr, result
        transcript = []
        with (out / "server.stderr.log").open("wb") as err:
            proc = subprocess.Popen([str(launcher)], cwd=root, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=err, start_new_session=True)
            selector = selectors.DefaultSelector()
            selector.register(proc.stdout, selectors.EVENT_READ)
            buffer = b""

            def send(payload):
                transcript.append({"request": payload})
                proc.stdin.write(json.dumps(payload, ensure_ascii=False).encode() + b"\n")
                proc.stdin.flush()

            def receive(identifier):
                nonlocal buffer
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if b"\n" not in buffer:
                        assert selector.select(max(0, deadline - time.monotonic())), "응답 시간 초과"
                        chunk = os.read(proc.stdout.fileno(), 1024 * 1024)
                        assert chunk, "응답 전에 서버가 종료되었습니다"
                        buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        reply = json.loads(line)
                        transcript.append({"response": reply})
                        if reply.get("id") == identifier:
                            assert "error" not in reply, reply
                            return reply["result"]
                raise AssertionError("응답 시간 초과")

            def call(identifier, name, arguments):
                send({"jsonrpc": "2.0", "id": identifier, "method": "tools/call",
                      "params": {"name": name, "arguments": arguments}})
                result = receive(identifier)
                assert not result.get("isError"), result
                return result

            try:
                send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "portable-readonly-smoke", "version": "1"}}})
                initialized = receive(1)
                assert initialized["serverInfo"]["version"] == "0.13.0+hanall.1"
                send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
                listed = receive(2)
                names = {t["name"] for t in listed["tools"]}
                assert {"list_toolboxes", "load_toolset"}.issubset(names)
                boxes = call(3, "list_toolboxes", {})
                if "get_installation_info" not in names:
                    call(4, "load_toolset", {"toolset_name": "config"})
                info = call(5, "get_installation_info", {})
                identity = info.get("structuredContent")
                if identity is None:
                    for block in info.get("content", []):
                        if block.get("type") == "text":
                            try:
                                identity = json.loads(block["text"])
                                break
                            except ValueError:
                                pass
                assert isinstance(identity, dict), info
                assert identity["build"]["version"] == "0.13.0+hanall.1", identity
                assert identity["build"]["commit"] == "94f80350cf67db27b179a06a8f6dbebfe4717927", identity
                actual = Path(identity["runtime"]["executable_path"])
                assert actual == copied / "bin/linux-x86_64/konnect", actual
                digest = hashlib.sha256(actual.read_bytes()).hexdigest()
                assert digest == hashlib.sha256((bundle / "bin/linux-x86_64/konnect").read_bytes()).hexdigest()
                assert not list(project.iterdir()), "빈 프로젝트에 파일이 생성되었습니다"
                report = {"status": "PASS", "scope": "Linux stdio만; Windows·GUI·CAD 쓰기·IPC 미검증",
                          "server_version": identity["build"]["version"], "source_commit": identity["build"]["commit"],
                          "server_sha256": digest, "starter_tools": len(names),
                          "korean_space_relocation": True, "private_home": True, "project_unchanged": True}
            finally:
                proc.stdin.close()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=5)
                selector.close()
                (out / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n")
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
