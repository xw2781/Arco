# Server Components Architecture Notes

## Deployment model

ArcRho Server components run on the Windows PC that locally hosts the selected
ArcRho Server workspace. The workspace folder may have any name; a frozen
component discovers it structurally from `<workspace>\apps\<component>` and an
explicit `ARCRHO_ROOT` remains the highest-precedence override.

Five components ship as one versioned server release:

- **Arco Engine** processes calculation, propagation, duplication, and other
  durable workspace requests. The Orchestrator normally maintains five workers.
- **Arco Orchestrator** supervises Engine and Bridge processes.
- **Arco Bridge** provides per-interactive-user ResQ automation. Its worker
  needs that user's ResQ GUI and COM session, so it is not a Windows service.
- **Arco Launcher** registers per-user login startup and starts Orchestrator
  and Bridge.
- **Arco Admin Control** exposes local component/configuration administration.

The offline companion installer and lifecycle contract are documented in
[Server Components Deployment](docs/server-components-deployment.md). The
frontend installer never owns these shared binaries.

## Component heartbeats and status

Every long-running component rewrites a heartbeat under
`<root>\runtime\instances\arcrho_<role>\` while it runs, and each role has a
stop switch at `apps.<role>.kill_all` in `<root>\config\config.json`.
`python-api/src/arcrho_server_component_status.py` is the one reader of both:
it lists the heartbeats with their machine, user and age, marks a heartbeat
stale after 6 seconds for Engines and Bridge workers and 60 seconds for every
other role, and reads the stop switches. Admin Control's instance table and the
desktop app's Server tab (through the Gateway's `server_component_status`
workspace read, or straight from disk when the server folder is on the same PC)
both use it, so the two cannot disagree about which component is stale.

## Component build deployment

`build_runtime.py` owns the copy-and-swap transaction every `build_exe.py`
deploys through; no build script restates it. A component keeps two folders
under `apps`: the live `<App Name>` and a standby `.<App Name>.slot`.

A deploy mirrors the new build into the standby slot while the component is
still running, then stops it only for three renames — live to `.<App Name>.prev`,
slot to live, `.prev` back to slot. Renames are executed by the file server, so
the stopped window is seconds rather than the length of a copy, and the build
that was live stays intact in the slot as both the rollback copy and the base
the next deploy compares against.

The copy is a delta because the slot already holds a build of the same
component; a rebuilt dist reuses the interpreter, site-packages, and DLLs
unchanged. PyInstaller stamps every file it collects with the moment of the
build, so timestamps alone report all ~1650 files as new even when ~99% are
byte for byte what was deployed. Each deployed folder therefore carries a
`.arcrho-deploy-manifest.json` recording its files' size, SHA-256, and
timestamp. Staging restores the deployed timestamp on files whose bytes are
unchanged — hashing the local dist, never reading back across the network — and
the mirror then skips them for one metadata round trip each.

Practical consequences:

- Do not delete a `.slot` folder or its manifest. Nothing breaks if they go, but
  the next deploy falls back to a full copy.
- The rotation needs two deploys to warm up: the first leaves no slot behind and
  the second parks a build that predates any manifest. Deltas start on the third.
- A deploy interrupted between the renames leaves the last good build in
  `.<App Name>.prev`; the next staging restores it before reusing the name.

## Remote build requests

The delta staging above removes most of a deploy's bytes but not its direction.
Measured from a client machine on 2026-08-17, the workspace share read at
50 MB/s while a deploy's writes ran at 0.18 MB/s, so the ~5 minutes a deploy
took was almost entirely the client pushing its build across the network.
Building on the machine that owns the disk removes that transfer, and
`arcrho_build_listener.py` is what lets a client ask for it.

The queue is a folder protocol under `requests\builds`, the same shape as
dependent propagation and project duplication, because the share is the one
channel every client already has and it survives the Gateway being down.
`arcrho_build_request_contract.py` owns the layout, the request and status
shapes, and the listener heartbeat; `arcrho_build_components.py` owns the
component table and the freshness rule that decides which components a change
made stale, so the Build Manager GUI and the `deploy.py` CLI cannot disagree.

A request carries source rather than a version. In the default `working-tree`
mode the client sends a patch of the affected trees against the newest commit
the server can already resolve, plus any untracked files, so a change that is
still uncommitted deploys normally — which matters because AGENT_GUIDELINES.md asks for a
rebuild *before* a change is committed. `ref` mode builds a pushed ref instead
and is the reproducible form.

Consequences worth knowing:

- **The listener owns its clone.** Every claimed request resets that working
  tree, so nobody may edit in it. That includes the listener's own source: a
  sync rewrites it, the running process keeps the code it already imported, and
  the listener should be restarted after a change to its own modules. Its
  heartbeat reports the commit it started from so the mismatch is visible.
- **Anyone who can write the queue can run repository code on the server.** The
  protection is the share's ACLs plus the listener's optional user allowlist.
- **A working-tree deploy carries the whole clone's state** under the affected
  roots, so concurrent edits by another person or agent in the same checkout
  travel with it. The CLI prints the changed and new files it is sending so that
  is visible rather than implied; `--ref` is the way to deploy without local
  state.
- The listener builds one request at a time and stops a request at its first
  failed component, so a broken source tree cannot half-deploy across
  components.
- A client cannot start the listener; that is the only step in the flow that
  needs a human at the server.

## `server-components/src/arcrho_bridge`

- ResQ import/export only; a separate module from permanent ArcRho processing.
- One supervisor per interactive user session; each user contributes the Bridge
  tied to their own ResQ GUI/license.
- Intended for migration support and removable when the ResQ transition ends.

## `server-components/src/arcrho_engine`

- Handles transformations and durable shared-workspace jobs.
- Runs as a worker pool on the local workspace host.
- Uses lease-backed request processing so concurrent workers do not update the
  same reserving class or project segment simultaneously.
