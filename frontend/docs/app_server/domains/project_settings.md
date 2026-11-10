# App Server Domain: project_settings

## Purpose
<!-- MANUAL:BEGIN -->
Project settings source and project-index management domain.
Also persists per-project Source Data date boundaries in `general_settings.json`.
Provides project-folder filesystem operations used by Project Settings tree actions (rename/duplicate/create/delete).
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.project_settings.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/general_settings` | `get_general_settings` | `str` | - | `project_settings_service.get_general_settings`, `workspace_read_client.run_workspace_read` |
| `POST` | `/general_settings` | `update_general_settings` | `GeneralSettingsUpdateRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.update_general_settings` |
| `POST` | `/general_settings/dates/job` | `submit_project_dates_change` | `ProjectDatesChangeRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_dates_job_service.submit_project_dates_job`, `workspace_mutation_client.run_workspace_mutation` |
| `GET` | `/general_settings/dates/job/status` | `get_project_dates_change_status` | `str` | - | `project_dates_job_service.get_project_dates_job_status`, `workspace_read_client.run_workspace_read` |
| `GET` | `/general_settings/dates/preview` | `preview_project_dates_change` | `str` | - | `project_dates_job_service.preview_project_dates_change`, `workspace_read_client.run_workspace_read` |
| `GET` | `/project_lock` | `get_project_lock` | `str` | - | `project_lock_service.get_project_lock`, `workspace_read_client.run_workspace_read` |
| `POST` | `/project_lock` | `set_project_lock` | `ProjectLockUpdateRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_lock_service.set_project_lock` |
| `GET` | `/project_settings` | `list_project_settings_sources` | - | - | `workspace_read_client.run_workspace_read` |
| `GET` | `/project_settings/{source}` | `get_project_settings` | `str` | - | `project_settings_service.get_project_settings`, `workspace_read_client.run_workspace_read` |
| `POST` | `/project_settings/{source}` | `update_project_settings` | `ProjectSettingsUpdateRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.update_project_settings` |
| `POST` | `/project_settings/{source}/create_project_folder` | `create_project_folder` | `CreateProjectFolderRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.create_project_folder` |
| `POST` | `/project_settings/{source}/delete_project_folder` | `delete_project_folder` | `DeleteProjectFolderRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.delete_project_folder` |
| `POST` | `/project_settings/{source}/duplicate_project_folder` | `duplicate_project_folder` | `DuplicateProjectFolderRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.duplicate_project_folder` |
| `POST` | `/project_settings/{source}/duplicate_project_folder/cancel/{request_id}` | `cancel_duplicate_project_folder` | `str` | - | `project_settings_service.cancel_duplicate_project_folder` |
| `GET` | `/project_settings/{source}/duplicate_project_folder/status/{request_id}` | `get_duplicate_project_folder_status` | `str` | - | `project_settings_service.get_duplicate_project_folder_status`, `workspace_read_client.run_polled_workspace_read` |
| `GET` | `/project_settings/{source}/folders` | `get_project_folders` | `str` | - | `project_settings_service.get_project_folders`, `workspace_read_client.run_workspace_read` |
| `POST` | `/project_settings/{source}/generated_dataset_cache/clear` | `clear_generated_dataset_csv_caches` | `GeneratedDatasetCacheClearRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.clear_generated_dataset_csv_caches` |
| `POST` | `/project_settings/{source}/open_project_folder` | `open_project_folder` | `OpenProjectFolderRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.open_project_folder` |
| `POST` | `/project_settings/{source}/rename_project_folder` | `rename_project_folder` | `RenameProjectFolderRequest` | [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) | `project_settings_service.rename_project_folder` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.project_settings.key_files -->
- [`app_server/api/project_settings_router.py`](../../../app_server/api/project_settings_router.py) - Project settings CRUD and folder ops routes.
- [`app_server/services/project_settings_service.py`](../../../app_server/services/project_settings_service.py) - Project settings persistence service.
- [`app_server/schemas/project_settings.py`](../../../app_server/schemas/project_settings.py) - Project settings request schemas.
- [`ui/project_settings/project_settings.js`](../../../ui/project_settings/project_settings.js) - Frontend caller for project settings endpoints.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Heavily used by `project_settings.js` UI flows.
- Provides `/general_settings` read/write for Source Data Origin/Development boundary values.
- The GET routes (`/project_settings`, `/project_settings/{source}`, `/project_settings/{source}/folders`, `/general_settings`) read on the server host through the Gateway as the `project_settings_sources`, `project_registry`, `project_folders` and `general_settings` hosted reads; a Client PC answers `503` rather than reading the share (see [`workspace_reads`](workspace_reads.md)).
- Provides project-folder CRUD-style endpoints under `/project_settings/{source}/*_project_folder` (including empty-folder creation for new-project tree action).
- The writes — folder create, rename and delete, the registry save, the General Settings save and the generated CSV cache clear — run on the server host through the Gateway as the `project_folder_create`, `project_folder_rename`, `project_folder_delete`, `project_registry_save`, `general_settings_save` and `generated_dataset_cache_clear` workspace mutations; a Client PC answers `503` rather than writing the share. The first five are not idempotent, so each carries a Gateway receipt keyed by the signed user and request id: a repeat of the same request (a body `request_id`, or the transport's one resend after a lost answer) answers with the first outcome instead of creating, renaming or deleting twice (see [`workspace_mutations`](workspace_mutations.md)).
- A project duplication is submitted, polled and cancelled on the server host through the Gateway: the `project_duplication_submit` and `project_duplication_cancel` workspace mutations and the `project_duplication_status` read, so a Client PC never touches the duplication's receipt, request, status or cancel files. The submit needs no Gateway receipt, because the duplication's own submission receipt already makes a request id replay return the same job; the id also travels as the mutation's own. Without the Gateway the submit and the cancel answer `503`, and a status poll answers `{ok, job_id, unknown: true}`, which the page treats as "ask again": it keeps polling and does not count the gap against its stalled-copy rule. The request and cancel marker name the signed user, not the server process.
- Provides `GET /project_lock` and `POST /project_lock` (`project_lock_service`) for the project lock. The read is the `project_lock` hosted read and the toggle is the `project_lock_set` workspace mutation, which carries a receipt because it appends an audit entry. A locked project refuses, with `423` and one message (`PROJECT_LOCKED_MESSAGE`), every save of a method or dataset, every project-data workspace mutation (imports, source profile, field mapping, dataset and reserving class types, data-processing rules, General Settings, dataset delete and review status, ResQ import publish, project folder rename and delete) and the apply step of a ResQ synchronization. Saves reach the check through `require_reserving_class_writable` and `require_project_scope_writable`; mutations reach it through `require_mutation_allowed`, which reads the covered kinds from `WorkspaceMutationKind.locked_project_arg`. Each user's own preferences, caches, previews and exports to ResQ are not project data and stay allowed.
- Provides `POST /project_settings/{source}/open_project_folder` for opening a selected project directory in the host OS file explorer. It stays on the client, because it hands a path to a program on this PC.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Handles project-index CRUD and settings JSON writes. Project names and virtual UI folders live in `projects/index.json`; source table paths live in each project's `field_mapping.json` and are never touched by registry reads or writes.
- `GET /project_settings/{source}` serves the registry as `folders` plus `project_paths` (each path's leaf segment is the project name) with the registry `revision` - one index read, no per-project file access. `POST /project_settings/{source}` is the authoritative registry write: `project_paths` is the complete project list (projects absent from it are removed), `folders` adds empty virtual folders, and `expected_revision` is the revision the caller read. The server owns the revision: it is stored in `index.json` (absent reads as 0), a save naming any other revision is refused with `409`, and a save moves it by one under a process lock, so the compare and the write are one step on the host that runs them. `GET /project_settings/{source}/folders` remains a read-only registry view for shared pickers. The write publishes a temp file over `index.json`; because Windows refuses that swap while any other handle (even a reader) is open, the swap is retried five times over about two seconds before the route reports `423`, and the duplicate-project finalizer retries a `423` twice more before surfacing it.
- `get_general_settings` serves repeat reads of an unchanged `general_settings.json` from the shared mtime-validated in-memory cache (`app_server/services/file_read_cache.py`); any timestamp or size change, including atomic replacement by settings saves, forces a fresh read, and recently written files are always re-read.
- Handles project folder open requests by resolving the project directory through config path helpers before launching OS file explorer.
- `create_project_folder` creates an empty project folder plus a `data` subfolder; client coordinates rollback if later folder-structure/settings saves fail.
- `POST /project_settings/{source}/duplicate_project_folder` validates the client request ID, logical source/target names, and normalized server-root-relative projects-directory setting, then writes a canonical location-independent submission receipt before atomically publishing the queued `ArcRhoDuplicateProject` v1 request under the fixed `<server-root>/requests` Engine protocol. An identical request-ID replay returns `202` from that receipt, repairs only missing queued publication, and never overwrites a valid Engine processing or terminal status; reusing the ID for different logical input or a different projects-directory setting returns `409`.
- `POST /project_settings/{source}/duplicate_project_folder/cancel/{request_id}` asks the Engine to stop a queued or running duplicate by publishing a location-independent cancel marker under `<server-root>/requests/project_duplication/cancel/`. The Engine reads the marker between copy steps and, when it finds it before the staging folder is renamed into place, discards the staging folder and publishes a terminal `cancelled` status; a job that already reached `success`, `error`, or `cancelled` is reported as-is with `cancel_requested: false`, and the marker is cleared with the rest of the job's durable metadata.
- `GET /project_settings/{source}/duplicate_project_folder/status/{request_id}` reads and validates the matching atomic Engine status. Request and status payloads are owned by `python-api/src/arcrho_project_duplication_contract.py`, contain no client-local paths, and derive their protocol locations from the configured ArcRho Server root.
- Arco Engine copies project-level files and materialized reserving-class folders on the server host, excludes the transient `data/.arcrho-resq-import-staging` and `data/tmp` folders, and exposes a target folder only after its same-parent staging copy completes.
- `POST /project_settings/{source}/generated_dataset_cache/clear` clears project `data/*/datasets/*.csv` files during Source Data refresh while preserving CSVs identified by canonical scalar `index.json` entries with `source_kind: input`. Independent reserving-class scans/deletes use bounded parallelism, sidecar and method JSON remain unchanged, and each affected reserving class is rebuilt through the canonical index producer under the shared update lock before the request completes or reports a partial-delete failure.
- Handles per-project `general_settings.json` persistence in each project folder.
- Normalizes stored Origin/Development boundary values to plain integer strings (no commas, no trailing `.0`/`.00`).
- Stores `auto_generated` in `general_settings.json`; the app server writes `project_name` as current project folder name to detect stale duplicated files.
- Stores the project lock in `project_lock.json` in the project folder: `{locked, locked_by, locked_at}` while locked, `{locked: false}` after an unlock. A missing file means unlocked. A duplicated project copies the file, so a copy of a locked project starts locked.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add source key support: update router path params + service source resolution.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Folder operation rollbacks can leave partial state when interrupted.
<!-- MANUAL:END -->
