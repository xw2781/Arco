from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))

from app_server import config
from app_server.services import project_user_preferences_service


class ProjectUserPreferencesDefaultsTests(unittest.TestCase):
    def test_project_settings_defaults_are_added_to_preference_reads(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(FRONTEND_ROOT)) as temp_dir:
            root = Path(temp_dir)
            prefs_path = root / "preferences.json"
            defaults_path = root / "project_settings_preferences.json"
            defaults_path.write_text(
                json.dumps({"projectSettings": {"tables": {"exampleTable": {"widths": {"Name": 240}}}}}),
                encoding="utf-8",
            )

            with (
                patch.object(project_user_preferences_service, "_prefs_path", return_value=str(prefs_path)),
                patch.object(config, "get_project_instance_default_preferences_path", return_value=str(root / "missing.json")),
                patch.object(config, "get_project_settings_default_preferences_path", return_value=str(defaults_path)),
            ):
                result = project_user_preferences_service.get_preferences("Example")

            self.assertEqual(
                result["data"]["projectSettings"]["tables"]["exampleTable"]["widths"]["Name"],
                240,
            )

    def test_saved_project_settings_preferences_are_laid_over_defaults(self) -> None:
        data = {"projectSettings": {"tables": {"savedTable": {"widths": {"Name": 310}, "collapsedGroups": ["a"]}}}}
        defaults = {
            "tables": {
                "savedTable": {"widths": {"Name": 200, "Level": 90}},
                "otherTable": {"widths": {"Name": 240}},
            }
        }
        with patch.object(project_user_preferences_service, "_read_project_settings_defaults", return_value=defaults):
            result = project_user_preferences_service._with_project_settings_defaults(data)

        self.assertEqual(
            result["projectSettings"],
            {
                "tables": {
                    "savedTable": {"widths": {"Name": 310, "Level": 90}, "collapsedGroups": ["a"]},
                    "otherTable": {"widths": {"Name": 240}},
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
