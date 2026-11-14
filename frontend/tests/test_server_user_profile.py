"""The signed-in user's folder on the Arco Server: preferences, chats, dashboards.

Each service runs on the server host for the login a request is signed with.
A Client PC reaches them only through registered hosted kinds, and what an
older app left on the PC is sent to the server once and then removed.
"""

from __future__ import annotations

import inspect
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
for path in (FRONTEND_ROOT, REPOSITORY_ROOT / "python-api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api import config as api_config  # noqa: E402
from arcrho_workspace_mutation_contract import (  # noqa: E402
    MAX_LARGE_WORKSPACE_MUTATION_REQUEST_BYTES,
    MAX_WORKSPACE_MUTATION_REQUEST_BYTES,
    WORKSPACE_MUTATION_KINDS,
    build_workspace_mutation_request,
)
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS, build_workspace_read_request  # noqa: E402
from app_server import config  # noqa: E402
from app_server.services import (  # noqa: E402
    arcbot_chat_store_service,
    dashboard_service,
    local_profile_import_service,
    scripting_preferences_service,
    server_user_profile_service,
    user_identity_service,
)

TEST_TEMP_ROOT = REPOSITORY_ROOT / "tmp_data"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

USER_READ_KINDS = (
    "user_preferences",
    "scripting_preferences",
    "shell_preferences",
    "arcbot_chat_sessions",
    "arcbot_chat_session",
    "dashboard_user_list",
    "dashboard_user_load",
    "dashboard_user_library",
)
USER_MUTATION_KINDS = (
    "user_preferences_update",
    "scripting_preferences_save",
    "shell_preferences_save",
    "arcbot_chat_session_save",
    "arcbot_chat_session_delete",
    "dashboard_user_save",
    "dashboard_user_delete",
    "dashboard_user_library_save",
    "dashboard_user_library_delete",
)


def _dashboard(name: str = "Review") -> dict:
    return {"format": "arco-dashboard", "name": name, "sources": [], "pages": []}


class ServerUserFolderTestCase(unittest.TestCase):
    """Runs the services as the server host does, as the user ``alice``."""

    login = "alice"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "server"
        self.root.mkdir()
        self._start(patch.dict(os.environ, {api_config.RUNTIME_SERVER_ROOT_ENV: str(self.root)}))
        self._start(user_identity_service.acting_identity(self.login))
        self.user_dir = self.root / "users" / self.login

    def _start(self, context) -> None:
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)


class RegisteredKindTests(unittest.TestCase):
    def test_every_kind_names_a_service_function_that_takes_its_arguments(self) -> None:
        for table, kinds in ((WORKSPACE_READ_KINDS, USER_READ_KINDS), (WORKSPACE_MUTATION_KINDS, USER_MUTATION_KINDS)):
            for kind in kinds:
                spec = table[kind]
                function = getattr(importlib.import_module(f"app_server.services.{spec.module}"), spec.function)
                self.assertEqual(set(inspect.signature(function).parameters), set(spec.allowed), kind)

    def test_no_kind_takes_the_login_as_an_argument(self) -> None:
        for table, kinds in ((WORKSPACE_READ_KINDS, USER_READ_KINDS), (WORKSPACE_MUTATION_KINDS, USER_MUTATION_KINDS)):
            for kind in kinds:
                self.assertFalse({"user", "user_name", "login", "login_name"} & set(table[kind].allowed), kind)

    def test_requests_build_and_only_whole_documents_get_the_large_budget(self) -> None:
        build_workspace_read_request(request_id="a" * 32, read_kind="user_preferences", kwargs={}, user_name="alice")
        build_workspace_mutation_request(
            request_id="a" * 32,
            mutation_kind="dashboard_user_save",
            kwargs={"name": "Review", "data": _dashboard(), "prev_name": "", "overwrite": False},
            user_name="alice",
        )
        large = {kind for kind, spec in WORKSPACE_MUTATION_KINDS.items() if spec.large_request}
        self.assertEqual(large, {"arcbot_chat_session_save", "dashboard_user_save"})
        self.assertEqual(
            WORKSPACE_MUTATION_KINDS["dashboard_user_save"].max_request_bytes,
            MAX_LARGE_WORKSPACE_MUTATION_REQUEST_BYTES,
        )
        self.assertEqual(
            WORKSPACE_MUTATION_KINDS["user_preferences_update"].max_request_bytes,
            MAX_WORKSPACE_MUTATION_REQUEST_BYTES,
        )


