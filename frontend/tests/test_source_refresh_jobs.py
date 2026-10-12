from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
SERVER_COMPONENTS_SRC = REPOSITORY_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
for path in (FRONTEND_ROOT, SERVER_COMPONENTS_SRC, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api.source_table_contract import (
    import_source_path_is_shared,
    normalize_import_source_path,
)
from arcrho_dependent_propagation_contract import ENGINE_UNAVAILABLE_MESSAGE
from arcrho_source_refresh_contract import (
    SOURCE_REFRESH_CONTRACT_VERSION,
    SOURCE_REFRESH_FUNCTION,
    SourceRefreshContractError,
    acquire_source_refresh_lease,
    build_source_refresh_request,
    build_source_refresh_status,
    find_source_refresh_hold,
    release_source_refresh_lease,
    reserving_class_matches_scope,
    source_refresh_request_path,
    source_refresh_status_path,
    validate_source_refresh_request,
    validate_source_refresh_status,
)
from app_server.services import source_refresh_service
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS


class SourceRefreshContractTests(unittest.TestCase):
    REQUEST_ID = "abcdef0123456789abcdef0123456789"

    def test_request_round_trips_and_rejects_filesystem_fields(self) -> None:
        request = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
        )
        self.assertEqual(request["Function"], SOURCE_REFRESH_FUNCTION)
        self.assertEqual(request["ContractVersion"], SOURCE_REFRESH_CONTRACT_VERSION)
        self.assertEqual(validate_source_refresh_request(request), request)

        with self.assertRaises(SourceRefreshContractError):
            validate_source_refresh_request({**request, "MasterTablePath": "E:\\x.csv"})

    def test_request_must_do_at_least_one_of_import_or_refresh(self) -> None:
        with self.assertRaises(SourceRefreshContractError):
            build_source_refresh_request(
                request_id=self.REQUEST_ID,
                project_name="Demo Project",
                user_name="Test User",
                import_source=False,
                refresh_dependents=False,
            )

    def test_flags_must_be_booleans_rather_than_truthy_text(self) -> None:
        request = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
        )
        with self.assertRaises(SourceRefreshContractError):
            validate_source_refresh_request({**request, "Force": "true"})

    def test_a_scope_travels_only_when_it_narrows_the_job(self) -> None:
        whole = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
            dataset_types=[],
            reserving_class_types=[],
        )
        # An unnarrowed request is the payload every deployed Engine accepts.
        self.assertNotIn("DatasetTypes", whole)
        self.assertNotIn("ReservingClassTypes", whole)

        narrowed = build_source_refresh_request(
            request_id=self.REQUEST_ID,
            project_name="Demo Project",
            user_name="Test User",
            dataset_types=["Gross Loss--Paid", " gross loss--paid ", "ALAE--Paid"],
            reserving_class_types=[
                {"Name": "HPPREF", "Level": 1},
                {"Name": "hppref", "Level": 1},
                {"Name": "HOL", "Level": 5},
            ],
        )
        self.assertEqual(narrowed["DatasetTypes"], ["Gross Loss--Paid", "ALAE--Paid"])
        self.assertEqual(
            narrowed["ReservingClassTypes"],
            [{"Name": "HPPREF", "Level": 1}, {"Name": "HOL", "Level": 5}],
        )
        self.assertEqual(validate_source_refresh_request(narrowed), narrowed)

        for bad in (
            {"DatasetTypes": "Gross Loss--Paid"},
            {"DatasetTypes": [""]},
            {"ReservingClassTypes": ["HOL"]},
            {"ReservingClassTypes": [{"Name": "HOL"}]},
            {"ReservingClassTypes": [{"Name": "HOL", "Level": 0}]},
            {"ReservingClassTypes": [{"Name": "HOL", "Level": True}]},
            {"ReservingClassTypes": [{"Name": "HOL", "Level": 5, "Path": "E:\\x"}]},
        ):
            with self.assertRaises(SourceRefreshContractError, msg=repr(bad)):
                validate_source_refresh_request({**whole, **bad})

    def test_a_class_is_in_scope_when_every_listed_level_names_its_segment(self) -> None:
        scope = [
            {"Name": "HPPREF", "Level": 1},
            {"Name": "PRNJ - HO+DF", "Level": 1},
            {"Name": "HOL", "Level": 5},
        ]
        self.assertTrue(reserving_class_matches_scope("HPPREF\\HO+DF\\NJ\\Legacy\\HOL", scope))
        self.assertTrue(reserving_class_matches_scope("PRNJ - HO+DF\\HO+DF\\NJ\\Legacy\\hol", scope))
        # Level 1 matches but level 5 does not, and the other way round.
        self.assertFalse(reserving_class_matches_scope("HPPREF\\HO+DF\\NJ\\Legacy\\HOPxCAT", scope))
        self.assertFalse(reserving_class_matches_scope("PIC2\\PA\\NY\\Core Direct\\HOL", scope))
        # A path shorter than a listed level has no segment there to match.
        self.assertFalse(reserving_class_matches_scope("HPPREF\\HO+DF", scope))
        # Levels the scope does not mention accept every value; no scope accepts every class.
        self.assertTrue(reserving_class_matches_scope("HPPREF\\PA\\NY\\Any\\HOL", scope))
        self.assertTrue(reserving_class_matches_scope("PIC2\\PA\\NY\\Core Direct\\COL", []))
        self.assertTrue(reserving_class_matches_scope("PIC2\\PA\\NY\\Core Direct\\COL", None))

    def test_status_result_is_normalized_and_bounded(self) -> None:
        status = build_source_refresh_status(
            self.REQUEST_ID,
            "success",
            progress={"stage": "complete", "completed": 4, "total": 4, "label": "Done"},
            result={
                "source_type": "csv",
                "imported": True,
                "dependents_refreshed": True,
                "row_count": 12,
                "classes_total": 2,
                "classes_refreshed": 2,
                "datasets_regenerated": 5,
                "dataset_types_expanded": ["Earned Premium", "  ", "Total Earned Premium"],
                "failures": ["  ", "Class A: boom"],
            },
        )
        validated = validate_source_refresh_status(status, expected_request_id=self.REQUEST_ID)
        self.assertEqual(validated["result"]["failures"], ["Class A: boom"])
        # The types the job rebuilt: the selection plus the formulas over it.
        self.assertEqual(
            validated["result"]["dataset_types_expanded"],
            ["Earned Premium", "Total Earned Premium"],
        )
        # Absent counts default to zero rather than to a missing key, so every
        # consumer reads the same shape.
        self.assertEqual(validated["result"]["methods_updated"], 0)
        self.assertEqual(validated["result"]["column_count"], 0)

    def test_status_rejects_a_rebuilt_type_list_that_is_not_a_list(self) -> None:
        with self.assertRaises(SourceRefreshContractError):
            build_source_refresh_status(
                self.REQUEST_ID,
                "success",
                progress={"stage": "complete", "completed": 1, "total": 1, "label": "Done"},
                result={"dataset_types_expanded": "Earned Premium"},
            )

    def test_status_rejects_an_unknown_result_field(self) -> None:
        with self.assertRaises(SourceRefreshContractError):
            build_source_refresh_status(
                self.REQUEST_ID,
                "success",
                progress={"stage": "complete", "completed": 1, "total": 1, "label": "Done"},
                result={"master_table_path": "E:\\projects\\x\\source\\master_table.csv"},
            )

    def test_registered_hosted_kinds_point_at_this_service(self) -> None:
        read = WORKSPACE_READ_KINDS["source_refresh_status"]
        self.assertEqual(read.module, "source_refresh_service")
        self.assertTrue(
            hasattr(source_refresh_service, read.function),
            f"{read.function} is registered but missing from the service.",
        )
        mutation = WORKSPACE_MUTATION_KINDS["source_table_refresh_submit"]
        self.assertEqual(mutation.module, "source_refresh_service")
        self.assertTrue(hasattr(source_refresh_service, mutation.function))


