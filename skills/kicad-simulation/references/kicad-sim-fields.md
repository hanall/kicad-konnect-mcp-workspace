# KiCad 10 회로도에 시뮬레이션 모델 붙이기

이 문서는 KiCad 회로도에 붙는 Sim 필드·심볼·네트·지시어 규칙과 kicad-cli 넷리스트 형식을 소유한다. 도구 호출은 mcp-tools, 모델 출처는 vendor-models로 넘긴다.

관측 기준: KiCad 10.0.6 AppImage, `kicad-cli sch export netlist --format spice`, Konnect 0.13.0+hanall.1. 라이브러리 기본값은 `/opt/kicad/10.0.6/share/kicad/symbols/Simulation_SPICE.kicad_symdir`에서 읽은 값이다.

## Sim 필드

| 필드 | 의미 | 예 |
|---|---|---|
| `Sim.Device` | 소자 종류 | `R`, `C`, `L`, `D`, `NPN`, `NMOS`, `V`, `I`, `SUBCKT`, `SPICE` |
| `Sim.Type` | 모델 수준·파형 | NMOS: `MOS1`(level 1), `VDMOS`(기본). V: `DC`, `PULSE`, `SIN`, `PWL`, `EXP` |
| `Sim.Params` | 모델·인스턴스 파라미터, 공백 구분 `key=value` | `vto=2 kp=0.5 lambda=0 w=100u l=100u` |
| `Sim.Pins` | 심볼 핀 번호→모델 핀 순서 | `1=D 2=G 3=S`, `1=K 2=A` |
| `Sim.Library` | 외부 모델 파일 | `/abs/path/model.lib` |
| `Sim.Name` | 라이브러리 안 모델·서브서킷 이름 | `OPA1641` |
| `Sim.Enable` | `0`이면 시뮬레이션 제외 | |

`Device:R`, `Device:C`, `Device:L`은 Sim 필드 없이 Value로 모델이 만들어진다(`R1 in out 1k`). 다른 Device 심볼(D, Q 등)은 필드가 없으면 넷리스트에 `D1 __D1`처럼 모델 미할당으로 나온다.

## Simulation_SPICE 심볼 기본값

| 심볼 | Sim.Device / Type | 기본 Sim.Params | Sim.Pins |
|---|---|---|---|
| `VDC` | V / DC | `dc=…` | `1=+ 2=-` |
| `VPULSE` | V / PULSE | `y1=0 y2=1 td=2n tr=2n tf=2n tw=50n per=100n` | `1=+ 2=-` |
| `VSIN` | V / SIN | `dc=0 ampl=1 f=1k ac=1` | `1=+ 2=-` |
| `NMOS` | NMOS / VDMOS | 없음 | `1=D 2=G 3=S` |
| `D` | D | `rs=50m cjo=10p` | `1=K 2=A` |
| `OPAMP` | SUBCKT | `${KICAD9_SYMBOL_DIR}/Simulation_SPICE.sp`의 `kicad_builtin_opamp`(POLE=20 GAIN=20k VOFF=10m ROUT=10) | `1=in+ 2=in- 3=vcc 4=vee 5=out` |
| `BSOURCE` | SPICE | `type="B" model="v=1"` | N+, N- |

VPULSE 파라미터 이름은 KiCad 식(`y1 y2 td tr tf tw per`)이며 넷리스트에서 `PULSE(y1 y2 td tr tf tw per)`로 나간다. 기본값은 반드시 과제 값으로 덮어쓴다(예: `D`의 `rs=50m cjo=10p`를 그대로 두면 이상 다이오드가 아니다).

## 실측 함정(2026-10-22, Konnect 0.13.0+hanall.1 + kicad-cli 10.0.6)

