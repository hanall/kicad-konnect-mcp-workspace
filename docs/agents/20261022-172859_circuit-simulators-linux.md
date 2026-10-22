# Linux 회로 시뮬레이터 구성 계약 (2026-10-22)

이 문서는 2026-10-22 사용자 그릴링(3라운드, 질문 10개)으로 확정한 Linux 회로 시뮬레이션 환경의 설치·검증 계약이다. 검증 결과와 측정값은 [HTML 보고서](../보고서/20261022-172859_circuit-simulators-linux.html)에, 원본 증거는 [`docs/검증/20261022-172859-circuit-simulators/`](../검증/20261022-172859-circuit-simulators/)에 있다.

## 구성

| 구성요소 | 버전 | 설치 방식 | 실행 진입점 | 잠금/매니페스트 |
|---|---|---|---|---|
| KiCad 내장 시뮬레이터 | KiCad 10.0.6 AppImage, ngspice **45.2** 번들 | 기존 설치(`/opt/kicad/10.0.6`) 그대로. 추가 설치 없음 | `eeschema` → 시뮬레이터 | `/opt/kicad/10.0.6/INSTALL-MANIFEST.json` |
| 시스템 ngspice | 44.2+ds-1 | Debian 13 공식 저장소 `apt` | `/usr/bin/ngspice` | `apt-packages.txt`(증거 폴더) |
| Qucs-S | 26.1.1 | GitHub 릴리스 AppImage를 `/opt/qucs-s/26.1.1`에 고정 설치, SHA256 2중 검증 | `/usr/local/bin/qucs-s` | `config/qucs-s.lock.json`, `/opt/qucs-s/26.1.1/INSTALL-MANIFEST.json` |
| LTspice | 24.0.12.0 | ADI 공식 MSI를 사용자 전용 Wine prefix에 조용한 설치 | `~/.local/bin/ltspice` | `config/ltspice.lock.json`, `~/.local/share/wineprefixes/ltspice/INSTALL-MANIFEST.json` |
| Wine | 10.0~repack-6 (wine, wine64, wine32:i386) | Debian 13 공식 저장소 `apt` | `/usr/bin/wine` | 위 LTspice 매니페스트에 기록 |

Qucs-S는 ngspice를 번들하지 않으므로 시스템 ngspice가 엔진이다. KiCad AppImage는 번들 45.2를 우선 로드하므로 시스템 44.2와 충돌하지 않는다.

## 명령

```bash
make sim-runtime-verify   # Qucs-S·LTspice 설치 매니페스트/SHA/래퍼 검증 + ngspice 버전
make sim-verify           # 검증 회로 5종을 시스템 ngspice 배치로 실행해 이론값과 대조
make install-qucs-s       # 재설치 또는 재검증(멱등)
make install-ltspice      # 재설치 또는 재검증. 설치 모드는 레인 DISPLAY가 필요
python3 scripts/sim-validation-run.py --engine kicad-bundled --out .artifacts/sim-validation-kicad-bundled   # KiCad 번들 ngspice 45.2로 같은 회귀. --out이 없으면 시스템 회귀 증거 폴더를 덮어쓴다
python3 -m unittest tests.test_sim_validation -v               # 사양·잠금·설치 계약 테스트
```

LTspice와 Qucs-S GUI는 ACUW 전용 레인에서만 띄운다. 레인 open과 `run-in-workspace.sh` 호출 **둘 다** `ACUW_LANE_MEMORY_MAX=16G`를 앞에 붙인다. 예:

```bash
ACUW_LANE_MEMORY_MAX=16G bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh run kicad-standard-quality -- run-in-workspace.sh --wait --host-home --cwd "$PWD" -- "$HOME/.local/bin/ltspice" -b circuit.cir
```

Qt 앱(Qucs-S)은 `--expect-window`가 창을 찾지 못해 프로세스를 정리하므로 쓰지 않고 `capture.sh`로 확인한다. 첫 실행에서 "Set simulator" 대화상자가 `/usr/bin/ngspice`를 자동 감지한다.

## 검증 회로 5종

사양은 [`projects/sim-validation-20261022/spec/spec.json`](../../projects/sim-validation-20261022/spec/spec.json)이며 `spec/theory.py`가 생성한다. 각 회로는 엔진 중립 SPICE 본체와 해석적으로 유도한 이론값, 허용 오차(이론값 대비 2%, 경로 간 1%)를 갖는다.

| id | 회로 | 판정 항목 |
|---|---|---|
| 01-rc-step | RC 과도응답 | τ 시점 전압, 3τ 전압, 10→90% 상승시간 |
| 02-mosfet-gate | MOSFET level 1 게이트 구동 | 게이트 τ 전압, Vth 도달 시각, ON Vds, ON Id |
| 03-opamp-noninv | KiCad 내장 단극 OP AMP 비반전 증폭 | 1 kHz 출력 피크, 10 Hz 이득(dB), −3 dB 주파수 |
| 04-diode-rectifier | Shockley 다이오드 반파 정류 | 출력 피크, 순방향 강하 |
| 05-precharge | 프리차지 RC 돌입 | 피크 전류, 저항 피크 전력, τ 전압, 95% 도달 시각, 저항 소산 에너지 |

