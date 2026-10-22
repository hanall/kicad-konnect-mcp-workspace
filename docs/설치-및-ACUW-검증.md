# KiCad 10 설치 및 ACUW live acceptance

## 현재 호스트 계약 (2026-10-06)

| 항목 | 현재 값 |
|---|---|
| KiCad | 공식 stable `10.0.6`, `/opt/kicad/10.0.6` |
| Konnect | 자체 `0.13.0+hanall.1`, 공식 main `9488e5f0` 기반 |
| 이전 설치 | `/opt/kicad/10.0.5` 보존 |
| 시연 레인 | ACUW `kicad-mcp-demo`, 기본 `:99` 무접촉 |
| 시연 설계 | `projects/mcp-led-demo-20261006/mcp-led-demo` |
| 기본 MCP HOME | `.runtime-home`, 사용자 전역 설정과 분리 |
| 기능 시험 HOME | `.artifacts` 하위 각 runner 전용 |
| 회로 시뮬레이터 (2026-10-22 추가) | 시스템 ngspice `44.2+ds-1`(apt), Qucs-S `26.1.1` `/opt/qucs-s/26.1.1`, LTspice `24.0.12.0` Wine prefix `~/.local/share/wineprefixes/ltspice`, KiCad 번들 ngspice `45.2` |

```bash
./scripts/install-kicad-appimage.sh --verify-only
make runtime-verify
make live-acceptance \
  KICAD_PROJECT=projects/mcp-led-demo-20261006/mcp-led-demo.kicad_pro \
  KICAD_BOARD=projects/mcp-led-demo-20261006/mcp-led-demo.kicad_pcb \
  KICAD_REQUIRE_CLEAN=1 \
  KICAD_EVIDENCE=.artifacts/demo-live-acceptance.json
```

현재 검증기는 바이너리뿐 아니라 추출 라이브러리 46,048개 항목(일반 파일 45,562개)의 목록·mode·해시·symlink target을 검사합니다. manifest 없는 기존 10.0.6은 installer 재실행이 필요하며, `--verify-only`가 손상을 자동 복구하지는 않습니다.

일반 live acceptance는 실행 계약, `KICAD_REQUIRE_CLEAN=1`은 추가로 DRC의 violations/unconnected_items/schematic_parity 모두 0을 요구합니다. schema 2 증거에는 실제 IPC board target, 버전, report SHA와 범주별 수치가 포함됩니다.

전용 레인의 GUI는 프로젝트별 `XDG_CONFIG_HOME`을 지정합니다. 자동 소켓 검색은 편의 기능일 뿐 여러 편집기의 식별 증명이 아니므로 병렬 시험은 서로 다른 TMPDIR/소켓을 사용하고 exact target을 재조회합니다. 뷰어의 `xdg-open`을 ACUW에 연결하는 별도 launcher는 `XDG_STATE_HOME=/home/hanol/.local/state`로 기존 레인 registry만 참조해야 합니다. Konnect의 격리 HOME 자체를 해제하지 않습니다.

## 회로 시뮬레이터 설치와 ACUW 검증 (2026-10-22)

구성·버전·잠금의 정본은 [회로 시뮬레이터 계약](agents/20261022-172859_circuit-simulators-linux.md)입니다. 이 절은 설치·재검증 순서와 ACUW 레인 규칙만 다룹니다.

| 구성요소 | 설치 | 선행 조건 | DISPLAY |
|---|---|---|---|
| 시스템 ngspice `44.2+ds-1` | Debian 공식 apt. 설치기는 패키지 버전만 검사 | — | 불필요 |
| Wine `10.0~repack-6` | Debian 공식 apt `wine`, `wine64`, `wine32:i386` | i386 아키텍처 | 불필요 |
| Qucs-S `26.1.1` | `make install-qucs-s` (`sudo`로 `/opt/qucs-s/26.1.1`, `/usr/local/bin/qucs-s`, desktop·icon 설치) | ngspice `44.2+ds-1` | 설치는 불필요, GUI 스모크는 레인 |
| LTspice `24.0.12.0` | `make install-ltspice` (사용자 Wine prefix와 `~/.local/bin/ltspice`) | wine·wine64 `10.0~repack-6` | 실제 설치 단계에서 필요 |

두 설치기는 이미 검증된 설치를 다시 쓰지 않습니다. `make install-ltspice`는 검증이 통과하면 재검증만 하고 끝나며, 미설치·검증 실패로 실제 설치에 들어갈 때만 DISPLAY를 요구합니다(없으면 다운로드 전에 exit 2).

```bash
# 레인은 open과 run 모두 16G로 실행한다
ACUW_LANE_MEMORY_MAX=16G bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh \
  open kicad-konnect-sim --backend visible-xvfb --size 1600x1000x24

# LTspice 실제 설치: Wine prefix와 래퍼가 실제 HOME 아래라 --host-home 필수
ACUW_LANE_MEMORY_MAX=16G bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh \
  run kicad-konnect-sim -- run-in-workspace.sh --wait --host-home --cwd "$PWD" -- \
  make install-ltspice

# 재검증은 레인 밖에서 실행
make sim-runtime-verify
make sim-verify
```

