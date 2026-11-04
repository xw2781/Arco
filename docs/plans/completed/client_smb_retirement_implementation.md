# Client SMB Retirement: Completed Implementation and Server Deployment

Status: Implementation and server-deployment portions completed through 2026-09-29. This record preserves the original steps, decisions, timing and validation, plus the six audit fixes. It does not claim that the desktop release or macro publication is complete; outstanding work is tracked only in the [remaining plan](../client_smb_retirement.md).
Last updated: 2026-09-29

The source changes were committed and pushed as `6b063a7f` (implementation) and `8b9e1982` (documentation). Production build `build-260929-171549-507-xwei` deployed Bridge, Engine, Gateway and Credential; health, active instances and new Gateway capabilities were verified. Earlier production deployments and the ArcBot prompt update were also verified.

The dated step notes below are implementation history, including the original future-tense instructions. Their references to a later release are historical context, not a second rollout checklist. The active plan is the authority for remaining work.

## Progress

Completed implementation and server-deployment portions of the original steps. Client rollout was split into the remaining plan.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Applying a ResQ bridge change saves on the server like any other save | [x] | 2026-09-26 | 50 min | 8 min | "Update local from ResQ" in a DFM now saves on the server, under the same protection as the page's own Save. |
| 2 | Bootstrap refresh, dataset notes and new empty datasets save on the server | [x] | 2026-09-27 | 60 min | 21 min | Refreshing a Bootstrap method, saving dataset notes and creating an empty dataset now save on the server, under the same protection as a page's own Save. |
| 3 | Audit log entries from two PCs can no longer overwrite each other | [x] | 2026-09-27 | 45 min | 41 min | The project audit log is read and written on the server, so entries saved from two PCs at once no longer overwrite each other. |
| 4 | ArcBot edits go through the normal save instead of writing files directly | [x] | 2026-09-27 | 70 min | 28 min | ArcBot's edits now land in the open page and save through its normal Save; "revert the latest ArcBot edit" undoes it in that page, and no backup files are written next to the method. |
| 5 | Editing a method file by hand no longer writes around the save | [x] | 2026-09-27 | 35 min | 18 min | "Open DFM JSON" now shows the method read only, loaded from the server; it cannot be saved there, so a method changes only through its DFM page. |
| 6 | Deploy the server side of steps 1-3 | [x] | 2026-09-27 | 20 min | not recorded | Production deployment confirmed by build records in the September 29 audit. |
| 7 | Project configuration pages load from the server | [x] | 2026-09-27 | 70 min | 23 min | Project Settings, the project pickers and the name on the Home page now load from the server, and opening the rules page no longer copies the source table or rebuilds its value list; Import Data does that. |
| 8 | Reserving-class pickers and filters load and save through the server | [x] | 2026-09-27 | 70 min | 28 min | The reserving-class picker, its filters, hidden paths and favorites, and your per-project preferences now load and save on the server; clearing a filter level or your last favorite now stays cleared. |
| 9 | Dataset and method side panels load from the server | [x] | 2026-09-27 | 65 min | 17 min | A dataset's details panel, the live preview of the datasets that depend on an unsaved edit, a DFM's dataset cell references, the % Developed comparison curve and the development pattern BF and Cape Cod read now load from the server. |
| 10 | "Changed by someone else" alerts stop firing on your own saves | [x] | 2026-09-27 | 55 min | 26 min | The "Updated Outside This Window" alert and the Project Instance "Refresh Table" button now check with the server, so your own saves no longer set them off, and they stay quiet while the server cannot be reached. |
| 11 | Calculations hand back their results directly instead of via the shared drive | [x] | 2026-09-27 | 60 min | 25 min | A calculation's result and a project's period headings now come straight back from the server instead of through the shared drive, so datasets that need recalculating open faster. |
| 12 | Deploy the server side of steps 7-11 | [x] | 2026-09-28 | 20 min | not recorded | Production Gateway, Engine and Bridge deployments confirmed; no need to repeat the historical deployment. |
| 13 | Project folder create, rename, delete and settings saves run on the server | [x] | 2026-09-27 | 75 min | 25 min | Creating, renaming and deleting a project, saving the project list and General Settings, and clearing generated dataset files now run on the server, and a change whose answer is lost on the network is never applied twice. |
| 14 | Dataset-type changes and project copies are submitted and tracked through the server | [x] | 2026-09-27 | 60 min | 27 min | Saving dataset types and copying or cancelling a project copy now go through the server, and while the server cannot be reached the progress window keeps waiting instead of reporting a failure. |
| 15 | Field mapping, source profile and reserving-class refresh run on the server | [x] | 2026-09-27 | 70 min | 27 min | Saving the field mapping, the import settings and the reserving class types now happens on the server, and Import Data no longer copies a shared source file through your PC when the server's import cannot run; uploading a source only your PC can read moved to step 22. |
| 16 | Shared macros, ArcBot prompts and the ResQ import request go through the server | [x] | 2026-09-27 | 60 min | 46 min | The Macro Library, the automatic macro updates and ArcBot's shared prompts now load from the server, ArcBot no longer creates prompt files on the server, and the ResQ import macro hands its request to the server once an app release carries that. |
| 17 | Deploy the server side of steps 13-16 | [x] | 2026-09-29 | 20 min | not recorded | Server deployment and capabilities verified; macro rollout is tracked in the remaining plan. |
| 18 | The app stops falling back to the shared drive when the server is unreachable | [x] | 2026-09-27 | 75 min | 51 min | Arco now needs the server: while it cannot be reached every page says "The server can't be reached" instead of reading the shared drive, a sign-in the server no longer accepts asks you to sign in again, and data processing rules save only through the server's Engine. |
| 19 | Old shared-drive save path and leftover dead code removed | [x] | 2026-09-27 | 55 min | 42 min | Every save now goes through the server, saving default number formats in Preferences works again and is done on the server, and the Dataset Viewer's reserving class list shows the classes the project's data holds. |
| 20 | Signing up to the server no longer needs the shared drive | [x] | 2026-09-27 | 90 min | 35 min | A new PC signs in to the server with your Windows account and receives only your own credential; the Server Connection dialog and Add Server ask for the server's address. Production Gateway and Credential deploy verified; a fresh Windows-profile check remains. |
| 21 | Running the test suites can never reach a real server | [x] | 2026-09-27 | 50 min | 34 min | Running the test suites on a developer PC can no longer read from or write to a real server. |
| 22 | Importing a source only your PC can read uploads it to the server | [x] | 2026-09-27 | 110 min | 36 min | Import Data now uploads a SQL Server table or a CSV only your PC can open to the server, which writes the project table; the progress window shows how much has been sent, an interrupted CSV upload picks up where it stopped, and a failed upload never replaces the table already there. |
| 23 | A PC whose sign-in the server refuses can sign in again from the app | [x] | 2026-09-27 | 40 min | 18 min | When the server refuses this PC's sign-in, "Sign in again" beside the message or on the server in the Server tab signs you in with your Windows account, and the next request works without restarting Arco. |
| 24 | ArcBot reads project data only through the server | [x] | 2026-09-27 | 50 min | 32 min | ArcBot now reads other methods, datasets and reserving classes of your project through the server, signed in as you, instead of browsing the shared drive; it can no longer open raw CSV files or list project folders. |

The implementation and server-deployment portions of all 24 original steps are complete. The unpublished macro portion of step 17 was split into the remaining plan. Six subsequent audit fixes are recorded below. Estimated 1,375 min, actual so far 608 min. Step 21 was added 2026-09-27 and ran before any production deploy. Step 22 was added 2026-09-27 (split from step 15) and fits before step 17. Step 23 was added 2026-09-27 after step 18 and must land before the app release that carries step 18. Step 24 was split from step 19 on 2026-09-27 and ran once decision 7 was taken the same day.

## September 29 follow-up

The audit findings are verified in source. The user approved all six fixes and explicitly declined a general Arcode editing restriction.

| Item | Source change | Validation / rollout |
| --- | --- | --- |
| Project Instance Help JSON | Pass a logical method/sidecar identity to a Gateway-loaded read-only view. | Ordinary Arcode file saves remain enabled; source tests cover both behaviors. |
| Active DFM macros | Build the draft from the captured page payload without opening or statting the share; explicit saves use the hosted DFM save. Notes and project settings load through registered reads. | Test a refused save and prohibit client file access. |
| Dataset grid handles | Send the registered CSV's relative location with the handle; the server confines it to the named project's data folder. Remove client read fallback. | Test an unknown handle after Gateway restart and reject paths outside that project. |
| ResQ review macro | Publish the request through the Gateway into the existing Bridge sync queue. | New mutation kind requires server deploy and compatible app before publishing macro 1.2.0. |
| Batch ResQ import macro | Read the existing-class inventory on the server, preserving counts and classes without indexes. | New read kind requires server deploy and compatible app before publishing macro 1.10.1. |
| Add Server | Store and inspect the folder alias without filesystem validation; enrollment and health checks use HTTP. Avoid resolving the project share during startup. | Test a profile whose share is unmounted. |

Validation completed: 163 focused Python tests and five Node tests passed. The Node tests include an ordinary Arcode file save alongside the read-only Project Instance preview. A private Engine/Gateway build ran under a repository-local temporary root on port 28787, separate from production's 28767. Real Windows enrollment created a fresh credential; packaged Gateway JSON reads, inventory and idempotent review publication passed. A macro built from the active draft saved through the packaged Engine while client access to `Q:\Unavailable-SMB` was explicitly refused. The packaged Gateway resolved an unknown dataset handle; a source regression test also covers recreating an unwritten manual roll-up after losing process state. The synthetic project's first header check lacked the required source table/configuration; completing that fixture made the grid check pass. The private services, build environments and validation scratch were removed afterwards.

Production deployment `build-260929-171549-507-xwei` succeeded for Bridge, Engine, Gateway and Credential. The freshness CLI reports every component current; Gateway health and its new read/mutation capabilities were checked, and Bridge, Engine and Gateway have active heartbeats. The current released client remains compatible because the server changes are additive.

Outstanding rollout, fresh-profile testing and operational follow-ups are tracked in the [remaining plan](../client_smb_retirement.md).

General Arcode/File Browser filesystem access is outside the six fixes. The user may deliberately open and edit a server file there; no project-file restriction is added. Project Instance's own Help actions use the dedicated read-only view instead. Excel workbook opens and Explorer handoffs retain the existing exceptions.

## Why

`AGENT_GUIDELINES.md` ("Server-Hosted Project Data I/O") makes HTTP through the Gateway the only client transport for project data and SMB the transport being retired. On 2026-09-26 an audit of the whole frontend (app server routes and services, Electron host, renderer, installer) found the client still reaches the share in three ways:

