# Local Server Root and Server Switcher

Status: Closed 2026-11-04 — all 8 steps done. Step 6 landed with the Arco 1.8.0 release on 2026-09-27; checked 2026-11-04 that production's Gateway reports the `server_id` held in `E:\ArcRho Server\config\config.json` and lists `server_component_status`. Offline use for every user (open decision 3) was not taken up and would need its own plan.

History: Steps 1-3 done 2026-09-26 — a private test server runs on the developer PC at `C:\Arco Server` beside production, with its own Gateway, credential and app profile, built from the working tree by `tools/local_server.py`; the app keeps a list of servers, one active, each with its own credential, behind three new app-server routes; every server root carries an id its Gateway reports, and the app refuses a Gateway whose id differs from its folder's (the server side reaches production with the step 6 deploy). Step 4 done 2026-09-26: a Server tab opened from Home lists the servers by name and address with a health dot, adds a server from its folder, and switches by restarting the app once no tab has unsaved changes. Step 7 done 2026-09-26: the tab's Components panel lists the server's running components with machine, user, last heard and stale state, grouped by role with each stop switch, read from disk for a folder on this PC and through the Gateway otherwise (the Gateway side reaches production with the step 6 deploy). Step 8 done 2026-09-26: for a server whose folder is on a fixed disk of this PC the panel starts and stops it, through the same module `tools/local_server.py` now uses; production shows only a line saying it is managed from Admin Control on the Server PC. Step 5 done 2026-09-26: the title bar shows a small badge naming the server whenever it is not production, including a server set at launch, and clicking it opens the Server tab. Step 6 (the release) is planned and not started; the Server tab was added 2026-09-26 at the user's request; offline use for every user is recorded as a direction with open decisions, not yet broken into steps.
Last updated: 2026-11-04
Related: [client_smb_retirement.md](../client_smb_retirement.md) (the first work tested this way), [hosted_workspace_http_transport.md](../hosted_workspace_http_transport.md)

**How this ships.** Step 1 changed only tools, docs and two launch-time switches in the desktop host that do nothing unless a launch sets them; it reaches users with the next frontend release and needs no server deploy. Steps 2, 4, 5 and 8 are frontend-release changes. Steps 3 and 7 add a field to the Gateway's capability answer and a registered read kind, additive server deploys that must land before the frontend release that uses them.

## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | Est. | Actual | What changed for the user |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | A private test server runs on the developer's PC beside production | [x] | 2026-09-26 | 90 min | not clocked | The developer can build, deploy and try server changes on their own PC; nobody else sees them. |
| 2 | The app remembers more than one server, each with its own sign-in | [x] | 2026-09-26 | 70 min | 15 min | The app can hold several servers and switch the active one, and each server signs in with its own credential; there is no screen for it yet. |
| 3 | The app refuses a server whose address and data folder do not belong together | [x] | 2026-09-26 | 55 min | 30 min | Pointing the app at one server's folder while signed in to another server is refused with a plain message instead of mixing the two. |
| 4 | A Server tab opened from Home lists servers by name and address and switches between them | [x] | 2026-09-26 | 90 min | 37 min | Home has a Server card that opens a Server tab listing each server by name and address with a live health dot; a server can be added by choosing its folder, and switching restarts the app but waits until no tab has unsaved changes. |
| 5 | The window shows which server it is using whenever it is not production | [x] | 2026-09-26 | 30 min | 15 min | The title bar shows a small badge naming the server whenever it is not production, with its address in the tooltip; clicking it opens the Server tab. |
| 6 | Deploy the server side and ship the app | [x] | 2026-09-27 | 30 min | not clocked | The Server tab and the server badge reached every user in Arco 1.8.0, and production's server answers with its own identity and its component list. |
| 7 | The Server tab shows which server components are running and how long since each was last heard from | [x] | 2026-09-26 | 60 min | 26 min | The Server tab lists each running part of the server with its machine, user and how long since it was last heard from, flags silent ones as stale, and shows when a part's stop switch is on. |
| 8 | A server on this PC can be started and stopped from the Server tab | [x] | 2026-09-26 | 45 min | 22 min | The Server tab starts and stops a server whose folder is on this PC, asks before stopping the one the window uses, and shows the parts going and coming back; production says it is managed from Admin Control on the Server PC. |

