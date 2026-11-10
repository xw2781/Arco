"""The Excel add-in's picker lists arrive in one hosted read."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
for path in (FRONTEND_ROOT, REPOSITORY_ROOT / "server-components" / "src", REPOSITORY_ROOT / "python-api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS, build_workspace_read_request  # noqa: E402

from app_server.services import (  # noqa: E402
    calculated_dataset_service,
    excel_formula_choices_service,
    project_settings_service,
)

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

PROJECT = "Fake Project"
CLASS_PATH = "PRNJ - PA\\PA\\NJ\\Direct Group\\COL"


class ExcelFormulaChoicesTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name) / "data"
        for folder in ("PRNJ - PA_%5C_PA_%5C_NJ_%5C_Direct Group_%5C_COL", "tmp", ".arcrho-resq-import-staging"):
            (self.data_dir / folder).mkdir(parents=True)
        (self.data_dir / "PRNJ - PA_%5C_PA_%5C_NJ_%5C_Direct Group_%5C_COL" / "index.json").write_text(
            json.dumps({"reserving_class": CLASS_PATH}), encoding="utf-8"
        )
        for target, name, value in (
            (calculated_dataset_service.config, "get_project_data_dir", lambda _project: str(self.data_dir)),
            (
                project_settings_service,
                "_read_project_index",
                lambda: {
                    "projects": [
                        {"name": "b project", "folder": ""},
                        {"name": "A project", "folder": "Team"},
                        {"name": "A project copy", "folder": "Backup"},
                    ]
                },
            ),
            (
                project_settings_service,
                "get_general_settings",
                lambda name: {"data": {"development_end_date": {"b project": "202512"}.get(name, "202606")}},
            ),
            (
                excel_formula_choices_service.dataset_types_service,
                "load_dataset_types_data",
                lambda _project: {
                    "columns": ["Name", "Data Format", "Category", "Calculated", "Formula"],
                    "rows": [["Net Loss--Paid", "Triangle", "F Net Loss", False, ""]],
                },
            ),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_read_is_registered_with_an_optional_project(self) -> None:
        spec = WORKSPACE_READ_KINDS["excel_formula_choices"]
        self.assertEqual((spec.module, spec.function), ("excel_formula_choices_service", "list_formula_choices"))
        self.assertEqual(spec.required, ())
        self.assertEqual(spec.optional, ("project_name",))
        request = build_workspace_read_request(
            request_id="0123456789abcdef", read_kind="excel_formula_choices", kwargs={}, user_name="u"
        )
        self.assertEqual(request["Kwargs"], {})

    def test_one_read_answers_projects_classes_and_dataset_types(self) -> None:
        self.assertEqual(
            excel_formula_choices_service.list_formula_choices(PROJECT),
            {
                "ok": True,
                "projects": ["A project", "A project copy", "b project"],
                "project_folders": ["Team", "Backup", ""],
                "latest_project": "A project",
                "project_name": PROJECT,
                "reserving_classes": [CLASS_PATH],
                "dataset_types": {
                    "columns": ["Name", "Data Format", "Category"],
                    "rows": [["Net Loss--Paid", "Triangle", "F Net Loss"]],
                },
            },
        )

    def test_the_latest_project_is_the_first_registered_with_the_newest_valuation(self) -> None:
        # "A project copy" shares the newest date but was registered after its original.
        self.assertEqual(excel_formula_choices_service.list_formula_choices()["latest_project"], "A project")

    def test_without_a_project_only_the_project_names_are_read(self) -> None:
        response = excel_formula_choices_service.list_formula_choices()
        self.assertEqual(response["projects"], ["A project", "A project copy", "b project"])
        self.assertEqual(response["reserving_classes"], [])
        self.assertEqual(response["dataset_types"]["rows"], [])


if __name__ == "__main__":
    unittest.main()
