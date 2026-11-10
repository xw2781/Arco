# Runtime: Data and Cache Files

## Purpose
<!-- MANUAL:BEGIN -->
Index cache/data files and refresh points used by app-server services.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN runtime.data_cache_files.entry_points -->
| Method | Path | Domain | Handler |
| --- | --- | --- | --- |
| `POST` | `/arcrho/headers/cache/clear` | `arcrho` | `clear_arcrho_headers_cache` |
| `POST` | `/arcrho/tri/refresh` | `arcrho` | `arcrho_tri_refresh` |
| `POST` | `/arcrho/vec/refresh` | `arcrho` | `arcrho_vec_refresh` |
| `POST` | `/bootstrap/refresh` | `bootstrap` | `refresh_bootstrap` |
| `POST` | `/dataset/cache/load` | `dataset` | `load_dataset_cache` |
| `GET` | `/datasets/cached` | `dataset` | `list_cached_dataset_names` |
| `POST` | `/datasets/cached/delete` | `dataset` | `delete_cached_datasets` |
| `POST` | `/datasets/cached/empty` | `dataset` | `create_empty_cached_dataset` |
| `GET` | `/datasets/cached/index-signature` | `dataset` | `get_cached_dataset_index_signature` |
| `POST` | `/dependent_propagation/refresh_dependents` | `dependent_propagation` | `submit_refresh_dependents_job` |
| `GET` | `/dependent_propagation/refresh_dependents/status/{request_id}` | `dependent_propagation` | `get_refresh_dependents_job_status` |
| `POST` | `/excel_links/refresh` | `excel_link` | `excel_links_refresh` |
| `POST` | `/excel_links/refresh/plan` | `excel_link` | `plan_excel_links_refresh` |
| `POST` | `/project_settings/{source}/generated_dataset_cache/clear` | `project_settings` | `clear_generated_dataset_csv_caches` |
| `POST` | `/source_table/refresh` | `source_table` | `refresh_source_table` |
| `POST` | `/source_table/refresh_job` | `source_table` | `submit_source_refresh_job` |
| `GET` | `/source_table/refresh_job/plan` | `source_table` | `get_source_refresh_plan` |
| `GET` | `/source_table/refresh_job/status` | `source_table` | `get_source_refresh_job_status` |
| `GET` | `/table_summary` | `table_summary` | `get_table_summary` |
| `POST` | `/table_summary/refresh` | `table_summary` | `refresh_table_summary` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN runtime.data_cache_files.key_files -->
- [`app_server/config.py`](../../app_server/config.py) - Cache/data file names and lock constants.

