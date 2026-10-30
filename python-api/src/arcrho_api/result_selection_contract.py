"""Result Selection calculation shared by the app server and agent previews."""

from __future__ import annotations

import math
from typing import Any, Mapping, MutableMapping


def round_number(value: Any) -> float | int | None:
    """Return one Result Selection number at the precision it was observed with.

    Every value here is a method ultimate produced somewhere else and copied in:
    a DFM chain, a Bornhuetter-Ferguson, a Cape Cod. Quantizing the copy made
    the weighted average of several ultimates disagree with the same average
    taken in ResQ, and the published selection carried the difference on to
    everything that reads it. The number is therefore carried whole, exactly as
    the input triangle and the DFM factor chain already are.
    """

    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number == 0:
        number = 0.0
    if isinstance(value, int) and not isinstance(value, bool):
        return int(number)
    return number


def weighted_ultimates(sources: list[Mapping[str, Any]], row_count: int) -> list[float | int | None]:
    out: list[float | int | None] = []
    for row in range(row_count):
        numerator = 0.0
        denominator = 0.0
        for source in sources:
            values = source.get("values") if isinstance(source.get("values"), list) else []
            weights = source.get("weights") if isinstance(source.get("weights"), list) else []
            try:
                value = float(values[row])
                weight = max(0.0, float(weights[row]))
            except (IndexError, TypeError, ValueError):
                continue
            if not math.isfinite(value) or not math.isfinite(weight) or weight <= 0:
                continue
            numerator += value * weight
            denominator += weight
        out.append(round_number(numerator / denominator) if denominator > 0 else None)
    return out


def recalculate_result_selection(payload: MutableMapping[str, Any]) -> None:
    """Refresh the calculated and selected ultimates of a normalized method in place."""

    method = payload["method_tab"]
    row_count = len(method.get("origin_labels", []))
    calculated = weighted_ultimates(method.get("loaded_datasets", []), row_count)
    overrides = list(method.get("ultimate_overrides") or [])[:row_count]
    overrides.extend([None] * (row_count - len(overrides)))
    method["ultimate_overrides"] = overrides
    method["calculated_ultimate"] = calculated
    method["selected_ultimate"] = [
        overrides[index] if overrides[index] is not None else calculated[index]
        for index in range(row_count)
    ]
