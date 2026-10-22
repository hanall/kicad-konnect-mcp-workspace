# KiCad 회로도 품질 표준 스킬 사용자 가이드·지원 현황

작성 기준: 2026-10-12 KST · 판본: v0.1 candidate · 정본 package: [`skills/kicad-schematic-quality/`](../../skills/kicad-schematic-quality/SKILL.md)

## 0. 결론

현재 정본은 **17파일, package identity `c77ca8ed6783532aaad86496f868f9d22af376c5756c9464c35938bdaf3ce3ca`**다. 요구·전기·시각·증거를 분리하고 `design`, `rewrite`, `change`, `review` 네 모드, 계획 선행 쓰기 guard, native evidence 수집, deterministic 검증, 기존 세 KiCad 스킬의 C01~C13 교정을 한 package로 제공한다.

검증된 범위는 다음과 같다.

- 기존 package 회귀 92개와 문서 안전 회귀 15개를 합친 **107 tests, rc 0**, MCP policy mutation **37/37 검출**
- 최종 정규 `make test` **rc 0**: Rust 합계 2513 통과·0 실패·50 ignored, Python root 190 통과·0 실패
- C1 실제 격리 작성·GUI 왕복 뒤 **현재 c77 deterministic static 재검증 PASS**
- T05 실제 모델 read-only 극성 시험: 잘못된 `Device:LED` 1=A/2=K 거부, 정상 1=K/2=A 극성 sub-gate 인정
- X1 current-c77 실제 작성·GUI 왕복·독립 검토·실입력 변이: **범위 제한 수용**

이 수치는 전체 회로·OS·모델·제조 안전 보장이 아니다. 50 ignored는 통과 수에 포함하지 않으며, C1의 ERC 0도 footprint·PCB·정격·동적 성능·제조·통전 합격을 뜻하지 않는다.

<!-- X1-C77-ACTUAL:START -->
> **X1 / gpt-6-astra(high) / current c77 범위 제한 수용:** 실제 CLI rollout 관측에 결속된 모델이 합성 A4 회로도 5부품·10핀·3망을 작성했다. native 명령과 verifier는 rc 0, ERC error/warning/exclusion 0이며 GUI 저장·닫기·재열기 뒤 최종 SCH SHA는 `fec0092cb81f57ca5e9d700a40978fd12503d161ab4079e5dd5120f9e63b522e`다. 독립 43대조의 차단 결함은 0, actual-input 변이 20개는 거부되고 control·GREEN2 2개는 통과했다. 이는 아래 공개 제한을 전제로 한 인계 receipt이며 보편 성공이 아니다.
<!-- X1-C77-ACTUAL:END -->

<!-- STANDARD-QUALITY-CLOSEOUT:START -->
> **문서 인계 판정:** 관측된 KiCad 10.0.6·Konnect `0.13.0+hanall.1`·package c77·C1/T05/X1 과제 조합의 **범위 제한 인계**다. package는 v0.1 candidate를 유지하며 실물·모든 모델·모든 회로·제조 안전을 보장하지 않는다. 새 프로젝트에서는 입력 계약·도구 버전과 실행 증거를 새로 결속해야 한다.
<!-- STANDARD-QUALITY-CLOSEOUT:END -->

## 1. 정본 구조와 책임 경계

```text
skills/kicad-schematic-quality/
|-- SKILL.md
|-- references/
|-- profiles/
|-- assets/
`-- scripts/
    |-- package_identity.py
    |-- guarded_mcp.py
    |-- collect_evidence.py
    `-- verify_quality.py

.claude/skills/kicad-schematic-quality -> ../../skills/kicad-schematic-quality
.agents/skills/kicad-schematic-quality -> ../../skills/kicad-schematic-quality
```

두 host 진입점은 복사본이 아니라 같은 정본을 가리키는 **상대 symlink**다. 프로젝트 요구·승인·원문·실제 runtime schema가 package의 일반 방법보다 구체적인 권위를 가진다. package는 GUI 편집, commit, push, 제조, 통전 권한을 부여하지 않는다.
회로 시뮬레이션(ngspice·LTspice·Qucs-S)은 이 package의 관문이 아니다. 별도 정본 [`skills/kicad-simulation/`](../../skills/kicad-simulation/SKILL.md)과 [시뮬레이터 설치 계약](20261022-172859_circuit-simulators-linux.md)·[시뮬레이션 MCP 도구 계약](20261022-172859_simulation-mcp-tools.md)이 소유한다. 두 package는 같은 상대 symlink 방식으로 노출하지만 identity·receipt·지원 현황은 package별로 분리하며, 시뮬레이션 결과는 이 package의 G0~G5 판정이나 c77 지원 현황을 바꾸지 않는다. 회로도에 Sim 모델 필드를 쓰는 작업은 CAD 쓰기이므로 이 package의 모드·계획·단일 작성자 규칙을 먼저 적용한다.

