# KiCad 10 + Konnect MCP 개발 워크스페이스

KiCad 10과 Konnect MCP를 재현 가능한 upstream 기준점에 고정하고, 회로도부터 제조 산출물까지 AI 보조 개발을 확장하기 위한 통합 프로젝트입니다.

## 고정된 upstream

| 구성요소 | 기준 버전 | 기준 커밋 | 역할 |
|---|---:|---|---|
| KiCad | `10.0.6` | `caf7377e9cb6fa1535ec3596dcb8c99bf44a996e` | 회로도, PCB, ERC/DRC, Gerber/제조 산출물 엔진 |
| Konnect 공식 release | `v0.13.0` | `6bbe3e4f890ba1d37c0e5d5f38ccd03d90958c9e` | upstream 배포 기준점 |
| Konnect 개발 기준 | `main` | `9488e5f09717cb508cb25779dc16586d1f06f758` | 자체 개선의 공식 기반 |
| Konnect 자체 개선 | `0.13.0+hanall.1` | `upstreams.lock.json`의 `commit` | 손실 방지, 라이브러리, IPC, 뷰어 및 도구 계약 개선 |

정확한 출처와 태그 시각은 [`upstreams.lock.json`](upstreams.lock.json)에 기록합니다. 두 소스는 `upstream/` 아래 Git submodule이며, 각각 태그 기준의 로컬 개발 브랜치에서 시작합니다.

