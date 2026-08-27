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
- 설치된 KiCad 10 무결성: `make runtime-verify`
- 실제 GUI/IPC: ACUW 전용 레인에서 KiCad PCB Editor를 연 뒤 `make live-acceptance KICAD_PROJECT=... KICAD_BOARD=...`
- 제조 기능 변경: 가능한 경우 실제 KiCad 10 `kicad-cli`로 ERC, DRC, Gerber, drill 생성과 결과 파일 존재를 함께 확인한다.
- KiCad GUI/IPC 기능은 KiCad 10 PCB Editor가 실행된 상태에서 별도 통합 테스트로 확인한다.

## 안전 계약

- 기본 MCP 실행은 반드시 `scripts/run-konnect.sh`를 통한다. 이 실행기는 `.runtime-home`을 사용해 upstream의 최초 실행 installer가 실제 사용자 `~/.claude`를 수정하지 못하게 한다.
- `.mcp.json`에서 upstream binary를 직접 실행하지 않는다.
- HTTP transport가 필요하면 loopback(`127.0.0.1`)만 사용한다. 외부 bind는 보안 검토 전 금지한다.
- Codex는 프로젝트의 `.codex/config.toml`, Claude 계열은 `.mcp.json`을 사용한다. 둘 다 `scripts/run-konnect.sh` 외의 binary를 직접 실행하지 않는다.
- 회로 파일은 원본 백업과 Git 상태를 확인한 뒤 수정한다.
- 생성된 Gerber가 DRC 통과를 의미하지 않는다. ERC/DRC/DFM을 별도 gate로 유지한다.

## 공개 API

MCP tool 이름, 입력/출력 schema, config key, environment variable, CLI flag, IPC protobuf는 공개 계약이다. 변경 시 호환성, migration, rollback, 회귀 테스트를 문서화한다.

## 라이선스

root 통합 계층과 Konnect 파생 변경은 `AGPL-3.0-only`를 따른다. KiCad는 `LICENSE.README`에 적힌 파일별 라이선스를 보존한다. 사업용 비공개 파생/네트워크 서비스는 Konnect의 상용 라이선스 필요 여부를 먼저 검토한다.

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

<!-- UNKNOWN-AWARE-PROTOCOL:START -->
<!-- protocol-version: compact-guarded.1 (derived from 1.0.0-rc.12) -->
<!-- Regenerate/rollout with ~/.local/bin/inject-unknown-protocol.py . Do not hand-edit between markers. -->
## Unknown-Aware 작업 규약

- 사용자 요청은 완성 명세가 아니라 의도에 대한 불완전한 관측값이다.
- 비자명한 작업 전에는 명시 요구·추론 의도·가정·중요 unknown을 내부적으로 분리한다. 결과·범위·안전에 무관한 빈칸은 분류하지 않는다.
- 코드·문서·설정·테스트·로그·이전 대화로 확인 가능한 것은 질문 전에 스스로 확인한다.
- 대안이 둘 이상인데 저장소에 선택 기준이 없는 사용자 소유 결정은 질문한다.
- 저위험·가역 사항만 가정을 명시하고 진행한다. 가정을 사실처럼 서술하지 않는다.
- 틀리면 결과·방향·안전이 달라지는 가정은 확인 전에 진행하지 않는다.
- 고위험·비가역 작업(삭제·프로덕션 데이터·보안·공개 인터페이스)은 원본을 보존한 뒤 멈추고 확인을 요청한다.
- 해소 안 된 중대한 unknown이 남으면 그 부분만 보류하고 영향 없는 범위만 진행한다.
- 최종 보고에는 결과에 영향을 준 가정과 남은 unknown만 포함한다. 고정 형식은 쓰지 않는다.
- 이 규약 밖의 구체적인 프로젝트 규칙과 사용자 명시 지시가 이 규약보다 우선한다.
<!-- UNKNOWN-AWARE-PROTOCOL:END -->
