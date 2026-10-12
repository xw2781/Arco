"""Combining several source tables into one master table.

A combined source (decision 3 of docs/plans/combined_source_import.md) names
several tables, the keys they share and how each joins onto the running
result. This module is the pure combine engine: it reads the given local CSV
files, joins them as the spec says, and reports what happened to every table.
It does no other I/O; fetching a SQL Server table into a local CSV and
uploading the result belong to the callers.

Every table is read with all columns as text (decision 4), so keys compare
exactly and no value is ever reformatted on its way to the master table.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

import pandas as pd

from arcrho_api.source_table_contract import (
    COMBINED_KEY_CONVERT_YYYYMM,
    COMBINED_ROWS_ALL,
    COMBINED_ROWS_BASE,
    COMBINED_ROWS_MATCH,
    combined_table_name,
    normalize_combined_source,
)

_UNNAMED_COLUMN = re.compile(r"Unnamed: \d+")
_YYYYMM = re.compile(r"\d{6}")
_YYYY_MM = re.compile(r"(\d{4})[-/](\d{1,2})")
_MERGE_HOW = {COMBINED_ROWS_ALL: "outer", COMBINED_ROWS_BASE: "left", COMBINED_ROWS_MATCH: "inner"}
_LEFT_ROW = "__combined_left_row"
_RIGHT_ROW = "__combined_right_row"


def name_token(name: Any) -> str:
    """Comparison form of a column name: case, spaces and underscores ignored."""
    return re.sub(r"[\s_]+", "", str(name)).lower()


def read_table_text(path: str) -> Tuple[pd.DataFrame, List[str]]:
    """Read a CSV with every column as text, as the merge notebook cleans it.

    Empty ``Unnamed: n`` columns and fully blank rows are dropped. Returns the
    frame and the names of the dropped columns.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    dropped = [
        column
        for column in frame.columns
        if _UNNAMED_COLUMN.fullmatch(str(column)) and not frame[column].astype(bool).any()
    ]
    if dropped:
        frame = frame.drop(columns=dropped)
    if len(frame.columns):
        frame = frame[frame.astype(bool).any(axis=1)].reset_index(drop=True)
    return frame, dropped


def _convert_yyyymm(value: str) -> str:
    match = _YYYY_MM.fullmatch(value)
    return f"{match.group(1)}{int(match.group(2)):02d}" if match else value


def _key_values(frame: pd.DataFrame, entry: Optional[Dict[str, Any]]) -> Optional[pd.Series]:
    """A key's values in one table, or None when the key is ignored there."""
    if not entry or entry.get("any"):
        return None
    if "fill" in entry:
        return pd.Series([entry["fill"]] * len(frame), index=frame.index, dtype=object)
    values = frame[entry["column"]].astype(str)
    if entry.get("convert") == COMBINED_KEY_CONVERT_YYYYMM:
        values = values.map(_convert_yyyymm)
    return values


def _first_value(frame: pd.DataFrame, column: str) -> str:
    for value in frame[column]:
        if value:
            return str(value)
    return ""


def _label(table: Dict[str, Any], index: int) -> Tuple[str, str]:
    """(display name, clash suffix) of a table."""
    nickname = table.get("nickname") or ""
    suffix = re.sub(r"\s+", "_", nickname) if nickname else f"T{index + 1}"
    return nickname or combined_table_name(table), suffix


def column_plan(frames_by_id: Mapping[str, pd.DataFrame], combined: Any) -> List[Dict[str, Any]]:
    """Every non-key column of every table and the master column it becomes.

    Entries keep table order, then column order. ``off`` marks a left-out
    column; ``conflict`` marks a name that clashed and got the table's suffix.
    """
    spec = normalize_combined_source(combined)
    used = {name_token(key["name"]) for key in spec["keys"]}
    plan = []
    for index, table in enumerate(spec["tables"]):
        table_id = table["id"]
        key_columns = {
            key["map"][table_id]["column"]
            for key in spec["keys"]
            if "column" in key["map"].get(table_id, {})
        }
        excluded = set(spec["exclude"].get(table_id, []))
        renames = spec["rename"].get(table_id, {})
        suffix = _label(table, index)[1]
        for column in frames_by_id[table_id].columns:
            if column in key_columns:
                continue
            off = column in excluded
            renamed = renames.get(column)
            master = renamed or column
            conflict = False
            if not off:
                if name_token(master) in used and not renamed:
                    conflict = True
                    master = f"{column}_{suffix}"
                used.add(name_token(master))
            plan.append({
                "table_id": table_id,
                "column": column,
                "master": master,
                "off": off,
                "conflict": conflict,
                "renamed": bool(renamed),
            })
    return plan


def _keyed_frame(
    frame: pd.DataFrame,
    table_id: str,
    keys: List[Dict[str, Any]],
    plan: List[Dict[str, Any]],
) -> Tuple[pd.DataFrame, List[str]]:
    """The table as key columns (named by key) plus its kept value columns."""
    data: Dict[str, Any] = {}
    used_keys = []
    for key in keys:
        values = _key_values(frame, key["map"].get(table_id))
        if values is not None:
            data[key["name"]] = values
            used_keys.append(key["name"])
    for item in plan:
        if item["table_id"] == table_id and not item["off"]:
            data[item["master"]] = frame[item["column"]]
    return pd.DataFrame(data, index=frame.index), used_keys


