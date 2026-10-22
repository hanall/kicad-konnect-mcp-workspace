#!/usr/bin/env bash
set -euo pipefail

# Qucs-S 공식 GitHub release AppImage를 /opt에 고정 설치하거나 재검증한다.
# KiCad installer(scripts/install-kicad-appimage.sh)와 같은 계약을 따른다.
# 잠금 원본: config/qucs-s.lock.json

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="26.1.1"
RELEASE_DATE="2026-04-26"
APPIMAGE="Qucs-S-${VERSION}-linux-x86_64.AppImage"
HASHES_FILE="hashes.sha256"
BASE_URL="https://github.com/ra3xdh/qucs_s/releases/download/${VERSION}"
SOURCE_PAGE="https://ra3xdh.github.io/"
RELEASE_API="https://api.github.com/repos/ra3xdh/qucs_s/releases/tags/${VERSION}"
APPIMAGE_SHA256="a86ab951118bfdffc8acfda8893cde0e2aeedc7129cc73978ae7d16761ec5cb5"
HASHES_SHA256="4bca7925f73bd7926cb6cbc966a77211c84deeb6da19345241f5a8b09f5f934e"
APPROVAL_DATE="2026-10-22"
INSTALL_DIR="/opt/qucs-s/${VERSION}"
INSTALLED_APPIMAGE="${INSTALL_DIR}/${APPIMAGE}"
ARTIFACT_DIR="${QUCS_INSTALL_ARTIFACT_DIR:-${ROOT}/.artifacts/qucs-s-${VERSION}-install}"
DESKTOP_FILE="/usr/local/share/applications/qucs-s.desktop"
ICON_FILE="/usr/local/share/icons/hicolor/scalable/apps/qucs-s.svg"
NGSPICE_PACKAGE_VERSION="44.2+ds-1"
MODE="install"
ENTRYPOINTS=(qucs-s)

