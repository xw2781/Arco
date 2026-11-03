# Project Dates Panel: Change All Project Dates at Once and Reshape the Project

Status: Planned 2026-11-03; all decisions taken the same day (origins follow their labels, developments follow absolute position, new cells start non-excluded, hand-entered datasets reshape and are listed, dates save first, a confirmation modal commits the change). 8 session-sized steps; step 1 done 2026-11-03 (inventory of date-shaped files, every method type has a reshape rule).
Last updated: 2026-11-03
Related: [generated_formula_dependency_refresh.md](generated_formula_dependency_refresh.md) (the scoped Engine refresh this reuses), [local_server_root_and_server_switcher.md](local_server_root_and_server_switcher.md) (the local root to deploy to first)

**How this ships.** New code in a server component (an Engine job and a Gateway route), plus a client panel. The Bridge, Engine and Gateway are rebuilt once, after step 7 is verified. Every user runs the latest app, so there is no old-client case to cover.

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A written list of every stored file that depends on the project dates, and how each one reshapes | [x] | 2026-11-03 | 60 min | 5 min | Nothing yet; the plan now lists every kind of saved data the dates shape and how each will follow a change. |
| 2 | A development method accepts a new set of columns and keeps its selections by position | [ ] | | 70 min | | |
| 3 | Every other method type reshapes the same way | [ ] | | 80 min | | |
| 4 | One background job saves the dates, rebuilds the datasets, reshapes the methods and refreshes what depends on them | [ ] | | 90 min | | |
| 5 | The app can start the job, report its progress, and preview what it will touch | [ ] | | 60 min | | |
| 6 | A floating panel changes all three dates together, behind a confirmation | [ ] | | 80 min | | |
| 7 | The dates on the main page are display only | [ ] | | 40 min | | |
| 8 | Tests, deploy to the local test server, then to production | [ ] | | 60 min | | |

Overall: 1 of 8 steps done. Estimated 540 min, actual so far 5 min.

## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one workflow subagent), one commit.
- Note the clock before the first file is read and again at the commit, keeping the two parts apart: time spent reading and editing, and time spent running tests, checks and deploys.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date, the actual minutes and the one-line user note, update the "Overall" count and actual total, append the actual to the step's `Estimate:` line, and update the `Status:` line at the top and this plan's row in the [plans index](README.md).
- If a step needs a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## What was found (2026-11-03)

Trigger: the import of Oct data into `NJ_Annual_Prod_2026 Oct`, a copy of the Sep project whose development end was moved to Oct 2026, ended with "The refresh reported problems", 23 of them.

- **The date change does nothing by itself.** Saving a date writes three values to the project's general settings file and one audit line, and stops (`update_general_settings` in `frontend/app_server/services/project_settings_service.py`). No dataset, method or dependent is touched.
- **The datasets caught up by accident.** The import's refresh regenerated the engine datasets at the new date. In the MA BI Total class the quarterly triangles went from 39 to 40 development columns (ages 2, 5, … 116 became 1, 4, … 118) because the September quarter now has data.
- **The methods did not.** Every quarterly Development Factor method kept its 39 saved columns. The method rule (`_apply_input_snapshot` in `python-api/src/arcrho_api/dfm_contract.py`) accepts a valuation shift only when the column count is unchanged, so it refused with "DFM input development-label geometry changed" and left the old method in place. Everything built on those methods (Cape Cod, BF, the Current Qtr results) was skipped.
- **Annual methods pass**, because their column count did not change. Only the log for one class was read in full; the rest are assumed to match until step 1 lists them.
- **Each date is editable alone.** The three month inputs on the main page each save as soon as they change (`bindEditor` in `project_settings_general_settings.js`). Starting a new year means changing the origin dates and the development end separately, with nothing reshaped in between.

### Inventory of date-shaped files (step 1, 2026-11-03)

Counted in `NJ_Annual_Prod_202605_Fake` (31 classes) from each class `index.json`, sidecar and method JSON. "Origin by label" and "development by position" are decision 3; "listed" is decision 1.

**Datasets**

