"""Routes for the project-owned imported source table.

The project's source settings, its import profile, the shared SQL Server
connection list and the refresh job are read and written on the server host
through the Gateway; a Client PC refuses rather than touching the share. What
stays here is what only this PC can do: translate its own drive letters, stat
an external CSV on a drive only it has, and talk to SQL Server as the user's
Windows login. A source only this PC can read (``/source_table/import`` for SQL
Server, ``/source_table/refresh`` for a CSV) is read here and uploaded to the
Gateway, which writes the master table. A combined source
(``/source_table/combined/*``) is read, previewed and joined here for the same
reason, and uploaded the same way.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from arcrho_api.source_table_contract import (
    SOURCE_TYPE_CSV,
    SOURCE_TYPE_MSSQL,
    normalize_import_source_path,
)

from app_server.schemas.source_table import (
    CombinedSourceImportRequest,
    CombinedSourcePreviewRequest,
    CombinedSourceSaveRequest,
    CombinedTableDescribeRequest,
    MssqlConnectionForgetRequest,
    MssqlConnectionTestRequest,
    MssqlTableListRequest,
    SourceProfileSaveRequest,
    SourceRefreshJobSubmitRequest,
    SourceTableImportRequest,
    SourceTableRefreshRequest,
)
from app_server.services import (
    combined_source_service,
    source_refresh_service,
    source_table_service,
    source_table_upload_service,
    workspace_mutation_client,
    workspace_read_client,
)

router = APIRouter()


def _source_table_settings(project_name: str) -> Dict[str, Any]:
    """The import record and master-table status, read on the server host."""
    if not str(project_name or "").strip():
        raise HTTPException(400, "project_name is required")
    return workspace_read_client.run_workspace_read(
        "source_table_settings",
        {"project_name": project_name},
        local=lambda: source_table_service.read_source_table_settings(project_name),
    )


@router.get("/source_table")
def get_source_table(project_name: str) -> Dict[str, Any]:
    try:
        settings = _source_table_settings(project_name)
        return {"ok": True, **source_table_service.get_source_table_state(project_name, settings)}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to read source table settings: {str(error)}")


@router.get("/source_table/file_status")
def get_source_table_file_status(project_name: str) -> Dict[str, Any]:
    """Live modified time and size of the external source file.

    The project's record comes from the server host; the stat of the external
    file stays here, because its path may be a drive only this PC has.
    """
    try:
        settings = _source_table_settings(project_name)
        return {"ok": True, **source_table_service.get_source_file_status(project_name, settings)}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to read the source file status: {str(error)}")


def _mutate(kind: str, kwargs: Dict[str, Any], local) -> Dict[str, Any]:
    return workspace_mutation_client.run_workspace_mutation(
        kind, kwargs, local=local
    )


@router.post("/source_table/profile")
def save_source_table_profile(req: SourceProfileSaveRequest) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"project_name": req.project_name, "source_type": req.source_type}
    if req.mssql is not None:
        kwargs["mssql"] = req.mssql.model_dump()
    if req.csv_path is not None:
        # Saved as the share it stands for: only this PC knows its drive letters.
        kwargs["csv_path"] = normalize_import_source_path(req.csv_path)
    try:
        settings = _mutate(
            "source_profile_save",
            kwargs,
            lambda: source_table_service.save_source_profile(**kwargs),
        )
        return {"ok": True, **source_table_service.get_source_table_state(req.project_name, settings)}
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to save source table settings: {str(error)}")


@router.post("/source_table/test_connection")
def test_source_table_connection(req: MssqlConnectionTestRequest) -> Dict[str, Any]:
    try:
        return source_table_service.test_mssql_connection(
            server=req.server,
            database=req.database,
            table=req.table,
            authentication=req.authentication or "",
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to test the SQL Server connection: {str(error)}")


@router.get("/source_table/connections")
def get_source_table_connections() -> Dict[str, Any]:
    """Server-shared list of previously used SQL Server server/database pairs."""
    try:
        return workspace_read_client.run_workspace_read(
            "mssql_connections",
            {},
            local=source_table_service.load_mssql_connections,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to read saved SQL Server connections: {str(error)}")


@router.post("/source_table/connections/forget")
def forget_source_table_connection(req: MssqlConnectionForgetRequest) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"server": req.server}
    if req.database is not None:
        kwargs["database"] = req.database
    try:
        return _mutate(
            "mssql_connection_forget",
            kwargs,
            lambda: source_table_service.forget_mssql_connection(**kwargs),
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to remove the saved SQL Server connection: {str(error)}")


@router.post("/source_table/tables")
def list_source_table_candidates(req: MssqlTableListRequest) -> Dict[str, Any]:
    """Tables and views available in the target database."""
    try:
        return source_table_service.list_mssql_tables(
            server=req.server,
            database=req.database,
            authentication=req.authentication or "",
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to list SQL Server tables: {str(error)}")


@router.post("/source_table/import")
def import_source_table(req: SourceTableImportRequest) -> Dict[str, Any]:
    """Read the SQL Server table as this user's login and upload it to the server."""
    return source_table_upload_service.upload_source_table(req.project_name, SOURCE_TYPE_MSSQL)


