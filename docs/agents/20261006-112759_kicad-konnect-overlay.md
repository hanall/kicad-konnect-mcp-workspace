# KiCad·Konnect 프로젝트 스킬 오버레이

## 정본과 구식 스킬 교정

글로벌 스킬 본문은 외부 저장소이므로 수정하지 않습니다. 충돌 시 이 프로젝트 오버레이, checkout의 도구 schema와 실제 KiCad 10.0.6 관측이 우선합니다.

| 주제 | 적용 규칙 |
|---|---|
| 도구 개수 | 구 스킬의 187/18, 구 문서의 193개를 사용하지 않습니다. 현재 Linux STDIO는 228 domain + 8 meta = 236개, 21 toolset이며 실행 `tools/list`가 정본입니다. 프로젝트 중계 확장이 `KONNECT_GUI_SYNC=1`로 1개, `KONNECT_SIM=1`로 4개를 더 노출합니다(core 수는 그대로). |
| 파일 수정 | 직접 텍스트/스크립트 편집은 금지합니다. MCP 또는 사용자가 보는 공유 화면의 KiCad GUI로 수정합니다. **GUI 직접 편집은 사용자 영구 승인(2026-10-07)**이며 글로벌 스킬의 MCP 전용 문구보다 우선합니다. 회로 원문 읽기는 export로 알 수 없는 보존 검증의 최후 수단입니다. |
| 공유 화면 GUI 승인 | 사용자 원문: 「공유 화면의 KiCad GUI에서 직접 편집하세요, 영구 승인함.」 프로젝트 생성·저장, 용지·표제란, 심볼·속성·배선·검증을 실제 공유 창에서 직접 수행할 수 있으며 재승인을 요구하지 않습니다. GUI/MCP 동시 쓰기와 살아 있는 편집기 잠금 삭제·우회는 금지합니다. 미저장 변경을 보존하고 GUI 저장 뒤 확인합니다. commit·push·제조·통전 승인은 별개입니다. |
| diode·LED 극성 | symbol pin 번호를 추측하지 않습니다. `Device:LED`는 pin 1=K, pin 2=A입니다. symbol 정의·footprint pad·실제 netlist를 각각 대조합니다. |
| PCB 상태 | live IPC 상태와 saved file은 서로 다른 원본입니다. 실패 시 조용히 파일 fallback하지 않습니다. |
| footprint 갱신 | 기존 point/필드/UUID/net/group 손실을 허용하지 않습니다. closed-file opt-in은 현재 dry-run revision과 닫힌 exact board를 요구하며 불명확한 객체를 거부합니다. |
| 경고 제거 | DRC 경고를 끄거나 ignore 목록으로 숨기지 않습니다. 라이브러리 geometry/필드를 교정한 뒤 ERC/DRC 전체 범주를 재확인합니다. |
| 뷰어 | 개선판은 Tauri가 아닌 loopback browser viewer입니다. 실제 SVG·브라우저 ACK를 받기 전 ready로 승격하지 않습니다. |
| 성공 범위 | mock, 단위시험, schema 거부, GUI 실행, 실제 전기시험을 구분합니다. 236개 호출 통과를 모든 인자·OS 무결성으로 표현하지 않습니다. |
| 시뮬레이션 | 글로벌 세 스킬에는 시뮬레이션 지침이 없습니다. KiCad 10.0.6의 회로도 IPC는 `GetOpenDocuments`만 등록하고 `kicad-cli sch`는 `erc`·`export`·`upgrade`뿐이라 시뮬레이션을 실행하지 않습니다. 실행은 `KONNECT_SIM=1` 중계가 시스템 ngspice 44.2, KiCad 번들 ngspice 45.2, LTspice 24.0.12(Wine, 레인)로 하며 Qucs-S 26.1.1은 GUI 전용입니다. KiCad 10.0.6 기본 ERC는 `simulation_model_issue`를 무시하므로 ERC 0을 모델 무결성으로 쓰지 않습니다. 교정 C14~C21은 [`kicad-simulation`](../../skills/kicad-simulation/SKILL.md) 패키지를 따릅니다. |

## 기본 순서

```text
schema -> backup -> dry-run -> revision -> apply -> readback -> ERC/DRC
  -> (시뮬레이션 범위) simulation_extension -> Sim 모델 readback
  -> export_spice_netlist 진단 0 -> run_spice_simulation -> 기대값 판정 -> (선택) 교차 엔진
```

- 정본 실행기는 `scripts/run-konnect.sh`입니다. 오래 살아 있는 MCP 프로세스는 디스크 binary와 다를 수 있으므로 PID/exe SHA와 initialize version을 대조합니다.
- 공유 checkout에서는 파일 소유권을 명시하고 release binary 교체는 조율 담당만 수행합니다. 최종 runner는 고정 SHA 전후 일치를 확인합니다.
- 상세 검증·rollback은 `docs/20261006-112759_업그레이드-및-검증-계약.md`를 따릅니다.
- 회로 동작 검토가 범위에 있으면 ERC 뒤에 시뮬레이션 단계를 둡니다: `get_installation_info`의 `simulation_extension` 확인 → `set_simulation_model`로 Sim 필드 지정 → `export_spice_netlist` 진단 0 → `run_spice_simulation`으로 기대값 판정. 절차는 [`skills/kicad-simulation`](../../skills/kicad-simulation/SKILL.md), 도구 계약은 [`20261022-172859_simulation-mcp-tools.md`](20261022-172859_simulation-mcp-tools.md)입니다. 측정 일치는 정격·실물 안전 승인이 아닙니다.
