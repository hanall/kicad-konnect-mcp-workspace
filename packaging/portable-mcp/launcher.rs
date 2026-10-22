//! 공통 소스의 얇은 실행기. MCP의 표준 입출력을 변환하지 않는다.
use std::io::{self, IsTerminal};
use std::path::{Path, PathBuf};
use std::process::{self, Command, Stdio};

fn relative_binary(os: &str, arch: &str) -> Result<&'static str, &'static str> {
    match (os, arch) {
        ("windows", "x86_64") => Ok("bin/windows-x86_64/konnect.exe"),
        ("linux", "x86_64") => Ok("bin/linux-x86_64/konnect"),
        ("macos", "x86_64") => Ok("bin/macos-x86_64/konnect"),
        ("macos", "aarch64") => Ok("bin/macos-aarch64/konnect"),
        _ => Err("이 실행 파일이 지원하지 않는 운영체제 또는 아키텍처입니다"),
    }
}

fn paths(root: &Path) -> Result<(PathBuf, PathBuf), String> {
    let relative = relative_binary(std::env::consts::OS, std::env::consts::ARCH)?;
    Ok((root.join(relative), root.join("config/active.toml")))
}

fn run() -> Result<i32, String> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() > 1 {
        return Err("인자는 --version, --check 또는 --help 하나만 허용합니다".into());
    }
    let option = args.first().map(|s| s.to_string_lossy().into_owned());
    if option.as_deref() == Some("--help") {
        println!("MCP 클라이언트의 command에 이 실행기를 등록하세요. 직접 실행은 --version 또는 --check만 사용하세요.");
        return Ok(0);
    }
    if !matches!(option.as_deref(), None | Some("--version") | Some("--check")) {
        return Err("지원하지 않는 인자입니다. 임의 subcommand를 전달하지 않습니다".into());
    }
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let root = executable.parent().ok_or("실행기 위치를 찾지 못했습니다")?;
    let (server, config) = paths(root)?;
    if !server.is_file() {
        return Err(format!("현재 OS용 서버 실행 파일이 없습니다: {}", server.display()));
    }
    if option.as_deref() == Some("--version") {
        let status = Command::new(&server).arg("--version").stdin(Stdio::null())
            .stdout(Stdio::inherit()).stderr(Stdio::inherit())
            .status().map_err(|e| format!("버전 확인 실패: {e}"))?;
        return Ok(status.code().unwrap_or(1));
    }
    if !config.is_file() {
        return Err(format!("설정이 없습니다. 먼저 Setup-Windows.ps1 또는 수동 설정 안내를 따르세요: {}", config.display()));
    }
    if option.as_deref() == Some("--check") {
        println!("실행 파일과 설정 경로 확인 완료. 실제 MCP·KiCad 연결 검증은 별도입니다.");
        return Ok(0);
    }
    // upstream은 대화형 stdin에서 설치기를 시작하므로 우발적인 실행을 막는다.
    if io::stdin().is_terminal() {
        return Err("대화형 직접 실행은 거부합니다. MCP 클라이언트에서 시작하세요".into());
    }
    let status = Command::new(&server).arg("--config").arg(&config)
        .current_dir(root).stdin(Stdio::inherit()).stdout(Stdio::inherit())
        .stderr(Stdio::inherit()).status()
        .map_err(|e| format!("MCP 서버 실행 실패: {e}"))?;
    Ok(status.code().unwrap_or(1))
}

fn main() {
    match run() {
        Ok(code) => process::exit(code),
        Err(message) => { eprintln!("{message}"); process::exit(2); }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn windows_binary() { assert_eq!(relative_binary("windows", "x86_64"), Ok("bin/windows-x86_64/konnect.exe")); }
    #[test] fn linux_binary() { assert_eq!(relative_binary("linux", "x86_64"), Ok("bin/linux-x86_64/konnect")); }
    #[test] fn macos_intel() { assert_eq!(relative_binary("macos", "x86_64"), Ok("bin/macos-x86_64/konnect")); }
    #[test] fn macos_arm() { assert_eq!(relative_binary("macos", "aarch64"), Ok("bin/macos-aarch64/konnect")); }
    #[test] fn unsupported_platform_fails() { assert!(relative_binary("windows", "aarch64").is_err()); assert!(relative_binary("linux", "aarch64").is_err()); }
    #[test] fn location_bound_not_cwd() { let p=Path::new("folder with spaces"); let (_, config)=paths(p).unwrap(); assert_eq!(config, p.join("config/active.toml")); }
}
