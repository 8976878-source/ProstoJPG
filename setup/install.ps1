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
    $bridge = [ordered]@{status='not-requested'}
    if (-not $ExtensionOnly) {
        $cli = Resolve-Executable $CodexPath $codexCandidates
        if (-not $cli) { throw 'Codex CLI was not found. Install Codex or supply -CodexPath. Browser-only setup: -ExtensionOnly.' }
        $plugin = [ordered]@{status='planned'; executable=$cli}
        if (-not $PlanOnly) {
            $marketplace = Invoke-Codex $cli @('plugin', 'marketplace', 'add', '8976878-source/ProstoJPG', '--json')
            $installed = Invoke-Codex $cli @('plugin', 'add', 'prostojpg@prostojpg-marketplace', '--json')
            if ($installed.name -ne 'prostojpg' -or -not $installed.version) { throw 'Codex did not confirm ProstoJPG installation.' }
            $plugin = [ordered]@{status='installed'; version=$installed.version; skillsBundled=$true}
            if ($installed.installedPath) {
                $bridgeInstaller = Join-Path $installed.installedPath 'bridge\install.ps1'
                if (Test-Path -LiteralPath $bridgeInstaller -PathType Leaf) {
                    $bridgeLines = @(& $bridgeInstaller -CodexPath $cli)
                    if ($LASTEXITCODE -ne 0) { throw 'Local Codex bridge installation failed.' }
                    $bridge = ($bridgeLines -join [Environment]::NewLine) | ConvertFrom-Json
                } else { $bridge = [ordered]@{status='unavailable'; reason='Installed plugin has no native bridge installer.'} }
            } else { $bridge = [ordered]@{status='unavailable'; reason='Codex did not return installedPath; install bridge/install.ps1 from the plugin package.'} }
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
        plugin=$plugin; bridge=$bridge; browsers=@($browsers); storeUrl=$storeUrl;
        browserConfirmationRequired=$true; noSupportedBrowserFound=($browsers.Count -eq 0)
    }
    $report | ConvertTo-Json -Depth 6
} catch {
    [Console]::Error.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
    exit 1
}
