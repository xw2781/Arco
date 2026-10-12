"""Shared configuration, paths, constants, locks, and mutable globals.

This module is the foundation of the app server. It has zero imports from other
app-server modules to prevent circular dependencies. Every other app-server
module may freely ``from app_server import config`` and reference ``config.DATA_DIR``,
``config._AUDIT_LOG_LOCK``, etc.
"""
from __future__ import annotations

import os
import re
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from arcrho_api import source_table_contract
from arcrho_api import config as api_config
from arcrho_api.hosted_save_enrollment import remember_server_id
from arcrho_api.field_mapping_contract import DATE_ROLE_SIGNIFICANCES
from arcrho_api.sidecar_audit_contract import PROJECT_AUDIT_LOG_MAX_ENTRIES
from arcrho_hosted_save_http_contract import (
    HostedSaveHttpContractError,
    normalize_client_config,
)
from arcrho_project_duplication_contract import (
    encode_filename_segment as _canonical_encode_filename_segment,
)


# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

def _resolve_project_root() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent,
        Path.cwd(),
    ]
    for candidate in candidates:
        if (
            (candidate / "workspace_paths.json").exists()
            or (candidate / "index.html").exists()
        ):
            return candidate
    return candidates[0]


PROJECT_ROOT = _resolve_project_root()

# ---------------------------------------------------------------------------
# Config - load workspace path settings
# ---------------------------------------------------------------------------

# Workspace root resolution is owned by ``arcrho_api.config`` so the app server,
# the Python API, and macros can never disagree about the Arco Server root.
DEFAULT_WORKSPACE_ROOT = api_config.DEFAULT_WORKSPACE_ROOT
RUNTIME_SERVER_ROOT_ENV = api_config.RUNTIME_SERVER_ROOT_ENV
DEFAULT_WORKSPACE_PATHS = dict(api_config.DEFAULT_WORKSPACE_PATHS)
# Canonical wait budget for one data-engine file-exchange round trip
# (ArcRhoTri/ArcRhoVec/ArcRhoHeaders). Callers and request schemas must not
# hardcode their own engine timeout.
ENGINE_REQUEST_TIMEOUT_SEC = 15.0
PROJECT_USER_PREFERENCES_FILE = "preferences.json"
PROJECT_INSTANCE_DEFAULT_PREFS_ENV = "ARCRHO_PROJECT_INSTANCE_DEFAULT_PREFS_PATH"
DEFAULT_PROJECT_INSTANCE_PREFS_PATH = PROJECT_ROOT / "app_server" / "default_preferences" / "project_instance_preferences.json"
PROJECT_SETTINGS_DEFAULT_PREFS_ENV = "ARCRHO_PROJECT_SETTINGS_DEFAULT_PREFS_PATH"
DEFAULT_PROJECT_SETTINGS_PREFS_PATH = PROJECT_ROOT / "app_server" / "default_preferences" / "project_settings_preferences.json"
DATASET_NUMBER_FORMATS_FILE = "dataset_number_formats.json"
DATASET_NUMBER_FORMATS_PATH_ENV = "ARCRHO_DATASET_NUMBER_FORMATS_PATH"
CLIENT_SAVE_LATENCY_LOG_FILE = "client_save_latency.jsonl"
CLIENT_READ_LATENCY_LOG_FILE = "client_read_latency.jsonl"


def _is_arcode_mode() -> bool:
    return os.environ.get("ARCRHO_APP_MODE", "").strip().lower() == "arcode"


def _get_user_appdata_dir() -> str:
    if not _is_arcode_mode():
        return str(api_config.config_dir())
    appdata = str(os.environ.get("APPDATA") or "").strip()
    if not appdata:
        appdata = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(appdata, "Arcode")


def app_runtime_name() -> str:
    """Display name of the app whose Python runtime serves this process.

    User-facing messages about a missing optional dependency name the runtime
    the user has to fix, and only this module knows which app is running.
    """

    return "Arcode" if _is_arcode_mode() else "Arco"


def _get_user_local_appdata_dir() -> str:
    """Return the machine-local application-data folder for runtime logs."""

    local_appdata = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not local_appdata:
        local_appdata = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local_appdata, "Arcode" if _is_arcode_mode() else "ArcRho")


def get_client_save_latency_log_path() -> str:
    """Canonical local-PC path for hosted-save network latency diagnostics."""

    return os.path.join(
        _get_user_local_appdata_dir(),
        "logs",
        CLIENT_SAVE_LATENCY_LOG_FILE,
    )


