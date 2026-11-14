"""UI automation helpers for the ArcRho regression harness.

`arcrho_api.ui` is tuned for macro authors: its helpers raise on failure, which is what a macro
wants. A regression harness wants the opposite - a failed command is a recorded result, not an
exception - and it needs commands macros never use: screenshots, synthetic input, tab lifecycle,
and the pointer overlay.

Transport lives in `arcrho_api.ui` and is reused here rather than duplicated.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import LOCAL_APP_FOLDER_NAME
from .ui import UiCommandResult, _base_url, _post_json

__all__ = [
    "UiTestClient",
    "app_ui_ready_marker_path",
    "read_ui_ready_marker",
    "wait_for_ui_ready",
]

# Keep in step with `getUiReadyMarkerPath` in frontend/electron/main.js.
UI_READY_MARKER_FILE = "app_ui_ready.json"
UI_READY_MARKER_FORMAT = "arcrho.app_ui_ready.v1"


def app_ui_ready_marker_path(*, app_mode: str = "arcrho", env: dict[str, str] | None = None) -> Path:
    """Path of the marker Electron writes once the main window is actually visible."""

    environ = env if env is not None else os.environ
    appdata = str(environ.get("APPDATA") or "").strip()
    if not appdata:
        appdata = str(Path.home() / "AppData" / "Roaming")
    folder = "Arcode" if str(app_mode).strip().lower() == "arcode" else LOCAL_APP_FOLDER_NAME
    return Path(appdata) / folder / UI_READY_MARKER_FILE


def read_ui_ready_marker(
    *,
    app_mode: str = "arcrho",
    env: dict[str, str] | None = None,
    pid: int | None = None,
) -> dict[str, Any] | None:
    """The newest app's ready entry, or the entry of the app with process id ``pid``."""

    path = app_ui_ready_marker_path(app_mode=app_mode, env=env)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    entries = payload.get("apps") if isinstance(payload.get("apps"), list) else [payload]
    for entry in entries:
        if not isinstance(entry, dict) or str(entry.get("format") or "") != UI_READY_MARKER_FORMAT:
            continue
        if pid is not None and str(entry.get("pid")) != str(pid):
            continue
        return entry
    return None


def wait_for_ui_ready(
    *,
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 0.5,
    app_mode: str = "arcrho",
    env: dict[str, str] | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    """Block until the ArcRho window is painted and visible; with ``pid``, that app's window.

    Waiting on `app_endpoint.json` instead would return while the splash screen is still up,
    because that file is written when the *backend* becomes ready.
    """

    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    last: dict[str, Any] | None = None
    while True:
        last = read_ui_ready_marker(app_mode=app_mode, env=env, pid=pid)
        if last is not None:
            return last
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Arco UI did not report ready within {timeout_sec:.0f}s "
                f"(marker: {app_ui_ready_marker_path(app_mode=app_mode, env=env)})"
            )
        time.sleep(max(0.05, float(poll_interval_sec)))


