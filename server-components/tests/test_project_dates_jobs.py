"""The project dates job (docs/plans/project_dates_panel.md, step 4).

The app server services are stood in for; what is tested here is the job's
own order and memory: the previous dates are recorded before the new ones are
saved, every class is reshaped under its lease before it is regenerated, and a
change that stopped part way resumes from its pending record.
"""

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

from arcrho_dependent_propagation_contract import find_project_scope_propagation_hold
from arcrho_engine import main as engine_main
from arcrho_engine import project_dates_jobs, source_table_refresh
from arcrho_project_dates_job_contract import (
    PROJECT_DATES_JOB_FUNCTION,
    build_project_dates_job_request,
    project_dates_job_request_path,
    read_pending_record,
    read_project_dates_job_status,
    write_pending_record,
)


PROJECT = "Demo Project"
REQUEST_ID = "0123456789abcdef0123456789abcdef"
OLD = {"origin_start_date": "201701", "origin_end_date": "202612", "development_end_date": "202605"}
NEW = {"origin_start_date": "201701", "origin_end_date": "202612", "development_end_date": "202612"}


def _request(dates=NEW):
    return build_project_dates_job_request(
        request_id=REQUEST_ID,
        project_name=PROJECT,
        origin_start_date=dates["origin_start_date"],
        origin_end_date=dates["origin_end_date"],
        development_end_date=dates["development_end_date"],
        user_name="Test User",
    )


