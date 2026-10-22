<!-- managed: ai-dependency-security-block -->
## 공급망 보안 지침 (최우선)

- 새 의존성 추가, 버전 변경, 설치, 게시 전에 `docs/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`와 `/home/hanol/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`를 읽는다.
- Rust dependency는 `Cargo.lock`과 `--locked`를 유지하고 Git source를 금지한다.
- Python/npm 의존성을 추가할 때는 홈 공통 guard와 감사 절차를 적용한다.

---

# AGENTS.md

이 저장소는 KiCad 10과 Konnect MCP의 재현 가능한 개발 워크스페이스다.

## 시작 게이트

1. `/home/hanol/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`를 읽고 새 의존성, 설치, 버전 변경에 적용한다.
2. `git status --short --branch`와 `git submodule status`로 root와 두 upstream 상태를 확인한다.
3. `upstreams.lock.json`과 실제 origin, tag, commit이 일치하는지 `make verify`로 확인한다.
4. 회로 시뮬레이션 작업이면 `make sim-runtime-verify`로 Qucs-S·LTspice 잠금(`config/qucs-s.lock.json`, `config/ltspice.lock.json`)과 설치 매니페스트·SHA·래퍼, 시스템 ngspice 버전을 확인한다. `make verify`는 시뮬레이터 잠금을 검사하지 않는다.

## 최신 Konnect MCP 사용 필수

- 이 저장소의 에이전트는 **프로젝트에서 최신으로 검증·고정한 Konnect MCP**를 사용한다. 기준은 `upstreams.lock.json`의 `components.konnect.version`과 `commit`이며, 임의의 전역 설치본이나 오래된 연결을 사용하지 않는다. 2026-10-06 현재 기준은 `0.13.0+hanall.1`, commit `94f80350cf67db27b179a06a8f6dbebfe4717927`이다. 이후 업그레이드에서는 잠금 파일의 새 검증값이 우선한다.
- 실행 경로는 반드시 프로젝트의 `scripts/run-konnect.sh`이며, 프로젝트 `.codex/config.toml` 또는 `.mcp.json`의 `konnect` 등록을 사용한다.
- **디스크 binary가 최신이라는 사실만으로 현재 MCP 연결도 최신이라고 판단하지 않는다.** 회로 변경 전에 현재 연결의 `get_installation_info`에서 `build.version`, `build.commit`, `runtime.executable_path`를 잠금 파일·프로젝트 release binary와 대조한다. Linux에서는 가능하면 실제 서버 PID의 `/proc/<PID>/exe` SHA-256과 디스크 binary SHA-256도 대조한다. 회로 시뮬레이션 작업이면 같은 응답의 `simulation_extension`(도구 4종·엔진 목록)이 있는지도 확인하고, 없으면 `KONNECT_SIM=1`이 아닌 구 연결로 본다.
- `get_installation_info`가 없거나 버전·commit·실행 경로가 다르면 구 연결로 간주하고 **설계 쓰기를 중단**한다. 해당 Konnect 연결을 지원되는 클라이언트 재연결 절차로 갱신한 뒤, 같은 연결에서 버전·commit과 `list_toolboxes`를 다시 확인한다. 새 테스트 프로세스의 성공을 기존 등록 연결의 재시작 성공으로 대신 보고하지 않는다.
- 재연결 시 다른 세션·다른 MCP 서버·KiCad GUI를 임의 종료하지 않는다. 단일 연결 재시작을 지원하지 않아 공유 daemon 전체에 영향을 주는 방법만 남으면, 영향 범위를 설명하고 별도 승인을 받은 뒤 수행한다.
- 오래된 도구 목록·글로벌 스킬의 도구 개수보다 **현재 검증된 연결이 반환한 schema와 프로젝트 오버레이**를 우선한다. “최신”을 이유로 공급망 검증이나 잠금 파일 갱신 없이 자동 다운로드·업그레이드하지 않는다.

## 소스 경계

