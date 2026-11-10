"""Build identity carried by a deployed folder, and the rollback it enables."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
if str(ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC))

import build_runtime  # noqa: E402
import deploy_rollback  # noqa: E402
from build_runtime import (  # noqa: E402
    DEPLOY_MANIFEST_SCHEMA_VERSION,
    bundle_version,
    deploy_manifest_path,
    deploy_slot_paths,
    describe_stamp,
    read_deploy_stamp,
    stage_deploy,
    swap_deploy,
    write_deploy_manifest,
)
from utils import DEPLOYED_COMPONENT_ROLES, component_app_name  # noqa: E402


APP_NAME = "ArcRho Test Component"


def _write_build(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _stamp(version: str, built_at: str, commit: str = "abc1234", dirty: bool = False) -> dict:
    return {
        "bundle_version": version,
        "built_at": built_at,
        "built_by": "tester@machine",
        "git_commit": commit,
        "git_dirty": dirty,
    }


class BundleVersionTests(unittest.TestCase):
    def test_the_bundle_version_is_the_desktop_app_version(self):
        """One version for the whole product; a server copy could disagree."""

        package = json.loads(
            (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
        )
        self.assertEqual(bundle_version(), str(package["version"]).strip())

    def test_the_installer_reads_that_same_file(self):
        source = (
            REPOSITORY_ROOT / "server-components" / "server-installer" / "build_release.py"
        ).read_text(encoding="utf-8")
        self.assertIn('FRONTEND_ROOT / "package.json"', source)
        self.assertEqual(
            build_runtime.PRODUCT_VERSION_PATH,
            REPOSITORY_ROOT / "frontend" / "package.json",
        )

    def test_a_missing_version_is_refused_rather_than_guessed(self):
        with tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT)) as temp:
            empty = Path(temp) / "package.json"
            empty.write_text(json.dumps({"name": "arcrho"}), encoding="utf-8")
            with patch.object(build_runtime, "PRODUCT_VERSION_PATH", empty):
                with self.assertRaises(RuntimeError):
                    bundle_version()


class BuildStampTests(unittest.TestCase):
    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.base = Path(self.temp.name)
        self.apps = self.base / "apps"
        self.dist = self.base / "dist"
        self.live, self.slot, _ = deploy_slot_paths(self.apps, APP_NAME)
        self.addCleanup(self.temp.cleanup)

    def _deploy(self, files: dict[str, str], stamp: dict) -> None:
        build_runtime.remove_tree_with_retry(self.dist / APP_NAME)
        staged = _write_build(self.dist / APP_NAME, files)
        with patch.object(build_runtime, "build_stamp", lambda: dict(stamp)):
            stage_deploy(staged, self.apps, APP_NAME)
            swap_deploy(self.apps, APP_NAME)

    def test_a_deploy_records_which_release_it_installed(self):
        self._deploy({"app.exe": "v1"}, _stamp("1.2.11", "2026-08-01T10:00:00+00:00"))

        stamp = read_deploy_stamp(self.live)
        self.assertEqual(stamp["bundle_version"], "1.2.11")
        self.assertEqual(stamp["built_at"], "2026-08-01T10:00:00+00:00")
        self.assertEqual(stamp["git_commit"], "abc1234")
        self.assertFalse(stamp["git_dirty"])
        self.assertEqual(stamp["app"], APP_NAME)

    def test_the_stamp_rotates_with_the_build_it_describes(self):
        """The parked folder must keep saying which release it is."""

        self._deploy({"app.exe": "v1"}, _stamp("1.2.11", "2026-08-01T10:00:00+00:00"))
        self._deploy({"app.exe": "v2"}, _stamp("1.2.12", "2026-08-16T21:00:00+00:00"))

        self.assertEqual(read_deploy_stamp(self.live)["bundle_version"], "1.2.12")
        self.assertEqual(read_deploy_stamp(self.slot)["bundle_version"], "1.2.11")

    def test_an_uncommitted_build_says_so(self):
        self._deploy(
            {"app.exe": "v1"},
            _stamp("1.2.12", "2026-08-16T21:00:00+00:00", dirty=True),
        )

        stamp = read_deploy_stamp(self.live)
        self.assertTrue(stamp["git_dirty"])
        self.assertIn("+edits", describe_stamp(stamp))

    def test_a_folder_deployed_before_stamping_reads_as_unstamped(self):
        staged = _write_build(self.dist / APP_NAME, {"app.exe": "v1"})
        self.live.mkdir(parents=True, exist_ok=True)
        legacy = {
            "schema_version": 1,
            "app": APP_NAME,
            "files": {"app.exe": {"size": 2, "mtime": 1.0, "sha256": "0" * 64}},
        }
        deploy_manifest_path(self.live).write_text(json.dumps(legacy), encoding="utf-8")

        stamp = read_deploy_stamp(self.live)
        self.assertEqual(stamp["bundle_version"], "")
        self.assertEqual(describe_stamp(stamp), "(unstamped build)")
        # A version 1 manifest predates the stamp but still names files, so it
        # must keep working as the delta base rather than force a full copy.
        self.assertEqual(
            build_runtime.align_staged_timestamps(
                staged, deploy_manifest_path(self.live)
            ),
            0,
        )

    def test_the_written_manifest_declares_the_current_schema(self):
        self._deploy({"app.exe": "v1"}, _stamp("1.2.12", "2026-08-16T21:00:00+00:00"))
        payload = json.loads(
            deploy_manifest_path(self.live).read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schema_version"], DEPLOY_MANIFEST_SCHEMA_VERSION)
        self.assertIn("files", payload)

    def test_a_real_deploy_stamps_the_repository_version(self):
        """The default path must stamp, not only an injected test stamp."""

        staged = _write_build(self.dist / APP_NAME, {"app.exe": "v1"})
        stage_deploy(staged, self.apps, APP_NAME)
        swap_deploy(self.apps, APP_NAME)

        self.assertEqual(
            read_deploy_stamp(self.live)["bundle_version"], bundle_version()
        )


class RollbackEligibilityTests(unittest.TestCase):
    def _row(self, live: dict | None, slot: dict | None) -> dict:
        return {"role": "engine", "app_name": "Arco Engine", "live": live, "slot": slot}

    def test_a_parked_previous_build_can_be_rolled_back(self):
        row = self._row(
            _stamp("1.2.12", "2026-08-16T21:00:00+00:00"),
            _stamp("1.2.11", "2026-08-01T10:00:00+00:00"),
        )
        self.assertIsNone(deploy_rollback.rollback_blocker(row))

    def test_without_a_slot_there_is_nothing_to_restore(self):
        row = self._row(_stamp("1.2.12", "2026-08-16T21:00:00+00:00"), None)
        self.assertEqual(
            deploy_rollback.rollback_blocker(row), "no parked previous build"
        )

    def test_a_slot_holding_the_live_build_is_refused(self):
        """The Launcher's in-place fallback leaves the slot equal to live."""

        stamp = _stamp("1.2.12", "2026-08-16T21:00:00+00:00")
        row = self._row(dict(stamp), dict(stamp))
        self.assertEqual(
            deploy_rollback.rollback_blocker(row),
            "the parked build is the one already deployed",
        )

    def test_two_unstamped_builds_are_still_offered(self):
        """Folders deployed before stamping are indistinguishable, not identical."""

        unstamped = {"bundle_version": "", "built_at": "", "git_commit": ""}
        row = self._row(dict(unstamped), dict(unstamped))
        self.assertIsNone(deploy_rollback.rollback_blocker(row))


