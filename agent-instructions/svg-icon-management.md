# SVG Icon Management

Read this before adding, moving, replacing, or embedding any SVG icon, cursor, logo, or glyph in this repository.

## 1. Store Artwork As Files (MUST)

Every drawing that a designer could plausibly revise lives in its own `.svg` file. Do not paste path data into a JavaScript string, a CSS `background-image`, or an HTML `<svg>` literal.

A file can be opened in a design tool, diffed as a shape, previewed at any size, and replaced without a code review of its geometry. Path data pasted into a module is invisible until it runs, invites a second module to copy it, and turns an artwork change into a noisy code diff.

Two narrow exceptions, and no others:

1. **Structural marks that are not artwork** — the two crossing lines of a close button, a focus ring, a caret. There is nothing for a designer to revise. `createTabCloseIcon` in `frontend/ui/shell/tab_strip.js` is the reference example.
2. **Geometry computed from runtime state** — a sparkline, a gauge arc, a shape whose coordinates come from data.

`frontend/ui/shell/home_card_icons.js` embeds Home launch-card path data in a JavaScript module. It predates this rule and is the known exception; do not copy the pattern. A new Home card's artwork goes in `frontend/ui/shell/home-card-icons/` instead (the Dashboards card is the first), and an older card's drawing moves there when it is next revised.

## 2. Where A File Goes (MUST)

Classify by how many independent consumers the drawing has **today**, not by how many you predict:

1. **One page or window** → that page's own folder. Example: `frontend/ui/method_pages/dfm/dfm_handwriting_cursor.svg`, referenced only by `dfm.css`.
2. **One feature area, several places inside it** → that feature's own icon subfolder. Examples: `frontend/ui/arcode/shared/launch-card-icons/` (Arcode only) and `frontend/ui/shell/tab-type-icons/` (the shell's tab strip).
3. **Two or more unrelated features** → `frontend/ui/shared/icons/`, or a named package beneath it. Examples: `frontend/ui/shared/icons/chevron-right.svg` (main shell and Arcode) and `frontend/ui/shared/file-icons/` (File Explorer and Arcode).

**Promote on the second consumer, never before.** Moving a file up when a real second caller appears costs a move plus a path update. Guessing early costs a shared folder nobody can prune, because no one can prove a drawing is still unused. A shared icon folder is only useful while it stays small enough to scan.

Application branding — installer, window, and component icons — stays in `assets/icons/` and `frontend/icons/` and is outside this classification.

## 3. How To Reference One

Pick by what the icon must do, not by habit:

- **Monochrome icon that must follow theme or state colors** → apply it as a CSS mask over `background-color: currentColor`. The element carries a data attribute; the stylesheet maps that attribute to the file. `frontend/ui/shell/tab-type-icons/tab_type_icons.css` is the reference implementation. One file then serves resting, hover, active, light, dark, and high contrast with no recolored copy.
- **Multicolor icon** → an `<img>` element or a `background-image`. A mask keeps only alpha and would flatten it. `frontend/ui/shared/file-icons/` works this way.
- **A single shape reused inside one document** → an SVG `<symbol>` sprite file addressed with `<use href="file.svg#id">`. Confirmed working in this app's Electron build on 2026-08-21 for `frontend/ui/shared/icons/chevron-right.svg`; do not "fix" it on the theory that cross-file references fail in Chromium.

Rules that apply to all three:

- Write `stroke="currentColor"` or `fill="currentColor"` in the file. Never a literal color in a UI icon, so the host owns color.
- Keep a stylesheet in the same folder as the artwork it points at, and keep its `url()` references relative to the stylesheet. Relative references resolve both from the app server and from a design page opened directly off disk; absolute `/ui/...` paths break the second case.
- Carry the repository's `?v=YYYYMMDDx` cache-busting stamp on every referenced path, and bump it with the artwork.
- Never let a failed reference render as a filled rectangle. A mask stylesheet must define a fallback drawing on the base class so an unmapped value degrades to a generic glyph rather than a solid block.

## 4. Drawing Rules For A Set

When a group of icons is used side by side, they must read as one set. Follow `frontend/ui/shell/tab-type-icons/README.md`, which records the concrete numbers for that set, and apply the same discipline to any new set:

- One canvas size for the whole set, chosen for the size it will actually render at. Do not reuse a 24-unit drawing for a 14px slot; detail that reads at one size turns to mud at the other.
- One stroke width, one cap style, one join style across the set.
- A consistent inset from the canvas edge so no stroke is clipped, and every drawing centered on the canvas center.
- A detail budget of roughly five elements. Small icons are read by silhouette, not by inspection.
- Distinct silhouettes between members. Two icons that differ only by a small internal mark cannot be told apart at a glance, which is the whole job.

Measure the finished set rather than trusting the eye: bounding box, center, and edge clearance per icon, so no member is visibly heavier or lighter than its neighbours.

## 5. Reviewing And Verifying

- **Preview before claiming a set looks right.** Run `python tools/svg_icon_preview.py` (or double-click `tools/preview_svg_icons.bat`) to open every SVG in the repository in one browser gallery with size, color, and background controls. Pass a folder to scope it. It serves the gallery live until Ctrl+C, so the page's Refresh button picks up edits; `--static` writes a one-off snapshot into git-ignored `tmp_data/` instead.
- **A set with a design decision behind it gets a review page** under `frontend/docs/ui/`, rendering it in its real host at its real size. `frontend/docs/ui/tab_type_icon_preview.html` is the example.
- **Validate before reporting done.** Every file must parse as XML, declare a `viewBox`, and keep its ink inside that box.
- **Do not claim an icon renders without seeing it**, in the app or in the gallery. State plainly when verification was by measurement only.

## 6. Naming

- Lowercase, and match the key the code looks up. The tab icons are named for the tab type they serve, so the mapping needs no translation table.
- Hyphenated folder names for icon packages (`file-icons`, `tab-type-icons`, `launch-card-icons`); the file inside keeps whatever separator its lookup key uses.
- Every icon package carries a `README.md` stating what the set is for, the drawing rules it follows, and how to add a member.
