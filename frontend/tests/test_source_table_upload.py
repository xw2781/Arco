"""A source only this PC can read is uploaded to the server, which writes the master table.

The client reads a SQL Server table or a client-only CSV and sends it to the
Gateway in numbered chunks; the server keeps each chunk as its part of the
upload and, on commit, checks the chunk count, byte total and row count before
swapping the master table in. Every write here lands in a temporary root.
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
from app_server.schemas.source_table import (  # noqa: E402
    SourceTableImportRequest,
    SourceTableRefreshRequest,
)
from app_server.services import (  # noqa: E402
    mssql_odbc,
    source_table_upload_service as upload,
    user_identity_service,
    workspace_read_client,
)
from app_server.services.workspace_read_client import GatewayTransportFailure  # noqa: E402

source_table_router = importlib.import_module("app_server.api.source_table_router")

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
PROJECT = "Demo Project"
GATEWAY = {"enabled": True, "url": "http://server:28767", "user": "alice", "secret": "x"}
MUTATIONS = ("source_table_upload_chunk", "source_table_upload_commit", "mssql_connection_remember")
READS = ("source_table_settings", "source_table_upload_status", "source_refresh_status")
OLD_TABLE = "LOB,Paid\nOld,1\n"


class SourceTableUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "server"
        self.project = self.root / "projects" / PROJECT
        (self.project / "source").mkdir(parents=True)
        self.master = self.project / "source" / "master_table.csv"
        self.master.write_text(OLD_TABLE, encoding="utf-8")
        # A CSV outside the server root: only this PC can read it.
        self.csv = Path(self.temp.name) / "client" / "claims.csv"
        self.csv.parent.mkdir()
        self.table = "LOB,State,Paid\r\n" + "".join(f"Auto,NJ,{index}\r\n" for index in range(200))
        self.csv.write_bytes(self.table.encode("utf-8"))
        self._write_mapping(str(self.csv))
        env = {key: value for key, value in os.environ.items() if key != api_config.RUNTIME_SERVER_ROOT_ENV}
        env.update({api_config.SERVER_ROOT_ENV: str(self.root), "USERNAME": "alice"})
        self.requests: list[dict] = []
        self.fail_chunk: int | None = None
        for patcher in (
            patch.dict(os.environ, env, clear=True),
            patch.object(config, "PROJECT_SETTINGS_DIR", str(self.root / "projects")),
            patch.object(config, "load_gateway_config", return_value=dict(GATEWAY)),
            patch.object(
                workspace_read_client,
                "cached_gateway_capabilities",
                return_value={"workspace_read_kinds": list(READS), "workspace_mutation_kinds": list(MUTATIONS)},
            ),
            patch.object(workspace_read_client, "post_signed_json", side_effect=self._gateway),
            patch.object(workspace_read_client, "_log"),
            # Many small chunks, so resume and ordering are exercised.
            patch.object(upload, "RAW_CHUNK_BYTES", 256),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.audit = patch.object(upload, "safe_append_project_audit_log").start()
        self.addCleanup(patch.stopall)
        workspace_read_client.reset_capability_cache()
        self.addCleanup(workspace_read_client.reset_capability_cache)
        upload._PENDING.clear()
        self.addCleanup(upload._PENDING.clear)

    def _write_mapping(self, table_path: str) -> None:
        (self.project / "field_mapping.json").write_text(
            json.dumps({"project_name": PROJECT, "table_path": table_path, "rows": []}), encoding="utf-8"
        )

    def _server_process(self):
        return patch.dict(os.environ, {api_config.RUNTIME_SERVER_ROOT_ENV: str(self.root)})

    def _gateway(self, gateway_config, path, request_payload, *, timeout):
        """Run the request as the Gateway does: the registered service, as the signed user."""

        request = json.loads(json.dumps(request_payload))
        if request.get("MutationKind") == "source_table_upload_chunk" and request["Kwargs"]["index"] == self.fail_chunk:
            self.fail_chunk = None
            raise GatewayTransportFailure("gateway_unreachable")
        self.requests.append(request)
        registry = WORKSPACE_READ_KINDS if "ReadKind" in request else WORKSPACE_MUTATION_KINDS
        spec = registry[request.get("ReadKind") or request["MutationKind"]]
        function = getattr(importlib.import_module(f"app_server.services.{spec.module}"), spec.function)
        with self._server_process(), user_identity_service.acting_identity(request["UserName"]):
            answer = jsonable_encoder(function(**request["Kwargs"]))
        return answer, str(self.root), 0

    def _chunks_sent(self) -> list[int]:
        return [
            request["Kwargs"]["index"]
            for request in self.requests
            if request.get("MutationKind") == "source_table_upload_chunk"
        ]

    def _uploads(self) -> list[Path]:
        folder = self.root / "requests" / "source_table_upload"
        return [path for path in folder.rglob("*") if path.is_file()] if folder.exists() else []

    def _refresh(self):
        return source_table_router.refresh_source_table(SourceTableRefreshRequest(project_name=PROJECT))

    def test_every_kind_names_a_service_that_takes_its_arguments(self) -> None:
        for registry, kind in (
            (WORKSPACE_MUTATION_KINDS, "source_table_upload_chunk"),
            (WORKSPACE_MUTATION_KINDS, "source_table_upload_commit"),
            (WORKSPACE_READ_KINDS, "source_table_upload_status"),
        ):
            with self.subTest(kind):
                spec = registry[kind]
                signature = inspect.signature(getattr(upload, spec.function))
                signature.bind(**{name: "x" for name in spec.required})
                signature.bind(**{name: "x" for name in spec.allowed})
                self.assertFalse(getattr(spec, "receipt", False))
        self.assertLess(upload.MAX_ENCODED_CHUNK_CHARS, 256 * 1024)

    def test_a_client_only_csv_is_uploaded_and_swapped_in(self) -> None:
        answer = self._refresh()

        self.assertEqual(self.master.read_bytes(), self.table.encode("utf-8"))
        record = answer["last_import"]
        self.assertEqual((record["row_count"], record["column_count"]), (200, 3))
        self.assertEqual(record["source_label"], str(self.csv))
        self.assertEqual(record["csv_size"], len(self.table))
        self.assertEqual(record["imported_by"], "alice")
        chunks = self._chunks_sent()
        self.assertEqual(chunks, list(range(len(chunks))))
        self.assertGreater(len(chunks), 5)
        commit = [request for request in self.requests if request.get("MutationKind") == "source_table_upload_commit"]
        self.assertEqual(
            {key: commit[0]["Kwargs"][key] for key in ("chunk_count", "byte_count", "row_count")},
            {"chunk_count": len(chunks), "byte_count": len(self.table), "row_count": 200},
        )
        # Only the outcome is left of the upload; the parts are gone.
        self.assertEqual([path.name for path in self._uploads()], ["commit.json"])
        self.assertFalse((self.project / "source" / "master_table.csv.import.tmp").exists())
        self.audit.assert_called_once()

    def test_an_interrupted_upload_resumes_without_resending_what_arrived(self) -> None:
        self.fail_chunk = 4
        with self.assertRaises(HTTPException) as failed:
            self._refresh()
        self.assertEqual(failed.exception.status_code, 503)
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)
        self.assertEqual(self._chunks_sent(), [0, 1, 2, 3])

        self.requests.clear()
        self._refresh()
        self.assertEqual(self._chunks_sent()[0], 4)
        self.assertEqual(self.master.read_bytes(), self.table.encode("utf-8"))

    def test_a_changed_file_starts_a_new_upload(self) -> None:
        self.fail_chunk = 2
        with self.assertRaises(HTTPException):
            self._refresh()
        self.table = self.table.replace("Auto", "Home")
        self.csv.write_bytes(self.table.encode("utf-8"))
        os.utime(self.csv, ns=(1, 1))
        self.requests.clear()
        self._refresh()
        self.assertEqual(self._chunks_sent()[:2], [0, 1])
        self.assertEqual(self.master.read_bytes(), self.table.encode("utf-8"))

    def _server_upload(self, parts: list[bytes], upload_id: str = "srcup_test") -> None:
        with self._server_process(), user_identity_service.acting_identity("alice"):
            for index, part in enumerate(parts):
                upload.receive_source_table_chunk(PROJECT, upload_id, upload.encode_chunk(part), index)

    def _server_commit(self, upload_id: str = "srcup_test", **counts):
        with self._server_process(), user_identity_service.acting_identity("alice"):
            return upload.commit_source_table_upload(PROJECT, upload_id, "csv", **counts)

    def test_a_resent_chunk_lands_once_and_a_repeated_commit_answers_the_first_outcome(self) -> None:
        parts = [b"LOB,Paid\n", b"A,1\nB,2\n", b"C,3\n"]
        self._server_upload(parts)
        self._server_upload(parts[:2])  # resent
        first = self._server_commit(chunk_count=3, byte_count=21, row_count=3)
        self.assertEqual(self.master.read_bytes(), b"".join(parts))
        self.master.write_text(OLD_TABLE, encoding="utf-8")
        repeat = self._server_commit(chunk_count=3, byte_count=21, row_count=3)
        self.assertEqual(repeat, json.loads(json.dumps(jsonable_encoder(first))))
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)
        self.audit.assert_called_once()

    def test_a_short_or_different_commit_leaves_the_previous_table(self) -> None:
        self._server_upload([b"LOB,Paid\n", b"A,1\n"])
        cases = (
            {"chunk_count": 3, "byte_count": 13, "row_count": 1},
            {"chunk_count": 2, "byte_count": 14, "row_count": 1},
            {"chunk_count": 2, "byte_count": 13, "row_count": 2},
        )
        for counts in cases:
            with self.subTest(**counts), self.assertRaises(HTTPException) as refused:
                self._server_commit(**counts)
            self.assertEqual(refused.exception.status_code, 409)
            self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)
            self.assertFalse((self.project / "source" / "master_table.csv.import.tmp").exists())
        # The parts are kept, so a right commit still lands.
        self._server_commit(chunk_count=2, byte_count=13, row_count=1)
        self.assertEqual(self.master.read_text(encoding="utf-8"), "LOB,Paid\nA,1\n")

    def test_a_running_refresh_refuses_the_swap(self) -> None:
        self._server_upload([b"LOB,Paid\nA,1\n"])
        with patch.object(
            upload.source_refresh_service, "get_source_table_refresh_status", return_value={"busy": True}
        ), self.assertRaises(HTTPException) as refused:
            self._server_commit(chunk_count=1, byte_count=13, row_count=1)
        self.assertEqual(refused.exception.status_code, 423)
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)

    def test_incompressible_blocks_are_halved_to_fit(self) -> None:
        data = os.urandom(4096)
        with patch.object(upload, "MAX_ENCODED_CHUNK_CHARS", 1500):
            pieces = list(upload._chunks(iter([data])))
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(encoded) <= 1500 for _raw, encoded in pieces))
        self.assertEqual(b"".join(upload.decode_chunk(encoded) for _raw, encoded in pieces), data)

    def test_a_sql_server_table_is_read_here_and_uploaded(self) -> None:
        source_import = {
            "source_type": "mssql",
            "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Claims", "authentication": "windows"},
        }
        (self.project / "source" / "source_import.json").write_text(json.dumps(source_import), encoding="utf-8")
        driver = _FakeOdbcDriver(["A", "B"], [(index, "z,quoted" if index == 1 else None) for index in range(50)])
        with patch.object(mssql_odbc, "pyodbc", driver), patch.object(
            mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
        ):
            answer = source_table_router.import_source_table(SourceTableImportRequest(project_name=PROJECT))

        text = self.master.read_bytes().decode("utf-8")
        self.assertTrue(text.startswith('A,B\r\n0,\r\n1,"z,quoted"\r\n'))
        self.assertEqual(answer["last_import"]["row_count"], 50)
        self.assertEqual(answer["last_import"]["source_label"], "SQLPRD01.DW.dbo.Claims")
        self.assertIn("Trusted_Connection=yes", driver.connection_string)
        remembered = json.loads((self.root / "config" / "mssql_connections.json").read_text(encoding="utf-8"))
        self.assertEqual(len(remembered["connections"]), 1)

    def test_a_client_refuses_without_the_gateway(self) -> None:
        with patch.object(config, "load_gateway_config", return_value={"enabled": False}):
            with self.assertRaises(HTTPException) as refused:
                self._refresh()
        self.assertEqual(refused.exception.status_code, 401)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)
        self.assertEqual(self._uploads(), [])

    # --- Combined sources, and single-table commits kept exactly as they were ---

    def _source_import(self) -> dict:
        return json.loads((self.project / "source" / "source_import.json").read_text(encoding="utf-8"))

    def _commit_stamped(self, record: dict) -> dict:
        """The record with this run's import time blanked, for an exact comparison."""
        record = json.loads(json.dumps(record))
        record["last_import"]["imported_at"] = "<now>"
        return record

    def test_a_csv_commit_writes_exactly_the_single_table_record(self) -> None:
        self._server_upload([b"LOB,Paid\n", b"A,1\n"])
        with self._server_process(), user_identity_service.acting_identity("alice"):
            answer = upload.commit_source_table_upload(
                PROJECT, "srcup_test", "csv", 2, 13, 1, "\\\\srv\\share\\claims.csv", 123, 13
            )
        self.assertEqual(
            self._commit_stamped(self._source_import()),
            {
                "json_format": "arcrho-source-import-v4",
                "project_name": PROJECT,
                "source_type": "csv",
                "mssql": {"server": "", "database": "", "table": "", "authentication": "windows"},
                "last_import": {
                    "source_type": "csv",
                    "source_label": "\\\\srv\\share\\claims.csv",
                    "imported_at": "<now>",
                    "imported_by": "alice",
                    "row_count": 1,
                    "column_count": 2,
                    "csv_path": "\\\\srv\\share\\claims.csv",
                    "csv_mtime_ns": 123,
                    "csv_size": 13,
                },
                "refresh_scope": {"dataset_types": [], "reserving_class_types": [], "chosen_by": "", "chosen_at": ""},
            },
        )
        self.assertEqual(
            sorted(answer),
            sorted(
                [
                    "ok", "upload_id", "project_name", "master_table_path", "master_table_exists",
                    "master_table_size", "master_table_mtime", "refreshed", "source_type", "mssql",
                    "last_import", "refresh_scope",
                ]
            ),
        )
        self.audit.assert_called_once_with(
            project_name=PROJECT, action="Imported source table from CSV (\\\\srv\\share\\claims.csv, 1 rows)"
        )

    def test_a_sql_server_commit_writes_exactly_the_single_table_record(self) -> None:
        profile = {"server": "SQLPRD01", "database": "DW", "table": "dbo.Claims", "authentication": "windows"}
        (self.project / "source" / "source_import.json").write_text(
            json.dumps({"source_type": "mssql", "mssql": profile}), encoding="utf-8"
        )
        self._server_upload([b"LOB,Paid\nA,1\n"])
        with self._server_process(), user_identity_service.acting_identity("alice"):
            answer = upload.commit_source_table_upload(PROJECT, "srcup_test", "mssql", 1, 13, 1)
        record = self._commit_stamped(self._source_import())
        self.assertEqual(record["source_type"], "mssql")
        self.assertEqual(record["mssql"], profile)
        self.assertEqual(
            record["last_import"],
            {
                "source_type": "mssql",
                "source_label": "SQLPRD01.DW.dbo.Claims",
                "imported_at": "<now>",
                "imported_by": "alice",
                "row_count": 1,
                "column_count": 2,
                "csv_path": "",
                "csv_mtime_ns": None,
                "csv_size": None,
            },
        )
        self.assertNotIn("combined", record)
        self.assertNotIn("combined", answer)

    def test_a_combined_commit_records_its_label_and_no_file_identity(self) -> None:
        combined = {
            "tables": [
                {"id": "t1", "nickname": "Loss", "source_type": "mssql",
                 "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Loss"}},
                {"id": "t2", "nickname": "", "source_type": "csv", "csv_path": "\\\\srv\\share\\EP.csv"},
            ],
            "keys": [{"name": "LOB", "map": {"t1": {"column": "LOB"}, "t2": {"column": "Lob"}}}],
        }
        (self.project / "source" / "source_import.json").write_text(
            json.dumps({"source_type": "combined", "combined": combined}), encoding="utf-8"
        )
        self._server_upload([b"LOB,Paid,EP\n", b"A,1,2\n"])
        with self._server_process(), user_identity_service.acting_identity("alice"):
            answer = upload.commit_source_table_upload(PROJECT, "srcup_test", "combined", 2, 18, 1)
        record = self._source_import()
        self.assertEqual(record["source_type"], "combined")
        self.assertEqual([table["id"] for table in record["combined"]["tables"]], ["t1", "t2"])
        last = record["last_import"]
        self.assertEqual(last["source_type"], "combined")
        self.assertEqual(last["source_label"], "Combined: Loss, EP")
        self.assertEqual((last["row_count"], last["column_count"]), (1, 3))
        self.assertEqual((last["csv_path"], last["csv_mtime_ns"], last["csv_size"]), ("", None, None))
        self.assertEqual(answer["combined"], record["combined"])
        self.assertEqual(self.master.read_bytes(), b"LOB,Paid,EP\nA,1,2\n")
        # No SQL Server pair is remembered for a combined import.
        self.assertFalse((self.root / "config" / "mssql_connections.json").exists())
        self.audit.assert_called_once_with(
            project_name=PROJECT, action="Imported combined source (Combined: Loss, EP, 1 rows)"
        )

    def test_a_combined_commit_needs_the_combined_source_saved_first(self) -> None:
        self._server_upload([b"LOB,Paid\nA,1\n"])
        with self.assertRaises(HTTPException) as refused:
            with self._server_process(), user_identity_service.acting_identity("alice"):
                upload.commit_source_table_upload(PROJECT, "srcup_test", "combined", 1, 13, 1)
        self.assertEqual(refused.exception.status_code, 400)
        self.assertEqual(self.master.read_text(encoding="utf-8"), OLD_TABLE)

    def _commit_kwargs(self) -> dict:
        commits = [request for request in self.requests if request.get("MutationKind") == "source_table_upload_commit"]
        self.assertEqual(len(commits), 1)
        return commits[0]["Kwargs"]

    def test_csv_and_sql_server_uploads_commit_exactly_the_single_table_arguments(self) -> None:
        self._refresh()
        csv_kwargs = self._commit_kwargs()
        stat = os.stat(self.csv)
        self.assertTrue(csv_kwargs.pop("upload_id").startswith("srcup_"))
        self.assertEqual(
            csv_kwargs,
            {
                "project_name": PROJECT,
                "source_type": "csv",
                "chunk_count": len(self._chunks_sent()),
                "byte_count": len(self.table),
                "row_count": 200,
                "csv_path": str(self.csv),
                "csv_mtime_ns": stat.st_mtime_ns,
                "csv_size": stat.st_size,
            },
        )

        self.requests.clear()
        (self.project / "source" / "source_import.json").write_text(
            json.dumps({
                "source_type": "mssql",
                "mssql": {"server": "SQLPRD01", "database": "DW", "table": "dbo.Claims", "authentication": "windows"},
            }),
            encoding="utf-8",
        )
        driver = _FakeOdbcDriver(["A", "B"], [(index, "x") for index in range(30)])
        with patch.object(mssql_odbc, "pyodbc", driver), patch.object(
            mssql_odbc, "installed_odbc_driver", return_value="ODBC Driver 18 for SQL Server"
        ):
            source_table_router.import_source_table(SourceTableImportRequest(project_name=PROJECT))
        sql_kwargs = self._commit_kwargs()
        self.assertTrue(sql_kwargs.pop("upload_id").startswith("srcup_"))
        self.assertEqual(
            sql_kwargs,
            {
                "project_name": PROJECT,
                "source_type": "mssql",
                "chunk_count": len(self._chunks_sent()),
                "byte_count": len("A,B\r\n") + 30 * len("0,x\r\n") + 20 * 1,
                "row_count": 30,
            },
        )

    def test_progress_is_reported_while_the_upload_runs(self) -> None:
        seen = []
        real = upload._set_progress

        def record(key, **values):
            real(key, **values)
            seen.append(upload.get_upload_progress(PROJECT))

        with patch.object(upload, "_set_progress", side_effect=record):
            self._refresh()
        self.assertTrue(all(item["active"] for item in seen))
        self.assertEqual(seen[-2]["bytes_sent"], len(self.table))
        self.assertEqual(seen[-2]["total_bytes"], len(self.table))
        self.assertEqual(seen[-2]["rows_sent"], 200)
        self.assertEqual(seen[-1]["phase"], "committing")
        self.assertFalse(upload.get_upload_progress(PROJECT)["active"])


class _FakeCursor:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = list(rows)
        self.description = None

    def execute(self, statement):
        self.description = [(name,) for name in self._columns]
        return self

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeOdbcDriver:
    def __init__(self, columns, rows):
        self._columns = columns
        self._rows = rows
        self.connection_string = ""

    def drivers(self):
        return ["ODBC Driver 18 for SQL Server"]

    def connect(self, connection_string, autocommit=False):
        self.connection_string = connection_string
        return _FakeConnection(_FakeCursor(self._columns, self._rows))


if __name__ == "__main__":
    unittest.main()