1. **Gateway-first with an SMB fallback.** Registered reads and mutations fall back to the mapped drive when the Gateway is disabled, unreachable, has not advertised the kind, or rejects the request before acting — including a rejected credential, which is therefore hidden behind an SMB read ([workspace_read_client.py](../../../frontend/app_server/services/workspace_read_client.py), [workspace_mutation_client.py](../../../frontend/app_server/services/workspace_mutation_client.py)). Engine calculations fall back to a request file on the share ([engine_calculation_service.py](../../../frontend/app_server/services/engine_calculation_service.py)). Hosted saves fall back to the share only when the Gateway has not advertised the kind ([engine_hosted_save_service.py](../../../frontend/app_server/services/engine_hosted_save_service.py)); with every user on the latest version that path is unreachable.
2. **SMB only.** Of 79 endpoints in the dataset and method routers, 31 have no Gateway path at all; nearly all project-settings, dataset-type, field-mapping, source-table, reserving-class, audit-log, user-preference and macro-library endpoints are the same.
3. **Writes that skip the hosted save.** These write project data without the Engine's reserving-class lease, and some skip the dependent walk:
   - ArcBot's edit mode writes method JSON straight onto the share and its revert copies a backup back ([arcbot_host.js](../../../frontend/electron/arcbot_host.js), `applyArcBotJsonEdit`, `revertLatestArcBotEdit`).
   - "Open DFM JSON" opens the method file in an Arcode editor that saves it straight to the share ([dfm_tabs_orchestrator.js](../../../frontend/ui/method_pages/dfm/dfm_tabs_orchestrator.js), [editor_framework.js](../../../frontend/ui/arcode/shared/editor_framework.js)).
   - Applying a ResQ bridge patch runs a full DFM save inside the client app server ([dfm_rpc_bridge_service.py](../../../frontend/app_server/services/dfm_rpc_bridge_service.py), `apply_remote_to_local`).
   - Bootstrap, BF and Cape Cod refresh, the dataset grid patch, dataset notes and create-empty all write under an in-process lock only.
   - A rules save falls back to a direct project-wide save when its Engine job answers 503 ([project_settings_data_processing_rules.js](../../../frontend/ui/project_settings/project_settings_data_processing_rules.js), `saveRulesDirectly`).
   - The audit log is read, changed and rewritten under a lock that covers one process, so two PCs lose each other's entries ([audit_service.py](../../../frontend/app_server/services/audit_service.py)).

SMB also answers wrongly, not only slowly: file times read over the share can be seconds stale after a server write, which already raises false "changed by someone else" alerts and hides terminal job statuses (memories `smb-stat-metadata-alternation`, `propagation-status-smb-cache-lag`, `bridge-heartbeat-false-negative`).

### What genuinely needs the client machine or the share

These stay, and each step that touches one records the reason in code and in the domain doc:

- **Gateway sign-up**, until step 20 (done 2026-09-27): the client learned the Gateway URL and its secret by reading and writing `config\arcrho_gateway.json` on the share ([hosted_save_enrollment.py](../../../python-api/src/arcrho_api/hosted_save_enrollment.py)). That file holds every user's secret and any client can still read it until its folder's permissions are narrowed (a follow-up for the user); no client code reads it any more.
- **First-run discovery of the server folder** in setup and the installer, until the client stores a Gateway URL instead of a share root.
- **Excel**: workbook reads, the Excel add-in install from the share, opening a workbook in Excel. Kept by the user's decision on 2026-09-26.
- **Sources only this PC can read**: a SQL Server import runs as the user's own Windows login, and a CSV source may sit on a drive only the client has. The read must stay on the client; only the master-table write moves to the Gateway (decision 3).
- **General Arcode editing**, retained by the user on 2026-09-29: files explicitly opened in Arcode remain editable, including share paths. This is distinct from the Project Instance Help preview.
- **Handing a path to another program**: open in Explorer, show in folder, open in Excel.
- **A file picked on this PC**: reserving-class types import from a local file.

### Already done (2026-09-26)

Removed with no behaviour change: the `/book/*` workbook routes and their service and schemas, `GET /datasets`, `GET /dataset/{ds_id}/diagonal`, and the Electron `project-instance-index-watch-*` handlers with their preload entries. None had a caller.

## Decisions

Decisions 1-3 were taken by the user on 2026-09-26 and 4-7 on 2026-09-27, each as recommended.

1. **The app may stop working while the Gateway is down.** Step 18 retires the fallback without waiting for TLS. The fallback does not protect confidentiality — the same data already crosses the LAN in cleartext whenever the Gateway is up — while it hides credential failures and serves stale answers. TLS stays its own item in [hosted_save_http_transport.md](../hosted_save_http_transport.md).
2. **ArcBot's edits go through the page's save.** Step 4: ArcBot hands the edited JSON to the open page, which applies it as unsaved changes and saves through its normal hosted save, so ArcBot never writes a project file. Its backup and revert work on the page's undo instead of files on the share. No "replace this method JSON" save kind is added.
3. **Client-only import sources upload to the Gateway.** Step 15b: the SQL Server import and a client-only CSV are still read on the client, and the rows are uploaded to a new Gateway operation that writes the master table, so the client never writes the share.

Two smaller questions: "Open DFM JSON" becomes read-only (step 5; the recommended read-only answer was taken on 2026-09-27). The developer's fixed Snowflake config path under `E:\XWSpace` moved to the user's own settings folder on 2026-09-26 (done ahead of step 19).

4. **The Dataset Viewer's reserving-class value list reads the data's own class paths** (found by step 8; decided by the user on 2026-09-27, as recommended). The path-tree cache file that only ever held the paths someone had expanded is retired; step 19 makes the change.
5. **An uploaded source table is checked by counts, not a checksum** (found by step 15; decided by the user on 2026-09-27, as recommended). Step 22 checks that every chunk arrived, that the byte total matches what the client read and that the row count matches the client's count, and the atomic swap refuses anything short. No hash.
6. **An ArcBot edit to an Arcode notebook or JSON file stays unsaved until the user saves it** (found by step 4; confirmed by the user on 2026-09-27). Only a DFM saves ArcBot's edit through its own save straight away.
7. **ArcBot reads project data through the server, not the share** (found by step 16, recorded by step 19; answered by the user on 2026-09-27, option a, as recommended). Step 24 makes the change. The question and the options as they were put: ArcBot starts a Codex run whose prompt names the project folder on the share as its project root (`PROJECT_ROOT` in [arcbot_host.js](../../../frontend/electron/arcbot_host.js) `buildAssistantPrompt`, from `getCodexAssistantProjectRoots`), and a Codex read-only sandbox can read any path this PC can open, so the model is invited to browse methods, sidecars and CSVs over SMB. Since step 4 its edits land through the page and step 16 stopped copying CSVs, so nothing ArcBot does needs that read; it is only what the model may look at beyond the page's own JSON and the attachments. Options:
   - **a. Point ArcBot at the server instead of the share (recommended).** The prompt names the local exchange folder as ArcBot's working folder and tells it to read any other project data through the Python API's Gateway client (`arcrho_api.gateway`, which notebooks already use), so every read goes through the server as the signed user. ArcBot keeps project-wide questions ("compare with the other class") through registered reads. Cost: a read the Gateway does not register (a raw CSV, a folder listing) is no longer available to it, and the sandbox can still open the share if the model tries, until the share is unmapped.
   - **b. Keep the share read by design.** It is read-only and never writes, so it is no risk to the data, but it is SMB traffic this plan exists to retire, answers from a stale cache, and needs the drive mapped.
   - **c. Only the page's JSON and the attachments.** Simplest and fully off the share, but ArcBot can no longer answer anything about objects other than the open one.

## Rough size

Estimated 1,375 minutes of agent time across 24 steps: 885 minutes of code edit and 490 minutes of test, validation and deploy. Three deploy steps carry most of the validation time that is not test runs.

## Plan

Steps 1-3 are independent of each other; 4 and 5 are independent of 1-3. Steps 7-11 are independent of each other. Steps 13-16 are independent of each other. Every deploy step follows the group before it. Step 18 needs every earlier step. Step 19 follows 18. Step 20 is independent of everything but the last deploy. Step 21 is independent of every other step but must land before the first production deploy (step 6); it runs next. Step 22 follows step 15 and fits before step 17, whose deploy then carries its Gateway operation. Step 24 follows step 19 and started once decision 7 was taken.

**Test locally first.** Every step is checked against the private server on the developer PC before production sees it: `py -3.10 tools/local_server.py deploy` builds the Engine and Gateway from the working tree into `C:\Arco Server`, and `launch-app` opens the dev app against it (see [local_server_root_and_server_switcher.md](local_server_root_and_server_switcher.md)). Each deploy step runs that first and deploys to production only after the check passes. The local root does not reach the share at all, so a feature that still quietly reads over SMB shows up there as reading `C:\Arco Server` — use the client read-latency log's `transport` field, not the result, to tell the two apart.

Every new registered kind added by this plan is called with `gateway_required=True` from the start: this plan adds no new SMB fallback. Server processes (`ARCRHO_RUNTIME_SERVER_ROOT` set) keep running the service locally, as today.

### Step 1 — ResQ bridge apply becomes a hosted save

**Goal.** "Apply" in the DFM ResQ bridge runs on the Engine under the reserving-class lease instead of saving from the client.

**Read first.** [dfm_rpc_bridge_service.py](../../../frontend/app_server/services/dfm_rpc_bridge_service.py) `apply_remote_to_local`; [dfm_rpc_bridge_router.py](../../../frontend/app_server/api/dfm_rpc_bridge_router.py); [arcrho_engine_save_contract.py](../../../python-api/src/arcrho_engine_save_contract.py) `SAVE_JOB_KINDS`; memory `adding-a-hosted-save-kind`; [completed/hosted_rpc_bridge_transport.md](hosted_rpc_bridge_transport.md) (why apply was deferred).

**Do.**
- [x] Add a `dfm_rpc_bridge_apply` save kind whose function is the existing apply, plus its `save_propagation_roots`.
- [x] Route `POST /dfm/rpc-bridge/apply` through `run_hosted_save`.
- [x] Update [dfm_rpc_bridge.md](../../../frontend/docs/app_server/domains/dfm_rpc_bridge.md).

**Tests.** `frontend/tests/test_dfm_rpc_bridge_*`: apply goes through the hosted save and never calls the in-process DFM save on a client; `test_save_plan_service` covers the new roots function.

**Done when.** The apply route has no path that writes the DFM JSON from the client process.

Estimate: code edit 30 min, test/validation 20 min, total 50 min. Actual: code edit 2 min, test/validation 6 min, total 8 min (the existing hosted-save recipe made it one table entry, one wrapper and one route; checked end to end on the local root).

### Step 2 — Bootstrap refresh, dataset notes and empty-dataset create become hosted saves

**Goal.** Three client-side writes move onto the Engine; two refresh routes nothing calls are deleted.

**Read first.** [bootstrap_router.py](../../../frontend/app_server/api/bootstrap_router.py) refresh route; [dataset_router.py](../../../frontend/app_server/api/dataset_router.py) notes, create-empty and patch routes; [bornhuetter_ferguson_router.py](../../../frontend/app_server/api/bornhuetter_ferguson_router.py) and [cape_cod_router.py](../../../frontend/app_server/api/cape_cod_router.py) refresh routes; memory `adding-a-hosted-save-kind`.

**Do.**
- [x] Confirm no caller of `POST /bornhuetter-ferguson/refresh` and `POST /cape-cod/refresh` (the 2026-09-26 audit found none) and delete both routes. Done: no UI caller; the service refresh functions stay for `tools/restate_percentage_developed.py`.
- [x] Make Bootstrap refresh, dataset notes save and create-empty dataset save kinds. Done as `bootstrap_refresh`, `dataset_notes` and `empty_dataset_create`; each route body travels as a mapping third, which is also how the module's one `save_propagation_roots` tells the kinds apart. The Bootstrap page's refresh client function has no caller today; the route stays because the step keeps it.
- [x] Check whether `POST /dataset/{ds_id}/patch` is reachable from a visible control (it is wired through `dataset_run_controller.js` and a hidden Save button). If not reachable, delete it with its client function; if reachable, record that in this step and add it to step 9 instead of guessing. Done: not reachable (the only trigger is the `saveBtn` inside `#hiddenControls`, `display:none` in both the Dataset Viewer and the DFM page, and nothing clicks it), so the route, its schemas, its service functions and the whole client chain were deleted; step 9 has nothing to pick up.

