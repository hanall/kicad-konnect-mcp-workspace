# 전기 계약과 회로 표현 규칙

이 문서는 전기적 정적 정확성의 입력과 대조 방법을 소유한다. 특정 부품값·정격·간격을 공통 기본값으로 제공하지 않는다.

## 권위 순서

1. 승인된 프로젝트 요구와 변경 결정
2. 적용 부품의 제조사 원문과 package pin 표
3. 현재 설치된 symbol/library의 실제 schema와 배치본 endpoint
4. 사전 검토된 semantic 계약
5. 일반 패턴과 기존 스킬 예제

하위 자료가 상위 자료와 다르면 추측으로 합치지 말고 불일치와 결정 주체를 기록한다. 일반 부품표의 핀 번호·극성은 힌트일 뿐 정답이 아니다. 특히 diode·LED·transistor·multi-unit IC는 `lib_id` 이름이나 도형만 보고 pin을 정하지 않는다.

## 실제 핀 계약

각 물리 부품에 대해 다음을 집합으로 고정한다.

- ref, unit, 물리 pin number, pin name/type, polarity
- symbol/library source와 package/footprint 상태
- 배치된 pin endpoint와 연결 net
- 공급·반환·전압·절연 영역
- 미사용 pin의 NC 근거와 표시 방식

`get_symbol_info`와 배치본 pin 위치 조회의 실제 응답 schema를 확인한다. 응답에 `unit_count`나 `units[].pins`가 항상 있다고 가정하지 않는다. 조회가 오류 없이 끝나도 pin 수가 0이거나 pin 목록·unit·상속 정보가 비어 있으면 성공으로 세지 않는다. library source의 물리 pin inventory, 다른 현재 API, 정확한 MPN/package 자료, 배치 뒤 endpoint readback을 조합해 기대 pin coverage·unit·번호·이름을 모두 닫기 전에는 `미확인`이다. multi-unit 부품의 power unit을 생략하지 않으며 같은 endpoint 중복 반환과 실제 CAD의 중복 unit·pin을 구분한다.

## 모드별 전기 oracle

| 모드 | 사전 고정할 전기 oracle | 차단 조건 |
|---|---|---|
| `design` | 요구·원문 기반 ref/unit/pin/net/type/value/footprint | 근거 없는 pin·극성·return |
| `rewrite` | 시작점 전체 집합과 허용 이름·심볼 대응 | 누락·중복·무승인 차이 |
| `change` | 승인 전후 diff와 영향 집합 | 승인 밖 차이 |
| `review` | 검토 대상 저장본과 요구·원문 | 최신성·범위 미확인을 PASS로 처리 |

후보 CAD에서 기대값을 다시 만들어 자기 자신을 검증하지 않는다. semantic 계약은 CAD 쓰기 전에 검토자가 고정하고, 후보는 별도 runtime envelope에 hash와 생성 provenance만 기록한다.

## 로컬 실선과 이름 연결

- 가까운 R/C, divider, filter, compensation, clamp, gate branch, sensing, Kelvin 경로는 실제 wire로 닫아 loop를 읽을 수 있게 한다.
- net 이름이 있다는 이유만으로 가까운 핀마다 label stub을 붙이지 않는다.
- 장거리·반복·페이지 경계는 label/port를 사용할 수 있지만 양쪽 ref.pin, 방향, 전기형, 전압 영역, 반환, 상대 시트를 계약한다.
- junction 모양만 보고 접점을 단정하지 않고 저장·재열기 뒤 wire graph와 native netlist를 확인한다.
- 교차와 분기, 예상 밖 wire 연장, label 오타, 다른 net 합류를 별도 검사한다.

실선 수나 label 수를 보편 목표로 삼지 않는다. 기능 흐름, 검토 가능성, 실제 전기 연결이 기준이다.

## 공급·반환·절연

공급원, 소비 pin, power return, signal reference, 부유 return, Kelvin return, chassis/PE, 절연 경계를 각각 계약한다. 보기 좋다는 이유로 서로 다른 기준점을 일반 GND나 VCC에 합치지 않는다.

`PWR_FLAG`는 ERC 경고를 숨기는 장식이 아니다. 실제 전원 공급 근거와 ERC 모델이 일치할 때만 승인 범위에서 사용한다. 경고를 줄이기 위해 pin type을 임의로 `passive`로 바꾸거나 no-connect를 추가하지 않는다.

전원 symbol도 실제 project/library 의미를 확인한다. 이름이 같은 rail이라도 전압 영역, 절연 영역, sequencing, return이 다르면 같은 net으로 간주하지 않는다.

## 기능별 검토 질문

### 전력 경로

입력·보호·변환·자기소자·정류·필터·차단·부하와 주전류 반환을 실제 pin으로 따라갈 수 있는가? 병렬 소자, fuse, shunt, Kelvin 분기가 실제 수와 소유로 보이는가?

### gate 구동

명령·허용 입력에서 driver output, Ron/Roff, clamp·DESAT, gate, 해당 switch의 Kelvin return까지 channel 대응이 보존되는가? 절연 전원의 공급과 부유 return이 다른 channel과 섞이지 않는가?

### 아날로그 sensing·feedback

측정점에서 divider/filter, amplifier/comparator, compensation/control, actuator까지 loop를 따라갈 수 있는가? reference와 high/low-side·차동·Kelvin return이 구분되는가?

### 논리·안전

active-low polarity, reset 우선순위, latch/watchdog, 기본 안전 상태를 실제 gate와 pin으로 확인할 수 있는가? 논리식 주석이 전기 연결을 대신하지 않는가?

### interface·multi-unit

한 물리 ref의 모든 unit·power pin·connector pin이 정확히 한 번 소유되는가? 기능 분할이 pin 누락·중복을 만들지 않는가?

## 수치와 성능 경계

decoupling 값, pull 값, 이격, 배치 거리, trace 조건, 정격, 전압·전류 제한은 요구·제조사 자료·선택 profile에서 가져온다. 관례값을 자동 채택하지 않는다. 회로도에서 부품이 가깝게 보이는 사실은 PCB 물리 거리나 SI·열·EMC 성능을 증명하지 않는다.

정적 pin/net/ERC 통과는 동적 안정성, 정격 여유, 절연 적합성, 실제 안전, 제조 적합성을 증명하지 않는다. 이들은 별도 분석·시험·승인 범위로 남긴다.