- `upstream/kicad`: 공식 KiCad 원본의 최신 안정 release를 추적하는 read-only 소스다. `.99.0` 개발 태그와 임의 patch는 반영하지 않는다.
- `upstream/konnect`: `hanall/Konnect` fork의 MCP 구현이다. 공식 `mixelpixx/Konnect`는 `upstream` remote로 유지한다. 변경 시 upstream `CONTRIBUTING.md`, `DEV.md`, `docs/NAMING_CONVENTIONS.md`를 먼저 읽는다.
- root의 `scripts`, `config`, `docs`, `projects`: 우리 통합 계층이다.
- 회로 시뮬레이터(시스템 ngspice 44.2·Qucs-S 26.1.1·LTspice 24.0.12·Wine)는 upstream 소스가 아닌 외부 설치 런타임이다. 정본은 `config/qucs-s.lock.json`, `config/ltspice.lock.json`과 각 `INSTALL-MANIFEST.json`이며, KiCad 번들 ngspice 45.2는 `upstreams.lock.json`의 KiCad 10.0.6 AppImage에 속한다. 자동 갱신하지 않는다. 갱신은 새 SHA256·버전·게시일을 잠금 파일과 설치 스크립트 상단 상수에 동시에 반영한 뒤 `make install-qucs-s`/`make install-ltspice`로 수행하며 7일 age gate를 지킨다.
- `projects/sim-validation-20261022/`는 엔진 검증 fixture다. 사양 정본은 `spec/theory.py`가 생성하는 `spec/spec.json`이며, fixture 회로를 바꾸면 `make sim-verify` 기준선이 함께 바뀐다.
- upstream tag를 이동시키지 않는다. 업그레이드는 새 tag와 commit을 `upstreams.lock.json`에 동시에 반영한다.
- KiCad 갱신은 `make check-updates` 후 `make update-kicad`, Konnect 개발 준비는 `make setup-konnect-dev`를 사용한다.

## 검증 계약

- `hanall` 계정은 과금 방지를 위해 GitHub Actions를 사용하지 않는다. workflow를 추가하지 않고 저장소 Actions 권한을 비활성 상태로 유지한다.
- push 전 전체 로컬 gate: `make check-local`
- root: `make verify`
- Konnect: `make test`
- MCP: `make mcp-smoke`
- 설치된 KiCad 10 무결성: `make runtime-verify`
- 회로 시뮬레이터(ngspice apt, Qucs-S AppImage, LTspice Wine) 설치 상태: `make sim-runtime-verify`, 검증 회로 5종 회귀: `make sim-verify`, 시뮬레이션 MCP 중계 계약: `make test-sim-mcp` ([설치 계약](docs/agents/20261022-172859_circuit-simulators-linux.md), [MCP 도구 계약](docs/agents/20261022-172859_simulation-mcp-tools.md))
- KiCad 번들 ngspice 45.2 경로 회귀: `python3 scripts/sim-validation-run.py --engine kicad-bundled` (`make sim-verify`는 시스템 ngspice만 실행한다)
- 시뮬레이션 MCP 중계(`KONNECT_SIM=1`) 도구 4종 계약: `make test-sim-mcp`. `make check-local`의 `make test`는 root Python 시험(`tests/test_sim_validation.py`, `tests/test_sim_mcp_extension.py` 포함)을 돌리지만 `make mcp-smoke`는 중계 env 없이 core만 확인하고, 실제 엔진 회귀(`make sim-verify`)와 설치 검증(`make sim-runtime-verify`)은 포함하지 않는다. 시뮬레이션 중계·엔진·잠금을 바꾸면 이 타깃들을 따로 실행한다.
- 시뮬레이션 기대값 판정 통과는 그 모델·파라미터·해석 조건 범위의 결과다. ERC/DRC, 제조, 정격·열·EMI, 통전 승인으로 승격하지 않는다.
- 실제 GUI/IPC: ACUW 전용 레인에서 KiCad PCB Editor를 연 뒤 `make live-acceptance KICAD_PROJECT=... KICAD_BOARD=...`
- 제조 기능 변경: 가능한 경우 실제 KiCad 10 `kicad-cli`로 ERC, DRC, Gerber, drill 생성과 결과 파일 존재를 함께 확인한다.
- KiCad GUI/IPC 기능은 KiCad 10 PCB Editor가 실행된 상태에서 별도 통합 테스트로 확인한다.

## 안전 계약

