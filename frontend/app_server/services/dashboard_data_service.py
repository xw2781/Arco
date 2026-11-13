"""Dashboard data tables read from an Arco project.

A dashboard charts flat tables: named columns and rows of scalars. This module
turns the two kinds of project data into that shape, and owns the shape itself
(`table_payload`) so a table built from an external CSV or a SQL query in
`dashboard_service` is the same document.

Both project reads are registered Server-hosted workspace reads
(`arcrho_workspace_read_contract`: `dashboard_dataset_table` and
`dashboard_source_table`). They run where the project folder is local disk, so
one request answers for every reserving class a dashboard names and a Client PC
never opens a dataset or the imported table over the share. Neither writes:
`read_source_table` reads the imported table as it stands, because the source
refresh job owns that copy.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd
from fastapi import HTTPException

from app_server.services import dataset_service, field_mapping_service, source_table_service


TABLE_FORMAT = "arco-dashboard-table-v1"
# A dashboard table is charted in the browser and may be kept inside the saved
# dashboard file, so it is bounded. A table over the limit is refused with the
# way out (group by fewer fields) rather than cut short, because a truncated
# aggregate would chart wrong totals without saying so.
MAX_TABLE_ROWS = 100_000
# An external table read without grouping is a preview of raw rows, cut here.
MAX_RAW_ROWS = 50_000

SEGMENT_COLUMN = "Segment"
SEGMENT_NAME_COLUMN = "Segment Name"
ORIGIN_COLUMN = "Origin"
ORIGIN_YEAR_COLUMN = "Origin Year"
DEVELOPMENT_COLUMN = "Development"
ROW_COUNT_COLUMN = "Rows"
# A date column offered as a coarser grouping: `<column>:year` in a request
# becomes the column `<column> Year` in the table.
DATE_PARTS = {"year": "Year", "quarter": "Quarter", "month": "Month"}


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _text_list(values: Any) -> List[str]:
    if not isinstance(values, (list, tuple)):
        return []
    seen: List[str] = []
    for value in values:
        text = _text(value)
        if text and text not in seen:
            seen.append(text)
    return seen


def json_scalar(value: Any) -> Any:
    """One table cell as JSON: a number, text, a boolean, or null for a gap."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        # Six decimals is finer than any chart or ratio shows, and it keeps a
        # summed 1948322.4400000002 from doubling the size of a saved table.
        return round(value, 6) if math.isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return json_scalar(value.item())
        except (TypeError, ValueError):
            return None
    if value is pd.NaT:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def column_spec(name: str, kind: str, **extra: Any) -> Dict[str, Any]:
    """One table column. `kind` is `number` or `text`; `role` says how a chart
    should offer it (`measure` to aggregate, `dimension` to group by)."""

    spec: Dict[str, Any] = {
        "name": str(name),
        "type": kind,
        "role": "measure" if kind == "number" else "dimension",
    }
    spec.update({key: value for key, value in extra.items() if value not in (None, "", [])})
    return spec


def table_payload(
    columns: Sequence[Dict[str, Any]],
    rows: Iterable[Sequence[Any]],
    **extra: Any,
) -> Dict[str, Any]:
    """The one shape every dashboard table has, whatever it was read from."""

    row_list = [[json_scalar(cell) for cell in row] for row in rows]
    payload: Dict[str, Any] = {
        "ok": True,
        "format": TABLE_FORMAT,
        "columns": [dict(column) for column in columns],
        "rows": row_list,
        "row_count": len(row_list),
    }
    payload.update(extra)
    return payload


def frame_table(frame: pd.DataFrame, **extra: Any) -> Dict[str, Any]:
    """A table from a data frame, typing each column from its values."""

    columns = []
    for name in frame.columns:
        series = frame[name]
        numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
        columns.append(column_spec(str(name), "number" if numeric else "text"))
    cleaned = frame.astype(object).where(pd.notna(frame), None)
    return table_payload(columns, cleaned.itertuples(index=False, name=None), **extra)


