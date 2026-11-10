@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
if not defined ARCRHO_BUILD_PRODUCT set "ARCRHO_BUILD_PRODUCT=arco"
if /i "%ARCRHO_BUILD_PRODUCT%"=="arco" goto product_arco
if /i "%ARCRHO_BUILD_PRODUCT%"=="arcode" goto product_arcode
echo ERROR: Unsupported ARCRHO_BUILD_PRODUCT: %ARCRHO_BUILD_PRODUCT%
echo Expected arco or arcode.
exit /b 1

:product_arco
set "PRODUCT_NAME=Arco"
set "INSTALLER_PREFIX=Arco"
set "DEFAULT_LOCAL_ROOT=%USERPROFILE%\Documents\build_arcrho_app"
set "PYTHON_SERVER_BUILD_SCRIPT=build\build_python_server.bat"
set "PYTHON_SERVER_DIR=arcrho_server"
set "PYTHON_SERVER_EXE=arcrho_server.exe"
set "ELECTRON_BUILDER_CONFIG_ARGS="
set "PUBLISH_PYTHON_API=1"
goto product_ready

:product_arcode
set "PRODUCT_NAME=Arcode"
set "INSTALLER_PREFIX=Arcode"
set "DEFAULT_LOCAL_ROOT=%USERPROFILE%\Documents\build_arcode_app"
set "PYTHON_SERVER_BUILD_SCRIPT=build\build_arcode_python_server.bat"
set "PYTHON_SERVER_DIR=arcode_server"
set "PYTHON_SERVER_EXE=arcode_server.exe"
set "ELECTRON_BUILDER_CONFIG_ARGS=--config electron-builder.arcode.json"
set "PUBLISH_PYTHON_API=0"
set "ARCRHO_APP_MODE=arcode"

:product_ready
if defined ARCRHO_LOCAL_WORKSPACE_LOG_ACTIVE goto after_wrapper_log_setup
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"`) do set "ARCRHO_LOCAL_WORKSPACE_LOG_STAMP=%%I"
set "ARCRHO_LOCAL_WORKSPACE_LOG_DIR=E:\XWSpace\Build ArcRho App\logs\%COMPUTERNAME%"
REM A single-PC build has no build share to log into, so it points the log
REM directory at a local folder. Unset, the two-PC default above is unchanged.
if defined ARCRHO_BUILD_LOG_DIR set "ARCRHO_LOCAL_WORKSPACE_LOG_DIR=%ARCRHO_BUILD_LOG_DIR%"
set "ARCRHO_LOCAL_WORKSPACE_LOG_FILE=%ARCRHO_LOCAL_WORKSPACE_LOG_DIR%\build_%ARCRHO_BUILD_PRODUCT%_via_local_workspace_%ARCRHO_LOCAL_WORKSPACE_LOG_STAMP%.log"
echo Writing local-workspace build log to: %ARCRHO_LOCAL_WORKSPACE_LOG_FILE%
set "ARCRHO_LOCAL_WORKSPACE_LOG_ACTIVE=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%transport\run_with_log.ps1" -LogPath "%ARCRHO_LOCAL_WORKSPACE_LOG_FILE%" -CommandPath "%~f0" %*
exit /b %ERRORLEVEL%

:after_wrapper_log_setup

REM Copies the network/source archive to a local Documents build workspace,
REM waits for its completion flag, then runs the selected app build from that
REM local workspace and opens the published installer.
REM Optional:
REM   set ARCRHO_LOCAL_BUILD_ROOT=C:\Local\Path\build_arcrho_app
REM   set ARCRHO_LOCAL_BUILD_SOURCE_ZIP=E:\XWSpace\Build ArcRho App\ArcRho.zip
REM Optional arguments are forwarded to the local application build stage.