- **사용자 영구 승인(2026-10-07)**: 「공유 화면의 KiCad GUI에서 직접 편집하세요, 영구 승인함.」 사용자가 보는 AI 공유 창의 KiCad에서 프로젝트·페이지/표제란·심볼·배선 등을 직접 편집·저장할 수 있다. 기존 MCP 전용 규칙의 명시적 예외이며 재승인을 반복 요구하지 않는다. 회로 파일 직접 텍스트 편집, GUI/MCP 동시 쓰기, 살아 있는 편집기 잠금 삭제·우회는 여전히 금지한다. 이 승인은 commit·push·제조 발주·통전 승인이 아니다. 상세는 프로젝트 오버레이를 따른다.
- 기본 MCP 실행은 반드시 `scripts/run-konnect.sh`를 통한다. 이 실행기는 `.runtime-home`을 사용해 upstream의 최초 실행 installer가 실제 사용자 `~/.claude`를 수정하지 못하게 한다.
- `.mcp.json`에서 upstream binary를 직접 실행하지 않는다.
- HTTP transport가 필요하면 loopback(`127.0.0.1`)만 사용한다. 외부 bind는 보안 검토 전 금지한다.
- Codex는 프로젝트의 `.codex/config.toml`, Claude 계열은 `.mcp.json`을 사용한다. 둘 다 `scripts/run-konnect.sh` 외의 binary를 직접 실행하지 않는다.
- 회로 파일은 원본 백업과 Git 상태를 확인한 뒤 수정한다.
- 생성된 Gerber가 DRC 통과를 의미하지 않는다. ERC/DRC/DFM을 별도 gate로 유지한다.
- 시뮬레이션 중계 도구 중 회로도 쓰기는 `set_simulation_model`뿐이며 내부적으로 core `edit_schematic_component`를 호출해 core 잠금 검사를 그대로 받는다. 공유 화면 KiCad가 같은 회로도를 열고 있으면 이 도구를 직접 호출하지 않고 `synchronize_schematic_edit`의 `edit_schematic_component` operation(`fields`에 `Sim.*`)으로 인계한다. `list_simulation_engines`, `export_spice_netlist`, `run_spice_simulation`은 `.kicad_*`를 쓰지 않는다.
- 시뮬레이션은 저장된 회로도를 `kicad-cli`가 읽어 넷리스트를 만든다. GUI 미저장 상태나 쓰기 뒤 readback 전에는 실행하지 않는다.
- 산출물은 `run_spice_simulation`의 기본 `.artifacts/sim-runs/<시각>-<stem>/`에 둔다. `export_spice_netlist`는 `output`을 생략하면 대상 프로젝트 안 `.konnect-sim/`에 쓰므로, 사용자 프로젝트의 Git 상태를 바꾸지 않으려면 `output`을 `.artifacts/` 아래 절대경로로 준다.
- 제조사 SPICE 모델(.lib/.sub/.sp)은 출처·SHA-256·라이선스·암호화 여부를 기록하고 사용자 승인 뒤 반입한다. 재배포 제한 모델과 시뮬레이터 바이너리를 저장소에 커밋하지 않는다.
- LTspice·Qucs-S·KiCad 시뮬레이터 GUI와 LTspice 배치는 명명된 ACUW 전용 레인에서만 실행한다(아래 레인 메모리 상한).

## 공개 API

MCP tool 이름, 입력/출력 schema, config key, environment variable, CLI flag, IPC protobuf는 공개 계약이다. 변경 시 호환성, migration, rollback, 회귀 테스트를 문서화한다.

공유 화면 회로도 안전 인계는 `KONNECT_GUI_SYNC=1`의 `synchronize_schematic_edit`로 제공한다. [계약](docs/agents/20261007-121257_schematic-gui-sync.md)을 먼저 읽고 dry_run revision과 실제 캡처를 검증한다. 이는 정상 종료·MCP 편집·같은 레인 재열기이며 열린 회로도 메모리 수정이나 잠금 우회가 아니다. 미저장/대화상자/다른 문서/낡은 revision은 거부한다. 회귀는 `make test-gui-sync`; 기존 core/GUI 연결은 임의 재시작하지 않는다.

