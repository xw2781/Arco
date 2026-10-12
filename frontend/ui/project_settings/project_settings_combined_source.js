/**
 * Source Data - combined source (several tables joined into one source).
 *
 * Owns the combined state of the Import Settings window: the tables in join
 * order, their nicknames, the shared keys, the row rules, left-out columns and
 * renames, and their serialization to and from the `combined` block of
 * `source_import.json` (decision 3 of docs/plans/combined_source_import.md).
 *
 * With one table the window is today's single-table form and this module only
 * adds the Add Table button. Adding a second table turns the form into the
 * grouped table list; removing tables back to one returns to the form with
 * that table's settings. Each table opens a details window (nickname, source,
 * columns) over the import window.
 *
 * The pure functions above `createCombinedSourceFeature` hold every rule so
 * they can be tested without a DOM. The feature is mounted by
 * project_settings_source_data.js, which injects every app-server call.
 */

export const SOURCE_TYPE_CSV = "csv";
export const SOURCE_TYPE_MSSQL = "mssql";
export const MSSQL_AUTH_WINDOWS = "windows";
export const NICKNAME_MAX_LENGTH = 24;
export const TABLE_COLOR_COUNT = 6;
export const ROW_RULE_ALL = "all";

const defaultEscape = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[ch]));

const clone = (value) => JSON.parse(JSON.stringify(value));

/** Comparison form of a column name: case, spaces and underscores ignored. */
export function nameToken(name) {
  return String(name ?? "").replace(/[\s_]+/g, "").toLowerCase();
}

/** One table's source in its canonical shape (CSV path, or a SQL Server profile). */
export function normalizeTableSpec(spec) {
  const data = spec && typeof spec === "object" ? spec : {};
  if (String(data.source_type || "").toLowerCase() === SOURCE_TYPE_MSSQL) {
    const mssql = data.mssql && typeof data.mssql === "object" ? data.mssql : {};
    return {
      source_type: SOURCE_TYPE_MSSQL,
      mssql: {
        server: String(mssql.server || "").trim(),
        database: String(mssql.database || "").trim(),
        table: String(mssql.table || "").trim(),
        authentication: MSSQL_AUTH_WINDOWS,
      },
    };
  }
  return { source_type: SOURCE_TYPE_CSV, csv_path: String(data.csv_path || "").trim() };
}

/** The first thing missing from a table's source, or "" when it is complete. */
export function tableSpecProblem(spec) {
  const table = normalizeTableSpec(spec);
  if (table.source_type === SOURCE_TYPE_MSSQL) {
    if (!table.mssql.server || !table.mssql.database) return "Enter the server and database name first.";
    if (!table.mssql.table) return "Select a table or view to import.";
    return "";
  }
  return table.csv_path ? "" : "Choose a CSV file to import.";
}

export function sameTableSpec(a, b) {
  const x = normalizeTableSpec(a);
  const y = normalizeTableSpec(b);
  if (x.source_type !== y.source_type) return false;
  if (x.source_type === SOURCE_TYPE_CSV) return x.csv_path.toLowerCase() === y.csv_path.toLowerCase();
  return ["server", "database", "table"].every(
    (field) => x.mssql[field].toLowerCase() === y.mssql[field].toLowerCase(),
  );
}

export function sameConnection(a, b) {
  return a?.source_type === SOURCE_TYPE_MSSQL && b?.source_type === SOURCE_TYPE_MSSQL
    && String(a.mssql?.server || "").toLowerCase() === String(b.mssql?.server || "").toLowerCase()
    && String(a.mssql?.database || "").toLowerCase() === String(b.mssql?.database || "").toLowerCase();
}

/** The table's own name: the SQL table, or the CSV file name. */
export function tableSourceName(table) {
  if (table?.source_type === SOURCE_TYPE_MSSQL) return String(table.mssql?.table || "").trim();
  const raw = String(table?.csv_path || "").trim();
  const idx = Math.max(raw.lastIndexOf("\\"), raw.lastIndexOf("/"));
  return idx < 0 ? raw : raw.slice(idx + 1);
}

/** What the window calls a table: its nickname, or its own name when blank (decision 7). */
export function tableLabel(table) {
  return String(table?.nickname || "").trim() || tableSourceName(table);
}

export function tableKindText(table) {
  return table?.source_type === SOURCE_TYPE_MSSQL ? "SQL table" : "CSV file";
}

function nameStem(table) {
  const name = tableSourceName(table);
  if (table?.source_type === SOURCE_TYPE_MSSQL) {
    const parts = name.split(".");
    return parts[parts.length - 1].replace(/^\[|\]$/g, "");
  }
  return name.replace(/\.[^.]+$/, "");
}

function stemTokens(table) {
  return nameStem(table).split(/[\s_\-.]+/).filter((token) => token && !/^\d+$/.test(token));
}

/**
 * A short nickname suggested when a table is added: its name without schema,
 * extension, pure numbers, and the words every other table's name shares.
 */
export function suggestNickname(table, others = []) {
  const tokens = stemTokens(table);
  const otherSets = others.map((other) => new Set(stemTokens(other).map((t) => t.toLowerCase())));
  const shared = (token) => otherSets.length > 0 && otherSets.every((set) => set.has(token.toLowerCase()));
  const kept = tokens.filter((token) => !shared(token));
  const words = kept.length ? kept : tokens;
  const text = words.length ? words.join(" ") : nameStem(table);
  return text.slice(0, NICKNAME_MAX_LENGTH).trim();
}

export function createCombinedState() {
  return { tables: [], keys: [], rows: {}, exclude: {}, rename: {} };
}

function nextTableId(state) {
  const used = state.tables.map((table) => Number(/^t(\d+)$/.exec(table.id)?.[1] || 0));
  return `t${Math.max(0, ...used) + 1}`;
}

