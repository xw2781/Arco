# ArcRho Agent Guidelines

These instructions apply to every code agent working in this repository, regardless of which agent tool is running. [CLAUDE.md](CLAUDE.md) redirects here and holds the Claude-only rules.

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
- **Server PC:** the shared machine that physically holds `E:\Arco Server` — the project workspace, the deployed server components, and the shared macro library — runs the server-side build listener, and is the machine with ResQ installed. Currently `NE7SASWPN02`. Older notes and commit messages call it the "Dev PC"; that name predates development moving onto a client machine, so prefer "Server PC" in new writing.
- **Client PC:** a user machine that runs the ArcRho desktop app and reaches the ArcRho Server workspace (`E:\Arco Server`) as a mapped or UNC network drive; it loads shared macros from the library into its own local `Documents\Arco\macros`. Development happens on one of these: the developer's workstation `L-H2MQ6280FVP` holds its own working clone of this repository at `C:\Users\xwei\Repos\Arco` (the Server PC's clone is `E:\XWSpace\Repos\Arco`) and runs the frontend app in dev mode, and maps `\\NE7SASWPN02\E` as drive `E:`, so `E:\Arco Server` resolves there exactly as it does on the Server PC.

## Mandatory Read Before Editing
Before changing files under `frontend/`, read `frontend/FRONTEND_AGENT_GUIDELINES.md`.

## Agent Memory
Claude Code project memories are tracked in `agent-memory/`, with `agent-memory/MEMORY.md` as the index. A `Stop` hook commits and pushes that folder, and only that folder, at the end of each turn — the one exception to the no-push-without-approval rule — so never commit `agent-memory/` by hand as part of another change.
A memory that depends on one workstation's layout — installed interpreters, drive letters, a count of tests already failing — must say so in its own text.
A new clone needs `tools/link_agent_memory.ps1` run once and a restart; see [tools/agent_memory_setup.md](tools/agent_memory_setup.md).

## Agent Project Data Access (MUST)
Agents may view on-disk metadata JSON files under `E:\Arco Server\projects` only for project `NJ_Annual_Prod_202605_Fake` by default.

Do not read metadata JSON files on disk for any other ArcRho Server project unless the user gives explicit permission for that project in the current session. If a user references another project without giving session-specific permission, ask for permission or ask the user to provide the needed excerpts directly in the chat.

When a task needs concrete sidecars, method JSON, or dataset JSON and the request names no reserving-class data path, use `E:\Arco Server\projects\NJ_Annual_Prod_202605_Fake\data\PRNJ - PA_%5C_PA_%5C_All States_%5C_Direct Group_%5C_COL` as the default data folder.

This restriction applies to agent tool use and analysis only; it does not change runnable scripts that a human may execute, such as `python-api/migration/resq_data_migration.py`.

## Single Source of Truth (MUST)
Before changing code, configuration, schemas, data contracts, automation, documentation, or tests, identify the canonical owner of every value and rule.
- Define each value or rule once. Consumers must import, read, derive, generate from, or delegate to that source; clearly model legitimate runtime overrides and derived values.
- When direct reuse across languages or build boundaries is impractical, use one canonical machine-readable source and generate validated adapters or artifacts so drift is detected.
- Tests may assert canonical behavior, but fixtures, expected values, generated documentation, and inventories must not become competing sources of truth.
- When the touched area already contains duplication, consolidate it within the task's safe scope and remove obsolete copies. Ask before cleanup that broadens behavior or compatibility risk.

## Minimal Diff and Approval-Gated Patterns (MUST)
Prefer the minimum-diff solution: implement the goal in its small, direct form. Do not inflate a simple implementation with validations, defensive checks, or try/except handling for situations that rarely occur in practice. The same restraint applies to docs and comments: do not describe rare cases.
Do not add SHA-256 (or other hash/checksum) validation or legacy fallback logic without the user's explicit approval. If the required task has no alternative solution, stop and ask the user for approval first, explaining why that validation or fallback must be used.

## Server-Hosted Project Data I/O (MUST)
The frontend client app on a Client PC reaches ArcRho project data over HTTP through the machine-wide Arco Gateway, not over the mapped or UNC drive. The Gateway, Engine, and Bridge run on the Server PC where the workspace is local disk; the canonical `app_server` service function stays the single owner of each read or save and runs unchanged on either side. SMB is the transport being retired, not a peer of HTTP.
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
| [Component Deployment Authorization](agent-instructions/component-deployment-authorization.md) | `rebuild`, `redeploy`, `deploy.py`, `build_exe.py`, `build_manager.bat`, `bundled_sources`, `kill_all`, `heartbeat`, `Bridge`, `Engine`, `Gateway`, `Orchestrator`, `Admin Control`, `Launcher` |
| [SVG Icon Management](agent-instructions/svg-icon-management.md) | `svg`, `.svg`, `icon`, `icons`, `iconography`, `glyph`, `sprite`, `symbol`, `cursor image`, `logo`, `artwork`, `viewBox`, `currentColor`, `mask-image`, `icon folder`, `shared/icons`, `file-icons`, `tab-type-icons` |
| [GUI Verification](agent-instructions/gui-verification.md) | `GUI verification`, `GUI test`, `verify in the GUI`, `click`, `double-click`, `drag`, `screenshot`, `mouse`, `desktop`, `Arco window`, `ResQ window`, `ResQ GUI`, `Excel window`, `Remote Desktop` |
| [ResQ API Reference Material](agent-instructions/resq-api-reference.md) | `ResQ COM`, `ResQ API`, `ResQ scripting`, `ResQ help manual`, `ResQToolBox`, `ResQ object hierarchy`, `ResQ migration`, `reserve review notebook`, `ConnectByName`, `GetDFMMethod`, `AddMethod` |
| [Persisted JSON Rules](.claude/skills/arcrho-json-contract/references/persisted-json-rules.md), with the `arcrho-json-contract` skill | `index.json`, `sidecar`, `method JSON`, `persisted JSON`, `json.dump`, `persisted_json_text`, `folder_signature`, `JSON schema`, `field name`, `data storage format`, `Generated=true`, `engine sidecar`, `ResQ migration`, `resq_data_migration.py` |
| [Writing and Running Tests](agent-instructions/testing.md) | `test`, `tests`, `unittest`, `pytest`, `tempfile`, `TemporaryDirectory`, `gateway_test_guard`, `allow_test_gateway` |