class PreferencesTests(ServerUserFolderTestCase):
    def test_a_save_replaces_the_sections_it_names_and_keeps_the_rest(self) -> None:
        server_user_profile_service.update_preferences({"tableColors": {"fonts": {"a": 1}}, "macros": {"order": ["x"]}})
        server_user_profile_service.update_preferences({"tableColors": {"components": {}}})

        data = server_user_profile_service.get_preferences()["data"]
        self.assertEqual(data["tableColors"], {"components": {}})
        self.assertEqual(data["macros"], {"order": ["x"]})
        self.assertEqual(Path(server_user_profile_service.user_folder("preferences.json")), self.user_dir / "preferences.json")

        server_user_profile_service.update_preferences({"macros": None})
        self.assertNotIn("macros", server_user_profile_service.get_preferences()["data"])

    def test_each_user_has_their_own_folder(self) -> None:
        server_user_profile_service.update_preferences({"notesPanel": {"width": 900}})
        with user_identity_service.acting_identity("bob"):
            self.assertEqual(server_user_profile_service.get_preferences()["data"], {})
            self.assertEqual(Path(server_user_profile_service.user_folder()), self.root / "users" / "bob")

    def test_scripting_and_shell_preferences_merge_into_their_own_sections(self) -> None:
        scripting_preferences_service.save_preferences({"execTime": True})
        scripting_preferences_service.save_preferences({"wrap": False})
        self.assertEqual(scripting_preferences_service.get_preferences(), {"execTime": True, "wrap": False})

        scripting_preferences_service.save_local_project_preferences({"projectName": "P1", "recentProjectNames": ["P1"]})
        scripting_preferences_service.save_local_project_preferences({"projectName": "P2", "recentProjectNames": ["P2"]})
        shell = scripting_preferences_service.get_local_project_preferences()
        self.assertEqual((shell["projectName"], shell["recentProjectNames"]), ("P2", ["P2", "P1"]))

        stored = json.loads((self.user_dir / "preferences.json").read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {"scripting", "shell", "updated_at"})

    def test_a_client_pc_without_a_gateway_reads_nothing_from_the_share(self) -> None:
        env = {key: value for key, value in os.environ.items() if key != api_config.RUNTIME_SERVER_ROOT_ENV}
        with patch.dict(os.environ, env, clear=True), self.assertRaises(HTTPException) as refused:
            scripting_preferences_service.get_local_project_preferences()
        self.assertEqual(refused.exception.status_code, 401)


class ArcBotChatStoreTests(ServerUserFolderTestCase):
    def test_save_list_read_and_delete(self) -> None:
        session = {"id": "chat-20260101000000-ab12cd34", "title": "Hello", "updatedAt": "2", "messages": [{"role": "user"}]}
        arcbot_chat_store_service.save_chat_session(session)
        self.assertTrue((self.user_dir / "arcbot" / "sessions" / f"{session['id']}.json").is_file())

        listed = arcbot_chat_store_service.list_chat_sessions()["sessions"]
        self.assertEqual([(item["id"], item["title"], item["messageCount"], item["archived"]) for item in listed],
                         [(session["id"], "Hello", 1, False)])
        self.assertEqual(arcbot_chat_store_service.read_chat_session(session["id"])["session"], session)

        self.assertTrue(arcbot_chat_store_service.delete_chat_session(session["id"])["deleted"])
        self.assertFalse(arcbot_chat_store_service.delete_chat_session(session["id"])["deleted"])
        self.assertIsNone(arcbot_chat_store_service.read_chat_session(session["id"])["session"])

    def test_an_id_that_is_not_a_chat_id_is_refused(self) -> None:
        for bad in ("", "..\\..\\preferences", "a/b", "a.b"):
            with self.assertRaises(HTTPException):
                arcbot_chat_store_service.read_chat_session(bad)
        with self.assertRaises(HTTPException):
            arcbot_chat_store_service.save_chat_session({"id": "..\\x"})