- `run-in-workspace.sh`는 호출마다 레인 slice의 `MemoryMax`를 `ACUW_LANE_MEMORY_MAX`(없으면 기본 8G)로 다시 설정합니다. open에만 16G를 주고 run에서 빠뜨리면 같은 레인의 KiCad까지 8G로 내려가 2026-10-06 OOM 조건이 돌아옵니다. 2026-10-22에도 env 없이 실행한 LTspice 배치와 첫 `qucs-s --help`가 `MemoryMax=8G` scope에서 돌았습니다.
- Qt 앱(Qucs-S)에는 `--expect-window`를 쓰지 않습니다. 창을 찾지 못하면 실행기가 앱 프로세스를 정리합니다. 백그라운드로 띄운 뒤 `capture.sh`로 확인합니다. `--wait`와 `--expect-window`는 원래 함께 쓸 수 없습니다.
- `--host-home`은 실제 HOME을 씁니다. KiCad 레인의 프로젝트별 `XDG_CONFIG_HOME`과 달리 Qucs-S는 `~/.config/qucs/qucs_s.conf`를 만들고 `~/.cache/qucs-s/`를 실행마다 덮어씁니다. 첫 실행의 "Set simulator" 대화상자는 `/usr/bin/ngspice`를 자동 감지합니다.
- 새 레인이 DISPLAY(100~199)·포트(VNC 5910+/noVNC 6081+/CDP 9223+)를 할당받지 못하면 `instance.sh list`에서 이 프로젝트가 연 실행 중 레인을 찾아 재사용합니다(2026-10-22: `kicad-standard-quality`, `:188`). 실행 중 레인에는 `run-in-workspace.sh --no-start`를 붙여 꺼진 레인을 자동 기동하지 않게 합니다. `gc --reclaim`은 브라우저 프로필까지 지우는 비가역 동작이므로 `--dry-run`으로 대상을 먼저 보고, 남이 연 레인은 회수·중지하지 않습니다.
- LTspice 배치 로그는 ASCII·CRLF이므로 `tr -d '\r'`로 읽습니다. Qucs-S가 만든 넷리스트는 AppImage 임시 마운트 경로의 `.INCLUDE`를 포함하므로 외부 ngspice로 다시 실행하지 않습니다. 재현은 `qucs-s -n -i <id>.sch -o <id>.dat --ngspice --run`으로 합니다.

`make sim-runtime-verify`의 `ngspice --version` 줄은 표시용입니다. ngspice 존재와 패키지 버전은 Qucs-S `--verify-only`의 `dpkg-query` 검사가 게이트합니다. KiCad 번들 ngspice 45.2는 `make runtime-verify`의 KiCad manifest 검사 범위입니다. 이 명령들의 성공은 설치 무결성 판정이며 회로 설계 승인이 아닙니다.
아래 내용은 8월 설치 당시의 원기록이며 그때의 버전·DRC 수치는 현재 개선판 결과와 혼합하지 않습니다.

## 2026-08-10 설치 기록 (이력, 현재판 아님)

| 항목 | 값 |
|---|---|
| OS | Debian 13 `trixie` |
| KiCad | 공식 stable full AppImage `10.0.5` |
| 설치 위치 | `/opt/kicad/10.0.5` |
| CLI | `/usr/local/bin/kicad-cli` |
| Konnect | `0.2.2`, project-isolated HOME |
| KiCad IPC | `ipc:///tmp/kicad/api.sock`, mode `0700` |
| Codex MCP | `.codex/config.toml` |
| Claude MCP | `.mcp.json` |
| 설치 승인 | 2026-08-10 사용자 명시 승인 |

Debian 13 기본 APT 후보는 KiCad `9.0.2`라서 Konnect의 KiCad 10 IPC 계약을
충족하지 못한다. 설치기는 KiCad 공식 Linux download 페이지가 제공하는 stable
full AppImage mirror URL을 고정하고, archive와 AppImage SHA-256 및 minisign을
모두 통과한 뒤에만 `/opt`와 `/usr/local`에 설치한다.

공급망 신뢰 근거는 다음 공식 표면을 교차 확인한다.

- KiCad `10.0.5` 안정 릴리스 공지: <https://www.kicad.org/blog/2026/07/KiCad-10.0.5-Release/>
- 공식 Linux 다운로드 페이지가 열거한 full AppImage와 TUNA mirror URL: <https://www.kicad.org/download/linux/>
- KiCad 공식 AppImage 저장소의 minisign 공개키 `40D6F856001D8BB2`: <https://gitlab.com/kicad/packaging/kicad-appimage/-/blob/main/keys/dev.pub>

직접 URL 설치는 홈 공급망 정책의 기본 금지 대상이지만, 이번 설치는 사용자가
KiCad `10.0.5` 범위를 명시 승인했다. 설치 manifest에 승인, 대안 검토, release
date, URL, 해시, 서명 공개키와 trusted comment를 함께 고정한다.

