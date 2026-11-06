"""The one-off tool that moves a method onto the origin length of the method it reads."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import reshape_mixed_period_methods as tool  # noqa: E402


def _sidecar(name, kind, period, precedents=()):
    return {"dataset_name": name, "source_kind": kind, "period_length": period,
            "precedents": [{"dataset_name": item} for item in precedents]}


def _sidecars(*items):
    return {tool._key(item["dataset_name"]): item for item in items}


class ConflictTests(unittest.TestCase):
    def test_cape_cod_and_dfm_refuse_any_other_length_selection_only_a_coarser_one(self) -> None:
        found = tool.conflicts(_sidecars(
            _sidecar("Paid", "engine", 12),
            _sidecar("F 23", "dfm", 3, ["Paid"]),
            _sidecar("C 12", "dfm", 12, ["Paid"]),
            _sidecar("F 53", "cape_cod", 12, ["Paid", "F 23"]),
            _sidecar("F 13", "dfm", 3, ["Paid", "C 12"]),
            _sidecar("C 91", "result_selection", 12, ["F 23", "Paid"]),  # finer candidate: readable
            _sidecar("C 92", "result_selection", 3, ["C 12", "F 23"]),  # coarser candidate: not
        ))
        self.assertEqual(
            sorted((method["dataset_name"], precedent["dataset_name"]) for method, precedent in found),
            [("C 92", "C 12"), ("F 13", "C 12"), ("F 53", "F 23")],
        )

    def test_another_class_precedent_is_left_alone(self) -> None:
        method = _sidecar("F 53", "cape_cod", 12)
        method["precedents"] = [{"dataset_name": "F 23", "reserving_class": "Other"}]
        self.assertEqual(tool.conflicts(_sidecars(method, _sidecar("F 23", "dfm", 3))), [])


class PayloadTests(unittest.TestCase):
    def test_weights_are_the_mean_over_each_years_quarters(self) -> None:
        old = ["2025 Q1", "2025 Q2", "2025 Q3", "2025 Q4", "2026 Q1", "2026 Q2"]
        self.assertEqual(tool.regroup_weights([1, 1, 0, 0, 1, None], old, ["2025", "2026"]), [0.5, 0.5])
        with self.assertRaises(ValueError):
            tool.regroup_weights([1], ["2025 Q1"], ["2025 H1"])

    def test_result_selection_takes_the_new_rows_and_blanks_what_the_save_rereads(self) -> None:
        method = {"details_tab": {"origin_length": 3}, "method_tab": {
            "origin_labels": ["2025 Q1", "2025 Q2"],
            "loaded_datasets": [{"name": "C 42", "weights": [1, 0], "values": [5, 6]}],
            "ratio_basis_values": [{"name": "Exposure", "values": [1, 2]}],
            "calculated_ultimate": [5, 6], "selected_ultimate": [5, 6], "ultimate_overrides": [None, 7],
        }}
        payload = tool.result_selection_payload(method, 12, ["2025"])
        tab = payload["method_tab"]
        self.assertEqual(payload["details_tab"]["origin_length"], 12)
        self.assertEqual(tab["loaded_datasets"][0]["weights"], [0.5])
        self.assertEqual((tab["loaded_datasets"][0]["values"], tab["ratio_basis_values"][0]["values"]), ([None], [None]))
        self.assertEqual(tab["ultimate_overrides"], [None])
        self.assertEqual(method["method_tab"]["origin_labels"], ["2025 Q1", "2025 Q2"])  # the input is not changed

    def test_new_dfm_takes_the_templates_rows_and_the_old_choice_in_every_column(self) -> None:
        settings = {"average_type": ["custom", "custom", "user_entry"], "periods": [None, 3, None]}
        old = {
            "json_format": "arcrho-dfm-v4",
            "details_tab": {"name": "F 13", "input_triangle": "Paid", "origin_length": 12, "development_length": 12},
            "ratios_tab": {"average_formulas": {
                "label": ["Volume - all", "Simple - 3", "User Entry"],
                "custom_average_formula_settings": settings,
                "selected": [[0, 0, 0], [1, 1, 0], [0, 0, 1]],
            }},
            "results_tab": {"ratio_basis_dataset": "C 12", "ultimate_ratio_decimal_places": 2},
        }
        template = {
            "details_tab": {"origin_length": 3, "development_length": 3},
            "data_tab": {"origin_labels": ["2025 Q1", "2025 Q2"], "development_labels": ["2m", "5m"]},
            "ratios_tab": {"average_formulas": {
                "label": ["Volume - all", "Simple - 12", "Benchmark"],
                "custom_average_formula_settings": {"average_type": ["custom", "custom", "user_entry"]},
                "selected": [[1, 1, 1, 1]] + [[0] * 4] * 2,
                "inputs": [[""] * 4, [""] * 4, ['="Simple - 12"'] * 4],
            }},
        }
        payload = tool.new_dfm_payload(old, template)
        formulas = payload["ratios_tab"]["average_formulas"]
        self.assertEqual(formulas["label"], ["Volume - all", "Simple - 12", "Benchmark"])
        self.assertEqual(formulas["selected"], [[0] * 4, [1] * 4, [0] * 4])
        self.assertEqual(formulas["inputs"][2], ['="Simple - 12"'] * 4)
        self.assertEqual((payload["details_tab"]["origin_length"], payload["details_tab"]["development_length"]), (3, 3))
        self.assertEqual(payload["data_tab"]["origin_labels"], ["2025 Q1", "2025 Q2"])
        self.assertEqual(payload["results_tab"]["ratio_basis_dataset"], "C 12")

    def test_new_cape_cod_keeps_its_settings_and_drops_every_per_origin_column(self) -> None:
        old = {"json_format": "arcrho-cape-cod-v4", "details_tab": {"name": "F 53", "origin_length": 12},
               "method_tab": {"origin_labels": ["2025", "2026"], "latest_dataset": "Paid", "latest_values": [1, 2],
                              "latest_source_revision": "sha256:x", "trend_rate": 0.02, "decay_factor": 0.75},
               "method_metadata": {"owned_revision": "sha256:y"}}
        payload = tool.new_cape_cod_payload(old, 3, ["2025 Q1", "2025 Q2"])
        tab = payload["method_tab"]
        self.assertEqual(payload["details_tab"]["origin_length"], 3)
        self.assertEqual((tab["origin_labels"], tab["latest_values"], tab["latest_source_revision"]),
                         (["2025 Q1", "2025 Q2"], [], ""))
        self.assertEqual((tab["latest_dataset"], tab["trend_rate"], tab["decay_factor"]), ("Paid", 0.02, 0.75))
        self.assertNotIn("method_metadata", payload)


if __name__ == "__main__":
    unittest.main()
