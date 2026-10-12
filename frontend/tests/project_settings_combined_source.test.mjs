import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const {
  addKey,
  addTable,
  autoMapKey,
  columnUses,
  combineProblem,
  combinedSourceSummary,
  coverageSegments,
  createCombinedSourceFeature,
  createCombinedState,
  describeTableRequest,
  detectKeys,
  fromCombinedBlock,
  importSteps,
  keyCandidates,
  matchText,
  moveTable,
  nameToken,
  openMismatches,
  previewCombinedRequest,
  previewRequestBody,
  removeKey,
  removeTable,
  restoreTableColumns,
  rowRule,
  saveCombinedRequest,
  setKeyEntry,
  setRename,
  setRowRule,
  setTableColumns,
  singleSettingsFromTable,
  suggestNickname,
  tableFromSingleSettings,
  tableGroups,
  tableLabel,
  tableSourceText,
  toCombinedBlock,
  toggleExclude,
  toggleKeyConvert,
  validateCombinedState,
  valueColumns,
  warningAlerts,
  warningId,
} = await import(new URL("../ui/project_settings/project_settings_combined_source.js", import.meta.url));

const read = async (path) => (await readFile(new URL(path, import.meta.url), "utf8")).replaceAll("\r\n", "\n");
const sourceDataJs = await read("../ui/project_settings/project_settings_source_data.js");
const coordinatorJs = await read("../ui/project_settings/project_settings.js");
const html = await read("../ui/project_settings/project_settings.html");
const combinedJs = await read("../ui/project_settings/project_settings_combined_source.js");

const KEYS = ["CO_CD", "PROD_CD", "acc_yrmo", "sys_yrmo"];
const sql = (table) => ({
  source_type: "mssql",
  mssql: { server: "IBNRSQL01", database: "ResQ_Monthly", table, authentication: "windows" },
});
const LOSS = { ...sql("dbo.ResQ_Channel_Loss_202609"), columns: [...KEYS, "Paid_Loss"], row_count: 300 };
const CLOSED = { ...sql("dbo.ResQ_Channel_Closed_Counts_202609"), columns: [...KEYS, "Closed_Counts"], row_count: 200 };
const EP = {
  source_type: "csv",
  csv_path: "E:\\NJ\\EP_EEX_NJ_2026Sep_channel.csv",
  columns: ["Co_Cd", "PROD_CD", "acc_yrmo", "FACID", "Earned Premium"],
  row_count: 72,
  dropped_columns: ["Unnamed: 9"],
};

function threeTables() {
  const state = createCombinedState();
  addTable(state, LOSS, { columns: LOSS.columns, row_count: LOSS.row_count });
  addTable(state, CLOSED, { columns: CLOSED.columns, row_count: CLOSED.row_count, nickname: "Closed" });
  addTable(state, EP, { ...EP, nickname: "EP" });
  return state;
}

test("name tokens ignore case, spaces and underscores", () => {
  assert.equal(nameToken("Co_Cd"), nameToken("CO_CD"));
  assert.equal(nameToken("Earned Premium"), "earnedpremium");
});

test("adding tables assigns ids and colours and proposes keys from the base", () => {
  const state = threeTables();
  assert.deepEqual(state.tables.map((table) => table.id), ["t1", "t2", "t3"]);
  assert.deepEqual(state.tables.map((table) => table.color), [0, 1, 2]);
  assert.deepEqual(state.keys.map((key) => key.name), KEYS);
  const co = state.keys.find((key) => key.name === "CO_CD");
  assert.deepEqual(co.map, { t1: { column: "CO_CD" }, t2: { column: "CO_CD" }, t3: { column: "Co_Cd" } });
  const sys = state.keys.find((key) => key.name === "sys_yrmo");
  assert.deepEqual(sys.map.t3, { fill: "0" });
});

test("a key a table lacks matches any value unless it is a month", () => {
  assert.deepEqual(autoMapKey({ columns: ["A"] }, "CHANNEL"), { any: true });
  assert.deepEqual(autoMapKey({ columns: ["A"] }, "sys_yrmo"), { fill: "0" });
  assert.deepEqual(autoMapKey({ columns: ["channel"] }, "CHANNEL"), { column: "channel" });
});

