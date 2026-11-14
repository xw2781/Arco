"""ArcRho UI automation helpers."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import config_dir
from .exceptions import ArcRhoApiError


@dataclass
class UiCommandResult:
    ok: bool
    result: dict[str, Any]
    error: str = ""
    command_id: str = ""

    @property
    def button(self) -> str:
        return str(self.result.get("button") or "")

    @property
    def progress_id(self) -> str:
        return str(self.result.get("progressId") or self.result.get("progress_id") or "")


@dataclass
class ArcRhoWindowProperties:
    """Current properties for a floating ArcRho UI window."""

    window_id: str
    title: str = ""
    kind: str = ""
    name: str = ""
    dataset_name: str = ""
    item_name: str = ""
    project_name: str = ""
    selected_path: str = ""
    path: str = ""
    method_type: str = ""
    window_key: str = ""
    active: bool = False
    hidden: bool = False
    maximized: bool = False
    dirty: bool = False
    connected: bool = True
    rect: dict[str, Any] | None = None

    @classmethod
    def from_result(cls, payload: dict[str, Any]) -> "ArcRhoWindowProperties":
        data = payload.get("window") if isinstance(payload.get("window"), dict) else payload
        if not isinstance(data, dict):
            data = {}
        window_id = str(data.get("windowId") or data.get("id") or "")
        return cls(
            window_id=window_id,
            title=str(data.get("title") or ""),
            kind=str(data.get("kind") or ""),
            name=str(data.get("name") or ""),
            dataset_name=str(data.get("datasetName") or data.get("dataset_name") or ""),
            item_name=str(data.get("itemName") or data.get("item_name") or ""),
            project_name=str(data.get("projectName") or data.get("project_name") or ""),
            selected_path=str(data.get("selectedPath") or data.get("selected_path") or ""),
            path=str(data.get("path") or ""),
            method_type=str(data.get("methodType") or data.get("method_type") or ""),
            window_key=str(data.get("windowKey") or data.get("window_key") or ""),
            active=bool(data.get("active")),
            hidden=bool(data.get("hidden")),
            maximized=bool(data.get("maximized")),
            dirty=bool(data.get("dirty")),
            connected=bool(data.get("connected", True)),
            rect=data.get("rect") if isinstance(data.get("rect"), dict) else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "windowId": self.window_id,
            "id": self.window_id,
            "windowKey": self.window_key,
            "kind": self.kind,
            "name": self.name,
            "datasetName": self.dataset_name,
            "itemName": self.item_name,
            "title": self.title,
            "projectName": self.project_name,
            "selectedPath": self.selected_path,
            "path": self.path,
            "methodType": self.method_type,
            "active": self.active,
            "hidden": self.hidden,
            "maximized": self.maximized,
            "dirty": self.dirty,
            "connected": self.connected,
            "rect": dict(self.rect or {}),
        }


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
    finally:
        kernel32.CloseHandle(handle)


def running_apps() -> list[dict[str, Any]]:
    """Every running Arco desktop app on this PC for this Windows user, newest first.

    The Electron host lists each app in ``%APPDATA%\\Arco\\app_endpoint.json`` once its
    app server is ready. A second app, or one whose preferred port was taken, runs on its
    own port, so this file is the only record of where each app is.
    """
    endpoint_path = os.path.join(config_dir(), "app_endpoint.json")
    try:
        with open(endpoint_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("apps") if isinstance(payload.get("apps"), list) else [payload]
    apps = []
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("app") or "").strip().lower() != "arcrho":
            continue
        url = str(entry.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        try:
            pid = int(entry.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        # An entry without a process id comes from a writer older than the list; trust it.
        if "pid" in entry and not _pid_alive(pid):
            continue
        apps.append({**entry, "url": url.rstrip("/")})
    return apps


def _discovered_app_url(*, pid: int | str | None = None, port: int | str | None = None) -> str:
    """The newest running app's URL, or the one with the named process id or port."""
    for entry in running_apps():
        if pid not in (None, "") and str(entry.get("pid")) != str(pid).strip():
            continue
        if port not in (None, "") and str(entry.get("port")) != str(port).strip():
            continue
        return entry["url"]
    return ""


