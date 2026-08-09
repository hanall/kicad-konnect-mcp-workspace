#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(
            f"명령 실패({result.returncode}): {' '.join(args)}\n{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    allow_uninitialized = os.environ.get("VERIFY_ALLOW_UNINITIALIZED") == "1"
    lock = json.loads((ROOT / "upstreams.lock.json").read_text(encoding="utf-8"))
    assert lock["schema_version"] == 2

    for name in ("kicad", "konnect"):
        item = lock["components"][name]
        expected_url = item["origin"]
        repo = ROOT / item["source_path"]
        index_line = run("git", "ls-files", "--stage", "--", item["source_path"])
        fields = index_line.split()
        assert fields[:2] == ["160000", item["commit"]], f"{name} gitlink 불일치"
        if not repo.is_dir() or not (repo / ".git").exists():
            assert allow_uninitialized, f"submodule 누락: {repo}"
            continue
        assert run("git", "remote", "get-url", "origin", cwd=repo) == expected_url
        assert run("git", "rev-parse", "HEAD", cwd=repo) == item["commit"]
        tag = item.get("upstream_tag", item.get("tag"))
        expected_tag_commit = item.get("upstream_commit", item["commit"])
        assert tag, f"{name} tag 계약 누락"
        actual_tag_commit = run("git", "rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=repo)
        assert actual_tag_commit == expected_tag_commit, f"{name} tag commit 불일치: {tag}"
        if name == "konnect":
            remotes = run("git", "remote", cwd=repo).splitlines()
            if "upstream" in remotes:
                assert run("git", "remote", "get-url", "upstream", cwd=repo) == item[
                    "upstream_origin"
                ], "konnect upstream remote 불일치"
        assert run("git", "status", "--porcelain", cwd=repo) == "", f"{name} dirty"

    modules = (ROOT / ".gitmodules").read_text(encoding="utf-8")
    for item in lock["components"].values():
        assert item["origin"] in modules

    cargo_lock = ROOT / "upstream/konnect/Cargo.lock"
    assert 'source = "git+' not in cargo_lock.read_text(encoding="utf-8")

    config = tomllib.loads((ROOT / "config/konnect.toml").read_text(encoding="utf-8"))
    assert config["transport"] == "stdio"
    assert config["http_address"].startswith("127.0.0.1:")
    configured_project_dir = Path(config["project_dir"])
    assert not configured_project_dir.is_absolute(), "project_dir는 checkout 상대 경로여야 함"
    resolved_project_dir = (ROOT / configured_project_dir).resolve()
    assert resolved_project_dir == (ROOT / "projects").resolve(), (
        f"project_dir는 projects를 가리켜야 함: {config['project_dir']}"
    )

    mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["konnect"]
    mcp_command = Path(server["command"])
    assert not mcp_command.is_absolute(), "MCP command는 checkout 상대 경로여야 함"
    assert (ROOT / mcp_command).resolve() == (ROOT / "scripts/run-konnect.sh").resolve()
    assert "config/konnect.toml" in server["args"]

    launcher = ROOT / "scripts/run-konnect.sh"
    assert launcher.stat().st_mode & stat.S_IXUSR
    launcher_text = launcher.read_text(encoding="utf-8")
    assert 'export HOME="$RUNTIME_HOME"' in launcher_text
    assert 'cd "$ROOT"' in launcher_text
    assert (ROOT / ".runtime-home").resolve() != Path.home().resolve()

    root_status = run("git", "status", "--porcelain")
    if "upstream/kicad" in root_status or "upstream/konnect" in root_status:
        allowed = {"A  upstream/kicad", "A  upstream/konnect"}
        actual = {line for line in root_status.splitlines() if "upstream/" in line}
        assert actual <= allowed, f"예상하지 못한 submodule 상태: {actual}"

    print("프로젝트 검증 통과")
    print(f"  KiCad:   {lock['components']['kicad']['tag']} @ {lock['components']['kicad']['commit'][:12]}")
    print(
        "  Konnect: "
        f"{lock['components']['konnect']['upstream_tag']} base, "
        f"dev @ {lock['components']['konnect']['commit'][:12]}"
    )
    print(f"  Cargo.lock SHA-256: {sha256(cargo_lock)}")
    print("  MCP transport: stdio, runtime HOME: project-isolated")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"프로젝트 검증 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
