#!/usr/bin/env python3
"""KiCad library tree manifest creation and fail-closed verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any, Iterable


LIBRARY_ROOTS = ("symbols", "footprints", "3dmodels")
SCHEMA_VERSION = 1


class IntegrityError(RuntimeError):
    """A library tree or its trust anchor did not satisfy the contract."""


def stable_stat_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def sha256_file(path: Path, expected_metadata: os.stat_result) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or stable_stat_identity(
            before
        ) != stable_stat_identity(expected_metadata):
            raise IntegrityError(f"검증 중 파일이 교체됐습니다: {path}")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if stable_stat_identity(before) != stable_stat_identity(after):
        raise IntegrityError(f"검증 중 파일이 변경됐습니다: {path}")
    return digest.hexdigest()


def mode_string(mode: int) -> str:
    return f"{stat.S_IMODE(mode):04o}"


def scan_tree(
    root: Path, *, include_unexpected_root_entries: bool = False
) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise IntegrityError(f"라이브러리 root가 디렉터리가 아닙니다: {root}")

    entries: list[dict[str, Any]] = []

    def checked_symlink_target(absolute: Path, relative: Path) -> str:
        target = os.readlink(absolute)
        if os.path.isabs(target):
            raise IntegrityError(
                f"symlink 경로 이탈(absolute): {relative.as_posix()} -> {target}"
            )
        try:
            resolved = (absolute.parent / target).resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError) as error:
            raise IntegrityError(
                f"symlink 경로 이탈: {relative.as_posix()} -> {target}"
            ) from error
        return target

    def visit(relative: Path) -> None:
        absolute = root / relative
        metadata = absolute.lstat()
        common = {"path": relative.as_posix(), "mode": mode_string(metadata.st_mode)}
        if stat.S_ISLNK(metadata.st_mode):
            entries.append(
                {
                    **common,
                    "type": "symlink",
                    "target": checked_symlink_target(absolute, relative),
                }
            )
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append({**common, "type": "directory"})
            with os.scandir(absolute) as iterator:
                names = sorted(entry.name for entry in iterator)
            for name in names:
                visit(relative / name)
        elif stat.S_ISREG(metadata.st_mode):
            entries.append(
                {
                    **common,
                    "type": "file",
                    "size": metadata.st_size,
                    "sha256": sha256_file(absolute, metadata),
                }
            )
        else:
            raise IntegrityError(
                f"지원하지 않는 파일 형식입니다: {relative.as_posix()}"
            )

    for name in LIBRARY_ROOTS:
        path = root / name
        try:
            metadata = path.lstat()
        except FileNotFoundError as error:
            raise IntegrityError(
                f"필수 라이브러리 디렉터리가 없습니다: {name}"
            ) from error
        if not stat.S_ISDIR(metadata.st_mode):
            raise IntegrityError(f"필수 라이브러리 디렉터리가 없습니다: {name}")
        visit(Path(name))
    if include_unexpected_root_entries:
        with os.scandir(root) as iterator:
            unexpected = sorted(
                entry.name for entry in iterator if entry.name not in LIBRARY_ROOTS
            )
        for name in unexpected:
            visit(Path(name))
    entries.sort(key=lambda entry: entry["path"])
    return entries


def canonical_manifest(version: str, entries: Iterable[dict[str, Any]]) -> bytes:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "product": "KiCad",
        "version": version,
        "library_roots": list(LIBRARY_ROOTS),
        "entries": list(entries),
    }
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def load_manifest(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise IntegrityError(
            "manifest SHA-256 불일치: "
            f"expected={expected_sha256} actual={actual_sha256}"
        )
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrityError(f"manifest JSON을 읽을 수 없습니다: {error}") from error
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise IntegrityError("manifest schema_version 불일치")
    if manifest.get("product") != "KiCad":
        raise IntegrityError("manifest product 불일치")
    if manifest.get("library_roots") != list(LIBRARY_ROOTS):
        raise IntegrityError("manifest library_roots 불일치")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise IntegrityError("manifest version이 없습니다")
    if not isinstance(manifest.get("entries"), list):
        raise IntegrityError("manifest entries가 배열이 아닙니다")
    validate_manifest_entries(manifest["entries"])
    if raw != canonical_manifest(manifest["version"], manifest["entries"]):
        raise IntegrityError("manifest가 canonical JSON 형식이 아닙니다")
    return manifest


def validate_manifest_entries(entries: list[Any]) -> None:
    paths: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise IntegrityError(f"manifest entry가 object가 아닙니다: index={index}")
        path = entry.get("path")
        entry_type = entry.get("type")
        mode = entry.get("mode")
        if not isinstance(path, str) or not path:
            raise IntegrityError(f"manifest entry path가 잘못됐습니다: index={index}")
        pure_path = PurePosixPath(path)
        if (
            pure_path.is_absolute()
            or pure_path.as_posix() != path
            or any(part in ("", ".", "..") for part in pure_path.parts)
            or pure_path.parts[0] not in LIBRARY_ROOTS
        ):
            raise IntegrityError(f"manifest entry path가 안전하지 않습니다: {path}")
        if (
            not isinstance(mode, str)
            or len(mode) != 4
            or any(character not in "01234567" for character in mode)
        ):
            raise IntegrityError(f"manifest entry mode가 잘못됐습니다: {path}")

        required_keys = {"path", "mode", "type"}
        if entry_type == "file":
            required_keys |= {"size", "sha256"}
            size = entry.get("size")
            sha256 = entry.get("sha256")
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise IntegrityError(f"manifest file size가 잘못됐습니다: {path}")
            if (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256)
            ):
                raise IntegrityError(f"manifest file SHA-256이 잘못됐습니다: {path}")
        elif entry_type == "symlink":
            required_keys.add("target")
            target = entry.get("target")
            if not isinstance(target, str) or not target or os.path.isabs(target):
                raise IntegrityError(f"manifest symlink target이 잘못됐습니다: {path}")
        elif entry_type != "directory":
            raise IntegrityError(f"manifest entry type이 잘못됐습니다: {path}")
        if set(entry) != required_keys:
            raise IntegrityError(f"manifest entry field가 잘못됐습니다: {path}")
        paths.append(path)

    if paths != sorted(paths):
        raise IntegrityError("manifest entries가 path 순서가 아닙니다")
    if len(paths) != len(set(paths)):
        raise IntegrityError("manifest entries에 중복 path가 있습니다")


def count_files(entries: Iterable[dict[str, Any]]) -> int:
    return sum(entry.get("type") == "file" for entry in entries)


def compare_entries(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> None:
    expected_by_path = {entry["path"]: entry for entry in expected}
    actual_by_path = {entry["path"]: entry for entry in actual}
    expected_paths = set(expected_by_path)
    actual_paths = set(actual_by_path)
    missing = sorted(expected_paths - actual_paths)
    extra = sorted(actual_paths - expected_paths)
    changed = sorted(
        path
        for path in expected_paths & actual_paths
        if expected_by_path[path] != actual_by_path[path]
    )
    if not (missing or changed or extra):
        return

    lines = [
        "라이브러리 tree가 신뢰된 manifest와 다릅니다: "
        f"missing={len(missing)} changed={len(changed)} extra={len(extra)}"
    ]
    lines.extend(f"missing: {path}" for path in missing)
    lines.extend(f"changed: {path}" for path in changed)
    lines.extend(f"extra: {path}" for path in extra)
    raise IntegrityError("\n".join(lines))


def command_create(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    entries = scan_tree(root)
    raw = canonical_manifest(args.version, entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    print(
        "KiCad 라이브러리 manifest 생성: "
        f"entries={len(entries)} files={count_files(entries)} "
        f"sha256={hashlib.sha256(raw).hexdigest()}"
    )


def command_verify(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest, args.manifest_sha256)
    expected = manifest["entries"]
    actual = scan_tree(args.root.resolve(), include_unexpected_root_entries=True)
    confirmed = scan_tree(args.root.resolve(), include_unexpected_root_entries=True)
    if confirmed != actual:
        raise IntegrityError(
            "검증 두 pass 사이에 라이브러리 tree가 변경됐습니다"
        )
    compare_entries(expected, actual)
    print(
        "KiCad 라이브러리 무결성 검증 통과: "
        f"entries={len(actual)} files={count_files(actual)}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="정렬된 library manifest 생성")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--version", required=True)
    create.set_defaults(handler=command_create)

    verify = subparsers.add_parser("verify", help="신뢰 anchor에 결속해 tree 검증")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--manifest-sha256", required=True)
    verify.set_defaults(handler=command_verify)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        args.handler(args)
    except (IntegrityError, OSError) as error:
        print(f"KiCad 라이브러리 무결성 검증 실패: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
