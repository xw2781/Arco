from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_COMPONENTS_SRC = REPO_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPO_ROOT / "python-api" / "src"
TESTS_DIR = Path(__file__).resolve().parent
for path in (SERVER_COMPONENTS_SRC, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api.dataset_type_contract import generated_formula_refresh_names
from arcrho_data_processing_rules_job_contract import (
    DATA_PROCESSING_RULES_JOB_FUNCTION,
    build_data_processing_rules_job_request,
    data_processing_rules_job_request_path,
    read_data_processing_rules_job_status,
)
from arcrho_dependent_propagation_contract import find_project_scope_propagation_hold
from arcrho_engine import data_processing_rules_jobs
from arcrho_engine import main as engine_main


PROJECT = "Demo Project"
REQUEST_ID = "0123456789abcdef0123456789abcdef"
RULES = [{"id": "rule-1", "name": "Keep BI", "target": {"source_measure": "Paid"}}]
# The Engine builds "Paid to Incurred" from the two types the save affects, so
# the refresh has to rebuild it too even though the save never names it.
DATASET_TYPE_ROWS = [
    {"name": "Paid", "calculated": False, "generated": True, "formula": ""},
    {"name": "Incurred", "calculated": False, "generated": True, "formula": ""},
    {
        "name": "Paid to Incurred",
        "calculated": True,
        "generated": True,
        "formula": '"Paid" / "Incurred"',
    },
]


def _request():
    return build_data_processing_rules_job_request(
        request_id=REQUEST_ID,
        project_name=PROJECT,
        expected_revision=3,
        rules=RULES,
        user_name="Test User",
    )


class _RevisionConflict(RuntimeError):
    pass


class _WriteLocked(RuntimeError):
    pass


class _ValidationError(RuntimeError):
    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


class _ValuesLocked(RuntimeError):
    pass


def _install_fake_app_server(save, bound: list):
    """Register a minimal ``app_server.services`` for the job's lazy imports."""

    @contextmanager
    def acting_identity(login_name, display_name=""):
        bound.append(str(login_name or "").strip())
        try:
            yield {"login_name": login_name, "display_name": display_name}
        finally:
            bound.pop()

    rules = types.ModuleType("app_server.services.data_processing_rules_service")
    rules.save_data_processing_rules = save
    rules.RulesRevisionConflictError = _RevisionConflict
    rules.RulesWriteLockedError = _WriteLocked
    rules.RulesValidationError = _ValidationError
    values = types.ModuleType("app_server.services.data_processing_values_service")
    values.DataProcessingValuesLockedError = _ValuesLocked
    identity = SimpleNamespace(acting_identity=acting_identity)
    # Only the table read is stood in for: which types a formula reaches is
    # decided by the canonical rule the app server's service calls.
    calculated = SimpleNamespace(
        generated_formula_refresh_types=lambda project, names: (
            generated_formula_refresh_names(DATASET_TYPE_ROWS, names)
        )
    )
    services = types.ModuleType("app_server.services")
    services.calculated_dataset_service = calculated
    services.data_processing_rules_service = rules
    services.data_processing_values_service = values
    services.user_identity_service = identity
    app_server = types.ModuleType("app_server")
    app_server.services = services
    return patch.dict(
        sys.modules,
        {
            "app_server": app_server,
            "app_server.services": services,
            "app_server.services.data_processing_rules_service": rules,
            "app_server.services.data_processing_values_service": values,
        },
    )


class ExecuteDataProcessingRulesSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=str(TESTS_DIR / "logs" / "tmp"))
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.runtime = patch.object(data_processing_rules_jobs, "configure_canonical_runtime")
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def test_the_save_runs_as_the_submitting_user_and_reports_its_stages(self) -> None:
        bound: list = []
        calls: list = []

        def save(project_name, *, expected_revision, data, progress):
            calls.append((project_name, expected_revision, data, list(bound)))
            progress("validating", 0, 0, "Validating the rules")
            progress("checking", 2, 9, "Checking generated datasets (3 of 9)")
            return {"ok": True, "data": {"revision": expected_revision + 1}}

        seen: list = []
        with _install_fake_app_server(save, bound):
            response = data_processing_rules_jobs.execute_data_processing_rules_save(
                self.root, _request(), progress_callback=seen.append
            )
        self.assertEqual(response["data"]["revision"], 4)
        self.assertEqual(calls, [(PROJECT, 3, {"rules": RULES}, ["Test User"])])
        self.assertEqual(
            seen,
            [
                {"stage": "validating", "completed": 0, "total": 0, "label": "Validating the rules"},
                {"stage": "checking", "completed": 2, "total": 9, "label": "Checking generated datasets (3 of 9)"},
            ],
        )

    def test_service_refusals_keep_the_direct_route_status_codes(self) -> None:
        cases = [
            (_RevisionConflict("moved"), 409, "moved"),
            (_WriteLocked("locked"), 423, "locked"),
            (_ValuesLocked("values"), 423, "values"),
            (_ValidationError(["bad rule", "worse rule"]), 400, "bad rule; worse rule"),
            (ValueError("Project folder not found under projects: x"), 404, "Project folder"),
            (ValueError("nope"), 400, "nope"),
        ]
        for error, code, text in cases:
            with self.subTest(error=error):
                def save(*_args, **_kwargs):
                    raise error

                with _install_fake_app_server(save, []):
                    with self.assertRaises(data_processing_rules_jobs.DataProcessingRulesJobRefused) as raised:
                        data_processing_rules_jobs.execute_data_processing_rules_save(self.root, _request())
                self.assertEqual(raised.exception.status_code, code)
                self.assertIn(text, str(raised.exception))

    def _saved(self, *, changed=True, affected_types=("Paid", "Incurred")):
        def save(project_name, *, expected_revision, data, progress):
            progress("checking", 3, 3, "Checked 3 generated dataset(s)")
            return {
                "ok": True,
                "changed": changed,
                "data": {"revision": expected_revision + 1},
                "impact": {"affected_dataset_types": list(affected_types)},
            }

        return save

    def _refresh_stubs(self, classes, instances, refresh_one):
        from arcrho_engine import source_table_refresh

        return (
            patch.object(source_table_refresh, "_reserving_class_paths", lambda project: list(classes)),
            patch.object(
                source_table_refresh,
                "_engine_dataset_instances",
                lambda project, reserving_class, types=None: list(instances.get(reserving_class, [])),
            ),
            patch.object(source_table_refresh, "_refresh_one_reserving_class", refresh_one),
        )

    def test_a_changed_save_refreshes_the_classes_holding_affected_datasets(self) -> None:
        classes = ["A\\One", "A\\Two", "A\\Three"]
        instances = {"A\\One": ["Paid"], "A\\Three": ["Paid", "Incurred"]}
        refreshed: list = []
        narrowed: list = []
        bound: list = []

        def refresh_one(root, project, reserving_class, result, *, on_dataset, dataset_types=None):
            refreshed.append((reserving_class, list(dataset_types or []), list(bound)))
            for name in instances[reserving_class]:
                on_dataset(name)
                result["datasets_regenerated"] += 1
            result["methods_updated"] += 2

        seen: list = []
        stubs = self._refresh_stubs(classes, instances, refresh_one)
        with _install_fake_app_server(self._saved(), bound), stubs[0], stubs[1], stubs[2]:
            response = data_processing_rules_jobs.execute_data_processing_rules_save(
                self.root, _request(), progress_callback=seen.append, narrow_lease=narrowed.append
            )
        # Only the classes with an engine instance of an affected type are
        # held and refreshed, each as the submitting user.
        self.assertEqual(narrowed, [["A\\One", "A\\Three"]])
        self.assertEqual(
            refreshed,
            [
                ("A\\One", ["Paid", "Incurred", "Paid to Incurred"], ["Test User"]),
                ("A\\Three", ["Paid", "Incurred", "Paid to Incurred"], ["Test User"]),
            ],
        )
        self.assertEqual(
            response["refresh"],
            {
                "classes_total": 2,
                "classes_refreshed": 2,
                "datasets_regenerated": 3,
                "datasets_failed": 0,
                "methods_updated": 4,
                "dataset_types_expanded": ["Paid", "Incurred", "Paid to Incurred"],
                "failures": [],
            },
        )
        # The window follows the save's own stages, then each class and dataset.
        self.assertEqual(
            [(item["stage"], item["completed"], item["total"], item["label"]) for item in seen],
            [
                ("checking", 3, 3, "Checked 3 generated dataset(s)"),
                ("scanning", 0, 0, "Finding the datasets the rules affect"),
                ("classes", 0, 2, "Refreshing A\\One (1 of 2)"),
                ("classes", 0, 2, "Refreshing A\\One: Paid"),
                ("classes", 1, 2, "Refreshing A\\Three (2 of 2)"),
                ("classes", 1, 2, "Refreshing A\\Three: Paid"),
                ("classes", 1, 2, "Refreshing A\\Three: Incurred"),
                ("classes", 2, 2, "Refreshed 2 of 2 reserving class(es)"),
            ],
        )

    def test_a_save_that_did_not_change_the_rules_refreshes_nothing(self) -> None:
        for save in (self._saved(changed=False), self._saved(affected_types=())):
            with self.subTest(changed=save):
                refresh_one = Mock()
                stubs = self._refresh_stubs(["A\\One"], {"A\\One": ["Paid"]}, refresh_one)
                narrowed: list = []
                with _install_fake_app_server(save, []), stubs[0], stubs[1], stubs[2]:
                    response = data_processing_rules_jobs.execute_data_processing_rules_save(
                        self.root, _request(), narrow_lease=narrowed.append
                    )
                refresh_one.assert_not_called()
                self.assertEqual(narrowed, [])
                self.assertEqual(response["refresh"]["classes_total"], 0)

    def test_a_class_that_fails_is_named_and_the_save_still_succeeds(self) -> None:
        classes = ["A\\One", "A\\Two"]
        instances = {"A\\One": ["Paid"], "A\\Two": ["Paid"]}

        def refresh_one(root, project, reserving_class, result, *, on_dataset, dataset_types=None):
            if reserving_class == "A\\Two":
                raise RuntimeError("the Engine did not return values")
            result["datasets_regenerated"] += 1

        stubs = self._refresh_stubs(classes, instances, refresh_one)
        with _install_fake_app_server(self._saved(), []), stubs[0], stubs[1], stubs[2]:
            response = data_processing_rules_jobs.execute_data_processing_rules_save(
                self.root, _request(), narrow_lease=lambda classes: None
            )
        self.assertEqual(response["data"]["revision"], 4)
        self.assertEqual(response["refresh"]["classes_refreshed"], 1)
        self.assertEqual(
            response["refresh"]["failures"], ["A\\Two: the Engine did not return values"]
        )
        self.assertEqual(
            data_processing_rules_jobs.summarize_refresh_failures(response["refresh"]),
            "The rules were saved, but 1 reserving class(es) were not refreshed. "
            "First problem: A\\Two: the Engine did not return values",
        )
        self.assertEqual(data_processing_rules_jobs.summarize_refresh_failures({"failures": []}), "")


