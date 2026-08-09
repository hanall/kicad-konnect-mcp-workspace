#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="10.0.5"
RELEASE_DATE="2026-07-22"
APPIMAGE="kicad-${VERSION}-x86_64.AppImage"
ARCHIVE="${APPIMAGE}.tar"
BASE_URL="https://mirror.tuna.tsinghua.edu.cn/kicad/appimage/stable"
SOURCE_PAGE="https://www.kicad.org/download/linux/"
ARCHIVE_SHA256="af65bb1fd5ee2730df860bc2a8c49f507a64c83c15c2ce13927eec74d38eba8f"
APPIMAGE_SHA256="966a01c0c81473b870c0136a5c2a7c42dc7e7e4fa52a7b95b802b7b5db8d9727"
MINISIGN_PUBLIC_KEY_ID="40D6F856001D8BB2"
MINISIGN_PUBLIC_KEY="RWSyix0AVvjWQGZChX64ywBpE5XqV1Eg+ZXYHR3Y27md9EoZ0AtVr9i9"
APPROVAL_DATE="2026-08-10"
INSTALL_DIR="/opt/kicad/${VERSION}"
INSTALLED_APPIMAGE="${INSTALL_DIR}/${APPIMAGE}"
ARTIFACT_DIR="${KICAD_INSTALL_ARTIFACT_DIR:-${ROOT}/.artifacts/kicad-${VERSION}-install}"
MODE="install"
ENTRYPOINTS=(kicad kicad-cli pcbnew eeschema gerbview bitmap2component pcb_calculator pl_editor)

usage() {
  cat <<'EOF'
사용법: scripts/install-kicad-appimage.sh [--verify-only]

옵션:
  --verify-only  다운로드나 시스템 변경 없이 현재 설치의 해시, 서명, 실행 진입점을 검증
  -h, --help     도움말 표시
EOF
}

while (($#)); do
  case "$1" in
    --verify-only) MODE="verify" ;;
    -h|--help) usage; exit 0 ;;
    *) printf '알 수 없는 옵션: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '필수 명령이 없습니다: %s\n' "$1" >&2
    exit 127
  }
}

verify_file() {
  local expected="$1" path="$2"
  printf '%s  %s\n' "$expected" "$path" | sha256sum -c -
}

verify_runtime() {
  local signature="${INSTALL_DIR}/${APPIMAGE}.minisig"
  local public_key="${INSTALL_DIR}/minisign.pub"
  local checksums="${INSTALL_DIR}/SHA256SUMS"
  local manifest="${INSTALL_DIR}/INSTALL-MANIFEST.json"
  local desktop="/usr/local/share/applications/org.kicad.kicad.desktop"
  local icon="/usr/local/share/icons/hicolor/128x128/apps/kicad.png"
  [[ -x "$INSTALLED_APPIMAGE" ]] || {
    printf 'KiCad AppImage가 없습니다: %s\n' "$INSTALLED_APPIMAGE" >&2
    return 1
  }
  [[ -r "$signature" ]] || {
    printf 'KiCad minisign 서명이 없습니다: %s\n' "$signature" >&2
    return 1
  }
  for required_file in "$public_key" "$checksums" "$manifest" "$desktop" "$icon"; do
    [[ -r "$required_file" ]] || {
      printf 'KiCad 설치 산출물이 없습니다: %s\n' "$required_file" >&2
      return 1
    }
  done

  verify_file "$APPIMAGE_SHA256" "$INSTALLED_APPIMAGE" || return 1
  minisign -Vm "$INSTALLED_APPIMAGE" -x "$signature" -p "$public_key" || return 1

  local tool
  for tool in "${ENTRYPOINTS[@]}"; do
    [[ -x "/usr/local/bin/${tool}" ]] || {
      printf '실행 진입점이 없습니다: /usr/local/bin/%s\n' "$tool" >&2
      return 1
    }
  done

  local actual_version
  actual_version="$(kicad-cli --version | head -n 1)" || return 1
  [[ "$actual_version" == "$VERSION" ]] || {
    printf 'KiCad CLI 버전 불일치: expected=%s actual=%s\n' "$VERSION" "$actual_version" >&2
    return 1
  }

  python3 - \
    "$manifest" "$public_key" "$checksums" "$desktop" "$icon" \
    "$VERSION" "$RELEASE_DATE" "$APPIMAGE" "$ARCHIVE_SHA256" "$APPIMAGE_SHA256" \
    "$MINISIGN_PUBLIC_KEY_ID" "$MINISIGN_PUBLIC_KEY" "$SOURCE_PAGE" "$BASE_URL" \
    "$INSTALL_DIR" "$APPROVAL_DATE" <<'PY' || return 1
import json
from pathlib import Path
import stat
import sys

(
    manifest_path,
    public_key_path,
    checksums_path,
    desktop_path,
    icon_path,
    version,
    release_date,
    appimage,
    archive_sha256,
    appimage_sha256,
    public_key_id,
    public_key,
    source_page,
    base_url,
    install_dir,
    approval_date,
) = sys.argv[1:]

entrypoint_names = (
    "kicad",
    "kicad-cli",
    "pcbnew",
    "eeschema",
    "gerbview",
    "bitmap2component",
    "pcb_calculator",
    "pl_editor",
)
entrypoints = [f"/usr/local/bin/{name}" for name in entrypoint_names]

expected_key = (
    f"untrusted comment: minisign public key {public_key_id}\n"
    f"{public_key}\n"
)
assert Path(public_key_path).read_text(encoding="utf-8") == expected_key
assert Path(checksums_path).read_text(encoding="utf-8") == (
    f"{appimage_sha256}  {appimage}\n"
)

manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
expected = {
    "schema_version": 1,
    "product": "KiCad",
    "version": version,
    "variant": "full-with-3d-packages",
    "architecture": "x86_64",
    "format": "official AppImage",
    "release_date": release_date,
    "source_page": source_page,
    "source_url": f"{base_url}/{appimage}.tar",
    "signature_url": f"{base_url}/{appimage}.minisig",
    "signature": {
        "algorithm": "minisign",
        "public_key_id": public_key_id,
        "public_key": public_key,
        "verification": "passed",
        "trusted_comment": f"KiCad-{version}-x86_64.AppImage",
    },
    "sha256": {"tar": archive_sha256, "appimage": appimage_sha256},
    "install_root": install_dir,
    "entrypoints": entrypoints,
    "reason": (
        "Debian 13 기본 APT의 KiCad 9.0.2 대신 Konnect v0.2.2 IPC 계약과 "
        f"일치하는 KiCad {version}가 필요함"
    ),
    "alternatives_reviewed": [
        "Debian 13 APT 9.0.2: Konnect의 KiCad 10 요구사항 불충족",
        "Flatpak: host kicad-cli와 IPC socket 연동이 간접적",
        "source build: 공식 AppImage보다 설치 재현성과 공급망 검증 비용이 큼",
    ],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": f"KiCad {version} 시스템 설치",
        "source": "사용자 명시 승인",
    },
}
for key, value in expected.items():
    assert manifest.get(key) == value, f"manifest 불일치: {key}"
