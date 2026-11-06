"""Machine-local HTTP gateway for Engine-hosted saves, Server-hosted workspace reads, and Engine calculations."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping
from urllib.parse import urlparse


_MODULE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_ROOT.parent
_PRODUCT_ROOT = _SOURCE_ROOT.parent
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _MODULE_ROOT)).resolve()
for _path in (_PRODUCT_ROOT, _SOURCE_ROOT, _BUNDLE_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

try:
    from src.utils import get_config_value, get_project_root, resolve_app_path
except ModuleNotFoundError:
    from utils import get_config_value, get_project_root, resolve_app_path

os.environ.setdefault("ARCRHO_RUNTIME_SERVER_ROOT", str(get_project_root()))

from arcrho_api.config import SERVER_ID_KEY, read_server_id  # noqa: E402
from arcrho_dependent_propagation_contract import (  # noqa: E402
    DependentPropagationContractError,
    EngineUnavailableError,
    find_reserving_class_propagation_hold,
    require_live_engine,
)
from arcrho_engine_save_contract import (  # noqa: E402
    SAVE_JOB_MODE_PLAN,
    SAVE_JOB_PLAN_TIMEOUT_SECONDS,
    SAVE_JOB_PROCESSING_TIMEOUT_SECONDS,
    SAVE_JOB_QUEUED_TIMEOUT_SECONDS,
    SaveJobContractError,
    discard_save_job_artifacts,
    read_save_job_result,
    read_save_job_status,
    save_job_request_path,
    save_job_status_is_terminal,
    save_job_status_response,
    validate_request_id,
    validate_save_job_request,
)
from arcrho_hosted_save_http_contract import (  # noqa: E402
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    CAPABILITIES_PATH,
    ENROLLMENT_CAPABILITY,
    ENROLLMENT_IDLE_SECONDS,
    ENROLLMENT_PATH,
    HEALTH_PATH,
    HOSTED_SAVE_PATH,
    HOSTED_SAVE_PROGRESS_PATH,
    HTTP_CONTRACT_VERSION,
    HTTP_SAVE_KINDS,
    MAX_PROGRESS_REQUEST_BYTES,
    MAX_REQUEST_BYTES,
    HostedSaveHttpContractError,
    canonical_request_bytes,
    default_gateway_config,
    normalize_gateway_config,
    normalize_user,
    receipt_path,
    request_sha256,
    server_config_path,
    verify_request_signature,
)
from arcrho_workspace_read_contract import (  # noqa: E402
    MAX_WORKSPACE_READ_REQUEST_BYTES,
    WORKSPACE_READ_PATH,
    WORKSPACE_ROOT_HEADER,
)
from arcrho_engine_calculation_contract import (  # noqa: E402
    ENGINE_CALCULATION_PATH,
    MAX_ENGINE_CALCULATION_REQUEST_BYTES,
)
from arcrho_workspace_mutation_contract import (  # noqa: E402
    MAX_WORKSPACE_MUTATION_REQUEST_BYTES,
    WORKSPACE_MUTATION_PATH,
)
from arcrho_log_retention_contract import apply_log_retention  # noqa: E402
from arcrho_gateway.engine_calculations import EngineCalculationExecutor  # noqa: E402
from arcrho_gateway.enrollment import WindowsEnrollment  # noqa: E402
from arcrho_gateway.receipts import (  # noqa: E402
    ReceiptReadError,
    now_iso as _now_iso,
    prune_terminal_receipts as _prune_terminal_receipts,
    read_json,
    receipt_lock as _receipt_lock,
    write_json_atomic as _write_json_atomic,
)
from arcrho_gateway.workspace_mutations import WorkspaceMutationExecutor  # noqa: E402
from arcrho_gateway.user_guide import GUIDE_PATH, guide_asset  # noqa: E402
from arcrho_gateway.workspace_reads import (  # noqa: E402
    WorkspaceReadExecutor,
    WorkspaceReadHttpError,
    WorkspaceReadRefusal,
)
HEARTBEAT_SECONDS = 5.0
# Sign-up carries no body; a larger one is refused before it is read.
MAX_ENROLLMENT_REQUEST_BYTES = 4 * 1024
STATUS_POLL_SECONDS = 0.05
GATEWAY_KILL_ALL_KEY = "apps.gateway.kill_all"


class GatewayHttpError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = str(detail)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return read_json(path)
    except ReceiptReadError as exc:
        raise GatewayHttpError(500, str(exc)) from exc


def _load_gateway_config(root: Path) -> dict[str, Any]:
    path = server_config_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = default_gateway_config()
        _write_json_atomic(path, payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise HostedSaveHttpContractError(
            f"Gateway configuration could not be read: {path}"
        ) from exc
    return normalize_gateway_config(payload)


def _log_path(root: Path) -> Path:
    return root / "runtime" / "logs" / "gateway.log"


def _log(root: Path, message: str) -> None:
    path = _log_path(root)
    line = f"{_now_iso()} {message}\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
    except OSError:
        pass


def _validate_logical_location(request: Mapping[str, Any]) -> None:
    project = str(request.get("ProjectName") or "").strip()
    reserving_class = str(request.get("Path") or "").strip()
    if (
        not project
        or project in {".", ".."}
        or any(character in project for character in ("/", "\\", ":"))
    ):
        raise GatewayHttpError(400, "ProjectName must be one logical project name.")
    path = PureWindowsPath(reserving_class)
    if (
        not reserving_class
        or path.is_absolute()
        or path.drive
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise GatewayHttpError(400, "Path must be a logical reserving-class path.")


def _publish_request(root: Path, request: Mapping[str, Any]) -> None:
    path = save_job_request_path(root, request["RequestId"])
    if path.exists() or read_save_job_status(root, request["RequestId"]) is not None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        temporary.write_bytes(canonical_request_bytes(request))
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _new_receipt(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "receipt_version": 1,
        "request_id": request["RequestId"],
        "request_sha256": request_sha256(request),
        "request": dict(request),
        "state": "accepted",
        "accepted_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def _terminal_receipt(
    receipt: Mapping[str, Any],
    *,
    status_code: int,
    response: Mapping[str, Any] | None = None,
    detail: str = "",
) -> dict[str, Any]:
    updated = dict(receipt)
    updated.update(
        {
            "state": "success" if int(status_code) == 200 else "error",
            "status_code": int(status_code),
            "updated_at": _now_iso(),
        }
    )
    if response is not None:
        updated["response"] = dict(response)
        updated.pop("detail", None)
    else:
        updated["detail"] = str(detail or "The hosted save failed.")
        updated.pop("response", None)
    return updated


def _receipt_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    status_code = int(receipt.get("status_code") or 500)
    if status_code != 200:
        raise GatewayHttpError(status_code, str(receipt.get("detail") or "Save failed."))
    response = receipt.get("response")
    if not isinstance(response, Mapping):
        raise GatewayHttpError(500, "The Gateway receipt has no response payload.")
    return dict(response)


def _wait_for_engine(root: Path, request: Mapping[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
    request_id = request["RequestId"]
    timeout = (
        SAVE_JOB_PLAN_TIMEOUT_SECONDS
        if request["Mode"] == SAVE_JOB_MODE_PLAN
        else SAVE_JOB_PROCESSING_TIMEOUT_SECONDS
    )
    started = time.monotonic()
    claim_deadline = started + SAVE_JOB_QUEUED_TIMEOUT_SECONDS
    deadline = started + timeout
    claimed = False
    while True:
        status = read_save_job_status(root, request_id)
        current = str((status or {}).get("status") or "queued")
        if current != "queued":
            claimed = True
        if save_job_status_is_terminal(status):
            if current == "success":
                response = save_job_status_response(status) or read_save_job_result(
                    root, request_id
                )
                if not isinstance(response, Mapping):
                    return 500, None, "Arco Engine returned no save response."
                return 200, dict(response), ""
            return (
                int(status.get("status_code") or 500),
                None,
                str(status.get("message") or "The hosted save failed."),
            )
        now = time.monotonic()
        if not claimed and now >= claim_deadline:
            request_path = save_job_request_path(root, request_id)
            if request_path.is_file():
                discard_save_job_artifacts(root, request_id)
                return 503, None, "Arco Engine did not pick up the save."
            claimed = True
        if now >= deadline:
            return (
                504,
                None,
                "The save is taking longer than expected on Arco Engine. "
                "Reload the dataset before retrying.",
            )
        time.sleep(STATUS_POLL_SECONDS)


class Gateway:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        # Written once, while the Gateway is stopped for a deploy; clients refuse
        # a Gateway whose id differs from the folder they are pointed at.
        self.server_id = read_server_id(self.root)
        self.reads = WorkspaceReadExecutor(
            self.root, load_gateway_config=_load_gateway_config, log=_log
        )
        self.calculations = EngineCalculationExecutor(
            self.root,
            load_gateway_config=_load_gateway_config,
            log=_log,
            ensure_runtime=self.reads.ensure_runtime,
        )
        self.mutations = WorkspaceMutationExecutor(
            self.root,
            load_gateway_config=_load_gateway_config,
            log=_log,
            ensure_runtime=self.reads.ensure_runtime,
        )
        self.enrollment = WindowsEnrollment(self.root, log=_log)

    def capabilities(self) -> dict[str, Any]:
        config = _load_gateway_config(self.root)
        return {
            "ok": True,
            "hosted_save_http": bool(config["users"]),
            "contract_version": HTTP_CONTRACT_VERSION,
            "allowed_save_kinds": list(HTTP_SAVE_KINDS),
            "insecure_http_pilot": True,
            ENROLLMENT_CAPABILITY: True,
            SERVER_ID_KEY: self.server_id,
            **self.reads.capability_fields(),
            **self.calculations.capability_fields(),
            **self.mutations.capability_fields(),
        }

    def authenticate(
        self,
        headers: Mapping[str, str],
        body: bytes,
        *,
        path: str = HOSTED_SAVE_PATH,
    ) -> str:
        config = _load_gateway_config(self.root)
        user = normalize_user(headers.get(AUTH_USER_HEADER))
        secret = config["users"].get(user)
        if not secret or not verify_request_signature(
            secret,
            headers.get(AUTH_SIGNATURE_HEADER, ""),
            user=user,
            timestamp=headers.get(AUTH_TIMESTAMP_HEADER, ""),
            method="POST",
            path=path,
            body=body,
        ):
            raise GatewayHttpError(401, "Gateway authentication failed.")
        return user

    def save_progress(self, raw_payload: Any) -> dict[str, Any]:
        """Answer one live-progress poll for a still-running hosted save.

        Reads the save-job status file on this host's local disk, so the
        client sees fresh walk progress instead of the seconds-stale view the
        SMB client cache would give it. Returns only the narration fields —
        the full save response stays on the submit exchange.
        """

        if not isinstance(raw_payload, Mapping):
            raise GatewayHttpError(400, "Progress request must be a JSON object.")
        try:
            request_id = validate_request_id(str(raw_payload.get("RequestId") or ""))
        except Exception as exc:
            raise GatewayHttpError(400, "Progress request needs a valid RequestId.") from exc
        status = read_save_job_status(self.root, request_id)
        if status is None:
            return {"request_id": request_id, "status": "unknown"}
        answer: dict[str, Any] = {
            "request_id": request_id,
            "status": str(status.get("status") or "unknown"),
        }
        progress = status.get("progress")
        if isinstance(progress, Mapping):
            answer["progress"] = dict(progress)
        message = str(status.get("message") or "").strip()
        if message:
            answer["message"] = message
        return answer

    def submit(self, authenticated_user: str, raw_payload: Any) -> dict[str, Any]:
        try:
            request = validate_save_job_request(raw_payload)
        except SaveJobContractError as exc:
            raise GatewayHttpError(400, str(exc)) from exc
        # ``validate_save_job_request`` already rejects any kind outside the
        # canonical SAVE_JOB_KINDS registry, so the gateway needs no second
        # allowlist of its own.
        if normalize_user(request["UserName"]) != normalize_user(authenticated_user):
            raise GatewayHttpError(403, "Authenticated user does not match the save user.")
        _validate_logical_location(request)

        request_id = request["RequestId"]
        path = receipt_path(self.root, request_id)
        with _receipt_lock(request_id):
            receipt = _read_json(path)
            digest = request_sha256(request)
            if receipt is not None:
                if receipt.get("request_sha256") != digest:
                    raise GatewayHttpError(
                        409, "This request id was already used for different save content."
                    )
                if receipt.get("state") in {"success", "error"}:
                    return _receipt_result(receipt)
            else:
                try:
                    require_live_engine(self.root)
                    hold = find_reserving_class_propagation_hold(
                        self.root, request["ProjectName"], request["Path"]
                    )
                except EngineUnavailableError as exc:
                    raise GatewayHttpError(503, str(exc)) from exc
                except DependentPropagationContractError as exc:
                    raise GatewayHttpError(400, str(exc)) from exc
                if hold is not None:
                    raise GatewayHttpError(
                        423,
                        "Dependent updates are currently running for this reserving "
                        "class. Please wait for them to finish, then save again.",
                    )
                receipt = _new_receipt(request)
                _write_json_atomic(path, receipt)

            try:
                _publish_request(self.root, request)
            except Exception as exc:
                terminal = _terminal_receipt(
                    receipt,
                    status_code=500,
                    detail="The Gateway could not publish the Engine request.",
                )
                _write_json_atomic(path, terminal)
                raise GatewayHttpError(500, terminal["detail"]) from exc

            status_code, response, detail = _wait_for_engine(self.root, request)
            terminal = _terminal_receipt(
                receipt,
                status_code=status_code,
                response=response,
                detail=detail,
            )
            _write_json_atomic(path, terminal)
            if status_code != 504:
                discard_save_job_artifacts(self.root, request_id)
            _log(
                self.root,
                f"request={request_id} user={authenticated_user} "
                f"kind={request['SaveKind']} mode={request['Mode']} status={status_code}",
            )
            return _receipt_result(terminal)


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    # One process must own the port. HTTPServer enables SO_REUSEADDR, which on
    # Windows lets a second process bind an address a live Gateway already
    # holds, leaving two Gateways each serving an arbitrary share of hosted
    # saves. A second copy has to fail to bind and exit instead.
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], gateway: Gateway) -> None:
        self.gateway = gateway
        super().__init__(address, GatewayHandler)


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_json(
        self,
        status_code: int,
        payload: Mapping[str, Any],
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if self._serve_user_guide(path):
            return
        if path == HEALTH_PATH:
            self._send_json(200, {"ok": True})
            return
        if path == CAPABILITIES_PATH:
            try:
                self._send_json(200, self.server.gateway.capabilities())
            except Exception as exc:
                self._send_json(503, {"detail": str(exc)})
            return
        self._send_json(404, {"detail": "Not found."})

    def do_HEAD(self) -> None:  # noqa: N802
        if not self._serve_user_guide(urlparse(self.path).path, head_only=True):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _serve_user_guide(self, path: str, *, head_only: bool = False) -> bool:
        if path == GUIDE_PATH.rstrip("/"):
            self.send_response(308)
            self.send_header("Location", GUIDE_PATH)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        if not path.startswith(GUIDE_PATH):
            return False
        asset = guide_asset(self.server.gateway.root, path)
        try:
            body = asset[0].read_bytes() if asset else None
        except OSError:
            body = None
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", asset[1] if body is not None else "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)) if body is not None else "0")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head_only and body is not None:
            self.wfile.write(body)
        return True

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == WORKSPACE_READ_PATH:
            self._handle_hosted_execution(
                self.server.gateway.reads, MAX_WORKSPACE_READ_REQUEST_BYTES, "Workspace-read"
            )
            return
        if path == ENGINE_CALCULATION_PATH:
            self._handle_hosted_execution(
                self.server.gateway.calculations,
                MAX_ENGINE_CALCULATION_REQUEST_BYTES,
                "Engine-calculation",
            )
            return
        if path == WORKSPACE_MUTATION_PATH:
            self._handle_hosted_execution(
                self.server.gateway.mutations,
                MAX_WORKSPACE_MUTATION_REQUEST_BYTES,
                "Workspace-mutation",
            )
            return
        if path == HOSTED_SAVE_PROGRESS_PATH:
            self._handle_save_progress()
            return
        if path == ENROLLMENT_PATH:
            self._handle_enrollment()
            return
        if path != HOSTED_SAVE_PATH:
            self._send_json(404, {"detail": "Not found."})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"detail": "Content-Length is invalid."})
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"detail": "Hosted-save request is too large."})
            return
        body = self.rfile.read(content_length)
        try:
            user = self.server.gateway.authenticate(self.headers, body)
            payload = json.loads(body.decode("utf-8"))
            response = self.server.gateway.submit(user, payload)
            self._send_json(200, response)
        except GatewayHttpError as exc:
            self._send_json(exc.status_code, {"detail": exc.detail})
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"detail": "Hosted-save request is not valid JSON."})
        except Exception:
            _log(self.server.gateway.root, traceback.format_exc())
            self._send_json(500, {"detail": "The Gateway failed unexpectedly."})

    def _handle_save_progress(self) -> None:
        """Serve one live-progress poll: authenticate, read status, answer."""

        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"detail": "Content-Length is invalid."})
            return
        if content_length <= 0 or content_length > MAX_PROGRESS_REQUEST_BYTES:
            self._send_json(413, {"detail": "Progress request is too large."})
            return
        body = self.rfile.read(content_length)
        try:
            self.server.gateway.authenticate(
                self.headers, body, path=HOSTED_SAVE_PROGRESS_PATH
            )
            payload = json.loads(body.decode("utf-8"))
            self._send_json(200, self.server.gateway.save_progress(payload))
        except GatewayHttpError as exc:
            self._send_json(exc.status_code, {"detail": exc.detail})
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"detail": "Progress request is not valid JSON."})
        except Exception:
            _log(self.server.gateway.root, traceback.format_exc())
            self._send_json(500, {"detail": "The Gateway failed unexpectedly."})

    def _handle_enrollment(self) -> None:
        """Serve one request of a Windows sign-up handshake.

        The handshake's state lives on this handler, which serves exactly one
        connection; a continuing handshake keeps the connection open for at
        most the idle limit.
        """

        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            content_length = -1
        if not 0 <= content_length <= MAX_ENROLLMENT_REQUEST_BYTES:
            self._send_json(413, {"detail": "Sign-up request is too large."}, {"Connection": "close"})
            return
        self.rfile.read(content_length)
        state = self.__dict__.setdefault("_enrollment_state", {})
        try:
            status_code, payload, headers = self.server.gateway.enrollment.respond(
                state, self.client_address[0], self.headers.get("Authorization")
            )
        except Exception:
            _log(self.server.gateway.root, traceback.format_exc())
            self._send_json(500, {"detail": "The Gateway failed unexpectedly."}, {"Connection": "close"})
            return
        if state:
            self.connection.settimeout(ENROLLMENT_IDLE_SECONDS)
        self._send_json(status_code, payload, headers)

    def _handle_hosted_execution(
        self, executor: Any, max_request_bytes: int, label: str
    ) -> None:
        """Serve one hosted read or calculation: authenticate, execute, answer."""

        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"detail": "Content-Length is invalid."})
            return
        if content_length <= 0 or content_length > max_request_bytes:
            self._send_json(413, {"detail": f"{label} request is too large."})
            return
        body = self.rfile.read(content_length)
        # The header tells the client which workspace root the payload's paths
        # belong to; it is present exactly when the hosted operation ran,
        # including a refusal the service raised itself.
        ran_headers = {WORKSPACE_ROOT_HEADER: str(executor.root)}
        try:
            user = executor.authenticate(self.headers, body)
            payload = json.loads(body.decode("utf-8"))
            response = executor.execute(user, payload)
            self._send_json(200, response, ran_headers)
        except WorkspaceReadRefusal as exc:
            self._send_json(exc.status_code, {"detail": exc.detail}, ran_headers)
        except WorkspaceReadHttpError as exc:
            self._send_json(exc.status_code, {"detail": exc.detail})
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"detail": f"{label} request is not valid JSON."})
        except Exception:
            _log(self.server.gateway.root, traceback.format_exc())
            self._send_json(500, {"detail": "The Gateway failed unexpectedly."})


def _heartbeat_path() -> Path:
    computer = os.environ.get("COMPUTERNAME") or socket.gethostname()
    user = os.environ.get("USERNAME") or "unknown"
    token = datetime.now().strftime("%y%m%d-%H%M%S-%f")[:-3]
    return resolve_app_path(
        "gateway", "instances", f"{computer}@{user}@{token}.json"
    )


def _start_heartbeat(server: GatewayServer, path: Path) -> threading.Thread:
    started = _now_iso()

    def monitor() -> None:
        while True:
            if get_config_value(GATEWAY_KILL_ALL_KEY, False):
                server.shutdown()
                return
            payload = {
                "Server": path.stem,
                "Created": started,
                "Last seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Port": server.server_port,
            }
            try:
                _write_json_atomic(path, payload)
            except OSError:
                pass
            time.sleep(HEARTBEAT_SECONDS)

    thread = threading.Thread(target=monitor, name="save-gateway-heartbeat", daemon=True)
    thread.start()
    return thread


def main() -> int:
    root = get_project_root().resolve()
    log_path = _log_path(root)
    apply_log_retention(log_path.parent, appended_files=(log_path,))
    try:
        config = _load_gateway_config(root)
        pruned = _prune_terminal_receipts(root, config["receipt_retention_hours"])
        gateway = Gateway(root)
        server = GatewayServer((config["host"], config["port"]), gateway)
    except Exception as exc:
        _log(root, f"startup failed: {exc}\n{traceback.format_exc()}")
        return 1
    heartbeat = _heartbeat_path()
    _start_heartbeat(server, heartbeat)
    gateway.reads.warm_up()
    _log(
        root,
        f"ready host={config['host']} port={server.server_port} "
        f"pid={os.getpid()} receipts_pruned={pruned}",
    )
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        # Another process reading the heartbeat can hold it open; a stop
        # must not crash on that.
        with contextlib.suppress(OSError):
            heartbeat.unlink(missing_ok=True)
        server.server_close()
        _log(root, f"stopped pid={os.getpid()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
