// Dashboards page: the list of dashboards, and one open dashboard with its pages, library, data
// sources, canvas and inspector. This module owns the page state and every change to it; the
// other modules draw what it hands them and call back.

import { api } from "./dashboard_api.js";
import { ASSET_DRAG_TYPE, FIELD_DRAG_TYPE, computeWidgetResult, createCanvas } from "./dashboard_canvas.js";
import { hideTooltip } from "./dashboard_charts.js";
import {
  button,
  closeGlyph,
  closeMenus,
  confirmDialog,
  el,
  icon,
  iconButton,
  multiPickField,
  openPickMenu,
  plusGlyph,
  promptDialog,
  tip,
} from "./dashboard_controls.js";
import { distinctValues, resultToRows, tableOfSource } from "./dashboard_data.js";
import { renderFieldList, renderInspector } from "./dashboard_inspector.js";
import {
  ASSISTANT_GUIDE,
  WIDGET_TYPES,
  applyDefaultFields,
  createDashboard,
  createWidget,
  findFreeCell,
  fromAssistantJson,
  newId,
  normalizeDashboard,
  normalizeWidget,
  resolveLayout,
  toAssistantJson,
} from "./dashboard_model.js";
import { openSourceDialog } from "./dashboard_sources.js";

const $ = (id) => document.getElementById(id);
const MAX_UNDO = 60;
const ASSISTANT_ROWS = 30;
const ASSISTANT_WIDGETS = 12;

const state = {
  dashboard: null,
  path: "",
  sample: false,
  dirty: false,
  mode: "view",
  pageId: "",
  selectedId: "",
  sidePanel: "library",
  cross: null,
  tables: new Map(),
  loading: new Set(),
  sourceErrors: new Map(),
  library: [],
  undo: [],
  redo: [],
  // The undo depth right after ArcBot's latest edit, so "revert" undoes that edit and no other.
  assistantUndoDepth: -1,
};

let canvas = null;

// ---------------------------------------------------------------------------
// State helpers
// ---------------------------------------------------------------------------

function currentPage() {
  const pages = state.dashboard?.pages || [];
  return pages.find((page) => page.id === state.pageId) || pages[0] || null;
}

function selectedWidget() {
  return currentPage()?.widgets.find((widget) => widget.id === state.selectedId) || null;
}

function sourceById(id) {
  return state.dashboard?.sources.find((source) => source.id === id) || null;
}

function rebuildTables() {
  state.tables = new Map();
  for (const source of state.dashboard?.sources || []) {
    if (source.extract) state.tables.set(source.id, tableOfSource(source));
  }
}

function setStatus(text, tone = "") {
  const node = $("dbStatus");
  node.textContent = text || "";
  node.classList.toggle("error", tone === "error");
}

function reportState() {
  const open = !!state.dashboard;
  window.parent?.postMessage({
    type: "arcrho:dashboard-state",
    path: open && !state.sample ? state.path : "",
    title: open ? state.dashboard.name : "Dashboards",
    dirty: open && state.dirty,
  }, "*");
}

function snapshot() {
  // Saved tables are large and never change through an edit, so a step keeps them by reference.
  const extracts = new Map(state.dashboard.sources.map((source) => [source.id, source.extract]));
  const text = JSON.stringify({ ...state.dashboard, sources: state.dashboard.sources.map(({ extract, ...rest }) => rest) });
  return { text, extracts, pageId: state.pageId, selectedId: state.selectedId };
}

function restore(step) {
  const dashboard = JSON.parse(step.text);
  for (const source of dashboard.sources) {
    if (step.extracts.get(source.id)) source.extract = step.extracts.get(source.id);
  }
  state.dashboard = dashboard;
  state.pageId = step.pageId;
  state.selectedId = step.selectedId;
  rebuildTables();
}

// Apply one change to the dashboard as a single undoable step.
function commit(change) {
  state.undo.push(snapshot());
  if (state.undo.length > MAX_UNDO) state.undo.shift();
  state.redo = [];
  change(state.dashboard);
  state.dirty = true;
  renderWorkbook();
  reportState();
}

function undo() {
  if (!state.undo.length) return false;
  state.redo.push(snapshot());
  restore(state.undo.pop());
  state.dirty = true;
  renderWorkbook();
  reportState();
  return true;
}