def _base_url(app_url: str | None = None) -> str:
    configured = str(app_url or os.environ.get("ARCRHO_APP_URL") or "").strip()
    if configured:
        return configured.rstrip("/")
    host = str(os.environ.get("ARCRHO_HOST") or "").strip()
    port = str(os.environ.get("ARCRHO_PORT") or "").strip()
    if host or port:
        return f"http://{host or '127.0.0.1'}:{port or '28765'}"
    discovered = _discovered_app_url(pid=os.environ.get("ARCRHO_APP_PID"))
    if discovered:
        return discovered
    return "http://127.0.0.1:28765"


def _request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_sec: float = 5.0,
    app_url: str | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if method.upper() != "GET" else None
    request = Request(
        f"{_base_url(app_url)}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method.upper(),
    )
    try:
        with urlopen(request, timeout=max(0.1, float(timeout_sec))) as response:
            body = response.read().decode("utf-8")
    except HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise ArcRhoApiError(f"Arco UI command failed ({err.code}): {detail}") from err
    except URLError as err:
        raise ArcRhoApiError(f"Arco app is not reachable at {_base_url(app_url)}.") from err
    except OSError as err:
        raise ArcRhoApiError(f"Arco UI command failed: {err}") from err

    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError as err:
        raise ArcRhoApiError(f"Arco UI command returned invalid JSON: {body[:200]}") from err
    if not isinstance(parsed, dict):
        raise ArcRhoApiError("Arco UI command returned an unexpected response.")
    return parsed


def _post_json(path: str, payload: dict[str, Any], timeout_sec: float, *, app_url: str | None = None) -> dict[str, Any]:
    return _request_json(
        path,
        method="POST",
        payload=payload,
        timeout_sec=max(0.1, float(timeout_sec) + 2.0),
        app_url=app_url,
    )


def get_app_health(*, timeout_sec: float = 2.0, app_url: str | None = None) -> dict[str, Any]:
    """Return `/app/health` from the running local ArcRho app."""

    return _request_json("/app/health", timeout_sec=timeout_sec, app_url=app_url)


def is_app_running(*, timeout_sec: float = 2.0, app_url: str | None = None) -> bool:
    """Return True when the local ArcRho app server is reachable."""

    try:
        health = get_app_health(timeout_sec=timeout_sec, app_url=app_url)
    except ArcRhoApiError:
        return False
    return bool(health.get("ok"))


def wait_for_app(
    *,
    timeout_sec: float = 10.0,
    interval_sec: float = 0.5,
    app_url: str | None = None,
) -> dict[str, Any]:
    """Wait for the local ArcRho app server and return its health payload."""

    deadline = time.monotonic() + max(0.1, float(timeout_sec))
    last_error = ""
    while time.monotonic() <= deadline:
        try:
            health = get_app_health(timeout_sec=min(2.0, max(0.1, float(interval_sec))), app_url=app_url)
            if health.get("ok"):
                return health
        except ArcRhoApiError as err:
            last_error = str(err)
        time.sleep(max(0.05, float(interval_sec)))
    raise ArcRhoApiError(last_error or f"Arco app is not reachable at {_base_url(app_url)}.")


def run_macro_source(
    source: str,
    *,
    filename: str = "untitled_macro.py",
    source_path: str = "",
    timeout_sec: float = 300.0,
    app_url: str | None = None,
) -> dict[str, Any]:
    """Run an editor buffer as a macro against the active DFM in ArcRho."""

    health = get_app_health(timeout_sec=min(2.0, max(0.1, float(timeout_sec))), app_url=app_url)
    app_name = str(health.get("app") or "").strip().lower()
    if app_name != "arcrho":
        connected_name = app_name or "an unsupported app"
        raise ArcRhoApiError(
            f"Run in Arco requires the Arco desktop app on {_base_url(app_url)}; "
            f"connected to {connected_name!r}."
        )
    return _post_json(
        "/scripting/run-in-arcrho",
        {
            "source": str(source or ""),
            "filename": str(filename or "untitled_macro.py"),
            "source_path": str(source_path or ""),
        },
        timeout_sec,
        app_url=app_url,
    )


# The shell window that started the running macro. The macro host sets it for the
# length of a run so every command the macro sends goes back to that window, even
# when another ArcRho app shares the same server. Empty leaves commands unaddressed.
_COMMAND_OWNER = ""


def set_command_owner(owner: str | None) -> str:
    """Address every following UI command to one shell window; return the previous owner."""

    global _COMMAND_OWNER
    previous = _COMMAND_OWNER
    _COMMAND_OWNER = str(owner or "").strip()
    return previous


