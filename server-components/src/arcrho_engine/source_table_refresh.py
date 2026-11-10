"""Durable, server-local ArcRho source-table refresh.

The Engine imports a project's source table and then rebuilds everything
derived from it, on the machine where ``E:\\Arco Server`` is a local drive.
A Client PC doing the same work copies the external CSV *through* itself --
read from one share, written to another -- reads the whole master copy back to
count its rows, and then pays one SMB round trip per dataset and per method for
the refresh that follows.

Requests queue under ``requests/source_table_refresh/requests`` and are retained
until a validated terminal status exists. A per-project lease serializes Engine
instances; while the project's classes are being rewritten each one is held
under the *dependent-propagation* reserving-class lease, so a client save into
that class meets the same 423 hold it already understands.

The job runs three stages:

``import``   the canonical ``source_table_service`` writes the master copy.
``caches``   the table summary, reserving-class values and the data-processing
             vocabulary cache are regenerated.
``classes``  every engine-generated dataset instance is regenerated through the
             canonical ``run_arcrho_tri`` path, then one dependent walk per
             reserving class updates the calculated datasets and the methods.

Nothing in here is specific to being the Engine: every step calls the same
canonical ``app_server`` service a Client PC would have called, which is what
keeps one implementation of "the raw data changed".
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_dependent_propagation_contract import (
    DependentPropagationLeaseUnavailable,
    acquire_reserving_class_lease,
    release_reserving_class_lease,
    start_reserving_class_lease_heartbeat,
    stop_reserving_class_lease_heartbeat,
)
from arcrho_engine_calculation_contract import MAX_ENGINE_CALCULATION_WAIT_SECONDS
from arcrho_engine_job_lease import engine_job_lease_is_owned
from arcrho_source_refresh_contract import (
    SOURCE_REFRESH_STATUS_HEARTBEAT_SECONDS,
    SourceRefreshContractError,
    acquire_source_refresh_lease,
    read_source_refresh_status,
    release_source_refresh_lease,
    reserving_class_matches_scope,
    source_refresh_request_path,
    start_source_refresh_lease_heartbeat,
    stop_source_refresh_lease_heartbeat,
    validate_request_id,
    validate_source_refresh_request,
    write_source_refresh_status,
)

# Path redaction and the canonical-runtime bootstrap are owned by the sibling
# durable-job modules; this job reuses them rather than growing second copies.
from arcrho_engine.dependent_propagation import (
    configure_canonical_runtime,
    dependent_refresh_failure_message,
    dependent_refresh_failures,
)
from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_engine.runtime_log import append_runtime_log
from arcrho_api.period_reshape import is_imported_dataset

SOURCE_REFRESH_LOG_FILENAME = "source_table_refresh.log"

# A regeneration nobody is watching may take far longer than the interactive
# grid default (``config.ENGINE_REQUEST_TIMEOUT_SEC``, 15 s). Failing a whole
# project's rebuild because one large triangle needed twenty seconds would be
# the wrong trade, so this job waits the longest the calculation contract
# allows and reports elapsed time per class instead.
DATASET_REGENERATION_TIMEOUT_SECONDS = MAX_ENGINE_CALCULATION_WAIT_SECONDS

# How long one class waits for a competing dependent walk to finish before the
# job gives up on it and moves to the next. The class is then left untouched
# and named in the failure list rather than silently skipped.
RESERVING_CLASS_LEASE_WAIT_SECONDS = 120.0

Progress = dict[str, Any]


def _log(server_root: Any, message: str, *, exc: BaseException | None = None) -> None:
    append_runtime_log(server_root, SOURCE_REFRESH_LOG_FILENAME, message, exc=exc)


class SourceRefreshJobError(RuntimeError):
    """Raised when a source-refresh job cannot run safely."""


class SourceRefreshLeaseLost(SourceRefreshJobError):
    """Raised when another Engine has taken ownership of the project."""


def _progress(stage: str, completed: int, total: int, label: str) -> Progress:
    return {
        "stage": str(stage or "working"),
        "completed": max(0, int(completed)),
        "total": max(0, int(total), int(completed)),
        "label": str(label or stage or "Working"),
    }


def _safe_status_message(exc: BaseException) -> str:
    if isinstance(exc, (SourceRefreshJobError, SourceRefreshContractError)):
        return _redact_machine_paths(exc) or "The source table refresh failed."
    if isinstance(exc, OSError):
        return "The Arco Server filesystem could not complete the source table refresh."
    return "The source table refresh failed."


def _empty_result() -> dict[str, Any]:
    return {
        "source_type": "",
        "imported": False,
        "dependents_refreshed": False,
        "row_count": 0,
        "column_count": 0,
        "classes_total": 0,
        "classes_refreshed": 0,
        "datasets_regenerated": 0,
        "datasets_failed": 0,
        "methods_updated": 0,
        "dataset_types_expanded": [],
        "failures": [],
    }


# ---------------------------------------------------------------------------
# Reserving-class enumeration
# ---------------------------------------------------------------------------


def _reserving_class_paths(project_name: str) -> list[str]:
    """Every reserving class in the project that owns persisted data.

    The folder name is an encoded form of the class path, so the canonical
    spelling is taken from the class's own ``index.json`` when it has one and
    only decoded from the folder name when it does not.
    """

    from app_server import config
    from arcrho_api.dataset_index_contract import INDEX_FILE_NAME

    try:
        data_dir = Path(config.get_project_data_dir(project_name))
    except ValueError as exc:
        raise SourceRefreshJobError(str(exc)) from exc
    try:
        entries = sorted(
            (entry for entry in os.scandir(data_dir) if entry.is_dir()),
            key=lambda entry: (entry.name.casefold(), entry.name),
        )
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise SourceRefreshJobError(
            "The project data folder could not be listed."
        ) from exc

    classes: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        name = ""
        try:
            payload = json.loads(
                Path(entry.path, INDEX_FILE_NAME).read_text(encoding="utf-8-sig")
            )
            if isinstance(payload, Mapping):
                name = str(payload.get("reserving_class") or "").strip()
        except (OSError, ValueError, TypeError):
            name = ""
        if not name:
            name = config.decode_filename_segment(entry.name).strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            classes.append(name)
    return classes


def _expanded_dataset_types(
    project_name: str,
    dataset_types: list[str] | None,
) -> list[str]:
    """The selected types plus the generated formulas the Engine builds from them.

    A type the person importing did not select is still rebuilt when its
    formula reads one that was: the Engine evaluates that formula against the
    source table, so the values it produced before the import are stale too.
    The expansion runs once per job, on types and before any instance is
    looked up, so a type with no instance in a class cannot hide a later
    formula. An empty selection is left empty, because it already means every
    engine dataset.
    """

    if not dataset_types:
        return []
    from app_server.services import calculated_dataset_service

    return calculated_dataset_service.generated_formula_refresh_types(
        project_name, list(dataset_types)
    )


def _engine_dataset_instances(
    project_name: str,
    reserving_class: str,
    dataset_types: list[str] | None = None,
) -> list[str]:
    """Names of the engine-generated dataset instances in one class.

    A calculated dataset is deliberately excluded: the dependent walk owns
    those, and recomputing one here would duplicate the walk's work with a
    different ordering. When the request names dataset types, only instances of
    those types are returned.
    """

    from app_server.services import dataset_instance_index_service

    wanted_types = {str(name).casefold() for name in dataset_types or []}
    index = dataset_instance_index_service.get_index(project_name, reserving_class)
    names: list[str] = []
    seen: set[str] = set()
    for row in index.get("files") or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("source_kind") or "").strip().casefold() != "engine":
            continue
        if wanted_types and (
            str(row.get("dataset_type") or "").strip().casefold() not in wanted_types
        ):
            continue
        # Index rows name the instance "name" (dataset_index_contract
        # INDEX_ROW_FIELDS); "dataset_name" exists only on sidecar payloads.
        name = str(row.get("name") or "").strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def is_imported_dataset_file(project_name: str, reserving_class: str, dataset_name: str) -> bool:
    """``is_imported_dataset`` for an engine-kind dataset on disk (its sidecar).

    A ResQ triangle stored as an engine dataset reads no source column, so the
    Engine cannot rebuild it; a sidecar that cannot be read counts as imported
    for the same reason.
    """

    from app_server.services import dataset_service

    try:
        sidecar = dataset_service._read_dataset_sidecar(
            dataset_service._get_dataset_sidecar_path(project_name, reserving_class, dataset_name)
        )
    except Exception:
        return True
    return bool(sidecar) and not sidecar.get("calculated") and is_imported_dataset(sidecar)


def _regeneration_request(
    sidecar: Mapping[str, Any],
    project_name: str,
) -> tuple[list, str]:
    """Build the canonical engine request for one persisted dataset instance.

    Every shape field comes from the dataset's own sidecar, so the regenerated
    CSV lands on the same cache filename it already occupies instead of
    creating a second variant beside it.

    The project is the one this job is refreshing, never the name the sidecar
    happens to carry. Duplicating or renaming a project copies that field
    verbatim, so a duplicate's sidecars still name the project they were copied
    from; trusting them would send the whole rebuild -- values and sidecar
    writes alike -- into the source project's folders and leave the project
    being refreshed with no cached values at all.
    """

    from app_server.helpers import set_data_path_like_vba

    is_vector = str(sidecar.get("data_format") or "").strip().casefold() == "vector"
    dataset_type = str(sidecar.get("dataset_type") or "").strip()
    instance_name = str(sidecar.get("dataset_name") or "").strip()
    # Display, not stored: this asks the Engine to regenerate the dataset, and
    # the shape it must produce is the one the dataset is shown at. A vector
    # states it under ``period_length`` alone.
    if is_vector:
        origin_length = int(sidecar.get("period_length") or sidecar.get("origin_length") or 0) or 12
        development_length = origin_length
    else:
        origin_length = int(sidecar.get("origin_length") or 0) or 12
        development_length = int(sidecar.get("development_length") or 0) or origin_length
    pairs = [
        ("Function", "ArcRhoVec" if is_vector else "ArcRhoTri"),
        ("Path", str(sidecar.get("reserving_class") or "").strip()),
        ("DatasetName", dataset_type or instance_name),
    ]
    # Sent whenever the sidecar names an instance, exactly as the dataset route
    # builds it: the Engine sees the same request either way only if the pair
    # list matches, and the Engine is what interprets it.
    if instance_name:
        pairs.append(("InstanceName", instance_name))
    pairs.extend(
        [
            ("Cumulative", str(bool(sidecar.get("cumulative", True)))),
            ("Transposed", str(False)),
            ("Calendar", str(bool(sidecar.get("calendar", False)))),
            ("ProjectName", str(project_name or "").strip()),
            ("OriginLength", str(origin_length)),
            ("DevelopmentLength", str(development_length)),
        ]
    )
    return pairs, set_data_path_like_vba(pairs)


def _regenerate_engine_dataset(
    server_root: Any,
    project_name: str,
    reserving_class: str,
    dataset_name: str,
) -> bool:
    """Rebuild one engine dataset from the newly imported table.

    ``run_arcrho_tri`` clears the cached CSV before it asks the Engine for a
    new one, so a failed calculation would otherwise leave the dataset with no
    values at all. A whole-project rebuild must not be able to empty a dataset
    it merely failed to refresh, so the old CSV is held aside and restored when
    the run does not succeed.
    """

    from app_server.services import arcrho_runtime_service, dataset_service

    sidecar = dataset_service.load_dataset_sidecar(
        project_name, reserving_class, dataset_name
    )
    if not sidecar.get("exists"):
        raise SourceRefreshJobError(f"{dataset_name}: no dataset metadata to refresh.")
    pairs, data_path = _regeneration_request(sidecar, project_name)
    if not data_path:
        raise SourceRefreshJobError(f"{dataset_name}: the cache path is unresolved.")

    backup_path = f"{data_path}.refresh-backup"
    held = False
    try:
        shutil.copyfile(data_path, backup_path)
        held = True
    except OSError:
        held = False

    try:
        outcome = arcrho_runtime_service.run_arcrho_tri(
            pairs,
            data_path,
            timeout_sec=DATASET_REGENERATION_TIMEOUT_SECONDS,
            force_refresh=True,
            write_sidecar=True,
            recalculate_dependents_on_cache_write=False,
            # The class index is rebuilt once by the dependent walk that
            # follows, not after each dataset in the batch.
            refresh_index=False,
        )
    except BaseException:
        if held:
            _restore_dataset_cache(backup_path, data_path)
        raise
    if not outcome.get("ok"):
        if held:
            _restore_dataset_cache(backup_path, data_path)
        raise SourceRefreshJobError(
            f"{dataset_name}: "
            + str(outcome.get("message") or "the Arco Engine did not return values.")
        )
    _discard_dataset_backup(backup_path)
    _log(
        server_root,
        f"regenerated {reserving_class}/{dataset_name}"
        f" (engine_request={bool(outcome.get('need_request'))})",
    )
    return True


def _restore_dataset_cache(backup_path: str, data_path: str) -> None:
    try:
        os.replace(backup_path, data_path)
    except OSError:
        _discard_dataset_backup(backup_path)


def _discard_dataset_backup(backup_path: str) -> None:
    try:
        os.remove(backup_path)
    except OSError:
        pass


def _method_update_count(result: Mapping[str, Any]) -> int:
    """Count the methods a dependent walk actually re-saved.

    Every method wave reports its re-saved methods under ``updated``
    (status-only touches sit apart under ``status_refreshed``), so that is
    the bucket the job's ``methods_updated`` figure reads.
    """

    total = 0
    for bucket in (
        "dfm_updates",
        "result_selection_updates",
        "berquist_sherman_updates",
        "bornhuetter_ferguson_updates",
        "cape_cod_updates",
        "bootstrap_updates",
    ):
        updates = result.get(bucket)
        if isinstance(updates, Mapping):
            total += len(updates.get("updated") or [])
    return total


def _refresh_one_reserving_class(
    server_root: Path,
    project_name: str,
    reserving_class: str,
    result: dict[str, Any],
    *,
    on_dataset: Callable[[str], None],
    dataset_types: list[str] | None = None,
    prepare: Callable[[], tuple[list[str], set[str]]] | None = None,
    expected_failures: Callable[[Mapping[str, Any], list[tuple[str, str]]], set[str]] | None = None,
) -> None:
    """Regenerate one class's engine datasets, then walk its dependents.

    The class is held under the dependent-propagation reserving-class lease for
    the whole step, so a client save into it is refused with the hold it already
    handles rather than racing the rewrite. ``dataset_types`` limits the
    regeneration to those types; the dependent walk that follows still starts
    from whatever was regenerated. ``prepare`` runs under the same lease before
    anything is regenerated and returns ``(roots, kept)``: more datasets to
    walk from (the project dates job reshapes hand-entered datasets and methods
    there), and the casefolded names of engine datasets it owns that must not
    be regenerated (ResQ triangles stored as engine kind, whether reshaped now
    or on an earlier run). Neither is regenerated.
    ``expected_failures`` gets the walk and its ``(name, line)`` failures and
    returns the names the caller expects to fail; their lines go to
    ``result["expected_problems"]`` instead of the problems and failures.
    """

    from app_server.services import calculated_dataset_service

    deadline = time.monotonic() + RESERVING_CLASS_LEASE_WAIT_SECONDS
    lease = acquire_reserving_class_lease(server_root, project_name, reserving_class)
    while lease is None:
        if time.monotonic() >= deadline:
            raise DependentPropagationLeaseUnavailable(
                f"{reserving_class}: another dependent propagation is still running."
            )
        time.sleep(1.0)
        lease = acquire_reserving_class_lease(server_root, project_name, reserving_class)

    heartbeat_stop, heartbeat_thread = start_reserving_class_lease_heartbeat(lease)
    try:
        prepared: list[str] = []
        kept: set[str] = set()
        if prepare is not None:
            roots_from_prepare, kept_from_prepare = prepare()
            prepared = list(roots_from_prepare or [])
            kept = {str(name).casefold() for name in kept_from_prepare or ()}
        regenerated: list[str] = []
        prepared_keys = {name.casefold() for name in prepared} | kept
        for dataset_name in _engine_dataset_instances(
            project_name, reserving_class, dataset_types
        ):
            if dataset_name.casefold() in prepared_keys or is_imported_dataset_file(
                project_name, reserving_class, dataset_name
            ):
                # Already rewritten by ``prepare`` (walked from below), or a
                # stored dataset the Engine cannot rebuild from its source.
                continue
            on_dataset(dataset_name)
            try:
                _regenerate_engine_dataset(
                    server_root, project_name, reserving_class, dataset_name
                )
            except Exception as exc:
                result["datasets_failed"] += 1
                result["failures"].append(
                    f"{reserving_class}: {_redact_machine_paths(exc)}"
                )
                _log(
                    server_root,
                    f"{reserving_class}/{dataset_name} regeneration failed",
                    exc=exc,
                )
                continue
            regenerated.append(dataset_name)
            result["datasets_regenerated"] += 1

        roots = regenerated + [
            name
            for name in prepared
            if name.casefold() not in {item.casefold() for item in regenerated}
        ]
        if not roots:
            # Nothing changed here, so there is no root to walk from. The
            # class still counts as visited.
            return
        first, *rest = roots
        walk = calculated_dataset_service.recalculate_dependents(
            project_name,
            reserving_class,
            first,
            "",
            additional_roots=[(name, "") for name in rest],
            rebuild_index=True,
        )
        result["methods_updated"] += _method_update_count(walk)
        if not walk.get("ok"):
            # The walk names each dependent that declined; the first reason
            # becomes the job message and every one of them goes to the log,
            # which is where a "reported errors" line used to end the trail.
            failures = dependent_refresh_failures(walk)
            expected = expected_failures(walk, failures) if expected_failures and failures else set()
            reasons: list[str] = []
            expected_lines: list[str] = []
            for name, line in failures:
                target = expected_lines if name in expected else reasons
                if line not in target:
                    target.append(line)
            if expected_lines:
                result.setdefault("expected_problems", []).extend(
                    f"{reserving_class}: {line}" for line in expected_lines
                )
                _log(
                    server_root,
                    f"{reserving_class} dependent refresh expected problems: "
                    + " | ".join(expected_lines),
                )
            if failures and not reasons:
                return
            # A caller that lists each declined dependent for review (the
            # project dates job) keeps every reason, not just the first.
            if isinstance(result.get("dependent_problems"), list):
                result["dependent_problems"].extend(
                    f"{reserving_class}: {reason}" for reason in reasons
                )
            result["failures"].append(
                dependent_refresh_failure_message(reserving_class, reasons)
            )
            _log(
                server_root,
                f"{reserving_class} dependent refresh reported errors: "
                + (" | ".join(reasons) if reasons else "no reason recorded"),
            )
    finally:
        stop_reserving_class_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        release_reserving_class_lease(lease)


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


def execute_source_refresh(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    progress_callback: Callable[[Progress], None] | None = None,
) -> dict[str, Any]:
    """Run one validated source-refresh request and return its result summary."""

    normalized = validate_source_refresh_request(request)
    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    configure_canonical_runtime(root)

    from app_server.services import (
        arcrho_runtime_service,
        data_processing_values_service,
        source_table_service,
        table_summary_service,
        user_identity_service,
    )

    project_name = normalized["ProjectName"]
    result = _empty_result()
    result["dependents_refreshed"] = normalized["RefreshDependents"]
    started = time.monotonic()
    _log(
        root,
        f"{normalized['RequestId']} start project={project_name!r} "
        f"import={normalized['Import']} dependents={normalized['RefreshDependents']} "
        f"dataset_types={len(normalized.get('DatasetTypes') or []) or 'all'} "
        f"class_types={len(normalized.get('ReservingClassTypes') or []) or 'all'}",
    )

    def notify(stage: str, completed: int, total: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback(_progress(stage, completed, total, label))

    # The job re-saves datasets, sidecars and method payloads: act as the user
    # who asked for the refresh so every stamp names them and not this service.
    dataset_types = list(normalized.get("DatasetTypes") or [])
    reserving_class_types = list(normalized.get("ReservingClassTypes") or [])

    with user_identity_service.acting_identity(normalized["UserName"]):
        # One expansion for the whole job. The user's selection travels on in
        # the request and the recorded scope exactly as it was chosen; this
        # derived set is what the classes are rebuilt from, and it is reported
        # so a status can say what was selected and what was rebuilt.
        expanded_types = _expanded_dataset_types(project_name, dataset_types)
        result["dataset_types_expanded"] = list(expanded_types)
        if dataset_types:
            _log(
                root,
                "dataset types selected=" + ", ".join(dataset_types)
                + " rebuilt=" + ", ".join(expanded_types),
            )
        classes = [
            reserving_class
            for reserving_class in (
                _reserving_class_paths(project_name)
                if normalized["RefreshDependents"]
                else []
            )
            if reserving_class_matches_scope(reserving_class, reserving_class_types)
        ]
        result["classes_total"] = len(classes)
        # One unit for the import, one for the derived caches, then one per
        # reserving class, so the bar means the same thing on every project.
        total_units = 2 + len(classes)
        completed_units = 0

        notify("import", completed_units, total_units, "Importing the source table")
        if normalized["Import"]:
            state = source_table_service.get_source_table_state(project_name)
            if str(state.get("source_type") or "") == "mssql":
                status = source_table_service.import_from_mssql(project_name)
            else:
                status = source_table_service.ensure_master_table(
                    project_name, force=normalized["Force"]
                )
            result["imported"] = True
            last_import = status.get("last_import")
            if isinstance(last_import, Mapping):
                result["source_type"] = str(last_import.get("source_type") or "")
                result["row_count"] = int(last_import.get("row_count") or 0)
                result["column_count"] = int(last_import.get("column_count") or 0)
        else:
            record = source_table_service.get_source_table_state(project_name)
            result["source_type"] = str(record.get("source_type") or "")
        if normalized["RefreshDependents"]:
            # Shared with every user of the project: the next Import Scope
            # step opens on what this refresh covered.
            source_table_service.record_refresh_scope(
                project_name, dataset_types, reserving_class_types
            )
        completed_units += 1

        notify(
            "caches",
            completed_units,
            total_units,
            "Rebuilding the table summary and reserving classes",
        )
        summary = table_summary_service.refresh_table_summary(
            project_name,
            refresh_reserving=True,
            import_source=False,
        )
        if not result["row_count"]:
            result["row_count"] = int(summary.get("row_count") or 0)
        # The Data Processing Rules page reads this cache and never writes it,
        # so the job that changed the table rebuilds it.
        try:
            data_processing_values_service.get_data_processing_values(project_name)
        except Exception as exc:
            result["failures"].append(
                "The data-processing value list could not be rebuilt: "
                f"{_redact_machine_paths(exc)}"
            )
            _log(root, "data-processing values rebuild failed", exc=exc)
        # Origin and development header labels are derived from the table that
        # just changed, so their cache is no longer describing it. Datasets
        # regenerated below rebuild it from the new data on first use.
        try:
            arcrho_runtime_service.clear_arcrho_headers_cache(project_name)
        except Exception as exc:
            result["failures"].append(
                f"The header cache could not be cleared: {_redact_machine_paths(exc)}"
            )
            _log(root, "header cache clear failed", exc=exc)
        completed_units += 1

        for index, reserving_class in enumerate(classes, start=1):
            def on_dataset(dataset_name: str, _class=reserving_class) -> None:
                notify(
                    "classes",
                    completed_units,
                    total_units,
                    f"Refreshing {_class}: {dataset_name}",
                )

            notify(
                "classes",
                completed_units,
                total_units,
                f"Refreshing {reserving_class} ({index} of {len(classes)})",
            )
            class_started = time.monotonic()
            try:
                _refresh_one_reserving_class(
                    root,
                    project_name,
                    reserving_class,
                    result,
                    on_dataset=on_dataset,
                    dataset_types=expanded_types,
                )
                result["classes_refreshed"] += 1
            except DependentPropagationLeaseUnavailable as exc:
                result["failures"].append(_redact_machine_paths(exc))
                _log(root, f"{reserving_class} skipped: {exc}")
            except Exception as exc:
                result["failures"].append(
                    f"{reserving_class}: {_redact_machine_paths(exc)}"
                )
                _log(root, f"{reserving_class} refresh failed", exc=exc)
            finally:
                completed_units += 1
                _log(
                    root,
                    f"{reserving_class} took {time.monotonic() - class_started:.2f}s",
                )

        notify("complete", total_units, total_units, "Source table refresh complete")

    _log(
        root,
        f"{normalized['RequestId']} done in {time.monotonic() - started:.2f}s "
        f"classes={result['classes_refreshed']}/{result['classes_total']} "
        f"datasets={result['datasets_regenerated']} "
        f"failed={result['datasets_failed']}",
    )
    return result


def _summarize_failures(result: Mapping[str, Any]) -> str:
    """One sentence naming how much of the refresh did not complete."""

    failures = list(result.get("failures") or [])
    counts = []
    if int(result.get("datasets_failed") or 0):
        counts.append(f"{int(result['datasets_failed'])} dataset(s) failed")
    unfinished = int(result.get("classes_total") or 0) - int(
        result.get("classes_refreshed") or 0
    )
    if unfinished > 0:
        counts.append(f"{unfinished} reserving class(es) were not refreshed")
    head = "; ".join(counts) if counts else "The refresh reported problems"
    return f"{head}. First problem: {failures[0]}" if failures else f"{head}."


def _require_lease(lease) -> None:
    if lease.heartbeat_failed.is_set() or not engine_job_lease_is_owned(lease):
        raise SourceRefreshLeaseLost("Source refresh project ownership was lost.")


def _terminal_status_or_none(
    server_root: Path, request_id: str
) -> dict[str, Any] | None:
    try:
        status = read_source_refresh_status(server_root, request_id)
    except (OSError, ValueError, TypeError, SourceRefreshContractError):
        return None
    if status is not None and status["status"] in {"success", "error"}:
        return status
    return None


def _remove_request_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"(source refresh queue cleanup error: {exc})")


def process_durable_source_refresh_request(
    server_root: str | os.PathLike[str],
    request_file: str | os.PathLike[str],
    request: Mapping[str, Any],
) -> bool:
    """Process one retained queue file under the per-project lease."""

    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    request_path = Path(os.fspath(request_file))
    raw_request_id = request.get("RequestId") if isinstance(request, Mapping) else None
    try:
        request_id = validate_request_id(raw_request_id)
    except SourceRefreshContractError as exc:
        # A request without a safe id can never publish status; drop it so the
        # queue rescan does not reprocess it forever.
        print(f"(source refresh request error: {_safe_status_message(exc)})")
        _remove_request_file(request_path)
        return False

    expected_path = source_refresh_request_path(root, request_id)
    try:
        if request_path.resolve(strict=False) != expected_path.resolve(strict=False):
            print("(source refresh request filename does not match RequestId)")
            return False
    except OSError:
        return False

    terminal = _terminal_status_or_none(root, request_id)
    if terminal is not None:
        _remove_request_file(request_path)
        return terminal["status"] == "success"

    try:
        normalized = validate_source_refresh_request(request)
    except SourceRefreshContractError as exc:
        message = _safe_status_message(exc)
        try:
            write_source_refresh_status(
                root,
                request_id,
                "error",
                progress=_progress("rejected", 0, 0, "Source refresh request rejected"),
                message=message,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish rejected source refresh status: "
                f"{_redact_machine_paths(status_exc)})"
            )
            return False
        print(f"(source refresh request error: {message})")
        _remove_request_file(request_path)
        return False

    lease = acquire_source_refresh_lease(root, normalized["ProjectName"])
    if lease is None:
        _log(root, f"{request_id} claim missed (project busy)")
        return False
    claimed_at = time.monotonic()
    heartbeat_stop, heartbeat_thread = start_source_refresh_lease_heartbeat(lease)
    try:
        # One lock serializes every status write: job progress and the status
        # heartbeat below republish the same file, and a stale heartbeat write
        # must never land after a newer progress write.
        status_write_lock = threading.Lock()
        current_progress = _progress("starting", 0, 0, "Preparing the source refresh")

        def publish(
            status: str,
            progress: Progress,
            *,
            message: str = "",
            result: Mapping[str, Any] | None = None,
        ) -> None:
            _require_lease(lease)
            with status_write_lock:
                write_source_refresh_status(
                    root,
                    request_id,
                    status,
                    progress=progress,
                    message=message,
                    result=result,
                )

        def publish_progress(progress: Progress) -> None:
            nonlocal current_progress
            current_progress = progress
            publish("processing", progress)

        # Remote pollers treat a status whose updated_at stops moving as an
        # abandoned job, so republish the current progress on the contract
        # heartbeat cadence even while one slow step is still running.
        heartbeat_stop_event = threading.Event()

        def status_heartbeat_loop() -> None:
            while not heartbeat_stop_event.wait(
                SOURCE_REFRESH_STATUS_HEARTBEAT_SECONDS
            ):
                try:
                    publish("processing", current_progress)
                except Exception:
                    # Lease loss or filesystem trouble ends the heartbeat; the
                    # job thread surfaces the same condition on its next write.
                    return

        status_heartbeat_thread = threading.Thread(
            target=status_heartbeat_loop,
            name=f"arcrho-source-refresh-status-{request_id[:8]}",
            daemon=True,
        )

        terminal_result: dict[str, Any] | None = None
        try:
            publish("processing", current_progress)
            status_heartbeat_thread.start()
            try:
                terminal_result = execute_source_refresh(
                    root, normalized, progress_callback=publish_progress
                )
            finally:
                heartbeat_stop_event.set()
                status_heartbeat_thread.join(
                    timeout=SOURCE_REFRESH_STATUS_HEARTBEAT_SECONDS * 2
                )
            failures = list(terminal_result.get("failures") or [])
            # A partially failed refresh is reported as an error on purpose:
            # the datasets that did not rebuild still hold values from the
            # previous table, and nothing else would tell the user that.
            terminal_state = "error" if failures else "success"
            terminal_message = _summarize_failures(terminal_result) if failures else ""
            terminal_progress = _progress(
                "complete",
                current_progress["total"],
                current_progress["total"],
                "Source table refresh complete",
            )
        except SourceRefreshLeaseLost:
            _log(root, f"{request_id} project ownership was lost")
            return False
        except Exception as exc:
            terminal_state = "error"
            terminal_message = _safe_status_message(exc)
            terminal_progress = current_progress
            # The status message is redacted for the client; the log keeps the
            # real exception and its traceback.
            _log(root, f"{request_id} raised: {terminal_message}", exc=exc)

        _log(
            root,
            f"{request_id} {terminal_state} after {time.monotonic() - claimed_at:.2f}s"
            + (f": {terminal_message}" if terminal_message else ""),
        )
        try:
            publish(
                terminal_state,
                terminal_progress,
                message=terminal_message,
                result=terminal_result,
            )
        except Exception as status_exc:
            _log(
                root,
                "could not publish source refresh status: "
                f"{_redact_machine_paths(status_exc)}",
                exc=status_exc,
            )
            return False
        if _terminal_status_or_none(root, request_id) is not None:
            _remove_request_file(request_path)
        return terminal_state == "success"
    except SourceRefreshLeaseLost:
        return False
    finally:
        stop_source_refresh_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        release_source_refresh_lease(lease)
