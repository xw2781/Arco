from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api.dfm_contract import DFM_JSON_FORMAT, recalculate_dfm_method  # noqa: E402
from arcrho_mcp import tools  # noqa: E402
from arcrho_mcp.reads import AGENT_READ_KINDS, agent_read_catalog  # noqa: E402
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS  # noqa: E402

HAS_MCP = importlib.util.find_spec("mcp") is not None


def dfm_method() -> dict:
    payload = {
        "json_format": DFM_JSON_FORMAT,
        "details_tab": {
            "name": "Paid DFM", "output_type": "Paid Ultimate", "output_dataset": "Paid Selected",
            "input_triangle": "Paid Loss", "origin_length": 12, "development_length": 12, "decimal_places": 4,
        },
        "data_tab": {},
        "ratios_tab": {
            "ratio_triangle": {"excluded": []},
            "average_formulas": {
                "label": ["Volume - all", "Simple - all"],
                "custom_average_formula_settings": {
                    "average_type": ["custom", "custom"], "base": ["volume", "simple"],
                    "periods": ["all", "all"], "exclude": [0, 0],
                },
                "selected": [[1, 1, 1], [0, 0, 0]],
            },
        },
        "results_tab": {"ratio_basis_dataset": "", "ultimate_ratio_decimal_places": 2},
        "method_metadata": {"last_modified": "2026-01-01T00:00:00Z", "data_refreshed": "2026-01-01T00:00:00Z"},
    }
    values = [[100, 150, 180], [200, 260, None], [400, None, None]]
    return recalculate_dfm_method(payload, input_snapshot={
        "name": "Paid Loss", "origin_labels": ["2020", "2021", "2022"],
        "development_labels": ["12m", "24m", "36m"], "values": values,
        "mask": [[item is not None for item in row] for row in values],
        "data_format": "Triangle", "number_format": "#,##0", "decimal_places": 0, "revision": "input:r1",
    })


def result_selection_method() -> dict:
    return {"method_tab": {
        "origin_labels": ["2020", "2021"],
        "loaded_datasets": [
            {"name": "Paid DFM", "values": [100.0, 200.0], "weights": [1.0, 1.0]},
            {"name": "Incurred DFM", "values": [300.0, 400.0], "weights": [0.0, 0.0]},
        ],
        "ultimate_overrides": [None, None],
        "calculated_ultimate": [100.0, 200.0],
        "selected_ultimate": [100.0, 200.0],
    }}


class FakeGateway:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls = []

    def read(self, kind, **arguments):
        self.calls.append((kind, arguments))
        return self.responses[kind]


def gateway() -> FakeGateway:
    return FakeGateway({
        "dfm_method_load": {"method": dfm_method(), "method_revision": "dfm:r1"},
        "result_selection_load": {"method": result_selection_method(), "method_revision": "rs:r1"},
        "project_names": {"projects": ["Fake"]},
        "dataset_index": {"files": [
            {"name": "Paid Selected", "method_name": "Paid DFM", "method_type": "DFM"},
            {"name": "Paid Loss", "method_name": "", "method_type": "None"},
        ]},
    })


class AgentReadTests(unittest.TestCase):
    def test_every_method_load_is_an_agent_read_and_simulations_are_not(self):
        method_loads = {name for name, spec in WORKSPACE_READ_KINDS.items()
                        if spec.function.startswith("load_") and "method_name" in spec.required}
        self.assertTrue(method_loads <= set(AGENT_READ_KINDS))
        self.assertNotIn("bootstrap_simulate", AGENT_READ_KINDS)
        self.assertEqual(agent_read_catalog()["dfm_method_load"]["required"],
                         ("project_name", "reserving_class", "method_name"))

    def test_arco_read_refuses_a_read_outside_the_list(self):
        fake = gateway()
        with self.assertRaisesRegex(ValueError, "not an agent read"):
            tools.arco_read(fake, "bootstrap_simulate", {})
        self.assertEqual(fake.calls, [])

    def test_list_methods_keeps_methods_only(self):
        self.assertEqual(tools.list_methods(gateway(), "Fake", "Auto"),
                         [{"method_name": "Paid DFM", "method_type": "DFM"}])


