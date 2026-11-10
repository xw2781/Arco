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

from arcrho_engine_calculation_contract import (
    ENGINE_CALCULATION_CAPABILITY_FIELD,
    ENGINE_CALCULATION_OPERATION_FIELD,
    ENGINE_CALCULATION_PATH,
    HTTP_ENGINE_CALCULATION_FUNCTIONS,
    HTTP_ENGINE_CALCULATION_OPERATIONS,
    MAX_ENGINE_CALCULATION_WAIT_SECONDS,
    OPERATION_DATASET_PRECHECK,
    OPERATION_DATASET_RUN,
    OUTPUT_VARIANT_TEMPORARY_VIEW,
    EngineCalculationContractError,
    build_engine_calculation_request,
    validate_engine_calculation_request,
)
from arcrho_hosted_save_http_contract import (
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    canonical_request_bytes,
    default_gateway_config,
    sign_request,
)
from arcrho_workspace_read_contract import WORKSPACE_ROOT_HEADER
from arcrho_api.gateway_test_guard import allow_test_gateway
from arcrho_gateway import engine_calculations, main as gateway_main
from app_server import config as app_config
from app_server.services import (
    client_save_latency_log_service,
    engine_calculation_service,
    user_identity_service,
    workspace_read_client,
)


TRI_PAIRS = [
    ["Function", "ArcRhoTri"],
    ["Path", "PA\\All States\\COL"],
    ["DatasetName", "Paid"],
    ["InstanceName", "Paid"],
    ["Cumulative", "True"],
    ["Transposed", "False"],
    ["Calendar", "False"],
    ["ProjectName", "Demo Project"],
    ["OriginLength", "12"],
    ["DevelopmentLength", "12"],
]
HEADER_PAIRS = [
    ["Function", "ArcRhoHeaders"],
    ["periodType", "0"],
    ["Transposed", "False"],
    ["Calendar", "False"],
    ["PeriodLength", "12"],
    ["ProjectName", "Demo Project"],
    ["StoredPeriodLength", "-1"],
]


def _request(pairs=None, **overrides) -> dict:
    fields = {
        "request_id": "calc-1",
        "pairs": TRI_PAIRS if pairs is None else pairs,
        "timeout_sec": 15.0,
        "user_name": "alice",
        "user_display_name": "Alice Example",
    }
    fields.update(overrides)
    return build_engine_calculation_request(**fields)


