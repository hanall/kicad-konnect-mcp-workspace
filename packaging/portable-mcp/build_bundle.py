#!/usr/bin/env python3
"""지정한 검증 산출물만 복사해 이식용 ZIP을 구성한다. 원본 소스는 쓰지 않는다."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib
import zipfile

COMMIT = "94f80350cf67db27b179a06a8f6dbebfe4717927"
VERSION = "0.13.0+hanall.1"
FIXED_TIME = (2026, 10, 12, 0, 0, 0)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    own = Path(__file__).resolve().parent
    evidence = args.evidence.resolve()
    output = args.output.resolve()
    assert not output.exists(), "기존 ZIP을 덮지 않습니다"
    upstream = root / "upstream/konnect"
    git = lambda *a: subprocess.check_output(["git", "-C", str(upstream), *a], text=True).strip()
    assert git("rev-parse", "HEAD") == COMMIT
    assert not git("status", "--porcelain"), "소스 worktree가 깨끗하지 않습니다"
    stage = evidence / "final-stage/Konnect-MCP-Portable"
    stage.mkdir(parents=True, exist_ok=False)

    def put(source, name):
        assert source.is_file() and not source.is_symlink(), source
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)

    for name in ("README.md", "README-WINDOWS.md", "Setup-Windows.ps1"):
        put(own / name, name)
    for folder in ("config", "client-config-examples"):
        for source in sorted((own / folder).iterdir()):
            assert source.is_file()
            if source.suffix == ".toml":
                tomllib.loads(source.read_text())
            elif source.suffix == ".json":
                json.loads(source.read_text())
            put(source, folder + "/" + source.name)
    (stage / "config/generated").mkdir()
    for name in ("Start-Konnect", "Start-Konnect.exe"):
        put(evidence / name, name)
    for source, name in (
        ("konnect-windows-distribution.exe", "bin/windows-x86_64/konnect.exe"),
        ("konnect-linux-distribution", "bin/linux-x86_64/konnect"),
    ):
        put(evidence / "build-dev" / source, name)
    for name in ("LICENSE", "THIRD_PARTY.md", "COMMERCIAL.md"):
        put(upstream / name, "licenses/" + name)
    license_stage = evidence / "license-stage"
    assert (license_stage / "INVENTORY.json").is_file(), "의존성 고지 수집이 아직 없습니다"
    for source in sorted(license_stage.rglob("*")):
        if source.is_file():
            put(source, "licenses/dependencies/" + source.relative_to(license_stage).as_posix())
    runtime_stage = evidence / "runtime-license-stage"
    assert (runtime_stage / "INVENTORY.json").is_file(), "런타임 고지 수집이 아직 없습니다"
    for source in sorted(runtime_stage.rglob("*")):
        if source.is_file():
            put(source, "licenses/runtimes/" + source.relative_to(runtime_stage).as_posix())
    source_notices = evidence / "source-license-stage"
    assert (source_notices / "INVENTORY.json").is_file(), "소스 고지 수집이 아직 없습니다"
    for source in sorted(source_notices.rglob("*")):
        if source.is_file():
            put(source, "licenses/source-assets/" + source.relative_to(source_notices).as_posix())
    skill = root / "skills/kicad-schematic-quality"
    skill_files = sorted(p for p in skill.rglob("*") if p.is_file())
    assert len(skill_files) == 17, "검증했던 품질 패키지 파일 수가 바뀌었습니다"
    for source in skill_files:
        put(source, "skills-reference/kicad-schematic-quality/" + source.relative_to(skill).as_posix())
    put(own / "launcher.rs", "source/launcher.rs")
    put(own / "BUILD-SOURCE.md", "source/BUILD-SOURCE.md")
    for source in sorted((own / "build-support").iterdir()):
        put(source, "source/build-support/" + source.name)
    source_zip = stage / "source/exact-konnect.zip"
    subprocess.run(["git", "-C", str(upstream), "archive", "--format=zip",
                    "--prefix=konnect/", "-o", str(source_zip), COMMIT], check=True)
    with zipfile.ZipFile(source_zip) as archive:
        source_names = [i.filename for i in archive.infolist() if not i.is_dir()]
        assert len(source_names) == 459
        for member in archive.infolist():
            assert not stat.S_ISLNK(member.external_attr >> 16), member.filename
        assert archive.read("konnect/Cargo.lock") == (upstream / "Cargo.lock").read_bytes()

    win = json.loads((evidence / "build-dev/windows-distribution-validation.json").read_text())
    lin = json.loads((evidence / "build-dev/linux-distribution-validation.json").read_text())
    smoke = json.loads((evidence / "native-smoke/result.json").read_text())
    assert smoke["status"] == "PASS"
    assert win["distribution"]["sha256"] == digest(stage / "bin/windows-x86_64/konnect.exe")
    assert lin["sha256"] == smoke["server_sha256"] == digest(stage / "bin/linux-x86_64/konnect")
    build_info = {
        "schema_version": 1, "konnect": {"version": VERSION, "commit": COMMIT},
        "source": {"archive": "source/exact-konnect.zip", "sha256": digest(source_zip),
                   "regular_files": len(source_names), "cargo_lock_sha256": digest(upstream / "Cargo.lock"),
                   "dependency_vendor_included": False, "runtime_private_config_included": False},
        "windows_x86_64": {
            "sha256": win["distribution"]["sha256"], "bytes": win["distribution"]["size"],
            "format": win["distribution"]["format"], "target": "x86_64-pc-windows-gnu",
            "dll_imports": win["distribution"]["imports"], "authenticode": False,
            "cross_build_rc": win["recipe"]["return_code"], "native_test": "미실행",
            "powershell_parser_and_execution": "미실행; 정적·모의 검사만 수행",
            "strip_text_unchanged": win["code_identity"]["byte_identical"]},
        "linux_x86_64": {
            "sha256": lin["sha256"], "bytes": lin["size"], "target": "x86_64-unknown-linux-gnu",
            "glibc_minimum_from_symbols": lin["glibc_max"], "elf_needed": lin["needed"],
            "native_mcp": smoke, "strip_text_unchanged": lin["text_unchanged"]},
        "build": {"rust": "1.96.0", "source_changes": 0, "dependency_changes": 0,
                  "windows_c_compiler": "Clang 14 + MinGW-w64 GCC 14 toolchain",
                  "source_build_instructions": "source/BUILD-SOURCE.md",
                  "path_remap": "사용자 홈을 /build/user로 치환한 뒤 debug section 제거",
                  "warnings": "CMake 주입 -w 제거, -Wno-error* 거부; source/dependency patch 없음"},
        "not_validated": ["Windows 실기기", "PowerShell 파서 및 실행", "macOS 빌드·실행",
                          "ARM64", "GUI/PCB IPC", "실제 CAD 편집·ERC/DRC", "제조·통전·안전"],
        "skills": {"mode": "참고 사본만; 자동 설치 없음", "files": 17,
                   "windows_python_helpers": "미지원·미검증"},
    }
    json_write(stage / "BUILD-INFO.json", build_info)
    files = []
    for path in sorted(stage.rglob("*")):
        assert not path.is_symlink(), path
        if not path.is_file():
            continue
        name = path.relative_to(stage).as_posix()
        assert ".." not in Path(name).parts and not name.startswith("/")
        assert not re.search(r"[<>:\\\"|?*]", name)
        assert b"/home/hanol" not in path.read_bytes(), name
        files.append({"path": name, "size": path.stat().st_size, "sha256": digest(path)})
    assert len({f["path"].casefold() for f in files}) == len(files)
    json_write(stage / "MANIFEST.json", {"schema_version": 1,
               "konnect": {"version": VERSION, "commit": COMMIT}, "files": files})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*")):
            relative = stage.name + "/" + path.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(relative + ("/" if path.is_dir() else ""), FIXED_TIME)
            mode = (stat.S_IFDIR | 0o755) if path.is_dir() else (stat.S_IFREG | (0o755 if path.name in ("Start-Konnect", "konnect") else 0o644))
            info.create_system = 3
            info.external_attr = mode << 16
            if path.is_dir():
                info.external_attr |= 0x10
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, b"" if path.is_dir() else path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert stage.name + "/config/generated/" in archive.namelist()
        for item in files:
            raw = archive.read(stage.name + "/" + item["path"])
            assert len(raw) == item["size"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
    external_hash = output.with_suffix(output.suffix + ".sha256")
    assert not external_hash.exists()
    external_hash.write_text(digest(output) + "  " + output.name + "\n", encoding="ascii")
    result = {"archive": str(output), "sha256": digest(output), "bytes": output.stat().st_size,
              "manifest_files": len(files), "source_files": len(source_names), "roundtrip": "PASS"}
    json_write(evidence / "bundle-result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
