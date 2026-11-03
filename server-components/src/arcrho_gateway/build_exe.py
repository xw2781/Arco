"""Build, atomically deploy, and restart ArcRho Gateway."""

from __future__ import annotations

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
CANONICAL_SOURCE_ROOT = REPOSITORY_ROOT / "python-api" / "src"
for path in (PROJECT_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_engine.bundled_sources import ENGINE_BUNDLED_SOURCES
from arcrho_gateway.publish_guide import publish_guide
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

from server_config import ensure_server_id  # noqa: E402
from utils import (  # noqa: E402
    component_app_name,
    get_config_value,
    get_project_root,
    resolve_app_path,
    set_config_value,
)

if str(CANONICAL_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANONICAL_SOURCE_ROOT))
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS  # noqa: E402
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS  # noqa: E402
from arcrho_gateway.engine_calculations import EXECUTOR_MODULES as CALCULATION_EXECUTOR_MODULES  # noqa: E402


BUILD_ROOT = PROJECT_ROOT / "builds" / BASE_DIR.name
BUILD_CACHE_ROOT = BUILD_ROOT / "cache"
DEPLOY_ROOT = get_project_root()
DEPLOY_ROOT_IS_LOCAL = is_local_fixed_path(DEPLOY_ROOT)
APPS_DIR = DEPLOY_ROOT / "apps"
VENV_PYTHON = PROJECT_ROOT / "venvs" / BASE_DIR.name / "Scripts" / "python.exe"
REQ_FILE = BASE_DIR / "requirements.txt"
ENTRY_PY = BASE_DIR / "main.py"
APP_NAME = component_app_name("gateway")
ICON = PROJECT_ROOT.parent / "assets" / "icons" / "ArcRho Orchestrator.ico"
STAGE_ONLY = os.environ.get("ARCRHO_STAGE_ONLY", "").strip() == "1"
BUILD_DIR = BUILD_ROOT / "build"
SPEC_DIR = BUILD_ROOT / "spec"
DIST_DIR = BUILD_ROOT / "dist"
STAGED_APP_DIR = DIST_DIR / APP_NAME
DEPLOY_APP_DIR = APPS_DIR / APP_NAME
KILL_ALL_KEY = "apps.gateway.kill_all"
SHUTDOWN_TIMEOUT_SECONDS = 30

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


def _remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass


def live_instance_count() -> int:
    try:
        return sum(
            1
            for path in resolve_app_path("gateway", "instances").iterdir()
            if path.is_file() and path.suffix.lower() == ".json"
        )
    except FileNotFoundError:
        return 0


def wait_for_shutdown() -> None:
    deadline = time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
    while live_instance_count():
        if time.monotonic() >= deadline:
            raise RuntimeError("The live Gateway did not stop; deploy aborted.")
        time.sleep(0.5)


def start_gateway() -> None:
    if live_instance_count():
        return
    executable = DEPLOY_APP_DIR / f"{APP_NAME}.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Deployed Gateway not found: {executable}")
    subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@contextmanager
def gateway_stopped():
    previous = get_config_value(KILL_ALL_KEY, False)
    set_config_value(KILL_ALL_KEY, True)
    try:
        wait_for_shutdown()
        # The Gateway reports this id from its capabilities and reads it once
        # as it starts, so it is written while the Gateway is down.
        ensure_server_id(DEPLOY_ROOT)
        yield
    finally:
        set_config_value(KILL_ALL_KEY, previous)
        if not previous:
            if DEPLOY_ROOT_IS_LOCAL:
                start_gateway()
            else:
                # Running the deployed executable here would host the server's
                # Gateway on the build machine. Clearing the kill switch is
                # enough: the server's own Orchestrator restores it.
                print(
                    f"\n>>> {DEPLOY_ROOT} is not a local disk; the server's "
                    "Orchestrator restarts the Gateway."
                )


def _hosted_service_modules() -> list[str]:
    """Every ``app_server.services`` module the gateway executes in-process."""

    modules = {spec.module for spec in WORKSPACE_READ_KINDS.values()}
    modules.update(spec.module for spec in WORKSPACE_MUTATION_KINDS.values())
    modules.update(CALCULATION_EXECUTOR_MODULES)
    return sorted(modules)


