# DotAudio installer for Windows.
# Prefer launching via Install.bat (double-click) so progress stays visible.
# Requires: Git and Python 3.12 or 3.13.

[CmdletBinding()]
param(
    [string]$RepoUrl = "https://github.com/network-user/DotAudio.git",
    [string]$InstallDir = "",
    [string]$Branch = "main",
    [switch]$SkipShortcut,
    [switch]$Launch,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "DotAudio - установка"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$script:Step = 0
$script:StepTotal = 6

function Write-Step([string]$Title, [int]$Percent) {
    $script:Step++
    Write-Host ""
    Write-Host ("=== Шаг {0}/{1}: {2}" -f $script:Step, $script:StepTotal, $Title) -ForegroundColor Cyan
    Write-Progress -Activity "Установка DotAudio" -Status $Title -PercentComplete $Percent
}

function Write-Ok([string]$Text) {
    Write-Host ("  OK  " + $Text) -ForegroundColor Green
}

function Write-Info([string]$Text) {
    Write-Host ("  ..  " + $Text) -ForegroundColor Gray
}

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw ("Не найдена команда '{0}'. {1}" -f $Name, $Hint)
    }
}

function Resolve-Python {
    foreach ($name in @("py", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($name -eq "py") {
            foreach ($ver in @("3.12", "3.13")) {
                try {
                    $out = & py "-$ver" -c "import sys; print(sys.executable)" 2>$null
                    if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -First 1).ToString().Trim() }
                } catch {}
            }
        } else {
            $exe = $cmd.Source
            $check = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2]); print(sys.executable)"
            if ($LASTEXITCODE -ne 0) { continue }
            $lines = @($check)
            if ($lines.Count -ge 2 -and $lines[0] -match '^3\.(12|13)$') {
                return $lines[1].Trim()
            }
        }
    }
    throw "Нужен Python 3.12 или 3.13. Скачайте с https://www.python.org/downloads/ и отметьте Add python.exe to PATH."
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

function Resolve-InstallDir {
    param(
        [string]$Requested,
        [string]$ScriptRoot
    )
    if ($Requested) { return $Requested }

    if ($ScriptRoot) {
        $fromScript = Split-Path -Parent $ScriptRoot
        if (Test-Path (Join-Path $fromScript "src\dotaudio")) {
            return $fromScript
        }
    }

    $here = (Get-Location).Path
    if (Test-Path (Join-Path $here "src\dotaudio")) {
        return $here
    }
    if (Test-Path (Join-Path $here ".git")) {
        return $here
    }
    return (Join-Path $env:LOCALAPPDATA "Programs\DotAudio")
}

Write-Host ""
Write-Host "  DotAudio - установка" -ForegroundColor White
Write-Host "  Репозиторий: $RepoUrl" -ForegroundColor DarkGray
Write-Host ""

