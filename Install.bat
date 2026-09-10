@echo off
chcp 65001 >nul
title DotAudio - установка
cd /d "%~dp0"

echo.
echo   DotAudio - установка
echo   Окно можно не закрывать: будет виден прогресс.
echo.

REM Process-only Bypass: не меняет политику системы, достаточно для двойного клика.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\install.ps1" -Launch
set ERR=%ERRORLEVEL%

if not "%ERR%"=="0" (
  echo.
  echo   Установка завершилась с ошибкой. Код: %ERR%
  echo.
  pause
  exit /b %ERR%
)

exit /b 0
