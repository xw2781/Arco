import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [html, main, css] = await Promise.all([
  readFile(
    new URL("../ui/method_pages/berquist_sherman/berquist_sherman.html", import.meta.url),
    "utf8",
  ),
  readFile(
    new URL("../ui/method_pages/berquist_sherman/berquist_sherman_main.js", import.meta.url),
    "utf8",
  ),
  readFile(
    new URL("../ui/method_pages/berquist_sherman/berquist_sherman.css", import.meta.url),
    "utf8",
  ),
]);

test("every B&S source picker uses a calculation role key", () => {
  // The sources are chosen on the Data Flow map from these definitions.
  const definitions = main.match(/const ROLE_DEFINITIONS = Object\.freeze\(\{[\s\S]*?\n\}\);/u)?.[0] || "";
  const roles = Array.from(
    definitions.matchAll(/key: "([^"]+)"/gu),
    (match) => match[1],
  );
  // Both variants list their sources in the ResQ Details tab order.
  assert.deepEqual(roles, [
    "paid_claims",
    "closed_claim_numbers",
    "ultimate_claim_numbers",
    "paid_claims",
    "incurred_claims",
    "reported_claim_numbers",
    "closed_claim_numbers",
  ]);
  assert.doesNotMatch(definitions, /key: "(?:sr|cra)_/u);
});

