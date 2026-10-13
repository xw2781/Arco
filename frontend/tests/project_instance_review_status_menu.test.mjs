import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const tableSource = await readFile(
  new URL("../ui/project_instance/project_instance_dataset_table.js", import.meta.url),
  "utf8",
);
const pageHtml = await readFile(
  new URL("../ui/project_instance/project_instance.html", import.meta.url),
  "utf8",
);
// The module is imported from a data: URL, so the browser-only pickers are
// stubbed; the review-status codes keep their real module, because the menu's
// whole decision is about those two values.
const reviewStatusUrl = new URL("../ui/shared/dataset/review_status.js", import.meta.url).href;
const testableSource = tableSource
  .replace("/ui/shared/components/value_filter_menu/value_filter_menu.js?v=20260920a", new URL("../ui/shared/components/value_filter_menu/value_filter_menu.js?v=20260920a", import.meta.url).href)
  .replace("/ui/shared/dataset/dataset_category.js?v=20260920a", new URL("../ui/shared/dataset/dataset_category.js?v=20260920a", import.meta.url).href)
  .replace("/ui/shared/components/table_group_row/table_group_row.js?v=20261013a", new URL("../ui/shared/components/table_group_row/table_group_row.js?v=20261013a", import.meta.url).href)
  .replace(
    /^import \{ openDatasetNamePicker \} from .*;\s*/mu,
    "const openDatasetNamePicker = async () => null;\n",
  )
  .replace(
    // [^}]* rather than [\s\S]*?, so the block cannot start at an earlier
    // import and swallow this one's neighbours on its way here.
    /^import \{[^}]*\} from "\/ui\/shared\/components\/settings_file\/settings_file\.js[^"]*";\s*/mu,
    [
      "const attachSettingsFileDropZone = () => () => {};",
      "const buildSettingsFile = (payload) => payload;",
      "const openSettingsFile = async () => ({ ok: false, reason: \"no-host\" });",
      "const openSettingsFileMenu = () => null;",
      "const readSettingsFile = async () => ({});",
      "const saveSettingsFile = async () => ({ ok: false, reason: \"no-host\" });",
      "",
    ].join("\n"),
  )
  .replace(
    /^import \{ reviewStatusIconSvg \} from .*;\s*/mu,
    "const reviewStatusIconSvg = () => \"\";\n",
  )
  .replace(
    /^import \{ formatDetailsFormulaText \} from .*;\s*/mu,
    "const formatDetailsFormulaText = (value) => String(value ?? \"\");\n",
  )
  .replace('from "/ui/shared/dataset/review_status.js"', `from "${reviewStatusUrl}"`)
  .replace(
    // [^}]* rather than [\s\S]*?, so the block cannot start at an earlier
    // import and swallow the review-status one on its way here.
    /^import \{[^}]*\} from "\/ui\/shared\/dataset\/berquist_sherman_contract\.js";\s*/mu,
    [
      "const BERQUIST_SHERMAN_VARIANTS = [];",
      "const berquistShermanDisplayLabel = (value) => String(value ?? \"\");",
      "const getBerquistShermanContract = () => null;",
      "const normalizeBerquistShermanVariant = () => \"\";",
      "",
    ].join("\n"),
  );
const { installProjectInstanceDatasetTable } = await import(
  `data:text/javascript;base64,${Buffer.from(testableSource).toString("base64")}`
);

const ROW_ACTIONS = [
  "view",
  "make-permanent",
  "show-as-vector",
  "view-as-triangle",
  "mark-for-review",
  "set-reviewed",
  "add-dfm",
  "add-result-selection",
  "add-bornhuetter-ferguson",
  "add-cape-cod",
  "delete",
];

