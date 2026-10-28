"""Canonical, filesystem-free contract for Bootstrap methods.

All persisted-data producers delegate Bootstrap normalization, the embedded DFM
snapshot, revision hashes, output variants, and the output-sidecar projection to
this module.  The numbers themselves come from :mod:`bootstrap_simulation`, which
is the single owner of every Bootstrap formula.

A Bootstrap method is the first Arco method whose data precedent is another
*method* rather than a dataset: it bootstraps a DFM.  A current v1 payload
embeds everything it needs from that DFM, so the Residuals, Simulation and
Results tabs open without reading the precedent.

Simulated reserves are deliberately **not** persisted.  ``results_tab`` keeps the
seed, the simulation count, and a compact summary; reopening the method re-runs
the simulation from the stored seed, which is bit-reproducible, and compares the
result against the stored summary so drift is detected rather than accepted.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .bootstrap_simulation import (
    BST_DISTRIBUTIONS,
    BST_MODEL_TYPES,
    BST_NEGATIVE_MEAN_ACTIONS,
    BST_ODP_NEGATIVE_MEAN_ACTIONS,
    BST_RESIDUAL_TYPES,
    BST_SCALING_METHODS,
    BST_SUMMARY_PERCENTILES,
    BootstrapCalculationError,
    BootstrapRefitRules,
    BootstrapSimulationOptions,
    calculate_residuals,
    fit_dfm_projection,
    observed_triangle,
    scale_simulated_reserves,
    selected_scale_values,
    percentile_key,
    simulate_bootstrap,
    summarize_reserves,
    total_reserve_ranks,
)
from .dataset_display_contract import normalize_show_subtotal
from .dfm_contract import aggregate_vector_values, canonical_number, selected_ratio_values
from .revision_contract import fingerprint
from .sidecar_audit_contract import (
    AUDIT_ACTION_INSERT,
    AUDIT_ACTION_UPDATE,
    append_audit_entry,
    normalize_audit_log,
)
from .sidecar_core_contract import (
    DATASET_SIDECAR_JSON_FORMAT,
    dependency_entries,
    stored_length_fields,
    validate_sidecar_core,
)
from .timestamps import persisted_timestamp as _timestamp


BST_JSON_FORMAT = "arcrho-bootstrap-v4"
BST_METHOD_TYPE = "Bootstrap"
BST_SOURCE_KIND = "bootstrap"
BST_METHOD_TYPE_CODE = 6
BST_FILE_PREFIX = "BST@"

#: Residual grids persisted on the Residuals tab, in ResQ ``ResidualType`` order.
BST_RESIDUAL_GRIDS = BST_RESIDUAL_TYPES

#: Scale rows persisted for both the residual and forecasting scale blocks.
BST_SCALE_ROWS = ("unsmoothed", "smoothed", "user_entry", "selected")


class BootstrapContractError(ValueError):
    """Raised when a Bootstrap payload cannot satisfy the canonical v1 contract."""


# Compact alias for callers that prefer the abbreviation used by the UI.
BstContractError = BootstrapContractError


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split()).strip()


def _integer(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    result = max(minimum, result)
    return min(result, maximum) if maximum is not None else result


def _tab(payload: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    return dict(value) if isinstance(value, Mapping) else {}


def _labels(value: Any) -> list[str]:
    return [_clean(item) for item in value] if isinstance(value, (list, tuple)) else []


def _number(value: Any) -> float | int | None:
    return canonical_number(value)


def _numbers(value: Any) -> list[float | int | None]:
    return [_number(item) for item in value] if isinstance(value, (list, tuple)) else []


def _matrix(value: Any) -> list[list[float | int | None]]:
    return [_numbers(row) for row in value] if isinstance(value, (list, tuple)) else []


def _exact(value: Any) -> float | None:
    """A finite float kept at full precision.

    ``canonical_number`` rounds to six decimals so a persisted file stays
    reviewable, which is right for a displayed statistic and wrong for a
    development ratio the Bootstrap chains together ten times over.
    """

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fit(values: list[Any], size: int, fill: Any) -> list[Any]:
    trimmed = list(values[:size])
    trimmed.extend([fill] * (size - len(trimmed)))
    return trimmed


def _fit_owned(values: list[Any], size: int | None, fill: Any) -> list[Any]:
    """Fit an owned list to its axis, or keep it whole while there is no axis."""

    return list(values) if size is None else _fit(values, size, fill)


def _flags(value: Any, size: int, default: bool = False) -> list[bool]:
    raw = [bool(item) for item in value] if isinstance(value, (list, tuple)) else []
    return _fit(raw, size, default)


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = _clean(value).lower().replace(" ", "_").replace("-", "_")
    return text if text in allowed else default


def _snapshot_revision(name: str, *parts: Any) -> str:
    if not _clean(name):
        return ""
    return fingerprint({"name": _clean(name), "parts": list(parts)})


# ---------------------------------------------------------------------------
# Embedded DFM snapshot
# ---------------------------------------------------------------------------


def dfm_snapshot_from_method(dfm_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project a DFM method JSON onto the compact snapshot a Bootstrap embeds.

    The Bootstrap needs the observed triangle, the selected development ratios,
    and which of those ratios a simulation may re-estimate.  A ratio the user
    fixed by hand — User Entry, a benchmark, or the tail — carries no estimation
    error, exactly as ResQ's "Preparation of DFM" guidance describes.
    """

    if not isinstance(dfm_payload, Mapping):
        raise BootstrapContractError("Bootstrap DFM snapshot requires a DFM method payload.")
    data = _tab(dfm_payload, "data_tab")
    ratios_tab = _tab(dfm_payload, "ratios_tab")
    details = _tab(dfm_payload, "details_tab")
    ratio_triangle = ratios_tab.get("ratio_triangle")
    ratio_triangle = dict(ratio_triangle) if isinstance(ratio_triangle, Mapping) else {}
    formulas = ratios_tab.get("average_formulas")
    formulas = dict(formulas) if isinstance(formulas, Mapping) else {}

    origin_labels = _labels(data.get("origin_labels"))
    development_labels = _labels(data.get("development_labels"))
    triangle = observed_triangle(data.get("input_data_triangle_values"))
    if not origin_labels or not development_labels or not triangle:
        raise BootstrapContractError("Bootstrap DFM snapshot requires a populated DFM data tab.")

    ratio_columns = len(_labels(ratio_triangle.get("development_labels"))) or len(development_labels)
    selected_rows = formulas.get("selected") if isinstance(formulas.get("selected"), list) else []
    settings = formulas.get("custom_average_formula_settings")
    settings = dict(settings) if isinstance(settings, Mapping) else {}
    average_types = _labels(settings.get("average_type"))
    bases = _labels(settings.get("base"))
    periods_setting = settings.get("periods") if isinstance(settings.get("periods"), list) else []
    exclude_setting = settings.get("exclude") if isinstance(settings.get("exclude"), list) else []

    # Full precision, not the six-decimal stored projection: the Bootstrap
    # chains every ratio together to back-fit the triangle, so display rounding
    # would show up as a ~1% error in the residuals and the scale parameter.
    selected_ratios = [float(value) for value in selected_ratio_values(dfm_payload)]
    refit: list[bool] = []
    base: list[str] = []
    periods: list[int | None] = []
    exclude_high_low: list[bool] = []
    last_observed_ratio = len(development_labels) - 1
    for column in range(ratio_columns):
        row_index = next(
            (
                row
                for row, flags in enumerate(selected_rows)
                if isinstance(flags, (list, tuple)) and column < len(flags) and flags[column] == 1
            ),
            0,
        )
        average_type = average_types[row_index] if row_index < len(average_types) else "custom"
        row_base = bases[row_index] if row_index < len(bases) else "volume"
        computed = average_type != "user_entry" and row_base in {"volume", "simple"}
        refit.append(bool(computed and column < last_observed_ratio))
        base.append(row_base if row_base in {"volume", "simple"} else "volume")
        raw_periods = periods_setting[row_index] if row_index < len(periods_setting) else "all"
        periods.append(None if _clean(raw_periods).lower() in {"", "all"} else _integer(raw_periods, 0) or None)
        raw_exclude = exclude_setting[row_index] if row_index < len(exclude_setting) else 0
        exclude_high_low.append(bool(raw_exclude))

    excluded = ratio_triangle.get("excluded") if isinstance(ratio_triangle.get("excluded"), list) else []
    excluded_ratios = [
        [bool(cell) for cell in row] if isinstance(row, (list, tuple)) else []
        for row in excluded
    ]
    results = _tab(dfm_payload, "results_tab")
    return {
        "name": _clean(details.get("name")),
        "origin_labels": origin_labels,
        "development_labels": development_labels,
        "origin_length": _integer(details.get("origin_length"), 12, minimum=1),
        "development_length": _integer(details.get("development_length"), 12, minimum=1),
        "total_development_periods": len(development_labels) + 1,
        "observed_triangle": [list(row) for row in triangle],
        "selected_ratios": selected_ratios,
        "refit_ratios": refit,
        "ratio_average_base": base,
        "ratio_average_periods": periods,
        "ratio_exclude_high_low": exclude_high_low,
        "excluded_ratios": excluded_ratios,
        "dfm_ultimate_values": _numbers(results.get("ultimate_vector")),
    }


