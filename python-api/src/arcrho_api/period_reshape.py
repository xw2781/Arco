"""Reshape stored per-period data when the project dates move.

One rule for every method and hand-entered dataset (decision 3 of
docs/plans/project_dates_panel.md): rows follow their origin label, so a kept
origin keeps its values wherever its row now sits, a dropped origin's row goes
and a new origin's row starts from ``fill``; along the development axis cells
copy by position from the first cell, and cells past the old end start from
``fill``. A per-column list that ends in a tail ("N - Ult") keeps the tail last.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

_AGE_LABEL = re.compile(r"\s*(\d+(?:\.\d+)?)m?\s*")


def _ages(labels: Sequence[Any]) -> list[float] | None:
    ages: list[float] = []
    for label in labels:
        match = _AGE_LABEL.fullmatch(str(label if label is not None else ""))
        if not match:
            return None
        ages.append(float(match.group(1)))
    return ages


def development_axis_reshapable(old_labels: Sequence[Any], new_labels: Sequence[Any]) -> bool:
    """True when both axes are development ages on the same spacing.

    That is what a move of the project dates produces: the ages shift and the
    column count may grow or shrink, but the period length stays. Anything else
    (a different development length, labels that are not ages) is a different
    triangle and is not reshaped.
    """

    old_ages, new_ages = _ages(old_labels), _ages(new_labels)
    if not old_ages or not new_ages:
        return False
    old_steps = {round(right - left, 6) for left, right in zip(old_ages, old_ages[1:])}
    new_steps = {round(right - left, 6) for left, right in zip(new_ages, new_ages[1:])}
    return not old_steps or not new_steps or old_steps == new_steps


def fit_by_position(values: Sequence[Any], count: int, fill: Any) -> list[Any]:
    """The first ``count`` cells of ``values``, padded with ``fill``."""

    out = [deepcopy(value) for value in list(values)[:count]]
    out.extend(deepcopy(fill) for _ in range(max(0, count - len(out))))
    return out


def fit_by_position_keep_tail(values: Sequence[Any], count: int, fill: Any) -> list[Any]:
    """Like :func:`fit_by_position`, with the last cell (the tail) kept last."""

    items = list(values)
    if count <= 0:
        return []
    if not items:
        return fit_by_position([], count, fill)
    return fit_by_position(items[:-1], count - 1, fill) + [deepcopy(items[-1])]


def rows_by_label(
    rows: Sequence[Any], old_labels: Sequence[Any], new_labels: Sequence[Any], fill: Any
) -> list[Any]:
    """One entry per new label: the old entry with the same label, else ``fill``."""

    lookup = {str(label): index for index, label in enumerate(old_labels)}
    out: list[Any] = []
    for label in new_labels:
        index = lookup.get(str(label))
        out.append(deepcopy(rows[index]) if index is not None and index < len(rows) else deepcopy(fill))
    return out


def reshape_matrix(
    matrix: Sequence[Sequence[Any]],
    old_labels: Sequence[Any],
    new_labels: Sequence[Any],
    column_count: int,
    fill: Any,
) -> list[list[Any]]:
    """Rows by origin label, columns by position, new cells ``fill``."""

    return [
        fit_by_position(row, column_count, fill)
        for row in rows_by_label(matrix, old_labels, new_labels, [])
    ]


#: Reasons a reshaped hand-entered or imported dataset is listed for review.
REVIEW_HAND_ENTERED = "hand-entered or imported"
REVIEW_CELL_LINKS = "has cell links"
REVIEW_DROPPED_DATA = "dropped origins held data"

#: Link fields whose target cells follow their origin (Arco links). Excel
#: links (``external_links``) keep their absolute cell (decision 8).
_SHIFTING_LINK_FIELDS = ("formula_links", "internal_links")
_EXCEL_LINK_FIELD = "external_links"


def _is_index_labels(labels: Sequence[Any]) -> bool:
    return bool(labels) and [str(label) for label in labels] == [str(index + 1) for index in range(len(labels))]


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and not (isinstance(value, float) and value != value)


def reshape_input_dataset(
    sidecar: Mapping[str, Any],
    values: Sequence[Sequence[Any]],
    old_origin_labels: Sequence[Any],
    new_origin_labels: Sequence[Any],
    development_labels: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Reshape one hand-entered or imported dataset to new project dates.

    ``old_origin_labels``/``new_origin_labels`` are the dataset's true origins
    at its stored period under the old and new dates; most of these datasets
    store index labels ``1..N``, so the caller derives the true origins from
    the dates, not from the sidecar. ``values`` is the stored grid, one list per
    row (a vector row is ``[value]``). ``development_labels`` are the new
    stored columns of a triangle; a vector keeps its single column.

    Rows follow their origin label and columns keep their position, new cells
    empty (decision 3). Arco formula and internal links move their target rows
    with the origin, and a target whose origin or column went is removed; their
    formula and source text are not rewritten. Excel links keep their absolute
    cells and the values under them stay put (decision 8).

    Returns ``{"sidecar", "values", "review"}``: a new sidecar (origin and
    development labels and link targets updated), the new grid, and the
    reasons the dataset is listed for review.
    """

    from .dataset_link_contract import compact_target_cells, expand_target_cells

    old_labels = [str(label) for label in old_origin_labels]
    new_labels = [str(label) for label in new_origin_labels]
    old_columns = list(sidecar.get("development_labels") or [])
    columns = list(development_labels) if development_labels is not None else old_columns
    column_count = max(1, len(columns))

    def link_cells(link: Mapping[str, Any], field: str) -> tuple[bool, list[dict[str, Any]]]:
        stored = link["target_cells"]
        as_blocks = any(isinstance(target, list) for target in stored)
        return as_blocks, expand_target_cells(stored, field) if as_blocks else [dict(target) for target in stored]

    # Excel-linked cells stay where they are, so they do not travel with
    # their row: lift them out before the rows move and put them back after.
    excel_cells = {
        (int(cell["row"]), int(cell["column"]))
        for link in sidecar.get(_EXCEL_LINK_FIELD) or []
        if isinstance(link, Mapping) and link.get("target_cells") is not None
        for cell in link_cells(link, _EXCEL_LINK_FIELD)[1]
    }
    movable = [
        [None if (row, column) in excel_cells else cell for column, cell in enumerate(cells)]
        for row, cells in enumerate(values)
    ]
    grid = reshape_matrix(movable, old_labels, new_labels, column_count, None)
    for row, column in excel_cells:
        if row < len(grid) and column < column_count:
            grid[row][column] = deepcopy(
                values[row][column] if row < len(values) and column < len(values[row]) else None
            )

    out = deepcopy(dict(sidecar))
    stored_labels = list(sidecar.get("origin_labels") or [])
    out["origin_labels"] = (
        [str(index + 1) for index in range(len(new_labels))]
        if _is_index_labels(stored_labels) or not stored_labels
        else new_labels
    )
    if development_labels is not None:
        out["development_labels"] = list(development_labels)

    new_row = {label: index for index, label in enumerate(new_labels)}
    has_links = False
    for field in (*_SHIFTING_LINK_FIELDS, _EXCEL_LINK_FIELD):
        links = out.get(field)
        if not isinstance(links, list) or not links:
            continue
        has_links = True
        kept_links = []
        for link in links:
            if not isinstance(link, dict) or link.get("target_cells") is None:
                kept_links.append(link)
                continue
            if field == _EXCEL_LINK_FIELD:
                kept_links.append(link)
                continue
            as_blocks, cells = link_cells(link, field)
            moved = []
            for cell in cells:
                row, column = int(cell["row"]), int(cell["column"])
                label = old_labels[row] if row < len(old_labels) else None
                target_row = new_row.get(label) if label is not None else None
                if target_row is None or column >= column_count:
                    continue
                moved.append({**cell, "row": target_row})
            if moved:
                kept_links.append({
                    **link,
                    "target_cells": compact_target_cells(moved, field) if as_blocks else moved,
                })
        out[field] = kept_links

    review = [REVIEW_HAND_ENTERED]
    if has_links:
        review.append(REVIEW_CELL_LINKS)
    kept = set(new_labels)
    if any(
        label not in kept and index < len(movable) and any(_has_value(cell) for cell in movable[index])
        for index, label in enumerate(old_labels)
    ):
        review.append(REVIEW_DROPPED_DATA)
    return {"sidecar": out, "values": grid, "review": review}
