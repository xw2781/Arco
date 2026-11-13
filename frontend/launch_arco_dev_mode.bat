@echo off
setlocal
cd /d "%~dp0"

REM ArcRho / Arcode development launcher.
REM
REM   launch_arcrho_dev_mode.bat           launches ArcRho  (default)
REM   launch_arcrho_dev_mode.bat arcode    launches Arcode
REM
REM The supervisor runs under pythonw and the backend console is hidden, so no
REM Python window accompanies the app.
REM
REM The displayed version comes from package.json through Electron's
REM app.getVersion(); the host appends "+" for unpackaged launches, so a dev
REM launch stays visually distinct from an installed release without this script
REM having to supply a version of its own.

set "APP_MODE=%~1"
if not defined APP_MODE set "APP_MODE=arcrho"
if /i "%APP_MODE%"=="arcrho" goto mode_ok
if /i "%APP_MODE%"=="arcode" goto mode_ok
echo Unknown mode "%APP_MODE%". Usage: %~nx0 [arcrho^|arcode]
pause
exit /b 1
:mode_ok

REM VS Code exports ELECTRON_RUN_AS_NODE=1 to its integrated terminals and
REM extension-host children, and it is inherited all the way down to our own
REM Electron.  Under that flag electron.exe runs as plain Node, so
REM require("electron") hands back the executable path instead of the API and
REM main.js dies on `app.getName` before a window ever opens.  Launching from
REM Explorer never sees it; launching from an editor terminal always does.
set "ELECTRON_RUN_AS_NODE="

set "NODE_HOME=%~dp0node-portable"
set "NPM_CMD=npm.cmd"

if exist "%NODE_HOME%\node.exe" (
  set "PATH=%NODE_HOME%;%PATH%"
  set "NPM_CMD=%NODE_HOME%\npm.cmd"
)

where node >nul 2>nul
if errorlevel 1 (
  echo Node.js not found. Extract the portable zip to: %NODE_HOME%
  echo Expected: %NODE_HOME%\node.exe
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo node_modules not found. Running npm install...
  call "%NPM_CMD%" install
  if errorlevel 1 (
    echo npm install failed.
    pause
    exit /b 1
  )
)

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMddHHmmss"') do set "ARCRHO_UI_VERSION=%%i"
set "ARCRHO_BACKEND_CONSOLE=hidden"

if not defined PYTHON_EXE (
  for /f "usebackq delims=" %%i in (`py -3.10 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%i"
)

if not defined PYTHON_EXE set "PYTHON_EXE=python"

"%PYTHON_EXE%" -c "import uvicorn, fastapi, pandas, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo ArcRho Python service dependencies were not found for: %PYTHON_EXE%
  echo Install the backend dependencies for that Python, or set PYTHON_EXE to a Python environment that has uvicorn, fastapi, pandas, and openpyxl.
  echo Example: set PYTHON_EXE=C:\Program Files\Python310\python.exe
  pause
  exit /b 1
)

REM Derive pythonw.exe in batch rather than through a `for /f` over a quoted
REM interpreter path: cmd mis-parses a backquoted command whose first token is
REM quoted, so that form failed silently and left the supervisor on python.exe.
set "PYTHONW_EXE=%PYTHON_EXE%"
for %%I in ("%PYTHON_EXE%") do set "PYTHONW_CANDIDATE=%%~dpIpythonw.exe"
if exist "%PYTHONW_CANDIDATE%" set "PYTHONW_EXE=%PYTHONW_CANDIDATE%"

REM Only the supervisor runs under pythonw. PYTHON_EXE stays the console build
REM because Electron passes it to the app server, and uvicorn logs to stderr:
REM under pythonw with no console sys.stderr is None and uvicorn exits with
REM code 1 before it ever binds the port. The backend still opens no window --
REM Electron spawns it with windowsHide and ignored stdio.
start "" "%PYTHONW_EXE%" "%~dp0electron_shell.py" --mode %APP_MODE%
endlocal
