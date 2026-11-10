"""Canonical ArcRho Server component configuration contract.

The server installer, Admin Control, and long-running components all share this
module so the default worker topology and JSON text cannot drift between
producers.  Unknown keys and existing values are intentionally preserved when
defaults are merged into an adopted workspace.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
if CANONICAL_API_SOURCE.is_dir() and str(CANONICAL_API_SOURCE) not in sys.path:
    sys.path.insert(0, str(CANONICAL_API_SOURCE))


SERVER_CONFIG_VERSION = "1.0"
SERVER_CONFIG_RELATIVE_PATH = Path("config") / "config.json"
LEGACY_SERVER_CONFIG_RELATIVE_PATH = Path("core") / "config.json"

_DEFAULT_APPS = {
    # Admin Control is not supervised by the Orchestrator, so this switch exists
    # only so a deploy can stop the live server long enough to swap its folder;
    # the build clears it and relaunches afterwards.
    "admin": {"kill_all": False},
    "engine": {"kill_all": False},
    "orchestrator": {
        "kill_all": False,
        "auto_create_workers": True,
        "max_workers": 5,
    },
    "bridge": {
        "kill_all": False,
        "auto_create_instance": True,
        "max_instances": 1,
        "max_workers": 1,
    },
    "bridge_worker": {"kill_all": False},
    "gateway": {
        "kill_all": False,
        "auto_create_instance": True,
        "max_instances": 1,
    },
}


def default_server_config(server_root: str | os.PathLike[str]) -> dict[str, Any]:
    return {
        "config_version": SERVER_CONFIG_VERSION,
        "root": str(Path(server_root).expanduser().resolve()),
        "apps": copy.deepcopy(_DEFAULT_APPS),
    }


def merge_missing_defaults(value: Any, defaults: Any) -> Any:
    """Return ``value`` with missing mapping keys supplied by ``defaults``."""

    if not isinstance(defaults, dict):
        return copy.deepcopy(value)
    if not isinstance(value, dict):
        return copy.deepcopy(defaults)
    merged = copy.deepcopy(value)
    for key, default_value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(default_value)
        elif isinstance(default_value, dict):
            merged[key] = merge_missing_defaults(merged[key], default_value)
    return merged


def resolve_server_config_path(server_root: str | os.PathLike[str]) -> Path:
    root = Path(server_root)
    configured = os.environ.get("ARCRHO_CONFIG") or os.environ.get("ADAS_CONFIG")
    canonical = root / SERVER_CONFIG_RELATIVE_PATH
    legacy = root / LEGACY_SERVER_CONFIG_RELATIVE_PATH
    if canonical.exists():
        return canonical
    if configured:
        return Path(configured).expanduser()
    if legacy.exists():
        return legacy
    return canonical


def read_server_config(
    path: Path,
    server_root: str | os.PathLike[str],
    *,
    merge_defaults: bool = True,
) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"ArcRho Server configuration must be a JSON object: {path}")
    if not merge_defaults:
        return payload
    return merge_missing_defaults(payload, default_server_config(server_root))


def _persisted_json_text(payload: dict[str, Any]) -> str:
    """Return the canonical on-disk text for this configuration payload.

    ``arcrho_api.io`` owns that text, but it is imported here rather than at
    module scope because the frozen Arco Bridge must load ``arcrho_api`` from
    its staged ResQ migration bundle instead of its own import graph.  Every
    Bridge process reads the server configuration through ``utils``, so a
    module-scope import here loaded a second ``arcrho_api`` into the worker
    before any ResQ import ran, and ``load_resq_data_migration`` then refused
    every import.  Only writers pay for the import, and no Bridge process
    writes this file.
    """

    from arcrho_api.io import persisted_json_text

    return persisted_json_text(payload)


def write_server_config(path: Path, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise TypeError("ArcRho Server configuration must be a mapping.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(_persisted_json_text(payload))
        # Every Engine, Bridge, and Orchestrator polls this file on its
        # heartbeat cycle, and an SMB reader holding it open surfaces as a
        # transient WinError 5 on the atomic replace. Retry briefly rather
        # than fail the write: a failed write here can strand a deploy's
        # kill switch and keep every worker down.
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def with_server_id(
    payload: dict[str, Any], *, keep_from: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return ``payload`` carrying the server's identity.

    The id is a GUID minted once per server root and never replaced: an id
    already in ``payload``, or else in ``keep_from`` (the configuration being
    reset), is kept. Clients compare it with the id the Gateway reports, so a
    new id would lock every client out until the Gateway restarted. The key is
    imported here rather than at module scope for the reason given in
    :func:`_persisted_json_text`.
    """

    from arcrho_api.config import SERVER_ID_KEY

    for source in (payload, keep_from or {}):
        server_id = str(source.get(SERVER_ID_KEY) or "").strip()
        if server_id:
            return payload if source is payload else {**payload, SERVER_ID_KEY: server_id}
    return {**payload, SERVER_ID_KEY: str(uuid.uuid4())}


def ensure_server_id(server_root: str | os.PathLike[str]) -> str:
    """Write the server id into the root's configuration if missing; return it."""

    from arcrho_api.config import SERVER_ID_KEY

    root = Path(server_root).expanduser().resolve()
    path = resolve_server_config_path(root)
    existing = read_server_config(path, root, merge_defaults=False)
    updated = with_server_id(existing)
    if updated is not existing:
        write_server_config(path, updated)
    return updated[SERVER_ID_KEY]


def ensure_server_config(server_root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]]:
    root = Path(server_root).expanduser().resolve()
    path = resolve_server_config_path(root)
    existing = read_server_config(path, root, merge_defaults=False)
    merged = with_server_id(merge_missing_defaults(existing, default_server_config(root)))
    if not path.exists() or merged != existing:
        write_server_config(path, merged)
    return path, merged
