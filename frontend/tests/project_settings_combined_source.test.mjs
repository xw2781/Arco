import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const {
  addTable,
  autoMapKey,
  columnUses,
  createCombinedState,
  describeTableRequest,
  detectKeys,
  fromCombinedBlock,
  moveTable,
  nameToken,
  removeTable,
  setTableColumns,
  singleSettingsFromTable,
  suggestNickname,
  tableFromSingleSettings,
  tableGroups,
  tableLabel,
  toCombinedBlock,
  validateCombinedState,
} = await import(new URL("../ui/project_settings/project_settings_combined_source.js", import.meta.url));

const read = async (path) => (await readFile(new URL(path, import.meta.url), "utf8")).replaceAll("\r\n", "\n");
const sourceDataJs = await read("../ui/project_settings/project_settings_source_data.js");
const coordinatorJs = await read("../ui/project_settings/project_settings.js");
const html = await read("../ui/project_settings/project_settings.html");

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
  assert.match(sourceDataJs, /import \{ createCombinedSourceFeature \} from "\.\/project_settings_combined_source\.js\?v=20261012combined1";/);
  assert.match(sourceDataJs, /function validateImportSettings\(\) \{\n\s+if \(combinedSource\.isActive\(\)\) return combinedSource\.validate\(\);/);
  // With one table the single-table checks run exactly as before.
  assert.match(sourceDataJs, /if \(method === SOURCE_TYPE_MSSQL\) \{\n\s+if \(!profile\.server \|\| !profile\.database\) error = "Enter the server and database name first\.";/);
  assert.match(coordinatorJs, /project_settings_source_data\.js\?v=20261012combined1/);
  assert.match(coordinatorJs, /createSourceDataFeature\(\{[\s\S]*fetchImpl: fetch\.bind\(window\),/);
  assert.match(html, /project_settings_combined_source\.css\?v=/);
  assert.match(html, /project_settings\.js\?v=20261012combined1/);
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
