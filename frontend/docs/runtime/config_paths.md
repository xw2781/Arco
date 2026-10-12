# Runtime: Config and Path Resolution

## Purpose
<!-- MANUAL:BEGIN -->
Document path/config setup, AppData-backed workspace path persistence, and runtime path refresh behavior.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN runtime.config_paths.entry_points -->
- Path/config helper functions in `app_server/config.py`:
  - `_find_existing_project_dir`
  - `_get_macro_dir`
  - `_get_macro_library_dir`
  - `_get_project_map_dir`
  - `_get_requests_dir`
  - `_get_scripting_dir`
  - `_get_user_appdata_cache_dir`
  - `_get_user_appdata_dir`
  - `_get_user_local_appdata_dir`
  - `_get_workflow_dir`
  - `_sanitize_project_dir_name`
  - `clear_runtime_path_caches`
  - `get_audit_log_path`
  - `get_client_read_latency_log_path`
  - `get_client_save_latency_log_path`
  - `get_client_temp_dir`
  - `get_data_processing_rules_path`
  - `get_data_processing_values_path`
  - `get_dataset_number_formats_path`
  - `get_dataset_types_path`
  - `get_field_mapping_path`
  - `get_gateway_config_path`
  - `get_gateway_url`
  - `get_general_settings_path`
  - `get_local_project_prefs_path`
  - `get_mssql_connections_path`
  - `get_path`
  - `get_project_data_dir`
  - `get_project_dataset_cache_dir`
  - `get_project_dataset_sidecar_dir`
  - `get_project_instance_default_preferences_path`
  - `get_project_lock_path`
  - `get_project_master_table_path`
  - `get_project_method_data_dir`
  - `get_project_reserving_class_data_dir`
  - `get_project_settings_default_preferences_path`
  - `get_project_settings_workbook_path`
  - `get_project_source_dir`
  - `get_project_source_import_path`
  - `get_project_temporary_view_dataset_cache_dir`
  - `get_reserving_class_combinations_path`
  - `get_reserving_class_types_path`
  - `get_reserving_class_values_path`
  - `get_root_path`
  - `get_scripting_prefs_path`
  - `get_table_summary_cache_path`
  - `get_username_index_path`
  - `load_workspace_paths`
  - `refresh_runtime_paths`
  - `save_workspace_paths`
  - `workspace_paths_file_exists`
- Workspace path config routes:
  - `POST` `/server/start` handled by `start_server`
  - `GET` `/server/status` handled by `get_server_component_status`
  - `POST` `/server/stop` handled by `stop_server`
  - `GET` `/server_profiles` handled by `get_server_profiles`
  - `POST` `/server_profiles` handled by `save_server_profile`
  - `POST` `/server_profiles/activate` handled by `activate_server_profile`
  - `GET` `/server_profiles/health` handled by `get_server_health`
  - `GET` `/server_profiles/inspect` handled by `inspect_server_folder`
  - `POST` `/server_profiles/sign_in` handled by `sign_in_again`
  - `GET` `/workspace_paths` handled by `get_workspace_paths`
  - `POST` `/workspace_paths` handled by `update_workspace_paths`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN runtime.config_paths.key_files -->