회로 시뮬레이션은 `KONNECT_SIM=1`의 중계 도구 4종(`list_simulation_engines`, `export_spice_netlist`, `set_simulation_model`, `run_spice_simulation`)으로 제공한다. [계약](docs/agents/20261022-172859_simulation-mcp-tools.md)을 먼저 읽는다. 회로도 쓰기는 upstream `edit_schematic_component`만 수행하고, 엔진은 시스템 ngspice·KiCad 번들 ngspice·LTspice(레인)다. 기존 지시어는 제거되고 호출 인자만 적용되며 `timeout_seconds`는 100초 이하다. 회귀는 `make test-sim-mcp`; 되돌리기는 `KONNECT_SIM=0`.

## 라이선스

root 통합 계층과 Konnect 파생 변경은 `AGPL-3.0-only`를 따른다. KiCad는 `LICENSE.README`에 적힌 파일별 라이선스를 보존한다. 사업용 비공개 파생/네트워크 서비스는 Konnect의 상용 라이선스 필요 여부를 먼저 검토한다.
회로 시뮬레이터는 저장소에 포함하지 않는 외부 런타임이며 각자의 라이선스를 따른다. Qucs-S 26.1.1은 GPL-2.0-or-later, LTspice 24.0.12는 ADI 무료 비공개 사용권이다(각 잠금 파일 `license`). 시스템 ngspice 44.2는 Debian `/usr/share/doc/ngspice/copyright` 기준 본체가 BSD-3-clause이고 일부 문서·설정 파일은 CC-BY-SA-4.0·GPL-2+ 등이다. 시뮬레이터 바이너리, Wine prefix, 제조사 모델을 저장소에 커밋·재배포하지 않는다. `scripts/konnect-mcp-sim.py`, `scripts/sim_engines.py`는 root 통합 계층으로 `AGPL-3.0-only`를 따른다.

## Agent skills

코드를 수정하기 전에 아래 순서와 [프로젝트 오버레이](docs/agents/20261006-112759_kicad-konnect-overlay.md)를 읽습니다. 글로벌 스킬의 구 도구 개수·극성·뷰어 설명보다 현재 실행 schema와 이 오버레이가 우선합니다.

| 단서 | 먼저 읽을 스킬 |
|---|---|
| 회로도 신규 설계·가독성 재작성·승인된 전기 변경·품질 검토 | 프로젝트 정본 [`skills/kicad-schematic-quality/SKILL.md`](skills/kicad-schematic-quality/SKILL.md)를 먼저 읽고 모드를 선택. 현재 실행 조합의 지원은 동일 패키지 SHA의 실제 receipt로 판단 |
| 회로 시뮬레이션·SPICE 모델·ngspice/LTspice/Qucs-S·동작 검토 | 프로젝트 정본 [`skills/kicad-simulation/SKILL.md`](skills/kicad-simulation/SKILL.md). MCP 도구 4종(`KONNECT_SIM=1`)과 엔진 사용법은 그 references가 정본 |
| KiCad, 회로도, PCB, `.kicad_*` | `~/.claude/skills/konnect/SKILL.md` |
| 오류, 고장, 진단, debug | `~/.claude/skills/diagnose/SKILL.md` |
| 시험 우선, TDD, red-green | `~/.claude/skills/tdd/SKILL.md` |
| ERC, DRC, 설계 검토 | `~/.claude/skills/kicad-review/SKILL.md` |
| 회로도 설계·편집 | `~/.claude/skills/kicad-schematic/SKILL.md` |
| PCB 배치·배선 | `~/.claude/skills/kicad-pcb/SKILL.md` |
| 심볼·footprint 라이브러리 | `~/.claude/skills/kicad-library/SKILL.md` |
| 제조·Gerber·발주 파일 | `~/.claude/skills/kicad-manufacture/SKILL.md` |
| 분석·진단·검증 결과 보고 | `~/.claude/skills/html-report/SKILL.md` |

회로도 품질 단서가 있으면 프로젝트 품질 스킬의 모드를 먼저 고르고 `konnect` 안전 규칙과 해당 작업 스킬을 이어 적용합니다. 시뮬레이션 단서가 있으면 `konnect` 안전 규칙 다음에 프로젝트 시뮬레이션 스킬을 적용하고, Sim 모델 부착처럼 회로도 쓰기가 필요하면 품질 스킬의 모드를 먼저 고릅니다. 그 외 복수 단서는 `konnect` 안전 규칙부터 적용합니다. `CLAUDE.md`는 `AGENTS.md`의 symlink이므로 별도 사본을 만들지 않습니다.