class RollbackRotationTests(unittest.TestCase):
    """Admin Control deploys without a stopped window, so it rolls back without one."""

    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.base = Path(self.temp.name)
        self.apps = self.base / "apps"
        self.dist = self.base / "dist"
        self.app_name = component_app_name("admin")
        self.live, self.slot, _ = deploy_slot_paths(self.apps, self.app_name)
        self.addCleanup(self.temp.cleanup)

    def _deploy(self, files: dict[str, str], stamp: dict) -> None:
        build_runtime.remove_tree_with_retry(self.dist / self.app_name)
        staged = _write_build(self.dist / self.app_name, files)
        with patch.object(build_runtime, "build_stamp", lambda: dict(stamp)):
            stage_deploy(staged, self.apps, self.app_name)
            swap_deploy(self.apps, self.app_name)

    def test_rollback_restores_the_parked_build_and_parks_the_current_one(self):
        self._deploy({"app.exe": "v1"}, _stamp("1.2.11", "2026-08-01T10:00:00+00:00"))
        self._deploy({"app.exe": "v2"}, _stamp("1.2.12", "2026-08-16T21:00:00+00:00"))

        restored = deploy_rollback.rollback(self.apps, "admin")

        self.assertEqual((self.live / "app.exe").read_text(encoding="utf-8"), "v1")
        self.assertEqual((self.slot / "app.exe").read_text(encoding="utf-8"), "v2")
        self.assertEqual(restored["live"]["bundle_version"], "1.2.11")
        # The build that was rolled back is now the rollback target, so the
        # rotation is reversible rather than a one-way escape hatch.
        self.assertEqual(restored["slot"]["bundle_version"], "1.2.12")

    def test_rollback_refuses_when_there_is_no_parked_build(self):
        self._deploy({"app.exe": "v1"}, _stamp("1.2.12", "2026-08-16T21:00:00+00:00"))
        with self.assertRaises(RuntimeError):
            deploy_rollback.rollback(self.apps, "admin")


