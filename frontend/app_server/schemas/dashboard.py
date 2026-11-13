from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel


class DashboardLoadRequest(BaseModel):
    path: str


class DashboardSaveRequest(BaseModel):
    name: str
    data: Dict[str, Any]
    prev_path: str = ""
    overwrite: bool = False


class DashboardDeleteRequest(BaseModel):
    path: str


class DashboardLibrarySaveRequest(BaseModel):
    name: str
    widget: Dict[str, Any]
    category: str = ""
    description: str = ""


class DashboardLibraryDeleteRequest(BaseModel):
    id: str


class DashboardSourceRequest(BaseModel):
    source: Dict[str, Any]