**Tests.** Hosted-save routing tests for each new kind; route tests that the deleted routes are gone.

**Done when.** None of these routes writes a sidecar, CSV or method JSON from the client process.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 15 min, test/validation 6 min, total 21 min (the hosted-save recipe from step 1 carried it; checked end to end on the local root).

### Step 3 — Audit log append runs on the server

**Goal.** Project audit log reads and appends go through the Gateway, under one server-side lock.

**Read first.** [audit_service.py](../../../frontend/app_server/services/audit_service.py); [audit_log_router.py](../../../frontend/app_server/api/audit_log_router.py); [arcrho_workspace_mutation_contract.py](../../../python-api/src/arcrho_workspace_mutation_contract.py); [workspace_mutation_client.py](../../../frontend/app_server/services/workspace_mutation_client.py); [sidecar_audit_contract.py](../../../python-api/src/arcrho_api/sidecar_audit_contract.py) (its normalizer drops unknown keys, so the entry id must be added there); memory `adding-a-hosted-workspace-read`.

**Do.**
- [x] Register an audit-log read kind and an append mutation kind. An append must be idempotent to use the mutation transport: carry a client-generated entry id and skip an id already present. Done as `project_audit_log` and `project_audit_log_append`; the id is stored on the record as `entry_id` through the canonical audit contract, and entries without one read as before.
- [x] Route the two audit-log endpoints and `safe_append_project_audit_log` callers on a Client PC through them. Done by process rather than call site: `safe_append_project_audit_log` sends the append through the Gateway in a client process and writes locally in a server process, so the Engine's rules, dataset-type change and source refresh jobs pay no Gateway hop. Client callers routed: the audit table's read and `POST`, reserving-class types save, presentation-only dataset-types save, source profile save, SQL Server import, source CSV path rewrite, project folder create and rename, General Settings save, generated CSV cache clear, field mapping save, and the direct rules save. Two test modules that saved rules or dataset types without patching the append now patch it, so a test run can never append to the Gateway this PC is enrolled with.

**Tests.** Duplicate append with the same id writes once; client routes use the Gateway and refuse when it is unavailable.

**Done when.** No client code path rewrites `audit_log.json` over the share.

Estimate: code edit 30 min, test/validation 15 min, total 45 min. Actual: code edit 20 min, test/validation 21 min, total 41 min (validation ran long because moving every client append onto the Gateway meant checking that no test run could append to this PC's enrolled Gateway; two suites could, and now patch it).

### Step 4 — ArcBot edits go through the page's save

**Goal.** ArcBot never writes a project file; its edits land through the same save the user would press. Follows decision 2.

**Read first.** [arcbot_host.js](../../../frontend/electron/arcbot_host.js) `applyArcBotJsonEdit`, `revertLatestArcBotEdit`, `validateArcBotJsonTarget`, and the staging functions that copy the method JSON and CSVs; the renderer side that receives ArcBot results ([ui/ai-assistant/index.js](../../../frontend/ui/ai-assistant/index.js)); the pages ArcBot edits and how they apply a payload: [dfm_rpc_bridge_client.js](../../../frontend/ui/method_pages/dfm/dfm_rpc_bridge_client.js) `reviewArcBotDfmEditApproval`, [dfm_ratio_history.js](../../../frontend/ui/method_pages/dfm/dfm_ratio_history.js) method steps, [dfm_tabs_orchestrator.js](../../../frontend/ui/method_pages/dfm/dfm_tabs_orchestrator.js) message handler, [project_instance_messages.js](../../../frontend/ui/project_instance/project_instance_messages.js) forwarding, [notebook-io.js](../../../frontend/ui/arcode/notebook-editor/notebook-io.js) and [editor_framework.js](../../../frontend/ui/arcode/shared/editor_framework.js) for Arcode notebooks and JSON files.

**Do.**
- [x] Implement decision 2. Done: the host returns the edit (`editProposed`, with the edited JSON and its persisted text) and the widget posts it to the tab that sent the context. A DFM applies it through the owned-patch apply as one whole-method undo step and saves through its normal hosted save (a failed save leaves it unsaved); an Arcode notebook or JSON editor applies it as one undoable unsaved change the user saves. "Revert the latest ArcBot edit" never reaches the host: the same tab undoes that step, refused once it is no longer the latest change, and a DFM saves again. Ask for Approval keeps its compare review and lands through the same apply. The host's backups, `history` folder, temp rename and latest-edit manifest are gone.
- [x] Stage the method JSON and CSVs from hosted reads rather than share copies, or record here which ones still lack a read kind and leave them for step 16. Done: the host no longer reads the target at all; it stages the page's own JSON (a method's in-memory payload, a notebook's cells, or a JSON editor's text). Still on the share, moved to step 16: the reserving-class CSVs (a folder listing plus every `.csv` beside the method) and the two linked CSVs (`data_tab` input triangle, `results_tab` ultimate vector) that `createArcBotEditSession` copies into the exchange folder; no read kind lists a class folder or returns a raw CSV.

**Tests.** Node tests: an edit targeting a project file never calls the host file writers; revert restores through the page.

