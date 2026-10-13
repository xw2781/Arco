"""Source Data writes run on the server host.

The field mapping save, the import profile save, the reserving class types
save, the shared SQL Server connection list, the table-summary rebuild and the
refresh plan's CSV path rewrite go to the Gateway from a Client PC and refuse
when it cannot answer; a server process runs the same service locally. A CSV
path is translated from this PC's drive letters on the client and reaches the
server as data. Every write here lands in a temporary root.
"""

from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
for path in (FRONTEND_ROOT, REPOSITORY_ROOT / "python-api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api import config as api_config  # noqa: E402
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS  # noqa: E402
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS  # noqa: E402
from app_server import config  # noqa: E402
from app_server.schemas.field_mapping import FieldMappingSaveRequest  # noqa: E402
from app_server.schemas.reserving_class import ReservingClassTypesSaveRequest  # noqa: E402
from app_server.schemas.source_table import (  # noqa: E402
    MssqlConnectionForgetRequest,
    SourceProfileSaveRequest,
)
from app_server.schemas.table_summary import TableSummaryRefreshRequest  # noqa: E402
from app_server.services import (  # noqa: E402
    source_refresh_service,
    source_table_service,
    user_identity_service,
    workspace_mutation_client,
    workspace_read_client,
)

field_mapping_router = importlib.import_module("app_server.api.field_mapping_router")
reserving_class_router = importlib.import_module("app_server.api.reserving_class_router")
source_table_router = importlib.import_module("app_server.api.source_table_router")
table_summary_router = importlib.import_module("app_server.api.table_summary_router")

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
PROJECT = "Demo Project"
GATEWAY = {"enabled": True, "url": "http://server:28767", "user": "alice", "secret": "x"}
MAPPED_CSV = "Z:\\data\\claims.csv"
SHARED_CSV = "\\\\server\\share\\data\\claims.csv"
KINDS = (
    "field_mapping_save",
    "source_profile_save",
    "source_combined_save",
    "source_scope_save",
    "source_csv_path_rewrite",
    "reserving_class_types_save",
    "table_summary_rebuild",
    "mssql_connection_remember",
    "mssql_connection_forget",
)
RECEIPT_KINDS = ("field_mapping_save", "source_profile_save", "source_combined_save", "reserving_class_types_save")
READ_KINDS = ("source_table_settings", "source_refresh_status")


def _translate(path):
    """This PC's drive mapping: Z: stands for the share."""
    text = str(path or "")
    return SHARED_CSV + text[len(MAPPED_CSV):] if text.startswith(MAPPED_CSV) else text


class SourceDataWritesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.project = self.projects / PROJECT
        (self.project / "source").mkdir(parents=True)
        (self.project / "source" / "master_table.csv").write_text(
            "LOB,State,Paid\nAuto,NJ,1\nHome,NY,2\n", encoding="utf-8"
        )
        self._write_mapping(MAPPED_CSV)
        env = {key: value for key, value in os.environ.items() if key != api_config.RUNTIME_SERVER_ROOT_ENV}
        env.update({api_config.SERVER_ROOT_ENV: str(self.root), "USERNAME": "alice"})
        self.requests: list[dict] = []
        for patcher in (
            patch.dict(os.environ, env, clear=True),
            patch.object(config, "PROJECT_SETTINGS_DIR", str(self.projects)),
            patch.object(config, "load_gateway_config", return_value=dict(GATEWAY)),
            patch.object(
                workspace_read_client,
                "cached_gateway_capabilities",
                return_value={
                    "workspace_read_kinds": list(READ_KINDS),
                    "workspace_mutation_kinds": list(KINDS),
                },
            ),
            patch.object(workspace_read_client, "post_signed_json", side_effect=self._gateway),
            patch.object(workspace_read_client, "_log"),
            patch.object(field_mapping_router, "normalize_import_source_path", side_effect=_translate),
            patch.object(source_table_router, "normalize_import_source_path", side_effect=_translate),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        workspace_read_client.reset_capability_cache()
        self.addCleanup(workspace_read_client.reset_capability_cache)

    def _write_mapping(self, table_path: str) -> None:
        (self.project / "field_mapping.json").write_text(
            json.dumps({"project_name": PROJECT, "table_path": table_path, "rows": []}),
            encoding="utf-8",
        )

    def _server_process(self):
        return patch.dict(os.environ, {api_config.RUNTIME_SERVER_ROOT_ENV: str(self.root)})

    def _gateway(self, gateway_config, path, request_payload, *, timeout):
        """Run the request as the Gateway does: the registered service, as the signed user."""

        request = json.loads(json.dumps(request_payload))
        self.requests.append(request)
        registry = WORKSPACE_READ_KINDS if "ReadKind" in request else WORKSPACE_MUTATION_KINDS
        spec = registry[request.get("ReadKind") or request["MutationKind"]]
        function = getattr(importlib.import_module(f"app_server.services.{spec.module}"), spec.function)
        with self._server_process(), user_identity_service.acting_identity(request["UserName"]):
            answer = jsonable_encoder(function(**request["Kwargs"]))
        return answer, str(self.root), 0

    def _kinds(self) -> list[str]:
        return [request.get("MutationKind") or request.get("ReadKind") for request in self.requests]

    def _files(self) -> dict[str, bytes]:
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def _stored_csv_path(self) -> str:
        return json.loads((self.project / "field_mapping.json").read_text(encoding="utf-8-sig"))["table_path"]

    def test_every_kind_names_a_service_that_takes_its_arguments(self) -> None:
        for kind in KINDS:
            with self.subTest(kind):
                spec = WORKSPACE_MUTATION_KINDS[kind]
                module = importlib.import_module(f"app_server.services.{spec.module}")
                signature = inspect.signature(getattr(module, spec.function))
                signature.bind(**{name: "x" for name in spec.required})
                signature.bind(**{name: "x" for name in spec.allowed})
                self.assertEqual(spec.receipt, kind in RECEIPT_KINDS)

    def test_each_write_runs_on_the_gateway(self) -> None:
        saved = field_mapping_router.save_field_mapping(
            FieldMappingSaveRequest(
                project_name=PROJECT,
                rows=[{"field_name": "LOB", "significance": "Reserving Class", "level": 1}],
            )
        )
        self.assertEqual(saved["count"], 1)
        values = json.loads((self.project / "reserving_class_values.json").read_text(encoding="utf-8"))
        self.assertEqual(values["fields"][0]["distinct_values"], ["Auto", "Home"])

        types = reserving_class_router.save_reserving_class_types(
            ReservingClassTypesSaveRequest(project_name=PROJECT, columns=[], rows=[])
        )
        self.assertTrue(types["ok"])

        profile = source_table_router.save_source_table_profile(
            SourceProfileSaveRequest(project_name=PROJECT, source_type="csv", csv_path=MAPPED_CSV + "x")
        )
        self.assertEqual(profile["csv_path"], SHARED_CSV + "x")
        self.assertIn("driver_available", profile)
        self.assertEqual(self._stored_csv_path(), SHARED_CSV + "x")

        summary = table_summary_router.refresh_table_summary(TableSummaryRefreshRequest(project_name=PROJECT))
        self.assertTrue(summary["reserving_refreshed"])
        self.assertEqual(summary["row_count"], 2)

        source_table_service.submit_mssql_connection_remember("SQLPRD01", "DW")
        remembered = json.loads((self.root / "config" / "mssql_connections.json").read_text(encoding="utf-8"))
        self.assertEqual(len(remembered["connections"]), 1)
        source_table_router.forget_source_table_connection(MssqlConnectionForgetRequest(server="SQLPRD01"))
        forgotten = json.loads((self.root / "config" / "mssql_connections.json").read_text(encoding="utf-8"))
        self.assertEqual(forgotten["connections"], [])

        self.assertEqual(
            self._kinds(),
            [
                "field_mapping_save",
                "reserving_class_types_save",
                "source_profile_save",
                "table_summary_rebuild",
                "mssql_connection_remember",
                "mssql_connection_forget",
            ],
        )
        self.assertEqual({request["UserName"] for request in self.requests}, {"alice"})
        # The server was sent the share path, never this PC's drive letter.
        self.assertEqual(self.requests[2]["Kwargs"]["csv_path"], SHARED_CSV + "x")

    def test_the_refresh_plan_sends_the_translated_path_as_data(self) -> None:
        plan = source_table_router.get_source_refresh_plan(PROJECT)
        self.assertEqual(
            self._kinds(), ["source_table_settings", "source_csv_path_rewrite", "source_refresh_status"]
        )
        self.assertEqual(
            self.requests[1]["Kwargs"],
            {"project_name": PROJECT, "from_path": MAPPED_CSV, "csv_path": SHARED_CSV},
        )
        self.assertTrue(plan["csv_path_rewritten"])
        self.assertTrue(plan["server_can_import"])
        self.assertFalse(plan["busy"])
        self.assertEqual(self._stored_csv_path(), SHARED_CSV)

        # Stored as the share now, so the next plan rewrites nothing.
        self.requests.clear()
        again = source_table_router.get_source_refresh_plan(PROJECT)
        self.assertEqual(self._kinds(), ["source_table_settings", "source_refresh_status"])
        self.assertFalse(again["csv_path_rewritten"])
        self.assertTrue(again["server_can_import"])

    def test_a_path_only_this_pc_can_read_stays_on_the_client(self) -> None:
        self._write_mapping("C:\\Users\\me\\claims.csv")
        plan = source_table_router.get_source_refresh_plan(PROJECT)
        self.assertFalse(plan["server_can_import"])
        self.assertNotIn("source_csv_path_rewrite", self._kinds())

    def test_the_rewrite_leaves_a_repeat_or_a_changed_path_alone(self) -> None:
        with self._server_process(), patch.object(source_table_service, "safe_append_project_audit_log") as audit:
            first = source_table_service.rewrite_source_csv_path(PROJECT, MAPPED_CSV, SHARED_CSV)
            repeat = source_table_service.rewrite_source_csv_path(PROJECT, MAPPED_CSV, SHARED_CSV)
            self._write_mapping("\\\\other\\claims.csv")
            changed = source_table_service.rewrite_source_csv_path(PROJECT, MAPPED_CSV, SHARED_CSV)
        self.assertTrue(first["rewritten"])
        self.assertFalse(repeat["rewritten"])
        self.assertFalse(changed["rewritten"])
        self.assertEqual(self._stored_csv_path(), "\\\\other\\claims.csv")
        self.assertEqual(audit.call_count, 1)

    # --- Combined sources, and single-table records kept exactly as they were ---

    COMBINED = {
        "tables": [
            {"id": "t1", "nickname": "Loss", "source_type": "mssql",
             "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Loss", "authentication": "windows"}},
            {"id": "t2", "nickname": "EP", "source_type": "csv", "csv_path": SHARED_CSV},
        ],
        "keys": [{"name": "LOB", "map": {"t1": {"column": "LOB"}, "t2": {"column": "Lob"}}}],
        "exclude": {"t2": ["FACID"]},
        "rename": {},
    }
    SINGLE_SETTINGS_KEYS = sorted(
        [
            "project_name", "master_table_path", "master_table_exists", "master_table_size",
            "master_table_mtime", "refreshed", "source_type", "mssql", "last_import", "refresh_scope",
            "csv_path", "supported_authentication",
        ]
    )

    def _save_combined(self, combined) -> dict:
        kwargs = {"project_name": PROJECT, "combined": combined}
        return workspace_mutation_client.run_workspace_mutation(
            "source_combined_save", kwargs, local=lambda: source_table_service.save_combined_source(**kwargs)
        )

    def _source_import_text(self) -> str:
        return (self.project / "source" / "source_import.json").read_text(encoding="utf-8")

    def _save_csv_profile(self) -> dict:
        return source_table_router.save_source_table_profile(
            SourceProfileSaveRequest(project_name=PROJECT, source_type="csv", csv_path=MAPPED_CSV)
        )

    def test_a_combined_source_is_saved_on_the_gateway_and_read_back(self) -> None:
        settings = self._save_combined(self.COMBINED)
        self.assertEqual(self._kinds(), ["source_combined_save"])
        self.assertEqual(self.requests[0]["Kwargs"]["combined"], self.COMBINED)
        self.assertEqual(settings["source_type"], "combined")
        self.assertEqual(settings["combined"], self.COMBINED)
        stored = json.loads(self._source_import_text())
        self.assertEqual(stored["source_type"], "combined")
        self.assertEqual(stored["combined"], self.COMBINED)
        with self._server_process():
            again = source_table_service.read_source_table_settings(PROJECT)
        self.assertEqual(again["combined"], self.COMBINED)
        self.assertEqual(sorted(again), sorted(self.SINGLE_SETTINGS_KEYS + ["combined"]))

    def test_a_combined_save_refuses_an_incomplete_source(self) -> None:
        one_table = {**self.COMBINED, "tables": self.COMBINED["tables"][:1]}
        no_key = {**self.COMBINED, "keys": []}
        sql_login = json.loads(json.dumps(self.COMBINED))
        sql_login["tables"][0]["mssql"]["authentication"] = "sql_login"
        no_table_name = json.loads(json.dumps(self.COMBINED))
        no_table_name["tables"][0]["mssql"]["table"] = ""
        with self._server_process():
            for combined in (one_table, no_key, sql_login, no_table_name):
                with self.subTest(combined=combined), self.assertRaises(HTTPException) as refused:
                    source_table_service.save_combined_source(PROJECT, combined)
                self.assertEqual(refused.exception.status_code, 400)
        self.assertFalse((self.project / "source" / "source_import.json").exists())

    def test_a_single_table_save_after_a_combined_one_writes_exactly_the_single_record(self) -> None:
        self._save_csv_profile()
        single = self._source_import_text()
        self.assertEqual(
            json.loads(single),
            {
                "json_format": "arcrho-source-import-v4",
                "project_name": PROJECT,
                "source_type": "csv",
                "mssql": {"server": "", "database": "", "table": "", "authentication": "windows"},
                "last_import": {
                    "source_type": "", "source_label": "", "imported_at": "", "imported_by": "",
                    "row_count": None, "column_count": None, "csv_path": "", "csv_mtime_ns": None, "csv_size": None,
                },
                "refresh_scope": {"dataset_types": [], "reserving_class_types": [], "chosen_by": "", "chosen_at": ""},
            },
        )

        self._save_combined(self.COMBINED)
        answer = self._save_csv_profile()
        # Byte for byte the record a project that was never combined holds.
        self.assertEqual(self._source_import_text(), single)
        self.assertNotIn("combined", answer)
        self.assertEqual(sorted(set(answer) - {"ok", "driver_available"}), self.SINGLE_SETTINGS_KEYS)

    def test_a_combined_project_is_never_re_read_behind_the_users_back(self) -> None:
        self._save_combined(self.COMBINED)
        master = self.project / "source" / "master_table.csv"
        before = master.read_bytes()
        with self._server_process():
            status = source_table_service.ensure_master_table(PROJECT, force=True)
            file_status = source_table_service.get_source_file_status(PROJECT)
        self.assertFalse(status["refreshed"])
        self.assertEqual(master.read_bytes(), before)
        # The CSV still named in the field mapping is not this source's file.
        self.assertEqual(file_status["csv_path"], "")

        master.unlink()
        with self._server_process():
            with self.assertRaises(source_table_service.SourceTableMissingError) as missing:
                source_table_service.ensure_master_table(PROJECT)
            self.assertEqual(source_table_service.resolve_source_table_for_read(PROJECT), "")
        self.assertIn("Project Settings > Source Data", str(missing.exception))
        self.assertFalse(master.exists())

    def test_the_refresh_plan_says_a_combined_source_imports_on_the_client(self) -> None:
        self._save_combined(self.COMBINED)
        self._write_mapping(SHARED_CSV)
        plan = source_table_router.get_source_refresh_plan(PROJECT)
        self.assertEqual(plan["source_type"], "combined")
        self.assertFalse(plan["server_can_import"])
        # The same shared CSV makes a single-table project server-importable.
        direct = source_refresh_service.describe_source_refresh_plan(
            PROJECT, {"source_type": "csv"}, {}, csv_path=SHARED_CSV, csv_path_rewritten=False
        )
        self.assertTrue(direct["server_can_import"])

    def test_a_client_refuses_without_the_gateway(self) -> None:
        before = self._files()
        routes = (
            lambda: field_mapping_router.save_field_mapping(FieldMappingSaveRequest(project_name=PROJECT)),
            lambda: reserving_class_router.save_reserving_class_types(
                ReservingClassTypesSaveRequest(project_name=PROJECT)
            ),
            lambda: source_table_router.save_source_table_profile(
                SourceProfileSaveRequest(project_name=PROJECT, source_type="csv", csv_path=MAPPED_CSV)
            ),
            lambda: source_table_router.forget_source_table_connection(
                MssqlConnectionForgetRequest(server="SQLPRD01")
            ),
            lambda: source_table_router.get_source_refresh_plan(PROJECT),
            lambda: table_summary_router.refresh_table_summary(TableSummaryRefreshRequest(project_name=PROJECT)),
            lambda: source_table_service.submit_mssql_connection_remember("SQLPRD01", "DW"),
        )
        with patch.object(config, "load_gateway_config", return_value={"enabled": False}):
            for route in routes:
                with self.assertRaises(HTTPException) as refused:
                    route()
                self.assertEqual(refused.exception.status_code, 401)
            # A poll the Gateway cannot answer is "unknown", never a failed job.
            status = source_table_router.get_source_refresh_job_status(PROJECT, "psrefresh_1")
        self.assertTrue(status["unknown"])
        self.assertEqual(self.requests, [])
        self.assertEqual(self._files(), before)


if __name__ == "__main__":
    unittest.main()
