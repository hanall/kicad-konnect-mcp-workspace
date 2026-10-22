# KiCad 회로도 GUI 안전 인계 MCP 계약

## 적용 범위

사용자 지시(2026-10-07): 공유 화면의 KiCad GUI 직접 편집을 영구 승인하고, 그 승인과 별개로 **MCP 안전 동기화 수정을 먼저** 수행한다.

새 도구는 `synchronize_schematic_edit`이다. 기존 Rust Konnect의 파일 잠금 검사는 변경하지 않는다. 프로젝트 STDIO 중계 계층(`scripts/konnect-mcp-gui.py`)에 도구 하나를 추가하며, 실제 회로도 쓰기는 고정된 Konnect 도구만 수행한다. upstream 소스·release binary·잠금 파일을 바꾸지 않았다.

KiCad 10.0.6의 `api_handler_sch.cpp`에는 회로도용 `SaveDocument`, `RevertDocument`, `SaveDocumentToString` 핸들러 등록이 없다. 공통 protobuf에 이름이 있다고 회로도 구현도 있다고 판단하지 않는다. 따라서 이번 기능은 **열린 메모리를 실시간 수정하는 API가 아니라, 정상 종료와 재열기를 자동화한 안전 인계**다. 편집기 창은 잠시 닫혔다가 같은 공유 레인에 다시 열린다.

## 상태 전이

```text
DRY_RUN -> REVISION -> BACKUP -> CLOSE_GUI -> MCP_EDIT -> READBACK -> REOPEN_GUI
   |           |                    |           |                      |
   v           v                    v           v                      v
 REFUSE      STALE                REFUSE      PARTIAL                UNCONFIRMED
```

## 안전 조건

- `dry_run` 기본값은 `true`이며 이 단계는 회로·GUI를 변경하지 않는다. 반환 revision은 같은 연결에서 5분 동안 유효한 일회용 값이다.
- 루트 절대경로, 명명된 ACUW `visible-xvfb` 레인, 창 ID, 실제 PID와 시작 시각, 프로세스의 프로젝트 인자, 파일 해시, 편집 배열을 결속한다. 같은 파일명만으로 선택하지 않는다.
- 현재 GUI에는 **루트 시트**가 보여야 한다. 하위 시트를 보고 있으면 루트로 이동한 뒤 호출한다. 편집 대상 파일은 해당 루트의 저장된 계층 안에서 고른다.
- 한국어·영어 KiCad 창 제목을 지원한다. `IsContentModified()`가 제목 앞에 붙이는 `*`를 검사해 **미저장 변경은 거부**한다. 자동 저장·폐기 승인·Esc로 사용자 작업 취소를 하지 않는다. 대화상자가 열려 있어도 거부한다.
- 작업 중에는 사용자가 같은 시험/작업 창을 조작하지 않는다. 아직 확정하지 않은 임시 배치 도구 상태까지 읽는 native API는 없으므로, 호출자는 배치·드래그를 마친 정지 상태에서 요청해야 한다.
- 정상 창 닫기 요청 후 창과 실제 `.lck`가 모두 사라진 것을 확인해야만 편집한다. 살아 있는 잠금을 삭제하거나 엔진 검사를 우회하지 않는다.
- 파일별 원본을 `.artifacts/gui-sync/<revision>/*.snapshot`으로 보존하고, 단계별 `receipt.json`을 fsync한다. 각 편집 사이에 해시를 다시 대조한다.
- 최대 32개 편집이다. 지원 목록은 도구의 실제 schema가 정본이다. 계층 생성/삭제, 프로젝트 이름 변경, PCB, 라이브러리 수정은 이 도구의 범위가 아니다.
- 도구 미로드·대상 불일치·revision 변경은 쓰기 전에 거부한다. 편집 배열의 모든 의미 오류를 미리 시뮬레이션하는 것은 아니다. 도중 실패하면 **이미 적용한 prefix와 불확실한 항목을 보고**하고 전체 성공으로 표시하지 않는다. `isError=false`여도 `errors`·`failures` 또는 `outcome.status`가 부분 실패를 나타내면 미완료로 취급한다. `applied_count`는 완전히 완료한 **도구 호출 수**이며 부품 수가 아니다. 단일 batch의 일부 적용은 해당 응답 본문과 pending_index에 보존한다.
- 자동 rollback은 하지 않는다. 후속 GUI/외부 변경을 덮어쓸 수 있기 때문이다. 실패 영수증·원본 snapshot·현재 파일을 대조해 복구한다.
- 재열기의 프로세스·문서·잠금·정상 창을 확인하고 화면을 캡처한다. 회로 객체의 native 메모리 readback은 지원하지 않으므로 `needs_visual_confirmation=true`가 남는다. 에이전트가 실제 캡처를 보고 반영을 확인해야 한다.
- 호출 타임아웃·연결 단절 뒤에는 무조건 재시도하지 않는다. 영수증과 창부터 확인한다. SIGTERM/SIGINT/SIGHUP 또는 upstream 응답 타임아웃은 자기 Konnect 연결을 먼저 정지시킨다. 강제 SIGKILL·호스트 종료는 자동 재열기까지 보장하지 않는다. 다른 MCP 연결·사용자 화면·프로세스는 종료하지 않는다.

