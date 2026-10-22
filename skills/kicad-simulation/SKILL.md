---
name: kicad-simulation
description: KiCad 10 회로도에 SPICE 모델을 붙이고 Konnect MCP 시뮬레이션 도구(KONNECT_SIM=1의 list_simulation_engines, export_spice_netlist, set_simulation_model, run_spice_simulation)로 ngspice·LTspice 배치 해석을 실행해 이론값·기대값과 대조한다. 전원부, MOSFET 구동, OP AMP·센서 아날로그, 정류, 프리차지 돌입 같은 동작 검토와 제조사 SPICE 모델 도입, Qucs-S·LTspice GUI 병행에 적용한다. ERC/DRC 자체, PCB 배치·배선, 제조 발주, 실물 통전 승인에는 적용하지 않는다.
---

# KiCad 회로 시뮬레이션

> 판본: v0.1 candidate. 이 스킬은 이 레포 전용 프로젝트 스킬이며(이식 패키지 규약과 package identity는 적용하지 않는다) 호스트 값은 프로젝트 오버레이·계약 문서·`config/*.lock.json`이 정본이다. 엔진·도구 지원은 2026-10-22 검증(검증 회로 5종을 시스템 ngspice 44.2, KiCad 번들 ngspice 45.2, LTspice 24.0.12(Wine), Qucs-S 26.1.1 네 경로로 실행해 이론값 2% 이내 일치)과 `make test-sim-mcp` 회귀 receipt로만 판단한다. 이 문서만으로 새 회로의 정확성이나 지원을 주장하지 않는다.

## 먼저 권위와 입력을 확정한다

프로젝트 지침(`AGENTS.md`)이 이 스킬보다 우선한다. 다음 입력을 실제 값으로 받아야 한다.

- 검증 질문: 무엇을(신호·시각·주파수) 왜(기동, 리플, 게이트 전압, 이득, 돌입 전류 등) 보려는가
- 대상 루트 회로도 절대경로와 쓰기 허용 여부. 모델 필드 설정은 회로도 **쓰기**다
- 기대값의 출처: 이론식, 데이터시트, 제조사 예제, 이전 측정. 출처가 없으면 "관측만" 모드로 둔다
- 허용 오차(기본: 이론값 대비 2%, 엔진 간 1%)
- 엔진: 기본 `system-ngspice`. KiCad 편집기 내장과 같은 엔진이 필요하면 `kicad-bundled-ngspice`, ADI/LT 모델·예제는 `ltspice`(ACUW 레인 필요)
- 제조사 모델이 있으면 파일 경로, 형식, 암호화 여부, 서브서킷 핀 순서

필수 입력이 없으면 추측하지 않고 `미확인`으로 남긴다. 특히 회로 값·모델 파라미터를 관례값으로 채우지 않는다.

## 엔진을 고른다

| 엔진 | 언제 | 헤드리스 | 비고 |
|---|---|---|---|
| `system-ngspice` | 기본. 배치 회귀, 측정·판정, 파형 CSV | 예 | Debian 44.2. XSPICE 코드모델 포함 |
| `kicad-bundled-ngspice` | KiCad 편집기 시뮬레이터와 같은 엔진으로 재현할 때 | 예 | 45.2 공유 라이브러리. 코드모델 미로드 |
| `ltspice` | ADI/Linear 모델·예제 회로, LTspice 문법 모델 | 아니오(레인) | Wine. `lane` 인자 필수 |
| `qucs-s` | 사람이 보는 회로도·파형 스케치, RF·Xyce | 아니오(GUI) | MCP 도구로 실행하지 않음. [engines](references/engines.md) |

## 항상 지킬 안전 규칙