회로도 품질 작업은 위 프로젝트 정본과 [`기존 스킬 교정`](skills/kicad-schematic-quality/references/legacy-skill-overrides.md)의 C01~C13을 함께 적용합니다. `konnect`, `kicad-schematic`, `kicad-review`의 고정 도구 수·잘못된 배선 인자·핀 극성·누락 검사를 PASS로 보는 설명은 현재 schema와 이 교정으로 대체하며, 외부 글로벌 원문은 수정하지 않습니다. `.claude/skills/kicad-schematic-quality`와 `.agents/skills/kicad-schematic-quality`는 같은 패키지의 상대 링크입니다. `make test-standard-quality`는 합성·이식성 회귀이며 실제 CAD/GUI·제조/통전 합격을 뜻하지 않습니다. [구축 범위와 검증 요구](docs/agents/20261012-040121_schematic-quality-standardization-plan.md), [사용·원복·현재 지원표](docs/agents/20261012-040121_standard-quality-user-guide.md)를 따릅니다.
회로 시뮬레이션 작업은 [`kicad-simulation`](skills/kicad-simulation/SKILL.md)과 그 패키지의 [시뮬레이션 교정](skills/kicad-simulation/references/legacy-skill-overrides.md) C14~C21을 함께 적용합니다. 글로벌 `konnect`·`kicad-schematic`·`kicad-review`에는 SPICE·시뮬레이션 지침이 없으므로(2026-10-22 확인) 그 흐름이 검증·저장·verdict로 끝나는 지점에 이 스킬을 잇습니다. C14~C21은 품질 패키지 identity를 바꾸지 않도록 `kicad-schematic-quality` 밖에 둡니다. `.claude/skills/kicad-simulation`과 `.agents/skills/kicad-simulation`은 같은 패키지의 상대 링크입니다.

<!-- SKILLS-INDEX:START -->
<!-- Auto-generated index of skills available at ~/.claude/skills/. Regenerate with `~/.local/bin/inject-skills-index.py`. Do not hand-edit between START/END markers — changes will be overwritten. -->

## Available Skills

이 프로젝트의 에이전트(Claude Code, Codex 등)는 사용자 글로벌 디렉토리 `~/.claude/skills/`에 설치된 **18개 스킬**을 사용할 수 있습니다. 비자명한 작업을 시작하기 전에 아래 목록에서 적용 가능한 스킬을 검토하고, 사용하려면 해당 스킬의 `SKILL.md`(예: `~/.claude/skills/<name>/SKILL.md`)를 먼저 읽은 뒤 그 지시를 따르세요. Claude Code는 자동 인식하지만, Codex 등 다른 에이전트는 이 인덱스를 명시적 진입점으로 사용합니다.

