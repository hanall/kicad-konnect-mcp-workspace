# 공통 흐름과 상태 계약

이 문서는 착수·계획·작성·재개 순서를 소유한다. 전기 기준, 시각 기준, 검증 판정은 각각의 reference를 필요한 때만 읽는다.

## 1. 착수 입력

| 구분 | 반드시 받을 값 | 누락 시 처리 |
|---|---|---|
| 권위 | 프로젝트 지침, 요구·결정·승인 출처 | 자체 확인 후 남으면 질문 |
| 범위 | 모드, 대상 시트, 비대상, 납품 형태 | CAD 쓰기 보류 |
| 경로 | workspace root, project dir, 루트 회로도, allowlist | 추정 경로로 쓰지 않음 |
| 원문 | 요구·제조사 자료·핀표의 판본과 원 bytes SHA-256 | 계약을 확정하지 않음 |
| profile | 적용 profile과 프로젝트별 수치 | 일반값을 합성하지 않음 |
| 역할 | 단일 CAD 작성자, 검토자, 승인된 작성 채널 | 조사·계획만 수행 |
| runtime | launcher, config, server cwd, 기대 version·commit | 연결 쓰기 금지 |
| oracle | 검토자가 선행 고정한 registry와 semantic 계약 | 검증 PASS 금지 |
| 증거 | 새 evidence 디렉터리와 보존 정책 | 기존 증거에 덮어쓰지 않음 |

확인 가능한 것은 먼저 확인하되, 잘못 가정하면 회로가 달라지는 unknown은 `내용`, `확인 근거`, `결정 주체`, `영향`으로 기록한다.

## 2. 상태와 소유권 baseline

CAD를 열거나 요청을 보내기 전에 다음을 한 receipt에 결속한다.

- 실제 project root와 대상 파일 SHA-256
- saved file SHA와 live editor의 문서·revision·미저장 여부
- 편집기 lock의 실제 소유자와 단일 작성자
- 현재 Git 변경 중 자신의 쓰기 범위와 보존할 타 작업자 변경
- 사용 채널, project authority가 허용한 범위, GUI와 MCP의 비동시 상태
- 현재 tool schema, version, commit, launcher/config/server cwd
- 입력 계약·registry·계획 파일의 경로와 SHA-256

live와 saved가 다르면 어느 쪽을 기준으로 삼을지 권위자에게 확인하고, 미저장 내용을 덮지 않는다. 읽기 전용 리뷰는 저장 명령을 실행하지 않고 검토한 saved/live 범위를 명시한다.

## 3. 모드별 계약

### 신규 설계 `design`

요구를 기능·인터페이스·보호·측정·전원·반환으로 나눈다. 제조사 원문의 판본·쪽·표와 실제 설치 심볼 schema를 근거로 ref/unit/pin, pin type, 극성, net, 전압 영역, 반환, 절연 경계를 계약한다. 계산값·채택값·가정·미확정을 분리한다.

### 가독성 재작성 `rewrite`

시작점에서 부품, 모든 물리 pin, net membership, 값, footprint, sheet/port 집합을 고정한다. 이름·기능 심볼 대응을 명시하고 전단사 및 무승인 전기 변경 0을 차단 조건으로 둔다. 시작점 오류 의심은 `발견`, `영향`, `근거`, `승인 필요`로 격리한다.

### 승인 전기 변경 `change`

승인 출처, 변경 전후 기대값, 영향받는 ref/pin/net/sheet/port/검사를 열거한다. 주변 정리는 별도 변경이다. 영향 시트와 전체 연결 통합을 모두 다시 확인한다.

### 읽기 전용 검토 `review`

검토한 saved/live 상태와 증거 SHA를 고정하고 `관측`, `결론`, `제안`, `미확인`을 분리한다. CAD 쓰기, 저장, 자동 수정, lock 변경은 0이어야 한다. 기존 계획이 없으면 `미수신`으로 기록하며 검토 뒤 계획을 소급 생성하지 않는다.

## 4. 공통 계획과 페이지 계획

쓰기 모드에서는 [공통 계획](../assets/common-plan.md)을 먼저 채우고 루트 회로도를 포함한 **모든 허용 회로도 파일**에 [페이지 계획](../assets/page-plan.md)을 만든다. 페이지 수, 용지, 좌표, 정격, 간격은 profile 입력이지 공통 상수가 아니다.

각 계획에는 다음이 있어야 한다.

- 기능의 시작·끝과 읽는 순서
- ref/unit/pin과 시트 소유
- 실선으로 닫을 로컬 망과 junction
- 양쪽 페이지 포트, 전기형, 전압 영역, 반환
- 공급·일반 접지·부유 기준·Kelvin·PE의 분리
- 보존 집합, 승인 변경, 허용 예외, 차단 기준
- 원문 source 경로·bytes SHA-256, 계획 자체 SHA-256

