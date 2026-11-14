"""Dashboards: the saved files, the reusable library, and loading a data source.

A dashboard is one JSON file (`config.DASHBOARD_EXT`) in the signed-in user's
folder on the Arco Server (`users/<login>/dashboards`), reached through the
Gateway so it follows the user to any PC. It names its data sources, its pages
and the widgets on them, and it may keep the last table each source returned so
it opens without waiting for the server. The samples that ship with the app sit
read-only in `config.DEFAULT_DASHBOARDS_DIR` on this PC; saving one writes a
copy to the user's folder.

The library holds reusable widgets: the built-in ones in the shipped
`library.json`, and one file per widget the user saved, in the `library`
folder beside their dashboards.

`load_source` is the one way a source becomes a table. Project data comes from
the server host through the registered `dashboard_dataset_table` and
`dashboard_source_table` reads, once per project a source names, and the answers
are joined with a `Project` column so one chart can compare valuations. A CSV
file and a SQL query are read on this PC, because the file may be on a drive
only this PC has and SQL Server signs in as this Windows user.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pandas as pd
from fastapi import HTTPException

from arcrho_api.io import persisted_json_text

from app_server import config
from app_server.services import (
    dashboard_data_service,
    server_user_profile_service,
    snowflake_service,
    sql_server_service,
    workspace_mutation_client,
    workspace_read_client,
)


DASHBOARD_FORMAT = "arco-dashboard"
DASHBOARD_VERSION = 1
ASSET_FORMAT = "arco-dashboard-asset"
PROJECT_COLUMN = "Project"
SOURCE_KINDS = ("arco_datasets", "arco_source_table", "csv", "sql")
USER_ASSET_PREFIX = "user:"


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: os.PathLike[str] | str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def _write_json(path: os.PathLike[str] | str, data: Dict[str, Any]) -> None:
    target = str(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp_path = f"{target}.tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(persisted_json_text(data))
    os.replace(temp_path, target)


def _file_name(name: str) -> str:
    return config.encode_filename_segment(_text(name)) or "Dashboard"


def _is_sample(path: str) -> bool:
    """Whether *path* names one of the dashboards that ship with the app."""

    target = Path(_text(path))
    if not target.is_absolute():
        return False
    try:
        target.resolve().relative_to(Path(config.DEFAULT_DASHBOARDS_DIR).resolve())
    except ValueError:
        return False
    return True


def _hosted_read(kind: str, kwargs: Dict[str, Any], local: Any) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(kind, kwargs, local=lambda: local(**kwargs))


def _hosted_change(kind: str, kwargs: Dict[str, Any], local: Any) -> Dict[str, Any]:
    return workspace_mutation_client.run_workspace_mutation(kind, kwargs, local=lambda: local(**kwargs))


# ---------------------------------------------------------------------------
# Dashboard files
#
# A user's dashboards live in their folder on the server and are named by file
# name alone, so the same name means the same dashboard on every PC. The
# `*_user_*` functions run on the server host; the others are what the routes
# call, and add the samples that ship with the app, which are read on this PC.
# ---------------------------------------------------------------------------

def _user_dir() -> Path:
    return Path(server_user_profile_service.user_folder(config.SERVER_USER_DASHBOARDS_SUBDIR))


def _user_file(name: str) -> Path:
    """The user's dashboard file called *name*; only the file name is used."""

    target = _user_dir() / Path(_text(name)).name
    if target.suffix.lower() != config.DASHBOARD_EXT:
        raise HTTPException(400, "Not a dashboard file.")
    return target


