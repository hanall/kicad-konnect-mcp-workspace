# 시뮬레이션 MCP 도구

이 문서는 시뮬레이션 MCP 도구 4종의 인자·응답·오류·제한을 소유한다. 회로도 필드 규칙은 kicad-sim-fields, 측정·판정은 measurements, 엔진 설치·레인은 engines로 넘긴다.

`scripts/konnect-mcp-sim.py`가 `KONNECT_SIM=1`일 때 Konnect STDIO에 도구 4개를 추가한다. 프로젝트 `.mcp.json`·`.codex/config.toml`은 기본으로 켠다. 실제 schema는 현재 연결의 `tools/list`가 정본이다. 계약·되돌리기는 `docs/agents/20261022-172859_simulation-mcp-tools.md`.

## 공통

- 모든 경로는 **절대경로**. 상대경로·홈 축약은 `invalid_argument`로 거부된다.
- 입력 경계: 회로도·넷리스트·`.include` 읽기는 레포, 사용자 홈, `/opt/kicad`·`/usr/share`·`/usr/lib`·`/usr/local/share` 아래만, 작업 디렉터리·출력 쓰기는 레포 안(`.artifacts/` 기본)만 허용한다. 다른 루트는 중계 실행 환경에 `KONNECT_SIM_ALLOWED_ROOTS=/path1:/path2`로 추가한다. 입력 넷리스트의 `.control`~`.endc`는 옵션과 무관하게 제거되고, `directives`는 `.model`·`.include`·`.lib`·`.param`·`.option(s)`·`.ic`·`.nodeset`·`.temp`·`.global`·`.func`·`.subckt`·해석·`.meas`·`.save` 접두사만 허용하며 `shell`·`source`·`write`·`set` 같은 제어 토큰이 있으면 거부한다. `.include` 대상 파일에 `.control`이 있으면 거부한다.
- 오류는 `isError=true`와 본문 `{"error": {"kind": ..., "message": ...}}`로 온다. kind: `invalid_argument`, `not_found`, `toolset_not_loaded`, `export_failed`, `engine_failed`, `upstream_tool_error`, `upstream_timeout`, `not_initialized`.
- `timeout_seconds`는 5~100. GUI 동기화 중계(`KONNECT_GUI_SYNC=1`)가 upstream 응답을 120초까지만 기다리므로 더 긴 해석은 넷리스트를 나누거나 CLI(`scripts/sim-validation-run.py`, `ngspice -b`)로 돌린다.
- `get_installation_info` 응답에 `simulation_extension.tools`와 `engines`가 붙는다. 없으면 이 연결에는 중계가 없다.

## list_simulation_engines

입력: `probe_bundled_version`(기본 true, 번들 libngspice를 로드해 버전 확인 약 1초).
출력: `engines.{system-ngspice, kicad-bundled-ngspice, ltspice, qucs-s, kicad-cli}` 각각 `available`, `path`, `version`, `headless`와 비고. 시뮬레이션 작업의 첫 호출로 쓴다.

## export_spice_netlist

입력: `schematic`(루트 `.kicad_sch`), `output`(선택, 기본 `<레포>/.artifacts/sim-exports/<시각>-<stem>.cir`. 사용자 프로젝트 안에는 파일을 만들지 않는다).
동작: `kicad-cli sch export netlist --format spice`. 회로도는 읽기만 한다.
출력: `netlist_text`, `netlist_path`, `diagnostics.{unassigned_models, suspicious_values, includes[], missing_includes, directives, has_ground, element_count}`, `include_problems`.

- `unassigned_models`: 넷리스트에 `D1 __D1`처럼 모델 없이 나온 심볼. 모델을 지정하거나 시뮬레이션에서 제외한다.
- `suspicious_values`: `V1 in GND DC VPULSE`처럼 값 자리에 심볼 이름이 들어간 소스. 배치 도구가 라이브러리 Sim 필드를 인스턴스에 복사하지 않아 생긴다(kicad-sim-fields 실측 함정 1). `set_simulation_model`로 Sim.Device/Type/Pins/Params를 명시한다.
- `include_problems`: `.include` 대상이 허용 루트 밖이거나 `.control`을 포함한다.
- `missing_includes`: `Sim.Library` 경로가 실제 파일로 풀리지 않음. 절대경로로 고친다.
- `directives`가 비어 있으면 회로도에 해석 지시어가 없다. `run_spice_simulation`의 `analysis`로 준다.

## set_simulation_model

