"""The combine engine behind a combined source (docs/plans/combined_source_import.md, step 2)."""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
for import_root in (PYTHON_API_SRC, FRONTEND_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app_server.services import combined_source_service as service

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

ACC = ["202604", "202605", "202606", "202607", "202608", "202609"]
PRODS = ["PPA_BI", "PPA_PD", "CMP_BI", "CMP_PD", "HO", "UMB"]


def frame(rows, columns):
    return pd.DataFrame(rows, columns=columns, dtype=str)


def loss_frame():
    """Base: one row per product and accident/system month pair, sys >= acc."""
    rows = []
    for prod in PRODS[:2]:
        for acc in ACC[:3]:
            for sys_month in ACC[:3]:
                if sys_month >= acc:
                    rows.append(["07", prod, acc, sys_month, "1000"])
    return frame(rows, ["CO_CD", "PROD_CD", "acc_yrmo", "sys_yrmo", "Paid_Loss"])


def ep_frame():
    """Premium: no system month, mixed-case company code, 72 rows."""
    rows = [[co, prod, acc, "F100", "500"] for co in ("07", "08") for prod in PRODS for acc in ACC]
    return frame(rows, ["Co_Cd", "PROD_CD", "acc_yrmo", "FACID", "Earned Premium"])


def table(table_id, nickname="", csv_name=None):
    return {"id": table_id, "nickname": nickname, "source_type": "csv", "csv_path": f"C:\\data\\{csv_name or table_id}.csv"}


def key(name, **entries):
    return {"name": name, "map": entries}


def notebook_spec(**overrides):
    spec = {
        "tables": [table("t1", "Loss"), table("t4", "EP")],
        "keys": [
            key("CO_CD", t1={"column": "CO_CD"}, t4={"column": "Co_Cd"}),
            key("PROD_CD", t1={"column": "PROD_CD"}, t4={"column": "PROD_CD"}),
            key("acc_yrmo", t1={"column": "acc_yrmo"}, t4={"column": "acc_yrmo"}),
            key("sys_yrmo", t1={"column": "sys_yrmo"}, t4={"fill": "0"}),
        ],
        "rows": {"t4": "all"},
        "exclude": {"t4": ["FACID"]},
        "rename": {},
    }
    spec.update(overrides)
    return spec


def kinds(result):
    return [warning["kind"] for warning in result["warnings"]]


class ReadTableTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)

    def write(self, name, rows):
        path = Path(self.temp.name) / name
        with open(path, "w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
        return str(path)

    def test_drops_empty_unnamed_columns_and_blank_rows(self):
        path = self.write("ep.csv", [
            ["Co_Cd", "Amount", "Unnamed: 9", "Unnamed: 3"],
            ["07", "00123", "", "x"],
            ["", "", "", ""],
            ["08", "1.10", "", ""],
        ])
        frame_, dropped = service.read_table_text(path)
        self.assertEqual(dropped, ["Unnamed: 9"])
        self.assertEqual(list(frame_.columns), ["Co_Cd", "Amount", "Unnamed: 3"])
        self.assertEqual(frame_["Amount"].tolist(), ["00123", "1.10"])

    def test_values_survive_the_round_trip_unchanged(self):
        source = self.write("in.csv", [["CO_CD", "v"], ["007", "00123"], ["08", "1.10"], ["09", "NA"]])
        frame_, _ = service.read_table_text(source)
        out = Path(self.temp.name) / "out.csv"
        service.write_combined_csv(frame_, str(out))
        again, _ = service.read_table_text(str(out))
        self.assertEqual(again.values.tolist(), [["007", "00123"], ["08", "1.10"], ["09", "NA"]])


class CombineTablesTests(unittest.TestCase):
    def test_notebook_case_filled_key_adds_premium_rows_on_their_own(self):
        result = service.combine_tables({"t1": loss_frame(), "t4": ep_frame()}, notebook_spec())
        out = result["frame"]
        self.assertEqual(list(out.columns), ["CO_CD", "PROD_CD", "acc_yrmo", "sys_yrmo", "Paid_Loss", "Earned Premium"])
        self.assertEqual(result["stats"]["t1"], {"read": 12})
        self.assertEqual(result["stats"]["t4"], {
            "read": 72, "matched": 0, "added": 72, "left_out": 0, "base_rows_dropped": 0, "max_repeat": 0,
        })
        self.assertEqual(len(out), 84)
        premium_rows = out[out["sys_yrmo"] == "0"]
        self.assertEqual(len(premium_rows), 72)
        self.assertEqual(set(premium_rows["Paid_Loss"]), {""})
        self.assertEqual(set(premium_rows["CO_CD"]), {"07", "08"})
        self.assertEqual(out["Paid_Loss"].iloc[0], "1000")
        self.assertEqual(kinds(result), ["filled_rows"])
        self.assertEqual(result["warnings"][0]["fills"], {"sys_yrmo": "0"})
        self.assertEqual(result["warnings"][0]["added"], 72)

    def _premium_on_base(self, rule):
        base = loss_frame()
        right = frame([["07", "PPA_BI", "202604", "9"], ["07", "XX", "202604", "8"]], ["CO_CD", "PROD_CD", "acc_yrmo", "Premium"])
        spec = {
            "tables": [table("t1"), table("t2")],
            "keys": [
                key("CO_CD", t1={"column": "CO_CD"}, t2={"column": "CO_CD"}),
                key("PROD_CD", t1={"column": "PROD_CD"}, t2={"column": "PROD_CD"}),
                key("acc_yrmo", t1={"column": "acc_yrmo"}, t2={"column": "acc_yrmo"}),
                key("sys_yrmo", t1={"column": "sys_yrmo"}, t2={"any": True}),
            ],
            "rows": {"t2": rule},
        }
        return service.combine_tables({"t1": base, "t2": right}, spec)

    def test_any_key_repeats_rows_and_warns(self):
        result = self._premium_on_base("base")
        stats = result["stats"]["t2"]
        # PPA_BI 202604 has three system months in the base.
        self.assertEqual(stats, {"read": 2, "matched": 1, "added": 0, "left_out": 1, "base_rows_dropped": 0, "max_repeat": 3})
        self.assertEqual(len(result["frame"]), 12)
        repeat = [w for w in result["warnings"] if w["kind"] == "repeat"]
        self.assertEqual(repeat[0]["any_keys"], ["sys_yrmo"])
        self.assertEqual(repeat[0]["max_repeat"], 3)

    def test_match_rule_keeps_only_matched_rows(self):
        result = self._premium_on_base("match")
        self.assertEqual(len(result["frame"]), 3)
        self.assertEqual(result["stats"]["t2"]["base_rows_dropped"], 9)
        self.assertEqual(set(result["frame"]["Premium"]), {"9"})

    def test_all_rule_adds_unmatched_rows_after_the_base(self):
        result = self._premium_on_base("all")
        out = result["frame"]
        self.assertEqual(len(out), 13)
        self.assertEqual(out.iloc[-1].tolist(), ["07", "XX", "202604", "", "", "8"])
        self.assertEqual(result["stats"]["t2"]["added"], 1)
        self.assertEqual(result["stats"]["t2"]["left_out"], 0)
        # The base keeps its own order ahead of the added row.
        self.assertEqual(out.iloc[:12]["sys_yrmo"].tolist(), loss_frame()["sys_yrmo"].tolist())

    def test_yyyy_mm_mismatch_is_detected_and_fixed_by_convert(self):
        budget = frame([["07", "PPA_BI", "2026-04", "77"]], ["Co_Cd", "PROD_CD", "acc_yrmo", "Budget Premium"])
        spec = {
            "tables": [table("t1", "Loss"), table("t5", "Budget")],
            "keys": [
                key("CO_CD", t1={"column": "CO_CD"}, t5={"column": "Co_Cd"}),
                key("PROD_CD", t1={"column": "PROD_CD"}, t5={"column": "PROD_CD"}),
                key("acc_yrmo", t1={"column": "acc_yrmo"}, t5={"column": "acc_yrmo"}),
                key("sys_yrmo", t1={"column": "sys_yrmo"}, t5={"any": True}),
            ],
            "rows": {"t5": "base"},
        }
        frames = {"t1": loss_frame(), "t5": budget}
        result = service.combine_tables(frames, spec)
        mismatch = [w for w in result["warnings"] if w["kind"] == "format_mismatch"]
        self.assertEqual(len(mismatch), 1)
        self.assertEqual(mismatch[0]["key"], "acc_yrmo")
        self.assertEqual(mismatch[0]["sample"], "2026-04")
        self.assertEqual(mismatch[0]["base_sample"], "202604")
        self.assertEqual(mismatch[0]["matched"], 0)
        self.assertEqual(mismatch[0]["fix"], {"convert": "yyyymm"})

        spec["keys"][2]["map"]["t5"]["convert"] = "yyyymm"
        fixed = service.combine_tables(frames, spec)
        self.assertNotIn("format_mismatch", kinds(fixed))
        self.assertEqual(fixed["stats"]["t5"]["matched"], 1)
        self.assertEqual((fixed["frame"]["Budget Premium"] == "77").sum(), 3)

    def test_exclude_and_rename(self):
        spec = notebook_spec(rename={"t4": {"Earned Premium": "EP_Amount"}})
        result = service.combine_tables({"t1": loss_frame(), "t4": ep_frame()}, spec)
        self.assertNotIn("FACID", result["frame"].columns)
        self.assertIn("EP_Amount", result["frame"].columns)
        facid = [p for p in result["plan"] if p["column"] == "FACID"][0]
        self.assertTrue(facid["off"])

    def test_name_clash_suffix_with_and_without_nickname(self):
        base = frame([["07", "1"]], ["CO_CD", "Amount"])
        second = frame([["07", "2"]], ["CO_CD", "amount"])
        third = frame([["07", "3"]], ["CO_CD", "Amount"])
        spec = {
            "tables": [table("t1", "Loss"), table("t2", "Earned Prem"), table("t3")],
            "keys": [key("CO_CD", t1={"column": "CO_CD"}, t2={"column": "CO_CD"}, t3={"column": "CO_CD"})],
        }
        result = service.combine_tables({"t1": base, "t2": second, "t3": third}, spec)
        self.assertEqual(list(result["frame"].columns), ["CO_CD", "Amount", "amount_Earned_Prem", "Amount_T3"])
        self.assertEqual(result["frame"].values.tolist(), [["07", "1", "2", "3"]])
        clashes = [w for w in result["warnings"] if w["kind"] == "name_clash"]
        self.assertEqual([w["master"] for w in clashes], ["amount_Earned_Prem", "Amount_T3"])
        self.assertEqual(clashes[1]["table"], "t3")

    def test_renamed_column_takes_no_suffix(self):
        base = frame([["07", "1"]], ["CO_CD", "Amount"])
        second = frame([["07", "2"]], ["CO_CD", "Amount"])
        spec = {
            "tables": [table("t1"), table("t2")],
            "keys": [key("CO_CD", t1={"column": "CO_CD"}, t2={"column": "CO_CD"})],
            "rename": {"t2": {"Amount": "Budget"}},
        }
        result = service.combine_tables({"t1": base, "t2": second}, spec)
        self.assertEqual(list(result["frame"].columns), ["CO_CD", "Amount", "Budget"])
        self.assertNotIn("name_clash", kinds(result))

    def test_text_values_survive_the_join_unchanged(self):
        base = frame([["007", "00123"]], ["CO_CD", "A"])
        second = frame([["007", "1.10"], ["008", "1.0"]], ["CO_CD", "B"])
        spec = {
            "tables": [table("t1"), table("t2")],
            "keys": [key("CO_CD", t1={"column": "CO_CD"}, t2={"column": "CO_CD"})],
        }
        out = service.combine_tables({"t1": base, "t2": second}, spec)["frame"]
        self.assertEqual(out.values.tolist(), [["007", "00123", "1.10"], ["008", "", "1.0"]])


class PreviewRowsTests(unittest.TestCase):
    def test_sorted_by_keys_and_limited(self):
        result = service.combine_tables({"t1": loss_frame(), "t4": ep_frame()}, notebook_spec())
        rows = service.preview_rows(result["frame"], ["CO_CD", "PROD_CD", "acc_yrmo", "sys_yrmo"], limit=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["PROD_CD"], "CMP_BI")
        self.assertEqual(rows[0]["sys_yrmo"], "0")
        self.assertEqual([row["acc_yrmo"] for row in rows], ["202604", "202605", "202606"])


if __name__ == "__main__":
    unittest.main()
