# General profile 선택 지침

이 profile은 특정 회로 유형의 사전값이 없는 일반 회로도에 사용할 **계획·수치 선택 지침**이다. 검증기의 정답은 별도의 사전 고정 semantic JSON이며, 이 Markdown에서 자동 생성하지 않는다.

## 적용 전 caller 입력

| 항목 | 프로젝트가 정할 값 | 근거 |
|---|---|---|
| 문서 구조 | 루트·상세 시트 목록, 읽는 순서, 페이지 수 | 요구·기능 분할 |
| 출력 매체 | 용지, 방향, 실제 출력 배율 | 납품·검토 방식 |
| 표현 단위 | grid, font, line/field 정책 | 현재 CAD·출력 시험 |
| 기능 흐름 | 각 시트 시작·끝·주 흐름·feedback | 회로 동작 |
| 전기 영역 | supply, return, reference, isolation, PE | 요구·원문 |
| 로컬 실선 | 실선으로 닫을 기능 loop와 예외 | 읽기 과제 |
| 페이지 포트 | 양쪽 ref.pin, 방향, 영역, return | hierarchy 계약 |
| 부품 수치 | 값·정격·허용오차·footprint 상태 | 제조사 원문·계산·승인 |
| ERC 정책 | 활성 규칙, 개별 경고 근거, 제외·비활성 | 프로젝트 검토 정책 |
| 시각 기준 | 문자 판독, field 여백, 확대 대상 | 실제 GUI/PDF 기준본 |
| 완료 범위 | 필요한 G0~G5 관문과 비대상 | 사용자 요청 |

값이 없으면 관례값이나 다른 프로젝트 값을 넣지 않고 질문 또는 unknown으로 남긴다.

## 기능 분할 질문

- 독자가 제목 없이도 시작점·종점·주 경로를 찾을 수 있는가?
- 한 로컬 loop를 실제 ref.pin과 실선으로 따라갈 수 있는가?
- 공급, signal reference, power return, 부유/Kelvin/PE가 구분되는가?
- page port의 실제 상대 시트와 수신 pin을 찾을 수 있는가?
- multi-unit 부품의 모든 물리 pin과 power unit이 정확히 한 번 소유되는가?
- 반복 channel이 축약 없이 검토 가능하고 서로 다른 net이 섞이지 않는가?
- ref/value/pin/net/주석이 실제 출력 배율에서 읽히는가?

## 선택 규칙

좌→우 흐름, 특정 grid, 고정 글자 크기, 고정 시트 수, 고정 간격, decoupling·pull 값은 공통 기본값이 아니다. 회로가 양방향, ring, 다중 source이거나 feedback 중심이면 자연스러운 읽기 방향을 계획하고 예외 근거를 기록한다.

local label과 port는 wire를 줄이는 목표가 아니라 기능 경계 표현 수단이다. 가까운 divider·filter·compensation·clamp·gate·Kelvin loop는 실선으로 닫는 것을 우선 검토한다. 멀리 떨어진 연결은 양쪽 계약이 있을 때 사용한다.

## 판정 경계

이 profile을 채웠다는 사실은 요구·전기·시각 검증 완료가 아니다. native export, 개별 ERC 판정, saved/live 결속, 전페이지 GUI/PDF 판독, 검증 receipt가 별도로 필요하다. 회로도 통과를 PCB·동적 성능·정격·제조·통전·인증·실물 안전으로 올리지 않는다.
