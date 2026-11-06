"""The one-off tool that puts a project's prior and expected-ratio vectors on the scale of its results."""

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
MODULE_PATH = REPO_ROOT / "tools" / "rescale_prior_inputs.py"
SPEC = importlib.util.spec_from_file_location("rescale_prior_inputs", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)

RC = "Line\\State"
QUARTERS = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]  # 2025 Q1 .. 2026 Q4


def _write_csv(path: Path, values) -> None:
    path.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


class RescalePriorInputsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.project = Path(self.temp.name) / "projects" / "Fixture"
        self.class_dir = self.project / "data" / "Line_%5C_State"
        for folder in ("sidecars", "datasets"):
            (self.class_dir / folder).mkdir(parents=True)
        self.table = Path(self.temp.name) / "source.csv"
        self.table.write_text("x\n", encoding="utf-8")
        os.utime(self.table, (1_000_000, 1_000_000))
        (self.project / "field_mapping.json").write_text(json.dumps({"table_path": str(self.table)}), encoding="utf-8")
        (self.project / "general_settings.json").write_text(
            json.dumps({"origin_start_date": "202501", "origin_end_date": "202612"}), encoding="utf-8"
        )
        # Quarterly Result Selections.
        self._vector("D 91 - Current Qtr Indicated", "result_selection", 3, QUARTERS)
        self._vector("D 92 - Current Qtr Selected", "result_selection", 3, QUARTERS, dependents=["G 92"])
        self._vector("G 92 - Current Qtr Selected", "result_selection", 3, [v / 10 for v in QUARTERS])
        # A prior stored yearly whose selection is quarterly: re-stored at 3.
        self._vector("D 81 - Prior Qtr Indicated", "input", 12, [999.0, 999.0], dependents=["D 92 - Current Qtr Selected"])
        self._vector("D 42 - Prior for BF Incurred", "input", 3, [1.0] * 8, dependents=["D 41 - BF Incurred"])
        self._vector("D 41 - BF Incurred", "bf", 12, [0.0, 0.0])
        self._vector("P 04 A-ALAE--Expected % of Ultimate Gross Loss - Indicated", "input", 3, [5.0] * 8,
                     dependents=["G 62 - Expected % * Ultimate Gross Loss"])
        self._vector("G 62 - Expected % * Ultimate Gross Loss", "dfm", 3, [0.0] * 8)
        self._vector("P 07 Gross Loss--Expected Gross Loss % of Earned Premium", "input", 12, [3.0, 3.0])
        self._vector("Total Earned Premium", "engine", 12, [100.0, 200.0])
        self._vector("Bootstrap", "input", 12, [1.0, 1.0])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _vector(self, name, kind, period, values, *, dependents=()):
        csv_file = f"{name}@{period}.csv".replace("*", "_%2A_")
        payload = {
            "dataset_name": name,
            "dataset_type": name,
            "reserving_class": RC,
            "source_kind": kind,
            "data_format": "Vector",
            "period_length": period,
            "stored_period_length": period,
            "csv_file": csv_file,
            "dependents": [{"dataset_name": entry} for entry in dependents],
        }
        (self.class_dir / "sidecars" / (name.replace("*", "_%2A_") + ".json")).write_text(json.dumps(payload), encoding="utf-8")
        _write_csv(self.class_dir / "datasets" / csv_file, values)

    def _plan(self):
        return {item.dataset_name: item for item in tool.plan_project(self.project)}

    def test_classify_names_each_vector_and_its_sources(self) -> None:
        self.assertEqual(tool.classify("C 81 - Prior Qtr Indicated"), ("81", ("C 91",)))
        self.assertEqual(tool.classify("E1 82 - Prior Qtr Selected"), ("82", ("E1 92",)))
        self.assertEqual(tool.classify("C 42a - Prior for BF Reported ex CWOP"), ("42", ("C 92",)))
        self.assertEqual(tool.classify("F 42 B - Prior for BF Incurred"), ("42", ("F 92",)))
        self.assertEqual(tool.classify("P 04 A-ALAE--Expected % of Ultimate Gross Loss - Indicated"), ("ratio", ("G", "D")))
        self.assertEqual(tool.classify("P 04 B-ALAE--Expected % of Ultimate Net Loss - Indicated"), ("ratio", ("G", "F")))
        self.assertEqual(tool.classify("P 06 Net Loss--Expected Net Loss % of Earned Premium"), ("ratio", ("F", tool.PREMIUM)))
        self.assertIsNone(tool.classify("F 72B - Bootstrap Net Incurred no PV"))
        self.assertIsNone(tool.classify("C 42 - Reported ex CWOP DFM w/ Selected LDFs"))

    def test_plan_orders_the_stages_and_takes_the_dependents_period(self) -> None:
        plan = tool.plan_project(self.project)
        self.assertEqual([item.stage for item in plan], ["81", "42", "ratio", "ratio"])
        items = self._plan()
        self.assertNotIn("Bootstrap", items)
        self.assertEqual((items["D 81 - Prior Qtr Indicated"].period, items["D 81 - Prior Qtr Indicated"].stored_period), (3, 12))
        self.assertEqual(items["D 81 - Prior Qtr Indicated"].sources, ("D 91 - Current Qtr Indicated",))
        # Its BF is yearly, its counterpart quarterly: kept at the finer one.
        self.assertEqual(items["D 42 - Prior for BF Incurred"].period, 3)
        # No dependent: follows its numerator's period.
        self.assertEqual(items["P 07 Gross Loss--Expected Gross Loss % of Earned Premium"].period, 3)

    def test_values_follow_the_counterpart_times_one_seeded_factor_per_origin(self) -> None:
        item = self._plan()["D 42 - Prior for BF Incurred"]
        values, current = tool.target_values(self.project, item, 7)
        self.assertEqual(current, QUARTERS)
        for value, base in zip(values, current):
            self.assertLessEqual(abs(value / base - 1.0), tool.triangles.DEVIATION)
        self.assertEqual(values, tool.target_values(self.project, item, 7)[0])

    def test_ratios_divide_numerator_by_denominator(self) -> None:
        item = self._plan()["P 04 A-ALAE--Expected % of Ultimate Gross Loss - Indicated"]
        _, current = tool.target_values(self.project, item, 7)
        self.assertEqual(current, [0.1] * 8)

    def test_premium_comes_from_a_file_built_from_the_source_table(self) -> None:
        item = self._plan()["P 07 Gross Loss--Expected Gross Loss % of Earned Premium"]
        with self.assertRaisesRegex(ValueError, "adds up to 3 months"):
            tool.target_values(self.project, item, 7)  # only a yearly premium file exists
        _write_csv(self.class_dir / "datasets" / "Total Earned Premium@3.csv", [20.0] * 8)
        _, current = tool.target_values(self.project, item, 7)
        self.assertEqual(current, [v / 20.0 for v in QUARTERS])
        os.utime(self.class_dir / "datasets" / "Total Earned Premium@3.csv", (1, 1))
        with self.assertRaisesRegex(ValueError, "built from the source table"):
            tool.target_values(self.project, item, 7)

    def test_save_arguments_re_store_only_on_a_period_change(self) -> None:
        items = self._plan()
        moved = tool.save_arguments(self.project, items["D 81 - Prior Qtr Indicated"], [1.0] * 8)
        self.assertTrue(moved["stored_values_cleared"])
        self.assertEqual(moved["origin_labels"][:2], ["2025 Q1", "2025 Q2"])
        self.assertEqual((moved["origin_length"], moved["values"][0], moved["mask"][0]), (3, [1.0], [True]))
        kept = tool.save_arguments(self.project, items["P 04 A-ALAE--Expected % of Ultimate Gross Loss - Indicated"], [0.1] * 8)
        self.assertNotIn("stored_values_cleared", kept)

    def test_check_flags_a_vector_off_its_counterpart_by_more_than_double(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            failures = tool.check_project(self.project)
        # D 81 cannot be read at 3, nor P 07's premium; D 42 (8 against 360) and P 04 A (40 against 0.8) are off scale.
        self.assertEqual(failures, 4, output.getvalue())
        _write_csv(self.class_dir / "datasets" / "D 42 - Prior for BF Incurred@3.csv", [25.0] * 4 + [65.0] * 4)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(tool.check_project(self.project), 3)


if __name__ == "__main__":
    unittest.main()