def _date_part(series: pd.Series, part: str) -> pd.Series:
    """A reserving period column (`202608`, or a date) at a coarser grain."""

    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any() and numeric.dropna().between(100_000, 999_999).all():
        year = numeric // 100
        month = numeric % 100
    else:
        dates = pd.to_datetime(series, errors="coerce")
        year = dates.dt.year
        month = dates.dt.month
    year_text = year.astype("Int64").astype(str)
    if part == "year":
        return year_text.where(year.notna(), None)
    if part == "quarter":
        quarter = ((month - 1) // 3 + 1).astype("Int64").astype(str)
        return (year_text + " Q" + quarter).where(year.notna(), None)
    month_text = month.astype("Int64").astype(str).str.zfill(2)
    return (year_text + "-" + month_text).where(year.notna(), None)


def _split_field(field: str) -> tuple[str, str]:
    name, separator, part = field.rpartition(":")
    if separator and part.lower() in DATE_PARTS:
        return name, part.lower()
    return field, ""


def source_columns_needed(dimensions: Sequence[str], measures: Sequence[str]) -> List[str]:
    """The table's own columns a grouping reads, in first-use order."""

    needed: List[str] = []
    for field in [*dimensions, *measures]:
        name = _split_field(field)[0]
        if name and name not in needed:
            needed.append(name)
    return needed


def aggregate_frame(
    frame: pd.DataFrame,
    dimensions: Sequence[str],
    measures: Sequence[str],
    *,
    row_limit: int = MAX_TABLE_ROWS,
) -> Dict[str, Any]:
    """Group `frame` by `dimensions` and total `measures`.

    With neither named, the table is the frame's own rows, cut at
    `MAX_RAW_ROWS`. A grouped result over `row_limit` is refused.
    """

    dims = _text_list(dimensions)
    values = _text_list(measures)
    missing = [name for name in source_columns_needed(dims, values) if name not in frame.columns]
    if missing:
        raise HTTPException(400, f"The table has no column named: {', '.join(missing)}")
    if not dims and not values:
        truncated = len(frame) > MAX_RAW_ROWS
        return frame_table(frame.head(MAX_RAW_ROWS), source_rows=int(len(frame)), truncated=truncated)

    working = pd.DataFrame(index=frame.index)
    dim_names: List[str] = []
    for field in dims:
        name, part = _split_field(field)
        label = f"{name} {DATE_PARTS[part]}" if part else name
        column = _date_part(frame[name], part) if part else frame[name].astype(object)
        working[label] = column.where(pd.notna(column), None)
        dim_names.append(label)
    for name in values:
        working[name] = pd.to_numeric(frame[name], errors="coerce")
    working[ROW_COUNT_COLUMN] = 1

    if dim_names:
        grouped = working.groupby(dim_names, dropna=False, sort=True)
        totals = grouped[[*values, ROW_COUNT_COLUMN]].sum(min_count=1).reset_index()
    else:
        totals = working[[*values, ROW_COUNT_COLUMN]].sum(min_count=1).to_frame().T
    if len(totals) > row_limit:
        raise HTTPException(
            422,
            f"This grouping gives {len(totals):,} rows; a dashboard table holds at most {row_limit:,}. "
            "Group by fewer fields.",
        )
    columns = [column_spec(name, "text") for name in dim_names]
    columns += [column_spec(name, "number") for name in [*values, ROW_COUNT_COLUMN]]
    cleaned = totals.astype(object).where(pd.notna(totals), None)
    return table_payload(
        columns,
        cleaned.itertuples(index=False, name=None),
        source_rows=int(len(frame)),
        truncated=False,
    )


def read_source_table(
    project_name: str,
    dimensions: Optional[Sequence[str]] = None,
    measures: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """The project's imported table, grouped by `dimensions` with `measures` totalled.

    A dimension may name a date part of a mapped date column, such as
    `acc_yrmo:year`. With no fields named the answer is the column list alone,
    which is what the data source dialog asks for first.
    """

    name = _text(project_name)
    if not name:
        raise HTTPException(400, "project_name is required")
    master_path = source_table_service.imported_master_table_path(name)
    if not master_path:
        raise HTTPException(404, f"Project has no imported source table: {name}")
    dims = _text_list(dimensions)
    values = _text_list(measures)
    date_roles = field_mapping_service.load_date_role_fields(name)
    if not dims and not values:
        header = pd.read_csv(master_path, nrows=200, encoding="utf-8-sig")
        columns = []
        for column in header.columns:
            numeric = pd.api.types.is_numeric_dtype(header[column]) and str(column) not in date_roles
            columns.append(column_spec(
                str(column),
                "number" if numeric else "text",
                date_role=date_roles.get(str(column), ""),
            ))
        return table_payload(columns, [], project_name=name)

    needed = source_columns_needed(dims, values)
    try:
        frame = pd.read_csv(master_path, usecols=needed, encoding="utf-8-sig", low_memory=False)
    except ValueError as error:
        raise HTTPException(400, f"The imported table could not be read: {error}")
    table = aggregate_frame(frame, dims, values)
    table["project_name"] = name
    return table


_LEADING_YEAR = re.compile(r"^\s*((?:19|20)\d{2})")


def origin_year(label: str) -> str:
    """The year an origin label starts with: `2024`, `2024 Q3` and `202407` are all 2024."""

    match = _LEADING_YEAR.match(str(label))
    return match.group(1) if match else str(label)


def _segment_levels(reserving_class: str) -> List[str]:
    return [part for part in str(reserving_class).split("\\") if part]


def read_dataset_table(
    project_name: str,
    reserving_classes: Sequence[str],
    dataset_names: Sequence[str],
    level_names: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Datasets of several reserving classes as one table.

    One row per reserving class, origin and development period, with one
    number column per dataset. A vector has no development period, so its
    values sit on a row of their own per origin. Datasets are read at the
    period each is stored at, so one class may hold annual, quarterly and
    monthly origins side by side; `Origin Year` is the grouping they share. A cumulative triangle column
    is marked `semi_additive`: it may be totalled across classes and origins
    but only its latest development period per origin counts, which is the
    `latest` aggregation the dashboard applies to it by default.

    A dataset one of the classes does not hold is left blank there and named
    in `missing`; the read still answers.
    """

    name = _text(project_name)
    classes = _text_list(reserving_classes)
    datasets = _text_list(dataset_names)
    if not name:
        raise HTTPException(400, "project_name is required")
    if not classes or not datasets:
        raise HTTPException(400, "Choose at least one reserving class and one dataset.")

    labels = _text_list(level_names)
    depth = max(len(_segment_levels(item)) for item in classes)
    level_columns = [labels[index] if index < len(labels) else f"Level {index + 1}" for index in range(depth)]

    origin_order: List[str] = []
    development_order: List[str] = []
    measure_meta: Dict[str, Dict[str, Any]] = {}
    cells: Dict[tuple, Dict[str, Any]] = {}
    missing: List[Dict[str, str]] = []

    for reserving_class in classes:
        for dataset in datasets:
            try:
                loaded = dataset_service.load_cached_dataset_values(name, reserving_class, dataset)
            except HTTPException as error:
                if error.status_code in (404, 422):
                    missing.append({"reserving_class": reserving_class, "dataset_name": dataset})
                    continue
                raise
            origins = [str(label) for label in loaded.get("origin_labels") or []]
            is_vector = str(loaded.get("data_format") or "").lower() == "vector"
            developments = [] if is_vector else [str(label) for label in loaded.get("dev_labels") or []]
            for label in origins:
                if label not in origin_order:
                    origin_order.append(label)
            for label in developments:
                if label not in development_order:
                    development_order.append(label)
            measure_meta.setdefault(dataset, {
                "data_format": "Vector" if is_vector else "Triangle",
                "semi_additive": (not is_vector) and loaded.get("cumulative") is not False,
                "decimal_places": loaded.get("decimal_places"),
            })
            for row_index, row in enumerate(loaded.get("values") or []):
                if row_index >= len(origins):
                    break
                for column_index, value in enumerate(row if isinstance(row, list) else [row]):
                    number = json_scalar(value)
                    if not isinstance(number, (int, float)) or isinstance(number, bool):
                        continue
                    if is_vector:
                        if column_index:
                            break
                        development = None
                    elif column_index < len(developments):
                        development = developments[column_index]
                    else:
                        break
                    cells.setdefault((reserving_class, origins[row_index], development), {})[dataset] = number

    present = [dataset for dataset in datasets if dataset in measure_meta]
    columns = [column_spec(SEGMENT_COLUMN, "text"), column_spec(SEGMENT_NAME_COLUMN, "text")]
    columns += [column_spec(label, "text") for label in level_columns]
    columns.append(column_spec(ORIGIN_COLUMN, "text", order=origin_order))
    columns.append(column_spec(ORIGIN_YEAR_COLUMN, "text", order=sorted({origin_year(label) for label in origin_order})))
    columns.append(column_spec(DEVELOPMENT_COLUMN, "text", order=development_order))
    for dataset in present:
        meta = measure_meta[dataset]
        columns.append(column_spec(
            dataset,
            "number",
            data_format=meta["data_format"],
            semi_additive=meta["semi_additive"] or None,
            default_aggregation="latest" if meta["semi_additive"] else "sum",
            decimal_places=meta["decimal_places"],
        ))

    origin_rank = {label: index for index, label in enumerate(origin_order)}
    development_rank = {label: index for index, label in enumerate(development_order)}
    class_rank = {label: index for index, label in enumerate(classes)}
    ordered = sorted(
        cells,
        key=lambda key: (
            class_rank[key[0]],
            origin_rank[key[1]],
            -1 if key[2] is None else development_rank[key[2]],
        ),
    )
    rows = []
    for reserving_class, origin, development in ordered:
        levels = _segment_levels(reserving_class)
        values = cells[(reserving_class, origin, development)]
        rows.append([
            reserving_class,
            levels[-1] if levels else reserving_class,
            *[levels[index] if index < len(levels) else None for index in range(depth)],
            origin,
            origin_year(origin),
            development,
            *[values.get(dataset) for dataset in present],
        ])
    if len(rows) > MAX_TABLE_ROWS:
        raise HTTPException(
            422,
            f"These datasets give {len(rows):,} rows; a dashboard table holds at most {MAX_TABLE_ROWS:,}. "
            "Choose fewer reserving classes or datasets.",
        )
    return table_payload(
        columns,
        rows,
        project_name=name,
        missing=missing,
        # How a `latest` aggregation finds the newest development period.
        semi_additive={"partition": [SEGMENT_COLUMN, ORIGIN_COLUMN], "order": DEVELOPMENT_COLUMN},
    )
