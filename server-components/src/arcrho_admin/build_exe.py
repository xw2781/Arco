import shutil
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
REPOSITORY_ROOT = PROJECT_ROOT.parent
SOURCE_ROOT = BASE_DIR.parent
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_runtime import (
    align_workspace_root_env,
    ensure_python_310_venv,
    is_local_fixed_path,
    stage_deploy,
    swap_deploy,
)

# Must run before utils is imported: utils resolves the workspace root once at
# import time, and this build reads the deployed workspace's config, kill
# switch, and heartbeats.
align_workspace_root_env()

from utils import (  # noqa: E402
    DEFAULT_DEPLOY_ROOT,
    component_app_name,
    get_config_value,
    resolve_app_path,
    set_config_value,
)

BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
DEPLOY_ROOT = DEFAULT_DEPLOY_ROOT
DEPLOY_ROOT_IS_LOCAL = is_local_fixed_path(DEPLOY_ROOT)
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
ENTRY_PY = BASE_DIR / "main.py"
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"
APP_NAME = component_app_name("admin")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Orchestrator.ico"

BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME
KILL_ALL_KEY = "apps.admin.kill_all"
# The switch is polled on Admin Control's heartbeat interval, so this only
# has to cover one tick plus the shutdown itself before falling back.
KILL_SWITCH_GRACE_SECONDS = 8
SHUTDOWN_TIMEOUT_SECONDS = 30
ADMIN_PORT = int(os.environ.get("ARCRHO_ADMIN_PORT") or 28766)


def run(cmd, check=True):
    print("\n>>>", " ".join(map(str, cmd)))
    return subprocess.run(list(map(str, cmd)), check=check)


def remove_tree(path, attempts=5, delay=0.5):
    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(delay * attempt)


def clean_build_dirs():
    for path in (BUILD_DIR, SPEC_DIR, DIST_DIR):
        remove_tree(path)


def ensure_venv():
    ensure_python_310_venv(VENV_PYTHON)


def install_pyinstaller():
    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([VENV_PYTHON, "-m", "pip", "install", "pyinstaller>=6.15,<7"])


def build_exe():
    cmd = [
        VENV_PYTHON,
        "-m",
        "PyInstaller",
        "--specpath",
        SPEC_DIR,
        "--noconfirm",
        "--onedir",
        "--paths",
        SOURCE_ROOT,
        "--paths",
        CANONICAL_SOURCE_ROOT,
        "--hidden-import",
        "utils",
        "--hidden-import",
        "server_config",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "_tkinter",
        f"--icon={ICON}",
        "--add-data",
        f"{BASE_DIR / 'index.html'};.",
        "--noconsole",
        "--clean",
        "--name",
        APP_NAME,
        "--distpath",
        DIST_DIR,
        "--workpath",
        BUILD_DIR,
        ENTRY_PY,
    ]
    run(cmd)


def live_instance_count():
    try:
        return sum(
            1
            for path in resolve_app_path("admin", "instances").iterdir()
            if path.is_file() and path.suffix.lower() == ".json"
        )
    except FileNotFoundError:
        return 0


def _wait_until_stopped(deadline):
    while live_instance_count():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)
    return True


def request_http_shutdown():
    """Ask the local server to close through the endpoint it already serves.

    The kill switch only reaches a build that polls it, and the instance being
    replaced is by definition the older one -- including the build that predates
    the switch entirely. This endpoint has been there far longer, so it is what
    makes the first deploy of the switch itself able to stop its predecessor.
    """

    request = Request(f"http://127.0.0.1:{ADMIN_PORT}/api/shutdown", data=b"", method="POST")
    try:
        with urlopen(request, timeout=2):
            return True
    except (OSError, URLError):
        return False


def wait_for_shutdown():
    if _wait_until_stopped(time.monotonic() + KILL_SWITCH_GRACE_SECONDS):
        return
    print(f"\n>>> Admin Control has not honoured {KILL_ALL_KEY}; asking it to close")
    request_http_shutdown()
    if not _wait_until_stopped(time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS):
        raise RuntimeError(
            "The live Admin Control did not stop; close it on the server and deploy again."
        )


def start_admin():
    if live_instance_count():
        return
    executable = DEPLOY_APP_DIR / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Deployed Admin Control not found: {executable}")
    # Headless: the deploy restores the local server, not somebody's browser.
    subprocess.Popen(
        [str(executable), "--no-browser", "--no-splash"],
        cwd=str(executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@contextmanager
def admin_stopped():
    """Stop the live Admin Control so its deployed folder can be renamed.

    Admin Control serves a local HTTP port and holds its own folder open, so a
    swap while it runs fails with WinError 32 no matter how often it retries.
    Unlike the Engine, Bridge and Gateway nothing supervises it, so this restores
    the switch and relaunches the server itself.
    """

    previous = get_config_value(KILL_ALL_KEY, False)
    set_config_value(KILL_ALL_KEY, True)
    try:
        wait_for_shutdown()
        yield
    finally:
        set_config_value(KILL_ALL_KEY, previous)
        if not previous:
            if DEPLOY_ROOT_IS_LOCAL:
                start_admin()
            else:
                # Launching the deployed executable here would host the server's
                # Admin Control on the build machine instead.
                print(
                    f"\n>>> {DEPLOY_ROOT} is not a local disk; start Admin Control "
                    "on the server when it is next needed."
                )


def deploy_exe():
    # Staged while the server is still live, because only the rename below needs
    # the stopped window and copying the build takes far longer than the swap.
    stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
    with admin_stopped():
        swap_deploy(APPS_DIR, APP_NAME)


def main():
    clean_build_dirs()
    ensure_venv()
    install_pyinstaller()
    build_exe()
    if not STAGE_ONLY:
        deploy_exe()
    output_dir = STAGED_APP_DIR if STAGE_ONLY else DEPLOY_APP_DIR
    print(f"\nBuild finished: {output_dir / f'{APP_NAME}.exe'}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: Command failed with exit code {exc.returncode}")
        sys.exit(exc.returncode)
