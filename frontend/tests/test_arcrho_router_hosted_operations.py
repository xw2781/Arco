"""The /arcrho/tri*, /arcrho/vec*, and precheck routes are hosted engine-calculation operations."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = FRONTEND_ROOT.parent / "python-api" / "src"
TEST_TEMP_ROOT = FRONTEND_ROOT.parent / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
for path in (FRONTEND_ROOT, API_SOURCE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_engine_calculation_contract import (
    OPERATION_DATASET_CSV,
    OPERATION_DATASET_PRECHECK,
    OPERATION_DATASET_RUN,
    OUTPUT_VARIANT_CANONICAL,
)

import app_server.api  # noqa: F401  (registers the submodules)
arcrho_router = sys.modules["app_server.api.arcrho_router"]
from app_server import config
from app_server.helpers import set_data_path_like_vba
from app_server.schemas.arcrho import ArcRhoTriRequest, ArcRhoVecRequest
from app_server.services import (
    arcrho_runtime_service,
    calculated_dataset_service,
    dependent_propagation_service,
    engine_calculation_service,
    file_read_cache,
    project_settings_service,
)


class ArcRhoRouterHostedOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []

        def fake_operation(operation, pairs, options, *, timeout_sec, local):
            self.calls.append(
                {
                    "operation": operation,
                    "pairs": list(pairs),
                    "options": dict(options),
                    "timeout_sec": timeout_sec,
                }
            )
            return local()

        self.patches = [
            patch.object(engine_calculation_service, "run_hosted_dataset_operation", fake_operation),
            patch.object(arcrho_router, "set_data_path_like_vba", return_value="C:\\mapped\\Paid@6@6@cum@dev.csv"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    def _tri(self, **overrides) -> ArcRhoTriRequest:
        fields = {
            "ProjectName": "Demo",
            "Path": "COL",
            "TriangleName": "Paid",
            "InstanceName": "Paid",
            "Cumulative": True,
            "Calendar": False,
            "OriginLength": 6,
            "DevelopmentLength": 6,
            "timeout_sec": 15.0,
        }
        fields.update(overrides)
        return ArcRhoTriRequest(**fields)

    def test_tri_run_and_refresh_are_dataset_run_operations(self) -> None:
        seen: list[dict] = []

        def fake_run(pairs, data_path, **kwargs):
            seen.append({"pairs": pairs, "data_path": data_path, **kwargs})
            return {"ok": True, "ds_id": "x"}

        with patch.object(arcrho_runtime_service, "run_arcrho_tri", fake_run):
            arcrho_router.arcrho_tri(self._tri(WriteSidecar=False))
            arcrho_router.arcrho_tri_refresh(self._tri())
        self.assertEqual([call["operation"] for call in self.calls], [OPERATION_DATASET_RUN] * 2)
        self.assertEqual(self.calls[0]["options"]["force_refresh"], False)
        self.assertEqual(self.calls[0]["options"]["write_sidecar"], False)
        self.assertEqual(self.calls[1]["options"]["force_refresh"], True)
        self.assertEqual(self.calls[1]["options"]["write_sidecar"], True)
        self.assertEqual(self.calls[0]["timeout_sec"], 15.0)
        # The local fallback runs the canonical route with the same options.
        self.assertEqual(seen[0]["data_path"], "C:\\mapped\\Paid@6@6@cum@dev.csv")
        self.assertEqual(seen[0]["force_refresh"], False)
        self.assertEqual(seen[0]["write_sidecar"], False)
        self.assertEqual(seen[1]["force_refresh"], True)
        self.assertEqual(seen[0]["timeout_sec"], 15.0)
        self.assertEqual(dict(self.calls[0]["pairs"])["Function"], "ArcRhoTri")

    def test_vec_run_is_a_dataset_run_operation(self) -> None:
        with patch.object(arcrho_runtime_service, "run_arcrho_tri", return_value={"ok": True}):
            arcrho_router.arcrho_vec(
                ArcRhoVecRequest(
                    ProjectName="Demo", Path="COL", VectorName="Counts", Cumulative=True,
                    Calendar=False, PeriodLength=12,
                )
            )
        self.assertEqual(self.calls[0]["operation"], OPERATION_DATASET_RUN)
        self.assertEqual(dict(self.calls[0]["pairs"])["Function"], "ArcRhoVec")

    def test_precheck_is_a_dataset_precheck_operation(self) -> None:
        seen: list[dict] = []

        def fake_precheck(data_path, pairs, **kwargs):
            seen.append({"data_path": data_path, **kwargs})
            return {"ok": True, "need_request": False}

        with patch.object(arcrho_runtime_service, "arcrho_precheck", fake_precheck):
            arcrho_router.arcrho_tri_precheck(self._tri(WriteSidecar=False))
        self.assertEqual(self.calls[0]["operation"], OPERATION_DATASET_PRECHECK)
        self.assertEqual(self.calls[0]["options"]["allow_runtime_cache_provenance"], True)
        self.assertEqual(seen[0]["allow_runtime_cache_provenance"], True)
        self.assertEqual(seen[0]["local_only"], False)


class HostedDatasetCsvTests(unittest.TestCase):
    """``dataset_csv`` answers with the figures, or with the run's own failure."""

    project_name = "Example Project"
    reserving_class = "Example Reserving Class"
    dataset_name = "Paid Losses"
    # Whole numbers written the way the Engine writes them: a pandas round
    # trip would turn every one of these into ``100.0``.
    ENGINE_TEXT = "100,200,300\n400,500,\n700,,\n"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.cache_dir = root / "data" / self.reserving_class / config.DATASET_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sidecar_dir = self.cache_dir.parent / config.DATASET_SIDECAR_DIR
        self.sidecar_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.cache_dir / f"{self.dataset_name}@12@12@cum@dev.csv"
        # This project lives only in the temp folder: the dataset cache is
        # there, the dataset is not a calculated one, and the processing
        # settings a recalculated cache records provenance from are stubbed.
        for target, name, value in (
            (config, "get_project_dataset_cache_dir", str(self.cache_dir)),
            (calculated_dataset_service, "_dataset_type_rows", [{"name": self.dataset_name, "data_format": "Triangle", "generated": True}]),
            (dependent_propagation_service, "get_reserving_class_busy", {"ok": True, "busy": False}),
            (arcrho_runtime_service, "get_processing_config_hash", "processing-hash"),
            (
                arcrho_runtime_service,
                "get_processing_provenance",
                {"config_hash": "processing-hash"},
            ),
        ):
            item = patch.object(target, name, return_value=value)
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(config.DATASETS.clear)
        self.addCleanup(config.DATASET_ROLLUPS.clear)

    def _pairs(self) -> list:
        return [
            ("Function", "ArcRhoTri"),
            ("Path", self.reserving_class),
            ("DatasetName", self.dataset_name),
            ("InstanceName", self.dataset_name),
            ("ProjectName", self.project_name),
            ("Cumulative", "True"),
            ("Calendar", "False"),
            ("OriginLength", "12"),
            ("DevelopmentLength", "12"),
        ]

    def _answer(self, **options) -> dict:
        return engine_calculation_service.execute_hosted_engine_calculation(
            self._pairs(), 15.0, OUTPUT_VARIANT_CANONICAL, OPERATION_DATASET_CSV, options
        )

    def _write_csv(self, text: str) -> None:
        with open(self.csv_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def _read_csv(self) -> str:
        with open(self.csv_path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()

    def _write_sidecar(self, source_kind: str = "input") -> None:
        payload = {
            "dataset_name": self.dataset_name,
            "dataset_type": self.dataset_name,
            "reserving_class": self.reserving_class,
            "project_name": self.project_name,
            "source_kind": source_kind,
            "data_format": "Triangle",
            "csv_file": self.csv_path.name,
            "cumulative": True,
            "calendar": False,
            "origin_length": 12,
            "development_length": 12,
            "stored_origin_length": 12,
            "stored_development_length": 12,
        }
        (self.sidecar_dir / f"{self.dataset_name}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def test_a_cached_triangle_answers_with_its_figures(self) -> None:
        self._write_csv(self.ENGINE_TEXT)
        self._write_sidecar()

        answer = self._answer()

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["local_cache_status"], "cache_exact")
        self.assertFalse(answer["need_request"])
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)

    def test_refresh_leaves_a_hand_entered_dataset_alone(self) -> None:
        self._write_csv(self.ENGINE_TEXT)
        self._write_sidecar()

        def refuse(*args, **kwargs):
            raise AssertionError("A hand-entered dataset has nothing to rebuild from.")

        with patch.object(engine_calculation_service, "run_engine_calculation", refuse):
            answer = self._answer()

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["local_cache_status"], "cache_exact")
        self.assertFalse(answer["need_request"])
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)
        self.assertEqual(self._read_csv(), self.ENGINE_TEXT)

    def test_refresh_serves_a_permanent_generated_dataset_without_rebuilding(self) -> None:
        self._write_csv(self.ENGINE_TEXT)
        self._write_sidecar(source_kind="engine")
        rebuilt = "1,2,3\n4,5,\n6,,\n"

        def fake_engine(pairs, data_path, timeout_sec, **kwargs):
            with open(data_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(rebuilt)
            return {"ok": True, "status": "completed", "request_file": "r.json"}

        with patch.object(engine_calculation_service, "run_engine_calculation", fake_engine):
            answer = self._answer()

        self.assertTrue(answer["ok"])
        self.assertFalse(answer["need_request"])
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)

    def test_refresh_serves_a_method_result_as_published(self) -> None:
        # A Result Selection published this dataset. A dataset read cannot
        # produce it again, and the Engine, asked to, would answer with an
        # error and write that error over the published figures.
        self._write_csv(self.ENGINE_TEXT)
        self._write_sidecar(source_kind="result_selection")

        def refuse(*args, **kwargs):
            raise AssertionError("A method result has nothing the Engine could rebuild it from.")

        with patch.object(engine_calculation_service, "run_engine_calculation", refuse):
            answer = self._answer()

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["local_cache_status"], "cache_exact")
        self.assertFalse(answer["need_request"])
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)
        self.assertEqual(self._read_csv(), self.ENGINE_TEXT)

    def test_a_method_result_without_its_figures_is_not_asked_of_the_engine(self) -> None:
        self._write_sidecar(source_kind="result_selection")

        def refuse(*args, **kwargs):
            raise AssertionError("A method result has nothing the Engine could rebuild it from.")

        with patch.object(engine_calculation_service, "run_engine_calculation", refuse):
            answer = self._answer()

        self.assertFalse(answer["ok"])
        self.assertFalse(answer["need_request"])
        self.assertNotIn("csv_text", answer)
        self.assertIn("no published CSV", answer["message"])
        self.assertIn(self.dataset_name, answer["message"])
        self.assertFalse(self.csv_path.exists())

    def test_a_name_spelled_with_a_doubled_space_reaches_the_stored_dataset(self) -> None:
        # ResQ spells some type names with a doubled space and production
        # workbooks still ask with those names; the stored record answers
        # whichever spacing the request used.
        self._write_csv(self.ENGINE_TEXT)
        self._write_sidecar()
        doubled = self.dataset_name.replace(" ", "  ")
        pairs = [
            (key, doubled if key in {"DatasetName", "InstanceName"} else value)
            for key, value in self._pairs()
        ]

        def refuse(*args, **kwargs):
            raise AssertionError("The stored dataset answers a differently spaced spelling of its name.")

        with patch.object(engine_calculation_service, "run_engine_calculation", refuse):
            answer = engine_calculation_service.execute_hosted_engine_calculation(
                pairs, 15.0, OUTPUT_VARIANT_CANONICAL, OPERATION_DATASET_CSV, {}
            )

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["local_cache_status"], "cache_exact")
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)

    def test_the_text_is_the_file_the_run_wrote(self) -> None:
        def fake_engine(pairs, data_path, timeout_sec, **kwargs):
            with open(data_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(self.ENGINE_TEXT)
            return {"ok": True, "status": "completed", "request_file": "r.json"}

        with patch.object(engine_calculation_service, "run_engine_calculation", fake_engine):
            answer = self._answer()

        self.assertTrue(answer["ok"])
        self.assertTrue(answer["need_request"])
        self.assertEqual(answer["csv_text"], self._read_csv())
        self.assertEqual(answer["csv_text"], self.ENGINE_TEXT)

    def test_a_dataset_the_engine_does_not_answer_reports_why(self) -> None:
        timeout = {
            "ok": False,
            "status": "timeout",
            "request_file": "r.json",
            "message": "Timed out waiting for the Arco Engine.",
        }
        with patch.object(
            engine_calculation_service, "run_engine_calculation", return_value=timeout
        ):
            answer = self._answer()

        self.assertFalse(answer["ok"])
        self.assertEqual(answer["status"], "timeout")
        self.assertNotIn("csv_text", answer)
        self.assertIn("Timed out", answer["message"])
        self.assertFalse(self.csv_path.exists())


class HostedProjectLevelCsvTests(unittest.TestCase):
    """``dataset_csv`` answers the headings and project-settings formulas too."""

    project_name = "Example Project"
    # Written the way the Engine writes a project-level CSV, line endings and
    # all: the answer carries that text unchanged.
    HEADER_TEXT = "2020,2021,2022\r\n"
    SETTINGS_TEXT = "Name,Example Project\r\nOrigin Length,12\r\n"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = root / "general_settings.json"
        self.settings_path.write_text("{}", encoding="utf-8")
        item = patch.object(config, "get_project_data_dir", return_value=str(self.data_dir))
        item.start()
        self.addCleanup(item.stop)
        item = patch.object(
            project_settings_service,
            "get_general_settings",
            return_value={
                "ok": True,
                "exists": True,
                "path": str(self.settings_path),
                "data": {"origin_start_date": "202001"},
            },
        )
        item.start()
        self.addCleanup(item.stop)
        self.addCleanup(file_read_cache.clear_file_read_cache)

    def _header_pairs(self) -> list:
        return [
            ("Function", "ArcRhoHeaders"),
            ("periodType", "0"),
            ("Transposed", "False"),
            ("Calendar", "False"),
            ("PeriodLength", "12"),
            ("ProjectName", self.project_name),
            ("StoredPeriodLength", "-1"),
        ]

    def _settings_pairs(self) -> list:
        return [("Function", "ArcRhoProjectSettings"), ("ProjectName", self.project_name)]

    def _answer(self, pairs: list, **options) -> dict:
        return engine_calculation_service.execute_hosted_engine_calculation(
            pairs, 15.0, OUTPUT_VARIANT_CANONICAL, OPERATION_DATASET_CSV, options
        )

    def _write_cache(self, pairs: list, text: str) -> Path:
        path = Path(set_data_path_like_vba([(str(k), str(v)) for k, v in pairs]))
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def _engine_writes(self, text: str):
        def fake_engine(pairs, data_path, timeout_sec, **kwargs):
            with open(data_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            return {"ok": True, "status": "completed", "request_file": "r.json"}

        return patch.object(engine_calculation_service, "run_engine_calculation", fake_engine)

    def test_the_headings_answer_matches_the_existing_route(self) -> None:
        self._write_cache(self._header_pairs(), self.HEADER_TEXT)

        answer = self._answer(self._header_pairs())
        route = arcrho_runtime_service.arcrho_headers(self._header_pairs(), timeout_sec=15.0)

        self.assertTrue(answer["ok"])
        self.assertEqual(answer["labels"], route["labels"])
        self.assertEqual(answer["labels"], ["2020", "2021", "2022"])
        self.assertEqual(answer["csv_text"], self.HEADER_TEXT)

    def test_the_project_settings_answer_is_the_engine_csv(self) -> None:
        with self._engine_writes(self.SETTINGS_TEXT):
            answer = self._answer(self._settings_pairs())

        path = Path(set_data_path_like_vba([(k, v) for k, v in self._settings_pairs()]))
        with open(path, "r", encoding="utf-8", newline="") as handle:
            self.assertEqual(answer["csv_text"], handle.read())
        self.assertEqual(answer["csv_text"], self.SETTINGS_TEXT)
        self.assertTrue(answer["ok"])

    def test_a_cached_project_settings_table_is_reused(self) -> None:
        self._write_cache(self._settings_pairs(), self.SETTINGS_TEXT)

        def refuse(*args, **kwargs):
            raise AssertionError("A cached project-settings table must not ask the Engine.")

        with patch.object(engine_calculation_service, "run_engine_calculation", refuse):
            answer = self._answer(self._settings_pairs())

        self.assertEqual(answer["csv_text"], self.SETTINGS_TEXT)

    def test_a_settings_save_after_the_cache_asks_the_engine_again(self) -> None:
        path = self._write_cache(self._settings_pairs(), self.SETTINGS_TEXT)
        os.utime(path, (0, 0))

        with self._engine_writes("Name,Renamed Project\r\n"):
            answer = self._answer(self._settings_pairs())

        self.assertEqual(answer["csv_text"], "Name,Renamed Project\r\n")

    def test_an_unanswered_project_settings_request_reports_why(self) -> None:
        timeout = {
            "ok": False,
            "status": "timeout",
            "request_file": "r.json",
            "message": "Timed out waiting for the Arco Engine.",
        }
        with patch.object(
            engine_calculation_service, "run_engine_calculation", return_value=timeout
        ):
            answer = self._answer(self._settings_pairs())

        self.assertFalse(answer["ok"])
        self.assertEqual(answer["status"], "timeout")
        self.assertNotIn("csv_text", answer)


if __name__ == "__main__":
    unittest.main()
