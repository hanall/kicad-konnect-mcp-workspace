# 회로도 공통 사전 계획 양식

> 쓰기 모드에서 복사해 실제 CAD 첫 mutation 전에 구체 내용으로 채운다. 빈 칸과 미확정을 숨기지 않는다. 이 양식은 체크 표시만 채우는 문서가 아니라 전체 회로도 구조와 전기·시각 계약을 다른 작성자가 재현할 수 있게 하는 설계도다.

## 1. 권위·범위·모드

| 항목 | 내용 |
|---|---|
| 프로젝트·판본 |  |
| 모드 | `design` / `rewrite` / `change` |
| 요청·독자·납품 형태 |  |
| 프로젝트 지침·승인 출처 |  |
| 대상·비대상 |  |
| workspace root·project dir |  |
| 루트 회로도·허용 파일 |  |
| 단일 CAD 작성자·검토자 |  |
| 승인된 GUI/MCP 채널 |  |
| saved/live·lock 상태 |  |

## 2. 요구·원문·profile

| 요구 ID | 기능·수치 | 원문 판본·위치 | 원 bytes SHA-256 | 채택·가정·미확정 | 검토자 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

- 선택 profile과 판본:
- 용지·방향·page 수·grid·font:
- 전압·절연 영역과 각 return:
- 프로젝트별 수치와 근거:
- 틀리면 결과가 달라지는 unknown·결정 주체:

## 3. 전체 구조와 읽는 순서

| 순서 | 회로도 파일·제목 | 기능 시작·끝 | 소유 부품·unit | 입력·출력 포트 | 전압 영역·반환 |
|---:|---|---|---|---|---|
|  |  |  |  |  |  |

- 루트에서 보일 전체 기능 흐름:
- 주 흐름과 feedback 방향:
- 페이지 간 이동 방법과 표제·판본 정책:
- 가까운 기능 loop의 실선 원칙:
- 장거리 label·port 허용 조건:
- 반복 channel의 표시와 실제 pin 보존 방법:

## 4. 보존·변경·전기 경계

| 집합 | 보존 기준 또는 승인 변경 | 원문·semantic 근거 | 차단 조건 |
|---|---|---|---|
| ref/unit/물리 pin |  |  |  |
| net·junction·port |  |  |  |
| value·footprint |  |  |  |
| supply·return·isolation |  |  |  |
| 승인 전기 변경 |  |  |  |

`rewrite`에서는 시작점과 후보의 전단사 및 무승인 차이 0을 적는다. `change`에서는 승인 전후 diff와 영향 시트를 적는다. `design`에서는 제조사 원문과 실제 설치 symbol schema의 불일치를 숨기지 않는다.

## 5. 도구·계획·검증

| 항목 | 실제 값·경로·SHA | 확인 방법 | 미지원 시 인계 |
|---|---|---|---|
| launcher/config/server cwd |  |  |  |
| 기대 version·commit |  |  |  |
| current tool schema |  |  |  |
| plan-index와 모든 페이지 계획 |  |  |  |
| registry·semantic 계약 |  |  |  |
| 새 evidence 경로 |  |  |  |
| native XML/PDF/ERC |  |  |  |

첫 CAD 쓰기 전 확인: 루트 포함 모든 허용 회로도 계획이 존재하고 구체 본문·원문 SHA·계획 SHA가 고정됐는가? `require_all_plans_before_write`가 true인가? read-only 파일·외부 library source가 쓰기 대상과 분리됐는가?

## 6. 계획 변경 원장

| 시각 | 발견 | 영향 | 새 계획 SHA | 작성 재개 조건 | 재검증 |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

과거 SHA를 덮어쓰거나 첫 쓰기 이전으로 소급하지 않는다. 변경 이유와 검토자를 append-only로 남긴다.