KiCad는 공식 GitLab 원본의 최신 안정 릴리스를 read-only 기준으로 추적합니다.
Konnect는 공식 `mixelpixx/Konnect`를 `upstream`으로 두고
[`hanall/Konnect`](https://github.com/hanall/Konnect) fork의 개발 브랜치에서
성능·신뢰성·도구 계약을 개선합니다.

## 구조

```text
MCP client
    |
    | JSON-RPC 2.0 over stdio
    v
scripts/run-konnect.sh
    |
    +-- project-isolated HOME
    |
    v
Konnect 0.13.0+hanall.1
    |                     |
    | NNG + protobuf      | subprocess
    v                     v
KiCad 10 PCB Editor   kicad-cli
    |                     |
    +----------+----------+
               v
 schematic / PCB / ERC / DRC / Gerber / drill / BOM / position
```

## 빠른 시작

```bash
git clone --recurse-submodules https://github.com/hanall/kicad-konnect-mcp-workspace.git
cd kicad-konnect-mcp-workspace

# fork에 없는 공식 tag도 잠금 원본에서 정확히 복구
python3 scripts/fetch-locked-tag.py kicad
python3 scripts/fetch-locked-tag.py konnect

# 프로젝트 자체와 upstream 고정을 확인
make verify

# 고정된 빌드 도구 준비 후 Konnect 빌드
./scripts/bootstrap-dev-deps.sh
make build

# 이 Debian 호스트에 고정된 공식 KiCad 10 AppImage 설치 또는 재검증
./scripts/install-kicad-appimage.sh
make runtime-verify

# upstream 테스트와 MCP JSON-RPC smoke
make test
make mcp-smoke
```

`.mcp.json`은 프로젝트의 안전 실행기를 가리킵니다. 실행기는 과거 자동 설치와 최신판의 명시적 `init`이 실제 `~/.claude`를 수정하지 않도록 `.runtime-home/`을 전용 HOME으로 사용합니다.

Codex는 공식 설정 형식인 [`.codex/config.toml`](.codex/config.toml)을 사용합니다.
프로젝트를 trusted로 연 Codex CLI/IDE/desktop 세션에서는 `konnect` STDIO MCP가
동일한 안전 실행기로 등록됩니다. Linux에서 KiCad API가 활성화되어
`/tmp/kicad/api.sock`이 존재하면 실행기가 IPC 주소를 자동 전달합니다.

얕은 submodule clone에서 tag ref가 생략됐다면 잠금 파일에 기록된 origin, commit,
tag를 검증하면서 필요한 tag만 복구할 수 있습니다.

```bash
python3 scripts/fetch-locked-tag.py kicad
python3 scripts/fetch-locked-tag.py konnect
```

## 검증과 GitHub 운영 정책

`hanall` 계정은 과금 방지를 위해 GitHub Actions를 사용하지 않습니다. 저장소의
Actions 권한을 비활성화하고 workflow 파일을 두지 않으며, push 전 아래 로컬 gate를
실행합니다.

```bash
make check-local
```

## Upstream 업데이트와 Konnect 개발

KiCad의 `.99.0` 개발 태그는 제외하고, 공식 원본의 가장 최신 안정 릴리스를
확인하거나 반영합니다. 현재 최신 버전이면 파일을 변경하지 않습니다.

```bash
make check-updates
make update-kicad
```

Konnect 개발을 시작할 때 fork를 `origin`, 공식 저장소를 `upstream`으로
구성하고 개발 브랜치를 checkout합니다.

```bash
make setup-konnect-dev
git -C upstream/konnect fetch upstream --tags
git -C upstream/konnect status --short --branch
```

Konnect 변경은 해당 submodule에서 테스트·커밋·fork push한 뒤 root의 gitlink와
`upstreams.lock.json`의 `commit`을 함께 갱신합니다. 공식 최신 release는
`upstream_tag`와 `upstream_commit`에 별도로 보존합니다.

## 디렉터리

| 경로 | 용도 |
|---|---|
| `upstream/kicad/` | KiCad 10.0.6 소스 submodule |
| `upstream/konnect/` | Konnect 0.13.0+hanall.1 소스 submodule |
| `projects/` | 우리가 만드는 KiCad 설계 프로젝트 |
| `config/` | 재현 가능한 Konnect 설정 |
| `scripts/` | bootstrap, build, 검증, MCP 실행 |
| `docs/` | 아키텍처, 로드맵, 보안·라이선스 문서 |
| `.runtime-home/` | 전역 설정을 보호하는 로컬 런타임 상태, Git 제외 |

## 개발 원칙

1. upstream 태그와 커밋은 함께 고정합니다.
2. KiCad 공식 upstream은 read-only이며 자체 변경은 Konnect fork와 root 통합 계층에만 둡니다.
3. Konnect 변경은 `upstream/konnect`의 `hanol-dev/v0.13.0` 브랜치에서 테스트 우선으로 수행합니다.
4. MCP tool 이름, schema, config key는 공개 API로 취급합니다.
5. 회로 파일 변경은 원본 보존, atomic write, ERC/DRC와 제조 산출물 재검증을 통과해야 합니다.
6. 실제 PCB 발주 전에는 ERC/DRC뿐 아니라 전원, 극성, footprint, BOM, 제조사 규칙을 사람이 최종 검토합니다.

## 현재 범위

- 소스 checkout과 MCP 서버 빌드/프로토콜 smoke는 `make check-local`로 로컬 검증합니다.
- 이 호스트에는 공식 full AppImage 기반 KiCad `10.0.6`가 `/opt/kicad/10.0.6`에 설치되어 있으며, `/usr/local/bin/kicad`와 `kicad-cli` 등 8개 진입점을 제공합니다. Debian 13 기본 APT 후보 `9.0.2`는 설치하지 않습니다.
- `make runtime-verify`는 AppImage SHA-256, minisign, 46,048개 라이브러리 항목의 고정 manifest, desktop entry와 실제 `kicad-cli --version`을 다시 확인합니다.
- `make live-acceptance KICAD_PROJECT=... KICAD_BOARD=...`는 실행 중인 KiCad 10 PCB Editor에 Konnect가 실제 IPC로 접속하고, live component 조회와 실제 `kicad-cli` DRC까지 수행합니다. ACUW 실행 절차와 현재 실측은 [`docs/설치-및-ACUW-검증.md`](docs/설치-및-ACUW-검증.md)를 따릅니다.
- Konnect는 upstream이 명시한 beta 소프트웨어입니다. Linux는 컴파일·CI 대상이지만 Windows만큼 현장 검증이 축적되지 않았습니다.

## 개선판 검증과 사용 경계

- 공개 표면은 현재 Linux STDIO에서 domain 228개와 meta 8개입니다. 도구 개수·목록은 실행 바이너리의 `tools/list`를 정본으로 삼습니다.
- 정상 실행, schema 거부, 원본 보존, 실제 GUI/IPC, ERC/DRC, 외부 서비스 시험은 서로 다른 증거입니다. 전체 목록을 호출했다는 사실만으로 모든 인자·환경의 무결성을 보장하지 않습니다.
- 실제 데모는 [`projects/mcp-led-demo-20261006/README.md`](projects/mcp-led-demo-20261006/README.md), 재현·migration·롤백은 [`검증 계약`](docs/20261006-112759_업그레이드-및-검증-계약.md)을 따릅니다.
- KiCad 파일은 직접 문자열 편집하지 않고 MCP로 변경합니다. 닫힌 PCB의 lossless footprint 갱신은 `allow_closed_board_file:true`와 현재 dry-run revision을 명시해야 하며, 안전성을 입증하지 못한 객체는 거부합니다.
- `make live-acceptance ... KICAD_REQUIRE_CLEAN=1`은 DRC 전체 범주 0도 요구합니다. 기본 모드의 성공은 DRC 실행 성공이며 설계 무결점 판정이 아닙니다.
- 교차 탐색의 `allow_saved_schematic_context:true`는 저장 회로도 기반 읽기 전용 opt-in입니다. KiCad가 제공하지 않은 live 회로도 프로젝트 식별을 추정하거나 선택 상태를 바꾸지 않습니다.
- `make build`는 서버와 별도 browser viewer를 모두 `--locked`로 빌드합니다. 뷰어는 Tauri/GTK 대신 loopback capability URL에서 격리 snapshot SVG를 표시하고 실제 페이지 로딩까지 확인합니다.
- Freerouting 선택 런타임은 `config/freerouting.lock.json`과 `scripts/install-freerouting-runtime.py`로 고정합니다. 시스템 Java/alternatives를 바꾸지 않습니다.
- JLCPCB 부품 DB는 제3자 공개 피드입니다. 수신 SHA·SQLite 구조 검증은 제공자 자료의 진위·재고·가격을 보증하지 않습니다.

## 라이선스

이 통합 프로젝트의 자체 코드와 문서는 `AGPL-3.0-only`로 둡니다. Konnect도 `AGPL-3.0-only`, KiCad의 결합 저작물은 주로 `GPL-3.0-or-later`이며 일부 제3자 파일에는 별도 호환 라이선스가 적용됩니다. 자세한 내용은 [`NOTICE.md`](NOTICE.md)와 [`docs/보안-및-라이선스.md`](docs/보안-및-라이선스.md)를 확인하세요.

## 2026-10-06 검증 보고서

- [업그레이드·개선·공개 기능 검증](docs/보고서/20261006-125005_kicad-konnect-upgrade-validation.html)
- 정상 경로 228/228 및 meta 8/8, schema·거부 입력 1,017/1,017을 확인했습니다.
- 전면 무결성 게이트는 rc 3으로 미통과입니다. 재조회 61건, 원본 보존 96건, 외부 실행 113건의 명시적 증거 공백과 sync 하네스 rc1/독립 재검증 rc0을 보고서에 구분했습니다.