def get_client_read_latency_log_path() -> str:
    """Canonical local-PC path for Server-hosted workspace-read diagnostics."""

    return os.path.join(
        _get_user_local_appdata_dir(),
        "logs",
        CLIENT_READ_LATENCY_LOG_FILE,
    )


def get_client_temp_dir() -> str:
    """This PC's own scratch folder for files that must never reach the share."""

    return os.path.join(_get_user_local_appdata_dir(), "temp")


def get_gateway_config_path() -> str:
    """Return the current user's machine-local Gateway credential for the active server."""

    return str(api_config.gateway_config_path(Path(WORKSPACE_PATHS_PATH)))


def get_gateway_url() -> str:
    """The Gateway address this app signs up at: the launch override, then the active profile's."""

    return api_config.gateway_url(Path(WORKSPACE_PATHS_PATH))


def load_gateway_config() -> Dict[str, Any]:
    """Load this PC's Gateway credential for the active server.

    A missing file means this PC has not signed in; a Client PC then refuses
    every server operation rather than reaching the share. A malformed file
    fails explicitly.
    """

    path = get_gateway_config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"enabled": False}
    except (OSError, json.JSONDecodeError) as exc:
        raise HostedSaveHttpContractError(
            f"Gateway configuration could not be read: {path}"
        ) from exc
    return normalize_client_config(raw)


def remember_gateway_server_id(server_id: str) -> None:
    """Store the server id in a credential signed up before sign-up stored one."""

    remember_server_id(get_gateway_config_path(), server_id)


WORKSPACE_PATHS_PATH = os.path.join(
    _get_user_appdata_dir(), api_config.WORKSPACE_PATHS_FILE_NAME
)
SNOWFLAKE_CONNECTIONS_PATH = os.path.join(_get_user_appdata_dir(), "snowflake_connections.json")
# Optional Snowflake connections.toml-style file in the same per-user folder;
# its `[connections.my_example_connection]` block seeds the profile store once.
SNOWFLAKE_CONFIG_IMPORT_PATH = os.path.join(_get_user_appdata_dir(), "snowflake_config.txt")
# Per-user Arcode SQL Server console profiles. This is not the Arco Server's
# shared server/database history behind `get_mssql_connections_path()`: that one
# records pairs Project Settings has reached, this one holds the named
# connections the Arcode SQL Server console runs queries through.
SQL_SERVER_CONNECTIONS_PATH = os.path.join(_get_user_appdata_dir(), "sql_server_connections.json")


def workspace_paths_file_exists() -> bool:
    return os.path.exists(WORKSPACE_PATHS_PATH)


def load_workspace_config() -> Dict[str, Any]:
    """The full workspace config, server profiles included, owned by ``arcrho_api.config``."""
    return api_config.load_workspace_config(Path(WORKSPACE_PATHS_PATH))


def load_workspace_paths() -> Dict[str, Any]:
    """Load runtime workspace path configuration."""
    cfg = load_workspace_config()
    workspace_root = (
        api_config.env_server_root() or cfg["workspace_root"] or DEFAULT_WORKSPACE_ROOT
    )
    return {
        "workspace_root": workspace_root,
        "paths": cfg["paths"],
        "gateway_url": api_config.active_server_profile(cfg).get("gateway_url", ""),
    }


def save_workspace_paths(cfg: Dict[str, Any]) -> None:
    """Point the active server profile at ``cfg``'s root and paths."""
    api_config.save_workspace_root(
        cfg["workspace_root"], cfg.get("paths"), Path(WORKSPACE_PATHS_PATH), gateway_url=cfg.get("gateway_url"),
    )


def get_root_path() -> str:
    """Get the workspace root path from config."""
    return load_workspace_paths()["workspace_root"]


def get_path(subpath: str) -> str:
    """Get a full path by joining the workspace root with subpath."""
    return os.path.join(get_root_path(), subpath)


def _get_project_map_dir() -> str:
    cfg = load_workspace_paths()
    return get_path(cfg.get("paths", {}).get("projects_dir", DEFAULT_WORKSPACE_PATHS["projects_dir"]))


def _get_requests_dir() -> str:
    cfg = load_workspace_paths()
    return get_path(cfg.get("paths", {}).get("requests_dir", DEFAULT_WORKSPACE_PATHS["requests_dir"]))


def _get_workflow_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "ArcRho", "workflows")


def _get_scripting_dir() -> str:
    if _is_arcode_mode():
        configured = str(os.environ.get("ARCODE_DATA_DIR") or "").strip()
        if configured:
            return configured
        return os.path.join(os.path.expanduser("~"), "Documents", "Arcode", "scripts")
    configured = str(os.environ.get("ARCRHO_SCRIPTING_DIR") or "").strip()
    if configured:
        return configured
    return os.path.join(os.path.expanduser("~"), "Documents", "ArcRho", "scripts")


