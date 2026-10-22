#!/usr/bin/env bash
# 2026-10-22 시뮬레이터 검증 증거 폴더를 갱신하고 SHA256SUMS.txt(자기 제외)를 다시 만든다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E="$ROOT/docs/검증/20261022-172859-circuit-simulators"
V="$ROOT/projects/sim-validation-20261022"
mkdir -p "$E/install-manifests" "$E/regression" "$E/screenshots" "$E/kicad-netlists"
cp -f "$V"/results/*.json "$E/regression/" 2>/dev/null || true
cp -f "$V/spec/spec.json" "$E/regression/spec.json"
for d in "$V"/kicad/*/; do
  id="$(basename "$d")"
  [[ -f "$d/$id.kicad.cir" ]] && cp -f "$d/$id.kicad.cir" "$E/kicad-netlists/$id.kicad.cir"
  [[ -f "$d/$id.erc.json" ]] && cp -f "$d/$id.erc.json" "$E/kicad-netlists/$id.erc.json"
done
for f in "$V"/qucs-s/00-first-run-set-simulator.png "$V"/qucs-s/00-simulators-settings.png "$V"/qucs-s/*/*-gui-result.png; do
  [[ -f "$f" ]] && cp -f "$f" "$E/screenshots/qucs-s-$(basename "$f")"
done
for f in "$V"/kicad-gui/*.png; do
  [[ -f "$f" ]] && cp -f "$f" "$E/screenshots/kicad-gui-$(basename "$f")"
done
( cd "$E" && find . -type f ! -name SHA256SUMS.txt | LC_ALL=C sort | xargs sha256sum > SHA256SUMS.txt )
( cd "$E" && sha256sum -c SHA256SUMS.txt --quiet && echo "증거 SHA 전수 일치: $(wc -l < SHA256SUMS.txt)개" )