class _HttpError(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _Workspace:
    """The settings file and the calls the job makes, in order."""

    def __init__(self, root: Path, dates: dict):
        self.root = root
        self.dates = dict(dates)
        self.calls: list = []
        self.save_error: Exception | None = None

    def get_general_settings(self, project_name):
        return {"data": dict(self.dates)}

    def update_general_settings(self, project_name, **dates):
        # The previous dates must already be on disk when the new ones land.
        pending = read_pending_record(self.root, PROJECT)
        self.calls.append(("save", dict(dates), pending and pending["previous_dates"]))
        if self.save_error is not None:
            raise self.save_error
        self.dates = dict(dates)
        return {"ok": True}


def _install_fake_app_server(workspace: _Workspace):
    @contextmanager
    def acting_identity(login_name, display_name=""):
        yield {"login_name": login_name}

    settings = SimpleNamespace(
        get_general_settings=workspace.get_general_settings,
        update_general_settings=workspace.update_general_settings,
    )
    runtime = SimpleNamespace(clear_arcrho_headers_cache=lambda project: workspace.calls.append(("headers",)))
    services = types.ModuleType("app_server.services")
    services.project_settings_service = settings
    services.arcrho_runtime_service = runtime
    services.user_identity_service = SimpleNamespace(acting_identity=acting_identity)
    app_server = types.ModuleType("app_server")
    app_server.services = services
    return patch.dict(sys.modules, {"app_server": app_server, "app_server.services": services})


class ExecuteProjectDatesChangeTests(unittest.TestCase):
    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for target in (
            patch.object(project_dates_jobs, "configure_canonical_runtime"),
            patch.object(source_table_refresh, "_reserving_class_paths", return_value=["A\\One", "A\\Two"]),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.workspace = _Workspace(self.root, OLD)
        fake = _install_fake_app_server(self.workspace)
        fake.start()
        self.addCleanup(fake.stop)
        self.failing_class = ""
        self.problem_classes: set = set()

        def refresh_one(root, project, reserving_class, result, *, on_dataset, prepare=None, dataset_types=None):
            if reserving_class == self.failing_class:
                raise RuntimeError("the Arco Engine did not answer")
            roots = prepare()
            if reserving_class in self.problem_classes:
                result["datasets_failed"] += 1
                result["failures"].append(f"{reserving_class}: F 42 - BF Paid: snapshot mismatch")
            self.workspace.calls.append(("class", reserving_class, roots))
            result["datasets_regenerated"] += 2

        self.reshaped: list = []

        def reshape_class(project, reserving_class, previous, dates, result, *, inputs_done, mark_input_done):
            self.reshaped.append((reserving_class, dict(previous), dict(dates), set(inputs_done)))
            key = f"{reserving_class.casefold()}|c 82"
            if key not in inputs_done:
                mark_input_done(key)
                result["datasets_reshaped"] += 1
            return ["C 82"]

        for target in (
            patch.object(source_table_refresh, "_refresh_one_reserving_class", side_effect=refresh_one),
            patch.object(project_dates_jobs, "_reshape_class", side_effect=reshape_class),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _run(self, dates=NEW, recorded=None):
        return project_dates_jobs.execute_project_dates_change(
            self.root,
            _request(dates),
            record_previous_dates=(recorded.append if recorded is not None else None),
        )

    def test_the_dates_are_saved_after_the_previous_ones_are_recorded_then_every_class_moves(self) -> None:
        recorded: list = []
        result = self._run(recorded=recorded)

        self.assertEqual(recorded, [OLD])
        self.assertEqual(
            self.workspace.calls,
            [
                ("save", NEW, OLD),
                ("headers",),
                ("class", "A\\One", ["C 82"]),
                ("class", "A\\Two", ["C 82"]),
            ],
        )
        self.assertEqual(result["previous_dates"], OLD)
        self.assertEqual(result["classes_refreshed"], 2)
        self.assertEqual(result["datasets_reshaped"], 2)
        self.assertEqual([item[1] for item in self.reshaped], [OLD, OLD])
        # Finished, so nothing is left to resume.
        self.assertIsNone(read_pending_record(self.root, PROJECT))

    def test_unchanged_dates_touch_nothing(self) -> None:
        self.workspace.dates = dict(NEW)
        result = self._run()
        self.assertTrue(result["unchanged"])
        self.assertEqual(self.workspace.calls, [])
        self.assertIsNone(read_pending_record(self.root, PROJECT))

    def test_a_stopped_change_resumes_from_the_class_it_did_not_finish(self) -> None:
        self.failing_class = "A\\Two"
        first = self._run()
        self.assertEqual(first["classes_refreshed"], 1)
        self.assertIn("A\\Two: the Arco Engine did not answer", first["failures"])
        self.assertIn("Run the same change again", project_dates_jobs.summarize_failures(first))
        pending = read_pending_record(self.root, PROJECT)
        self.assertEqual(pending["previous_dates"], OLD)
        self.assertEqual(pending["classes_done"], ["A\\One"])

        # The dates are already the new ones; the pending record still knows
        # what the project was moved from, and only the second class is left.
        self.failing_class = ""
        self.workspace.calls.clear()
        second = self._run()
        self.assertTrue(second["resumed"])
        self.assertEqual(second["previous_dates"], OLD)
        self.assertEqual(self.workspace.calls, [("headers",), ("class", "A\\Two", ["C 82"])])
        self.assertEqual(self.reshaped[-1][1], OLD)
        self.assertIsNone(read_pending_record(self.root, PROJECT))

    def test_a_class_with_problems_is_walked_once_more_when_the_change_runs_again(self) -> None:
        self.problem_classes = {"A\Two"}
        first = self._run()
        self.assertEqual(first["classes_refreshed"], 2)
        self.assertTrue(first["rerun_needed"])
        self.assertIn("Run the same change again", project_dates_jobs.summarize_failures(first))
        pending = read_pending_record(self.root, PROJECT)
        self.assertEqual(pending["classes_done"], ["A\One"])
        self.assertEqual(pending["classes_retried"], ["A\Two"])

        # The preview and the panel see an unfinished change, not "unchanged".
        self.workspace.calls.clear()
        self.problem_classes = set()
        second = self._run()
        self.assertTrue(second["resumed"])
        self.assertFalse(second["rerun_needed"])
        self.assertEqual(self.workspace.calls, [("headers",), ("class", "A\Two", ["C 82"])])
        # Nothing reshaped twice: the dataset moved on the first walk is skipped.
        self.assertEqual(second["datasets_reshaped"], 0)
        self.assertIsNone(read_pending_record(self.root, PROJECT))

    def test_a_problem_that_survives_the_second_walk_does_not_hold_the_change(self) -> None:
        self.problem_classes = {"A\Two"}
        self._run()
        second = self._run()
        self.assertFalse(second["rerun_needed"])
        self.assertIsNone(read_pending_record(self.root, PROJECT))
        message = project_dates_jobs.summarize_failures(second)
        self.assertNotIn("Run the same change again", message)
        self.assertIn("review them in the list", message)

    def test_a_resumed_class_never_moves_a_dataset_twice(self) -> None:
        write_pending_record(
            self.root,
            project_name=PROJECT,
            request_id=REQUEST_ID,
            previous_dates=OLD,
            dates=NEW,
            inputs_done=["a\\two|c 82"],
        )
        self.workspace.dates = dict(NEW)
        result = self._run()
        self.assertEqual(result["datasets_reshaped"], 1)
        self.assertEqual(self.reshaped[1][3], {"a\\one|c 82", "a\\two|c 82"})

    def test_other_dates_are_refused_while_a_change_is_unfinished(self) -> None:
        write_pending_record(
            self.root, project_name=PROJECT, request_id=REQUEST_ID, previous_dates=OLD, dates=NEW
        )
        other = {**NEW, "development_end_date": "202701", "origin_end_date": "202701"}
        with self.assertRaises(project_dates_jobs.ProjectDatesJobRefused) as caught:
            self._run(other)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.workspace.calls, [])

    def test_a_refused_save_keeps_its_code_and_leaves_nothing_pending(self) -> None:
        self.workspace.save_error = _HttpError(423, "General settings file is locked.")
        with self.assertRaises(project_dates_jobs.ProjectDatesJobRefused) as caught:
            self._run()
        self.assertEqual(caught.exception.status_code, 423)
        self.assertIsNone(read_pending_record(self.root, PROJECT))


class GridTextTests(unittest.TestCase):
    def test_cells_round_trip_as_written_and_a_blank_row_stays_an_origin(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(TESTS_DIR / "logs" / "tmp")) as temp:
            path = Path(temp) / "grid.csv"
            path.write_text("0.1000000000000000055511,\n\n3,4\n", encoding="utf-8")
            grid = project_dates_jobs._read_grid(str(path))
        self.assertEqual(grid, [["0.1000000000000000055511", None], [], ["3", "4"]])
        self.assertEqual(
            project_dates_jobs._grid_text([["0.1000000000000000055511", None], [None], ["3", "4"]]),
            "0.1000000000000000055511,\n\n3,4\n",
        )


class DurableProjectDatesJobTests(unittest.TestCase):
    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.request = _request()
        self.request_path = project_dates_job_request_path(self.root, REQUEST_ID)
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")

    def _process(self, execute):
        with patch.object(project_dates_jobs, "execute_project_dates_change", execute):
            return project_dates_jobs.process_durable_project_dates_request(
                self.root, self.request_path, self.request
            )

    def test_the_status_names_the_previous_dates_and_the_result(self) -> None:
        holds: list = []

        def execute(root, request, *, progress_callback=None, record_previous_dates=None):
            holds.append(find_project_scope_propagation_hold(root, PROJECT))
            record_previous_dates(OLD)
            progress_callback(project_dates_jobs._progress("classes", 1, 2, "Reshaping A\\One (1 of 2)"))
            return {"classes_total": 2, "classes_refreshed": 2, "failures": [], "review": []}

        self.assertTrue(self._process(execute))
        self.assertEqual(holds, [{"reason": "project"}])
        self.assertIsNone(find_project_scope_propagation_hold(self.root, PROJECT))
        status = read_project_dates_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["previous_dates"], OLD)
        self.assertEqual(status["result"]["classes_refreshed"], 2)
        self.assertEqual(status["progress"]["stage"], "complete")
        self.assertFalse(self.request_path.exists())

    def test_a_refusal_is_terminal_error_with_its_status_code(self) -> None:
        def execute(root, request, *, progress_callback=None, record_previous_dates=None):
            raise project_dates_jobs.ProjectDatesJobRefused(409, "An earlier change has not finished.")

        self.assertFalse(self._process(execute))
        status = read_project_dates_job_status(self.root, REQUEST_ID)
        self.assertEqual((status["status"], status["status_code"]), ("error", 409))
        self.assertNotIn("previous_dates", status)

    def test_dates_that_break_the_rule_are_rejected_without_a_lease(self) -> None:
        broken = {**self.request, "OriginEndDate": "202701"}
        execute = Mock()
        with patch.object(project_dates_jobs, "execute_project_dates_change", execute):
            self.assertFalse(
                project_dates_jobs.process_durable_project_dates_request(self.root, self.request_path, broken)
            )
        execute.assert_not_called()
        status = read_project_dates_job_status(self.root, REQUEST_ID)
        self.assertEqual(status["status_code"], 400)
        self.assertIn("Origin End Date must not be after Development End Date", status["message"])


class EngineDispatchTests(unittest.TestCase):
    def test_the_engine_routes_the_function_to_the_dates_worker(self) -> None:
        handler = engine_main.RequestHandler()
        self.addCleanup(handler.shutdown, wait=False)
        request = {"Function": PROJECT_DATES_JOB_FUNCTION, "RequestId": REQUEST_ID}
        with patch.object(handler, "_schedule_project_dates") as scheduled:
            with patch.object(engine_main, "read_json", return_value=request):
                handler.process_file("queued.json", dispatch_duplication=True)
        scheduled.assert_called_once()

    def test_the_offline_rescan_covers_the_dates_queue(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(TESTS_DIR / "logs" / "tmp")) as temp:
            request_dir = Path(temp) / "requests"
            queue = request_dir / "project_dates" / "requests"
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