test("key detection keeps only base columns another table shares", () => {
  const state = createCombinedState();
  addTable(state, LOSS, { columns: LOSS.columns });
  assert.deepEqual(state.keys, []);
  addTable(state, EP, EP);
  assert.deepEqual(state.keys.map((key) => key.name), ["CO_CD", "PROD_CD", "acc_yrmo"]);
});

test("a table read after it was added gets its keys matched then", () => {
  const state = createCombinedState();
  addTable(state, LOSS);
  addTable(state, CLOSED, { columns: CLOSED.columns });
  assert.deepEqual(state.keys, [], "an unread base proposes nothing");
  setTableColumns(state, "t1", { columns: LOSS.columns, row_count: 300 });
  assert.deepEqual(state.keys.map((key) => key.name), KEYS);
  addTable(state, EP);
  assert.deepEqual(state.keys[0].map.t3, { any: true });
  setTableColumns(state, "t3", EP);
  assert.deepEqual(state.keys[0].map.t3, { column: "Co_Cd" });
  assert.equal(state.tables[2].row_count, 72);
});

test("reordering moves a table and a new base proposes the keys again", () => {
  const state = threeTables();
  assert.equal(moveTable(state, "t3", "t2"), false);
  assert.deepEqual(state.tables.map((table) => table.id), ["t1", "t3", "t2"]);
  assert.equal(moveTable(state, "t2", "t3", true), false);
  assert.deepEqual(state.tables.map((table) => table.id), ["t1", "t3", "t2"]);
  state.rows.t3 = "match";
  assert.equal(moveTable(state, "t3", "t1"), true);
  assert.deepEqual(state.tables.map((table) => table.id), ["t3", "t1", "t2"]);
  assert.equal(state.rows.t3, undefined, "the base has no row rule");
  assert.deepEqual(state.keys.map((key) => key.name), ["Co_Cd", "PROD_CD", "acc_yrmo"]);
  assert.deepEqual(state.keys[0].map.t1, { column: "CO_CD" });
});

test("removing a table drops its settings and the base proposes keys again", () => {
  const state = threeTables();
  state.rows.t3 = "base";
  state.exclude.t3 = ["FACID"];
  removeTable(state, "t3");
  assert.equal(state.rows.t3, undefined);
  assert.equal(state.exclude.t3, undefined);
  assert.ok(state.keys.every((key) => !("t3" in key.map)));
  removeTable(state, "t1");
  assert.deepEqual(state.tables.map((table) => table.id), ["t2"]);
  assert.deepEqual(state.keys, []);
});

test("back to one table gives the single-table form that table's settings", () => {
  const state = threeTables();
  removeTable(state, "t1");
  removeTable(state, "t2");
  assert.deepEqual(singleSettingsFromTable(state.tables[0]), {
    method: "csv",
    csvPath: "E:\\NJ\\EP_EEX_NJ_2026Sep_channel.csv",
    profile: null,
  });
  assert.deepEqual(singleSettingsFromTable(LOSS), {
    method: "mssql",
    csvPath: "",
    profile: { server: "IBNRSQL01", database: "ResQ_Monthly", table: "dbo.ResQ_Channel_Loss_202609", authentication: "windows" },
  });
});

test("the single-table form becomes the first table, with the form's own messages", () => {
  assert.deepEqual(tableFromSingleSettings({ method: "csv", csvPath: "" }), { error: "Choose a CSV file to import." });
  assert.deepEqual(
    tableFromSingleSettings({ method: "mssql", profile: { server: "S", database: "" } }),
    { error: "Enter the server and database name first." },
  );
  assert.deepEqual(
    tableFromSingleSettings({ method: "mssql", profile: { server: "S", database: "D", table: "" } }),
    { error: "Select a table or view to import." },
  );
  assert.deepEqual(tableFromSingleSettings({ method: "csv", csvPath: " C:\\a.csv " }), {
    spec: { source_type: "csv", csv_path: "C:\\a.csv" },
  });
});