- [`app_server/config.py`](../../app_server/config.py) - Primary runtime path + config module, including AppData workspace path persistence.
- [`app_server/api/workspace_paths_router.py`](../../app_server/api/workspace_paths_router.py) - HTTP interface for workspace path updates.
- [`app_server/main.py`](../../app_server/main.py) - App bootstrap and static path mounting.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Frontend shell settings modal calls `/workspace_paths` routes.
- App-server modules import `app_server.config` for runtime path resolution.
- On first-time setup, the Electron shell searches `D:\ArcRho Server` through `Z:\ArcRho Server` and fills the Server Connection root path when found.
- Saving Server Connection hot-applies the new config by refreshing `app_server.config` runtime globals and notifying open UI frames; app restart is not required for new server requests.
- ArcRho startup and Server Connection saves attempt first-run Gateway sign-up when the local credential is absent. The address comes from `ARCRHO_GATEWAY_URL` or the active profile's `gateway_url` (the Server Connection dialog and the Server tab ask for it); the app probes it, signs up through the Gateway's Windows-authenticated `POST /api/enroll`, and writes `%APPDATA%\ArcRho\arcrho_gateway.json` with the secret the Gateway returned. The shared registry is never read from a client.
- DFM RPC Bridge writes request files under `<workspace_root>/<requests_dir>/RPC bridge` and expects remote DFM/SyncDFM JSON files under `<workspace_root>/<projects_dir>/<project>/data/<ReservingClassFolder>/methods/tmp_rpc`.
- Dataset number-format preferences are read from `<workspace_root>/config/dataset_number_formats.json`; `ARCRHO_DATASET_NUMBER_FORMATS_PATH` may override this path for migration tooling or controlled deployments.
- `ARCRHO_RUNTIME_SERVER_ROOT` is a trusted process-only override for server-owned workers. It takes precedence over the user-local AppData workspace preference, is never persisted, and lets the deployed ResQ Bridge calculate processing provenance against its own shared ArcRho Server root.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- `%APPDATA%\ArcRho\workspace_paths.json` is the persistent user-local source-of-truth for workspace root/path mapping. It holds a list of server profiles (`profiles`, each `id`, `name`, `root`, optional `gateway_config` and `gateway_url`) and the `active_profile`; `workspace_root` mirrors the active profile's root. A file with no list reads as one `default` profile, built in memory and never written back. `arcrho_api.config` owns the file and its shape.
- Each server profile has its own Gateway credential: `%APPDATA%\ArcRho\arcrho_gateway.json` for the `default` profile, `arcrho_gateway.<id>.json` for any other, unless the profile names a file. `ARCRHO_GATEWAY_CONFIG` outranks the active profile, as `ARCRHO_SERVER_ROOT` outranks its root, and `ARCRHO_GATEWAY_URL` outranks its address. The Excel add-in's credential helper always uses `arcrho_gateway.json` and signs up at the `default` profile's address unless given `--url`.
- `%APPDATA%\ArcRho\arcrho_gateway.json` is an authoritative per-user, per-PC pilot credential. Existing files are never replaced automatically, so `enabled: false` remains an explicit opt-out. `<workspace_root>/config/arcrho_gateway.json` is the server-only HMAC user registry, with no save-kind allowlist — the supported kinds are derived from `SAVE_JOB_KINDS`. Only the Gateway's sign-up route and the server-side tools (`configure_pilot.py`, `tools/local_server.py init`) write it, under a lock so concurrent sign-ups cannot lose users; the released app still reads it over the share until users update.
- `ARCRHO_RUNTIME_SERVER_ROOT`, when set by a trusted worker, supersedes the persisted root only for that process. It is not a user preference and must not be written back to `%APPDATA%`. The workspace-read client also treats its presence as "this is a server process" and never routes a read to the gateway from such a process.
- `%LOCALAPPDATA%\ArcRho\logs\client_save_latency.jsonl` and `client_read_latency.jsonl` (`get_client_save_latency_log_path`, `get_client_read_latency_log_path`) hold the per-operation transport diagnostics for hosted saves and Server-hosted workspace reads; both rotate at 5 MB with three backups and never contain project data.
- If the AppData workspace path file does not exist yet, the app uses built-in defaults until the Server Connection setting is saved.
- Runtime globals in `app_server/config.py` are refreshed from config after `/workspace_paths` updates.
- The workspace-global `config/dataset_number_formats.json` stores a fallback display format plus reserving-class/Dataset Type Name overrides shared by ResQ migration and frontend dataset generation. Override rows use `reserving_class`, `dataset_type_name`, and `number_format`; they are not keyed by dataset instance Name and are not project-specific.
- In-memory runtime caches that contain absolute workspace paths, including the app-server dataset registry, are cleared after `/workspace_paths` updates.
- Request-result waits use direct polling for UNC and mapped Windows network paths, while local-drive paths may use file-event watching. Every wait shares one timeout budget so an event-watch fallback cannot extend a caller's requested timeout.
- Dataset valid-value caches and the DFM root-path cache are cleared or replaced when the shell broadcasts a Server Connection update.
- User-local fixed paths are also refreshed in `app_server/config.py`, including workflow export path (`~/Documents/ArcRho/workflows`), scripting notebook path (`~/Documents/ArcRho/scripts`), and Macro window path (`~/Documents/ArcRho/macros`).
- Project, reserving-class, dataset, DFM method, workflow, and project-user folder/file components encode Windows-invalid filename characters with the reversible `_%XX_` rule, for example `/` becomes `_%2F_`, `:` becomes `_%3A_`, and ASCII control characters use their two-digit hex code. Backend paths use `app_server.config.encode_filename_segment`; direct renderer-side file paths use the shared `/ui/shared/filename_sanitizer.js` helper so DFM, Dataset, and future pages follow the same convention.
- ArcoTri generated dataset CSV caches use `projects/<project>/data/<ReservingClassFolder>/datasets/<DatasetName>@<OriginLength>@<DevelopmentLength>@<cum|inc>@<dev|cal>.csv` with one base `sidecars/<DatasetName>.json` sidecar, so period length, cumulative/incremental, and development/calendar shape changes rebuild separate CSV caches without creating extra metadata files. Runtime cache creation writes the sidecar only if it is missing; the Dataset page Save button updates saved period lengths, cumulative/calendar/transposed settings, and user fields. Dataset sidecars record the current Windows login user in `user` and `modified_by` for Project Instance's `User` column.
- Project Instance Temporary view uses a separate durable CSV cache at `projects/<project>/data/<ReservingClassFolder>/datasets/.temporary-view/`. It reuses a valid canonical cache when available; otherwise generated or derived output is retained in that folder after the UI closes. Temporary-view output never creates a sidecar or an `index.json` entry and never triggers an index rebuild.
- DFM local method files use `projects/<project>/data/<ReservingClassFolder>/methods/DFM@<Name>.json`; within one project/reserving-class pair, the DFM `Name` is the sole local instance identity. DFM RPC Bridge remote responses use `data/<ReservingClassFolder>/methods/tmp_rpc/DFM@<Name>.json`, while remote-update status files start with `SyncDFM@`.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a new configurable path: update the AppData `workspace_paths.json` contract + `app_server/config.py` getters.
2. Change path refresh behavior: validate all services that depend on runtime globals.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Path changes affect every filesystem-backed domain.
- Environment-specific path assumptions can break packaged deployments.
<!-- MANUAL:END -->
