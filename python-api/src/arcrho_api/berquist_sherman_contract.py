"""Canonical, filesystem-free contract for the two Berquist Sherman methods.

The page under ``frontend/ui/method_pages/berquist_sherman`` computes a B&S
method in the browser and saves the result triangle it computed. That leaves
the Engine's dependent-propagation walk without a way to recompute a B&S
output when one of its sources moves -- a Result Selection whose ultimate
claim counts feed a Settlement Rate adjustment, say -- so the output CSV the
Dataset Viewer reads would stay stale while the method page, which recomputes
from its sources on every open, looked fresh.

This module is the server-side twin of ``calculation_helpers.js``,
``settlement_rate_calculation.js``, and ``case_reserve_adequacy_calculation.js``:
the same normalization, the same tri-cube loess fit, the same pair-wise,
all-points, and loess estimators, cell for cell. Both are pinned to the one
COL golden fixture (``frontend/tests/fixtures/berquist_sherman_col_golden.json``)
so neither can drift from the other without a test saying so. Inputs are
named as the persisted ``method_tab`` names them, so a stored method JSON plus
its source values is the whole calculation input.

Every formula here is the ResQ calculation the page reproduces; see
``frontend/docs/ui/berquist_sherman.md`` for the behavioural notes.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Mapping, Sequence

from .period_reshape import fit_by_position, reshape_matrix
from .dataset_index_contract import (
    BS_CRA_JSON_FORMAT,
    BS_SR_JSON_FORMAT,
    METHOD_TYPE_BS_CRA,
    METHOD_TYPE_BS_SR,
)


BS_SR_SOURCE_KIND = "berquist_sherman_sr"
BS_CRA_SOURCE_KIND = "berquist_sherman_cra"
BS_SR_VARIANT = "sr"
BS_CRA_VARIANT = "cra"

DEFAULT_LOESS_SPAN = 7
MIN_LOESS_SPAN = 2
MAX_LOESS_SPAN = 99

# The annual period every B&S source must use, as the page enforces.
BS_ANNUAL_PERIOD_LENGTH = 12

SR_ADJUSTMENT_TYPES = frozenset({"unadjusted", "pairs", "all", "loess"})
CRA_INFLATION_SELECTIONS = frozenset({"case_column", "case_all", "paid_column", "paid_all", "user"})
CRA_AVERAGE_SELECTIONS = frozenset({"latest", "monotone", "loess", "user"})

# Source roles per variant, in the ResQ order the page lists them, keyed as
# the persisted ``method_tab`` stores the dataset names.
BS_SOURCE_ROLES: dict[str, tuple[tuple[str, str], ...]] = {
    BS_SR_VARIANT: (
        ("paid_claims", "Triangle"),
        ("closed_claim_numbers", "Triangle"),
        ("ultimate_claim_numbers", "Vector"),
    ),
    BS_CRA_VARIANT: (
        ("paid_claims", "Triangle"),
        ("incurred_claims", "Triangle"),
        ("reported_claim_numbers", "Triangle"),
        ("closed_claim_numbers", "Triangle"),
    ),
}

_VARIANT_ALIASES = {
    BS_SR_VARIANT: BS_SR_VARIANT,
    BS_CRA_VARIANT: BS_CRA_VARIANT,
    METHOD_TYPE_BS_SR.casefold(): BS_SR_VARIANT,
    METHOD_TYPE_BS_CRA.casefold(): BS_CRA_VARIANT,
    BS_SR_SOURCE_KIND: BS_SR_VARIANT,
    BS_CRA_SOURCE_KIND: BS_CRA_VARIANT,
    BS_SR_JSON_FORMAT: BS_SR_VARIANT,
    BS_CRA_JSON_FORMAT: BS_CRA_VARIANT,
    "bssr": BS_SR_VARIANT,
    "bscra": BS_CRA_VARIANT,
}

BS_JSON_FORMAT_BY_VARIANT = {
    BS_SR_VARIANT: BS_SR_JSON_FORMAT,
    BS_CRA_VARIANT: BS_CRA_JSON_FORMAT,
}
BS_METHOD_TYPE_BY_VARIANT = {
    BS_SR_VARIANT: METHOD_TYPE_BS_SR,
    BS_CRA_VARIANT: METHOD_TYPE_BS_CRA,
}
BS_SOURCE_KIND_BY_VARIANT = {
    BS_SR_VARIANT: BS_SR_SOURCE_KIND,
    BS_CRA_VARIANT: BS_CRA_SOURCE_KIND,
}


class BerquistShermanContractError(ValueError):
    """A B&S input the calculation cannot accept, in the page's own words."""


Number = float
Row = list
Triangle = list


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_berquist_sherman_variant(value: Any) -> str:
    """Return ``"sr"``/``"cra"`` for any persisted B&S identity, else ``""``."""

    return _VARIANT_ALIASES.get(_clean(value).casefold(), "")


