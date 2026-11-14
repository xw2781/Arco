# App Server Domain: app_control

## Purpose
<!-- MANUAL:BEGIN -->
Application lifecycle control domain (restart/shutdown flags) coordinated between app-server routes and Electron host startup/shutdown flow.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.app_control.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/app/restart` | `app_restart` | `Request` | - | - |
| `POST` | `/app/restart_electron` | `app_restart_electron` | - | - | - |
| `POST` | `/app/shutdown` | `app_shutdown` | `Request` | - | - |
| `POST` | `/app/shutdown_electron` | `app_shutdown_electron` | - | - | - |
| `GET` | `/arcbot/agent-skills` | `arcbot_agent_skills` | `str` | - | `agent_skill_service.read_agent_skills`, `workspace_read_client.run_workspace_read` |
| `GET` | `/arcbot/prompt-files` | `arcbot_prompt_files` | - | - | `workspace_read_client.run_workspace_read` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.app_control.key_files -->
- [`app_server/api/app_control_router.py`](../../../app_server/api/app_control_router.py) - Restart/shutdown control endpoints.
- [`app_server/config.py`](../../../app_server/config.py) - Flag-file paths for app control.
- [`app_launcher.py`](../../../app_launcher.py) - Launcher process watching control flags.
- [`electron/main.js`](../../../electron/main.js) - Electron host restart/shutdown integration.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Called by shell app control actions.
- Coordinated with launcher/electron host watchers.
- Electron host startup clears stale lifecycle flags before spawning the app server on preferred local port `28765` by default; when that port is held by a listener it can neither reuse nor clear (for example another user session on the same machine), it reuses a compatible sibling-instance backend port or falls back to an automatically chosen free local port, then publishes the effective endpoint to the per-user `%APPDATA%\Arco\app_endpoint.json` discovery file. Each packaged backend build contains a `backend-artifact.json` manifest whose identity hashes the complete collected PyInstaller bundle, including the executable and served assets. Every launch token also carries a hash of the Electron user-data path. The host reuses an existing listener only when the health response has the matching app mode and either the exact current launch token or both the same user-data-profile hash and the same artifact identity; development requires the same profile hash and project root. A backend owned by another Windows profile therefore remains incompatible even when both users installed the same build, is left running for its owner, and causes the later user to start a separate backend on a free port. Same-profile obsolete backends may be cleared; unscoped or other-profile healthy backends are bypassed without termination. Shutdown paths post `/app/shutdown` then wait before force-kill fallback.
- The server's life follows the windows using it. Each window writes a client marker naming its process, app mode and port; a departing window stops the server when no other live window of the same mode claims the same port, whether it started that server or reused it (`decideBackendShutdownOnExit` in `electron/backend_port.js`). Startup also stops a same-profile server on a port whose window died without cleaning up, using the preferred-port leave-or-clear decision. A shell restart first asks the host how many other windows share the server and confirms before interrupting them.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Uses lifecycle flag files under project root: `.restart_app_<port>`, `.shutdown_app_<port>`, `.restart_electron`, `.shutdown_electron`. The server markers carry the port of the server that wrote them (`app_server/app_control_flags.py`), so two development apps run from one checkout each stop or restart only their own server; the host clears only the markers of the port it is about to start a server on.
- The development Electron supervisor (`electron_shell.py`, used only by `launch_arcrho_dev_mode.bat`) relaunches Electron only when `.restart_electron` was observed. Electron exiting on its own ends the supervisor, because a user closing the app and a crash are indistinguishable from an exit code and relaunching either one leaves an app that cannot be closed. `.shutdown_electron` remains an external stop signal for the supervisor; no in-app path writes it, since the ordinary quit path is simply Electron exiting.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add lifecycle action: define flag contract and watcher handling in launcher/host.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Incorrect flag behavior can cause app restart loops.
- Stale `.shutdown_app_<port>` plus premature process kill can cause next-launch startup timeout.
<!-- MANUAL:END -->
