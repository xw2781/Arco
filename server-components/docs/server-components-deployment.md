# ArcRho Server Components Deployment

## Release artifact

`ArcRho-Server-Setup-<version>.exe` is the offline, per-user companion installer
for Arco Engine, Orchestrator, Bridge, Launcher, and Admin Control. Its version
must match `frontend/package.json`. It is published beside the matching
`Arco-v<version>` frontend release with a SHA-256 checksum and is also copied
to `releases/server-installers` in the ArcRho Server release share.

Build with Python 3.10:

```powershell
py -3.10 server-components/server-installer/build_release.py
```

The build runs every component's PyInstaller build with
`ARCRHO_STAGE_ONLY=1`, freezes the deployment helper, stages the five complete
one-directory apps, writes `payload-manifest.json`, validates the staged
inventory, and compiles the standalone NSIS installer. Generated output is
under `server-components/server-installer/out/<version>/`.

Every component build verifies that its cached virtual environment is Python
3.10 and replaces a stale environment created by another Python version. The
release copy excludes Python/source caches and migration validation-result
output before calculating the manifest, so machine-local build artifacts cannot
enter the client payload.

For an already validated local component/helper build, use
`--reuse-component-builds --reuse-deployer-build`. `--stage-only` validates the
payload without invoking NSIS.

## Deployed build identity

### User Guide source

`frontend/user-manual` owns the HTML guide, its styles, scripts, and screenshots.
Gateway serves `GET` and `HEAD /user-guide/` from `<Server root>/user-guide`,
outside its frozen executable. `/user-guide` redirects to the trailing-slash
address so relative links work. This documentation route is public to anyone
who can reach Gateway, carries no user credential, and permits only guide web
assets. It does not list directories or serve JSON, project data, parent paths,
Windows drive paths, or links resolving outside the guide directory. Responses
use `no-cache` so a newly published guide appears without a Gateway restart.

A Gateway build publishes the source through the shared staged deployment
rotation before swapping the executable. The working-tree build request includes
`frontend/user-manual`, while guide edits alone do not mark the executable stale.
To publish documentation only, without freezing or restarting Gateway, run:

```powershell
py -3.10 server-components/publish_user_guide.py
```

The publisher uses the configured Server root and honors `ARCRHO_DEPLOY_ROOT`
with the same workspace-root consistency check as component builds. It mirrors
the source through the deployment tooling's standby slot and rollback mechanism;
the browser never reads the share. Deploy Gateway before releasing the Help →
User Guide menu action; the additive route is compatible with released clients.

### Component builds

Components are also deployed straight from the repository by their own
`build_exe.py`, which is how Gateway reaches a workspace at all: the offline
installer ships only the five receipted components. Either path stamps the
folder it writes.

That repository path normally runs on the server rather than on the client that
wants the deploy: `server-components/deploy.py` queues a build request and the
ArcRho Build Listener runs the same `build_exe.py` locally, which is what keeps
the frozen build off the network (see "Remote build requests" in
[architectures.md](../architectures.md)). The stamp is unchanged either way —
`git_dirty` still reports a working-tree build, because a request carries the
requester's uncommitted source as a patch.

`stage_deploy` records the build in the same `.arcrho-deploy-manifest.json` that
carries the copy delta, so the record rotates with the folder it describes and a
parked build keeps saying which release it is. Schema version 2 adds
`bundle_version`, `built_at`, `built_by`, `git_commit`, and `git_dirty`; a
version 1 manifest still works as a delta base and reports as unstamped.

`bundle_version` is read from `frontend/package.json`. The whole product ships
under one version — `build_release.py` already refuses a server payload whose
`product_version` differs from the desktop app's — so a directly deployed
component must not mint a version of its own. `git_dirty` is what keeps
`git_commit` honest: components are routinely rebuilt from a working tree
mid-change, and a commit alone would describe such a build as reproducible.

