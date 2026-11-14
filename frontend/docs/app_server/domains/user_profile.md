# App Server Domain: user_profile

## Purpose
<!-- MANUAL:BEGIN -->
What the signed-in user keeps on the Arco Server: their preferences and their ArcBot chats.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.user_profile.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/arcbot/chat-session/delete` | `delete_arcbot_chat_session` | `ArcBotChatSessionIdRequest` | [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) | `arcbot_chat_store_service.delete_chat_session`, `workspace_mutation_client.run_workspace_mutation` |
| `POST` | `/arcbot/chat-session/load` | `load_arcbot_chat_session` | `ArcBotChatSessionIdRequest` | [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) | `arcbot_chat_store_service.read_chat_session`, `workspace_read_client.run_workspace_read` |
| `POST` | `/arcbot/chat-session/save` | `save_arcbot_chat_session` | `ArcBotChatSessionSaveRequest` | [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) | `arcbot_chat_store_service.save_chat_session`, `workspace_mutation_client.run_workspace_mutation` |
| `GET` | `/arcbot/chat-sessions` | `list_arcbot_chat_sessions` | - | - | `workspace_read_client.run_workspace_read` |
| `GET` | `/user-preferences/{section}` | `get_user_preference_section` | `str` | - | `workspace_read_client.run_workspace_read` |
| `POST` | `/user-preferences/{section}` | `save_user_preference_section` | `UserPreferenceSectionSaveRequest` | [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) | `server_user_profile_service.update_preferences`, `workspace_mutation_client.run_workspace_mutation` |
| `POST` | `/user-profile/import-local` | `import_local_profile` | `LocalProfileImportRequest` | [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) | `local_profile_import_service.import_local_profile` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.user_profile.key_files -->
- [`app_server/api/user_profile_router.py`](../../../app_server/api/user_profile_router.py) - HTTP routes for the signed-in user's preferences and ArcBot chats, and the one-time import from this PC.
- [`app_server/services/server_user_profile_service.py`](../../../app_server/services/server_user_profile_service.py) - The user's folder on the server and the sectioned preferences file in it.
- [`app_server/services/arcbot_chat_store_service.py`](../../../app_server/services/arcbot_chat_store_service.py) - The user's ArcBot chats, one file each.
- [`app_server/services/scripting_preferences_service.py`](../../../app_server/services/scripting_preferences_service.py) - The scripting and shell preference sections.
- [`app_server/services/local_profile_import_service.py`](../../../app_server/services/local_profile_import_service.py) - Sends what an older app left on the PC to the server, once.
- [`app_server/schemas/user_profile.py`](../../../app_server/schemas/user_profile.py) - User profile request models.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Called by the desktop host (`electron/main.js`, `electron/arcbot_host.js`) and, for the scripting and shell sections, by the pages through `/scripting/preferences` and `/local-project/preferences`.
- Every route runs on the server host through the Gateway for the login the request is signed with; a Client PC answers 401 or 503 and never opens the folder over the share.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Everything lives under `<workspace_root>\users\<login>`: `preferences.json` (one section per preference, each written whole), `arcbot\sessions` (one file per chat) and `dashboards` (owned by the dashboard domain).
- The login is never an argument, so a user reads and writes only their own folder.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a preference that follows the user: pick a section name, load and save it through `/user-preferences/{section}`, and add its old file to `LEGACY_PREFERENCE_FILES` only if an older app wrote one.
2. Add another kind of user file: a service that builds its path with `server_user_profile_service.user_folder`, registered as hosted read and mutation kinds.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A preference that is a path on one PC (favourite folders, recent files) or that standalone Arcode shares stays in `%APPDATA%\Arco\prefs`; do not move it here.
- A test that runs one of these services must pin `ARCRHO_RUNTIME_SERVER_ROOT` to its own folder, or it writes into the real server root.
<!-- MANUAL:END -->