class SourceRefreshPlanTests(unittest.TestCase):
    """Only a CSV on a share is imported by the server; every other source on the client."""

    def _plan(self, source_type: str, csv_path: str) -> dict:
        return source_refresh_service.describe_source_refresh_plan(
            "Demo Project", {"source_type": source_type}, {"busy": False}, csv_path=csv_path, csv_path_rewritten=False
        )

    def test_a_shared_csv_is_the_only_server_import(self) -> None:
        shared = r"\\fileserver\data\claims.csv"
        self.assertEqual(
            self._plan("csv", shared),
            {
                "ok": True,
                "project_name": "Demo Project",
                "source_type": "csv",
                "server_can_import": True,
                "csv_path_rewritten": False,
                "busy": False,
                "busy_reason": "",
            },
        )
        self.assertFalse(self._plan("csv", r"C:\Users\me\claims.csv")["server_can_import"])
        self.assertFalse(self._plan("mssql", shared)["server_can_import"])

    def test_a_combined_source_imports_on_the_client(self) -> None:
        plan = self._plan("combined", r"\\fileserver\data\claims.csv")
        self.assertEqual(plan["source_type"], "combined")
        self.assertFalse(plan["server_can_import"])


class ImportSourcePathTests(unittest.TestCase):
    def test_unc_paths_are_shared_and_left_alone(self) -> None:
        unc = r"\\fileserver\data\claims.csv"
        self.assertTrue(import_source_path_is_shared(unc))
        self.assertEqual(normalize_import_source_path(unc), unc)

    def test_a_drive_letter_is_not_shared(self) -> None:
        self.assertFalse(import_source_path_is_shared(r"Z:\data\claims.csv"))
        self.assertFalse(import_source_path_is_shared(r"C:\Users\me\claims.csv"))

    def test_an_unmapped_drive_letter_is_returned_unchanged(self) -> None:
        # No machine in a test run is guaranteed to have a mapping, so the
        # contract must never invent one.
        with patch(
            "arcrho_api.source_table_contract._mapped_drive_target", return_value=""
        ):
            self.assertEqual(
                normalize_import_source_path(r"Z:\data\claims.csv"),
                r"Z:\data\claims.csv",
            )

    def test_a_mapped_drive_letter_becomes_its_share_path(self) -> None:
        with patch(
            "arcrho_api.source_table_contract._mapped_drive_target",
            return_value=r"\\fileserver\data",
        ):
            self.assertEqual(
                normalize_import_source_path(r"Z:\claims\2026.csv"),
                r"\\fileserver\data\claims\2026.csv",
            )


