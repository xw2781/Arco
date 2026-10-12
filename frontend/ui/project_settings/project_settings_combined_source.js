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
 * With two or more tables the window gains a Combine page after the settings:
 * the Join Map (one card per table, key rows lined up across the cards, row
 * rules, value-column lists, the Combined Table card) and the Row Match and
 * Preview tabs, fed by `POST /source_table/combined/preview` on this PC.
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

/* ---------------- Combine step: keys, row rules, columns ---------------- */

export const KEY_CONVERT_YYYYMM = "yyyymm";
export const ROW_RULES = {
  all: { label: "All Rows", note: "Keep every row from both sides. Rows without a match get blanks." },
  base: { label: "Base Rows", note: "Keep the rows already combined. Rows only in this table are left out." },
  match: { label: "Matches Only", note: "Keep only rows found on both sides." },
};

/** The import window's pages: Combine sits between Source and Datasets only with two or more tables. */
export function importSteps(state) {
  return state.tables.length >= 2
    ? ["settings", "combine", "datasets", "classes"]
    : ["settings", "datasets", "classes"];
}

export function rowRule(state, id) {
  return ROW_RULES[state.rows[id]] ? state.rows[id] : ROW_RULE_ALL;
}

/** A non-base table's row rule; the base has none. */
export function setRowRule(state, id, rule) {
  if (!ROW_RULES[rule] || state.tables[0]?.id === id || !state.tables.some((table) => table.id === id)) return;
  state.rows[id] = rule;
}

/**
 * Where a key comes from in one table: `{column}`, `{fill}` or `{any: true}`.
 * The base always names a column, and that column names the key.
 */
export function setKeyEntry(state, index, id, entry) {
  const key = state.keys[index];
  if (!key) return;
  const isBase = state.tables[0]?.id === id;
  if (isBase && entry?.column === undefined) return;
  if (isBase && state.keys.some((other) => other !== key && nameToken(other.name) === nameToken(entry.column))) return;
  key.map[id] = clone(entry);
  if (isBase) key.name = entry.column;
}

/** Turn "Read as YYYYMM" on or off for a key's column in one table. */
export function toggleKeyConvert(state, index, id) {
  const entry = state.keys[index]?.map[id];
  if (!entry || entry.column === undefined) return;
  if (entry.convert) delete entry.convert;
  else entry.convert = KEY_CONVERT_YYYYMM;
}

/** Base columns that are not yet a key, for Add Key. */
export function keyCandidates(state) {
  const base = state.tables[0];
  const used = new Set(state.keys.map((key) => nameToken(key.name)));
  return (base?.columns || []).filter((column) => !used.has(nameToken(column)));
}

/** Match rows on one more base column; the other tables match it by name. */
export function addKey(state, column) {
  const base = state.tables[0];
  if (!base || !keyCandidates(state).includes(column)) return null;
  const map = {};
  state.tables.forEach((table) => {
    map[table.id] = table === base ? { column } : autoMapKey(table, column);
  });
  const key = { name: column, map };
  state.keys.push(key);
  return key;
}

/** Stop matching on a key; the last key stays so rows can still be matched. */
export function removeKey(state, index) {
  if (state.keys.length <= 1 || !state.keys[index]) return false;
  state.keys.splice(index, 1);
  return true;
}

export function toggleExclude(state, id, column) {
  const list = state.exclude[id] || [];
  const next = list.includes(column) ? list.filter((item) => item !== column) : [...list, column];
  if (next.length) state.exclude[id] = next;
  else delete state.exclude[id];
}

/** A column's name in the combined table; blank or its own name clears the rename. */
export function setRename(state, id, column, name) {
  const value = String(name ?? "").trim();
  const names = { ...(state.rename[id] || {}) };
  if (value && value !== column) names[column] = value;
  else delete names[column];
  if (Object.keys(names).length) state.rename[id] = names;
  else delete state.rename[id];
}

/**
 * A table's value columns as the settings say now: left out, renamed, or
 * named with the clash suffix the last preview gave it (decision 6).
 */
export function valueColumns(state, id, plan = []) {
  const table = state.tables.find((item) => item.id === id);
  if (!table || !Array.isArray(table.columns)) return [];
  const keyColumns = new Set(state.keys.map((key) => key.map[id]?.column).filter((column) => column !== undefined));
  const excluded = new Set(state.exclude[id] || []);
  const renames = state.rename[id] || {};
  const planned = new Map((plan || []).filter((item) => item.table_id === id).map((item) => [item.column, item]));
  return table.columns.filter((column) => !keyColumns.has(column)).map((column) => {
    const off = excluded.has(column);
    const renamed = renames[column] || "";
    const item = planned.get(column);
    const conflict = !off && !renamed && !!item?.conflict && !item.off && !item.renamed;
    return { column, master: renamed || (conflict ? item.master : column), off, conflict, renamed: !!renamed };
  });
}

export function previewRequestBody(projectName, state, refresh = false) {
  return { project_name: String(projectName || ""), combined: toCombinedBlock(state), refresh: !!refresh };
}