class StatusReportTests(unittest.TestCase):
    def _rows(self, versions: dict[str, str]) -> list[dict]:
        return [
            {
                "role": role,
                "app_name": component_app_name(role),
                "live": _stamp(version, "2026-08-16T21:00:00+00:00"),
                "slot": None,
            }
            for role, version in versions.items()
        ]

    def test_a_split_bundle_is_called_out(self):
        report = deploy_rollback.render_status(
            self._rows({"engine": "1.2.12", "gateway": "1.2.11"}), "1.2.12"
        )
        self.assertIn("Components disagree on the bundle version: 1.2.11, 1.2.12", report)

    def test_a_server_behind_the_repository_is_called_out(self):
        report = deploy_rollback.render_status(
            self._rows({"engine": "1.2.11", "gateway": "1.2.11"}), "1.2.12"
        )
        self.assertIn("The server runs 1.2.11 while the repository is at 1.2.12", report)

    def test_a_matching_bundle_reports_no_discrepancy(self):
        report = deploy_rollback.render_status(
            self._rows({"engine": "1.2.12", "gateway": "1.2.12"}), "1.2.12"
        )
        self.assertNotIn("disagree", report)
        self.assertNotIn("while the repository", report)

    def test_unstamped_components_are_named(self):
        rows = self._rows({"engine": "1.2.12"})
        rows[0]["live"]["bundle_version"] = ""
        self.assertIn("unknown: engine", deploy_rollback.render_status(rows, "1.2.12"))


class StoppedWindowDelegationTests(unittest.TestCase):
    """Rollback must reuse each component's deploy-time stop, never restate it."""

    def test_every_named_stop_context_exists_in_its_build_script(self):
        for role, context_name in deploy_rollback.STOP_CONTEXT_BY_ROLE.items():
            source = (ENGINE_SRC / f"arcrho_{role}" / "build_exe.py").read_text(
                encoding="utf-8"
            )
            with self.subTest(role=role):
                self.assertIn(f"def {context_name}(", source)

    def test_roles_without_a_stop_context_deploy_without_one(self):
        for role in DEPLOYED_COMPONENT_ROLES:
            if role in deploy_rollback.STOP_CONTEXT_BY_ROLE:
                continue
            source = (ENGINE_SRC / f"arcrho_{role}" / "build_exe.py").read_text(
                encoding="utf-8"
            )
            with self.subTest(role=role):
                self.assertNotIn("@contextmanager", source)

    def test_the_rollback_inventory_is_the_deployed_component_set(self):
        self.assertEqual(
            tuple(row["role"] for row in deploy_rollback.deployment_rows(Path("apps"))),
            DEPLOYED_COMPONENT_ROLES,
        )


if __name__ == "__main__":
    unittest.main()
