"""Canonical request and status contract for ArcRho project dates change jobs.

Changing a project's Origin Start, Origin End or Development End Date changes
the shape of nearly everything stored in it: engine datasets gain or lose rows
and columns, hand-entered datasets have to follow their origins, and every
method has to move its selections onto the new periods
(docs/plans/project_dates_panel.md). Saving the three dates alone left all of
that behind, so the change runs as one durable Engine job: it checks the date
rule, saves the dates, and then reshapes and refreshes the project class by
class under the *project-scope* lease owned by
``arcrho_dependent_propagation_contract``.

The job saves the dates first (decision 2). A failure part way through leaves
the project half moved, and running the same change again resumes it. That is
why the job keeps a *pending record* per project beside its queue: the
previous dates (most hand-entered datasets store index labels ``1..N``, so
their true origins can only be worked out from the dates they were saved
under), and the classes and hand-entered datasets already done, so a resumed
run never moves a dataset twice. A class whose refresh reported problems is
not done: the record stays, and running the same change again walks that
class once more (``classes_retried``); a class that still reports problems on
its second walk counts as done, so a problem the project had before the change
never holds the record forever. ``inputs_new_diagonal`` names the reshaped
hand-entered triangles that gained a diagonal they hold no values for; a
method refused only for that is expected, not a problem of the change.

Callers identify the work by logical project name only; the Engine derives
every absolute filesystem path from its own configured server root.

This module uses only the Python standard library so the frontend app server,
the Gateway and the frozen Engine can load the same source file. It owns the
request shape, the status shape, the pending record and the protocol paths.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from arcrho_project_duplication_contract import (
    encode_project_directory_segment,
    validate_project_name as _canonical_validate_project_name,
    validate_request_id as _canonical_validate_request_id,
    write_json_atomic,
)


PROJECT_DATES_JOB_FUNCTION = "ArcRhoChangeProjectDates"
PROJECT_DATES_JOB_CONTRACT_VERSION = 1
PROJECT_DATES_JOB_REQUIRED_FIELDS = (
    "Function",
    "ContractVersion",
    "RequestId",
    "ProjectName",
    "OriginStartDate",
    "OriginEndDate",
    "DevelopmentEndDate",
    "UserName",
)
PROJECT_DATES_JOB_STATUS_VALUES = ("queued", "processing", "success", "error")

#: The three dates, by the field names ``general_settings.json`` stores them under.
PROJECT_DATE_FIELDS = ("origin_start_date", "origin_end_date", "development_end_date")

# The canonical ``app_server.services`` modules the job runs, named so the
# frozen Engine's build probe imports them and a missing one stops the build.
PROJECT_DATES_JOB_SERVICE_MODULES: tuple[str, ...] = (
    "arcrho_runtime_service",
    "berquist_sherman_service",
    "calculated_dataset_service",
    "dataset_instance_index_service",
    "dataset_service",
    "project_settings_service",
    "result_selection_service",
    "user_identity_service",
)

PROJECT_DATES_JOB_STATUS_HEARTBEAT_SECONDS = 5.0
PROJECT_DATES_JOB_STATUS_STALE_SECONDS = 45.0
PROJECT_DATES_JOB_QUEUED_STALE_SECONDS = 180.0

_PROGRESS_FIELDS = frozenset({"stage", "completed", "total", "label"})
_DATE_RE = re.compile(r"^\d{4}(0[1-9]|1[0-2])$")


class ProjectDatesJobContractError(ValueError):
    """Raised when a project dates job payload violates this contract."""


def _required_text(value: Any, field_name: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ProjectDatesJobContractError(f"{field_name} is required.")
    return text


def validate_request_id(value: Any) -> str:
    try:
        return _canonical_validate_request_id(value)
    except ValueError as exc:
        raise ProjectDatesJobContractError(str(exc)) from exc


def validate_project_name(value: Any, field_name: str = "ProjectName") -> str:
    try:
        return _canonical_validate_project_name(value, field_name)
    except ValueError as exc:
        raise ProjectDatesJobContractError(str(exc)) from exc


def project_identity(project_name: Any) -> str:
    return validate_project_name(project_name).casefold()


# ---------------------------------------------------------------------------
# The date rule (decision 4)
# ---------------------------------------------------------------------------


def _month(value: Any, label: str) -> str:
    text = str(value if value is not None else "").strip()
    if not _DATE_RE.fullmatch(text):
        raise ProjectDatesJobContractError(f"{label} must be a month written YYYYMM.")
    return text


def normalize_project_dates(
    origin_start_date: Any,
    origin_end_date: Any,
    development_end_date: Any,
) -> dict[str, str]:
    """The three dates as ``YYYYMM`` text, refusing any that break the rule.

    Origin Start must not be after Origin End. Origin End may fall after
    Development End: a project valued mid-year keeps the year's later origins
    (empty until they are written), as ResQ does. All three are months, so
    there is nothing else to check; ``YYYYMM`` text compares in date order.
    """

    dates = {
        "origin_start_date": _month(origin_start_date, "Origin Start Date"),
        "origin_end_date": _month(origin_end_date, "Origin End Date"),
        "development_end_date": _month(development_end_date, "Development End Date"),
    }
    if dates["origin_start_date"] > dates["origin_end_date"]:
        raise ProjectDatesJobContractError(
            "Origin Start Date must not be after Origin End Date."
        )
    return dates


def normalize_date_set(
    value: Any, field_name: str, *, enforce_rule: bool = True
) -> dict[str, str]:
    """A ``{origin_start_date, origin_end_date, development_end_date}`` object.

    ``enforce_rule=False`` checks only that each is a month: the dates a
    project is moved *from* were saved before the rule existed and may break
    it, and they are recorded as they were.
    """

    if not isinstance(value, Mapping):
        raise ProjectDatesJobContractError(f"{field_name} must be a JSON object.")
    if enforce_rule:
        return normalize_project_dates(*(value.get(field) for field in PROJECT_DATE_FIELDS))
    labels = ("Origin Start Date", "Origin End Date", "Development End Date")
    return {
        field: _month(value.get(field), label)
        for field, label in zip(PROJECT_DATE_FIELDS, labels)
    }


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def build_project_dates_job_request(
    *,
    request_id: Any,
    project_name: Any,
    origin_start_date: Any,
    origin_end_date: Any,
    development_end_date: Any,
    user_name: Any,
) -> dict[str, Any]:
    """Build the complete canonical request payload."""

    return validate_project_dates_job_request(
        {
            "Function": PROJECT_DATES_JOB_FUNCTION,
            "ContractVersion": PROJECT_DATES_JOB_CONTRACT_VERSION,
            "RequestId": request_id,
            "ProjectName": project_name,
            "OriginStartDate": origin_start_date,
            "OriginEndDate": origin_end_date,
            "DevelopmentEndDate": development_end_date,
            "UserName": user_name,
        }
    )


def validate_project_dates_job_request(payload: Any) -> dict[str, Any]:
    """Return the normalized exact request, rejecting paths and extensions."""

    if not isinstance(payload, Mapping):
        raise ProjectDatesJobContractError(
            "Project dates job request must be a JSON object."
        )
    supplied = set(payload)
    allowed = set(PROJECT_DATES_JOB_REQUIRED_FIELDS)
    missing = [field for field in PROJECT_DATES_JOB_REQUIRED_FIELDS if field not in supplied]
    if missing:
        raise ProjectDatesJobContractError(
            "Missing request field(s): " + ", ".join(missing) + "."
        )
    extra = sorted((str(field) for field in supplied - allowed), key=str.casefold)
    if extra:
        raise ProjectDatesJobContractError(
            "Unexpected request field(s): " + ", ".join(extra) + "."
        )
    if _required_text(payload.get("Function"), "Function") != PROJECT_DATES_JOB_FUNCTION:
        raise ProjectDatesJobContractError(
            f"Function must be {PROJECT_DATES_JOB_FUNCTION!r}."
        )
    version = payload.get("ContractVersion")
    if isinstance(version, bool) or version != PROJECT_DATES_JOB_CONTRACT_VERSION:
        raise ProjectDatesJobContractError(
            f"Unsupported ContractVersion {version!r}; expected "
            f"{PROJECT_DATES_JOB_CONTRACT_VERSION}."
        )
    dates = normalize_project_dates(
        payload.get("OriginStartDate"),
        payload.get("OriginEndDate"),
        payload.get("DevelopmentEndDate"),
    )
    return {
        "Function": PROJECT_DATES_JOB_FUNCTION,
        "ContractVersion": PROJECT_DATES_JOB_CONTRACT_VERSION,
        "RequestId": validate_request_id(payload.get("RequestId")),
        "ProjectName": validate_project_name(payload.get("ProjectName")),
        "OriginStartDate": dates["origin_start_date"],
        "OriginEndDate": dates["origin_end_date"],
        "DevelopmentEndDate": dates["development_end_date"],
        "UserName": _required_text(payload.get("UserName"), "UserName"),
    }


def request_dates(request: Mapping[str, Any]) -> dict[str, str]:
    """The requested dates of a validated request, by settings field name."""

    return {
        "origin_start_date": request["OriginStartDate"],
        "origin_end_date": request["OriginEndDate"],
        "development_end_date": request["DevelopmentEndDate"],
    }


# ---------------------------------------------------------------------------
# Protocol paths
# ---------------------------------------------------------------------------


def _root_path(server_root: str | os.PathLike[str]) -> Path:
    raw = os.fspath(server_root)
    if not str(raw).strip():
        raise ProjectDatesJobContractError("Arco Server root is required.")
    return Path(raw).expanduser()


def project_dates_job_protocol_directory(server_root: str | os.PathLike[str]) -> Path:
    """A subfolder of ``requests``, so loose-file sweeps never touch it."""

    return _root_path(server_root) / "requests" / "project_dates"


def project_dates_job_requests_directory(server_root: str | os.PathLike[str]) -> Path:
    return project_dates_job_protocol_directory(server_root) / "requests"


def project_dates_job_statuses_directory(server_root: str | os.PathLike[str]) -> Path:
    return project_dates_job_protocol_directory(server_root) / "statuses"


def project_dates_pending_directory(server_root: str | os.PathLike[str]) -> Path:
    return project_dates_job_protocol_directory(server_root) / "pending"


def project_dates_job_request_path(server_root: str | os.PathLike[str], request_id: Any) -> Path:
    return project_dates_job_requests_directory(server_root) / f"{validate_request_id(request_id)}.json"


def project_dates_job_status_path(server_root: str | os.PathLike[str], request_id: Any) -> Path:
    return project_dates_job_statuses_directory(server_root) / f"{validate_request_id(request_id)}.json"


def project_dates_pending_path(server_root: str | os.PathLike[str], project_name: Any) -> Path:
    segment = encode_project_directory_segment(validate_project_name(project_name))
    return project_dates_pending_directory(server_root) / f"{segment}.json"


# ---------------------------------------------------------------------------
# Pending record: what a half-finished change needs to resume
# ---------------------------------------------------------------------------


def _name_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProjectDatesJobContractError(f"{field_name} must be a list of text.")
    return list(value)


def validate_pending_record(payload: Any) -> dict[str, Any]:
    """Validate a pending record and return its canonical fields."""

    if not isinstance(payload, Mapping):
        raise ProjectDatesJobContractError("Pending record must be a JSON object.")
    return {
        "contract_version": PROJECT_DATES_JOB_CONTRACT_VERSION,
        "project_name": validate_project_name(payload.get("project_name"), "project_name"),
        "request_id": validate_request_id(payload.get("request_id")),
        "previous_dates": normalize_date_set(
            payload.get("previous_dates"), "previous_dates", enforce_rule=False
        ),
        "dates": normalize_date_set(payload.get("dates"), "dates"),
        "classes_done": _name_list(payload.get("classes_done"), "classes_done"),
        "inputs_done": _name_list(payload.get("inputs_done"), "inputs_done"),
        "classes_retried": _name_list(payload.get("classes_retried"), "classes_retried"),
        "inputs_new_diagonal": _name_list(payload.get("inputs_new_diagonal"), "inputs_new_diagonal"),
        "updated_at": _required_text(payload.get("updated_at"), "updated_at"),
    }


def pending_item_key(reserving_class: Any, name: Any) -> str:
    """One done-list entry for a dataset in a class."""

    return f"{str(reserving_class or '').strip().casefold()}|{str(name or '').strip().casefold()}"


def write_pending_record(
    server_root: str | os.PathLike[str],
    *,
    project_name: Any,
    request_id: Any,
    previous_dates: Mapping[str, Any],
    dates: Mapping[str, Any],
    classes_done: Iterable[str] = (),
    inputs_done: Iterable[str] = (),
    classes_retried: Iterable[str] = (),
    inputs_new_diagonal: Iterable[str] = (),
) -> Path:
    payload = validate_pending_record(
        {
            "project_name": project_name,
            "request_id": request_id,
            "previous_dates": dict(previous_dates),
            "dates": dict(dates),
            "classes_done": list(classes_done),
            "inputs_done": list(inputs_done),
            "classes_retried": list(classes_retried),
            "inputs_new_diagonal": list(inputs_new_diagonal),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return write_json_atomic(project_dates_pending_path(server_root, project_name), payload)


def read_pending_record(
    server_root: str | os.PathLike[str], project_name: Any
) -> dict[str, Any] | None:
    path = project_dates_pending_path(server_root, project_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    return validate_pending_record(payload)


def clear_pending_record(server_root: str | os.PathLike[str], project_name: Any) -> None:
    try:
        project_dates_pending_path(server_root, project_name).unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def _normalize_progress(progress: Any) -> dict[str, Any]:
    if not isinstance(progress, Mapping):
        raise ProjectDatesJobContractError("progress must be a JSON object.")
    supplied = set(progress)
    missing = sorted(_PROGRESS_FIELDS - supplied)
    extra = sorted((str(field) for field in supplied - _PROGRESS_FIELDS), key=str.casefold)
    if missing:
        raise ProjectDatesJobContractError("Missing progress field(s): " + ", ".join(missing) + ".")
    if extra:
        raise ProjectDatesJobContractError("Unexpected progress field(s): " + ", ".join(extra) + ".")
    completed, total = progress.get("completed"), progress.get("total")
    for field_name, value in (("completed", completed), ("total", total)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProjectDatesJobContractError(f"progress.{field_name} must be a non-negative integer.")
    if completed > total:
        raise ProjectDatesJobContractError("progress.completed must not be greater than progress.total.")
    return {
        "stage": _required_text(progress.get("stage"), "progress.stage"),
        "completed": completed,
        "total": total,
        "label": _required_text(progress.get("label"), "progress.label"),
    }


def _normalize_status_code(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ProjectDatesJobContractError("status_code must be an HTTP status code.")
    return value


def _normalize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise ProjectDatesJobContractError("result must be a JSON object.")
    return dict(result)


def _status_payload(
    request_id: Any,
    status: Any,
    *,
    progress: Any,
    updated_at: Any,
    message: Any = None,
    status_code: Any = None,
    previous_dates: Any = None,
    result: Any = None,
) -> dict[str, Any]:
    normalized_status = str(status if status is not None else "").strip()
    if normalized_status not in PROJECT_DATES_JOB_STATUS_VALUES:
        raise ProjectDatesJobContractError(f"Invalid project dates job status: {status!r}.")
    payload: dict[str, Any] = {
        "contract_version": PROJECT_DATES_JOB_CONTRACT_VERSION,
        "status": normalized_status,
        "updated_at": _required_text(updated_at, "updated_at"),
        "request_id": validate_request_id(request_id),
        "progress": _normalize_progress(progress),
    }
    normalized_message = str(message if message is not None else "").strip()
    if normalized_message:
        payload["message"] = normalized_message
    if status_code is not None:
        payload["status_code"] = _normalize_status_code(status_code)
    if previous_dates is not None:
        payload["previous_dates"] = normalize_date_set(
            previous_dates, "previous_dates", enforce_rule=False
        )
    if result is not None:
        payload["result"] = _normalize_result(result)
    return payload


def build_project_dates_job_status(
    request_id: Any,
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    status_code: int | None = None,
    previous_dates: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    updated_at: Any = None,
) -> dict[str, Any]:
    """Build one complete location-independent job status payload.

    ``previous_dates`` is recorded before the dates are saved, so a status
    always says what the project was moved from; ``status_code`` carries the
    HTTP status a refusal maps to (400 bad dates, 409 another change still
    unfinished, 423 locked).
    """

    return _status_payload(
        request_id,
        status,
        progress=progress,
        updated_at=(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
            if updated_at is None
            else updated_at
        ),
        message=message,
        status_code=status_code,
        previous_dates=previous_dates,
        result=result,
    )


def validate_project_dates_job_status(
    payload: Any, *, expected_request_id: Any = None
) -> dict[str, Any]:
    """Validate a persisted status and return only its canonical fields."""

    if not isinstance(payload, Mapping):
        raise ProjectDatesJobContractError("Project dates job status must be a JSON object.")
    required = {"contract_version", "status", "updated_at", "request_id", "progress"}
    allowed = required | {"message", "status_code", "previous_dates", "result"}
    supplied = set(payload)
    missing = sorted(required - supplied)
    extra = sorted((str(field) for field in supplied - allowed), key=str.casefold)
    if missing:
        raise ProjectDatesJobContractError("Missing status field(s): " + ", ".join(missing) + ".")
    if extra:
        raise ProjectDatesJobContractError("Unexpected status field(s): " + ", ".join(extra) + ".")
    version = payload.get("contract_version")
    if isinstance(version, bool) or version != PROJECT_DATES_JOB_CONTRACT_VERSION:
        raise ProjectDatesJobContractError(
            f"Unsupported contract_version {version!r}; expected "
            f"{PROJECT_DATES_JOB_CONTRACT_VERSION}."
        )
    normalized = _status_payload(
        payload.get("request_id"),
        payload.get("status"),
        progress=payload.get("progress"),
        updated_at=payload.get("updated_at"),
        message=payload.get("message"),
        status_code=payload.get("status_code"),
        previous_dates=payload.get("previous_dates"),
        result=payload.get("result"),
    )
    if "message" in payload and "message" not in normalized:
        raise ProjectDatesJobContractError("message is required.")
    if expected_request_id is not None and normalized["request_id"] != validate_request_id(expected_request_id):
        raise ProjectDatesJobContractError(
            "Project dates job status RequestId does not match the requested job."
        )
    return normalized


def write_project_dates_job_status(
    server_root: str | os.PathLike[str],
    request_id: Any,
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    status_code: int | None = None,
    previous_dates: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    updated_at: Any = None,
) -> Path:
    """Build and atomically publish one project dates job status."""

    payload = build_project_dates_job_status(
        request_id,
        status,
        progress=progress,
        message=message,
        status_code=status_code,
        previous_dates=previous_dates,
        result=result,
        updated_at=updated_at,
    )
    return write_json_atomic(project_dates_job_status_path(server_root, request_id), payload)


def read_project_dates_job_status(
    server_root: str | os.PathLike[str], request_id: Any
) -> dict[str, Any] | None:
    """Read and validate one published status, or ``None`` when absent."""

    normalized_request_id = validate_request_id(request_id)
    path = project_dates_job_status_path(server_root, normalized_request_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    return validate_project_dates_job_status(payload, expected_request_id=normalized_request_id)


# ---------------------------------------------------------------------------
# Queued-job probe
# ---------------------------------------------------------------------------


def find_queued_project_dates_job(
    server_root: str | os.PathLike[str],
    project_name: Any,
    *,
    now: float | None = None,
    queued_fresh_seconds: float = PROJECT_DATES_JOB_QUEUED_STALE_SECONDS,
) -> dict[str, str] | None:
    """Return a submitted-but-unclaimed dates change for one project, or ``None``.

    A running job is reported by the project-scope propagation hold; this
    covers only the window between the request being published and an Engine
    claiming the lease, so two changes cannot be queued for one project.
    """

    identity = project_identity(project_name)
    observed_at = time.time() if now is None else float(now)
    try:
        candidates = tuple(project_dates_job_requests_directory(server_root).glob("*.json"))
    except OSError:
        return None
    for candidate in candidates:
        try:
            if observed_at - candidate.stat().st_mtime > queued_fresh_seconds:
                continue
            request = validate_project_dates_job_request(
                json.loads(candidate.read_text(encoding="utf-8-sig"))
            )
        except (OSError, ValueError, TypeError):
            continue
        if project_identity(request["ProjectName"]) != identity:
            continue
        try:
            status = read_project_dates_job_status(server_root, request["RequestId"])
        except (OSError, ValueError, TypeError):
            status = None
        if status is not None and status["status"] in {"success", "error"}:
            continue
        return {"reason": "queued", "job_id": request["RequestId"]}
    return None
