# Excel Add-in over the ArcRho Gateway

Status: Done. Investigated and decided 2026-09-12, implemented across 10 session-sized steps 2026-09-12 to 2026-09-13, released 2026-09-13 and checked against a real workbook the same day. The share path is deleted, the add-in reaches project data only over HTTP, no coarser view is written to disk any more, a PC with no credential installs its own when Excel opens, and [excel-addin/README.md](../../../excel-addin/README.md) is the one-page note for users.
Last updated: 2026-09-16
Related: [hosted_workspace_http_transport.md](hosted_workspace_http_transport.md) (the transport this plan finally extends to Excel, and whose "coexist on SMB" decision this plan reverses)

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | What changed for the user |
| :--- | :--- | :--- | :--- | :--- |
| 1 | A workbook full of single-cell formulas stops fetching the same triangle over and over | [x] | 2026-09-12 | Twenty-one formulas over one triangle now read it once instead of twenty-one times. |
| 2 | Excel can talk to the ArcRho Server directly, and a check button proves it | [x] | 2026-09-12 | Excel can now reach the ArcRho Server directly, and a one-line check says whether this PC can. |
| 3 | The server can hand Excel a triangle's figures in one answer | [x] | 2026-09-12 | The ArcRho Server can now answer a request for a triangle with its figures, so Excel will not have to open files on the shared drive. |
| 4 | The server can hand Excel its period headings and project settings the same way | [x] | 2026-09-12 | The ArcRho Server can now answer a request for a project's period headings or its settings with their figures, so every Excel formula has an answer that does not need the shared drive. |
| 5 | Formulas get their figures from the server instead of the shared drive | [x] | 2026-09-12 | Formulas now read from the server, and every figure matches the shared drive exactly. The server is about twice as quick when a triangle has to be worked out, and neither quicker nor slower than the drive when it is only being read back. |
| 6 | Excel no longer needs the shared drive for project data at all | [x] | 2026-09-12 | Excel now gets every ArcRho figure and the Select Datasets list from the server, opens nothing on the shared drive, and tells a PC that has not been given access what to do about it in one line. |
| 7 | Coarser views of a hand-typed triangle stop leaving files behind on the server | [x] | 2026-09-12 | Asking for a hand-typed triangle at a coarser shape no longer leaves a copy of it on the server; the figures are worked out fresh each time and sent straight to Excel. |
| 8 | A one-page note tells a user how to set Excel up and what to do when it cannot connect | [x] | 2026-09-12 | One page now says what a PC needs for Excel to reach ArcRho, that Excel sets itself up the first time it opens, and what every message a cell can show means. |
| 9 | Released to the server and checked against a real workbook | [x] | 2026-09-13 | The new Excel add-in is released and a real workbook was checked against it: it works as expected. |
| 10 | Excel gives itself access to the server the first time it opens, with nobody setting the PC up by hand | [x] | 2026-09-12 | A PC that has never been given access to ArcRho now gives itself access the first time Excel opens, so nobody has to set a new PC up by hand. |

Overall: 10 of 10 steps done. Plan complete.

Step 10 was added on 2026-09-12, after steps 1 to 7 were already done, so it carries the next free number but ran next: step 10 landed the same day, and steps 8 and 9 follow it. Nothing is renumbered, because the numbers are already written into commits.

## How agents work this plan

- Take the first unticked step in the Progress table, except that step 10 runs before steps 8 and 9, as the note under the table says. One step is one context (a session or one workflow subagent), one commit.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date and the one-line user note, update the "Overall" count, and update the `Status:` line at the top and this plan's row in [README.md](../README.md).
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## The question

The add-in reads every dataset off the workspace share. On a Client PC each filesystem operation is a network round trip, and [Core.bas](../../../excel-addin/src_vba/Core.bas) performs several per formula before it opens the CSV: a look and a timestamp on the project's dataset-type table, a look and a timestamp on the reserving-class index, a directory check, a file check, then the read. A calculated dataset adds a request file written onto the share and a poll loop that checks for the Engine's answer every tenth of a second.

[hosted_workspace_http_transport.md](hosted_workspace_http_transport.md) decided in August 2026 that Excel would coexist on SMB indefinitely, on the grounds that "HMAC and byte-exact canonical JSON in VBA is the expensive part". That premise was tested on 2026-09-12 and is wrong, which is why this plan exists.

## What was measured

On the developer Client PC (`L-H2MQ6280FVP`) against the stored triangle `Net Loss--Incurred Adjusted***` in `NJ_Annual_Prod_202605_Fake`, reserving class `HPPREF_\_HO+DF_\_NJ_\_Legacy_\_HOL`. One pass is the metadata looks and the CSV read that one warm formula performs today, against one hosted read of the same dataset. Eight alternating passes.

| Path for one warm formula | Median |
| :--- | :--- |
| The share, in the order the add-in visits it | 320 ms |
| `dataset_cache_load` through the Gateway | 145 ms |

Two caveats. The HTTP figure built a fresh connection every pass and still returned 140 KB of JSON against a 33 KB CSV, so a reused connection and a leaner payload widen the gap. Share latency on this network varies between days, as the "PI path-load SMB cost" memory records, so treat the ratio rather than the absolute numbers as the result.

The larger win is not in that table. A calculated dataset today costs a request-file write plus a poll loop; the Gateway already hosts that whole exchange as one call, and the transport plan measured the exchange at roughly 3 s of a 15 s length-change run before it was hosted.

## What was proven

Both on 2026-09-12, on the developer Client PC, from a standalone script using the same late-bound COM objects and the same HTTP object VBA has:

- **The signature matches byte for byte.** `System.Security.Cryptography.SHA256Managed` and `HMACSHA256` through `CreateObject`, UTF-8 bytes through `ADODB.Stream`, hex through the `bin.hex` node type of `MSXML2.DOMDocument`. Compared against `sign_request` in [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py) on a payload containing a non-ASCII dataset name: identical body digest and identical signature. No new add-in reference, no pure-VBA crypto, nothing beyond what Windows ships.
- **A live authenticated read works.** A signed `table_summary` read for the fake project returned 200 with a real summary of the 84 MB source table in 0.105 s, using the credential already installed at `%APPDATA%\ArcRho\arcrho_gateway.json`.

