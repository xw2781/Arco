import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
import sys
import shutil
import os

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
REPOSITORY_ROOT = PROJECT_ROOT.parent
SOURCE_ROOT = BASE_DIR.parent
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
for path in (SOURCE_ROOT, CANONICAL_SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_engine.bundled_sources import ENGINE_BUNDLED_SOURCES
from arcrho_engine_save_contract import SAVE_JOB_KINDS
from arcrho_data_processing_rules_job_contract import (
    DATA_PROCESSING_RULES_JOB_SERVICE_MODULES,
)
from arcrho_dataset_types_change_contract import DATASET_TYPES_CHANGE_SERVICE_MODULES
from arcrho_project_dates_job_contract import PROJECT_DATES_JOB_SERVICE_MODULES
from arcrho_source_refresh_contract import SOURCE_REFRESH_SERVICE_MODULES
from build_runtime import ensure_python_310_venv, stage_deploy, swap_deploy
from utils import (
    component_app_name,
    get_config_value,
    resolve_app_path,
    set_config_value,
)

BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
DEPLOY_ROOT = Path(os.environ.get("ARCRHO_DEPLOY_ROOT", r"E:\ArcRho Server"))
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"

ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("engine")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Engine.ico"

BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME

# The orchestrator relaunches Engine instances up to apps.orchestrator.
# max_workers, so a deploy that only stopped the running processes would race
# fresh instances that re-lock the exe part way through the copy. An instance
# finishing a long durable job (propagation, duplication) delays its shutdown,
# so the wait is longer than the Bridge's.
ENGINE_KILL_ALL_KEY = "apps.engine.kill_all"
ENGINE_SHUTDOWN_TIMEOUT_SECONDS = 180
ENGINE_SHUTDOWN_POLL_SECONDS = 1

for path in (BUILD_DIR, SPEC_DIR, DIST_DIR):
    try:
        shutil.rmtree(path)
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


def _hosted_service_modules():
    """Every ``app_server.services`` module the frozen Engine must import.

    The hosted-save kinds come from the canonical ``SAVE_JOB_KINDS`` registry,
    the source-refresh services from ``SOURCE_REFRESH_SERVICE_MODULES`` and the
    dataset-type change services from ``DATASET_TYPES_CHANGE_SERVICE_MODULES``,
    so registering a new kind or step is enough for its module to be probed and
    bundled; the rest are the walk and legacy calculation executors.
    """

    modules = {module for module, _function in SAVE_JOB_KINDS.values()}
    # dataset_link_refresh_service is the walk's link-driven dataset
    # evaluator, imported lazily inside calculated_dataset_service.
    modules.update({
        "calculated_dataset_service",
        "dataset_link_refresh_service",
        "arcrho_runtime_service",
    })
    modules.update(SOURCE_REFRESH_SERVICE_MODULES)
    modules.update(DATASET_TYPES_CHANGE_SERVICE_MODULES)
    modules.update(DATA_PROCESSING_RULES_JOB_SERVICE_MODULES)
    modules.update(PROJECT_DATES_JOB_SERVICE_MODULES)
    return sorted(modules)


def validate_canonical_runtime_environment():
    """Fail the build if the bundled app_server import graph is incomplete."""

    import_paths = [str(CANONICAL_SOURCE_ROOT), str(REPOSITORY_ROOT / "frontend")]
    probe = (
        "import sys; "
        f"sys.path[:0] = {import_paths!r}; "
        + "".join(
            f"from app_server.services import {module}; "
            for module in _hosted_service_modules()
        )
        + "import arcrho_dependent_propagation_contract; "
        "import arcrho_engine_save_contract; "
        "import arcrho_source_refresh_contract; "
        "import arcrho_dataset_types_change_contract; "
        "import arcrho_data_processing_rules_job_contract; "
        "import arcrho_project_dates_job_contract; "
        "import arcrho_api.period_reshape; "
        "import arcrho_reserving_class_type_contract; "
        "import arcrho_engine_job_lease"
    )
    print("\n>>> Validating canonical dependent-propagation dependencies")
    run([VENV_PYTHON, "-c", probe])


def build_exe():
    for module_name in (
        "arcrho_project_duplication_contract.py",
        "arcrho_dependent_propagation_contract.py",
        "arcrho_engine_save_contract.py",
        "arcrho_source_refresh_contract.py",
        "arcrho_dataset_types_change_contract.py",
        "arcrho_data_processing_rules_job_contract.py",
        "arcrho_project_dates_job_contract.py",
        "arcrho_reserving_class_type_contract.py",
        "arcrho_engine_job_lease.py",
    ):
        contract_module = CANONICAL_SOURCE_ROOT / module_name
        if not contract_module.is_file():
            raise FileNotFoundError(
                f"Canonical contract module not found: {contract_module}"
            )
    for bundled in ENGINE_BUNDLED_SOURCES:
        if not bundled.source.is_dir():
            raise FileNotFoundError(
                f"Canonical propagation bundle source was not found: {bundled.source}"
            )

    cmd = [
        VENV_PYTHON,
        "-m", "PyInstaller",
        "--specpath", SPEC_DIR,
        "--noconfirm",
        "--onedir",
        "--paths", SOURCE_ROOT,
        "--paths", CANONICAL_SOURCE_ROOT,
        "--paths", REPOSITORY_ROOT / "frontend",
        "--hidden-import", "utils",
        "--hidden-import", "server_config",
        "--hidden-import", "arcrho_project_duplication_contract",
        "--hidden-import", "arcrho_dependent_propagation_contract",
        "--hidden-import", "arcrho_engine_save_contract",
        "--hidden-import", "arcrho_source_refresh_contract",
        "--hidden-import", "arcrho_dataset_types_change_contract",
        "--hidden-import", "arcrho_data_processing_rules_job_contract",
        "--hidden-import", "arcrho_project_dates_job_contract",
        "--hidden-import", "arcrho_reserving_class_type_contract",
        "--hidden-import", "arcrho_engine_job_lease",
        *[
            argument
            for module in _hosted_service_modules()
            for argument in ("--hidden-import", f"app_server.services.{module}")
        ],
        f"--icon={ICON}",
        "--add-data", f"{ICON};.",
        *[
            argument
            for bundled in ENGINE_BUNDLED_SOURCES
            for argument in ("--add-data", f"{bundled.source};{bundled.target}")
        ],
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


def live_engine_instance_count():
    try:
        entries = list(resolve_app_path("engine", "instances").iterdir())
    except FileNotFoundError:
        return 0
    return sum(1 for entry in entries if entry.is_file())


def wait_for_engine_shutdown():
    deadline = time.monotonic() + ENGINE_SHUTDOWN_TIMEOUT_SECONDS
    while True:
        remaining = live_engine_instance_count()
        if not remaining:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"The live ArcRho Engine did not stop within "
                f"{ENGINE_SHUTDOWN_TIMEOUT_SECONDS}s ({remaining} heartbeat(s) still "
                "present). Deploy aborted; the deployed Engine was left untouched."
            )
        time.sleep(ENGINE_SHUTDOWN_POLL_SECONDS)


@contextmanager
def engines_stopped():
    """Hold live Engine instances down for the deploy window, then release.

    Setting the shared kill switch makes every instance exit on its next
    heartbeat cycle and keeps the orchestrator from launching replacements;
    restoring the previous value lets the orchestrator bring the new build
    back up to its configured worker count.
    """

    previous = get_config_value(ENGINE_KILL_ALL_KEY, False)
    print(f"\n>>> Stopping live ArcRho Engine instances ({ENGINE_KILL_ALL_KEY} = True)")
    set_config_value(ENGINE_KILL_ALL_KEY, True)
    try:
        wait_for_engine_shutdown()
        yield
    finally:
        print(f"\n>>> Releasing the ArcRho Engine ({ENGINE_KILL_ALL_KEY} = {previous})")
        set_config_value(ENGINE_KILL_ALL_KEY, previous)


def main():
    ensure_venv()
    ensure_venv_python()
    install_requirements()
    validate_canonical_runtime_environment()
    build_exe()
    if not STAGE_ONLY:
        stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
        with engines_stopped():
            swap_deploy(APPS_DIR, APP_NAME)

    output_dir = STAGED_APP_DIR if STAGE_ONLY else DEPLOY_APP_DIR
    print(f"\nBuild finished: {output_dir / f'{APP_NAME}.exe'}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed with exit code {e.returncode}")
        sys.exit(e.returncode)