test("a blank nickname shows the table name", () => {
  const state = threeTables();
  assert.equal(tableLabel(state.tables[0]), "dbo.ResQ_Channel_Loss_202609");
  assert.equal(tableLabel(state.tables[1]), "Closed");
  assert.equal(tableLabel({ source_type: "csv", csv_path: "E:\\x\\Budget.csv", nickname: "  " }), "Budget.csv");
});

test("a suggested nickname drops the schema, numbers and words every other table shares", () => {
  const others = [LOSS];
  assert.equal(suggestNickname(CLOSED, others), "Closed Counts");
  assert.equal(suggestNickname(LOSS, []), "ResQ Channel Loss");
  assert.equal(suggestNickname({ source_type: "csv", csv_path: "E:\\EP.csv" }, others), "EP");
  const long = { source_type: "csv", csv_path: "E:\\An_Extremely_Long_Table_Name_That_Keeps_Going.csv" };
  assert.ok(suggestNickname(long, []).length <= 24);
});

test("nicknames are trimmed and capped at 24 characters", () => {
  const state = createCombinedState();
  const table = addTable(state, EP, { nickname: "  A nickname that is far too long to keep  " });
  assert.equal(table.nickname, "A nickname that is far t");
});

test("tables group by SQL connection, with CSV files in their own group", () => {
  const state = threeTables();
  addTable(state, { ...sql("dbo.Other"), mssql: { ...sql("dbo.Other").mssql, database: "Archive" } });
  addTable(state, sql("dbo.ResQ_Channel_Reported_Counts_202609"));
  const groups = tableGroups(state);
  assert.deepEqual(groups.map((group) => [group.kind, group.database, group.tables.map((t) => t.id)]), [
    ["mssql", "ResQ_Monthly", ["t1", "t2", "t5"]],
    ["csv", undefined, ["t3"]],
    ["mssql", "Archive", ["t4"]],
  ]);
});

test("the details window says what each column is used as", () => {
  const state = threeTables();
  state.exclude.t3 = ["FACID"];
  assert.deepEqual(columnUses(state, "t3"), [
    { column: "Co_Cd", use: "Key → CO_CD", faint: false },
    { column: "PROD_CD", use: "Key", faint: false },
    { column: "acc_yrmo", use: "Key", faint: false },
    { column: "FACID", use: "Left out", faint: true },
    { column: "Earned Premium", use: "Value column", faint: false },
    { column: "Unnamed: 9", use: "Empty, dropped on import", faint: true },
  ]);
});

test("serialization writes the decision-3 block and reads it back", () => {
  const state = threeTables();
  state.rows.t3 = "match";
  state.exclude.t3 = ["FACID"];
  state.rename.t2 = { Closed_Counts: "Closed" };
  const block = toCombinedBlock(state);
  assert.deepEqual(block.tables, [
    { id: "t1", nickname: "", source_type: "mssql", mssql: LOSS.mssql },
    { id: "t2", nickname: "Closed", source_type: "mssql", mssql: CLOSED.mssql },
    { id: "t3", nickname: "EP", source_type: "csv", csv_path: EP.csv_path },
  ]);
  assert.deepEqual(block.rows, { t2: "all", t3: "match" });
  assert.deepEqual(block.exclude, { t3: ["FACID"] });
  assert.deepEqual(block.rename, { t2: { Closed_Counts: "Closed" } });
  assert.deepEqual(block.keys[3], { name: "sys_yrmo", map: { t1: { column: "sys_yrmo" }, t2: { column: "sys_yrmo" }, t3: { fill: "0" } } });
  const restored = fromCombinedBlock(JSON.parse(JSON.stringify(block)));
  assert.deepEqual(toCombinedBlock(restored), block);
  assert.ok(restored.tables.every((table) => table.columns === null), "columns are read again, not stored");
});

