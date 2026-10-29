# DSV and DFM formula bars

## Formula assistance
<!-- MANUAL:BEGIN -->
Both editors offer function-name completion, argument names with the active argument highlighted, and choices for datasets, projects, reserving-class paths, and Boolean arguments. Typing `[` opens the dataset-name list; choosing a name inserts `[Dataset][` ready for coordinates. Tab or Enter accepts a suggestion, arrows move through it, and Escape closes it. Dataset choices use the project and RC specified by the call.

Path offers the current RC shortcut; enter other RC paths as quoted text. Formula dataset lists and value reads require the Gateway. Other legacy dataset-router reads (including index-signature polling) retain their existing SMB paths and should be migrated separately.

Click **fx** to open Insert Formula inside the current window. The left pane lists functions in groups (Arco Data, Logic, Math, Array) under a search box; arrow keys in the search box move through the matches and Enter jumps to the first field. The right pane shows a form built from the selected function, the formula text, and a live preview.

- **Arco dataset calls** show Project, Reserving Class, and the dataset as dropdowns that also accept typing. The dataset list holds only triangles or only vectors, to match the function, and is read for the project and RC chosen above it. An empty Project or Reserving Class shows the current one in muted text and writes an empty argument. Picking the current one keeps it empty. Typing only filters a list; the text counts once it is picked, entered with Enter, or the field is left. Period lengths are a fixed Annual / Half-Year / Quarterly / Monthly list. TRUE/FALSE arguments are checkboxes. The ByTypeName and SuppressWarnings compatibility slots are not shown. Text is quoted for the user, and only arguments that differ from their defaults are written.
- **Built-in functions** take one expression field per argument, with `[` dataset completion. List functions such as SUM add a field as the last one is filled.
- **The formula text** stays editable and two-way: while it is a single call to a listed function, the form follows it. Anything larger dims the form, and choosing a function starts over. Opening on a cell whose formula is one listed call fills the form from it; any other formula opens as it stands.
- **Preview** runs about 300 ms after the last change once every required field is filled, shows up to 50 rows and 20 columns, and reports the full dimensions or the error in the footer. Insert is enabled only for a successful preview of the current text; it writes the formula bar draft, and Enter in the bar applies it. Cancel, Escape, or the close button keeps the original draft.

DSV's persistent formula panel shows the first cell (top left) of the first selected range, including a multi-cell selection. Read-only cells retain their existing restrictions.

DFM Ratios' formula bar is likewise a fixed, always-visible panel docked directly above the average-formula summary table rather than a floating overlay: it does not anchor to, follow, or drag away from the cell it edits. It takes the width of the visible area rather than the width of the tables, which are usually wider, and holds the left edge of that area, so its row label and its workbook button stay where the window puts them no matter how far the tables are scrolled sideways. Selecting a User Entry cell shows its editable formula there; selecting another summary row's cell (an average or benchmark row) shows that cell's unrounded value read-only, written after an `=` so the bar reads as an equation, and selectable and copyable but not editable; selecting anything else leaves the bar in an idle note.
<!-- MANUAL:END -->

## Functions and dataset calls
<!-- MANUAL:BEGIN -->
`TAKE(array, rows, [columns])` selects leading or trailing rows/columns; negative counts select from the end, oversized counts clamp to the available size, and zero is an error. `INDEX(array, row_num, [column_num])` uses one-based positions; zero selects an entire row or column. `TRANSPOSE(array)` swaps axes. Array constants use commas between columns and semicolons between rows. These functions compose with the existing numeric functions and dataset/workbook references.

The numeric Excel add-in dataset functions are available with the same positional argument order: `ArcoTri`, `ArcoTriDiag`, `ArcoTriCell`, `ArcoTriOrigin`, `ArcoVec`, and `ArcoVecCell`. Their signatures and defaults are generated from `excel-addin/src_vba/ArcRhoFunctions.bas`. Arguments are quoted text, numbers, TRUE/FALSE, or omitted slots; calculations can wrap the calls. Blank/omitted Path and blank/omitted/Default ProjectName use the editor's current RC and project. Explicit project and RC values can name other scopes. As in the add-in, ByTypeName and SuppressWarnings are accepted compatibility slots.

Examples:

```text
=TAKE(ArcoTri(,"Paid Claims"),-3,2)
=TRANSPOSE(ArcoVec("","Selected Ultimate"))
=INDEX(ArcoTri("Other RC","Paid Claims",TRUE,FALSE,FALSE,"Other Project"),2,1)
```

DSV spills into its eligible target cells and saves the formula link. DFM accepts one row of positive numeric results that fits the available User Entry cells; use TAKE/INDEX/TRANSPOSE to select that shape. DFM saves each spilled cell as INDEX of the original expression, preserving its dataset references for recalculation. Existing DFM row references and decimal half-up ROUND behavior remain supported.

Local dataset calls participate in the existing segment dependency graph. Other-project/RC calls are evaluated on entry, preview, and explicit refresh (and when the owning DFM recalculates); a save in another scope does not automatically push refreshes across scopes. Cross-scope sources are not recorded as same-named local graph nodes. Saved values remain snapshots until refreshed.
<!-- MANUAL:END -->

## Implementation and checks
<!-- MANUAL:BEGIN -->
`arcrho_api.dataset_link_contract` owns numeric grammar and evaluation, with `dataset_formula_arrays` owning array selection. `generate_dataset_formula_metadata.py` derives browser metadata and the Python add-in catalog; browser/server parity tests cover the evaluator. `dataset_formula_values.js` shares asynchronous reads and preview evaluation; formula completion and the dialog live in `ui/shared/components/formula_bar/`.

The existing `/dataset/internal_links/resolve` route batches both bracket references and add-in calls. It requires Gateway transport on clients. `arcrho_formula_service` delegates dataset shape conversion to the same hosted dataset reader used by Excel, caches repeated reads within a request, and supplies numeric matrices. Missing sources or invalid indices fail visibly without applying a partial preview.

Node tests that load browser `/ui/` module paths use `--import ./frontend/tests/ui_module_loader.mjs`. The helper lifecycle tests check preview, cancellation, stale responses, insertion, and focus; browser testing is still needed for visual layout.
<!-- MANUAL:END -->
