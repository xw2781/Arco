// The Source Data import call sequences: every path an import can take, run
// against a stub fetch and a stub refresh job. The single-table sequences (CSV
// the server reads, CSV only this PC reads, SQL Server) are pinned exactly as
// they ran before a combined source existed; the combined sequence sits beside
// them.
import assert from "node:assert/strict";
import test from "node:test";

const {
  createSourceImport,
  describeSourceUploadProgress,
  localImportRequest,
} = await import(new URL("../ui/project_settings/project_settings_source_import.js", import.meta.url));

const PROJECT = "NJ_Annual_Prod_202608_Fake";
const PROFILE = { server: "IBNRSQL01", database: "ResQ_Monthly", table: "dbo.Loss", authentication: "windows" };
const SCOPE = { datasetTypes: ["Gross Loss--Paid"], reservingClassTypes: [{ name: "HOL", level: 5 }] };

/**
 * One import against stubs. `log` records every call in order: fetches as
 * ["fetch", url, body], refresh-job calls as ["plan" | "job", ...], and the
 * page callbacks by name.
 */
function harness({ plan = { server_can_import: false }, job = { ok: true, result: { row_count: 12 } }, importAnswer = null } = {}) {
  const log = [];
  const answers = {
    "/source_table/profile": { source_type: "csv", csv_path: "saved" },
    "/source_table/refresh": importAnswer || { last_import: { row_count: 10 } },
    "/source_table/import": importAnswer || { last_import: { row_count: 11 } },
    "/source_table/combined/import": importAnswer || { last_import: { row_count: 13, source_type: "combined" } },
  };
  const fetchImpl = async (url, init = {}) => {
    if (String(url).startsWith("/source_table/upload_progress")) {
      log.push(["progress", url]);
      return { ok: true, json: async () => ({ active: true, bytes_sent: 1048576, rows_sent: 5 }) };
    }
    log.push(["fetch", url, init.body === undefined ? undefined : JSON.parse(init.body)]);
    return { ok: true, json: async () => answers[url] };
  };
  const sourceImport = createSourceImport({
    fetchImpl,
    getProjectName: () => PROJECT,
    sourceRefresh: {
      isRunning: () => false,
      loadPlan: async (name) => {
        log.push(["plan", name]);
        return plan;
      },
      runJob: async (name, options) => {
        log.push(["job", name, options]);
        return job;
      },
    },
    applySourceState: (state) => log.push(["apply", state]),
    setSourceStatus: (text, tone) => log.push(["sourceStatus", text, tone]),
    setStatus: (text) => log.push(["status", text]),
    showProgress: (title) => log.push(["showProgress", title]),
    hideProgress: () => log.push(["hideProgress"]),
    reloadViews: async (name, options) => log.push(["reload", name, options]),
    progressPollMs: 60_000,
  });
  return { log, sourceImport };
}

const jobCall = (importSource) => ["job", PROJECT, {
  importSource,
  refreshDependents: true,
  datasetTypes: SCOPE.datasetTypes,
  reservingClassTypes: SCOPE.reservingClassTypes,
}];

test("a CSV the server can read saves its path, then the job imports it on the server", async () => {
  const { log, sourceImport } = harness({ plan: { server_can_import: true } });
  assert.equal(await sourceImport.saveImportSettings("csv", PROFILE, " \\\\share\\raw\\claims.csv "), true);
  const result = await sourceImport.importSourceData("csv", SCOPE);
  assert.deepEqual(result, { ok: true, rowCount: 12 });
  assert.deepEqual(log, [
    ["fetch", "/source_table/profile", {
      project_name: PROJECT,
      source_type: "csv",
      mssql: PROFILE,
      csv_path: "\\\\share\\raw\\claims.csv",
    }],
    ["apply", { source_type: "csv", csv_path: "saved" }],
    ["plan", PROJECT],
    jobCall(true),
    ["reload", PROJECT, { forceRefresh: false }],
  ]);
});

test("a CSV only this PC can read is uploaded here, then the job runs with the import off", async () => {
  const { log, sourceImport } = harness({ plan: { server_can_import: false } });
  await sourceImport.saveImportSettings("csv", PROFILE, "C:\\local\\claims.csv");
  const result = await sourceImport.importSourceData("csv", SCOPE);
  assert.deepEqual(result, { ok: true, rowCount: 12 });
  assert.deepEqual(log, [
    ["fetch", "/source_table/profile", {
      project_name: PROJECT,
      source_type: "csv",
      mssql: PROFILE,
      csv_path: "C:\\local\\claims.csv",
    }],
    ["apply", { source_type: "csv", csv_path: "saved" }],
    ["plan", PROJECT],
    ["showProgress", "Uploading CSV file..."],
    ["fetch", "/source_table/refresh", { project_name: PROJECT }],
    ["apply", { last_import: { row_count: 10 } }],
    ["hideProgress"],
    jobCall(false),
    ["reload", PROJECT, { forceRefresh: false }],
  ]);
});

test("a SQL Server table is always uploaded here, whatever the plan says", async () => {
  const { log, sourceImport } = harness({ plan: { server_can_import: true } });
  await sourceImport.saveImportSettings("mssql", PROFILE, "ignored.csv");
  const result = await sourceImport.importSourceData("mssql", SCOPE);
  assert.deepEqual(result, { ok: true, rowCount: 12 });
  assert.deepEqual(log, [
    // A SQL Server save carries no CSV path.
    ["fetch", "/source_table/profile", { project_name: PROJECT, source_type: "mssql", mssql: PROFILE }],
    ["apply", { source_type: "csv", csv_path: "saved" }],
    ["plan", PROJECT],
    ["showProgress", "Uploading table from SQL Server..."],
    ["fetch", "/source_table/import", { project_name: PROJECT }],
    ["apply", { last_import: { row_count: 11 } }],
    ["hideProgress"],
    jobCall(false),
    ["reload", PROJECT, { forceRefresh: false }],
  ]);
});

