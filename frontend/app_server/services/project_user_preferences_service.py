"""Per-project, per-Windows-user preferences stored on the server root.

A Client PC reads and writes them through the Gateway, where the login is the
one the request is signed with (the acting identity), never a payload field.
"""
from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

from fastapi import HTTPException

from app_server import config
from app_server.services import user_identity_service

USER_PREFS_FILE = config.PROJECT_USER_PREFERENCES_FILE
_PREFERENCES_WRITE_LOCKS: Dict[str, threading.Lock] = {}
_PREFERENCES_WRITE_LOCKS_GUARD = threading.Lock()
_PREFERENCES_WRITE_LOCK_TIMEOUT_SECONDS = 5.0
_WINDOWS_LOCK_ERRORS = {32, 33}
_PREFERENCES_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.35, 0.5)


def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _safe_folder_name(value: str, fallback: str = "unknown") -> str:
    cleaned = config.encode_filename_segment(_clean_text(value))
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned or fallback


def _current_user_name() -> str:
    return _safe_folder_name(user_identity_service.get_windows_login_name() or "unknown")


def _require_project_dir(project_name: str) -> str:
    project = _clean_text(project_name)
    if not project:
        raise HTTPException(400, "project_name is required.")
    project_dir = config._find_existing_project_dir(project)
    if not project_dir:
        raise HTTPException(404, f"Project folder not found under projects: {project}")
    return project_dir


def _prefs_path(project_name: str) -> str:
    project_dir = _require_project_dir(project_name)
    return os.path.join(project_dir, "users", _current_user_name(), USER_PREFS_FILE)


