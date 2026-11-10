"""The tool that keeps a private Arco Server root on this PC for testing.

What matters is that it can never reach production: it refuses a shared or
production root, binds the local Gateway to this PC only, keeps its credential
in a file of its own, and hands every build and child process the local root
rather than whatever the calling shell inherited.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
MODULE_PATH = REPO_ROOT / "tools" / "local_server.py"
SPEC = importlib.util.spec_from_file_location("local_server", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
local_server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = local_server
SPEC.loader.exec_module(local_server)

from arcrho_dependent_propagation_contract import (  # noqa: E402  (on sys.path once the tool loads)
    acquire_reserving_class_lease,
    release_reserving_class_lease,
)


class LocalServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        base = Path(self.temp.name)
        self.root = base / "Arco Server"
        self.production = base / "production"
        (self.production / "config").mkdir(parents=True)
        (self.production / "config" / "username_index.json").write_text("{}", encoding="utf-8")
        orchestrator = self.production / "apps" / "ArcRho Orchestrator"
        orchestrator.mkdir(parents=True)
        (orchestrator / "ArcRho Orchestrator.exe").write_bytes(b"exe")
        self.credential = base / "appdata" / "arcrho_gateway.local.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _init(self) -> list[str]:
        return local_server.init_root(
            self.root,
            production_root=self.production,
            credential_path=self.credential,
            user="tester",
        )

    def test_a_shared_or_production_root_is_refused(self) -> None:
        with self.assertRaisesRegex(local_server.LocalServerError, "fixed disk of this PC"):
            local_server.require_local_root(Path(r"\\server\share\Arco Server"), self.production)
        with self.assertRaisesRegex(local_server.LocalServerError, "production server"):
            local_server.require_local_root(self.production, self.production)
        self.assertEqual(
            local_server.require_local_root(self.root, self.production),
            self.root.resolve(),
        )

    def test_init_builds_a_root_that_serves_this_pc_only(self) -> None:
        self._init()
        for folder in local_server.ROOT_FOLDERS:
            self.assertTrue((self.root / folder).is_dir(), folder)
        apps = json.loads((self.root / "config" / "config.json").read_text(encoding="utf-8"))["apps"]
        self.assertFalse(apps["bridge"]["auto_create_instance"])
        self.assertTrue(apps["bridge"]["kill_all"])
        registry = json.loads((self.root / "config" / "arcrho_gateway.json").read_text(encoding="utf-8"))
        self.assertEqual(registry["host"], "127.0.0.1")
        self.assertEqual(registry["client_url"], "http://127.0.0.1:28767")
        credential = json.loads(self.credential.read_text(encoding="utf-8"))
        self.assertEqual(credential["url"], "http://127.0.0.1:28767")
        self.assertEqual(registry["users"]["tester"], credential["secret"])
        self.assertTrue((self.root / "config" / "username_index.json").is_file())
        self.assertTrue((self.root / "apps" / "ArcRho Orchestrator" / "ArcRho Orchestrator.exe").is_file())

    def test_init_again_keeps_the_same_credential(self) -> None:
        self._init()
        first = json.loads(self.credential.read_text(encoding="utf-8"))["secret"]
        self._init()
        self.assertEqual(json.loads(self.credential.read_text(encoding="utf-8"))["secret"], first)

    def test_copy_project_skips_locks_and_refuses_to_overwrite_silently(self) -> None:
        project = self.production / "projects" / "Fake"
        (project / "data").mkdir(parents=True)
        (project / "data" / "index.json").write_text("{}", encoding="utf-8")
        (project / "data" / ".index.json.lock").write_text("", encoding="utf-8")
        (project / ".tmp_write").write_text("", encoding="utf-8")
        (project / "data" / ".arcrho-resq-import-staging" / "abc").mkdir(parents=True)
        (project / "data" / "tmp").mkdir()
        (project / "data" / "Class" / "sidecars").mkdir(parents=True)
        (project / "data" / "Class" / "sidecars" / "x.json.bak").write_text("{}", encoding="utf-8")
        (project / "dataset_types.json").write_text("{}", encoding="utf-8")
        (project / "dataset_types.json.before-severity-formulas-20260830.bak").write_text("{}", encoding="utf-8")
        (project / "data_processing_rules.before_phase2_20260717.json").write_text("{}", encoding="utf-8")
        target = local_server.copy_project(self.root, production_root=self.production, name="Fake", overwrite=False)
        self.assertTrue((target / "data" / "index.json").is_file())
        self.assertFalse((target / "data" / ".index.json.lock").exists())
        self.assertFalse((target / ".tmp_write").exists())
        # The leftovers the contract scan reports stay behind; only root backups are dropped.
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["data", "dataset_types.json"])
        self.assertEqual(sorted(path.name for path in (target / "data").iterdir()), ["Class", "index.json"])
        self.assertTrue((target / "data" / "Class" / "sidecars" / "x.json.bak").is_file())
        with self.assertRaisesRegex(local_server.LocalServerError, "--overwrite"):
            local_server.copy_project(self.root, production_root=self.production, name="Fake", overwrite=False)

    def _publishable(self) -> Path:
        local = self.root / "projects" / "Fake"
        (local / "data").mkdir(parents=True)
        (local / "source").mkdir()
        local_source = self.root / "sources" / "new.csv"
        mapping = {"project_name": "Fake", "table_path": str(local_source)}
        (local / "field_mapping.json").write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        record = {"last_import": {"csv_path": str(local_source), "source_label": str(local_source), "csv_size": 1}}
        (local / "source" / "source_import.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        values = {"path": str(local / "source" / "master_table.csv").lower()}
        (local / "data_processing_values.json").write_text(json.dumps(values), encoding="utf-8")
        (local / "data" / ".index.json.lock").write_text("", encoding="utf-8")
        old = self.production / "projects" / "Fake"
        old.mkdir(parents=True)
        (old / "old.txt").write_text("old", encoding="utf-8")
        shared = self.production / "shared.csv"
        shared.write_text("a,b\n", encoding="utf-8")
        return shared

    def test_publish_keeps_a_backup_and_points_paths_at_production(self) -> None:
        shared = self._publishable()
        target, backup = local_server.publish_project(
            self.root, production_root=self.production, name="Fake", source=shared, today="20261106"
        )
        self.assertEqual(backup.name, "Fake.before_refresh_20261106")
        self.assertTrue((backup / "old.txt").is_file())
        self.assertFalse((target / "old.txt").exists())
        self.assertFalse((target / "data" / ".index.json.lock").exists())
        mapping = json.loads((target / "field_mapping.json").read_text(encoding="utf-8"))
        self.assertEqual(mapping["table_path"], str(shared))
        last = json.loads((target / "source" / "source_import.json").read_text(encoding="utf-8"))["last_import"]
        self.assertEqual((last["csv_path"], last["source_label"]), (str(shared), str(shared)))
        self.assertEqual(last["csv_size"], shared.stat().st_size)
        values = json.loads((target / "data_processing_values.json").read_text(encoding="utf-8"))
        self.assertEqual(values["path"], str(target / "source" / "master_table.csv").lower())

    def test_publish_refuses_while_production_is_busy(self) -> None:
        shared = self._publishable()
        old = self.production / "projects" / "Fake"
        lease = acquire_reserving_class_lease(self.production, "Fake", "A\\B")
        self.assertIsNotNone(lease)
        try:
            with self.assertRaisesRegex(local_server.LocalServerError, "busy: a dependent walk is processing for A"):
                local_server.publish_project(self.root, production_root=self.production, name="Fake", source=shared)
        finally:
            release_reserving_class_lease(lease)
        pending = local_server.project_dates_pending_path(self.production, "Fake")
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(local_server.LocalServerError, "project dates change"):
            local_server.publish_project(self.root, production_root=self.production, name="Fake", source=shared)
        # Nothing moved: production's copy is where it was and no backup exists.
        self.assertTrue((old / "old.txt").is_file())
        self.assertEqual([path.name for path in (self.production / "projects").iterdir()], ["Fake"])

    def test_builds_get_the_local_root_and_none_of_the_inherited_overrides(self) -> None:
        inherited = {"ARCRHO_SERVER_ROOT": r"E:\Arco Server", "ARCRHO_RUNTIME_SERVER_ROOT": r"E:\Arco Server"}
        with patch.dict(local_server.os.environ, inherited), patch.object(local_server.subprocess, "run") as run:
            run.return_value.returncode = 0
            local_server.deploy(self.root, ["engine"])
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["ARCRHO_DEPLOY_ROOT"], str(self.root))
        self.assertEqual(env["ARCRHO_ROOT"], str(self.root))
        self.assertNotIn("ARCRHO_SERVER_ROOT", env)
        self.assertNotIn("ARCRHO_RUNTIME_SERVER_ROOT", env)

    def test_start_and_stop_act_through_the_shared_server_control(self) -> None:
        with patch.object(local_server, "start_server", return_value=True) as start, \
                patch.object(local_server, "stop_server", return_value=True) as stop:
            for command in ("start", "stop"):
                self.assertEqual(
                    local_server.main(["--root", str(self.root), "--production-root", str(self.production), command]), 0
                )
        self.assertEqual(start.call_args.args[0], self.root.resolve())
        self.assertEqual(stop.call_args.args, (self.root.resolve(), local_server.STOP_WAIT_SECONDS))

    def test_launch_app_names_the_local_credential_and_address(self) -> None:
        credential = self.production / "credential.json"
        credential.write_text("{}", encoding="utf-8")
        with patch.object(local_server, "gateway_health", return_value={"ok": True}),                 patch.object(local_server.subprocess, "run") as run:
            local_server.launch_app(self.root, credential)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["ARCRHO_GATEWAY_CONFIG"], str(credential))
        self.assertEqual(env["ARCRHO_GATEWAY_URL"], local_server.LOCAL_GATEWAY_URL)

    def test_deploy_with_no_components_builds_engine_and_gateway(self) -> None:
        with patch.object(local_server, "deploy") as deploy:
            local_server.main(["--root", str(self.root), "--production-root", str(self.production), "deploy"])
        self.assertEqual(deploy.call_args.args[1], ["engine", "gateway"])


if __name__ == "__main__":
    unittest.main()
