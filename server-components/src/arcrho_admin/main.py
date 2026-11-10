import argparse
import atexit
import getpass
import json
import os
import re
import subprocess
import sys
import time


def early_log_event(message):
    try:
        base_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "arcrho_admin.log")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, mode="a", encoding="utf-8") as file:
            file.write(f"{stamp} {message}\n")
    except OSError:
        pass


early_log_event(f"python module entry pid={os.getpid()} frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")

import socket
import tempfile
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = MODULE_ROOT.parent
PRODUCT_ROOT = SOURCE_ROOT.parent
CANONICAL_SOURCE_ROOT = PRODUCT_ROOT.parent / "python-api" / "src"
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", MODULE_ROOT)).resolve()
EXE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None

for path in (PRODUCT_ROOT, SOURCE_ROOT, CANONICAL_SOURCE_ROOT, BUNDLE_ROOT):
    if str(path) not in sys.path and path.exists():
        sys.path.insert(0, str(path))

try:
    from src.server_config import (
        default_server_config,
        merge_missing_defaults,
        read_server_config,
        resolve_server_config_path,
        with_server_id,
        write_server_config,
    )
    from src.utils import get_config_value, get_project_root, resolve_app_exe, resolve_app_path
except ModuleNotFoundError:
    from server_config import (
        default_server_config,
        merge_missing_defaults,
        read_server_config,
        resolve_server_config_path,
        with_server_id,
        write_server_config,
    )
    from utils import get_config_value, get_project_root, resolve_app_exe, resolve_app_path

from arcrho_log_retention_contract import apply_log_retention
from arcrho_server_component_status import (
    COMPONENT_ROLES,
    DEFAULT_STALE_AFTER_SECONDS,
    instance_folder,
    list_instances as list_component_instances,
    stale_after_seconds_by_role,
)

def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DEFAULT_PORT = env_int("ARCRHO_ADMIN_PORT", 28766)
HEARTBEAT_INTERVAL_SECONDS = 2
# Deploys stop Admin Control through this switch so the live folder can be
# swapped; nothing else sets it, and the build clears it again afterwards.
KILL_ALL_KEY = "apps.admin.kill_all"
HEARTBEAT_WRITE_ATTEMPTS = 5
PROJECT_ROOT = get_project_root()
os.environ.setdefault("ARCRHO_ROOT", str(PROJECT_ROOT))
CONFIG_FILE = resolve_server_config_path(PROJECT_ROOT)
LOG_FILE = PROJECT_ROOT / "runtime" / "logs" / "arcrho_admin.log"
DEPLOY_LOG_FILE = (EXE_DIR or MODULE_ROOT) / "arcrho_admin.log"


def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_config():
    return default_server_config(PROJECT_ROOT)


def merge_defaults(config, defaults):
    return merge_missing_defaults(config, defaults)


def load_config():
    return read_server_config(CONFIG_FILE, PROJECT_ROOT)


def save_config(config):
    write_server_config(CONFIG_FILE, config)


def set_nested_value(data, key_path, value):
    parts = key_path.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_event(message):
    line = f"{current_timestamp()} {message}\n"
    for log_file in (DEPLOY_LOG_FILE, LOG_FILE):
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, mode="a", encoding="utf-8") as file:
                file.write(line)
        except OSError:
            pass


def apply_admin_log_retention():
    """Keep both Admin Control logs inside the shared retention window.

    Admin Control appends to one log under the server root and one beside its
    own executable, and neither ever changes name, so the old lines are dropped
    rather than the files.
    """

    for log_file in (LOG_FILE, DEPLOY_LOG_FILE):
        apply_log_retention(log_file.parent, appended_files=(log_file,))


