import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import reset_unfit_method_settings as tool  # noqa: E402


def _dfm(typed: float, average: float, ratios: list[list[float | None]]) -> dict:
    return {
        "ratios_tab": {
            "ratio_triangle": {"ratio_values": ratios, "excluded": [[1, 0], [0]]},
            "average_formulas": {
                "label": ["Volume - all", "User Entry"],
                "custom_average_formula_settings": {"average_type": ["custom", "user_entry"]},
                "selected": [[0, 0, 0], [1, 1, 1]],
                "values": [[average, 1.1, 1.0], [typed, 1.1, 1.0]],
                "inputs": [["", "", ""], ["", "", ""]],
            },
        },
    }


class ResetTests(unittest.TestCase):
    def test_typed_factor_far_from_the_average_selects_the_average(self) -> None:
        method = _dfm(9.0, 2.0, [[2.1, 1.1], [1.9]])
        self.assertEqual(len(tool.reset_user_entries(method)), 1)
        selected = method["ratios_tab"]["average_formulas"]["selected"]
        self.assertEqual(selected, [[1, 0, 0], [0, 1, 1]])

    def test_close_factor_and_column_without_data_are_kept(self) -> None:
        self.assertEqual(tool.reset_user_entries(_dfm(2.2, 2.0, [[2.1, 1.1], [1.9]])), [])
        self.assertEqual(tool.reset_user_entries(_dfm(9.0, 1.0, [[None, 1.1], [None]])), [])

    def test_column_with_ratios_and_no_selection_gets_the_default(self) -> None:
        method = _dfm(1.0, 2.0, [[2.1, None], [1.9]])
        method["ratios_tab"]["average_formulas"]["selected"] = [[0, 0, 0], [0, 0, 1]]
        self.assertEqual(tool.select_unselected(method), ["1: no row -> Volume - all"])
        # Column 2 has no ratio and column 3 is the tail, so both stay as they were.
        self.assertEqual(method["ratios_tab"]["average_formulas"]["selected"], [[1, 0, 0], [0, 0, 1]])

    def test_exclusions_follow_the_walk_report(self) -> None:
        walks = [{"reserving_class": "A/B", "message": "Method refresh failure(s): C 22 - CWOP: 422: DFM input values "
                  "are missing for previously excluded ratio cells. Update; F 13: 422: other"}]
        self.assertEqual(tool.excluded_dfms(walks), {("a/b", "C 22 - CWOP")})
        method = _dfm(2.0, 2.0, [[2.0, 1.1], [2.0]])
        self.assertTrue(tool.clear_exclusions(method))
        self.assertEqual(method["ratios_tab"]["ratio_triangle"]["excluded"], [[0, 0], [0]])

    def test_deleted_candidate_hands_its_origins_to_the_first_dfm(self) -> None:
        method = {"method_tab": {"loaded_datasets": [
            {"name": "Paid", "method_type": "None", "weights": [0, 0]},
            {"name": "F 23", "method_type": "DFM", "weights": [0, 1]},
            {"name": "F 41  BF", "method_type": "Bornhuetter Ferguson", "weights": [1, 0]},
        ]}}
        self.assertEqual(tool.drop_missing_candidates(method, {"paid", "f 23"}), ["dropped F 41  BF, weights to F 23"])
        self.assertEqual([item["weights"] for item in method["method_tab"]["loaded_datasets"]], [[0, 0], [1, 1]])
        self.assertEqual(tool.drop_missing_candidates(method, {"paid", "f 23"}), [])


if __name__ == "__main__":
    unittest.main()
