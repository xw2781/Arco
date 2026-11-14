# Frontend: Server

## Purpose
<!-- MANUAL:BEGIN -->
Server tab: lists the servers this PC knows by name and Gateway address, marks the one in use, adds a server from its folder, and switches between them by restarting the app. Its Components panel shows the running components of the server in use: one row per heartbeat with machine, user, when it was last heard from and whether that is stale, grouped by role with each role's stop switch. For a server whose folder is on a fixed disk of this PC and is not production, the panel also starts and stops it; production shows one line saying it is managed from Admin Control on the Server PC.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.server.entry_points -->
- `ui/server/server.html`: external scripts `./server.js?v=20260927b`, `/ui/shared/services/color_theme.js?v=20260923c`; inline imports _none_.

Detected `fetch(...)` targets in key JS files:
- `/server/${kind}`
- `/server/status`
- `/server_profiles`
- `/server_profiles/activate`
- `/server_profiles/health${healthQuery(row)}`
- `/server_profiles/inspect?root=${encodeURIComponent(folder)}`
- `/server_profiles/sign_in`

Detected `arcrho:*` message types in key JS files:
- `arcrho:agent-guide-load-result`
- `arcrho:assistant-context-request`
- `arcrho:open-path-result`
- `arcrho:project-settings-progress-cancel`
- `arcrho:server-switch`
- `arcrho:server-switch-result`
- `arcrho:task-designer-context-response`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.server.key_files -->
- [`ui/server/server.html`](../../ui/server/server.html) - Server tab iframe entrypoint: server list, add form, components panel with start and stop, confirmation dialog.
- [`ui/server/server.js`](../../ui/server/server.js) - Server tab controller: listing, health, add server, the switch request to the shell, component polling while on screen, and start and stop.
- [`ui/server/server_model.js`](../../ui/server/server_model.js) - Pure rules for rows, labels, set-at-launch, add validation, switch and sign-in messages, the title-bar badge, component groups, and start/stop progress.
- [`ui/server/server.css`](../../ui/server/server.css) - Server tab styling on the shared theme tokens.
- [`ui/shell/shell_messages.js`](../../ui/shell/shell_messages.js) - Shell side of a switch: unsaved-changes guard, activation, and restart.
- [`app_server/services/server_profile_service.py`](../../app_server/services/server_profile_service.py) - Server profile listing, health probe, folder inspection, activation, sign in again, component-status transport, and start/stop of a server on this PC.
- [`app_server/services/server_component_status_service.py`](../../app_server/services/server_component_status_service.py) - Component heartbeats and stop switches of the server folder this process serves.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opened from the Home Server card, the Server Connection dialog, or the titlebar's server badge as one restorable `server` shell tab.
- `GET /server_profiles` also reports `default_profile`, production's profile id. The shell's titlebar badge shows whenever the active profile differs from it or a launch override is set, and uses the same name and address rules as the tab's rows.
- Reads `GET /server_profiles`, `GET /server_profiles/health` (the app server probes each Gateway) and `GET /server_profiles/inspect`, and adds with `POST /server_profiles`. Adding needs the server's address, typed in the form: the folder check only names the folder, because a server's Gateway registry is server-only and never read from a client. The address is where the app signs up when it switches to that server.
- Reads `GET /server/status` for the Components panel. The app server reads a server folder on a fixed disk of this PC directly and asks any other server's Gateway (the `server_component_status` read); a silent Gateway comes back as `answering: false` with a plain reason, never as a read over the share.
- Starts and stops with `POST /server/start` and `POST /server/stop`. The status carries `control` (`available`, the refusal `detail`, and the `roles` start and stop cover), and the buttons show only when `available` is true. Stop asks for confirmation first, because the window loses its own server until it is started again. The page then shows `Starting... N s` or `Stopping... N s`, asks every 2 seconds, and ends when every covered role has a live heartbeat with its stop switch off (start) or none has a live heartbeat (stop), or after 90 seconds with an error line.
- The server in use (the active profile, or the `Set at launch` row) offers `Sign in again` in place of `Switch`; it posts `POST /server_profiles/sign_in` and shows `Signed in again as <user>.` or the reason it failed. The shell's status bar offers the same action beside any message carrying "Sign in to the server again" (`asksToSignIn` in `server_model.js`, pinned to the app server's two sign-in messages by `tests/server_tab.test.mjs`).
- Switches by posting `arcrho:server-switch` to the shell, which refuses while any tab is dirty, activates the profile, runs the ordinary restart, and answers with `arcrho:server-switch-result`.
- Uses the host `pickFolder` bridge when present; the folder text field is the fallback.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Holds no state of its own; the profile list lives in `%APPDATA%\Arco\workspace_paths.json`, owned by `arcrho_api.config`.
- While a launch override is set (`set_at_launch`), shows that server as `Set at launch` and turns switching and adding off; `Sign in again` stays on and replaces only that launch's credential file.
- The Components panel asks again every 5 seconds, and only while it is on screen: an inactive shell tab hides its frame without changing the page's visibility state, so the page also checks its frame's layout, and asks at once when it comes back into view.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change what a row shows: update `server_model.js`, `server.js`, and `tests/server_tab.test.mjs` together.
2. Change what start or stop does, or which folders may be controlled: change `python-api/src/arcrho_server_control.py`, which `tools/local_server.py` shares; the page only follows the heartbeats.
3. Change when a component counts as stale: change `python-api/src/arcrho_server_component_status.py`, which Admin Control shares; the page only displays the server's verdict.
4. Change what a switch does: update the shell handler in `shell_messages.js`, the activate route, and both test files.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A switch restarts the app server; it must stay blocked while any tab holds unsaved changes.
- Stop takes down the Gateway this window uses, so the window cannot read or save until Start brings it back. Production is never offered: its stop switches would stop it for every user.
- Never save profiles from a `launch-app` session; the routes refuse with 409 and the page disables the controls.
<!-- MANUAL:END -->
