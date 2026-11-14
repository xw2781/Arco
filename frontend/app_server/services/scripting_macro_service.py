"""Macro engine for Arco scripting.

Owns macro metadata parsing, macro file storage, task-wrapper generation,
active-DFM context binding, and sandboxed macro source execution. Shares the
cancellation/timeout toolkit with the scripting console session engine in
scripting_service.
"""
from __future__ import annotations

import ast
import builtins
import copy
import inspect
import io
import json
import os
import re
import sys
import threading
import time as py_time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app_server import config
from app_server.services.scripting_service import (
    _ensure_arcrho_api_import_path,
    _ExecutionActivity,
    _initialize_macro_com_apartment,
    _make_cooperative_cancel_checker,
    _make_scoped_cancel_trace,
    _make_session_import_hook,
    _make_trusted_macro_call,
    _run_with_timeout,
)

# ---------------------------------------------------------------------------
# User macros
# ---------------------------------------------------------------------------

_MACRO_META_BEGIN = "# <arcrho-macro>"
_MACRO_META_END = "# </arcrho-macro>"
_MAX_MACRO_SOURCE_CHARS = 2_000_000
_MACRO_TIMEOUT_SEC = 120
_MACRO_REVIEW_TIMEOUT_SEC = 120.0
_MACRO_REVIEW_EXPIRY_BUFFER_SEC = 5.0
_MACRO_EXECUTION_LOCK = threading.Lock()
_MACRO_SCOPE_LABELS = {
    "dfm": "DFM",
    "result selection": "Result Selection",
    "result_selection": "Result Selection",
    "restult selection": "Result Selection",
    "reserving class": "Reserving Class",
    "reserving_class": "Reserving Class",
    "project": "Project",
}


# A macro may name the Flight Deck glyph a button made from it should start with. The catalog of
# names lives with the deck, so this only keeps the shape of a name and lets the deck decide
# whether it knows one.
_MACRO_ICON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


def _normalize_macro_icon(value: Any) -> str:
    name = re.sub(r"\s+", "", str(value or "").strip().lower())
    return name if _MACRO_ICON_PATTERN.match(name) else ""


def _normalize_macro_scopes(value: Any) -> List[str]:
    parts = re.split(r"[,;/|]+", str(value or ""))
    scopes: List[str] = []
    seen: Set[str] = set()
    for part in parts:
        key = re.sub(r"\s+", " ", str(part or "").strip().lower())
        label = _MACRO_SCOPE_LABELS.get(key)
        if not label or label in seen:
            continue
        seen.add(label)
        scopes.append(label)
    return scopes or ["DFM"]


def _get_macros_dir() -> str:
    macro_dir = str(getattr(config, "MACRO_DIR", "") or "").strip() or config._get_macro_dir()
    os.makedirs(macro_dir, exist_ok=True)
    return macro_dir


def _parse_macro_metadata(text: str, filename: str) -> Dict[str, Any]:
    title = os.path.splitext(os.path.basename(filename))[0].replace("_", " ").title()
    description_parts: List[str] = []
    generated = ""
    scope_text = ""
    icon_text = ""
    version = ""
    release_note = ""
    active_key = ""
    in_block = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line == _MACRO_META_BEGIN:
            in_block = True
            continue
        if line == _MACRO_META_END:
            break
        if not in_block:
            continue
        if line.startswith("#"):
            line = line[1:].strip()
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "title" and value:
                title = value
                active_key = "title"
                continue
            if key == "description":
                description_parts = [value] if value else []
                active_key = "description"
                continue
            if key == "generated":
                generated = value
                active_key = "generated"
                continue
            if key == "scope":
                scope_text = value
                active_key = "scope"
                continue
            if key == "icon":
                icon_text = value
                active_key = "icon"
                continue
            if key == "version":
                version = value
                active_key = "version"
                continue
            if key == "release note":
                release_note = value
                active_key = "release note"
                continue
        if active_key == "description" and line:
            description_parts.append(line)
            continue
        active_key = ""
    description = " ".join(part for part in description_parts if part).strip()
    scopes = _normalize_macro_scopes(scope_text)
    return {
        "title": title,
        "description": description,
        "generated": generated,
        "scope": scopes[0],
        "scopes": scopes,
        "icon": _normalize_macro_icon(icon_text),
        "version": version,
        "release_note": release_note,
    }


def _parse_task_wrapper_tasks(text: str) -> List[Dict[str, str]]:
    try:
        tree = ast.parse(str(text or ""))
    except SyntaxError:
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "TASKS" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            return []
        tasks: List[Dict[str, str]] = []
        for index, item in enumerate(value if isinstance(value, list) else []):
            if not isinstance(item, dict):
                continue
            macro_id = os.path.basename(str(item.get("macro_id") or item.get("macroId") or "").strip().replace("\\", "/"))
            if not macro_id:
                continue
            if not macro_id.lower().endswith(".py"):
                macro_id = f"{macro_id}.py"
            task_id = str(item.get("task_id") or item.get("taskId") or "").strip() or f"task_{index + 1}"
            tasks.append({
                "macro_id": macro_id,
                "task_id": task_id,
                "name": str(item.get("name") or os.path.splitext(macro_id)[0]).strip(),
                "description": str(item.get("description") or "").strip(),
            })
        return tasks
    return []


