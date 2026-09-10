@echo off
chcp 65001 >nul
title DotAudio - install
cd /d "%~dp0"

echo.
echo   DotAudio - install
echo   Keep this window open to see progress.
echo.

REM Process-only Bypass: does not change machine policy; enough for double-click.
REM install.ps1 must be UTF-8 with BOM so Windows PowerShell 5.1 parses Cyrillic.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\install.ps1" -Launch
set ERR=%ERRORLEVEL%

if not "%ERR%"=="0" (
  echo.
  echo   Install failed. Exit code: %ERR%
  echo.
  pause
  exit /b %ERR%
)

exit /b 0