def _get_preferences_write_lock(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _PREFERENCES_WRITE_LOCKS_GUARD:
        lock = _PREFERENCES_WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PREFERENCES_WRITE_LOCKS[key] = lock
        return lock


def _is_file_lock_error(err: OSError) -> bool:
    return getattr(err, "winerror", None) in _WINDOWS_LOCK_ERRORS or isinstance(err, PermissionError)


def _unique_preferences_temp_path(path: str) -> str:
    return (
        f"{path}."
        f"{os.getpid()}."
        f"{threading.get_ident()}."
        f"{time.monotonic_ns()}.tmp"
    )


def _replace_preferences_with_retry(temp_path: str, path: str) -> None:
    for delay in (*_PREFERENCES_REPLACE_RETRY_DELAYS, None):
        try:
            os.replace(temp_path, path)
            return
        except OSError as err:
            if delay is None or not _is_file_lock_error(err):
                raise
            time.sleep(delay)


def _write_preferences_file(path: str, data: Dict[str, Any]) -> None:
    temp_path = _unique_preferences_temp_path(path)
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        _replace_preferences_with_retry(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_json_for_update(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except PermissionError as err:
        raise HTTPException(
            423,
            f"Project user preferences are locked or inaccessible: {str(err)}",
        ) from err
    except OSError as err:
        raise HTTPException(500, f"Failed to read project user preferences: {str(err)}") from err
    except json.JSONDecodeError as err:
        raise HTTPException(
            409,
            f"Project user preferences contain invalid JSON; no changes were written: {str(err)}",
        ) from err
    if not isinstance(data, dict):
        raise HTTPException(
            409,
            "Project user preferences must contain a JSON object; no changes were written.",
        )
    return data


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _extract_last_reserving_class_path(data: Dict[str, Any]) -> str:
    for key in ("lastReservingClassPath", "last_reserving_class_path"):
        value = _clean_text(data.get(key))
        if value:
            return value
    for section_key in ("datasetViewer", "dfmObject"):
        section = data.get(section_key)
        if not isinstance(section, dict):
            continue
        for key in ("reservingClass", "reserving_class", "path"):
            value = _clean_text(section.get(key))
            if value:
                return value
    return ""


def _normalize_project_user_preferences(data: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(data if isinstance(data, dict) else {})
    last_path = _extract_last_reserving_class_path(out)
    if last_path:
        out["lastReservingClassPath"] = last_path
    out.pop("last_reserving_class_path", None)

    for section_key in ("datasetViewer", "dfmObject"):
        section = out.get(section_key)
        if not isinstance(section, dict):
            continue
        cleaned = dict(section)
        for key in ("reservingClass", "reserving_class", "path"):
            cleaned.pop(key, None)
        out[section_key] = cleaned

    reserving_class_tree = out.get("reservingClassTree")
    if isinstance(reserving_class_tree, dict):
        cleaned_tree = dict(reserving_class_tree)
        preferences = cleaned_tree.get("preferences")
        if isinstance(preferences, dict):
            cleaned_preferences = dict(preferences)
            cleaned_preferences.pop("auto_close_on_select", None)
            cleaned_preferences.pop("autoCloseOnSelect", None)
            cleaned_tree["preferences"] = cleaned_preferences
        out["reservingClassTree"] = cleaned_tree
    return out


def _read_project_instance_defaults() -> Dict[str, Any]:
    defaults = _read_json(config.get_project_instance_default_preferences_path())
    project_instance = defaults.get("projectInstance")
    return deepcopy(project_instance) if isinstance(project_instance, dict) else {}


def _read_project_settings_defaults() -> Dict[str, Any]:
    defaults = _read_json(config.get_project_settings_default_preferences_path())
    project_settings = defaults.get("projectSettings")
    return deepcopy(project_settings) if isinstance(project_settings, dict) else {}


def _with_project_instance_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    project_instance = data.get("projectInstance")
    if isinstance(project_instance, dict) and project_instance:
        return data

    defaults = _read_project_instance_defaults()
    if not defaults:
        return data

    out = dict(data)
    out["projectInstance"] = defaults
    return out


def _with_project_settings_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    """Lay the user's saved Project Settings values over the admin defaults.

    A user who sized one table's columns still gets the defaults for every
    other table and column they have not touched.
    """
    defaults = _read_project_settings_defaults()
    if not defaults:
        return data

    project_settings = data.get("projectSettings")
    out = dict(data)
    out["projectSettings"] = _deep_merge(defaults, project_settings if isinstance(project_settings, dict) else {})
    return out


def get_preferences(project_name: str) -> Dict[str, Any]:
    path = _prefs_path(project_name)
    data = _normalize_project_user_preferences(_read_json(path))
    data = _with_project_instance_defaults(data)
    data = _with_project_settings_defaults(data)
    return {
        "ok": True,
        "project_name": _clean_text(project_name),
        "user_name": _current_user_name(),
        "path": path,
        "data": data,
    }


def _replace_whole_values(merged: Dict[str, Any], patch: Dict[str, Any], whole_values: Iterable[Tuple[str, ...]]) -> None:
    for key_path in whole_values:
        target, source = merged, patch
        for key in key_path[:-1]:
            target, source = target[key], source[key]
        target[key_path[-1]] = deepcopy(source[key_path[-1]])


def update_preferences(
    project_name: str,
    patch: Optional[Dict[str, Any]] = None,
    whole_values: Iterable[Tuple[str, ...]] = (),
) -> Dict[str, Any]:
    """Merge *patch* into the signed-in user's preference file.

    Each value the patch names replaces the stored one, and nested objects are
    merged key by key, so applying the same patch again lands the same state
    (only ``updated_at`` moves). A key path listed in *whole_values* is
    replaced outright instead of merged, so keys it no longer holds are
    dropped.
    """
    if patch is None:
        patch = {}
    if not isinstance(patch, dict):
        raise HTTPException(400, "data must be an object.")
    path = _prefs_path(project_name)
    lock = _get_preferences_write_lock(path)
    if not lock.acquire(timeout=_PREFERENCES_WRITE_LOCK_TIMEOUT_SECONDS):
        raise HTTPException(423, "Project user preferences are busy. Please retry.")
    try:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            current = _read_json_for_update(path)
            merged = _deep_merge(current, patch)
            _replace_whole_values(merged, patch, whole_values)
            next_data = _normalize_project_user_preferences(merged)
            next_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _write_preferences_file(path, next_data)
        except HTTPException:
            raise
        except PermissionError as err:
            raise HTTPException(
                423,
                f"Project user preferences are locked or inaccessible: {str(err)}",
            ) from err
        except OSError as err:
            raise HTTPException(500, f"Failed to write project user preferences: {str(err)}") from err
    finally:
        lock.release()
    return {
        "ok": True,
        "project_name": _clean_text(project_name),
        "user_name": _current_user_name(),
        "path": path,
        "data": next_data,
    }
