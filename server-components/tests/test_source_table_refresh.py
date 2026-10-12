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

from arcrho_api.dataset_index_contract import canonicalize_index_row
from arcrho_api.dataset_type_contract import generated_formula_refresh_names
from arcrho_source_refresh_contract import (
    SOURCE_REFRESH_FUNCTION,
    acquire_source_refresh_lease,
    build_source_refresh_request,
    read_source_refresh_status,
    release_source_refresh_lease,
    source_refresh_request_path,
    write_source_refresh_status,
)
from arcrho_engine import source_table_refresh
from arcrho_engine import main as engine_main


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


def _install_fake_app_server(modules: dict):
    """Register a minimal ``app_server`` package for the lazy service imports."""

    services = types.ModuleType("app_server.services")
    modules = {
        "data_processing_values_service": SimpleNamespace(
            get_data_processing_values=lambda project: {}
        ),
        **modules,
    }
    for name, module in modules.items():
        setattr(services, name, module)
    app_server = types.ModuleType("app_server")
    app_server.services = services
    return patch.dict(
        sys.modules,
        {"app_server": app_server, "app_server.services": services},
    )


class ReservingClassEnumerationTests(unittest.TestCase):
    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.data_dir = Path(self.temp.name) / "data"
        self.data_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _patched_config(self):
        config = types.ModuleType("app_server.config")
        config.get_project_data_dir = lambda name: str(self.data_dir)
        config.decode_filename_segment = lambda name: str(name).replace("_%5C_", "\\")
        app_server = types.ModuleType("app_server")
        app_server.config = config
        return patch.dict(
            sys.modules, {"app_server": app_server, "app_server.config": config}
        )

    def test_the_index_owns_the_class_name_and_the_folder_is_the_fallback(self) -> None:
        indexed = self.data_dir / "HPPREF_%5C_HO+DF"
        indexed.mkdir()
        (indexed / "index.json").write_text(
            json.dumps({"reserving_class": "HPPREF\\HO+DF", "files": []}),
            encoding="utf-8",
        )
        unindexed = self.data_dir / "Auto_%5C_NJ"
        unindexed.mkdir()

        with self._patched_config():
            classes = source_table_refresh._reserving_class_paths("Demo Project")

        self.assertEqual(sorted(classes), ["Auto\\NJ", "HPPREF\\HO+DF"])

    def test_a_project_with_no_data_folder_has_no_classes(self) -> None:
        missing = types.ModuleType("app_server.config")
        missing.get_project_data_dir = lambda name: str(self.data_dir / "absent")
        missing.decode_filename_segment = lambda name: name
        app_server = types.ModuleType("app_server")
        app_server.config = missing
        with patch.dict(
            sys.modules, {"app_server": app_server, "app_server.config": missing}
        ):
            self.assertEqual(source_table_refresh._reserving_class_paths("Demo"), [])


class EngineDatasetEnumerationTests(unittest.TestCase):
    """The job must read names from index rows as the index contract writes them.

    The rows are built through ``canonicalize_index_row`` on purpose: a
    hand-typed fixture once carried the sidecar-only ``dataset_name`` field,
    which the contract's projection drops, and the enumeration silently found
    zero datasets on every real project.
    """

    def _enumerate(self, rows, dataset_types=None):
        index_service = SimpleNamespace(
            get_index=lambda project, reserving_class: {"files": rows}
        )
        with _install_fake_app_server(
            {"dataset_instance_index_service": index_service}
        ):
            return source_table_refresh._engine_dataset_instances(
                "Demo Project", "HPPREF\\NJ", dataset_types
            )

    def test_a_dataset_type_scope_keeps_only_instances_of_those_types(self) -> None:
        rows = [
            canonicalize_index_row(
                {"name": "ALAE Paid", "dataset_type": "ALAE--Paid", "source_kind": "engine"}
            ),
            canonicalize_index_row(
                {"name": "Paid", "dataset_type": "Gross Loss--Paid", "source_kind": "engine"}
            ),
            canonicalize_index_row(
                {"name": "Paid 12", "dataset_type": "Gross Loss--Paid", "source_kind": "engine"}
            ),
            canonicalize_index_row(
                {"name": "Cutoff", "dataset_type": "Gross Loss--Paid", "source_kind": "input"}
            ),
        ]
        self.assertEqual(
            self._enumerate(rows, ["gross loss--paid"]), ["Paid", "Paid 12"]
        )
        # No scope is the whole class, exactly as before.
        self.assertEqual(self._enumerate(rows, []), ["ALAE Paid", "Paid", "Paid 12"])

    def test_engine_rows_are_found_in_a_contract_shaped_index(self) -> None:
        rows = [
            # A sidecar-flavored source names its dataset "dataset_name"; the
            # canonical projection persists it as "name" only.
            canonicalize_index_row(
                {"dataset_name": "ALAE Paid", "source_kind": "engine"}
            ),
            canonicalize_index_row({"name": "Paid", "source_kind": "engine"}),
            canonicalize_index_row({"name": "Cutoff", "source_kind": "input"}),
            canonicalize_index_row({"name": "Ultimate", "source_kind": "dfm"}),
        ]
        self.assertNotIn("dataset_name", rows[0])
        self.assertEqual(self._enumerate(rows), ["ALAE Paid", "Paid"])

    def test_duplicate_names_and_malformed_rows_are_skipped(self) -> None:
        rows = [
            canonicalize_index_row({"name": "Paid", "source_kind": "engine"}),
            canonicalize_index_row({"name": "PAID", "source_kind": "engine"}),
            "not a row",
            {"source_kind": "engine"},
        ]
        self.assertEqual(self._enumerate(rows), ["Paid"])


