# App Server Domain: source_table

## Purpose
<!-- MANUAL:BEGIN -->
The project-owned imported source table.

Every project folder owns exactly one imported raw table at a fixed location and a fixed name:

```
<project dir>/source/master_table.csv     the table every ArcRho consumer reads
<project dir>/source/source_import.json   which source produced it, plus the SQL Server profile
```

Three import routes write that same copy:

- **`csv`** - copied from the external path in `field_mapping.json::table_path`. The copy is refreshed automatically whenever that file's identity (path, mtime, size) differs from the recorded import, so existing projects keep working with no user action.
- **`mssql`** - read from SQL Server on the client with the caller's Windows identity and uploaded to the server. Never re-read implicitly; only an explicit import writes the copy.
- **`combined`** - several CSV and SQL Server tables read and joined on the client, then uploaded as one table with `source_type: combined`. Never re-read implicitly: `ensure_master_table` treats it like `mssql`, the refresh plan answers `server_can_import: false`, and the Engine's refresh job reaches that same guarded read. The join spec is the `combined` block of `source_import.json` ([plan](../../../../docs/plans/combined_source_import.md), decision 3); it is saved whole by the `source_combined_save` mutation (`source_table_service.save_combined_source`, receipt, needs two tables and one key) and appears in `source_import.json`, the settings answer and the upload commit answer only for a combined source, so single-table records and answers keep exactly their shape. Saving a single-table profile drops the block. The upload commit labels a combined import from the saved block (`Combined: Loss, EP`) and records no CSV identity.

The external CSV path and the SQL Server table are *import sources*. Nothing downstream reads them: table summary, reserving class values, data processing rules/values, and the data engine all resolve `source/master_table.csv`.

The SQL Server profile lives with the project and is shared by every user of that project. It stores `server`, `database`, `table`, and `authentication` only - never credentials. `windows` is the only supported authentication mode; `sql_login` exists in the shape as a reserved placeholder and every service path rejects it until it is implemented.

`POST /source_table/profile` also accepts an optional `csv_path` for `csv`-sourced projects and writes it into the project's `field_mapping.json::table_path`, making the profile save the single writer of the external CSV selection; an omitted `csv_path` leaves the stored path unchanged. The save is the `source_profile_save` workspace mutation (Gateway-required, with a receipt because it appends an audit entry) and answers with the settings as they now stand; the client adds `driver_available`. The `csv_path` is translated from this PC's drive letters into the share it stands for before it is sent (`normalize_import_source_path`), because only this PC has that mapping.

`GET /source_table/file_status` reads the external source file's own identity - modified time, size, and whether it still matches the recorded import - without importing anything, so the Source Data details panel can show the file's live modified time rather than the one captured when the copy was taken. It runs on the caller's machine rather than the ArcRho Server host on purpose: an import source is not project data, and the configured path may be a Client PC drive the server cannot see, which is the same reason the refresh plan translates drive letters on the client. An unreachable file answers `exists: false` instead of failing. Only that stat stays on the client: the import record and the configured path come from the `source_table_settings` hosted read, the same one `GET /source_table` uses.

`GET /source_table` and `GET /source_table/connections` read on the server host through the Gateway (the `source_table_settings` and `mssql_connections` hosted reads, Gateway-required; see [`workspace_reads`](workspace_reads.md)). `driver_available` in the `GET /source_table` answer is added on the client, because the SQL Server import runs there with the user's own Windows login.

`POST /source_table/tables` lists the tables and views the caller can see in one database, so the Source Data picker never has to assemble a name itself. It validates only the server/database half of the profile, because choosing the table is exactly what it is for.

