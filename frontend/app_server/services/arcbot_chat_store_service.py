"""The signed-in user's ArcBot chats, kept in their folder on the Arco Server.

One chat is one JSON file under ``users\\<login>\\arcbot\\sessions``, stored as
the desktop host sends it; the host owns the chat's shape. They live on the
server so a chat follows its user to another PC and so the team maintaining
ArcBot can read what a conversation actually contained.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List

from fastapi import HTTPException

from arcrho_api.io import persisted_json_text

from app_server import config
from app_server.services import server_user_profile_service


_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def _sessions_dir() -> str:
    return server_user_profile_service.user_folder(*config.SERVER_USER_ARCBOT_SESSIONS_SUBPATH)


def _session_path(session_id: Any) -> str:
    text = str(session_id or "")
    if not _SESSION_ID.fullmatch(text):
        raise HTTPException(400, "Not an ArcBot chat id.")
    return os.path.join(_sessions_dir(), f"{text}.json")


def _read(path: str) -> Dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_chat_sessions() -> Dict[str, Any]:
    """Every chat's summary; the caller sorts and filters them."""

    try:
        names = os.listdir(_sessions_dir())
    except OSError:
        names = []
    sessions: List[Dict[str, Any]] = []
    for name in names:
        stem, extension = os.path.splitext(name)
        if extension.lower() != ".json" or not _SESSION_ID.fullmatch(stem):
            continue
        session = _read(os.path.join(_sessions_dir(), name))
        if not session or session.get("id") != stem:
            continue
        messages = session.get("messages")
        sessions.append(
            {
                "id": stem,
                "title": str(session.get("title") or ""),
                "updatedAt": str(session.get("updatedAt") or ""),
                "createdAt": str(session.get("createdAt") or ""),
                "messageCount": len(messages) if isinstance(messages, list) else 0,
                "archived": session.get("archived") is True,
            }
        )
    return {"ok": True, "sessions": sessions}


def read_chat_session(session_id: str) -> Dict[str, Any]:
    """One chat as stored; ``session`` is ``None`` when there is no such chat."""

    return {"ok": True, "session": _read(_session_path(session_id))}


def save_chat_session(session: Dict[str, Any]) -> Dict[str, Any]:
    """Store one chat whole under its own id."""

    if not isinstance(session, dict):
        raise HTTPException(400, "session must be an object.")
    path = _session_path(session.get("id"))
    temp_path = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(persisted_json_text(session))
        os.replace(temp_path, path)
    except OSError as error:
        raise HTTPException(500, f"The chat could not be saved: {error}") from error
    return {"ok": True, "id": session["id"]}


def delete_chat_session(session_id: str) -> Dict[str, Any]:
    """Remove one chat; a chat already gone answers ``deleted: false``."""

    try:
        os.remove(_session_path(session_id))
    except FileNotFoundError:
        return {"ok": True, "deleted": False}
    except OSError as error:
        raise HTTPException(500, f"The chat could not be deleted: {error}") from error
    return {"ok": True, "deleted": True}
