#!/usr/bin/env bash
set -euo pipefail

# LTspice(ADI 공식 Windows 설치 파일)를 사용자 전용 Wine prefix에 설치하거나 재검증한다.
# 잠금 원본: config/ltspice.lock.json
# 공급망 지침의 직접 URL 설치 예외는 사용자가 2026-10-22에 명시 승인했다.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="24.0.12.0"
MSI="LTspice64.msi"
MSI_URL="https://ltspice.analog.com/download/latest/${MSI}"
MSI_SHA256="62a9f20b630738e6ade20a37551baa91b20760bfb718807d8a2be4caa3421a36"
MSI_LAST_MODIFIED="2024-04-19"
APPROVAL_DATE="2026-10-22"
WINE_PACKAGE_VERSION="10.0~repack-6"
PREFIX="${LTSPICE_WINEPREFIX:-${HOME}/.local/share/wineprefixes/ltspice}"
WRAPPER="${HOME}/.local/bin/ltspice"
ARTIFACT_DIR="${LTSPICE_INSTALL_ARTIFACT_DIR:-${ROOT}/.artifacts/ltspice-${VERSION}-install}"
MANIFEST="${PREFIX}/INSTALL-MANIFEST.json"
EXE_RELATIVE="drive_c/Program Files/ADI/LTspice/LTspice.exe"
MODE="install"

export WINEARCH=win64
export WINEPREFIX="$PREFIX"
# wine-mono/gecko 다운로드 대화상자를 막는다. LTspice는 .NET/HTML 렌더링을 쓰지 않는다.
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
export WINEDEBUG="${WINEDEBUG:--all}"

usage() {
  cat <<'EOF'
사용법: scripts/install-ltspice-wine.sh [--verify-only]

옵션:
  --verify-only  다운로드나 변경 없이 Wine prefix, LTspice 실행 파일, 래퍼를 검증
  -h, --help     도움말 표시

요구:
  Debian wine 패키지(wine, wine64, wine32:i386)가 설치되어 있어야 한다.
  설치 모드는 X 디스플레이(DISPLAY)가 필요하다. ACUW 레인에서 실행한다.
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

verify_wine() {
  local installed
  for pkg in wine wine64; do
    installed="$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || true)"
    [[ "$installed" == "$WINE_PACKAGE_VERSION" ]] || {
      printf 'wine 패키지 버전 불일치: %s expected=%s actual=%s\n' \
        "$pkg" "$WINE_PACKAGE_VERSION" "${installed:-none}" >&2
      return 1
    }
  done
  command -v wine >/dev/null 2>&1 || {
    printf 'wine 실행 파일이 없습니다.\n' >&2
    return 1
  }
}

verify_runtime() {
  local exe="${PREFIX}/${EXE_RELATIVE}"
  verify_wine || return 1
  [[ -d "$PREFIX" ]] || {
    printf 'Wine prefix가 없습니다: %s\n' "$PREFIX" >&2
    return 1
  }
  [[ -f "$exe" ]] || {
    printf 'LTspice 실행 파일이 없습니다: %s\n' "$exe" >&2
    return 1
  }
  [[ -r "$MANIFEST" ]] || {
    printf 'LTspice 설치 매니페스트가 없습니다: %s\n' "$MANIFEST" >&2
    return 1
  }
  [[ -x "$WRAPPER" ]] || {
    printf 'LTspice 래퍼가 없습니다: %s\n' "$WRAPPER" >&2
    return 1
  }

  local wine_runtime_version
  wine_runtime_version="$(wine --version)" || return 1
  python3 - "$MANIFEST" "$WRAPPER" "$exe" "$VERSION" "$MSI" "$MSI_URL" "$MSI_SHA256" \
    "$MSI_LAST_MODIFIED" "$PREFIX" "$APPROVAL_DATE" "$WINE_PACKAGE_VERSION" \
    "$wine_runtime_version" <<'PY' || return 1
import hashlib
import json
from pathlib import Path
import stat
import sys

(
    manifest_path,
    wrapper_path,
    exe_path,
    version,
    msi,
    msi_url,
    msi_sha256,
    msi_last_modified,
    prefix,
    approval_date,
    wine_version,
    wine_runtime_version,
) = sys.argv[1:]

manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
expected = {
    "schema_version": 1,
    "product": "LTspice",
    "vendor": "Analog Devices Inc.",
    "version": version,
    "format": "Windows MSI under Wine",
    "source_url": msi_url,
    "msi": {"name": msi, "sha256": msi_sha256, "http_last_modified": msi_last_modified},
    "wine": {
        "source": "Debian 13 공식 저장소",
        "package_version": wine_version,
        "runtime_version": wine_runtime_version,
        "winearch": "win64",
        "dll_overrides": "mscoree=d;mshtml=d",
    },
    "prefix": prefix,
    "entrypoints": [wrapper_path],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": "wine 전체 apt 설치와 LTspice64.msi 직접 URL 설치",
        "source": "사용자 명시 승인 (그릴링 Q3, Q10)",
        "exception": "공급망 지침 직접 URL 설치 기본 금지에 대한 사용자 승인 예외",
    },
}
for key, value in expected.items():
    assert manifest.get(key) == value, f"manifest 불일치: {key}"
assert isinstance(manifest.get("installed_at"), str) and manifest["installed_at"]

exe_sha256 = hashlib.sha256(Path(exe_path).read_bytes()).hexdigest()
assert manifest.get("exe_sha256") == exe_sha256, "LTspice.exe SHA256이 매니페스트와 다름"

expected_wrapper = (
    "#!/bin/sh\n"
    "set -eu\n"
    f'export WINEPREFIX="{prefix}"\n'
    "export WINEARCH=win64\n"
    'export WINEDLLOVERRIDES="mscoree=d;mshtml=d"\n'
    'export WINEDEBUG="${WINEDEBUG:--all}"\n'
    'exec wine "C:\\\\Program Files\\\\ADI\\\\LTspice\\\\LTspice.exe" "$@"\n'
)
assert Path(wrapper_path).read_text(encoding="utf-8") == expected_wrapper, "래퍼 내용 불일치"
mode = stat.S_IMODE(Path(wrapper_path).stat().st_mode)
assert mode == 0o755, f"래퍼 mode 불일치: {mode:o}"
PY
  printf 'LTspice %s (Wine %s) 런타임 검증 통과\n' "$VERSION" "$WINE_PACKAGE_VERSION"
}

