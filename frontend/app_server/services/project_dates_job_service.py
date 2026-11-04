"""Client-side submission, status and preview for a project dates change.

Changing Origin Start, Origin End or Development End moves the whole project
to a new shape (docs/plans/project_dates_panel.md), so it runs as one durable
Engine job (``arcrho_project_dates_job_contract``) rather than as the three
field saves the main page used to make. This module is the app server's half:

- ``submit_project_dates_job`` publishes the request for the Engine, after the
  same project-wide preflight every project-scope job takes, and refuses other
  dates while an earlier change is unfinished.
- ``get_project_dates_job_status`` answers a poller with the job's status and
  whether the project is still held.
- ``preview_project_dates_change`` answers what the confirmation modal shows
  -- how many classes, datasets and methods the change touches, how many
  origins drop out, and which hand-entered datasets are reshaped -- without
  writing anything.

Submission travels as a hosted workspace mutation and the status and preview
as hosted reads, so from a Client PC each is one HTTP exchange with the
Gateway. Submission is idempotent by the client-owned ``request_id``.
"""

from __future__ import annotations

import csv
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping

from fastapi import HTTPException

from arcrho_api.period_reshape import (
    is_imported_dataset,
    month_index,
    origin_start_months,
    plan_input_dataset_reshape,
)
from arcrho_dependent_propagation_contract import find_project_scope_propagation_hold
from arcrho_project_dates_job_contract import (
    PROJECT_DATE_FIELDS,
    ProjectDatesJobContractError,
    build_project_dates_job_request,
    find_queued_project_dates_job,
    normalize_date_set,
    normalize_project_dates,
    project_dates_job_request_path,
    read_pending_record,
    read_project_dates_job_status,
    validate_project_name,
    validate_request_id,
    write_project_dates_job_status,
)
from arcrho_project_duplication_contract import path_is_link_or_reparse, write_json_atomic
from arcrho_source_refresh_contract import find_source_refresh_hold

from app_server import config
from app_server.services import (
    dataset_instance_index_service,
    dataset_sidecar_status_service,
    dependent_propagation_service,
    project_settings_service,
    reserving_class_service,
    user_identity_service,
)


DATES_JOB_BUSY_MESSAGE = (
    "A change of the project dates is already queued for this project. "
    "Please wait for it to finish."
)
SOURCE_REFRESH_RUNNING_MESSAGE = (
    "A source table refresh is running for this project. "
    "Please wait for it to finish, then change the dates again."
)
UNFINISHED_CHANGE_MESSAGE = (
    "An earlier change of the project dates has not finished. "
    "Run that change again before choosing other dates."
)
INVALID_CURRENT_DATES_MESSAGE = (
    "The project's current dates are missing or invalid, so nothing can say "
    "where its stored rows belong."
)

# Index rows that are datasets rather than methods. Everything else with a
# source kind is a method the dependent walk refreshes.
_DATASET_SOURCE_KINDS = frozenset({"input", "engine"})
_CALCULATED_SOURCE_KIND = "calculated"


def _validated_project(project_name: str) -> str:
    try:
        return validate_project_name(project_name)
    except ProjectDatesJobContractError as error:
        raise HTTPException(400, str(error)) from error


def _validated_dates(origin_start_date: Any, origin_end_date: Any, development_end_date: Any) -> Dict[str, str]:
    try:
        return normalize_project_dates(origin_start_date, origin_end_date, development_end_date)
    except ProjectDatesJobContractError as error:
        raise HTTPException(400, str(error)) from error


def _validate_protocol_paths(server_root: Path) -> None:
    current = server_root
    checks = []
    for part in ("requests", "project_dates"):
        current /= part
        checks.append(current)
    for leaf in ("requests", "statuses", "pending"):
        checks.append(current / leaf)
    for path in checks:
        try:
            unsafe = path_is_link_or_reparse(path)
        except OSError as error:
            raise HTTPException(500, "The project dates job protocol path is inaccessible.") from error
        if unsafe:
            raise HTTPException(500, "The project dates job protocol path is unsafe.")


def _pending(server_root: Path, project_name: str) -> Dict[str, Any] | None:
    try:
        return read_pending_record(server_root, project_name)
    except (OSError, ValueError) as error:
        raise HTTPException(
            409, "The record of an unfinished date change could not be read."
        ) from error


def _refuse_other_dates(pending: Mapping[str, Any] | None, dates: Mapping[str, str]) -> None:
    if pending is not None and pending["dates"] != dict(dates):
        raise HTTPException(409, UNFINISHED_CHANGE_MESSAGE)