## 2. 설치와 동일성 확인

### 2.1 다른 프로젝트에 설치

`SOURCE_PACKAGE`는 검토·봉인된 배포 package 디렉터리, `TARGET_ROOT`는 대상 Git 프로젝트 root다. 대상 경로가 이미 있으면 덮어쓰지 말고 먼저 기존 소유자와 identity를 확인한다.

```bash
# standard-quality-safe-install
# 호출자가 네 절대경로/값을 먼저 export해야 한다.
# SOURCE_PACKAGE, TARGET_ROOT, EXPECTED_PACKAGE_SHA256, INSTALL_RECEIPT
(
  set -eu
  : "${SOURCE_PACKAGE:?SOURCE_PACKAGE가 필요합니다}"
  : "${TARGET_ROOT:?TARGET_ROOT가 필요합니다}"
  : "${EXPECTED_PACKAGE_SHA256:?EXPECTED_PACKAGE_SHA256이 필요합니다}"
  : "${INSTALL_RECEIPT:?INSTALL_RECEIPT가 필요합니다}"

  fail() { printf '%s\n' "$*" >&2; exit 1; }
  absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
  case "$SOURCE_PACKAGE:$TARGET_ROOT:$INSTALL_RECEIPT" in /*:/*:/*) ;; *) fail '모든 경로는 절대경로여야 합니다' ;; esac
  [ -d "$SOURCE_PACKAGE" ] && [ ! -L "$SOURCE_PACKAGE" ] || fail 'source package가 실제 디렉터리가 아닙니다'
  [ -f "$SOURCE_PACKAGE/SKILL.md" ] && [ ! -L "$SOURCE_PACKAGE/SKILL.md" ] || fail 'source SKILL.md가 없습니다'
  [ -d "$TARGET_ROOT" ] && [ ! -L "$TARGET_ROOT" ] || fail 'target root가 실제 디렉터리가 아닙니다'

  DEST="$TARGET_ROOT/skills/kicad-schematic-quality"
  CLAUDE_ALIAS="$TARGET_ROOT/.claude/skills/kicad-schematic-quality"
  AGENTS_ALIAS="$TARGET_ROOT/.agents/skills/kicad-schematic-quality"
  absent "$DEST" || fail 'canonical destination이 이미 있거나 dangling symlink입니다'
  absent "$CLAUDE_ALIAS" || fail 'Claude alias destination이 이미 있거나 dangling symlink입니다'
  absent "$AGENTS_ALIAS" || fail 'Agents alias destination이 이미 있거나 dangling symlink입니다'
  absent "$INSTALL_RECEIPT" || fail 'install receipt 경로가 이미 있거나 dangling symlink입니다'

  mkdir -p "$TARGET_ROOT/skills" "$TARGET_ROOT/.claude/skills" "$TARGET_ROOT/.agents/skills"
  for parent in "$TARGET_ROOT/skills" "$TARGET_ROOT/.claude" "$TARGET_ROOT/.claude/skills" "$TARGET_ROOT/.agents" "$TARGET_ROOT/.agents/skills" "$(dirname "$INSTALL_RECEIPT")"; do
    [ -d "$parent" ] && [ ! -L "$parent" ] || fail "symlink이 아닌 실제 parent가 필요합니다: $parent"
  done

  SOURCE_SHA="$(python3 "$SOURCE_PACKAGE/scripts/package_identity.py" | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha256"])')"
  [ "$SOURCE_SHA" = "$EXPECTED_PACKAGE_SHA256" ] || fail 'source package SHA가 기대값과 다릅니다'

  cp -a -- "$SOURCE_PACKAGE" "$DEST"
  RECEIPT_TMP="${INSTALL_RECEIPT}.tmp.$$"
  absent "$RECEIPT_TMP" || fail 'receipt 임시경로가 이미 있습니다'
  python3 "$DEST/scripts/package_identity.py" > "$RECEIPT_TMP"
  python3 "$DEST/scripts/package_identity.py" | python3 -c 'import json,sys; e=json.load(open(sys.argv[1],encoding="utf-8")); a=json.load(sys.stdin); c=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False); raise SystemExit(0 if c(e)==c(a) else 1)' "$RECEIPT_TMP" || fail '복사본 identity 재대조 실패'
  absent "$INSTALL_RECEIPT" || fail 'receipt 최종경로가 실행 중 점유됐습니다'
  mv -T -- "$RECEIPT_TMP" "$INSTALL_RECEIPT"

  absent "$CLAUDE_ALIAS" && absent "$AGENTS_ALIAS" || fail 'alias 경로가 실행 중 점유됐습니다'
  ln -s ../../skills/kicad-schematic-quality "$CLAUDE_ALIAS"
  ln -s ../../skills/kicad-schematic-quality "$AGENTS_ALIAS"
  [ "$(readlink -- "$CLAUDE_ALIAS")" = '../../skills/kicad-schematic-quality' ] || fail 'Claude alias 검증 실패'
  [ "$(readlink -- "$AGENTS_ALIAS")" = '../../skills/kicad-schematic-quality' ] || fail 'Agents alias 검증 실패'
)
```

