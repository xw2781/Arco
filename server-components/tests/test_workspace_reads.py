from __future__ import annotations

import importlib
import inspect
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# Every test temp directory lives under one gitignored folder at the
# repository root, so a suite that dies before teardown cannot scatter
# tmp folders beside the code.
TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
ENGINE_SOURCE = REPOSITORY_ROOT / "server-components" / "src"
API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
for path in (ENGINE_SOURCE, API_SOURCE, FRONTEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi import HTTPException

from arcrho_hosted_save_http_contract import (
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    canonical_request_bytes,
    default_gateway_config,
    sign_request,
)
from arcrho_workspace_read_contract import (
    HTTP_WORKSPACE_READ_KINDS,
    WORKSPACE_READ_KINDS,
    WORKSPACE_READ_PATH,
    WORKSPACE_ROOT_HEADER,
    WorkspaceReadContractError,
    build_workspace_read_request,
    validate_workspace_read_request,
)
from arcrho_api.gateway_test_guard import allow_test_gateway
from arcrho_gateway import main as gateway_main
from arcrho_gateway import workspace_reads
from app_server import config as app_config
from app_server.services import (
    client_save_latency_log_service,
    dataset_service,
    user_identity_service,
    workspace_read_client,
)


def _request(kind: str = "dataset_index", **overrides) -> dict:
    kwargs = {"project_name": "Demo Project", "reserving_class": "PA\\All States\\COL"}
    kwargs.update(overrides)
    return build_workspace_read_request(
        request_id="read-1",
        read_kind=kind,
        kwargs=kwargs,
        user_name="alice",
        user_display_name="Alice Example",
    )


class WorkspaceReadContractTests(unittest.TestCase):
    def test_every_registered_kind_names_a_real_service_read(self) -> None:
        """The registry is the only table; drift from the services must fail here."""

        for kind, spec in WORKSPACE_READ_KINDS.items():
            module = importlib.import_module(f"app_server.services.{spec.module}")
            function = getattr(module, spec.function)
            parameters = inspect.signature(function).parameters
            for name in spec.required + spec.optional:
                self.assertIn(name, parameters, f"{kind}: {spec.function} lacks {name}")
            for name, parameter in parameters.items():
                if parameter.default is inspect.Parameter.empty and parameter.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    self.assertIn(name, spec.required, f"{kind}: {name} must be required")

    def test_advertised_kinds_are_the_registry(self) -> None:
        self.assertEqual(HTTP_WORKSPACE_READ_KINDS, tuple(sorted(WORKSPACE_READ_KINDS)))

    def test_validation_normalizes_a_request(self) -> None:
        request = _request(refresh=True)
        self.assertEqual(request["ReadKind"], "dataset_index")
        self.assertEqual(request["Kwargs"]["refresh"], True)
        self.assertEqual(request["UserName"], "alice")
        self.assertEqual(request["UserDisplayName"], "Alice Example")

    def test_validation_rejects_unknown_kind_and_arguments(self) -> None:
        with self.assertRaises(WorkspaceReadContractError):
            _request("not_a_read")
        with self.assertRaises(WorkspaceReadContractError):
            _request(csv_file="anything.csv")
        with self.assertRaises(WorkspaceReadContractError):
            _request(reserving_class="")

    def test_validation_rejects_machine_local_locations(self) -> None:
        with self.assertRaises(WorkspaceReadContractError):
            _request(reserving_class="E:\\Arco Server\\projects\\Demo")
        with self.assertRaises(WorkspaceReadContractError):
            _request(project_name="CON")

    def test_optional_null_arguments_are_allowed(self) -> None:
        request = _request(
            "dataset_cache_load",
            dataset_name="Paid",
            csv_file="",
            origin_length=None,
        )
        self.assertIsNone(request["Kwargs"]["origin_length"])

    def test_a_kind_that_names_no_project_validates(self) -> None:
        """The Bridge-worker liveness look reads the runtime folder, not a project."""

        request = build_workspace_read_request(
            request_id="read-1",
            read_kind="bridge_worker_liveness",
            kwargs={"queue": "import", "request_id": ""},
            user_name="alice",
        )
        self.assertEqual(request["ReadKind"], "bridge_worker_liveness")
        self.assertEqual(request["Kwargs"]["queue"], "import")

    def test_foreign_payload_is_refused(self) -> None:
        with self.assertRaises(WorkspaceReadContractError):
            validate_workspace_read_request({"Function": "ArcRhoHostedSave"})


class _FakeReadRuntime:
    """Swap one registered read for a fake without touching any workspace."""

    def __init__(self, kind: str, implementation) -> None:
        self.spec = WORKSPACE_READ_KINDS[kind]
        self.module = importlib.import_module(f"app_server.services.{self.spec.module}")
        self.patch = patch.object(self.module, self.spec.function, implementation)

    def __enter__(self):
        self.patch.start()
        return self

    def __exit__(self, *exc) -> None:
        self.patch.stop()


class WorkspaceReadExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.root / "config" / "arcrho_gateway.json", config
        )
        self.logged: list[str] = []
        self.executor = workspace_reads.WorkspaceReadExecutor(
            self.root,
            load_gateway_config=gateway_main._load_gateway_config,
            log=lambda _root, message: self.logged.append(message),
        )
        # The canonical runtime is this checkout; skip repointing app_server at
        # the temporary root so the test process keeps its own configuration.
        self.executor._runtime_ready = True

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_execute_runs_the_registered_service_as_the_requesting_user(self) -> None:
        seen: dict = {}

        def fake_index(project_name: str, reserving_class: str, refresh: bool = False):
            seen.update(
                {
                    "project_name": project_name,
                    "reserving_class": reserving_class,
                    "refresh": refresh,
                    "identity": user_identity_service.get_current_identity(),
                }
            )
            return {"ok": True, "files": [], "folder_paths": {"data": str(self.root / "x")}}

        with _FakeReadRuntime("dataset_index", fake_index):
            response = self.executor.execute("alice", _request(refresh=True))
        self.assertEqual(response["ok"], True)
        self.assertEqual(seen["project_name"], "Demo Project")
        self.assertEqual(seen["reserving_class"], "PA\\All States\\COL")
        self.assertIs(seen["refresh"], True)
        self.assertEqual(seen["identity"]["login_name"], "alice")
        self.assertEqual(seen["identity"]["display_name"], "Alice Example")

    def test_service_refusal_keeps_its_status_and_redacts_paths(self) -> None:
        def refuse(**_kwargs):
            raise HTTPException(404, "DFM method not found under E:\\Arco Server\\x")

        with _FakeReadRuntime("dfm_method_load", refuse):
            with self.assertRaises(workspace_reads.WorkspaceReadRefusal) as caught:
                self.executor.execute(
                    "alice", _request("dfm_method_load", method_name="Paid DFM")
                )
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn("E:\\", caught.exception.detail)

    def test_user_mismatch_and_bad_payload_are_gateway_errors(self) -> None:
        with self.assertRaises(workspace_reads.WorkspaceReadHttpError) as mismatch:
            self.executor.execute("bob", _request())
        self.assertEqual(mismatch.exception.status_code, 403)
        with self.assertRaises(workspace_reads.WorkspaceReadHttpError) as invalid:
            self.executor.execute("alice", {"Function": "ArcRhoWorkspaceRead"})
        self.assertEqual(invalid.exception.status_code, 400)

    def test_capabilities_advertise_every_registered_kind(self) -> None:
        payload = gateway_main.Gateway(self.root).capabilities()
        self.assertEqual(payload["workspace_read_kinds"], list(HTTP_WORKSPACE_READ_KINDS))


