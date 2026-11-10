from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_project_duplication_contract import (  # noqa: E402
    PROJECT_DUPLICATION_CONTRACT_VERSION,
    ProjectDuplicationContractError,
    build_project_duplication_request,
    build_project_duplication_status,
    encode_project_directory_segment,
    project_duplication_lock_directory,
    project_duplication_projects_path,
    project_duplication_request_path,
    project_duplication_status_path,
    validate_project_duplication_status,
    write_json_atomic,
)
from arcrho_engine import project_duplication  # noqa: E402


class ProjectDuplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.server_root = Path(self.temp_dir.name) / "Arco Server"
        self.projects_dir = self.server_root / "projects"
        self.projects_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _request(
        self,
        *,
        request_id: str = "job-123",
        source: str = "Source",
        target: str = "Target",
        projects_directory: str = "projects",
    ) -> dict:
        return build_project_duplication_request(
            request_id=request_id,
            source_project_name=source,
            target_project_name=target,
            projects_directory=projects_directory,
            user_name="tester",
        )

    def _create_source(
        self,
        name: str = "Source",
        *,
        projects_dir: Path | None = None,
    ) -> Path:
        source = (projects_dir or self.projects_dir) / encode_project_directory_segment(
            name
        )
        (source / "source").mkdir(parents=True)
        (source / "source" / "master_table.csv").write_text(
            "AccidentYear,Paid\n2025,10\n", encoding="utf-8"
        )
        (source / "general_settings.json").write_text(
            '{"project_name":"Source"}\n', encoding="utf-8"
        )
        data = source / "data"
        (data / "RC B" / "datasets").mkdir(parents=True)
        (data / "RC B" / "datasets" / "paid.csv").write_text(
            "1,2\n", encoding="utf-8"
        )
        (data / "RC A" / "sidecars").mkdir(parents=True)
        (data / "RC A" / "sidecars" / "paid.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (data / "index.json").write_text('{"version":1}\n', encoding="utf-8")
        (data / "tmp").mkdir()
        (data / "tmp" / "ignored.txt").write_text("tmp", encoding="utf-8")
        (data / ".arcrho-resq-import-staging").mkdir()
        (data / ".arcrho-resq-import-staging" / "ignored.txt").write_text(
            "staged", encoding="utf-8"
        )
        return source

    def _queue_request(self, request: dict) -> Path:
        path = project_duplication_request_path(
            self.server_root,
            request["RequestId"],
        )
        write_json_atomic(path, request)
        return path

    def _interrupt_after_verified_staging(self, request: dict) -> Path:
        with (
            patch.object(
                project_duplication.os,
                "rename",
                side_effect=SystemExit("simulated worker crash"),
            ),
            patch.object(project_duplication.shutil, "rmtree"),
        ):
            with self.assertRaises(SystemExit):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )
        staging = project_duplication._staging_path(
            self.projects_dir,
            encode_project_directory_segment(request["TargetProjectName"]),
            request["RequestId"],
        )
        self.assertTrue(staging.is_dir())
        return staging

    def _symlink_or_skip(
        self,
        target: Path,
        link: Path,
        *,
        target_is_directory: bool,
    ) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"Filesystem symlinks are unavailable: {exc}")

    def test_canonical_request_paths_and_status_are_exact_and_path_free(self):
        request = self._request(source="Source/Book", target="Target:Copy")

        self.assertEqual(request["ContractVersion"], PROJECT_DUPLICATION_CONTRACT_VERSION)
        self.assertEqual(
            encode_project_directory_segment(request["SourceProjectName"]),
            "Source_%2F_Book",
        )
        self.assertEqual(
            project_duplication_request_path(self.server_root, "job-123"),
            self.server_root / "requests" / "job-123.json",
        )
        self.assertEqual(
            project_duplication_projects_path(self.server_root),
            self.server_root / "projects",
        )
        self.assertEqual(
            project_duplication_projects_path(
                self.server_root,
                r"project-store\active",
            ),
            self.server_root / "project-store" / "active",
        )
        self.assertEqual(
            project_duplication_lock_directory(self.server_root),
            self.server_root / "requests" / "project_duplication" / "locks",
        )
        self.assertEqual(
            project_duplication_status_path(self.server_root, "job-123"),
            self.server_root
            / "requests"
            / "project_duplication"
            / "status"
            / "job-123.json",
        )

        forbidden = dict(request, StatusPath=r"X:\client\status.json")
        with self.assertRaisesRegex(
            ProjectDuplicationContractError, "Filesystem paths must not be supplied"
        ):
            build_project_duplication_status(
                forbidden,
                "queued",
                progress={
                    "stage": "queued",
                    "completed": 0,
                    "total": 0,
                    "label": "Queued for ArcRho Engine",
                },
            )

        for unsafe_projects_directory in (
            r"C:\outside",
            r"\\server\share",
            "../outside",
            "project-store/../outside",
        ):
            with self.subTest(projects_directory=unsafe_projects_directory):
                with self.assertRaises(ProjectDuplicationContractError):
                    self._request(projects_directory=unsafe_projects_directory)

        status = build_project_duplication_status(
            request,
            "queued",
            progress={
                "stage": "queued",
                "completed": 0,
                "total": 0,
                "label": "Queued for ArcRho Engine",
            },
            updated_at="2026-08-01T12:00:00+00:00",
        )
        self.assertEqual(
            status,
            {
                "contract_version": 1,
                "status": "queued",
                "updated_at": "2026-08-01T12:00:00+00:00",
                "request_id": "job-123",
                "progress": {
                    "stage": "queued",
                    "completed": 0,
                    "total": 0,
                    "label": "Queued for ArcRho Engine",
                },
            },
        )
        self.assertEqual(
            validate_project_duplication_status(
                status, expected_request_id="job-123"
            ),
            status,
        )

        status_path = project_duplication_status_path(self.server_root, "job-123")
        write_json_atomic(status_path, status)
        self.assertEqual(json.loads(status_path.read_text(encoding="utf-8")), status)
        self.assertEqual(list(status_path.parent.glob("*.tmp")), [])

    def test_atomic_status_publication_retries_a_transient_share_lock(self):
        status_path = project_duplication_status_path(
            self.server_root,
            "job-retry",
        )
        payload = {"status": "queued"}
        canonical_replace = os.replace
        attempts = []

        def replace_after_two_locks(source, target):
            attempts.append((source, target))
            if len(attempts) < 3:
                raise PermissionError("status reader still closing")
            canonical_replace(source, target)

        with (
            patch(
                "arcrho_project_duplication_contract.os.replace",
                side_effect=replace_after_two_locks,
            ),
            patch("arcrho_project_duplication_contract.time.sleep"),
        ):
            write_json_atomic(status_path, payload)

        self.assertEqual(len(attempts), 3)
        self.assertEqual(
            json.loads(status_path.read_text(encoding="utf-8")),
            payload,
        )

    def test_duplicate_copies_actual_rc_units_in_order_and_excludes_transients(self):
        source = self._create_source()
        request = self._request(target="Target/Copy")
        progress = []

        total = project_duplication.duplicate_project(
            self.server_root,
            request,
            progress_callback=progress.append,
        )

        target = self.projects_dir / "Target_%2F_Copy"
        self.assertEqual(total, 2)
        self.assertTrue(source.is_dir())
        self.assertEqual(
            (target / "source" / "master_table.csv").read_text(encoding="utf-8"),
            "AccidentYear,Paid\n2025,10\n",
        )
        self.assertTrue((target / "data" / "index.json").is_file())
        self.assertTrue((target / "data" / "RC A" / "sidecars" / "paid.json").is_file())
        self.assertTrue((target / "data" / "RC B" / "datasets" / "paid.csv").is_file())
        self.assertFalse((target / "data" / "tmp").exists())
        self.assertFalse((target / "data" / ".arcrho-resq-import-staging").exists())

        rc_progress = [
            item for item in progress if item["stage"] == "reserving_classes"
        ]
        self.assertEqual(
            [(item["completed"], item["total"]) for item in rc_progress],
            [(0, 2), (1, 2), (2, 2)],
        )
        self.assertEqual(progress[-1]["stage"], "finalizing")
        self.assertEqual(
            (progress[-1]["completed"], progress[-1]["total"]),
            (0, 0),
        )
        self.assertEqual(list(self.projects_dir.glob(".arcrho-project-duplication-*")), [])
        lock_dir = self.server_root / "requests" / "project_duplication" / "locks"
        self.assertEqual(list(lock_dir.glob("*.lock")), [])

    def test_existing_target_is_never_modified(self):
        self._create_source()
        target = self.projects_dir / "Target"
        target.mkdir()
        marker = target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(
            project_duplication.ProjectDuplicationError,
            "target project folder already exists",
        ):
            project_duplication.duplicate_project(
                self.server_root,
                self._request(),
                progress_callback=lambda _event: None,
            )

        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_mocked_source_reparse_entry_cannot_publish_target(self):
        source = self._create_source()
        request = self._request(request_id="job-mocked-reparse")
        source_manifest = project_duplication._source_manifest

        class ReparseEntry:
            name = "escape"

            @staticmethod
            def is_symlink():
                return False

            @staticmethod
            def stat(*, follow_symlinks):
                self.assertFalse(follow_symlinks)

                class ReparseMetadata:
                    st_file_attributes = (
                        project_duplication.stat_module.FILE_ATTRIBUTE_REPARSE_POINT
                    )

                return ReparseMetadata()

        class ReparseScan:
            def __enter__(self):
                return iter((ReparseEntry(),))

            def __exit__(self, *_args):
                return False

        def manifest_with_reparse(path, *, include_transient=False):
            if Path(path) == source:
                with patch.object(
                    project_duplication.os,
                    "scandir",
                    return_value=ReparseScan(),
                ):
                    return source_manifest(
                        path,
                        include_transient=include_transient,
                    )
            return source_manifest(path, include_transient=include_transient)

        with patch.object(
            project_duplication,
            "_source_manifest",
            side_effect=manifest_with_reparse,
        ):
            with self.assertRaisesRegex(
                project_duplication.ProjectDuplicationError,
                "unsupported symbolic link",
            ):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )

        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(
            list(self.projects_dir.glob(".arcrho-project-duplication-*")),
            [],
        )

    def test_source_tree_symlink_cannot_publish_target_when_supported(self):
        source = self._create_source()
        outside = Path(self.temp_dir.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        self._symlink_or_skip(
            outside,
            source / "escape.txt",
            target_is_directory=False,
        )

        with self.assertRaisesRegex(
            project_duplication.ProjectDuplicationError,
            "unsupported symbolic link",
        ):
            project_duplication.duplicate_project(
                self.server_root,
                self._request(request_id="job-source-symlink"),
                progress_callback=lambda _event: None,
            )

        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(
            list(self.projects_dir.glob(".arcrho-project-duplication-*")),
            [],
        )

    def test_mocked_symlink_request_is_rejected_and_preserved(self):
        self._create_source()
        request = self._request(request_id="job-mocked-request-link")
        request_path = self._queue_request(request)
        path_is_symlink = Path.is_symlink

        def mark_request_as_symlink(path):
            if path == request_path:
                return True
            return path_is_symlink(path)

        with patch.object(Path, "is_symlink", new=mark_request_as_symlink):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        self.assertTrue(request_path.is_file())
        self.assertFalse((self.projects_dir / "Target").exists())

    def test_symlink_request_is_rejected_and_preserved_when_supported(self):
        self._create_source()
        request = self._request(request_id="job-request-link")
        request_path = project_duplication_request_path(
            self.server_root,
            request["RequestId"],
        )
        payload_path = Path(self.temp_dir.name) / "request-payload.json"
        write_json_atomic(payload_path, request)
        request_path.parent.mkdir(parents=True, exist_ok=True)
        self._symlink_or_skip(
            payload_path,
            request_path,
            target_is_directory=False,
        )

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        self.assertTrue(request_path.is_symlink())
        self.assertTrue(payload_path.is_file())
        self.assertFalse((self.projects_dir / "Target").exists())

    def test_mocked_symlink_protocol_root_is_rejected_without_claim(self):
        request = self._request(request_id="job-mocked-protocol-link")
        request_path = self._queue_request(request)
        protocol_root = project_duplication_lock_directory(self.server_root).parent
        path_is_symlink = Path.is_symlink

        def mark_protocol_as_symlink(path):
            if path == protocol_root:
                return True
            return path_is_symlink(path)

        with patch.object(Path, "is_symlink", new=mark_protocol_as_symlink):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        self.assertTrue(request_path.is_file())
        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertFalse((protocol_root / "claims").exists())

    def test_symlink_protocol_root_is_rejected_without_escape_when_supported(self):
        request = self._request(request_id="job-protocol-link")
        requests_dir = self.server_root / "requests"
        requests_dir.mkdir()
        outside_protocol = Path(self.temp_dir.name) / "outside-protocol"
        outside_protocol.mkdir()
        protocol_root = requests_dir / "project_duplication"
        self._symlink_or_skip(
            outside_protocol,
            protocol_root,
            target_is_directory=True,
        )
        request_path = self._queue_request(request)

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        self.assertTrue(request_path.is_file())
        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(list(outside_protocol.iterdir()), [])

    def test_mocked_intermediate_project_store_reparse_is_rejected(self):
        custom_projects = self.server_root / "project-store" / "link" / "active"
        custom_projects.mkdir(parents=True)
        self._create_source(projects_dir=custom_projects)
        request = self._request(
            request_id="job-mocked-project-store-link",
            projects_directory="project-store/link/active",
        )
        linked_segment = self.server_root / "project-store" / "link"
        inspect_path = project_duplication._path_is_link_or_reparse

        def mark_intermediate_as_reparse(path):
            if path == linked_segment:
                return True
            return inspect_path(path)

        with patch.object(
            project_duplication,
            "_path_is_link_or_reparse",
            side_effect=mark_intermediate_as_reparse,
        ):
            with self.assertRaisesRegex(
                project_duplication.ProjectDuplicationError,
                "contains a symbolic link or reparse point",
            ):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )

        self.assertFalse((custom_projects / "Target").exists())

    def test_intermediate_project_store_symlink_is_rejected_when_supported(self):
        project_store = self.server_root / "project-store"
        project_store.mkdir()
        outside_store = Path(self.temp_dir.name) / "outside-project-store"
        custom_projects = outside_store / "active"
        custom_projects.mkdir(parents=True)
        self._create_source(projects_dir=custom_projects)
        self._symlink_or_skip(
            outside_store,
            project_store / "link",
            target_is_directory=True,
        )
        request = self._request(
            request_id="job-project-store-link",
            projects_directory="project-store/link/active",
        )

        with self.assertRaisesRegex(
            project_duplication.ProjectDuplicationError,
            "contains a symbolic link or reparse point",
        ):
            project_duplication.duplicate_project(
                self.server_root,
                request,
                progress_callback=lambda _event: None,
            )

        self.assertFalse((custom_projects / "Target").exists())

    def test_partial_copy_and_source_change_remove_staging_without_target(self):
        self._create_source()
        request = self._request()
        real_copytree = project_duplication.shutil.copytree

        def fail_after_staging(source, target, *args, **kwargs):
            Path(target).mkdir(parents=True)
            (Path(target) / "partial.txt").write_text("partial", encoding="utf-8")
            raise OSError("copy interrupted")

        with patch.object(
            project_duplication.shutil, "copytree", side_effect=fail_after_staging
        ):
            with self.assertRaises(OSError):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )
        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(list(self.projects_dir.glob(".arcrho-project-duplication-*")), [])

        with (
            patch.object(project_duplication.shutil, "copytree", real_copytree),
            patch.object(
                project_duplication,
                "_source_manifest",
                side_effect=("before", "after", "before"),
            ),
        ):
            with self.assertRaisesRegex(
                project_duplication.ProjectDuplicationError,
                "source project changed",
            ):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )
        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(list(self.projects_dir.glob(".arcrho-project-duplication-*")), [])

    def test_open_project_bookkeeping_during_the_copy_still_publishes(self):
        """Preferences, caches and indexes the app rewrites must not fail a copy."""

        source = self._create_source()
        prefs = source / "users" / "tester" / "preferences.json"
        prefs.parent.mkdir(parents=True)
        prefs.write_text('{"zoom":1}\n', encoding="utf-8")
        (source / "table_summary.json").write_text("{}\n", encoding="utf-8")
        (source / "data" / "RC A" / "index.json").write_text("{}\n", encoding="utf-8")
        (source / "data" / "RC A" / ".index.json.lock").write_bytes(b"\0")
        (source / "data" / "RC A" / "sidecars" / "old.json.abc.tmp").write_text(
            "", encoding="utf-8"
        )
        request = self._request()

        def touch_bookkeeping(event):
            if event["stage"] != "reserving_classes" or event["completed"] != 1:
                return
            prefs.write_text('{"zoom":2}\n', encoding="utf-8")
            (source / "users" / "other" / "reviews").mkdir(parents=True)
            (source / "users" / "other" / "reviews" / "side.xlsx").write_bytes(b"x")
            (source / "table_summary.json").write_text('{"v":2}\n', encoding="utf-8")
            (source / "reserving_class_combinations_cache.json").write_text(
                "{}\n", encoding="utf-8"
            )
            (source / "data" / "RC A" / "index.json").write_text(
                '{"rebuilt":true}\n', encoding="utf-8"
            )
            (source / "data" / "RC B" / ".index.json.lock").write_bytes(b"\0")
            (source / ".arcrho-visibility-probe-1.tmp").write_text("", encoding="utf-8")

        project_duplication.duplicate_project(
            self.server_root,
            request,
            progress_callback=touch_bookkeeping,
        )

        target = self.projects_dir / "Target"
        self.assertTrue((target / "users" / "tester" / "preferences.json").is_file())
        self.assertTrue((target / "data" / "RC A" / "index.json").is_file())
        self.assertFalse((target / "data" / "RC A" / ".index.json.lock").exists())
        self.assertFalse(
            (target / "data" / "RC A" / "sidecars" / "old.json.abc.tmp").exists()
        )
        self.assertFalse((target / ".arcrho-visibility-probe-1.tmp").exists())

    def test_data_change_during_the_copy_is_still_refused(self):
        source = self._create_source()
        request = self._request()

        def edit_dataset(event):
            if event["stage"] == "reserving_classes" and event["completed"] == 1:
                (source / "data" / "RC B" / "datasets" / "paid.csv").write_text(
                    "1,2,3\n", encoding="utf-8"
                )

        with self.assertRaisesRegex(
            project_duplication.ProjectDuplicationError,
            "source project changed",
        ):
            project_duplication.duplicate_project(
                self.server_root,
                request,
                progress_callback=edit_dataset,
            )
        self.assertFalse((self.projects_dir / "Target").exists())

    def test_transient_copy_error_is_retried_and_publishes_the_target(self):
        """A share hiccup on one reserving class must not abort the project."""

        self._create_source()
        request = self._request()
        real_copytree = project_duplication.shutil.copytree
        failed = []

        def flaky_copytree(source, target, *args, **kwargs):
            if Path(source).name == "RC A" and not failed:
                failed.append(Path(source).name)
                # Leave the partial destination a real copy would leave behind.
                Path(target).mkdir(parents=True)
                (Path(target) / "partial.bin").write_text("partial", encoding="utf-8")
                raise PermissionError(32, "The process cannot access the file")
            return real_copytree(source, target, *args, **kwargs)

        with (
            patch.object(project_duplication.shutil, "copytree", flaky_copytree),
            patch.object(
                project_duplication, "PROJECT_DUPLICATION_COPY_RETRY_SECONDS", (0,)
            ),
        ):
            total = project_duplication.duplicate_project(
                self.server_root,
                request,
                progress_callback=lambda _event: None,
            )

        self.assertEqual(failed, ["RC A"])
        self.assertEqual(total, 2)
        target = self.projects_dir / "Target"
        self.assertTrue((target / "data" / "RC A" / "sidecars" / "paid.json").is_file())
        self.assertTrue((target / "data" / "RC B" / "datasets" / "paid.csv").is_file())
        # The retry must discard the partial attempt, or the staged manifest
        # would no longer match the source and publication would be refused.
        self.assertFalse((target / "data" / "RC A" / "partial.bin").exists())
        self.assertEqual(
            list(self.projects_dir.glob(".arcrho-project-duplication-*")), []
        )

    def test_failed_copy_logs_the_real_error_while_status_stays_redacted(self):
        self._create_source()
        request = self._request()

        def always_fails(source, target, *args, **kwargs):
            raise OSError(64, "The specified network name is no longer available")

        with (
            patch.object(project_duplication.shutil, "copytree", always_fails),
            patch.object(
                project_duplication, "PROJECT_DUPLICATION_COPY_RETRY_SECONDS", (0,)
            ),
        ):
            self.assertFalse(
                project_duplication.execute_project_duplication(
                    self.server_root, request
                )
            )

        status = json.loads(
            project_duplication_status_path(
                self.server_root, request["RequestId"]
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(
            status["message"],
            "The Arco Server filesystem could not complete project duplication.",
        )

        log_text = project_duplication._duplication_log_path(
            self.server_root
        ).read_text(encoding="utf-8")
        # The shared status stays location-independent; the log carries the
        # detail that makes a client-site failure diagnosable at all.
        self.assertIn("The specified network name is no longer available", log_text)
        self.assertIn("attempt 1 failed, retrying", log_text)
        self.assertIn(
            f"failed after {project_duplication.PROJECT_DUPLICATION_COPY_ATTEMPTS}"
            " attempts",
            log_text,
        )
        self.assertIn("Traceback", log_text)

    def test_live_lock_blocks_and_stale_lock_is_recovered_without_owner_race(self):
        self._create_source()
        request = self._request()
        lock = project_duplication._acquire_target_lock(
            self.server_root, "Target", "first-owner"
        )
        try:
            with self.assertRaisesRegex(
                project_duplication.ProjectDuplicationError,
                "Another project duplication",
            ):
                project_duplication.duplicate_project(
                    self.server_root,
                    request,
                    progress_callback=lambda _event: None,
                )
            self.assertTrue(lock.path.is_file())

            old_time = time.time() - 30
            os.utime(lock.path, (old_time, old_time))
            with patch.object(
                project_duplication,
                "PROJECT_DUPLICATION_LOCK_STALE_SECONDS",
                1,
            ):
                replacement = project_duplication._acquire_target_lock(
                    self.server_root, "Target", "second-owner"
                )
            self.assertNotEqual(lock.owner_token, replacement.owner_token)
            project_duplication._release_target_lock(lock)
            self.assertTrue(replacement.path.is_file())
            project_duplication._release_target_lock(replacement)
            self.assertFalse(replacement.path.exists())
        finally:
            project_duplication._release_target_lock(lock)

    def test_execute_publishes_terminal_success_and_safe_error(self):
        self._create_source()
        request = self._request()

        self.assertTrue(
            project_duplication.execute_project_duplication(
                self.server_root, request
            )
        )
        status_path = project_duplication_status_path(self.server_root, "job-123")
        status = validate_project_duplication_status(
            json.loads(status_path.read_text(encoding="utf-8")),
            expected_request_id="job-123",
        )
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["progress"]["completed"], 2)
        self.assertEqual(status["progress"]["total"], 2)

        error_request = self._request(request_id="job-error", target="Target")
        self.assertFalse(
            project_duplication.execute_project_duplication(
                self.server_root, error_request
            )
        )
        error_status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root, "job-error"
                ).read_text(encoding="utf-8")
            ),
            expected_request_id="job-error",
        )
        self.assertEqual(error_status["status"], "error")
        self.assertEqual(
            error_status["message"], "The target project folder already exists."
        )
        self.assertNotIn(str(self.server_root), json.dumps(error_status))

    def test_worker_that_loses_lease_does_not_publish_terminal_error(self):
        request = self._request(request_id="job-stale-worker")
        ownership_checks = 0
        published_statuses = []

        def require_owner():
            nonlocal ownership_checks
            ownership_checks += 1
            if ownership_checks > 1:
                raise project_duplication.ProjectDuplicationLeaseLost("taken over")

        def capture_status(_root, _request, status, **_kwargs):
            published_statuses.append(status)

        with (
            patch.object(
                project_duplication,
                "duplicate_project",
                side_effect=project_duplication.ProjectDuplicationError(
                    "copy failed"
                ),
            ),
            patch.object(
                project_duplication,
                "write_project_duplication_status",
                side_effect=capture_status,
            ),
        ):
            self.assertFalse(
                project_duplication.execute_project_duplication(
                    self.server_root,
                    request,
                    ownership_callback=require_owner,
                )
            )

        self.assertEqual(ownership_checks, 2)
        self.assertEqual(published_statuses, ["processing"])

    def test_success_status_failure_rolls_back_the_visible_target(self):
        self._create_source()
        request = self._request(request_id="job-status-failure")
        canonical_writer = project_duplication.write_project_duplication_status

        def fail_success(server_root, request_payload, status, **kwargs):
            if status == "success":
                raise OSError("status share unavailable")
            return canonical_writer(
                server_root,
                request_payload,
                status,
                **kwargs,
            )

        with patch.object(
            project_duplication,
            "write_project_duplication_status",
            side_effect=fail_success,
        ):
            self.assertFalse(
                project_duplication.execute_project_duplication(
                    self.server_root,
                    request,
                )
            )

        self.assertFalse((self.projects_dir / "Target").exists())
        self.assertEqual(
            list(self.projects_dir.glob(".arcrho-project-duplication-*")),
            [],
        )
        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    "job-status-failure",
                ).read_text(encoding="utf-8")
            ),
            expected_request_id="job-status-failure",
        )
        self.assertEqual(status["status"], "error")

    def test_status_failure_preserves_a_target_changed_after_publication(self):
        self._create_source()
        target = self.projects_dir / "Target"

        def change_target_then_fail(_total):
            transient_dir = target / "data" / "tmp"
            transient_dir.mkdir()
            (transient_dir / "concurrent.txt").write_text(
                "keep",
                encoding="utf-8",
            )
            raise OSError("status share unavailable")

        with self.assertRaisesRegex(
            project_duplication.ProjectDuplicationError,
            "target changed before rollback",
        ):
            project_duplication.duplicate_project(
                self.server_root,
                self._request(request_id="job-concurrent-change"),
                progress_callback=lambda _event: None,
                commit_callback=change_target_then_fail,
            )

        self.assertEqual(
            (target / "data" / "tmp" / "concurrent.txt").read_text(
                encoding="utf-8"
            ),
            "keep",
        )

    def test_preserved_target_publishes_recovery_required_error(self):
        self._create_source()
        target = self.projects_dir / "Target"
        request = self._request(request_id="job-recovery-required")
        canonical_writer = project_duplication.write_project_duplication_status

        def change_target_before_success(server_root, request_payload, status, **kwargs):
            if status == "success":
                transient_dir = target / "data" / "tmp"
                transient_dir.mkdir()
                (transient_dir / "concurrent.txt").write_text(
                    "keep",
                    encoding="utf-8",
                )
                raise OSError("status share unavailable")
            return canonical_writer(
                server_root,
                request_payload,
                status,
                **kwargs,
            )

        with patch.object(
            project_duplication,
            "write_project_duplication_status",
            side_effect=change_target_before_success,
        ):
            self.assertFalse(
                project_duplication.execute_project_duplication(
                    self.server_root,
                    request,
                )
            )

        self.assertTrue(target.is_dir())
        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    "job-recovery-required",
                ).read_text(encoding="utf-8")
            ),
            expected_request_id="job-recovery-required",
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "recovery_required")

    def test_rollback_verification_failure_preserves_target_for_recovery(self):
        self._create_source()
        target = self.projects_dir / "Target"
        request = self._request(request_id="job-rollback-verification")
        canonical_writer = project_duplication.write_project_duplication_status
        canonical_manifest = project_duplication._source_manifest
        strict_staging_reads = 0

        def fail_success(server_root, request_payload, status, **kwargs):
            if status == "success":
                raise OSError("status share unavailable")
            return canonical_writer(
                server_root,
                request_payload,
                status,
                **kwargs,
            )

        def fail_quarantined_verification(path, *, include_transient=False):
            nonlocal strict_staging_reads
            if include_transient and Path(path).name.startswith(
                project_duplication._STAGING_PREFIX
            ):
                strict_staging_reads += 1
                if strict_staging_reads == 2:
                    raise project_duplication.ProjectDuplicationError(
                        "verification unavailable"
                    )
            return canonical_manifest(path, include_transient=include_transient)

        with (
            patch.object(
                project_duplication,
                "write_project_duplication_status",
                side_effect=fail_success,
            ),
            patch.object(
                project_duplication,
                "_source_manifest",
                side_effect=fail_quarantined_verification,
            ),
        ):
            self.assertFalse(
                project_duplication.execute_project_duplication(
                    self.server_root,
                    request,
                )
            )

        self.assertTrue(target.is_dir())
        self.assertEqual(
            list(self.projects_dir.glob(".arcrho-project-duplication-*")),
            [],
        )
        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    "job-rollback-verification",
                ).read_text(encoding="utf-8")
            ),
            expected_request_id="job-rollback-verification",
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "recovery_required")

    def test_invalid_version_with_safe_id_publishes_rejected_status(self):
        request = self._request(request_id="job-newer-contract")
        request["ContractVersion"] = PROJECT_DUPLICATION_CONTRACT_VERSION + 1

        self.assertFalse(
            project_duplication.execute_project_duplication(
                self.server_root,
                request,
            )
        )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    "job-newer-contract",
                ).read_text(encoding="utf-8")
            ),
            expected_request_id="job-newer-contract",
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "rejected")
        self.assertIn("Unsupported ContractVersion", status["message"])

    def test_durable_request_lease_blocks_parallel_engine_and_allows_stale_takeover(self):
        request = self._request(request_id="job-durable-lease")
        request_path = self._queue_request(request)
        first = project_duplication._acquire_request_lease(
            self.server_root,
            request["RequestId"],
        )
        self.assertIsNotNone(first)
        assert first is not None
        try:
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )
            self.assertTrue(request_path.is_file())

            old_time = time.time() - 30
            os.utime(first.path, (old_time, old_time))
            with patch.object(
                project_duplication,
                "PROJECT_DUPLICATION_CLAIM_STALE_SECONDS",
                1,
            ):
                replacement = project_duplication._acquire_request_lease(
                    self.server_root,
                    request["RequestId"],
                )
            self.assertIsNotNone(replacement)
            assert replacement is not None
            first.heartbeat_failed.set()
            with patch.object(
                project_duplication,
                "_request_lease_is_owned",
                return_value=True,
            ) as stale_owner_check:
                project_duplication._release_request_lease(first)
            stale_owner_check.assert_not_called()
            self.assertTrue(replacement.path.is_file())
            project_duplication._release_request_lease(replacement)
            self.assertFalse(replacement.path.exists())
        finally:
            project_duplication._release_request_lease(first)

    def test_request_lease_heartbeat_runs_in_background(self):
        lease = project_duplication._acquire_request_lease(
            self.server_root,
            "job-heartbeat",
        )
        self.assertIsNotNone(lease)
        assert lease is not None
        try:
            with (
                patch.object(
                    project_duplication,
                    "PROJECT_DUPLICATION_CLAIM_HEARTBEAT_SECONDS",
                    0.01,
                ),
                patch.object(
                    project_duplication,
                    "_refresh_request_lease",
                    return_value=False,
                ) as refresh,
            ):
                stop_event, thread = project_duplication._start_request_lease_heartbeat(
                    lease
                )
                thread.join(timeout=1)
                stop_event.set()
            self.assertFalse(thread.is_alive())
            refresh.assert_called_once_with(lease)
            self.assertTrue(lease.heartbeat_failed.is_set())
            with self.assertRaises(project_duplication.ProjectDuplicationLeaseLost):
                project_duplication._require_request_lease(lease)
        finally:
            project_duplication._release_request_lease(lease)

    def test_partial_staging_is_cleaned_and_restarted_from_retained_request(self):
        self._create_source()
        request = self._request(request_id="job-partial-restart")
        request_path = self._queue_request(request)
        staging = project_duplication._staging_path(
            self.projects_dir,
            "Target",
            request["RequestId"],
        )
        staging.mkdir()
        (staging / "partial.txt").write_text("partial", encoding="utf-8")

        self.assertTrue(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        self.assertTrue((self.projects_dir / "Target").is_dir())
        self.assertFalse(request_path.exists())
        self.assertFalse(
            project_duplication._recovery_journal_path(
                self.server_root,
                request["RequestId"],
            ).exists()
        )

    def test_verified_staging_and_published_target_recover_after_worker_crash(self):
        self._create_source()
        request = self._request(request_id="job-staging-recovery")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        journal_text = journal_path.read_text(encoding="utf-8")
        self.assertNotIn(str(self.server_root), journal_text)

        self.assertTrue(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )
        self.assertFalse(staging.exists())
        self.assertTrue((self.projects_dir / "Target").is_dir())
        self.assertFalse(request_path.exists())
        self.assertFalse(journal_path.exists())

        second_request = self._request(
            request_id="job-target-recovery",
            target="Recovered Target",
        )
        second_path = self._queue_request(second_request)
        second_staging = self._interrupt_after_verified_staging(second_request)
        target = self.projects_dir / "Recovered Target"
        os.rename(second_staging, target)
        crashed_target_lock = project_duplication._acquire_target_lock(
            self.server_root,
            "Recovered Target",
            second_request["RequestId"],
        )

        self.assertTrue(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                second_path,
                second_request,
            )
        )
        self.assertTrue(target.is_dir())
        self.assertFalse(second_path.exists())
        self.assertFalse(crashed_target_lock.path.exists())

    def test_changed_published_target_requires_recovery_and_is_preserved(self):
        self._create_source()
        request = self._request(request_id="job-changed-recovery")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        target = self.projects_dir / "Target"
        os.rename(staging, target)
        (target / "concurrent.txt").write_text("keep", encoding="utf-8")

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        self.assertEqual(
            (target / "concurrent.txt").read_text(encoding="utf-8"),
            "keep",
        )
        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertFalse(request_path.exists())

    def test_reparse_published_target_requires_recovery_and_is_preserved(self):
        self._create_source()
        request = self._request(request_id="job-reparse-target-recovery")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        target = self.projects_dir / "Target"
        os.rename(staging, target)
        inspect_path = project_duplication._path_is_link_or_reparse

        def mark_target_as_reparse(path):
            if Path(path) == target:
                return True
            return inspect_path(path)

        with patch.object(
            project_duplication,
            "_path_is_link_or_reparse",
            side_effect=mark_target_as_reparse,
        ):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        self.assertTrue(target.is_dir())
        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "recovery_required")

    def test_changed_verified_staging_requires_recovery_and_is_preserved(self):
        self._create_source()
        request = self._request(request_id="job-changed-staging")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        (staging / "concurrent.txt").write_text("keep", encoding="utf-8")

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertEqual(
            (staging / "concurrent.txt").read_text(encoding="utf-8"),
            "keep",
        )
        self.assertFalse(request_path.exists())
        self.assertTrue(journal_path.is_file())

    def test_missing_verified_copy_requires_recovery_and_preserves_journal(self):
        self._create_source()
        request = self._request(request_id="job-missing-verified-copy")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        project_duplication.shutil.rmtree(staging)

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertFalse(request_path.exists())
        self.assertTrue(journal_path.is_file())

    def test_unverifiable_journal_publishes_recovery_required(self):
        self._create_source()
        request = self._request(request_id="job-invalid-journal")
        request_path = self._queue_request(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        write_json_atomic(journal_path, {"journal_version": 999})

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertFalse(request_path.exists())
        self.assertTrue(journal_path.exists())

    def test_invalid_existing_status_preserves_request_and_journal_for_retry(self):
        self._create_source()
        request = self._request(request_id="job-invalid-existing-status")
        request_path = self._queue_request(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        write_json_atomic(journal_path, {"preserve": True})
        status_path = project_duplication_status_path(
            self.server_root,
            request["RequestId"],
        )
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text("{", encoding="utf-8")

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        self.assertTrue(request_path.is_file())
        self.assertTrue(journal_path.is_file())
        self.assertEqual(status_path.read_text(encoding="utf-8"), "{")
        self.assertFalse((self.projects_dir / "Target").exists())

    def test_failed_request_cleanup_keeps_recovery_journal(self):
        request = self._request(request_id="job-cleanup-retry")
        request_path = self._queue_request(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        write_json_atomic(journal_path, {"preserve": True})
        project_duplication.write_project_duplication_status(
            self.server_root,
            request,
            "success",
            progress={
                "stage": "complete",
                "completed": 0,
                "total": 0,
                "label": "Project duplication complete",
            },
        )
        real_unlink = Path.unlink

        def fail_request_unlink(path, *args, **kwargs):
            if path == request_path:
                raise PermissionError("request locked")
            return real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_request_unlink):
            self.assertFalse(
                project_duplication._cleanup_durable_terminal(
                    self.server_root,
                    request_path,
                    request["RequestId"],
                )
            )

        self.assertTrue(request_path.is_file())
        self.assertTrue(journal_path.is_file())

    def test_recovered_success_write_failure_leaves_target_and_journal_for_retry(self):
        self._create_source()
        request = self._request(request_id="job-recovery-status-retry")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )

        with patch.object(
            project_duplication,
            "write_project_duplication_status",
            side_effect=PermissionError("status unavailable"),
        ):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        self.assertFalse(staging.exists())
        self.assertTrue((self.projects_dir / "Target").is_dir())
        self.assertTrue(request_path.is_file())
        self.assertTrue(journal_path.is_file())

    def test_target_and_staging_together_require_manual_recovery(self):
        self._create_source()
        request = self._request(request_id="job-ambiguous-recovery")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        target = self.projects_dir / "Target"
        project_duplication.shutil.copytree(staging, target)

        self.assertFalse(
            project_duplication.process_durable_project_duplication_request(
                self.server_root,
                request_path,
                request,
            )
        )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertTrue(target.is_dir())
        self.assertTrue(staging.is_dir())
        self.assertFalse(request_path.exists())
        self.assertTrue(
            project_duplication._recovery_journal_path(
                self.server_root,
                request["RequestId"],
            ).exists()
        )

    def test_target_appearing_during_staging_recovery_requires_recovery(self):
        self._create_source()
        request = self._request(request_id="job-target-race")
        request_path = self._queue_request(request)
        staging = self._interrupt_after_verified_staging(request)
        target = self.projects_dir / "Target"
        journal_path = project_duplication._recovery_journal_path(
            self.server_root,
            request["RequestId"],
        )
        acquire_target_lock = project_duplication._acquire_target_lock

        def acquire_after_target_appears(*args, **kwargs):
            lock = acquire_target_lock(*args, **kwargs)
            project_duplication.shutil.copytree(staging, target)
            return lock

        with patch.object(
            project_duplication,
            "_acquire_target_lock",
            side_effect=acquire_after_target_appears,
        ):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        status = validate_project_duplication_status(
            json.loads(
                project_duplication_status_path(
                    self.server_root,
                    request["RequestId"],
                ).read_text(encoding="utf-8")
            ),
            expected_request_id=request["RequestId"],
        )
        self.assertEqual(status["progress"]["stage"], "recovery_required")
        self.assertTrue(target.is_dir())
        self.assertTrue(staging.is_dir())
        self.assertTrue(journal_path.is_file())
        self.assertFalse(request_path.exists())

    def test_status_write_failure_keeps_request_for_retry(self):
        self._create_source()
        request = self._request(request_id="job-status-retry")
        request_path = self._queue_request(request)

        with patch.object(
            project_duplication,
            "write_project_duplication_status",
            side_effect=PermissionError("status unavailable"),
        ):
            self.assertFalse(
                project_duplication.process_durable_project_duplication_request(
                    self.server_root,
                    request_path,
                    request,
                )
            )

        self.assertTrue(request_path.is_file())
        self.assertIsNone(
            project_duplication._validated_terminal_status(
                self.server_root,
                request["RequestId"],
            )
        )


if __name__ == "__main__":
    unittest.main()