assert isinstance(manifest.get("installed_at"), str) and manifest["installed_at"]

for name, path_string in zip(entrypoint_names, entrypoints, strict=True):
    path = Path(path_string)
    expected_wrapper = (
        "#!/bin/sh\n"
        "set -eu\n"
        f'exec "{install_dir}/{appimage}" "{name}" "$@"\n'
    )
    assert path.read_text(encoding="utf-8") == expected_wrapper
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o755, f"실행 진입점 mode 불일치: {path}={mode:o}"

desktop = Path(desktop_path).read_text(encoding="utf-8").splitlines()
assert "Exec=/usr/local/bin/kicad %f" in desktop
assert "TryExec=/usr/local/bin/kicad" in desktop
assert Path(icon_path).stat().st_size > 0
PY

  desktop-file-validate "$desktop" || return 1
  printf 'KiCad %s 런타임 검증 통과\n' "$VERSION"
}

for command_name in sha256sum minisign desktop-file-validate python3; do
  require_command "$command_name"
done

if [[ "$MODE" == "verify" ]]; then
  verify_runtime
  exit 0
fi

if verify_runtime >/dev/null 2>&1; then
  printf 'KiCad %s가 이미 검증된 상태로 설치되어 있습니다.\n' "$VERSION"
  verify_runtime
  exit 0
fi

[[ "$(uname -m)" == "x86_64" ]] || {
  printf '지원하지 않는 아키텍처입니다: %s\n' "$(uname -m)" >&2
  exit 1
}

for command_name in curl tar install sudo mktemp python3; do
  require_command "$command_name"
done

mkdir -p "$ARTIFACT_DIR"
archive_path="${ARTIFACT_DIR}/${ARCHIVE}"
signature_path="${ARTIFACT_DIR}/${APPIMAGE}.minisig"

