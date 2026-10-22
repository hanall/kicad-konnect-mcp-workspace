# 검증·증거·지원 판정

이 문서는 deterministic 검사, 사람의 시각 판독, 증거 결속, 지원 상태를 분리한다.

## 서로 대체하지 않는 네 축

| 축 | 주요 증거 | 단독으로 증명하지 못하는 것 |
|---|---|---|
| 요구 적합성 | 요구-시트-증거 대응, 보존·비대상 계약 | 말하지 않은 요구 충족 |
| 전기적 정적 정확성 | 원문 pin, native netlist, ERC, semantic 검사 | 동적 안정성·정격·실물 안전 |
| 시각적 이해 가능성 | GUI/PDF 전페이지·확대, 읽기 과제 | 자동 문자 검사만으로 가독성 보장 |
| 증거·재현성 | CAD·입력·도구 SHA, argv, 원 rc, receipt | 변경 뒤 과거 PASS 재사용 |

한 축의 PASS로 다른 축의 FAIL 또는 unknown을 상쇄하지 않는다.

## G0~G5 관문

### G0 범위·보존

모드, 대상·비대상, 권한, 작성 채널, 단일 작성자, saved/live 상태, plan-index와 원문·계획 SHA, capability·unknown을 확인한다. 불명확하면 쓰지 않는다.

### G1 핀·전기

ref/unit/물리 pin 집합, 실제 pin type·극성, 값·footprint, net membership, 공급·반환·절연 경계를 검사한다. `design` 원문 계약, `rewrite` 전단사, `change` 승인 diff 중 선택한 oracle과 비교한다.

### G2 실선·페이지

계획의 wire-only 연결, junction·교차·예상 밖 연장·short, 양쪽 page port, 반복 channel과 부유/Kelvin return 분리를 검사한다. label은 빠진 실선을 숨기는 수단이 아니다.

### G3 저장·ERC

실제 승인 채널로 저장하고 재열기 한 뒤 fresh native export를 만든다. ERC 오류·경고를 개별 ref/pin/net/원인/근거로 대조하고 개별 제외와 기본 비활성 규칙을 모두 공개한다. 경고 총개수만 비교하거나 누락 결과를 0으로 세지 않는다.

ERC는 owning root schematic에서 hierarchy 전체를 대상으로 실행한다. child sheet 단독 결과를 전체 ERC로 올리지 않는다. aggregate review는 ERC와 직접 connectivity 검사를 대신하지 않으며, 필수 검사 미실행·부분 실패·source 불일치·모순 미해결은 `INCOMPLETE`다.

### G4 시각·읽기

모든 페이지의 GUI와 native PDF 전체·필요 확대, 필수 읽기 과제, 문자획 관통·잘림을 판독한다. PDF 구조·text 경계·bbox 검사는 전페이지 실제 glyph 판독을 대신하지 않는다.

### G5 통합·증거

요구, 시트, 부품 소유, port 범위의 누락을 대조한다. CAD/library/계획/registry/semantic/runtime/검증기/산출물의 SHA, 생성 source, argv, 원 rc, version·commit, 예외·미확정·미검증 범위를 receipt에 결속한다.

## oracle과 후보 분리

- registry는 schema 1이며 `project-root` 기준 상대경로와 검토된 SHA를 가진다.
- semantic 계약은 schema 2이며 CAD 쓰기 전에 검토자가 고정한 기대값이다.
- runtime 계약은 schema 2이며 후보 CAD와 native 산출물의 hash·provenance를 담는다.
- 이 표준판의 runtime schema 2는 `producer_package_identity`와 `producer_plan_binding`을 필수로 가지며, 현재 동일 패키지 전체 identity와 동일 `ProjectPolicy`의 plan-index·공통/페이지 계획 SHA에 exact 결속되지 않으면 검증을 실패한다.
- 작성자는 후보 결과에서 registry·semantic 기대값을 재작성하지 않는다.
- `--registry-sha256`은 호출자가 검토·고정한 registry bytes SHA-256이어야 한다.

Markdown profile은 계획과 수치 선택 지침이다. 검증기의 정답은 별도 semantic JSON이다. profile 문구를 parser의 숨은 정답으로 사용하지 않는다.

## package identity

검증 실행 전 실제 `SKILL_DIR`의 전체 정본 identity를 생성한다.

