# Frontend Behavior Contract

## Purpose
Set lightweight frontend behavior guardrails for the current pre-production app.

Prefer clean coordinated refactors over compatibility shims unless the user explicitly asks for migration support.

## Scope
This contract applies when changing shell/tab orchestration, iframe pages, keyboard/menu actions, or cross-frame `arcrho:*` messages.

## Core Rules
1. Preserve shell and iframe state semantics unless intentionally changing them. Keep tab state, iframe lifecycle, and dirty-state prompts coherent.
2. Change `arcrho:*` message contracts only as coordinated refactors. Update all known producers, consumers, and docs in the same change.
3. Keep user-facing save, close, restart, import/export, and error flows explicit. Do not silently swallow failures for actions users can observe or depend on.
4. Avoid lifecycle and performance regressions such as duplicate listeners, accidental full reloads, infinite refresh loops, lost tab state, or iframe recreation unless the task intentionally changes that behavior.
5. Keep Project Instance disk-backed dataset inventory refreshes tied to durable saves or explicit user refreshes. Unsaved Dataset grid edits, including pasted Excel references, may publish in-memory dependency previews but must not trigger an inventory refresh.
6. Keep one owner for the Details tab. `ui/shared/tabs/details/details_form_layout.css` owns label and field typography, colour, size, and focus for every `.arDetailsRoot` page; a page stylesheet may add layout a field genuinely needs, such as a picker inset, but must not restate the shared look. `ui/shared/tabs/details/details_host_fields.js` owns which rows a host suppresses: a row whose value the host fixes is tagged `data-details-field` on both of its grid cells and is hidden everywhere except a Workflow step, the one host that still lets the user choose the project inside the embedded page. Hide such a row rather than removing its control, because page controllers read and write those inputs whether or not the host shows them. Every Details tab orders its rows into up to four `.arDetailsSection` blocks, in this order and with no headings: **identity** (`Name`, the output identity row, `Project`, `Segment`, `Method Type`), **inputs and dependencies** - what the output is computed from and what consumes it, ending in the one `Dependencies` map of precedents and dependents every Details tab now shows - **shape and precision** (`Origin Length`, `Development Length`, `Decimal Places`), and **remaining settings**. A page omits a section it has no row for rather than showing it empty. `Name` is the first row and the output identity row is the second - `Dataset Type` in the Dataset Viewer and `Output Type` on every method page, including DFM, which no longer labels it `Output Vector`. The reserving-class row is labelled `Segment` on every Details tab.

    `.arDetailsSection` is the only wrapper a Details page uses, whether it groups rows visually or shows and hides them together; there is no separate invisible group. One light `--ar-details-section-divider` rule separates a section from the one before it, with `--ar-details-section-gap` on each side. That rule is a `+` selector, which cannot know that the sections above it are all hidden or emptied, so a page must call `syncDetailsSections` after `applyHostFixedDetailsFields` and after any runtime toggle of a whole section - `syncDetailsLabelWidth` already does the first. Every control in the shape-and-precision section shares `--ar-details-short-field-width` through `.arDetailsShortField` on the field cell, so a page must not restate that width; a field that needs a different width, such as `Number Format`, belongs in another section.

    `ui/shared/tabs/details/details_dependencies.js` and its stylesheet are the sole owner of that section's dependency surface: the `Dependencies` map (drawn by `details_dependency_map.js`, which only `details_dependencies.js` imports), the formula field, the hover tooltip, the click that opens a related dataset or method, and the map's button that opens the full Dependency Graph. A page supplies only its element ids, its identity, and - on a method page - the method type its output box is labelled with, through `createDetailsDependenciesController` (the Dataset Viewer's Data tab uses `createDetailsDependenciesView` with the same options), and must not restate the look or re-implement the map. The graph is keyed by **dataset name**, so a method page reads it for the dataset it publishes - `details tab.output dataset`, falling back to the method name - never for the method itself, and re-reads it after a save, which rewrites both sides. The formula field names its sources as quoted plain text; it is deliberately not a set of links, because the `Dependencies` map directly below shows the same sources as boxes and owns opening them, and it always carries the read-only fill because a calculated dataset's formula belongs to its Dataset Type in Project Settings and cannot be edited from a dataset window.

    `formatDetailsFormulaText` in that same module is the one way a formula is displayed anywhere in the app. The Dataset Viewer Formula field, the Project Settings Dataset Types table, and the Project Instance dataset table all render through it, so one formula never reads three ways. It quotes every name it recognises, whether or not the stored text quoted it, and normalises operator spacing; the stored text is never rewritten, and Project Settings keeps the raw value on the cell so a copy or an edit round-trips what is on disk. Both forms are canonical on disk - `_extract_formula_components` takes quoted names when present and otherwise matches known dataset-type names - so a caller **must** pass the dataset-type names it knows. Without them a name holding `-` or `/`, such as `C 22 - CWOP DFM w/ Selected LDFs`, cannot be told from an expression; with nothing matched the formula is returned untouched rather than split, because a wrong split shows a formula that is not on disk.

    The reserving-class row is read-only on every Details tab and has no picker: the host fixes the segment. A picker field opens its list only from its own button; clicking or tabbing into the text box places a caret, and typing or `ArrowDown` may still filter or open a combobox list.

Dataset Viewer value editing allows only manual/input datasets and new manual drafts. Non-input or unresolved source kinds and a nonempty project Dataset Type formula keep the grid and links read-only while allowing display settings and notes to save. The shared Data tab owns source-based editing eligibility; Project Instance and Result Selection must not translate a derived source kind into the window-wide `readonly=1` flag. Explicit read-only and temporary windows block all save commands, including clean saves and keyboard saves. Derived values still refresh through propagation and owning method saves.

An eligible manual/input Dataset Viewer or method Save remains available while clean and triggers full downstream recalculation. Derived-dataset display saves skip propagation. Dirty state continues to govern unsaved-change prompts, not propagation eligibility. A DFM window shows unsaved changes only after a user edit has been compared with its last loaded or saved state and found different, and returns to clean when a later edit removes the difference (see `docs/ui/dfm.md`); no other window compares itself against a baseline.

Dataset Viewer Data exposes Copy, eligible manual/input Paste, and Copy All with muted shortcut hints, plus Clear data, which zeroes every editable cell of the displayed grid and is offered only while the grid is editable. Ctrl/Cmd+A selects and copies the displayed grid when the grid owns keyboard focus. Manual/input datasets keep the cell formula editor in a separate full-width panel above the table; the existing editing and read-only rules still apply.

The manual Data formula panel provides a compact formula field with Enter to apply and Escape to cancel edits. Plain numeric edits remain values, while `=` expressions use the canonical dataset-cell formula grammar and retain their formula links on save.

DSV and DFM share formula completion and an fx dialog for function selection, argument choices, and read-only result previews. Inserting a validated formula changes only the draft; the editor's normal Enter command applies it. Typing `[` offers dataset names in both editors. DSV's formula panel shows the top-left cell of the first selected range. A DSV grid and a DFM Ratios summary each open on a cell rather than on an instruction to pick one. A DSV grid opens on the first cell holding a formula, or on the grid's first cell when none does, and may still move onto a formula cell whose links arrive after the first paint. A DFM Ratios summary opens on the selected average cell of the first development column, or on that column's first row while nothing is selected, and follows the selection as a method's saved selections settle. Neither overrides a selection the reader has made. The [formula-bar guide](../ui/formula_bar.md) defines the supported dataset calls and scope defaults.

Dependency Graph card actions use the shared `dependency_graph_contract.js`
request/result messages. PI accepts them only from an owned graph frame and
uses that frame's pinned class. Review delegates to the existing review-status
action; table navigation selects the exact dataset instance and reports a
failed reveal without minimizing the graph. See [PI](../ui/project_instance.md).

Dependency Graph filters use the PI dataset table's shared searchable value menu.
The last Status, Category, Method Type, and matched-only choices are local-user
preferences restored on graph open, independent of PI table filters and project
data. Already-open graphs retain their own state.

Arcode notebook search uses the editing cell while in edit mode and all cell
source in command mode. Whole-notebook replacements participate in notebook
undo and normal dirty/save tracking. Python completion and signature help use
the notebook's own session; overflow popups must remain accessible outside cell
bounds. See [Arcode](../ui/arcode.md).

Help → User Guide opens the guide served by the current server's Gateway in the
system browser (a new tab in browser mode). The server profile owns its address;
the app never substitutes bundled documentation or opens the Server share.
Connection lookup and browser launch failures appear in the shell status bar.

DFM's in-window question-mark guide is presentation-only state, retained across
its internal tab changes and cleared when the window reloads. Guide controls
must not mutate method data, dirty state, save payloads, or audit history. See
[DFM](../ui/dfm.md) for in-page markers and single-tooltip hover behavior.

Shared Table Appearance fonts and colors are local-user preferences, never
method data. Specific section font properties override broader table settings;
resetting a section's font preserves its colors. See [shell](../ui/shell.md).

## Before Finishing
ArcBot prepares an unused read-only CLI thread when entering a chat. Task
commands and output remain in a collapsible work log; the final response
contains the result. Local Windows dictation inserts editable draft text and
never sends it automatically. ArcBot's project-read tool is restricted to the
active project's registered method loads and discovery reads. Project-wide
reads do not grant write access: edits still require the original method page
to be open and active and use its existing apply/save and dirty-state flow.
ArcBot account switching applies to new requests only and is refused while a
reply is running; credentials stay in each account's own folder.

1. State which behavior area changed, or state "no frontend behavior impact."
2. Update relevant MANUAL sections in `docs/ui/*.md` when behavior changes.
3. Run `python tools/docs_index_builder.py --write`.
4. Run `python tools/docs_index_builder.py --check`.
