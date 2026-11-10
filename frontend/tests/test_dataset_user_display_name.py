from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
if str(FRONTEND_ROOT) not in sys.path:
    sys.path.insert(0, str(FRONTEND_ROOT))
TEST_TEMP_ROOT = FRONTEND_ROOT.parent / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

from app_server import config
from app_server.services import (
    audit_service,
    calculated_dataset_service,
    dataset_service,
    result_selection_service,
    user_identity_service,
)


class DatasetUserDisplayNameTests(unittest.TestCase):
    """Dataset writes stamp the configured full name, not the Windows login."""

    def setUp(self) -> None:
        user_identity_service.clear_display_name_cache()
        # The username index is read only where the workspace is local disk.
        server = patch.dict("os.environ", {config.RUNTIME_SERVER_ROOT_ENV: str(TEST_TEMP_ROOT)})
        server.start()
        self.addCleanup(server.stop)
        self._temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        index_path = Path(self._temp_dir.name) / "username_index.json"
        index_path.write_text(
            json.dumps({"users": [{"login_name": "xwei", "full_name": "Wei, Xiao"}]}),
            encoding="utf-8",
        )
        patchers = (
            patch.object(config, "get_username_index_path", return_value=str(index_path)),
            patch.object(user_identity_service, "get_windows_login_name", return_value="xwei"),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        user_identity_service.clear_display_name_cache()
        self._temp_dir.cleanup()

    def test_dataset_sidecar_user_is_the_configured_full_name(self) -> None:
        self.assertEqual(dataset_service._current_user_name(), "Wei, Xiao")

    def test_calculated_dataset_sidecar_user_is_the_configured_full_name(self) -> None:
        self.assertEqual(calculated_dataset_service._current_user_name(), "Wei, Xiao")

    def test_result_selection_sidecar_user_is_the_configured_full_name(self) -> None:
        self.assertEqual(result_selection_service._current_user_name(), "Wei, Xiao")

    def test_audit_entries_use_the_configured_full_name(self) -> None:
        self.assertEqual(audit_service._resolve_audit_user_name(), "Wei, Xiao")

    def test_an_explicit_login_is_resolved_and_a_display_name_survives(self) -> None:
        self.assertEqual(audit_service._resolve_audit_user_name("xwei"), "Wei, Xiao")
        self.assertEqual(audit_service._resolve_audit_user_name("Wei, Xiao"), "Wei, Xiao")

    def test_an_unmapped_login_keeps_its_login_name(self) -> None:
        with patch.object(user_identity_service, "get_windows_login_name", return_value="nobody"):
            user_identity_service.clear_display_name_cache()
            self.assertEqual(dataset_service._current_user_name(), "nobody")
            self.assertEqual(audit_service._resolve_audit_user_name(), "nobody")


class HostedSaveUserDisplayNameTests(unittest.TestCase):
    """A save hosted on Arco Engine stamps the user, not the instance.

    Engine instances run under their own service profiles, so before the
    acting identity existed the same edit could be attributed to a different
    account each time depending on which instance claimed the request.
    """

    def setUp(self) -> None:
        user_identity_service.clear_display_name_cache()
        self.addCleanup(user_identity_service.clear_display_name_cache)
        # The username index is read only where the workspace is local disk.
        server = patch.dict("os.environ", {config.RUNTIME_SERVER_ROOT_ENV: str(TEST_TEMP_ROOT)})
        server.start()
        self.addCleanup(server.stop)
        self._temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self._temp_dir.cleanup)
        index_path = Path(self._temp_dir.name) / "username_index.json"
        index_path.write_text(
            json.dumps({"users": [{"login_name": "xwei", "full_name": "Wei, Xiao"}]}),
            encoding="utf-8",
        )
        patchers = (
            patch.object(config, "get_username_index_path", return_value=str(index_path)),
            patch.dict("os.environ", {"USERNAME": "arcrho.engine.02"}, clear=False),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _stamped_names(self) -> list[str]:
        return [
            dataset_service._current_user_name(),
            calculated_dataset_service._current_user_name(),
            result_selection_service._current_user_name(),
            audit_service._resolve_audit_user_name(),
        ]

    def test_the_engine_account_is_what_the_bug_looked_like(self) -> None:
        self.assertEqual(self._stamped_names(), ["arcrho.engine.02"] * 4)

    def test_every_writer_follows_the_acting_identity(self) -> None:
        with user_identity_service.acting_identity("xwei", "Wei, Xiao"):
            self.assertEqual(self._stamped_names(), ["Wei, Xiao"] * 4)
        self.assertEqual(self._stamped_names(), ["arcrho.engine.02"] * 4)

    def test_a_login_only_binding_resolves_through_the_username_index(self) -> None:
        with user_identity_service.acting_identity("xwei"):
            self.assertEqual(self._stamped_names(), ["Wei, Xiao"] * 4)


if __name__ == "__main__":
    unittest.main()