def berquist_sherman_method_variant(method: Mapping[str, Any]) -> str:
    """Resolve a stored method JSON's variant from its identity fields."""

    if not isinstance(method, Mapping):
        return ""
    metadata = method.get("method_metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    details = method.get("details_tab")
    details = details if isinstance(details, Mapping) else {}
    for candidate in (
        method.get("json_format"),
        metadata.get("source_kind"),
        metadata.get("method_type"),
        details.get("method_type"),
    ):
        variant = normalize_berquist_sherman_variant(candidate)
        if variant:
            return variant
    return ""


def berquist_sherman_precedent_names(method: Mapping[str, Any]) -> list[str]:
    """The source dataset names a stored method reads, in role order."""

    variant = berquist_sherman_method_variant(method)
    tab = method.get("method_tab") if isinstance(method, Mapping) else None
    tab = tab if isinstance(tab, Mapping) else {}
    names: list[str] = []
    for role, _format in BS_SOURCE_ROLES.get(variant, ()):
        name = _clean(tab.get(role))
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return names


# --------------------------------------------------------------------------
# Number helpers (``calculation_helpers.js``)
# --------------------------------------------------------------------------


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: Any) -> bool:
    return _is_finite(value) and value > 0


def number_or_none(value: Any) -> float | None:
    """``numberOrNull``: blank stays blank, anything non-numeric is blank too."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def normalize_loess_span(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_LOESS_SPAN
    if not math.isfinite(number):
        return DEFAULT_LOESS_SPAN
    return min(MAX_LOESS_SPAN, max(MIN_LOESS_SPAN, int(math.trunc(number))))


def normalize_annual_triangle(raw_values: Any, raw_mask: Any = None) -> Triangle:
    """Apply the Dataset Viewer mask and the annual staircase at ingestion.

    ResQ and some legacy CSVs pad the unavailable lower-right area with numeric
    zeroes, so the value alone cannot tell a real zero observation from
    structural padding; the mask and the staircase decide, and each row keeps
    exactly the cells it owns so the calculation preserves the jagged shape.
    """

    rows = raw_values if isinstance(raw_values, list) else []
    masks = raw_mask if isinstance(raw_mask, list) else []
    development_count = max(
        [0]
        + [len(row) if isinstance(row, list) else 1 for row in rows]
        + [len(mask) if isinstance(mask, list) else 0 for mask in masks]
    )
    result: Triangle = []
    for row_index, raw_row in enumerate(rows):
        values = raw_row if isinstance(raw_row, list) else [raw_row]
        mask = masks[row_index] if row_index < len(masks) and isinstance(masks[row_index], list) else None
        structural_length = max(0, development_count - row_index)
        candidate_length = min(structural_length, max(len(values), len(mask) if mask else 0))
        last_included = candidate_length - 1
        if mask is not None:
            while last_included >= 0 and not (last_included < len(mask) and mask[last_included]):
                last_included -= 1
        else:
            while last_included >= 0 and (
                last_included >= len(values) or values[last_included] is None or values[last_included] == ""
            ):
                last_included -= 1
        if last_included < 0:
            result.append([])
            continue
        row: Row = []
        for column_index in range(last_included + 1):
            if mask is not None and not (column_index < len(mask) and mask[column_index]):
                row.append(None)
                continue
            value = values[column_index] if column_index < len(values) else None
            row.append(number_or_none(value))
        result.append(row)
    return result


def normalize_vector(raw_values: Any) -> list[float | None]:
    """The page's ``normalizeVector``: one number per row, first numeric cell wins."""

    rows = raw_values if isinstance(raw_values, list) else []
    result: list[float | None] = []
    for raw_row in rows:
        if not isinstance(raw_row, list):
            result.append(number_or_none(raw_row))
            continue
        chosen = None
        for value in raw_row:
            number = number_or_none(value)
            if number is not None:
                chosen = number
                break
        result.append(chosen)
    return result


def loess_fit(
    points: Sequence[tuple[float, float]],
    target: Any,
    span: int,
    minimum_points: int = 2,
) -> float | None:
    """ResQ "Loess (n)": a tri-cube weighted straight line over the ``span + 1``
    nearest neighbours, evaluated at *target*. The furthest neighbour's weight
    is exactly zero, so it drops out. ``None`` when too few neighbours carry
    weight; each method decides what a degenerate fit means."""

    if not _is_finite(target) or len(points) < minimum_points:
        return None
    distances = sorted(abs(x - target) for x, _y in points)
    bandwidth = distances[min(span, len(points) - 1)]
    weighted: list[tuple[float, float, float]] = []
    for x, y in points:
        distance = abs(x - target)
        if not bandwidth > 0 or distance >= bandwidth:
            continue
        scaled = distance / bandwidth
        weighted.append((x, y, (1 - scaled ** 3) ** 3))
    if len(weighted) < minimum_points:
        return None
    weight_sum = sum(weight for _x, _y, weight in weighted)
    mean_x = sum(weight * x for x, _y, weight in weighted) / weight_sum
    mean_y = sum(weight * y for _x, y, weight in weighted) / weight_sum
    sxx = sum(weight * (x - mean_x) ** 2 for x, _y, weight in weighted)
    if not sxx > 0:
        return None
    slope = sum(weight * (x - mean_x) * (y - mean_y) for x, y, weight in weighted) / sxx
    return mean_y + slope * (target - mean_x)