def _summary(path: Path, *, sample: bool) -> Dict[str, Any] | None:
    try:
        data = _read_json(path)
        modified = os.path.getmtime(path)
    except (OSError, ValueError):
        return None
    if data.get("format") != DASHBOARD_FORMAT:
        return None
    pages = [page for page in data.get("pages") or [] if isinstance(page, dict)]
    projects: List[str] = []
    for source in data.get("sources") or []:
        for project in source_projects(source if isinstance(source, dict) else {}):
            if project["name"] not in projects:
                projects.append(project["name"])
    return {
        "name": _text(data.get("name")) or path.stem,
        "description": _text(data.get("description")),
        "path": str(path) if sample else path.name,
        "sample": sample,
        "modified": datetime.fromtimestamp(modified, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "page_count": len(pages),
        "widget_count": sum(len(page.get("widgets") or []) for page in pages),
        "projects": projects,
    }


def _list_folder(folder: Path, *, sample: bool) -> List[Dict[str, Any]]:
    try:
        entries = sorted(folder.iterdir(), key=lambda entry: entry.name.casefold())
    except OSError:
        return []
    found = []
    for entry in entries:
        if entry.suffix.lower() != config.DASHBOARD_EXT or not entry.is_file():
            continue
        summary = _summary(entry, sample=sample)
        if summary:
            found.append(summary)
    return found


def _read_dashboard(target: Path) -> Dict[str, Any]:
    try:
        data = _read_json(target)
    except FileNotFoundError:
        raise HTTPException(404, f"Dashboard not found: {target.name}")
    except (OSError, ValueError) as error:
        raise HTTPException(400, f"The dashboard file could not be read: {error}")
    if data.get("format") != DASHBOARD_FORMAT:
        raise HTTPException(400, "Not a dashboard file.")
    return data


def list_user_dashboards() -> Dict[str, Any]:
    return {"ok": True, "dashboards": _list_folder(_user_dir(), sample=False)}


def load_user_dashboard(name: str) -> Dict[str, Any]:
    target = _user_file(name)
    return {"ok": True, "path": target.name, "sample": False, "data": _read_dashboard(target)}


def save_user_dashboard(name: str, data: Dict[str, Any], prev_name: str = "", overwrite: bool = False) -> Dict[str, Any]:
    """Write a dashboard to the user's folder under `name`.

    `prev_name` is the user's file this dashboard was opened from; a save under
    a new name removes it (a rename). Another dashboard already using the name
    is refused with 409 unless `overwrite` is set.
    """

    title = _text(name)
    if not title:
        raise HTTPException(400, "Give the dashboard a name.")
    if not isinstance(data, dict) or data.get("format") != DASHBOARD_FORMAT:
        raise HTTPException(400, "Not a dashboard.")
    target = _user_dir() / f"{_file_name(title)}{config.DASHBOARD_EXT}"
    previous = _user_file(prev_name) if _text(prev_name) else None
    same_file = previous is not None and previous.name.casefold() == target.name.casefold()
    if target.exists() and not same_file and not overwrite:
        raise HTTPException(409, f"A dashboard named \"{title}\" already exists.")
    payload = dict(data)
    payload["name"] = title
    payload["version"] = DASHBOARD_VERSION
    payload["saved_at"] = _now_text()
    try:
        _write_json(target, payload)
        if previous is not None and not same_file and previous.is_file():
            previous.unlink()
    except OSError as error:
        raise HTTPException(500, f"The dashboard could not be saved: {error}")
    return {"ok": True, "path": target.name, "name": title, "saved_at": payload["saved_at"]}


def delete_user_dashboard(name: str) -> Dict[str, Any]:
    target = _user_file(name)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise HTTPException(500, f"The dashboard could not be deleted: {error}")
    return {"ok": True, "path": target.name}


def list_dashboards() -> Dict[str, Any]:
    listing = _hosted_read("dashboard_user_list", {}, list_user_dashboards)
    return {
        "ok": True,
        "dashboards": listing["dashboards"],
        "samples": _list_folder(Path(config.DEFAULT_DASHBOARDS_DIR), sample=True),
    }


def load_dashboard(path: str) -> Dict[str, Any]:
    if _is_sample(path):
        return {"ok": True, "path": _text(path), "sample": True, "data": _read_dashboard(Path(_text(path)))}
    return _hosted_read("dashboard_user_load", {"name": Path(_text(path)).name}, load_user_dashboard)


def save_dashboard(name: str, data: Dict[str, Any], prev_path: str = "", overwrite: bool = False) -> Dict[str, Any]:
    """Save to the user's folder; a sample it was opened from is never touched."""

    kwargs = {
        "name": name,
        "data": data,
        "prev_name": "" if _is_sample(prev_path) else Path(_text(prev_path)).name,
        "overwrite": bool(overwrite),
    }
    return _hosted_change("dashboard_user_save", kwargs, save_user_dashboard)


def delete_dashboard(path: str) -> Dict[str, Any]:
    if _is_sample(path):
        raise HTTPException(400, "Only your own dashboards can be deleted.")
    return _hosted_change("dashboard_user_delete", {"name": Path(_text(path)).name}, delete_user_dashboard)


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def _library_dir() -> Path:
    return _user_dir() / config.DASHBOARD_LIBRARY_SUBDIR


def _normalize_asset(raw: Any, *, builtin: bool, asset_id: str = "") -> Dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("widget"), dict):
        return None
    name = _text(raw.get("name"))
    if not name:
        return None
    return {
        "id": asset_id or _text(raw.get("id")) or name,
        "name": name,
        "category": _text(raw.get("category")) or "My Library",
        "description": _text(raw.get("description")),
        "builtin": builtin,
        "widget": raw["widget"],
    }


