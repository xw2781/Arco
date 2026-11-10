import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const moduleSource = await readFile(
  new URL("../ui/project_settings/project_settings_source_refresh_job.js", import.meta.url),
  "utf8",
);
const {
  clearPendingSourceRefresh,
  createSourceRefreshRequestId,
  describeSourceRefreshResult,
  loadPendingSourceRefresh,
  normalizeSourceRefreshScope,
  pendingSourceRefreshStorageKey,
  savePendingSourceRefresh,
  sourceRefreshScopeRequestFields,
  sourceRefreshStatusUrl,
  waitForSourceRefreshJob,
} = await import(
  `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

function response(body, status = 200) {
  const raw = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => raw,
  };
}

function statusPayload(status, overrides = {}) {
  return {
    ok: true,
    job_id: "psrefresh_1",
    found: true,
    busy: status === "queued" || status === "processing",
    contract_version: 1,
    status,
    updated_at: "2026-08-18T00:00:00+00:00",
    request_id: "psrefresh_1",
    progress: { stage: "classes", completed: 2, total: 5, label: "Refreshing HPPREF" },
    ...overrides,
  };
}

function memoryStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    size: () => map.size,
  };
}

const immediatePoll = () => Promise.resolve();
const WORKSPACE_ROOT = "E:/Arco Server";
const WORKSPACE_SCOPE = `ws_${WORKSPACE_ROOT}`;

test("the status URL names both the project and the job", () => {
  assert.equal(
    sourceRefreshStatusUrl("Demo Project", "psrefresh_1"),
    "/source_table/refresh_job/status?project_name=Demo+Project&job_id=psrefresh_1",
  );
});

test("request ids are generated in the accepted request-id shape", () => {
  const id = createSourceRefreshRequestId({
    randomUUID: () => "0f1e2d3c-4b5a-6978-8765-43210fedcba9",
  });
  assert.match(id, /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u);
  assert.ok(id.startsWith("psrefresh_"));
});

test("a job is followed to success and reports each progress tick", async () => {
  const payloads = [statusPayload("queued"), statusPayload("processing"), statusPayload("success")];
  const seen = [];
  const result = await waitForSourceRefreshJob({
    fetchImpl: async () => response(payloads.shift()),
    projectName: "Demo Project",
    jobId: "psrefresh_1",
    onProgress: (progress) => seen.push(progress.label),
    waitForPoll: immediatePoll,
  });
  assert.equal(result.status, "success");
  assert.deepEqual(seen, ["Refreshing HPPREF", "Refreshing HPPREF", "Refreshing HPPREF"]);
});

test("a failed job raises a coded error carrying the server message", async () => {
  await assert.rejects(
    waitForSourceRefreshJob({
      fetchImpl: async () =>
        response(statusPayload("error", { message: "2 dataset(s) failed." })),
      projectName: "Demo Project",
      jobId: "psrefresh_1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "SOURCE_REFRESH_JOB_ERROR" && /2 dataset/.test(error.message),
  );
});

test("a missing status is distinguished from a transient failure", async () => {
  await assert.rejects(
    waitForSourceRefreshJob({
      fetchImpl: async () => response({ detail: "Source refresh job was not found." }, 404),
      projectName: "Demo Project",
      jobId: "psrefresh_1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "SOURCE_REFRESH_STATUS_NOT_FOUND",
  );
});

test("a locked or failing status endpoint is retried, then reported as unavailable", async () => {
  let calls = 0;
  await assert.rejects(
    waitForSourceRefreshJob({
      fetchImpl: async () => {
        calls += 1;
        return response({ detail: "locked" }, 423);
      },
      projectName: "Demo Project",
      jobId: "psrefresh_1",
      waitForPoll: immediatePoll,
      maxStatusRetries: 2,
    }),
    (error) => error.code === "SOURCE_REFRESH_STATUS_UNAVAILABLE",
  );
  assert.equal(calls, 3);
});

test("an unknown status keeps polling and never counts as a failure or a stall", async () => {
  let clock = 0;
  const unknown = () => response({ ok: true, project_name: "Demo Project", job_id: "psrefresh_1", found: false, unknown: true });
  const replies = [
    response(statusPayload("processing")),
    ...Array.from({ length: 20 }, unknown),
    response(statusPayload("processing")),
    response(statusPayload("success", { progress: { stage: "complete", completed: 5, total: 5, label: "Done" } })),
  ];
  const labels = [];
  const terminal = await waitForSourceRefreshJob({
    fetchImpl: async () => replies.shift(),
    projectName: "Demo Project",
    jobId: "psrefresh_1",
    onProgress: (progress) => labels.push(progress.label),
    waitForPoll: () => {
      clock += 10_000;
      return Promise.resolve();
    },
    now: () => clock,
    maxStatusRetries: 2,
  });
  assert.equal(terminal.status, "success");
  assert.ok(labels.includes("Refresh is still running; waiting for the server to answer..."));
});

test("a status that stops moving is treated as a stalled worker", async () => {
  let clock = 0;
  await assert.rejects(
    waitForSourceRefreshJob({
      fetchImpl: async () => response(statusPayload("processing")),
      projectName: "Demo Project",
      jobId: "psrefresh_1",
      waitForPoll: () => {
        clock += 10_000;
        return Promise.resolve();
      },
      now: () => clock,
    }),
    (error) => error.code === "SOURCE_REFRESH_STATUS_STALE",
  );
});

test("a queued job is given a longer silence than a processing one", async () => {
  let clock = 0;
  const queuedCalls = [];
  await assert.rejects(
    waitForSourceRefreshJob({
      fetchImpl: async () => {
        queuedCalls.push(clock);
        return response(statusPayload("queued"));
      },
      projectName: "Demo Project",
      jobId: "psrefresh_1",
      waitForPoll: () => {
        clock += 10_000;
        return Promise.resolve();
      },
      now: () => clock,
    }),
    (error) => error.code === "SOURCE_REFRESH_STATUS_STALE",
  );
  // 45 s would have ended a processing job; a queued one waits for 180 s.
  assert.ok(queuedCalls.at(-1) >= 180_000, `queued job gave up at ${queuedCalls.at(-1)}ms`);
});

test("a recovery record round-trips and is scoped to project and workspace", () => {
  const storage = memoryStorage();
  const record = {
    version: 1,
    projectName: "Demo Project",
    workspaceScope: "ws_1",
    requestId: "psrefresh_1",
    importSource: true,
    refreshDependents: true,
    submittedAt: 1,
  };
  assert.ok(savePendingSourceRefresh(storage, record));
  assert.equal(loadPendingSourceRefresh(storage, "Demo Project", "ws_1").requestId, "psrefresh_1");
  // Another workspace must never replay a job submitted against this one.
  assert.equal(loadPendingSourceRefresh(storage, "Demo Project", "ws_2"), null);
  assert.equal(loadPendingSourceRefresh(storage, "Other Project", "ws_1"), null);

  assert.equal(clearPendingSourceRefresh(storage, "Demo Project", "ws_1", "other-id"), false);
  assert.equal(clearPendingSourceRefresh(storage, "Demo Project", "ws_1", "psrefresh_1"), true);
  assert.equal(loadPendingSourceRefresh(storage, "Demo Project", "ws_1"), null);
});

test("an unusable storage key never produces a recovery record", () => {
  assert.equal(pendingSourceRefreshStorageKey("Demo Project", ""), "");
  assert.equal(pendingSourceRefreshStorageKey("", "ws_1"), "");
  assert.equal(savePendingSourceRefresh(memoryStorage(), { version: 1 }), null);
});

test("a refresh scope is normalized, de-duplicated, and sent only when it narrows the job", () => {
  const scope = normalizeSourceRefreshScope({
    datasetTypes: [" Gross Loss--Paid ", "gross loss--paid", "", null, "ALAE--Paid"],
    reservingClassTypes: [
      { name: "HPPREF", level: 1 },
      { name: "hppref", level: "1" },
      { name: "HOL", level: 5 },
      { name: "", level: 2 },
      { name: "NJ", level: 0 },
    ],
  });
  assert.deepEqual(scope, {
    datasetTypes: ["Gross Loss--Paid", "ALAE--Paid"],
    reservingClassTypes: [{ name: "HPPREF", level: 1 }, { name: "HOL", level: 5 }],
  });
  // The server reads an absent field as "everything", so nothing is sent for it.
  assert.deepEqual(sourceRefreshScopeRequestFields({}), {});
  assert.deepEqual(sourceRefreshScopeRequestFields({ datasetTypes: ["ALAE--Paid"] }), {
    dataset_types: ["ALAE--Paid"],
  });
  assert.deepEqual(sourceRefreshScopeRequestFields(scope).reserving_class_types, [
    { Name: "HPPREF", Level: 1 },
    { Name: "HOL", Level: 5 },
  ]);
});

test("a recovery record keeps the scope so a replayed submission asks for the same work", () => {
  const storage = memoryStorage();
  savePendingSourceRefresh(storage, {
    version: 1,
    projectName: "Demo Project",
    workspaceScope: "ws_1",
    requestId: "psrefresh_1",
    importSource: true,
    refreshDependents: true,
    datasetTypes: ["ALAE--Paid"],
    reservingClassTypes: [{ name: "HOL", level: 5 }],
    submittedAt: 1,
  });
  const loaded = loadPendingSourceRefresh(storage, "Demo Project", "ws_1");
  assert.deepEqual(loaded.datasetTypes, ["ALAE--Paid"]);
  assert.deepEqual(loaded.reservingClassTypes, [{ name: "HOL", level: 5 }]);
  // A record written before the scope existed still loads, as a whole-project job.
  storage.setItem(
    pendingSourceRefreshStorageKey("Demo Project", "ws_1"),
    JSON.stringify({
      version: 1,
      projectName: "Demo Project",
      workspaceScope: "ws_1",
      requestId: "psrefresh_2",
      importSource: true,
      refreshDependents: true,
      submittedAt: 1,
    }),
  );
  const legacy = loadPendingSourceRefresh(storage, "Demo Project", "ws_1");
  assert.deepEqual(legacy.datasetTypes, []);
  assert.deepEqual(legacy.reservingClassTypes, []);
});

test("the result summary names what the job actually did", () => {
  assert.equal(
    describeSourceRefreshResult({
      imported: true,
      row_count: 1234,
      dependents_refreshed: true,
      classes_refreshed: 3,
      datasets_regenerated: 9,
      methods_updated: 4,
      datasets_failed: 0,
    }),
    "Source table refresh: imported 1,234 row(s); refreshed 9 dataset(s) and 4 method(s) across 3 reserving class(es).",
  );
  assert.match(describeSourceRefreshResult({ datasets_failed: 2 }), /2 dataset\(s\) failed/);
  assert.equal(describeSourceRefreshResult(null), "Source table refresh complete.");
});

// ---------------------------------------------------------------------------
// The Project Settings feature that drives the job.
// ---------------------------------------------------------------------------

const featureSource = await readFile(
  new URL("../ui/project_settings/project_settings_source_refresh.js", import.meta.url),
  "utf8",
);
globalThis.__sourceRefreshJobHelpers = await import(
  `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);
