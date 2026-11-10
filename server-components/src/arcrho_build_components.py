"""The deployed-component model shared by the Build Manager, the build
listener, and the client deploy CLI.

This was extracted from ``arcrho_build_manager`` when builds became remotely
triggerable. The component table, the trees whose edits make a deployed
component stale, and the freshness rule now have one owner, so the GUI a human
drives and the CLI an agent drives can never disagree about which components a
change makes stale — the exact mistake this module is meant to prevent, where
an ``app_server`` edit silently left the Gateway on old code because only the
Bridge and Engine were rebuilt.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# The Bridge owns the list of repository trees it freezes; read it rather than
# restating it, so a change to what the Bridge bundles cannot silently stop
# being reported as stale here.
from arcrho_bridge.bundled_sources import BUNDLED_SOURCE_ROOTS
from arcrho_engine.bundled_sources import ENGINE_BUNDLED_SOURCES
from utils import DEFAULT_DEPLOY_ROOT, DEPLOYED_COMPONENT_ROLES, component_app_name


BASE_DIR = Path(__file__).resolve().parent
SERVER_COMPONENTS_ROOT = BASE_DIR.parent
REPOSITORY_ROOT = SERVER_COMPONENTS_ROOT.parent
DEPLOY_ROOT = DEFAULT_DEPLOY_ROOT
APPS_DIR = DEPLOY_ROOT / "apps"
INSTANCES_DIR = DEPLOY_ROOT / "runtime" / "instances"

SOURCE_EXTENSIONS = {".html", ".ico", ".json", ".py", ".txt"}
# "logs" holds run output, not source; counting it reports a component as stale
# every time it runs.
SOURCE_SKIP_DIRS = {"__pycache__", "build", "dist", "logs", "spec"}

STALE_FRESHNESS_VALUES = frozenset({"Missing EXE", "Source newer"})

# A clone the build listener is allowed to own carries this file, inside its
# own ``.git`` directory. That location is the point: the listener checks out a
# detached base commit, resets hard and runs ``git clean -fd`` before every
# build, so anything in the working tree is at the mercy of whichever commit it
# built from. A first attempt put the marker in the tree and gitignored it, and
# the first real build removed it -- the base commit predated the ignore rule,
# so the file was merely untracked. Nothing under ``.git`` is touched by any of
# those three commands, whatever the commit says.
BUILD_CLONE_MARKER = "arcrho-build-clone"
_DRIVE_FIXED = 3


def workspace_drive_is_local(root: Path = DEPLOY_ROOT) -> bool:
    """True when this machine physically holds the workspace.

    The Server PC shares its whole workspace drive and the Client PC maps it to
    the same letter, so a path proves nothing about which machine is reading
    it. The drive type does: a local disk on the server, a network drive
    through the share.
    """

    if os.name != "nt":
        return False
    drive = os.path.splitdrive(str(Path(root)))[0]
    if not drive:
        return False
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") == _DRIVE_FIXED
    except Exception:  # noqa: BLE001 - an unreadable drive is not a local one
        return False


def auto_listen_decision(
    repository_root: Path = REPOSITORY_ROOT,
    deploy_root: Path = DEPLOY_ROOT,
) -> tuple[bool, str]:
    """Whether the Build Manager should start listening unasked, and why not.

    Turning the listener on by hand was the one human step in every remote
    build, and on the Server PC it is the same step every time. It is only safe
    to skip when *both* conditions hold, because a listener resets the clone it
    was started from at the start of every build:

    1. This machine holds the workspace, so it is the machine builds belong on.
    2. The clone it would own is marked as a clone nobody edits. Without this,
       starting the Manager from a working clone on the server would quietly
       revert whoever is editing it -- and doing that automatically, with no
       one ticking a box, is worse than the manual step it replaces.
    """

    if not workspace_drive_is_local(deploy_root):
        return False, f"{deploy_root} is reached over the share, so this is not the Server PC"
    git_dir = Path(repository_root) / ".git"
    if not git_dir.is_dir():
        return False, f"{repository_root} is not a plain git clone"
    if not (git_dir / BUILD_CLONE_MARKER).exists():
        return False, (
            f"{repository_root} carries no .git/{BUILD_CLONE_MARKER}, so it may be a clone "
            "someone edits and a build would reset it"
        )
    return True, ""


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    source_dir: Path
    exe_name: str
    instance_roles: tuple[str, ...]
    # Repository trees outside source_dir that the component freezes into its
    # executable. Editing one of these leaves the deployed app stale even though
    # source_dir is untouched, so freshness has to consider them too.
    bundled_source_roots: tuple[Path, ...] = ()

    @property
    def build_script(self) -> Path:
        return self.source_dir / "build_exe.py"

    @property
    def deploy_exe(self) -> Path:
        return APPS_DIR / Path(self.exe_name).stem / self.exe_name

    @property
    def freshness_source_dirs(self) -> tuple[Path, ...]:
        return (self.source_dir, *self.bundled_source_roots)


SHARED_COMPONENT_SOURCES = (
    BASE_DIR / "utils.py",
    BASE_DIR / "server_config.py",
    BASE_DIR / "build_runtime.py",
)

# The Engine and the Gateway freeze the same trees: the Gateway's build script
# bundles ENGINE_BUNDLED_SOURCES directly, which is why an app_server edit
# makes three components stale rather than two.
_ENGINE_BUNDLED_ROOTS = tuple(item.source for item in ENGINE_BUNDLED_SOURCES)


def _role_bundled_roots(role: str) -> tuple[Path, ...]:
    if role == "bridge":
        return BUNDLED_SOURCE_ROOTS
    if role in ("engine", "gateway"):
        return _ENGINE_BUNDLED_ROOTS
    if role == "credential":
        # It freezes the canonical enrollment, so an edit there leaves the
        # deployed helper stale even though its own folder is untouched.
        return (REPOSITORY_ROOT / "python-api" / "src",)
    return ()


def _build_component(role: str) -> Component:
    if role in ("launcher", "credential"):
        instance_roles: tuple[str, ...] = ()
    elif role == "bridge":
        instance_roles = ("arcrho_bridge", "arcrho_bridge_worker")
    else:
        instance_roles = (f"arcrho_{role}",)
    return Component(
        role,
        "Admin Control" if role == "admin" else role.title(),
        BASE_DIR / f"arcrho_{role}",
        f"{component_app_name(role)}.exe",
        instance_roles,
        bundled_source_roots=(*_role_bundled_roots(role), *SHARED_COMPONENT_SOURCES),
    )


COMPONENTS = tuple(_build_component(role) for role in DEPLOYED_COMPONENT_ROLES)
COMPONENT_KEYS = tuple(component.key for component in COMPONENTS)


def component_by_key(key: str) -> Component:
    normalized = str(key or "").strip().lower()
    for component in COMPONENTS:
        if component.key == normalized:
            return component
    known = ", ".join(COMPONENT_KEYS)
    raise KeyError(f"Unknown component {key!r}. Known components: {known}")


def instance_folder(role: str) -> Path:
    return INSTANCES_DIR / role


def read_json(path: Path) -> dict[str, object]:
    try:
        with open(path, mode="r", encoding="utf-8") as file:
            payload = json.load(file)
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_instance_files(component: Component) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for role in component.instance_roles:
        folder = instance_folder(role)
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = read_json(path)
            rows.append(
                {
                    "role": role,
                    "path": path,
                    "name": path.name,
                    "server": payload.get("Server") or path.stem,
                    "user": payload.get("User") or "",
                    "last_seen": payload.get("Last seen") or "",
                    "age": max(0, int(time.time() - path.stat().st_mtime)),
                }
            )
    return rows


def latest_source_timestamp(component: Component) -> float | None:
    latest: float | None = None
    for root in component.freshness_source_dirs:
        if not root.exists():
            continue
        candidates = (root,) if root.is_file() else root.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            if any(part in SOURCE_SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
                continue
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            try:
                timestamp = path.stat().st_mtime
            except OSError:
                continue
            latest = timestamp if latest is None else max(latest, timestamp)
    return latest


def build_freshness(component: Component) -> str:
    exe_path = component.deploy_exe
    if not exe_path.exists():
        return "Missing EXE"

    latest_source = latest_source_timestamp(component)
    if latest_source is None:
        return "No source"

    try:
        exe_timestamp = exe_path.stat().st_mtime
    except OSError:
        return "EXE inaccessible"

    return "Updated" if exe_timestamp >= latest_source else "Source newer"


def stale_components() -> list[Component]:
    """Every deployed component whose bundled sources are newer than its EXE.

    Both the Build Manager's status table and ``deploy.py --auto`` read this, so
    "which components does my change make stale?" has exactly one answer.
    """

    return [
        component
        for component in COMPONENTS
        if build_freshness(component) in STALE_FRESHNESS_VALUES
    ]


def remove_instance_file(path: Path, attempts: int = 5, delay: float = 0.1) -> bool:
    resolved = path.resolve()
    instances_root = INSTANCES_DIR.resolve()
    if instances_root not in resolved.parents:
        raise ValueError(f"Refusing to remove file outside instances folder: {path}")

    for _ in range(attempts):
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            time.sleep(delay)
    path.unlink()
    return True
