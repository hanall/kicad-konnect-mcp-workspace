# 엔진 구성과 사용법

이 문서는 네 엔진의 설치 구성·검증 명령·ACUW 레인 사용법·알려진 제약을 소유한다. 이 호스트 기준 값이며 정본은 계약 문서와 잠금 파일이다.

설치 계약과 잠금: `docs/agents/20261022-172859_circuit-simulators-linux.md`, `config/qucs-s.lock.json`, `config/ltspice.lock.json`. 설치 상태 확인은 `make sim-runtime-verify` 또는 MCP `list_simulation_engines`.

| 엔진 | 버전 | 실행 | 작업 위치 |
|---|---|---|---|
| 시스템 ngspice | 44.2+ds-1 (Debian apt) | `ngspice -b -o run.log run.cir` | 아무 디렉터리. `.spiceinit`은 cwd |
| KiCad 번들 ngspice | 45.2 (AppImage `shared/lib/libngspice.so.0.0.14`) | `python3 -I scripts/ngspice_shared_batch.py <lib> run.cir` | 코드모델 미로드 |
| LTspice | 24.0.12 (Wine 10.0, `~/.local/share/wineprefixes/ltspice`) | `~/.local/bin/ltspice -b run.cir`(배치), `-Run run.cir`(GUI) | ACUW 레인 DISPLAY 필수 |
| Qucs-S | 26.1.1 (`/opt/qucs-s/26.1.1`, 엔진은 시스템 ngspice) | `qucs-s`(GUI), `qucs-s -n -i x.sch -o x.dat --ngspice --run`(배치) | ACUW 레인 DISPLAY 필수 |

## ACUW 레인에서 GUI·Wine 실행

```bash
I=/home/hanol/ai-computer-use-workspace/scripts/instance.sh
ACUW_LANE_MEMORY_MAX=16G bash $I open kicad-standard-quality          # 프로젝트 소유 레인 이름 재사용
ACUW_LANE_MEMORY_MAX=16G bash $I run kicad-standard-quality -- run-in-workspace.sh --wait --host-home \
  --cwd "$WORK" --name ltspice-x -- "$HOME/.local/bin/ltspice" -b x.cir     # LTspice 배치
ACUW_LANE_MEMORY_MAX=16G bash $I run kicad-standard-quality -- run-in-workspace.sh --host-home \
  --name qucs -- /usr/local/bin/qucs-s x.sch                                 # Qucs-S GUI(백그라운드)
bash $I run kicad-standard-quality -- capture.sh                              # 화면 PNG → Read로 판독
```

- 새 이름으로 `open`이 "빈 noVNC 포트를 찾지 못했습니다"로 실패하면 이 프로젝트가 이미 쓴 레인 이름(`kicad-standard-quality`, `kicad-smps-sync-gui`, `kicad-mcp-demo` 등)을 그대로 연다. `gc --reclaim`은 다른 프로젝트 레인을 지울 수 있어 쓰지 않는다.
- `run-in-workspace.sh`는 호출마다 레인 MemoryMax를 다시 설정하므로 `ACUW_LANE_MEMORY_MAX=16G`를 open뿐 아니라 run에도 붙인다(KiCad GUI를 띄울 때 8G면 OOM).
- Qt 앱(Qucs-S)에 `--expect-window`를 쓰면 창을 못 찾고 프로세스를 정리한다. 쓰지 말고 `capture.sh`로 확인한다.
- 사용자 실제 화면(:0)과 다른 레인은 건드리지 않는다. 내가 띄운 프로세스는 `run-in-workspace.sh --json`이 돌려준 pid 파일의 PGID 기준으로만 종료한다.

## LTspice(Wine)

- 첫 GUI 실행에 "Web Sync" 업데이트 확인 대화상자가 뜨며 버튼 글꼴이 네모로 깨진다(Wine 글꼴 차이, ADI FAQ의 알려진 항목). 배치 모드(`-b`)에는 영향이 없다. 자동 업데이트를 원하지 않으면 LTspice 설정의 Web Sync를 끈다.
- 로그는 `<file>.log` 평문 ASCII(CRLF). `.raw`는 바이너리라 MCP 도구는 파형을 반환하지 않는다.
- `.meas` 문법은 등호 없이 `AT 1m`, `FROM a TO b`. `run_spice_simulation`이 변환한다.
- 접지는 `0`만 인식한다. KiCad 넷리스트의 `GND`는 치환해야 한다.
- ADI/LT 부품 모델과 예제는 `C:\Program Files\ADI\LTspice\`(prefix 안 `drive_c`)의 `lib`, `examples`에 있다.

## Qucs-S

- 첫 실행에 "Set simulator" 대화상자가 `/usr/bin/ngspice`를 자동 감지한다. 설정은 `~/.config/qucs/qucs_s.conf`(`NgspiceExecutable=/usr/bin/ngspice`).
- 회로도는 `.sch` 텍스트이며 SPICE 전용 컴포넌트(`S4Q_V`, `R_SPICE`, `C_SPICE`, `NMOS_SPICE`, `DIODE_SPICE`, `SpiceModel`, `SpLib`, `src_eqndef`)로 ngspice 넷리스트와 1:1 대응한다. 예제: `projects/sim-validation-20261022/qucs-s/*/*.sch`.
- `Simulate(F2)` 결과 데이터셋은 `<name>.dat.ngspice`(`<Qucs Dataset>` 텍스트, `<indep time N>`, `<dep v(out) time>`). 파서 예: `projects/sim-validation-20261022/qucs-s/measure_qucs_dataset.py`.
- 배치 `--run`은 `-o`에 데이터셋을 쓴다. 2026-10-22 검증에서 GUI와 CLI 데이터셋이 바이트 동일했다.
- 마이크로스트립 해석은 ngspice 45 이상이 필요해 Debian 44.2에서는 제한된다. RF 해석은 QucsatorRF(번들, SPICE 비호환)를 쓴다.

## KiCad 편집기 시뮬레이터

AppImage가 ngspice 45.2를 번들하므로 추가 설치가 없다. ACUW 레인에서 `eeschema <sch>`로 열고 `Inspect → Simulator`. 넷리스트 생성 규칙은 [kicad-sim-fields](kicad-sim-fields.md). 헤드리스 등가 경로는 `kicad-bundled-ngspice` 엔진이다.

## 알려진 제약

- Windows 전용 도구(PSpice for TI, QSPICE, TINA-TI)는 이 호스트에서 쓰지 않는다. PSpice for TI는 타사 모델을 가져오면 동시 프로브 3개 제한이 있다.
- 암호화된 제조사 모델은 모든 오픈 엔진에서 불가하다.
- `.artifacts/`는 Git 추적 밖이다. 보고에 남길 증거는 `docs/검증/<ts>-…/`로 복사한다.
