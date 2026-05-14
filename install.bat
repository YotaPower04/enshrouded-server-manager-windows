@echo off
setlocal enabledelayedexpansion

title Enshrouded Server Manager — Windows Installer

echo.
echo  ============================================================
echo   Enshrouded Dedicated Server Manager ^| Windows Installer
echo  ============================================================
echo.

:: ── Find Python ───────────────────────────────────────────────────────────
call :find_python
if defined PYTHON (
    echo  [OK] Found Python: !PYTHON!
    echo.
    goto :run_installer
)

:: ── Python not found — download and install it automatically ──────────────
echo  Python was not found. Downloading Python 3.12 automatically...
echo.

set "PY_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
set "PY_INST=%TEMP%\python-3.12.10-amd64.exe"

powershell -NoProfile -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "Write-Host '  Downloading Python 3.12...' -NoNewline;" ^
    "(New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INST%');" ^
    "Write-Host ' done.'"

if not exist "%PY_INST%" (
    echo.
    echo  [ERR] Download failed. Check your internet connection, then try again.
    echo        Or install Python manually from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  Installing Python 3.12 (no admin rights needed)...
"%PY_INST%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del /f /q "%PY_INST%" 2>nul
echo  [OK] Python 3.12 installed.
echo.

:: Look in the standard per-user install location (InstallAllUsers=0)
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
) do (
    if not defined PYTHON if exist %%~P set "PYTHON=%%~P"
)

if not defined PYTHON (
    echo  [ERR] Python was installed but could not be located automatically.
    echo        Please open a new Command Prompt and run:  python install.py
    pause
    exit /b 1
)

:: ── Run the Python installer ───────────────────────────────────────────────
:run_installer
"!PYTHON!" "%~dp0install.py"
goto :eof

:: ── Helper: find any Python in current PATH ────────────────────────────────
:find_python
set PYTHON=
for %%C in (python py python3) do (
    if not defined PYTHON (
        where %%C >nul 2>&1 && set "PYTHON=%%C"
    )
)
goto :eof