실행 경로: 시스템 ngspice 배치, KiCad 번들 ngspice 공유 라이브러리(`scripts/ngspice_shared_batch.py`), Konnect MCP로 작성한 KiCad 회로도 → `kicad-cli` SPICE 넷리스트, LTspice 배치(`-b`), Qucs-S GUI/CLI. 적대적 검증 에이전트가 이론값을 독립 재유도하고 측정 정의를 반박한다.

## 공급망·갱신

- 세 설치는 모두 사용자 명시 승인 아래 수행했고 승인 근거는 각 잠금 파일 `approval` 필드에 있다. LTspice는 지침의 직접 URL 금지 예외다.
- Qucs-S와 LTspice는 자동 갱신되지 않는다. 갱신은 새 SHA256·버전·게시일을 잠금 파일과 설치 스크립트 상단 상수에 **동시에** 반영한 뒤 `make install-*`로 수행한다. 7일 age gate를 지킨다.
- 시스템 ngspice와 Wine은 Debian 패키지라 이 호스트의 unattended-upgrades(Debian 안정·보안 origin, hold·blacklist 없음)로 바뀔 수 있다. 바뀌면 `make sim-runtime-verify`가 패키지 버전 불일치로 실패한다(의도된 fail-closed). 그때는 `make sim-verify`와 LTspice 재검증을 돌린 뒤 설치 스크립트의 `NGSPICE_PACKAGE_VERSION`·`WINE_PACKAGE_VERSION`과 이 문서를 갱신한다. 사용자 결정(2026-10-22): `apt-mark hold`는 쓰지 않는다. 보안 업데이트를 막지 않고 fail-closed 뒤 갱신 절차를 따른다.
- LTspice `latest` URL은 파일이 바뀔 수 있다. 설치 스크립트는 잠금 SHA와 다르면 중단한다.

## 2026-10-22 네 경로 결과 요약

| 경로 | 엔진 | 17개 측정 항목 | 적대적 검증 |
|---|---|---|---|
| 시스템 ngspice 배치 | 44.2 | 17/17 이론값 2% 이내(최대 0.26%) | 5/5 confirmed |
| KiCad 번들 ngspice 공유 라이브러리 | 45.2 | 17/17, 시스템과 동일 | (같은 넷리스트) |
| Qucs-S GUI·CLI | 26.1.1 + 시스템 ngspice 44.2 | 17/17, 시스템 ngspice와 최대 차 4.8e-6 | 5/5 confirmed |
| LTspice 배치(Wine) | 24.0.12 | 17/17 이론값 2% 이내 | 5/5 confirmed |
| Konnect MCP 회로도 → kicad-cli SPICE 넷리스트 → 시스템 ngspice | 0.13.0+hanall.1 + kicad-cli 10.0.6 + 44.2 | 5/5 회로 넷리스트 동등, 17/17 판정, 수기 넷리스트와 상호 차 0 | 5/5 confirmed |
| KiCad 편집기 내장 시뮬레이터 GUI (ACUW 레인) | KiCad 10.0.6, 번들 ngspice 45.2 | 5/5 실행, 17/17 (콘솔 .meas + CSV 재계산, 배치 경로와 4.5e-6 이내) | 5/5 confirmed(캡처 재판독) |

경로 간 1% 교차 기준은 **1건 미달**이다. LTspice의 `04-diode-rectifier` `vf_pk_derived`(0.72517 V)가 ngspice 계열(0.71278 V)과 1.74% 차이 난다. 이론값 대비로는 두 값 모두 2% 이내이며 원인(LTspice 다이오드 모델 기본 파라미터 또는 파형 압축)은 확인하지 않았다. 교차 판정 자동화와 `.options plotwinsize=0` 재실행은 로드맵 5단계의 미완료 항목이다.

## 알려진 제약

- Qucs-S 25.2.0 이후 마이크로스트립 해석은 ngspice 45 이상을 요구한다. Debian 44.2에서는 그 기능만 제한된다.
- LTspice는 Wine 실행이라 글꼴 렌더링과 PWL 편집기에서 ADI FAQ가 적은 알려진 차이가 있다.
- ngspice 배치 모드는 `.meas ac ... vdb(out)`만으로는 저장 벡터를 정하지 못해 해석을 건너뛴다. `.save all`을 함께 둔다.
- 암호화된 제조사 PSpice 모델은 ngspice에서 쓸 수 없다. 2차 검증(사용자 핵심 IC)은 모델 파일 형식 확인부터 시작한다.