def _snapshot(details: Mapping[str, Any]) -> dict[str, Any]:
    snapshot = details.get("dfm_snapshot")
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _normalize_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    origins = _labels(raw.get("origin_labels"))
    development = _labels(raw.get("development_labels"))
    triangle = observed_triangle(raw.get("observed_triangle"))
    periods = _integer(raw.get("total_development_periods"), len(development) + 1, minimum=1)
    ratio_count = max(periods - 1, 0)
    return {
        "name": _clean(raw.get("name")),
        "origin_labels": origins,
        "development_labels": development,
        "origin_length": _integer(raw.get("origin_length"), 12, minimum=1),
        "development_length": _integer(raw.get("development_length"), 12, minimum=1),
        "total_development_periods": periods,
        "observed_triangle": [list(row) for row in triangle],
        "selected_ratios": _fit(
            [
                _exact(value) if _exact(value) is not None else 1.0
                for value in (raw.get("selected_ratios") or [])
            ],
            ratio_count,
            1.0,
        ),
        "refit_ratios": _flags(raw.get("refit_ratios"), ratio_count),
        "ratio_average_base": _fit(_labels(raw.get("ratio_average_base")), ratio_count, "volume"),
        "ratio_average_periods": _fit(_numbers(raw.get("ratio_average_periods")), ratio_count, None),
        "ratio_exclude_high_low": _flags(raw.get("ratio_exclude_high_low"), ratio_count),
        "excluded_ratios": [
            [bool(cell) for cell in row] if isinstance(row, (list, tuple)) else []
            for row in (raw.get("excluded_ratios") or [])
        ],
        "dfm_ultimate_values": _fit(_numbers(raw.get("dfm_ultimate_values")), len(origins), None),
    }


def snapshot_revision(snapshot: Mapping[str, Any]) -> str:
    return _snapshot_revision(
        snapshot.get("name"),
        snapshot.get("origin_labels"),
        snapshot.get("development_labels"),
        snapshot.get("observed_triangle"),
        snapshot.get("selected_ratios"),
        snapshot.get("refit_ratios"),
        snapshot.get("total_development_periods"),
    )


# ---------------------------------------------------------------------------
# Calculation entry points
# ---------------------------------------------------------------------------


def _fit_and_residuals(snapshot: Mapping[str, Any], model_type: str):
    fit = fit_dfm_projection(
        snapshot["observed_triangle"],
        snapshot["selected_ratios"],
        snapshot["total_development_periods"],
    )
    residuals = calculate_residuals(
        fit, model_type=model_type, excluded_ratios=snapshot.get("excluded_ratios") or []
    )
    return fit, residuals


def _refit_rules(snapshot: Mapping[str, Any]) -> BootstrapRefitRules:
    return BootstrapRefitRules(
        refit=list(snapshot.get("refit_ratios") or []),
        base=list(snapshot.get("ratio_average_base") or []),
        periods=[None if v is None else int(v) for v in (snapshot.get("ratio_average_periods") or [])],
        exclude_high_low=list(snapshot.get("ratio_exclude_high_low") or []),
        excluded_ratios=list(snapshot.get("excluded_ratios") or []),
    )


