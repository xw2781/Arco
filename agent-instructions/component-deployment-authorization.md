# Component Deployment Authorization

Read this before rebuilding or redeploying any frozen server component. It covers how to run a deploy, what each component's rebuild costs, what to verify afterwards, and how far the standing authorization reaches.

## Running a deploy (MUST)

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
- **The listener owns its clone, so it must have one nobody edits.** Every claimed request checks out a detached base commit in the listener's clone, resets the working tree and deletes untracked files. That clone is not a setting — it is wherever the listener's own code was started from. It runs from `E:\XWSpace\Repos\ArcRho-buildbot`, which carries the working clone as a second remote so an unpushed commit still resolves. Before deploying, check that the newest heartbeat under `E:\Arco Server\runtime\instances\arcrho_build_listener\` names that clone; if it names a clone anyone edits, stop and move the listener with `tools\arcrho_service_control.ps1` rather than deploying, or the next deploy will revert their uncommitted work.
- **Exit codes are the result**: `0` success, `1` the build or deploy failed, `2` a usage or precondition problem, `3` no listener is running. Report a non-zero result plainly and do not retry blindly.
- **No listener on the Server PC is handled for you**: there, the CLI starts the Build Manager from the one sibling clone marked `.git/arcrho-build-clone`, which listens by itself, and waits for it. Exit code `3` therefore means a Client PC, or a Server PC with no single marked clone.
- **The one human step**: on exit code `3`, ask the user to run `server-components\build_manager.bat` on the ArcRho Server machine and turn on "Listen for build requests". Relay the CLI's message; do not attempt to start it remotely.
- **A forced stop blocks the next Engine deploy.** The deploy waits on the heartbeat files under `E:\Arco Server\runtime\instances\` to decide the old Engine is gone, and a component killed rather than closed leaves its file behind, so the wait cannot succeed and the deploy aborts. Clear them with `tools\arcrho_service_control.ps1 -Action clear-stale-heartbeats`, which removes only a heartbeat with no live process behind it.

`server-components/build_manager.bat` remains the direct interface for a human at the server.

## Standing authorization

The user pre-authorizes agents to rebuild, redeploy, and relaunch any component below, including stopping that component's own running instances, whenever a task changes code it bundles. Do not request conversational confirmation for the build, deploy, stop, or relaunch; do still request any platform-required sandbox escalation.

The authorization is per component. Stopping one never authorizes stopping another, and it never authorizes stopping ResQ.

**The authorization covers only a deploy that cannot break users on the latest released app.** Every user runs the latest released desktop app, so before rebuilding decide whether that released app keeps working against the new server component. It does when the change is confined to the server side: a fix inside a job, a new job kind nothing released calls yet, a new optional field a released reader ignores. It does not when the server starts to require something the released app does not send, changes a response shape or persisted JSON the released app reads, or removes or renames a route or request kind. In that second case stop before building and tell the user explicitly what breaks and that the fix needs a frontend release, a coordinated release plus deploy, or a compatibility step; do not deploy until they answer.

## Ship impact statement (MUST, before code changes)

Before changing code for a feature or fix, state in one short block how it ships, so the user can weigh it before any work starts:

- **Frontend release only** — the change lives in `frontend/ui`, the Electron host, or app-server code that runs only inside the desktop app, and no server component bundles it.
- **Server component redeploy only** — the change lives in code bundled by Engine, Gateway, Bridge, Orchestrator, Admin Control, or Launcher (read the bundle owner named in the table below; `frontend/app_server` is bundled by the Engine and Gateway, so a hosted save or read fix is a server deploy), and the released app already sends and reads what it needs.
- **Both, in this order** — say which side must go first and why the released app is safe in between. When no order is safe, say so; the user decides how to sequence the release.
- **Risk to the released app** — "none", or the concrete request, response, or file the released app would no longer handle.

Give the same statement again in the final response when the implementation changed the answer.

## Rules that apply to every component

- **A frozen component runs its bundled copy**, so an edit to a bundled tree has no effect until that component is rebuilt. Never trust a restated bundle list — read the owner module named in the table. Many changes that look unrelated to a component still require its rebuild.
- **Rebuild once per task**, after the change is verified and before reporting the task complete — not after each edit. Skip the rebuild when a task changed only tests, docs, release fragments, or files outside every bundle, and say so.
- **Never deploy a change that has not passed its checks.**
- **A failed build leaves the deployed component untouched.** The build scripts abort rather than half-deploy: a failed build, a live instance that will not stop within the timeout, or a rolled-back swap all preserve what is deployed. Report that outcome plainly and do not retry blindly.
- **Verify after deploying** using the component's row below, and **state in the final response** which components were rebuilt, redeployed, and relaunched, or why none were.

## Components

| Component | Bundle owner to read | Stopping it costs | Verify after deploy |
| --- | --- | --- | --- |
| **Bridge** | `arcrho_bridge/bundled_sources.py` — `BUNDLED_SOURCES`, `CANONICAL_MODULE_ROOT`, `CANONICAL_HIDDEN_IMPORTS` | Every ResQ import blocks while it is down | The Orchestrator relaunches it only when `apps.bridge.auto_create_instance` is true — that flag has flipped before, so check it and start the deployed exe manually if it is false. Bridges are per interactive user session |
| **Engine** | `arcrho_engine/bundled_sources.py` — `ENGINE_BUNDLED_SOURCES`, plus `build_exe.py`'s `--paths` and hidden imports | Every pending calculation, dependent-propagation, and project-duplication job pauses until instances return | Fresh heartbeats under `runtime\instances\arcrho_engine\`; if the Orchestrator is not running, start `apps\Arco Engine\Arco Engine.exe` manually |
| **Gateway** | `arcrho_gateway/build_exe.py` — its `--paths` and `--hidden-import` list (it bundles `ENGINE_BUNDLED_SOURCES`) | Hosted saves fail for enrolled users; a save in flight during the swap must be retried | Fresh heartbeat under `runtime\instances\arcrho_gateway\` and `GET <client_url>/api/health` → `{"ok": true}` |
| **Orchestrator** | `arcrho_orchestrator/build_exe.py` — its imports, PyInstaller paths, and deployment logic | Component replenishment pauses; Engine, Bridge, Gateway, and ResQ keep running | Fresh heartbeat under `runtime\instances\arcrho_orchestrator\`. When the task changed its supervision of another component, verify that component's readiness signal too |
| **Admin Control** | `server-components/src/arcrho_admin/` | Local administration UI is unavailable | `GET http://127.0.0.1:28766/api/health` → `{"ok": true}` and the process is running |
| **Launcher** | `server-components/src/arcrho_launcher/` | Nothing running is affected; it owns no runtime instance | Deployed executable is stamped with the new build |

