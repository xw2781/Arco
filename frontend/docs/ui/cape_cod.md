## Purpose
<!-- MANUAL:BEGIN -->
Cape Cod method page replicating the ResQ Generalised Cape Cod method: an ultimate vector produced from a latest actual triangle, an exposure vector, and a prior ultimate vector, with trend adjustment and decay-weighted expected ultimate ratios.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.cape_cod.entry_points -->
- `ui/method_pages/cape_cod/cape_cod.html`: external scripts `/ui/method_pages/cape_cod/cape_cod_main.js?v=20261020a`, `/ui/shared/services/color_theme.js?v=20260923c`, `/ui/shared/tabbed_page/initial_tab_paint.js?v=20260824d`; inline imports _none_.

Detected `fetch(...)` targets in key JS files:
- `/dataset/cache/load`
- `/datasets/cached?${qs.toString()}`
- `/dfm/development-pattern?${qs.toString()}`

Detected `arcrho:*` message types in key JS files:
- `arcrho:cc-tab-changed`
- `arcrho:dataset-dirty`
- `arcrho:project-instance-refresh-datasets`
- `arcrho:status`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.cape_cod.key_files -->
- [`ui/method_pages/cape_cod/cape_cod.html`](../../ui/method_pages/cape_cod/cape_cod.html) - Cape Cod iframe page.
- [`ui/method_pages/cape_cod/cape_cod_main.js`](../../ui/method_pages/cape_cod/cape_cod_main.js) - Cape Cod state, persistence, calculation, and tab coordination.
- [`ui/method_pages/cape_cod/cape_cod_ratios_chart.js`](../../ui/method_pages/cape_cod/cape_cod_ratios_chart.js) - Cape Cod Ratios-tab renderer.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opens from Project Instance as a floating iframe method window at `/ui/method_pages/cape_cod/cape_cod.html`. Home no longer offers a Cape Cod launch card. `tab_actions.openCapeCodTab` and the shell's `cape_cod` tab type remain only so a previously opened standalone Cape Cod tab still restores; the shell API does not expose an entry point that creates one.
- Uses `ui/shared/tabbed_page/` for reusable tab chrome and pop-out behavior, and the shared Details/Notes/Audit tab presentation modules; tab order is `Details`, `Method`, `Ultimates`, `Ratios`, `Notes`, `Audit Log`, matching the ResQ Cape Cod editor.
- The Details tab is three sections separated by light rules and carrying no headings: identity - Name, Output Type, Project, Segment - then `Prior Ultimate Type` (the `Latest / Ultimates` or `Pattern` mode dropdown) and the Data Flow map, where the datasets the method is built from - `Latest`, `Exposure`, and `Prior Ultimate` - are chosen through each box's `...` button or a dashed `Choose` box while empty - then Origin Length at the shared short field width.
- `Ctrl+PageUp` and `Ctrl+PageDown` cycle through Cape Cod tabs with wraparound through the shared tabbed-page runtime, including when the shell or Project Instance host still owns keyboard focus.
- Loads a saved method through `/cape-cod/load`, which reads only `methods/CC@<Name>.json` and the output sidecar; the response also carries the derived as-if `ultimates_triangle` for the Ultimates tab.
- Saves through `/cape-cod/save`, which publishes `methods/CC@<Name>.json`, the native `datasets/<Name>@<OriginLength>.csv`, supported coarser CSV variants, and the output sidecar as one server-owned transaction with the sidecar written last.
- Save is available whenever the method has unsaved changes, and it stays available on a clean page whose output carries the Needs Review flag, because re-saving the method unchanged is what clears that flag; `updateTabbedPageSaveControls` in `ui/shared/tabbed_page/tabbed_page.js` owns that rule for every method page, and the flag itself comes from the output sidecar `status` the last load or save returned, read through `ui/shared/dataset/review_status.js`. Cancel remains clickable throughout.
- A Cape Cod save runs behind the shared saving animation described in [`dataset.md`](dataset.md), titled `Saving Cape Cod`, so the page cannot be edited while the save settles. `saveCapeCod` wraps the save in it, so the Save bar and the shell save message are both covered; the card then streams the dependent walk's live updates and the spinner is dismissed before the post-save review warning and before the Engine-unavailable message box. Neither explicit save entry point closes the window: after a clean walk (`propagationClean`) they show the saved-dependents notice and leave the method open, and a failed or stalled walk shows no notice.
- The output sidecar keeps `source_kind: "cape_cod"`, `method_type: "Cape Cod"`, Notes, Audit, status, and dependency graph fields.
- Uses Project Instance `arcrho:dataset-dirty`, `arcrho:dataset-save`, `arcrho:dependency-source-preview`, `arcrho:dependency-source-cleared`, `arcrho:project-instance-refresh-datasets`, `arcrho:project-instance-open-dependent-dataset`, and `arcrho:cc-tab-changed` messages.
- Open-window change alert: after a successful method load or save, the page watches its `CC@<name>.json` and output sidecar through `/object_change/fingerprint` (`ui/shared/services/object_change_watch.js`) and shows a one-time "close and reopen" message box when another user or the Engine dependent-propagation job rewrites the method; the save flow pauses and rebases the watch so its own writes never alert. The alert offers a Refresh Now action that reloads the window in place when it has no unsaved changes. The alert names the writer: the window reads the object's recorded attribution once after the fingerprint moved and says who saved it, or which automation task rewrote it and the account it ran as. A stale mapped-drive read of the window's own save never raises it: a change is only reported when the object's recorded write is newer than what this window already has. Dependent-propagation jobs started by this app instance never raise the alert: Project Instance broadcasts `arcrho:dependent-propagation-started`/`-finished` scope messages that pause the watch for the job's project and reserving class and rebase it at the terminal status.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- The canonical method type label is exactly `Cape Cod` in UI, method JSON, and sidecar metadata.
- V1 inputs are one latest triangle, one exposure vector, and one prior ultimate vector. `pattern` mode reads percentages directly from the selected vector. `latest_ultimates` mode takes Percentage Developed from the development factors of the DFM that published the prior ultimate -- `1 / cumulative development factor` at each origin's own development age, read from that DFM's method JSON the way a Bootstrap reads its DFM precedent, and stored as the `prior_ultimate_percentage_developed` snapshot covered by `prior_ultimate_source_revision`. Dividing Latest by the prior ultimate cannot describe an origin whose latest observation is zero, and produced percentages above 100% whenever the Latest triangle was not the one the DFM was built on. Cape Cod also accepts a prior ultimate with no DFM behind it, which carries no pattern; only that case still falls back to `Latest / Prior Ultimate`.
- Owned parameters mirror ResQ one-to-one: Trend Rate (decimal, displayed as a six-decimal percentage), Fit and Auto Fit, Decay Factor, Scaling (`percentage`/`unscaled`/`auto_scaled`), Decimal Places, Alternative Ultimate Calculation, and per-origin manual Trend Factor overrides. Fitting or changing the trend rate clears the overrides, and Auto Fit keeps trend factor cells read-only, matching ResQ.
- The Method grid columns and totals follow the ResQ Cape Cod Method tab: Origin, Latest, Exposure, Trend Factor, Trended [Latest], Percentage Developed, Development Factor, Developed [Exposure], Future [Exposure], Trended Developed Ratio, Expected Ultimate Ratio, Detrended Expected Ratio, Future [Latest], Cape Cod Ultimate, and Cape Cod Ultimate Ratio, with dataset names embedded in the bracketed captions.
- Every calculation is owned by `python-api/src/arcrho_api/cape_cod_contract.py` and mirrored exactly by `cape_cod_json_contract.js`; the formulas were verified against the ResQ COM output of a production Cape Cod method (see `frontend/docs/plans/cape_cod_method_plan.md`).
- The Ultimates tab shows the as-if diagnostic triangle: each historical cell re-estimated on its own calendar diagonal with the current parameters. ArcRho computes it at the dataset's stored development points only (cell-exact with ResQ there); ResQ's spline-interpolated in-between display columns are intentionally not reproduced.
- The Ratios tab plots Latest/Exposure, Trended Latest/Exposure, Trended Developed Ratio, Expected Ultimate Ratio, Detrended Expected Ratio, and Cape Cod Ultimate Ratio by origin.
- ResQ/RPC sync, vector-latest input, Single/All Origin graphs, and manual Exposure/Percentage-Developed cell overrides are deferred.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change Cape Cod calculation behavior: update `python-api/src/arcrho_api/cape_cod_contract.py` first, mirror `ui/method_pages/cape_cod/cape_cod_json_contract.js`, and keep `frontend/docs/plans/cape_cod_method_plan.md` in sync.
2. Change Cape Cod persistence or refresh behavior: update the canonical Python contract, app-server service, frontend payload adapter, migration producer, exact parity tests, and app-server domain documentation together.
3. Change Cape Cod routing: update Project Instance dataset table, window, and message modules together.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- The JS calculation mirror must remain identical to the Python contract; a drifted mirror makes the server reject saves because derived columns no longer match the embedded snapshots.
- The persisted method label must remain `Cape Cod` so Project Instance and Data Flow map boxes route to the Cape Cod page.
- Percentage Developed near 1.0 makes Future Exposure a small difference of large numbers; ArcRho's canonical six-decimal rounding bounds its absolute error at the exposure scale, which is visible only when decimals are increased.
- Out-of-band source-file edits bypass the managed dependency event and require an ArcRho save or explicit repair before a Cape Cod can be refreshed automatically.
<!-- MANUAL:END -->
