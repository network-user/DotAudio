@echo off
chcp 65001 >nul
title DotAudio - скачать и установить
cd /d "%~dp0"

echo.
echo   DotAudio - загрузка с GitHub и установка
echo.

set "TARGET=%LOCALAPPDATA%\Programs\DotAudio"

where git >nul 2>&1
if errorlevel 1 (
  echo   Нужен Git for Windows: https://git-scm.com/download/win
  pause
  exit /b 1
)

if exist "%TARGET%\.git" (
  echo   Найдена установка: %TARGET%
) else if exist "%~dp0src\dotaudio" (
  echo   Запуск установщика из этой папки...
  call "%~dp0Install.bat"
  exit /b %ERRORLEVEL%
) else (
  echo   Клонируем в %TARGET% ...
  if exist "%TARGET%" (
    echo   Каталог уже есть и это не git-клон. Удалите его или укажите другой путь.
    pause
    exit /b 1
  )
  git clone --progress --branch main --single-branch https://github.com/network-user/DotAudio.git "%TARGET%"
  if errorlevel 1 (
    echo   git clone не удался
    pause
    exit /b 1
  )
)

call "%TARGET%\Install.bat"
exit /b %ERRORLEVEL%
