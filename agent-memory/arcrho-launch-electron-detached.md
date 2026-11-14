---
name: arcrho-launch-electron-detached
description: Launch ArcRho via Win32_Process.Create; electron started from the agent shell dies or crashes at main.js:41
metadata: 
  node_type: memory
  type: project
  originSessionId: 65357351-b081-4660-97de-09268c8952fc
  modified: 2026-08-09T16:51:43.639Z
---

Starting ArcRho from the agent's Bash/PowerShell tool does not work by the obvious routes:

- Running `electron.exe .` or `npm run electron` directly from Git Bash exits immediately, logging
  `TypeError: Cannot read properties of undefined (reading 'getName')` at `electron/main.js:41`.
  That is the signature of `main.js` being loaded outside a real Electron host, **not** a bug in
  `main.js`.
- `Start-Process` from the tool's PowerShell starts it, but the process is killed when the tool
  call ends.

What works is creating a fully detached process:

```powershell
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
  CommandLine = 'cmd.exe /c "E:\XWSpace\Repos\Arco\frontend\launch_arcrho_dev_mode.bat"';
  CurrentDirectory = 'E:\XWSpace\Repos\Arco\frontend'
}
```

Readiness signal: poll for `%APPDATA%\ArcRho\app_ui_ready.json`, which `main.js` writes on
`did-finish-load`. It is written **once per launch** - do not delete it and then wait for it to
reappear. `app_endpoint.json` is not a substitute; it appears when the backend is ready, well
before the window paints.

`launch_arcrho_dev_mode.bat` (2026-08-09) is the only dev launcher; it replaced `start_electron.bat`,
`start_electron_no_python_window.bat`, and `start_arcode.bat`. Pass `arcode` as its one argument to
launch Arcode instead of ArcRho.

Electron main-process crash logs land in
`%APPDATA%\arcrho-electron\logs\electron-main-*.log` (not under `ArcRho\logs`).

Related: [[arcrho-dev-ui-cache-restart]]
