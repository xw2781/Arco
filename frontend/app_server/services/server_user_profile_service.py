"""The signed-in user's own folder on the Arco Server, and the preferences in it.

Everything a user keeps that is neither one project's nor one PC's lives under
``<workspace_root>\\users\\<encoded-windows-login>``: ``preferences.json`` here,
the ArcBot chats (``arcbot_chat_store_service``) and the saved dashboards
(``dashboard_service``). A Client PC reaches it only through the Gateway, where
the login is the one the request is signed with (the acting identity), never a
payload field, so a user can read and write only their own folder.

``preferences.json`` holds one section per preference, each read and written
whole. A save replaces the sections it names and leaves the others alone, so
two windows saving different sections never erase each other.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import HTTPException

from app_server import config
from app_server.services import project_user_preferences_service as _files


def user_folder(*parts: str) -> str:
    """This user's folder on the server, or a path under it."""

    return os.path.join(
        config.get_path(config.SERVER_USERS_DIR), _files._current_user_name(), *parts
    )


def _preferences_path() -> str:
    return user_folder(config.SERVER_USER_PREFERENCES_FILE)


def get_preferences() -> Dict[str, Any]:
    """Every preference section this user has saved."""

    return {"ok": True, "data": _files._read_json(_preferences_path())}


def get_section(name: str) -> Any:
    """One section as stored, or ``None`` when the user never saved it."""

    return _files._read_json(_preferences_path()).get(name)


def update_preferences(patch: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Replace each section *patch* names; a section set to ``None`` is removed.

    Applying the same patch again lands the same state; only ``updated_at``
    moves.
    """

    if patch is None:
        patch = {}
    if not isinstance(patch, dict):
        raise HTTPException(400, "data must be an object.")
    path = _preferences_path()
    lock = _files._get_preferences_write_lock(path)
    if not lock.acquire(timeout=_files._PREFERENCES_WRITE_LOCK_TIMEOUT_SECONDS):
        raise HTTPException(423, "Your preferences are busy. Please retry.")
    try:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            data = _files._read_json_for_update(path)
            for name, value in patch.items():
                if value is None:
                    data.pop(name, None)
                else:
                    data[name] = value
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _files._write_preferences_file(path, data)
        except HTTPException:
            raise
        except PermissionError as err:
            raise HTTPException(423, f"Your preferences are locked or inaccessible: {err}") from err
        except OSError as err:
            raise HTTPException(500, f"Failed to write your preferences: {err}") from err
    finally:
        lock.release()
    return {"ok": True, "data": data}