def log_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc_value, exc_traceback)
    log_event("unhandled exception\n" + "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    return sys.__excepthook__(exc_type, exc_value, exc_traceback)


def log_thread_exception(args):
    log_event(
        f"unhandled thread exception thread={getattr(args.thread, 'name', '')}\n"
        + "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    )


sys.excepthook = log_unhandled_exception
if hasattr(threading, "excepthook"):
    threading.excepthook = log_thread_exception
atexit.register(lambda: log_event(f"process exiting pid={os.getpid()}"))
log_event(
    f"module loaded pid={os.getpid()} frozen={getattr(sys, 'frozen', False)} "
    f"exe={sys.executable} exe_dir={EXE_DIR} root={PROJECT_ROOT} config={CONFIG_FILE}"
)

import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


def admin_instance_id():
    stamp = datetime.now().strftime("%y%m%d-%H%M%S")
    return f"{socket.gethostname()}@{getpass.getuser()}@{os.getpid()}@{stamp}"


def write_json(path, payload, attempts=HEARTBEAT_WRITE_ATTEMPTS):
    path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, attempts + 1):
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.{attempt}.tmp")
        try:
            with open(temp_path, mode="w", encoding="utf-8") as file:
                json.dump(payload, file, indent=2)
                file.write("\n")
            os.replace(temp_path, path)
            return
        except OSError:
            safe_unlink(temp_path)
            if attempt == attempts:
                raise
            time.sleep(0.1 * attempt)


def safe_unlink(path):
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def admin_heartbeat_payload(instance_id, created):
    return {
        "Server": instance_id,
        "Role": "admin",
        "User": getpass.getuser(),
        "Created": created,
        "Last seen": current_timestamp(),
    }


def start_admin_heartbeat(server, instance_path):
    instance_id = instance_path.stem
    created = current_timestamp()
    write_json(instance_path, admin_heartbeat_payload(instance_id, created))
    log_event(f"started pid={os.getpid()} instance={instance_path}")

    def monitor():
        while True:
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)
            if getattr(server, "shutdown_requested", False):
                log_event(f"heartbeat stopped pid={os.getpid()} reason=shutdown_requested")
                return
            try:
                # A deploy cannot rename this app's folder while the server holds
                # it, so it asks for the same graceful shutdown the UI does and
                # waits for the heartbeat to disappear.
                if get_config_value(KILL_ALL_KEY, False):
                    shutdown_server(server, "kill_all")
                    return
            except Exception:
                log_event(f"kill switch read failed pid={os.getpid()}\n{traceback.format_exc()}")
            try:
                if not instance_path.exists():
                    log_event(f"heartbeat missing; recreating pid={os.getpid()} instance={instance_path}")
                write_json(instance_path, admin_heartbeat_payload(instance_id, created))
            except Exception:
                log_event(f"heartbeat write failed pid={os.getpid()}\n{traceback.format_exc()}")

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    return thread


def instance_sources():
    root = get_project_root()
    return {role: (label, instance_folder(root, role)) for role, label in COMPONENT_ROLES.items()}


def resolve_source_main(role):
    path = SOURCE_ROOT / f"arcrho_{role}" / "main.py"
    return path if path.exists() else None


def list_instances():
    return list_component_instances(get_project_root())


def remove_instance(role, name):
    sources = instance_sources()
    if role not in sources:
        raise ValueError(f"Unknown role: {role}")
    if not name.lower().endswith(".json") or Path(name).name != name:
        raise ValueError("Invalid instance file name")

    path = sources[role][1] / name
    folder = sources[role][1].resolve()
    resolved = path.resolve()
    if folder not in resolved.parents:
        raise ValueError("Instance path is outside the expected folder")
    if resolved.exists():
        resolved.unlink()
        return True
    return False


def clear_stale_instances():
    removed = []
    for item in list_instances():
        if item.get("status") != "Stale":
            continue
        try:
            if remove_instance(item["role"], item["name"]):
                removed.append(item)
        except (OSError, ValueError):
            log_event(f"failed to remove stale instance role={item.get('role')} name={item.get('name')}")
    return removed


def start_component_instance(role):
    exe = resolve_app_exe(role)
    if exe is not None and exe.exists():
        # Each app runs with its own folder as working directory so it never
        # keeps this app's folder locked against a redeploy.
        process = subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)
        log_event(f"started {role} exe={exe} pid={process.pid}")
        return {"started": True, "pid": process.pid, "path": str(exe)}

    source_main = resolve_source_main(role)
    if source_main is not None:
        process = subprocess.Popen([sys.executable, str(source_main)], close_fds=True)
        log_event(f"started {role} source={source_main} pid={process.pid}")
        return {"started": True, "pid": process.pid, "path": str(source_main)}

    raise FileNotFoundError(f"Could not find ArcRho {role} executable or source main.py")


def start_orchestrator_instance():
    return start_component_instance("orchestrator")


