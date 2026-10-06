[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$CodexPath,
    [string]$PythonPath,
    [string]$InstallRoot,
    [string]$ExtensionId = 'djjocjgglhbkcfclclilmamlcoggoole',
    [switch]$PlanOnly,
    [switch]$NoRegister
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
try {
    if ($ExtensionId -notmatch '^[a-p]{32}$') { throw 'Invalid extension ID.' }
    $cliPath = (Resolve-Path -LiteralPath $CodexPath -ErrorAction Stop).Path
    if (-not $PythonPath) {
        $runtimePython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $runtimePython -PathType Leaf) { $PythonPath = $runtimePython }
        else {
            $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
            if ($pythonCommand -and $pythonCommand.Source -notmatch 'WindowsApps') { $PythonPath = $pythonCommand.Source }
        }
    }
    if (-not $PythonPath) { throw 'Python 3.10+ is required for the local Codex bridge.' }
    $pythonExe = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
    & $pythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required for the local Codex bridge.' }
    if (-not $InstallRoot) { $InstallRoot = Join-Path $env:LOCALAPPDATA 'ProstoJPG\codex-bridge\1.0.3' }
    $destination = [IO.Path]::GetFullPath($InstallRoot)
    $manifestPath = Join-Path $destination 'ru.prostoseller.codex_bridge.json'
    $registrationKeys = @('HKCU:\Software\Google\Chrome\NativeMessagingHosts\ru.prostoseller.codex_bridge',
        'HKCU:\Software\Yandex\YandexBrowser\NativeMessagingHosts\ru.prostoseller.codex_bridge')
    if ($PlanOnly) {
        @{status='planned'; installRoot=$destination; python=$pythonExe; codex=$cliPath; registryKeys=$registrationKeys; extensionId=$ExtensionId} | ConvertTo-Json -Depth 4
        exit 0
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($name in @('host.py','codex_rpc.py','runner.py','cards.py')) {
        $source = Join-Path $PSScriptRoot $name
        $target = Join-Path $destination $name
        if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($target)) { Copy-Item -LiteralPath $source -Destination $target -Force }
    }
    & $pythonExe -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("PIL") else 1)'
    if ($LASTEXITCODE -ne 0) {
        $pipOutput = @(& $pythonExe -m pip install --disable-pip-version-check --target (Join-Path $destination 'vendor') 'Pillow>=10' 2>&1)
        foreach ($line in $pipOutput) { [Console]::Error.WriteLine([string]$line) }
        if ($LASTEXITCODE -ne 0) { throw 'Pillow installation failed.' }
    }
    $jobsRoot = Join-Path ([IO.Directory]::GetParent($destination).FullName) 'jobs'
    $configText = @{codexPath=$cliPath; jobsRoot=$jobsRoot; extensionId=$ExtensionId} | ConvertTo-Json
    [IO.File]::WriteAllText((Join-Path $destination 'config.json'),$configText,[Text.UTF8Encoding]::new($false))
    $launcher = "@echo off`r`nchcp 65001 >nul`r`n`"$pythonExe`" -X utf8 `"%~dp0host.py`" %*`r`n"
    [IO.File]::WriteAllText((Join-Path $destination 'host.cmd'),$launcher,[Text.UTF8Encoding]::new($false))
    $manifestText = @{name='ru.prostoseller.codex_bridge'; description='ProstoJPG product cards with local Codex'; path=(Join-Path $destination 'host.cmd'); type='stdio'; allowed_origins=@("chrome-extension://$ExtensionId/")} | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($manifestPath,$manifestText,[Text.UTF8Encoding]::new($false))
    if (-not $NoRegister) {
        foreach ($key in $registrationKeys) {
            New-Item -Path $key -Force | Out-Null
            Set-Item -LiteralPath $key -Value $manifestPath
        }
    }
    @{status=$(if ($NoRegister) {'files-only'} else {'installed'}); manifest=$manifestPath; extensionId=$ExtensionId; codex=$cliPath; python=$pythonExe} | ConvertTo-Json
} catch {
    [Console]::Error.WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
    exit 1
}