function freeColor(state) {
  const used = new Set(state.tables.map((table) => table.color));
  for (let i = 0; i < TABLE_COLOR_COUNT; i += 1) if (!used.has(i)) return i;
  return state.tables.length % TABLE_COLOR_COUNT;
}

/**
 * How a key is matched in a table: its column with the same name token, else
 * a fill for a month-like key (the notebook's `sys_yrmo = 0`), else any value.
 */
export function autoMapKey(table, keyName) {
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const column = columns.find((name) => nameToken(name) === nameToken(keyName));
  if (column !== undefined) return { column };
  return /yrmo/i.test(keyName) ? { fill: "0" } : { any: true };
}

/**
 * Propose the keys (decision 5): every base column whose name, ignoring case,
 * spaces and underscores, appears in at least one other table.
 */
export function detectKeys(state) {
  const base = state.tables[0];
  const others = state.tables.slice(1).filter((table) => Array.isArray(table.columns));
  if (!base || !Array.isArray(base.columns) || !others.length) {
    state.keys = [];
    return state.keys;
  }
  const otherTokens = others.map((table) => new Set(table.columns.map(nameToken)));
  state.keys = base.columns
    .filter((column) => otherTokens.some((tokens) => tokens.has(nameToken(column))))
    .map((name) => {
      const map = {};
      state.tables.forEach((table) => {
        map[table.id] = table === base ? { column: name } : autoMapKey(table, name);
      });
      return { name, map };
    });
  return state.keys;
}

/** Add a table at the end of the join order; the second table proposes the keys. */
export function addTable(state, spec, extra = {}) {
  const table = {
    id: nextTableId(state),
    nickname: String(extra.nickname || "").trim().slice(0, NICKNAME_MAX_LENGTH),
    ...normalizeTableSpec(spec),
    columns: Array.isArray(extra.columns) ? extra.columns.map(String) : null,
    row_count: Number.isFinite(Number(extra.row_count)) && extra.row_count !== null ? Number(extra.row_count) : null,
    dropped_columns: Array.isArray(extra.dropped_columns) ? extra.dropped_columns.map(String) : [],
    color: freeColor(state),
  };
  state.tables.push(table);
  if (state.tables.length === 2 || !state.keys.length) detectKeys(state);
  else state.keys.forEach((key) => { key.map[table.id] = autoMapKey(table, key.name); });
  return table;
}

function dropTableSettings(state, id) {
  delete state.rows[id];
  delete state.exclude[id];
  delete state.rename[id];
}

export function removeTable(state, id) {
  const index = state.tables.findIndex((table) => table.id === id);
  if (index < 0) return;
  state.tables.splice(index, 1);
  dropTableSettings(state, id);
  if (index === 0 || state.tables.length < 2) detectKeys(state);
  else state.keys.forEach((key) => { delete key.map[id]; });
  if (state.tables[0]) delete state.rows[state.tables[0].id];
}

/** Move a table before (or after) another; a new base proposes the keys again. */
export function moveTable(state, id, targetId, after = false) {
  const moving = state.tables.find((table) => table.id === id);
  if (!moving || id === targetId) return false;
  const oldBase = state.tables[0]?.id;
  const rest = state.tables.filter((table) => table !== moving);
  const targetIndex = rest.findIndex((table) => table.id === targetId);
  if (targetIndex < 0) return false;
  rest.splice(targetIndex + (after ? 1 : 0), 0, moving);
  state.tables = rest;
  const baseChanged = state.tables[0].id !== oldBase;
  if (baseChanged) {
    delete state.rows[state.tables[0].id];
    detectKeys(state);
  }
  return baseChanged;
}

/** Store what a read found in a table; the base re-proposes keys, others re-match. */
export function setTableColumns(state, id, description) {
  const table = state.tables.find((item) => item.id === id);
  if (!table) return;
  const firstRead = !Array.isArray(table.columns);
  table.columns = (Array.isArray(description?.columns) ? description.columns : []).map(String);
  table.row_count = Number.isFinite(Number(description?.row_count)) ? Number(description.row_count) : null;
  table.dropped_columns = (Array.isArray(description?.dropped_columns) ? description.dropped_columns : []).map(String);
  if (state.tables[0] === table || !state.keys.length) {
    detectKeys(state);
    return;
  }
  state.keys.forEach((key) => {
    const entry = key.map[id];
    if (firstRead || !entry || (entry.column !== undefined && !table.columns.includes(entry.column))) {
      key.map[id] = autoMapKey(table, key.name);
    }
  });
}

/** Tables grouped for the list: one group per SQL connection, one for CSV files. */
export function tableGroups(state) {
  const groups = [];
  state.tables.forEach((table) => {
    let group = table.source_type === SOURCE_TYPE_MSSQL
      ? groups.find((item) => item.kind === SOURCE_TYPE_MSSQL && sameConnection(item.tables[0], table))
      : groups.find((item) => item.kind === SOURCE_TYPE_CSV);
    if (!group) {
      group = table.source_type === SOURCE_TYPE_MSSQL
        ? { kind: SOURCE_TYPE_MSSQL, server: table.mssql.server, database: table.mssql.database, tables: [] }
        : { kind: SOURCE_TYPE_CSV, tables: [] };
      groups.push(group);
    }
    group.tables.push(table);
  });
  return groups;
}

/** What each column of a table becomes, for the details window's "Used As". */
export function columnUses(state, id) {
  const table = state.tables.find((item) => item.id === id);
  if (!table) return [];
  const excluded = new Set(state.exclude[id] || []);
  const uses = (table.columns || []).map((column) => {
    const key = state.keys.find((item) => item.map[id]?.column === column);
    if (key) return { column, use: key.name === column ? "Key" : `Key → ${key.name}`, faint: false };
    if (excluded.has(column)) return { column, use: "Left out", faint: true };
    return { column, use: "Value column", faint: false };
  });
  (table.dropped_columns || []).forEach((column) => {
    uses.push({ column, use: "Empty, dropped on import", faint: true });
  });
  return uses;
}

