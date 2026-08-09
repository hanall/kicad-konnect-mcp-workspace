#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
KONNECT_SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def version_key(match: re.Match[str]) -> tuple[int, int, int]:
    return tuple(int(part) for part in match.groups())


def latest_stable_kicad_tag(tags: list[str]) -> str:
    candidates = []
    for tag in tags:
        match = SEMVER.fullmatch(tag)
        if match and int(match.group(2)) != 99:
            candidates.append((version_key(match), tag))
    if not candidates:
        raise ValueError("KiCad 안정 release tag를 찾지 못함")
    return max(candidates)[1]


def latest_konnect_tag(tags: list[str]) -> str:
    candidates = []
    for tag in tags:
        match = KONNECT_SEMVER.fullmatch(tag)
        if match:
            candidates.append((version_key(match), tag))
    if not candidates:
        raise ValueError("Konnect release tag를 찾지 못함")
    return max(candidates)[1]


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(
            f"명령 실패({result.returncode}): {' '.join(args)}\n{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


def remote_tags(origin: str) -> list[str]:
    output = run("git", "ls-remote", "--tags", "--refs", origin)
    return [line.rsplit("refs/tags/", 1)[1] for line in output.splitlines() if "refs/tags/" in line]


def load_lock(lock_file: Path) -> dict:
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    if lock["schema_version"] != 2:
        raise ValueError("지원하지 않는 lock schema")
    return lock


def discover(lock: dict) -> tuple[str, str]:
    kicad = lock["components"]["kicad"]
    konnect = lock["components"]["konnect"]
    return (
        latest_stable_kicad_tag(remote_tags(kicad["origin"])),
        latest_konnect_tag(remote_tags(konnect["upstream_origin"])),
    )


def check(lock_file: Path) -> int:
    lock = load_lock(lock_file)
    latest_kicad, latest_konnect = discover(lock)
    pinned_kicad = lock["components"]["kicad"]["tag"]
    pinned_konnect = lock["components"]["konnect"]["upstream_tag"]
    print("upstream 안정 tag 상태")
    print(f"  KiCad:   pinned={pinned_kicad} latest={latest_kicad}")
    print(f"  Konnect: pinned={pinned_konnect} latest={latest_konnect}")
    return 0 if (pinned_kicad, pinned_konnect) == (latest_kicad, latest_konnect) else 1


def update_kicad(lock_file: Path) -> int:
    lock = load_lock(lock_file)
    item = lock["components"]["kicad"]
    latest = latest_stable_kicad_tag(remote_tags(item["origin"]))
    if latest == item["tag"]:
        print(f"KiCad가 이미 최신 안정 release임: {latest}")
        return 0

    if run("git", "status", "--porcelain"):
        raise AssertionError("root worktree가 dirty이므로 KiCad update를 중단함")
    repo = (ROOT / item["source_path"]).resolve()
    if run("git", "status", "--porcelain", cwd=repo):
        raise AssertionError("KiCad submodule이 dirty이므로 update를 중단함")
    if run("git", "remote", "get-url", "origin", cwd=repo) != item["origin"]:
        raise AssertionError("KiCad origin이 잠금 계약과 다름")

    ref = f"refs/tags/{latest}"
    run("git", "fetch", "--no-tags", "origin", f"{ref}:{ref}", cwd=repo)
    commit = run("git", "rev-parse", f"{ref}^{{commit}}", cwd=repo)
    tag_object = run("git", "rev-parse", ref, cwd=repo)
    branch = f"official/{latest}"
    run("git", "switch", "--force-create", branch, commit, cwd=repo)

    item.update(
        {
            "tag": latest,
            "commit": commit,
            "tag_object": None if tag_object == commit else tag_object,
            "commit_date": run("git", "show", "-s", "--format=%cI", commit, cwd=repo),
            "local_branch": branch,
        }
    )
    lock["retrieved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    temporary = lock_file.with_suffix(lock_file.suffix + ".tmp")
    temporary.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(lock_file)
    run("python3", "scripts/verify-project.py")
    print(f"KiCad 최신 안정 release 반영: {latest} @ {commit[:12]}")
    print("변경을 검토한 뒤 make check-local을 실행하세요.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="공식 upstream release 추적 도구")
    parser.add_argument("command", choices=("check", "update-kicad"))
    parser.add_argument("--lock-file", type=Path, default=ROOT / "upstreams.lock.json")
    args = parser.parse_args()
    lock_file = args.lock_file.resolve()
    return check(lock_file) if args.command == "check" else update_kicad(lock_file)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"upstream 관리 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