def _get_macro_dir() -> str:
    configured = str(os.environ.get("ARCRHO_MACRO_DIR") or "").strip()
    if configured:
        return configured
    return os.path.join(os.path.expanduser("~"), "Documents", "ArcRho", "macros")


MACRO_LIBRARY_DIR_ENV = "ARCRHO_MACRO_LIBRARY_DIR"
MACRO_LIBRARY_SUBPATH = os.path.join("shared", "macros")


def _get_macro_library_dir() -> str:
    """Shared read-only macro library on the Arco Server workspace root.

    The directory is deployer-managed; users only read from it, so this
    resolver never creates it.
    """
    configured = str(os.environ.get(MACRO_LIBRARY_DIR_ENV) or "").strip()
    if configured:
        return configured
    return get_path(MACRO_LIBRARY_SUBPATH)


PROJECT_INDEX_FILE = "index.json"

# Project settings JSON files (on shared network drive)
PROJECT_SETTINGS_SOURCES = {
    "project_map": PROJECT_INDEX_FILE,
    # Add more sources here as needed
}

WORKFLOW_EXT = ".arcwf"

# ---------------------------------------------------------------------------
# Mutable runtime paths — refreshed from config
# ---------------------------------------------------------------------------

DATA_DIR: str = ""
PROJECT_SETTINGS_DIR: str = ""
WORKFLOW_DIR: str = ""
SCRIPTING_DIR: str = ""
MACRO_DIR: str = ""
MACRO_LIBRARY_DIR: str = ""
ALLOWED_BOOK_DIRS: List[Path] = []
REQUEST_DIR: str = ""


def refresh_runtime_paths() -> None:
    """Refresh runtime directories from workspace path config."""
    global DATA_DIR, PROJECT_SETTINGS_DIR, WORKFLOW_DIR, SCRIPTING_DIR, MACRO_DIR
    global MACRO_LIBRARY_DIR, ALLOWED_BOOK_DIRS, REQUEST_DIR
    PROJECT_SETTINGS_DIR = _get_project_map_dir()
    WORKFLOW_DIR = _get_workflow_dir()
    SCRIPTING_DIR = _get_scripting_dir()
    MACRO_DIR = _get_macro_dir()
    MACRO_LIBRARY_DIR = _get_macro_library_dir()
    DATA_DIR = SCRIPTING_DIR
    ALLOWED_BOOK_DIRS = [
        Path(os.path.abspath(PROJECT_SETTINGS_DIR)),
    ]
    REQUEST_DIR = _get_requests_dir()


# In-memory dataset cache
DATASETS: Dict[str, str] = {}

# A coarser view of a hand-entered dataset is never written down: the grid
# routes keep the recipe that builds it here and roll the stored CSV up again
# on every read, so an edit to that CSV can never be served stale.
DATASET_ROLLUPS: Dict[str, Dict[str, Any]] = {}


def clear_runtime_path_caches() -> None:
    """Clear in-memory caches that contain absolute workspace paths."""
    DATASETS.clear()
    DATASET_ROLLUPS.clear()


# Initialise paths on first import
refresh_runtime_paths()

# ---------------------------------------------------------------------------
# File-name constants
# ---------------------------------------------------------------------------

