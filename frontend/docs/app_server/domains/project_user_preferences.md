# App Server Domain: Project User Preferences

## Purpose
<!-- MANUAL:BEGIN -->
Project user preference routes store per-Windows-user UI defaults inside each server project folder so shared-server preferences follow the project and user instead of local AppData.
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->
Routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/project-user-preferences?project_name=<name>` | Read the current Windows user's project preference JSON for a project. |
| `POST` | `/project-user-preferences` | Merge preference updates into the current Windows user's project preference JSON. |

Both routes run on the server host through the Gateway, as the `project_user_preferences` read and the `project_user_preferences_update` mutation (step 8 of [client_smb_retirement.md](../../../../docs/plans/client_smb_retirement.md)). The user is the login the request is signed with, never a payload field; a Client PC answers `503` when the Gateway is unavailable. An update is idempotent: each value the patch names replaces the stored one and nested objects merge key by key, so a repeat lands the same state and only `updated_at` moves. A caller may name key paths (`whole_values`) that replace outright instead of merging; the reserving-class tree's filter spec and preferences use it.
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `app_server/api/project_user_preferences_router.py` - Thin API routes.
- `app_server/schemas/project_user_preferences.py` - Update request schema.
- `app_server/services/project_user_preferences_service.py` - Project folder resolution and atomic preference writes using the shared user-identity service.
- `app_server/default_preferences/project_settings_preferences.json` - Repo-owned Project Settings table-width defaults intended for manual adjustment.
- `ui/shared/services/project_user_preferences.js` - Frontend loader/saver with debounced saves.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Preference file path: `projects/<project>/users/<windows-login>/preferences.json`; the Windows login folder uses the shared reversible `_%XX_` filename escaping rule for Windows-invalid filename characters.
- `lastReservingClassPath` stores the project-specific last Reserving Class path shared by Dataset Viewer, DFM objects, and future pages that use the same Reserving Class input.
- `datasetViewer` stores the project-specific last Dataset Name for Dataset Viewer.
- `datasetNamePicker` stores the Dataset Type picker `dsp-pref-pop` toggles (`doubleClickToSelect`, `closeAfterSelection`) for the current project/user.
- `dfmObject` stores the project-specific input dataset name, method name, output vector, and basic DFM settings used by DFM save/open defaults. It does not store its own Reserving Class path; it uses `lastReservingClassPath`.
- `reservingClassTree` stores shared reserving-class path picker user settings for the current project/user, including active `filterSpec`, `rcprefs-window` toggle/size/favorite preferences, and `hiddenPaths` from the `ptree-window` right-click hide/unhide menu. The `rcprefs-window` toggles persist as `auto_expand_single_child` and `hide_segment_labels`; obsolete auto-close fields are removed during preference normalization.
- `projectInstance` stores Project Instance UI defaults such as the right-panel dataset table layout. If a current project/user preference file is missing `projectInstance`, `GET /project-user-preferences` returns the `projectInstance` block from the default preferences JSON at `ARCRHO_PROJECT_INSTANCE_DEFAULT_PREFS_PATH` when set, otherwise from the repo-owned `app_server/default_preferences/project_instance_preferences.json` snapshot. Since the read runs on the Gateway, the defaults are the Gateway's copy.
- `projectSettings` stores Project Settings table defaults. If a current project/user preference file is missing `projectSettings`, `GET /project-user-preferences` returns the `projectSettings` block from `ARCRHO_PROJECT_SETTINGS_DEFAULT_PREFS_PATH` when set, otherwise from `app_server/default_preferences/project_settings_preferences.json`. The repo-owned file maps PS table IDs and visible column labels to default pixel widths.
- On read/write, legacy `datasetViewer.reservingClass`, `datasetViewer.path`, and `dfmObject.reservingClass` values are normalized into `lastReservingClassPath`, and those old per-feature keys are removed on the next preference write.
- Server-hosted project duplication copies the project-level `users/<windows-login>/preferences.json` tree into the duplicated project. Arco Engine also copies the materialized reserving-class folders under `data`; only canonical transient data-root folders are excluded.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- The folder name uses the login from the shared user-identity service: on the Gateway, the acting identity of the signed request; in a local server process, the process login. If that process runs under a service account, preferences it writes for itself follow that account.
- Project folders must be writable to create and atomically replace `users/<windows-login>/preferences.json`; otherwise UI preference saves remain non-blocking and the app continues with current in-memory/default values. Saves are serialized per preference path, use unique same-folder temporary files, and retry transient mapped-drive sharing violations. Persistent lock/access failures return `423`, while unreadable or invalid existing JSON is never replaced from an empty fallback.
<!-- MANUAL:END -->
