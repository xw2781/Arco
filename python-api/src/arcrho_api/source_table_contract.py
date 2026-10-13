"""Canonical contract for the project-owned imported source table.

Every Arco project folder owns exactly one imported raw table at a fixed
location and a fixed name:

    <project dir>/source/master_table.csv

That copy is the only table any consumer reads. The external CSV path a user
picks in Project Settings and the SQL Server profile they configure are *import
sources*; they are never read directly by the data engine, the app server
summary/reserving/data-processing services, or any downstream method.

`source/source_import.json` records which source produced the current master
copy, plus the shared SQL Server profile for the project. It never stores
credentials: SQL Server access uses the caller's Windows identity.

This module is the single owner of the folder/file names, the JSON schema, the
normalization rules, and the staleness rule. Consumers must import from here
rather than rebuilding any of it. The Engine cannot import this package from
its frozen bundle, so it mirrors the two path constants locally and
`frontend/tests/test_source_table_contract.py` fails when the mirror drifts.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


# --- Layout ---------------------------------------------------------------
SOURCE_IMPORT_DIR = "source"
MASTER_TABLE_FILE = "master_table.csv"
SOURCE_IMPORT_FILE = "source_import.json"
SOURCE_IMPORT_JSON_FORMAT = "arcrho-source-import-v4"

# --- Source kinds ---------------------------------------------------------
SOURCE_TYPE_CSV = "csv"
SOURCE_TYPE_MSSQL = "mssql"
# A source built by joining several CSV and SQL Server tables on the client.
SOURCE_TYPE_COMBINED = "combined"
SOURCE_TYPES = (SOURCE_TYPE_CSV, SOURCE_TYPE_MSSQL, SOURCE_TYPE_COMBINED)

# --- Combined source rules ------------------------------------------------
COMBINED_KEY_CONVERT_YYYYMM = "yyyymm"
COMBINED_NICKNAME_MAX = 24

# --- SQL Server authentication -------------------------------------------
# Only Windows authentication is wired up. The SQL login mode is reserved so
# the profile shape does not change when it is implemented; services must
# reject it until then.
MSSQL_AUTH_WINDOWS = "windows"
MSSQL_AUTH_SQL_LOGIN = "sql_login"
MSSQL_AUTH_MODES = (MSSQL_AUTH_WINDOWS, MSSQL_AUTH_SQL_LOGIN)
SUPPORTED_MSSQL_AUTH_MODES = (MSSQL_AUTH_WINDOWS,)


def source_dir(project_dir: str) -> str:
    """Folder holding the imported master table and its import record."""
    return os.path.join(str(project_dir), SOURCE_IMPORT_DIR)


def master_table_path(project_dir: str) -> str:
    """The one table every Arco consumer reads for this project."""
    return os.path.join(source_dir(project_dir), MASTER_TABLE_FILE)


def source_import_path(project_dir: str) -> str:
    """The import record describing how the master table was produced."""
    return os.path.join(source_dir(project_dir), SOURCE_IMPORT_FILE)


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_source_type(value: Any) -> str:
    candidate = _text(value).lower()
    return candidate if candidate in SOURCE_TYPES else SOURCE_TYPE_CSV


# --- External source reachability ----------------------------------------
# The configured CSV is the one path in this contract that names a machine the
# workspace does not own. A Client PC browses to it as `Z:\...`; the ArcRho
# Server host has no such mapping, so a path saved in the client's own drive
# letters is unreadable by the Engine that now performs the import. Resolving
# the letter to the share it stands for makes one saved path mean the same file
# on every machine, which is also what the persisted-JSON rules require of any
# value stored in project configuration.


def _mapped_drive_target(drive: str) -> str:
    """UNC target of one mapped Windows drive letter, or "" when unmapped."""

    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return ""
    try:
        buffer_length = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(buffer_length.value)
        result = ctypes.windll.mpr.WNetGetConnectionW(
            ctypes.c_wchar_p(drive),
            buffer,
            ctypes.byref(buffer_length),
        )
    except Exception:
        return ""
    if result != 0:
        return ""
    return _text(buffer.value)


def normalize_import_source_path(csv_path: Any) -> str:
    """Rewrite a mapped-drive CSV path as the UNC path it stands for.

    A UNC path, an unmapped local path, or a path on a machine without drive
    mappings is returned unchanged; this never invents a share that the caller's
    own session does not already have.
    """

    clean = _text(csv_path)
    if len(clean) < 2 or clean[1] != ":":
        return clean
    drive = clean[0].upper() + ":"
    target = _mapped_drive_target(drive)
    if not target:
        return clean
    remainder = clean[2:].lstrip("\\/")
    return os.path.join(target.rstrip("\\/"), remainder) if remainder else target


def import_source_path_is_shared(csv_path: Any) -> bool:
    """Whether a saved CSV path names a location another machine can open.

    A UNC path qualifies; a drive letter does not, because the letter is only
    the caller's own mapping. Callers use this to decide whether the ArcRho
    Server host can perform the import, or whether it has to stay on the client.
    """

    clean = _text(csv_path).replace("/", "\\")
    return clean.startswith("\\\\")


def normalize_mssql_auth(value: Any) -> str:
    candidate = _text(value).lower()
    return candidate if candidate in MSSQL_AUTH_MODES else MSSQL_AUTH_WINDOWS


def empty_mssql_profile() -> Dict[str, str]:
    return {
        "server": "",
        "database": "",
        "table": "",
        "authentication": MSSQL_AUTH_WINDOWS,
    }


def normalize_mssql_profile(profile: Any) -> Dict[str, str]:
    data = profile if isinstance(profile, dict) else {}
    return {
        "server": _text(data.get("server")),
        "database": _text(data.get("database")),
        "table": _text(data.get("table")),
        "authentication": normalize_mssql_auth(data.get("authentication")),
    }


def empty_last_import() -> Dict[str, Any]:
    return {
        "source_type": "",
        "source_label": "",
        "imported_at": "",
        "imported_by": "",
        "row_count": None,
        "column_count": None,
        # CSV imports record the origin file identity so a changed external
        # file can be detected and re-copied without asking the user.
        "csv_path": "",
        "csv_mtime_ns": None,
        "csv_size": None,
    }


def normalize_last_import(payload: Any) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    out = empty_last_import()
    out["source_type"] = normalize_source_type(data.get("source_type")) if _text(data.get("source_type")) else ""
    out["source_label"] = _text(data.get("source_label"))
    out["imported_at"] = _text(data.get("imported_at"))
    out["imported_by"] = _text(data.get("imported_by"))
    out["row_count"] = _int_or_none(data.get("row_count"))
    out["column_count"] = _int_or_none(data.get("column_count"))
    out["csv_path"] = _text(data.get("csv_path"))
    out["csv_mtime_ns"] = _int_or_none(data.get("csv_mtime_ns"))
    out["csv_size"] = _int_or_none(data.get("csv_size"))
    return out


def empty_refresh_scope() -> Dict[str, Any]:
    """The scope of the last Engine refresh: what it regenerated, by whom, when.

    Shared by every user of the project, so the next import opens on the same
    choice. Empty lists mean everything, which is also what a project that has
    never been narrowed records.
    """
    return {
        "dataset_types": [],
        "reserving_class_types": [],
        "chosen_by": "",
        "chosen_at": "",
    }


def normalize_refresh_scope(payload: Any) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    out = empty_refresh_scope()
    seen_types: set = set()
    for item in data.get("dataset_types") or []:
        name = _text(item)
        if name and name.casefold() not in seen_types:
            seen_types.add(name.casefold())
            out["dataset_types"].append(name)
    seen_classes: set = set()
    for item in data.get("reserving_class_types") or []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("Name"))
        level = _int_or_none(item.get("Level"))
        if not name or level is None or level < 1 or (level, name.casefold()) in seen_classes:
            continue
        seen_classes.add((level, name.casefold()))
        out["reserving_class_types"].append({"Name": name, "Level": level})
    out["chosen_by"] = _text(data.get("chosen_by"))
    out["chosen_at"] = _text(data.get("chosen_at"))
    return out


def normalize_source_import(payload: Any, project_name: str = "") -> Dict[str, Any]:
    """Return the full canonical `source_import.json` payload.

    Every producer of this file must emit exactly this shape so the parsed
    payloads stay identical for the same logical inputs.
    """
    data = payload if isinstance(payload, dict) else {}
    source_type = normalize_source_type(data.get("source_type"))
    out = {
        "json_format": SOURCE_IMPORT_JSON_FORMAT,
        "project_name": _text(data.get("project_name")) or _text(project_name),
        "source_type": source_type,
        "mssql": normalize_mssql_profile(data.get("mssql")),
        "last_import": normalize_last_import(data.get("last_import")),
        "refresh_scope": normalize_refresh_scope(data.get("refresh_scope")),
    }
    # Single-table records keep exactly their historical shape: the block is
    # emitted only for a combined source.
    if source_type == SOURCE_TYPE_COMBINED:
        out["combined"] = normalize_combined_source(data.get("combined"))
    return out


def _normalize_combined_table(item: Any) -> Dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    table_type = SOURCE_TYPE_MSSQL if _text(data.get("source_type")).lower() == SOURCE_TYPE_MSSQL else SOURCE_TYPE_CSV
    table: Dict[str, Any] = {
        "id": _text(data.get("id")),
        "nickname": _text(data.get("nickname"))[:COMBINED_NICKNAME_MAX].strip(),
        "source_type": table_type,
    }
    if table_type == SOURCE_TYPE_MSSQL:
        table["mssql"] = normalize_mssql_profile(data.get("mssql"))
    else:
        # Only stripped here; translating a drive letter to the share is the
        # caller's job (`normalize_import_source_path`).
        table["csv_path"] = _text(data.get("csv_path"))
    return table


def _normalize_key_map_entry(entry: Any) -> Optional[Dict[str, Any]]:
    data = entry if isinstance(entry, dict) else {}
    column = _text(data.get("column"))
    if column:
        out: Dict[str, Any] = {"column": column}
        if _text(data.get("convert")).lower() == COMBINED_KEY_CONVERT_YYYYMM:
            out["convert"] = COMBINED_KEY_CONVERT_YYYYMM
        return out
    if "fill" in data and data.get("fill") is not None:
        return {"fill": _text(data.get("fill"))}
    if data.get("any") is True:
        return {"any": True}
    return None


def normalize_combined_source(payload: Any) -> Dict[str, Any]:
    """Canonical `combined` block of a combined source's `source_import.json`.

    Every table is outer-joined on the keys, so no row of any table is lost;
    the first table names the keys. A legacy ``rows`` entry is dropped. Table
    ids are de-duplicated (first wins), entries naming an unknown table are
    dropped, and every per-table map follows table order so the payload is
    deterministic.
    """
    data = payload if isinstance(payload, dict) else {}
    tables = []
    seen_ids: set = set()
    for item in data.get("tables") if isinstance(data.get("tables"), list) else []:
        table = _normalize_combined_table(item)
        if not table["id"] or table["id"] in seen_ids:
            continue
        seen_ids.add(table["id"])
        tables.append(table)
    ids = [table["id"] for table in tables]

    keys = []
    seen_keys: set = set()
    for item in data.get("keys") if isinstance(data.get("keys"), list) else []:
        key = item if isinstance(item, dict) else {}
        name = _text(key.get("name"))
        if not name or name.casefold() in seen_keys:
            continue
        seen_keys.add(name.casefold())
        raw_map = key.get("map") if isinstance(key.get("map"), dict) else {}
        key_map: Dict[str, Any] = {}
        for table_id in ids:
            entry = _normalize_key_map_entry(raw_map.get(table_id))
            if entry is not None:
                key_map[table_id] = entry
        keys.append({"name": name, "map": key_map})

    raw_exclude = data.get("exclude") if isinstance(data.get("exclude"), dict) else {}
    exclude: Dict[str, Any] = {}
    for table_id in ids:
        columns = []
        for column in raw_exclude.get(table_id) if isinstance(raw_exclude.get(table_id), list) else []:
            name = _text(column)
            if name and name not in columns:
                columns.append(name)
        if columns:
            exclude[table_id] = columns

    raw_rename = data.get("rename") if isinstance(data.get("rename"), dict) else {}
    rename: Dict[str, Any] = {}
    for table_id in ids:
        source = raw_rename.get(table_id) if isinstance(raw_rename.get(table_id), dict) else {}
        names = {}
        for old, new in source.items():
            old_name, new_name = _text(old), _text(new)
            if old_name and new_name and old_name != new_name:
                names[old_name] = new_name
        if names:
            rename[table_id] = names

    return {
        "tables": tables,
        "keys": keys,
        "exclude": exclude,
        "rename": rename,
    }


def combined_table_name(table: Any) -> str:
    """A combined-source table's own name: the SQL table, or the CSV file name."""
    data = _normalize_combined_table(table)
    if data["source_type"] == SOURCE_TYPE_MSSQL:
        return data["mssql"]["table"]
    base = data["csv_path"].replace("/", "\\").rsplit("\\", 1)[-1]
    return os.path.splitext(base)[0]