def combine_tables(frames_by_id: Mapping[str, pd.DataFrame], combined: Any) -> Dict[str, Any]:
    """Join the tables as the combined spec says.

    The first table is the base; every other table joins onto the running
    result in list order with its row rule (``all`` outer, ``base`` left,
    ``match`` inner). Returns ``frame`` (keys first, then value columns in
    table order, every value text), ``plan`` (see ``column_plan``), ``stats``
    per table id and ``warnings``.
    """
    spec = normalize_combined_source(combined)
    tables, keys = spec["tables"], spec["keys"]
    key_names = [key["name"] for key in keys]
    plan = column_plan(frames_by_id, spec)
    base = tables[0]

    result, _ = _keyed_frame(frames_by_id[base["id"]], base["id"], keys, plan)
    for name in key_names:
        if name not in result.columns:
            result[name] = ""
    stats: Dict[str, Dict[str, Any]] = {base["id"]: {"read": len(result)}}

    for table in tables[1:]:
        table_id = table["id"]
        rule = spec["rows"].get(table_id, COMBINED_ROWS_ALL)
        right, join_keys = _keyed_frame(frames_by_id[table_id], table_id, keys, plan)
        left = result.reset_index(drop=True)
        left[_LEFT_ROW] = range(len(left))
        right = right.reset_index(drop=True)
        right[_RIGHT_ROW] = range(len(right))
        if join_keys:
            merged = left.merge(right, how=_MERGE_HOW[rule], on=join_keys, sort=False)
        else:
            merged = left.merge(right, how="cross")
        merged = merged.sort_values([_LEFT_ROW, _RIGHT_ROW], na_position="last", kind="stable")

        both = merged[merged[_LEFT_ROW].notna() & merged[_RIGHT_ROW].notna()]
        hits = both[_RIGHT_ROW].value_counts()
        matched = int(len(hits))
        added = int((merged[_LEFT_ROW].isna()).sum())
        dropped_base = len(left) - int(both[_LEFT_ROW].nunique()) if rule == COMBINED_ROWS_MATCH else 0
        stats[table_id] = {
            "read": len(right),
            "matched": matched,
            "added": added,
            "left_out": len(right) - matched - added,
            "base_rows_dropped": dropped_base,
            "max_repeat": int(hits.max()) if matched else 0,
        }
        result = merged.drop(columns=[_LEFT_ROW, _RIGHT_ROW]).fillna("").reset_index(drop=True)

    masters = [item["master"] for item in plan if not item["off"]]
    frame = result[key_names + masters].fillna("").astype(str).reset_index(drop=True)
    return {
        "frame": frame,
        "plan": plan,
        "stats": stats,
        "warnings": _warnings(frames_by_id, spec, plan, stats),
    }


def _warnings(
    frames_by_id: Mapping[str, pd.DataFrame],
    spec: Dict[str, Any],
    plan: List[Dict[str, Any]],
    stats: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    tables, keys = spec["tables"], spec["keys"]
    base = tables[0]
    labels = {table["id"]: _label(table, index)[0] for index, table in enumerate(tables)}
    out: List[Dict[str, Any]] = []
    for table in tables[1:]:
        table_id = table["id"]
        table_stats = stats[table_id]
        for key in keys:
            entry = key["map"].get(table_id, {})
            base_entry = key["map"].get(base["id"], {})
            if "column" not in entry or entry.get("convert") or "column" not in base_entry:
                continue
            sample = _first_value(frames_by_id[table_id], entry["column"])
            base_sample = _first_value(frames_by_id[base["id"]], base_entry["column"])
            if _YYYY_MM.fullmatch(sample) and _YYYYMM.fullmatch(base_sample):
                out.append({
                    "kind": "format_mismatch",
                    "table_id": table_id,
                    "table": labels[table_id],
                    "key": key["name"],
                    "sample": sample,
                    "base_sample": base_sample,
                    "matched": table_stats["matched"],
                    "fix": {"convert": COMBINED_KEY_CONVERT_YYYYMM},
                })
        if table_stats["max_repeat"] > 1:
            out.append({
                "kind": "repeat",
                "table_id": table_id,
                "table": labels[table_id],
                "max_repeat": table_stats["max_repeat"],
                "any_keys": [key["name"] for key in keys if key["map"].get(table_id, {}).get("any") or not key["map"].get(table_id)],
            })
        fills = [key for key in keys if "fill" in key["map"].get(table_id, {})]
        if fills and table_stats["added"]:
            out.append({
                "kind": "filled_rows",
                "table_id": table_id,
                "table": labels[table_id],
                "fills": {key["name"]: key["map"][table_id]["fill"] for key in fills},
                "added": table_stats["added"],
            })
    for item in plan:
        if item["conflict"]:
            out.append({
                "kind": "name_clash",
                "table_id": item["table_id"],
                "table": labels[item["table_id"]],
                "column": item["column"],
                "master": item["master"],
            })
    return out


def write_combined_csv(frame: pd.DataFrame, path: str) -> None:
    """Write the combined table as UTF-8 CSV with no index, values unchanged."""
    frame.to_csv(path, index=False, encoding="utf-8")


def preview_rows(frame: pd.DataFrame, key_names: List[str], limit: int = 14) -> List[Dict[str, str]]:
    """The first ``limit`` rows ordered by the keys as text."""
    ordered = frame.sort_values(list(key_names), kind="stable") if key_names else frame
    return ordered.head(limit).to_dict(orient="records")
