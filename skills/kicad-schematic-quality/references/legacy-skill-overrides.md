# 기존 KiCad 스킬 교정 오버레이

이 문서는 기존 `konnect`, `kicad-schematic`, `kicad-review`를 함께 호출하는 환경에서 적용할 이식 가능한 교정 정본이다. 외부 스킬이 없어도 `SKILL.md`와 다른 내부 reference만으로 필수 안전 규칙은 완결된다.

## 적용 우선순위

1. 이 패키지의 직접 텍스트 CAD 수정 금지, 단일 작성자, GUI/MCP 비동시, lock 우회 금지
2. 현재 프로젝트의 더 강한 제한, 요구·승인·설계 계약
3. 현재 연결의 실제 runtime schema, version·commit, readback
4. 선택한 profile과 선행 고정 semantic 계약
5. 기존 스킬의 일반 예제

프로젝트가 GUI 쓰기를 승인했는지는 호출별 입력이다. 한 프로젝트의 영구 승인을 다른 프로젝트에 복사하지 않는다.

## 이식 가능한 필수 교정 C01~C13

| ID | 교정 규칙 | 적용 방법 |
|---|---|---|
| C01 | 현재 build·schema가 먼저다 | `get_installation_info`와 fresh `tools/list`가 없으면 tool 수·서명·coverage를 `unknown`으로 둔다. 일부 toolset에서 본 개수를 전체 수라고 쓰지 않는다. |
| C02 | 모드와 권한을 분리한다 | `design`, `rewrite`, `change`, `review`를 먼저 고르고 `review`에서는 CAD 쓰기·저장 0을 유지한다. |
| C03 | 실선과 label을 분리한다 | local 기능 흐름은 solid wire를 우선한다. 현재 관측 schema의 `batch_connect_to_net` 기본 `stub_length=0`은 wire 없는 endpoint label이므로 명시 stub/wire 또는 검토된 waiver와 readback 없이는 완료가 아니다. |
| C04 | physical pin map이 필수다 | 정확한 MPN/package lead, symbol pin, footprint pad, drawing view를 결속하고 query-back·render로 확인한다. 일반 library ID나 성공 응답만으로 대체하지 않는다. |
| C05 | `PWR_FLAG`에는 source 근거가 필요하다 | 실제 외부·수동 power source를 ERC 모델에 나타낼 때만 사용하며 단순 경고 억제에는 쓰지 않는다. |
| C06 | ERC는 owning root에서 hierarchy 전체를 검사한다 | child sheet 단독 결과를 전체 ERC로 승격하지 않고 root schematic, 원 report·rc, sheet coverage, 제외·비활성 규칙을 기록한다. |
| C07 | aggregate는 direct check의 대체가 아니다 | `run_design_review`와 `audit_*` 결과를 직접 ERC, short·orphan·single-pin 후보, net·saved/exported connectivity와 독립 실행·대조한다. |
| C08 | schematic과 PCB 거리를 분리한다 | `audit_decoupling` 또는 회로도상 근접으로 PCB proximity를 주장하지 않는다. connectivity, 값, PCB placement를 별도 검사한다. |
| C09 | 정격·전류는 profile 계산 대상이다 | `audit_power_rails`가 current capacity, voltage, sequencing을 검사한다고 가정하지 않고 요구·원문·계산·ERC를 별도 증거로 쓴다. |
| C10 | 저장 의미를 정확히 쓴다 | offline schematic MCP edit는 atomic file commit·readback·파일 SHA로 확인한다. `save_project`는 현재 관측상 live PCB IPC 저장이므로 schematic 저장 증거로 쓰지 않는다. |
| C11 | coverage gap은 `INCOMPLETE`다 | required check 미실행, partial/failed, impossible zero, source 불일치, unresolved contradiction을 PASS로 쓰지 않는다. |
| C12 | 제조·발주 승인을 분리한다 | ERC/DRC/제한 audit/`READY`를 fabrication artifact, BOM/CPL, fab profile, order preview, safety review, 사람의 명시 발주 승인으로 확대하지 않는다. |
| C13 | symbol query 성공과 pin 완전성을 분리한다 | `isError=false`여도 pin 수 0, 빈 pins, unit·상속 누락, exact package 불일치이면 `INCOMPLETE`다. 대안 조회와 배치 후 physical map을 확인한다. |

위 표의 현재 도구 관측은 호환성 결함을 설명하는 기준이며 미래 schema를 고정하지 않는다. 실제 호출에서는 항상 C01을 먼저 적용한다.

## `konnect` 교정

