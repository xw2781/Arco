"""Cover the Review Reserving Class against ResQ macro's client side.

The macro owns no ResQ session: it publishes a logical request to the shared
Arco Bridge queue and opens the workbook a ResQ-connected worker wrote. These
tests cover what is the macro's own -- the request it publishes, the wait, the
workbook it reaches through its own server root, and what it tells the person
-- against the Bridge contract the worker reads, which a macro cannot import.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

_MACRO_PATH = (
    Path(__file__).resolve().parents[1] / "macros" / "review_reserving_class_against_resq.py"
)
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "server-components"
    / "src"
    / "arcrho_bridge"
    / "resq_reserving_class_review_contract.json"
)
_IMPORT_CONTRACT_PATH = _CONTRACT_PATH.with_name("resq_reserving_class_import_contract.json")
_REQUEST_ID = "a1b2c3d4e5f6478899aabbccddeeff00"
_CONTRACT_VERSION = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))["contract_version"]
_WORKBOOK_RELATIVE = str(Path("projects") / "Demo" / "users" / "tester" / "reviews" / "book.xlsx")

_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def load_macro_module():
    spec = importlib.util.spec_from_file_location(
        "review_reserving_class_against_resq_macro_under_test", _MACRO_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the ResQ reserving-class review macro.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A missing Bridge is judged after a silence, not a look; keep it short here.
    module.BRIDGE_SILENCE_LIMIT_SEC = 0.05
    module.POLL_INTERVAL_SEC = 0.01
    return module


def _result(**overrides):
    payload = {
        "review_api_version": 2,
        "project_name": "Demo",
        "rc_path": r"Auto\PP",
        "workbook_relative_path": _WORKBOOK_RELATIVE,
        "workbook_name": "book.xlsx",
        "datasets_compared": 12,
        "datasets_needing_review": 2,
        "result_selections_compared": 3,
        "result_selections_needing_review": 0,
        "dfm_notes_compared": 7,
        "dfm_notes_needing_review": 1,
        "skipped_datasets": 1,
        "skipped_result_selections": 0,
        "skipped_dfm_notes": 0,
        "reserving_class_errors": [],
        "flagged": [],
        "needs_attention": True,
    }
    payload.update(overrides)
    return payload


def _success_status(result=None):
    return {
        "contract_version": _CONTRACT_VERSION,
        "status": "success",
        "updated_at": "2026-09-21T10:00:00",
        "request_id": _REQUEST_ID,
        "result": result if result is not None else _result(),
    }


class _Progress:
    def __init__(self):
        self.total = 0
        self.completed = 0
        self.updates = []
        self.closed = False

    def update(self, **kwargs):
        self.updates.append(kwargs)
        self.total = int(kwargs.get("total", self.total) or 0)
        self.completed = int(kwargs.get("completed", self.completed) or 0)

    def close(self, **_kwargs):
        self.closed = True


class _UI:
    def __init__(self, context=None):
        self.messages = []
        self.progress_calls = []
        self.project_instance = types.SimpleNamespace(
            context=lambda **_kwargs: context
            if context is not None
            else {"projectName": "Demo", "selectedPath": r"Auto\PP"}
        )

    def message_box(self, message, **kwargs):
        self.messages.append((message, kwargs))
        return {"ok": True}

    def progress_bar(self, **kwargs):
        self.progress_calls.append(kwargs)
        return _Progress()


class ReviewMacroTests(unittest.TestCase):
    def setUp(self):
        self.module = load_macro_module()
        self.tempdir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.tempdir.cleanup)
        self.server_root = Path(self.tempdir.name)
        self.ui = _UI()
        self.opened = []
        self.api_module = types.ModuleType("arcrho_api")
        self.api_module.ArcRhoUI = lambda: self.ui
        self.api_module.get_server_root = lambda **_kwargs: self.server_root
        def hosted_publish(kind, **kwargs):
            self.assertEqual(kind, "resq_review_request_publish")
            path, _ = self.module._request_paths(self.server_root, kwargs["request_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(kwargs["request"]), encoding="utf-8")
            return {"ok": True}

        self.gateway = Mock()
        self.gateway.mutate.side_effect = hosted_publish
        patcher = patch("arcrho_api.gateway.GatewayClient", return_value=self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)


    def test_gateway_refusal_never_publishes_a_local_request(self):
        identifier, payload = self.module.create_review_request(project_name="Demo", rc_path="COL")
        self.gateway.mutate.side_effect = RuntimeError("Gateway unavailable")
        with patch.object(Path, "open", side_effect=AssertionError("Client file write")):
            with self.assertRaisesRegex(self.module.BridgeRequestError, "Gateway unavailable"):
                self.module.publish_review_request(server_root=self.server_root, request_id=identifier, payload=payload)

    def _write_worker(self, *, role="bridge_worker", gui_running=True, age_sec=0.0):
        path = self.server_root / self.module.BRIDGE_WORKER_DIR / "worker.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"Role": role, "ResQGuiRunning": gui_running}), encoding="utf-8"
        )
        if age_sec:
            stamp = time.time() - age_sec
            os.utime(path, (stamp, stamp))
        return path

    def _publish_status(self, status):
        original = self.module.publish_review_request

        def publish_and_respond(**kwargs):
            request_path = original(**kwargs)
            _, status_path = self.module._request_paths(
                kwargs["server_root"], kwargs["request_id"]
            )
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(status), encoding="utf-8")
            return request_path

        return publish_and_respond

    def _run_macro(self, status):
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)
        with (
            patch.dict(sys.modules, {"arcrho_api": self.api_module}),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module, "publish_review_request", side_effect=self._publish_status(status)
            ),
            patch.object(self.module.os, "startfile", side_effect=self.opened.append, create=True),
        ):
            return self.module.run_macro()

    def test_embedded_adapter_matches_canonical_bridge_contract(self):
        contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        import_contract = json.loads(_IMPORT_CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(self.module.REQUEST_FUNCTION, contract["function"])
        self.assertEqual(self.module.CONTRACT_VERSION, contract["contract_version"])
        self.assertEqual(
            tuple(self.module.REQUEST_RELATIVE_DIR.parts),
            tuple(contract["request_relative_dir"]),
        )
        self.assertEqual(
            tuple(self.module.STATUS_RELATIVE_DIR.parts),
            tuple(contract["status_relative_dir"]),
        )
        self.assertEqual(
            self.module.REQUIRED_REQUEST_FIELDS,
            tuple(contract["required_request_fields"]),
        )
        self.assertEqual(
            tuple(self.module.BRIDGE_WORKER_DIR.parts),
            tuple(import_contract["worker_heartbeat_relative_dir"]),
        )
        self.assertEqual(
            self.module.BRIDGE_WORKER_MAX_AGE_SEC,
            import_contract["worker_heartbeat_max_age_seconds"],
        )
        self.assertEqual(
            self.module.FORBIDDEN_PATH_FIELDS, tuple(import_contract["forbidden_path_fields"])
        )
        self.assertEqual(self.module.STATUS_VALUES, frozenset(import_contract["status_values"]))

    def test_logical_identifiers_match_bridge_request_validation(self):
        self.assertEqual(self.module._logical_project_name("Demo"), "Demo")
        self.assertEqual(self.module._logical_rc_path("Auto/PP"), r"Auto\PP")

        for project_name in ("Demo:Archive", "Demo/Archive", r"Demo\Archive", ".", ".."):
            with self.subTest(project_name=project_name):
                with self.assertRaises(ValueError):
                    self.module._logical_project_name(project_name)

        for rc_path in ("", r"\Auto\PP", r"Auto\\PP", r"Auto\..\PP", "Auto:PP", "Auto\x00PP"):
            with self.subTest(rc_path=rc_path):
                with self.assertRaises(ValueError):
                    self.module._logical_rc_path(rc_path)

    def test_unavailable_bridge_stops_before_progress_or_request_publication(self):
        with patch.dict(sys.modules, {"arcrho_api": self.api_module}):
            result = self.module.run_macro()

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.ui.progress_calls, [])
        self.assertFalse((self.server_root / self.module.REQUEST_RELATIVE_DIR).exists())

    def test_a_stale_or_non_resq_worker_does_not_pass_the_preflight(self):
        for kwargs in ({"age_sec": 60.0}, {"gui_running": False}, {"role": "engine_worker"}):
            with self.subTest(**kwargs):
                self._write_worker(**kwargs)
                with self.assertRaises(self.module.BridgeUnavailableError):
                    self.module.require_live_bridge_workers(self.server_root, sleep=lambda _s: None)

    def test_publishes_a_location_independent_request_and_opens_the_workbook(self):
        self._write_worker()

        result = self._run_macro(_success_status())

        request_path, status_path = self.module._request_paths(self.server_root, _REQUEST_ID)
        self.assertTrue(request_path.is_file())
        self.assertTrue(status_path.is_file())
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload),
            {"Function", "ContractVersion", "RequestId", "ProjectName", "Path", "UserName"},
        )
        self.assertEqual(payload["Function"], "ReviewResQReservingClass")
        self.assertEqual(payload["ContractVersion"], _CONTRACT_VERSION)
        self.assertEqual(payload["ProjectName"], "Demo")
        self.assertEqual(payload["Path"], r"Auto\PP")
        self.assertTrue(payload["UserName"])
        self.assertNotIn(str(self.server_root), json.dumps(payload))
        self.assertFalse(request_path.with_name(f".{_REQUEST_ID}.tmp").exists())

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["workbook_opened"])
        self.assertEqual(self.opened, [self.server_root / _WORKBOOK_RELATIVE])

    def test_the_request_goes_to_the_reserving_class_the_page_has_open(self):
        self._write_worker()
        self.ui = _UI(context={"project_name": "Other", "path": r"Home\HO"})
        self.api_module.ArcRhoUI = lambda: self.ui

        self._run_macro(_success_status())

        request_path, _ = self.module._request_paths(self.server_root, _REQUEST_ID)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ProjectName"], "Other")
        self.assertEqual(payload["Path"], r"Home\HO")

    def test_the_workbook_is_reached_through_this_computers_own_server_root(self):
        """The Bridge names the file under the root, never by its own drive."""

        path = self.module.workbook_path(r"\\server\share\Arco Server", _result())

        self.assertEqual(path, Path(r"\\server\share\Arco Server") / _WORKBOOK_RELATIVE)

    def test_a_result_without_a_workbook_is_refused(self):
        with self.assertRaisesRegex(self.module.BridgeRequestError, "where it wrote"):
            self.module.workbook_path(self.server_root, _result(workbook_relative_path=""))

    def test_the_completion_names_what_needs_review(self):
        message = self.module.review_summary(_result(), r"Auto\PP")

        self.assertIn(r"Auto\PP", message)
        self.assertIn("12 compared, 2 need review", message)
        self.assertIn("3 compared, 0 need review", message)
        self.assertIn("DFM notes: 7 compared, 1 need review", message)
        self.assertIn("1 item(s) were left out", message)

    def test_a_reserving_class_resq_refused_is_named_in_the_completion(self):
        message = self.module.review_summary(
            _result(reserving_class_errors=[{"rc_path": r"Auto\PP", "note": "no such class"}]),
            r"Auto\PP",
        )

        self.assertIn("ResQ refused: no such class", message)

    def test_a_clean_review_still_reports_and_opens(self):
        self._write_worker()

        result = self._run_macro(
            _success_status(_result(datasets_needing_review=0, needs_attention=False))
        )

        self.assertTrue(result["workbook_opened"])
        self.assertEqual(self.ui.messages[-1][1]["kind"], "info")

    def test_a_workbook_that_will_not_open_is_reported_rather_than_hidden(self):
        self._write_worker()
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            patch.dict(sys.modules, {"arcrho_api": self.api_module}),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_review_request",
                side_effect=self._publish_status(_success_status()),
            ),
            patch.object(
                self.module.os,
                "startfile",
                side_effect=OSError("no application is associated"),
                create=True,
            ),
        ):
            result = self.module.run_macro()

        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["workbook_opened"])
        self.assertIn("no application is associated", result["message"])
        self.assertIn(_WORKBOOK_RELATIVE, result["message"])

    def test_a_bridge_error_is_reported_without_opening_anything(self):
        self._write_worker()

        result = self._run_macro({
            "contract_version": _CONTRACT_VERSION,
            "status": "error",
            "request_id": _REQUEST_ID,
            "message": "ResQ refused the reserving class",
        })

        self.assertEqual(result["status"], "error")
        self.assertIn("ResQ refused the reserving class", result["message"])
        self.assertEqual(self.opened, [])

    def test_a_failure_stamped_by_the_shared_queue_is_still_reported(self):
        """An interrupted request is closed out by the queue it shares.

        That status carries the synchronization queue's version, and a
        failure is a message and nothing else, so it must still reach the
        person rather than being refused as unreadable.
        """

        self._write_worker()

        result = self._run_macro({
            "contract_version": _CONTRACT_VERSION + 99,
            "status": "error",
            "request_id": _REQUEST_ID,
            "message": "The Arco Bridge stopped before this run finished.",
        })

        self.assertEqual(result["status"], "error")
        self.assertIn("stopped before this run finished", result["message"])

    def test_a_success_stamped_by_another_queue_is_never_accepted(self):
        self._write_worker()

        result = self._run_macro(_success_status() | {"contract_version": _CONTRACT_VERSION + 99})

        self.assertEqual(result["status"], "error")
        self.assertIn("unsupported status contract version", result["message"])
        self.assertEqual(self.opened, [])

    def test_an_unclaimed_request_fails_promptly_with_a_bridge_restart_message(self):
        self._write_worker()

        with self.assertRaisesRegex(self.module.BridgeRequestError, "did not claim"):
            self.module.wait_for_review_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                claim_timeout_sec=0.05,
                timeout_sec=1.0,
                poll_interval_sec=0.01,
            )

    def test_a_page_with_no_reserving_class_open_publishes_nothing(self):
        self._write_worker()
        self.ui = _UI(context={"projectName": "Demo"})
        self.api_module.ArcRhoUI = lambda: self.ui

        with patch.dict(sys.modules, {"arcrho_api": self.api_module}):
            result = self.module.run_macro()

        self.assertEqual(result["status"], "error")
        self.assertFalse((self.server_root / self.module.REQUEST_RELATIVE_DIR).exists())


if __name__ == "__main__":
    unittest.main()