Cache/lock constants detected:
- `AUDIT_LOG_FILE`
- `CLIENT_READ_LATENCY_LOG_FILE`
- `CLIENT_SAVE_LATENCY_LOG_FILE`
- `DATASET_NUMBER_FORMATS_FILE`
- `DATASET_TYPES_FILE`
- `DATA_PROCESSING_RULES_FILE`
- `DATA_PROCESSING_VALUES_FILE`
- `FIELD_MAPPING_FILE`
- `GENERAL_SETTINGS_FILE`
- `LOCAL_PROJECT_PREFS_FILE`
- `PROJECT_INDEX_FILE`
- `PROJECT_LOCK_FILE`
- `PROJECT_SETTINGS_XLSX_FILE`
- `PROJECT_USER_PREFERENCES_FILE`
- `RESERVING_CLASS_COMBINATIONS_FILE`
- `RESERVING_CLASS_TYPES_FILE`
- `RESERVING_CLASS_VALUES_FILE`
- `SCRIPTING_PREFS_FILE`
- `TABLE_SUMMARY_CACHE_FILE`
- `USERNAME_INDEX_FILE`
- `_AUDIT_LOG_LOCK`
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Cache refresh is exposed via route endpoints and service calls.
- Several caches are project-folder scoped; others are user AppData scoped.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- File names and limits are defined in `app_server/config.py` constants.
- `projects/<project>/data_processing_values.json` is the lazy `arcrho-source-vocab-v1` cache used by the Data Processing Rules editor. It contains de-duplicated mapped reserving-class key combinations for each source measure and is invalidated by the source CSV path/mtime/size fingerprint or a Field Mapping signature change.
- Project data is organized by reserving class as `data/<ReservingClassFolder>/datasets` for CSV caches, `data/<ReservingClassFolder>/methods` for method JSON and method RPC temp files, `data/<ReservingClassFolder>/sidecars` for dataset metadata and notes, and `data/<ReservingClassFolder>/index.json` for the Project Instance cache index. Background `WriteSidecar: false` engine requests keep per-CSV processing provenance in `data/<ReservingClassFolder>/.arcrho-cache-provenance/`; each atomic technical record includes the current processing hash and the CSV size, modification time, and SHA-256 content fingerprint, letting non-mutating Dataset/DFM/Result Selection loads reuse only the recorded file without changing the user-editable base sidecar. An app-calculated CSV keeps a record in the same folder holding the formula it was built with and, for each dependency, the exact file it was read from with that file's size, modification time, and SHA-256 fingerprint (plus the input a DFM method output was rebuilt from); the dataset sidecar beside it names precedents only. Dataset deletion and generated-cache clearing remove the corresponding technical record; a mismatched or replaced CSV invalidates it automatically.
- Dataset Viewer and DFM store the local last selected Project Name in `%APPDATA%\ArcRho\local_project_prefs.json` so it can be checked and edited manually without opening the server project folder. The same file also stores `recentProjectNames`, capped to the last three project names selected from the project tree picker, which appear in the picker's blue virtual `Recent Projects` folder above real project folders, and `projectExplorer.expandedFolders`, which restores the Project Settings folder expansion state.
- That file also holds `homeShortcuts`, the user's Home custom groups and shortcut cards, as `{ "version": 1, "groups": [{ "id", "title", "cards": [{ "id", "label", "target" }] }] }`. A card `target` is the same normalized descriptor `shellActivityHistory` entries use, minus the activity timestamp, so a card opens through the same restore path as Browsing History. Caps are 24 groups, 48 cards per group, and 60-character titles and labels; `ui/shell/home_shortcuts.js` owns the document schema and `scripting_preferences_service.py` validates structure and caps on save. Because `save_local_project_preferences` merges only the keys present in a request, the frequent `shellActivityHistory` writes and Home shortcut saves never overwrite each other.
- Reserving-class tree filter specs are stored in each project-user preference file under `projects/<project>/users/<windows-login>/preferences.json`; `%APPDATA%\ArcRho\cache\reserving_class_filter_spec.json` is obsolete and is no longer read or written.
- Dependency Graph's last filter choices are local-user browser storage under `arcrho_dependency_graph_filters`, owned by `ui/project_instance/dependency_graph_preferences.js`. The payload holds Status, Category, and Method Type value arrays plus `matchedOnly`; it applies across projects in this PC profile and is saved on each change. It does not write project metadata or project-user preference files.
- Refresh endpoints can clear and rebuild cache files.
- ResQ method imports persist the output object's review status in the dataset sidecar: vector-backed methods use `OutputVector.Status`, while Berquist-Sherman methods use `OutputTriangle.Status`. Status `2` remains Needs Review through graph refresh even when precedent timestamps are current; status `0` can still become Needs Review when ArcRho detects a newer precedent.
- ResQ migration treats `Generated=true` single-instance datasets as Arco Engine outputs. The migration and frontend runtime use the same canonical engine-sidecar builder; those sidecars intentionally omit ResQ labels/formulas, and `/dataset/cache/load` hydrates canonical project development headers plus the Dataset Type formula before returning the grid model.
- On an engine sidecar, `updated_at` is when the cache file was produced, while migration-written sidecars also carry `source_modified` — when the data last changed in ResQ. The import's precedent-freshness check compares `source_modified` (falling back to `updated_at`), so rewriting an unchanged dataset's cache at import time does not flip its dependent methods to Needs Review. A frontend engine regeneration removes `source_modified` because the content no longer comes from ResQ.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add cache file constant: update config, service readers/writers, and this index.
2. Change refresh logic: verify endpoint side effects and lock behavior.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Cache invalidation bugs can surface as stale or mismatched UI data.
- File locking can fail writes under concurrent access.
- Source-vocabulary generation must not publish a cache if the source CSV changes during its scan.
<!-- MANUAL:END -->
