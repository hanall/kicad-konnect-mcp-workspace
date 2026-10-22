#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectDirectory,
    [string]$KiCadBin
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ExpectedVersion = '0.13.0+hanall.1'
$ExpectedCommit = '94f80350cf67db27b179a06a8f6dbebfe4717927'
$CreatedFiles = New-Object 'System.Collections.Generic.List[string]'

function Assert-SafeText([string]$Value, [string]$Label) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\x00-\x1f\x7f"<>|]') {
        throw "$Label 경로가 비었거나 제어문자, 큰따옴표 또는 Windows 금지문자를 포함합니다."
    }
}

function Assert-NoReparse([string]$Path) {
    $cursor = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $attributes = [System.IO.File]::GetAttributes($cursor)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "심볼릭 링크 또는 reparse point 경로를 거부합니다: $cursor"
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Get-LocalDirectory([string]$Path, [string]$Label) {
    Assert-SafeText $Path $Label
    # UNC, 장치 경로, drive-relative 및 상대 경로를 받지 않습니다.
    if ($Path -notmatch '^[A-Za-z]:[\\/]') {
        throw "$Label 에는 로컬 드라이브의 절대경로를 입력하세요."
    }
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.Substring(2).Contains(':')) { throw "$Label 에 ADS 경로를 사용할 수 없습니다." }
    Assert-NoReparse $full
    if (-not (Test-Path -LiteralPath $full -PathType Container)) {
        throw "$Label 폴더가 없습니다. 먼저 폴더를 준비하세요: $full"
    }
    return $full
}

function Get-BundleFile([string]$Relative) {
    Assert-SafeText $Relative 'MANIFEST'
    if ([System.IO.Path]::IsPathRooted($Relative) -or $Relative -match '[:\\]' -or $Relative.StartsWith('/')) {
        throw "MANIFEST 경로는 /로 구분한 상대경로여야 합니다: $Relative"
    }
    foreach ($segment in $Relative.Split('/')) {
        if ([string]::IsNullOrEmpty($segment) -or $segment -eq '.' -or $segment -eq '..' -or
            $segment -match '[. ]$' -or $segment -match '[*?]' -or
            $segment -match '^(?i:CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)') {
            throw "MANIFEST 경로 구성요소를 거부합니다: $Relative"
        }
    }
    $full = [System.IO.Path]::GetFullPath((Join-Path $BundleRoot $Relative))
    $prefix = $BundleRoot.TrimEnd('\', '/') + '\'
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "번들 밖 경로를 거부합니다: $Relative"
    }
    Assert-NoReparse $full
    if (-not (Test-Path -LiteralPath $full -PathType Leaf)) {
        throw "번들 파일이 없습니다: $Relative"
    }
    return $full
}

function ConvertTo-TomlString([string]$Value) {
    Assert-SafeText $Value 'TOML'
    # TOML 기본 문자열. 경로의 공백, 한글, 작은따옴표는 보존합니다.
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function Get-VersionOutput([string]$Executable, [string]$Argument) {
    # shell을 거치지 않고 읽기 전용 버전 인자 하나만 실행합니다.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Argument
    $info.WorkingDirectory = $BundleRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        if (-not $process.Start()) { throw '버전 조회 프로세스를 시작하지 못했습니다.' }
        $process.StandardInput.Close()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(15000)) {
            $process.Kill()
            $process.WaitForExit()
            throw "버전 조회 15초 초과: $Executable"
        }
        $output = $stdout.GetAwaiter().GetResult()
        $errorOutput = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            throw "버전 조회 실패(rc=$($process.ExitCode)): $errorOutput"
        }
        if (-not [string]::IsNullOrWhiteSpace($errorOutput)) {
            throw "버전 조회가 stderr를 출력했습니다: $errorOutput"
        }
        return $output.Trim()
    }
    finally { $process.Dispose() }
}

function Write-NewUtf8File([string]$Path, [string]$Content) {
    Assert-NoReparse $Path
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $bytes = $encoding.GetBytes($Content)
    # 존재 확인 이후의 경합도 CreateNew로 방어합니다. 기존 파일은 덮지 않습니다.
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    $CreatedFiles.Add($Path)
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally { $stream.Dispose() }
    if ([System.IO.File]::ReadAllText($Path, $encoding) -cne $Content) {
        throw "생성 파일 전체 readback 불일치: $Path"
    }
}

