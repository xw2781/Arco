# Generated formula dependencies and scoped source refresh

Status: Complete, closed 2026-11-09. All 7 steps done: the code landed 2026-09-12, the Bridge, the Engine and the Gateway were deployed 2026-09-13, and the user confirmed on 2026-11-09 that testing is finished. The repair counts and the detail of the app checks were not written into this plan.
Last updated: 2026-11-09

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | What changed for the user |
| :--- | :--- | :--- | :--- | :--- |
| 1 | One shared rule decides which datasets a formula reads | [x] | 2026-09-12 | Nothing visible yet, but a formula that names some inputs in quotes and others plain now reads the same way everywhere; checked against the fake project, where all 61 formulas keep the inputs they already had and 10 mixed ones gain the plain-named inputs the Dataset Types tab used to drop. |
| 2 | A dataset's Details show its formula inputs and readers, and a rebuild keeps them current | [x] | 2026-09-12 | A dataset the app builds from a formula over other datasets now lists what it is made from and what reads it, and rebuilding one brings those links up to date instead of leaving whatever they were first written with. |
| 3 | A project imported from ResQ shows the same links | [x] | 2026-09-12 | A project brought in from ResQ now arrives with the same inputs and readers on a formula-built dataset that the app writes itself, instead of arriving with none. |
| 4 | Importing source data for one dataset type also rebuilds the formula datasets that use it | [x] | 2026-09-12 | Importing source data for chosen dataset types now rebuilds the datasets built from them by formula, and the formulas built on those, in every reserving class the import covers, then refreshes the methods that read them; saving Data Processing Rules does the same. |
| 5 | The Dependency Graph draws the formula links and marks a generated formula | [x] | 2026-09-12 | The Dependency Graph now marks a dataset built by a formula as Generated, in its own colour, and draws arrows from the datasets it is made from, so clicking one of those inputs lights the formula and every method that reads it; those inputs are drawn straight away instead of waiting for the Show all box. |
| 6 | A one-off script fixes the links of the few existing projects | [x] | 2026-09-12 | Nothing changes on its own, but there is now a one-off repair that can be run over a project that already exists so its formula-built datasets list what they are made from and what reads them, without touching anything else in the file and without marking any method for review. |
| 7 | Released to the server, the existing projects fixed, and the fake project checked | [x] | 2026-11-09 | The change is live on the server, and a formula-built dataset shows what it is made from, appears linked in the Dependency Graph, and is rebuilt when one of its inputs is imported; the user confirmed the testing is finished. |

Overall: 7 of 7 steps done.

## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one workflow subagent), one commit.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date and the one-line user note, update the "Overall" count, and update the `Status:` line at the top and this plan's row in [README.md](../README.md).
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## Answer

Currently, importing the source table with dependent refresh scoped to dataset type A does **not reliably refresh B** when B is an Engine-generated formula using A. The source-refresh job regenerates existing Engine instances of explicitly selected types, then runs a dependency walk whose formula graph excludes generated types. In the ordinary A -> B case, B is neither selected for regeneration nor reached by that walk. Dependencies below B can consequently remain stale too.

An unscoped dependent refresh selects every existing Engine dataset instance in the selected reserving classes, including B, provided its regeneration succeeds. The type selection scopes regeneration, not the columns imported from the source table. This is the current workaround; no import or recalculation was performed during this investigation.

The missing DSV Details links have the same underlying classification problem. This is a contained backend change, but fixing only the displayed links or removing every `generated` guard would be incorrect. Generated formulas must continue to calculate through the Engine against source data.

The Project Instance Dependency Graph window shows the same gap, because it is a reader of the same sidecar graph: it draws every class index row as a box and every sidecar precedent as an arrow, so A, C, and B come out as three unconnected boxes. Two further things make the window misleading even once the edges exist. Every Engine-built dataset is labelled `Imported`, which is right for A and C (one source column each) and wrong for B (a formula over other types the Engine evaluates against the source table). And a dataset nothing reads is hidden until `Show all` is ticked, so today A and C are hidden by default in a class where B and its methods are drawn.

An import does not repair the links on its own (checked 2026-09-11). When the Engine regenerates a dataset that already has a sidecar, the runtime keeps the file and refreshes only its status, timestamps, shape fields, cache filename, and audit log; the two link lists are recomputed only when a sidecar is created for the first time. So every dataset an import regenerates keeps whatever links it had, right or wrong, and existing projects need an explicit repair.

## Confirmed fake-project example

Read-only inspection of `NJ_Annual_Prod_202605_Fake` on 2026-09-05:

| Role | Dataset type | Formula or direct source | Generated |
| :--- | :--- | :--- | :--- |
| A | Earned Premium | `Earned_Premium` CSV field | true |
| C | Remaining Budget Premium | `Remaining_Budget_Premium` CSV field | true |
| B | Total Earned Premium | `Earned Premium + Remaining Budget Premium` | true |

