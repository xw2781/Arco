"""Load, consolidate, and save Stochastic Consolidation methods.

A Stochastic Consolidation combines the simulated reserves of several Bootstrap
methods ("segments") into one total distribution.  Its segments live in other
reserving classes, named by class path and method name, and a segment that
names a project lives in that project instead of the consolidation's own.  So
this service reads each segment's Bootstrap method JSON (and the input type of
the DFM that bootstrap re-fits) from its own project and class.  It never reads
the host class's datasets.

Cross-class propagation is deferred: saving a bootstrap does not refresh the
consolidations that include it.  Instead the load compares the revision each
segment was consumed at with the bootstrap's current one and reports every
segment that changed, vanished, or was never consolidated, and the page offers
Consolidate.  No reverse ``dependents`` edge is written onto a bootstrap's
sidecar for the same reason.

Every number comes from ``arcrho_api.stochastic_consolidation_contract``; the
service only reads, checks, and publishes.
"""
from __future__ import annotations

import getpass
import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from fastapi import HTTPException

from arcrho_api.bootstrap_contract import BST_JSON_FORMAT
from arcrho_api.dfm_contract import DFM_JSON_FORMAT
from arcrho_api.io import persisted_json_text
from arcrho_api.stochastic_consolidation_contract import (
    SCON_JSON_FORMAT,
    StochasticConsolidationContractError,
    apply_owned_patch,
    build_stochastic_consolidation_output_sidecar,
    consolidate_stochastic_method,
    consolidate_stochastic_method_with_ladder,
    method_revisions,
    normalize_stochastic_consolidation_method,
    publication_projection,
    run_input_revision,
    stale_segments,
    stochastic_consolidation_output_variants,
    stochastic_consolidation_precedents,
)
from arcrho_api.timestamps import utc_now_text
from app_server import config
from app_server.helpers import sanitize_dataset_file_name
from app_server.services import (
    bootstrap_service,
    dataset_sidecar_status_service,
    dependent_propagation_service,
    precedent_cache_service,
    user_identity_service,
)


READ_MAX_WORKERS = 8
_READ_EXECUTOR = ThreadPoolExecutor(
    max_workers=READ_MAX_WORKERS,
    thread_name_prefix="arcrho-scon-read",
)

# The run state the page's header chip shows.
STATE_UP_TO_DATE = "up_to_date"
STATE_NOT_RUN = "not_run"
STATE_INPUTS_CHANGED = "inputs_changed"
STATE_SEGMENT_CHANGED = "segment_changed"

# Per-segment freshness, as ``stale_segments`` reports it, plus the one it
# leaves out.
SEGMENT_CURRENT = "current"

# Why a segment cannot be consolidated as it stands, shown inline on its row.
PROBLEM_MISSING = "missing"
PROBLEM_NO_RUN = "no_run"
PROBLEM_SIMULATION_COUNT = "simulation_count_mismatch"
PROBLEM_BASE_TYPE = "base_type_mismatch"


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _key(value: Any) -> str:
    return " ".join(_clean(value).lower().split())


def _now() -> str:
    return utc_now_text()


def _lock(project_name: str, reserving_class: str):
    return dataset_sidecar_status_service.reserving_class_io_lock(project_name, reserving_class)


def _method_path(project_name: str, reserving_class: str, method_name: str) -> str:
    return dataset_sidecar_status_service.method_json_path(
        project_name,
        reserving_class,
        dataset_sidecar_status_service.METHOD_TYPE_STOCHASTIC_CONSOLIDATION,
        method_name,
    )


def _bootstrap_path(project_name: str, reserving_class: str, method_name: str) -> str:
    return dataset_sidecar_status_service.method_json_path(
        project_name,
        reserving_class,
        dataset_sidecar_status_service.METHOD_TYPE_BOOTSTRAP,
        method_name,
    )


def _dfm_path(project_name: str, reserving_class: str, method_name: str) -> str:
    return dataset_sidecar_status_service.method_json_path(
        project_name,
        reserving_class,
        dataset_sidecar_status_service.METHOD_TYPE_DFM,
        method_name,
    )


