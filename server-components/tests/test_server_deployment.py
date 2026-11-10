"""ArcRho Server release, deployment, repair, rollback, and uninstall contracts."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
API_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for import_root in (ENGINE_SRC, API_SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_server_deployer import main as deployer  # noqa: E402
import build_runtime  # noqa: E402
from server_config import (  # noqa: E402
    default_server_config,
    read_server_config,
    write_server_config,
)
from server_deployment_contract import (  # noqa: E402
    INSTALL_METADATA_RELATIVE_DIR,
    MANIFEST_FILE_NAME,
    RECEIPT_FILE_NAME,
    SERVER_COMPONENTS,
    build_manifest,
    compare_versions,
    normalize_manifest,
)
import utils  # noqa: E402


NO_KILL_SWITCHES = {key: False for key in deployer.KILL_SWITCH_PATHS}


def _build_payload(parent: Path, version: str, marker: str) -> tuple[Path, Path]:
    payload = parent / f"payload-{version}-{marker}"
    component_roots = []
    for component in SERVER_COMPONENTS:
        root = payload / component.relative_destination
        root.mkdir(parents=True)
        (root / f"{component.app_name}.exe").write_bytes(
            f"{version}:{marker}:{component.role}".encode("utf-8")
        )
        internal = root / "_internal"
        internal.mkdir()
        (internal / "runtime.dat").write_bytes(
            f"runtime:{version}:{component.role}".encode("utf-8")
        )
        component_roots.append((component, root))
    manifest = build_manifest(version, component_roots)
    manifest_path = payload / MANIFEST_FILE_NAME
    manifest_path.write_text(persisted_json_text(manifest), encoding="utf-8")
    return payload, manifest_path


class ServerDeploymentTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.base = Path(self.temp.name)
        self.appdata = self.base / "AppData"
        self.appdata.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _runtime_patches(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(
            patch.object(deployer, "_windows_drive_type", return_value=deployer.DRIVE_FIXED)
        )
        stack.enter_context(
            patch.object(deployer, "_stop_components", return_value=dict(NO_KILL_SWITCHES))
        )
        stack.enter_context(patch.object(deployer, "_register_shortcuts"))
        stack.enter_context(patch.object(deployer, "_remove_shortcuts"))
        stack.enter_context(patch.object(deployer, "_start_launcher"))
        stack.enter_context(patch.object(deployer, "_wait_for_startup"))
        # A rollback asks the Admin Control on this PC to shut down; never the real one.
        stack.enter_context(patch.object(deployer, "_request_admin_shutdown"))
        stack.enter_context(patch.dict(os.environ, {"APPDATA": str(self.appdata)}))
        return stack

    def _deploy(
        self,
        root: Path,
        payload: Path,
        manifest: Path,
        **overrides,
    ):
        arguments = {
            "mode": "auto",
            "workspace_root": root,
            "payload_root": payload,
            "manifest_path": manifest,
            "launch": False,
        }
        arguments.update(overrides)
        return deployer.deploy(**arguments)

    def test_clean_install_supports_an_arbitrarily_named_workspace(self):
        root = self.base / "Company Model Host"
        payload, manifest = _build_payload(self.base, "1.2.3", "clean")

        with self._runtime_patches():
            result = self._deploy(root, payload, manifest)

        self.assertEqual(result["mode"], "install")
        self.assertEqual(result["version"], "1.2.3")
        for name in deployer.WORKSPACE_DIRECTORIES:
            self.assertTrue((root / name).is_dir())
        for component in SERVER_COMPONENTS:
            self.assertTrue(
                (root / component.relative_destination / f"{component.app_name}.exe").is_file()
            )
        receipt = json.loads(
            (root / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["installed_version"], "1.2.3")
        self.assertEqual(Path(receipt["workspace_root"]), root.resolve())

    def test_empty_workspace_scaffolding_is_still_a_clean_install(self):
        root = self.base / "Precreated Empty Workspace"
        for name in deployer.WORKSPACE_DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)
        payload, manifest = _build_payload(self.base, "1.2.3", "clean-empty")

        with self._runtime_patches():
            result = self._deploy(root, payload, manifest)

        self.assertEqual(result["mode"], "install")

    def test_adopt_preserves_project_data_credentials_and_worker_preferences(self):
        root = self.base / "Existing Shared Workspace"
        project_file = root / "projects" / "Demo" / "keep.bin"
        project_file.parent.mkdir(parents=True)
        project_file.write_bytes(b"project-data")
        request_file = root / "requests" / "queued.json"
        request_file.parent.mkdir(parents=True)
        request_file.write_bytes(b'{"status":"queued"}\n')
        history_file = root / "runtime" / "history" / "completed.log"
        history_file.parent.mkdir(parents=True)
        history_file.write_bytes(b"keep-history\r\n")
        unrelated_app = root / "apps" / "Unrelated Tool" / "tool.bin"
        unrelated_app.parent.mkdir(parents=True)
        unrelated_app.write_bytes(b"not-owned")
        config_path = root / "config" / "config.json"
        config = default_server_config(root)
        config["resq"] = {"user_name": "service", "password": "secret"}
        config["apps"]["orchestrator"]["max_workers"] = 9
        # A server that already has its identity keeps it, so the file is untouched.
        config["server_id"] = "0b6f7c1e-2a4d-4f1b-9d3e-5c8a7b6e4f21"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            json.dumps(config, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        expected_bytes = {
            path: path.read_bytes()
            for path in (
                project_file,
                request_file,
                history_file,
                unrelated_app,
                config_path,
            )
        }
        payload, manifest = _build_payload(self.base, "2.0.0", "adopt")

        with self._runtime_patches():
            result = self._deploy(root, payload, manifest)

        self.assertEqual(result["mode"], "adopt")
        for path, expected in expected_bytes.items():
            self.assertEqual(path.read_bytes(), expected, path)
        config = read_server_config(config_path, root)
        self.assertEqual(config["resq"]["password"], "secret")
        self.assertEqual(config["apps"]["orchestrator"]["max_workers"], 9)
        self.assertIn("engine", config["apps"])

    def test_upgrade_and_repair_preserve_unrelated_apps(self):
        root = self.base / "Server"
        first_payload, first_manifest = _build_payload(self.base, "1.0.0", "old")
        second_payload, second_manifest = _build_payload(self.base, "1.1.0", "new")
        with self._runtime_patches():
            self._deploy(root, first_payload, first_manifest)
            custom = root / "apps" / "Custom Tool" / "keep.txt"
            custom.parent.mkdir()
            custom.write_text("unrelated", encoding="utf-8")
            upgraded = self._deploy(root, second_payload, second_manifest)
            engine = root / "apps" / "Arco Engine" / "Arco Engine.exe"
            engine.write_bytes(b"corrupt")
            repaired = self._deploy(root, second_payload, second_manifest)

        self.assertEqual(upgraded["mode"], "upgrade")
        self.assertEqual(repaired["mode"], "repair")
        self.assertIn(b"1.1.0:new:engine", engine.read_bytes())
        self.assertEqual(custom.read_text(encoding="utf-8"), "unrelated")

    def test_copied_workspace_with_a_foreign_receipt_is_adopted(self):
        original = self.base / "Original Server"
        copied = self.base / "Copied To New PC"
        payload, manifest = _build_payload(self.base, "1.0.0", "release")
        with self._runtime_patches():
            self._deploy(original, payload, manifest)
            original_receipt = json.loads(
                (original / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME).read_text(
                    encoding="utf-8"
                )
            )
            shutil.copytree(original, copied)
            result = self._deploy(copied, payload, manifest)

        copied_receipt = json.loads(
            (copied / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(result["mode"], "adopt")
        self.assertEqual(Path(copied_receipt["workspace_root"]), copied.resolve())
        self.assertNotEqual(
            copied_receipt["installation_id"], original_receipt["installation_id"]
        )

    def test_downgrade_and_corrupt_payload_are_rejected_before_replacement(self):
        root = self.base / "Server"
        new_payload, new_manifest = _build_payload(self.base, "3.0.0", "new")
        old_payload, old_manifest = _build_payload(self.base, "2.0.0", "old")
        corrupt_payload, corrupt_manifest = _build_payload(self.base, "3.1.0", "bad")
        with self._runtime_patches():
            self._deploy(root, new_payload, new_manifest)
            engine = root / "apps" / "Arco Engine" / "Arco Engine.exe"
            before = engine.read_bytes()
            with self.assertRaisesRegex(deployer.DeploymentError, "Downgrade blocked"):
                self._deploy(root, old_payload, old_manifest)
            (corrupt_payload / "apps" / "Arco Engine" / "Arco Engine.exe").write_bytes(
                b"tampered"
            )
            with self.assertRaisesRegex(deployer.DeploymentError, "checksum mismatch"):
                self._deploy(root, corrupt_payload, corrupt_manifest)
        self.assertEqual(engine.read_bytes(), before)

    def test_mid_swap_failure_restores_every_component_and_receipt(self):
        root = self.base / "Server"
        old_payload, old_manifest = _build_payload(self.base, "1.0.0", "old")
        new_payload, new_manifest = _build_payload(self.base, "2.0.0", "new")
        with self._runtime_patches():
            self._deploy(root, old_payload, old_manifest)
            receipt_path = root / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME
            config_path = root / "config" / "config.json"
            receipt_before = receipt_path.read_bytes()
            config_before = config_path.read_bytes()
            with self.assertRaisesRegex(OSError, "Injected deployment swap failure"):
                self._deploy(
                    root,
                    new_payload,
                    new_manifest,
                    fail_after_swap=2,
                )

        for component in SERVER_COMPONENTS:
            data = (
                root
                / component.relative_destination
                / f"{component.app_name}.exe"
            ).read_bytes()
            self.assertIn(f"1.0.0:old:{component.role}".encode(), data)
        self.assertEqual(receipt_path.read_bytes(), receipt_before)
        self.assertEqual(config_path.read_bytes(), config_before)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["installed_version"], "1.0.0")

    def test_staging_failure_leaves_live_components_and_configuration_unchanged(self):
        root = self.base / "Server"
        old_payload, old_manifest = _build_payload(self.base, "1.0.0", "old")
        new_payload, new_manifest = _build_payload(self.base, "2.0.0", "new")
        with self._runtime_patches():
            self._deploy(root, old_payload, old_manifest)
            engine = root / "apps" / "Arco Engine" / "Arco Engine.exe"
            config_path = root / "config" / "config.json"
            receipt_path = root / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME
            before = (engine.read_bytes(), config_path.read_bytes(), receipt_path.read_bytes())
            with patch.object(deployer.shutil, "copytree", side_effect=OSError("locked")):
                with self.assertRaisesRegex(OSError, "locked"):
                    self._deploy(root, new_payload, new_manifest)
        self.assertEqual(
            (engine.read_bytes(), config_path.read_bytes(), receipt_path.read_bytes()),
            before,
        )

    def test_startup_verification_failure_rolls_back_the_completed_swap(self):
        root = self.base / "Server"
        old_payload, old_manifest = _build_payload(self.base, "1.0.0", "old")
        new_payload, new_manifest = _build_payload(self.base, "2.0.0", "new")
        with self._runtime_patches():
            self._deploy(root, old_payload, old_manifest)
        with self._runtime_patches() as patches:
            patches.enter_context(
                patch.object(
                    deployer,
                    "_wait_for_startup",
                    side_effect=deployer.DeploymentError("heartbeat verification failed"),
                )
            )
            with self.assertRaisesRegex(deployer.DeploymentError, "heartbeat verification"):
                self._deploy(
                    root,
                    new_payload,
                    new_manifest,
                    launch=True,
                    verify_startup=True,
                )

        engine = root / "apps" / "Arco Engine" / "Arco Engine.exe"
        self.assertIn(b"1.0.0:old:engine", engine.read_bytes())
        receipt = json.loads(
            (root / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["installed_version"], "1.0.0")

    def test_uninstall_removes_owned_binaries_but_preserves_workspace_data(self):
        root = self.base / "Server"
        payload, manifest = _build_payload(self.base, "1.0.0", "installed")
        with self._runtime_patches():
            self._deploy(root, payload, manifest)
            project = root / "projects" / "Demo" / "data.bin"
            project.parent.mkdir(parents=True)
            project.write_bytes(b"keep")
            custom = root / "apps" / "Custom Tool" / "keep.txt"
            custom.parent.mkdir()
            custom.write_text("keep", encoding="utf-8")
            result = deployer.uninstall(workspace_root=root)

        self.assertTrue(result["ok"])
        self.assertEqual(project.read_bytes(), b"keep")
        self.assertEqual(custom.read_text(encoding="utf-8"), "keep")
        self.assertTrue((root / "config" / "config.json").is_file())
        for component in SERVER_COMPONENTS:
            self.assertFalse((root / component.relative_destination).exists())
        self.assertFalse(
            (root / INSTALL_METADATA_RELATIVE_DIR / RECEIPT_FILE_NAME).exists()
        )

    def test_workspace_validation_rejects_remote_relative_file_and_drive_root(self):
        file_path = self.base / "file.txt"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(deployer.DeploymentError):
            deployer.validate_workspace_root(r"\\server\share\ArcRho")
        with self.assertRaises(deployer.DeploymentError):
            deployer.validate_workspace_root("relative")
        with self.assertRaises(deployer.DeploymentError):
            deployer.validate_workspace_root(
                file_path, drive_type_resolver=lambda _: deployer.DRIVE_FIXED
            )
        with self.assertRaisesRegex(deployer.DeploymentError, "mapped/network"):
            deployer.validate_workspace_root(
                self.base / "remote", drive_type_resolver=lambda _: deployer.DRIVE_REMOTE
            )
        with self.assertRaisesRegex(deployer.DeploymentError, "drive root"):
            deployer.validate_workspace_root(
                Path(self.base.anchor), drive_type_resolver=lambda _: deployer.DRIVE_FIXED
            )
        with patch.object(
            deployer, "_probe_writable_directory", side_effect=deployer.DeploymentError("not writable")
        ):
            with self.assertRaisesRegex(deployer.DeploymentError, "not writable"):
                deployer.validate_workspace_root(
                    self.base / "blocked", drive_type_resolver=lambda _: deployer.DRIVE_FIXED
                )

    def test_shutdown_sets_and_restores_all_kill_switches(self):
        root = self.base / "Server"
        config_path = root / "config" / "config.json"
        write_server_config(config_path, default_server_config(root))
        with patch.object(deployer, "_request_admin_shutdown"), patch.object(
            deployer, "_wait_for_shutdown"
        ) as wait:
            previous = deployer._stop_components(root, config_path, timeout_seconds=7)
        wait.assert_called_once_with(root, 7)
        stopped = read_server_config(config_path, root)
        self.assertTrue(all(deployer._nested_get(stopped, key) for key in deployer.KILL_SWITCH_PATHS))
        deployer._restore_kill_switches(root, config_path, previous)
        restored = read_server_config(config_path, root)
        self.assertTrue(
            all(not deployer._nested_get(restored, key) for key in deployer.KILL_SWITCH_PATHS)
        )

    def test_server_config_keeps_the_canonical_persisted_json_text(self):
        # ``server_config`` imports the canonical text owner inside its writer
        # so the frozen Bridge never loads ``arcrho_api`` outside its staged
        # migration bundle. The written text must still be the canonical one.
        root = self.base / "Server"
        config_path = root / "config" / "config.json"
        payload = default_server_config(root)

        write_server_config(config_path, payload)

        self.assertEqual(
            config_path.read_text(encoding="utf-8"), persisted_json_text(payload)
        )

    def test_deployment_lock_rejects_a_concurrent_owner(self):
        root = self.base / "Server"
        root.mkdir()
        with deployer.deployment_lock(root):
            with self.assertRaises(deployer.DeploymentLockError):
                with deployer.deployment_lock(root):
                    self.fail("second deployment lock unexpectedly succeeded")

    def test_atomic_rename_retries_a_transient_windows_file_lock(self):
        source = self.base / "source"
        destination = self.base / "destination"
        source.mkdir()
        original_rename = Path.rename
        attempts = 0

        def flaky_rename(path, target):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError(13, "temporarily locked", str(path))
            return original_rename(path, target)

        with patch.object(Path, "rename", new=flaky_rename), patch.object(
            deployer.time, "sleep"
        ):
            deployer._rename_transaction_path(source, destination)
        self.assertEqual(attempts, 2)
        self.assertTrue(destination.is_dir())

    def test_transaction_folders_do_not_lengthen_live_component_paths(self):
        root = self.base / "Server"
        root.mkdir()
        for kind in ("s", "b", "u"):
            transaction = deployer._new_transaction_directory(root, kind)
            self.assertEqual(len(transaction.name), len("apps"))

    def test_overlong_payload_destination_is_rejected_before_copy(self):
        _payload, manifest_path = _build_payload(self.base, "1.0.0", "long-path")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["components"][0]["files"][0]["path"] = f"{'x' * 260}.dat"
        with self.assertRaisesRegex(deployer.DeploymentError, "too long"):
            deployer._validate_payload_destination_lengths(self.base, manifest)


class ServerContractTests(unittest.TestCase):
    def test_manifest_rejects_an_unexpected_product(self):
        with self.assertRaisesRegex(ValueError, "Unexpected payload product"):
            normalize_manifest(
                {
                    "schema_version": 1,
                    "product": "Not ArcRho",
                    "product_version": "1.0.0",
                    "components": [],
                }
            )

    def test_semver_comparison_blocks_prerelease_downgrades(self):
        self.assertGreater(compare_versions("2.0.0", "2.0.0-rc.1"), 0)
        self.assertLess(compare_versions("2.0.0-rc.1", "2.0.0"), 0)
        self.assertEqual(compare_versions("2.0.0+build.2", "2.0.0+build.1"), 0)

    def test_frozen_layout_infers_root_without_a_reserved_folder_name(self):
        fake_exe = Path(r"Q:\Selected By User\apps\Arco Engine\Arco Engine.exe")
        with patch.object(utils.sys, "frozen", True, create=True), patch.object(
            utils.sys, "executable", str(fake_exe)
        ), patch.dict(os.environ, {"ARCRHO_ROOT": ""}, clear=False):
            self.assertEqual(
                utils.find_project_root(Path(r"C:\irrelevant")),
                Path(r"Q:\Selected By User"),
            )

    def test_explicit_root_overrides_the_frozen_layout(self):
        fake_exe = Path(r"Q:\Selected By User\apps\Arco Engine\Arco Engine.exe")
        explicit = Path(r"R:\Operator Override")
        with patch.object(utils.sys, "frozen", True, create=True), patch.object(
            utils.sys, "executable", str(fake_exe)
        ), patch.dict(os.environ, {"ARCRHO_ROOT": str(explicit)}, clear=False):
            self.assertEqual(utils.find_project_root(Path(r"C:\irrelevant")), explicit)

    def test_component_entry_points_delegate_root_resolution_to_utils(self):
        for role in ("admin", "bridge", "engine", "launcher", "orchestrator"):
            source = (ENGINE_SRC / f"arcrho_{role}" / "main.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("get_project_root", source, role)
            self.assertNotIn('if "ARCRHO_ROOT" not in os.environ', source, role)

    def test_every_component_build_enforces_the_python_310_venv(self):
        self.assertEqual(build_runtime.REQUIRED_PYTHON, (3, 10))
        for role in ("admin", "bridge", "engine", "launcher", "orchestrator"):
            source = (ENGINE_SRC / f"arcrho_{role}" / "build_exe.py").read_text(
                encoding="utf-8"
            )
            self.assertIn("ensure_python_310_venv", source, role)


class CredentialHelperRoleTests(unittest.TestCase):
    """The helper a client runs to give its own PC a Gateway credential.

    It is deployed from the repository like the Gateway, so it is not part of
    the offline installer's payload; and nothing supervises it, so it must own
    no instance role or the Orchestrator would look for a heartbeat it never
    writes.
    """

    ROLE = "credential"

    def test_it_is_deployed_but_not_installed(self):
        self.assertIn(self.ROLE, utils.DEPLOYED_COMPONENT_ROLES)
        self.assertNotIn(self.ROLE, utils.SERVER_COMPONENT_ROLES)
        self.assertNotIn(self.ROLE, {item.role for item in SERVER_COMPONENTS})

    def test_it_owns_no_instance_role(self):
        import arcrho_build_components

        component = arcrho_build_components.component_by_key(self.ROLE)
        self.assertEqual(component.instance_roles, ())
        self.assertEqual(
            component.deploy_exe.name, f"{utils.component_app_name(self.ROLE)}.exe"
        )


if __name__ == "__main__":
    unittest.main()
