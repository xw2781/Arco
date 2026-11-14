from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel


class UserPreferenceSectionSaveRequest(BaseModel):
    preferences: Dict[str, Any]


class ArcBotChatSessionIdRequest(BaseModel):
    session_id: str


class ArcBotChatSessionSaveRequest(BaseModel):
    session: Dict[str, Any]


class LocalProfileImportRequest(BaseModel):
    profile_dir: str = ""
