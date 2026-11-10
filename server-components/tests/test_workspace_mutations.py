from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# Every test temp directory lives under one gitignored folder at the
# repository root, so a suite that dies before teardown cannot scatter
# tmp folders beside the code.
TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
ENGINE_SOURCE = REPOSITORY_ROOT / "server-components" / "src"
API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
for path in (ENGINE_SOURCE, API_SOURCE, FRONTEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi import HTTPException

from arcrho_hosted_save_http_contract import (
    default_gateway_config,
    mutation_receipt_path,
    request_sha256,
)
from arcrho_workspace_mutation_contract import (
    HTTP_WORKSPACE_MUTATION_KINDS,
    WORKSPACE_MUTATION_CAPABILITY_FIELD,
    WORKSPACE_MUTATION_KINDS,
    WorkspaceMutationContractError,
    build_workspace_mutation_request,
    validate_workspace_mutation_request,
)
from arcrho_api.gateway_test_guard import allow_test_gateway
from arcrho_gateway import main as gateway_main
from arcrho_gateway import workspace_mutations, workspace_reads
from app_server import config as app_config
from app_server.services import (
    client_save_latency_log_service,
    user_identity_service,
    workspace_mutation_client,
    workspace_read_client,
)


def _request(kind: str = "cached_dataset_delete", **overrides) -> dict:
    kwargs = {
        "project_name": "Demo Project",
        "reserving_class": "PA\\All States\\COL",
        "dataset_names": ["Paid Loss"],
    }
    kwargs.update(overrides)
    return build_workspace_mutation_request(
        request_id="mutation-1",
        mutation_kind=kind,
        kwargs=kwargs,
        user_name="alice",
        user_display_name="Alice Example",
    )


class WorkspaceMutationContractTests(unittest.TestCase):
    def test_every_registered_kind_names_a_real_service_function(self) -> None:
        """The registry is the only table; drift from the services must fail here."""

        for kind, spec in WORKSPACE_MUTATION_KINDS.items():
            module = importlib.import_module(f"app_server.services.{spec.module}")
            function = getattr(module, spec.function)
            parameters = inspect.signature(function).parameters
            for name in spec.required + spec.optional:
                self.assertIn(name, parameters, f"{kind}: {spec.function} lacks {name}")
            for name, parameter in parameters.items():
                if parameter.default is inspect.Parameter.empty and parameter.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    self.assertIn(name, spec.required, f"{kind}: {name} must be required")

    def test_advertised_kinds_are_the_registry(self) -> None:
        self.assertEqual(HTTP_WORKSPACE_MUTATION_KINDS, tuple(sorted(WORKSPACE_MUTATION_KINDS)))

    def test_validation_normalizes_and_trims_the_name_list(self) -> None:
        request = _request(dataset_names=["Paid Loss", "  Selected Ultimate  ", ""])
        self.assertEqual(request["MutationKind"], "cached_dataset_delete")
        self.assertEqual(
            request["Kwargs"]["dataset_names"], ["Paid Loss", "Selected Ultimate"]
        )
        self.assertEqual(request["UserName"], "alice")

    def test_validation_rejects_unknown_kind_and_arguments(self) -> None:
        with self.assertRaises(WorkspaceMutationContractError):
            _request("not_a_mutation")
        with self.assertRaises(WorkspaceMutationContractError):
            _request(refresh=True)
        with self.assertRaises(WorkspaceMutationContractError):
            _request(reserving_class="")

    def test_validation_rejects_a_name_list_that_is_not_a_list(self) -> None:
        """A bare string would otherwise be accepted as one oddly named dataset."""

        with self.assertRaises(WorkspaceMutationContractError):
            _request(dataset_names="Paid Loss")
        with self.assertRaises(WorkspaceMutationContractError):
            _request(dataset_names=[])
        with self.assertRaises(WorkspaceMutationContractError):
            _request(dataset_names=["  "])

    def test_validation_rejects_machine_local_locations(self) -> None:
        with self.assertRaises(WorkspaceMutationContractError):
            _request(reserving_class="E:\\Arco Server\\projects\\Demo")
        with self.assertRaises(WorkspaceMutationContractError):
            _request(project_name="CON")

    def test_foreign_payload_is_refused(self) -> None:
        with self.assertRaises(WorkspaceMutationContractError):
            validate_workspace_mutation_request({"Function": "ArcRhoWorkspaceRead"})


class _FakeMutationRuntime:
    """Swap one registered mutation for a fake without touching any workspace."""

    def __init__(self, kind: str, implementation) -> None:
        self.spec = WORKSPACE_MUTATION_KINDS[kind]
        self.module = importlib.import_module(f"app_server.services.{self.spec.module}")
        self.patch = patch.object(self.module, self.spec.function, implementation)

    def __enter__(self):
        self.patch.start()
        return self

    def __exit__(self, *exc) -> None:
        self.patch.stop()


class WorkspaceMutationExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.root / "config" / "arcrho_gateway.json", config
        )
        self.logged: list[str] = []
        self.executor = workspace_mutations.WorkspaceMutationExecutor(
            self.root,
            load_gateway_config=gateway_main._load_gateway_config,
            log=lambda _root, message: self.logged.append(message),
            ensure_runtime=lambda: None,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_execute_runs_the_registered_service_as_the_requesting_user(self) -> None:
        seen: dict = {}

        def fake_delete(project_name, reserving_class, dataset_names):
            seen.update(
                {
                    "project_name": project_name,
                    "reserving_class": reserving_class,
                    "dataset_names": list(dataset_names),
                    "identity": user_identity_service.get_current_identity(),
                }
            )
            return {"ok": True, "deleted_count": 2, "index": {"ok": True, "files": []}}

        with _FakeMutationRuntime("cached_dataset_delete", fake_delete):
            response = self.executor.execute("alice", _request())

        self.assertEqual(response["deleted_count"], 2)
        self.assertEqual(seen["project_name"], "Demo Project")
        self.assertEqual(seen["reserving_class"], "PA\\All States\\COL")
        self.assertEqual(seen["dataset_names"], ["Paid Loss"])
        self.assertEqual(seen["identity"]["login_name"], "alice")
        self.assertEqual(seen["identity"]["display_name"], "Alice Example")

    def test_structured_refusal_survives_and_only_its_text_is_redacted(self) -> None:
        """The blocked-dependents payload is what the page renders, not a string."""

        def refuse(**_kwargs):
            raise HTTPException(
                409,
                {
                    "error": "dataset_has_dependents",
                    "message": "Blocked while reading E:\\Arco Server\\projects\\Demo",
                    "blocked_datasets": [
                        {
                            "dataset_name": "Paid Loss",
                            "dependents": [
                                {"dataset_name": "Paid DFM", "method_type": "DFM"}
                            ],
                        }
                    ],
                },
            )

        with _FakeMutationRuntime("cached_dataset_delete", refuse):
            with self.assertRaises(workspace_reads.WorkspaceReadRefusal) as caught:
                self.executor.execute("alice", _request())

        detail = caught.exception.detail
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail["error"], "dataset_has_dependents")
        self.assertNotIn("E:\\", detail["message"])
        self.assertEqual(
            detail["blocked_datasets"],
            [
                {
                    "dataset_name": "Paid Loss",
                    "dependents": [{"dataset_name": "Paid DFM", "method_type": "DFM"}],
                }
            ],
        )

    def test_user_mismatch_and_bad_payload_are_gateway_errors(self) -> None:
        with self.assertRaises(workspace_reads.WorkspaceReadHttpError) as mismatch:
            self.executor.execute("bob", _request())
        self.assertEqual(mismatch.exception.status_code, 403)
        with self.assertRaises(workspace_reads.WorkspaceReadHttpError) as invalid:
            self.executor.execute("alice", {"Function": "ArcRhoWorkspaceMutation"})
        self.assertEqual(invalid.exception.status_code, 400)

    def test_capabilities_advertise_every_registered_kind(self) -> None:
        payload = gateway_main.Gateway(self.root).capabilities()
        self.assertEqual(
            payload[WORKSPACE_MUTATION_CAPABILITY_FIELD],
            list(HTTP_WORKSPACE_MUTATION_KINDS),
        )


