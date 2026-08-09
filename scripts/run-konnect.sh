#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/upstream/konnect/target/release/konnect"
RUNTIME_HOME="$ROOT/.runtime-home"

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

# Konnect v0.2.2의 최초 실행 installer를 프로젝트 내부에 격리한다.
export HOME="$RUNTIME_HOME"
export XDG_CONFIG_HOME="$RUNTIME_HOME/.config"
export XDG_CACHE_HOME="$RUNTIME_HOME/.cache"
export XDG_DATA_HOME="$RUNTIME_HOME/.local/share"
export XDG_STATE_HOME="$RUNTIME_HOME/.local/state"

# KiCad가 Konnect를 자식 프로세스로 실행하면 KICAD_API_SOCKET이 자동으로
# 전달된다. Codex/Claude가 독립 STDIO 서버로 실행하는 Linux 경로에서는
# 현재 사용자의 활성 KiCad 10 API socket을 안전하게 자동 발견한다.
if [[ -z "${KICAD_API_SOCKET:-}" && -S /tmp/kicad/api.sock ]]; then
  export KICAD_API_SOCKET="ipc:///tmp/kicad/api.sock"
fi

cd "$ROOT"
exec "$BIN" "$@"
