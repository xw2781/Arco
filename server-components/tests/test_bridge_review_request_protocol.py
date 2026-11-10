"""Cover the Bridge's read-only Arco/ResQ reserving-class review.

A review is served by the same ResQ-connected worker as an import and a
synchronization, through the same claim/status/heartbeat protocol, but from
the synchronization queue's folders: inside the Arco app every poll is the
hosted Bridge-liveness read, which knows the import and sync queues and no
others, so a third folder would be unreadable until the app itself was
rebuilt. These tests pin that sharing, that the two functions stay apart, and
that a malformed, mis-versioned, or path-bearing request is refused.
"""
from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENGINE_SRC = REPOSITORY_ROOT / "server-components" / "src"
CANONICAL_SRC = REPOSITORY_ROOT / "python-api" / "src"
for source_root in (ENGINE_SRC, CANONICAL_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from arcrho_bridge import main as bridge_main  # noqa: E402
from arcrho_bridge.resq_import_contract import (  # noqa: E402
    load_resq_reserving_class_import_contract,
)
from arcrho_bridge.resq_review_contract import (  # noqa: E402
    ResQReviewContractError,
    load_resq_reserving_class_review_contract,
)
from arcrho_bridge.resq_sync_contract import (  # noqa: E402
    load_resq_reserving_class_sync_contract,
)


TEST_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
_REQUEST_ID = "review-request-123"
_CONTRACT_PATH = ENGINE_SRC / "arcrho_bridge" / "resq_reserving_class_review_contract.json"


def _review_request(**overrides):
    payload = {
        "Function": bridge_main.RESQ_REVIEW_FUNCTION,
        "ContractVersion": bridge_main.RESQ_REVIEW_CONTRACT_VERSION,
        "RequestId": _REQUEST_ID,
        "ProjectName": "Demo",
        "Path": r"Auto\PP",
        "UserName": "tester",
    }
    payload.update(overrides)
    return payload


class BridgeReviewContractTests(unittest.TestCase):
    def test_bridge_uses_the_versioned_json_contract(self):
        contract = load_resq_reserving_class_review_contract()

        self.assertEqual(bridge_main.RESQ_REVIEW_FUNCTION, contract["function"])
        self.assertEqual(
            bridge_main.RESQ_REVIEW_CONTRACT_VERSION,
            contract["contract_version"],
        )
        self.assertEqual(
            bridge_main._RESQ_REVIEW_REQUIRED_FIELDS,
            tuple(contract["required_request_fields"]),
        )

    def test_the_review_shares_the_sync_queue_folders_under_its_own_function(self):
        review = load_resq_reserving_class_review_contract()
        sync = load_resq_reserving_class_sync_contract()

        self.assertEqual(
            tuple(review["request_relative_dir"]), tuple(sync["request_relative_dir"])
        )
        self.assertEqual(
            tuple(review["status_relative_dir"]), tuple(sync["status_relative_dir"])
        )
        self.assertNotEqual(review["function"], sync["function"])

    def test_worker_and_status_facts_are_taken_from_the_import_contract(self):
        review = load_resq_reserving_class_review_contract()
        import_contract = load_resq_reserving_class_import_contract()
        shared = (
            "worker_role",
            "worker_heartbeat_relative_dir",
            "worker_heartbeat_max_age_seconds",
            "status_values",
            "forbidden_path_fields",
        )

        raw = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        for key in shared:
            with self.subTest(field=key):
                self.assertEqual(review[key], import_contract[key])
                self.assertNotIn(key, raw)

    def test_a_contract_that_restates_worker_facts_is_rejected(self):
        from arcrho_bridge import resq_review_contract

        payload = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        payload["worker_role"] = "bridge_worker"

        with self.assertRaisesRegex(ResQReviewContractError, "import contract"):
            resq_review_contract._validated_contract(payload)

    def test_a_contract_that_moves_the_queue_elsewhere_is_rejected(self):
        from arcrho_bridge import resq_review_contract

        payload = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
        payload["request_relative_dir"] = [
            "requests",
            "RPC bridge",
            "resq_reserving_class_review",
            "requests",
        ]

        with self.assertRaisesRegex(ResQReviewContractError, "hosted liveness poll"):
            resq_review_contract._validated_contract(payload)


class BridgeReviewRequestHandlingTests(unittest.TestCase):
    def test_review_request_is_claimed_before_status_and_validation(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        events = []

        def record_status(_request, status, **_kwargs):
            events.append(status)
            return True

        with (
            patch.object(bridge_main, "read_json", return_value=_review_request(ProjectName="")),
            patch.object(
                bridge_main,
                "safe_remove",
                side_effect=lambda _path: events.append("claim") or True,
            ),
            patch.object(bridge_main, "_write_resq_review_status", side_effect=record_status),
        ):
            self.assertTrue(handler.process_file(Path("request.json")))

        self.assertEqual(events, ["claim", "processing", "error"])
        client.write_resq_reserving_class_review.assert_not_called()

    def test_a_review_request_is_never_handled_by_the_sync_or_import_path(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)

        with (
            patch.object(bridge_main, "read_json", return_value=_review_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(bridge_main, "_write_resq_review_status", return_value=True),
            patch.object(bridge_main, "_write_resq_sync_status") as sync_status,
            patch.object(bridge_main, "_write_resq_import_status") as import_status,
        ):
            handler.process_file(Path("request.json"))

        sync_status.assert_not_called()
        import_status.assert_not_called()
        client.write_resq_reserving_class_sync.assert_not_called()
        client.write_resq_reserving_class_import.assert_not_called()
        client.write_resq_reserving_class_review.assert_called_once()

    def test_review_success_publishes_progress_and_terminal_result(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        statuses = []

        def record_status(_request, status, **kwargs):
            statuses.append((status, kwargs))
            return True

        def write_review(_request, *, progress_callback=None):
            self.assertIsNotNone(progress_callback)
            progress_callback({"message": "Comparing plain datasets...", "completed": 1, "total": 0})
            return {"workbook_relative_path": r"projects\Demo\users\tester\reviews\book.xlsx"}

        client.write_resq_reserving_class_review.side_effect = write_review
        with (
            patch.object(bridge_main, "read_json", return_value=_review_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(bridge_main, "_write_resq_review_status", side_effect=record_status),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual([status for status, _kwargs in statuses], ["processing", "processing", "success"])
        self.assertEqual(
            statuses[-1][1]["result"],
            {"workbook_relative_path": r"projects\Demo\users\tester\reviews\book.xlsx"},
        )

    def test_a_failed_review_reports_the_error_without_a_success_status(self):
        client = Mock()
        handler = bridge_main.BridgeRequestHandler(client)
        statuses = []
        client.write_resq_reserving_class_review.side_effect = RuntimeError("ResQ is unavailable")

        with (
            patch.object(bridge_main, "read_json", return_value=_review_request()),
            patch.object(bridge_main, "safe_remove", return_value=True),
            patch.object(
                bridge_main,
                "_write_resq_review_status",
                side_effect=lambda _request, status, **kwargs: statuses.append((status, kwargs)) or True,
            ),
        ):
            handler.process_file(Path("request.json"))

        self.assertEqual([status for status, _kwargs in statuses], ["processing", "error"])
        self.assertIn("ResQ is unavailable", str(statuses[-1][1]["message"]))

    def test_the_review_status_carries_the_review_contract_version(self):
        """The shared status folder is not a shared contract.

        A client waiting on a review must be able to tell the two queues'
        payloads apart, so the document is stamped with the review's own
        version even though it sits beside the synchronization's.
        """

        with patch.object(bridge_main, "_publish_queue_status") as publish:
            bridge_main._publish_resq_review_status(_REQUEST_ID, "success")

        _, kwargs = publish.call_args
        self.assertEqual(kwargs["contract_version"], bridge_main.RESQ_REVIEW_CONTRACT_VERSION)
        self.assertIs(kwargs["status_path_of"], bridge_main.resq_sync_status_path)
        self.assertNotEqual(
            bridge_main.RESQ_REVIEW_CONTRACT_VERSION,
            bridge_main.RESQ_SYNC_CONTRACT_VERSION,
        )


class BridgeReviewWorkbookTests(unittest.TestCase):
    """Where the workbook lands, and how the waiting client is told."""

    def setUp(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        self.server_root = (Path(self.temp_dir.name) / "Arco Server").resolve()
        (self.server_root / "projects" / "Demo").mkdir(parents=True)

    def test_the_workbook_goes_under_the_asking_persons_project_folder(self):
        from arcrho_bridge import resq_review_runner

        path = resq_review_runner.review_workbook_path(
            self.server_root, "demo", r"HPPREF\HO+DF\NJ\Legacy\HOL", "xwei"
        )

        relative = path.relative_to(self.server_root)
        self.assertEqual(relative.parts[:5], ("projects", "Demo", "users", "xwei", "reviews"))
        self.assertTrue(relative.name.startswith("Side by side HOL "))
        self.assertTrue(relative.suffix == ".xlsx")

    def test_a_project_the_server_does_not_hold_is_refused(self):
        from arcrho_bridge import resq_review_runner

        with self.assertRaisesRegex(resq_review_runner.ResQReviewRequestError, "no project folder"):
            resq_review_runner.review_workbook_path(
                self.server_root, "Missing", r"Auto\PP", "xwei"
            )

    def test_the_result_names_the_workbook_under_the_root_not_by_this_drive(self):
        from arcrho_bridge import resq_review_runner

        scope = []
        migration = types.SimpleNamespace(
            _apply_runtime_scope=lambda project, root: scope.append(("apply", project, root))
            or "previous",
            _restore_runtime_scope=lambda previous: scope.append(("restore", previous)),
        )
        review = types.SimpleNamespace(
            run_review=lambda **kwargs: {
                "workbook_path": str(kwargs["output_path"]),
                "needs_attention": False,
                "asked_for": kwargs["rc_paths"],
                "account": kwargs["credentials"],
                "scope_when_read": list(scope),
            }
        )
        with (
            patch.object(resq_review_runner, "get_project_root", return_value=self.server_root),
            patch.object(resq_review_runner, "configure_canonical_runtime", return_value=None),
            patch.object(resq_review_runner, "load_resq_data_migration", return_value=migration),
            patch.object(resq_review_runner, "load_review_module", return_value=review),
        ):
            result = resq_review_runner.run_reserving_class_review(
                _review_request(),
                resq_credentials={"connection_name": "SRV", "user_name": "svc", "password": "s"},
            )

        self.assertNotIn("workbook_path", result)
        relative = Path(result["workbook_relative_path"])
        self.assertFalse(relative.is_absolute())
        self.assertEqual(relative.parts[:5], ("projects", "Demo", "users", "tester", "reviews"))
        self.assertNotIn(str(self.server_root), json.dumps(result))
        self.assertEqual(result["asked_for"], [r"Auto\PP"])
        self.assertEqual(result["account"]["user_name"], "svc")
        self.assertEqual(result["request_id"], _REQUEST_ID)
        # The Arco side is read from this Bridge's own workspace, not the
        # migration module's default root, and the scope is put back after.
        self.assertEqual(result["scope_when_read"], [["apply", "Demo", str(self.server_root)]])
        self.assertEqual(scope[-1], ("restore", "previous"))


class BridgeReviewRequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.handler = bridge_main.BridgeRequestHandler(Mock())

    def test_a_valid_request_is_accepted_and_normalized(self):
        request = _review_request(Path="Auto/PP ", ProjectName=" Demo ")
        self.handler._validate_resq_review_request(request)
        self.assertEqual(request["Path"], r"Auto\PP")
        self.assertEqual(request["ProjectName"], "Demo")

    def test_a_mis_versioned_request_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Unsupported ContractVersion"):
            self.handler._validate_resq_review_request(
                _review_request(ContractVersion=bridge_main.RESQ_REVIEW_CONTRACT_VERSION + 1)
            )

    def test_a_request_naming_the_sync_function_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Function must be"):
            self.handler._validate_resq_review_request(
                _review_request(Function=bridge_main.RESQ_SYNC_FUNCTION)
            )

    def test_every_required_field_is_demanded(self):
        for key in ("ProjectName", "Path", "UserName"):
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError, "Missing request field"):
                    self.handler._validate_resq_review_request(_review_request(**{key: "  "}))

    def test_a_request_that_supplies_a_path_field_is_refused(self):
        for key in ("StatusPath", "DataPath", "TargetPath", "ServerRoot"):
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError, "must not supply path field"):
                    self.handler._validate_resq_review_request(
                        _review_request(**{key: r"E:\Arco Server"})
                    )

    def test_an_escaping_reserving_class_path_is_refused(self):
        for rc_path in (r"..\escape", r"\absolute", "C:\\drive", "Auto\\..\\PP"):
            with self.subTest(rc_path=rc_path):
                with self.assertRaises(ValueError):
                    self.handler._validate_resq_review_request(_review_request(Path=rc_path))


if __name__ == "__main__":
    unittest.main()