def _safe_macro_path(macro_id: str) -> str:
    macro_dir = os.path.abspath(_get_macros_dir())
    safe_name = os.path.basename(str(macro_id or "").strip().replace("\\", "/"))
    if not safe_name:
        raise ValueError("Macro id is required.")
    if not safe_name.lower().endswith(".py"):
        safe_name = f"{safe_name}.py"
    path = os.path.abspath(os.path.join(macro_dir, safe_name))
    if not (path == macro_dir or path.startswith(macro_dir + os.sep)):
        raise ValueError("Macro path is outside the macros directory.")
    return path


def list_macros() -> List[Dict[str, Any]]:
    macro_dir = _get_macros_dir()
    result: List[Dict[str, Any]] = []
    for entry in sorted(os.listdir(macro_dir)):
        if not entry.lower().endswith(".py"):
            continue
        path = os.path.join(macro_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
            meta = _parse_macro_metadata(text, entry)
            wrapper_tasks = _parse_task_wrapper_tasks(text)
            is_task_wrapper = (
                "task designer wrapper" in str(meta.get("generated") or "").lower()
                or "TASK_DESIGNER_WRAPPER = True" in text
                or bool(wrapper_tasks)
            )
            stat = os.stat(path)
            result.append({
                "id": entry,
                "name": meta["title"],
                "description": meta["description"],
                "scope": meta["scope"],
                "scopes": meta["scopes"],
                "icon": meta["icon"],
                "version": meta["version"],
                "path": path,
                "modified": str(int(stat.st_mtime)),
                "builtin": False,
                "task_designer_wrapper": is_task_wrapper,
                "tasks": wrapper_tasks if is_task_wrapper else [],
            })
        except OSError:
            continue
    return result


def delete_macro(macro_id: str) -> Dict[str, Any]:
    path = _safe_macro_path(macro_id)
    if not os.path.isfile(path):
        return {"success": False, "message": f"Macro not found: {macro_id}"}
    try:
        os.remove(path)
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": f"Deleted macro: {os.path.basename(path)}"}


def rename_macro(macro_id: str, new_name: str) -> Dict[str, Any]:
    old_path = _safe_macro_path(macro_id)
    if not os.path.isfile(old_path):
        return {"success": False, "message": f"Macro not found: {macro_id}"}
    raw_name = os.path.basename(str(new_name or "").strip().replace("\\", "/"))
    if raw_name.lower().endswith(".py"):
        raw_name = raw_name[:-3]
    safe_stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw_name).strip(" ._-")
    safe_stem = re.sub(r"\s+", "_", safe_stem)
    if not safe_stem:
        return {"success": False, "message": "New macro name is required."}
    new_path = _safe_macro_path(f"{safe_stem}.py")
    if os.path.abspath(new_path) == os.path.abspath(old_path):
        return {
            "success": True,
            "message": f"Macro name is unchanged: {os.path.basename(old_path)}",
            "macro_id": os.path.basename(old_path),
            "path": old_path,
        }
    if os.path.exists(new_path):
        return {"success": False, "message": f"Macro already exists: {os.path.basename(new_path)}"}
    try:
        os.rename(old_path, new_path)
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {
        "success": True,
        "message": f"Renamed macro to: {os.path.basename(new_path)}",
        "macro_id": os.path.basename(new_path),
        "path": new_path,
    }


def _safe_generated_macro_filename(title: str, filename: str = "") -> str:
    raw = str(filename or "").strip() or str(title or "").strip() or "Task Designer Wrapper"
    raw = os.path.basename(raw.replace("\\", "/"))
    if raw.lower().endswith(".py"):
        raw = raw[:-3]
    slug = re.sub(r"[^A-Za-z0-9._ -]+", "_", raw).strip(" ._-")
    slug = re.sub(r"[\s-]+", "_", slug)
    if not slug:
        slug = "task_designer_wrapper"
    if not slug.lower().startswith("task_"):
        slug = f"task_{slug}"
    return f"{slug}.py"


def _normalize_wrapper_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for index, task in enumerate(tasks if isinstance(tasks, list) else []):
        if not isinstance(task, dict):
            continue
        macro_id = os.path.basename(str(task.get("macro_id") or task.get("macroId") or "").strip().replace("\\", "/"))
        if not macro_id:
            continue
        if not macro_id.lower().endswith(".py"):
            macro_id = f"{macro_id}.py"
        task_id = str(task.get("task_id") or task.get("taskId") or "").strip() or f"task_{index + 1}"
        task_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id).strip("._-") or f"task_{index + 1}"
        normalized.append({
            "macro_id": macro_id,
            "task_id": task_id,
            "name": str(task.get("name") or os.path.splitext(macro_id)[0]).strip(),
            "description": str(task.get("description") or "").strip(),
        })
    return normalized