/** The decision-3 `combined` block the server stores. */
export function toCombinedBlock(state) {
  const ids = new Set(state.tables.map((table) => table.id));
  const tables = state.tables.map((table) => {
    const entry = { id: table.id, nickname: table.nickname, source_type: table.source_type };
    if (table.source_type === SOURCE_TYPE_MSSQL) entry.mssql = { ...table.mssql };
    else entry.csv_path = table.csv_path;
    return entry;
  });
  const keys = state.keys.map((key) => {
    const map = {};
    Object.entries(key.map).forEach(([id, entry]) => { if (ids.has(id)) map[id] = { ...entry }; });
    return { name: key.name, map };
  });
  const rows = {};
  state.tables.slice(1).forEach((table) => { rows[table.id] = state.rows[table.id] || ROW_RULE_ALL; });
  const exclude = {};
  Object.entries(state.exclude).forEach(([id, list]) => {
    if (ids.has(id) && Array.isArray(list) && list.length) exclude[id] = [...list];
  });
  const rename = {};
  Object.entries(state.rename).forEach(([id, names]) => {
    if (ids.has(id) && names && Object.keys(names).length) rename[id] = { ...names };
  });
  return { tables, keys, rows, exclude, rename };
}

/** State from a stored `combined` block; columns stay unknown until each table is read. */
export function fromCombinedBlock(block) {
  const data = block && typeof block === "object" ? block : {};
  const state = createCombinedState();
  (Array.isArray(data.tables) ? data.tables : []).forEach((entry) => {
    const id = String(entry?.id || "").trim();
    if (!id || state.tables.some((table) => table.id === id)) return;
    state.tables.push({
      id,
      nickname: String(entry.nickname || "").trim().slice(0, NICKNAME_MAX_LENGTH),
      ...normalizeTableSpec(entry),
      columns: null,
      row_count: null,
      dropped_columns: [],
      color: freeColor(state),
    });
  });
  const ids = new Set(state.tables.map((table) => table.id));
  state.keys = (Array.isArray(data.keys) ? data.keys : []).map((key) => {
    const map = {};
    Object.entries(key?.map || {}).forEach(([id, entry]) => { if (ids.has(id)) map[id] = clone(entry); });
    return { name: String(key?.name || ""), map };
  }).filter((key) => key.name);
  Object.entries(data.rows || {}).forEach(([id, rule]) => { if (ids.has(id)) state.rows[id] = String(rule); });
  Object.entries(data.exclude || {}).forEach(([id, list]) => {
    if (ids.has(id) && Array.isArray(list)) state.exclude[id] = list.map(String);
  });
  Object.entries(data.rename || {}).forEach(([id, names]) => {
    if (ids.has(id) && names && typeof names === "object") state.rename[id] = { ...names };
  });
  if (state.tables[0]) delete state.rows[state.tables[0].id];
  return state;
}

/** The single-table form's values as one table, or the form's own first problem. */
export function tableFromSingleSettings(settings) {
  const method = settings?.method === SOURCE_TYPE_MSSQL ? SOURCE_TYPE_MSSQL : SOURCE_TYPE_CSV;
  const spec = method === SOURCE_TYPE_MSSQL
    ? normalizeTableSpec({ source_type: method, mssql: settings?.profile })
    : normalizeTableSpec({ source_type: method, csv_path: settings?.csvPath });
  const error = tableSpecProblem(spec);
  return error ? { error } : { spec };
}

/** What the single-table form shows for a table, when the list goes back to one. */
export function singleSettingsFromTable(table) {
  const spec = normalizeTableSpec(table);
  return spec.source_type === SOURCE_TYPE_MSSQL
    ? { method: SOURCE_TYPE_MSSQL, csvPath: "", profile: { ...spec.mssql } }
    : { method: SOURCE_TYPE_CSV, csvPath: spec.csv_path, profile: null };
}

/** Whether the combined settings can go on to the next step. */
export function validateCombinedState(state) {
  let error = "";
  if (state.tables.length < 2) error = "Add a second table to combine.";
  else if (state.tables.some((table) => !Array.isArray(table.columns))) {
    const unread = state.tables.find((table) => !Array.isArray(table.columns));
    error = `${tableLabel(unread)} has not been read yet.`;
  } else if (!state.keys.length) {
    error = "The tables share no column to match rows on.";
  }
  return { ok: !error, error };
}

/* ------------------------------------------------------------------------ */
/* DOM feature                                                              */
/* ------------------------------------------------------------------------ */

const ICONS = {
  plus: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  close: '<svg viewBox="0 0 10 10" aria-hidden="true"><line x1="2" y1="2" x2="8" y2="8"></line><line x1="8" y1="2" x2="2" y2="8"></line></svg>',
  x: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  grip: '<svg viewBox="0 0 12 14" aria-hidden="true"><g fill="currentColor"><circle cx="4" cy="3" r="1.1"/><circle cx="8" cy="3" r="1.1"/><circle cx="4" cy="7" r="1.1"/><circle cx="8" cy="7" r="1.1"/><circle cx="4" cy="11" r="1.1"/><circle cx="8" cy="11" r="1.1"/></g></svg>',
  db: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.6"><ellipse cx="12" cy="5.5" rx="7" ry="2.7"/><path d="M5 5.5v13c0 1.5 3.1 2.7 7 2.7s7-1.2 7-2.7v-13"/><path d="M5 12c0 1.5 3.1 2.7 7 2.7s7-1.2 7-2.7"/></g></svg>',
  csv: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M6 2.8h8l4.5 4.5v13.9H6z"/><path d="M14 2.8v4.5h4.5"/><path d="M9 12.5h6M9 15.5h6M9 18.5h4"/></g></svg>',
  info: '<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="6.4"/><path d="M8 7.2v4M8 4.8h.01"/></g></svg>',
};

