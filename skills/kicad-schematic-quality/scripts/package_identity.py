#!/usr/bin/env python3
"""위치와 무관한 전체 스킬 패키지 원문 identity를 생성·재대조한다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat


def _inventory(root: Path) -> list[Path]:
    files = []
    for folder, directories, names in os.walk(root, followlinks=False):
        base = Path(folder)
        for name in tuple(directories):
            child = base / name
            if child.is_symlink():
                raise ValueError(f"패키지 내부 symlink 디렉터리 금지: {child}")
            if name == "__pycache__":
                directories.remove(name)
        for name in names:
            child = base / name
            if child.is_symlink():
                raise ValueError(f"패키지 내부 symlink 파일 금지: {child}")
            if child.suffix not in (".pyc", ".pyo"):
                files.append(child)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def capture(package_root: Path | None = None) -> dict:
    root = Path(package_root) if package_root is not None else Path(__file__).resolve().parents[1]
    if root.is_symlink() or not root.is_dir():
        raise ValueError("패키지 root는 symlink가 아닌 실제 디렉터리여야 합니다")
    entry = root / "SKILL.md"
    if entry.is_symlink() or not entry.is_file():
        raise ValueError("패키지 SKILL.md 정본이 없습니다")
    inventory = _inventory(root)
    rows = []
    for path in inventory:
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"패키지 특수 파일 금지: {path}")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            data = handle.read()
            after_fd = os.fstat(handle.fileno())
        after = path.stat(follow_symlinks=False)
        signature = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                   value.st_mtime_ns, value.st_ctime_ns, value.st_mode)
        if any(signature(item) != signature(before) for item in (opened, after_fd, after)):
            raise ValueError(f"패키지 판독 중 파일 변경: {path}")
        rows.append({"path": path.relative_to(root).as_posix(), "size": len(data),
                     "sha256": hashlib.sha256(data).hexdigest()})
    if inventory != _inventory(root):
        raise ValueError("패키지 판독 중 파일 목록 변경")
    value = {"schema_version": 1, "algorithm": "sha256-path-size-content-v1", "files": rows}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {**value, "sha256": hashlib.sha256(encoded).hexdigest()}


def strict_equal(left, right) -> bool:
    """Python의 True==1 동등성 대신 JSON 타입과 값을 함께 비교한다."""
    def validate(value):
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("JSON 객체 키는 문자열이어야 합니다")
            for item in value.values():
                validate(item)
        elif type(value) is list:
            for item in value:
                validate(item)
        elif type(value) not in (str, int, float, bool, type(None)):
            raise ValueError("JSON에서 표현할 수 없는 타입입니다")

    try:
        validate(left)
        validate(right)
        options = {"ensure_ascii": False, "sort_keys": True,
                   "separators": (",", ":"), "allow_nan": False}
        return json.dumps(left, **options) == json.dumps(right, **options)
    except (TypeError, ValueError):
        return False


def assert_unchanged(before: dict, package_root: Path | None = None) -> dict:
    after = capture(package_root)
    if not strict_equal(before, after):
        raise ValueError("실행 도중 패키지 원문 또는 identity 변경")
    return after


if __name__ == "__main__":
    print(json.dumps(capture(), ensure_ascii=False, indent=2))
