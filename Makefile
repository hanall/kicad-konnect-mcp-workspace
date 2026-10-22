.PHONY: help verify bootstrap build test mcp-smoke runtime-verify live-acceptance check-updates update-kicad setup-konnect-dev check-local

KICAD_PROJECT ?=
KICAD_BOARD ?=
KICAD_EVIDENCE ?=.artifacts/kicad-live-acceptance.json
KICAD_REQUIRE_CLEAN ?=0

help:
	@printf '%s\n' \
	  'make verify        root와 upstream 고정 검증' \
	  'make bootstrap     고정된 Konnect 빌드 도구 준비' \
	  'make build         Konnect release binary 빌드' \
	  'make test          root와 Konnect 전체 로컬 gate' \
	  'make test-standard-quality  표준 회로도 품질 스킬 합성·이식성 회귀' \
	  'make mcp-smoke     MCP initialize/tools-list smoke' \
	  'make runtime-verify 설치된 KiCad 10 AppImage 해시/서명/CLI 검증' \
	  'make live-acceptance KICAD_PROJECT=... KICAD_BOARD=...  실행 중인 GUI/IPC/DRC 검증' \
	  'make check-updates 최신 안정 upstream tag 조회' \
	  'make update-kicad  공식 최신 KiCad 안정 release 반영' \
	  'make setup-konnect-dev  Konnect fork/upstream 개발 remote 준비' \
	  'make install-qucs-s  Qucs-S 26.1.1 AppImage /opt 고정 설치 또는 재검증' \
	  'make install-ltspice  LTspice 24.0.12.0을 사용자 Wine prefix에 설치(레인 DISPLAY 필요) 또는 재검증' \
	  'make sim-runtime-verify  Qucs-S·LTspice 매니페스트/SHA/래퍼와 시스템 ngspice 패키지 버전 검증' \
	  'make sim-verify    검증 회로 5종을 시스템 ngspice 배치로 실행해 이론값과 대조' \
	  'make test-sim-mcp  시뮬레이션 MCP 중계(KONNECT_SIM=1) 도구 4종 계약 회귀' \
	  'make test-gui-sync  GUI 안전 인계 중계(KONNECT_GUI_SYNC=1) 회귀와 스모크' \
	  'make check-local   GitHub Actions 없는 전체 로컬 gate'

verify:
	@python3 scripts/verify-project.py

bootstrap:
	@./scripts/bootstrap-dev-deps.sh

build:
	@./scripts/build-konnect.sh

test: verify
	@./scripts/test-konnect.sh

.PHONY: test-standard-quality
test-standard-quality:
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_standard_quality*.py' -v

mcp-smoke:
	@python3 scripts/mcp-smoke.py

runtime-verify:
	@./scripts/install-kicad-appimage.sh --verify-only

.PHONY: test-gui-sync
test-gui-sync:
	@python3 -m unittest discover -s tests -p 'test_*.py' -v
	@KONNECT_GUI_SYNC=1 python3 scripts/mcp-smoke.py

live-acceptance:
	@test -n "$(KICAD_PROJECT)" || { printf '%s\n' 'KICAD_PROJECT=.kicad_pro 경로가 필요합니다.' >&2; exit 2; }
	@test -n "$(KICAD_BOARD)" || { printf '%s\n' 'KICAD_BOARD=.kicad_pcb 경로가 필요합니다.' >&2; exit 2; }
	@python3 scripts/mcp-live-acceptance.py \
	  --project "$(KICAD_PROJECT)" \
	  --board "$(KICAD_BOARD)" \
	  --evidence "$(KICAD_EVIDENCE)" \
	  $(if $(filter 1,$(KICAD_REQUIRE_CLEAN)),--require-clean-design,)

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

.PHONY: install-qucs-s install-ltspice sim-runtime-verify sim-verify
install-qucs-s:
	@./scripts/install-qucs-s-appimage.sh

install-ltspice:
	@./scripts/install-ltspice-wine.sh

sim-runtime-verify:
	@./scripts/install-qucs-s-appimage.sh --verify-only
	@./scripts/install-ltspice-wine.sh --verify-only
	@ngspice --version | grep -E '^\*\* ngspice-[0-9]'

sim-verify:
	@python3 scripts/sim-validation-run.py --out .artifacts/sim-validation-ngspice --json .artifacts/sim-validation-ngspice.json

.PHONY: test-sim-mcp
test-sim-mcp:
	@PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_sim_mcp_extension -v
	@KONNECT_SIM=1 KONNECT_GUI_SYNC=1 python3 scripts/mcp-smoke.py
