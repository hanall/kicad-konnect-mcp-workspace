.PHONY: help verify bootstrap build test mcp-smoke runtime-verify live-acceptance check-updates update-kicad setup-konnect-dev check-local

KICAD_PROJECT ?=
KICAD_BOARD ?=
KICAD_EVIDENCE ?=.artifacts/kicad-live-acceptance.json

help:
	@printf '%s\n' \
	  'make verify        root와 upstream 고정 검증' \
	  'make bootstrap     고정된 Konnect 빌드 도구 준비' \
	  'make build         Konnect release binary 빌드' \
	  'make test          root와 Konnect 전체 로컬 gate' \
	  'make mcp-smoke     MCP initialize/tools-list smoke' \
	  'make runtime-verify 설치된 KiCad 10 AppImage 해시/서명/CLI 검증' \
	  'make live-acceptance KICAD_PROJECT=... KICAD_BOARD=...  실행 중인 GUI/IPC/DRC 검증' \
	  'make check-updates 최신 안정 upstream tag 조회' \
	  'make update-kicad  공식 최신 KiCad 안정 release 반영' \
	  'make setup-konnect-dev  Konnect fork/upstream 개발 remote 준비' \
	  'make check-local   GitHub Actions 없는 전체 로컬 gate'

verify:
	@python3 scripts/verify-project.py

bootstrap:
	@./scripts/bootstrap-dev-deps.sh

build:
	@./scripts/build-konnect.sh

test: verify
	@./scripts/test-konnect.sh

mcp-smoke:
	@python3 scripts/mcp-smoke.py

runtime-verify:
	@./scripts/install-kicad-appimage.sh --verify-only

live-acceptance:
	@test -n "$(KICAD_PROJECT)" || { printf '%s\n' 'KICAD_PROJECT=.kicad_pro 경로가 필요합니다.' >&2; exit 2; }
	@test -n "$(KICAD_BOARD)" || { printf '%s\n' 'KICAD_BOARD=.kicad_pcb 경로가 필요합니다.' >&2; exit 2; }
	@python3 scripts/mcp-live-acceptance.py \
	  --project "$(KICAD_PROJECT)" \
	  --board "$(KICAD_BOARD)" \
	  --evidence "$(KICAD_EVIDENCE)"

check-updates:
	@./scripts/check-updates.sh

update-kicad:
	@python3 scripts/manage-upstreams.py update-kicad

setup-konnect-dev:
	@./scripts/setup-konnect-dev.sh

check-local:
	@$(MAKE) check-updates
	@$(MAKE) test
	@$(MAKE) build
	@$(MAKE) mcp-smoke