def _build_task_wrapper_source(title: str, description: str, tasks: List[Dict[str, str]]) -> str:
    clean_title = str(title or "Task Designer Wrapper").strip() or "Task Designer Wrapper"
    clean_description = str(description or "").strip()
    header_title = re.sub(r"[\r\n]+", " ", clean_title)
    header_description = re.sub(r"[\r\n]+", " ", clean_description or "Generated Task Designer wrapper macro.")
    tasks_json = json.dumps(tasks, indent=2, ensure_ascii=False)
    return f'''# <arcrho-macro>
# Title: {header_title}
# Description: {header_description}
# Generated: Task Designer wrapper
# </arcrho-macro>

TASK_DESIGNER_WRAPPER = True
TASKS = {tasks_json}


def _fallback_task_designer():
    try:
        from arcrho_api import ui as arcrho_ui
        return arcrho_ui.task_designer
    except Exception as exc:
        print(f"Task Designer API is not available: {{exc}}")
        return None


def _safe_task_call(designer, method_name, *args, **kwargs):
    if designer is None:
        return None
    method = getattr(designer, method_name, None)
    if not callable(method):
        return None
    try:
        return method(*args, **kwargs)
    except Exception as exc:
        print(f"Task Designer {{method_name}} failed: {{exc}}")
        return None


def _task_message(result):
    parts = []
    if isinstance(result, dict):
        for key in ("message", "stdout"):
            value = str(result.get(key) or "").strip()
            if value and value not in parts:
                parts.append(value)
    return "\\n".join(parts)


def run_macro(active_dfm=None, active_context=None):
    """Run child macros sequentially and report each child as a Task Designer row."""
    injected_designer = globals().get("task_designer")
    designer = injected_designer or _fallback_task_designer()
    wrapper_owns_rows = injected_designer is None

    _safe_task_call(designer, "open", title={clean_title!r}, context="Active DFM validation")

    failures = 0
    for task in TASKS:
        task_id = task.get("task_id", "")
        if wrapper_owns_rows:
            _safe_task_call(designer, "register_task", task_id, task.get("name", ""), task.get("description", ""))
            _safe_task_call(designer, "start_task", task_id)
        result = run_task_macro(
            task.get("macro_id", ""),
            task_id=task_id,
            name=task.get("name", ""),
            description=task.get("description", ""),
        )
        success = bool(isinstance(result, dict) and result.get("success"))
        if not success:
            failures += 1
        if wrapper_owns_rows:
            _safe_task_call(
                designer,
                "complete_task",
                task_id,
                "pass" if success else "error",
                message=_task_message(result),
            )
    if failures:
        return {{"success": False, "message": f"Task Designer wrapper completed with {{failures}} failing task(s)."}}
    return {{"success": True, "message": f"Task Designer wrapper completed {{len(TASKS)}} macro(s)."}}
'''


