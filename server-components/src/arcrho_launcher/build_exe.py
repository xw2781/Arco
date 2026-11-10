import subprocess
from pathlib import Path
import sys
import shutil
import os

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
REPOSITORY_ROOT = PROJECT_ROOT.parent
SOURCE_ROOT = BASE_DIR.parent
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_runtime import (
    copy_tree_delta,
    ensure_python_310_venv,
    stage_deploy,
    swap_deploy,
)
from utils import DEFAULT_DEPLOY_ROOT, component_app_name

BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
DEPLOY_ROOT = DEFAULT_DEPLOY_ROOT
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"

ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("launcher")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Launcher.ico"

BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME

for _folder in (BUILD_DIR, SPEC_DIR, DIST_DIR):
    try:
        shutil.rmtree(_folder)
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
        # "--noconsole",
        "--clean",
        "--name", APP_NAME,
        "--distpath", DIST_DIR,
        "--workpath", BUILD_DIR,
        ENTRY_PY,
    ]

    print("\nRunning PyInstaller:")
    print(" ".join(map(str, cmd)))
    run(cmd)


def deploy_exe():
    """Rotate the staged build into place, with a content sync fallback when
    the folder itself is pinned by another session.

    Apps started by pre-2026-08 launchers inherited the launcher folder as
    their working directory, and any live process from another user session
    keeps that folder pinned: it cannot be removed or renamed, but the files
    inside it can still be replaced because the launcher only runs briefly.
    """

    slot = stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
    try:
        swap_deploy(APPS_DIR, APP_NAME)
    except PermissionError:
        # The swap restored the pinned folder, so the new build is still in the
        # slot. Mirroring it in replaces the files without touching the folder.
        print(
            f"\n>>> {DEPLOY_APP_DIR} is pinned by a live process; "
            "replacing its contents in place."
        )
        copy_tree_delta(slot, DEPLOY_APP_DIR)


def main():
    ensure_venv()
    ensure_venv_python()
    install_requirements()
    build_exe()
    if not STAGE_ONLY:
        deploy_exe()

    exe_path = (STAGED_APP_DIR if STAGE_ONLY else DEPLOY_APP_DIR) / f"{APP_NAME}.exe"
    print("\nBuild finished!")
    print(f"EXE location: {exe_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
