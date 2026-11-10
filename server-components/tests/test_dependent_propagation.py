from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_COMPONENTS_SRC = REPO_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPO_ROOT / "python-api" / "src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (SERVER_COMPONENTS_SRC, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_dependent_propagation_contract import (
    DEPENDENT_PROPAGATION_FUNCTION,
    build_dependent_propagation_request,
    dependent_propagation_request_path,
    dependent_propagation_status_path,
    validate_dependent_propagation_status,
)
from arcrho_engine import dependent_propagation
from arcrho_engine import main as engine_main


def _identity_stub(bound: list):
    """Stand in for the canonical acting-identity binding.

    ``bound`` holds the identity only while it is in scope, so the walk can
    assert it ran *inside* the binding rather than merely next to it.
    """

    @contextmanager
    def acting_identity(login_name, display_name=""):
        identity = {
            "login_name": str(login_name or "").strip(),
            "display_name": str(display_name or "").strip()
            or str(login_name or "").strip(),
        }
        bound.append(identity)
        try:
            yield identity
        finally:
            bound.pop()

    return SimpleNamespace(acting_identity=acting_identity)


def _fake_app_server(*, walk, marking, bound_identities=None):
    fake_services = types.ModuleType("app_server.services")
    fake_services.calculated_dataset_service = SimpleNamespace(
        recalculate_dependents=walk
    )
    fake_services.dataset_sidecar_status_service = SimpleNamespace(
        refresh_method_statuses_for_dependents=marking
    )
    fake_services.user_identity_service = _identity_stub(
        bound_identities if bound_identities is not None else []
    )
    fake_app_server = types.ModuleType("app_server")
    fake_app_server.services = fake_services
    return {"app_server": fake_app_server, "app_server.services": fake_services}


class DependentPropagationEngineTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def setUp(self) -> None:
        logs_tmp = REPO_ROOT / "test"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _publish_request(self, request_id: str | None = None) -> tuple[Path, dict]:
        request = build_dependent_propagation_request(
            request_id=request_id or self.REQUEST_ID,
            project_name="Demo",
            path="HPPREF\\HOL",
            changed_roots=[{"dataset_name": "Paid", "dataset_type": "Paid Loss"}],
            user_name="tester",
        )
        path = dependent_propagation_request_path(self.root, request["RequestId"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(request), encoding="utf-8")
        return path, request

    def test_walk_failure_summary_names_dataset_and_method_failures(self) -> None:
        message = dependent_propagation._summarize_walk_failure(
            {
                "skipped": [
                    {"dataset_name": "C 61 Reported - CWOP"},
                    {
                        "dataset_type_name": "F 63 - Expected Net Loss % * Earned Premium",
                        "reason": "dependency_error",
                        "errors": ["Ambiguous dependency: P 06 Net Loss"],
                    },
                ],
                "result_selection_updates": {
                    "ok": False,
                    "errors": [
                        {
                            "dataset_name": "C 91 - Current Qtr Indicated",
                            "reason": "Required precedent needs review: C 41 - BF Reported ex CWOP",
                        }
                    ],
                },
                "bootstrap_updates": {"ok": True, "errors": []},
            }
        )
        self.assertIn("C 61 Reported - CWOP", message)
        # A skip states its own cause, so the reader is not left with a name
        # and no reason to act on.
        self.assertIn(
            "F 63 - Expected Net Loss % * Earned Premium: "
            "Ambiguous dependency: P 06 Net Loss",
            message,
        )
        self.assertIn(
            "C 91 - Current Qtr Indicated: Required precedent needs review: "
            "C 41 - BF Reported ex CWOP",
            message,
        )
        self.assertIn("save again or refresh to retry", message)

        generic = dependent_propagation._summarize_walk_failure({"skipped": []})
        self.assertIn("One or more dependent updates failed.", generic)

    def test_claimed_walk_preserves_review_status_before_running(self) -> None:
        calls: list[tuple] = []

        def record_marking(*args, **kwargs):
            calls.append(("mark", args, kwargs))
            return []

        def record_walk(*args, **kwargs):
            calls.append(("walk", args, kwargs))
            return {"ok": True}

        _path, request = self._publish_request()
        progress: list[dict] = []
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules,
                _fake_app_server(walk=record_walk, marking=record_marking),
            ),
        ):
            result = dependent_propagation.execute_dependent_propagation(
                self.root,
                request,
                additional_roots=[
                    {"dataset_name": "Extra", "dataset_type": "Extra Type"}
                ],
                progress_callback=progress.append,
            )

        self.assertTrue(result["ok"])
        self.assertEqual([kind for kind, *_ in calls], ["walk"])
        walk_args, walk_kwargs = calls[0][1], calls[0][2]
        self.assertEqual(walk_args, ("Demo", "HPPREF\\HOL", "Paid", "Paid Loss"))
        self.assertEqual(walk_kwargs["additional_roots"], [("Extra", "Extra Type")])

    def test_successful_walk_does_not_call_the_failure_marker(self) -> None:
        def failing_marking(*_args, **_kwargs):
            raise OSError("sidecar folder unavailable")

        _path, request = self._publish_request()
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules,
                _fake_app_server(
                    walk=lambda *args, **kwargs: {"ok": True}, marking=failing_marking
                ),
            ),
        ):
            result = dependent_propagation.execute_dependent_propagation(
                self.root, request
            )
        self.assertTrue(result["ok"])

    def test_the_walk_runs_as_the_user_whose_save_queued_it(self) -> None:
        # The walk re-saves every dependent it recalculates. This instance runs
        # under its own service profile, so without the binding those sidecars
        # would name the instance instead of the person who saved.
        bound: list = []
        seen: list = []

        def record_walk(*_args, **_kwargs):
            seen.append(list(bound))
            return {"ok": True}

        _path, request = self._publish_request()
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules,
                _fake_app_server(
                    walk=record_walk,
                    marking=lambda *args, **kwargs: [],
                    bound_identities=bound,
                ),
            ),
        ):
            dependent_propagation.execute_dependent_propagation(self.root, request)

        self.assertEqual(
            seen, [[{"login_name": "tester", "display_name": "tester"}]]
        )
        self.assertEqual(bound, [], "the binding must not outlive the walk")

    def _propagation_log(self) -> str:
        path = (
            self.root
            / "runtime"
            / "logs"
            / dependent_propagation.DEPENDENT_PROPAGATION_LOG_FILENAME
        )
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_a_stalled_stage_is_attributable_from_the_log(self) -> None:
        """The log must localize a stall to one stage.

        A walk whose wall-clock far exceeds its work is otherwise invisible:
        the status file keeps only the newest progress snapshot, so a phase
        that hangs leaves nothing behind. Each transition therefore reports
        how long the stage that just ended took.
        """

        clock = iter([0.0, 1.0, 16.0, 16.5, 17.0])

        def walk(*args, **kwargs):
            progress = kwargs["progress_callback"]
            progress("dfm", 0, 0, "Refreshing DFM methods")
            progress("result_selection", 0, 0, "Refreshing Result Selection methods")
            return {"ok": True}

        _path, request = self._publish_request()
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules,
                _fake_app_server(walk=walk, marking=lambda *a, **k: []),
            ),
            patch.object(dependent_propagation.time, "monotonic", lambda: next(clock)),
        ):
            dependent_propagation.execute_dependent_propagation(self.root, request)

        log = self._propagation_log()
        self.assertIn("walk start", log)
        # The 15 s belongs to the stage that ended at the second transition,
        # not to the walk as an undifferentiated total.
        self.assertIn("stage dfm took 15.00s -> result_selection", log)
        self.assertIn("walk done in", log)

    def test_the_log_keeps_failure_detail_the_client_status_redacts(self) -> None:
        def walk(*args, **kwargs):
            return {
                "ok": False,
                "skipped": [],
                "result_selection_updates": {
                    "ok": False,
                    "refreshed": [],
                    "errors": [
                        {
                            "dataset_name": "D 92 - Current Qtr Selected",
                            "reason": "[WinError 5] Access is denied",
                        }
                    ],
                },
            }

        path, request = self._publish_request()
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules, _fake_app_server(walk=walk, marking=lambda *a, **k: [])
            ),
        ):
            dependent_propagation.process_durable_dependent_propagation_request(
                self.root, path, request
            )

        log = self._propagation_log()
        self.assertIn("claimed after", log)
        self.assertIn("D 92 - Current Qtr Selected", log)
        self.assertIn("WinError 5", log)
        self.assertIn("error after", log)

    def test_a_missed_claim_says_the_class_was_busy(self) -> None:
        path, request = self._publish_request()
        with (
            patch.object(
                dependent_propagation, "acquire_reserving_class_lease", return_value=None
            ),
            patch.object(dependent_propagation, "execute_dependent_propagation") as walk,
        ):
            completed = dependent_propagation.process_durable_dependent_propagation_request(
                self.root, path, request
            )
        self.assertFalse(completed)
        walk.assert_not_called()
        # Without this line a contended class is indistinguishable from a slow
        # walk: both show up only as wall-clock time in the client.
        self.assertIn("claim missed (class busy)", self._propagation_log())

    def test_logging_failure_never_breaks_a_walk(self) -> None:
        # A log is a diary, never a dependency: an unwritable log directory
        # must not turn a healthy propagation into a failed one.
        blocker = self.root / "runtime"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("not a directory", encoding="utf-8")

        _path, request = self._publish_request()
        with (
            patch.object(dependent_propagation, "configure_canonical_runtime"),
            patch.dict(
                sys.modules,
                _fake_app_server(
                    walk=lambda *a, **k: {"ok": True}, marking=lambda *a, **k: []
                ),
            ),
        ):
            result = dependent_propagation.execute_dependent_propagation(
                self.root, request
            )
        self.assertTrue(result["ok"])
        self.assertEqual(self._propagation_log(), "")

    def test_request_filename_must_match_request_id(self) -> None:
        path, request = self._publish_request()
        renamed = path.with_name("other-name.json")
        path.rename(renamed)
        with patch.object(dependent_propagation, "execute_dependent_propagation") as walk:
            completed = dependent_propagation.process_durable_dependent_propagation_request(
                self.root, renamed, request
            )
        self.assertFalse(completed)
        walk.assert_not_called()
        self.assertTrue(renamed.exists())

    def test_contract_invalid_request_publishes_rejected_status_and_is_consumed(self) -> None:
        path, request = self._publish_request()
        request = {**request, "DataPath": r"E:\Arco Server\file.csv"}
        path.write_text(json.dumps(request), encoding="utf-8")
        completed = dependent_propagation.process_durable_dependent_propagation_request(
            self.root, path, request
        )
        self.assertFalse(completed)
        self.assertFalse(path.exists())
        persisted = json.loads(
            dependent_propagation_status_path(self.root, self.REQUEST_ID).read_text(
                encoding="utf-8"
            )
        )
        status = validate_dependent_propagation_status(
            persisted, expected_request_id=self.REQUEST_ID
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "rejected")

    def test_unidentifiable_request_is_dropped_so_the_rescan_cannot_loop(self) -> None:
        path = (
            self.root / "requests" / "dependent_propagation" / "requests" / "bad.json"
        )
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"Function": DEPENDENT_PROPAGATION_FUNCTION}), encoding="utf-8")
        completed = dependent_propagation.process_durable_dependent_propagation_request(
            self.root, path, {"Function": DEPENDENT_PROPAGATION_FUNCTION}
        )
        self.assertFalse(completed)
        self.assertFalse(path.exists())

    def test_request_is_retained_until_a_validated_terminal_status_exists(self) -> None:
        path, request = self._publish_request()

        with (
            patch.object(
                dependent_propagation,
                "execute_dependent_propagation",
                return_value={"ok": True, "steps": []},
            ),
            patch.object(
                dependent_propagation,
                "write_dependent_propagation_status",
                side_effect=PermissionError("locked"),
            ),
        ):
            completed = dependent_propagation.process_durable_dependent_propagation_request(
                self.root, path, request
            )

        self.assertFalse(completed)
        self.assertTrue(path.exists())

    def test_handler_dispatches_durable_propagation_off_the_legacy_path(self) -> None:
        handler = engine_main.RequestHandler()
        path, request = self._publish_request()
        with (
            patch.object(
                engine_main,
                "process_durable_dependent_propagation_request",
            ) as process,
            patch.object(engine_main, "get_project_root", return_value=self.root),
        ):
            handler.process_file(str(path), dispatch_duplication=False)
        process.assert_called_once()
        self.assertTrue(handler.shutdown(wait=True, timeout=2.0))

    def test_scheduled_dispatch_runs_on_the_propagation_worker_thread(self) -> None:
        handler = engine_main.RequestHandler()
        path, request = self._publish_request()
        with (
            patch.object(
                engine_main,
                "process_durable_dependent_propagation_request",
            ) as process,
            patch.object(engine_main, "get_project_root", return_value=self.root),
        ):
            handler.process_file(str(path), dispatch_duplication=True)
            handler._propagation_queue.join()
        process.assert_called_once()
        self.assertTrue(handler.shutdown(wait=True, timeout=2.0))

    def test_rescan_cycle_offers_the_propagation_queue_subfolder(self) -> None:
        path, _request = self._publish_request()
        observed: list[str] = []

        class _Recorder:
            def process_file_debug(self, file_path):
                observed.append(str(file_path))

        engine_main.process_existing_requests(self.root / "requests", _Recorder())
        self.assertEqual(observed, [str(path)])


if __name__ == "__main__":
    unittest.main()
