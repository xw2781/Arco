"""A move of the project dates reshapes every other method type and the
hand-entered datasets (docs/plans/project_dates_panel.md, step 3).

Rows follow their origin label and development columns keep their position,
through the one helper in ``arcrho_api.period_reshape``. The Development
Factor method has its own tests in ``test_dfm_reshape.py``.
"""

from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api.berquist_sherman_contract import (  # noqa: E402
    calculate_berquist_sherman_output,
    reshape_berquist_sherman_periods,
)
from arcrho_api.bootstrap_contract import BST_JSON_FORMAT, recalculate_bootstrap_method  # noqa: E402
from arcrho_api.bornhuetter_ferguson_contract import (  # noqa: E402
    BF_JSON_FORMAT,
    normalize_bornhuetter_ferguson_method,
    recalculate_bornhuetter_ferguson_method,
)
from arcrho_api.cape_cod_contract import CC_JSON_FORMAT, recalculate_cape_cod_method  # noqa: E402
from arcrho_api.dataset_link_contract import compact_sidecar_links  # noqa: E402
from arcrho_api.period_reshape import (  # noqa: E402
    REVIEW_CELL_LINKS,
    REVIEW_DROPPED_DATA,
    REVIEW_HAND_ENTERED,
    reshape_input_dataset,
)
from arcrho_api.result_selection_contract import reshape_result_selection_origins  # noqa: E402


OLD = ["2020", "2021", "2022", "2023"]
# A January move: 2020 drops out, 2024 arrives.
NEW = ["2021", "2022", "2023", "2024"]


def bf_payload() -> dict:
    return {
        "json_format": BF_JSON_FORMAT,
        "details_tab": {
            "name": "BF Ultimate",
            "method_type": "Bornhuetter Ferguson",
            "output_type": "Ultimate Loss",
            "dataset_category": "Loss",
            "origin_length": 12,
            "statistic_decimal_places": 1,
        },
        "method_tab": {
            "latest_dataset": "Paid Loss",
            "dfm_dataset": "Paid DFM Ultimate",
            "prior_datasets": [
                {"name": "Plan A", "values": [], "weights": [1, 0, 2, 1]},
                {"name": "Plan B", "values": [], "weights": [1, 1, 0, 3]},
            ],
            "origin_labels": list(OLD),
        },
        "method_metadata": {"last_modified": "2026-01-01T00:00:00Z", "data_refreshed": "2026-01-01T00:00:00Z"},
    }


def bf_snapshots(labels: list[str]) -> dict:
    latest = {label: 100 * (index + 1) for index, label in enumerate(["2020", "2021", "2022", "2023", "2024"])}
    return {
        "latest": {
            "name": "Paid Loss",
            "origin_labels": labels,
            "values": [[1, latest[label]] for label in labels],
            "mask": [[True, True] for _ in labels],
        },
        "dfm": {
            "name": "Paid DFM Ultimate",
            "origin_labels": labels,
            "values": [2 * latest[label] for label in labels],
            "percentage_developed": [0.5 for _ in labels],
        },
        "priors": [
            {"name": "Plan A", "origin_labels": labels, "values": [3 * latest[label] for label in labels]},
            {"name": "Plan B", "origin_labels": labels, "values": [5 * latest[label] for label in labels]},
        ],
    }


def cc_payload() -> dict:
    return {
        "json_format": CC_JSON_FORMAT,
        "details_tab": {
            "name": "CC Ultimate",
            "method_type": "Cape Cod",
            "output_type": "CC Ultimate",
            "dataset_category": "Loss",
            "origin_length": 12,
            "statistic_decimal_places": 0,
        },
        "method_tab": {
            "latest_dataset": "Paid Loss",
            "exposure_dataset": "Premium",
            "prior_ultimate_dataset": "Prior Ultimate",
            "prior_ultimate_mode": "latest_ultimates",
            "trend_rate": 0.05,
            "auto_trend_fit": False,
            "decay_factor": 1,
            "scaling_type": "percentage",
            "trend_factor_overrides": [None, 2.0, None, 3.0],
            "origin_labels": list(OLD),
        },
        "method_metadata": {"last_modified": "2026-01-01T00:00:00Z", "data_refreshed": "2026-01-01T00:00:00Z"},
    }