`swap_deploy` renames the live folder aside, which Windows refuses with
`WinError 32` while any process still holds it, so every component's build must
account for being deployed while it runs. Bridge, Engine, Gateway, Orchestrator
and Admin Control each set their own `apps.<role>.kill_all` switch, wait for the
component's heartbeats to disappear, swap, then clear the switch and restart.
Admin Control is the exception that proves the rule: nothing supervises it, so
its build relaunches the local server itself (headless — a deploy restores the
server, not somebody's browser tab), and an open Admin Control page needs a
refresh afterwards. The Launcher instead recovers from the failed rename by
replacing the folder's contents in place, because the process pinning its folder
is another app that inherited it as a working directory rather than the Launcher
itself. `server-components/tests/test_component_deploy_swap_safety.py` pins that every
deployed role has one of those two answers: without it, a component that cannot
be swapped while running fails its rename after the retries expire, and because
the build listener abandons a request at the first component failure, it takes
every other component in that run down with it.

```powershell
py -3.10 server-components/src/deploy_rollback.py status
```

`status` prints the deployed and parked build of every component in
`utils.DEPLOYED_COMPONENT_ROLES`, and names the discrepancies that matter for a
single-version bundle: components that disagree on the version, and a server
running behind the repository.

## Rollback

A deploy rotates the live folder into its standby slot, so the build it replaced
stays on the server complete. `swap_deploy` rotates live and slot in both
directions, which makes a rollback the same three renames run backwards rather
than a second transaction with its own failure modes.

```powershell
py -3.10 server-components/src/deploy_rollback.py rollback [--role gateway] [--yes]
```

Rollback defaults to the whole bundle, prints the plan, and asks before it
touches anything. Each component is stopped through its own build script's
stopped window, so the kill switch, heartbeat wait, and restart are the ones
that component already uses to deploy; the Launcher is the only component that
deploys and rolls back without one. A component is skipped when it has
no parked build, or when the parked build is the one already deployed — the
state the Launcher's in-place fallback leaves behind.

Only the immediately previous build is recoverable. The slot is also the delta
base the next deploy compares against, so a second deploy overwrites it. Older
releases come back by rebuilding them from the repository, not from the server.
Roll back the bundle rather than a single component when
`HTTP_CONTRACT_VERSION` in `arcrho_hosted_save_http_contract` moved between the
two versions, because a mixed pair can fail to agree with the installed desktop
app.

## Workspace and ownership

Setup accepts any writable absolute folder on a local fixed Windows disk. UNC
paths, mapped drives, drive roots, protected system/program folders, files, and
invalid paths are rejected before live workspace mutation. A root that would make an
installed payload file exceed the Windows-safe path boundary is also rejected
with a prompt to choose a shorter folder. The selected workspace owns:

- `apps`: installed component directories and the hidden installer receipt;
- `config`: shared component configuration;
- `projects`, `requests`, and `runtime`: shared operational data.

The receipt at `apps/.arcrho-server-installer/install-receipt.json` records its
schema version, installation ID, normalized root, installed version, UTC install
time, canonical component inventory, file sizes, and SHA-256 hashes. It is
installer metadata, not project data. Unknown apps and all non-`apps` workspace
data remain outside installer ownership.

## Server identity

Every server root carries a `server_id`, a GUID in `config/config.json` that is
written once and never replaced. `server_config.ensure_server_config` adds it
(the installer, adoption and `tools/local_server.py`), and the Gateway's own
deploy adds it with `ensure_server_id` while the Gateway is stopped, which is
how an existing server gains one. An Admin Control configuration reset keeps
it. The Gateway reads the id once as it starts and returns it from
`/api/capabilities`; the desktop app refuses a Gateway whose id differs from
the one in the folder it is pointed at, so a credential for one server is never
used against another server's folder.

## Install, adoption, upgrade, and repair

The helper selects the lifecycle operation from the receipt and workspace:

- an empty unreceipted workspace is a clean install;
- an existing unreceipted workspace is adopted;
- a newer payload upgrades a receipted workspace;
- the same version repairs it;
- an older payload is rejected as a downgrade.

Before mutation, the helper validates every payload file against the manifest,
acquires an exclusive per-workspace lock, creates/merges canonical configuration
defaults, and copies the complete payload into a same-volume staging folder.
Adoption merges missing defaults only; worker choices, ResQ credentials, unknown
configuration, projects, and queued requests are retained.

For replacement, the helper preserves all kill-switch values, signals Engine,
Bridge, Orchestrator, and Admin Control to stop, and aborts before changing live
binaries if their heartbeats do not disappear. It then renames all five live
folders to a transaction backup and all staged folders into place. Any swap,
receipt, configuration, launch, or heartbeat-verification failure stops the new
processes and restores every prior folder and the prior receipt. Backups are
deleted only after fresh Orchestrator and Engine heartbeats prove startup.
Atomic renames retry bounded transient antivirus/file-lock errors; a persistent
lock aborts and rolls back rather than falling back to an in-place overwrite.

Launcher remains a per-user login program because Bridge requires an interactive
ResQ session. Setup also adds an Admin Control Start Menu shortcut. If requested,
it calls the canonical Python API `set_server_root` to configure
`%APPDATA%\ArcRho\workspace_paths.json` without changing that file's schema.

## Uninstall and publication

Uninstall stops components, transactionally parks only the five receipted app
folders, deletes the parked binaries, then removes the receipt and startup/Start
Menu integration. It preserves projects, requests, configuration, credentials,
runtime history, and unrelated apps. A deletion problem fails the uninstall and
retains the receipt so a subsequent repair or uninstall can recover ownership;
shared data is never exposed to recursive deletion.

Publish only after the matching frontend GitHub release exists:

```powershell
powershell -NoProfile -File server-components/server-installer/publish_server_installer.ps1 `
  -InstallerPath server-components/server-installer/out/<version>/ArcRho-Server-Setup-<version>.exe
```

Server upgrades are operator-initiated; neither ArcRho Desktop startup nor its
updater silently replaces shared host components.
