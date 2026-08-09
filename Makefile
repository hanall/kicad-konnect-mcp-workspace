.PHONY: help verify bootstrap build test mcp-smoke check-updates

help:
	@printf '%s\n' \
	  'make verify        root와 upstream 고정 검증' \
	  'make bootstrap     고정된 Konnect 빌드 도구 준비' \
	  'make build         Konnect release binary 빌드' \
	  'make test          root와 Konnect 전체 로컬 gate' \
	  'make mcp-smoke     MCP initialize/tools-list smoke' \
	  'make check-updates 최신 안정 upstream tag 조회'

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
