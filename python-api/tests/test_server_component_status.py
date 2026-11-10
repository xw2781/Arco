"""The shared reader of Arco Server heartbeats and stop switches."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY_ROOT / "python-api" / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from arcrho_server_component_status import (  # noqa: E402
    COMPONENT_ROLES,
    component_status,
    is_on_local_fixed_disk,
    list_instances,
    read_stop_switches,
    stale_after_seconds,
)

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
NOW = datetime(2026, 9, 26, 22, 0, 0)


def _stamp(seconds_ago: int) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S")


class ServerComponentStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _heartbeat(self, role: str, name: str, payload: dict | str) -> Path:
        folder = self.root / "runtime" / "instances" / f"arcrho_{role}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return path

    def test_engine_turns_stale_after_six_seconds_and_the_gateway_after_sixty(self) -> None:
        self._heartbeat("engine", "PC1@alice@260926-215959-001.json", {"Server": "PC1@alice@260926-215959-001", "Last seen": _stamp(6)})
        self._heartbeat("engine", "PC1@alice@260926-215959-002.json", {"Server": "PC1@alice@260926-215959-002", "Last seen": _stamp(7)})
        self._heartbeat("gateway", "PC1@svc@260926-210000-000.json", {"Server": "PC1@svc@260926-210000-000", "Last seen": _stamp(59)})

        rows = {row["name"]: row for row in list_instances(self.root, now=NOW)}

        self.assertEqual(rows["PC1@alice@260926-215959-001.json"]["status"], "Active")
        self.assertEqual(rows["PC1@alice@260926-215959-002.json"]["status"], "Stale")
        self.assertEqual(rows["PC1@alice@260926-215959-002.json"]["age_seconds"], 7)
        gateway = rows["PC1@svc@260926-210000-000.json"]
        self.assertEqual((gateway["status"], gateway["machine"], gateway["user"]), ("Active", "PC1", "svc"))
        self.assertEqual(gateway["created"], "2026-09-26 21:00:00")
        self.assertEqual(stale_after_seconds("bridge_worker"), 6)
        self.assertEqual(stale_after_seconds("orchestrator"), 60)

    def test_missing_folders_list_no_instances_but_every_role(self) -> None:
        self.assertEqual(list_instances(self.root / "absent", now=NOW), [])
        status = component_status(self.root / "absent", now=NOW)
        self.assertEqual([role["role"] for role in status["roles"]], list(COMPONENT_ROLES))
        self.assertTrue(all(role["instances"] == [] and role["stop_switch"] is False for role in status["roles"]))
        self.assertEqual(status["checked_at"], "2026-09-26 22:00:00")

    def test_a_garbled_heartbeat_still_lists_with_no_age_as_admin_control_does(self) -> None:
        self._heartbeat("orchestrator", "PC2@bob@260926-100000-000.json", "{not json")

        (row,) = list_instances(self.root, now=NOW)

        self.assertEqual((row["role"], row["server"], row["machine"], row["user"]), ("orchestrator", "PC2@bob@260926-100000-000", "PC2", "bob"))
        self.assertIsNone(row["age_seconds"])
        self.assertEqual(row["status"], "Active")

    def test_stop_switches_come_from_the_server_config(self) -> None:
        (self.root / "config").mkdir()
        (self.root / "config" / "config.json").write_text(
            json.dumps({"apps": {"engine": {"kill_all": True}, "gateway": {"kill_all": False}, "bridge": "bad"}}),
            encoding="utf-8",
        )

        switches = read_stop_switches(self.root)

        self.assertTrue(switches["engine"])
        self.assertFalse(switches["gateway"])
        self.assertFalse(switches["bridge"])
        engine = next(role for role in component_status(self.root, now=NOW)["roles"] if role["role"] == "engine")
        self.assertTrue(engine["stop_switch"])

    def test_a_garbled_config_sets_no_switch(self) -> None:
        (self.root / "config").mkdir()
        (self.root / "config" / "config.json").write_text("{", encoding="utf-8")
        self.assertFalse(any(read_stop_switches(self.root).values()))

    def test_network_paths_are_never_local(self) -> None:
        self.assertFalse(is_on_local_fixed_disk(r"\\NE7SASWPN02\E\Arco Server"))
        self.assertFalse(is_on_local_fixed_disk("relative\\folder"))
        self.assertTrue(is_on_local_fixed_disk(self.root))


if __name__ == "__main__":
    unittest.main()
