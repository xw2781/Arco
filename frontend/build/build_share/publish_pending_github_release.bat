@echo off
setlocal EnableExtensions

REM Publishes an already-built installer to GitHub Releases without rebuilding it.
REM
REM Use this to seed the GitHub Releases history after a build produced an
REM installer but failed at its publish step. From that point on the normal
REM build derives its next version number from this history, so a version that
REM shipped but was never published to GitHub would otherwise be rebuilt.
REM
REM Usage:
REM   publish_pending_github_release.bat [version] [product]
REM   publish_pending_github_release.bat --check
REM
REM Defaults to Arco 1.2.5. Safe to re-run: an existing release is updated in
REM place rather than duplicated.

set "BUILD_SHARE_ROOT=%~dp0"
set "BUILD_SHARE_ROOT=%BUILD_SHARE_ROOT:~0,-1%"
set "PUBLISH_SCRIPT=E:\XWSpace\Repos\ArcRho\frontend\build\release\publish_github_release.ps1"

REM --check reports the resolved paths and publishes nothing. Accept it in any
REM position so a check never turns into a real publish.
set "CHECK_ONLY="
for %%A in (%*) do if /i "%%~A"=="--check" set "CHECK_ONLY=1"

set "APP_VERSION=%~1"
set "PRODUCT_NAME=%~2"
if /i "%APP_VERSION%"=="--check" set "APP_VERSION="
if /i "%PRODUCT_NAME%"=="--check" set "PRODUCT_NAME="
if not defined APP_VERSION set "APP_VERSION=1.2.5"
if not defined PRODUCT_NAME set "PRODUCT_NAME=Arco"

if /i "%PRODUCT_NAME%"=="Arco" (
    set "DEFAULT_LOCAL_ROOT=%USERPROFILE%\Documents\build_arcrho_app"
    set "FEED_DIR=E:\Arco Server\releases\installers"
) else if /i "%PRODUCT_NAME%"=="Arcode" (
    set "DEFAULT_LOCAL_ROOT=%USERPROFILE%\Documents\build_arcode_app"
    set "FEED_DIR=E:\Arcode Server\releases\arcode-installers"
) else (
    echo ERROR: Unsupported product: %PRODUCT_NAME%
    echo Expected Arco or Arcode.
    echo.
    pause
    exit /b 1
)

set "LOCAL_ROOT=%DEFAULT_LOCAL_ROOT%"
if defined ARCRHO_LOCAL_BUILD_ROOT set "LOCAL_ROOT=%ARCRHO_LOCAL_BUILD_ROOT%"
set "LOCAL_FRONTEND=%LOCAL_ROOT%\frontend"
set "INSTALLER_NAME=%PRODUCT_NAME%-Setup-%APP_VERSION%.exe"

REM Prefer the locally built installer. Reading it from the network feed works
REM but hashes and uploads roughly 360 MB across the network drive.
set "INSTALLER_PATH="
set "INSTALLER_SOURCE="
if exist "%LOCAL_FRONTEND%\dist\%INSTALLER_NAME%" (
    set "INSTALLER_PATH=%LOCAL_FRONTEND%\dist\%INSTALLER_NAME%"
    set "INSTALLER_SOURCE=local build workspace"
) else if exist "%FEED_DIR%\%INSTALLER_NAME%" (
    set "INSTALLER_PATH=%FEED_DIR%\%INSTALLER_NAME%"
    set "INSTALLER_SOURCE=network feed - slower, read across the mapped E: drive"
)

REM Release notes are generated into the build workspace and are not committed
REM back to the repository. Without them the release body falls back to the
REM product and version.
set "NOTES_PATH="
if exist "%LOCAL_FRONTEND%\docs\releases\%APP_VERSION%.md" set "NOTES_PATH=%LOCAL_FRONTEND%\docs\releases\%APP_VERSION%.md"

if defined CHECK_ONLY (
    echo Build share:      %BUILD_SHARE_ROOT%
    echo Product:          %PRODUCT_NAME%
    echo Version:          %APP_VERSION%
    echo Publish script:   %PUBLISH_SCRIPT%
    echo Local workspace:  %LOCAL_FRONTEND%
    echo Network feed:     %FEED_DIR%
    echo Installer:        %INSTALLER_PATH%
    echo Installer source: %INSTALLER_SOURCE%
    echo Release notes:    %NOTES_PATH%
    exit /b 0
)

echo ========================================
echo Publishing %PRODUCT_NAME% %APP_VERSION% to GitHub Releases
echo ========================================
echo.

if not exist "%PUBLISH_SCRIPT%" (
    echo ERROR: Publish script not found:
    echo %PUBLISH_SCRIPT%
    echo Confirm this PC can reach the source PC through its mapped E: drive.
    echo.
    pause
    exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI was not found on PATH.
    echo Install GitHub CLI on this build PC, then run: gh auth login
    echo.
    pause
    exit /b 1
)

gh auth status >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI is not authenticated for this Windows user.
    echo Run 'gh auth login' in a normal, non-elevated window signed in as the
    echo same user that runs the build, then run this script again.
    echo.
    pause
    exit /b 1
)

if not defined INSTALLER_PATH (
    echo ERROR: %INSTALLER_NAME% was not found in either location:
    echo   %LOCAL_FRONTEND%\dist
    echo   %FEED_DIR%
    echo Pass a different version as the first argument, or rebuild that version.
    echo.
    pause
    exit /b 1
)

echo Installer:      %INSTALLER_PATH%
echo Read from:      %INSTALLER_SOURCE%
if defined NOTES_PATH (
    echo Release notes:  %NOTES_PATH%
) else (
    echo Release notes:  none found - the release body will be "%PRODUCT_NAME% %APP_VERSION%"
)
echo.
echo Uploading the installer can take several minutes on a slow uplink.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PUBLISH_SCRIPT%" -InstallerPath "%INSTALLER_PATH%" -ReleaseNotesPath "%NOTES_PATH%" -ProductName "%PRODUCT_NAME%"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to publish the GitHub Release.
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Published %PRODUCT_NAME% %APP_VERSION%
echo ========================================
echo.
echo The next build will derive its version from this release history.
echo.
pause
exit /b 0
