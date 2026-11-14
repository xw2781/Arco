---
name: user-folder-on-server-and-arco-rename
description: 2026-11-14: per-user server folder (preferences, ArcBot chats, dashboards) and the ArcRho to Arco local-folder rename are coded but not released; release order matters
metadata:
  type: project
---

On 2026-11-14 the user asked to move each user's settings and documents to the Arco Server and to rename the PC folders from ArcRho to Arco. Coded in one change, not committed, not deployed, not released at the time of writing.

- **On the server** (`<root>\users\<login>\`, via Gateway kinds): `preferences.json` in sections, `arcbot\sessions`, `dashboards`. Owner: `server_user_profile_service.py`.
- **Stays on the PC**, by the user's decision: macros and scripts ("let the user's copy stay on their local drive for edits and run"). My own call, flagged to the user and not yet confirmed: workflows and templates also stay, because they go through Windows file dialogs; favourite folders, recent files and anything standalone Arcode shares stay too.
- **Theme** keeps a copy on the PC (user approved) and is adopted from the server before the window is built.
- **Folders**: `%APPDATA%\Arco` (profile inside it as `profile`), `%LOCALAPPDATA%\Arco`, `Documents\Arco`. The desktop host renames the old ones at start (`frontend/electron/local_folders.js`).

**Why:** the user wants settings to follow people across PCs and wants ArcBot chats on the Server PC "so that the developer can debug and improve the chat experience".

**How to apply:** the release order is server components, then the desktop app, then the Excel add-in (4.4.2 is edited and noted but was deliberately not built or released: released before the app it would make Excel and the app fight over the sign-in). Check `git log` for whether this has shipped before relying on any of it. See [[user-folder-tests-touch-real-folders]].
