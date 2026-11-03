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
from typing import Any, Sequence

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
