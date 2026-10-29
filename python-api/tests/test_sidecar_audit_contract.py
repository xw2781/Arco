"""Canonical sidecar audit vocabulary and attribution projection."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from arcrho_api.sidecar_audit_contract import (  # noqa: E402
    AUDIT_ACTION_AUTO_REFRESH,
    AUDIT_ACTION_INSERT,
    AUDIT_ACTION_UPDATE,
    DATASET_AUDIT_LOG_MAX_ENTRIES,
    PROJECT_AUDIT_LOG_MAX_ENTRIES,
    append_audit_entry,
    is_automatic_audit_action,
    latest_audit_entry,
    normalize_audit_action,
    normalize_audit_log,
    sidecar_attribution,
)


def _entry(index: int, action: str, user: str = "Sam Okafor") -> dict:
    return {"event_date": f"2026-08-20T14:{index:02d}:00Z", "action": action, "user": user}


class AuditLogPolicyTests(unittest.TestCase):
    def test_the_caps_are_the_plan_figures(self) -> None:
        self.assertEqual(DATASET_AUDIT_LOG_MAX_ENTRIES, 200)
        self.assertEqual(PROJECT_AUDIT_LOG_MAX_ENTRIES, 500)

    def test_every_action_is_kept_including_auto_refresh(self) -> None:
        log = normalize_audit_log([
            _entry(1, "Insert"),
            _entry(2, "Auto Refresh"),
            _entry(3, "Update"),
            _entry(4, "Imported"),
        ])
        self.assertEqual([item["action"] for item in log], ["Insert", "Auto Refresh", "Update", "Imported"])

    def test_automatic_entries_on_different_days_are_each_kept(self) -> None:
        log = normalize_audit_log([
            {"event_date": "2026-09-24T19:06:54Z", "action": "Auto Refresh", "user": "Engine"},
            {"event_date": "2026-09-24T20:00:00Z", "action": "Auto Refresh", "user": "Engine"},
            {"event_date": "2026-10-28T19:03:33Z", "action": "Auto Refresh", "user": "Engine"},
        ])
        self.assertEqual(
            [item["event_date"] for item in log],
            ["2026-09-24T20:00:00Z", "2026-10-28T19:03:33Z"],
        )

    def test_consecutive_automatic_entries_collapse_to_the_most_recent(self) -> None:
        log = normalize_audit_log([
            _entry(1, "Update"),
            _entry(2, "Auto Refresh", "Engine"),
            _entry(3, "auto refresh", "Engine"),
            _entry(4, "Auto Refresh", "Engine"),
            _entry(5, "Update"),
            _entry(6, "Auto Refresh", "Engine"),
        ])
        self.assertEqual(
            [(item["event_date"][14:16], item["action"]) for item in log],
            [("01", "Update"), ("04", "Auto Refresh"), ("05", "Update"), ("06", "Auto Refresh")],
        )

    def test_unusable_entries_are_dropped_and_legacy_keys_are_read(self) -> None:
        log = normalize_audit_log([
            {"Event Date": "2026-08-20T14:01:00Z", "Action": "update", "User": "Dana", "Change Info": ""},
            {"event_date": "", "action": "Update"},
            {"event_date": "2026-08-20T14:02:00Z"},
            "text",
            None,
        ])
        self.assertEqual(log, [{
            "event_date": "2026-08-20T14:01:00Z",
            "action": "Update",
            "change_info": "Values",
            "user": "Dana",
        }])
        self.assertEqual(normalize_audit_log(None), [])
        self.assertEqual(normalize_audit_log({"event_date": "x"}), [])

    def test_the_cap_keeps_the_newest_entries(self) -> None:
        log = normalize_audit_log([_entry(index % 60, "Update") for index in range(250)])
        self.assertEqual(len(log), DATASET_AUDIT_LOG_MAX_ENTRIES)
        self.assertEqual(log[-1]["event_date"], _entry(249 % 60, "Update")["event_date"])
        project = normalize_audit_log(
            [_entry(index % 60, "Update") for index in range(600)],
            max_entries=PROJECT_AUDIT_LOG_MAX_ENTRIES,
        )
        self.assertEqual(len(project), PROJECT_AUDIT_LOG_MAX_ENTRIES)

    def test_append_applies_the_same_policy_and_defaults_change_info(self) -> None:
        log = append_audit_entry(None, event_date="2026-08-20T14:01:00Z", action="Insert", user="Dana")
        self.assertEqual(log, [{
            "event_date": "2026-08-20T14:01:00Z",
            "action": "Insert",
            "change_info": "",
            "user": "Dana",
        }])
        log = append_audit_entry(log, event_date="2026-08-20T14:02:00Z", action="Update", user="Dana")
        self.assertEqual(log[-1]["change_info"], "Values")
        log = append_audit_entry(log, event_date="2026-08-20T14:03:00Z", action="Auto Refresh", user="Engine")
        log = append_audit_entry(log, event_date="2026-08-20T14:04:00Z", action="Auto Refresh", user="Engine")
        self.assertEqual([item["action"] for item in log], ["Insert", "Update", "Auto Refresh"])
        self.assertEqual(log[-1]["event_date"], "2026-08-20T14:04:00Z")
        # Only an Insert has nothing to describe; every other action defaults.
        self.assertEqual(log[-1]["change_info"], "Values")
        explicit = append_audit_entry(
            log, event_date="2026-08-20T14:05:00Z", action="Auto Refresh", user="Engine", change_info=""
        )
        self.assertEqual(explicit[-1]["change_info"], "")


class SidecarAuditContractTests(unittest.TestCase):
    def test_action_names_are_the_ones_producers_write(self) -> None:
        self.assertEqual(AUDIT_ACTION_INSERT, "Insert")
        self.assertEqual(AUDIT_ACTION_UPDATE, "Update")
        self.assertEqual(AUDIT_ACTION_AUTO_REFRESH, "Auto Refresh")

    def test_only_an_unattended_rewrite_counts_as_automatic(self) -> None:
        self.assertTrue(is_automatic_audit_action("Auto Refresh"))
        self.assertTrue(is_automatic_audit_action("auto refresh"))
        self.assertFalse(is_automatic_audit_action("Update"))
        self.assertFalse(is_automatic_audit_action(""))
        self.assertFalse(is_automatic_audit_action("Imported"))

    def test_normalization_restores_canonical_casing_and_keeps_the_unknown(self) -> None:
        self.assertEqual(normalize_audit_action("  auto REFRESH "), "Auto Refresh")
        self.assertEqual(normalize_audit_action("insert"), "Insert")
        self.assertEqual(normalize_audit_action("Imported"), "Imported")
        self.assertEqual(normalize_audit_action(None), "")

    def test_the_last_entry_naming_an_action_describes_the_file_as_it_stands(self) -> None:
        entry = latest_audit_entry({
            "audit_log": [
                {"event_date": "2026-08-19T09:00:00Z", "action": "Insert", "user": "Dana Reid"},
                {"event_date": "2026-08-20T14:24:11Z", "action": "Auto Refresh", "user": "Sam Okafor"},
                {"event_date": "2026-08-20T15:00:00Z", "user": "no action recorded"},
            ],
        })
        self.assertEqual(entry["action"], "Auto Refresh")
        self.assertEqual(entry["user"], "Sam Okafor")
        self.assertEqual(entry["at"], "2026-08-20T14:24:11Z")
        self.assertEqual(latest_audit_entry({}), {})
        self.assertEqual(latest_audit_entry({"audit_log": "not a list"}), {})
        self.assertEqual(latest_audit_entry(None), {})

    def test_attribution_prefers_the_audit_entry_and_fills_gaps_from_the_payload(self) -> None:
        self.assertEqual(
            sidecar_attribution({
                "updated_at": "2026-08-20T14:20:00Z",
                "modified_by": "Dana Reid",
                "audit_log": [
                    {"event_date": "2026-08-20T14:24:11Z", "action": "Update", "user": "Sam Okafor"},
                ],
            }),
            {
                "user": "Sam Okafor",
                "action": "Update",
                "at": "2026-08-20T14:24:11Z",
                "automatic": False,
            },
        )
        # A no-op automatic refresh appends no entry and keeps the prior stamp.
        self.assertEqual(
            sidecar_attribution({"updated_at": "2026-08-20T14:20:00Z", "user": "Dana Reid"}),
            {"user": "Dana Reid", "action": "", "at": "2026-08-20T14:20:00Z", "automatic": False},
        )
        self.assertEqual(
            sidecar_attribution({}),
            {"user": "", "action": "", "at": "", "automatic": False},
        )


if __name__ == "__main__":
    unittest.main()