def _scale_block(
    unsmoothed: list[float], user_entry: list[Any], smoothing: float
) -> dict[str, list[Any]]:
    # Smoothing is not implemented yet, so Smoothed mirrors Unsmoothed; the
    # stored smoothing parameter still round-trips so enabling it later cannot
    # silently change a saved method.
    smoothed = list(unsmoothed)
    return {
        "unsmoothed": list(unsmoothed),
        "smoothed": smoothed,
        "user_entry": list(user_entry),
        "selected": selected_scale_values(unsmoothed, smoothed=smoothed, user_entry=user_entry),
    }


def _simulation_options(simulation: Mapping[str, Any]) -> BootstrapSimulationOptions:
    return BootstrapSimulationOptions(
        simulation_count=_integer(simulation.get("simulation_count"), 10000, minimum=1, maximum=1000000),
        random_seed=_integer(simulation.get("random_seed"), 0, minimum=0),
        estimation_variance=_choice(simulation.get("estimation_variance"), BST_DISTRIBUTIONS, "gamma"),
        process_variance=_choice(simulation.get("process_variance"), BST_DISTRIBUTIONS, "gamma"),
        prevent_negative_data=bool(simulation.get("prevent_negative_data", True)),
        negative_mean_action=_choice(
            simulation.get("negative_mean_action"), BST_NEGATIVE_MEAN_ACTIONS, "normal"
        ),
        odp_negative_mean_action=_choice(
            simulation.get("odp_negative_mean_action"), BST_ODP_NEGATIVE_MEAN_ACTIONS, "negative_mean"
        ),
    )