Overall: 8 of 8 steps done. Estimated 470 min; actual 145 min (steps 1 and 6 were not clocked). Order: 2, 3, 4, 7, 8, 5, then 6.

## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one workflow subagent), one commit.
- Note the clock before the first file is read and again at the commit, keeping the two parts apart: time spent reading and editing, and time spent running tests, checks and deploys.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date, the actual minutes and the one-line user note, update the "Overall" count and actual total, append the actual to the step's `Estimate:` line, and update the `Status:` line at the top and this plan's row in the [plans index](../README.md).
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.

## The local test root (in use)

A second, independent server root on the developer PC. Production (`E:\ArcRho Server`, the Server PC share) is never written by it.

```
py -3.10 tools/local_server.py init                  # folders, config, local Gateway registry, credential, Orchestrator
py -3.10 tools/local_server.py copy-project          # NJ_Annual_Prod_202605_Fake by default; --overwrite to refresh
py -3.10 tools/local_server.py deploy                # build Engine + Gateway from this working tree into the local root
py -3.10 tools/local_server.py start | stop | status
py -3.10 tools/local_server.py launch-app            # dev-mode app against the local root
```

What keeps it apart from production:

| Concern | How it is kept apart |
| :--- | :--- |
| Server data | Every component finds its root from where its exe sits, and heartbeats, request queues, receipts and kill switches are all under the root. The tool refuses a root that is a network path, not on a local fixed disk, or the production root. |
| Builds | `deploy` sets both `ARCRHO_DEPLOY_ROOT` and `ARCRHO_ROOT` to the local root and drops every inherited root override. Without `ARCRHO_ROOT` the Engine and Orchestrator builds look for their kill switches under the repository instead. |
| Network | The local Gateway registry binds `127.0.0.1:28767`, written before the Gateway first starts. Left to itself the Gateway writes a registry bound to every interface. |
| Sign-in | The local credential is `%APPDATA%\ArcRho\arcrho_gateway.local.json`. The production credential `arcrho_gateway.json` is untouched, and so are the Excel add-in and scripts, which always use it. |
| The app | `launch-app` sets `ARCRHO_SERVER_ROOT`, `ARCRHO_GATEWAY_CONFIG`, `ARCRHO_GATEWAY_URL` (where the app signs up when that credential is missing, since 2026-09-27), a separate Electron profile (`ARCRHO_USER_DATA_DIR`, so it never reuses a running app's backend) and backend port 28785. ArcBot follows `ARCRHO_SERVER_ROOT` too. |
| ResQ | Not available: ResQ lives only on the Server PC. The local root never starts a Bridge, so ResQ import, export and sync are production-only. |
| Components | Engine and Gateway are built from the working tree. The Orchestrator is copied from production by `init`; it starts the Engines and the Gateway and cleans stale heartbeats. `stop` uses the root's kill switches, never a process kill, so nothing on another root is touched. |

Known limits, none of which writes to production:

- A copied project still names the production share as its **import source** (`field_mapping.json`, `source/source_import.json`), so a source refresh on the local root reads production's source files. It never writes there.
- Five project-level caches store absolute `E:\ArcRho Server` paths; on the local root they miss and rebuild the first time they are read.
- `%APPDATA%\ArcRho\prefs`, `app_endpoint.json` and the logs under `%LOCALAPPDATA%\ArcRho\logs` are shared by every app on the PC. A macro or notebook run outside the app finds "the running app" through `app_endpoint.json`, whichever app wrote it last.
- `arcrho_api.gateway` (scripts and notebooks) signs with `ARCRHO_GATEWAY_CONFIG` when set, otherwise the active server profile's credential (step 2). A notebook started outside a `launch-app` session therefore uses the production credential unless the local profile is active.
- Ports are per machine, so one local root runs at a time.
- There is no Build Listener for the local root; `deploy` runs the build scripts directly, which is fast on a local disk.
- Never save the Server Connection page in a `launch-app` session. It writes the per-machine `workspace_paths.json` that the production app also reads.

## Why a switcher, and what the investigation found (2026-09-26)

Changing the root on the Server Connection page today is unsafe for anything but production:

- **The Gateway does not follow the root.** Enrollment returns "existing" whenever a credential file exists (`python-api/src/arcrho_api/hosted_save_enrollment.py`, `enroll_once`). After switching the root to another server, hosted reads, saves and calculations still go to the old Gateway while share-only routes use the new folder. The client never checks which root a Gateway serves.
- **Two resolvers.** `arcrho_api/config.py` owns root resolution, but `frontend/app_server/config.py` has its own reader and writer of `workspace_paths.json` with a different order, and `arcrho_api` caches the file value at import and never reloads it, so macros keep the old root until the backend restarts.
- **Pages keep the old server.** A switch posts a message to open tabs; Project Instance and Home ignore it.
- **The server is shown nowhere** but the dialog's path field: not in the status bar, title bar or About box.
- **Profiles need a path for now.** Until retirement-plan steps 11, 18 and 20 land, many features still read the share, so a server entry must carry its folder as well as its address.

## Open decisions

Decisions 1 and 2 were taken as recommended on 2026-09-26, when the user asked for the Server tab to be built; the steps below follow them. Decision 4 was added the same day.

1. **What the app shows as the server's identity.** Taken as recommended: the profile name and its Gateway address, for example `Production — NE7SASWPN02:28767` and `Local test — 127.0.0.1:28767`, with the folder path in a details section. A custom `arco://` scheme reads well but is not a real address and cannot be pasted into a browser for a health check.
2. **Switching restarts the app server, not the window.** Taken as recommended, because it clears every per-process cache and the stale `arcrho_api` root in one step. The alternative, a live switch, needs every page to handle the change message, and two do not today.
3. **Offline use for every user** (not broken into steps yet). The installer already detects a local root and can start the Launcher at login; the missing pieces are shipping the Gateway and Credential in the server payload, seeding a loopback Gateway registry and enrolling the installing user, making the Bridge optional, and — the large one — moving projects between the user's PC and production. Recommended scope for a first version: **a local sandbox**. The user copies a project down and works on it freely, and nothing is pushed back. True offline editing with sync-back needs a conflict rule per file kind and is a separate plan.
4. **May the Server tab stop and start production's components?** A kill switch on production stops that component for every user, and a Client PC cannot start a process on the Server PC. Recommended: the tab monitors every server, but offers start and stop only for a server whose folder is on this PC (step 8); production stays managed from Admin Control on the Server PC, and the tab says so. Steps 7 and 8 follow the recommendation; a later step can add production controls if the answer changes.

## Suggestions

- **Give every server an identity.** Put a `server_id` (a GUID written once) in `<root>\config\config.json` and return it from the Gateway's `/api/capabilities`. The client stores it in the profile and refuses a Gateway whose id does not match the folder it is pointed at. This closes the mixed-server hazard for good, and it is what makes a URL-only profile safe after SMB retirement. It is step 3.
- **One credential per server.** Derive the credential file from the profile id (`arcrho_gateway.json` for production, `arcrho_gateway.<id>.json` otherwise) instead of storing it, and route every reader — app server, `arcrho_api.gateway`, the credential helper — through one helper. The Excel add-in stays tied to the server it was installed from.
- **Show the active server.** A small badge in the title bar whenever the active server is not production, so a test session is never mistaken for real work.
- **Keep `workspace_root` at the top of `workspace_paths.json`.** The installer and the running-app probe read that field, so a profile list must mirror the active root into it.
- **Grow the dev control center.** `tools/arcrho_dev_control` could show the local root's heartbeats and run `deploy`, `start` and `stop`, as it already does for the dev app.
- **Test the SMB retirement against the local root first.** Each deploy step in that plan becomes "deploy locally, check, then deploy to production".

## Rough size

Estimated 470 minutes across 8 steps: 295 minutes of code edit and 175 of test, validation and deploy. Step 1 is done. Offline use for every user is not estimated until decision 3 is taken.

## Plan

### Step 1 — Local test root (done 2026-09-26)

**Goal.** A private server root on the developer PC that server components can be built into and the dev app pointed at, without touching production.

**Do.**
- [x] `tools/local_server.py` with `init`, `copy-project`, `deploy`, `start`, `stop`, `status` and `launch-app`, and its tests in `tools/tests/test_local_server.py`.
- [x] `ARCRHO_USER_DATA_DIR` in `frontend/electron/main.js`, so a second dev app has its own Electron profile and backend.
- [x] ArcBot follows `ARCRHO_SERVER_ROOT` (`frontend/electron/arcbot_host.js`).
- [x] Stand up `C:\Arco Server`, copy the Fake project, build Engine and Gateway, check heartbeats and health.
- [x] "Local test root" in `AGENT_GUIDELINES.md` and the deployment authorization doc.

**Done when.** `status` shows a live Orchestrator, Engine and Gateway, and the Gateway health check answers on `127.0.0.1:28767`.

Estimate: code edit 55 min, test/validation 35 min, total 90 min. Actual: not clocked; it was done in the same session as the audit.

### Step 2 — Server profiles

**Goal.** The app keeps a list of servers, one active, each with its own folder, address and credential; one module owns it.

**Read first.** `python-api/src/arcrho_api/config.py` (`get_server_root`, the workspace-paths reader and writer); `frontend/app_server/config.py` (`load_workspace_paths`, `save_workspace_paths`, `get_gateway_config_path`); `python-api/src/arcrho_api/gateway.py`; `frontend/app_server/api/workspace_paths_router.py`.

**Do.**
- [x] `profiles` and `active_profile` in `workspace_paths.json`, owned by `arcrho_api.config`; the active root mirrored into `workspace_root`. With no `profiles` key, one `default` profile is built in memory from today's file and nothing is written.
- [x] One credential-path helper in `arcrho_api.config`: `ARCRHO_GATEWAY_CONFIG`, then the active profile. `app_server/config.py` and `arcrho_api/gateway.py` use it.
- [x] `app_server/config.py` delegates its reader and writer to `arcrho_api.config` and drops its own.
- [x] `GET /server_profiles`, `POST /server_profiles`, `POST /server_profiles/activate` (activate then asks for the existing app restart).

**Tests.** Migration from today's file writes nothing; env overrides still win; each profile resolves its own credential.

**Done when.** Two profiles can be stored and activated from the API, and each activation uses its own credential.

Estimate: code edit 50 min, test/validation 20 min, total 70 min. Actual: code edit 10 min, test/validation 5 min, total 15 min; under a quarter of the estimate because enrollment already followed the credential path and root, so only the path helper had to change.

### Step 3 — Server identity

**Goal.** A server says which one it is, and the client refuses a Gateway that serves a different root from the one it is pointed at.

**Read first.** `server-components/src/server_config.py`; the capabilities handler in `server-components/src/arcrho_gateway/main.py`; `frontend/app_server/services/workspace_read_client.py` (`cached_gateway_capabilities`); `frontend/app_server/services/hosted_save_http_client.py` (`probe_gateway`, which every capability check goes through, including the hosted-save one); `gateway_stopped` in `server-components/src/arcrho_gateway/build_exe.py`; the `reset-config` handler in `server-components/src/arcrho_admin/main.py`.

**Do.**
- [x] `server_id` written once into `config.json` by `ensure_server_config`, and by the Gateway's deploy (`ensure_server_id`, while the Gateway is stopped), which is how production gains one in step 6. An Admin Control configuration reset keeps it. The key and the client's reader live in `arcrho_api.config`.
- [x] `/api/capabilities` returns it (additive); the Gateway reads it once as it starts.
- [x] The client compares it with the active root's `config.json` and refuses with a plain message (409, never a fall back to the share) in `probe_gateway`. A found root id is kept for the process; a missing one is re-read after 30 s.

**Rule chosen for a missing id.** The ids must be equal, and both sides lacking one is the only agreement allowed without an id. So a Gateway that reports no id is refused whenever the folder has one (the folder was updated but the Gateway was not, or the credential belongs to another server), and a Gateway that reports an id is refused for a folder without one. Production's folder and Gateway both lack an id until the step 6 deploy writes it, so the working tree keeps working against production today; once that deploy lands every Gateway carries an id and the "no id" case is refused everywhere. The check covers the desktop app's app server only; scripts and notebooks (`arcrho_api.gateway`) and the Excel add-in do not make it.

**Tests.** Mismatch refused; a Gateway that sends no id is refused for a folder that has one; a refused read never runs over the share; the id is written once and survives a reset (`frontend/tests/test_gateway_server_identity.py`, `server-components/tests/test_server_identity.py`).

**Done when.** Pointing the app at the local folder with the production credential is refused rather than served.

Estimate: code edit 35 min, test/validation 20 min, total 55 min. Actual: code edit 15 min, test/validation 15 min, total 30 min.

### Step 4 — The Server tab, opened from Home

**Goal.** A "Server" card on Home opens one Server tab. It lists the servers by name and address, marks the active one, adds one by choosing its folder, and switching restarts the app server. The Server Connection dialog stays for first-run setup and links to the tab.

**Read first.** [shell.md](../../../frontend/docs/ui/shell.md) "Common Change Tasks" (the recipe for a new tab type); `frontend/ui/shell/home_view.js` (the fixed card groups and their click wiring); `frontend/ui/shell/tab_actions.js` (`openProjectSettingsTab`, the single-instance pattern, and `RESTORABLE_ACTIVITY_TYPES`); `frontend/ui/shell/iframe_host.js` `ensureIframe` (the `agent_guide` case is the simplest template); `frontend/ui/shell/root_path_settings.js`; `frontend/ui/shell/app_lifecycle.js` (restart); `frontend/ui/shell/shell_messages.js` (where iframe requests are handled, and the harness `tests/project_settings_shell_progress.test.mjs` uses to test one); `frontend/ui/shell/shell_activity_history.js` and `home_card_icons.js` (the restorable-type list and Home icon kinds); skill `arcrho-ui-design`.

**Do.**
- [x] A `Server` card in Home's General group, `openServerTab()` in `tab_actions.js`, a `server` tab type in `iframe_host.js`, and a tab icon.
- [x] A new page `frontend/ui/server/server.html` (+ its script and styles) fetching the step 2 routes: one row per profile with name, address, a health dot from `/api/health` (probed by the app server, not the page), and the active one marked.
- [x] Add server: pick the folder; the address fills in from the folder's Gateway registry; the name is editable. A details section shows the folder, credential file and user.
- [x] Switching is blocked while any tab has unsaved changes; an env override shows the server as "set at launch" and read-only.
- [x] Update `shell.md` and bump the `?v=` stamps of every edited module.

**Tests.** Node tests for the list, add and blocked switch; the new tab type opens once and is restorable.

**Done when.** The developer opens the Server tab from Home and switches between production and the local root and back, and each side's saves land on its own server.

Estimate: code edit 60 min, test/validation 30 min, total 90 min. Actual: code edit 17 min, test/validation 20 min, total 37 min; under half the estimate because the shell's tab, dirty-state and restart pieces needed only wiring. The "Done when" round trip was not driven on the developer's own app, by instruction: the switch was checked by tests and a mocked render, and the real app was checked in a `launch-app` session, which shows "Set at launch".

**What was built.** `GET /server_profiles` also returns `current` (this process's server) and each server's credential user, and falls back to the folder's Gateway registry for the address before a credential exists; `GET /server_profiles/health` and `GET /server_profiles/inspect` were added. The switch runs in the shell (`handleServerSwitchMessage` in `shell_messages.js`, message `arcrho:server-switch`). The page is `frontend/ui/server/` with its rules in `server_model.js`; the Components panel is an empty placeholder for step 7. The Server tab's release fragment is in, and step 5 added the badge's line to it.

### Step 5 — Active-server badge

**Goal.** The title bar shows the server's name whenever it is not production.

**Read first.** The title bar in `frontend/ui/index.html` and its shell script (`frontend/ui/shell/ui_shell.js`, `shell.css`); `frontend/app_server/services/server_profile_service.py` `list_server_profiles`; `frontend/ui/server/server_model.js` (`serverLabel`, `isSetAtLaunch`); [server.md](../../../frontend/docs/ui/server.md).

**Do.**
- [x] `GET /server_profiles` (not `/workspace_paths`, which the plan first named) reports `default_profile`, production's id, beside the `current` and `set_at_launch` it already gave, so the shell makes one read and no new route is needed.
- [x] A small badge in the title bar whenever a launch override is set or the active profile is not the default. It names the profile (`Set at launch` for an override), its tooltip adds the address and folder, and clicking it opens the Server tab.

**Tests.** Node tests for the badge rule and the shell module's one read, render and click (`frontend/tests/server_tab.test.mjs`); the listing reports the default profile (`frontend/tests/test_server_profiles_routes.py`).

**Done when.** A `launch-app` session and a switched session both show the badge; production shows none.

Estimate: code edit 20 min, test/validation 10 min, total 30 min. Actual: code edit 8 min, test/validation 7 min, total 15 min; half the estimate because the listing and the label rules already existed. The `launch-app` session was checked in the real app (the badge reads `Set at launch` and opens the Server tab); the switched and production cases were checked with the model tests and a mocked render in both themes, because switching the developer's own app was out of bounds.

**What was built.** The rule is `activeServerBadge` in `server_model.js`, reusing the tab's name and address rules; `frontend/ui/shell/server_badge.js` makes the one read as the shell starts and wires the click. The badge uses the themes' warning tokens, so it needs no per-theme rule. A Server Connection save does not change which profile is active, so the badge does not re-read on it.

### Step 6 — Deploy and release

**Goal.** Production's Gateway reports its identity and serves component status (steps 3 and 7), then the app that uses them ships.

**Do.**
- [x] Deploy to the local root and check; then `python server-components/deploy.py`.
- [x] The frontend release follows the server deploy; the badge's release line is already in the Server tab's fragment (step 5).

**Done when.** Production's `/api/capabilities` carries `server_id` and lists `server_component_status`, and the released app switches servers.

Estimate: code edit 5 min, test/validation 25 min, total 30 min.

### Step 7 — Component status in the Server tab

**Goal.** The Server tab shows the active server's components (Orchestrator, Engines, Gateway, Bridge and its workers, Admin Control): one row per running instance with its machine, user, when it was last heard from and whether that is stale, plus each role's stop switch. Fits after step 4 and before the step 6 deploy.

**Read first.** `server-components/src/arcrho_admin/main.py` `list_instances`, `instance_sources`, `stale_after_seconds` (the rules this must match); `server-components/src/server_config.py` (the `apps.<role>.kill_all` switches); memory `adding-a-hosted-workspace-read`; `docs/plans/client_smb_retirement.md` (every new kind is `gateway_required=True`); `frontend/app_server/services/workspace_read_client.py` `run_workspace_read` (what a Gateway-required read raises when the Gateway is silent); `server-components/src/arcrho_admin/build_exe.py` (Admin Control's frozen build already has `python-api/src` on its path); `tools/local_server.py` `require_local_root`.

**Do.**
- [x] One reader of `<root>\runtime\instances\arcrho_<role>\*.json` and the kill switches, in `python-api` so the Admin tool, the Gateway and the app server share it; Admin Control uses it too.
- [x] A `server_component_status` workspace read kind, `gateway_required=True`, and `GET /server/status`. For a server whose folder is on this PC the app server reads the disk directly, so the tab still reports when that server's Gateway is down; for any other server, a Gateway that does not answer shows as "Gateway not answering" and nothing is read over the share.
- [x] The tab refreshes the panel every few seconds while it is visible.

**Tests.** Reader tests for active and stale rows and missing folders; transport tests (Gateway used for a remote server, the disk for a local one, never the share).

**Done when.** The tab shows the local root's live Orchestrator, Engines and Gateway, and a stopped Engine turns stale within its role's threshold.

Estimate: code edit 40 min, test/validation 20 min, total 60 min. Actual: code edit 14 min, test/validation 12 min, total 26 min; under half the estimate because the workspace-read registry, the Gateway build and Admin Control's import path needed no changes to take a new shared module.

**What was built.** The reader is `python-api/src/arcrho_server_component_status.py` (heartbeats, stale rule, stop switches, and the fixed-disk check `tools/local_server.py` now uses too); Admin Control's instance table calls it. The app server's `server_profile_service.server_component_status` picks the transport; a Gateway too old to advertise the read says it needs updating rather than "not answering", which is what production shows until step 6. The panel checks its own frame's layout as well as the page's visibility, because an inactive shell tab hides its frame without changing the page's visibility state. The local tool's own `status` and `stop` still judge heartbeats by file age (30 s); step 8 moves them onto this reader. The Server tab's release fragment gained one line for the panel.

### Step 8 — Start and stop a server on this PC

**Goal.** For a server whose folder is on this PC, the Server tab starts it (launches its Orchestrator) and stops it (sets its kill switches and waits for the heartbeats to go). Production shows no controls and a line saying it is managed from Admin Control on the Server PC (decision 4).

**Read first.** `tools/local_server.py` `start`, `stop`, `require_local_root`; step 7's reader; `frontend/electron/backend_lifecycle.js` (the app ends its app server with `taskkill /T`, so a child the app server launches dies with it); the main loop of `server-components/src/arcrho_orchestrator/main.py` (it checks its stop switch every 15 s).

**Do.**
- [x] Move start, stop and the local-root check from `tools/local_server.py` into a module the app server can import, and keep the tool as a thin wrapper.
- [x] `POST /server/start` and `POST /server/stop`, refused unless the active server's folder is on a fixed disk of this PC.
- [x] Start and Stop buttons in the component panel, with a confirmation for Stop.

**Tests.** The routes refuse a network or production folder; start and stop set and clear the switches in a temporary root.

**Done when.** The developer stops and restarts the local root from the tab and the panel follows.

Estimate: code edit 30 min, test/validation 15 min, total 45 min. Actual: code edit 10 min, test/validation 12 min, total 22 min; under half the estimate because step 7's reader and route already carried everything the controls needed to follow.

**What was built.** `python-api/src/arcrho_server_control.py` owns the check (`control_refusal`: not production, on a fixed disk of this PC), `start_server`, `stop_server` and the stop-switch write, which uses the canonical `write_json_atomic` with a short retry; a test pins its text to `server_config.write_server_config` and its Orchestrator folder name to the server-components table. `tools/local_server.py` `start`, `stop` and `status` call it and the step 7 reader, so the 30 s file-age rule is gone. Start launches the Orchestrator through `start`, so it is not in the app server's process tree: the app ends its app server with `taskkill /T`, which would otherwise take the whole server down with the app. `GET /server/status` gained `control`; `POST /server/stop` returns at once and the page follows the heartbeats (every 2 s, up to 90 s). Checked on `C:\Arco Server` through the routes of a `launch-app` session: stop cleared every heartbeat within 5 s, and start brought the Orchestrator, both Engines and the Gateway back within 6 s.