```bash
./scripts/install-kicad-appimage.sh
make runtime-verify
```

설치기는 같은 해시와 서명이 이미 검증되면 시스템 파일을 다시 쓰지 않는
멱등 동작을 한다. 제거가 필요하면 먼저 `/opt/kicad/10.0.5/INSTALL-MANIFEST.json`의
범위를 확인하고 해당 버전의 파일만 복구 가능한 방식으로 격리한다.

`--verify-only`는 AppImage 본체만 보지 않는다. 다음 중 하나라도 누락·불일치하면
fail-closed 한다.

- AppImage SHA-256과 minisign 공개키·서명·trusted comment
- `SHA256SUMS`, `minisign.pub`, 승인 포함 `INSTALL-MANIFEST.json`
- 8개 `/usr/local/bin` wrapper의 정확한 대상·mode
- desktop entry의 `Exec`·`TryExec`, icon, `desktop-file-validate`
- 실제 `kicad-cli --version = 10.0.5`

## Codex/Claude MCP 경계

```text
Codex (.codex/config.toml) ----+
                               |
Claude (.mcp.json) ------------+--> scripts/run-konnect.sh
                                      |
                                      +-- .runtime-home
                                      +-- KICAD_API_SOCKET auto-detect
                                      +-- Konnect 0.2.2 STDIO
```

`scripts/run-konnect.sh`는 실제 사용자 HOME을 Konnect의 최초 실행 installer로부터
격리한다. Linux에서 AI client가 KiCad의 자식 프로세스가 아닌 독립 MCP process로
Konnect를 시작해도, 현재 사용자의 `/tmp/kicad/api.sock`이 실제 socket일 때만
`KICAD_API_SOCKET`을 자동 설정한다.

Codex 공식 문서의 trusted project 범위 `.codex/config.toml` 계약을 적용했다.
실제 등록 상태는 다음 명령으로 확인한다.

```bash
codex mcp get konnect
```

공식 문서: <https://learn.chatgpt.com/docs/extend/mcp#connect-codex-to-an-mcp-server>

## ACUW 전용 레인 검증

다른 프로젝트의 기본 `:99`를 오염시키지 않도록 전용 병렬 레인을 사용한다.

```bash
bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh \
  open kicad-konnect-install --backend visible-xvfb --size 1600x1000x24

bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh \
  run kicad-konnect-install -- run-in-workspace.sh \
  --dbus-mode none --cwd /path/to/fixture --name kicad-10-llvmpipe -- \
  env LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe \
  kicad /path/to/fixture/example.kicad_pro

bash /home/hanol/ai-computer-use-workspace/scripts/instance.sh \
  run kicad-konnect-install -- capture.sh
```

GUI가 열린 뒤 KiCad의 `설정 -> 환경 설정 -> 플러그인`에서 `KiCad API 활성화`가
켜져 있는지 확인한다. 이 호스트의 정본 설정은
`~/.config/kicad/10.0/kicad_common.json`의 `api.enable_server=true`이며,
실제 socket의 존재와 permission도 함께 확인한다.

```bash
make live-acceptance \
  KICAD_PROJECT=/path/to/fixture/example.kicad_pro \
  KICAD_BOARD=/path/to/fixture/example.kicad_pcb \
  KICAD_EVIDENCE=.artifacts/kicad-live-acceptance.json
```

live acceptance의 통과 조건은 다음과 같다.

| 계층 | 통과 증거 |
|---|---|
| runtime | `kicad-cli --version = 10.0.5` |
| MCP | protocol `2025-06-18`, server `konnect 0.2.2` |
| GUI | `check_kicad_ui = running:true, ipc_responsive:true` |
| PCB IPC | `get_component_list`가 실행 중인 PCB Editor에서 구조화 결과 반환 |
| CLI bridge | Konnect `run_drc`가 JSON report 생성 |
| 화면 | ACUW capture에서 PCB Editor와 Help/About `10.0.5` 확인 |

2026-08-10 04:54 KST 최종 실측:

| 증거 | 결과 |
|---|---|
| `.artifacts/kicad-acuw-board-final.png` | ACUW `DISPLAY=:110`의 PCB 편집기 |
| `.artifacts/kicad-acuw-about-final.png` | GUI `Version: 10.0.5, release build` |
| `.artifacts/kicad-acuw-api-enabled-final.png` | `KiCad API 사용` 체크, `ipc:///tmp/kicad/api.sock` 수신 중 |
| `.artifacts/kicad-live-acceptance-final.json` | Konnect `0.2.2`, IPC responsive, live components 4 |
| `.artifacts/kicad-live-acceptance-final.drc.json` | 실제 KiCad CLI DRC report, SHA-256 증거 포함 |

DRC의 설계 위반 개수는 fixture 품질 판정이며 설치 실패가 아니다. acceptance는 DRC
명령이 실제 KiCad 10 CLI로 실행되어 구조화 결과와 report를 생성했는지를 판정한다.
공식 `upstream/kicad/demos/microwave` fixture는 현재 errors 8, warnings 16이며,
설치 수용 판정과 분리해 기록한다.