입력: `schematic`, `reference`, 그리고 `device`(Sim.Device), `type`(Sim.Type), `params`(Sim.Params), `pins`(Sim.Pins), `library`(Sim.Library), `name`(Sim.Name), `enable`(Sim.Enable), `clear[]`.
전제: `sch_components` toolset이 로드되어 있어야 한다(`load_toolset`). 아니면 `toolset_not_loaded`.
동작: upstream `edit_schematic_component`의 `fields`로 Sim 필드만 쓴다. 다른 필드는 건드리지 않는다. `library`는 파일 존재를 확인한다(변수 포함 경로는 통과). 저장 뒤 `get_schematic_component`로 readback해 `readback_fields`·`readback_matches`를 돌려준다. `readback_matches`가 `false`면 `readback_mismatch`를 보고 다시 쓰며, `null`이면 응답 형식을 해석하지 못한 것이므로 `get_schematic_component`로 직접 확인한다. 회로도가 쓰기 허용 루트 밖이면 거부한다.

예: level 1 NMOS

```json
{"schematic": "/abs/x.kicad_sch", "reference": "M1", "device": "NMOS", "type": "MOS1",
 "params": "vto=2 kp=0.5 lambda=0 w=100u l=100u", "pins": "1=D 2=G 3=S"}
```

예: 제조사 서브서킷

```json
{"schematic": "/abs/x.kicad_sch", "reference": "U1", "device": "SUBCKT",
 "library": "/abs/models/opa1641.lib", "name": "OPA1641", "pins": "1=in+ 2=in- 3=vcc 4=vee 5=out"}
```

## run_spice_simulation

입력(하나만): `netlist`(`.cir`) 또는 `schematic`(먼저 내보냄). 공통: `engine`, `analysis{type,args}`, `directives[]`, `measurements[]`, `expectations[]`, `save_signals[]`, `ngbehavior`, `lane`(ltspice), `work_dir`, `strip_existing_directives`(기본 true), `timeout_seconds`.
동작: 기존 `.tran/.ac/.meas/.control` 줄을 제거하고 인자로 받은 해석·측정·지시어를 붙인 실행 넷리스트 `<stem>.<engine>.cir`를 작업 디렉터리에 쓴 뒤 엔진을 배치 실행한다. ngspice에서 `save_signals`는 `wrdata waves.csv`로 저장한다. `ngbehavior`는 작업 디렉터리 `.spiceinit`로 적용한다(홈 `.spiceinit`은 만들지 않는다).
출력: `engine{name,version,path}`, `work_dir`, `netlist_path`, `log_path`, `measurements{name:value}`, `missing_measurements`, `expectations[{name,theory,value,err_rel|err_abs,pass}]`, `all_pass`, `waveforms{signal:{csv,points,min,max,final}}`, `diagnostics`, `warnings`, `errors`.

예: RC 과도응답 판정

```json
{"netlist": "/abs/rc.cir", "engine": "system-ngspice",
 "analysis": {"type": "tran", "args": "1u 5m"},
 "measurements": [
   {"name": "v_at_tau", "kind": "FIND", "signal": "v(out)", "at": "1m"},
   {"name": "t_rise", "kind": "TRIG_TARG", "signal": "v(out)", "trig_val": 0.5, "targ_val": 4.5}
 ],
 "expectations": [{"name": "v_at_tau", "theory": 3.1606, "tol_rel": 0.02},
                  {"name": "t_rise", "theory": 0.0021972, "tol_rel": 0.02}],
 "save_signals": ["v(out)"]}
```

예: 회로도에서 바로, KiCad 내장 엔진으로 AC 이득

```json
{"schematic": "/abs/amp.kicad_sch", "engine": "kicad-bundled-ngspice",
 "analysis": {"type": "ac", "args": "dec 100 1 10meg"},
 "measurements": [{"name": "g10", "kind": "AC_FIND_DB", "signal": "v(out)", "at": "10"},
                  {"name": "f3", "kind": "AC_WHEN_DB", "signal": "v(out)", "val": 16.9957, "edge": "FALL=1"}]}
```

예: LTspice 교차 실행(레인 필요)

```json
{"netlist": "/abs/rc.cir", "engine": "ltspice", "lane": "kicad-standard-quality",
 "analysis": {"type": "tran", "args": "1u 5m"},
 "measurements": [{"name": "v_at_tau", "kind": "FIND", "signal": "v(out)", "at": "1m"}]}
```

## 판정 해석

- `all_pass`는 `expectations`가 있을 때만 의미가 있다. 없으면 관측만이다.
- `missing_measurements`가 비어 있지 않으면 해석이 중단됐거나 신호명이 틀린 것이다. `log_path`를 읽는다.
- `warnings`에 "singular matrix", "timestep too small", "no data saved"가 있으면 결과를 쓰지 않는다.
- 엔진 간 교차(1%)는 같은 넷리스트를 `engine`만 바꿔 다시 실행해 비교한다.

## CLI 동등물

MCP 없이 같은 일을 하려면 `python3 scripts/sim-validation-run.py --engine {system|kicad-bundled}`(사양 기반 회귀)와 `ngspice -b -o run.log run.cir`를 쓴다. Qucs-S 배치는 `qucs-s -n -i x.sch -o x.dat --ngspice --run`(레인 DISPLAY 필요).
