#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


DEFAULT_ROOT = Path(__file__).resolve().parent.parent


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode:
        raise AssertionError(
            f"명령 실패({result.returncode}): {' '.join(args)}\n{result.stdout}{result.stderr}"
        )
    return result


def resolve_repo(root: Path, source_path: str) -> Path:
    relative = Path(source_path)
    assert not relative.is_absolute(), f"source_path는 상대 경로여야 함: {source_path}"
    repo = (root / relative).resolve()
    assert repo.is_relative_to(root), f"source_path가 프로젝트 밖을 가리킴: {source_path}"
    assert (repo / ".git").exists(), f"초기화된 submodule이 아님: {repo}"
    return repo


def tag_commit(repo: Path, tag: str) -> str | None:
    ref = f"refs/tags/{tag}"
    exists = run("git", "show-ref", "--verify", "--quiet", ref, cwd=repo, check=False)
    if exists.returncode == 1:
        return None
    if exists.returncode:
        raise AssertionError(f"tag ref 확인 실패: {ref}")
    return run("git", "rev-parse", f"{ref}^{{commit}}", cwd=repo).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="얕은 submodule clone에 잠금 파일의 정확한 tag ref를 복구합니다."
    )
    parser.add_argument("component", help="upstreams.lock.json의 component 이름")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    lock_file = (args.lock_file or root / "upstreams.lock.json").resolve()
    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    assert lock["schema_version"] == 2, "지원하지 않는 lock schema"
    assert args.component in lock["components"], f"알 수 없는 component: {args.component}"

    item = lock["components"][args.component]
    expected_origin = item["origin"]
    expected_commit = item["commit"]
    tag = item.get("upstream_tag", item.get("tag"))
    assert tag, f"tag 계약 누락: {args.component}"
    expected_tag_commit = item.get("upstream_commit", expected_commit)
    repo = resolve_repo(root, item["source_path"])

    ref = f"refs/tags/{tag}"
    run("git", "check-ref-format", ref, cwd=repo)
    actual_origin = run("git", "remote", "get-url", "origin", cwd=repo).stdout.strip()
    assert actual_origin == expected_origin, (
        f"origin 불일치: expected={expected_origin}, actual={actual_origin}"
    )
    actual_head = run("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    assert actual_head == expected_commit, (
        f"HEAD 불일치: expected={expected_commit}, actual={actual_head}"
    )

    current_tag_commit = tag_commit(repo, tag)
    if current_tag_commit is None:
        fetch_source = item.get("upstream_origin", "origin")
        run(
            "git",
            "fetch",
            "--no-tags",
            "--depth=1",
            fetch_source,
            f"{ref}:{ref}",
            cwd=repo,
        )
        current_tag_commit = tag_commit(repo, tag)

    assert current_tag_commit == expected_tag_commit, (
        f"tag commit 불일치: {tag}, expected={expected_tag_commit}, actual={current_tag_commit}"
    )
    print(f"잠금 tag 확인: {args.component} {tag} @ {expected_tag_commit[:12]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, KeyError, OSError, ValueError) as exc:
        print(f"잠금 tag 복구 실패: {exc}", file=sys.stderr)
        raise SystemExit(1)