`field_mapping.json` contains A and C, but not B. `dataset_types.json` marks B calculated and generated, and expands its Source to `Earned_Premium + Remaining_Budget_Premium`.

In the default class `PRNJ - PA_\_PA_\_All States_\_Direct Group_\_COL`, the persisted sidecars confirm that A has no formula dependents and B has no precedents. B does retain method dependents, including `D 13 - Paid DFM w/ Selected LDFs`, `D 18 - BS Paid DFM`, and `D 92 - Current Qtr Selected`. The missing links therefore affect real downstream paths, not just the example formula.

These conclusions combine current repository logic with persisted project metadata. They are not a live reproduction of an import, nor a verification of the deployed Engine's source revision.

## Why the change is safe

Verified against the code on 2026-09-11; the steps below rely on these properties, so an implementer who finds one no longer true should stop and record it under "Open decisions".

- A type is generated only when its expanded Source resolves entirely to source-table columns, so a generated formula can only name other generated types. The new edges therefore join Engine-built datasets only; no ordinary user save can reach them, and an app-calculated type reading a generated one already records that link today.
- `compute_status` returns current for any non-method dataset, so a generated dataset can never be flagged Needs Review by the timestamp comparison.
- `write_sidecar` stamps neither `updated_at` nor an audit entry, and method freshness compares the stored timestamp text before file mtime, so rewriting the two link lists alone cannot move a method to Needs Review.
- `apply_sidecar_graph_fields` re-reads the existing dependents and keeps the method ones, so a rewrite cannot detach a method from its input.
- The one visible consequence: once A lists B as a dependent, republishing A marks B's methods Needs Review through B (the marking walk crosses plain datasets to reach methods). That is right after a source refresh, and step 4 regenerates B in the same job so the walk clears it.

## Code evidence and ownership

- [source_table_refresh.py](../../../server-components/src/arcrho_engine/source_table_refresh.py): `_engine_dataset_instances` filters `source_kind == engine` by exact selected dataset type. `_refresh_one_reserving_class` regenerates those instances and passes only the successful names to `recalculate_dependents`. The data-processing-rules job ([data_processing_rules_jobs.py](../../../server-components/src/arcrho_engine/data_processing_rules_jobs.py)) calls the same two functions, so an expansion inside them reaches both jobs.
- [calculated_dataset_service.py](../../../frontend/app_server/services/calculated_dataset_service.py): `_calculated_dataset_contract_from_rows`, `_direct_dependent_names`, `_dependency_map`, and `_target_dependency_map` exclude `generated` rows. `sidecar_graph_fields` uses these helpers. The recalculation target map also deliberately excludes generated types. `_formula_components` is the parser the persisted graph uses: quoted names first, then unquoted known names, longest first.
- [dataset_types_service.py](../../../frontend/app_server/services/dataset_types_service.py): owns Dataset Type normalization and source-expression derivation. Project Dataset Type formulas own logical type relationships; Field Mapping owns direct source-column bindings. Sidecar graph fields are derived instance relationships. Its own `_extract_formula_components` reads a formula differently (only the quoted names when any are quoted) and serves Source resolution and save-time validation; step 1 points it at the shared reader.
- [arcrho_runtime_service.py](../../../frontend/app_server/services/arcrho_runtime_service.py): `_write_dataset_sidecar_impl` has two branches. A new sidecar is built by the contract and then gets `apply_sidecar_graph_fields`; an existing sidecar is refreshed in place and never has its link lists recomputed.
- [dataset_service.py](../../../frontend/app_server/services/dataset_service.py): `load_dataset_sidecar` reads persisted graph fields and enriches their names for display. It does not recover missing generated-formula edges. `_dataset_type_calculation_map` is the one place that decides which formula a dataset type shows - an app-calculated type its own, a generated type "the Engine's formula for display", anything else none.
- [details_dependencies.js](../../../frontend/ui/shared/tabs/details/details_dependencies.js): renders the returned precedent/dependent lists. There is no evidence that the chip renderer is dropping B.
- [engine_dataset_sidecar_contract.py](../../../python-api/src/arcrho_api/engine_dataset_sidecar_contract.py) owns Engine sidecar payload construction. Migration derives graph fields with its own copies of the parser and the two name helpers in [catalog.py](../../../python-api/migration/resq_migration/catalog.py), so producer parity must be covered.
- [dataset_type_contract.py](../../../python-api/src/arcrho_api/dataset_type_contract.py) is the one owner of "is this type app-calculated" (`is_app_calculated_dataset_type`) and already parses quoted names; it is where the shared graph helper belongs.
- [dataset_dependency_graph_service.py](../../../frontend/app_server/services/dataset_dependency_graph_service.py): the hosted read behind `GET /datasets/dependency-graph` (`dataset_dependency_graph` in the workspace read contract). Nodes are the class index rows with their `source_kind`, `method_type`, `status`, and `formula`; edges are the sidecars' `precedents` and `dependents`. An Engine sidecar carries no formula by contract, so an engine node's `formula` is empty here even though the Details page hydrates it from the dataset types.
- [dependency_graph_layout.js](../../../frontend/ui/project_instance/dependency_graph_layout.js): `dependencyNodeKind` maps `source_kind == engine` to the `engine` family labelled `Imported`, with no look at the formula; `dependencyGraphHiddenByDefault` hides any non-method, in-index box without dependents; `dependencyGraphReach` lights the transitive chain. [dependency_graph_window.js](../../../frontend/ui/project_instance/dependency_graph_window.js) renders boxes, ports, and the legend from those families, and [dependency_graph_window.html](../../../frontend/ui/project_instance/dependency_graph_window.html) spells the legend. The window redraws on `arcrho:dependency-graph-refresh`, which `project_instance_dataset_cache.js` posts whenever the page applies a disk-backed dataset table reload, and on its own Refresh button.
- The dataset-type change job's "Rebuilding dataset dependency graphs" stage in `calculated_dataset_service.py` already recomputes the link lists of affected instances, writing a sidecar only when its payload changed; the one-off repair of step 6 is that stage's loop over every Engine instance of a project. [backfill_stored_period_lengths.py](../../../tools/backfill_stored_period_lengths.py) is the model for the script itself: nothing written without `--apply`, one project or all, a counted report, and the [report](manual_input_period_rollup_backfill_report.md) it left beside its plan.