배포 source에는 `__pycache__`, `.pyc`, `.pyo`를 넣지 않는다. identity JSON의 `sha256`이 설치 receipt의 기대값과 같아야 하며, path·size·bytes가 하나라도 달라지면 이전 지원 receipt를 새 package에 승계하지 않는다.

### 2.2 현재 checkout 확인

```bash
python3 skills/kicad-schematic-quality/scripts/package_identity.py
PYTHONDONTWRITEBYTECODE=1 make test-standard-quality
```

현재 기대 identity는 `c77ca8ed...f3ce3ca`, package gate는 기존 92 tests와 설치·원복 문서 안전 15 tests를 합친 **107 tests rc 0**이다. 이 gate는 합성·이식성·정적 contract 회귀이며 실제 CAD 작성 성공을 대신하지 않는다.

## 3. 모드 선택과 실제 사용

| 모드 | 기준 계약 | CAD 쓰기 | 핵심 완료 조건 |
|---|---|---:|---|
| `design` | 요구·원문·실제 pin으로 새 계약 | 승인 범위만 | 선행 계획, 실제 pin, native·시각·증거 |
| `rewrite` | 시작본 부품·pin·net·값·footprint 전단사 | 표현 변경만 | 무승인 전기 변경 0 |
| `change` | 승인된 전후 diff와 영향 범위 | 승인된 차이만 | 영향 시트와 전체 연결 재검증 |
| `review` | 현재 saved/live 상태·요구·증거 | **0** | 관측·결론·제안·unknown 분리 |

쓰기 모드는 [공통 계획 양식](../../skills/kicad-schematic-quality/assets/common-plan.md), 루트 포함 각 회로도의 [페이지 계획 양식](../../skills/kicad-schematic-quality/assets/page-plan.md), `plan-index.json`을 첫 CAD mutation 전에 고정한다. `plan-index.json`은 schema 1, mode, common plan, 모든 schematic-plan mapping, allowlist, read-only files/library refs, `require_all_plans_before_write: true`를 가져야 한다. 검증 정답은 Markdown profile이 아니라 **CAD 쓰기 전에 검토자가 고정한 별도 semantic JSON**이다.

### 3.1 읽기 전용 review

1. `mode: "review"`인 project-local `plan-index.json`을 둔다.
2. `allowed_files`에는 조회할 실제 파일만, `read_only_files`에는 보존할 파일을 정확히 적는다.
3. 현재 runtime에서 확인된 read tool만 JSONL에 넣는다.
4. `guarded_mcp.py`를 실행한다. review mode의 mutation은 guard가 거부해야 한다.
5. saved file과 live editor가 다르면 어느 상태를 읽었는지 기록하고 저장하지 않는다.

```bash
SKILL_DIR=/absolute/path/to/skills/kicad-schematic-quality

python3 "$SKILL_DIR/scripts/guarded_mcp.py" \
  --workspace-root "$WORKSPACE_ROOT" \
  --project-dir "$PROJECT_DIR" \
  --launcher "$LAUNCHER" \
  --config "$CONFIG" \
  --server-cwd "$SERVER_CWD" \
  --expected-version "$EXPECTED_VERSION" \
  --expected-commit "$EXPECTED_COMMIT" \
  --requests "$REQUESTS_JSONL" \
  --evidence-dir "$NEW_EVIDENCE_DIR"
```

요청 JSONL은 임시파일 write → flush/fsync → atomic rename → 부모 fsync → 전체 readback으로 새로 확정한다. timeout·연결 끊김·불명확 응답 뒤에는 실제 객체와 파일 SHA를 먼저 읽고, 과거 request를 그대로 반복하지 않는다.

### 3.2 native evidence와 deterministic 검증

