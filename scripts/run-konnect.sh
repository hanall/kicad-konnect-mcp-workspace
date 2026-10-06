#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/upstream/konnect/target/release/konnect"
RUNTIME_HOME="$(python3 - "$ROOT" "${KONNECT_RUNTIME_HOME:-.runtime-home}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
requested = Path(sys.argv[2])
target = (requested if requested.is_absolute() else root / requested).resolve()
default = root / ".runtime-home"
artifacts = root / ".artifacts"
if target != default and (target == artifacts or not target.is_relative_to(artifacts)):
    raise SystemExit("KONNECT_RUNTIME_HOME은 프로젝트 .runtime-home 또는 .artifacts 하위 전용 디렉터리여야 합니다.")
if target.exists() and not target.is_dir():
    raise SystemExit("KONNECT_RUNTIME_HOME이 디렉터리가 아닙니다.")
print(target)
PY
)"

if [[ ! -x "$BIN" ]]; then
  printf 'Konnect binary가 없습니다. 먼저 make build를 실행하세요: %s\n' "$BIN" >&2
  exit 127
fi

umask 077
mkdir -p "$RUNTIME_HOME" \
  "$RUNTIME_HOME/.config" \
  "$RUNTIME_HOME/.cache" \
  "$RUNTIME_HOME/.local/share" \
  "$RUNTIME_HOME/.local/state"
chmod 700 "$RUNTIME_HOME"

# 구버전 installer와 최신판의 명시적 init 모두 프로젝트 내부에 격리한다.
export HOME="$RUNTIME_HOME"
export XDG_CONFIG_HOME="$RUNTIME_HOME/.config"
export XDG_CACHE_HOME="$RUNTIME_HOME/.cache"
export XDG_DATA_HOME="$RUNTIME_HOME/.local/share"
export XDG_STATE_HOME="$RUNTIME_HOME/.local/state"

# AppImage의 GUI mount 수명과 무관한, 검증된 설치본의 라이브러리 경로.
# 호출자가 명시한 경로는 덮어쓰지 않는다.
KICAD_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["components"]["kicad"]["tag"])' "$ROOT/upstreams.lock.json")"
KICAD_SHARE="/opt/kicad/${KICAD_VERSION}/share/kicad"
if [[ -d "$KICAD_SHARE/symbols" && -d "$KICAD_SHARE/footprints" ]]; then
  export KICAD10_SYMBOL_DIR="${KICAD10_SYMBOL_DIR:-$KICAD_SHARE/symbols}"
  export KICAD10_FOOTPRINT_DIR="${KICAD10_FOOTPRINT_DIR:-$KICAD_SHARE/footprints}"
  export KICAD10_3DMODEL_DIR="${KICAD10_3DMODEL_DIR:-$KICAD_SHARE/3dmodels}"
fi

# KiCad가 Konnect를 자식 프로세스로 실행하면 KICAD_API_SOCKET이 자동으로
# 전달된다. Codex/Claude가 독립 STDIO 서버로 실행하는 Linux 경로에서는
# 현재 사용자의 활성 KiCad 10 API socket을 안전하게 자동 발견한다.
if [[ -z "${KICAD_API_SOCKET:-}" && -S /tmp/kicad/api.sock ]]; then
  export KICAD_API_SOCKET="ipc:///tmp/kicad/api.sock"
fi

cd "$ROOT"
exec "$BIN" "$@"