def start_bridge_instance():
    config = load_config()
    bridge_config = config.get("apps", {}).get("bridge", {})
    if bridge_config.get("kill_all", False):
        return {"started": False, "message": "Bridge is stopped by config"}

    # Bridges are per user session: every ResQ user contributes one bridge on
    # their own ResQ GUI/license, so the cap counts only the current user.
    max_instances = max(0, min(int(bridge_config.get("max_instances", 1)), 1))
    if max_instances == 0:
        return {"started": False, "message": "Bridge max instances is 0"}

    current_user = getpass.getuser().casefold()
    active_bridge_count = sum(
        1 for item in list_instances()
        if item.get("role") == "bridge"
        and item.get("status") == "Active"
        and str(item.get("user") or "").casefold() == current_user
    )
    if active_bridge_count >= max_instances:
        return {"started": False, "message": "Bridge instance already running for this user"}

    return start_component_instance("bridge")


FOLDER_ACCESS_PRESETS = (
    {"key": "root", "label": "ArcRho Server (entire folder)", "relative": ""},
    {"key": "runtime", "label": "runtime (instance heartbeats)", "relative": "runtime"},
    {"key": "requests", "label": "requests (job queues)", "relative": "requests"},
    {"key": "projects", "label": "projects (project data)", "relative": "projects"},
    {"key": "shared", "label": "shared (macro library)", "relative": "shared"},
    {"key": "config", "label": "config", "relative": "config"},
)
FOLDER_ACCESS_RIGHTS = {"modify": "M", "full": "F", "read": "RX"}
_PRINCIPAL_FORBIDDEN_CHARS = set('/:;,*?"<>|()=+[]')


def resolve_access_folder(key_or_relative):
    """Map a preset key or relative path to a folder inside the server root."""

    value = str(key_or_relative or "").strip()
    for preset in FOLDER_ACCESS_PRESETS:
        if value == preset["key"]:
            value = preset["relative"]
            break
    base = PROJECT_ROOT.resolve()
    target = (base / value).resolve() if value else base
    if target != base and base not in target.parents:
        raise ValueError("Folder must be inside the ArcRho Server root")
    if not target.is_dir():
        raise ValueError(f"Folder does not exist: {target}")
    return target


def validate_principal(principal):
    name = str(principal or "").strip()
    if not name:
        raise ValueError("Account or group name is required")
    if any(char in _PRINCIPAL_FORBIDDEN_CHARS or ord(char) < 32 for char in name):
        raise ValueError("Account or group name contains invalid characters")
    return name