export const warningId = (warning) => `${warning.kind}|${warning.table_id}|${warning.key || warning.column || ""}`;

/** Format mismatches the settings still have (no "Read as YYYYMM") and nobody dismissed. */
export function openMismatches(state, warnings, dismissed = new Set()) {
  return (warnings || []).filter((warning) => {
    if (warning.kind !== "format_mismatch" || dismissed.has(warningId(warning))) return false;
    const entry = state.keys.find((key) => key.name === warning.key)?.map[warning.table_id];
    return !!entry && entry.column !== undefined && !entry.convert;
  });
}

/**
 * Why Next cannot leave the Combine step yet, or "". The preview must answer
 * for the current settings, and every format mismatch must be fixed or dismissed.
 */
export function combineProblem(state, preview, dismissed = new Set()) {
  const tables = validateCombinedState(state);
  if (!tables.ok) return tables.error;
  const block = JSON.stringify(toCombinedBlock(state));
  if (preview?.error && preview.block === block) return preview.error;
  if (!preview?.data || preview.block !== block) return "Wait for the preview to finish.";
  const open = openMismatches(state, preview.data.warnings, dismissed)[0];
  if (open) {
    const table = state.tables.find((item) => item.id === open.table_id);
    return `${tableLabel(table)} stores ${open.key} as ${open.sample}. Read it as YYYYMM or dismiss the warning.`;
  }
  return "";
}

/** The Row Match messages for the preview's warnings, as HTML with an optional fix. */
export function warningAlerts(state, warnings, esc = defaultEscape) {
  const label = (warning) => esc(tableLabel(state.tables.find((item) => item.id === warning.table_id)) || warning.table || "");
  const mono = (text) => `<span class="cs-mono">${esc(text)}</span>`;
  return (warnings || []).map((warning) => {
    const id = warningId(warning);
    if (warning.kind === "format_mismatch") {
      return {
        id,
        tone: "warn",
        html: `<b>${label(warning)}</b> stores ${esc(warning.key)} as ${mono(warning.sample)}; the base uses ${mono(warning.base_sample)}. `
          + `${formatCount(warning.matched || 0)} of its rows match.`,
        fix: { table_id: warning.table_id, key: warning.key },
      };
    }
    if (warning.kind === "repeat") {
      const keys = (warning.any_keys || []).join(", ") || "a key";
      return {
        id,
        tone: "warn",
        html: `Each <b>${label(warning)}</b> row lands on up to ${formatCount(warning.max_repeat)} combined rows because `
          + `${esc(keys)} matches any value. Its amounts will repeat on every one.`,
      };
    }
    if (warning.kind === "filled_rows") {
      const fills = Object.entries(warning.fills || {});
      return {
        id,
        tone: "info",
        html: `<b>${label(warning)}</b> has no ${esc(fills.map(([name]) => name).join(", "))}, so its rows sit at `
          + `${esc(fills.map(([name, value]) => `${name} = ${value}`).join(", "))} and form ${formatCount(warning.added || 0)} rows of their own.`,
      };
    }
    if (warning.kind === "name_clash") {
      return {
        id,
        tone: "info",
        html: `Two tables have <b>${esc(warning.column)}</b>. The ${label(warning)} copy is named ${mono(warning.master)}. `
          + "Click it in the column list to rename it.",
      };
    }
    return null;
  }).filter(Boolean);
}

/** Coverage bar segments, most tables first: `[{ tables, rows }]`. */
export function coverageSegments(coverage) {
  return Object.entries(coverage || {})
    .map(([tables, rows]) => ({ tables: Number(tables), rows: Number(rows) }))
    .filter((item) => item.tables > 0 && item.rows > 0)
    .sort((a, b) => b.tables - a.tables);
}

/** "12 of 72 matched · 60 added as new rows", as the Row Match tab words it. */
export function matchText(stats, rule) {
  const read = Number(stats?.read || 0);
  const matched = Number(stats?.matched || 0);
  let rest;
  if (matched >= read) rest = "all matched";
  else if (rule === ROW_RULE_ALL) rest = `${formatCount(stats?.added || 0)} added as new rows`;
  else rest = `${formatCount(stats?.left_out || 0)} left out`;
  const dropped = Number(stats?.base_rows_dropped || 0);
  return `${formatCount(matched)} of ${formatCount(read)} matched · ${rest}`
    + (dropped ? ` · ${formatCount(dropped)} combined rows dropped` : "");
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
  warn: '<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.2 14.3 13.3H1.7z"/><path d="M8 6.6v3.2M8 11.6h.01"/></g></svg>',
  more: '<svg viewBox="0 0 16 16" aria-hidden="true"><g fill="currentColor"><circle cx="3.5" cy="8" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="12.5" cy="8" r="1.3"/></g></svg>',
};