/** The one menu element the table reads, with just the surface it touches. */
function createMenu() {
  const items = new Map(
    ROW_ACTIONS.map((action) => [action, { hidden: false, disabled: false, title: "" }]),
  );
  return {
    items,
    style: {},
    classList: { add: () => {}, remove: () => {} },
    setAttribute: () => {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 180, height: 240 }),
    querySelector: (selector) => {
      const match = /\[data-row-action='([^']+)'\]/u.exec(selector);
      if (match) return items.get(match[1]) || null;
      return null;
    },
    querySelectorAll: () => [],
  };
}

function createHarness(records) {
  const menu = createMenu();
  const state = {
    selectedPath: "Direct Group/COLL",
    datasetRows: [],
    datasetTableVisibleRecords: records,
    datasetRowContextKey: "",
    datasetTablePreferenceWidthKeys: new Set(),
    datasetTableView: { filters: new Map(), collapsedGroups: new Set(), groupBy: [] },
    cachedDatasetFilter: { loading: false, loadedPath: "Direct Group/COLL", names: new Set(), instanceRows: [], metadataByName: new Map() },
    datasetTableSelection: { selectedKeys: new Set(), anchorKey: "", activeKey: "" },
    datasetIndexWatch: { pending: false, suppressUntil: 0 },
    lastDatasetSelectionStatusCount: 0,
  };
  const els = {
    datasetRowContextMenu: menu,
    datasetTableWrap: { scrollLeft: 0, scrollTop: 0 },
  };
  const calls = { statuses: [], requests: [], reloads: 0 };
  const api = {
    beginPageLoading: () => {},
    finishPageLoading: () => {},
    focusProjectInstancePage: () => {},
    focusDatasetTableSurface: () => {},
    getCachedDatasetKey: (value) => String(value || "").trim().toLowerCase(),
    hasCachedDatasetMetadataForSelectedPath: () => true,
    isDatasetRecordCached: () => true,
    isReservingClassBusy: () => false,
    isTemporaryDatasetView: () => false,
    normalizeLookupKey: (value) => String(value || "").trim().toLowerCase(),
    normalizePath: (value) => String(value || "").trim(),
    postProjectInstanceStatus: () => {},
    setStatus: (text) => calls.statuses.push(String(text ?? "")),
    shouldUseCachedDatasetFilter: () => true,
    syncCachedDatasetToolbar: () => {},
    toText: (value) => String(value ?? "").trim(),
    applyCachedDatasetSnapshot: () => {},
    captureDatasetTableScroll: () => ({
      left: els.datasetTableWrap.scrollLeft,
      top: els.datasetTableWrap.scrollTop,
    }),
    restoreDatasetTableScroll: (scrollState) => {
      els.datasetTableWrap.scrollLeft = Number(scrollState?.left) || 0;
      els.datasetTableWrap.scrollTop = Number(scrollState?.top) || 0;
    },
    // The real reload empties the rows and re-renders them, which drops the
    // highlight and sends the wrapper back to the top; the stub reproduces
    // exactly that so the restore has something to put back.
    loadCachedDatasetFilterForSelectedPath: async () => {
      calls.reloads += 1;
      els.datasetTableWrap.scrollTop = 0;
      state.datasetTableSelection.selectedKeys.clear();
      state.datasetTableSelection.anchorKey = "";
      state.datasetTableSelection.activeKey = "";
    },
  };
  installProjectInstanceDatasetTable({
    api,
    els,
    projectName: "PI review status test",
    state,
    constants: {
      DATASET_TABLE_COLUMNS: [],
      DATASET_COLUMNS: [],
      DATASET_TABLE_DEFAULT_WIDTHS: {},
      DATASET_TABLE_AUTOFIT_MAX_WIDTH: 400,
      DATASET_TABLE_AUTOFIT_CELL_EXTRA_WIDTH: 0,
      DATASET_TABLE_AUTOFIT_HEADER_EXTRA_WIDTH: 0,
      DATASET_TABLE_BLANK_LABEL: "(Blank)",
    },
    fetchProjectDatasetTypes: async () => [],
    loadProjectUserPreferences: async () => ({}),
    scheduleProjectUserPreferencesSave: () => {},
  });
  return { api, calls, els, menu, state };
}

