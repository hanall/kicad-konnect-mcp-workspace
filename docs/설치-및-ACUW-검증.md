# KiCad 10 설치 및 ACUW live acceptance

## 현재 호스트 계약

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