def get_command_owner() -> str:
    """The shell window UI commands are currently addressed to, or empty."""

    return _COMMAND_OWNER


def send_command(
    command: str,
    *,
    target: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Send a typed UI automation command to the running ArcRho app."""

    payload = {
        "command": str(command or "").strip(),
        "target": target or {},
        "args": args or {},
        "timeout_sec": float(timeout_sec),
    }
    if _COMMAND_OWNER:
        payload["owner"] = _COMMAND_OWNER
    response = _post_json("/ui_automation/commands", payload, timeout_sec, app_url=app_url)
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    out = UiCommandResult(
        ok=bool(response.get("ok")),
        result=result,
        error=str(response.get("error") or ""),
        command_id=str(response.get("command_id") or ""),
    )
    if not out.ok:
        raise ArcRhoApiError(out.error or f"Arco UI command failed: {command}")
    return out


REVIEW_TABLE_POLL_SECONDS = 0.5


def _command_result(result: object) -> dict[str, Any]:
    """The result payload of a UI command, whether it came back typed or as JSON."""

    if isinstance(result, dict):
        payload = result.get("result")
        return dict(payload) if isinstance(payload, dict) else dict(result)
    payload = getattr(result, "result", None)
    return dict(payload) if isinstance(payload, dict) else {}


def await_review_table(
    ui: "ArcRhoUI",
    payload: dict[str, Any],
    *,
    on_poll: Callable[[], None] | None = None,
    poll_interval_sec: float = REVIEW_TABLE_POLL_SECONDS,
) -> dict[str, Any]:
    """Open a review table, wait until the person completes it, and return the completion.

    ``ui.reviewTableOpen`` returns at once so the automation queue stays free
    while the table is open; the completion is read through
    ``ui.reviewTableStatus`` and the table is always closed afterwards.
    ``on_poll`` runs before every status look, which is where a macro reports
    its activity and checks whether it was cancelled.
    """

    opened = ui.send_command("ui.reviewTableOpen", args=dict(payload), timeout_sec=20)
    opened_payload = _command_result(opened)
    dialog_id = str(opened_payload.get("dialogId") or opened_payload.get("dialog_id") or "").strip()
    if not dialog_id:
        raise ArcRhoApiError("Arco did not return a review-table dialog ID. Update or restart the Arco shell.")
    try:
        while True:
            if on_poll is not None:
                on_poll()
            status = ui.send_command("ui.reviewTableStatus", args={"dialogId": dialog_id}, timeout_sec=20)
            completion = _command_result(status)
            state = str(completion.get("status") or completion.get("state") or "").strip().casefold()
            if state == "completed":
                return completion
            if state not in {"", "pending", "open"}:
                raise ArcRhoApiError(
                    str(completion.get("error") or f"Review table ended in an unexpected state: {state}")
                )
            time.sleep(poll_interval_sec)
    finally:
        try:
            ui.send_command("ui.reviewTableClose", args={"dialogId": dialog_id}, timeout_sec=10)
        except Exception:
            pass


def message_box(
    message: str,
    *,
    title: str = "Arco",
    buttons: list[str] | tuple[str, ...] | None = None,
    kind: str = "info",
    auto_close_ms: int | float | None = None,
    presentation: str | None = None,
    links: list[dict[str, Any]] | None = None,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Show a message box in the active ArcRho app and return the clicked button.

    ``links`` lists items shown under the message as clickable rows, each
    ``{"label", "kind", "args"}`` where ``args`` are the
    ``projectInstance.openDataset`` arguments the shell runs when the row is
    clicked; the box stays open so several items can be opened in turn.
    """

    args = {
        "message": str(message or ""),
        "title": str(title or "Arco"),
        "buttons": list(buttons or ["OK"]),
        "kind": str(kind or "info"),
    }
    if auto_close_ms is not None:
        args["autoCloseMs"] = max(0, int(float(auto_close_ms)))
    if presentation is not None:
        args["presentation"] = str(presentation or "")
    if links:
        args["links"] = [dict(link) for link in links]
    return send_command(
        "ui.messageBox",
        args=args,
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def progress_open(
    *,
    progress_id: str = "default",
    title: str = "Arco Progress",
    label: str = "Starting...",
    detail: str = "",
    total: int | float = 0,
    completed: int | float = 0,
    timeout_sec: float = 10.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Open or update a shell-owned progress window."""

    return send_command(
        "ui.progressOpen",
        args={
            "progressId": str(progress_id or "default"),
            "title": str(title or "Arco Progress"),
            "label": str(label or ""),
            "detail": str(detail or ""),
            "total": max(0, int(float(total or 0))),
            "completed": max(0, int(float(completed or 0))),
        },
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def progress_update(
    *,
    progress_id: str = "default",
    label: str | None = None,
    detail: str | None = None,
    total: int | float | None = None,
    completed: int | float | None = None,
    tone: str | None = None,
    timeout_sec: float = 10.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Update a shell-owned progress window."""

    args: dict[str, Any] = {"progressId": str(progress_id or "default")}
    if label is not None:
        args["label"] = str(label)
    if detail is not None:
        args["detail"] = str(detail)
    if total is not None:
        args["total"] = max(0, int(float(total or 0)))
    if completed is not None:
        args["completed"] = max(0, int(float(completed or 0)))
    if tone is not None:
        args["tone"] = str(tone or "")
    return send_command(
        "ui.progressUpdate",
        args=args,
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def progress_close(
    *,
    progress_id: str = "default",
    auto_close_ms: int | float | None = None,
    timeout_sec: float = 10.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Close a shell-owned progress window."""

    args: dict[str, Any] = {"progressId": str(progress_id or "default")}
    if auto_close_ms is not None:
        args["autoCloseMs"] = max(0, int(float(auto_close_ms)))
    return send_command(
        "ui.progressClose",
        args=args,
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


class ProgressBar:
    """Convenience wrapper for a shell-owned progress window."""

    def __init__(
        self,
        ui: "ArcRhoUI",
        *,
        progress_id: str = "default",
        title: str = "Arco Progress",
        total: int = 0,
        label: str = "Starting...",
        detail: str = "",
    ) -> None:
        self._ui = ui
        self.progress_id = str(progress_id or "default")
        self.title = str(title or "Arco Progress")
        self.total = max(0, int(total or 0))
        self.completed = 0
        self.open(label=label, detail=detail, total=self.total, completed=0)

    def open(
        self,
        *,
        label: str = "Starting...",
        detail: str = "",
        total: int | None = None,
        completed: int | None = None,
    ) -> UiCommandResult:
        if total is not None:
            self.total = max(0, int(total or 0))
        if completed is not None:
            self.completed = max(0, int(completed or 0))
        return self._ui.progress_open(
            progress_id=self.progress_id,
            title=self.title,
            label=label,
            detail=detail,
            total=self.total,
            completed=self.completed,
        )

    def update(
        self,
        *,
        label: str | None = None,
        detail: str | None = None,
        total: int | None = None,
        completed: int | None = None,
        tone: str | None = None,
    ) -> UiCommandResult:
        if total is not None:
            self.total = max(0, int(total or 0))
        if completed is not None:
            self.completed = max(0, int(completed or 0))
        return self._ui.progress_update(
            progress_id=self.progress_id,
            label=label,
            detail=detail,
            total=self.total,
            completed=self.completed,
            tone=tone,
        )

    def close(self, *, auto_close_ms: int | float | None = None) -> UiCommandResult:
        return self._ui.progress_close(progress_id=self.progress_id, auto_close_ms=auto_close_ms)


def open_dataset_in_active_project_instance(
    dataset_name: str,
    *,
    dataset_type_name: str | None = None,
    read_only: bool | None = None,
    generated: bool | None = None,
    method_type: str | None = None,
    open_method: bool | None = None,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Open or activate a Dataset Viewer window in the active Project Instance page."""

    args: dict[str, Any] = {"datasetName": str(dataset_name or "")}
    if dataset_type_name is not None:
        args["datasetTypeName"] = str(dataset_type_name)
    if read_only is not None:
        args["readOnly"] = bool(read_only)
    if generated is not None:
        args["generated"] = bool(generated)
    if method_type is not None:
        args["methodType"] = str(method_type)
    if open_method is not None:
        args["openMethod"] = bool(open_method)
    return send_command(
        "projectInstance.openDataset",
        target={"scope": "activeProjectInstance"},
        args=args,
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def project_instance_window_action(
    action: str,
    *,
    window_id: str | None = None,
    window_key: str | None = None,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Run an action against a floating window in the active Project Instance page."""

    args: dict[str, Any] = {"action": str(action or "properties")}
    if window_id is not None:
        args["windowId"] = str(window_id)
    if window_key is not None:
        args["windowKey"] = str(window_key)
    return send_command(
        "projectInstance.windowAction",
        target={"scope": "activeProjectInstance"},
        args=args,
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def active_project_instance_window(
    *,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Return properties for the active floating window in the active Project Instance page."""

    return send_command(
        "projectInstance.activeWindow",
        target={"scope": "activeProjectInstance"},
        args={"action": "properties"},
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def project_instance_context(
    *,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Return project and selected reserving-class path for the active Project Instance page."""

    return send_command(
        "projectInstance.context",
        target={"scope": "activeProjectInstance"},
        args={},
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


def reload_project_instance_dataset_table(
    *,
    timeout_sec: float = 30.0,
    app_url: str | None = None,
) -> UiCommandResult:
    """Reload the dataset table in the active Project Instance page from disk."""

    return send_command(
        "projectInstance.refreshDatasets",
        target={"scope": "activeProjectInstance"},
        args={},
        timeout_sec=timeout_sec,
        app_url=app_url,
    )


class ArcRhoWindow:
    """COM-style wrapper for a floating ArcRho UI window."""

    def __init__(
        self,
        ui: "ArcRhoUI",
        window_id: str,
        properties: ArcRhoWindowProperties | dict[str, Any] | None = None,
    ) -> None:
        self._ui = ui
        self._window_id = str(window_id or "")
        self._properties = self._coerce_properties(properties)

    def __repr__(self) -> str:
        title = self._properties.title if self._properties else ""
        return f"ArcRhoWindow(id={self.id!r}, title={title!r})"

    @staticmethod
    def _coerce_properties(
        properties: ArcRhoWindowProperties | dict[str, Any] | None,
    ) -> ArcRhoWindowProperties | None:
        if isinstance(properties, ArcRhoWindowProperties):
            return properties
        if isinstance(properties, dict):
            return ArcRhoWindowProperties.from_result(properties)
        return None

    def _run(self, action: str, *, timeout_sec: float = 30.0) -> UiCommandResult:
        result = self._ui.send_command(
            "projectInstance.windowAction",
            target={"scope": "activeProjectInstance"},
            args={"action": action, "windowId": self.id},
            timeout_sec=timeout_sec,
        )
        if action == "close":
            props = self._properties or ArcRhoWindowProperties(window_id=self.id)
            props.connected = bool(result.result.get("connected", False))
            self._properties = props
        else:
            self._properties = ArcRhoWindowProperties.from_result(result.result)
        return result

    @property
    def id(self) -> str:
        return self._window_id or (self._properties.window_id if self._properties else "")

    @property
    def window_id(self) -> str:
        return self.id

    @property
    def properties(self) -> ArcRhoWindowProperties:
        self.refresh()
        return self._properties or ArcRhoWindowProperties(window_id=self.id)

    def refresh(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        self._run("properties", timeout_sec=timeout_sec)
        return self

    def get_properties(self, *, timeout_sec: float = 30.0) -> ArcRhoWindowProperties:
        self.refresh(timeout_sec=timeout_sec)
        return self._properties or ArcRhoWindowProperties(window_id=self.id)

    def activate(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        self._run("activate", timeout_sec=timeout_sec)
        return self

    def focus(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        return self.activate(timeout_sec=timeout_sec)

    def maximize(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        self._run("maximize", timeout_sec=timeout_sec)
        return self

    def restore(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        self._run("restore", timeout_sec=timeout_sec)
        return self

    def minimize(self, *, timeout_sec: float = 30.0) -> "ArcRhoWindow":
        self._run("minimize", timeout_sec=timeout_sec)
        return self

    def close(self, *, timeout_sec: float = 30.0) -> bool:
        return bool(self._run("close", timeout_sec=timeout_sec).result.get("closed"))

    @property
    def title(self) -> str:
        return self.properties.title

    @property
    def kind(self) -> str:
        return self.properties.kind

    @property
    def dataset_name(self) -> str:
        return self.properties.dataset_name

    @property
    def selected_path(self) -> str:
        return self.properties.selected_path

    @property
    def is_active(self) -> bool:
        return self.properties.active

    @property
    def is_hidden(self) -> bool:
        return self.properties.hidden

    @property
    def is_maximized(self) -> bool:
        return self.properties.maximized

    @property
    def is_dirty(self) -> bool:
        return self.properties.dirty

    @property
    def is_closed(self) -> bool:
        try:
            return not self.properties.connected
        except ArcRhoApiError:
            return True


class ProjectInstanceAutomation:
    """Automation entry point for the active Project Instance page."""

    def __init__(self, ui: "ArcRhoUI") -> None:
        self._ui = ui

    def open_dataset(
        self,
        dataset_name: str,
        *,
        dataset_type_name: str | None = None,
        read_only: bool | None = None,
        generated: bool | None = None,
        method_type: str | None = None,
        open_method: bool | None = None,
        timeout_sec: float = 30.0,
    ) -> ArcRhoWindow:
        result = self._ui.open_dataset_in_active_project_instance(
            dataset_name,
            dataset_type_name=dataset_type_name,
            read_only=read_only,
            generated=generated,
            method_type=method_type,
            open_method=open_method,
            timeout_sec=timeout_sec,
        )
        properties = ArcRhoWindowProperties.from_result(result.result)
        return ArcRhoWindow(self._ui, properties.window_id, properties)

    def active_window(self, *, timeout_sec: float = 30.0) -> ArcRhoWindow | None:
        result = self._ui.send_command(
            "projectInstance.activeWindow",
            target={"scope": "activeProjectInstance"},
            args={"action": "properties"},
            timeout_sec=timeout_sec,
        )
        properties = ArcRhoWindowProperties.from_result(result.result)
        return ArcRhoWindow(self._ui, properties.window_id, properties) if properties.window_id else None

    def context(self, *, timeout_sec: float = 30.0) -> dict[str, Any]:
        result = self._ui.project_instance_context(timeout_sec=timeout_sec)
        return dict(result.result or {})

    def reload_dataset_table(self, *, timeout_sec: float = 30.0) -> dict[str, Any]:
        result = self._ui.reload_project_instance_dataset_table(timeout_sec=timeout_sec)
        return dict(result.result or {})

    def window(self, window_id: str) -> ArcRhoWindow:
        return ArcRhoWindow(self._ui, window_id)


class TaskDesignerAutomation:
    """Automation entry point for the shell Task Designer window."""

    def __init__(self, ui: "ArcRhoUI") -> None:
        self._ui = ui

    @staticmethod
    def _target_args(
        *,
        window_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        args = dict(kwargs)
        args["windowId"] = str(window_id or "task-designer-main")
        if session_id is not None:
            args["sessionId"] = str(session_id)
        return args

    def open(
        self,
        *,
        title: str = "Task Designer",
        context: str = "",
        macro_id: str = "",
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.open",
            args=self._target_args(
                window_id=window_id,
                session_id=session_id,
                title=str(title or "Task Designer"),
                context=str(context or ""),
                macroId=str(macro_id or ""),
            ),
            timeout_sec=timeout_sec,
        )

    def set_tasks(
        self,
        tasks: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        *,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.setTasks",
            args=self._target_args(window_id=window_id, session_id=session_id, tasks=list(tasks or [])),
            timeout_sec=timeout_sec,
        )

    def register_task(
        self,
        task_id: str,
        name: str,
        description: str = "",
        *,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.registerTask",
            args=self._target_args(
                window_id=window_id,
                session_id=session_id,
                taskId=str(task_id or ""),
                name=str(name or task_id or ""),
                description=str(description or ""),
            ),
            timeout_sec=timeout_sec,
        )

    def start_task(
        self,
        task_id: str,
        *,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.startTask",
            args=self._target_args(window_id=window_id, session_id=session_id, taskId=str(task_id or "")),
            timeout_sec=timeout_sec,
        )

    def complete_task(
        self,
        task_id: str,
        result: str,
        *,
        message: str = "",
        details: Any = None,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.completeTask",
            args=self._target_args(
                window_id=window_id,
                session_id=session_id,
                taskId=str(task_id or ""),
                result=str(result or ""),
                message=str(message or ""),
                details=details,
            ),
            timeout_sec=timeout_sec,
        )

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        message: str | None = None,
        details: Any = None,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        args = self._target_args(window_id=window_id, session_id=session_id, taskId=str(task_id or ""))
        if status is not None:
            args["status"] = str(status)
        if message is not None:
            args["message"] = str(message)
        if details is not None:
            args["details"] = details
        return self._ui.send_command("taskDesigner.updateTask", args=args, timeout_sec=timeout_sec)

    def close(
        self,
        *,
        window_id: str | None = None,
        session_id: str | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        return self._ui.send_command(
            "taskDesigner.close",
            args=self._target_args(window_id=window_id, session_id=session_id),
            timeout_sec=timeout_sec,
        )


class MacroAutomation:
    """Run saved or unsaved Python source against ArcRho's live DFM context."""

    def __init__(self, ui: "ArcRhoUI") -> None:
        self._ui = ui

    def run_source(
        self,
        source: str,
        *,
        filename: str = "untitled_macro.py",
        source_path: str = "",
        timeout_sec: float = 300.0,
    ) -> dict[str, Any]:
        return run_macro_source(
            source,
            filename=filename,
            source_path=source_path,
            timeout_sec=timeout_sec,
            app_url=self._ui.app_url,
        )

    def run_file(self, path: str | os.PathLike[str], *, timeout_sec: float = 300.0) -> dict[str, Any]:
        source_path = Path(path).expanduser().resolve()
        source = source_path.read_text(encoding="utf-8-sig")
        return self.run_source(
            source,
            filename=source_path.name,
            source_path=str(source_path),
            timeout_sec=timeout_sec,
        )


class ArcRhoUI:
    """Convenience object for ArcRho UI automation commands."""

    def __init__(
        self,
        app_url: str | None = None,
        *,
        pid: int | None = None,
        port: int | None = None,
    ) -> None:
        """Pass ``pid`` or ``port`` to reach one of several running apps (see ``running_apps``)."""
        self.app_url = str(app_url or "").strip() or None
        if not self.app_url and (pid is not None or port is not None):
            self.app_url = _discovered_app_url(pid=pid, port=port)
            if not self.app_url:
                raise ArcRhoApiError(f"No running Arco app matches pid={pid}, port={port}.")

    @property
    def base_url(self) -> str:
        return _base_url(self.app_url)

    @property
    def project_instance(self) -> ProjectInstanceAutomation:
        return ProjectInstanceAutomation(self)

    @property
    def task_designer(self) -> TaskDesignerAutomation:
        return TaskDesignerAutomation(self)

    @property
    def macros(self) -> MacroAutomation:
        return MacroAutomation(self)

    def get_app_health(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("app_url", self.app_url)
        return get_app_health(**kwargs)

    def is_app_running(self, **kwargs: Any) -> bool:
        kwargs.setdefault("app_url", self.app_url)
        return is_app_running(**kwargs)

    def wait_for_app(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("app_url", self.app_url)
        return wait_for_app(**kwargs)

    def send_command(self, command: str, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return send_command(command, **kwargs)

    def message_box(self, message: str, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return message_box(message, **kwargs)

    def progress_open(self, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return progress_open(**kwargs)

    def progress_update(self, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return progress_update(**kwargs)

    def progress_close(self, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return progress_close(**kwargs)

    def progress_bar(self, **kwargs: Any) -> ProgressBar:
        return ProgressBar(self, **kwargs)

    def review_table(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return await_review_table(self, payload, **kwargs)

    def project_instance_context(self, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return project_instance_context(**kwargs)

    def reload_project_instance_dataset_table(self, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return reload_project_instance_dataset_table(**kwargs)

    def open_dataset_in_active_project_instance(self, dataset_name: str, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return open_dataset_in_active_project_instance(dataset_name, **kwargs)

    def project_instance_window_action(self, action: str, **kwargs: Any) -> UiCommandResult:
        kwargs.setdefault("app_url", self.app_url)
        return project_instance_window_action(action, **kwargs)

    def active_project_instance_window(self, **kwargs: Any) -> ArcRhoWindow | None:
        kwargs.setdefault("app_url", self.app_url)
        result = active_project_instance_window(**kwargs)
        properties = ArcRhoWindowProperties.from_result(result.result)
        return ArcRhoWindow(self, properties.window_id, properties) if properties.window_id else None

    def window(self, window_id: str) -> ArcRhoWindow:
        return ArcRhoWindow(self, window_id)


task_designer = TaskDesignerAutomation(ArcRhoUI())