def combined_source_label(combined: Any) -> str:
    """Display label such as ``Combined: Loss, Closed, Reported, EP``."""
    tables = normalize_combined_source(combined)["tables"]
    names = [table["nickname"] or combined_table_name(table) for table in tables]
    return "Combined: " + ", ".join(names)


def csv_identity(csv_path: str) -> Dict[str, Any]:
    """Identity of an external CSV used to decide whether a re-copy is due."""
    clean = _text(csv_path)
    identity: Dict[str, Any] = {
        "csv_path": clean,
        "csv_mtime_ns": None,
        "csv_size": None,
    }
    if not clean:
        return identity
    stat = os.stat(clean)
    identity["csv_mtime_ns"] = int(stat.st_mtime_ns)
    identity["csv_size"] = int(stat.st_size)
    return identity


def same_csv_identity(last_import: Any, identity: Dict[str, Any]) -> bool:
    """True when the recorded CSV import already matches `identity`."""
    recorded = normalize_last_import(last_import)
    if recorded.get("source_type") != SOURCE_TYPE_CSV:
        return False
    if recorded.get("csv_mtime_ns") is None or recorded.get("csv_size") is None:
        return False
    return (
        os.path.normcase(os.path.normpath(recorded.get("csv_path") or ""))
        == os.path.normcase(os.path.normpath(_text(identity.get("csv_path"))))
        and recorded.get("csv_mtime_ns") == identity.get("csv_mtime_ns")
        and recorded.get("csv_size") == identity.get("csv_size")
    )


