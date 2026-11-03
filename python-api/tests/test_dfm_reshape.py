"""A move of the project dates reshapes a Development Factor method.

Rows follow their origin label; along the development axis exclusions,
average-formula cells and cell notes keep their position from the first
column, with the tail kept last (docs/plans/project_dates_panel.md, step 2).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api.dfm_contract import (  # noqa: E402
    DFM_JSON_FORMAT,
    DfmContractError,
    normalize_dfm_method,
    recalculate_dfm_method,
)
from arcrho_api.period_reshape import (  # noqa: E402
    development_axis_reshapable,
    fit_by_position,
    fit_by_position_keep_tail,
    reshape_matrix,
    rows_by_label,
)


def snapshot(origins: list[str], devs: list[str], values: list[list[float | None]]) -> dict:
    return {
        "name": "Paid Loss",
        "origin_labels": origins,
        "development_labels": devs,
        "values": values,
        "mask": [[item is not None for item in row] for row in values],
        "data_format": "Triangle",
        "number_format": "#,##0",
        "decimal_places": 0,
    }


def method(origins: list[str], devs: list[str], values: list[list[float | None]], owned: dict) -> dict:
    payload = {
        "json_format": DFM_JSON_FORMAT,
        "details_tab": {
            "name": "Paid DFM",
            "output_type": "Paid Ultimate",
            "output_dataset": "Paid Selected",
            "input_triangle": "Paid Loss",
            "origin_length": 3,
            "development_length": 3,
            "decimal_places": 4,
        },
        "data_tab": {},
        "ratios_tab": {
            "ratio_triangle": {},
            "average_formulas": {
                "label": ["Volume - all", "Simple - all", "User Entry"],
                "custom_average_formula_settings": {
                    "average_type": ["custom", "custom", "user_entry"],
                    "base": ["volume", "simple", "simple"],
                    "periods": ["all", "all", "all"],
                    "exclude": [0, 0, 0],
                },
                "selected": owned["selected"],
                "values": owned["values"],
                "inputs": owned["inputs"],
                "display_inputs": [[""] * len(devs) for _ in range(3)],
            },
            "cell_notes": {"ratio_main_table": owned["notes"], "ratio_summary_table": {}},
        },
        "results_tab": {"ratio_basis_dataset": "", "ultimate_ratio_decimal_places": 2},
        "method_metadata": {
            "last_modified": "2026-01-01T00:00:00Z",
            "data_refreshed": "2026-01-01T00:00:00Z",
        },
    }
    created = recalculate_dfm_method(payload, input_snapshot=snapshot(origins, devs, values))
    # Exclusions are keyed by origin label, which a method only has once its
    # first triangle is in, so they are set on the created method.
    created["ratios_tab"]["ratio_triangle"]["excluded"] = owned["excluded"]
    return recalculate_dfm_method(created)


QUARTERS = ["2025 Q1", "2025 Q2", "2025 Q3"]
JUNE_DEVS = ["2", "5", "8"]
JUNE_VALUES = [[100, 150, 180], [200, 300, None], [400, None, None]]
SEPT_DEVS = ["1", "4", "7", "10"]
SEPT_VALUES = [[90, 140, 175, 190], [190, 290, 310, None], [380, 410, None, None]]


def june_method() -> dict:
    return method(QUARTERS, JUNE_DEVS, JUNE_VALUES, {
        "excluded": [[1, 0], [0], []],
        "selected": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        "values": [[1, 1, 1], [1, 1, 1], [1.5, 1.2, 1.05]],
        "inputs": [["", "", ""], ["", "", ""], ["1.5", "1.2", ""]],
        "notes": {"2025 Q1": {"(1) 2-5": "First", "8 - Ult": "Tail"}},
    })


def owned_axes(payload: dict) -> dict:
    formulas = payload["ratios_tab"]["average_formulas"]
    curves = payload["curves_tab"]
    return {
        "origin_labels": payload["data_tab"]["origin_labels"],
        "development_labels": payload["data_tab"]["development_labels"],
        "ratio_labels": payload["ratios_tab"]["ratio_triangle"]["development_labels"],
        "excluded": payload["ratios_tab"]["ratio_triangle"]["excluded"],
        "selected": formulas["selected"],
        "user_entry_values": formulas["values"][2],
        "inputs": formulas["inputs"],
        "notes": payload["ratios_tab"]["cell_notes"]["ratio_main_table"],
        "curve_periods": [len(curves["included"]), len(curves["selected_estimates"])],
    }


class PeriodReshapeHelperTests(unittest.TestCase):
    def test_development_axis_is_reshapable_only_for_ages_on_the_same_spacing(self) -> None:
        self.assertTrue(development_axis_reshapable(["2", "5", "8"], ["1", "4", "7", "10"]))
        self.assertTrue(development_axis_reshapable(["12m", "24m"], ["5m", "17m", "29m"]))
        self.assertFalse(development_axis_reshapable(["3", "6", "9"], ["12", "24", "36"]))
        self.assertFalse(development_axis_reshapable(["2025 Q1"], ["1", "4"]))
        self.assertFalse(development_axis_reshapable([], ["1", "4"]))

    def test_rows_follow_labels_and_cells_follow_position(self) -> None:
        self.assertEqual(fit_by_position([1, 2, 3], 2, 0), [1, 2])
        self.assertEqual(fit_by_position([1, 2], 4, 0), [1, 2, 0, 0])
        self.assertEqual(fit_by_position_keep_tail([1, 2, 9], 4, 0), [1, 2, 0, 9])
        self.assertEqual(fit_by_position_keep_tail([1, 2, 3, 9], 2, 0), [1, 9])
        self.assertEqual(rows_by_label(["a", "b"], ["2018", "2019"], ["2019", "2020"], "-"), ["b", "-"])
        self.assertEqual(
            reshape_matrix([[1, 0], [0, 1]], ["2018", "2019"], ["2019", "2020"], 3, 0),
            [[0, 1, 0], [0, 0, 0]],
        )


class DfmReshapeTests(unittest.TestCase):
    def test_a_new_development_column_keeps_the_pattern_by_position(self) -> None:
        june = june_method()
        september = recalculate_dfm_method(june, input_snapshot=snapshot(QUARTERS, SEPT_DEVS, SEPT_VALUES))
        self.assertEqual(owned_axes(september), {
            "origin_labels": QUARTERS,
            "development_labels": SEPT_DEVS,
            "ratio_labels": ["(1) 1-4", "(2) 4-7", "(3) 7-10", "10 - Ult"],
            "excluded": [[1, 0, 0], [0, 0], [0]],
            "selected": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]],
            "user_entry_values": [1.5, 1.2, 1.0, 1.05],
            "inputs": [["", "", "", ""], ["", "", "", ""], ["1.5", "1.2", "", ""]],
            "notes": {"2025 Q1": {"(1) 1-4": "First", "10 - Ult": "Tail"}},
            "curve_periods": [3, 3],
        })
        self.assertEqual(normalize_dfm_method(september), september)

    def test_a_dropped_development_column_shrinks_back(self) -> None:
        june = june_method()
        september = recalculate_dfm_method(june, input_snapshot=snapshot(QUARTERS, SEPT_DEVS, SEPT_VALUES))
        september["ratios_tab"]["ratio_triangle"]["excluded"][0][2] = 1
        september = recalculate_dfm_method(september)
        back = recalculate_dfm_method(september, input_snapshot=snapshot(QUARTERS, JUNE_DEVS, JUNE_VALUES))
        self.assertEqual(owned_axes(back), owned_axes(june))
        self.assertEqual(back["results_tab"]["ultimate_vector"], june["results_tab"]["ultimate_vector"])
        self.assertEqual(normalize_dfm_method(back), back)

    def test_a_january_change_keeps_each_surviving_origin_on_its_label(self) -> None:
        december = method(
            ["2018", "2019", "2020"],
            ["12", "24", "36"],
            [[100, 150, 180], [200, 260, None], [400, None, None]],
            {
                "excluded": [[0, 1], [1], []],
                "selected": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                "values": [[1, 1, 1], [1, 1, 1], [1.4, 1.1, 1.02]],
                "inputs": [["", "", ""], ["", "", ""], ["1.4", "1.1", ""]],
                "notes": {"2019": {"(1) 12-24": "Large claim"}},
            },
        )
        january = recalculate_dfm_method(december, input_snapshot=snapshot(
            ["2019", "2020", "2021"],
            ["1", "13", "25", "37"],
            [[20, 205, 265, 280], [40, 410, 450, None], [30, 300, None, None]],
        ))
        axes = owned_axes(january)
        self.assertEqual(axes["origin_labels"], ["2019", "2020", "2021"])
        self.assertEqual(axes["excluded"], [[1, 0, 0], [0, 0], [0]])
        self.assertEqual(axes["selected"], [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]])
        self.assertEqual(axes["user_entry_values"], [1.4, 1.1, 1.0, 1.02])
        self.assertEqual(axes["notes"], {"2019": {"(1) 1-13": "Large claim"}})
        self.assertEqual(normalize_dfm_method(january), january)

    def test_a_different_development_length_is_still_refused(self) -> None:
        june = june_method()
        with self.assertRaisesRegex(DfmContractError, "geometry changed"):
            recalculate_dfm_method(june, input_snapshot=snapshot(QUARTERS, ["12", "24", "36"], JUNE_VALUES))


if __name__ == "__main__":
    unittest.main()
