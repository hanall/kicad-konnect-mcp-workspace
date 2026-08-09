#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

latest_kicad="$({
  git ls-remote --tags --refs https://gitlab.com/kicad/code/kicad.git 'refs/tags/10.*'
} | sed -E 's#^.*refs/tags/##' | grep -E '^10\.0\.[0-9]+$' | sort -V | tail -1)"

latest_konnect="$({
  git ls-remote --tags --refs https://github.com/mixelpixx/Konnect.git 'refs/tags/v*'
} | sed -E 's#^.*refs/tags/##' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)"

pinned_kicad="$(python3 -c 'import json; print(json.load(open("upstreams.lock.json"))["components"]["kicad"]["tag"])')"
pinned_konnect="$(python3 -c 'import json; print(json.load(open("upstreams.lock.json"))["components"]["konnect"]["tag"])')"

printf 'upstream 안정 tag 상태\n'
printf '  KiCad:   pinned=%s latest=%s\n' "$pinned_kicad" "$latest_kicad"
printf '  Konnect: pinned=%s latest=%s\n' "$pinned_konnect" "$latest_konnect"

[[ "$pinned_kicad" == "$latest_kicad" && "$pinned_konnect" == "$latest_konnect" ]]