/** One visible row, its Method Type and Status read the way the index reports them. */
function makeRecord(rowIndex, name, methodType, status) {
  return {
    rowIndex,
    datasetName: name,
    meta: { status },
    values: { name, methodType, dataFormat: "Vector", status },
  };
}

function selectAll(state, records) {
  state.datasetTableSelection.selectedKeys = new Set(records.map((_, index) => `row-${index}`));
}

globalThis.window = { innerWidth: 1600, innerHeight: 900 };

test("the menu offers marking for review only while every method row is up to date", () => {
  const records = [makeRecord(0, "G 41 - BF Paid", "Bornhuetter Ferguson", 0)];
  const { api, menu, state } = createHarness(records);
  selectAll(state, records);

  api.showDatasetRowContextMenu("row-0", 10, 10);
  assert.equal(menu.items.get("mark-for-review").hidden, false);
  assert.equal(menu.items.get("set-reviewed").hidden, true);
});

test("a flagged row offers only setting it reviewed", () => {
  const records = [makeRecord(0, "G 41 - BF Paid", "Bornhuetter Ferguson", 2)];
  const { api, menu, state } = createHarness(records);
  selectAll(state, records);

  api.showDatasetRowContextMenu("row-0", 10, 10);
  assert.equal(menu.items.get("mark-for-review").hidden, true);
  assert.equal(menu.items.get("set-reviewed").hidden, false);
});

test("a selection of mixed statuses offers setting reviewed", () => {
  const records = [
    makeRecord(0, "Flagged DFM", "DFM", 2),
    makeRecord(1, "Current DFM", "DFM", 0),
  ];
  const { api, menu, state } = createHarness(records);
  selectAll(state, records);

  api.showDatasetRowContextMenu("row-0", 10, 10);
  assert.equal(menu.items.get("mark-for-review").hidden, true, "a mixed selection never marks");
  assert.equal(menu.items.get("set-reviewed").hidden, false);
});

test("a row no method wrote shows neither item", () => {
  const records = [makeRecord(0, "Net Loss--Paid", "None", 0)];
  const { api, menu, state } = createHarness(records);
  selectAll(state, records);

  api.showDatasetRowContextMenu("row-0", 10, 10);
  assert.equal(menu.items.get("mark-for-review").hidden, true);
  assert.equal(menu.items.get("set-reviewed").hidden, true);
});

test("a method row beside a plain dataset still offers the action", () => {
  const records = [
    makeRecord(0, "Selected Ultimate", "Result Selection", 0),
    makeRecord(1, "Net Loss--Paid", "None", 0),
  ];
  const { api, menu, state } = createHarness(records);
  selectAll(state, records);

  api.showDatasetRowContextMenu("row-1", 10, 10);
  assert.equal(menu.items.get("mark-for-review").hidden, false);
  assert.equal(menu.items.get("set-reviewed").hidden, true);
});

test("the request carries only the method rows and the table reloads after it", async () => {
  const records = [
    makeRecord(0, "Selected Ultimate", "Result Selection", 0),
    makeRecord(1, "Net Loss--Paid", "None", 0),
  ];
  const { api, calls, state } = createHarness(records);
  selectAll(state, records);
  const sent = [];
  globalThis.fetch = async (url, options) => {
    sent.push({ url, body: JSON.parse(options.body) });
    return { ok: true, status: 200, json: async () => ({ ok: true, updated: ["Selected Ultimate"] }) };
  };
  try {
    await api.setDatasetRowsReviewStatus(records, true);
  } finally {
    delete globalThis.fetch;
  }
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "/datasets/review-status");
  assert.deepEqual(sent[0].body.dataset_names, ["Selected Ultimate"]);
  assert.equal(sent[0].body.status, 2);
  assert.equal(sent[0].body.reserving_class, "Direct Group/COLL");
  assert.equal(calls.reloads, 1, "the table re-reads the index the writes made stale");
  assert.equal(state.datasetIndexWatch.pending, false, "no Refresh Table prompt for our own write");
  assert.match(calls.statuses.at(-1), /Marked 1 object for review\./u);
});