class DurableDataProcessingRulesJobTests(unittest.TestCase):
    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.request = _request()
        self.request_path = data_processing_rules_job_request_path(self.root, REQUEST_ID)
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")

    def _process(self, execute):
        with patch.object(data_processing_rules_jobs, "execute_data_processing_rules_save", execute):
            return data_processing_rules_jobs.process_durable_data_processing_rules_request(
                self.root, self.request_path, self.request
            )

    def test_a_completed_save_publishes_its_response_and_drops_the_queue_file(self) -> None:
        observed: list = []

        def execute(root, request, *, progress_callback=None, narrow_lease=None):
            observed.append(find_project_scope_propagation_hold(root, PROJECT))
            progress_callback(data_processing_rules_jobs._progress("checking", 1, 4, "Checking"))
            return {"ok": True, "data": {"revision": 4}, "impact": {"invalidated_count": 2}}

        self.assertTrue(self._process(execute))
        # The project is held while the save runs and released when it ends.
        self.assertEqual(observed, [{"reason": "project"}])
        self.assertIsNone(find_project_scope_propagation_hold(self.root, PROJECT))
        status = read_data_processing_rules_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["result"]["data"]["revision"], 4)
        self.assertEqual(status["progress"]["stage"], "complete")
        self.assertFalse(self.request_path.exists())

    def test_a_refresh_that_fell_short_still_succeeds_and_says_what_was_left(self) -> None:
        holds: list = []

        def execute(root, request, *, progress_callback=None, narrow_lease=None):
            narrow_lease(["A\\Two"])
            # Narrowed: a class outside the refresh is writable again while
            # the one being refreshed is still held.
            holds.append(find_project_scope_propagation_hold(root, PROJECT))
            progress_callback(data_processing_rules_jobs._progress("classes", 0, 1, "Refreshing A\\Two (1 of 1)"))
            return {
                "ok": True,
                "data": {"revision": 4},
                "refresh": {
                    "classes_total": 1,
                    "classes_refreshed": 0,
                    "datasets_regenerated": 0,
                    "datasets_failed": 1,
                    "methods_updated": 0,
                    "failures": ["A\\Two: Paid: the Arco Engine did not return values."],
                },
            }

        self.assertTrue(self._process(execute))
        self.assertEqual(holds, [{"reason": "project"}])
        status = read_data_processing_rules_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["result"]["data"]["revision"], 4)
        self.assertEqual(
            status["message"],
            "The rules were saved, but 1 dataset(s) could not be refreshed; "
            "1 reserving class(es) were not refreshed. "
            "First problem: A\\Two: Paid: the Arco Engine did not return values.",
        )
        self.assertFalse(self.request_path.exists())

    def test_a_refused_save_is_terminal_error_with_its_status_code(self) -> None:
        def execute(root, request, *, progress_callback=None, narrow_lease=None):
            raise data_processing_rules_jobs.DataProcessingRulesJobRefused(
                409, "Data processing rules revision changed from 3 to 4."
            )

        self.assertFalse(self._process(execute))
        status = read_data_processing_rules_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["status_code"], 409)
        self.assertIn("revision changed", status["message"])
        self.assertNotIn("result", status)
        self.assertFalse(self.request_path.exists())

    def test_a_malformed_request_is_rejected_without_a_lease(self) -> None:
        broken = {**self.request, "Rules": "not a list"}
        self.request_path.write_text(json.dumps(broken), encoding="utf-8")
        execute = Mock()
        with patch.object(data_processing_rules_jobs, "execute_data_processing_rules_save", execute):
            self.assertFalse(
                data_processing_rules_jobs.process_durable_data_processing_rules_request(
                    self.root, self.request_path, broken
                )
            )
        execute.assert_not_called()
        status = read_data_processing_rules_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["status_code"], 400)
        self.assertFalse(self.request_path.exists())


