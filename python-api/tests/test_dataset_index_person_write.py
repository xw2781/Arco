from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from arcrho_api.dataset_index_contract import build_dataset_index_payload


def _entry(date: str, action: str, user: str) -> dict:
    return {"event_date": date, "action": action, "change_info": "Values", "user": user}


class DatasetIndexPersonWriteTests(unittest.TestCase):
    def row_for(self, sidecar: dict) -> dict:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            sidecars = Path(folder) / "sidecars"
            sidecars.mkdir()
            (sidecars / "Paid Loss.json").write_text(json.dumps(sidecar), encoding="utf-8")
            payload = build_dataset_index_payload("Demo", r"Auto\PP", folder)
        return next(row for row in payload["files"] if row["name"] == "Paid Loss")

    def test_table_names_the_last_write_that_was_not_an_auto_refresh(self):
        row = self.row_for({
            "dataset_name": "Paid Loss",
            "data_format": "Triangle",
            "updated_at": "2026-10-28T19:04:10.205Z",
            "modified_by": "Wei, Xiao",
            "audit_log": [
                _entry("2026-09-25T11:36:25.000Z", "Update", "Zhu, Jay"),
                _entry("2026-10-28T19:04:10.205Z", "Auto Refresh", "Wei, Xiao"),
            ],
        })
        self.assertEqual(row["last_modified"], "2026-09-25T11:36:25Z")
        self.assertEqual(row["user"], "Zhu, Jay")

    def test_object_with_only_auto_refreshes_keeps_its_own_stamp(self):
        row = self.row_for({
            "dataset_name": "Paid Loss",
            "data_format": "Triangle",
            "updated_at": "2026-10-28T19:04:10.205Z",
            "modified_by": "Wei, Xiao",
            "audit_log": [_entry("2026-10-28T19:04:10.205Z", "Auto Refresh", "Wei, Xiao")],
        })
        self.assertEqual(row["last_modified"], "2026-10-28T19:04:10Z")
        self.assertEqual(row["user"], "Wei, Xiao")


if __name__ == "__main__":
    unittest.main()
