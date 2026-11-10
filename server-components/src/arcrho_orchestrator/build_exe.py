import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
REPOSITORY_ROOT = PROJECT_ROOT.parent
SOURCE_ROOT = BASE_DIR.parent
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from utils import (
    DEFAULT_DEPLOY_ROOT,
    component_app_name,
    get_config_value,
    resolve_app_path,
    set_config_value,
)
from build_runtime import ensure_python_310_venv, stage_deploy, swap_deploy

BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
DEPLOY_ROOT = DEFAULT_DEPLOY_ROOT
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"

ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("orchestrator")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Orchestrator.ico"

BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME

# Nothing supervises the orchestrator: the launcher only starts it once at
# login. A deploy therefore has to bring it back up itself, or the server is
# left without the component that maintains engines and the Bridge.
ORCHESTRATOR_KILL_ALL_KEY = "apps.orchestrator.kill_all"
ORCHESTRATOR_SHUTDOWN_TIMEOUT_SECONDS = 60
ORCHESTRATOR_SHUTDOWN_POLL_SECONDS = 1


def clean_build_dirs():
    for folder in (BUILD_DIR, SPEC_DIR, DIST_DIR):
        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            pass


def run(cmd, check=True):
    print("\n>>>", " ".join(map(str, cmd)))
    return subprocess.run(list(map(str, cmd)), check=check)


def ensure_venv():
    ensure_python_310_venv(VENV_PYTHON)


def ensure_venv_python():
    if not VENV_PYTHON.exists():
        raise FileNotFoundError(f"Venv python not found: {VENV_PYTHON}")


def install_requirements():
    if not REQ_FILE.exists():
        raise FileNotFoundError(f"requirements.txt not found: {REQ_FILE}")

    # Upgrade pip tooling first (more reliable installs)
    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    # Install requirements
    run([VENV_PYTHON, "-m", "pip", "install", "-r", REQ_FILE])


def build_exe():
    cmd = [
        VENV_PYTHON,
        "-m", "PyInstaller",
        "--specpath", SPEC_DIR,
        "--noconfirm",
        "--onedir",
        "--paths", SOURCE_ROOT,
        "--paths", CANONICAL_SOURCE_ROOT,
        "--hidden-import", "utils",
        "--hidden-import", "server_config",
        f"--icon={ICON}",
        "--add-data", f"{ICON};.",
        "--noconsole",
        "--clean",
        "--name", APP_NAME,
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        ENTRY_PY,
    ]

    print("\nRunning PyInstaller:")
    print(" ".join(map(str, cmd)))
    run(cmd)


def live_orchestrator_instance_count():
    try:
        entries = list(resolve_app_path("orchestrator", "instances").iterdir())
    except FileNotFoundError:
        return 0
    return sum(1 for entry in entries if entry.is_file())


def wait_for_orchestrator_shutdown():
    deadline = time.monotonic() + ORCHESTRATOR_SHUTDOWN_TIMEOUT_SECONDS
    while True:
        remaining = live_orchestrator_instance_count()
        if not remaining:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"The live Arco Orchestrator did not stop within "
                f"{ORCHESTRATOR_SHUTDOWN_TIMEOUT_SECONDS}s ({remaining} heartbeat(s) "
                "still present). Deploy aborted; the deployed Orchestrator was left "
                "untouched."
            )
        time.sleep(ORCHESTRATOR_SHUTDOWN_POLL_SECONDS)


def start_orchestrator():
    if live_orchestrator_instance_count():
        print("\n>>> An Arco Orchestrator is already running; not starting another.")
        return

    exe = DEPLOY_APP_DIR / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"Deployed orchestrator not found: {exe}")

    print(f"\n>>> Starting {exe}")
    # Its own app folder as working directory: the orchestrator must not pin
    # the folder this build script happened to run from.
    subprocess.Popen([str(exe)], cwd=str(DEPLOY_APP_DIR), close_fds=True)


@contextmanager
def orchestrator_stopped():
    """Hold the orchestrator down for the deploy window, then bring it back.

    Running engines and the Bridge are separate processes with their own kill
    switches, so they keep serving while the orchestrator is replaced; only
    engine replenishment and Bridge relaunch pause. The orchestrator is
    restarted whether the deploy succeeded or rolled back, so a failed deploy
    never leaves the server without one.
    """

    previous = get_config_value(ORCHESTRATOR_KILL_ALL_KEY, False)
    print(f"\n>>> Stopping the live Arco Orchestrator ({ORCHESTRATOR_KILL_ALL_KEY} = True)")
    set_config_value(ORCHESTRATOR_KILL_ALL_KEY, True)
    try:
        wait_for_orchestrator_shutdown()
        yield
    finally:
        print(f"\n>>> Releasing the Arco Orchestrator ({ORCHESTRATOR_KILL_ALL_KEY} = {previous})")
        set_config_value(ORCHESTRATOR_KILL_ALL_KEY, previous)
        start_orchestrator()


def deploy_exe():
    """Sync the staged build into its slot, then rotate it into place.

    PyInstaller builds into an isolated dist folder rather than straight into
    the deployed app folder. Building in place would delete the live
    orchestrator before writing its replacement, so any locked file left the
    deployment destroyed with nothing to fall back to.
    """

    stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
    swap_deploy(APPS_DIR, APP_NAME)


def main():
    clean_build_dirs()
    ensure_venv()
    ensure_venv_python()
    install_requirements()
    build_exe()
    if STAGE_ONLY:
        exe_path = STAGED_APP_DIR / f"{APP_NAME}.exe"
    else:
        with orchestrator_stopped():
            deploy_exe()
        exe_path = DEPLOY_APP_DIR / f"{APP_NAME}.exe"
    print(f"\nBuild finished: {exe_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
