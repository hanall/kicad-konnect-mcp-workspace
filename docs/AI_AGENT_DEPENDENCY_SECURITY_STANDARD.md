# AI dependency supply-chain policy

이 프로젝트는 `/home/hanol/AI_AGENT_DEPENDENCY_SECURITY_STANDARD.md`의 로컬 적용본입니다.

## 필수 통제

1. 새 의존성은 공식 registry와 publisher를 확인하고 정확한 버전과 lockfile을 함께 반영합니다.
2. 공개 후 7일 미만 release는 기본적으로 도입하지 않습니다.
3. direct URL, Git, tarball, 로컬 파일 dependency는 명시적 검토 없이 추가하지 않습니다.
4. Rust build는 upstream `Cargo.lock`과 `--locked`를 사용합니다.
5. `Cargo.lock`의 registry checksum을 유지하고 `git+` source가 생기면 gate를 실패시킵니다.
6. Python/npm 의존성을 추가하면 홈 공통 guard와 감사 절차를 적용합니다.
7. 설치 후 `make verify`, `make test`, `make mcp-smoke`를 다시 실행합니다.

## 현재 기준

- KiCad `10.0.6`: 공식 GitLab tag/commit, AppImage SHA/minisign와 라이브러리 manifest 고정
- Konnect 공식 `v0.13.0` 및 main `9488e5f0` 기반 자체 `0.13.0+hanall.1`: 공식 tag와 자체 commit을 분리 고정
- Rust `1.96.0`: upstream `rust-toolchain.toml` 고정
- `protobuf-compiler 3.21.12-11+deb13u1`: Debian 13 공식 저장소 고정
- Konnect `Cargo.lock`: package 497개, crates.io registry source 489개, Git source 0개
- 별도 viewer lock: package 81개, registry source 78개, Git source 0개
- Freerouting `2.5.0` 및 전용 JRE: `config/freerouting.lock.json`의 exact SHA와 사용자 예외 기록

Python `.pth` 감사에서 발견되는 `distutils-precedence.pth`는 Debian의
`python3-setuptools 78.1.1-0.1` 소유 파일이며 `dpkg -V`가 무결성 변경을
보고하지 않습니다. 실행 줄은 `_distutils_hack` shim으로 확인했으며 임의
네트워크·subprocess·encoded payload는 없습니다.

## 현재 승인·감사 범위

2026-10-06 사용자가 최신 upstream 업그레이드의 공급망 예외와 Freerouting 2.5.0의 공개 7일 미만 예외를 명시 승인했습니다. Rust에 채택된 registry release는 별도 검토에서 모두 공개 후 7일 이상을 충족했습니다. GitHub asset digest는 독립 서명으로 표현하지 않습니다. audit의 마지막 advisory DB commit/시각, 조회 여부와 0건 결과는 최종 보고서에 함께 기록합니다.

프로젝트 `.artifacts` 아래의 검증 전용 Python venv도 공통 guard·정확 버전/hash lock·`.pth` 감사 대상입니다. runtime/application dependency 또는 사용자 전역 패키지로 조용히 승격하지 않습니다.