class RegenerationRequestTests(unittest.TestCase):
    def _with_helpers(self):
        helpers = types.ModuleType("app_server.helpers")
        helpers.set_data_path_like_vba = lambda pairs: "E:\\cache.csv"
        app_server = types.ModuleType("app_server")
        app_server.helpers = helpers
        return patch.dict(
            sys.modules, {"app_server": app_server, "app_server.helpers": helpers}
        )

    def test_triangle_pairs_carry_the_sidecar_shape(self) -> None:
        with self._with_helpers():
            pairs, data_path = source_table_refresh._regeneration_request(
                {
                    "project_name": "Demo Project",
                    "reserving_class": "HPPREF\\NJ",
                    "dataset_name": "Paid 2026Q1",
                    "dataset_type": "Paid",
                    "data_format": "Triangle",
                    "origin_length": 12,
                    "development_length": 6,
                    "cumulative": False,
                    "calendar": True,
                },
                "Demo Project",
            )
        values = dict(pairs)
        self.assertEqual(values["Function"], "ArcRhoTri")
        self.assertEqual(values["DatasetName"], "Paid")
        self.assertEqual(values["InstanceName"], "Paid 2026Q1")
        self.assertEqual(values["OriginLength"], "12")
        self.assertEqual(values["DevelopmentLength"], "6")
        self.assertEqual(values["Cumulative"], "False")
        self.assertEqual(values["Calendar"], "True")
        self.assertEqual(data_path, "E:\\cache.csv")

    def test_a_vector_asks_for_the_vector_function_and_names_its_instance(self) -> None:
        with self._with_helpers():
            pairs, _ = source_table_refresh._regeneration_request(
                {
                    "project_name": "Demo Project",
                    "reserving_class": "HPPREF\\NJ",
                    "dataset_name": "Premium",
                    "dataset_type": "Premium",
                    "data_format": "Vector",
                    "period_length": 12,
                    "origin_length": 12,
                },
                "Demo Project",
            )
        values = dict(pairs)
        self.assertEqual(values["Function"], "ArcRhoVec")
        # The vector's shape travels in both length pairs, as the dataset route
        # does for a PeriodLength request.
        self.assertEqual(values["InstanceName"], "Premium")
        self.assertEqual(values["OriginLength"], "12")
        self.assertEqual(values["DevelopmentLength"], "12")

    def test_a_quarterly_vector_is_rebuilt_at_the_period_it_is_shown_at(self) -> None:
        # A vector sidecar states its period only under ``period_length``;
        # rebuilding it at 12 would refresh an annual copy nobody reads and
        # leave the quarterly one stale.
        with self._with_helpers():
            sys.modules["app_server.helpers"].set_data_path_like_vba = (
                lambda pairs: f"E:\\Earned Premium@{dict(pairs)['OriginLength']}.csv"
            )
            pairs, data_path = source_table_refresh._regeneration_request(
                {
                    "reserving_class": "HPPREF\\NJ",
                    "dataset_name": "Earned Premium",
                    "dataset_type": "Earned Premium",
                    "data_format": "Vector",
                    "period_length": 3,
                    "stored_period_length": 1,
                },
                "Demo Project",
            )
        values = dict(pairs)
        self.assertEqual(values["OriginLength"], "3")
        self.assertEqual(values["DevelopmentLength"], "3")
        self.assertEqual(data_path, "E:\\Earned Premium@3.csv")

    def test_the_project_refreshed_wins_over_the_name_in_the_sidecar(self) -> None:
        # A duplicated project's sidecars still name the project they were
        # copied from. Following that name would rebuild every dataset into the
        # source project and leave this one with no values at all.
        with self._with_helpers():
            pairs, _ = source_table_refresh._regeneration_request(
                {
                    "project_name": "Prod 2026 Q2-May",
                    "reserving_class": "HPPREF\\NJ",
                    "dataset_name": "Paid",
                    "dataset_type": "Paid",
                    "data_format": "Triangle",
                    "origin_length": 12,
                    "development_length": 12,
                },
                "Prod 2026 Q3-Aug",
            )
        self.assertEqual(dict(pairs)["ProjectName"], "Prod 2026 Q3-Aug")


class RegenerationSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.cache = self.root / "Paid.csv"
        self.cache.write_text("1,2\n3,4\n", encoding="utf-8")
        self.calls: list = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, outcome):
        sidecar = {
            "exists": True,
            "project_name": "Demo Project",
            "reserving_class": "HPPREF\\NJ",
            "dataset_name": "Paid",
            "dataset_type": "Paid",
            "data_format": "Triangle",
            "origin_length": 12,
            "development_length": 12,
            "cumulative": True,
            "calendar": False,
        }
        def run_arcrho_tri(*args, **kwargs):
            self.calls.append(kwargs)
            return self._clear_and_return(outcome)

        runtime = SimpleNamespace(run_arcrho_tri=run_arcrho_tri)
        dataset_service = SimpleNamespace(load_dataset_sidecar=lambda *a: sidecar)
        with _install_fake_app_server(
            {"arcrho_runtime_service": runtime, "dataset_service": dataset_service}
        ), patch.object(
            source_table_refresh,
            "_regeneration_request",
            return_value=([("Function", "ArcRhoTri")], str(self.cache)),
        ):
            return source_table_refresh._regenerate_engine_dataset(
                self.root, "Demo Project", "HPPREF\\NJ", "Paid"
            )

    def _clear_and_return(self, outcome):
        # The canonical runtime removes the cache before it asks the Engine for
        # a new one; a failed run must not leave the dataset without values.
        self.cache.unlink()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def test_a_failed_regeneration_restores_the_previous_cache(self) -> None:
        with self.assertRaises(source_table_refresh.SourceRefreshJobError):
            self._run({"ok": False, "message": "engine timed out"})
        self.assertTrue(self.cache.is_file())
        self.assertEqual(self.cache.read_text(encoding="utf-8"), "1,2\n3,4\n")
        self.assertFalse(Path(f"{self.cache}.refresh-backup").exists())

    def test_a_raised_regeneration_restores_the_previous_cache(self) -> None:
        with self.assertRaises(RuntimeError):
            self._run(RuntimeError("engine crashed"))
        self.assertTrue(self.cache.is_file())

    def test_a_successful_regeneration_keeps_the_new_cache_and_no_backup(self) -> None:
        self.assertTrue(self._run({"ok": True, "need_request": True}))
        # One index rebuild covers the whole class, at the end of its walk;
        # rebuilding after each dataset re-reads every sidecar in the folder.
        self.assertEqual(self.calls[0]["refresh_index"], False)
        self.assertEqual(self.calls[0]["recalculate_dependents_on_cache_write"], False)
        self.assertEqual(self.calls[0]["force_refresh"], True)
        # The stub deleted the cache to imitate the real refresh; success must
        # not put the stale copy back over the Engine's output.
        self.assertFalse(self.cache.exists())
        self.assertFalse(Path(f"{self.cache}.refresh-backup").exists())