`plan-index.json`은 schema 1을 유지하고 `mode`, `common_plan`, `plans`, `allowed_files`, `read_only_files`, `read_only_library_refs`, `require_all_plans_before_write: true`를 명시한다. `plans`는 루트와 모든 쓰기 허용 `.kicad_sch`를 빠짐없이 매핑한다. `read_only_library_refs` 값은 실제 설치 심볼 source의 절대경로이며 **조회·project-scope 참조만** 허용한다.

[plan-index 예제](../assets/plan-index.example.json)는 `create_project`로 새 프로젝트를 만드는 `design` 예제이므로 생성 대상 `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`를 allowlist에 두고 `read_only_files`는 비워 둔다. 기존 프로젝트의 PCB를 보존해야 한다면 `create_project`를 호출하지 않는다. 기존 project/PCB를 baseline으로 고정하고 `.kicad_pcb`를 `read_only_files`에 넣은 뒤, 현재 schema에서 확인한 회로도 전용 경로로 승인·계획된 `.kicad_sch`만 만든다. hierarchy나 루트 회로도 변경이 필요하면 그 파일의 별도 쓰기 승인을 먼저 받는다. guard를 통과시키려고 read-only 항목을 제거하거나 allowlist·권한을 자동 확대하지 않는다.

계획은 체크 표시만 있는 빈 양식이 아니라 다른 작성자가 구현할 수 있는 구체 설계도여야 한다. 첫 mutation보다 늦게 만든 파일을 사전 계획으로 인정하지 않는다. 요구나 배치 계약이 바뀌면 쓰기를 멈추고 새 판본과 SHA를 남긴 뒤 재개한다.

## 5. capability 시험과 작성

새 도구·심볼·회로 유형·runtime 조합이면 생산 회로가 아닌 승인된 격리 소회로에서 조회, 작성, readback, 저장, 재열기, native export를 확인한다. 이 성공은 그 기능과 조합의 capability일 뿐 전체 회로 합격이 아니다.

한 번에 기능 소회로 하나만 쓴다.

1. 실제 심볼의 모든 unit, 물리 pin, type, endpoint를 조회한다.
2. 페이지 계획의 ref·pin 소유와 기능 구역을 대조한다.
3. 가까운 R/C, divider, compensation, clamp, gate branch, Kelvin 경로를 실선으로 닫는다.
4. 먼 기능 경계만 양쪽 계약이 있는 port/label로 연결한다.
5. 쓰기 직후 대상 ref/pin/net과 예상 밖 wire·중복·연장선을 readback한다.
6. 명시된 저장 채널로 정상 저장한 뒤 다음 소회로로 진행한다.

요청 수나 batch 크기는 품질 기준이 아니다. 과거 request 파일을 확인 없이 재사용하지 않는다.

## 6. 채널 전환과 실패

GUI에서 MCP로 전환하려면 미저장 변경 확인, 정상 저장, 정상 닫기, lock 해제를 확인한다. MCP에서 GUI로 전환하면 현재 파일을 다시 열어 saved 상태를 읽고 새 export를 만든다. 프로젝트가 GUI 쓰기를 승인하지 않았다면 GUI는 관측에만 사용한다.

timeout·연결 끊김·불명확 응답 뒤에는 같은 쓰기를 바로 반복하지 않는다. 실제 파일 SHA와 대상 ref/pin/wire/port를 읽어 `적용`, `미적용`, `부분 적용`, `확인 불가`로 판정한다. 재시도는 미적용이 확인되고 새 원자 request와 새 SHA가 있을 때 한 번만 수행한다. 부분 적용·확인 불가이면 안전한 저장본과 단일 작성자 상태를 복구할 때까지 쓰지 않는다.

## 7. 왕복과 재개

쓰기 결과는 정상 저장, 닫기·재열기, CAD readback, native XML/PDF/ERC 생성, deterministic 검사, 전페이지 시각 판독 순으로 확인한다. 각 단계의 source, argv, 원 rc, 입력·출력 SHA를 보존한다. GUI를 왕복했다는 사실이 없으면 합성하지 않는다.

재개 전 다음을 대조한다.

1. 마지막 검증 CAD SHA와 현재 SHA
2. saved/live 차이와 lock 소유자
3. 단일 작성자와 다른 작업자의 변경
4. 마지막 완료 소회로, 열린 결함, 다음 안전한 동작

부분 결과에는 반드시 scope를 붙인다. `도구 호출 성공`, `한 시트 정적 통과`, `전체 전기 계약 통과`, `작성자 시각 검토`, `독립 검토`, `제한 범위 인계`는 서로 다른 사실이다.