test("a combined source is joined and uploaded here, then the job runs with the import off", async () => {
  // The combined save goes through the combined module before this runs, and
  // the server plan never offers to import it; even a plan that did is ignored.
  const { log, sourceImport } = harness({ plan: { server_can_import: true } });
  const result = await sourceImport.importSourceData("combined", SCOPE);
  assert.deepEqual(result, { ok: true, rowCount: 12 });
  assert.deepEqual(log, [
    ["plan", PROJECT],
    ["showProgress", "Combining and uploading tables..."],
    ["fetch", "/source_table/combined/import", { project_name: PROJECT }],
    ["apply", { last_import: { row_count: 13, source_type: "combined" } }],
    ["hideProgress"],
    jobCall(false),
    ["reload", PROJECT, { forceRefresh: false }],
  ]);
});

test("each source type reaches its own upload route", () => {
  assert.deepEqual(localImportRequest("csv"), { url: "/source_table/refresh", title: "Uploading CSV file..." });
  assert.deepEqual(localImportRequest("mssql"), { url: "/source_table/import", title: "Uploading table from SQL Server..." });
  assert.deepEqual(localImportRequest("combined"), {
    url: "/source_table/combined/import",
    title: "Combining and uploading tables...",
  });
  assert.equal(describeSourceUploadProgress({ phase: "committing" }), "Writing the table on Arco Server...");
  assert.equal(describeSourceUploadProgress({ bytes_sent: 1048576, total_bytes: 2097152, rows_sent: 1200 }), "1.0 of 2.0 MB, 1,200 rows");
});

test("with no Engine a server-read CSV imports nothing, and an uploaded source reloads in full", async () => {
  const server = harness({ plan: { server_can_import: true }, job: { unavailable: true } });
  const refused = await server.sourceImport.importSourceData("csv", SCOPE);
  assert.equal(refused.ok, false);
  assert.match(refused.error, /Arco Engine is unavailable, so the table could not be imported/);
  assert.ok(!server.log.some((entry) => entry[0] === "fetch"), "the server-read CSV was copied by this PC");

  for (const sourceType of ["csv", "mssql", "combined"]) {
    const local = harness({ plan: { server_can_import: false }, job: { unavailable: true } });
    const result = await local.sourceImport.importSourceData(sourceType, SCOPE);
    assert.equal(result.ok, true, sourceType);
    assert.deepEqual(local.log.at(-1), ["reload", PROJECT, { forceRefresh: true }], sourceType);
  }
});

test("an import stops before any upload when the plan is missing or a refresh is running", async () => {
  const noPlan = harness({ plan: null });
  assert.deepEqual(await noPlan.sourceImport.importSourceData("combined", SCOPE), {
    ok: false,
    error: "Could not reach Arco Server to plan the import. Try again.",
  });
  assert.deepEqual(noPlan.log, [["plan", PROJECT]]);
  const busy = harness({ plan: { busy: true } });
  const result = await busy.sourceImport.importSourceData("mssql", SCOPE);
  assert.equal(result.ok, false);
  assert.deepEqual(busy.log, [["plan", PROJECT]]);
});

test("a failed upload is reported and the job never runs", async () => {
  const log = [];
  const sourceImport = createSourceImport({
    fetchImpl: async (url) => {
      log.push(url);
      return { ok: false, status: 400, json: async () => ({}) };
    },
    readResponseErrorDetail: async () => "Save the combined source before importing it.",
    getProjectName: () => PROJECT,
    sourceRefresh: {
      isRunning: () => false,
      loadPlan: async () => ({ server_can_import: false }),
      runJob: async () => {
        throw new Error("the job ran after a failed upload");
      },
    },
    progressPollMs: 60_000,
  });
  assert.deepEqual(await sourceImport.importSourceData("combined", SCOPE), {
    ok: false,
    error: "Save the combined source before importing it.",
  });
  assert.deepEqual(log, ["/source_table/combined/import"]);
});

test("the upload shows its progress while it runs", async () => {
  const titles = [];
  let release;
  const sourceImport = createSourceImport({
    fetchImpl: async (url) => {
      if (String(url).startsWith("/source_table/upload_progress")) {
        assert.equal(url, `/source_table/upload_progress?project_name=${PROJECT}`);
        setTimeout(() => release(), 0);
        return { ok: true, json: async () => ({ active: true, bytes_sent: 1048576, rows_sent: 5 }) };
      }
      await new Promise((resolve) => { release = resolve; });
      await new Promise((resolve) => setTimeout(resolve, 5));
      return { ok: true, json: async () => ({ last_import: { row_count: 5 } }) };
    },
    getProjectName: () => PROJECT,
    sourceRefresh: {
      isRunning: () => false,
      loadPlan: async () => ({ server_can_import: false }),
      runJob: async () => ({ ok: true, result: { row_count: 5 } }),
    },
    showProgress: (title) => titles.push(title),
    progressPollMs: 1,
  });
  assert.deepEqual(await sourceImport.importSourceData("combined", {}), { ok: true, rowCount: 5 });
  assert.equal(titles[0], "Combining and uploading tables...");
  assert.ok(titles.includes("Combining and uploading tables... 1.0 MB, 5 rows"), titles.join(" | "));
});