class ScopedRefreshTests(unittest.TestCase):
    """A narrowed request refreshes only the classes and types it names."""

    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def _run(self, import_source=False, source_type="csv", source_table_extra=None, **scope):
        request = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
            import_source=import_source,
            **scope,
        )
        refreshed = []
        self.recorded = []
        self.values_rebuilt = []

        def refresh_one(root, project, reserving_class, result, *, on_dataset, dataset_types=None):
            refreshed.append((reserving_class, list(dataset_types or [])))

        source_table = SimpleNamespace(
            get_source_table_state=lambda project: {"source_type": source_type},
            record_refresh_scope=lambda project, types, class_types: self.recorded.append(
                (project, list(types), list(class_types))
            ),
            **(source_table_extra or {}),
        )
        summary = SimpleNamespace(
            refresh_table_summary=lambda project, **kwargs: {"row_count": 7},
        )
        runtime = SimpleNamespace(clear_arcrho_headers_cache=lambda project: None)
        classes = [
            "HPPREF\\HO+DF\\NJ\\Legacy\\HOL",
            "HPPREF\\HO+DF\\NJ\\Legacy\\HOPxCAT",
            "PIC2\\PA\\NY\\Core Direct\\COL",
        ]
        # No formula in this project's table reads the selected type, so the
        # expansion gives the selection back unchanged.
        calculated = SimpleNamespace(
            generated_formula_refresh_types=lambda project, names: (
                generated_formula_refresh_names([], names)
            )
        )
        with _install_fake_app_server(
            {
                "arcrho_runtime_service": runtime,
                "calculated_dataset_service": calculated,
                "data_processing_values_service": SimpleNamespace(
                    get_data_processing_values=self.values_rebuilt.append
                ),
                "source_table_service": source_table,
                "table_summary_service": summary,
                "user_identity_service": _identity_stub([]),
            }
        ), patch.object(
            source_table_refresh, "configure_canonical_runtime", lambda root: None
        ), patch.object(
            source_table_refresh, "_reserving_class_paths", lambda project: list(classes)
        ), patch.object(
            source_table_refresh, "_refresh_one_reserving_class", refresh_one
        ), patch.object(source_table_refresh, "_log", lambda *a, **k: None):
            result = source_table_refresh.execute_source_refresh(
                Path(tempfile.gettempdir()), request
            )
        return result, refreshed

    def test_no_scope_refreshes_every_class_and_every_engine_dataset(self) -> None:
        result, refreshed = self._run()
        self.assertEqual(result["classes_total"], 3)
        self.assertEqual([types for _, types in refreshed], [[], [], []])
        self.assertEqual(result["dataset_types_expanded"], [])
        # "Everything" is recorded too, so a later narrowing never lingers.
        self.assertEqual(self.recorded, [("Demo Project", [], [])])

    def test_an_import_of_a_combined_source_goes_through_the_guarded_master_read(self) -> None:
        # A combined source is joined on the client; the job must reach the
        # path that never re-reads it, not the SQL Server import.
        calls = []

        def ensure_master_table(project, *, force=False):
            calls.append((project, force))
            return {"last_import": {"source_type": "combined", "row_count": 4, "column_count": 3}}

        def import_from_mssql(project):
            raise AssertionError("a combined source must never be read from SQL Server by the Engine")

        result, _refreshed = self._run(
            import_source=True,
            source_type="combined",
            source_table_extra={
                "ensure_master_table": ensure_master_table,
                "import_from_mssql": import_from_mssql,
            },
        )
        self.assertEqual(calls, [("Demo Project", True)])
        self.assertEqual((result["source_type"], result["row_count"]), ("combined", 4))

    def test_the_job_rebuilds_the_data_processing_value_list(self) -> None:
        # The Data Processing Rules page only reads this cache; the refresh
        # that changed the table is what writes it.
        result, _refreshed = self._run()
        self.assertEqual(self.values_rebuilt, ["Demo Project"])
        self.assertEqual(result["failures"], [])

    def test_class_types_pick_the_classes_and_dataset_types_reach_each_one(self) -> None:
        result, refreshed = self._run(
            dataset_types=["Gross Loss--Paid"],
            reserving_class_types=[
                {"Name": "HPPREF", "Level": 1},
                {"Name": "HOL", "Level": 5},
            ],
        )
        self.assertEqual(result["classes_total"], 1)
        self.assertEqual(
            refreshed, [("HPPREF\\HO+DF\\NJ\\Legacy\\HOL", ["Gross Loss--Paid"])]
        )
        self.assertEqual(result["dataset_types_expanded"], ["Gross Loss--Paid"])
        self.assertEqual(
            self.recorded,
            [(
                "Demo Project",
                ["Gross Loss--Paid"],
                [{"Name": "HPPREF", "Level": 1}, {"Name": "HOL", "Level": 5}],
            )],
        )


class DurableSourceRefreshTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def setUp(self) -> None:
        logs_tmp = TESTS_DIR / "logs" / "tmp"
        logs_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(logs_tmp))
        self.root = Path(self.temp.name)
        self.request = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
        )
        self.request_path = source_refresh_request_path(self.root, self.REQUEST_ID)
        self.request_path.parent.mkdir(parents=True, exist_ok=True)
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _process(self, execute):
        with patch.object(source_table_refresh, "execute_source_refresh", execute):
            return source_table_refresh.process_durable_source_refresh_request(
                self.root, self.request_path, self.request
            )

    def test_a_completed_job_publishes_success_and_drops_its_queue_file(self) -> None:
        result = source_table_refresh._empty_result()
        result.update({"imported": True, "row_count": 42, "source_type": "csv"})
        seen = []

        def execute(root, request, *, progress_callback=None):
            seen.append(request["RequestId"])
            progress_callback(
                source_table_refresh._progress("caches", 1, 3, "Rebuilding caches")
            )
            return result

        self.assertTrue(self._process(execute))
        self.assertEqual(seen, [self.REQUEST_ID])
        status = read_source_refresh_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["result"]["row_count"], 42)
        self.assertFalse(self.request_path.exists())

    def test_reported_failures_make_the_job_terminal_error_with_its_counts(self) -> None:
        result = source_table_refresh._empty_result()
        result.update(
            {
                "imported": True,
                "classes_total": 2,
                "classes_refreshed": 1,
                "datasets_failed": 1,
                "failures": ["HPPREF\\NJ: Paid: the ArcRho Engine did not return values."],
            }
        )

        self.assertFalse(self._process(lambda *a, **k: result))
        status = read_source_refresh_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertIn("1 dataset(s) failed", status["message"])
        self.assertEqual(status["result"]["classes_refreshed"], 1)

    def test_a_raised_job_publishes_a_redacted_error(self) -> None:
        def explode(*args, **kwargs):
            raise OSError(r"E:\ArcRho Server\projects\Demo\source\master_table.csv")

        self.assertFalse(self._process(explode))
        status = read_source_refresh_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        # The client is told the filesystem failed, never where on the server.
        self.assertNotIn("master_table.csv", status["message"])
        self.assertNotIn("projects", status["message"])

    def test_a_held_project_is_not_claimed_and_leaves_the_request_queued(self) -> None:
        lease = acquire_source_refresh_lease(self.root, "Demo Project")
        self.addCleanup(release_source_refresh_lease, lease)
        called = []
        self.assertFalse(self._process(lambda *a, **k: called.append(1)))
        self.assertEqual(called, [])
        self.assertTrue(self.request_path.exists())

    def test_an_already_terminal_request_is_dropped_without_rerunning(self) -> None:
        write_source_refresh_status(
            self.root,
            self.REQUEST_ID,
            "success",
            progress={"stage": "complete", "completed": 1, "total": 1, "label": "Done"},
        )
        called = []
        self.assertTrue(self._process(lambda *a, **k: called.append(1)))
        self.assertEqual(called, [])
        self.assertFalse(self.request_path.exists())

    def test_a_rejected_payload_publishes_an_error_and_drops_the_file(self) -> None:
        broken = {**self.request, "Force": "yes"}
        with patch.object(source_table_refresh, "execute_source_refresh") as execute:
            handled = source_table_refresh.process_durable_source_refresh_request(
                self.root, self.request_path, broken
            )
        self.assertFalse(handled)
        execute.assert_not_called()
        status = read_source_refresh_status(self.root, self.REQUEST_ID)
        self.assertEqual(status["status"], "error")
        self.assertFalse(self.request_path.exists())


class EngineDispatchTests(unittest.TestCase):
    def test_the_engine_routes_the_function_to_the_source_refresh_worker(self) -> None:
        handler = engine_main.RequestHandler()
        self.addCleanup(handler.shutdown, wait=False)
        request = {
            "Function": SOURCE_REFRESH_FUNCTION,
            "RequestId": "0123456789abcdef0123456789abcdef",
        }
        with patch.object(handler, "_schedule_source_refresh") as scheduled:
            handler.process_file = types.MethodType(
                engine_main.RequestHandler.process_file, handler
            )
            with patch.object(engine_main, "read_json", return_value=request):
                handler.process_file("queued.json", dispatch_duplication=True)
        scheduled.assert_called_once()


