"""Canonical, filesystem-free contract for Stochastic Consolidation methods.

A Stochastic Consolidation combines the simulated reserves of several Bootstrap
methods ("segments") into one total distribution.  Every persisted-data
producer delegates normalization, revisions, the consolidation run, output
variants and the output-sidecar projection to this module; the numbers come
from :mod:`stochastic_consolidation_simulation`, and each segment's
simulations from ``bootstrap_contract.bootstrap_simulated_reserves``.

A consolidation lists its segments explicitly, by reserving-class path and
method name, because they live in other reserving classes; it never reads its
own class's datasets.  Like a Bootstrap it persists no simulations: the run is
rebuilt from the segments and the seed, and the method keeps a summary rich
enough for every Results view.  Each segment records the revision of the
bootstrap it consumed, so a reader can say which segment changed since.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .bootstrap_contract import (
    BST_FINEST_LADDER_INTERVAL,
    BST_METHOD_TYPE,
    BootstrapContractError,
    bootstrap_simulated_reserves,
    ladder_percentile_steps,
    normalize_bootstrap_method,
    normalize_summary_block,
)
from .bootstrap_simulation import summarize_reserves
from .dataset_display_contract import normalize_show_subtotal
from .dfm_contract import aggregate_vector_values, canonical_number
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
from .stochastic_consolidation_simulation import (
    SCON_CORRELATION_OPTIONS,
    SCON_DEFAULT_DEGREES_OF_FREEDOM,
    SCON_DEPENDENCY_TYPES,
    ConsolidationOptions,
    StochasticConsolidationError,
    adjusted_correlation_matrix,
    consolidate_simulations,
    summarize_consolidated_simulations,
    target_correlation_matrix,
)
from .timestamps import persisted_timestamp as _timestamp


SCON_JSON_FORMAT = "arcrho-stochastic-consolidation-v4"
SCON_METHOD_TYPE = "Stochastic Consolidation"
SCON_SOURCE_KIND = "stochastic_consolidation"
SCON_METHOD_TYPE_CODE = 7
SCON_FILE_PREFIX = "SCON@"


class StochasticConsolidationContractError(ValueError):
    """Raised when a consolidation payload cannot satisfy the canonical contract."""


def _clean(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split()).strip()


def _key(value: Any) -> str:
    return _clean(value).casefold()


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


def _fit(values: list[Any], size: int, fill: Any) -> list[Any]:
    trimmed = list(values[:size])
    trimmed.extend([fill] * (size - len(trimmed)))
    return trimmed


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = _clean(value).lower().replace(" ", "_").replace("-", "_")
    return text if text in allowed else default


def _segment_label(segment: Mapping[str, Any]) -> str:
    label = f"{_clean(segment.get('reserving_class'))} / {_clean(segment.get('method_name'))}"
    project = _clean(segment.get("project_name"))
    return f"{project}: {label}" if project else label


def _segment_identity(segment: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _key(segment.get("project_name")),
        _key(segment.get("reserving_class")),
        _key(segment.get("method_name")),
    )


# ---------------------------------------------------------------------------
# Segments and correlations
# ---------------------------------------------------------------------------


def _normalize_segment(raw: Any) -> dict[str, Any]:
    """One included bootstrap.

    ``project_name`` names the project the bootstrap lives in and is written
    only when it is not the consolidation's own project, so a same-project
    segment keeps its original shape.
    """

    source = dict(raw) if isinstance(raw, Mapping) else {}
    factor = _number(source.get("factor"))
    project = _clean(source.get("project_name"))
    return {
        **({"project_name": project} if project else {}),
        "reserving_class": _clean(source.get("reserving_class")),
        "method_name": _clean(source.get("method_name")),
        "factor": 1 if factor is None else factor,
        "bootstrap_revision": _clean(source.get("bootstrap_revision")),
    }


def _output_origin_labels(origins: list[str], raw: Any) -> list[str]:
    """The origins the output vector publishes: the latest ones of the run.

    A run whose segments all live in the host project publishes every origin.
    One that takes a longer history from another project publishes only the
    host project's origins, because the host's datasets have only those rows.
    """

    labels = _labels(raw)
    if labels and len(labels) <= len(origins) and origins[len(origins) - len(labels):] == labels:
        return labels
    return list(origins)


def _target_matrix(raw: Any, size: int) -> list[list[float | int | None]]:
    """The target rank correlations as a full symmetric matrix, upper triangle authoritative."""

    try:
        square = target_correlation_matrix("specified", size, raw if isinstance(raw, list) else [])
    except StochasticConsolidationError as exc:
        raise StochasticConsolidationContractError(str(exc)) from exc
    return _matrix(square)


def bootstrap_segment_revision(bootstrap_payload: Mapping[str, Any]) -> str:
    """The revision a consolidation records for a bootstrap it consumed.

    It moves whenever the bootstrap's simulations could: its simulation
    settings, its model, or anything derived from its DFM and targets.  A
    display-only change on the bootstrap's page leaves it alone.
    """

    try:
        method = normalize_bootstrap_method(bootstrap_payload, require_complete=False)
    except BootstrapContractError as exc:
        raise StochasticConsolidationContractError(str(exc)) from exc
    return fingerprint({
        "model_type": method["details_tab"]["model_type"],
        "simulation_tab": method["simulation_tab"],
        "derived_revision": method["method_metadata"]["derived_revision"],
    })


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _empty_summary() -> dict[str, Any]:
    return {
        "simulation_count": 0,
        "random_seed": 0,
        "scaled": {},
        "achieved_rank_correlations": [],
        "achieved_linear_correlations": [],
        "segments": [],
        "diversification": {},
    }


def _normalize_summary(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return _empty_summary()
    segments = raw.get("segments") if isinstance(raw.get("segments"), list) else []
    diversification = raw.get("diversification")
    diversification = dict(diversification) if isinstance(diversification, Mapping) else {}
    return {
        "simulation_count": _integer(raw.get("simulation_count"), 0, minimum=0),
        "random_seed": _integer(raw.get("random_seed"), 0, minimum=0),
        "scaled": normalize_summary_block(raw.get("scaled")),
        "achieved_rank_correlations": _matrix(raw.get("achieved_rank_correlations")),
        "achieved_linear_correlations": _matrix(raw.get("achieved_linear_correlations")),
        "segments": [
            {
                key: _number(item.get(key))
                for key in ("factor", "mean", "standard_error", "cv", "share_of_mean")
            }
            for item in segments
            if isinstance(item, Mapping)
        ],
        "diversification": {
            key: _number(diversification.get(key))
            for key in ("total_standard_error", "sum_of_standalone_standard_errors", "benefit")
            if key in diversification
        },
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_stochastic_consolidation_method(
    payload: Mapping[str, Any],
    *,
    require_complete: bool = True,
    timestamp: Any = None,
) -> dict[str, Any]:
    """Return the exact canonical Stochastic Consolidation payload."""

    if not isinstance(payload, Mapping):
        raise StochasticConsolidationContractError("Stochastic Consolidation payload must be a JSON object.")
    json_format = _clean(payload.get("json_format"))
    if json_format != SCON_JSON_FORMAT:
        raise StochasticConsolidationContractError(
            f"Unsupported Stochastic Consolidation JSON format: {json_format!r}."
        )

    details_source = _tab(payload, "details_tab")
    segments_source = _tab(payload, "segments_tab")
    correlation_source = _tab(payload, "correlation_tab")
    results_source = _tab(payload, "results_tab")
    metadata_source = _tab(payload, "method_metadata")

    raw_segments = segments_source.get("segments") if isinstance(segments_source.get("segments"), list) else []
    segments = [_normalize_segment(item) for item in raw_segments]
    size = len(segments)
    origins = _labels(results_source.get("origin_labels"))
    row_count = len(origins)
    degrees = _number(correlation_source.get("degrees_of_freedom"))

    default_time = _timestamp(timestamp)
    last_modified = _clean(metadata_source.get("last_modified")) or default_time
    data_refreshed = _clean(metadata_source.get("data_refreshed")) or last_modified

    normalized: dict[str, Any] = {
        "json_format": SCON_JSON_FORMAT,
        "details_tab": {
            "name": _clean(details_source.get("name")),
            "method_type": SCON_METHOD_TYPE,
            "output_type": _clean(details_source.get("output_type")),
            "dataset_category": _clean(details_source.get("dataset_category")),
            "base_triangle_type": _clean(details_source.get("base_triangle_type")),
            "origin_length": _integer(details_source.get("origin_length"), 12, minimum=1),
            "development_length": _integer(details_source.get("development_length"), 12, minimum=1),
            "simulation_count": _integer(details_source.get("simulation_count"), 0, minimum=0),
            "random_seed": _integer(details_source.get("random_seed"), 0, minimum=0),
        },
        "segments_tab": {"segments": segments},
        "correlation_tab": {
            "correlation_option": _choice(
                correlation_source.get("correlation_option"), SCON_CORRELATION_OPTIONS, "specified"
            ),
            "dependency_type": _choice(
                correlation_source.get("dependency_type"), SCON_DEPENDENCY_TYPES, "normal"
            ),
            "degrees_of_freedom": SCON_DEFAULT_DEGREES_OF_FREEDOM if not degrees or degrees <= 0 else degrees,
            "target_correlations": _target_matrix(correlation_source.get("target_correlations"), size),
            "adjusted_correlations": _matrix(correlation_source.get("adjusted_correlations")),
        },
        "results_tab": {
            "input_revision": _clean(results_source.get("input_revision")),
            "origin_labels": origins,
            "output_origin_labels": _output_origin_labels(origins, results_source.get("output_origin_labels")),
            "latest_values": _fit(_numbers(results_source.get("latest_values")), row_count, None),
            "simulation_summary": _normalize_summary(results_source.get("simulation_summary")),
            "consolidation_ultimate": _fit(
                _numbers(results_source.get("consolidation_ultimate")), row_count, None
            ),
        },
        "method_metadata": {
            "method_type": SCON_METHOD_TYPE,
            "source_kind": SCON_SOURCE_KIND,
            "last_modified": last_modified,
            "data_refreshed": data_refreshed,
            "owned_revision": "",
            "derived_revision": "",
            "publication_revision": "",
        },
    }
    _set_revisions(normalized)
    if require_complete:
        _validate_complete(normalized)
    return normalized


def _validate_complete(payload: Mapping[str, Any]) -> None:
    details = _tab(payload, "details_tab")
    segments = _tab(payload, "segments_tab").get("segments") or []
    for key in ("name", "output_type"):
        if not _clean(details.get(key)):
            raise StochasticConsolidationContractError(f"Stochastic Consolidation details_tab.{key} is required.")
    if _integer(details.get("origin_length"), 0) not in {1, 3, 6, 12}:
        raise StochasticConsolidationContractError(
            "Stochastic Consolidation origin_length must be 1, 3, 6, or 12 months."
        )
    if not segments:
        raise StochasticConsolidationContractError("Stochastic Consolidation needs at least one included bootstrap.")
    seen: set[tuple[str, str, str]] = set()
    for index, segment in enumerate(segments, start=1):
        if not segment["reserving_class"] or not segment["method_name"]:
            raise StochasticConsolidationContractError(
                f"Stochastic Consolidation segment {index} needs a reserving class and a method."
            )
        identity = _segment_identity(segment)
        if identity in seen:
            raise StochasticConsolidationContractError(
                f"Stochastic Consolidation includes {_segment_label(segment)} more than once."
            )
        seen.add(identity)


# ---------------------------------------------------------------------------
# Projections and revisions
# ---------------------------------------------------------------------------


_OWNED_DETAILS = (
    "name",
    "output_type",
    "dataset_category",
    "base_triangle_type",
    "origin_length",
    "development_length",
    "random_seed",
)
_OWNED_CORRELATION = ("correlation_option", "dependency_type", "degrees_of_freedom", "target_correlations")


def owned_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    correlation = _tab(payload, "correlation_tab")
    segments = _tab(payload, "segments_tab").get("segments") or []
    return {
        "details_tab": {key: details.get(key) for key in _OWNED_DETAILS},
        "segments_tab": [
            {
                key: segment.get(key)
                for key in ("project_name", "reserving_class", "method_name", "factor")
                if key in segment
            }
            for segment in segments
        ],
        "correlation_tab": {key: deepcopy(correlation.get(key)) for key in _OWNED_CORRELATION},
    }


def run_input_revision(payload: Mapping[str, Any]) -> str:
    """Fingerprint of everything a consolidation run depends on besides its segments' data.

    Stored as ``results_tab.input_revision`` when the method is consolidated,
    so a reader tells "inputs changed since the last run" by recomputing it.
    """

    owned = owned_projection(payload)
    details = owned["details_tab"]
    return fingerprint({
        "base_triangle_type": details.get("base_triangle_type"),
        "random_seed": details.get("random_seed"),
        "segments": owned["segments_tab"],
        "correlation": owned["correlation_tab"],
    })


def derived_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    correlation = _tab(payload, "correlation_tab")
    results = _tab(payload, "results_tab")
    segments = _tab(payload, "segments_tab").get("segments") or []
    return {
        "simulation_count": details.get("simulation_count", 0),
        "bootstrap_revisions": [segment.get("bootstrap_revision", "") for segment in segments],
        "adjusted_correlations": deepcopy(correlation.get("adjusted_correlations") or []),
        "input_revision": results.get("input_revision", ""),
        "origin_labels": deepcopy(results.get("origin_labels") or []),
        "latest_values": deepcopy(results.get("latest_values") or []),
        "simulation_summary": deepcopy(results.get("simulation_summary") or {}),
        "consolidation_ultimate": deepcopy(results.get("consolidation_ultimate") or []),
    }


def publication_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    details = _tab(payload, "details_tab")
    labels, values = _published_output(_tab(payload, "results_tab"))
    return {
        "dataset_name": details.get("name", ""),
        "dataset_type": details.get("output_type", ""),
        "dataset_category": details.get("dataset_category", ""),
        "origin_length": details.get("origin_length", 12),
        "origin_labels": labels,
        "consolidation_ultimate": values,
    }


def _published_output(results: Mapping[str, Any]) -> tuple[list[Any], list[Any]]:
    """The output vector's origins and values: the run's last ``output_origin_labels`` rows."""

    origins = list(results.get("origin_labels") or [])
    labels = list(results.get("output_origin_labels") or origins)
    values = list(results.get("consolidation_ultimate") or [])
    start = max(0, len(values) - len(labels)) if len(labels) < len(origins) else 0
    return deepcopy(labels), deepcopy(values[start:])


def method_revisions(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return deterministic revisions for owned, derived, and published state."""

    return {
        "owned_revision": fingerprint(owned_projection(payload)),
        "derived_revision": fingerprint(derived_projection(payload)),
        "publication_revision": fingerprint(publication_projection(payload)),
    }


