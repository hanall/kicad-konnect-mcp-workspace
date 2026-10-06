#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KONNECT="$ROOT/upstream/konnect"

command -v protoc >/dev/null 2>&1 || {
  printf 'protoc이 없습니다. 먼저 make bootstrap을 실행하세요.\n' >&2
  exit 2
}

(
  cd "$KONNECT"
  cargo fmt --all -- --check
  cargo test --workspace --locked --lib --tests
  cargo test --workspace --locked --doc
  cargo clippy --workspace --locked --all-targets -- -D warnings
  cargo fmt --manifest-path crates/schematic-viewer/Cargo.toml -- --check
  cargo test --locked --manifest-path crates/schematic-viewer/Cargo.toml
  cargo clippy --locked --manifest-path crates/schematic-viewer/Cargo.toml --all-targets -- -D warnings
)

(
  cd "$ROOT"
  python3 -m unittest discover -s tests -p 'test_*.py' -v
)
printf 'Konnect와 root contract gate 통과\n'
