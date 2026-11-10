"""Start and stop an Arco Server whose folder is on a fixed disk of this PC.

Starting launches the server's Orchestrator, which starts its Engines and its
Gateway; stopping sets the stop switches (``apps.<role>.kill_all`` in
``<root>\\config\\config.json``) so each component exits by itself and removes
its heartbeat. No process is ever killed, so nothing on another server root is
touched. Production is refused: its switches stop it for every user, and it is
managed from Admin Control on the Server PC.

``tools/local_server.py`` and the desktop app's Server tab both act through
this module; whether a component runs is judged by
``arcrho_server_component_status``.
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from arcrho_api.config import (
    DEFAULT_WORKSPACE_ROOT,
    GATEWAY_CONFIG_ENV,
    GATEWAY_URL_ENV,
    SERVER_CONFIG_RELATIVE_PATH,
    SERVER_ROOT_ENV_VARS,
)
from arcrho_api.exceptions import ArcRhoApiError
from arcrho_api.io import read_json, write_json_atomic
from arcrho_server_component_status import is_on_local_fixed_disk, list_instances


# The roles the Orchestrator supervises; the Bridge needs ResQ and is never
# started on a server folder on a Client PC.
SUPERVISED_ROLES = ("orchestrator", "engine", "gateway")
# Pinned to server-components' component table by
# python-api/tests/test_server_control.py.
ORCHESTRATOR_APP_NAME = "Arco Orchestrator"
# Every override that could point a child process at another root. The caller
# sets the one it means; nothing inherited survives, so an app session launched
# against one server can never hand its Gateway credential or root to another.
ROOT_ENV_VARS = (
    *SERVER_ROOT_ENV_VARS,
    GATEWAY_CONFIG_ENV,
    GATEWAY_URL_ENV,
    "ARCRHO_ROOT",
    "ADAS_ROOT",
    "ARCRHO_DEPLOY_ROOT",
)
# Longer than the slowest role's stale threshold, so a heartbeat a component
# left behind has gone stale by the end of the wait.
STOP_WAIT_SECONDS = 75.0
PRODUCTION_REFUSAL = "The production server is started and stopped from Admin Control on the Server PC."
NOT_LOCAL_REFUSAL = "Only a server whose folder is on a fixed disk of this PC can be started or stopped here."


class ServerControlError(RuntimeError):
    pass


def _same_folder(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def control_refusal(root: str | os.PathLike[str], production_root: str | os.PathLike[str] = DEFAULT_WORKSPACE_ROOT) -> str:
    """Why this PC may not start or stop the server at ``root``; ``""`` when it may."""

    if _same_folder(root, production_root):
        return PRODUCTION_REFUSAL
    if not is_on_local_fixed_disk(root):
        return NOT_LOCAL_REFUSAL
    if _same_folder(Path(root).resolve(), Path(production_root).resolve()):
        return PRODUCTION_REFUSAL
    return ""


def require_local_root(root: str | os.PathLike[str], production_root: str | os.PathLike[str] = DEFAULT_WORKSPACE_ROOT) -> Path:
    """Return ``root`` resolved, or refuse a folder that could be shared."""

    refusal = control_refusal(root, production_root)
    if refusal:
        raise ServerControlError(f"{os.fspath(root)}: {refusal}")
    return Path(root).expanduser().resolve()


def child_env(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in ROOT_ENV_VARS}
    env.update(extra)
    return env


def orchestrator_exe(root: str | os.PathLike[str]) -> Path:
    return Path(root) / "apps" / ORCHESTRATOR_APP_NAME / f"{ORCHESTRATOR_APP_NAME}.exe"


def set_stop_switches(root: str | os.PathLike[str], on: bool, roles: tuple[str, ...] = SUPERVISED_ROLES) -> None:
    path = Path(root) / SERVER_CONFIG_RELATIVE_PATH
    payload = read_json(path) if path.is_file() else {}
    apps = payload.setdefault("apps", {})
    for role in roles:
        apps.setdefault(role, {})["kill_all"] = on
    # Every running component polls this file, and a reader holding it open
    # fails the atomic replace for a moment, so the write is retried briefly.
    for attempt in range(5):
        try:
            write_json_atomic(path, payload)
            return
        except ArcRhoApiError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))


def running_roles(root: str | os.PathLike[str], *, now: datetime | None = None) -> list[str]:
    """The supervised roles with at least one heartbeat that is not stale."""

    active = {row["role"] for row in list_instances(root, now=now) if row["status"] == "Active"}
    return [role for role in SUPERVISED_ROLES if role in active]


def start_server(root: str | os.PathLike[str]) -> bool:
    """Clear the stop switches and launch the Orchestrator unless one is running; True when launched."""

    exe = orchestrator_exe(root)
    if not exe.is_file():
        raise ServerControlError(f"{exe} is missing.")
    set_stop_switches(root, False)
    if "orchestrator" in running_roles(root):
        return False
    # Launched through "start" so the Orchestrator is not a child of the
    # caller: the desktop app ends its app server with a process-tree kill,
    # which would otherwise take this server down with it.
    subprocess.Popen(
        f'start "" "{exe}"',
        shell=True,
        cwd=str(exe.parent),
        env=child_env(ARCRHO_ROOT=str(root)),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return True


def stop_server(root: str | os.PathLike[str], wait_seconds: float = STOP_WAIT_SECONDS) -> bool:
    """Set the stop switches and wait for the supervised heartbeats to go; True once none is live."""

    set_stop_switches(root, True)
    deadline = time.monotonic() + wait_seconds
    while True:
        if not running_roles(root):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1.0)
