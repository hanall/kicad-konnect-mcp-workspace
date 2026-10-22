# 회로 시뮬레이션 MCP 도구 계약

## 적용 범위

사용자 요청(2026-10-22): 이번에 설치한 시뮬레이터를 **AI가 MCP로 사용자 대신** 쓸 수 있는 체계로 만든다. 새 도구는 `list_simulation_engines`, `export_spice_netlist`, `set_simulation_model`, `run_spice_simulation` 4개다. 기존 Rust Konnect와 release binary, 잠금 파일은 바꾸지 않는다. GUI 안전 인계(`synchronize_schematic_edit`)와 같은 프로젝트 STDIO 중계 패턴으로 `scripts/konnect-mcp-sim.py`가 도구를 추가하며, 회로도 쓰기는 upstream `edit_schematic_component`만 수행한다. 엔진 실행은 Python stdlib와 이미 설치된 ngspice·KiCad AppImage·Wine LTspice·ACUW만 쓴다. 추가 의존성은 없다.

이 계약은 AI 작업 절차인 [`skills/kicad-simulation`](../../skills/kicad-simulation/SKILL.md)의 도구 정의 원본이다. 실제 schema는 현재 연결의 `tools/list`가 정본이다.

## 활성화와 체인

- `.mcp.json`, `.codex/config.toml`은 `KONNECT_GUI_SYNC=1`과 함께 `KONNECT_SIM=1`을 전달한다. `scripts/run-konnect.sh`는 `KONNECT_GUI_SYNC=1`이면 GUI 중계를, 그 upstream 호출에서 `KONNECT_SIM=1`이면 시뮬레이션 중계를, 마지막에 release binary를 실행한다. 두 중계는 각각 자기 upstream에 자기 변수만 `0`으로 내려 재귀를 끊는다.
- 새 연결부터 적용된다. 기존 연결을 임의 종료하지 않는다.
- 비활성화(rollback): 등록 env를 `KONNECT_SIM=0`으로 바꾸고 그 연결만 다시 연다. core 도구 수와 동작은 그대로다.
- `get_installation_info` 응답에 `simulation_extension{version, path, upstream_pid, tools, engines}`가 붙는다. 없으면 구 연결이다.

## 도구 요약

| 도구 | 쓰기 | 전제 | 핵심 응답 |
|---|---|---|---|
| `list_simulation_engines` | 없음 | 없음 | 엔진별 available·version·path·headless |
| `export_spice_netlist` | 없음(회로도 읽기, `.cir` 생성) | kicad-cli | `unassigned_models`, `missing_includes`, `directives`, `has_ground` |
| `set_simulation_model` | 회로도 Sim.* 필드 | `sch_components` 로드 | 적용 필드와 upstream 결과 |
| `run_spice_simulation` | 작업 디렉터리에 넷리스트·로그 | 엔진 설치, ltspice는 `lane` | `measurements`, `expectations[].pass`, `all_pass`, `waveforms`, `warnings`, `errors` |

입력·출력·예시는 [mcp-tools](../../skills/kicad-simulation/references/mcp-tools.md).

## 안전 조건

- 모든 경로는 절대경로. 회로도는 `.kicad_sch`만 받고 텍스트로 편집하지 않는다.
- 입력 경계(2026-10-22 v1): 읽기(회로도·넷리스트·`.include`)는 레포·사용자 홈·`/opt/kicad`·`/usr/share`·`/usr/lib`·`/usr/local/share` 아래, 쓰기(작업 디렉터리·출력·Sim 필드가 들어갈 회로도)는 레포 안 또는 `KONNECT_SIM_ALLOWED_ROOTS`(콜론 구분)로 추가한 루트만 허용한다. 입력 넷리스트의 `.control`~`.endc`는 `strip_existing_directives` 값과 무관하게 항상 제거한다(ngspice 배치는 `.control`의 `shell`로 OS 명령을 실행하므로). `directives`와 `analysis.args`는 지시어 접두사 화이트리스트와 제어 토큰(`shell`, `source`, `write`, `set`, `cd` 등) 거부로 검사한다. `.include`·`.lib` 대상은 허용 루트와 `.control` 부재를 확인한다. `save_signals`는 신호명 형식만 받는다. 거부 입력 회귀는 `tests/test_sim_mcp_extension.py`의 `test_08`·`test_09`다.
- `export_spice_netlist`의 기본 출력은 `.artifacts/sim-exports/`이며 사용자 프로젝트 디렉터리에 파일을 만들지 않는다. 진단에 `suspicious_values`(값 자리에 심볼 이름)와 `include_problems`를 포함한다.
- `set_simulation_model`은 쓰기 뒤 `get_schematic_component`로 readback해 `readback_matches`를 돌려준다. 품질 스킬의 guarded 어댑터 경로 밖에서 쓰는 도구이므로, 회로도 품질 단서가 있는 작업에서는 품질 스킬의 모드·계획·allowlist를 먼저 적용한다.
- `run_spice_simulation`은 기존 `.tran/.ac/.meas/.control` 줄을 제거하고 호출 인자만 적용한다(기본). 회로도의 지시어 텍스트는 KiCad GUI용으로 남는다.
- `timeout_seconds`는 5~100으로 제한한다. GUI 중계가 upstream 응답을 120초까지만 기다리고 초과 시 자기 연결을 종료하기 때문이다. 긴 해석은 CLI로 돌린다.
- `ngbehavior`는 작업 디렉터리 `.spiceinit`에만 쓴다. 홈 `.spiceinit`은 만들지 않는다.
- 기본 작업 디렉터리는 `.artifacts/sim-runs/<시각>-<stem>/`(Git 추적 밖). 보고 증거는 `docs/검증/`로 복사한다.
- `DERIVED` 식은 AST 화이트리스트(산술·일부 수학 함수)만 평가한다. 임의 코드 실행이 없다.
- `ltspice` 엔진은 ACUW 레인의 `run-in-workspace.sh --wait`로만 실행하고 `ACUW_LANE_MEMORY_MAX`가 없으면 16G를 준다. 레인을 열거나 닫지 않는다.
- `isError=false`여도 `errors`, `missing_measurements`, `all_pass`를 읽어야 한다. 측정 일치는 실물 안전·정격 승인이 아니다.

