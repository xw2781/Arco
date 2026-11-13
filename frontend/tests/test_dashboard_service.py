"""Dashboards: files, library, data tables, and where each table is read.

Project data reaches a dashboard through two registered Server-hosted reads; a
CSV file and a SQL query are read on this PC. The tables all share one shape.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
for path in (FRONTEND_ROOT, REPOSITORY_ROOT / "python-api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_workspace_read_contract import (  # noqa: E402
    WORKSPACE_READ_KINDS,
    build_workspace_read_request,
)
from app_server import config  # noqa: E402
from app_server.services import (  # noqa: E402
    dashboard_data_service,
    dashboard_service,
    workspace_read_client,
)

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
GATEWAY = {"enabled": True, "url": "http://server:28767", "user": "alice", "secret": "x"}


def _dashboard(name: str = "Review") -> dict:
    return {
        "format": "arco-dashboard",
        "name": name,
        "description": "Quarterly view",
        "sources": [{"id": "src1", "kind": "arco_datasets", "projects": [{"name": "P1", "label": "May"}, "P2"]}],
        "pages": [{"id": "p1", "name": "Overview", "widgets": [{"id": "w1", "type": "bar"}]}],
    }


def _loaded(dataset: str, triangle: bool) -> dict:
    if triangle:
        return {
            "data_format": "Triangle",
            "cumulative": True,
            "decimal_places": 0,
            "origin_labels": ["2024", "2025"],
            "dev_labels": ["8m", "20m"],
            "values": [[10.0, 30.0], [5.0, None]],
        }
    return {
        "data_format": "Vector",
        "cumulative": None,
        "decimal_places": 0,
        "origin_labels": ["2024", "2025"],
        "dev_labels": ["Ultimate"],
        "values": [[50.0], [40.0]],
    }


class DashboardFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.user_dir = Path(self.temp.name) / "dashboards"
        self.samples_dir = Path(self.temp.name) / "samples"
        self.samples_dir.mkdir()
        for target, value in (("DASHBOARD_DIR", str(self.user_dir)), ("DEFAULT_DASHBOARDS_DIR", self.samples_dir)):
            patcher = patch.object(config, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_save_load_list_rename_and_delete(self) -> None:
        saved = dashboard_service.save_dashboard("Review", _dashboard())
        path = Path(saved["path"])
        self.assertEqual(path.name, "Review.arcdash")
        self.assertEqual(dashboard_service.load_dashboard(saved["path"])["data"]["name"], "Review")

        listed = dashboard_service.list_dashboards()
        self.assertEqual(listed["samples"], [])
        summary = listed["dashboards"][0]
        self.assertEqual(
            (summary["name"], summary["page_count"], summary["widget_count"], summary["projects"], summary["sample"]),
            ("Review", 1, 1, ["P1", "P2"], False),
        )

        renamed = dashboard_service.save_dashboard("Review Q3", _dashboard(), prev_path=saved["path"])
        self.assertFalse(path.exists())
        self.assertTrue(Path(renamed["path"]).exists())

        dashboard_service.save_dashboard("Other", _dashboard())
        with self.assertRaises(HTTPException) as refused:
            dashboard_service.save_dashboard("Other", _dashboard(), prev_path=renamed["path"])
        self.assertEqual(refused.exception.status_code, 409)
        self.assertTrue(Path(renamed["path"]).exists())

        dashboard_service.delete_dashboard(renamed["path"])
        self.assertFalse(Path(renamed["path"]).exists())

    def test_a_saved_table_is_written_one_row_per_line(self) -> None:
        data = _dashboard()
        data["sources"][0]["extract"] = {"columns": [{"name": "A"}], "rows": [["x", 1.5], ["y", None]]}
        text = Path(dashboard_service.save_dashboard("Rows", data)["path"]).read_text(encoding="utf-8")
        self.assertIn('["x", 1.5],\n', text)
        self.assertEqual(json.loads(text)["sources"][0]["extract"]["rows"], [["x", 1.5], ["y", None]])

    def test_a_sample_is_listed_and_saving_it_never_touches_the_shipped_file(self) -> None:
        sample = self.samples_dir / "Sample.arcdash"
        sample.write_text(json.dumps(_dashboard("Sample")), encoding="utf-8")
        before = sample.read_bytes()
        loaded = dashboard_service.load_dashboard(str(sample))
        self.assertTrue(loaded["sample"])
        self.assertTrue(dashboard_service.list_dashboards()["samples"][0]["sample"])

        saved = dashboard_service.save_dashboard("Sample", loaded["data"], prev_path=str(sample))
        self.assertEqual(Path(saved["path"]).parent, self.user_dir)
        self.assertEqual(sample.read_bytes(), before)
        with self.assertRaises(HTTPException):
            dashboard_service.delete_dashboard(str(sample))

    def test_other_files_are_refused(self) -> None:
        stray = self.user_dir / "notes.arcdash"
        self.user_dir.mkdir()
        stray.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
        with self.assertRaises(HTTPException):
            dashboard_service.load_dashboard(str(stray))
        with self.assertRaises(HTTPException):
            dashboard_service.save_dashboard("X", {"format": "something-else"})
        self.assertEqual(dashboard_service.list_dashboards()["dashboards"], [])

    def test_library_lists_built_in_items_and_the_users_own(self) -> None:
        (self.samples_dir / "library.json").write_text(json.dumps({
            "assets": [{"id": "bar", "name": "Bar Chart", "category": "Charts", "widget": {"type": "bar"}}, {"name": "Broken"}],
        }), encoding="utf-8")
        saved = dashboard_service.save_library_asset("My KPI", {"type": "kpi", "title": "Paid"})["asset"]
        self.assertEqual((saved["id"], saved["builtin"], saved["category"]), ("user:My KPI", False, "My Library"))

        assets = dashboard_service.list_library()["assets"]
        self.assertEqual([(asset["id"], asset["builtin"]) for asset in assets], [("bar", True), ("user:My KPI", False)])

        with self.assertRaises(HTTPException):
            dashboard_service.delete_library_asset("bar")
        dashboard_service.delete_library_asset("user:My KPI")
        self.assertEqual(len(dashboard_service.list_library()["assets"]), 1)


class DashboardTableTests(unittest.TestCase):
    def test_datasets_become_one_table_with_vectors_on_their_own_rows(self) -> None:
        def load(project, reserving_class, dataset):
            if dataset == "Missing":
                raise HTTPException(404, "not found")
            return _loaded(dataset, triangle=dataset == "Paid")

        with patch.object(dashboard_data_service.dataset_service, "load_cached_dataset_values", side_effect=load):
            table = dashboard_data_service.read_dataset_table(
                "P1", ["Co\\NJ\\BI", "Co\\NY\\BI"], ["Paid", "Ultimate", "Missing"], ["Company", "State"],
            )

        self.assertEqual(
            [column["name"] for column in table["columns"]],
            ["Segment", "Segment Name", "Company", "State", "Level 3", "Origin", "Origin Year", "Development", "Paid", "Ultimate"],
        )
        paid = table["columns"][8]
        self.assertEqual((paid["default_aggregation"], paid["semi_additive"], paid["data_format"]), ("latest", True, "Triangle"))
        self.assertEqual(table["columns"][9]["default_aggregation"], "sum")
        self.assertEqual(table["columns"][7]["order"], ["8m", "20m"])
        self.assertEqual(table["columns"][6]["order"], ["2024", "2025"])
        self.assertEqual(
            [dashboard_data_service.origin_year(label) for label in ("2024", "2024 Q3", "202407", "Prior")],
            ["2024", "2024", "2024", "Prior"],
        )
        self.assertEqual(table["semi_additive"], {"partition": ["Segment", "Origin"], "order": "Development"})
        self.assertEqual(table["rows"][:3], [
            ["Co\\NJ\\BI", "BI", "Co", "NJ", "BI", "2024", "2024", None, None, 50.0],
            ["Co\\NJ\\BI", "BI", "Co", "NJ", "BI", "2024", "2024", "8m", 10.0, None],
            ["Co\\NJ\\BI", "BI", "Co", "NJ", "BI", "2024", "2024", "20m", 30.0, None],
        ])
        # The unobserved cell of the newest origin makes no row.
        self.assertEqual(table["row_count"], 2 * (3 + 2))
        self.assertEqual(len(table["missing"]), 2)
        json.dumps(table, allow_nan=False)

    def test_grouping_totals_measures_and_reads_date_parts(self) -> None:
        frame = pd.DataFrame({
            "State": ["NJ", "NJ", "NY", None],
            "acc_yrmo": [202401, 202407, 202501, 202501],
            "paid": [10.0, 5.0, None, 2.0],
        })
        table = dashboard_data_service.aggregate_frame(frame, ["State", "acc_yrmo:year"], ["paid"])
        self.assertEqual([column["name"] for column in table["columns"]], ["State", "acc_yrmo Year", "paid", "Rows"])
        self.assertEqual(table["rows"], [["NJ", "2024", 15.0, 2], ["NY", "2025", None, 1], [None, "2025", 2.0, 1]])
        self.assertEqual(table["source_rows"], 4)

        quarters = dashboard_data_service.aggregate_frame(frame, ["acc_yrmo:quarter"], ["paid"])
        self.assertEqual([row[0] for row in quarters["rows"]], ["2024 Q1", "2024 Q3", "2025 Q1"])

        with self.assertRaises(HTTPException) as too_many:
            dashboard_data_service.aggregate_frame(frame, ["State", "acc_yrmo"], ["paid"], row_limit=2)
        self.assertEqual(too_many.exception.status_code, 422)
        with self.assertRaises(HTTPException) as unknown:
            dashboard_data_service.aggregate_frame(frame, ["Nope"], [])
        self.assertEqual(unknown.exception.status_code, 400)

    def test_projects_stack_under_a_project_column_with_merged_orders(self) -> None:
        def table(developments, extra):
            columns = [
                dashboard_data_service.column_spec("Segment", "text"),
                dashboard_data_service.column_spec("Origin", "text", order=["2024"]),
                dashboard_data_service.column_spec("Development", "text", order=developments),
                dashboard_data_service.column_spec("Paid", "number", default_aggregation="latest"),
                dashboard_data_service.column_spec(extra, "number"),
            ]
            rows = [["BI", "2024", developments[0], 1.0, 9.0]]
            return dashboard_data_service.table_payload(
                columns, rows, semi_additive={"partition": ["Segment", "Origin"], "order": "Development"},
            )

        merged = dashboard_service.merge_project_tables([
            ("May", table(["5m", "17m"], "Only May")),
            ("Aug", table(["8m", "20m"], "Only Aug")),
        ])
        self.assertEqual(
            [column["name"] for column in merged["columns"]],
            ["Project", "Segment", "Origin", "Development", "Paid", "Only May", "Only Aug"],
        )
        self.assertEqual(merged["columns"][0]["order"], ["May", "Aug"])
        self.assertEqual(merged["columns"][3]["order"], ["5m", "8m", "17m", "20m"])
        self.assertEqual(merged["rows"], [
            ["May", "BI", "2024", "5m", 1.0, 9.0, None],
            ["Aug", "BI", "2024", "8m", 1.0, None, 9.0],
        ])
        self.assertEqual(merged["semi_additive"]["partition"], ["Project", "Segment", "Origin"])

    def test_a_csv_source_is_read_on_this_pc(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            csv_path = Path(folder) / "claims.csv"
            csv_path.write_text("Region,Paid\nEast,10\nEast,5\nWest,1\n", encoding="utf-8")
            with patch.object(workspace_read_client, "run_workspace_read", side_effect=AssertionError("not a hosted read")):
                fields = dashboard_service.source_fields({"kind": "csv", "path": str(csv_path)})
                raw = dashboard_service.load_source({"kind": "csv", "path": str(csv_path)})
                grouped = dashboard_service.load_source({"kind": "csv", "path": str(csv_path), "dimensions": ["Region"], "measures": ["Paid"]})
        self.assertEqual([(column["name"], column["type"]) for column in fields["columns"]], [("Region", "text"), ("Paid", "number")])
        self.assertEqual(raw["row_count"], 3)
        self.assertEqual(grouped["rows"], [["East", 15.0, 2], ["West", 1.0, 1]])
        self.assertTrue(grouped["refreshed_at"].endswith("Z"))
        with self.assertRaises(HTTPException) as missing:
            dashboard_service.load_source({"kind": "csv", "path": str(Path(TEST_TEMP_ROOT) / "absent.csv")})
        self.assertEqual(missing.exception.status_code, 404)

    def test_a_sql_source_types_its_columns_from_the_values(self) -> None:
        answer = {"ok": True, "columns": ["State", "Paid"], "rows": [["NJ", "12.5"], ["NY", None]], "truncated": True}
        with patch.object(dashboard_service.sql_server_service, "run_query", return_value=answer) as run_query:
            table = dashboard_service.load_source({"kind": "sql", "engine": "sqlserver", "connection": "Prod", "sql": "SELECT 1"})
        self.assertEqual(run_query.call_args.args[:2], ("SELECT 1", "Prod"))
        self.assertEqual([(column["name"], column["type"]) for column in table["columns"]], [("State", "text"), ("Paid", "number")])
        self.assertEqual(table["rows"], [["NJ", 12.5], ["NY", None]])
        self.assertTrue(table["truncated"])

        failed = {"ok": False, "error": "Login failed."}
        with patch.object(dashboard_service.sql_server_service, "run_query", return_value=failed):
            with self.assertRaises(HTTPException) as refused:
                dashboard_service.load_source({"kind": "sql", "sql": "SELECT 1"})
        self.assertEqual(refused.exception.detail, "Login failed.")


class DashboardTransportTests(unittest.TestCase):
    def test_project_sources_run_as_registered_reads_once_per_project(self) -> None:
        for kind, function in (("dashboard_dataset_table", "read_dataset_table"), ("dashboard_source_table", "read_source_table")):
            spec = WORKSPACE_READ_KINDS[kind]
            self.assertEqual((spec.module, spec.function), ("dashboard_data_service", function))
            self.assertTrue(callable(getattr(dashboard_data_service, function)))

        sent = []

        def gateway_read(read_kind, kwargs, *, local, finalize=None):
            # The request must pass the contract a Gateway validates it against.
            request = build_workspace_read_request(request_id="r1", read_kind=read_kind, kwargs=kwargs, user_name="alice")
            sent.append((read_kind, request["Kwargs"]))
            return dashboard_data_service.table_payload(
                [dashboard_data_service.column_spec("Segment", "text"), dashboard_data_service.column_spec("Paid", "number")],
                [["BI", 1.0]],
            )

        source = {
            "kind": "arco_datasets",
            "projects": [{"name": "Fake_202605", "label": "May"}, {"name": "Fake_202608", "label": "Aug"}],
            "reserving_classes": ["Co\\NJ\\BI"],
            "datasets": ["Paid"],
        }
        with patch.object(workspace_read_client, "run_workspace_read", side_effect=gateway_read):
            table = dashboard_service.load_source(source)
            dashboard_service.load_source({"kind": "arco_source_table", "project": "Fake_202605", "dimensions": ["STATE_CD"], "measures": ["paid"]})
            dashboard_service.source_fields({"kind": "arco_source_table", "project": "Fake_202605"})

        self.assertEqual([item[0] for item in sent], ["dashboard_dataset_table"] * 2 + ["dashboard_source_table"] * 2)
        self.assertEqual([item[1]["project_name"] for item in sent[:2]], ["Fake_202605", "Fake_202608"])
        self.assertEqual(sent[2][1], {"project_name": "Fake_202605", "dimensions": ["STATE_CD"], "measures": ["paid"]})
        self.assertEqual(sent[3][1], {"project_name": "Fake_202605"})
        self.assertEqual(table["rows"], [["May", "BI", 1.0], ["Aug", "BI", 1.0]])

    def test_a_client_pc_never_reads_project_data_itself(self) -> None:
        with (
            patch.dict("os.environ", {"ARCRHO_RUNTIME_SERVER_ROOT": ""}),
            patch.object(config, "load_gateway_config", return_value=GATEWAY),
            patch.object(workspace_read_client, "cached_gateway_capabilities", return_value={"workspace_read_kinds": []}),
            patch.object(dashboard_data_service, "read_dataset_table", side_effect=AssertionError("ran locally")),
        ):
            with self.assertRaises(HTTPException) as refused:
                dashboard_service.load_source({
                    "kind": "arco_datasets", "project": "P1", "reserving_classes": ["A\\B"], "datasets": ["Paid"],
                })
        self.assertEqual(refused.exception.status_code, 503)

    def test_a_source_without_a_project_or_a_known_kind_is_refused(self) -> None:
        for source in ({"kind": "arco_datasets"}, {"kind": "excel"}, {"kind": "sql", "sql": " "}):
            with self.assertRaises(HTTPException) as refused:
                dashboard_service.load_source(source)
            self.assertEqual(refused.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