```bash
python3 "$SKILL_DIR/scripts/collect_evidence.py" \
  --project-root "$PROJECT_ROOT" \
  --root-schematic "$ROOT_SCHEMATIC" \
  --registry "$REGISTRY" \
  --registry-sha256 "$REGISTRY_SHA256" \
  --profile-id "$PROFILE_ID" \
  --output-dir "$NEW_OUTPUT_DIR" \
  --kicad-cli "$KICAD_CLI" \
  --pdf-text-tool "$PDFTOTEXT" \
  --launcher "$LAUNCHER" \
  --config "$CONFIG" \
  --server-cwd "$SERVER_CWD" \
  --expected-version "$EXPECTED_VERSION" \
  --expected-commit "$EXPECTED_COMMIT"

python3 "$SKILL_DIR/scripts/verify_quality.py" \
  --project-root "$PROJECT_ROOT" \
  --registry "$REGISTRY" \
  --registry-sha256 "$REGISTRY_SHA256" \
  --contract "$RUNTIME_CONTRACT" \
  --netlist "$NATIVE_KICADXML" \
  --layout "$LAYOUT_JSON" \
  --erc "$ERC_JSON" \
  --pdf "$NATIVE_PDF" \
  --report "$NEW_REPORT" \
  --pdf-text-tool "$PDFTOTEXT"
```

`collect_evidence.py`는 native XML 형식을 `kicadxml`로 명시하고 raw rc와 SHA를 보존한다. `verify_quality.py`의 PASS는 요구된 정적 contract와 PDF 구조 범위다. 실제 glyph 전페이지 판독, GUI 왕복, 동적 회로, PCB·제조·통전은 별도 관문이다.

## 4. 지원 현황

| 대상 | package | 증거 유형 | 현재 상태 | 지원 한계 |
|---|---|---|---|---|
| package identity·두 alias·이식성 | c77 | 실제 파일·symlink·별도 cwd | <span>검증됨</span> | 다른 설치 위치는 새 identity receipt 필요 |
| guard·collector·verifier·문서 안전 계약 | c77 | 기존 92 + 신규 15 = 107 local tests | 검증됨 | 실제 CAD 전체 성공이 아닌 contract 회귀 포함 |
| `PWR_FLAG` 자동 삽입 | c77 | 4개 삽입 경로 fail-closed | **미지원** | source 승인 schema가 없어 유효 근거를 주장해도 adapter 통과 불가 |
| MCP policy mutation | c77 | 37/37 검출 | 검증됨 | FakeTransport·가짜 STDIO 중심, native 작성과 구분 |
| 최종 정규 기본 local gate | current source | `make test` rc 0 | 검증됨 | Rust 2513/0/50 ignored + Python 190/0; ignored 합산 금지 |
| C1 실제 작성 | b274 authoring | Claude 실제 모델·MCP·native·GUI | 제한 검증 | 원 작성판 b274; 완전 무실패 아님 |
| C1 current 재검증 | c77 | actual native input·정적 검증·실제 입력 변이 | 제한 검증 | c77 작성 성공이 아니라 c77 검증기 재검증 |
| C1 전페이지 시각 | 저장본 | GUI 왕복·작성자/독립 판독 | 제한 검증 | 단순 1쪽 RC fixture, 모든 회로로 일반화 금지 |
| T05 LED 극성 G0 | c77 | 실제 Claude read-only 두 입력 | 제한 검증 | 단일 installed `Device:LED`, CAD 작성 0, 응답 형식 편차 2건 |
<!-- X1-C77-ACTUAL-ROW:START -->
| X1 실제 작성 | c77 | gpt-6-astra(high) 실제 CLI·native·GUI·독립검토·변이 | **범위 제한 수용** | 최종 SCH `fec0092...b522e`; 합성 1쪽 과제와 공개 제한에만 결속 |
<!-- X1-C77-ACTUAL-ROW:END -->
| 회로 시뮬레이션 관문 | 해당 없음(c77 범위 밖) | 이 package 회귀·receipt 없음 | **미실행** | 엔진 설치·MCP 중계는 [시뮬레이터 설치 계약](20261022-172859_circuit-simulators-linux.md)·[시뮬레이션 MCP 도구 계약](20261022-172859_simulation-mcp-tools.md)과 `kicad-simulation` receipt로만 판단; C1·T05·X1에 승계 금지 |
| PCB·정격·동적·제조·통전·인증 | 해당 없음 | 미수행 또는 범위 밖 | 미지원 | 별도 설계·시험·승인 필요 |

관측 조합은 KiCad 10.0.6과 Konnect `0.13.0+hanall.1` commit `94f80350cf67db27b179a06a8f6dbebfe4717927`이다. 다른 OS·KiCad·Konnect·model·회로 유형은 동일 package SHA의 별도 receipt가 생기기 전에는 미지원이다.

## 5. 기존 세 스킬의 C01~C13 교정

정본은 [legacy-skill-overrides.md](../../skills/kicad-schematic-quality/references/legacy-skill-overrides.md)다.

