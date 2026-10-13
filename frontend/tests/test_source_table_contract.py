"""Project-owned imported source table: contract parity, auto-copy, SQL import."""
from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
for import_root in (PYTHON_API_SRC, FRONTEND_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app_server import config
from app_server.services import mssql_odbc, source_table_service
from arcrho_api import source_table_contract

ENGINE_DATA_PROCESSING = (
    REPOSITORY_ROOT / "server-components" / "src" / "arcrho_engine" / "data_processing.py"
)


class SourceTableLayoutParityTests(unittest.TestCase):
    """The engine mirrors the layout constants; this fails when they drift."""

    def test_engine_mirrors_canonical_layout_constants(self) -> None:
        source = ENGINE_DATA_PROCESSING.read_text(encoding="utf-8")
        mirrored = {
            name: match
            for name, match in re.findall(
                r'^(SOURCE_IMPORT_DIR|MASTER_TABLE_FILE)\s*=\s*"([^"]+)"',
                source,
                flags=re.MULTILINE,
            )
        }
        self.assertEqual(
            mirrored,
            {
                "SOURCE_IMPORT_DIR": source_table_contract.SOURCE_IMPORT_DIR,
                "MASTER_TABLE_FILE": source_table_contract.MASTER_TABLE_FILE,
            },
        )

    def test_engine_resolves_master_table_without_the_source_name(self) -> None:
        source = ENGINE_DATA_PROCESSING.read_text(encoding="utf-8")
        body = source.split("def get_project_table_path(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("SOURCE_IMPORT_DIR / MASTER_TABLE_FILE", body)
        # The engine must not fall back to the external path shown in the UI.
        self.assertNotIn("table_path", body)

    def test_master_table_path_is_fixed_under_the_project_folder(self) -> None:
        project_dir = str(Path("C:/ArcRho Server/projects/Demo"))
        self.assertEqual(
            source_table_contract.master_table_path(project_dir),
            str(Path(project_dir) / "source" / "master_table.csv"),
        )
        self.assertEqual(
            source_table_contract.source_import_path(project_dir),
            str(Path(project_dir) / "source" / "source_import.json"),
        )


class SourceImportNormalizationTests(unittest.TestCase):
    def test_normalizes_to_a_stable_full_payload(self) -> None:
        payload = source_table_contract.normalize_source_import({}, "Demo")
        self.assertEqual(
            sorted(payload.keys()),
            ["json_format", "last_import", "mssql", "project_name", "refresh_scope", "source_type"],
        )
        self.assertEqual(list(payload)[0], "json_format")
        self.assertEqual(payload["json_format"], source_table_contract.SOURCE_IMPORT_JSON_FORMAT)
        self.assertTrue(payload["json_format"].endswith("-v4"))
        self.assertEqual(payload["source_type"], source_table_contract.SOURCE_TYPE_CSV)
        self.assertEqual(payload["mssql"]["authentication"], source_table_contract.MSSQL_AUTH_WINDOWS)
        self.assertEqual(payload["refresh_scope"], source_table_contract.empty_refresh_scope())

    def test_the_last_refresh_scope_is_shared_and_normalized(self) -> None:
        payload = source_table_contract.normalize_source_import(
            {
                "refresh_scope": {
                    "dataset_types": ["Gross Loss--Paid", " gross loss--paid ", "", "ALAE--Paid"],
                    "reserving_class_types": [
                        {"Name": "HPPREF", "Level": "1"},
                        {"Name": "hppref", "Level": 1},
                        {"Name": "HOL", "Level": 5},
                        {"Name": "", "Level": 2},
                        {"Name": "NJ", "Level": 0},
                        "PA",
                    ],
                    "chosen_by": "jhou",
                    "chosen_at": "2026-09-05T13:00:00Z",
                }
            },
            "Demo",
        )
        self.assertEqual(
            payload["refresh_scope"],
            {
                "dataset_types": ["Gross Loss--Paid", "ALAE--Paid"],
                "reserving_class_types": [
                    {"Name": "HPPREF", "Level": 1},
                    {"Name": "HOL", "Level": 5},
                ],
                "chosen_by": "jhou",
                "chosen_at": "2026-09-05T13:00:00Z",
            },
        )

    def test_unknown_values_fall_back_to_the_supported_defaults(self) -> None:
        payload = source_table_contract.normalize_source_import(
            {"source_type": "oracle", "mssql": {"authentication": "kerberos"}},
            "Demo",
        )
        self.assertEqual(payload["source_type"], source_table_contract.SOURCE_TYPE_CSV)
        self.assertEqual(payload["mssql"]["authentication"], source_table_contract.MSSQL_AUTH_WINDOWS)

    def test_credentials_are_never_part_of_the_payload(self) -> None:
        payload = source_table_contract.normalize_source_import(
            {"mssql": {"server": "S", "user": "me", "password": "secret"}},
            "Demo",
        )
        self.assertEqual(
            sorted(payload["mssql"].keys()),
            ["authentication", "database", "server", "table"],
        )
        self.assertNotIn("password", json.dumps(payload))


_STRAY_COMBINED = {
    "tables": [
        {"id": "t1", "nickname": "Loss", "source_type": "mssql",
         "mssql": {"server": "S", "database": "D", "table": "dbo.Loss"}},
        {"id": "t2", "source_type": "csv", "csv_path": "C:\\x\\EP.csv"},
    ],
    "keys": [{"name": "CO_CD", "map": {"t1": {"column": "CO_CD"}, "t2": {"column": "Co_Cd"}}}],
}

_LAST_IMPORT_CSV = {
    "source_type": "csv",
    "source_label": "\\\\share\\raw.csv",
    "imported_at": "2026-10-01T12:00:00Z",
    "imported_by": "tester",
    "row_count": 10,
    "column_count": 3,
    "csv_path": "\\\\share\\raw.csv",
    "csv_mtime_ns": 123,
    "csv_size": 456,
}

_REFRESH_SCOPE = {
    "dataset_types": ["Gross Loss--Paid"],
    "reserving_class_types": [{"Name": "HOL", "Level": 5}],
    "chosen_by": "tester",
    "chosen_at": "2026-10-01T12:00:00Z",
}


class SingleTableGoldenPayloadTests(unittest.TestCase):
    """Single-table records normalize to exactly the historical payload."""

    def test_csv_record_is_unchanged_even_with_a_stray_combined_block(self) -> None:
        payload = source_table_contract.normalize_source_import(
            {
                "project_name": "Demo",
                "source_type": "csv",
                "mssql": {"server": "", "database": "", "table": "", "authentication": "windows"},
                "last_import": dict(_LAST_IMPORT_CSV),
                "refresh_scope": dict(_REFRESH_SCOPE),
                "combined": _STRAY_COMBINED,
            }
        )
        self.assertEqual(
            payload,
            {
                "json_format": "arcrho-source-import-v4",
                "project_name": "Demo",
                "source_type": "csv",
                "mssql": {"server": "", "database": "", "table": "", "authentication": "windows"},
                "last_import": _LAST_IMPORT_CSV,
                "refresh_scope": _REFRESH_SCOPE,
            },
        )
        self.assertEqual(
            list(payload),
            ["json_format", "project_name", "source_type", "mssql", "last_import", "refresh_scope"],
        )

    def test_mssql_record_is_unchanged_even_with_a_stray_combined_block(self) -> None:
        last_import = {
            "source_type": "mssql",
            "source_label": "SQLPRD01.DW.dbo.Claims",
            "imported_at": "2026-10-01T12:00:00Z",
            "imported_by": "tester",
            "row_count": 7,
            "column_count": 2,
            "csv_path": "",
            "csv_mtime_ns": None,
            "csv_size": None,
        }
        payload = source_table_contract.normalize_source_import(
            {
                "source_type": "mssql",
                "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Claims"},
                "last_import": dict(last_import),
                "combined": _STRAY_COMBINED,
            },
            "Demo",
        )
        self.assertEqual(
            payload,
            {
                "json_format": "arcrho-source-import-v4",
                "project_name": "Demo",
                "source_type": "mssql",
                "mssql": {
                    "server": "SQLPRD01",
                    "database": "DW",
                    "table": "dbo.Claims",
                    "authentication": "windows",
                },
                "last_import": last_import,
                "refresh_scope": source_table_contract.empty_refresh_scope(),
            },
        )

    def test_empty_and_unknown_records_still_fall_back_to_csv_without_combined(self) -> None:
        for raw in ({}, {"source_type": "oracle", "combined": _STRAY_COMBINED}):
            with self.subTest(raw=raw):
                payload = source_table_contract.normalize_source_import(raw, "Demo")
                self.assertEqual(payload["source_type"], "csv")
                self.assertNotIn("combined", payload)

    def test_csv_identity_match_stays_csv_only(self) -> None:
        identity = {"csv_path": "\\\\share\\raw.csv", "csv_mtime_ns": 123, "csv_size": 456}
        self.assertTrue(source_table_contract.same_csv_identity(_LAST_IMPORT_CSV, identity))
        for other in ("mssql", "combined"):
            with self.subTest(source_type=other):
                self.assertFalse(
                    source_table_contract.same_csv_identity(
                        dict(_LAST_IMPORT_CSV, source_type=other), identity
                    )
                )


class CombinedSourceContractTests(unittest.TestCase):
    canonical = {
        "tables": [
            {"id": "t1", "nickname": "Loss", "source_type": "mssql",
             "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Loss",
                       "authentication": "windows"}},
            {"id": "t2", "nickname": "", "source_type": "mssql",
             "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Closed",
                       "authentication": "windows"}},
            {"id": "t4", "nickname": "EP", "source_type": "csv",
             "csv_path": "\\\\share\\monthly\\EP.csv"},
        ],
        "keys": [
            {"name": "CO_CD", "map": {"t1": {"column": "CO_CD"}, "t4": {"column": "Co_Cd"}}},
            {"name": "sys_yrmo", "map": {"t1": {"column": "sys_yrmo"}, "t2": {"any": True},
                                          "t4": {"fill": "0"}}},
            {"name": "acc_yrmo", "map": {"t1": {"column": "acc_yrmo"},
                                          "t4": {"column": "acc_yrmo", "convert": "yyyymm"}}},
        ],
        "exclude": {"t4": ["FACID"]},
        "rename": {"t2": {"Earned Premium": "Budget Premium"}},
    }

    def test_a_combined_record_round_trips(self) -> None:
        payload = source_table_contract.normalize_source_import(
            {"source_type": "combined", "combined": self.canonical}, "Demo"
        )
        self.assertEqual(payload["source_type"], "combined")
        self.assertEqual(payload["combined"], self.canonical)
        self.assertEqual(list(payload)[-1], "combined")
        again = source_table_contract.normalize_source_import(json.loads(json.dumps(payload)))
        self.assertEqual(again, payload)

    def test_last_import_accepts_combined(self) -> None:
        record = source_table_contract.normalize_last_import({"source_type": "Combined"})
        self.assertEqual(record["source_type"], "combined")
        self.assertEqual(source_table_contract.normalize_source_type("combined"), "combined")

    def test_missing_block_normalizes_to_an_empty_one(self) -> None:
        payload = source_table_contract.normalize_source_import({"source_type": "combined"})
        self.assertEqual(
            payload["combined"],
            {"tables": [], "keys": [], "exclude": {}, "rename": {}},
        )

    def test_normalization_drops_bad_entries_and_keeps_order(self) -> None:
        combined = source_table_contract.normalize_combined_source(
            {
                "tables": [
                    {"id": "t1", "nickname": "  A nickname that is far too long  ",
                     "source_type": "mssql", "mssql": {"server": "S", "database": "D",
                                                       "table": "dbo.X", "password": "p"}},
                    {"id": "t1", "source_type": "csv", "csv_path": "dup.csv"},
                    {"id": "", "source_type": "csv", "csv_path": "noid.csv"},
                    {"id": "t3", "source_type": "oracle", "csv_path": "  Z:\\x\\Y.csv  "},
                    "junk",
                ],
                "keys": [
                    {"name": "K", "map": {"t9": {"column": "K"}, "t3": {"column": "k", "convert": "bad"},
                                          "t1": {"column": "K"}}},
                    {"name": "k", "map": {"t1": {"column": "dup"}}},
                    {"name": "", "map": {"t1": {"column": "X"}}},
                    {"name": "F", "map": {"t1": {}, "t3": {"fill": ""}}},
                ],
                "rows": {"t1": "match", "t3": "sideways", "t9": "base"},
                "exclude": {"t3": ["A", " A ", "", "B"], "t9": ["X"], "t1": []},
                "rename": {"t3": {"A": "B", "C": "", "D": "D"}, "t9": {"X": "Y"}},
            }
        )
        self.assertEqual(
            combined,
            {
                "tables": [
                    {"id": "t1", "nickname": "A nickname that is far t", "source_type": "mssql",
                     "mssql": {"server": "S", "database": "D", "table": "dbo.X",
                               "authentication": "windows"}},
                    {"id": "t3", "nickname": "", "source_type": "csv", "csv_path": "Z:\\x\\Y.csv"},
                ],
                "keys": [
                    {"name": "K", "map": {"t1": {"column": "K"}, "t3": {"column": "k"}}},
                    {"name": "F", "map": {"t3": {"fill": ""}}},
                ],
                "exclude": {"t3": ["A", "B"]},
                "rename": {"t3": {"A": "B"}},
            },
        )
        self.assertLessEqual(
            len(combined["tables"][0]["nickname"]), source_table_contract.COMBINED_NICKNAME_MAX
        )

    def test_label_uses_nicknames_then_table_names_in_order(self) -> None:
        self.assertEqual(
            source_table_contract.combined_source_label(self.canonical),
            "Combined: Loss, dbo.Closed, EP",
        )
        self.assertEqual(
            source_table_contract.combined_source_label(
                {"tables": [{"id": "a", "source_type": "csv", "csv_path": "\\\\s\\d\\Reported.csv"}]}
            ),
            "Combined: Reported",
        )