FIELD_MAPPING_FILE = "field_mapping.json"
# The significances whose mapped field carries a reserving period, named once
# in `arcrho_api.field_mapping_contract` because the granularity recorded
# against them is read by the Engine too. Re-exported here so the summary, the
# rule editor, and the mapping validator keep their existing spelling.
FIELD_MAPPING_DATE_SIGNIFICANCES = DATE_ROLE_SIGNIFICANCES
FIELD_MAPPING_SIGNIFICANCES = {
    "Reserving Class",
    *FIELD_MAPPING_DATE_SIGNIFICANCES,
    "Dataset",
}
RESERVING_CLASS_VALUES_FILE = "reserving_class_values.json"
RESERVING_CLASS_COMBINATIONS_FILE = "reserving_class_combinations_cache.json"
RESERVING_CLASS_TYPES_FILE = "reserving_class_types.json"
SCRIPTING_PREFS_FILE = "scripting_prefs.json"
LOCAL_PROJECT_PREFS_FILE = "local_project_prefs.json"
DATASET_TYPES_FILE = "dataset_types.json"
DATA_PROCESSING_RULES_FILE = "data_processing_rules.json"
DATA_PROCESSING_RULES_FORMAT = "arcrho-data-processing-rules-v1"
DATA_PROCESSING_VALUES_FILE = "data_processing_values.json"
# The rule-editor response retains this public, materialized vocabulary contract.
DATA_PROCESSING_VALUES_FORMAT = "arcrho-source-vocab-v1"
# The project cache can evolve independently because it is regenerated on demand.
DATA_PROCESSING_VALUES_CACHE_FORMAT = "arcrho-source-vocab-v2"
DATA_PROCESSING_ALGORITHM_VERSION = "arcrho-data-processing-v1"
USERNAME_INDEX_FILE = "username_index.json"
PROJECT_SETTINGS_XLSX_FILE = "settings.xlsx"
RESERVING_CLASS_TYPES_SHEET_NAME = "Reserving Class Types"
RESERVING_CLASS_TYPES_COLUMNS = ["Name", "Level", "Formula"]
RESERVING_CLASS_TYPES_FILE_COLUMNS = ["Name", "Level", "Formula", "Source"]
DATASET_TYPES_COLUMNS = ["Name", "Data Format", "Category", "Calculated", "Formula"]
DATASET_TYPES_FILE_COLUMNS = ["Name", "Data Format", "Category", "Calculated", "Formula", "Source", "Generated"]
AUDIT_LOG_FILE = "audit_log.json"
# The project log shares the one audit policy with dataset sidecars; the cap
# is owned by ``arcrho_api.sidecar_audit_contract``.
AUDIT_LOG_MAX_ENTRIES = PROJECT_AUDIT_LOG_MAX_ENTRIES
# The table-summary cache is shared by every user of a project. Its payload
# carries `summary_version`; `table_summary_service.load_valid_cache` rejects a
# cache built by another version so a schema change regenerates it in place.
TABLE_SUMMARY_CACHE_FILE = "table_summary.json"
GENERAL_SETTINGS_FILE = "general_settings.json"
PROJECT_LOCK_FILE = "project_lock.json"
PROJECT_DATA_DIR = "data"
DATASET_CACHE_DIR = "datasets"
METHOD_DATA_DIR = "methods"
DATASET_SIDECAR_DIR = "sidecars"
TEMPORARY_VIEW_DATASET_CACHE_DIR = ".temporary-view"
RUNTIME_CACHE_PROVENANCE_DIR = ".arcrho-cache-provenance"
RUNTIME_CACHE_PROVENANCE_FORMAT = "arcrho-runtime-cache-provenance-v4"

# ---------------------------------------------------------------------------
# Thread locks
# ---------------------------------------------------------------------------

_AUDIT_LOG_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# App-control flag paths
# ---------------------------------------------------------------------------

BASE_DIR = PROJECT_ROOT
ELECTRON_RESTART_FLAG = BASE_DIR / ".restart_electron"
ELECTRON_SHUTDOWN_FLAG = BASE_DIR / ".shutdown_electron"

# ---------------------------------------------------------------------------
# Path-resolver helpers
# ---------------------------------------------------------------------------

def encode_filename_segment(name: str) -> str:
    """Delegate filename encoding to the shared cross-process contract owner."""

    return _canonical_encode_filename_segment(name)


def decode_filename_segment(name: str) -> str:
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return re.sub(r"_%([0-9A-Fa-f]{2})_", repl, str(name or ""))


def _sanitize_folder_name(name: str) -> str:
    return encode_filename_segment(name or "")


def _sanitize_project_dir_name(name: str) -> str:
    out = (name or "").strip()
    return encode_filename_segment(out)


def sanitize_reserving_class_folder(value: Any, fallback: str = "ReservingClass") -> str:
    text = str(value if value is not None else "").strip()
    text = encode_filename_segment(text)
    text = re.sub(r"[. ]+$", lambda match: "^" * len(match.group(0)), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or fallback


def _find_existing_project_dir(project_name: str) -> Optional[str]:
    """Find an existing project folder under E:\\ArcRho Server\\projects by name (case-insensitive)."""
    target = _sanitize_folder_name(project_name or "").strip()
    if not target:
        return None

    direct = os.path.join(PROJECT_SETTINGS_DIR, target)
    if os.path.isdir(direct):
        return direct

    try:
        target_l = target.lower()
        with os.scandir(PROJECT_SETTINGS_DIR) as it:
            for entry in it:
                if entry.is_dir() and entry.name.strip().lower() == target_l:
                    return entry.path
    except Exception:
        return None
    return None


def get_table_summary_cache_path(project_name: str) -> str:
    """Table-summary cache path under an existing project folder."""
    chosen_name = (project_name or "").strip()
    project_dir = _find_existing_project_dir(chosen_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {chosen_name}")
    return os.path.join(project_dir, TABLE_SUMMARY_CACHE_FILE)


def get_field_mapping_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, FIELD_MAPPING_FILE)


def get_dataset_types_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, DATASET_TYPES_FILE)


