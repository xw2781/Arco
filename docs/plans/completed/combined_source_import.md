# Combined Source Import

Status: Done 2026-10-12: all 9 steps landed. A project's source can now be several CSV and SQL Server tables joined in the Source Data import window; the server parts are deployed and the window reaches users with the next app release. The demo in the Aug fake project rebuilt its master table from three CSV tables, identical to the original, and a single-table project looked and behaved as before.
Last updated: 2026-10-12

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A project can record a source made of several tables, and single-table projects record exactly what they do today | [x] | 2026-10-12 | 45 min | 3 min | Nothing visible yet; a project's source record can now describe several joined tables, and single-table projects are recorded exactly as before. |
| 2 | Arco can combine several tables into one the way the merge notebook does | [x] | 2026-10-12 | 70 min | 5 min | Nothing visible yet; Arco can now join several tables into one the way the merge notebook does and report how well each table matched. |
| 3 | The server accepts and keeps a combined source and never re-reads it behind the user's back | [x] | 2026-10-12 | 60 min | 7 min | Nothing visible yet; the server can now keep a combined source and accept its imported table, and it never re-reads one on its own, while single-table projects save and import exactly as before. |
| 4 | The app can read every table of a combined source, preview the result and import it | [x] | 2026-10-12 | 60 min | 9 min | Nothing visible yet; Arco can now read each table of a combined source, preview the joined result and import it the same way a single table is uploaded, while single-table imports work exactly as before. |
| 5 | The import window lists several tables, each with a nickname and a details window | [x] | 2026-10-12 | 75 min | 15 min | The import window has an Add Table button: several tables can be listed with nicknames, grouped by connection, dragged into join order and opened in a details window that shows their columns, while a single-table import looks and works exactly as before; importing several tables comes in a later step. |
| 6 | The import window shows how the tables join and what the result will look like | [x] | 2026-10-12 | 80 min | 25 min | With two or more tables the import window gains a Combine step: a map lines up the matching columns across the tables, each key, row rule and column can be changed in place, and a Row Match tab and a Preview tab show how well the tables match and the first rows of the result before anything is imported; the table list no longer shows connection details. |
| 7 | Importing a combined source runs end to end and the Source Data tab describes it | [x] | 2026-10-12 | 50 min | 19 min | Import Data now imports a combined source from start to finish, the Source Data tab names it with its tables and keys, and the import window reopens on its saved tables, nicknames, keys and rules, while single-table projects look and work exactly as before. |
| 8 | The server parts are live | [x] | 2026-10-12 | 25 min | 8 min | The server now runs the combined-source code, and a single-table project's source settings read back exactly as before the update. |
| 9 | A combined source is built and checked in the Aug fake project | [x] | 2026-10-12 | 45 min | 29 min | The Aug fake project now takes its source from three tables joined in the import window, and the imported table came out identical to the one it had before; a single-table project looks and works as before. |

Overall: 9 of 9 steps done. Estimated 510 min, actual 120 min.

## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one workflow subagent), one commit.
- Note the clock before the first file is read and again at the commit, keeping the two parts apart: time spent reading and editing, and time spent running tests, checks and deploys.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date, the actual minutes and the one-line user note, update the "Overall" count and actual total, append the actual to the step's `Estimate:` line, and update the `Status:` line at the top and this plan's row in the [plans index](../README.md).
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## Ship impact

- **How it ships:** server redeploy first (Gateway and Engine, which both carry `frontend/app_server` and `python-api/src`), then the frontend in the next app release.
- **Risk to the released app: none, by construction.** The released app never sends a combined source, every request it sends keeps its current shape and answer, and a single-table `source_import.json` is written byte for byte as today (decision 2). The server can therefore be deployed before the release.
- **Risk to existing projects: none, by construction.** Single-table projects keep their record, their import path and their Engine refresh path. Every step that touches a shared path carries a test proving it.

## The question

