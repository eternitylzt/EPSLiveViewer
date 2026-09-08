@echo off
setlocal EnableExtensions

REM Build EPS Live Viewer as a single Windows executable.
REM Run this file from Explorer or a Command Prompt on Windows 11.
cd /d "%~dp0"

REM Prefer the Python Launcher, but also support installations that only put
REM python.exe on PATH.
set "PYTHON_LAUNCHER="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_LAUNCHER=py -3"
)
if not defined PYTHON_LAUNCHER (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
        if not errorlevel 1 set "PYTHON_LAUNCHER=python"
    )
)
if not defined PYTHON_LAUNCHER (
    echo [ERROR] Python 3.11 or newer was not found.
    echo Install it from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating Python virtual environment...
    %PYTHON_LAUNCHER% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Python 3.11+ virtual environment could not be created.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] The existing .venv does not use Python 3.11 or newer.
    echo Rename or remove .venv, then run build.bat again.
    pause
    exit /b 1
)

echo [2/4] Installing build dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Packaging EPSLiveViewer.exe...
REM Avoid pulling unrelated DLLs from MATLAB, LaTeX, image tools, etc. into
REM the executable. PyInstaller finds Qt's own binaries via its PyQt6 hooks.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%CD%\.venv\Scripts"
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist EPSLiveViewer.spec del /q EPSLiveViewer.spec

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name EPSLiveViewer ^
    --icon "resources\icon.ico" ^
    --add-data "resources;resources" ^
    --collect-all imageio_ffmpeg ^
    main.py
if errorlevel 1 goto :failed
if not exist "dist\EPSLiveViewer.exe" goto :failed

echo [4/4] Copying editable runtime configuration...
copy /y config.json "dist\config.json" >nul
if errorlevel 1 goto :failed

echo.
echo Build succeeded:
echo   %CD%\dist\EPSLiveViewer.exe
echo.
echo Ghostscript remains a runtime dependency. Install it separately on each PC.
pause
exit /b 0

:failed
echo.
echo [ERROR] Build failed. Review the messages above.
pause
exit /b 1
