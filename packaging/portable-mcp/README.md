# Konnect MCP 공통 배포 묶음

이 ZIP은 공통 소스와 OS별 실행 파일을 한곳에 둔 **복사형 배포 묶음**입니다. 하나의 실행 파일이 모든 OS에서 실행되는 형식은 아닙니다. KiCad 자체는 각 OS용으로 별도 설치합니다.

```text
common source
  +-- Windows x86_64 -> Start-Konnect.exe
  +-- Linux x86_64   -> Start-Konnect
  `-- macOS         -> source build only
```

## Windows 11

먼저 [Windows 설치 안내](README-WINDOWS.md)를 읽으세요. 관리자·Rust·Python 설치 없이 동봉된 실행 파일을 사용할 수 있도록 구성했지만, **Windows 실기기 실행과 PowerShell 설정기 실행은 이 Linux 호스트에서 검증하지 못했습니다.** 동봉 Windows 서버는 같은 고정 소스의 교차 빌드이며 Authenticode 서명은 없습니다. 정상 동작을 보장하는 검증 완료 배포판으로 표시하지 않습니다.

`Setup-Windows.ps1`은 설치된 KiCad 10과 대상 프로젝트를 확인한 후, 이 번들 안에 런타임 설정과 클라이언트 등록 예제를 생성합니다. 다른 프로그램 설정·로그인 정보·시스템 실행 정책은 바꾸지 않습니다. 원 ZIP에 포함된 MANIFEST와 전달받은 외부 SHA-256을 먼저 대조하세요.

PowerShell 실행이 조직 정책상 금지되어 있다면 정책을 우회하지 마세요. `config/active-windows.example.toml`을 읽고 경로를 본인 PC에 맞게 바꿔 `config/active.toml`로 저장한 뒤, `client-config-examples/`의 예제를 수동으로 등록할 수 있습니다. 한 번 설정한 번들을 이동했다면 경로를 다시 대조해야 합니다.

## Linux x86_64

Linux 실행 파일도 같은 고정 소스로 빌드했습니다. Debian 13 계열에서 검사했으며, ELF의 실제 GLIBC 요구 버전은 `BUILD-INFO.json`을 확인하세요. 다른 배포판의 동작을 검증했다고 주장하지 않습니다.

1. ZIP을 새 디렉터리에 풉니다.
2. `chmod +x Start-Konnect bin/linux-x86_64/konnect`로 실행 권한을 확인합니다.
3. `config/active-linux.example.toml`의 KiCad CLI·프로젝트 경로를 고쳐 `config/active.toml`로 저장합니다.
4. MCP 클라이언트의 command를 이 폴더의 `Start-Konnect` 절대경로로 등록합니다. 터미널에서 직접 실행하지 않습니다. `--version`, `--check`는 읽기 전용 점검용입니다.

서버의 정상 사용자 상태 경로를 유지합니다. Linux는 `~/.konnect`, Windows는 `%APPDATA%\konnect` 등에 로그·실행 기록이 생길 수 있습니다. 실행마다 모든 흔적이 사라지는 무상태 프로그램이 아닙니다.

## 포함 범위와 한계

- Konnect `0.13.0+hanall.1`, commit `94f80350cf67db27b179a06a8f6dbebfe4717927`의 Windows/Linux 서버와 얇은 native stdio 실행기
- 같은 commit의 원 소스 ZIP·Cargo.lock·라이선스·빌드 안내
- 기존 회로도 품질 지침은 `skills-reference/`에 참고용으로 동봉합니다. 그 안의 Python helper는 POSIX 전제이며 **Windows 지원으로 승격하지 않습니다**. 자동 설치·스킬 등록·hook 실행은 하지 않습니다.
- Linux ACUW GUI bridge, schematic viewer, Freerouting/Java, KiCad 설치본, 사용자 CAD·설정·인증·캐시·로그는 동봉하지 않습니다.
- macOS와 Linux ARM64/Windows ARM64 실행 파일은 없습니다. 원 소스에 해당 플랫폼의 빌드 환경이 별도로 필요합니다.
- 공급된 서버와 실행기는 파일 기반 회로도·CLI·IPC 기능을 구분합니다. 실제 PCB 작업 전에는 해당 Windows/Linux KiCad에서 API 활성화와 문서 identity를 확인해야 합니다.

## 소스와 무결성

`source/exact-konnect.zip`은 위 commit의 Git 추적 파일을 그대로 보존합니다. `source/launcher.rs`는 배포 실행기 소스입니다. 원 서버 소스·Cargo.lock·기존 설치본을 수정해 만든 바이너리가 아닙니다. Windows 빌드에서는 Clang/MinGW toolchain을 명시했고, 사용자 빌드 경로를 remap한 후 debug section을 제거했습니다. 상세는 `BUILD-INFO.json`에 기록합니다.

각 파일은 `MANIFEST.json`의 상대경로·크기·SHA-256으로 결속합니다. MANIFEST 자체는 자기 목록에서 제외합니다. 최상위 ZIP 전체의 SHA-256은 ZIP 옆 파일로 별도 제공합니다. 해시는 손상 확인이며 서명이나 발행자 신뢰의 대체가 아닙니다.

라이선스와 제3자 고지는 `licenses/`에 있습니다. 소스 ZIP 안의 공개 upstream 예제/시험 fixture는 원본 소스의 일부이며 사용자의 작업 회로가 아닙니다. 원본 예제를 변경하지 않고 보존했습니다. 첫 소스 빌드는 Cargo.lock에 명시된 registry 의존성 다운로드가 필요할 수 있으며 완전 offline source vendor 묶음은 아닙니다.

이 묶음은 사용자의 다른 PC에서 사용하도록 로컬 파일로 전달합니다. 공개 게시나 제3자 재배포의 권리 검토를 완료했다는 뜻은 아닙니다. 원 소스의 일부 로고에는 별도 권리 문구가 있어 `licenses/source-assets/UNRESOLVED-NOTICES.md`에 원문 위치와 미확인 사항을 보존했습니다.
