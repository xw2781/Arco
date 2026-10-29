## Purpose
<!-- MANUAL:BEGIN -->
Stochastic Consolidation method page: combines the simulated reserves of several Bootstrap methods ("segments"), which live in other reserving classes, into one total reserve range with chosen correlations, the way ResQ's Stochastic Consolidation does. It keeps ResQ's features but not its layout: ResQ's one-control Simulation tab is folded into Details, the correlation matrix shows what the run really used and achieved, and the Results tab adds a segment breakdown.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.stochastic_consolidation.entry_points -->
- `ui/method_pages/stochastic_consolidation/stochastic_consolidation.html`: external scripts `/ui/method_pages/stochastic_consolidation/stochastic_consolidation_main.js?v=20261028a`, `/ui/shared/services/color_theme.js?v=20260923c`, `/ui/shared/tabbed_page/initial_tab_paint.js?v=20260824d`; inline imports _none_.

Detected `arcrho:*` message types in key JS files:
- `arcrho:dataset-dirty`
- `arcrho:project-instance-refresh-datasets`
- `arcrho:scon-tab-changed`
- `arcrho:status`
- `arcrho:window-run-state`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.stochastic_consolidation.key_files -->
- [`ui/method_pages/stochastic_consolidation/stochastic_consolidation.html`](../../ui/method_pages/stochastic_consolidation/stochastic_consolidation.html) - Stochastic Consolidation iframe page.
- [`ui/method_pages/stochastic_consolidation/stochastic_consolidation_main.js`](../../ui/method_pages/stochastic_consolidation/stochastic_consolidation_main.js) - Stochastic Consolidation state, load/consolidate/save flow, rendering, and tab coordination.
- [`ui/method_pages/stochastic_consolidation/stochastic_consolidation_page_model.js`](../../ui/method_pages/stochastic_consolidation/stochastic_consolidation_page_model.js) - Pure settings, correlation-matrix, segment-check, run-state, and segment-breakdown rules the page and its tests share.
- [`ui/method_pages/stochastic_consolidation/stochastic_consolidation_method_api.js`](../../ui/method_pages/stochastic_consolidation/stochastic_consolidation_method_api.js) - Stochastic Consolidation load/consolidate/candidates/save transport adapter.
- [`ui/shared/components/reserve_range/reserve_range_model.js`](../../ui/shared/components/reserve_range/reserve_range_model.js) - Results views shared with the Bootstrap page.
- [`ui/shared/components/reserve_range/reserve_range_table.js`](../../ui/shared/components/reserve_range/reserve_range_table.js) - Shared Results summary-table and full-ladder markup.
- [`ui/shared/components/reserve_range/reserve_distribution_chart.js`](../../ui/shared/components/reserve_range/reserve_distribution_chart.js) - Shared Results distribution chart.
- [`ui/shared/components/reserve_range/reserve_fan_chart.js`](../../ui/shared/components/reserve_range/reserve_fan_chart.js) - Shared Results fan chart.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opens from Project Instance as a floating iframe method window at `/ui/method_pages/stochastic_consolidation/stochastic_consolidation.html`. A dataset row whose Method Type is `Stochastic Consolidation` opens it (on Results by default, per the Default Tabs preference), and `Add > Stochastic Consolidation` on a vector row whose Method Type is `None` opens a new one on Details with that row as its output. There is no shell tab type, as for Bootstrap: standalone method tabs are legacy.
- Tabs, in order: `Details`, `Segments`, `Correlation`, `Results`, `Notes`, `Audit Log`, owned by `ui/shared/tabs/window_tab_catalog.js`. The page reports tab changes with `arcrho:scon-tab-changed`, and Project Instance snapshots carry `kind: "stochastic_consolidation"` plus `sconTab`.
- Layout, shared with Bootstrap: no header above the tabs. The run-state chip sits beside the window title, drawn by Project Instance from the page's `arcrho:window-run-state` message (`Not run yet`, `Consolidating` while a run is in flight, `Up to date`, `Inputs changed — run again`, or `A segment changed`). The Consolidate, Save and Cancel buttons sit together at the right of the bottom save bar, as on the other method pages. A Consolidate shows a running card over the page (a Galton board piling balls into a bell curve, with the elapsed time) for at least two seconds, from `ui/shared/components/simulation_run/`. The page and every table scroll under the shared framed scrollbar (`ar-framed-scroll`, driven by `ui/shared/styles/framed_scroll_activity.js`). The value grids select like the other method grids through `ui/shared/components/spreadsheet/method_grid_selection.js`: click, drag, Shift and Ctrl selection, row and column labels, arrow keys, Escape, Ctrl+C and a right-click menu with Copy values and Remove Highlights; a copied cell gives its raw figure. Cell text is never selectable as text. The correlation matrices join the selection each time they are drawn; the Segments list keeps its own whole-row selection for Remove, Move Up and Move Down.
- Talks to the server through the `/stochastic-consolidation/*` routes (see [`stochastic_consolidation`](../app_server/domains/stochastic_consolidation.md)): load, consolidate, the segment picker's candidates, and save. **Consolidate** runs the settings on screen without writing; the result shows at once, the page stays dirty, and Save keeps it. **Save** consolidates again on the server whenever the stored run is stale, so a saved consolidation always holds the run of its saved inputs. The page never computes a derived value itself; it sends the loaded method back with only its owned settings changed, and the server rebases them through `apply_owned_patch`.
- Saves run behind the shared saving animation, show the post-save review warning and saved-dependents notice, and ask Project Instance to refresh its dataset table, as the other method pages do. Help > Open Dataset JSON File opens `methods/SCON@<Name>.json`.
- Open-window change alert: after a load or save the page watches its `SCON@` method file and output sidecar through the shared object-change watch.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- `stochastic_consolidation_page_model.js` owns every rule the page applies: which settings it edits and how they are read from and written back into the method (writing back what it read leaves the method unchanged; a segment keeps its consumed bootstrap revision only while it names the same bootstrap), the correlation matrix rules, the per-segment checks, the run-state chip, and the segment breakdown. The Results table, the percentile chooser and both charts come from the shared `ui/shared/components/reserve_range/` modules, which the Bootstrap page also uses.
- **Run state.** The page remembers the settings the run on screen was made from. The chip says `Inputs changed` whenever the settings that change a run (base type, seed, segments and factors, and every correlation setting) differ from those; name, output type and notes do not. `A segment changed` comes from the load's per-segment freshness report and clears after a Consolidate.
- **Details**: Name (read-only once saved), Output Type, Reserving Class, Base Triangle Type (a dropdown of the stored type and every type the segments' DFMs are built on), the Data Flow map, the inherited Origin and Development Lengths read-only, Simulations read-only (the count the segments agree on, or "Segments disagree"), and the seed with New Seed.
- **Segments**: one row per included bootstrap: index, reserving class (the last level, the full path in a tooltip), method (a dropdown of the bootstraps in that class), factor (editable), and the bootstrap's own simulations, mean reserve, standard deviation and CV. A Check column says `Ready` or every reason the row cannot be consolidated: not found, no saved run, a different simulation count from the first segment, a base type that differs from the consolidation's, or included twice; after a run it also notes a segment that changed since or was not in it. Add Segment lists every bootstrap in the project's other classes not already included, with its figures; Remove, Move Up and Move Down act on the clicked row, and the correlations travel with their segments.
- **Correlation**: the four options as a segmented control (Independent, Fully Correlated, Specified, As Generated), the dependency structure (Normal, Uniform, Gamma, Student's T) with Degrees Of Freedom beside it only for Student's T, and the matrix with a `Target / Used / Achieved` switch. Target shows the rank correlations; with Specified the cells above the diagonal are editable, the cell below mirrors each one, and a value outside -1..1 (or not a number) is refused with its reason under the matrix and the cell outlined. Used shows the linear correlations the run uses, `2·sin(π·ρ/6)` of each target: the stored adjusted matrix while the settings match the run, otherwise the conversion of the settings on screen with a note when the matrix is not positive definite and a run will repair it. Achieved, available once a run exists, shows the run's achieved rank and linear correlations side by side.
- **Results** reads only the stored summary. A consolidation combines scaled reserves only, so there is a `Reserves / Ultimates` switch but no `Scaled / Unscaled` one; the percentile chooser, Full Ladder, Copy Table, Download CSV, the summary table (without the DFM columns a bootstrap has), the distribution chart and the fan chart behave exactly as on the Bootstrap page. Below them the Segment Breakdown lists each segment's standalone mean, standard deviation and CV, its factor and its share of the total mean, with a total row and a caption giving the total's standard deviation against the sum of the standalone ones, which is the diversification the correlations give. A notice with Consolidate appears while the run is stale, and until a run exists the tab shows an empty state with Consolidate.
- Every select-like control opens one shared in-page menu styled to the app, with keyboard navigation.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change what a tab edits: update `stochastic_consolidation_page_model.js` and `tests/stochastic_consolidation_frontend.test.mjs`, and check that the field is one `apply_owned_patch` in `python-api/src/arcrho_api/stochastic_consolidation_contract.py` accepts.
2. Change a Results view: update the shared `reserve_range` modules and run both the Bootstrap and the Stochastic Consolidation Node tests.
3. Change routing: update the Project Instance dataset table, window, and message modules together.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- The segment checks mirror the server's; the server stays the authority and refuses a run the page let through, with the segment named.
- Saving a segment bootstrap does not refresh a consolidation that includes it; the page reports it on open instead.
- No dark-theme rules exist for the page yet, like Bootstrap.
<!-- MANUAL:END -->