/** Two circles for a row rule: the shaded parts are the rows kept. */
function vennIcon(rule) {
  const left = rule === "match" ? 0 : 0.28;
  const right = rule === ROW_RULE_ALL ? 0.28 : 0;
  return '<svg class="cs-venn" viewBox="0 0 20 14" aria-hidden="true">'
    + `<circle cx="7.5" cy="7" r="5" fill="currentColor" fill-opacity="${left}" stroke="currentColor" stroke-width="1.1"/>`
    + `<circle cx="12.5" cy="7" r="5" fill="currentColor" fill-opacity="${right}" stroke="currentColor" stroke-width="1.1"/>`
    + '<path d="M10 2.67A5 5 0 0 1 10 11.33A5 5 0 0 1 10 2.67Z" fill="currentColor" fill-opacity=".55"/></svg>';
}

const NUMERIC_TEXT = /^-?[\d,]*\.?\d+(?:[eE][-+]?\d+)?$/;

const ordinal = (n) => {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] || "th"}`;
};
const formatCount = (value) => Number(value).toLocaleString("en-US");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

async function postJson(fetchImpl, url, body) {
  if (typeof fetchImpl !== "function") return { ok: false, error: "Not available." };
  try {
    const res = await fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) return { ok: false, error: String(payload?.detail || `Request failed (${res.status}).`) };
    return payload;
  } catch (err) {
    return { ok: false, error: err?.message || "Could not reach the app server." };
  }
}

/** Columns and row count of one table, read on this PC by the client app server. */
export function describeTableRequest(fetchImpl, table) {
  return postJson(fetchImpl, "/source_table/combined/describe", { table, refresh: false });
}

/** Statistics, warnings and first rows of the combined table, joined on this PC. */
export function previewCombinedRequest(fetchImpl, body) {
  return postJson(fetchImpl, "/source_table/combined/preview", body);
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
    onPreview = (body) => previewCombinedRequest(fetchImpl, body),
    getProjectName = () => "",
    // Called when the Combine step can no longer show (tables back to one).
    onLeaveCombine = () => {},
    previewDelayMs = 350,
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
  // Combine step: shown flag, the last preview ({ data, error, loading, block }
  // where block is the JSON of the settings it answered), Row Match or Preview.
  let combineVisible = false;
  let preview = null;
  let previewTimer = null;
  let previewToken = 0;
  let resultTab = "match";
  const dismissed = new Set();

  const bar = doc?.createElement("div");
  const list = doc?.createElement("div");
  const modalHost = doc?.createElement("div");
  const popEl = doc?.createElement("div");
  const combineEl = doc?.createElement("div");
  let addBtn = null;
  let barNote = null;
  let mapHost = null;
  let resultHost = null;
  let combineStatus = null;

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
    // The Combine step is its own page of the import window, after the settings.
    combineEl.className = "sd-import-body cs-combine";
    combineEl.hidden = true;
    combineEl.innerHTML = '<div class="cs-map-host"></div><div class="cs-result-host"></div>'
      + '<div class="sd-source-status cs-combine-status" hidden></div>';
    mapHost = combineEl.querySelector(".cs-map-host");
    resultHost = combineEl.querySelector(".cs-result-host");
    combineStatus = combineEl.querySelector(".cs-combine-status");
    settingsBody.after(combineEl);
    combineEl.addEventListener("click", onCombineClick);
    combineEl.addEventListener("keydown", onCombineKeydown);
    combineEl.addEventListener("mouseover", onMapHover);
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
    if (!combineVisible) return;
    if (active) {
      renderCombine();
      schedulePreview();
    } else {
      showCombine(false);
      onLeaveCombine();
    }
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
    // Connection details live only in the details window; a second connection
    // is told apart by its number.
    const all = tableGroups(state);
    const several = all.filter((group) => group.kind === SOURCE_TYPE_MSSQL).length > 1;
    let connections = 0;
    const groups = all.map((group) => {
      if (group.kind === SOURCE_TYPE_MSSQL) connections += 1;
      const name = several ? `SQL Server · connection ${connections}` : "SQL Server";
      const shared = group.tables.length > 1 ? " · one shared connection" : "";
      const head = group.kind === SOURCE_TYPE_MSSQL
        ? `${ICONS.db}<b>${name}</b><span class="cs-where">${plural(group.tables.length, "table", "tables")}${shared}</span>`
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
    if (combineVisible) {
      renderCombine();
      schedulePreview();
    }
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
    if (pop?.onPick) {
      const choice = event.target.closest("[data-value]");
      if (choice) pop.onPick(choice.dataset.value);
      return;
    }
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

  /* ---------------- Combine step ---------------- */

  function showCombine(visible) {
    combineVisible = !!visible && isActive();
    if (!combineEl) return;
    combineEl.hidden = !combineVisible;
    closePop();
    if (!combineVisible) {
      clearTimeout(previewTimer);
      return;
    }
    setCombineStatus("");
    renderCombine();
    schedulePreview(0);
  }

  function setCombineStatus(text, tone = "") {
    if (!combineStatus) return;
    const value = String(text || "").trim();
    combineStatus.textContent = value;
    combineStatus.classList.toggle("error", tone === "error");
    combineStatus.classList.toggle("ok", tone === "ok");
    combineStatus.hidden = !value;
  }

  /** Something on the Combine step changed: redraw it and ask for a new preview. */
  function combineChanged() {
    setCombineStatus("");
    if (isActive()) renderList();
    renderCombine();
    schedulePreview();
  }

  const currentBlock = () => JSON.stringify(toCombinedBlock(state));

  function schedulePreview(delay = previewDelayMs, refresh = false) {
    clearTimeout(previewTimer);
    if (!combineVisible || !validateCombinedState(state).ok) return;
    if (!refresh && preview && !preview.loading && preview.block === currentBlock()) return;
    preview = { ...(preview || {}), loading: true };
    renderResult();
    previewTimer = setTimeout(() => runPreview(refresh), delay);
  }

  async function runPreview(refresh) {
    const token = ++previewToken;
    const body = previewRequestBody(getProjectName(), state, refresh);
    const block = JSON.stringify(body.combined);
    const result = await onPreview(body);
    if (token !== previewToken) return;
    if (result?.ok) {
      preview = { data: result, error: "", loading: false, block };
      (result.tables || []).forEach((item) => {
        const table = tableById(item.id);
        if (table && Number.isFinite(Number(item.row_count))) table.row_count = Number(item.row_count);
      });
    } else {
      preview = { data: preview?.data || null, error: String(result?.error || "Could not preview the combined table."), loading: false, block };
    }
    if (combineVisible) renderCombine();
  }

  const planOf = () => preview?.data?.plan || [];
  const colorClass = (table) => `cs-color-${table.color + 1}`;
  const keyIndexOf = (name) => state.keys.findIndex((key) => key.name === name);

  function keyCellHtml(table, key, index, warned) {
    const entry = key.map[table.id] || { any: true };
    const attrs = `data-act="key" data-id="${esc(table.id)}" data-k="${index}"`;
    if (entry.any) return `<button class="cs-kcell cs-virtual" type="button" ${attrs}>Any value</button>`;
    if (entry.fill !== undefined) {
      return `<button class="cs-kcell cs-virtual" type="button" ${attrs}>Fill <span class="cs-mono">${esc(entry.fill)}</span>`
        + '<span class="cs-alt">not in table</span></button>';
    }
    const differs = entry.column !== key.name;
    let alt = "";
    if (warned) alt = `<span class="cs-alt">${esc(warned.sample)}</span>`;
    else if (entry.convert) alt = '<span class="cs-alt">as YYYYMM</span>';
    else if (differs) alt = '<span class="cs-alt">≈ name</span>';
    const title = differs ? `${entry.column} becomes ${key.name}` : entry.column;
    return `<button class="cs-kcell${warned ? " cs-warn" : ""}" type="button" ${attrs} title="${esc(title)}">`
      + `${warned ? ICONS.warn : ""}<span class="cs-mono">${esc(entry.column)}</span>${alt}</button>`;
  }

  function mapHtml() {
    const tables = state.tables;
    const keyCount = state.keys.length;
    const lastRow = 5 + keyCount;
    const cells = [];
    const at = (column, row, html, cls, attrs = "") => cells.push(
      `<div class="${cls}" style="grid-column:${column};grid-row:${row}"${attrs}>${html}</div>`,
    );
    const card = (row, extra = "") => `cs-cc${row === 1 ? " cs-top" : ""}${row === lastRow ? " cs-bot" : ""}${extra ? ` ${extra}` : ""}`;
    const warned = openMismatches(state, preview?.data?.warnings);
    const plan = planOf();

    at(1, 1, '<span class="sd-field-label">Tables</span>', "cs-lc");
    at(1, 2, '<span class="sd-field-label">Rows To Keep</span>', "cs-lc");
    at(1, 3, '<span class="sd-field-label">Match Rows On</span>', "cs-lc cs-sec");
    state.keys.forEach((key, index) => at(1, 4 + index,
      `<span class="cs-kname" title="${esc(key.name)}">${esc(key.name)}</span>`
      + `<button class="cs-icon-btn" type="button" data-act="remove-key" data-k="${index}" aria-label="Stop matching on ${esc(key.name)}">${ICONS.x}</button>`,
      "cs-lc", ` data-key="${index}"`));
    at(1, 4 + keyCount, `<button class="cs-add-key" type="button" data-act="add-key">${ICONS.plus}Add Key</button>`, "cs-lc");
    at(1, lastRow, '<span class="sd-field-label">Other Columns</span>', "cs-lc cs-lc-top");

    tables.forEach((table, ti) => {
      const gutter = 2 + ti * 2;
      const column = 3 + ti * 2;
      const label = tableLabel(table);
      const rows = Number.isFinite(table.row_count) && table.row_count !== null ? `${formatCount(table.row_count)} rows` : "Not read";
      at(column, 1, '<div class="cs-card-head"><div class="cs-card-title">'
        + `<span class="cs-dot ${colorClass(table)}"></span><b>${esc(label)}</b>`
        + `<button class="cs-icon-btn" type="button" data-act="card-menu" data-id="${esc(table.id)}" aria-label="${esc(label)} options">${ICONS.more}</button></div>`
        + `<span class="cs-card-sub cs-num">${table.source_type === SOURCE_TYPE_MSSQL ? ICONS.db : ICONS.csv}${tableKindText(table)} · ${rows}</span></div>`,
      card(1, "cs-open"), ` data-act="details" data-id="${esc(table.id)}" tabindex="0" role="button" title="${esc(tableSourceName(table))} · click for source details"`);
      const rule = rowRule(state, table.id);
      at(column, 2, ti === 0
        ? '<span class="cs-base-label">Base table</span>'
        : `<button class="cs-pill" type="button" data-act="join" data-id="${esc(table.id)}">${vennIcon(rule)}${ROW_RULES[rule].label}<span class="cs-caret"></span></button>`,
      card(2));
      at(column, 3, "", card(3, "cs-sec"));
      state.keys.forEach((key, ki) => {
        const entry = key.map[table.id] || {};
        const warning = warned.find((item) => item.table_id === table.id && item.key === key.name);
        at(column, 4 + ki, keyCellHtml(table, key, ki, warning), card(4 + ki), ` data-key="${ki}"`);
        at(gutter, 4 + ki, `<span class="cs-rail${entry.column === undefined ? " cs-soft" : ""}"></span>`, "cs-gut", ` data-key="${ki}"`);
      });
      at(column, 4 + keyCount, "", card(4 + keyCount, "cs-sec"));
      const values = valueColumns(state, table.id, plan).map((item) => {
        let to = "";
        if (item.off) to = '<span class="cs-to">left out</span>';
        else if (item.master !== item.column) to = `<span class="cs-to">→ ${esc(item.master)}</span>`;
        let title = "Click to leave out or rename";
        if (item.off) title = "Left out. Click to include.";
        else if (item.master !== item.column) title = `${item.column} becomes ${item.master}`;
        return `<button class="cs-crow${item.off ? " cs-off" : ""}${item.conflict ? " cs-conflict" : ""}" type="button" data-act="column" `
          + `data-id="${esc(table.id)}" data-col="${esc(item.column)}" title="${esc(title)}"><span class="cs-cn">${esc(item.column)}</span>${to}</button>`;
      }).join("");
      at(column, lastRow, `<div class="cs-clist">${values || '<span class="cs-quiet">None</span>'}</div>`, card(lastRow));
    });

    const gutter = 2 + tables.length * 2;
    const column = 3 + tables.length * 2;
    const data = preview?.data;
    const sub = data ? `${formatCount(data.row_count)} rows · ${formatCount(data.column_count)} cols` : "Not previewed yet";
    at(column, 1, '<div class="cs-card-head"><div class="cs-card-title"><span class="cs-dot cs-dot-master"></span><b>Combined Table</b></div>'
      + `<span class="cs-card-sub cs-num">${sub}</span></div>`, card(1, "cs-master"));
    at(column, 2, '<span class="cs-base-label">Becomes the project source</span>', card(2, "cs-master"));
    at(column, 3, "", card(3, "cs-master cs-sec"));
    state.keys.forEach((key, ki) => {
      at(column, 4 + ki, `<span class="cs-master-key">${esc(key.name)}</span>`, card(4 + ki, "cs-master"), ` data-key="${ki}"`);
      at(gutter, 4 + ki, '<span class="cs-rail"></span>', "cs-gut", ` data-key="${ki}"`);
    });
    at(column, 4 + keyCount, "", card(4 + keyCount, "cs-master cs-sec"));
    const masters = tables.flatMap((table) => valueColumns(state, table.id, plan)
      .filter((item) => !item.off)
      .map((item) => `<span class="cs-mcol"><span class="cs-dot cs-dot-small ${colorClass(table)}"></span><span>${esc(item.master)}</span></span>`));
    at(column, lastRow, `<div class="cs-mcols">${masters.join("")}</div>`, card(lastRow, "cs-master"));

    const template = ["150px"];
    for (let i = 0; i <= tables.length; i += 1) template.push("24px", "184px");
    return `<div class="cs-map-wrap"><div class="cs-map" style="grid-template-columns:${template.join(" ")}">${cells.join("")}</div></div>`;
  }

  function matchPaneHtml(data) {
    const alerts = warningAlerts(state, data.warnings, esc).map((alert) => {
      let actions = "";
      if (alert.fix) {
        const fixed = !openMismatches(state, [data.warnings.find((item) => warningId(item) === alert.id)]).length;
        if (!fixed) {
          actions = `<button class="sd-btn cs-fix-btn" type="button" data-act="convert" data-id="${esc(alert.fix.table_id)}" data-k="${keyIndexOf(alert.fix.key)}">Read as YYYYMM</button>`
            + (dismissed.has(alert.id) ? "" : `<button class="sd-btn cs-dismiss-btn" type="button" data-act="dismiss" data-wid="${esc(alert.id)}">Dismiss</button>`);
        }
      }
      return `<div class="cs-alert${alert.tone === "info" ? " cs-info" : ""}">${alert.tone === "info" ? ICONS.info : ICONS.warn}`
        + `<span class="cs-msg">${alert.html}</span>${actions}</div>`;
    }).join("");
    const bars = state.tables.map((table, index) => {
      const stats = data.stats?.[table.id] || {};
      const who = `<span class="cs-who"><span class="cs-dot ${colorClass(table)}"></span><span>${esc(tableLabel(table))}</span></span>`;
      if (index === 0) {
        return `${who}<div class="cs-mbar"><i class="${colorClass(table)}" style="width:100%"></i></div>`
          + `<span class="cs-match-text cs-num">${formatCount(stats.read || 0)} rows · base</span>`;
      }
      const pct = stats.read ? (stats.matched / stats.read) * 100 : 0;
      return `${who}<div class="cs-mbar" title="${formatCount(stats.matched || 0)} matched"><i class="${colorClass(table)}" style="width:${pct}%"></i>`
        + `<i class="cs-rest" style="width:${100 - pct}%"></i></div>`
        + `<span class="cs-match-text cs-num">${esc(matchText(stats, rowRule(state, table.id)))}</span>`;
    }).join("");
    const total = state.tables.length;
    const segments = coverageSegments(data.coverage);
    const shade = (n) => `color-mix(in srgb, var(--ar-color-accent, #2b6df6) ${Math.round(25 + 75 * (n / total))}%, var(--ar-color-text-subtle, #94a3b8))`;
    const name = (n) => (n === total ? `All ${total} tables` : plural(n, "table", "tables"));
    const cover = segments.length
      ? '<div class="cs-cover"><span class="sd-field-label">Combined Rows By Number Of Tables With Data</span><div class="cs-cover-bar">'
        + segments.map((seg) => `<div style="flex-grow:${seg.rows};background:${shade(seg.tables)}" title="${formatCount(seg.rows)} rows with data from ${name(seg.tables).toLowerCase()}">`
          + `${seg.rows / Math.max(1, data.row_count) > 0.07 ? formatCount(seg.rows) : ""}</div>`).join("")
        + '</div><div class="cs-cover-legend">'
        + segments.map((seg) => `<span><i style="background:${shade(seg.tables)}"></i>${name(seg.tables)} · ${formatCount(seg.rows)}</span>`).join("")
        + "</div></div>"
      : "";
    return (alerts ? `<div class="cs-alerts">${alerts}</div>` : "") + `<div class="cs-match-grid">${bars}</div>${cover}`;
  }

  function previewPaneHtml(data) {
    const keyNames = new Set(state.keys.map((key) => key.name));
    const owner = new Map();
    state.tables.forEach((table) => valueColumns(state, table.id, data.plan).forEach((item) => {
      if (!item.off) owner.set(item.master, table);
    }));
    const columns = data.columns || [];
    const rows = data.rows || [];
    const numeric = new Set(columns.filter((name) => !keyNames.has(name)
      && rows.every((row) => !row[name] || NUMERIC_TEXT.test(String(row[name]).trim()))));
    const head = columns.map((name) => {
      const table = owner.get(name);
      const cls = [keyNames.has(name) ? "" : "cs-th-value", table ? `cs-top-${table.color + 1}` : "", numeric.has(name) ? "cs-n" : ""].filter(Boolean).join(" ");
      return `<th class="${cls}">${esc(name)}</th>`;
    }).join("");
    const body = rows.map((row) => `<tr>${columns.map((name) => {
      const value = row[name];
      const cls = [keyNames.has(name) ? "cs-k" : "", numeric.has(name) ? "cs-n" : "", value ? "" : "cs-empty"].filter(Boolean).join(" ");
      return `<td class="${cls}">${value ? esc(value) : "·"}</td>`;
    }).join("")}</tr>`).join("");
    const legend = '<div class="cs-prev-legend"><span><span class="cs-dot cs-dot-key"></span>Key</span>'
      + state.tables.map((table) => `<span><span class="cs-dot ${colorClass(table)}"></span>${esc(tableLabel(table))}</span>`).join("")
      + `<span class="cs-prev-count cs-num">First ${formatCount(rows.length)} of ${formatCount(data.row_count)} rows · a dot means no value</span></div>`;
    return `${legend}<div class="cs-prev-wrap"><table class="cs-prev"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function resultHtml() {
    const data = preview?.data;
    const tables = validateCombinedState(state);
    const loading = !!preview?.loading;
    let sum = "";
    if (loading) sum = '<span class="cs-sum cs-quiet">Updating...</span>';
    else if (data) sum = `<span class="cs-sum cs-num">Combined: <b>${formatCount(data.row_count)}</b> rows × <b>${formatCount(data.column_count)}</b> columns</span>`;
    const tab = (id, label) => `<button class="cs-tab${resultTab === id ? " is-active" : ""}" type="button" role="tab" aria-selected="${resultTab === id}" data-act="tab" data-tab="${id}">${label}</button>`;
    const head = `<div class="cs-tabs" role="tablist">${tab("match", "Row Match")}${tab("preview", "Preview")}${sum}`
      + `<button class="sd-btn cs-refresh" type="button" data-act="refresh" title="Read every table again, including SQL Server tables"${loading || !tables.ok ? " disabled" : ""}>Read Again</button></div>`;
    let pane;
    if (!tables.ok) pane = `<p class="cs-quiet">${esc(tables.error)}</p>`;
    else if (preview?.error && preview.block === currentBlock() && !loading) pane = `<p class="cs-result-error">${esc(preview.error)}</p>`;
    else if (!data) pane = '<p class="cs-quiet">Reading the tables and matching rows...</p>';
    else pane = resultTab === "preview" ? previewPaneHtml(data) : matchPaneHtml(data);
    return `<div class="cs-result">${head}<div class="cs-pane${loading && data ? " is-stale" : ""}">${pane}</div></div>`;
  }

  function renderResult() {
    if (combineVisible && resultHost) resultHost.innerHTML = resultHtml();
  }

  function renderCombine() {
    if (!combineVisible || !mapHost) return;
    const scroll = mapHost.querySelector(".cs-map-wrap")?.scrollLeft || 0;
    mapHost.innerHTML = mapHtml();
    const wrap = mapHost.querySelector(".cs-map-wrap");
    if (wrap) wrap.scrollLeft = scroll;
    renderResult();
  }

  /** A small menu under a Join Map control; `onPick` gets the chosen item's value. */
  function openMenu(anchor, html, onPick) {
    closePop();
    pop = { anchor, onPick };
    popEl.innerHTML = html;
    popEl.hidden = false;
    placePop();
    const input = popEl.querySelector("input");
    input?.focus({ preventScroll: true });
    input?.select();
  }

  function menuItem(value, labelHtml, { selected = false, note = "", lead = null } = {}) {
    const leadHtml = lead ?? `<span class="cs-tick">${selected ? "✓" : ""}</span>`;
    return `<button class="cs-pop-item${selected ? " is-selected" : ""}" type="button" role="menuitem" data-value="${esc(value)}">${leadHtml}`
      + `<span class="cs-pop-label">${labelHtml}${note ? `<span class="cs-pop-note">${esc(note)}</span>` : ""}</span></button>`;
  }

  const inputRow = (id, value, label, button) => `<div class="cs-pop-row"><input class="cs-d-input" id="${id}" type="text" autocomplete="off" spellcheck="false" value="${esc(value)}" aria-label="${label}">`
    + `<button class="sd-btn" type="button" data-value="apply">${button}</button></div>`;

  function openKeyMenu(anchor, id, index) {
    const key = state.keys[index];
    const table = tableById(id);
    if (!key || !table) return;
    const entry = key.map[id] || {};
    const isBase = state.tables[0] === table;
    let html = `<div class="cs-pop-head">${esc(key.name)} comes from</div>`
      + (table.columns || []).map((column) => menuItem(`col:${column}`, `<span class="cs-mono">${esc(column)}</span>`, { selected: entry.column === column })).join("");
    if (!isBase) {
      html += '<div class="cs-pop-sep"></div>'
        + menuItem("fill", "Fill with a value", { selected: entry.fill !== undefined, note: "Every row of this table gets the same value" })
        + inputRow("csPopFill", entry.fill !== undefined ? entry.fill : "0", "Fill value", "Apply")
        + menuItem("any", "Match any value", { selected: !!entry.any, note: "Ignore this key for this table. Its rows repeat on every match." });
    }
    const mismatch = openMismatches(state, preview?.data?.warnings).some((item) => item.table_id === id && item.key === key.name);
    if (mismatch || entry.convert) {
      html += '<div class="cs-pop-sep"></div>'
        + menuItem("convert", "Read as YYYYMM", { selected: !!entry.convert, note: "Turns 2026-07 into 202607 before matching" });
    }
    openMenu(anchor, html, (value) => {
      if (value.startsWith("col:")) setKeyEntry(state, index, id, { column: value.slice(4) });
      else if (value === "fill" || value === "apply") {
        const fill = String(popEl.querySelector("#csPopFill")?.value || "").trim() || "0";
        setKeyEntry(state, index, id, { fill });
      } else if (value === "any") setKeyEntry(state, index, id, { any: true });
      else if (value === "convert") toggleKeyConvert(state, index, id);
      closePop();
      combineChanged();
    });
  }

  function openJoinMenu(anchor, id) {
    const current = rowRule(state, id);
    const html = `<div class="cs-pop-head">Rows to keep when joining ${esc(tableLabel(tableById(id)))}</div>`
      + Object.entries(ROW_RULES).map(([rule, info]) => menuItem(rule, info.label, { selected: current === rule, note: info.note, lead: vennIcon(rule) })).join("");
    openMenu(anchor, html, (value) => {
      setRowRule(state, id, value);
      closePop();
      combineChanged();
    });
  }

  function openColumnMenu(anchor, id, column) {
    const item = valueColumns(state, id, planOf()).find((entry) => entry.column === column);
    if (!item) return;
    const html = menuItem("toggle", item.off ? "Include column" : "Leave out column")
      + (item.off ? "" : '<div class="cs-pop-sep"></div><div class="cs-pop-head">Name in the combined table</div>'
        + inputRow("csPopName", item.master, "Column name", "Rename"));
    openMenu(anchor, html, (value) => {
      if (value === "toggle") toggleExclude(state, id, column);
      else if (value === "apply") setRename(state, id, column, popEl.querySelector("#csPopName")?.value);
      closePop();
      combineChanged();
    });
  }

  function openCardMenu(anchor, id) {
    const isBase = state.tables[0]?.id === id;
    const html = menuItem("details", "Source details", { note: "File or connection, nickname, columns" })
      + (isBase ? "" : menuItem("base", "Make base table", { note: "Move it to the front; keys are proposed again" }))
      + menuItem("remove", "Remove table");
    openMenu(anchor, html, (value) => {
      closePop();
      if (value === "details") openDetail("view", id);
      else if (value === "base") {
        moveTable(state, id, state.tables[0].id, false);
        combineChanged();
      } else if (value === "remove") removeTableAndSync(id);
    });
  }

  function openAddKeyMenu(anchor) {
    const columns = keyCandidates(state);
    const html = '<div class="cs-pop-head">Columns in the base table</div>'
      + (columns.length
        ? columns.map((column) => menuItem(column, `<span class="cs-mono">${esc(column)}</span>`)).join("")
        : '<div class="cs-pop-head cs-pop-quiet">Every column is already a key</div>');
    openMenu(anchor, html, (value) => {
      addKey(state, value);
      closePop();
      combineChanged();
    });
  }

  function onCombineClick(event) {
    const el = event.target.closest("[data-act]");
    if (!el || busy || !combineEl.contains(el)) return;
    const { act, id } = el.dataset;
    const index = el.dataset.k !== undefined ? Number(el.dataset.k) : -1;
    if (pop?.anchor === el) {
      closePop();
      return;
    }
    if (act === "details") openDetail("view", id);
    else if (act === "card-menu") {
      event.stopPropagation();
      openCardMenu(el, id);
    } else if (act === "join") openJoinMenu(el, id);
    else if (act === "key") openKeyMenu(el, id, index);
    else if (act === "column") openColumnMenu(el, id, el.dataset.col);
    else if (act === "add-key") openAddKeyMenu(el);
    else if (act === "remove-key") {
      if (removeKey(state, index)) combineChanged();
      else setCombineStatus("Keep at least one key so rows can be matched.", "error");
    } else if (act === "convert") {
      toggleKeyConvert(state, index, id);
      combineChanged();
    } else if (act === "dismiss") {
      dismissed.add(el.dataset.wid);
      setCombineStatus("");
      renderResult();
    } else if (act === "tab") {
      resultTab = el.dataset.tab === "preview" ? "preview" : "match";
      renderResult();
    } else if (act === "refresh") schedulePreview(0, true);
  }

  function onCombineKeydown(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    const cardEl = event.target.closest?.('[data-act="details"]');
    if (!cardEl || event.target !== cardEl) return;
    event.preventDefault();
    openDetail("view", cardEl.dataset.id);
  }

  /** Light up one key's row across every card. */
  function onMapHover(event) {
    const map = mapHost?.querySelector(".cs-map");
    if (!map) return;
    const cell = event.target.closest?.("[data-key]");
    const key = cell && map.contains(cell) ? cell.dataset.key : "";
    if (map.dataset.hk === key) return;
    map.dataset.hk = key;
    map.querySelectorAll(".cs-hl").forEach((node) => node.classList.remove("cs-hl"));
    if (key) map.querySelectorAll(`[data-key="${key}"]`).forEach((node) => node.classList.add("cs-hl"));
  }

  /* ---------------- keyboard and outside clicks ---------------- */

  function onKeydownCapture(event) {
    if (event.key === "Escape") {
      if (pop) {
        const anchor = pop.anchor;
        closePop();
        anchor?.focus({ preventScroll: true });
      } else if (detail) closeDetail();
      else return;
      event.stopPropagation();
      event.preventDefault();
      return;
    }
    if (event.key === "Enter" && pop?.onPick && event.target.tagName === "INPUT" && popEl.contains(event.target)) {
      event.preventDefault();
      pop.onPick("apply");
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
      showCombine(false);
      state = createCombinedState();
      preview = null;
      previewToken += 1;
      dismissed.clear();
      resultTab = "match";
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
    /** The import window's pages for the current table count. */
    steps() {
      return importSteps(state);
    },
    /** Show or hide the Combine step's page. */
    showCombine,
    /** The Combine step's own status line, for messages while it shows. */
    setCombineStatus,
    /** Whether the table list can go on to the Combine step. */
    validateTables() {
      return validateCombinedState(state);
    },
    /** Whether the combined settings can go on past the Combine step. */
    validate() {
      const error = combineProblem(state, preview, dismissed);
      return { ok: !error, error };
    },
    getCombinedBlock() {
      return toCombinedBlock(state);
    },
    getState() {
      return state;
    },
  };
}
