"""One-time move of a user's settings, chats and dashboards from this PC to the server.

Before the per-user server folder existed (`server_user_profile_service`), each
of these was a file on the PC. On every start the desktop host asks for this
import; whatever is still on the PC is sent to the server and then removed from
the PC, so a later start finds nothing left to do. The server's copy wins when
both exist: another PC of the same user got there first.

Nothing here opens the share. A server that cannot be reached leaves every
local file where it is for the next start.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from app_server import config
from app_server.services import (
    arcbot_chat_store_service,
    dashboard_service,
    scripting_preferences_service,
    server_user_profile_service,
    workspace_mutation_client,
    workspace_read_client,
)

# Preference section -> the file under ``%APPDATA%\Arco`` that used to hold it.
LEGACY_PREFERENCE_FILES: Dict[str, tuple[str, ...]] = {
    "macros": ("prefs", "macro_prefs.json"),
    "flightDeck": ("prefs", "flight_deck.json"),
    "notesPanel": ("prefs", "notes_panel_prefs.json"),
    "tableColors": ("prefs", "table_colors.json"),
    "scriptingShortcuts": ("prefs", "scripting_shortcuts.json"),
    "arcbotUi": ("prefs", "arcbot_ui_settings.json"),
    scripting_preferences_service.SHELL_SECTION: ("local_project_prefs.json",),
    scripting_preferences_service.SCRIPTING_SECTION: ("cache", "scripting_prefs.json"),
}
LEGACY_CHAT_SESSIONS_DIR = "arcbot_chat_sessions"
LEGACY_DASHBOARDS_DIR = "dashboards"


def _read_object(path: Path) -> Dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _files(folder: Path, suffix: str) -> List[Path]:
    try:
        return sorted(entry for entry in folder.iterdir() if entry.is_file() and entry.suffix.lower() == suffix)
    except OSError:
        return []


def _read(kind: str, local: Any) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(kind, {}, local=local)


def _change(kind: str, kwargs: Dict[str, Any], local: Any) -> Dict[str, Any]:
    return workspace_mutation_client.run_workspace_mutation(kind, kwargs, local=lambda: local(**kwargs))


def _import_preferences(appdata_dir: Path) -> int:
    found = {
        section: appdata_dir.joinpath(*parts)
        for section, parts in LEGACY_PREFERENCE_FILES.items()
        if appdata_dir.joinpath(*parts).is_file()
    }
    if not found:
        return 0
    stored = _read("user_preferences", server_user_profile_service.get_preferences)["data"]
    patch = {}
    for section, path in found.items():
        data = _read_object(path)
        if data is not None and section not in stored:
            patch[section] = data
    if patch:
        _change("user_preferences_update", {"patch": patch}, server_user_profile_service.update_preferences)
    for path in found.values():
        path.unlink()
    return len(patch)


def _import_chats(profile_dir: Path) -> int:
    files = _files(profile_dir / LEGACY_CHAT_SESSIONS_DIR, ".json")
    if not files:
        return 0
    listing = _read("arcbot_chat_sessions", arcbot_chat_store_service.list_chat_sessions)
    stored = {session["id"] for session in listing["sessions"]}
    sent = 0
    for path in files:
        session = _read_object(path)
        if session is not None and session.get("id") == path.stem and path.stem not in stored:
            _change("arcbot_chat_session_save", {"session": session}, arcbot_chat_store_service.save_chat_session)
            sent += 1
        path.unlink()
    return sent


def _import_dashboards(documents_dir: Path) -> int:
    """Send each dashboard and library item; one whose name the server already holds stays on the PC."""

    folder = documents_dir / LEGACY_DASHBOARDS_DIR
    dashboards = _files(folder, config.DASHBOARD_EXT)
    assets = _files(folder / config.DASHBOARD_LIBRARY_SUBDIR, ".json")
    if not dashboards and not assets:
        return 0
    sent = 0
    listing = _read("dashboard_user_list", dashboard_service.list_user_dashboards)
    stored = {str(item["path"]).casefold() for item in listing["dashboards"]}
    for path in dashboards:
        data = _read_object(path)
        if data is None or data.get("format") != dashboard_service.DASHBOARD_FORMAT or path.name.casefold() in stored:
            continue
        kwargs = {"name": path.stem, "data": data, "prev_name": "", "overwrite": False}
        saved = _change("dashboard_user_save", kwargs, dashboard_service.save_user_dashboard)
        stored.add(str(saved["path"]).casefold())
        path.unlink()
        sent += 1
    library = _read("dashboard_user_library", dashboard_service.list_user_library)
    stored_assets = {str(asset["id"]).casefold() for asset in library["assets"]}
    for path in assets:
        data = _read_object(path)
        asset_id = f"{dashboard_service.USER_ASSET_PREFIX}{path.stem}".casefold()
        if data is None or not isinstance(data.get("widget"), dict) or asset_id in stored_assets:
            continue
        kwargs = {
            "name": str(data.get("name") or path.stem),
            "widget": data["widget"],
            "category": str(data.get("category") or ""),
            "description": str(data.get("description") or ""),
        }
        _change("dashboard_user_library_save", kwargs, dashboard_service.save_user_library_asset)
        path.unlink()
        sent += 1
    return sent


def import_local_profile(profile_dir: str) -> Dict[str, Any]:
    """Send what this PC still holds to the user's server folder.

    *profile_dir* is the desktop host's own data folder, where the chats were.
    """

    return {
        "ok": True,
        "preferences": _import_preferences(Path(config._get_user_appdata_dir())),
        "chats": _import_chats(Path(str(profile_dir or ""))) if str(profile_dir or "").strip() else 0,
        "dashboards": _import_dashboards(Path(config._get_user_documents_dir())),
    }
