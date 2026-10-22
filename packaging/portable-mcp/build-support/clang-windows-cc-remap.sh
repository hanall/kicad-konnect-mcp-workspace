#!/bin/bash
set -euo pipefail

link=yes
args=()
for arg in "$@"; do
  case "$arg" in
    -c|-E|-S|--version|-v) link=no ;;
    -w) continue ;;
    -Wno-error*)
      printf '진단 완화 플래그를 거부합니다: %s\n' "$arg" >&2
      exit 64
      ;;
  esac
  args+=("$arg")
done

base=(/usr/bin/clang-14 --target=x86_64-w64-windows-gnu --sysroot=/usr/x86_64-w64-mingw32)
if [[ "$link" == yes ]]; then
  exec "${base[@]}" --ld-path=/usr/bin/x86_64-w64-mingw32-ld \
    -L/usr/lib/gcc/x86_64-w64-mingw32/14-win32 "${args[@]}"
fi
exec "${base[@]}" "${args[@]}"