def validate_canonical_runtime_environment() -> None:
    """Fail the build if the bundled app_server import graph is incomplete.

    Every registered workspace read and mutation is imported the way the
    running gateway imports it, so a service that gained a dependency the venv
    lacks stops the build here instead of failing the first request on the
    server.
    """

    import_paths = [str(CANONICAL_SOURCE_ROOT), str(REPOSITORY_ROOT / "frontend")]
    imports = "; ".join(
        f"from app_server.services import {module}" for module in _hosted_service_modules()
    )
    probe = f"import sys; sys.path[:0] = {import_paths!r}; {imports}"
    print("\n>>> Validating canonical hosted-operation dependencies")
    run([VENV_PYTHON, "-c", probe])


def build_exe() -> None:
    for path in (BUILD_DIR, SPEC_DIR, DIST_DIR):
        _remove_tree(path)
    for bundled in ENGINE_BUNDLED_SOURCES:
        if not bundled.source.is_dir():
            raise FileNotFoundError(
                f"Canonical bundle source was not found: {bundled.source}"
            )
    ensure_python_310_venv(VENV_PYTHON)
    run([VENV_PYTHON, "-m", "pip", "install", "-r", REQ_FILE])
    validate_canonical_runtime_environment()
    # The gateway executes registered app_server reads in-process, so it
    # freezes the same canonical trees the Engine does and resolves them at
    # runtime through the Engine's configure_canonical_runtime.
    service_hidden_imports = [
        argument
        for module in _hosted_service_modules()
        for argument in ("--hidden-import", f"app_server.services.{module}")
    ]
    run(
        [
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
            "--paths",
            REPOSITORY_ROOT / "frontend",
            "--hidden-import",
            "utils",
            "--hidden-import",
            "server_config",
            "--hidden-import",
            "arcrho_engine_save_contract",
            "--hidden-import",
            "arcrho_hosted_save_http_contract",
            "--hidden-import",
            "arcrho_dependent_propagation_contract",
            "--hidden-import",
            "arcrho_workspace_read_contract",
            "--hidden-import",
            "arcrho_workspace_mutation_contract",
            "--hidden-import",
            "arcrho_source_refresh_contract",
            "--hidden-import",
            "arcrho_dataset_types_change_contract",
            "--hidden-import",
            "arcrho_data_processing_rules_job_contract",
            "--hidden-import",
            "arcrho_project_dates_job_contract",
            "--hidden-import",
            "arcrho_engine_calculation_contract",
            "--hidden-import",
            "arcrho_project_duplication_contract",
            "--hidden-import",
            "arcrho_engine_job_lease",
            "--hidden-import",
            "arcrho_bridge.bundled_sources",
            "--hidden-import",
            "arcrho_engine.bundled_sources",
            "--hidden-import",
            "arcrho_engine.project_duplication",
            "--hidden-import",
            "arcrho_engine.dependent_propagation",
            "--hidden-import",
            "arcrho_gateway.workspace_reads",
            "--hidden-import",
            "arcrho_gateway.engine_calculations",
            "--hidden-import",
            "arcrho_gateway.workspace_mutations",
            "--hidden-import",
            "arcrho_gateway.receipts",
            "--hidden-import",
            "arcrho_gateway.enrollment",
            *service_hidden_imports,
            *[
                argument
                for bundled in ENGINE_BUNDLED_SOURCES
                for argument in ("--add-data", f"{bundled.source};{bundled.target}")
            ],
            f"--icon={ICON}",
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
    )


def main() -> int:
    build_exe()
    if not STAGE_ONLY:
        # Staging runs while the Gateway is still serving; only the rename
        # rotation below needs the stopped window, and that takes seconds.
        stage_deploy(STAGED_APP_DIR, APPS_DIR, APP_NAME)
        publish_guide(DEPLOY_ROOT)
        with gateway_stopped():
            swap_deploy(APPS_DIR, APP_NAME)
    output = STAGED_APP_DIR if STAGE_ONLY else DEPLOY_APP_DIR
    print(f"\nBuild finished: {output / f'{APP_NAME}.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
