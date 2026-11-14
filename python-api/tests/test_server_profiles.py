"""Server profiles in workspace_paths.json: one active server, each with its own credential."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api import config as api_config  # noqa: E402
from arcrho_api.exceptions import InvalidArcRhoServerError  # noqa: E402

TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


class ServerProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        base = Path(self.temp.name)
        self.settings = base / "appdata" / "Arco"
        self.config_path = self.settings / "workspace_paths.json"
        self.production = base / "production"
        self.local = base / "local"
        for root in (self.production, self.local):
            (root / "projects").mkdir(parents=True)
        env = patch.dict(os.environ, {
            "APPDATA": str(base / "appdata"),
            api_config.SERVER_ROOT_ENV: "",
            api_config.RUNTIME_SERVER_ROOT_ENV: "",
            api_config.GATEWAY_CONFIG_ENV: "",
            api_config.GATEWAY_URL_ENV: "",
        })
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.temp.cleanup)

    def _write_legacy_file(self) -> bytes:
        self.settings.mkdir(parents=True)
        text = json.dumps({"workspace_root": str(self.production), "paths": {"projects_dir": "projects"}})
        self.config_path.write_text(text, encoding="utf-8")
        return self.config_path.read_bytes()

    def test_file_without_profiles_reads_as_one_default_profile_and_writes_nothing(self) -> None:
        before = self._write_legacy_file()

        cfg = api_config.load_workspace_config()
        credential = api_config.gateway_config_path()

        self.assertEqual(cfg["profiles"], [{"id": "default", "name": "Production", "root": str(self.production)}])
        self.assertEqual(cfg["active_profile"], "default")
        self.assertEqual(cfg["workspace_root"], str(self.production))
        self.assertEqual(credential, self.settings / "arcrho_gateway.json")
        self.assertEqual(self.config_path.read_bytes(), before)

    def test_a_saved_root_under_the_old_folder_name_is_renamed_and_saved_once(self) -> None:
        self.settings.mkdir(parents=True)
        self.config_path.write_text(json.dumps({
            "workspace_root": r"E:\ArcRho Server",
            "profiles": [
                {"id": "default", "name": "Production", "root": "\\\\NE7SASWPN02\\E\\arcrho server\\"},
                {"id": "local", "name": "Local", "root": str(self.local)},
            ],
        }), encoding="utf-8")

        cfg = api_config.load_workspace_config()
        saved = self.config_path.read_bytes()

        self.assertEqual(cfg["workspace_root"], "\\\\NE7SASWPN02\\E\\Arco Server\\")
        self.assertEqual(cfg["profiles"][1]["root"], str(self.local))
        self.assertEqual(json.loads(saved)["workspace_root"], cfg["workspace_root"])
        self.assertEqual(api_config.load_workspace_config(), cfg)
        self.assertEqual(self.config_path.read_bytes(), saved)

    def test_missing_file_leaves_the_root_unconfigured_and_writes_nothing(self) -> None:
        cfg = api_config.load_workspace_config()

        self.assertEqual(cfg["workspace_root"], "")
        self.assertEqual(api_config.gateway_config_path(), self.settings / "arcrho_gateway.json")
        self.assertFalse(self.settings.exists())

    def test_each_profile_resolves_its_own_credential(self) -> None:
        self._write_legacy_file()
        api_config.upsert_server_profile(name="Local test", root=str(self.local), profile_id="local")
        api_config.upsert_server_profile(
            name="Other", root=str(self.local), gateway_config=str(self.local / "other.json"),
        )

        self.assertEqual(api_config.gateway_config_path(), self.settings / "arcrho_gateway.json")
        saved = api_config.activate_server_profile("local")
        self.assertEqual(api_config.gateway_config_path(), self.settings / "arcrho_gateway.local.json")
        self.assertEqual(saved["workspace_root"], str(self.local))
        on_disk = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["workspace_root"], str(self.local))
        self.assertEqual([p["id"] for p in on_disk["profiles"]], ["default", "local", "other"])
        self.assertEqual(on_disk["paths"], {"projects_dir": "projects", "requests_dir": "requests"})
        api_config.activate_server_profile("other")
        self.assertEqual(api_config.gateway_config_path(), self.local / "other.json")

    def test_each_profile_keeps_the_address_it_signs_up_at(self) -> None:
        self._write_legacy_file()
        api_config.upsert_server_profile(
            name="Local test", root=str(self.local), profile_id="local", gateway_url="http://127.0.0.1:28767/",
        )
        self.assertEqual(api_config.gateway_url(), "")

        api_config.save_workspace_root(str(self.production), gateway_url="http://production:28767")
        self.assertEqual(api_config.gateway_url(), "http://production:28767")
        api_config.activate_server_profile("local")
        self.assertEqual(api_config.gateway_url(), "http://127.0.0.1:28767")
        with patch.dict(os.environ, {api_config.GATEWAY_URL_ENV: "http://launch:28767/"}):
            self.assertEqual(api_config.gateway_url(), "http://launch:28767")
        with self.assertRaises(ValueError):
            api_config.save_workspace_root(str(self.local), gateway_url="local-test")

    def test_launch_overrides_win_over_the_active_profile(self) -> None:
        self._write_legacy_file()
        api_config.upsert_server_profile(name="Local test", root=str(self.local), profile_id="local")
        api_config.activate_server_profile("local")
        launched = str(self.production / "launch.json")

        with patch.dict(os.environ, {
            api_config.GATEWAY_CONFIG_ENV: launched,
            api_config.SERVER_ROOT_ENV: str(self.production),
        }):
            self.assertEqual(api_config.gateway_config_path(), Path(launched))
            self.assertEqual(api_config.get_server_root(), self.production.resolve())

    def test_server_connection_save_moves_only_the_active_profile(self) -> None:
        self._write_legacy_file()
        api_config.upsert_server_profile(name="Local test", root=str(self.local), profile_id="local")
        api_config.activate_server_profile("local")
        moved = self.local / "moved"

        api_config.save_workspace_root(moved)

        cfg = api_config.load_workspace_config()
        self.assertEqual({p["id"]: p["root"] for p in cfg["profiles"]},
                         {"default": str(self.production), "local": str(moved)})
        self.assertEqual(cfg["workspace_root"], str(moved))

    def test_a_profile_needs_a_server_folder_and_a_plain_id(self) -> None:
        with self.assertRaises(ValueError):
            api_config.upsert_server_profile(name="Missing", root="")
        with self.assertRaises(ValueError):
            api_config.upsert_server_profile(name="Bad", root=str(self.local), profile_id="../x")
        with self.assertRaises(ValueError):
            api_config.activate_server_profile("unknown")
        self.assertFalse(self.config_path.exists())


if __name__ == "__main__":
    unittest.main()