class ClassWalkReportingTests(unittest.TestCase):
    """The class step says why a dependent walk failed and counts real updates."""

    def _walk(self, walk):
        result = source_table_refresh._empty_result()
        logged: list[str] = []
        calculated = SimpleNamespace(
            recalculate_dependents=lambda *a, **k: walk,
            cascade_failure_reasons=lambda report: [
                f"{item['dataset_type_name']}: {item['reason']}"
                for item in report.get("skipped", [])
            ],
        )
        with _install_fake_app_server(
            {"calculated_dataset_service": calculated}
        ), patch.object(
            source_table_refresh, "acquire_reserving_class_lease", lambda *a: object()
        ), patch.object(
            source_table_refresh,
            "start_reserving_class_lease_heartbeat",
            lambda lease: (None, None),
        ), patch.object(
            source_table_refresh, "stop_reserving_class_lease_heartbeat", lambda *a: None
        ), patch.object(
            source_table_refresh, "release_reserving_class_lease", lambda lease: None
        ), patch.object(
            source_table_refresh, "_engine_dataset_instances", lambda *a: ["Paid"]
        ), patch.object(
            source_table_refresh, "_regenerate_engine_dataset", lambda *a: True
        ), patch.object(
            source_table_refresh,
            "_log",
            lambda root, message, **kwargs: logged.append(message),
        ):
            source_table_refresh._refresh_one_reserving_class(
                Path(tempfile.gettempdir()),
                "Demo Project",
                "HPPREF\\NJ",
                result,
                on_dataset=lambda name: None,
            )
        return result, logged

    def test_a_failed_walk_names_the_first_reason_and_logs_them_all(self) -> None:
        result, logged = self._walk(
            {
                "ok": False,
                "skipped": [
                    {
                        "dataset_type_name": "C 12 - CWP DFM",
                        "reason": "DFM precedent 'Claim Counts--CWP' could not be "
                        "generated at the method's period: engine timed out",
                    },
                    {"dataset_type_name": "F 13 - Paid DFM", "reason": "engine timed out"},
                ],
                "dfm_updates": {"ok": False, "updated": [], "errors": []},
            }
        )
        self.assertEqual(
            result["failures"],
            [
                "HPPREF\\NJ: C 12 - CWP DFM: DFM precedent 'Claim Counts--CWP' could "
                "not be generated at the method's period: engine timed out (+1 more)"
            ],
        )
        self.assertTrue(
            any(
                "C 12 - CWP DFM" in line and "F 13 - Paid DFM" in line
                for line in logged
            ),
            logged,
        )

    def test_a_failed_walk_with_no_named_reason_keeps_the_generic_line(self) -> None:
        result, logged = self._walk({"ok": False})
        self.assertEqual(
            result["failures"], ["HPPREF\\NJ: the dependent refresh reported errors."]
        )
        self.assertTrue(any("no reason recorded" in line for line in logged), logged)

    def test_methods_updated_counts_the_methods_each_wave_re_saved(self) -> None:
        result, _logged = self._walk(
            {
                "ok": True,
                "dfm_updates": {
                    "ok": True,
                    "updated": [{"method_name": "F 12"}, {"method_name": "G 21"}],
                    "status_refreshed": [{"method_name": "F 13"}],
                },
                "bornhuetter_ferguson_updates": {"ok": True, "updated": [{"method_name": "F 41"}]},
                "cape_cod_updates": {"ok": True, "updated": []},
            }
        )
        self.assertEqual(result["methods_updated"], 3)
        self.assertEqual(result["failures"], [])


