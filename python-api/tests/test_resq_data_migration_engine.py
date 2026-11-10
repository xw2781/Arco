from __future__ import annotations

import importlib
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migration" / "resq_data_migration.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location("resq_data_migration_engine_under_test", _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load resq_data_migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_triangle(name: str, dataset_type: str):
    return types.SimpleNamespace(
        Name=name,
        DatasetType=types.SimpleNamespace(
            Name=dataset_type,
            Category=types.SimpleNamespace(Name="Loss"),
            DataFormat=0,
        ),
    )


class _FakeCollection:
    def __init__(self, items: dict):
        self._items = items

    def Item(self, name):
        return self._items[name]

    def __iter__(self):
        return iter(self._items.values())


class _FakeReservingClass:
    def __init__(self, triangles: dict):
        self._triangles = triangles

    def Triangles(self):
        return _FakeCollection(self._triangles)


class ResqDataMigrationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.tmp.name) / "Arco Server"
        self.project_dir = self.root / "projects" / "Demo"
        self.rc_dir = self.project_dir / "data" / "Auto_%5C_PP"
        self.datasets_dir = self.rc_dir / "datasets"
        self.methods_dir = self.rc_dir / "methods"
        self.sidecars_dir = self.rc_dir / "sidecars"
        self.datasets_dir.mkdir(parents=True)
        self.methods_dir.mkdir()
        self.sidecars_dir.mkdir()
        instances_dir = self.root / "runtime" / "instances" / "arcrho_engine"
        instances_dir.mkdir(parents=True)
        (instances_dir / "worker.json").write_text("{}", encoding="utf-8")

        self.module = load_migration_module()
        self.module.SERVER_ROOT = self.root
        self.module.PROJECT_NAME = "Demo"
        self.module.PROJECT_DATA_DIR = self.project_dir / "data"

        self.catalog = importlib.import_module("resq_migration.catalog")
        self.catalog.configure_catalog(
            server_root=self.root,
            project_name="Demo",
            rs_json_format=self.module.RS_JSON_FORMAT,
            method_data_dir=self.module.METHOD_DATA_DIR,
        )
        self.extractors = importlib.import_module("resq_migration.extractors")
        self.extractors.configure_extractors(
            project_name="Demo",
            rs_json_format=self.module.RS_JSON_FORMAT,
            method_data_dir=self.module.METHOD_DATA_DIR,
        )

        (self.project_dir / "dataset_types.json").write_text(json.dumps({
            "columns": ["Formula", "Generated", "Name", "Calculated", "Data Format", "Category", "Source"],
            "rows": [
                ["", True, "Paid Loss", False, "Triangle", "Loss", "PaidLoss"],
                ["", True, "Generated Premium", False, "Vector", "Premium", "Prem"],
                ["\"Paid Loss\" * 1.1", False, "Loaded Loss", True, "Triangle", "Loss", ""],
                # Copied from ResQ with a formula over a type ArcRho never imported.
                ["\"Current Qtr Indicated\" * \"Loaded Loss\"", False, "Orphaned Loss", True, "Triangle", "Loss", ""],
            ],
        }), encoding="utf-8")

        self.provenance = {
            "config_hash": "sha256:deadbeef",
            "algorithm_version": "arcrho-data-processing-v1",
            "rules_format": "arcrho-data-processing-rules-v1",
            "rules_revision": 4,
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- gate -----------------------------------------------------------------

    def test_gate_true_for_generated_instance_named_as_type(self) -> None:
        self.assertTrue(
            self.module._is_engine_generated_instance(
                {"name": "Paid Loss", "dataset_type": "Paid Loss"}
            )
        )

    def test_gate_false_when_instance_name_differs_from_type(self) -> None:
        self.assertFalse(
            self.module._is_engine_generated_instance(
                {"name": "Paid Loss AY2020", "dataset_type": "Paid Loss"}
            )
        )

    def test_gate_false_for_non_generated_type(self) -> None:
        self.assertFalse(
            self.module._is_engine_generated_instance(
                {"name": "Loaded Loss", "dataset_type": "Loaded Loss"}
            )
        )

    # -- source kind ----------------------------------------------------------

    def test_triangle_source_kind_follows_the_dataset_types_library(self) -> None:
        """A ResQ triangle named after a plain type is an input, not an engine dataset."""
        self.assertEqual(self.module._triangle_source_kind("Paid Loss", "Paid Loss"), "engine")
        self.assertEqual(self.module._triangle_source_kind("Paid Loss AY2020", "Paid Loss"), "input")
        self.assertEqual(self.module._triangle_source_kind("Loaded Loss", "Loaded Loss"), "calculated")
        self.assertEqual(
            self.module._triangle_source_kind(
                "Net Loss--Incurred Adjusted*", "Net Loss--Incurred Adjusted*"
            ),
            "input",
        )
        # A calculated type whose formula names a type ArcRho does not have
        # can never be rebuilt, so its instances are hand-entered inputs.
        self.assertEqual(self.module._triangle_source_kind("Orphaned Loss", "Orphaned Loss"), "input")

    # -- two-decimal comparison -----------------------------------------------

    def test_import_comparison_agrees_within_two_decimal_places(self) -> None:
        from resq_migration.engine_parity import compare_import_values, describe_import_mismatch

        agreed = compare_import_values([[1.004, None]], [[1.0, None]])
        self.assertTrue(agreed["matches"])
        self.assertEqual(describe_import_mismatch(agreed), "")

        differs = compare_import_values([[1.0, 2.0]], [[1.006, 2.0]])
        self.assertFalse(differs["matches"])
        self.assertEqual(
            describe_import_mismatch(differs),
            "1 cell(s) differ from ResQ at 2 decimal places; first at origin 1, development 1: "
            "ResQ 1.00, Arco Engine 1.01.",
        )

        shape = compare_import_values([[1.0, 2.0]], [[1.0]])
        self.assertEqual(
            describe_import_mismatch(shape),
            "ResQ holds 1 x 2 cells but Arco Engine produced 1 x 1.",
        )

    # -- unreviewed datasets --------------------------------------------------

    def test_unreviewed_rule_covers_calculated_and_engine_generated_datasets(self) -> None:
        self.assertTrue(self.module._is_unreviewed_dataset("Paid Loss", "Paid Loss"))
        self.assertTrue(self.module._is_unreviewed_dataset("Loaded Loss", "Loaded Loss"))
        self.assertFalse(self.module._is_unreviewed_dataset("Paid Loss AY2020", "Paid Loss"))
        self.assertFalse(self.module._is_unreviewed_dataset("Incurred Loss", "Incurred Loss"))
        self.assertFalse(self.module._is_unreviewed_dataset("Orphaned Loss", "Orphaned Loss"))

    def test_ticked_names_keep_every_unreviewed_dataset(self) -> None:
        """The review never offers calculated or generated datasets, so ticking cannot drop them."""
        triangles = {
            "Paid Loss": _fake_triangle("Paid Loss", "Paid Loss"),
            "Loaded Loss": _fake_triangle("Loaded Loss", "Loaded Loss"),
            "Incurred Loss": _fake_triangle("Incurred Loss", "Incurred Loss"),
        }
        vectors = {
            "Generated Premium": _fake_triangle("Generated Premium", "Generated Premium"),
            "Earned Premium": _fake_triangle("Earned Premium", "Earned Premium"),
        }
        reserving_class = types.SimpleNamespace(Vectors=lambda: _FakeCollection(vectors))
        inventory = {
            "triangle_names": list(triangles),
            "triangle_items": {name.casefold(): item for name, item in triangles.items()},
            "triangle_method_types": {},
            "vector_names": list(vectors),
        }

        narrowed = self.module._select_export_inventory(inventory, ["Incurred Loss"], reserving_class)

        self.assertEqual(narrowed["triangle_names"], ["Paid Loss", "Loaded Loss", "Incurred Loss"])
        self.assertEqual(narrowed["vector_names"], ["Generated Premium"])
        self.assertEqual((narrowed["triangles"], narrowed["vectors"], narrowed["total"]), (3, 1, 4))

    # -- sidecar writer -------------------------------------------------------

    def test_engine_triangle_sidecar_shape_and_provenance(self) -> None:
        csv_name = "Paid Loss@12@6@cum@dev.csv"
        csv_path = self.datasets_dir / csv_name
        csv_path.write_text("1,2\n3,4\n", encoding="utf-8")
        self.extractors.write_engine_generated_export(
            {
                "name": "Paid Loss",
                "dataset_type": "Paid Loss",
                "category": "Loss",
                "data_format": 0,
                "origin_length": 12,
                "development_length": 6,
                "origin_labels": ["2025", "2026"],
                "user": "tester",
                "created": "2026-01-01T00:00:00",
                "modified": "2026-01-02T00:00:00",
            },
            r"Auto\PP",
            self.rc_dir,
            is_vector=False,
            provenance=self.provenance,
            csv_name=csv_name,
            csv_path=csv_path,
        )
        payload = json.loads((self.sidecars_dir / "Paid Loss.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["source_kind"], "engine")
        self.assertNotIn("source", payload)  # no resq_* marker -> not an imported snapshot
        self.assertFalse(payload["calculated"])
        self.assertNotIn("formula", payload)
        self.assertEqual(payload["data_format"], "Triangle")
        self.assertEqual(payload["origin_length"], 12)
        self.assertEqual(payload["development_length"], 6)
        self.assertTrue(payload["cumulative"])
        self.assertFalse(payload["calendar"])
        self.assertEqual(payload["status"], 0)
        self.assertEqual(payload["method_type"], "None")
        self.assertNotIn("origin_labels", payload)  # engine determines shape
        self.assertEqual(payload["csv_file"], csv_name)
        self.assertEqual(payload["processing"], self.provenance)
        self.assertNotIn("processing_by_csv", payload)
        self.assertEqual(payload["audit_log"][0]["action"], "Insert")

    def test_engine_vector_sidecar_uses_period_length(self) -> None:
        csv_name = "Generated Premium@6.csv"
        csv_path = self.datasets_dir / csv_name
        csv_path.write_text("10\n", encoding="utf-8")
        self.extractors.write_engine_generated_export(
            {
                "name": "Generated Premium",
                "dataset_type": "Generated Premium",
                "category": "Premium",
                "data_format": 1,
                "origin_length": 6,
                "development_length": 6,
                "period_length": 6,
                "user": "tester",
            },
            r"Auto\PP",
            self.rc_dir,
            is_vector=True,
            provenance=self.provenance,
            csv_name=csv_name,
            csv_path=csv_path,
        )
        payload = json.loads((self.sidecars_dir / "Generated Premium.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["source_kind"], "engine")
        self.assertEqual(payload["data_format"], "Vector")
        self.assertEqual(payload["period_length"], 6)
        self.assertNotIn("origin_length", payload)
        self.assertNotIn("development_length", payload)
        self.assertNotIn("cumulative", payload)
        self.assertEqual(payload["processing"]["config_hash"], "sha256:deadbeef")
        self.assertNotIn("processing_by_csv", payload)

    # -- orchestration: period preservation + no fallback ---------------------

    def test_generated_dataset_orchestration_preserves_periods(self) -> None:
        payload = {
            "name": "Paid Loss",
            "dataset_type": "Paid Loss",
            "category": "Loss",
            "data_format": 0,
            "origin_length": 24,
            "development_length": 18,
            "user": "tester",
        }
        task = self.module._create_engine_generated_task(
            payload,
            r"Auto\PP",
            self.rc_dir,
            is_vector=False,
        )
        job = task["job"]

        self.assertEqual(job.payload["OriginLength"], 24)
        self.assertEqual(job.payload["DevelopmentLength"], 18)
        self.assertEqual(job.payload["Function"], "ArcRhoTri")
        self.assertEqual(job.target_path.name, "Paid Loss@24@18@cum@dev.csv")

    def test_engine_failure_records_error_without_resq_fallback(self) -> None:
        write_calls = []

        def _boom(_job, **_kwargs):
            raise RuntimeError("engine down")

        self.module.publish_engine_request = _boom
        self.module.write_triangle_export = lambda *a, **k: write_calls.append(a)
        rc = _FakeReservingClass({"Paid Loss": _fake_triangle("Paid Loss", "Paid Loss")})
        self.module.export_triangle = lambda *_args, **_kwargs: self.fail(
            "engine-owned datasets must not extract ResQ cell values"
        )

        progress_state = {"completed": 0, "total": 1}
        written, errors = self.module.export_triangles_for_rc(
            rc,
            r"Auto\PP",
            self.rc_dir,
            progress_state=progress_state,
            triangle_names=["Paid Loss"],
            engine_provenance=self.provenance,
            verbose=False,
        )

        self.assertEqual((written, errors), (0, 1))
        self.assertEqual(write_calls, [])  # no ResQ fallback write
        self.assertFalse(any(self.datasets_dir.glob("Paid Loss@*.csv")))

    def test_missing_engine_skips_generated_dataset_without_resq_value_read(self) -> None:
        rc = _FakeReservingClass({"Paid Loss": _fake_triangle("Paid Loss", "Paid Loss")})
        self.module.export_triangle = lambda *_args, **_kwargs: self.fail(
            "engine-owned datasets must not extract ResQ cell values"
        )
        progress_state = {"completed": 0, "total": 1}

        written, errors = self.module.export_triangles_for_rc(
            rc,
            r"Auto\PP",
            self.rc_dir,
            progress_state=progress_state,
            triangle_names=["Paid Loss"],
            engine_available=False,
            verbose=False,
        )

        self.assertEqual((written, errors), (0, 0))
        self.assertEqual(progress_state["engine_skipped"], 1)
        self.assertEqual(progress_state["skipped"], 1)

    def test_generated_requests_are_all_published_before_waiting(self) -> None:
        rc = _FakeReservingClass({
            "Paid Loss": _fake_triangle("Paid Loss", "Paid Loss"),
            "Generated Premium": _fake_triangle("Generated Premium", "Generated Premium"),
        })
        published = []
        waited = []
        preflight_roots = []
        events = []

        def publish(job, *, check_workers=True):
            self.assertFalse(check_workers)
            published.append(job)
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            job.output_path.write_text("1,2\n", encoding="utf-8")
            return job.request_path

        def wait(job, **_kwargs):
            self.assertEqual(len(published), 2)
            waited.append(job)
            return job.output_path

        self.module.publish_engine_request = publish
        self.module.wait_for_engine_request = wait
        self.module.require_running_engine_instances = (
            lambda root: preflight_roots.append(Path(root)) or (Path("worker.json"),)
        )
        value_reads = []

        def read_resq_values(triangle, **_kwargs):
            # ResQ values are read only for the comparison: after every request
            # was published and after this dataset's own Engine result arrived.
            self.assertEqual(len(published), 2)
            self.assertGreater(len(waited), len(value_reads))
            value_reads.append(triangle.Name)
            return {"values": [[1.0, 2.0]]}

        self.module.export_triangle = read_resq_values

        written, errors = self.module.export_triangles_for_rc(
            rc,
            r"Auto\PP",
            self.rc_dir,
            triangle_names=["Paid Loss", "Generated Premium"],
            engine_provenance=self.provenance,
            progress_callback=events.append,
            verbose=False,
        )

        self.assertEqual((written, errors), (2, 0))
        self.assertEqual(len(published), 2)
        self.assertEqual(len(waited), 2)
        self.assertEqual(value_reads, ["Paid Loss", "Generated Premium"])
        self.assertEqual([e["status"] for e in events if e.get("event") == "finish"], ["success", "success"])
        self.assertEqual(preflight_roots, [self.root])
        self.assertTrue((self.datasets_dir / "Paid Loss@12@12@cum@dev.csv").is_file())
        messages = [str(event.get("message") or "") for event in events]
        self.assertIn("Submitting 2 generated dataset(s) to Arco Engine...", messages)
        self.assertIn("Submitted generated dataset 2 of 2: Generated Premium", messages)
        self.assertIn("Waiting for Arco Engine result 1 of 2: Paid Loss", messages)
        self.assertIn("Waiting for Arco Engine result 2 of 2: Generated Premium", messages)

    def test_resq_inventory_reports_live_discovered_counts_before_total(self) -> None:
        events = []
        rc = _FakeReservingClass({
            "Paid Loss": _fake_triangle("Paid Loss", "Paid Loss"),
            "Reported Loss": _fake_triangle("Reported Loss", "Reported Loss"),
        })

        names, _items, _method_types = self.module._triangle_export_inventory(
            rc,
            events.append,
        )

        self.assertEqual(names, ["Paid Loss", "Reported Loss"])
        self.assertEqual(
            [event["message"] for event in events],
            ["Scanning ResQ triangles: 1 found", "Scanning ResQ triangles: 2 found"],
        )
        self.assertTrue(all("total" not in event for event in events))

    def test_engine_result_that_differs_from_resq_is_kept_with_a_warning(self) -> None:
        rc = _FakeReservingClass({"Paid Loss": _fake_triangle("Paid Loss", "Paid Loss")})
        events = []

        def publish(job, *, check_workers=True):
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            job.output_path.write_text("100,200.004\n300,\n", encoding="utf-8")
            return job.request_path

        self.module.publish_engine_request = publish
        self.module.wait_for_engine_request = lambda job, **_kwargs: job.output_path
        self.module.require_running_engine_instances = lambda root: (Path("worker.json"),)
        # 200.004 agrees at two decimals; 300 versus 300.01 does not; a blank
        # against a number is a disagreement too.
        self.module.export_triangle = lambda *_a, **_k: {"values": [[100, 200], [300.01, 5]]}
        progress_state = {"completed": 0, "total": 1}

        written, errors = self.module.export_triangles_for_rc(
            rc,
            r"Auto\PP",
            self.rc_dir,
            progress_state=progress_state,
            triangle_names=["Paid Loss"],
            engine_provenance=self.provenance,
            progress_callback=events.append,
            verbose=False,
        )

        self.assertEqual((written, errors), (1, 0))
        self.assertTrue((self.datasets_dir / "Paid Loss@12@12@cum@dev.csv").is_file())
        self.assertEqual(progress_state["engine_parity_mismatches"], 1)
        warning = progress_state["engine_parity_warnings"][0]
        self.assertEqual((warning["kind"], warning["name"]), ("triangle", "Paid Loss"))
        self.assertEqual(
            warning["message"],
            "2 cell(s) differ from ResQ at 2 decimal places; first at origin 2, development 1: "
            "ResQ 300.01, Arco Engine 300.00.",
        )
        finish = [e for e in events if e.get("event") == "finish"][0]
        self.assertEqual(finish["status"], "warning")
        self.assertIn(warning["message"], finish["message"])

    def test_a_comparison_that_cannot_be_made_is_a_warning_not_an_error(self) -> None:
        rc = _FakeReservingClass({"Paid Loss": _fake_triangle("Paid Loss", "Paid Loss")})

        def publish(job, *, check_workers=True):
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            job.output_path.write_text("1\n", encoding="utf-8")
            return job.request_path

        self.module.publish_engine_request = publish
        self.module.wait_for_engine_request = lambda job, **_kwargs: job.output_path
        self.module.require_running_engine_instances = lambda root: (Path("worker.json"),)

        def unreadable(*_a, **_k):
            raise RuntimeError("COM read failed")

        self.module.export_triangle = unreadable
        progress_state = {"completed": 0, "total": 1}

        written, errors = self.module.export_triangles_for_rc(
            rc,
            r"Auto\PP",
            self.rc_dir,
            progress_state=progress_state,
            triangle_names=["Paid Loss"],
            engine_provenance=self.provenance,
            verbose=False,
        )

        self.assertEqual((written, errors), (1, 0))
        self.assertEqual(
            progress_state["engine_parity_warnings"][0]["message"],
            "Could not be compared with ResQ: COM read failed",
        )

    def test_generated_vector_reads_resq_values_only_for_the_comparison(self) -> None:
        vector = types.SimpleNamespace(
            Name="Generated Premium",
            DatasetType=types.SimpleNamespace(
                Name="Generated Premium",
                Category=types.SimpleNamespace(Name="Premium"),
                DataFormat=1,
            ),
            MethodType=0,
            PeriodLength=6,
        )
        reserving_class = types.SimpleNamespace(
            Vectors=lambda: _FakeCollection({"Generated Premium": vector}),
        )

        def publish(job, *, check_workers=True):
            self.assertFalse(check_workers)
            job.output_path.parent.mkdir(parents=True, exist_ok=True)
            job.output_path.write_text("10\n", encoding="utf-8")
            return job.request_path

        self.module.publish_engine_request = publish
        self.module.wait_for_engine_request = lambda job, **_kwargs: job.output_path
        value_reads = []

        def read_resq_values(item, **_kwargs):
            self.assertTrue((self.datasets_dir / "Generated Premium@6.csv").is_file())
            value_reads.append(item.Name)
            return {"values": [[10]]}

        self.module.export_vector = read_resq_values
        progress_state = {"completed": 0, "total": 1}

        written, errors = self.module.export_vectors_for_rc(
            reserving_class,
            r"Auto\PP",
            self.rc_dir,
            progress_state=progress_state,
            vector_names=["Generated Premium"],
            engine_provenance=self.provenance,
            verbose=False,
        )

        self.assertEqual((written, errors), (1, 0))
        self.assertEqual(value_reads, ["Generated Premium"])
        self.assertNotIn("engine_parity_warnings", progress_state)

    def test_dfm_export_does_not_request_engine_ratio_basis_generation(self) -> None:
        vector = types.SimpleNamespace(
            Name="C 12 - CWP DFM w/ Selected LDFs",
            MethodType=self.module.METHOD_TYPE_DFM_CODE,
        )
        reserving_class = types.SimpleNamespace(
            Vectors=lambda: _FakeCollection({vector.Name: vector}),
        )
        dfm = object()
        calls = []

        def export_dfm_output(_dfm, _rc_path, _rc_dir, **kwargs):
            calls.append(kwargs)
            return vector.Name, "    OK DFM", False

        with (
            patch.object(self.module, "_dfm_methods_by_output_name", return_value={vector.Name.lower(): (vector.Name, dfm)}),
            patch.object(self.module, "_export_dfm_output_dataset", side_effect=export_dfm_output),
            patch.object(self.module, "publish_engine_request") as publish,
        ):
            written, errors = self.module.export_vectors_for_rc(
                reserving_class,
                r"Auto\PP",
                self.rc_dir,
                vector_names=[vector.Name],
                include_dfm_methods=True,
                engine_available=True,
                verbose=False,
            )

        self.assertEqual((written, errors), (1, 0))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("ratio_basis_snapshot", calls[0])
        publish.assert_not_called()

    def test_no_engine_worker_stops_before_resq_import(self) -> None:
        error = self.module.EngineUnavailableError("no workers")
        with (
            patch.object(
                self.module,
                "require_running_engine_instances",
                side_effect=error,
            ),
            self.assertRaises(self.module.EngineUnavailableError),
        ):
            self.module.import_reserving_class_from_resq(
                "Demo",
                r"Auto\PP",
                server_root=self.root,
                verbose=False,
            )

    def test_bridge_mode_keeps_stored_import_when_engine_preflight_fails(self) -> None:
        """A failed engine component must not suppress stored ResQ methods."""

        reserving_class = object()
        project = types.SimpleNamespace(
            ReservingClasses=lambda: types.SimpleNamespace(
                Item=lambda _path: reserving_class
            )
        )
        application = types.SimpleNamespace(
            ConnectByName=Mock(),
            Projects=lambda: types.SimpleNamespace(Item=lambda _name: project),
            Disconnect=Mock(),
        )
        client_module = types.ModuleType("win32com.client")
        client_module.Dispatch = Mock(return_value=application)
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module
        rebuild = Mock()
        engine_error = self.module.EngineGenerationError("provenance unavailable")

        with (
            patch.dict(
                "sys.modules",
                {
                    "win32com": win32com_module,
                    "win32com.client": client_module,
                },
            ),
            patch.object(
                self.module,
                "discover_fresh_engine_heartbeats",
                return_value=(Path("worker.json"),),
            ),
            patch.object(
                self.module,
                "get_engine_processing_provenance",
                side_effect=engine_error,
            ),
            patch.object(
                self.module,
                "_selected_exports",
                return_value=(False, False, True),
            ),
            patch.object(
                self.module,
                "resq_export_dataset_counts",
                return_value={
                    "total": 0,
                    "triangles": 0,
                    "vectors": 0,
                    "dfms": 1,
                    "methods": 1,
                    "dfm_names": ["Stored DFM"],
                },
            ),
            patch.object(self.module, "export_dfms_for_rc", return_value=(1, 0)) as export_dfms,
            patch.object(self.module, "rebuild_dataset_instance_index", rebuild),
        ):
            result = self.module.import_reserving_class_from_resq(
                "Demo",
                r"Auto\PP",
                server_root=self.root,
                export_mode="dfm",
                cleanup_target=False,
                skip_unavailable_engine=True,
                verbose=False,
            )

        export_dfms.assert_called_once()
        self.assertFalse(result["engine_available"])
        self.assertEqual(result["engine_errors"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["dfms_written"], 1)
        self.assertEqual(result["error_details"][0]["kind"], "engine_preflight")
        application.Disconnect.assert_called_once_with()

    def _engine_scope_during_import(self, rc_path: str, *, resq_calculated: bool) -> bool:
        """Import *rc_path* and report whether its datasets were handed to the Engine."""

        reserving_class = types.SimpleNamespace(Calculated=resq_calculated)
        project = types.SimpleNamespace(
            ReservingClasses=lambda: types.SimpleNamespace(Item=lambda _path: reserving_class)
        )
        application = types.SimpleNamespace(
            ConnectByName=Mock(),
            Projects=lambda: types.SimpleNamespace(Item=lambda _name: project),
            Disconnect=Mock(),
        )
        client_module = types.ModuleType("win32com.client")
        client_module.Dispatch = Mock(return_value=application)
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module
        seen: list[bool] = []

        def export_triangles(*_args, **_kwargs):
            seen.append(self.catalog.engine_builds_class())
            return 0, 0

        with (
            patch.dict("sys.modules", {"win32com": win32com_module, "win32com.client": client_module}),
            patch.object(self.module, "require_running_engine_instances", return_value=(Path("worker.json"),)),
            patch.object(self.module, "get_engine_processing_provenance", return_value=self.provenance),
            patch.object(self.module, "_selected_exports", return_value=(True, False, False)),
            patch.object(
                self.module,
                "resq_export_dataset_counts",
                return_value={"total": 0, "triangles": 0, "vectors": 0, "dfms": 0, "methods": 0},
            ),
            patch.object(self.module, "export_triangles_for_rc", side_effect=export_triangles),
            patch.object(self.module, "rebuild_dataset_instance_index", Mock()),
        ):
            self.module.import_reserving_class_from_resq(
                "Demo",
                rc_path,
                server_root=self.root,
                export_mode="triangles",
                cleanup_target=False,
                verbose=False,
            )
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_engine_scope_follows_the_projects_reserving_class_types_not_resqs_flag(self) -> None:
        (self.project_dir / "field_mapping.json").write_text(json.dumps({"rows": [
            {"field_name": "LOB", "significance": "Reserving Class", "level": 1},
            {"field_name": "SUBLINE", "significance": "Reserving Class", "level": 2},
        ]}), encoding="utf-8")
        (self.project_dir / "reserving_class_types.json").write_text(json.dumps({
            "columns": ["Name", "Level", "Formula", "Source"],
            "rows": [["Auto", "1", "", "\"Auto\""], ["PP", "2", "", "\"PP\""]],
        }), encoding="utf-8")

        # ResQ calls nearly every class calculated; a class Arco can resolve still goes to the Engine.
        self.assertTrue(self._engine_scope_during_import(r"Auto\PP", resq_calculated=True))
        # A level Arco does not define (ResQ's Total) keeps ResQ's values, whatever ResQ says.
        self.assertFalse(self._engine_scope_during_import(r"Auto\Total", resq_calculated=False))
        self.assertFalse(self._engine_scope_during_import(r"Motor\PP", resq_calculated=False))

    def test_interrupted_import_rebuilds_index_after_mutation_started(self) -> None:
        reserving_class = object()
        project = types.SimpleNamespace(
            ReservingClasses=lambda: types.SimpleNamespace(
                Item=lambda _path: reserving_class
            )
        )
        application = types.SimpleNamespace(
            ConnectByName=Mock(),
            Projects=lambda: types.SimpleNamespace(Item=lambda _name: project),
            Disconnect=Mock(),
        )
        client_module = types.ModuleType("win32com.client")
        client_module.Dispatch = Mock(return_value=application)
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module
        rebuild = Mock()

        with (
            patch.dict(
                "sys.modules",
                {
                    "win32com": win32com_module,
                    "win32com.client": client_module,
                },
            ),
            patch.object(
                self.module,
                "require_running_engine_instances",
                return_value=(Path("worker.json"),),
            ),
            patch.object(
                self.module,
                "get_engine_processing_provenance",
                return_value=self.provenance,
            ),
            patch.object(
                self.module,
                "_selected_exports",
                return_value=(True, False, False),
            ),
            patch.object(
                self.module,
                "resq_export_dataset_counts",
                return_value={
                    "total": 1,
                    "triangles": 1,
                    "vectors": 0,
                    "dfms": 0,
                    "methods": 0,
                    "triangle_names": ["Paid Loss"],
                },
            ),
            patch.object(
                self.module,
                "export_triangles_for_rc",
                side_effect=RuntimeError("export interrupted"),
            ),
            patch.object(
                self.module,
                "rebuild_dataset_instance_index",
                rebuild,
            ),
            self.assertRaisesRegex(RuntimeError, "export interrupted"),
        ):
            self.module.import_reserving_class_from_resq(
                "Demo",
                r"Auto\PP",
                server_root=self.root,
                cleanup_target=False,
                verbose=False,
            )

        rebuild.assert_called_once_with("Demo", r"Auto\PP", self.rc_dir)
        application.Disconnect.assert_called_once_with()

    def test_partial_triangle_migration_hands_its_datasets_to_the_dependent_walk(self) -> None:
        reserving_class = object()
        project = types.SimpleNamespace(
            ReservingClasses=lambda: types.SimpleNamespace(Item=lambda _path: reserving_class)
        )
        application = types.SimpleNamespace(
            ConnectByName=Mock(),
            Projects=lambda: types.SimpleNamespace(Item=lambda _name: project),
            Disconnect=Mock(),
        )
        client_module = types.ModuleType("win32com.client")
        client_module.Dispatch = Mock(return_value=application)
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module

        with (
            patch.dict("sys.modules", {"win32com": win32com_module, "win32com.client": client_module}),
            patch.object(self.module, "discover_fresh_engine_heartbeats", return_value=(Path("worker.json"),)),
            patch.object(self.module, "get_engine_processing_provenance", return_value=self.provenance),
            patch.object(self.module, "_selected_exports", return_value=(True, False, False)),
            patch.object(self.module, "resq_export_dataset_counts", return_value={
                "total": 1,
                "triangles": 1,
                "vectors": 0,
                "dfms": 0,
                "methods": 0,
                "triangle_names": ["Paid Loss"],
                "triangle_items": {},
                "triangle_method_types": {},
            }),
            patch.object(self.module, "export_triangles_for_rc", return_value=(1, 0)),
            patch.object(self.module, "refresh_sidecar_graphs_for_rc", return_value=1),
            patch.object(self.module, "refresh_dfm_dependents_for_sources") as walk,
            patch.object(self.module, "rebuild_dataset_instance_index"),
        ):
            result = self.module.import_reserving_class_from_resq(
                "Demo",
                r"Auto\PP",
                server_root=self.root,
                export_mode="triangles",
                cleanup_target=False,
                skip_unavailable_engine=True,
                verbose=False,
            )

        # The walk waits for the caller's merge; the importer only names what it wrote.
        walk.assert_not_called()
        self.assertEqual(result["imported_dataset_names"], ["Paid Loss"])

    def test_full_migration_hands_triangles_and_vectors_to_the_dependent_walk(self) -> None:
        reserving_class = object()
        project = types.SimpleNamespace(
            ReservingClasses=lambda: types.SimpleNamespace(Item=lambda _path: reserving_class)
        )
        application = types.SimpleNamespace(
            ConnectByName=Mock(),
            Projects=lambda: types.SimpleNamespace(Item=lambda _name: project),
            Disconnect=Mock(),
        )
        client_module = types.ModuleType("win32com.client")
        client_module.Dispatch = Mock(return_value=application)
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module

        with (
            patch.dict("sys.modules", {"win32com": win32com_module, "win32com.client": client_module}),
            patch.object(self.module, "discover_fresh_engine_heartbeats", return_value=(Path("worker.json"),)),
            patch.object(self.module, "get_engine_processing_provenance", return_value=self.provenance),
            patch.object(self.module, "_selected_exports", return_value=(True, True, True)),
            patch.object(self.module, "resq_export_dataset_counts", return_value={
                "total": 2,
                "triangles": 1,
                "vectors": 1,
                "dfms": 1,
                "methods": 1,
                "triangle_names": ["Locally Selected Triangle"],
                "triangle_items": {},
                "triangle_method_types": {},
                "vector_names": ["Locally Selected Basis"],
                "dfm_names": ["ResQ DFM"],
            }),
            patch.object(self.module, "export_triangles_for_rc", return_value=(1, 0)),
            patch.object(self.module, "export_vectors_for_rc", return_value=(1, 0)),
            patch.object(self.module, "refresh_sidecar_graphs_for_rc", return_value=2),
            patch.object(self.module, "refresh_dfm_dependents_for_sources") as walk,
            patch.object(self.module, "rebuild_dataset_instance_index"),
        ):
            result = self.module.import_reserving_class_from_resq(
                "Demo",
                r"Auto\PP",
                server_root=self.root,
                export_mode="all",
                cleanup_target=False,
                skip_unavailable_engine=True,
                verbose=False,
            )

        walk.assert_not_called()
        self.assertEqual(
            result["imported_dataset_names"],
            ["Locally Selected Triangle", "Locally Selected Basis"],
        )

    def _write_imported_dataset(self, rc_dir: Path, name: str, rows: str) -> None:
        (rc_dir / "sidecars").mkdir(parents=True, exist_ok=True)
        (rc_dir / "datasets").mkdir(parents=True, exist_ok=True)
        csv_name = f"{name}@12.csv"
        (rc_dir / "sidecars" / f"{name}.json").write_text(
            json.dumps({"dataset_name": name, "csv_file": csv_name}),
            encoding="utf-8",
        )
        (rc_dir / "datasets" / csv_name).write_text(rows, encoding="utf-8")

    def test_the_import_walks_only_from_datasets_whose_values_changed(self) -> None:
        stage_rc = self.root / "r" / "job" / "d" / self.rc_dir.name
        self._write_imported_dataset(self.rc_dir, "Paid Loss", "1,2\n3,\n")
        self._write_imported_dataset(stage_rc, "Paid Loss", "1,2\n3,\n")
        self._write_imported_dataset(self.rc_dir, "Incurred Loss", "5,6\n7,\n")
        self._write_imported_dataset(stage_rc, "Incurred Loss", "5,6\n8,\n")
        self._write_imported_dataset(stage_rc, "New Engine", "9\n")
        imported = ["Paid Loss", "Incurred Loss", "New Engine", "Skipped"]

        with patch.object(
            self.module,
            "refresh_dfm_dependents_for_sources",
            return_value=self.module.DfmPropagationResult(("Paid DFM",), ()),
        ) as walk:
            result = self.module.refresh_import_dependents(self.rc_dir, stage_rc, r"Auto\PP", imported)

        reserving_class, changed = walk.call_args.args
        # An unchanged rebuild and a skipped item start nothing, and nothing
        # the import wrote is refreshed a second time.
        self.assertEqual(changed, ["Incurred Loss", "New Engine"])
        self.assertEqual(walk.call_args.kwargs["settled"], imported)
        self.assertEqual(reserving_class.data_dir, stage_rc)
        self.assertEqual(result.refreshed_outputs, ("Paid DFM",))

    def test_an_import_that_changed_no_values_starts_no_walk(self) -> None:
        stage_rc = self.root / "r" / "job" / "d" / self.rc_dir.name
        self._write_imported_dataset(self.rc_dir, "Paid Loss", "1,2\n3,\n")
        self._write_imported_dataset(stage_rc, "Paid Loss", "1,2\n3,\n")

        with patch.object(self.module, "refresh_dfm_dependents_for_sources") as walk:
            result = self.module.refresh_import_dependents(self.rc_dir, stage_rc, r"Auto\PP", ["Paid Loss"])

        walk.assert_not_called()
        self.assertEqual(result.refreshed_outputs, ())
        self.assertEqual(result.warnings, ())


if __name__ == "__main__":
    unittest.main()