1. **배치 도구는 라이브러리 Sim 필드를 인스턴스에 복사하지 않는다.** `add_schematic_component`·`batch_place_components`로 놓은 `Simulation_SPICE` 심볼은 `lib_symbols`에만 Sim.*가 있고 인스턴스에는 없다. 그 상태에서 kicad-cli는 rc=0으로 `V1 in GND DC VPULSE`(값 자리에 심볼 이름) 같은 잘못된 줄을 내보낸다. 배치 직후 `set_simulation_model`(또는 `batch_edit_schematic_components create_missing=true`)로 `Sim.Device`·`Sim.Type`·`Sim.Pins`(서브서킷은 `Sim.Library`·`Sim.Name`까지)를 라이브러리 기본값과 같게 **명시**하고 `Sim.Params`를 넣는다. `export_spice_netlist`의 `suspicious_values`와 `unassigned_models`가 이 실패를 잡는다.
2. **4단자 MOS 모델과 3핀 심볼.** `Sim.Type=MOS1`(및 MOS2/3, BSIM 계열) 모델 핀은 D,G,S,B 4개인데 `Simulation_SPICE:NMOS`는 3핀이라 벌크가 `NC-M1-0`으로 떠 버린다. `Sim.Pins`를 `1=D 2=G 3=S 3=B`로 두면 심볼 핀 3이 S와 B에 함께 매핑되어 `M1 d g GND GND`가 된다. KiCad GUI의 Simulation Model 대화상자는 핀당 모델 핀 하나만 보여 주므로 그 대화상자에서 저장하면 중복 매핑이 사라질 수 있다. 벌크가 소스와 다르면 `NMOS_Substrate`(4핀) 심볼을 쓴다.
3. **VDC는 Value가 DC 값이다.** `Simulation_SPICE:VDC`에는 Sim.Params가 없고 Value `1`이 DC 값 역할을 한다. `Sim.Params=dc=12`를 쓰면 Value도 `12`로 맞춰 표시와 넷리스트를 일치시킨다.
4. **PWR_FLAG는 GND 네트에 필요하다.** `power:GND`의 핀은 power_in이고 시뮬레이션 소스·R·C 핀은 passive라 ERC `power_pin_not_driven`이 GND에서 난다. GND 네트(그리고 `vee`처럼 power_in 핀이 있는 레일)에 `power:PWR_FLAG`를 붙이면 오류 0이 된다. 전압원 + 핀 네트의 플래그는 ERC에 영향이 없다. 넷리스트에는 나오지 않는다.
5. **`${KICAD9_SYMBOL_DIR}`는 휘발성 경로로 풀릴 수 있다.** 사용자 설정에 실행 중인 다른 KiCad AppImage의 `/tmp/.mount_…` 마운트가 저장돼 있어 `.include`가 그 GUI 종료 후 깨진다. 재현성이 필요하면 `Sim.Library`를 `/opt/kicad/<버전>/share/kicad/symbols/Simulation_SPICE.sp` 절대경로로 두고, 회로도에 호스트 경로가 기록됐음을 보고에 남긴다(두 파일의 SHA-256은 같다).
6. **ERC `lib_symbol_issues` 경고.** 격리 HOME(`.runtime-home`)이나 sym-lib-table이 없는 환경의 kicad-cli ERC는 `Simulation_SPICE`·`power`·`Device` 라이브러리를 찾지 못한다는 경고를 낸다. 심볼은 회로도에 내장돼 넷리스트에는 영향이 없다. 보호 파일인 라이브러리 테이블을 만들지 말고 경고를 기록한다.
7. **전역 라벨·GND.** 전역 라벨을 쓰면 넷 이름에 `/` 접두사가 없다. kicad-cli는 GND를 `GND`로 내보내고 ngspice 44.2·45.2는 이를 접지로 처리한다(수기 `0` 넷리스트와 6자리까지 동일한 측정값 실측).
8. **새로 만든 Sim.Params 필드의 위치.** 라이브러리의 justify를 물려받지 않아 가운데 정렬로 배선 위를 가로지를 수 있다. 숨김(`field_placements.hide`)으로 두거나 위치를 옮긴다.

## 네트 이름과 접지