class EngineDispatchTests(unittest.TestCase):
    def test_the_engine_routes_the_function_to_the_rules_worker(self) -> None:
        handler = engine_main.RequestHandler()
        self.addCleanup(handler.shutdown, wait=False)
        request = {"Function": DATA_PROCESSING_RULES_JOB_FUNCTION, "RequestId": REQUEST_ID}
        with patch.object(handler, "_schedule_data_processing_rules") as scheduled:
            handler.process_file = types.MethodType(engine_main.RequestHandler.process_file, handler)
            with patch.object(engine_main, "read_json", return_value=request):
                handler.process_file("queued.json", dispatch_duplication=True)
        scheduled.assert_called_once()

    def test_the_offline_rescan_covers_the_rules_queue(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(TESTS_DIR / "logs" / "tmp")) as temp:
            request_dir = Path(temp) / "requests"
            queue = request_dir / "data_processing_rules" / "requests"
            queue.mkdir(parents=True)
            (queue / f"{REQUEST_ID}.json").write_text("{}", encoding="utf-8")
            handler = SimpleNamespace(process_file_debug=Mock())
            engine_main.process_existing_requests(request_dir, handler)
        self.assertEqual(
            [Path(call.args[0]).name for call in handler.process_file_debug.call_args_list],
            [f"{REQUEST_ID}.json"],
        )


if __name__ == "__main__":
    unittest.main()
