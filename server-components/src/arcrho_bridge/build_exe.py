import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
SOURCE_ROOT = BASE_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_bridge.bundled_sources import (
    BUNDLED_SOURCES,
    CANONICAL_HIDDEN_IMPORTS,
    CANONICAL_MODULE_ROOT,
)
from build_runtime import ensure_python_310_venv, stage_deploy, swap_deploy
from utils import (
    DEFAULT_DEPLOY_ROOT,
    component_app_name,
    get_config_value,
    resolve_app_path,
    set_config_value,
)

BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
DEPLOY_ROOT = DEFAULT_DEPLOY_ROOT
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"

ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("bridge")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Engine.ico"
RESQ_IMPORT_CONTRACT_FILE = BASE_DIR / "resq_reserving_class_import_contract.json"
RESQ_SYNC_CONTRACT_FILE = BASE_DIR / "resq_reserving_class_sync_contract.json"
RESQ_REVIEW_CONTRACT_FILE = BASE_DIR / "resq_reserving_class_review_contract.json"
RESQ_CONTRACT_BUNDLE_TARGET = "arcrho_bridge"
RESQ_CONTRACT_FILES = (
    RESQ_IMPORT_CONTRACT_FILE,
    RESQ_SYNC_CONTRACT_FILE,
    RESQ_REVIEW_CONTRACT_FILE,
)

BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME

# The orchestrator relaunches the Bridge every few seconds, so a deploy that
# only stopped the running processes would race a fresh supervisor that
# re-locks the exe part way through the copy.
BRIDGE_KILL_ALL_KEY = "apps.bridge.kill_all"
BRIDGE_SHUTDOWN_TIMEOUT_SECONDS = 60
BRIDGE_SHUTDOWN_POLL_SECONDS = 1


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

    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([VENV_PYTHON, "-m", "pip", "install", "-r", REQ_FILE])


def validate_resq_import_environment():
    """Fail the build if the canonical migration/provenance imports are incomplete."""

    import_paths = tuple(
        dict.fromkeys(
            (
                *(bundled.import_root for bundled in BUNDLED_SOURCES),
                CANONICAL_MODULE_ROOT,
            )
        )
    )
    probe = (
        "import sys; "
        f"sys.path[:0] = {repr([str(path) for path in import_paths])}; "
        "from resq_migration.engine import get_engine_processing_provenance; "
        "from resq_migration.sync_session import build_runtime; "
        "from app_server.services.data_processing_rules_service import "
        "get_processing_provenance; "
        + "; ".join(f"import {name}" for name in CANONICAL_HIDDEN_IMPORTS)
    )
    print("\n>>> Validating canonical ResQ import dependencies")
    run([VENV_PYTHON, "-c", probe])


def build_exe():
    for bundled in BUNDLED_SOURCES:
        if not bundled.source.exists():
            raise FileNotFoundError(
                f"Canonical ResQ import bundle source was not found: {bundled.source}"
            )
    for contract_file in RESQ_CONTRACT_FILES:
        if not contract_file.is_file():
            raise FileNotFoundError(
                f"ResQ reserving-class queue contract was not found: {contract_file}"
            )
    for module_name in CANONICAL_HIDDEN_IMPORTS:
        canonical_module = CANONICAL_MODULE_ROOT / f"{module_name}.py"
        if not canonical_module.is_file():
            raise FileNotFoundError(
                f"Canonical Bridge module not found: {canonical_module}"
            )
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
        REPO_ROOT / "frontend",
        "--paths",
        CANONICAL_MODULE_ROOT,
        *[
            argument
            for name in CANONICAL_HIDDEN_IMPORTS
            for argument in ("--hidden-import", name)
        ],
        "--hidden-import",
        "utils",
        "--hidden-import",
        "server_config",
        "--hidden-import",
        "win32timezone",
        "--hidden-import",
        "app_server.services.data_processing_rules_service",
        "--hidden-import",
        "app_server.services.data_processing_values_service",
        "--hidden-import",
        "app_server.services.audit_service",
        "--hidden-import",
        "arcrho_bridge.resq_import_runner",
        "--hidden-import",
        "arcrho_bridge.resq_sync_runner",
        "--hidden-import",
        "arcrho_bridge.resq_review_runner",
        # The review writes its workbook from the bundled validation module,
        # which PyInstaller carries as data and therefore never analyses, so
        # its Excel writer has to be named here.
        "--hidden-import",
        "openpyxl",
        f"--icon={ICON}",
        "--add-data",
        f"{ICON};.",
        *[
            argument
            for bundled in BUNDLED_SOURCES
            for argument in ("--add-data", f"{bundled.source};{bundled.target}")
        ],
        *[
            argument
            for contract_file in RESQ_CONTRACT_FILES
            for argument in ("--add-data", f"{contract_file};{RESQ_CONTRACT_BUNDLE_TARGET}")
        ],
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

    print("\nRunning PyInstaller:")
    print(" ".join(map(str, cmd)))
    run(cmd)


def live_bridge_instance_count():
    total = 0
    for role in ("bridge", "bridge_worker"):
        try:
            entries = list(resolve_app_path(role, "instances").iterdir())
        except FileNotFoundError:
            continue
        total += sum(1 for entry in entries if entry.is_file())
    return total


def wait_for_bridge_shutdown():
    deadline = time.monotonic() + BRIDGE_SHUTDOWN_TIMEOUT_SECONDS
    while True:
        remaining = live_bridge_instance_count()
        if not remaining:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"The live Arco Bridge did not stop within "
                f"{BRIDGE_SHUTDOWN_TIMEOUT_SECONDS}s ({remaining} heartbeat(s) still "
                "present). Deploy aborted; the deployed Bridge was left untouched."
            )
        time.sleep(BRIDGE_SHUTDOWN_POLL_SECONDS)


@contextmanager
def bridge_stopped():
    """Hold the live Bridge down for the deploy window, then let it return.

    Stopping the supervisor and worker by hand is not enough: the orchestrator
    relaunches the Bridge on its own loop and would re-lock the exe mid-deploy.
    Setting the shared kill switch is what makes it stay down, and restoring the
    previous value is what lets the orchestrator bring the new build back up.
    """

    previous = get_config_value(BRIDGE_KILL_ALL_KEY, False)
    print(f"\n>>> Stopping the live Arco Bridge ({BRIDGE_KILL_ALL_KEY} = True)")
    set_config_value(BRIDGE_KILL_ALL_KEY, True)
    try:
        wait_for_bridge_shutdown()
        yield
    finally:
        print(f"\n>>> Releasing the Arco Bridge ({BRIDGE_KILL_ALL_KEY} = {previous})")
        set_config_value(BRIDGE_KILL_ALL_KEY, previous)


def main():
    clean_build_dirs()
    ensure_venv()
    ensure_venv_python()
    install_requirements()
    validate_resq_import_environment()
    build_exe()
    if STAGE_ONLY:
        exe_path = STAGED_APP_DIR / f"{APP_NAME}.exe"
    else:
        stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
        with bridge_stopped():
            swap_deploy(APPS_DIR, APP_NAME)
        exe_path = DEPLOY_APP_DIR / f"{APP_NAME}.exe"
    print(f"\nBuild finished: {exe_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: Command failed with exit code {exc.returncode}")
        sys.exit(exc.returncode)