def normalize_triangle(value: Any, name: str) -> Triangle:
    if not isinstance(value, list) or not value:
        raise BerquistShermanContractError(f"{name} must be a non-empty triangle.")
    result: Triangle = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            raise BerquistShermanContractError(f"{name}[{row_index}] must be an array.")
        cells: Row = []
        for column_index, cell in enumerate(row):
            if cell is None or cell == "":
                cells.append(None)
                continue
            number = number_or_none(cell)
            if number is None:
                raise BerquistShermanContractError(
                    f"{name}[{row_index}][{column_index}] must be numeric or blank."
                )
            cells.append(number)
        result.append(cells)
    return result


def assert_same_triangle_shape(reference: Triangle, candidate: Triangle, name: str) -> None:
    if len(candidate) != len(reference):
        raise BerquistShermanContractError(
            f"{name} must have the same number of rows as the primary triangle."
        )
    for row_index, row in enumerate(reference):
        if len(candidate[row_index]) != len(row):
            raise BerquistShermanContractError(
                f"{name}[{row_index}] must match the primary triangle row length."
            )


def column_count(triangle: Triangle) -> int:
    return max((len(row) for row in triangle), default=0)


def matrix_like(triangle: Triangle, get_value: Callable[[int, int], Any]) -> Triangle:
    return [
        [get_value(row_index, column_index) for column_index in range(len(row))]
        for row_index, row in enumerate(triangle)
    ]


def _cell(triangle: Triangle, row_index: int, column_index: int) -> Any:
    if row_index < 0 or row_index >= len(triangle):
        return None
    row = triangle[row_index]
    if not isinstance(row, list) or column_index < 0 or column_index >= len(row):
        return None
    return row[column_index]


def latest_by_column(triangle: Triangle, fallback: float = 0.0) -> tuple[list[float], list[int]]:
    """Per column, the last row holding a finite value (and which row that was)."""

    count = column_count(triangle)
    values: list[float] = [fallback] * count
    row_indexes: list[int] = [-1] * count
    for column_index in range(count):
        for row_index in range(len(triangle) - 1, -1, -1):
            value = _cell(triangle, row_index, column_index)
            if _is_finite(value):
                values[column_index] = value
                row_indexes[column_index] = row_index
                break
    return values, row_indexes


