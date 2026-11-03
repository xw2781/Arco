from __future__ import annotations

import uuid
from typing import Any, Dict, Union

from fastapi import APIRouter, HTTPException, status

from app_server.schemas.project_settings import (
    ProjectSettingsUpdateRequest,
    RenameProjectFolderRequest,
    DuplicateProjectFolderRequest,
    DuplicateProjectFolderCancelResponse,
    DuplicateProjectFolderJobResponse,
    ProjectDuplicationJobStatusResponse,
    ProjectDuplicationUnknownStatusResponse,
    CreateProjectFolderRequest,
    DeleteProjectFolderRequest,
    OpenProjectFolderRequest,
    GeneratedDatasetCacheClearRequest,
    GeneralSettingsUpdateRequest,
    ProjectDatesChangeRequest,
    ProjectLockUpdateRequest,
)
from app_server.services import (
    project_dates_job_service,
    project_lock_service,
    project_settings_service,
    workspace_mutation_client,
    workspace_read_client,
)

router = APIRouter()


# The GET routes read the project registry and General Settings on the server
# host through the Gateway, and the writes run there as workspace mutations; a
# Client PC refuses rather than touching the share. Opening a project folder in
# Explorer stays on this PC, because it hands a path to a program here.


def _mutate(kind: str, kwargs: Dict[str, Any], local, request_id: str | None = None) -> Dict[str, Any]:
    return workspace_mutation_client.run_workspace_mutation(
        kind, kwargs, local=local, request_id=request_id
    )


@router.get("/project_settings")
def list_project_settings_sources() -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "project_settings_sources",
        {},
        local=project_settings_service.list_project_settings_sources,
    )


@router.get("/project_settings/{source}/folders")
def get_project_folders(source: str) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "project_folders",
        {"source": source},
        local=lambda: project_settings_service.get_project_folders(source),
    )


@router.post("/project_settings/{source}/rename_project_folder")
def rename_project_folder(source: str, req: RenameProjectFolderRequest) -> Dict[str, Any]:
    kwargs = {"source": source, "old_name": req.old_name, "new_name": req.new_name}
    return _mutate(
        "project_folder_rename",
        kwargs,
        lambda: project_settings_service.rename_project_folder(**kwargs),
        req.request_id,
    )


