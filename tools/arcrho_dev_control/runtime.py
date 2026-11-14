from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend"
DEV_LAUNCHER = FRONTEND_ROOT / "launch_arcrho_dev_mode.bat"

_ACTION_LOCK = Lock()
_PREFERENCE_PATHS: dict[str, Path] = {}

# Preference discovery walks every project and user folder on the workspace
# share, which costs about a round trip each and measures ~10s here.  The status
# page polls every few seconds, so an uncached scan never finishes before the
# next one starts and the share sees a growing pile of concurrent walks.  These
# files change rarely, so a short cache keeps the page responsive; the clear
# action rediscovers directly and resets the cache.
_PREFERENCE_CACHE_SECONDS = 60.0
_PREFERENCE_CACHE_LOCK = Lock()
_PREFERENCE_CACHE: tuple[float, list[dict[str, str]], list[str]] | None = None


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    parent_pid: int
    name: str
    command_line: str


def _windows_creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run_process(command: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=_windows_creation_flags(),
        check=False,
    )


def _run_launcher(command: list[str], *, timeout: float = 15) -> int:
    """Run the batch launcher without retaining its supervisor's output handles.

    ``launch_arcrho_dev_mode.bat`` starts ``pythonw`` detached.  Capturing the
    batch file's stdout/stderr lets that detached process inherit the capture
    pipes, so ``communicate()`` waits until ArcRho exits even after ``cmd.exe``
    has finished.  The control-center action must finish when the launcher has
    handed off the process tree, not when that tree later stops.
    """

    process = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_windows_creation_flags(),
    )
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        raise RuntimeError("ArcRho's development launcher did not finish its startup handoff.") from error


