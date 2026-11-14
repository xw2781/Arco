"""The frozen helper the Excel add-in runs when a PC has no credential.

It must install exactly the credential the desktop app installs, sign up at
production's own address rather than read the server's folder, and never touch
a credential that is already there.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for import_root in (
    REPOSITORY_ROOT / "python-api" / "src",
    REPOSITORY_ROOT / "server-components" / "src",
):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from arcrho_api import hosted_save_enrollment  # noqa: E402
from arcrho_credential import main as credential_helper  # noqa: E402
from arcrho_hosted_save_http_contract import (  # noqa: E402
    CLIENT_CONFIG_FILE_NAME,
    normalize_client_config,
)

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
SERVER_URL = "http://arcrho-server.test:28767"


class GatewayCredentialHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        # The add-in passes the share folder; it does not exist here, so any read would fail.
        self.workspace = base / "Arco Server"
        self.appdata = base / "AppData"
        self.local_path = self.appdata / "Arco" / CLIENT_CONFIG_FILE_NAME

    def _write_profiles(self, production_url: str = SERVER_URL) -> None:
        profiles = [
            {"id": "default", "name": "Production", "root": str(self.workspace), "gateway_url": production_url},
            {"id": "local", "name": "Local", "root": "C:\\Arco Server", "gateway_url": "http://127.0.0.1:28767"},
        ]
        path = self.appdata / "Arco" / "workspace_paths.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"profiles": profiles, "active_profile": "local"}), encoding="utf-8")

    def _run(self, *argv: str, probe=None) -> tuple[int, str, list[str]]:
        probed: list[str] = []
        output = StringIO()
        with (
            patch.dict("os.environ", {"APPDATA": str(self.appdata), "ARCRHO_GATEWAY_URL": ""}),
            patch.object(
                hosted_save_enrollment,
                "probe_gateway_url",
                side_effect=probe or (lambda url: probed.append(url) or {"windows_enrollment": True}),
            ),
            patch.object(
                hosted_save_enrollment,
                "request_windows_enrollment",
                return_value={"user": "alice", "secret": "alice-secret"},
            ),
            redirect_stdout(output),
        ):
            code = credential_helper.main([str(self.workspace), *argv])
        return code, output.getvalue().strip(), probed

    def test_first_run_signs_up_at_productions_address(self) -> None:
        self._write_profiles()

        code, printed, probed = self._run()

        self.assertEqual(code, 0)
        self.assertIn("installed", printed)
        self.assertEqual(probed, [SERVER_URL])
        installed = normalize_client_config(json.loads(self.local_path.read_text(encoding="utf-8")))
        self.assertEqual((installed["url"], installed["user"], installed["secret"]), (SERVER_URL, "alice", "alice-secret"))
        self.assertFalse(self.workspace.exists())

    def test_an_address_on_the_command_line_wins(self) -> None:
        code, _, probed = self._run("--url", "http://other:28767")

        self.assertEqual(code, 0)
        self.assertEqual(probed, ["http://other:28767"])

    def test_an_existing_opt_out_is_left_alone(self) -> None:
        self._write_profiles()
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self.local_path.write_text('{"enabled": false}\n', encoding="utf-8")

        code, printed, probed = self._run()

        self.assertEqual(code, 0)
        self.assertIn("already present", printed)
        self.assertEqual(probed, [])
        self.assertEqual(self.local_path.read_text(encoding="utf-8"), '{"enabled": false}\n')

    def test_no_known_address_writes_nothing(self) -> None:
        code, printed, probed = self._run()

        self.assertEqual(code, 1)
        self.assertIn("No Gateway address", printed)
        self.assertEqual(probed, [])
        self.assertFalse(self.local_path.exists())

    def test_an_unreachable_server_writes_nothing(self) -> None:
        self._write_profiles()

        def offline(_url):
            raise OSError("the server could not be reached")

        code, printed, _ = self._run(probe=offline)

        self.assertEqual(code, 1)
        self.assertIn("could not be reached", printed)
        self.assertFalse(self.local_path.exists())


if __name__ == "__main__":
    unittest.main()