def get_data_processing_rules_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, DATA_PROCESSING_RULES_FILE)


def get_data_processing_values_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, DATA_PROCESSING_VALUES_FILE)


def get_reserving_class_values_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, RESERVING_CLASS_VALUES_FILE)


def get_reserving_class_combinations_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, RESERVING_CLASS_COMBINATIONS_FILE)


def get_reserving_class_types_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, RESERVING_CLASS_TYPES_FILE)


def _get_user_appdata_cache_dir() -> str:
    return os.path.join(_get_user_appdata_dir(), "cache")


def get_scripting_prefs_path() -> str:
    return os.path.join(_get_user_appdata_cache_dir(), SCRIPTING_PREFS_FILE)


def get_local_project_prefs_path() -> str:
    return os.path.join(_get_user_appdata_dir(), LOCAL_PROJECT_PREFS_FILE)


def get_project_instance_default_preferences_path() -> str:
    configured = str(os.environ.get(PROJECT_INSTANCE_DEFAULT_PREFS_ENV) or "").strip()
    if configured:
        return configured
    return str(DEFAULT_PROJECT_INSTANCE_PREFS_PATH)


def get_project_settings_default_preferences_path() -> str:
    configured = str(os.environ.get(PROJECT_SETTINGS_DEFAULT_PREFS_ENV) or "").strip()
    if configured:
        return configured
    return str(DEFAULT_PROJECT_SETTINGS_PREFS_PATH)


def get_dataset_number_formats_path() -> str:
    configured = str(os.environ.get(DATASET_NUMBER_FORMATS_PATH_ENV) or "").strip()
    if configured:
        return configured
    return os.path.join(get_root_path(), "config", DATASET_NUMBER_FORMATS_FILE)

def get_username_index_path() -> str:
    return os.path.join(get_root_path(), "config", USERNAME_INDEX_FILE)


def get_mssql_connections_path() -> str:
    """Server-shared list of previously used SQL Server server/database pairs."""
    return os.path.join(
        get_root_path(), "config", source_table_contract.MSSQL_CONNECTIONS_FILE
    )


def get_project_settings_workbook_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, PROJECT_SETTINGS_XLSX_FILE)


def get_audit_log_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, AUDIT_LOG_FILE)


def get_general_settings_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, GENERAL_SETTINGS_FILE)


def get_project_lock_path(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, PROJECT_LOCK_FILE)


def get_project_data_dir(project_name: str) -> str:
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return os.path.join(project_dir, PROJECT_DATA_DIR)


def get_project_source_dir(project_name: str) -> str:
    """Folder that owns this project's imported master table."""
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return source_table_contract.source_dir(project_dir)


def get_project_master_table_path(project_name: str) -> str:
    """The single imported table every ArcRho consumer reads for this project."""
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return source_table_contract.master_table_path(project_dir)


def get_project_source_import_path(project_name: str) -> str:
    """Import record describing how this project's master table was produced."""
    project_dir = _find_existing_project_dir(project_name)
    if not project_dir:
        raise ValueError(f"Project folder not found under projects: {project_name}")
    return source_table_contract.source_import_path(project_dir)


def get_project_reserving_class_data_dir(project_name: str, reserving_class: str) -> str:
    return os.path.join(
        get_project_data_dir(project_name),
        sanitize_reserving_class_folder(reserving_class),
    )


def get_project_dataset_sidecar_dir(project_name: str, reserving_class: str) -> str:
    return os.path.join(
        get_project_reserving_class_data_dir(project_name, reserving_class),
        DATASET_SIDECAR_DIR,
    )


def get_project_dataset_cache_dir(project_name: str, reserving_class: str) -> str:
    return os.path.join(
        get_project_reserving_class_data_dir(project_name, reserving_class),
        DATASET_CACHE_DIR,
    )


def get_project_temporary_view_dataset_cache_dir(project_name: str, reserving_class: str) -> str:
    """Return the persistent, non-indexed cache folder used by Temporary view."""
    return os.path.join(
        get_project_dataset_cache_dir(project_name, reserving_class),
        TEMPORARY_VIEW_DATASET_CACHE_DIR,
    )


def get_project_method_data_dir(project_name: str, reserving_class: str) -> str:
    return os.path.join(
        get_project_reserving_class_data_dir(project_name, reserving_class),
        METHOD_DATA_DIR,
    )