- **`diagnose`** — Diagnosis loop for hard bugs and performance regressions. Use when the user says "diagnose"/"debug this", or reports something broken/throwing/failing/slow.
- **`docx`** — Word 문서 생성, 편집, 분석. .docx 파일 작업: 새 문서 생성, 콘텐츠 수정, 변경 추적, 코멘트 추가.
- **`gmail-agent-system`** — Use the shared local Gmail system in /home/hanol/gmail-agent-system when the user asks to read, search, analyze, send, reply to, forward, label, or delete email from the shared Google account across any project. Prefer the global `gmail-...
- **`grill-with-docs`** — Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. Use when user wants to stress-test a plan against their pro...
- **`grilling`** — Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
- **`html-report`** — Hanol 표준 HTML 보고서를 작성·생성·보고한다. 분석/진단/조사/감사/마이그레이션 계획 등의 결과를 자기완결형(외부 의존성 0) 다크테마 HTML 보고서로 만들고, 대화창에서 Ctrl+Click으로 바로 열리는 file:// 링크로 보고할 때 사용. "보고서로 정리", "HTML 보고서", "리포트 만들어", "결과를 문서로" 등의 요청에 트리거. 새 프로젝트에 이 보고서 시스템을 셋업/전파할 때도 사용.
- **`kicad-library`** — Library management workflow for KiCAD — creating symbols, footprints, and managing libraries via MCP tools. Triggers on: "create a symbol", "make a footprint", "custom component", "register library", "find a part", "pin numbering", "new ...
- **`kicad-manufacture`** — Manufacturing and fabrication workflow for KiCAD projects via MCP tools. Triggers on: "send to fab", "order boards", "gerbers", "JLCPCB", "manufacturing", "export for production", "pick and place", "assembly files", "generate fabrication...
- **`kicad-pcb`** — Workflow skill for KiCAD PCB layout and routing via MCP tools. Triggers on: "layout the board", "route traces", "PCB", "place footprints", "copper pour", "board outline", "differential pair", "board setup", "track width", "via", "zone", ...
- **`kicad-review`** — Design review and validation workflow for KiCAD projects via MCP tools. Triggers on: "review my design", "check for errors", "audit", "DRC", "ERC", "find problems", "design review", "is this ready", "validate", "check my schematic", "che...
- **`kicad-schematic`** — Workflow skill for KiCAD schematic design via MCP tools. Triggers on: "design a circuit", "add a component", "wire up", "connect pins", "build schematic", "place resistor", "place cap", "place IC", "schematic", "add symbol", "net label",...
- **`konnect`** — Mandatory operating rules for ANY task involving KiCAD projects. Loaded when the user mentions KiCAD, schematics, PCBs, or any .kicad_* file. Prevents file corruption by routing all changes through Konnect MCP tools.
- **`pptx`** — 프레젠테이션 생성, 편집, 분석. .pptx 파일 작업: 새 프레젠테이션 생성, 콘텐츠 수정, 레이아웃 작업, 발표자 노트 추가.
- **`security-best-practices`** — Perform language and framework specific security best-practice reviews and suggest improvements. Trigger only when the user explicitly requests security best practices guidance, a security review/report, or secure-by-default coding help....
- **`security-ownership-map`** — Analyze git repositories to build a security ownership topology (people-to-file), compute bus factor and sensitive-code ownership, and export CSV/JSON for graph databases and visualization. Trigger only when the user explicitly wants a s...
- **`security-threat-model`** — Repository-grounded threat modeling that enumerates trust boundaries, assets, attacker capabilities, abuse paths, and mitigations, and writes a concise Markdown threat model. Trigger only when the user explicitly asks to threat model a c...
- **`tdd`** — Test-driven development with red-green-refactor loop. Use when user wants to build features or fix bugs using TDD, mentions "red-green-refactor", wants integration tests, or asks for test-first development.
- **`user-screen-terminal`** — Open a shared terminal on the user's real screen (X session) and interact with it only through the tmux text channel — the user watches live while the agent types/reads without touching their keyboard, mouse, or focus. Use when the user ...

<!-- SKILLS-INDEX:END -->

<!-- REPORT-SYSTEM:START -->
## HTML 보고서 시스템 (분석·진단·조사·계획 결과 보고 시 필수 준수)

분석/진단/조사/마이그레이션 계획 등 결과물은 자기완결형 HTML 보고서로 작성하고, 대화창에서 Ctrl+Click으로 바로 열리는 `file://` 링크로 보고한다.

- 키트: `$AGENT_OS_ROOT/skills/skills/personal/html-report/` (`$AGENT_OS_ROOT` 미설정 시 `~/agent-os/skills/skills/personal/html-report/`)
- git repo 안의 출력 위치: `<repo>/docs/보고서/`
- 레포에 `docs/리뷰/`가 있으면 같은 timestamp의 Markdown도 생성한다.
- 파일명: `YYYYMMDD-HHMMSS_slug.html`; 시각은 MCP time 또는 `date`로 실측한다.
- CSS/JS는 inline으로 유지하고 외부 dependency를 사용하지 않는다.
- 결론을 먼저 제시하고 측정값, 리스크, rollback을 포함한다.
- 보고 시 `file://` 링크, 핵심 요약 3~5줄, 평문 절대경로를 함께 제공한다.
<!-- REPORT-SYSTEM:END -->

<!-- ACUW-MANUAL:START -->
<!-- 자동 주입: ai-computer-use-workspace/scripts/inject-acuw-manual.py. 마커 사이는 수정하지 마세요(덮어쓰기됨). -->
## AI Computer Use Workspace — 화면 조작이 필요할 때