Today a project's source is one CSV file or one SQL Server table. Monthly work such as `E:\ResQ\Automations\Monthly Project\202609\Arco - Merge Tables.ipynb` first outer-merges several tables (three SQL Server tables and one CSV) on shared keys, renaming keys that differ only in case, filling a key a table lacks (`sys_yrmo = 0`), dropping a column (`FACID`), and cleaning empty `Unnamed: n` columns and blank rows. The user wants Arco to do this in the Source Data tab with a visual join, mixing SQL and CSV tables, while everything downstream stays the same.

The agreed UX is the prototype [project_settings_combined_source_demo.html](../../../frontend/docs/ui/project_settings_combined_source_demo.html). Read it before any frontend step; it is the specification for the window's behaviour and wording.

## How it fits

Everything after an import reads one file, `<project>/source/master_table.csv` (see [source_table domain](../../../frontend/docs/app_server/domains/source_table.md)). A combined source produces that same file, so field mapping, dataset types, reserving classes and the Engine refresh are unchanged.

A combined source is imported **on the client**, like a SQL Server source today: the client app server reads every table (CSV with the client's drive mappings, SQL Server with the user's own Windows login), combines them, and sends the result through the existing chunked upload (`source_table_upload_chunk` / `source_table_upload_commit`). The refresh job then runs with `import_source` off, exactly as it does after a SQL Server upload.

## Decisions

1. **Combined is a third source type, `combined`.** `csv` and `mssql` keep their meaning and their code paths untouched.
2. **Single-table records do not change.** `source_import.json` gains an optional `combined` block that `normalize_source_import` emits **only** when `source_type` is `combined`. A `csv` or `mssql` record normalizes to exactly today's payload, so `json_format` stays `arcrho-source-import-v4`. Saving a single-table source through `source_profile_save` drops any `combined` block, so switching back yields exactly the single-table shape.
3. **The `combined` block:**
   ```json
   "combined": {
     "tables": [
       { "id": "t1", "nickname": "Loss", "source_type": "mssql",
         "mssql": { "server": "...", "database": "...", "table": "dbo.X", "authentication": "windows" } },
       { "id": "t4", "nickname": "EP", "source_type": "csv", "csv_path": "\\\\share\\...\\EP.csv" }
     ],
     "keys": [
       { "name": "CO_CD", "map": { "t1": { "column": "CO_CD" }, "t4": { "column": "Co_Cd" } } },
       { "name": "sys_yrmo", "map": { "t1": { "column": "sys_yrmo" }, "t4": { "fill": "0" } } },
       { "name": "acc_yrmo", "map": { "t5": { "column": "acc_yrmo", "convert": "yyyymm" } } }
     ],
     "rows": { "t2": "all", "t3": "base", "t4": "match" },
     "exclude": { "t4": ["FACID"] },
     "rename": { "t5": { "Earned Premium": "Budget Premium" } }
   }
   ```
   - The first table is the base; the others join onto the running result in list order.
   - A key map entry is `{column}` (optionally with `convert: "yyyymm"`, which turns `2026-07` into `202607`), `{fill: "<value>"}`, or `{any: true}` (the key is ignored for that table).
   - `rows` per non-base table: `all` (outer, default), `base` (left), `match` (inner).
   - Each SQL table carries its own full profile; the UI groups tables with the same server and database under one connection header. No separate connections map.
   - CSV paths are stored translated to the share (`normalize_import_source_path`), as single CSV paths are.
   - The normalizer de-duplicates ids, drops key-map entries for unknown tables, and keeps list order.
4. **Combining reads everything as text.** Every table is read with all columns as strings (`dtype=str`, `keep_default_na=False`), so keys compare exactly and no value is reformatted. Empty `Unnamed: n` columns and fully blank rows are dropped, as the notebook's `read_csv_clean` does.
5. **Key matching by name** ignores case, spaces and underscores, when the UI proposes keys; the stored spec always names the exact column.
6. **Name clashes** on value columns get `_<nickname>` (spaces as `_`), or `_T<n>` when the table has no nickname, unless renamed.
7. **Nicknames** are optional, at most 24 characters, asked for when a table is added, and shown wherever the window names a table; a blank nickname shows the table name.
8. **The combined result is computed on the client** and uploaded with `source_type: "combined"`. The server never re-reads a combined source implicitly: `ensure_master_table` treats it like `mssql`, and `describe_source_refresh_plan` answers `server_can_import: false`.
9. **The single-table form stays exactly as today.** The list, the details window and the Combine step appear only once a second table is added. Removing tables back to one returns to the single-table form and the single-table source type.
10. **Out of scope:** a `{YYYYMM}` token in paths, an append (union) mode, and different keys per pair of tables. They are recorded in the prototype's open questions and are not needed for the notebook's case.