def _sidecar_path(project_name: str, reserving_class: str, dataset_name: str) -> str:
    return dataset_sidecar_status_service.sidecar_path(project_name, reserving_class, dataset_name)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except PermissionError as exc:
        raise HTTPException(423, f"File is locked or inaccessible: {os.path.basename(path)}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"Invalid JSON: {os.path.basename(path)}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _contract_call(func, *args: Any, **kwargs: Any) -> Any:
    try:
        return func(*args, **kwargs)
    except StochasticConsolidationContractError as exc:
        raise HTTPException(422, str(exc)) from exc


def _details(payload: Mapping[str, Any]) -> Dict[str, Any]:
    value = payload.get("details_tab") if isinstance(payload, Mapping) else None
    return value if isinstance(value, dict) else {}


def _results_tab(payload: Mapping[str, Any]) -> Dict[str, Any]:
    value = payload.get("results_tab") if isinstance(payload, Mapping) else None
    return value if isinstance(value, dict) else {}


def _segments(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    tab = payload.get("segments_tab") if isinstance(payload, Mapping) else None
    rows = tab.get("segments") if isinstance(tab, Mapping) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _identity(payload: Mapping[str, Any]) -> Tuple[str, str]:
    method_name = _clean(_details(payload).get("name"))
    if not method_name:
        raise HTTPException(422, "Stochastic Consolidation method name is required.")
    return method_name, method_name


def _label(reserving_class: Any, method_name: Any, project_name: Any = "") -> str:
    label = f"{_clean(reserving_class)} / {_clean(method_name)}"
    return f"{_clean(project_name)}: {label}" if _clean(project_name) else label


def _segment_project(project_name: str, segment: Mapping[str, Any]) -> str:
    """The project a segment's bootstrap lives in: its own, or the consolidation's."""

    return _clean(segment.get("project_name")) or project_name


def _segment_key(segment: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        _key(segment.get("project_name")),
        _key(segment.get("reserving_class")),
        _key(segment.get("method_name")),
    )


def _revision_response(payload: Mapping[str, Any]) -> Dict[str, str]:
    revisions = method_revisions(payload)
    publication = _clean(revisions.get("publication_revision"))
    return {
        "owned_revision": _clean(revisions.get("owned_revision")),
        "derived_revision": _clean(revisions.get("derived_revision")),
        "publication_revision": publication,
        "method_revision": publication,
    }


def _sidecar_response(payload: Mapping[str, Any], *, exists: bool) -> Dict[str, Any]:
    if not exists:
        return {"exists": False, "notes": "", "audit_log": []}
    return {**dict(payload), "exists": True}


# ---------------------------------------------------------------------------
# Reading the segments from their own reserving classes
# ---------------------------------------------------------------------------


def _read_bootstrap(project_name: str, reserving_class: str, method_name: str) -> Dict[str, Any]:
    """One segment's Bootstrap payload and the input type of the DFM it re-fits.

    ``bootstrap`` is ``None`` when the method is gone or is not a readable
    Bootstrap; ``base_triangle_type`` is empty when its DFM cannot be read,
    which leaves the base-type check to the DFM's own absence.
    """

    try:
        payload = _read_json(_bootstrap_path(project_name, reserving_class, method_name))
    except HTTPException as exc:
        return {"bootstrap": None, "base_triangle_type": "", "error": str(exc.detail)}
    if not payload or _clean(payload.get("json_format")) != BST_JSON_FORMAT:
        return {"bootstrap": None, "base_triangle_type": "", "error": ""}
    base_type = ""
    dfm_name = _clean(_details(payload).get("dfm_method"))
    if dfm_name:
        try:
            dfm = _read_json(_dfm_path(project_name, reserving_class, dfm_name))
        except HTTPException:
            dfm = {}
        if _clean(dfm.get("json_format")).lower() == DFM_JSON_FORMAT:
            base_type = _clean(_details(dfm).get("input_triangle"))
    return {"bootstrap": payload, "base_triangle_type": base_type, "error": ""}


def _read_segments(project_name: str, method: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Each included bootstrap, read in parallel and returned in segment order."""

    futures = [
        _READ_EXECUTOR.submit(
            _read_bootstrap,
            _segment_project(project_name, segment),
            _clean(segment.get("reserving_class")),
            _clean(segment.get("method_name")),
        )
        for segment in _segments(method)
    ]
    return [future.result() for future in futures]


def _bootstrap_statistics(bootstrap: Mapping[str, Any] | None) -> Dict[str, Any]:
    """A bootstrap's standalone total-reserve figures, scaled when it has a target."""

    if not isinstance(bootstrap, Mapping):
        return {"simulation_count": 0, "random_seed": 0, "has_run": False,
                "mean": None, "standard_error": None, "cv": None}
    simulation = bootstrap.get("simulation_tab") if isinstance(bootstrap.get("simulation_tab"), Mapping) else {}
    summary = _results_tab(bootstrap).get("simulation_summary")
    summary = summary if isinstance(summary, Mapping) else {}
    block: Mapping[str, Any] = {}
    for name in ("scaled", "unscaled"):
        candidate = summary.get(name)
        if isinstance(candidate, Mapping) and isinstance(candidate.get("mean"), list) and candidate["mean"]:
            block = candidate
            break

    def _total(field: str) -> float | None:
        values = block.get(field)
        value = values[0] if isinstance(values, list) and values else None
        return float(value) if isinstance(value, (int, float)) else None

    mean = _total("mean")
    deviation = _total("standard_error")
    try:
        run_count = int(summary.get("simulation_count") or 0)
    except (TypeError, ValueError):
        run_count = 0
    try:
        count = int(simulation.get("simulation_count") or 0)
    except (TypeError, ValueError):
        count = 0
    try:
        seed = int(simulation.get("random_seed") or 0)
    except (TypeError, ValueError):
        seed = 0
    return {
        "simulation_count": count,
        "random_seed": seed,
        "has_run": bool(run_count and mean is not None),
        "mean": mean,
        "standard_error": deviation,
        "cv": deviation / mean if mean and deviation is not None else None,
    }


def _segment_rows(method: Mapping[str, Any], reads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per included segment: its freshness, its figures, and any problem."""

    stale = _contract_call(stale_segments, method, [read.get("bootstrap") for read in reads])
    stale_by_identity = {_segment_key(item): item["reason"] for item in stale}
    base_type = _key(_details(method).get("base_triangle_type"))
    rows: List[Dict[str, Any]] = []
    first_count: int | None = None
    for segment, read in zip(_segments(method), reads):
        bootstrap = read.get("bootstrap")
        statistics = _bootstrap_statistics(bootstrap)
        problems: List[str] = []
        if bootstrap is None:
            problems.append(PROBLEM_MISSING)
        else:
            if not statistics["has_run"]:
                problems.append(PROBLEM_NO_RUN)
            if first_count is None:
                first_count = statistics["simulation_count"]
            elif statistics["simulation_count"] != first_count:
                problems.append(PROBLEM_SIMULATION_COUNT)
            segment_base = _key(read.get("base_triangle_type"))
            if base_type and segment_base and segment_base != base_type:
                problems.append(PROBLEM_BASE_TYPE)
        rows.append({
            "project_name": _clean(segment.get("project_name")),
            "reserving_class": _clean(segment.get("reserving_class")),
            "method_name": _clean(segment.get("method_name")),
            "factor": segment.get("factor"),
            "status": stale_by_identity.get(_segment_key(segment), SEGMENT_CURRENT),
            "base_triangle_type": _clean(read.get("base_triangle_type")),
            **statistics,
            "problems": problems,
            "error": _clean(read.get("error")),
        })
    return rows


def _run_state(method: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> str:
    results = _results_tab(method)
    if not _clean(results.get("input_revision")):
        return STATE_NOT_RUN
    if _contract_call(run_input_revision, method) != _clean(results.get("input_revision")):
        return STATE_INPUTS_CHANGED
    if any(row.get("status") != SEGMENT_CURRENT for row in rows):
        return STATE_SEGMENT_CHANGED
    return STATE_UP_TO_DATE


def _segment_inputs(project_name: str, method: Mapping[str, Any], reads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The contract's per-segment inputs; a vanished bootstrap is refused by name."""

    inputs: List[Dict[str, Any]] = []
    for segment, read in zip(_segments(method), reads):
        if read.get("bootstrap") is None:
            reason = _clean(read.get("error"))
            raise HTTPException(
                404,
                "Included bootstrap not found: "
                f"{_label(segment.get('reserving_class'), segment.get('method_name'), segment.get('project_name'))}"
                + (f" ({reason})" if reason else "."),
            )
        inputs.append({
            "bootstrap": read["bootstrap"],
            "base_triangle_type": read.get("base_triangle_type") or "",
        })
    return inputs


def _consolidate(project_name: str, method: Mapping[str, Any], reads: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _contract_call(
        consolidate_stochastic_method,
        method,
        _segment_inputs(project_name, method, reads),
        timestamp=_now(),
    )


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def _csv_text(values: Iterable[Any]) -> str:
    return bootstrap_service._csv_text(values)


def _output_files(project_name: str, reserving_class: str, payload: Mapping[str, Any]) -> Dict[str, str]:
    _method_name, output_dataset = _identity(payload)
    data_dir = config.get_project_dataset_cache_dir(project_name, reserving_class)
    safe_name = sanitize_dataset_file_name(output_dataset)
    variants = _contract_call(stochastic_consolidation_output_variants, payload)
    return {
        os.path.join(data_dir, f"{safe_name}@{period_length}.csv"): _csv_text(values)
        for period_length, values in variants.items()
    }


def _output_paths(project_name: str, reserving_class: str, payload: Mapping[str, Any]) -> List[str]:
    _method_name, output_dataset = _identity(payload)
    origin_length = int(_details(payload).get("origin_length") or 12)
    periods = [origin_length]
    periods.extend(
        target for target in (3, 6, 12) if target > origin_length and target % origin_length == 0
    )
    data_dir = config.get_project_dataset_cache_dir(project_name, reserving_class)
    safe_name = sanitize_dataset_file_name(output_dataset)
    return [os.path.join(data_dir, f"{safe_name}@{period}.csv") for period in periods]


def _build_sidecar(
    project_name: str,
    reserving_class: str,
    payload: Mapping[str, Any],
    existing: Mapping[str, Any],
    output_files: Mapping[str, str],
    *,
    notes: str | None,
) -> Dict[str, Any]:
    from app_server.services import calculated_dataset_service

    _method_name, output_dataset = _identity(payload)
    origin_length = int(_details(payload).get("origin_length") or 12)
    primary = next(path for path in output_files if path.endswith(f"@{origin_length}.csv"))
    canonical_existing: Dict[str, Any] = dict(existing)
    if not existing:
        # A new output still inherits the dataset-type graph's dependents: a
        # formula over the output type names this dataset before it exists.
        graph_seed = {
            "dataset_name": output_dataset,
            "dataset_type": _clean(_details(payload).get("output_type")) or output_dataset,
            "project_name": project_name,
            "reserving_class": reserving_class,
            "source_kind": dataset_sidecar_status_service.SCON_SOURCE_KIND,
            "method_type": dataset_sidecar_status_service.METHOD_TYPE_STOCHASTIC_CONSOLIDATION,
            "precedents": stochastic_consolidation_precedents(payload, reserving_class=reserving_class),
            "dependents": [],
        }
        calculated_dataset_service.apply_sidecar_graph_fields(
            graph_seed,
            project_name,
            graph_seed["dataset_type"],
        )
        canonical_existing = graph_seed
    return _contract_call(
        build_stochastic_consolidation_output_sidecar,
        payload,
        project_name=project_name,
        reserving_class=reserving_class,
        csv_file=os.path.basename(primary),
        existing=canonical_existing,
        existing_record=bool(existing),
        dependents=canonical_existing.get("dependents"),
        notes=notes,
        timestamp=_now(),
        user=user_identity_service.get_current_display_name() or getpass.getuser(),
        output_changed=True,
        append_audit=True,
        audit_action="Update" if existing else "Insert",
        status=dataset_sidecar_status_service.STATUS_CURRENT,
    )


def _publish(
    project_name: str,
    reserving_class: str,
    payload: Mapping[str, Any],
    existing_sidecar: Mapping[str, Any],
    *,
    notes: str | None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Write the method JSON and output CSVs, then the sidecar last."""

    method_name, output_dataset = _identity(payload)
    sidecar_path = _sidecar_path(project_name, reserving_class, output_dataset)
    output_files = _output_files(project_name, reserving_class, payload)
    sidecar = _build_sidecar(
        project_name, reserving_class, payload, existing_sidecar, output_files, notes=notes
    )
    files = {_method_path(project_name, reserving_class, method_name): persisted_json_text(payload)}
    files.update(output_files)
    files[sidecar_path] = persisted_json_text(sidecar)
    changed_paths = bootstrap_service._commit_text_files(files, last_paths=[sidecar_path])
    return sidecar, changed_paths


def _precedent_identities(entries: Any) -> set[Tuple[str, str]]:
    return {
        (_key(entry.get("dataset_name")), _key(entry.get("reserving_class")), _key(entry.get("project")))
        for entry in entries or []
        if isinstance(entry, Mapping)
    }


def _validate_pair(
    reserving_class: str,
    requested_method_name: str,
    method: Mapping[str, Any],
    sidecar: Mapping[str, Any],
) -> None:
    method_name, output_dataset = _identity(method)
    if _key(method_name) != _key(requested_method_name):
        raise HTTPException(409, "Stochastic Consolidation method identity does not match the requested method.")
    if _key(sidecar.get("dataset_name")) != _key(output_dataset):
        raise HTTPException(409, "Stochastic Consolidation sidecar identity does not match the method JSON.")
    sidecar_method = _clean(sidecar.get("method_name")) or output_dataset
    if _key(sidecar_method) != _key(method_name):
        raise HTTPException(409, "Stochastic Consolidation sidecar is owned by a different method.")
    if dataset_sidecar_status_service.normalize_method_type(
        sidecar.get("method_type"), sidecar.get("source_kind")
    ) != dataset_sidecar_status_service.METHOD_TYPE_STOCHASTIC_CONSOLIDATION:
        raise HTTPException(409, "Stochastic Consolidation output sidecar does not identify a consolidation output.")
    if _clean(sidecar.get("data_format")).lower() != "vector":
        raise HTTPException(409, "Stochastic Consolidation output sidecar must identify a Vector dataset.")
    if precedent_cache_service.source_period(sidecar) != int(_details(method).get("origin_length") or 0):
        raise HTTPException(409, "Stochastic Consolidation method and output sidecar origin lengths do not match.")
    method_origins = [str(item) for item in publication_projection(method).get("origin_labels", [])]
    sidecar_origins = (
        [str(item) for item in sidecar.get("origin_labels", [])]
        if isinstance(sidecar.get("origin_labels"), list)
        else []
    )
    if sidecar_origins != method_origins:
        raise HTTPException(409, "Stochastic Consolidation method and output sidecar origin labels do not match.")
    expected = _precedent_identities(stochastic_consolidation_precedents(method, reserving_class=reserving_class))
    if expected != _precedent_identities(sidecar.get("precedents")):
        raise HTTPException(409, "Stochastic Consolidation method and output sidecar precedents do not match.")
    if _clean(sidecar.get("publication_revision")) != _revision_response(method)["publication_revision"]:
        raise HTTPException(409, "Stochastic Consolidation method and output sidecar publication revisions do not match.")


def _method_response(
    project_name: str,
    reserving_class: str,
    method: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    rows: List[Dict[str, Any]],
    *,
    changed_paths: Iterable[str] = (),
) -> Dict[str, Any]:
    method_name, output_dataset = _identity(method)
    origin_length = int(_details(method).get("origin_length") or 12)
    output_paths = sorted(_output_paths(project_name, reserving_class, method), key=os.path.normcase)
    return {
        "ok": True,
        "project_name": project_name,
        "reserving_class": reserving_class,
        "method_name": method_name,
        "output_dataset": output_dataset,
        "method": dict(method),
        **_revision_response(method),
        "sidecar": _sidecar_response(sidecar, exists=bool(sidecar)),
        "segments": rows,
        "stale_segments": [
            {key: row[key] for key in ("project_name", "reserving_class", "method_name", "status")}
            for row in rows
            if row.get("status") != SEGMENT_CURRENT
        ],
        "run_state": _run_state(method, rows),
        "changed_paths": sorted(changed_paths, key=os.path.normcase),
        "aggregated_csv_paths": [
            path for path in output_paths if not path.endswith(f"@{origin_length}.csv")
        ],
    }


def _required(project_name: Any, reserving_class: Any) -> Tuple[str, str]:
    project = _clean(project_name)
    reserving = _clean(reserving_class)
    if not project or not reserving:
        raise HTTPException(400, "project_name and reserving_class are required.")
    return project, reserving


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def load_stochastic_consolidation_method(
    project_name: str,
    reserving_class: str,
    method_name: str,
) -> Dict[str, Any]:
    """The method and its sidecar, plus each segment's freshness and figures."""

    project, reserving = _required(project_name, reserving_class)
    name = _clean(method_name)
    if not name:
        raise HTTPException(400, "project_name, reserving_class, and method_name are required.")
    method_path = _method_path(project, reserving, name)
    sidecar_path = _sidecar_path(project, reserving, name)
    with dataset_sidecar_status_service.sidecar_write_lock(sidecar_path):
        method_future = _READ_EXECUTOR.submit(_read_json, method_path)
        sidecar_future = _READ_EXECUTOR.submit(_read_json, sidecar_path)
        method = method_future.result()
        sidecar = sidecar_future.result()
    if not method:
        raise HTTPException(404, f"Stochastic Consolidation method not found: {name}")
    if not sidecar:
        raise HTTPException(409, "Stochastic Consolidation requires both its method JSON and output sidecar.")
    json_format = _clean(method.get("json_format"))
    if json_format != SCON_JSON_FORMAT:
        raise HTTPException(422, f"Unsupported Stochastic Consolidation JSON format: {json_format or '(missing)'}.")
    normalized = _contract_call(normalize_stochastic_consolidation_method, method, require_complete=True)
    _validate_pair(reserving, name, normalized, sidecar)
    rows = _segment_rows(normalized, _read_segments(project, normalized))
    return _method_response(project, reserving, normalized, sidecar, rows)


def consolidate_stochastic_consolidation_method(
    project_name: str,
    reserving_class: str,
    method: Dict[str, Any],
) -> Dict[str, Any]:
    """Run the consolidation a page describes and return it without writing.

    Every segment is re-simulated from its bootstrap's seed, so the result is
    exactly what a save of the same inputs publishes. The run's finest
    percentile ladder comes back beside the method and is never stored.
    """

    project, reserving = _required(project_name, reserving_class)
    incoming = _contract_call(normalize_stochastic_consolidation_method, method, require_complete=True)
    _identity(incoming)
    reads = _read_segments(project, incoming)
    consolidated, ladder = _contract_call(
        consolidate_stochastic_method_with_ladder,
        incoming,
        _segment_inputs(project, incoming, reads),
        timestamp=_now(),
    )
    rows = _segment_rows(consolidated, reads)
    return {**_method_response(project, reserving, consolidated, {}, rows), "finer_ladder": ladder}


def list_stochastic_consolidation_candidates(
    project_name: str,
    reserving_class: str,
    source_project_name: str = "",
) -> Dict[str, Any]:
    """Every Bootstrap the segment picker offers.

    By default those in the project's other reserving classes.  With
    ``source_project_name`` naming another project, every Bootstrap in that
    project, each row carrying the project it comes from.
    """

    project, reserving = _required(project_name, reserving_class)
    source = _clean(source_project_name)
    if _key(source) == _key(project):
        source = ""
    scanned = source or project
    try:
        data_dir = config.get_project_data_dir(scanned)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if source and not os.path.isdir(data_dir):
        raise HTTPException(404, f"Project not found: {source}")
    host = "" if source else _key(reserving)
    classes: List[str] = []
    if os.path.isdir(data_dir):
        classes = [
            config.decode_filename_segment(entry.name)
            for entry in os.scandir(data_dir)
            if entry.is_dir()
        ]
    classes = [name for name in classes if _key(name) != host]

    def _class_bootstraps(class_name: str) -> List[Tuple[str, str]]:
        methods_dir = config.get_project_method_data_dir(scanned, class_name)
        try:
            entries = list(os.scandir(methods_dir))
        except OSError:
            return []
        prefix = dataset_sidecar_status_service.METHOD_JSON_FILENAME_PREFIX_BY_TYPE[
            dataset_sidecar_status_service.METHOD_TYPE_BOOTSTRAP
        ].lower()
        return [
            (class_name, entry.path)
            for entry in entries
            if entry.is_file()
            and entry.name.lower().startswith(prefix)
            and entry.name.lower().endswith(".json")
        ]

    files = [
        item
        for future in [_READ_EXECUTOR.submit(_class_bootstraps, name) for name in classes]
        for item in future.result()
    ]

    def _candidate(class_name: str, path: str) -> Dict[str, Any] | None:
        try:
            payload = _read_json(path)
        except HTTPException:
            return None
        if _clean(payload.get("json_format")) != BST_JSON_FORMAT:
            return None
        name = _clean(_details(payload).get("name"))
        if not name:
            return None
        read = _read_bootstrap(scanned, class_name, name)
        return {
            "project_name": source,
            "reserving_class": class_name,
            "method_name": name,
            "output_type": _clean(_details(payload).get("output_type")),
            "dfm_method": _clean(_details(payload).get("dfm_method")),
            "base_triangle_type": _clean(read.get("base_triangle_type")),
            **_bootstrap_statistics(payload),
        }

    futures = [_READ_EXECUTOR.submit(_candidate, class_name, path) for class_name, path in files]
    candidates = [row for row in (future.result() for future in futures) if row]
    candidates.sort(key=lambda row: (row["reserving_class"].casefold(), row["method_name"].casefold()))
    return {
        "ok": True,
        "project_name": project,
        "reserving_class": reserving,
        "source_project_name": source,
        "candidates": candidates,
    }


def save_stochastic_consolidation_method(
    project_name: str,
    reserving_class: str,
    method: Dict[str, Any],
    *,
    notes: str | None = None,
    expected_owned_revision: str | None = None,
    expected_derived_revision: str | None = None,
) -> Dict[str, Any]:
    """Save a consolidation, consolidating again whenever its stored run is stale.

    The run is re-done when there is none yet, when the run's own inputs
    changed since it, or when any segment's bootstrap changed since it was
    consumed, so a saved consolidation always publishes the result of its
    saved inputs.  A save that changes only notes keeps the stored run.
    """

    project, reserving = _required(project_name, reserving_class)
    # Dependent propagation runs on Arco Engine; refuse before any write when
    # no Engine can take the job or another walk is rewriting this class.
    dependent_propagation_service.require_reserving_class_writable(project, reserving)
    incoming = _contract_call(normalize_stochastic_consolidation_method, method, require_complete=False)
    method_name, output_dataset = _identity(incoming)
    method_path = _method_path(project, reserving, method_name)
    sidecar_path = _sidecar_path(project, reserving, output_dataset)
    with _lock(project, reserving), dataset_sidecar_status_service.sidecar_write_lock(sidecar_path):
        current_future = _READ_EXECUTOR.submit(_read_json, method_path)
        sidecar_future = _READ_EXECUTOR.submit(_read_json, sidecar_path)
        current = current_future.result()
        existing_sidecar = sidecar_future.result()
        if current:
            if _clean(current.get("json_format")) != SCON_JSON_FORMAT:
                raise HTTPException(409, "Stochastic Consolidation changed on disk; reload it before saving.")
            current = _contract_call(normalize_stochastic_consolidation_method, current, require_complete=True)
            if _key(_identity(current)[0]) != _key(method_name):
                raise HTTPException(409, "An existing Stochastic Consolidation cannot change its name during Save.")
            if expected_owned_revision is not None \
                    and _clean(expected_owned_revision) != _revision_response(current)["owned_revision"]:
                raise HTTPException(409, "Stochastic Consolidation settings changed on disk; reload before saving.")
            merged = _contract_call(apply_owned_patch, current, method, timestamp=_now())
        else:
            if expected_owned_revision is not None and _clean(expected_owned_revision):
                raise HTTPException(409, "Stochastic Consolidation was removed on disk; reload before saving.")
            # A first save keeps nothing a client sent as derived state: the
            # owned settings go onto an empty method, so the run starts fresh.
            merged = _contract_call(
                apply_owned_patch, {"json_format": SCON_JSON_FORMAT}, method, timestamp=_now()
            )
        if existing_sidecar:
            owner = _clean(existing_sidecar.get("method_name")) or _clean(existing_sidecar.get("dataset_name"))
            owner_type = dataset_sidecar_status_service.normalize_method_type(
                existing_sidecar.get("method_type"), existing_sidecar.get("source_kind")
            )
            if _key(owner) != _key(method_name) \
                    or owner_type != dataset_sidecar_status_service.METHOD_TYPE_STOCHASTIC_CONSOLIDATION:
                raise HTTPException(
                    409,
                    f"Output dataset '{output_dataset}' is already owned by '{owner}'. "
                    "Choose a unique Stochastic Consolidation name.",
                )
        _contract_call(normalize_stochastic_consolidation_method, merged, require_complete=True)
        reads = _read_segments(project, merged)
        rows = _segment_rows(merged, reads)
        rerun = _run_state(merged, rows) != STATE_UP_TO_DATE
        if rerun:
            refreshed = _consolidate(project, merged, reads)
            rows = _segment_rows(refreshed, reads)
        else:
            refreshed = merged
        published_sidecar, changed_paths = _publish(
            project, reserving, refreshed, existing_sidecar, notes=notes
        )
        response = _method_response(
            project, reserving, refreshed, published_sidecar, rows, changed_paths=changed_paths
        )
    response["consolidated"] = rerun
    response["derived_rebased"] = bool(
        current
        and expected_derived_revision is not None
        and _clean(expected_derived_revision) != _revision_response(current)["derived_revision"]
    )
    response["propagation"] = dependent_propagation_service.enqueue_marked_save_propagation(
        project,
        reserving,
        output_dataset,
        _clean(_details(refreshed).get("output_type")) or output_dataset,
    )
    response["propagation_ok"] = bool(response["propagation"].get("ok"))
    response["calculated_updates"] = response["propagation"]
    response["index_ok"] = bool(response["propagation"].get("index_ok", True))
    response["index_error"] = _clean(response["propagation"].get("index_error"))
    return response


def save_propagation_roots(
    project_name: str,
    reserving_class: str,
    method: Dict[str, Any],
    **_ignored: Any,
) -> List[Tuple[str, str]]:
    """Return the roots ``save_stochastic_consolidation_method`` propagates from.

    Save refuses to rename an existing consolidation, so the incoming
    payload's identity is the one the save publishes.
    """

    incoming = _contract_call(normalize_stochastic_consolidation_method, method, require_complete=False)
    _method_name, output_dataset = _identity(incoming)
    output_type = _clean(_details(incoming).get("output_type")) or output_dataset
    return [(output_dataset, output_type)]