class SourceRefreshSubmissionTests(unittest.TestCase):
    REQUEST_ID = "0123456789abcdef0123456789abcdef"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT))
        self.root = Path(self.temp_dir.name)
        (self.root / "projects").mkdir()
        self.instances_dir = self.root / "runtime" / "instances" / "arcrho_engine"
        self.path_patch = patch.object(
            source_refresh_service.config,
            "load_workspace_paths",
            return_value={
                "workspace_root": str(self.root),
                "paths": {"projects_dir": "projects", "requests_dir": "requests"},
            },
        )
        self.path_patch.start()
        self.identity_patch = patch.object(
            source_refresh_service.user_identity_service,
            "get_windows_login_name",
            return_value="Test User",
        )
        self.identity_patch.start()

    def tearDown(self) -> None:
        self.identity_patch.stop()
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def _write_heartbeat(self) -> Path:
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        heartbeat = self.instances_dir / "engine.json"
        heartbeat.write_text(
            json.dumps({"Server": "engine.json", "Last seen": "2026-08-18 12:00:00"}),
            encoding="utf-8",
        )
        return heartbeat

    def _submit(self, **overrides):
        payload = {
            "project_name": "Demo Project",
            "request_id": self.REQUEST_ID,
        }
        payload.update(overrides)
        return source_refresh_service.submit_source_table_refresh_job(**payload)

    def test_submit_refuses_before_writing_anything_without_a_live_engine(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._submit()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(str(raised.exception.detail), ENGINE_UNAVAILABLE_MESSAGE)
        self.assertFalse((self.root / "requests").exists())

    def test_submit_publishes_the_queued_status_before_the_request(self) -> None:
        self._write_heartbeat()
        canonical_writer = source_refresh_service.write_json_atomic

        def observe_request_write(path, payload):
            if Path(path) == source_refresh_request_path(self.root, self.REQUEST_ID):
                # A request the Engine can claim before its status exists would
                # have no way to report progress at all.
                self.assertTrue(
                    source_refresh_status_path(self.root, self.REQUEST_ID).is_file()
                )
            return canonical_writer(path, payload)

        with patch.object(
            source_refresh_service, "write_json_atomic", side_effect=observe_request_write
        ):
            response = self._submit()

        self.assertEqual(response["job_id"], self.REQUEST_ID)
        self.assertEqual(response["status"], "queued")
        self.assertFalse(response["resumed"])
        published = json.loads(
            source_refresh_request_path(self.root, self.REQUEST_ID).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_source_refresh_request(published), published)
        self.assertEqual(published["UserName"], "Test User")

    def test_resubmitting_one_id_resumes_instead_of_queueing_twice(self) -> None:
        self._write_heartbeat()
        first = self._submit()
        second = self._submit()
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["resumed"])
        queued = list(
            source_refresh_request_path(self.root, self.REQUEST_ID).parent.glob("*.json")
        )
        self.assertEqual(len(queued), 1)

    def test_a_second_job_for_a_held_project_is_refused(self) -> None:
        self._write_heartbeat()
        lease = acquire_source_refresh_lease(self.root, "Demo Project")
        self.addCleanup(release_source_refresh_lease, lease)
        with self.assertRaises(HTTPException) as raised:
            self._submit(request_id="ffffffffffffffffffffffffffffffff")
        self.assertEqual(raised.exception.status_code, 423)

    def test_a_held_project_is_reported_busy_and_a_free_one_is_not(self) -> None:
        self.assertIsNone(find_source_refresh_hold(self.root, "Demo Project"))
        lease = acquire_source_refresh_lease(self.root, "Demo Project")
        try:
            hold = find_source_refresh_hold(self.root, "Demo Project")
            self.assertEqual(hold, {"reason": "processing"})
            # The hold is per project, so another project stays writable.
            self.assertIsNone(find_source_refresh_hold(self.root, "Other Project"))
        finally:
            release_source_refresh_lease(lease)

    def test_status_reports_the_project_hold_with_no_job_named(self) -> None:
        response = source_refresh_service.get_source_table_refresh_status("Demo Project")
        self.assertEqual(response["found"], False)
        self.assertEqual(response["busy"], False)

        self._write_heartbeat()
        self._submit()
        response = source_refresh_service.get_source_table_refresh_status(
            "Demo Project", self.REQUEST_ID
        )
        self.assertTrue(response["found"])
        self.assertEqual(response["status"], "queued")
        self.assertEqual(response["job_id"], self.REQUEST_ID)
        # A queued request with no terminal status holds the project.
        self.assertTrue(response["busy"])

    def test_status_for_an_unknown_job_is_a_404(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            source_refresh_service.get_source_table_refresh_status(
                "Demo Project", "ffffffffffffffffffffffffffffffff"
            )
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