def _read_status(server_root: Path, request_id: str) -> Dict[str, Any] | None:
    try:
        return read_project_dates_job_status(server_root, request_id)
    except PermissionError as error:
        raise HTTPException(423, "Project dates job status is locked or inaccessible.") from error
    except (ValueError, TypeError) as error:
        raise HTTPException(502, "Arco Engine published an invalid project dates job status.") from error
    except OSError as error:
        raise HTTPException(500, "Failed to read the project dates job status.") from error


# ---------------------------------------------------------------------------
# Submit and status
# ---------------------------------------------------------------------------


def submit_project_dates_job(
    project_name: str,
    request_id: str = "",
    *,
    origin_start_date: str = "",
    origin_end_date: str = "",
    development_end_date: str = "",
) -> Dict[str, Any]:
    """Publish one queued dates change and return its job identity.

    Preflights the whole project before anything is published: a live Engine,
    no project-wide job already running, no reserving class still being
    walked, and no unfinished change to other dates. Re-submitting an id that
    already has a published status returns that job untouched.
    """

    name = _validated_project(project_name)
    dates = _validated_dates(origin_start_date, origin_end_date, development_end_date)
    server_root = dependent_propagation_service.require_project_scope_writable(name)
    _validate_protocol_paths(server_root)

    try:
        request = build_project_dates_job_request(
            request_id=request_id if request_id else uuid.uuid4().hex,
            project_name=name,
            origin_start_date=dates["origin_start_date"],
            origin_end_date=dates["origin_end_date"],
            development_end_date=dates["development_end_date"],
            # The Engine stamps the settings, sidecars and audit log as this user.
            user_name=user_identity_service.get_windows_login_name(),
        )
    except ProjectDatesJobContractError as error:
        raise HTTPException(400, str(error)) from error

    normalized_request_id = request["RequestId"]
    existing = _read_status(server_root, normalized_request_id)
    if existing is not None:
        return {"ok": True, "job_id": normalized_request_id, "status": existing["status"], "resumed": True}

    _refuse_other_dates(_pending(server_root, name), dates)
    if find_source_refresh_hold(server_root, name) is not None:
        raise HTTPException(423, SOURCE_REFRESH_RUNNING_MESSAGE)
    if find_queued_project_dates_job(server_root, name) is not None:
        raise HTTPException(423, DATES_JOB_BUSY_MESSAGE)

    request_path = project_dates_job_request_path(server_root, normalized_request_id)
    published_status_path: Path | None = None
    try:
        published_status_path = write_project_dates_job_status(
            server_root,
            normalized_request_id,
            "queued",
            progress={"stage": "queued", "completed": 0, "total": 0, "label": "Queued for Arco Engine"},
        )
        write_json_atomic(request_path, request)
    except PermissionError as error:
        _remove_unpublished_files(request_path, published_status_path)
        raise HTTPException(423, "The project dates job queue is locked or inaccessible.") from error
    except OSError as error:
        _remove_unpublished_files(request_path, published_status_path)
        raise HTTPException(500, "Failed to submit the project dates change.") from error

    return {"ok": True, "job_id": normalized_request_id, "status": "queued", "resumed": False}


def _remove_unpublished_files(*paths: Path | None) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def get_project_dates_job_status(project_name: str, job_id: str = "") -> Dict[str, Any]:
    """One job's status plus whether the project is still held."""

    name = _validated_project(project_name)
    server_root = dependent_propagation_service.workspace_server_root()
    hold = find_project_scope_propagation_hold(server_root, name)
    response: Dict[str, Any] = {
        "ok": True,
        "project_name": name,
        "job_id": "",
        "found": False,
        "busy": hold is not None,
        "busy_reason": hold["reason"] if hold is not None else "",
    }
    if not str(job_id or "").strip():
        return response
    try:
        normalized_job_id = validate_request_id(job_id)
    except ProjectDatesJobContractError as error:
        raise HTTPException(400, str(error)) from error
    response["job_id"] = normalized_job_id
    status = _read_status(server_root, normalized_job_id)
    if status is None:
        raise HTTPException(404, "Project dates job was not found.")
    response["found"] = True
    response.update(status)
    return response


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _stored_width(csv_path: str) -> int:
    """The widest row of a stored CSV, as the job reads it."""

    try:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
            return max((len(row) for row in csv.reader(handle)), default=0)
    except FileNotFoundError:
        return 0


