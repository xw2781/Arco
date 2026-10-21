## Purpose
<!-- MANUAL:BEGIN -->
Bootstrap method page: an over-dispersed Poisson bootstrap of a DFM, simulated from a seed and scaled onto a target ultimate. It keeps ResQ's Bootstrap features but not its layout: setup tabs come first, the targets sit with the inputs, and the run state is always visible above the tabs.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.bootstrap.entry_points -->
- `ui/method_pages/bootstrap/bootstrap.html`: external scripts `/ui/method_pages/bootstrap/bootstrap_main.js?v=20261020a`, `/ui/shared/services/color_theme.js?v=20260923c`, `/ui/shared/tabbed_page/initial_tab_paint.js?v=20260824d`; inline imports _none_.

Detected `fetch(...)` targets in key JS files:
- `/datasets/cached?${qs.toString()}`

Detected `arcrho:*` message types in key JS files:
- `arcrho:bst-tab-changed`
- `arcrho:dataset-dirty`
- `arcrho:project-instance-refresh-datasets`
- `arcrho:status`
- `arcrho:window-run-state`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.bootstrap.key_files -->
- [`ui/method_pages/bootstrap/bootstrap.html`](../../ui/method_pages/bootstrap/bootstrap.html) - Bootstrap iframe page.
- [`ui/method_pages/bootstrap/bootstrap_main.js`](../../ui/method_pages/bootstrap/bootstrap_main.js) - Bootstrap state, load/save flow, rendering, and tab coordination.
- [`ui/method_pages/bootstrap/bootstrap_page_model.js`](../../ui/method_pages/bootstrap/bootstrap_page_model.js) - Pure settings, residual-flag, Targets-row, and Results-view rules the page and its tests share.
- [`ui/method_pages/bootstrap/bootstrap_method_api.js`](../../ui/method_pages/bootstrap/bootstrap_method_api.js) - Bootstrap load/simulate/ladder/save transport adapter.
- [`ui/method_pages/bootstrap/bootstrap_residual_chart.js`](../../ui/method_pages/bootstrap/bootstrap_residual_chart.js) - Residuals-tab scatter renderer.
- [`ui/shared/components/reserve_range/reserve_range_model.js`](../../ui/shared/components/reserve_range/reserve_range_model.js) - Results views shared with the Stochastic Consolidation page: rows, columns, ladder, clipboard, fan bands, distribution markers.
- [`ui/shared/components/reserve_range/reserve_range_table.js`](../../ui/shared/components/reserve_range/reserve_range_table.js) - Shared Results summary-table and full-ladder markup.
- [`ui/shared/components/reserve_range/reserve_distribution_chart.js`](../../ui/shared/components/reserve_range/reserve_distribution_chart.js) - Shared Results distribution chart of the total with the chosen percentiles marked.
- [`ui/shared/components/reserve_range/reserve_fan_chart.js`](../../ui/shared/components/reserve_range/reserve_fan_chart.js) - Shared Results fan chart of the mean and percentile bands by origin.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opens from Project Instance as a floating iframe method window at `/ui/method_pages/bootstrap/bootstrap.html`. A dataset row whose Method Type is `Bootstrap` opens it (on Results by default, per the Default Tabs preference), and `Add > Bootstrap` on a vector row whose Method Type is `None` opens a new one on Details with that row as its output. Unlike Cape Cod there is no shell tab type: standalone method tabs are legacy and no Bootstrap tab has ever existed to restore.
- Tabs, in order: `Details`, `Residuals`, `Simulation`, `Targets`, `Results`, `Notes`, `Audit Log`, owned by `ui/shared/tabs/window_tab_catalog.js`. The page reports tab changes with `arcrho:bst-tab-changed`, and Project Instance snapshots carry `kind: "bootstrap"` plus `bstTab`.
- Layout, shared with Stochastic Consolidation: no header above the tabs. The run-state chip sits beside the window title, drawn by Project Instance from the page's `arcrho:window-run-state` message (`Not run yet`, `Simulating` while a run is in flight, `Up to date`, or `Inputs changed — run again` while a setting that changes a run differs from the run on screen). The Simulate, Save and Cancel buttons sit together at the right of the bottom save bar, as on the other method pages. A Simulate shows a running card over the page (a Galton board piling balls into a bell curve, with the elapsed time) for at least two seconds, from `ui/shared/components/simulation_run/`. The page and every table scroll under the shared framed scrollbar (`ar-framed-scroll`, driven by `ui/shared/styles/framed_scroll_activity.js`). The value grids select like the other method grids through `ui/shared/components/spreadsheet/method_grid_selection.js`: click, drag, Shift and Ctrl selection, row and column labels, arrow keys, Escape, Ctrl+C and a right-click menu with Copy values and Remove Highlights; a copied cell gives its raw figure. Cell text is never selectable as text.
- Loads through `/bootstrap/load`, simulates through `/bootstrap/simulate`, and saves through `/bootstrap/save` (see [`bootstrap`](../app_server/domains/bootstrap.md)). Simulate sends the settings on screen to the run-only route, which writes nothing, and shows the returned run unsaved: the page stays dirty until Save or Cancel. Every save re-simulates on the server from the same seed, so a Save after Simulate publishes the run on screen; when no run on screen matches the settings, the save's progress card says it runs the model too. Simulate stays available when nothing changed, so the stored settings can be run again. The chip compares a snapshot of the settings that change a run (everything but the name, output type, category and the scale-values display switch) with the one the run on screen was made from. The page never computes a derived value itself. It sends the loaded method back with only its owned settings changed, and the server rebases those settings through `apply_owned_patch`.
- Saves run behind the shared saving animation, show the post-save review warning and saved-dependents notice, and ask Project Instance to refresh its dataset table, as the other method pages do. Help > Open Dataset JSON File opens `methods/BST@<Name>.json`.
- Open-window change alert: after a load or save the page watches its `BST@` method file and output sidecar through the shared object-change watch.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- `bootstrap_page_model.js` owns every rule the page applies: which settings it edits and how they are read from and written back into the method (writing back what it read leaves the method unchanged), the option lists and labels, the run-state chip, the residual flag rule, the Targets rows, and every Results view (the rows by origin, the table columns, the full ladder, the clipboard text, the percentile chooser, the fan bands and the distribution markers). The Results views, the table markup and the two charts live in `ui/shared/components/reserve_range/`, shared with the Stochastic Consolidation page; the page model re-exports the views under their Bootstrap names, and the chart modules only draw what they are handed.
- **Details**: Name (read-only once saved, because a save cannot change a method's identity), Output Type, the DFM picker (it lists DFM output vectors and stores the DFM's method name, and stretches with the window like the other boxes), the Dependencies map, the inherited Origin and Development Lengths read-only, and the model as a segmented control. Mack is shown disabled with a "not available yet" tooltip. ResQ's single-scale checkbox is the same setting as the model and appears only here.
- **Residuals**: one toolbar with the residual type, the two scale-value smoothers, and Show Scale Values; below it the residual grid, which widens with the window, and under the grid a scatter of residuals by development period that resizes with it. A residual is flagged in the warning colour when its size reaches 1.5 times the root mean square of the residuals in the same grid, which matches ResQ's red cells for the reference method and stays meaningful for the unscaled types. Show Scale Values adds the Unsmoothed, Smoothed, User Entry and Selected rows for both scale blocks; User Entry cells are editable and must be positive or blank. A caption gives the zero-mean adjustment, the bias factor, and the data point and parameter counts.
- **Simulation**: simulations, the seed with New Seed, the pseudo-data and forecast distributions, prevent negative cumulative data, and the two negative-mean choices; the over-dispersed Poisson one is disabled unless a distribution is ODP.
- **Targets**: the target ultimate picker (with Clear) and one row per origin: target ultimate, target reserve, scaling method (a dropdown), CV (editable only for User Defined, entered in percent and stored as a fraction), unscaled mean reserve, target minus unscaled, and target over unscaled, with a total row. Target values and unscaled means come from the last run, and a caption says so while a changed target is unsaved.
- **Results** reads only the simulation summary of the run on screen (the stored one, or an unsaved Simulate's). A toolbar holds the `Scaled / Unscaled` and `Reserves / Ultimates` switches, the percentile chooser (default 50, 75, 90, 95, 99, 99.5; any half-percent step from 0 to 100, at most 12, typed as a list), Full Ladder, and at the toolbar's right end Copy Table and Download CSV. The summary table has one row per origin and a total: latest, mean, standard deviation, CV (blank for a zero or negative mean), the chosen percentiles, the mean of the other measure, the DFM's figure, and mean minus DFM. Full Ladder turns it into ResQ's Detail grid: statistics down the side (every percentile at the chosen interval between the minimum and maximum, the chosen ones in bold) and origins plus the total across. The interval dropdown beside Full Ladder, enabled only while it is ticked, offers ResQ's 5%, 1%, 0.1% and 0.01% steps plus the stored 0.5% (the default). The coarser three read the stored ladder; 0.1% and 0.01% ask `/bootstrap/ladder` to re-run the run on screen from its seed, and the table shows a working row until that ladder arrives (Copy Table and Download CSV wait for it). A failed re-run falls back to 0.5% with the reason in the status bar. The finer ladder belongs to the run on screen, so a new Simulate or load works it out again. Copy Table puts the table on the clipboard as tab-separated plain numbers, and Download CSV saves the same rows as a CSV file through the desktop save dialog; each button shows a check for a moment once done. Below the table sit two charts side by side (stacked below 1,100px): the distribution of the total as the stored histogram with the mean and the chosen percentiles marked, and a fan chart by origin with the mean, the DFM as a dashed line, and one band per symmetric pair of the chosen percentiles. An ultimate is the latest plus the reserve, so the ultimates view moves every reserve figure by the latest. A notice with Simulate appears above the table while the settings on screen differ from the run's, and until a run exists the tab shows an empty state with Simulate. The view choices are page state and never make the method dirty.
- Every select-like control opens one shared in-page menu styled to the app, with keyboard navigation.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change what a tab edits: update `bootstrap_page_model.js` and `tests/bootstrap_frontend.test.mjs`, and check that the field is one `apply_owned_patch` in `python-api/src/arcrho_api/bootstrap_contract.py` accepts.
2. Change Bootstrap routing: update the Project Instance dataset table, window, and message modules together.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- No dark-theme rules exist for the page yet, like Cape Cod.
<!-- MANUAL:END -->
