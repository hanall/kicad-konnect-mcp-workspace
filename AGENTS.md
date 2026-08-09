<!-- managed: ai-dependency-security-block -->
## 공급망 보안 지침 (최우선)

- 새 의존성 추가, 버전 변경, 설치, 게시 전에 `docs/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`와 `/home/hanol/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`를 읽는다.
- Rust dependency는 `Cargo.lock`과 `--locked`를 유지하고 Git source를 금지한다.
- Python/npm 의존성을 추가할 때는 홈 공통 guard와 감사 절차를 적용한다.

---

# AGENTS.md

이 저장소는 KiCad 10과 Konnect MCP의 재현 가능한 개발 워크스페이스다.

## 시작 게이트

1. 파일 수정 전 `proj gate kicad-konnect-mcp-workspace`를 실행한다.
2. `/home/hanol/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`를 읽고 새 의존성, 설치, 버전 변경에 적용한다.
3. `git status --short --branch`와 `git submodule status`로 root와 두 upstream 상태를 확인한다.
4. `upstreams.lock.json`과 실제 origin, tag, commit이 일치하는지 `make verify`로 확인한다.

## 소스 경계

- `upstream/kicad`: 공식 KiCad 원본의 최신 안정 release를 추적하는 read-only 소스다. `.99.0` 개발 태그와 임의 patch는 반영하지 않는다.
- `upstream/konnect`: `hanall/Konnect` fork의 MCP 구현이다. 공식 `mixelpixx/Konnect`는 `upstream` remote로 유지한다. 변경 시 upstream `CONTRIBUTING.md`, `DEV.md`, `docs/NAMING_CONVENTIONS.md`를 먼저 읽는다.
- root의 `scripts`, `config`, `docs`, `projects`: 우리 통합 계층이다.
- upstream tag를 이동시키지 않는다. 업그레이드는 새 tag와 commit을 `upstreams.lock.json`에 동시에 반영한다.
- KiCad 갱신은 `make check-updates` 후 `make update-kicad`, Konnect 개발 준비는 `make setup-konnect-dev`를 사용한다.

## 검증 계약

- `hanall` 계정은 과금 방지를 위해 GitHub Actions를 사용하지 않는다. workflow를 추가하지 않고 저장소 Actions 권한을 비활성 상태로 유지한다.
- push 전 전체 로컬 gate: `make check-local`
- root: `make verify`
- Konnect: `make test`
- MCP: `make mcp-smoke`
- 제조 기능 변경: 가능한 경우 실제 KiCad 10 `kicad-cli`로 ERC, DRC, Gerber, drill 생성과 결과 파일 존재를 함께 확인한다.
- KiCad GUI/IPC 기능은 KiCad 10 PCB Editor가 실행된 상태에서 별도 통합 테스트로 확인한다.

## 안전 계약

- 기본 MCP 실행은 반드시 `scripts/run-konnect.sh`를 통한다. 이 실행기는 `.runtime-home`을 사용해 upstream의 최초 실행 installer가 실제 사용자 `~/.claude`를 수정하지 못하게 한다.
- `.mcp.json`에서 upstream binary를 직접 실행하지 않는다.
- HTTP transport가 필요하면 loopback(`127.0.0.1`)만 사용한다. 외부 bind는 보안 검토 전 금지한다.
- 회로 파일은 원본 백업과 Git 상태를 확인한 뒤 수정한다.
- 생성된 Gerber가 DRC 통과를 의미하지 않는다. ERC/DRC/DFM을 별도 gate로 유지한다.

## 공개 API

MCP tool 이름, 입력/출력 schema, config key, environment variable, CLI flag, IPC protobuf는 공개 계약이다. 변경 시 호환성, migration, rollback, 회귀 테스트를 문서화한다.

## 라이선스

root 통합 계층과 Konnect 파생 변경은 `AGPL-3.0-only`를 따른다. KiCad는 `LICENSE.README`에 적힌 파일별 라이선스를 보존한다. 사업용 비공개 파생/네트워크 서비스는 Konnect의 상용 라이선스 필요 여부를 먼저 검토한다.

<!-- SKILLS-INDEX:START -->
<!-- Auto-generated index of skills available at ~/.claude/skills/. Regenerate with `~/.local/bin/inject-skills-index.py`. Do not hand-edit between START/END markers — changes will be overwritten. -->

## Available Skills

이 프로젝트의 에이전트(Claude Code, Codex 등)는 사용자 글로벌 디렉토리 `~/.claude/skills/`에 설치된 **21개 스킬**을 사용할 수 있습니다. 비자명한 작업을 시작하기 전에 아래 목록에서 적용 가능한 스킬을 검토하고, 사용하려면 해당 스킬의 `SKILL.md`(예: `~/.claude/skills/<name>/SKILL.md`)를 먼저 읽은 뒤 그 지시를 따르세요. Claude Code는 자동 인식하지만, Codex 등 다른 에이전트는 이 인덱스를 명시적 진입점으로 사용합니다.

- **`computer-use`** — Use Orca's computer-use CLI to inspect and operate local desktop app windows through accessibility trees, screenshots, and safe UI actions. Use for desktop app interaction: list apps/windows, get app state, read visible UI, click control...
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
- **`orca-cli`** — Use the public `orca` CLI to operate Orca-managed worktrees, folder contexts, terminals, repos, automations, worktree comments, and the browser embedded inside the Orca app. Use when the user says "$orca-cli", "use orca cli", "Orca workt...
- **`orchestration`** — Use Orca orchestration for structured multi-agent coordination: threaded messages, blocking ask/reply flows, task dispatch, worker_done/escalation waits, task DAGs, decision gates, coordinator loops, or decomposing work across agents. Us...
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
