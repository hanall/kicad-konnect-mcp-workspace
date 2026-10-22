# SMPS profile 선택 지침

이 profile은 절연·비절연 전력변환 회로의 계획과 프로젝트별 수치 선택을 돕는다. 특정 제품의 페이지 수, 정격, 용지, 간격, 부품값을 강제하지 않는다. 검증기의 정답은 별도의 사전 고정 semantic JSON이다.

## 먼저 받을 프로젝트 매개변수

| 범주 | 필요한 값 | 주요 근거 |
|---|---|---|
| topology | 변환 방식, 단방향·양방향, 제어 구조 | 요구·설계 결정 |
| 정격 | 입력·출력 범위, 전류, 전력, transient, derating | 요구·계산·부품 원문 |
| 절연 | 절연 경계, 적용 규격·등급·환경, 시험 조건 | 적용 규격 원문·안전 검토 |
| switching | 주파수, dead time, gate 조건, 기본 안전 상태 | controller·switch·driver 원문 |
| 자기소자 | 권선, 점극성, 절연, flux·손실 조건 | 계산·제조 사양 |
| 전력 경로 | fuse, bridge, switch, rectifier, filter, 차단, load | topology 계약 |
| 측정 | shunt/divider, Kelvin, amplifier, ADC/comparator 범위 | 오차 budget·원문 |
| feedback | reference, compensation, actuator, startup/shutdown | 제어 계산·원문 |
| 보호 | OVP/OCP/OTP, DESAT, latch, watchdog, discharge | 위험 분석·요구 |
| bias | 각 domain 공급, 부유 return, sequencing, power-good | 절연전원 원문 |
| 출력 profile | 용지, 페이지 수, font/grid, 시각 threshold | 납품 매체·기준본 |

수치가 빠졌으면 기존 SMPS 사례의 값으로 채우지 않는다. 적용 규격과 안전 조건은 최신 원문 확인이 필요한 별도 입력이다.

## 권장 기능 분할 후보

과제에 존재하는 블록만 선택한다.

- 입력 보호·정류·DC link
- 주 switching stage와 자기소자
- 2차 정류·필터·출력 차단
- channel별 gate driver·DESAT·Miller clamp·Kelvin
- 전압·전류 sensing과 reference
- feedback·compensation·limit
- supervisor·latch·watchdog·enable/stop
- 절연 bias와 각 부유 return
- connector·controller interface·debug

블록 수와 페이지 수는 topology와 출력 매체로 정한다. 루트와 각 상세 페이지의 ref/unit/pin 소유와 양쪽 port 계약을 첫 CAD 쓰기 전에 고정한다.

## SMPS 전기·시각 확인

- 주 에너지 경로와 주전류 return을 실제 pin으로 끊김 없이 따라갈 수 있는가?
- shunt·divider의 Kelvin 경로가 주전류·일반 ground와 구분되는가?
- transformer·inductor의 권선과 점극성이 원문·계산 계약과 같은가?
- gate channel의 command, driver output, Ron/Roff, clamp·DESAT, gate, source/Kelvin 대응이 맞는가?
- 각 절연 bias의 source, 양·음 output, midpoint/return, feedback·RLIM·power-good가 다른 channel과 섞이지 않는가?
- feedback loop가 측정점에서 filter·amplifier·controller·actuator까지 읽히는가?
- active-low, latch/reset 우선순위, startup/shutdown의 기본 안전 상태가 실제 gate로 표현되는가?

pull 방향, label/tag 거리, field 여백 같은 수치는 선택한 용지·font·grid·실제 glyph 기준으로 교정한다. 한 제품에서 성공한 값이나 페이지 구성을 다른 SMPS에 자동 적용하지 않는다.

## 완료 한계

static pin/net, ERC, native PDF와 시각 검토가 통과해도 loop 안정성, switching waveform, magnetic saturation, 열, creepage/clearance 적합성, EMC, 정격, 실물 안전, 제조·통전을 증명하지 않는다. 계산, simulation, PCB 검토, 실험, 규격 심사와 승인 상태를 별도로 보고한다.