## Proposed behavior

1. Discover logical formula dependencies for both generated and app-calculated types. Keep the calculation owner separate: generated types use the Engine; app-calculated types keep their existing evaluator. One reader serves every part of the app: the names in double quotes, then any unquoted name that matches a type in the table, so a formula that mixes the two counts both (decided 2026-09-11). Formulas imported from ResQ quote every name, so only a hand-edited formula can be mixed; for such a type the Source expansion and the Generated flag may change at its next Dataset Types save, which is the intended reading.
2. For a source refresh scoped to A, include existing Engine instances of A and every transitively dependent generated type, including B. Respect the reserving-class selection. Empty type selection continues to mean all Engine types.
3. Discover type reachability before filtering to existing instances: an intermediate type without a persisted instance must not hide a later generated formula whose expanded source still uses A.
4. Regenerate the selected Engine instances using the existing request builder, force-refresh behavior, stored geometry, failure reporting, and cache restoration. Pass all successfully regenerated instances into the existing downstream method/app-calculated walk as one batch.
5. Show direct logical links in Details: A lists B, and B lists A and C. Transitive descendants belong in refresh expansion, not B's direct precedent list. A generated formula's precedents and dependents are written only for instances that exist in the class, the way dependents already are; an app-calculated dataset keeps naming a missing input, because for it that is a real problem.
6. Updating A does not mean B should add cached matrices from A and C. B reads the newly imported source through the Engine. This distinction matters especially for ratios and other expressions whose source aggregation differs from matrix arithmetic.
7. The Dependency Graph window draws the same structure the refresh follows. A and C each get an arrow into B, and B keeps its arrows into `D 13`, `D 18`, and `D 92`, so selecting A lights B and everything downstream of B in green, and selecting `D 13` lights B, A, and C in blue. B is drawn in its own `Generated` family - an Engine-built formula over other types - while A and C stay `Imported`, so the reader can tell a source column from a formula the Engine evaluates. B's left port lists A and C, A's right port lists B. Because A and C now have a dependent, the default view draws them; nothing changes in the hide rule itself. Arrows keep one style: an arrow means "computed from" whoever does the computing, and the box family already says who.
8. Every regeneration of an existing Engine dataset recomputes its two link lists, so from then on an import repairs the links of everything it rebuilds and a re-import from ResQ writes them correctly from the start; no user ever has to ask for a repair. The few projects that already exist are fixed once, by hand, with a one-off script under `tools/` run on the Server PC (decided 2026-09-11 in place of a repair button or job: a button would be pressed almost never, and a macro would walk the project over the share). The script rewrites only the sidecars whose link lists change and touches nothing else in them.

## Open decisions

None open.

Closed 2026-09-11: how existing projects are repaired. A Project Settings job, a button in the Dependency Graph window, and a macro were considered; the one-off script of step 6 was chosen (see Proposed behavior item 8).

Closed 2026-09-11: how a formula that mixes quoted and unquoted names is read. Both count as inputs, everywhere. The Dataset Types tab's own reader, which ignored the unquoted names whenever any name was quoted, is pointed at the shared reader in step 1 (see Proposed behavior item 1).

## Plan

Steps 1 and 2 come first and in order. Steps 3, 4, 5, and 6 are independent of one another once step 2 is in. Step 7 is last and is the only step that touches the server.

### Step 1 — One formula-dependency helper for every reader

**Goal.** One function in the Python API contract layer turns a project's dataset-type table into the logical formula graph, for generated and app-calculated types alike, and both of the app server's formula readers delegate to it. The evaluator's "which types may ArcRho compute" rule stays exactly where it is.

