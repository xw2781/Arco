# Fake Project Refresh: Realistic Data and Current File Formats

Status: Investigated and planned 2026-09-26; decisions taken the same day (fix on the local test root first, then publish; one new synthetic source file that both ResQ and Arco import; repair file formats in place). 11 session-sized steps, none started.
Last updated: 2026-09-26
Related: [local_server_root_and_server_switcher.md](local_server_root_and_server_switcher.md) (the local root this work runs on), [client_smb_retirement.md](client_smb_retirement.md) (the work that needs this project to test smoothly)

**How this ships.** Steps 1 and 9 change code a server component bundles (the ResQ import's sidecar writer, run by the Bridge): an additive fix, safe for the released app, deployed to production in step 9. Everything else is tools and data. Steps 2-8 write only to the local root. Step 9 replaces production's copy of the Fake project and adds a source file on the Server PC share; step 10 is ResQ-side work on the Server PC.

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A ResQ import no longer writes datasets without a review status | [ ] | | 45 min | | |
| 2 | One command reports every file in a project that is not in the current format | [ ] | | 40 min | | |
| 3 | The local Fake project opens without format errors | [ ] | | 50 min | | |
| 4 | A realistic synthetic source table for the Fake project | [ ] | | 90 min | | |
| 5 | The local Fake project's datasets are rebuilt from the new source | [ ] | | 45 min | | |
| 6 | Prior-quarter and prior-ultimate inputs sit on the same scale as the results | [ ] | | 50 min | | |
| 7 | Every method in the local Fake project is recalculated on the new data | [ ] | | 70 min | | |
| 8 | Methods whose settings make no sense on the new data are reset | [ ] | | 60 min | | |
| 9 | The refreshed project and the import fix reach production | [ ] | | 45 min | | |
| 10 | ResQ's Fake project matches Arco's again | [ ] | | 60 min | | |
| 11 | Tests, fixtures and notes that quoted the old numbers are brought up to date | [ ] | | 40 min | | |

Overall: 0 of 11 steps done. Estimated 595 min, actual so far 0 min.

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

## Decisions (taken 2026-09-26)

1. **Local first.** Every change is made and checked on `C:\Arco Server` (`tools/local_server.py`), and production's copy is replaced only in step 9.
2. **One shared source file.** A new synthetic source table replaces `_Fake_2.csv` as the import source for both ResQ and Arco, so the two stay comparable; the input vectors are exported to ResQ.
3. **New synthetic data**, not a repair of the perturbed extract. Hand-made selections and the bootstrap tuning are given up; step 8 resets what no longer fits.
4. **Repair formats in place**, not a re-import from ResQ; the four dead-format BF methods are deleted.

## Open decisions

1. **Where the new source file lives on the share** (step 9). Recommended: `ResQ_Channel_202605_Fake_3.csv` beside `_Fake_2.csv`, which stays for rollback. Writing into the ResQ source folder on the Server PC share needs the user's go-ahead at step 9.
2. **How ResQ re-imports** (step 10). The ResQ data load is a Server PC procedure the user runs; the step records it once the user describes it.

Two smaller choices carry a recommended answer the step applies unless told otherwise: the synthetic model keeps every existing key combination, the 34 columns, the origin range and the 202605 valuation, so field mapping, rules, reserving classes and dataset types stay valid (step 4); and "Prior Qtr" inputs are the new current results with a small random deviation, not a genuine re-run at an earlier valuation (step 6).

## Rough size

Estimated 595 minutes of agent time across 11 steps: 350 minutes of code edit and 245 of test, validation and deploy. The ResQ re-import in step 10 is the user's time and is not counted.

## Plan

Steps 1 and 2 are independent of each other and of everything else. Steps 3-8 run in order on the local root. Step 9 needs 1 and 8; step 10 needs 9; step 11 needs 10.

### Step 1 — ResQ import writes complete sidecars

**Goal.** Every sidecar the ResQ import writes carries `status` and `method_type`, and a method output is marked calculated.

**Read first.** The sidecar writers under `python-api/migration/resq_migration/` and the Bridge import path; `arcrho_api.sidecar_core_contract` (`validate_sidecar_core`, `SIDECAR_CORE_DEFAULTS`); skill `arcrho-json-contract`.

**Do.**
- [ ] Find the writer that produced the 119 failing sidecars (ResQ user in `modified_by`, empty `audit_log`, extra `source` / `dataset_category`) and route it through the canonical builder, or validate before writing.
- [ ] Cross-producer parity test per the Persisted JSON Producer Parity rule.

**Tests.** A ResQ-import test that every written sidecar passes `validate_sidecar_core`.

**Done when.** No import code path can write a sidecar that fails core validation.

Estimate: code edit 30 min, test/validation 15 min, total 45 min.

### Step 2 — Project contract scan tool

**Goal.** One read-only command lists, per file kind and per problem, every file of a project that is not in the current format.

**Read first.** The canonical validators named in "File formats" above; the 2026-09-26 scan scripts are not kept, rebuild from the contracts.

**Do.**
- [ ] `tools/scan_project_contracts.py --root <root> --project <name>`: sidecars, method JSON of every kind, `index.json`, persisted-text layout, leftovers; counts plus example paths; exit code 1 when anything fails.
- [ ] Bounded parallel reads, so a scan over the share stays usable.

**Tests.** `tools/tests/test_scan_project_contracts.py` on a small fixture project with one file of each problem.

**Done when.** The scan of the local Fake copy reproduces the counts in "File formats".

Estimate: code edit 30 min, test/validation 10 min, total 40 min.

### Step 3 — Repair the local copy's formats

**Goal.** The local Fake project scans clean.

**Read first.** `tools/restate_bf_unobserved_origin_ultimates.py`; `tools/restate_percentage_developed.py`; memory `bulk-method-restatement-hold`; `tools/local_server.py`.

**Do.**
- [ ] With `ARCRHO_SERVER_ROOT=C:\Arco Server` and the local server started, run both restate tools with `--apply`; extend the CC restate to the trend-rate and trend-factor cases if the scan still reports them.
- [ ] A one-off `tools/repair_sidecar_core_fields.py --apply`: fill `status` and `method_type` from `SIDECAR_CORE_DEFAULTS`, mark method outputs calculated; no timestamp or audit change.
- [ ] Delete the 4 dead-format BF methods and their 9 sidecars, the staging folders, `data\tmp`, the root backups, lock and temp files.
- [ ] `copy-project` gains the same exclusions so a fresh copy never brings leftovers.

**Tests.** The repair tool's tests on a fixture.

**Done when.** `scan_project_contracts.py` reports nothing for the local copy, and the app opens a BF and a CC method that it refused before.

Estimate: code edit 30 min, test/validation 20 min, total 50 min.

### Step 4 — Synthetic source generator

**Goal.** A deterministic generator writes a source table with this project's 34 columns and key combinations, whose figures behave like real insurance data.

**Read first.** `python-api/src/arcrho_api/demo_data/abc_group.py` (the model: claim-by-claim Poisson frequency, lognormal severity, report and settlement lags, case reserves, premium trend); the project's `field_mapping.json`; the header and the distinct key combinations, origin range and premium rows of `_Fake_2.csv` (read once, structure only).

**Do.**
- [ ] `tools/generate_fake_project_source.py --output <csv>`: every key combination and month of the current file; per-coverage frequency, severity, reporting and payment patterns, loss ratios 0.5-0.8; identities by construction (incurred = paid + reserve, net = gross − salvage − subrogation − recovery, capped ≤ uncapped by layer, excess ≤ total, integer non-negative counts, pending ≥ 0); premium and exposure rows including budget months.
- [ ] Reuse the demo generator's helpers rather than copying them.

**Tests.** `tools/tests/test_generate_fake_project_source.py`: every identity holds on every row; same seed gives the same file; annual loss ratios and first link ratios fall in plausible ranges.

**Done when.** A generated file has the current header and keys and passes every identity.

Estimate: code edit 70 min, test/validation 20 min, total 90 min.

### Step 5 — Rebuild the local datasets from the new source

**Goal.** The local project imports the generated file and every Engine-built dataset is regenerated from it.

**Read first.** `source_refresh_service` and the source-table profile (`field_mapping.json` `table_path`, `source/source_import.json`); memory `source-refresh-job-diagnosis`.

**Do.**
- [ ] Generate the file under `C:\Arco Server\sources\` and point the local project's import source at it.
- [ ] Run the source refresh on the local Engine; collect its failures.
- [ ] A small realism report (share of negative, decreasing and all-zero cells per dataset type) run before and after.

**Tests.** None new; the report is the check.

**Done when.** The refresh finishes with no failures and the report shows no negative pending counts, no decreasing cumulative reported losses, and no all-zero count triangles outside the excess layers.

Estimate: code edit 20 min, test/validation 25 min, total 45 min.

### Step 6 — Rescale the hand-entered inputs

**Goal.** "Prior Qtr Selected / Indicated", BF priors and expected loss ratios sit on the same scale as the new results.

**Read first.** The x 81 / x 82 vector sidecars and the BF prior sources in two classes; the hosted dataset save.

**Do.**
- [ ] A one-off tool that sets each prior vector to the matching current result times a small seeded deviation, at the method's own period, saved through the dataset save so the walk runs.
- [ ] Expected loss ratios and BF priors from the new premium and results.

**Tests.** The tool's tests on a fixture class.

**Done when.** No prior vector is more than twice or less than half its current counterpart.

Estimate: code edit 35 min, test/validation 15 min, total 50 min.

### Step 7 — Recalculate every method

**Goal.** Every DFM, BF, CC, RS, Bootstrap and Stochastic Consolidation in the local project is refreshed on the new data.

**Read first.** Memory `bulk-method-restatement-hold` (the 423 wait between classes); the restate tools' `_wait_for_class`; memory `refresh-problem-diagnosis-logs`. Memory `blank-csv-row-is-an-empty-origin`: the reader fix for a Result Selection whose oldest origin is unselected (commit 6f70babd, 2026-09-27) must be in the local root's Engine and Gateway before this step, or every such method's dependents fail to read it.

**Do.**
- [ ] A driver that refreshes class by class in dependency order and records each failure.
- [ ] A plausibility report: selected factors, ultimate-to-latest ratios, loss ratios per method.

**Tests.** None new beyond the driver's dry-run test.

**Done when.** Every method refreshes, or each failure is listed with its reason for step 8.

Estimate: code edit 40 min, test/validation 30 min, total 70 min.

### Step 8 — Reset methods that no longer fit

**Goal.** No method carries a setting made for the old data that gives nonsense on the new.

**Read first.** Step 7's report.

**Do.**
- [ ] Manual factor overrides and User Entry rows outside plausible ranges reset to the default average; tails re-selected.
- [ ] Bootstrap and Stochastic Consolidation re-run and checked for sane ranges.
- [ ] Re-run the plausibility report.

**Tests.** None.

**Done when.** The report shows no selected factor above 10 outside the first two columns and no ultimate more than 20 times the latest where the origin is past its third year.

Estimate: code edit 40 min, test/validation 20 min, total 60 min.

### Step 9 — Publish to production

**Goal.** Production's Fake project is the refreshed one, reading the new shared source file, and the import fix is deployed. Needs open decision 1.

**Read first.** `AGENT_GUIDELINES.md` "Component Build and Deploy"; `tools/local_server.py`.

**Do.**
- [ ] Write the generated file to the agreed place on the share.
- [ ] A publish command in `tools/local_server.py` that refuses while any class of the project holds a lease, renames production's folder to `NJ_Annual_Prod_202605_Fake.before_refresh_<date>`, copies the local project in, and points its import source at the shared file.
- [ ] `python server-components/deploy.py` for the step 1 fix.
- [ ] Scan production's copy.

**Tests.** The publish command's refusal test.

**Done when.** Production's scan is clean and the app opens the project from a Client PC.

Estimate: code edit 20 min, test/validation 25 min, total 45 min.

### Step 10 — Bring ResQ's Fake project in line

**Goal.** ResQ imports the same source file and holds the same input vectors and methods. Needs open decision 2.

**Read first.** `python-api/macros/README.md`; the Export macro; memories `resq-com-probe`, `resq-com-probe-dont-call-blindly`.

**Do.**
- [ ] The user re-imports ResQ's Fake project from the new file on the Server PC (user's time).
- [ ] Export the input vectors and methods from Arco to ResQ with the Export macro.
- [ ] Spot-check three classes, Arco against ResQ.

**Tests.** None.

**Done when.** The spot-checked classes agree at two decimals.

Estimate: code edit 10 min, test/validation 50 min, total 60 min.

### Step 11 — Fixtures, tests and notes

**Goal.** Nothing in the repository quotes the old Fake numbers as current.

**Read first.** `tools/bootstrap_parity_report.py`; `tools/resq_bootstrap_capture.py`; the agent-memory notes that name the project.

**Do.**
- [ ] Recapture the Bootstrap / Stochastic Consolidation ResQ fixture and re-run the parity report.
- [ ] Update or mark as historical every memory note and doc that quotes the old counts.

**Tests.** The suites that read the fixtures.

**Done when.** The parity report passes against the new fixture and no note presents the old figures as current.

Estimate: code edit 25 min, test/validation 15 min, total 40 min.