def _origin_changes(lengths: List[int], previous: Mapping[str, str], dates: Mapping[str, str]) -> List[Dict[str, int]]:
    changes = []
    for length in sorted(set(lengths), reverse=True):
        old = origin_start_months(previous["origin_start_date"], previous["origin_end_date"], length)
        new = origin_start_months(dates["origin_start_date"], dates["origin_end_date"], length)
        kept = set(new)
        dropped = [month for month in old if month not in kept]
        # Which side of the new origin range each dropped origin starts on, so
        # the panel can name the cut-off once; one inside the range means the
        # periods were regrouped and only the counts are honest.
        first, last = month_index(dates["origin_start_date"]), month_index(dates["origin_end_date"])
        changes.append({
            "origin_length": length,
            "before": len(old),
            "after": len(new),
            "dropped": len(dropped),
            "dropped_before": sum(1 for month in dropped if month < first),
            "dropped_after": sum(1 for month in dropped if month > last),
            "added": len(new) - (len(old) - len(dropped)),
        })
    return changes


def preview_project_dates_change(
    project_name: str,
    origin_start_date: str = "",
    origin_end_date: str = "",
    development_end_date: str = "",
) -> Dict[str, Any]:
    """What a change to these dates would touch, without changing anything.

    Counts per project: the reserving classes the job walks, the engine
    datasets it regenerates, the calculated datasets and methods the
    dependent walk refreshes, and every hand-entered or imported dataset with
    whether the job reshapes it (the same plan the job writes) or lists it
    as off the date grid. ``origin_changes`` gives, for each origin length
    the project stores, how many origins drop out and how many are added.
    Refuses bad dates (400) and other dates while an earlier change is
    unfinished (409), as the submission does.
    """

    name = _validated_project(project_name)
    dates = _validated_dates(origin_start_date, origin_end_date, development_end_date)
    server_root = dependent_propagation_service.workspace_server_root()
    pending = _pending(server_root, name)
    _refuse_other_dates(pending, dates)

    settings = project_settings_service.get_general_settings(name).get("data") or {}
    current = {field: str(settings.get(field) or "").strip() for field in PROJECT_DATE_FIELDS}
    if pending is not None:
        previous = dict(pending["previous_dates"])
    else:
        try:
            previous = normalize_date_set(current, "previous_dates", enforce_rule=False)
        except ProjectDatesJobContractError as error:
            raise HTTPException(422, INVALID_CURRENT_DATES_MESSAGE) from error

    response: Dict[str, Any] = {
        "ok": True,
        "project_name": name,
        "dates": dict(dates),
        "previous_dates": previous,
        "unchanged": pending is None and current == dates,
        "resumed": pending is not None,
        "classes": 0,
        "engine_datasets": 0,
        "calculated_datasets": 0,
        "methods": 0,
        "imported_datasets": 0,
        "imported_reshaped": 0,
        "imported": [],
        "origin_changes": [],
    }
    if response["unchanged"]:
        return response

    classes = reserving_class_service.list_reserving_classes_with_data(name)["reserving_classes"]
    response["classes"] = len(classes)
    origin_lengths: List[int] = []
    for reserving_class in classes:
        index = dataset_instance_index_service.get_index(name, reserving_class)
        data_dir = config.get_project_dataset_cache_dir(name, reserving_class)
        for row in index.get("files") or []:
            if not isinstance(row, Mapping) or not str(row.get("name") or "").strip():
                continue
            length = row.get("origin_length")
            if isinstance(length, int) and not isinstance(length, bool) and length > 0:
                origin_lengths.append(length)
            source_kind = str(row.get("source_kind") or "").strip().casefold()
            if source_kind == _CALCULATED_SOURCE_KIND:
                response["calculated_datasets"] += 1
                continue
            if source_kind not in _DATASET_SOURCE_KINDS:
                if source_kind:
                    response["methods"] += 1
                continue
            dataset_name = str(row["name"]).strip()
            sidecar = dataset_sidecar_status_service.read_sidecar(
                dataset_sidecar_status_service.sidecar_path(name, reserving_class, dataset_name)
            ) or {}
            if sidecar.get("calculated"):
                response["calculated_datasets"] += 1
                continue
            if not is_imported_dataset(sidecar):
                response["engine_datasets"] += 1
                continue
            width = 0
            if str(sidecar.get("data_format") or "").strip().casefold() != "vector":
                csv_file = os.path.basename(str(sidecar.get("csv_file") or "").strip())
                if csv_file:
                    width = _stored_width(os.path.join(data_dir, csv_file))
            shape = plan_input_dataset_reshape(sidecar, width, previous, dates)
            off_grid = shape["origins"] is None
            response["imported_datasets"] += 1
            if shape["changed"]:
                response["imported_reshaped"] += 1
            response["imported"].append({
                "reserving_class": reserving_class,
                "name": dataset_name,
                "reshaped": shape["changed"],
                "off_grid": off_grid,
                "origins_dropped": 0 if off_grid else shape["origins"]["dropped"],
            })
    response["origin_changes"] = _origin_changes(origin_lengths, previous, dates)
    return response
