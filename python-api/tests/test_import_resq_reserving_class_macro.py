from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
import contextlib
from unittest.mock import patch


# Every test temp directory lives under one gitignored folder at the
# repository root, so a suite that dies before teardown cannot scatter
# tmp folders beside the code.
TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

_MACRO_PATH = (
    Path(__file__).resolve().parents[1]
    / "macros"
    / "import_resq_reserving_class.py"
)
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "server-components"
    / "src"
    / "arcrho_bridge"
    / "resq_reserving_class_import_contract.json"
)
_REQUEST_ID = "a1b2c3d4e5f6478899aabbccddeeff00"
# The fixtures answer with the version the canonical contract names, so a
# contract bump moves the whole file at once.
_CONTRACT_VERSION = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))["contract_version"]
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


def load_macro_module():
    spec = importlib.util.spec_from_file_location(
        "import_resq_reserving_class_macro_under_test",
        _MACRO_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the ResQ reserving-class import macro.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # A missing Bridge is judged after a silence, not a look; keep it short here.
    module.BRIDGE_SILENCE_LIMIT_SEC = 0.05
    module.POLL_INTERVAL_SEC = 0.01
    return module


def _look(*, live: bool = True, status: dict | None = None, status_age: float = 0.0) -> dict:
    """One scripted liveness look, as the hosted read would report it."""

    return {
        "observed_at": 0.0,
        "workers": [{"name": "worker.json", "age_sec": 0.4 if live else 9.6, "live": live}],
        "request": {
            "request_id": _REQUEST_ID,
            "found": status is not None,
            "age_sec": status_age if status is not None else None,
            "status": status,
        },
    }


def _processing_status() -> dict:
    return {"contract_version": _CONTRACT_VERSION, "status": "processing", "request_id": _REQUEST_ID}


def _success_status() -> dict:
    return {
        "contract_version": _CONTRACT_VERSION,
        "status": "success",
        "request_id": _REQUEST_ID,
        "result": {"datasets_imported": 1, "errors": 0},
    }


class _Progress:
    def __init__(self):
        self.total = 0
        self.completed = 0
        self.updates = []
        self.closed = False

    def update(self, **kwargs):
        self.updates.append(kwargs)
        self.total = int(kwargs.get("total", self.total) or 0)
        self.completed = int(kwargs.get("completed", self.completed) or 0)

    def close(self, **_kwargs):
        self.closed = True


class _UI:
    def __init__(self, button_script=None):
        self.messages = []
        self.progress_calls = []
        self.reload_calls = []
        # Buttons returned by successive message boxes; with no script a
        # prompt answers with no button at all, which every question reads
        # as Cancel.
        self.button_script = list(button_script or [])
        self.project_instance = types.SimpleNamespace(
            context=lambda **_kwargs: {
                "projectName": "Demo",
                "selectedPath": r"Auto\PP",
            },
            reload_dataset_table=self._reload_dataset_table,
        )

    def _reload_dataset_table(self, **kwargs):
        self.reload_calls.append(kwargs)
        return {"refreshed": True}

    def message_box(self, message, **kwargs):
        self.messages.append((message, kwargs))
        if kwargs.get("buttons") and self.button_script:
            return {"ok": True, "button": self.button_script.pop(0)}
        return {"ok": True}

    def progress_bar(self, **kwargs):
        self.progress_calls.append(kwargs)
        return _Progress()


class ImportResqReservingClassMacroTests(unittest.TestCase):
    def setUp(self):
        self.module = load_macro_module()
        self.tempdir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.tempdir.cleanup)
        self.server_root = Path(self.tempdir.name)
        self.ui = _UI()
        self.review = {"status": "reviewed", "accepted": True, "names": None}
        self.review_calls = []
        self.api_module = types.ModuleType("arcrho_api")
        self.api_module.ArcRhoUI = lambda: self.ui
        self.api_module.get_server_root = lambda **_kwargs: self.server_root
        self.published = []
        self.publish_error = None

    def _app_server_modules(self) -> dict:
        """The app server's hosted mutation, standing in for the Gateway.

        It records what the macro sent and writes the request where the server
        would, so the rest of the macro sees the queue it expects.
        """

        # Same signature as app_server.services.workspace_mutation_client, so an
        # argument the app no longer accepts fails here as it would in Arco.
        def run_workspace_mutation(kind, kwargs, *, local, request_id=None):
            self.published.append({"kind": kind, "kwargs": kwargs})
            if self.publish_error is not None:
                raise self.publish_error
            request_path, _ = self.module._request_paths(self.server_root, kwargs["request_id"])
            request_path.parent.mkdir(parents=True, exist_ok=True)
            request_path.write_text(json.dumps(kwargs["request"]), encoding="utf-8")
            return {"ok": True, "request_id": kwargs["request_id"], "resumed": False}

        services = types.ModuleType("app_server.services")
        services.workspace_mutation_client = types.SimpleNamespace(run_workspace_mutation=run_workspace_mutation)
        services.resq_import_queue_service = types.SimpleNamespace(publish_resq_import_request=None)
        package = types.ModuleType("app_server")
        package.services = services
        return {"app_server": package, "app_server.services": services}

    def _write_worker(
        self,
        *,
        name: str = "worker.json",
        role: str = "bridge_worker",
        gui_running: bool = True,
        age_sec: float = 0.0,
    ) -> Path:
        path = self.server_root / self.module.BRIDGE_WORKER_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"Role": role, "ResQGuiRunning": gui_running}),
            encoding="utf-8",
        )
        if age_sec:
            timestamp = time.time() - age_sec
            os.utime(path, (timestamp, timestamp))
        return path

    def _macro_modules(self):
        """The macro's imports, with the shared transfer review answered.

        The review opens a window against a live Bridge, which no unit test
        has; ``self.review`` is the answer it returns, accepting everything
        unless a test says otherwise, and ``self.review_calls`` records what
        the macro asked for.
        """

        def review(_ui, _root, project_name, rc_path, *, overwrite):
            self.review_calls.append(
                {"project_name": project_name, "rc_path": rc_path, "overwrite": overwrite}
            )
            return dict(self.review)

        stack = contextlib.ExitStack()
        stack.enter_context(patch.dict(sys.modules, {"arcrho_api": self.api_module, **self._app_server_modules()}))
        stack.enter_context(patch.object(self.module, "review_import_plan", side_effect=review))
        return stack

    def _contract(self) -> dict:
        with _CONTRACT_PATH.open(encoding="utf-8") as stream:
            return json.load(stream)

    def _publish_status(self, status: dict):
        original_publish = self.module.publish_import_request

        def publish_and_respond(**kwargs):
            request_path = original_publish(**kwargs)
            _, status_path = self.module._request_paths(
                kwargs["server_root"],
                kwargs["request_id"],
            )
            status_path.parent.mkdir(parents=True, exist_ok=True)
            status_path.write_text(json.dumps(status), encoding="utf-8")
            return request_path

        return publish_and_respond

    def test_the_request_is_published_through_the_gateway_and_never_over_the_share(self):
        request_id, payload = self.module.create_import_request(project_name="Demo", rc_path=r"Auto\PP")
        with patch.dict(sys.modules, self._app_server_modules()):
            request_path = self.module.publish_import_request(
                server_root=self.server_root, request_id=request_id, payload=payload
            )
        self.assertEqual(
            self.published,
            [{
                "kind": "resq_import_request_publish",
                "kwargs": {
                    "project_name": "Demo",
                    "reserving_class": r"Auto\PP",
                    "request_id": request_id,
                    "request": payload,
                },
            }],
        )
        self.assertEqual(json.loads(request_path.read_text(encoding="utf-8")), payload)

    def test_a_request_the_gateway_cannot_take_stops_the_import(self):
        request_id, payload = self.module.create_import_request(project_name="Demo", rc_path=r"Auto\PP")
        self.publish_error = RuntimeError("Arco Gateway could not answer this request.")
        with patch.dict(sys.modules, self._app_server_modules()):
            with self.assertRaises(self.module.BridgeRequestError) as raised:
                self.module.publish_import_request(server_root=self.server_root, request_id=request_id, payload=payload)
        self.assertIn("Arco Gateway could not answer", str(raised.exception))
        self.assertFalse((self.server_root / self.module.REQUEST_RELATIVE_DIR).exists())

    def test_embedded_adapter_matches_canonical_bridge_contract(self):
        contract = self._contract()

        self.assertEqual(self.module.REQUEST_FUNCTION, contract["function"])
        self.assertEqual(self.module.CONTRACT_VERSION, contract["contract_version"])
        self.assertEqual(
            tuple(self.module.REQUEST_RELATIVE_DIR.parts),
            tuple(contract["request_relative_dir"]),
        )
        self.assertEqual(
            tuple(self.module.STATUS_RELATIVE_DIR.parts),
            tuple(contract["status_relative_dir"]),
        )
        self.assertEqual(
            tuple(self.module.BRIDGE_WORKER_DIR.parts),
            tuple(contract["worker_heartbeat_relative_dir"]),
        )
        self.assertEqual(self.module.BRIDGE_WORKER_ROLE, contract["worker_role"])
        self.assertEqual(
            self.module.BRIDGE_WORKER_MAX_AGE_SEC,
            contract["worker_heartbeat_max_age_seconds"],
        )
        self.assertEqual(
            self.module.REQUIRED_REQUEST_FIELDS,
            tuple(contract["required_request_fields"]),
        )
        self.assertEqual(
            self.module.FORBIDDEN_PATH_FIELDS,
            tuple(contract["forbidden_path_fields"]),
        )
        self.assertEqual(
            self.module.ALLOWED_EXPORT_MODES,
            frozenset(contract["allowed_export_modes"]),
        )
        self.assertEqual(
            self.module.ALLOWED_IMPORT_POLICIES,
            frozenset(contract["allowed_import_policies"]),
        )
        self.assertEqual(
            self.module.STATUS_VALUES,
            frozenset(contract["status_values"]),
        )

    def test_logical_identifiers_match_bridge_request_validation(self):
        self.assertEqual(self.module._logical_project_name("Demo"), "Demo")
        self.assertEqual(self.module._logical_rc_path("Auto/PP"), r"Auto\PP")

        for project_name in ("Demo:Archive", "Demo/Archive", r"Demo\Archive", ".", ".."):
            with self.subTest(project_name=project_name):
                with self.assertRaises(ValueError):
                    self.module._logical_project_name(project_name)

        invalid_paths = (
            "",
            r"\Auto\PP",
            r"Auto\\PP",
            r"Auto\.\PP",
            r"Auto\..\PP",
            "Auto:PP",
            "Auto\x00PP",
            "Auto\\PP\\",
        )
        for rc_path in invalid_paths:
            with self.subTest(rc_path=rc_path):
                with self.assertRaises(ValueError):
                    self.module._logical_rc_path(rc_path)

    def test_unavailable_bridge_stops_before_progress_or_request_publication(self):
        with self._macro_modules():
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "bridge_unavailable")
        self.assertEqual(self.ui.progress_calls, [])
        self.assertFalse((self.server_root / self.module.REQUEST_ROOT).exists())
        message, options = self.ui.messages[-1]
        self.assertIn("import was not started", message)
        self.assertEqual(options["title"], "Arco Bridge Unavailable")
        self.assertEqual(options["kind"], "error")

    def test_progress_status_exposes_indeterminate_and_determinate_phase_labels(self):
        progress = _Progress()

        self.module._update_progress_from_status(
            progress,
            {
                "status": "processing",
                "progress": {
                    "event": "inventory",
                    "message": "Scanning ResQ triangles: 17 found",
                },
            },
        )
        self.assertEqual(progress.total, 0)
        self.assertEqual(progress.completed, 0)
        self.assertEqual(progress.updates[-1]["label"], "Scanning ResQ triangles: 17 found")
        self.assertEqual(progress.updates[-1]["detail"], "Scanning ResQ triangles: 17 found")

        self.module._update_progress_from_status(
            progress,
            {
                "status": "processing",
                "progress": {
                    "event": "engine_wait",
                    "message": "Waiting for Arco Engine result 3 of 8: Paid Loss",
                    "completed": 41,
                    "total": 130,
                },
            },
        )
        self.assertEqual(progress.total, 130)
        self.assertEqual(progress.completed, 41)
        self.assertEqual(
            progress.updates[-1]["label"],
            "Waiting for Arco Engine result 3 of 8: Paid Loss",
        )

    def test_non_dfm_macro_context_falls_back_to_project_instance_context(self):
        self._write_worker()
        status = {
            "contract_version": _CONTRACT_VERSION,
            "status": "success",
            "updated_at": "2026-07-26T10:00:00",
            "request_id": _REQUEST_ID,
            "result": {"datasets_imported": 1, "errors": 0},
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)
        non_dfm_context = {
            "available": False,
            "pageType": "project_instance",
            "error": "Open or activate a DFM tab/window before running a macro.",
        }

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=self._publish_status(status)),
        ):
            result = self.module.run_macro(active_context=non_dfm_context)

        self.assertTrue(result["success"])
        request_path, _ = self.module._request_paths(self.server_root, _REQUEST_ID)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ProjectName"], "Demo")
        self.assertEqual(payload["Path"], r"Auto\PP")

    def test_stale_or_non_resq_worker_does_not_pass_hard_preflight(self):
        self._write_worker(age_sec=self.module.BRIDGE_WORKER_MAX_AGE_SEC + 1)
        self._write_worker(name="not-resq.json", gui_running=False)

        with self._macro_modules():
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "bridge_unavailable")
        self.assertFalse((self.server_root / self.module.REQUEST_ROOT).exists())

    def test_unclaimed_request_fails_promptly_with_a_bridge_restart_message(self):
        self._write_worker()

        with self.assertRaisesRegex(self.module.BridgeRequestError, "did not claim request"):
            self.module.wait_for_import_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                timeout_sec=1,
                poll_interval_sec=0.01,
                claim_timeout_sec=0.01,
            )

    def test_publishes_location_independent_request_and_waits_for_success_status(self):
        self._write_worker()
        status = {
            "contract_version": _CONTRACT_VERSION,
            "status": "success",
            "updated_at": "2026-07-26T10:00:00",
            "request_id": _REQUEST_ID,
            "result": {"datasets_imported": 2, "methods_imported": 1, "errors": 0},
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)
        publish_and_respond = self._publish_status(status)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=publish_and_respond),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        self.assertEqual(result["request_id"], _REQUEST_ID)
        self.assertEqual(len(self.ui.reload_calls), 1)
        request_path, status_path = self.module._request_paths(self.server_root, _REQUEST_ID)
        self.assertTrue(request_path.is_file())
        self.assertTrue(status_path.is_file())
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload),
            {
                "Function",
                "ContractVersion",
                "RequestId",
                "ProjectName",
                "Path",
                "UserName",
                "ExportMode",
                "ImportPolicy",
            },
        )
        self.assertEqual(payload["Function"], "ImportResQReservingClass")
        self.assertEqual(payload["ImportPolicy"], "overwrite")
        self.assertEqual(payload["ContractVersion"], _CONTRACT_VERSION)
        self.assertEqual(payload["RequestId"], _REQUEST_ID)
        self.assertEqual(payload["ProjectName"], "Demo")
        self.assertEqual(payload["Path"], r"Auto\PP")
        self.assertTrue(payload["UserName"])
        self.assertEqual(payload["ExportMode"], "configured")
        self.assertNotIn("StatusPath", payload)
        self.assertNotIn(str(self.server_root), json.dumps(payload))
        self.assertFalse(request_path.with_name(f".{_REQUEST_ID}.tmp").exists())
        self.assertIn("Datasets imported: 2", result["message"])
        self.assertIn("Methods imported: 1", result["message"])

    def test_the_import_always_overwrites_without_asking_which_policy(self):
        self._write_worker()
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_import_request",
                side_effect=self._publish_status(_success_status()),
            ),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        request_path, _ = self.module._request_paths(self.server_root, _REQUEST_ID)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ImportPolicy"], "overwrite")
        # No policy question and, with nothing newer in ArcRho, no second look.
        prompts = [kwargs for _msg, kwargs in self.ui.messages if kwargs.get("buttons")]
        self.assertEqual(prompts, [])

    def _preview_with_a_newer_arcrho_copy(self):
        return [
            {
                "id": "paid loss",
                "name": "Paid Loss",
                "kind": "Dataset",
                "dataset_type": "Paid Loss",
                "presence": "both",
                "newer_side": "arcrho",
                "transfer_supported": True,
            },
            {
                "id": "d 18 - bs paid dfm",
                "name": "D 18 - BS Paid DFM",
                "kind": "DFM",
                "method_name": "D 18 - BS Paid DFM",
                "presence": "both",
                "newer_side": "arcrho",
                "export_review": {"changed": "resq"},
                "transfer_supported": True,
            },
            {
                "id": "incurred loss",
                "name": "Incurred Loss",
                "kind": "Dataset",
                "dataset_type": "Incurred Loss",
                "presence": "both",
                "newer_side": "resq",
                "transfer_supported": True,
            },
        ]

    def test_ticked_items_newer_in_arcrho_are_listed_with_links_before_the_overwrite(self):
        self._write_worker()
        self.ui = _UI(button_script=["Overwrite"])
        self.review = {
            "status": "reviewed",
            "accepted": True,
            "names": ["Paid Loss", "D 18 - BS Paid DFM", "Incurred Loss"],
            "preview": self._preview_with_a_newer_arcrho_copy(),
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_import_request",
                side_effect=self._publish_status(_success_status()),
            ),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        prompts = [(msg, kwargs) for msg, kwargs in self.ui.messages if kwargs.get("buttons")]
        self.assertEqual(len(prompts), 1)
        message, options = prompts[0]
        self.assertIn("1 Arco copy is newer than the ResQ version", message)
        self.assertEqual(options["buttons"], ["Overwrite", "Cancel"])
        self.assertEqual(options["kind"], "warning")
        self.assertEqual(options["presentation"], "floating")
        # The DFM's ArcRho edit was already recorded as a ResQ change by the
        # baseline, so only the dataset with a real ArcRho edit is listed.
        self.assertEqual(
            options["links"],
            [{
                "label": "Paid Loss",
                "kind": "Dataset",
                "args": {"datasetName": "Paid Loss", "datasetTypeName": "Paid Loss"},
            }],
        )
        request_path, _ = self.module._request_paths(self.server_root, _REQUEST_ID)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["ImportPolicy"], "overwrite")

    def test_an_item_left_unticked_is_not_held_against_the_overwrite(self):
        self._write_worker()
        self.review = {
            "status": "reviewed",
            "accepted": True,
            "names": ["Incurred Loss"],
            "preview": self._preview_with_a_newer_arcrho_copy(),
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_import_request",
                side_effect=self._publish_status(_success_status()),
            ),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        prompts = [kwargs for _msg, kwargs in self.ui.messages if kwargs.get("buttons")]
        self.assertEqual(prompts, [])

    def test_a_declined_second_look_publishes_nothing(self):
        self._write_worker()
        self.ui = _UI(button_script=["Cancel"])
        self.review = {
            "status": "reviewed",
            "accepted": True,
            "names": ["Paid Loss"],
            "preview": self._preview_with_a_newer_arcrho_copy(),
        }

        with self._macro_modules():
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "cancelled")
        self.assertFalse((self.server_root / self.module.REQUEST_ROOT / "requests").exists())

    def test_the_ticked_names_travel_in_the_request_payload(self):
        self._write_worker()
        self.review = {"status": "reviewed", "accepted": True, "names": ["Paid Loss", "D 18 - BS Paid DFM"]}
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_import_request",
                side_effect=self._publish_status(_success_status()),
            ),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        request_path, _ = self.module._request_paths(self.server_root, _REQUEST_ID)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["SelectedNames"], ["Paid Loss", "D 18 - BS Paid DFM"])

    def test_a_review_that_ticked_nothing_publishes_no_import(self):
        self._write_worker()
        self.review = {"status": "reviewed", "accepted": True, "names": []}

        with self._macro_modules():
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "empty_selection")
        self.assertFalse((self.server_root / self.module.REQUEST_ROOT / "requests").exists())

    def test_a_cancelled_review_publishes_no_import(self):
        self._write_worker()
        self.review = {"status": "reviewed", "accepted": False, "names": []}

        with self._macro_modules():
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "cancelled")
        self.assertFalse((self.server_root / self.module.REQUEST_ROOT / "requests").exists())

    def test_the_review_is_told_that_the_run_overwrites(self):
        self._write_worker()
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(
                self.module,
                "publish_import_request",
                side_effect=self._publish_status(_success_status()),
            ),
        ):
            self.module.run_macro()

        self.assertEqual(
            self.review_calls,
            [{"project_name": "Demo", "rc_path": r"Auto\PP", "overwrite": True}],
        )

    def test_a_comparison_that_failed_asks_before_importing_everything(self):
        self.ui = _UI(button_script=["Import Anyway"])

        self.assertTrue(self.module.confirm_without_preview(self.ui, RuntimeError("ResQ is busy")))

        message, options = self.ui.messages[-1]
        self.assertIn("ResQ is busy", message)
        self.assertIn("everything ResQ offers", message)
        self.assertEqual(options["buttons"], ["Import Anyway", "Cancel"])

    def test_a_selection_saved_by_the_bridge_is_reported_in_the_completion(self):
        message = self.module._success_message(
            "Demo",
            r"Auto\PP",
            {"result": {"datasets_imported": 2, "errors": 0, "selection": {"saved": 2, "error": ""}}},
        )

        self.assertIn("Saved the 2 selected item(s) as the default for the next import.", message)

    def test_a_selection_the_bridge_could_not_save_is_reported_as_such(self):
        message = self.module._success_message(
            "Demo",
            r"Auto\PP",
            {"result": {"selection": {"saved": 0, "error": "The share was read-only."}}},
        )

        self.assertIn("The selection was not saved", message)
        self.assertIn("The share was read-only.", message)

    def test_a_success_status_with_skipped_items_lists_them_by_name(self):
        self._write_worker()
        self.ui = _UI(button_script=["Merge"])
        status = {
            "contract_version": _CONTRACT_VERSION,
            "status": "success",
            "updated_at": "2026-08-21T10:00:00",
            "request_id": _REQUEST_ID,
            "result": {
                "datasets_imported": 4,
                "errors": 1,
                "error_details": [{
                    "kind": "vector",
                    "name": "G 41 - BF Paid",
                    "message": (
                        "The Perc Developed input does not name a ResQ dataset; "
                        "its selection is blank or broken."
                    ),
                }],
            },
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=self._publish_status(status)),
        ):
            result = self.module.run_macro()

        # The class committed with one item skipped; the completion box names
        # the skipped item and stays on screen as a warning.
        self.assertEqual(len(self.ui.reload_calls), 1)
        message, options = self.ui.messages[-1]
        self.assertIn("Import from ResQ completed.", message)
        self.assertIn("Skipped (could not be exported from ResQ", message)
        self.assertIn("vector G 41 - BF Paid: The Perc Developed input", message)
        self.assertEqual(options["kind"], "warning")
        self.assertIsNone(options.get("auto_close_ms"))

    def test_an_engine_result_that_differs_from_resq_is_shown_as_a_warning(self):
        self._write_worker()
        self.ui = _UI(button_script=["Merge"])
        status = {
            "contract_version": _CONTRACT_VERSION,
            "status": "success",
            "updated_at": "2026-08-21T10:00:00",
            "request_id": _REQUEST_ID,
            "result": {
                "datasets_imported": 4,
                "errors": 0,
                "error_details": [],
                "engine_parity_mismatches": 1,
                "engine_parity_warnings": [{
                    "kind": "triangle",
                    "name": "Paid Loss",
                    "message": (
                        "3 cell(s) differ from ResQ at 2 decimal places; first at origin 4, "
                        "development 2: ResQ 12,345.67, Arco Engine 12,345.70."
                    ),
                }],
            },
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=self._publish_status(status)),
        ):
            result = self.module.run_macro()

        # The class committed and the Engine result was kept, but the box warns,
        # names the dataset and its first differing cell, and stays on screen.
        self.assertTrue(result["success"])
        message, options = self.ui.messages[-1]
        self.assertIn("Import from ResQ completed.", message)
        self.assertIn("WARNING - Arco Engine results that differ from ResQ at two decimal places", message)
        self.assertIn("- triangle Paid Loss: 3 cell(s) differ from ResQ", message)
        self.assertNotIn("Skipped (could not be exported", message)
        self.assertEqual(options["kind"], "warning")
        self.assertIsNone(options.get("auto_close_ms"))

    def test_bridge_error_status_is_reported_without_reloading_dataset_table(self):
        self._write_worker()
        status = {
            "contract_version": _CONTRACT_VERSION,
            "status": "error",
            "updated_at": "2026-07-26T10:00:00",
            "request_id": _REQUEST_ID,
            "message": "ResQ import failed safely.",
            "result": {
                "errors": 1,
                "error_details": [{
                    "kind": "dfm",
                    "name": "Broken DFM",
                    "message": "Missing input triangle.",
                }],
            },
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=self._publish_status(status)),
        ):
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(result["request_id"], _REQUEST_ID)
        self.assertEqual(self.ui.reload_calls, [])
        message, options = self.ui.messages[-1]
        self.assertIn("ResQ import failed safely.", message)
        self.assertIn("dfm Broken DFM: Missing input triangle.", message)
        self.assertEqual(options["kind"], "error")

    def test_incompatible_status_contract_is_not_accepted_as_success(self):
        self._write_worker()
        status = {
            "contract_version": 99,
            "status": "success",
            "updated_at": "2026-07-26T10:00:00",
            "request_id": _REQUEST_ID,
        }
        request_uuid = types.SimpleNamespace(hex=_REQUEST_ID)

        with (
            self._macro_modules(),
            patch.object(self.module.uuid, "uuid4", return_value=request_uuid),
            patch.object(self.module, "publish_import_request", side_effect=self._publish_status(status)),
        ):
            result = self.module.run_macro()

        self.assertFalse(result["success"])
        self.assertEqual(self.ui.reload_calls, [])
        self.assertIn("unsupported status contract version", result["message"])

    def _scripted_looks(self, *looks: dict | None):
        """Answer each liveness look from the script, repeating the last one."""

        remaining = list(looks)

        def observe(_server_root, *, queue, request_id=""):
            self.assertEqual(queue, "import")
            return remaining.pop(0) if len(remaining) > 1 else remaining[0]

        return patch.object(self.module, "observe_bridge_liveness", side_effect=observe)

    def test_a_stale_heartbeat_reading_mid_import_does_not_abandon_the_request(self):
        # The first looks are what a lagging drive cache produces: a heartbeat
        # nine seconds old and a status file untouched for twelve. Neither is
        # a verdict; the import then reports success.
        looks = self._scripted_looks(
            _look(live=False, status=_processing_status(), status_age=12.0),
            _look(live=False, status=_processing_status(), status_age=12.0),
            _look(live=True, status=_success_status()),
        )

        with looks:
            status = self.module.wait_for_import_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                timeout_sec=5,
                poll_interval_sec=0.001,
            )

        self.assertEqual(status["status"], "success")

    def test_a_fresh_status_file_is_life_even_when_no_heartbeat_looks_usable(self):
        self.module.BRIDGE_SILENCE_LIMIT_SEC = 0.02
        looks = self._scripted_looks(
            *[_look(live=False, status=_processing_status(), status_age=0.8)] * 6,
            _look(live=False, status=_success_status(), status_age=0.5),
        )

        with looks:
            status = self.module.wait_for_import_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                timeout_sec=5,
                poll_interval_sec=0.01,
            )

        self.assertEqual(status["status"], "success")

    def test_silence_past_the_limit_abandons_the_wait_without_claiming_the_data_unchanged(self):
        looks = self._scripted_looks(
            _look(live=False, status=_processing_status(), status_age=12.0),
        )

        with looks, self.assertRaises(self.module.BridgeUnavailableError) as raised:
            self.module.wait_for_import_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                timeout_sec=5,
                poll_interval_sec=0.01,
            )

        message = str(raised.exception)
        self.assertIn("was abandoned", message)
        self.assertIn("consecutive checks", message)
        self.assertIn("worker.json 9.6 s old (not usable)", message)
        self.assertIn("status file 12.0 s old", message)
        self.assertIn("Whether the import finished is unknown", message)
        self.assertNotIn("left unchanged", message)

    def test_a_look_that_fails_is_a_silent_look_not_a_crash(self):
        calls = []

        def observe(*_args, **_kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise RuntimeError("gateway hiccup")
            return _look(live=True, status=_success_status())

        with patch.object(self.module, "observe_bridge_liveness", side_effect=observe):
            status = self.module.wait_for_import_result(
                server_root=self.server_root,
                request_id=_REQUEST_ID,
                timeout_sec=5,
                poll_interval_sec=0.001,
            )

        self.assertEqual(status["status"], "success")
        self.assertEqual(len(calls), 3)

    def test_the_preflight_waits_out_a_short_silence_before_refusing(self):
        looks = self._scripted_looks(_look(live=False), _look(live=False), _look(live=True))

        with looks:
            workers = self.module.require_live_bridge_workers(self.server_root)

        self.assertEqual(workers, ("worker.json",))

    def _write_class_files(self, method_names: list[str], dataset_names: list[str]) -> Path:
        rc_dir = (
            self.server_root
            / "projects"
            / "Demo"
            / "data"
            / self.module.reserving_class_folder_name(r"Auto\PP")
        )
        (rc_dir / "methods").mkdir(parents=True, exist_ok=True)
        for name in method_names:
            (rc_dir / "methods" / name).write_text("{}", encoding="utf-8")
        (rc_dir / "sidecars").mkdir(parents=True, exist_ok=True)
        (rc_dir / "datasets").mkdir(parents=True, exist_ok=True)
        for name in dataset_names:
            (rc_dir / "sidecars" / f"{name}.json").write_text(
                json.dumps({"source_kind": "input", "csv_file": f"{name}@12.csv"}),
                encoding="utf-8",
            )
            (rc_dir / "datasets" / f"{name}@12.csv").write_text("origin\n2025\n", encoding="utf-8")
        return rc_dir

    def test_the_class_is_copied_before_the_request_is_published(self):
        self._write_worker()
        self._write_class_files(["DFM@A.json", "BF@B.json"], ["Accounting Cutoff"])
        backed_up_when_published: list[list[str]] = []
        publish_and_respond = self._publish_status(_success_status())

        def publish(**kwargs):
            class_dir = (
                self.server_root
                / self.module.IMPORT_BACKUP_RELATIVE_DIR
                / "Demo"
                / self.module.reserving_class_folder_name(r"Auto\PP")
            )
            backed_up_when_published.append(
                sorted(
                    str(item.relative_to(class_dir).as_posix())
                    for item in next(class_dir.iterdir()).rglob("*")
                    if item.is_file()
                )
                if class_dir.is_dir()
                else []
            )
            return publish_and_respond(**kwargs)

        with (
            self._macro_modules(),
            patch.object(
                self.module.uuid, "uuid4", return_value=types.SimpleNamespace(hex=_REQUEST_ID)
            ),
            patch.object(self.module, "publish_import_request", side_effect=publish),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        # Every file was already in place when the Bridge request went out.
        published = [name.split("/", 1)[1] for name in backed_up_when_published[0]]
        self.assertEqual(
            sorted(published),
            [
                "backup.json",
                "datasets/Accounting Cutoff@12.csv",
                "methods/BF@B.json",
                "methods/DFM@A.json",
                "sidecars/Accounting Cutoff.json",
            ],
        )
        self.assertEqual(result["backup"]["methods"], 2)
        self.assertEqual(result["backup"]["datasets"], 1)
        self.assertIn("Backed up 2 method(s) and 1 dataset(s)", result["message"])

    def test_a_failed_backup_warns_in_the_completion_box_and_still_imports(self):
        self._write_worker()
        self._write_class_files(["DFM@A.json"], [])
        publish_and_respond = self._publish_status(_success_status())

        with (
            self._macro_modules(),
            patch.object(
                self.module.uuid, "uuid4", return_value=types.SimpleNamespace(hex=_REQUEST_ID)
            ),
            patch.object(self.module, "publish_import_request", side_effect=publish_and_respond),
            patch.object(self.module.resq_import_backup.shutil, "copy2", side_effect=OSError("share offline")),
        ):
            result = self.module.run_macro()

        self.assertTrue(result["success"])
        self.assertIn("share offline", result["backup"]["error"])
        message, kwargs = self.ui.messages[-1]
        self.assertIn("no restore point", message)
        self.assertEqual(kwargs["kind"], "warning")
        self.assertIsNone(kwargs["auto_close_ms"])


class ReservingClassBackupTests(unittest.TestCase):
    """The copy taken of a reserving class before an import rewrites it."""

    def setUp(self):
        self.module = load_macro_module()
        self.tempdir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.tempdir.cleanup)
        self.server_root = Path(self.tempdir.name)
        # The copy is taken on this machine's disk, as outside the app,
        # whatever an earlier test in the same run imported.
        outside_the_app = patch.dict(sys.modules, {"app_server.services": None})
        outside_the_app.start()
        self.addCleanup(outside_the_app.stop)

    def _write_class(
        self,
        rc_path: str,
        method_names: list[str],
        *,
        datasets: list[tuple[str, str]] | None = None,
        folder: str = "",
    ) -> Path:
        """One class folder; ``datasets`` pairs a dataset name with its kind."""

        rc_dir = (
            self.server_root
            / "projects"
            / "Demo"
            / "data"
            / (folder or self.module.reserving_class_folder_name(rc_path))
        )
        (rc_dir / "methods").mkdir(parents=True, exist_ok=True)
        for index, name in enumerate(method_names):
            (rc_dir / "methods" / name).write_text(
                json.dumps({"name": name, "value": index}), encoding="utf-8"
            )
        (rc_dir / "sidecars").mkdir(parents=True, exist_ok=True)
        (rc_dir / "datasets").mkdir(parents=True, exist_ok=True)
        for name, source_kind in datasets or []:
            data_file = f"{name}@12.csv"
            (rc_dir / "sidecars" / f"{name}.json").write_text(
                json.dumps(
                    {
                        "dataset_name": name,
                        "source_kind": source_kind,
                        "csv_file": data_file,
                    }
                ),
                encoding="utf-8",
            )
            (rc_dir / "datasets" / data_file).write_text(
                f"origin,{name}\n2025,1\n", encoding="utf-8"
            )
        rc_dir.joinpath("index.json").write_text(
            json.dumps({"reserving_class": rc_path}), encoding="utf-8"
        )
        return rc_dir

    def test_the_folder_name_matches_the_apps_reserving_class_folder_rule(self):
        self.assertEqual(
            self.module.reserving_class_folder_name(r"HPPREF\HO+DF\NJ\Legacy\HOL"),
            "HPPREF_%5C_HO+DF_%5C_NJ_%5C_Legacy_%5C_HOL",
        )
        self.assertEqual(
            self.module.reserving_class_folder_name("Auto/PP"),
            "Auto_%2F_PP",
        )
        # A folder name Windows would refuse to keep as typed: each trailing
        # dot or space becomes a caret, as the app server's own rule does.
        self.assertEqual(self.module.reserving_class_folder_name("Auto ."), "Auto^^")
        self.assertEqual(self.module.reserving_class_folder_name(""), "ReservingClass")

    def test_the_class_is_copied_in_its_own_layout_with_a_manifest_beside_it(self):
        rc_dir = self._write_class(
            r"Auto\PP",
            ["DFM@A.json", "BF@B.json"],
            datasets=[
                ("Accounting Cutoff", "input"),
                ("Prior Qtr Indicated", "input"),
                ("Selected Ultimate", "calculated"),
                ("A - Paid DFM", "dfm"),
                ("Net Loss--Paid", "engine"),
            ],
        )

        backup = self.module.backup_reserving_class(
            self.server_root, "Demo", r"Auto\PP", import_policy="overwrite"
        )

        self.assertEqual(backup["error"], "")
        self.assertEqual(backup["methods"], 2)
        self.assertEqual(backup["sidecars"], 4)
        self.assertEqual(backup["datasets"], 4)
        self.assertEqual(backup["engine_datasets_skipped"], 1)
        # Two methods, four sidecars, four data files and the class index.
        self.assertEqual(backup["files"], 11)

        target = Path(backup["path"])
        self.assertEqual(
            sorted(item.name for item in target.iterdir()),
            ["backup.json", "datasets", "index.json", "methods", "sidecars"],
        )
        self.assertEqual(
            sorted(item.name for item in (target / "methods").iterdir()),
            ["BF@B.json", "DFM@A.json"],
        )
        self.assertEqual(
            sorted(item.stem for item in (target / "sidecars").iterdir()),
            ["A - Paid DFM", "Accounting Cutoff", "Prior Qtr Indicated", "Selected Ultimate"],
        )
        self.assertEqual(
            sorted(item.name for item in (target / "datasets").iterdir()),
            [
                "A - Paid DFM@12.csv",
                "Accounting Cutoff@12.csv",
                "Prior Qtr Indicated@12.csv",
                "Selected Ultimate@12.csv",
            ],
        )
        for relative in ("methods/DFM@A.json", "datasets/Accounting Cutoff@12.csv"):
            self.assertEqual(
                (target / relative).read_text(encoding="utf-8"),
                (rc_dir / relative).read_text(encoding="utf-8"),
            )

        manifest = json.loads((target / "backup.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["project_name"], "Demo")
        self.assertEqual(manifest["reserving_class"], r"Auto\PP")
        self.assertEqual(manifest["import_policy"], "overwrite")
        self.assertEqual(manifest["file_count"], 11)
        self.assertEqual(manifest["engine_datasets_skipped"], 1)
        self.assertIn("methods/DFM@A.json", manifest["files"])
        self.assertIn("index.json", manifest["files"])
        # The copy lives outside the projects tree, so a project copy never
        # carries it and no reserving-class scan can reach it.
        self.assertNotIn("projects", target.relative_to(self.server_root).parts)

    def test_an_engine_generated_dataset_is_left_out_with_its_data_file(self):
        self._write_class(
            r"Auto\PP",
            [],
            datasets=[("Net Loss--Paid", "engine"), ("Accounting Cutoff", "input")],
        )

        backup = self.module.backup_reserving_class(self.server_root, "Demo", r"Auto\PP")

        target = Path(backup["path"])
        self.assertEqual(
            [item.name for item in (target / "sidecars").iterdir()],
            ["Accounting Cutoff.json"],
        )
        self.assertEqual(
            [item.name for item in (target / "datasets").iterdir()],
            ["Accounting Cutoff@12.csv"],
        )
        self.assertEqual(backup["engine_datasets_skipped"], 1)
        self.assertIn("1 engine-generated dataset(s) were left out", self.module.backup_sentence(backup))

    def test_a_data_file_no_sidecar_claims_is_kept(self):
        rc_dir = self._write_class(
            r"Auto\PP", [], datasets=[("Net Loss--Paid", "engine")]
        )
        (rc_dir / "datasets" / "Unclaimed@12.csv").write_text("origin\n2025\n", encoding="utf-8")

        backup = self.module.backup_reserving_class(self.server_root, "Demo", r"Auto\PP")

        self.assertEqual(
            [item.name for item in (Path(backup["path"]) / "datasets").iterdir()],
            ["Unclaimed@12.csv"],
        )

    def test_the_backup_never_overwrites_an_earlier_one_in_the_same_second(self):
        self._write_class(r"Auto\PP", ["DFM@A.json"])
        moment = datetime(2026, 9, 3, 14, 30, 0)

        first = self.module.backup_reserving_class(
            self.server_root, "Demo", r"Auto\PP", now=moment
        )
        second = self.module.backup_reserving_class(
            self.server_root, "Demo", r"Auto\PP", now=moment
        )

        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(first["methods"], 1)
        self.assertEqual(second["methods"], 1)

    def test_only_the_most_recent_backups_of_a_class_are_kept(self):
        self._write_class(r"Auto\PP", ["DFM@A.json"])
        keep = self.module.IMPORT_BACKUP_KEEP_PER_CLASS

        for minute in range(keep + 5):
            backup = self.module.backup_reserving_class(
                self.server_root,
                "Demo",
                r"Auto\PP",
                now=datetime(2026, 9, 3, 8, minute, 0),
            )

        class_dir = Path(backup["path"]).parent
        stamps = sorted(item.name for item in class_dir.iterdir())
        self.assertEqual(len(stamps), keep)
        self.assertEqual(stamps[0], "20260903-080500")
        self.assertEqual(stamps[-1], f"20260903-08{keep + 4:02d}00")

    def test_a_class_the_project_does_not_hold_yet_backs_up_nothing(self):
        backup = self.module.backup_reserving_class(self.server_root, "Demo", r"New\Class")

        self.assertEqual(backup["files"], 0)
        self.assertEqual(backup["reason"], "no_class_folder")
        self.assertEqual(backup["error"], "")
        self.assertEqual(self.module.backup_sentence(backup), "")

    def test_a_class_folder_holding_nothing_to_keep_backs_up_nothing(self):
        rc_dir = self._write_class(r"Auto\PP", [], datasets=[("Net Loss--Paid", "engine")])
        (rc_dir / "index.json").unlink()

        backup = self.module.backup_reserving_class(self.server_root, "Demo", r"Auto\PP")

        self.assertEqual(backup["files"], 0)
        self.assertEqual(backup["reason"], "nothing_to_back_up")
        self.assertEqual(self.module.backup_sentence(backup), "")

    def test_a_folder_named_under_an_older_rule_is_found_through_its_index(self):
        self._write_class(r"Auto\PP", ["DFM@A.json"], folder="legacy-folder")

        backup = self.module.backup_reserving_class(self.server_root, "Demo", r"Auto\PP")

        self.assertEqual(backup["methods"], 1)
        self.assertEqual(Path(backup["path"]).parent.name, "legacy-folder")

    def test_a_backup_that_cannot_be_written_is_reported_not_raised(self):
        self._write_class(r"Auto\PP", ["DFM@A.json"])

        with patch.object(self.module.resq_import_backup.shutil, "copy2", side_effect=OSError("share offline")):
            backup = self.module.backup_reserving_class(self.server_root, "Demo", r"Auto\PP")

        self.assertEqual(backup["files"], 0)
        self.assertIn("share offline", backup["error"])
        sentence = self.module.backup_sentence(backup)
        self.assertIn("WARNING", sentence)
        self.assertIn("no restore point", sentence)


if __name__ == "__main__":
    unittest.main()
