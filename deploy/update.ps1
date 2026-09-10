# Sync DotAudio checkout to origin/main and reinstall the editable package.
# Safe for user data: only touches the git tree and .venv.

[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [switch]$AllowDirty,
    [switch]$Relaunch,
    [int]$WaitPid = 0
)

$ErrorActionPreference = "Stop"

if ($WaitPid -gt 0) {
    try {
        $proc = Get-Process -Id $WaitPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Ждём завершения процесса $WaitPid…"
            Wait-Process -Id $WaitPid -Timeout 120 -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
    } catch {}
}

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
Set-Location $RepoRoot

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    throw "Не git-репозиторий: $RepoRoot"
}

$porcelain = git status --porcelain
if ($porcelain -and -not $AllowDirty) {
    throw "Есть локальные правки. Передайте -AllowDirty, чтобы сбросить их (reset --hard)."
}

Write-Host "fetch $Remote $Branch"
git fetch $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    git fetch $Remote
    if ($LASTEXITCODE -ne 0) { throw "git fetch не удался" }
}

$tip = "$Remote/$Branch"
Write-Host "checkout/reset $tip"
git checkout -f -B $Branch $tip
git reset --hard $tip
if ($LASTEXITCODE -ne 0) { throw "git reset не удался" }

$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python).Source
}
Write-Host "pip install -e ."
& $python -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Warning "pip install завершился с ошибкой. Код уже на $tip; перезапустите и повторите при необходимости."
}

Write-Host "Готово: $(git rev-parse --short HEAD)"

if ($Relaunch) {
    $pythonw = Join-Path $RepoRoot ".venv\Scripts\pythonw.exe"
    $target = if (Test-Path $pythonw) { $pythonw } else { $python }
    Start-Process -FilePath $target -ArgumentList "-m dotaudio" -WorkingDirectory $RepoRoot
}