class EngineCalculationContractTests(unittest.TestCase):
    def test_executor_names_a_real_service_function(self) -> None:
        """The gateway resolves the executor only through the contract constants."""

        module = importlib.import_module(
            f"app_server.services.{engine_calculations.EXECUTOR_MODULE}"
        )
        function = getattr(module, engine_calculations.EXECUTOR_FUNCTION)
        parameters = list(inspect.signature(function).parameters)
        self.assertEqual(parameters[:3], ["pairs", "timeout_sec", "output_variant"])

    def test_validation_normalizes_a_request(self) -> None:
        request = _request()
        self.assertEqual(request["EngineFunction"], "ArcRhoTri")
        self.assertEqual(request["Pairs"], TRI_PAIRS)
        self.assertEqual(request["TimeoutSeconds"], 15.0)
        self.assertEqual(request["OutputVariant"], "canonical")
        self.assertEqual(request["UserName"], "alice")
        header = _request(HEADER_PAIRS)
        self.assertEqual(header["EngineFunction"], "ArcRhoHeaders")

    def test_pair_order_and_spelling_are_preserved(self) -> None:
        """The Engine reads keys verbatim and header file names follow pair order."""

        reordered = list(reversed(HEADER_PAIRS))
        self.assertEqual(_request(reordered)["Pairs"], reordered)
        with self.assertRaises(EngineCalculationContractError):
            _request([["Function", "ArcRhoHeaders"], ["PeriodType", "0"], ["ProjectName", "Demo"]])

    def test_validation_rejects_unknown_function_and_keys(self) -> None:
        with self.assertRaises(EngineCalculationContractError):
            _request([["Function", "ArcRhoDatasetTypes"], ["ProjectName", "Demo"]])
        with self.assertRaises(EngineCalculationContractError):
            _request(TRI_PAIRS + [["periodType", "0"]])
        with self.assertRaises(EngineCalculationContractError):
            _request(TRI_PAIRS + [["OriginLength", "24"]])
        with self.assertRaises(EngineCalculationContractError):
            _request([])

    def test_validation_rejects_server_owned_keys(self) -> None:
        for key in ("DataPath", "datapath", "StatusPath", "RequestId", "UserName"):
            with self.assertRaises(EngineCalculationContractError, msg=key):
                _request(TRI_PAIRS + [[key, "x"]])

    def test_validation_rejects_machine_local_locations(self) -> None:
        with self.assertRaises(EngineCalculationContractError):
            _request([pair if pair[0] != "Path" else ["Path", "E:\\Arco Server\\x"] for pair in TRI_PAIRS])
        with self.assertRaises(EngineCalculationContractError):
            _request([pair if pair[0] != "ProjectName" else ["ProjectName", "CON"] for pair in TRI_PAIRS])
        with self.assertRaises(EngineCalculationContractError):
            _request([pair for pair in TRI_PAIRS if pair[0] != "Path"])

    def test_validation_rejects_request_line_breakers(self) -> None:
        with self.assertRaises(EngineCalculationContractError):
            _request(TRI_PAIRS + [["VectorName", "a#b"]])
        with self.assertRaises(EngineCalculationContractError):
            _request(TRI_PAIRS + [["VectorName", "a\nb"]])
        with self.assertRaises(EngineCalculationContractError):
            _request(TRI_PAIRS + [["VectorName", 12]])

    def test_output_variant_is_per_function(self) -> None:
        self.assertEqual(
            _request(output_variant=OUTPUT_VARIANT_TEMPORARY_VIEW)["OutputVariant"],
            OUTPUT_VARIANT_TEMPORARY_VIEW,
        )
        with self.assertRaises(EngineCalculationContractError):
            _request(HEADER_PAIRS, output_variant=OUTPUT_VARIANT_TEMPORARY_VIEW)
        with self.assertRaises(EngineCalculationContractError):
            _request(output_variant="scratch")

    def test_operations_and_options_are_per_function(self) -> None:
        request = _request(
            operation=OPERATION_DATASET_RUN,
            options={"force_refresh": True, "write_sidecar": False, "temporary_session_id": None},
        )
        self.assertEqual(request["Operation"], OPERATION_DATASET_RUN)
        self.assertEqual(
            request["Options"],
            {"force_refresh": True, "write_sidecar": False, "temporary_session_id": None},
        )
        self.assertEqual(_request()["Operation"], "exchange")
        self.assertEqual(_request()["Options"], {})
        precheck = _request(
            operation=OPERATION_DATASET_PRECHECK,
            options={"allow_runtime_cache_provenance": True, "temporary_session_id": " abc "},
        )
        self.assertEqual(precheck["Options"]["temporary_session_id"], "abc")
        with self.assertRaises(EngineCalculationContractError):
            _request(HEADER_PAIRS, operation=OPERATION_DATASET_RUN)
        with self.assertRaises(EngineCalculationContractError):
            _request(operation="dataset_delete")
        with self.assertRaises(EngineCalculationContractError):
            _request(operation=OPERATION_DATASET_RUN, options={"force_refresh": "yes"})
        with self.assertRaises(EngineCalculationContractError):
            _request(operation=OPERATION_DATASET_RUN, options={"allow_runtime_cache_provenance": True})
        with self.assertRaises(EngineCalculationContractError):
            _request(options={"force_refresh": True})
        with self.assertRaises(EngineCalculationContractError):
            _request(operation=OPERATION_DATASET_RUN, output_variant=OUTPUT_VARIANT_TEMPORARY_VIEW)

    def test_advertised_operations_are_the_registry(self) -> None:
        self.assertEqual(
            HTTP_ENGINE_CALCULATION_OPERATIONS,
            ("dataset_csv", "dataset_precheck", "dataset_run", "exchange"),
        )

    def test_timeout_is_clamped(self) -> None:
        self.assertEqual(_request(timeout_sec=0)["TimeoutSeconds"], 0.1)
        self.assertEqual(
            _request(timeout_sec=10_000)["TimeoutSeconds"], MAX_ENGINE_CALCULATION_WAIT_SECONDS
        )
        with self.assertRaises(EngineCalculationContractError):
            _request(timeout_sec="soon")

    def test_foreign_payload_is_refused(self) -> None:
        with self.assertRaises(EngineCalculationContractError):
            validate_engine_calculation_request({"Function": "ArcRhoWorkspaceRead"})

    def test_advertised_functions_are_the_registry(self) -> None:
        self.assertEqual(
            HTTP_ENGINE_CALCULATION_FUNCTIONS,
            ("ArcRhoHeaders", "ArcRhoProjectSettings", "ArcRhoTri", "ArcRhoVec"),
        )