const featureTestSource = featureSource
  .replace(
    /import \{[\s\S]*?from "\/ui\/project_settings\/project_settings_source_refresh_job\.js\?v=[^"]+";\s*/u,
    `
const {
  clearPendingSourceRefresh,
  createSourceRefreshRequestId,
  describeSourceRefreshResult,
  loadPendingSourceRefresh,
  normalizeSourceRefreshScope,
  savePendingSourceRefresh,
  sourceRefreshRecoveryStorage,
  sourceRefreshScopeRequestFields,
  waitForSourceRefreshJob,
} = globalThis.__sourceRefreshJobHelpers;
`,
  )
  .replace(
    /import \{ createDuplicateWorkspaceScope \} from "[^"]+";\s*/u,
    "const createDuplicateWorkspaceScope = (config) => (config?.workspace_root ? `ws_${config.workspace_root}` : \"\");\n",
  );
const { createSourceRefreshFeature } = await import(
  `data:text/javascript;base64,${Buffer.from(featureTestSource).toString("base64")}`
);
delete globalThis.__sourceRefreshJobHelpers;

function featureHarness({ submit, statuses = [statusPayload("success")] }) {
  let clock = 0;
  const storage = memoryStorage();
  const progress = [];
  const status = [];
  const queue = [...statuses];
  const feature = createSourceRefreshFeature({
    fetchImpl: async (url, init) => {
      if (String(url).startsWith("/source_table/refresh_job/status")) {
        clock += 1000;
        return response(queue.length > 1 ? queue.shift() : queue[0]);
      }
      if (String(url) === "/source_table/refresh_job") {
        return submit(JSON.parse(init.body));
      }
      throw new Error(`unexpected request: ${url}`);
    },
    setStatus: (text) => status.push(text),
    publishShellProgress: (message) => progress.push(message),
    readResponseErrorDetail: async (res) => String((await res.json())?.detail || res.status),
    storage,
    requestIdFactory: () => "psrefresh_fixed",
    now: () => 1,
    pollOptions: { waitForPoll: immediatePoll, now: () => clock, staleStatusMs: 1, queuedStaleStatusMs: 1 },
  });
  feature.setWorkspaceRoot({ workspace_root: WORKSPACE_ROOT });
  return { feature, storage, progress, status };
}

