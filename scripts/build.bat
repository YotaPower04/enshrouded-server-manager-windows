@echo off
setlocal
title Build -- Enshrouded Server Manager Installer

:: Run from repo root so all relative paths line up
cd /d "%~dp0\.."

if not exist assets\install.ico (
    echo [INFO] assets\install.ico missing -- generating icons...
    python src\make_icons.py
    if errorlevel 1 (
        echo [ERR] make_icons.py failed -- is Pillow installed? "pip install pillow"
        pause
        exit /b 1
    )
)

echo.
echo Installing/upgrading PyInstaller...
pip install --quiet --upgrade pyinstaller
if errorlevel 1 (
    echo [ERR] pip failed. Make sure Python is on PATH.
    pause
    exit /b 1
)

echo Building "Install ESM.exe"...
pyinstaller --noconfirm --onefile --windowed --icon=assets\install.ico ^
    --add-data "src\enshrouded_manager.py;." ^
    --add-data "assets\manager.ico;." ^
    --add-data "assets\running.ico;." ^
    --name "Install ESM" src\install_tk.py

if exist "dist\Install ESM.exe" (
    echo.
    echo [OK] Built successfully.
    copy /y "dist\Install ESM.exe" "Install ESM.exe" >nul
    echo [OK] Copied to "Install ESM.exe" -- ready to distribute.
) else (
    echo.
    echo [ERR] Build failed -- check PyInstaller output above.
)
echo.
pause
