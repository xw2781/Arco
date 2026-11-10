from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tools.arcrho_dev_control import runtime

# Every test temp directory lives under one gitignored folder at the
# repository root, so a suite that dies before teardown cannot scatter
# tmp folders beside the code.
TEST_TEMP_ROOT = Path(runtime.REPO_ROOT) / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class ArcRhoDevControlRuntimeTests(unittest.TestCase):
    def test_launcher_handoff_does_not_capture_detached_supervisor_output(self) -> None:
        process = Mock()
        process.wait.return_value = 0

        with patch.object(runtime.subprocess, "Popen", return_value=process) as popen:
            return_code = runtime._run_launcher(["cmd.exe", "/c", "launcher.bat"])

        self.assertEqual(return_code, 0)
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 15})
        self.assertEqual(
            popen.call_args.kwargs,
            {
                "cwd": str(runtime.REPO_ROOT),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "creationflags": runtime._windows_creation_flags(),
            },
        )

    def test_launcher_handoff_times_out_cleanly(self) -> None:
        process = Mock()
        process.wait.side_effect = [subprocess.TimeoutExpired(["cmd.exe"], 15), None]

        with patch.object(runtime.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "did not finish"):
                runtime._run_launcher(["cmd.exe"], timeout=15)

        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_args_list[-1].args, ())

    def test_process_selection_includes_descendants(self) -> None:
        frontend = str(runtime.FRONTEND_ROOT)
        processes = [
            runtime.ProcessInfo(100, 1, "pythonw.exe", f'pythonw.exe "{frontend}\\electron_shell.py"'),
            runtime.ProcessInfo(101, 100, "cmd.exe", "cmd.exe /c npm run electron"),
            runtime.ProcessInfo(102, 101, "electron.exe", "electron.exe ."),
            runtime.ProcessInfo(200, 1, "python.exe", "python unrelated.py"),
        ]
        with (
            patch.object(runtime, "_query_windows_processes", return_value=processes),
            patch.object(runtime, "_read_runtime_anchor_pids", return_value=set()),
        ):
            selected = runtime.list_arcrho_dev_processes()
        self.assertEqual({item.pid for item in selected}, {100, 101, 102})

    def test_process_anchor_adds_safe_ancestors_and_descendants(self) -> None:
        processes = [
            runtime.ProcessInfo(90, 1, "pythonw.exe", "C:\\Python310\\pythonw.exe"),
            runtime.ProcessInfo(100, 90, "cmd.exe", "C:\\Windows\\cmd.exe"),
            runtime.ProcessInfo(101, 100, "electron.exe", "electron.exe"),
            runtime.ProcessInfo(102, 101, "python.exe", "C:\\Python310\\python.exe"),
            runtime.ProcessInfo(200, 1, "explorer.exe", "C:\\Windows\\explorer.exe"),
        ]
        with (
            patch.object(runtime, "_query_windows_processes", return_value=processes),
            patch.object(runtime, "_read_runtime_anchor_pids", return_value={101}),
        ):
            selected = runtime.list_arcrho_dev_processes()
        self.assertEqual({item.pid for item in selected}, {90, 100, 101, 102})

    def test_cache_paths_are_children_of_appdata_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            appdata = Path(temp_dir)
            with patch.dict(os.environ, {"APPDATA": str(appdata)}, clear=False):
                root = runtime._electron_user_data_root().resolve()
                paths = runtime._electron_cache_paths()
        self.assertGreater(len(paths), 5)
        self.assertTrue(all(path.resolve().parent == root for path in paths))
        self.assertNotIn(root / "prefs", paths)
        self.assertNotIn(root / "logs", paths)

    def test_preference_discovery_uses_configured_project_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            projects = Path(temp_dir) / "projects"
            preference = projects / "Sample" / "users" / "alice" / "preferences.json"
            preference.parent.mkdir(parents=True)
            preference.write_text("{}", encoding="utf-8")
            config = SimpleNamespace(
                PROJECT_SETTINGS_DIR=str(projects),
                PROJECT_USER_PREFERENCES_FILE="preferences.json",
            )
            with patch.object(runtime, "_load_frontend_config", return_value=config):
                discovered = runtime.list_project_user_preferences()
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]["project"], "Sample")
        self.assertEqual(discovered[0]["user"], "alice")

    def setUp(self) -> None:
        runtime.invalidate_preference_cache()
        self.addCleanup(runtime.invalidate_preference_cache)

    def test_repeated_status_polls_reuse_one_workspace_scan(self) -> None:
        with (
            patch.object(runtime, "list_project_user_preferences", return_value=[]) as discover,
            patch.object(runtime, "list_arcrho_dev_processes", return_value=[]),
            patch.object(runtime, "_backend_health", return_value={"reachable": False}),
        ):
            runtime.get_state()
            runtime.get_state()
            runtime.get_state()
            self.assertEqual(discover.call_count, 1)
            runtime.invalidate_preference_cache()
            runtime.get_state()
            self.assertEqual(discover.call_count, 2)

    def test_unreachable_workspace_share_warns_without_failing_state(self) -> None:
        denied = PermissionError(5, "Access is denied", r"E:\Arco Server\projects")

        with (
            patch.object(runtime, "_load_frontend_config", side_effect=denied),
            patch.object(runtime, "list_arcrho_dev_processes", return_value=[]),
            patch.object(runtime, "_backend_health", return_value={"reachable": False}),
        ):
            runtime._PREFERENCE_PATHS["stale"] = Path("stale.json")
            state = runtime.get_state()

        self.assertTrue(state["ok"])
        self.assertEqual(state["preferences"], [])
        self.assertEqual(runtime._PREFERENCE_PATHS, {})
        self.assertEqual(len(state["warnings"]), 1)
        self.assertIn("Access is denied", state["warnings"][0])
        self.assertTrue(state["folders"])

    def test_clear_preference_moves_file_to_backup_before_relaunch(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            preference = Path(temp_dir) / "preferences.json"
            preference.write_text('{"saved": true}', encoding="utf-8")
            selected = {"id": "pref-id", "project": "Sample", "user": "alice", "path": str(preference)}

            def discover() -> list[dict[str, str]]:
                runtime._PREFERENCE_PATHS.clear()
                runtime._PREFERENCE_PATHS["pref-id"] = preference
                return [selected]

            with (
                patch.object(runtime, "list_project_user_preferences", side_effect=discover),
                patch.object(runtime, "stop_arcrho_dev_processes", return_value={"stopped": 3}),
                patch.object(runtime, "launch_arcrho_dev", return_value={"launched": True}),
            ):
                result = runtime.clear_project_user_preference_and_relaunch("pref-id")

            self.assertFalse(preference.exists())
            backup = Path(result["backup_path"])
            self.assertTrue(backup.is_file())
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"saved": true}')


if __name__ == "__main__":
    unittest.main()