## 공개 API 호환성

- upstream 도구 이름·schema는 변경 없음. `tools/list`에 4개가 추가되고 `get_installation_info` 본문에 키 하나가 추가된다. 기존 클라이언트는 새 키를 무시해도 된다.
- migration: 없음(env만). Codex는 `default_tools_approval_mode = "writes"` 그대로다. `set_simulation_model`과 `run_spice_simulation`은 파일을 쓰므로 승인 대상이다.
- rollback: `KONNECT_SIM=0`.
- 회귀: `make test-sim-mcp`(`tests/test_sim_mcp_extension.py` 10건 + `KONNECT_SIM=1 KONNECT_GUI_SYNC=1` 스모크). 전체 gate `make test`에도 포함된다(`tests/test_*.py` discover).

## 이번 검증 증거

- `make test-sim-mcp`: `tests/test_sim_mcp_extension.py` 13건 통과 + `KONNECT_SIM=1 KONNECT_GUI_SYNC=1` 체인 스모크 통과(starter 도구 27개 = core 22 + GUI 인계 1 + 시뮬레이션 4). 시험 내용: tools/list 노출, installation_info 확장, 엔진 목록, RC 회로 실행·판정(all_pass, 파형 CSV), 데모 회로도 모델 미할당 진단(`J1`), **데모 프로젝트 복사본에서 `set_simulation_model`(D1) → `export_spice_netlist` 왕복으로 미할당 목록에서 D1 제거 확인과 원본 SHA 불변**, 잘못된 인자 거부, **입력 넷리스트·지시어·`analysis.args` 세 경로의 `.control`/`shell` 무력화(마커 파일 미생성 확인)**, **허용 루트 밖 `work_dir`·`output` 거부**, 측정 문법·안전 식 평가·넷리스트 진단(`suspicious_values`)·LTspice 로그 파싱 단위시험.
- 기존 계약 시험(`test_project_contract`, `test_runtime_home_isolation`, `test_upstream_policy`, `test_schematic_gui_sync`) 30건이 MCP 등록 변경 뒤에도 통과했고, root Python 시험 전체(`python3 -m unittest discover -s tests`) 211건이 통과했다(품질 스킬 107건 포함, 2026-10-22 19:0x).
- 엔진 탐지 실측: system-ngspice 44.2, kicad-bundled 45.2, ltspice 24.0.12.0, qucs-s 26.1.1, kicad-cli 10.0.6.
- 검증 회로 5종의 네 경로 결과는 [설치 계약](20261022-172859_circuit-simulators-linux.md)과 [보고서](../보고서/20261022-172859_circuit-simulators-linux.html).
- KiCad GUI 시뮬레이터 수치 검증(2026-10-22, ACUW 레인 `kicad-smps-sync-gui`): Konnect MCP로 작성한 회로도 사본 5종에 `add_schematic_text`로 `.meas`를 넣고 eeschema `Inspect → Simulator`로 실행해 17/17 측정이 이론값 2% 이내, 배치 경로와 4.5e-6 이내로 일치했다. 적대적 재판독 5/5 confirmed. 증거는 `projects/sim-validation-20261022/kicad-gui/`와 `docs/검증/20261022-172859-circuit-simulators/screenshots/kicad-gui-*`.
