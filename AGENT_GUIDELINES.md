# ArcRho Agent Guidelines

These instructions apply to every code agent working in this repository, regardless of which agent tool is running. Both [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md) redirect here; agent-specific rules stay in those files.

This is the ArcRho monorepo root. Use one Git repository here for all ArcRho components.

## Repository Layout
- `frontend/`: current ArcRho desktop/web UI, Electron host, backend service code currently bundled with the frontend app, docs, release fragments, and frontend-specific agent rules.
- `python-api/`: Python API, ResQ migration scripts, migration references, and macro source files.
- `server-components/`: the ArcRho Server components — Engine, Orchestrator, Bridge, Launcher, Admin Control, Gateway — with their build, deploy, and installer tooling.
- `tools/`: repository-level automation, including commit/push helpers for agents, `agent_screen_control/` for looking at and clicking desktop applications during GUI verification, `arco_window_control/` for doing the same inside the Arco window only, and `svg_icon_preview.py`, which collects every SVG in the repository into one browser gallery (run it directly, or double-click `tools/preview_svg_icons.bat`).
- `agent-memory/`: tracked Claude Code project memories; see [Agent Memory](#agent-memory).

## Project Terms and Abbreviations
- **DSV (Dataset Viewer):** the frontend workspace for viewing and editing datasets under `frontend/ui/dataset_viewer`.
- **DFM (Development Factor Method):** the frontend workspace for creating and reviewing development factor methods under `frontend/ui/method_pages/dfm`.
- **BF (Bornhuetter Ferguson):** the frontend workspace for Bornhuetter Ferguson methods under `frontend/ui/method_pages/bornhuetter_ferguson`.
- **CC (Cape Cod):** the frontend workspace for Cape Cod methods under `frontend/ui/method_pages/cape_cod`.
- **RS (Result Selection):** the frontend workspace for result selection methods under `frontend/ui/method_pages/result_selection`.
- **PI (Project Instance):** the frontend workspace for browsing and working within a project instance under `frontend/ui/project_instance`.
- **PS (Project Settings):** the frontend workspace for configuring project settings under `frontend/ui/project_settings`.
- **Server PC:** the shared machine that physically holds `E:\ArcRho Server` — the project workspace, the deployed server components, and the shared macro library — runs the server-side build listener, and is the machine with ResQ installed. Currently `NE7SASWPN02`. Older notes and commit messages call it the "Dev PC"; that name predates development moving onto a client machine, so prefer "Server PC" in new writing.
- **Client PC:** a user machine that runs the ArcRho desktop app and reaches the ArcRho Server workspace (`E:\ArcRho Server`) as a mapped or UNC network drive; it loads shared macros from the library into its own local `Documents\ArcRho\macros`. Development happens on one of these: the developer's workstation `L-H2MQ6280FVP` holds this repository's working clone and runs the frontend app in dev mode, and maps `\\NE7SASWPN02\E` as drive `E:`, so `E:\ArcRho Server` resolves there exactly as it does on the Server PC.

## Mandatory Read Before Editing
Before changing files under `frontend/`, read `frontend/FRONTEND_AGENT_GUIDELINES.md`.

## Agent Memory
Claude Code project memories are tracked in this repository under `agent-memory/`, with `agent-memory/MEMORY.md` as the index. They are reviewed and committed to `main` like any other documentation, so a hard-won debugging technique survives a machine rebuild and reaches every clone.

The agent harness derives its memory directory from the repository's absolute path (`%USERPROFILE%\.claude\projects\<slug>\memory`) and offers no setting to move it. Run `tools/link_agent_memory.ps1` once per machine and per clone path to make that directory a junction pointing at `agent-memory/`; memory writes then land in the working tree. The script is idempotent, needs no elevation, and refuses to replace a non-empty real memory directory without `-Force`. Restart Claude Code afterwards so the index is loaded at session start.

**Setting up a new clone is two steps, and skipping either one silently loses memories.** Run `tools/link_agent_memory.ps1`, then restart. Without the junction the harness writes into a real directory outside the tree, nothing commits it, and that machine's memories never reach anyone else — a divergence that is invisible until an agent gives a wrong answer from a stale index.

Committing memories is automatic and is the one exception to the push rule below. The `Stop` hook in `.claude/settings.json` runs `tools/sync_agent_memory.sh`, which commits and pushes `agent-memory/` — and only `agent-memory/` — at the end of each turn. It uses the pathspec form of `git commit`, so work staged elsewhere is never swept in, and it does nothing during a rebase, merge, cherry-pick, or on a detached HEAD. A rejected push leaves the commit local for the next run to carry. Do not commit `agent-memory/` by hand as part of another change; let the hook own it, so a memory edit never rides along in an unrelated commit.

`.claude/settings.json` is tracked for this reason: a hook that exists on only one machine cannot keep two machines in sync. Keep machine-specific paths out of it — resolve the repository root at runtime with `git rev-parse --show-toplevel`. Per-machine overrides belong in `.claude/settings.local.json`, which stays ignored.

Because these notes are now shared across machines, a memory that depends on one workstation's layout — installed interpreters, drive letters, a bundled `node-portable`, a count of tests already failing at HEAD — must say so in its own text instead of being written as a universal fact.

## Agent Project Data Access (MUST)
Agents may view on-disk metadata JSON files under `E:\ArcRho Server\projects` only for project `NJ_Annual_Prod_202605_Fake` by default.

Do not read metadata JSON files on disk for any other ArcRho Server project unless the user gives explicit permission for that project in the current session. If a user references another project without giving session-specific permission, ask for permission or ask the user to provide the needed excerpts directly in the chat.

This restriction applies to agent tool use and analysis only; it does not change runnable scripts that a human may execute, such as `python-api/resq_data_migration.py`.

## Single Source of Truth (MUST)
Before changing code, configuration, schemas, data contracts, automation, documentation, or tests, identify the canonical owner of every value and rule.
- Define each value or rule once. Consumers must import, read, derive, generate from, or delegate to that source; clearly model legitimate runtime overrides and derived values.
- When direct reuse across languages or build boundaries is impractical, use one canonical machine-readable source and generate validated adapters or artifacts so drift is detected.
- Tests may assert canonical behavior, but fixtures, expected values, generated documentation, and inventories must not become competing sources of truth.
- When the touched area already contains duplication, consolidate it within the task's safe scope and remove obsolete copies. Ask before cleanup that broadens behavior or compatibility risk.

## Minimal Diff and Approval-Gated Patterns (MUST)
Prefer the minimum-diff solution: implement the goal in its small, direct form. Do not inflate a simple implementation with validations, defensive checks, or try/except handling for situations that rarely occur in practice. The same restraint applies to docs and comments: do not describe rare cases.
Do not add SHA-256 (or other hash/checksum) validation or legacy fallback logic without the user's explicit approval. If the required task has no alternative solution, stop and ask the user for approval first, explaining why that validation or fallback must be used.

## Persisted JSON Producer Parity (MUST)
When more than one ArcRho component can create the same persisted JSON file, all producers must emit the exact same full parsed payload for the same logical inputs.
- Keep one canonical owner for the schema, version, field projection, inclusion/omission rules, defaults, normalization, timestamp representation, and deterministic list ordering. Frontend, Python API, migration, macro, and other producers must import, generate from, or delegate to that owner; producer-specific enrichment is forbidden.
- Keep reserving-class `index.json` a minimal scalar summary of logical dataset instances. Do not copy arrays or nested sidecar/method details into it. In particular, `origin_labels`, dependency graphs, audit logs, and other detail payloads remain in their owning sidecar or method JSON.
- Persist only location-independent, reserving-class-owned data in `index.json`. Do not persist producer-local drive letters, UNC aliases, absolute folder paths, or rebuild-time enrichment from project/global JSON. Resolve machine-local paths and other presentation-only values in the API response or consumer instead.
- Reading a valid current `index.json` must return it without scanning sidecars/methods and without rewriting or enriching the file. Rebuild only when the index is missing, invalid, explicitly refreshed, made stale by a durable mutation, or uses an outdated canonical version/schema.
- Detect a durable mutation by listing the reserving-class instance folders once and comparing that listing against the persisted `folder_signature`. A staleness check must not open sidecar or method payloads. Because that check runs before the index lock is taken, a rebuild it triggers must enumerate the folder again inside the lock rather than reuse the unlocked listing, so a payload and the `folder_signature` written beside it always describe the same observation. Enumeration must keep the size and modification time the directory listing already returned; do not re-stat each enumerated path.
- A transient permission/network read failure during rebuild must abort and preserve the last valid index; it must never be converted into and persist a degraded but schema-valid payload.
- Coordinate any `index.json` contract or build-logic change across the bundled frontend app server, the public Python API, `python-api/migration/resq_data_migration.py`, its migration modules, and the mirrored macro under `python-api/macros`.
- Every such change must include an exact full-payload cross-producer parity test, including path-alias independence, and a test proving that a valid current index is served without a sidecar scan or rewrite.

## Persisted JSON Text Format (MUST)
`arcrho_api/io.py` owns the on-disk text of every persisted ArcRho JSON file. `format_json_for_save` produces the layout and `persisted_json_text` produces the complete document, including its single trailing newline.
- A two-dimensional array — a triangle, a vector of vectors, a table of rows — must be written one row per line. `json.dumps(..., indent=2)` puts one scalar per line, which turns a 40x40 triangle into roughly 1,900 lines a human cannot review and doubles the bytes a network-drive read pays for. This applies to every 2D array, not to a named list of keys; a writer must not decide per field which arrays are compact.
- Every producer of persisted project, reserving-class, method, sidecar, index, or project-data cache JSON must call `persisted_json_text` rather than `json.dump`/`json.dumps` with an `indent`. That includes the bundled app server, the public Python API, `python-api/migration/`, macros, and the bridge. A payload with no 2D array renders byte-identical to the previous `indent=2` text, so there is no reason for a persisted-JSON writer to opt out.
- Only a component that genuinely cannot import `arcrho_api` may keep a copy, and only behind a test that pins the copy to the canonical text byte for byte. There are two: the frozen Bridge, which loads `arcrho_api` from its data bundle rather than its import graph (`arcrho_bridge/bridge_utils.py`, pinned by `server-components/tests/test_bridge_json_parity.py`), and the Electron host (`frontend/electron/persisted_json_text.js`, pinned by `frontend/tests/test_host_json_text_parity.py`). The host copy serves only files the host writes on its own — templates, notebooks, undo steps, ArcBot exchange copies; persisted project data is never written from JavaScript, which cannot tell `1` from `1.0`, so a renderer saves a method or sidecar through an app-server route.
- Revisions, digests, and unchanged-file comparisons must not depend on this layout. Hash the canonical projection with `separators=(",", ":")` as `dfm_contract` does, so reformatting a file can never shift a stored revision.
- Transient runtime files that are not ArcRho project data — bridge heartbeats, engine request envelopes, editor scratch state — are outside this rule.

## Generated Dataset Import Parity (MUST)
When ResQ migration encounters a single-instance Dataset Type with `Generated=true`, the migration must reproduce the frontend generation path rather than copy the ResQ object's values or presentation metadata.
- Submit the same ArcRho Engine request contract used by the frontend and publish only the completed Engine CSV.
- Build the persisted engine sidecar through the same canonical contract as the frontend runtime. Do not copy ResQ origin/development labels, counts, formulas, users, or timestamps into an engine-owned sidecar.
- Keep Dataset Type formulas and project header labels in their canonical project configuration/header sources. Cached dataset reads must hydrate them before the first grid render; do not synthesize generic `12, 24, ...` labels for an engine dataset.
- Once the Engine CSV is written, compare it with the ResQ copy of the same dataset at two decimal places (`resq_migration.engine_parity`, the module the offline parity validation also uses) and carry any disagreement to the person importing as a warning that names the dataset and its first differing cell. The Engine result is kept either way; ResQ values are read only for this comparison, never before the Engine has produced the dataset.
- Add an exact full-payload cross-producer test for the frontend and migration engine-sidecar writers, including path-alias independence, plus a cached-load test proving formula and development-label hydration matches a force rebuild.

## Server-Hosted Project Data I/O (MUST)
The frontend client app on a Client PC reaches ArcRho project data over HTTP through the machine-wide ArcRho Gateway, not over the mapped or UNC drive. The Gateway, Engine, and Bridge run on the Server PC where the workspace is local disk; the canonical `app_server` service function stays the single owner of each read or save and runs unchanged on either side. SMB is the transport being retired, not a peer of HTTP.
- Prefer HTTP for every client interaction with files on the Server PC. Register a read in `python-api/src/arcrho_workspace_read_contract.py` and route it through `workspace_read_client.run_workspace_read`; register a save in `arcrho_engine_save_contract.SAVE_JOB_KINDS` and route it through `workspace_mutation_client.run_workspace_mutation` or the hosted save job. Engine calculations already run hosted. A new client-side feature must not open project JSON, sidecars, CSVs, or indexes over the share directly.
- When a task touches any module that still reads or writes project data over SMB from the client — a route not wrapped in the hosted transport, a service the read registry does not list, or a hosted path that quietly runs locally when the Gateway is unavailable — say so explicitly in the response, name the module, and propose moving it onto the Gateway and removing the SMB fallback. Do this even when the task itself did not ask about transport.
- Do not add a new SMB fallback, and do not keep an existing one out of caution. Keep an SMB path only for a strong, feature-specific reason that HTTP cannot serve, state that reason in the response, and record it in the implementation and the domain doc so the next agent does not re-open the question.
- Where an SMB path remains, every filesystem operation is a full round trip: enumerate a folder once, reuse request-scoped index and configuration snapshots, use bounded parallel or batched reads rather than a per-file awaited loop, and coalesce writes under the existing lock and atomic temporary-file replacement patterns.
- Add focused coverage for transport selection and failure handling whenever a change moves a read or save between transports.

## Log File Retention (MUST)
Every log file any ArcRho component writes is kept for 30 days and no longer. No component may define its own retention window, keep-last-N rule, or cleanup routine.
- `python-api/src/arcrho_log_retention_contract.py` owns the window and the mechanics. `LOG_RETENTION_DAYS` is the only place the number 30 is written; `prune_aged_log_files` deletes aged files, `trim_aged_log_lines` drops the aged leading lines of a log appended under a fixed name, and `apply_log_retention` does both for one folder.
- A component applies retention once as it starts, before its first log line. A folder whose files are named per launch or per request is pruned; a log whose name never changes must be trimmed by line, because its own file age can never expire it.
- Never add a log writer without adding its retention call in the same change. This covers diagnostics, request traces, deploy logs, and anything else written to disk to be read by a human later.
- Retention is best effort and must never change what a component does: swallow every failure, so a locked file or a full disk can only leave an old log in place.
- Size rotation may bound a single busy log in addition to the 30-day rule, never instead of it.
- The Electron host cannot import Python, so `frontend/electron/log_retention.js` mirrors the rule and `frontend/tests/log_retention.test.mjs` pins the mirror to the contract. Change the Python constant; the test fails until the mirror follows.

## Conditional Instruction Entry Points

| Read only this file when triggered | Trigger words |
| --- | --- |
| [User Preference Storage Scopes](agent-instructions/user-preference-storage-scopes.md) | `preference`, `preferences`, `user setting`, `settings storage`, `AppData`, `localStorage`, `project-user`, `shared preference`, `workspace_paths.json` |
| [Excel Add-in Build and Release](agent-instructions/excel-addin-build-and-release.md) | `excel-addin/`, `Excel add-in`, `.xlam`, `VBA add-in`, `build_xlam`, `release_xlam` |
| [Agent Project Data Access](agent-instructions/agent-project-data-access.md) | `ArcRho Server project data`, `project metadata JSON`, `sidecar`, `method JSON`, `dataset JSON`, `reserving-class data path`, `resq_data_migration.py`, `E:\ArcRho Server\projects` |
| [Component Deployment Authorization](agent-instructions/component-deployment-authorization.md) | `rebuild`, `redeploy`, `deploy.py`, `build_exe.py`, `build_manager.bat`, `bundled_sources`, `kill_all`, `heartbeat`, `Bridge`, `Engine`, `Gateway`, `Orchestrator`, `Admin Control`, `Launcher` |
| [SVG Icon Management](agent-instructions/svg-icon-management.md) | `svg`, `.svg`, `icon`, `icons`, `iconography`, `glyph`, `sprite`, `symbol`, `cursor image`, `logo`, `artwork`, `viewBox`, `currentColor`, `mask-image`, `icon folder`, `shared/icons`, `file-icons`, `tab-type-icons` |
| [GUI Verification](agent-instructions/gui-verification.md) | `GUI verification`, `GUI test`, `verify in the GUI`, `click`, `double-click`, `drag`, `screenshot`, `mouse`, `desktop`, `Arco window`, `ResQ window`, `ResQ GUI`, `Excel window`, `Remote Desktop` |
| [ResQ API Reference Material](agent-instructions/resq-api-reference.md) | `ResQ COM`, `ResQ API`, `ResQ scripting`, `ResQ help manual`, `ResQToolBox`, `ResQ object hierarchy`, `ResQ migration`, `reserve review notebook`, `ConnectByName`, `GetDFMMethod`, `AddMethod` |

## UI Text
Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.

## Bug Fix Verification and Cleanup
Before changing code for a bug fix, review the relevant code and verify that its current logic can explain the bug or unexpected behavior reported by the user. If the reported behavior cannot be traced to the code, or if any material detail is uncertain, stop and ask the user for more details or clarification until the issue is clear. Do not make assumptions or guesses when deciding on code changes.
When fixing a bug, remove clearly obsolete code in the touched area. Ask before broader cleanup or cleanup with behavior risk.

## ArcRho JSON Contract Skill
Use `$arcrho-json-contract` when refining dataset JSON sidecars/sidercars, reserving-class `index.json`, data storage formats, JSON field names or structures, ResQ migration behavior, or `python-api/migration/resq_data_migration.py` output.

## ArcRho Workspace Sync Skill
Use `$arcrho-sync-workspace` when asked to sync, update, or refresh this clone against the remote, to pull the latest, or when the user says they have switched between the NE7SASWPN02 and L-H2MQ6280FVP workspaces. It fast-forwards unasked only when the clone is clean and purely behind, and it asks before rebasing, merging, or discarding anything that exists only here. It refuses to run in the Build Listener's clone, which resets itself.

## ArcRho Macro Source
Treat `python-api/macros` as the source of truth for ArcRho macro files maintained in this repository.
Follow the macro metadata, versioning, release-note, and backup rules in `python-api/macros/README.md` whenever adding or changing a macro.
A macro must stand on its own: it runs against the `arcrho_api` the installed app was built with, so it must never depend on a change made in `python-api/src/arcrho_api` in the same turn. Put the behaviour a macro owns in the macro file, and see "A macro must stand on its own" in `python-api/macros/README.md`.
When adding or editing a macro, update the file in `python-api/macros` first, then copy all active macro files from that folder to `C:\Users\xwei.PRCINS\Documents\ArcRho\macros`.
After adding or editing any active macro, also publish the active macros to the official shared macro library (`E:\ArcRho Server\shared\macros`) by running `python publish_macro_library.py` from `python-api/macros`.
Run `python publish_macro_library.py --check` from `python-api/macros` before reporting any task that touched `python-api/macros` or `python-api/migration` as finished, and at the start of any task investigating a macro failure. It writes nothing and exits 1 when the library is behind the repo; publish then, or tell the user what is unpublished and why.

## Python Runtime Preference
Always prefer Python 3.10 for this repository. When validating Python code, running scripts, installing dependencies, or creating virtual environments, use a Python 3.10 interpreter unless the user explicitly asks for another version or a toolchain requires a different runtime.

## Component Build and Deploy (MUST)
Every frozen server component — Bridge, Engine, Gateway, Orchestrator, Admin Control, Launcher — is rebuilt and redeployed through `server-components/deploy.py`, which asks the ArcRho Build Listener on the server machine to do the work. Do not run a component's `build_exe.py` from a client machine unless the listener is unavailable: a client deploy pushes the frozen build across the workspace share, measured on 2026-08-17 at 0.18 MB/s of writes against that same share's 50 MB/s reads, so five of every six minutes was transfer rather than build.

```
python server-components/deploy.py            # every component the change made stale
python server-components/deploy.py bridge engine
python server-components/deploy.py --stale    # report freshness, build nothing
python server-components/deploy.py --ref main # build a pushed ref instead of local source
```

- **Do not work out which components are stale by hand.** With no arguments the CLI derives that from each component's bundled source roots, which is the only reliable answer — an edit under `frontend/app_server/` makes the Bridge, the Engine **and** the Gateway stale, and reasoning about it by memory has already caused a missed Gateway deploy.
- **Uncommitted work deploys.** The CLI sends a patch of the affected trees against the newest commit the server can resolve, so a rebuild required before a change is committed works normally. Do not commit or push merely to deploy.
- **Check what the payload contains before accepting a deploy.** A working-tree deploy ships the state of the whole tree under the affected roots, so a colleague's or another agent's half-finished edits in the same clone go to the server too. The CLI prints the changed and new files for that reason: if the list contains work that is not yours, stop and ask rather than deploying it. `--ref` builds a pushed ref instead and never carries local state.
- **The listener owns its clone, so it must have one nobody edits.** Every claimed request checks out a detached base commit in the listener's clone, resets the working tree and deletes untracked files. That clone is not a setting — it is wherever the listener's own code was started from. It runs from `E:\XWSpace\Repos\ArcRho-buildbot`, which carries the working clone as a second remote so an unpushed commit still resolves. Before deploying, check that the newest heartbeat under `E:\ArcRho Server\runtime\instances\arcrho_build_listener\` names that clone; if it names a clone anyone edits, stop and move the listener with `tools\arcrho_service_control.ps1` rather than deploying, or the next deploy will revert their uncommitted work.
- **Exit codes are the result**: `0` success, `1` the build or deploy failed, `2` a usage or precondition problem, `3` no listener is running. Report a non-zero result plainly and do not retry blindly.
- **The one human step**: on exit code `3`, ask the user to run `server-components\build_manager.bat` on the ArcRho Server machine and turn on "Listen for build requests". Relay the CLI's message; do not attempt to start it remotely.
- **A forced stop blocks the next Engine deploy.** The deploy waits on the heartbeat files under `E:\ArcRho Server\runtime\instances\` to decide the old Engine is gone, and a component killed rather than closed leaves its file behind, so the wait cannot succeed and the deploy aborts. Clear them with `tools\arcrho_service_control.ps1 -Action clear-stale-heartbeats`, which removes only a heartbeat with no live process behind it.
- Rebuild once per task, after the change is verified and before reporting the task complete. Skip it when a task changed only tests, docs, release fragments, or files outside every bundle, and say so.
- State in the final response which components were rebuilt and redeployed, or why none were.

The user pre-authorizes these rebuilds and the component restarts they cause, so do not ask for conversational confirmation; read [Component Deployment Authorization](agent-instructions/component-deployment-authorization.md) before a rebuild for how far that reaches, what each component's downtime costs, what to verify afterwards, and the slower fallback for when no listener is running. `server-components/build_manager.bat` remains the direct interface for a human at the server.

### Local test root (developer PC)
The developer PC `L-H2MQ6280FVP` keeps a private server root at `C:\Arco Server`, run by `tools/local_server.py` (`init`, `copy-project`, `deploy`, `start`, `stop`, `status`, `launch-app`). Nothing in it reaches production or other users; see [docs/plans/local_server_root_and_server_switcher.md](docs/plans/local_server_root_and_server_switcher.md) for what keeps it apart and its limits.
- For work on the SMB retirement ([docs/plans/client_smb_retirement.md](docs/plans/client_smb_retirement.md)), and for any server-component change whose effect can be checked without ResQ, deploy to the local root first (`py -3.10 tools/local_server.py deploy`), check it there with `launch-app`, and only then run `server-components/deploy.py` for production.
- Never point a build at the local root by hand without both `ARCRHO_DEPLOY_ROOT` and `ARCRHO_ROOT`; the tool sets both. Never give a client process `ARCRHO_RUNTIME_SERVER_ROOT`: it marks the process as a server and turns the Gateway off.
- In a `launch-app` session never save the Server Connection page; it writes the per-machine file the production app reads.

## Node Runtime Preference
The frontend includes a bundled portable Node runtime. When validating or running Node/npm commands for this repository, prefer `frontend\node-portable\node.exe` and `frontend\node-portable\npm.cmd` instead of plain `node` or `npm`, because Node is not expected to be installed globally or available on `PATH` in the agent environment. Do not report "Node is not installed in this environment" unless the bundled portable runtime is also missing or fails.

## Validation Runtime
Validation commands must not write files to the C drive. If temporary files are needed, write them only inside the current repository folder, and follow the temporary-file rule below.

## Temporary Files (MUST)
- Never create temporary files or folders loose in the repository root or beside the code under test. Two gitignored folders at the repository root own every scratch path, and each is created on demand if missing: **`test/` for anything a test writes**, and **`temp/` for an agent's own scratch** during validation or an experiment (or the harness scratchpad directory when one is provided). Point `tempfile` calls and shell scratch paths at the right one explicitly — for example `tempfile.mkdtemp(dir=temp_dir)` — rather than relying on the default location.
- Delete whatever you created before finishing the task: remove the scratch files and any folder you made for them once the validation or experiment is done. Wrap them in `tempfile.TemporaryDirectory()` or an equivalent so cleanup happens even when a command fails.
- Before ending a task, check `git status --short --ignored` for anything new that you left behind — a stray `tmp*` folder, a generated spreadsheet, a copied JSON — and remove it. A gitignored leftover is still litter: it clutters the working tree for the next person and other agents.

### Test temporary files (MUST)
Every temporary directory a test creates must live under `test/` at the repository root, whichever test tree the test belongs to — `frontend/tests`, `python-api/tests`, `server-components/tests`, or `tools/tests`. Anchor it on the repository root rather than on the test file, so one folder collects the output of every suite:

```python
TEST_TEMP_ROOT = Path(__file__).resolve().parents[N] / "test"   # N reaches the repository root
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
```

- **Never pass the repository root, a package root, or a test folder as `dir=`.** `tempfile.TemporaryDirectory(dir=REPO_ROOT)` drops a `tmp<random>` folder beside the code, and a test that raises in `setUp` never reaches the teardown that would remove it — one interrupted suite run left 33 of them loose in the root. `test/` keeps that failure mode in one place a single `rm -rf` can clear.
- **Create the directory in the test, not by hand.** `mkdir(parents=True, exist_ok=True)` at import time is enough; the folder is gitignored and must never be committed or relied on existing.
- **Still clean up.** Use `TemporaryDirectory` (or an equivalent that survives a failure) so a passing run leaves `test/` empty. The folder is a backstop for the runs that fail, not a licence to leak.
- **Applies to new and edited tests.** Do not mass-migrate existing suites as a side effect of unrelated work; when you touch a test that anchors its temp directory anywhere else, move that one onto `test/` as part of the change.

### Tests and the Gateway (MUST)
A developer PC is signed in to a real Gateway, so a test that patches the workspace root but not the Gateway would read from and write to that server. `python-api/src/arcrho_api/gateway_test_guard.py` prevents it: in a process started as a test run (`python -m unittest` from any folder, pytest, or a `tests/test_*.py` file run directly) and in every process that run starts, the Gateway credential points at a missing file and every Gateway client refuses a URL no test allowed, as if the Gateway were unreachable. Nothing needs importing; the guard sits in the credential lookup and the Gateway clients.
- **A test sees no Gateway.** A Gateway-only operation answers 503 in a test. Stub what the test needs (for example the propagation busy check), or run the check as a server process against the test's own temporary root.
- **A test that starts its own Gateway on loopback opts in** with `self.addCleanup(allow_test_gateway(url))`. Only loopback URLs can be allowed; allow only the server the test itself started, never the local test server at `C:\Arco Server`.
- **Record mode.** Set `ARCRHO_TEST_GATEWAY_RECORD` to a file path and every refused request is appended there with the test that sent it; a clean run records nothing.
- A new Gateway HTTP client builds its opener with `gateway_test_guard.gateway_opener()`, never `build_opener` directly.
