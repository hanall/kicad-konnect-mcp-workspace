# 도구 호환성과 안전한 호출

이 문서는 MCP·GUI·CLI의 실제 능력과 안전한 실패 처리를 소유한다. 특정 설치 위치, DISPLAY, port, 고정 도구 수를 공통값으로 두지 않는다.

## caller가 명시할 환경

- `workspace-root`, `project-dir`
- 검증된 launcher와 config 경로
- server cwd
- 기대 server version·commit
- 요청 JSONL과 새 evidence 디렉터리
- timeout을 바꿀 때 그 근거
- GUI를 쓸 경우 프로젝트 권위의 승인, 실제 instance/display/window/document, saved 상태와 lock

하나라도 필수인데 없으면 추측하지 않는다. 조회·계획까지만 진행하고 누락 입력을 요청한다.

## 현재 schema가 정본

고정된 도구 이름·개수·toolset 목록을 신뢰하지 않는다. launcher가 연 현재 연결에서 initialize, installation 정보, `tools/list`를 확인하고 기대 version·commit·실행 경로와 대조한다. 쓰기는 현재 schema에서 확인된 정확한 tool 이름, required field, type, `additionalProperties` 정책과 plan-index 경로 범위에만 허용한다.

metadata-only 요청에서 필요한 toolset이 비어 있으면 빈 `load_toolset` 호출을 만들지 않는다. metadata 성공은 CAD 조회·쓰기 capability 성공이 아니다. batch 응답 wrapper와 readback shape도 현재 schema에서 확인한다.

도구 응답의 `isError=false`도 내용 완전성을 보장하지 않는다. symbol 조회에서 pin 수 0, 빈 pin 목록, unit·상속 누락이 보이면 `INCOMPLETE`로 두고 current library source·대안 API·정확한 package 자료·배치본 endpoint를 확인한다. schema에 `unit_count` 같은 필드가 항상 존재한다고 가정하지 않는다.

## guarded MCP 실행

요청 파일은 한 줄에 `{"tool":"...","arguments":{...}}` 한 객체인 UTF-8 JSONL이다. 매 시도마다 새 파일을 임시파일 write, flush/fsync, atomic rename, 부모 디렉터리 fsync, 전체 readback으로 확정하고 SHA-256을 기록한다.

```bash
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

필요한 경우에만 `--timeout`을 추가한다. `project-dir`은 `workspace-root` 안의 실제 디렉터리여야 한다. evidence 경로는 새 디렉터리여야 한다. 요청은 adapter가 허용한 회로도 조회·작성 범위에 한정하며 PCB·제조·설정 변경을 우회 통과시키지 않는다.

`plan-index.json`의 `mode: review`는 모든 mutation을 거부해야 한다. 다른 쓰기 모드도 모든 회로도 계획과 common plan, `require_all_plans_before_write: true`, 쓰기 allowlist가 일치해야 한다. `read_only_files`는 조회할 수 있어도 쓰지 못한다. `read_only_library_refs`는 설치 source 조회와 project-scope 참조만 허용하고 외부 library 수정·삭제·global 등록을 허용하지 않는다.

## 채널별 규칙

### MCP

- 프로젝트가 지정한 launcher/config/server cwd로만 새 연결을 연다.
- 시작 전 version·commit을 대조하고 요청 도구의 현재 schema를 봉인한다.
- 쓰기 직전 plan-index·계획 SHA·lock·allowlist를 다시 확인한다.
- 응답 성공 뒤 대상 객체와 파일 SHA를 readback한다.
- 이름에 `save`가 있어도 회로도 저장인지 PCB/IPC 저장인지 schema와 왕복으로 확인하기 전 호출하지 않는다.
- 현재 관측의 `save_project`는 live PCB IPC 저장이므로 offline schematic 저장 증거로 쓰지 않는다. schematic 쓰기는 adapter의 atomic commit, 대상 readback, 파일 SHA로 확인한다.

### GUI

GUI 쓰기는 현재 프로젝트의 명시 승인 입력이 있을 때만 가능하다. 다른 프로젝트나 이전 세션의 영구 승인을 이식하지 않는다. 실제 instance/display/window/document와 미저장 상태를 다시 확인한다. GUI와 MCP를 동시에 쓰지 않으며, 저장·닫기·재열기를 실제로 수행한 경우에만 해당 receipt를 남긴다.

### CLI

CLI는 native export와 검증에 사용한다. 명시한 executable과 version, argv, 원 rc를 보존한다. `.xml` 확장자만 보고 XML이라 단정하지 않고 export format을 `kicadxml`로 명시한다. CLI HOME/library 환경과 MCP·GUI 환경이 다르면 같은 CAD의 library 해석과 ERC가 달라질 수 있으므로 모두 기록한다.

## capability 표

| 능력 | 지원/미지원/미확인 | 확인 도구·version | 소회로 readback | 제한 |
|---|---|---|---|---|
| project·sheet 조회 |  |  |  |  |
| symbol unit·물리 pin 조회 |  |  |  |  |
| pin endpoint 조회 |  |  |  |  |
| 배치·이동·회전 |  |  |  |  |
| wire·junction·port 작성 |  |  |  |  |
| 저장·닫기·재열기 |  |  |  |  |
| native XML export |  |  |  |  |
| ERC 원문 export |  |  |  |  |
| PDF·GUI page 판독 |  |  |  |  |
| SHA·log·원 rc 보존 |  |  |  |  |

도구가 목록에 있다는 사실은 capability 증거가 아니다. 새 조합은 격리 소회로에서 실제 symbol 조회, 배치·wire·junction·port, 이동, readback, 저장·재열기, native export를 확인한다.

## 불명확 응답과 재시도

timeout·연결 끊김이면 같은 mutation을 즉시 반복하지 않는다.

1. session, process, editor, lock 상태를 확인한다.
2. 대상 ref/pin/wire/port와 파일 SHA를 readback한다.
3. `적용`, `미적용`, `부분 적용`, `확인 불가`로 판정한다.
4. 미적용일 때만 현재 readback을 반영한 새 원자 request로 한 번 재시도한다.
5. 부분 적용·확인 불가는 안전한 저장본을 복구하고 권위자에게 인계한다.

다른 이름의 도구를 무한히 시도하거나 과거 request 전체를 재실행하지 않는다.

## 빠진 능력에 따른 역할 제한

| 빠진 필수 능력 | 허용 역할 | 금지 선언 |
|---|---|---|
| 안전한 CAD 쓰기 | 조사·계약·계획·읽기 전용 검토 | 작성 완료 |
| 실제 pin schema | 문서 조사·unknown 기록 | pin·극성 계약 완료 |
| 저장·재열기·export | 작성 초안까지 | 왕복·정적 통과 |
| 전페이지 GUI/PDF 판독 | deterministic 검사와 검토 인계 | 시각 완료 |
| 최신 SHA·log | 제한 관측 보고 | 재현 가능한 완료 |

기준을 낮추거나 존재하지 않는 명령을 꾸며내지 않는다.
