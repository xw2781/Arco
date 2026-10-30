"""Contract and listener behaviour for remotely requested component builds."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
SERVER_COMPONENTS_ROOT = REPOSITORY_ROOT / "server-components"
TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
for candidate in (ENGINE_SRC, PYTHON_API_SRC, SERVER_COMPONENTS_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import arcrho_build_request_contract as contract  # noqa: E402
import deploy  # noqa: E402
from arcrho_build_listener import BuildListener, BuildListenerError  # noqa: E402


KNOWN_ROLES = ("admin", "bridge", "engine", "launcher", "orchestrator", "gateway")


def _temp_root() -> tempfile.TemporaryDirectory:
    TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEST_TMP_ROOT)


class BuildRequestContractTests(unittest.TestCase):
    def test_working_tree_request_round_trips_through_validation(self) -> None:
        request = contract.build_build_request(
            request_id="build-260817-120000-000-xwei",
            components=["bridge", "engine", "bridge"],
            base_commit="5890c00",
            payload_name="build-260817-120000-000-xwei.zip",
            user_name="xwei",
            machine="L-CLIENT",
            known_roles=KNOWN_ROLES,
        )
        # Duplicates collapse but request order is kept: components deploy in
        # the order the requester listed them.
        self.assertEqual(request["Components"], ["bridge", "engine"])
        self.assertEqual(request["SourceMode"], contract.SOURCE_MODE_WORKING_TREE)
        self.assertEqual(
            contract.validate_build_request(request, known_roles=KNOWN_ROLES), request
        )

    def test_unknown_component_and_unsupported_version_are_rejected(self) -> None:
        with self.assertRaises(contract.BuildRequestContractError):
            contract.build_build_request(
                request_id="build-1",
                components=["frontend"],
                base_commit="5890c00",
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
        future = contract.build_build_request(
            request_id="build-1",
            components=["bridge"],
            base_commit="5890c00",
            user_name="xwei",
            known_roles=KNOWN_ROLES,
        )
        future["ContractVersion"] = contract.BUILD_REQUEST_CONTRACT_VERSION + 1
        with self.assertRaises(contract.BuildRequestContractError):
            contract.validate_build_request(future, known_roles=KNOWN_ROLES)

    def test_working_tree_mode_requires_a_base_commit(self) -> None:
        with self.assertRaises(contract.BuildRequestContractError):
            contract.build_build_request(
                request_id="build-1",
                components=["bridge"],
                source_mode=contract.SOURCE_MODE_WORKING_TREE,
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
        ref_request = contract.build_build_request(
            request_id="build-1",
            components=["bridge"],
            source_mode=contract.SOURCE_MODE_REF,
            ref="main",
            user_name="xwei",
            known_roles=KNOWN_ROLES,
        )
        self.assertEqual(ref_request["Ref"], "main")
        self.assertEqual(ref_request["BaseCommit"], "")

    def test_payload_name_may_not_escape_the_payload_folder(self) -> None:
        request = contract.build_build_request(
            request_id="build-1",
            components=["bridge"],
            base_commit="5890c00",
            user_name="xwei",
            known_roles=KNOWN_ROLES,
        )
        request["PayloadName"] = "../../evil.zip"
        with self.assertRaises(contract.BuildRequestContractError):
            contract.validate_build_request(request, known_roles=KNOWN_ROLES)

    def test_allowlist_rejects_an_unlisted_requester(self) -> None:
        request = contract.build_build_request(
            request_id="build-1",
            components=["bridge"],
            base_commit="5890c00",
            user_name="mallory",
            known_roles=KNOWN_ROLES,
        )
        contract.validate_build_request(
            request, known_roles=KNOWN_ROLES, allowed_users=["Mallory"]
        )
        with self.assertRaises(contract.BuildRequestContractError):
            contract.validate_build_request(
                request, known_roles=KNOWN_ROLES, allowed_users=["xwei"]
            )

    def test_queue_paths_all_sit_under_the_requests_protocol_folder(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            protocol = contract.ensure_build_protocol_directories(server_root)
            self.assertEqual(protocol, server_root / "requests" / "builds")
            for path in (
                contract.build_request_path(server_root, "build-1"),
                contract.build_status_path(server_root, "build-1"),
                contract.build_lock_path(server_root, "build-1"),
                contract.build_payload_path(server_root, "build-1"),
                contract.build_log_path(server_root, "build-1"),
            ):
                self.assertIn(protocol, path.parents)
                self.assertTrue(path.parent.is_dir())

    def test_status_round_trip_and_terminal_detection(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            contract.ensure_build_protocol_directories(server_root)
            status = contract.build_build_status(
                request_id="build-1",
                status="building",
                message="Building Bridge...",
                components=[contract.build_component_state("bridge", "building")],
                log_bytes=42,
            )
            contract.write_build_status(server_root, status)
            self.assertFalse(contract.build_status_is_terminal(status))
            loaded = contract.read_build_status(server_root, "build-1")
            self.assertEqual(loaded["log_bytes"], 42)
            self.assertEqual(loaded["components"][0]["role"], "bridge")

            done = contract.build_build_status(
                request_id="build-1", status="success", created_at=status["created_at"]
            )
            contract.write_build_status(server_root, done)
            self.assertTrue(
                contract.build_status_is_terminal(
                    contract.read_build_status(server_root, "build-1")
                )
            )
            # The created_at of the first status survives the terminal write, so
            # a poller can measure how long a build actually took.
            self.assertEqual(done["created_at"], status["created_at"])

    def test_missing_status_reads_as_none(self) -> None:
        with _temp_root() as root:
            self.assertIsNone(contract.read_build_status(Path(root), "build-absent"))


class ListenerHeartbeatTests(unittest.TestCase):
    def test_listener_preflight_reports_how_to_start_one(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            with self.assertRaises(contract.BuildListenerUnavailable) as caught:
                contract.require_live_listener(server_root)
            # The client's only human-facing instruction must name the launcher.
            self.assertIn("build_manager.bat", str(caught.exception))

            path = contract.listener_heartbeat_path(server_root, "SERVER", "xwei")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"Server": "SERVER@xwei"}), encoding="utf-8")
            fresh = contract.require_live_listener(server_root)
            self.assertEqual(fresh[0]["Server"], "SERVER@xwei")

    def test_a_stale_heartbeat_does_not_count_as_a_live_listener(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            path = contract.listener_heartbeat_path(server_root, "SERVER", "xwei")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            stale = time.time() - (contract.LISTENER_HEARTBEAT_MAX_AGE_SECONDS + 30)
            import os

            os.utime(path, (stale, stale))
            with self.assertRaises(contract.BuildListenerUnavailable):
                contract.require_live_listener(server_root)


class ServerListenerStartTests(unittest.TestCase):
    """deploy.py starts the Build Manager itself on the Server PC, and nowhere else."""

    def test_only_the_sibling_clone_carrying_the_marker_is_a_build_clone(self) -> None:
        with _temp_root() as root:
            repos = Path(root)
            for name in ("ArcRho", "ArcRho-buildbot", "Other"):
                (repos / name / ".git").mkdir(parents=True)
            (repos / "ArcRho-buildbot" / ".git" / deploy.BUILD_CLONE_MARKER).write_text("", encoding="utf-8")
            self.assertEqual(deploy.build_clones(repos / "ArcRho"), [repos / "ArcRho-buildbot"])

    def test_the_server_pc_starts_the_manager_from_the_build_clone_and_waits(self) -> None:
        live = [{"Server": "SERVER@xwei"}]
        with patch.object(deploy, "workspace_drive_is_local", return_value=True), \
                patch.object(deploy, "build_clones", return_value=[Path("E:/Repos/ArcRho-buildbot")]), \
                patch.object(deploy.subprocess, "Popen") as popen, \
                patch.object(deploy.time, "sleep"), \
                patch.object(deploy, "require_live_listener",
                             side_effect=[contract.BuildListenerUnavailable("none"), live]):
            self.assertEqual(deploy._start_server_listener(Path("E:/ArcRho Server")), live)
        command = popen.call_args.args[0]
        self.assertEqual(Path(command[-1]), Path("E:/Repos/ArcRho-buildbot/server-components/build_manager.bat"))

    def test_nothing_starts_from_a_client_pc_or_without_one_marked_clone(self) -> None:
        for local, clones in ((False, [Path("E:/a")]), (True, []), (True, [Path("E:/a"), Path("E:/b")])):
            with self.subTest(local=local, clones=clones), \
                    patch.object(deploy, "workspace_drive_is_local", return_value=local), \
                    patch.object(deploy, "build_clones", return_value=clones), \
                    patch.object(deploy.subprocess, "Popen") as popen:
                self.assertEqual(deploy._start_server_listener(Path("E:/ArcRho Server")), [])
                popen.assert_not_called()


class ListenerServicingTests(unittest.TestCase):
    """The listener's queue behaviour, with the build script itself stubbed."""

    def _listener(self, server_root: Path, repository_root: Path) -> BuildListener:
        return BuildListener(
            server_root,
            repository_root=repository_root,
            python_executable=sys.executable,
        )

    def _queue(self, server_root: Path, **overrides) -> str:
        contract.ensure_build_protocol_directories(server_root)
        payload = {
            "request_id": contract.new_request_id("xwei"),
            "components": ["bridge"],
            "base_commit": "5890c00",
            "user_name": "xwei",
            "known_roles": KNOWN_ROLES,
        }
        payload.update(overrides)
        request = contract.build_build_request(**payload)
        contract.write_json_atomic(
            contract.build_request_path(server_root, request["RequestId"]), request
        )
        return request["RequestId"]

    def test_a_serviced_request_is_consumed_and_reports_success(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            request_id = self._queue(server_root)
            listener = self._listener(server_root, REPOSITORY_ROOT)
            with (
                patch.object(BuildListener, "_prepare_sources", return_value=None),
                patch.object(BuildListener, "_run_build_script", return_value=(0, "")),
            ):
                self.assertEqual(listener.poll_once(), 1)

            status = contract.read_build_status(server_root, request_id)
            self.assertEqual(status["status"], "success")
            self.assertEqual(status["components"][0]["state"], "success")
            # Consuming the request file is what stops a redelivery loop.
            self.assertFalse(contract.build_request_path(server_root, request_id).exists())
            self.assertEqual(listener.poll_once(), 0)

    def test_a_failed_component_fails_the_request_and_skips_the_rest(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            request_id = self._queue(server_root, components=["bridge", "engine"])
            listener = self._listener(server_root, REPOSITORY_ROOT)
            with (
                patch.object(BuildListener, "_prepare_sources", return_value=None),
                patch.object(
                    BuildListener, "_run_build_script", return_value=(1, "PyInstaller failed")
                ),
            ):
                listener.poll_once()

            status = contract.read_build_status(server_root, request_id)
            self.assertEqual(status["status"], "error")
            self.assertIn("PyInstaller failed", status["message"])
            states = {item["role"]: item["state"] for item in status["components"]}
            self.assertEqual(states, {"bridge": "error", "engine": "skipped"})

    def test_a_source_preparation_failure_becomes_an_error_status(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            request_id = self._queue(server_root)
            listener = self._listener(server_root, REPOSITORY_ROOT)
            with patch.object(
                BuildListener,
                "_prepare_sources",
                side_effect=BuildListenerError("Base commit 5890c00 is not in the server clone."),
            ):
                listener.poll_once()

            status = contract.read_build_status(server_root, request_id)
            self.assertEqual(status["status"], "error")
            self.assertIn("not in the server clone", status["message"])

    def test_a_held_lease_keeps_a_second_listener_off_the_same_request(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            request_id = self._queue(server_root)
            lock = contract.build_lock_path(server_root, request_id)
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(json.dumps({"owner_token": "someone-else"}), encoding="utf-8")

            listener = self._listener(server_root, REPOSITORY_ROOT)
            with patch.object(BuildListener, "_prepare_sources", return_value=None):
                self.assertEqual(listener.poll_once(), 0)
            self.assertTrue(contract.build_request_path(server_root, request_id).exists())

    def test_an_invalid_request_is_reported_rather_than_retried_forever(self) -> None:
        with _temp_root() as root:
            server_root = Path(root)
            contract.ensure_build_protocol_directories(server_root)
            request_id = "build-broken"
            contract.write_json_atomic(
                contract.build_request_path(server_root, request_id),
                {"Function": "ArcRhoBuildAndDeploy", "ContractVersion": 1},
            )
            listener = self._listener(server_root, REPOSITORY_ROOT)
            listener.poll_once()

            status = contract.read_build_status(server_root, request_id)
            self.assertEqual(status["status"], "error")
            self.assertFalse(contract.build_request_path(server_root, request_id).exists())

    def test_a_payload_may_not_write_outside_the_repository(self) -> None:
        with _temp_root() as root, _temp_root() as clone:
            server_root = Path(root)
            repository = Path(clone)
            request_id = self._queue(server_root)
            request = contract.validate_build_request(
                json.loads(
                    contract.build_request_path(server_root, request_id).read_text(
                        encoding="utf-8"
                    )
                ),
                known_roles=KNOWN_ROLES,
            )
            request["PayloadName"] = f"{request_id}.zip"
            archive_path = contract.build_payload_path(server_root, request_id)
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("untracked/../../escaped.py", "print('escaped')")

            listener = self._listener(server_root, repository)
            with self.assertRaises(BuildListenerError) as caught:
                listener._apply_payload(request, contract.build_log_path(server_root, request_id))
            self.assertIn("outside the repository", str(caught.exception))
            self.assertFalse((repository.parent / "escaped.py").exists())


class WorkingTreePayloadRoundTripTests(unittest.TestCase):
    """A client's uncommitted source must reappear in the listener's clone.

    These run real git commands against scratch repositories, because the value
    of the working-tree mode rests entirely on the patch applying cleanly to a
    base commit the server already has.
    """

    def _git(self, repository: Path, *arguments: str) -> str:
        import subprocess

        completed = subprocess.run(
            ["git", *arguments],
            cwd=str(repository),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"git {' '.join(arguments)} failed: {completed.stderr or completed.stdout}"
            )
        return (completed.stdout or "").strip()

    def _init_repository(self, path: Path) -> str:
        path.mkdir(parents=True, exist_ok=True)
        self._git(path, "init", "--quiet")
        self._git(path, "config", "user.email", "tests@arcrho.local")
        self._git(path, "config", "user.name", "ArcRho Tests")
        source = path / "src"
        source.mkdir(parents=True, exist_ok=True)
        (source / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        self._git(path, "add", "-A")
        self._git(path, "commit", "--quiet", "-m", "base")
        return self._git(path, "rev-parse", "HEAD")

    def test_uncommitted_edits_and_new_files_reach_the_listener_clone(self) -> None:
        with _temp_root() as workspace, _temp_root() as server:
            root = Path(workspace)
            client = root / "client"
            base_commit = self._init_repository(client)
            server_clone = root / "server-clone"
            self._git(root, "clone", "--quiet", str(client), str(server_clone))

            # The client edits a tracked file, adds a new one, and commits
            # neither -- the state an agent is in when AGENTS.md asks for a
            # rebuild.
            (client / "src" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
            (client / "src" / "added.py").write_text("NEW = True\n", encoding="utf-8")

            server_root = Path(server)
            contract.ensure_build_protocol_directories(server_root)
            request_id = contract.new_request_id("xwei")
            payload = deploy._build_payload(
                ["src"],
                base_commit,
                contract.build_payload_path(server_root, request_id),
                repository=client,
            )
            archive = payload["archive"]
            self.assertIsNotNone(archive)
            self.assertGreater(payload["size"], 0)
            # What the deploy will send has to be reportable: a working-tree
            # deploy also carries edits someone else is making at the same time.
            self.assertEqual(payload["changed"], ["src/module.py"])
            self.assertEqual(payload["untracked"], ["src/added.py"])

            request = contract.build_build_request(
                request_id=request_id,
                components=["bridge"],
                base_commit=base_commit,
                payload_name=archive.name,
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
            listener = BuildListener(
                server_root, repository_root=server_clone, python_executable=sys.executable
            )
            listener._prepare_sources(request, contract.build_log_path(server_root, request_id))

            self.assertEqual(
                (server_clone / "src" / "module.py").read_text(encoding="utf-8"), "VALUE = 2\n"
            )
            self.assertEqual(
                (server_clone / "src" / "added.py").read_text(encoding="utf-8"), "NEW = True\n"
            )

    def test_the_patch_reaches_git_byte_for_byte_on_an_lf_clone(self) -> None:
        # The server clone checks files out with LF endings. A patch pushed
        # through a text-mode pipe on Windows arrives with CRLF line endings,
        # and git then refuses hunks anchored at the start or end of a file
        # (seen 2026-08-17: "patch does not apply" on a docstring rewrite and
        # a trailing-line removal). The listener must hand git the bytes.
        with _temp_root() as workspace, _temp_root() as server:
            root = Path(workspace)
            client = root / "client"
            client.mkdir(parents=True, exist_ok=True)
            self._git(client, "init", "--quiet")
            self._git(client, "config", "user.email", "tests@arcrho.local")
            self._git(client, "config", "user.name", "ArcRho Tests")
            source = client / "src"
            source.mkdir(parents=True, exist_ok=True)
            original = "\n".join(f"LINE_{index} = {index}" for index in range(1, 25)) + "\n"
            (source / "module.py").write_bytes(original.encode("utf-8"))
            self._git(client, "add", "-A")
            self._git(client, "commit", "--quiet", "-m", "base")
            base_commit = self._git(client, "rev-parse", "HEAD")
            server_clone = root / "server-clone"
            self._git(root, "-c", "core.autocrlf=false", "clone", "--quiet", str(client), str(server_clone))
            self._git(server_clone, "config", "core.autocrlf", "false")
            self.assertNotIn(b"\r", (server_clone / "src" / "module.py").read_bytes())

            # First line rewritten, last line dropped: one hunk anchored at
            # each end of the file.
            edited = original.replace("LINE_1 = 1", "FIRST = 'x'", 1)
            edited = edited[: edited.rfind("LINE_24 = 24")]
            (source / "module.py").write_bytes(edited.encode("utf-8"))

            server_root = Path(server)
            contract.ensure_build_protocol_directories(server_root)
            request_id = contract.new_request_id("xwei")
            payload = deploy._build_payload(
                ["src"],
                base_commit,
                contract.build_payload_path(server_root, request_id),
                repository=client,
            )
            request = contract.build_build_request(
                request_id=request_id,
                components=["bridge"],
                base_commit=base_commit,
                payload_name=payload["archive"].name,
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
            listener = BuildListener(
                server_root, repository_root=server_clone, python_executable=sys.executable
            )
            listener._prepare_sources(request, contract.build_log_path(server_root, request_id))
            self.assertEqual(
                (server_clone / "src" / "module.py").read_bytes(), edited.encode("utf-8")
            )

    def test_a_patch_ending_on_a_blank_context_line_survives_the_payload(self) -> None:
        # A hunk's trailing context can be a blank line, which git writes as a
        # line containing one space. Trimming the patch's trailing whitespace
        # deletes that line, leaving the final hunk one line shorter than its
        # own header claims; git then refuses the whole patch as "corrupt
        # patch at <stdin>:<last line>" (seen 2026-08-20). The payload must
        # carry git's bytes as git produced them.
        with _temp_root() as workspace, _temp_root() as server:
            root = Path(workspace)
            client = root / "client"
            client.mkdir(parents=True, exist_ok=True)
            self._git(client, "init", "--quiet")
            self._git(client, "config", "user.email", "tests@arcrho.local")
            self._git(client, "config", "user.name", "ArcRho Tests")
            source = client / "src"
            source.mkdir(parents=True, exist_ok=True)
            # The edit lands just before a run of blank lines at the end of the
            # file, so the hunk's last context line is blank.
            original = "VALUE = 1\nKEEP = 2\n\n\n"
            (source / "module.py").write_bytes(original.encode("utf-8"))
            self._git(client, "add", "-A")
            self._git(client, "commit", "--quiet", "-m", "base")
            base_commit = self._git(client, "rev-parse", "HEAD")
            server_clone = root / "server-clone"
            self._git(
                root, "-c", "core.autocrlf=false", "clone", "--quiet", str(client), str(server_clone)
            )
            self._git(server_clone, "config", "core.autocrlf", "false")

            edited = original.replace("VALUE = 1", "VALUE = 99", 1)
            (source / "module.py").write_bytes(edited.encode("utf-8"))

            server_root = Path(server)
            contract.ensure_build_protocol_directories(server_root)
            request_id = contract.new_request_id("xwei")
            payload = deploy._build_payload(
                ["src"],
                base_commit,
                contract.build_payload_path(server_root, request_id),
                repository=client,
            )
            with zipfile.ZipFile(payload["archive"]) as archive:
                patch_text = archive.read(deploy.PATCH_MEMBER_NAME).decode("utf-8")
            # The blank context line is what a strip() would have eaten.
            self.assertTrue(
                patch_text.endswith(" \n"),
                f"patch lost its trailing context line: {patch_text[-40:]!r}",
            )

            request = contract.build_build_request(
                request_id=request_id,
                components=["bridge"],
                base_commit=base_commit,
                payload_name=payload["archive"].name,
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
            listener = BuildListener(
                server_root, repository_root=server_clone, python_executable=sys.executable
            )
            listener._prepare_sources(request, contract.build_log_path(server_root, request_id))
            self.assertEqual(
                (server_clone / "src" / "module.py").read_bytes(), edited.encode("utf-8")
            )

    def test_a_base_commit_the_server_cannot_resolve_is_refused(self) -> None:
        with _temp_root() as workspace, _temp_root() as server:
            root = Path(workspace)
            client = root / "client"
            self._init_repository(client)
            server_clone = root / "server-clone"
            self._git(root, "clone", "--quiet", str(client), str(server_clone))
            # Detach the clone from its origin so the listener's fetch cannot
            # reach the commit; that is what "never pushed" means in practice.
            self._git(server_clone, "remote", "remove", "origin")

            # A commit made after the clone stands in for one the client never
            # pushed; the listener must say so instead of building stale source.
            (client / "src" / "module.py").write_text("VALUE = 3\n", encoding="utf-8")
            self._git(client, "commit", "--quiet", "-am", "local only")
            unpushed = self._git(client, "rev-parse", "HEAD")

            request = contract.build_build_request(
                request_id=contract.new_request_id("xwei"),
                components=["bridge"],
                base_commit=unpushed,
                user_name="xwei",
                known_roles=KNOWN_ROLES,
            )
            server_root = Path(server)
            contract.ensure_build_protocol_directories(server_root)
            listener = BuildListener(
                server_root, repository_root=server_clone, python_executable=sys.executable
            )
            with self.assertRaises(BuildListenerError) as caught:
                listener._prepare_sources(
                    request, contract.build_log_path(server_root, request["RequestId"])
                )
            self.assertIn("Push the branch", str(caught.exception))

    def test_the_client_diffs_from_a_commit_the_server_already_has(self) -> None:
        with _temp_root() as workspace:
            root = Path(workspace)
            client = root / "client"
            base_commit = self._init_repository(client)
            self._git(root, "clone", "--quiet", str(client), str(root / "server-clone"))
            self._git(client, "remote", "add", "origin", str(root / "server-clone"))
            self._git(client, "fetch", "--quiet", "origin")

            # A local commit on top of the pushed base must not become the base;
            # otherwise the server could not resolve it.
            (client / "src" / "module.py").write_text("VALUE = 9\n", encoding="utf-8")
            self._git(client, "commit", "--quiet", "-am", "local only")
            self.assertEqual(deploy._base_commit(client), base_commit)


if __name__ == "__main__":
    unittest.main()


class AutoListenDecisionTests(unittest.TestCase):
    """The listener resets the clone it was started from, so ticking "Listen
    for build requests" without being asked has to be refused everywhere the
    reset would land on someone's work."""

    def setUp(self) -> None:
        import arcrho_build_components

        self.components = arcrho_build_components
        self.root = Path(tempfile.mkdtemp(prefix="auto-listen-", dir=str(TEST_TMP_ROOT)))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _decide(self, *, local: bool, marked: bool) -> tuple[bool, str]:
        git_dir = self.root / ".git"
        git_dir.mkdir(exist_ok=True)
        if marked:
            (git_dir / self.components.BUILD_CLONE_MARKER).write_text("", encoding="utf-8")
        with patch.object(self.components, "workspace_drive_is_local", return_value=local):
            return self.components.auto_listen_decision(self.root, Path(r"E:\ArcRho Server"))

    def test_the_server_pc_in_the_listeners_own_clone_listens_unasked(self) -> None:
        allowed, reason = self._decide(local=True, marked=True)

        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_a_clone_with_no_marker_is_refused_even_on_the_server(self) -> None:
        allowed, reason = self._decide(local=True, marked=False)

        self.assertFalse(allowed)
        self.assertIn(self.components.BUILD_CLONE_MARKER, reason)

    def test_a_workspace_reached_over_the_share_is_refused(self) -> None:
        allowed, reason = self._decide(local=False, marked=True)

        self.assertFalse(allowed)
        self.assertIn("share", reason)

    def test_the_marker_lives_under_git_where_a_reset_cannot_reach_it(self) -> None:
        # The listener checks out a detached base commit, resets hard and runs
        # git clean -fd before every build. A marker in the working tree is at
        # the mercy of whichever commit it built from -- an earlier attempt
        # gitignored one and the first real build deleted it, because that base
        # commit predated the ignore rule. Nothing under .git is touched.
        self.assertFalse(self.components.BUILD_CLONE_MARKER.startswith("."))

        allowed, _ = self._decide(local=True, marked=True)
        self.assertTrue(allowed)
        self.assertTrue((self.root / ".git" / self.components.BUILD_CLONE_MARKER).exists())

    def test_a_directory_that_is_not_a_plain_clone_is_refused(self) -> None:
        with patch.object(self.components, "workspace_drive_is_local", return_value=True):
            allowed, reason = self.components.auto_listen_decision(self.root, Path(r"E:\ArcRho Server"))

        self.assertFalse(allowed)
        self.assertIn("plain git clone", reason)
