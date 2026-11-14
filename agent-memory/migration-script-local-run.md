---
name: migration-script-local-run
description: How to run python-api/migration/resq_data_migration.py — Client PC venv is ready but ResQ COM only exists on the Server PC
metadata: 
  node_type: memory
  type: project
  originSessionId: b757a9f5-ce16-42f7-ad0f-c286530f509e
  modified: 2026-08-21T17:51:22.627Z
---

The Client PC clone has full local component venvs under `server-components\venvs\` (engine venv = Python 3.10.11 with pandas, pywin32, fastapi, pydantic, numpy, openpyxl). `.vscode/settings.json` (gitignored, machine-local) points the Python interpreter and Code Runner at `server-components\venvs\arcrho_engine\Scripts\python.exe`, so VS Code "Run" uses 3.10 instead of the bare `python` (3.13, no packages).

**Why:** `resq_data_migration.py` imports app_server services (pandas) and needs pywin32; plain `python` fails at pandas. With the venv it runs up to `ResQ3Automation.ResQApplication` Dispatch and dies with 'Invalid class string' (confirmed 2026-08-21) because ResQ is not installed here — see [[resq-com-probe]].

**How to apply:** For a real migration run, execute on the Server PC (NE7SASWPN02), e.g. `E:\XWSpace\Repos\Arco\server-components\venvs\arcrho_engine\Scripts\python.exe -u ...\python-api\migration\resq_data_migration.py`. Its `main()` performs no writes before the ResQ connect succeeds, so a dry attempt on the Client PC is harmless. That clone is the Build Listener's repository ([[remote-component-deploy]]) — it gets hard-reset by deploys, so check its checked-out state first.
