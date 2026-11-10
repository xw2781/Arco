@echo off
setlocal

cd /d "%~dp0"

echo Step 1+2: Build beta\ARCRHO_BETA.xlam, then release it to E:\Arco Server\Excel Add-ins\Arco.xlam.
echo This updates the beta add-in, archives the existing release add-in, and overwrites it from beta.
echo.
choice /C YN /N /M "Continue with build and release? [Y/N] "
if errorlevel 2 (
    echo Build and release cancelled.
    echo.
    pause
    exit /b 1
)

echo.
echo Step 1: Building beta\ARCRHO_BETA.xlam from src_vba...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_xlam.ps1"
if errorlevel 1 (
    echo.
    echo Step 1 failed. Release was not run.
    echo.
    pause
    exit /b 1
)

echo.
echo Step 1 completed successfully.
echo.
echo Step 2: Releasing beta\ARCRHO_BETA.xlam to E:\Arco Server\Excel Add-ins\Arco.xlam...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0release_xlam.ps1"
if errorlevel 1 (
    echo.
    echo Step 2 failed. See the messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo Step 1+2 completed successfully.
echo.
pause