class _FakeEngine:
    """Answer request files the way the Engine does: claim, then write the CSV."""

    def __init__(self, request_dir: Path, output_path: Path, *, respond: bool = True) -> None:
        self.request_dir = request_dir
        self.output_path = output_path
        self.respond = respond
        self.claimed: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "_FakeEngine":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            for path in sorted(self.request_dir.glob("request-*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
                self.claimed.append(payload)
                if self.respond:
                    target = Path(payload["DataPath"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("1,2\n3,4\n", encoding="utf-8")
            time.sleep(0.02)


class HostedExecutionTests(unittest.TestCase):
    """``execute_hosted_engine_calculation`` against a workspace on local disk."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        self.request_dir = self.root / "requests"
        self.request_dir.mkdir()
        self.output_path = self.root / "projects" / "Demo Project" / "data" / "COL" / "datasets" / "Paid@12@12@cum@dev.csv"
        self.patches = [
            patch.object(app_config, "REQUEST_DIR", str(self.request_dir)),
            patch.object(
                engine_calculation_service,
                "set_data_path_like_vba",
                side_effect=lambda pairs: str(self.output_path),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_publishes_as_the_acting_user_and_waits_for_the_csv(self) -> None:
        with _FakeEngine(self.request_dir, self.output_path) as engine:
            with user_identity_service.acting_identity("alice", "Alice Example"):
                response = engine_calculation_service.execute_hosted_engine_calculation(
                    TRI_PAIRS, 10.0
                )
        self.assertEqual(response["ok"], True)
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["data_path"], str(self.output_path))
        self.assertTrue(response["request_file"].startswith(str(self.request_dir)))
        self.assertGreaterEqual(response["wait_ms"], 0)
        # The CSV's exact text travels back, so the client never reads its drive.
        self.assertEqual(response["csv_text"], self.output_path.read_bytes().decode("utf-8"))
        self.assertEqual(len(engine.claimed), 1)
        claimed = engine.claimed[0]
        self.assertEqual(claimed["UserName"], "alice")
        self.assertEqual(claimed["Function"], "ArcRhoTri")
        self.assertEqual(claimed["DataPath"], str(self.output_path))
        self.assertEqual(claimed["OriginLength"], 12)
        self.assertIs(claimed["Cumulative"], True)
        self.assertTrue(self.output_path.is_file())

    def test_reports_a_timeout_when_no_engine_answers(self) -> None:
        with _FakeEngine(self.request_dir, self.output_path, respond=False):
            response = engine_calculation_service.execute_hosted_engine_calculation(
                TRI_PAIRS, 0.2
            )
        self.assertEqual(response["ok"], False)
        self.assertEqual(response["status"], "timeout")
        self.assertNotIn("csv_text", response)
        self.assertFalse(self.output_path.exists())

    def test_temporary_view_variant_targets_the_temporary_cache(self) -> None:
        from app_server.services import arcrho_runtime_service

        temporary_dir = self.output_path.parent / app_config.TEMPORARY_VIEW_DATASET_CACHE_DIR
        with patch.object(
            app_config,
            "get_project_temporary_view_dataset_cache_dir",
            return_value=str(temporary_dir),
        ):
            expected = arcrho_runtime_service.temporary_dataset_path(
                str(self.output_path), [tuple(pair) for pair in TRI_PAIRS]
            )
            with _FakeEngine(self.request_dir, Path(expected)) as engine:
                response = engine_calculation_service.execute_hosted_engine_calculation(
                    TRI_PAIRS, 10.0, OUTPUT_VARIANT_TEMPORARY_VIEW
                )
        self.assertEqual(response["data_path"], expected)
        self.assertEqual(engine.claimed[0]["DataPath"], expected)
        self.assertTrue(Path(expected).is_file())

    def test_dataset_operations_run_the_canonical_route(self) -> None:
        from app_server.services import arcrho_runtime_service

        seen: dict = {}

        def fake_run(pairs, data_path, timeout_sec, **kwargs):
            seen.update({"pairs": pairs, "data_path": data_path, "timeout_sec": timeout_sec, **kwargs})
            return {"ok": True, "ds_id": "arcrhotri_x", "data_path": data_path, "need_request": True}

        def fake_precheck(data_path, pairs, **kwargs):
            seen.update({"precheck_path": data_path, **kwargs})
            return {"ok": True, "need_request": False, "data_path": data_path}

        with patch.object(arcrho_runtime_service, "run_arcrho_tri", fake_run):
            response = engine_calculation_service.execute_hosted_engine_calculation(
                TRI_PAIRS,
                15.0,
                "canonical",
                OPERATION_DATASET_RUN,
                {"force_refresh": True, "write_sidecar": False, "temporary_session_id": None},
            )
        self.assertEqual(response["ds_id"], "arcrhotri_x")
        self.assertEqual(seen["data_path"], str(self.output_path))
        self.assertEqual(seen["pairs"], [tuple(pair) for pair in TRI_PAIRS])
        self.assertEqual(seen["timeout_sec"], 15.0)
        self.assertIs(seen["force_refresh"], True)
        self.assertIs(seen["write_sidecar"], False)
        self.assertIs(seen["allow_derived"], True)
        self.assertIsNone(seen["temporary_session_id"])
        with patch.object(arcrho_runtime_service, "arcrho_precheck", fake_precheck):
            response = engine_calculation_service.execute_hosted_engine_calculation(
                TRI_PAIRS, 15.0, "canonical", OPERATION_DATASET_PRECHECK, {"local_only": True}
            )
        self.assertEqual(response["need_request"], False)
        self.assertEqual(seen["precheck_path"], str(self.output_path))
        self.assertIs(seen["local_only"], True)
        self.assertIs(seen["allow_runtime_cache_provenance"], False)

    def test_unknown_project_is_a_refusal(self) -> None:
        with patch.object(
            engine_calculation_service,
            "set_data_path_like_vba",
            side_effect=ValueError("Project folder not found under projects: Demo Project"),
        ):
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.execute_hosted_engine_calculation(TRI_PAIRS, 1.0)
        self.assertEqual(caught.exception.status_code, 404)


class EngineCalculationExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(self.root / "config" / "arcrho_gateway.json", config)
        self.logged: list[str] = []
        self.executor = engine_calculations.EngineCalculationExecutor(
            self.root,
            load_gateway_config=gateway_main._load_gateway_config,
            log=lambda _root, message: self.logged.append(message),
            ensure_runtime=lambda: None,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_execute_runs_the_canonical_executor_as_the_requesting_user(self) -> None:
        seen: dict = {}

        def fake_execute(pairs, timeout_sec, output_variant="canonical", operation="exchange", options=None):
            seen.update(
                {
                    "pairs": pairs,
                    "timeout_sec": timeout_sec,
                    "output_variant": output_variant,
                    "operation": operation,
                    "options": options,
                    "identity": user_identity_service.get_current_identity(),
                }
            )
            return {"ok": True, "status": "completed", "data_path": "x", "request_file": "y", "wait_ms": 1.0}

        with patch.object(
            engine_calculation_service, engine_calculations.EXECUTOR_FUNCTION, fake_execute
        ):
            response = self.executor.execute(
                "alice", _request(output_variant=OUTPUT_VARIANT_TEMPORARY_VIEW)
            )
            self.assertEqual(seen["output_variant"], OUTPUT_VARIANT_TEMPORARY_VIEW)
            run_response = self.executor.execute(
                "alice",
                _request(operation=OPERATION_DATASET_RUN, options={"force_refresh": True}),
            )
        self.assertEqual(response["status"], "completed")
        self.assertEqual(seen["pairs"], TRI_PAIRS)
        self.assertEqual(seen["timeout_sec"], 15.0)
        self.assertEqual(seen["operation"], OPERATION_DATASET_RUN)
        self.assertEqual(seen["options"], {"force_refresh": True})
        self.assertEqual(run_response["ok"], True)
        self.assertEqual(seen["identity"]["login_name"], "alice")
        self.assertEqual(seen["identity"]["display_name"], "Alice Example")
        self.assertTrue(any("function=ArcRhoTri" in line for line in self.logged))

    def test_service_refusal_keeps_its_status_and_redacts_paths(self) -> None:
        def refuse(pairs, timeout_sec, output_variant="canonical", operation="exchange", options=None):
            raise HTTPException(404, "Project folder not found under E:\\Arco Server\\projects")

        with patch.object(engine_calculation_service, engine_calculations.EXECUTOR_FUNCTION, refuse):
            with self.assertRaises(engine_calculations.WorkspaceReadRefusal) as caught:
                self.executor.execute("alice", _request())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn("E:\\", caught.exception.detail)

    def test_user_mismatch_and_bad_payload_are_gateway_errors(self) -> None:
        with self.assertRaises(engine_calculations.WorkspaceReadHttpError) as mismatch:
            self.executor.execute("bob", _request())
        self.assertEqual(mismatch.exception.status_code, 403)
        with self.assertRaises(engine_calculations.WorkspaceReadHttpError) as invalid:
            self.executor.execute("alice", {"Function": "ArcRhoEngineCalculation"})
        self.assertEqual(invalid.exception.status_code, 400)

    def test_capabilities_advertise_every_registered_function(self) -> None:
        payload = gateway_main.Gateway(self.root).capabilities()
        self.assertEqual(
            payload[ENGINE_CALCULATION_CAPABILITY_FIELD], list(HTTP_ENGINE_CALCULATION_FUNCTIONS)
        )
        self.assertEqual(
            payload[ENGINE_CALCULATION_OPERATION_FIELD], list(HTTP_ENGINE_CALCULATION_OPERATIONS)
        )


class EngineCalculationHttpRoundTripTests(unittest.TestCase):
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
        gateway_main._write_json_atomic(self.server_root / "config" / "arcrho_gateway.json", config)
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
        self.server_csv = str(self.server_root / "projects" / "Demo Project" / "data" / "COL" / "datasets" / "Paid@12@12@cum@dev.csv")
        self.client_csv = str(self.client_root / "projects" / "Demo Project" / "data" / "COL" / "datasets" / "Paid@12@12@cum@dev.csv")
        self.records: list[dict] = []
        self.visibility_waits: list[str] = []
        self.local_publishes: list[str] = []

        def visible(path, timeout_sec, settle_ms=50.0):
            self.visibility_waits.append(path)
            return True

        def local_publish(request_info):
            self.local_publishes.append(request_info)
            return "C:\\mapped\\requests\\request-local.json"

        self.patches = [
            patch.object(app_config, "load_gateway_config", return_value=self.client_config),
            patch.object(app_config, "get_root_path", return_value=str(self.client_root)),
            # The temporary paths live on local disk: the transport depends on
            # the process, never on where the workspace root sits.
            patch.object(workspace_read_client, "_is_server_process", return_value=False),
            patch.object(engine_calculation_service, "wait_for_file", side_effect=visible),
            patch.object(engine_calculation_service, "send_request_like_vba", side_effect=local_publish),
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

    def _hosted(self, response=None, error=None):
        seen: dict = {}

        def fake_execute(pairs, timeout_sec, output_variant="canonical", operation="exchange", options=None):
            seen.update(
                {
                    "pairs": pairs,
                    "timeout_sec": timeout_sec,
                    "output_variant": output_variant,
                    "operation": operation,
                    "options": options,
                }
            )
            if error is not None:
                raise error
            return dict(
                response
                or {
                    "ok": True,
                    "status": "completed",
                    "data_path": self.server_csv,
                    "request_file": str(self.server_root / "requests" / "request-1.json"),
                    "wait_ms": 12.5,
                    "csv_text": "\n1.5,2\n3,\n",
                }
            )

        return seen, patch.object(
            engine_calculation_service, engine_calculations.EXECUTOR_FUNCTION, fake_execute
        )

    def test_calculation_runs_on_the_gateway_and_paths_are_rebased(self) -> None:
        seen, hosted = self._hosted()
        with hosted:
            outcome = engine_calculation_service.run_engine_calculation(
                TRI_PAIRS, self.client_csv, 15.0
            )
        self.assertEqual(outcome["ok"], True)
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(outcome["transport"], "http_gateway")
        self.assertEqual(
            outcome["request_file"], str(self.client_root / "requests" / "request-1.json")
        )
        self.assertEqual(seen["pairs"], TRI_PAIRS)
        self.assertEqual(seen["timeout_sec"], 15.0)
        # The result travels in the reply: the client never publishes, never
        # waits for the CSV on its drive, and the file need not exist there.
        self.assertEqual(outcome["csv_text"], "\n1.5,2\n3,\n")
        self.assertEqual(self.local_publishes, [])
        self.assertEqual(self.visibility_waits, [])
        self.assertFalse(Path(self.client_csv).exists())
        record = self.records[-1]
        self.assertEqual(record["read_kind"], "engine_calculation")
        self.assertEqual(record["engine_function"], "ArcRhoTri")
        self.assertEqual(record["transport"], "http_gateway")
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(record["server_wait_ms"], 12.5)

    def test_temporary_view_variant_travels(self) -> None:
        seen, hosted = self._hosted()
        with hosted:
            engine_calculation_service.run_engine_calculation(
                TRI_PAIRS,
                self.client_csv,
                15.0,
                output_variant=OUTPUT_VARIANT_TEMPORARY_VIEW,
            )
        self.assertEqual(seen["output_variant"], OUTPUT_VARIANT_TEMPORARY_VIEW)

    def test_server_timeout_is_reported_not_retried(self) -> None:
        _seen, hosted = self._hosted(
            response={
                "ok": False,
                "status": "timeout",
                "data_path": self.server_csv,
                "request_file": str(self.server_root / "requests" / "request-1.json"),
                "wait_ms": 15000.0,
            }
        )
        with hosted:
            outcome = engine_calculation_service.run_engine_calculation(
                TRI_PAIRS, self.client_csv, 15.0
            )
        self.assertEqual(outcome["ok"], False)
        self.assertEqual(outcome["status"], "timeout")
        self.assertEqual(outcome["transport"], "http_gateway")
        self.assertEqual(self.local_publishes, [])
        self.assertEqual(self.visibility_waits, [])

    def test_a_success_without_its_result_is_an_error_not_a_drive_read(self) -> None:
        # A Gateway older than the body in the reply: the client does not fall
        # back to waiting for the file on its drive.
        _seen, hosted = self._hosted(
            response={
                "ok": True,
                "status": "completed",
                "data_path": self.server_csv,
                "request_file": "r",
                "wait_ms": 1.0,
            }
        )
        with hosted:
            outcome = engine_calculation_service.run_engine_calculation(
                TRI_PAIRS, self.client_csv, 15.0
            )
        self.assertEqual(outcome["ok"], False)
        self.assertEqual(outcome["status"], "gateway_error")
        self.assertIn("needs updating", outcome["message"])
        self.assertNotIn("csv_text", outcome)
        self.assertEqual(self.visibility_waits, [])
        self.assertEqual(self.local_publishes, [])

    def test_service_refusal_passes_through_with_its_status(self) -> None:
        _seen, hosted = self._hosted(error=HTTPException(404, "Project folder not found under projects: Demo Project"))
        with hosted:
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.run_engine_calculation(TRI_PAIRS, self.client_csv, 15.0)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.local_publishes, [])
        self.assertEqual(self.records[-1]["http_status"], 404)

    def test_mismatched_output_location_is_an_error(self) -> None:
        _seen, hosted = self._hosted(
            response={
                "ok": True,
                "status": "completed",
                "data_path": str(self.server_root / "projects" / "Other" / "x.csv"),
                "request_file": "r",
                "wait_ms": 1.0,
            }
        )
        with hosted:
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.run_engine_calculation(TRI_PAIRS, self.client_csv, 15.0)
        self.assertEqual(caught.exception.status_code, 500)

    def _refused(self, pairs=None) -> HTTPException:
        with self.assertRaises(HTTPException) as caught:
            engine_calculation_service.run_engine_calculation(
                pairs or TRI_PAIRS, self.client_csv, 15.0
            )
        # A Client PC never writes a request file of its own.
        self.assertEqual(self.local_publishes, [])
        return caught.exception

    def test_a_function_not_advertised_needs_a_server_update(self) -> None:
        with patch.object(
            engine_calculation_service, "gateway_supports_engine_function", return_value=False
        ):
            refused = self._refused(HEADER_PAIRS)
        self.assertEqual(refused.status_code, 503)
        self.assertIn("needs updating", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "kind_not_advertised")

    def test_a_disabled_gateway_asks_the_user_to_sign_in(self) -> None:
        with patch.object(app_config, "load_gateway_config", return_value={"enabled": False}):
            refused = self._refused()
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(self.records[-1]["reason"], "gateway_disabled")

    def test_an_unhostable_request_is_refused(self) -> None:
        refused = self._refused(TRI_PAIRS + [["StoredPeriodLength", "-1"]])
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.records[-1]["reason"], "request_not_hostable")

    def test_a_refused_signature_asks_the_user_to_sign_in_again(self) -> None:
        wrong_secret = dict(self.client_config, secret="not-alice")
        with patch.object(app_config, "load_gateway_config", return_value=wrong_secret):
            refused = self._refused()
        self.assertEqual(refused.status_code, 401)
        self.assertIn("Sign in to the server again", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "gateway_rejected:401")

    def test_an_unreachable_gateway_is_reported(self) -> None:
        unreachable = dict(self.client_config, url="http://127.0.0.1:9")
        self.addCleanup(allow_test_gateway(unreachable["url"]))
        with patch.object(app_config, "load_gateway_config", return_value=unreachable):
            refused = self._refused()
        self.assertEqual(refused.status_code, 503)
        self.assertIn("can't be reached", refused.detail)
        self.assertEqual(self.records[-1]["reason"], "gateway_unreachable")

    def test_server_process_never_routes_to_itself(self) -> None:
        with patch.object(workspace_read_client, "_is_server_process", return_value=True):
            outcome = engine_calculation_service.run_engine_calculation(
                TRI_PAIRS, self.client_csv, 15.0
            )
        self.assertEqual(outcome["transport"], "smb")
        self.assertEqual(self.records[-1]["reason"], "server_process")

    def test_dataset_run_is_hosted_and_registers_the_handle(self) -> None:
        seen, hosted = self._hosted(
            response={
                "ok": True,
                "need_request": True,
                "ds_id": "arcrhotri_abc",
                "data_path": self.server_csv,
                "request_file": str(self.server_root / "requests" / "request-1.json"),
                "calculated_updates": None,
                "sidecar_written": True,
            }
        )
        options = {"force_refresh": True, "local_only": False, "allow_derived": True,
                   "write_sidecar": True, "temporary_session_id": None}
        with hosted, patch.dict(app_config.DATASETS, {}, clear=True):
            payload = engine_calculation_service.run_hosted_dataset_operation(
                OPERATION_DATASET_RUN,
                TRI_PAIRS,
                options,
                timeout_sec=15.0,
                local=lambda: self.fail("the run must not execute locally"),
            )
            self.assertEqual(app_config.DATASETS, {"arcrhotri_abc": self.client_csv})
        self.assertEqual(payload["data_path"], self.client_csv)
        self.assertEqual(payload["request_file"], str(self.client_root / "requests" / "request-1.json"))
        self.assertEqual(seen["operation"], OPERATION_DATASET_RUN)
        self.assertEqual(seen["options"], options)
        # The route owns the request; the client neither publishes nor probes.
        self.assertEqual(self.local_publishes, [])
        self.assertEqual(self.visibility_waits, [])
        record = self.records[-1]
        self.assertEqual(record["operation"], OPERATION_DATASET_RUN)
        self.assertEqual(record["transport"], "http_gateway")
        self.assertEqual(record["outcome"], "success")

    def test_dataset_precheck_is_hosted_without_registering(self) -> None:
        _seen, hosted = self._hosted(
            response={"ok": True, "need_request": False, "cache_exists": True,
                      "data_path": self.server_csv, "ds_id": "arcrhotri_abc"}
        )
        with hosted, patch.dict(app_config.DATASETS, {}, clear=True):
            payload = engine_calculation_service.run_hosted_dataset_operation(
                OPERATION_DATASET_PRECHECK,
                TRI_PAIRS,
                {"local_only": False},
                timeout_sec=15.0,
                local=lambda: self.fail("the precheck must not execute locally"),
            )
            self.assertEqual(app_config.DATASETS, {})
        self.assertEqual(payload["data_path"], self.client_csv)

    def test_dataset_run_refusal_passes_through(self) -> None:
        _seen, hosted = self._hosted(error=HTTPException(423, "Cannot clear cached ArcRho tri file."))
        with hosted:
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.run_hosted_dataset_operation(
                    OPERATION_DATASET_RUN, TRI_PAIRS, {}, timeout_sec=15.0,
                    local=lambda: self.fail("a hosted refusal must not fall back"),
                )
        self.assertEqual(caught.exception.status_code, 423)

    def test_a_dataset_run_the_gateway_does_not_offer_is_never_run_here(self) -> None:
        with patch.object(engine_calculation_service, "gateway_supports_operation", return_value=False):
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.run_hosted_dataset_operation(
                    OPERATION_DATASET_RUN, TRI_PAIRS, {}, timeout_sec=15.0,
                    local=lambda: self.fail("a Client PC must not run the route itself"),
                )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.records[-1]["reason"], "kind_not_advertised")

    def test_dataset_run_timeout_is_a_504_not_a_local_rerun(self) -> None:
        with patch.object(
            engine_calculation_service,
            "post_signed_json",
            side_effect=engine_calculation_service.GatewayTransportFailure("gateway_timeout", timed_out=True),
        ):
            with self.assertRaises(HTTPException) as caught:
                engine_calculation_service.run_hosted_dataset_operation(
                    OPERATION_DATASET_RUN, TRI_PAIRS, {}, timeout_sec=15.0,
                    local=lambda: self.fail("an accepted request must not re-run locally"),
                )
        self.assertEqual(caught.exception.status_code, 504)
        self.assertEqual(self.records[-1]["reason"], "gateway_timeout")

    def _signed(self, body: bytes, *, secret: str = "alice-secret") -> Request:
        timestamp = str(int(time.time()))
        return Request(
            f"{self.url}{ENGINE_CALCULATION_PATH}",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                AUTH_USER_HEADER: "alice",
                AUTH_TIMESTAMP_HEADER: timestamp,
                AUTH_SIGNATURE_HEADER: sign_request(
                    secret,
                    user="alice",
                    timestamp=timestamp,
                    method="POST",
                    path=ENGINE_CALCULATION_PATH,
                    body=body,
                ),
            },
        )

    def test_raw_http_contract(self) -> None:
        _seen, hosted = self._hosted()
        body = canonical_request_bytes(_request())
        with hosted:
            with urlopen(self._signed(body), timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(
                    response.headers.get(WORKSPACE_ROOT_HEADER), str(self.server_root.resolve())
                )
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["data_path"], self.server_csv)
            with self.assertRaises(HTTPError) as denied:
                urlopen(self._signed(body, secret="wrong"), timeout=5)
            self.assertEqual(denied.exception.code, 401)
            self.assertIsNone(denied.exception.headers.get(WORKSPACE_ROOT_HEADER))
        with urlopen(f"{self.url}/api/capabilities", timeout=5) as response:
            capabilities = json.loads(response.read().decode("utf-8"))
        self.assertEqual(
            capabilities[ENGINE_CALCULATION_CAPABILITY_FIELD], list(HTTP_ENGINE_CALCULATION_FUNCTIONS)
        )


if __name__ == "__main__":
    unittest.main()