const ordinal = (n) => {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] || "th"}`;
};
const formatCount = (value) => Number(value).toLocaleString("en-US");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Columns and row count of one table, read on this PC by the client app server. */
export async function describeTableRequest(fetchImpl, table) {
  if (typeof fetchImpl !== "function") return { ok: false, error: "Not available." };
  try {
    const res = await fetchImpl("/source_table/combined/describe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ table, refresh: false }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, error: String(payload?.detail || `Request failed (${res.status}).`) };
    return payload;
  } catch (err) {
    return { ok: false, error: err?.message || "Could not reach the app server." };
  }
}

export function createCombinedSourceFeature(deps = {}) {
  const {
    settingsBody = null,
    escapeHtml = defaultEscape,
    setStatus = () => {},
    // The single-table form's current values: { method, csvPath, profile }.
    readSingleSettings = () => ({ method: SOURCE_TYPE_CSV, csvPath: "", profile: null }),
    // Put one table back into the single-table form ({ method, csvPath, profile }).
    applySingleSettings = () => {},
    onListTables = async () => ({ ok: false, error: "Not available.", tables: [] }),
    onCsvPathPick = async () => "",
    // The coordinator's fetch; this module owns the combined-source routes.
    fetchImpl = null,
    onDescribeTable = (table) => describeTableRequest(fetchImpl, table),
  } = deps;
  const esc = escapeHtml;
  const doc = settingsBody?.ownerDocument || (typeof document === "undefined" ? null : document);

  let state = createCombinedState();
  let busy = false;
  // The open details window: { mode: "add" | "view", id, spec, nickname,
  // description, readSpec, reading, error, token }.
  let detail = null;
  let readToken = 0;
  let pop = null;
  let drag = null;
  let backdropPress = false;

  const bar = doc?.createElement("div");
  const list = doc?.createElement("div");
  const modalHost = doc?.createElement("div");
  const popEl = doc?.createElement("div");
  let addBtn = null;
  let barNote = null;

  function mount() {
    if (!settingsBody || !doc) return;
    bar.className = "cs-bar";
    bar.innerHTML = `<p class="sd-source-note cs-bar-note" hidden></p>`
      + `<button class="sd-btn cs-add-btn" type="button" aria-haspopup="menu">${ICONS.plus}Add Table</button>`;
    addBtn = bar.querySelector(".cs-add-btn");
    barNote = bar.querySelector(".cs-bar-note");
    list.className = "cs-list";
    list.hidden = true;
    settingsBody.prepend(bar);
    const status = settingsBody.querySelector(".sd-source-status");
    if (status) settingsBody.insertBefore(list, status);
    else settingsBody.append(list);
    modalHost.className = "cs-modal-host";
    popEl.className = "cs-pop";
    popEl.hidden = true;
    popEl.setAttribute("role", "menu");
    doc.body.append(modalHost, popEl);
    addBtn.addEventListener("click", () => onAddClick());
    list.addEventListener("click", onListClick);
    list.addEventListener("keydown", onListKeydown);
    list.addEventListener("pointerdown", onGripPointerDown);
    popEl.addEventListener("click", onPopClick);
    modalHost.addEventListener("mousedown", (event) => {
      backdropPress = event.target.classList?.contains("cs-modal-back");
    });
    modalHost.addEventListener("click", onModalClick);
    modalHost.addEventListener("change", onModalChange);
    // Capture on the window so Escape closes this module's popover or details
    // window before the import window's own Escape handler closes the window.
    doc.defaultView?.addEventListener("keydown", onKeydownCapture, true);
    doc.defaultView?.addEventListener("mousedown", onMousedownCapture, true);
  }

  const isActive = () => state.tables.length >= 2;
  const tableById = (id) => state.tables.find((table) => table.id === id);

  /* ---------------- table list ---------------- */

  function syncMode() {
    if (!settingsBody) return;
    const active = isActive();
    settingsBody.classList.toggle("cs-active", active);
    list.hidden = !active;
    barNote.hidden = !active;
    barNote.textContent = active
      ? "Tables are combined into one source. Click a table to see its file or connection; drag to change the join order."
      : "";
    if (active) renderList();
    else list.innerHTML = "";
  }

  function rowHtml(table) {
    const index = state.tables.indexOf(table);
    const label = tableLabel(table);
    let size;
    if (table.reading) size = "Reading...";
    else if (table.readError) size = '<span class="cs-row-error">Could not read</span>';
    else if (Array.isArray(table.columns)) {
      size = `${formatCount(table.row_count || 0)} rows · ${formatCount(table.columns.length)} cols`;
    } else size = "Not read";
    return `<div class="cs-row" data-id="${esc(table.id)}" tabindex="0" role="button" aria-label="${esc(label)} details">`
      + `<span class="cs-grip" title="Drag to reorder">${ICONS.grip}</span>`
      + `<span class="cs-dot cs-color-${table.color + 1}"></span>`
      + `<span class="cs-name"><b>${esc(label)}</b><span>${tableKindText(table)}</span></span>`
      + (index === 0 ? '<span class="cs-base-tag">Base</span>' : `<span class="cs-size">${ordinal(index + 1)}</span>`)
      + `<span class="cs-size cs-num">${size}</span>`
      + `<button class="cs-icon-btn cs-remove" type="button" aria-label="Remove ${esc(label)}">${ICONS.x}</button>`
      + "</div>";
  }

  function renderList() {
    const groups = tableGroups(state).map((group) => {
      const head = group.kind === SOURCE_TYPE_MSSQL
        ? `${ICONS.db}<b>SQL Server</b><span class="cs-where">${esc(group.server)} / ${esc(group.database)} · ${plural(group.tables.length, "table", "tables")}</span>`
        : `${ICONS.csv}<b>CSV Files</b><span class="cs-where">${plural(group.tables.length, "file", "files")}</span>`;
      return `<div class="cs-group"><div class="cs-group-head">${head}</div>${group.tables.map(rowHtml).join("")}</div>`;
    });
    const order = state.tables
      .map((table) => `<b class="cs-text-color-${table.color + 1}">${esc(tableLabel(table))}</b>`)
      .join(" → ");
    list.innerHTML = groups.join("")
      + `<div class="cs-order-note">${ICONS.info}<span>Join order: ${order}. The first table is the base; the others join onto it in this order.</span></div>`;
  }

  function onListClick(event) {
    const row = event.target.closest(".cs-row");
    if (!row || busy) return;
    if (event.target.closest(".cs-remove")) {
      removeTableAndSync(row.dataset.id);
      return;
    }
    if (event.target.closest(".cs-grip")) return;
    openDetail("view", row.dataset.id);
  }

  function onListKeydown(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest(".cs-row");
    if (!row || event.target !== row) return;
    event.preventDefault();
    openDetail("view", row.dataset.id);
  }

  function removeTableAndSync(id) {
    removeTable(state, id);
    if (state.tables.length === 1) applySingleSettings(singleSettingsFromTable(state.tables[0]));
    setStatus("");
    syncMode();
  }

  /* ---- drag to reorder: pointer capture on the grip (UI rule L16) ---- */

  function onGripPointerDown(event) {
    const grip = event.target.closest(".cs-grip");
    if (!grip || event.button !== 0 || busy || drag) return;
    const row = grip.closest(".cs-row");
    event.preventDefault();
    grip.setPointerCapture?.(event.pointerId);
    drag = { id: row.dataset.id, pointerId: event.pointerId, grip, row, targetId: null, after: false };
    row.classList.add("is-dragging");
    grip.addEventListener("pointermove", onDragMove);
    grip.addEventListener("pointerup", onDragUp);
    grip.addEventListener("pointercancel", onDragCancel);
    grip.addEventListener("lostpointercapture", onDragCancel);
  }

  function clearDropMarks() {
    list.querySelectorAll(".cs-drop-before, .cs-drop-after").forEach((node) => {
      node.classList.remove("cs-drop-before", "cs-drop-after");
    });
  }

  function onDragMove(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const rows = Array.from(list.querySelectorAll(".cs-row")).filter((node) => node !== drag.row);
    let target = null;
    let best = Infinity;
    rows.forEach((node) => {
      const rect = node.getBoundingClientRect();
      const distance = event.clientY < rect.top ? rect.top - event.clientY
        : event.clientY > rect.bottom ? event.clientY - rect.bottom : 0;
      if (distance < best) {
        best = distance;
        target = { node, after: event.clientY > rect.top + rect.height / 2 };
      }
    });
    clearDropMarks();
    if (!target) return;
    drag.targetId = target.node.dataset.id;
    drag.after = target.after;
    target.node.classList.add(target.after ? "cs-drop-after" : "cs-drop-before");
  }

  function endDrag(commit) {
    if (!drag) return;
    const { grip, row, id, targetId, after, pointerId } = drag;
    drag = null;
    grip.removeEventListener("pointermove", onDragMove);
    grip.removeEventListener("pointerup", onDragUp);
    grip.removeEventListener("pointercancel", onDragCancel);
    grip.removeEventListener("lostpointercapture", onDragCancel);
    if (grip.hasPointerCapture?.(pointerId)) grip.releasePointerCapture(pointerId);
    row.classList.remove("is-dragging");
    clearDropMarks();
    if (!commit || !targetId) return;
    const baseChanged = moveTable(state, id, targetId, after);
    if (baseChanged) {
      setStatus(`${tableLabel(state.tables[0])} is now the base table. Keys were proposed again from its columns.`, "ok");
    }
    renderList();
  }

  function onDragUp(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    endDrag(true);
  }

  function onDragCancel(event) {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    endDrag(false);
  }

  /* ---------------- reading tables ---------------- */

  async function describeInto(id) {
    const table = tableById(id);
    if (!table) return;
    table.reading = true;
    table.readError = "";
    if (isActive()) renderList();
    const spec = normalizeTableSpec(table);
    const result = await onDescribeTable({ ...spec, id: table.id, nickname: table.nickname });
    const current = tableById(id);
    if (!current || !sameTableSpec(current, spec)) return;
    current.reading = false;
    if (result?.ok) setTableColumns(state, id, result);
    else current.readError = String(result?.error || "Could not read the table.");
    if (isActive()) renderList();
    if (detail?.mode === "view" && detail.id === id && !detail.readSpec) {
      detail.error = current.readError;
      if (result?.ok) {
        detail.description = { columns: current.columns, row_count: current.row_count, dropped_columns: current.dropped_columns };
        detail.readSpec = spec;
      }
    }
    if (detail) renderDetailColumns();
  }

  /* ---------------- Add Table ---------------- */

  function currentConnection() {
    const table = state.tables.find((item) => item.source_type === SOURCE_TYPE_MSSQL);
    return table ? { ...table.mssql } : null;
  }

  async function onAddClick() {
    if (busy) return;
    if (!pop?.anchor || pop.anchor !== addBtn) closePop();
    else {
      closePop();
      return;
    }
    if (!isActive()) {
      // The form's table becomes the base; rebuild it from what the form holds now.
      const single = tableFromSingleSettings(readSingleSettings());
      if (single.error) {
        setStatus(`${single.error} It becomes the first table.`, "error");
        return;
      }
      if (!state.tables[0] || !sameTableSpec(state.tables[0], single.spec)) {
        state = createCombinedState();
        addTable(state, single.spec);
        describeInto(state.tables[0].id);
      }
    }
    setStatus("");
    openAddMenu();
  }

  function popItem(value, labelHtml, iconHtml, note = "") {
    return `<button class="cs-pop-item" type="button" role="menuitem" data-value="${esc(value)}">${iconHtml}`
      + `<span class="cs-pop-label">${labelHtml}${note ? `<span class="cs-pop-note">${esc(note)}</span>` : ""}</span></button>`;
  }

  function renderAddMenu() {
    const conn = pop.connection;
    let html = "";
    if (conn) {
      html += `<div class="cs-pop-head">SQL Server · ${esc(conn.server)} / ${esc(conn.database)}</div>`;
      if (pop.loading) html += '<div class="cs-pop-head cs-pop-quiet">Reading tables...</div>';
      else if (pop.error) html += `<div class="cs-pop-head cs-pop-error">${esc(pop.error)}</div>`;
      else {
        const added = state.tables
          .filter((table) => sameConnection(table, { source_type: SOURCE_TYPE_MSSQL, mssql: conn }))
          .map((table) => table.mssql.table.toLowerCase());
        const left = pop.tables.filter((name) => !added.includes(name.toLowerCase()));
        html += left.length
          ? left.map((name) => popItem(`sql:${name}`, `<span class="cs-mono">${esc(name)}</span>`, ICONS.db)).join("")
          : '<div class="cs-pop-head cs-pop-quiet">Every table is already added</div>';
      }
      html += '<div class="cs-pop-sep"></div>';
    }
    html += popItem("browse", "Browse for a CSV file...", ICONS.csv);
    html += popItem("other-db", conn ? "Another SQL Server database..." : "A SQL Server table...", ICONS.db);
    popEl.innerHTML = html;
    placePop();
  }

  function placePop() {
    const view = doc.defaultView;
    const rect = pop.anchor.getBoundingClientRect();
    popEl.style.left = "0px";
    popEl.style.top = "0px";
    const width = popEl.offsetWidth;
    const height = popEl.offsetHeight;
    const left = Math.max(8, Math.min(rect.left, view.innerWidth - width - 8));
    let top = rect.bottom + 4;
    if (top + height > view.innerHeight - 8 && rect.top - height - 4 > 8) top = rect.top - height - 4;
    popEl.style.left = `${left}px`;
    popEl.style.top = `${top}px`;
  }

  async function openAddMenu() {
    const connection = currentConnection();
    const token = {};
    pop = { anchor: addBtn, token, connection, loading: !!connection, error: "", tables: [] };
    popEl.hidden = false;
    addBtn.setAttribute("aria-expanded", "true");
    renderAddMenu();
    if (!connection) return;
    const result = await onListTables({ ...connection, authentication: MSSQL_AUTH_WINDOWS });
    if (pop?.token !== token) return;
    pop.loading = false;
    if (result?.ok) {
      pop.tables = (Array.isArray(result.tables) ? result.tables : [])
        .map((item) => String(item?.qualified_name || ""))
        .filter(Boolean);
    } else pop.error = String(result?.error || "Could not read tables from that database.");
    renderAddMenu();
  }

  function closePop() {
    if (!pop) return;
    pop = null;
    popEl.hidden = true;
    popEl.innerHTML = "";
    addBtn?.setAttribute("aria-expanded", "false");
  }

  async function onPopClick(event) {
    const item = event.target.closest(".cs-pop-item");
    if (!item || !pop) return;
    const value = item.dataset.value;
    const connection = pop.connection;
    closePop();
    if (value.startsWith("sql:")) {
      openDetail("add", null, { source_type: SOURCE_TYPE_MSSQL, mssql: { ...connection, table: value.slice(4) } });
    } else if (value === "browse") {
      const last = [...state.tables].reverse().find((table) => table.source_type === SOURCE_TYPE_CSV);
      const picked = String(await onCsvPathPick(last?.csv_path || "") || "").trim();
      if (picked) openDetail("add", null, { source_type: SOURCE_TYPE_CSV, csv_path: picked });
    } else if (value === "other-db") {
      openDetail("add", null, { source_type: SOURCE_TYPE_MSSQL, mssql: {} });
    }
  }

  /* ---------------- details window ---------------- */

  function openDetail(mode, id, spec = null) {
    closePop();
    const table = id ? tableById(id) : null;
    if (mode === "view" && !table) return;
    const tableSpec = normalizeTableSpec(table || spec);
    detail = {
      mode,
      id: table?.id || null,
      spec: tableSpec,
      nickname: table ? table.nickname : suggestNickname(tableSpec, state.tables),
      description: table && Array.isArray(table.columns)
        ? { columns: table.columns, row_count: table.row_count, dropped_columns: table.dropped_columns }
        : null,
      readSpec: table && Array.isArray(table.columns) ? normalizeTableSpec(table) : null,
      reading: false,
      error: table?.readError || "",
      status: "",
    };
    renderDetail();
    if (!detail.description && !tableSpecProblem(detail.spec) && !table?.reading) readDetail();
    const nick = modalHost.querySelector(".cs-d-nickname");
    nick?.focus({ preventScroll: true });
    nick?.select();
  }

  function closeDetail() {
    if (!detail) return;
    detail = null;
    readToken += 1;
    modalHost.innerHTML = "";
  }

  function sourceFieldsHtml(spec) {
    if (spec.source_type === SOURCE_TYPE_MSSQL) {
      const field = (name, label, value, placeholder) => `<label class="cs-d-label" for="csD_${name}">${label}</label>`
        + `<input class="cs-d-input cs-d-src" id="csD_${name}" data-field="${name}" type="text" autocomplete="off" spellcheck="false" value="${esc(value)}" placeholder="${placeholder}">`;
      return '<span class="cs-d-label">Import Method</span><span class="cs-d-static">SQL Server</span>'
        + field("server", "Server", spec.mssql.server, "Enter the server name")
        + field("database", "Database", spec.mssql.database, "Enter the database name")
        + field("table", "Table Or View", spec.mssql.table, "Schema-qualified name, such as dbo.Claims")
        + '<span class="cs-d-label">Sign In</span><span class="cs-d-static">Windows account</span>';
    }
    return '<span class="cs-d-label">Import Method</span><span class="cs-d-static">CSV File</span>'
      + '<label class="cs-d-label" for="csD_csv_path">File</label>'
      + '<span class="cs-d-with-btn">'
      + `<input class="cs-d-input cs-d-src" id="csD_csv_path" data-field="csv_path" type="text" autocomplete="off" spellcheck="false" value="${esc(spec.csv_path)}" placeholder="Browse to choose a CSV file">`
      + '<button class="sd-btn" type="button" data-act="browse">Browse</button></span>';
  }

  function sourceNote(spec) {
    if (spec.source_type !== SOURCE_TYPE_MSSQL) return "The file is read on this PC when you import.";
    const shared = state.tables.filter((table) => table.id !== detail.id && sameConnection(table, spec)).length;
    return shared
      ? `This connection is shared with ${plural(shared, "other table", "other tables")}. Changing the server or database changes them too.`
      : "Connects as your Windows account. No credentials are stored.";
  }

  function previewState() {
    const preview = clone(state);
    let id = detail.id;
    if (detail.mode === "add") {
      if (!state.tables.length) return { preview, id: null };
      id = addTable(preview, detail.spec, { ...(detail.description || {}), nickname: detail.nickname }).id;
    } else if (detail.description) {
      setTableColumns(preview, id, detail.description);
    }
    return { preview, id };
  }

  function detailColumnsHtml() {
    if (detail.reading) return '<p class="cs-d-quiet">Reading the table...</p>';
    if (detail.error) return `<p class="cs-d-error">${esc(detail.error)}</p>`;
    if (!detail.description) return '<p class="cs-d-quiet">Columns show once the table is read.</p>';
    const { preview, id } = previewState();
    const uses = id ? columnUses(preview, id) : detail.description.columns.map((column) => ({ column, use: "", faint: false }));
    const rows = uses.map((item) => {
      const faint = item.faint ? " cs-faint" : "";
      return `<tr><td class="cs-mono${faint}">${esc(item.column)}</td><td class="cs-use${faint}">${esc(item.use)}</td></tr>`;
    }).join("");
    return `<div class="cs-d-cols"><table class="cs-d-table"><thead><tr><th>Column</th><th>Used As</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function detailColumnsLabel() {
    const desc = detail.description;
    if (!desc || detail.reading || detail.error) return "Columns";
    return `Columns · ${formatCount(desc.columns.length)} columns, ${formatCount(desc.row_count || 0)} rows`;
  }

  function renderDetail() {
    const table = detail.id ? tableById(detail.id) : null;
    const adding = detail.mode === "add";
    const color = table ? table.color : freeColor(state);
    const title = adding ? "Add Table" : tableLabel(table);
    modalHost.innerHTML = '<div class="cs-modal-back">'
      + '<div class="rct-row-editor cs-detail" role="dialog" aria-modal="true" aria-labelledby="csDetailTitle">'
      + '<div class="rct-row-editor-header">'
      + `<span class="cs-dot cs-color-${color + 1}"></span>`
      + `<div class="rct-row-editor-title" id="csDetailTitle">${esc(title)}</div>`
      + `<button class="rct-row-editor-close" type="button" data-act="close" aria-label="Close">${ICONS.close}</button>`
      + "</div>"
      + '<div class="cs-d-body">'
      + '<div class="cs-d-sec"><label class="sd-field-label" for="csD_nickname">Nickname</label>'
      + `<input class="cs-d-input cs-d-nickname" id="csD_nickname" type="text" maxlength="${NICKNAME_MAX_LENGTH}" autocomplete="off" spellcheck="false" value="${esc(detail.nickname)}" placeholder="${esc(tableSourceName(detail.spec))}">`
      + '<p class="sd-source-note">Shown in the table list and in messages. Leave it blank to show the table name.</p></div>'
      + '<div class="cs-d-sec"><span class="sd-field-label">Source</span>'
      + `<div class="cs-d-grid">${sourceFieldsHtml(detail.spec)}</div>`
      + `<p class="sd-source-note cs-d-src-note">${esc(sourceNote(detail.spec))}</p></div>`
      + `<div class="cs-d-sec"><span class="sd-field-label cs-num cs-d-cols-label">${esc(detailColumnsLabel())}</span>`
      + `<div class="cs-d-cols-host">${detailColumnsHtml()}</div></div>`
      + '<div class="sd-source-status cs-d-status" hidden></div>'
      + "</div>"
      + '<div class="rct-row-editor-actions">'
      + (adding ? "" : '<button class="dialog-btn cs-d-remove" type="button" data-act="remove">Remove Table</button>')
      + '<button class="dialog-btn" type="button" data-act="close">Cancel</button>'
      + `<button class="dialog-btn primary cs-d-save" type="button" data-act="save">${adding ? "Add Table" : "Save"}</button>`
      + "</div></div></div>";
    syncDetailSave();
  }

  /** Redraw only the column list, so inputs keep their caret while a read lands. */
  function renderDetailColumns() {
    if (!detail) return;
    const label = modalHost.querySelector(".cs-d-cols-label");
    const host = modalHost.querySelector(".cs-d-cols-host");
    if (label) label.textContent = detailColumnsLabel();
    if (host) host.innerHTML = detailColumnsHtml();
    syncDetailSave();
  }

  function syncDetailSave() {
    const save = modalHost.querySelector(".cs-d-save");
    if (save) save.disabled = !!detail?.reading;
  }

  function setDetailStatus(text, tone = "") {
    const node = modalHost.querySelector(".cs-d-status");
    if (!node) return;
    node.textContent = text;
    node.classList.toggle("error", tone === "error");
    node.hidden = !text;
  }

  function readDetailInputs() {
    const nick = modalHost.querySelector(".cs-d-nickname");
    if (nick) detail.nickname = nick.value.trim().slice(0, NICKNAME_MAX_LENGTH);
    const spec = clone(detail.spec);
    modalHost.querySelectorAll(".cs-d-src").forEach((input) => {
      if (spec.source_type === SOURCE_TYPE_MSSQL) spec.mssql[input.dataset.field] = input.value.trim();
      else spec.csv_path = input.value.trim();
    });
    detail.spec = normalizeTableSpec(spec);
  }

  async function readDetail() {
    const token = ++readToken;
    const spec = clone(detail.spec);
    detail.reading = true;
    detail.error = "";
    renderDetailColumns();
    const result = await onDescribeTable({ ...spec, id: detail.id || undefined, nickname: detail.nickname });
    if (!detail || token !== readToken) return false;
    detail.reading = false;
    if (result?.ok) {
      detail.description = {
        columns: (result.columns || []).map(String),
        row_count: result.row_count,
        dropped_columns: (result.dropped_columns || []).map(String),
      };
      detail.readSpec = spec;
    } else {
      detail.description = null;
      detail.readSpec = null;
      detail.error = String(result?.error || "Could not read the table.");
    }
    renderDetailColumns();
    return !!result?.ok;
  }

  function onModalChange(event) {
    if (!detail || !event.target.classList.contains("cs-d-src")) return;
    readDetailInputs();
    if (!tableSpecProblem(detail.spec) && !(detail.readSpec && sameTableSpec(detail.readSpec, detail.spec))) {
      readDetail();
    }
  }

  async function onModalClick(event) {
    if (!detail) return;
    if (event.target.classList.contains("cs-modal-back")) {
      if (backdropPress) closeDetail();
      return;
    }
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const act = button.dataset.act;
    if (act === "close") closeDetail();
    else if (act === "save") saveDetail();
    else if (act === "remove") {
      const id = detail.id;
      closeDetail();
      removeTableAndSync(id);
    } else if (act === "browse") {
      readDetailInputs();
      const picked = String(await onCsvPathPick(detail.spec.csv_path) || "").trim();
      if (!picked || !detail) return;
      const input = modalHost.querySelector("#csD_csv_path");
      if (input) input.value = picked;
      readDetailInputs();
      readDetail();
    }
  }

  async function saveDetail() {
    if (!detail || detail.reading) return;
    readDetailInputs();
    const problem = tableSpecProblem(detail.spec);
    if (problem) {
      setDetailStatus(problem, "error");
      return;
    }
    if (!detail.readSpec || !sameTableSpec(detail.readSpec, detail.spec)) {
      if (!(await readDetail())) return;
    }
    if (!detail.description) return;
    const { mode, id, spec, nickname, description } = detail;
    if (mode === "add") {
      const table = addTable(state, spec, { ...description, nickname });
      closeDetail();
      setStatus(`Added ${tableLabel(table)}. Its keys were matched by name.`, "ok");
      syncMode();
      return;
    }
    const table = tableById(id);
    if (!table) {
      closeDetail();
      return;
    }
    table.nickname = nickname;
    if (!sameTableSpec(table, spec)) {
      // The tables listed under one connection follow a server or database change.
      const followers = spec.source_type === SOURCE_TYPE_MSSQL && !sameConnection(table, spec)
        ? state.tables.filter((other) => other !== table && sameConnection(other, table))
        : [];
      Object.assign(table, normalizeTableSpec(spec));
      if (spec.source_type === SOURCE_TYPE_MSSQL) delete table.csv_path;
      else delete table.mssql;
      table.readError = "";
      setTableColumns(state, id, description);
      followers.forEach((other) => {
        other.mssql = { ...other.mssql, server: spec.mssql.server, database: spec.mssql.database };
        describeInto(other.id);
      });
    }
    closeDetail();
    syncMode();
  }

  /* ---------------- keyboard and outside clicks ---------------- */

  function onKeydownCapture(event) {
    if (event.key === "Escape") {
      if (pop) {
        closePop();
        addBtn?.focus({ preventScroll: true });
      } else if (detail) closeDetail();
      else return;
      event.stopPropagation();
      event.preventDefault();
      return;
    }
    if (event.key === "Enter" && detail && event.target.classList?.contains("cs-d-nickname")) {
      event.preventDefault();
      saveDetail();
    }
  }

  function onMousedownCapture(event) {
    if (!pop) return;
    if (popEl.contains(event.target) || pop.anchor.contains(event.target)) return;
    closePop();
  }

  mount();

  return {
    /** True once the window lists two or more tables. */
    isActive,
    /** Back to the single-table form with an empty combined state. */
    reset() {
      closeDetail();
      closePop();
      if (drag) endDrag(false);
      state = createCombinedState();
      syncMode();
    },
    /** Close this module's popover and details window. */
    close() {
      closeDetail();
      closePop();
      if (drag) endDrag(false);
    },
    setBusy(value) {
      busy = !!value;
      if (addBtn) addBtn.disabled = busy;
      if (busy) closePop();
    },
    validate() {
      return validateCombinedState(state);
    },
    getCombinedBlock() {
      return toCombinedBlock(state);
    },
    getState() {
      return state;
    },
  };
}
