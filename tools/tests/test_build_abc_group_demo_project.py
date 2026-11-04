"""The ABC demo builder's renaming, path budget and selection rules."""

from __future__ import annotations

import unittest

from tools.build_abc_group_demo_project import (
    CLASS_MAP,
    PROJECTS_DIR,
    PROJECT,
    _exclude_covid_year,
    _primary_development_method,
    class_dir,
    combined_source_spec,
    decode_file_name,
    demo_formula,
    demo_name,
    encode_file_name,
    plan_result_selection,
)

# ArcRho writes "<file>.<uuid4>.tmp" beside a file (41 characters) under the
# 260-character Windows limit, and the longest template file name the classes
# keep is about 75 characters.
LONGEST_FILE_PART = len(r"\methods\DFM@G 22 A - ALAE_%2F_Gross Paid Loss DFM w_%2F_ Selected LDFs.json")


class DemoNamesTest(unittest.TestCase):
    def test_template_names_are_shortened_and_lose_their_stars(self) -> None:
        self.assertEqual(demo_name("Net Loss--Incurred Adjusted*"), "Net Loss--Incurred Adj 1")
        self.assertEqual(
            demo_name("Net Loss--Incurred Adjusted* - B&S Case Reserve Adequacy Adjustment"),
            "Net Loss--Incurred Adj 1 - B&S Case Adj",
        )
        self.assertEqual(demo_name("Total Earned Premium"), "Earned Premium")
        self.assertEqual(demo_name("C 91 -  Current Qtr Indicated"), "C 91 - Current Qtr Indicated")
        self.assertEqual(demo_name("B&S Case Reserve Adequacy Adjustment"), "B&S Case Reserve Adequacy Adjustment")

    def test_formulas_rename_quoted_and_bracketed_names_only(self) -> None:
        self.assertEqual(
            demo_formula('"P 06 Net Loss--Expected Net Loss % of Earned Premium" * (Earned Premium + Remaining Budget Premium)'),
            '"P 06 Net Loss--Expected Net Loss % of Earned Premium" * Earned Premium',
        )
        self.assertEqual(
            demo_formula("=[F 42 - Prior for BF Incurred][1:40] * [P 04 B-ALAE--Expected % of Ultimate Net Loss - Indicated][1:40]"),
            "=[F 42 - Prior for BF Incurred][1:40] * [P 04 B ALAE--Expected % of Ultimate Net Loss][1:40]",
        )

    def test_file_names_round_trip(self) -> None:
        name = "C 62 Reported *(CWOP/Reported) CDF"
        self.assertEqual(encode_file_name(name), "C 62 Reported _%2A_(CWOP_%2F_Reported) CDF")
        self.assertEqual(decode_file_name(encode_file_name(name)), name)

    def test_every_class_leaves_room_for_the_longest_file_and_its_temporary_copy(self) -> None:
        for path in CLASS_MAP.values():
            full = len(str(class_dir(PROJECT, path))) + LONGEST_FILE_PART + 41
            self.assertLessEqual(full, 259, path)
        self.assertEqual(len(set(CLASS_MAP.values())), 17)

    def test_combined_source_joins_four_tables_and_fills_the_missing_evaluation_month(self) -> None:
        spec = combined_source_spec()
        self.assertEqual([t["nickname"] for t in spec["tables"]], ["Loss", "Claim Counts", "Premium", "Exposure"])
        self.assertTrue(all(str(PROJECTS_DIR / PROJECT) in t["csv_path"] for t in spec["tables"]))
        months = next(k for k in spec["keys"] if k["name"] == "sys_yrmo")["map"]
        self.assertEqual(months["t3"], {"fill": "0"})


class SelectionRulesTest(unittest.TestCase):
    def test_liability_prefers_restated_then_adjusted_incurred(self) -> None:
        sources = [{"name": "F 13 - Paid DFM w/ Selected LDFs"}, {"name": "F 28 - BS Incurred DFM"},
                   {"name": "F 23 - Incurred DFM w/ Selected LDFs"}]
        kinds = ["dfm", "dfm", "dfm"]
        self.assertEqual(_primary_development_method(sources, kinds, {"liability": True}), 1)
        self.assertEqual(_primary_development_method(sources, kinds, {"liability": False}), 2)

    def test_covid_year_is_excluded_only_where_three_factors_remain(self) -> None:
        ratios = [[1.5, 1.1, 1.01, 1.0] for _ in range(4)] + [[1.6, 1.2]]  # 2017-2021; 2020 is row 3
        method = {"details_tab": {"origin_length": 12},
                  "ratios_tab": {"ratio_triangle": {"ratio_values": ratios,
                                                    "excluded": [[0] * len(row) for row in ratios]}}}
        self.assertTrue(_exclude_covid_year(method))
        excluded = method["ratios_tab"]["ratio_triangle"]["excluded"]
        self.assertEqual(excluded[3], [1, 1, 1, 1])
        method["ratios_tab"]["ratio_triangle"]["excluded"] = [[0] * len(row) for row in ratios]
        method["ratios_tab"]["ratio_triangle"]["ratio_values"][0][3] = None
        _exclude_covid_year(method)
        self.assertEqual(method["ratios_tab"]["ratio_triangle"]["excluded"][3], [1, 1, 1, 0])

    def test_result_selection_weights_follow_maturity(self) -> None:
        labels = [str(year) for year in range(2017, 2027)]
        method = {
            "details_tab": {"origin_length": 12},
            "method_tab": {"origin_labels": labels, "loaded_datasets": [
                {"name": "Net Loss--Paid", "data_format": "Triangle"},
                {"name": "F 23 - Incurred DFM w/ Selected LDFs", "method_type": "DFM"},
                {"name": "F 41 - BF Incurred", "method_type": "Bornhuetter Ferguson"},
            ]},
        }
        planned, notes = plan_result_selection(method, r"ABC Auto\PPA\NY\Exclusive\BI Total", [1.0] * 10)
        dfm, bf = (planned["method_tab"]["loaded_datasets"][i]["weights"] for i in (1, 2))
        self.assertEqual(dfm[:6], [1.0] * 6)
        self.assertEqual((dfm[6], bf[6]), (0.5, 0.5))
        self.assertEqual(bf[9], 1.0)
        self.assertIn("2017 to 2022", notes)


if __name__ == "__main__":
    unittest.main()