| Kind | Fake count | Stores | Reshape |
| :--- | :--- | :--- | :--- |
| Engine triangles and vectors (`source_kind` engine) | 1,174 + 133 | No labels; CSV views per period (`@12@12@cum@dev.csv`), `processing.config_hash`, stored at source granularity | Regenerate from the source table. The Engine reads the dates from `general_settings.json` (`data_processing.py` project settings, mtime-cached), so saving the dates first is enough. |
| Calculated (formula) datasets | 85 | 75 carry index labels `1..N` | Recomputed by the dependent walk from their precedents; no reshape. |
| Method outputs (dfm, result_selection, bornhuetter_ferguson, cape_cod, berquist_sherman_sr/cra, bootstrap, stochastic_consolidation) | 361, 120, 67, 17, 14, 6, 2 | Origin labels copied from the method | Republished by the method's own recalculation after it is reshaped; no separate rule. |
| Hand-entered and imported (`source_kind` input) | 214: 208 vectors, 6 triangles | 204 vectors store index labels `1..N` (ResQ `resq_vector`), not dates; 8 of the vectors are ResQ Bootstrap outputs; triangles store `Jan 2017` / `2017` / `2017 Q1` origins and `1m`/`5m`/`12m` ages | Rows follow their true origin, columns by position, new cells empty; every one listed. Because most store index labels, the true origin of row *i* is the **old** Origin Start plus *i* stored periods, so the job must keep the previous dates (in its status, before saving) to reshape and to resume. Write the CSV at the stored length and delete its coarser `@n` sibling views ([stale sibling views](../../agent-memory/calculated-walk-reads-stale-sibling-views.md)). |
| Cell links on input datasets (`formula_links`, `external_links`, `internal_links`) | 7 datasets (6 formula, 1 Excel) | Target cells by row and column index; formula ranges as position text (`[1:40]`) | Target rows shift with their origin and a target whose origin drops is removed; range text is not rewritten; the dataset is listed with the reason "has cell links". |
| Project header and settings caches (`data/ArcRhoHeaders@*.csv`, `ArcRhoProjectSettings.csv`) | 11 | Labels for the whole project | Already dropped when older than `general_settings.json` (`_drop_project_csv_cache_older_than_settings` in `arcrho_runtime_service.py`); nothing to add. |

