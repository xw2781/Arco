@echo off
setlocal EnableExtensions

REM Builds or publishes an ArcRho or Arcode release from the repository on THIS PC.
REM
REM Use this when the repository, the build toolchain, and an authenticated gh CLI all
REM live on the same machine. It needs no second PC, no build share, no source ZIP, and
REM no listener. The one-step path runs in place against this repository's own frontend, so
REM its version bump, generated release notes, and archived changelog fragments land directly
REM in the working tree. Build-only mode restores version metadata and records a pending
REM installer outside the repository instead, so it can be tested before publication.
REM
REM The two-PC workflow in BUILD_FROM_ZIP_ON_SECOND_PC.md is unchanged and remains the
REM route to use when the PC holding the repository cannot run the full build toolchain.
REM
REM Usage:
REM   build_app_from_local_repo.bat [--check] [--build-only] [version] [--no-commit]
REM   build_app_from_local_repo.bat --publish version [--no-commit]
REM
REM   --check       Validate prerequisites and print resolved paths, build nothing.
REM   --build-only  Build an installer and record it for local testing. Do not publish.
REM   --publish     Publish a previously recorded local installer. Requires a version.
REM   version       Explicit semantic version. Omitted, the patch version is bumped from
REM                 the GitHub Releases history.
REM   --no-commit   Leave the release bookkeeping in the working tree, uncommitted.
REM
REM Optional environment overrides:
REM   set ARCRHO_BUILD_PRODUCT=arcode                    REM defaults to arco
REM   set ARCRHO_LOCAL_RELEASE_WORK_DIR=D:\ArcRho Build  REM build logs, outside the repo
REM   set PYTHON_API_PACKAGE_DIR=D:\packages             REM shared Python API wheel target

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "REPO_ROOT=%%~fI"

if not defined ARCRHO_BUILD_PRODUCT set "ARCRHO_BUILD_PRODUCT=arco"
set "PRODUCT_NAME="
if /i "%ARCRHO_BUILD_PRODUCT%"=="arco" set "PRODUCT_NAME=Arco"
if /i "%ARCRHO_BUILD_PRODUCT%"=="arcode" set "PRODUCT_NAME=Arcode"
if not defined PRODUCT_NAME (
    echo ERROR: Unsupported ARCRHO_BUILD_PRODUCT: %ARCRHO_BUILD_PRODUCT%
    echo Expected arco or arcode.
    exit /b 1
)

set "EXPLICIT_VERSION="
set "COMMIT_BOOKKEEPING=1"
set "CHECK_ONLY="
set "BUILD_ONLY="
set "PUBLISH_ONLY="
set "ARCRHO_RELEASE_BUILD_ONLY="
set "ARCRHO_RELEASE_VERSION_SNAPSHOT="

:parse_args
if "%~1"=="" goto parse_args_done
if /i "%~1"=="--check" goto parse_args_check
if /i "%~1"=="--no-commit" goto parse_args_no_commit
if /i "%~1"=="--build-only" goto parse_args_build_only
if /i "%~1"=="--publish" goto parse_args_publish
set "EXPLICIT_VERSION=%~1"
shift
goto parse_args

:parse_args_check
set "CHECK_ONLY=1"
shift
goto parse_args

:parse_args_no_commit
set "COMMIT_BOOKKEEPING="
shift
goto parse_args

:parse_args_build_only
set "BUILD_ONLY=1"
shift
goto parse_args

:parse_args_publish
set "PUBLISH_ONLY=1"
shift
goto parse_args

:parse_args_done

if defined BUILD_ONLY if defined PUBLISH_ONLY (
    echo ERROR: --build-only and --publish cannot be used together.
    exit /b 1
)
if defined PUBLISH_ONLY if not defined EXPLICIT_VERSION (
    echo ERROR: --publish requires the version of a pending local installer.
    exit /b 1
)

set "BUILD_WRAPPER=%SCRIPT_DIR%build_app_via_local_workspace.bat"
set "SYNC_SCRIPT=%SCRIPT_DIR%release\sync_published_release.py"
set "RELEASE_WORKFLOW_SCRIPT=%SCRIPT_DIR%release\release_workflow.py"