def bootstrap_simulated_reserves(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Regenerate every simulation a stored Bootstrap payload describes.

    This is the one place a consumer (a Stochastic Consolidation) gets a
    bootstrap's simulations from; nothing else re-implements the run.  The
    result is plain JSON-shaped data, never persisted:

    * ``scaled`` and ``unscaled`` each hold ``reserves`` (simulation x origin),
      ``totals`` (the all-origin reserve of every simulation, the plain sum of
      its origins) and ``total_ranks`` (the rank of every simulation's total,
      1 for the smallest, a permutation of 1..n as ResQ's ``TotalRank``);
    * list position ``s`` is simulation ``s + 1`` in ResQ's numbering;
    * the seed, count, origin labels, latest diagonal, DFM reserves and the
      run's diagnostics come along so ``summarize_bootstrap_simulations`` can
      rebuild the stored summary exactly.

    Deterministic for a given ``random_seed``.
    """

    method = normalize_bootstrap_method(payload, require_complete=False)
    details = method["details_tab"]
    snapshot = details["dfm_snapshot"]
    if not snapshot.get("observed_triangle"):
        raise BootstrapContractError("Bootstrap cannot simulate without a DFM snapshot.")
    residuals_tab = method["residuals_tab"]
    results_tab = method["results_tab"]

    fit, residuals = _fit_and_residuals(snapshot, details["model_type"])
    options = _simulation_options(method["simulation_tab"])
    run = simulate_bootstrap(
        fit,
        residuals,
        options,
        residual_scale=residuals_tab["scale_values_residuals"]["selected"],
        forecast_scale=residuals_tab["scale_values_forecasting"]["selected"],
        refit_rules=_refit_rules(snapshot),
    )
    scaled_reserves = scale_simulated_reserves(
        run.reserves,
        target_means=results_tab["target_reserve_values"],
        scaling_methods=results_tab["target_scaling_methods"],
        target_cvs=results_tab["target_cvs"],
    )

    def _block(reserves: list[list[float]]) -> dict[str, Any]:
        totals = [sum(row) for row in reserves]
        return {"reserves": reserves, "totals": totals, "total_ranks": total_reserve_ranks(totals)}

    return {
        "simulation_count": options.simulation_count,
        "random_seed": options.random_seed,
        "model_type": details["model_type"],
        "origin_labels": list(snapshot["origin_labels"]),
        "latest_values": list(fit.latest_values),
        "dfm_reserves": list(fit.dfm_reserves),
        "unscaled": _block([list(row) for row in run.reserves]),
        "scaled": _block(scaled_reserves),
        "diagnostics": {
            "data_point_count": residuals.data_point_count,
            "parameter_count": residuals.parameter_count,
            "development_factor_count": max(fit.observed_columns - 1, 0),
            "negative_data_pseudo": run.negative_data_pseudo,
            "negative_data_forecast": run.negative_data_forecast,
            "negative_mean_pseudo": run.negative_mean_pseudo,
            "negative_mean_forecast": run.negative_mean_forecast,
        },
    }


def summarize_bootstrap_simulations(simulations: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce ``bootstrap_simulated_reserves`` output to the simulation summary.

    The summary serves every Results view: mean, standard deviation, minimum
    and maximum of the reserves, the half-percent percentile ladder, the mean
    and standard deviation of the ultimates, and a histogram of the total
    reserve, scaled and unscaled, with index 0 the all-origin total.
    """

    latest = list(simulations.get("latest_values") or [])
    return {
        "simulation_count": simulations.get("simulation_count", 0),
        "random_seed": simulations.get("random_seed", 0),
        "model_type": simulations.get("model_type", ""),
        "unscaled": summarize_reserves(simulations["unscaled"]["reserves"], latest_values=latest),
        "scaled": summarize_reserves(simulations["scaled"]["reserves"], latest_values=latest),
        "diagnostics": dict(simulations.get("diagnostics") or {}),
        "dfm_reserves": list(simulations.get("dfm_reserves") or []),
        "latest_values": latest,
    }


def run_bootstrap_simulation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Run the simulation a normalized payload describes and return its summary.

    Deterministic for a given ``random_seed``: the same payload always produces
    the same summary, which is what lets the method persist a seed instead of a
    multi-megabyte reserve array.
    """

    return summarize_bootstrap_simulations(bootstrap_simulated_reserves(payload))


#: The finest ladder interval, in percent: ResQ's 0.01% Percentiles.
BST_FINEST_LADDER_INTERVAL = 0.01


def ladder_percentile_steps(interval: float) -> list[float]:
    """Every percentile from 0 to 100 at ``interval`` percent, a Full Ladder's rows.

    Shared by the Bootstrap and the Stochastic Consolidation ladders, so a
    coarser interval's steps are exactly some of a finer one's.
    """

    count = round(100 / float(interval)) if interval else 0
    if interval < BST_FINEST_LADDER_INTERVAL or count < 1 or abs(count * interval - 100) > 1e-9:
        raise BootstrapContractError(f"{interval}% is not an interval that divides 100%.")
    # index * 100 / count is the correctly rounded percent, as the page computes it.
    return [index * 100 / count for index in range(count + 1)]


def bootstrap_percentile_ladder(payload: Mapping[str, Any], interval: float) -> dict[str, Any]:
    """The percentile ladder of a stored run at ``interval`` percent, scaled and unscaled.

    The stored summary holds every half percent; a finer interval re-runs the
    simulation from the stored seed and keeps only the ladder, keyed as the
    stored one is (``percentile_key``).  A re-run whose means differ from the
    stored summary is not the run on screen, so it is refused rather than
    shown beside that run's statistics.
    """

    steps = ladder_percentile_steps(interval)
    stored = normalize_bootstrap_method(payload, require_complete=False)["results_tab"]["simulation_summary"]
    simulations = bootstrap_simulated_reserves(payload)
    ladders: dict[str, Any] = {"interval": float(interval)}
    for basis in ("scaled", "unscaled"):
        block = summarize_reserves(simulations[basis]["reserves"], percentiles=steps)
        if _numbers(block["mean"]) != stored[basis].get("mean"):
            raise BootstrapContractError("This run no longer reproduces; simulate again to see a finer interval.")
        ladders[basis] = {key: _numbers(values) for key, values in block["percentiles"].items()}
    return ladders


def _empty_summary() -> dict[str, Any]:
    return {
        "simulation_count": 0,
        "random_seed": 0,
        "model_type": "",
        "unscaled": {},
        "scaled": {},
        "diagnostics": {},
        "dfm_reserves": [],
        "latest_values": [],
    }


def _normalize_histogram(value: Any) -> dict[str, Any]:
    raw = dict(value) if isinstance(value, Mapping) else {}
    counts = raw.get("counts")
    return {
        "lower": _number(raw.get("lower")) or 0,
        "upper": _number(raw.get("upper")) or 0,
        "counts": [_integer(item, 0, minimum=0) for item in counts] if isinstance(counts, list) else [],
    }


def normalize_summary_block(value: Any) -> dict[str, Any]:
    """One scaled or unscaled summary block; index 0 of every vector is the total.

    A summary saved before the half-percent ladder keeps the 5% steps it has,
    and its missing ultimate statistics and histogram read as empty.  A missing
    block stays an empty object, as an unsimulated method has always stored it.
    """

    if not isinstance(value, Mapping):
        return {}
    source = dict(value)
    ladder = source.get("percentiles")
    ladder = dict(ladder) if isinstance(ladder, Mapping) else {}
    keys = [percentile_key(step) for step in BST_SUMMARY_PERCENTILES]
    return {
        "mean": _numbers(source.get("mean")),
        "standard_error": _numbers(source.get("standard_error")),
        "minimum": _numbers(source.get("minimum")),
        "maximum": _numbers(source.get("maximum")),
        "percentiles": {key: _numbers(ladder.get(key)) for key in keys if key in ladder},
        "ultimate_mean": _numbers(source.get("ultimate_mean")),
        "ultimate_standard_error": _numbers(source.get("ultimate_standard_error")),
        "histogram": _normalize_histogram(source.get("histogram")),
    }


def _normalize_summary(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _empty_summary()

    diagnostics = raw.get("diagnostics")
    return {
        "simulation_count": _integer(raw.get("simulation_count"), 0, minimum=0),
        "random_seed": _integer(raw.get("random_seed"), 0, minimum=0),
        "model_type": _choice(raw.get("model_type"), BST_MODEL_TYPES, ""),
        "unscaled": normalize_summary_block(raw.get("unscaled")),
        "scaled": normalize_summary_block(raw.get("scaled")),
        "diagnostics": {
            key: _integer(value, 0, minimum=0)
            for key, value in (dict(diagnostics) if isinstance(diagnostics, Mapping) else {}).items()
        },
        "dfm_reserves": _numbers(raw.get("dfm_reserves")),
        "latest_values": _numbers(raw.get("latest_values")),
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_bootstrap_method(
    payload: Mapping[str, Any],
    *,
    require_complete: bool = True,
    timestamp: Any = None,
) -> dict[str, Any]:
    """Return the exact canonical, self-contained Bootstrap v1 payload."""

    if not isinstance(payload, Mapping):
        raise BootstrapContractError("Bootstrap method payload must be a JSON object.")
    json_format = _clean(payload.get("json_format"))
    if json_format != BST_JSON_FORMAT:
        raise BootstrapContractError(f"Unsupported Bootstrap JSON format: {json_format!r}.")

    details_source = _tab(payload, "details_tab")
    residuals_source = _tab(payload, "residuals_tab")
    simulation_source = _tab(payload, "simulation_tab")
    results_source = _tab(payload, "results_tab")
    output_source = _tab(payload, "output_tab")
    metadata_source = _tab(payload, "method_metadata")

    snapshot = _normalize_snapshot(_snapshot(details_source))
    origins = snapshot["origin_labels"]
    row_count = len(origins)
    periods = snapshot["total_development_periods"]
    model_type = _choice(details_source.get("model_type"), BST_MODEL_TYPES, "odp_single_scale")
    # Before a DFM snapshot exists (a first save, an import) the method has no
    # axis to size its owned per-origin and per-period lists by. They are kept
    # as given until recalculation embeds the snapshot and fits them, so a
    # first save cannot silently drop a scaling method or a user scale entry.
    has_axis = bool(origins)
    owned_rows = row_count if has_axis else None
    owned_periods = periods if has_axis else None

    user_residual_scale = _fit_owned(
        _numbers(residuals_source.get("user_scale_values_residuals")), owned_periods, None
    )
    user_forecast_scale = _fit_owned(
        _numbers(residuals_source.get("user_scale_values_forecasting")), owned_periods, None
    )

    default_time = _timestamp(timestamp)
    last_modified = _clean(metadata_source.get("last_modified")) or default_time
    data_refreshed = _clean(metadata_source.get("data_refreshed")) or last_modified

    residual_values = residuals_source.get("residual_values")
    residual_values = dict(residual_values) if isinstance(residual_values, Mapping) else {}
    scale_residuals = residuals_source.get("scale_values_residuals")
    scale_residuals = dict(scale_residuals) if isinstance(scale_residuals, Mapping) else {}
    scale_forecasting = residuals_source.get("scale_values_forecasting")
    scale_forecasting = dict(scale_forecasting) if isinstance(scale_forecasting, Mapping) else {}

    normalized: dict[str, Any] = {
        "json_format": BST_JSON_FORMAT,
        "details_tab": {
            "name": _clean(details_source.get("name")),
            "method_type": BST_METHOD_TYPE,
            "output_type": _clean(details_source.get("output_type")),
            "dataset_category": _clean(details_source.get("dataset_category")),
            "origin_length": _integer(details_source.get("origin_length"), snapshot["origin_length"], minimum=1),
            "development_length": _integer(
                details_source.get("development_length"), snapshot["development_length"], minimum=1
            ),
            "model_type": model_type,
            "dfm_method": _clean(details_source.get("dfm_method")) or snapshot["name"],
            "dfm_source_revision": snapshot_revision(snapshot),
            "dfm_snapshot": snapshot,
        },
        "residuals_tab": {
            "residual_type": _choice(
                residuals_source.get("residual_type"),
                BST_RESIDUAL_TYPES,
                "scaled_bias_adjusted_zero_average",
            ),
            "show_scale_values": bool(residuals_source.get("show_scale_values", False)),
            "tile_grid_and_graph": bool(residuals_source.get("tile_grid_and_graph", False)),
            "residual_scale_smoothing": float(_number(residuals_source.get("residual_scale_smoothing")) or 0.0),
            "forecast_scale_smoothing": float(_number(residuals_source.get("forecast_scale_smoothing")) or 0.0),
            "user_scale_values_residuals": user_residual_scale,
            "user_scale_values_forecasting": user_forecast_scale,
            "residual_values": {
                key: _matrix(residual_values.get(key)) for key in BST_RESIDUAL_GRIDS
            },
            "scale_values_residuals": {
                row: _fit(_numbers(scale_residuals.get(row)), periods, None) for row in BST_SCALE_ROWS
            },
            "scale_values_forecasting": {
                row: _fit(_numbers(scale_forecasting.get(row)), periods, None) for row in BST_SCALE_ROWS
            },
            "residual_adjustment": float(_number(residuals_source.get("residual_adjustment")) or 0.0),
            "bias_factor": float(_number(residuals_source.get("bias_factor")) or 0.0),
            "data_point_count": _integer(residuals_source.get("data_point_count"), 0, minimum=0),
            "parameter_count": _integer(residuals_source.get("parameter_count"), 0, minimum=0),
        },
        "simulation_tab": {
            "estimation_variance": _choice(
                simulation_source.get("estimation_variance"), BST_DISTRIBUTIONS, "gamma"
            ),
            "process_variance": _choice(
                simulation_source.get("process_variance"), BST_DISTRIBUTIONS, "gamma"
            ),
            "simulation_count": _integer(
                simulation_source.get("simulation_count"), 10000, minimum=1, maximum=1000000
            ),
            "random_seed": _integer(simulation_source.get("random_seed"), 0, minimum=0),
            "prevent_negative_data": bool(simulation_source.get("prevent_negative_data", True)),
            "negative_mean_action": _choice(
                simulation_source.get("negative_mean_action"), BST_NEGATIVE_MEAN_ACTIONS, "normal"
            ),
            "odp_negative_mean_action": _choice(
                simulation_source.get("odp_negative_mean_action"),
                BST_ODP_NEGATIVE_MEAN_ACTIONS,
                "negative_mean",
            ),
        },
        "results_tab": {
            "target_ultimate": _clean(results_source.get("target_ultimate")),
            "target_ultimate_values": _fit(
                _numbers(results_source.get("target_ultimate_values")), row_count, None
            ),
            "target_ultimate_source_revision": "",
            "latest_values": _fit(_numbers(results_source.get("latest_values")), row_count, None),
            "target_reserve_values": _fit(
                _numbers(results_source.get("target_reserve_values")), row_count, None
            ),
            "target_scaling_methods": _fit_owned(
                [
                    _choice(item, BST_SCALING_METHODS, "additive")
                    for item in (results_source.get("target_scaling_methods") or [])
                ],
                owned_rows,
                "additive",
            ),
            "target_cvs": _fit_owned(_numbers(results_source.get("target_cvs")), owned_rows, 0),
            "simulation_summary": _normalize_summary(results_source.get("simulation_summary")),
            "bootstrap_ultimate": _fit(
                _numbers(results_source.get("bootstrap_ultimate")), row_count, None
            ),
            "origin_labels": origins,
        },
        "output_tab": {
            "observed_triangle": bool(output_source.get("observed_triangle", True)),
            "scale_parameters": bool(output_source.get("scale_parameters", True)),
            "latest_simulated_diagonal": bool(output_source.get("latest_simulated_diagonal", True)),
            "development_factors": bool(output_source.get("development_factors", True)),
            "reserves_by_origin": bool(output_source.get("reserves_by_origin", True)),
            "reserves_by_origin_and_development": bool(
                output_source.get("reserves_by_origin_and_development", True)
            ),
            "total_reserve_ranks": bool(output_source.get("total_reserve_ranks", True)),
        },
        "method_metadata": {
            "method_type": BST_METHOD_TYPE,
            "source_kind": BST_SOURCE_KIND,
            "last_modified": last_modified,
            "data_refreshed": data_refreshed,
            "owned_revision": "",
            "derived_revision": "",
            "publication_revision": "",
        },
    }
    normalized["results_tab"]["target_ultimate_source_revision"] = _snapshot_revision(
        normalized["results_tab"]["target_ultimate"],
        origins,
        normalized["results_tab"]["target_ultimate_values"],
    )
    _set_revisions(normalized)
    if require_complete:
        _validate_complete(normalized)
    return normalized


def _validate_complete(payload: Mapping[str, Any]) -> None:
    details = _tab(payload, "details_tab")
    residuals = _tab(payload, "residuals_tab")
    results = _tab(payload, "results_tab")
    for key in ("name", "output_type", "dfm_method"):
        if not _clean(details.get(key)):
            raise BootstrapContractError(f"Bootstrap details_tab.{key} is required.")
    if _integer(details.get("origin_length"), 0) not in {1, 3, 6, 12}:
        raise BootstrapContractError("Bootstrap origin_length must be 1, 3, 6, or 12 months.")
    snapshot = _snapshot(details)
    origins = _labels(snapshot.get("origin_labels"))
    if not origins:
        raise BootstrapContractError("Bootstrap requires an embedded DFM snapshot with origins.")
    periods = _integer(snapshot.get("total_development_periods"), 0)
    for block in ("scale_values_residuals", "scale_values_forecasting"):
        rows = residuals.get(block)
        rows = dict(rows) if isinstance(rows, Mapping) else {}
        for row in BST_SCALE_ROWS:
            values = rows.get(row)
            if not isinstance(values, list) or len(values) != periods:
                raise BootstrapContractError(
                    f"Bootstrap residuals_tab.{block}.{row} needs one value per development period."
                )
    for key in ("target_scaling_methods", "target_cvs", "bootstrap_ultimate", "latest_values"):
        values = results.get(key)
        if not isinstance(values, list) or len(values) != len(origins):
            raise BootstrapContractError(
                f"Bootstrap results_tab.{key} needs exactly one entry per origin period."
            )


# ---------------------------------------------------------------------------
# Projections and revisions
# ---------------------------------------------------------------------------


def owned_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    residuals = _tab(payload, "residuals_tab")
    results = _tab(payload, "results_tab")
    return {
        "details_tab": {
            key: details.get(key)
            for key in (
                "name",
                "output_type",
                "dataset_category",
                "origin_length",
                "development_length",
                "model_type",
                "dfm_method",
            )
        },
        "residuals_tab": {
            key: residuals.get(key)
            for key in (
                "residual_type",
                "show_scale_values",
                "tile_grid_and_graph",
                "residual_scale_smoothing",
                "forecast_scale_smoothing",
                "user_scale_values_residuals",
                "user_scale_values_forecasting",
            )
        },
        "simulation_tab": deepcopy(_tab(payload, "simulation_tab")),
        "results_tab": {
            "target_ultimate": results.get("target_ultimate", ""),
            "target_scaling_methods": deepcopy(results.get("target_scaling_methods") or []),
            "target_cvs": deepcopy(results.get("target_cvs") or []),
        },
        "output_tab": deepcopy(_tab(payload, "output_tab")),
    }


def derived_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    residuals = _tab(payload, "residuals_tab")
    results = _tab(payload, "results_tab")
    return {
        "dfm_snapshot": deepcopy(details.get("dfm_snapshot") or {}),
        "dfm_source_revision": details.get("dfm_source_revision", ""),
        "residual_values": deepcopy(residuals.get("residual_values") or {}),
        "scale_values_residuals": deepcopy(residuals.get("scale_values_residuals") or {}),
        "scale_values_forecasting": deepcopy(residuals.get("scale_values_forecasting") or {}),
        "residual_adjustment": residuals.get("residual_adjustment", 0.0),
        "bias_factor": residuals.get("bias_factor", 0.0),
        "data_point_count": residuals.get("data_point_count", 0),
        "parameter_count": residuals.get("parameter_count", 0),
        "origin_labels": deepcopy(results.get("origin_labels") or []),
        "latest_values": deepcopy(results.get("latest_values") or []),
        "target_ultimate_values": deepcopy(results.get("target_ultimate_values") or []),
        "target_ultimate_source_revision": results.get("target_ultimate_source_revision", ""),
        "target_reserve_values": deepcopy(results.get("target_reserve_values") or []),
        "simulation_summary": deepcopy(results.get("simulation_summary") or {}),
        "bootstrap_ultimate": deepcopy(results.get("bootstrap_ultimate") or []),
    }


def publication_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    results = _tab(payload, "results_tab")
    return {
        "dataset_name": details.get("name", ""),
        "dataset_type": details.get("output_type", ""),
        "dataset_category": details.get("dataset_category", ""),
        "origin_length": details.get("origin_length", 12),
        "origin_labels": deepcopy(results.get("origin_labels") or []),
        "bootstrap_ultimate": deepcopy(results.get("bootstrap_ultimate") or []),
    }


def method_revisions(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return deterministic revisions for owned, derived, and published state."""

    return {
        "owned_revision": fingerprint(owned_projection(payload)),
        "derived_revision": fingerprint(derived_projection(payload)),
        "publication_revision": fingerprint(publication_projection(payload)),
    }


def _set_revisions(payload: dict[str, Any]) -> None:
    payload.setdefault("method_metadata", {}).update(method_revisions(payload))


def _current_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    json_format = _clean(payload.get("json_format"))
    if json_format not in {"", BST_JSON_FORMAT}:
        raise BootstrapContractError(f"Unsupported Bootstrap JSON format: {json_format!r}.")
    stamped = deepcopy(dict(payload))
    stamped["json_format"] = BST_JSON_FORMAT
    return stamped


# ---------------------------------------------------------------------------
# Recalculation
# ---------------------------------------------------------------------------


def recalculate_bootstrap_method(
    payload: Mapping[str, Any],
    *,
    dfm_snapshot: Mapping[str, Any] | None = None,
    target_snapshot: Mapping[str, Any] | None = None,
    changed_precedents: Iterable[str] = (),
    timestamp: Any = None,
    update_refresh_timestamp: bool | None = None,
    simulate: bool = True,
) -> dict[str, Any]:
    """Refresh Bootstrap derived state, optionally re-running the simulation."""

    changed = tuple(str(item) for item in changed_precedents)
    refreshed_at = _timestamp(timestamp)
    if update_refresh_timestamp is None:
        update_refresh_timestamp = (
            dfm_snapshot is not None or target_snapshot is not None or bool(changed)
        )
    method = normalize_bootstrap_method(
        _current_payload(payload), require_complete=False, timestamp=refreshed_at
    )
    details = method["details_tab"]
    results = method["results_tab"]

    if dfm_snapshot is not None:
        snapshot = _normalize_snapshot(dfm_snapshot)
        configured = _clean(details.get("dfm_method"))
        if snapshot["name"] and configured and snapshot["name"].casefold() != configured.casefold():
            raise BootstrapContractError(
                "Bootstrap DFM snapshot identity does not match its configured DFM."
            )
        if not configured and snapshot["name"]:
            details["dfm_method"] = snapshot["name"]
        details["dfm_snapshot"] = snapshot
        details["dfm_source_revision"] = snapshot_revision(snapshot)

    snapshot = details["dfm_snapshot"]
    origins = _labels(snapshot.get("origin_labels"))
    results["origin_labels"] = origins
    row_count = len(origins)

    if target_snapshot is not None:
        labels = _labels(
            target_snapshot.get("origin_labels") or target_snapshot.get("origin_labels")
        )
        raw = _numbers(target_snapshot.get("values"))
        lookup = {label: raw[index] if index < len(raw) else None for index, label in enumerate(labels)}
        results["target_ultimate"] = _clean(target_snapshot.get("name")) or results["target_ultimate"]
        results["target_ultimate_values"] = [lookup.get(label) for label in origins]

    if not snapshot.get("observed_triangle"):
        if update_refresh_timestamp:
            method["method_metadata"]["data_refreshed"] = refreshed_at
        return normalize_bootstrap_method(method, require_complete=False, timestamp=refreshed_at)

    fit, residuals = _fit_and_residuals(snapshot, details["model_type"])
    periods = snapshot["total_development_periods"]
    residuals_tab = method["residuals_tab"]
    residuals_tab["residual_values"] = {
        key: [[_number(value) for value in row] for row in residuals.grids[key]]
        for key in BST_RESIDUAL_GRIDS
    }
    residuals_tab["scale_values_residuals"] = _scale_block(
        residuals.scale_unsmoothed,
        _fit(residuals_tab["user_scale_values_residuals"], periods, None),
        residuals_tab["residual_scale_smoothing"],
    )
    residuals_tab["scale_values_forecasting"] = _scale_block(
        residuals.scale_unsmoothed,
        _fit(residuals_tab["user_scale_values_forecasting"], periods, None),
        residuals_tab["forecast_scale_smoothing"],
    )
    residuals_tab["residual_adjustment"] = residuals.residual_adjustment
    residuals_tab["bias_factor"] = residuals.bias_factor
    residuals_tab["data_point_count"] = residuals.data_point_count
    residuals_tab["parameter_count"] = residuals.parameter_count

    results["latest_values"] = list(fit.latest_values)
    results["target_ultimate_values"] = _fit(results["target_ultimate_values"], row_count, None)
    results["target_scaling_methods"] = _fit(results["target_scaling_methods"], row_count, "additive")
    results["target_cvs"] = _fit(results["target_cvs"], row_count, 0)
    results["target_reserve_values"] = [
        None
        if _number(results["target_ultimate_values"][index]) is None
        else float(results["target_ultimate_values"][index]) - fit.latest_values[index]
        for index in range(row_count)
    ]
    results["target_ultimate_source_revision"] = _snapshot_revision(
        results["target_ultimate"], origins, results["target_ultimate_values"]
    )

    if simulate:
        summary = run_bootstrap_simulation(method)
        results["simulation_summary"] = _normalize_summary(summary)
        scaled_mean = summary["scaled"]["mean"]
        results["bootstrap_ultimate"] = [
            _number(fit.latest_values[index] + scaled_mean[index + 1])
            for index in range(row_count)
        ]
    else:
        results["simulation_summary"] = _empty_summary()
        results["bootstrap_ultimate"] = [None] * row_count

    if update_refresh_timestamp:
        method["method_metadata"]["data_refreshed"] = refreshed_at
    # Round-trip through normalization so a recalculated payload is byte-identical
    # to the same payload re-read from disk: every persisted statistic then lives
    # at the canonical six-decimal precision no matter which producer wrote it.
    return normalize_bootstrap_method(method, require_complete=True, timestamp=refreshed_at)


def apply_owned_patch(
    base: Mapping[str, Any], patch: Mapping[str, Any], *, timestamp: Any = None
) -> dict[str, Any]:
    """Rebase Bootstrap-owned edits onto the newest embedded derived snapshots."""

    method = normalize_bootstrap_method(base, require_complete=False, timestamp=timestamp)
    incoming = normalize_bootstrap_method(patch, require_complete=False, timestamp=timestamp)
    owned = owned_projection(incoming)

    details = method["details_tab"]
    incoming_details = owned["details_tab"]
    dfm_changed = (
        _clean(incoming_details.get("dfm_method")).casefold()
        != _clean(details.get("dfm_method")).casefold()
    )
    for key, value in incoming_details.items():
        details[key] = value
    if dfm_changed:
        # A new DFM invalidates every embedded derived value; the caller
        # re-supplies the snapshot through recalculate_bootstrap_method.
        details["dfm_snapshot"] = _normalize_snapshot({})
        details["dfm_source_revision"] = ""

    for key, value in owned["residuals_tab"].items():
        method["residuals_tab"][key] = value
    method["simulation_tab"] = owned["simulation_tab"]
    method["output_tab"] = owned["output_tab"]

    results = method["results_tab"]
    incoming_results = owned["results_tab"]
    if (
        _clean(incoming_results["target_ultimate"]).casefold()
        != _clean(results["target_ultimate"]).casefold()
    ):
        results["target_ultimate_values"] = [None] * len(results.get("origin_labels") or [])
        results["target_ultimate_source_revision"] = ""
    results["target_ultimate"] = incoming_results["target_ultimate"]
    row_count = len(results.get("origin_labels") or [])
    results["target_scaling_methods"] = _fit(
        incoming_results["target_scaling_methods"], row_count, "additive"
    )
    results["target_cvs"] = _fit(incoming_results["target_cvs"], row_count, 0)

    method["method_metadata"]["last_modified"] = _timestamp(timestamp)
    _set_revisions(method)
    return method


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------


def bootstrap_precedent_names(payload: Mapping[str, Any]) -> list[str]:
    """Return the DFM and target-ultimate precedents, in dependency order."""

    details = _tab(payload, "details_tab")
    results = _tab(payload, "results_tab")
    names: list[str] = []
    seen: set[str] = set()
    for value in (details.get("dfm_method"), results.get("target_ultimate")):
        name = _clean(value)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def bootstrap_output_variants(
    payload: Mapping[str, Any],
) -> dict[int, list[float | int | None]]:
    """Return the native and supported 3/6/12-period Bootstrap output variants."""

    method = normalize_bootstrap_method(payload, require_complete=True)
    details = method["details_tab"]
    results = method["results_tab"]
    base_length = _integer(details.get("origin_length"), 12, minimum=1)
    values = _numbers(results.get("bootstrap_ultimate"))
    variants = {base_length: values}
    for target_length in (3, 6, 12):
        if target_length <= base_length or target_length % base_length:
            continue
        aggregate = aggregate_vector_values(
            values, results["origin_labels"], base_length, target_length
        )
        if aggregate:
            variants[target_length] = aggregate
    return variants


def build_bootstrap_output_sidecar(
    payload: Mapping[str, Any],
    *,
    project_name: Any,
    reserving_class: Any,
    csv_file: Any,
    precedents: Any = None,
    existing: Mapping[str, Any] | None = None,
    existing_record: bool | None = None,
    dependents: Any = None,
    notes: Any = None,
    timestamp: Any = None,
    user: Any = "",
    output_changed: bool = True,
    append_audit: bool = True,
    audit_action: Any = None,
    status: Any = 0,
) -> dict[str, Any]:
    """Build the canonical parsed payload for a Bootstrap output sidecar.

    ``precedents`` exists because a Bootstrap's first precedent is a *method*
    while the reserving-class dependency graph is keyed by dataset name.  The
    caller resolves the DFM method to the dataset it publishes and supplies the
    resolved names here; omitting them falls back to the method-name view, which
    is correct whenever a DFM publishes under its own name.
    """

    method = normalize_bootstrap_method(payload, require_complete=True, timestamp=timestamp)
    prior = existing if isinstance(existing, Mapping) else {}
    record_exists = bool(prior) if existing_record is None else bool(existing_record)
    details = method["details_tab"]
    results = method["results_tab"]
    metadata = method["method_metadata"]
    published_at = _timestamp(timestamp)
    actor = _clean(user)
    if not output_changed and record_exists:
        published_at = str(prior.get("updated_at") or "").strip() or published_at
        actor = _clean(prior.get("modified_by")) or actor
    created = str(prior.get("created") or "").strip() or published_at
    sidecar_notes = str(prior.get("notes") or "") if notes is None else str(notes)
    if append_audit:
        audits = append_audit_entry(
            prior.get("audit_log"),
            event_date=published_at,
            action=_clean(audit_action) or (AUDIT_ACTION_UPDATE if record_exists else AUDIT_ACTION_INSERT),
            user=actor,
        )
    else:
        audits = normalize_audit_log(prior.get("audit_log"))
    graph_precedents = bootstrap_precedent_names(method) if precedents is None else precedents
    return validate_sidecar_core({
        "json_format": DATASET_SIDECAR_JSON_FORMAT,
        "dataset_name": details["name"],
        "dataset_type": details["output_type"] or details["name"],
        "dataset_category": details.get("dataset_category", ""),
        "reserving_class": _clean(reserving_class),
        "project_name": _clean(project_name),
        "source_kind": BST_SOURCE_KIND,
        "calculated": True,
        "method_name": details["name"],
        "method_type": BST_METHOD_TYPE,
        "data_format": "Vector",
        "period_length": details["origin_length"],
        # A method output is produced at its own origin period, so the
        # vector it publishes is stored at that period too.
        **stored_length_fields("Vector", details["origin_length"]),
        "transposed": False,
        "show_subtotal": normalize_show_subtotal(prior.get("show_subtotal")),
        "number_format": _clean(prior.get("number_format")) or "#,##0",
        "decimal_places": _integer(prior.get("decimal_places"), 0, minimum=0, maximum=8),
        "csv_file": _clean(csv_file),
        "notes": sidecar_notes,
        "origin_labels": deepcopy(results["origin_labels"]),
        "development_labels": ["Ultimate"],
        "precedents": dependency_entries(graph_precedents),
        "dependents": dependency_entries(prior.get("dependents") if dependents is None else dependents),
        "created": created,
        "updated_at": published_at,
        "modified_by": actor,
        "status": _integer(status, 0, minimum=0),
        "publication_revision": metadata["publication_revision"],
        "audit_log": audits,
    })


__all__ = [
    "BST_FILE_PREFIX",
    "BST_FINEST_LADDER_INTERVAL",
    "BST_JSON_FORMAT",
    "BST_METHOD_TYPE",
    "BST_METHOD_TYPE_CODE",
    "BST_RESIDUAL_GRIDS",
    "BST_SCALE_ROWS",
    "BST_SOURCE_KIND",
    "BootstrapContractError",
    "BstContractError",
    "apply_owned_patch",
    "bootstrap_output_variants",
    "bootstrap_percentile_ladder",
    "bootstrap_precedent_names",
    "bootstrap_simulated_reserves",
    "build_bootstrap_output_sidecar",
    "derived_projection",
    "dfm_snapshot_from_method",
    "ladder_percentile_steps",
    "method_revisions",
    "normalize_bootstrap_method",
    "normalize_summary_block",
    "owned_projection",
    "publication_projection",
    "recalculate_bootstrap_method",
    "run_bootstrap_simulation",
    "snapshot_revision",
    "summarize_bootstrap_simulations",
]
