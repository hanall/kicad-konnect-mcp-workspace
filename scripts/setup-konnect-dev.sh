#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$ROOT/upstream/konnect"

mapfile -t contract < <(python3 - "$ROOT/upstreams.lock.json" <<'PY'
import json
import sys

item = json.load(open(sys.argv[1], encoding="utf-8"))["components"]["konnect"]
print(item["origin"])
print(item["upstream_origin"])
print(item["development_branch"])
PY
)

fork_origin="${contract[0]}"
official_upstream="${contract[1]}"
development_branch="${contract[2]}"

[[ -d "$REPO" && -e "$REPO/.git" ]] || {
  printf 'Konnect submodule이 없습니다: %s\n' "$REPO" >&2
  exit 1
}

actual_origin="$(git -C "$REPO" remote get-url origin)"
[[ "$actual_origin" == "$fork_origin" ]] || {
  printf 'Konnect origin 불일치: expected=%s actual=%s\n' "$fork_origin" "$actual_origin" >&2
  exit 1
}

if git -C "$REPO" remote get-url upstream >/dev/null 2>&1; then
  git -C "$REPO" remote set-url upstream "$official_upstream"
else
  git -C "$REPO" remote add upstream "$official_upstream"
fi

git -C "$REPO" fetch --filter=blob:none upstream --tags
git -C "$REPO" fetch origin "$development_branch"
if git -C "$REPO" show-ref --verify --quiet "refs/heads/$development_branch"; then
  git -C "$REPO" switch "$development_branch"
else
  git -C "$REPO" switch --track -c "$development_branch" "origin/$development_branch"
fi
git -C "$REPO" branch --set-upstream-to="origin/$development_branch" "$development_branch"

printf 'Konnect 개발 환경 준비 완료\n'
printf '  fork:     %s\n' "$fork_origin"
printf '  upstream: %s\n' "$official_upstream"
printf '  branch:   %s\n' "$development_branch"
