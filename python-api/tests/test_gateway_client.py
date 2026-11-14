"""The script-side Gateway client signs as its user and sends the shared request shapes."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api import gateway  # noqa: E402
from arcrho_api.exceptions import ArcRhoApiError  # noqa: E402
from arcrho_engine_save_contract import validate_save_job_request  # noqa: E402
from arcrho_hosted_save_http_contract import (  # noqa: E402
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    HOSTED_SAVE_PATH,
    verify_request_signature,
)
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_PATH, validate_workspace_mutation_request  # noqa: E402
from arcrho_workspace_read_contract import WORKSPACE_READ_PATH, validate_workspace_read_request  # noqa: E402

TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

CONFIG = {
    "enabled": True,
    "url": "http://gateway.example:28767",
    "user": "xwei",
    "secret": "test-secret",
    "allow_insecure_http": True,
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class GatewayClientTests(unittest.TestCase):
    def _send(self, call, answer=None):
        sent = []

        def fake_open(request, timeout):
            sent.append(request)
            return _Response(json.dumps(answer or {"ok": True}).encode("utf-8"))

        with patch.object(gateway._OPENER, "open", side_effect=fake_open):
            result = call(gateway.GatewayClient(CONFIG))
        self.assertEqual(len(sent), 1)
        request = sent[0]
        headers = {name.lower(): value for name, value in request.header_items()}
        path = request.full_url[len(CONFIG["url"]):]
        self.assertEqual(headers[AUTH_USER_HEADER.lower()], "xwei")
        self.assertTrue(verify_request_signature(
            CONFIG["secret"],
            headers[AUTH_SIGNATURE_HEADER.lower()],
            user="xwei",
            timestamp=headers[AUTH_TIMESTAMP_HEADER.lower()],
            method="POST",
            path=path,
            body=request.data,
        ))
        return result, path, json.loads(request.data)

    def test_read_sends_a_signed_workspace_read_as_the_credential_user(self):
        result, path, payload = self._send(
            lambda client: client.read("propagation_busy", project_name="P", reserving_class="A\\B"),
            answer={"ok": True, "busy": False},
        )
        self.assertEqual(result, {"ok": True, "busy": False})
        self.assertEqual(path, WORKSPACE_READ_PATH)
        request = validate_workspace_read_request(payload)
        self.assertEqual(request["ReadKind"], "propagation_busy")
        self.assertEqual(request["Kwargs"], {"project_name": "P", "reserving_class": "A\\B"})
        self.assertEqual(request["UserName"], "xwei")

    def test_mutate_sends_a_signed_workspace_mutation(self):
        _, path, payload = self._send(
            lambda client: client.mutate(
                "propagation_submit",
                project_name="P",
                reserving_class="A",
                changed_roots=[{"dataset_name": "T", "dataset_type": "T"}],
                request_id="a" * 32,
            )
        )
        self.assertEqual(path, WORKSPACE_MUTATION_PATH)
        self.assertEqual(validate_workspace_mutation_request(payload)["MutationKind"], "propagation_submit")

    def test_save_passes_project_and_class_ahead_of_the_service_arguments(self):
        _, path, payload = self._send(
            lambda client: client.save("result_selection_method", "P", "A", {"m": 1}, "notes", "rev")
        )
        self.assertEqual(path, HOSTED_SAVE_PATH)
        request = validate_save_job_request(payload)
        self.assertEqual(request["SaveKind"], "result_selection_method")
        self.assertEqual(request["Args"], ["P", "A", {"m": 1}, "notes", "rev"])
        self.assertEqual(request["UserName"], "xwei")

    def test_refusal_carries_the_status_and_detail(self):
        def refuse(request, timeout):
            raise HTTPError(request.full_url, 423, "Locked", {}, io.BytesIO(b'{"detail": "busy"}'))

        with patch.object(gateway._OPENER, "open", side_effect=refuse):
            with self.assertRaises(gateway.GatewayError) as caught:
                gateway.GatewayClient(CONFIG).read("propagation_busy", project_name="P", reserving_class="A")
        self.assertEqual((caught.exception.status, caught.exception.detail), (423, "busy"))

    def test_missing_credential_names_the_file(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder, patch.dict(
            os.environ, {"APPDATA": folder, "ARCRHO_GATEWAY_CONFIG": ""}
        ):
            with self.assertRaisesRegex(ArcRhoApiError, "No Arco Gateway credential"):
                gateway.GatewayClient()

    def test_credential_follows_the_active_server_profile(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder, patch.dict(
            os.environ, {"APPDATA": folder, "ARCRHO_GATEWAY_CONFIG": ""}
        ):
            settings = Path(folder) / "Arco"
            settings.mkdir()
            (settings / "workspace_paths.json").write_text(json.dumps({
                "profiles": [{"id": "local", "name": "Local test", "root": folder}],
                "active_profile": "local",
            }), encoding="utf-8")
            (settings / "arcrho_gateway.local.json").write_text(json.dumps(CONFIG), encoding="utf-8")
            self.assertEqual(gateway.GatewayClient().url, CONFIG["url"])


if __name__ == "__main__":
    unittest.main()
