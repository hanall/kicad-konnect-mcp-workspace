# KiCad·Konnect 프로젝트 스킬 오버레이

## 정본과 구식 스킬 교정

글로벌 스킬 본문은 외부 저장소이므로 수정하지 않습니다. 충돌 시 이 프로젝트 오버레이, checkout의 도구 schema와 실제 KiCad 10.0.6 관측이 우선합니다.

| 주제 | 적용 규칙 |
|---|---|
| 도구 개수 | 구 스킬의 187/18, 구 문서의 193개를 사용하지 않습니다. 현재 Linux STDIO는 228 domain + 8 meta = 236개, 21 toolset이며 실행 `tools/list`가 정본입니다. |
| 파일 수정 | `.kicad_*`, `sym-lib-table`, `fp-lib-table`의 수정은 MCP만 사용합니다. 회로 원문 읽기는 export로 알 수 없는 보존 검증의 최후 수단입니다. |
| diode·LED 극성 | symbol pin 번호를 추측하지 않습니다. `Device:LED`는 pin 1=K, pin 2=A입니다. symbol 정의·footprint pad·실제 netlist를 각각 대조합니다. |
| PCB 상태 | live IPC 상태와 saved file은 서로 다른 원본입니다. 실패 시 조용히 파일 fallback하지 않습니다. |
| footprint 갱신 | 기존 point/필드/UUID/net/group 손실을 허용하지 않습니다. closed-file opt-in은 현재 dry-run revision과 닫힌 exact board를 요구하며 불명확한 객체를 거부합니다. |
| 경고 제거 | DRC 경고를 끄거나 ignore 목록으로 숨기지 않습니다. 라이브러리 geometry/필드를 교정한 뒤 ERC/DRC 전체 범주를 재확인합니다. |
| 뷰어 | 개선판은 Tauri가 아닌 loopback browser viewer입니다. 실제 SVG·브라우저 ACK를 받기 전 ready로 승격하지 않습니다. |
| 성공 범위 | mock, 단위시험, schema 거부, GUI 실행, 실제 전기시험을 구분합니다. 236개 호출 통과를 모든 인자·OS 무결성으로 표현하지 않습니다. |

## 기본 순서

```text
schema -> backup -> dry-run -> revision -> apply -> readback -> ERC/DRC
```

- 정본 실행기는 `scripts/run-konnect.sh`입니다. 오래 살아 있는 MCP 프로세스는 디스크 binary와 다를 수 있으므로 PID/exe SHA와 initialize version을 대조합니다.
- 공유 checkout에서는 파일 소유권을 명시하고 release binary 교체는 조율 담당만 수행합니다. 최종 runner는 고정 SHA 전후 일치를 확인합니다.
- 상세 검증·rollback은 `docs/20261006-112759_업그레이드-및-검증-계약.md`를 따릅니다.
