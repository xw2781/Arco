import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const moduleSource = await readFile(
  new URL("../ui/project_settings/project_settings_source_data.js", import.meta.url),
  "utf8",
);
const sourceDataModule = await import(
  new URL("../ui/project_settings/project_settings_source_data.js", import.meta.url)
);
const {
  getLastClosedMonthCanonical,
  getMonthPickerYearRange,
  formatSummaryNumber,
  getColumnRowSummary,
  getHistBarRangeLabels,
  getHistBarLabels,
  getDistributionAreaPath,
} = sourceDataModule;
const generalSettingsSource = await readFile(
  new URL("../ui/project_settings/project_settings_general_settings.js", import.meta.url),
  "utf8",
);
const projectSettingsJs = await readFile(
  new URL("../ui/project_settings/project_settings.js", import.meta.url),
  "utf8",
);
const projectSettingsHtml = await readFile(
  new URL("../ui/project_settings/project_settings.html", import.meta.url),
  "utf8",
);
const summaryCss = await readFile(
  new URL("../ui/project_settings/project_settings_summary.css", import.meta.url),
  "utf8",
);
const projectSettingsCss = await readFile(
  new URL("../ui/project_settings/project_settings.css", import.meta.url),
  "utf8",
);
const skeletonCss = await readFile(
  new URL("../ui/project_settings/project_settings_skeleton.css", import.meta.url),
  "utf8",
);
const summaryService = await readFile(
  new URL("../app_server/services/table_summary_service.py", import.meta.url),
  "utf8",
);
const summaryConfig = await readFile(
  new URL("../app_server/config.py", import.meta.url),
  "utf8",
);
const fieldMappingService = await readFile(
  new URL("../app_server/services/field_mapping_service.py", import.meta.url),
  "utf8",
);
const rulesService = await readFile(
  new URL("../app_server/services/data_processing_rules_service.py", import.meta.url),
  "utf8",
);
const summaryRouter = await readFile(
  new URL("../app_server/api/table_summary_router.py", import.meta.url),
  "utf8",
);
const sourceTableRouter = await readFile(
  new URL("../app_server/api/source_table_router.py", import.meta.url),
  "utf8",
);
const sourceTableService = await readFile(
  new URL("../app_server/services/source_table_service.py", import.meta.url),
  "utf8",
);
const sourceTableContract = await readFile(
  new URL("../../python-api/src/arcrho_api/source_table_contract.py", import.meta.url),
  "utf8",
);
const appServerConfig = await readFile(
  new URL("../app_server/config.py", import.meta.url),
  "utf8",
);

test("Source Data markup keeps the ids project_settings.js binds", () => {
  const boundIds = [
    "summaryTablePathInput",
    "summaryTablePathReloadBtn",
    "summaryOriginStartInput",
    "summaryOriginEndInput",
    "summaryDevelopmentEndInput",
  ];
  for (const id of boundIds) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
    assert.ok(projectSettingsJs.includes(id), `#${id} is no longer referenced by project_settings.js`);
  }

  // Rendering targets moved to the feature module and must stay resolvable there.
  for (const id of ["summaryStats", "summaryColumns"]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
    assert.ok(moduleSource.includes(id), `#${id} is not owned by the Source Data module`);
  }
});