def cc_snapshots(labels: list[str]) -> dict:
    return {
        "latest": {"name": "Paid Loss", "origin_labels": labels, "values": [[50, 100] for _ in labels]},
        "exposure": {"name": "Premium", "origin_labels": labels, "values": [1000 for _ in labels]},
        "prior_ultimate": {
            "name": "Prior Ultimate",
            "origin_labels": labels,
            "values": [200 for _ in labels],
            "percentage_developed": [0.5 for _ in labels],
        },
    }


class OriginFollowsLabelMethodTests(unittest.TestCase):
    def test_bornhuetter_ferguson_weights_follow_their_origin(self) -> None:
        method = recalculate_bornhuetter_ferguson_method(bf_payload(), source_snapshots=bf_snapshots(OLD))
        moved = recalculate_bornhuetter_ferguson_method(method, source_snapshots=bf_snapshots(NEW))
        tab = moved["method_tab"]

        self.assertEqual(tab["origin_labels"], NEW)
        # 2021-2023 keep their weights; the new 2024 starts at the default 1.
        self.assertEqual(tab["prior_datasets"][0]["weights"], [0, 2, 1, 1])
        self.assertEqual(tab["prior_datasets"][1]["weights"], [1, 0, 3, 1])
        self.assertEqual(tab["latest_values"], [200, 300, 400, 500])
        # The stored ultimate still matches its embedded source snapshots.
        normalize_bornhuetter_ferguson_method(moved, require_complete=True)

    def test_cape_cod_trend_overrides_follow_their_origin(self) -> None:
        method = recalculate_cape_cod_method(cc_payload(), source_snapshots=cc_snapshots(OLD))
        moved = recalculate_cape_cod_method(method, source_snapshots=cc_snapshots(NEW))
        tab = moved["method_tab"]

        self.assertEqual(tab["origin_labels"], NEW)
        self.assertEqual(tab["trend_factor_overrides"], [2, None, 3, None])
        self.assertEqual(tab["trend_factors"][0], 2)
        self.assertEqual(tab["trend_factors"][2], 3)

    def test_result_selection_weights_and_overrides_follow_their_origin(self) -> None:
        payload = {
            "details_tab": {"name": "Selected", "output_type": "Selected", "origin_length": 12},
            "method_tab": {
                "origin_labels": list(OLD),
                "loaded_datasets": [
                    {"name": "DFM", "values": [10, 20, 30, 40], "weights": [1, 1, 0, 1]},
                    {"name": "BF", "values": [11, 21, 31, 41], "weights": [0, 1, 1, 0]},
                ],
                "ratio_basis_values": [{"name": "Premium", "values": [1, 2, 3, 4]}],
                "ultimate_overrides": [None, 99, None, None],
            },
        }
        reshape_result_selection_origins(payload, NEW)
        tab = payload["method_tab"]

        self.assertEqual(tab["origin_labels"], NEW)
        self.assertEqual(tab["loaded_datasets"][0]["weights"], [1, 0, 1, 0.0])
        self.assertEqual(tab["loaded_datasets"][1]["weights"], [1, 1, 0, 0.0])
        self.assertEqual(tab["loaded_datasets"][0]["values"], [20, 30, 40, None])
        self.assertEqual(tab["ratio_basis_values"][0]["values"], [2, 3, 4, None])
        self.assertEqual(tab["ultimate_overrides"], [99, None, None, None])
        self.assertEqual(tab["selected_ultimate"], [99, 31, 40, None])

    def test_bootstrap_scaling_choices_follow_their_origin(self) -> None:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "resq_bootstrap_f72a.json").read_text(encoding="utf-8")
        )
        case = fixture["methods"]["odp_single_scale"]
        origins = list(case["origin_labels"])
        periods = case["total_development_periods"]
        ratio_count = periods - 1

        def snapshot(labels: list[str], triangle: list[list[float]]) -> dict:
            return {
                "name": "Incurred DFM",
                "origin_labels": labels,
                "development_labels": [f"{5 + 12 * index}m" for index in range(ratio_count)],
                "origin_length": 12,
                "development_length": 12,
                "total_development_periods": periods,
                "observed_triangle": triangle,
                "selected_ratios": case["selected_ratios"],
            }

        scaling = ["additive", "multiplicative", "unscaled"] * len(origins)
        payload = {
            "json_format": BST_JSON_FORMAT,
            "details_tab": {"name": "Bootstrap", "output_type": "Ultimate", "dfm_method": "Incurred DFM"},
            "results_tab": {
                "target_scaling_methods": scaling[: len(origins)],
                "target_cvs": [index / 100 for index in range(len(origins))],
            },
        }
        triangle = deepcopy(case["observed_triangle"])
        method = recalculate_bootstrap_method(payload, dfm_snapshot=snapshot(origins, triangle), simulate=False)
        new_origins = origins[1:] + [str(int(origins[-1]) + 1)]
        new_triangle = triangle[1:] + [[triangle[-1][0]]]
        moved = recalculate_bootstrap_method(method, dfm_snapshot=snapshot(new_origins, new_triangle), simulate=False)
        results = moved["results_tab"]

        self.assertEqual(results["origin_labels"], new_origins)
        self.assertEqual(results["target_scaling_methods"], scaling[1: len(origins)] + ["additive"])
        self.assertEqual(results["target_cvs"], [index / 100 for index in range(1, len(origins))] + [0])


