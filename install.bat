@echo off
setlocal
set "ProstoJpgSetupFile=%~f0"
set "ProstoJpgPlanOnly=0"
set "ProstoJpgNoBrowserLaunch=0"
:parse
if "%~1"=="" goto run
if /i "%~1"=="--plan" goto plan
if /i "%~1"=="--no-browser" goto nobrowser
echo Unsupported argument. Use --plan or --no-browser. 1>&2
exit /b 2
:plan
set "ProstoJpgPlanOnly=1"
shift
goto parse
:nobrowser
set "ProstoJpgNoBrowserLaunch=1"
shift
goto parse
:run
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$ErrorActionPreference='Stop'; $text=[IO.File]::ReadAllText($env:ProstoJpgSetupFile); $marker=[regex]::Match($text,'(?m)^# PROSTOJPG_POWERSHELL\r?\n'); if(-not $marker.Success){[Console]::Error.WriteLine('Installer payload missing'); exit 2}; $code=$text.Substring($marker.Index+$marker.Length); $global:LASTEXITCODE=0; & ([ScriptBlock]::Create($code)) -PlanOnly:($env:ProstoJpgPlanOnly -eq '1') -NoBrowserLaunch:($env:ProstoJpgNoBrowserLaunch -eq '1') -SkipDiscovery:($env:PROSTOJPG_SKIP_DISCOVERY -eq '1') -CodexPath $env:PROSTOJPG_CODEX_PATH -ChromePath $env:PROSTOJPG_CHROME_PATH -YandexPath $env:PROSTOJPG_YANDEX_PATH; exit $LASTEXITCODE"
exit /b %ERRORLEVEL%
# PROSTOJPG_POWERSHELL
[CmdletBinding()]
param(
    [switch]$PlanOnly,
    [switch]$ExtensionOnly,
    [switch]$NoBrowserLaunch,
    [switch]$SkipDiscovery,
    [string]$CodexPath,
    [string]$ChromePath,
    [string]$YandexPath
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$storeUrl = 'https://chromewebstore.google.com/detail/%D0%BF%D1%80%D0%BE%D1%81%D1%82%D0%BEjpg/djjocjgglhbkcfclclilmamlcoggoole'

function Resolve-Executable([string]$Override, [string[]]$Candidates) {
    if ($Override) {
        if (-not (Test-Path -LiteralPath $Override -PathType Leaf)) { throw "Executable not found: $Override" }
        return (Resolve-Path -LiteralPath $Override).Path
    }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    return $null
}

function Get-AppPath([string]$Name) {
    foreach ($hive in @('HKCU:', 'HKLM:')) {
        $key = "$hive\Software\Microsoft\Windows\CurrentVersion\App Paths\$Name"
        if (Test-Path -LiteralPath $key) {
            $value = (Get-Item -LiteralPath $key).GetValue('')
            if ($value) { return $value.Trim('"') }
        }
    }
    return $null
}

function Invoke-Codex([string]$Executable, [string[]]$CliArguments) {
    $global:LASTEXITCODE = 0
    $lines = @(& $Executable @CliArguments)
    if ($LASTEXITCODE -ne 0) { throw "Codex command failed ($LASTEXITCODE): $($CliArguments -join ' ')" }
    $data = ($lines -join [Environment]::NewLine) | ConvertFrom-Json
    if (-not $data) { throw 'Codex returned no installation result.' }
    return $data
}

try {
    $codexCandidates = @()
    $chromeCandidates = @()
    $yandexCandidates = @()
    if (-not $SkipDiscovery) {
        $command = Get-Command codex -ErrorAction SilentlyContinue
        if ($command) { $codexCandidates += $command.Source }
        if ($env:LOCALAPPDATA) {
            $codexBins = Join-Path $env:LOCALAPPDATA 'OpenAI\Codex\bin'
            if (Test-Path -LiteralPath $codexBins) {
                $codexCandidates += @(Get-ChildItem -LiteralPath $codexBins -Filter codex.exe -File -Recurse | Sort-Object LastWriteTimeUtc -Descending | ForEach-Object { $_.FullName })
            }
            $chromeCandidates += Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'
            $yandexCandidates += Join-Path $env:LOCALAPPDATA 'Yandex\YandexBrowser\Application\browser.exe'
        }
        $chromeRegistryPath = Get-AppPath 'chrome.exe'
        if ($chromeRegistryPath) { $chromeCandidates = @($chromeRegistryPath) + $chromeCandidates }
        $yandexRegistryPath = Get-AppPath 'browser.exe'
        if ($yandexRegistryPath -and $yandexRegistryPath -match 'Yandex') { $yandexCandidates = @($yandexRegistryPath) + $yandexCandidates }
        foreach ($programRoot in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
            if ($programRoot) {
                $chromeCandidates += Join-Path $programRoot 'Google\Chrome\Application\chrome.exe'
                $yandexCandidates += Join-Path $programRoot 'Yandex\YandexBrowser\Application\browser.exe'
            }
        }
    }
    $chrome = Resolve-Executable $ChromePath $chromeCandidates
    $yandex = Resolve-Executable $YandexPath $yandexCandidates
    $browsers = @()
    if ($chrome) { $browsers += [ordered]@{name='Chrome'; executable=$chrome; extensionStatus='planned'} }
    if ($yandex) { $browsers += [ordered]@{name='Yandex'; executable=$yandex; extensionStatus='planned'} }
    $plugin = [ordered]@{status='not-requested'}
    if (-not $ExtensionOnly) {
        $cli = Resolve-Executable $CodexPath $codexCandidates
        if (-not $cli) { throw 'Codex CLI was not found. Install Codex or supply -CodexPath. Browser-only setup: -ExtensionOnly.' }
        $plugin = [ordered]@{status='planned'; executable=$cli}
        if (-not $PlanOnly) {
            $marketplace = Invoke-Codex $cli @('plugin', 'marketplace', 'add', '8976878-source/ProstoJPG', '--json')
            $installed = Invoke-Codex $cli @('plugin', 'add', 'prostojpg@prostojpg-marketplace', '--json')
            if ($installed.name -ne 'prostojpg' -or -not $installed.version) { throw 'Codex did not confirm ProstoJPG installation.' }
            $plugin = [ordered]@{status='installed'; version=$installed.version; skillsBundled=$true}
        }
    }
    if (-not $PlanOnly) {
        foreach ($browser in $browsers) {
            if ($NoBrowserLaunch) {
                $browser.extensionStatus = 'not-opened'
            } else {
                try {
                    # A visible window is needed for the browser's install confirmation.
                    Start-Process -FilePath $browser.executable -ArgumentList @($storeUrl) -WindowStyle Normal | Out-Null
                    $browser.extensionStatus = 'awaiting-browser-confirmation'
                } catch {
                    $browser.extensionStatus = 'open-failed'
                    $browser.error = $_.Exception.Message
                }
            }
        }
    }
    $report = [ordered]@{
        plugin=$plugin; browsers=@($browsers); storeUrl=$storeUrl;
        browserConfirmationRequired=$true; noSupportedBrowserFound=($browsers.Count -eq 0)
    }
    $report | ConvertTo-Json -Depth 6
} catch {
    [Console]::Error.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
    exit 1
}
