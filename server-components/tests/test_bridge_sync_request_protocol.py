"""Cover the Bridge's ResQ reserving-class synchronization queue.

A synchronization is served by the same ResQ-connected worker as an import,
from a sibling queue folder, through the same claim/status/heartbeat protocol.
These tests pin that: the worker reads its function, folders, and phases from
the versioned contract; it claims a request before reporting anything; and it
refuses a request that is malformed, mis-versioned, or tries to name a path.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_bridge import main as bridge_main  # noqa: E402
from arcrho_bridge.resq_import_contract import (  # noqa: E402
    load_resq_reserving_class_import_contract,
)
from arcrho_bridge.resq_sync_contract import (  # noqa: E402
    ResQSyncContractError,
    load_resq_reserving_class_sync_contract,
)


_REQUEST_ID = "sync-request-123"


def _reviewed_row(row_id: str = "paid-loss") -> dict:
    return {
        "Id": row_id,
        "Name": row_id,
        "Signature": {"key": row_id, "action": "arcrho_to_resq"},
    }


def _sync_request(**overrides):
    payload = {
        "Function": bridge_main.RESQ_SYNC_FUNCTION,
        "ContractVersion": bridge_main.RESQ_SYNC_CONTRACT_VERSION,
        "RequestId": _REQUEST_ID,
        "ProjectName": "Demo",
        "Path": r"Auto\PP",
        "UserName": "tester",
        "Phase": "preview",
    }
    payload.update(overrides)
    return payload


class BridgeSyncContractTests(unittest.TestCase):
    def test_bridge_uses_the_versioned_json_contract(self):
        contract = load_resq_reserving_class_sync_contract()

        self.assertEqual(bridge_main.RESQ_SYNC_FUNCTION, contract["function"])
        self.assertEqual(
            bridge_main.RESQ_SYNC_CONTRACT_VERSION,
            contract["contract_version"],
        )
        self.assertEqual(
            bridge_main._RESQ_SYNC_ALLOWED_PHASES,
            frozenset(contract["allowed_phases"]),
        )
        self.assertEqual(
            bridge_main._RESQ_SYNC_SELECTION_FIELD,
            contract["selection_field"],
        )

    def test_worker_and_status_facts_are_taken_from_the_import_contract(self):
        sync_contract = load_resq_reserving_class_sync_contract()
        import_contract = load_resq_reserving_class_import_contract()

        for key in (
            "worker_role",
            "worker_heartbeat_relative_dir",
            "worker_heartbeat_max_age_seconds",
            "status_values",
            "forbidden_path_fields",
        ):
            with self.subTest(field=key):
                self.assertEqual(sync_contract[key], import_contract[key])

        raw = json.loads(
            (ENGINE_SRC / "arcrho_bridge" / "resq_reserving_class_sync_contract.json").read_text(
                encoding="utf-8"
            )
        )
        for key in (
            "worker_role",
            "worker_heartbeat_relative_dir",
            "worker_heartbeat_max_age_seconds",
            "status_values",
            "forbidden_path_fields",
        ):
            self.assertNotIn(key, raw)

    def test_a_contract_that_restates_worker_facts_is_rejected(self):
        from arcrho_bridge import resq_sync_contract

        payload = json.loads(
            (ENGINE_SRC / "arcrho_bridge" / "resq_reserving_class_sync_contract.json").read_text(
                encoding="utf-8"
            )
        )
        payload["worker_role"] = "bridge_worker"

        with self.assertRaisesRegex(ResQSyncContractError, "import contract"):
            resq_sync_contract._validated_contract(payload)

    def test_the_sync_queue_is_a_distinct_sibling_of_the_import_queue(self):
        sync_contract = load_resq_reserving_class_sync_contract()
        import_contract = load_resq_reserving_class_import_contract()

        self.assertEqual(
            tuple(sync_contract["request_relative_dir"])[:2],
            tuple(import_contract["request_relative_dir"])[:2],
        )
        self.assertNotEqual(
            tuple(sync_contract["request_relative_dir"])[2],
            tuple(import_contract["request_relative_dir"])[2],
        )


class BridgeSyncQueuePathTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_queue_and_status_paths_are_deterministic_and_server_relative(self):
        request_dir = bridge_main.resq_sync_request_dir(self.server_root)
        status_path = bridge_main.resq_sync_status_path(_REQUEST_ID, self.server_root)

        self.assertEqual(
            request_dir,
            self.server_root
            / "requests"
            / "RPC bridge"
            / "resq_reserving_class_sync"
            / "requests",
        )
        self.assertEqual(status_path, request_dir.with_name("statuses") / f"{_REQUEST_ID}.json")

    def test_an_unsafe_request_id_never_resolves_a_status_path(self):
        for request_id in ("", "..", r"..\escape", "a/b"):
            with self.subTest(request_id=request_id):
                with self.assertRaises(ValueError):
                    bridge_main.resq_sync_status_path(request_id, self.server_root)

    def test_an_orphaned_processing_status_is_closed_out(self):
        status_path = bridge_main.resq_sync_status_path(_REQUEST_ID, self.server_root)
        status_path.write_text(
            json.dumps({
                "contract_version": bridge_main.RESQ_SYNC_CONTRACT_VERSION,
                "request_id": _REQUEST_ID,
                "status": "processing",
            }),
            encoding="utf-8",
        )

        reconciled = bridge_main.reconcile_orphaned_resq_sync_statuses(
            self.server_root,
            now=time.time() + bridge_main.RESQ_IMPORT_STATUS_STALE_SECONDS + 60,
        )

        self.assertEqual(reconciled, (_REQUEST_ID,))
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["contract_version"], bridge_main.RESQ_SYNC_CONTRACT_VERSION)
        self.assertIn("stopped before this synchronization finished", payload["message"])

    def test_a_fresh_processing_status_is_left_alone(self):
        status_path = bridge_main.resq_sync_status_path(_REQUEST_ID, self.server_root)
        status_path.write_text(
            json.dumps({
                "contract_version": bridge_main.RESQ_SYNC_CONTRACT_VERSION,
                "request_id": _REQUEST_ID,
                "status": "processing",
            }),
            encoding="utf-8",
        )

        self.assertEqual(bridge_main.reconcile_orphaned_resq_sync_statuses(self.server_root), ())
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "processing")


class BridgeSyncRequestHandlingTests(unittest.TestCase):
    def test_sync_request_is_claimed_before_status_and_validation(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        events = []

        def record_status(_request, status, **_kwargs):
            events.append(status)
            return True

        with (
            patch.object(bridge_main, "read_json", return_value=_sync_request(ProjectName="")),
            patch.object(
                bridge_main,
                "safe_remove",
                side_effect=lambda _path: events.append("claim") or True,
            ),
            patch.object(bridge_main, "_write_resq_sync_status", side_effect=record_status),
        ):
            self.assertTrue(handler.process_file(Path("request.json")))

        self.assertEqual(events, ["claim", "processing", "error"])
        client.write_resq_reserving_class_sync.assert_not_called()

    def test_a_sync_request_is_never_handled_by_the_import_path(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)

        with (
            patch.object(bridge_main, "read_json", return_value=_sync_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(bridge_main, "_write_resq_sync_status", return_value=True),
            patch.object(bridge_main, "_write_resq_import_status") as import_status,
        ):
            handler.process_file(Path("request.json"))

        import_status.assert_not_called()
        client.write_resq_reserving_class_import.assert_not_called()
        client.write_resq_reserving_class_sync.assert_called_once()

    def test_sync_success_publishes_progress_and_terminal_result(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        statuses = []

        def record_status(_request, status, **kwargs):
            statuses.append((status, kwargs))
            return True

        def write_sync(_request, *, progress_callback=None):
            self.assertIsNotNone(progress_callback)
            progress_callback({"event": "scan", "completed": 0, "total": 0})
            return {"status": "review_required", "preview": []}

        client.write_resq_reserving_class_sync.side_effect = write_sync
        with (
            patch.object(bridge_main, "read_json", return_value=_sync_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(bridge_main, "_write_resq_sync_status", side_effect=record_status),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual(
            statuses,
            [
                ("processing", {}),
                ("processing", {"progress": {"event": "scan", "completed": 0, "total": 0}}),
                ("success", {"result": {"status": "review_required", "preview": []}}),
            ],
        )

    def test_a_failed_sync_reports_the_error_without_a_success_status(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        statuses = []
        client.write_resq_reserving_class_sync.side_effect = RuntimeError("ResQ is unavailable")

        with (
            patch.object(bridge_main, "read_json", return_value=_sync_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(
                bridge_main,
                "_write_resq_sync_status",
                side_effect=lambda _request, status, **kwargs: statuses.append((status, kwargs)) or True,
            ),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual([status for status, _kwargs in statuses], ["processing", "error"])
        self.assertIn("ResQ is unavailable", str(statuses[-1][1]["message"]))


class SyncDfmSaveTimeTests(unittest.TestCase):
    """A confirmed upload reports the ``Modified`` its own save produced.

    ResQ stamps the method when it saves, so without this the local copy keeps
    an older time and the next sync review calls the remote newer even though
    it holds the settings ArcRho just sent.
    """

    def _client_and_method(self):
        from arcrho_bridge import resq_client

        class _OutputVector:
            Modified = "2026-08-19T09:00:00"

        class _Dfm:
            def __init__(self):
                self.OutputVector = _OutputVector()
                self.saved = False

            def Save(self):
                self.saved = True
                # ResQ moves its own timestamp forward on save.
                self.OutputVector.Modified = "2026-08-19T10:05:30.500000"

        return resq_client.ResQClient(), _Dfm()

    def _run(self, client, dfm, request):
        from arcrho_bridge import resq_client

        written = {}
        with (
            patch.object(client, "_connect"),
            patch.object(client, "_disconnect"),
            patch.object(client, "_dfm_method", return_value=dfm),
            patch.object(client, "_sync_excluded_ratios", return_value=0),
            patch.object(client, "_sync_user_entry_values", return_value=0),
            patch.object(client, "_sync_selected_ratios", return_value=0),
            patch.object(client, "_sync_cell_notes", return_value=False),
            patch.object(client, "_sync_method_notes", return_value=False),
            patch.object(resq_client, "read_json", return_value={}),
            patch.object(resq_client, "write_json", side_effect=lambda path, payload: written.update(payload)),
        ):
            returned = client.write_sync_dfm_payload(request)
        return returned, written

    def test_the_status_reports_the_time_the_save_produced(self):
        client, dfm = self._client_and_method()
        request = {"MethodJsonPath": "method.json", "DataPath": "status.json", "MethodName": "M"}
        returned, written = self._run(client, dfm, request)
        self.assertTrue(dfm.saved)
        # Read after Save(), so it is the new value rather than the one the
        # method carried when the upload started.
        self.assertEqual(returned["last_modified"], "2026-08-19T10:05:30.500000")
        self.assertEqual(written["last_modified"], returned["last_modified"])
        self.assertTrue(written["ok"])

    def test_a_method_without_a_readable_modified_reports_an_empty_value(self):
        # The app server treats an empty value as "not reported" and leaves the
        # local timestamp alone rather than inventing one.
        client, dfm = self._client_and_method()

        class _Unreadable:
            @property
            def Modified(self):
                raise RuntimeError("no such property")

        dfm.OutputVector = _Unreadable()
        dfm.Save = lambda: None
        request = {"MethodJsonPath": "method.json", "DataPath": "status.json", "MethodName": "M"}
        returned, _ = self._run(client, dfm, request)
        self.assertEqual(returned["last_modified"], "")


class BridgeWorkerWakeUpTests(unittest.TestCase):
    """A request that arrives between scans must not wait out the idle period."""

    def test_a_watchdog_event_ends_the_idle_wait_immediately(self):
        handler = bridge_main.BridgeRequestHandler.__new__(bridge_main.BridgeRequestHandler)
        handler._scan_requested = bridge_main.threading.Event()

        started = time.monotonic()
        handler.wait_for_scan_request(5)
        self.assertGreaterEqual(time.monotonic() - started, 5 - 0.5)

        handler._request_scan("request-DFM-2026.json")
        started = time.monotonic()
        handler.wait_for_scan_request(5)
        self.assertLess(time.monotonic() - started, 1)
        # The wait leaves the flag for the scan check at the top of the loop.
        self.assertTrue(handler.consume_scan_request())
        self.assertFalse(handler.consume_scan_request())

    def test_a_non_json_event_does_not_wake_the_worker(self):
        handler = bridge_main.BridgeRequestHandler.__new__(bridge_main.BridgeRequestHandler)
        handler._scan_requested = bridge_main.threading.Event()
        handler._request_scan("request-DFM-2026.tmp")
        started = time.monotonic()
        handler.wait_for_scan_request(1)
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertFalse(handler.consume_scan_request())


class BridgeSyncRequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.handler = bridge_main.BridgeRequestHandler(Mock())

    def _assert_rejected(self, request, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self.handler._validate_resq_sync_request(request)

    def test_a_valid_preview_request_is_normalized(self):
        request = _sync_request(ProjectName=" Demo ", Path="Auto/PP", Phase="PREVIEW")

        self.handler._validate_resq_sync_request(request)

        self.assertEqual(request["ProjectName"], "Demo")
        self.assertEqual(request["Path"], r"Auto\PP")
        self.assertEqual(request["Phase"], "preview")

    def test_a_valid_apply_request_keeps_its_reviewed_rows(self):
        request = _sync_request(Phase="apply", SelectedRows=[_reviewed_row()])

        self.handler._validate_resq_sync_request(request)

        self.assertEqual(request["SelectedRows"], [_reviewed_row()])

    def test_a_mis_versioned_or_misnamed_request_is_refused(self):
        self._assert_rejected(_sync_request(Function="ImportResQReservingClass"), "Function must be")
        self._assert_rejected(_sync_request(ContractVersion="1"), "ContractVersion must be")
        self._assert_rejected(_sync_request(ContractVersion=99), "Unsupported ContractVersion")

    def test_missing_logical_fields_are_refused(self):
        self._assert_rejected(_sync_request(UserName=""), "Missing request field")
        self._assert_rejected(_sync_request(Phase=""), "Missing request field")
        self._assert_rejected(_sync_request(ProjectName=".."), "one logical path segment")
        self._assert_rejected(_sync_request(Path=r"..\escape"), "relative Windows Arco")

    def test_an_unknown_phase_is_refused(self):
        self._assert_rejected(_sync_request(Phase="rollback"), "Phase must be one of")

    def test_an_apply_request_must_carry_reviewed_rows(self):
        self._assert_rejected(_sync_request(Phase="apply"), "SelectedRows must list")
        self._assert_rejected(_sync_request(Phase="apply", SelectedRows=[]), "SelectedRows must list")

    def test_a_preview_request_must_not_carry_reviewed_rows(self):
        self._assert_rejected(
            _sync_request(SelectedRows=[_reviewed_row()]),
            "preview request must not supply",
        )

    def test_an_export_request_is_accepted_without_a_selection_and_refused_with_one(self):
        request = _sync_request(Phase="Export")

        self.handler._validate_resq_sync_request(request)

        self.assertEqual(request["Phase"], "export")
        self._assert_rejected(
            _sync_request(Phase="export", SelectedRows=[_reviewed_row()]),
            "export request must not supply",
        )

    def test_a_request_may_never_name_a_path(self):
        for field in bridge_main._RESQ_IMPORT_FORBIDDEN_PATH_FIELDS:
            with self.subTest(field=field):
                self._assert_rejected(
                    _sync_request(**{field: r"E:\Arco Server"}),
                    "must not supply path field",
                )


if __name__ == "__main__":
    unittest.main()