class BerquistShermanReshapeTests(unittest.TestCase):
    def test_settlement_rate_rows_follow_origin_and_columns_keep_position(self) -> None:
        method = {
            "json_format": "arcrho-berquist-sherman-sr-v4",
            "method_tab": {
                "origin_labels": ["2021", "2022", "2023"],
                "development_labels": ["12m", "24m", "36m"],
                "selected_proportion_settled": [0.2, 0.5, 0.9],
                "selected_proportion_is_default": [False, True, False],
                "selected_adjustment": [
                    ["all", "loess", "pairs"],
                    ["unadjusted", "all", None],
                    ["loess", None, None],
                ],
            },
        }
        moved = reshape_berquist_sherman_periods(method, ["2022", "2023", "2024"], ["12m", "24m", "36m", "48m"])
        tab = moved["method_tab"]

        self.assertEqual(tab["origin_labels"], ["2022", "2023", "2024"])
        self.assertEqual(tab["development_labels"], ["12m", "24m", "36m", "48m"])
        self.assertEqual(tab["selected_proportion_settled"], [0.2, 0.5, 0.9, None])
        self.assertEqual(tab["selected_proportion_is_default"], [False, True, False, True])
        self.assertEqual(tab["selected_adjustment"], [
            ["unadjusted", "all", None, None],
            ["loess", None, None, None],
            [None, None, None, None],
        ])
        self.assertEqual(method["method_tab"]["origin_labels"], ["2021", "2022", "2023"])

        paid = [[100, 180, 200, 210], [110, 190, 205], [120, 200], [130]]
        closed = [[10, 18, 20, 21], [11, 19, 20.5], [12, 20], [13]]
        output = calculate_berquist_sherman_output(
            {**moved, "method_tab": {**tab, "origin_labels": ["2021"] + tab["origin_labels"]}},
            {"paid_claims": paid, "closed_claim_numbers": closed, "ultimate_claim_numbers": [22, 22, 22, 22]},
        )
        self.assertEqual(len(output["output"]), 4)

    def test_case_reserve_adequacy_columns_keep_position(self) -> None:
        method = {
            "json_format": "arcrho-berquist-sherman-cra-v4",
            "method_tab": {
                "origin_labels": ["2021", "2022", "2023"],
                "development_labels": ["12m", "24m", "36m"],
                "inflation_selection": ["user", "case_all", "user"],
                "user_inflation": [0.1, 0.0, 0.2],
                "average_case_reserve_selection": ["loess", "latest", "user"],
                "user_average_case_reserves": [0.0, 0.0, 500.0],
            },
        }
        tab = reshape_berquist_sherman_periods(method, ["2022", "2023"], ["12m", "24m"])["method_tab"]

        self.assertEqual(tab["inflation_selection"], ["user", "case_all"])
        self.assertEqual(tab["user_inflation"], [0.1, 0.0])
        self.assertEqual(tab["average_case_reserve_selection"], ["loess", "latest"])
        grown = reshape_berquist_sherman_periods(method, ["2022", "2023"], ["12m", "24m", "36m", "48m"])["method_tab"]
        self.assertEqual(grown["inflation_selection"], ["user", "case_all", "user", "paid_all"])
        self.assertEqual(grown["user_average_case_reserves"], [0.0, 0.0, 500.0, 0.0])


