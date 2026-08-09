#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPECTED_PROTOBUF='3.21.12-11+deb13u1'
EXPECTED_RUST='1.96.0'

sudo_run() {
  if sudo -n true 2>/dev/null; then
    sudo -n "$@"
  elif [[ -n "${SUDO_PASSWORD:-}" ]]; then
    printf '%s\n' "$SUDO_PASSWORD" | sudo -S -p '' "$@"
  else
    sudo "$@"
  fi
}

if [[ -x /home/hanol/.local/bin/audit_python_pth.sh ]]; then
  /home/hanol/.local/bin/audit_python_pth.sh
fi

candidate="$(apt-cache policy protobuf-compiler | awk '/후보:|Candidate:/ {print $2; exit}')"
if [[ "$candidate" != "$EXPECTED_PROTOBUF" ]]; then
  printf 'protobuf-compiler 후보가 검증값과 다릅니다: expected=%s actual=%s\n' \
    "$EXPECTED_PROTOBUF" "${candidate:-없음}" >&2
  exit 2
fi

if ! dpkg-query -W -f='${Version}' protobuf-compiler 2>/dev/null | grep -Fxq "$EXPECTED_PROTOBUF"; then
  sudo_run apt-get update
  sudo_run apt-get install -y "protobuf-compiler=$EXPECTED_PROTOBUF"
fi

if ! command -v rustup >/dev/null 2>&1; then
  printf '공식 rustup이 없습니다. 임의 installer를 실행하지 않고 중단합니다.\n' >&2
  exit 3
fi

rustup toolchain install "$EXPECTED_RUST" --profile minimal --component clippy,rustfmt

actual_protoc="$(protoc --version)"
actual_rust="$(rustc "+$EXPECTED_RUST" --version)"
printf '빌드 도구 준비 완료\n'
printf '  protoc: %s\n' "$actual_protoc"
printf '  rustc:  %s\n' "$actual_rust"
printf '  cmake:  %s\n' "$(cmake --version | head -1)"

python3 "$ROOT/scripts/verify-project.py"