**Done when.** No ArcBot code path writes under the workspace root.

Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 18 min, test/validation 10 min, total 28 min (the DFM approval path and the method undo step already existed, so the page side was a reuse; checked against the local root by posting the widget's messages to a DFM page served by the dev app).

### Step 5 — "Open DFM JSON" becomes read-only

**Goal.** The Arcode window opened from a DFM shows the method JSON without saving it back over the share.

**Read first.** [dfm_tabs_orchestrator.js](../../../frontend/ui/method_pages/dfm/dfm_tabs_orchestrator.js) "Open DFM JSON"; [editor_framework.js](../../../frontend/ui/arcode/shared/editor_framework.js) open, revision check and save; the path the request travels: [project_instance_messages.js](../../../frontend/ui/project_instance/project_instance_messages.js) `forwardOpenPathRequestToShell`, [shell_messages.js](../../../frontend/ui/shell/shell_messages.js) `arcrho:open-path`, [main.js](../../../frontend/electron/main.js) `open-path` and `createArcodeWindow`, [arcode/main.js](../../../frontend/ui/arcode/main.js) `openCodeTab`, and [code-editor/index.js](../../../frontend/ui/arcode/code-editor/index.js).

**Do.**
- [x] Load the content through the hosted DFM load and open it read-only (recommended answer; if the user prefers editable, route the save through the DFM hosted save instead). Done: the DFM page sends the method's identity, not its path; the Project Instance and the shell pass it on and the host opens Arcode without touching the share. The code editor loads the method through `/dfm/method/load`, lays it out with the host's persisted-JSON formatter, and opens it read only with a "Read only" chip; Save, Save As, Ctrl+S and ArcBot edits are refused, the tab has no path (no recent-file entry, no revision polling), and every other file keeps its normal save.
- [x] Bump the `?v=` stamps of every edited module and update the tests that pin them (memory `theme-css-version-pins`, `frontend-node-test-suite`).

**Tests.** Node test that the window opened from a DFM cannot save to a file path.

**Done when.** No DFM-originated Arcode window writes a method file.

Estimate: code edit 20 min, test/validation 15 min, total 35 min. Actual: code edit 12 min, test/validation 6 min, total 18 min (checked against the local root in headless Chrome: a DFM page's "Open DFM JSON" opened the method read only and no save reached the host; the method file's time was unchanged).

### Step 6 — Deploy the server side of steps 1-3

**Goal.** The Engine and Gateway advertise the new save, read and mutation kinds.

**Read first.** `AGENT_GUIDELINES.md` "Component Build and Deploy"; [component-deployment-authorization.md](../../../agent-instructions/component-deployment-authorization.md).

**Do.**
- [x] Production deployment confirmed by build records; September 29 follow-up also checked the source payload.
- [x] Production Gateway capabilities verified on September 29.

**Tests.** None beyond the capability check.

**Done when.** The capability list carries every kind steps 1-3 added.

Estimate: code edit 0 min, test/validation 20 min, total 20 min.

### Step 7 — Project configuration reads

**Goal.** Project Settings pages read their configuration through the Gateway.

**Read first.** [project_settings_router.py](../../../frontend/app_server/api/project_settings_router.py) GET routes; [dataset_types_router.py](../../../frontend/app_server/api/dataset_types_router.py) `GET /dataset_types`; [field_mapping_router.py](../../../frontend/app_server/api/field_mapping_router.py) GET; [source_table_router.py](../../../frontend/app_server/api/source_table_router.py) `GET /source_table`, `GET /file_status` (JSON part only), `GET /connections`; [arcrho_router.py](../../../frontend/app_server/api/arcrho_router.py) `GET /arcrho/projects`; [dataset_router.py](../../../frontend/app_server/api/dataset_router.py) number-format defaults GET; [user_identity_router.py](../../../frontend/app_server/api/user_identity_router.py); [data_processing_rules_router.py](../../../frontend/app_server/api/data_processing_rules_router.py) GET and validate with [data_processing_rules_service.py](../../../frontend/app_server/services/data_processing_rules_service.py) `_load_validation_context` and [data_processing_values_service.py](../../../frontend/app_server/services/data_processing_values_service.py) `get_data_processing_values`; the `caches` stage of [source_table_refresh.py](../../../server-components/src/arcrho_engine/source_table_refresh.py); memory `adding-a-hosted-workspace-read`.

**Do.**
- [x] Register a read kind per route above, each a service function returning the route's exact current response. The registered `project_dataset_types` kind returns a different shape than `GET /dataset_types`, so that route gets its own function. Done: 13 kinds, all Gateway-required (`project_settings_sources`, `project_folders`, `project_registry`, `project_names`, `general_settings`, `dataset_types_table`, `field_mapping`, `source_table_settings`, `mssql_connections`, `dataset_number_format_defaults`, `user_identity`, `data_processing_rules`, `data_processing_rules_validate`). Route bodies that mapped errors moved into their service so a refusal crosses the Gateway with the same status. `GET /source_table` adds `driver_available` on the client, because the SQL Server import runs there. `GET /app/user-identity` answers for the signed login; the other client writers still resolve their own display name from the username index over the share (cached per process), which is left for step 18 or 19.
- [x] Keep the local stat of an external CSV in `/file_status` on the client (it may name a drive only this PC has); move only its project-JSON reads. Done: it reuses the `source_table_settings` read for the import record and path.
- [x] Rewrite `data_processing_rules` GET and validate so a read never copies the master table or rebuilds `data_processing_values.json`; that write belongs to the source refresh job. Done: both read the master table as it stands and build a stale value list in memory. The source refresh job now rebuilds `data_processing_values.json` in its `caches` stage; a rules save still refreshes the table and the list as before. No other caller relied on the read's side effect (the list had no other writer). Until the next refresh, a Field Mapping save leaves the list stale, so the rules page rebuilds it in memory on each open.

**Tests.** Per-kind transport tests (Gateway used, refused when unavailable); a response-shape parity test per route.

**Done when.** None of these routes opens a file under the workspace root on a Client PC.

Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 14 min, test/validation 9 min, total 23 min (the step 3 read recipe made each route one contract entry and one wrapper; checked on the local root, where every route answered through the Gateway exactly as the server-side call did).

### Step 8 — Reserving-class reads and per-user preferences

**Goal.** Reserving-class pickers, path trees, filters and hidden paths load and save through the Gateway.

**Read first.** [reserving_class_router.py](../../../frontend/app_server/api/reserving_class_router.py); [reserving_class_service.py](../../../frontend/app_server/services/reserving_class_service.py) path-tree children and types refresh; [project_user_preferences_service.py](../../../frontend/app_server/services/project_user_preferences_service.py) and [project_user_preferences_router.py](../../../frontend/app_server/api/project_user_preferences_router.py); the callers of the tree routes in [valid_value_lists.js](../../../frontend/ui/shared/services/valid_value_lists.js) and [reserving_class_picker.js](../../../frontend/ui/shared/components/pickers/reserving_class_picker.js); the values-refresh writers ([table_summary_service.py](../../../frontend/app_server/services/table_summary_service.py) `refresh_table_summary`, [field_mapping_service.py](../../../frontend/app_server/services/field_mapping_service.py) save).

**Do.**
- [x] Read kinds for combinations, path tree and the reserving-class types; the path-tree children GET must stop refreshing values and rewriting caches on a read (the source refresh job owns that write). Done: `reserving_class_combinations`, `reserving_class_path_tree`, `reserving_class_path_tree_children`, `reserving_class_types`, plus `reserving_class_hidden_paths`, `reserving_class_filter_spec` and `project_user_preferences` for the preference GETs; the existing `reserving_classes_with_data` is now Gateway-required too. Each service returns its route's whole answer, refusals included. The children read computes from the combinations and types files as they stand (checked equal to the old answer for 1,082 prefixes of NJ_Annual_Prod_202605_Fake) and writes nothing. The values, combinations and types files were already written by the source refresh job's `caches` stage, a field mapping save, `POST /table_summary/refresh`, `POST /reserving_class_values/refresh` and `POST /reserving_class_types`, so nothing new owns them. Recorded, not decided: `reserving_class_path_tree_cache.json` now has no writer. Its only reader is `GET /reserving_class_path_tree`, which the Dataset Viewer's reserving-class value list prefers over the combinations; that list relied on the children read's side effect and only ever saw the paths some children call had expanded (no page calls the children route; `tools/build_monthly_insurance_demo_project.py` does, and its `force` now just skips the cache). A full expansion of the Fake project is about 29,000 paths (about 1 s), so whether a writer should build the file in full or the list should read the combinations is a question for the user; the file is left as it stands, and the lock and helpers that only its writer used were removed.
- [x] Mutation kinds for hidden paths, filter spec and project user preferences, with the login taken from the signed request, never from the payload. Done: `reserving_class_hidden_paths_save`, `reserving_class_filter_spec_save`, `project_user_preferences_update`; the user is the Gateway's acting identity, as step 7's `user_identity`. All are whole-value writes, which makes them idempotent. That needed one fix: the filter spec and tree preferences were deep-merged into the stored ones, so a cleared filter level or a removed last favorite came back on the next open; they now replace the stored value (`update_preferences(..., whole_values=...)`), in one write instead of two.
- [x] `GET /reserving_class_types` stops writing the JSON and workbook on a read. Done: it shows the merge in memory (`refresh_reserving_class_types_json(..., persist=False)`); no caller relied on the write, since every values refresh already persists the merge. The types save, the values refresh (step 15) and the local-file types import (a file picked on this PC, kept by design) are the router's only routes still run in the client process.

**Tests.** Transport tests; a test that a GET writes nothing.

**Done when.** No reserving-class or user-preference route touches the share from a Client PC, and no GET in this router writes.

Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 21 min, test/validation 7 min, total 28 min (the step 3 and 7 recipes carried the kinds; checked on the local root, where every route answered through the Gateway exactly as the server-side call did).

### Step 9 — Dataset and method side reads

**Goal.** The dataset sidecar panel, dependents preview, DFM dataset references and pattern reads come from the Gateway.

**Read first.** [dataset_router.py](../../../frontend/app_server/api/dataset_router.py) `POST /dataset/sidecar/load`, `POST /dataset/calculated/preview`; [dfm_method_router.py](../../../frontend/app_server/api/dfm_method_router.py) dataset-references resolve; [dfm_method_index_router.py](../../../frontend/app_server/api/dfm_method_index_router.py) percent-developed curve, development pattern and index refresh; the index refresh's callers, [dfm_startup_state.js](../../../frontend/ui/method_pages/dfm/dfm_startup_state.js) `refreshDfmMethodIndex` and [dfm_details.js](../../../frontend/ui/method_pages/dfm/dfm_details.js) `loadDfmMethodNames`; the Gateway's request size refusal in [main.py](../../../server-components/src/arcrho_gateway/main.py) `_handle_hosted_execution`.

**Do.**
- [x] Read kinds for sidecar load, calculated preview, dataset-references resolve, percent-developed curve and development pattern. Done: `dataset_sidecar_load`, `dataset_calculated_preview`, `dfm_dataset_references_resolve`, `dfm_percent_developed_curve`, `dfm_development_pattern`, each Gateway-required and each the route's whole answer. The preview sends the whole edited grid, which the 256 KiB read budget would refuse for a large triangle, so a read now has the hosted save's request budget (`MAX_WORKSPACE_READ_REQUEST_BYTES` is its `MAX_REQUEST_BYTES`).
- [x] The method-index refresh becomes a mutation kind (it rewrites `index.json`); it runs on every DFM open today. Done as `dataset_index_rebuild`, Gateway-required; `rebuild_index` was already idempotent (the index derives from the folders and an unchanged index is not rewritten). Correction: nothing calls `POST /dfm/method-index/refresh` — the DFM stopped calling it on open on 2026-07-26 (974e66e7) and `refreshDfmMethodIndex` is imported but unused — so no DFM open pays its round trip (about 130 ms warm on the local root). The live rebuild is the DFM `Name` picker's button, `GET /dfm/method-index?refresh=true`, which rebuilds through the `dataset_index` read kind; that read kind becomes Gateway-required with the other fallbacks in step 18.
- [x] If step 2 recorded the grid patch as reachable, make it a hosted save kind here. Does not apply: step 2 found it unreachable and deleted the route.

**Tests.** Transport tests per kind.

**Done when.** None of these routes opens project files from a Client PC.

Estimate: code edit 45 min, test/validation 20 min, total 65 min. Actual: code edit 8 min, test/validation 9 min, total 17 min (the step 7 and 8 recipes made each route one contract entry and one wrapper; checked on the local root, where every route answered through the Gateway exactly as the server-side call did).

### Step 10 — Change detection through the Gateway

**Goal.** The "changed by someone else" watch and the Project Instance table watch ask the server, which reads its own disk and is never stale.

**Read first.** [object_change_watch_service.py](../../../frontend/app_server/services/object_change_watch_service.py); [object_change_watch.js](../../../frontend/ui/shared/services/object_change_watch.js); `GET /datasets/cached/index-signature` in [dataset_router.py](../../../frontend/app_server/api/dataset_router.py) and its poller in [project_instance_dataset_cache.js](../../../frontend/ui/project_instance/project_instance_dataset_cache.js) `checkDatasetIndexSignature`; business-logic contract rule 15 on the stale-stat comparison; the DFM method-file watcher block in [dfm_persistence.js](../../../frontend/ui/method_pages/dfm/dfm_persistence.js) (`readDfmMethodFileRevision`, `startDfmMethodFileWatcher`).

**Do.**
- [x] Read kinds for fingerprint, attribution and index signature. A Gateway failure answers "unknown" quietly (no alert, no error), as hosted-save progress does. Done: `object_change_fingerprint`, `object_change_attribution` and `dataset_index_signature`, served through `workspace_read_client.run_polled_workspace_read`, which is Gateway-required but turns a 503 or 504 into the route's answer with `unknown: true`. An unknown fingerprint or index signature skips that poll and keeps the baseline; an unknown attribution after a moved fingerprint defers the alert to the next poll. Polling cadence unchanged (5 s windows, 8 s Project Instance); measured on the local root, one poll is about 5-10 ms through the Gateway.
- [x] Keep the `updated_at` comparison rule; note in the contract that the server-side stat is authoritative.
- [x] The DFM page's own method-file watcher: recorded for deletion in step 19, not moved. It never runs: `startDfmMethodFileWatcher` has been a no-op since 974e66e7, nothing starts the timer, and `checkDfmMethodFileWatch` and `refreshDfmMethodFileRevision` have no callers, so `readDfmMethodFileRevision` never stats the share. The DFM page's object-change watch already covers the same method file and its output sidecar through the Gateway.

**Tests.** Transport tests; the unknown answer never raises an alert.

**Done when.** No watch polls the share.

Estimate: code edit 35 min, test/validation 20 min, total 55 min. Actual: code edit 10 min, test/validation 16 min, total 26 min (checked on the local root: every poll went through the Gateway, your own hosted save moved the fingerprint once and the rebase absorbed it, and a direct server-side write by "someone else" was detected on the next poll and named; the one-page headless check was not possible because the Dataset Viewer's watch starts only under a Project Instance host).

### Step 11 — Calculations answer with their data

**Goal.** A hosted calculation returns its result in the reply, so the client stops waiting for a CSV to appear on its drive and reading it there.

**Read first.** [engine_calculation_service.py](../../../frontend/app_server/services/engine_calculation_service.py) hosted branch and `wait_for_file`; [arcrho_runtime_service.py](../../../frontend/app_server/services/arcrho_runtime_service.py) `/arcrho/headers` and the header cache clear; [arcrho_engine_calculation_contract.py](../../../python-api/src/arcrho_engine_calculation_contract.py); business-logic contract rule 18; [arcrho_router.py](../../../frontend/app_server/api/arcrho_router.py) (the routes resolve the CSV path on the client before choosing a transport); `helpers.read_dataset_csv` and [excel_dataset_service.py](../../../frontend/app_server/services/excel_dataset_service.py) (the one place a calculation's CSV text is parsed as a dataset); `workspace_read_client.run_workspace_read` (it looked the display name up in the username index over the share); memories `engine-calculation-gateway-transport`, `blank-csv-row-is-an-empty-origin`.

**Do.**
- [x] The hosted exchange returns the CSV body; the client stops calling `wait_for_file` after a hosted success. Done: a successful exchange answer carries `csv_text`, the CSV's exact text, and the client hands it to its caller (the headings use it) without waiting for or reading the file; a success without it (a Gateway older than this step) is a `gateway_error` saying the server needs updating, not a drive read, so the frontend release must follow the step 12 deploy, as steps 7-10 already require. A caller that parses the text as a dataset uses the new `helpers.read_dataset_csv_text`, which reads it exactly as `read_dataset_csv` reads the file, leading blank origin included; the Excel calculated-formula path, which parsed such text with a bare `pd.read_csv`, now uses it. Also needed for "no share I/O": the transport no longer depends on whether the workspace root is a network drive (only on the process, as for workspace reads), so a local-root client uses its Gateway too; the `/arcrho/tri*` routes resolve the CSV path only for a local run (resolving it stats the project folder); and calculations and workspace reads send an empty display name for the server to resolve, instead of reading the username index over the share.
- [x] Headers become a read kind returning the labels; the header cache clear becomes a mutation kind. Done as `arcrho_headers` (`get_project_headers`, which now takes `stored_period_length`, so the route's pairs are unchanged) and `arcrho_headers_cache_clear` (idempotent), both Gateway-required.
- [x] Update contract rule 18.

**Tests.** Hosted exchange test with no client-side file read; headers transport test.

**Done when.** A hosted calculation on a Client PC performs no share I/O.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 18 min, test/validation 7 min, total 25 min (the headings reused the read and mutation recipes; checked on the local root, where a triangle and two vectors, their grids and the headings came back with zero client file operations, equal to the server-side run, including F 91 whose first origin is empty).

### Step 12 — Deploy the server side of steps 7-11

**Goal.** The Gateway (and Engine, for step 11) advertise every kind steps 7-11 added.

**Read first.** As step 6.

**Do.**
- [x] Production deployment and Gateway capabilities verified on September 29.

**Tests.** Capability check.

**Done when.** Every kind from steps 7-11 is advertised.

Estimate: code edit 0 min, test/validation 20 min, total 20 min.

### Step 13 — Project folder and settings writes on the server

**Goal.** Creating, renaming and deleting a project folder, saving the project registry and general settings, and clearing the generated cache run on the Gateway.

**Read first.** [project_settings_service.py](../../../frontend/app_server/services/project_settings_service.py) and [project_settings_router.py](../../../frontend/app_server/api/project_settings_router.py); [arcrho_workspace_mutation_contract.py](../../../python-api/src/arcrho_workspace_mutation_contract.py) (only idempotent kinds may register); [workspace_mutation_client.py](../../../frontend/app_server/services/workspace_mutation_client.py); the Gateway's hosted-save receipts in [arcrho_gateway/main.py](../../../server-components/src/arcrho_gateway/main.py) `submit` and [arcrho_gateway/workspace_mutations.py](../../../server-components/src/arcrho_gateway/workspace_mutations.py); the registry's client in [project_settings_project_map.js](../../../frontend/ui/project_settings/project_settings_project_map.js); business-logic contract rule 19.

**Do.**
- [x] Give the mutation transport a request-id receipt so a non-idempotent write (rename, create, delete) replays its stored outcome instead of running twice. Record the receipt rule in contract rule 19. Done: a kind marked `receipt` gets a receipt in the Gateway's one receipt store (moved out of `main.py` into `arcrho_gateway/receipts.py` and shared with hosted saves) under `receipts\mutations\<user>\<request id>.json`, written before the run and holding one lock for it; a repeat of the same request answers from it, a different request under the id is refused with 409, and a receipt a stopped Gateway left unfinished answers 409. Receipts expire with the hosted-save ones (24 h, pruned at Gateway start, now recursively). The routes take an optional `request_id`; otherwise the client makes one, and resends the same request once when the answer is lost after the server had it (not after a timeout).
- [x] Register the six writes; replace the registry's mtime conflict check with a revision the server owns. Done: `project_folder_create`, `project_folder_rename`, `project_folder_delete`, `project_registry_save` and `general_settings_save` carry a receipt (General Settings because each save appends an audit entry); `generated_dataset_cache_clear` is idempotent. All Gateway-required. The registry stores `revision` in `index.json` (absent reads as 0); the GET answers it instead of `mtime`, a save names `expected_revision`, a stale one is 409, and the compare and write run under one process lock. The Project Settings page and the demo-project tool send the revision they read. Opening a project folder in Explorer stays on the client: it hands a path to a program on this PC.

**Tests.** Replay returns the first outcome; a rename is never applied twice; transport tests.

**Done when.** No Project Settings write touches the share from a Client PC.

Estimate: code edit 55 min, test/validation 20 min, total 75 min. Actual: code edit 14 min, test/validation 11 min, total 25 min (the step 3 and 8 recipes carried the six kinds, and the hosted-save receipt was a ready model; checked on the local root: a scratch project was created, renamed twice under one request id (the second answered from the receipt, and a different change under that id got 409), its General Settings saved, its cache cleared, the registry saved and refused at a stale revision, and the folder deleted, every call through the Gateway).

### Step 14 — Dataset-type change job and project duplication through the Gateway

**Goal.** Both Engine jobs are submitted, polled and cancelled over HTTP.

**Read first.** [dataset_types_change_service.py](../../../frontend/app_server/services/dataset_types_change_service.py); [project_settings_service.py](../../../frontend/app_server/services/project_settings_service.py) duplication submit, status and cancel; business-logic contract rules 14 and 20; the routes in [dataset_types_router.py](../../../frontend/app_server/api/dataset_types_router.py) and [project_settings_router.py](../../../frontend/app_server/api/project_settings_router.py) (the save route decided direct, plan or job by reading the table on the client); the two pollers [project_settings_dataset_types_job.js](../../../frontend/ui/project_settings/project_settings_dataset_types_job.js) and [project_settings_duplicate_job.js](../../../frontend/ui/project_settings/project_settings_duplicate_job.js); `workspace_read_client.run_polled_workspace_read` (step 10).

**Do.**
- [x] Mutation kinds for both submits and the duplication cancel (both are already keyed by request id); read kinds for both statuses. Done: `dataset_types_save`, `project_duplication_submit` and `project_duplication_cancel` (Gateway-required, no Gateway receipt: both submits are idempotent by their own request id, which also travels as the mutation's id), and `dataset_types_change_status` and `project_duplication_status`, served through `run_polled_workspace_read`, so a poll the Gateway cannot answer is `unknown: true`; both pollers keep polling on it and restart their stall clock. The duplication request and cancel marker now name the signed user instead of the server process. The `dataset_types_change_plan` read had no caller left and was removed.
- [x] Move the dataset-types direct write (the no-job branch of `POST /dataset_types`) to a mutation kind. Done as part of `dataset_types_save`: the route's whole decision (direct, plan or job) moved into `dataset_types_change_service.save_dataset_types`, because it read the table on the client to decide. The direct write now skips a table that already holds the submitted rows, so a replay writes nothing and appends no second audit entry, which is what makes the kind idempotent.

**Tests.** Transport tests; a replayed submit returns the existing job.

**Done when.** Neither job's request or status file is touched from a Client PC.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 13 min, test/validation 14 min, total 27 min (the step 10 and 13 recipes carried the kinds; checked on the local root: a direct save, its replay and revert, a dataset-type change job and its replayed submit, one duplication cancelled and one completed and then deleted, and both status polls answering "unknown" with the Gateway off, with zero client file operations under the root).

### Step 15 — Field mapping, source profile and reserving-class refresh on the server

**Goal.** The remaining Project Settings data writes run on the Gateway or the Engine. Part b follows decision 3.

**Read first.** [field_mapping_service.py](../../../frontend/app_server/services/field_mapping_service.py); [source_table_service.py](../../../frontend/app_server/services/source_table_service.py) profile, connections, import and refresh; [source_refresh_service.py](../../../frontend/app_server/services/source_refresh_service.py) plan; `POST /reserving_class_values/refresh`, `POST /reserving_class_types` and `POST /table_summary/refresh`; the Import Data flow `importSourceData` in [project_settings.js](../../../frontend/ui/project_settings/project_settings.js) and the poll loop in [project_settings_source_refresh_job.js](../../../frontend/ui/project_settings/project_settings_source_refresh_job.js); [test_project_settings_writes_hosted.py](../../../frontend/tests/test_project_settings_writes_hosted.py) as the test model.

**Do.**
- [x] a. Mutation kinds for the field mapping save, source profile save and connection list; the reserving-class values refresh and table-summary refresh become the source refresh job where the source is server-readable. The refresh plan's drive-letter-to-UNC translation stays on the client and is sent as data. Done: `field_mapping_save`, `source_profile_save` and `reserving_class_types_save` carry a receipt (each appends an audit entry; the reserving class types save moved out of its route into `reserving_class_service.save_reserving_class_types`); `mssql_connection_remember` (sent by `submit_mssql_connection_remember` after a SQL Server listing or import on this PC) and `mssql_connection_forget` are idempotent. A CSV path is translated from this PC's drive letters before the profile and mapping saves send it. The plan reads the settings and the busy check through the Gateway, translates the stored path on the client, and sends `source_csv_path_rewrite` with both spellings, which changes the stored path only while it still reads the drive letter; `resolve_import_source_for_server` is gone. The source refresh submit is Gateway-required and its poll is a polled read (`unknown` keeps the page polling). Import Data no longer falls back to a local copy of a server-readable source: with no plan or no Engine it says so and imports nothing. `POST /table_summary/refresh` is now `table_summary_rebuild`, a server-side rebuild of the summary and reserving-class values with no forced re-import, asked for only after a client-only import while no Engine runs. `POST /reserving_class_values/refresh` had no caller and was removed. Project Settings module stamps move to `20260927src1`.
- [x] b. Implement decision 3 for the SQL Server import and a client-only CSV. Moved to step 22 on 2026-09-27: the Fake project's table is about 346,000 rows by 34 columns (88 MB), far past the 256 KiB mutation limit, so it needs a chunked, resumable upload with its own Gateway operation, temporary storage, an atomic swap of the master table and progress, which is a step of its own. Until then `POST /source_table/import` and `POST /source_table/refresh` still write the master table over the share for such a source, as the `source_table` domain doc records.

**Tests.** Transport tests; the client-only source case per decision 3 (moved to step 22).

**Done when.** The only share writes left in Project Settings are the ones decision 3 keeps, each documented. Holds for part a: the client-only import of part b is the one left, documented in the `source_table` domain doc and owned by step 22; the rules-save direct fallback stays with step 18.

Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 16 min, test/validation 11 min, total 27 min (part a only; the step 13 and 14 recipes carried the kinds; checked on the local root: every save, the connection remember and forget, the plan and the rebuild ran over the Gateway against the local Fake project with its saved mapping and types unchanged, and a scratch copy with a small CSV reachable as a share was imported by the Engine job, its replayed submit resumed the same job, and the copy was deleted).

### Step 16 — Macro library, ArcBot prompts and the ResQ import request

**Goal.** The last share reads for supporting files, and the macro that still drops a request file, go through the Gateway.

**Read first.** [macro_library_service.py](../../../frontend/app_server/services/macro_library_service.py); ArcBot prompt and instruction loaders in [arcbot_host.js](../../../frontend/electron/arcbot_host.js); [import_resq_reserving_class.py](../../../python-api/macros/import_resq_reserving_class.py) `publish_import_request`; [resq_sync_queue_service.py](../../../frontend/app_server/services/resq_sync_queue_service.py) and `arcrho_api.resq_sync_queue.submit_sync_request` as the publish model; memories `scripts-save-through-gateway-client`, `shared-macro-library-deploy`, `macro-must-not-depend-on-app-arcrho-api`, `release-vs-source-comparison` (the released app's contract decides whether a macro can use a new kind).

**Do.**
- [x] Read kinds for the macro library listing and file text; the install and sync write only to local Documents. Done: `macro_library_listing` and `macro_library_file` (Gateway-required) return each macro's exact text; the client compares with its own macros folder and writes only there. A Gateway that cannot answer is "library unavailable", and the check before a run leaves the local copy alone.
- [x] ArcBot reads its prompt and instructions through the app server's hosted read; it stops seeding files onto the share. Done: `arcbot_prompt_files` (Gateway-required) behind `GET /arcbot/prompt-files`, which the Electron host calls on the local app server. With no server prompt or no answer ArcBot uses the bundled prompt in memory. Nobody seeds the server's copy any more: an administrator edits `config\arcbot` on the server, and every earlier ArcBot request already seeded it on production. The legacy `config\arcbot_prompt.md` is no longer read.
- [x] ArcBot's edit staging copies the reserving-class CSVs and the method's linked CSVs from the share into its local exchange folder (`createArcBotEditSession` in [arcbot_host.js](../../../frontend/electron/arcbot_host.js), left by step 4). Give it a hosted read for those files, or drop the copy and let ArcBot read them through the Python API. Done: the copy was dropped, not given a read. It copied the `.csv` files beside the method, but since the 2026-06-09 layout a method lives in the class's `methods` folder, which holds none, and the two linked-CSV fields are stripped by the DFM contract and never sent by the page, so both copies had nothing to copy. Only the page's JSON is staged.
- [x] The import macros publish through the Gateway client, the way the ResQ sync request already does; publish the macros. Done: `resq_import_request_publish` (`resq_import_queue_service`): the macro sends the request it built, the server checks it names the validated project, class and id, stamps the signed user and writes it into the import queue, idempotent by request id; the macro calls it Gateway-required. The single import macro is 1.15.0 (the batch macro publishes through it). **Its publish waits for the next app release:** the released app (1.7.5) validates the kind against its own contract, which lacks it, so 1.15.0 on 1.7.5 would refuse every import. The macro library was not published here.

**Tests.** Transport tests; macro test that the publish uses the Gateway.

**Done when.** None of these reads or publishes touches the share from a Client PC.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 20 min, test/validation 26 min, total 46 min.

### Step 17 — Deploy the server side of steps 13-16

**Goal.** Every kind steps 13-16 and 22 added is advertised.

**Read first.** As step 6.

**Do.**
- [x] Production's ArcBot prompt copy (verified 2026-09-29; Gateway instructions and `READABLE_FOLDERS` are present). Original rollout instructions: The server's `config\arcbot\arcbot_prompt.md` is edited by an administrator on the server (step 16), so no deploy writes it. Before the app release that carries step 24, give it the bundled prompt's wording ([arcbot_prompt.md](../../../frontend/electron/prompts/arcbot_prompt.md)): drop the `Current project folder: {{PROJECT_ROOT}}`, `Local exchange server root` and `{{NETWORK_ROOT_NOTE}}` lines, add `Extra folders the user allowed you to read: {{READABLE_FOLDERS}}` and the "Project data" section that points at `arcrho_api.gateway`, and replace the edit mode's "original server root" line. The app no longer fills `PROJECT_ROOT` or `NETWORK_ROOT_NOTE`, so an unchanged copy renders `Current project folder: .` and lacks the Gateway instructions; any instruction file under `config\arcbot\instructions` that names the share needs the same change. The local test root holds no copy, so the bundled prompt was what the step 24 check used.
- [x] Production server deployment and capability checks completed on September 29. Macro publication is tracked in the [remaining plan](../client_smb_retirement.md#2-publish-compatible-macros).

**Tests.** Capability check.

**Done when.** Every kind from steps 13-16 is advertised.

Estimate: code edit 0 min, test/validation 20 min, total 20 min.

### Step 18 — Remove the SMB fallback from the transports

**Goal.** A Client PC reads and writes only through the Gateway; an unavailable Gateway is reported, never worked around. Follows decision 1.

**Read first.** [workspace_read_client.py](../../../frontend/app_server/services/workspace_read_client.py) `run_workspace_read`; [workspace_mutation_client.py](../../../frontend/app_server/services/workspace_mutation_client.py); [engine_calculation_service.py](../../../frontend/app_server/services/engine_calculation_service.py) `_select_transport`; [resq_sync_queue_service.py](../../../frontend/app_server/services/resq_sync_queue_service.py); [project_settings_data_processing_rules.js](../../../frontend/ui/project_settings/project_settings_data_processing_rules.js) `saveRulesDirectly`; business-logic contract rules 16-19; [hosted_save_http_client.py](../../../frontend/app_server/services/hosted_save_http_client.py) `require_same_server` and [hosted_save_enrollment.py](../../../python-api/src/arcrho_api/hosted_save_enrollment.py) (the server-identity check read the root's `config\config.json`); [user_identity_service.py](../../../frontend/app_server/services/user_identity_service.py) (the display-name lookup read the username index); the server-components round-trip tests `test_workspace_reads`, `test_workspace_mutations`, `test_engine_calculations`, which tested the fallback.

**Do.**
- [x] Both transports run `local` only in a server process; on a Client PC every failure is an error. A rejected credential reports "sign in to the server again" rather than a generic failure. Remove the now-redundant `gateway_required` arguments. Done: one selection, `workspace_read_client.require_client_gateway`, serves reads, mutations and Engine calculations: no or an unreadable credential is 401 "This PC is not signed in to the server. Sign in to the server again.", no answer is 503 "The server can't be reached. Try again once it is back.", an operation the Gateway does not list is 503 "The server needs updating before it can do this.", and a signature the Gateway refuses (401/403) is 401 "The server did not accept this PC's sign-in. Sign in to the server again." (`failure_error`; a hosted save's refused signature says the same). A polled read answers `unknown` for all of them. Every `gateway_required=True` argument is gone; a contract refusal of a mutation is now a 400 instead of a local run.
- [x] Engine calculations and every job submit/status (rules, source refresh, ResQ sync, import backup, DFM bridge) lose their request-file branch on a Client PC. The source refresh submit and status became Gateway-required in step 15. Done: `run_engine_calculation` and `run_hosted_dataset_operation` publish or run the route only in a server process (the hosting Engine's in-process calculator first); the job submits and polls are workspace mutations and reads, so they follow the transports. The ResQ import backup and the Bridge liveness look in `arcrho_api` call the same transports inside the app, so a Client PC refuses there too; a script outside the app still uses the drive, as rule 18 keeps for `arcrho_api`.
- [x] Delete the rules-save fallback to a direct save; a 503 shows the Engine-unavailable message. Done: `saveRulesDirectly` and `POST /data_processing_rules` are gone; the job's 503 is the save error.
- [x] Rewrite contract rules 16-19 and the domain docs that describe the fallback.
- [x] The server-identity check no longer reads the share (added by the coordinator). Sign-up stores the `server_id` the Gateway reports in the credential (`client_credential`, `enroll_once`; the server-side `provision_gateway_user` reads it from its own root), and every capability probe compares the Gateway's id with the credential's. The hazard of switcher step 3, a credential used against a different server, keeps its protection before the credential is sent; the folder the app is pointed at is no longer where a Client PC gets its data, so it is not compared. A credential signed up before ids were stored adopts the id of the first Gateway it probes (`remember_server_id`), because every production credential predates this step; a wrong server then refuses its signature, which asks the user to sign in again.
- [x] The client never reads `config\username_index.json` (added by the coordinator; steps 7 and 20 noted it). Hosted saves, reads, mutations and calculations send the login only and the server resolves the display name; `load_username_display_names` answers with an empty mapping outside a server process.
- [x] The DFM `Name` picker's refresh (`GET /dfm/method-index?refresh=true`, the `dataset_index` read) is Gateway-only with every other read, so it can no longer rebuild the index over the share.

**Client share access left after this step.** By design (plan section "What genuinely needs the client machine or the share"): Excel workbook reads and opening a workbook; handing a path to Explorer; a dataset-type or reserving-class-type file picked on this PC; the SQL Server and client-only CSV reads that feed step 22's upload; first-run setup's folder check; `arcrho_api` scripts outside the app. The Server tab's component status reads a server folder directly only when it is on this PC's own fixed disk (the local test root), never the share. Not by design, moved to step 19: `PUT /dataset/number-format-defaults` still writes `<root>\config\dataset_number_formats.json` directly (the plan's audit missed it; it needs a receipt mutation kind), and the hosted-save request-file branch still runs for a PC with no credential as well as for a kind the Gateway does not advertise.

**Historical follow-up, completed by step 23.** Before that step, the app had no "sign in again" action: a credential the server refuses stays in place, and startup signs up only when the file is missing, so recovering means removing the credential file and restarting. A Server-tab "Sign in again" button (the Windows sign-up returns the same user's current secret) would make the message actionable.

**Tests.** Transport-selection tests for each failure class on a Client PC and in a server process.

**Done when.** No client code path reaches `run local()` on a Client PC; the frontend suites pass.

Estimate: code edit 50 min, test/validation 25 min, total 75 min. Actual: code edit 28 min, test/validation 23 min, total 51 min (one selection function carried all three transports; most of the test time went to rewriting the tests that relied on the fallback, including python-api tests whose result depended on which module imported the app server first; checked on the local test root: normal use, the Gateway stopped and a rejected credential each with zero client file operations under the root).

### Step 19 — Remove the old SMB save path and leftover dead code

**Goal.** Delete what steps 1-18 left unreachable.

**Read first.** [engine_hosted_save_service.py](../../../frontend/app_server/services/engine_hosted_save_service.py) `_run_hosted_job_impl` and its helpers; [test_engine_hosted_saves.py](../../../frontend/tests/test_engine_hosted_saves.py); [dfm_persistence.js](../../../frontend/ui/method_pages/dfm/dfm_persistence.js) the method-file watcher block; [snowflake_service.py](../../../frontend/app_server/services/snowflake_service.py) `SNOWFLAKE_CONFIG_IMPORT_PATH`; [dataset_number_format_service.py](../../../frontend/app_server/services/dataset_number_format_service.py) `save_preferences` and the `DatasetNumberFormatsSaveRequest` schema; [valid_value_lists.js](../../../frontend/ui/shared/services/valid_value_lists.js) `loadReservingClassValidValueList` and the path-tree block of [reserving_class_service.py](../../../frontend/app_server/services/reserving_class_service.py); [dfm_method_index_router.py](../../../frontend/app_server/api/dfm_method_index_router.py) refresh route; `workspace_read_client.require_client_gateway`; [arcbot_host.js](../../../frontend/electron/arcbot_host.js) `getCodexAssistantProjectRoots` and `buildAssistantPrompt`.

**Do.**
- [x] Delete the hosted-save request-file branch; a kind the Gateway does not advertise is a 503 that says the server needs updating, and a PC with no credential is the 401 "not signed in" answer the other transports give (step 18 left this branch, which a PC without a credential still reaches). Done: `_run_hosted_job` selects its Gateway through `require_client_gateway`, the same selection reads, mutations and calculations use (so a silent Gateway is the 503 "can't be reached" and the capability answer is cached as theirs is), and the request publisher, the status polling and its cleanup are gone from the client. A server process never sends a hosted save (its routes do not run there) and is refused with 500. The client latency record keeps `transport` and gains the refusal `reason`; its status-poll fields went with the polling.
- [x] `PUT /dataset/number-format-defaults` writes `<root>\config\dataset_number_formats.json` from the client (found by step 18). Give it a receipt mutation kind (the save checks a revision, so a replay needs the stored answer), or record why it stays. Move the tests that used the branch onto the HTTP path. Update contract rules 15-16 and [hosted_save_http_transport.md](../hosted_save_http_transport.md). Done as `dataset_number_format_defaults_save` (receipt, Gateway-required; the route takes an optional `request_id`); `updated_by` is the signed login rather than the server process's account. Found on the way: the save's schema still required a `reserving_class` on every override, which the Preferences window stopped sending on 2026-08-25, so any save with a dataset type format answered 422; the field is gone (overrides are keyed by Dataset Type Name alone). The SMB tests of `test_engine_hosted_saves.py` were replaced by Gateway ones (every refusal, the exact request, a service error's status).
- [x] Delete the DFM method-file watcher and its external-change highlight helper, bumping module stamps. Done, with its flash style and the two diff helpers only it used; also deleted the unused `POST /dfm/method-index/refresh` route, its schema, the `dataset_index_rebuild` mutation kind and `refreshDfmMethodIndex` (step 9 found no caller). DFM module stamps are `20260927smb19` along the import chain.
- [x] Move the Snowflake config path to local settings (done 2026-09-26: it is `snowflake_config.txt` in the per-user settings folder).
- [x] Delete client-only SMB softeners that nothing uses any more (check `class_folder_scan_cache` and `file_read_cache` callers first; server processes still use them). Checked: both, and the dependent-propagation preflight and its protocol-path cache, are still used by services that run on the server host (calculated datasets, dataset types, project settings, every hosted save's Engine side), so none is client-only and nothing was deleted.
- [x] Decision 4: the Dataset Viewer's reserving-class value list reads the data's own class paths through a server read, and the path-tree cache file and its reader are deleted. Done: the list reads `GET /reserving_class_combinations` (752 paths for the local Fake project); `GET /reserving_class_path_tree`, its read kind, its service and config helpers, and the children read's use of the cache (with its `force` flag and cache fields) are gone, as is the list's unused crawl of the children route. A file an older version left in a project folder is not read or removed.
- [x] ArcBot's AI process (the Codex run ArcBot starts) is still granted read access to the project folder on the share (found by step 16). Move what it reads onto the server reads, or record why it stays; if it needs a design decision, record it under Open decisions instead of guessing. Completed in step 24 after decision 7.

**Tests.** The suites that covered the deleted code, rewritten or removed.

**Done when.** No request file is written by client code.

Estimate: code edit 35 min, test/validation 20 min, total 55 min. Actual: code edit 24 min, test/validation 18 min, total 42 min (the step 18 selection function carried the hosted save, and the mutation recipe the number-format save; checked on the local test root with a client process wired like `launch-app`: a dataset notes save and its restore went through the Gateway, the same save was refused with 503 for a kind the Gateway did not offer and 401 with no credential, the number-format save moved the revision once, named the signed user and answered a repeat of its request from the receipt, the class list read 752 combinations and the removed routes answered 404, all with zero client file operations under the root; the two changed files were restored).

### Step 20 — Gateway sign-up without the share

**Goal.** A new PC gets its Gateway credential over HTTP, and no client can read another user's secret.

**Read first.** [hosted_save_enrollment.py](../../../python-api/src/arcrho_api/hosted_save_enrollment.py); [hosted_save_enrollment_service.py](../../../frontend/app_server/services/hosted_save_enrollment_service.py); [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py); the Gateway's routes in `server-components/src/arcrho_gateway/main.py`; [hosted_workspace_http_transport.md](../hosted_workspace_http_transport.md) "Authentication Posture"; steps 2-3 of [local_server_root_and_server_switcher.md](local_server_root_and_server_switcher.md) (per-profile credentials, the `server_id` check in `hosted_save_http_client.probe_gateway`); `server_profile_service.py` (it read the registry for a server's address); `server-components/src/arcrho_credential/main.py` (the Excel add-in's helper enrolls the same way); `tools/local_server.py` `init` and `launch-app`.

**Do.**
- [x] A Gateway enrollment route authenticated by Windows (Negotiate), which mints or returns only the caller's secret; the client stores the Gateway URL, supplied by the installer, instead of discovering it from the share. Done as `POST /api/enroll` (`arcrho_gateway/enrollment.py`), advertised as `windows_enrollment`: an SSPI handshake on one kept-open connection, the login read from the handshake's Windows token (anonymous, Guest and non-user accounts refused), the secret minted into the registry once and returned sealed with the handshake's session key, at most ten handshakes a minute per address. The client (`request_windows_enrollment`) names no service principal, so Windows uses NTLM, which works whatever account the Gateway runs under. The address is the active profile's new `gateway_url`, or `ARCRHO_GATEWAY_URL` for a launch (`launch-app` sets it); the Server Connection dialog and the Server tab's Add Server ask for it. The installer does not supply it yet (follow-up below).
- [x] The client stops reading `config\arcrho_gateway.json`; the shared file becomes server-only. The app server's sign-up, the Server tab's address lookup and folder inspection, and the Excel add-in's credential helper no longer read it; the helper signs up at the production profile's address or `--url`. Sign-up keeps the `server_id` check: it probes through the same identity check every capability probe makes, so a Gateway serving another server's folder is refused before sign-up. The Gateway keeps writing the registry, because the released app still reads it; `configure_pilot.py` and `tools/local_server.py init` still write it directly, on the machine that holds it.
- [x] Deploy the Gateway, then check a fresh enrollment from the Client PC. The Client PC check is the user's time if it needs a new Windows profile. Deployed to the local test root and checked there: a process wired like `launch-app` with a credential path that did not exist signed up (the Gateway logged `enrolled user=xwei source=127.0.0.1`), then made one hosted read and one hosted save with the new credential; an open/list trace showed it never opened `config\arcrho_gateway.json`. The first local deploy failed sign-up because the frozen Gateway lacked `win32timezone`, which SSPI needs; both SSPI callers now import it. Production deployment is verified; a fresh-Windows-profile check remains.

**Completed follow-up.** The Credential helper was deployed to production. Step 18 removed client reads of the server id and display-name files. Installer configuration, registry permissions and fresh-profile validation are tracked in the [remaining plan](../client_smb_retirement.md).

**Tests.** Enrollment route tests; client enrollment test with no share access.

**Done when.** A Client PC with no share access enrolls and saves.

Estimate: code edit 60 min, test/validation 30 min, total 90 min. Actual: code edit 19 min, test/validation 16 min, total 35 min; under half the estimate because pywin32's SSPI wrapper and the Gateway's per-connection handler carried the handshake with no new dependency, and the loopback handshake let the route be tested end to end on this PC.

### Step 21 — Tests never reach a live Gateway

**Goal.** No test run on a developer PC can read from or write to a real server through the Gateway this PC is signed in to. Added 2026-09-27: step 3 found the rules and dataset-type change job tests sending audit appends to production's Gateway (refused only because production did not offer the operation yet). After the step 6 deploy, the same run would have written audit entries, and could have created test project folders, on production.

**Read first.** Memory `job-tests-read-live-gateway`; how the client finds its credential (`arcrho_api.config.gateway_config_path`, `frontend/app_server/config.get_gateway_config_path`, `load_gateway_config`); how the frontend, python-api, server-components and tools suites are run (`py -3.10 -m unittest` from `frontend/` and from `frontend/tests`, pytest from `.pytest-tools`; memory `python-test-runner`); the two stubs step 3 added in `frontend/tests/test_dataset_types_change_jobs.py` and `frontend/tests/test_data_processing_rules.py`; every Gateway HTTP opener (`hosted_save_http_client.py`, `workspace_read_client.py`, `arcrho_api/gateway.py`, `arcrho_api/hosted_save_enrollment.py`); the server-components tests that start their own loopback Gateway (`test_gateway`, `test_workspace_reads`, `test_workspace_mutations`, `test_engine_calculations`).

**Do.**
- [x] One guard every test entry point passes through, whichever way the suite is launched: for example a module every test imports first, or `sitecustomize`-style setup on the test paths. It points `ARCRHO_GATEWAY_CONFIG` at a missing file, and it makes the HTTP Gateway client refuse any URL that is not a loopback test server started by the test itself. A test that means to reach a Gateway opts in explicitly. Done as `arcrho_api/gateway_test_guard.py`. The test files share no setup module (224 of them each set their own paths) and a `sitecustomize` needs `PYTHONPATH`, so the guard sits in the layer every Gateway call already passes: the credential lookup (`arcrho_api.config`) and the one opener all four Gateway clients now build. It turns on only in a process launched as a test run (`-m unittest`, pytest, a `tests/test_*.py` run directly) and in that run's children, through an environment flag; the app, the server components, macros and notebooks never start that way. A loopback test Gateway opts in with `allow_test_gateway(url)`. IDE adapters whose main module is their own script are not detected.
- [x] Scan every suite for real outbound Gateway calls with the guard in "record" mode, and fix or stub each one found. Done with a throwaway socket-level scan that recorded every outbound connection and every read of the real credential, refusing anything not on loopback and the local test server's port, then with the guard's own record mode (`ARCRHO_TEST_GATEWAY_RECORD`). Before: the dataset-type and rules job tests, three cached-dataset delete tests, and the python-api ResQ import (both macros), import backup, sync queue and review macro tests all reached production's Gateway, including the pre-import backup, a write. After: none. The job tests now run the propagation checks as a server process against their temporary root; the delete tests stub the busy check; the python-api tests needed nothing beyond the guard. The scan also caught one leak that is not a Gateway: a server-deployment test's rollback posted a shutdown to the Admin Control port on this PC, which on the Server PC is the real one; it is now stubbed.
- [x] Keep step 3's two stubs, or replace them with the guard if it covers them. Replaced: the append swallows its failure, and the guard refuses it.

**Tests.** A test proving the guard refuses a non-loopback Gateway URL, and that a suite launched from each of the usual working directories picks the guard up.

**Done when.** A full run of the frontend, python-api, server-components and tools suites records zero outbound Gateway requests, and the job tests' results no longer depend on which server this PC uses.

Estimate: code edit 35 min, test/validation 15 min, total 50 min. Actual: code edit 19 min, test/validation 15 min, total 34 min.

### Step 22 — Client-only import sources upload to the server

**Goal.** A SQL Server import and a CSV only this PC can open are still read on the client, as decision 3 requires, and the rows are uploaded to the Gateway, which writes the master table; the client never writes the share. Split from step 15 on 2026-09-27; fits before step 17.

**Read first.** Decision 3 and open decision 2 above; step 15's Done notes; [source_table_service.py](../../../frontend/app_server/services/source_table_service.py) `_stream_mssql_to_master`, `_copy_csv_to_master`, `ensure_master_table`, `import_from_mssql`, `_commit_master`; [source_table_router.py](../../../frontend/app_server/api/source_table_router.py) `/source_table/import` and `/source_table/refresh`; `importSourceDataLocally` and `importSourceData` in [project_settings.js](../../../frontend/ui/project_settings/project_settings.js); [workspace_read_client.py](../../../frontend/app_server/services/workspace_read_client.py) `post_signed_json` and the signing it uses; [arcrho_gateway/main.py](../../../server-components/src/arcrho_gateway/main.py) request-size handling and [arcrho_gateway/receipts.py](../../../server-components/src/arcrho_gateway/receipts.py); memory `source-refresh-job-diagnosis` (a locked `master_table.csv` fails the swap); [source_refresh_service.py](../../../frontend/app_server/services/source_refresh_service.py) `get_source_table_refresh_status` and `import_source_path_is_shared` (the busy check and what "client-only" means); `mutation_receipt_path` in [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py) (the per-user folder name); [test_source_data_writes_hosted.py](../../../frontend/tests/test_source_data_writes_hosted.py) as the test model.

**Do.**
- [x] A contract for one upload: an upload id the client owns, numbered chunks of CSV text (compressed) sized well above the 256 KiB mutation limit but bounded, and a commit that names the chunk count, the byte total and the row count the client read. Chunks are stored under the server root's runtime temporary area per user and upload id; a repeated chunk overwrites the same numbered part, so a resend is idempotent, and the client can ask which parts the server holds to resume. The commit assembles the parts into the master table's staging file, checks them as open decision 2 settles, swaps it in atomically, writes `source_import.json::last_import` (source label, rows, columns, who, when), remembers the SQL Server pair for a SQL source, appends the audit entry, and removes the parts; a repeated commit answers from the first outcome. Abandoned uploads expire with the other receipts. Done in the new `source_table_upload_service` (both halves) with `source_table_upload_chunk` and `source_table_upload_commit` mutations and a `source_table_upload_status` read, all Gateway-required. Rather than a chunk above the 256 KiB mutation limit, each chunk is 256 KiB of raw CSV compressed with zlib level 1 and base64-encoded, which stays well inside that limit (the Fake table compresses about 2.4 times, so a chunk is at most about 145 KiB; a block that would not fit is halved), so no new Gateway route or size limit was needed. The parts live under `<root>/requests/source_table_upload/<user>/<upload id>`; the user folder name is the one mutation receipts use, now shared as `user_path_segment`. The commit refuses while a source refresh runs (423) and keeps its answer as `commit.json` in the upload folder, so neither kind needs a Gateway receipt; row counts on both sides are lines after the header through one `RowCounter`. Uploads older than the receipt window are removed when a new upload starts rather than at Gateway start, because the upload service, not the Gateway, owns that folder.
- [x] Client: the SQL Server import streams its batches into the upload instead of a staging file on the share, and a client-only CSV is read and uploaded the same way; the page shows upload progress in the shell's progress window and then runs the refresh job with `import_source` off, as today. `POST /source_table/import` and `POST /source_table/refresh` stop writing the share; both are Gateway-required. Done: both routes call `upload_source_table`, and the page polls `GET /source_table/upload_progress` (the client app server's memory) twice a second for the megabytes and rows sent. A CSV upload that failed part way resumes on the next import in the same app session while the file is unchanged (path, modified time and size); a SQL Server import always starts over, because a second query need not return rows in the same order. `import_from_mssql` stays for an Engine job asked to import a SQL Server project. Project Settings module stamps move to `20260927src2`.
- [x] Docs: the `source_table` domain doc, `workspace_mutations.md` (or the new operation's own section), the Status line and the plans index; a release fragment.

**Tests.** Upload contract validation; a resent chunk and a resumed upload land one master table; a short or mismatched commit refuses and leaves the previous master table; a commit replay; client transport tests with the Gateway on and off; the SQL Server streaming path against the fake ODBC driver the source-table tests already use. Local check: import a scratch copy of the Fake project from a CSV on a local drive and confirm zero client file operations under the root.

**Done when.** Importing a SQL Server table or a client-only CSV writes nothing on the share from a Client PC, and the previous master table survives any failed upload.

Estimate: code edit 75 min, test/validation 35 min, total 110 min. Actual: code edit 16 min, test/validation 20 min, total 36 min (under half the estimate because the existing mutation transport carried the chunks unchanged once they were sized to fit it; checked on the local root: a scratch copy of the Fake project was pointed at an 88 MB, 346,115-row CSV on C:, an upload was cut at chunk 150 of 337 and resumed without resending the first 150, a full upload took about 9 s (9.4 MB/s over loopback), the master table matched the CSV byte for byte, the refresh job ran on it, the client process opened nothing under the root but `config\config.json` for reading, and the copy was deleted).

### Step 23 — Sign in again from the app

**Goal.** Since step 18, a PC whose server sign-in is refused or missing shows "Sign in to the server again", but nothing in the app does that: startup signs up only when the credential file is missing, so recovery means deleting the file and restarting. Give the message an action. Added 2026-09-27 after step 18; it must land before the app release that carries step 18.

**Read first.** Step 20's Windows sign-up (`python-api/src/arcrho_api/hosted_save_enrollment.py`, `server-components/src/arcrho_gateway/enrollment.py`: it returns the caller's current secret); step 18's error mapping in `frontend/app_server/services/hosted_save_http_client.py` and the 401 messages; the Server tab (`frontend/ui/server/`) and the Server Connection dialog (`frontend/ui/shell/root_path_settings.js`); memory `concise-ui-message-copy`.

**Do.**
- [x] An app-server route that re-runs the Windows sign-up for the active server profile and replaces the credential file only after the new one is received (never leaves the PC with no credential), keeping the credential's stored server id and refusing a Gateway whose id differs. Done as `POST /server_profiles/sign_in` over `arcrho_api.hosted_save_enrollment.sign_in_again`, which shares one probe-sign-up-write helper with `enroll_once`: it signs up at the launch address, else the profile's, else the credential's own, writes the file this process uses (a launch override included, so a `launch-app` session can use it) under the credential lock only after the handshake returns, keeps the stored `server_id` (a credential without one takes the Gateway's), and refuses a Gateway reporting another id with the 409 mismatch before signing up. A silent Gateway is 503 and a failed handshake 502 with its reason; each leaves the old file byte for byte.
- [x] A "Sign in again" button on the active server's row in the Server tab, and a way to reach it from the 401 message (a link in the status message that opens the Server tab is enough). Done: the row in use (the active profile or `Set at launch`) shows Sign in again where the others show Switch. Rather than a link to the tab, the shell's status bar shows a Sign in again action beside any message carrying "Sign in to the server again" and runs the same route, reporting "Signed in again as <user>." in place; a Node test pins the phrase to both Python sign-in messages. The Server tab's Components panel now says a refused sign-in as such instead of "Gateway not answering".
- [x] Clear the process's cached capabilities and credential after a successful sign-in so the next request uses it without a restart. Done: the capability cache (which also held any cached probe failure) is the only per-process state; the credential is read per request.

**Remaining limitation.** Inline-only sign-in messages are tracked in the [remaining plan](../client_smb_retirement.md#known-limitations).

**Tests.** Route tests: a refused credential is replaced by the sign-up's; a failed sign-up leaves the old file untouched; a different server id is refused. Node test for the button and the message link.

**Done when.** On the local test root, a client with a wrong-secret credential gets the sign-in message, presses Sign in again, and its next read succeeds without a restart.

Estimate: code edit 25 min, test/validation 15 min, total 40 min. Actual: code edit 9 min, test/validation 9 min, total 18 min (under half the estimate because sign-up already had one probe-and-write path to share and the credential is read per request, so only the capability cache needed clearing; checked on the local test root with a client app server wired like `launch-app` and a temporary copy of the local credential carrying a wrong secret: a hosted read answered 401 with the sign-in message, Sign in again from the status bar and then from the Server tab each replaced the secret and kept the server id, and the next hosted read answered 200 without a restart; a credential naming another server id was refused with 409 and left untouched; no server component changed, so nothing was deployed).

### Step 24 — ArcBot reads project data only through the server

**Goal.** ArcBot's AI process is no longer pointed at the project folder on the share; what it may read follows decision 7. Split from step 19 on 2026-09-27.

**Read first.** Open decision 7; step 4 and step 16 above (what ArcBot stages and no longer copies); [arcbot_host.js](../../../frontend/electron/arcbot_host.js) `getCodexAssistantProjectRoots`, `getArcBotReadableRootsForSandbox`, `buildAssistantPrompt` and the request handler that logs `serverReadRoots`; the ArcBot prompt template (`config\arcbot` on the server, the bundled prompt in the app) for `PROJECT_ROOT` and `CLI_ROOT`; [arcrho_api/gateway.py](../../../python-api/src/arcrho_api/gateway.py) and memory `scripts-save-through-gateway-client`; `getArcBotCodexEnv` in arcbot_host.js (which `arcrho_api` ArcBot's Python imports) and [gateway_test_guard.py](../../../python-api/src/arcrho_api/gateway_test_guard.py) (every `arcrho_api` import goes through it, including inside ArcBot's sandbox); the widget's Folder Permissions text in [ai-assistant/index.js](../../../frontend/ui/ai-assistant/index.js) and [template.js](../../../frontend/ui/ai-assistant/template.js).

**Do.**
- [x] Take the option the user chose in open decision 7. For the recommended one: stop resolving the share as ArcBot's project root, start the Codex run in the local exchange folder, and replace `PROJECT_ROOT` in the prompt with the instruction to read other project data through `arcrho_api.gateway`; keep the user's own configured readable folders (a folder this PC chose is not the share by default). Done: `getCodexAssistantProjectRoot(s)` and the edit staging's `net use` lookup of the server folder are gone; every run starts in `Documents\ArcRho\ArcBot\workspace`, and the configured folder is used only as text to keep the staged copy's project layout. The bundled prompt drops `PROJECT_ROOT`, `NETWORK_ROOT_NOTE` and the stray `EXCHANGE_SERVER_ROOT` line and gains `READABLE_FOLDERS` (the user's folders, which never reached the prompt before) and a "Project data" section: read with `GatewayClient().read(kind, ...)` from the kinds of `arcrho_workspace_read_contract`, use only `read`, and say so when no read serves a file. The page context and the Claude path name a file by its name only (`withFileNamesOnly`), since a page's path points into the server folder. `GatewayClient` already signs with the active profile's credential (`arcrho_api.config.gateway_config_path`, covered by `test_gateway_client`), and a launch's `ARCRHO_GATEWAY_CONFIG` reaches ArcBot's Python through the inherited environment. Found on the way: in ArcBot's read-only sandbox every `arcrho_api` import failed, because the test guard asked `tempfile` for the temp folder at import and finding it writes a probe file the sandbox refuses; the guard's missing-credential path is now beside the module. And the packaged app never put `arcrho_api` on ArcBot's import path (only the development source folder), so the host now puts the bundled wheel there; it is pure Python and imports straight from the file, so ArcBot uses the app's own client and read kinds with no install.
- [x] Bump the `?v=` stamps of any edited renderer module and update the pinned tests. Done: the Folder Permissions text no longer says the server folder is included; `template.js` is now imported with a stamp, and the widget's import chain is `20260927smb24` through `ui_shell.js` and Arcode's `main.js`.

**What ArcBot can no longer do.** Browse the project folder: open a raw CSV, a sidecar or method file by path, or list a folder. It answers project-wide questions through the registered reads instead. The sandbox-access limitation is tracked in the [remaining plan](../client_smb_retirement.md#known-limitations). On this PC Codex's Windows sandbox did not see `E:` at all, and its network block is proxy variables, which the Gateway client ignores (it builds its opener without proxies), so a read reaches a LAN Gateway; the model's own requests elsewhere are still refused.

**Tests.** Node tests: the prompt and the Codex start never name the workspace root or a mapped-drive path of it; the configured readable folders still reach the prompt.

**Done when.** No ArcBot request names or resolves the project folder on the share, and ArcBot answers a question about another object of the project through the server on the local test root.

Estimate: code edit 30 min, test/validation 20 min, total 50 min. Actual: code edit 18 min, test/validation 14 min, total 32 min (checked on the local test root with the host wired like `launch-app` against the dev test app's app server: a review and an edit of a Fake-project DFM started in the exchange folder, named no server folder or share path and resolved no mapped drive, the user's extra folder reached the prompt, and the prompt's `dataset_index` read ran inside the real Codex app-server with ArcBot's read-only policy and returned the class's index signed as the local user; the same read from a freshly built wheel on the import path reached the Gateway too; the Engine and Gateway bundles carry `arcrho_api`, so the guard fix makes them stale with no behaviour change and it ships with their next deploy).
