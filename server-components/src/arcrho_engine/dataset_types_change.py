"""Durable, server-local ArcRho dataset-type change.

A project's dataset-type table defines what every dataset instance in that
project is, which of them are calculated, and what each formula refers to. The
Engine applies a change to it on the machine where ``E:\\Arco Server`` is a
local drive, because rebuilding what the change re-derives means visiting every
sidecar of every reserving class -- one SMB round trip each from a Client PC,
inside a request the user is waiting on.

Requests queue under ``requests/dataset_types_change/requests`` and are retained
until a validated terminal status exists. Unlike a source refresh, this job
takes the *project-scope* propagation lease rather than a per-class one: the
table it rewrites belongs to no single reserving class. The whole project is
held only while the plan is confirmed and the table written; the lease is then
narrowed to the reserving classes the plan named, and every other class of the
project is writable again while those are rebuilt.

The job runs three stages:

``plan``    the canonical ``dataset_types_plan_service`` recomputes, from each
            class's index, which reserving classes the change reaches, and
            the job refuses to continue unless that matches the plan the user
            confirmed -- an edit made while the dialog was open must be
            reviewed, not silently absorbed into a wider lock.
``table``   the canonical ``dataset_types_service`` validates the submitted
            rows, resolves each row's Source/Generated, and writes the JSON and
            its XLSX companion.
``graphs``  the canonical ``calculated_dataset_service`` rewrites the sidecars
            the plan named -- a renamed type's instances take its new name --
            re-derives their precedents/dependents from the new table,
            recalculates the calculated datasets whose formula or kind
            changed, and walks each affected reserving class's dependents.

Nothing in here is specific to being the Engine: every step calls the same
canonical ``app_server`` service a Client PC would have called, which is what
keeps one implementation of "the dataset type table changed".
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_dataset_types_change_contract import (
    DATASET_TYPES_CHANGE_STATUS_HEARTBEAT_SECONDS,
    DatasetTypesChangeContractError,
    dataset_types_change_request_path,
    plans_match,
    read_dataset_types_change_status,
    validate_dataset_types_change_request,
    validate_request_id,
    write_dataset_types_change_status,
)
from arcrho_dependent_propagation_contract import (
    acquire_project_scope_lease,
    find_any_reserving_class_propagation_hold,
    narrow_project_scope_lease,
    release_project_scope_lease,
    start_project_scope_lease_heartbeat,
    stop_project_scope_lease_heartbeat,
)
from arcrho_engine_job_lease import engine_job_lease_is_owned

# Path redaction and the canonical-runtime bootstrap are owned by the sibling
# durable-job modules; this job reuses them rather than growing second copies.
from arcrho_engine.dependent_propagation import (
    configure_canonical_runtime,
    dependent_refresh_failure_message,
    dependent_refresh_failure_reasons,
)
from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_engine.runtime_log import append_runtime_log

DATASET_TYPES_CHANGE_LOG_FILENAME = "dataset_types_change.log"

# How long the job waits for a reserving-class walk that was already running
# when the request was submitted. The client preflighted the whole project, so
# this window only covers the gap between that preflight and the moment this
# lease was claimed; a class still busy after it means something else owns the
# project's data and the change must not proceed.
RESERVING_CLASS_QUIET_WAIT_SECONDS = 120.0

# Writing the table is one unit; the rebuild that follows contributes one unit
# per dataset instance it visits and one more per reserving class it revisits,
# so the caller's bar measures work rather than stages. The rebuild's own total
# is not known until the plan has been recomputed, which is why the count
# below starts at one and grows.
_TABLE_UNIT = 1

PLAN_CHANGED_MESSAGE = (
    "The project changed since you reviewed this change, so the reserving "
    "classes it affects are no longer the ones you confirmed. Nothing was "
    "saved. Review the change again."
)

Progress = dict[str, Any]


def _log(server_root: Any, message: str, *, exc: BaseException | None = None) -> None:
    append_runtime_log(server_root, DATASET_TYPES_CHANGE_LOG_FILENAME, message, exc=exc)


class DatasetTypesChangeJobError(RuntimeError):
    """Raised when a dataset-type change job cannot run safely."""


class DatasetTypesChangeLeaseLost(DatasetTypesChangeJobError):
    """Raised when another Engine has taken ownership of the project."""


def _progress(stage: str, completed: int, total: int, label: str) -> Progress:
    return {
        "stage": str(stage or "working"),
        "completed": max(0, int(completed)),
        "total": max(0, int(total), int(completed)),
        "label": str(label or stage or "Working"),
    }


def _safe_status_message(exc: BaseException) -> str:
    if isinstance(exc, (DatasetTypesChangeJobError, DatasetTypesChangeContractError)):
        return _redact_machine_paths(exc) or "The dataset type change failed."
    if isinstance(exc, OSError):
        return (
            "The Arco Server filesystem could not complete the dataset type change."
        )
    # A service refusal (an unresolved formula component, an unavailable
    # dataset-type document) carries the sentence the user needs; it is a
    # message this Engine composed, not a path.
    detail = getattr(exc, "detail", None)
    if isinstance(detail, str) and detail.strip():
        return _redact_machine_paths(detail)
    return "The dataset type change failed."


def _empty_result() -> dict[str, Any]:
    return {
        "rows_written": 0,
        "types_changed": 0,
        "datasets_total": 0,
        "datasets_updated": 0,
        "datasets_renamed": 0,
        "classes_total": 0,
        "classes_affected": 0,
        "classes_walked": 0,
        "datasets_recalculated": 0,
        "failures": [],
    }


def _require_quiet_project(server_root: Path, project_name: str) -> None:
    """Refuse to start while a reserving-class walk is still running.

    The submitting client preflighted the project, but its lease did not exist
    yet: a walk claimed in that gap would be rewriting the same sidecars this
    job is about to re-derive. Waiting is worth more than failing here, because
    the client is already showing a running job.
    """

    deadline = time.monotonic() + RESERVING_CLASS_QUIET_WAIT_SECONDS
    while True:
        hold = find_any_reserving_class_propagation_hold(server_root, project_name)
        if hold is None:
            return
        if time.monotonic() >= deadline:
            reserving_class = str(hold.get("reserving_class") or "").strip()
            named = f" for '{reserving_class}'" if reserving_class else ""
            raise DatasetTypesChangeJobError(
                f"Dependent updates are still running{named}. "
                "The dataset type table was not changed."
            )
        time.sleep(1.0)


_MAX_LISTED_BLOCKERS = 6


def _describe_removal_blockers(blocked: list) -> str:
    """One refusal naming the types that cannot go and what still reads them.

    The client shows this as the job's failure, so it has to be readable on its
    own: the reader needs to know which input to clear, and where.
    """

    lines: list[str] = []
    for entry in blocked:
        dataset_type = str(entry.get("dataset_type") or "").strip() or "A dataset type"
        for instance in list(entry.get("instances") or [])[:_MAX_LISTED_BLOCKERS]:
            readers = ", ".join(
                f"{str(dependent.get('dataset_name') or '').strip()}"
                + (
                    f" ({str(dependent.get('method_type') or '').strip()})"
                    if str(dependent.get("method_type") or "").strip()
                    else ""
                )
                for dependent in list(instance.get("dependents") or [])[:_MAX_LISTED_BLOCKERS]
            )
            lines.append(
                f"{dataset_type} / {str(instance.get('dataset_name') or '').strip()}"
                f" in {str(instance.get('reserving_class') or '').strip()} is read by {readers}"
            )
    listed = "; ".join(lines[:_MAX_LISTED_BLOCKERS])
    more = len(lines) - _MAX_LISTED_BLOCKERS
    suffix = f" (+{more} more)" if more > 0 else ""
    return (
        "These dataset types are still in use and were not removed: "
        f"{listed}{suffix}. Open each dependent listed and clear this input "
        "there, then change the dataset types again. Nothing was saved."
    )


def execute_dataset_types_change(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    progress_callback: Callable[[Progress], None] | None = None,
    narrow_lease: Callable[[list[str]], None] | None = None,
) -> dict[str, Any]:
    """Run one validated dataset-type change and return its result summary.

    ``narrow_lease`` is called with the affected reserving classes once the
    table is written, so the caller holding the project-scope lease can let
    every other class go while the rebuild runs.
    """

    normalized = validate_dataset_types_change_request(request)
    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    configure_canonical_runtime(root)

    from app_server.services import (
        calculated_dataset_service,
        dataset_types_plan_service,
        dataset_types_service,
        user_identity_service,
    )
    from app_server.services.audit_service import safe_append_project_audit_log

    project_name = normalized["ProjectName"]
    result = _empty_result()
    started = time.monotonic()
    _log(
        root,
        f"{normalized['RequestId']} start project={project_name!r} "
        f"rows={len(normalized['Rows'])} renames={len(normalized['Renames'])} "
        f"classes={len(normalized['Plan']['affected'])}",
    )

    def notify(stage: str, completed: int, total: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback(_progress(stage, completed, total, label))

    _require_quiet_project(root, project_name)

    # The plan the user confirmed was built without a lock. Recompute it now,
    # under the lease, and refuse if the project moved on: the classes about
    # to be held must be exactly the ones the user agreed to.
    notify("scanning", 0, 1, "Checking the reserving classes this change affects")
    planned = dataset_types_plan_service.plan_dataset_types_change(
        project_name,
        normalized["Rows"],
        normalized["Renames"],
        on_progress=lambda scanned, total, reserving_class: notify(
            "scanning", scanned, total, f"Checking reserving classes: {reserving_class}"
        ),
    )
    if not plans_match(normalized["Plan"], planned.plan):
        raise DatasetTypesChangeJobError(PLAN_CHANGED_MESSAGE)
    result["types_changed"] = len(planned.changed_types)

    # A dataset type may only go once nothing reads its instances, so those
    # instances are checked before anything is written: a refusal here leaves
    # the table exactly as it was.
    if planned.removed_types:
        notify("scanning", 0, 1, "Checking whether the removed types are in use")
        blocked = calculated_dataset_service.find_dataset_type_removal_blockers(
            project_name, planned
        )
        if blocked:
            raise DatasetTypesChangeJobError(_describe_removal_blockers(blocked))

    affected_classes = [affected.reserving_class for affected in planned.classes]

    # The job writes the table and re-saves sidecars: act as the user who asked
    # for the change so every stamp names them and not this service.
    with user_identity_service.acting_identity(normalized["UserName"]):
        notify("table", 0, _TABLE_UNIT, "Writing the dataset type table")
        written = dataset_types_service.apply_dataset_types_rows(
            project_name, planned.rows
        )
        result["rows_written"] = int(written.get("count") or 0)
        safe_append_project_audit_log(
            project_name=project_name,
            action=f"Saved Dataset Types ({result['rows_written']} rows)",
        )

        # The table is the new one, so a class the plan did not name can only
        # gain instances of the new names from here on: let it go.
        if narrow_lease is not None:
            narrow_lease(affected_classes)

        notify("graphs", _TABLE_UNIT, _TABLE_UNIT, "Rebuilding dataset dependency graphs")

        def on_rebuild_progress(stage: str, label: str, completed: int, total: int) -> None:
            # The table's own unit stays ahead of the rebuild's count, so the
            # bar never moves backwards when the rebuild learns its total.
            notify(stage, _TABLE_UNIT + completed, _TABLE_UNIT + total, label)

        refresh = calculated_dataset_service.apply_planned_dataset_types_change(
            project_name,
            planned,
            on_progress=on_rebuild_progress,
        )

    result["datasets_updated"] = int(refresh.get("sidecars_updated") or 0)
    result["datasets_renamed"] = int(refresh.get("datasets_renamed") or 0)
    result["datasets_total"] = int(refresh.get("datasets_total") or 0)
    result["classes_total"] = int(refresh.get("classes_total") or 0)
    result["classes_affected"] = len(affected_classes)
    chains = list(refresh.get("chains") or [])
    result["classes_walked"] = sum(1 for chain in chains if chain.get("ok"))
    result["datasets_recalculated"] = sum(
        len(chain.get("updated") or []) for chain in chains
    )
    for error in refresh.get("errors") or []:
        result["failures"].append(_redact_machine_paths(str(error)))
    for chain in chains:
        if chain.get("ok"):
            continue
        reserving_class = str(chain.get("reserving_class") or "").strip()
        reasons = dependent_refresh_failure_reasons(chain)
        propagation = chain.get("propagation")
        if isinstance(propagation, Mapping) and not propagation.get("ok", True):
            text = str(propagation.get("message") or propagation.get("reason") or "").strip()
            if text:
                reasons.append(f"dependent propagation: {_redact_machine_paths(text)}")
        result["failures"].append(
            dependent_refresh_failure_message(reserving_class, reasons)
        )
        _log(
            root,
            f"{reserving_class or 'A class'} dependent refresh reported errors: "
            + (" | ".join(reasons) if reasons else "no reason recorded"),
        )

    finished_units = _TABLE_UNIT + result["datasets_total"] + len(chains)
    notify("complete", finished_units, finished_units, "Dataset type change complete")
    _log(
        root,
        f"{normalized['RequestId']} done in {time.monotonic() - started:.2f}s "
        f"rows={result['rows_written']} datasets={result['datasets_updated']} "
        f"renamed={result['datasets_renamed']} "
        f"classes={len(affected_classes)}/{result['classes_total']} "
        f"failed={len(result['failures'])}",
    )
    return result


def _summarize_failures(result: Mapping[str, Any]) -> str:
    """One sentence naming how much of the rebuild did not complete."""

    failures = list(result.get("failures") or [])
    if not failures:
        return ""
    head = failures[0]
    if len(failures) == 1:
        return (
            "The dataset type table was saved, but part of the rebuild failed: "
            f"{head}"
        )
    return (
        "The dataset type table was saved, but "
        f"{len(failures)} parts of the rebuild failed. First: {head}"
    )


def _require_lease(lease) -> None:
    if lease.heartbeat_failed.is_set() or not engine_job_lease_is_owned(lease):
        raise DatasetTypesChangeLeaseLost(
            "Dataset type change project ownership was lost."
        )


def _terminal_status_or_none(
    server_root: Path, request_id: str
) -> dict[str, Any] | None:
    try:
        status = read_dataset_types_change_status(server_root, request_id)
    except (OSError, ValueError, TypeError, DatasetTypesChangeContractError):
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
        print(f"(dataset types change queue cleanup error: {exc})")


def process_durable_dataset_types_change_request(
    server_root: str | os.PathLike[str],
    request_file: str | os.PathLike[str],
    request: Mapping[str, Any],
) -> bool:
    """Process one retained queue file under the project-scope lease."""

    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    request_path = Path(os.fspath(request_file))
    raw_request_id = request.get("RequestId") if isinstance(request, Mapping) else None
    try:
        request_id = validate_request_id(raw_request_id)
    except DatasetTypesChangeContractError as exc:
        # A request without a safe id can never publish status; drop it so the
        # queue rescan does not reprocess it forever.
        print(f"(dataset types change request error: {_safe_status_message(exc)})")
        _remove_request_file(request_path)
        return False

    expected_path = dataset_types_change_request_path(root, request_id)
    try:
        if request_path.resolve(strict=False) != expected_path.resolve(strict=False):
            print("(dataset types change request filename does not match RequestId)")
            return False
    except OSError:
        return False

    terminal = _terminal_status_or_none(root, request_id)
    if terminal is not None:
        _remove_request_file(request_path)
        return terminal["status"] == "success"

    try:
        normalized = validate_dataset_types_change_request(request)
    except DatasetTypesChangeContractError as exc:
        message = _safe_status_message(exc)
        try:
            write_dataset_types_change_status(
                root,
                request_id,
                "error",
                progress=_progress(
                    "rejected", 0, 0, "Dataset type change request rejected"
                ),
                message=message,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish rejected dataset types change status: "
                f"{_redact_machine_paths(status_exc)})"
            )
            return False
        print(f"(dataset types change request error: {message})")
        _remove_request_file(request_path)
        return False

    lease = acquire_project_scope_lease(root, normalized["ProjectName"])
    if lease is None:
        _log(root, f"{request_id} claim missed (project busy)")
        return False
    claimed_at = time.monotonic()
    heartbeat_stop, heartbeat_thread = start_project_scope_lease_heartbeat(lease)
    try:
        # One lock serializes every status write: job progress and the status
        # heartbeat below republish the same file, and a stale heartbeat write
        # must never land after a newer progress write.
        status_write_lock = threading.Lock()
        current_progress = _progress(
            "starting", 0, _TABLE_UNIT, "Preparing the dataset type change"
        )

        def publish(
            status: str,
            progress: Progress,
            *,
            message: str = "",
            result: Mapping[str, Any] | None = None,
        ) -> None:
            _require_lease(lease)
            with status_write_lock:
                write_dataset_types_change_status(
                    root,
                    request_id,
                    status,
                    progress=progress,
                    message=message,
                    result=result,
                )

        def record_progress(progress: Progress) -> None:
            # The graph rebuild reports once per sidecar. Recording the label
            # and letting the heartbeat publish it keeps the status file's
            # write rate bounded by the contract cadence instead of by the size
            # of the project.
            nonlocal current_progress
            current_progress = progress

        # Remote pollers treat a status whose updated_at stops moving as an
        # abandoned job, so republish the current progress on the contract
        # heartbeat cadence even while one slow stage is still running.
        heartbeat_stop_event = threading.Event()

        def status_heartbeat_loop() -> None:
            while not heartbeat_stop_event.wait(
                DATASET_TYPES_CHANGE_STATUS_HEARTBEAT_SECONDS
            ):
                try:
                    publish("processing", current_progress)
                except Exception:
                    # Lease loss or filesystem trouble ends the heartbeat; the
                    # job thread surfaces the same condition on its next write.
                    return

        status_heartbeat_thread = threading.Thread(
            target=status_heartbeat_loop,
            name=f"arcrho-dataset-types-change-status-{request_id[:8]}",
            daemon=True,
        )

        terminal_result: dict[str, Any] | None = None
        try:
            publish("processing", current_progress)
            status_heartbeat_thread.start()
            try:
                terminal_result = execute_dataset_types_change(
                    root,
                    normalized,
                    progress_callback=record_progress,
                    narrow_lease=lambda classes: narrow_project_scope_lease(
                        lease, normalized["ProjectName"], classes
                    ),
                )
            finally:
                heartbeat_stop_event.set()
                status_heartbeat_thread.join(
                    timeout=DATASET_TYPES_CHANGE_STATUS_HEARTBEAT_SECONDS * 2
                )
            failures = list(terminal_result.get("failures") or [])
            # A partially failed rebuild is reported as an error on purpose:
            # the table is already the new one, so a dataset that did not
            # rebuild now disagrees with it, and nothing else would say so.
            terminal_state = "error" if failures else "success"
            terminal_message = _summarize_failures(terminal_result) if failures else ""
            terminal_progress = _progress(
                "complete",
                current_progress["total"],
                current_progress["total"],
                "Dataset type change complete",
            )
        except DatasetTypesChangeLeaseLost:
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
                "could not publish dataset types change status: "
                f"{_redact_machine_paths(status_exc)}",
                exc=status_exc,
            )
            return False
        if _terminal_status_or_none(root, request_id) is not None:
            _remove_request_file(request_path)
        return terminal_state == "success"
    except DatasetTypesChangeLeaseLost:
        return False
    finally:
        stop_project_scope_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        release_project_scope_lease(lease)
