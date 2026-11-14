# GUI Verification

Read this before looking at or driving a desktop application's window — ResQ, Excel, the ArcRho desktop app, or any other — to verify behaviour through its real GUI.

## Arco: use the Arco-only tool

For anything inside the Arco desktop app, use `tools/arco_window_control/arco_window_control.ps1` instead of the desktop tool below. It sends input into Arco's page only, so nothing outside Arco can be clicked and the person's real pointer never moves. Coordinates are window pixels, the same pixels as its unzoomed screenshots. A click, key press, or wheel turn by the person in Arco pauses the agent, and the next command exits with code `3`; stop at once. Its [README](../tools/arco_window_control/README.md) documents every command. It cannot reach Windows dialogs such as a file picker; use the desktop tool for those. The loop and rules below apply to it as well, with `-Window` meaning which Arco window to drive rather than a guard.

## Other applications: the desktop tool

Use `tools/agent_screen_control/agent_screen_control.ps1` for every step outside Arco. Do not write your own `SendInput`, `SetCursorPos`, or `CopyFromScreen` code. The tool already solves three problems that each broke a hand-written attempt:

- **Coordinates.** It works in real screen pixels. After a Remote Desktop reconnect at a different scale, a process using the older DPI setting sees a stretched screen, and its clicks land 25% away from what its screenshot showed.
- **Wrong window.** A click names the window it expects (`-Window`), and the tool refuses when anything else is under the target. A test window once ended up behind ResQ and the clicks went into the live ResQ window.
- **The person at the desk.** The screen is someone's live Remote Desktop session. The tool shows an overlay saying an agent is in control, draws its own pointer, borrows the real pointer only for the instant of each click, and gives a **Release** button that stops the agent.

The tool's [README](../tools/agent_screen_control/README.md) documents every command and option.

## The loop

1. **Find the window.** `windows -Window <text>` lists matching windows front to back with their positions. Dialogs are separate windows; a program's taskbar entry can be a zero-size window.
2. **Take control.** `start -Agent '<model name>' -Action '<first step>'`. Use `-Position TopRight` or another corner when the panel would cover what you need.
3. **Look.** `screenshot -Out tmp_data\gui\<name>.png` for a region or `-Window <text>`, then read the image. Capture only the area you need, and zoom in (`-Zoom 2` or `3`) on thin targets. The command prints the region's origin; convert image points back to screen points with it.
4. **Act.** `click -X -Y -Window <text> -Action '<what and why>'`, with `-Button Right` or `-Button Double` as needed, or `drag -X -Y -ToX -ToY -Window <text>`. Check `$LASTEXITCODE` after every command: `3` means the person pressed Release, so stop at once; `4` means the tool refused or could not confirm, and the warning says why.
5. **Check.** Take a fresh screenshot after every action that changes the screen. Windows move and resize between steps, so never reuse coordinates from an older screenshot.
6. **Finish.** `stop` in the same block that ends the work, and delete your screenshots under `tmp_data\`.

## Rules

- **Read-only unless asked.** Opening, expanding, selecting, scrolling, and resizing panels are fine. Do not click Save, Apply, OK on an edit form, Refresh, Delete, or anything that writes data unless the user asked for that change. Close an edit form with Cancel.
- **Always pass `-Window`**, and name the specific dialog when one is open.
- **After a timeout, look before retrying.** A timeout means the click was not confirmed, not that it failed; a blind retry can double-click. `overlay.log` in `%APPDATA%\Arco\agent_screen_control` shows how far the command got.
- **Put the layout back.** When a test drags a divider or resizes a panel, drag it back and compare a screenshot with the one taken before.
- **The Remote Desktop window must stay open.** When the person minimises it, the remote screen stops drawing and clicks and screenshots fail; ask them to restore it rather than retrying.
- **Keyboard input is only in the Arco tool.** It has `type` and `key`. The desktop tool has none; when a step outside Arco needs typing, say so rather than improvising a key sender.