def save_task_wrapper_macro(
    title: str,
    description: str = "",
    filename: str = "",
    tasks: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    normalized_tasks = _normalize_wrapper_tasks(tasks or [])
    if not normalized_tasks:
        return {"success": False, "message": "Add at least one macro before saving a wrapper."}
    for task in normalized_tasks:
        path = _safe_macro_path(task["macro_id"])
        if not os.path.isfile(path):
            return {"success": False, "message": f"Child macro not found: {task['macro_id']}"}
    safe_name = _safe_generated_macro_filename(title, filename)
    path = _safe_macro_path(safe_name)
    source = _build_task_wrapper_source(title, description, normalized_tasks)
    if os.path.isfile(path):
        try:
            existing = Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            return {"success": False, "message": str(exc)}
        if "Generated: Task Designer wrapper" not in existing:
            return {
                "success": False,
                "message": f"Macro already exists and is not a Task Designer wrapper: {safe_name}",
            }
    try:
        Path(path).write_text(source, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {
        "success": True,
        "message": f"Saved Task Designer wrapper: {safe_name}",
        "macro_id": safe_name,
        "path": path,
        "tasks": normalized_tasks,
    }


def _decode_filename_segment(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return re.sub(r"_%([0-9A-Fa-f]{2})_", repl, str(value or ""))


def _infer_active_dfm_identity_from_path(method_path: str) -> Dict[str, str]:
    raw_path = str(method_path or "").strip()
    if not raw_path:
        return {}
    try:
        path = Path(raw_path)
        parts = list(path.parts)
    except Exception:
        return {}

    out: Dict[str, str] = {}
    lower_parts = [str(part).lower() for part in parts]
    try:
        projects_index = lower_parts.index("projects")
        if projects_index + 1 < len(parts):
            out["project_name"] = str(parts[projects_index + 1]).strip()
    except ValueError:
        pass

    for index in range(0, max(0, len(parts) - 2)):
        if lower_parts[index] == "data" and lower_parts[index + 1] in {"manual", "generated"}:
            out["reserving_class"] = _decode_filename_segment(str(parts[index + 2]).strip())
            break

    filename = path.name
    if filename.startswith("DFM@") and filename.lower().endswith(".json"):
        out["method_name"] = filename[4:-5].strip()
    return out


def _restamp_active_dfm_revisions(active_json: Dict[str, Any]) -> Dict[str, Any]:
    """Re-stamp canonical revisions on the captured in-memory DFM payload.

    The captured activeJson reflects the UI's current state — including unsaved
    edits — while still carrying the revision stamps of the last save. Strict
    validation requires stamped revisions to match the canonical payload, so it
    would reject exactly the dirty state macros are meant to operate on.
    """
    from arcrho_api.dfm_contract import DFM_JSON_FORMAT, normalize_dfm_method

    if str(active_json.get("json_format") or "") != DFM_JSON_FORMAT:
        return active_json
    try:
        return normalize_dfm_method(active_json, require_complete=False)
    except ValueError as err:
        raise ValueError(f"Active DFM JSON could not be normalized: {err}") from err


def _build_active_dfm(active_context: Dict[str, Any]):
    _ensure_arcrho_api_import_path()
    from app_server.services.macro_dfm_service import build_macro_dfm

    active_json = active_context.get("activeJson")
    if not isinstance(active_json, dict):
        raise ValueError("Active DFM JSON is not available.")
    # The UI stamps the live Notes tab text onto the transient
    # `method metadata.method notes` carrier; normalization strips it, so read
    # it first and seed it as pending notes below.
    captured_metadata = active_json.get("method_metadata")
    ui_method_notes = (
        captured_metadata.get("method_notes")
        if isinstance(captured_metadata, dict) and "method_notes" in captured_metadata
        else None
    )
    active_json = _restamp_active_dfm_revisions(copy.deepcopy(active_json))
    restamped_metadata = active_json.get("method_metadata")
    if isinstance(restamped_metadata, dict):
        restamped_metadata.pop("method_notes", None)
    fields = active_context.get("fields") if isinstance(active_context.get("fields"), dict) else {}
    details = active_json.get("details_tab") if isinstance(active_json.get("details_tab"), dict) else {}
    metadata = active_json.get("method_metadata") if isinstance(active_json.get("method_metadata"), dict) else {}

    project_name = str(fields.get("project") or metadata.get("project") or "").strip()
    reserving_class = str(fields.get("reservingClass") or details.get("reserving class") or "").strip()
    method_name = str(fields.get("methodName") or details.get("name") or "").strip()
    method_path = str(active_context.get("methodPath") or "").strip()
    inferred = _infer_active_dfm_identity_from_path(method_path)
    project_name = project_name or inferred.get("project_name", "")
    reserving_class = reserving_class or inferred.get("reserving_class", "")
    method_name = method_name or inferred.get("method_name", "")

    dfm = build_macro_dfm(
        active_json, project_name, reserving_class, method_name, method_path,
    )
    return _seed_active_dfm_notes(dfm, ui_method_notes)


def _macro_pending_method_notes(active_dfm) -> Any:
    """Notes the macro itself set, or None when it left the seeded notes alone."""
    if active_dfm is None:
        return None
    pending = getattr(active_dfm, "_pending_notes", None)
    if pending is None:
        return None
    seeded = getattr(active_dfm, "_macro_seeded_notes", None)
    return None if seeded is not None and pending == seeded else pending


def _seed_active_dfm_notes(dfm, ui_method_notes):
    """Seed `dfm.notes` from the UI's live Notes tab text.

    Without this, `DfmMethod.notes` falls back to the persisted output sidecar,
    so a macro would read (and diff against) stale notes whenever the Notes tab
    has unsaved edits. `_macro_seeded_notes` records the seed so the apply path
    can tell an untouched seed from a macro's own `update_notes()`.
    """
    if ui_method_notes is None:
        return dfm
    seeded = str(ui_method_notes)
    dfm.update_notes(seeded)
    dfm._macro_seeded_notes = seeded
    return dfm


class _MacroTaskDesignerProxy:
    def __init__(self, window_id: str = "", session_id: str = "") -> None:
        _ensure_arcrho_api_import_path()
        from arcrho_api import ArcRhoUI

        self._ui = ArcRhoUI()
        self.window_id = str(window_id or "task-designer-main")
        self.session_id = str(session_id or "")

    def open(self, title: str = "Task Designer", context: str = "") -> Any:
        return self._ui.task_designer.open(
            title=title,
            context=context,
            window_id=self.window_id,
            session_id=self.session_id,
        )

    def register_task(self, task_id: str, name: str, description: str = "") -> Any:
        return self._ui.task_designer.register_task(
            task_id,
            name,
            description=description,
            window_id=self.window_id,
            session_id=self.session_id,
        )

    def start_task(self, task_id: str) -> Any:
        return self._ui.task_designer.start_task(
            task_id,
            window_id=self.window_id,
            session_id=self.session_id,
        )

    def complete_task(self, task_id: str, result: str, message: str = "", details: Any = None) -> Any:
        return self._ui.task_designer.complete_task(
            task_id,
            result,
            message=message,
            details=details,
            window_id=self.window_id,
            session_id=self.session_id,
        )

    def update_task(
        self,
        task_id: str,
        status: str | None = None,
        message: str | None = None,
        details: Any = None,
    ) -> Any:
        return self._ui.task_designer.update_task(
            task_id,
            status=status,
            message=message,
            details=details,
            window_id=self.window_id,
            session_id=self.session_id,
        )

    def close(self) -> Any:
        return self._ui.task_designer.close(window_id=self.window_id, session_id=self.session_id)


def _normalize_task_result(value: str) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"needsreview", "review"}:
        return "needs_review"
    if raw in {"passed", "complete", "completed", "ok"}:
        return "pass"
    if raw == "failed":
        return "fail"
    return raw


class _TaskRowTrackingDesignerProxy:
    _FINAL_RESULTS = {"pass", "fail", "needs_review", "skipped", "error"}

    def __init__(self, delegate: Any, row_id: str, row_name: str = "", row_description: str = "") -> None:
        self._delegate = delegate
        self._row_id = str(row_id or "")
        self._row_name = str(row_name or "")
        self._row_description = str(row_description or "")
        self.row_finalized = False

    def _track(self, task_id: str, status: str = "") -> None:
        if str(task_id or "") == self._row_id and _normalize_task_result(status) in self._FINAL_RESULTS:
            self.row_finalized = True

    def open(self, *args, **kwargs) -> Any:
        return self._delegate.open(*args, **kwargs)

    def register_task(self, task_id: str, name: str = "", description: str = "", *args, **kwargs) -> Any:
        if str(task_id or "") == self._row_id:
            return self._delegate.register_task(
                task_id,
                self._row_name or name,
                self._row_description or description,
            )
        return self._delegate.register_task(task_id, name, description, *args, **kwargs)

    def start_task(self, *args, **kwargs) -> Any:
        return self._delegate.start_task(*args, **kwargs)

    def complete_task(self, task_id: str, result: str, *args, **kwargs) -> Any:
        self._track(task_id, result)
        return self._delegate.complete_task(task_id, result, *args, **kwargs)

    def update_task(self, task_id: str, status: str | None = None, *args, **kwargs) -> Any:
        self._track(task_id, status or "")
        return self._delegate.update_task(task_id, status=status, *args, **kwargs)

    def close(self) -> Any:
        return self._delegate.close()


def _run_task_child_macro(
    macro_id: str,
    active_context: Dict[str, Any],
    task_designer: Any = None,
    *,
    task_id: str = "",
    name: str = "",
    description: str = "",
) -> Dict[str, Any]:
    normalized_macro_id = os.path.basename(str(macro_id or "").strip().replace("\\", "/"))
    row_id = str(task_id or os.path.splitext(normalized_macro_id)[0] or "task").strip()
    row_name = str(name or os.path.splitext(normalized_macro_id)[0] or normalized_macro_id).strip()
    row_description = str(description or normalized_macro_id).strip()
    row_task_designer = _TaskRowTrackingDesignerProxy(task_designer, row_id, row_name, row_description) if task_designer is not None else None
    if row_task_designer is not None:
        try:
            row_task_designer.register_task(row_id, row_name, row_description)
            row_task_designer.start_task(row_id)
        except Exception:
            pass

    output = io.StringIO()
    try:
        path = _safe_macro_path(normalized_macro_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Child macro not found: {normalized_macro_id}")
        source = Path(path).read_text(encoding="utf-8-sig")
        child_dfm = _build_active_dfm(active_context) if isinstance(active_context.get("activeJson"), dict) else None

        def run_nested_task_macro(
            child_macro_id: str,
            task_id: str = "",
            name: str = "",
            description: str = "",
        ) -> Dict[str, Any]:
            return _run_task_child_macro(
                child_macro_id,
                active_context,
                task_designer,
                task_id=task_id,
                name=name,
                description=description,
            )

        namespace: Dict[str, Any] = {
            "__name__": "__arcrho_child_macro__",
            "__file__": path,
            "active_dfm": child_dfm,
            "dfm": child_dfm,
            "active_context": active_context,
            "task_designer": row_task_designer,
            "task_id": row_id,
            "run_task_macro": run_nested_task_macro,
            "log": print,
        }
        runner_result = None
        with redirect_stdout(output):
            exec(compile(source, path, "exec"), namespace)
            runner = namespace.get("run_macro") or namespace.get("main")
            if callable(runner):
                runner_result = runner(child_dfm, active_context)
        stdout = output.getvalue().strip()
        success = not (isinstance(runner_result, dict) and runner_result.get("success") is False)
        message = stdout
        if isinstance(runner_result, dict) and runner_result.get("message"):
            message = "\n".join(part for part in [message, str(runner_result.get("message"))] if part).strip()
        if row_task_designer is not None and not row_task_designer.row_finalized:
            try:
                row_task_designer.complete_task(row_id, "pass" if success else "error", message=message)
            except Exception:
                pass
        return {
            "success": success,
            "macro_id": normalized_macro_id,
            "stdout": stdout,
            "message": message,
            "result": runner_result if isinstance(runner_result, dict) else {},
        }
    except Exception as exc:
        message = str(exc)
        stdout = output.getvalue().strip()
        if stdout:
            message = f"{stdout}\n{message}"
        if row_task_designer is not None and not row_task_designer.row_finalized:
            try:
                row_task_designer.complete_task(row_id, "error", message=message)
            except Exception:
                pass
        return {
            "success": False,
            "macro_id": normalized_macro_id,
            "stdout": stdout,
            "message": message,
            "traceback": traceback.format_exc(),
        }


def _normalize_macro_source(source: str, filename: str, source_path: str = "") -> Tuple[str, str, str]:
    text = str(source or "")
    if text.startswith("\ufeff"):
        text = text[1:]
    if not text.strip():
        raise ValueError("The editor does not contain Python source to run.")
    if len(text) > _MAX_MACRO_SOURCE_CHARS:
        raise ValueError(f"Macro source exceeds the {_MAX_MACRO_SOURCE_CHARS:,}-character limit.")
    if "\x00" in text:
        raise ValueError("Macro source contains an invalid null character.")

    requested_path = str(source_path or "").strip()
    requested_name = str(filename or "").strip() or "untitled_macro.py"
    if "\x00" in requested_path or "\x00" in requested_name:
        raise ValueError("Macro filename contains an invalid null character.")
    compile_path = requested_path or requested_name
    display_name = os.path.basename(requested_path or requested_name) or "untitled_macro.py"
    return text, compile_path, display_name


def _invoke_macro_runner(runner: Any, active_dfm: Any, active_context: Dict[str, Any]) -> Any:
    """Call the conventional macro entry point while supporting simple main() scripts."""
    try:
        signature = inspect.signature(runner)
    except (TypeError, ValueError):
        return runner(active_dfm, active_context)

    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in {parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD}
    ]
    has_varargs = any(
        parameter.kind == parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if has_varargs or len(positional) >= 2:
        return runner(active_dfm, active_context)
    if len(positional) == 1:
        return runner(active_dfm)
    return runner()


def _set_macro_command_owner(client_id: str) -> str:
    """Address the running macro's UI commands to the window that started it.

    Runs are serialised by the execution lock, so one process-wide owner is
    enough. Returns the previous owner so the caller can restore it.
    """
    _ensure_arcrho_api_import_path()
    try:
        from arcrho_api import ui as arcrho_ui
    except Exception:
        return ""
    setter = getattr(arcrho_ui, "set_command_owner", None)
    if not callable(setter):
        return ""
    return str(setter(client_id) or "")


def _execute_macro_source_body(
    source: str,
    compile_path: str,
    source_path: str,
    active_context: Dict[str, Any],
    task_window_id: str,
    task_session_id: str,
    task_mode: str,
    output: io.StringIO,
    cancel_event: threading.Event,
    activity: _ExecutionActivity,
    client_id: str = "",
) -> Dict[str, Any]:
    com_apartment = _initialize_macro_com_apartment()
    try:
        with _MACRO_EXECUTION_LOCK:
            previous_owner = _set_macro_command_owner(client_id)
            previous_trace = sys.gettrace()
            macro_root = _get_macros_dir()
            sys.settrace(
                _make_scoped_cancel_trace(
                    cancel_event,
                    traced_files={compile_path, source_path},
                    traced_roots=(macro_root,),
                )
            )
            source_directory = ""
            inserted_source_directory = False
            try:
                active_dfm = _build_active_dfm(active_context) if isinstance(active_context.get("activeJson"), dict) else None
                before_payload = copy.deepcopy(active_dfm.to_dict()) if active_dfm is not None else None
                task_designer = _MacroTaskDesignerProxy(task_window_id, task_session_id)

                def run_task_macro(
                    child_macro_id: str,
                    task_id: str = "",
                    name: str = "",
                    description: str = "",
                ) -> Dict[str, Any]:
                    return _run_task_child_macro(
                        child_macro_id,
                        active_context,
                        task_designer,
                        task_id=task_id,
                        name=name,
                        description=description,
                    )

                macro_import, _time_proxy = _make_session_import_hook(
                    builtins.__import__,
                    cancel_event,
                    threading.get_ident(),
                )
                macro_builtins = dict(vars(builtins))
                macro_builtins["__import__"] = macro_import
                check_macro_cancelled = _make_cooperative_cancel_checker(cancel_event)
                run_trusted_macro_call = _make_trusted_macro_call(cancel_event)
                namespace: Dict[str, Any] = {
                    "__name__": "__arcrho_macro__",
                    "__file__": compile_path,
                    "__builtins__": macro_builtins,
                    "active_dfm": active_dfm,
                    "dfm": active_dfm,
                    "active_context": active_context,
                    "task_window_id": str(task_window_id or ""),
                    "task_session_id": str(task_session_id or ""),
                    "task_mode": str(task_mode or ""),
                    "task_designer": task_designer,
                    "run_task_macro": run_task_macro,
                    "check_macro_cancelled": check_macro_cancelled,
                    "run_trusted_macro_call": run_trusted_macro_call,
                    "report_macro_activity": activity.touch,
                    "log": print,
                }
                if source_path:
                    try:
                        source_directory = str(Path(source_path).expanduser().resolve().parent)
                    except (OSError, RuntimeError, ValueError):
                        source_directory = ""
                inserted_source_directory = bool(
                    source_directory
                    and os.path.isdir(source_directory)
                    and source_directory not in sys.path
                )
                if inserted_source_directory:
                    sys.path.insert(0, source_directory)

                with redirect_stdout(output):
                    exec(compile(source, compile_path, "exec"), namespace)
                    runner = namespace.get("run_macro") or namespace.get("main")
                    runner_result = _invoke_macro_runner(runner, active_dfm, active_context) if callable(runner) else None
                after_payload = copy.deepcopy(active_dfm.to_dict()) if active_dfm is not None else None
                return {
                    "runner_result": runner_result,
                    "before_payload": before_payload,
                    "after_payload": after_payload,
                    # Method Notes live in the output sidecar, not the method
                    # payload; carry a macro's update_notes() result separately
                    # so the apply path can deliver it to the DFM Notes tab.
                    "pending_method_notes": _macro_pending_method_notes(active_dfm),
                }
            finally:
                if inserted_source_directory:
                    try:
                        sys.path.remove(source_directory)
                    except ValueError:
                        pass
                sys.settrace(previous_trace)
                _set_macro_command_owner(previous_owner)
    finally:
        if com_apartment is not None:
            com_apartment.CoUninitialize()


def run_macro_source(
    source: str,
    filename: str,
    active_context: Dict[str, Any],
    *,
    source_path: str = "",
    task_window_id: str = "",
    task_session_id: str = "",
    task_mode: str = "",
    client_id: str = "",
) -> Dict[str, Any]:
    output = io.StringIO()
    compile_path = str(source_path or filename or "untitled_macro.py")
    try:
        source, compile_path, display_name = _normalize_macro_source(source, filename, source_path)
        active_context = active_context if isinstance(active_context, dict) else {}
        cancel_event = threading.Event()
        activity = _ExecutionActivity()
        execution = _run_with_timeout(
            lambda: _execute_macro_source_body(
                source,
                compile_path,
                source_path,
                active_context,
                task_window_id,
                task_session_id,
                task_mode,
                output,
                cancel_event,
                activity,
                client_id,
            ),
            _MACRO_TIMEOUT_SEC,
            cancel_event,
            activity=activity,
        )
        runner_result = execution.get("runner_result")
        runner_success = not (
            isinstance(runner_result, dict)
            and runner_result.get("success") is False
        )
        explicit_payload = (
            runner_result.get("payload")
            if isinstance(runner_result, dict) and isinstance(runner_result.get("payload"), dict)
            else None
        )
        changed_payload = execution.get("after_payload")
        if changed_payload == execution.get("before_payload"):
            changed_payload = None
        payload = explicit_payload if explicit_payload is not None else changed_payload
        pending_method_notes = execution.get("pending_method_notes")
        if runner_success and pending_method_notes is not None:
            # Stamp the transient `method metadata.method notes` carrier (the
            # same convention as the DFM RPC bridge) so accepting the macro
            # result updates the DFM Notes tab; canonicalization strips the
            # stamp before anything is persisted to the method JSON.
            notes_payload = copy.deepcopy(
                payload if payload is not None else execution.get("after_payload")
            )
            if isinstance(notes_payload, dict):
                metadata = notes_payload.setdefault("method_metadata", {})
                if isinstance(metadata, dict):
                    metadata["method_notes"] = str(pending_method_notes)
                    payload = notes_payload
        preview = (
            runner_result.get("preview")
            if isinstance(runner_result, dict) and isinstance(runner_result.get("preview"), dict)
            else None
        )
        response = {
            "success": runner_success,
            "message": f"Ran {display_name}",
            "stdout": output.getvalue(),
            "path": compile_path,
        }
        if runner_success and payload is not None:
            response["payload"] = payload
        if runner_success and preview is not None:
            response["preview"] = preview
        if isinstance(runner_result, dict) and runner_result.get("message"):
            response["message"] = str(runner_result.get("message"))
        return response
    except BaseException as exc:
        return {
            "success": False,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "stdout": output.getvalue(),
            "path": compile_path,
        }


def run_macro(
    macro_id: str,
    active_context: Dict[str, Any],
    *,
    task_window_id: str = "",
    task_session_id: str = "",
    task_mode: str = "",
    client_id: str = "",
) -> Dict[str, Any]:
    # The library module imports this one, so it is imported here rather than at
    # module level. A newer published version replaces the local copy before the
    # source is read, so the macro that runs is always the latest one.
    from app_server.services import macro_library_service

    path = _safe_macro_path(macro_id)
    if not os.path.isfile(path):
        return {"success": False, "message": f"Macro not found: {macro_id}"}
    library_update = macro_library_service.sync_library_macro(macro_id)
    try:
        source = Path(path).read_text(encoding="utf-8-sig")
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "path": path,
        }
    result = run_macro_source(
        source,
        os.path.basename(path),
        active_context,
        source_path=path,
        task_window_id=task_window_id,
        task_session_id=task_session_id,
        task_mode=task_mode,
        client_id=client_id,
    )
    if library_update:
        result["library_update"] = library_update
    return result


def _consume_captured_macro_target(target: Dict[str, Any]) -> None:
    """Best-effort cleanup when source execution fails before review/apply."""
    from app_server.services import ui_automation_service

    try:
        ui_automation_service.submit_command(
            "macro.reviewAndApplyResult",
            {"scope": "capturedDfm"},
            {"target": target, "discard": True},
            5.0,
        )
    except Exception:
        pass


def run_macro_source_in_arcrho(source: str, filename: str, source_path: str = "") -> Dict[str, Any]:
    """Capture the live DFM, execute editor source, then safely apply the result."""
    from app_server.services import ui_automation_service

    try:
        source, _compile_path, _display_name = _normalize_macro_source(source, filename, source_path)
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
            "path": str(source_path or filename or "untitled_macro.py"),
        }

    capture = ui_automation_service.submit_command(
        "macro.captureActiveDfmContext",
        {"scope": "activeShell"},
        {},
        10.0,
    )
    if not capture.get("ok"):
        return {
            "success": False,
            "message": capture.get("error") or "Arco could not read the active DFM context.",
        }
    captured = capture.get("result") if isinstance(capture.get("result"), dict) else {}
    active_context = captured.get("activeContext") if isinstance(captured.get("activeContext"), dict) else {}
    target = captured.get("target") if isinstance(captured.get("target"), dict) else {}
    if not target.get("token"):
        return {
            "success": False,
            "message": "Arco did not return a usable macro execution context.",
        }

    execution = run_macro_source(
        source,
        filename,
        active_context,
        source_path=source_path,
    )
    if not execution.get("success"):
        _consume_captured_macro_target(target)
        return execution

    review_expires_at = int(
        (
            py_time.time()
            + _MACRO_REVIEW_TIMEOUT_SEC
            - _MACRO_REVIEW_EXPIRY_BUFFER_SEC
        )
        * 1000
    )
    review = ui_automation_service.submit_command(
        "macro.reviewAndApplyResult",
        {"scope": "capturedDfm"},
        {
            "target": target,
            "payload": execution.get("payload"),
            "preview": execution.get("preview"),
            "message": execution.get("message") or "",
            "expiresAt": review_expires_at,
        },
        _MACRO_REVIEW_TIMEOUT_SEC,
    )
    response = {
        key: value
        for key, value in execution.items()
        if key not in {"payload", "preview"}
    }
    if not review.get("ok"):
        response["success"] = False
        response["message"] = review.get("error") or "The macro ran, but Arco could not review or apply its result."
        return response

    review_result = review.get("result") if isinstance(review.get("result"), dict) else {}
    response["applied"] = bool(review_result.get("applied"))
    response["cancelled"] = bool(review_result.get("cancelled"))
    if review_result.get("message"):
        response["message"] = str(review_result.get("message"))
    return response


def run_arcrho_macro_source(source: str, filename: str, source_path: str = "") -> Dict[str, Any]:
    """Proxy standalone Arcode source to the user's running Arco desktop app."""
    _ensure_arcrho_api_import_path()
    try:
        source, _compile_path, _display_name = _normalize_macro_source(source, filename, source_path)
        from arcrho_api import ArcRhoUI

        # Without an explicit override, arcrho_api resolves the Arco desktop app
        # URL itself (env overrides, then the per-user app_endpoint.json written by
        # the desktop host, then the default local port).
        app_url = str(os.environ.get("ARCRHO_DESKTOP_APP_URL") or "").strip() or None
        return ArcRhoUI(app_url=app_url).macros.run_source(
            source,
            filename=filename,
            source_path=source_path,
            timeout_sec=300.0,
        )
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "path": str(source_path or filename or "untitled_macro.py"),
        }


