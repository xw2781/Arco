import json
import shutil
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import recalculate_project_methods as tool  # noqa: E402

TEST_ROOT = REPO_ROOT / "test" / "recalculate_project_methods"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _class(project: Path, folder: str, path: str, files: list[dict], precedents: list[dict] | None = None) -> Path:
    class_dir = project / "data" / folder
    _write(class_dir / "index.json", {"reserving_class": path, "files": files})
    _write(class_dir / "sidecars" / "out.json", {"precedents": precedents or []})
    return class_dir


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        self.project = TEST_ROOT / "projects" / "P"
        self.addCleanup(shutil.rmtree, TEST_ROOT, ignore_errors=True)

    def test_upstream_class_first_and_roots_exclude_methods(self) -> None:
        engine = {"name": "Paid", "dataset_type": "Paid", "source_kind": "engine", "method_type": "None"}
        hand = {"name": "Prior", "dataset_type": "Prior", "source_kind": "input", "method_type": "None"}
        calculated = {"name": "Sev", "dataset_type": "Sev", "source_kind": "calculated", "method_type": "None"}
        dfm = {"name": "F 23", "dataset_type": "F 23", "source_kind": "dfm", "method_type": "DFM"}
        boot = {"name": "F 72", "dataset_type": "F 72", "source_kind": "input", "method_type": "Bootstrap"}
        _class(self.project, "A_Total", "A\\Total", [engine, dfm], [{"dataset_name": "F 23", "reserving_class": "A\\Line"}])
        _class(self.project, "A_Line", "A\\Line", [engine, hand, calculated, dfm, boot])
        _class(self.project, "A_Empty", "A\\Empty", [engine])

        plan = tool.plan_classes(self.project)

        self.assertEqual([walk.reserving_class for walk in plan], ["A\\Line", "A\\Total"])
        self.assertEqual([root["dataset_name"] for root in plan[0].roots], ["Paid", "Prior"])
        self.assertEqual(plan[0].methods, 2)
        self.assertEqual(plan[1].reads_from, {"A\\Line"})

    def test_dry_run_prints_the_plan_without_the_gateway(self) -> None:
        _class(self.project, "A_Line", "A\\Line", [
            {"name": "Paid", "dataset_type": "Paid", "source_kind": "engine", "method_type": "None"},
            {"name": "F 23", "dataset_type": "F 23", "source_kind": "dfm", "method_type": "DFM"},
        ])
        self.assertEqual(tool.main(["--root", str(TEST_ROOT), "--project", "P", "--dry-run"]), 0)


class MeasureTests(unittest.TestCase):
    def test_dfm_selected_factor_ratio_and_loss_ratio(self) -> None:
        dfm = {
            "ratios_tab": {"average_formulas": {
                "selected": [[0, 1], [1, 0]],
                "values": [[9.0, 1.2], [2.0, 5.0]],
            }},
            "data_tab": {"input_data_triangle_values": [[50, 100, 110], [40, 80], [30]]},
            "results_tab": {"ultimate_vector": [110, 96, 72], "ratio_basis_values": [200, 200, None],
                            "ratio_basis_dataset": "Total Earned Premium"},
        }
        measures = tool.method_measures("DFM", dfm)
        self.assertEqual(tool.selected_factors(dfm), [2.0, 1.2])
        self.assertEqual(measures["first_factor"], 2.0)
        self.assertAlmostEqual(measures["max_ult_to_latest"], 2.4)
        self.assertAlmostEqual(measures["loss_ratio"], 206 / 400)

    def test_result_selection_loss_ratio_skips_empty_origins(self) -> None:
        rs = {
            "details_tab": {"active_ratio_basis_dataset": "Total Earned Premium"},
            "method_tab": {"selected_ultimate": [60, None, 70],
                           "ratio_basis_values": [{"name": "Total Earned Premium", "values": [100, 100, 100]}]},
        }
        self.assertAlmostEqual(tool.method_measures("RS", rs)["loss_ratio"], 0.65)

    def test_step_8_bar_counts_late_factors_and_mature_origins_only(self) -> None:
        dfm = {
            "curves_tab": {"selected_values": [30.0, 12.0, 11.0, 1.0]},
            "data_tab": {"origin_labels": ["2019", "2025"], "input_data_triangle_values": [[10, 20], [1]]},
            "results_tab": {"ultimate_vector": [500, 100]},
        }
        valuation = 2026 * 12 + 4  # May 2026
        measures = tool.method_measures("DFM", dfm, valuation)
        self.assertEqual(measures["late_factors_over_10"], [3])
        self.assertAlmostEqual(measures["max_mature_ult_to_latest"], 25.0)  # 2025 is young and left out
        self.assertEqual(tool.mature_origins(["2023 Q1", "2023 Q3", "Jan 2023"], valuation), [True, False, True])


if __name__ == "__main__":
    unittest.main()
