from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
for path in (FRONTEND_ROOT, FRONTEND_ROOT.parent / "python-api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api import config as api_config
from app_server.services import scripting_preferences_service as service
from app_server.services import user_identity_service

TEST_TEMP_ROOT = FRONTEND_ROOT.parent / "tmp_data"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


PI_TARGET = {"tabType": "project_instance", "title": "NJ_Annual", "projectName": "NJ_Annual"}


def _shortcuts(*groups: dict) -> dict:
    return {"version": 1, "groups": list(groups)}


def _group(group_id: str, title: str, cards: list | None = None) -> dict:
    return {"id": group_id, "title": title, "cards": cards or []}


def _card(card_id: str, label: str, target: dict | None = None) -> dict:
    return {"id": card_id, "label": label, "target": dict(target or PI_TARGET)}


class HomeShortcutNormalizationTests(unittest.TestCase):
    def test_valid_document_round_trips(self) -> None:
        payload = _shortcuts(_group("grp_a", "Q3 Close", [_card("crd_a", "NJ Annual")]))

        normalized = service._normalize_local_project_preferences({"homeShortcuts": payload})

        self.assertEqual(normalized["homeShortcuts"], payload)

    def test_absent_key_is_not_invented(self) -> None:
        normalized = service._normalize_local_project_preferences({"projectName": "NJ_Annual"})

        self.assertNotIn("homeShortcuts", normalized)

    def test_snake_case_key_is_accepted_and_emitted_as_camel_case(self) -> None:
        normalized = service._normalize_local_project_preferences(
            {"home_shortcuts": _shortcuts(_group("grp_a", "Q3 Close"))}
        )

        self.assertEqual(normalized["homeShortcuts"]["groups"][0]["title"], "Q3 Close")

    def test_malformed_groups_and_cards_are_dropped(self) -> None:
        normalized = service._normalize_local_project_preferences(
            {
                "homeShortcuts": {
                    "groups": [
                        "not a group",
                        {"title": "No id"},
                        _group(
                            "grp_a",
                            "Keep",
                            [
                                _card("crd_a", "Keep"),
                                "not a card",
                                {"id": "crd_b", "label": "No target"},
                                {"id": "crd_c", "label": "Untyped", "target": {"title": "x"}},
                                _card("crd_a", "Duplicate id"),
                            ],
                        ),
                    ]
                }
            }
        )

        groups = normalized["homeShortcuts"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual([card["label"] for card in groups[0]["cards"]], ["Keep"])

    def test_stale_activity_timestamps_are_stripped_from_targets(self) -> None:
        normalized = service._normalize_local_project_preferences(
            {"homeShortcuts": _shortcuts(_group("grp_a", "Q3", [_card("crd_a", "NJ", {**PI_TARGET, "ts": 1737000000000})]))}
        )

        self.assertNotIn("ts", normalized["homeShortcuts"]["groups"][0]["cards"][0]["target"])

    def test_titles_and_labels_are_clipped_with_a_fallback(self) -> None:
        normalized = service._normalize_local_project_preferences(
            {"homeShortcuts": _shortcuts(_group("grp_a", "x" * 200, [_card("crd_a", "   ")]))}
        )

        group = normalized["homeShortcuts"]["groups"][0]
        self.assertEqual(len(group["title"]), service.MAX_HOME_SHORTCUT_TITLE_LENGTH)
        self.assertEqual(group["cards"][0]["label"], "NJ_Annual")

    def test_caps_match_the_frontend_document_owner(self) -> None:
        groups = [_group(f"grp_{i}", f"Group {i}") for i in range(service.MAX_HOME_SHORTCUT_GROUPS + 5)]
        groups[0]["cards"] = [
            _card(f"crd_{i}", f"Card {i}") for i in range(service.MAX_HOME_SHORTCUT_CARDS_PER_GROUP + 5)
        ]

        normalized = service._normalize_local_project_preferences({"homeShortcuts": {"groups": groups}})

        self.assertEqual(len(normalized["homeShortcuts"]["groups"]), service.MAX_HOME_SHORTCUT_GROUPS)
        self.assertEqual(
            len(normalized["homeShortcuts"]["groups"][0]["cards"]),
            service.MAX_HOME_SHORTCUT_CARDS_PER_GROUP,
        )


class LocalProjectPreferencesMergeTests(unittest.TestCase):
    """Home shortcuts share the user's `shell` preferences with the frequently written shell
    activity history, so a partial save from either producer must leave the other intact."""

    def test_sections_survive_each_other_s_partial_saves(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as tmp:
            prefs_path = Path(tmp) / "users" / "alice" / "preferences.json"
            # The preferences are in the user's folder on the server; the test
            # runs as the server host does, as the user alice.
            with (
                patch.dict(os.environ, {api_config.RUNTIME_SERVER_ROOT_ENV: tmp}),
                user_identity_service.acting_identity("alice"),
            ):
                shortcuts = _shortcuts(_group("grp_a", "Q3 Close", [_card("crd_a", "NJ Annual")]))
                service.save_local_project_preferences({"homeShortcuts": shortcuts})

                service.save_local_project_preferences(
                    {"shellActivityHistory": {"entries": [{"tabType": "project_instance", "title": "NJ_Annual"}]}}
                )
                after_history = service.get_local_project_preferences()
                self.assertEqual(after_history["homeShortcuts"], shortcuts)

                service.save_local_project_preferences({"homeShortcuts": _shortcuts(_group("grp_b", "Renamed"))})
                after_shortcuts = service.get_local_project_preferences()
                self.assertEqual(len(after_shortcuts["shellActivityHistory"]["entries"]), 1)
                self.assertEqual(after_shortcuts["homeShortcuts"]["groups"][0]["title"], "Renamed")

                with open(prefs_path, "r", encoding="utf-8") as handle:
                    self.assertIn("homeShortcuts", json.load(handle)["shell"])


if __name__ == "__main__":
    unittest.main()
