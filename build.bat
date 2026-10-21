@echo off
rem Build Peek & Grep Portable. Nothing to install: the repository holds the Python runtime
rem (vendor\runtime) and the built UI (frontend\dist). The launcher is compiled with the C#
rem compiler that is part of Windows. Output: release\PeekGrep.exe
setlocal
cd /d "%~dp0"

if not exist "vendor\runtime\python.exe" (
    echo vendor\runtime\python.exe is missing. Clone or download the complete repository again.
    pause
    exit /b 1
)

"vendor\runtime\python.exe" "portable\build_portable.py" %*
if errorlevel 1 (
    echo.
    echo BUILD FAILED. See the messages above.
    pause
    exit /b 1
)

echo.
echo Done: %~dp0release\PeekGrep.exe
pause
