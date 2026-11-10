"""Arco host workspace configuration for the Python API.

This module is the canonical owner of Arco Server root resolution. Every
Arco component that needs the server root -- including the bundled app server
in ``frontend/app_server/config.py`` -- must read these constants and helpers
instead of redefining its own environment names, config file name, or default
root, so a macro and the desktop app can never disagree about the workspace.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .exceptions import InvalidArcRhoServerError
from .gateway_test_guard import isolate_test_run
from .io import persisted_json_text

WORKSPACE_PATHS_FILE_NAME = "workspace_paths.json"
DEFAULT_WORKSPACE_ROOT = r"E:\Arco Server"
# The server folder was renamed from "ArcRho Server" on 2026-11-09; a saved
# root still naming the old folder is read, and saved once, under the new name.
_RENAMED_ROOT_PATTERN = re.compile(r"(?i)(^|[\\/])ArcRho Server([\\/]?)$")
DEFAULT_WORKSPACE_PATHS = {
    "projects_dir": "projects",
    "requests_dir": "requests",
}
# Environment overrides, highest precedence first. ``ARCRHO_RUNTIME_SERVER_ROOT``
# is what the Arco Bridge import runner exports into worker processes.
SERVER_ROOT_ENV = "ARCRHO_SERVER_ROOT"
RUNTIME_SERVER_ROOT_ENV = "ARCRHO_RUNTIME_SERVER_ROOT"
SERVER_ROOT_ENV_VARS = (SERVER_ROOT_ENV, RUNTIME_SERVER_ROOT_ENV)
# A launch that names its own Gateway credential outranks the active profile's.
GATEWAY_CONFIG_ENV = "ARCRHO_GATEWAY_CONFIG"
# ... and one that names its Gateway address outranks the active profile's.
GATEWAY_URL_ENV = "ARCRHO_GATEWAY_URL"
# A test run never finds this PC's credential (see ``gateway_test_guard``).
isolate_test_run(GATEWAY_CONFIG_ENV)
# ``workspace_paths.json`` keeps a list of server profiles, one of them active.
# A file with no list reads as one profile under this id; its credential keeps
# the original file name.
DEFAULT_PROFILE_ID = "default"
DEFAULT_PROFILE_NAME = "Production"
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# What a profile may carry beside its id, name and folder: its own credential
# file, and the Gateway address the app signs up at when it has no credential.
PROFILE_OPTIONAL_KEYS = ("gateway_config", "gateway_url")
# A server's identity: a GUID ``server_config.ensure_server_config`` writes once
# into the root's component configuration, and the Gateway reports from
# ``/api/capabilities`` under the same key.
SERVER_ID_KEY = "server_id"
SERVER_CONFIG_RELATIVE_PATH = Path("config") / "config.json"
# A running desktop app already knows its workspace root; asking it is the last
# resort before the packaged default, so keep the probe short enough that a
# stopped app never stalls a macro.
APP_QUERY_TIMEOUT_SEC = 3.0


def config_dir() -> Path:
    """Return the per-user ArcRho config folder (``%APPDATA%\\ArcRho``)."""

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "ArcRho"
    return Path.home() / "AppData" / "Roaming" / "ArcRho"


def get_config_path() -> Path:
    """Return the Arco host workspace config file used by the Python API."""

    return config_dir() / WORKSPACE_PATHS_FILE_NAME


def read_server_id(server_root: str | Path) -> str:
    """Return the server id written in ``server_root``'s configuration, or ``""``."""

    try:
        payload = json.loads(
            (Path(server_root) / SERVER_CONFIG_RELATIVE_PATH).read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        return ""
    return str(payload.get(SERVER_ID_KEY) or "").strip() if isinstance(payload, dict) else ""


def env_server_root() -> str:
    """Return the Arco Server root set by environment override, if any."""

    for name in SERVER_ROOT_ENV_VARS:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _normalize_path(path_like: str | Path) -> Path:
    return Path(path_like).expanduser().resolve()


def validate_server_root(path_like: str | Path) -> Path:
    root = _normalize_path(path_like)
    try:
        valid_root = root.exists() and root.is_dir()
        valid_projects = (root / "projects").exists() and (root / "projects").is_dir()
    except OSError as exc:
        raise InvalidArcRhoServerError(f"Arco Server root is not accessible: {root}") from exc
    if not valid_root:
        raise InvalidArcRhoServerError(f"Arco Server root does not exist: {root}")
    projects_dir = root / "projects"
    if not valid_projects:
        raise InvalidArcRhoServerError(
            f"Arco Server root must contain a projects folder: {projects_dir}"
        )
    return root


def _read_workspace_config(path: Path | None = None) -> dict:
    path = path or get_config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: object, default: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _root_text(value: object) -> str:
    return _RENAMED_ROOT_PATTERN.sub(r"\1Arco Server\2", _text(value))


def normalize_workspace_config(raw: dict) -> dict:
    """Return the canonical workspace config: server profiles, the active one, and paths.

    A file written before profiles existed holds only ``workspace_root``; it
    reads as one ``default`` profile for that root, built in memory. An empty
    root means none is configured, so callers fall back as they always have.
    ``workspace_root`` always mirrors the active profile, because the installer,
    ArcBot and the running-app probe read that field.
    """

    paths = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
    profiles: list[dict] = []
    for item in raw.get("profiles") if isinstance(raw.get("profiles"), list) else []:
        if not isinstance(item, dict):
            continue
        profile_id = _text(item.get("id")).lower()
        root = _root_text(item.get("root"))
        if not profile_id or not root or any(p["id"] == profile_id for p in profiles):
            continue
        profile = {"id": profile_id, "name": _text(item.get("name"), profile_id), "root": root}
        for key in PROFILE_OPTIONAL_KEYS:
            if _text(item.get(key)):
                profile[key] = _text(item.get(key))
        profiles.append(profile)
    if not profiles:
        profiles = [{
            "id": DEFAULT_PROFILE_ID,
            "name": DEFAULT_PROFILE_NAME,
            "root": _root_text(raw.get("workspace_root")),
        }]
    active = _text(raw.get("active_profile")).lower()
    if not any(p["id"] == active for p in profiles):
        active = profiles[0]["id"]
    return {
        "workspace_root": next(p["root"] for p in profiles if p["id"] == active),
        "paths": {
            key: _text(paths.get(key), default) for key, default in DEFAULT_WORKSPACE_PATHS.items()
        },
        "profiles": profiles,
        "active_profile": active,
    }


def load_workspace_config(path: Path | None = None) -> dict:
    """Read the host workspace config file; a missing file reads as the in-memory default."""

    raw = _read_workspace_config(path)
    cfg = normalize_workspace_config(raw)
    saved_roots = [raw.get("workspace_root")] + [
        item.get("root") for item in raw.get("profiles") or [] if isinstance(item, dict)
    ]
    if any(_RENAMED_ROOT_PATTERN.search(_text(root)) for root in saved_roots):
        cfg = save_workspace_config(cfg, path)
    return cfg


def save_workspace_config(payload: dict, path: Path | None = None) -> dict:
    """Write the host workspace config atomically and return what was written."""

    config_path = path or get_config_path()
    cfg = normalize_workspace_config(payload)
    for profile in cfg["profiles"]:
        profile["root"] = profile["root"] or DEFAULT_WORKSPACE_ROOT
    cfg["workspace_root"] = active_server_profile(cfg)["root"]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
    tmp_path.write_text(persisted_json_text(cfg), encoding="utf-8")
    os.replace(tmp_path, config_path)
    return cfg


def save_workspace_root(
    root: str | Path, paths: dict | None = None, path: Path | None = None, *, gateway_url: str | None = None,
) -> dict:
    """Point the active server profile at ``root`` and, when given, its Gateway address (the Server Connection save)."""

    cfg = load_workspace_config(path)
    profile = active_server_profile(cfg)
    profile["root"] = str(root).strip()
    if gateway_url is not None:
        _set_gateway_url(profile, gateway_url)
    cfg["paths"].update(paths or {})
    return save_workspace_config(cfg, path)


def active_server_profile(cfg: dict) -> dict:
    return next(p for p in cfg["profiles"] if p["id"] == cfg["active_profile"])


def profile_gateway_config_path(profile: dict, folder: Path) -> Path:
    """The Gateway credential for one server profile.

    A profile may name its own file; otherwise the default profile keeps the
    original credential name and every other profile ``arcrho_gateway.<id>.json``
    beside it, so each server has its own sign-in.
    """

    if profile.get("gateway_config"):
        return Path(profile["gateway_config"]).expanduser()
    from arcrho_hosted_save_http_contract import CLIENT_CONFIG_FILE_NAME

    if profile["id"] == DEFAULT_PROFILE_ID:
        return folder / CLIENT_CONFIG_FILE_NAME
    name = Path(CLIENT_CONFIG_FILE_NAME)
    return folder / f"{name.stem}.{profile['id']}{name.suffix}"


def _set_gateway_url(profile: dict, url: str) -> None:
    from arcrho_hosted_save_http_contract import normalize_gateway_client_url

    url = normalize_gateway_client_url(url, allow_empty=True)
    if url:
        profile["gateway_url"] = url
    else:
        profile.pop("gateway_url", None)


def gateway_url(path: Path | None = None) -> str:
    """The Gateway address this app signs up at: the launch override, then the active profile's."""

    return env_gateway_url() or active_server_profile(load_workspace_config(path)).get("gateway_url", "")


def env_gateway_url() -> str:
    """Return the Gateway address set by environment override, if any."""

    return str(os.environ.get(GATEWAY_URL_ENV) or "").strip().rstrip("/")


def env_gateway_config_path() -> str:
    """Return the Gateway credential set by environment override, if any."""

    return str(os.environ.get(GATEWAY_CONFIG_ENV) or "").strip()


def gateway_config_path(path: Path | None = None) -> Path:
    """The current user's Gateway credential: the launch override, then the active profile's."""

    configured = env_gateway_config_path()
    if configured:
        return Path(configured)
    config_path = path or get_config_path()
    return profile_gateway_config_path(
        active_server_profile(load_workspace_config(config_path)), config_path.parent
    )


def profile_id_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def upsert_server_profile(
    *, name: str, root: str, profile_id: str = "", gateway_config: str = "", gateway_url: str = "",
    path: Path | None = None,
) -> dict:
    """Add a server profile, or replace the one with the same id, and save."""

    profile_id = (profile_id.strip() or profile_id_for(name)).lower()
    if not PROFILE_ID_PATTERN.match(profile_id):
        raise ValueError("A server profile id uses letters, digits, '_' or '-' only.")
    if not root.strip():
        raise ValueError("A server folder is required.")
    # A client records the folder as an alias; only the server opens it.
    profile = {"id": profile_id, "name": name.strip() or profile_id, "root": root.strip()}
    if gateway_config.strip():
        profile["gateway_config"] = gateway_config.strip()
    _set_gateway_url(profile, gateway_url)
    cfg = load_workspace_config(path)
    cfg["profiles"] = [p for p in cfg["profiles"] if p["id"] != profile_id] + [profile]
    return save_workspace_config(cfg, path)


def activate_server_profile(profile_id: str, path: Path | None = None) -> dict:
    """Make one saved profile the active server and save."""

    profile_id = profile_id.strip().lower()
    cfg = load_workspace_config(path)
    if not any(p["id"] == profile_id for p in cfg["profiles"]):
        raise ValueError(f"No server profile named {profile_id!r}.")
    cfg["active_profile"] = profile_id
    return save_workspace_config(cfg, path)


def _load_host_server_root() -> Path | None:
    raw = load_workspace_config()["workspace_root"]
    return _normalize_path(raw) if raw else None


def _load_env_server_root() -> Path | None:
    raw = env_server_root()
    return _normalize_path(raw) if raw else None


def _load_running_app_server_root() -> Path | None:
    """Ask the running Arco desktop app which workspace root it is using.

    The host config file is only written when a user saves Arco Server
    Connection, so a fresh client install has no file at all. The desktop app
    resolves a root regardless, and its endpoint is discoverable, so querying it
    keeps macros on exactly the workspace the app is showing.
    """

    try:
        from .ui import _request_json

        payload = _request_json("/workspace_paths", timeout_sec=APP_QUERY_TIMEOUT_SEC)
    except Exception:
        return None
    config = payload.get("config")
    if not isinstance(config, dict):
        return None
    raw = str(config.get("workspace_root") or "").strip()
    return _normalize_path(raw) if raw else None


def _load_default_server_root() -> Path | None:
    """Return the packaged default root only when it is a real Arco Server."""

    try:
        return validate_server_root(DEFAULT_WORKSPACE_ROOT)
    except InvalidArcRhoServerError:
        return None


def _resolve_configured_server_root() -> Path | None:
    """Resolve the root from local configuration only (no network probes)."""

    return _load_env_server_root() or _load_host_server_root()


def _discover_server_root() -> Path | None:
    """Resolve the root from the running app, then the packaged default."""

    return _load_running_app_server_root() or _load_default_server_root()


def _resolve_default_server_root() -> Path | None:
    return _resolve_configured_server_root() or _discover_server_root()


# Set only by set_server_root(); an explicit call outranks every other source.
_explicit_server_root: Path | None = None
# Cached file/app/default resolution. The environment is deliberately not cached
# here: the Arco Bridge exports ARCRHO_RUNTIME_SERVER_ROOT into an already
# running process, and that must not lose to a root cached at import time.
_server_root: Path | None = _load_host_server_root()
_discovery_attempted = False


def get_server_root(*, required: bool = False) -> Path | None:
    """Return the current default Arco Server root.

    Resolution order:

    1. an in-process root from :func:`set_server_root`;
    2. the ``ARCRHO_SERVER_ROOT`` / ``ARCRHO_RUNTIME_SERVER_ROOT`` environment
       overrides, re-read on every call;
    3. the Arco host app workspace config file
       (``%APPDATA%\\ArcRho\\workspace_paths.json``);
    4. the workspace root reported by the running Arco desktop app;
    5. the packaged default root, when it exists and holds a projects folder.

    Steps 4 and 5 are attempted once per process; call
    :func:`reload_server_root` to retry them.
    """

    global _server_root, _discovery_attempted
    if _explicit_server_root is not None:
        return _explicit_server_root
    env_root = _load_env_server_root()
    if env_root is not None:
        return env_root
    if _server_root is None:
        _server_root = _load_host_server_root()
    if _server_root is None and not _discovery_attempted:
        _discovery_attempted = True
        _server_root = _discover_server_root()
    if _server_root is not None:
        return _server_root
    if required:
        raise InvalidArcRhoServerError(
            "Arco Server root was not found in the Arco host config file. "
            "Use Arco Server Connection, call set_server_root(...), set "
            f"{SERVER_ROOT_ENV}, or pass server_root=... to ArcRhoClient(...)."
        )
    return None


def set_server_root(server_root: str | Path, *, persist: bool = True, validate: bool = True) -> Path:
    """Set the default Arco Server root in process and in the host config."""

    global _explicit_server_root, _server_root, _discovery_attempted
    root = validate_server_root(server_root) if validate else _normalize_path(server_root)
    _explicit_server_root = root
    _server_root = root
    _discovery_attempted = False
    if persist:
        save_workspace_root(root)
    return root


def reload_server_root() -> Path | None:
    """Re-resolve the server root, dropping any in-process override.

    Retries the running-app query and the packaged default that
    :func:`get_server_root` attempts only once per process.
    """

    global _explicit_server_root, _server_root, _discovery_attempted
    _explicit_server_root = None
    _discovery_attempted = True
    _server_root = _resolve_default_server_root()
    return _server_root