- 측정 신호명은 넷 이름이다. 시트 로컬 라벨은 넷리스트에서 `/in`처럼 접두사가 붙으므로, 측정에 쓰는 네트는 **전역 라벨**(`connect_to_net`의 `label_type: global_label` 또는 `add_schematic_net_label` type `global_label`)로 붙인다.
- `power:GND` 심볼의 네트는 넷리스트에 `GND`로 나간다(KiCad 10.0.6은 `0`으로 바꾸지 않는다). ngspice는 `gnd`를 접지로 인식하지만 LTspice는 `0`만 접지다. LTspice 교차 실행용 넷리스트는 `GND`를 `0`으로 치환해야 한다(`run_spice_simulation`은 치환하지 않는다. 수기 넷리스트는 처음부터 `0`을 쓴다).
- 전압원 + 핀 네트에 `power:PWR_FLAG`를 두면 ERC의 "전원 입력 핀 미구동" 오류가 사라지며 SPICE 넷리스트에는 영향이 없다.

## 해석 지시어

- KiCad 편집기 시뮬레이터와 kicad-cli 넷리스트는 회로도 **텍스트 항목**의 `.tran 1u 5m`, `.ac dec 100 1 10meg`, `.meas …` 줄을 지시어로 포함한다. Konnect `sch_batch` toolset의 `add_schematic_text`로 넣는다.
- `run_spice_simulation`은 기본으로 기존 지시어를 제거하고 인자로 받은 해석만 적용한다. 회로도 텍스트는 KiCad GUI 시뮬레이터용으로 두고, MCP 판정은 인자로 통제한다.

## 외부 모델 경로

`OPAMP` 심볼 기본 `Sim.Library`는 `${KICAD9_SYMBOL_DIR}` 변수를 쓴다. kicad-cli 환경에서 이 변수가 풀리지 않으면 넷리스트의 `.include` 경로가 깨진다. `export_spice_netlist`의 `missing_includes`나 `.include` 경로가 `/tmp/.mount_…` 같은 휘발성 경로면 `set_simulation_model`의 `library`를 `/opt/kicad/<버전>/share/kicad/symbols/Simulation_SPICE.sp` 절대경로로 바꾸고(실측 함정 5), 회로도에 호스트 경로가 기록된다는 사실을 보고에 남긴다.

## KiCad 편집기 시뮬레이터(GUI)

- 메뉴 `Inspect → Simulator`. 회로도 텍스트의 지시어를 해석 탭으로 가져오고 `Run`, 신호 추가, `Measurements` 탭에서 `.meas` 결과를 본다. 엔진은 AppImage 번들 ngspice 45.2(`Help → About → Version`에 표시).
- 호환 모드는 시뮬레이터 설정에서 고른다(KiCad는 내부적으로 `set ngbehavior=psa|lta|ltpsa|hsa` 또는 `unset`을 보낸다).
- GUI 실행은 ACUW 레인에서만 하며, 같은 회로도를 MCP로 동시에 쓰지 않는다. 2026-10-22 실측: 검증 회로 5종을 `Inspect → Simulator`에서 실행해 17개 측정이 콘솔 `.meas` 출력(클립보드 텍스트)과 `File → Export current plot as CSV` 재계산 양쪽에서 이론값 2% 이내, 배치 경로와 상대 4.5e-6 이내로 일치했다. 회로도 텍스트의 `.meas` 줄은 넷리스트에 포함되어 콘솔에 `name = value`로 출력된다. `.tran`과 `.ac`가 함께 있으면 자동 생성 탭은 TRAN 하나뿐이라 AC 측정은 시뮬레이터에서 AC 탭을 추가해야 나온다. GUI는 넷리스트에 `.save all`·`.probe alli`를 덧붙인다. 종료 시 workbook·회로도 변경은 저장하지 않는다(쓰기는 MCP가 담당).

## kicad-cli 넷리스트 형식

```
.title KiCad schematic
R1 in out 1k
V1 in GND PULSE(0 5 0 1n 1n 10m 20m)
D1 __D1          ← 모델 미할당
.end
```

`.title` 줄이 첫 줄이고, 지시어 텍스트가 있으면 `.end` 앞에 들어간다. `Sim.Library`는 `.include "경로"`로 나간다.
