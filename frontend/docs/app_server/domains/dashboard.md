# App Server Domain: dashboard

## Purpose
<!-- MANUAL:BEGIN -->
Dashboard files, the reusable library, and the tables a dashboard charts.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.dashboard.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/dashboard/delete` | `dashboard_delete` | `DashboardDeleteRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.delete_dashboard` |
| `GET` | `/dashboard/library` | `dashboard_library` | - | - | `dashboard_service.list_library` |
| `POST` | `/dashboard/library/delete` | `dashboard_library_delete` | `DashboardLibraryDeleteRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.delete_library_asset` |
| `POST` | `/dashboard/library/save` | `dashboard_library_save` | `DashboardLibrarySaveRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.save_library_asset` |
| `GET` | `/dashboard/list` | `dashboard_list` | - | - | `dashboard_service.list_dashboards` |
| `POST` | `/dashboard/load` | `dashboard_load` | `DashboardLoadRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.load_dashboard` |
| `POST` | `/dashboard/save` | `dashboard_save` | `DashboardSaveRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.save_dashboard` |
| `POST` | `/dashboard/source/fields` | `dashboard_source_fields` | `DashboardSourceRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.source_fields` |
| `POST` | `/dashboard/source/load` | `dashboard_source_load` | `DashboardSourceRequest` | [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) | `dashboard_service.load_source` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.dashboard.key_files -->
- [`app_server/api/dashboard_router.py`](../../../app_server/api/dashboard_router.py) - HTTP routes for dashboard files, the library, and data source loading.
- [`app_server/services/dashboard_service.py`](../../../app_server/services/dashboard_service.py) - Dashboard and library files, per-project merging, CSV and SQL sources.
- [`app_server/services/dashboard_data_service.py`](../../../app_server/services/dashboard_data_service.py) - The table shape, grouping, and the two Server-hosted project reads.
- [`app_server/schemas/dashboard.py`](../../../app_server/schemas/dashboard.py) - Dashboard request models.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Consumed by the Dashboards page (`ui/dashboard`, see [the page doc](../../ui/dashboard.md)).
- `GET /dashboard/list` answers the user's dashboards and the shipped samples, each with its name, description, page and widget counts, and the projects it reads. `POST /dashboard/load`, `/dashboard/save` and `/dashboard/delete` work on one file. A save under a name another dashboard holds is refused with `409` unless `overwrite` is set; a save under a new name removes the file it was opened from when that file is the user's own; a sample is never written or deleted.
- `GET /dashboard/library` answers the built-in items and the user's own; `POST /dashboard/library/save` and `/dashboard/library/delete` write and remove one user item. A built-in item cannot be deleted.
- `POST /dashboard/source/load` turns one data source into a table, and `POST /dashboard/source/fields` lists the columns of a table source before any are chosen.
- **Where a source is read.** `arco_datasets` and `arco_source_table` are read on the server host through the registered `dashboard_dataset_table` and `dashboard_source_table` workspace reads (`arcrho_workspace_read_contract`), once per project the source names; a Client PC never opens a dataset or the imported table over the share, and a Gateway that does not offer the read answers `503`. `dashboard_service.merge_project_tables` stacks the answers under a leading `Project` column, matching columns by name and merging each column's natural order. A `csv` source is read on this PC because the file may be on a drive only this PC has, and a `sql` source runs through the SQL Server or Snowflake console service as this Windows user, under that service's row ceiling.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Dashboards are `.arcdash` files in `config.DASHBOARD_DIR` (`Documents\ArcRho\dashboards`; `ARCRHO_DASHBOARD_DIR` moves it for a test), written with `persisted_json_text` so a saved table is one row per line. The user's library items are one JSON file each under its `library` subfolder. Samples and the built-in `library.json` ship in `config.DEFAULT_DASHBOARDS_DIR`, which the desktop build packages beside `default_preferences`.
- Every table has one shape, owned by `dashboard_data_service.table_payload`: `{format, columns: [{name, type, role, ...}], rows, row_count}`. A column's `order` lists its values in their natural order, and `semi_additive` names the partition and order a `latest` aggregation uses.
- `read_dataset_table` gives one row per reserving class, origin and development period with one number column per dataset; a vector's values sit on a row with no development period. A dataset a class does not hold is left blank and named in `missing`. Each dataset is loaded at the period it is stored at and nothing is built or written.
- `read_source_table` groups the project's imported table by the chosen fields and totals the chosen numbers; `<column>:year`, `:quarter` and `:month` group a period column more coarsely. It reads the imported copy as it stands and never imports.
- A table holds at most 100,000 rows; a larger grouping is refused with `422`, not cut. Raw rows of an ungrouped CSV are cut at 50,000 and marked `truncated`.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a data source kind: `SOURCE_KINDS` and `load_source` in `dashboard_service.py`, the source dialog, and a test.
2. Change the table shape only in `dashboard_data_service.table_payload`.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A project read must stay a read: `read_source_table` never imports, and `read_dataset_table` loads each dataset at the period it is stored at.
<!-- MANUAL:END -->