An Orchestrator deploy relaunches at least one Orchestrator. Other users' per-session Orchestrators return through their normal Launcher/login lifecycle, and their already-running Engine, Bridge, and Gateway processes are untouched.

## Admin Control needs a stop and a reopen

It is the one component the deploy cannot fully cycle on its own:

1. Shut the running server down through `POST http://127.0.0.1:28766/api/shutdown` and wait for the listener to exit. If it does not respond but the process remains, terminate only the identified `Arco Admin Control.exe` so the folder can be replaced.
2. Deploy it.
3. Launch `apps\Arco Admin Control\Arco Admin Control.exe` with a hidden process window so the browser UI reopens.
4. Verify health as in the table.

## Fallback: building from a client machine

When no build listener is available, running a component's own `build_exe.py` still works from a client against the server workspace over the network. It is several minutes slower per component because the frozen build crosses the share; take it only when the listener is down, and say that is what happened.

Set `ARCRHO_DEPLOY_ROOT` to the mapped or UNC ArcRho Server path. The scripts align the workspace root from it before reading any configuration and refuse a pair naming two different workspaces, so the kill switch, heartbeats, and deployed folder always belong to the same server. When the deploy root is not a local fixed disk the script does not start the deployed executable — that would run the server's component on the build machine — so clearing the kill switch is enough and the server's Orchestrator restores it. Verification is unchanged.

Do not substitute manual process termination or an in-place executable overwrite for a build script's deploy: the slot rotation, rollback, and kill-switch restore all live in that path.

## Local test root first

On the developer PC a private root at `C:\Arco Server` takes the same Engine and Gateway builds without reaching any other user: `py -3.10 tools/local_server.py deploy` builds from the working tree into it, and `launch-app` opens the dev app against it. Deploy there first whenever the change can be checked without ResQ, then deploy to production as above. A deploy to the local root needs no ship-impact check, since no released app talks to it; the production deploy that follows still does. The root, its limits, and what keeps it apart are in [docs/plans/completed/local_server_root_and_server_switcher.md](../docs/plans/completed/local_server_root_and_server_switcher.md).

The developer PC `L-H2MQ6280FVP` keeps a private server root at `C:\Arco Server`; on the Server PC `NE7SASWPN02` it lives at `E:\XWSpace\Arco Server`, never on C:. Both are run by `tools/local_server.py` (`init`, `copy-project`, `deploy`, `start`, `stop`, `status`, `launch-app`). Nothing in it reaches production or other users; see [docs/plans/completed/local_server_root_and_server_switcher.md](../docs/plans/completed/local_server_root_and_server_switcher.md) for what keeps it apart and its limits.
- For work on the SMB retirement ([docs/plans/client_smb_retirement.md](../docs/plans/client_smb_retirement.md)), and for any server-component change whose effect can be checked without ResQ, deploy to the local root first (`py -3.10 tools/local_server.py deploy`), check it there with `launch-app`, and only then run `server-components/deploy.py` for production.
- Never point a build at the local root by hand without both `ARCRHO_DEPLOY_ROOT` and `ARCRHO_ROOT`; the tool sets both. Never give a client process `ARCRHO_RUNTIME_SERVER_ROOT`: it marks the process as a server and turns the Gateway off.
- In a `launch-app` session never save the Server Connection page; it writes the per-machine file the production app reads.
