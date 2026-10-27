import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const skeleton = await import(
  new URL("../ui/project_settings/project_settings_skeleton.js", import.meta.url)
);
const {
  SKELETON_BAR_CLASS,
  SKELETON_ROW_CLASS,
  SKELETON_ROW_COUNT,
  clearTableSkeletonRows,
  renderTableSkeletonRows,
} = skeleton;

const read = async (relativePath) => readFile(
  new URL(relativePath, import.meta.url),
  "utf8",
);

const projectSettingsHtml = await read("../ui/project_settings/project_settings.html");
const projectSettingsJs = await read("../ui/project_settings/project_settings.js");
const projectSettingsCss = await read("../ui/project_settings/project_settings.css");
const skeletonCss = await read("../ui/project_settings/project_settings_skeleton.css");
const reservingClassTypesJs = await read(
  "../ui/project_settings/project_settings_reserving_class_types.js",
);
const datasetTypesJs = await read("../ui/project_settings/project_settings_dataset_types.js");
const dataProcessingRulesJs = await read(
  "../ui/project_settings/project_settings_data_processing_rules.js",
);
const auditJs = await read("../ui/project_settings/project_settings_audit.js");

// Minimal element/document stubs: the module only needs element creation,
// parent/child links, a class bag, attributes, and two fixed selectors.
function createElement(tag) {
  return {
    tagName: String(tag).toUpperCase(),
    className: "",
    children: [],
    attributes: {},
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name)
        ? this.attributes[name]
        : null;
    },
    set innerHTML(value) {
      if (String(value) === "") this.children = [];
    },
    get innerHTML() {
      return "";
    },
  };
}

/** A table whose header and colgroup counts are supplied by the test. */
function createTableStub({ headerCells = 0, colCount = 0 } = {}) {
  const table = createElement("table");
  const tbody = createElement("tbody");
  table.querySelectorAll = (selector) => {
    if (selector === "thead tr:last-child th") {
      return Array.from({ length: headerCells }, () => createElement("th"));
    }
    if (selector === "colgroup col") {
      return Array.from({ length: colCount }, () => createElement("col"));
    }
    return [];
  };
  tbody.closest = (selector) => (selector === "table" ? table : null);
  return { table, tbody };
}

const originalDocument = globalThis.document;
globalThis.document = { createElement };
test.after(() => {
  globalThis.document = originalDocument;
});

test("a table skeleton fills the rendered grid and marks the table busy", () => {
  const { table, tbody } = createTableStub({ headerCells: 5, colCount: 5 });
  renderTableSkeletonRows(tbody, { columns: 2 });

  assert.equal(tbody.children.length, SKELETON_ROW_COUNT);
  assert.equal(table.getAttribute("aria-busy"), "true");
  for (const row of tbody.children) {
    assert.equal(row.className, SKELETON_ROW_CLASS);
    // The placeholder is decoration; the status line carries the real message.
    assert.equal(row.getAttribute("aria-hidden"), "true");
    // The live header wins over the caller's hint, so a tab that rebuilds its
    // own columns cannot render a placeholder of the wrong width.
    assert.equal(row.children.length, 5);
    for (const cell of row.children) {
      assert.equal(cell.tagName, "TD");
      assert.equal(cell.children.length, 1);
      assert.equal(cell.children[0].className, SKELETON_BAR_CLASS);
    }
  }

  clearTableSkeletonRows(tbody);
  assert.equal(table.getAttribute("aria-busy"), "false");
});

test("the skeleton column count falls back from header to colgroup to caller", () => {
  const withColgroup = createTableStub({ headerCells: 0, colCount: 3 });
  renderTableSkeletonRows(withColgroup.tbody);
  assert.equal(withColgroup.tbody.children[0].children.length, 3);

  const bare = createTableStub({ headerCells: 0, colCount: 0 });
  renderTableSkeletonRows(bare.tbody, { columns: 4, rows: 2 });
  assert.equal(bare.tbody.children.length, 2);
  assert.equal(bare.tbody.children[0].children.length, 4);

  // A missing body is a no-op rather than a thrown error mid-render.
  assert.doesNotThrow(() => renderTableSkeletonRows(null));
  assert.doesNotThrow(() => clearTableSkeletonRows(null));
});

test("every Project Settings tab shows the shared skeleton while it loads", () => {
  const owners = [
    ["reserving class types", reservingClassTypesJs, "function renderReservingClassTypesLoading()"],
    ["dataset types", datasetTypesJs, "function renderDatasetTypesLoading()"],
    ["data processing rules", dataProcessingRulesJs, "function renderLoading()"],
    ["audit log", auditJs, "renderLoading()"],
  ];
  for (const [label, source, marker] of owners) {
    assert.ok(source.includes(marker), `${label} has no loading renderer`);
    assert.match(
      source,
      /from "\.\/project_settings_skeleton\.js\?v=/,
      `${label} does not use the shared skeleton`,
    );
    assert.ok(
      source.includes("clearTableSkeletonRows("),
      `${label} never drops the busy flag`,
    );
  }

  // Selecting a project puts every tab into the same busy state, so none of
  // them is left showing a plain "Loading ..." row.
  const clearBlock = projectSettingsJs
    .split("function clearProjectDetailPanels(project) {")[1]
    .split("\nasync function selectProject(")[0];
  for (const call of [
    "sourceDataFeature.resetForProjectChange()",
    "reservingClassTypesFeature?.renderReservingClassTypesLoading()",
    "datasetTypesFeature?.renderDatasetTypesLoading()",
    "dataProcessingRulesFeature?.renderRulesLoading()",
    "auditLogStore.renderLoading()",
  ]) {
    assert.ok(clearBlock.includes(call), `clearProjectDetailPanels is missing ${call}`);
  }
  assert.doesNotMatch(clearBlock, /renderEmpty\("Loading|Empty\("Loading/);
});

test("the skeleton stylesheet owns the flowing fill for the whole page", () => {
  assert.match(
    projectSettingsHtml,
    /<link rel="stylesheet" href="\/ui\/project_settings\/project_settings_skeleton\.css\?v=/,
  );
  assert.match(skeletonCss, /\.project-settings-page \{[\s\S]*?--ps-skeleton-fill:/);
  assert.match(skeletonCss, /\.ps-skeleton-row > td > \.ps-skeleton-bar \{ width: \d+%; \}/);
  // Placeholder rows are not pointer targets, which is also what keeps every
  // themed row-hover rule from lighting them up.
  assert.match(skeletonCss, /\.ps-skeleton-row \{[\s\S]*?pointer-events: none;/);
  assert.doesNotMatch(projectSettingsCss, /ps-skeleton/);
});
