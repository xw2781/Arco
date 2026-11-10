---
name: arco-server-root-move
description: "2026-11-09 move of the live server root from E:\\ArcRho Server to E:\\Arco Server — what was done, what the agent could not do"
metadata:
  node_type: memory
  type: project
  originSessionId: e5c82069-8544-44ee-aebf-2c2de9a79a83
  modified: 2026-11-10T03:36:11.119Z
---

On 2026-11-09 the live server root moved to `E:\Arco Server` by copy (the old `E:\ArcRho Server` stays, its projects folder renamed `projects - backup`). Copied: projects, config, shared, Excel Add-ins, user-guide, packages, library, r, users, releases, archive, backups, apps, runtime\logs. Not copied: `requests`, `runtime\instances`, `runtime\locks`. All seven components were rebuilt into the new root and Arco.xlam 4.2.5 was released there.

The same night the visible component names changed from `ArcRho X` to `Arco X` (app folders, exe and process names, shortcuts): `apps\Arco Engine\Arco Engine.exe` and likewise Bridge, Gateway, Orchestrator, Launcher, Admin Control, Credential. Internal names stayed: `arcrho_*` source and heartbeat folders, config keys, `ARCRHO_*` variables, icon files. The Launcher removes the old `ArcRho Launcher` Startup shortcut. Add-in 4.2.6 starts `Arco Credential`.

**Why:** the old folder could not be renamed because another user's session (jhou, session 16) ran `ArcRho Gateway.exe` from it, holding port 28767.

**How to apply:**
- The Build Listener runs whatever code its clone had when it started. After a change to the server root name, stop it, check the buildbot clone out at the new commit, and restart it, or it listens under the old root and `deploy.py` exits 3.
- The auto-mode classifier denies an agent editing the old root's config (to trip another user's Gateway kill switch) and `icacls` grants on the root. The user must do those: the old root carried an explicit `PRCINS\Domain Users: Modify` grant that a new folder does not inherit.
- robocopy exit code 1 means files copied, not failure.
