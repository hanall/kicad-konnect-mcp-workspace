#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KONNECT="$ROOT/upstream/konnect"

command -v protoc >/dev/null 2>&1 || {
  printf 'protoc이 없습니다. 먼저 make bootstrap을 실행하세요.\n' >&2
  exit 2
}

if grep -q 'source = "git+' "$KONNECT/Cargo.lock"; then
  printf 'Cargo.lock에서 허용하지 않은 Git dependency를 발견했습니다.\n' >&2
  exit 3
fi

(
  cd "$KONNECT"
  cargo build --release --locked -p konnect
)

BIN="$KONNECT/target/release/konnect"
test -x "$BIN"
printf 'Konnect 빌드 완료: %s\n' "$BIN"
"$BIN" --version