class MssqlConnectionHistoryTests(unittest.TestCase):
    """The server-shared list of previously used server/database pairs."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT))
        self.path = Path(self.temp_dir.name) / "config" / "mssql_connections.json"
        self.path_patch = mock.patch.object(
            config, "get_mssql_connections_path", return_value=str(self.path)
        )
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_stores_pairs_under_the_shared_config_folder(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "ActuarialDW")
        self.assertTrue(self.path.exists())
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], source_table_contract.MSSQL_CONNECTIONS_VERSION)
        self.assertEqual(
            [(item["server"], item["database"]) for item in saved["connections"]],
            [("SQLPRD01", "ActuarialDW")],
        )
        self.assertIn("last_used_at", saved["connections"][0])

    def test_never_stores_credentials(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "ActuarialDW")
        entry = json.loads(self.path.read_text(encoding="utf-8"))["connections"][0]
        self.assertEqual(sorted(entry.keys()), ["database", "last_used_at", "server"])

    def test_reusing_a_pair_does_not_duplicate_it(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "ActuarialDW")
        source_table_service.remember_mssql_connection("sqlprd01", "actuarialdw")
        loaded = source_table_service.load_mssql_connections()
        self.assertEqual(len(loaded["connections"]), 1)
        # The newest casing wins so the list reflects what was just used.
        self.assertEqual(loaded["connections"][0]["server"], "sqlprd01")

    def test_most_recently_used_pair_is_listed_first(self) -> None:
        with mock.patch.object(source_table_service, "_utc_now_text", return_value="2026-07-01T00:00:00Z"):
            source_table_service.remember_mssql_connection("SQLA", "DbA")
        with mock.patch.object(source_table_service, "_utc_now_text", return_value="2026-07-30T00:00:00Z"):
            source_table_service.remember_mssql_connection("SQLB", "DbB")
        listed = source_table_service.load_mssql_connections()["connections"]
        self.assertEqual([item["server"] for item in listed], ["SQLB", "SQLA"])

    def test_forgetting_one_database_keeps_the_others(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "DbA")
        source_table_service.remember_mssql_connection("SQLPRD01", "DbB")
        remaining = source_table_service.forget_mssql_connection("SQLPRD01", "DbA")
        self.assertEqual(
            [item["database"] for item in remaining["connections"]], ["DbB"]
        )

    def test_forgetting_a_server_drops_all_of_its_pairs(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "DbA")
        source_table_service.remember_mssql_connection("SQLPRD01", "DbB")
        source_table_service.remember_mssql_connection("SQLPRD02", "DbC")
        remaining = source_table_service.forget_mssql_connection("SQLPRD01")
        self.assertEqual(
            [(item["server"], item["database"]) for item in remaining["connections"]],
            [("SQLPRD02", "DbC")],
        )

    def test_incomplete_pairs_are_never_stored(self) -> None:
        source_table_service.remember_mssql_connection("SQLPRD01", "")
        source_table_service.remember_mssql_connection("", "ActuarialDW")
        self.assertEqual(source_table_service.load_mssql_connections()["connections"], [])

    def test_missing_or_corrupt_file_reads_as_empty(self) -> None:
        self.assertEqual(source_table_service.load_mssql_connections()["connections"], [])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(source_table_service.load_mssql_connections()["connections"], [])

    def test_forgetting_requires_a_server(self) -> None:
        with self.assertRaises(Exception):
            source_table_service.forget_mssql_connection("")


class SourceTableServiceTests(unittest.TestCase):
    project_name = "Demo Project"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT))
        self.root = Path(self.temp_dir.name)
        self.projects_dir = self.root / "projects"
        self.project_dir = self.projects_dir / self.project_name
        self.project_dir.mkdir(parents=True)
        self.external_csv = self.root / "external" / "raw_202605.csv"
        self.external_csv.parent.mkdir(parents=True)
        self.external_csv.write_text("A,B\n1,2\n3,4\n", encoding="utf-8")
        self._write_mapping(str(self.external_csv))
        self.master_path = self.project_dir / "source" / "master_table.csv"

        self.project_root_patch = mock.patch.object(
            config, "PROJECT_SETTINGS_DIR", str(self.projects_dir)
        )
        self.project_root_patch.start()
        self.audit_patch = mock.patch.object(
            source_table_service, "safe_append_project_audit_log"
        )
        self.audit_patch.start()
        self.login_patch = mock.patch.object(
            source_table_service, "get_windows_login_name", return_value="tester"
        )
        self.login_patch.start()

    def tearDown(self) -> None:
        self.login_patch.stop()
        self.audit_patch.stop()
        self.project_root_patch.stop()
        self.temp_dir.cleanup()

    def _write_mapping(self, table_path: str) -> None:
        (self.project_dir / "field_mapping.json").write_text(
            json.dumps({"project_name": self.project_name, "table_path": table_path, "rows": []}),
            encoding="utf-8",
        )

    # --- CSV auto-copy ---------------------------------------------------

    def test_first_access_copies_the_external_csv_into_the_project(self) -> None:
        self.assertFalse(self.master_path.exists())
        status = source_table_service.ensure_master_table(self.project_name)

        self.assertTrue(status["refreshed"])
        self.assertEqual(status["master_table_path"], str(self.master_path))
        self.assertTrue(self.master_path.exists())
        self.assertEqual(self.master_path.read_text(encoding="utf-8"), "A,B\n1,2\n3,4\n")

        record = source_table_service.read_source_import(self.project_name)
        self.assertEqual(record["last_import"]["source_type"], "csv")
        self.assertEqual(record["last_import"]["source_label"], str(self.external_csv))
        self.assertEqual(record["last_import"]["row_count"], 2)
        self.assertEqual(record["last_import"]["column_count"], 2)
        self.assertEqual(record["last_import"]["imported_by"], "tester")

    def test_unchanged_external_csv_is_not_copied_again(self) -> None:
        source_table_service.ensure_master_table(self.project_name)
        second = source_table_service.ensure_master_table(self.project_name)
        self.assertFalse(second["refreshed"])

    def test_changed_external_csv_is_re_copied(self) -> None:
        source_table_service.ensure_master_table(self.project_name)
        self.external_csv.write_text("A,B\n9,9\n", encoding="utf-8")
        status = source_table_service.ensure_master_table(self.project_name)
        self.assertTrue(status["refreshed"])
        self.assertEqual(self.master_path.read_text(encoding="utf-8"), "A,B\n9,9\n")

    def test_unreachable_external_csv_preserves_the_last_good_import(self) -> None:
        source_table_service.ensure_master_table(self.project_name)
        self._write_mapping(str(self.root / "missing" / "gone.csv"))

        status = source_table_service.ensure_master_table(self.project_name)

        self.assertFalse(status["refreshed"])
        self.assertTrue(status["master_table_exists"])
        self.assertEqual(self.master_path.read_text(encoding="utf-8"), "A,B\n1,2\n3,4\n")

    def test_no_configured_source_reports_not_configured(self) -> None:
        self._write_mapping("")
        with self.assertRaises(source_table_service.SourceTableNotConfiguredError):
            source_table_service.ensure_master_table(self.project_name)
        self.assertEqual(
            source_table_service.resolve_source_table_for_read(self.project_name), ""
        )

    # --- SQL Server ------------------------------------------------------

    def _configure_sql_profile(self) -> None:
        source_table_service.save_source_profile(
            self.project_name,
            "mssql",
            {"server": "SQLPRD01", "database": "DW", "table": "dbo.Claims"},
        )

    def test_saving_an_incomplete_sql_profile_is_rejected(self) -> None:
        with self.assertRaises(Exception) as ctx:
            source_table_service.save_source_profile(
                self.project_name, "mssql", {"server": "SQLPRD01"}
            )
        self.assertIn("missing", str(ctx.exception).lower())

    def test_sql_login_authentication_is_rejected_until_implemented(self) -> None:
        with self.assertRaises(Exception) as ctx:
            source_table_service.save_source_profile(
                self.project_name,
                "mssql",
                {
                    "server": "SQLPRD01",
                    "database": "DW",
                    "table": "dbo.Claims",
                    "authentication": "sql_login",
                },
            )
        self.assertIn("not supported yet", str(ctx.exception))

    def test_sql_project_never_auto_reimports(self) -> None:
        self._configure_sql_profile()
        with self.assertRaises(source_table_service.SourceTableMissingError):
            source_table_service.ensure_master_table(self.project_name)
        # The external CSV must not be copied in for a SQL Server project.
        self.assertFalse(self.master_path.exists())

    def test_import_streams_the_table_into_the_master_copy(self) -> None:
        self._configure_sql_profile()
        fake_driver = _FakeOdbcDriver(
            columns=["A", "B"],
            rows=[(1, "x"), (2, None), (3, "z,quoted")],
        )
        with mock.patch.object(mssql_odbc, "pyodbc", fake_driver), \
                mock.patch.object(
                    mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
                ):
            status = source_table_service.import_from_mssql(self.project_name)

        self.assertTrue(status["refreshed"])
        self.assertEqual(status["source_type"], "mssql")
        with open(self.master_path, "r", encoding="utf-8", newline="") as handle:
            written = list(csv.reader(handle))
        self.assertEqual(written[0], ["A", "B"])
        self.assertEqual(written[1], ["1", "x"])
        self.assertEqual(written[2], ["2", ""])
        self.assertEqual(written[3], ["3", "z,quoted"])

        record = source_table_service.read_source_import(self.project_name)
        self.assertEqual(record["last_import"]["row_count"], 3)
        self.assertEqual(record["last_import"]["source_label"], "SQLPRD01.DW.dbo.Claims")
        self.assertIn("Trusted_Connection=yes", fake_driver.connection_string)
        self.assertNotIn("PWD", fake_driver.connection_string)

    def test_lists_tables_and_views_with_schema_qualified_names(self) -> None:
        driver = _FakeOdbcDriver(
            columns=[],
            rows=[],
            listing_rows=[
                ("dbo", "ClaimsDetail", "BASE TABLE"),
                ("dbo", "vClaimsSummary", "VIEW"),
                ("staging", "Raw", "BASE TABLE"),
            ],
        )
        with mock.patch.object(mssql_odbc, "pyodbc", driver), \
                mock.patch.object(
                    mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
                ):
            result = source_table_service.list_mssql_tables("SQLPRD01", "DW")

        self.assertTrue(result["ok"])
        self.assertEqual(result["table_count"], 3)
        self.assertEqual(
            [item["qualified_name"] for item in result["tables"]],
            ["dbo.ClaimsDetail", "dbo.vClaimsSummary", "staging.Raw"],
        )
        self.assertEqual(
            [item["kind"] for item in result["tables"]],
            ["table", "view", "table"],
        )
        self.assertIn("INFORMATION_SCHEMA.TABLES", driver.last_statement)

    def test_listing_requires_a_server_and_database(self) -> None:
        with self.assertRaises(Exception) as ctx:
            source_table_service.list_mssql_tables("", "DW")
        self.assertIn("missing", str(ctx.exception).lower())

    def test_listing_does_not_need_a_table_to_be_chosen_yet(self) -> None:
        # The picker is what chooses the table, so listing must not require one.
        driver = _FakeOdbcDriver(columns=[], rows=[], listing_rows=[])
        with mock.patch.object(mssql_odbc, "pyodbc", driver), \
                mock.patch.object(
                    mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
                ):
            result = source_table_service.list_mssql_tables("SQLPRD01", "DW")
        self.assertTrue(result["ok"])
        self.assertEqual(result["tables"], [])

    def test_failed_import_leaves_the_previous_master_copy_intact(self) -> None:
        source_table_service.ensure_master_table(self.project_name)
        original = self.master_path.read_text(encoding="utf-8")
        self._configure_sql_profile()

        failing_driver = _FakeOdbcDriver(columns=["A"], rows=[], execute_error=RuntimeError("boom"))
        with mock.patch.object(mssql_odbc, "pyodbc", failing_driver), \
                mock.patch.object(
                    mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
                ):
            with self.assertRaises(Exception):
                source_table_service.import_from_mssql(self.project_name)

        self.assertEqual(self.master_path.read_text(encoding="utf-8"), original)
        self.assertFalse((self.project_dir / "source" / "master_table.csv.import.tmp").exists())

    def test_table_names_that_could_break_out_of_quoting_are_rejected(self) -> None:
        for bad in ("dbo.Claims]; DROP TABLE x --", "a.b.c.d", ""):
            with self.subTest(table=bad):
                with self.assertRaises(Exception):
                    source_table_service._quote_object_name(bad)

    def test_schema_qualified_names_are_bracket_quoted(self) -> None:
        self.assertEqual(
            source_table_service._quote_object_name("dbo.Claims"), "[dbo].[Claims]"
        )
        self.assertEqual(
            source_table_service._quote_object_name("DW.dbo.Claims"), "[DW].[dbo].[Claims]"
        )


class _FakeCursor:
    def __init__(self, columns, rows, execute_error=None, listing_rows=None, driver=None):
        self._columns = columns
        self._rows = list(rows)
        self._execute_error = execute_error
        self._listing_rows = list(listing_rows or [])
        self._driver = driver
        self.description = None
        self.closed = False

    def execute(self, statement):
        if self._driver is not None:
            self._driver.last_statement = statement
        if self._execute_error is not None:
            raise self._execute_error
        self.description = [(name,) for name in self._columns]
        return self

    def fetchall(self):
        return list(self._listing_rows)

    def fetchmany(self, size):
        batch = self._rows[:size]
        self._rows = self._rows[size:]
        return batch

    def close(self):
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeOdbcDriver:
    """Minimal stand-in for pyodbc so the import path runs without a database."""

    def __init__(self, columns, rows, execute_error=None, listing_rows=None):
        self._columns = columns
        self._rows = rows
        self._execute_error = execute_error
        self._listing_rows = listing_rows
        self.connection_string = ""
        self.last_statement = ""

    def drivers(self):
        return ["ODBC Driver 18 for SQL Server"]

    def connect(self, connection_string, autocommit=False):
        self.connection_string = connection_string
        return _FakeConnection(
            _FakeCursor(
                self._columns,
                self._rows,
                self._execute_error,
                listing_rows=self._listing_rows,
                driver=self,
            )
        )


if __name__ == "__main__":
    unittest.main()
