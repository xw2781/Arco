"""The combine engine behind a combined source (docs/plans/combined_source_import.md, step 2)."""
from __future__ import annotations

import csv
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
TESTS_ROOT = Path(__file__).resolve().parent
for import_root in (PYTHON_API_SRC, FRONTEND_ROOT, TESTS_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import test_source_table_upload as upload_tests  # noqa: E402  (its fake SQL Server driver)
from arcrho_api import config as api_config  # noqa: E402
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS  # noqa: E402
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS  # noqa: E402
from app_server import config  # noqa: E402
from app_server.schemas.source_table import (  # noqa: E402
    CombinedSourceImportRequest,
    CombinedSourcePreviewRequest,
    CombinedSourceSaveRequest,
    CombinedTableDescribeRequest,
)
from app_server.services import combined_source_service as service  # noqa: E402
from app_server.services import (  # noqa: E402
    mssql_odbc,
    source_table_service,
    source_table_upload_service as upload,
    user_identity_service,
    workspace_read_client,
)

source_table_router = importlib.import_module("app_server.api.source_table_router")

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


# --- Client half: describe, preview, save and import (step 4) ---------------

PROJECT = "Demo Project"
GATEWAY = {"enabled": True, "url": "http://server:28767", "user": "alice", "secret": "x"}
MUTATIONS = ("source_table_upload_chunk", "source_table_upload_commit", "source_combined_save")
READS = ("source_table_settings", "source_table_upload_status")
OLD_TABLE = "LOB,Paid\nOld,1\n"


class CombinedSourceClientTests(unittest.TestCase):
    """The client reads and joins every table and uploads the result like a single table."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        temp = Path(self.temp.name)
        self.root = temp / "server"
        self.project = self.root / "projects" / PROJECT
        (self.project / "source").mkdir(parents=True)
        self.master = self.project / "source" / "master_table.csv"
        self.master.write_text(OLD_TABLE, encoding="utf-8")
        self.client_temp = temp / "client_temp"
        self.loss_csv = self._write_frame(temp / "client" / "loss.csv", loss_frame())
        ep = ep_frame()
        ep["Unnamed: 9"] = ""
        self.ep_csv = self._write_frame(temp / "client" / "ep.csv", ep)
        env = {key: value for key, value in os.environ.items() if key != api_config.RUNTIME_SERVER_ROOT_ENV}
        env.update({api_config.SERVER_ROOT_ENV: str(self.root), "USERNAME": "alice"})
        self.requests = []
        for patcher in (
            patch.dict(os.environ, env, clear=True),
            patch.object(config, "PROJECT_SETTINGS_DIR", str(self.root / "projects")),
            patch.object(config, "load_gateway_config", return_value=dict(GATEWAY)),
            patch.object(config, "get_client_temp_dir", return_value=str(self.client_temp)),
            patch.object(
                workspace_read_client,
                "cached_gateway_capabilities",
                return_value={"workspace_read_kinds": list(READS), "workspace_mutation_kinds": list(MUTATIONS)},
            ),
            patch.object(workspace_read_client, "post_signed_json", side_effect=self._gateway),
            patch.object(workspace_read_client, "_log"),
            patch.object(upload, "RAW_CHUNK_BYTES", 512),
            patch.object(upload, "safe_append_project_audit_log"),
            patch.object(source_table_service, "safe_append_project_audit_log"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        workspace_read_client.reset_capability_cache()
        self.addCleanup(workspace_read_client.reset_capability_cache)
        for state in (service._TABLE_CACHE, upload._PENDING):
            state.clear()
            self.addCleanup(state.clear)

    def _write_frame(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(path, index=False)
        return str(path)

    def _gateway(self, gateway_config, path, request_payload, *, timeout):
        request = json.loads(json.dumps(request_payload))
        self.requests.append(request)
        registry = WORKSPACE_READ_KINDS if "ReadKind" in request else WORKSPACE_MUTATION_KINDS
        spec = registry[request.get("ReadKind") or request["MutationKind"]]
        function = getattr(importlib.import_module(f"app_server.services.{spec.module}"), spec.function)
        with patch.dict(os.environ, {api_config.RUNTIME_SERVER_ROOT_ENV: str(self.root)}), \
                user_identity_service.acting_identity(request["UserName"]):
            answer = jsonable_encoder(function(**request["Kwargs"]))
        return answer, str(self.root), 0

    def _spec(self, **overrides):
        spec = notebook_spec(**overrides)
        spec["tables"] = [
            {**spec["tables"][0], "csv_path": self.loss_csv},
            {**spec["tables"][1], "csv_path": self.ep_csv},
        ]
        return spec

    def _mutations(self, kind):
        return [request["Kwargs"] for request in self.requests if request.get("MutationKind") == kind]

    def test_describe_reads_a_csv_and_reuses_it_until_the_file_changes(self):
        answer = source_table_router.describe_combined_table(
            CombinedTableDescribeRequest(table={"source_type": "csv", "csv_path": self.ep_csv})
        )
        self.assertEqual(answer, {
            "ok": True,
            "columns": ["Co_Cd", "PROD_CD", "acc_yrmo", "FACID", "Earned Premium"],
            "row_count": 72,
            "dropped_columns": ["Unnamed: 9"],
        })
        with patch.object(service, "read_table_text", wraps=service.read_table_text) as reads:
            service.describe_table({"source_type": "csv", "csv_path": self.ep_csv})
            self.assertEqual(reads.call_count, 0)
            Path(self.ep_csv).write_text("Co_Cd,EP\n07,1\n", encoding="utf-8")
            self.assertEqual(service.describe_table({"source_type": "csv", "csv_path": self.ep_csv})["row_count"], 1)
            self.assertEqual(reads.call_count, 1)

    def test_a_sql_server_table_is_read_once_until_a_refresh(self):
        driver = upload_tests._FakeOdbcDriver(["CO_CD", "Paid"], [("07", 1.5), ("08", None)])
        table = {"source_type": "mssql", "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Loss"}}
        with patch.object(mssql_odbc, "pyodbc", driver), patch.object(
            mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
        ), patch.object(driver, "connect", wraps=driver.connect) as connects:
            first = service.describe_table(table)
            service.describe_table(table)
            self.assertEqual(connects.call_count, 1)
            service.describe_table(table, refresh=True)
            self.assertEqual(connects.call_count, 2)
        self.assertEqual((first["columns"], first["row_count"]), (["CO_CD", "Paid"], 2))
        frame_, _ = service.fetch_table(table)
        self.assertEqual(frame_.values.tolist(), [["07", "1.5"], ["08", ""]])
        # The temporary copy stayed on this PC and is gone.
        self.assertEqual(list(self.client_temp.rglob("*.csv")), [])

    def test_preview_reports_tables_statistics_warnings_and_first_rows(self):
        answer = source_table_router.preview_combined_source(
            CombinedSourcePreviewRequest(project_name=PROJECT, combined=self._spec())
        )
        self.assertEqual([table["name"] for table in answer["tables"]], ["loss", "ep"])
        self.assertEqual(answer["tables"][1]["dropped_columns"], ["Unnamed: 9"])
        self.assertEqual(answer["stats"]["t4"]["added"], 72)
        self.assertEqual([warning["kind"] for warning in answer["warnings"]], ["filled_rows"])
        self.assertEqual((answer["row_count"], answer["column_count"]), (84, 6))
        self.assertEqual(len(answer["rows"]), 14)
        self.assertEqual(answer["columns"], ["CO_CD", "PROD_CD", "acc_yrmo", "sys_yrmo", "Paid_Loss", "Earned Premium"])
        json.dumps(answer)  # the route answer is plain JSON
        self.assertEqual(self.requests, [])  # a preview reads nothing on the server

    def test_preview_refuses_a_spec_that_cannot_be_combined(self):
        for spec, message in (
            (self._spec(keys=[]), "at least one key"),
            ({**self._spec(), "tables": self._spec()["tables"][:1]}, "at least two tables"),
            (self._spec(keys=[key("CO_CD", t1={"column": "CO_CD"}, t4={"column": "Nope"})]), "Nope in EP"),
        ):
            with self.subTest(message), self.assertRaises(HTTPException) as refused:
                service.preview_combined(PROJECT, spec)
            self.assertEqual(refused.exception.status_code, 400)
            self.assertIn(message, refused.exception.detail)

    def test_save_then_import_uploads_the_combined_table_and_commits_combined(self):
        saved = source_table_router.save_combined_source(
            CombinedSourceSaveRequest(project_name=PROJECT, combined=self._spec())
        )
        self.assertEqual(saved["source_type"], "combined")
        self.assertEqual([table["csv_path"] for table in saved["combined"]["tables"]], [self.loss_csv, self.ep_csv])
        self.assertIn("driver_available", saved)
        self.requests.clear()

        answer = source_table_router.import_combined_source(CombinedSourceImportRequest(project_name=PROJECT))

        expected = service.combine_tables(
            {"t1": loss_frame(), "t4": ep_frame()}, notebook_spec()
        )["frame"]
        imported, _ = service.read_table_text(str(self.master))
        self.assertEqual(imported.values.tolist(), expected.values.tolist())
        self.assertEqual(list(imported.columns), list(expected.columns))
        chunks = [kwargs["index"] for kwargs in self._mutations("source_table_upload_chunk")]
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks, list(range(len(chunks))))
        commits = self._mutations("source_table_upload_commit")
        self.assertEqual(len(commits), 1)
        commit = dict(commits[0])
        self.assertTrue(commit.pop("upload_id").startswith("srcup_"))
        self.assertEqual(commit, {
            "project_name": PROJECT,
            "source_type": "combined",
            "chunk_count": len(chunks),
            "byte_count": self.master.stat().st_size,
            "row_count": 84,
        })
        last = answer["last_import"]
        self.assertEqual((last["source_type"], last["source_label"], last["row_count"]), ("combined", "Combined: Loss, EP", 84))
        self.assertEqual(list(self.client_temp.rglob("*.csv")), [])

    def test_import_refuses_a_project_whose_combined_source_is_not_saved(self):
        with self.assertRaises(HTTPException) as refused:
            service.import_combined(PROJECT)
        self.assertEqual(refused.exception.status_code, 400)
        self.assertEqual(self._mutations("source_table_upload_chunk"), [])
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)


if __name__ == "__main__":
    unittest.main()