for command_name in sha256sum python3 dpkg-query; do
  require_command "$command_name"
done

if [[ "$MODE" == "verify" ]]; then
  verify_runtime
  exit 0
fi

if verify_runtime >/dev/null 2>&1; then
  printf 'LTspice %s가 이미 검증된 상태로 설치되어 있습니다.\n' "$VERSION"
  verify_runtime
  exit 0
fi

for command_name in curl wine wineboot wineserver mkdir; do
  require_command "$command_name"
done
verify_wine
[[ -n "${DISPLAY:-}" ]] || {
  printf 'DISPLAY가 없습니다. ACUW 레인(run-in-workspace.sh)에서 실행하세요.\n' >&2
  exit 2
}

mkdir -p "$ARTIFACT_DIR"
msi_path="${ARTIFACT_DIR}/${MSI}"
if [[ ! -f "$msi_path" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 \
    --output "$msi_path" "$MSI_URL"
fi
verify_file "$MSI_SHA256" "$msi_path" || {
  printf 'latest URL의 MSI가 잠금 SHA256과 다릅니다. config/ltspice.lock.json을 갱신하기 전에는 설치하지 않습니다.\n' >&2
  exit 1
}

mkdir -p "$(dirname "$PREFIX")" "$(dirname "$WRAPPER")"
if [[ ! -d "$PREFIX" ]]; then
  wineboot --init
  wineserver --wait
fi

# Advanced Installer 기반 MSI. 조용한 설치(/qn)로 전체 사용자 대상 설치를 시도한다.
wine msiexec /i "$(winepath -w "$msi_path")" /qn ALLUSERS=1
wineserver --wait

exe="${PREFIX}/${EXE_RELATIVE}"
[[ -f "$exe" ]] || {
  printf 'LTspice.exe가 예상 경로에 없습니다: %s\n' "$exe" >&2
  find "$PREFIX/drive_c" -iname 'LTspice*.exe' -print >&2 || true
  exit 1
}

cat >"$WRAPPER" <<EOF
#!/bin/sh
set -eu
export WINEPREFIX="${PREFIX}"
export WINEARCH=win64
export WINEDLLOVERRIDES="mscoree=d;mshtml=d"
export WINEDEBUG="\${WINEDEBUG:--all}"
exec wine "C:\\\\Program Files\\\\ADI\\\\LTspice\\\\LTspice.exe" "\$@"
EOF
chmod 0755 "$WRAPPER"

installed_at="$(date --iso-8601=seconds)"
exe_sha256="$(sha256sum "$exe" | cut -d' ' -f1)"
wine_runtime_version="$(wine --version)"
python3 - "$MANIFEST" "$installed_at" "$exe_sha256" "$wine_runtime_version" \
  "$VERSION" "$MSI" "$MSI_URL" "$MSI_SHA256" "$MSI_LAST_MODIFIED" "$PREFIX" \
  "$WRAPPER" "$APPROVAL_DATE" "$WINE_PACKAGE_VERSION" <<'PY'
import json
import sys

(
    manifest_path,
    installed_at,
    exe_sha256,
    wine_runtime_version,
    version,
    msi,
    msi_url,
    msi_sha256,
    msi_last_modified,
    prefix,
    wrapper,
    approval_date,
    wine_version,
) = sys.argv[1:]

manifest = {
    "schema_version": 1,
    "product": "LTspice",
    "vendor": "Analog Devices Inc.",
    "version": version,
    "format": "Windows MSI under Wine",
    "installed_at": installed_at,
    "source_url": msi_url,
    "msi": {"name": msi, "sha256": msi_sha256, "http_last_modified": msi_last_modified},
    "exe_sha256": exe_sha256,
    "wine": {
        "source": "Debian 13 공식 저장소",
        "package_version": wine_version,
        "runtime_version": wine_runtime_version,
        "winearch": "win64",
        "dll_overrides": "mscoree=d;mshtml=d",
    },
    "prefix": prefix,
    "entrypoints": [wrapper],
    "approval": {
        "status": "approved",
        "approved_at": approval_date,
        "scope": "wine 전체 apt 설치와 LTspice64.msi 직접 URL 설치",
        "source": "사용자 명시 승인 (그릴링 Q3, Q10)",
        "exception": "공급망 지침 직접 URL 설치 기본 금지에 대한 사용자 승인 예외",
    },
}
with open(manifest_path, "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

verify_runtime