@router.post("/source_table/refresh")
def refresh_source_table(req: SourceTableRefreshRequest) -> Dict[str, Any]:
    """Read the configured CSV on this PC and upload it as the master table."""
    return source_table_upload_service.upload_source_table(req.project_name, SOURCE_TYPE_CSV)


@router.post("/source_table/combined/describe")
def describe_combined_table(req: CombinedTableDescribeRequest) -> Dict[str, Any]:
    """Columns and row count of one table of a combined source, read on this PC."""
    return combined_source_service.describe_table(req.table, req.refresh)


@router.post("/source_table/combined/preview")
def preview_combined_source(req: CombinedSourcePreviewRequest) -> Dict[str, Any]:
    """What importing the combined source would produce, without importing it."""
    return combined_source_service.preview_combined(req.project_name, req.combined, req.refresh)


@router.post("/source_table/combined/save")
def save_combined_source(req: CombinedSourceSaveRequest) -> Dict[str, Any]:
    combined = dict(req.combined)
    tables = combined.get("tables") if isinstance(combined.get("tables"), list) else []
    # Saved as the share each CSV stands for: only this PC knows its drive letters.
    combined["tables"] = [
        {**table, "csv_path": normalize_import_source_path(table.get("csv_path"))}
        if isinstance(table, dict) and table.get("source_type") != SOURCE_TYPE_MSSQL
        else table
        for table in tables
    ]
    kwargs: Dict[str, Any] = {"project_name": req.project_name, "combined": combined}
    settings = _mutate(
        "source_combined_save",
        kwargs,
        lambda: source_table_service.save_combined_source(**kwargs),
    )
    return {"ok": True, **source_table_service.get_source_table_state(req.project_name, settings)}


@router.post("/source_table/combined/import")
def import_combined_source(req: CombinedSourceImportRequest) -> Dict[str, Any]:
    """Read and join every table of the saved combined source here and upload the result."""
    return combined_source_service.import_combined(req.project_name)


@router.get("/source_table/upload_progress")
def get_source_table_upload_progress(project_name: str) -> Dict[str, Any]:
    """Bytes and rows this app's open import has uploaded so far, from memory."""
    return source_table_upload_service.get_upload_progress(project_name)


@router.get("/source_table/refresh_job/plan")
def get_source_refresh_plan(project_name: str) -> Dict[str, Any]:
    """Who imports this project's table, and whether a refresh is already running.

    The settings and the busy check are read on the server host. A CSV path
    saved in this machine's drive letters is translated here, because only
    this session has the mapping, and the translation is sent to the server
    as data to store in place of the drive letter.
    """
    try:
        settings = _source_table_settings(project_name)
        configured = str(settings.get("csv_path") or "").strip()
        csv_path = normalize_import_source_path(configured)
        rewritten = False
        if configured and csv_path != configured:
            kwargs = {"project_name": project_name, "from_path": configured, "csv_path": csv_path}
            rewritten = bool(
                _mutate(
                    "source_csv_path_rewrite",
                    kwargs,
                    lambda: source_table_service.rewrite_source_csv_path(**kwargs),
                ).get("rewritten")
            )
        status = workspace_read_client.run_workspace_read(
            "source_refresh_status",
            {"project_name": project_name},
            local=lambda: source_refresh_service.get_source_table_refresh_status(project_name),
        )
        return source_refresh_service.describe_source_refresh_plan(
            project_name,
            settings,
            status,
            csv_path=csv_path,
            csv_path_rewritten=rewritten,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, f"Failed to inspect the source refresh: {str(error)}")


@router.post("/source_table/refresh_job")
def submit_source_refresh_job(req: SourceRefreshJobSubmitRequest) -> Dict[str, Any]:
    kwargs = {
        "project_name": req.project_name,
        "request_id": req.request_id,
        "import_source": bool(req.import_source),
        "force": bool(req.force),
        "refresh_dependents": bool(req.refresh_dependents),
    }
    # A scope travels only when one was chosen: the mutation contract reads an
    # empty list arg as a malformed request, and an absent one as "everything".
    if req.dataset_types:
        kwargs["dataset_types"] = [str(name) for name in req.dataset_types]
    if req.reserving_class_types:
        kwargs["reserving_class_types"] = [
            {"Name": entry.Name, "Level": int(entry.Level)}
            for entry in req.reserving_class_types
        ]
    return _mutate(
        "source_table_refresh_submit",
        kwargs,
        lambda: source_refresh_service.submit_source_table_refresh_job(**kwargs),
    )


@router.get("/source_table/refresh_job/status")
def get_source_refresh_job_status(project_name: str, job_id: str = "") -> Dict[str, Any]:
    # Polled while the job runs; a poll the Gateway cannot answer is
    # "unknown", never a failed refresh.
    kwargs = {"project_name": project_name, "job_id": job_id}
    return workspace_read_client.run_polled_workspace_read(
        "source_refresh_status",
        kwargs,
        local=lambda: source_refresh_service.get_source_table_refresh_status(**kwargs),
        unknown={"ok": True, "project_name": project_name, "job_id": job_id, "found": False},
    )
