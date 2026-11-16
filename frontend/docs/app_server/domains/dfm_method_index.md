# App Server Domain: Dataset Instance Index

## Purpose
<!-- MANUAL:BEGIN -->
Dataset instance index routes maintain a reserving-class-scoped `index.json` cache of logical dataset instances, minimal Project Instance table metadata, folder signatures, and method-backed dataset associations. Project Instance uses the index for its cached dataset table, and the DFM Details `Name` selector uses `files` entries with `method_type: "DFM"` for DFM-backed dataset names.
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->
Routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/dfm/method-index?project_name=<name>&reserving_class=<path>&refresh=false` | Return the cached dataset instance index for a project/reserving-class path, rebuilding it only when it is missing, invalid, outdated, or `refresh=true`. |
| `GET` | `/dfm/percent-developed-curve?project_name=<name>&reserving_class=<path>&method_name=<name>` | Read the matching local DFM method JSON from a project and return computed `% Developed` curve points for prior-project comparison overlays. |
| `GET` | `/dfm/development-pattern?project_name=<name>&reserving_class=<path>&dataset_name=<name>` | Return the percentage developed for each origin of the DFM that published `dataset_name`: `1 / cumulative development factor` at each origin's own development age. Resolves the dataset's sidecar to its DFM method, then projects the method JSON through `arcrho_api.dfm_contract.dfm_percent_developed_vector`. `422` when the dataset is not a DFM output, `404` when its method file is missing. Bornhuetter Ferguson and Cape Cod windows read their Percentage Developed from it. |
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `app_server/api/dfm_method_index_router.py` - Thin API routes.
- `app_server/services/dataset_instance_index_service.py` - Project/reserving-class path resolution, current-index validation, rebuild-reason logging, per-index locking, API response metadata, and delegation to the canonical builder.
- `python-api/src/arcrho_api/dataset_index_contract.py` - Canonical version/schema, bounded-parallel physical scan, method-output extraction, scalar row projection, folder signature, validation, serialization, and atomic write shared by frontend and migration.
- `ui/method_pages/dfm/dfm_details.js` - Details `Name` selector UI that consumes the index.
- `ui/method_pages/dfm/dfm_startup_state.js` - Last-opened DFM object project-user preference state and index refresh helper.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Cache file path: `projects/<project>/data/<ReservingClassFolder>/index.json`.
- Indexed method files must match local DFM method storage: `projects/<project>/data/<ReservingClassFolder>/methods/DFM@<Name>.json`.
- The persisted index stores location-independent `files` and `folder_signature` data, never producer-local absolute `folder_paths`. The app server adds locally resolved `folder_paths` only to its response for file watching and reveal/open operations. One canonical contract owns the persisted version, schema, entry projection, normalization, and deterministic ordering; the bundled frontend app server, public Python API, ResQ migration, and mirrored migration macro emit the exact same full parsed payload for identical logical inputs even when the same server folder is reached through different drive-letter or UNC aliases. `folder_signature` is a short `sha256:` digest of reserving-class cache-file names, sizes, modification times, and folder existence. The `files` list is a logical dataset-instance list, not a physical inventory: mode-qualified triangle and vector cache variants collapse into a base instance, while older two-length-only names remain literal. Encoded names are decoded from the reversible `_%XX_` form before logical matching. Each entry is a scalar summary sourced only from reserving-class datasets, sidecars, and methods; arrays and nested details such as `origin_labels`, dependency graphs, and audit logs stay in their owning JSON. Project Dataset Type formula/category defaults are resolved by consumers instead of being copied into the persisted index; the indexed `user` value remains the raw reserving-class-owned text, and any optional display-name mapping is presentation-only. For DFM entries, `name` uses `details tab.output dataset` or `output vector`, falling back to `details tab.name` and then `output type`; `dataset_type` uses `output type`. When the method-file name differs from that output identity, the row includes scalar `method_name` from `details tab.name`, which Project Instance and the DFM Details selector use to open `DFM@<method_name>.json`.
- `GET /dfm/method-index` (and Project Instance's `GET /datasets/cached`) is the `dataset_index` Server-hosted workspace read: when the Gateway advertises it, the signature check and any rebuild — the path that opens every sidecar and method JSON in the class — run on the server host, and the response's `folder_paths` are rebased onto the client's workspace root. See [`workspace_reads`](workspace_reads.md).
- `GET /dfm/percent-developed-curve` and `GET /dfm/development-pattern` are the Gateway-required `dfm_percent_developed_curve` and `dfm_development_pattern` reads, and `POST /dfm/method-index/refresh` is the Gateway-required `dataset_index_rebuild` mutation (step 9 of [client_smb_retirement.md](../../../../docs/plans/completed/client_smb_retirement.md)). A Client PC answers `503` rather than reading or rewriting the class folder over the share; server processes run the services locally.
- Normal DFM saves and app-server generated dataset cache writes request an index refresh for the current project/reserving-class path after files are written, so Project Instance and the Details `Name` selector use the shared durable cache instead of scanning folders during every page load.
- A valid current index is returned as persisted without scanning `datasets/`, `methods/`, or `sidecars/` and without rewriting or enriching `index.json`. The index is rebuilt from those folders only when the endpoint is called with `refresh=true`, a durable mutation requests refresh, or the cache is missing, invalid, or uses an outdated canonical version/schema.
- Contract tests compare the complete frontend, public Python API, and migration-produced payloads for exact equality across path aliases and verify that a valid current index read performs neither a detail-file scan nor an index write.
- `% Developed` curve lookup is read-only. It uses the same local DFM filename convention, reads `data tab`.`development labels` for x-axis month indexes, reads `ratios tab`.`ratio triangle`.`development labels` for displayed ratio period labels, reads `ratios tab`.`average formulas`.`selected` and `values`, derives selected/cumulative/% developed values, and returns only plot points and request metadata. Missing or incomplete DFM methods return explicit API errors so the frontend does not add a comparison line.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Filename parsing assumes the local DFM method filename convention. If method filenames are renamed, update the parser and chooser together.
- The cache lives in each durable reserving-class `data/<ReservingClassFolder>` folder and is duplicated with the project; locked or inaccessible folders surface as API errors in the chooser or Project Instance status areas. External file edits that do not refresh `index.json` are not reflected until the endpoint rebuilds the index.
<!-- MANUAL:END -->