Server/database pairs that connect successfully are recorded in a **server-shared** preference at `<workspace_root>/config/mssql_connections.json`, resolved by `config.get_mssql_connections_path()` - never a hardcoded server root. Every user of that ArcRho Server sees and can prune the same list through `GET /source_table/connections` and `POST /source_table/connections/forget`. The file holds `server`, `database`, and `last_used_at` only: no credentials, and no table name, since the table is a per-project choice. The listing and the SQL Server import run on the client as the user's Windows login, but the list is written on the server host: `submit_mssql_connection_remember` sends the pair as the `mssql_connection_remember` mutation from a Client PC, and the forget route is the `mssql_connection_forget` mutation (both Gateway-required and idempotent). Recording is best-effort - an unreachable Gateway must not fail a good connect or a committed import.

`GET /source_table/refresh_job/plan` says who performs the import and whether a refresh is running. The settings (`source_table_settings`) and the busy check (`source_refresh_status` without a job) are read on the server host. A CSV path still saved in a drive letter is translated on the client and sent as data: the `source_csv_path_rewrite` mutation stores the share path only while the stored path still reads the drive-letter spelling, so a repeat writes nothing. `server_can_import` is true for a `csv` source whose path is a share; a SQL Server source and a path only this PC can open are read on the client and uploaded (`POST /source_table/import`, `POST /source_table/refresh`, below) before the job runs with `import_source` off. With no Engine, a server-readable source is not imported at all, and after a client-only import the page asks for `POST /table_summary/refresh`, which rebuilds the summary and the reserving-class values on the server (see [`table_summary`](table_summary.md)).

**Uploading a source only this PC can read** (decisions 3 and 5 of [client_smb_retirement.md](../../../../docs/plans/client_smb_retirement.md)). `POST /source_table/import` reads the SQL Server table as the user's own Windows login and `POST /source_table/refresh` reads the configured CSV, both in the client app server; only the master-table write moves to the server, so a Client PC never writes the share. `source_table_upload_service` owns both halves. The client cuts the CSV bytes into 256 KiB blocks, compresses each (zlib level 1, base64; a block that would not fit the 256 KiB mutation limit is halved) and sends it as the `source_table_upload_chunk` mutation, numbered from 0 under an upload id the client makes. The server keeps each chunk as its numbered part under `<root>/requests/source_table_upload/<user>/<upload id>/`, so a resent chunk overwrites the same part. The `source_table_upload_commit` mutation names the chunk count, the byte total and the row count the client read (lines after the header, counted by the same `RowCounter` on both sides; no checksum). Under the project lock the server refuses while a source refresh is running (`423`), refuses a missing part or a byte or row mismatch (`409`) without touching the master table, assembles the parts into `master_table.csv.import.tmp` and swaps it in with one `os.replace`, then writes `last_import` (a CSV's path, modified time and size come from the client's stat), remembers the SQL Server pair, appends the audit entry, stores its answer as `commit.json` in the upload folder and removes the parts. A repeated commit answers from `commit.json`, so neither kind needs a Gateway receipt. A CSV upload that failed part way resumes on the next try in the same app session while the file's path, modified time and size are unchanged: the `source_table_upload_status` read lists the parts the server holds and only the rest are sent. A SQL Server import always starts a new upload, because a second query need not return rows in the same order. Uploads older than the Gateway's receipt window (24 h) are removed when a new upload starts. While the request is open, `GET /source_table/upload_progress` answers the bytes and rows sent so far from the client app server's memory, and the page shows them in its progress window. Measured on the local test root on 2026-09-27: the Fake project's 88 MB, 346,115-row table uploads in about 9 s (337 chunks).