function redo() {
  if (!state.redo.length) return;
  state.undo.push(snapshot());
  restore(state.redo.pop());
  state.dirty = true;
  renderWorkbook();
  reportState();
}

function changeWidget(id, edit) {
  commit((dashboard) => {
    const page = dashboard.pages.find((item) => item.id === state.pageId) || dashboard.pages[0];
    const index = page.widgets.findIndex((widget) => widget.id === id);
    if (index < 0) return;
    const draft = JSON.parse(JSON.stringify(page.widgets[index]));
    edit(draft);
    page.widgets[index] = normalizeWidget(draft, page.widgets.filter((_, position) => position !== index).map((widget) => widget.id));
    page.widgets = resolveLayout(page.widgets, id);
  });
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

function filtersFor(widget, table) {
  const filters = [];
  for (const filter of currentPage()?.filters || []) {
    if (filter.values.length && table.index.has(filter.field)) filters.push(filter);
  }
  const cross = state.cross;
  if (cross && cross.widgetId !== widget.id && table.index.has(cross.field)) {
    filters.push({ field: cross.field, values: [cross.value == null ? null : String(cross.value)] });
  }
  return filters;
}

function sourceStatus(sourceId) {
  if (state.loading.has(sourceId)) return "Loading data...";
  if (state.sourceErrors.has(sourceId)) return state.sourceErrors.get(sourceId);
  return sourceById(sourceId) ? "This data source has not been loaded. Refresh it." : "Choose a data source.";
}

async function refreshSources(ids) {
  const sources = ids.map(sourceById).filter(Boolean);
  if (!sources.length) return;
  for (const source of sources) { state.loading.add(source.id); state.sourceErrors.delete(source.id); }
  $("dbCanvas").classList.add("dbStale");
  renderSidePanel();
  setStatus("Loading data...");
  let failed = 0;
  await Promise.all(sources.map(async (source) => {
    const { extract, ...definition } = source;
    try {
      const table = await api.loadSource(definition);
      const live = sourceById(source.id);
      if (live) live.extract = table;
    } catch (error) {
      failed += 1;
      state.sourceErrors.set(source.id, String(error.message || error));
    } finally {
      state.loading.delete(source.id);
    }
  }));
  rebuildTables();
  if (failed < sources.length) state.dirty = true;
  $("dbCanvas").classList.remove("dbStale");
  setStatus(failed ? `${failed} data source${failed === 1 ? "" : "s"} could not be loaded.` : "Data refreshed.", failed ? "error" : "");
  renderWorkbook();
  reportState();
}

// ---------------------------------------------------------------------------
// Gallery
// ---------------------------------------------------------------------------

function galleryCard(item) {
  const card = el("div", "dbCard");
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const head = el("div", "dbCardHead");
  head.append(icon("bar"), el("div", "dbCardName", item.name));
  card.appendChild(head);
  if (item.description) card.appendChild(el("div", "dbCardText", item.description));
  const facts = [`${item.page_count} page${item.page_count === 1 ? "" : "s"}`, `${item.widget_count} chart${item.widget_count === 1 ? "" : "s"}`];
  if (!item.sample) facts.push(new Date(item.modified).toLocaleDateString());
  card.appendChild(el("div", "dbCardFacts", facts.join(" · ")));
  if (item.projects.length) card.appendChild(el("div", "dbCardProjects", item.projects.join(", ")));
  const open = () => void openDashboard(item.path);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  if (!item.sample) {
    const remove = iconButton(closeGlyph(), "Delete dashboard", async (event) => {
      event.stopPropagation();
      if (!await confirmDialog({ title: "Delete Dashboard", message: `Delete "${item.name}"? This cannot be undone.`, confirmLabel: "Delete" })) return;
      try { await api.remove(item.path); } catch (error) { return setGalleryMessage(String(error.message || error)); }
      void showGallery();
    });
    remove.classList.add("dbCardDelete");
    card.appendChild(remove);
  }
  return card;
}

function setGalleryMessage(text) {
  $("dbGalleryMessage").textContent = text || "";
}

async function showGallery() {
  hideTooltip();
  closeMenus();
  state.dashboard = null;
  state.path = "";
  state.dirty = false;
  $("dbWorkbook").hidden = true;
  $("dbGallery").hidden = false;
  reportState();
  setGalleryMessage("");
  let listing = { dashboards: [], samples: [] };
  try {
    listing = await api.list();
  } catch (error) {
    setGalleryMessage(String(error.message || error));
  }
  const mine = $("dbMyDashboards");
  mine.replaceChildren();
  const create = el("div", "dbCard dbCardNew");
  create.tabIndex = 0;
  create.setAttribute("role", "button");
  create.append(plusGlyph(), el("div", "dbCardName", "New Dashboard"));
  create.addEventListener("click", newDashboard);
  create.addEventListener("keydown", (event) => { if (event.key === "Enter") newDashboard(); });
  mine.appendChild(create);
  for (const item of listing.dashboards) mine.appendChild(galleryCard(item));
  const samples = $("dbSamples");
  samples.replaceChildren();
  for (const item of listing.samples) samples.appendChild(galleryCard(item));
  $("dbSamplesGroup").hidden = !listing.samples.length;
}

function enterDashboard(dashboard, { path = "", sample = false, mode = "view" } = {}) {
  state.dashboard = dashboard;
  state.path = path;
  state.sample = sample;
  state.dirty = false;
  state.mode = mode;
  state.pageId = dashboard.pages[0].id;
  state.selectedId = "";
  state.cross = null;
  state.undo = [];
  state.redo = [];
  state.assistantUndoDepth = -1;
  state.sourceErrors = new Map();
  rebuildTables();
  $("dbGallery").hidden = true;
  $("dbWorkbook").hidden = false;
  setStatus("");
  renderWorkbook();
  reportState();
  const unloaded = dashboard.sources.filter((source) => !source.extract).map((source) => source.id);
  if (unloaded.length) void refreshSources(unloaded);
}

async function openDashboard(path) {
  try {
    const loaded = await api.load(path);
    enterDashboard(normalizeDashboard(loaded.data), { path: loaded.path, sample: !!loaded.sample });
  } catch (error) {
    await showGallery();
    setGalleryMessage(String(error.message || error));
  }
}

function newDashboard() {
  enterDashboard(createDashboard(), { mode: "edit" });
}

async function leaveDashboard() {
  if (state.dirty && !await confirmDialog({ title: "Unsaved Changes", message: "Changes to this dashboard have not been saved.", confirmLabel: "Discard" })) return;
  void showGallery();
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

async function save({ saveAs = false } = {}) {
  if (!state.dashboard) return;
  let name = state.dashboard.name;
  const needsName = saveAs || state.sample || !state.path;
  if (needsName) {
    name = await promptDialog({ title: saveAs ? "Save Dashboard As" : "Save Dashboard", label: "Name", value: name, confirmLabel: "Save" });
    if (!name) return;
  }
  // A sample and a Save As both write a new file and leave the one that was opened alone.
  const previous = saveAs || state.sample ? "" : state.path;
  const data = { ...state.dashboard, name };
  let saved = null;
  try {
    saved = await api.save(name, data, previous);
  } catch (error) {
    const message = String(error.message || error);
    if (!message.includes("already exists")) return setStatus(message, "error");
    if (!await confirmDialog({ title: "Replace Dashboard", message: `${message} Replace it?`, confirmLabel: "Replace" })) return;
    try { saved = await api.save(name, data, previous, true); } catch (retryError) { return setStatus(String(retryError.message || retryError), "error"); }
  }
  state.dashboard.name = saved.name;
  state.path = saved.path;
  state.sample = false;
  state.dirty = false;
  setStatus(`Saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
  renderTopbar();
  reportState();
}

// ---------------------------------------------------------------------------
// Widgets
// ---------------------------------------------------------------------------

function addWidget(template, type, cell = null) {
  const page = currentPage();
  if (!page) return;
  let widget = createWidget(type, page.widgets.map((item) => item.id), template);
  const source = sourceById(widget.source) || state.dashboard.sources[0] || null;
  widget = applyDefaultFields({ ...widget, source: source?.id || "" }, source);
  // A comparison template names only its field; the two ends are the field's first and last values.
  const compareField = template?.compare?.field;
  const table = source ? state.tables.get(source.id) : null;
  if (compareField && !widget.compare && table?.index.has(compareField)) {
    const values = distinctValues(table, compareField).map(String);
    if (values.length > 1) widget.compare = { field: compareField, base: values[0], target: values[values.length - 1], mode: template.compare.mode === "percent" ? "percent" : "delta" };
  }
  const spot = cell
    ? { x: Math.max(0, Math.min(12 - widget.layout.w, cell.x)), y: cell.y }
    : findFreeCell(page.widgets, widget.layout.w, widget.layout.h);
  widget.layout = { ...widget.layout, ...spot };
  commit((dashboard) => {
    const target = dashboard.pages.find((item) => item.id === page.id);
    target.widgets = resolveLayout([...target.widgets, widget], widget.id);
    state.selectedId = widget.id;
  });
}

function addAsset(assetId, cell = null) {
  const asset = state.library.find((item) => item.id === assetId);
  if (asset) addWidget(asset.widget, asset.widget.type, cell);
}

function dropField(widgetId, { source, field, role }) {
  changeWidget(widgetId, (draft) => {
    const spec = WIDGET_TYPES[draft.type];
    if (draft.type === "text") return;
    if (draft.source !== source) Object.assign(draft, { source, category: "", series: "", measures: [], filters: [], compare: undefined });
    if (role === "measure") {
      const column = state.tables.get(source)?.columns.find((item) => item.name === field);
      const measure = { field, agg: column?.default_aggregation || "sum" };
      if (draft.measures.length >= spec.maxMeasures) draft.measures[draft.measures.length - 1] = measure;
      else draft.measures.push(measure);
    } else if (!draft.category || !spec.series) {
      draft.category = field;
    } else {
      draft.series = field;
    }
  });
  state.selectedId = widgetId;
}

async function widgetAction(id, action) {
  const widget = currentPage()?.widgets.find((item) => item.id === id);
  if (!widget) return;
  if (action === "table") return changeWidget(id, (draft) => { draft.options = { ...draft.options, table: !draft.options?.table }; });
  if (action === "ask") return askAssistant(`Explain the "${widget.title || WIDGET_TYPES[widget.type].label}" chart on this dashboard page: what it shows, the main drivers, and anything unusual.`);
  if (action === "delete") {
    return commit((dashboard) => {
      const page = dashboard.pages.find((item) => item.id === state.pageId);
      page.widgets = resolveLayout(page.widgets.filter((item) => item.id !== id));
      if (state.selectedId === id) state.selectedId = "";
    });
  }
  if (action === "duplicate") return addWidget({ ...widget, title: widget.title }, widget.type);
  if (action === "library") {
    const name = await promptDialog({ title: "Save to Library", label: "Name", value: widget.title || WIDGET_TYPES[widget.type].label, confirmLabel: "Save" });
    if (!name) return;
    const { id: _id, layout, ...template } = widget;
    try {
      await api.saveAsset(name, { ...template, layout: { w: layout.w, h: layout.h } });
      await loadLibrary();
      state.sidePanel = "library";
      renderSidePanel();
      setStatus(`"${name}" was added to your library.`);
    } catch (error) {
      setStatus(String(error.message || error), "error");
    }
  }
}

function crossFilter(widget, field, value) {
  const same = state.cross && state.cross.field === field && String(state.cross.value) === String(value);
  state.cross = same ? null : { field, value, widgetId: widget.id };
  renderFilterBar();
  canvas.render();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderTopbar() {
  $("dbName").textContent = state.dashboard.name;
  $("dbSampleChip").hidden = !state.sample;
  $("dbDirtyChip").hidden = !state.dirty;
  $("dbModeView").classList.toggle("active", state.mode === "view");
  $("dbModeEdit").classList.toggle("active", state.mode === "edit");
  $("dbUndo").disabled = !state.undo.length;
  $("dbRedo").disabled = !state.redo.length;
  $("dbUndo").hidden = $("dbRedo").hidden = state.mode !== "edit";
}

function renderPages() {
  const bar = $("dbPages");
  bar.replaceChildren();
  const editing = state.mode === "edit";
  for (const page of state.dashboard.pages) {
    const tab = el("button", page.id === currentPage().id ? "dbPageTab active" : "dbPageTab", page.name);
    tab.type = "button";
    tab.addEventListener("click", () => {
      if (page.id !== state.pageId) {
        state.pageId = page.id;
        state.selectedId = "";
        state.cross = null;
        renderWorkbook();
      } else if (editing) {
        openPickMenu(tab, {
          options: [{ value: "rename", label: "Rename" }, ...(state.dashboard.pages.length > 1 ? [{ value: "delete", label: "Delete Page" }] : [])],
          selected: new Set(),
          onPick: (action) => void pageAction(page, action),
        });
      }
    });
    bar.appendChild(tab);
  }
  if (editing) {
    bar.appendChild(iconButton(plusGlyph(), "Add page", () => commit((dashboard) => {
      const id = newId("p", dashboard.pages.map((page) => page.id));
      dashboard.pages.push({ id, name: `Page ${dashboard.pages.length + 1}`, filters: [], widgets: [] });
      state.pageId = id;
      state.selectedId = "";
    })));
  }
}

async function pageAction(page, action) {
  if (action === "rename") {
    const name = await promptDialog({ title: "Rename Page", label: "Name", value: page.name, confirmLabel: "Rename" });
    if (name) commit((dashboard) => { dashboard.pages.find((item) => item.id === page.id).name = name; });
  } else if (action === "delete") {
    commit((dashboard) => {
      dashboard.pages = dashboard.pages.filter((item) => item.id !== page.id);
      state.pageId = dashboard.pages[0].id;
      state.selectedId = "";
    });
  }
}

function filterValues(field) {
  const seen = new Map();
  for (const table of state.tables.values()) {
    for (const value of distinctValues(table, field)) if (!seen.has(String(value))) seen.set(String(value), value);
  }
  return [...seen.keys()];
}

function dimensionFields() {
  const names = [];
  for (const table of state.tables.values()) {
    for (const column of table.columns) if (column.role !== "measure" && !names.includes(column.name)) names.push(column.name);
  }
  return names;
}

function renderFilterBar() {
  const bar = $("dbFilterBar");
  bar.replaceChildren();
  const page = currentPage();
  const editing = state.mode === "edit";
  page.filters.forEach((filter, index) => {
    const item = el("div", "dbFilter");
    item.appendChild(el("span", "dbFilterLabel", filter.label || filter.field));
    item.appendChild(multiPickField({
      options: filterValues(filter.field).map((value) => ({ value, label: value })),
      values: filter.values.map(String),
      onChange: (values) => {
        // Choosing filter values is using the dashboard, not editing it, so it is not an undo step.
        page.filters[index].values = values;
        state.dirty = true;
        renderTopbar();
        reportState();
        canvas.render();
      },
    }));
    if (editing) item.appendChild(iconButton(closeGlyph(), "Remove filter", () => commit((dashboard) => {
      dashboard.pages.find((entry) => entry.id === page.id).filters.splice(index, 1);
    })));
    bar.appendChild(item);
  });
  if (state.cross) {
    const chip = el("button", "dbChip");
    chip.type = "button";
    chip.append(el("span", "", `${state.cross.field}: ${state.cross.value ?? "(Blank)"}`), closeGlyph());
    chip.addEventListener("click", () => { state.cross = null; renderFilterBar(); canvas.render(); });
    bar.appendChild(chip);
  }
  if (editing) {
    const add = button("Filter", { small: true });
    add.prepend(plusGlyph());
    add.addEventListener("click", () => openPickMenu(add, {
      options: dimensionFields().filter((name) => !page.filters.some((filter) => filter.field === name)).map((name) => ({ value: name, label: name })),
      selected: new Set(),
      search: true,
      emptyText: "Add a data source first",
      onPick: (field) => commit((dashboard) => { dashboard.pages.find((entry) => entry.id === page.id).filters.push({ field, values: [] }); }),
    }));
    bar.appendChild(add);
  }
  bar.hidden = !bar.children.length;
}

function renderLibrary(host) {
  const groups = new Map();
  for (const asset of state.library) {
    if (!groups.has(asset.category)) groups.set(asset.category, []);
    groups.get(asset.category).push(asset);
  }
  for (const [category, assets] of groups) {
    host.appendChild(el("div", "dbSectionLabel", category));
    for (const asset of assets) {
      const row = el("div", "dbAsset");
      row.draggable = true;
      row.tabIndex = 0;
      tip(row, asset.description);
      row.append(icon(asset.widget.type), el("span", "dbAssetName", asset.name));
      row.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData(ASSET_DRAG_TYPE, asset.id);
        event.dataTransfer.effectAllowed = "copy";
      });
      row.addEventListener("click", () => addAsset(asset.id));
      row.addEventListener("keydown", (event) => { if (event.key === "Enter") addAsset(asset.id); });
      if (!asset.builtin) {
        row.appendChild(iconButton(closeGlyph(), "Remove from library", async (event) => {
          event.stopPropagation();
          try { await api.deleteAsset(asset.id); await loadLibrary(); renderSidePanel(); } catch (error) { setStatus(String(error.message || error), "error"); }
        }));
      }
      host.appendChild(row);
    }
  }
}

function sourceSummary(source) {
  const table = source.extract;
  if (state.loading.has(source.id)) return "Loading...";
  if (state.sourceErrors.has(source.id)) return state.sourceErrors.get(source.id);
  if (!table) return "Not loaded";
  const when = table.refreshed_at ? new Date(table.refreshed_at).toLocaleDateString() : "";
  return [`${(table.row_count || table.rows.length).toLocaleString()} rows`, when].filter(Boolean).join(" · ");
}

async function editSource(source = null) {
  const names = state.dashboard.sources.filter((item) => item.id !== source?.id).map((item) => item.name);
  const result = await openSourceDialog({ source, existingNames: names });
  if (!result) return;
  commit((dashboard) => {
    if (source) {
      const index = dashboard.sources.findIndex((item) => item.id === source.id);
      dashboard.sources[index] = { ...result, id: source.id };
    } else {
      dashboard.sources.push({ ...result, id: newId("src", dashboard.sources.map((item) => item.id)) });
    }
    state.sourceErrors.delete(source?.id);
    rebuildTables();
  });
}

function renderSources(host) {
  for (const source of state.dashboard.sources) {
    const block = el("div", "dbSource");
    const head = el("div", "dbSourceHead");
    head.append(icon("source"), el("span", "dbSourceName", source.name));
    const menu = el("button", "dbBtn small", "Options");
    menu.type = "button";
    menu.addEventListener("click", () => openPickMenu(menu, {
      options: [{ value: "refresh", label: "Refresh Data" }, { value: "edit", label: "Edit" }, { value: "remove", label: "Remove" }],
      selected: new Set(),
      onPick: async (action) => {
        if (action === "refresh") return void refreshSources([source.id]);
        if (action === "edit") return void editSource(source);
        const used = state.dashboard.pages.some((page) => page.widgets.some((widget) => widget.source === source.id));
        if (used && !await confirmDialog({ title: "Remove Data Source", message: `Charts using "${source.name}" will have no data.`, confirmLabel: "Remove" })) return;
        commit((dashboard) => { dashboard.sources = dashboard.sources.filter((item) => item.id !== source.id); rebuildTables(); });
      },
    }));
    head.appendChild(menu);
    block.appendChild(head);
    const summary = el("div", state.sourceErrors.has(source.id) ? "dbSourceFacts error" : "dbSourceFacts", sourceSummary(source));
    block.appendChild(summary);
    renderFieldList(block, source, state.tables.get(source.id), FIELD_DRAG_TYPE);
    host.appendChild(block);
  }
  const add = button("Add Data Source", { primary: true, onClick: () => void editSource() });
  add.classList.add("dbWide");
  host.appendChild(add);
}

function renderSidePanel() {
  const editing = state.mode === "edit";
  $("dbLeft").hidden = !editing;
  $("dbRight").hidden = !editing;
  if (!editing) return;
  $("dbTabLibrary").classList.toggle("active", state.sidePanel === "library");
  $("dbTabData").classList.toggle("active", state.sidePanel === "data");
  const host = $("dbLeftBody");
  host.replaceChildren();
  if (state.sidePanel === "library") renderLibrary(host);
  else renderSources(host);
  renderInspector($("dbRight"), {
    dashboard: state.dashboard,
    widget: selectedWidget(),
    tables: state.tables,
    change: (edit) => changeWidget(state.selectedId, edit),
  });
}

function renderWorkbook() {
  if (!state.dashboard) return;
  if (!currentPage()) state.pageId = state.dashboard.pages[0].id;
  renderTopbar();
  renderPages();
  renderFilterBar();
  renderSidePanel();
  canvas.render();
}

function setMode(mode) {
  if (state.mode === mode) return;
  state.mode = mode;
  state.cross = null;
  if (mode === "view") state.selectedId = "";
  renderWorkbook();
}

async function loadLibrary() {
  try {
    state.library = (await api.library()).assets || [];
  } catch (error) {
    state.library = [];
    setStatus(String(error.message || error), "error");
  }
}

// ---------------------------------------------------------------------------
// ArcBot
// ---------------------------------------------------------------------------

function askAssistant(prompt) {
  window.parent?.postMessage({ type: "arcrho:assistant-ask", prompt }, "*");
}

function assistantTargetPath() {
  return state.path || `${state.dashboard.name}.arcdash`;
}

// What ArcBot is told about the open dashboard: the document it may edit, how to edit it, and
// the numbers each chart on the current page is showing.
function assistantContext() {
  if (!state.dashboard) return { available: false, pageType: "dashboard", title: "Dashboards" };
  const page = currentPage();
  const widgets = [];
  for (const widget of page.widgets.slice(0, ASSISTANT_WIDGETS)) {
    const table = state.tables.get(widget.source);
    if (widget.type === "text" || !table) continue;
    const result = computeWidgetResult(table, widget, filtersFor(widget, table));
    const rows = resultToRows(result);
    const entry = { id: widget.id, title: widget.title, type: widget.type, columns: rows.header, rows: rows.rows.slice(0, ASSISTANT_ROWS) };
    if (result?.kpi) entry.value = result.kpi.value;
    if (result?.error) entry.error = result.error;
    if (rows.rows.length > ASSISTANT_ROWS) entry.more_rows = rows.rows.length - ASSISTANT_ROWS;
    widgets.push(entry);
  }
  const project = state.dashboard.sources.flatMap((source) => source.projects || [])[0]?.name || "";
  return {
    available: true,
    pageType: "dashboard",
    title: state.dashboard.name,
    targetPath: assistantTargetPath(),
    dirty: state.dirty,
    fields: project ? { project } : {},
    assistantGuide: ASSISTANT_GUIDE,
    activeJson: toAssistantJson(state.dashboard),
    dashboardPage: {
      name: page.name,
      filters: page.filters.filter((filter) => filter.values.length),
      charts: widgets,
    },
  };
}

function applyAssistantEdit(msg) {
  const reply = (payload) => window.parent?.postMessage({ type: `${msg.type}-result`, requestId: msg.requestId || "", ...payload }, "*");
  if (!state.dashboard || (msg.targetPath && msg.targetPath !== assistantTargetPath())) {
    return reply({ ok: false, error: "The dashboard ArcBot worked on is no longer open. Nothing was changed." });
  }
  if (msg.type.endsWith("revert-json-edit")) {
    if (state.assistantUndoDepth !== state.undo.length) {
      return reply({ ok: false, error: "The dashboard changed after ArcBot's edit, so nothing was reverted. Use Undo to step back through it." });
    }
    undo();
    state.assistantUndoDepth = -1;
    return reply({ ok: true, message: "Reverted the latest ArcBot edit." });
  }
  let edited = msg.proposedJson;
  if (!edited && msg.proposedText) {
    try { edited = JSON.parse(msg.proposedText); } catch { edited = null; }
  }
  if (!edited || edited.format !== "arco-dashboard" || !Array.isArray(edited.pages)) {
    return reply({ ok: false, error: "ArcBot did not return a dashboard. Nothing was changed." });
  }
  const next = fromAssistantJson(edited, state.dashboard);
  commit(() => {
    state.dashboard = next;
    if (!next.pages.some((page) => page.id === state.pageId)) state.pageId = next.pages[0].id;
    state.selectedId = "";
    rebuildTables();
  });
  state.assistantUndoDepth = state.undo.length;
  if (state.mode !== "edit") setMode("edit");
  const unloaded = next.sources.filter((source) => !source.extract).map((source) => source.id);
  if (unloaded.length) void refreshSources(unloaded);
  reply({ ok: true, message: "The dashboard was updated. Save it to keep the change." });
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function isTyping(target) {
  return !!target?.closest?.("input, textarea, [contenteditable='true']");
}

function init() {
  canvas = createCanvas({
    host: $("dbCanvas"),
    getView: () => ({
      page: currentPage(),
      mode: state.mode,
      selectedId: state.selectedId,
      tables: state.tables,
      filtersFor,
      sourceStatus,
    }),
    handlers: {
      onSelect: (id) => { if (state.mode === "edit" && state.selectedId !== id) { state.selectedId = id; renderSidePanel(); canvas.render(); } },
      onLayout: (id, layout) => changeWidget(id, (draft) => { draft.layout = layout; }),
      onAction: (id, action) => void widgetAction(id, action),
      onCrossFilter: crossFilter,
      onDropAsset: addAsset,
      onDropField: dropField,
    },
  });

  $("dbBack").addEventListener("click", () => void leaveDashboard());
  $("dbModeView").addEventListener("click", () => setMode("view"));
  $("dbModeEdit").addEventListener("click", () => setMode("edit"));
  $("dbRefresh").addEventListener("click", () => void refreshSources(state.dashboard.sources.map((source) => source.id)));
  $("dbAsk").addEventListener("click", () => askAssistant(`Summarize what the "${currentPage().name}" page of this dashboard shows, and call out anything unusual.`));
  $("dbUndo").addEventListener("click", undo);
  $("dbRedo").addEventListener("click", redo);
  $("dbSave").addEventListener("click", () => void save());
  $("dbMore").addEventListener("click", () => openPickMenu($("dbMore"), {
    options: [{ value: "saveAs", label: "Save As..." }, { value: "rename", label: "Rename" }, { value: "describe", label: "Edit Description" }],
    selected: new Set(),
    onPick: async (action) => {
      if (action === "saveAs") return void save({ saveAs: true });
      const describing = action === "describe";
      const value = await promptDialog({
        title: describing ? "Dashboard Description" : "Rename Dashboard",
        label: describing ? "Description" : "Name",
        value: describing ? state.dashboard.description : state.dashboard.name,
      });
      if (value) commit((dashboard) => { if (describing) dashboard.description = value; else dashboard.name = value; });
    },
  }));
  $("dbTabLibrary").addEventListener("click", () => { state.sidePanel = "library"; renderSidePanel(); });
  $("dbTabData").addEventListener("click", () => { state.sidePanel = "data"; renderSidePanel(); });

  window.addEventListener("message", (event) => {
    const msg = event.data || {};
    if (msg.type === "arcrho:dashboard-save") return void save();
    if (msg.type === "arcrho:dashboard-save-as") return void save({ saveAs: true });
    if (msg.type === "arcrho:assistant-context-request") {
      window.parent?.postMessage({ type: "arcrho:assistant-context-result", requestId: msg.requestId || "", context: assistantContext() }, "*");
      return;
    }
    if (msg.type === "arcrho:assistant-apply-json-edit" || msg.type === "arcrho:assistant-revert-json-edit") applyAssistantEdit(msg);
  });

  window.addEventListener("keydown", (event) => {
    if (!state.dashboard) return;
    const key = event.key.toLowerCase();
    const command = event.ctrlKey || event.metaKey;
    if (command && key === "s") { event.preventDefault(); return void save({ saveAs: event.shiftKey }); }
    if (isTyping(event.target) || state.mode !== "edit") return;
    if (command && key === "z" && !event.shiftKey) { event.preventDefault(); undo(); }
    else if (command && (key === "y" || (key === "z" && event.shiftKey))) { event.preventDefault(); redo(); }
    else if (key === "delete" && state.selectedId && (event.target === document.body || event.target.closest?.("#dbCanvas"))) { event.preventDefault(); void widgetAction(state.selectedId, "delete"); }
    else if (key === "escape" && state.selectedId) { state.selectedId = ""; renderSidePanel(); canvas.render(); }
  });

  void loadLibrary().then(() => { if (state.dashboard) renderSidePanel(); });
  const path = new URLSearchParams(window.location.search).get("path") || "";
  if (path) void openDashboard(path);
  else void showGallery();
}

init();
