"""Instance-cap enforcement when several Orchestrators supervise one workspace.

Every signed-in user runs an Orchestrator against the same shared workspace, so
the cap on machine-wide components is only as good as the coordination between
them. These tests pin the two ways the cap used to be exceeded: concurrent
Orchestrators each filling the same deficit, and one Orchestrator relaunching
into the gap before a cold component publishes its heartbeat.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ENGINE_SRC = Path(__file__).resolve().parents[1] / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
if str(ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC))

from arcrho_orchestrator import main as orchestrator_main  # noqa: E402
import build_runtime  # noqa: E402


class ReplenishmentCapTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.root = Path(self.temp_dir.name)
        self.live = 0
        self.launches = 0
        patcher = patch.object(orchestrator_main, "get_project_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Waiting stops when this Orchestrator's own heartbeat is gone, so give
        # the tests a live one and keep the refresh out of the way.
        own_heartbeat = self.root / "arcrho_orchestrator.json"
        own_heartbeat.write_text("{}", encoding="utf-8")
        identity = patch.object(orchestrator_main, "id_path", str(own_heartbeat))
        identity.start()
        self.addCleanup(identity.stop)
        heartbeat = patch.object(orchestrator_main, "touch_heartbeat")
        heartbeat.start()
        self.addCleanup(heartbeat.stop)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _count(self):
        return self.live

    def _launch_registering(self, role):
        """A launch whose component publishes its heartbeat immediately."""

        self.launches += 1
        self.live += 1
        return True

    def _launch_silent(self, role):
        """A launch whose component never registers within the timeout."""

        self.launches += 1
        return True

    def test_replenishment_stops_at_the_configured_cap(self):
        with patch.object(orchestrator_main, "launch_app", self._launch_registering):
            orchestrator_main.replenish_instances("engine", "engine", self._count, 5)

        self.assertEqual(self.launches, 5)
        self.assertEqual(self.live, 5)

    def test_a_second_orchestrator_cannot_launch_while_the_slot_is_held(self):
        """The lock, not the instance count, is what stops the second launch."""

        with orchestrator_main.launch_slot("engine") as acquired:
            self.assertTrue(acquired)
            with patch.object(orchestrator_main, "launch_app", self._launch_registering):
                orchestrator_main.replenish_instances("engine", "engine", self._count, 5)

        self.assertEqual(self.launches, 0)
        self.assertEqual(self.live, 0)

    def test_the_slot_is_released_for_the_next_orchestrator(self):
        with orchestrator_main.launch_slot("engine") as acquired:
            self.assertTrue(acquired)
        with orchestrator_main.launch_slot("engine") as acquired:
            self.assertTrue(acquired)

    def test_a_lock_left_by_a_dead_orchestrator_is_reclaimed(self):
        path = orchestrator_main.launch_lock_path("engine")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        stale = orchestrator_main.time.time() - (
            orchestrator_main.LAUNCH_LOCK_STALE_SECONDS + 60
        )
        orchestrator_main.os.utime(path, (stale, stale))

        with orchestrator_main.launch_slot("engine") as acquired:
            self.assertTrue(acquired)

    def test_a_component_that_never_registers_is_launched_once_per_pass(self):
        """A crashing component must not be spawned once per missing instance."""

        with (
            patch.object(orchestrator_main, "launch_app", self._launch_silent),
            patch.object(orchestrator_main, "INSTANCE_REGISTRATION_TIMEOUT_SECONDS", 0.05),
            patch.object(orchestrator_main, "INSTANCE_POLL_SECONDS", 0.01),
        ):
            orchestrator_main.replenish_instances("engine", "engine", self._count, 5)

        self.assertEqual(self.launches, 1)

    def test_a_registering_component_keeps_the_pass_going(self):
        """Only a failed registration ends the pass early, not a slow one."""

        with (
            patch.object(orchestrator_main, "launch_app", self._launch_registering),
            patch.object(orchestrator_main, "INSTANCE_REGISTRATION_TIMEOUT_SECONDS", 0.05),
            patch.object(orchestrator_main, "INSTANCE_POLL_SECONDS", 0.01),
        ):
            orchestrator_main.replenish_instances("engine", "engine", self._count, 3)

        self.assertEqual(self.launches, 3)

    def test_waiting_ends_as_soon_as_the_instance_registers(self):
        counts = iter([0, 0, 1])

        with (
            patch.object(orchestrator_main, "INSTANCE_POLL_SECONDS", 0.01),
            patch.object(orchestrator_main, "INSTANCE_REGISTRATION_TIMEOUT_SECONDS", 5),
        ):
            registered = orchestrator_main.wait_for_new_instance(lambda: next(counts), 0)

        self.assertTrue(registered)

    def test_waiting_gives_up_when_the_instance_never_registers(self):
        with (
            patch.object(orchestrator_main, "INSTANCE_POLL_SECONDS", 0.01),
            patch.object(orchestrator_main, "INSTANCE_REGISTRATION_TIMEOUT_SECONDS", 0.05),
        ):
            registered = orchestrator_main.wait_for_new_instance(lambda: 0, 0)

        self.assertFalse(registered)

    def test_per_user_components_do_not_share_one_lock(self):
        """A bridge is per session, so one user's launch cannot block another's."""

        with orchestrator_main.launch_slot("bridge@alice") as alice:
            self.assertTrue(alice)
            with orchestrator_main.launch_slot("bridge@bob") as bob:
                self.assertTrue(bob)


class BuildWorkspaceAlignmentTests(unittest.TestCase):
    """Remote deploys must read the config and heartbeats they deploy against."""

    def test_no_deploy_root_leaves_resolution_to_utils(self):
        environment = {}

        self.assertIsNone(build_runtime.align_workspace_root_env(environment))
        self.assertEqual(environment, {})

    def test_deploy_root_sets_the_workspace_root(self):
        environment = {"ARCRHO_DEPLOY_ROOT": r"\\devpc\arcrho\Arco Server"}

        resolved = build_runtime.align_workspace_root_env(environment)

        self.assertEqual(str(resolved), r"\\devpc\arcrho\Arco Server")
        self.assertEqual(environment["ARCRHO_ROOT"], r"\\devpc\arcrho\Arco Server")

    def test_a_matching_workspace_root_is_kept(self):
        environment = {
            "ARCRHO_DEPLOY_ROOT": r"E:\Arco Server",
            "ARCRHO_ROOT": r"e:\arco server",
        }

        resolved = build_runtime.align_workspace_root_env(environment)

        self.assertEqual(str(resolved), r"E:\Arco Server")
        self.assertEqual(environment["ARCRHO_ROOT"], r"e:\arco server")

    def test_conflicting_roots_stop_the_build(self):
        environment = {
            "ARCRHO_DEPLOY_ROOT": r"\\devpc\arcrho\Arco Server",
            "ARCRHO_ROOT": r"E:\Arco Server",
        }

        with self.assertRaises(RuntimeError):
            build_runtime.align_workspace_root_env(environment)

    def test_a_unc_workspace_is_not_a_local_disk(self):
        self.assertFalse(build_runtime.is_local_fixed_path(r"\\devpc\arcrho\Arco Server"))

    def test_a_relative_path_is_not_treated_as_a_local_disk(self):
        self.assertFalse(build_runtime.is_local_fixed_path("Arco Server"))


if __name__ == "__main__":
    unittest.main()
