from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


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

from arcrho_engine_save_contract import (
    SAVE_JOB_KINDS,
    build_save_job_request,
    validate_save_job_request,
    write_save_job_status,
)
from arcrho_hosted_save_http_contract import (
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    HOSTED_SAVE_PATH,
    HTTP_SAVE_KINDS,
    canonical_request_bytes,
    default_gateway_config,
    sign_request,
    verify_request_signature,
)
from arcrho_api.gateway_test_guard import allow_test_gateway
from arcrho_gateway import main as gateway_main
from arcrho_gateway import configure_pilot
from app_server.services import hosted_save_http_client


class HostedSaveHttpContractTests(unittest.TestCase):
    def test_http_transport_covers_every_canonical_save_kind(self) -> None:
        self.assertEqual(HTTP_SAVE_KINDS, tuple(sorted(SAVE_JOB_KINDS)))

    def test_gateway_configuration_stores_no_save_kind_allowlist(self) -> None:
        """The supported kinds are derived, so no config may narrow them."""

        self.assertNotIn("allowed_save_kinds", default_gateway_config())

    def test_provisioning_clears_the_pilot_login_startup_entry(self) -> None:
        """The Orchestrator owns Gateway startup; a login entry races it."""

        registry_key = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = registry_key
        with (
            patch.object(configure_pilot.winreg, "OpenKey", return_value=context) as open_key,
            patch.object(configure_pilot.winreg, "DeleteValue") as delete_value,
        ):
            self.assertTrue(configure_pilot.remove_current_user_startup())

        open_key.assert_called_once_with(
            configure_pilot.winreg.HKEY_CURRENT_USER,
            configure_pilot.STARTUP_REGISTRY_KEY,
            0,
            configure_pilot.winreg.KEY_SET_VALUE,
        )
        delete_value.assert_called_once_with(
            registry_key, configure_pilot.STARTUP_VALUE_NAME
        )

    def test_clearing_a_missing_login_startup_entry_is_not_an_error(self) -> None:
        with patch.object(configure_pilot.winreg, "OpenKey", side_effect=FileNotFoundError):
            self.assertFalse(configure_pilot.remove_current_user_startup())

    def test_the_gateway_refuses_to_share_a_port_with_a_live_gateway(self) -> None:
        """Two bound Gateways would each serve an arbitrary share of saves."""

        self.assertFalse(gateway_main.GatewayServer.allow_reuse_address)

    def test_provisioning_drops_a_pilot_era_save_kind_allowlist(self) -> None:
        """An upgraded gateway must not stay narrowed by a stored pilot list."""

        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temporary:
            root = Path(temporary)
            server_config = default_gateway_config()
            server_config["allowed_save_kinds"] = ["dataset_sidecar"]
            server_config["users"] = {"alice": "existing-secret"}
            gateway_main._write_json_atomic(
                root / "config" / "arcrho_gateway.json",
                server_config,
            )
            client_output = root / "client" / "arcrho_gateway.json"

            configure_pilot.configure(
                server_root=root,
                user="alice",
                url="http://gateway.test:28767",
                client_output=client_output,
            )

            updated = json.loads(
                (root / "config" / "arcrho_gateway.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertNotIn("allowed_save_kinds", updated)
            self.assertEqual(updated["users"], {"alice": "existing-secret"})

    def test_signature_binds_user_path_timestamp_and_body(self) -> None:
        body = b'{"RequestId":"abc"}'
        timestamp = "1000"
        signature = sign_request(
            "secret",
            user="Alice",
            timestamp=timestamp,
            method="POST",
            path=HOSTED_SAVE_PATH,
            body=body,
        )
        self.assertTrue(
            verify_request_signature(
                "secret",
                signature,
                user="alice",
                timestamp=timestamp,
                method="POST",
                path=HOSTED_SAVE_PATH,
                body=body,
                now=1000,
            )
        )
        self.assertFalse(
            verify_request_signature(
                "secret",
                signature,
                user="bob",
                timestamp=timestamp,
                method="POST",
                path=HOSTED_SAVE_PATH,
                body=body,
                now=1000,
            )
        )
        self.assertFalse(
            verify_request_signature(
                "secret",
                signature,
                user="alice",
                timestamp=timestamp,
                method="POST",
                path=HOSTED_SAVE_PATH,
                body=b"different",
                now=1000,
            )
        )


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp_dir.name)
        (self.root / "projects").mkdir()
        config = default_gateway_config()
        config["host"] = "127.0.0.1"
        config["port"] = 28767
        config["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.root / "config" / "arcrho_gateway.json", config
        )
        self.gateway = gateway_main.Gateway(self.root)
        self.preflight = patch.object(gateway_main, "require_live_engine")
        self.hold = patch.object(
            gateway_main, "find_reserving_class_propagation_hold", return_value=None
        )
        self.preflight.start()
        self.hold.start()

    def tearDown(self) -> None:
        self.hold.stop()
        self.preflight.stop()
        self.temp_dir.cleanup()

    def _request(self, request_id: str = "request-123") -> dict:
        return build_save_job_request(
            request_id=request_id,
            save_kind="dataset_sidecar",
            project_name="Demo Project",
            path="LOB\\State",
            args=["Demo Project", "LOB\\State", "Paid Input"],
            kwargs={"values": [[1.0, 2.0]], "mask": [[True, True]]},
            user_name="alice",
            user_display_name="Alice Example",
        )

    def _dfm_request(self, request_id: str = "dfm-request-123") -> dict:
        method = {
            "json_format": "arcrho-dfm-v4",
            "details_tab": {
                "name": "C 22 - CWOP DFM w/ Selected LDFs",
                "output_dataset": "CWOP Ultimate",
            },
            "data_tab": {"values": [[100.0, 120.0], [90.0]]},
        }
        return build_save_job_request(
            request_id=request_id,
            save_kind="dfm_method",
            project_name="Demo Project",
            path="LOB\\State",
            args=["Demo Project", "LOB\\State", method],
            kwargs={
                "notes": "transport parity",
                "expected_owned_revision": "owned-123",
                "expected_derived_revision": "derived-123",
            },
            user_name="alice",
            user_display_name="Alice Example",
        )

    def _engine_stub(self, seen: list[dict]) -> threading.Thread:
        def run() -> None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                requests = list((self.root / "requests").glob("arcrho_hosted_save_*.json"))
                if requests:
                    request = validate_save_job_request(
                        json.loads(requests[0].read_text(encoding="utf-8"))
                    )
                    seen.append(request)
                    requests[0].unlink()
                    write_save_job_status(
                        self.root,
                        request["RequestId"],
                        "success",
                        response={"ok": True, "saved": request["Args"][2]},
                    )
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def test_replaying_one_request_returns_one_engine_execution(self) -> None:
        seen: list[dict] = []
        request = self._request()
        thread = self._engine_stub(seen)
        first = self.gateway.submit("alice", request)
        thread.join(timeout=5)
        second = self.gateway.submit("alice", request)
        self.assertEqual(first, {"ok": True, "saved": "Paid Input"})
        self.assertEqual(second, first)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], validate_save_job_request(request))

        receipt = json.loads(
            (self.root / "runtime" / "arcrho_gateway" / "receipts" / "request-123.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["state"], "success")
        self.assertEqual(receipt["request"]["Kwargs"]["values"], [[1.0, 2.0]])

    def test_dfm_request_reaches_engine_byte_for_byte_logically(self) -> None:
        seen: list[dict] = []
        request = self._dfm_request()
        thread = self._engine_stub(seen)
        result = self.gateway.submit("alice", request)
        thread.join(timeout=5)

        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], validate_save_job_request(request))
        self.assertEqual(result["saved"], request["Args"][2])

    def _request_for_kind(self, save_kind: str, request_id: str) -> dict:
        return build_save_job_request(
            request_id=request_id,
            save_kind=save_kind,
            project_name="Demo Project",
            path="LOB\\State",
            args=["Demo Project", "LOB\\State", {"name": f"{save_kind} object"}],
            kwargs={},
            user_name="alice",
            user_display_name="Alice Example",
        )

    def test_every_canonical_save_kind_reaches_engine_over_http(self) -> None:
        """No save procedure is left behind on the SMB transport."""

        for index, save_kind in enumerate(sorted(SAVE_JOB_KINDS)):
            with self.subTest(save_kind=save_kind):
                seen: list[dict] = []
                thread = self._engine_stub(seen)
                request = self._request_for_kind(save_kind, f"kind-request-{index}")
                result = self.gateway.submit("alice", request)
                thread.join(timeout=5)

                self.assertTrue(result["ok"])
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0]["SaveKind"], save_kind)
                self.assertEqual(seen[0], validate_save_job_request(request))

    def test_capabilities_advertise_every_canonical_save_kind(self) -> None:
        self.assertEqual(
            self.gateway.capabilities()["allowed_save_kinds"],
            list(HTTP_SAVE_KINDS),
        )

    def test_a_stored_pilot_allowlist_no_longer_narrows_the_gateway(self) -> None:
        stored = default_gateway_config()
        stored["allowed_save_kinds"] = ["dataset_sidecar"]
        stored["users"] = {"alice": "alice-secret"}
        gateway_main._write_json_atomic(
            self.root / "config" / "arcrho_gateway.json", stored
        )

        seen: list[dict] = []
        thread = self._engine_stub(seen)
        request = self._request_for_kind("cape_cod_method", "legacy-config-request")
        result = self.gateway.submit("alice", request)
        thread.join(timeout=5)

        self.assertTrue(result["ok"])
        self.assertEqual(seen[0]["SaveKind"], "cape_cod_method")

    def test_same_request_id_with_different_content_is_rejected(self) -> None:
        seen: list[dict] = []
        request = self._request()
        thread = self._engine_stub(seen)
        self.gateway.submit("alice", request)
        thread.join(timeout=5)
        conflicting = self._request()
        conflicting["Kwargs"]["values"] = [[999.0]]
        with self.assertRaises(gateway_main.GatewayHttpError) as raised:
            self.gateway.submit("alice", conflicting)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(seen), 1)

    def test_a_new_gateway_process_recovers_an_accepted_unpublished_receipt(self) -> None:
        request = self._request("recovered-request-123")
        receipt = gateway_main._new_receipt(request)
        gateway_main._write_json_atomic(
            self.root
            / "runtime"
            / "arcrho_gateway"
            / "receipts"
            / "recovered-request-123.json",
            receipt,
        )
        seen: list[dict] = []
        thread = self._engine_stub(seen)
        replacement = gateway_main.Gateway(self.root)
        result = replacement.submit("alice", request)
        thread.join(timeout=5)
        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 1)

    def test_absolute_reserving_class_path_is_rejected_before_acceptance(self) -> None:
        request = self._request("absolute-path-request")
        request["Path"] = r"E:\Arco Server\projects\Demo"
        with self.assertRaises(gateway_main.GatewayHttpError) as raised:
            self.gateway.submit("alice", request)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(
            (
                self.root
                / "runtime"
                / "arcrho_gateway"
                / "receipts"
                / "absolute-path-request.json"
            ).exists()
        )

    def test_http_client_and_gateway_round_trip(self) -> None:
        server = gateway_main.GatewayServer(("127.0.0.1", 0), self.gateway)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        self.addCleanup(allow_test_gateway(url))
        seen: list[dict] = []
        engine_thread = self._engine_stub(seen)
        try:
            result, timings = hosted_save_http_client.submit_hosted_save(
                {
                    "url": url,
                    "user": "alice",
                    "secret": "alice-secret",
                },
                self._request("http-request-123"),
                timeout_seconds=5,
            )
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
            engine_thread.join(timeout=5)
        self.assertTrue(result["ok"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(timings["gateway_attempts"], 1)
        self.assertGreater(timings["request_bytes"], 0)

    def test_authentication_rejects_a_modified_body(self) -> None:
        request = self._request()
        body = canonical_request_bytes(request)
        timestamp = str(int(time.time()))
        signature = sign_request(
            "alice-secret",
            user="alice",
            timestamp=timestamp,
            method="POST",
            path=HOSTED_SAVE_PATH,
            body=body,
        )
        headers = {
            AUTH_USER_HEADER: "alice",
            AUTH_TIMESTAMP_HEADER: timestamp,
            AUTH_SIGNATURE_HEADER: signature,
        }
        self.assertEqual(self.gateway.authenticate(headers, body), "alice")
        with self.assertRaises(gateway_main.GatewayHttpError) as raised:
            self.gateway.authenticate(headers, body + b" ")
        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
