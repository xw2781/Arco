"""Build and deploy the Arco Credential helper.

Modelled on the Gateway's build script, minus the stopped window: nothing
supervises this helper, so there is no instance to stop before the swap. A
client may still be running it for the second it takes, which is the
Launcher's situation exactly -- no process to stop, so a rename Windows
refuses is answered by replacing the folder's contents in place.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
REPOSITORY_ROOT = PROJECT_ROOT.parent
SOURCE_ROOT = BASE_DIR.parent
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_runtime import (  # noqa: E402
    align_workspace_root_env,
    copy_tree_delta,
    ensure_python_310_venv,
    stage_deploy,
    swap_deploy,
)

# Must run before utils is imported: utils resolves the workspace root once at
# import time, and this build deploys into that workspace.
align_workspace_root_env()

from utils import component_app_name, get_project_root  # noqa: E402


BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
BUILD_CACHE_ROOT = BUILD_ROOT / "cache"
DEPLOY_ROOT = get_project_root()
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("credential")
ICON = REPOSITORY_ROOT / "assets" / "icons" / "ArcRho Launcher.ico"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"
BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME

for name, folder in {
    "TEMP": BUILD_CACHE_ROOT / "tmp",
    "TMP": BUILD_CACHE_ROOT / "tmp",
    "PIP_CACHE_DIR": BUILD_CACHE_ROOT / "pip",
    "PYINSTALLER_CONFIG_DIR": BUILD_CACHE_ROOT / "pyinstaller",
}.items():
    folder.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(folder)


def run(command: list[object]) -> None:
    print("\n>>>", " ".join(map(str, command)))
    subprocess.run(list(map(str, command)), check=True)


def build_exe() -> None:
    for path in (BUILD_DIR, SPEC_DIR, DIST_DIR):
        shutil.rmtree(path, ignore_errors=True)
    ensure_python_310_venv(VENV_PYTHON)
    run([VENV_PYTHON, "-m", "pip", "install", "-r", REQ_FILE])
    run(
        [
            VENV_PYTHON,
            "-m",
            "PyInstaller",
            "--specpath",
            SPEC_DIR,
            "--noconfirm",
            "--onedir",
            "--console",
            "--paths",
            CANONICAL_SOURCE_ROOT,
            "--hidden-import",
            "arcrho_api.config",
            "--hidden-import",
            "arcrho_api.hosted_save_enrollment",
            "--hidden-import",
            "arcrho_api.io",
            "--hidden-import",
            "arcrho_hosted_save_http_contract",
            "--hidden-import",
            "sspi",
            f"--icon={ICON}",
            "--clean",
            "--name",
            APP_NAME,
            "--distpath",
            DIST_DIR,
            "--workpath",
            BUILD_DIR,
            ENTRY_PY,
        ]
    )


def deploy_exe() -> None:
    slot = stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
    try:
        swap_deploy(APPS_DIR, APP_NAME)
    except PermissionError:
        # A client is running the helper right now. The swap restored the
        # pinned folder, so the new build is still in the slot; mirroring it
        # in replaces the files without touching the folder.
        print(
            f"\n>>> {DEPLOY_APP_DIR} is pinned by a live process; "
            "replacing its contents in place."
        )
        copy_tree_delta(slot, DEPLOY_APP_DIR)


def main() -> int:
    build_exe()
    if not STAGE_ONLY:
        deploy_exe()
    output = STAGED_APP_DIR if STAGE_ONLY else DEPLOY_APP_DIR
    print(f"\nBuild finished: {output / f'{APP_NAME}.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
