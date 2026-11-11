"""A user-requested cancel stops a running duplicate without leaving a target."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = REPOSITORY_ROOT / "test"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_project_duplication_contract import (  # noqa: E402
    PROJECT_DUPLICATION_STATUS_VALUES,
    PROJECT_DUPLICATION_TERMINAL_STATUS_VALUES,
    build_project_duplication_request,
    build_project_duplication_status_for_request_id,
    clear_project_duplication_cancel_request,
    project_duplication_cancel_path,
    project_duplication_cancel_requested,
    project_duplication_request_path,
    project_duplication_status_path,
    validate_project_duplication_status,
    write_json_atomic,
    write_project_duplication_cancel_request,
)
from arcrho_engine import project_duplication  # noqa: E402


class ProjectDuplicationCancelTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"
        self.projects_dir = self.server_root / "projects"
        self.projects_dir.mkdir(parents=True)
        source = self.projects_dir / "Source"
        (source / "general_settings.json").parent.mkdir(parents=True)
        (source / "general_settings.json").write_text("{}\n", encoding="utf-8")
        data = source / "data"
        for name in ("RC A", "RC B", "RC C"):
            (data / name / "datasets").mkdir(parents=True)
            (data / name / "datasets" / "paid.csv").write_text("1,2\n", encoding="utf-8")
        (data / "index.json").write_text('{"version":1}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _request(self, request_id: str = "job-cancel") -> dict:
        return build_project_duplication_request(
            request_id=request_id,
            source_project_name="Source",
            target_project_name="Target",
            projects_directory="projects",
            user_name="tester",
        )

    def _read_status(self, request_id: str) -> dict:
        return validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(self.server_root, request_id).read_text(
                    encoding="utf-8"
                )
            ),
            expected_request_id=request_id,
        )

    def test_cancel_marker_lives_beside_the_other_protocol_folders(self) -> None:
        self.assertEqual(
            project_duplication_cancel_path(self.server_root, "job-1"),
            self.server_root / "requests" / "project_duplication" / "cancel" / "job-1.json",
        )
        self.assertIn("cancelled", PROJECT_DUPLICATION_STATUS_VALUES)
        self.assertEqual(
            PROJECT_DUPLICATION_TERMINAL_STATUS_VALUES, {"success", "error", "cancelled"}
        )
        status = build_project_duplication_status_for_request_id(
            "job-1",
            "cancelled",
            progress={"stage": "cancelled", "completed": 1, "total": 3, "label": "x"},
        )
        self.assertEqual(validate_project_duplication_status(status)["status"], "cancelled")

        self.assertFalse(project_duplication_cancel_requested(self.server_root, "job-1"))
        written = write_project_duplication_cancel_request(
            self.server_root, "job-1", user_name="Wei"
        )
        payload = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(payload["request_id"], "job-1")
        self.assertEqual(payload["user_name"], "Wei")
        self.assertNotIn(str(self.server_root), json.dumps(payload))
        self.assertTrue(project_duplication_cancel_requested(self.server_root, "job-1"))
        self.assertTrue(clear_project_duplication_cancel_request(self.server_root, "job-1"))
        self.assertFalse(project_duplication_cancel_requested(self.server_root, "job-1"))
        self.assertTrue(clear_project_duplication_cancel_request(self.server_root, "job-1"))

    def test_cancel_during_the_copy_discards_staging_and_publishes_cancelled(self) -> None:
        request = self._request()
        request_path = project_duplication_request_path(self.server_root, "job-cancel")
        write_json_atomic(request_path, request)
        real_copytree = project_duplication.shutil.copytree
        copied: list[str] = []

        def copy_then_cancel(source, target, *args, **kwargs):
            result = real_copytree(source, target, *args, **kwargs)
            # copytree recurses through this same patched name, so only the
            # top-level project and reserving-class copies are recorded.
            projects_dir = project_duplication._extended_length_path(self.projects_dir)
            if Path(source).parent in (projects_dir, projects_dir / "Source" / "data"):
                copied.append(Path(source).name)
            # The user presses Cancel while the first reserving class copies.
            if Path(source).name == "RC A":
                write_project_duplication_cancel_request(
                    self.server_root, "job-cancel", user_name="Wei"
                )
            return result

        with patch.object(project_duplication.shutil, "copytree", side_effect=copy_then_cancel):
            outcome = project_duplication.process_durable_project_duplication_request(
                self.server_root, request_path, request
            )

        self.assertFalse(outcome)
        self.assertEqual(copied, ["Source", "RC A"], "later classes were never copied")
        status = self._read_status("job-cancel")
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["progress"]["stage"], "cancelled")
        # The cancel is honoured before the next progress is published, and the
        # staged copy of RC A is discarded, so the status keeps the last
        # published count rather than claiming a class that no longer exists.
        self.assertEqual(status["progress"]["completed"], 0)
        self.assertEqual(status["progress"]["total"], 3)
        self.assertIn("cancelled", status["message"])
        self.assertFalse((self.projects_dir / "Target").exists(), "no target was published")
        self.assertEqual(list(self.projects_dir.glob(".arcrho-project-duplication-*")), [])
        self.assertFalse(request_path.exists(), "a cancelled job is terminal and leaves the queue")
        self.assertFalse(
            project_duplication_cancel_requested(self.server_root, "job-cancel"),
            "the marker is cleared with the rest of the job's metadata",
        )

    def test_cancel_marker_present_before_the_copy_starts_stops_it_at_once(self) -> None:
        request = self._request("job-early")
        request_path = project_duplication_request_path(self.server_root, "job-early")
        write_json_atomic(request_path, request)
        write_project_duplication_cancel_request(self.server_root, "job-early")

        with patch.object(project_duplication.shutil, "copytree") as copytree:
            outcome = project_duplication.process_durable_project_duplication_request(
                self.server_root, request_path, request
            )

        self.assertFalse(outcome)
        copytree.assert_not_called()
        self.assertEqual(self._read_status("job-early")["status"], "cancelled")
        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertFalse(request_path.exists())

    def test_cancel_after_publication_is_too_late_and_the_target_stays(self) -> None:
        request = self._request("job-late")
        request_path = project_duplication_request_path(self.server_root, "job-late")
        write_json_atomic(request_path, request)
        real_rename = project_duplication.os.rename

        def rename_then_cancel(source, target, *args, **kwargs):
            real_rename(source, target, *args, **kwargs)
            write_project_duplication_cancel_request(self.server_root, "job-late")

        with patch.object(project_duplication.os, "rename", side_effect=rename_then_cancel):
            outcome = project_duplication.process_durable_project_duplication_request(
                self.server_root, request_path, request
            )

        self.assertTrue(outcome)
        self.assertEqual(self._read_status("job-late")["status"], "success")
        self.assertTrue((self.projects_dir / "Target" / "data" / "RC C").is_dir())
        self.assertFalse(project_duplication_cancel_requested(self.server_root, "job-late"))


if __name__ == "__main__":
    unittest.main()
