---
name: arcrho-ui-design
description: ArcRho frontend UI design reference for applying the app's dense, quiet, operational workspace style. Use when asked to make or fix frontend UI, visual styling, layout, controls, icons, dropdowns, tables, drag/drop areas, empty/loading/error states, or interaction polish in ArcRho; apply these rules during implementation and do not update the skill unless explicitly asked to revise durable design guidance.
---

# ArcRho UI Design Reference

## Purpose

Use this skill as the baseline reference for ArcRho frontend UI work. It captures the current modern, minimal, clean direction from the Atlas navigation demo in `frontend/docs/ui/global_app_ui_demo.html`.

Atlas is an object-first global app shell: a compact icon rail, searchable project tree, command strip, broad work canvas, and contextual activity panel. It should feel like a focused desktop analytics tool, not a marketing site.

## Design Prompt

### D01 - Operational workspace

Design ArcRho interfaces as dense, quiet, operational workspaces for actuarial data, DFM, workflow, scripting, and project management. Use the Atlas pattern: a thin global icon rail, structured object tree, command or search strip, large task canvas, and optional right-side context area.

### D02 - Visible working surface

Keep surfaces pale, borders precise, typography compact, and motion short. Favor visible data, controls, and state over decoration. Build working application screens with controls, tables, forms, tabs, drag/drop areas, status indicators, dialogs, toasts, and explicit empty, loading, and error states.

## Reference Routing

### R01 - Visual foundation

Always read [visual-foundations.md](references/visual-foundations.md) for visual styling, typography, color, borders, shadows, corners, motion, or general quality work.

### R02 - Layout and shell

Read [layout-and-shell.md](references/layout-and-shell.md) for page composition, shell regions, panels, tiles, sidebars, command strips, floating windows, dragging and resizing, responsive layout, or Atlas component work.

### R03 - Controls and states

Read [controls-and-states.md](references/controls-and-states.md) for buttons, inputs, dropdowns, menus and cascading submenus, steppers, switches, chips, pickers, dialogs, drag/drop, focus, hover, disabled, empty, loading, or error states.

### R04 - Tables and scrollbars

Read [tables-and-scrollbars.md](references/tables-and-scrollbars.md) for tables, sticky headers, table frames, scrollbars, keyboard visibility, or resizable columns.

### R05 - Cross-group work

Read every matching reference before editing when a task spans multiple groups.

### R06 - Detailed rules win

Do not infer a rule from this index when a linked reference provides the detailed guidance.

## Implementation Notes

### I01 - Reference demo

Use `frontend/docs/ui/global_app_ui_demo.html`, especially the `style-atlas` section and Atlas CSS selectors.

### I02 - Preserve contracts

Keep production shell changes compatible with frontend behavior contracts and `arcrho:*` message semantics.

### I03 - Demo location

Put standalone design demos in `frontend/docs/ui/` unless they are wired into runtime navigation.
