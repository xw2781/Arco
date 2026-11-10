from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
MIGRATION_ROOT = REPOSITORY_ROOT / "python-api" / "migration"
for import_root in (MIGRATION_ROOT, PYTHON_API_SRC, FRONTEND_ROOT):
    import_path = str(import_root)
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from fastapi import HTTPException

from app_server import config
from app_server.services import dataset_instance_index_service, dependent_propagation_service
from arcrho_api import ArcRhoClient
from arcrho_api import dataset_index_contract
from arcrho_api.dataset_index_contract import (
    DATASET_INDEX_VERSION,
    FORBIDDEN_INDEX_ROW_FIELDS,
    INDEX_ROW_FIELDS,
    normalize_cached_dataset_name,
)
from resq_migration import catalog


_TEST_TEMP_ROOT = FRONTEND_ROOT / "tests" / "logs" / "tmp"
_FIXED_MTIME_NS = 1_767_225_600_000_000_000
_FIXTURE_FORBIDDEN_FIELDS = {
    "origin_labels",
    "precedents",
    "dependents",
    "audit_log",
    "external_links",
    "calculated",
}


class DatasetIndexCrossComponentContractTests(unittest.TestCase):
    project_name = "Demo"
    reserving_class = r"Auto\PP"

    def setUp(self) -> None:
        _TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(_TEST_TEMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)

        self.server_root = Path(self.temp_dir.name) / "Arco Server"
        self.projects_dir = self.server_root / "projects"
        self.project_dir = self.projects_dir / self.project_name
        self.rc_dir = self.project_dir / "data" / "Auto_%5C_PP"
        self.datasets_dir = self.rc_dir / "datasets"
        self.methods_dir = self.rc_dir / "methods"
        self.sidecars_dir = self.rc_dir / "sidecars"
        self.datasets_dir.mkdir(parents=True)
        self.methods_dir.mkdir()
        self.sidecars_dir.mkdir()

        old_catalog_config = {
            "server_root": catalog.SERVER_ROOT,
            "project_name": catalog.PROJECT_NAME,
            "rs_json_format": catalog.RS_JSON_FORMAT,
            "method_data_dir": catalog.METHOD_DATA_DIR,
        }
        self.addCleanup(catalog.configure_catalog, **old_catalog_config)
        catalog.configure_catalog(
            server_root=self.server_root,
            project_name=self.project_name,
            rs_json_format="arcrho-result-selection-v4",
            method_data_dir="methods",
        )

        self._write_project_metadata()
        self._write_index_source_fixture()

    @property
    def index_path(self) -> Path:
        return self.rc_dir / "index.json"

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.utime(path, ns=(_FIXED_MTIME_NS, _FIXED_MTIME_NS))

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        os.utime(path, ns=(_FIXED_MTIME_NS, _FIXED_MTIME_NS))

    def _write_project_metadata(self) -> None:
        dataset_types = {
            "columns": [
                "Name",
                "Data Format",
                "Category",
                "Calculated",
                "Formula",
                "Source",
                "Generated",
            ],
            "rows": [
                ["Paid Loss", "Triangle", "Loss", False, "", "", False],
                [
                    "Projected Premium",
                    "Vector",
                    "Premium",
                    True,
                    '"Written Premium" * 1.05',
                    "",
                    False,
                ],
                ["Ultimate Loss", "Vector", "Ultimate", False, "", "", False],
                ["Selected Ultimate", "Vector", "Ultimate", False, "", "", False],
                ["BF Ultimate", "Vector", "Ultimate", False, "", "", False],
                ["CC Ultimate", "Vector", "Ultimate", False, "", "", False],
                ["BST Ultimate", "Vector", "Ultimate", False, "", "", False],
                ["SCON Ultimate", "Vector", "Ultimate", False, "", "", False],
                ["Adjusted Paid", "Triangle", "Loss", False, "", "", False],
            ],
        }
        self._write_json(self.project_dir / "dataset_types.json", dataset_types)
        self._write_json(
            self.server_root / "config" / "username_index.json",
            {
                "users": [
                    {
                        "login_name": "migration_user",
                        "full_name": "Migration User",
                    }
                ]
            },
        )

    def _write_index_source_fixture(self) -> None:
        common_forbidden_metadata = {
            "origin_labels": ["2024", "2025"],
            "precedents": ["Written Premium"],
            "dependents": ["Selected Ultimate"],
            "audit_log": [{"action": "migration"}],
            "external_links": [{"label": "Source workbook", "target": "book.xlsx"}],
            "calculated": False,
        }
        self._write_text(
            self.datasets_dir / "Paid Loss@12@24@cum@dev.csv",
            "Origin,12,24\n2024,100,150\n2025,125,\n",
        )
        self._write_json(
            self.sidecars_dir / "Paid Loss.json",
            {
                "dataset_name": "Paid Loss",
                "dataset_type": "Paid Loss",
                "dataset_category": "Loss",
                "source_kind": "input",
                "method_type": "None",
                "data_format": "Triangle",
                "origin_length": 12,
                "development_length": 24,
                # Entered monthly by origin and quarterly by development, then
                # displayed annually: the stored pair differs from the display
                # pair on both axes, and independently.
                "stored_origin_length": 1,
                "stored_development_length": 12,
                "status": 0,
                "user": "migration_user",
                "created": "2026-01-01T01:02:03",
                "last_modified": "2026-01-02T03:04:05",
                **common_forbidden_metadata,
            },
        )

        self._write_text(
            self.datasets_dir / "Projected Premium@12.csv",
            "Origin,Value\n2024,1000\n2025,1100\n",
        )
        self._write_json(
            self.sidecars_dir / "Projected Premium.json",
            {
                "dataset_name": "Projected Premium",
                "dataset_type": "Projected Premium",
                "dataset_category": "Premium",
                "source_kind": "calculated",
                "method_type": "None",
                "data_format": "Vector",
                "period_length": 12,
                "stored_period_length": 3,
                "status": 0,
                "formula": '"Written Premium" * 1.05',
                "calculated": True,
                "origin_labels": ["2024", "2025"],
            },
        )

        self._write_json(
            self.methods_dir / "DFM@Paid Development Method.json",
            {
                "json_format": "arcrho-dfm-method-by-tab-v1",
                "details_tab": {
                    "name": "Paid Development Method",
                    "output_dataset": "Paid DFM Ultimate",
                    "output_type": "Ultimate Loss",
                    "output_category": "Ultimate",
                },
                "data_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_text(
            self.datasets_dir / "Paid DFM Ultimate@12.csv",
            "Origin,Value\n2024,175\n2025,200\n",
        )
        self._write_json(
            self.sidecars_dir / "Paid DFM Ultimate.json",
            {
                "dataset_name": "Paid DFM Ultimate",
                "dataset_type": "Ultimate Loss",
                "source_kind": "dfm",
                "method_type": "DFM",
                "data_format": "Vector",
                "period_length": 12,
                "status": 2,
            },
        )
        for method_name in ("Frontend DFM A", "Frontend DFM B"):
            self._write_json(
                self.methods_dir / f"DFM@{method_name}.json",
                {
                    "json_format": "arcrho-dfm-method-by-tab-v1",
                    "details_tab": {
                        "name": method_name,
                        "output_type": "Ultimate Loss",
                    },
                },
            )
        self._write_json(
            self.methods_dir / "RS@Selected Ultimate.json",
            {
                "json_format": "arcrho-result-selection-v4",
                "details_tab": {
                    "name": "Selected Ultimate",
                    "output_type": "Selected Ultimate",
                    "dataset_category": "Ultimate",
                },
                "method_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_json(
            self.methods_dir / "BF@BF Ultimate.json",
            {
                "json_format": "arcrho-bornhuetter-ferguson-v4",
                "details_tab": {
                    "name": "BF Ultimate",
                    "output_type": "BF Ultimate",
                    "dataset_category": "Ultimate",
                },
                "method_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_json(
            self.methods_dir / "CC@CC Ultimate.json",
            {
                "json_format": "arcrho-cape-cod-v4",
                "details_tab": {
                    "name": "CC Ultimate",
                    "output_type": "CC Ultimate",
                    "dataset_category": "Ultimate",
                },
                "method_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_json(
            self.methods_dir / "BST@BST Ultimate.json",
            {
                "json_format": "arcrho-bootstrap-v4",
                "details_tab": {
                    "name": "BST Ultimate",
                    "output_type": "BST Ultimate",
                    "dataset_category": "Ultimate",
                },
                "results_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_json(
            self.methods_dir / "SCON@SCON Ultimate.json",
            {
                "json_format": "arcrho-stochastic-consolidation-v4",
                "details_tab": {
                    "name": "SCON Ultimate",
                    "output_type": "SCON Ultimate",
                    "dataset_category": "Ultimate",
                },
                "segments_tab": {
                    "segments": [
                        {"reserving_class": "Other\\Class", "method_name": "BST Ultimate", "factor": 1},
                    ],
                },
                "results_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )
        self._write_json(
            self.methods_dir / "BSSR@Adjusted Paid.json",
            {
                "json_format": "arcrho-berquist-sherman-sr-v4",
                "details_tab": {
                    "name": "Adjusted Paid",
                    "output_type": "Adjusted Paid",
                    "dataset_category": "Loss",
                    "origin_length": 12,
                    "development_length": 24,
                },
                "method_tab": {
                    "origin_labels": ["2024", "2025"],
                },
            },
        )

    @contextmanager
    def _frontend_workspace(self):
        with (
            mock.patch.object(config, "PROJECT_SETTINGS_DIR", str(self.projects_dir)),
            mock.patch.object(config, "get_root_path", return_value=str(self.server_root)),
            # A test run has no Gateway to ask whether the class is busy
            # (arcrho_api.gateway_test_guard); nothing holds this one.
            mock.patch.object(
                dependent_propagation_service, "get_reserving_class_busy", return_value={"ok": True, "busy": False}
            ),
        ):
            yield

    def _migration_rebuild(self) -> tuple[dict, str]:
        rebuilt_path = catalog.rebuild_dataset_instance_index(
            self.project_name,
            self.reserving_class,
            self.rc_dir,
        )
        self.assertEqual(rebuilt_path, self.index_path)
        text = self.index_path.read_text(encoding="utf-8")
        return json.loads(text), text

    def _assert_minimal_rows(self, payload: dict) -> None:
        rows = payload["files"]
        self.assertEqual(
            {row["name"] for row in rows},
            {
                "Adjusted Paid",
                "BF Ultimate",
                "BST Ultimate",
                "CC Ultimate",
                "Frontend DFM A",
                "Frontend DFM B",
                "Paid DFM Ultimate",
                "Paid Loss",
                "Projected Premium",
                "SCON Ultimate",
                "Selected Ultimate",
            },
        )
        self.assertNotIn("Paid Development Method", {row["name"] for row in rows})
        scon_row = next(row for row in rows if row["name"] == "SCON Ultimate")
        self.assertEqual(scon_row["method_type"], "Stochastic Consolidation")
        self.assertEqual(scon_row["source_kind"], "stochastic_consolidation")
        self.assertEqual(scon_row["data_format"], "Vector")
        dfm_row = next(
            row for row in rows if row["name"] == "Paid DFM Ultimate"
        )
        self.assertEqual(dfm_row["dataset_type"], "Ultimate Loss")
        self.assertEqual(dfm_row["method_name"], "Paid Development Method")
        self.assertEqual(dfm_row["status"], 2)
        frontend_dfm_rows = [
            row for row in rows if row["name"].startswith("Frontend DFM ")
        ]
        self.assertEqual(
            [row["name"] for row in frontend_dfm_rows],
            ["Frontend DFM A", "Frontend DFM B"],
        )
        self.assertEqual(
            [row.get("method_name", row["name"]) for row in frontend_dfm_rows],
            ["Frontend DFM A", "Frontend DFM B"],
        )
        self.assertTrue(all("method_name" not in row for row in frontend_dfm_rows))
        # The stored shape is projected beside the display shape, per axis, and
        # a vector's single stored period lands under the origin column its
        # display period already uses.
        triangle_row = next(row for row in rows if row["name"] == "Paid Loss")
        self.assertEqual(
            (
                triangle_row["origin_length"],
                triangle_row["development_length"],
                triangle_row["stored_origin_length"],
                triangle_row["stored_development_length"],
            ),
            (12, 24, 1, 12),
        )
        vector_row = next(row for row in rows if row["name"] == "Projected Premium")
        self.assertEqual(vector_row["origin_length"], 12)
        self.assertEqual(vector_row["stored_origin_length"], 3)
        self.assertNotIn("stored_development_length", vector_row)
        # A method computes its output at its own period, so what it publishes
        # is stored at the shape it is displayed at.
        method_row = next(row for row in rows if row["name"] == "Adjusted Paid")
        self.assertEqual(
            (
                method_row["stored_origin_length"],
                method_row["stored_development_length"],
            ),
            (method_row["origin_length"], method_row["development_length"]),
        )
        for row in rows:
            with self.subTest(dataset=row["name"]):
                self.assertLessEqual(set(row), set(INDEX_ROW_FIELDS))
                self.assertTrue(set(row).isdisjoint(FORBIDDEN_INDEX_ROW_FIELDS))
                self.assertTrue(set(row).isdisjoint(_FIXTURE_FORBIDDEN_FIELDS))
                self.assertFalse(
                    {
                        key.casefold()
                        for key in row
                    }
                    & {key.casefold() for key in _FIXTURE_FORBIDDEN_FIELDS}
                )
                self.assertFalse(
                    any(isinstance(value, (dict, list)) for value in row.values()),
                    f"index row contains structured detail data: {row}",
                )
                for timestamp_field in ("last_modified", "created"):
                    timestamp = row.get(timestamp_field)
                    if timestamp:
                        self.assertTrue(
                            timestamp.endswith("Z"),
                            f"{timestamp_field} must carry an explicit UTC marker: {row}",
                        )

    def test_legacy_two_length_only_name_remains_a_literal_instance_name(self) -> None:
        self.assertEqual(
            normalize_cached_dataset_name("Legacy Name@12@24"),
            "Legacy Name@12@24",
        )

    def test_canonical_builder_enumerates_network_folders_concurrently(self) -> None:
        original_enumerate = dataset_index_contract._enumerate_folder
        active = 0
        max_active = 0
        activity_lock = threading.Lock()

        def slow_enumerate(*args):
            nonlocal active, max_active
            with activity_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.01)
                return original_enumerate(*args)
            finally:
                with activity_lock:
                    active -= 1

        with mock.patch.object(
            dataset_index_contract,
            "_enumerate_folder",
            side_effect=slow_enumerate,
        ):
            dataset_index_contract.build_dataset_index_payload(
                self.project_name,
                self.reserving_class,
                self.rc_dir,
                max_workers=4,
            )

        self.assertGreater(max_active, 1)

    def test_canonical_builder_reads_independent_json_files_concurrently(self) -> None:
        original_read = dataset_index_contract._safe_read_json
        active = 0
        max_active = 0
        activity_lock = threading.Lock()

        def slow_read(path):
            nonlocal active, max_active
            with activity_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.01)
                return original_read(path)
            finally:
                with activity_lock:
                    active -= 1

        with mock.patch.object(
            dataset_index_contract,
            "_safe_read_json",
            side_effect=slow_read,
        ):
            payload = dataset_index_contract.build_dataset_index_payload(
                self.project_name,
                self.reserving_class,
                self.rc_dir,
                max_workers=4,
            )

        self._assert_minimal_rows(payload)
        self.assertGreater(max_active, 1)

    def test_migration_and_frontend_emit_identical_minimal_index_json(self) -> None:
        migration_payload, migration_text = self._migration_rebuild()
        self.assertEqual(migration_payload["version"], DATASET_INDEX_VERSION)
        self._assert_minimal_rows(migration_payload)

        with self._frontend_workspace():
            frontend_response = dataset_instance_index_service.rebuild_index(
                self.project_name,
                self.reserving_class,
            )

        frontend_text = self.index_path.read_text(encoding="utf-8")
        frontend_payload = json.loads(frontend_text)
        self._assert_minimal_rows(frontend_payload)
        self.assertEqual(frontend_payload, migration_payload)
        self.assertEqual(frontend_text, migration_text)

        persisted_response = dict(frontend_response)
        self.assertTrue(persisted_response.pop("index_persisted"))
        self.assertEqual(persisted_response.pop("index_warning"), "")
        self.assertEqual(persisted_response.pop("index_rebuild_reason"), "explicit-rebuild")
        self.assertTrue(persisted_response.pop("index_rebuilt"))
        self.assertGreaterEqual(persisted_response.pop("index_elapsed_ms"), 0)
        # Response-only staleness baseline: the just-written file's own stat.
        self.assertEqual(
            persisted_response.pop("index_signature"),
            dataset_instance_index_service._index_signature_of(str(self.index_path)),
        )
        self.assertEqual(
            persisted_response.pop("index_file_name"),
            dataset_index_contract.INDEX_FILE_NAME,
        )
        response_paths = persisted_response.pop("folder_paths")
        self.assertEqual(
            os.path.normcase(os.path.abspath(response_paths["data"])),
            os.path.normcase(os.path.abspath(self.rc_dir)),
        )
        self.assertNotIn("folder_paths", migration_payload)
        self.assertEqual(persisted_response, migration_payload)

    def test_python_api_emits_the_same_canonical_index_json(self) -> None:
        migration_payload, migration_text = self._migration_rebuild()
        self.index_path.unlink()

        refs = (
            ArcRhoClient(self.server_root)
            .project(self.project_name.lower())
            .rebuild_dfm_index()
        )

        self.assertEqual(
            [item.name for item in refs],
            ["Frontend DFM A", "Frontend DFM B", "Paid Development Method"],
        )
        api_text = self.index_path.read_text(encoding="utf-8")
        api_payload = json.loads(api_text)
        self._assert_minimal_rows(api_payload)
        self.assertEqual(api_payload, migration_payload)
        self.assertEqual(api_text, migration_text)

    def test_python_api_lowercase_reserving_class_keeps_filesystem_identity(self) -> None:
        migration_payload, migration_text = self._migration_rebuild()
        self.index_path.unlink()

        index_path = (
            ArcRhoClient(self.server_root)
            .project(self.project_name.lower())
            .rebuild_reserving_class_index(self.reserving_class.lower())
        )

        self.assertEqual(
            os.path.normcase(os.path.abspath(index_path)),
            os.path.normcase(os.path.abspath(self.index_path)),
        )
        api_text = self.index_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(api_text), migration_payload)
        self.assertEqual(api_text, migration_text)

    def test_migration_lowercase_alias_keeps_filesystem_identity(self) -> None:
        migration_payload, migration_text = self._migration_rebuild()
        self.index_path.unlink()

        catalog.rebuild_dataset_instance_index(
            self.project_name.lower(),
            self.reserving_class.lower(),
            self.rc_dir,
        )

        alias_text = self.index_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(alias_text), migration_payload)
        self.assertEqual(alias_text, migration_text)

    def test_payload_is_location_independent_across_drive_or_unc_aliases(self) -> None:
        alias_rc_dir = Path(self.temp_dir.name) / "UNC-alias" / "Auto_%5C_PP"
        shutil.copytree(self.rc_dir, alias_rc_dir)

        local_payload = dataset_index_contract.build_dataset_index_payload(
            self.project_name,
            self.reserving_class,
            self.rc_dir,
        )
        alias_payload = dataset_index_contract.build_dataset_index_payload(
            self.project_name,
            self.reserving_class,
            alias_rc_dir,
        )

        self.assertNotIn("folder_paths", local_payload)
        self.assertEqual(alias_payload, local_payload)

    def test_network_json_read_failure_aborts_instead_of_persisting_degraded_index(
        self,
    ) -> None:
        original_read = dataset_index_contract._safe_read_json
        blocked_path = self.methods_dir / "DFM@Paid Development Method.json"

        def fail_one_read(path):
            if Path(path) == blocked_path:
                raise PermissionError(13, "Network path unavailable", str(path))
            return original_read(path)

        with mock.patch.object(
            dataset_index_contract,
            "_safe_read_json",
            side_effect=fail_one_read,
        ):
            with self.assertRaises(PermissionError):
                dataset_index_contract.build_dataset_index_payload(
                    self.project_name,
                    self.reserving_class,
                    self.rc_dir,
                )

    def test_frontend_accepts_migration_index_without_scan_rebuild_or_write(self) -> None:
        migration_payload, migration_text = self._migration_rebuild()

        with (
            self._frontend_workspace(),
            mock.patch.object(
                dataset_instance_index_service,
                "_read_cached_metadata",
                side_effect=AssertionError("current migration index must not read payloads"),
            ) as scan,
            mock.patch.object(
                dataset_instance_index_service,
                "rebuild_index",
                side_effect=AssertionError("current migration index must not trigger a rebuild"),
            ) as rebuild,
            mock.patch.object(
                dataset_instance_index_service,
                "_write_index_file",
                side_effect=AssertionError("opening a current migration index must not write it"),
            ) as write,
            mock.patch.object(
                dataset_index_contract,
                "build_dataset_index_payload",
                side_effect=AssertionError("current migration index must not trigger a shared folder scan"),
            ) as shared_build,
        ):
            response = dataset_instance_index_service.get_index(
                self.project_name.lower(),
                self.reserving_class.lower(),
            )

        scan.assert_not_called()
        rebuild.assert_not_called()
        write.assert_not_called()
        shared_build.assert_not_called()
        self.assertEqual(self.index_path.read_text(encoding="utf-8"), migration_text)

        persisted_response = dict(response)
        self.assertTrue(persisted_response.pop("index_persisted"))
        self.assertEqual(persisted_response.pop("index_warning"), "")
        # Served straight from index.json, so the response must not claim a rebuild.
        self.assertEqual(persisted_response.pop("index_rebuild_reason"), "")
        self.assertFalse(persisted_response.pop("index_rebuilt"))
        self.assertGreaterEqual(persisted_response.pop("index_elapsed_ms"), 0)
        # Response-only staleness baseline: the untouched file's own stat.
        self.assertEqual(
            persisted_response.pop("index_signature"),
            dataset_instance_index_service._index_signature_of(str(self.index_path)),
        )
        self.assertEqual(
            persisted_response.pop("index_file_name"),
            dataset_index_contract.INDEX_FILE_NAME,
        )
        response_paths = persisted_response.pop("folder_paths")
        self.assertEqual(
            os.path.normcase(os.path.abspath(response_paths["data"])),
            os.path.normcase(os.path.abspath(self.rc_dir)),
        )
        self.assertEqual(persisted_response, migration_payload)

    def test_unchanged_folder_is_served_without_reading_any_payload(self) -> None:
        """A matching signature must not cost one open/read per sidecar and method."""

        self._migration_rebuild()

        with (
            self._frontend_workspace(),
            mock.patch.object(
                dataset_index_contract,
                "_safe_read_json",
                side_effect=AssertionError("an unchanged folder must not read payloads"),
            ) as read_payload,
            mock.patch.object(
                dataset_instance_index_service,
                "_write_index_file",
                side_effect=AssertionError("an unchanged folder must not rewrite the index"),
            ) as write,
        ):
            response = dataset_instance_index_service.get_index(
                self.project_name,
                self.reserving_class,
            )

        read_payload.assert_not_called()
        write.assert_not_called()
        self._assert_minimal_rows(response)

    def _delete(self, *dataset_names: str) -> dict:
        with self._frontend_workspace():
            return dataset_instance_index_service.delete_cached_datasets(
                self.project_name,
                self.reserving_class,
                list(dataset_names),
            )

    # The fixture's "Paid Loss" sidecar records "Selected Ultimate" as its
    # dependent, so deleting the triangle alone is refused. Tests about how a
    # delete resolves and reports its targets take the pair, which is what a
    # user with the same graph would have to select.
    PAID_LOSS_WITH_DEPENDENT = ("Paid Loss", "Selected Ultimate")

    def test_delete_refuses_a_dataset_another_object_still_uses(self) -> None:
        """An input may only be deleted once nothing reads it.

        The refusal names the dependents so the page can offer them as links;
        it must also leave every file in place, because a half-applied delete
        would strand the dependent on a source that no longer exists.
        """

        self._migration_rebuild()

        with self.assertRaises(HTTPException) as raised:
            self._delete("Paid Loss")

        self.assertEqual(raised.exception.status_code, 409)
        detail = raised.exception.detail
        self.assertEqual(
            detail["error"],
            dataset_instance_index_service.DELETE_BLOCKED_BY_DEPENDENTS,
        )
        self.assertEqual(
            detail["blocked_datasets"],
            [
                {
                    "dataset_name": "Paid Loss",
                    "dependents": [
                        {"dataset_name": "Selected Ultimate", "method_type": "None"},
                    ],
                }
            ],
        )
        # The refusal also names the full downstream chain, so the page can
        # offer deleting the selection together with everything that reads it.
        self.assertEqual(
            detail["downstream_closure"],
            [{"dataset_name": "Selected Ultimate", "method_type": "None"}],
        )
        self.assertTrue((self.datasets_dir / "Paid Loss@12@24@cum@dev.csv").exists())
        self.assertTrue((self.sidecars_dir / "Paid Loss.json").exists())

    def test_delete_allows_a_dependent_removed_in_the_same_request(self) -> None:
        """Selecting the chain leaves nothing dangling, so nothing is refused."""

        self._migration_rebuild()

        result = self._delete(*self.PAID_LOSS_WITH_DEPENDENT)

        self.assertTrue(result["ok"])
        self.assertFalse((self.datasets_dir / "Paid Loss@12@24@cum@dev.csv").exists())
        self.assertFalse((self.methods_dir / "RS@Selected Ultimate.json").exists())

    def test_delete_resolves_targets_without_reading_sidecar_payloads(self) -> None:
        """A cached CSV and a sidecar are named after their dataset.

        Opening one payload per file to learn what the directory listing already
        says costs a network round trip per file on a mapped share, which is the
        whole reason a delete used to take tens of seconds. The dependency guard
        reads sidecars, but only one per *requested* dataset -- a set the user
        chose and can see -- never one per file in the folder.
        """

        self._migration_rebuild()
        read_paths: list[str] = []
        original_read = dataset_instance_index_service._safe_read_json

        def counting_read(path: str):
            read_paths.append(os.path.normcase(os.path.abspath(path)))
            return original_read(path)

        with mock.patch.object(
            dataset_instance_index_service,
            "_safe_read_json",
            side_effect=counting_read,
        ):
            result = self._delete(*self.PAID_LOSS_WITH_DEPENDENT)

        self.assertEqual(result["deleted_count"], 3)
        self.assertFalse((self.datasets_dir / "Paid Loss@12@24@cum@dev.csv").exists())
        self.assertFalse((self.sidecars_dir / "Paid Loss.json").exists())
        sidecar_reads = {
            path for path in read_paths
            if path.startswith(os.path.normcase(os.path.abspath(self.sidecars_dir)))
        }
        # Exactly the two requested datasets, and nothing else in the folder:
        # target resolution still opens no sidecar payload at all, and the
        # guard's reads are bounded by the selection rather than by the class.
        self.assertEqual(
            sidecar_reads,
            {
                os.path.normcase(os.path.abspath(self.sidecars_dir / f"{name}.json"))
                for name in self.PAID_LOSS_WITH_DEPENDENT
            },
        )
        method_reads = [
            path for path in read_paths
            if path.startswith(os.path.normcase(os.path.abspath(self.methods_dir)))
        ]
        self.assertTrue(method_reads, "method payloads still have to be opened")
        self.assertEqual(
            len(read_paths),
            len(method_reads) + len(sidecar_reads),
            read_paths,
        )

    def test_delete_returns_the_rebuilt_index_for_the_caller(self) -> None:
        """The table applies this payload instead of paying for a second read."""

        self._migration_rebuild()
        result = self._delete(*self.PAID_LOSS_WITH_DEPENDENT)

        index = result["index"]
        self.assertTrue(index["ok"])
        self.assertNotIn("Paid Loss", {row["name"] for row in index["files"]})
        self.assertEqual(
            index["folder_signature"],
            dataset_index_contract.scan_folder_signature(self.rc_dir).signature,
        )
        self.assertEqual(
            json.loads(self.index_path.read_text(encoding="utf-8"))["files"],
            index["files"],
        )

    def test_delete_verification_pass_removes_a_file_its_filename_hides(self) -> None:
        """The filename fast path is verified against the rebuild, not trusted."""

        stray = self.sidecars_dir / "Legacy Export.json"
        self._write_json(
            stray,
            {
                "dataset_name": "Adjusted Paid",
                "dataset_type": "Adjusted Paid",
                "data_format": "Triangle",
                "source_kind": "input",
            },
        )
        self._migration_rebuild()

        result = self._delete("Adjusted Paid")

        self.assertFalse(stray.exists())
        self.assertIn(
            "Legacy Export.json",
            {item["name"] for item in result["deleted_files"]},
        )
        self.assertNotIn(
            "Adjusted Paid",
            {row["name"] for row in result["index"]["files"]},
        )

    def test_folder_listing_is_not_restatted_per_file(self) -> None:
        """The directory listing already carries size and mtime on Windows."""

        original_stat = Path.stat
        statted: list[str] = []

        def counting_stat(path_self, *args, **kwargs):
            statted.append(os.path.normcase(os.path.abspath(path_self)))
            return original_stat(path_self, *args, **kwargs)

        with mock.patch.object(Path, "stat", counting_stat):
            payload = dataset_index_contract.build_dataset_index_payload(
                self.project_name,
                self.reserving_class,
                self.rc_dir,
            )

        enumerated = {
            os.path.normcase(os.path.abspath(item.path))
            for item in dataset_index_contract.scan_folder_signature(self.rc_dir).files
        }
        self.assertTrue(enumerated)
        self.assertEqual(enumerated.intersection(statted), set())
        self._assert_minimal_rows(payload)

    def test_durable_mutation_without_an_index_update_self_heals_on_a_plain_read(
        self,
    ) -> None:
        """Another producer's write must not leave the table silently stale."""

        migration_payload, _migration_text = self._migration_rebuild()
        self.assertNotIn(
            "Late Reported Loss",
            {row["name"] for row in migration_payload["files"]},
        )

        self._write_json(
            self.sidecars_dir / "Late Reported Loss.json",
            {
                "dataset_name": "Late Reported Loss",
                "dataset_type": "Reported Loss",
                "dataset_category": "Loss",
                "data_format": "Triangle",
                "source_kind": "engine",
                "user": "another.producer",
                "last_modified": "2026-02-01T00:00:00Z",
                "created_at": "2026-02-01T00:00:00Z",
                "origin_labels": ["2024", "2025"],
            },
        )

        with self._frontend_workspace():
            response = dataset_instance_index_service.get_index(
                self.project_name,
                self.reserving_class,
            )

        self.assertIn(
            "Late Reported Loss",
            {row["name"] for row in response["files"]},
        )
        self.assertTrue(response["index_persisted"])
        persisted = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["files"], response["files"])
        self.assertNotEqual(
            persisted["folder_signature"],
            migration_payload["folder_signature"],
        )

    def test_self_healing_rebuild_enumerates_inside_the_index_lock(self) -> None:
        """The staleness check runs unlocked, so the rebuild must observe the folder again.

        Reusing the pre-lock enumeration would let a concurrent producer's write
        be dropped from the payload this rebuild persists.
        """

        self._migration_rebuild()
        self._write_json(
            self.sidecars_dir / "Late Reported Loss.json",
            {
                "dataset_name": "Late Reported Loss",
                "dataset_type": "Reported Loss",
                "data_format": "Triangle",
            },
        )

        original_enumerate = dataset_index_contract._enumerate_folder
        original_lock = dataset_instance_index_service.index_update_lock
        events: list[str] = []

        def recording_enumerate(rc_dir, folder_name):
            events.append("enumerate")
            return original_enumerate(rc_dir, folder_name)

        @contextmanager
        def recording_lock(*args, **kwargs):
            events.append("lock-acquired")
            with original_lock(*args, **kwargs):
                yield
            events.append("lock-released")

        with (
            self._frontend_workspace(),
            mock.patch.object(
                dataset_index_contract,
                "_enumerate_folder",
                side_effect=recording_enumerate,
            ),
            mock.patch.object(
                dataset_instance_index_service,
                "index_update_lock",
                recording_lock,
            ),
        ):
            dataset_instance_index_service.get_index(
                self.project_name,
                self.reserving_class,
            )

        self.assertIn("lock-acquired", events)
        locked = events[events.index("lock-acquired") : events.index("lock-released")]
        self.assertEqual(locked.count("enumerate"), 3)

    def test_get_index_resolves_canonical_identity_at_most_once_per_parent(self) -> None:
        """Each canonical name costs a parent-folder listing, so resolve it once."""

        self._migration_rebuild()
        self.index_path.unlink()

        original_canonical = dataset_instance_index_service.canonical_existing_directory
        resolved: list[str] = []

        def counting_canonical(path):
            resolved.append(os.path.normcase(os.path.abspath(path)))
            return original_canonical(path)

        with (
            self._frontend_workspace(),
            mock.patch.object(
                dataset_instance_index_service,
                "canonical_existing_directory",
                side_effect=counting_canonical,
            ),
        ):
            dataset_instance_index_service.get_index(
                self.project_name,
                self.reserving_class,
            )

        self.assertEqual(len(resolved), len(set(resolved)))
        self.assertEqual(len(resolved), 2)

    def test_refresh_still_forces_a_rebuild_when_the_folder_is_unchanged(self) -> None:
        """The forced rebuild stays available for callers that want the index rewritten."""

        self._migration_rebuild()

        with (
            self._frontend_workspace(),
            mock.patch.object(
                dataset_instance_index_service,
                "build_dataset_index_payload",
                wraps=dataset_index_contract.build_dataset_index_payload,
            ) as build,
        ):
            response = dataset_instance_index_service.get_index(
                self.project_name,
                self.reserving_class,
                refresh=True,
            )

        build.assert_called_once()
        self._assert_minimal_rows(response)

    def test_legacy_notes_migration_runs_only_when_a_legacy_file_is_present(self) -> None:
        """A one-time migration must not glob the sidecar folder on every rebuild."""

        with mock.patch.object(
            dataset_index_contract,
            "migrate_legacy_notes_files",
            side_effect=AssertionError("no legacy notes file exists in this folder"),
        ) as migrate:
            dataset_index_contract.build_dataset_index_payload(
                self.project_name,
                self.reserving_class,
                self.rc_dir,
            )
        migrate.assert_not_called()

        legacy_path = self.sidecars_dir / "ArcRhoTriNotes@Paid Loss.json"
        self._write_json(legacy_path, {"notes": "carried over"})

        payload = dataset_index_contract.build_dataset_index_payload(
            self.project_name,
            self.reserving_class,
            self.rc_dir,
        )

        self.assertFalse(legacy_path.exists())
        self.assertEqual(
            json.loads((self.sidecars_dir / "Paid Loss.json").read_text(encoding="utf-8"))["notes"],
            "carried over",
        )
        self._assert_minimal_rows(payload)
        self.assertEqual(
            payload["folder_signature"],
            dataset_index_contract.scan_folder_signature(self.rc_dir).signature,
        )


if __name__ == "__main__":
    unittest.main()
