"""A hand-entered triangle kept from an earlier valuation is rolled up by cell position."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = FRONTEND_ROOT.parent
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

from app_server import config
from app_server.services import dataset_service, precedent_cache_service

SIDECAR = {
    "source_kind": "input",
    "data_format": "Triangle",
    "cumulative": True,
    "calendar": False,
    "origin_length": 12,
    "development_length": 12,
    "stored_origin_length": 12,
    "stored_development_length": 1,
}


def _monthly_rows(months: int) -> list[list[float]]:
    # Ten yearly origins from January 2017 at monthly development; each cell
    # holds its own age in months, so a rolled-up cell names the age it read.
    return [[float(age) for age in range(1, months - 12 * row + 1)] for row in range(10)]


class RollupPositionalValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        settings_path = Path(self.temp_dir.name) / "general_settings.json"
        # Valued at September 2026: 117 months from January 2017.
        settings_path.write_text(
            '{"origin_start_date":"201701","origin_end_date":"202612","development_end_date":"202609"}',
            encoding="utf-8",
        )
        settings_patch = patch.object(config, "get_general_settings_path", return_value=str(settings_path))
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

    def test_triangle_at_the_project_valuation_keeps_the_project_anchor(self):
        rows = _monthly_rows(117)
        self.assertEqual(dataset_service.rollup_valuation_months("P", rows, 1), 117)
        view = precedent_cache_service.rollup_rows("P", SIDECAR, rows, 12, 12)
        self.assertEqual(view[0], [9.0 + 12 * column for column in range(10)])

    def test_triangle_from_the_month_before_is_read_by_position(self):
        rows = _monthly_rows(116)
        self.assertEqual(dataset_service.rollup_valuation_months("P", rows, 1), 116)
        view = precedent_cache_service.rollup_rows("P", SIDECAR, rows, 12, 12)
        self.assertEqual(view[0], [8.0 + 12 * column for column in range(10)])
        self.assertEqual(
            [sum(cell is not None for cell in row) for row in view],
            [10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
        )

    def test_calendar_triangle_keeps_the_project_anchor(self):
        self.assertEqual(
            dataset_service.rollup_valuation_months("P", _monthly_rows(116), 1, calendar=True), 117
        )


if __name__ == "__main__":
    unittest.main()
