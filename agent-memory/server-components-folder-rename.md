---
name: server-components-folder-rename
description: data-engine/ was renamed to server-components/ on 2026-08-25; the build listener was restarted from the new folder that same day, but every venv and build tree was lost with the old folder
metadata: 
  node_type: memory
  type: project
  originSessionId: 7b01be8b-9594-4b09-aaf2-56419c4df111
  modified: 2026-08-25T17:02:16.646Z
---

On 2026-08-25 the repo folder `data-engine/` became `server-components/` (Engine, Orchestrator, Bridge, Launcher, Admin Control, Gateway, build listener/manager, server installer). Every tracked path reference and the `DATA_ENGINE_*` test anchors were rewritten in the same commit; archived release notes and macro backups keep the old name on purpose.

**Why:** The folder had outgrown its name — only a third of it was the Engine — and the Gateway could not be carved out because it imports Engine modules and shares the one component/deploy table.

**How to apply:** Done on 2026-08-25 — the buildbot clone `E:\XWSpace\Repos\ArcRho-buildbot` was reset onto `origin/main` at `ea15a683` and the listener restarted with `tools/arcrho_service_control.ps1 -Action listener-start`; its heartbeat now reports that clone at that commit. **The `venvs\` and `builds\` trees did not survive.** The plan below assumed the listener's `git clean -fd` (no `-x`) would spare them for a rename, but by then the whole `data-engine\` folder had already been deleted from disk in both clones, so the first deploy after the rename rebuilds every component's virtual environment from scratch — budget for a much longer run than usual. See [[remote-component-deploy]].

The buildbot clone's remotes are `origin` (GitHub) and `worktree` (`E:\XWSpace\Repos\Arco`, the Server PC's own working clone — not the Client PC clone), so a commit must be pushed to GitHub or pulled into that server clone before the listener can resolve it. Git refuses to run against the buildbot clone **over the share** ("dubious ownership") — read its `.git/config` and `.git/HEAD` as plain files from a client; from a session on the Server PC itself `E:` is a local drive and ordinary git commands work there normally. See [[dev-pc-and-client-pc-identity]] and check `hostname` before assuming which side you are on.

The Build Manager now ticks "Listen for build requests" by itself when the workspace drive is local *and* the clone carries the untracked marker file `.git/arcrho-build-clone` (`auto_listen_decision` in `arcrho_build_components.py`), so on the Server PC starting `server-components\build_manager.bat` is enough — the old "the checkbox defaults to off" step no longer applies there. A fresh clone will not auto-listen until that marker is created.