| ID | portable 교정 |
|---|---|
| C01 | 고정 tool 수·서명 대신 현재 build와 fresh schema를 먼저 확인 |
| C02 | `design/rewrite/change/review`와 권한을 분리, review 쓰기·저장 0 |
| C03 | local 기능 흐름은 실선 우선, wire 없는 label 기본값은 완료로 인정 금지 |
| C04 | exact MPN/package lead·symbol pin·footprint pad·drawing view 결속 |
| C05 | 실제 power source 근거가 필요하지만 c77 adapter에는 승인 schema가 없어 자동 `PWR_FLAG` 삽입 자체가 현재 미지원 |
| C06 | ERC는 owning root에서 hierarchy 전체 검사, child 결과 승격 금지 |
| C07 | `run_design_review`·`audit_*` aggregate가 direct ERC/connectivity를 대체하지 않음 |
| C08 | schematic 근접과 PCB 물리 거리를 분리 |
| C09 | 전압·전류·sequence·정격은 profile·원문·계산의 별도 증거 |
| C10 | offline schematic atomic commit과 live PCB `save_project` 의미를 분리 |
| C11 | 미실행·partial·불가능한 0·source 불일치는 `INCOMPLETE` |
| C12 | ERC/DRC/limited audit/READY를 제조·발주 승인으로 확대 금지 |
| C13 | symbol query 성공과 physical pin inventory 완전성을 분리 |

전수 감사는 외부 7파일 전부와 78개 절·rule group을 확인해 차단 11개, 교정 13개, 후속 시험 16개를 도출했다. 글로벌 원문은 수정하지 않았고 이 package의 portable overlay와 프로젝트 routing이 우선한다.

## 6. 실제·모의 증거를 구분해 읽는 법

| 증거 | 실제인 것 | 증명하지 않는 것 |
|---|---|---|
| 107 tests | 기존 92 parser·path·identity·policy·contract + 신규 15 설치·원복 문서 안전 회귀 | 실제 GUI/CAD 전체 동작 |
| 37 mutation | MCP guard의 거부 조건 | native 전기·시각 품질 |
| C1 actual | 실제 모델 작성, native export, GUI 저장·재열기, 독립 판독 | 모든 회로·정격·제조 안전 |
| C1 c77 | current verifier가 actual native C1과 변이를 판정 | current c77로 새 CAD를 작성했다는 주장 |
| T05 | 실제 모델이 잘못된 LED pin 계획을 거부하고 정상 극성만 인정 | LED 회로 작성·동작 성공 |
| X1 | current c77로 실제 CLI 작성, GUI 왕복, 독립 43대조, actual-input 변이 20거부·control 2통과 | 제품 회로·실물 package·정격·동적·제조 안전 |
| 기본 `make test` | 현재 checkout의 정규 local gate rc 0 | 50 ignored 항목 또는 live 장비 성공 |

T05 두 응답은 JSON을 Markdown code fence로 감싼 형식 편차가 있다(`format_instruction_exact_pass=false`). 극성 의미 판정만 수용하며 형식까지 무결하다고 주장하지 않는다.

## 7. ERC·ignored·제조 경계

C1 native ERC는 error 0, warning 0, exclusion 0이었다. 기본 비활성 4종은 `footprint_filter`, `four_way_junction`, `simulation_model_issue`, `single_global_label`이며 숨기지 않는다. 별도 actual review의 `run_design_review`는 네 부품의 footprint가 비어 있어 **4 errors / NOT READY**를 반환했다. 이는 정적 회로 fixture 계약에는 맞지만 PCB·제조 준비가 끝나지 않았다는 올바른 경계다.
`simulation_model_issue`가 기본 비활성이므로 ERC 0은 Sim 모델 지정의 완전성이나 시뮬레이션 가능성을 뜻하지 않는다. 시뮬레이션 전 모델 누락·include 누락은 `kicad-simulation` 절차의 SPICE netlist 진단으로 따로 닫는다. 이 ERC 규칙을 켜야 한다면 프로젝트 ERC 설정 변경을 승인된 GUI 채널로 수행하고 새 CAD SHA로 G3를 다시 실행한다.

현재 c77 guard는 `PWR_FLAG` source 승인을 표현·검증할 machine-readable schema가 없다. 따라서 `add_power_symbol`, 단일 component 배치, batch 배치, component 교체의 네 자동 삽입 경로를 모두 fail-closed로 거부한다. 단순히 “유효한 source 근거가 있다”고 요청에 적어도 adapter를 통과하지 않는다. 권한을 우회하거나 raw CAD를 고치지 말고, 프로젝트가 별도로 승인한 GUI 경로를 사용하거나 source 승인 계약을 후속 개발한 뒤 새 시험·receipt를 만들어야 한다.

정규 기본 gate의 Rust 결과에서 **50 ignored**는 Java, live KiCad IPC, 실제 `kicad-cli`, 수동 GUI 등 별도 환경을 요구해 실행되지 않았다. 따라서 `2513 pass + 50 ignored`를 2563 pass로 쓰지 않는다. 제조 완료에는 최소한 footprint·PCB DRC·closed outline·drill/pad·BOM/CPL·Gerber/drill·order preview·안전 검토와 사람의 명시 승인이 별도로 필요하다.