REM Only build logs and the version handover file live here; the build itself runs in
REM the repository. Kept outside the repository so a build never writes into it.
set "WORK_DIR=%USERPROFILE%\Documents\ArcRho Local Build"
if defined ARCRHO_LOCAL_RELEASE_WORK_DIR set "WORK_DIR=%ARCRHO_LOCAL_RELEASE_WORK_DIR%"
set "ARCRHO_LOCAL_RELEASE_WORK_DIR=%WORK_DIR%"
set "VERSION_OUT=%WORK_DIR%\last_built_%ARCRHO_BUILD_PRODUCT%_version.txt"
set "ARCRHO_BUILD_LOG_DIR=%WORK_DIR%\logs\%COMPUTERNAME%"

if not defined PYTHON_API_PACKAGE_DIR set "PYTHON_API_PACKAGE_DIR=E:\Arco Server\packages"

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%I in (`py -3.10 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%I"
)
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo ========================================
echo %PRODUCT_NAME% local release build
echo ========================================
echo Repository:        %REPO_ROOT%
echo Builds in:         %REPO_ROOT%\frontend
echo Build logs:        %ARCRHO_BUILD_LOG_DIR%
echo Python:            %PYTHON_EXE%
if /i "%ARCRHO_BUILD_PRODUCT%"=="arco" echo Python API target: %PYTHON_API_PACKAGE_DIR%
if defined EXPLICIT_VERSION echo Requested version: %EXPLICIT_VERSION%
if defined BUILD_ONLY echo Mode:              build installer for local testing only
if defined PUBLISH_ONLY echo Mode:              publish an existing pending installer
if not defined COMMIT_BOOKKEEPING echo Bookkeeping:       written but not committed
echo.

if defined PUBLISH_ONLY (
    call :check_publish_prerequisites
) else (
    call :check_prerequisites
)
if errorlevel 1 exit /b 1

if defined CHECK_ONLY (
    echo All prerequisites passed. Nothing was built or published.
    exit /b 0
)

if defined PUBLISH_ONLY call :publish_pending_release
if defined PUBLISH_ONLY exit /b %ERRORLEVEL%

echo ========================================
if defined BUILD_ONLY echo Step A: Building %PRODUCT_NAME% for local testing
if not defined BUILD_ONLY echo Step A: Building and publishing %PRODUCT_NAME%
echo ========================================
if exist "%VERSION_OUT%" del /q "%VERSION_OUT%" >nul 2>nul
REM The build runs against this repository rather than a copied workspace.
set "ARCRHO_BUILD_IN_PLACE=1"
set "ARCRHO_LOCAL_BUILD_ROOT=%REPO_ROOT%"
set "ARCRHO_BUILD_VERSION_OUT=%VERSION_OUT%"
if defined BUILD_ONLY call :prepare_build_only
if defined BUILD_ONLY if errorlevel 1 exit /b 1
call "%BUILD_WRAPPER%" %EXPLICIT_VERSION%
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if defined BUILD_ONLY call :restore_build_only_metadata
if defined BUILD_ONLY if errorlevel 1 exit /b 1
if not "%BUILD_EXIT_CODE%"=="0" (
    echo.
    echo ERROR: The %PRODUCT_NAME% build failed with exit code %BUILD_EXIT_CODE%.
    echo Build log directory: %ARCRHO_BUILD_LOG_DIR%
    echo.
    echo The working tree may hold a partial version bump. Inspect it with:
    echo   git -C "%REPO_ROOT%" status --short
    exit /b %BUILD_EXIT_CODE%
)

set "BUILT_VERSION="
if exist "%VERSION_OUT%" set /p BUILT_VERSION=<"%VERSION_OUT%"
if not defined BUILT_VERSION (
    echo.
    echo WARNING: The build succeeded but did not report its version.
    echo The installer is published and the bookkeeping is already in the working tree.
    echo Review it with: git -C "%REPO_ROOT%" status --short
    exit /b 0
)

if defined BUILD_ONLY (
    echo.
    echo ========================================
    echo %PRODUCT_NAME% %BUILT_VERSION% built for local testing
    echo ========================================
    echo Installer:      %REPO_ROOT%\frontend\dist\%PRODUCT_NAME%-Setup-%BUILT_VERSION%.exe
    echo Pending record: %WORK_DIR%\pending_releases\%PRODUCT_NAME%-v%BUILT_VERSION%.json
    echo Publish later:  frontend\build\build_app_from_local_repo.bat --publish %BUILT_VERSION%
    exit /b 0
)

echo.
echo ========================================
echo Step B: Recording %PRODUCT_NAME% %BUILT_VERSION% in this repository
echo ========================================
REM The in-place build already wrote the version metadata, the release notes, and the
REM fragment archive. This only refreshes the documentation index and commits them.
call :commit_bookkeeping
if errorlevel 1 (
    echo.
    echo WARNING: The release bookkeeping was not committed.
    echo The installer is already published; only the commit is missing.
    echo Review and commit it by hand from %REPO_ROOT%.
    exit /b 0
)

echo.
echo ========================================
echo %PRODUCT_NAME% %BUILT_VERSION% released from this PC
echo ========================================
echo GitHub Release: %PRODUCT_NAME%-v%BUILT_VERSION%
echo Installer:      %REPO_ROOT%\frontend\dist\%PRODUCT_NAME%-Setup-%BUILT_VERSION%.exe
echo Build logs:     %ARCRHO_BUILD_LOG_DIR%
if defined COMMIT_BOOKKEEPING echo The release bookkeeping was committed locally. Nothing was pushed.
if not defined COMMIT_BOOKKEEPING echo Review and commit the release bookkeeping when ready.
exit /b 0

:publish_pending_release
echo ========================================
echo Publishing pending %PRODUCT_NAME% %EXPLICIT_VERSION%
echo ========================================
set "PUBLISH_ARGS=publish --product %PRODUCT_NAME% --version %EXPLICIT_VERSION%"
if not defined COMMIT_BOOKKEEPING set "PUBLISH_ARGS=%PUBLISH_ARGS% --no-commit"
"%PYTHON_EXE%" "%RELEASE_WORKFLOW_SCRIPT%" %PUBLISH_ARGS%
exit /b %ERRORLEVEL%

:prepare_build_only
set "ARCRHO_RELEASE_BUILD_ONLY=1"
set "ARCRHO_RELEASE_VERSION_SNAPSHOT=%WORK_DIR%\pending_releases\version_metadata_%RANDOM%_%RANDOM%.json"
"%PYTHON_EXE%" "%RELEASE_WORKFLOW_SCRIPT%" snapshot-version --snapshot-path "%ARCRHO_RELEASE_VERSION_SNAPSHOT%"
if errorlevel 1 (
    echo ERROR: Could not preserve the current version metadata before the build.
    exit /b 1
)
exit /b 0

:restore_build_only_metadata
"%PYTHON_EXE%" "%RELEASE_WORKFLOW_SCRIPT%" restore-version --snapshot-path "%ARCRHO_RELEASE_VERSION_SNAPSHOT%" --delete
if not errorlevel 1 exit /b 0
echo.
echo ERROR: The build-only run could not restore the original version metadata.
echo Snapshot retained at: %ARCRHO_RELEASE_VERSION_SNAPSHOT%
exit /b 1

:commit_bookkeeping
set "SYNC_ARGS=%BUILT_VERSION% --product %PRODUCT_NAME% --bookkeeping-only"
if defined COMMIT_BOOKKEEPING set "SYNC_ARGS=%SYNC_ARGS% --commit"
pushd "%REPO_ROOT%\frontend"
if errorlevel 1 (
    echo ERROR: Could not enter %REPO_ROOT%\frontend
    exit /b 1
)
"%PYTHON_EXE%" build\release\sync_published_release.py %SYNC_ARGS%
set "SYNC_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %SYNC_EXIT_CODE%

:check_prerequisites
if not exist "%REPO_ROOT%\frontend\package.json" (
    echo ERROR: This does not look like the ArcRho repository: %REPO_ROOT%
    exit /b 1
)
if not exist "%BUILD_WRAPPER%" (
    echo ERROR: Missing build wrapper: %BUILD_WRAPPER%
    exit /b 1
)
if not exist "%SYNC_SCRIPT%" (
    echo ERROR: Missing release bookkeeping script: %SYNC_SCRIPT%
    exit /b 1
)
if not exist "%RELEASE_WORKFLOW_SCRIPT%" (
    echo ERROR: Missing local release workflow script: %RELEASE_WORKFLOW_SCRIPT%
    exit /b 1
)
if not exist "%REPO_ROOT%\frontend\node-portable\node.exe" (
    echo ERROR: Missing portable Node: %REPO_ROOT%\frontend\node-portable\node.exe
    echo HINT: node-portable is not in Git. Copy it from a machine that has it.
    exit /b 1
)
if not exist "%REPO_ROOT%\frontend\node_modules\electron-builder\cli.js" (
    echo ERROR: Missing electron-builder: %REPO_ROOT%\frontend\node_modules\electron-builder\cli.js
    echo HINT: Run npm install in %REPO_ROOT%\frontend first.
    exit /b 1
)

REM The build's own first step smokes this runtime, so checking it here turns a failure
REM that would otherwise arrive after the version bump into an immediate one.
call "%REPO_ROOT%\frontend\node-portable\node.exe" "%REPO_ROOT%\frontend\build\arcbot_runtime\validate_bundled_codex_runtime.js" --runtime-root "%REPO_ROOT%\frontend\node-portable" --cwd "%REPO_ROOT%\frontend" --timeout-ms 30000
if errorlevel 1 (
    echo ERROR: The bundled ArcBot/Codex runtime under node-portable is incomplete or cannot run.
    echo HINT: node-portable is not in Git, so a fresh clone or a copied runtime can be
    echo       missing pieces. Refresh it on this PC with:
    echo         powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\frontend\build\arcbot_runtime\refresh_bundled_codex_runtime.ps1"
    exit /b 1
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 10, 6) <= sys.version_info[:3] < (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: %PRODUCT_NAME% packaging requires Python 3.10.6 or newer within the 3.10 line.
    echo HINT: Install Python 3.10.6+ or set PYTHON_EXE to a compatible interpreter.
    exit /b 1
)

where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI was not found on PATH.
    echo HINT: The version step reads the published release history and the publish step
    echo       creates the release, so gh is required on this PC.
    exit /b 1
)
gh auth status >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI is not authenticated.
    echo HINT: Run gh auth login, or set GH_TOKEN, then retry.
    exit /b 1
)

git -C "%REPO_ROOT%" rev-parse --git-dir >nul 2>nul
if errorlevel 1 (
    echo ERROR: %REPO_ROOT% is not a Git repository.
    exit /b 1
)

REM The shared Python API wheel is published to the ArcRho Server workspace, which on a
REM client PC is a mapped network drive. Fail here rather than after a full package.
REM A build-only installer retains the wheel locally and defers this shared write until
REM the explicit publish action, so it can be tested while the server workspace is offline.
if defined BUILD_ONLY goto check_fragments
if /i not "%ARCRHO_BUILD_PRODUCT%"=="arco" goto check_fragments
for %%I in ("%PYTHON_API_PACKAGE_DIR%\..") do set "PYTHON_API_PACKAGE_PARENT=%%~fI"
if not exist "%PYTHON_API_PACKAGE_PARENT%" (
    echo ERROR: The Python API package destination is unreachable: %PYTHON_API_PACKAGE_DIR%
    echo HINT: On a client PC this is a mapped network drive. Reconnect it, or set
    echo       PYTHON_API_PACKAGE_DIR to a reachable folder before building.
    exit /b 1
)

:check_fragments
"%PYTHON_EXE%" "%REPO_ROOT%\frontend\build\release\release_notes.py" check
if errorlevel 1 (
    echo ERROR: Release note fragment validation failed.
    echo HINT: Fix the fragments under frontend\changes\unreleased before building.
    exit /b 1
)
echo.
exit /b 0

:check_publish_prerequisites
if not exist "%RELEASE_WORKFLOW_SCRIPT%" (
    echo ERROR: Missing local release workflow script: %RELEASE_WORKFLOW_SCRIPT%
    exit /b 1
)
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 10, 6) <= sys.version_info[:3] < (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: %PRODUCT_NAME% release publishing requires Python 3.10.6 or newer within the 3.10 line.
    exit /b 1
)
where gh >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI was not found on PATH.
    echo HINT: Install GitHub CLI and run gh auth login before publishing.
    exit /b 1
)
gh auth status >nul 2>nul
if errorlevel 1 (
    echo ERROR: The gh CLI is not authenticated.
    echo HINT: Run gh auth login, or set GH_TOKEN, then retry.
    exit /b 1
)
echo.
exit /b 0
