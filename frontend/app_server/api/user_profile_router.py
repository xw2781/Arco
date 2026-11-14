"""The signed-in user's own preferences and ArcBot chats.

Each runs on the server host through the Gateway for the login the request is
signed with; a Client PC answers 401 or 503 rather than touching the user's
folder over the share. The desktop host is the caller: it holds no preference
or chat file of its own for these.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app_server.schemas.user_profile import (
    ArcBotChatSessionIdRequest,
    ArcBotChatSessionSaveRequest,
    LocalProfileImportRequest,
    UserPreferenceSectionSaveRequest,
)
from app_server.services import (
    arcbot_chat_store_service,
    local_profile_import_service,
    server_user_profile_service,
    workspace_mutation_client,
    workspace_read_client,
)

router = APIRouter()


@router.get("/user-preferences/{section}")
def get_user_preference_section(section: str) -> Dict[str, Any]:
    stored = workspace_read_client.run_workspace_read(
        "user_preferences", {}, local=server_user_profile_service.get_preferences
    )["data"].get(section)
    exists = isinstance(stored, dict)
    return {"ok": True, "exists": exists, "preferences": stored if exists else {}}


@router.post("/user-preferences/{section}")
def save_user_preference_section(section: str, req: UserPreferenceSectionSaveRequest) -> Dict[str, Any]:
    if section == "updated_at":
        raise HTTPException(400, "Not a preference section.")
    kwargs = {"patch": {section: dict(req.preferences)}}
    workspace_mutation_client.run_workspace_mutation(
        "user_preferences_update",
        kwargs,
        local=lambda: server_user_profile_service.update_preferences(**kwargs),
    )
    return {"ok": True, "preferences": kwargs["patch"][section]}


@router.get("/arcbot/chat-sessions")
def list_arcbot_chat_sessions() -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "arcbot_chat_sessions", {}, local=arcbot_chat_store_service.list_chat_sessions
    )


@router.post("/arcbot/chat-session/load")
def load_arcbot_chat_session(req: ArcBotChatSessionIdRequest) -> Dict[str, Any]:
    kwargs = {"session_id": req.session_id}
    return workspace_read_client.run_workspace_read(
        "arcbot_chat_session",
        kwargs,
        local=lambda: arcbot_chat_store_service.read_chat_session(**kwargs),
    )


@router.post("/arcbot/chat-session/save")
def save_arcbot_chat_session(req: ArcBotChatSessionSaveRequest) -> Dict[str, Any]:
    kwargs = {"session": dict(req.session)}
    return workspace_mutation_client.run_workspace_mutation(
        "arcbot_chat_session_save",
        kwargs,
        local=lambda: arcbot_chat_store_service.save_chat_session(**kwargs),
    )


@router.post("/arcbot/chat-session/delete")
def delete_arcbot_chat_session(req: ArcBotChatSessionIdRequest) -> Dict[str, Any]:
    kwargs = {"session_id": req.session_id}
    return workspace_mutation_client.run_workspace_mutation(
        "arcbot_chat_session_delete",
        kwargs,
        local=lambda: arcbot_chat_store_service.delete_chat_session(**kwargs),
    )


@router.post("/user-profile/import-local")
def import_local_profile(req: LocalProfileImportRequest) -> Dict[str, Any]:
    return local_profile_import_service.import_local_profile(req.profile_dir)