| 기존 지침에서 위험한 일반화 | 이 패키지에서의 적용 |
|---|---|
| 모든 수정은 MCP만 가능 | 직접 텍스트 수정은 항상 금지한다. GUI 쓰기는 **현재 프로젝트가 명시 승인한 경우에만** 별도 채널로 허용하며 MCP와 동시에 쓰지 않는다. |
| 고정 도구 수·toolset 목록 | 현재 `tools/list`와 각 tool schema를 조회한다. 숫자나 오래된 목록을 계약으로 쓰지 않는다. |
| Schematic Editor는 GUI 없이 file engine으로 안전 수정 | 프로젝트가 승인한 launcher·guarded adapter·계획·allowlist·lock·readback을 모두 만족해야 한다. engine 존재만으로 쓰기 권한이나 무결성을 주장하지 않는다. |
| exported 파일만 읽고 source는 피함 | native export를 우선하되 hierarchy·표제·보존 검증에 필요한 source 읽기는 최후 수단으로 허용한다. 읽기와 텍스트 수정을 구분한다. |
| 고정 설계 규칙과 부품값 | 요구·제조사 원문·profile에서 정한다. 일반값은 채택 근거가 아니다. |
| 도구 호출 성공 뒤 완료 | saved/live 상태, 대상 객체 readback, 저장·재열기, native export와 scope별 검증이 필요하다. |

구식 예제의 `connect_pins(from_component, from_pin, to_component, to_pin)`, `connect_to_net(component_reference, pin_number, net_name)`, `add_power_symbol(component_reference, pin_number, power_net)` 서명은 현재 관측 schema와 맞지 않는다. 현재 관측에서는 각각 schematic과 ref/pin 양쪽, schematic·net과 ref/pin 또는 좌표, schematic·power net·좌표가 필요했다. 이 서술도 미래 서명은 아니므로 호출 직전 current schema의 required field를 다시 확인한다.

## `kicad-schematic` 교정

| 기존 지침에서 위험한 일반화 | 이 패키지에서의 적용 |
|---|---|
| 시작 시 고정 toolset을 무조건 load | 현재 schema에서 실제 필요한 nonempty toolset만 load한다. metadata-only에서는 빈 load를 보내지 않는다. |
| 일반 library 표로 pin·극성 결정 | 현재 설치 심볼의 모든 unit·pin과 제조사 package 표를 대조한다. 현재 관측한 `Device:D`와 `Device:LED`는 pin 1=K, pin 2=A였지만 다른 library·symbol에 일반화하지 않고 실제 설치본을 다시 확인한다. |
| 모든 배치를 고정 grid·간격으로 강제 | 용지·grid·간격은 profile 입력이다. 실제 출력과 기능 구역에 맞춰 결정한다. |
| 가까운 pin은 거리 숫자로 자동 실선, 이름 있는 신호는 label | 로컬 기능 loop는 실선으로 닫고 장거리·페이지 경계만 계약된 label/port를 쓴다. 거리 하나가 전기·가독성 결정을 대신하지 않는다. |
| power symbol은 항상 자동 연결 | 공급·return·절연 domain을 먼저 확인한다. 보기 편한 generic VCC/GND로 치환하지 않는다. |
| `PWR_FLAG`로 power ERC 해결 | 실제 전원 공급 근거가 있을 때만 사용한다. 경고 억제를 위해 넣지 않는다. |
| `save_project`를 자주 호출 | 현재 관측상 인자 없는 live PCB IPC 저장이며 offline schematic 저장이 아니다. schematic은 승인 adapter의 atomic commit, readback, 파일 SHA로 확인한다. 읽기 전용 리뷰에서는 저장 0이다. |
| batch 3개 이상을 품질 규칙으로 사용 | batch는 효율 선택일 뿐이다. 기능 소회로, 원자 request, 실패 후 readback 경계가 우선이다. |
| decoupling의 회로도상 거리로 PCB 근접 판정 | 회로도 연결과 PCB 물리 placement를 분리한다. 회로도만으로 거리·SI 성능을 승인하지 않는다. |

현재 설치본에서 조회 실패가 확인된 구 ID 예로 `Device:Q_NPN_BCE`, `Device:Q_PNP_BCE`, `Device:Q_NMOS_GDS`, `Device:Q_PMOS_GDS`, `Device:Ferrite_Bead`, `Regulator_Linear:MCP1700-3302E_SOT23`, `Interface_USB:CP2102N-A02-GQFN24`가 있다. 이 목록을 새 고정 blacklist로 쓰지 말고 `search_symbols`, 현재 library source, exact MPN/package pin map으로 선택한다. 반대로 조회 성공도 C13의 완전성 관문을 통과해야 한다. rotation과 mirror도 같은 동작으로 보지 말고 실제 render로 확인한다.