def _decode_console_output(raw):
    for encoding in ("oem", "mbcs", "utf-8"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _user_profile_directories():
    system_drive = os.environ.get("SystemDrive") or "C:"
    profile_root = Path(system_drive if system_drive.endswith("\\") else f"{system_drive}\\") / "Users"
    names = [entry.name for entry in profile_root.iterdir() if entry.is_dir()]
    return sorted(names, key=str.casefold)


def folder_access_principals():
    try:
        names = _user_profile_directories()
    except OSError as exc:
        return {"options": [], "warnings": [str(exc)]}
    domain = str(os.environ.get("USERDOMAIN") or "PRCINS").strip() or "PRCINS"
    return {
        "options": [
            {"value": f"{domain}\\{name}", "label": f"{domain}\\{name}"}
            for name in names
        ],
        "warnings": [],
    }


def run_icacls(args):
    result = subprocess.run(
        ["icacls.exe", *args],
        capture_output=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return (
        result.returncode,
        _decode_console_output(result.stdout).strip(),
        _decode_console_output(result.stderr).strip(),
    )


def parse_icacls_entries(output, folder):
    entries = []
    prefix = str(folder)
    for line in output.splitlines():
        text = line.strip()
        if not text or text.lower().startswith("successfully processed"):
            continue
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
        if ":" not in text:
            continue
        principal, _, rights = text.rpartition(":")
        tokens = {
            token.strip()
            for group in re.split(r"[()]+", rights)
            if group
            for token in group.split(",")
            if token.strip()
        }
        entries.append(
            {
                "principal": principal.strip(),
                "rights": rights.strip(),
                "inherited": "I" in tokens,
                "modify": bool(tokens & {"F", "M"}),
                "delete": bool(tokens & {"F", "M", "D", "DE"}),
            }
        )
    return entries


def folder_access_report(folder):
    code, out, err = run_icacls([str(folder)])
    if code != 0:
        raise OSError(err or out or f"icacls failed with exit code {code}")
    return {
        "path": str(folder),
        "entries": parse_icacls_entries(out, folder),
        "raw": out,
    }


def grant_folder_access(folder, principal, access="modify"):
    right = FOLDER_ACCESS_RIGHTS.get(str(access or "modify").strip().lower())
    if right is None:
        raise ValueError(
            "Access level must be one of: " + ", ".join(sorted(FOLDER_ACCESS_RIGHTS))
        )
    # (OI)(CI) makes the grant inheritable, so heartbeat, request, and project
    # files created later by any user's components keep the same rights and
    # every user can claim requests and clean up stale heartbeats.
    code, out, err = run_icacls(
        [str(folder), "/grant", f"{principal}:(OI)(CI){right}"]
    )
    message = err or out
    if code != 0:
        raise OSError(message or f"icacls failed with exit code {code}")
    log_event(f"folder access granted principal={principal} right={right} folder={folder}")
    return message


def revoke_folder_access(folder, principal):
    code, out, err = run_icacls([str(folder), "/remove:g", principal])
    message = err or out
    if code != 0:
        raise OSError(message or f"icacls failed with exit code {code}")
    log_event(f"folder access revoked principal={principal} folder={folder}")
    return message


def shutdown_server(server, reason):
    if getattr(server, "shutdown_requested", False):
        return
    server.shutdown_requested = True
    log_event(f"shutdown requested pid={os.getpid()} reason={reason}")
    instance_path = getattr(server, "admin_instance_path", None)
    if instance_path is not None:
        safe_unlink(instance_path)
    threading.Thread(target=server.shutdown, daemon=True).start()


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "ArcRhoAdmin/1.0"

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.send_file(resource_path("index.html"), "text/html; charset=utf-8")
        elif parsed.path == "/api/health":
            self.send_json({"ok": True})
        elif parsed.path == "/api/config":
            self.send_json({"path": str(CONFIG_FILE), "config": load_config()})
        elif parsed.path == "/api/folder-access":
            query = parse_qs(parsed.query)
            folder_key = query.get("folder", ["root"])[0]
            try:
                folder = resolve_access_folder(folder_key)
                report = folder_access_report(folder)
                self.send_json(
                    {
                        "ok": True,
                        "presets": list(FOLDER_ACCESS_PRESETS),
                        "report": report,
                    }
                )
            except ValueError as exc:
                self.send_error(400, str(exc))
            except OSError as exc:
                log_event(f"folder access report failed\n{traceback.format_exc()}")
                self.send_error(500, str(exc))
        elif parsed.path == "/api/folder-access/principals":
            self.send_json({"ok": True, **folder_access_principals()})
        elif parsed.path == "/api/instances":
            self.send_json(
                {
                    "instances": list_instances(),
                    "stale_after_seconds": DEFAULT_STALE_AFTER_SECONDS,
                    "stale_after_seconds_by_role": stale_after_seconds_by_role(),
                }
            )
        else:
            self.send_error(404, "Not found")

    def do_PATCH(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/config":
            self.send_error(404, "Not found")
            return

        payload = self.read_json_body()
        key_path = payload.get("path")
        if not key_path:
            self.send_error(400, "Missing config path")
            return

        config = load_config()
        set_nested_value(config, key_path, payload.get("value"))
        save_config(config)
        self.send_json({"ok": True, "path": str(CONFIG_FILE), "config": config})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/instances":
            self.send_error(404, "Not found")
            return

        query = parse_qs(parsed.query)
        role = query.get("role", [""])[0]
        name = query.get("name", [""])[0]
        try:
            removed = remove_instance(role, name)
            self.send_json({"ok": True, "removed": removed, "instances": list_instances()})
            admin_instance_path = getattr(self.server, "admin_instance_path", None)
            if role == "admin" and admin_instance_path is not None and name == admin_instance_path.name:
                shutdown_server(self.server, "current admin instance removed")
        except ValueError as exc:
            self.send_error(400, str(exc))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/open-config-folder":
            os.startfile(CONFIG_FILE.parent)
            self.send_json({"ok": True})
        elif parsed.path == "/api/reset-config":
            # A reset keeps the server's identity; see with_server_id.
            config = with_server_id(default_config(), keep_from=load_config())
            save_config(config)
            self.send_json({"ok": True, "path": str(CONFIG_FILE), "config": config})
        elif parsed.path == "/api/clear-stale-instances":
            removed = clear_stale_instances()
            self.send_json({"ok": True, "removed": len(removed), "instances": list_instances()})
        elif parsed.path == "/api/start-orchestrator":
            try:
                result = start_orchestrator_instance()
                self.send_json({"ok": True, **result, "instances": list_instances()})
            except (FileNotFoundError, OSError) as exc:
                log_event(f"start orchestrator failed\n{traceback.format_exc()}")
                self.send_error(500, str(exc))
        elif parsed.path == "/api/start-bridge":
            try:
                result = start_bridge_instance()
                self.send_json({"ok": True, **result, "instances": list_instances()})
            except (FileNotFoundError, OSError) as exc:
                log_event(f"start bridge failed\n{traceback.format_exc()}")
                self.send_error(500, str(exc))
        elif parsed.path in ("/api/folder-access/grant", "/api/folder-access/revoke"):
            payload = self.read_json_body()
            try:
                folder = resolve_access_folder(payload.get("folder", "root"))
                principal = validate_principal(payload.get("principal"))
                if parsed.path.endswith("/grant"):
                    message = grant_folder_access(
                        folder, principal, payload.get("access", "modify")
                    )
                else:
                    message = revoke_folder_access(folder, principal)
                self.send_json(
                    {
                        "ok": True,
                        "message": message,
                        "report": folder_access_report(folder),
                    }
                )
            except ValueError as exc:
                self.send_error(400, str(exc))
            except OSError as exc:
                log_event(f"folder access change failed\n{traceback.format_exc()}")
                self.send_error(500, str(exc))
        elif parsed.path == "/api/shutdown":
            self.send_json({"ok": True})
            shutdown_server(self.server, "api shutdown")
        else:
            self.send_error(404, "Not found")

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_file(self, path, content_type):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, f"Missing file: {path}")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def make_server(port):
    server = ThreadingHTTPServer(("127.0.0.1", port), AdminHandler)
    server.shutdown_requested = False
    server.admin_instance_path = None
    return server


class StartupSplash:
    def __init__(self, port):
        self.port = port
        self._ready = threading.Event()
        self._path = None

    def start(self):
        try:
            self._path = Path(tempfile.gettempdir()) / f"arcrho_admin_splash_{os.getpid()}.html"
            self._path.write_text(self._html(), encoding="utf-8")
            webbrowser.open(self._path.as_uri())
        except Exception:
            log_event(f"splash failed\n{traceback.format_exc()}")
        finally:
            self._ready.set()

    def close(self):
        return

    def _html(self):
        port = int(self.port)
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Arco Admin Control</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f3b67;
      --muted: #5d6a7f;
      --line: #dfe6ef;
      --blue: #2563eb;
      --blue-soft: #dbeafe;
      --page: #f4f7fb;
      --panel: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: var(--page);
      color: var(--ink);
      font-family: "Segoe UI", Arial, sans-serif;
    }}
    main {{
      width: min(440px, calc(100vw - 32px));
      padding: 28px 30px 30px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 18px 42px rgba(31, 59, 103, 0.12);
    }}
    .brand {{
      display: grid;
      grid-template-columns: 52px 1fr;
      gap: 18px;
      align-items: center;
    }}
    .mark {{
      width: 52px;
      height: 52px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: var(--blue-soft);
    }}
    .mark::before {{
      content: "";
      width: 25px;
      height: 25px;
      border-radius: 5px;
      background: var(--blue);
      box-shadow: inset 0 0 0 7px #fff;
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    p {{
      margin: 7px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .status {{
      margin-top: 28px;
      font-size: 12px;
      font-weight: 600;
      color: #4d5b71;
    }}
    .bar {{
      position: relative;
      height: 8px;
      margin-top: 14px;
      overflow: hidden;
      border-radius: 999px;
      background: #e2e8f0;
    }}
    .bar::after {{
      content: "";
      position: absolute;
      inset-block: 0;
      width: 34%;
      border-radius: inherit;
      background: var(--blue);
      animation: slide 1.1s ease-in-out infinite;
    }}
    @keyframes slide {{
      from {{ transform: translateX(-110%); }}
      to {{ transform: translateX(320%); }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="brand">
      <div class="mark" aria-hidden="true"></div>
      <div>
        <h1>Arco Admin Control</h1>
        <p>Starting the local admin server.</p>
      </div>
    </div>
    <div class="status" id="status">Preparing workspace</div>
    <div class="bar" aria-hidden="true"></div>
  </main>
  <script>
    const port = {port};
    const statusEl = document.getElementById("status");

    async function probe() {{
      const url = `http://127.0.0.1:${{port}}/`;
      try {{
        const response = await fetch(`${{url}}api/health`, {{cache: "no-store"}});
        if (response.ok) {{
          window.location.replace(url);
          return true;
        }}
      }} catch (err) {{}}
      return false;
    }}

    async function poll() {{
      statusEl.textContent = `Waiting for local admin server on port ${{port}}`;
      if (await probe()) return;
      setTimeout(poll, 700);
    }}

    poll();
  </script>
</body>
</html>
"""


def is_admin_server(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/config", timeout=0.35) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload.get("config"), dict) and "path" in payload
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def request_admin_shutdown(port):
    request = Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"", method="POST")
    try:
        with urlopen(request, timeout=0.35):
            return True
    except (OSError, URLError):
        return False


def wait_for_admin_shutdown(port, timeout_seconds=3.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_admin_server(port):
            return True
        time.sleep(0.1)
    return not is_admin_server(port)


def get_port_listener_pids(port):
    if os.name != "nt":
        return []

    try:
        result = subprocess.run(
            ["netstat.exe", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return []

    pids = set()
    for line in result.stdout.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        if local_address.rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid > 0 and pid != os.getpid():
            pids.add(pid)
    return sorted(pids)


def kill_port_listeners(port):
    killed = []
    for pid in get_port_listener_pids(port):
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            killed.append(pid)
        except OSError:
            pass
    return killed


def wait_for_port_clear(port, timeout_seconds=3.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not get_port_listener_pids(port):
            return True
        time.sleep(0.1)
    return not get_port_listener_pids(port)


def clear_existing_admin_port(port):
    if is_admin_server(port):
        if request_admin_shutdown(port) and wait_for_admin_shutdown(port):
            print(f"Closed previous Arco Admin Control server on port {port}")
            return
        print(f"Previous Arco Admin Control server on port {port} did not close gracefully")

    pids = kill_port_listeners(port)
    if pids:
        print(f"Killed process(es) listening on Admin Control port {port}: {', '.join(map(str, pids))}")
    if not wait_for_port_clear(port):
        raise OSError(f"Port {port} is still in use")


def main():
    parser = argparse.ArgumentParser(description="Run Arco Admin Control in a local browser.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-splash", action="store_true")
    args = parser.parse_args()

    server = None
    apply_admin_log_retention()
    log_event(f"main starting pid={os.getpid()} frozen={getattr(sys, 'frozen', False)} root={PROJECT_ROOT}")
    splash = None if args.no_splash or args.no_browser else StartupSplash(args.port)
    if splash:
        log_event(f"splash starting pid={os.getpid()}")
        splash.start()

    try:
        log_event(f"clearing existing listener pid={os.getpid()} port={args.port}")
        clear_existing_admin_port(args.port)

        log_event(f"creating server pid={os.getpid()} port={args.port}")
        server = make_server(args.port)
        server.admin_instance_path = resolve_app_path("admin", "instances", f"{admin_instance_id()}.json")
        log_event(f"starting heartbeat pid={os.getpid()} instance={server.admin_instance_path}")
        start_admin_heartbeat(server, server.admin_instance_path)
        url = f"http://127.0.0.1:{server.server_port}/"
        log_event(f"server ready pid={os.getpid()} url={url}")
        print(f"Arco Admin Control: {url}")

        if not args.no_browser and splash is None:
            webbrowser.open(url)
    except Exception:
        log_event(f"startup failed pid={os.getpid()}\n{traceback.format_exc()}")
        raise
    finally:
        if splash:
            splash.close()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server is not None:
            server.shutdown_requested = True
            safe_unlink(server.admin_instance_path)
            server.server_close()
            log_event(f"stopped pid={os.getpid()}")


if __name__ == "__main__":
    main()