@router.post(
    "/project_settings/{source}/duplicate_project_folder",
    response_model=DuplicateProjectFolderJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def duplicate_project_folder(
    source: str,
    req: DuplicateProjectFolderRequest,
) -> DuplicateProjectFolderJobResponse:
    # The copy runs on the Engine; the submit, its status and a cancel go
    # through the Gateway, so a Client PC never touches the job files. The
    # request id keys the job and travels as the mutation's own id.
    request_id = str(req.request_id or "").strip() or uuid.uuid4().hex
    kwargs = {
        "source": source,
        "old_name": req.old_name,
        "new_name": req.new_name,
        "request_id": request_id,
    }
    return _mutate(
        "project_duplication_submit",
        kwargs,
        lambda: project_settings_service.duplicate_project_folder(**kwargs),
        request_id,
    )


@router.get(
    "/project_settings/{source}/duplicate_project_folder/status/{request_id}",
    response_model=Union[ProjectDuplicationJobStatusResponse, ProjectDuplicationUnknownStatusResponse],
    response_model_exclude_none=True,
)
def get_duplicate_project_folder_status(
    source: str,
    request_id: str,
) -> Dict[str, Any]:
    # Polled while the copy runs; a poll the Gateway cannot answer is
    # "unknown", never a failed copy.
    kwargs = {"source": source, "request_id": request_id}
    return workspace_read_client.run_polled_workspace_read(
        "project_duplication_status",
        kwargs,
        local=lambda: project_settings_service.get_duplicate_project_folder_status(**kwargs),
        unknown={"ok": True, "job_id": str(request_id or "").strip()},
    )


@router.post(
    "/project_settings/{source}/duplicate_project_folder/cancel/{request_id}",
    response_model=DuplicateProjectFolderCancelResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_duplicate_project_folder(
    source: str,
    request_id: str,
) -> DuplicateProjectFolderCancelResponse:
    kwargs = {"source": source, "request_id": request_id}
    return _mutate(
        "project_duplication_cancel",
        kwargs,
        lambda: project_settings_service.cancel_duplicate_project_folder(**kwargs),
    )


@router.post("/project_settings/{source}/create_project_folder")
def create_project_folder(source: str, req: CreateProjectFolderRequest) -> Dict[str, Any]:
    kwargs = {"source": source, "name": req.name}
    return _mutate(
        "project_folder_create",
        kwargs,
        lambda: project_settings_service.create_project_folder(**kwargs),
        req.request_id,
    )


@router.post("/project_settings/{source}/delete_project_folder")
def delete_project_folder(source: str, req: DeleteProjectFolderRequest) -> Dict[str, Any]:
    kwargs = {"source": source, "name": req.name}
    return _mutate(
        "project_folder_delete",
        kwargs,
        lambda: project_settings_service.delete_project_folder(**kwargs),
        req.request_id,
    )


@router.post("/project_settings/{source}/open_project_folder")
def open_project_folder(source: str, req: OpenProjectFolderRequest) -> Dict[str, Any]:
    return project_settings_service.open_project_folder(source, req.project_name)


@router.post("/project_settings/{source}/generated_dataset_cache/clear")
def clear_generated_dataset_csv_caches(source: str, req: GeneratedDatasetCacheClearRequest) -> Dict[str, Any]:
    kwargs = {"source": source, "project_name": req.project_name}
    return _mutate(
        "generated_dataset_cache_clear",
        kwargs,
        lambda: project_settings_service.clear_generated_dataset_csv_caches(**kwargs),
    )


@router.get("/project_settings/{source}")
def get_project_settings(source: str) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "project_registry",
        {"source": source},
        local=lambda: project_settings_service.get_project_settings(source),
    )


@router.post("/project_settings/{source}")
def update_project_settings(source: str, req: ProjectSettingsUpdateRequest) -> Dict[str, Any]:
    kwargs = {
        "source": source,
        "folders": list(req.folders),
        "project_paths": list(req.project_paths),
        "expected_revision": req.expected_revision,
    }
    return _mutate(
        "project_registry_save",
        kwargs,
        lambda: project_settings_service.update_project_settings(**kwargs),
        req.request_id,
    )


@router.get("/general_settings")
def get_general_settings(project_name: str) -> Dict[str, Any]:
    if not str(project_name or "").strip():
        raise HTTPException(400, "project_name is required")
    return workspace_read_client.run_workspace_read(
        "general_settings",
        {"project_name": project_name},
        local=lambda: project_settings_service.get_general_settings(project_name),
    )


# A dates change reshapes the whole project, so it runs as one Engine job:
# the preview counts what it touches without writing, the submit queues it,
# and the client polls the status for progress and the result.


@router.get("/general_settings/dates/preview")
def preview_project_dates_change(
    project_name: str,
    origin_start_date: str,
    origin_end_date: str,
    development_end_date: str,
) -> Dict[str, Any]:
    kwargs = {
        "project_name": project_name,
        "origin_start_date": origin_start_date,
        "origin_end_date": origin_end_date,
        "development_end_date": development_end_date,
    }
    return workspace_read_client.run_workspace_read(
        "project_dates_preview",
        kwargs,
        local=lambda: project_dates_job_service.preview_project_dates_change(**kwargs),
    )


@router.post("/general_settings/dates/job")
def submit_project_dates_change(req: ProjectDatesChangeRequest) -> Dict[str, Any]:
    kwargs = {
        "project_name": req.project_name,
        "request_id": str(req.request_id or "").strip() or uuid.uuid4().hex,
        "origin_start_date": req.origin_start_date,
        "origin_end_date": req.origin_end_date,
        "development_end_date": req.development_end_date,
    }
    return workspace_mutation_client.run_workspace_mutation(
        "project_dates_change_submit",
        kwargs,
        local=lambda: project_dates_job_service.submit_project_dates_job(**kwargs),
    )


@router.get("/general_settings/dates/job/status")
def get_project_dates_change_status(project_name: str, job_id: str = "") -> Dict[str, Any]:
    kwargs = {"project_name": project_name, "job_id": job_id}
    return workspace_read_client.run_workspace_read(
        "project_dates_job_status",
        kwargs,
        local=lambda: project_dates_job_service.get_project_dates_job_status(**kwargs),
    )


@router.get("/project_lock")
def get_project_lock(project_name: str) -> Dict[str, Any]:
    if not str(project_name or "").strip():
        raise HTTPException(400, "project_name is required")
    return workspace_read_client.run_workspace_read(
        "project_lock",
        {"project_name": project_name},
        local=lambda: project_lock_service.get_project_lock(project_name),
    )


@router.post("/project_lock")
def set_project_lock(req: ProjectLockUpdateRequest) -> Dict[str, Any]:
    kwargs = {"project_name": req.project_name, "locked": bool(req.locked)}
    return _mutate(
        "project_lock_set",
        kwargs,
        lambda: project_lock_service.set_project_lock(**kwargs),
        req.request_id,
    )


@router.post("/general_settings")
def update_general_settings(req: GeneralSettingsUpdateRequest) -> Dict[str, Any]:
    kwargs = {
        "project_name": req.project_name,
        "origin_start_date": req.origin_start_date,
        "origin_end_date": req.origin_end_date,
        "development_end_date": req.development_end_date,
        "auto_generated": bool(req.auto_generated),
    }
    return _mutate(
        "general_settings_save",
        kwargs,
        lambda: project_settings_service.update_general_settings(**kwargs),
        req.request_id,
    )
