# Project Settings Multi-Tab Plan

Version: v0.1
Updated: 2026-10-09
Status: Draft, not started

---

## 1. Goal

Let a user keep the settings of several projects open at once, each in its own tab, so moving between projects no longer means re-selecting them in the Project Explorer tree.

- The existing **Project Explorer** tab stays as it is: the tree on the left, one selected project on the right.
- A new **project tab** shows one project's settings, with the project name as the tab title. It has no tree and cannot switch to another project.
- **One editable copy per project.** A project is open in at most one place at a time: either the Explorer's selection or its own project tab. Opening a project that already has a tab switches to that tab.

This rule matters because field mapping, dataset types and reserving class types auto-save with no version check. If two tabs edited the same project, the later save would silently overwrite the earlier one. Only data processing rules and the project registry detect a stale copy today.

Out of scope: more than one Explorer tab, and side-by-side comparison inside a single tab.

---

## 2. Current State

| Concern | Today | File |
| --- | --- | --- |
| Opening | `openProjectSettingsTab()` switches to the existing tab if there is one | [tab_actions.js:308](../../ui/shell/tab_actions.js#L308) |
| Restore from history | Finds the first `project_settings` tab | [tab_actions.js:388](../../ui/shell/tab_actions.js#L388) |
| Saved tab state | Keeps only `projectSettingsRibbon` | [shell_state.js:111](../../ui/shell/shell_state.js#L111), [shell_state.js:188](../../ui/shell/shell_state.js#L188) |
| Activity history | Keeps only the ribbon | [shell_activity_history.js:132](../../ui/shell/shell_activity_history.js#L132) |
| Page URL | `project_settings.html?v=...` with no project | [iframe_host.js:193](../../ui/shell/iframe_host.js#L193) |
| Initial project | Read from one fixed sessionStorage key that every frame shares | [project_settings_tree_view.js:14](../../ui/project_settings/project_settings_tree_view.js#L14), [project_settings.js:641](../../ui/project_settings/project_settings.js#L641) |
| Tree project menu | Rename, Duplicate, Delete | [project_settings.html:521](../../ui/project_settings/project_settings.html#L521) |

These already work per tab and need no change:

- **Shell menu commands** (save/load to a local file) go only to the active tab ([shell_menus.js:381](../../ui/shell/shell_menus.js#L381)).
- **Progress and ribbon messages** are matched to the frame that sent them ([shell_messages.js:98](../../ui/shell/shell_messages.js#L98), [shell_messages.js:241](../../ui/shell/shell_messages.js#L241)).
- **Project lock** is read from the server.
- **Pending-job recovery** (source refresh, duplicate) is keyed by project.
- **Page state** lives in each frame's own JavaScript, so two frames share nothing in memory.

Project Instance tabs are the model to copy. They carry `projectName` on the tab, pass it in the page URL, and avoid opening the same project twice ([tab_actions.js:341](../../ui/shell/tab_actions.js#L341)).

---

## 3. Design

### 3.1 Tab model

A `project_settings` tab gains optional `projectName` and `projectFolder`.

- No `projectName` means the Explorer tab. A saved session from before this change restores as the Explorer, so no migration is needed.
- With a `projectName`, it is a project tab. Its title is the project name and its id prefix stays `ps_`.
- The ribbon (`projectSettingsRibbon`) is still kept per tab.

### 3.2 Opening a project tab

`openProjectSettingsTab(project?, options?)`:

- With no project, it behaves as it does today: one Explorer tab, focused if it already exists.
- With a project, it focuses that project's tab if one exists, matching the name case-insensitively. Otherwise it creates a new tab.
- The frame URL adds `project=` and `folder=`, the same way `project_instance` does.

Entry points:

- **Tree right-click** on a project gains **Open in New Tab**, above Rename.
- **Middle-click** on a tree project does the same.
- **Activity history and restore** reopen the exact project tab.

### 3.3 Project mode in the page

When the URL has `project=`, the page:

- hides the tree pane and its resizer, and takes the full width for the detail panel;
- loads the registry as it does today, then selects that project and never shows the empty state;
- neither reads nor writes the shared selected-project sessionStorage key, so it cannot change which project the Explorer reopens;
- shows a short "This project no longer exists" state if the project is missing, with no tree to fall back on.

Rename stays available from the detail header. Duplicate, Delete and Create stay in the Explorer only.

### 3.4 One editable copy per project

The shell owns the list of projects that have their own tab.

1. Whenever a project tab opens, closes or is renamed, the shell posts `arcrho:project-settings-open-projects` with the list of names to the Explorer frame. It posts the list again when that frame finishes loading.
2. When the Explorer is about to select a project in that list, it posts `arcrho:project-settings-open-project` instead. The shell focuses that project's tab and the Explorer keeps its current selection.
3. When a project tab opens for the project the Explorer has selected, the Explorer first flushes any pending auto-save for that project, then clears its selection.
4. Tree rows for projects open in their own tab show a small "open in tab" marker, so the redirect does not surprise the user.

Step 3 needs a flush of every pending debounced save for that project. Check that each auto-save feature exposes one; the scheduler in [project_settings_auto_save.js](../../ui/project_settings/project_settings_auto_save.js) may need a `flush(projectName)`.

### 3.5 Keeping tabs in sync after registry changes

Today a registry change made in one frame leaves the other frame on an old revision. Its next registry write then hits a conflict and reloads the page. With several tabs this becomes common, so:

- After any successful registry write (rename, move, duplicate, delete, create), the page posts `arcrho:project-registry-changed` with the old and new names.
- The shell relays it to every other `project_settings` frame and to its own tab records.
- **Explorer frames** reload the project map quietly and keep their selection, following a rename.
- **Project tabs** follow a rename by updating their title and `projectName`. On a delete they show the "no longer exists" state.

This is in-session only. Changes made by another user still reach this session through the existing revision conflict, as they do today.

---

## 4. Steps

### Step 1 — Shell: project tabs

- `openProjectSettingsTab(project, options)` with find-or-create by project ([tab_actions.js](../../ui/shell/tab_actions.js)).
- Fix the history restore path so it opens the right tab rather than the first one ([tab_actions.js:388](../../ui/shell/tab_actions.js#L388)).
- Save and restore `projectName` and `projectFolder` for `project_settings` tabs in both save and restore normalisers ([shell_state.js](../../ui/shell/shell_state.js)).
- Add `projectName` to activity-history entries ([shell_activity_history.js](../../ui/shell/shell_activity_history.js), [tab_actions.js:50](../../ui/shell/tab_actions.js#L50)).
- Pass `project` and `folder` in the frame URL ([iframe_host.js:193](../../ui/shell/iframe_host.js#L193)).
- Handle a new `arcrho:project-settings-open-project` message from a frame.

### Step 2 — Page: project mode

- Read `project` and `folder` from the URL at start-up in [project_settings.js](../../ui/project_settings/project_settings.js).
- In project mode, hide the tree, skip the sessionStorage selection, select the fixed project, and add the "no longer exists" state.
- Add **Open in New Tab** to the project menu ([project_settings.html:521](../../ui/project_settings/project_settings.html#L521)) and middle-click in [project_settings_tree_view.js](../../ui/project_settings/project_settings_tree_view.js).

### Step 3 — One editable copy per project

- Shell pushes the open-project list to the Explorer frame.
- Explorer redirects selection, shows the row marker, and flushes then releases its selection when needed.
- Add the auto-save flush if it is missing.

### Step 4 — Registry sync

- Page posts `arcrho:project-registry-changed` after registry writes ([project_settings_project_map.js](../../ui/project_settings/project_settings_project_map.js), [project_settings_project_ops.js](../../ui/project_settings/project_settings_project_ops.js)).
- Shell relays it, and updates project-tab titles and names.
- Explorer reloads its map quietly; project tabs follow a rename or show the deleted state.

### Step 5 — Tests and docs

- **Node tests** for find-or-create, the restore round trip of `projectName`, the old-session restore as Explorer, and the shell relay and open-project routing.
- **Page test** that project mode never writes the shared sessionStorage key.
- **Docs:** update [project_settings.md](../ui/project_settings.md) and [shell.md](../ui/shell.md) with the two tab kinds and the one-copy rule.
- **GUI check** in Arco: open three project tabs, edit dataset types in one, rename another from the Explorer, restart, and confirm every tab restores on its project.

---

## 5. Risks and Open Questions

- **Duplicate-name matching.** Project names are matched case-insensitively, as Project Instance tabs do. If two folders can hold projects with the same name, the tab key must include the folder. Check the registry rules before Step 1.
- **Hidden auto-save state.** Some features may keep unsaved edits outside the shared scheduler. Step 3's flush must cover them all, or the handoff can drop an edit.
- **Memory.** Each tab loads the full page (about 18k lines of script) and its own copy of the registry. That is fine for a handful of tabs and is not worth optimising first.
- **Floating windows.** Project tabs inherit floating-window support. Check that the full-width layout without the tree reads well in a small floating window.
- **Other users.** The one-copy rule covers this session only. Two users on the same project can still overwrite each other's auto-saved grids, as today. That gap is separate from this plan.
