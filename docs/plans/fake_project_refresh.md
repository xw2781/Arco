# Fake Project Refresh: Realistic Data and Current File Formats

Status: Investigated and planned 2026-09-26; decisions taken the same day (fix on the local test root first, then publish; one new synthetic source file that both ResQ and Arco import; repair file formats in place). 13 session-sized steps (step 12 appended 2026-11-06, run between 7 and 8; step 13 appended 2026-11-06, run between 8 and 9); steps 1-4 done 2026-11-04, step 5 done 2026-11-05, steps 6, 7, 12, 8, 13 and 9 done 2026-11-06 (decisions 8 and 9 taken in step 7, 10 and 11 after step 8); production now holds the refreshed project; step 10 done 2026-11-09 (decisions 12-14); step 11 is next.
Last updated: 2026-11-09
Related: [local_server_root_and_server_switcher.md](completed/local_server_root_and_server_switcher.md) (the local root this work runs on), [client_smb_retirement.md](client_smb_retirement.md) (the work that needs this project to test smoothly)

**How this ships.** Steps 1, 5, 7 and 9 change code a server component bundles (the ResQ import's sidecar writer, run by the Bridge; the Engine's source refresh skipping ResQ-stored triangles; the project dates rule that lets Origin End follow Development End, decision 9, in the Engine and Gateway): additive fixes, safe for the released app, deployed to production in step 9. Everything else is tools and data. Steps 2-8, 12 and 13 write only to the local root. Step 9 replaces production's copy of the Fake project and adds a source file on the Server PC share; step 10 is ResQ-side work on the Server PC.

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A ResQ import no longer writes datasets without a review status | [x] | 2026-11-04 | 45 min | 15 min | Imported datasets always carry a review status; an incomplete one is refused instead of saved |
| 2 | One command reports every file in a project that is not in the current format | [x] | 2026-11-04 | 40 min | 6 min | One read-only command lists, by kind and problem, every project file the app would refuse or that is left-over clutter |
| 3 | The local Fake project opens without format errors | [x] | 2026-11-04 | 50 min | 25 min | The local copy passes every format check, and the BF and Cape Cod methods it refused before open again |
| 4 | A realistic synthetic source table for the Fake project | [x] | 2026-11-04 | 90 min | 14 min | One command writes a new source table with the same columns and segments whose totals add up and whose loss ratios and development look like real business |
| 5 | The local Fake project's datasets are rebuilt from the new source | [x] | 2026-11-05 | 45 min | 48 min | The local project now reads the new source table: every dataset built from it was rebuilt, pending counts are never negative and reported claim counts never go down |
| 6 | The adjusted triangles imported from ResQ sit on the same scale as the new data | [x] | 2026-11-06 | 50 min | 22 min | The adjusted and ad hoc triangles now follow the new figures, and the Penn+CT MP+PIP adjusted severity builds again |
| 7 | Every method in the local Fake project is recalculated on the new data | [x] | 2026-11-06 | 70 min | 42 min | The local project is valued at May 2026 again, Origin End may now fall after Development End, and every method that can refresh on the new data has; the ones that cannot are listed for step 8 |
| 8 | Methods whose settings make no sense on the new data are reset | [x] | 2026-11-06 | 60 min | 27 min | Hand-typed factors far from the new data, exclusions on empty cells and deleted candidates are reset, and every result is plausible; eight methods that read a precedent at another period length still refuse and wait on a decision |
| 9 | The refreshed project and the import fix reach production | [x] | 2026-11-06 | 45 min | 11 min | Production's Fake project is the refreshed one, reading the new source file beside the old one on the ResQ share, with the previous copy kept beside it; the import, refresh and dates fixes are live |
| 10 | ResQ's Fake project matches Arco's again | [x] | 2026-11-09 | 60 min | 315 min | ResQ's Fake project imports the new data and holds Arco's inputs, priors, adjusted triangles and method selections; the three spot-checked classes agree apart from two ResQ formulas recorded as known |
| 11 | Tests, fixtures and notes that quoted the old numbers are brought up to date | [ ] | | 40 min | | |
| 12 | Prior-quarter, BF prior and expected loss ratio inputs sit on the same scale as the recalculated results (runs between 7 and 8) | [x] | 2026-11-06 | 60 min | 16 min | Every prior-quarter figure, BF prior and expected ratio now follows the recalculated results, and the MA MP+PIP selections refresh again |
| 13 | Methods that read another method at a different period length are moved to that length (runs between 8 and 9) | [x] | 2026-11-06 | 55 min | 25 min | The eight methods that refused every refresh now use the period length of the method they read, and every class of the local project refreshes cleanly |

Overall: 12 of 13 steps done. Estimated 710 min, actual so far 566 min.

## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one workflow subagent), one commit.
- Note the clock before the first file is read and again at the commit, keeping the two parts apart: time spent reading and editing, and time spent running tests, checks and deploys.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date, the actual minutes and the one-line user note, update the "Overall" count and actual total, append the actual to the step's `Estimate:` line, and update the `Status:` line at the top and this plan's row in the [plans index](README.md).
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## What was found (2026-09-26)

A read-only scan of all 5,799 files of `NJ_Annual_Prod_202605_Fake` against the current contracts in `python-api/src/arcrho_api`.

### File formats

Mostly current: every one of 2,193 sidecars has the v4 layout, stored lengths and block-form links, and the RS, Berquist-Sherman, Bootstrap and Stochastic Consolidation methods are clean. The real problems:

| Kind | Problem | Files | What the app does |
| :--- | :--- | :--- | :--- |
| BF method | Dead format `arcrho-bornhuetter-ferguson-method-by-tab-v2`; its 9 sidecars point at missing CSVs | 4 | Refuses to open |
| BF method | Stored ultimate disagrees with its own source snapshots (the 2026-09-21 rule) | 48 of 63 | Refuses load, save and refresh; `tools/restate_bf_unobserved_origin_ultimates.py` fixes it and was never run here |
| CC method | Trend rate, percentage developed or trend factors disagree with the snapshots | 13 of 17 | Refuses; `tools/restate_percentage_developed.py` covers the percentage-developed case |
| Sidecar | `status` missing (9 also miss `method_type`) | 109 | Read as current, but fails `validate_sidecar_core` |
| Sidecar | Method output marked `calculated: false` | 10 | Fails validation |
| Leftovers | Two abandoned ResQ-import staging folders (138 files), a stray `data\tmp` class, 4 backups at the project root, 34 lock files, a 0-byte temp file | — | Noise for every scan and copy |

Self-healing and left alone: 197 DFMs without `curves_tab` (filled on next save), 7 indexes one version behind and one missing (rebuilt on read).

The missing-status sidecars were all written 2026-09-05 to 09-24 by the ResQ import (ResQ user names in `modified_by`, empty audit log), so a re-import recreates them until that writer is fixed — step 1.

### Data

The project was imported from `\\NE7SASWPN02\E\ResQ\IBNR_SQL_Codes\202605\ResQ_Channel_202605_Fake_2.csv` (346,125 rows, 34 columns), a copy of the real monthly extract with every column perturbed on its own, then hand-tuned for the bootstrap work. ResQ holds the same project and imports the same file.

