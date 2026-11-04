#!/usr/bin/env python3
r"""Run a private Arco Server on this PC for testing, next to production.

The production server root (``E:\ArcRho Server``, the Server PC's share) is
shared by every user. This tool keeps a second, independent root on a local
fixed disk -- ``C:\Arco Server`` by default, ``E:\XWSpace\Arco Server`` on the
Server PC -- so server-component changes can
be deployed and exercised here before anything reaches other users. See
``docs/plans/completed/local_server_root_and_server_switcher.md``.

Nothing here writes to the production root. ``init`` and ``copy-project`` read
from it; every other command touches only the local root, and every command
refuses a root that is not on a local fixed disk or that is the production root.

Usage
-----
    py -3.10 tools/local_server.py init
    py -3.10 tools/local_server.py copy-project [NAME] [--overwrite]
    py -3.10 tools/local_server.py deploy [engine] [gateway] [orchestrator]
    py -3.10 tools/local_server.py start | stop | status
    py -3.10 tools/local_server.py launch-app

``init`` creates the folders and ``config`` files, installs a prebuilt
Orchestrator copied from production, binds the local Gateway to this PC only,
and writes this user's credential for it to a separate file, so the production
credential in ``%APPDATA%\ArcRho\arcrho_gateway.json`` is never touched.
``deploy`` builds the named components from this working tree into the local
root. ``launch-app`` starts the dev-mode desktop app against the local root,
with its own Electron profile and backend port, beside any app already running
against production.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
for _source in (REPO_ROOT / "server-components" / "src", REPO_ROOT / "python-api" / "src"):
    if str(_source) not in sys.path:
        sys.path.insert(0, str(_source))

from arcrho_api.config import DEFAULT_WORKSPACE_ROOT  # noqa: E402
from arcrho_api.hosted_save_enrollment import provision_gateway_user  # noqa: E402
from arcrho_api.io import write_json_atomic  # noqa: E402
from arcrho_hosted_save_http_contract import (  # noqa: E402
    default_gateway_config,
    normalize_gateway_config,
    server_config_path as gateway_registry_path,
)
from arcrho_server_component_status import component_status  # noqa: E402
from arcrho_server_control import (  # noqa: E402
    STOP_WAIT_SECONDS,
    SUPERVISED_ROLES,
    ServerControlError,
    child_env,
    require_local_root,
    start_server,
    stop_server,
)
from server_config import ensure_server_config, read_server_config, write_server_config  # noqa: E402
from utils import component_app_name  # noqa: E402


SERVER_PC_NAME = "NE7SASWPN02"
# The Server PC keeps the test root on E: beside the repo, never on C:.
DEFAULT_ROOT = (
    Path(r"E:\XWSpace\Arco Server")
    if os.environ.get("COMPUTERNAME", "").upper() == SERVER_PC_NAME
    else Path(r"C:\Arco Server")
)
LOCAL_GATEWAY_HOST = "127.0.0.1"
LOCAL_GATEWAY_PORT = 28767
LOCAL_GATEWAY_URL = f"http://{LOCAL_GATEWAY_HOST}:{LOCAL_GATEWAY_PORT}"
LOCAL_CREDENTIAL_NAME = "arcrho_gateway.local.json"
LOCAL_APP_PORT = 28785
LOCAL_USER_DATA_NAME = "arcrho-electron-local"
DEFAULT_PROJECT = "NJ_Annual_Prod_202605_Fake"
ROOT_FOLDERS = ("apps", "config", "projects", "requests", "runtime")
SHARED_CONFIG_FILES = (
    "dataset_number_formats.json",
    "username_index.json",
    "username_index.csv",
    "mssql_connections.json",
)
BUILDABLE = ("engine", "gateway", "orchestrator")

# The local-root check, start and stop live in python-api's
# arcrho_server_control, which the desktop app's Server tab uses too.
LocalServerError = ServerControlError


def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def local_credential_path() -> Path:
    return _appdata() / "ArcRho" / LOCAL_CREDENTIAL_NAME


def _set_apps(root: Path, updates: dict[str, dict[str, Any]]) -> None:
    config_path, _ = ensure_server_config(root)
    payload = read_server_config(config_path, root)
    for role, values in updates.items():
        payload.setdefault("apps", {}).setdefault(role, {}).update(values)
    write_server_config(config_path, payload)


def init_root(
    root: Path,
    *,
    production_root: Path,
    credential_path: Path,
    user: str,
) -> list[str]:
    """Create or complete the local root; safe to run again."""

    notes: list[str] = []
    for folder in ROOT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    # The Bridge needs ResQ, which lives only on the Server PC, so the local
    # root never starts one; two Engines are plenty for one tester.
    _set_apps(
        root,
        {
            "orchestrator": {"max_workers": 2},
            "bridge": {"auto_create_instance": False, "kill_all": True},
        },
    )

    for name in SHARED_CONFIG_FILES:
        source = production_root / "config" / name
        target = root / "config" / name
        if not target.exists() and source.is_file():
            shutil.copy2(source, target)
            notes.append(f"copied config\\{name}")

    registry = gateway_registry_path(root)
    if not registry.exists():
        # Written before the Gateway first starts, or it would create the
        # default registry bound to every interface of this PC.
        gateway = default_gateway_config()
        gateway.update(host=LOCAL_GATEWAY_HOST, port=LOCAL_GATEWAY_PORT, client_url=LOCAL_GATEWAY_URL)
        write_json_atomic(registry, gateway)
        notes.append("wrote the Gateway registry for this PC only")
    else:
        gateway = normalize_gateway_config(json.loads(registry.read_text(encoding="utf-8")))
        if gateway["host"] != LOCAL_GATEWAY_HOST:
            notes.append(f"WARNING: the Gateway registry binds {gateway['host']}, not {LOCAL_GATEWAY_HOST}")

    # This PC is the local root's server machine, so the registry is local
    # disk; a Client PC signs up through the Gateway instead.
    provision_gateway_user(
        server_root=root,
        user=user,
        client_output=credential_path,
        client_url=LOCAL_GATEWAY_URL,
    )
    notes.append(f"credential for {user}: {credential_path}")

    orchestrator = component_app_name("orchestrator")
    target = root / "apps" / orchestrator
    source = production_root / "apps" / orchestrator
    if not target.exists():
        if source.is_dir():
            # The Orchestrator changes rarely and has no build environment on
            # a Client PC; a frozen copy finds its root from where it sits.
            shutil.copytree(source, target)
            notes.append(f"installed {orchestrator} from production")
        else:
            notes.append(f"no {orchestrator} to copy; run: deploy orchestrator")
    return notes


def copy_project(root: Path, *, production_root: Path, name: str, overwrite: bool) -> Path:
    source = production_root / "projects" / name
    target = root / "projects" / name
    if not source.is_dir():
        raise LocalServerError(f"No production project named {name!r}.")
    if target.exists():
        if not overwrite:
            raise LocalServerError(f"{target} exists; pass --overwrite to replace it.")
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("*.lock", ".tmp*", "*.tmp"))
    return target


def deploy(root: Path, components: Sequence[str]) -> None:
    # ARCRHO_ROOT as well as ARCRHO_DEPLOY_ROOT: the Engine and Orchestrator
    # builds find their kill switches and heartbeats through ARCRHO_ROOT and
    # would otherwise look for them somewhere else entirely.
    env = child_env(ARCRHO_DEPLOY_ROOT=str(root), ARCRHO_ROOT=str(root))
    for component in components:
        script = REPO_ROOT / "server-components" / "src" / f"arcrho_{component}" / "build_exe.py"
        print(f"== building {component} into {root}", flush=True)
        result = subprocess.run([sys.executable, str(script)], env=env, cwd=str(script.parent))
        if result.returncode != 0:
            raise LocalServerError(f"{component} build failed with exit code {result.returncode}.")


def status_lines(root: Path) -> list[str]:
    """One line per supervised role: each heartbeat's age and whether it is stale."""

    lines = []
    for role in component_status(root)["roles"]:
        if role["role"] not in SUPERVISED_ROLES:
            continue
        beats = [f"{row['age_seconds']}s {row['status'].lower()}" for row in role["instances"]]
        switch = "  (stop switch on)" if role["stop_switch"] else ""
        lines.append(f"{role['role']:13} {', '.join(beats) or 'not running'}{switch}")
    return lines


