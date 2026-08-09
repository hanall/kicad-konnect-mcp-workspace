# KiCad 10 + Konnect MCP 개발 워크스페이스

KiCad 10과 Konnect MCP를 재현 가능한 upstream 기준점에 고정하고, 회로도부터 제조 산출물까지 AI 보조 개발을 확장하기 위한 통합 프로젝트입니다.

## 고정된 upstream

| 구성요소 | 기준 버전 | 기준 커밋 | 역할 |
|---|---:|---|---|
| KiCad | `10.0.5` | `18fb9289ff0efdca53c0352ed81a0973f0a6b58c` | 회로도, PCB, ERC/DRC, Gerber/제조 산출물 엔진 |
| Konnect | `v0.2.2` | `ac878269de0692ca4555f19658dd5af7886a8b78` | KiCad 10 IPC API와 `kicad-cli`를 MCP로 노출 |

정확한 출처와 태그 시각은 [`upstreams.lock.json`](upstreams.lock.json)에 기록합니다. 두 소스는 `upstream/` 아래 Git submodule이며, 각각 태그 기준의 로컬 개발 브랜치에서 시작합니다.

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
Konnect v0.2.2
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
cd /home/hanol/kicad-konnect-mcp-workspace

# 프로젝트 자체와 upstream 고정을 확인
make verify

# 고정된 빌드 도구 준비 후 Konnect 빌드
./scripts/bootstrap-dev-deps.sh
make build

# upstream 테스트와 MCP JSON-RPC smoke
make test
make mcp-smoke
```

`.mcp.json`은 프로젝트의 안전 실행기를 가리킵니다. 실행기는 Konnect의 최초 실행 설치가 실제 `~/.claude`를 수정하지 않도록 `.runtime-home/`을 전용 HOME으로 사용합니다.

## 디렉터리

| 경로 | 용도 |
|---|---|
| `upstream/kicad/` | KiCad 10.0.5 소스 submodule |
| `upstream/konnect/` | Konnect v0.2.2 소스 submodule |
| `projects/` | 우리가 만드는 KiCad 설계 프로젝트 |
| `config/` | 재현 가능한 Konnect 설정 |
| `scripts/` | bootstrap, build, 검증, MCP 실행 |
| `docs/` | 아키텍처, 로드맵, 보안·라이선스 문서 |
| `.runtime-home/` | 전역 설정을 보호하는 로컬 런타임 상태, Git 제외 |

## 개발 원칙

1. upstream 태그와 커밋은 함께 고정합니다.
2. KiCad upstream은 기본적으로 변경하지 않고, IPC 계약이 필요할 때만 별도 변경합니다.
3. Konnect 변경은 `upstream/konnect`의 `hanol-dev/v0.2.2` 브랜치에서 테스트 우선으로 수행합니다.
4. MCP tool 이름, schema, config key는 공개 API로 취급합니다.
5. 회로 파일 변경은 원본 보존, atomic write, ERC/DRC와 제조 산출물 재검증을 통과해야 합니다.
6. 실제 PCB 발주 전에는 ERC/DRC뿐 아니라 전원, 극성, footprint, BOM, 제조사 규칙을 사람이 최종 검토합니다.

## 현재 범위

- 소스 checkout과 MCP 서버 빌드/프로토콜 smoke는 이 저장소에서 자동 검증합니다.
- KiCad GUI와 `kicad-cli` 런타임은 별도 시스템 설치가 필요합니다. Debian 13 기본 APT는 KiCad 9.0.2이므로 KiCad 10을 그 경로로 잘못 설치하지 않습니다.
- Konnect는 upstream이 명시한 beta 소프트웨어입니다. Linux는 컴파일·CI 대상이지만 Windows만큼 현장 검증이 축적되지 않았습니다.

## 라이선스

이 통합 프로젝트의 자체 코드와 문서는 `AGPL-3.0-only`로 둡니다. Konnect도 `AGPL-3.0-only`, KiCad의 결합 저작물은 주로 `GPL-3.0-or-later`이며 일부 제3자 파일에는 별도 호환 라이선스가 적용됩니다. 자세한 내용은 [`NOTICE.md`](NOTICE.md)와 [`docs/보안-및-라이선스.md`](docs/보안-및-라이선스.md)를 확인하세요.
