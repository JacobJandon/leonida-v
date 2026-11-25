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

rem A self-update (leonida self-update / the Update button) unpacked the new version into leonida-v.new:
rem switch to it now, while Leonida is not running. State\ and Downloads\ are not touched.
if not exist "%BASE%\leonida-v.new\.leonida-update-ready" goto :noupdate
rem This kit's Leonida window holds State\leonida-gui.lock (its first line is the process id): while that
rem process runs, wait. A lock left behind by a crash names a process that is gone: no reason to wait.
set "LPID="
if exist "%LEONIDA_STATE_DIR%\leonida-gui.lock" set /p LPID=<"%LEONIDA_STATE_DIR%\leonida-gui.lock"
if defined LPID "%SystemRoot%\System32\tasklist.exe" /FI "PID eq %LPID%" /NH 2>nul | "%SystemRoot%\System32\find.exe" " %LPID% " >nul && goto :busy
echo Applying the Leonida V update...
if exist "%BASE%\leonida-v.old" rmdir /s /q "%BASE%\leonida-v.old"
if exist "%BASE%\leonida-v.old" goto :swapfail
if exist "%BASE%\leonida-v" ren "%BASE%\leonida-v" leonida-v.old || goto :swapfail
ren "%BASE%\leonida-v.new" leonida-v || goto :swapback
del "%BASE%\leonida-v\.leonida-update-ready" >nul 2>&1
if exist "%BASE%\.venv\.leonida-installed" del "%BASE%\.venv\.leonida-installed"
echo Updated. The previous version is kept in leonida-v.old
goto :noupdate
:swapback
if exist "%BASE%\leonida-v.old" ren "%BASE%\leonida-v.old" leonida-v
:swapfail
echo Could not switch to the update (a file in leonida-v is in use?) - starting the current version.
goto :noupdate
:busy
echo Leonida V is still running - close it to apply the downloaded update.
:noupdate
rem Tests and the release dry run (build/e2e_update.py) stop here, right after applying an update.
if defined LEONIDA_SWAP_ONLY exit /b 0

if exist "%BASE%\pyproject.toml" (set "PROJ=%BASE%") else (set "PROJ=%BASE%\leonida-v")
if exist "%PROJ%\pyproject.toml" goto :python
echo Unpacking Leonida V...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$z = Get-ChildItem -LiteralPath '%BASE%' -Filter 'leonida-v-*.zip' | Sort-Object LastWriteTime | Select-Object -Last 1; if (-not $z) { exit 2 }; Expand-Archive -LiteralPath $z.FullName -DestinationPath '%BASE%' -Force"
if errorlevel 1 goto :nozip

:python
rem Needs 64-bit Python 3.10+: PySide6 (the GUI) has no 32-bit Windows wheels.
set "OKPY=import sys, struct; sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize('P') == 8 else 1)"
set "PY="
py -3-64 -c "%OKPY%" >nul 2>&1 && set "PY=py -3-64"
if not defined PY py -3 -c "%OKPY%" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "%OKPY%" >nul 2>&1 && set "PY=python"
if not defined PY goto :nopython

set "VENV=%BASE%\.venv"
if not exist "%VENV%\Scripts\python.exe" goto :mkvenv
"%VENV%\Scripts\python.exe" -c "%OKPY%" >nul 2>&1 && goto :deps
echo The Python environment in %VENV% is 32-bit or too old - rebuilding it...
rmdir /s /q "%VENV%" || goto :fail

:mkvenv
echo Creating the Python environment...
%PY% -m venv "%VENV%" || goto :fail

:deps
if exist "%VENV%\.leonida-installed" goto :run
echo Installing Leonida V and the GUI library - first run only, takes a few minutes...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install -e "%PROJ%[gui]" || goto :fail
echo ok> "%VENV%\.leonida-installed"

:run
rem First run: a "Leonida V" shortcut in the Start menu and on the desktop, pointing at this file, minimized (so its
rem console stays out of the way) with the logo as icon. Once only: the marker remembers it, so deleted shortcuts
rem stay deleted. LEONIDA_NO_SHORTCUTS=1 skips it.
if not exist "%LEONIDA_STATE_DIR%\.shortcuts-created" "%VENV%\Scripts\python.exe" -m leonida.shortcuts --target "%~f0" --workdir "%BASE%" --icon "%PROJ%\leonida\gui\assets\leonida.ico" --minimized --marker "%LEONIDA_STATE_DIR%\.shortcuts-created" >nul 2>&1
if /i "%~1"=="cli" goto :cli
rem leonida.detach starts the GUI without this console's handles: a caller that captures this script's output
rem isn't kept waiting until the GUI is closed. A second start only brings the open Leonida window to the front.
"%VENV%\Scripts\python.exe" -m leonida.detach "%VENV%\Scripts\leonida-gui.exe" || start "" "%VENV%\Scripts\leonida-gui.exe"
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
echo 64-bit Python 3.10 or newer is required (a 32-bit Python cannot run the GUI).
echo Install "Windows installer (64-bit)" from python.org and tick "Add python.exe to PATH".
start "" https://www.python.org/downloads/
pause
exit /b 1

:fail
echo Setup failed - see the messages above.
pause
exit /b 1