## UI Text
Avoid unnecessary secondary labels and descriptions. Let the layout do the explaining.

## Bug Fix Verification and Cleanup
Before changing code for a bug fix, review the relevant code and verify that its current logic can explain the bug or unexpected behavior reported by the user. If the reported behavior cannot be traced to the code, or if any material detail is uncertain, stop and ask the user for more details or clarification until the issue is clear. Do not make assumptions or guesses when deciding on code changes.
When fixing a bug, remove clearly obsolete code in the touched area. Ask before broader cleanup or cleanup with behavior risk.

## ArcRho Macro Source
Treat `python-api/macros` as the source of truth for ArcRho macro files maintained in this repository.
Follow the macro metadata, versioning, release-note, and backup rules in `python-api/macros/README.md` whenever adding or changing a macro.
A macro must stand on its own: it runs against the `arcrho_api` the installed app was built with, so it must never depend on a change made in `python-api/src/arcrho_api` in the same turn. Put the behaviour a macro owns in the macro file, and see "A macro must stand on its own" in `python-api/macros/README.md`.
When adding or editing a macro, update the file in `python-api/macros` first, then copy all active macro files from that folder to the current user's `%USERPROFILE%\Documents\Arco\macros`.
After adding or editing any active macro, also publish the active macros to the official shared macro library (`E:\Arco Server\shared\macros`) by running `python publish_macro_library.py` from `python-api/macros`.
Run `python publish_macro_library.py --check` from `python-api/macros` before reporting any task that touched `python-api/macros` or `python-api/migration` as finished, and at the start of any task investigating a macro failure. It writes nothing and exits 1 when the library is behind the repo; publish then, or tell the user what is unpublished and why.

## Python Runtime Preference
Always prefer Python 3.10 for this repository. When validating Python code, running scripts, installing dependencies, or creating virtual environments, use a Python 3.10 interpreter unless the user explicitly asks for another version or a toolchain requires a different runtime.

## Component Build and Deploy (MUST)
Every frozen server component — Bridge, Engine, Gateway, Orchestrator, Admin Control, Launcher — runs its bundled copy of the source, so an edit under a bundled tree (including `frontend/app_server/`) is live only after a rebuild. Rebuild once per task with `python server-components/deploy.py`, after the change is verified, and state in the final response which components were redeployed or why none were. The user pre-authorizes these rebuilds when the released app stays safe. Read [Component Deployment Authorization](agent-instructions/component-deployment-authorization.md) before any rebuild: it holds the deploy commands, the ship impact statement, the local test root, and how far the authorization reaches.

## Node Runtime Preference
Node is not installed globally or on `PATH`. Run Node and npm through the bundled portable runtime: `frontend\node-portable\node.exe` and `frontend\node-portable\npm.cmd`.

## Validation Runtime
Validation commands must not write files to the C drive. If temporary files are needed, write them only under `tmp_data/` in the repository, as the temporary-file rule below describes. This overrides a harness scratchpad directory on C:.

## Temporary Files (MUST)
- Never create temporary files or folders loose in the repository root or beside the code under test. One gitignored folder at the repository root, **`tmp_data/`**, owns every scratch path — what a test writes and an agent's own scratch during validation or an experiment (screenshots, browser profiles, mock pages, generated files) — and is created on demand if missing. Give each task its own subfolder. Point `tempfile` calls and shell scratch paths at it explicitly — for example `tempfile.mkdtemp(dir=tmp_data_dir)`, or `TEMP`/`TMP` set to `tmp_data/tmp` for a shell run — rather than relying on the default location.
- Delete whatever you created before finishing the task: remove the scratch files and any folder you made for them once the validation or experiment is done. Wrap them in `tempfile.TemporaryDirectory()` or an equivalent so cleanup happens even when a command fails.
- Before ending a task, check `git status --short --ignored` for anything new that you left behind — a stray `tmp*` folder, a generated spreadsheet, a copied JSON — and remove it. A gitignored leftover is still litter: it clutters the working tree for the next person and other agents.
- A test's temporary directories also live under `tmp_data/`, and a test run never reaches a real Gateway; read [Writing and Running Tests](agent-instructions/testing.md) before adding or editing a test.
