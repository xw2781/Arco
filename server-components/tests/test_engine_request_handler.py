from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, call, patch


ENGINE_SRC = Path(__file__).resolve().parents[1] / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
if str(ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC))

from arcrho_engine import main as engine_main  # noqa: E402


def _request(**overrides):
    payload = {
        "Function": "ArcRhoTri",
        "ProjectName": "Demo",
        "Path": r"Auto\PP",
        "DatasetName": "Paid Loss",
        "OriginLength": 12,
        "DevelopmentLength": 12,
        "Cumulative": True,
        "Transposed": False,
        "Calendar": False,
        "DataPath": r"E:\Arco Server\output.csv",
        "UserName": "tester",
        "RequestId": "request-123",
        "StatusPath": r"E:\Arco Server\status.json",
    }
    payload.update(overrides)
    return payload


class EngineRequestHandlerTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_created_and_moved_json_events_use_the_same_processor(self):
        handler = engine_main.RequestHandler()
        handler.process_file = Mock()

        handler.on_created(
            SimpleNamespace(is_directory=False, src_path=r"E:\requests\request-created.json")
        )
        handler.on_moved(
            SimpleNamespace(
                is_directory=False,
                src_path=r"E:\requests\request.tmp",
                dest_path=r"E:\requests\request-moved.json",
            )
        )
        handler.on_created(
            SimpleNamespace(is_directory=False, src_path=r"E:\requests\request.tmp")
        )

        self.assertEqual(
            handler.process_file.call_args_list,
            [
                call(
                    r"E:\requests\request-created.json",
                    dispatch_duplication=True,
                ),
                call(
                    r"E:\requests\request-moved.json",
                    dispatch_duplication=True,
                ),
            ],
        )

    def test_request_must_be_claimed_before_project_validation(self):
        handler = engine_main.RequestHandler()
        events = []

        with (
            patch.object(engine_main, "read_json", return_value=_request()),
            patch.object(
                engine_main,
                "safe_remove",
                side_effect=lambda _path: events.append("claim") or False,
            ),
            patch.object(
                engine_main,
                "project_exists",
                side_effect=lambda _name: events.append("validate") or True,
            ),
            patch.object(engine_main, "write_json") as write_status,
        ):
            handler.process_file(r"E:\requests\request.json")

        self.assertEqual(events, ["claim"])
        write_status.assert_not_called()

    def test_status_protocol_is_atomic_optional_and_tracks_success(self):
        handler = engine_main.RequestHandler()
        status_path = Path(self.temp_dir.name) / "job" / "status.json"
        request = _request(StatusPath=str(status_path))

        with (
            patch.object(engine_main, "read_json", return_value=request),
            patch.object(engine_main, "safe_remove", return_value=True),
            patch.object(engine_main, "project_exists", return_value=True),
            patch.object(engine_main, "get_project_table_path", return_value="source.csv"),
            patch.object(engine_main, "UDF_ADASTri") as udf,
            patch.object(engine_main, "debug_mode", 0),
        ):
            handler.process_file(r"E:\requests\request.json")

        payload = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["request_id"], "request-123")
        self.assertIn("updated_at", payload)
        self.assertNotIn("message", payload)
        self.assertEqual(tuple(status_path.parent.glob("*.tmp")), ())
        udf.assert_called_once_with(request)

        legacy_request = _request()
        legacy_request.pop("RequestId")
        legacy_request.pop("StatusPath")
        with patch.object(engine_main, "write_json") as write_status:
            self.assertTrue(
                engine_main._write_request_status(legacy_request, "processing")
            )
        write_status.assert_not_called()

    def test_processing_status_is_written_immediately_after_claim(self):
        handler = engine_main.RequestHandler()
        events = []
        request = _request()

        def record_status(_path, payload):
            events.append(payload["status"])
            return True

        with (
            patch.object(engine_main, "read_json", return_value=request),
            patch.object(
                engine_main,
                "safe_remove",
                side_effect=lambda _path: events.append("claim") or True,
            ),
            patch.object(engine_main, "write_json", side_effect=record_status),
            patch.object(
                engine_main,
                "project_exists",
                side_effect=lambda _name: events.append("validate") or True,
            ),
            patch.object(engine_main, "get_project_table_path", return_value="source.csv"),
            patch.object(engine_main, "UDF_ADASTri"),
            patch.object(engine_main, "debug_mode", 0),
        ):
            handler.process_file(r"E:\requests\request.json")

        self.assertEqual(events, ["claim", "processing", "validate", "success"])

    def test_project_duplication_dispatches_before_legacy_project_validation(self):
        handler = engine_main.RequestHandler()
        request = {
            "Function": "ArcRhoDuplicateProject",
            "ContractVersion": 1,
            "RequestId": "duplicate-123",
            "SourceProjectName": "Source",
            "TargetProjectName": "Target",
            "UserName": "tester",
        }
        server_root = Path(self.temp_dir.name) / "Arco Server"

        with (
            patch.object(engine_main, "read_json", return_value=request),
            patch.object(engine_main, "get_project_root", return_value=server_root),
            patch.object(
                engine_main,
                "process_durable_project_duplication_request",
            ) as execute,
            patch.object(engine_main, "safe_remove") as legacy_claim,
            patch.object(engine_main, "project_exists") as project_exists,
            patch.object(engine_main, "get_project_table_path") as table_path,
            patch.object(engine_main, "write_json") as legacy_status,
        ):
            handler.process_file(r"E:\requests\duplicate-123.json")

        execute.assert_called_once_with(
            server_root,
            r"E:\requests\duplicate-123.json",
            request,
        )
        legacy_claim.assert_not_called()
        project_exists.assert_not_called()
        table_path.assert_not_called()
        legacy_status.assert_not_called()

    def test_long_duplication_does_not_block_serialized_legacy_request(self):
        handler = engine_main.RequestHandler()
        duplication_started = Event()
        release_duplication = Event()
        duplicate_request = {
            "Function": "ArcRhoDuplicateProject",
            "ContractVersion": 1,
            "RequestId": "duplicate-long",
            "SourceProjectName": "Source",
            "TargetProjectName": "Target",
            "UserName": "tester",
        }
        legacy_request = _request(RequestId="legacy-during-copy", StatusPath="")

        def read_request(path):
            if str(path).endswith("duplicate.json"):
                return duplicate_request
            return legacy_request

        def hold_duplication(_root, _path, _request_payload):
            duplication_started.set()
            self.assertTrue(release_duplication.wait(timeout=2.0))

        try:
            with (
                patch.object(engine_main, "read_json", side_effect=read_request),
                patch.object(
                    engine_main,
                    "process_durable_project_duplication_request",
                    side_effect=hold_duplication,
                ),
                patch.object(engine_main, "safe_remove", return_value=True),
                patch.object(engine_main, "project_exists", return_value=True),
                patch.object(
                    engine_main,
                    "get_project_table_path",
                    return_value="source.csv",
                ),
                patch.object(engine_main, "UDF_ADASTri") as legacy_udf,
                patch.object(engine_main, "debug_mode", 0),
                patch.dict(engine_main.PROJECT_CONFIG, {}, clear=True),
            ):
                handler.process_file_debug(r"E:\requests\duplicate.json")
                self.assertTrue(duplication_started.wait(timeout=1.0))

                handler.process_file_debug(r"E:\requests\legacy.json")

                legacy_udf.assert_called_once_with(legacy_request)
        finally:
            release_duplication.set()
            self.assertTrue(handler.shutdown(wait=True, timeout=2.0))

    def test_repeated_duplicate_events_schedule_one_worker_job(self):
        handler = engine_main.RequestHandler()
        duplication_started = Event()
        release_duplication = Event()
        request = {
            "Function": "ArcRhoDuplicateProject",
            "ContractVersion": 1,
            "RequestId": "duplicate-repeat",
            "SourceProjectName": "Source",
            "TargetProjectName": "Target",
            "UserName": "tester",
        }

        def hold_duplication(_root, _path, _request_payload):
            duplication_started.set()
            self.assertTrue(release_duplication.wait(timeout=2.0))

        try:
            with (
                patch.object(engine_main, "read_json", return_value=request),
                patch.object(
                    engine_main,
                    "process_durable_project_duplication_request",
                    side_effect=hold_duplication,
                ) as execute,
                patch.object(engine_main, "debug_mode", 0),
            ):
                handler.process_file_debug(r"E:\requests\duplicate-repeat.json")
                self.assertTrue(duplication_started.wait(timeout=1.0))
                handler.process_file_debug(r"E:\requests\duplicate-repeat-moved.json")
                handler.process_file_debug(r"E:\requests\duplicate-repeat-rescan.json")

                self.assertEqual(execute.call_count, 1)
        finally:
            release_duplication.set()
            self.assertTrue(handler.shutdown(wait=True, timeout=2.0))

    def test_duplication_worker_queue_is_bounded_and_shutdown_rejects_new_work(self):
        handler = engine_main.RequestHandler(duplication_queue_capacity=1)
        first_started = Event()
        release_first = Event()
        second_completed = Event()

        def duplicate_request(request_id):
            return {
                "Function": "ArcRhoDuplicateProject",
                "ContractVersion": 1,
                "RequestId": request_id,
                "SourceProjectName": "Source",
                "TargetProjectName": request_id,
                "UserName": "tester",
            }

        first = duplicate_request("duplicate-first")
        second = duplicate_request("duplicate-second")
        third = duplicate_request("duplicate-third")

        def execute(_root, _path, request_payload):
            if request_payload["RequestId"] == "duplicate-first":
                first_started.set()
                self.assertTrue(release_first.wait(timeout=2.0))
            else:
                second_completed.set()

        try:
            with patch.object(
                engine_main,
                "process_durable_project_duplication_request",
                side_effect=execute,
            ) as worker:
                self.assertTrue(
                    handler._schedule_project_duplication("first.json", first)
                )
                self.assertTrue(first_started.wait(timeout=1.0))
                self.assertTrue(
                    handler._schedule_project_duplication("second.json", second)
                )
                self.assertFalse(
                    handler._schedule_project_duplication("third.json", third)
                )
                release_first.set()
                self.assertTrue(second_completed.wait(timeout=1.0))
                self.assertTrue(handler.shutdown(wait=True, timeout=2.0))
                self.assertFalse(
                    handler._schedule_project_duplication("third.json", third)
                )

            self.assertEqual(
                [item.args[2]["RequestId"] for item in worker.call_args_list],
                ["duplicate-first", "duplicate-second"],
            )
        finally:
            release_first.set()
            handler.shutdown(wait=True, timeout=2.0)

    def test_failed_duplication_worker_releases_dedupe_for_retry(self):
        handler = engine_main.RequestHandler()
        request = {
            "Function": "ArcRhoDuplicateProject",
            "ContractVersion": 1,
            "RequestId": "duplicate-retry",
            "SourceProjectName": "Source",
            "TargetProjectName": "Target",
            "UserName": "tester",
        }

        with patch.object(
            engine_main,
            "process_durable_project_duplication_request",
            side_effect=RuntimeError("worker failed"),
        ) as worker:
            self.assertTrue(handler._schedule_project_duplication("first.json", request))
            handler._duplication_queue.join()
            self.assertTrue(handler._schedule_project_duplication("retry.json", request))
            handler._duplication_queue.join()

        self.assertTrue(handler.shutdown(wait=True, timeout=2.0))
        self.assertEqual(worker.call_count, 2)

    def test_direct_legacy_requests_remain_serialized(self):
        handler = engine_main.RequestHandler()
        first_started = Event()
        second_started = Event()
        release_first = Event()
        udf_calls = 0

        def run_legacy(_request_payload):
            nonlocal udf_calls
            udf_calls += 1
            if udf_calls == 1:
                first_started.set()
                release_first.wait(timeout=2.0)
            else:
                second_started.set()

        def read_request(path):
            return _request(
                RequestId=Path(path).stem,
                StatusPath="",
            )

        with (
            patch.object(engine_main, "read_json", side_effect=read_request),
            patch.object(engine_main, "safe_remove", return_value=True),
            patch.object(engine_main, "project_exists", return_value=True),
            patch.object(
                engine_main,
                "get_project_table_path",
                return_value="source.csv",
            ),
            patch.object(engine_main, "UDF_ADASTri", side_effect=run_legacy),
            patch.object(engine_main, "debug_mode", 0),
            patch.dict(engine_main.PROJECT_CONFIG, {}, clear=True),
        ):
            first = Thread(target=handler.process_file, args=("first.json",))
            second = Thread(target=handler.process_file, args=("second.json",))
            first.start()
            self.assertTrue(first_started.wait(timeout=1.0))
            second.start()
            self.assertFalse(second_started.wait(timeout=0.1))
            release_first.set()
            first.join(timeout=1.0)
            second.join(timeout=1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertTrue(second_started.is_set())

    def test_existing_requests_are_processed_after_offline_queueing(self):
        request_dir = Path(self.temp_dir.name) / "requests"
        request_dir.mkdir()
        (request_dir / "b.json").write_text("{}", encoding="utf-8")
        (request_dir / "a.JSON").write_text("{}", encoding="utf-8")
        (request_dir / "ignore.tmp").write_text("{}", encoding="utf-8")
        handler = SimpleNamespace(process_file_debug=Mock())

        engine_main.process_existing_requests(request_dir, handler)

        self.assertEqual(
            [Path(call.args[0]).name for call in handler.process_file_debug.call_args_list],
            ["a.JSON", "b.json"],
        )

    def test_existing_request_recovery_retries_after_scan_failure(self):
        handler = engine_main.RequestHandler()

        class StopAfterTwoScans:
            def __init__(self):
                self.wait_calls = 0

            def is_set(self):
                return False

            def wait(self, _interval):
                self.wait_calls += 1
                return self.wait_calls >= 2

        stop_event = StopAfterTwoScans()
        with patch.object(
            engine_main,
            "process_existing_requests",
            side_effect=(PermissionError("offline"), None),
        ) as scan:
            engine_main.recover_existing_requests(
                Path(self.temp_dir.name) / "requests",
                handler,
                stop_event,
                interval_seconds=0.1,
            )

        self.assertEqual(scan.call_count, 2)

    def test_status_aware_request_stops_when_processing_marker_cannot_be_written(self):
        handler = engine_main.RequestHandler()

        with (
            patch.object(engine_main, "read_json", return_value=_request()),
            patch.object(engine_main, "safe_remove", return_value=True),
            patch.object(engine_main, "_write_request_status", return_value=False),
            patch.object(engine_main, "project_exists") as project_exists,
            patch.object(engine_main, "UDF_ADASTri") as udf,
        ):
            handler.process_file(r"E:\requests\request.json")

        project_exists.assert_not_called()
        udf.assert_not_called()

    def test_all_worker_error_branches_publish_terminal_status_and_legacy_csv(self):
        scenarios = (
            (
                "project_missing",
                {},
                {"project_exists": False},
                "(project not found: Demo)",
                [["(project not found: Demo)"]],
            ),
            (
                "configuration_refresh",
                {},
                {
                    "project_config_version": True,
                    "config_error": engine_main.DataProcessingConfigurationError("bad config"),
                },
                "(data processing configuration error: bad config)",
                [["(data processing configuration error: bad config)"]],
            ),
            (
                "invalid_function",
                {"Function": "NotAFunction"},
                {},
                "(invalid function name)",
                [["(invalid function name)"]],
            ),
            (
                "processing_rules",
                {},
                {"udf_error": engine_main.DataProcessingRulesError("bad rules")},
                "(data processing rules error: bad rules)",
                [["(data processing rules error: bad rules)"]],
            ),
            (
                "processing_configuration",
                {},
                {
                    "udf_error": engine_main.DataProcessingConfigurationError(
                        "bad processing config"
                    )
                },
                "(data processing configuration error: bad processing config)",
                [["(data processing configuration error: bad processing config)"]],
            ),
            (
                "project_settings",
                {},
                {"udf_error": engine_main.ProjectSettingsError("dates missing")},
                "project settings not defined: dates missing",
                [["project settings not defined"]],
            ),
            (
                "unexpected",
                {},
                {"udf_error": RuntimeError("boom")},
                "(error: BOOM)",
                [[0]],
            ),
        )

        for name, request_overrides, behavior, message, csv_rows in scenarios:
            with self.subTest(name=name):
                handler = engine_main.RequestHandler()
                request = _request(**request_overrides)
                statuses = []
                csv_calls = []

                def record_status(_path, payload):
                    statuses.append(payload)
                    return True

                project_config = (
                    {"Demo - Version": "old"}
                    if behavior.get("project_config_version")
                    else {}
                )
                config_error = behavior.get("config_error")
                config_probe = (
                    Mock(side_effect=config_error)
                    if config_error is not None
                    else Mock(return_value="old")
                )

                with (
                    patch.object(engine_main, "read_json", return_value=request),
                    patch.object(engine_main, "safe_remove", return_value=True),
                    patch.object(
                        engine_main,
                        "project_exists",
                        return_value=behavior.get("project_exists", True),
                    ),
                    patch.object(
                        engine_main,
                        "get_project_table_path",
                        return_value="source.csv",
                    ),
                    patch.object(engine_main, "write_json", side_effect=record_status),
                    patch.object(
                        engine_main,
                        "write_lists_to_csv",
                        side_effect=lambda path, rows: csv_calls.append((path, rows)),
                    ),
                    patch.object(
                        engine_main,
                        "UDF_ADASTri",
                        side_effect=behavior.get("udf_error"),
                    ),
                    patch.object(
                        engine_main,
                        "_get_vps_last_modified_time",
                        config_probe,
                    ),
                    patch.dict(engine_main.PROJECT_CONFIG, project_config, clear=True),
                    patch.object(engine_main, "debug_mode", 0),
                ):
                    handler.process_file(r"E:\requests\request.json")

                self.assertEqual(
                    [payload["status"] for payload in statuses],
                    ["processing", "error"],
                )
                self.assertEqual(statuses[-1]["request_id"], "request-123")
                self.assertEqual(statuses[-1]["message"], message)
                self.assertEqual(csv_calls, [(request["DataPath"], csv_rows)])

    def test_error_status_survives_error_csv_write_failure(self):
        handler = engine_main.RequestHandler()
        statuses = []

        with (
            patch.object(engine_main, "read_json", return_value=_request()),
            patch.object(engine_main, "safe_remove", return_value=True),
            patch.object(engine_main, "project_exists", return_value=False),
            patch.object(
                engine_main,
                "write_lists_to_csv",
                side_effect=PermissionError("output locked"),
            ),
            patch.object(
                engine_main,
                "write_json",
                side_effect=lambda _path, payload: statuses.append(payload) or True,
            ),
            patch.object(engine_main, "debug_mode", 0),
        ):
            handler.process_file(r"E:\requests\request.json")

        self.assertEqual([item["status"] for item in statuses], ["processing", "error"])
        self.assertIn("failed to write error CSV", statuses[-1]["message"])

    def test_monitor_removes_heartbeat_when_observer_thread_dies(self):
        observer = Mock()
        observer.is_alive.return_value = False
        handler = Mock()

        with (
            patch.object(engine_main, "Observer", return_value=observer),
            patch.object(engine_main, "RequestHandler", return_value=handler),
            patch.object(engine_main, "remove_old_instances"),
            patch.object(engine_main, "write_json", return_value=True),
            patch.object(engine_main, "_remove_instance_heartbeat") as remove_heartbeat,
        ):
            engine_main.start_monitoring(r"E:\Arco Server\requests")

        observer.schedule.assert_called_once()
        observer.start.assert_called_once_with()
        remove_heartbeat.assert_called_once_with()
        observer.join.assert_called_once_with()
        handler.shutdown.assert_called_once_with(wait=True, timeout=None)


class UnreadableRequestTests(unittest.TestCase):
    """A request file that exists but will not parse is logged once, not skipped in silence."""

    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.request_path = Path(self.temp_dir.name) / "request-2026-09-05_11-41-50.269.json"
        self.request_path.write_text('{"Function": "ArcRhoTri"}\n}\n', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_an_unreadable_request_is_logged_once_and_left_unclaimed(self):
        handler = engine_main.RequestHandler()
        with (
            patch.object(
                engine_main, "read_json", side_effect=PermissionError("Cannot open request")
            ),
            patch.object(engine_main, "safe_remove") as claim,
            patch.object(engine_main, "append_runtime_log") as log,
            patch.object(engine_main, "get_project_root", return_value=Path(self.temp_dir.name)),
        ):
            handler.process_file(str(self.request_path))
            handler.process_file(str(self.request_path))

        claim.assert_not_called()
        log.assert_called_once()
        root, filename, message = log.call_args.args
        self.assertEqual(filename, engine_main.ENGINE_REQUEST_LOG_FILENAME)
        self.assertIn(self.request_path.name, message)
        self.assertIn("Cannot open request", message)
        self.assertTrue(self.request_path.exists())

    def test_a_request_another_engine_claimed_is_not_news(self):
        handler = engine_main.RequestHandler()
        with (
            patch.object(engine_main, "read_json", side_effect=FileNotFoundError("gone")),
            patch.object(engine_main, "append_runtime_log") as log,
        ):
            handler.process_file(str(self.request_path.with_name("request-gone.json")))
        log.assert_not_called()


class InProcessCalculationTests(unittest.TestCase):
    """The canonical runtime on this Engine runs its exchanges without a request file."""

    def test_the_function_runs_under_the_legacy_serialisation(self):
        handler = engine_main.RequestHandler()
        request = _request()
        request.pop("RequestId")
        request.pop("StatusPath")
        seen = []

        def udf(arg):
            seen.append((dict(arg), handler._processing_lock.locked()))

        with (
            patch.object(engine_main, "project_exists", return_value=True),
            patch.object(engine_main, "get_project_table_path", return_value="source.csv"),
            patch.object(engine_main, "_refresh_project_config") as refresh_config,
            patch.object(engine_main, "UDF_ADASTri", side_effect=udf),
            patch.object(engine_main, "safe_remove") as claim,
        ):
            handler.calculate_in_process(request)

        self.assertEqual(seen, [(request, True)])
        refresh_config.assert_called_once_with("Demo")
        # Nothing was published, so there is nothing to claim.
        claim.assert_not_called()
        self.assertFalse(handler._processing_lock.locked())

    def test_the_vector_alias_reaches_the_triangle_function(self):
        handler = engine_main.RequestHandler()
        with (
            patch.object(engine_main, "project_exists", return_value=True),
            patch.object(engine_main, "get_project_table_path", return_value="source.csv"),
            patch.object(engine_main, "_refresh_project_config"),
            patch.object(engine_main, "UDF_ADASTri") as udf,
        ):
            handler.calculate_in_process(_request(Function="ArcRhoVec"))
        udf.assert_called_once()

    def test_a_missing_project_and_an_unknown_function_raise(self):
        handler = engine_main.RequestHandler()
        with patch.object(engine_main, "project_exists", return_value=False):
            with self.assertRaises(FileNotFoundError):
                handler.calculate_in_process(_request())
        with (
            patch.object(engine_main, "project_exists", return_value=True),
            patch.object(engine_main, "get_project_table_path", return_value="source.csv"),
            patch.object(engine_main, "_refresh_project_config"),
        ):
            with self.assertRaises(ValueError):
                handler.calculate_in_process(_request(Function="ArcRhoBogus"))
        self.assertFalse(handler._processing_lock.locked())

    def test_warmup_registers_the_calculator_with_the_canonical_runtime(self):
        handler = engine_main.RequestHandler()
        calculation = SimpleNamespace(set_in_process_calculator=Mock())
        services = ModuleType("app_server.services")
        services.engine_calculation_service = calculation
        app_server = ModuleType("app_server")
        app_server.services = services
        with (
            patch.dict(
                sys.modules,
                {"app_server": app_server, "app_server.services": services},
            ),
            patch.object(engine_main, "get_project_root", return_value=Path(TEST_TMP_ROOT)),
            patch(
                "arcrho_engine.dependent_propagation.configure_canonical_runtime",
                lambda root: None,
            ),
        ):
            engine_main._warm_canonical_runtime(handler)

        calculation.set_in_process_calculator.assert_called_once_with(
            handler.calculate_in_process
        )


if __name__ == "__main__":
    unittest.main()
