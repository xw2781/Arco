"""Compare an Arco Engine dataset with the ResQ copy of the same dataset.

Two callers share this: the offline parity validation under ``validation/``,
which compares at floating-point precision and writes a report, and the ResQ
import, which compares each Engine-built dataset with ResQ at two decimal
places and warns the person importing when any cell disagrees.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Sequence


DEFAULT_ABSOLUTE_TOLERANCE = 1e-9
DEFAULT_RELATIVE_TOLERANCE = 1e-12
# The import warns when a cell disagrees beyond two decimal places.
IMPORT_DECIMAL_PLACES = 2
IMPORT_ABSOLUTE_TOLERANCE = 0.5 * 10 ** -IMPORT_DECIMAL_PLACES


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected a numeric dataset value, received {value!r}.") from exc


def read_engine_csv(path: Path) -> list[list[float | None]]:
    """Read the data-engine's headerless CSV while preserving blank cells."""

    rows: list[list[float | None]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row_number, raw_row in enumerate(csv.reader(handle), start=1):
            row: list[float | None] = []
            for column_number, raw_value in enumerate(raw_row, start=1):
                text = raw_value.strip()
                if not text:
                    row.append(None)
                    continue
                try:
                    value = float(text)
                except ValueError as exc:
                    raise ValueError(
                        "Engine output contains a non-numeric value at "
                        f"row {row_number}, column {column_number}: {raw_value!r}."
                    ) from exc
                row.append(None if math.isnan(value) else value)
            rows.append(row)
    if not rows:
        raise ValueError("Engine output CSV was empty.")
    return rows


def _matrix_shape(matrix: Sequence[Sequence[object]]) -> tuple[int, int]:
    return len(matrix), max((len(row) for row in matrix), default=0)


def _matrix_value(matrix: Sequence[Sequence[object]], row: int, column: int) -> object:
    if row >= len(matrix) or column >= len(matrix[row]):
        return None
    return matrix[row][column]


def _format_cell(row: int, column: int) -> str:
    return f"origin {row + 1}, development {column + 1}"


def compare_matrices(
    resq_values: Sequence[Sequence[object]],
    engine_values: Sequence[Sequence[object]],
    *,
    absolute_tolerance: float = DEFAULT_ABSOLUTE_TOLERANCE,
    relative_tolerance: float = DEFAULT_RELATIVE_TOLERANCE,
) -> dict[str, object]:
    """Compare shape, missingness, and numeric cells without coercing blanks to zero."""

    resq_shape = _matrix_shape(resq_values)
    engine_shape = _matrix_shape(engine_values)
    categories: list[str] = []
    mismatch_count = 0
    missingness_mismatch_count = 0
    numeric_mismatch_count = 0
    max_absolute_delta: float | None = None
    max_relative_delta: float | None = None
    first_mismatch: tuple[str, object, object] | None = None

    if resq_shape != engine_shape:
        categories.append("shape")
        mismatch_count += 1
        first_mismatch = ("shape", resq_shape, engine_shape)

    row_limit = min(resq_shape[0], engine_shape[0])
    column_limit = min(resq_shape[1], engine_shape[1])
    for row in range(row_limit):
        for column in range(column_limit):
            resq_value = _matrix_value(resq_values, row, column)
            engine_value = _matrix_value(engine_values, row, column)
            resq_missing = _is_missing(resq_value)
            engine_missing = _is_missing(engine_value)
            if resq_missing or engine_missing:
                if resq_missing != engine_missing:
                    missingness_mismatch_count += 1
                    mismatch_count += 1
                    if first_mismatch is None:
                        first_mismatch = (_format_cell(row, column), resq_value, engine_value)
                continue

            try:
                resq_number = _as_float(resq_value)
                engine_number = _as_float(engine_value)
            except ValueError:
                numeric_mismatch_count += 1
                mismatch_count += 1
                if first_mismatch is None:
                    first_mismatch = (_format_cell(row, column), resq_value, engine_value)
                continue

            if not (math.isfinite(resq_number) and math.isfinite(engine_number)):
                equal = resq_number == engine_number
            else:
                equal = math.isclose(
                    resq_number,
                    engine_number,
                    abs_tol=absolute_tolerance,
                    rel_tol=relative_tolerance,
                )
            if equal:
                continue

            absolute_delta = abs(resq_number - engine_number)
            scale = max(abs(resq_number), abs(engine_number))
            relative_delta = 0.0 if scale == 0 else absolute_delta / scale
            max_absolute_delta = max(max_absolute_delta or 0.0, absolute_delta)
            max_relative_delta = max(max_relative_delta or 0.0, relative_delta)
            numeric_mismatch_count += 1
            mismatch_count += 1
            if first_mismatch is None:
                first_mismatch = (_format_cell(row, column), resq_value, engine_value)

    if missingness_mismatch_count:
        categories.append("missingness")
    if numeric_mismatch_count:
        categories.append("numeric")
    first_cell, first_resq, first_engine = first_mismatch or ("", None, None)
    return {
        "matches": not categories,
        "categories": tuple(categories),
        "resq_shape": resq_shape,
        "engine_shape": engine_shape,
        "mismatch_count": mismatch_count,
        "max_absolute_delta": max_absolute_delta,
        "max_relative_delta": max_relative_delta,
        "first_mismatch_cell": first_cell,
        "resq_value": first_resq,
        "engine_value": first_engine,
    }


def compare_import_values(
    resq_values: Sequence[Sequence[object]],
    engine_values: Sequence[Sequence[object]],
) -> dict[str, object]:
    """The import's comparison: cells agree when they round to the same two decimals."""

    return compare_matrices(
        resq_values,
        engine_values,
        absolute_tolerance=IMPORT_ABSOLUTE_TOLERANCE,
        relative_tolerance=0.0,
    )


def _cell_text(value: object) -> str:
    if _is_missing(value):
        return "blank"
    try:
        return f"{float(value):,.{IMPORT_DECIMAL_PLACES}f}"
    except (TypeError, ValueError):
        return str(value)


def describe_import_mismatch(comparison: dict[str, object]) -> str:
    """One sentence naming how an Engine dataset disagrees with ResQ, for a warning."""

    if comparison.get("matches"):
        return ""
    if "shape" in comparison.get("categories", ()):
        resq_rows, resq_columns = comparison["resq_shape"]
        engine_rows, engine_columns = comparison["engine_shape"]
        return (
            f"ResQ holds {resq_rows} x {resq_columns} cells but Arco Engine produced "
            f"{engine_rows} x {engine_columns}."
        )
    count = int(comparison.get("mismatch_count") or 0)
    return (
        f"{count} cell(s) differ from ResQ at {IMPORT_DECIMAL_PLACES} decimal places; "
        f"first at {comparison['first_mismatch_cell']}: ResQ {_cell_text(comparison['resq_value'])}, "
        f"Arco Engine {_cell_text(comparison['engine_value'])}."
    )