test("the picked rows stay highlighted and the table stays where it was", async () => {
  const records = [
    makeRecord(0, "Selected Ultimate", "Result Selection", 0),
    makeRecord(1, "G 41 - BF Paid", "Bornhuetter Ferguson", 0),
  ];
  const { api, els, state } = createHarness(records);
  state.datasetTableSelection.selectedKeys = new Set(["row-1"]);
  state.datasetTableSelection.anchorKey = "row-1";
  state.datasetTableSelection.activeKey = "row-1";
  els.datasetTableWrap.scrollTop = 940;
  els.datasetTableWrap.scrollLeft = 120;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, updated: ["G 41 - BF Paid"] }),
  });
  try {
    await api.setDatasetRowsReviewStatus([records[1]], true);
  } finally {
    delete globalThis.fetch;
  }
  assert.deepEqual(Array.from(state.datasetTableSelection.selectedKeys), ["row-1"]);
  assert.equal(state.datasetTableSelection.activeKey, "row-1");
  assert.equal(els.datasetTableWrap.scrollTop, 940, "the reader keeps their place in the class");
  assert.equal(els.datasetTableWrap.scrollLeft, 120);
});

test("setting reviewed sends the current status code", async () => {
  const records = [makeRecord(0, "Flagged DFM", "DFM", 2)];
  const { api } = createHarness(records);
  const sent = [];
  globalThis.fetch = async (url, options) => {
    sent.push(JSON.parse(options.body));
    return { ok: true, status: 200, json: async () => ({ ok: true, updated: ["Flagged DFM"] }) };
  };
  try {
    await api.setDatasetRowsReviewStatus(records, false);
  } finally {
    delete globalThis.fetch;
  }
  assert.equal(sent[0].status, 0);
});

test("both items are in the row context menu, worded as the user asked", () => {
  assert.match(pageHtml, /data-row-action="mark-for-review" hidden>Mark For Review</u);
  assert.match(pageHtml, /data-row-action="set-reviewed" hidden>Set Reviewed</u);
});

test("graph review targets its pinned class without reloading another class's table", async () => {
  const records = [makeRecord(0, "Flagged DFM", "DFM", 2)];
  const { api, calls, state } = createHarness(records);
  const notified = [];
  api.notifyDependencyGraphWindows = path => notified.push(path);
  globalThis.fetch = async (url, options) => {
    assert.equal(JSON.parse(options.body).reserving_class, "Graph Class");
    return { ok: true, json: async () => ({ ok: true, updated: ["Flagged DFM"] }) };
  };
  try {
    const result = await api.setDatasetRowsReviewStatus(records, false, { reservingClass: "Graph Class" });
    assert.equal(result.ok, true);
  } finally { delete globalThis.fetch; }
  assert.equal(calls.reloads, 0);
  assert.equal(state.selectedPath, "Direct Group/COLL");
  assert.deepEqual(notified, ["Graph Class"]);
});

test("review failures return their message without reloading or changing selection", async () => {
  const records = [makeRecord(0, "Flagged DFM", "DFM", 2)];
  const { api, calls, state } = createHarness(records);
  selectAll(state, records);
  globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: "Gateway unavailable" }) });
  try {
    assert.deepEqual(await api.setDatasetRowsReviewStatus(records, false), { ok: false, message: "Gateway unavailable" });
  } finally { delete globalThis.fetch; }
  assert.equal(calls.reloads, 0);
  assert.deepEqual([...state.datasetTableSelection.selectedKeys], ["row-0"]);
});

test("the Project Instance status column reads the shared review-status codes", () => {
  assert.match(tableSource, /from "\/ui\/shared\/dataset\/review_status\.js"/u);
  assert.ok(
    !/function normalizeDatasetStatus/u.test(tableSource),
    "the page keeps no second reading of what the stored status means",
  );
});
