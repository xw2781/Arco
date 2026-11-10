from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FRONTEND_ROOT.parent
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
for candidate in (FRONTEND_ROOT, REPO_ROOT / "python-api" / "src", REPO_ROOT / "python-api" / "migration"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app_server.services import (
    arcrho_runtime_service,
    calculated_dataset_service,
    dataset_sidecar_status_service,
    user_identity_service,
)
from resq_migration import catalog, extractors


class EngineDatasetSidecarContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.root = Path(self.temp_dir.name)
        self.runtime_rc = self.root / "runtime" / "rc"
        self.migration_rc = self.root / "migration" / "rc"
        for rc_dir in (self.runtime_rc, self.migration_rc):
            (rc_dir / "datasets").mkdir(parents=True)
            (rc_dir / "sidecars").mkdir()
        self.csv_name = "Ratio@12@12@cum@dev.csv"
        self.runtime_csv = self.runtime_rc / "datasets" / self.csv_name
        self.migration_csv = self.migration_rc / "datasets" / self.csv_name
        self.runtime_csv.write_text("1,2\n3,4\n", encoding="utf-8")
        self.migration_csv.write_text("1,2\n3,4\n", encoding="utf-8")
        self.provenance = {
            "config_hash": "sha256:canonical",
            "algorithm_version": "arcrho-data-processing-v1",
            "rules_format": "arcrho-data-processing-rules-v1",
            "rules_revision": 7,
        }
        self.generated_at = "2026-07-31T23:59:00Z"
        self.created_at = "2026-07-31T23:58:00Z"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _apply_graph(payload, *_args, **_kwargs):
        payload["formula"] = ""
        payload["calculated"] = False
        payload["precedents"] = []
        payload["dependents"] = [{"name": "Downstream Ratio", "formula": '"Ratio" / "Other"'}]
        return payload

    def test_runtime_and_migration_emit_the_exact_same_engine_sidecar(self) -> None:
        runtime_sidecar = self.runtime_rc / "sidecars" / "Ratio.json"
        pairs = [
            ("ProjectName", "Demo"),
            ("Path", r"Auto\PP"),
            ("DatasetName", "Ratio"),
            ("InstanceName", "Ratio"),
            ("Function", "ArcRhoTri"),
            ("OriginLength", "12"),
            ("DevelopmentLength", "12"),
            ("Cumulative", "true"),
            ("Calendar", "false"),
        ]

        with (
            user_identity_service.acting_identity("tester", "Tester Name"),
            patch.object(arcrho_runtime_service, "utc_now_text", return_value=self.generated_at),
            patch.object(arcrho_runtime_service, "_utc_timestamp_from_stat", return_value=self.created_at),
            patch.object(arcrho_runtime_service, "_dataset_sidecar_path", return_value=str(runtime_sidecar)),
            patch.object(arcrho_runtime_service, "get_processing_provenance", return_value=self.provenance),
            patch.object(
                arcrho_runtime_service.dataset_number_format_service,
                "dataset_type_number_format_settings",
                return_value={"number_format": "0.0%", "decimal_places": 1},
            ),
            patch(
                "app_server.services.calculated_dataset_service.apply_sidecar_graph_fields",
                side_effect=self._apply_graph,
            ),
            patch.object(
                arcrho_runtime_service.dataset_sidecar_status_service,
                "refresh_method_statuses_for_dependents",
            ),
        ):
            arcrho_runtime_service._write_dataset_sidecar_impl(str(self.runtime_csv), pairs)

        runtime_payload = json.loads(runtime_sidecar.read_text(encoding="utf-8"))

        extractors.PROJECT_NAME = "Demo"
        with (
            user_identity_service.acting_identity("tester", "Tester Name"),
            patch.object(extractors, "utc_now_text", return_value=self.generated_at),
            patch.object(extractors, "_engine_cache_created_at", return_value=self.created_at),
            patch.object(extractors, "dataset_type_number_format", return_value="0.0%"),
            patch.object(extractors, "dataset_type_decimal_places", return_value=1),
            patch.object(extractors, "_apply_graph_meta_best_effort", side_effect=self._apply_graph),
        ):
            extractors.write_engine_generated_export(
                {
                    "name": "Ratio",
                    "dataset_type": "Ratio",
                    "data_format": 0,
                    "origin_length": 12,
                    "development_length": 12,
                    "origin_labels": ["wrong ResQ label"],
                    "development_labels": ["12", "24"],
                    "user": "ResQ User",
                    "created": "2000-01-01",
                    "modified": "2000-01-02",
                },
                r"Auto\PP",
                self.migration_rc,
                is_vector=False,
                provenance=self.provenance,
                csv_name=self.csv_name,
                csv_path=self.migration_csv,
            )

        migration_payload = json.loads(
            (self.migration_rc / "sidecars" / "Ratio.json").read_text(encoding="utf-8")
        )
        # The migration additionally records when the data last changed in ResQ;
        # the runtime writer has no ResQ source, so the field is migration-only.
        self.assertEqual(migration_payload.pop("source_modified"), "2000-01-02")
        self.assertEqual(migration_payload, runtime_payload)
        # Both writers stamp the configured full name of the acting user, never the login.
        self.assertEqual(runtime_payload["modified_by"], "Tester Name")
        self.assertEqual(runtime_payload["audit_log"][-1]["user"], "Tester Name")
        self.assertIs(runtime_payload["show_subtotal"], True)
        # Both writers record the shape the CSV is stored at beside the shape
        # it is displayed at; a generated dataset is stored at the shape the
        # request asked for until the field mapping records its source
        # granularity.
        self.assertEqual(runtime_payload["stored_origin_length"], 12)
        self.assertEqual(runtime_payload["stored_development_length"], 12)
        self.assertNotIn("origin_labels", migration_payload)
        self.assertNotIn("development_labels", migration_payload)
        self.assertNotIn(str(self.runtime_rc), json.dumps(runtime_payload))
        self.assertNotIn(str(self.migration_rc), json.dumps(migration_payload))


class EngineDatasetRegenerationTests(unittest.TestCase):
    """Regenerating an existing Engine dataset brings its links up to date.

    Until now a rebuild refreshed only status, timestamps, shape and cache
    name, so a dataset kept whatever links it was first written with, right or
    wrong.
    """

    ROWS = [
        {"name": "Earned Premium", "data_format": "Triangle", "calculated": False, "formula": "", "source": "Earned_Premium", "generated": True},
        {"name": "Remaining Budget Premium", "data_format": "Triangle", "calculated": False, "formula": "", "source": "Remaining_Budget_Premium", "generated": True},
        {"name": "Total Earned Premium", "data_format": "Triangle", "calculated": True, "formula": '"Earned Premium" + "Remaining Budget Premium"', "source": "Earned_Premium + Remaining_Budget_Premium", "generated": True},
    ]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.root = Path(self.temp_dir.name)
        (self.root / "datasets").mkdir(parents=True)
        (self.root / "sidecars").mkdir()
        self.csv_path = self.root / "datasets" / "Total Earned Premium@12@12@cum@dev.csv"
        self.csv_path.write_text("1,2\n3,4\n", encoding="utf-8")
        self.sidecar_path = self.root / "sidecars" / "Total Earned Premium.json"
        self.pairs = [
            ("ProjectName", "Demo"),
            ("Path", "Auto"),
            ("DatasetName", "Total Earned Premium"),
            ("InstanceName", "Total Earned Premium"),
            ("Function", "ArcRhoTri"),
            ("OriginLength", "12"),
            ("DevelopmentLength", "12"),
            ("Cumulative", "true"),
            ("Calendar", "false"),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, *, generated_at: str, graph):
        with (
            user_identity_service.acting_identity("tester", "Tester Name"),
            patch.object(arcrho_runtime_service, "utc_now_text", return_value=generated_at),
            patch.object(arcrho_runtime_service, "_utc_timestamp_from_stat", return_value="2026-09-11T00:00:00Z"),
            patch.object(arcrho_runtime_service, "_dataset_sidecar_path", return_value=str(self.sidecar_path)),
            patch.object(arcrho_runtime_service, "get_processing_provenance", return_value={"rules_revision": 7}),
            patch.object(arcrho_runtime_service, "_engine_stored_lengths", return_value=(12, 12)),
            patch.object(
                arcrho_runtime_service.dataset_number_format_service,
                "dataset_type_number_format_settings",
                return_value={"number_format": "#,##0", "decimal_places": 0},
            ),
            patch.object(
                arcrho_runtime_service.dataset_sidecar_status_service,
                "refresh_method_statuses_for_dependents",
            ),
            graph,
        ):
            arcrho_runtime_service._write_dataset_sidecar_impl(str(self.csv_path), self.pairs)
        return json.loads(self.sidecar_path.read_text(encoding="utf-8"))

    @staticmethod
    def _stale_graph(payload, *_args, **_kwargs):
        payload["precedents"] = []
        payload["dependents"] = [{"dataset_name": "D 13 - Paid DFM w/ Selected LDFs"}]
        return payload

    def test_a_regeneration_recomputes_the_links_and_changes_nothing_else(self) -> None:
        first = self._write(
            generated_at="2026-09-11T10:00:00Z",
            graph=patch(
                "app_server.services.calculated_dataset_service.apply_sidecar_graph_fields",
                side_effect=self._stale_graph,
            ),
        )

        real_graph = patch.multiple(
            calculated_dataset_service,
            _dataset_type_rows=lambda _project: [dict(row) for row in self.ROWS],
            _existing_dataset_keys=lambda _project, _rc: {
                "earned premium",
                "remaining budget premium",
                "total earned premium",
            },
        )
        def read_sidecar(path: str):
            # The dataset's own sidecar comes off disk; its method dependent is
            # the only other file the rewrite reads.
            if Path(path).name.startswith("D 13"):
                return {"method_type": "DFM", "source_kind": "dfm"}
            return json.loads(Path(path).read_text(encoding="utf-8"))

        with (
            patch.object(
                dataset_sidecar_status_service,
                "sidecar_path",
                return_value=str(self.root / "sidecars" / "D 13 - Paid DFM w Selected LDFs.json"),
            ),
            patch.object(dataset_sidecar_status_service, "read_sidecar", side_effect=read_sidecar),
        ):
            second = self._write(generated_at="2026-09-12T10:00:00Z", graph=real_graph)

        self.assertEqual(
            dataset_sidecar_status_service.entry_names(second["precedents"]),
            ["Earned Premium", "Remaining Budget Premium"],
        )
        # The method reading this dataset is still its dependent; the type
        # graph cannot re-derive a method edge.
        self.assertEqual(
            dataset_sidecar_status_service.entry_names(second["dependents"]),
            ["D 13 - Paid DFM w/ Selected LDFs"],
        )
        # Nothing else moved but what a rebuild always stamps: when it ran, who
        # ran it, and the audit line saying so.
        changed = {
            key
            for key in set(first) | set(second)
            if first.get(key) != second.get(key)
        }
        self.assertEqual(changed, {"precedents", "updated_at", "audit_log"})


class EngineFormulaLinkParityTests(unittest.TestCase):
    """Both writers give a formula the Engine builds the exact same links.

    The fake project's example: two source columns, ``Earned Premium`` (A) and
    ``Remaining Budget Premium`` (C), and the formula over them, ``Total Earned
    Premium`` (B). The app server writes one set of sidecars, the ResQ import
    writes another under a different path spelling, and the parsed payloads
    must match.
    """

    A = "Earned Premium"
    C = "Remaining Budget Premium"
    B = "Total Earned Premium"
    ROWS = [
        {"name": A, "data_format": "Triangle", "category": "Premium", "calculated": False, "formula": "", "source": "Earned_Premium", "generated": True},
        {"name": C, "data_format": "Triangle", "category": "Premium", "calculated": False, "formula": "", "source": "Remaining_Budget_Premium", "generated": True},
        {"name": B, "data_format": "Triangle", "category": "Premium", "calculated": True, "formula": f'"{A}" + "{C}"', "source": "Earned_Premium + Remaining_Budget_Premium", "generated": True},
    ]
    RESERVING_CLASS = r"Auto\PP"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.root = Path(self.temp_dir.name)
        # Two spellings of the same reserving class, so a path can never leak
        # into either payload and still let them compare equal.
        self.runtime_rc = self.root / "R" / "Arco Server" / "projects" / "Demo" / "data" / "Auto_%5C_PP"
        self.migration_root = self.root / "a much longer server root" / "Arco Server"
        self.migration_rc = self.migration_root / "projects" / "Demo" / "data" / "Auto_%5C_PP"
        for rc_dir in (self.runtime_rc, self.migration_rc):
            (rc_dir / "datasets").mkdir(parents=True)
            (rc_dir / "sidecars").mkdir()
            for name in (self.A, self.C, self.B):
                (rc_dir / "datasets" / f"{name}@12@12@cum@dev.csv").write_text("1,2\n3,4\n", encoding="utf-8")
        (self.migration_root / "projects" / "Demo").mkdir(parents=True, exist_ok=True)
        (self.migration_root / "projects" / "Demo" / "dataset_types.json").write_text(json.dumps({
            "columns": ["Name", "Data Format", "Category", "Calculated", "Formula", "Source", "Generated"],
            "rows": [
                [row["name"], row["data_format"], row["category"], row["calculated"], row["formula"], row["source"], row["generated"]]
                for row in self.ROWS
            ],
        }), encoding="utf-8")
        self.provenance = {"config_hash": "sha256:canonical", "rules_revision": 7}
        self.generated_at = "2026-09-12T12:00:00Z"
        self.created_at = "2026-09-12T11:00:00Z"
        self.catalog_state = (catalog.SERVER_ROOT, catalog.PROJECT_NAME)
        catalog.configure_catalog(
            server_root=self.migration_root,
            project_name="Demo",
            rs_json_format=catalog.RS_JSON_FORMAT,
            method_data_dir=catalog.METHOD_DATA_DIR,
        )
        self.extractors_project = extractors.PROJECT_NAME
        extractors.PROJECT_NAME = "Demo"

    def tearDown(self) -> None:
        catalog.SERVER_ROOT, catalog.PROJECT_NAME = self.catalog_state
        extractors.PROJECT_NAME = self.extractors_project
        self.temp_dir.cleanup()

    def _runtime_payload(self, name: str) -> dict:
        csv_path = self.runtime_rc / "datasets" / f"{name}@12@12@cum@dev.csv"
        sidecar_path = self.runtime_rc / "sidecars" / f"{name}.json"
        pairs = [
            ("ProjectName", "Demo"),
            ("Path", self.RESERVING_CLASS),
            ("DatasetName", name),
            ("InstanceName", name),
            ("Function", "ArcRhoTri"),
            ("OriginLength", "12"),
            ("DevelopmentLength", "12"),
            ("Cumulative", "true"),
            ("Calendar", "false"),
        ]
        with (
            user_identity_service.acting_identity("tester", "Tester Name"),
            patch.object(arcrho_runtime_service, "utc_now_text", return_value=self.generated_at),
            patch.object(arcrho_runtime_service, "_utc_timestamp_from_stat", return_value=self.created_at),
            patch.object(arcrho_runtime_service, "_dataset_sidecar_path", return_value=str(sidecar_path)),
            patch.object(arcrho_runtime_service, "get_processing_provenance", return_value=self.provenance),
            patch.object(arcrho_runtime_service, "_engine_stored_lengths", return_value=(12, 12)),
            patch.object(
                arcrho_runtime_service.dataset_number_format_service,
                "dataset_type_number_format_settings",
                return_value={"number_format": "#,##0", "decimal_places": 0},
            ),
            patch.object(
                arcrho_runtime_service.dataset_sidecar_status_service,
                "refresh_method_statuses_for_dependents",
            ),
            patch.multiple(
                calculated_dataset_service,
                _dataset_type_rows=lambda _project: [dict(row) for row in self.ROWS],
                _existing_dataset_keys=lambda _project, _rc: {
                    calculated_dataset_service._canon_dataset_name(item)
                    for item in (self.A, self.C, self.B)
                },
            ),
        ):
            arcrho_runtime_service._write_dataset_sidecar_impl(str(csv_path), pairs)
        return json.loads(sidecar_path.read_text(encoding="utf-8"))

    def _migration_payload(self, name: str) -> dict:
        csv_name = f"{name}@12@12@cum@dev.csv"
        with (
            user_identity_service.acting_identity("tester", "Tester Name"),
            patch.object(extractors, "utc_now_text", return_value=self.generated_at),
            patch.object(extractors, "_engine_cache_created_at", return_value=self.created_at),
            patch.object(extractors, "dataset_type_number_format", return_value="#,##0"),
            patch.object(extractors, "dataset_type_decimal_places", return_value=0),
        ):
            extractors.write_engine_generated_export(
                {
                    "name": name,
                    "dataset_type": name,
                    "data_format": 0,
                    "origin_length": 12,
                    "development_length": 12,
                    "stored_origin_length": 12,
                    "stored_development_length": 12,
                },
                self.RESERVING_CLASS,
                self.migration_rc,
                is_vector=False,
                provenance=self.provenance,
                csv_name=csv_name,
                csv_path=self.migration_rc / "datasets" / csv_name,
            )
        return json.loads((self.migration_rc / "sidecars" / f"{name}.json").read_text(encoding="utf-8"))

    def test_the_import_writes_the_same_formula_links_as_the_app(self) -> None:
        for name in (self.A, self.C, self.B):
            with self.subTest(dataset=name):
                runtime_payload = self._runtime_payload(name)
                migration_payload = self._migration_payload(name)
                self.assertEqual(migration_payload, runtime_payload)
                self.assertNotIn(str(self.runtime_rc), json.dumps(runtime_payload))
                self.assertNotIn(str(self.migration_rc), json.dumps(migration_payload))

        # The formula reads its two source columns, and each of them is read by
        # the formula.
        total = json.loads((self.migration_rc / "sidecars" / f"{self.B}.json").read_text(encoding="utf-8"))
        self.assertEqual(dataset_sidecar_status_service.entry_names(total["precedents"]), [self.A, self.C])
        self.assertEqual(total["dependents"], [])
        for name in (self.A, self.C):
            payload = json.loads((self.migration_rc / "sidecars" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["precedents"], [])
            self.assertEqual(dataset_sidecar_status_service.entry_names(payload["dependents"]), [self.B])


if __name__ == "__main__":
    unittest.main()