test("a completed job opens, updates, and closes the shell progress window", async () => {
  const harness = featureHarness({
    submit: async () => response({ ok: true, job_id: "psrefresh_fixed", status: "queued" }),
    statuses: [
      statusPayload("processing"),
      statusPayload("success", { result: { imported: true, row_count: 5 } }),
    ],
  });
  const outcome = await harness.feature.runJob("Demo Project", {
    importSource: true,
    refreshDependents: true,
  });
  assert.equal(outcome.ok, true);
  assert.deepEqual(
    harness.progress.map((message) => message.action),
    ["open", "update", "update", "update", "close"],
  );
  assert.equal(harness.progress.at(0).title, "Refresh Source Table");
  // The record exists only while the job is unresolved.
  assert.equal(loadPendingSourceRefresh(harness.storage, "Demo Project", WORKSPACE_SCOPE), null);
  assert.equal(harness.feature.isRunning(), false);
});

test("a missing Engine is reported as unavailable so the caller can fall back", async () => {
  const harness = featureHarness({
    submit: async () => response({ detail: "The ArcRho Engine service is not available." }, 503),
  });
  const outcome = await harness.feature.runJob("Demo Project", {
    importSource: true,
    refreshDependents: true,
  });
  assert.deepEqual(
    { ok: outcome.ok, unavailable: outcome.unavailable },
    { ok: false, unavailable: true },
  );
  // A job the server never accepted must not leave a record to resume.
  assert.equal(loadPendingSourceRefresh(harness.storage, "Demo Project", WORKSPACE_SCOPE), null);
  assert.equal(harness.progress.at(-1).action, "close");
});

