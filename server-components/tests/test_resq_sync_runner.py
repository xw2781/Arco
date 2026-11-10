"""Cover the Bridge-side runner for queued ArcRho/ResQ synchronizations.

The runner owns no synchronization rules -- those live in the canonical
``resq_migration.sync_session`` the Bridge freezes. What it does own is worth
pinning: which phase may write, that a writing phase holds the same reserving
class lease a ResQ import holds (and always gives it back), and that a request
whose reviewed rows are incomplete is refused before any of that begins.
"""
from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_bridge import resq_sync_runner  # noqa: E402

# Take the error class from the runner itself: a suite that already imported the
# Bridge under its ``src.`` package prefix holds a second, unequal copy of it.
ResQMigrationBundleError = resq_sync_runner.ResQMigrationBundleError


def _reviewed_row(row_id: str = "paid-loss") -> dict:
    return {
        "Id": row_id,
        "Name": row_id,
        "Signature": {"key": row_id, "action": "arcrho_to_resq"},
    }


def _request(**overrides):
    payload = {
        "Function": "SyncResQReservingClass",
        "ContractVersion": 2,
        "RequestId": "sync-request-123",
        "ProjectName": "Demo",
        "Path": r"Auto\PP",
        "UserName": "tester",
        "Phase": "preview",
    }
    payload.update(overrides)
    return payload


class _StubSession(types.SimpleNamespace):
    """Stands in for the frozen canonical session module."""

    def __init__(self, *, apply_result=None, apply_error=None):
        super().__init__()
        self.SYNC_SESSION_API_VERSION = resq_sync_runner.SUPPORTED_SYNC_SESSION_API_VERSION
        self.preview_calls = []
        self.transfer_preview_calls = []
        self.apply_calls = []
        self.export_calls = []
        self.export_selections = []
        self._apply_result = apply_result or {"status": "completed", "results": []}
        self._apply_error = apply_error

    def build_runtime(self, migration, exporter_module, *, resq_credentials=None):
        return {
            "migration": migration,
            "exporter_module": exporter_module,
            "resq_credentials": resq_credentials,
        }

    def preview_sync(self, runtime, project_name, rc_path, *, server_root, progress_callback=None):
        self.preview_calls.append((runtime, project_name, rc_path, server_root))
        if progress_callback is not None:
            progress_callback({"event": "scan", "completed": 0, "total": 0})
        return {"status": "review_required", "preview": [{"id": "paid-loss"}]}

    def preview_transfer(
        self,
        runtime,
        project_name,
        rc_path,
        *,
        direction,
        server_root,
        progress_callback=None,
    ):
        self.transfer_preview_calls.append((project_name, rc_path, direction, server_root))
        if progress_callback is not None:
            progress_callback({"event": "scan", "completed": 0, "total": 0})
        return {"status": "review_required", "direction": direction, "preview": [{"id": "paid loss"}]}

    def apply_sync(
        self,
        runtime,
        project_name,
        rc_path,
        *,
        server_root,
        reviewed_rows,
        progress_callback=None,
    ):
        self.apply_calls.append((project_name, rc_path, server_root, list(reviewed_rows)))
        if self._apply_error is not None:
            raise self._apply_error
        return dict(self._apply_result)

    def export_reserving_class(
        self,
        runtime,
        project_name,
        rc_path,
        *,
        server_root,
        selected_names=None,
        requested_by="",
        progress_callback=None,
    ):
        self.export_calls.append((runtime, project_name, rc_path, server_root))
        self.export_selections.append((selected_names, requested_by))
        if progress_callback is not None:
            progress_callback({"event": "write", "completed": 1, "total": 1, "status": "success"})
        return {"status": "completed", "results": [{"id": "paid-loss", "outcome": "exported"}]}


class ResQSyncRunnerPhaseTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"
        self.server_root.mkdir(parents=True, exist_ok=True)
        self.lease = object()
        self.session = _StubSession()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run(self, request, *, session=None, progress=None, credentials=None):
        session = session or self.session
        bundle = types.SimpleNamespace(migration_dir=self.server_root / "bundle" / "migration")
        self.acquire = Mock(return_value=self.lease)
        self.release = Mock()
        with (
            patch.object(resq_sync_runner, "get_project_root", return_value=self.server_root),
            patch.object(resq_sync_runner, "configure_canonical_runtime", return_value=bundle),
            patch.object(resq_sync_runner, "load_resq_data_migration", return_value=Mock()),
            patch.object(resq_sync_runner, "load_sync_session", return_value=session),
            patch.object(resq_sync_runner, "load_sync_exporter", return_value=Mock()),
            patch.object(resq_sync_runner, "_import_staging_parent", return_value=self.server_root / "r"),
            patch.object(resq_sync_runner, "_acquire_target_lock", self.acquire),
            patch.object(resq_sync_runner, "release_engine_job_lease", self.release),
            patch.object(
                resq_sync_runner,
                "start_engine_job_lease_heartbeat",
                return_value=(None, None),
            ),
            patch.object(resq_sync_runner, "stop_engine_job_lease_heartbeat"),
        ):
            return resq_sync_runner.run_reserving_class_sync(
                request,
                progress_callback=progress,
                resq_credentials=credentials,
            )

    def test_the_session_connects_with_the_account_the_bridge_hands_it(self):
        account = {"connection_name": "ResQ Prod", "user_name": "svc", "password": "secret"}

        self._run(_request(), credentials=account)

        runtime = self.session.preview_calls[0][0]
        self.assertEqual(runtime["resq_credentials"], account)

    def test_a_preview_reads_without_taking_the_reserving_class_lease(self):
        events = []

        result = self._run(_request(), progress=events.append)

        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["phase"], "preview")
        self.acquire.assert_not_called()
        self.release.assert_not_called()
        self.assertEqual(events, [{"event": "scan", "completed": 0, "total": 0}])
        _runtime, project_name, rc_path, server_root = self.session.preview_calls[0]
        self.assertEqual((project_name, rc_path), ("Demo", r"Auto\PP"))
        self.assertEqual(server_root, self.server_root.resolve())

    def test_an_apply_holds_the_reserving_class_lease_and_gives_it_back(self):
        result = self._run(_request(Phase="apply", SelectedRows=[_reviewed_row()]))

        self.assertEqual(result["phase"], "apply")
        self.acquire.assert_called_once()
        self.release.assert_called_once_with(self.lease)
        _project, _path, _root, reviewed = self.session.apply_calls[0]
        self.assertEqual(reviewed, [{"id": "paid-loss", "signature": {"key": "paid-loss", "action": "arcrho_to_resq"}, "name": "paid-loss"}])

    def test_the_lease_is_released_when_the_session_fails(self):
        session = _StubSession(apply_error=RuntimeError("ResQ went away"))

        with self.assertRaisesRegex(RuntimeError, "ResQ went away"):
            self._run(_request(Phase="apply", SelectedRows=[_reviewed_row()]), session=session)

        self.release.assert_called_once_with(self.lease)

    def test_an_apply_takes_the_same_lock_a_resq_import_takes(self):
        self._run(_request(Phase="apply", SelectedRows=[_reviewed_row()]))

        staging_parent, project_name, rc_path, request_id = self.acquire.call_args.args
        self.assertEqual(staging_parent, self.server_root / "r")
        self.assertEqual((project_name, rc_path), ("Demo", r"Auto\PP"))
        self.assertEqual(request_id, "sync-request-123")

    def test_an_export_holds_the_reserving_class_lease_and_runs_the_export_session(self):
        events = []
        account = {"connection_name": "ResQ Prod", "user_name": "svc", "password": "secret"}

        result = self._run(_request(Phase="export"), progress=events.append, credentials=account)

        self.assertEqual(result["phase"], "export")
        self.assertEqual(result["status"], "completed")
        self.acquire.assert_called_once()
        self.release.assert_called_once_with(self.lease)
        self.assertEqual(self.session.apply_calls, [])
        runtime, project_name, rc_path, server_root = self.session.export_calls[0]
        self.assertEqual((project_name, rc_path), ("Demo", r"Auto\PP"))
        self.assertEqual(server_root, self.server_root.resolve())
        self.assertEqual(runtime["resq_credentials"], account)
        self.assertEqual(events, [{"event": "write", "completed": 1, "total": 1, "status": "success"}])

    def test_a_transfer_preview_reads_the_named_direction_without_the_lease(self):
        events = []

        result = self._run(
            _request(Phase="transfer_preview", Direction="import"), progress=events.append
        )

        self.assertEqual(result["phase"], "transfer_preview")
        self.assertEqual(result["direction"], "import")
        self.acquire.assert_not_called()
        self.release.assert_not_called()
        self.assertEqual(self.session.preview_calls, [])
        project_name, rc_path, direction, server_root = self.session.transfer_preview_calls[0]
        self.assertEqual((project_name, rc_path, direction), ("Demo", r"Auto\PP", "import"))
        self.assertEqual(server_root, self.server_root.resolve())

    def test_a_transfer_preview_without_a_known_direction_is_refused(self):
        for direction in (None, "", "sideways"):
            with self.subTest(direction=direction):
                request = _request(Phase="transfer_preview")
                if direction is not None:
                    request["Direction"] = direction
                # A missing field is caught by the shared required-text check,
                # an unknown one by the direction rule; both refuse the request.
                with self.assertRaises(ValueError):
                    self._run(request)

    def test_an_export_carries_the_ticked_names_and_who_asked(self):
        self._run(_request(Phase="export", SelectedNames=[" Paid Loss ", "", "Paid LDF"]))

        self.assertEqual(self.session.export_selections, [(["Paid Loss", "Paid LDF"], "tester")])

    def test_an_export_without_a_selection_asks_for_the_whole_class(self):
        self._run(_request(Phase="export"))

        self.assertEqual(self.session.export_selections, [(None, "tester")])

    def test_a_selection_that_is_not_a_list_of_names_is_refused(self):
        for names in ("Paid Loss", [{"Id": "paid-loss"}], [1, 2]):
            with self.subTest(names=names):
                with self.assertRaises(resq_sync_runner.ResQSyncRequestError):
                    self._run(_request(Phase="export", SelectedNames=names))

    def test_a_reviewed_row_without_its_signature_is_refused_before_any_lease(self):
        for rows in ([{"Id": "paid-loss"}], [{"Signature": {"key": "x"}}], ["paid-loss"], []):
            with self.subTest(rows=rows):
                with self.assertRaises(resq_sync_runner.ResQSyncRequestError):
                    self._run(_request(Phase="apply", SelectedRows=rows))
                self.acquire.assert_not_called()

    def test_a_duplicate_reviewed_row_is_collapsed_once(self):
        self._run(_request(Phase="apply", SelectedRows=[_reviewed_row(), _reviewed_row()]))

        _project, _path, _root, reviewed = self.session.apply_calls[0]
        self.assertEqual([row["id"] for row in reviewed], ["paid-loss"])

    def test_an_unknown_phase_is_refused(self):
        with self.assertRaises(resq_sync_runner.ResQSyncRequestError):
            self._run(_request(Phase="rollback"))


class ResQSyncRunnerBundleTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.bundle_root = Path(self.temp_dir.name) / "resq_importer" / "python-api"
        (self.bundle_root / "migration").mkdir(parents=True)
        self.bundle = types.SimpleNamespace(migration_dir=self.bundle_root / "migration")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_the_exporter_is_read_from_beside_the_frozen_migration_folder(self):
        macros = self.bundle_root / "macros"
        macros.mkdir()
        exporter = macros / "export_reserving_class_to_resq.py"
        exporter.write_text("VALUE = 1\n", encoding="utf-8")

        self.assertEqual(resq_sync_runner.sync_exporter_path(self.bundle), exporter.resolve())

    def test_a_bridge_without_the_frozen_exporter_says_to_rebuild(self):
        with self.assertRaisesRegex(ResQMigrationBundleError, "Rebuild and redeploy the Bridge"):
            resq_sync_runner.sync_exporter_path(self.bundle)

    def test_a_session_from_outside_the_bundle_is_refused(self):
        stranger = types.SimpleNamespace(
            __name__="resq_migration.sync_session",
            __file__=str(Path(self.temp_dir.name) / "elsewhere" / "sync_session.py"),
            SYNC_SESSION_API_VERSION=resq_sync_runner.SUPPORTED_SYNC_SESSION_API_VERSION,
        )

        with patch.dict(sys.modules, {"resq_migration.sync_session": stranger}):
            with self.assertRaisesRegex(ResQMigrationBundleError, "outside this Bridge's canonical bundle"):
                resq_sync_runner.load_sync_session(self.bundle)

    def test_a_session_the_bridge_was_not_built_against_is_refused(self):
        newer = types.SimpleNamespace(
            __name__="resq_migration.sync_session",
            __file__=str(self.bundle.migration_dir / "sync_session.py"),
            SYNC_SESSION_API_VERSION=resq_sync_runner.SUPPORTED_SYNC_SESSION_API_VERSION + 1,
        )

        with patch.dict(sys.modules, {"resq_migration.sync_session": newer}):
            with self.assertRaisesRegex(ResQMigrationBundleError, "Rebuild and redeploy the Bridge"):
                resq_sync_runner.load_sync_session(self.bundle)

    def test_a_session_that_declares_no_api_version_is_refused(self):
        undeclared = types.SimpleNamespace(
            __name__="resq_migration.sync_session",
            __file__=str(self.bundle.migration_dir / "sync_session.py"),
        )

        with patch.dict(sys.modules, {"resq_migration.sync_session": undeclared}):
            with self.assertRaisesRegex(ResQMigrationBundleError, "does not declare its API version"):
                resq_sync_runner.load_sync_session(self.bundle)


if __name__ == "__main__":
    unittest.main()