class DfmPreviewTests(unittest.TestCase):
    def test_empty_edit_reproduces_the_loaded_results(self):
        preview = tools.preview_dfm_edit(gateway(), "Fake", "Auto", "Paid DFM", {})
        self.assertEqual(preview["method_revision"], "dfm:r1")
        self.assertEqual(preview["developments"], [])
        self.assertTrue(all(row["change"] == 0 for row in preview["ultimates"]))

    def test_exclusion_and_average_choice_move_the_ldf_and_ultimates(self):
        summary = tools.get_dfm_summary(gateway(), "Fake", "Auto", "Paid DFM")
        first = summary["developments"][0]
        self.assertEqual(first["selected_average"], "Volume - all")
        preview = tools.preview_dfm_edit(gateway(), "Fake", "Auto", "Paid DFM", {
            "exclude": [{"origin": "2021", "development": first["development"]}],
        })
        self.assertEqual(preview["excluded"], [{"origin": "2021", "development": first["development"]}])
        self.assertAlmostEqual(preview["developments"][0]["after"]["ldf"], 1.5)
        self.assertGreater(preview["ultimates"][2]["change"], 0)
        preview = tools.preview_dfm_edit(gateway(), "Fake", "Auto", "Paid DFM", {
            "select_average": [{"development": first["development"], "average": "simple - all"}],
        })
        self.assertEqual(preview["developments"][0]["after"]["selected_average"], "Simple - all")

    def test_unknown_labels_and_operations_are_refused(self):
        method = dfm_method()
        development = method["ratios_tab"]["ratio_triangle"]["development_labels"][0]
        for edit, message in (
            ({"exclude": [{"origin": "1999", "development": development}]}, "No origin labelled '1999'"),
            ({"exclude": [{"origin": "2020", "development": "99-111"}]}, "No development"),
            ({"exclude": [{"origin": "2022", "development": development}]}, "No ratio at origin '2022'"),
            ({"select_average": [{"development": development, "average": "Volume - 3"}]}, "No average"),
            ({"set_tail": 1.05}, "Unknown DFM edit operation: set_tail"),
        ):
            with self.subTest(edit=edit), self.assertRaisesRegex(ValueError, message):
                tools.apply_dfm_edit(method, edit)


class ResultSelectionPreviewTests(unittest.TestCase):
    def test_weights_change_the_selected_ultimate(self):
        preview = tools.preview_result_selection_weights(gateway(), "Fake", "Auto", "Selected", [
            {"source": "Incurred DFM", "weight": 1, "origin": "2021"},
        ])
        self.assertEqual([row["after"] for row in preview["origins"]], [100.0, 300.0])
        self.assertEqual(preview["total_selected_ultimate"], {"before": 300.0, "after": 400.0})
        preview = tools.preview_result_selection_weights(gateway(), "Fake", "Auto", "Selected", [
            {"source": "Paid DFM", "weight": 0}, {"source": "Incurred DFM", "weight": 2},
        ])
        self.assertEqual([row["after"] for row in preview["origins"]], [300.0, 400.0])

    def test_unknown_source_and_negative_weight_are_refused(self):
        method = result_selection_method()
        with self.assertRaisesRegex(ValueError, "No source labelled 'BF'"):
            tools.apply_weight_changes(method, [{"source": "BF", "weight": 1}])
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            tools.apply_weight_changes(method, [{"source": "Paid DFM", "weight": -1}])


@unittest.skipUnless(HAS_MCP, "the mcp extra is not installed")
class ServerTests(unittest.TestCase):
    def call(self, name, arguments):
        from arcrho_mcp.server import build_server

        return asyncio.run(build_server(gateway()).call_tool(name, arguments))

    def test_lists_arrive_as_one_named_result(self):
        result = self.call("list_projects", {})
        self.assertEqual(json.loads(result.content[0].text), {"projects": ["Fake"]})

    def test_a_refused_label_reaches_the_agent(self):
        from mcp.server.mcpserver.exceptions import ToolError

        with self.assertRaisesRegex(ToolError, "No origin labelled '1999'"):
            self.call("preview_dfm_edit", {
                "project_name": "Fake", "reserving_class": "Auto", "method_name": "Paid DFM",
                "edit": {"exclude": [{"origin": "1999", "development": "x"}]},
            })


if __name__ == "__main__":
    unittest.main()