test("a job interrupted before its outcome is resumed under the same request id", async () => {
  const submitted = [];
  const harness = featureHarness({
    submit: async (body) => {
      submitted.push(body);
      return response({ ok: true, job_id: body.request_id, status: "queued", resumed: true });
    },
    statuses: [statusPayload("success", { request_id: "psrefresh_earlier" })],
  });
  // Nothing pending means nothing to re-attach to.
  assert.equal(await harness.feature.resumePending("Demo Project"), null);

  savePendingSourceRefresh(harness.storage, {
    version: 1,
    projectName: "Demo Project",
    workspaceScope: WORKSPACE_SCOPE,
    requestId: "psrefresh_earlier",
    importSource: false,
    refreshDependents: true,
    datasetTypes: ["ALAE--Paid"],
    reservingClassTypes: [{ name: "HOL", level: 5 }],
    submittedAt: 1,
  });
  const outcome = await harness.feature.resumePending("Demo Project");
  assert.equal(outcome.ok, true);
  assert.equal(submitted.at(-1).request_id, "psrefresh_earlier");
  // The resumed submission keeps the original job's plan; re-importing a table
  // the client already copied would do the work twice, and a wider scope would
  // refresh classes the person chose to leave alone.
  assert.equal(submitted.at(-1).import_source, false);
  assert.deepEqual(submitted.at(-1).dataset_types, ["ALAE--Paid"]);
  assert.deepEqual(submitted.at(-1).reserving_class_types, [{ Name: "HOL", Level: 5 }]);
  assert.equal(loadPendingSourceRefresh(harness.storage, "Demo Project", WORKSPACE_SCOPE), null);
});

test("a whole-project refresh posts no scope fields and a narrowed one posts both", async () => {
  const submitted = [];
  const harness = featureHarness({
    submit: async (body) => {
      submitted.push(body);
      return response({ ok: true, job_id: body.request_id, status: "queued" });
    },
  });
  await harness.feature.runJob("Demo Project", { importSource: true, refreshDependents: true });
  assert.equal("dataset_types" in submitted.at(-1), false);
  assert.equal("reserving_class_types" in submitted.at(-1), false);

  await harness.feature.runJob("Demo Project", {
    importSource: true,
    refreshDependents: true,
    datasetTypes: ["Gross Loss--Paid"],
    reservingClassTypes: [{ name: "HPPREF", level: 1 }],
  });
  assert.deepEqual(submitted.at(-1).dataset_types, ["Gross Loss--Paid"]);
  assert.deepEqual(submitted.at(-1).reserving_class_types, [{ Name: "HPPREF", Level: 1 }]);
});

test("a job the server rejected settles its record, a stalled one keeps it", async () => {
  const failed = featureHarness({
    submit: async () => response({ ok: true, job_id: "psrefresh_fixed", status: "queued" }),
    statuses: [statusPayload("error", { message: "1 dataset(s) failed." })],
  });
  const outcome = await failed.feature.runJob("Demo Project", { importSource: true, refreshDependents: true });
  assert.equal(outcome.ok, false);
  assert.match(outcome.error, /1 dataset/);
  assert.equal(loadPendingSourceRefresh(failed.storage, "Demo Project", WORKSPACE_SCOPE), null);

  const stalled = featureHarness({
    submit: async () => response({ ok: true, job_id: "psrefresh_fixed", status: "queued" }),
    statuses: [statusPayload("processing")],
  });
  // A status that never moves ends the wait without settling the job: the
  // server may still be working, so the record must survive for the next visit.
  const stalledOutcome = await stalled.feature.runJob("Demo Project", {
    importSource: true,
    refreshDependents: true,
  });
  assert.equal(stalledOutcome.ok, false);
  assert.ok(loadPendingSourceRefresh(stalled.storage, "Demo Project", WORKSPACE_SCOPE));
});