try {
    Write-Step "Проверка Git и Python" 5
    Assert-Command git "Установите Git for Windows: https://git-scm.com/download/win"
    $python = Resolve-Python
    Write-Ok "Git найден"
    Write-Ok "Python: $python"

    $InstallDir = Resolve-InstallDir -Requested $InstallDir -ScriptRoot $PSScriptRoot
    Write-Info "Каталог установки: $InstallDir"

    Write-Step "Загрузка кода с GitHub" 20
    $gitDir = Join-Path $InstallDir ".git"
    if (-not (Test-Path $gitDir)) {
        $parent = Split-Path -Parent $InstallDir
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        if ((Test-Path $InstallDir) -and (Get-ChildItem $InstallDir -Force | Where-Object { $_.Name -ne '.' -and $_.Name -ne '..' })) {
            if (-not (Test-Path (Join-Path $InstallDir "src\dotaudio"))) {
                throw "Каталог уже занят и это не DotAudio: $InstallDir"
            }
            Write-Info "Код уже на диске (без .git) - ставим из этой папки"
        } else {
            Write-Info "Клонируем $Branch (это может занять минуту)..."
            & git clone --progress --branch $Branch --single-branch $RepoUrl $InstallDir
            if ($LASTEXITCODE -ne 0) { throw "git clone не удался" }
            Write-Ok "Репозиторий скачан"
        }
    } else {
        Write-Info "Обновляем существующий клон..."
        Push-Location $InstallDir
        try {
            & git fetch --progress origin $Branch
            if ($LASTEXITCODE -ne 0) {
                & git fetch --progress origin
                if ($LASTEXITCODE -ne 0) { throw "git fetch не удался" }
            }
            & git checkout -f -B $Branch "origin/$Branch"
            & git reset --hard "origin/$Branch"
            if ($LASTEXITCODE -ne 0) { throw "git reset не удался" }
            Write-Ok ("Код на " + (& git rev-parse --short HEAD))
        } finally {
            Pop-Location
        }
    }

    Write-Step "Создание виртуального окружения" 40
    $venvPython = Join-Path $InstallDir ".venv\Scripts\python.exe"
    $venvPythonw = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Info "python -m venv .venv"
        & $python -m venv (Join-Path $InstallDir ".venv")
        if ($LASTEXITCODE -ne 0) { throw "venv не создался" }
        Write-Ok ".venv создан"
    } else {
        Write-Ok ".venv уже есть"
    }

    Write-Step "Установка зависимостей (pip)" 55
    Write-Info "Обновляем pip..."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "не удалось обновить pip" }
    Write-Info "Ставим DotAudio и библиотеки (PySide6, faster-whisper...). Это самый долгий шаг."
    Write-Progress -Activity "Установка DotAudio" -Status "pip install -e ." -PercentComplete 65
    & $venvPython -m pip install -e "$InstallDir"
    if ($LASTEXITCODE -ne 0) { throw "pip install -e . не удался" }
    Write-Ok "Пакет установлен"

    Write-Step "Ярлыки на рабочем столе и в меню Пуск" 85
    $icon = Join-Path $InstallDir "src\dotaudio\assets\app_icon.ico"
    $target = if (Test-Path $venvPythonw) { $venvPythonw } else { $venvPython }
    $launchArgs = "-m dotaudio"

    if (-not $SkipShortcut) {
        $desktop = [Environment]::GetFolderPath("Desktop")
        $desktopLnk = Join-Path $desktop "DotAudio.lnk"
        New-Shortcut -Path $desktopLnk -Target $target -Arguments $launchArgs `
            -WorkingDirectory $InstallDir -IconLocation $icon
        Write-Ok "Рабочий стол: $desktopLnk"

        $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\DotAudio"
        $startLnk = Join-Path $startMenu "DotAudio.lnk"
        New-Shortcut -Path $startLnk -Target $target -Arguments $launchArgs `
            -WorkingDirectory $InstallDir -IconLocation $icon
        Write-Ok "Меню Пуск: $startLnk"
    } else {
        Write-Info "Ярлыки пропущены (-SkipShortcut)"
    }

    $launcher = Join-Path $InstallDir "deploy\DotAudio.cmd"
    @"
@echo off
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" -m dotaudio
"@ | Set-Content -Path $launcher -Encoding ASCII

    Write-Step "Готово" 100
    Write-Progress -Activity "Установка DotAudio" -Completed
    Write-Host ""
    Write-Host "  Установка завершена." -ForegroundColor Green
    Write-Host "  Данные: %LOCALAPPDATA%\DotCore\DotAudio" -ForegroundColor DarkGray
    Write-Host "  Запуск: ярлык DotAudio на рабочем столе" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  При первом запуске откроется мастер настройки:" -ForegroundColor Yellow
    Write-Host "  он сам скачает модели и покажет прогресс в окне приложения." -ForegroundColor Yellow
    Write-Host ""

    if ($Launch) {
        Write-Info "Запускаем DotAudio..."
        Start-Process -FilePath $target -ArgumentList $launchArgs -WorkingDirectory $InstallDir
    }
}
catch {
    Write-Progress -Activity "Установка DotAudio" -Completed
    Write-Host ""
    Write-Host "  Ошибка установки:" -ForegroundColor Red
    Write-Host ("  " + $_.Exception.Message) -ForegroundColor Red
    Write-Host ""
    if (-not $NoPause) {
        Read-Host "Нажмите Enter, чтобы закрыть"
    }
    exit 1
}

if (-not $NoPause) {
    Read-Host "Нажмите Enter, чтобы закрыть"
}
exit 0