try {
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT -or
        -not [System.Environment]::Is64BitOperatingSystem -or [IntPtr]::Size -ne 8) {
        throw 'Windows 11 x64 및 64비트 PowerShell에서만 설정할 수 있습니다.'
    }
    if ($PSVersionTable.PSEdition -ne 'Desktop' -or
        $PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
        throw '이 설정기는 Windows PowerShell 5.1 전용입니다. powershell.exe -NoProfile로 실행하세요.'
    }
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $processors = @(Get-CimInstance -ClassName Win32_Processor)
    if ([int]$os.BuildNumber -lt 22000 -or $os.Version -notmatch '^10\.' -or
        [int]$os.ProductType -ne 1 -or $processors.Count -eq 0) {
        throw 'Windows 11 클라이언트 OS가 아닙니다. Windows Server와 다른 OS는 지원하지 않습니다.'
    }
    foreach ($processor in $processors) {
        if ([int]$processor.Architecture -ne 9) {
            throw '실제 CPU가 x64가 아닙니다. ARM64/x86 및 에뮬레이션 설치는 지원하지 않습니다.'
        }
    }

    $BundleRoot = Get-LocalDirectory $PSScriptRoot '번들'
    $manifestPath = Get-BundleFile 'MANIFEST.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (($manifest.schema_version -isnot [int] -and $manifest.schema_version -isnot [long]) -or
        $manifest.schema_version -ne 1 -or $manifest.konnect.version -isnot [string] -or
        $manifest.konnect.commit -isnot [string] -or $manifest.konnect.version -cne $ExpectedVersion -or
        $manifest.konnect.commit -cne $ExpectedCommit -or $manifest.files -isnot [System.Array] -or
        $manifest.files.Count -eq 0) {
        throw 'MANIFEST 스키마 또는 고정 Konnect 소스/버전이 일치하지 않습니다.'
    }
    $listed = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $manifest.files) {
        if ($entry.path -isnot [string] -or $entry.sha256 -isnot [string] -or
            $entry.sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            ($entry.size -isnot [int] -and $entry.size -isnot [long]) -or $entry.size -lt 0) {
            throw 'MANIFEST 파일 항목의 path/size/sha256 형식이 잘못되었습니다.'
        }
        if ($entry.path -ieq 'MANIFEST.json' -or -not $listed.Add($entry.path)) {
            throw "중복 또는 자기참조 MANIFEST 항목입니다: $($entry.path)"
        }
        $file = Get-BundleFile $entry.path
        if ((Get-Item -LiteralPath $file).Length -ne $entry.size -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.sha256) {
            throw "번들 크기/SHA-256 검증 실패: $($entry.path)"
        }
    }
    foreach ($required in @('Setup-Windows.ps1', 'README-WINDOWS.md', 'Start-Konnect.exe',
            'bin/windows-x86_64/konnect.exe', 'bin/linux-x86_64/konnect', 'source/exact-konnect.zip')) {
        if (-not $listed.Contains($required)) { throw "MANIFEST 필수 파일 누락: $required" }
    }
    # 미기재 DLL 등의 끼워 넣기를 방지합니다. 링크는 재귀 진입 전에 검사합니다.
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($BundleRoot)
    while ($pending.Count -gt 0) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            Assert-NoReparse $item.FullName
            if ($item.PSIsContainer) { $pending.Push($item.FullName); continue }
            $relative = $item.FullName.Substring($BundleRoot.TrimEnd('\', '/').Length + 1).Replace('\', '/')
            if ($relative -ine 'MANIFEST.json' -and -not $listed.Contains($relative)) {
                throw "MANIFEST에 없는 파일이 있습니다. 새 폴더에 ZIP을 다시 풀어주세요: $relative"
            }
        }
    }

    $project = Get-LocalDirectory $ProjectDirectory '프로젝트'
    if ([string]::IsNullOrWhiteSpace($KiCadBin)) {
        $candidates = @()
        foreach ($base in @($env:ProgramW6432, $env:ProgramFiles)) {
            if (-not [string]::IsNullOrWhiteSpace($base)) {
                foreach ($version in @('10.0', '10.0.6', '10')) {
                    $candidate = Join-Path $base ("KiCad\$version\bin")
                    if (Test-Path -LiteralPath (Join-Path $candidate 'kicad-cli.exe') -PathType Leaf) {
                        $candidates += $candidate
                    }
                }
            }
        }
        $candidates = @($candidates | Sort-Object -Unique)
        if ($candidates.Count -ne 1) {
            throw 'KiCad 10 bin 자동 탐색 결과가 없거나 여러 개입니다. -KiCadBin 절대경로를 지정하세요.'
        }
        $KiCadBin = $candidates[0]
    }
    $kicad = Get-LocalDirectory $KiCadBin 'KiCad bin'
    $cli = Join-Path $kicad 'kicad-cli.exe'
    $gui = Join-Path $kicad 'kicad.exe'
    foreach ($exe in @($cli, $gui)) {
        Assert-NoReparse $exe
        if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "KiCad 실행 파일 누락: $exe" }
    }
    $activePath = Join-Path $BundleRoot 'config\active.toml'
    $generated = Join-Path $BundleRoot 'config\generated'
    $claudePath = Join-Path $generated 'claude-mcp.json'
    $codexPath = Join-Path $generated 'codex-mcp.toml'
    foreach ($path in @($activePath, $claudePath, $codexPath)) {
        Assert-NoReparse $path
        if (Test-Path -LiteralPath $path) { throw "기존 설정을 덮지 않습니다: $path" }
    }
    if (-not (Test-Path -LiteralPath $generated -PathType Container)) {
        throw '번들의 config/generated 폴더가 없습니다. ZIP을 완전히 풀어주세요.'
    }
    # 모든 파일 검증과 출력 충돌 검사가 끝난 뒤에만 바이너리를 실행합니다.
    $server = Get-BundleFile 'bin/windows-x86_64/konnect.exe'
    $version = Get-VersionOutput $server '--version'
    if ($version -cne "konnect $ExpectedVersion") { throw "Konnect 버전 불일치: $version" }
    $kicadVersion = Get-VersionOutput $cli 'version'
    if ($kicadVersion -notmatch '^10\.\d+\.\d+(?:[-+ ].*)?$') {
        throw "KiCad 10 버전 확인 실패: $kicadVersion"
    }

    $wrapper = Get-BundleFile 'Start-Konnect.exe'
    $active = @(
        '# 이 PC의 경로입니다. 다른 PC에서는 새 번들로 다시 설정하세요.'
        'transport = "stdio"'
        ('project_dir = ' + (ConvertTo-TomlString $project))
        ('kicad_cli = ' + (ConvertTo-TomlString $cli))
        ('kicad_binary = ' + (ConvertTo-TomlString $gui))
        'ipc_address = ""'
        'log_level = "info"'
    ) -join "`n"
    $claude = [ordered]@{
        mcpServers = [ordered]@{
            konnect = [ordered]@{ type = 'stdio'; command = $wrapper; args = @() }
        }
    } | ConvertTo-Json -Depth 8
    $codex = @(
        '# 수동으로 프로젝트 .codex/config.toml에 추가할 스니펫입니다.'
        '[mcp_servers.konnect]'
        ('command = ' + (ConvertTo-TomlString $wrapper))
        'args = []'
        ('cwd = ' + (ConvertTo-TomlString $BundleRoot))
    ) -join "`n"
    Write-NewUtf8File $activePath ($active + "`n")
    Write-NewUtf8File $claudePath ($claude + "`n")
    Write-NewUtf8File $codexPath ($codex + "`n")
    Write-Host "설정 생성 완료: Konnect $ExpectedVersion / KiCad $kicadVersion"
    foreach ($path in $CreatedFiles) { Write-Host "생성: $path" }
    Write-Host 'MCP는 시작하지 않았습니다. README-WINDOWS.md의 수동 등록·연결 확인을 진행하세요.'
    Write-Host '다른 AI 설정, 로그인 정보, HOME/USERPROFILE/APPDATA는 변경하지 않았습니다.'
}
catch {
    [Console]::Error.WriteLine("설정 실패: $($_.Exception.Message)")
    if ($CreatedFiles.Count -gt 0) {
        [Console]::Error.WriteLine('다음 파일이 생성되었거나 부분 기록되었습니다. 자동 삭제·덮어쓰기는 하지 않습니다:')
        foreach ($path in $CreatedFiles) { [Console]::Error.WriteLine($path) }
        [Console]::Error.WriteLine('이 파일을 확인·백업하거나 새 폴더에 ZIP을 다시 푼 뒤 재시도하세요.')
    }
    exit 1
}