def list_user_library() -> Dict[str, Any]:
    assets: List[Dict[str, Any]] = []
    try:
        entries = sorted(_library_dir().glob("*.json"), key=lambda entry: entry.name.casefold())
    except OSError:
        entries = []
    for entry in entries:
        try:
            raw = _read_json(entry)
        except (OSError, ValueError):
            continue
        asset = _normalize_asset(raw, builtin=False, asset_id=f"{USER_ASSET_PREFIX}{entry.stem}")
        if asset:
            assets.append(asset)
    return {"ok": True, "assets": assets}


def list_library() -> Dict[str, Any]:
    """The built-in items that ship with the app, then the user's own."""

    assets: List[Dict[str, Any]] = []
    try:
        shipped = _read_json(Path(config.DEFAULT_DASHBOARDS_DIR) / config.DEFAULT_DASHBOARD_LIBRARY_FILE)
    except (OSError, ValueError):
        shipped = {}
    for raw in shipped.get("assets") or []:
        asset = _normalize_asset(raw, builtin=True)
        if asset:
            assets.append(asset)
    assets.extend(_hosted_read("dashboard_user_library", {}, list_user_library)["assets"])
    return {"ok": True, "assets": assets}


def save_user_library_asset(name: str, widget: Dict[str, Any], category: str = "", description: str = "") -> Dict[str, Any]:
    title = _text(name)
    if not title:
        raise HTTPException(400, "Give the library item a name.")
    if not isinstance(widget, dict) or not _text(widget.get("type")):
        raise HTTPException(400, "Nothing to save to the library.")
    stem = _file_name(title)
    payload = {
        "format": ASSET_FORMAT,
        "name": title,
        "category": _text(category) or "My Library",
        "description": _text(description),
        "widget": widget,
    }
    try:
        _write_json(_library_dir() / f"{stem}.json", payload)
    except OSError as error:
        raise HTTPException(500, f"The library item could not be saved: {error}")
    return {"ok": True, "asset": _normalize_asset(payload, builtin=False, asset_id=f"{USER_ASSET_PREFIX}{stem}")}


def save_library_asset(name: str, widget: Dict[str, Any], category: str = "", description: str = "") -> Dict[str, Any]:
    kwargs = {"name": name, "widget": widget, "category": category, "description": description}
    return _hosted_change("dashboard_user_library_save", kwargs, save_user_library_asset)


def delete_user_library_asset(asset_id: str) -> Dict[str, Any]:
    key = _text(asset_id)
    if not key.startswith(USER_ASSET_PREFIX):
        raise HTTPException(400, "Built-in library items cannot be deleted.")
    target = _library_dir() / f"{Path(key[len(USER_ASSET_PREFIX):]).name}.json"
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    except OSError as error:
        raise HTTPException(500, f"The library item could not be deleted: {error}")
    return {"ok": True, "id": key}


def delete_library_asset(asset_id: str) -> Dict[str, Any]:
    return _hosted_change("dashboard_user_library_delete", {"asset_id": asset_id}, delete_user_library_asset)


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