```bash
python3 "$SKILL_DIR/scripts/package_identity.py"
```

표준 출력 JSON의 `sha256`은 cache를 제외한 패키지 정본 문서·reference·asset·profile·script 전부를 상대 path, size, bytes로 결속한다. 개별 파일 SHA 몇 개나 Git commit만으로 이를 대신하지 않는다. JSON 전체를 실행 receipt에 보존하고, `guarded_mcp.py`, `collect_evidence.py`, `verify_quality.py`가 기록한 package identity와 같은지 대조한다.

정본 파일의 path·size·bytes가 하나라도 바뀌면 package SHA도 달라진다. 이전 receipt는 이전 SHA의 증거로 동결하고, 변경 영향에 해당하는 RED→GREEN→mutation→GREEN2, native evidence 수집, deterministic 검증을 새 SHA로 다시 실행한다. 문서만 바뀌었다는 이유로 과거 지원 결과를 새 SHA에 자동 승계하지 않는다.

## deterministic 검증 CLI

실제 package 경로를 `SKILL_DIR`로 두고, caller가 고정한 값을 모두 명시한다.

```bash
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

`--pdf-text-tool`은 선택 인자다. 사용할 때에는 실제 executable 경로를 명시한다. netlist는 확장자에 의존하지 않고 KiCad native export에서 `kicadxml` 형식을 명시해 생성하고 XML parser로 확인한다.

검증 결과는 회로 정적 계약과 PDF 구조 범위에 한정한다. `pdftotext`의 구조·문자 경계 검사는 색상, glyph 획, 도형 내부, 전페이지 시각 품질을 증명하지 않는다.

## native evidence 수집 CLI

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
```

필요하면 검토한 GUI 왕복 등 외부 영수증 JSON을 `--companion-receipts`로 명시한다. receipt가 없으면 도구가 GUI 저장·닫기·재열기를 수행했다고 합성하지 않는다. output은 새 디렉터리여야 하며 기존 결과에 덮어쓰지 않는다.

## RED에서 GREEN2까지

검증기 또는 계약을 바꾸면 다음을 분리해 보존한다.

```text
원인 재현 RED -> 정상본 GREEN -> 같은 원인 mutation 거부 -> 오염되지 않은 GREEN2
```

변이는 export 사본이나 승인된 격리 시험물에만 적용한다. 생산 CAD를 텍스트로 깨뜨리지 않는다. assertion 완화, allowlist 확대, expected 값의 후보 기반 재생성으로 GREEN을 만들지 않는다. 원 FAIL 입력·SHA·원 rc를 보존한다.

## 증거 최소 필드

- package SHA와 대상 CAD/library/plan/원문 SHA
- registry SHA와 semantic/runtime 계약 SHA
- tool/KiCad/plugin/host/model 식별값
- 각 argv, 시작·종료 시각, 원 rc, stdout/stderr 또는 report
- native XML/PDF/ERC/layout의 생성 source·format·SHA
- saved/live와 GUI roundtrip의 실제 여부
- deterministic·mutation·GREEN2 결과
- 페이지별 자체/독립 검토와 읽기 과제
- 개별 ERC 경고·제외·비활성 규칙
- 예외·unknown·미검증 범위와 다음 결정 주체

## 완료와 지원 상태

범위 안에서 미대응 요구, 미검토 페이지, 전기 계약 오류, 무승인 차이, 설명 없는 경고·예외, 시각 차단 결함, 실패한 필수 읽기 과제, stale·누락 증거가 모두 0일 때만 해당 범위 완료를 말한다. 범위 밖 unknown은 별도 목록으로 남긴다.

정상적으로 생성될 수 없는 0, 실행하지 않은 검사의 0, aggregate가 다루지 않은 항목의 0을 PASS로 쓰지 않는다. coverage가 부족하면 판정은 `INCOMPLETE`이며 다른 검사 성공으로 메우지 않는다.

v0.1 candidate의 지원은 외부 호출 프로젝트가 남긴 receipt와 정확히 같은 package SHA, host/model, tool version·commit, 과제 범위에만 결속한다. core 문서에 시험 횟수나 PASS 수를 나중에 삽입하지 않는다. package SHA가 바뀌면 이전 receipt는 이전 판본 근거로 동결하며 새 판본 성공으로 자동 승계하지 않는다.
