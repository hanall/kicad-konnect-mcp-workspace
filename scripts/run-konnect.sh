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

exec "$BIN" "$@"