test("reading a block drops duplicate ids and entries for unknown tables", () => {
  const state = fromCombinedBlock({
    tables: [{ id: "t1", source_type: "csv", csv_path: "a.csv" }, { id: "t1", source_type: "csv", csv_path: "b.csv" }, { id: "t2", source_type: "csv", csv_path: "c.csv" }],
    keys: [{ name: "K", map: { t1: { column: "K" }, t9: { column: "K" } } }],
    rows: { t1: "match", t2: "base", t9: "all" },
    exclude: { t9: ["X"] },
  });
  assert.deepEqual(state.tables.map((table) => table.csv_path), ["a.csv", "c.csv"]);
  assert.deepEqual(state.keys[0].map, { t1: { column: "K" } });
  assert.deepEqual(state.rows, { t2: "base" });
  assert.deepEqual(state.exclude, {});
});

test("combined settings need two read tables and a shared key", () => {
  const state = createCombinedState();
  addTable(state, LOSS, { columns: LOSS.columns });
  assert.equal(validateCombinedState(state).ok, false);
  addTable(state, EP, { nickname: "EP" });
  assert.deepEqual(validateCombinedState(state), { ok: false, error: "EP has not been read yet." });
  setTableColumns(state, "t2", { columns: ["Other"], row_count: 1 });
  assert.deepEqual(validateCombinedState(state), { ok: false, error: "The tables share no column to match rows on." });
  setTableColumns(state, "t2", EP);
  assert.deepEqual(validateCombinedState(state), { ok: true, error: "" });
  detectKeys(state);
  assert.equal(state.keys.length, 3);
});