class LocalProfileImportTests(ServerUserFolderTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.appdata = Path(self.temp.name) / "appdata"
        self.profile = Path(self.temp.name) / "profile"
        self.documents = Path(self.temp.name) / "documents"
        for target, value in (("_get_user_appdata_dir", self.appdata), ("_get_user_documents_dir", self.documents)):
            self._start(patch.object(config, target, return_value=str(value)))

    def _write(self, path: Path, data: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_local_files_move_to_the_server_once(self) -> None:
        colors = self._write(self.appdata / "prefs" / "table_colors.json", {"fonts": {"a": 1}})
        shell = self._write(self.appdata / "local_project_prefs.json", {"projectName": "P1"})
        kept = self._write(self.appdata / "prefs" / "home_folders.json", {"folders": ["C:\\Work"]})
        chat = self._write(self.profile / "arcbot_chat_sessions" / "chat-1.json", {"id": "chat-1", "title": "Hi"})
        board = self._write(self.documents / "dashboards" / "Review.arcdash", _dashboard())
        asset = self._write(
            self.documents / "dashboards" / "library" / "My KPI.json", {"name": "My KPI", "widget": {"type": "kpi"}}
        )

        result = local_profile_import_service.import_local_profile(str(self.profile))
        self.assertEqual((result["preferences"], result["chats"], result["dashboards"]), (2, 1, 2))
        for moved in (colors, shell, chat, board, asset):
            self.assertFalse(moved.exists(), moved)
        self.assertTrue(kept.exists())

        stored = server_user_profile_service.get_preferences()["data"]
        self.assertEqual(stored["tableColors"], {"fonts": {"a": 1}})
        self.assertEqual(stored["shell"], {"projectName": "P1"})
        self.assertEqual(arcbot_chat_store_service.read_chat_session("chat-1")["session"]["title"], "Hi")
        self.assertEqual(dashboard_service.list_user_dashboards()["dashboards"][0]["path"], "Review.arcdash")
        self.assertEqual(dashboard_service.list_user_library()["assets"][0]["id"], "user:My KPI")

        again = local_profile_import_service.import_local_profile(str(self.profile))
        self.assertEqual((again["preferences"], again["chats"], again["dashboards"]), (0, 0, 0))

    def test_what_the_server_already_holds_is_never_overwritten(self) -> None:
        server_user_profile_service.update_preferences({"tableColors": {"fonts": {"server": 1}}})
        dashboard_service.save_user_dashboard("Review", {**_dashboard(), "description": "server"})
        colors = self._write(self.appdata / "prefs" / "table_colors.json", {"fonts": {"pc": 1}})
        board = self._write(self.documents / "dashboards" / "Review.arcdash", {**_dashboard(), "description": "pc"})

        local_profile_import_service.import_local_profile(str(self.profile))

        self.assertEqual(server_user_profile_service.get_preferences()["data"]["tableColors"], {"fonts": {"server": 1}})
        self.assertFalse(colors.exists())
        self.assertEqual(dashboard_service.load_user_dashboard("Review.arcdash")["data"]["description"], "server")
        # A dashboard is the user's work, so the PC's copy stays where it is.
        self.assertTrue(board.exists())

    def test_a_server_that_cannot_be_reached_leaves_the_pc_untouched(self) -> None:
        colors = self._write(self.appdata / "prefs" / "table_colors.json", {"fonts": {"a": 1}})
        env = {key: value for key, value in os.environ.items() if key != api_config.RUNTIME_SERVER_ROOT_ENV}
        with patch.dict(os.environ, env, clear=True), self.assertRaises(HTTPException):
            local_profile_import_service.import_local_profile(str(self.profile))
        self.assertTrue(colors.exists())


if __name__ == "__main__":
    unittest.main()