class WorkspaceReadHttpRoundTripTests(unittest.TestCase):
    """The client transport against a live gateway, both ends in this process."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        self.server_root = self.root / "server"
        self.client_root = self.root / "client-mapped"
        (self.server_root / "config").mkdir(parents=True)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.server_root / "config" / "arcrho_gateway.json", config
        )
        self.gateway = gateway_main.Gateway(self.server_root)
        self.gateway.reads._runtime_ready = True
        self.server = gateway_main.GatewayServer(("127.0.0.1", 0), self.gateway)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(allow_test_gateway(self.url))
        self.client_config = {
            "enabled": True,
            "url": self.url,
            "user": "alice",
            "secret": "alice-secret",
            "allow_insecure_http": True,
        }
        self.records: list[dict] = []
        self.patches = [
            patch.object(app_config, "load_gateway_config", return_value=self.client_config),
            patch.object(app_config, "get_root_path", return_value=str(self.client_root)),
            patch.object(workspace_read_client, "_is_server_process", return_value=False),
            patch.object(
                client_save_latency_log_service,
                "append_client_read_latency",
                side_effect=lambda record: self.records.append(dict(record)) or True,
            ),
        ]
        for item in self.patches:
            item.start()
        workspace_read_client.reset_capability_cache()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        workspace_read_client.reset_capability_cache()
        self.temp_dir.cleanup()

    def _signed(self, body: bytes, *, user: str = "alice", secret: str = "alice-secret") -> Request:
        timestamp = str(int(time.time()))
        return Request(
            f"{self.url}{WORKSPACE_READ_PATH}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                AUTH_USER_HEADER: user,
                AUTH_TIMESTAMP_HEADER: timestamp,
                AUTH_SIGNATURE_HEADER: sign_request(
                    secret,
                    user=user,
                    timestamp=timestamp,
                    method="POST",
                    path=WORKSPACE_READ_PATH,
                    body=body,
                ),
            },
        )

    def test_read_runs_on_the_gateway_and_paths_are_rebased(self) -> None:
        server_csv = str(self.server_root / "projects" / "Demo" / "data" / "COL" / "datasets" / "Paid.csv")

        def fake_load(project_name, reserving_class, dataset_name, **kwargs):
            return {
                "ok": True,
                "id": "arcrhotri_abc",
                "path": server_csv,
                "values": [[1.0, None], [2.0, 3.0]],
                "folder": {"data": str(self.server_root / "projects" / "Demo")},
            }

        adopted: dict = {}
        with _FakeReadRuntime("dataset_cache_load", fake_load):
            response = workspace_read_client.run_workspace_read(
                "dataset_cache_load",
                {
                    "project_name": "Demo",
                    "reserving_class": "COL",
                    "dataset_name": "Paid",
                    "csv_file": "",
                    "origin_length": None,
                },
                local=lambda: self.fail("the read must not run locally"),
                finalize=lambda payload: adopted.update(payload) or payload,
            )
        expected_csv = str(self.client_root / "projects" / "Demo" / "data" / "COL" / "datasets" / "Paid.csv")
        self.assertEqual(response["path"], expected_csv)
        self.assertEqual(response["folder"]["data"], str(self.client_root / "projects" / "Demo"))
        self.assertEqual(response["values"], [[1.0, None], [2.0, 3.0]])
        self.assertEqual(adopted["path"], expected_csv)
        self.assertEqual(self.records[-1]["transport"], "http_gateway")
        self.assertEqual(self.records[-1]["outcome"], "success")
        self.assertEqual(self.records[-1]["read_kind"], "dataset_cache_load")

    def test_service_refusal_passes_through_with_its_status(self) -> None:
        def refuse(**_kwargs):
            raise HTTPException(409, "DFM requires both its method JSON and output sidecar.")

        with _FakeReadRuntime("dfm_method_load", refuse):
            with self.assertRaises(HTTPException) as caught:
                workspace_read_client.run_workspace_read(
                    "dfm_method_load",
                    {"project_name": "Demo", "reserving_class": "COL", "method_name": "Paid DFM"},
                    local=lambda: self.fail("a hosted refusal must not fall back"),
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("output sidecar", caught.exception.detail)
        self.assertEqual(self.records[-1]["transport"], "http_gateway")
        self.assertEqual(self.records[-1]["http_status"], 409)

    def _refused(self) -> HTTPException:
        with self.assertRaises(HTTPException) as caught:
            workspace_read_client.run_workspace_read(
                "table_summary",
                {"project_name": "Demo"},
                local=lambda: self.fail("a Client PC must not read the share"),
            )
        return caught.exception

    def test_a_kind_not_advertised_needs_a_server_update(self) -> None:
        with patch.object(workspace_read_client, "gateway_supports_read_kind", return_value=False):
            refused = self._refused()
        self.assertEqual(refused.status_code, 503)
        self.assertIn("needs updating", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "kind_not_advertised")

    def test_an_unreachable_gateway_is_reported(self) -> None:
        unreachable = dict(self.client_config, url="http://127.0.0.1:9")
        self.addCleanup(allow_test_gateway(unreachable["url"]))
        with patch.object(app_config, "load_gateway_config", return_value=unreachable):
            refused = self._refused()
        self.assertEqual(refused.status_code, 503)
        self.assertIn("can't be reached", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "gateway_unreachable")

    def test_a_refused_signature_asks_the_user_to_sign_in_again(self) -> None:
        """A wrong secret is a gateway refusal without the workspace-root header."""

        wrong_secret = dict(self.client_config, secret="not-alice")
        with patch.object(app_config, "load_gateway_config", return_value=wrong_secret):
            refused = self._refused()
        self.assertEqual(refused.status_code, 401)
        self.assertIn("Sign in to the server again", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "gateway_rejected:401")

    def test_server_process_never_routes_to_itself(self) -> None:
        with patch.object(workspace_read_client, "_is_server_process", return_value=True):
            response = workspace_read_client.run_workspace_read(
                "table_summary",
                {"project_name": "Demo"},
                local=lambda: {"ok": True, "from": "local"},
            )
        self.assertEqual(response["from"], "local")
        self.assertEqual(self.records[-1]["reason"], "server_process")

    def test_raw_http_contract(self) -> None:
        with _FakeReadRuntime("table_summary", lambda project_name: {"ok": True, "rows": 3}):
            body = canonical_request_bytes(
                build_workspace_read_request(
                    request_id="raw-1",
                    read_kind="table_summary",
                    kwargs={"project_name": "Demo"},
                    user_name="alice",
                )
            )
            with urlopen(self._signed(body), timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.headers.get(WORKSPACE_ROOT_HEADER), str(self.server_root.resolve()))
            self.assertEqual(payload, {"ok": True, "rows": 3})
            with self.assertRaises(HTTPError) as denied:
                urlopen(self._signed(body, secret="wrong"), timeout=5)
            self.assertEqual(denied.exception.code, 401)
            self.assertIsNone(denied.exception.headers.get(WORKSPACE_ROOT_HEADER))


class DatasetHandleRegistrationTests(unittest.TestCase):
    def test_register_dataset_handle_binds_id_to_path(self) -> None:
        with patch.dict(app_config.DATASETS, {}, clear=True):
            dataset_service.register_dataset_handle("arcrhotri_x", "C:\\mapped\\Paid.csv")
            dataset_service.register_dataset_handle("", "ignored")
            self.assertEqual(app_config.DATASETS, {"arcrhotri_x": "C:\\mapped\\Paid.csv"})


if __name__ == "__main__":
    unittest.main()