def unweighted_log_inflation(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    count = len(points)
    sum_x = sum_y = sum_xx = sum_xy = 0.0
    for x, value in points:
        y = math.log(value)
        sum_x += x
        sum_y += y
        sum_xx += x * x
        sum_xy += x * y
    denominator = count * sum_xx - sum_x * sum_x
    if not denominator:
        return 0.0
    slope = (count * sum_xy - sum_x * sum_y) / denominator
    return _exp(slope) - 1


def weighted_fixed_effects_log_inflation(
    groups: Iterable[Sequence[tuple[float, float, float]]],
) -> float:
    numerator = 0.0
    denominator = 0.0
    for group in groups:
        weight_sum = sum(weight for _x, _value, weight in group)
        if not weight_sum > 0:
            continue
        mean_x = sum(weight * x for x, _value, weight in group) / weight_sum
        mean_y = sum(weight * math.log(value) for _x, value, weight in group) / weight_sum
        for x, value, weight in group:
            centered_x = x - mean_x
            centered_y = math.log(value) - mean_y
            numerator += weight * centered_x * centered_y
            denominator += weight * centered_x * centered_x
    if not denominator:
        return 0.0
    return _exp(numerator / denominator) - 1


def boolean_at(matrix: Any, row_index: int, column_index: int) -> bool:
    return _cell(matrix, row_index, column_index) is True if isinstance(matrix, list) else False


# --------------------------------------------------------------------------
# Settlement Rate (``settlement_rate_calculation.js``)
# --------------------------------------------------------------------------


def _normalize_number_vector(
    value: Any,
    count: int,
    name: str,
    fallback: float | None = None,
) -> list[float | None]:
    source = value if isinstance(value, list) else []
    result: list[float | None] = []
    for index in range(count):
        entry = source[index] if index < len(source) else None
        if entry is None or entry == "":
            result.append(fallback)
            continue
        number = number_or_none(entry)
        if number is None:
            raise BerquistShermanContractError(f"{name}[{index}] must be numeric or blank.")
        result.append(number)
    return result


def _row_points(closed_claim_numbers: Row, paid_claims: Row) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index, paid in enumerate(paid_claims):
        closed = closed_claim_numbers[index] if index < len(closed_claim_numbers) else None
        if _is_finite(closed) and _is_finite(paid) and paid > 0:
            points.append((closed, math.log(paid)))
    return points


def _pairwise_estimate(points: Sequence[tuple[float, float]], selected_closed: Any) -> float | None:
    if not _is_finite(selected_closed):
        return None
    if len(points) < 2:
        return 0.0
    pair_index = 0 if selected_closed < points[0][0] else len(points) - 2
    for index in range(len(points) - 1):
        if points[index][0] <= selected_closed <= points[index + 1][0]:
            pair_index = index
    lower_x, lower_y = points[pair_index]
    upper_x, upper_y = points[pair_index + 1]
    if lower_x == upper_x:
        return _exp((lower_y + upper_y) / 2)
    weight = (selected_closed - lower_x) / (upper_x - lower_x)
    return _exp(lower_y + weight * (upper_y - lower_y))


def _all_points_estimate(points: Sequence[tuple[float, float]], selected_closed: Any) -> float:
    if not _is_finite(selected_closed) or len(points) < 2:
        return 0.0
    count = len(points)
    sum_x = sum(x for x, _y in points)
    sum_y = sum(y for _x, y in points)
    sum_xx = sum(x * x for x, _y in points)
    sum_xy = sum(x * y for x, y in points)
    denominator = count * sum_xx - sum_x * sum_x
    if not denominator:
        return 0.0
    slope = (count * sum_xy - sum_x * sum_y) / denominator
    intercept = (sum_y - slope * sum_x) / count
    return _exp(intercept + slope * selected_closed)


def _loess_estimate(points: Sequence[tuple[float, float]], selected_closed: Any, span: int) -> float | None:
    fitted = loess_fit(points, selected_closed, span)
    return None if fitted is None else _exp(fitted)


def _selected_adjustment_at(selection: Any, row_index: int, column_index: int, fallback: str) -> str:
    raw = _cell(selection, row_index, column_index) if isinstance(selection, list) else None
    value = fallback if raw is None or raw == "" else _clean(raw).lower()
    if value not in SR_ADJUSTMENT_TYPES:
        raise BerquistShermanContractError(f"Unsupported settlement-rate adjustment: {raw}")
    return value


def calculate_settlement_rate(source: Mapping[str, Any]) -> dict[str, Any]:
    """Paid claims adjusted to constant proportions settled.

    *source* carries the ``method_tab`` selection fields by their persisted
    names plus the three source roles' values: ``paid_claims`` and
    ``closed_claim_numbers`` as annual triangles, ``ultimate_claim_numbers``
    as one value per origin period.
    """

    paid_claims = normalize_triangle(source.get("paid_claims"), "paid_claims")
    closed_claim_numbers = normalize_triangle(source.get("closed_claim_numbers"), "closed_claim_numbers")
    assert_same_triangle_shape(paid_claims, closed_claim_numbers, "closed_claim_numbers")

    row_count = len(paid_claims)
    development_count = column_count(paid_claims)
    ultimate_claim_numbers = _normalize_number_vector(
        source.get("ultimate_claim_numbers"), row_count, "ultimate_claim_numbers"
    )
    if any(not _is_finite(value) for value in ultimate_claim_numbers):
        raise BerquistShermanContractError(
            "ultimate_claim_numbers must contain one value per origin period."
        )

    def proportion(row_index: int, column_index: int) -> float | None:
        closed = closed_claim_numbers[row_index][column_index]
        ultimate = ultimate_claim_numbers[row_index]
        if not _is_finite(closed):
            return None
        return closed / ultimate if ultimate else 0.0

    proportion_settled = matrix_like(paid_claims, proportion)
    defaults, _rows = latest_by_column(proportion_settled, 0.0)
    entered = _normalize_number_vector(
        source.get("selected_proportion_settled"), development_count, "selected_proportion_settled"
    )
    default_flags = source.get("selected_proportion_is_default")
    default_flags = default_flags if isinstance(default_flags, list) else []
    selected_proportion_settled: list[float] = []
    for index, default_value in enumerate(defaults):
        flag = default_flags[index] if index < len(default_flags) else None
        value = entered[index]
        if flag is True or not _is_finite(value):
            selected_proportion_settled.append(default_value)
        else:
            selected_proportion_settled.append(value)

    selected_claim_numbers = matrix_like(
        paid_claims,
        lambda row_index, column_index: (
            ultimate_claim_numbers[row_index] * selected_proportion_settled[column_index]
        ),
    )
    points_by_row = [
        _row_points(closed_claim_numbers[row_index], row) for row_index, row in enumerate(paid_claims)
    ]
    pairs_adjustment = matrix_like(
        paid_claims,
        lambda row_index, column_index: _pairwise_estimate(
            points_by_row[row_index], selected_claim_numbers[row_index][column_index]
        ),
    )
    all_adjustment = matrix_like(
        paid_claims,
        lambda row_index, column_index: _all_points_estimate(
            points_by_row[row_index], selected_claim_numbers[row_index][column_index]
        ),
    )
    loess_span = normalize_loess_span(source.get("loess_span"))

    def loess(row_index: int, column_index: int) -> float | None:
        estimate = _loess_estimate(
            points_by_row[row_index], selected_claim_numbers[row_index][column_index], loess_span
        )
        # ResQ reverts to pair-wise interpolation when the Loess fit fails.
        if estimate is None:
            return _pairwise_estimate(
                points_by_row[row_index], selected_claim_numbers[row_index][column_index]
            )
        return estimate

    loess_adjustment = matrix_like(paid_claims, loess)
    selected_adjustment = matrix_like(
        paid_claims,
        lambda row_index, column_index: _selected_adjustment_at(
            source.get("selected_adjustment"),
            row_index,
            column_index,
            "unadjusted" if len(points_by_row[row_index]) < 2 else "pairs",
        ),
    )

    def adjusted(row_index: int, column_index: int) -> float | None:
        selection = selected_adjustment[row_index][column_index]
        if selection == "unadjusted":
            return paid_claims[row_index][column_index]
        if selection == "all":
            return all_adjustment[row_index][column_index]
        if selection == "loess":
            return loess_adjustment[row_index][column_index]
        return pairs_adjustment[row_index][column_index]

    adjusted_paid_claims = matrix_like(paid_claims, adjusted)
    return {
        "loess_span": loess_span,
        "proportion_settled": proportion_settled,
        "selected_proportion_settled": selected_proportion_settled,
        "selected_claim_numbers": selected_claim_numbers,
        "pairs_adjustment": pairs_adjustment,
        "all_adjustment": all_adjustment,
        "loess_adjustment": loess_adjustment,
        "selected_adjustment": selected_adjustment,
        "adjusted_paid_claims": adjusted_paid_claims,
        "output": adjusted_paid_claims,
    }


# --------------------------------------------------------------------------
# Case Reserve Adequacy (``case_reserve_adequacy_calculation.js``)
# --------------------------------------------------------------------------


def _positive_ratio(numerator: Any, denominator: Any) -> float:
    if not _positive(numerator) or not _positive(denominator):
        return 0.0
    return numerator / denominator


def _normalize_selection_vector(
    value: Any,
    count: int,
    allowed: frozenset[str],
    fallback: str,
    name: str,
) -> list[str]:
    source = value if isinstance(value, list) else []
    result: list[str] = []
    for index in range(count):
        entry = source[index] if index < len(source) else None
        selection = fallback if entry is None or entry == "" else _clean(entry).lower()
        if selection not in allowed:
            raise BerquistShermanContractError(f"Unsupported {name} selection: {entry}")
        result.append(selection)
    return result


def _estimate_inflation_by_column(averages: Triangle, exclusions: Any) -> list[float]:
    estimates: list[float] = []
    for column_index in range(column_count(averages)):
        points: list[tuple[float, float]] = []
        for row_index, row in enumerate(averages):
            value = _cell(averages, row_index, column_index)
            if _positive(value) and not boolean_at(exclusions, row_index, column_index):
                points.append((float(row_index), value))
        estimates.append(unweighted_log_inflation(points))
    return estimates


def _estimate_overall_inflation(
    averages: Triangle,
    exclusions: Any,
    weight_at: Callable[[int, int], Any],
) -> float:
    groups: list[list[tuple[float, float, float]]] = []
    for column_index in range(column_count(averages)):
        points: list[tuple[float, float, float]] = []
        for row_index, _row in enumerate(averages):
            value = _cell(averages, row_index, column_index)
            weight = weight_at(row_index, column_index)
            if (
                _positive(value)
                and _positive(weight)
                and not boolean_at(exclusions, row_index, column_index)
            ):
                points.append((float(row_index), value, weight))
        groups.append(points)
    return weighted_fixed_effects_log_inflation(groups)


def _monotone_latest_averages(latest: Sequence[float]) -> list[float]:
    observations = [(index, value) for index, value in enumerate(latest) if _positive(value)]
    if not observations:
        return [0.0 for _ in latest]

    blocks: list[dict[str, float]] = []
    for index, value in observations:
        blocks.append({"first": index, "last": index, "sum": value, "count": 1, "value": value})
        while len(blocks) > 1 and blocks[-2]["value"] > blocks[-1]["value"]:
            right = blocks.pop()
            left = blocks.pop()
            total = left["sum"] + right["sum"]
            count = left["count"] + right["count"]
            blocks.append({
                "first": left["first"],
                "last": right["last"],
                "sum": total,
                "count": count,
                "value": total / count,
            })

    fitted: dict[int, float] = {}
    for block in blocks:
        for index, _value in observations:
            if block["first"] <= index <= block["last"]:
                fitted[index] = block["value"]
    result: list[float] = []
    for index in range(len(latest)):
        chosen = fitted[observations[0][0]]
        for observation_index, _value in observations:
            if observation_index <= index:
                chosen = fitted[observation_index]
        result.append(chosen)
    return result


def _loess_latest_averages(latest: Sequence[float], span: int) -> list[float]:
    # ResQ smooths the latest averages themselves, on the value scale, against
    # development period; a local line here needs three weighted neighbours.
    points = [(float(index), value) for index, value in enumerate(latest) if _positive(value)]
    result: list[float] = []
    for index in range(len(latest)):
        fitted = loess_fit(points, float(index), span, 3)
        result.append(0.0 if fitted is None else fitted)
    return result


def calculate_case_reserve_adequacy(source: Mapping[str, Any]) -> dict[str, Any]:
    """Incurred claims adjusted for case reserve adequacy.

    *source* carries the ``method_tab`` selection fields by their persisted
    names plus the four source roles' annual triangles: ``paid_claims``,
    ``incurred_claims``, ``reported_claim_numbers``, ``closed_claim_numbers``.
    The COL exclusion flags are non-contributing and deferred, as on the page.
    """

    incurred_claims = normalize_triangle(source.get("incurred_claims"), "incurred_claims")
    paid_claims = normalize_triangle(source.get("paid_claims"), "paid_claims")
    reported_claim_numbers = normalize_triangle(
        source.get("reported_claim_numbers"), "reported_claim_numbers"
    )
    closed_claim_numbers = normalize_triangle(source.get("closed_claim_numbers"), "closed_claim_numbers")
    assert_same_triangle_shape(incurred_claims, paid_claims, "paid_claims")
    assert_same_triangle_shape(incurred_claims, reported_claim_numbers, "reported_claim_numbers")
    assert_same_triangle_shape(incurred_claims, closed_claim_numbers, "closed_claim_numbers")
    avg_case_reserve_exclusions = source.get("avg_case_reserve_exclusions")
    avg_paid_claims_exclusions = source.get("avg_paid_claims_exclusions")

    development_count = column_count(incurred_claims)

    def open_claims(row_index: int, column_index: int) -> float | None:
        reported = reported_claim_numbers[row_index][column_index]
        closed = closed_claim_numbers[row_index][column_index]
        return reported - closed if _is_finite(reported) and _is_finite(closed) else None

    open_claim_numbers = matrix_like(incurred_claims, open_claims)

    def case_reserve(row_index: int, column_index: int) -> float | None:
        incurred = incurred_claims[row_index][column_index]
        paid = paid_claims[row_index][column_index]
        return incurred - paid if _is_finite(incurred) and _is_finite(paid) else None

    case_reserves = matrix_like(incurred_claims, case_reserve)
    average_case_reserves = matrix_like(
        incurred_claims,
        lambda row_index, column_index: _positive_ratio(
            case_reserves[row_index][column_index], open_claim_numbers[row_index][column_index]
        ),
    )

    def incremental(triangle: Triangle) -> Callable[[int, int], float | None]:
        def value_at(row_index: int, column_index: int) -> float | None:
            current = triangle[row_index][column_index]
            if not _is_finite(current):
                return None
            previous = triangle[row_index][column_index - 1] if column_index > 0 else 0.0
            return current - previous if _is_finite(previous) else None

        return value_at

    incremental_closed_claim_numbers = matrix_like(incurred_claims, incremental(closed_claim_numbers))
    incremental_paid_claims = matrix_like(incurred_claims, incremental(paid_claims))
    average_paid_claims = matrix_like(
        incurred_claims,
        lambda row_index, column_index: _positive_ratio(
            incremental_paid_claims[row_index][column_index],
            incremental_closed_claim_numbers[row_index][column_index],
        ),
    )

    case_inflation_by_column = _estimate_inflation_by_column(
        average_case_reserves, avg_case_reserve_exclusions
    )
    paid_inflation_by_column = _estimate_inflation_by_column(
        average_paid_claims, avg_paid_claims_exclusions
    )
    case_inflation_overall = _estimate_overall_inflation(
        average_case_reserves,
        avg_case_reserve_exclusions,
        lambda row_index, column_index: _cell(open_claim_numbers, row_index, column_index),
    )
    paid_inflation_overall = _estimate_overall_inflation(
        average_paid_claims,
        avg_paid_claims_exclusions,
        lambda row_index, column_index: _cell(
            incremental_closed_claim_numbers, row_index, column_index
        ),
    )

    inflation_selection = _normalize_selection_vector(
        source.get("inflation_selection"),
        development_count,
        CRA_INFLATION_SELECTIONS,
        "paid_all",
        "inflation",
    )
    user_inflation = _normalize_number_vector(
        source.get("user_inflation"), development_count, "user_inflation", 0.0
    )
    selected_inflation: list[float] = []
    for column_index, selection in enumerate(inflation_selection):
        if selection == "case_column":
            selected_inflation.append(case_inflation_by_column[column_index])
        elif selection == "case_all":
            selected_inflation.append(case_inflation_overall)
        elif selection == "paid_column":
            selected_inflation.append(paid_inflation_by_column[column_index])
        elif selection == "paid_all":
            selected_inflation.append(paid_inflation_overall)
        else:
            selected_inflation.append(user_inflation[column_index])

    latest_average_case_reserves, latest_row_indexes = latest_by_column(average_case_reserves, 0.0)
    monotone_average_case_reserves = _monotone_latest_averages(latest_average_case_reserves)
    loess_span = normalize_loess_span(source.get("loess_span"))
    loess_average_case_reserves = _loess_latest_averages(latest_average_case_reserves, loess_span)
    average_case_reserve_selection = _normalize_selection_vector(
        source.get("average_case_reserve_selection"),
        development_count,
        CRA_AVERAGE_SELECTIONS,
        "latest",
        "average case reserve",
    )
    user_average_case_reserves = _normalize_number_vector(
        source.get("user_average_case_reserves"),
        development_count,
        "user_average_case_reserves",
        0.0,
    )
    selected_average_case_reserves: list[float] = []
    for column_index, selection in enumerate(average_case_reserve_selection):
        if selection == "latest":
            selected_average_case_reserves.append(latest_average_case_reserves[column_index])
        elif selection == "monotone":
            selected_average_case_reserves.append(monotone_average_case_reserves[column_index])
        elif selection == "loess":
            selected_average_case_reserves.append(loess_average_case_reserves[column_index])
        else:
            selected_average_case_reserves.append(user_average_case_reserves[column_index])

    def adjusted_average(row_index: int, column_index: int) -> float | None:
        latest_row_index = latest_row_indexes[column_index]
        if latest_row_index < row_index:
            return None
        inflation = selected_inflation[column_index]
        if not inflation > -1:
            raise BerquistShermanContractError(
                f"selected_inflation[{column_index}] must be greater than -1."
            )
        return selected_average_case_reserves[column_index] / (
            (1 + inflation) ** (latest_row_index - row_index)
        )

    adjusted_average_case_reserves = matrix_like(incurred_claims, adjusted_average)

    def adjusted_incurred(row_index: int, column_index: int) -> float | None:
        paid = paid_claims[row_index][column_index]
        open_count = open_claim_numbers[row_index][column_index]
        adjusted = adjusted_average_case_reserves[row_index][column_index]
        if not _is_finite(paid) or not _is_finite(open_count) or not _is_finite(adjusted):
            return None
        return paid + adjusted * open_count

    adjusted_incurred_claims = matrix_like(incurred_claims, adjusted_incurred)
    return {
        "loess_span": loess_span,
        "open_claim_numbers": open_claim_numbers,
        "case_reserves": case_reserves,
        "average_case_reserves": average_case_reserves,
        "incremental_closed_claim_numbers": incremental_closed_claim_numbers,
        "incremental_paid_claims": incremental_paid_claims,
        "average_paid_claims": average_paid_claims,
        "case_inflation_by_column": case_inflation_by_column,
        "case_inflation_overall": case_inflation_overall,
        "paid_inflation_by_column": paid_inflation_by_column,
        "paid_inflation_overall": paid_inflation_overall,
        "inflation_selection": inflation_selection,
        "user_inflation": user_inflation,
        "selected_inflation": selected_inflation,
        "latest_average_case_reserves": latest_average_case_reserves,
        "monotone_average_case_reserves": monotone_average_case_reserves,
        "loess_average_case_reserves": loess_average_case_reserves,
        "average_case_reserve_selection": average_case_reserve_selection,
        "user_average_case_reserves": user_average_case_reserves,
        "selected_average_case_reserves": selected_average_case_reserves,
        "adjusted_average_case_reserves": adjusted_average_case_reserves,
        "adjusted_incurred_claims": adjusted_incurred_claims,
        "output": adjusted_incurred_claims,
    }


# --------------------------------------------------------------------------
# Whole-method entry points
# --------------------------------------------------------------------------


def calculate_berquist_sherman_output(
    method: Mapping[str, Any],
    source_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the stored method's variant over its already-normalized sources.

    *source_values* maps each role of the variant (``BS_SOURCE_ROLES``) to the
    values the page would hold after ``normalize_annual_triangle`` or
    ``normalize_vector`` -- the page's ``state.sourceValues``.
    """

    variant = berquist_sherman_method_variant(method)
    if variant not in BS_SOURCE_ROLES:
        raise BerquistShermanContractError("Not a Berquist Sherman method.")
    tab = method.get("method_tab") if isinstance(method, Mapping) else None
    tab = tab if isinstance(tab, Mapping) else {}
    if variant == BS_SR_VARIANT:
        return calculate_settlement_rate({
            "paid_claims": source_values.get("paid_claims"),
            "closed_claim_numbers": source_values.get("closed_claim_numbers"),
            "ultimate_claim_numbers": source_values.get("ultimate_claim_numbers"),
            "selected_proportion_settled": tab.get("selected_proportion_settled"),
            "selected_proportion_is_default": tab.get("selected_proportion_is_default"),
            "selected_adjustment": tab.get("selected_adjustment"),
            "loess_span": tab.get("loess_span"),
        })
    return calculate_case_reserve_adequacy({
        "reported_claim_numbers": source_values.get("reported_claim_numbers"),
        "closed_claim_numbers": source_values.get("closed_claim_numbers"),
        "incurred_claims": source_values.get("incurred_claims"),
        "paid_claims": source_values.get("paid_claims"),
        # The stored COL exclusion flags are non-contributing and deferred.
        "avg_case_reserve_exclusions": [],
        "avg_paid_claims_exclusions": [],
        "inflation_selection": tab.get("inflation_selection"),
        "user_inflation": tab.get("user_inflation"),
        "average_case_reserve_selection": tab.get("average_case_reserve_selection"),
        "user_average_case_reserves": tab.get("user_average_case_reserves"),
        "loess_span": tab.get("loess_span"),
    })


def berquist_sherman_development_count(
    method: Mapping[str, Any],
    source_values: Mapping[str, Any],
) -> int:
    """The page's ``matrixDevelopmentCount``: the widest of the stored labels
    and every source triangle row, which is the width the output CSV pads to."""

    variant = berquist_sherman_method_variant(method)
    tab = method.get("method_tab") if isinstance(method, Mapping) else None
    tab = tab if isinstance(tab, Mapping) else {}
    labels = tab.get("development_labels")
    count = len(labels) if isinstance(labels, list) else 0
    for role, data_format in BS_SOURCE_ROLES.get(variant, ()):
        if data_format != "Triangle":
            continue
        rows = source_values.get(role)
        for row in rows if isinstance(rows, list) else []:
            count = max(count, len(row) if isinstance(row, list) else 0)
    return count


def _js_number_text(value: float) -> str:
    """``String(number)`` for the values a B&S output holds: an integral value
    prints without a fraction, anything else in the shortest round-trip form."""

    if value == math.trunc(value) and abs(value) < 1e21:
        return str(int(value))
    return repr(float(value))


def berquist_sherman_output_csv_text(values: Any, development_count: int) -> str:
    """The page's ``matrixCsv``: every row padded to the method's width, a blank
    for each missing or non-numeric cell, and a trailing newline."""

    rows = values if isinstance(values, list) else []
    matrix: list[list[float | None]] = []
    for raw_row in rows:
        row = [number_or_none(value) for value in (raw_row if isinstance(raw_row, list) else [raw_row])]
        while row and row[-1] is None:
            row.pop()
        matrix.append(row)
    width = max([development_count] + [len(row) for row in matrix] + [0])
    lines = []
    for row in matrix:
        cells = []
        for index in range(width):
            number = row[index] if index < len(row) else None
            cells.append("" if number is None else _js_number_text(number))
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


def parse_output_csv_text(text: Any) -> list[list[float | None]]:
    """Read a B&S output CSV back into the matrix ``berquist_sherman_output_csv_text`` wrote."""

    rows: list[list[float | None]] = []
    for line in str(text or "").splitlines():
        if line == "":
            continue
        rows.append([number_or_none(cell.strip()) for cell in line.split(",")])
    return rows


def output_values_equal(left: Any, right: Any, *, rel_tol: float = 1e-12) -> bool:
    """Whether two output matrices hold the same numbers, cell for cell."""

    left_rows = left if isinstance(left, list) else []
    right_rows = right if isinstance(right, list) else []

    def trimmed(rows: list) -> list[list[float | None]]:
        result = []
        for raw_row in rows:
            row = [number_or_none(value) for value in (raw_row if isinstance(raw_row, list) else [raw_row])]
            while row and row[-1] is None:
                row.pop()
            result.append(row)
        while result and not result[-1]:
            result.pop()
        return result

    a = trimmed(left_rows)
    b = trimmed(right_rows)
    if len(a) != len(b):
        return False
    for row_a, row_b in zip(a, b):
        if len(row_a) != len(row_b):
            return False
        for x, y in zip(row_a, row_b):
            if x is None or y is None:
                if x is not y:
                    return False
                continue
            if not math.isclose(x, y, rel_tol=rel_tol, abs_tol=1e-9):
                return False
    return True


__all__ = [
    "BS_ANNUAL_PERIOD_LENGTH",
    "BS_CRA_JSON_FORMAT",
    "BS_CRA_SOURCE_KIND",
    "BS_CRA_VARIANT",
    "BS_JSON_FORMAT_BY_VARIANT",
    "BS_METHOD_TYPE_BY_VARIANT",
    "BS_SOURCE_KIND_BY_VARIANT",
    "BS_SOURCE_ROLES",
    "BS_SR_JSON_FORMAT",
    "BS_SR_SOURCE_KIND",
    "BS_SR_VARIANT",
    "BerquistShermanContractError",
    "DEFAULT_LOESS_SPAN",
    "berquist_sherman_development_count",
    "berquist_sherman_method_variant",
    "berquist_sherman_output_csv_text",
    "berquist_sherman_precedent_names",
    "calculate_berquist_sherman_output",
    "calculate_case_reserve_adequacy",
    "calculate_settlement_rate",
    "latest_by_column",
    "loess_fit",
    "normalize_annual_triangle",
    "normalize_berquist_sherman_variant",
    "normalize_loess_span",
    "normalize_vector",
    "number_or_none",
    "output_values_equal",
    "parse_output_csv_text",
]


# --------------------------------------------------------------------------
# A move of the project dates
# --------------------------------------------------------------------------

#: Per-development-column selections and the value a new column starts at.
_COLUMN_SELECTIONS: dict[str, tuple[tuple[str, Any], ...]] = {
    BS_SR_VARIANT: (
        ("selected_proportion_settled", None),
        ("selected_proportion_is_default", True),
    ),
    BS_CRA_VARIANT: (
        ("inflation_selection", "paid_all"),
        ("user_inflation", 0.0),
        ("user_inflation_inputs", ""),
        ("average_case_reserve_selection", "latest"),
        ("user_average_case_reserves", 0.0),
        ("user_average_case_reserves_inputs", ""),
    ),
}


def reshape_berquist_sherman_periods(
    method: Mapping[str, Any],
    origin_labels: Sequence[Any],
    development_labels: Sequence[Any],
) -> dict[str, Any]:
    """Return *method* moved onto new origins and development columns.

    Rows follow their origin label and columns keep their position from the
    first column (``period_reshape``); a new column starts at the page's
    default selection, and a new Settlement Rate row or cell starts null,
    which the calculation reads as its default adjustment. The output triangle
    is recalculated from the sources by the next refresh.
    """

    variant = berquist_sherman_method_variant(method)
    if variant not in BS_SOURCE_ROLES:
        raise BerquistShermanContractError("Not a Berquist Sherman method.")
    out = {key: value for key, value in method.items()}
    tab = dict(method.get("method_tab") or {})
    old_origins = [str(label) for label in tab.get("origin_labels") or []]
    origins = [str(label) for label in origin_labels]
    columns = [str(label) for label in development_labels]
    for key, fill in _COLUMN_SELECTIONS[variant]:
        if isinstance(tab.get(key), list):
            tab[key] = fit_by_position(tab[key], len(columns), fill)
    if variant == BS_SR_VARIANT and isinstance(tab.get("selected_adjustment"), list):
        tab["selected_adjustment"] = reshape_matrix(
            tab["selected_adjustment"], old_origins, origins, len(columns), None
        )
    tab["origin_labels"] = origins
    tab["development_labels"] = columns
    out["method_tab"] = tab
    return out
