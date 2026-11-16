# App Server Domain: reserving_class

## Purpose
<!-- MANUAL:BEGIN -->
Reserving class values/tree/preferences/types domain.

Values are always collected from the project-owned imported master table resolved by `source_table_service.resolve_source_table_for_read`; see [`source_table`](source_table.md). `refresh_reserving_class_values` no longer accepts a `table_path` override, and the `POST /reserving_class_values/refresh` route, which had no caller left, was removed by step 15 of [client_smb_retirement.md](../../../../docs/plans/completed/client_smb_retirement.md). `mapping_rows_override` remains, so a field-mapping save can refresh against rows it has not committed yet.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.reserving_class.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/reserving_class_combinations` | `get_reserving_class_combinations` | `str` | - | `reserving_class_service.read_reserving_class_combinations` |
| `GET` | `/reserving_class_filter_spec` | `get_reserving_class_filter_spec` | `str` | - | `reserving_class_service.read_filter_spec` |
| `POST` | `/reserving_class_filter_spec` | `save_reserving_class_filter_spec` | `ReservingClassFilterSpecSaveRequest` | [`app_server/schemas/reserving_class.py`](../../../app_server/schemas/reserving_class.py) | `reserving_class_service.save_filter_spec`, `workspace_mutation_client.run_workspace_mutation` |
| `GET` | `/reserving_class_hidden_paths` | `get_reserving_class_hidden_paths` | `str` | - | `reserving_class_service.read_hidden_paths` |
| `POST` | `/reserving_class_hidden_paths` | `save_reserving_class_hidden_paths` | `ReservingClassHiddenPathsSaveRequest` | [`app_server/schemas/reserving_class.py`](../../../app_server/schemas/reserving_class.py) | `reserving_class_service.save_hidden_paths`, `workspace_mutation_client.run_workspace_mutation` |
| `GET` | `/reserving_class_path_tree/children` | `get_reserving_class_path_tree_children` | `str` | - | `reserving_class_service.read_reserving_class_path_tree_children` |
| `GET` | `/reserving_class_paths_with_data` | `get_reserving_class_paths_with_data` | `str` | - | `reserving_class_service.list_reserving_classes_with_data` |
| `GET` | `/reserving_class_types` | `get_reserving_class_types` | `str` | - | `reserving_class_service.read_reserving_class_types` |
| `POST` | `/reserving_class_types` | `save_reserving_class_types` | `ReservingClassTypesSaveRequest` | [`app_server/schemas/reserving_class.py`](../../../app_server/schemas/reserving_class.py) | `reserving_class_service.save_reserving_class_types`, `workspace_mutation_client.run_workspace_mutation` |
| `POST` | `/reserving_class_types/import_local_file` | `import_local_reserving_class_types_file` | `ReservingClassTypesImportLocalFileRequest` | [`app_server/schemas/reserving_class.py`](../../../app_server/schemas/reserving_class.py) | `reserving_class_service.parse_local_reserving_class_types_file` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.reserving_class.key_files -->
- [`app_server/api/reserving_class_router.py`](../../../app_server/api/reserving_class_router.py) - Reserving-class routes for values/tree/preferences/types.
- [`app_server/services/reserving_class_service.py`](../../../app_server/services/reserving_class_service.py) - Cache generation, refresh, and preference persistence.
- [`app_server/schemas/reserving_class.py`](../../../app_server/schemas/reserving_class.py) - Reserving class request models.
- [`ui/shared/components/pickers/reserving_class_picker.js`](../../../ui/shared/components/pickers/reserving_class_picker.js) - Frontend caller for reserving-class endpoints.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Consumed by dataset, DFM, and project settings features.
- Exposes refresh and cache children endpoints.
- Every GET in this router, and the hidden-paths and filter-spec saves, run on the server host through the Gateway (step 8 of [client_smb_retirement.md](../../../../docs/plans/completed/client_smb_retirement.md)); a Client PC answers `503` when the Gateway is unavailable rather than reading or writing over the share. Each service in the "Route answers" block of `reserving_class_service` returns its route's whole response, refusals included, so both transports answer alike. The read kinds are `reserving_class_combinations`, `reserving_class_path_tree_children`, `reserving_class_types`, `reserving_class_hidden_paths`, `reserving_class_filter_spec` and the existing `reserving_classes_with_data` (now Gateway-required too); the mutation kinds are `reserving_class_hidden_paths_save` and `reserving_class_filter_spec_save`. The preference login is the one the request is signed with, never a payload field.
- No GET here writes. `GET /reserving_class_path_tree/children` computes the children from `reserving_class_combinations_cache.json` and `reserving_class_types.json` as they stand; it refreshes no values and writes nothing. `GET /reserving_class_types` shows the saved types merged with the source-derived rows without writing the JSON or the workbook. The values, combinations and types files are written by the writers that change them: the source refresh job's `caches` stage (through `table_summary_service.refresh_table_summary`), a field mapping save, `POST /table_summary/refresh`, and `POST /reserving_class_types`. All of them run on the server host: the job on the Engine, the three saves as Gateway-required workspace mutations (`field_mapping_save`, `table_summary_rebuild`, `reserving_class_types_save`, the last with a receipt because it appends an audit entry).
- `reserving_class_path_tree_cache.json` is retired (decision 4 of [client_smb_retirement.md](../../../../docs/plans/completed/client_smb_retirement.md), step 19): `GET /reserving_class_path_tree` and its read kind are gone, and the Dataset Viewer's reserving-class value list (`ui/shared/services/valid_value_lists.js`) reads the data's own class paths from `GET /reserving_class_combinations`. A file an older version left in a project folder is not read.
- `POST /reserving_class_types` writes both `reserving_class_types.json` and a same-folder mirror workbook `reserving_class_types.xlsx` with `Name`, `Level`, `Formula`, and resolved `Source`.
- `POST /reserving_class_types/import_local_file` parses local reserving-class-type `.json`/`.xlsx` files for Project Settings local load; the JSON parser accepts either UI columns (`Name`, `Level`, `Formula`) or persisted file columns with trailing `Source` and silently discards a retired `EEX Formula` column.
- Source-derived reserving class type rows are generated independently per `(Name, Level)` pair (not deduped by `Name` only), so the same name can appear in multiple level groups when present in distinct source levels.
- Reserving class `Source` expressions always wrap each resolved component in double quotes (including single-component formulas), and quoted tokens in `Formula` are treated as atomic components so operator-normalization does not insert spaces inside quoted names or collapse user-entered spacing within quoted text (for example `/` in `"Affinity/Referral Partners"` or the double space in `"eSales -  Teachers"`).
- `POST /reserving_class_types` rejects changed user-defined formulas when they reference a reserving class type name that does not exist in the submitted/current table, or when they reference a name containing `+`, `-`, `*`, or `/` without wrapping that full name in double quotes; invalid saves return `400` with the offending row/field details. Unchanged legacy rows are not revalidated on save, formulas may reference user-defined rows as well as source-derived rows, and quoted components are validated by exact name match, including repeated spaces inside the quotes.
- The Engine resolves each level of a class path against `reserving_class_types.json` on one type key (outer space dropped, inner runs of space collapsed, case ignored), owned by `python-api/src/arcrho_reserving_class_type_contract.py`. The ResQ import uses the same module to decide whether a class goes to the Engine: only when every level of its path is a defined type; otherwise (a ResQ Total, say) its datasets keep ResQ's values.
- `EEX Formula` is no longer part of Reserving Class Types persistence or validation. Legacy JSON payloads may still contain that column, but readers discard it so Project Settings and dependent features remain available. XLSX imports continue to return an explicit conversion-required error; measure-specific row filters belong in `data_processing_rules.json`.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Uses multiple JSON cache files with lock protection plus project-user preference files under `projects/<project>/users/<windows-login>/preferences.json`.
- Reserving class types persistence uses paired JSON/XLSX writes with rollback-safe ordering (write XLSX then JSON, rollback XLSX on JSON failure).
- Active tree `filter_spec`, `rcprefs-window` preferences, favorite path nicknames/folders from `ptree-window`, and hidden paths from the tree context menu are stored in the project-user preference file under `reservingClassTree`, so they are user-specific and copy with project duplication. All three are whole-value writes: the hidden-path list, the filter spec and (when sent) the tree preferences replace the stored value outright, so clearing a level's filter or the last favorite sticks and a repeated save lands the same state. A filter-spec save without `preferences` keeps the stored ones. The tree preferences include automatic single-child expansion and whether segment labels are hidden; reserving-class trees remain open after a final path is selected. Reverting a favorite nickname removes that path's nickname entry so the UI falls back to the original raw path label.
- These reads are on the Project Instance page-load critical path. They now run on the server host, but each request still reads each file once: `GET /reserving_class_filter_spec` takes one preference-file read for both the filter spec and the tree preferences, and `refresh_reserving_class_types_json` takes one read of `reserving_class_types.json` that serves both the merge base and the unchanged-file comparison that decides whether to write. `refresh_reserving_class_types_json` still merges newly discovered source values and, for its writers (`persist=True`), still writes the paired JSON/XLSX when the merge differs; only the redundant reads were removed. `tests/test_reserving_class_read_io.py` pins those read counts alongside the write behaviour.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a reserving-class endpoint: keep schema/service lock logic consistent.
2. Change cache structure: update readers/writers and UI consumers together.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- High route volume and file-lock contention make regression risk higher here.
<!-- MANUAL:END -->