**Methods** (owned = the person's choices, kept; derived = recomputed from the new snapshots)

| Type | Fake count | Owned fields that carry geometry | Rule |
| :--- | :--- | :--- | :--- |
| Development Factor (`dfm_contract`) | 361: 291 annual, 70 quarterly | `ratios_tab.ratio_triangle.excluded` (origin x ratio column), `average_formulas.selected/inputs/values` of User Entry rows (per ratio column), `curves_tab.included/selected_estimates/user_columns[].values` (per period), `cell_notes` keyed by origin label and column label | Origins by `data_tab.origin_labels`; every per-column list copies by index from the first column, new columns non-excluded and unselected; cell-note columns renamed by position (what `_development_axis_shift` already does for an equal count). Data, ratios, basis, ultimate are derived. Keep the refusal only when the new labels are not ages on the same spacing (a different development length or a different triangle), which is not a date change. |
| Bornhuetter Ferguson | 67: 44 annual, 23 quarterly | `prior_datasets[].weights` per origin | Already remapped by origin label in the refresh (`bornhuetter_ferguson_contract.py` around line 543); rest derived. Needs only the new snapshots. |
| Cape Cod | 17 annual | `trend_factor_overrides` per origin | Already remapped by origin label (`cape_cod_contract.py` around line 755); rest derived. |
| Result Selection | 120: 82 annual, 38 quarterly | `loaded_datasets[].weights` and `ultimate_overrides` per origin | **Not label-aware today**: the refresh fits them by position and refuses when a source's row count differs from the stored `origin_labels` (`result_selection_service.py` around line 806). Reshape by `method_tab.origin_labels`, new origins weight 0 and no override. |
| Berquist-Sherman SR and CRA | 8 + 6, annual only (`BS_ANNUAL_PERIOD_LENGTH`) | SR: `selected_proportion_settled`, `selected_proportion_is_default` per column, `selected_adjustment` origin x column. CRA: `inflation_selection`, `user_inflation(_inputs)`, `average_case_reserve_selection`, `user_average_case_reserves(_inputs)` per column | Rows by `method_tab.origin_labels`, columns by position, new cells default; output triangle recalculated. |
| Bootstrap | 6 annual | `residuals_tab.user_scale_values_residuals/forecasting` per period; `results_tab.target_scaling_methods/target_cvs` per origin | Periods by position; per-origin lists by `results_tab.origin_labels` (fit by position today). `dfm_snapshot` and the simulation are derived and rerun. |
| Stochastic Consolidation | 2 annual | None: segments, factors and correlations only | No reshape; its results are rerun by the walk. |

**Other readers of the dates** read them live and store nothing, so they need no reshape: dataset creation and the roll-up anchor (`_general_settings_month_bounds` and `valuation_months` in `dataset_service.py`), the Excel formula choices' latest project (`excel_formula_choices_service.py`), the header load check (`arcrho_runtime_service.py`), the notes macro's valuation stamp (`link_notes_to_method_values.py`), and the main page's origin span note.

**What the counts change.** In the Fake project a development end that crosses a quarter boundary makes the 70 quarterly DFMs refuse, and everything built on them is skipped. Crossing into January does the same to the 291 annual DFMs, because their column count grows too. Moving the origin range changes the row count, which today also makes all 120 Result Selection methods refuse.

## Desired behaviour

- **One panel for all dates.** A floating panel holds Origin Start, Origin End and Development End. The user edits any or all of them and presses Apply.
- **A confirmation modal commits the change.** It says the change reshapes the whole project and starts a large refresh, and shows what will be touched (classes, datasets, methods). Nothing is saved until the user confirms.
- **One job does the work.** It saves the dates, regenerates every engine dataset at the new shape, reshapes every method, and refreshes the dependents. A progress window shows it, like Import Data and the rules save.
- **Origins follow their labels; developments keep their position.** Data and selections stay with their true origin label when the origin range moves, as it does for a January project. Along each row, a method's ratio selection pattern applies from the first development cell, ignoring columns added or dropped. Diagonals and origins that did not exist before start non-excluded.
- **Hand-entered and imported datasets reshape the same way** and are listed in the job result for review.
- **The main page only displays the dates.** They stay visible and cannot be edited there. The only way to change them is the panel.
- **Clicking anywhere on the dates band opens the panel.** The whole band (`summaryPeriodsBand`), not just a date or a button, is the target. It gets a pointer cursor, a hover state and keyboard access.
- **An import with the new data then finds the shapes already matching**, so the error that started this does not appear.

## Plan

### Step 1: Inventory what depends on the dates
Estimate: 60 min

Read-only. List every file kind that stores period geometry and say how each reshapes.
- Engine datasets (sidecar and CSV views): rebuilt from the source table.
- Manual and imported datasets: cannot be rebuilt from the source. Count them; they reshape by decision 3 and are listed for review (decision 1).
- Methods: Development Factor, Bornhuetter Ferguson, Cape Cod, Result Selection, Berquist-Sherman, Bootstrap, Stochastic Consolidation. For each, which fields carry labels, counts or selections.
- Anything else that reads the dates: the dataset service, the Excel formula choices, the origin span note on the main page.

Done when the table sits in this plan under "What was found", and each method type has a named reshape rule or a new entry under "Open decisions".

Actual: code edit 4 min, test/validation 1 min, total 5 min; well under because the class index files gave every count in one read-only pass.

### Step 2: Development method reshape
Estimate: 70 min

Replace the refusal in `_apply_input_snapshot` with a reshape. The new triangle's origin and development labels replace the saved ones. Rows match by origin label (decision 3): a kept origin carries its row, a dropped origin's row goes, a new origin's row starts empty and non-excluded. Within each row, ratio selections and exclusions copy by absolute development index from the first cell, and new cells are non-excluded. Selected factors, tails and averages follow the development position rule, so no hand-picked value moves to a different column silently. Keep the refusal for a change that is not a date change, if step 1 finds one.

Follow the persisted JSON rules: write through `persisted_json_text`, and keep revisions on the canonical projection. Use `$arcrho-json-contract`.

Done when a 39-column method becomes a 40-column method with its pattern in place, a 40-column method shrinks back, a January change (earliest origin dropped, new origin added) keeps each surviving origin's values and pattern on its own label, and tests cover all three with exact payloads.

### Step 3: Other method types
Estimate: 80 min

Apply step 1's rules to each remaining method type and to hand-entered and imported datasets, reusing the one reshape helper from step 2 (origin by label, development by position) rather than a copy per type (Single Source of Truth). Methods that cannot be reshaped safely, and every reshaped hand-entered or imported dataset, are listed in the job result for review, not skipped silently.

Done when each type has a reshape test, and the BF "stored ultimate matches its source snapshots" check still passes after a reshape.

### Step 4: The project dates job
Estimate: 90 min

Clone the pattern in [adding-a-project-level-engine-job](../../agent-memory/adding-a-project-level-engine-job.md): a job contract in `python-api/src`, an Engine worker beside `data_processing_rules_jobs.py`, registered in the Engine's dispatcher and both `build_exe.py` hidden-import lists.

The job runs under the project-scope lease, in this order: check the date rules (decision 4), save the dates, regenerate engine datasets for every class, reshape hand-entered and imported datasets and methods per class (step 2 and 3 rules), then one dependent walk per class using the source refresh job's per-class step. Failures leave the job reporting what was done, as the rules save does, and running the same change again resumes it (decision 2). The status carries progress ticks and the per-class results.

Done when the job runs against a copy of the Fake project on the local test root and leaves every quarterly method at the new shape.

### Step 5: Start, progress and preview in the app server
Estimate: 60 min

Add the job service in `frontend/app_server`, with a submit, a status read and a preview that returns the counts the modal shows without changing anything, including the origins that will be dropped and the hand-entered datasets that will be reshaped. Register them as workspace mutation and read kinds so a Client PC reaches them over the Gateway, with the preflight that refuses while a propagation hold is active. Add a route in the project settings router. No SMB fallback.

Done when each route is covered by a transport-selection test and the preview matches what the job then touches.

### Step 6: The floating panel and confirmation modal
Estimate: 80 min

Add a floating panel to Project Settings with the three month pickers, reusing the existing month picker. Apply opens the confirmation modal; confirming submits the job and opens the progress window through the existing shell progress messages. Validate before the modal (decision 4: origin start ≤ origin end ≤ development end). The modal names how many origins drop out when there are any. Follow `$arcrho-ui-design`: dense and quiet, no secondary labels, modal copy of two lines at most, screenshot in both themes. Bump the `?v=` pin and any test that pins it.

Done when a start-of-year change (origin and development end together) runs end to end on the local test root.

### Step 7: Main page display only
Estimate: 40 min

Keep the three dates visible on the main page and make them read-only. Remove the per-input save path (`bindEditor`, its keyboard stepping and the immediate save) and the direct date save route's use from the UI, as obsolete code. Make the whole `summaryPeriodsBand` the one way to open the panel: a click anywhere on it opens the panel, it is reachable by keyboard (Enter and Space), and it shows a pointer cursor and a hover state. The calendar buttons beside each date go, since the band replaces them. The band does nothing while no project is selected or the project is locked.

Done when no control on the main page can change a date, a click on any part of the band opens the panel, and the Import Settings window still reads the dates.

### Step 8: Tests, deploy, notes
Estimate: 60 min

- Run the new tests and the suites around them; baseline failures before blaming the change.
- Deploy to the local test root, run the whole flow with `launch-app`, then run `server-components/deploy.py` for the Bridge, Engine and Gateway, checking the payload first.
- Add the memory notes and release fragment, and move this plan to `completed/` when done.

## Decisions (2026-11-03)

None open. A new question found during a step goes under a fresh "Open decisions" heading, per the working rules above.

1. **Manual and imported datasets: reshape and list.** A dataset entered by hand or imported from ResQ is reshaped with the same position rules as a method (decision 3), and every one of them is listed in the job result for review. Step 1 counts them.
2. **Order and failure: dates first.** The job saves the dates first. A failed rebuild leaves the project half moved, and running the same change again resumes it.
3. **Origins follow their labels; developments follow position.** When the origin range moves (a January project drops the earliest origin year and adds the new one), data and selections stay with their true origin label, so a row for 2019 keeps 2019's values and pattern wherever that row now sits. Origins that drop out lose their data and selections; new origins start empty and non-excluded. Within a row, the development axis keeps the absolute-position rule: the pattern applies from the first development cell, and new diagonals start non-excluded. The preview and modal count the origins that will be dropped.
4. **Date rules: start ≤ end ≤ development end.** Origin start must not be after origin end, and origin end must not be after development end. All three are months, so no month-end check is needed. The panel checks before the modal, and the job checks again before saving.
5. **Who may change them: the existing project lock.** The band is inert while the project is locked, and the job runs under the project-scope lease. No separate permission check.
6. **Import Data: read only.** An import never sets the dates; it reads what the panel saved.
7. **Duplicating a project: not in this plan.** The duplicate flow stays as it is; the user opens the panel after duplicating. A later plan may offer it straight away.
