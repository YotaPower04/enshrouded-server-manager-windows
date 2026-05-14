@echo off
setlocal enabledelayedexpansion

echo.
echo  Enshrouded Dedicated Server Manager ^| Windows Installer
echo  --------------------------------------------------------
echo.

:: Check for Python 3.8+
set PYTHON=
for %%P in (python python3) do (
    if not defined PYTHON (
        where %%P >nul 2>&1 && (
            for /f "tokens=2 delims= " %%V in ('%%P --version 2^>^&1') do (
                for /f "tokens=1,2 delims=." %%A in ("%%V") do (
                    if %%A geq 3 if %%B geq 8 set PYTHON=%%P
                )
            )
        )
    )
)

if not defined PYTHON (
    echo  [ERR] Python 3.8 or newer was not found on this system.
    echo.
    echo  Please download and install Python from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add python.exe to PATH" during installation,
    echo  then re-run this installer.
    echo.
    set /p OPEN=Open the Python download page now? [Y/n]:
    if /i not "!OPEN!"=="n" start https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Run the Python installer in the same directory as this batch file
%PYTHON% "%~dp0install.py"

endlocal