set "SOURCE_ZIP=E:\XWSpace\Build ArcRho App\ArcRho.zip"
if defined ARCRHO_LOCAL_BUILD_SOURCE_ZIP set "SOURCE_ZIP=%ARCRHO_LOCAL_BUILD_SOURCE_ZIP%"
set "LOCAL_ROOT=%DEFAULT_LOCAL_ROOT%"
if defined ARCRHO_LOCAL_BUILD_ROOT set "LOCAL_ROOT=%ARCRHO_LOCAL_BUILD_ROOT%"
set "LOCAL_FRONTEND=%LOCAL_ROOT%\frontend"
set "SOURCE_ZIP_READY_FLAG=%SOURCE_ZIP%.ready"
set "SOURCE_ZIP_HASH=%SOURCE_ZIP%.sha256"
set "READY_SIGNAL_FILE=%LOCAL_ROOT%.source_zip_ready_signal"
if not defined ARCRHO_BUILD_LOG_DIR set "ARCRHO_BUILD_LOG_DIR=E:\XWSpace\Build ArcRho App\logs\%COMPUTERNAME%"
set "ARCRHO_LOCAL_BUILD_START_SECONDS="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()" 2^>nul`) do set "ARCRHO_LOCAL_BUILD_START_SECONDS=%%I"

if /i "%~1"=="--check" (
    echo Network/source build script: %SCRIPT_DIR%
    echo Product:                     %PRODUCT_NAME%
    echo Source archive:              %SOURCE_ZIP%
    echo Source completion flag:      %SOURCE_ZIP_READY_FLAG%
    echo Local workspace:           %LOCAL_ROOT%
    echo Consumed-signal marker:     %READY_SIGNAL_FILE%
    echo Release channel definition: %SCRIPT_DIR%release\release_channel.json
    echo Shared build log directory: %ARCRHO_BUILD_LOG_DIR%
    if not exist "%SCRIPT_DIR%transport\prepare_local_build_workspace_from_zip.ps1" (
        echo ERROR: Missing prepare_local_build_workspace_from_zip.ps1 beside this batch file.
        exit /b 1
    )
    echo Local workspace wrapper check passed.
    exit /b 0
)

if defined ARCRHO_BUILD_IN_PLACE goto workspace_ready

echo ========================================
echo Preparing local %PRODUCT_NAME% build workspace
echo ========================================
echo Source build script: %SCRIPT_DIR%
echo Source archive:      %SOURCE_ZIP%
echo Completion flag:     %SOURCE_ZIP_READY_FLAG%
echo Local workspace:     %LOCAL_ROOT%
echo Signal marker:       %READY_SIGNAL_FILE%
echo Shared log directory: %ARCRHO_BUILD_LOG_DIR%
echo.