def _query_windows_processes() -> list[ProcessInfo]:
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = _run_process(["powershell.exe", "-NoProfile", "-Command", script], timeout=12)
    if result.returncode != 0:
        return _query_windows_process_snapshot()
    raw = json.loads(result.stdout or "[]")
    rows = raw if isinstance(raw, list) else [raw]
    output: list[ProcessInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId") or 0)
            parent_pid = int(row.get("ParentProcessId") or 0)
        except (TypeError, ValueError):
            continue
        output.append(
            ProcessInfo(
                pid=pid,
                parent_pid=parent_pid,
                name=str(row.get("Name") or ""),
                command_line=str(row.get("CommandLine") or ""),
            )
        )
    return output


def _query_windows_process_snapshot() -> list[ProcessInfo]:
    """Read PID/parent/image data without WMI, which some standard users cannot query."""

    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class ProcessEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        raise RuntimeError("Could not inspect running processes.")
    entry = ProcessEntry32()
    entry.dwSize = ctypes.sizeof(ProcessEntry32)
    processes: list[ProcessInfo] = []
    try:
        has_entry = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while has_entry:
            pid = int(entry.th32ProcessID)
            processes.append(
                ProcessInfo(
                    pid=pid,
                    parent_pid=int(entry.th32ParentProcessID),
                    name=str(entry.szExeFile),
                    command_line=_query_process_image_path(pid),
                )
            )
            has_entry = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def _query_process_image_path(pid: int) -> str:
    if os.name != "nt" or pid <= 0:
        return ""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _read_runtime_anchor_pids() -> set[int]:
    root = _appdata_root()
    candidates = [root / "app_endpoint.json", root / "app_ui_ready.json"]
    client_dir = _electron_user_data_root() / "backend_clients"
    if client_dir.is_dir():
        try:
            candidates.extend(path for path in client_dir.glob("*.json") if path.is_file())
        except OSError:
            pass
    ports: set[int] = {28765}
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            port = int(payload.get("port") or 0)
            if 0 < port <= 65535:
                ports.add(port)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    pids: set[int] = set()
    for port in ports:
        if _port_hosts_arcrho_backend(port):
            pids.update(_listener_pids(port))
    return pids


def _port_hosts_arcrho_backend(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/app/health", timeout=0.35) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
        project_root = Path(str(payload.get("project_root") or "")).resolve()
        return payload.get("ok") is True and payload.get("app") == "arcrho" and project_root == FRONTEND_ROOT.resolve()
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return False


def _listener_pids(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    result = _run_process(["netstat.exe", "-ano", "-p", "tcp"], timeout=8)
    if result.returncode != 0:
        return set()
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        if f":{port}" not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        try:
            pids.add(int(parts[-1]))
        except (IndexError, ValueError):
            continue
    return pids


def _is_arcrho_dev_process(process: ProcessInfo) -> bool:
    command = process.command_line.replace("/", "\\").lower()
    frontend = str(FRONTEND_ROOT).replace("/", "\\").lower()
    direct_markers = (
        f"{frontend}\\electron_shell.py",
        f"{frontend}\\app_shell.py",
        f"{frontend}\\node_modules\\electron",
    )
    return any(marker in command for marker in direct_markers)


def list_arcrho_dev_processes() -> list[ProcessInfo]:
    processes = _query_windows_processes()
    by_id = {process.pid: process for process in processes}
    by_parent: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        by_parent.setdefault(process.parent_pid, []).append(process)

    selected: dict[int, ProcessInfo] = {
        process.pid: process for process in processes if _is_arcrho_dev_process(process)
    }
    selected.update(
        (pid, by_id[pid]) for pid in _read_runtime_anchor_pids() if pid in by_id
    )

    safe_ancestor_names = {"cmd.exe", "conhost.exe", "electron.exe", "node.exe", "python.exe", "pythonw.exe"}
    ancestor_pending = list(selected)
    while ancestor_pending:
        child_pid = ancestor_pending.pop()
        child = selected[child_pid]
        parent = by_id.get(child.parent_pid)
        if parent is None or parent.pid in selected or parent.name.lower() not in safe_ancestor_names:
            continue
        selected[parent.pid] = parent
        ancestor_pending.append(parent.pid)

    pending = list(selected)
    while pending:
        parent_pid = pending.pop()
        for child in by_parent.get(parent_pid, []):
            if child.pid in selected:
                continue
            selected[child.pid] = child
            pending.append(child.pid)
    return sorted(selected.values(), key=lambda process: (process.name.lower(), process.pid))


def _top_level_process_ids(processes: list[ProcessInfo]) -> list[int]:
    ids = {process.pid for process in processes}
    return sorted(process.pid for process in processes if process.parent_pid not in ids)


def stop_arcrho_dev_processes(timeout: float = 12) -> dict[str, Any]:
    processes = list_arcrho_dev_processes()
    roots = _top_level_process_ids(processes)
    failures: list[str] = []
    for pid in roots:
        result = _run_process(["taskkill.exe", "/PID", str(pid), "/T", "/F"], timeout=8)
        if result.returncode != 0 and "not found" not in result.stderr.lower():
            failures.append(result.stderr.strip() or f"taskkill failed for PID {pid}")

    deadline = time.monotonic() + timeout
    remaining: list[ProcessInfo] = []
    while time.monotonic() < deadline:
        remaining = list_arcrho_dev_processes()
        if not remaining:
            break
        time.sleep(0.25)
    if remaining:
        failures.append("ArcRho processes still running: " + ", ".join(str(item.pid) for item in remaining))
    if failures:
        raise RuntimeError("; ".join(failures))
    return {"stopped": len(processes), "root_processes": roots}


def launch_arcrho_dev() -> dict[str, Any]:
    if not DEV_LAUNCHER.is_file():
        raise RuntimeError(f"Development launcher not found: {DEV_LAUNCHER}")
    if list_arcrho_dev_processes():
        raise RuntimeError("ArcRho development mode is already running. Use Relaunch instead.")
    return_code = _run_launcher(
        ["cmd.exe", "/d", "/s", "/c", "call", str(DEV_LAUNCHER)],
    )
    if return_code != 0:
        raise RuntimeError(f"ArcRho's development launcher failed with exit code {return_code}.")
    time.sleep(0.8)
    return {"launched": True, "processes": len(list_arcrho_dev_processes())}


def relaunch_arcrho_dev() -> dict[str, Any]:
    with _ACTION_LOCK:
        stopped = stop_arcrho_dev_processes()
        launched = launch_arcrho_dev()
    return {**stopped, **launched}


def _appdata_root() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Arco"


def _local_appdata_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Arco"


def _electron_user_data_root() -> Path:
    return _appdata_root() / "profile"


def _documents_root() -> Path:
    return Path.home() / "Documents" / "Arco"


def folder_catalog() -> list[dict[str, Any]]:
    appdata = _appdata_root()
    electron_data = _electron_user_data_root()
    entries = [
        ("appdata", "Application Data", appdata, "Workspace connection, local preferences, and runtime endpoints"),
        ("preferences", "Application Preferences", appdata / "prefs", "Window, shortcut, notebook, and home-folder preferences"),
        ("app-cache", "App Cache", appdata / "cache", "ArcRho scripting and local application caches"),
        ("electron-profile", "Electron Profile", electron_data, "Chromium profile state, host data, cache, and logs"),
        ("app-logs", "Electron Logs", electron_data / "logs", "Electron host and app-server logs"),
        ("browser-storage", "Browser Storage", electron_data / "Local Storage", "Electron renderer localStorage preferences"),
        ("arcbot-sessions", "ArcBot Sessions", electron_data / "arcbot_chat_sessions", "Local ArcBot conversation session files"),
        ("backend-clients", "Backend Client Markers", electron_data / "backend_clients", "Running frontend-to-backend ownership markers"),
        ("updates", "Update Files", electron_data / "updates", "Downloaded update staging and cleanup state"),
        ("local-logs", "Local Runtime Logs", _local_appdata_root() / "logs", "Hosted-save latency and local runtime diagnostics"),
        ("temp-runtime", "Temporary Runtime Files", Path(tempfile.gettempdir()) / "Arco", "Recoverable calculation and editor scratch state"),
        ("arcbot-logs", "ArcBot Request Logs", _documents_root() / "ArcBot" / "request_logs", "Local ArcBot request diagnostics"),
        ("documents", "User ArcRho Files", _documents_root(), "Local macros, scripts, templates, and workflows"),
    ]
    output = []
    for folder_id, label, path, purpose in entries:
        exists = path.is_dir()
        item_count: int | None = None
        if exists:
            try:
                item_count = sum(1 for _ in path.iterdir())
            except OSError:
                item_count = None
        output.append(
            {
                "id": folder_id,
                "label": label,
                "path": str(path),
                "purpose": purpose,
                "exists": exists,
                "item_count": item_count,
            }
        )
    return output


def open_catalog_folder(folder_id: str) -> dict[str, Any]:
    entry = next((item for item in folder_catalog() if item["id"] == folder_id), None)
    if entry is None:
        raise ValueError("Unknown folder.")
    path = Path(entry["path"])
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise RuntimeError("Open Folder is currently supported on Windows only.")
    os.startfile(str(path))  # type: ignore[attr-defined]
    return {"opened": str(path)}


def _electron_cache_paths() -> list[Path]:
    root = _electron_user_data_root().resolve()
    names = (
        "Cache",
        "Code Cache",
        "GPUCache",
        "DawnCache",
        "DawnGraphiteCache",
        "DawnWebGPUCache",
        "Service Worker",
        "Session Storage",
        "Local Storage",
        "WebStorage",
        "databases",
        "IndexedDB",
        "Network",
        "blob_storage",
        "Shared Dictionary",
    )
    return [root / name for name in names]


def clear_cache_and_relaunch() -> dict[str, Any]:
    with _ACTION_LOCK:
        stopped = stop_arcrho_dev_processes()
        root = _electron_user_data_root().resolve()
        removed: list[str] = []
        for path in _electron_cache_paths():
            resolved = path.resolve()
            if resolved.parent != root:
                raise RuntimeError(f"Refusing to clear path outside the Electron profile: {resolved}")
            if resolved.is_dir():
                shutil.rmtree(resolved)
                removed.append(str(resolved))
            elif resolved.exists():
                resolved.unlink()
                removed.append(str(resolved))
        launched = launch_arcrho_dev()
    return {**stopped, **launched, "removed": removed}


def _load_frontend_config():
    import sys

    python_api_src = REPO_ROOT / "python-api" / "src"
    for path in (str(FRONTEND_ROOT), str(python_api_src)):
        if path not in sys.path:
            sys.path.insert(0, path)
    from app_server import config

    config.refresh_runtime_paths()
    return config


def list_project_user_preferences() -> list[dict[str, str]]:
    config = _load_frontend_config()
    projects_root = Path(config.PROJECT_SETTINGS_DIR)
    discovered: list[dict[str, str]] = []
    preference_paths: dict[str, Path] = {}
    if projects_root.is_dir():
        try:
            projects = sorted((item for item in projects_root.iterdir() if item.is_dir()), key=lambda item: item.name.lower())
        except OSError:
            projects = []
        for project in projects:
            users_root = project / "users"
            if not users_root.is_dir():
                continue
            try:
                users = sorted((item for item in users_root.iterdir() if item.is_dir()), key=lambda item: item.name.lower())
            except OSError:
                continue
            for user in users:
                preference_path = user / config.PROJECT_USER_PREFERENCES_FILE
                if not preference_path.is_file():
                    continue
                try:
                    resolved = preference_path.resolve()
                except OSError:
                    continue
                preference_id = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:24]
                preference_paths[preference_id] = resolved
                discovered.append(
                    {
                        "id": preference_id,
                        "project": project.name,
                        "user": user.name,
                        "path": str(resolved),
                    }
                )
    _PREFERENCE_PATHS.clear()
    _PREFERENCE_PATHS.update(preference_paths)
    return discovered


def invalidate_preference_cache() -> None:
    global _PREFERENCE_CACHE
    with _PREFERENCE_CACHE_LOCK:
        _PREFERENCE_CACHE = None


def _preference_state() -> tuple[list[dict[str, str]], list[str]]:
    """Discover preference files, degrading to a warning when they are unreachable.

    ``PROJECT_SETTINGS_DIR`` lives on the workspace share, and loading the
    frontend config resolves that directory eagerly.  A mapped drive that fails
    to reconnect answers ``WinError 5`` there, and ``Path.resolve`` only
    swallows a missing path -- so the denial used to escape ``get_state`` and
    blank the whole page.  The control center is what a developer opens when the
    environment is already broken, so a share outage may cost this card alone
    and not the folder catalog, the process tree, and the run state with it.

    The lock is held across the scan so overlapping polls share one walk of the
    share rather than each starting their own.
    """

    global _PREFERENCE_CACHE
    with _PREFERENCE_CACHE_LOCK:
        cached = _PREFERENCE_CACHE
        if cached is not None and time.monotonic() - cached[0] < _PREFERENCE_CACHE_SECONDS:
            return cached[1], cached[2]
        try:
            preferences, warnings = list_project_user_preferences(), []
        except Exception as error:
            _PREFERENCE_PATHS.clear()
            preferences, warnings = [], [f"Preference files are unavailable: {error}"]
        _PREFERENCE_CACHE = (time.monotonic(), preferences, warnings)
        return preferences, warnings


def clear_project_user_preference_and_relaunch(preference_id: str) -> dict[str, Any]:
    with _ACTION_LOCK:
        current = {item["id"]: item for item in list_project_user_preferences()}
        selected = current.get(str(preference_id or ""))
        path = _PREFERENCE_PATHS.get(str(preference_id or ""))
        if selected is None or path is None:
            raise ValueError("The selected preference file no longer exists. Refresh and choose it again.")
        stopped = stop_arcrho_dev_processes()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.cleared-{stamp}.bak")
        suffix = 1
        while backup.exists():
            backup = path.with_name(f"{path.name}.cleared-{stamp}-{suffix}.bak")
            suffix += 1
        os.replace(path, backup)
        invalidate_preference_cache()
        launched = launch_arcrho_dev()
    return {**stopped, **launched, "cleared": selected, "backup_path": str(backup)}


def _backend_health() -> dict[str, Any]:
    endpoint_path = _appdata_root() / "app_endpoint.json"
    try:
        endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
        host = str(endpoint.get("host") or "127.0.0.1")
        port = int(endpoint.get("port") or 28765)
        with urllib.request.urlopen(f"http://{host}:{port}/app/health", timeout=0.5) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
        return {"reachable": bool(payload.get("ok")), "host": host, "port": port}
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
        return {"reachable": False}


def get_state() -> dict[str, Any]:
    processes = list_arcrho_dev_processes()
    preferences, warnings = _preference_state()
    return {
        "ok": True,
        "running": bool(processes),
        "backend": _backend_health(),
        "processes": [asdict(process) for process in processes],
        "folders": folder_catalog(),
        "preferences": preferences,
        "warnings": warnings,
        "launcher": str(DEV_LAUNCHER),
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