test("B&S rejects source format and period mismatches", () => {
  assert.match(main, /norm\(payloadFormat\) !== norm\(role\.format\)/u);
  assert.match(
    main,
    /const payload = state\.sourcePayloads\[role\.key\][\s\S]{0,300}Array\.isArray\(originLabels\)\s*&& originLabels\.length\s*&& \(/u,
  );
  assert.match(main, /uses different origin periods/u);
  assert.match(main, /uses different development periods/u);
  assert.match(main, /createDatasetHeadersService/u);
  assert.doesNotMatch(main, /`\$\{\(index \+ 1\) \* ANNUAL_PERIOD_LENGTH\}m`/u);
});

test("B&S applies the annual triangle mask to disk loads and live previews", () => {
  assert.match(main, /normalizeAnnualTriangle\(payload\?\.values, payload\?\.mask\)/u);
  assert.match(main, /normalizeAnnualTriangle\(matrixValues, message\.mask\)/u);
  assert.doesNotMatch(main, /normalizeMaskedMatrix/u);
});

test("the unavailable lower-right area is masked instead of printed as zero", () => {
  // `formatDatasetNumberValue` coerces with `Number(...)`, so a missing cell
  // must never reach it: the page resolves a blank before formatting.
  assert.match(
    main,
    /function formatCellValue\(value, format\) \{\s*\n\s*const number = numberOrNull\(value\);\s*\n\s*if \(number === null\) return "";/u,
  );
  // Every triangle grid stops at its own row length and masks the rest.
  const masked = Array.from(main.matchAll(/rowElement\.appendChild\(maskedCell\([^)]*\)\)/gu));
  assert.equal(masked.length, 3, "the three triangle grids must all mask");
  assert.match(main, /if \(devIndex >= populatedCount\) \{\s*\n\s*rowElement\.appendChild\(maskedCell\(/u);
  assert.match(main, /cell\.className = "bsMaskedCell"/u);
  assert.doesNotMatch(main, /bsAdjBlankCell/u);
  // A masked cell shows neither a fill nor a grid line.
  assert.match(
    css,
    /\.bsMethodTable td\.bsMaskedCell \{[^}]*border-right-color: transparent;[^}]*background: transparent;/u,
  );
});

test("the page opens on one Server-hosted read", () => {
  // The method JSON and the output sidecar arrive together, so a Client PC pays
  // one workspace visit instead of one per file. Reading the method through the
  // host API could never reach the Gateway at all.
  assert.match(main, /fetch\("\/berquist-sherman\/load"/u);
  assert.match(main, /method_type: contract\.methodType/u);
  assert.doesNotMatch(main, /tryLoadExistingMethod/u);
  const openBody = main.slice(
    main.indexOf("async function openMethodPage()"),
    main.indexOf("function getPrecedentNames()"),
  );
  assert.doesNotMatch(openBody, /readJsonFile/u, "the page open must not read the method file directly");
  // The sidecar is applied before the method, so a saved Details number format
  // still wins over the output dataset's own.
  assert.match(openBody, /applySidecarPayload\(payload\?\.sidecar\)[\s\S]*applyMethodPayload\(payload\.method\)/u);
  // One place applies a sidecar, whether it came from the page open, an Audit
  // refresh, or the save response that already carries the saved one.
  assert.equal(
    Array.from(main.matchAll(/applySidecarPayload\(/gu)).length,
    4,
    "one definition and the three callers",
  );
  // The index and the page open are independent reads and must not serialize.
  assert.match(
    main,
    /await Promise\.all\(\[\s*\n\s*loadCachedRows\(\)[\s\S]{0,220}openMethodPage\(\),\s*\n\s*\]\)/u,
  );
});

test("B&S publishes and clears full-triangle dependency previews", () => {
  assert.match(main, /message\.matrixValues = cloneMatrix\(output\)/u);
  assert.match(main, /message\.mask = output\.map/u);
  assert.match(main, /scheduleOutputDependencyPreview\("upstream-preview", true\)/u);
  assert.match(main, /else clearOutputDependencyPreview\("clean"\)/u);
  assert.match(main, /type:\s*"arcrho:dependency-source-cleared"/u);
});

test("B&S keeps previews reproducible across invalid, clear, picker, and save paths", () => {
  assert.match(
    main,
    /if \(lastOutputPreviewMessage\) clearOutputDependencyPreview\("invalid"\)/u,
  );
  assert.match(main, /isDirty \|\| activeDependencyPreviews\.size > 0/u);
  assert.match(
    main,
    /blockSaveForActiveSourcePreviews\(\)[\s\S]+await refreshSourceRoles\(\);[\s\S]+blockSaveForActiveSourcePreviews\(\)/u,
  );
  assert.match(main, /state\.sourceNames\[role\.key\] = priorName/u);
  assert.match(main, /input\?\.addEventListener\("input"/u);
});

test("result-affecting MVP selections remain editable and persisted", () => {
  const gridRows = main.slice(
    main.indexOf("const INFLATION_GRID_ROWS"),
    main.indexOf("const state = {"),
  );
  const estimators = Array.from(
    gridRows.matchAll(/method: "([a-z_]+)"/gu),
    (match) => match[1],
  );
  assert.deepEqual(estimators, [
    "case_column",
    "case_all",
    "paid_column",
    "paid_all",
    "user",
    "latest",
    "monotone",
    "loess",
    "user",
  ]);
  assert.match(main, /methodTab\.selected_adjustment = cloneMatrix/u);
  assert.match(main, /methodTab\.loess_span = state\.loessSpan/u);
  assert.match(main, /methodTab\.inflation_selection = state\.inflationSelection\.slice/u);
});

test("both variants follow the ResQ sub-tab order with in-grid selection UX", () => {
  const labels = Array.from(
    main.matchAll(/label: "([^"]+)",\s*\n?\s*caption:/gu),
    (match) => match[1],
  );
  assert.deepEqual(labels, [
    "Paid Claims",
    "Numbers Closed",
    "Proportion Settled",
    "Selected Numbers Closed",
    "Adjusted Paid Claims",
    "Reported",
    "Closed",
    "Open",
    "Paid Claims",
    "Incurred Claims",
    "Case Reserves",
    "Avg. Case Reserves",
    "Avg. Paid",
    "Avg. Selections",
    "Adj. Avg. Case Reserves",
    "Adj. Incurred",
  ]);
  // Each variant opens on the first ResQ sub-tab.
  assert.match(main, /currentView: VIEW_DEFINITIONS\[variant\]\[0\]\.key/u);
  // Select Leading Diagonal is an item of the shared cell context menu.
  assert.match(html, /data-action="select_leading_diagonal"[^>]*>Select Leading Diagonal</u);
  assert.match(main, /if \(action === "select_leading_diagonal"\) selectLeadingDiagonal\(\);/u);
  assert.match(main, /bsPropSelectedInput/u);
  assert.match(main, /state\.selectedProportionIsDefault\[devIndex\] = false/u);
  assert.match(main, /Paid Claims Adjusted to Constant Proportions Settled/u);
});

test("CRA Avg. Selections stacks two ResQ selection grids in the Method frame", () => {
  assert.match(main, /secondaryCaption: "Current Average Case Reserves:"/u);
  assert.match(html, /<div class="bsGridPane" id="bsSecondaryPane" hidden>/u);
  assert.match(html, /bsSecondaryHead/u);
  assert.match(html, /bsSecondaryBody/u);
  // The single Loess Span control moves to the caption that owns the estimator.
  assert.match(main, /loessCaption\.appendChild\(els\.loessSpanField\)/u);
  assert.match(main, /state\.currentView === "avgSelections" \? els\.secondaryCaption : null/u);
  assert.doesNotMatch(html, /bsSelectionSummary/u);
  assert.doesNotMatch(css, /bsSelectionSummary/u);
});

test("CRA selection grids support per-column, whole-row, and user-value edits", () => {
  assert.match(main, /dataset\.selectMethod = row\.method/u);
  assert.match(main, /dataset\.selectDev = String\(devIndex\)/u);
  assert.match(main, /if \(devIndex === null\) \{\s*\n\s*for \(let index = 0/u);
  assert.match(main, /selection\[devIndex\] = "user"/u);
  // The User Value row follows the Result Selection entry UX: the cell is a
  // spreadsheet cell, not a permanent input. A click activates it, typing or
  // Enter opens an in-cell editor, Escape abandons it, Delete clears it, and a
  // cleared column falls back to the grid's default estimator.
  assert.doesNotMatch(main, /input\.dataset\.selectScope/u);
  assert.match(main, /const USER_CELL_EDIT_START_KEYS = \/\^\[0-9\.\\-\+='"\[\]\$\/u;/u);
  assert.match(main, /event\.key === "Enter" \|\| event\.key === "F2"/u);
  assert.match(main, /event\.key === "Delete" \|\| event\.key === "Backspace"/u);
  assert.match(main, /if \(selection\[devIndex\] === "user"\) selection\[devIndex\] = config\.defaultMethod;/u);
  // The active cell is the anchor of the shared grid selection, so it wears the
  // shared dashed outline through the selection controller, not its own class.
  assert.match(main, /function setActiveUserCell\([\s\S]*?cellSelection\.selectCell\(cell\);/u);
  assert.doesNotMatch(main, /classList\.add\("arSpreadsheetSelectionAnchor"\)/u);
  assert.match(main, /document\.addEventListener\("paste", handleUserCellPaste\)/u);
  // A typed figure reads red and bold, an Excel-linked one green, and a link
  // the workbook refused red, as on the RS and DFM grids.
  assert.match(css, /\.bsMethodTable td\.bsSelUserCell \{[^}]*color: #dc2626;[^}]*font-weight: 700;/u);
  assert.match(css, /\.bsMethodTable td\.bsSelUserCell\.bsSelExcelLinked \{[^}]*color: #166534;/u);
  assert.match(css, /\.bsMethodTable td\.bsSelUserCell\.bsSelExcelLinkError \{/u);
  // Excel references and formulas commit through the same entry path, and the
  // Links tab lists, refreshes, and breaks them.
  assert.match(main, /expandUserValueRangeEntry\(raw, devIndex, matrixDevelopmentCount\(\)\)/u);
  assert.match(main, /evaluateUserValueFormula\(entry\.input, values\)/u);
  assert.match(main, /createBerquistShermanLinksTab\(\{/u);
  assert.match(main, /onRefresh: refreshUserValueExcelLinks,/u);
  assert.match(main, /onBreak: breakUserValueExcelLinks,/u);
  assert.match(main, /void checkUserValueExcelLinkFreshness\(\);/u);
  assert.match(html, /<section class="bsPage" id="bsLinksPage" data-page="links" role="tabpanel">/u);
  assert.match(html, /id="bsLinksMount"/u);
  assert.match(css, /\.bsMethodTable td\.bsSelUserCell \{[^}]*background: var\(--bs-selected-band\);/u);
});

test("SR adjusted paid grid supports per-cell, per-origin, and all-origin selection", () => {
  assert.match(main, /dataset\.adjustMethod = gridRow\.method/u);
  assert.match(main, /dataset\.adjustDev = String\(devIndex\)/u);
  assert.match(main, /applyAdjustmentSelection\(/u);
  assert.match(main, /event\.ctrlKey \|\| event\.metaKey/u);
  assert.match(main, /state\.selectedAdjustment\[originIndex\]\[devIndex\] = method/u);
  assert.match(main, /state\.loessSpan = normalizeLoessSpan\(method\.loess_span\)/u);
  assert.match(html, /bsLoessSpanInput/u);
  assert.match(html, /tabbedPageTabBar/u);
});

test("input views keep their dataset instance's number format", () => {
  // One canonical formatter, and the resolver routes a source view to its own
  // dataset instance while everything calculated uses the Details format.
  assert.match(main, /from "\/ui\/shared\/dataset\/dataset_number_format\.js"/u);
  assert.doesNotMatch(main, /toLocaleString\(undefined, \{\s*\n\s*maximumFractionDigits/u);
  assert.match(
    main,
    /function viewNumberFormat\(viewKey = state\.currentView\) \{[\s\S]*?SOURCE_VIEW_ROLES\[viewKey\][\s\S]*?roleNumberFormat\(roleKey\) : derivedNumberFormat\(\)/u,
  );
  assert.match(main, /roleNumberFormat\("ultimate_claim_numbers"\)/u);
  // Every source role is recorded, and the record round-trips through the
  // method JSON rather than the output sidecar alone.
  assert.match(main, /methodTab\.number_formats = buildNumberFormatsRecord\(\)/u);
  assert.match(main, /applyNumberFormatsRecord\(method\.number_formats\)/u);
});

test("the Details format governs the calculated triangles and syncs silently", () => {
  assert.match(html, /id="bsNumberFormatInput"/u);
  assert.match(html, /id="bsDecimalPlacesInput"/u);
  // Number Format is the shared caret field the Dataset Viewer uses, so the
  // canonical preset list is reached through that component rather than a
  // page-local menu.
  assert.match(html, /class="arNumberFormatField"/u);
  assert.match(html, /class="arNumberFormatToggle"/u);
  assert.match(html, /class="datasetDropdown arNumberFormatMenu"/u);
  assert.match(main, /wireNumberFormatField\(\{[\s\S]*?menu: els\.numberFormatMenu/u);
  assert.doesNotMatch(main, /DATASET_NUMBER_FORMAT_PRESETS/u);
  // Editing the Details pair is a real edit; a source restyle is not.
  assert.match(main, /function applyDerivedNumberFormat\([\s\S]*?markDirty\(\);/u);
  assert.match(main, /derivedNumberFormat: derivedNumberFormat\(\)/u);
  assert.doesNotMatch(main, /sourceNumberFormats:[\s\S]{0,40}configSnapshot/u);
  // The silent rewrite preserves every other saved field, including the
  // method's last-modified stamp and the output's review status.
  const rewriteStart = main.indexOf("async function rewriteRecordedNumberFormats()");
  assert.ok(rewriteStart >= 0, "rewriteRecordedNumberFormats not found");
  // The file is checked out with CRLF, so the closing brace has to be matched
  // without assuming a bare LF; a missed match silently widens the slice to the
  // rest of the file and turns every `doesNotMatch` below into a pass-through.
  const rewriteEnd = /\r?\n\}\r?\n/u.exec(main.slice(rewriteStart));
  assert.ok(rewriteEnd, "rewriteRecordedNumberFormats has no closing brace");
  const rewriteBody = main
    .slice(rewriteStart, rewriteStart + rewriteEnd.index)
    .replace(/^\s*\/\/.*$/gmu, "");
  assert.match(
    rewriteBody,
    /method: \{ \.\.\.data, method_tab: \{ \.\.\.methodTab, number_formats: record \} \}/u,
  );
  // Carrying a sidecar would publish the output, bump its review status, and
  // queue a dependent walk for what is only a display-state catch-up.
  for (const forbidden of ["markDirty", "last_modified", "sidecar:", "status"]) {
    assert.doesNotMatch(rewriteBody, new RegExp(forbidden, "u"), forbidden);
  }
});

test("B&S frames its pages on the shared tabbed-page gutter like DFM", () => {
  // The shell must lay the tab strip, page frame, and save bar out as flex rows
  // so the frame cannot overflow past the bottom of the window.
  assert.match(css, /\.bsTabbed \{[^}]*flex-direction: column;/u);
  assert.match(css, /\.bsPageHost \{[^}]*flex: 1 1 auto;/u);
  assert.doesNotMatch(css, /\.bsPageHost \{[^}]*height: 100%/u);
  // The frame, the strip, and the save bar share one gutter, and every Method
  // row shares one inset derived from it.
  assert.match(css, /\.bsPageHost \{[^}]*margin: 0 var\(--tabbed-page-gutter, 8px\);/u);
  assert.match(css, /\.bsSaveBar \{[^}]*padding: 6px var\(--tabbed-page-gutter, 8px\) 4px;/u);
  assert.match(css, /#bsMethodPage \{[^}]*--bs-method-inset: var\(--tabbed-page-gutter, 8px\);/u);
  // The nested strip inherits the gutter instead of redeclaring it.
  assert.doesNotMatch(css, /\.bsMethodTabBar \{[^}]*--tabbed-page-gutter/u);
});

test("the method label column has one alignment source", () => {
  assert.match(css, /\.bsMethodTable td:first-child \{[^}]*text-align: center;/u);
  // The adjusted grid's origin and estimator rows must not re-align the column.
  assert.doesNotMatch(css, /\.bsMethodTable tr\.bsAdjYearRow td \{[^}]*text-align/u);
  assert.doesNotMatch(css, /\.bsMethodTable td\.bsAdjRowLabel \{[^}]*text-align/u);
});

test("row hover never repaints a meaningful cell fill", () => {
  const rule = css.match(/\.bsMethodTable tbody tr[^{]*:hover[^{]*\{[^}]*--bs-row-hover[^}]*\}/u);
  assert.ok(rule, "row-hover rule not found");
  const excluded = new Set(
    Array.from(rule[0].matchAll(/:not\(:is\(([^)]*)\)\)/gu), (match) =>
      match[1].split(",").map((entry) => entry.trim())).flat(),
  );
  for (const selector of [
    ".bsAdjYearRow",
    ".bsPropSelectedRow",
    ".bsPropSpacerRow",
    ".bsSelGroupRow",
    ".bsAdjSelectedSource",
    ".bsPropSelectedSource",
    ".bsSelSelectedSource",
    ".bsSelUserCell",
    ".bsMaskedCell",
  ]) {
    assert.ok(excluded.has(selector), `row hover must leave ${selector} alone`);
  }
});

test("the Details form matches the other method pages", () => {
  // Section spacing comes from the shared Details primitive alone, so the panels
  // are not padded twice the way BF, CC, and RS avoid.
  assert.match(css, /\.bsDetailsStack \{[^}]*gap: 0;/u);
  assert.match(css, /\.bsPanelBody \{\s*\n\s*padding: 0;\s*\n\}/u);
  // The picker sits inside its field instead of beside it.
  assert.match(css, /\.bsFieldControl\.withPicker \{\s*\n\s*position: relative;\s*\n\}/u);
  assert.doesNotMatch(css, /\.bsFieldControl\.withPicker \{[^}]*grid-template-columns/u);
  assert.match(css, /\.bsFieldControl\.withPicker \.bsInput \{[^}]*padding-right: 36px;/u);
  assert.match(css, /\.bsIconButton \{[^}]*position: absolute;[^}]*width: 22px;[^}]*height: 22px;/u);
  // An inline wrap cannot take a width at all, so it stays a block-level box; the
  // 70px now comes from `.arDetailsShortField` on the cell, not from this page.
  assert.match(css, /\.bsDecimalPlacesWrap \{[^}]*display: inline-flex;[^}]*width: 100%;/u);
  assert.doesNotMatch(css, /\.bsDecimalPlacesWrap \{[^}]*width: 70px;/u);
  // The shared stepper owns the control geometry; only the token is set here.
  assert.match(css, /\.bsDecimalPlacesWrap \{[^}]*--topbar-control-height: 30px;/u);
  assert.doesNotMatch(css, /\.bsDecimalPlacesInput \{[^}]*(?:padding|text-align|height)/u);
});

test("the nested calculation strip encloses its client area like ResQ", () => {
  // The message row and every captioned grid pane live inside the nested
  // strip's own frame, not directly on the Method page.
  assert.match(
    html,
    /<div class="bsMethodFrame">[\s\S]*bsMethodMessage[\s\S]*bsMethodCaption[\s\S]*bsTableWrap[\s\S]*bsSecondaryCaption[\s\S]*bsTableWrap[\s\S]*<\/div>\s*<\/section>/u,
  );
  // The frame takes the strip's bottom rule as its top edge and shares the
  // strip's gutter, so the active calculation tab sits on a closed box.
  assert.match(css, /\.bsMethodFrame \{[^}]*margin: 0 var\(--bs-method-inset\) var\(--bs-method-inset\);/u);
  assert.match(css, /\.bsMethodFrame \{[^}]*border-top: 0;/u);
  // Rows inside the frame are inset by the frame's own padding, not the gutter.
  for (const rule of ["bsMethodCaption", "bsMethodMessage", "bsTableWrap"]) {
    assert.match(css, new RegExp(String.raw`\.${rule} \{[^}]*var\(--bs-method-pad\)`, "u"), rule);
  }
  // Two stacked grids share the client area evenly, as the ResQ tab does.
  assert.match(css, /\.bsGridPane \{[^}]*flex: 1 1 0;/u);
});

test("B&S never writes a persisted project file from the renderer", () => {
  // The method JSON and output CSV go through `/berquist-sherman/save`, so the
  // on-disk text comes from the app server's canonical writer; a host-API
  // write would bypass it and could not even reproduce a `1.0`.
  assert.match(main, /fetch\("\/berquist-sherman\/save"/u);
  assert.doesNotMatch(main, /saveJsonFile|saveTextFile|readJsonFile/u);
  // That one Engine-hosted call carries the output sidecar too, so the save is
  // a single visit to the workspace rather than a share write followed by a
  // second save. A separate sidecar post would put the share back in the path.
  assert.doesNotMatch(main, /fetch\("\/dataset\/sidecar\/save"/u);
  assert.match(main, /requestMethodSave\(\{[\s\S]*?sidecar: sidecarBody,/u);
});

test("B&S reads its output sidecar only through the registered hosted routes", () => {
  // Both the save and the Audit tab used to fetch the sidecar on its own, which
  // reaches the workspace from the renderer's PC and opens the sidecar, the
  // project's dataset-type rows, the reserving-class index, and one more file
  // per graph edge — every one of them its own round trip off the server host.
  assert.doesNotMatch(main, /fetch\("\/dataset\/sidecar\/load"/u);
  // The Audit tab refreshes through the page-open read, which carries it.
  assert.match(
    main,
    /async function loadSidecar\(\)[\s\S]*?requestMethodAndSidecar\(details\.name\)[\s\S]*?applySidecarPayload\(payload\?\.sidecar\)/u,
  );
  // A save applies the sidecar it was just handed instead of loading it back.
  assert.match(
    main,
    /function applySavedOutputSidecar\(payload\)[\s\S]*?applySidecarPayload\(payload\)/u,
  );
  const saveStart = main.indexOf("async function runBerquistShermanSave(");
  assert.ok(saveStart >= 0, "runBerquistShermanSave not found");
  const saveEnd = /\r?\n\}\r?\n/u.exec(main.slice(saveStart));
  assert.ok(saveEnd, "runBerquistShermanSave has no closing brace");
  const saveBody = main.slice(saveStart, saveStart + saveEnd.index);
  assert.doesNotMatch(saveBody, /loadSidecar\(\)/u);
  // The in-place number-format sync reads and writes through the same routes.
  assert.match(
    main,
    /async function rewriteRecordedNumberFormats\(\) \{[\s\S]*?requestMethodAndSidecar\([\s\S]*?requestMethodSave\(/u,
  );
  // No renderer-side workspace path resolution is left to drift from the server's.
  assert.doesNotMatch(main, /\/workspace_paths|function joinPath|getMethodPath|getCsvPath/u);
});
