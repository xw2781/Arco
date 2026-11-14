---
name: client-pc-primary-workstation
description: The Client PC is the primary development machine; Engine, Bridge, and Gateway already deploy to the server from there because the share is mapped to the same E: letter
metadata:
  node_type: memory
  type: project
  originSessionId: f4f319b0-3e2f-4953-b73b-0f0bfb281d98
  modified: 2026-08-16T00:00:00.000Z
---

As of 2026-08-15 the user works mainly on the Client PC (`L-H2MQ6280FVP`, repo
at `c:\Users\xwei\Repos\Arco`) rather than the Dev PC, and wants server
component builds triggerable from there. See [[dev-pc-and-client-pc-identity]].

**Engine, Bridge, and Save Gateway already build and deploy to
`E:\ArcRho Server\apps\` from the Client PC.** Verified 2026-08-16 against the
Client PC's own Claude session transcripts: repeated `Stopping live ArcRho
Engine instances` followed by `Build finished: E:\ArcRho Server\apps\...`.

**Why it works without any environment variable:** the Client PC maps
`\\NE7SASWPN02\E` to the *same drive letter* `E:`, so `E:\ArcRho Server` is
spelled identically on both machines. The hardcoded
`Path(os.environ.get("ARCRHO_DEPLOY_ROOT", r"E:\ArcRho Server"))` default in
each `build_exe.py` is already correct there, and `utils.get_project_root()`
resolves to the same place, so the deploy target and the kill switch/heartbeats
agree.

**How to apply:** do not claim these builds are Dev-PC-only, and do not treat
`build_runtime.align_workspace_root_env()` as a prerequisite for them. Its value
is contingency: it is what makes a build correct when the deploy root is spelled
*differently* from what `utils` resolves — a UNC path, or a different mapped
letter — and it refuses a mismatched pair instead of deploying against the wrong
workspace. Only `arcrho_gateway/build_exe.py` uses it today.

Two caveats still stand. Untested from the Client PC: Orchestrator, Admin
Control, Launcher — no `Build finished:` for them in any Client PC transcript.
The Orchestrator is the one that matters, because Gateway work drags it in
whenever `utils.py` or `server_config.py` changes, and unlike Engine and Bridge
its `build_exe.py` calls `start_orchestrator()` on the deployed exe with no
locality guard. Related: [[bridge-restart-after-deploy]].
