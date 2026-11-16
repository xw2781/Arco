from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_job_status_retention_contract import (  # noqa: E402
    JOB_STATUS_RETENTION_DAYS,
    job_status_directories,
    prune_finished_job_statuses,
)
from arcrho_project_duplication_contract import (  # noqa: E402
    project_duplication_cancel_path,
    project_duplication_status_path,
    project_duplication_submission_receipt_path,
)


DAY = 86400
TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "tmp_data"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


def _write(path: Path, text: str, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def _status(path: Path, status: str, age_days: float) -> Path:
    return _write(path, json.dumps({"status": status}), age_days)


class PruneFinishedJobStatusesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.old = JOB_STATUS_RETENTION_DAYS + 1
        self.recent = JOB_STATUS_RETENTION_DAYS - 1

    def test_removes_old_finished_statuses_in_every_job_folder(self):
        old, kept = [], []
        for directory in job_status_directories(self.root):
            old.append(_status(directory / "done.json", "success", self.old))
            old.append(_status(directory / "failed.json", "error", self.old))
            kept.append(_status(directory / "recent.json", "success", self.recent))

        removed = prune_finished_job_statuses(self.root)

        self.assertEqual(removed, len(old))
        self.assertFalse(any(path.exists() for path in old))
        self.assertTrue(all(path.exists() for path in kept))

    def test_keeps_whatever_is_not_a_finished_status(self):
        directory = job_status_directories(self.root)[0]
        kept = [
            _status(directory / "queued.json", "queued", self.old),
            _status(directory / "processing.json", "processing", self.old),
            _write(directory / "broken.json", "{not json", self.old),
            _write(directory / "list.json", "[]", self.old),
            _status(directory / "done.claim", "success", self.old),
            _status(directory.with_name("requests") / "done.json", "success", self.old),
            _status(directory.with_name("locks") / "done.json", "success", self.old),
        ]

        self.assertEqual(prune_finished_job_statuses(self.root), 0)
        self.assertTrue(all(path.exists() for path in kept))

    def test_a_duplication_status_takes_its_receipt_lock_and_cancel_marker(self):
        def job(request_id: str, status: str) -> list[Path]:
            receipt = project_duplication_submission_receipt_path(self.root, request_id)
            return [
                _status(project_duplication_status_path(self.root, request_id), status, self.old),
                _write(receipt, "{}", self.old),
                _write(receipt.with_name(f".{receipt.name}.lock"), "", self.old),
                _write(project_duplication_cancel_path(self.root, request_id), "{}", self.old),
            ]

        finished = job("a" * 32, "cancelled")
        queued = job("b" * 32, "queued")

        self.assertEqual(prune_finished_job_statuses(self.root), 1)
        self.assertFalse(any(path.exists() for path in finished))
        self.assertTrue(all(path.exists() for path in queued))

    def test_a_missing_server_root_prunes_nothing(self):
        self.assertEqual(prune_finished_job_statuses(self.root / "absent"), 0)


if __name__ == "__main__":
    unittest.main()
