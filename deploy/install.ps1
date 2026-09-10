# DotAudio source installer for Windows.
# Requires: Git, Python 3.12 or 3.13 in PATH.
# Creates .venv, editable install, Desktop + Start Menu shortcuts.

[CmdletBinding()]
param(
    [string]$RepoUrl = "https://github.com/network-user/DotAudio.git",
    [string]$InstallDir = "",
    [string]$Branch = "main",
    [switch]$SkipShortcut,
    [switch]$Launch
)

$ErrorActionPreference = "Stop"

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Не найдена команда '$Name'. Установите её и повторите."
    }
}

function Resolve-Python {
    foreach ($name in @("py", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($name -eq "py") {
            try {
                $ver = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) { return $ver.Trim() }
            } catch {}
            try {
                $ver = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $ver) { return $ver.Trim() }
            } catch {}
        } else {
            $exe = $cmd.Source
            $check = & $exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}'); print(sys.executable)"
            if ($LASTEXITCODE -ne 0) { continue }
            $lines = @($check)
            $minor = $lines[0]
            if ($minor -match '^3\.(12|13)$') {
                return $lines[1].Trim()
            }
        }
    }
    throw "Нужен Python 3.12 или 3.13 (команда py или python)."
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$IconLocation,
        [string]$Description = "DotAudio"
    )
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($Path)
    $s.TargetPath = $Target
    $s.Arguments = $Arguments
    $s.WorkingDirectory = $WorkingDirectory
    $s.WindowStyle = 7
    $s.Description = $Description
    if (Test-Path $IconLocation) {
        $s.IconLocation = "$IconLocation,0"
    }
    $s.Save()
}

Assert-Command git
$python = Resolve-Python
Write-Host "Python: $python"

if (-not $InstallDir) {
    $here = (Get-Location).Path
    if (Test-Path (Join-Path $here ".git")) {
        $InstallDir = $here
        Write-Host "Используем текущий клон: $InstallDir"
    } else {
        $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\DotAudio"
    }
}

if (-not (Test-Path (Join-Path $InstallDir ".git"))) {
    $parent = Split-Path -Parent $InstallDir
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if (Test-Path $InstallDir) {
        throw "Каталог уже существует и это не git-клон: $InstallDir"
    }
    Write-Host "Клонируем $RepoUrl ($Branch) → $InstallDir"
    git clone --branch $Branch --single-branch $RepoUrl $InstallDir
    if ($LASTEXITCODE -ne 0) { throw "git clone не удался" }
} else {
    Write-Host "Репозиторий найден: $InstallDir"
    Push-Location $InstallDir
    try {
        git fetch origin $Branch
        git checkout -f -B $Branch "origin/$Branch"
        git reset --hard "origin/$Branch"
    } finally {
        Pop-Location
    }
}

$venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Создаём .venv"
    & $python -m venv (Join-Path $InstallDir ".venv")
    if ($LASTEXITCODE -ne 0) { throw "venv не создался" }
}

Write-Host "Устанавливаем DotAudio (editable)"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e "$InstallDir"
if ($LASTEXITCODE -ne 0) { throw "pip install -e . не удался" }

$icon = Join-Path $InstallDir "src\dotaudio\assets\app_icon.ico"
$target = if (Test-Path $venvPythonw) { $venvPythonw } else { $venvPython }
$launchArgs = "-m dotaudio"

if (-not $SkipShortcut) {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $desktopLnk = Join-Path $desktop "DotAudio.lnk"
    New-Shortcut -Path $desktopLnk -Target $target -Arguments $launchArgs `
        -WorkingDirectory $InstallDir -IconLocation $icon
    Write-Host "Ярлык на рабочем столе: $desktopLnk"

    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\DotAudio"
    $startLnk = Join-Path $startMenu "DotAudio.lnk"
    New-Shortcut -Path $startLnk -Target $target -Arguments $launchArgs `
        -WorkingDirectory $InstallDir -IconLocation $icon
    Write-Host "Ярлык в меню Пуск: $startLnk"
}

$launcher = Join-Path $InstallDir "deploy\DotAudio.cmd"
$launcherDir = Split-Path -Parent $launcher
if (-not (Test-Path $launcherDir)) {
    New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
}
@"
@echo off
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" -m dotaudio
"@ | Set-Content -Path $launcher -Encoding ASCII

Write-Host ""
Write-Host "Готово. Данные пользователя: %LOCALAPPDATA%\DotCore\DotAudio"
Write-Host "Запуск: ярлык DotAudio или $launcher"
Write-Host "Обновление из UI: Настройки - Обновления, либо deploy\update.ps1"

if ($Launch) {
    Start-Process -FilePath $target -ArgumentList $launchArgs -WorkingDirectory $InstallDir
}