`POST /source_table/refresh_job` submits the Engine-hosted refresh (`python-api/src/arcrho_source_refresh_contract.py` owns the request) through the Gateway, and its status poll is a polled hosted read: a poll the Gateway cannot answer is `unknown: true`, and the page keeps polling. It takes an optional scope: `dataset_types`, a list of engine-built dataset type names, and `reserving_class_types`, a list of `{Name, Level}` reserving class types. The router forwards each only when non-empty, because the hosted-mutation contract reads an empty list argument as a malformed request and an absent one as "everything"; the contract writes them into the request file as `DatasetTypes` and `ReservingClassTypes` under the same rule, so a whole-project refresh is the payload every deployed Engine already accepts. `reserving_class_matches_scope` in the contract is the one owner of the class rule: a class is in scope when its path segment at every listed level is one of the names listed for that level, and a level not listed accepts every value. The Engine worker (`server-components/src/arcrho_engine/source_table_refresh.py`) applies that rule to the class list and regenerates the engine datasets whose index row `dataset_type` is in the **expanded** set of types. The expansion is `arcrho_api.dataset_type_contract.generated_formula_refresh_names`, reached through `calculated_dataset_service.generated_formula_refresh_types`: the selected types plus every type the Engine builds from a formula that reads one of them, and the formulas over those. It runs once per job, on types and before any instance is looked up, so a type with no persisted instance cannot hide a later formula whose source still uses a selected type; walking instances instead would have left a generated total stale after an import of one of its columns. Only generated types join the set, because the dependent walk owns the app-calculated ones. The selection the person made travels on unchanged in the request and in the recorded scope, and the derived set is reported as `result.dataset_types_expanded` so a status can say what was selected and what was rebuilt. Every dataset the class regenerated is a root of that class's one dependent walk; a regeneration that failed is named in `result.failures` and is not a root, so nothing claims its downstream was refreshed. Each dataset is regenerated at the shape its sidecar displays it at, `origin_length`/`development_length` for a triangle and `period_length` for a vector, so a quarterly vector keeps its quarterly display. A method's own-period copy of a regenerated dataset needs no separate invalidation: the imported table is part of the processing configuration hash every generated cache is validated against, so the import leaves no alternate-period cache able to serve pre-import values. The same expansion reaches the data-processing-rules save job, which calls the same helper before it scans for affected classes. The job then records the scope it ran in `source_import.json::refresh_scope` (`dataset_types`, `reserving_class_types`, `chosen_by`, `chosen_at`; `normalize_refresh_scope` in the contract owns the shape) through `source_table_service.record_refresh_scope`. It is project-owned, so every user of the project sees the same record, and the Source Data tab opens its Import Scope step on it; "everything" is recorded as two empty lists, so a narrowing never outlives the next whole-project import. The Engine writes it on the server host, which is why no client-side write of the record was added.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.source_table.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/source_table` | `get_source_table` | `str` | - | `source_table_service.get_source_table_state` |
| `GET` | `/source_table/connections` | `get_source_table_connections` | - | - | `workspace_read_client.run_workspace_read` |
| `POST` | `/source_table/connections/forget` | `forget_source_table_connection` | `MssqlConnectionForgetRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_service.forget_mssql_connection` |
| `GET` | `/source_table/file_status` | `get_source_table_file_status` | `str` | - | `source_table_service.get_source_file_status` |
| `POST` | `/source_table/import` | `import_source_table` | `SourceTableImportRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_upload_service.upload_source_table` |
| `POST` | `/source_table/profile` | `save_source_table_profile` | `SourceProfileSaveRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_service.get_source_table_state`, `source_table_service.save_source_profile` |
| `POST` | `/source_table/refresh` | `refresh_source_table` | `SourceTableRefreshRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_upload_service.upload_source_table` |
| `POST` | `/source_table/refresh_job` | `submit_source_refresh_job` | `SourceRefreshJobSubmitRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_refresh_service.submit_source_table_refresh_job` |
| `GET` | `/source_table/refresh_job/plan` | `get_source_refresh_plan` | `str` | - | `source_refresh_service.describe_source_refresh_plan`, `source_refresh_service.get_source_table_refresh_status`, `source_table_service.rewrite_source_csv_path`, `workspace_read_client.run_workspace_read` |
| `GET` | `/source_table/refresh_job/status` | `get_source_refresh_job_status` | `str` | - | `source_refresh_service.get_source_table_refresh_status`, `workspace_read_client.run_polled_workspace_read` |
| `POST` | `/source_table/tables` | `list_source_table_candidates` | `MssqlTableListRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_service.list_mssql_tables` |
| `POST` | `/source_table/test_connection` | `test_source_table_connection` | `MssqlConnectionTestRequest` | [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) | `source_table_service.test_mssql_connection` |
| `GET` | `/source_table/upload_progress` | `get_source_table_upload_progress` | `str` | - | `source_table_upload_service.get_upload_progress` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.source_table.key_files -->
- [`app_server/api/source_table_router.py`](../../../app_server/api/source_table_router.py) - Import source profile, connection test, and import routes.
- [`app_server/services/source_table_service.py`](../../../app_server/services/source_table_service.py) - Project-owned master table copy and SQL Server import.
- [`app_server/services/source_table_upload_service.py`](../../../app_server/services/source_table_upload_service.py) - Upload of a source only the client can read, and its server-side commit.
- [`app_server/schemas/source_table.py`](../../../app_server/schemas/source_table.py) - Import source request schemas.
- [`../python-api/src/arcrho_api/source_table_contract.py`](../../../../python-api/src/arcrho_api/source_table_contract.py) - Canonical master-table layout and source_import.json schema.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- `python-api/src/arcrho_api/source_table_contract.py` is the canonical owner of the folder/file names, the `source_import.json` schema, the normalization rules, and the CSV staleness rule. `app_server/config.py` delegates its path helpers to it.
- The Engine ships as its own frozen bundle and cannot import `arcrho_api`, so `arcrho_engine/data_processing.py` mirrors `SOURCE_IMPORT_DIR` and `MASTER_TABLE_FILE` locally. `frontend/tests/test_source_table_contract.py` fails when the mirror drifts, and also asserts the engine resolves the master path without consulting `table_path`.
- Requires `pyodbc` plus a Microsoft ODBC Driver for SQL Server (18, 17, or a Native Client fallback) on the client PC. Both are optional at import time: a missing driver answers `503` with an explicit message rather than failing at startup.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Writes are serialized per project by an in-process lock, and every import (the server-side copy and the upload commit) stages to `master_table.csv.import.tmp` and `os.replace`s on success. A failed or interrupted import discards the staging file and leaves the previous master copy intact.
- SQL Server rows are fetched in `_MSSQL_FETCH_BATCH` (20000) batches and sent in 256 KiB chunks as they are written, so a large table never materializes in memory.
- Table names are bracket-quoted per part and rejected when they are empty, deeper than three parts, or contain a `]`; the query is always a plain `SELECT * FROM <quoted>`.
- A transient CSV read failure (missing or locked external file) preserves the last good import instead of clearing the project.
- `resolve_source_table_for_read` returns `""` when nothing is configured or imported, matching the historical "no table path" behavior of its callers.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a field to `source_import.json`: extend `normalize_source_import` in `arcrho_api/source_table_contract.py` first, then the service and the Source Data tab consumer.
2. Enable SQL Server login: extend `SUPPORTED_MSSQL_AUTH_MODES`, add the credential handling (which must not persist to the shared project folder), and enable the disabled radio in `ui/project_settings/project_settings.html`.
3. Move or rename the master table: change only the contract constants, then update the data-engine mirror; the parity test names both.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A project switched to `mssql` before its first import answers `409` until the user imports; this is deliberate, since the app server must never open a database connection implicitly.
- The master copy doubles the on-disk footprint of the raw table inside the project folder, and `source/` is carried along by project duplicate.
- Concurrent imports of the same project from two PCs are serialized by the Gateway's per-project lock at commit; each swap is atomic and the last commit wins.
- Resuming an interrupted upload relies on the app session's memory of the upload id, so a restarted app uploads the whole table again; the parts it left expire with the receipt window.
<!-- MANUAL:END -->
