# Konnect MCP 포터블 번들 — Windows 11

**Windows 11 x64용 설치 후보입니다. Windows 실기기·PowerShell 실행·KiCad GUI/IPC 연결은 아직 검증하지 않았습니다.** Linux에서의 교차 빌드/정적 검토를 Windows 동작 완료로 해석하지 마세요. 설치 대상 PC에서 아래 연결 확인이 필요합니다.

고정 서버: `0.13.0+hanall.1`, 소스 commit `94f80350cf67db27b179a06a8f6dbebfe4717927`. OS별 바이너리는 같은 Rust 서버 소스로 만들며, 플랫폼별 실행기만 분리합니다. 다른 OS의 GUI 기능까지 동일하게 검증했다는 뜻은 아닙니다.

## 1. 준비

1. [공식 Windows 다운로드](https://www.kicad.org/download/windows/)에서 **KiCad 10 x64와 라이브러리를 별도로 설치**하세요. KiCad는 ZIP에 포함되지 않습니다. 프로젝트의 기존 기준은 10.0.6이며 다른 10.x 패치의 동작은 별도 확인 대상입니다.
2. 사용하려는 프로젝트 폴더를 준비하고 원본을 백업하세요. 설정기는 이 폴더의 CAD 파일을 수정하지 않습니다.
3. ZIP의 SHA-256을 전달받은 외부 `.zip.sha256` 파일와 비교하고 ZIP을 **새 로컬 폴더에 완전히** 푸세요. ZIP 내부에서 직접 실행하지 마세요. 번들·프로젝트·KiCad 경로의 심볼릭 링크/junction/reparse point, UNC 경로는 지원하지 않습니다.
4. `Setup-Windows.ps1`을 읽고 **64비트 Windows PowerShell 5.1**에서 실행하세요. PowerShell 7, ARM64 에뮬레이션, Windows Server는 이 설정기의 지원 범위가 아닙니다. 관리자 권한은 요구하지 않습니다. 조직의 [PowerShell 실행 정책](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies?view=powershell-5.1)을 준수하세요. 이 안내는 정책 우회·영구 변경을 요구하지 않습니다.

ZIP 및 MANIFEST 해시는 손상 확인용이며 서명/발행자 신뢰를 대체하지 않습니다. 전달자의 외부 해시와 출처를 함께 확인하세요. [Get-FileHash 공식 문서](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1)의 SHA-256을 사용합니다.

```powershell
Get-FileHash -LiteralPath 'D:\Downloads\konnect-portable.zip' -Algorithm SHA256

# ZIP을 푼 폴더에서 실행합니다. 경로는 본인 PC에 맞게 바꾸세요.
powershell.exe -NoProfile -File .\Setup-Windows.ps1 `
  -ProjectDirectory 'D:\설계 작업\프로젝트' `
  -KiCadBin 'C:\Program Files\KiCad\10.0\bin'
```

`-ProjectDirectory`는 필수이며 기존 로컬 절대경로여야 합니다. `-KiCadBin`을 생략하면 Program Files의 알려진 KiCad 10 위치만 찾고, 후보가 하나가 아닐 때 멈춥니다. 한글·공백·작은따옴표는 파일 형식에서 보존합니다. 큰따옴표·개행·제어문자·Windows 금지문자는 거부합니다. PowerShell 명령의 작은따옴표 안에 작은따옴표가 있으면 두 번 적으세요.

## 2. 설정기가 하는 일과 하지 않는 일

```text
OS/path checks -> MANIFEST + all files -> size/SHA-256
  -> konnect --version + kicad-cli version -> 3 new config files
  -> manual MCP registration -> read-only connection check
```

- MANIFEST의 모든 파일 크기·SHA-256, 고정 서버 commit/버전, 경로, 미기재 파일을 확인합니다. 검증이 끝나기 전에는 번들 바이너리를 실행하지 않습니다.
- `konnect.exe --version`과 설치된 `kicad-cli.exe version`만 실행합니다. MCP 서버·KiCad GUI를 시작하거나 회로를 열지 않습니다.
- 아래 3개만 UTF-8로 새로 생성하고 전체 readback을 확인합니다. 하나라도 이미 있으면 덮지 않습니다. 중간 오류가 발생하면 생성/부분 기록 파일의 경로를 표시하며 **자동 삭제하지 않습니다**.
- AI 설정 자동 병합·전역 등록·로그인·인증 변경·도구 다운로드·방화벽/서비스 등록·실행 정책 변경을 하지 않습니다.
- `HOME`, `USERPROFILE`, `APPDATA`를 바꾸지 않습니다. KiCad의 정상 전역 라이브러리 탐색을 유지합니다. **나중에 실제 MCP 서버를 실행하면 `%APPDATA%\konnect` 등에 실행 기록/상태 파일이 생길 수 있습니다. 완전히 무상태인 앱은 아닙니다.**
- 기존 파일/부분 생성/번들 이동/다른 PC 재설정은 새 폴더에 원 ZIP을 다시 풀어 진행하거나 사용자가 기존 설정을 직접 백업한 뒤 처리하세요. 서버 실행 중인 번들의 파일을 교체하지 마세요. 설정기 재실행은 기존 생성 파일 때문에 실패하도록 설계되어 있습니다.

정확한 생성 위치는 다음과 같습니다.

```text
bundle/
+-- Start-Konnect.exe
+-- bin/windows-x86_64/konnect.exe
+-- bin/linux-x86_64/konnect
+-- config/
|   +-- active.toml
|   +-- generated/
|       +-- claude-mcp.json
|       +-- codex-mcp.toml
+-- source/exact-konnect.zip
+-- skills-reference/
+-- licenses/
+-- MANIFEST.json
```

`active.toml`은 이 PC의 절대 프로젝트/KiCad 경로를 사용하며 MCP transport는 **stdio**입니다. HTTP 포트를 열지 않습니다. 생성 파일에는 개인 경로가 들어가므로 고객/다른 PC에 그대로 배포하지 마세요. 원 ZIP에는 특정 사용자 설정·인증정보를 포함하지 않습니다.

## 3. AI 클라이언트에 수동 추가

- Claude 계열: `config/generated/claude-mcp.json`의 `mcpServers.konnect` 항목을 **사용할 프로젝트의 `.mcp.json`**에 수동 추가하세요. 기존 파일을 통째로 덮지 말고 이름 충돌을 확인하세요. 호환 여부가 불명확한 `cwd` 필드는 넣지 않았습니다.
- Codex: `config/generated/codex-mcp.toml` 내용을 **사용할 프로젝트의 `.codex/config.toml`**에 수동 추가하세요. 이 파일은 완전한 전역 설정이 아닌 스니펫입니다. `[mcp_servers.konnect]`가 이미 있다면 중복 추가하지 마세요. 프로젝트 설정은 신뢰한 프로젝트에 적용됩니다. [공식 Codex MCP 문서](https://developers.openai.com/codex/mcp)를 참고하세요.
- 두 설정 모두 `command`는 번들 `Start-Konnect.exe`의 절대경로이고 `args`는 빈 배열입니다. Codex는 `cwd`도 번들 루트로 지정합니다. 실행기는 자신의 실행 파일 위치에서 `config/active.toml`을 찾으므로 Claude의 시작 cwd에 의존하지 않습니다.
- `Start-Konnect.exe`는 네이티브 stdio 상속 실행기입니다. **PowerShell 파이프로 MCP 바이트를 중계하지 않습니다.** 터미널 stdin이면 실행을 거부하여 upstream의 더블클릭 installer를 차단합니다. 직접 더블클릭하거나 서버 `konnect.exe`를 직접 실행하지 말고 MCP 클라이언트가 실행기를 시작하게 하세요. `konnect init`도 실행하지 마세요.

클라이언트의 해당 MCP 연결만 재연결한 뒤 먼저 `get_installation_info`에서 버전·commit·실행 경로를 MANIFEST/번들 서버와 비교하고 `list_toolboxes`를 읽기 전용으로 확인하세요. 불일치/누락이면 설계 쓰기를 하지 마세요. 이 단계 성공은 GUI 연결이나 모든 도구의 Windows 동작을 증명하지 않습니다.

## 4. KiCad 연결과 안전 경계

- PCB live IPC는 **해당 PCB Editor가 실행 중이고 KiCad API가 활성화**되어야 합니다. PCB Editor의 Preferences에서 API Server/Enable KiCad API 항목을 확인하세요. 필요 시 사용자가 실제 소켓 주소를 `active.toml`의 `ipc_address`에 설정합니다. [KiCad 10 PCB Editor 공식 매뉴얼](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html)을 따르세요. 설정기는 이를 켜거나 소켓을 검증하지 않습니다.
- 회로도는 항목 수준 live IPC가 아닙니다. 파일 기반 MCP 편집 전에 GUI의 미저장 변경을 보존·저장하고 대상 회로도를 닫으세요. **GUI/MCP 동시 쓰기 및 살아 있는 편집기 잠금 삭제·우회는 금지**합니다.
- `.kicad_*`, 라이브러리, library table을 텍스트/스크립트로 직접 고치지 마세요. 도구 schema·실제 심볼 핀·제조사 자료를 확인하고 백업, dry-run/revision, readback, ERC/DRC를 분리해 검증하세요.
- GUI 실행·ERC/DRC·내보내기는 제조/통전/전기 안전·인증 완료를 뜻하지 않습니다. Linux에서 관측한 도구 수를 Windows의 보장값으로 사용하지 마세요.

## 5. 포함하지 않는 기능

- Linux ACUW GUI 동기화 bridge와 별도 `schematic-viewer`, Freerouting 서버/Java 런타임은 포함하지 않습니다. 이 기능들의 Windows 연결·자동 설치를 제공하지 않습니다.
- `skills-reference/`는 현재 품질 지침의 **참고 사본**입니다. 자동으로 AI의 스킬/훅에 등록하지 않습니다. 포함된 POSIX/Python 품질 helper의 Windows 실행은 지원/검증하지 않았습니다. 참고 문서에 Linux 경로나 셸 예제가 있더라도 이 Windows 설치 절차로 해석하지 마세요.
- Linux 바이너리를 함께 제공해도 `Setup-Windows.ps1`은 Linux 설치기가 아닙니다. macOS/ARM64 바이너리는 제공하지 않습니다.

## 6. 같은 소스로 Windows에서 직접 빌드할 때

`source/exact-konnect.zip`은 위 commit의 서버 소스와 `Cargo.lock`을 제공합니다. 별도 폴더에 풀고 `Cargo.toml`이 있는 루트에서 빌드하세요. **Rust 1.96.0**, CMake, `protoc`, MSVC C++ Build Tools/Windows SDK가 별도로 필요합니다. 이 번들은 개발 도구를 설치하지 않습니다. 공식 배포처에서 출처·정확한 버전·공급망 정책을 확인한 후 사용자가 준비하세요: [Rust](https://rust-lang.org/tools/install/), [CMake](https://cmake.org/download/), [Protocol Buffers](https://github.com/protocolbuffers/protobuf/releases), [MSVC Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

도구가 준비된 x64 개발 셸의 예시입니다. `protoc`가 PATH에 없다면 `$env:PROTOC`에 실제 실행 파일 경로를 별도로 지정하세요. 소스 ZIP은 Git 메타데이터가 없으므로 고정 source commit을 빌드 환경에 명시합니다.

```powershell
$env:KONNECT_BUILD_COMMIT = '94f80350cf67db27b179a06a8f6dbebfe4717927'
cargo +1.96.0 build --release --locked -p konnect --bin konnect `
  --target x86_64-pc-windows-msvc
```

첫 Cargo 빌드는 잠금 파일에 지정된 crate 다운로드가 필요할 수 있습니다. 잠금 파일 변경이나 최신판 자동 갱신을 하지 마세요. 직접 빌드한 서버는 원 MANIFEST와 해시가 달라지므로 **기존 번들에 덮어쓰면 설정기의 검증이 실패**합니다. 새 빌드의 라이선스·소스 결속·검증·MANIFEST를 별도로 관리해야 합니다. Windows MSVC 빌드와 실기기 실행도 아직 이 전달물의 검증 범위가 아닙니다.

Konnect와 파생 통합 코드는 `AGPL-3.0-only`를 따릅니다. `licenses/`와 동봉 소스를 함께 보존하세요. 사업용 비공개 파생/네트워크 서비스는 상용 라이선스 필요 여부를 별도 검토해야 합니다.