@dataclass
class UiTestClient:
    """Non-raising client for the UI automation bus.

    Every method returns a `UiCommandResult`; callers inspect `.ok` rather than catching. That
    keeps a failing assertion inside the report instead of aborting the run.
    """

    app_url: str | None = None
    default_timeout_sec: float = 30.0
    window: str = ""
    _issued: list[str] = field(default_factory=list, repr=False)

    # -- transport ---------------------------------------------------------------

    def command(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        timeout_sec: float | None = None,
        target: dict[str, Any] | None = None,
    ) -> UiCommandResult:
        timeout = float(timeout_sec if timeout_sec is not None else self.default_timeout_sec)
        payload = {
            "command": str(name or "").strip(),
            "target": target or {},
            "args": args or {},
            "timeout_sec": timeout,
        }
        try:
            # Allow slack over the service deadline so the service's own timeout reports first and
            # we get a structured error instead of a socket exception.
            response = _post_json(
                "/ui_automation/commands", payload, timeout + 15.0, app_url=self.app_url
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed step, not a crash
            return UiCommandResult(ok=False, result={}, error=f"{type(exc).__name__}: {exc}")

        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        out = UiCommandResult(
            ok=bool(response.get("ok")),
            result=result,
            error=str(response.get("error") or ""),
            command_id=str(response.get("command_id") or ""),
        )
        if out.command_id:
            self._issued.append(out.command_id)
        return out

    def cancel(self, command_id: str) -> dict[str, Any]:
        try:
            return _post_json(
                f"/ui_automation/commands/{command_id}/cancel", {}, 10.0, app_url=self.app_url
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def drain(self) -> dict[str, Any]:
        """Cancel everything outstanding. Call between scenarios so one cannot bleed into the next."""
        try:
            return _post_json("/ui_automation/commands/drain", {}, 10.0, app_url=self.app_url)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def queue_status(self) -> dict[str, Any]:
        url = f"{_base_url(self.app_url)}/ui_automation/queue"
        try:
            request = Request(url, method="GET")
            with urlopen(request, timeout=10.0) as response:  # noqa: S310 - localhost only
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    # -- shell -------------------------------------------------------------------

    def list_tabs(self) -> UiCommandResult:
        return self.command("shell.listTabs")

    def open_tab(self, tab_type: str, **args: Any) -> UiCommandResult:
        return self.command("shell.openTab", {"type": tab_type, **args})

    def activate_tab(self, **match: Any) -> UiCommandResult:
        return self.command("shell.activateTab", match)

    def close_tab(self, *, skip_confirm: bool = True, **match: Any) -> UiCommandResult:
        return self.command("shell.closeTab", {"skipConfirm": skip_confirm, **match})

    def dismiss_dialogs(self) -> UiCommandResult:
        return self.command("ui.dismissDialogs", timeout_sec=10.0)

    def list_windows(self) -> UiCommandResult:
        return self.command("ui.listWindows", timeout_sec=10.0)

    # -- project instance --------------------------------------------------------

    def select_path(self, path: str, *, reveal: bool = True, timeout_sec: float = 60.0) -> UiCommandResult:
        return self.command(
            "projectInstance.selectPath",
            {"path": path, "reveal": reveal, "timeoutMs": int(timeout_sec * 1000)},
            timeout_sec=timeout_sec,
        )

    def project_instance_context(self) -> UiCommandResult:
        return self.command("projectInstance.context")

    def open_dataset(
        self,
        name: str,
        *,
        open_method: bool = False,
        method_type: str = "",
        timeout_sec: float = 60.0,
    ) -> UiCommandResult:
        args: dict[str, Any] = {"name": name, "timeoutMs": int(timeout_sec * 1000)}
        if open_method:
            args["openMethod"] = True
            if method_type:
                args["methodType"] = method_type
        return self.command("projectInstance.openDataset", args, timeout_sec=timeout_sec)

    # -- capture and input -------------------------------------------------------

    def capture_screenshot(
        self,
        name: str,
        *,
        path: str | Path | None = None,
        review: bool = False,
        window: str = "",
        rect: dict[str, Any] | None = None,
        timeout_sec: float = 30.0,
    ) -> UiCommandResult:
        args: dict[str, Any] = {"name": name, "review": review}
        if path is not None:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            args["path"] = str(target)
        if window or self.window:
            args["window"] = window or self.window
        if rect:
            args["rect"] = rect
        return self.command("ui.captureScreenshot", args, timeout_sec=timeout_sec)

    def save_screenshot(self, name: str, path: str | Path, **kwargs: Any) -> UiCommandResult:
        """Capture straight to disk, falling back to decoding a data URL if the host returned one."""

        outcome = self.capture_screenshot(name, path=path, **kwargs)
        if not outcome.ok:
            return outcome
        if outcome.result.get("path"):
            return outcome
        data_url = str(outcome.result.get("dataUrl") or "")
        if data_url.startswith("data:image/png;base64,"):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
            outcome.result["path"] = str(target)
        return outcome

    def click_at(
        self,
        x: float,
        y: float,
        *,
        button: str = "left",
        click_count: int = 1,
        travel_ms: int | None = None,
        modifiers: list[str] | None = None,
    ) -> UiCommandResult:
        args: dict[str, Any] = {
            "x": x,
            "y": y,
            "button": button,
            "clickCount": max(1, int(click_count)),
        }
        if travel_ms is not None:
            args["travelMs"] = max(0, int(travel_ms))
        if modifiers:
            args["modifiers"] = list(modifiers)
        if self.window:
            args["window"] = self.window
        return self.command("ui.clickAt", args)

    def type_text(self, text: str) -> UiCommandResult:
        args: dict[str, Any] = {"text": text}
        if self.window:
            args["window"] = self.window
        return self.command("ui.typeText", args)

    def press_key(self, key: str, *, modifiers: list[str] | None = None) -> UiCommandResult:
        args: dict[str, Any] = {"key": key}
        if modifiers:
            args["modifiers"] = list(modifiers)
        if self.window:
            args["window"] = self.window
        return self.command("ui.pressKey", args)

    def send_input(self, events: list[dict[str, Any]]) -> UiCommandResult:
        args: dict[str, Any] = {"events": events}
        if self.window:
            args["window"] = self.window
        return self.command("ui.sendInput", args)

    # -- pointer overlay ---------------------------------------------------------

    def set_pointer(self, enabled: bool) -> UiCommandResult:
        return self.command("ui.pointer", {"enabled": bool(enabled)}, timeout_sec=10.0)

    def move_pointer(self, x: float, y: float, *, travel_ms: int = 0) -> UiCommandResult:
        return self.command(
            "ui.pointer",
            {"x": x, "y": y, "travelMs": max(0, int(travel_ms))},
            timeout_sec=15.0,
        )