def _set_revisions(payload: dict[str, Any]) -> None:
    payload.setdefault("method_metadata", {}).update(method_revisions(payload))


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


def _segment_inputs_checked(
    method: Mapping[str, Any], segment_inputs: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize each included bootstrap and refuse a segment the run cannot use."""

    segments = method["segments_tab"]["segments"]
    if len(segment_inputs) != len(segments):
        raise StochasticConsolidationContractError(
            f"Stochastic Consolidation has {len(segments)} segments but {len(segment_inputs)} bootstraps were supplied."
        )
    base_type = _key(method["details_tab"]["base_triangle_type"])
    checked: list[dict[str, Any]] = []
    first_count: int | None = None
    for segment, supplied in zip(segments, segment_inputs):
        label = _segment_label(segment)
        source = supplied.get("bootstrap") if isinstance(supplied, Mapping) else None
        if not isinstance(source, Mapping):
            raise StochasticConsolidationContractError(f"No bootstrap was supplied for {label}.")
        try:
            bootstrap = normalize_bootstrap_method(source, require_complete=False)
        except BootstrapContractError as exc:
            raise StochasticConsolidationContractError(f"{label}: {exc}") from exc
        if _key(bootstrap["details_tab"]["name"]) != _key(segment["method_name"]):
            raise StochasticConsolidationContractError(
                f"The bootstrap supplied for {label} is {bootstrap['details_tab']['name']!r}."
            )
        segment_base = _key(supplied.get("base_triangle_type"))
        if base_type and segment_base and segment_base != base_type:
            raise StochasticConsolidationContractError(
                f"{label} is based on {_clean(supplied.get('base_triangle_type'))!r}, not the consolidation's "
                f"{method['details_tab']['base_triangle_type']!r}."
            )
        count = bootstrap["simulation_tab"]["simulation_count"]
        if first_count is None:
            first_count = count
        elif count != first_count:
            raise StochasticConsolidationContractError(
                f"{label} runs {count:,} simulations; {_segment_label(segments[0])} runs {first_count:,}."
            )
        checked.append(bootstrap)
    return checked


def consolidate_stochastic_method(
    payload: Mapping[str, Any],
    segment_inputs: Sequence[Mapping[str, Any]],
    *,
    ranks: Sequence[Sequence[int]] | None = None,
    timestamp: Any = None,
) -> dict[str, Any]:
    """Run the consolidation a payload describes and return the refreshed payload.

    ``segment_inputs`` holds one mapping per included segment, in the same
    order: ``bootstrap`` is that segment's stored Bootstrap payload and
    ``base_triangle_type`` (optional) the input type of the DFM it bootstraps.
    Every bootstrap is re-simulated from its seed, the segments are combined by
    ResQ's rules, and the summary, the output vector and each segment's
    consumed revision are stored.  ``ranks`` replaces the generated ranks,
    which is how ResQ's own ranks reproduce ResQ.
    """

    return _consolidated(payload, segment_inputs, ranks=ranks, timestamp=timestamp)[0]


def consolidate_stochastic_method_with_ladder(
    payload: Mapping[str, Any],
    segment_inputs: Sequence[Mapping[str, Any]],
    *,
    timestamp: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``consolidate_stochastic_method`` plus the run's finest percentile ladder.

    The stored summary holds every half percent.  The ladder at
    ``BST_FINEST_LADDER_INTERVAL`` is taken from the same simulations, keyed as
    the stored one is, and is never stored: a page keeps it for the finer Full
    Ladder intervals until its next run.
    """

    method, combined = _consolidated(payload, segment_inputs, timestamp=timestamp)
    steps = ladder_percentile_steps(BST_FINEST_LADDER_INTERVAL)
    block = summarize_reserves(combined["reserves"], percentiles=steps)
    ladder = {
        "interval": BST_FINEST_LADDER_INTERVAL,
        "scaled": {key: _numbers(values) for key, values in block["percentiles"].items()},
    }
    return method, ladder


def _consolidated(
    payload: Mapping[str, Any],
    segment_inputs: Sequence[Mapping[str, Any]],
    *,
    ranks: Sequence[Sequence[int]] | None = None,
    timestamp: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The refreshed payload and the combined simulations it summarizes."""

    refreshed_at = _timestamp(timestamp)
    method = normalize_stochastic_consolidation_method(payload, require_complete=True, timestamp=refreshed_at)
    bootstraps = _segment_inputs_checked(method, segment_inputs)
    host_origins = [
        list(bootstrap["details_tab"]["dfm_snapshot"].get("origin_labels") or [])
        for segment, bootstrap in zip(method["segments_tab"]["segments"], bootstraps)
        if not segment.get("project_name")
    ]
    details = method["details_tab"]
    correlation = method["correlation_tab"]
    segments = method["segments_tab"]["segments"]

    try:
        simulations = [bootstrap_simulated_reserves(bootstrap) for bootstrap in bootstraps]
        options = ConsolidationOptions(
            simulation_count=bootstraps[0]["simulation_tab"]["simulation_count"],
            random_seed=details["random_seed"],
            correlation_option=correlation["correlation_option"],
            dependency_type=correlation["dependency_type"],
            degrees_of_freedom=float(correlation["degrees_of_freedom"]),
            target_correlations=correlation["target_correlations"],
            factors=[float(segment["factor"]) for segment in segments],
        )
        combined = consolidate_simulations(simulations, options, ranks=ranks)
    except (BootstrapContractError, StochasticConsolidationError) as exc:
        raise StochasticConsolidationContractError(str(exc)) from exc
    summary = summarize_consolidated_simulations(combined)

    for segment, bootstrap in zip(segments, bootstraps):
        segment["bootstrap_revision"] = bootstrap_segment_revision(bootstrap)
    details["simulation_count"] = combined["simulation_count"]
    correlation["adjusted_correlations"] = combined["adjusted_correlations"]
    latest = list(combined["latest_values"] or [])
    scaled_mean = summary["scaled"]["mean"]
    results = method["results_tab"]
    results["input_revision"] = run_input_revision(method)
    results["origin_labels"] = list(combined["origin_labels"])
    results["output_origin_labels"] = (
        max(host_origins, key=len) if host_origins else list(combined["origin_labels"])
    )
    results["latest_values"] = latest
    results["simulation_summary"] = summary
    results["consolidation_ultimate"] = [
        latest[index] + scaled_mean[index + 1] if index < len(latest) else None
        for index in range(len(combined["origin_labels"]))
    ]
    method["method_metadata"]["data_refreshed"] = refreshed_at
    # Round-trip through normalization so a consolidated payload equals the
    # same payload re-read from disk, whichever producer wrote it.
    return normalize_stochastic_consolidation_method(method, require_complete=True, timestamp=refreshed_at), combined


def stale_segments(
    payload: Mapping[str, Any], current_bootstraps: Sequence[Mapping[str, Any] | None]
) -> list[dict[str, str]]:
    """The segments whose bootstrap changed, or vanished, since the last consolidation.

    ``current_bootstraps`` holds each segment's current Bootstrap payload in
    order, ``None`` for one that no longer exists.  Each stale segment comes
    back as its reserving class, method name and a plain reason.
    """

    method = normalize_stochastic_consolidation_method(payload, require_complete=False)
    stale: list[dict[str, str]] = []
    for index, segment in enumerate(method["segments_tab"]["segments"]):
        current = current_bootstraps[index] if index < len(current_bootstraps) else None
        if not isinstance(current, Mapping):
            reason = "missing"
        elif not segment["bootstrap_revision"]:
            reason = "not_consolidated"
        elif bootstrap_segment_revision(current) != segment["bootstrap_revision"]:
            reason = "changed"
        else:
            continue
        stale.append({
            "project_name": segment.get("project_name", ""),
            "reserving_class": segment["reserving_class"],
            "method_name": segment["method_name"],
            "reason": reason,
        })
    return stale


def apply_owned_patch(
    base: Mapping[str, Any], patch: Mapping[str, Any], *, timestamp: Any = None
) -> dict[str, Any]:
    """Rebase consolidation-owned edits onto the newest stored derived state.

    A segment keeps the bootstrap revision it was consolidated with only while
    it names the same reserving class and method.
    """

    method = normalize_stochastic_consolidation_method(base, require_complete=False, timestamp=timestamp)
    incoming = normalize_stochastic_consolidation_method(patch, require_complete=False, timestamp=timestamp)
    owned = owned_projection(incoming)

    method["details_tab"].update(owned["details_tab"])
    consumed = {
        _segment_identity(segment): segment["bootstrap_revision"]
        for segment in method["segments_tab"]["segments"]
    }
    method["segments_tab"]["segments"] = [
        {**segment, "bootstrap_revision": consumed.get(_segment_identity(segment), "")}
        for segment in owned["segments_tab"]
    ]
    method["correlation_tab"].update(owned["correlation_tab"])
    method["method_metadata"]["last_modified"] = _timestamp(timestamp)
    return normalize_stochastic_consolidation_method(method, require_complete=False, timestamp=timestamp)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def stochastic_consolidation_precedents(
    payload: Mapping[str, Any], *, reserving_class: Any = ""
) -> list[dict[str, str]]:
    """The included bootstraps as dependency entries, in segment order.

    A bootstrap in another reserving class carries that class in the entry's
    reserved ``reserving_class`` field, and one in another project also its
    ``project``; one in the consolidation's own class stays a plain same-class
    entry.
    """

    host = _key(reserving_class)
    entries = []
    for segment in _tab(payload, "segments_tab").get("segments") or []:
        entry = {"dataset_name": _clean(segment.get("method_name")), "method_type": BST_METHOD_TYPE}
        segment_class = _clean(segment.get("reserving_class"))
        project = _clean(segment.get("project_name"))
        if segment_class and (project or _key(segment_class) != host):
            entry["reserving_class"] = segment_class
        if project:
            entry["project"] = project
        entries.append(entry)
    return dependency_entries(entries)


def stochastic_consolidation_output_variants(
    payload: Mapping[str, Any],
) -> dict[int, list[float | int | None]]:
    """Return the native and supported 3/6/12-period output variants."""

    method = normalize_stochastic_consolidation_method(payload, require_complete=True)
    details = method["details_tab"]
    results = method["results_tab"]
    base_length = _integer(details.get("origin_length"), 12, minimum=1)
    labels, published = _published_output(results)
    values = _numbers(published)
    variants = {base_length: values}
    for target_length in (3, 6, 12):
        if target_length <= base_length or target_length % base_length:
            continue
        aggregate = aggregate_vector_values(values, labels, base_length, target_length)
        if aggregate:
            variants[target_length] = aggregate
    return variants


def build_stochastic_consolidation_output_sidecar(
    payload: Mapping[str, Any],
    *,
    project_name: Any,
    reserving_class: Any,
    csv_file: Any,
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
    """Build the canonical parsed payload for a consolidation's output sidecar."""

    method = normalize_stochastic_consolidation_method(payload, require_complete=True, timestamp=timestamp)
    prior = existing if isinstance(existing, Mapping) else {}
    record_exists = bool(prior) if existing_record is None else bool(existing_record)
    details = method["details_tab"]
    results = method["results_tab"]
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
    return validate_sidecar_core({
        "json_format": DATASET_SIDECAR_JSON_FORMAT,
        "dataset_name": details["name"],
        "dataset_type": details["output_type"] or details["name"],
        "dataset_category": details.get("dataset_category", ""),
        "reserving_class": _clean(reserving_class),
        "project_name": _clean(project_name),
        "source_kind": SCON_SOURCE_KIND,
        "calculated": True,
        "method_name": details["name"],
        "method_type": SCON_METHOD_TYPE,
        "data_format": "Vector",
        "period_length": details["origin_length"],
        **stored_length_fields("Vector", details["origin_length"]),
        "transposed": False,
        "show_subtotal": normalize_show_subtotal(prior.get("show_subtotal")),
        "number_format": _clean(prior.get("number_format")) or "#,##0",
        "decimal_places": _integer(prior.get("decimal_places"), 0, minimum=0, maximum=8),
        "csv_file": _clean(csv_file),
        "notes": sidecar_notes,
        "origin_labels": _published_output(results)[0],
        "development_labels": ["Ultimate"],
        "precedents": stochastic_consolidation_precedents(method, reserving_class=reserving_class),
        "dependents": dependency_entries(prior.get("dependents") if dependents is None else dependents),
        "created": created,
        "updated_at": published_at,
        "modified_by": actor,
        "status": _integer(status, 0, minimum=0),
        "publication_revision": method["method_metadata"]["publication_revision"],
        "audit_log": audits,
    })


__all__ = [
    "SCON_FILE_PREFIX",
    "SCON_JSON_FORMAT",
    "SCON_METHOD_TYPE",
    "SCON_METHOD_TYPE_CODE",
    "SCON_SOURCE_KIND",
    "StochasticConsolidationContractError",
    "apply_owned_patch",
    "bootstrap_segment_revision",
    "build_stochastic_consolidation_output_sidecar",
    "consolidate_stochastic_method",
    "consolidate_stochastic_method_with_ladder",
    "derived_projection",
    "method_revisions",
    "normalize_stochastic_consolidation_method",
    "owned_projection",
    "publication_projection",
    "run_input_revision",
    "stale_segments",
    "stochastic_consolidation_output_variants",
    "stochastic_consolidation_precedents",
]