## 호출 순서

1. `get_installation_info`에서 core 버전/commit/실행 경로와 `gui_sync_extension`을 확인한다.
2. `sch_hierarchy`, `sch_components`, `sch_analysis`, `sch_batch`, `sch_wiring` 중 필요한 도구 묶음을 로드한다. `get_sheet_hierarchy`, `get_schematic_layout`, 편집에 쓸 도구가 필요하다.
3. 다음 형식으로 준비한다. 경로와 레인은 실제 대상으로 대체한다.

```json
{
  "schematic": "/absolute/project/root.kicad_sch",
  "lane": "project-lane",
  "dry_run": true,
  "operations": [
    {
      "tool": "set_schematic_page",
      "arguments": {
        "schematic": "/absolute/project/root.kicad_sch",
        "size": "A3",
        "portrait": false
      }
    }
  ]
}
```

4. 동일한 인자에서 `dry_run=false`, `expected_revision=<준비 응답의 revision>`으로 적용한다.
5. 응답의 outcome·applied_count·개별 결과·receipt·캡처를 확인한다. `applied_and_reopened`는 회로 안전성이나 ERC 통과를 뜻하지 않는다.

## 활성화와 되돌리기

프로젝트 `.mcp.json`, `.codex/config.toml`은 기존 `scripts/run-konnect.sh`에 `KONNECT_GUI_SYNC=1`을 전달한다. `battery-module-cycler`에도 같은 절대경로 실행기를 등록했다. 새 연결부터 적용되며 기존 연결을 임의 종료하지 않는다. 이번 검증은 새 전용 STDIO 연결에서 수행했다.

- 비활성화: 등록 env를 `KONNECT_GUI_SYNC=0`으로 바꾸고 **그 연결만** 다시 연다. core의 원래 잠금 거부는 그대로다.
- 추가 의존성·패키지 설치 없음. Python stdlib와 이미 설치된 ACUW·wmctrl·xprop·KiCad를 사용한다.
- root 검증: `make verify`, `make test-gui-sync`. Rust/core와 KiCad 원본은 변경하지 않아 이번에는 Rust 전체 시험을 재실행하지 않았다.

## 이번 검증 증거

- root Python 시험 **83건 통과**(GUI 인계 12건 포함), 미저장 거부 가드를 제거한 임시 변이본에서 해당 회귀가 실패하고 정본은 다시 통과했다. `isError=false`인 부분 batch를 완전 성공으로 잘못 표시하는 추가 회귀도 RED → GREEN으로 고쳤다.
- 실제 GUI 시험은 **SMPS 원본이 아닌 별도 fixture**, `kicad-smps-live-sync` / `DISPLAY=:183`에서 수행했다.
- 정상 추가: `R101=10k`를 기존 MCP로 추가하고 같은 레인에 재열기, 저장 회로 재조회와 화면 확인.
- 미저장 거부: 실제 GUI에서 저항을 회전한 뒤 저장하지 않은 상태에 `unsaved_changes`. 파일 SHA와 창이 보존됨.
- stale 거부: 준비 뒤 실제 GUI를 수정·저장하고 이전 revision을 적용하면 `stale_revision`, 창을 닫지 않음.
- 부분 실패: 첫 텍스트 추가 뒤 없는 reference 수정이 실패하면 `applied_count=1`, `partial_or_uncertain`, GUI 재열기와 첫 적용분 보존.
- 단일 batch 부분 실패도 실제 GUI로 재검증했다. 정상 저항 하나와 없는 라이브러리 심볼을 함께 요청했을 때 core의 `isError=false`, `placed_count=1`을 전체 성공으로 오인하지 않고 `upstream_partial`로 보고하며 정상 저항을 보존·재열기했다.
- source 갱신 뒤 전용 연결을 다시 열어 정상 재열기를 재확인했다. core binary의 실행 중 `/proc/<PID>/exe`와 디스크 SHA는 일치하며 `0.13.0+hanall.1`, commit `94f80350cf67db27b179a06a8f6dbebfe4717927`을 유지한다.
- 원 로그·JSON-RPC·영수증: `.artifacts/20261007-gui-sync-live/`, `.artifacts/gui-sync/`. 이 자료는 로컬 검증 산출물이며 Git 추적 대상이 아니다.

GUI 직접 편집 영구 승인은 [기존 오버레이](20261006-112759_kicad-konnect-overlay.md)에 기록했다. 이 승인과 MCP 인계 구현은 별개의 사실이다.
