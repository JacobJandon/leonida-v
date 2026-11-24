@echo off
setlocal EnableExtensions
title Leonida V
rem Portable launcher: everything (project, mod downloads, logs, backups) stays next to this file.
set "BASE=%~dp0"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
set "LEONIDA_DOWNLOAD_DIR=%BASE%\Downloads"
set "LEONIDA_STATE_DIR=%BASE%\State"
if not exist "%BASE%\Downloads" mkdir "%BASE%\Downloads"
if not exist "%BASE%\State" mkdir "%BASE%\State"

if exist "%BASE%\pyproject.toml" (set "PROJ=%BASE%") else (set "PROJ=%BASE%\leonida-v")
if exist "%PROJ%\pyproject.toml" goto :python
echo Unpacking Leonida V...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$z = Get-ChildItem -LiteralPath '%BASE%' -Filter 'leonida-v-*.zip' | Sort-Object LastWriteTime | Select-Object -Last 1; if (-not $z) { exit 2 }; Expand-Archive -LiteralPath $z.FullName -DestinationPath '%BASE%' -Force"
if errorlevel 1 goto :nozip

:python
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || goto :nopython

set "VENV=%BASE%\.venv"
if exist "%VENV%\Scripts\python.exe" goto :deps
echo Creating the Python environment...
%PY% -m venv "%VENV%" || goto :fail

:deps
if exist "%VENV%\.leonida-installed" goto :run
echo Installing Leonida V and the GUI library - first run only, takes a few minutes...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install -e "%PROJ%[gui]" || goto :fail
echo ok> "%VENV%\.leonida-installed"

:run
if /i "%~1"=="cli" goto :cli
start "" "%VENV%\Scripts\leonida-gui.exe"
exit /b 0

:cli
echo Leonida V command line. Try:  leonida doctor   leonida detect   leonida get --watch   leonida --help
cmd /k ""%VENV%\Scripts\activate.bat""
exit /b 0

:nozip
echo Could not find leonida-v-*.zip next to this file in %BASE%
pause
exit /b 1

:nopython
echo Python 3.10 or newer is required. Install it from python.org and tick "Add python.exe to PATH".
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo Setup failed - see the messages above.
pause
exit /b 1