test("the source data tab only mounts the combined module and keeps the single path", () => {
  assert.match(sourceDataJs, /createCombinedSourceFeature,\n\} from "\.\/project_settings_combined_source\.js\?v=20261012combined3";/);
  assert.match(sourceDataJs, /function validateImportSettings\(\) \{\n\s+if \(combinedSource\.isActive\(\)\) \{\n\s+return \{ \.\.\.combinedSource\.validate\(\), method: SOURCE_TYPE_COMBINED/);
  // With one table the single-table checks run exactly as before.
  assert.match(sourceDataJs, /if \(method === SOURCE_TYPE_MSSQL\) \{\n\s+if \(!profile\.server \|\| !profile\.database\) error = "Enter the server and database name first\.";/);
  assert.match(coordinatorJs, /project_settings_source_data\.js\?v=20261012combined3/);
  assert.match(coordinatorJs, /createSourceDataFeature\(\{[\s\S]*fetchImpl: fetch\.bind\(window\),/);
  assert.match(html, /project_settings_combined_source\.css\?v=/);
  assert.match(html, /project_settings\.js\?v=20261012combined3/);
});

test("a table is described through the client route with the table spec", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return { ok: true, json: async () => ({ ok: true, columns: ["A"], row_count: 2, dropped_columns: [] }) };
  };
  const table = { source_type: "csv", csv_path: "E:\a.csv", id: "t2", nickname: "A" };
  assert.deepEqual(await describeTableRequest(fetchImpl, table), { ok: true, columns: ["A"], row_count: 2, dropped_columns: [] });
  assert.deepEqual(calls, [["/source_table/combined/describe", { table, refresh: false }]]);
  const failing = async () => ({ ok: false, status: 404, json: async () => ({ detail: "Source table file was not found: E:\a.csv" }) });
  assert.deepEqual(await describeTableRequest(failing, table), { ok: false, error: "Source table file was not found: E:\a.csv" });
  assert.deepEqual(await describeTableRequest(null, table), { ok: false, error: "Not available." });
});

/* ---------------- Combine step ---------------- */

test("the Combine step sits between Source and Datasets only with two or more tables", () => {
  const state = createCombinedState();
  assert.deepEqual(importSteps(state), ["settings", "datasets", "classes"]);
  addTable(state, LOSS, { columns: LOSS.columns });
  assert.deepEqual(importSteps(state), ["settings", "datasets", "classes"], "one table is today's window");
  addTable(state, EP, EP);
  assert.deepEqual(importSteps(state), ["settings", "combine", "datasets", "classes"]);
  removeTable(state, "t2");
  assert.deepEqual(importSteps(state), ["settings", "datasets", "classes"]);
});

test("a key cell points at a column, a fill or any value; the base column names the key", () => {
  const state = threeTables();
  const sys = state.keys.findIndex((key) => key.name === "sys_yrmo");
  setKeyEntry(state, sys, "t3", { fill: "202609" });
  assert.deepEqual(state.keys[sys].map.t3, { fill: "202609" });
  setKeyEntry(state, sys, "t3", { any: true });
  assert.deepEqual(state.keys[sys].map.t3, { any: true });
  setKeyEntry(state, 0, "t3", { column: "Co_Cd" });
  assert.deepEqual(state.keys[0].map.t3, { column: "Co_Cd" });
  setKeyEntry(state, 0, "t1", { fill: "07" });
  assert.deepEqual(state.keys[0].map.t1, { column: "CO_CD" }, "the base always names a column");
  setKeyEntry(state, 0, "t1", { column: "PROD_CD" });
  assert.equal(state.keys[0].name, "CO_CD", "a base column that is already a key is refused");
  setKeyEntry(state, 0, "t1", { column: "Paid_Loss" });
  assert.equal(state.keys[0].name, "Paid_Loss");
});

test("Read as YYYYMM toggles on a key column only", () => {
  const state = threeTables();
  const acc = state.keys.findIndex((key) => key.name === "acc_yrmo");
  toggleKeyConvert(state, acc, "t3");
  assert.deepEqual(state.keys[acc].map.t3, { column: "acc_yrmo", convert: "yyyymm" });
  toggleKeyConvert(state, acc, "t3");
  assert.deepEqual(state.keys[acc].map.t3, { column: "acc_yrmo" });
  const sys = state.keys.findIndex((key) => key.name === "sys_yrmo");
  toggleKeyConvert(state, sys, "t3");
  assert.deepEqual(state.keys[sys].map.t3, { fill: "0" });
});

test("keys are added from base columns and the last key stays", () => {
  const state = createCombinedState();
  addTable(state, LOSS, { columns: LOSS.columns });
  addTable(state, EP, EP);
  assert.deepEqual(keyCandidates(state), ["sys_yrmo", "Paid_Loss"]);
  const key = addKey(state, "sys_yrmo");
  assert.deepEqual(key, { name: "sys_yrmo", map: { t1: { column: "sys_yrmo" }, t2: { fill: "0" } } });
  assert.equal(addKey(state, "sys_yrmo"), null, "a key is added once");
  assert.equal(removeKey(state, 3), true);
  assert.equal(removeKey(state, 0), true);
  assert.equal(removeKey(state, 0), true);
  assert.equal(removeKey(state, 0), false);
  assert.deepEqual(state.keys.map((item) => item.name), ["acc_yrmo"]);
});

test("row rules apply to non-base tables only and default to All Rows", () => {
  const state = threeTables();
  assert.equal(rowRule(state, "t2"), "all");
  setRowRule(state, "t2", "match");
  setRowRule(state, "t3", "base");
  setRowRule(state, "t1", "match");
  setRowRule(state, "t2", "outer");
  assert.deepEqual(state.rows, { t2: "match", t3: "base" });
  assert.deepEqual(toCombinedBlock(state).rows, { t2: "match", t3: "base" });
});

test("value columns follow leave-out and rename at once and take the preview's clash names", () => {
  const state = threeTables();
  toggleExclude(state, "t3", "FACID");
  setRename(state, "t2", "Closed_Counts", "Closed");
  const plan = [
    { table_id: "t3", column: "Earned Premium", master: "Earned Premium_EP", off: false, conflict: true, renamed: false },
  ];
  assert.deepEqual(valueColumns(state, "t3", plan), [
    { column: "FACID", master: "FACID", off: true, conflict: false, renamed: false },
    { column: "Earned Premium", master: "Earned Premium_EP", off: false, conflict: true, renamed: false },
  ]);
  assert.deepEqual(valueColumns(state, "t2"), [
    { column: "Closed_Counts", master: "Closed", off: false, conflict: false, renamed: true },
  ]);
  setRename(state, "t2", "Closed_Counts", " Closed_Counts ");
  toggleExclude(state, "t3", "FACID");
  assert.deepEqual(toCombinedBlock(state).rename, {}, "renaming back to its own name clears it");
  assert.deepEqual(toCombinedBlock(state).exclude, {});
  setRename(state, "t3", "Earned Premium", "EP Premium");
  assert.deepEqual(valueColumns(state, "t3", plan)[1], {
    column: "Earned Premium", master: "EP Premium", off: false, conflict: false, renamed: true,
  });
});

test("the preview request carries the serialized block", async () => {
  const state = threeTables();
  state.exclude.t3 = ["FACID"];
  const body = previewRequestBody("Aug Fake", state, true);
  assert.deepEqual(body, { project_name: "Aug Fake", combined: toCombinedBlock(state), refresh: true });
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return { ok: false, status: 400, json: async () => ({ detail: "A combined source needs at least one key." }) };
  };
  assert.deepEqual(await previewCombinedRequest(fetchImpl, body), { ok: false, error: "A combined source needs at least one key." });
  assert.deepEqual(calls, [["/source_table/combined/preview", JSON.parse(JSON.stringify(body))]]);
});

const MISMATCH = {
  kind: "format_mismatch", table_id: "t3", table: "EP", key: "acc_yrmo",
  sample: "2026-04", base_sample: "202604", matched: 0, fix: { convert: "yyyymm" },
};

test("Next from Combine waits for the current preview and an answered format mismatch", () => {
  const state = threeTables();
  const block = JSON.stringify(toCombinedBlock(state));
  assert.equal(combineProblem(state, null), "Wait for the preview to finish.");
  const data = { ok: true, warnings: [MISMATCH] };
  assert.equal(
    combineProblem(state, { data, block }),
    "EP stores acc_yrmo as 2026-04. Read it as YYYYMM or dismiss the warning.",
  );
  assert.equal(combineProblem(state, { data, block }, new Set([warningId(MISMATCH)])), "");
  assert.equal(combineProblem(state, { data: null, error: "Key columns were not found: X in EP.", block }), "Key columns were not found: X in EP.");
  const acc = state.keys.findIndex((key) => key.name === "acc_yrmo");
  toggleKeyConvert(state, acc, "t3");
  assert.equal(combineProblem(state, { data, block }), "Wait for the preview to finish.", "a stale preview is not enough");
  assert.equal(openMismatches(state, data.warnings).length, 0, "converted keys raise no mismatch");
  assert.equal(combineProblem(state, { data, block: JSON.stringify(toCombinedBlock(state)) }), "");
  state.keys = [];
  assert.equal(combineProblem(state, { data, block }), "The tables share no column to match rows on.");
});

test("Row Match words the warnings, the bars and the coverage", () => {
  const state = threeTables();
  const alerts = warningAlerts(state, [
    MISMATCH,
    { kind: "repeat", table_id: "t2", table: "Closed", max_repeat: 3, any_keys: ["sys_yrmo"] },
    { kind: "filled_rows", table_id: "t3", table: "EP", fills: { sys_yrmo: "0" }, added: 72 },
    { kind: "name_clash", table_id: "t3", table: "EP", column: "Earned Premium", master: "Earned Premium_EP" },
  ]);
  assert.deepEqual(alerts.map((alert) => alert.tone), ["warn", "warn", "info", "info"]);
  assert.deepEqual(alerts[0].fix, { table_id: "t3", key: "acc_yrmo" });
  assert.match(alerts[0].html, /<b>EP<\/b> stores acc_yrmo as <span class="cs-mono">2026-04<\/span>; the base uses <span class="cs-mono">202604<\/span>\. 0 of its rows match\./);
  assert.match(alerts[1].html, /Each <b>Closed<\/b> row lands on up to 3 combined rows because sys_yrmo matches any value\./);
  assert.match(alerts[2].html, /<b>EP<\/b> has no sys_yrmo, so its rows sit at sys_yrmo = 0 and form 72 rows of their own\./);
  assert.match(alerts[3].html, /Two tables have <b>Earned Premium<\/b>\. The EP copy is named <span class="cs-mono">Earned Premium_EP<\/span>\./);
  assert.equal(matchText({ read: 72, matched: 0, added: 72, left_out: 0 }, "all"), "0 of 72 matched · 72 added as new rows");
  assert.equal(matchText({ read: 2, matched: 1, added: 0, left_out: 1, base_rows_dropped: 9 }, "match"), "1 of 2 matched · 1 left out · 9 combined rows dropped");
  assert.equal(matchText({ read: 5, matched: 5 }, "base"), "5 of 5 matched · all matched");
  assert.deepEqual(coverageSegments({ 1: 84, 3: 1200, 2: 0 }), [{ tables: 3, rows: 1200 }, { tables: 1, rows: 84 }]);
});

test("the import window's steps come from the combined module and its group headers name no connection", () => {
  assert.match(sourceDataJs, /panelStep = combinedSource\.steps\(\)\.includes\(step\) \? step : "settings";/);
  assert.match(sourceDataJs, /combinedSource\.showCombine\(panelStep === "combine"\);/);
  assert.match(sourceDataJs, /getProjectName: \(\) => String\(getSelectedProject\(\)\?\.name \|\| ""\)/);
  assert.match(coordinatorJs, /getSelectedProject: \(\) => selectedProject,\n\s+\/\/ Admin-editable defaults/);
  assert.doesNotMatch(combinedJs, /group\.server|group\.database/);
  assert.match(combinedJs, /one shared connection/);
});

/* ---------------- Saved source: reopen, save, import, header ---------------- */

const SAVED = {
  tables: [
    { id: "t1", nickname: "Loss", source_type: "mssql", mssql: { server: "IBNRSQL01", database: "ResQ_Monthly", table: "dbo.Loss", authentication: "windows" } },
    { id: "t4", nickname: "", source_type: "csv", csv_path: "\\\\share\\NJ\\EP.csv" },
  ],
  keys: [
    { name: "CO_CD", map: { t1: { column: "CO_CD" }, t4: { column: "Co_Cd" } } },
    { name: "sys_yrmo", map: { t1: { column: "sys_yrmo" }, t4: { fill: "0" } } },
  ],
  rows: { t4: "match" },
  exclude: { t4: ["FACID"] },
  rename: { t4: { "Earned Premium": "Budget Premium" } },
};

test("a saved combined source reopens with its tables, nicknames, keys and rules", () => {
  const state = fromCombinedBlock(SAVED);
  assert.deepEqual(state.tables.map((table) => [table.id, tableLabel(table), table.restored]), [
    ["t1", "Loss", true],
    ["t4", "EP.csv", true],
  ]);
  assert.deepEqual(toCombinedBlock(state), SAVED);
  // Reading a restored table's columns keeps the saved keys, even the base's,
  // where a fresh read would propose the keys again.
  restoreTableColumns(state, "t1", { columns: ["CO_CD", "sys_yrmo", "co_cd2"], row_count: 9, dropped_columns: ["Unnamed: 9"] });
  restoreTableColumns(state, "t4", { columns: ["Co_Cd", "FACID", "Earned Premium"], row_count: 72 });
  assert.deepEqual(toCombinedBlock(state), SAVED);
  assert.equal(state.tables[0].restored, undefined);
  assert.deepEqual(state.tables[0].dropped_columns, ["Unnamed: 9"]);
  assert.equal(state.tables[1].row_count, 72);
  assert.deepEqual(validateCombinedState(state), { ok: true, error: "" });
  // Once the person changes a table, its keys are matched by name again.
  setTableColumns(state, "t1", { columns: ["CO_CD", "Other"], row_count: 1 });
  assert.deepEqual(state.keys.map((key) => key.name), ["CO_CD"]);
});

test("the header and its details panel describe a saved combined source", () => {
  assert.deepEqual(combinedSourceSummary(SAVED), {
    tableCount: 2,
    keyCount: 2,
    tables: [
      { label: "Loss", kind: "SQL table", source: "IBNRSQL01 · ResQ_Monthly · dbo.Loss", color: 0 },
      { label: "EP.csv", kind: "CSV file", source: "\\\\share\\NJ\\EP.csv", color: 1 },
    ],
  });
  assert.equal(tableSourceText({ source_type: "csv", csv_path: "E:\\a.csv" }), "E:\\a.csv");
  assert.deepEqual(combinedSourceSummary(null), { tableCount: 0, keyCount: 0, tables: [] });
});

test("the combined source is saved through its own client route", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push([url, JSON.parse(init.body)]);
    return { ok: true, json: async () => ({ ok: true, source_type: "combined", combined: SAVED }) };
  };
  const body = { project_name: "P", combined: SAVED };
  assert.deepEqual(await saveCombinedRequest(fetchImpl, body), { ok: true, source_type: "combined", combined: SAVED });
  assert.deepEqual(calls, [["/source_table/combined/save", body]]);
  const refused = async () => ({ ok: false, status: 400, json: async () => ({ detail: "A combined source needs at least two tables." }) });
  assert.deepEqual(await saveCombinedRequest(refused, body), { ok: false, error: "A combined source needs at least two tables." });
});