test("Source Data panel exposes the quiet surface elements", () => {
  for (const id of [
    "summaryPathIdentity",
    "summaryPathDisplay",
    "summaryPathName",
    "summaryPathDir",
    "summaryOpenFolderBtn",
    "summaryInfoBtn",
    "summaryMessage",
    "summaryColumnFilter",
    "summaryColumnCount",
    "summaryColumnsHead",
    "summaryStatsCard",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
  }
  assert.match(projectSettingsHtml, /class="sd-resizer" data-col="name"/);
  assert.match(projectSettingsHtml, /class="sd-resizer" data-col="type"/);
  assert.ok(!projectSettingsHtml.includes("summaryStateDot"), "the removed state dot remains in markup");
  assert.ok(!moduleSource.includes("summaryStateDot"), "the removed state dot remains bound");
  assert.ok(!moduleSource.includes("setStateTone"), "the removed state-dot behavior remains");
  assert.ok(!summaryCss.includes(".sd-state-dot"), "the removed state-dot styles remain");
});

test("source identity keeps the quiet info trigger beside the file name and the folder in its panel", () => {
  const nameIndex = projectSettingsHtml.indexOf('id="summaryPathName"');
  const infoIndex = projectSettingsHtml.indexOf('id="summaryInfoBtn"');
  const actionsIndex = projectSettingsHtml.indexOf('class="sd-actions"');
  const statsIndex = projectSettingsHtml.indexOf('id="summaryStatsCard"');
  const directoryIndex = projectSettingsHtml.indexOf('id="summaryPathDir"');

  assert.ok(nameIndex >= 0 && infoIndex > nameIndex, "the info trigger is not after the file name");
  assert.ok(infoIndex < actionsIndex, "the info trigger remains in the standard action-button group");
  assert.ok(directoryIndex > statsIndex, "the source directory is not inside the floating info panel");
  assert.match(projectSettingsHtml, /class="sd-info-trigger" id="summaryInfoBtn"/);
  assert.match(projectSettingsHtml, /<circle cx="8" cy="8" r="6\.4"\/><path d="M8 4\.4v4\.6"\/>/);
  assert.match(summaryCss, /\.sd-info-trigger\s*\{[\s\S]*border:\s*0;[\s\S]*background:\s*transparent;/);
  // The card is sized by its own rows and never spills its content past the edge.
  assert.match(summaryCss, /\.sd-stats-card\s*\{[\s\S]*width:\s*max-content;[\s\S]*max-width:\s*min\(460px, calc\(100vw - 16px\)\)/);
  assert.match(summaryCss, /\.sd-stat-val\s*\{[\s\S]*overflow-wrap:\s*anywhere;/);
  // Card rows are plain text; the title is the only bold thing in the card.
  assert.match(summaryCss, /\.sd-stat-val\s*\{[\s\S]*font-weight:\s*400;/);
  // Clicking the identity now opens the Import Settings panel instead of an
  // inline path editor; the panel is the only place a source is edited.
  assert.match(moduleSource, /function beginPathEdit\(\)\s*\{[\s\S]*?openSourcePanel\(\)/);
  assert.ok(
    !/dom\.pathIdentity\.hidden = true/.test(moduleSource),
    "the retired inline path editor remains",
  );
  assert.match(moduleSource, /dom\.pathDirRow\.hidden = !parts\.dir/);
  // The folder row carries the one folder action, and it opens the OS explorer
  // through the desktop host bridge rather than copying the path.
  assert.match(moduleSource, /dom\.openFolderBtn\?\.addEventListener\("click"/);
  assert.match(moduleSource, /host\.showItemInFolder\(\{ path: value \}\)/);
  // The page is an iframe inside the shell, so the desktop bridge has to be
  // reached through the host window or the action reports "desktop app only".
  assert.match(projectSettingsJs, /getHostApi: \(\) => window\.ADAHost \|\| window\.parent\?\.ADAHost \|\| window\.top\?\.ADAHost/);
  assert.match(moduleSource, /window\.ADAHost \|\| window\.parent\?\.ADAHost \|\| window\.top\?\.ADAHost/);
  assert.ok(!moduleSource.includes("copyToClipboard"), "the retired copy-path action remains");
  assert.match(projectSettingsHtml, /id="summaryOpenFolderBtn"[^>]*aria-label="Open folder in file explorer"/);
});

test("the details card value column can be selected and copied", () => {
  // project_settings.css turns selection off for the whole body, so the value
  // column has to opt back in or the card's paths cannot be copied at all.
  assert.match(projectSettingsCss, /body\s*\{[\s\S]*?user-select:\s*none;/);
  assert.match(summaryCss, /\.sd-stat-val\s*\{[\s\S]*user-select:\s*text;/);
  assert.match(summaryCss, /\.sd-stat-val\s*\{[\s\S]*cursor:\s*text;/);
  // A selection dragged past the card edge must not dismiss the card.
  assert.match(moduleSource, /if \(event\.buttons\) return;/);
});

test("period band uses the requested labels and omits the normal origin span", () => {
  assert.match(projectSettingsHtml, /id="summaryOriginLabel">Origin Period:<\/span>/);
  assert.match(projectSettingsHtml, /id="summaryDevelopmentLabel">Development End:<\/span>/);
  assert.ok(!moduleSource.includes("`${months} months`"), "the derived month-span label remains");
  assert.match(moduleSource, /dom\.originSpanNote\.textContent = "";/);
  // Each label wraps together with its inputs; groups are separated by a column gap.
  assert.match(
    projectSettingsHtml,
    /class="sd-band-group">\s*<span class="sd-key" id="summaryOriginLabel"/,
  );
  assert.match(
    projectSettingsHtml,
    /class="sd-band-group">\s*<span class="sd-key" id="summaryDevelopmentLabel"/,
  );
  assert.match(summaryCss, /\.sd-band\s*\{[\s\S]*?column-gap:\s*24px;/);
  assert.match(summaryCss, /\.sd-band-group\s*\{[\s\S]*?display:\s*flex;/);
  assert.ok(!projectSettingsHtml.includes("sd-key-gap"), "the retired label margin class remains in markup");
  assert.ok(!summaryCss.includes(".sd-key-gap"), "the retired label margin styles remain");
  assert.match(summaryCss, /\.sd-note:empty\s*\{\s*display:\s*none;/);
});

test("date inputs use one shared month/year picker that stays open under the pointer", () => {
  for (const id of [
    "summaryOriginStartPickerBtn",
    "summaryOriginEndPickerBtn",
    "summaryDevelopmentEndPickerBtn",
    "summaryMonthPicker",
    "summaryMonthPickerYear",
    "summaryMonthPickerGrid",
    "summaryMonthPickerPrevYear",
    "summaryMonthPickerNextYear",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
  }
  for (const retiredId of [
    "summaryOriginStartUpBtn",
    "summaryOriginStartDownBtn",
    "summaryOriginEndUpBtn",
    "summaryOriginEndDownBtn",
    "summaryDevelopmentEndUpBtn",
    "summaryDevelopmentEndDownBtn",
  ]) {
    assert.ok(!projectSettingsHtml.includes(retiredId), `retired stepper #${retiredId} remains`);
    assert.ok(!projectSettingsJs.includes(retiredId), `coordinator still binds #${retiredId}`);
  }
  assert.ok(!projectSettingsHtml.includes("Current Month"), "the removed shortcut remains in the picker");
  assert.ok(!moduleSource.includes("summaryMonthPickerCurrent"), "the removed shortcut remains bound");
  assert.ok(!summaryCss.includes(".sd-month-picker-current"), "the removed shortcut styles remain");
  assert.match(moduleSource, /monthPickerYear -= 1/);
  assert.match(moduleSource, /monthPickerYear \+= 1/);
  assert.match(projectSettingsHtml, /id="summaryMonthPickerYear"[^>]*type="button"[^>]*aria-expanded="false"/);
  assert.match(moduleSource, /monthPickerYear\?\.addEventListener\("click", toggleMonthPickerYearView\)/);
  assert.match(moduleSource, /class="sd-month-picker-year-option"[^>]*data-year=/);
  assert.match(moduleSource, /monthPickerView = "months";/);
  assert.match(moduleSource, /monthPickerView === "years"/);
  assert.match(moduleSource, /classList\.toggle\("is-year-view-hidden", hidden\)/);
  assert.match(moduleSource, /setAttribute\("aria-hidden", "true"\)/);
  assert.match(summaryCss, /\.sd-month-picker-nav\.is-year-view-hidden\s*\{\s*visibility:\s*hidden;\s*pointer-events:\s*none;/);
  assert.match(moduleSource, /let monthPickerPointerInside = false;/);
  assert.match(moduleSource, /monthPicker\?\.addEventListener\("pointerenter", \(\) => \{\s*monthPickerPointerInside = true;/);
  assert.match(moduleSource, /monthPicker\?\.addEventListener\("pointerleave", \(\) => \{\s*monthPickerPointerInside = false;/);
  assert.match(moduleSource, /if \(monthPickerPointerInside && !force\) return;/);
  assert.match(moduleSource, /closeMonthPicker\(\{ restoreFocus: true, force: true \}\)/);
  assert.match(moduleSource, /placeFloating\(dom\.monthPicker, activeMonthInput\.getBoundingClientRect\(\), 6\)/);
  assert.doesNotMatch(moduleSource, /placeFloating\(dom\.monthPicker, button\.getBoundingClientRect\(\), 6\)/);
  assert.match(moduleSource, /input\.dispatchEvent\(new Event\("change"/);
  assert.match(generalSettingsSource, /input\.onchange = \(\) =>/);
  assert.match(generalSettingsSource, /commitPending = true/);
  assert.match(generalSettingsSource, /if \(commitPending\)/);
  assert.match(projectSettingsJs, /formatMonth: formatBoundaryYmDisplay/);
  assert.ok(!summaryCss.includes(".sd-month-lane"), "retired stepper lane styles remain");
  const pickerButtonRule = summaryCss.match(/\.sd-month-picker-btn\s*\{([\s\S]*?)\}/)?.[1] || "";
  assert.ok(!pickerButtonRule.includes("border-left"), "calendar icon retains its left divider");
  assert.match(summaryCss, /\.sd-month-picker-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(4, 1fr\)/);
  assert.match(moduleSource, /normalizeMonth\(input\.value\) \|\| getLastClosedMonthCanonical\(\)/);
  assert.equal(getLastClosedMonthCanonical(new Date(2026, 0, 15)), "202512");
  assert.equal(getLastClosedMonthCanonical(new Date(2026, 6, 29)), "202606");
  assert.deepEqual(getMonthPickerYearRange(2017), Array.from({ length: 51 }, (_value, index) => 1967 + index));
  assert.deepEqual(getMonthPickerYearRange(2026), Array.from({ length: 51 }, (_value, index) => 1976 + index));
  assert.deepEqual(getMonthPickerYearRange("invalid"), []);
});

test("the removed table markup and its styles are gone", () => {
  assert.ok(!projectSettingsHtml.includes("summary-derived-frame"), "old fieldset markup remains");
  assert.ok(!projectSettingsHtml.includes("summary-table-path"), "old path row markup remains");
  // "summaryColumnsTable" survives only as the shared width-preference key.
  assert.ok(!projectSettingsJs.includes('id="summaryColumnsTable"'), "old columns table is still rendered");
  assert.ok(
    !projectSettingsJs.includes('initTableColumnResizing("summaryColumnsTable"'),
    "old columns table still uses the <table> resizer",
  );
  assert.ok(!summaryCss.includes(".columns-table"), "old columns table styles remain");
  assert.ok(!summaryCss.includes(".stat-item"), "old stat tile styles remain");
});

test("project_settings.js delegates Source Data rendering to the feature module", () => {
  assert.match(projectSettingsJs, /createSourceDataFeature\(\{/);
  assert.match(projectSettingsJs, /sourceDataFeature\.renderSummary\(data\)/);
  assert.match(projectSettingsJs, /sourceDataFeature\.showNoPath\(/);
  assert.match(projectSettingsJs, /sourceDataFeature\.showError\(/);
  // The date role now rides on the summary payload, so the coordinator no
  // longer pushes a separately fetched copy of the mapping into the tab.
  assert.ok(
    !projectSettingsJs.includes("setDateRoles"),
    "the coordinator still pushes date roles into Source Data",
  );
  // The month parser is imported from its owner rather than reimplemented here.
  assert.match(projectSettingsJs, /normalizeMonth: normalizeBoundaryYmCanonical/);
  assert.match(projectSettingsJs, /formatMonth: formatBoundaryYmDisplay/);
  assert.match(
    projectSettingsJs,
    /import \{[\s\S]*normalizeBoundaryYmCanonical,\s*\} from "\/ui\/project_settings\/project_settings_general_settings\.js/,
  );
});

test("Source Data shows flowing placeholders while the table is copied or read", () => {
  // The working surface stays in place and exposes a real busy state.
  assert.match(moduleSource, /function setSummaryLoading\(loading, message = ""\)/);
  assert.match(moduleSource, /setAttribute\("aria-busy", String\(summaryLoading\)\)/);
  assert.match(moduleSource, /Array\.from\(\{ length: SKELETON_ROW_COUNT \}/);
  assert.match(moduleSource, /class="sd-row sd-loading-row"/);
  assert.match(moduleSource, /\$\{bar\} sd-loading-bar-mark/);
  assert.match(moduleSource, /\$\{bar\} sd-loading-bar-summary/);
  // The flowing fill has one owner, so Source Data and the table tabs match.
  assert.match(moduleSource, /const bar = `\$\{SKELETON_BAR_CLASS\} sd-loading-bar`/);

  // The three period fields and their picker actions stay inert and shimmer
  // until their values have been resolved from summary + saved settings.
  for (const binding of ["dom.originStart", "dom.originEnd", "dom.developmentEnd"]) {
    assert.ok(moduleSource.includes(binding), `${binding} is not part of the loading state`);
  }
  assert.match(moduleSource, /\.\.\.dom\.monthPickerButtons, dom\.filter/);
  assert.match(summaryCss, /\.table-summary\.is-loading \.sd-month input \{[\s\S]*?background-image: var\(--ps-skeleton-fill\);/);
  assert.match(skeletonCss, /\.ps-skeleton-bar \{[\s\S]*?animation: ps-skeleton-sweep 1\.15s ease-in-out infinite;/);
  assert.match(skeletonCss, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(summaryCss, /@media \(prefers-reduced-motion: reduce\)/);
  // Only the skeleton stylesheet paints the fill; the summary sheet sizes it.
  assert.doesNotMatch(summaryCss, /@keyframes sd-loading-sweep|--sd-loading-base:/);

  // Import Data starts the same state before the potentially long copy call.
  const importBlock = moduleSource.split("async function importData()")[1].split("/* ---------------- tooltips")[0];
  assert.ok(
    importBlock.indexOf("setSummaryLoading(") < importBlock.indexOf("await onImportData(method, scope)"),
    "the loading surface starts only after the source copy finishes",
  );

  // Rendering waits until the date inputs are ready, avoiding a stale-value flash.
  const loadBlock = projectSettingsJs.split("async function loadTableSummary")[1].split("// ============ Open in New Tab")[0];
  assert.ok(
    loadBlock.indexOf("sourceDataFeature.renderSummary(data)")
      > loadBlock.indexOf("applyStoredPeriodsToInputs(existingGeneralSettings)"),
    "the summary stops loading before the period inputs are resolved",
  );
});

test("the column preview opens only from a Distribution-cell click", () => {
  assert.match(moduleSource, /closest\("\.sd-c-dist"\)/);
  assert.match(moduleSource, /placeAtPointer\(/);
  assert.match(
    moduleSource,
    /addEventListener\("click", \(event\) => \{\s*const cell = event\.target\.closest\("\.sd-c-dist"\);[\s\S]*if \(!cell \|\| !row\) return;[\s\S]*showPreview\(row, \{ x: event\.clientX, y: event\.clientY \}, \{ cell \}\)/,
  );
  // No hover- or focus-driven preview remains.
  assert.ok(!moduleSource.includes('dom.list?.addEventListener("mousemove"'), "the hover preview handler remains");
  assert.ok(!moduleSource.includes('dom.list?.addEventListener("focusin"'), "the focus auto-open handler remains");
  assert.ok(!moduleSource.includes("PREVIEW_OPEN_DELAY_MS"), "the hover open delay remains");
  assert.ok(!moduleSource.includes("previewPinned"), "the retired pinned flag remains");
  assert.ok(!moduleSource.includes("hidePreview({ force: true })"), "the retired force option remains");
  // Keyboard rows open the same preview anchored to the cell.
  assert.match(moduleSource, /event\.key !== "Enter" && event\.key !== " "/);
  // Escape or an outside click closes it.
  assert.match(moduleSource, /!previewCard\.contains\(event\.target\)[\s\S]*!previewCell\?\.contains\(event\.target\)/);
  assert.match(moduleSource, /hidePreview\(\);[\s\S]*closeDetails\(\)/);
  // The card is always interactive; no pinned-state pointer-events toggle remains.
  const previewCardRule = summaryCss.match(/\.sd-preview-card\s*\{([\s\S]*?)\}/)?.[1] || "";
  assert.ok(!previewCardRule.includes("pointer-events"), "the preview card still toggles pointer events");
  assert.ok(!summaryCss.includes('[data-pinned="true"]'), "the retired pinned selector remains");
  assert.match(summaryCss, /\.sd-row \.sd-c-dist\s*\{\s*cursor:\s*pointer;/);
});

test("distribution marks cover categorical and numeric columns", () => {
  assert.match(moduleSource, /kind === "numeric"/);
  assert.match(moduleSource, /kind === "categorical"/);
  assert.match(moduleSource, /preserveAspectRatio="none"/);
  assert.match(summaryCss, /\.sd-area\b/);
  assert.match(summaryCss, /\.sd-strip\b/);
});

test("distribution cells pair the mark with an inline key-value summary", () => {
  assert.match(projectSettingsHtml, /class="sd-head-label">Distribution &amp; Summary</);
  assert.match(moduleSource, /class="sd-dist-mark"/);
  assert.match(moduleSource, /class="sd-dist-summary"/);
  assert.match(summaryCss, /\.sd-dist-mark\s*\{[\s\S]*?flex:\s*0 0 196px;/);
  assert.match(summaryCss, /\.sd-dist-summary\s*\{[\s\S]*?margin-left:\s*8px;/);
  assert.match(summaryCss, /\.sd-dist-summary\s*\{[\s\S]*?text-overflow:\s*ellipsis;/);
  // Null shares stay out of the row cells; the floating preview owns completeness.
  assert.ok(!moduleSource.includes("sd-dist-null"), "the removed inline null note remains rendered");
  assert.ok(!summaryCss.includes(".sd-dist-null"), "the removed inline null note styles remain");

  assert.equal(formatSummaryNumber(202612), "202,612");
  // Floats group thousands without decimals unless decimals are requested.
  assert.equal(formatSummaryNumber(1234567.891), "1,234,568");
  assert.equal(formatSummaryNumber(0.5, 4), "0.5000");
  assert.equal(formatSummaryNumber("bad"), "");

  assert.equal(
    getColumnRowSummary({
      type: "Float",
      stats: { min: -1400.6, max: 21630.29 },
      null_ratio: 0.021,
      distribution: { kind: "numeric", bins: [1] },
    }),
    "-1,401 ~ 21,630",
  );
  // Decimals stay only when the column's largest magnitude is under 10.
  assert.equal(
    getColumnRowSummary({
      type: "Float",
      stats: { min: -0.25, max: 5.5 },
      null_ratio: 0,
      distribution: { kind: "numeric", bins: [1] },
    }),
    "-0.2500 ~ 5.5000",
  );
  // Date-role columns render YYYYMM bounds as plain 6-digit integers.
  assert.equal(
    getColumnRowSummary(
      {
        type: "Float",
        stats: { min: 201701, max: 202612 },
        null_ratio: 0,
        distribution: { kind: "numeric", bins: [1] },
      },
      { asDate: true },
    ),
    "201701 ~ 202612",
  );
  assert.equal(
    getColumnRowSummary({
      type: "DateTime",
      stats: { min: "2017-01-01 00:00:00", max: "2026-05-31 00:00:00" },
      null_ratio: 0,
      distribution: { kind: "numeric", bins: [1] },
    }),
    "2017-01-01 00:00:00 ~ 2026-05-31 00:00:00",
  );
  // Date-role rows swap the displayed data type for `Date`.
  assert.match(moduleSource, /getColumnRowSummary\(column, \{ asDate: !!role \}\)/);
  assert.match(moduleSource, /const typeLabel = role \? "Date" : column\?\.type;/);
  assert.match(summaryCss, /\.sd-type-Date\s*\{\s*--sd-type-color:/);
  assert.equal(
    getColumnRowSummary({
      type: "String",
      distinct_count: 8,
      null_ratio: 0,
      distribution: { kind: "categorical", items: [{ label: "Direct", share: 0.42 }] },
    }),
    "8 distinct · Direct 42.0%",
  );
  // Columns without stats or a usable distribution fall back to the values string.
  assert.equal(
    getColumnRowSummary({ values: "(unknown)", distribution: { kind: "none" }, null_ratio: 1 }),
    "(unknown)",
  );
});

test("the first column uses regular-weight row text", () => {
  assert.match(summaryCss, /\.sd-row-name\s*\{[\s\S]*?font-weight:\s*400;/);
  assert.match(summaryCss, /\.sd-row-role\s*\{[\s\S]*?font-weight:\s*400;/);
});

test("column previews show completeness and percentage-accurate frequency meters", () => {
  assert.match(moduleSource, /const nullRatio = clampRatio\(column\?\.null_ratio\)/);
  assert.match(moduleSource, /const filledRatio = 1 - nullRatio/);
  assert.match(moduleSource, /<b>\$\{filledPercent\}<\/b> filled/);
  assert.match(moduleSource, /<b>\$\{nullPercent\}<\/b> null/);
  assert.ok(!moduleSource.includes("</b> empty"), "the retired empty-value label remains");
  assert.match(moduleSource, /Most Frequent<\/span><span>% of filled/);
  assert.match(moduleSource, /role="meter"/);
  assert.match(moduleSource, /aria-valuenow="\$\{pct\.toFixed\(1\)\}"/);
  assert.match(moduleSource, /--sd-bar-share:\$\{pct\.toFixed\(1\)\}%/);
  assert.match(summaryCss, /width:\s*var\(--sd-bar-share, 0%\)/);
  assert.match(summaryCss, /\.sd-bar-track\s*\{[\s\S]*border:\s*1px solid/);
});

test("histogram bars expose their bin range on hover", () => {
  assert.match(moduleSource, /class="sd-hist-bar"/);
  assert.match(moduleSource, /const rangeLabels = getHistBarLabels\(dist\)/);
  assert.match(summaryCss, /\.sd-hist-bar\s*\{[\s\S]*?height:\s*100%;/);
  assert.match(summaryCss, /\.sd-hist-bar:hover i\s*\{\s*opacity:\s*1;/);

  assert.deepEqual(getHistBarRangeLabels([0, 12000, 24000]), ["0 ~ 12,000", "12,000 ~ 24,000"]);
  // Decimals follow the same under-10 magnitude rule as the row summary.
  assert.deepEqual(getHistBarRangeLabels([0, 2.5, 5]), ["0 ~ 2.5000", "2.5000 ~ 5"]);
  assert.deepEqual(
    getHistBarRangeLabels([201701, 202156.5, 202612], { asDate: true }),
    ["201701 ~ 202157", "202157 ~ 202612"],
  );
  assert.deepEqual(getHistBarRangeLabels([1]), []);
  assert.deepEqual(getHistBarRangeLabels(["bad", 2]), []);
  assert.deepEqual(getHistBarRangeLabels(undefined), []);
});

test("a clipped histogram domain labels its end bins as open-ended", () => {
  // A clipped end bin also holds every value the quantile window cut away, so
  // it must not claim to cover only its own drawn span.
  assert.deepEqual(
    getHistBarRangeLabels([0, 100, 200, 300], { clippedLow: true, clippedHigh: true }),
    ["≤ 100", "100 ~ 200", "≥ 200"],
  );
  // Each end is reported independently: a zero-floored column clips only its
  // right tail, so its first bin keeps a closed range.
  assert.deepEqual(
    getHistBarRangeLabels([0, 100, 200, 300], { clippedHigh: true }),
    ["0 ~ 100", "100 ~ 200", "≥ 200"],
  );
  // An unclipped domain keeps closed ranges on every bin.
  assert.deepEqual(
    getHistBarRangeLabels([0, 100, 200, 300]),
    ["0 ~ 100", "100 ~ 200", "200 ~ 300"],
  );
});

test("empty histogram bins render at zero height instead of a floor", () => {
  // A minimum bar height draws a dashed baseline across empty bins that users
  // read as data; the full-height cell keeps the range tooltip regardless.
  assert.ok(
    !/Math\.max\(2, Math\.round\(\(Number\(value\) \|\| 0\) \* 100\)\)/.test(moduleSource),
    "histogram bars still floor their height",
  );
  assert.match(moduleSource, /height:\$\{\(clampRatio\(value\) \* 100\)\.toFixed\(1\)\}%/);
  assert.ok(
    !/\.sd-hist-bar i \{[\s\S]*?min-height:/.test(summaryCss),
    "the histogram bar floor survives in CSS",
  );
});

test("the row distribution mark is a monotone cubic area that never dips below its baseline", () => {
  const path = getDistributionAreaPath([0, 0.2, 1, 0.15, 0.05]);
  assert.match(path, /^M0,20 L0,20\.00 C/, "the area still opens on the baseline");
  assert.match(path, / L100,20 Z$/, "the area still closes on the baseline");

  // Every emitted coordinate, control points included, must stay inside the
  // viewBox: a filled overshoot would paint under the baseline or above the peak.
  const ys = [...path.matchAll(/[ML C](?:-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/g)]
    .map((match) => Number(match[1]));
  assert.ok(ys.length > 0);
  for (const y of ys) {
    assert.ok(y >= 0 && y <= 20, `control point ${y} escaped the viewBox`);
  }

  // A flat distribution stays flat rather than rippling between equal points.
  const flat = getDistributionAreaPath([0.5, 0.5, 0.5]);
  const flatYs = [...flat.matchAll(/,(-?\d+(?:\.\d+)?)/g)]
    .map((match) => Number(match[1]))
    .filter((y) => y !== 20);
  for (const y of flatYs) assert.equal(y, 11);

  assert.equal(getDistributionAreaPath([1]), "");
  assert.equal(getDistributionAreaPath([]), "");
  assert.equal(getDistributionAreaPath(undefined), "");
});

test("table summary service publishes versioned distribution data", () => {
  assert.match(summaryService, /SUMMARY_VERSION = 6/);
  // Significant digits, not decimal places: rounding a 1e-9 column's edges to a
  // fixed number of places collapses every hover label to "0 ~ 0".
  assert.match(summaryService, /"edges": \[float\(f"\{e:\.12g\}"\) for e in edges\]/);
  assert.match(summaryService, /def load_valid_cache\(/);
  assert.match(summaryService, /"distinct_count": distinct_count/);
  assert.match(summaryService, /"null_count": null_count/);
  assert.match(summaryService, /"null_ratio":/);
  assert.match(summaryService, /"stats": stats/);
  // Raw stats stay JSON-safe plain types because the router json.dumps the payload.
  assert.match(summaryService, /stats = \{"min": min_val, "max": max_val\}/);
  assert.match(summaryService, /min_val = float\(col_data\.min\(\)\)/);
  assert.match(summaryService, /stats = \{"min": str\(min_val\), "max": str\(max_val\)\}/);
  assert.match(summaryService, /"distribution": distribution/);
  assert.match(summaryService, /"summary_version": SUMMARY_VERSION/);
  // A stale or version-mismatched cache must be regenerated rather than served.
  assert.match(
    summaryRouter,
    /load_valid_cache\(master_path, cache_path, date_roles\)/,
  );
  assert.ok(!summaryRouter.includes("is_cache_valid("), "router still trusts mtime alone");
  // The cache lives at one fixed name; the app is not shipped yet, so there is
  // no per-version file name or legacy-file adoption to keep two installed
  // builds from colliding.
  assert.match(summaryConfig, /TABLE_SUMMARY_CACHE_FILE = "table_summary\.json"/);
  assert.match(summaryConfig, /def get_table_summary_cache_path\(project_name: str\)/);
  assert.match(summaryRouter, /config\.get_table_summary_cache_path\(name\)/);
  // A re-import makes the cached payload stale, so refresh discards it.
  assert.match(summaryRouter, /discard_cached_summary\(cache_path\)/);
});

test("date-role columns are binned by calendar year, one bar per year", () => {
  // Linear binning of YYYYMM combs: the 900 numeric units between 201701 and
  // 202612 hold only 120 real values, because months 13-99 do not exist.
  assert.match(summaryService, /def _date_year_distribution\(/);
  assert.match(summaryService, /np\.bincount\(years - first_year, minlength=span\)/);
  assert.match(summaryService, /"bin_labels": labels/);
  // Placeholder zeros and any other non-period value stay out of the chart.
  assert.match(summaryService, /\(years >= DATE_MIN_YEAR\) & \(years <= DATE_MAX_YEAR\)/);
  assert.match(summaryService, /& \(months >= 1\) & \(months <= 12\)/);
  // Year counts are directly comparable, so they keep linear heights.
  assert.ok(
    !/_date_year_distribution[\s\S]*?np\.sqrt[\s\S]*?def _empty_numeric/.test(summaryService),
    "year bars are root-scaled like the free-form numeric path",
  );
  // An unusable or absurdly wide column falls back rather than drawing nothing.
  assert.match(summaryService, /DATE_MAX_YEARS = 60/);
  assert.match(summaryService, /if span > DATE_MAX_YEARS:\s*\n\s*return None/);
  assert.match(summaryService, /def _distribution_for_column\(col_data: pd\.Series, role: str\)/);
});

test("the app server owns date-role detection and the cache tracks it", () => {
  // One canonical vocabulary instead of the literal pair repeated per service.
  assert.match(summaryConfig, /FIELD_MAPPING_DATE_SIGNIFICANCES = \("Origin Date", "Development Date"\)/);
  assert.match(summaryConfig, /\*FIELD_MAPPING_DATE_SIGNIFICANCES,/);
  assert.ok(
    !/\{"Origin Date", "Development Date"\}/.test(rulesService),
    "the rule service still repeats the date significance pair",
  );

  // One resolver owns "which columns hold a reserving period".
  assert.match(fieldMappingService, /def load_date_role_fields\(project_name: str\) -> Dict\[str, str\]/);
  assert.match(fieldMappingService, /if significance in config\.FIELD_MAPPING_DATE_SIGNIFICANCES/);
  assert.match(summaryRouter, /field_mapping_service\.load_date_role_fields\(name\)/);
  assert.match(summaryService, /"role": role/);

  // Remapping Origin Date leaves the CSV untouched, so an mtime-only cache
  // check would keep serving the previous column's year bars.
  assert.match(summaryService, /if cached\.get\("date_roles"\) != dict\(date_roles or \{\}\):/);
  assert.match(summaryService, /"date_roles": dict\(date_roles or \{\}\)/);
  assert.match(summaryRouter, /load_valid_cache\(master_path, cache_path, date_roles\)/);
});

test("histogram bar labels prefer the server's year labels", () => {
  assert.deepEqual(
    getHistBarLabels({ bins: [1, 0.5], bin_labels: ["2017", "2018"] }),
    ["2017", "2018"],
  );
  // A label array that does not line up with the bars is ignored, not zipped.
  assert.deepEqual(
    getHistBarLabels({ bins: [1, 0.5], bin_labels: ["2017"], edges: [0, 10, 20] }),
    ["0 ~ 10", "10 ~ 20"],
  );
  // Free-form numeric columns still describe each bar as a bin range.
  assert.deepEqual(
    getHistBarLabels({ bins: [1, 0.5], edges: [0, 10, 20], clipped_high: true }),
    ["0 ~ 10", "≥ 10"],
  );
  assert.deepEqual(getHistBarLabels({}), []);
  assert.deepEqual(getHistBarLabels(undefined), []);
});

test("Source Data reads each column's date role from the payload", () => {
  assert.match(moduleSource, /function roleForColumn\(column\) \{\s*return String\(column\?\.role \|\| ""\)\.trim\(\);/);
  assert.ok(
    !moduleSource.includes("dateRoles"),
    "the tab still keeps its own copy of the field mapping",
  );
  assert.ok(
    !moduleSource.includes("setDateRoles"),
    "the retired setDateRoles entry point remains",
  );
});

test("numeric distributions are quantile-framed, smoothed, and root-scaled", () => {
  // Concentrated columns with long tails are the shape this pipeline exists for:
  // the raw min/max domain plus linear heights renders them as a bare spike.
  assert.match(summaryService, /DISTRIBUTION_TAIL_QUANTILE = 0\.005/);
  assert.match(summaryService, /np\.clip\(arr, lo, hi\)/);
  assert.match(summaryService, /heights = np\.sqrt\(density \/ peak\)/);

  // Binned KDE: oversample, convolve one Gaussian, average back down.
  assert.match(summaryService, /DISTRIBUTION_OVERSAMPLE = 8/);
  assert.match(summaryService, /bins=bin_count \* DISTRIBUTION_OVERSAMPLE/);
  assert.match(summaryService, /np\.convolve\(/);
  assert.match(summaryService, /\.reshape\(bin_count, DISTRIBUTION_OVERSAMPLE\)\.mean\(axis=1\)/);

  // Never more output bins than the fine histogram found occupied, or a
  // low-cardinality column combs into alternating full and empty bins. Reading
  // occupancy off the counts keeps this free; a distinct-value pass over the
  // rows would roughly double the per-column cost on a large table.
  assert.match(summaryService, /DISTRIBUTION_BIN_COUNT = 40/);
  assert.match(summaryService, /bin_count = int\(np\.count_nonzero\(counts\)\)/);
  assert.match(summaryService, /bin_count = max\(DISTRIBUTION_MIN_BIN_COUNT, bin_count\)/);
  const numericDistribution = summaryService.slice(
    summaryService.indexOf("def _numeric_distribution("),
    summaryService.indexOf("def _categorical_distribution("),
  );
  assert.ok(numericDistribution.length > 0);
  assert.ok(
    !numericDistribution.includes("nunique"),
    "the numeric distribution still pays for a distinct-value pass over the rows",
  );

  // Both clip ends ship so the preview can label only the bins that truly clip.
  assert.match(summaryService, /"clipped_low": clipped_low/);
  assert.match(summaryService, /"clipped_high": clipped_high/);
  assert.match(summaryService, /bool\(lo > data_min\), bool\(hi < data_max\)/);

  // A column too short for the tail window to hold one observation is drawn
  // across its full range instead of having its only two rows clipped away.
  assert.match(summaryService, /DISTRIBUTION_CLIP_MIN_ROWS = int\(1 \/ DISTRIBUTION_TAIL_QUANTILE\)/);
  assert.match(summaryService, /if values\.size >= DISTRIBUTION_CLIP_MIN_ROWS:/);
  // Infinities survive dropna and would collapse the domain onto a single bin.
  assert.match(summaryService, /arr = arr\[np\.isfinite\(arr\)\]/);
});

test("table summary is addressed by project and reads the imported master table", () => {
  // The route no longer accepts a caller-supplied path; the project owns the table.
  assert.match(summaryRouter, /def get_table_summary\(project_name: str\)/);
  assert.match(summaryRouter, /source_table_service\.ensure_master_table\(project_name, force=force\)/);
  assert.match(summaryRouter, /generate_table_summary\(master_path, date_roles\)/);
  assert.ok(!summaryRouter.includes("req.path"), "refresh still reads a caller path");

  assert.match(projectSettingsJs, /async function loadTableSummary\(projectName = "", options = \{\}\)/);
  assert.match(projectSettingsJs, /new URLSearchParams\(\{ project_name: projectName \|\| "" \}\)/);
  assert.ok(
    !/JSON\.stringify\(\{\s*path: tablePath/.test(projectSettingsJs),
    "coordinator still posts an external table path to /table_summary/refresh",
  );
});

test("the Source Data reload button only re-reads the page", () => {
  const handler = projectSettingsJs.slice(
    projectSettingsJs.indexOf("summaryTablePathReloadBtn.onclick"),
  ).slice(0, projectSettingsJs.slice(
    projectSettingsJs.indexOf("summaryTablePathReloadBtn.onclick"),
  ).indexOf("\n  };"));
  assert.ok(handler.includes("loadTableSummary("), "reload no longer loads the summary");
  // A forced refresh re-imports the source table, clears every generated
  // dataset cache and rebuilds the reserving-class values. Reload must not.
  assert.ok(
    !/forceRefresh:\s*true/.test(handler),
    "reload forces a full source-table refresh again",
  );
  assert.match(handler, /forceDerivedDates:\s*true/);
  assert.match(handler, /forceFieldMappingReload:\s*true/);
  assert.match(handler, /forceReservingClassTypesReload:\s*true/);

  // Re-deriving the period boundaries no longer rides on the full refresh.
  assert.match(
    projectSettingsJs,
    /const forceDerivedDates = forceRefresh \|\| !!options\?\.forceDerivedDates;/,
  );
  assert.match(
    projectSettingsJs,
    /\|\| \(forceDerivedDates && !!existingGeneralSettings\.autoGenerated\)/,
  );

  // The cache clears stay bound to a forced refresh, which only Import Data's
  // Engine-unavailable fallback still asks for.
  assert.match(
    projectSettingsJs,
    /if \(forceRefresh && projectName\) \{\s*\n\s*await clearArcRhoHeadersCacheForProject\(projectName\);/,
  );
});

test("the Import Settings window is a regular draggable window", () => {
  for (const id of [
    "summaryImportSettingsBtn",
    "summaryImportWindow",
    "summaryImportWindowHeader",
    "summaryImportWindowClose",
    "sdMethodTrigger",
    "sdMethodList",
    "sdCsvPath",
    "sdCsvBrowseBtn",
    "sdMssqlServer",
    "sdMssqlDatabase",
    "sdMssqlLoadTablesBtn",
    "sdMssqlTableInput",
    "sdMssqlTableCaretBtn",
    "sdMssqlTableList",
    "sdMssqlAuthGroup",
    "sdImportDataBtn",
    "sdMssqlStatus",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing markup id ${id}`);
    assert.ok(moduleSource.includes(id), `feature module never binds ${id}`);
  }

  // It reuses the page's editor-window chrome rather than a page-local style.
  assert.match(projectSettingsHtml, /class="rct-row-editor sd-import-window" id="summaryImportWindow"/);
  assert.match(projectSettingsHtml, /class="rct-row-editor-header" id="summaryImportWindowHeader"/);
  assert.match(summaryCss, /\.sd-import-window \{/);

  // The window lives beside the other editor windows, not inside the tab body.
  const windowIndex = projectSettingsHtml.indexOf('id="summaryImportWindow"');
  const summaryEndIndex = projectSettingsHtml.indexOf('id="summaryStatsCard"');
  assert.ok(windowIndex > summaryEndIndex, "the window is still nested in the Source Data tab");

  // Dragged by its title bar, exactly like the sibling editors.
  assert.match(moduleSource, /function onWindowHeaderMouseDown\(event\)/);
  assert.match(moduleSource, /dom\.sourcePanelHeader\?\.addEventListener\("mousedown", onWindowHeaderMouseDown\)/);
  assert.match(projectSettingsJs, /sourceDataFeature\?\.onEditorMouseMove\(e\)/);
  assert.match(projectSettingsJs, /sourceDataFeature\?\.onEditorMouseUp\(\)/);

  // A regular window is not dismissed by clicking outside it.
  assert.match(moduleSource, /an outside click never/);
  assert.ok(
    !/closeSourcePanel\(\);\s*\} else if/.test(moduleSource),
    "the window still closes on an outside click",
  );

  // Only the selected method's fields are shown, and Import Data commits either.
  assert.match(moduleSource, /section\.hidden = String\(section\.dataset\.method \|\| ""\) !== method/);
  assert.match(projectSettingsHtml, /data-method="csv"/);
  assert.match(projectSettingsHtml, /data-method="mssql"/);
  assert.match(projectSettingsHtml, /id="sdImportDataBtn"[^>]*>Import Data</);

  // SQL Server login is present as a disabled placeholder only.
  assert.match(projectSettingsHtml, /data-auth="sql_login"[^>]*disabled/);

  // The header keeps three actions; the copy-path and per-method icons are gone.
  for (const retired of [
    "summaryCopyPathBtn",
    "summaryTablePathBrowseBtn",
    "summarySourceSettingsBtn",
    "summaryImportBtn",
  ]) {
    assert.ok(!projectSettingsHtml.includes(`id="${retired}"`), `retired #${retired} remains in markup`);
    assert.ok(!moduleSource.includes(retired), `retired #${retired} remains bound`);
  }
});

test("the Import Settings window is resizable and opens at a workable size", () => {
  // Header and footer stay pinned while only the body scrolls.
  assert.match(summaryCss, /\.sd-import-window \{[\s\S]*?overflow: hidden;/);
  assert.match(summaryCss, /\.sd-import-window\.show \{\s*display: flex;\s*flex-direction: column;/);
  assert.match(summaryCss, /\.sd-import-window \.rct-row-editor-actions \{ flex: 0 0 auto; \}/);
  assert.match(summaryCss, /\.sd-import-body \{[\s\S]*?flex: 1 1 auto;[\s\S]*?overflow-y: auto;/);
  assert.match(summaryCss, /\.sd-import-window \{[\s\S]*?min-width: 520px;/);
  assert.match(summaryCss, /\.sd-import-window \{[\s\S]*?min-height: 360px;/);
  assert.match(summaryCss, /\.sd-import-window \{[\s\S]*?max-height: calc\(100vh - 32px\);/);

  const width = Number(summaryCss.match(/\.sd-import-window \{[\s\S]*?width: (\d+)px;/)?.[1]);
  assert.ok(width >= 720, `the window default width is still narrow: ${width}px`);

  // A resizable window with overflow cannot clip its own dropdowns, so the
  // lists render into document.body and are re-anchored as the window changes.
  assert.match(moduleSource, /if \(list && list\.parentElement !== document\.body\) document\.body\.appendChild\(list\)/);
  assert.match(summaryCss, /\.sd-select-list \{[\s\S]*?position: fixed;/);
  assert.match(moduleSource, /function repositionSourceLists\(\)/);
  assert.match(moduleSource, /new ResizeObserver\(\(\) => repositionSourceLists\(\)\)\.observe\(dom\.sourcePanel\)/);
  // Ownership can no longer be asked of the window markup.
  assert.match(moduleSource, /owns: \(node\) =>/);
  assert.match(moduleSource, /!methodSelect\.owns\(event\.target\)/);
  assert.match(moduleSource, /!tableSelect\.owns\(event\.target\)/);
});

test("the window resizes from its own grip, anchored at the top-left corner", () => {
  // The native `resize` property would paint the page-wide ::-webkit-resizer
  // glyph and, because the window is centered with a transform, would grow it
  // from both edges at once. Neither is acceptable, so there is no native resize.
  const windowBlock = summaryCss.match(/\.sd-import-window \{[\s\S]*?\}/)?.[0] || "";
  assert.ok(windowBlock, "the .sd-import-window rule is missing");
  assert.ok(!/\bresize:/.test(windowBlock), "the window still uses native CSS resize");
  assert.ok(
    !summaryCss.includes(".sd-import-window::-webkit-resizer"),
    "the native resizer pseudo-element is still being styled",
  );

  // Invisible hit-areas on every edge and corner carry the resize affordance.
  assert.match(projectSettingsHtml, /id="summaryImportWindowResizer"/);
  for (const edge of ["n", "s", "e", "w", "nw", "ne", "sw", "se"]) {
    assert.match(projectSettingsHtml, new RegExp(`class="sd-import-resizer" data-edge="${edge}"`));
  }
  assert.match(summaryCss, /\.sd-import-resizer \{[\s\S]*?position: absolute;/);
  assert.match(summaryCss, /\.sd-import-resizer\[data-edge="ne"\] \{[^}]*cursor: nesw-resize;/);
  // Every page shares one window height, so changing pages never makes it jump.
  assert.match(summaryCss, /\.sd-import-window \{[^}]*height: min\(620px, calc\(100vh - 172px\)\);/);
  // A top or left grip moves that edge and keeps the opposite one still.
  assert.match(moduleSource, /dom\.sourcePanel\.style\.left = `\$\{right - width\}px`/);
  assert.match(moduleSource, /dom\.sourcePanel\.style\.top = `\$\{bottom - height\}px`/);

  // Pinning left/top before sizing is what keeps the left edge still: while the
  // centering transform is in place, `left` names the window's midpoint.
  assert.match(moduleSource, /function pinSourcePanelPosition\(rect\)/);
  assert.match(moduleSource, /transform = "none"/);
  const resizerDown = moduleSource.match(/function onWindowResizerMouseDown\([\s\S]*?\n  \}/)?.[0] || "";
  assert.ok(resizerDown, "onWindowResizerMouseDown is missing");
  assert.ok(
    resizerDown.indexOf("pinSourcePanelPosition") < resizerDown.indexOf("windowResizeState ="),
    "the resize drag starts before the window position is pinned",
  );
  assert.match(moduleSource, /grip\.addEventListener\("mousedown", onWindowResizerMouseDown\)/);

  // CSS stays the single owner of the minimum size; JS only reads it back.
  assert.match(moduleSource, /function sourcePanelSizeLimits\(\)/);
  assert.match(moduleSource, /getComputedStyle\(dom\.sourcePanel\)/);

  // A stale resize state would hijack a later header drag.
  assert.match(moduleSource, /function onWindowMouseUp\(\) \{\s*windowDragState = null;\s*windowResizeState = null;/);
});

test("dropdown lists never scroll sideways", () => {
  // A horizontal bar sits on top of the last row and hides the option the user
  // is reaching for, so long names ellipsize instead.
  assert.match(summaryCss, /\.sd-select-list \{[\s\S]*?overflow-x: hidden;/);
  // The rows were 12px wider than the list without border-box: `width: 100%`
  // plus horizontal padding.
  assert.match(summaryCss, /\.sd-select-opt \{[\s\S]*?box-sizing: border-box;[\s\S]*?width: 100%;/);
  assert.match(summaryCss, /\.sd-select-opt-name \{[\s\S]*?text-overflow: ellipsis;[\s\S]*?white-space: nowrap;/);
});

test("the dropdown caret is a filled triangle in a reserved arrow lane", () => {
  // Matches the canonical .dpr-select-caret treatment.
  assert.match(summaryCss, /\.sd-select-caret \{[\s\S]*?position: absolute;/);
  assert.match(summaryCss, /\.sd-select-caret \{[\s\S]*?width: 0;[\s\S]*?height: 0;/);
  assert.match(summaryCss, /\.sd-select-caret \{[\s\S]*?border-left: 4px solid transparent;/);
  assert.match(summaryCss, /\.sd-select-caret \{[\s\S]*?border-top: 5px solid/);
  // It flips when the list is open.
  assert.match(
    summaryCss,
    /\.sd-select-trigger\[aria-expanded="true"\] \.sd-select-caret \{\s*transform: translateY\(-75%\) rotate\(180deg\);/,
  );
  // The trigger anchors the caret and reserves its lane.
  assert.match(summaryCss, /\.sd-select-trigger \{[\s\S]*?position: relative;/);
  assert.match(summaryCss, /\.sd-select-trigger \{[\s\S]*?padding: 0 24px 0 8px;/);
  // The old flex-sized caret stretched into a bar and must not come back.
  assert.ok(
    !/\.sd-select-caret \{[\s\S]*?flex: 0 0 16px;/.test(summaryCss),
    "the caret is still flex-sized and will render as a bar",
  );
});

test("the table list is searched by typing in the field itself", () => {
  // The field is the search box: no separate input is rendered inside the list.
  assert.ok(!moduleSource.includes("sd-select-search"), "a separate search box remains");
  assert.ok(!summaryCss.includes(".sd-select-search"), "the separate search box styles remain");
  assert.match(projectSettingsHtml, /id="sdMssqlTableInput"[^>]*role="combobox"/);
  assert.match(projectSettingsHtml, /id="sdMssqlTableInput"[^>]*aria-autocomplete="list"/);

  // Typing filters; only the list is re-rendered, never the field, so the
  // caret keeps its position across keystrokes.
  assert.match(moduleSource, /function visibleOptions\(\)/);
  assert.match(moduleSource, /\.toLowerCase\(\)\.includes\(query\)/);
  const inputHandler = moduleSource
    .split('input?.addEventListener("input", () => {')[1]
    .split("});")[0];
  assert.ok(inputHandler.includes("filter = String(input.value"), "typing does not drive the filter");
  assert.ok(!inputHandler.includes("input.value ="), "the field is rewritten while typing");
  assert.ok(!inputHandler.includes(".focus()"), "the field is re-focused while typing");

  // The committed table stays separate from the typed filter text.
  assert.match(moduleSource, /getValue: \(\) => committed/);
  assert.match(moduleSource, /function restoreCommittedText\(\)/);
  // A single remaining match commits on Enter.
  assert.match(moduleSource, /if \(rows\.length === 1\) \{/);
  assert.match(moduleSource, /\$\{rows\.length\} of \$\{options\.length\}/);
});

test("used server/database pairs are remembered in the server-shared config", () => {
  // Server-shared scope: one canonical builder under <workspace_root>/config,
  // never a hardcoded drive or server root.
  assert.match(sourceTableContract, /MSSQL_CONNECTIONS_FILE = "mssql_connections\.json"/);
  assert.match(appServerConfig, /def get_mssql_connections_path\(\) -> str:/);
  assert.match(
    appServerConfig,
    /get_root_path\(\), "config", source_table_contract\.MSSQL_CONNECTIONS_FILE/,
  );
  assert.ok(
    !/E:\\\\ArcRho Server/.test(appServerConfig.split("def get_mssql_connections_path")[1] || ""),
    "the shared connections path hardcodes a server root",
  );

  // Identifiers only - the shared file must never carry credentials.
  assert.match(sourceTableContract, /def normalize_mssql_connection\(/);
  const entryShape = sourceTableContract
    .split("def normalize_mssql_connection(")[1]
    .split("def ")[0];
  for (const forbidden of ["password", "user", "token"]) {
    assert.ok(!entryShape.includes(forbidden), `the saved entry carries ${forbidden}`);
  }

  // Recorded on a successful connect and on a committed import, both of which
  // run on this PC; the shared list itself is written on the server host.
  assert.match(sourceTableService, /def remember_mssql_connection\(/);
  assert.equal(
    (sourceTableService.match(/submit_mssql_connection_remember\(profile\["server"\], profile\["database"\]\)/g) || []).length,
    2,
    "the pair is not recorded on both connect and import",
  );
  assert.match(sourceTableService, /"mssql_connection_remember",/);
  // An unreachable Gateway must not fail an otherwise good operation.
  assert.match(sourceTableService, /except HTTPException:\s*\n\s*# An unreachable Gateway/);

  assert.match(sourceTableRouter, /@router\.get\("\/source_table\/connections"\)/);
  assert.match(sourceTableRouter, /@router\.post\("\/source_table\/connections\/forget"\)/);
});

test("saved connections can be picked and deleted from the field dropdowns", () => {
  for (const id of [
    "sdMssqlServerCombo",
    "sdMssqlServerHistoryBtn",
    "sdMssqlServerList",
    "sdMssqlDatabaseCombo",
    "sdMssqlDatabaseHistoryBtn",
    "sdMssqlDatabaseList",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing markup id ${id}`);
    assert.ok(moduleSource.includes(id), `feature module never binds ${id}`);
  }

  // Free text stays possible; the dropdown only offers prior values.
  assert.match(projectSettingsHtml, /<input id="sdMssqlServer" type="text"/);
  assert.match(projectSettingsHtml, /<input id="sdMssqlDatabase" type="text"/);
  assert.match(moduleSource, /function createSdCombo\(/);

  // Every row carries a remove action.
  assert.match(moduleSource, /class="sd-select-opt-remove"/);
  assert.match(moduleSource, /onRemove\?\.\(remove\.dataset\.remove\)/);
  assert.match(summaryCss, /\.sd-select-opt-remove \{/);
  // Removing a server drops all of its pairs; removing a database drops one.
  assert.match(moduleSource, /onRemove: \(server\) => forgetConnection\(server, null\)/);
  assert.match(moduleSource, /onRemove: \(database\) => forgetConnection\(/);

  // The database list is scoped to the server currently typed in.
  assert.match(moduleSource, /entry\.server\.toLowerCase\(\) === currentServer/);
  assert.match(moduleSource, /if \(input === dom\.mssqlServer\) syncDatabaseHistory\(\)/);
  // Re-seeding the server list on every keystroke would clear the filter being
  // typed, so only the database list re-scopes as the server changes.
  assert.match(moduleSource, /function syncDatabaseHistory\(\)/);
  const serverInputSync = moduleSource
    .split("function syncDatabaseHistory()")[1]
    .split("\n  }")[0];
  assert.ok(!serverInputSync.includes("serverCombo.setOptions"), "typing a server resets its own list");

  assert.match(projectSettingsJs, /"\/source_table\/connections"/);
  assert.match(projectSettingsJs, /"\/source_table\/connections\/forget"/);
});

test("import method is chosen from a dropdown built by the shared select", () => {
  // The retired segmented switch is fully gone.
  assert.ok(!projectSettingsHtml.includes("sd-source-switch"), "the retired method switch remains in markup");
  assert.ok(!projectSettingsHtml.includes("sd-source-opt"), "the retired method switch options remain");
  assert.ok(!summaryCss.includes(".sd-source-switch"), "the retired method switch styles remain");
  assert.ok(!moduleSource.includes("sourceOptions"), "the retired method switch is still bound");

  assert.match(projectSettingsHtml, /id="sdMethodTrigger"[^>]*aria-haspopup="listbox"/);
  assert.match(projectSettingsHtml, /id="sdMethodList"[^>]*role="listbox"/);

  // Both dropdowns come from one implementation.
  assert.match(moduleSource, /function createSdSelect\(/);
  assert.match(moduleSource, /const methodSelect = createSdSelect\(/);
  assert.match(moduleSource, /const tableSelect = createSdCombo\(/);
  assert.match(moduleSource, /\{ value: SOURCE_TYPE_CSV, label: "CSV File" \}/);
  assert.match(moduleSource, /\{ value: SOURCE_TYPE_MSSQL, label: "SQL Server" \}/);
});

test("the table picker lists tables and views from the chosen database", () => {
  // A themed listbox, not an unstyled native select popup.
  const windowMarkup = projectSettingsHtml
    .slice(projectSettingsHtml.indexOf('id="summaryImportWindow"'))
    .split('id="reservingClassTypesRowContextMenu"')[0];
  assert.ok(!windowMarkup.includes("<select"), "a native select was used in the import window");
  assert.match(projectSettingsHtml, /id="sdMssqlTableInput"[^>]*role="combobox"/);
  assert.match(projectSettingsHtml, /id="sdMssqlTableCaretBtn"[^>]*aria-haspopup="listbox"/);
  assert.match(summaryCss, /\.sd-select-list \{/);
  assert.match(summaryCss, /\.sd-select-caret \{/);

  assert.match(moduleSource, /function loadTableOptions\(\)/);
  assert.match(moduleSource, /await onListTables\(profile\)/);
  assert.match(moduleSource, /item\.kind === "view" \? "View" : "Table"/);
  // Editing the connection invalidates the list it produced.
  assert.match(
    moduleSource,
    /if \(tableSelect\.hasOptions\(\)\) tableSelect\.setOptions\(\[\], \{ keepSelection: false \}\)/,
  );

  assert.match(projectSettingsJs, /"\/source_table\/tables"/);
  assert.match(sourceTableRouter, /@router\.post\("\/source_table\/tables"\)/);
  assert.match(sourceTableService, /INFORMATION_SCHEMA\.TABLES/);
  assert.match(sourceTableService, /TABLE_TYPE IN \('BASE TABLE', 'VIEW'\)/);
});

test("Source Data reports the project-owned imported table, not the external source", () => {
  assert.match(moduleSource, /export function normalizeSourceState/);
  assert.match(moduleSource, /master_table_path/);
  assert.match(moduleSource, /key: "Imported From"/);
  assert.match(moduleSource, /key: "Imported At"/);
  // "Modified" is the external CSV's own mtime. The master copy is rewritten on
  // every import, so its mtime would only ever repeat "Imported At".
  assert.match(moduleSource, /key: "Modified", value: formatTimestamp\(sourceCsvMtimeSeconds\(\)\)/);
  assert.match(moduleSource, /csvMtimeNs: lastImport\.csv_mtime_ns/);
  assert.match(sourceTableContract, /out\["csv_mtime_ns"\] = _int_or_none\(data\.get\("csv_mtime_ns"\)\)/);
  assert.ok(!moduleSource.includes("data?.csv_mtime"), "the master-copy mtime is still rendered");
  // The imported-copy path and the row-count caption were dropped from the card.
  assert.ok(!moduleSource.includes('key: "Imported Table"'), "the imported-table row remains");
  assert.ok(!moduleSource.includes("data rows, header excluded"), "the row-count caption remains");

  // Every app-server call stays in the coordinator.
  assert.ok(!moduleSource.includes("fetch("), "feature module calls the app server directly");
  assert.match(projectSettingsJs, /\/source_table\?project_name=/);
  assert.match(projectSettingsJs, /"\/source_table\/profile"/);
  assert.match(projectSettingsJs, /"\/source_table\/import"/);
  assert.match(projectSettingsJs, /"\/source_table\/refresh"/);
});

test("Opening the details panel reads the source file's own modified time", () => {
  // Opening the panel is what asks the file; the recorded time only stands in
  // until the read lands, and stays when the file cannot be reached.
  assert.match(moduleSource, /placeFloating\(dom\.statsCard[^;]*;\s*refreshFileStatus\(\);/);
  assert.match(moduleSource, /async function refreshFileStatus\(\)/);
  assert.match(moduleSource, /const status = await onSourceFileStatus\(\);/);
  assert.match(moduleSource, /const live = fileStatus\?\.exists \? fileStatus\.csv_mtime_ns : null;/);
  assert.match(moduleSource, /Number\(live \?\? sourceState\.lastImport\?\.csvMtimeNs\)/);
  // Hover opens the panel, so repeated opens must not re-read the file.
  assert.match(moduleSource, /Date\.now\(\) - fileStatusAt < FILE_STATUS_FRESH_MS/);
  // A SQL Server project has no source file to read.
  assert.match(moduleSource, /sourceState\.sourceType === SOURCE_TYPE_MSSQL \|\| fileStatusPending/);
  // A new selection or a finished import retires the comparison.
  assert.match(moduleSource, /sourceState = normalizeSourceState\(state\);[\s\S]{0,240}?fileStatus = null;/);
  assert.match(moduleSource, /note: sourceCsvMtimeNote\(\)/);
  assert.match(moduleSource, /return fileStatus\.matches_import \? "" : "changed since the last import";/);

  // The read stays in the coordinator and never blocks the panel.
  assert.match(projectSettingsJs, /\/source_table\/file_status\?project_name=/);
  assert.match(projectSettingsJs, /onSourceFileStatus: \(\) => loadSourceFileStatus\(\)/);
  assert.match(sourceTableRouter, /@router\.get\("\/source_table\/file_status"\)/);
  assert.match(sourceTableService, /def get_source_file_status\(project_name: str\)/);
  assert.match(sourceTableService, /status\["matches_import"\] = same_csv_identity\(record\.get\("last_import"\), identity\)/);
  // Reading the file must never import it, and must never fail the panel.
  const statusFn = sourceTableService
    .slice(sourceTableService.indexOf("def get_source_file_status"))
    .split("\ndef ")[0];
  assert.ok(!statusFn.includes("_copy_csv_to_master"), "the status read re-copies the master table");
  assert.match(statusFn, /except OSError:\s+return status/);
});

test("Import Data rebuilds the master table from whichever method is selected", () => {
  assert.match(moduleSource, /async function importData\(\)/);
  // Both branches save the settings first, then run one import.
  assert.match(moduleSource, /await onProfileSave\(method, profile, csvPath\)/);
  assert.match(moduleSource, /await onImportData\(method, scope\)/);
  // Each method validates only what it needs before touching the server.
  assert.match(moduleSource, /Select a table or view to import\./);
  assert.match(moduleSource, /Choose a CSV file to import\./);

  // A source only this PC can read is read here and uploaded, SQL or CSV.
  assert.match(projectSettingsJs, /isSql \? "\/source_table\/import" : "\/source_table\/refresh"/);
  assert.match(projectSettingsJs, /body: JSON\.stringify\(\{ project_name: name \}\)/);
  // A finished import refreshes everything derived from the table.
  assert.match(projectSettingsJs, /forceReservingClassTypesReload: true/);
});

test("Import Data is preceded by an Import Scope step that narrows the refresh", () => {
  // The window has two pages sharing one body class; Next validates the
  // settings and opens the scope page, Back returns, Import Data runs from it.
  assert.match(projectSettingsHtml, /<div class="sd-import-body sd-import-scope" id="sdImportScope" data-step="scope" data-page="datasets" hidden>/);
  for (const id of [
    "sdImportNextBtn",
    "sdImportBackBtn",
    "sdImportDataBtn",
    "sdScopeDatasetsList",
    "sdScopeDatasetsFilter",
    "sdScopeDatasetsCount",
    "sdScopeClassTypesList",
    "sdScopeClassTypesFilter",
    "sdScopeClassTypesCount",
    "sdScopeStatus",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
    assert.ok(moduleSource.includes(`el("${id}")`), `#${id} is not bound by the Source Data module`);
  }
  assert.match(moduleSource, /importNextBtn\?\.addEventListener\("click", \(\) => goToNextPanelStep\(\)\)/);
  assert.match(moduleSource, /importBackBtn\?\.addEventListener\("click", \(\) => goToPreviousPanelStep\(\)\)/);
  // Datasets and reserving class types are separate pages, in that order.
  // With one table the pages are settings, datasets, classes (importSteps in the combined module).
  assert.match(moduleSource, /panelStep = combinedSource\.steps\(\)\.includes\(step\) \? step : "settings";/);
  assert.match(moduleSource, /datasets: "Import Scope: Datasets"/);
  assert.match(moduleSource, /classes: "Import Scope: Reserving Class Types"/);
  assert.match(moduleSource, /if \(panelStep === "settings" \|\| panelStep === "combine"\) \{\s*goToScopeStep\(\);/);
  assert.match(moduleSource, /if \(panelStep === "datasets" && !datasetScopeProblem\(\)\) \{\s*showPanelStep\("classes"\)/);
  assert.match(moduleSource, /importDataBtn\.hidden = panelStep !== "classes"/);
  assert.match(projectSettingsHtml, /<section class="sd-scope-pane" data-page="datasets"/);
  assert.match(projectSettingsHtml, /<section class="sd-scope-pane" data-page="classes" [^>]*hidden>/);
  assert.match(summaryCss, /\.sd-scope-pane\[hidden\],\s*\.sd-scope-intro\[hidden\] \{ display: none; \}/);
  // The Datasets page cannot move on with nothing ticked.
  assert.match(moduleSource, /importNextBtn\.disabled = sourceBusy \|\| \(panelStep === "datasets" && !!datasetProblem\)/);
  // The body class sets display, so the hidden page needs its own rule.
  assert.match(summaryCss, /\.sd-import-body\[hidden\] \{ display: none; \}/);
  assert.match(summaryCss, /\.rct-row-editor-actions \.dialog-btn\[hidden\] \{ display: none; \}/);

  // The options come from the app server, and only engine-built dataset types are offered.
  assert.match(moduleSource, /const options = await onLoadImportScope\(\)/);
  assert.match(projectSettingsJs, /onLoadImportScope: \(\) => loadImportScopeOptions\(\)/);
  assert.match(projectSettingsJs, /generated\[item\.name\] === true/);
  assert.match(projectSettingsJs, /fetch\(`\/reserving_class_types\?\$\{query\}`\)/);

  // Nothing ticked is not a refresh, and every narrowed level must keep a type.
  assert.match(moduleSource, /return "Choose at least one dataset\."/);
  assert.match(moduleSource, /Choose at least one reserving class type at Level \$\{Math\.min\(\.\.\.empty\)\}\./);
  assert.match(moduleSource, /dom\.importDataBtn\.disabled = sourceBusy \|\| !!problem/);
  // A fully ticked list is "everything", and an unnarrowed level is left out.
  assert.match(moduleSource, /scopeState\.selectedDatasets\.size === scopeState\.datasetTypes\.length\s*\? \[\]/);
  assert.match(moduleSource, /\(tickedByLevel\.get\(item\.level\) \|\| 0\) < totalByLevel\.get\(item\.level\)/);
  // A group tick only reaches the rows a filter still shows.
  assert.match(moduleSource, /\.sd-scope-row:not\(\[hidden\]\) input/);
  // Each list has Select all / Clear all, reaching the same shown rows.
  for (const id of [
    "sdScopeDatasetsAllBtn",
    "sdScopeDatasetsNoneBtn",
    "sdScopeClassTypesAllBtn",
    "sdScopeClassTypesNoneBtn",
  ]) {
    assert.ok(projectSettingsHtml.includes(`id="${id}"`), `missing #${id} in markup`);
    assert.ok(moduleSource.includes(`el("${id}")`), `#${id} is not bound by the Source Data module`);
  }
  assert.match(moduleSource, /function setScopeListAll\(listEl, selected, on\)/);
  assert.match(moduleSource, /setScopeListAll\(list, selected\(\), button\.dataset\.bulk === "all"\)/);
  assert.match(moduleSource, /allBtn\.disabled = sourceBusy \|\| ticked === boxes\.length/);
  assert.match(moduleSource, /noneBtn\.disabled = sourceBusy \|\| ticked === 0/);
  // A filter that hides everything says so.
  assert.match(moduleSource, /No matches for/);
  // The sticky group head meets the list's top edge, so no row peeks above it.
  assert.match(summaryCss, /\.sd-scope-list \{[\s\S]*?padding: 0 0 3px;/);
  // Lists scroll vertically only (design rule C16).
  assert.match(summaryCss, /\.sd-scope-list \{[\s\S]*?overflow-y: auto;\s*overflow-x: hidden;/);

  // The scope reaches the job, and the job reaches the server.
  assert.match(projectSettingsJs, /async function importSourceData\(sourceType, scope = \{\}\)/);
  assert.match(projectSettingsJs, /datasetTypes: scope\?\.datasetTypes \|\| \[\]/);
  assert.match(projectSettingsJs, /reservingClassTypes: scope\?\.reservingClassTypes \|\| \[\]/);
  assert.match(sourceTableRouter, /if req\.dataset_types:/);
  assert.match(sourceTableRouter, /if req\.reserving_class_types:/);

  // A source the server can read is imported only by the job: with no plan or
  // no Engine this PC imports nothing rather than copy it over the share.
  const importFlow = projectSettingsJs.slice(
    projectSettingsJs.indexOf("async function importSourceData("),
    projectSettingsJs.indexOf("// ============ Table Summary ============"),
  );
  assert.match(importFlow, /if \(!plan\) return \{ ok: false, error: "Could not reach Arco Server/);
  assert.match(importFlow, /if \(job\.unavailable\) \{[\s\S]*?if \(importOnServer\) \{\s*return \{\s*ok: false,/);
  assert.equal(importFlow.match(/importSourceDataLocally\(/g).length, 1, "a second local import came back");
  // A client-only source is uploaded; the page shows how far it has got.
  assert.match(projectSettingsJs, /fetch\(`\/source_table\/upload_progress\?\$\{query\}`\)/);
  assert.match(projectSettingsJs, /if \(!finished && progress\?\.active\)/);
  assert.match(sourceTableRouter, /upload_source_table\(req\.project_name, SOURCE_TYPE_MSSQL\)/);
  assert.match(sourceTableRouter, /upload_source_table\(req\.project_name, SOURCE_TYPE_CSV\)/);
  // The rebuild a client-only import still asks for runs on the server.
  assert.match(summaryRouter, /run_workspace_mutation\(\s*"table_summary_rebuild"/);
});

test("the Import Scope step opens on the project's last refresh scope, shared by every user", () => {
  const { normalizeSourceState } = sourceDataModule;
  // The record travels with the project's import state and is normalized here.
  const state = normalizeSourceState({
    source_type: "csv",
    refresh_scope: {
      dataset_types: ["Gross Loss--Paid", " ", null],
      reserving_class_types: [{ Name: "HOL", Level: 5 }, { Name: "", Level: 1 }, { Name: "NJ", Level: "x" }],
      chosen_by: "jhou",
      chosen_at: "2026-09-05T13:36:00Z",
    },
  });
  assert.deepEqual(state.refreshScope, {
    datasetTypes: ["Gross Loss--Paid"],
    reservingClassTypes: [{ name: "HOL", level: 5 }],
    chosenBy: "jhou",
    chosenAt: "2026-09-05T13:36:00Z",
  });
  assert.deepEqual(normalizeSourceState(null).refreshScope, {
    datasetTypes: [],
    reservingClassTypes: [],
    chosenBy: "",
    chosenAt: "",
  });

  // The step builds its ticks from that record and says so on the page.
  assert.match(moduleSource, /scopeState = buildScopeState\(options, sourceState\.refreshScope\)/);
  assert.match(moduleSource, /state\.restored = !!\(rememberedTypes\.length \|\| rememberedClassTypes\.length\)/);
  // A level the record did not narrow stays fully ticked.
  assert.match(moduleSource, /!narrowedLevels\.has\(item\.level\) \|\| wanted\.has\(classTypeKeyOf\(item\)\)/);
  assert.match(moduleSource, /function syncScopeRestoredNote\(\)/);
  assert.match(moduleSource, /Restored the scope chosen for the last import/);
  assert.match(projectSettingsHtml, /id="sdScopeRestored" hidden/);

  // The record is written by the Engine job that actually ran the scope, on
  // the server, so no client-side write over the share was added.
  assert.match(sourceTableService, /def record_refresh_scope\(/);
  assert.match(sourceTableService, /"refresh_scope": record\.get\("refresh_scope"\)/);
  assert.match(sourceTableContract, /"refresh_scope": normalize_refresh_scope\(data\.get\("refresh_scope"\)\)/);
});

test("SQL Server source identity replaces the file identity without a path", () => {
  assert.match(moduleSource, /export function getSourceIdentity/);
  const { getSourceIdentity, normalizeSourceState } = sourceDataModule;

  const sql = normalizeSourceState({
    source_type: "mssql",
    mssql: { server: "SQLPRD01", database: "DW", table: "dbo.Claims" },
  });
  assert.deepEqual(getSourceIdentity(sql), {
    name: "dbo.Claims",
    detail: "SQLPRD01 · DW",
    configured: true,
  });

  const emptySql = normalizeSourceState({ source_type: "mssql" });
  assert.equal(getSourceIdentity(emptySql).configured, false);
  assert.equal(getSourceIdentity(emptySql).name, "No SQL Server table");

  const csv = normalizeSourceState({ source_type: "csv", csv_path: "E:\\raw\\claims_202605.csv" });
  assert.deepEqual(getSourceIdentity(csv), {
    name: "claims_202605.csv",
    detail: "E:\\raw",
    configured: true,
  });
  assert.equal(getSourceIdentity(normalizeSourceState(null)).configured, false);
});

test("Source Data header actions carry shared ArcRho tooltips", () => {
  // aria-label alone renders no visible bubble, so each icon action must be
  // attached to the shared tooltip surface (design rule C11).
  assert.match(moduleSource, /import \{ attachArcrhoTooltip \} from "\.\.\/shared\/components\/tooltip\/tooltip\.js"/);
  assert.match(moduleSource, /function wireTooltips\(\)/);
  assert.match(moduleSource, /wireTooltips\(\);/);

  const block = moduleSource.split("function wireTooltips()")[1].split("\n  }")[0];
  for (const control of [
    "dom.infoBtn",
    "dom.reloadBtn",
    "dom.importMenuBtn",
  ]) {
    assert.ok(block.includes(control), `${control} has no tooltip`);
  }
  // Import Data shows its label, so it needs no tooltip of its own.
  assert.ok(!block.includes("dom.importSettingsBtn"), "the labelled Import Data button repeats its label as a tooltip");
  // Tooltip wording is not duplicated; it reads each control's accessible name.
  assert.match(block, /control\?\.getAttribute\("aria-label"\)/);
  // Controls inside the floating panels would sit above the shared tooltip.
  assert.ok(!block.includes("dom.openFolderBtn"), "tooltip attached inside a floating panel");
  assert.ok(!block.includes("dom.mssqlTestBtn"), "tooltip attached inside a floating panel");
});

test("a first-time user finds the import from a labelled button and a first-run panel", () => {
  // The header's entry point is a labelled button, not a gear icon.
  assert.match(
    projectSettingsHtml,
    /<button class="sd-import-cta" id="summaryImportSettingsBtn"[\s\S]*?<span>Import Data<\/span>/,
  );
  assert.ok(!projectSettingsHtml.includes('aria-label="Import settings"'), "the gear-icon entry point remains");
  // The arrow menu appears only once there is an import to repeat.
  assert.match(projectSettingsHtml, /id="summaryImportMenuBtn"[^>]*hidden>/);
  assert.match(projectSettingsHtml, /data-import-action="again"/);
  assert.match(projectSettingsHtml, /data-import-action="change"/);
  assert.match(moduleSource, /const canRepeat = !!when \|\| sourceState\.masterTableExists;/);
  assert.match(moduleSource, /if \(action === "again"\) goToScopeStep\(\);/);
  // The header names the last import.
  assert.match(projectSettingsHtml, /id="summaryImportMeta" hidden/);
  assert.match(moduleSource, /`Imported \$\{when\}/);
  // An empty project offers both methods, and each opens the window on it.
  assert.match(projectSettingsHtml, /class="sd-first-run" id="summaryFirstRun" hidden/);
  assert.match(projectSettingsHtml, /class="sd-first-run-choice" type="button" data-method="csv"/);
  assert.match(projectSettingsHtml, /class="sd-first-run-choice" type="button" data-method="mssql"/);
  assert.match(moduleSource, /openSourcePanel\(\{ method: choice\.dataset\.method \}\)/);
  assert.match(moduleSource, /function openSourcePanel\(\{ method = "" \} = \{\}\)/);
  assert.match(moduleSource, /setFirstRunVisible\(!!dom\.firstRun\);/);
  // Any summary on screen retires the first-run panel.
  assert.match(moduleSource, /function setBodyVisible\(visible\) \{\s*if \(visible\) setFirstRunVisible\(false\);/);
  // The primary action is blue-tinted, not a filled block (design rule C02).
  assert.match(summaryCss, /\.sd-import-cta \{[^}]*background: var\(--ar-color-accent-soft, #eaf2ff\);/);
  // The menu is a vertical list that never scrolls sideways (design rule C16).
  assert.match(summaryCss, /\.sd-import-menu \{[^}]*overflow-x: hidden;/);
});

test("unknown source types and auth modes fall back to the supported defaults", () => {
  const { normalizeSourceState } = sourceDataModule;
  const state = normalizeSourceState({ source_type: "oracle", mssql: { authentication: "kerberos" } });
  assert.equal(state.sourceType, "csv");
  // The UI only ever offers Windows authentication today.
  assert.equal(state.mssql.authentication, "kerberos");
  assert.match(moduleSource, /authentication: MSSQL_AUTH_WINDOWS,/);
});