The canonical-JSON half of the old objection turns out not to apply. The signature covers the SHA-256 of the exact bytes the client sends, so a client only has to hash its own body. Sorted canonical JSON is used for the save fingerprint, and the read and calculation transports keep no idempotency receipt by contract, so neither needs it.

The Gateway's advertised capabilities on the same day already included `dataset_cache_load`, `dataset_index`, `dataset_grid_load`, and the `ArcoTri` / `ArcoVec` / `ArcoHeaders` functions with the `exchange`, `dataset_run`, and `dataset_precheck` operations.

## Decisions

Made 2026-09-12. An implementer who finds one of these no longer holds should stop and record it under "Open decisions".

1. **Straight to the Gateway, not through the local app server.** The add-in signs its own requests and posts them. The alternative, hopping through the ArcRho app already running on the same PC, needs no signing code at all, but it requires the desktop app to be open, and an Excel-only user will not always have it. Chosen for that reason alone; the hop remains the fallback design if signing ever becomes a problem.
2. **The answer carries CSV text, not a JSON grid.** One field holds exactly the text the CSV would have held, produced by the same `pandas` call the runtime already uses to materialize one, so [GetDataArray](../../../excel-addin/src_vba/Core.bas#L1254) is reused unchanged and no number can parse differently than it does today. A JSON grid would need a second numeric path in VBA and a larger payload for no gain.
3. **One call per formula.** A new operation on the hosted calculation route resolves the cache, rolls a coarser view up in memory, runs the Engine only when the dataset genuinely needs it, and returns the figures in the same answer. Asking the existing precheck first and loading second is two round trips, which measured barely better than the share.
4. **The server owns the output location.** Only logical names travel: project, reserving-class path, dataset name, the two period lengths, and the two flags. The server derives the path with [set_data_path_like_vba](../../../frontend/app_server/helpers.py#L137), the canonical builder already named for this rule. The add-in's own path building and its folder-name and filename escaping are deleted rather than kept in parallel.
5. **No coarser-view files on the HTTP path.** Those files exist only because a worksheet formula could not be handed a frame in memory. Over HTTP it can, and the runtime already registers an in-memory roll-up handle when it is not materializing. The materializing producer and its Engine handler are removed once the share path is gone, not before.
6. **This is a replacement, not a fallback.** Per the "Server-Hosted Project Data I/O" rule in [AGENT_GUIDELINES.md](../../../AGENT_GUIDELINES.md), the share path is not kept as a safety net. Step 5 adds the HTTP path and chooses it whenever a credential is present, which is a rollout window; step 6 deletes the share path. The add-in is loaded from the share on every launch, so every user is on the new version as soon as it is released, and the "All users run the latest app version" memory makes old-client compatibility a non-goal.
7. **Shared library files stay on the share.** The reserving-class input CSV under `library\`, the version-track document, the team profile workbook, and the add-in itself are not project data and are out of scope.

## Open decisions

None open. The credential question that stood here was answered on 2026-09-12 and is recorded below.

## Answered decisions

- **How every Excel user gets a Gateway credential. Answered 2026-09-12: the add-in installs one for itself the first time it runs.** The question was whether to provision each Excel user by hand, one `configure_pilot.py` run at a time, during the step 9 rollout. The user decided against it: nobody is to be set up by hand, so the add-in must give the PC its own credential on first use. That is new work no step covered, so it became **step 10**, which runs after step 7 and before steps 8 and 9.

  **Step 9 therefore provisions nobody by hand any more.** Its "provision the credential for each Excel user" item is gone, and so is the item telling it to stop while this question was open. What step 9 now checks is that a PC with no credential sets itself up when Excel opens.

  The server still knows who is asking, because the credential is written through the workspace share under the user's own Windows account, and the share's own permissions are the authentication. Nothing new is handed out over the network: the Gateway grows no enrollment route, and no secret reaches a caller that can only reach the Gateway's port. This is the same trust boundary the ArcRho desktop app has used since the hosted-save pilot, where startup enrolls the logged-in user the same way.

- **Whether to go on deleting the share path when the speed gain no longer shows. Answered 2026-09-12: go on.** The user decided to continue with step 6 whatever the timing shows, because every value matches cell for cell on both paths, because a coarser view of a hand-entered triangle already works only on the server, and because the other reasons for the move — one call per formula, no request files, no view files, and the server owning the output location — do not depend on speed. The timing is recorded, not required.

  Both sets of numbers, from [check_gateway_transport.md](../../../excel-addin/tools/check_gateway_transport.md), all on `L-H2MQ6280FVP` on 2026-09-12 with the same add-in package and the same server:

  | Workbook | Share | Server |
  | :--- | :--- | :--- |
  | First run: ten blocks, nine datasets, one class | 0.46 s | 0.60 s |
  | First run: twenty-three annual triangles, one class | 1.03 s | 1.14 s |
  | Second run, case A: twenty-four cached datasets across twelve classes | 1.78 s | 1.46 s |
  | Second run, case B: three datasets the Engine recalculates | 1.74 s | 0.86 s |

  The first run covered one reserving class and only datasets already cached, and there the share was a shade faster. The second run covered the two cases the plan expected the win to come from and the first run did not: across twelve classes the server is about 18% faster, which is less than the spread between passes and so should be read as "at least as fast, probably a little faster"; on datasets the Engine has to calculate the server is about twice as fast, repeatably, because the share pays a request file and a poll loop for what the server answers in one call. Values matched exactly in both runs: 1,332 figures in case A and 297 in case B, none differing, on top of the first run's 566 and 1,104.

## Where the duplication is today

Moving to HTTP is also the removal of four copies of a server-owned rule from the add-in. Naming them here so an implementer does not preserve them out of habit.

| Rule | Canonical owner | Copy in the add-in |
| :--- | :--- | :--- |
| Where a dataset's CSV lives | [set_data_path_like_vba](../../../frontend/app_server/helpers.py#L137) | [BuildDatasetRequestSpec](../../../excel-addin/src_vba/Core.bas#L449) |
| How a name becomes a folder or file name | `encode_filename_segment` in [arcrho_project_duplication_contract.py](../../../python-api/src/arcrho_project_duplication_contract.py), documented in [filename-escaping-rules.md](../../../server-components/docs/filename-escaping-rules.md) | [Core.bas:1041-1069](../../../excel-addin/src_vba/Core.bas#L1041-L1069) |
| Whether a dataset type is Engine-generated | [dataset_type_contract.py](../../../python-api/src/arcrho_api/dataset_type_contract.py) and the project's dataset-type table | [ResolveDatasetRequestMode](../../../excel-addin/src_vba/Core.bas#L629) and the generated-flag cache below it |
| When a coarser view is possible and when it is stale | [materialize_dataset_view](../../../frontend/app_server/services/arcrho_runtime_service.py#L1173) and the runtime's roll-up rules | [DatasetViewStoredFile](../../../excel-addin/src_vba/Core.bas#L791) and [DatasetViewIsStale](../../../excel-addin/src_vba/Core.bas#L843) |

## Code evidence and ownership

- [Core.bas](../../../excel-addin/src_vba/Core.bas): [GetDataset:144-253](../../../excel-addin/src_vba/Core.bas#L144-L253) is the single entry every worksheet function funnels through. It resolves the request mode, derives the CSV path, reuses the file when one exists, otherwise deletes the cache, writes a request file with [SendRequest:1082](../../../excel-addin/src_vba/Core.bas#L1082) and polls with `WaitForFileReady`. [GetDataArray:1254](../../../excel-addin/src_vba/Core.bas#L1254) turns CSV text into the array a formula returns; it takes a path today and is the one piece that must survive unchanged.
- [ArcRhoFunctions.bas](../../../excel-addin/src_vba/ArcRhoFunctions.bas): `ArcoTri:2`, `ArcoVec:192`, `ArcoHeaders:111` and `ArcoProjectSettings:285` call `GetDataset` directly. `ArcoTriDiag:56`, `ArcoTriCell:87`, `ArcoTriOrigin:143` and `ArcoVecCell:224` each re-enter through `ArcoTri` or `ArcoVec`, so a sheet of single-cell formulas fetches the same dataset once per cell. The `ADAS*` aliases from 306 onwards delegate to the same functions and need no change.
- `processedArrays` and `processedCells` are declared in [Core.bas:24-25](../../../excel-addin/src_vba/Core.bas#L24-L25) but populated only by the development helper in [DevScratch.bas](../../../excel-addin/src_vba/DevScratch.bas); the ribbon's refresh loops in [RibbonActions.bas:100-215](../../../excel-addin/src_vba/RibbonActions.bas#L100-L215) fill them through `SearchArcRhoFormulas:261` and refresh a block at a time with `RefreshArcRhoBlock` in [Utilities.bas:249](../../../excel-addin/src_vba/Utilities.bas#L249). There is no cache of dataset contents anywhere.
- [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py): `ENGINE_CALCULATION_KINDS` names the three hosted functions and their exact request-file keys; `OPERATIONS` and `OPERATION_OPTIONS` are the tables a new operation is added to. `SERVER_OWNED_REQUEST_KEYS` is why a client may not name an output path. `DATASET_VIEW_REQUEST_KEY` is deliberately absent from every kind and stays absent.
- [engine_calculation_service.py:182-238](../../../frontend/app_server/services/engine_calculation_service.py#L182-L238): `execute_hosted_engine_calculation` is the one function the Gateway calls, and its operation branches are where a new operation is implemented. [engine_calculations.py](../../../server-components/src/arcrho_gateway/engine_calculations.py) forwards the operation name and needs no change of its own, but the Gateway bundles `frontend/app_server`, so it is redeployed.
- [arcrho_runtime_service.py](../../../frontend/app_server/services/arcrho_runtime_service.py): `run_arcrho_tri:2425` is the whole dataset route. `resolve_local_triangle_cache:996` resolves or derives a triangle and, at [956-981](../../../frontend/app_server/services/arcrho_runtime_service.py#L956-L981), either registers an in-memory roll-up handle or writes the CSV with `pd.DataFrame(values).to_csv(header=False, index=False)`; that call is the parity anchor for the text a hosted answer returns. `materialize_dataset_view:1173` is the producer step 7 removes. `arcrho_headers:1484` already returns values rather than a path.
- [dataset_service.py](../../../frontend/app_server/services/dataset_service.py): `get_dataset:1503` resolves a registered handle, preferring the in-memory roll-up over the file; `load_cached_dataset_values:1941` is the existing hosted read that proved the measurement.
- [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py): `sign_request:102` and `verify_request_signature:127` own the signature; the message is the casefolded user, the Unix timestamp, the method, the path, and the hex digest of the body, joined by newlines. `normalize_client_config:225` owns the client credential file's shape. Skew is 300 seconds, so the add-in must send UTC seconds.
- [main.py](../../../server-components/src/arcrho_gateway/main.py): the HTTP surface. `GET /api/health` and `GET /api/capabilities` are unauthenticated; the four POST paths are signed. Capabilities is how a client discovers whether an operation exists before using it.
- The cross-language pin precedent this plan follows for VBA: [log_retention.js](../../../frontend/electron/log_retention.js) mirrors a Python contract and [log_retention.test.mjs](../../../frontend/tests/log_retention.test.mjs) fails until the mirror follows, as the "Log File Retention" rule in [AGENT_GUIDELINES.md](../../../AGENT_GUIDELINES.md) describes.

## Plan

Ten steps, numbered in the order they were written and run in the order 1 to 7, then 10, then 8 and 9. Steps 1 and 2 are independent of each other and of everything else, and 3 and 4 are independent of 1 and 2; every other step depends on the one before it in that order. Every step that changes a file under `excel-addin/` ends with the build and release scripts from [excel-addin-build-and-release.md](../../../agent-instructions/excel-addin-build-and-release.md), and the "Excel add-in build needs the server clone" memory applies: those scripts cannot run from the Client PC, so a step that cannot run them says so in its commit message and leaves the release to step 9.

Every step that changes user-visible behaviour adds a fragment under `frontend/changes/unreleased/` with scope `excel add-in`, the way [excel_addin_requested_dataset_shape.json](../../../frontend/changes/archive/1.6.0/excel_addin_requested_dataset_shape.json) does.

### Step 1 — One dataset is fetched once per recalculation

**Goal.** A dataset that several formulas ask for during one recalculation is fetched once. This removes most of the add-in's reads on a real workbook and is worth having whichever transport is underneath, so it lands first and independently.

**Read first.** [The question](#the-question), [Code evidence and ownership](#code-evidence-and-ownership). [Core.bas:144-253](../../../excel-addin/src_vba/Core.bas#L144-L253) and [Core.bas:1-60](../../../excel-addin/src_vba/Core.bas#L1-L60) for the module-level state; [ArcRhoFunctions.bas:1-260](../../../excel-addin/src_vba/ArcRhoFunctions.bas#L1-L260); [RibbonActions.bas:60-215](../../../excel-addin/src_vba/RibbonActions.bas#L60-L215) and `SearchArcRhoFormulas` at 261; [Utilities.bas:249-300](../../../excel-addin/src_vba/Utilities.bas#L249-L300); [Excel Add-in Build and Release](../../../agent-instructions/excel-addin-build-and-release.md) and [build_xlam.ps1](../../../excel-addin/tools/build_xlam.ps1), which updates an add-in package that already exists rather than creating one. The `$arcrho-ui-design` skill does not apply; there is no UI change here.

**Do.**

- [x] Add a module-level dictionary in `Core.bas` keyed by the request text `GetDataset` already receives, holding the array it returned. Look it up at the top of `GetDataset` and fill it on every successful return, for all three request modes.
- [x] Clear the dictionary at the start of every full recalculation and every ribbon refresh: the existing entry points in `RibbonActions.bas` already bracket those passes, and `removeData` being on must bypass the cache entirely rather than serve a stale entry.
- [x] Clear it as well when the add-in's own refresh writes a block, so a refreshed dataset is not served from the pass that preceded it.
- [x] Leave the two file-freshness caches for the dataset-type table and the class index exactly as they are; they are removed in step 6 along with the rest of the share path.
- [x] Bump `ARCRHO_VERSION` in [Core.bas:4](../../../excel-addin/src_vba/Core.bas#L4). Note in the commit message that this resets each user's saved add-in settings, because [LoadConfig](../../../excel-addin/src_vba/Core.bas#L317) deletes a config file whose version differs.

**Tests.** No automated harness covers VBA, so the check is a recorded manual one. Add `excel-addin/tools/check_dataset_cache.md` describing the two-minute check: a sheet with one array formula and twenty single-cell formulas over the same triangle, the add-in's debug output on, and the count of dataset fetches before and after. Record the two counts in the commit message and in the Progress row.

**Done when.** A sheet of twenty single-cell formulas over one triangle fetches that triangle once per recalculation instead of twenty times, a ribbon refresh still picks up an edited dataset, and turning the "always refresh" setting on still bypasses every cache.

### Step 2 — The add-in can sign and send one Gateway request

**Goal.** A new VBA module finds the user's credential, signs a request the way the server verifies it, and posts it. Nothing in the add-in uses it yet, and a check the implementer can run proves the signature matches the server's.

**Read first.** [What was proven](#what-was-proven), [Decisions](#decisions) item 1. [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py) (whole file); [main.py:490-560](../../../server-components/src/arcrho_gateway/main.py#L490-L560) for the paths and headers; [Core.bas:1018-1040](../../../excel-addin/src_vba/Core.bas#L1018-L1040) for the existing UTF-8 file helpers and [Json.bas](../../../excel-addin/src_vba/Json.bas) for the parser already in the add-in; [log_retention.test.mjs](../../../frontend/tests/log_retention.test.mjs) as the pinning pattern to copy. The "Python test runner" memory: pytest lives in the repo-local `.pytest-tools`.

**Do.**

- [x] Add `excel-addin/src_vba/GatewayClient.bas`: read and cache the credential file from `%APPDATA%\ArcRho\arcrho_gateway.json`, treating a missing or disabled file as "no gateway"; UTF-8 bytes through `ADODB.Stream` skipping the byte-order mark; SHA-256 and HMAC-SHA256 hex through the late-bound .NET classes with hex via the `bin.hex` node; UTC Unix seconds through `WbemScripting.SWbemDateTime`; one `POST` through `WinHttp.WinHttpRequest.5.1` returning status and body. Reuse one request object across calls so the connection is not rebuilt per formula.
- [x] Give the module one public entry that takes a path, a body, and a timeout and answers with status and text, plus a public check routine that signs the fixed vector below and reports whether it matches.
- [x] Add `excel-addin/tools/verify_gateway_signing.vbs`: the same helpers standalone, printing the digest and signature for the fixed vector, so the check can be run without opening Excel. Keep the expected values in one named constant block at the top of the file.
- [x] Add a health and capabilities call to the module so later steps can ask whether an operation is advertised before using it.

**Tests.** New `frontend/tests/test_excel_addin_gateway_signing.py`: derive the digest and signature for the fixed vector from `arcrho_hosted_save_http_contract`, read the same named constant block out of both `GatewayClient.bas` and `verify_gateway_signing.vbs`, and assert the two blocks agree with each other and with the contract, so a change on any side fails. Pin the route and header names the add-in has to spell out for itself there too, and record the manual run in `excel-addin/tools/check_gateway_signing.md`. Use the vector proved on 2026-09-12: secret `probe-secret-value`, user `XWei`, timestamp `1757650000`, method `POST`, path `/api/workspace-reads`, body `{"Function":"ArcRhoWorkspaceRead","Name":"Net Loss--Paid é"}`, giving digest `bede0538b3ba1824f3572ce81a492868099b0bfc4ba90b1ce9c105cb3cfc5656` and signature `3a81facfc86c05784d7978f8a2f2de06b6172b513c9f75d496777aff6008d2d0`.

**Done when.** The new test passes, the standalone script prints those two values on a Client PC, and the check routine run from Excel reports a successful capabilities call against the live Gateway.

### Step 3 — The server answers a dataset request with its figures

**Goal.** One hosted operation takes the add-in's logical dataset request and answers with the CSV text the add-in would have read, resolving the cache, rolling a coarser view up in memory, and running the Engine only when needed.

**Read first.** [Decisions](#decisions) items 2 to 5, [Code evidence and ownership](#code-evidence-and-ownership). [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py) (whole file); [engine_calculation_service.py:150-260](../../../frontend/app_server/services/engine_calculation_service.py#L150-L260); [arcrho_runtime_service.py:900-1000](../../../frontend/app_server/services/arcrho_runtime_service.py#L900-L1000) (the materialize-or-register branch), `resolve_local_triangle_cache:996`, `materialize_dataset_view:1173`, `run_arcrho_tri:2425`; [dataset_service.py:1503-1535](../../../frontend/app_server/services/dataset_service.py#L1503-L1535); [test_arcrho_router_hosted_operations.py](../../../frontend/tests/test_arcrho_router_hosted_operations.py), [test_manual_dataset_rollup_view.py](../../../frontend/tests/test_manual_dataset_rollup_view.py), [test_engine_calculation_in_process.py](../../../frontend/tests/test_engine_calculation_in_process.py). Memories: "Method precision: observed, not projected", "Engine stored lengths are source granularity", "origin_length is NOT the row count". AGENT_GUIDELINES "Single Source of Truth" and "Minimal Diff".

**Do.**

- [x] Add one operation to `OPERATIONS`, to `OPERATION_OPTIONS`, and to the `operations` tuple of the `ArcoTri` and `ArcoVec` kinds in the contract. Its options are the run's existing `force_refresh`, `local_only` and `allow_derived`; it accepts no output variant other than the canonical one and no session id, and `DATASET_VIEW_REQUEST_KEY` stays absent from every kind. Landed as `dataset_csv`, with the answer's field name owned by the contract as `ENGINE_CALCULATION_CSV_FIELD`.
- [x] Add a service function in `arcrho_runtime_service.py` that derives the path with the canonical builder, runs the dataset route, then produces the text: from the registered in-memory roll-up when one exists, otherwise from the resolved file. Serialize with the same `pd.DataFrame(values).to_csv(header=False, index=False)` call the materializing branch uses, into a string buffer, so the text cannot differ from the file's. The resolved file's own text is returned verbatim rather than round-tripped through `pandas`, which would respell `100` as `100.0`.
- [x] Branch to it from `execute_hosted_engine_calculation`, returning the run's own status fields alongside the text so a failure still reports why, and never writing a view file on this path.
- [x] Confirm a hand-entered triangle asked for at a coarser shape is answered from the in-memory roll-up with no file appearing in the class's view folder.
- [x] Decided while implementing: the operation runs the route with `write_sidecar` false, like the method loaders, so reading a figure in a worksheet records only the technical cache provenance and never restates a dataset's record or starts a dependent walk. It is not an option a client can set.

**Tests.** `python-api/tests` gains the contract cases: the new operation is accepted for both dataset functions and refused for the headers function, its option table rejects an unlisted option, and a request naming a server-owned key or the view key is still refused. `test_arcrho_router_hosted_operations.py` gains: the operation returns text for a cached triangle; the text is byte-identical to the file the same request writes through the existing run; a generated dataset that needs the Engine returns the run's failure status and no text when the Engine does not answer. `test_manual_dataset_rollup_view.py` gains a coarser-shape case asserting the text matches the materialized view byte for byte and that no file was created.

**Done when.** For a stored triangle, a coarser view of a hand-entered triangle, and a generated dataset, the hosted operation's text equals the CSV the share path produces byte for byte, and the coarser case writes nothing to disk.

### Step 4 — The server answers headings and project settings the same way

**Goal.** The period-heading and project-settings formulas can be served over HTTP too, so no worksheet function is left needing the share.

**Read first.** [Decisions](#decisions) item 2. [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py) `ENGINE_CALCULATION_KINDS`; [arcrho_runtime_service.py:1484-1560](../../../frontend/app_server/services/arcrho_runtime_service.py#L1484-L1560) (`arcrho_headers`); [arcrho_router.py:108-135](../../../frontend/app_server/api/arcrho_router.py#L108-L135); [ArcRhoFunctions.bas:111-142](../../../excel-addin/src_vba/ArcRhoFunctions.bas#L111-L142) and [ArcRhoFunctions.bas:285-292](../../../excel-addin/src_vba/ArcRhoFunctions.bas#L285-L292) for what the two formulas expect back; [Core.bas:583-590](../../../excel-addin/src_vba/Core.bas#L583-L590) for the unscoped request path they use; [test_arcrho_router_hosted_operations.py](../../../frontend/tests/test_arcrho_router_hosted_operations.py) and [test_engine_calculations.py](../../../server-components/tests/test_engine_calculations.py), whose advertised-function list is a pin a new kind moves. Step 3 must be committed first, because this reuses its operation.

**Do.**

- [x] Extend the headings kind with the step 3 operation, served by the existing headings service, which already answers with values rather than a path.
- [x] Register the project-settings function as a hosted kind with its exact request-file keys, no reserving class, the canonical output variant only, and the step 3 operation. Its keys are `Function` and `ProjectName`, the only two the Engine's handler reads.
- [x] Return both as the same text field step 3 defined, so the add-in has one answer shape to parse. The headings answer keeps its labels beside the text, so the app's own route is unchanged.
- [x] Decided while implementing: the project-settings table is served by a new `arcrho_project_settings` in the runtime service, which reuses the cache beside the project data until the project's general settings are saved again. That staleness rule was already the headings cache's and is now shared between them, because both CSVs are derived from the project's origin and development dates. The operation's `force_refresh` drops either cache before the read, so the add-in's "always refresh" reaches them; `local_only` and `allow_derived` describe a dataset route and do not apply.

**Tests.** `python-api/tests`: both kinds accept the operation and refuse an unlisted key. `test_arcrho_router_hosted_operations.py`: the headings answer matches the existing route's values for the same request, and the project-settings answer matches the CSV the share path produces.

**Done when.** All four worksheet functions have a hosted answer, and each one's text matches what the share path produces for the same request.

### Step 5 — Formulas read through the Gateway

**Goal.** With a credential present, every worksheet function gets its figures from the Gateway. The share path stays in place for a user without a credential until step 6 removes it.

**Read first.** [Decisions](#decisions) items 1, 3, 4 and 6; [Where the duplication is today](#where-the-duplication-is-today). [Core.bas:144-253](../../../excel-addin/src_vba/Core.bas#L144-L253), [Core.bas:443-600](../../../excel-addin/src_vba/Core.bas#L443-L600), [Core.bas:1254-1310](../../../excel-addin/src_vba/Core.bas#L1254-L1310); `GatewayClient.bas` from step 2; [ArcRhoFunctions.bas](../../../excel-addin/src_vba/ArcRhoFunctions.bas); [Json.bas](../../../excel-addin/src_vba/Json.bas); [ufSettings.frm](../../../excel-addin/src_vba/ufSettings.frm) and [Core.bas:317-442](../../../excel-addin/src_vba/Core.bas#L317-L442) for how a setting is stored. Steps 1 to 4 must be committed. Added while implementing: [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py) `build_engine_calculation_request` for the exact request body the add-in has to write by hand, and [main.py:600-635](../../../server-components/src/arcrho_gateway/main.py#L600-L635) for what a refusal answers with; [component-deployment-authorization.md](../../../agent-instructions/component-deployment-authorization.md), because steps 3 and 4 are not live until the Engine and the Gateway are redeployed and nothing in this step can be checked before that.

**Do.**

- [x] Split `GetDataArray` so the text-to-array conversion is a function taking text, and have the existing path read the file and call it. Nothing about the conversion changes.
- [x] In `GetDataset`, when the Gateway is configured and advertises the operation, build the logical pairs from the request text, post one call, and convert the returned text. Send no path, no user name and no view key; the server owns all three.
- [x] Carry a failure through as the message the server gave, not as a file-not-found, so a user sees why. Keep the existing loading indicator around the call.
- [x] Reuse the step 1 cache for the HTTP answers unchanged, so the two paths cache identically.
- [x] Add one setting that forces the share path, defaulting to off, for diagnosing a difference between the two. Bump `ARCRHO_VERSION` so the setting reaches existing users.
- [x] Add a change fragment under `frontend/changes/unreleased/`.

**Tests.** Manual, recorded: add `excel-addin/tools/check_gateway_transport.md` describing the comparison. One workbook covering an array triangle, a single cell, a diagonal, a vector, headings and project settings, evaluated with the force setting on and off, values compared cell by cell, and the elapsed time of a full recalculation recorded for both. Put the two times and the comparison result in the commit message and the Progress row.

**Done when.** Every cell of the check workbook holds the same value on both paths, and the elapsed time of a full recalculation each way is recorded in [check_gateway_transport.md](../../../excel-addin/tools/check_gateway_transport.md). The timing is recorded rather than required: the move does not depend on it, as the answered decision above sets out.

### Step 6 — The add-in stops reading project data from the share

**Goal.** Delete the share path and the four copied rules with it, so the add-in reaches project data only over HTTP and a missing credential is an explicit, readable failure.

**Read first.** [Decisions](#decisions) items 4, 6 and 7; [Where the duplication is today](#where-the-duplication-is-today); the "Server-Hosted Project Data I/O" rule in [AGENT_GUIDELINES.md](../../../AGENT_GUIDELINES.md); the [Open decisions](#open-decisions) entry, which must be answered before step 9 but not before this step. [Core.bas](../../../excel-addin/src_vba/Core.bas) whole file; [Utilities.bas:140-190](../../../excel-addin/src_vba/Utilities.bas#L140-L190) (`WaitForFileReady`); [RibbonActions.bas:60-215](../../../excel-addin/src_vba/RibbonActions.bas#L60-L215). Step 5 must be committed and its comparison recorded.

**Do.**

- [ ] Remove from `Core.bas`: the request-mode resolution and the dataset-type generated-flag cache, the class-index cache and the coarser-view naming and staleness checks, the path building and the project, class and file-name escaping, the request-file writer and its JSON helpers, and the folder creation and cache deletion the share path needed.
- [ ] Remove `WaitForFileReady` and the force-the-share setting added in step 5, together with the config key and its control.
- [ ] Replace a missing or disabled credential with one clear message naming what to do, not a file path.
- [ ] Keep `ProductRootPath` and `ProductPath`: the add-in itself, the reserving-class input CSV, the version-track document and the team profile workbook still live on the share and are not project data.
- [ ] Confirm no remaining reference in `excel-addin/src_vba/` opens anything under a project's data folder.
- [ ] Bump `ARCRHO_VERSION` and add a change fragment.

Two things the checklist above did not foresee, found while confirming that last point and done in the same step:

- [x] The **Select Datasets** window read the project's dataset-type table off the share, which is the only other thing in `src_vba/` that opened a project folder and the only reason the project file-name escaping was still there. A `project_dataset_types` workspace read was registered in [arcrho_workspace_read_contract.py](../../../python-api/src/arcrho_workspace_read_contract.py) and the form now asks the Gateway for it, so Bridge, Engine and Gateway are redeployed by this step too.
- [x] `ArcoTriCell`, `ArcoTriDiag`, `ArcoTriOrigin` and `ArcoHeaders` assumed `ArcoTri` had returned an array and silently turned a refusal into `0` or `#VALUE!`. Without that fix a PC with no credential shows a blank rather than the message this step adds, so each now passes a non-array answer straight through.

**Tests.** Manual, recorded: re-run the step 5 check workbook and confirm every value is unchanged. Then rename the credential file aside and confirm every formula reports the new message rather than a path or a blank, and restore it. Record both in the commit message.

**Done when.** Nothing under `excel-addin/src_vba/` touches a project data folder, the check workbook's values are unchanged from step 5, and a user without a credential gets one readable message.

### Step 7 — The coarser-view files stop being written

**Goal.** With no worksheet formula reading a CSV any more, the one producer that materializes a coarser view of a hand-entered dataset is removed, along with the Engine handler and the request key that reached it.

**Read first.** [Decisions](#decisions) item 5; the commit that added this producer, `21d2cda9`. [arcrho_runtime_service.py:1173-1200](../../../frontend/app_server/services/arcrho_runtime_service.py#L1173-L1200) and the `write_input_view` and `materialize_path` arguments of `resolve_local_triangle_cache:996`; [main.py:470-530](../../../server-components/src/arcrho_engine/main.py#L470-L530) for the Engine's view handler and the branch that reaches it; `DATASET_VIEW_REQUEST_KEY` in [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py); [test_manual_dataset_rollup_view.py](../../../frontend/tests/test_manual_dataset_rollup_view.py); [arcrho.md](../../../frontend/docs/app_server/domains/arcrho.md). Step 6 must be committed, because the share path is the only remaining caller. Memory: "Deploy staleness is mtime-based".

**Do.**

- [x] Remove the view materializer, the Engine handler that calls it, and the request key from the contract.
- [x] Keep the `write_input_view` behaviour of `resolve_local_triangle_cache` only if another caller uses it; if the materializer was its only caller, remove that argument too. It was the only caller, so the argument is gone from both `resolve_local_triangle_cache` and `_derive_triangle_cache`.
- [x] Leave the in-memory roll-up handle and its registration untouched: that is how both the app and, since step 3, Excel get a coarser view.
- [x] Delete any leftover view folders the old path created under the fake project only, and say in the commit message that live projects keep theirs until someone clears them.
- [x] Update the arcrho domain doc to say a coarser view is never materialized.

One thing the checklist above did not foresee, done in the same step:

- [x] The contract test that pinned the refusal imported the key by name, so it could not survive the key's removal. It now asserts the contract no longer defines the key and refuses a request naming it as the unknown key it has become, and `test_manual_dataset_rollup_view.py` pins the exact text a worksheet formula receives rather than comparing it against a file it no longer writes.

**Tests.** `test_manual_dataset_rollup_view.py` keeps its in-memory cases and loses the materializing ones. Add a case asserting a request carrying the removed key is refused by the contract, in [test_engine_calculation_dataset_csv_contract.py](../../../python-api/tests/test_engine_calculation_dataset_csv_contract.py).

**Done when.** No code path writes a dataset view file, a coarser view still comes back correct in the app and over the hosted operation, and the removed key is refused.

### Step 8 — A user can set Excel up and read a failure

**Goal.** One short page tells a user what Excel needs in order to reach the server, and what each failure message means.

**Read first.** The answered credential decision under [Answered decisions](#answered-decisions); `GatewayClient.bas` and the messages written in steps 5 and 6; [excel-addin-build-and-release.md](../../../agent-instructions/excel-addin-build-and-release.md). Steps 6, 7 and 10 must be committed, so the messages are final.

**Do.**

- [x] Write `excel-addin/README.md` covering: what the credential is, where it lives, that the add-in installs it on its own the first time it runs and what to do on the rare PC where that fails, how to run the check routine, every failure message the add-in can now show with its cause, and the three check documents from steps 1, 5 and 10. All four check documents are listed, since the signing check from step 2 is the one a user runs when a PC cannot reach the server.
- [x] Link it from the plans index row and from the arcrho domain doc.
- [x] Note the shared library files that still come from the share, so nobody concludes the add-in needs no drive mapping at all.

**Tests.** None; this step changes no behaviour. Confirm every message the page lists appears verbatim in the sources. Done by joining each source file's continued string literals and searching for the page's exact wording: all twenty-five quoted strings and paths were found, none missing.

**Done when.** The page names every failure message the add-in can produce, and each one is findable in the sources by the exact wording the page uses.

### Step 9 — Release and check against a real workbook

**Goal.** The change reaches the server and one real workbook is checked against it.

**Read first.** The answered credential decision under [Answered decisions](#answered-decisions); [excel-addin-build-and-release.md](../../../agent-instructions/excel-addin-build-and-release.md); [component-deployment-authorization.md](../../../agent-instructions/component-deployment-authorization.md); memories "Excel add-in build needs the server clone", "Remote component deploy", "Deploy staleness is mtime-based", "Bridge restart after deploy". Every earlier step committed.

**Do.**

- [x] Deploy the server components the contract and app-server changes made stale, derived by the deploy CLI rather than by hand. The release-packaging fix landed 2026-09-13 (`af652326`), assembling the release beside the beta copy instead of editing it in place on the share, so a server holding the file no longer blocks a release.
- [x] Build and release the add-in from the server clone, since the beta workbook and signature files exist only there. Released 2026-09-13.
- [x] Check that a PC with no credential sets itself up: on one machine that has never been provisioned, open the released add-in and confirm a formula returns figures without anyone running a command. Nobody is provisioned by hand.
- [x] Check one real workbook a user already relies on. Checked 2026-09-13 against the released add-in: it works as expected.
- [x] Move this plan to `completed/` and update the plans index, as [README.md](../README.md) describes.

**Tests.** The full frontend and Python suites before the release, compared against a stash in the same tree rather than a fresh worktree, per the "Worktree baselines mask new failures" memory.

**Done when.** The components are deployed, the add-in is released, every PC that opens the workbook has set itself up, and one real workbook returns the same values faster than before.

### Step 10 — The add-in gives its own PC a credential on first run

**Goal.** This step runs after step 7 and before steps 8 and 9; it carries the next free number only because steps 1 to 7 were already committed when it was added. The first time the add-in loads on a PC with no Gateway credential, it installs one for the logged-in Windows user, so an Excel-only user is never set up by hand and never meets the "no credential" message that step 6 wrote.

**Read first.** The answered credential decision under [Answered decisions](#answered-decisions); [Decisions](#decisions) items 1 and 7. [hosted_save_enrollment.py](../../../python-api/src/arcrho_api/hosted_save_enrollment.py) (whole file — `provision_gateway_user` is the canonical enrollment and must stay the only one); [hosted_save_enrollment_service.py](../../../frontend/app_server/services/hosted_save_enrollment_service.py), which holds the "enroll once" policy the desktop app has used since the hosted-save pilot; [configure_pilot.py](../../../server-components/src/arcrho_gateway/configure_pilot.py); [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py) `normalize_client_config:225` and `normalize_gateway_config:170` for the two file shapes; [GatewayClient.bas:483-499](../../../excel-addin/src_vba/GatewayClient.bas#L483-L499) (`EnsureGatewayConfig`) and [ThisWorkbook.cls](../../../excel-addin/src_vba/ThisWorkbook.cls); [Core.bas:64-95](../../../excel-addin/src_vba/Core.bas#L64-L95) for `ProductRootPath`, which is already the workspace root; [RibbonActions.bas:452-463](../../../excel-addin/src_vba/RibbonActions.bas#L452-L463), where the add-in already runs an executable from the share; [arcrho_build_components.py:133-175](../../../server-components/src/arcrho_build_components.py#L133-L175) and [utils.py:67-79](../../../server-components/src/utils.py#L67-L79) for how a role joins the deployed set; [build_exe.py](../../../server-components/src/arcrho_gateway/build_exe.py) as the build script to copy, together with [the Launcher's](../../../server-components/src/arcrho_launcher/build_exe.py) pinned-folder fallback and [test_component_deploy_swap_safety.py](../../../server-components/tests/test_component_deploy_swap_safety.py), which requires every deployed role either to stop its own process or to recover from a rename Windows refuses; [component-deployment-authorization.md](../../../agent-instructions/component-deployment-authorization.md); [excel-addin-build-and-release.md](../../../agent-instructions/excel-addin-build-and-release.md). Steps 6 and 7 must be committed. Memory: "Excel add-in build needs the server clone".

A running build listener validates a requested role against its own frozen copy of the deployed set, so it rejects a role added in the same change. Deploy the existing components through the listener and build this one from the client with `ARCRHO_DEPLOY_ROOT` set, as the fallback in [AGENT_GUIDELINES.md](../../../AGENT_GUIDELINES.md) describes.

Three facts settle the shape of this step, and an implementer should not re-litigate them.

- **The share is the authentication.** A credential is created by adding the user's secret to `<workspace>\config\arcrho_gateway.json` and writing the matching file to `%APPDATA%\ArcRho\arcrho_gateway.json`. Both happen on the client, over the share, under the user's own Windows account, which is how the server can be sure who asked. The Gateway itself cannot tell: it is plain HTTP with no Windows authentication, so an enrollment route there would hand a secret to anything that could reach the port. No such route is added.
- **The registry write does not happen in VBA.** `provision_gateway_user` updates the shared file under an OS byte-range lock. A VBA file lock does not interlock with it, so a losing write would silently drop another user's entry and lock that person out, and it would be a second copy of a rule the "Single Source of Truth" section of [AGENT_GUIDELINES.md](../../../AGENT_GUIDELINES.md) says must have one owner.
- **So a small frozen helper does the work and VBA only starts it.** The helper is the canonical Python, built and deployed by the machinery every other component uses. The add-in already starts an executable from the share, so this is an established pattern here rather than a new one.

**Do.**

- [ ] Move the "enroll once" policy out of `hosted_save_enrollment_service.auto_enroll_current_user` and into `arcrho_api.hosted_save_enrollment`, keeping every rule it already has: an existing local file is authoritative including an explicit `enabled: false`, the shared `client_url` is read and probed before anything is written, and a failure before enrollment leaves no file. The app-server service becomes a thin caller. This removes a duplication rather than creating one; do not let the new helper grow a second copy of the policy.
- [ ] Add `server-components/src/arcrho_credential/` with a `main.py` that calls that one function and a `build_exe.py` modelled on the Gateway's. It takes the workspace root as an argument, because an Excel-only PC may have no `workspace_paths.json` to resolve one from. It prints one line saying what it did and exits non-zero on failure.
- [ ] Register `credential` in `DEPLOYED_COMPONENT_ROLES` only, the way `gateway` is: it is deployed from the repository and is not part of the installed server payload. Give it no instance role, as the Launcher has none, so it writes no heartbeat and the Orchestrator does not supervise it.
- [ ] Fix the URL default while moving this code: `configure_pilot.py` falls back to `http://<this machine's name>` when `--url` is absent, which is the client's own name when it runs on a Client PC. The shared registry's `client_url` is the only correct answer, so pass nothing and let `provision_gateway_user` use it. Keep `configure_pilot.py` working for a person at the Server PC; it delegates to the same function.
- [ ] In the add-in, at `Workbook_Open` and nowhere inside a worksheet function, check for the local credential file and run the helper once per Excel session when it is missing. The helper is `ProductPath("apps\ArcRho Credential\ArcRho Credential.exe")` and it is handed `ProductRootPath()` as the workspace root, so no path is written out in VBA. Run it hidden and wait for it, and put the reason in the existing loading indicator so a user sees why Excel paused. Clear the module's cached "no gateway" answer afterwards so the first formula of that session sees the new credential.
- [ ] Attempt this at most once per Excel session, and never when the workspace share cannot be reached, so a PC that is off the network pays one short failure rather than one per launch.
- [ ] Leave the step 6 message exactly as it is for every case that still fails, and leave an `enabled: false` file untouched: that file is a deliberate opt-out, not a missing credential.
- [ ] Do not bump `ARCRHO_VERSION`. This step adds no setting, and a bump would reset every user's saved add-in settings for nothing.
- [ ] Confirm a plain user can run the helper from `apps\ArcRho Credential` on the share with no warning dialog. If Windows blocks an executable opened from the share, say so in the commit message and leave step 9 to sign it with the certificate the add-in release already uses.
- [ ] Add a change fragment under `frontend/changes/unreleased/` with scope `excel add-in`.
- [ ] Deploy the components the deploy CLI reports stale, which includes the new helper, and say which in the commit message. Build the add-in with `build_xlam.ps1`; the release stays with step 9.

**Tests.** `frontend/tests/test_hosted_save_auto_enrollment.py` keeps passing unchanged against the service that now delegates, which is the proof the policy moved rather than changed. New `python-api/tests/test_gateway_credential_helper.py`: against a temporary workspace root and a temporary `%APPDATA%`, the helper writes a file `normalize_client_config` accepts for a user the shared registry then holds; it takes the shared `client_url` rather than one built from the local machine name; it leaves an existing `enabled: false` file untouched and reports that it did; and it exits non-zero without writing anything when the shared registry has no `client_url`. `server-components/tests`: the new role is in the deployed set, is absent from the installed payload, and owns no instance role. Manual, recorded in `excel-addin/tools/check_first_run_credential.md`: rename the credential aside, open Excel, and confirm it comes back and a triangle formula returns figures with no command run by hand; then make the share unreachable and confirm one short failure, the step 6 message, and no hang.

**Done when.** Opening Excel on a PC that has never had a credential installs one and the add-in's formulas work, with nobody running a command; an `enabled: false` file is still honoured; every remaining failure leaves the step 6 message and a usable Excel; and no secret can be obtained from the Gateway by a caller that only reaches its port.

## Rough size

Ten sessions, one per step. Steps 1, 2, 3, 5 and 10 are the substantial ones; 4, 7 and 8 are short; 6 is mostly deletion; 9 is a release and a measurement. Steps 1 and 2 can run in parallel with 3 and 4, because the first two touch only the add-in and the second two only the server. Step 10 is substantial because it spans three trees — the canonical enrollment in `python-api`, a new small component in `server-components`, and the add-in's first-run path — even though each piece is small.
