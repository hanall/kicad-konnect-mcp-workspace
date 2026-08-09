.PHONY: help verify bootstrap build test mcp-smoke check-updates update-kicad setup-konnect-dev check-local

help:
	@printf '%s\n' \
	  'make verify        root와 upstream 고정 검증' \
	  'make bootstrap     고정된 Konnect 빌드 도구 준비' \
	  'make build         Konnect release binary 빌드' \
	  'make test          root와 Konnect 전체 로컬 gate' \
	  'make mcp-smoke     MCP initialize/tools-list smoke' \
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
