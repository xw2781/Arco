# TODO

## Local test server root on the developer PC (moved 2026-09-26)

Built and in use: `tools/local_server.py` runs a private root at `C:\Arco Server` beside production. The proposal that stood here became [plans/local_server_root_and_server_switcher.md](plans/completed/local_server_root_and_server_switcher.md), which also plans switching servers from the app and records offline use for every user as a direction. The investigation corrected four of the proposal's assumptions:

- Saving the Server Connection page does **not** re-enrol with the new root's Gateway while a credential file exists; the app keeps signing to the old Gateway.
- Copied projects are not free of absolute paths: five caches hold `E:\Arco Server` paths (they rebuild), and the import source still names the production share.
- The deployer cannot create a bare root; `server_config.ensure_server_config` does, and the tool uses it.
- The Build Listener lives in the Build Manager window, not the Orchestrator; the local root does without one.

## Ship-impact statement and deploy gate (done 2026-09-20)

Recorded in `agent-instructions/component-deployment-authorization.md`:

- Before code changes, agents state how a feature ships: frontend release only, server component redeploy only, or both in a given order, plus the concrete risk to users on the latest released app.
- The standing rebuild/redeploy authorization applies only when the released app cannot break. Otherwise the agent stops before building and reports what breaks and what release sequence is needed.