이 호스트에는 **AI가 사람처럼 GUI 화면을 보고 조작**하는 로컬 컴퓨터 유즈 워크스페이스가 있습니다. 다른 작업 중 클릭·타이핑·스크린샷·앱 실행 등 **실제 화면 GUI 조작이 필요하면**, 설치/설정 없이 절대경로 셸 명령으로 바로 쓰세요(현재 cwd 무관, 검증됨).

- **전체 사용 매뉴얼(SSOT)**: `/home/hanol/ai-computer-use-workspace/docs/운영/AGENT-WORKSPACE-MANUAL.md`
- **모델(독립 입력 채널)**: 기본 레인은 격리 `DISPLAY=:99` — 에이전트가 :99만 조작하고 사용자는 실제 화면의 Chrome noVNC observer 창으로 같은 장면을 함께 봅니다. 선택 레인 `host-mpx`는 사용자 **실제 화면(:0)에 AI 전용 커서/키보드**(MPX/XInput2 마스터)를 만듭니다. 다만 Chromium X11은 추가 MasterKeyboard에서 사용자 core DOM 키를 폐기하므로 host-mpx는 기본 차단된 실험 레인입니다.
- **정책**: 기본 visible 레인은 개방. host-mpx는 `ACUW_MPX_ALLOW_CHROMIUM_INPUT_RISK=1`의 명시 위험 수용이 있어야 시작합니다. live truth는 `bash /home/hanol/ai-computer-use-workspace/scripts/status.sh`.
- **오류·대기·종료 보장**: MCP/공동 메모는 잘못된 Unicode·JSON 입력 뒤에도 정상 작업을 계속할 수 있고, watch/term-text 대기는 외부 도구 호출까지 같은 deadline을 적용합니다. media 강제 종료는 자체 PID 세대와 socket 결속을 확인합니다. 상세는 정본 매뉴얼을 따릅니다.

**다른 프로젝트에서 쓸 때의 원칙(필수)**: 기본 인스턴스(`:99`)는 공유 자원이라 이미 다른 AI가 작업 중일 수 있습니다. **자기 프로젝트 전용 병렬 레인을 열어 작업하세요** — 기본 인스턴스에 브라우저/앱을 띄우면 남의 작업을 오염시킵니다(안전 게이트·상세는 매뉴얼 §9).

```bash
# 다른 프로젝트에서 GUI 작업 = 병렬 레인이 기본 (이름은 자기 프로젝트명)
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh open 내프로젝트명   # 자동 할당·:99 비간섭
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh run 내프로젝트명 -- run-in-workspace.sh -- firefox https://example.com
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh run 내프로젝트명 -- capture.sh
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh stop 내프로젝트명   # 내 레인만 정리(busy면 거부)
```

빠른 시작(기본 인스턴스 — ACUW 자체 작업/사용자 지시가 있을 때만):

```bash
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh list           # 먼저 확인: 누가 어디서 작업 중인가
bash /home/hanol/ai-computer-use-workspace/scripts/start-workspace.sh        # 시작(idempotent)
bash /home/hanol/ai-computer-use-workspace/scripts/run-in-workspace.sh -- firefox https://example.com
bash /home/hanol/ai-computer-use-workspace/scripts/capture.sh                # 화면 PNG — LLM은 이 파일을 직접 Read(비전)로 판독
bash /home/hanol/ai-computer-use-workspace/scripts/browser.sh start          # 브라우저 레인(CDP): navigate/eval/text/find/fill/console/network
bash /home/hanol/ai-computer-use-workspace/scripts/record.sh start           # 화면 녹화(mp4/gif는 stop --gif; digest로 프레임 판독)
bash /home/hanol/ai-computer-use-workspace/scripts/open-command-terminal.sh --mux 세션명 -- <TUI>   # tmux 텍스트 레인
bash /home/hanol/ai-computer-use-workspace/scripts/term-text.sh capture --session 세션명            # 터미널 무손실 판독(OCR 불필요)
bash /home/hanol/ai-computer-use-workspace/scripts/user-screen-terminal.sh open 세션명 --cwd "$PWD" -- claude   # ★사용자 실제 화면에 공유 터미널 — 같이 보며 텍스트로 대화(send/capture/stop, 매뉴얼 §4.9)
bash /home/hanol/ai-computer-use-workspace/scripts/watch.sh --once           # 화면 변화까지 대기(차분 79ms; push·변화 좌표는 damage-monitor.py --regions)
bash /home/hanol/ai-computer-use-workspace/scripts/stop-workspace.sh         # 정리
export ACUW_BACKEND=host-mpx ACUW_MPX_ALLOW_CHROMIUM_INPUT_RISK=1              # Chromium 사용자 키 유실 위험 명시 수용
bash /home/hanol/ai-computer-use-workspace/scripts/start-workspace.sh          # 실제 화면(:0)에 AI 전용 커서
bash /home/hanol/ai-computer-use-workspace/scripts/status.sh                   # 실제 geometry, observer/VNC 비활성
bash /home/hanol/ai-computer-use-workspace/scripts/stop-workspace.sh && unset ACUW_BACKEND ACUW_MPX_ALLOW_CHROMIUM_INPUT_RISK
```