def gateway_health(timeout: float = 3.0) -> dict[str, Any] | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{LOCAL_GATEWAY_URL}/api/health", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def launch_app(root: Path, credential_path: Path) -> None:
    if not credential_path.is_file():
        raise LocalServerError(f"{credential_path} is missing; run init first.")
    if gateway_health() is None:
        print(f"WARNING: no Gateway answers at {LOCAL_GATEWAY_URL}; run start first.")
    env = child_env(
        ARCRHO_SERVER_ROOT=str(root),
        ARCRHO_GATEWAY_CONFIG=str(credential_path),
        ARCRHO_GATEWAY_URL=LOCAL_GATEWAY_URL,
        ARCRHO_USER_DATA_DIR=str(_appdata() / LOCAL_USER_DATA_NAME),
        ARCRHO_PORT=str(LOCAL_APP_PORT),
    )
    env.pop("ELECTRON_RUN_AS_NODE", None)
    launcher = REPO_ROOT / "frontend" / "launch_arcrho_dev_mode.bat"
    subprocess.run(["cmd", "/c", str(launcher)], env=env, cwd=str(launcher.parent), check=True)
    print(f"Launched the dev app against {root} on port {LOCAL_APP_PORT}.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="local test root (default: %(default)s)")
    parser.add_argument("--production-root", default=DEFAULT_WORKSPACE_ROOT, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create or complete the local root")
    copy = commands.add_parser("copy-project", help="copy one production project into the local root")
    copy.add_argument("name", nargs="?", default=DEFAULT_PROJECT)
    copy.add_argument("--overwrite", action="store_true")
    build = commands.add_parser("deploy", help="build components from this tree into the local root")
    # Python 3.10's argparse checks an omitted "*" positional against choices as
    # one list value and refuses it, so main() checks the names instead.
    build.add_argument("components", nargs="*", metavar="{" + ",".join(BUILDABLE) + "}")
    commands.add_parser("start", help="start the local Orchestrator, which starts Engine and Gateway")
    commands.add_parser("stop", help="stop every component of the local root")
    commands.add_parser("status", help="show heartbeats and Gateway health")
    commands.add_parser("launch-app", help="start the dev-mode app against the local root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    unknown = [name for name in getattr(args, "components", []) if name not in BUILDABLE]
    if unknown:
        parser.error(f"unknown component(s): {', '.join(unknown)} (choose from {', '.join(BUILDABLE)})")
    production_root = Path(args.production_root)
    try:
        root = require_local_root(Path(args.root), production_root)
        if args.command == "init":
            notes = init_root(
                root,
                production_root=production_root,
                credential_path=local_credential_path(),
                user=os.environ.get("USERNAME", ""),
            )
            print("\n".join([f"Local root ready: {root}", *notes]))
        elif args.command == "copy-project":
            print(f"Copied to {copy_project(root, production_root=production_root, name=args.name, overwrite=args.overwrite)}")
        elif args.command == "deploy":
            deploy(root, args.components or ["engine", "gateway"])
        elif args.command == "start":
            if start_server(root):
                print(f"Started the Orchestrator of {root}.")
            else:
                print("An Orchestrator is already running for this root; stop switches cleared.")
        elif args.command == "stop":
            stopped = stop_server(root, STOP_WAIT_SECONDS)
            print("Stopped." if stopped else "Some components still report a live heartbeat.")
        elif args.command == "status":
            print("\n".join(status_lines(root)))
            print(f"gateway       {LOCAL_GATEWAY_URL}/api/health: {gateway_health() or 'no answer'}")
        elif args.command == "launch-app":
            launch_app(root, local_credential_path())
    except LocalServerError as error:
        print(f"local_server: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