call :wait_for_new_source_zip_signal
if errorlevel 1 (
    echo.
    echo ERROR: Failed while waiting for a completed source ZIP.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%transport\prepare_local_build_workspace_from_zip.ps1" -SourceZip "%SOURCE_ZIP%" -Destination "%LOCAL_ROOT%"
if errorlevel 1 (
    echo.
    echo ERROR: Failed to prepare local build workspace.
    pause
    exit /b 1
)

if not exist "%LOCAL_FRONTEND%\build\build_app_via_local_workspace.bat" (
    echo.
    echo ERROR: Local build script was not copied to %LOCAL_FRONTEND%\build\build_app_via_local_workspace.bat
    pause
    exit /b 1
)

:workspace_ready
REM In-place mode skips the ZIP transport entirely: the repository is already on
REM this PC, so LOCAL_ROOT points at it and the build runs against its own
REM frontend. A one-step build writes its version bump, release notes, and archived fragments
REM into that repository; build-only mode defers those release artifacts until publication.
echo.
echo ========================================
if defined ARCRHO_BUILD_IN_PLACE echo Building %PRODUCT_NAME% in place from the local repository
if not defined ARCRHO_BUILD_IN_PLACE echo Building %PRODUCT_NAME% from local workspace
echo ========================================
if defined ARCRHO_BUILD_IN_PLACE echo Repository:          %LOCAL_ROOT%
if defined ARCRHO_BUILD_IN_PLACE echo Build log directory: %ARCRHO_BUILD_LOG_DIR%
echo.

pushd "%LOCAL_FRONTEND%"
if errorlevel 1 (
    echo ERROR: Could not enter local frontend directory: %LOCAL_FRONTEND%
    call :pause_if_interactive
    exit /b 1
)

set "ARCRHO_INSTALL_PYTHON_DEPS=1"
set "ARCRHO_SKIP_SUCCESS_PAUSE=1"
call :build_local_application %*
set "BUILD_EXIT_CODE=%ERRORLEVEL%"

popd

if not "%BUILD_EXIT_CODE%"=="0" (
    echo.
    echo ERROR: Local %PRODUCT_NAME% build failed with exit code %BUILD_EXIT_CODE%.
    echo Build log directory: %ARCRHO_BUILD_LOG_DIR%
    call :print_total_time
    call :pause_if_interactive
    exit /b %BUILD_EXIT_CODE%
)

echo.
echo ========================================
echo Local %PRODUCT_NAME% build completed successfully
echo ========================================
echo Local output directory: %LOCAL_FRONTEND%\dist
echo.
call :publish_built_version
call :record_source_zip_signal
if errorlevel 1 (
    echo WARNING: Could not record the completed ZIP signal.
    echo The next Step 2 run may build this ZIP again.
    echo.
)
call :sync_source_repository
call :print_total_time
if defined ARCRHO_RELEASE_BUILD_ONLY goto skip_open_released_installer
call :open_released_installer
if errorlevel 1 (
    echo.
    echo WARNING: The build succeeded, but the built installer could not be opened.
    echo Local output directory: %LOCAL_FRONTEND%\dist
    call :pause_if_interactive
)
:skip_open_released_installer
exit /b 0

:wait_for_new_source_zip_signal
set "LAST_READY_SIGNAL="
if exist "%READY_SIGNAL_FILE%" set /p LAST_READY_SIGNAL=<"%READY_SIGNAL_FILE%"
echo Waiting for Step 1 to publish a new completed ZIP signal...
echo Press Ctrl+C to stop waiting.

:wait_for_new_source_zip_signal_loop
set "CURRENT_READY_SIGNAL="
if exist "%SOURCE_ZIP_READY_FLAG%" set /p CURRENT_READY_SIGNAL=<"%SOURCE_ZIP_READY_FLAG%"
if not defined CURRENT_READY_SIGNAL goto wait_for_new_source_zip_signal_delay
if defined LAST_READY_SIGNAL if "%CURRENT_READY_SIGNAL%"=="%LAST_READY_SIGNAL%" goto wait_for_new_source_zip_signal_delay
if not exist "%SOURCE_ZIP%" goto wait_for_new_source_zip_signal_delay
if not exist "%SOURCE_ZIP_HASH%" goto wait_for_new_source_zip_signal_delay
echo New completed source ZIP detected.
echo Signal: %CURRENT_READY_SIGNAL%
echo.
exit /b 0

:wait_for_new_source_zip_signal_delay
timeout /t 5 /nobreak >nul
goto wait_for_new_source_zip_signal_loop

:record_source_zip_signal
REM An in-place build consumed no ZIP, so there is no readiness token to record.
if defined ARCRHO_BUILD_IN_PLACE exit /b 0
if not defined CURRENT_READY_SIGNAL exit /b 1
for %%I in ("%READY_SIGNAL_FILE%") do if not exist "%%~dpI" mkdir "%%~dpI" >nul 2>nul
> "%READY_SIGNAL_FILE%" echo %CURRENT_READY_SIGNAL%
if errorlevel 1 exit /b 1
exit /b 0

:publish_built_version
REM A caller that drives this wrapper itself cannot read APP_VERSION back out of it,
REM because the wrapper runs under setlocal. Hand the built version over through a
REM file when the caller asked for one.
if not defined ARCRHO_BUILD_VERSION_OUT exit /b 0
if not defined APP_VERSION exit /b 0
for %%I in ("%ARCRHO_BUILD_VERSION_OUT%") do if not exist "%%~dpI" mkdir "%%~dpI" >nul 2>nul
> "%ARCRHO_BUILD_VERSION_OUT%" echo %APP_VERSION%
exit /b 0

:sync_source_repository
REM The build workspace is disposable and cannot write to the source repository, so
REM ask the listener that runs beside the repository to record what this build shipped.
if not defined APP_VERSION (
    echo WARNING: No built version is available, so the repository was not synced.
    echo.
    exit /b 0
)
REM On a single PC the repository is already on this machine, so there is no listener
REM to ask and nothing to wait for. An in-place build has already written the version
REM bump, release notes, and archived fragments straight into it.
if defined ARCRHO_BUILD_IN_PLACE goto skip_listener_release_sync
if defined ARCRHO_SKIP_LISTENER_RELEASE_SYNC goto skip_listener_release_sync
goto run_listener_release_sync

:skip_listener_release_sync
echo Skipping the build-share listener sync request; this repository is local.
echo.
exit /b 0

:run_listener_release_sync
for %%I in ("%SOURCE_ZIP%") do set "BUILD_SHARE_ROOT=%%~dpI"
if defined BUILD_SHARE_ROOT set "BUILD_SHARE_ROOT=%BUILD_SHARE_ROOT:~0,-1%"
echo Syncing the source repository to the published release...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%release\request_release_sync.ps1" -Version "%APP_VERSION%" -ProductName "%PRODUCT_NAME%" -BuildShareRoot "%BUILD_SHARE_ROOT%" -ReadySignal "%CURRENT_READY_SIGNAL%"
if errorlevel 1 (
    echo.
    echo WARNING: The published release was not recorded in the source repository.
    echo The installer is already published; only the repository bookkeeping is missing.
    echo Run this on the source PC to finish it:
    echo   frontend\build\sync_published_release.bat %APP_VERSION%
    echo.
    exit /b 0
)
echo.
exit /b 0

:open_released_installer
if not defined APP_VERSION (
    echo ERROR: No built version is available to open.
    exit /b 1
)
set "BUILT_INSTALLER=%LOCAL_FRONTEND%\dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe"
if not exist "%BUILT_INSTALLER%" (
    echo ERROR: Built installer not found: %BUILT_INSTALLER%
    exit /b 1
)
echo Opening built installer: %BUILT_INSTALLER%
start "" "%BUILT_INSTALLER%"
exit /b 0

:print_total_time
if not defined ARCRHO_LOCAL_BUILD_START_SECONDS exit /b 0
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$elapsed = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$env:ARCRHO_LOCAL_BUILD_START_SECONDS; $span = [TimeSpan]::FromSeconds($elapsed); if ($span.TotalHours -ge 1) { '{0:00}:{1:00}:{2:00}' -f [int]$span.TotalHours, $span.Minutes, $span.Seconds } else { '{0:00}:{1:00}' -f [int]$span.TotalMinutes, $span.Seconds }" 2^>nul`) do set "ARCRHO_LOCAL_BUILD_ELAPSED=%%I"
if defined ARCRHO_LOCAL_BUILD_ELAPSED echo Total time spent: %ARCRHO_LOCAL_BUILD_ELAPSED%
exit /b 0

:build_local_application
set "APP_ROOT=%CD%"
if not defined ARCRHO_BUILD_LOG_FILE set "ARCRHO_BUILD_LOG_FILE=%ARCRHO_LOCAL_WORKSPACE_LOG_FILE%"

echo ========================================
echo Building %PRODUCT_NAME% Standalone Application
echo ========================================
echo.
if defined ARCRHO_BUILD_LOG_FILE (
    echo Build log: %ARCRHO_BUILD_LOG_FILE%
    echo.
)

REM Setup portable node in PATH
set "NODE_HOME=%APP_ROOT%\node-portable"
set "PATH=%NODE_HOME%;%PATH%"
set "APP_BUILDER_EXE=node_modules\app-builder-bin\win\x64\app-builder.exe"
set "APP_VERSION="
if not defined PYTHON_API_PACKAGE_DIR set "PYTHON_API_PACKAGE_DIR=E:\Arco Server\packages"
set "PYTHON_API_WHEEL="

echo Validating bundled Node, npm, and Codex runtime...
call :validate_bundled_codex_runtime "%NODE_HOME%" "%APP_ROOT%"
if errorlevel 1 (
    echo ERROR: Bundled Node, npm, and Codex runtime validation failed.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Bundled CLI runtime validated.
echo.

if not defined PYTHON_EXE (
    for /f "usebackq delims=" %%I in (`py -3.10 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%I"
)
if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo Using Python: %PYTHON_EXE%
call :validate_python_310
if errorlevel 1 (
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo.

echo Step 0: Validating release note fragments...
echo ----------------------------------------
"%PYTHON_EXE%" build\release\release_notes.py check
if errorlevel 1 (
    echo ERROR: Release note fragment validation failed.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Release note fragments validated.
echo.

echo Step 1: Updating application version...
echo ----------------------------------------
set "APP_VERSION_FILE=build\app_version.txt"
if exist "%APP_VERSION_FILE%" del /q "%APP_VERSION_FILE%" >nul 2>nul
if "%~1"=="" (
    "%PYTHON_EXE%" build\release\version_manager.py --github-release-product "%PRODUCT_NAME%" --version-file "%APP_VERSION_FILE%"
) else (
    "%PYTHON_EXE%" build\release\version_manager.py "%~1" --github-release-product "%PRODUCT_NAME%" --version-file "%APP_VERSION_FILE%"
)
if errorlevel 1 (
    echo ERROR: Failed to update application version metadata.
    echo HINT: The next version comes from the GitHub Releases history, so gh must be
    echo       authenticated on this machine ^(run: gh auth status^).
    echo.
    call :pause_if_interactive
    exit /b 1
)
if exist "%APP_VERSION_FILE%" (
    set /p APP_VERSION=<"%APP_VERSION_FILE%"
    del /q "%APP_VERSION_FILE%" >nul 2>nul
)
if not defined APP_VERSION (
    echo ERROR: Version updater did not return a version.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Building version %APP_VERSION%
echo.

if "%PUBLISH_PYTHON_API%"=="1" (
    echo Step 2: Building Python API wheel...
    echo ----------------------------------------
    call :build_python_api_wheel
    if errorlevel 1 (
        echo.
        call :pause_if_interactive
        exit /b 1
    )
    echo Python API wheel built: %PYTHON_API_WHEEL%
    echo.
) else (
    echo Step 2: Python API wheel publication is not part of the %PRODUCT_NAME% build.
    echo.
)

echo Step 3: Building Python app server with PyInstaller...
echo ----------------------------------------
call :run_pyinstaller
if errorlevel 1 (
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Python app server built successfully!
echo.

echo Step 4: Writing release notes for this version...
echo ----------------------------------------
REM The app reads its Release History from the notes packaged inside it, so this
REM version's notes must exist before the packaging step below picks up docs\releases.
REM The fragments stay unreleased until Step 6 archives them.
"%PYTHON_EXE%" build\release\release_notes.py stage-notes "%APP_VERSION%"
if errorlevel 1 (
    echo ERROR: Failed to write release notes for version %APP_VERSION%.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo.

echo Step 5: Building Electron app with electron-builder...
echo ----------------------------------------
if not exist "python_dist\%PYTHON_SERVER_DIR%\%PYTHON_SERVER_EXE%" (
    echo ERROR: Missing app-server bundle: python_dist\%PYTHON_SERVER_DIR%\%PYTHON_SERVER_EXE%
    echo HINT: PyInstaller step did not produce the server executable.
    echo       Do not continue, otherwise installer may build fast but fail at launch.
    echo.
    call :pause_if_interactive
    exit /b 1
)
call :prepare_app_builder
call :run_electron
if errorlevel 1 (
    echo.
    call :pause_if_interactive
    exit /b 1
)

set "PACKAGED_NODE_HOME=%APP_ROOT%\dist\win-unpacked\resources\node-portable"
echo Validating packaged ArcBot CLI runtime...
call :validate_bundled_codex_runtime "%PACKAGED_NODE_HOME%" "%APP_ROOT%"
if errorlevel 1 (
    echo ERROR: Packaged Node, npm, and Codex runtime validation failed.
    echo HINT: The installer was not published because its bundled CLI payload is incomplete or cannot run.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Packaged ArcBot CLI runtime validated.
echo.

if not exist "dist\%INSTALLER_PREFIX%-Setup-*.exe" (
    echo ERROR: Installer was not generated in dist\.
    echo.
    call :pause_if_interactive
    exit /b 1
)

if defined ARCRHO_RELEASE_BUILD_ONLY goto record_pending_release

echo.
echo Step 6: Archiving the release note fragments...
echo ----------------------------------------
set "RELEASE_NOTE_PATH_FILE=build\release_note_path_%APP_VERSION%.txt"
if exist "%RELEASE_NOTE_PATH_FILE%" del /q "%RELEASE_NOTE_PATH_FILE%" >nul 2>nul
"%PYTHON_EXE%" build\release\release_notes.py release "%APP_VERSION%" --path-file "%RELEASE_NOTE_PATH_FILE%"
if errorlevel 1 (
    echo ERROR: Failed to archive the release note fragments for version %APP_VERSION%.
    echo.
    call :pause_if_interactive
    exit /b 1
)
if exist "%RELEASE_NOTE_PATH_FILE%" (
    set /p RELEASE_NOTE_PATH=<"%RELEASE_NOTE_PATH_FILE%"
    del /q "%RELEASE_NOTE_PATH_FILE%" >nul 2>nul
)
if not defined RELEASE_NOTE_PATH (
    echo ERROR: Release note generator did not return a release note path.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Release notes: %RELEASE_NOTE_PATH%
echo.

echo Step 7: Publishing GitHub Release...
echo ----------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "build\release\publish_github_release.ps1" -InstallerPath "dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe" -ReleaseNotesPath "%RELEASE_NOTE_PATH%" -ProductName "%PRODUCT_NAME%"
if errorlevel 1 (
    echo ERROR: Failed to publish GitHub Release.
    echo HINT: Ensure the gh CLI is installed and authenticated ^(run: gh auth login^).
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo GitHub Release published.
echo.

goto after_release_publication

:record_pending_release
echo.
echo Step 6: Recording pending local release...
echo ----------------------------------------
call :capture_pending_release
if errorlevel 1 (
    echo ERROR: Failed to record the built installer for later publication.
    echo.
    call :pause_if_interactive
    exit /b 1
)
echo Pending local release recorded. Test the installer, then publish it from Release Manager.
echo.

:after_release_publication

if defined ARCRHO_RELEASE_BUILD_ONLY goto after_python_api_publication
if "%PUBLISH_PYTHON_API%"=="1" (
    echo Step 8: Publishing Python API package...
    echo ----------------------------------------
    call :publish_python_api_package
    if errorlevel 1 (
        echo.
        call :pause_if_interactive
        exit /b 1
    )
    echo Python API package published: %PYTHON_API_PACKAGE_DIR%
    echo.
) else (
    echo Step 8: Shared Python API package publication is not part of the %PRODUCT_NAME% build.
    echo.
)

:after_python_api_publication

echo Step 9: Cleaning Python build artifacts...
echo ----------------------------------------
if exist "python_dist" (
    rmdir /s /q "python_dist"
)
if exist "python_build" (
    rmdir /s /q "python_build"
)

if exist "dist\win-unpacked" (
    rmdir /s /q "dist\win-unpacked"
)
del /q "dist\*Portable*.exe" 2>nul
del /q "dist\*-portable*.exe" 2>nul
del /q "dist\*.zip" 2>nul

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo.
echo Output location: dist\
echo.
echo - %INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe  (Installer)
if defined ARCRHO_RELEASE_BUILD_ONLY echo - Pending local release record  (Publish only after local testing)
if not defined ARCRHO_RELEASE_BUILD_ONLY echo - GitHub Release %PRODUCT_NAME%-v%APP_VERSION%  (Published Installer and Auto-Update Source)
if "%PUBLISH_PYTHON_API%"=="1" if not defined ARCRHO_RELEASE_BUILD_ONLY echo - %PYTHON_API_PACKAGE_DIR%\arcrho_api-latest.whl  (Python API Package)
if not defined ARCRHO_RELEASE_BUILD_ONLY echo - %RELEASE_NOTE_PATH%  (Release Notes)
echo.
if not defined ARCRHO_SKIP_SUCCESS_PAUSE call :pause_if_interactive
exit /b 0

:capture_pending_release
if not defined APP_VERSION (
    echo ERROR: No built version is available to record.
    exit /b 1
)
if not exist "build\release\release_workflow.py" (
    echo ERROR: Missing pending-release workflow helper: build\release\release_workflow.py
    exit /b 1
)
if "%PUBLISH_PYTHON_API%"=="1" goto capture_pending_release_with_wheel
if defined ARCRHO_RELEASE_VERSION_SNAPSHOT goto capture_pending_release_with_snapshot
"%PYTHON_EXE%" build\release\release_workflow.py capture-built --product "%PRODUCT_NAME%" --version "%APP_VERSION%" --installer-path "dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe"
exit /b %ERRORLEVEL%

:capture_pending_release_with_snapshot
"%PYTHON_EXE%" build\release\release_workflow.py capture-built --product "%PRODUCT_NAME%" --version "%APP_VERSION%" --installer-path "dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe" --version-snapshot-path "%ARCRHO_RELEASE_VERSION_SNAPSHOT%"
exit /b %ERRORLEVEL%

:capture_pending_release_with_wheel
if defined ARCRHO_RELEASE_VERSION_SNAPSHOT goto capture_pending_release_with_wheel_snapshot
"%PYTHON_EXE%" build\release\release_workflow.py capture-built --product "%PRODUCT_NAME%" --version "%APP_VERSION%" --installer-path "dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe" --python-api-wheel-path "%PYTHON_API_WHEEL%" --python-api-package-dir "%PYTHON_API_PACKAGE_DIR%"
exit /b %ERRORLEVEL%

:capture_pending_release_with_wheel_snapshot
"%PYTHON_EXE%" build\release\release_workflow.py capture-built --product "%PRODUCT_NAME%" --version "%APP_VERSION%" --installer-path "dist\%INSTALLER_PREFIX%-Setup-%APP_VERSION%.exe" --python-api-wheel-path "%PYTHON_API_WHEEL%" --python-api-package-dir "%PYTHON_API_PACKAGE_DIR%" --version-snapshot-path "%ARCRHO_RELEASE_VERSION_SNAPSHOT%"
exit /b %ERRORLEVEL%

:build_python_api_wheel
if not exist "%NODE_HOME%\node.exe" (
    echo ERROR: Missing portable node: %NODE_HOME%\node.exe
    exit /b 1
)
call "%NODE_HOME%\node.exe" build\helpers\build_python_api_wheel.js
if errorlevel 1 (
    echo ERROR: Failed to build Python API wheel.
    exit /b 1
)
for %%I in ("build\python_packages\arcrho_api-*.whl") do set "PYTHON_API_WHEEL=%%~fI"
if not defined PYTHON_API_WHEEL (
    echo ERROR: Python API wheel was not generated in build\python_packages.
    exit /b 1
)
if not exist "%PYTHON_API_WHEEL%" (
    echo ERROR: Python API wheel path does not exist: %PYTHON_API_WHEEL%
    exit /b 1
)
exit /b 0

:publish_python_api_package
if not defined PYTHON_API_WHEEL (
    echo ERROR: Python API wheel path is empty.
    exit /b 1
)
if not exist "%PYTHON_API_WHEEL%" (
    echo ERROR: Python API wheel does not exist: %PYTHON_API_WHEEL%
    exit /b 1
)
if not exist "build\release\release_workflow.py" (
    echo ERROR: Missing Python API publication workflow helper: build\release\release_workflow.py
    exit /b 1
)
"%PYTHON_EXE%" build\release\release_workflow.py publish-python-api --wheel-path "%PYTHON_API_WHEEL%" --destination "%PYTHON_API_PACKAGE_DIR%"
if errorlevel 1 (
    echo ERROR: Failed to publish the Python API wheel to %PYTHON_API_PACKAGE_DIR%.
    exit /b 1
)
exit /b 0

:validate_python_310
"%PYTHON_EXE%" --version
if errorlevel 1 (
    echo ERROR: Could not run selected Python interpreter: %PYTHON_EXE%
    echo HINT: Install Python 3.10 or set PYTHON_EXE to a Python 3.10 executable.
    exit /b 1
)
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 10, 6) <= sys.version_info[:3] < (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo ERROR: %PRODUCT_NAME% packaging requires Python 3.10.6 or newer within the Python 3.10 line.
    echo HINT: Install Python 3.10.6+ or set PYTHON_EXE to a compatible Python 3.10 executable before running the one-click build.
    exit /b 1
)
exit /b 0

:validate_bundled_codex_runtime
if not exist "%~1\node.exe" (
    echo ERROR: Missing portable Node executable: %~1\node.exe
    exit /b 1
)
if not exist "%APP_ROOT%\build\arcbot_runtime\validate_bundled_codex_runtime.js" (
    echo ERROR: Missing bundled CLI runtime validator: %APP_ROOT%\build\arcbot_runtime\validate_bundled_codex_runtime.js
    exit /b 1
)
call "%~1\node.exe" "%APP_ROOT%\build\arcbot_runtime\validate_bundled_codex_runtime.js" --runtime-root "%~1" --cwd "%~2" --timeout-ms 30000
if errorlevel 1 exit /b 1
exit /b 0

:run_pyinstaller
call %PYTHON_SERVER_BUILD_SCRIPT%
if not errorlevel 1 exit /b 0

echo.
echo WARNING: PyInstaller failed on first attempt.
echo Retrying once with a clean Python build workspace...
if exist "python_dist" (
    rmdir /s /q "python_dist"
)
if exist "python_build" (
    rmdir /s /q "python_build"
)
call %PYTHON_SERVER_BUILD_SCRIPT% --clean
if not errorlevel 1 exit /b 0

echo ERROR: PyInstaller build failed after retry.
echo HINT: Re-run manually to capture full traceback:
echo       set PYTHON_EXE=%PYTHON_EXE%
echo       %PYTHON_SERVER_BUILD_SCRIPT% --clean
exit /b 1

:prepare_app_builder
if not exist "%APP_BUILDER_EXE%" exit /b 0
REM Best-effort unblock in case Windows marks this binary as downloaded.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Item -Path '%APP_BUILDER_EXE%' -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" >nul 2>nul
exit /b 0

:run_electron
if /i "%ARCRHO_BUILD_PRODUCT%"=="arcode" (
    call "%NODE_HOME%\node.exe" build\helpers\convert_icon.js icons\icon_wing_geo_v8.svg build\generated\arcode-icons
    if errorlevel 1 (
        echo ERROR: Failed to generate Arcode icons from icons\icon_wing_geo_v8.svg.
        exit /b 1
    )
)
call "%NODE_HOME%\node.exe" build\installer\patch_nsis_installer_progress.js
if errorlevel 1 (
    echo ERROR: Failed to prepare NSIS installer progress patch.
    exit /b 1
)
call "%NODE_HOME%\node.exe" node_modules\electron-builder\cli.js %ELECTRON_BUILDER_CONFIG_ARGS% --win
if not errorlevel 1 exit /b 0

echo.
echo WARNING: Electron build failed on first attempt.
echo Retrying once after re-preparing app-builder...
call :prepare_app_builder
call "%NODE_HOME%\node.exe" build\installer\patch_nsis_installer_progress.js
if errorlevel 1 (
    echo ERROR: Failed to prepare NSIS installer progress patch.
    exit /b 1
)
timeout /t 2 /nobreak >nul
call "%NODE_HOME%\node.exe" node_modules\electron-builder\cli.js %ELECTRON_BUILDER_CONFIG_ARGS% --win
if not errorlevel 1 exit /b 0

echo ERROR: Electron build failed after retry.
echo HINT: If error shows "spawn EPERM" for app-builder.exe, run:
echo       powershell -NoProfile -Command "Get-Item '%APP_BUILDER_EXE%' ^| Unblock-File"
echo       Then retry the one-click build workflow.
exit /b 1

:pause_if_interactive
if defined ARCRHO_NONINTERACTIVE exit /b 0
pause
exit /b 0
