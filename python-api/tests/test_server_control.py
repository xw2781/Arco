"""Starting and stopping an Arco Server whose folder is on this PC."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for source in (REPOSITORY_ROOT / "python-api" / "src", REPOSITORY_ROOT / "server-components" / "src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

import arcrho_server_control as control  # noqa: E402
from server_config import write_server_config  # noqa: E402
from utils import component_app_name  # noqa: E402

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class ServerControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Arco Server"
        (self.root / "config").mkdir(parents=True)
        self.config = self.root / "config" / "config.json"
        self.config.write_text(
            json.dumps({"server_id": "abc", "apps": {"orchestrator": {"kill_all": True, "max_workers": 2}}}),
            encoding="utf-8",
        )

    def _switches(self) -> dict[str, bool]:
        apps = json.loads(self.config.read_text(encoding="utf-8"))["apps"]
        return {role: apps[role]["kill_all"] for role in control.SUPERVISED_ROLES}

    def _heartbeat(self, role: str) -> None:
        folder = self.root / "runtime" / "instances" / f"arcrho_{role}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "PC1@alice@260926-220000-000.json").write_text(
            json.dumps({"Last seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8"
        )

    def _install_orchestrator(self) -> Path:
        exe = control.orchestrator_exe(self.root)
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"exe")
        return exe

    def test_only_a_non_production_folder_on_a_fixed_disk_of_this_pc_may_be_controlled(self) -> None:
        self.assertEqual(control.control_refusal(r"\\server\share\Arco Server"), control.NOT_LOCAL_REFUSAL)
        self.assertEqual(control.control_refusal(control.DEFAULT_WORKSPACE_ROOT), control.PRODUCTION_REFUSAL)
        self.assertEqual(control.control_refusal(self.root, self.root), control.PRODUCTION_REFUSAL)
        with patch.object(control, "is_on_local_fixed_disk", return_value=False):
            self.assertEqual(control.control_refusal(self.root), control.NOT_LOCAL_REFUSAL)
        self.assertEqual(control.control_refusal(self.root), "")
        with self.assertRaisesRegex(control.ServerControlError, "Admin Control"):
            control.require_local_root(self.root, self.root)
        self.assertEqual(control.require_local_root(self.root), self.root.resolve())

    def test_the_orchestrator_folder_is_the_one_server_components_deploys(self) -> None:
        self.assertEqual(control.ORCHESTRATOR_APP_NAME, component_app_name("orchestrator"))

    def test_switches_keep_every_other_key_and_the_canonical_text(self) -> None:
        control.set_stop_switches(self.root, True)
        payload = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(payload["server_id"], "abc")
        self.assertEqual(payload["apps"]["orchestrator"]["max_workers"], 2)
        self.assertEqual(self._switches(), {"orchestrator": True, "engine": True, "gateway": True})

        reference = self.root / "config" / "reference.json"
        write_server_config(reference, payload)
        self.assertEqual(self.config.read_bytes(), reference.read_bytes())

    def test_start_clears_the_switches_and_launches_the_orchestrator_outside_the_callers_tree(self) -> None:
        exe = self._install_orchestrator()
        inherited = {"ARCRHO_SERVER_ROOT": r"E:\Arco Server", "ARCRHO_GATEWAY_CONFIG": r"C:\cred.json"}
        with patch.dict(os.environ, inherited), patch.object(control.subprocess, "Popen") as popen:
            self.assertTrue(control.start_server(self.root))

        self.assertEqual(self._switches(), {"orchestrator": False, "engine": False, "gateway": False})
        command, env = popen.call_args.args[0], popen.call_args.kwargs["env"]
        self.assertEqual(command, f'start "" "{exe}"')
        self.assertEqual(env["ARCRHO_ROOT"], str(self.root))
        self.assertNotIn("ARCRHO_SERVER_ROOT", env)
        self.assertNotIn("ARCRHO_GATEWAY_CONFIG", env)

    def test_start_launches_nothing_while_an_orchestrator_is_live_or_missing(self) -> None:
        with self.assertRaisesRegex(control.ServerControlError, "missing"):
            control.start_server(self.root)
        self._install_orchestrator()
        self._heartbeat("orchestrator")
        with patch.object(control.subprocess, "Popen") as popen:
            self.assertFalse(control.start_server(self.root))
        popen.assert_not_called()
        self.assertFalse(self._switches()["orchestrator"])

    def test_stop_sets_the_switches_and_reports_whether_every_heartbeat_went(self) -> None:
        self._heartbeat("engine")
        self.assertFalse(control.stop_server(self.root, wait_seconds=0))
        self.assertEqual(self._switches(), {"orchestrator": True, "engine": True, "gateway": True})
        self.assertEqual(control.running_roles(self.root), ["engine"])

        for path in (self.root / "runtime" / "instances").rglob("*.json"):
            path.unlink()
        self.assertTrue(control.stop_server(self.root, wait_seconds=0))


if __name__ == "__main__":
    unittest.main()
