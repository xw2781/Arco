"""Per-user instance scoping on a shared PC.

Every user session contributes its own bridge (on that user's ResQ GUI and
license), so bridge/worker bookkeeping must never touch another user's
heartbeats, and the admin folder-access helpers must build safe icacls calls.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE_SRC = Path(__file__).resolve().parents[1] / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
if str(ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC))

from arcrho_bridge import main as bridge_main  # noqa: E402
from arcrho_orchestrator import main as orchestrator_main  # noqa: E402


def _write_heartbeat(folder, name, payload, age_seconds=1):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


class BridgePerUserScopingTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _worker_folder(self):
        return self.server_root / "runtime" / "instances" / "arcrho_bridge_worker"

    def test_worker_heartbeat_discovery_filters_by_user(self):
        folder = self._worker_folder()
        alice = _write_heartbeat(
            folder,
            "bridge_worker@PC@alice@260807-1.json",
            {"Role": "bridge_worker", "ResQGuiRunning": True, "User": "Alice"},
        )
        _write_heartbeat(
            folder,
            "bridge_worker@PC@bob@260807-2.json",
            {"Role": "bridge_worker", "ResQGuiRunning": True, "User": "bob"},
        )

        all_workers = bridge_main.discover_fresh_bridge_worker_heartbeats(
            self.server_root
        )
        alice_workers = bridge_main.discover_fresh_bridge_worker_heartbeats(
            self.server_root, user="alice"
        )

        self.assertEqual(len(all_workers), 2)
        self.assertEqual(alice_workers, (alice,))

    def test_remove_worker_heartbeats_only_touches_one_users_files(self):
        folder = self._worker_folder()
        alice = _write_heartbeat(
            folder,
            "bridge_worker@PC@alice@260807-1.json",
            {"Role": "bridge_worker", "User": "alice"},
        )
        bob = _write_heartbeat(
            folder,
            "bridge_worker@PC@bob@260807-2.json",
            {"Role": "bridge_worker", "User": "bob"},
        )

        with patch.object(bridge_main, "worker_instance_folder", return_value=folder):
            bridge_main.remove_worker_heartbeats("alice")

        self.assertFalse(alice.exists())
        self.assertTrue(bob.exists())

    def test_remove_worker_heartbeats_without_user_removes_all(self):
        folder = self._worker_folder()
        alice = _write_heartbeat(
            folder,
            "bridge_worker@PC@alice@260807-1.json",
            {"Role": "bridge_worker", "User": "alice"},
        )
        bob = _write_heartbeat(
            folder,
            "bridge_worker@PC@bob@260807-2.json",
            {"Role": "bridge_worker", "User": "bob"},
        )

        with patch.object(bridge_main, "worker_instance_folder", return_value=folder):
            bridge_main.remove_worker_heartbeats()

        self.assertFalse(alice.exists())
        self.assertFalse(bob.exists())

    def test_same_user_bridge_detection_ignores_other_users_and_stale_files(self):
        folder = self.server_root / "runtime" / "instances" / "arcrho_bridge"
        _write_heartbeat(
            folder,
            "bridge@PC@bob@260807-1.json",
            {"Role": "bridge", "User": "bob"},
        )
        _write_heartbeat(
            folder,
            "bridge@PC@alice@260807-2.json",
            {"Role": "bridge", "User": "alice"},
            age_seconds=bridge_main.BRIDGE_STALE_AFTER_SECONDS + 5,
        )

        with patch.object(bridge_main, "resolve_app_path", return_value=folder):
            self.assertFalse(bridge_main.same_user_bridge_is_running("alice"))
            self.assertTrue(bridge_main.same_user_bridge_is_running("BOB"))

    def test_instance_file_user_parses_both_id_layouts(self):
        self.assertEqual(
            bridge_main._instance_file_user("bridge_worker@PC@alice@260807-1.json"),
            "alice",
        )
        self.assertEqual(bridge_main._instance_file_user("PC@bob@260807-1.json"), "bob")
        self.assertEqual(bridge_main._instance_file_user("fresh.json"), "")


class OrchestratorPerUserBridgeTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.folder = Path(self.temp_dir.name) / "arcrho_bridge"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_user_file_counts_counts_only_that_user(self):
        _write_heartbeat(self.folder, "bridge@PC@alice@260807-1.json", {})
        _write_heartbeat(self.folder, "bridge@PC@bob@260807-2.json", {})
        _write_heartbeat(self.folder, "bridge@PC@bob@260807-3.json", {})

        self.assertEqual(orchestrator_main.user_file_counts(str(self.folder), "Alice"), 1)
        self.assertEqual(orchestrator_main.user_file_counts(str(self.folder), "bob"), 2)
        self.assertEqual(orchestrator_main.user_file_counts(str(self.folder), "carol"), 0)

    def test_limit_user_instance_files_keeps_other_users_untouched(self):
        old_alice = _write_heartbeat(
            self.folder, "bridge@PC@alice@260807-1.json", {}, age_seconds=30
        )
        new_alice = _write_heartbeat(
            self.folder, "bridge@PC@alice@260807-2.json", {}, age_seconds=1
        )
        bob = _write_heartbeat(
            self.folder, "bridge@PC@bob@260807-3.json", {}, age_seconds=300
        )

        orchestrator_main.limit_user_instance_files(str(self.folder), "alice", 1)

        self.assertFalse(old_alice.exists())
        self.assertTrue(new_alice.exists())
        self.assertTrue(bob.exists())


class AdminFolderAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Admin Control logs to <root>\runtime\logs as it loads and again as the
        # process exits, and with no root set it falls back to production's.
        # Its root is fixed at import, so the import runs against a test root.
        with patch.dict(os.environ, {"ARCRHO_ROOT": str(TEST_TMP_ROOT / "admin_root")}):
            from arcrho_admin import main as admin_main  # noqa: E402

        cls.admin_main = admin_main

    def test_parse_icacls_entries(self):
        folder = r"E:\Arco Server"
        output = "\n".join(
            [
                r"E:\Arco Server BUILTIN\Users:(OI)(CI)(M)",
                r"                 NT AUTHORITY\SYSTEM:(I)(OI)(CI)(F)",
                r"                 PRCINS\xwei:(I)(OI)(CI)(RX)",
                "",
                "Successfully processed 1 files; Failed processing 0 files",
            ]
        )

        entries = self.admin_main.parse_icacls_entries(output, folder)

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["principal"], r"BUILTIN\Users")
        self.assertTrue(entries[0]["modify"])
        self.assertFalse(entries[0]["inherited"])
        self.assertEqual(entries[1]["principal"], r"NT AUTHORITY\SYSTEM")
        self.assertTrue(entries[1]["inherited"])
        self.assertTrue(entries[1]["modify"])
        self.assertEqual(entries[2]["principal"], r"PRCINS\xwei")
        self.assertFalse(entries[2]["modify"])

    def test_validate_principal_rejects_flag_like_input(self):
        self.assertEqual(self.admin_main.validate_principal(" Users "), "Users")
        self.assertEqual(
            self.admin_main.validate_principal(r"PRCINS\some user"),
            r"PRCINS\some user",
        )
        for bad in ("", "/grant", "a:b", "x;y", 'a"b', "a(b)"):
            with self.assertRaises(ValueError):
                self.admin_main.validate_principal(bad)

    def test_folder_access_principals_use_profile_names_with_domain_prefix(self):
        with patch.object(
            self.admin_main,
            "_user_profile_directories",
            return_value=["Alice", "Public"],
        ), patch.dict(os.environ, {"USERDOMAIN": "PRCINS"}, clear=False):
            result = self.admin_main.folder_access_principals()

        self.assertEqual(
            result,
            {
                "options": [
                    {"value": r"PRCINS\Alice", "label": r"PRCINS\Alice"},
                    {"value": r"PRCINS\Public", "label": r"PRCINS\Public"},
                ],
                "warnings": [],
            },
        )

    def test_resolve_access_folder_stays_inside_the_server_root(self):
        with tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT)) as temp_root:
            root = Path(temp_root)
            (root / "runtime").mkdir()
            with patch.object(self.admin_main, "PROJECT_ROOT", root):
                self.assertEqual(self.admin_main.resolve_access_folder("root"), root)
                self.assertEqual(
                    self.admin_main.resolve_access_folder("runtime"),
                    root / "runtime",
                )
                with self.assertRaises(ValueError):
                    self.admin_main.resolve_access_folder("..")
                with self.assertRaises(ValueError):
                    self.admin_main.resolve_access_folder("missing-folder")


if __name__ == "__main__":
    unittest.main()
