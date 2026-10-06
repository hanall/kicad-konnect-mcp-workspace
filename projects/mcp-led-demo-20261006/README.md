# MCP 생성 5V LED 데모

사용자가 관찰하는 ACUW 전용 레인에서 Konnect MCP만으로 생성·배치·배선한 기능 검증용 설계입니다. KiCad 원본 파일을 직접 문자열 편집하지 않았습니다.

## 설계

| 항목 | 값 |
|---|---|
| 입력 | J1 pin 1=+5V, pin 2=GND |
| 저항 | R1 470 ohm, `Resistor_SMD:R_0805_2012Metric` |
| LED | D1 `Device:LED`, pin 1=K/GND, pin 2=A/R1 출력 |
| LED footprint | `LED_THT:LED_D5.0mm` |
| capacitor | C1 100nF, 전원과 GND 사이 |
| 보드 | 40 x 25 mm, 2 copper layer |
| 관측 수량 | 4 footprint, 8 pad, 9 track, 0 via, 3 net, B.Cu GND zone 1 |

```text
J1.1 (+5V) -- R1 (470R) -- D1.2 (A)
     |                         |
   C1 (100nF)                D1.1 (K)
     |                         |
J1.2 (GND) --------------------+
```

## 검증과 한계

- 실제 KiCad 10.0.6 `kicad-cli`에서 ERC 오류/경고 0, DRC 오류/경고/미연결/회로도 parity 모두 0을 확인했습니다.
- 초기 DRC 6개 경고는 PCB Description 필드 4개와 library footprint 차이 2개였습니다. 경고를 끄지 않고 동기화·lossless 갱신으로 해소했습니다.
- 실제 PCB Editor 재오픈과 3D viewer에서 커넥터·저항·capacitor·LED 모델을 확인했습니다. GUI 자동 저장/개인 상태는 Git에서 제외합니다.
- 실물 제작, 부품 정격 검토, 전원 인가·LED 전류·발열·EMC·제조사 DFM 검증은 수행하지 않았습니다. 제조/발주 승인용 설계가 아닙니다.
- 라이브러리는 고정 설치본 `/opt/kicad/10.0.6/share/kicad`를 사용합니다. 다른 호스트에서는 설치 및 library table 경로를 MCP로 확인해야 합니다.
- 전체 도구 시험의 복잡한 PCB stress fixture는 이 데모와 분리되어 있습니다.

실행 시 source/runtime version을 먼저 검증하고 루트 문서의 strict live acceptance를 사용합니다. 상세 증거는 루트 `docs/보고서/`의 2026-10-06 보고서를 확인하세요.
