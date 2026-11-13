from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app_server.schemas.dashboard import (
    DashboardDeleteRequest,
    DashboardLibraryDeleteRequest,
    DashboardLibrarySaveRequest,
    DashboardLoadRequest,
    DashboardSaveRequest,
    DashboardSourceRequest,
)
from app_server.services import dashboard_service


router = APIRouter()


@router.get("/dashboard/list")
def dashboard_list() -> Dict[str, Any]:
    return dashboard_service.list_dashboards()


@router.post("/dashboard/load")
def dashboard_load(req: DashboardLoadRequest) -> Dict[str, Any]:
    return dashboard_service.load_dashboard(req.path)


@router.post("/dashboard/save")
def dashboard_save(req: DashboardSaveRequest) -> Dict[str, Any]:
    return dashboard_service.save_dashboard(req.name, req.data, req.prev_path, req.overwrite)


@router.post("/dashboard/delete")
def dashboard_delete(req: DashboardDeleteRequest) -> Dict[str, Any]:
    return dashboard_service.delete_dashboard(req.path)


@router.get("/dashboard/library")
def dashboard_library() -> Dict[str, Any]:
    return dashboard_service.list_library()


@router.post("/dashboard/library/save")
def dashboard_library_save(req: DashboardLibrarySaveRequest) -> Dict[str, Any]:
    return dashboard_service.save_library_asset(req.name, req.widget, req.category, req.description)


@router.post("/dashboard/library/delete")
def dashboard_library_delete(req: DashboardLibraryDeleteRequest) -> Dict[str, Any]:
    return dashboard_service.delete_library_asset(req.id)


@router.post("/dashboard/source/load")
def dashboard_source_load(req: DashboardSourceRequest) -> Dict[str, Any]:
    return dashboard_service.load_source(req.source)


@router.post("/dashboard/source/fields")
def dashboard_source_fields(req: DashboardSourceRequest) -> Dict[str, Any]:
    return dashboard_service.source_fields(req.source)