class WorkspaceMutationHttpRoundTripTests(unittest.TestCase):
    """The client transport against a live gateway, both ends in this process."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        self.server_root = self.root / "server"
        self.client_root = self.root / "client-mapped"
        (self.server_root / "config").mkdir(parents=True)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.server_root / "config" / "arcrho_gateway.json", config
        )
        self.gateway = gateway_main.Gateway(self.server_root)
        self.gateway.reads._runtime_ready = True
        self.server = gateway_main.GatewayServer(("127.0.0.1", 0), self.gateway)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(allow_test_gateway(self.url))
        self.client_config = {
            "enabled": True,
            "url": self.url,
            "user": "alice",
            "secret": "alice-secret",
            "allow_insecure_http": True,
        }
        self.records: list[dict] = []
        self.patches = [
            patch.object(app_config, "load_gateway_config", return_value=self.client_config),
            patch.object(app_config, "get_root_path", return_value=str(self.client_root)),
            patch.object(workspace_read_client, "_is_server_process", return_value=False),
            patch.object(
                client_save_latency_log_service,
                "append_client_read_latency",
                side_effect=lambda record: self.records.append(dict(record)) or True,
            ),
        ]
        for item in self.patches:
            item.start()
        workspace_read_client.reset_capability_cache()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        workspace_read_client.reset_capability_cache()
        self.temp_dir.cleanup()

    def _run(self, **overrides):
        kwargs = {
            "project_name": "Demo",
            "reserving_class": "COL",
            "dataset_names": ["Paid Loss"],
        }
        kwargs.update(overrides)
        return workspace_mutation_client.run_workspace_mutation(
            "cached_dataset_delete",
            kwargs,
            local=lambda: self.fail("the mutation must not run locally"),
        )

    def test_delete_runs_on_the_gateway_and_paths_are_rebased(self) -> None:
        server_csv = str(
            self.server_root / "projects" / "Demo" / "data" / "COL" / "datasets" / "Paid Loss.csv"
        )

        def fake_delete(project_name, reserving_class, dataset_names):
            return {
                "ok": True,
                "deleted_count": 1,
                "deleted_files": [{"name": "Paid Loss.csv", "path": server_csv}],
                "index": {
                    "ok": True,
                    "files": [],
                    "folder_paths": {"data": str(self.server_root / "projects" / "Demo")},
                },
            }

        with _FakeMutationRuntime("cached_dataset_delete", fake_delete):
            response = self._run()

        expected_csv = str(
            self.client_root / "projects" / "Demo" / "data" / "COL" / "datasets" / "Paid Loss.csv"
        )
        self.assertEqual(response["deleted_files"][0]["path"], expected_csv)
        self.assertEqual(
            response["index"]["folder_paths"]["data"],
            str(self.client_root / "projects" / "Demo"),
        )
        self.assertEqual(self.records[-1]["transport"], "http_gateway")
        self.assertEqual(self.records[-1]["outcome"], "success")
        self.assertEqual(self.records[-1]["read_kind"], "mutation:cached_dataset_delete")

    def test_blocked_refusal_reaches_the_client_as_an_object(self) -> None:
        """The page switches on `error` and lists `blocked_datasets` as links."""

        blocked = {
            "error": "dataset_has_dependents",
            "message": "'Paid Loss' is used as input by other objects.",
            "blocked_datasets": [
                {
                    "dataset_name": "Paid Loss",
                    "dependents": [{"dataset_name": "Paid DFM", "method_type": "DFM"}],
                }
            ],
        }

        def refuse(**_kwargs):
            raise HTTPException(409, blocked)

        with _FakeMutationRuntime("cached_dataset_delete", refuse):
            with self.assertRaises(HTTPException) as caught:
                self._run()

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail, blocked)
        self.assertEqual(self.records[-1]["transport"], "http_gateway")
        self.assertEqual(self.records[-1]["http_status"], 409)

    def test_a_kind_not_advertised_needs_a_server_update(self) -> None:
        with patch.object(
            workspace_mutation_client,
            "gateway_supports_mutation_kind",
            return_value=False,
        ):
            with self.assertRaises(HTTPException) as caught:
                workspace_mutation_client.run_workspace_mutation(
                    "cached_dataset_delete",
                    {
                        "project_name": "Demo",
                        "reserving_class": "COL",
                        "dataset_names": ["Paid Loss"],
                    },
                    local=lambda: self.fail("a Client PC must not write the workspace itself"),
                )
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("needs updating", caught.exception.detail)
        self.assertEqual(self.records[-1]["reason"], "kind_not_advertised")

    def test_an_accepted_request_is_never_re_run_locally(self) -> None:
        """A delete the server may have applied must not be repeated here.

        A mutation whose answer was lost after the server had it may already
        have been applied, so the user is told to refresh and look.
        """

        failure = workspace_read_client.GatewayTransportFailure(
            "gateway_connection_lost", accepted=True
        )
        with patch.object(
            workspace_read_client, "post_signed_json", side_effect=failure
        ):
            with self.assertRaises(HTTPException) as caught:
                self._run()

        self.assertEqual(caught.exception.status_code, 504)
        self.assertIn("Refresh", caught.exception.detail)
        self.assertEqual(self.records[-1]["transport"], "http_gateway")
        self.assertEqual(self.records[-1]["reason"], "gateway_connection_lost")

    def test_a_request_the_contract_refuses_is_a_400(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            workspace_mutation_client.run_workspace_mutation(
                "cached_dataset_delete",
                {"project_name": "Demo", "reserving_class": "COL", "dataset_names": []},
                local=lambda: self.fail("a Client PC must not write the workspace itself"),
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_a_failure_before_the_server_could_act_is_reported(self) -> None:
        failure = workspace_read_client.GatewayTransportFailure("gateway_unreachable")
        with patch.object(
            workspace_read_client, "post_signed_json", side_effect=failure
        ):
            with self.assertRaises(HTTPException) as caught:
                self._run()
        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("can't be reached", caught.exception.detail)
        self.assertEqual(self.records[-1]["reason"], "gateway_unreachable")

    def _lose_first_answer(self):
        """Deliver the first request to the Gateway, then drop its answer."""

        real_post = workspace_read_client.post_signed_json
        sent: list[dict] = []

        def post(gateway_config, path, request_payload, *, timeout):
            sent.append(dict(request_payload))
            answer = real_post(gateway_config, path, request_payload, timeout=timeout)
            if len(sent) == 1:
                raise workspace_read_client.GatewayTransportFailure(
                    "gateway_connection_lost", accepted=True
                )
            return answer

        return patch.object(workspace_read_client, "post_signed_json", side_effect=post), sent

    def test_a_lost_answer_to_a_receipt_kind_is_replayed_not_run_again(self) -> None:
        runs: list[str] = []

        def create(source, name):
            runs.append(name)
            return {"ok": True, "created_folder": name}

        lose, sent = self._lose_first_answer()
        with _FakeMutationRuntime("project_folder_create", create), lose:
            response = workspace_mutation_client.run_workspace_mutation(
                "project_folder_create",
                {"source": "project_map", "name": "Scratch"},
                local=lambda: self.fail("the mutation must not run locally"),
                request_id="create-1",
            )

        self.assertEqual(response, {"ok": True, "created_folder": "Scratch"})
        self.assertEqual(runs, ["Scratch"])
        self.assertEqual([request["RequestId"] for request in sent], ["create-1", "create-1"])
        self.assertEqual(sent[0], sent[1])

    def test_a_lost_answer_to_an_idempotent_kind_is_not_resent(self) -> None:
        lose, sent = self._lose_first_answer()
        with _FakeMutationRuntime("cached_dataset_delete", lambda **_kwargs: {"ok": True}), lose:
            with self.assertRaises(HTTPException) as caught:
                self._run()
        self.assertEqual(caught.exception.status_code, 504)
        self.assertEqual(len(sent), 1)


class WorkspaceMutationReceiptTests(unittest.TestCase):
    """Receipt kinds against real project-folder services in a temporary root."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.projects = self.root / "projects"
        (self.projects / "Alpha" / "data").mkdir(parents=True)
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["users"] = {"alice": "alice-secret", "bob": "bob-secret"}
        gateway_main._write_json_atomic(self.root / "config" / "arcrho_gateway.json", config)
        for patcher in (
            patch.object(app_config, "PROJECT_SETTINGS_DIR", str(self.projects)),
            patch.object(workspace_read_client, "_is_server_process", return_value=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.executor = workspace_mutations.WorkspaceMutationExecutor(
            self.root,
            load_gateway_config=gateway_main._load_gateway_config,
            log=lambda _root, _message: None,
            ensure_runtime=lambda: None,
        )

    def _request(self, kind: str, kwargs: dict, *, user: str = "alice", request_id: str = "r-1") -> dict:
        return build_workspace_mutation_request(
            request_id=request_id, mutation_kind=kind, kwargs=kwargs, user_name=user
        )

    def _rename(self, new_name: str = "Beta", **overrides) -> dict:
        return self._request(
            "project_folder_rename",
            {"source": "project_map", "old_name": "Alpha", "new_name": new_name},
            **overrides,
        )

    def _receipt(self, user: str = "alice", request_id: str = "r-1") -> Path:
        return mutation_receipt_path(self.root, user, request_id)

    def test_a_repeated_rename_answers_from_its_receipt_and_is_never_applied_twice(self) -> None:
        first = self.executor.execute("alice", self._rename())
        # Put a folder back under the old name: a second real run would now
        # rename it too (or refuse, since Beta exists). The replay does neither.
        (self.projects / "Alpha").mkdir()
        second = self.executor.execute("alice", self._rename())

        self.assertEqual(first, {"ok": True, "old_folder": "Alpha", "new_folder": "Beta"})
        self.assertEqual(second, first)
        self.assertTrue((self.projects / "Alpha").is_dir())
        self.assertTrue((self.projects / "Beta" / "data").is_dir())
        receipt = json.loads(self._receipt().read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "success")
        self.assertEqual(receipt["mutation_kind"], "project_folder_rename")

    def test_a_different_change_under_the_same_id_is_refused(self) -> None:
        self.executor.execute("alice", self._rename())
        with self.assertRaises(workspace_reads.WorkspaceReadRefusal) as caught:
            self.executor.execute("alice", self._rename("Gamma"))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse((self.projects / "Gamma").exists())

    def test_receipts_are_kept_per_user(self) -> None:
        self.executor.execute("alice", self._rename())
        (self.projects / "Alpha").mkdir()
        answer = self.executor.execute("bob", self._rename("Gamma", user="bob"))
        self.assertEqual(answer["new_folder"], "Gamma")
        self.assertTrue(self._receipt("bob").is_file())

    def test_a_refusal_is_replayed_without_running_again(self) -> None:
        runs: list[str] = []
        real_create = importlib.import_module(
            "app_server.services.project_settings_service"
        ).create_project_folder

        def create(source, name):
            runs.append(name)
            return real_create(source, name)

        request = self._request("project_folder_create", {"source": "project_map", "name": "Alpha"})
        with _FakeMutationRuntime("project_folder_create", create):
            for _attempt in range(2):
                with self.assertRaises(workspace_reads.WorkspaceReadRefusal) as caught:
                    self.executor.execute("alice", request)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertIn("already exists", caught.exception.detail)
        self.assertEqual(runs, ["Alpha"])

    def test_an_unfinished_receipt_is_reported_not_run(self) -> None:
        request = self._rename()
        gateway_main._write_json_atomic(
            self._receipt(),
            {"receipt_version": 1, "request_sha256": request_sha256(request), "state": "accepted"},
        )
        with self.assertRaises(workspace_reads.WorkspaceReadRefusal) as caught:
            self.executor.execute("alice", request)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue((self.projects / "Alpha").is_dir())

    def test_an_idempotent_kind_keeps_no_receipt(self) -> None:
        with _FakeMutationRuntime("generated_dataset_cache_clear", lambda **_kwargs: {"ok": True}):
            self.executor.execute(
                "alice",
                self._request("generated_dataset_cache_clear", {"source": "project_map", "project_name": "Alpha"}),
            )
        self.assertFalse((self.root / "runtime").exists())

    def test_startup_expires_old_terminal_mutation_receipts(self) -> None:
        self.executor.execute("alice", self._rename())
        unfinished = self._receipt(request_id="r-2")
        gateway_main._write_json_atomic(unfinished, {"state": "accepted"})
        old = time.time() - 48 * 3600
        for path in (self._receipt(), unfinished):
            os.utime(path, (old, old))

        self.assertEqual(gateway_main._prune_terminal_receipts(self.root, 24), 1)
        self.assertFalse(self._receipt().exists())
        self.assertTrue(unfinished.exists())


if __name__ == "__main__":
    unittest.main()