## Open decisions

None. Steps 8 and 9 are authorised by the user's 2026-10-12 request to demo the feature in the Aug fake project, subject to the deploy safety rule (the deploying agent re-checks that the released app is unaffected before building).

## Rough size

9 steps, estimated 510 minutes: code edit 345 minutes, test/validation 165 minutes.

## Plan

Steps run in order. Step 2 depends only on step 1 and could run beside step 3, but both touch `frontend/tests` service fixtures, so run them in order.

### Step 1 — Contract for a combined source

**Goal.** `source_import.json` can hold a combined source, and single-table records normalize exactly as today.

**Read first.**
- Decisions 1-3 and 10 above.
- [source_table_contract.py](../../../python-api/src/arcrho_api/source_table_contract.py) (whole file).
- [test_source_table_contract.py](../../../frontend/tests/test_source_table_contract.py).
- Skill `arcrho-json-contract`.

**Do.**
- [ ] Add `SOURCE_TYPE_COMBINED = "combined"` to `SOURCE_TYPES`; `normalize_source_type` accepts it.
- [ ] Add `normalize_combined_source(payload)` implementing decision 3 (tables, keys, rows, exclude, rename; CSV paths are only stripped here, translation is the caller's job).
- [ ] `normalize_source_import` adds `"combined"` only when the normalized `source_type` is `combined`.
- [ ] `normalize_last_import` accepts `combined` as a `source_type`.
- [ ] `same_csv_identity` stays CSV-only (no change, but assert it).
- [ ] Add `combined_source_label(combined)` giving `"Combined: Loss, Closed, Reported, EP"` (nickname or table name, in order).

**Tests.** In `test_source_table_contract.py`: golden full-payload tests that a `csv` and an `mssql` record normalize to exactly today's dict (no `combined` key) even when the input carries a stray `combined` block; a combined record round-trips; normalization drops unknown-table key entries, bad row rules (fall back to `all`), duplicate ids; the label.

**Done when.** The contract tests pass and a single-table record's normalized payload is unchanged.

**Estimate.** Estimate: code edit 30 min, test/validation 15 min, total 45 min. Actual: code edit 2 min, test/validation 1 min, total 3 min (the contract module was small and self-contained, and the tests passed first run).

### Step 2 — The combine engine

**Goal.** A pure Python service that takes table files and a combine spec and returns the combined table, per-table match statistics, warnings and preview rows.

**Read first.**
- Decisions 3-6 above, and the prototype's `combine()`, `columnPlan()` and `alertsFor()` functions in [project_settings_combined_source_demo.html](../../../frontend/docs/ui/project_settings_combined_source_demo.html) for the exact statistics and warnings.
- Step 1's `normalize_combined_source`.
- [pandas-read-csv-not-round-trip memory](../../../agent-memory/pandas-read-csv-not-round-trip.md).

**Do.**
- [ ] New `frontend/app_server/services/combined_source_service.py`, no I/O beyond reading the given local CSV files and writing a given output path:
  - `read_table_text(path)`: all columns as strings, drop empty `Unnamed: n` columns and fully blank rows; returns the frame and the dropped column names.
  - `combine_tables(frames_by_id, combined)`: sequential joins per decision 3 (base first; `all`/`base`/`match`; `fill`; `any` drops that key from the join for that table; `convert: yyyymm`); value-column plan with exclusions, renames and clash suffixes (decision 6); key columns renamed to the key name; output column order = keys, then value columns in table order.
  - Statistics per non-base table: `read`, `matched`, `added`, `left_out`, `base_rows_dropped`, `max_repeat`; base: `read`.
  - Warnings with a machine `kind`: `format_mismatch` (a key whose sample in one table looks like `yyyy-mm` while the base looks like `yyyymm`, with the fix `convert`), `repeat` (max_repeat > 1 because of `any`), `filled_rows`, `name_clash`.
  - `write_combined_csv(frame, path)` writing UTF-8 CSV with no index, values unchanged.
  - `preview_rows(frame, limit)` sorted by the keys.

**Tests.** New `frontend/tests/test_combined_source_service.py` with small fixture frames reproducing the notebook: `Co_Cd` mapped to `CO_CD`; `sys_yrmo` fill `0` adding the EP rows on their own (EP 72 rows, 0 matched, 72 added); `match` and `base` row rules; `any` producing a repeat warning; `yyyy-mm` mismatch detected and fixed by `convert`; exclude and rename; clash suffix with and without a nickname; `Unnamed: 9` and blank rows dropped; a value like `00123` and `1.10` survives unchanged.

**Done when.** The new tests pass under `py -3.10 -m unittest` from `frontend/tests`.

**Estimate.** Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 3 min, test/validation 2 min, total 5 min (a small pure module whose behaviour the prototype already spelled out; the tests passed first run).

### Step 3 — Server half: save, commit and guards

**Goal.** The server stores a combined source, accepts its upload, and never re-imports it implicitly; single-table saves and imports behave exactly as before.

**Read first.**
- Decisions 2 and 8 above; "How it fits".
- [source_table_service.py](../../../frontend/app_server/services/source_table_service.py) `save_source_profile`, `ensure_master_table`, `read_source_table_settings`, `_master_status`, `get_source_file_status` (a combined source has no single file to stat).
- [source_table_upload_service.py](../../../frontend/app_server/services/source_table_upload_service.py) `commit_source_table_upload`.
- [source_refresh_service.py](../../../frontend/app_server/services/source_refresh_service.py) `describe_source_refresh_plan`.
- [arcrho_workspace_mutation_contract.py](../../../python-api/src/arcrho_workspace_mutation_contract.py) entries `source_profile_save` and `source_table_upload_commit`.
- Memory notes [adding-a-hosted-save-kind](../../../agent-memory/adding-a-hosted-save-kind.md) and [propagation-hold-and-test-isolation](../../../agent-memory/propagation-hold-and-test-isolation.md).
- Tests [test_source_table_upload.py](../../../frontend/tests/test_source_table_upload.py), [test_source_data_writes_hosted.py](../../../frontend/tests/test_source_data_writes_hosted.py), [test_source_refresh_jobs.py](../../../frontend/tests/test_source_refresh_jobs.py).

**Do.**
- [x] `save_combined_source(project_name, combined)` in `source_table_service`: normalize (step 1), require at least two tables and at least one key, reject `sql_login`, store `source_type: combined` plus the block under the project lock, audit `Saved combined source (<label>)`, answer `read_source_table_settings`.
- [x] New mutation kind `source_combined_save` (`project_name`, `combined`; receipt, locked project), registered wherever `source_profile_save` is registered (mutation contract, Gateway dispatch tables, any HTTP kind list the tests enumerate).
- [x] `save_source_profile` drops the `combined` block (decision 2).
- [x] `read_source_table_settings` includes `combined` only for a combined source.
- [x] `commit_source_table_upload` accepts `combined`: `last_import.source_label` from `combined_source_label`, no CSV identity, no SQL pair remembered; audit `Imported combined source (<label>, N rows)`. Add nothing to the mutation's argument list unless needed.
- [x] `ensure_master_table` treats `combined` like `mssql` (never re-read; missing master answers the "import in Project Settings > Source Data" error).
- [x] `describe_source_refresh_plan` answers `server_can_import: false` for `combined`.
- [x] Confirm the Engine's import branch in [source_table_refresh.py](../../../server-components/src/arcrho_engine/source_table_refresh.py) reaches `ensure_master_table` for `combined` and so never re-reads it; add a test there rather than code.

**Tests.** Extend the three test files above: combined save round-trip; single save after a combined save writes exactly the single-table record (golden); combined commit records the label and leaves the CSV identity empty; `ensure_master_table` on a combined project does not touch the master; the refresh plan says client import; existing single-table tests pass unchanged. Add the Engine case to [test_source_table_refresh.py](../../../server-components/tests/test_source_table_refresh.py).

**Done when.** The touched test modules pass, and the mutation contract tests (`grep -l source_profile_save frontend/tests python-api/tests`) pass with the new kind.

**Estimate.** Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 5 min, test/validation 2 min, total 7 min (the mutation dispatch is generic, so the new kind needed only its contract entry, and the existing csv-only checks already kept a combined source on the client).

### Step 4 — Client routes: describe, preview, import

**Goal.** The client app server can list a table's columns, preview a combined source, and import it through the existing upload.

**Read first.**
- "How it fits" and decision 8.
- [source_table_router.py](../../../frontend/app_server/api/source_table_router.py), [schemas/source_table.py](../../../frontend/app_server/schemas/source_table.py).
- [source_table_upload_service.py](../../../frontend/app_server/services/source_table_upload_service.py) `_mssql_blocks`, `_chunks`, `upload_source_table`.
- Step 2's `combined_source_service`.

**Do.**
- [x] `combined_source_service` gains the client half:
  - `fetch_table(spec)`: a CSV is read from its path (drive letters work on the client); a SQL table is streamed with the user's Windows login into a temporary CSV under the app's temp folder (never the share). Cache by table spec and, for a CSV, its identity, for the life of the app session; a SQL table is re-read only when the person asks to refresh the preview or imports.
  - `describe_table(spec)`: columns, row count, dropped empty columns.
  - `preview_combined(project_name, combined)`: per-table description, statistics, warnings, first 14 rows, combined row and column counts.
  - `import_combined(project_name)`: reads the saved `combined` block through the `source_table_settings` read, re-reads every table, combines, writes a temporary CSV, then uploads it with the same chunk and commit mutations as `upload_source_table` using `source_type: combined` and the same progress reporting. Refactor `upload_source_table` so both share one chunk-and-commit helper; the CSV and SQL behaviour must not change.
- [x] Routes `POST /source_table/combined/describe`, `POST /source_table/combined/preview`, `POST /source_table/combined/save` (forwards `source_combined_save`, translating CSV paths with `normalize_import_source_path` first), `POST /source_table/combined/import`.
- [x] Update the [source_table domain doc](../../../frontend/docs/app_server/domains/source_table.md) manual sections and regenerate the docs index.

**Tests.** New cases in `frontend/tests/test_combined_source_service.py` with CSV fixtures and a fake pyodbc driver: describe, preview statistics, import uploads one chunk set and commits `combined`; the existing `test_source_table_upload.py` passes unchanged for CSV and SQL.

**Done when.** The tests pass and `docs_index_builder.py --check` is clean.

**Estimate.** Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 6 min, test/validation 3 min, total 9 min (the upload already had one clean chunk-and-commit loop to lift out, and every new test passed first run).

### Step 5 — Import window: table list, nicknames, details window

**Goal.** In the Source Data import window, Add Table turns the single-table form into the grouped table list; each table has a nickname and a details window holding its path or connection and its columns.

**Read first.**
- The prototype's Source step, Add Table popover and details window (`renderSource`, `renderModal`, the `add-table` and `details` actions).
- Decisions 7 and 9.
- Skill `arcrho-ui-design`.
- [project_settings.html](../../../frontend/ui/project_settings/project_settings.html) import window markup; [project_settings_source_data.js](../../../frontend/ui/project_settings/project_settings_source_data.js) `openSourcePanel`, `showPanelStep`, `validateImportSettings`, `PANEL_STEPS`; [project_settings.css](../../../frontend/ui/project_settings/project_settings.css) import-window rules.
- [project_settings_module_split.test.mjs](../../../frontend/tests/project_settings_module_split.test.mjs) and [project_settings_source_data.test.mjs](../../../frontend/tests/project_settings_source_data.test.mjs).
- Memory notes [arcrho-dev-ui-cache-restart](../../../agent-memory/arcrho-dev-ui-cache-restart.md), [theme-css-version-pins](../../../agent-memory/theme-css-version-pins.md), [frontend-node-test-suite](../../../agent-memory/frontend-node-test-suite.md).
- Version and size guards: [project_settings_data_processing_rules.test.mjs](../../../frontend/tests/project_settings_data_processing_rules.test.mjs) pins the page's stylesheet list and one shared `?v=` stamp for every Project Settings stylesheet; [project_settings_module_split.test.mjs](../../../frontend/tests/project_settings_module_split.test.mjs) caps the coordinator below 1,800 lines and pins the split modules to the coordinator's stamp; [color_theme.test.mjs](../../../frontend/tests/color_theme.test.mjs) pins the coordinator stamp.

**Do.**
- [x] New module `frontend/ui/project_settings/project_settings_combined_source.js` (and a CSS file if the rules exceed a screenful) owning the combined state: tables, keys, rows, exclude, rename; key auto-detection by name (decision 5); serialization to and from the decision 3 block.
- [x] Add Table on the single-table form: menu of tables in the current connection (from `/source_table/tables`), recent CSV via the existing browse, "Another SQL Server database…". Picking one opens the details window in add mode with the nickname box focused and suggested.
- [x] Table list grouped by SQL connection and CSV, drag to reorder (pointer capture, per memory [pointer-capture-drag-fix](../../../agent-memory/pointer-capture-drag-fix.md)), base tag, remove, join-order note; no paths on the list.
- [x] Details window (second-level window over the import window): nickname, source fields, column table with "Used As", Remove Table, Save; Escape and backdrop close it.
- [x] Removing tables back to one returns to today's form with that table's settings.
- [x] The single-table form, its validation and its save are unchanged when only one table exists.
- [x] Bump the module version stamps and their test pins.

**Tests.** New `frontend/tests/project_settings_combined_source.test.mjs` for the state module: add/remove/reorder, key auto-detection, nickname fallback, serialization round trip, back-to-one. Existing source data tests pass.

**Done when.** Node tests pass (diff against a baseline per the memory note) and the window renders the list and details window in a dev app launch or an Electron screenshot check ([electron-ui-screenshot-check](../../../agent-memory/electron-ui-screenshot-check.md)).

**Estimate.** Estimate: code edit 50 min, test/validation 25 min, total 75 min. Actual: code edit 11 min, test/validation 4 min, total 15 min (the prototype already spelled out the list and details window, and the state tests passed first run; the only rework was the coordinator line cap and the shared stylesheet stamp).

### Step 6 — Combine step: Join Map, Row Match, Preview

**Goal.** With two or more tables the window shows the Combine step: the Join Map with key rows across table cards, row rules, column lists, and the Row Match and Preview tabs fed by the preview route.

**Read first.**
- The prototype's `renderCombine`, `renderResult`, `renderPreview`, the `key`, `join`, `chip`, `add-key`, `remove-key`, `convert` actions, and the popover.
- Step 5's module; step 4's preview route.
- [project_settings_source_data.js](../../../frontend/ui/project_settings/project_settings_source_data.js) `showPanelStep`, `goToNextPanelStep`, `goToPreviousPanelStep`, `setSourceStatus`, and the step-list pins in [project_settings_source_data.test.mjs](../../../frontend/tests/project_settings_source_data.test.mjs) ("Import Data is preceded by an Import Scope step").
- [combined_source_service.py](../../../frontend/app_server/services/combined_source_service.py) `combine_tables`: the coverage bar needs the combined row count by number of tables, which the preview did not return.
- The dark theme paints every `button` like an input (`dark.css`, `:is(..., button)` at 0-3-0); flat buttons need a stronger dark rule.
- Skill `arcrho-ui-design`.

**Do.**
- [x] Insert the Combine step between Source and Datasets only when there are two or more tables (`PANEL_STEPS` and titles become dynamic).
- [x] Join Map as in the prototype: label column, one card per table (nickname, "SQL table"/"CSV file", row count; click opens the details window), rails, key cells with Fill/Any/convert menu, row-rule pill with Venn icons, plain value-column list (leave out, rename, clash suffix), Combined Table card.
- [x] Row Match tab: per-table bars, coverage bar, warnings with one-click fixes; Preview tab: first rows with column headers coloured by table.
- [x] Preview requests are debounced and show a loading state; an error from the route shows in place with its message.
- [x] Next from Combine requires at least one key and no unresolved `format_mismatch` the person has not dismissed.

**Tests.** Extend `project_settings_combined_source.test.mjs`: key cell edits, row rules, exclude/rename, clash suffix, step list with one and two tables, preview request payload equals the serialized block.

**Done when.** Node tests pass and a screenshot check shows the Join Map and both tabs with the fixture data.

**Estimate.** Estimate: code edit 55 min, test/validation 25 min, total 80 min. Actual: code edit 13 min, test/validation 12 min, total 25 min (the prototype spelled out the map and both tabs; the preview gained a coverage count, and the screenshot check caught a class clash, missing border-box sizing and the dark theme's button paint).

### Step 7 — End-to-end import and the Source Data header

**Goal.** Import Data on a combined source saves it, imports it on the client with progress, runs the refresh job, and the Source Data tab describes the combined source and reopens on it.

**Read first.**
- [project_settings.js](../../../frontend/ui/project_settings/project_settings.js) `saveImportSettings`, the import functions around the `/source_table/import` call and `server_can_import`, and the source state read near `sourceState.sourceType`.
- [project_settings_source_data.js](../../../frontend/ui/project_settings/project_settings_source_data.js) `importData`, `normalizeSourceState`, `getSourceIdentity`, `syncImportEntry`.
- Step 4's routes.
- [project_settings_combined_source.js](../../../frontend/ui/project_settings/project_settings_combined_source.js) `fromCombinedBlock`, `setTableColumns` (a base read re-proposes the keys, so a restored table needs its own column store), `describeInto`, `combineProblem` (needs a fresh preview, which Import Again never has).
- The coordinator was 2 lines under its 1,800-line cap, and the page modules have no DOM test harness, so the save and import sequence moved into its own module to be testable with a stub fetch.

**Do.**
- [x] `normalizeSourceState` carries `combined`; the window opens on the saved tables, keys and rules.
- [x] `importData` for a combined source: save through `/source_table/combined/save`, import through `/source_table/combined/import` with the existing upload progress, then submit the refresh job with `import_source` off, as the SQL path does.
- [x] Header: stacked table dots, "Combined source", "N tables · K keys", row and column counts; Import Again re-imports with the saved settings; the details panel lists each table's nickname and source.
- [x] Single-table save, import, Import Again and header are unchanged.

**Tests.** Extend the Node tests for state normalization, the import call sequence for combined, and unchanged single-table sequences (CSV share, CSV local, SQL).

**Done when.** Node and Python suites touched by the plan pass against their baselines.

**Estimate.** Estimate: code edit 30 min, test/validation 20 min, total 50 min. Actual: code edit 15 min, test/validation 4 min, total 19 min (the C: drive filled up before the commit, which the orchestrating session made after re-running the tests).

### Step 8 — Deploy the server parts

**Goal.** Gateway and Engine run the new server code.

**Read first.** Memory notes [deploy-only-when-released-app-is-safe](../../../agent-memory/deploy-only-when-released-app-is-safe.md), [deploy-without-asking](../../../agent-memory/deploy-without-asking.md), [remote-component-deploy](../../../agent-memory/remote-component-deploy.md), [local-test-root](../../../agent-memory/local-test-root.md).

**Do.**
- [x] Re-check the ship-impact statement against the landed diff: no request or response the released app uses changed shape, and single-table records are unchanged. If that fails, stop and record it under "Open decisions".
- [x] Check `git status` for other sessions' uncommitted work; deploy with `--ref <sha>` if present.
- [x] `py -3.10 server-components/deploy.py --stale`, then deploy what is stale (expected: Gateway and Engine), and confirm with the deployed canonical copy (`grep -c save_combined_source`).

**Tests.** The deploy's own verification and a `GET /source_table` of a single-table project through the dev app showing the same answer as before.

**Done when.** The deployed copies carry the new service and the single-table answer is unchanged.

**Estimate.** Estimate: code edit 0 min, test/validation 25 min, total 25 min. Actual: code edit 2 min, test/validation 6 min, total 8 min (the build server's warm slots made the four-component deploy take about 3 minutes).

### Step 9 — Demo and GUI check in the Aug fake project

**Goal.** A combined source is built in the Aug fake project through the app, imported, and every screen of the flow is checked by screenshots; a single-table project is checked unchanged.

**Read first.** Memory notes [arcrho-launch-electron-detached](../../../agent-memory/arcrho-launch-electron-detached.md), [desktop-input-control-works](../../../agent-memory/desktop-input-control-works.md), [arco-is-the-app-name](../../../agent-memory/arco-is-the-app-name.md), [agent-share-listing-blocked-use-python](../../../agent-memory/agent-share-listing-blocked-use-python.md). The user allowed edits to the Aug fake project (`NJ_Annual_Prod_202608_Fake` on the production server) on 2026-10-12; no other project may be edited.

**Do.**
- [x] Record the project's current `source_import.json` and field mapping so the demo can be undone.
- [x] Build the combined source from the project's current source table plus at least one more table (split columns of its own source into two CSVs if no second real table exists), with at least one renamed key, one filled key and one left-out column.
- [x] Walk the flow with screenshots: Add Table and nickname, details window, list reorder, Combine step, a key fix, Row Match, Preview, Import, the header after import, Import Again.
- [x] Open a single-table project's Source Data tab and import window and confirm they look and behave as before.
- [x] Fix any defect found in a follow-up commit within this step, or record it under "Open decisions" if it needs a decision.

**Tests.** The screenshots and the import's status JSON (rows and columns as the preview predicted).

**Done when.** The combined import succeeded in the Aug fake project, the screenshots match the prototype's behaviour, and the single-table check found no change.

**Result (2026-10-12).**
- **Demo source.** The project's master table split into three CSV files under `E:\XWSpace\Repos\ArcRho\tmp_data\combined_source_demo\` (they must stay while the project uses them): `Loss A` (base, keys and 12 loss columns, 306,210 rows), `Loss B` (the same rows, `CO_CD` spelled `Co_Cd`, the other 11 loss columns, a junk `FACID` column left out and an empty column dropped on read), and `EP` (39,915 premium rows without `sys_yrmo`, filled with `0`). Seven keys, both joins `All Rows`.
- **Import.** The preview and the import both gave 346,125 rows and 34 columns, and the new master table is identical, cell for cell and in order, to the one it replaced. Import Again gave the same. The refresh scope was narrowed to Earned Premium and one class path, so the Engine job refreshed nothing downstream.
- **Undo.** The previous `source_import.json`, `field_mapping.json` and `table_summary.json` are kept under `tmp_data\combined_source\undo\`; the field mapping did not change. Choosing the original CSV again through Change source and importing restores the single-table record.
- **Single-table check.** `NJ_Annual_Prod_202605_Fake`'s Source Data tab and import window opened as before and were closed without saving.
- **Not defects.** A drag in the table list driven by the Arco window tool's synthetic input stayed half-finished until the next click; the same drag with the real mouse reordered correctly. The Engine refresh status reports `column_count` 0 after any client upload (SQL Server as well), while the source record holds the right count.

**Estimate.** Estimate: code edit 5 min, test/validation 40 min, total 45 min. Actual: code edit 6 min, test/validation 23 min, total 29 min (the demo split the project's own master table into three CSV tables, so no second real table was needed and the result could be checked cell for cell).
