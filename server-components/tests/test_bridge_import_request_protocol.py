from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_bridge import main as bridge_main  # noqa: E402
from arcrho_bridge import resq_client  # noqa: E402
from arcrho_bridge.resq_import_contract import (  # noqa: E402
    load_resq_reserving_class_import_contract,
)


def _import_request(**overrides):
    payload = {
        "Function": bridge_main.RESQ_IMPORT_FUNCTION,
        "ContractVersion": bridge_main.RESQ_IMPORT_CONTRACT_VERSION,
        "RequestId": "import-request-123",
        "ProjectName": "Demo",
        "Path": r"Auto\PP",
        "UserName": "tester",
        "ExportMode": "configured",
    }
    payload.update(overrides)
    return payload


class BridgeImportRequestProtocolTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_bridge_uses_the_versioned_json_contract(self):
        contract = load_resq_reserving_class_import_contract()

        self.assertEqual(bridge_main.RESQ_IMPORT_FUNCTION, contract["function"])
        self.assertEqual(
            bridge_main.RESQ_IMPORT_CONTRACT_VERSION,
            contract["contract_version"],
        )
        self.assertEqual(
            bridge_main.WORKER_STALE_AFTER_SECONDS,
            contract["worker_heartbeat_max_age_seconds"],
        )
        self.assertEqual(bridge_main.WORKER_ROLE, contract["worker_role"])
        self.assertIn("configured", contract["allowed_export_modes"])

    def test_queue_and_status_paths_are_deterministic_and_server_relative(self):
        request_dir = bridge_main.resq_import_request_dir(self.server_root)
        status_path = bridge_main.resq_import_status_path(
            "import-request-123",
            self.server_root,
        )

        self.assertEqual(
            request_dir,
            self.server_root
            / "requests"
            / "RPC bridge"
            / "resq_reserving_class_import"
            / "requests",
        )
        self.assertEqual(
            status_path,
            self.server_root
            / "requests"
            / "RPC bridge"
            / "resq_reserving_class_import"
            / "statuses"
            / "import-request-123.json",
        )
        self.assertTrue(request_dir.is_dir())
        self.assertTrue(status_path.parent.is_dir())

    def test_created_and_moved_json_events_request_a_worker_thread_scan(self):
        handler = bridge_main.BridgeRequestHandler(Mock())
        handler.process_file = Mock()

        handler.on_created(
            SimpleNamespace(is_directory=False, src_path=r"E:\requests\created.json")
        )
        handler.on_moved(
            SimpleNamespace(
                is_directory=False,
                src_path=r"E:\requests\request.tmp",
                dest_path=r"E:\requests\moved.json",
            )
        )
        handler.on_created(
            SimpleNamespace(is_directory=False, src_path=r"E:\requests\request.tmp")
        )

        handler.process_file.assert_not_called()
        self.assertTrue(handler.consume_scan_request())
        self.assertFalse(handler.consume_scan_request())

    def test_import_request_is_claimed_before_status_and_validation(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        events = []
        request = _import_request(ProjectName="")

        def record_status(_request, status, **_kwargs):
            events.append(status)
            return True

        with (
            patch.object(bridge_main, "read_json", return_value=request),
            patch.object(
                bridge_main,
                "safe_remove",
                side_effect=lambda _path: events.append("claim") or True,
            ),
            patch.object(
                bridge_main,
                "_write_resq_import_status",
                side_effect=record_status,
            ),
        ):
            self.assertTrue(handler.process_file(Path("request.json")))

        self.assertEqual(events, ["claim", "processing", "error"])
        client.write_resq_reserving_class_import.assert_not_called()

    def test_processing_status_failure_stops_before_validation_or_import(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)

        with (
            patch.object(bridge_main, "read_json", return_value=_import_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(bridge_main, "_write_resq_import_status", return_value=False),
            patch.object(handler, "_validate_resq_import_request") as validate,
        ):
            handler.process_file(Path("request.json"))

        validate.assert_not_called()
        client.write_resq_reserving_class_import.assert_not_called()

    def test_import_success_publishes_progress_and_terminal_result(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        request = _import_request()
        statuses = []

        def record_status(_request, status, **kwargs):
            statuses.append((status, kwargs))
            return True

        def write_import(_request, *, progress_callback=None):
            self.assertIsNotNone(progress_callback)
            progress_callback({"stage": "methods", "completed": 2, "total": 4})
            return {"datasets_imported": 2, "methods_imported": 1}

        client.write_resq_reserving_class_import.side_effect = write_import
        with (
            patch.object(bridge_main, "read_json", return_value=request),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(
                bridge_main,
                "_write_resq_import_status",
                side_effect=record_status,
            ),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual(
            statuses,
            [
                ("processing", {}),
                (
                    "processing",
                    {"progress": {"stage": "methods", "completed": 2, "total": 4}},
                ),
                (
                    "success",
                    {"result": {"datasets_imported": 2, "methods_imported": 1}},
                ),
            ],
        )
        client.write_resq_reserving_class_import.assert_called_once()
        called_request = client.write_resq_reserving_class_import.call_args.args[0]
        self.assertEqual(called_request["ProjectName"], "Demo")
        self.assertIn(
            "progress_callback",
            client.write_resq_reserving_class_import.call_args.kwargs,
        )

    def test_long_resq_import_keeps_the_worker_heartbeat_fresh(self):
        client = Mock()
        heartbeats = []
        handler = bridge_main.BridgeRequestHandler(
            client,
            worker_heartbeat=lambda: heartbeats.append(time.monotonic()),
            heartbeat_interval_sec=0.01,
        )
        request = _import_request()

        def write_import(_request, *, progress_callback=None):
            initial_count = len(heartbeats)
            deadline = time.monotonic() + 0.2
            while len(heartbeats) == initial_count and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertGreater(len(heartbeats), initial_count)
            return {"datasets_imported": 1}

        client.write_resq_reserving_class_import.side_effect = write_import
        with (
            patch.object(bridge_main, "get_project_root", return_value=self.server_root),
            patch.object(bridge_main, "_write_resq_import_status", return_value=True),
        ):
            handler._process_resq_import_request(request)

        self.assertGreaterEqual(len(heartbeats), 2)

    def test_a_running_import_keeps_its_status_fresh_for_reconciliation(self):
        # Reconciliation reads the status mtime, so a slow but healthy import
        # must renew it even when it publishes no progress event.
        client = Mock()
        status_path = bridge_main.resq_import_status_path(
            "import-request-123",
            self.server_root,
        )
        status_path.write_text(
            json.dumps({"status": "processing", "request_id": "import-request-123"}),
            encoding="utf-8",
        )
        aged = time.time() - 600
        os.utime(status_path, (aged, aged))
        handler = bridge_main.BridgeRequestHandler(client, heartbeat_interval_sec=0.01)

        def write_import(_request, *, progress_callback=None):
            return {"datasets_imported": 1}

        client.write_resq_reserving_class_import.side_effect = write_import
        with (
            patch.object(bridge_main, "get_project_root", return_value=self.server_root),
            patch.object(bridge_main, "_write_resq_import_status", return_value=True),
        ):
            handler._process_resq_import_request(_import_request())

        self.assertGreater(status_path.stat().st_mtime, aged)

    def test_startup_closes_out_statuses_no_live_worker_is_renewing(self):
        interrupted = self._write_status("interrupted", "processing", age_seconds=600)
        live = self._write_status("live", "processing", age_seconds=1)
        finished = self._write_status("finished", "success", age_seconds=600)
        staged = self.server_root / "r" / "interrupted" / "d" / "rc"
        staged.mkdir(parents=True)
        (staged / "index.json").write_text("{}", encoding="utf-8")

        reconciled = bridge_main.reconcile_orphaned_resq_import_statuses(
            self.server_root,
            max_age_seconds=bridge_main.RESQ_IMPORT_STATUS_STALE_SECONDS,
        )

        self.assertEqual(reconciled, ("interrupted",))
        closed = json.loads(interrupted.read_text(encoding="utf-8"))
        self.assertEqual(closed["status"], "error")
        self.assertEqual(closed["request_id"], "interrupted")
        self.assertIn("stopped before this import finished", closed["message"])
        # Another user's running import and an already-terminal one are untouched.
        self.assertEqual(
            json.loads(live.read_text(encoding="utf-8"))["status"],
            "processing",
        )
        self.assertEqual(
            json.loads(finished.read_text(encoding="utf-8"))["status"],
            "success",
        )
        # The dead import's staged copy is reclaimed with it.
        self.assertFalse((self.server_root / "r" / "interrupted").exists())

    def test_reconciliation_keeps_a_half_committed_import_backup(self):
        self._write_status("half-committed", "processing", age_seconds=600)
        backup = self.server_root / "r" / "half-committed" / "previous" / "sidecars"
        backup.mkdir(parents=True)
        (backup / "old-resq.json").write_text("{}", encoding="utf-8")

        bridge_main.reconcile_orphaned_resq_import_statuses(self.server_root)

        self.assertTrue((backup / "old-resq.json").is_file())

    def _write_status(self, request_id, status, *, age_seconds):
        path = bridge_main.resq_import_status_path(request_id, self.server_root)
        path.write_text(
            json.dumps({"status": status, "request_id": request_id}),
            encoding="utf-8",
        )
        stamp = time.time() - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_client_delegates_full_import_to_the_canonical_runner(self):
        request = _import_request()
        progress_callback = Mock()
        expected = {"committed": True}
        client = resq_client.ResQClient()

        with patch(
            "arcrho_bridge.resq_import_runner.run_reserving_class_import",
            return_value=expected,
        ) as run_import, patch.object(client, "_ensure_com_initialized") as ensure_com:
            result = client.write_resq_reserving_class_import(
                request,
                progress_callback=progress_callback,
            )

        self.assertIs(result, expected)
        ensure_com.assert_called_once_with()
        run_import.assert_called_once_with(request, progress_callback=progress_callback)
        self.assertIsNone(client.app)

    def test_import_error_publishes_terminal_error_without_calling_legacy_writer(self):
        client = Mock()
        error = RuntimeError("ResQ is busy")
        error.status_result = {
            "errors": 1,
            "engine_errors": 0,
            "error_details": [{"kind": "dfm", "name": "Broken DFM", "message": "Missing input."}],
        }
        client.write_resq_reserving_class_import.side_effect = error
        handler = bridge_main.BridgeRequestHandler(client)
        statuses = []

        def record_status(_request, status, **kwargs):
            statuses.append((status, kwargs))
            return True

        with (
            patch.object(bridge_main, "read_json", return_value=_import_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(
                bridge_main,
                "_write_resq_import_status",
                side_effect=record_status,
            ),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual(statuses[0], ("processing", {}))
        self.assertEqual(statuses[-1][0], "error")
        self.assertIn("ResQ is busy", str(statuses[-1][1]["message"]))
        self.assertEqual(statuses[-1][1]["result"], error.status_result)
        client.write_error.assert_not_called()

    def test_status_writer_is_atomic_and_never_uses_request_status_path(self):
        request = _import_request(
            StatusPath=r"Q:\Arco Server\not-allowed.json",
        )
        with patch.object(bridge_main, "get_project_root", return_value=self.server_root):
            self.assertTrue(
                bridge_main._write_resq_import_status(
                    request,
                    "processing",
                    progress={"stage": "discovering", "completed": 1, "total": 3},
                )
            )

        status_path = bridge_main.resq_import_status_path(
            request["RequestId"],
            self.server_root,
        )
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "processing")
        self.assertEqual(payload["request_id"], request["RequestId"])
        self.assertEqual(payload["contract_version"], bridge_main.RESQ_IMPORT_CONTRACT_VERSION)
        self.assertEqual(payload["progress"]["stage"], "discovering")
        self.assertFalse(Path(request["StatusPath"]).exists())
        self.assertEqual(tuple(status_path.parent.glob("*.tmp")), ())

    def test_validation_rejects_unknown_contract_and_producer_local_paths(self):
        handler = bridge_main.BridgeRequestHandler(Mock())

        with self.assertRaisesRegex(ValueError, "Unsupported ContractVersion"):
            handler._validate_resq_import_request(_import_request(ContractVersion=99))
        with self.assertRaisesRegex(ValueError, "must not supply path"):
            handler._validate_resq_import_request(
                _import_request(StatusPath=r"Z:\Arco Server\status.json")
            )
        with self.assertRaisesRegex(ValueError, "ExportMode must be one of"):
            handler._validate_resq_import_request(
                _import_request(ExportMode="not-a-real-mode")
            )

    def test_validation_accepts_only_logical_project_and_relative_rc_identities(self):
        handler = bridge_main.BridgeRequestHandler(Mock())

        with self.assertRaisesRegex(ValueError, "one logical path segment"):
            handler._validate_resq_import_request(
                _import_request(ProjectName=r"Demo\Other")
            )
        with self.assertRaisesRegex(ValueError, "one logical path segment"):
            handler._validate_resq_import_request(
                _import_request(ProjectName="Demo*Archive")
            )
        with self.assertRaisesRegex(ValueError, "relative Windows Arco"):
            handler._validate_resq_import_request(
                _import_request(Path=r"C:\Arco Server\projects\Demo")
            )
        with self.assertRaisesRegex(ValueError, "without '..'"):
            handler._validate_resq_import_request(
                _import_request(Path=r"Auto\..\Other")
            )
        with self.assertRaisesRegex(ValueError, "without '..'"):
            handler._validate_resq_import_request(
                _import_request(Path=r"Auto\\PP")
            )

        request = _import_request(ProjectName=" Demo ", Path="Auto/PP")
        handler._validate_resq_import_request(request)
        self.assertEqual(request["ProjectName"], "Demo")
        self.assertEqual(request["Path"], r"Auto\PP")

    def test_discovers_only_fresh_resq_connected_bridge_workers(self):
        folder = (
            self.server_root
            / "runtime"
            / "instances"
            / "arcrho_bridge_worker"
        )
        folder.mkdir(parents=True, exist_ok=True)
        fresh = folder / "fresh.json"
        stale = folder / "stale.json"
        wrong_role = folder / "wrong-role.json"
        no_resq = folder / "no-resq.json"
        string_false = folder / "string-false.json"
        fresh.write_text(
            json.dumps({"Role": "bridge_worker", "ResQGuiRunning": True}),
            encoding="utf-8",
        )
        stale.write_text(
            json.dumps({"Role": "bridge_worker", "ResQGuiRunning": True}),
            encoding="utf-8",
        )
        wrong_role.write_text(
            json.dumps({"Role": "bridge", "ResQGuiRunning": True}),
            encoding="utf-8",
        )
        no_resq.write_text(
            json.dumps({"Role": "bridge_worker", "ResQGuiRunning": False}),
            encoding="utf-8",
        )
        string_false.write_text(
            json.dumps({"Role": "bridge_worker", "ResQGuiRunning": "false"}),
            encoding="utf-8",
        )
        now = time.time()
        os.utime(fresh, (now - 1, now - 1))
        os.utime(stale, (now - 7, now - 7))
        os.utime(wrong_role, (now - 1, now - 1))
        os.utime(no_resq, (now - 1, now - 1))
        os.utime(string_false, (now - 1, now - 1))

        discovered = bridge_main.discover_fresh_bridge_worker_heartbeats(
            self.server_root,
            max_age_seconds=bridge_main.WORKER_STALE_AFTER_SECONDS,
            now=now,
        )

        self.assertEqual(discovered, (fresh,))

    def test_process_pending_retries_unclaimed_files_on_the_next_mapped_share_scan(self):
        handler = bridge_main.BridgeRequestHandler(Mock())
        request_path = Path("pending.json")
        handler.process_file = Mock(side_effect=(False, True))

        with patch.object(bridge_main, "list_json_files_by_mtime", return_value=[request_path]):
            handler.process_pending(Path("requests"))
            handler.process_pending(Path("requests"))

        self.assertEqual(handler.process_file.call_args_list, [call(request_path), call(request_path)])


if __name__ == "__main__":
    unittest.main()