if [[ ! -f "$archive_path" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$archive_path" "${BASE_URL}/${ARCHIVE}"
fi
if [[ ! -f "$signature_path" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$signature_path" "${BASE_URL}/${APPIMAGE}.minisig"
fi

verify_file "$ARCHIVE_SHA256" "$archive_path"
[[ "$(tar -tf "$archive_path")" == "$APPIMAGE" ]] || {
  printf 'AppImage archive 멤버 계약이 예상과 다릅니다.\n' >&2
  exit 1
}

stage="$(mktemp -d "${ARTIFACT_DIR}/stage.XXXXXX")"
cleanup() {
  [[ -z "${stage:-}" || ! -d "$stage" ]] || rm -rf -- "$stage"
}
trap cleanup EXIT
tar --extract --file "$archive_path" --directory "$stage" --no-same-owner --no-same-permissions
chmod 0755 "${stage}/${APPIMAGE}"
verify_file "$APPIMAGE_SHA256" "${stage}/${APPIMAGE}"
minisign -Vm "${stage}/${APPIMAGE}" -x "$signature_path" -P "$MINISIGN_PUBLIC_KEY"

sudo install -d -m 0755 "$INSTALL_DIR" /usr/local/bin \
  /usr/local/share/applications /usr/local/share/icons/hicolor/128x128/apps
sudo install -m 0755 "${stage}/${APPIMAGE}" "$INSTALLED_APPIMAGE"
sudo install -m 0644 "$signature_path" "${INSTALL_DIR}/${APPIMAGE}.minisig"

printf 'untrusted comment: minisign public key %s\n%s\n' \
  "$MINISIGN_PUBLIC_KEY_ID" "$MINISIGN_PUBLIC_KEY" \
  >"${stage}/minisign.pub"
printf '%s  %s\n' "$APPIMAGE_SHA256" "$APPIMAGE" >"${stage}/SHA256SUMS"
sudo install -m 0644 "${stage}/minisign.pub" "${INSTALL_DIR}/minisign.pub"
sudo install -m 0644 "${stage}/SHA256SUMS" "${INSTALL_DIR}/SHA256SUMS"

for tool in "${ENTRYPOINTS[@]}"; do
  cat >"${stage}/${tool}" <<EOF
#!/bin/sh
set -eu
exec "${INSTALLED_APPIMAGE}" "${tool}" "\$@"
EOF
  sudo install -m 0755 "${stage}/${tool}" "/usr/local/bin/${tool}"
done

extract_dir="${stage}/desktop"
mkdir -p "$extract_dir"
(
  cd "$extract_dir"
  "${stage}/${APPIMAGE}" --appimage-extract 'org.kicad.kicad.desktop' >/dev/null
  "${stage}/${APPIMAGE}" --appimage-extract 'kicad.png' >/dev/null
)
python3 - "${extract_dir}/AppDir/org.kicad.kicad.desktop" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    if line.startswith("Exec="):
        out.append("Exec=/usr/local/bin/kicad %f")
        out.append("TryExec=/usr/local/bin/kicad")
        continue
    elif line.startswith("TryExec="):
        continue
    out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
sudo install -m 0644 "${extract_dir}/AppDir/org.kicad.kicad.desktop" \
  /usr/local/share/applications/org.kicad.kicad.desktop
sudo install -m 0644 "${extract_dir}/AppDir/kicad.png" \
  /usr/local/share/icons/hicolor/128x128/apps/kicad.png
sudo update-desktop-database /usr/local/share/applications

installed_at="$(date --iso-8601=seconds)"
python3 - \
  "$installed_at" "${stage}/INSTALL-MANIFEST.json" \
  "$VERSION" "$RELEASE_DATE" "$APPIMAGE" "$ARCHIVE_SHA256" "$APPIMAGE_SHA256" \
  "$MINISIGN_PUBLIC_KEY_ID" "$MINISIGN_PUBLIC_KEY" "$SOURCE_PAGE" "$BASE_URL" \
  "$INSTALL_DIR" "$APPROVAL_DATE" <<'PY'
import json
import sys

(
    installed_at,
    output_path,
    version,
    release_date,
    appimage,
    archive_sha256,
    appimage_sha256,
    public_key_id,
    public_key,
    source_page,
    base_url,
    install_dir,
    approval_date,
) = sys.argv[1:]

entrypoints = [
    f"/usr/local/bin/{name}"
    for name in (
        "kicad",
        "kicad-cli",
        "pcbnew",
        "eeschema",
        "gerbview",
        "bitmap2component",
        "pcb_calculator",
        "pl_editor",
    )
]

manifest = {
    "schema_version": 1,
    "product": "KiCad",
    "version": version,
    "variant": "full-with-3d-packages",
    "architecture": "x86_64",
    "format": "official AppImage",
    "release_date": release_date,
    "installed_at": installed_at,
    "source_page": source_page,
    "source_url": f"{base_url}/{appimage}.tar",
    "signature_url": f"{base_url}/{appimage}.minisig",
    "signature": {
        "algorithm": "minisign",
        "public_key_id": public_key_id,
        "public_key": public_key,
        "verification": "passed",
        "trusted_comment": f"KiCad-{version}-x86_64.AppImage",
    },
    "sha256": {
        "tar": archive_sha256,
        "appimage": appimage_sha256,
    },
    "install_root": install_dir,
    "entrypoints": entrypoints,
    "reason": (
        "Debian 13 기본 APT의 KiCad 9.0.2 대신 Konnect v0.2.2 IPC 계약과 "
        f"일치하는 KiCad {version}가 필요함"
    ),
    "alternatives_reviewed": [
        "Debian 13 APT 9.0.2: Konnect의 KiCad 10 요구사항 불충족",
        "Flatpak: host kicad-cli와 IPC socket 연동이 간접적",
        "source build: 공식 AppImage보다 설치 재현성과 공급망 검증 비용이 큼",
    ],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": f"KiCad {version} 시스템 설치",
        "source": "사용자 명시 승인",
    },
}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
sudo install -m 0644 "${stage}/INSTALL-MANIFEST.json" "${INSTALL_DIR}/INSTALL-MANIFEST.json"

verify_runtime