class GeneratedFormulaScopeTests(unittest.TestCase):
    """A narrowed refresh rebuilds the formulas the Engine builds from the selection.

    ``Total Earned Premium`` is an Engine formula over ``Earned Premium`` and
    ``Remaining Budget Premium``, and ``Premium Ratio`` is a formula over that.
    Selecting only ``Earned Premium`` therefore has to rebuild all three, in
    every class the request covers, or the values downstream of the import stay
    as they were. The type walk is shared with the app server, so the stand-in
    service here delegates to the canonical reader rather than re-deciding.
    """

    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    DATASET_TYPE_ROWS = [
        {"name": "Earned Premium", "calculated": False, "generated": True, "formula": ""},
        {
            "name": "Remaining Budget Premium",
            "calculated": False,
            "generated": True,
            "formula": "",
        },
        {"name": "Net Loss--Paid", "calculated": False, "generated": True, "formula": ""},
        {
            "name": "Total Earned Premium",
            "calculated": True,
            "generated": True,
            "formula": '"Earned Premium" + "Remaining Budget Premium"',
        },
        {
            "name": "Premium Ratio",
            "calculated": True,
            "generated": True,
            "formula": '"Net Loss--Paid" / "Total Earned Premium"',
        },
        {
            # ArcRho's own evaluator owns this one, and the dependent walk
            # rebuilds it; the Engine must not put it in the regeneration set.
            "name": "Paid Loss Ratio",
            "calculated": True,
            "generated": False,
            "formula": '"Net Loss--Paid" / "Earned Premium"',
        },
    ]

    CLASS_INSTANCES = {
        "HPPREF\\HO+DF\\NJ\\Legacy\\HOL": [
            ("Earned Premium", "Earned Premium"),
            ("Earned Premium 2025", "Earned Premium"),
            ("Total Earned Premium", "Total Earned Premium"),
            ("Premium Ratio", "Premium Ratio"),
            ("Net Loss--Paid", "Net Loss--Paid"),
        ],
        "HPPREF\\HO+DF\\NJ\\Legacy\\HOPxCAT": [
            ("Earned Premium", "Earned Premium"),
            # No instance of the formula in between, which must not stop the
            # ratio built on top of it from being rebuilt here.
            ("Premium Ratio", "Premium Ratio"),
        ],
        "PIC2\\PA\\NY\\Core Direct\\COL": [
            ("Earned Premium", "Earned Premium"),
            ("Total Earned Premium", "Total Earned Premium"),
        ],
    }

    def _index(self, project, reserving_class):
        return {
            "files": [
                canonicalize_index_row(
                    {"name": name, "dataset_type": type_name, "source_kind": "engine"}
                )
                for name, type_name in self.CLASS_INSTANCES.get(reserving_class, [])
            ]
        }

    def _run(self, *, failing_dataset: str = "", **scope):
        request = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
            import_source=False,
            **scope,
        )
        self.regenerated: list[tuple[str, str]] = []
        self.walk_roots: list[tuple[str, list[str]]] = []
        self.recorded: list[tuple] = []

        def regenerate(root, project, reserving_class, dataset_name):
            if dataset_name == failing_dataset:
                raise source_table_refresh.SourceRefreshJobError(
                    f"{dataset_name}: the ArcRho Engine did not return values."
                )
            self.regenerated.append((reserving_class, dataset_name))
            return True

        def recalculate_dependents(
            project, reserving_class, first, _kind, *, additional_roots=(), rebuild_index=False
        ):
            self.walk_roots.append(
                (reserving_class, [first, *[name for name, _ in additional_roots]])
            )
            return {"ok": True}

        calculated = SimpleNamespace(
            # The one expansion rule, read through the canonical helper the app
            # server's service calls; only the table read is stood in for here.
            generated_formula_refresh_types=lambda project, names: (
                generated_formula_refresh_names(self.DATASET_TYPE_ROWS, names)
            ),
            recalculate_dependents=recalculate_dependents,
        )
        source_table = SimpleNamespace(
            get_source_table_state=lambda project: {"source_type": "csv"},
            record_refresh_scope=lambda project, types, class_types: self.recorded.append(
                (project, list(types), list(class_types))
            ),
        )
        modules = {
            "arcrho_runtime_service": SimpleNamespace(
                clear_arcrho_headers_cache=lambda project: None
            ),
            "calculated_dataset_service": calculated,
            "dataset_instance_index_service": SimpleNamespace(get_index=self._index),
            "source_table_service": source_table,
            "table_summary_service": SimpleNamespace(
                refresh_table_summary=lambda project, **kwargs: {"row_count": 7}
            ),
            "user_identity_service": _identity_stub([]),
        }
        with _install_fake_app_server(modules), patch.object(
            source_table_refresh, "configure_canonical_runtime", lambda root: None
        ), patch.object(
            source_table_refresh,
            "_reserving_class_paths",
            lambda project: list(self.CLASS_INSTANCES),
        ), patch.object(
            source_table_refresh, "acquire_reserving_class_lease", lambda *a: object()
        ), patch.object(
            source_table_refresh,
            "start_reserving_class_lease_heartbeat",
            lambda lease: (None, None),
        ), patch.object(
            source_table_refresh, "stop_reserving_class_lease_heartbeat", lambda *a: None
        ), patch.object(
            source_table_refresh, "release_reserving_class_lease", lambda lease: None
        ), patch.object(
            source_table_refresh, "_regenerate_engine_dataset", regenerate
        ), patch.object(source_table_refresh, "_log", lambda *a, **k: None):
            return source_table_refresh.execute_source_refresh(
                Path(tempfile.gettempdir()), request
            )

    def _names_in(self, reserving_class: str) -> list[str]:
        return [name for klass, name in self.regenerated if klass == reserving_class]

    def test_one_selected_type_rebuilds_the_formulas_built_on_it(self) -> None:
        result = self._run(dataset_types=["Earned Premium"])

        self.assertEqual(
            result["dataset_types_expanded"],
            ["Earned Premium", "Total Earned Premium", "Premium Ratio"],
        )
        # Both instances of the selected type, the formula over it, and the
        # formula over that one; the unrelated engine type stays out.
        self.assertEqual(
            self._names_in("HPPREF\\HO+DF\\NJ\\Legacy\\HOL"),
            ["Earned Premium", "Earned Premium 2025", "Total Earned Premium", "Premium Ratio"],
        )
        # Every regenerated dataset is a root of the class's one walk.
        self.assertEqual(
            self.walk_roots[0],
            (
                "HPPREF\\HO+DF\\NJ\\Legacy\\HOL",
                ["Earned Premium", "Earned Premium 2025", "Total Earned Premium", "Premium Ratio"],
            ),
        )
        self.assertEqual(len(self.walk_roots), 3)
        # The selection the person made is what the next Import Scope opens on.
        self.assertEqual(self.recorded, [("Demo Project", ["Earned Premium"], [])])

    def test_a_type_with_no_instance_does_not_hide_the_formula_above_it(self) -> None:
        self._run(dataset_types=["Earned Premium"])

        self.assertEqual(
            self._names_in("HPPREF\\HO+DF\\NJ\\Legacy\\HOPxCAT"),
            ["Earned Premium", "Premium Ratio"],
        )

    def test_a_class_scope_leaves_the_classes_outside_it_alone(self) -> None:
        result = self._run(
            dataset_types=["Earned Premium"],
            reserving_class_types=[{"Name": "HPPREF", "Level": 1}],
        )

        self.assertEqual(result["classes_total"], 2)
        self.assertEqual(self._names_in("PIC2\\PA\\NY\\Core Direct\\COL"), [])
        self.assertEqual(result["datasets_regenerated"], 6)

    def test_selecting_the_formula_itself_rebuilds_only_what_reads_it(self) -> None:
        result = self._run(dataset_types=["Total Earned Premium"])

        self.assertEqual(
            result["dataset_types_expanded"],
            ["Total Earned Premium", "Premium Ratio"],
        )
        self.assertEqual(
            self._names_in("HPPREF\\HO+DF\\NJ\\Legacy\\HOL"),
            ["Total Earned Premium", "Premium Ratio"],
        )

    def test_an_unscoped_refresh_rebuilds_every_engine_dataset_as_before(self) -> None:
        result = self._run()

        self.assertEqual(result["dataset_types_expanded"], [])
        self.assertEqual(
            self._names_in("HPPREF\\HO+DF\\NJ\\Legacy\\HOL"),
            [
                "Earned Premium",
                "Earned Premium 2025",
                "Total Earned Premium",
                "Premium Ratio",
                "Net Loss--Paid",
            ],
        )

    def test_a_formula_that_fails_is_reported_and_left_out_of_the_walk(self) -> None:
        result = self._run(
            dataset_types=["Earned Premium"], failing_dataset="Total Earned Premium"
        )

        self.assertEqual(result["datasets_failed"], 2)
        self.assertTrue(
            all("Total Earned Premium" in failure for failure in result["failures"]),
            result["failures"],
        )
        for reserving_class, roots in self.walk_roots:
            self.assertNotIn("Total Earned Premium", roots, reserving_class)
        # What did succeed is still walked, so nothing else is left behind.
        self.assertEqual(
            self.walk_roots[0],
            (
                "HPPREF\\HO+DF\\NJ\\Legacy\\HOL",
                ["Earned Premium", "Earned Premium 2025", "Premium Ratio"],
            ),
        )


