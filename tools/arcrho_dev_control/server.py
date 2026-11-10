from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.arcrho_dev_control import runtime


HTML_PATH = Path(__file__).with_name("index.html")
DEV_CONTROL_PORT = 28768


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True
    # ``TCPServer`` turns on SO_REUSEADDR, which on Windows lets a second
    # process bind a port another process already listens on.  Both servers then
    # answer this URL and the browser reaches whichever the stack picks, so
    # restarting to pick up a code change silently keeps serving the old build.
    # Refusing the duplicate bind turns that into a startup error instead.
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]):
        super().__init__(address, handler)
        self.control_token = secrets.token_urlsafe(32)


class ControlHandler(BaseHTTPRequestHandler):
    server: ControlServer

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, error: Exception) -> None:
        status = HTTPStatus.BAD_REQUEST if isinstance(error, ValueError) else HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_json({"ok": False, "error": str(error)}, status)

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("X-ArcRho-Control-Token", ""),
            self.server.control_token,
        )

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            html = HTML_PATH.read_text(encoding="utf-8").replace(
                "__CONTROL_TOKEN__",
                json.dumps(self.server.control_token),
            )
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/state":
            try:
                self._send_json(runtime.get_state())
            except Exception as error:
                self._send_error_json(error)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/action":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._send_json({"ok": False, "error": "Unauthorized request."}, HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 2 or length > 8192:
                raise ValueError("Invalid request size.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            action = str(payload.get("action") or "")
            if action == "launch":
                result = runtime.launch_arcrho_dev()
            elif action == "relaunch":
                result = runtime.relaunch_arcrho_dev()
            elif action == "clear_cache":
                result = runtime.clear_cache_and_relaunch()
            elif action == "clear_preference":
                result = runtime.clear_project_user_preference_and_relaunch(str(payload.get("preference_id") or ""))
            elif action == "open_folder":
                result = runtime.open_catalog_folder(str(payload.get("folder_id") or ""))
            elif action == "stop_control":
                result = {"stopping": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                raise ValueError("Unknown action.")
            self._send_json({"ok": True, "result": result})
        except Exception as error:
            self._send_error_json(error)


def main() -> None:
    parser = argparse.ArgumentParser(description="ArcRho localhost development control center")
    parser.add_argument("--host", default="127.0.0.1")
    # 28765 is the app server, 28766 is Arco Admin Control, and 28767 is the
    # Gateway (``DEFAULT_GATEWAY_PORT``). Sharing a port with a deployed
    # ArcRho service means whichever process binds first silently wins and the
    # other fails to start, so this dev-only page takes the next free port.
    parser.add_argument("--port", type=int, default=DEV_CONTROL_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("The control center may only bind to localhost.")

    try:
        server = ControlServer((args.host, args.port), ControlHandler)
    except OSError as error:
        raise SystemExit(
            f"Port {args.port} is already in use, most likely by another ArcRho Dev Control Center.\n"
            f"Open http://127.0.0.1:{args.port}/ and press Stop Control Center, or stop that process,\n"
            f"then start this one again. Detail: {error}"
        ) from error
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"ArcRho Dev Control Center: {url}")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