## `kicad-review` 교정

| 기존 지침에서 위험한 일반화 | 이 패키지에서의 적용 |
|---|---|
| review 전에 저장 | `review` 모드는 현재 저장본·live 상태를 명시하고 저장·수정 0을 유지한다. 미저장 상태가 있으면 그 사실을 보고하고 권위자에게 인계한다. |
| 모든 review에서 schematic·PCB·제조 toolset 전부 load | 요청 범위에 해당하는 조회만 실행한다. schematic 검토를 DRC·제조 감사로 자동 확대하지 않는다. |
| 모든 orphan·single-pin net은 오류 | NC, test point, intentional stub 등 원문과 pin 계약으로 개별 판정한다. unknown을 오류 0이나 critical로 합성하지 않는다. |
| short 탐지 결과는 언제나 확정 critical | detector의 범위·오탐 가능성과 native 연결을 대조한다. 확정 short는 차단하지만 tool label만으로 결론내지 않는다. |
| 모든 DRC 오류를 고치면 제조 가능 | PCB 범위와 승인된 waiver를 따로 판정하며 회로도 review를 제조 승인으로 승격하지 않는다. |
| decoupling·power audit가 값·용량·근접을 증명 | 원문, 예상 부하, PCB placement, 실제 도구 관측이 필요하다. schematic audit 단독 결과는 제안 또는 미확인이다. |
| quick/full review를 항상 고정 순서로 실행 | 위험과 사용자 범위에 비례한다. 작은 승인 변경은 영향 검사만 하되 전체 연결 회귀가 필요한 경우를 별도 판단한다. |
| review 뒤 즉시 fix 제안·실행 | 수정 제안과 CAD mutation은 별도 승인·모드·계획이다. 읽기 전용 세션에서는 실행하지 않는다. |
| PASS/FAIL 한 줄 | 요구·전기·시각·증거 축, saved/live, 경고·비활성·예외, scope를 분리한다. |

현재 관측 coverage는 다음처럼 제한된다. 미래 판본에는 다시 확인한다.

| 도구·주장 | 확인된 한계 | 필요한 보완 |
|---|---|---|
| `audit_esd_protection` | 현재 registry/schema에 없는 phantom 이름 | interface threat·rating profile과 수동 근거로 남기고 다른 audit 성공으로 대체하지 않음 |
| `run_design_review` | ERC와 `find_orphan_items`, `find_shorted_nets`, `find_single_pin_nets`를 실행하지 않음 | aggregate와 direct checks를 별도 실행·대조 |
| `audit_decoupling` | schematic 같은-net capacitor heuristic이며 PCB 거리·값·bulk·고전류 적합성을 증명하지 않음 | 원문 값, net 계약, 실제 PCB placement를 별도 검사 |
| `audit_connections` | I2C와 reset pull-up 중심의 제한 검사 | expected fanout, SI, enable, LED, floating, output conflict를 요구 기반으로 별도 검사 |
| `audit_power_rails` | 전류 용량·전압 적합성·sequence·`PWR_FLAG` 근거를 검사하지 않음 | rating/profile 계산과 ERC·원문 증거를 별도 대조 |
| manufacturing audit | 제한 heuristic이며 모든 outline·spacing·via·drill·pad·조립 조건을 증명하지 않음 | native DRC, closed outline, fab profile, BOM/CPL, 산출물·preview를 별도 확인 |

`find_orphan_items`, `find_shorted_nets`, `find_single_pin_nets`는 후보 탐지다. hierarchy/global scope, intentional tie, NC, test point, intentional stub, native ERC와 실제 요구를 대조한 뒤 severity를 정한다. 자동 결과가 polarity, absolute maximum, 제품 위험 등급을 스스로 입증한다고 가정하지 않는다.

## 프로젝트 호출 지침에 연결하는 방법

프로젝트의 agent 지침에서 회로도 신규 설계·재작성·전기 변경·읽기 전용 검토는 먼저 `kicad-schematic-quality`로 routing하고, 실제 CAD 도구가 필요할 때만 기존 도구 스킬을 이어 호출한다. 충돌 시 이 문서의 교정과 현재 runtime schema를 기존 스킬 예제보다 우선한다고 명시한다.

이 routing은 GUI 승인이나 쓰기 권한을 만들지 않는다. 각 프로젝트는 자신의 authority 문서, allowlist, launcher/config, version·commit, 승인 채널을 별도로 제공해야 한다.
