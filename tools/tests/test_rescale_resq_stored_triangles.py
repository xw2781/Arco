"""The one-off tool that rescales a project's ResQ-stored "Adjusted" / ad hoc triangles."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
MODULE_PATH = REPO_ROOT / "tools" / "rescale_resq_stored_triangles.py"
SPEC = importlib.util.spec_from_file_location("rescale_resq_stored_triangles", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)

RC = "Line\\State"
BASE_12 = [[100.0, 150.0], [200.0, None]]
BASE_3 = [[float(i + 1)] * 8 for i in range(8)]


def _write_csv(path: Path, rows) -> None:
    path.write_text("".join(",".join("" if v is None else str(v) for v in row) + "\n" for row in rows), encoding="utf-8")


class RescaleResqStoredTrianglesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.project = Path(self.temp.name) / "projects" / "Fixture"
        self.class_dir = self.project / "data" / "Line_%5C_State"
        for folder in ("sidecars", "datasets", "methods"):
            (self.class_dir / folder).mkdir(parents=True)
        table = Path(self.temp.name) / "source.csv"
        table.write_text("x\n", encoding="utf-8")
        os.utime(table, (1_000_000, 1_000_000))
        (self.project / "field_mapping.json").write_text(json.dumps({"table_path": str(table)}), encoding="utf-8")
        (self.project / "general_settings.json").write_text(
            json.dumps({"origin_start_date": "202501", "origin_end_date": "202612"}), encoding="utf-8"
        )
        datasets = self.class_dir / "datasets"
        _write_csv(datasets / "Net Loss--Incurred@12@12@cum@dev.csv", BASE_12)
        _write_csv(datasets / "Net Loss--Incurred@3@3@cum@dev.csv", BASE_3)
        _write_csv(datasets / "Net Loss--Paid@12@12@cum@dev.csv", BASE_12)
        # Hand-entered, stored 12x1 under a 12x12 display: keeps its store.
        self._sidecar("Net Loss--Incurred Adjusted*", "input", 12, 12, 12, 1, dependents=["F 23 C"])
        _write_csv(datasets / "Net Loss--Incurred Adjusted_%2A_@12@1@cum@dev.csv", [[0.0] * 24] * 2)
        self._method("F 23 C", 12, 12)
        # Engine-kind at 1x1 whose DFM reads 3x3: rewritten at 3x3.
        self._sidecar("Net Loss--Paid Adjusted*", "engine", 1, 1, 1, 1, dependents=["F 13 C"])
        self._method("F 13 C", 12, 12)
        self._sidecar("Net Loss - ad hoc", "engine", 3, 3, 3, 3, dependents=["Severity", "F 99"])
        self._method("F 99", 3, 3)
        self._sidecar("Severity", "engine", 12, 12, 12, 12, calculated=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _sidecar(self, name, kind, origin, development, stored_origin, stored_development, *, dependents=(), calculated=False):
        payload = {
            "dataset_name": name,
            "dataset_type": name,
            "reserving_class": RC,
            "source_kind": kind,
            "source": "resq_triangle",
            "calculated": calculated,
            "data_format": "Triangle",
            "origin_length": origin,
            "development_length": development,
            "stored_origin_length": stored_origin,
            "stored_development_length": stored_development,
            "csv_file": f"{name}@{stored_origin}@{stored_development}@cum@dev.csv".replace("*", "_%2A_"),
            "dependents": [{"dataset_name": entry} for entry in dependents],
        }
        file_name = name.replace("*", "_%2A_") + ".json"
        (self.class_dir / "sidecars" / file_name).write_text(json.dumps(payload), encoding="utf-8")

    def _method(self, name, origin, development):
        payload = {"details_tab": {"name": name}, "method_tab": {"origin_length": origin, "development_length": development}}
        (self.class_dir / "methods" / f"DFM@{name}.json").write_text(json.dumps(payload), encoding="utf-8")

    def _plan(self):
        return {item.dataset_name: item for item in tool.plan_project(self.project, seed=7)}

    def test_base_dataset_names(self) -> None:
        self.assertEqual(tool.base_dataset("Net Loss--Incurred Adjusted***"), "Net Loss--Incurred")
        self.assertEqual(tool.base_dataset("Net Loss--Paid Adjusted*"), "Net Loss--Paid")
        self.assertEqual(tool.base_dataset("Net Loss--Incurred Adjusted"), "Net Loss--Incurred")
        self.assertEqual(tool.base_dataset("Gross Loss - ad hoc"), "Gross Loss--Incurred")

    def test_plan_takes_the_dependents_lengths_and_skips_calculated(self) -> None:
        plan = self._plan()
        self.assertNotIn("Severity", plan)
        kept = plan["Net Loss--Incurred Adjusted*"]
        self.assertEqual((kept.origin_length, kept.development_length, kept.reshape), (12, 12, False))
        reshaped = plan["Net Loss--Paid Adjusted*"]
        self.assertEqual((reshaped.origin_length, reshaped.development_length, reshaped.reshape), (12, 12, True))
        adhoc = plan["Net Loss - ad hoc"]
        self.assertEqual((adhoc.base, adhoc.origin_length, adhoc.reshape), ("Net Loss--Incurred", 3, False))
        self.assertEqual(len(adhoc.values), 8)
        self.assertEqual(adhoc.origin_labels[:2], ["2025 Q1", "2025 Q2"])

    def test_values_are_the_base_times_one_seeded_factor_per_origin(self) -> None:
        item = self._plan()["Net Loss--Incurred Adjusted*"]
        factors = [row[0] / base[0] for row, base in zip(item.values, BASE_12)]
        self.assertEqual(item.values[1][1], None)
        self.assertAlmostEqual(item.values[0][1] / BASE_12[0][1], factors[0])
        for factor in factors:
            self.assertLessEqual(abs(factor - 1.0), tool.DEVIATION)
        self.assertEqual(item.values, self._plan()["Net Loss--Incurred Adjusted*"].values)

    def test_save_arguments_clear_the_store_only_on_a_reshape(self) -> None:
        plan = self._plan()
        kept = tool.save_arguments(plan["Net Loss--Incurred Adjusted*"])
        self.assertNotIn("stored_values_cleared", kept)
        self.assertEqual(kept["mask"], [[True, True], [True, False]])
        self.assertEqual(kept["values"][1][1], 0.0)
        moved = tool.save_arguments(plan["Net Loss--Paid Adjusted*"])
        self.assertTrue(moved["stored_values_cleared"])
        self.assertEqual(moved["origin_labels"], ["2025", "2026"])
        self.assertEqual(moved["source_kind"], "engine")

    def test_a_hand_entered_store_finer_on_origin_keeps_its_rows(self) -> None:
        # Quarterly store under a yearly dependent: two quarters per year.
        self._sidecar("Net Loss--Incurred Adjusted**", "input", 3, 3, 3, 3, dependents=["F 23 C"])
        _write_csv(self.class_dir / "datasets" / "Net Loss--Incurred Adjusted_%2A__%2A_@3@3@cum@dev.csv",
                   [[1.0, 2.0], [3.0, None], [0.0, 0.0], [0.0, None]])
        item = self._plan()["Net Loss--Incurred Adjusted**"]
        self.assertFalse(item.reshape)
        self.assertEqual(item.write_lengths, (3, 3))
        factor = tool.origin_factors(7, RC, "Net Loss--Incurred Adjusted**", 2)[0]
        self.assertAlmostEqual(item.values[0][1] + item.values[1][0], 150.0 * factor)
        self.assertEqual(item.values[2:], [[0.0, 0.0], [0.0, None]])  # nothing held, nothing to rescale
        arguments = tool.save_arguments(item)
        self.assertEqual((arguments["origin_length"], arguments["development_length"], arguments["display_at"]), (3, 3, [3, 3]))

    def test_a_stale_base_cache_is_refused(self) -> None:
        os.utime(self.class_dir / "datasets" / "Net Loss--Incurred@3@3@cum@dev.csv", (1, 1))
        self.assertIn("older than the source table", self._plan()["Net Loss - ad hoc"].problem)

    def test_check_compares_each_latest_diagonal_with_its_base(self) -> None:
        datasets = self.class_dir / "datasets"
        _write_csv(datasets / "Net Loss - ad hoc@3@3@cum@dev.csv", BASE_3)
        # 12x1 scattered store: zeros between the yearly ages.
        _write_csv(datasets / "Net Loss--Incurred Adjusted_%2A_@12@1@cum@dev.csv", [[100.0, 0.0, 150.0, 0.0], [210.0, 0.0, None, None]])
        _write_csv(datasets / "Net Loss--Paid Adjusted_%2A_@1@1@cum@dev.csv", [[155.0], [400.0]])
        output = io.StringIO()
        with redirect_stdout(output):
            failures = tool.check_project(self.project)
        self.assertEqual(failures, 1, output.getvalue())  # the Paid store's second origin is twice its base
