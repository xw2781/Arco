---
name: local-test-root
description: "Since 2026-09-26 the Client PC runs a private server root at C:\\Arco Server via tools/local_server.py; deploy server changes there first, launch-app for the test client; on the Server PC it is E:\\XWSpace\\Arco Server (never C:)"
metadata:
  node_type: memory
  type: project
  originSessionId: dceedf07-29d5-400b-9dfb-1b5d138ebc34
  modified: 2026-09-27T00:40:50.475Z
---

Since 2026-09-26 the Client PC (L-H2MQ6280FVP, see [[dev-pc-and-client-pc-identity]]) keeps a second server root at `C:\Arco Server`, run by `tools/local_server.py` (`init`, `copy-project`, `deploy`, `start`, `stop`, `status`, `launch-app`). Engine and Gateway are built from the working tree; the Orchestrator was copied from production; the Gateway listens on 127.0.0.1:28767; the local credential is `%APPDATA%\ArcRho\arcrho_gateway.local.json`; `launch-app` runs the dev app on port 28785 with its own Electron profile (`ARCRHO_USER_DATA_DIR`).

On the Server PC (NE7SASWPN02) the test root is `E:\XWSpace\Arco Server`, not C: — user rule of 2026-11-04, when it was moved there. `local_server.py` picks it by computer name; its `config\config.json` `root` was rewritten to match.

**Why:** the user wants server changes (starting with the SMB retirement, docs/plans/client_smb_retirement.md) tested on their own PC before other users see them; docs/plans/completed/local_server_root_and_server_switcher.md records the design and limits.

**How to apply:** deploy to the local root first (`py -3.10 tools/local_server.py deploy`), check with `launch-app`, then run `server-components/deploy.py` for production. Building by hand needs BOTH `ARCRHO_DEPLOY_ROOT` and `ARCRHO_ROOT`, or the Engine/Orchestrator builds look for kill switches under the repo. Never give a client `ARCRHO_RUNTIME_SERVER_ROOT` (it turns the Gateway off). No ResQ/Bridge on the local root. The local Fake project copy is being refreshed per docs/plans/completed/fake_project_refresh.md.