또한 실제 다중 hierarchy child ERC 거부, 멀리 배치한 실제 PCB capacitor, 실제 current/voltage mismatch, 실제 via-in-pad/acid-trap, `READY`이지만 BOM/CPL/Gerber/drill/preview가 빠진 exact fixture는 실행하지 않았다. 확인된 것은 actual audit의 `pcb_distance_checked=false`·NOT READY 같은 제한을 보존하고, 해당 범위를 `checked`로 승격하는 claim mutation을 거부한 사실이다. 이를 표준의 전체 기능 무결성이나 각 detector의 실제 결함 검출 성능으로 확대하지 않는다.

### X1 독립 시각·증거 경계

X1의 독립 시각 판정 정본은 **후보 설명을 읽기 전 1단계 blind 관측을 SHA로 봉인한 결과**다. 2단계에서 `roundtrip.json`의 `visual_root`·`title_block` 설명이 노출된 뒤의 판독은 보충으로 분리했고 blind 답안으로 승계하지 않았다. GUI 전후 layout geometry와 XML semantic은 같고 동일 옵션의 300 dpi ink raster는 byte-identical이었다. 반면 PDF text-layer의 17단어 bbox는 exact 차이가 있었고, CAD `Reference`/`Value` field 원문 좌표 bytes의 직접 전후 대조는 하지 않았다. 따라서 “모든 PDF bytes 동일” 또는 “CAD field 원문 동일”이라고 주장하지 않는다.

X1 actual review는 footprint 5개 미할당으로 **5 errors / NOT READY**이며, 표제란 Title/Date/Rev는 공백이다. 본문 `sense-filter`는 보이지만 표제란 완성이나 제조 준비를 대신하지 않는다. PCB·정격·동적 성능·제조·통전·인증·실물 안전은 계속 미완이다.

## 8. 원 FAIL과 최신 기본 재실행

타입 봉합 뒤 첫 정규 `make test`는 upstream test `open_project_says_kicad_answered_when_it_answered_with_an_error`의 mock port bind에서 `AddressInUse`로 rc 2였다. Rust 결과는 1770 pass, 1 fail, 23 ignored에서 중단됐다. 독립 진단은 fixture의 임시 TCP port 예약 공백에서 같은 원인의 경합을 재현했지만 upstream source는 수정하지 않았다.

그 뒤 source 무수정·기본 병렬 설정 그대로 실행한 역사 재실행은 Rust 2513 pass, 0 fail, 50 ignored와 당시 Python root **175 pass**로 rc 0이었다. 문서 안전 15 tests가 공개 gate에 추가된 뒤의 **최종** `make test`도 rc 0이며 Rust 2513/0/50 ignored, Python root **190/0**이다. 최종 `make test-standard-quality`는 core 92 + docs 15 = 107/0이다. `make verify`, runtime verify, skill quick validation도 각각 rc 0이다. 최신 통과를 원 fixture 취약성 수정으로 표현하지 않고, 원 FAIL 로그와 진단을 함께 보존한다.

```bash
PYTHONDONTWRITEBYTECODE=1 make test
```

## 9. 보호 경계

실제 모델 검증은 원 제품 checkout과 사용자 global skill·memory를 가리고 package·oracle은 read-only, 과제별 출력만 쓰기 가능하도록 격리했으며 API key 환경·MCP·GUI 권한을 요청 범위에 맞게 제거했다. 자격증명 값·개인 계정 식별정보·관리형 계정 내부 구현·실행 binary 사본은 이 문서와 인도 package에 포함하지 않는다. 이 보호 검증은 회로의 전기·제조 적합성 증거가 아니라 입력·쓰기 범위가 분리됐다는 운영 증거다.

## 10. 원복

### 10.1 두 신규 alias만 정확히 제거

아래 명령은 대상이 정확히 `../../skills/kicad-schematic-quality`인 symlink일 때만 제거한다. 다른 link나 디렉터리는 건드리지 않는다.

```bash
# standard-quality-safe-alias-rollback
(
  set -eu
  : "${TARGET_ROOT:?TARGET_ROOT가 필요합니다}"
  fail() { printf '%s\n' "$*" >&2; exit 1; }
  case "$TARGET_ROOT" in /*) ;; *) fail 'TARGET_ROOT는 절대경로여야 합니다' ;; esac
  [ -d "$TARGET_ROOT" ] && [ ! -L "$TARGET_ROOT" ] || fail 'target root가 실제 디렉터리가 아닙니다'

  CLAUDE_ALIAS="$TARGET_ROOT/.claude/skills/kicad-schematic-quality"
  AGENTS_ALIAS="$TARGET_ROOT/.agents/skills/kicad-schematic-quality"
  for link in "$CLAUDE_ALIAS" "$AGENTS_ALIAS"; do
    [ -L "$link" ] || fail "예상 symlink가 아닙니다: $link"
    [ "$(readlink -- "$link")" = '../../skills/kicad-schematic-quality' ] || fail "다른 target의 alias입니다: $link"
  done
  unlink -- "$CLAUDE_ALIAS"
  unlink -- "$AGENTS_ALIAS"
)
```