- **Identities broken row by row.** Capped-at-50K above uncapped in 34% of rows, gross incurred ≠ paid + reserve in 51%, net ≠ gross − recoveries in 50%. Claim counts are fractional in 26-38% of rows.
- **Triangles.** Pending counts and case reserves negative in about 19% of cells, outstanding negative in 13.5%, cumulative reported decreasing in 12-13%, first link ratios of excess layers from −93 to +77, excess count triangles 97-99% zero, several "Adjusted" triangles empty.
- **Method inputs on another scale.** Every "Prior Qtr Selected / Indicated" vector is 100-900 times the current results (implied loss ratios 30-200); some are monthly where the methods are annual.
- **Outputs.** Median first selected factor 3.35 (90th percentile 20, maximum 363); 76 origins with an ultimate over 20 times the latest; 8 "F 00 Ultimate Net Loss" inputs all zero.

### What depends on it

- `tools/bootstrap_parity_report.py` compares stored Bootstrap and Stochastic Consolidation results with a frozen ResQ fixture; it goes stale once the data changes (step 11).
- `server-components/tests/test_reserving_class_type_contract.py` reads this project's `field_mapping.json` and `reserving_class_types.json` live from E:. The synthetic source keeps the same keys and columns, so both files survive.
- The ResQ probe and capture tools (`tools/resq_*`) name this project; their fixtures are frozen and stay green.
- About ten agent-memory notes quote its counts (step 11).
- The Engine-to-ResQ parity validation already targets another project.

## Decisions (taken 2026-09-26; 5 on 2026-11-05; 6-11 on 2026-11-06; 12-14 on 2026-11-09)