def source_projects(source: Dict[str, Any]) -> List[Dict[str, str]]:
    """The projects a source reads, each with the label its rows carry.

    `projects` is a list of `{name, label}`; a bare name and the single
    `project` field mean the same thing with the name as the label.
    """

    raw = source.get("projects")
    items = raw if isinstance(raw, list) and raw else [source.get("project")]
    projects: List[Dict[str, str]] = []
    for item in items:
        name = _text(item.get("name") if isinstance(item, dict) else item)
        label = _text(item.get("label")) if isinstance(item, dict) else ""
        if name and all(existing["name"] != name for existing in projects):
            projects.append({"name": name, "label": label or name})
    return projects


_LEADING_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def _merged_order(orders: Sequence[Sequence[Any]]) -> List[str]:
    """One natural order from each project's own (`8m, 20m` beside `5m, 17m`)."""

    merged: List[str] = []
    for order in orders:
        for label in order:
            text = str(label)
            if text not in merged:
                merged.append(text)
    numbers = [_LEADING_NUMBER.match(label) for label in merged]
    if merged and all(numbers):
        merged.sort(key=lambda label: float(_LEADING_NUMBER.match(label).group(1)))
    return merged


def merge_project_tables(tables: Sequence[tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Stack one table per project under a leading `Project` column.

    Columns are matched by name, so a dataset one project lacks is blank on
    that project's rows. A column's natural order is merged across projects.
    """

    labels = [label for label, _table in tables]
    columns: List[Dict[str, Any]] = []
    index_of: Dict[str, int] = {}
    orders: Dict[str, List[Sequence[Any]]] = {}
    for _label, table in tables:
        for column in table.get("columns") or []:
            name = column["name"]
            if name not in index_of:
                index_of[name] = len(columns)
                columns.append(dict(column))
            if column.get("order"):
                orders.setdefault(name, []).append(column["order"])
    for name, found in orders.items():
        columns[index_of[name]]["order"] = _merged_order(found)

    rows: List[List[Any]] = []
    missing: List[Dict[str, str]] = []
    source_rows = 0
    for label, table in tables:
        positions = [index_of[column["name"]] for column in table.get("columns") or []]
        for row in table.get("rows") or []:
            merged_row: List[Any] = [None] * len(columns)
            for position, value in zip(positions, row):
                merged_row[position] = value
            rows.append([label, *merged_row])
        for item in table.get("missing") or []:
            missing.append({"project": label, **item})
        source_rows += int(table.get("source_rows") or 0)

    project_column = dashboard_data_service.column_spec(PROJECT_COLUMN, "text", order=labels)
    extra: Dict[str, Any] = {"missing": missing}
    if source_rows:
        extra["source_rows"] = source_rows
    semi_additive = next((table.get("semi_additive") for _label, table in tables if table.get("semi_additive")), None)
    if semi_additive:
        extra["semi_additive"] = {
            "partition": [PROJECT_COLUMN, *semi_additive["partition"]],
            "order": semi_additive["order"],
        }
    if len(rows) > dashboard_data_service.MAX_TABLE_ROWS:
        raise HTTPException(
            422,
            f"These projects give {len(rows):,} rows; a dashboard table holds at most "
            f"{dashboard_data_service.MAX_TABLE_ROWS:,}. Choose fewer projects or fields.",
        )
    return dashboard_data_service.table_payload([project_column, *columns], rows, **extra)


def _load_project_source(source: Dict[str, Any]) -> Dict[str, Any]:
    projects = source_projects(source)
    if not projects:
        raise HTTPException(400, "Choose a project for this data source.")
    kind = source["kind"]
    tables = []
    for project in projects:
        if kind == "arco_datasets":
            kwargs: Dict[str, Any] = {
                "project_name": project["name"],
                "reserving_classes": list(source.get("reserving_classes") or []),
                "dataset_names": list(source.get("datasets") or []),
                "level_names": list(source.get("level_names") or []),
            }
            read = dashboard_data_service.read_dataset_table
            read_kind = "dashboard_dataset_table"
        else:
            kwargs = {
                "project_name": project["name"],
                "dimensions": list(source.get("dimensions") or []),
                "measures": list(source.get("measures") or []),
            }
            read = dashboard_data_service.read_source_table
            read_kind = "dashboard_source_table"
        table = workspace_read_client.run_workspace_read(
            read_kind, kwargs, local=lambda read=read, kwargs=kwargs: read(**kwargs),
        )
        tables.append((project["label"], table))
    return merge_project_tables(tables)


def _read_csv_file(path: str, **options: Any) -> pd.DataFrame:
    target = _text(path)
    if not target:
        raise HTTPException(400, "Choose a CSV file for this data source.")
    try:
        return pd.read_csv(target, encoding="utf-8-sig", low_memory=False, **options)
    except FileNotFoundError:
        raise HTTPException(404, f"File not found: {target}")
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise HTTPException(400, f"The file could not be read as a table: {error}")


def _load_csv_source(source: Dict[str, Any]) -> Dict[str, Any]:
    frame = _read_csv_file(source.get("path"))
    return dashboard_data_service.aggregate_frame(
        frame, source.get("dimensions") or [], source.get("measures") or [],
    )


def _load_sql_source(source: Dict[str, Any]) -> Dict[str, Any]:
    sql = _text(source.get("sql"))
    if not sql:
        raise HTTPException(400, "Enter a query for this data source.")
    engine = _text(source.get("engine")).lower() or "sqlserver"
    connection = _text(source.get("connection"))
    # The console services own the row ceiling a query may return.
    if engine == "snowflake":
        result = snowflake_service.run_query(sql, connection or snowflake_service.DEFAULT_CONNECTION_NAME, 10**9)
    elif engine == "sqlserver":
        result = sql_server_service.run_query(sql, connection, 10**9)
    else:
        raise HTTPException(400, f"Unknown SQL engine: {engine}")
    if not result.get("ok"):
        raise HTTPException(400, _text(result.get("error")) or "The query failed.")
    columns = [str(name) for name in result.get("columns") or []]
    if not columns:
        raise HTTPException(400, "The query returned no table.")
    frame = pd.DataFrame(result.get("rows") or [], columns=columns)
    for name in columns:
        numeric = pd.to_numeric(frame[name], errors="coerce")
        if frame[name].notna().any() and numeric.notna().sum() == frame[name].notna().sum():
            frame[name] = numeric
    return dashboard_data_service.frame_table(frame, truncated=bool(result.get("truncated")))


def _require_kind(source: Any) -> str:
    kind = _text(source.get("kind")) if isinstance(source, dict) else ""
    if kind not in SOURCE_KINDS:
        raise HTTPException(400, "Unknown data source kind.")
    return kind


def load_source(source: Dict[str, Any]) -> Dict[str, Any]:
    """Return the table a dashboard data source describes, read now."""

    kind = _require_kind(source)
    if kind in ("arco_datasets", "arco_source_table"):
        table = _load_project_source(source)
    elif kind == "csv":
        table = _load_csv_source(source)
    else:
        table = _load_sql_source(source)
    table["refreshed_at"] = _now_text()
    return table


def source_fields(source: Dict[str, Any]) -> Dict[str, Any]:
    """The columns a table source offers, before any are chosen.

    The data source dialog lists these so the user picks what to group by and
    what to total. It answers for the imported table of the source's first
    project, or for the head of a CSV file.
    """

    kind = _require_kind(source)
    if kind == "arco_source_table":
        projects = source_projects(source)
        if not projects:
            raise HTTPException(400, "Choose a project for this data source.")
        kwargs = {"project_name": projects[0]["name"]}
        return workspace_read_client.run_workspace_read(
            "dashboard_source_table",
            kwargs,
            local=lambda: dashboard_data_service.read_source_table(**kwargs),
        )
    if kind == "csv":
        head = _read_csv_file(source.get("path"), nrows=200)
        table = dashboard_data_service.frame_table(head)
        table["rows"] = []
        table["row_count"] = 0
        return table
    raise HTTPException(400, "This data source has no field list.")