class RulesJobScopeTests(unittest.TestCase):
    """Saving the rules expands the affected types exactly as Import Data does."""

    def test_the_rules_job_rebuilds_the_formulas_over_an_affected_type(self) -> None:
        from arcrho_engine import data_processing_rules_jobs

        refreshed: list[tuple[str, list[str]]] = []

        def refresh_one(root, project, reserving_class, result, *, on_dataset, dataset_types=None):
            refreshed.append((reserving_class, list(dataset_types or [])))

        calculated = SimpleNamespace(
            generated_formula_refresh_types=lambda project, names: (
                generated_formula_refresh_names(
                    GeneratedFormulaScopeTests.DATASET_TYPE_ROWS, names
                )
            )
        )
        with _install_fake_app_server(
            {"calculated_dataset_service": calculated}
        ), patch.object(
            source_table_refresh,
            "_reserving_class_paths",
            lambda project: ["HPPREF\\HO+DF\\NJ\\Legacy\\HOL"],
        ), patch.object(
            source_table_refresh, "_engine_dataset_instances", lambda *a: ["Earned Premium"]
        ), patch.object(
            source_table_refresh, "_refresh_one_reserving_class", refresh_one
        ), patch.object(
            data_processing_rules_jobs, "_log", lambda *a, **k: None
        ):
            result = data_processing_rules_jobs._refresh_affected_datasets(
                Path(tempfile.gettempdir()),
                "Demo Project",
                ["Earned Premium"],
                notify=lambda *a: None,
            )

        self.assertEqual(
            result["dataset_types_expanded"],
            ["Earned Premium", "Total Earned Premium", "Premium Ratio"],
        )
        self.assertEqual(
            refreshed,
            [
                (
                    "HPPREF\\HO+DF\\NJ\\Legacy\\HOL",
                    ["Earned Premium", "Total Earned Premium", "Premium Ratio"],
                )
            ],
        )

if __name__ == "__main__":
    unittest.main()
