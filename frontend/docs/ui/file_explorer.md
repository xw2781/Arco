# Frontend: File Explorer

## Purpose
<!-- MANUAL:BEGIN -->
Standard ArcRho tab for browsing local files with a customizable, resizable Favorite folders sidebar and a persistent details list.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.file_explorer.entry_points -->
- `ui/file_explorer/file_explorer.html`: external scripts `/ui/file_explorer/file_explorer.js?v=20260808a`, `/ui/shared/services/color_theme.js?v=20260923c`; inline imports _none_.

Detected `arcrho:*` message types in key JS files:
- `arcrho:browsing-history-updated`
- `arcrho:close-active-tab`
- `arcrho:file-explorer-path-changed`
- `arcrho:fullscreen-change`
- `arcrho:hotkey`
- `arcrho:status`
- `arcrho:update-active-tab-title`
- `arcrho:zoom`
- `arcrho:zoom-reset`
- `arcrho:zoom-step`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.file_explorer.key_files -->
- [`ui/file_explorer/file_explorer.html`](../../ui/file_explorer/file_explorer.html) - File Explorer iframe entrypoint and two-pane layout.
- [`ui/file_explorer/file_explorer.js`](../../ui/file_explorer/file_explorer.js) - Favorite-folder, navigation, file-list, and open-action controller.
- [`ui/file_explorer/file_explorer_model.js`](../../ui/file_explorer/file_explorer_model.js) - Favorite-folder schema plus file normalization, filtering, sorting, and formatting helpers.
- [`ui/file_explorer/file_explorer.css`](../../ui/file_explorer/file_explorer.css) - File Explorer sidebar, details table, state, menu, and dialog styling.
- [`ui/shared/file-icons/fileIconResolver.js`](../../ui/shared/file-icons/fileIconResolver.js) - Canonical shared common-file-type icon resolver.
- [`electron/preload.js`](../../electron/preload.js) - Renderer-safe folder preferences, listing, watch, and open APIs.
- [`electron/main.js`](../../electron/main.js) - Desktop favorite persistence, metadata listing, folder watching, and read-only Excel opening.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opened from the Home File Explorer card as one restorable `file_explorer` shell tab.
- Uses the Electron preload bridge for folder selection, directory listings, file opening, reveal/copy actions, and folder watches.
- Receives explicit shell visibility messages so background or minimized tabs do not keep a live folder watcher.
- The Favorites sidebar has a keyboard-accessible drag separator; its local-user width is retained in browser storage. Folder actions remain available from the folder row's context menu rather than a per-row overflow button.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Persists ordered favorite-folder paths and user nicknames in `%APPDATA%\Arco\prefs\home_folders.json`; browser local storage is a non-Electron fallback.
- Persists the Favorites sidebar width as the local-user `arcrho_file_explorer_sidebar_width_v1` browser-storage value.
- Requests file size and modified-time metadata only for File Explorer listings so existing Arcode listing payloads remain compatible.
- Uses `ui/shared/file-icons/` as the canonical resolver, mapping, and asset package shared with Arcode.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change File Explorer behavior or layout: update `ui/file_explorer/` and focused tests together.
2. Change shell tab lifecycle: update Home launch, tab actions, iframe host, visibility messaging, and shell docs together.
3. Change folder/file host operations: preserve existing preload IPC names and update Electron main/preload plus integration tests.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Folder paths can become inaccessible or disappear while pinned; these must remain visible as favorites and surface recoverable list errors.
- File opening is delegated to desktop associations; Excel read-only opening requires the explicit `/r` host path. That host spawn, and the PowerShell fallback behind it, must run from a real directory rather than the packaged `app.asar` app root.
- Watchers must stop while the tab is hidden and be replaced when navigation changes folders.
<!-- MANUAL:END -->