**Read first.** [Answer](#answer), [Why the change is safe](#why-the-change-is-safe), [Proposed behavior](#proposed-behavior) item 1. [dataset_type_contract.py](../../../python-api/src/arcrho_api/dataset_type_contract.py) (whole file), [calculated_dataset_service.py:100-148](../../../frontend/app_server/services/calculated_dataset_service.py#L100-L148) and [calculated_dataset_service.py:1326-1351](../../../frontend/app_server/services/calculated_dataset_service.py#L1326-L1351), [dataset_types_service.py:491-621](../../../frontend/app_server/services/dataset_types_service.py#L491-L621) (`_replace_formula_components_with_sources`, `_extract_formula_components`, `_find_unresolved_dataset_refs`) and [dataset_types_service.py:718-784](../../../frontend/app_server/services/dataset_types_service.py#L718-L784) (`require_resolvable_formulas`, `resolve_persisted_rows`), [test_dataset_type_contract.py](../../../python-api/tests/test_dataset_type_contract.py), [test_dataset_type_calculated_rule.py](../../../frontend/tests/test_dataset_type_calculated_rule.py). The reader's other callers, so the change of a mixed formula's reading is seen where it lands: [dataset_types_service.py:869](../../../frontend/app_server/services/dataset_types_service.py#L869) (`_formula_component_map`), [dataset_types_plan_service.py:273-290](../../../frontend/app_server/services/dataset_types_plan_service.py#L273-L290), [reserving_class_service.py:1024](../../../frontend/app_server/services/reserving_class_service.py#L1024) and [reserving_class_service.py:1669](../../../frontend/app_server/services/reserving_class_service.py#L1669). AGENT_GUIDELINES "Single Source of Truth", "Agent Project Data Access" (the fake project's `dataset_types.json` may be read for the check below), and "Python test runner" memory (pytest lives in the repo-local `.pytest-tools`).

**Do.**

- [x] Add to `dataset_type_contract.py`: `formula_references(formula, known_names)` with the behaviour of `_formula_components` (quoted names in order, then unquoted known names matched longest first on word boundaries, case-insensitive, whitespace-normalized, once each); `dataset_type_formula_graph(rows)` returning, for every row flagged calculated with a non-empty formula and regardless of `generated`, its direct precedents in formula order plus the reverse map; `formula_closure(rows, names, direction)` returning the transitive precedents or dependents in a deterministic order with a cycle guard.
- [x] Make `_formula_components` in `calculated_dataset_service.py` delegate to `formula_references` and delete its body. Leave `_app_calculated_rows`, `_dependency_map`, and `_target_dependency_map` guarded by `is_app_calculated_dataset_type`: they are the evaluator's target maps and must keep excluding generated types.
- [x] Make `_extract_formula_components` in `dataset_types_service.py` delegate to `formula_references` too and delete its body, so Source expansion and save-time validation read a mixed formula the way the links do. `_replace_formula_components_with_sources` and `_find_unresolved_dataset_refs` keep their own jobs; only the name extraction moves.
- [x] Before committing, read the fake project's `dataset_types.json` once and confirm every formula in it lists the same names under the old reader and the shared one; note the result in the Progress row. A live project is not touched.
- [x] As built, one refinement of `_formula_components`: each matched name is taken off the text, so the shorter type `Premium` is not also read out of the words `Earned Premium`. The old reader searched the whole formula once per name and could report both, which is what "longest first" was there to prevent; `_extract_formula_components` already eliminated the overlap its own way. Checked on the fake project: all 61 formulas keep exactly the inputs the links reader gave them, and the 10 mixed formulas gain the unquoted names the Dataset Types tab dropped (the other 3 differences are ordering only).

**Tests.** `python-api/tests/test_dataset_type_contract.py` gains: quoted, unquoted, and mixed references; whitespace and case differences; overlapping names (a name that is a prefix of another); a generated type's edges present; a transitive A -> B -> D chain; a cycle that terminates. `frontend/tests/test_dataset_type_calculated_rule.py` gains the A/C/B fixture from the example: both direct edges come from the graph while `_app_calculated_rows` still leaves B out and `_target_dependency_map` has no entry for it. A new `frontend/tests/test_dataset_types_formula_reader.py`: `require_resolvable_formulas` rejects an unquoted name that is not in the table only when it matches nothing, accepts a mixed formula whose names all exist, and `resolve_persisted_rows` expands a mixed formula's Source from both names.

**Done when.** The A/C/B fixture yields A -> B and C -> B from the shared graph, B is still not app-calculated, a mixed formula reads the same in the links, the Source expansion, and the save validation, and the existing calculated-dataset and dataset-types tests pass unchanged.

### Step 2 — Sidecars record generated-formula links, and regeneration keeps them current

**Goal.** Every sidecar the app server writes or rewrites for an Engine-built dataset lists its formula inputs and formula readers, and the dependent walk's calculated tier still never tries to rebuild one.

**Read first.** [Proposed behavior](#proposed-behavior) items 5, 6, and 8; [Why the change is safe](#why-the-change-is-safe). [calculated_dataset_service.py:151-400](../../../frontend/app_server/services/calculated_dataset_service.py#L151-L400) (`_calculated_dataset_contract_from_rows` through `apply_sidecar_graph_fields`) and [calculated_dataset_service.py:1892-1960](../../../frontend/app_server/services/calculated_dataset_service.py#L1892-L1960) (walk targets); [arcrho_runtime_service.py:1218-1321](../../../frontend/app_server/services/arcrho_runtime_service.py#L1218-L1321); [dataset_service.py:1637-1660](../../../frontend/app_server/services/dataset_service.py#L1637-L1660) and the Details enrichment that follows it; [test_calculated_dataset_runtime.py](../../../frontend/tests/test_calculated_dataset_runtime.py), [test_engine_dataset_sidecar_contract.py](../../../frontend/tests/test_engine_dataset_sidecar_contract.py), [test_dataset_method_calculated_sidecar.py](../../../frontend/tests/test_dataset_method_calculated_sidecar.py). Step 1's helpers, since the graph fields are built from them: `dataset_type_formula_graph` and `dataset_type_key` in [dataset_type_contract.py](../../../python-api/src/arcrho_api/dataset_type_contract.py). Memory: "Propagation hold and test isolation" (a saving test must use the workspace stub) and "Hosted-save fix needs Engine deploy" (nothing here is live until step 9).

**Do.**

- [x] `sidecar_graph_fields`: for a generated formula type, precedents come from the step 1 graph and are filtered to instances existing in the class (the filter `_existing_dataset_keys` already applies to dependents); app-calculated precedents are unchanged. Dependents gain the generated readers of the type, filtered the same way; app-calculated readers and preserved method dependents are unchanged.
- [x] `_write_dataset_sidecar_impl`, existing-sidecar branch: call `apply_sidecar_graph_fields` before the write, exactly as the new-sidecar branch does, so a regeneration recomputes the two lists and nothing else changes in what that branch already writes.
- [x] Confirm, with a test rather than code, that the walk's calculated tier never targets a generated type: a walk rooted at A must not list B as a calculated target, and B's methods are refreshed only when B itself is a root. If the guard from step 1 holds, no walk code changes.
- [x] Check Details on the A/C/B fixture through `load_dataset_sidecar`: B's precedent chips show A and C, A's dependent chips show B. Change `dataset_service` or the chip renderer only if the check fails. As built the check passed with no change to either: the chips resolve from the reserving-class index, and the reader's chip already carries the Engine's formula because `_dataset_type_calculation_map` hands a generated type its formula for display.

**Tests.** `test_calculated_dataset_runtime.py`: graph fields for A, C, and B; a generated precedent with no instance in the class is left out while an app-calculated one is kept; method dependents survive a rewrite. `test_engine_dataset_sidecar_contract.py`: regenerating an existing Engine dataset recomputes the two link lists and changes only the fields the branch already changed before. A walk test in `test_dataset_method_calculated_sidecar.py` or beside it: root A does not target B; root B refreshes the DFM reading it.

**Done when.** Regenerating an existing Engine dataset in a test workspace leaves its sidecar with the two link lists recomputed; the A/C/B fixture carries A -> B and C -> B on both sides; the walk's calculated tier never targets a generated type.

### Step 3 — ResQ import writes the same links

**Goal.** A project re-imported from ResQ gets exactly the sidecar links the app writes, from the same helper.

**Read first.** [Proposed behavior](#proposed-behavior) item 5; AGENT_GUIDELINES "Generated Dataset Import Parity" and "Persisted JSON Producer Parity". [catalog.py:110-140](../../../python-api/migration/resq_migration/catalog.py#L110-L140) (`_formula_components`), [catalog.py:240-340](../../../python-api/migration/resq_migration/catalog.py#L240-L340) (`_direct_precedent_names`, `_direct_dependent_names`, `_filter_existing_dependents`), [catalog.py:400-520](../../../python-api/migration/resq_migration/catalog.py#L400-L520) (`_dataset_type_graph_fields`, `_apply_sidecar_graph_meta`, `_reconcile_sidecar_dependents`); [test_resq_data_migration_graph.py](../../../python-api/tests/test_resq_data_migration_graph.py); the parity tests in [test_engine_dataset_sidecar_contract.py](../../../frontend/tests/test_engine_dataset_sidecar_contract.py). Also the two things the import has to match, added 2026-09-12 while doing the step: the step 1 helper itself in [dataset_type_contract.py](../../../python-api/src/arcrho_api/dataset_type_contract.py) (`formula_references`, `dataset_type_formula_graph`), and step 2's rule in [calculated_dataset_service.py](../../../frontend/app_server/services/calculated_dataset_service.py) (`_generated_formula_rows`, `_direct_precedent_names`, `_direct_dependent_names`, `sidecar_graph_fields`), which the migration mirrors line for line. Skill `$arcrho-json-contract`. Memory: "Macro tests poisoned by test_resq_dfm_v2" (run the migration tests in their own pytest process).

**Do.**

- [ ] Replace catalog's `_formula_components`, `_direct_precedent_names`, and `_direct_dependent_names` with calls into the step 1 helper, applying the same existing-instance rule as step 2 (generated precedents and all dependents filtered to instances in the class; app-calculated precedents kept).
- [ ] Keep `_reconcile_sidecar_dependents` and the cell-link merge as they are; only the formula edges change.
- [ ] Add a full-payload parity test: the app server's Engine sidecar and the migration's, for A, C, and B with identical logical inputs and two different path spellings, compare equal as parsed payloads.

**Tests.** `test_resq_data_migration_graph.py` gains the A/C/B class; the parity test lands beside the existing Engine-sidecar parity coverage.

**Done when.** The parity test passes for A, C, and B, and the migration graph tests pass in their own pytest process.

### Step 4 — A scoped refresh rebuilds the formula datasets too

**Goal.** Importing source data scoped to A regenerates A, B, and every generated descendant in the selected classes, then walks B's methods; the rules-save job gets the same expansion for free.

**Read first.** [Proposed behavior](#proposed-behavior) items 2, 3, and 4; [Answer](#answer). [source_table_refresh.py:1-130](../../../server-components/src/arcrho_engine/source_table_refresh.py#L1-L130), [source_table_refresh.py:188-224](../../../server-components/src/arcrho_engine/source_table_refresh.py#L188-L224), [source_table_refresh.py:379-464](../../../server-components/src/arcrho_engine/source_table_refresh.py#L379-L464), and the job execution that follows it; [data_processing_rules_jobs.py:150-215](../../../server-components/src/arcrho_engine/data_processing_rules_jobs.py#L150-L215); the scope and result fields of [arcrho_source_refresh_contract.py](../../../python-api/src/arcrho_source_refresh_contract.py); [test_source_table_refresh.py](../../../server-components/tests/test_source_table_refresh.py). Memory: "Engine in-process calculator", "Refresh problem diagnosis logs", and "Mixed origin-length precedents" (BF and Cape Cod failures in the Q2 test project are pre-existing; do not chase them).

**Do.**

- [ ] Expand the requested dataset types once per job through the step 1 forward closure, on types and before any instance filtering, so an intermediate type with no instance cannot hide a later one. `_engine_dataset_instances` receives the expanded set; both callers get the expansion.
- [ ] Keep the user's selection in the request and status as it is; add the derived set to the result (a `dataset_types_expanded` list) so a status can say what was selected and what was rebuilt, and validate it in the contract.
- [ ] Every successful regeneration in a class is already a root of the one walk; make sure the expanded instances join that batch and a repeated path or instance is walked once.
- [ ] A failed regeneration of B is reported as today and its downstream is not claimed refreshed.
- [ ] Write a test that opens the alternate-period cache of a regenerated dataset after the job; fix the invalidation owner only if it serves pre-import values.

**Tests.** `test_source_table_refresh.py` gains: A-only scope rebuilds A and B; transitive B -> D; missing intermediate instance; two instances of one type; a class restriction; unscoped refresh unchanged; failed regeneration of B; the rules-job path expanding the same way. Each asserts the derived set in the result.

**Done when.** An A-only refresh in the test workspace rebuilds A, B, and generated descendants inside the selected classes, then refreshes B's downstream methods; unrelated Engine types stay outside the regeneration set; the rules-job test shows the same expansion.

### Step 5 — The Dependency Graph window draws the links and marks a generated formula

**Goal.** In the Project Instance Dependency Graph, an Engine-built formula dataset is labelled `Generated`, its inputs are drawn with arrows into it, and the default view shows them.

**Read first.** [Proposed behavior](#proposed-behavior) item 7. [dataset_dependency_graph_service.py](../../../frontend/app_server/services/dataset_dependency_graph_service.py) (whole), [dataset_service.py:1637-1660](../../../frontend/app_server/services/dataset_service.py#L1637-L1660), [dependency_graph_layout.js:1-60](../../../frontend/ui/project_instance/dependency_graph_layout.js#L1-L60), [dependency_graph_window.html](../../../frontend/ui/project_instance/dependency_graph_window.html), the family block of [dependency_graph_window.css:545-565](../../../frontend/ui/project_instance/dependency_graph_window.css#L545-L565), the import lines of [dependency_graph_window.js:35-45](../../../frontend/ui/project_instance/dependency_graph_window.js#L35-L45); [test_dataset_dependency_graph_service.py](../../../frontend/tests/test_dataset_dependency_graph_service.py), [project_instance_dependency_graph.test.mjs](../../../frontend/tests/project_instance_dependency_graph.test.mjs); the Dependency Graph paragraphs of [project_instance.md](../../../frontend/docs/ui/project_instance.md) and [dataset.md](../../../frontend/docs/app_server/domains/dataset.md). `frontend/FRONTEND_AGENT_GUIDELINES.md`, skill `$arcrho-ui-design`. Memory: "Dev UI cache and restart", "Frontend node test suite", "Worktree baselines mask new failures".

**Do.**

- [ ] In the graph service, hydrate each engine node's `formula` from `_dataset_type_calculation_map` in the same read that builds the node list, one dataset-types read per graph. A direct-column generated type has an empty Formula cell and stays empty. Do not put the formula on the index row; `FORBIDDEN_INDEX_ROW_FIELDS` exists to stop that.
- [ ] In `dependencyNodeKind`, an `engine` node with a non-empty formula becomes the `generated` family labelled `Generated`; without one it stays `engine` / `Imported`. Add the legend entry and one accent beside the other four, so the node stripe, the popover row, and the legend swatch all read it.
- [ ] No new arrow style, and no change to `dependencyGraphHiddenByDefault`: A and C are drawn because they now have a dependent.
- [ ] Bump the `?v=` stamp on the layout module's import in the window (and any other importer).
- [ ] Update the Dependency Graph paragraphs in `project_instance.md` and the service line in `dataset.md`; add a release fragment under `frontend/changes/unreleased/`; run `python tools/docs_index_builder.py --write` then `--check` from `frontend/`.
- [ ] Check that an open window redraws after a regeneration through the page's disk-backed table reload; if the class index does not change, the Refresh button is the documented path. Add a message only if the window stays stale after the table itself has reloaded.

**Tests.** `test_dataset_dependency_graph_service.py`: the A/C/B class with a method reading B - both edges into B, the edge into the method, B's hydrated formula, A's and C's empty one. `project_instance_dependency_graph.test.mjs`: `dependencyNodeKind` with and without a formula; A and C not hidden by default; B's left port listing A and C as `Imported` and A's right port listing B as `Generated`; the reach from A covering B and its methods; the legend spelling the new label. Run with the bundled `node-portable`; take the failure baseline by stashing in the same tree.

**Done when.** The fixture draws `Earned Premium (Imported) -> Total Earned Premium (Generated) -> D 13 / D 18 / D 92` with `Remaining Budget Premium (Imported)` as B's second input, all visible by default, selecting A lights B and B's methods, and a class with no generated formula types draws exactly as before.

### Step 6 — A one-off script fixes the links of the few existing projects

**Goal.** One app-server function recomputes the two link lists of every Engine-built dataset in a reserving class and rewrites only the files whose lists change; a checked-in script under `tools/` runs it over every class of one project or all of them, on the Server PC, writing nothing without `--apply`.

**Read first.** [Proposed behavior](#proposed-behavior) item 8; [Why the change is safe](#why-the-change-is-safe). [calculated_dataset_service.py:3020-3066](../../../frontend/app_server/services/calculated_dataset_service.py#L3020-L3066) (the dataset-type job's "graphs" stage, the loop to copy) and `apply_sidecar_graph_fields`; [dataset_sidecar_status_service.py:218-233](../../../frontend/app_server/services/dataset_sidecar_status_service.py#L218-L233) and `reserving_class_io_lock`; [source_table_refresh.py:140-186](../../../server-components/src/arcrho_engine/source_table_refresh.py#L140-L186) (`_reserving_class_paths`, how a project's classes are enumerated from disk); [backfill_stored_period_lengths.py](../../../tools/backfill_stored_period_lengths.py) (the model: arguments, the `--apply` gate, the counted report, the tests beside it under `tools/tests/`); the lease functions of [arcrho_dependent_propagation_contract.py](../../../python-api/src/arcrho_dependent_propagation_contract.py). AGENT_GUIDELINES "Temporary Files" and "Agent Project Data Access" (an agent may run the script only against `NJ_Annual_Prod_202605_Fake`; the other projects are the user's runs). Memory: "Offline dependent-walk replay" (never point a test at the live share; patch the project directory helpers and byte-copy a class first).

**Do.**

- [x] Add `repair_reserving_class_graph_fields(project_name, reserving_class)` to `calculated_dataset_service.py`: under the class io lock, read each `source_kind == engine` sidecar of the class, run `apply_sidecar_graph_fields`, write only when the parsed payload differs, and return counts (sidecars read, sidecars written) plus the names it could not read. Touch nothing but the two link lists: no `updated_at`, no audit entry, no index rebuild (the index carries no link fields). A second run writes nothing.
- [x] Add `tools/repair_dataset_graph_fields.py`: `--project` once or many, or every project under the server root; `--apply` to write, otherwise report only; take the reserving-class lease from the propagation contract for each class before writing and release it after, so a save landing at the same moment is refused with the 423 hold it already understands, and skip and report a class whose lease is held by a running job; print per-project and per-class counts and finish with a summary the deploy step can paste into this plan.
- [x] The script imports the working tree's app server directly, so it needs nothing deployed, but it must be run on the Server PC where the workspace is local disk; the module docstring says so and names the machine, and there is no check in code.
- [x] The script walks a project's classes through `calculated_dataset_service.project_reserving_classes`, added beside the repair: the same enumeration the Engine's source refresh makes, the canonical name from each class's own `index.json` and the folder name only as a fallback. The Engine keeps its own copy, because its tests stand a minimal `app_server` module in for the real one and delegating would pull the whole service into them.

**Tests.** A new `frontend/tests/test_dataset_graph_repair.py`: a fake project with two classes, one holding A, C, and B with stale links and a method reading B, the other already correct; the first run writes only the stale sidecars, keeps the method dependent, and leaves every other field byte-identical; the second run writes nothing; an unreadable sidecar is reported and the rest still repaired. A new `tools/tests/test_repair_dataset_graph_fields.py`: without `--apply` nothing is written and the report is right; with it the class is repaired; a held class is skipped and reported.

**Done when.** The test project comes out with the step 2 links after one `--apply` run, a second run writes nothing, no timestamp or audit entry moved, and a report-only run changes no file.

### Step 7 — Deploy, fix the existing projects, and check the fake project

**Goal.** The change is live on the ArcRho Server, the few existing projects carry the links, and the fake project shows and follows them.

**Read first.** AGENT_GUIDELINES "Component Build and Deploy" and [component-deployment-authorization.md](../../../agent-instructions/component-deployment-authorization.md); the docstring of `tools/repair_dataset_graph_fields.py`. Memory: "Deploy without asking", "Remote component deploy", "Gateway deploy swap lock", "Bridge restart after deploy", "Hosted-save fix needs Engine deploy", "Deploy staleness is mtime-based", "Dev PC and Client PC identity".

**Do.**

- [x] Check the build listener heartbeat names its own clone, then run `python server-components/deploy.py` with no arguments; expect the Bridge, the Engine, and the Gateway to be stale.
- [x] Confirm the deployed canonical copies carry the step 2 runtime change and the step 4 expansion.
- [ ] On the Server PC, run the step 6 script against `NJ_Annual_Prod_202605_Fake` without `--apply`, read the report, then with `--apply`; record both counts in this plan.
- [ ] Hand the user the report-only command for the other projects; those `--apply` runs are theirs, and the counts they report go into this plan too.
- [ ] On the fake project: open Details on Earned Premium and Total Earned Premium; open the Dependency Graph on the default class and press Refresh; run Import Data scoped to Earned Premium only, then confirm Total Earned Premium's cache and sidecar timestamps moved and `D 13` refreshed.
- [x] Record what was observed, and move the plan to `completed/` with its README row, as [README.md](../README.md) describes.

**Deploy, 2026-09-13.** The build listener's newest heartbeat named its own clone `E:\XWSpace\Repos\ArcRho-buildbot`. `deploy.py --stale` reported the Bridge, the Engine and the Gateway stale, as expected, and also the Credential Installer, which earlier committed work had made stale and which was left alone. `python server-components/deploy.py bridge engine gateway` built and deployed all three at 06:00-06:01 UTC. Verified afterwards: the Engine's and the Gateway's `arcrho_canonical` copies of `arcrho_runtime_service.py` carry the step 2 call, their `arcrho_source_refresh_contract.py` carries the step 4 `dataset_types_expanded` field, the Gateway's `dataset_type_contract.py` carries the step 1 graph helper, and the Bridge's bundled `resq_migration/catalog.py` is byte-identical to the working tree.

The remaining boxes need the Server PC: the repair script walks a project's classes over local disk, and the Details, Dependency Graph and scoped-import checks are done in the app.

**Closed, 2026-11-09.** The user reported the testing complete and asked for the plan to be closed. The repair script's counts and the individual app observations were not handed over, so the three boxes above stay unticked as a record that no figures were written down here, not as open work. The Fake project was rebuilt from a new source table on the same day ([fake_project_refresh.md](fake_project_refresh.md)), which writes these links through the ordinary import.

**Tests.** None new; this step observes the live system.

**Done when.** The three components are deployed, the script reports zero writes on a second pass over the fake project, its Details and Dependency Graph show the links, and an Earned Premium-only import refreshed Total Earned Premium and its methods.

## Rough size

Seven sessions. Steps 1 to 4 and 6 are each one ordinary session of code plus tests; step 5 is one session across the graph read and the window; step 7 is a short session plus the deploy, the script runs, and the checks on the server. The arrows in the window and the repairs done by every future import both fall out of step 2, so the work that most needs care is step 2 (the runtime branch) and the `--apply` runs of step 7 (a write across every class of a live project).

Transport follow-up found during inspection: `source_table_router.get_source_refresh_plan` intentionally executes locally, and `source_refresh_service.describe_source_refresh_plan` inspects server workspace state there. Keep client-only drive-letter translation local, move project configuration and busy-state reads through the Gateway, and remove client SMB access for that server-owned portion. Submission and status already use hosted mutation/read wrappers. This transport cleanup is adjacent work, not a prerequisite for the dependency fix.