class InputDatasetReshapeTests(unittest.TestCase):
    def test_vector_with_index_labels_moves_rows_and_its_formula_link(self) -> None:
        sidecar = compact_sidecar_links({
            "source_kind": "input",
            "data_format": "Vector",
            "origin_labels": ["1", "2", "3", "4"],
            "development_labels": ["Value"],
            "formula_links": [{
                "formula": "=[Other][1:4]",
                "target_cells": [
                    {"row": row, "column": 0, "result_row": row, "result_column": 0} for row in range(4)
                ],
            }],
        })
        result = reshape_input_dataset(sidecar, [[1.0], [2.0], [3.0], [4.0]], OLD, NEW)

        self.assertEqual(result["values"], [[2.0], [3.0], [4.0], [None]])
        self.assertEqual(result["sidecar"]["origin_labels"], ["1", "2", "3", "4"])
        # Targets move up with their origin, the 2020 target goes, and the
        # result cell each one reads (the formula text) is not rewritten.
        self.assertEqual(result["sidecar"]["formula_links"][0]["target_cells"], [[0, 0, 3, 1, 1, 0]])
        self.assertEqual(result["sidecar"]["formula_links"][0]["formula"], "=[Other][1:4]")
        self.assertEqual(result["review"], [REVIEW_HAND_ENTERED, REVIEW_CELL_LINKS, REVIEW_DROPPED_DATA])
        self.assertEqual(sidecar["formula_links"][0]["target_cells"], [[0, 0, 4, 1, 0, 0]])

    def test_triangle_excel_cells_keep_their_absolute_position(self) -> None:
        sidecar = compact_sidecar_links({
            "source_kind": "input",
            "data_format": "Triangle",
            "origin_labels": ["2021", "2022", "2023"],
            "development_labels": ["12m", "24m", "36m"],
            "external_links": [{
                "workbook": "Inputs.xlsx",
                "target_cells": [{"row": 1, "column": 0, "source_cell": "B2"}],
            }],
        })
        values = [[11, 12, 13], [21, 22, None], [31, None, None]]
        result = reshape_input_dataset(
            sidecar, values, ["2021", "2022", "2023"], ["2022", "2023", "2024"], ["12m", "24m", "36m", "48m"]
        )

        self.assertEqual(result["sidecar"]["origin_labels"], ["2022", "2023", "2024"])
        self.assertEqual(result["sidecar"]["development_labels"], ["12m", "24m", "36m", "48m"])
        # 2022's typed value moves up a row; the Excel cell (row 1, column 0)
        # keeps its value where it was and does not travel with 2022.
        self.assertEqual(result["values"], [
            [None, 22, None, None],
            [21, None, None, None],
            [None, None, None, None],
        ])
        self.assertEqual(result["sidecar"]["external_links"], sidecar["external_links"])
        self.assertEqual(result["review"], [REVIEW_HAND_ENTERED, REVIEW_CELL_LINKS, REVIEW_DROPPED_DATA])

    def test_unlinked_vector_with_nothing_dropped_is_listed_as_hand_entered(self) -> None:
        sidecar = {"origin_labels": ["1", "2"], "development_labels": ["Value"]}
        result = reshape_input_dataset(sidecar, [[None], [5]], ["2020", "2021"], ["2021", "2022", "2023"])

        self.assertEqual(result["values"], [[5], [None], [None]])
        self.assertEqual(result["sidecar"]["origin_labels"], ["1", "2", "3"])
        self.assertEqual(result["review"], [REVIEW_HAND_ENTERED])


if __name__ == "__main__":
    unittest.main()