# --- Shared SQL Server connection history --------------------------------
# Server-shared preference: every user of one Arco Server sees the same list
# of previously used server/database pairs. It records identifiers only - no
# credentials, and no table name, because the table is a per-project choice.
MSSQL_CONNECTIONS_FILE = "mssql_connections.json"
MSSQL_CONNECTIONS_VERSION = 1


def connection_key(server: Any, database: Any) -> str:
    """Case-insensitive identity of one server/database pair."""
    return f"{_text(server).casefold()}\x1f{_text(database).casefold()}"


def normalize_mssql_connection(entry: Any) -> Dict[str, str]:
    data = entry if isinstance(entry, dict) else {}
    return {
        "server": _text(data.get("server")),
        "database": _text(data.get("database")),
        "last_used_at": _text(data.get("last_used_at")),
    }


def normalize_mssql_connections(payload: Any) -> Dict[str, Any]:
    """Full canonical `mssql_connections.json` payload.

    Entries are de-duplicated case-insensitively, incomplete pairs are dropped,
    and the list is ordered most-recently-used first so the UI can present it
    without re-sorting.
    """
    data = payload if isinstance(payload, dict) else {}
    raw = data.get("connections")
    seen: set[str] = set()
    entries: list[Dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        entry = normalize_mssql_connection(item)
        if not entry["server"] or not entry["database"]:
            continue
        key = connection_key(entry["server"], entry["database"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    entries.sort(key=lambda item: item["last_used_at"], reverse=True)
    return {
        "version": MSSQL_CONNECTIONS_VERSION,
        "connections": entries,
    }


def upsert_mssql_connection(
    payload: Any,
    server: Any,
    database: Any,
    used_at: str,
) -> Dict[str, Any]:
    """Record one pair as most recently used, replacing any prior casing."""
    normalized = normalize_mssql_connections(payload)
    target = connection_key(server, database)
    kept = [
        entry for entry in normalized["connections"]
        if connection_key(entry["server"], entry["database"]) != target
    ]
    kept.append(
        {
            "server": _text(server),
            "database": _text(database),
            "last_used_at": _text(used_at),
        }
    )
    return normalize_mssql_connections({"connections": kept})


def remove_mssql_connections(
    payload: Any,
    server: Any,
    database: Optional[Any] = None,
) -> Dict[str, Any]:
    """Drop one pair, or every pair for a server when `database` is omitted."""
    normalized = normalize_mssql_connections(payload)
    server_key = _text(server).casefold()
    if database is None:
        kept = [
            entry for entry in normalized["connections"]
            if _text(entry["server"]).casefold() != server_key
        ]
    else:
        target = connection_key(server, database)
        kept = [
            entry for entry in normalized["connections"]
            if connection_key(entry["server"], entry["database"]) != target
        ]
    return normalize_mssql_connections({"connections": kept})


def mssql_source_label(profile: Any) -> str:
    """Stable display label for a SQL Server import source."""
    normalized = normalize_mssql_profile(profile)
    parts = [normalized["server"], normalized["database"], normalized["table"]]
    return ".".join(part for part in parts if part)
