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

from arcrho_dataset_types_change_contract import (
    DATASET_TYPES_CHANGE_FUNCTION,
    build_dataset_types_change_request,
    dataset_types_change_request_path,
    read_dataset_types_change_status,
    write_dataset_types_change_status,
)
from arcrho_dependent_propagation_contract import (
    acquire_project_scope_lease,
    acquire_reserving_class_lease,
    find_reserving_class_propagation_hold,
    release_project_scope_lease,
    release_reserving_class_lease,
)
from arcrho_engine import dataset_types_change
from arcrho_engine import main as engine_main


PROJECT = "Demo Project"
ROWS = [
    ["Paid", "Triangle", "A Loss", False, ""],
    ["Paid Ultimate", "Vector", "A Loss", True, '"Paid" * 2'],
]
CLASS_A = "HPPREF\\NJ"
CLASS_B = "PRNJ\\PA"


def _affected(reserving_class, instances=1, adopting=0, renaming=0, reason=""):
    return {
        "project": PROJECT,
        "reserving_class": reserving_class,
        "instances": instances,
        "adopting": adopting,
        "renaming": renaming,
        "reason": reason,
    }


PLAN = {"table_digest": "sha256:table", "affected": [_affected(CLASS_A, 3), _affected(CLASS_B, 1)]}


class _Instance(SimpleNamespace):
    pass


def _planned(plan, *, rows=None, changed_types=(), removed_types=(), class_count=5):
    """The planner's answer, shaped like ``DatasetTypesChangePlan``."""

    classes = [
        SimpleNamespace(
            reserving_class=entry["reserving_class"],
            instances=[
                _Instance(name=f"Dataset {index}", dataset_type="Paid", method_type="None",
                          new_dataset_type="Paid", rename_to="")
                for index in range(entry["instances"])
            ],
            reason=entry["reason"],
        )
        for entry in plan["affected"]
    ]
    return SimpleNamespace(
        plan=plan,
        rows=list(rows if rows is not None else ROWS),
        renames=[],
        rename_map={},
        changed_types=list(changed_types),
        removed_types=list(removed_types),
        classes=classes,
        class_count=class_count,
    )


def _identity_stub(bound: list):
    """Stand in for the canonical acting-identity binding."""

    @contextmanager
    def acting_identity(login_name, display_name=""):
        bound.append(str(login_name or "").strip())
        try:
            yield {"login_name": login_name, "display_name": display_name}
        finally:
            bound.pop()

    return SimpleNamespace(acting_identity=acting_identity)


def _install_fake_app_server(modules: dict, audit_calls: list):
    """Register a minimal ``app_server`` package for the lazy service imports."""

    services = types.ModuleType("app_server.services")
    for name, module in modules.items():
        setattr(services, name, module)
    audit = types.ModuleType("app_server.services.audit_service")
    audit.safe_append_project_audit_log = lambda **kwargs: audit_calls.append(kwargs)
    services.audit_service = audit
    app_server = types.ModuleType("app_server")
    app_server.services = services
    return patch.dict(
        sys.modules,
        {
            "app_server": app_server,
            "app_server.services": services,
            "app_server.services.audit_service": audit,
        },
    )


class ExecuteDatasetTypesChangeTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.request = build_dataset_types_change_request(
            request_id=self.REQUEST_ID,
            project_name=PROJECT,
            rows=ROWS,
            renames=[],
            changed_types=["Paid Ultimate"],
            plan=PLAN,
            user_name="Test User",
        )
        self.identities: list[str] = []
        self.audit_calls: list[dict] = []
        self.applied: list[tuple] = []
        self.refreshed: list[tuple] = []
        self.blocker_calls: list[tuple] = []
        self.narrowed: list[list[str]] = []
        self.planner_calls: list[tuple] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _services(self, refresh_result=None, blockers=None, planned=None):
        dataset_types_service = SimpleNamespace(
            apply_dataset_types_rows=lambda project, rows: (
                self.applied.append((project, rows, list(self.identities)))
                or {"path": "table.json", "xlsx_path": "table.xlsx", "rows": rows, "count": len(rows)}
            ),
        )
        answer = planned if planned is not None else _planned(PLAN, changed_types=["Paid Ultimate"])

        def plan(project, rows, renames, on_progress=None):
            self.planner_calls.append((project, rows, renames))
            if on_progress:
                on_progress(1, 5, "HPPREF")
            return answer

        dataset_types_plan_service = SimpleNamespace(plan_dataset_types_change=plan)
        calculated_dataset_service = SimpleNamespace(
            find_dataset_type_removal_blockers=lambda project, planned: (
                self.blocker_calls.append((project, list(planned.removed_types)))
                or list(blockers or [])
            ),
            apply_planned_dataset_types_change=lambda project, planned, on_progress=None: (
                self.refreshed.append((project, planned.changed_types, list(self.identities)))
                or (on_progress and on_progress("graphs", "Rebuilding HPPREF", 6, 12))
                or (refresh_result if refresh_result is not None else {
                    "ok": True,
                    "sidecars_updated": 4,
                    "datasets_renamed": 1,
                    "datasets_total": 12,
                    "classes_total": 5,
                    "chains": [],
                    "errors": [],
                })
            ),
        )
        return {
            "dataset_types_service": dataset_types_service,
            "dataset_types_plan_service": dataset_types_plan_service,
            "calculated_dataset_service": calculated_dataset_service,
            "user_identity_service": _identity_stub(self.identities),
        }

    def _execute(self, refresh_result=None, progress=None, blockers=None, planned=None):
        services = self._services(refresh_result, blockers=blockers, planned=planned)
        with _install_fake_app_server(services, self.audit_calls):
            with patch.object(dataset_types_change, "configure_canonical_runtime"):
                return dataset_types_change.execute_dataset_types_change(
                    self.root,
                    self.request,
                    progress_callback=(progress.append if progress is not None else None),
                    narrow_lease=self.narrowed.append,
                )

    def test_the_table_is_written_and_the_graphs_rebuilt_as_the_saving_user(self) -> None:
        result = self._execute()
        self.assertEqual(self.planner_calls, [(PROJECT, ROWS, [])])
        self.assertEqual(self.applied[0][0], PROJECT)
        self.assertEqual(self.applied[0][1], ROWS)
        # Both canonical steps run bound to the person who asked for the change.
        self.assertEqual(self.applied[0][2], ["Test User"])
        self.assertEqual(self.refreshed[0][1], ["Paid Ultimate"])
        self.assertEqual(self.refreshed[0][2], ["Test User"])
        # The whole project is let go once the table is the new one.
        self.assertEqual(self.narrowed, [[CLASS_A, CLASS_B]])
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["types_changed"], 1)
        self.assertEqual(result["datasets_updated"], 4)
        self.assertEqual(result["datasets_renamed"], 1)
        self.assertEqual(result["datasets_total"], 12)
        self.assertEqual(result["classes_total"], 5)
        self.assertEqual(result["classes_affected"], 2)
        self.assertEqual(result["failures"], [])
        self.assertEqual(
            self.audit_calls,
            [{"project_name": PROJECT, "action": "Saved Dataset Types (2 rows)"}],
        )

    def test_the_table_written_is_the_planners_rewritten_one(self) -> None:
        rewritten = [ROWS[0], ["Paid Ultimate", "Vector", "A Loss", True, '"Paid" * 3']]
        self._execute(planned=_planned(PLAN, rows=rewritten))
        self.assertEqual(self.applied[0][1], rewritten)

    def test_a_plan_that_no_longer_matches_stops_the_change(self) -> None:
        wider = {"table_digest": PLAN["table_digest"], "affected": PLAN["affected"] + [_affected("New\\Class")]}
        with self.assertRaises(dataset_types_change.DatasetTypesChangeJobError) as raised:
            self._execute(planned=_planned(wider))
        self.assertEqual(str(raised.exception), dataset_types_change.PLAN_CHANGED_MESSAGE)
        self.assertEqual(self.applied, [])
        self.assertEqual(self.narrowed, [])

        moved_table = {"table_digest": "sha256:other", "affected": PLAN["affected"]}
        with self.assertRaises(dataset_types_change.DatasetTypesChangeJobError):
            self._execute(planned=_planned(moved_table))
        self.assertEqual(self.applied, [])

    def test_progress_reaches_the_publisher_with_countable_units(self) -> None:
        progress: list[dict] = []
        self._execute(progress=progress)
        labels = [item["label"] for item in progress]
        self.assertIn("Checking reserving classes: HPPREF", labels)
        self.assertIn("Writing the dataset type table", labels)
        self.assertIn("Rebuilding HPPREF", labels)
        self.assertEqual(labels[-1], "Dataset type change complete")

        # The rebuild's own count is offset past the table's unit, so the bar
        # only ever moves forward.
        rebuild = next(item for item in progress if item["label"] == "Rebuilding HPPREF")
        self.assertEqual((rebuild["completed"], rebuild["total"]), (7, 13))
        final = progress[-1]
        self.assertEqual(final["completed"], final["total"])
        self.assertGreater(final["total"], 1)
        table_at = labels.index("Writing the dataset type table")
        for earlier, later in zip(progress[table_at:], progress[table_at + 1:]):
            self.assertGreaterEqual(later["completed"], earlier["completed"])

    def test_a_failed_chain_is_reported_as_a_failure(self) -> None:
        result = self._execute(
            refresh_result={
                "ok": False,
                "sidecars_updated": 1,
                "datasets_total": 8,
                "classes_total": 2,
                "chains": [
                    {"ok": False, "reserving_class": "HPPREF\\NJ", "updated": []},
                    {"ok": True, "reserving_class": "PRNJ\\PA", "updated": [{"ok": True}]},
                ],
                "errors": ["PRNJ\\PA index rebuild: disk full"],
            }
        )
        self.assertEqual(result["classes_total"], 2)
        self.assertEqual(result["classes_walked"], 1)
        self.assertEqual(result["datasets_total"], 8)
        self.assertEqual(result["datasets_recalculated"], 1)
        self.assertIn("PRNJ\\PA index rebuild: disk full", result["failures"])
        self.assertTrue(
            any("HPPREF\\NJ" in failure for failure in result["failures"])
        )

    def test_a_failed_chain_names_why_its_propagation_declined(self) -> None:
        result = self._execute(
            refresh_result={
                "ok": False,
                "sidecars_updated": 1,
                "datasets_total": 8,
                "classes_total": 1,
                "chains": [
                    {
                        "ok": False,
                        "reserving_class": "HPPREF\\NJ",
                        "updated": [],
                        "propagation": {
                            "ok": False,
                            "message": "another dependent propagation is still running.",
                        },
                    },
                ],
                "errors": [],
            }
        )
        self.assertEqual(
            result["failures"],
            [
                "HPPREF\\NJ: dependent propagation: another dependent propagation "
                "is still running."
            ],
        )

    def test_a_removed_type_still_read_downstream_stops_the_change(self) -> None:
        # The planner found "Growth Adjustment - Counts" leaving the table.
        planned = _planned(PLAN, removed_types=["Growth Adjustment - Counts"])
        blockers = [
            {
                "dataset_type": "Growth Adjustment - Counts",
                "instances": [
                    {
                        "reserving_class": "HPPREF\\NJ",
                        "dataset_name": "Growth Adjustment - Counts",
                        "dependents": [
                            {"dataset_name": "Selected Ultimate", "method_type": "DFM"}
                        ],
                    }
                ],
            }
        ]
        with self.assertRaises(dataset_types_change.DatasetTypesChangeJobError) as raised:
            self._execute(blockers=blockers, planned=planned)
        message = str(raised.exception)
        self.assertIn("Growth Adjustment - Counts", message)
        self.assertIn("Selected Ultimate (DFM)", message)
        self.assertIn("Nothing was saved.", message)
        # The refusal happens before the table is touched.
        self.assertEqual(self.applied, [])
        self.assertEqual(self.blocker_calls, [(PROJECT, ["Growth Adjustment - Counts"])])

    def test_a_change_that_removes_nothing_never_scans_for_readers(self) -> None:
        self._execute()
        self.assertEqual(self.blocker_calls, [])

    def test_a_removed_type_nothing_reads_is_applied(self) -> None:
        planned = _planned(PLAN, removed_types=["Growth Adjustment - Counts"])
        result = self._execute(blockers=[], planned=planned)
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(self.blocker_calls, [(PROJECT, ["Growth Adjustment - Counts"])])

    def test_a_class_still_being_walked_stops_the_change(self) -> None:
        lease = acquire_reserving_class_lease(self.root, PROJECT, "HPPREF\\NJ")
        self.addCleanup(release_reserving_class_lease, lease)
        with patch.object(
            dataset_types_change, "RESERVING_CLASS_QUIET_WAIT_SECONDS", 0.0
        ):
            with self.assertRaises(dataset_types_change.DatasetTypesChangeJobError):
                self._execute()
        # Nothing was written: the table is only changed once the project is
        # quiet enough for the rebuild that follows it.
        self.assertEqual(self.applied, [])


class DurableDatasetTypesChangeTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.request = build_dataset_types_change_request(
            request_id=self.REQUEST_ID,
            project_name=PROJECT,
            rows=ROWS,
            renames=[],
            changed_types=[],
            plan=PLAN,
            user_name="Test User",
        )
        self.request_path = dataset_types_change_request_path(self.root, self.REQUEST_ID)
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _process(self, execute):
        with patch.object(dataset_types_change, "execute_dataset_types_change", execute):
            return dataset_types_change.process_durable_dataset_types_change_request(
                self.root, self.request_path, self.request
            )

    def test_the_running_job_holds_the_project_then_only_the_planned_classes(self) -> None:
        observed: list = []

        def execute(root, request, *, progress_callback=None, narrow_lease=None):
            observed.append(find_reserving_class_propagation_hold(root, PROJECT, CLASS_A))
            observed.append(find_reserving_class_propagation_hold(root, PROJECT, CLASS_B))
            observed.append(
                find_reserving_class_propagation_hold(root, "Other Project", CLASS_A)
            )
            narrow_lease([CLASS_A])
            observed.append(find_reserving_class_propagation_hold(root, PROJECT, CLASS_A))
            observed.append(find_reserving_class_propagation_hold(root, PROJECT, CLASS_B))
            return dataset_types_change._empty_result()

        self.assertTrue(self._process(execute))
        # Every class of the project, and no other project's, until the table
        # is written; then only the classes the plan named.
        self.assertEqual(observed[:3], [{"reason": "project"}, {"reason": "project"}, None])
        self.assertEqual(observed[3:], [{"reason": "project"}, None])
        # And the hold is released when the job ends.
        self.assertIsNone(find_reserving_class_propagation_hold(self.root, PROJECT, CLASS_A))

    def test_a_completed_job_publishes_success_and_drops_its_queue_file(self) -> None:
        result = dataset_types_change._empty_result()
        result.update({"rows_written": 2, "datasets_updated": 9, "datasets_total": 20})

        def execute(root, request, *, progress_callback=None, narrow_lease=None):
            progress_callback(
                dataset_types_change._progress("graphs", 1, 2, "Rebuilding graphs")
            )
            return result

        self.assertTrue(self._process(execute))
        status = read_dataset_types_change_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["result"]["datasets_updated"], 9)
        self.assertFalse(self.request_path.exists())

    def test_reported_failures_make_the_job_terminal_error(self) -> None:
        result = dataset_types_change._empty_result()
        result.update({"rows_written": 2, "failures": ["HPPREF\\NJ: the dependent refresh reported errors."]})

        self.assertFalse(self._process(lambda *a, **k: result))
        status = read_dataset_types_change_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        # The table did land; the message must not read as if nothing happened.
        self.assertIn("was saved", status["message"])

    def test_a_raised_job_publishes_a_redacted_error(self) -> None:
        def explode(*args, **kwargs):
            raise OSError(r"E:\Arco Server\projects\Demo\dataset_types.json")

        self.assertFalse(self._process(explode))
        status = read_dataset_types_change_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertNotIn("dataset_types.json", status["message"])
        self.assertNotIn("projects", status["message"])

    def test_a_held_project_is_not_claimed_and_leaves_the_request_queued(self) -> None:
        lease = acquire_project_scope_lease(self.root, PROJECT)
        self.addCleanup(release_project_scope_lease, lease)
        called: list = []
        self.assertFalse(self._process(lambda *a, **k: called.append(1)))
        self.assertEqual(called, [])
        self.assertTrue(self.request_path.exists())

    def test_an_already_terminal_request_is_dropped_without_rerunning(self) -> None:
        write_dataset_types_change_status(
            self.root,
            self.REQUEST_ID,
            "success",
            progress={"stage": "complete", "completed": 1, "total": 1, "label": "Done"},
        )
        called: list = []
        self.assertTrue(self._process(lambda *a, **k: called.append(1)))
        self.assertEqual(called, [])
        self.assertFalse(self.request_path.exists())

    def test_a_rejected_payload_publishes_an_error_and_drops_the_file(self) -> None:
        broken = {**self.request, "Rows": [["only", "three", "cells"]]}
        with patch.object(dataset_types_change, "execute_dataset_types_change") as execute:
            handled = dataset_types_change.process_durable_dataset_types_change_request(
                self.root, self.request_path, broken
            )
        self.assertFalse(handled)
        execute.assert_not_called()
        status = read_dataset_types_change_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertFalse(self.request_path.exists())


class EngineDispatchTests(unittest.TestCase):
    def test_the_engine_routes_the_function_to_the_change_worker(self) -> None:
        handler = engine_main.RequestHandler()
        self.addCleanup(handler.shutdown, wait=False)
        request = {
            "Function": DATASET_TYPES_CHANGE_FUNCTION,
            "RequestId": "0123456789abcdef0123456789abcdef",
        }
        with patch.object(handler, "_schedule_dataset_types_change") as scheduled:
            handler.process_file = types.MethodType(
                engine_main.RequestHandler.process_file, handler
            )
            with patch.object(engine_main, "read_json", return_value=request):
                handler.process_file("queued.json", dispatch_duplication=True)
        scheduled.assert_called_once()


if __name__ == "__main__":
    unittest.main()