`ACUW_BACKEND=host-mpx`와 위험 override 같은 인라인 env는 다음 명령으로 자동 지속되지 않습니다. 연속 조작은 위처럼 둘 다 `export`하거나 모든 명령에 같은 prefix를 붙이세요.

입력 표면(클릭/타이핑/키/스크롤/드래그/대기)·부분 확대 캡처(zoom)·클립보드·터미널·기본앱/데스크톱앱·브라우저 레인(CDP)·화면 녹화·host-mpx 레인(매뉴얼 §1-5, 계약 §2-3)·**계층적 읽기 채널**(tmux 버퍼 `term-text.sh`·Codex 이벤트 `codex-events.sh`·변화 감시 `watch.sh`/`damage-monitor.py`·PRIMARY 긁기 `read-terminal.sh`·AT-SPI `a11y.sh`·영상 `media.sh`·녹화 digest — 매뉴얼 §5.3-1~§5.3-6)·MCP(`workspace_*` 50종)·트러블슈팅은 위 매뉴얼을 참조하세요. 전체 도구 카탈로그는 `/home/hanol/ai-computer-use-workspace/scripts/REGISTRY.md`.
<!-- ACUW-MANUAL:END -->

## 레인 메모리 상한 (2026-10-06 추가 — OOM 사고 재발 방지)

KiCad(kicad+pcbnew+eeschema)를 한 ACUW 레인에 동시에 띄우면 레인 합산 피크가 8G에 닿아 cgroup OOM으로 사살된다(2026-10-06 11:20 실사고: `kicad-native-capability-probe` 레인, slice 피크 8G, kicad PID 1484949 사살 → GNOME "앱 중지함 / 장치 메모리가 거의 가득 찼습니다" 알림). 이 레포에서 레인을 열 때는 **`ACUW_LANE_MEMORY_MAX=16G`를 env로 명시**한다. 전역 기본값(8G)은 호스트 보호용이므로 ACUW 쪽은 바꾸지 않는다(매뉴얼 §6-4).

```bash
ACUW_LANE_MEMORY_MAX=16G bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh open kicad-konnect
# start-workspace.sh / run-in-workspace.sh 를 직접 부르는 경로도 같은 env 를 앞에 둔다
```

- `scripts/mcp-pcb-functional.py`(781행 부근)가 `run-in-workspace.sh`를 직접 호출한다 — 그 호출부에도 env 전달이 필요하다(코드 미수정, 담당 세션 판단).
- 회로 시뮬레이터 GUI(LTspice·Qucs-S·KiCad 시뮬레이터)와 LTspice 배치도 같은 규칙을 따른다. 레인은 `ACUW_LANE_MEMORY_MAX=16G ... instance.sh open <레인>`으로 미리 연다. `run_spice_simulation(engine='ltspice', lane=...)`은 `instance.sh run`만 호출하며(레인을 열지 않음) `ACUW_LANE_MEMORY_MAX`가 비어 있으면 16G를 넣는다. 2026-10-22 LTspice 검증 1건은 이 env 없이 `MemoryMax=8G` 레인에서 실행됐다(`projects/sim-validation-20261022/results/ltspice-workflow.json`).