1. 시작 시 `get_installation_info`로 Konnect `build.version`·`commit`·`executable_path`가 잠금 파일과 같고 `simulation_extension`이 있는지 확인한다. 없으면 구 연결이므로 쓰기·시뮬레이션을 시작하지 않는다.
2. `.kicad_sch`·`.kicad_pro`·라이브러리 파일을 텍스트로 편집하지 않는다. Sim 필드는 `set_simulation_model`(내부적으로 `edit_schematic_component`)로만 바꾼다. GUI와 MCP를 동시에 쓰지 않는다.
3. 시뮬레이션 전에 `export_spice_netlist`의 `unassigned_models`와 `missing_includes`를 0으로 만든다. 모델 없는 심볼을 추측 모델로 채우지 않는다. 커넥터·테스트포인트처럼 시뮬레이션과 무관한 심볼은 KiCad의 "Exclude from simulation" 또는 `Sim.Enable=0`으로 뺀다.
4. 판정에는 기대값 출처와 허용 오차를 반드시 적는다. 측정값 일치는 모델 정확성, 정격, 열, EMI, 실물 안전의 승인이 아니다(SPICE는 모델에 있는 특성만 계산한다).
5. 제조사 모델은 [vendor-models](references/vendor-models.md) 절차를 따른다. 암호화 모델은 ngspice·LTspice·Qucs-S에서 쓸 수 없다. PSpice/LTspice 문법 모델은 `ngbehavior`를 지정한다.
6. GUI(LTspice, Qucs-S, KiCad 시뮬레이터)는 ACUW 전용 레인에서만 띄우고 `ACUW_LANE_MEMORY_MAX=16G`를 open과 run 양쪽에 붙인다. 사용자 실제 화면과 다른 레인·MCP 연결을 건드리지 않는다.
7. 작업 디렉터리, 실행 넷리스트, 로그, 판정표를 보고에 남긴다. `isError=false`여도 `errors`·`missing_measurements`·`all_pass`를 읽는다.

## 필요한 문서만 읽는다

- MCP 도구 4종의 인자·응답·오류·제한과 호출 예: [mcp-tools](references/mcp-tools.md)
- 회로도에 모델을 붙일 때(Sim 필드, Simulation_SPICE 심볼, 라벨, 접지, 지시어, PWR_FLAG): [kicad-sim-fields](references/kicad-sim-fields.md)
- 측정 정의·판정·이론값 유도·배치 모드 함정: [measurements](references/measurements.md)
- 엔진 설치 구성, 검증 명령, LTspice·Qucs-S·KiCad GUI 레인 사용법, 알려진 제약: [engines](references/engines.md)
- 제조사 모델 도입: [vendor-models](references/vendor-models.md)
- 글로벌 `konnect`·`kicad-schematic`·`kicad-review`와 함께 쓸 때: [기존 스킬 교정 C14~C21](references/legacy-skill-overrides.md)

## 최소 흐름

```text
get_installation_info -> list_simulation_engines
   -> (필요 시) set_simulation_model ... -> export_spice_netlist (진단 0)
   -> run_spice_simulation(analysis, measurements, expectations)
   -> 판정·증거 -> (선택) ltspice / kicad-bundled 교차 -> 보고
```

새 회로는 먼저 작은 검증 회로(RC, 분압, 단일 소자)로 모델과 측정 정의가 맞는지 확인한 뒤 실제 회로로 간다. Sim 필드 설정과 지시어 텍스트 추가는 회로도 **쓰기**이므로, 회로도 품질 단서가 함께 있으면 프로젝트 정본 `skills/kicad-schematic-quality`의 모드·계획·allowlist·단일 작성자·readback 규칙을 먼저 적용하고 같은 저장본 SHA에서 시뮬레이션을 잇는다. 기대값·측정 정의·허용 오차·모델 출처 SHA는 실행 전에 고정하고 결과를 보고 고쳐 쓰지 않는다.

## 상태 보고

`엔진 확인`, `모델 지정 완료`, `넷리스트 진단 0`, `해석 완료(판정 없음)`, `기대값 판정 통과`, `교차 엔진 일치`를 구분한다. 각 문구에 엔진·버전, 작업 디렉터리, 실행 넷리스트 SHA, 측정표(이론·측정·오차·허용), 경고, 빠진 항목, 다음 결정 주체를 붙인다. 실행하지 않은 엔진·회로 유형은 `미실행`으로 남긴다.
