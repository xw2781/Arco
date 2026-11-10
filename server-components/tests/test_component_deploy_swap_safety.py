"""Every deployed component must survive a swap while it is running.

``swap_deploy`` renames the live app folder aside, which Windows refuses with
``WinError 32`` whenever a process still holds it. A component whose build does
not account for that cannot be deployed while it runs -- and because the build
listener abandons a whole request at the first component failure, one such
component blocks every other component in the same run. That is exactly what
happened to Admin Control on 2026-08-17: the swap exhausted its retries and
Bridge, Engine, Gateway, Launcher and Orchestrator never built.

There are only two sound answers, and this pins that each component has one:

* Stop the live process first, swap, then restore it. Correct when the process
  holding the folder is the component itself.
* Fall back to replacing the folder's contents in place. Correct only for the
  Launcher, where the process pinning the folder is some *other* app that
  inherited it as its working directory, so there is nothing to stop.
"""

from __future__ import annotations

import ast
import sys
import unittest
import unittest.mock
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SOURCE = REPOSITORY_ROOT / "server-components" / "src"
API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
for path in (ENGINE_SOURCE, API_SOURCE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from server_config import default_server_config
from utils import DEPLOYED_COMPONENT_ROLES


# Roles whose live process is not the component itself, so a stop is not
# available. Each must instead recover from the failed rename. The Launcher is
# pinned by whichever app inherited its folder; the Credential helper is a
# client's own short-lived run, started on demand and supervised by nothing.
IN_PLACE_FALLBACK_ROLES = frozenset({"launcher", "credential"})


def _build_script(role: str) -> Path:
    for candidate in ENGINE_SOURCE.glob("arcrho_*/build_exe.py"):
        if candidate.parent.name == f"arcrho_{role}":
            return candidate
    raise AssertionError(f"No build_exe.py for role {role!r}")


def _calls_in(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


class ComponentDeploySwapSafetyTests(unittest.TestCase):
    def test_every_deployed_role_has_a_build_script(self) -> None:
        for role in DEPLOYED_COMPONENT_ROLES:
            self.assertTrue(_build_script(role).is_file(), role)

    def test_each_component_stops_itself_or_recovers_from_a_pinned_folder(self) -> None:
        for role in DEPLOYED_COMPONENT_ROLES:
            with self.subTest(role=role):
                source = _build_script(role).read_text(encoding="utf-8-sig")
                tree = ast.parse(source)
                self.assertIn(
                    "swap_deploy",
                    _calls_in(tree),
                    f"{role}: build script never swaps its deployment",
                )
                if role in IN_PLACE_FALLBACK_ROLES:
                    self.assertIn(
                        "copy_tree_delta",
                        _calls_in(tree),
                        f"{role}: must replace contents in place when the folder is pinned",
                    )
                    continue
                stop_contexts = {
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name.endswith("_stopped")
                }
                self.assertTrue(
                    stop_contexts,
                    f"{role}: no <component>_stopped() context; a running instance "
                    "would make its swap fail with WinError 32",
                )


class AdminKillSwitchTests(unittest.TestCase):
    """Admin Control's stop switch, which nothing else in the fleet provides."""

    KEY = "apps.admin.kill_all"

    def test_the_switch_is_a_documented_default(self) -> None:
        apps = default_server_config(r"C:\Arco Server")["apps"]
        self.assertIn("admin", apps)
        self.assertIs(apps["admin"]["kill_all"], False)

    def test_admin_polls_the_switch_and_shuts_itself_down(self) -> None:
        source = (ENGINE_SOURCE / "arcrho_admin" / "main.py").read_text(encoding="utf-8-sig")
        self.assertIn(f'KILL_ALL_KEY = "{self.KEY}"', source)
        self.assertIn("get_config_value(KILL_ALL_KEY, False)", source)
        self.assertIn('shutdown_server(server, "kill_all")', source)

    def test_the_build_restores_the_switch_it_set(self) -> None:
        """A build that died holding the switch would keep Admin Control down."""

        tree = ast.parse(_build_script("admin").read_text(encoding="utf-8-sig"))
        stopped = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "admin_stopped"
        )
        tries = [node for node in ast.walk(stopped) if isinstance(node, ast.Try)]
        self.assertTrue(tries, "admin_stopped must restore the switch in a finally block")
        self.assertTrue(
            any(
                "set_config_value" in _calls_in(ast.Module(body=item.finalbody, type_ignores=[]))
                for item in tries
            ),
            "admin_stopped must clear apps.admin.kill_all in finally",
        )


class BuildInterpreterTests(unittest.TestCase):
    """Every path that spawns a build must pick the same interpreter.

    ``require_python_310`` refuses anything but 3.10, and the Build Manager is
    launched through ``pyw -3`` -- the *newest* interpreter installed. On
    2026-08-17 that was 3.14.2 on the server, so the GUI's `Build Selected`
    failed on a machine where the listener built the same component fine.
    """

    def test_the_listener_and_the_manager_share_one_resolver(self) -> None:
        import arcrho_build_listener
        import arcrho_build_manager
        from build_runtime import build_python_executable

        self.assertIs(arcrho_build_manager.build_python_executable, build_python_executable)
        self.assertEqual(
            arcrho_build_listener._default_python_executable(),
            build_python_executable(),
        )

    def test_no_build_entry_point_launches_its_own_interpreter(self) -> None:
        for name in ("arcrho_build_manager.py", "arcrho_build_listener.py"):
            with self.subTest(module=name):
                tree = ast.parse((ENGINE_SOURCE / name).read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.List):
                        continue
                    first = node.elts[0] if node.elts else None
                    is_sys_executable = (
                        isinstance(first, ast.Attribute)
                        and first.attr == "executable"
                        and isinstance(first.value, ast.Name)
                        and first.value.id == "sys"
                    )
                    self.assertFalse(
                        is_sys_executable,
                        f"{name}: a command built on sys.executable runs the build under "
                        "whatever launched this process, not Python 3.10",
                    )

    def test_the_resolver_asks_the_launcher_for_the_required_version(self) -> None:
        from build_runtime import REQUIRED_PYTHON_LABEL, build_python_executable

        with unittest.mock.patch("build_runtime.subprocess.run") as run:
            run.return_value = unittest.mock.Mock(returncode=0, stdout="C:\\Py310\\python.exe\n")
            self.assertEqual(build_python_executable(), "C:\\Py310\\python.exe")
        self.assertEqual(run.call_args.args[0][:2], ["py", f"-{REQUIRED_PYTHON_LABEL}"])

    def test_a_missing_launcher_falls_back_rather_than_raising(self) -> None:
        """The build's own version check gives a clearer error than we could."""

        from build_runtime import build_python_executable

        with unittest.mock.patch("build_runtime.subprocess.run", side_effect=OSError):
            self.assertEqual(build_python_executable(), sys.executable)


if __name__ == "__main__":
    unittest.main()
