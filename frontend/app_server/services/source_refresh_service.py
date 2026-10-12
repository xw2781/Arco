"""Client-side submission and status for Engine-hosted source-table refreshes.

Importing a project's source table used to run in whatever process the user
clicked in. On a Client PC that meant copying the external CSV through the
client -- read from one share, written to another -- then reading the whole
master copy back to count its rows, and finally rebuilding the table summary
and reserving-class values over the same mapped drive. This module replaces
that with a durable job: the request is published for the Arco Engine, which
does all of it on local disk, and the client only polls the status.

The job optionally continues into the project's dependency graph, regenerating
every engine-built dataset instance and walking the calculated datasets and
methods that depend on them. That part has no client-side equivalent at all --
it is the step that used to be left to whoever next opened each object.

Submission is idempotent by ``request_id``: the client generates the id before
its first POST and reuses it on every retry, so a response lost in flight can
never produce a second refresh.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

from arcrho_dependent_propagation_contract import (
    ENGINE_UNAVAILABLE_MESSAGE,
    EngineUnavailableError,
    find_project_scope_propagation_hold,
    require_live_engine,
)
from arcrho_project_duplication_contract import (
    path_is_link_or_reparse,
    write_json_atomic,
)
from arcrho_source_refresh_contract import (
    SourceRefreshContractError,
    build_source_refresh_request,
    find_source_refresh_hold,
    source_refresh_request_path,
    source_refresh_status_path,
    validate_project_name,
    validate_request_id,
    validate_source_refresh_status,
    write_source_refresh_status,
)

from arcrho_api.source_table_contract import (
    SOURCE_TYPE_CSV,
    import_source_path_is_shared,
    normalize_source_type,
)
from app_server import config
from app_server.services import user_identity_service


SOURCE_REFRESH_BUSY_MESSAGE = (
    "A source table refresh is already running for this project. "
    "Please wait for it to finish before starting another."
)
PROJECT_JOB_RUNNING_MESSAGE = (
    "A project-wide update is currently running for this project. "
    "Please wait for it to finish before refreshing the source table."
)


def _validate_protocol_paths(server_root: Path) -> None:
    current = server_root
    checks = []
    for part in ("requests", "source_table_refresh"):
        current /= part
        checks.append(current)
    for leaf in ("requests", "statuses", "locks"):
        checks.append(current / leaf)
    for path in checks:
        try:
            unsafe = path_is_link_or_reparse(path)
        except OSError as error:
            raise HTTPException(
                500, "The source refresh protocol path is inaccessible."
            ) from error
        if unsafe:
            raise HTTPException(500, "The source refresh protocol path is unsafe.")


def _workspace_server_root() -> Path:
    workspace = config.load_workspace_paths()
    server_root_value = str(workspace.get("workspace_root") or "").strip()
    if not server_root_value:
        raise HTTPException(500, "The Arco Server workspace is not configured.")
    server_root = Path(server_root_value).expanduser()
    if not server_root.is_absolute():
        raise HTTPException(500, "The Arco Server workspace root must be absolute.")
    try:
        root_available = server_root.is_dir()
    except OSError as error:
        raise HTTPException(
            500, "The Arco Server workspace root is inaccessible."
        ) from error
    if not root_available:
        raise HTTPException(500, "The Arco Server workspace root is unavailable.")
    _validate_protocol_paths(server_root)
    return server_root


def _validated_project(project_name: str) -> str:
    try:
        return validate_project_name(project_name)
    except SourceRefreshContractError as error:
        raise HTTPException(400, str(error)) from error


def _read_status(server_root: Path, request_id: str) -> Dict[str, Any] | None:
    status_path = source_refresh_status_path(server_root, request_id)
    try:
        with status_path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except FileNotFoundError:
        return None
    except PermissionError as error:
        raise HTTPException(
            423, "Source refresh status is locked or inaccessible."
        ) from error
    except json.JSONDecodeError as error:
        raise HTTPException(
            502, "Arco Engine published an invalid source refresh status."
        ) from error
    except OSError as error:
        raise HTTPException(500, "Failed to read the source refresh status.") from error
    try:
        return validate_source_refresh_status(payload, expected_request_id=request_id)
    except SourceRefreshContractError as error:
        raise HTTPException(
            502, "Arco Engine published an invalid source refresh status."
        ) from error


def describe_source_refresh_plan(
    project_name: str,
    settings: Dict[str, Any],
    status: Dict[str, Any],
    *,
    csv_path: str,
    csv_path_rewritten: bool,
) -> Dict[str, Any]:
    """Say who can perform this project's import, and whether one is running.

    The caller needs both answers before it offers the button: a CSV on a share
    is imported by the Arco Server host, while a SQL Server profile or a path
    only this machine can open has to be imported here first.

    Everything here is already in hand: *settings* is the project's source
    settings and *status* its refresh status, both read on the server host,
    and *csv_path* the saved path as the client translated it from its own
    drive letters. A SQL Server project is never server-importable: the import
    authenticates as the caller's Windows login, and moving it to a server
    service account would silently change who reads the table. A combined
    source is never server-importable either: its tables are read and joined
    on the client, so only ``csv`` can answer yes.
    """

    name = _validated_project(project_name)
    source_type = normalize_source_type(settings.get("source_type"))
    return {
        "ok": True,
        "project_name": name,
        "source_type": source_type,
        "server_can_import": bool(
            source_type == SOURCE_TYPE_CSV and csv_path and import_source_path_is_shared(csv_path)
        ),
        "csv_path_rewritten": bool(csv_path_rewritten),
        "busy": bool(status.get("busy")),
        "busy_reason": str(status.get("busy_reason") or ""),
    }


def submit_source_table_refresh_job(
    project_name: str,
    request_id: str | None = None,
    *,
    import_source: bool = True,
    force: bool = True,
    refresh_dependents: bool = True,
    dataset_types: Any = None,
    reserving_class_types: Any = None,
) -> Dict[str, Any]:
    """Publish one queued source-refresh request and return its job identity.

    Re-submitting an id that already has a published status returns that job
    untouched, so a retry after a lost response never starts a second refresh.

    ``dataset_types`` and ``reserving_class_types`` narrow the dependent refresh
    to the chosen engine-built dataset types and the reserving classes whose
    path matches the chosen ``{Name, Level}`` types; either left empty means
    everything.
    """

    server_root = _workspace_server_root()
    try:
        require_live_engine(server_root)
    except EngineUnavailableError as error:
        raise HTTPException(503, ENGINE_UNAVAILABLE_MESSAGE) from error

    try:
        request = build_source_refresh_request(
            request_id=request_id if request_id else uuid.uuid4().hex,
            project_name=project_name,
            user_name=user_identity_service.get_windows_login_name(),
            import_source=bool(import_source),
            force=bool(force),
            refresh_dependents=bool(refresh_dependents),
            dataset_types=dataset_types,
            reserving_class_types=reserving_class_types,
        )
    except SourceRefreshContractError as error:
        raise HTTPException(400, str(error)) from error

    normalized_request_id = request["RequestId"]
    existing = _read_status(server_root, normalized_request_id)
    if existing is not None:
        return {
            "ok": True,
            "job_id": normalized_request_id,
            "status": existing["status"],
            "resumed": True,
        }

    hold = find_source_refresh_hold(server_root, request["ProjectName"])
    if hold is not None:
        raise HTTPException(423, SOURCE_REFRESH_BUSY_MESSAGE)
    # A project-scope job (a dataset-type change) already owns every class of
    # this project; a refresh queued behind it would walk the classes it is
    # still rewriting.
    if find_project_scope_propagation_hold(server_root, request["ProjectName"]) is not None:
        raise HTTPException(423, PROJECT_JOB_RUNNING_MESSAGE)

    request_path = source_refresh_request_path(server_root, normalized_request_id)
    published_status_path: Path | None = None
    try:
        published_status_path = write_source_refresh_status(
            server_root,
            normalized_request_id,
            "queued",
            progress={
                "stage": "queued",
                "completed": 0,
                "total": 0,
                "label": "Queued for Arco Engine",
            },
        )
        write_json_atomic(request_path, request)
    except PermissionError as error:
        _remove_unpublished_files(request_path, published_status_path)
        raise HTTPException(
            423, "The source refresh request queue is locked or inaccessible."
        ) from error
    except OSError as error:
        _remove_unpublished_files(request_path, published_status_path)
        raise HTTPException(500, "Failed to submit the source refresh job.") from error

    return {
        "ok": True,
        "job_id": normalized_request_id,
        "status": "queued",
        "resumed": False,
    }


def _remove_unpublished_files(*paths: Path | None) -> None:
    for path in paths:
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def get_source_table_refresh_status(
    project_name: str,
    job_id: str = "",
) -> Dict[str, Any]:
    """One job's status plus whether the project is busy with any refresh.

    Both answers come from the same visit because a poller needs them together:
    a job that has not published a status yet is indistinguishable from a lost
    one unless the caller can also see that the project is still held.
    """

    name = _validated_project(project_name)
    server_root = _workspace_server_root()
    hold = find_source_refresh_hold(server_root, name)
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
    except SourceRefreshContractError as error:
        raise HTTPException(400, str(error)) from error
    response["job_id"] = normalized_job_id

    status = _read_status(server_root, normalized_job_id)
    if status is None:
        raise HTTPException(404, "Source refresh job was not found.")
    response["found"] = True
    response.update(status)
    return response
