#!/usr/bin/env python3
"""고정 Freerouting JAR와 JRE 25를 프로젝트 artifact에만 설치·검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "config/freerouting.lock.json"


class InstallerError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_lock(path: Path) -> dict:
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallerError(f"lock을 읽을 수 없습니다: {path}: {error}") from error
    if lock.get("schema_version") != 1:
        raise InstallerError("지원하지 않는 lock schema_version")
    for section in ("freerouting", "jre", "approval"):
        if not isinstance(lock.get(section), dict):
            raise InstallerError(f"lock section 누락: {section}")
    for section in ("freerouting", "jre"):
        url = lock[section].get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise InstallerError(f"{section} URL은 exact HTTPS여야 합니다")
        digest = lock[section].get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise InstallerError(f"{section} SHA-256이 잘못되었습니다")
    if lock["freerouting"].get("digest_is_signature") is not False:
        raise InstallerError("GitHub asset digest를 독립 서명으로 표시할 수 없습니다")
    return lock


def validate_target(root: Path, requested: Path) -> Path:
    root = root.resolve()
    artifacts = (root / ".artifacts").resolve()
    target = (requested if requested.is_absolute() else root / requested).resolve()
    if target == artifacts or not target.is_relative_to(artifacts):
        raise InstallerError("target은 프로젝트 .artifacts 하위 전용 디렉터리여야 합니다")
    if target.exists() and not target.is_dir():
        raise InstallerError("target이 디렉터리가 아닙니다")
    return target


def verify_blob(path: Path, spec: dict, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise InstallerError(f"{label}이 regular file이 아닙니다: {path}")
    size = path.stat().st_size
    if size != spec["size"]:
        raise InstallerError(f"{label} size 불일치: {size} != {spec['size']}")
    digest = sha256_file(path)
    if digest != spec["sha256"]:
        raise InstallerError(f"{label} SHA-256 불일치: {digest}")


def verify_install_manifest(path: Path, lock_sha256: str) -> None:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InstallerError(f"설치 manifest를 읽을 수 없습니다: {error}") from error
    if manifest.get("lock_sha256") != lock_sha256:
        raise InstallerError("설치 manifest와 현재 lock SHA-256이 다릅니다")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    if result.returncode != 0:
        raise InstallerError(
            f"명령 실패 rc={result.returncode}: {command!r}\n{result.stdout}\n{result.stderr}"
        )
    return result


def _deb_metadata(path: Path) -> dict[str, str]:
    values = {}
    for field in ("Package", "Version", "Architecture"):
        values[field] = _run(["dpkg-deb", "--field", str(path), field]).stdout.strip()
    return values


def _verify_relocated_jre(target: Path, lock: dict) -> dict:
    jre = lock["jre"]
    java = target / jre["java_relative_path"]
    if not java.is_file() or not os.access(java, os.X_OK):
        raise InstallerError(f"격리 Java 실행 파일이 없습니다: {java}")
    jvm_root = java.parents[1]
    escaped = []
    prefix = jre["absolute_symlink_prefix"]
    for path in jvm_root.rglob("*"):
        if path.is_symlink() and os.readlink(path).startswith(prefix):
            escaped.append(str(path))
    if escaped:
        raise InstallerError(f"격리 JRE에 system /etc symlink가 남았습니다: {escaped}")
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(target / "runtime-home"),
            "XDG_CONFIG_HOME": str(target / "runtime-home/.config"),
            "XDG_STATE_HOME": str(target / "runtime-home/.local/state"),
            "XDG_CACHE_HOME": str(target / "runtime-home/.cache"),
        }
    )
    result = _run([str(java), "-version"], env=env)
    version_output = result.stdout + result.stderr
    if jre["java_version_contains"] not in version_output:
        raise InstallerError(f"Java version 불일치: {version_output.strip()}")
    return {"java": str(java), "version_output": version_output.strip()}


def verify_runtime(target: Path, lock: dict, lock_sha256: str, *, require_manifest: bool) -> dict:
    jar = target / "bin" / lock["freerouting"]["asset"]
    deb = target / "download" / lock["jre"]["filename"]
    verify_blob(jar, lock["freerouting"], "Freerouting JAR")
    verify_blob(deb, lock["jre"], "JRE Debian package")
    metadata = _deb_metadata(deb)
    expected = {
        "Package": lock["jre"]["package"],
        "Version": lock["jre"]["version"],
        "Architecture": lock["jre"]["architecture"],
    }
    if metadata != expected:
        raise InstallerError(f"Debian package metadata 불일치: {metadata} != {expected}")
    java = _verify_relocated_jre(target, lock)
    if require_manifest:
        verify_install_manifest(target / "INSTALL-MANIFEST.json", lock_sha256)
    system_java = Path("/usr/bin/java").resolve()
    if system_java.is_relative_to(target):
        raise InstallerError("system Java가 artifact runtime을 가리킵니다")
    return {
        "target": str(target),
        "jar": str(jar),
        "jar_sha256": sha256_file(jar),
        "deb": str(deb),
        "deb_sha256": sha256_file(deb),
        "deb_metadata": metadata,
        "java": java,
        "system_java": str(system_java),
        "digest_is_signature": False,
    }


def _download(url: str, destination: Path, expected: dict, label: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Konnect-Freerouting-Installer/1"})
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=300) as response, destination.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > expected["size"]:
                    raise InstallerError(f"{label}이 고정 size를 초과했습니다")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
        destination.unlink(missing_ok=True)
        raise InstallerError(f"{label} download size/SHA-256 불일치")


def _relocate_debian_jre(extracted: Path, lock: dict) -> list[dict]:
    jre = lock["jre"]
    java = extracted / jre["java_relative_path"]
    jvm_root = java.parents[1]
    etc = extracted / jre["etc_relative_path"]
    prefix = jre["absolute_symlink_prefix"]
    replaced = []
    for link in sorted(path for path in jvm_root.rglob("*") if path.is_symlink()):
        raw = os.readlink(link)
        if not raw.startswith("/"):
            if not link.resolve().is_relative_to(extracted):
                raise InstallerError(f"JRE relative symlink escape: {link} -> {raw}")
            continue
        if not raw.startswith(prefix):
            raise InstallerError(f"허용되지 않은 JRE absolute symlink: {link} -> {raw}")
        source = etc / raw[len(prefix) :]
        if not source.exists() or source.is_symlink():
            raise InstallerError(f"JRE relocation source 누락: {source}")
        link.unlink()
        if source.is_dir():
            shutil.copytree(source, link)
        else:
            shutil.copy2(source, link)
        replaced.append({"path": str(link.relative_to(extracted)), "source": str(source.relative_to(extracted))})
    return replaced


def _atomic_manifest(target: Path, lock_sha256: str, lock: dict, *, adopted: bool) -> None:
    manifest = {
        "schema_version": 1,
        "lock_sha256": lock_sha256,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "adopted_existing_verified_runtime": adopted,
        "freerouting_version": lock["freerouting"]["version"],
        "jar_sha256": lock["freerouting"]["sha256"],
        "jre_package_sha256": lock["jre"]["sha256"],
        "digest_is_signature": False,
    }
    path = target / "INSTALL-MANIFEST.json"
    temporary = target / ".INSTALL-MANIFEST.json.tmp"
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, ensure_ascii=False)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def install(root: Path, target: Path, lock_path: Path, lock: dict, lock_sha256: str) -> dict:
    if target.exists():
        raise InstallerError("target이 이미 존재합니다. --verify-only 또는 --adopt-existing을 사용하세요")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        (temporary / "download").mkdir()
        (temporary / "bin").mkdir()
        jar = temporary / "bin" / lock["freerouting"]["asset"]
        deb = temporary / "download" / lock["jre"]["filename"]
        _download(lock["freerouting"]["url"], jar, lock["freerouting"], "Freerouting JAR")
        _download(lock["jre"]["url"], deb, lock["jre"], "JRE Debian package")
        os.chmod(jar, 0o444)
        os.chmod(deb, 0o444)
        _run(["dpkg-deb", "--extract", str(deb), str(temporary / "jre25")])
        relocation = _relocate_debian_jre(temporary, lock)
        _atomic_manifest(temporary, lock_sha256, lock, adopted=False)
        verify_runtime(temporary, lock, lock_sha256, require_manifest=True)
        os.replace(temporary, target)
        parent_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        result = verify_runtime(target, lock, lock_sha256, require_manifest=True)
        result["relocated_symlinks"] = relocation
        return result
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--target")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", action="store_true")
    actions.add_argument("--verify-only", action="store_true")
    actions.add_argument("--adopt-existing", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve()
        lock_path = Path(args.lock).resolve()
        lock = load_lock(lock_path)
        lock_sha256 = sha256_file(lock_path)
        requested = Path(args.target) if args.target else Path(lock["runtime_dir"])
        target = validate_target(root, requested)
        if args.install:
            result = install(root, target, lock_path, lock, lock_sha256)
        elif args.adopt_existing:
            result = verify_runtime(target, lock, lock_sha256, require_manifest=False)
            _atomic_manifest(target, lock_sha256, lock, adopted=True)
            result = verify_runtime(target, lock, lock_sha256, require_manifest=True)
        else:
            result = verify_runtime(target, lock, lock_sha256, require_manifest=True)
        print(json.dumps({"verified": True, **result}, indent=2, ensure_ascii=False))
        return 0
    except (InstallerError, OSError, subprocess.SubprocessError) as error:
        print(f"Freerouting runtime 검증 실패: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