1. **Local first.** Every change is made and checked on `C:\Arco Server` (`tools/local_server.py`), and production's copy is replaced only in step 9.
2. **One shared source file.** A new synthetic source table replaces `_Fake_2.csv` as the import source for both ResQ and Arco, so the two stay comparable; the input vectors are exported to ResQ.
3. **New synthetic data**, not a repair of the perturbed extract. Hand-made selections and the bootstrap tuning are given up; step 8 resets what no longer fits.
4. **Repair formats in place**, not a re-import from ResQ; the four dead-format BF methods are deleted.
5. **What step 5's "Done when" accepts** (taken 2026-11-05, raised by the first step 5 run, whose refresh ended with 19 failed datasets):
   - **ResQ-stored triangles are never rebuilt.** The "Adjusted" / "ad hoc" triangles a ResQ import stored as engine datasets (`source` `resq_triangle`) read no source column. The source refresh now skips them with the same `period_reshape.is_imported_dataset` rule the project dates job uses; their old-scale values are rescaled in step 6. Deployed to the local root now, to production with step 9.
   - **Method refusals** (DFMs whose excluded cells are now missing, a Cape Cod on a 3-month precedent, a Result Selection's 3-month cache) are left to steps 7 and 8.
   - **A young class may have all-zero counts.** The all-zero check skips classes with fewer than 50 reported claims: MA has written only since 202512 and has no closed claim yet.
   - **A −1 excess pending cell is accepted**: a closed claim that a later recovery takes below the layer leaves the reported layer only. The pending check covers the total, not the excess layers.
   - **"No decreasing cumulative reported"** means reported claim counts; incurred losses may fall as case reserves are taken down.
6. **Step 6 is split** (taken 2026-11-06, raised by the first step 6 run). None of the 120 Result Selection outputs (the x 91 / x 92 vectors the priors, BF priors and expected loss ratios copy) was recalculated by step 5, so they still hold pre-refresh values: F 92 against the rebuilt latest incurred ran from 0.00 times to 7.2 times. Step 6 therefore rescales only the 25 ResQ-stored "Adjusted" / ad hoc triangles, which need nothing but the rebuilt source triangles. The prior, BF prior and expected-loss-ratio vectors move to step 12, run between steps 7 and 8 on step 7's recalculated Result Selections.
7. **Penn+CT `MP+PIP` "Net Loss--Incurred Adjusted*" becomes a hand-entered (input) triangle stored at 3 months** (taken 2026-11-06). It feeds a 3-month DFM and the 12-month "Severity--Adjusted Net Incurred per Reported ex CWOP"; an Engine-kind ResQ triangle cannot be rebuilt at another length, while a hand-entered one rolls up to 12, so the severity builds. Done in step 6 through the dataset save.
8. **The local project moves back to development end 202605** (taken 2026-11-06, raised by step 6's outcome). The local copy's development end had drifted to 202612 (a dates-panel test on 2026-11-03); production, ResQ and this plan use 202605. Step 7 moves it back with the project dates Engine job, the canonical path, and waits for its pending record to clear before any recalculation. Origin end stays 202612 (decision 9).
9. **Origin End may fall after Development End** (taken 2026-11-06, raised by step 7: the dates job refused 201701 / 202612 / 202605). Production and ResQ both hold that pair, and a mid-year valuation keeping the year's later (empty) origins is the normal layout; moving origin end to 202605 instead would have dropped 7 monthly origins from 104 imported datasets and left ResQ's grid. The project dates contract's rule now checks only Origin Start ≤ Origin End; the Project Dates panel's pre-check drops the same comparison. Deployed to the local root in step 7, to production's Engine and Gateway with step 9; the panel's pre-check reaches users with the next app release (until then the released panel still refuses that pair before submitting).
10. **The new source file goes beside the old one on the share** (taken 2026-11-06, was open decision 1): `\\NE7SASWPN02\E\ResQ\IBNR_SQL_Codes\202605\ResQ_Channel_202605_Fake_3.csv`, with `_Fake_2.csv` kept for rollback. Step 9 writes it.
11. **Methods that read another method at a different origin length are moved to that length** (taken 2026-11-06, was open decision 3, raised by step 8), not published refusing. Each of the eight methods takes its precedent's origin length: the four Cape Cods and the NY BI Total and Penn+CT BI Total DFMs F 13 become 3-month, the NY MP+PIP DFM F 13 and the Result Selection C 91 become 12-month (and C 92, which reads C 91, follows). Done in step 13.
12. **How ResQ re-imports** (taken 2026-11-09, was open decision 2). ResQ's five saved imports are repointed in the ResQ Import Wizard to `_Fake_3` copies cut from the shared source by `tools/split_fake_source_for_resq.py` (three new SQL Server tables beside the `_Fake_2` ones, two CSVs on the share) and run with their stored settings. Settings are changed only in the wizard; the API only runs a saved import.
13. **Values the Export macro does not send are written into ResQ directly** (taken 2026-11-09). `tools/push_fake_values_to_resq.py` writes Arco's prior-quarter vectors into the "– Feb 2026" vectors ResQ's x 81 / x 82 formulas read, and the ResQ-stored "Adjusted" triangles. A ResQ formula that is not a single reference (G 42 = F 42 × P 04 B, Rider PD+UMPD Earned Exposure = PD only) stays a known difference.
14. **ResQ's hand-written triangles are stored at development 1** (taken 2026-11-09, raised by step 10). A ResQ triangle stored at 12/12 puts a May valuation's values at ages 12, 24, …, and a ResQ DFM on it divides the latest value by a spline-interpolated monthly pattern, so the youngest origins differed from Arco (HOPxCAT F 23 C 2026: 3.23M against 1.50M) with identical inputs and factors. Stored at origin 12 / development 1, ResQ reads the same grid at the true ages (5m, 17m, …) as Arco does, and the ultimates agree to the unit. `tools/push_fake_values_to_resq.py` writes the Adjusted triangles that way; imported triangles were already monthly (memory `resq-dfm-mid-period-valuation`).

## Open decisions

None.

Two smaller choices carry a recommended answer the step applies unless told otherwise: the synthetic model keeps every existing key combination, the 34 columns, the origin range and the 202605 valuation, so field mapping, rules, reserving classes and dataset types stay valid (step 4); and "Prior Qtr" inputs are the new current results with a small random deviation, not a genuine re-run at an earlier valuation (step 6).

## Rough size

Estimated 710 minutes of agent time across 13 steps: 415 minutes of code edit and 295 of test, validation and deploy. The ResQ re-import in step 10 is the user's time and is not counted.

## Plan

Steps 1 and 2 are independent of each other and of everything else. Steps 3-8 run in order on the local root, with step 12 between 7 and 8 and step 13 after 8 (order 3, 4, 5, 6, 7, 12, 8, 13). Step 9 needs 1, 8, 12 and 13; step 10 needs 9; step 11 needs 10.

### Step 1 — ResQ import writes complete sidecars

**Goal.** Every sidecar the ResQ import writes carries `status` and `method_type`, and a method output is marked calculated.

**Read first.** The sidecar writers under `python-api/migration/resq_migration/` and the Bridge import path; `arcrho_api.sidecar_core_contract` (`validate_sidecar_core`, `SIDECAR_CORE_DEFAULTS`); skill `arcrho-json-contract`.

**Do.**
- [x] Find the writer that produced the 119 failing sidecars (ResQ user in `modified_by`, empty `audit_log`, extra `source` / `dataset_category`) and route it through the canonical builder, or validate before writing.
- [x] Cross-producer parity test per the Persisted JSON Producer Parity rule.

**Tests.** A ResQ-import test that every written sidecar passes `validate_sidecar_core`.

**Done when.** No import code path can write a sidecar that fails core validation.

Estimate: code edit 30 min, test/validation 15 min, total 45 min. Actual: code edit 8 min, test/validation 7 min, total 15 min.

**Outcome (2026-11-04).** The plain triangle and vector writers in `resq_migration/extractors.py` never set `status`, and the triangle writer set `method_type` only for Berquist-Sherman; both now write the app's values for a new input dataset (`"None"`, status from ResQ). `core._write_sidecar_json` runs `validate_sidecar_core` on every sidecar the import produces; the graph refresh and the precedent-label backfill patch a file already on disk and pass `in_place=True`, so an old incomplete file is carried forward until step 3 repairs it. A deferred-graph write now carries empty `precedents` / `dependents` until the bulk refresh fills them. The 10 `calculated: false` method outputs came from a 2026-07-20 DFM import and one app edit, not from current import code; the validation now refuses that shape too. The parity test checks the core values against the app's create path; full-payload parity is not possible while the import alone writes `source` and `dataset_category` — left for a separate decision. The shared macro library's ResQ migration support was already 21 files behind before this step; step 9 publishes it with the Bridge deploy.

### Step 2 — Project contract scan tool

**Goal.** One read-only command lists, per file kind and per problem, every file of a project that is not in the current format.

**Read first.** The canonical validators named in "File formats" above; the 2026-09-26 scan scripts are not kept, rebuild from the contracts.

**Do.**
- [x] `tools/scan_project_contracts.py --root <root> --project <name>`: sidecars, method JSON of every kind, `index.json`, persisted-text layout, leftovers; counts plus example paths; exit code 1 when anything fails.
- [x] Bounded parallel reads, so a scan over the share stays usable.

**Tests.** `tools/tests/test_scan_project_contracts.py` on a small fixture project with one file of each problem.

**Done when.** The scan of the local Fake copy reproduces the counts in "File formats".

Estimate: code edit 30 min, test/validation 10 min, total 40 min. Actual: code edit 4 min, test/validation 2 min, total 6 min (each method kind already had a normalizer, and the retired v4 migrator in git history showed the kind-to-contract map).

**Outcome (2026-11-04).** `py -3.10 tools/scan_project_contracts.py --root "<server root>" --project <name> [--examples N] [--json]`. Problems fail the run (exit 1); notices are what the app repairs by itself (a DFM without `curves_tab`, a missing or stale `index.json`) and do not. A lock file inside a staging folder counts under both leftovers, as the 2026-09-26 scan did. Counts measured 2026-11-04:

| Finding | 2026-09-26 | Production today | Local copy today |
| :--- | :--- | :--- | :--- |
| BF dead format | 4 | 4 | 4 |
| BF ultimate disagrees with snapshots | 48 | 48 | 48 |
| CC trend rate / percentage developed / trend factors | 13 | 5 / 4 / 4 | 5 / 4 / 4 |
| Sidecar missing `status` (and `method_type`) | 109 (9) | 105 (9) | 89 (8) |
| Method output `calculated: false` | 10 | 10 | 1 |
| Sidecar names a missing CSV | 9 | 9 | 7 |
| Staging-folder files / lock files / root backups / stray class / empty file | 138 / 34 / 4 / 1 / 1 | 138 / 34 / 4 / 1 / 1 | 135 / 32 / 4 / 1 / 0 |
| Notice: DFM without `curves_tab` | 197 | 191 | 15 |
| Notice: index missing / not current | 1 / 7 | 1 / 26 (version) | 0 / 24 (folder changed) |

Production reproduces the 2026-09-26 counts except where it was edited since (4 sidecars gained a status, 6 DFMs a `curves_tab`) and where the index version has moved on. Every difference in the local copy traces to that copy: the app saved its sidecars and DFMs on 2026-11-03 (each file that dropped out is now valid, `modified_by` the user), and the copy skipped the empty `.tmp` file and the staging folders' three lock files. No file fails the persisted text layout.

### Step 3 — Repair the local copy's formats

**Goal.** The local Fake project scans clean.

**Read first.** `tools/restate_bf_unobserved_origin_ultimates.py`; `tools/restate_percentage_developed.py`; memory `bulk-method-restatement-hold`; `tools/local_server.py`; memory `local-root-scripts-need-local-gateway-env` (a script against the local root needs the local Gateway credential and URL, not only `ARCRHO_SERVER_ROOT`).

**Do.**
- [x] With the local root, the local Gateway credential and URL set and the local server started, run both restate tools with `--apply`; extend the CC restate to the trend-rate and trend-factor cases if the scan still reports them.
- [x] A one-off `tools/repair_sidecar_core_fields.py --apply`: fill `status` and `method_type` from `SIDECAR_CORE_DEFAULTS`, mark method outputs calculated; no timestamp or audit change.
- [x] Delete the 4 dead-format BF methods and their 9 sidecars, the staging folders, `data\tmp`, the root backups, lock and temp files.
- [x] `copy-project` gains the same exclusions so a fresh copy never brings leftovers.

**Tests.** The repair tool's tests on a fixture.

**Done when.** `scan_project_contracts.py` reports nothing for the local copy, and the app opens a BF and a CC method that it refused before.

Estimate: code edit 30 min, test/validation 20 min, total 50 min. Actual: code edit 12 min, test/validation 13 min, total 25 min (the existing snapshot restate needed only a second method kind; the production-write investigation below is in the validation time).

**Outcome (2026-11-04).** The local copy scans with no problems; the 13 notices left (5 DFMs without `curves_tab`, 8 indexes the app rebuilds on read) are self-healing. Done on the Server PC root `E:\XWSpace\Arco Server`:

- **Methods.** `restate_bf_unobserved_origin_ultimates.py` now covers Cape Cod too (`--kind bf|cc|all`, default all): it recalculates from the method's own snapshots, so it fixes the trend-rate and trend-factor cases as well as percentage developed, and restates any method the app would refuse. `restate_percentage_developed.py` was not used for the apply: it re-reads precedents, and 5 of the methods it covers cannot refresh on this data (mixed origin lengths, a 1-row adjusted triangle). The apply restated 48 BF and 13 CC methods and queued 16 walks; 14 succeeded, and 2 left Result Selections review-needed on the old 3-month vs 12-month mismatch (`MA\MP+PIP` C/D/E/G 92, `NY\MP+PIP` C 91/92, F 31) — data problems for steps 5-8.
- **Sidecars.** `tools/repair_sidecar_core_fields.py` filled 81 `status`, 8 `method_type` + `status` (`method_type` takes the reader default `""`, not the `"None"` a fresh import writes) and marked 1 B&S output calculated.
- **Deleted.** The 4 dead BF methods; 7 sidecars without a CSV (the 4 BF outputs, and `F 42` / `G 42` / `F 63` in `NY\BI Total`, which only the dead BFs read) and their entries in 5 sibling graphs; the staging folder, `data\tmp`, 4 root backups and every lock file. The Result Selections `F 91` / `G 91` in `NY\BI Total` still list the deleted BFs as candidate methods; step 8 resets them if a refresh refuses.
- **copy-project** now also leaves out the project-root backups and the `data` folders project duplication already skips (staging, `tmp`); the backup pattern is shared with the scan.
- **Opened.** `load_bornhuetter_ferguson_method` / `load_cape_cod_method` run against the local root open `HOL / F 41 A` and the `HOPxCAT` and `PD+UMPD` `F 53` methods, all three refused before.
- **Lock files come back.** Every index write leaves `.index.json.lock`, so the scan reports lock files again after any use of the project; delete them before step 9's copy.
- **Production touched once.** A first `restate_percentage_developed.py --dry-run` run with only `ARCRHO_SERVER_ROOT` set sent its Engine calculations to the production Gateway: production's Engine regenerated 76 engine-dataset CSVs in production's `NJ_Annual_Prod_202605_Fake` (18:59-19:06, no other production file changed), and the local copies, cleared before the request, were regenerated by the local Engine afterwards (two 3-month views in `NY\BI Total` are left to regenerate on demand). The production CSVs are Engine output from production's own source table, the same an open in the app would produce; 54 of them differ from the local Engine's output for the same file, which is built from today's source.

### Step 4 — Synthetic source generator

**Goal.** A deterministic generator writes a source table with this project's 34 columns and key combinations, whose figures behave like real insurance data.

**Read first.** `python-api/src/arcrho_api/demo_data/abc_group.py` (the model: claim-by-claim Poisson frequency, lognormal severity, report and settlement lags, case reserves, premium trend); the project's `field_mapping.json`; the header and the distinct key combinations, origin range and premium rows of `_Fake_2.csv` (read once, structure only).

**Do.**
- [x] `tools/generate_fake_project_source.py --output <csv>`: every key combination and month of the current file; per-coverage frequency, severity, reporting and payment patterns, loss ratios 0.5-0.8; identities by construction (incurred = paid + reserve, net = gross − salvage − subrogation − recovery, capped ≤ uncapped by layer, excess ≤ total, integer non-negative counts, pending ≥ 0); premium and exposure rows including budget months.
- [x] Reuse the demo generator's helpers rather than copying them.

**Tests.** `tools/tests/test_generate_fake_project_source.py`: every identity holds on every row; same seed gives the same file; annual loss ratios and first link ratios fall in plausible ranges.

**Done when.** A generated file has the current header and keys and passes every identity.

Estimate: code edit 70 min, test/validation 20 min, total 90 min. Actual: code edit 9 min, test/validation 5 min, total 14 min (the demo model covered almost everything; the generator only maps the extract's keys onto it).

**Outcome (2026-11-04).** `py -3.10 tools/generate_fake_project_source.py --template <current csv> --output <new csv> [--seed N] [--valuation 202605]`, default seed `20261104`.

- **Template, structure only.** `--template` is the current extract (the local copy `source\master_table.csv` is the imported copy of `_Fake_2.csv`); only its keys and, per key, the month spans of its loss, earned-premium and remaining-budget rows are read. The output keeps all 759 keys, the 34 columns, those spans, the `sys_yrmo = 0` premium rows and the extract's `201701.0` origin text; running it on its own output keeps the same structure.
- **Model.** The demo's claim simulation (`abc_group`, whose five simulation helpers are now public) per key: IBNRCAT maps to a demo coverage, plus oil tank, foundation and umbrella coverages, health-care-primary and commercial-auto variants; `_CAT` keys get the demo's named catastrophes (Penn read as PA) and minor storm months as a subset of their parent. Keys with premium but no losses in the template still get none, so a few classes (umbrella mostly) show low loss ratios.
- **Budget rows.** An aggregate key's remaining budget is its members' projected premium and exposure after the valuation (zero up to it), with a 5% deviation.
- **Full run.** 226,393 rows (186,478 loss, 39,915 premium and budget) in 17 s, 33.8 MB; every identity holds on every row and cumulatively. Accident-year gross incurred / earned premium 0.57-0.69 for 2017-2024 (PA 0.55-0.79, HO 0.45-0.68); incurred 12-24 link 1.03-1.18 for the large lines, paid 1.3-1.6; 264,646 reported claims, 3,102 above 50K. The file is not committed: step 5 generates it.

### Step 5 — Rebuild the local datasets from the new source

**Goal.** The local project imports the generated file and every Engine-built dataset is regenerated from it.

**Read first.** `source_refresh_service` and the source-table profile (`field_mapping.json` `table_path`, `source/source_import.json`); memory `source-refresh-job-diagnosis`; memory `local-root-scripts-need-local-gateway-env`; `period_reshape.is_imported_dataset` and the class step of `server-components/src/arcrho_engine/source_table_refresh.py` (decision 5).

**Do.**
- [x] Generate the file under `C:\Arco Server\sources\` and point the local project's import source at it.
- [x] Run the source refresh on the local Engine; collect its failures.
- [x] A small realism report (share of negative, decreasing and all-zero cells per dataset type) run before and after.
- [x] (Decision 5) The source refresh skips the ResQ-stored triangles the Engine cannot rebuild; deployed to the local root.

**Tests.** None new for the data; the report is the check. `server-components/tests/test_source_table_refresh.py` gains the ResQ-triangle skip.

**Done when.** The refresh finishes with no failures and the report shows no negative pending counts, no decreasing cumulative reported losses, and no all-zero count triangles outside the excess layers. Decision 5 says what this accepts.

Estimate: code edit 20 min, test/validation 25 min, total 45 min. Actual: code edit 13 min, test/validation 35 min, total 48 min (two runs of the 14-minute refresh, the first blocked on decision 5).

**Outcome (2026-11-05).** On the Server PC root `E:\XWSpace\Arco Server`:

- **Source.** `E:\XWSpace\Arco Server\sources\ResQ_Channel_202605_Fake_3.csv` from `generate_fake_project_source.py` (default seed, template the old local `master_table.csv`; the original `_Fake_2.csv` is unchanged on the ResQ share). `field_mapping.json` `table_path` points at it; not committed.
- **Refresh.** Job `96a960fe…`: 226,393 rows, 32 of 32 classes, 1,288 datasets regenerated, 482 methods updated. The 18 ResQ-stored triangles are now skipped. One dataset still fails: Penn+CT `MP+PIP` "Severity--Adjusted Net Incurred per Reported ex CWOP", a calculated ResQ-stored triangle over a 3-month imported `Net Loss--Incurred Adjusted*` that the Engine cannot build at 12 months (the same failure as before; step 6 or 7). The other failure lines are method refusals left to steps 7-8: DFMs with excluded cells now missing (HOL, NY and Penn+CT `BI Total`, NY `MP+PIP`), the MA `BI Total` Cape Cod `F 53`, and the MA `MP+PIP` Result Selections.
- **Realism** (`tools/fake_project_realism_report.py`, before -> after): all three checks pass. Pending counts negative 21.3% -> 0%, outstanding negative 15.2% -> 7.4%, reported counts decreasing 0.02% -> 0%, gross incurred decreasing 14.1% -> 10.8%, net incurred 19.1% -> 14.2%, capped incurred about 36% -> 24%. Subro and recoveries are mostly negative because the source stores recoveries as negative amounts. The "Adjusted" triangles keep their old values until step 6.
- **Production untouched.** No file under production's `NJ_Annual_Prod_202605_Fake` changed after the step started (5,841 files checked).

### Step 6 — Rescale the ResQ-stored triangles

**Goal.** The 25 "Adjusted" / ad hoc triangles a ResQ import stored (`source` `resq_triangle`) sit on the scale of the rebuilt source triangles (decisions 5 and 6).

**Read first.** Decisions 5-7; `dataset_service._save_dataset_sidecar_impl` (the stored-shape rules for a hand-entered dataset, `stored_values_cleared`); `precedent_cache_service.materialize_engine_source` (why an Engine-kind ResQ triangle cannot be read at another length); `dfm_service._load_source_snapshot`'s development labels (a hand-entered precedent read without roll-up takes its sidecar's own labels); memories `local-root-scripts-need-local-gateway-env`, `scripts-save-through-gateway-client`, `bulk-method-restatement-hold`.

**Do.**
- [x] A one-off tool that sets each triangle to its base triangle (Net Loss--Incurred, Net Loss--Paid or Gross Loss--Incurred; "Net Loss - ad hoc" reads Net Loss--Incurred) times a small seeded per-origin factor, at the shortest lengths its dependent methods use, saved through the hosted dataset save so the walk runs.
- [x] (Decision 7) Penn+CT `MP+PIP` "Net Loss--Incurred Adjusted*" saved as a hand-entered triangle at 3 months.

**Tests.** The tool's tests on a fixture class.

**Done when.** Every triangle's latest diagonal is within 10% of its base's, and the Penn+CT `MP+PIP` severity builds.

Estimate: code edit 35 min, test/validation 15 min, total 50 min. Actual: code edit 16 min, test/validation 6 min, total 22 min (each hosted save took about a second, and the split left only the triangles).

**Outcome (2026-11-06).** `tools/rescale_resq_stored_triangles.py` (`--dry-run`, `--check`), tests in `tools/tests/test_rescale_resq_stored_triangles.py`. On the Server PC root `E:\XWSpace\Arco Server`:

- **Saved.** All 24 non-calculated triangles went through the hosted dataset save (seed 20261106, ±5% per origin); `--check` passes for every one, with latest/base from 0.977 to 1.014.
- **Shapes.** Penn+CT `BI Total` "Net Loss--Incurred Adjusted" (1x1 -> 3x3) and "Adjusted*" (1x1 -> 12x12) are rewritten at their DFMs' lengths. The two hand-entered monthly stores keep their store and are rescaled per origin: HOL "Net Loss--Incurred Adjusted***" held only zeros and stays empty, and MA `BI Total` "Adjusted*" holds one quarter. Moving them would carry their ResQ development labels (120 / 113) into a store their DFMs read without roll-up.
- **Decision 7.** Penn+CT `MP+PIP` "Net Loss--Incurred Adjusted*" is now hand-entered at 3 months, and its severity rebuilt (status current).
- **Walk failures for step 7 or 8.** NY `BI Total` F 23 C / F 24 C and Penn+CT `MP+PIP` F 23 C: "DFM input 'Net Loss--Incurred Adjusted*' has incompatible development geometry". Their sidecars keep ResQ's development labels (113 and 38), while the file has the local project's 40 quarterly columns. MA `MP+PIP` D 92: "Exact 3-month cache cannot be derived from the current 12-month output for 'D 81 - Prior Qtr Indicated'" (step 12's vectors).
- **Development end date differs.** The local project's General Settings say development end 202612; production's say 202605. So the local Engine builds 40 quarterly columns where ResQ had 38.
- **Production untouched.** No file under production's `NJ_Annual_Prod_202605_Fake` changed after 2026-11-05 00:57 EST (5,841 files checked).

### Step 7 — Recalculate every method

**Goal.** Every DFM, BF, CC, RS, Bootstrap and Stochastic Consolidation in the local project is refreshed on the new data.

**Read first.** Decisions 8 and 9; memory `project-dates-change-job` (the dates move, its pending record and its second run); memory `bulk-method-restatement-hold` (the 423 wait between classes); the restate tools' `_wait_for_class`; memory `refresh-problem-diagnosis-logs`. Memory `blank-csv-row-is-an-empty-origin`: the reader fix for a Result Selection whose oldest origin is unselected (commit 6f70babd, 2026-09-27) must be in the local root's Engine and Gateway before this step, or every such method's dependents fail to read it.

**Do.**
- [x] (Decision 8) Move the local project to 201701 / 202612 / 202605 with the project dates job; (decision 9) the contract first lets Origin End follow Development End.
- [x] A driver that refreshes class by class in dependency order and records each failure.
- [x] A plausibility report: selected factors, ultimate-to-latest ratios, loss ratios per method.

**Tests.** None new beyond the driver's dry-run test.

**Done when.** Every method refreshes, or each failure is listed with its reason for step 8.

Estimate: code edit 40 min, test/validation 30 min, total 70 min. Actual: code edit 18 min, test/validation 24 min, total 42 min (the dates job's two runs took 21 minutes; the walks found nearly everything already refreshed by it).

**Outcome (2026-11-06).** `tools/recalculate_project_methods.py` (`--dry-run`, `--report`), tests in `tools/tests/test_recalculate_project_methods.py`. On the Server PC root `E:\XWSpace\Arco Server`:

- **Engine and Gateway.** The blank-first-row reader fix (6f70babd) was already in both. The Gateway was behind the tree and was redeployed, then both again with decision 9.
- **Dates (decisions 8, 9).** Job `psdates_step7_1606a764d1ce` moved the project to 201701 / 202612 / 202605: 1,288 engine datasets regenerated, 23 imported datasets and 14 methods reshaped, 458 methods updated; it asked for a second run, which (`psdates_step7_792827a49237`, 9 classes, 181 methods) cleared the pending record.
- **Walks.** One walk per class over its engine and hand-entered datasets: 13 of 22 classes clean. The method refusals left for step 8 (each blocks its dependents; the rest of each list is "precedent refresh failed"):
  - *Excluded ratio cells now empty* ("DFM input values are missing for previously excluded ratio cells"), 22 DFMs: HOL C 22, C 52, H 02; NJ BIR51+UMBIR51 C 22; NJ BIx51+UMBIx51 C 52; NY BI Total C 12, C 32, C 42, C 43, C 52, F 23, F 24; NY MP+PIP C 32, C 43, C 52, F 11, F 23; Penn+CT BI Total C 22, C 52; Penn+CT MP+PIP C 22, C 52.
  - *Development geometry.* NY BI Total F 23 C / F 24 C: the hand-entered "Net Loss--Incurred Adjusted*" was reshaped to 38 quarterly columns but its sidecar keeps ResQ's 113 monthly development labels. Penn+CT MP+PIP F 23 C now refreshes. Newly failing after the date move: Penn+CT BI Total F 23 E and F 46 ("Net Loss--Incurred Adjusted", engine kind), MA MP+PIP D 23 C ("Gross Loss--Incurred Adjusted*", engine kind) and MA BI Total F 23 C (monthly hand-entered store): the date move left these ResQ triangles 38 columns wide, while an Engine triangle with origins to 2026 Q4 is 40 wide (two blank columns past the valuation) and the DFM reader only trims extra blank columns. A rewrite at 40 columns through the dataset save (as step 6 did) fits them without a code change.
  - *Origin length.* Cape Cod on a 3-month DFM: MA BI Total F 53, MA MP+PIP D 53, NY BI Total F 53, Penn+CT MP+PIP F 53. DFM precedent at another origin length: NY MP+PIP F 13 (C 12 is 12-month, expected 3), Penn+CT BI Total F 13 (C 12 is 3-month, expected 12).
  - *Step 12's vectors.* MA MP+PIP C 92 / D 92: "Exact 3-month cache cannot be derived from the current 12-month output" for C 81 / D 81 Prior Qtr Indicated.
- **Plausibility** (`--report`, 561 DFM, BF, Cape Cod and Result Selection methods): first selected DFM factor median 2.73, 90th percentile 18.5, maximum 1,614 (NJ BIx51+UMBIx51 F 12 Prior LDFs; the large ones are paid and ALAE DFMs on young or excess layers, and prior or user-entry selections from the old data); 48 methods have an origin whose ultimate is over 20 times its latest (worst MA MP+PIP G 41 BF Paid). Result Selection loss ratios on earned premium: median 0.52 over 33, 9 outside 0.3-1.5 (0.11 to 2.88), because their selections still hold the old figures. Step 8 resets these.
- **Production untouched.** No file under production's `NJ_Annual_Prod_202605_Fake` changed after the step started (5,841 files checked).

### Step 8 — Reset methods that no longer fit

**Goal.** No method carries a setting made for the old data that gives nonsense on the new.

**Read first.** Step 7's report; step 6's and step 12's tools (`rescale_resq_stored_triangles.py`, `rescale_prior_inputs.py`), which this step re-runs; `dfm_contract.recalculate_dfm_method` (the exclusion refusal) and `dfm_service._load_source_snapshot` (why a hand-entered triangle's sidecar development labels must match its file).

**Do.**
- [x] Manual factor overrides and User Entry rows outside plausible ranges reset to the default average; tails re-selected.
- [x] Bootstrap and Stochastic Consolidation re-run and checked for sane ranges.
- [x] Re-run the plausibility report.

**Tests.** None.

**Done when.** The report shows no selected factor above 10 outside the first two columns and no ultimate more than 20 times the latest where the origin is past its third year.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 11 min, test/validation 16 min, total 27 min (the step 6 and 12 tools did most of the saving, and each class walk took under 10 seconds).

**Outcome (2026-11-06).** `tools/reset_unfit_method_settings.py` (`--walks`, `--part refusals|selections`, `--dry-run`), tests in `tools/tests/test_reset_unfit_method_settings.py`; `recalculate_project_methods.py --report` now lists this step's bar directly (`late_factor_over_10`, `mature_ult_over_20x_latest`). On the Server PC root `E:\XWSpace\Arco Server`, every save through the hosted method or dataset save:

- **Triangles.** Penn+CT BI Total "Net Loss--Incurred Adjusted" and MA MP+PIP "Gross Loss--Incurred Adjusted*" rewritten at the Engine's 40 quarterly columns (step 6's tool). NY BI Total and MA BI Total "Net Loss--Incurred Adjusted*" were hand-entered stores whose sidecars kept ResQ's 113 monthly development labels, which a DFM reads as they stand and the dataset save cannot change; they are now stored like the other ResQ triangles (engine kind, 3x3, 40 columns), so F 23 C, F 24 C and their BF refresh.
- **Exclusions.** 23 DFMs refused "previously excluded ratio cells" (21 from step 7, plus NY BI Total and NY MP+PIP C 22 once their class got further): the new data has no ratio where the old exclusions sit (a zero first-age count), so every exclusion of those DFMs is cleared.
- **Deleted candidates.** NY BI Total F 91 drops F 41 and F 41 B, G 91 drops G 41 (the BFs step 3 deleted); their origins go to F 23 and G 12.
- **Hand-typed factors.** 147 development columns in 104 DFMs selected a typed User Entry more than 25% from the column's "Volume - all" average; they now select that average. A column the new data has no ratio in keeps its typed factor. No Curves-tab tail was outside 1.0-1.5.
- **Priors.** The resets moved the selections, so step 12's tool was re-run (twice) on NY BI Total, NY MP+PIP, Penn+CT BI Total, Penn+CT MP+PIP and HOL; `--check` passes for all 191 vectors again.
- **Bootstrap and Stochastic Consolidation.** The class walks refreshed all six Bootstraps (scaled mean equals the selected ultimate; total reserve CV 0.07-0.27). The consolidation "F 72 A" was saved again and re-ran (CV 0.10). "F 72B" refuses: its segment Bootstrap does not exist and it has never run (then open decision 3; see step 13).
- **Plausibility** (561 methods): no selected factor above 10 past the second column, and the largest ultimate-to-latest ratio of an origin past its third year is 3.1, so the bar holds. First DFM factor median 2.60, 90th percentile 24.3, maximum 241 (was 1,614); 54 methods have an origin over 20 times its latest, all young. Result Selection loss ratios on earned premium: median 0.55 over 33; 7 outside 0.3-1.5 (HOL F 91/92 0.12; MA BI Total F 91/92 1.76 and MA MP+PIP D 91/92 2.81, a class written only since 202512; Rider BI+PIP F 92 0.26).
- **Still refusing.** The eight origin-length methods of then open decision 3 (moved in step 13, decision 11), and C 92 / F 31 behind NY MP+PIP C 91. Every other walk succeeds (16 of 22 classes clean).
- **Scan and production.** The scan reports nothing after the 25 lock files and the recreated empty `data\tmp` class were deleted (one self-healing notice). No file under production's `NJ_Annual_Prod_202605_Fake` changed after the step started (5,841 files checked).

### Step 9 — Publish to production

**Goal.** Production's Fake project is the refreshed one, reading the new shared source file, and the import fix is deployed. Needs step 13; decision 10 says where the file goes.

**Read first.** `AGENT_GUIDELINES.md` "Component Build and Deploy"; `tools/local_server.py`.

**Do.**
- [x] Write the generated file to the agreed place on the share.
- [x] A publish command in `tools/local_server.py` that refuses while any class of the project holds a lease, renames production's folder to `NJ_Annual_Prod_202605_Fake.before_refresh_<date>`, copies the local project in, and points its import source at the shared file.
- [x] `python server-components/deploy.py` for the step 1 fix, and `python publish_macro_library.py` from `python-api/macros` so the macro-run import carries it too.
- [x] Scan production's copy.

**Tests.** The publish command's refusal test.

**Done when.** Production's scan is clean and the app opens the project from a Client PC.

Estimate: code edit 20 min, test/validation 25 min, total 45 min. Actual: code edit 4 min, test/validation 7 min, total 11 min (under a quarter: the listener deploy took 4 minutes and the copy is local disk on the Server PC).

**Outcome (2026-11-06).**
- **Source.** `\\NE7SASWPN02\E\ResQ\IBNR_SQL_Codes\202605\ResQ_Channel_202605_Fake_3.csv` (226,393 rows, default seed, byte-identical to the local `master_table.csv`); `_Fake_2.csv` untouched.
- **Publish.** `py -3.10 tools/local_server.py publish-project NJ_Annual_Prod_202605_Fake --source <shared csv>`. It refuses while a project-scope or class lease, a queued walk, a source refresh or a project dates pending record exists; renames production's folder to `NJ_Annual_Prod_202605_Fake.before_refresh_20261106` (the rollback: rename it back); copies with `copy-project`'s exclusions; rewrites every JSON path into the local root to production's root (no local-root path is left) and the import source to the shared file, with `source_import.json`'s size and mtime taken from it.
- **Deploy.** `server-components/deploy.py` rebuilt Bridge, Engine, Gateway and Credential, exit 0; the payload was the five committed bundled files since `45429b8c`. Fresh heartbeats, Gateway health ok.
- **Macros.** `publish_macro_library.py` published the 21 ResQ migration-support files; `--check` exits 0.
- **Checks.** Production scan: 0 problems, 0 notices. Through the production Gateway: 31 classes with data, the table summary reads the new 226,393-row source, and one DFM, BF and Cape Cod (HOL F 23, F 41, F 53) load with no changed paths. The GUI open from a Client PC was not done by the agent.

### Step 10 — Bring ResQ's Fake project in line

**Goal.** ResQ imports the same source file and holds the same input vectors and methods. Needs open decision 2.

**Read first.** `python-api/macros/README.md`; the Export macro; memories `resq-com-probe`, `resq-com-probe-dont-call-blindly`.

**Do.**
- [x] ResQ's Fake project re-imports the new file on the Server PC (decision 12).
- [x] Export the input vectors and methods from Arco to ResQ with the Export macro.
- [x] Spot-check three classes, Arco against ResQ.

**Tests.** None.

**Done when.** The spot-checked classes agree at two decimals.

Estimate: code edit 10 min, test/validation 50 min, total 60 min. Actual: code edit 60 min, test/validation 255 min, total 315 min (five ResQ imports of 1-36 minutes, two re-runs after the mapping fix, four batch exports of about 7 minutes, and the young-origin diagnosis).

**Outcome (2026-11-09).**

- **Re-import (decision 12).** `py -3.10 tools/split_fake_source_for_resq.py --source <_Fake_3.csv> --suffix Fake_3` reproduces the `_Fake_2` pieces row for row from `_Fake_2.csv`, and wrote `ResQ_Channel_{Loss,Reported_Counts,Closed_Counts}_202605_Fake_3` (186,478 rows each) on `CO1ADBWPV01` / `Actuarial_NJ` and `EP_EEX_NJ_2026May_channel_Fake_3.csv` / `Budget EEX and EP 2026 May_Fake_3.csv` (38,397 / 1,518 rows) beside the `_Fake_2` ones. All five imports were repointed in the wizard and run (Loss 36 min, counts 12-15 min each).
- **Import mapping fixed.** The saved Closed Counts import sent `CWP_ex_50k/100k/1000k` into "Claim Counts--Reported Excess of …", overwriting the Reported Counts import, and "CWP Excess of …" had not been imported since June. Remapped to "Claim Counts--CWP Excess of 50K/100K/1M" in the wizard; Closed Counts then Reported Counts re-run. The excess-count triangles now agree.
- **Export.** "Export Reserving Classes to ResQ" for the 17 default classes: 582 items written, 24 saved, 135 skipped (124 calculated in ResQ, 8 HOL items on "Net Loss--Incurred Adjusted*" which ResQ's HOL lacks, 3 Arco-only inputs), 0 failed. Run twice; the second changed nothing in the spot check.
- **Direct writes (decision 13).** `tools/push_fake_values_to_resq.py --apply` wrote the prior-quarter vectors and 21 Adjusted triangles across the 17 classes. Re-storing a "– Feb 2026" vector at Arco's period needs `ClearData` first (it moves the store to the display period); a triangle write reloads the class, so each target is looked up again.
- **Development stored monthly (decision 14).** The young-origin DFM and BF differences came from ResQ triangles stored at 12/12; re-stored at 12/1 by the tool, ResQ's DFMs read 5m, 17m, … like Arco's.
- **Unselected DFM columns.** Five Arco DFMs had development columns with ratios but no selected row (HOPxCAT F 18 and F 28 columns 1-3, NJ BIx51+UMBIx51 C 42 column 1, NJ BI Total's two quarterly count DFMs columns 35-37); Arco computed them from "Volume - all", while the export left ResQ's old row ("Aug 2024") selected. `reset_unfit_method_settings.py --part selections` now selects the default average in such a column; applied on production through the hosted method save (Arco's ultimates unchanged), then exported.
- **Spot check** (`combined_side_by_side_review.py`, NJ MP+PIP, HOPxCAT, Rider PD+UMPD): every DFM Method Note and every dataset and Result Selection agrees at two decimals except decision 13's ResQ formulas (NJ MP+PIP G 42 and the G 91 that reads it; Rider PD+UMPD Earned Exposure, the 8 per-exposure datasets on it, and F 31) and the ResQ-only "– Feb 2026" helper vectors.
- **Seen on the way.** HOPxCAT F 91 still selects 20,651 for 2022 and 18,138 for 2024 (old-data overrides, both sides agree); step 8 did not reset Result Selection overrides.

### Step 11 — Fixtures, tests and notes

**Goal.** Nothing in the repository quotes the old Fake numbers as current.

**Read first.** `tools/bootstrap_parity_report.py`; `tools/resq_bootstrap_capture.py`; the agent-memory notes that name the project.

**Do.**
- [ ] Recapture the Bootstrap / Stochastic Consolidation ResQ fixture and re-run the parity report.
- [ ] Update or mark as historical every memory note and doc that quotes the old counts.

**Tests.** The suites that read the fixtures.

**Done when.** The parity report passes against the new fixture and no note presents the old figures as current.

Estimate: code edit 25 min, test/validation 15 min, total 40 min.

### Step 12 — Rescale the prior inputs

Appended 2026-11-06 (decision 6); runs after step 7 and before step 8.

**Goal.** "Prior Qtr Selected / Indicated", BF priors and expected loss ratios sit on the same scale as step 7's recalculated results.

**Read first.** Decision 6; the x 81 / x 82 vector sidecars and the BF prior sources in two classes; the hosted dataset save; step 6's tool.

**Do.**
- [x] A one-off tool (or step 6's, extended) that sets each prior vector to its counterpart times a small seeded deviation: x 81 from x 91; x 82, x 42, C 42a, F 42 B and F 00 from x 92.
- [x] Expected ratios from the same results: P 01, P 02, P 03 and P 04 A are E, E1, E2 and G 92 over D 92; P 04 B is G 92 over F 92; P 05, P 06 and P 07 are G, F and D 92 over Total Earned Premium.
- [x] Refresh the Result Selections these inputs feed once more.

**Notes.** Most prior vectors are stored monthly (120 rows) while their Result Selection is annual or quarterly: re-store each at its counterpart's period, with `stored_values_cleared` and the counterpart's origin labels. Save through `GatewayClient.save("dataset_sidecar", ...)` and poll `propagation_busy` before each save.

**Tests.** The tool's tests on a fixture class.

**Done when.** No prior vector is more than twice or less than half its current counterpart.

Estimate: code edit 35 min, test/validation 25 min, total 60 min. Actual: code edit 7 min, test/validation 9 min, total 16 min (step 6's helpers and step 7's driver were reused, and each hosted save took about a second).

**Outcome (2026-11-06).** `tools/rescale_prior_inputs.py` (`--dry-run`, `--check`), tests in `tools/tests/test_rescale_prior_inputs.py`. On the Server PC root `E:\XWSpace\Arco Server`:

- **Saved.** 191 vectors through the hosted dataset save (seed 20261106, ±5% per origin), run twice so the "Prior Qtr Selected" and BF priors read the selections the first run's walks refreshed. `--check` passes for all 191 it covers: vector over current counterpart from 0.84 to 1.15 (before: 0.001 to 1,936). There is no F 00 or P 05 input in this project. CMPxCAT "E1 42" and "E2 42" have no E1 / E2 selection and hold nothing; they are left as they are. Auto Liab Total "E 42" follows E 91, the only E selection there.
- **Period.** Each vector is written at the shortest period its counterpart and its dependents use; 51 were re-stored (most were monthly). The first run wrote MA BI Total "P 06" at its yearly F 63's period, and F 63 failed on a 10-against-40 shape, because a calculated dataset reads it at the quarterly selection's period; the second run put it back at 3 months.
- **Step 7's MA MP+PIP failure is gone.** C 92 / D 92 refresh now that C 81 / D 81 / C 82 / D 82 are stored at 3 months.
- **Left for step 8.** A final walk per class (step 7's driver) leaves the same 9 classes with the same refusals as step 7 (excluded ratio cells, development geometry, origin length). Two more show only in the walks this step's saves started: NY MP+PIP C 91 cannot read the 12-month C 42 DFM at 3 months, and NY BI Total G 91 finds no "G 41 - BF Paid" sidecar.
- **Plausibility.** Result Selection loss ratios on earned premium: median 0.54 over 33, maximum 2.81 (step 7: 0.52, 2.88). The selections still carry the old data's choices, which step 8 resets.
- **Production untouched.** No file under production's `NJ_Annual_Prod_202605_Fake` changed after the step started (5,841 files checked).

### Step 13 — Reshape the methods that read a precedent at another period length

Appended 2026-11-06 (decision 11); runs after step 8 and before step 9.

**Goal.** The eight methods of decision 11 take their precedent's origin length, so every method of the local project refreshes.

**Read first.** Decision 11; step 8's outcome; memories `mixed-origin-length-precedents`, `bulk-method-restatement-hold`, `method-precision-observed-not-projected`, `local-root-scripts-need-local-gateway-env`; the length handling of the method saves: `dfm_service.save_dfm_method` with `dfm_contract.apply_owned_patch` and `_apply_input_snapshot`, `cape_cod_service.save_cape_cod_method` with `cape_cod_contract.apply_owned_patch`, `result_selection_service.save_result_selection` with `_refresh_review_save_payload`; `dataset_instance_index_service.delete_cached_datasets`.

**Do.**
- [x] A one-off tool that finds every method reading a method output it cannot read at its own length and moves it through the app's saves.
- [x] Walk every class (step 7's driver), re-run step 12's `--check` and the rescale where it fails, and the plausibility report against step 8's bar.
- [x] Stochastic Consolidation F 72B: repair it if its missing segment Bootstrap is a data slip, otherwise list it.

**Tests.** The tool's tests on fixture sidecars and payloads; step 12's tool gains a test for a yearly counterpart read quarterly.

**Done when.** No method refuses for an origin length, every class walk succeeds, step 12's check passes, and step 8's bar still holds.

Estimate: code edit 30 min, test/validation 25 min, total 55 min. Actual: code edit 13 min, test/validation 12 min, total 25 min (the saves and walks took seconds each; most of the time went into finding which save path can change a length).

**Outcome (2026-11-06).** `tools/reshape_mixed_period_methods.py` (`--dry-run`), tests in `tools/tests/test_reshape_mixed_period_methods.py`. On the Server PC root `E:\XWSpace\Arco Server`:

- **Moved.** The four Cape Cods (MA BI Total F 53, MA MP+PIP D 53, NY BI Total F 53, Penn+CT MP+PIP F 53) and the DFMs NY BI Total F 13 and Penn+CT BI Total F 13 are now 3-month; NY MP+PIP F 13 and C 91 are 12-month, and C 92, which then could not read C 91 at 3 months, followed on the tool's second pass. The tool's plan found exactly these eight, and nothing else, before it ran.
- **How.** A Result Selection save of a review-needed selection re-reads every candidate at the new length, so C 91 and C 92 were saved with annual labels and each candidate's quarterly weights averaged per year. The Cape Cod and DFM saves cannot change a stored method's length: the Cape Cod save keeps the stored origin labels ("has 40 rows; expected 10"), the DFM save keeps the stored triangle and only relabels it, and a DFM refresh refuses a triangle whose development steps differ. None of the seven has a dependent, so each was deleted with the Project Instance delete and saved again as a new method, which reads every source at the new length. The Cape Cods keep their settings; the DFMs take their ratio-basis DFM's average-formula rows (the same rows at the new length) and select the row their old selection used most (Simple - 3 became Simple - 12 in NY BI Total and Simple - 8 in Penn+CT BI Total; Volume - all in NY MP+PIP). Their typed factors, Curves-tab choices and audit history start fresh. A first run sent the new DFMs without origin labels; the save refused them after the delete, and the three were restored from a copy taken beforehand and moved on the second run.
- **App gap found.** Changing Origin Length on an existing DFM or Cape Cod page cannot be saved as a user expects: the DFM save publishes the old triangle under the new length, and the Cape Cod save refuses. Not fixed here; worth its own fix.
- **Priors.** C 91 had refused since step 7, so the old data's figures it held had been copied into C 81 / C 82 / C 42a by step 12 (about 10 times the new results). Step 12's tool was re-run twice on NY MP+PIP; it now spreads a yearly counterpart evenly over the quarters when a prior is read quarterly (C 42a for the 3-month BF C 41). `--check` passes for all 191 vectors.
- **Walks.** All 22 classes succeed (step 8: 16).
- **Plausibility** (561 methods): step 8's bar holds (no selected factor above 10 past the second column, no origin past its third year over 20 times its latest). First DFM factor median 2.56, 90th percentile 23.5, maximum 220; Result Selection loss ratios on earned premium median 0.55 over 33, the same 7 outside 0.3-1.5 as step 8.
- **Left behind.** C 91 keeps its old 3-month and 6-month files beside the 12-month one; nothing reads them now (memory `calculated-walk-reads-stale-sibling-views` describes the risk if a reader is added).
- **F 72B not repaired.** All five of its segments name "F 72B - Bootstrap Net Incurred no PV", which exists only in All States MP+PIP; BI Total, CMPxCAT, COL and PD+UMPD have only "F 72 A ... with PV". Repairing it means creating four "no PV" Bootstraps or repointing the segments at the "with PV" ones, which changes what the consolidation means; left for a later decision. It has never run and holds no result.
- **Scan and production.** The scan reports nothing after the 22 lock files were deleted. No file under production's `NJ_Annual_Prod_202605_Fake` changed after the step started (5,841 files checked).
