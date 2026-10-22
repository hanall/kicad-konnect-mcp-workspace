# 기존 KiCad 스킬 시뮬레이션 교정
이 문서는 글로벌 `konnect`·`kicad-schematic`·`kicad-review`를 이 패키지와 함께 쓸 때의 교정 정본이다. 세 스킬과 references에는 SPICE·시뮬레이션 지침이 없다(2026-10-22 확인). C01~C13은 `kicad-schematic-quality` 패키지를 따르고 번호를 잇는다.

| ID | 교정 규칙 | 적용 방법 |
|---|---|---|
| C14 | 시뮬레이션 실행을 KiCad IPC·`kicad-cli`에 기대하지 않는다 | KiCad 10.0.6의 회로도 IPC는 `GetOpenDocuments`만 등록하고 `FT_SPICE_SIMULATOR`는 창 식별자이며 `kicad-cli sch`는 `erc`·`export`·`upgrade`뿐이다. 실행은 `export_spice_netlist`(또는 core `generate_netlist`의 `format='spice'`) 다음 `run_spice_simulation(engine=...)`이다. 결과에 엔진 이름·경로·버전을 남기고 `ngspice`라는 이름만으로 시스템 44.2와 번들 45.2를 섞지 않는다. eeschema 시뮬레이터 GUI 결과는 레인 캡처 증거이며 결정적 `.meas` 판정을 대신하지 않는다. |
| C15 | KiCad 넷리스트와 SPICE 넷리스트를 구분한다 | `konnect` Channel 2의 `.net` 분석과 core `generate_netlist` 기본값 `format='kicad'`(schema 설명 `Output .net file path`)은 시뮬레이션 입력이 아니다. `format='spice'`와 `.cir`만 엔진에 넣는다. kicad-cli 10.0.6의 `spicemodel`과 `--variant`는 현재 core schema에 노출되지 않았으므로 쓰려면 호출 전 schema와 실제 출력을 확인한다. |
| C16 | Sim 모델 부착은 쓰기이며 핀 결속 관문을 거친다 | `Sim.Device`·`Sim.Type`·`Sim.Params`·`Sim.Pins`(필요 시 `Sim.Library`·`Sim.Name`·`Sim.Enable`)는 `set_simulation_model` 또는 core `edit_schematic_component.fields`로만 쓴다. `set_simulation_model`은 저장 뒤 `get_schematic_component`로 readback해 `readback_matches`를 돌려주므로, 그 값과 넷리스트의 해당 소자 줄로 확인한다. `Sim.Pins`는 symbol pin과 모델 노드 순서를 묶으므로 C04·C13과 같은 physical pin map 관문이다(예: 검증 fixture VDMOS `1=D 2=G 3=S`). `Sim.Library`는 `${KICAD10_SYMBOL_DIR}` 같은 변수 경로를 우선 쓰고 kicad-cli가 풀지 못할 때만 절대경로로 두며, `export_spice_netlist`의 `missing_includes`로 존재를 확인한다. |
| C17 | 해석 지시문과 측정의 정본 위치를 정한다 | 회로도 text의 `.tran` 등은 `kicad-cli` SPICE 넷리스트에 포함된다(2026-10-22 `01-rc-step` 관측). `run_spice_simulation`은 `strip_existing_directives` 기본값 `true`로 이를 제거하고 호출 인자 `analysis`만 적용하므로, 어느 쪽을 정본으로 썼는지 결과에 적는다. ngspice 배치의 `.meas ac ... vdb()`는 `.save all` 없이는 해석을 건너뛴다. |
| C18 | 한 엔진의 통과를 다른 엔진으로 일반화하지 않는다 | `.meas` 문법은 엔진별로 생성된다(검증 기록: ngspice `AT=1m`, LTspice `AT 1m`). 로그 형식(LTspice CRLF), 코드모델(번들 45.2 미로드), 모델 방언(`ngbehavior`)도 다르다. `kicad-cli` 넷리스트는 접지를 `GND` 노드명으로 내보냈고 시스템 ngspice 배치는 이를 접지로 처리했다. LTspice 검증은 노드 `0`의 수기 넷리스트로만 했으므로, KiCad 넷리스트의 LTspice 실행은 첫 실행 전까지 `미검증`이다. 교차 판정은 같은 측정 정의와 경로 간 허용오차(계약 1%)로 한다. |
| C19 | ERC 0을 SPICE 모델 무결성으로 쓰지 않는다 | KiCad 10.0.6 기본 ERC는 `simulation_model_issue`(ERCE_SIMULATION_MODEL)를 ignore로 둔다. 시뮬레이션 범위에서는 `export_spice_netlist`의 `unassigned_models`·`missing_includes`를 0으로 만들고 프로젝트 ERC의 이 범주 상태를 기록한다. 심각도 변경은 `.kicad_pro` 쓰기이므로 별도 승인이 필요하다. |
| C20 | 동적 주장은 해석 측정값이 있을 때만 쓴다 | `kicad-review`의 `Better transient response on power rails`, 체크리스트의 `prevent ringing`·Reset RC·Crystal load caps 같은 동적 주장은 해당 해석의 측정값·모델 출처·허용오차가 없으면 제안 또는 `미확인`이다. `all_pass`는 `expectations`가 있을 때만 의미가 있고, 통과는 그 모델·파라미터·해석 조건 범위에 한정된다. 시뮬레이션이 범위인데 엔진 불가·미실행·측정 누락이면 C11에 따라 `INCOMPLETE`이며, C12처럼 제조·통전·정격 승인으로 확대하지 않는다. |
| C21 | 모델 출처를 증거로 남긴다 | 제조사 모델은 출처, 파일 SHA-256, 라이선스·재배포 조건, 암호화 여부, 문법(PSpice·LTspice면 `ngbehavior`), 서브서킷 핀 순서를 기록한다. 암호화 모델은 ngspice에서 쓸 수 없다. KiCad `Simulation_SPICE` 기본 소스나 level 1 일반 모델로 대체했으면 그 사실과 한계를 판정에 적는다. |

## 글로벌 흐름에 잇는 지점
| 글로벌 스킬·위치 | 이 패키지의 단계 |
|---|---|
| `konnect` Standard Workflow 6 `Verify` 뒤 | `simulation_extension` 확인 → 최소 흐름 |
| `konnect` Decision Tree(시뮬레이션 행 없음) | 실행·내보내기는 Channel 2, `set_simulation_model`은 Channel 1 |
| `konnect` Tool Usage Pattern 7 뒤 | 8 `export_spice_netlist`, 9 `run_spice_simulation` |
| `kicad-schematic` Verification Workflow 8 `save_project` 뒤(C10 저장 의미) | Sim readback → 넷리스트 진단 0 → 실행·판정 |
| `kicad-review` ERC 절 | C19 |
| `kicad-review` Full Review·Pre-Manufacturing Final verdict 앞, Reporting Verdict | 시뮬레이션 축 별도 보고, 미실행 INCOMPLETE(C20) |

위 도구 관측(기본값·readback·timeout)은 2026-10-22 중계 v1 기준이며 미래 schema를 고정하지 않는다. 호출 직전 current `tools/list`와 `simulation_extension`을 다시 확인한다.
