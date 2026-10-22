# 동봉 실행 파일의 소스·빌드 안내

일반 Windows 사용자는 빌드 도구가 필요 없습니다. `README-WINDOWS.md`를 따릅니다.
이 문서는 소스에서 다시 빌드하려는 개발자용입니다. 새 도구 설치는 자동화하지 않습니다.

## 소스 결속

- 서버: `exact-konnect.zip`, 고정 commit `94f80350cf67db27b179a06a8f6dbebfe4717927`, `0.13.0+hanall.1`.
- 소스 안의 `Cargo.lock`은 변경하지 않습니다. 의존성 소스 vendor는 포함하지 않으므로 첫 빌드에 registry 다운로드가 필요할 수 있습니다.
- stdio 실행기: `launcher.rs`. 외부 crate를 쓰지 않습니다. `--version`과 `--check`만 직접 실행하고 정상 MCP는 클라이언트에서 기동합니다.
- 실제 빌드는 Rust `1.96.0`을 사용했습니다. 재현 입력은 고정하지만 다른 컴파일러/경로에서 byte-identical 결과를 보장하지 않습니다.
- Linux는 Debian 13의 기존 GCC·CMake·protoc로 빌드했습니다. 제공 ELF의 GLIBC symbol 요구는 2.39이며 구버전 GLIBC 배포판은 별도 빌드가 필요합니다.
- Windows 실행 파일은 Linux에서 Clang 14·MinGW-w64 GCC 14 조합으로 교차 빌드했습니다. Windows 실행과 MSVC 빌드는 시험하지 않았습니다.

## Linux 네이티브 서버·실행기

`exact-konnect.zip`을 새 개발 폴더에 풀고 서버 소스의 `Cargo.toml`이 있는 곳에서 실행합니다.
Rust, CMake, protobuf compiler와 C/C++ 빌드 도구를 별도 준비해야 합니다. upstream `DEV.md`도 확인하세요.

```bash
export KONNECT_BUILD_COMMIT=94f80350cf67db27b179a06a8f6dbebfe4717927
export RUSTFLAGS="--remap-path-prefix=$HOME=/build/user"
cargo +1.96.0 build --release --locked -p konnect --bin konnect
```

캐시가 모두 갖춰진 배포 빌드에는 `--locked`보다 강한 `--frozen`을 사용했습니다.
실행기는 `launcher.rs`가 있는 디렉터리에서 별도로 빌드합니다.

```bash
rustc +1.96.0 --edition=2021 -O \
  --remap-path-prefix="$HOME=/build/user" launcher.rs -o Start-Konnect
```

## 같은 Linux toolchain으로 Windows 서버 교차 빌드

동봉 `build-support/`는 실제 사용한 compiler wrapper와 경로 상대화한 CMake toolchain입니다.
다음 `/usr` 경로가 실제로 있는 Linux 환경의 예시이며 범용 설치기가 아닙니다:
Clang 14, `/usr/x86_64-w64-mingw32`, MinGW-w64 GCC 14 win32 런타임,
`x86_64-w64-mingw32-gcc`, `x86_64-w64-mingw32-ld`, CMake, protoc.
Rust 1.96.0의 `x86_64-pc-windows-gnu` 표준 라이브러리도 필요합니다.

compiler wrapper는 CMake의 자동 `-w`를 제거하며 `-Wno-error*`를 거부합니다.
NNG 소스나 의존성 파일을 고치지 않았습니다. 원 GCC 빌드 실패를 성공으로 바꾸어 기록하지 않고
Clang toolchain에서 새로 빌드했습니다. 원 경고가 없었다는 뜻은 아닙니다.

서버 소스 루트에서 `SUPPORT`를 실제 동봉 경로로 바꾸어 실행합니다.

```bash
SUPPORT=/absolute/path/to/source/build-support
chmod +x "$SUPPORT"/*.sh
export KONNECT_BUILD_COMMIT=94f80350cf67db27b179a06a8f6dbebfe4717927
export RUSTFLAGS="--remap-path-prefix=$HOME=/build/user"
export CFLAGS_x86_64_pc_windows_gnu="-ffile-prefix-map=$HOME=/build/user"
export CXXFLAGS_x86_64_pc_windows_gnu="$CFLAGS_x86_64_pc_windows_gnu"
export CC_x86_64_pc_windows_gnu="$SUPPORT/clang-windows-cc-remap.sh"
export CXX_x86_64_pc_windows_gnu="$SUPPORT/clang-windows-cxx-remap.sh"
export CMAKE_TOOLCHAIN_FILE_x86_64_pc_windows_gnu="$SUPPORT/windows-clang-mingw-remap.cmake"
export CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=/usr/bin/x86_64-w64-mingw32-gcc
cargo +1.96.0 build --release --locked --target x86_64-pc-windows-gnu \
  -p konnect --bin konnect -j4
```

실행기는 `launcher.rs`가 있는 곳에서 별도로 빌드합니다.

```bash
rustc +1.96.0 --edition=2021 -O \
  --remap-path-prefix="$HOME=/build/user" \
  --target x86_64-pc-windows-gnu \
  -C linker=/usr/bin/x86_64-w64-mingw32-gcc launcher.rs -o Start-Konnect.exe
```

## 배포 후처리와 검증 범위

제공 사본에는 각 플랫폼의 `strip --strip-debug`를 적용했습니다. 서버 `.text`가 후처리 전후
같음을 확인했고 Windows DLL import set도 같았습니다. `BUILD-INFO.json`과 `MANIFEST.json`에
최종 배포 파일의 SHA·크기·native 실행 여부를 기록했습니다.

새 빌드를 기존 번들 파일에 덮으면 원 MANIFEST와 불일치합니다. 원 번들을 보존하고 새 빌드는
별도 디렉터리·별도 검증·별도 MANIFEST로 관리하세요. 원 서버 소스 라이선스는 `licenses/`에,
이 배포 실행기와 통합 코드의 라이선스는 `AGPL-3.0-only`입니다.