test("reopened settings import again unchanged, and a change needs the Combine check again", async () => {
  const calls = [];
  const feature = createCombinedSourceFeature({
    fetchImpl: async (url, init) => {
      calls.push([url, JSON.parse(init.body)]);
      return { ok: true, json: async () => ({ ok: true, source_type: "combined" }) };
    },
    getProjectName: () => "NJ_Annual_Prod_202608_Fake",
    applySingleSettings: (settings) => calls.push(["single", settings]),
  });
  assert.equal(feature.isActive(), false);
  // Import Again opens without reading the tables and goes straight to the scope.
  feature.load(SAVED, { read: false });
  assert.equal(feature.isActive(), true);
  assert.deepEqual(feature.getCombinedBlock(), SAVED);
  assert.deepEqual(feature.validate(), { ok: true, error: "" });
  // The single-table form underneath holds the base table, for going back to one.
  assert.deepEqual(calls, [["single", { method: "mssql", csvPath: "", profile: SAVED.tables[0].mssql }]]);
  calls.length = 0;
  assert.deepEqual(await feature.save(), { ok: true, source_type: "combined" });
  assert.deepEqual(calls, [["/source_table/combined/save", { project_name: "NJ_Annual_Prod_202608_Fake", combined: SAVED }]]);
  // A changed rule is no longer the saved settings: the tables must be read and previewed.
  feature.getState().rows.t4 = "all";
  assert.equal(feature.validate().ok, false);
  feature.reset();
  assert.equal(feature.isActive(), false);
  // A block with fewer than two tables opens the single-table form.
  feature.load({ tables: [SAVED.tables[0]] }, { read: false });
  assert.equal(feature.isActive(), false);
});