usage() {
  cat <<'EOF'
사용법: scripts/install-qucs-s-appimage.sh [--verify-only]

옵션:
  --verify-only  다운로드나 시스템 변경 없이 AppImage, 실행 진입점, 엔진을 검증
  -h, --help     도움말 표시

검증 특성:
  AppImage는 ngspice를 번들하지 않으므로 시스템 ngspice(Debian 공식 패키지)를
  엔진으로 요구한다. GUI 실행 스모크는 X 디스플레이가 필요해 여기서는 하지 않고
  ACUW 레인에서 별도로 수행한다.
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

verify_engine() {
  command -v ngspice >/dev/null 2>&1 || {
    printf 'ngspice 엔진이 없습니다. sudo apt-get install ngspice 로 설치하세요.\n' >&2
    return 1
  }
  local installed
  installed="$(dpkg-query -W -f='${Version}' ngspice 2>/dev/null || true)"
  [[ "$installed" == "$NGSPICE_PACKAGE_VERSION" ]] || {
    printf 'ngspice 패키지 버전 불일치: expected=%s actual=%s\n' \
      "$NGSPICE_PACKAGE_VERSION" "${installed:-none}" >&2
    return 1
  }
}

verify_runtime() {
  local checksums="${INSTALL_DIR}/SHA256SUMS"
  local manifest="${INSTALL_DIR}/INSTALL-MANIFEST.json"
  [[ -x "$INSTALLED_APPIMAGE" ]] || {
    printf 'Qucs-S AppImage가 없습니다: %s\n' "$INSTALLED_APPIMAGE" >&2
    return 1
  }
  for required_file in "$checksums" "$manifest" "$DESKTOP_FILE" "$ICON_FILE"; do
    [[ -r "$required_file" ]] || {
      printf 'Qucs-S 설치 산출물이 없습니다: %s\n' "$required_file" >&2
      return 1
    }
  done

  verify_file "$APPIMAGE_SHA256" "$INSTALLED_APPIMAGE" || return 1
  verify_engine || return 1

  local tool
  for tool in "${ENTRYPOINTS[@]}"; do
    [[ -x "/usr/local/bin/${tool}" ]] || {
      printf '실행 진입점이 없습니다: /usr/local/bin/%s\n' "$tool" >&2
      return 1
    }
  done

  python3 - \
    "$manifest" "$checksums" "$DESKTOP_FILE" "$ICON_FILE" \
    "$VERSION" "$RELEASE_DATE" "$APPIMAGE" "$APPIMAGE_SHA256" "$HASHES_SHA256" \
    "$SOURCE_PAGE" "$BASE_URL" "$RELEASE_API" "$INSTALL_DIR" "$APPROVAL_DATE" \
    "$NGSPICE_PACKAGE_VERSION" <<'PY' || return 1
import json
from pathlib import Path
import stat
import sys

(
    manifest_path,
    checksums_path,
    desktop_path,
    icon_path,
    version,
    release_date,
    appimage,
    appimage_sha256,
    hashes_sha256,
    source_page,
    base_url,
    release_api,
    install_dir,
    approval_date,
    ngspice_version,
) = sys.argv[1:]

entrypoint_names = ("qucs-s",)
entrypoints = [f"/usr/local/bin/{name}" for name in entrypoint_names]

assert Path(checksums_path).read_text(encoding="utf-8") == (
    f"{appimage_sha256}  {appimage}\n"
)

manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
expected = {
    "schema_version": 1,
    "product": "Qucs-S",
    "version": version,
    "architecture": "x86_64",
    "format": "GitHub release AppImage",
    "release_date": release_date,
    "source_page": source_page,
    "source_url": f"{base_url}/{appimage}",
    "release_api": release_api,
    "signature": {
        "algorithm": None,
        "verification": "not_available",
        "note": "upstream은 서명을 제공하지 않는다. SHA256을 GitHub API digest와 hashes.sha256으로 교차 검증했다.",
    },
    "sha256": {"appimage": appimage_sha256, "hashes_file": hashes_sha256},
    "install_root": install_dir,
    "entrypoints": entrypoints,
    "engine": {
        "ngspice": {
            "bundled": False,
            "source": "Debian 13 공식 저장소",
            "package_version": ngspice_version,
        }
    },
    "reason": (
        "Debian 13 공식 저장소에는 qucs-s 패키지가 없다. 개인 OBS 저장소의 영구 "
        "신뢰나 flatpak 런타임 추가 없이 정확한 SHA256으로 고정 설치한다."
    ),
    "alternatives_reviewed": [
        "OBS home:ra3xdh Debian_13 26.1.1-1: 개인 저장소 키를 apt 신뢰 체인에 영구 추가",
        "Flathub io.github.ra3xdh.qucs_s 26.1.1: flatpak 런타임 신규 설치, Unverified",
        "보류: KiCad 10 내장 시뮬레이터만 사용",
    ],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": f"Qucs-S {version} AppImage 시스템 설치",
        "source": "사용자 명시 승인 (그릴링 Q1)",
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
        f'exec "{install_dir}/{appimage}" "$@"\n'
    )
    assert path.read_text(encoding="utf-8") == expected_wrapper
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o755, f"실행 진입점 mode 불일치: {path}={mode:o}"

desktop = Path(desktop_path).read_text(encoding="utf-8").splitlines()
assert "Exec=/usr/local/bin/qucs-s %f" in desktop
assert "TryExec=/usr/local/bin/qucs-s" in desktop
assert "Icon=qucs-s" in desktop
assert Path(icon_path).stat().st_size > 0
PY

  desktop-file-validate "$DESKTOP_FILE" || return 1
  printf 'Qucs-S %s 런타임 검증 통과 (엔진 ngspice %s)\n' "$VERSION" "$NGSPICE_PACKAGE_VERSION"
}

for command_name in sha256sum desktop-file-validate python3 dpkg-query; do
  require_command "$command_name"
done

if [[ "$MODE" == "verify" ]]; then
  verify_runtime
  exit 0
fi

if verify_runtime >/dev/null 2>&1; then
  printf 'Qucs-S %s가 이미 검증된 상태로 설치되어 있습니다.\n' "$VERSION"
  verify_runtime
  exit 0
fi

[[ "$(uname -m)" == "x86_64" ]] || {
  printf '지원하지 않는 아키텍처입니다: %s\n' "$(uname -m)" >&2
  exit 1
}

for command_name in curl install sudo mktemp python3; do
  require_command "$command_name"
done

verify_engine

mkdir -p "$ARTIFACT_DIR"
appimage_path="${ARTIFACT_DIR}/${APPIMAGE}"
hashes_path="${ARTIFACT_DIR}/${HASHES_FILE}"

if [[ ! -f "$appimage_path" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$appimage_path" "${BASE_URL}/${APPIMAGE}"
fi
if [[ ! -f "$hashes_path" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$hashes_path" "${BASE_URL}/${HASHES_FILE}"
fi

verify_file "$APPIMAGE_SHA256" "$appimage_path"
verify_file "$HASHES_SHA256" "$hashes_path"
grep -qE "^${APPIMAGE_SHA256} \*?${APPIMAGE}$" "$hashes_path" || {
  printf 'upstream hashes.sha256의 AppImage 항목이 잠금값과 다릅니다.\n' >&2
  exit 1
}

stage="$(mktemp -d "${ARTIFACT_DIR}/stage.XXXXXX")"
cleanup() {
  [[ -z "${stage:-}" || ! -d "$stage" ]] || rm -rf -- "$stage"
}
trap cleanup EXIT
install -m 0755 "$appimage_path" "${stage}/${APPIMAGE}"
verify_file "$APPIMAGE_SHA256" "${stage}/${APPIMAGE}"

extract_dir="${stage}/desktop"
mkdir -p "$extract_dir"
(
  cd "$extract_dir"
  # 루트의 desktop/icon은 symlink일 수 있으므로 전체를 추출한 뒤 실체를 복사한다.
  "${stage}/${APPIMAGE}" --appimage-extract >/dev/null
)
for asset in qucs-s.desktop qucs-s.svg; do
  src="${extract_dir}/squashfs-root/${asset}"
  [[ -e "$src" ]] || {
    printf 'AppImage 안에 %s가 없습니다.\n' "$asset" >&2
    exit 1
  }
  cp -L "$src" "${extract_dir}/${asset}"
  test -s "${extract_dir}/${asset}"
done
rm -rf -- "${extract_dir}/squashfs-root"

python3 - "${extract_dir}/qucs-s.desktop" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
out = []
for line in lines:
    if line.startswith("Exec="):
        out.append("Exec=/usr/local/bin/qucs-s %f")
        out.append("TryExec=/usr/local/bin/qucs-s")
        continue
    if line.startswith("TryExec="):
        continue
    if line.startswith("Icon="):
        out.append("Icon=qucs-s")
        continue
    out.append(line)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

sudo install -d -m 0755 "$INSTALL_DIR" /usr/local/bin \
  /usr/local/share/applications /usr/local/share/icons/hicolor/scalable/apps
sudo install -m 0755 "${stage}/${APPIMAGE}" "$INSTALLED_APPIMAGE"
sudo install -m 0644 "$hashes_path" "${INSTALL_DIR}/${HASHES_FILE}"

printf '%s  %s\n' "$APPIMAGE_SHA256" "$APPIMAGE" >"${stage}/SHA256SUMS"
sudo install -m 0644 "${stage}/SHA256SUMS" "${INSTALL_DIR}/SHA256SUMS"

for tool in "${ENTRYPOINTS[@]}"; do
  cat >"${stage}/${tool}" <<EOF
#!/bin/sh
set -eu
exec "${INSTALLED_APPIMAGE}" "\$@"
EOF
  sudo install -m 0755 "${stage}/${tool}" "/usr/local/bin/${tool}"
done

sudo install -m 0644 "${extract_dir}/qucs-s.desktop" "$DESKTOP_FILE"
sudo install -m 0644 "${extract_dir}/qucs-s.svg" "$ICON_FILE"
sudo update-desktop-database /usr/local/share/applications

installed_at="$(date --iso-8601=seconds)"
python3 - \
  "$installed_at" "${stage}/INSTALL-MANIFEST.json" \
  "$VERSION" "$RELEASE_DATE" "$APPIMAGE" "$APPIMAGE_SHA256" "$HASHES_SHA256" \
  "$SOURCE_PAGE" "$BASE_URL" "$RELEASE_API" "$INSTALL_DIR" "$APPROVAL_DATE" \
  "$NGSPICE_PACKAGE_VERSION" <<'PY'
import json
import sys

(
    installed_at,
    output_path,
    version,
    release_date,
    appimage,
    appimage_sha256,
    hashes_sha256,
    source_page,
    base_url,
    release_api,
    install_dir,
    approval_date,
    ngspice_version,
) = sys.argv[1:]

manifest = {
    "schema_version": 1,
    "product": "Qucs-S",
    "version": version,
    "architecture": "x86_64",
    "format": "GitHub release AppImage",
    "release_date": release_date,
    "installed_at": installed_at,
    "source_page": source_page,
    "source_url": f"{base_url}/{appimage}",
    "release_api": release_api,
    "signature": {
        "algorithm": None,
        "verification": "not_available",
        "note": "upstream은 서명을 제공하지 않는다. SHA256을 GitHub API digest와 hashes.sha256으로 교차 검증했다.",
    },
    "sha256": {"appimage": appimage_sha256, "hashes_file": hashes_sha256},
    "install_root": install_dir,
    "entrypoints": ["/usr/local/bin/qucs-s"],
    "engine": {
        "ngspice": {
            "bundled": False,
            "source": "Debian 13 공식 저장소",
            "package_version": ngspice_version,
        }
    },
    "reason": (
        "Debian 13 공식 저장소에는 qucs-s 패키지가 없다. 개인 OBS 저장소의 영구 "
        "신뢰나 flatpak 런타임 추가 없이 정확한 SHA256으로 고정 설치한다."
    ),
    "alternatives_reviewed": [
        "OBS home:ra3xdh Debian_13 26.1.1-1: 개인 저장소 키를 apt 신뢰 체인에 영구 추가",
        "Flathub io.github.ra3xdh.qucs_s 26.1.1: flatpak 런타임 신규 설치, Unverified",
        "보류: KiCad 10 내장 시뮬레이터만 사용",
    ],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": f"Qucs-S {version} AppImage 시스템 설치",
        "source": "사용자 명시 승인 (그릴링 Q1)",
    },
}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
sudo install -m 0644 "${stage}/INSTALL-MANIFEST.json" "${INSTALL_DIR}/INSTALL-MANIFEST.json"

verify_runtime