### 10.2 복사한 canonical package 제거

설치 receipt와 현재 `package_identity.py` 결과가 **JSON 타입까지 엄밀히 동일**하고 대상이 이 설치에서 새로 복사한 폴더임을 확인한 뒤에만 원복용 새 경로로 이동한다. 수정된 package는 제자리에 보존하고 실패한다. 삭제보다 이동을 우선하며, backup 경로가 이미 있거나 dangling symlink이면 덮어쓰지 않는다.

```bash
# standard-quality-safe-package-rollback
# 호출자가 TARGET_ROOT, INSTALL_RECEIPT, ROLLBACK_BACKUP을 먼저 export한다.
(
  set -eu
  : "${TARGET_ROOT:?TARGET_ROOT가 필요합니다}"
  : "${INSTALL_RECEIPT:?INSTALL_RECEIPT가 필요합니다}"
  : "${ROLLBACK_BACKUP:?ROLLBACK_BACKUP이 필요합니다}"
  fail() { printf '%s\n' "$*" >&2; exit 1; }
  absent() { [ ! -e "$1" ] && [ ! -L "$1" ]; }
  case "$TARGET_ROOT:$INSTALL_RECEIPT:$ROLLBACK_BACKUP" in /*:/*:/*) ;; *) fail '모든 경로는 절대경로여야 합니다' ;; esac

  PACKAGE="$TARGET_ROOT/skills/kicad-schematic-quality"
  PACKAGE_PARENT="$TARGET_ROOT/skills"
  BACKUP_PARENT="$(dirname "$ROLLBACK_BACKUP")"
  [ -d "$TARGET_ROOT" ] && [ ! -L "$TARGET_ROOT" ] || fail 'target root가 실제 디렉터리가 아닙니다'
  [ -d "$PACKAGE_PARENT" ] && [ ! -L "$PACKAGE_PARENT" ] || fail 'package parent가 실제 디렉터리가 아닙니다'
  [ -d "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || fail 'canonical package가 실제 디렉터리가 아닙니다'
  [ -f "$PACKAGE/SKILL.md" ] && [ ! -L "$PACKAGE/SKILL.md" ] || fail 'canonical SKILL.md가 없습니다'
  [ -f "$INSTALL_RECEIPT" ] && [ ! -L "$INSTALL_RECEIPT" ] || fail '원 install receipt가 없거나 symlink입니다'
  [ -d "$BACKUP_PARENT" ] && [ ! -L "$BACKUP_PARENT" ] || fail 'backup parent가 실제 디렉터리가 아닙니다'
  absent "$ROLLBACK_BACKUP" || fail 'backup 경로가 이미 있거나 dangling symlink입니다'
  case "$ROLLBACK_BACKUP" in "$PACKAGE"|"$PACKAGE"/*) fail 'backup은 package 밖의 새 경로여야 합니다' ;; esac

  python3 "$PACKAGE/scripts/package_identity.py" | python3 -c 'import json,sys; e=json.load(open(sys.argv[1],encoding="utf-8")); a=json.load(sys.stdin); c=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False); raise SystemExit(0 if c(e)==c(a) else 1)' "$INSTALL_RECEIPT" || fail 'install receipt와 현재 package identity가 다릅니다; 원본을 보존합니다'

  absent "$ROLLBACK_BACKUP" || fail 'backup 경로가 실행 중 점유됐습니다'
  mv -T -- "$PACKAGE" "$ROLLBACK_BACKUP"
  [ ! -e "$PACKAGE" ] && [ ! -L "$PACKAGE" ] || fail '원 package 경로가 남았습니다'
  [ -d "$ROLLBACK_BACKUP" ] && [ ! -L "$ROLLBACK_BACKUP" ] || fail 'backup 이동 검증 실패'
)
```

전역 `~/.claude/skills/konnect`, `kicad-schematic`, `kicad-review`, 사용자 계정 설정, 기존 CAD, 다른 프로젝트 파일은 원복 대상이 아니다. broad `rm`, global skill 덮어쓰기, 살아 있는 lock 삭제를 하지 않는다.

## 11. 추적 가능한 근거