test("Import Data saves a combined source through its own route, then imports it", () => {
  // Single-table settings still save through the coordinator's profile save.
  assert.match(sourceDataJs, /const saved = combined \? await saveCombinedSource\(\) : await onProfileSave\(method, profile, csvPath\);/);
  assert.match(sourceDataJs, /const result = await onImportData\(method, scope\);/);
  assert.match(sourceDataJs, /async function saveCombinedSource\(\) \{\n\s+const result = await combinedSource\.save\(\);/);
  assert.doesNotMatch(sourceDataJs, /Importing a combined source is not available yet/);
  // The window reopens on a saved combined source; Import Again skips reading its tables.
  assert.match(sourceDataJs, /if \(!method && sourceState\.sourceType === SOURCE_TYPE_COMBINED\) \{\n\s+combinedSource\.load\(sourceState\.combined, \{ read: readTables \}\);/);
  assert.match(sourceDataJs, /openSourcePanel\(\{ readTables: action !== "again" \}\);/);
  // The header's dots and chip exist only for a combined source.
  assert.match(html, /<span class="sd-file-dots" id="summaryPathDots" aria-hidden="true" hidden><\/span>/);
  assert.match(html, /<span class="sd-file-chip" id="summaryPathChip" hidden><\/span>/);
  assert.match(coordinatorJs, /project_settings_source_import\.js\?v=20261012combined3/);
});