일반 Git에 보존한 정본 증거는 [검증 근거 색인](../검증/20261012-standard-quality/README.md)의 공통·C1·X1 압축/manifest에서 확인한다. 아래 `.artifacts/` 링크는 개발 호스트의 상세 조회용이며 다른 checkout에서는 보존 묶음 내부 경로로 대조한다.

최종 인계 정본은 이 가이드와 새 package다. `.artifacts/`는 로컬 상세 evidence와 재현 환경이며 배포 package의 실행 의존성이 아니다.

| 근거 | 경로 |
|---|---|
| 구축·검증 계획 | [표준화 계획](20261012-040121_schematic-quality-standardization-plan.md) |
| 외부 7파일 전수 감사 | [source-audit README](../../.artifacts/20261012-040121-standard-quality/source-audit/README.md) |
| 92 tests | [root-type-green2.txt](../../.artifacts/20261012-040121-standard-quality/root-type-green2.txt) |
| 37 MCP mutation | [mcp final manifest](../../.artifacts/20261012-040121-standard-quality/mcp-dev/final-manifest.json) |
| c77 strict type·C1 actual 재검증 | [독립 감사 README](../../.artifacts/20261012-040121-standard-quality/strict-type-independent/README.md) |
| C1 c77 static report | [static-report.json](../../.artifacts/20261012-040121-standard-quality/isolation/case/project/evidence/root-type-fixed/static-report.json) |
| C1 GUI 왕복 | [roundtrip.json](../../.artifacts/20261012-040121-standard-quality/gui-evidence/roundtrip.json) |
| C1 actual review·제조 경계 | [response-0005.json](../../.artifacts/20261012-040121-standard-quality/isolation/case/project/evidence/root-actual-review/responses/response-0005.json) |
| T05 실제 모델 G0 | [T05 README](../../.artifacts/20261012-040121-standard-quality/polarity-g0/README.md) |
| 원 full FAIL | [root-full-test-type-fixed.txt](../../.artifacts/20261012-040121-standard-quality/root-full-test-type-fixed.txt) |
| 최신 기본 전체 rc 0 | [full-default-rerun receipt](../../.artifacts/20261012-040121-standard-quality/upstream-flake-probe/full-default-rerun.receipt.md) |
| 최종 C/T 지원·잔여 제약 감사 | [final-audit README](../../.artifacts/20261012-040121-standard-quality/final-audit-closeout/README.md) |
| X1 범위 제한 closeout | [x1-closeout.json](../../.artifacts/20261012-040121-standard-quality/x1-closeout.json) |
| X1 CLI model 관측 | [model-observation.public.json](../../.artifacts/20261012-040121-standard-quality/x1-managed/model-observation.public.json) |
| X1 독립 판정 | [VERDICT.json](../../.artifacts/20261012-040121-standard-quality/x1-independent/VERDICT.json) · [독립 검토 보고서](../../.artifacts/20261012-040121-standard-quality/x1-independent/20261012-063207_x1-independent-review.md) |
| X1 actual-input 변이 | [run-01-result.json](../../.artifacts/20261012-040121-standard-quality/x1-input-mutations/run-01-result.json) |
| 최종 107 standard tests | [log](../../.artifacts/20261012-040121-standard-quality/final-standard-tests.txt) · [rc](../../.artifacts/20261012-040121-standard-quality/final-standard-tests.rc) |
| 최종 full gate 2513+190 | [stdout](../../.artifacts/20261012-040121-standard-quality/final-full-test.txt) · [stderr](../../.artifacts/20261012-040121-standard-quality/final-full-test.stderr) · [rc](../../.artifacts/20261012-040121-standard-quality/final-full-test.rc) |
| 최종 verify·runtime·skill | [verify](../../.artifacts/20261012-040121-standard-quality/final-verify.txt)·[rc](../../.artifacts/20261012-040121-standard-quality/final-verify.rc) · [runtime](../../.artifacts/20261012-040121-standard-quality/final-runtime-verify.txt)·[rc](../../.artifacts/20261012-040121-standard-quality/final-runtime-verify.rc) · [skill](../../.artifacts/20261012-040121-standard-quality/final-skill-validation.txt)·[rc](../../.artifacts/20261012-040121-standard-quality/final-skill-validation.rc) |
| C1 추적 가능 archive 1 | [allowlist.json](../../.artifacts/20261012-040121-standard-quality/c1-handover-selection/allowlist.json) |
| C1 추적 가능 archive 2 | [selection-receipt.json](../../.artifacts/20261012-040121-standard-quality/c1-handover-selection/selection-receipt.json) |
| C1 추적 가능 archive 3 | [reproduction-commands.json](../../.artifacts/20261012-040121-standard-quality/c1-handover-selection/reproduction-commands.json) |

지원 판정은 항상 package SHA, host/model, KiCad/Konnect version, 과제 범위가 같은 receipt에 한정한다.
