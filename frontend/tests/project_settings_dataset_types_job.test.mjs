import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  createAutoSaveScheduler,
} from "../ui/project_settings/project_settings_auto_save.js";
import { describeProgressBar } from "../ui/shared/components/progress_popup/progress_popup.js";
import {
  createDatasetTypesChangeRequestId,
  datasetTypesChangeStatusUrl,
  datasetTypesRowsSignature,
  describeDatasetTypesChangeResult,
  waitForDatasetTypesChangeJob,
} from "../ui/project_settings/project_settings_dataset_types_job.js";

const CRYPTO = {
  randomUUID: () => "0f2a1b3c-4d5e-6f70-8192-a3b4c5d6e7f8",
};

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

function processingStatus(overrides = {}) {
  return {
    ok: true,
    status: "processing",
    updated_at: "2026-08-20T03:00:00Z",
    progress: { stage: "graphs", completed: 1, total: 2, label: "Rebuilding graphs" },
    ...overrides,
  };
}

// ---------------------------------------------------------------- identity ---

test("a submission id is generated in a shape the server accepts", () => {
  const id = createDatasetTypesChangeRequestId(CRYPTO);
  assert.match(id, /^psdtc_[a-z0-9-]+$/u);
  assert.ok(id.length <= 128);
});

test("the status URL carries the project and the job", () => {
  const url = datasetTypesChangeStatusUrl("NJ Prod 2026 Q2", "psdtc_1");
  assert.equal(
    url,
    "/dataset_types/change_job/status?project_name=NJ+Prod+2026+Q2&job_id=psdtc_1",
  );
});

test("the rows signature distinguishes a changed table", () => {
  const rows = [["Paid", "Triangle", "A Loss", false, ""]];
  assert.equal(datasetTypesRowsSignature(rows), datasetTypesRowsSignature([...rows]));
  assert.notEqual(
    datasetTypesRowsSignature(rows),
    datasetTypesRowsSignature([...rows, ["New", "Vector", "A Loss", false, ""]]),
  );
});

// -------------------------------------------------------------- job polling ---

test("a finished job resolves with its terminal status and reports progress", async () => {
  const responses = [
    jsonResponse({ ok: true, status: "queued", updated_at: "t0", progress: { stage: "queued", completed: 0, total: 0, label: "Queued for Arco Engine" } }),
    jsonResponse(processingStatus()),
    jsonResponse({
      ok: true,
      status: "success",
      updated_at: "t2",
      progress: { stage: "complete", completed: 2, total: 2, label: "Dataset type change complete" },
      result: {
        rows_written: 3,
        datasets_total: 9,
        datasets_updated: 5,
        classes_total: 2,
        datasets_recalculated: 2,
        failures: [],
      },
    }),
  ];
  const labels = [];
  const terminal = await waitForDatasetTypesChangeJob({
    fetchImpl: async () => responses.shift(),
    projectName: "Demo",
    jobId: "psdtc_1",
    onProgress: (progress) => labels.push(progress.label),
    waitForPoll: async () => {},
  });
  assert.equal(terminal.status, "success");
  assert.deepEqual(labels, [
    "Queued for Arco Engine",
    "Rebuilding graphs",
    "Dataset type change complete",
  ]);
  assert.equal(
    describeDatasetTypesChangeResult(terminal),
    "3 dataset types saved. 5 datasets updated across 2 reserving classes. 2 calculated datasets recalculated.",
  );
});

test("a job the Engine ended in error throws a decided failure", async () => {
  await assert.rejects(
    waitForDatasetTypesChangeJob({
      fetchImpl: async () => jsonResponse({
        ok: true,
        status: "error",
        updated_at: "t1",
        progress: { stage: "graphs", completed: 1, total: 2, label: "Rebuilding graphs" },
        message: "The dataset type table was saved, but part of the rebuild failed: HPPREF",
      }),
      projectName: "Demo",
      jobId: "psdtc_1",
      waitForPoll: async () => {},
    }),
    (error) => {
      assert.equal(error.code, "DATASET_TYPES_CHANGE_JOB_ERROR");
      assert.match(error.message, /was saved, but part of the rebuild failed/);
      return true;
    },
  );
});

test("a status that stops moving is treated as a dead worker", async () => {
  let now = 0;
  await assert.rejects(
    waitForDatasetTypesChangeJob({
      fetchImpl: async () => jsonResponse(processingStatus()),
      projectName: "Demo",
      jobId: "psdtc_1",
      waitForPoll: async () => { now += 1000; },
      now: () => now,
      staleStatusMs: 5000,
    }),
    (error) => {
      assert.equal(error.code, "DATASET_TYPES_CHANGE_STATUS_STALE");
      return true;
    },
  );
});

test("a queued job is allowed to sit longer than a processing one", async () => {
  let now = 0;
  const queued = () => jsonResponse({
    ok: true,
    status: "queued",
    updated_at: "t0",
    progress: { stage: "queued", completed: 0, total: 0, label: "Queued for Arco Engine" },
  });
  let polls = 0;
  await assert.rejects(
    waitForDatasetTypesChangeJob({
      fetchImpl: async () => { polls += 1; return queued(); },
      projectName: "Demo",
      jobId: "psdtc_1",
      waitForPoll: async () => { now += 1000; },
      now: () => now,
      staleStatusMs: 2000,
      queuedStaleStatusMs: 20000,
    }),
    (error) => error.code === "DATASET_TYPES_CHANGE_STATUS_STALE",
  );
  // It waited out the queued allowance, not the shorter processing one.
  assert.ok(polls > 10, `polled ${polls} times`);
});

test("transient status failures are retried before giving up", async () => {
  const responses = [
    jsonResponse({ detail: "locked" }, 423),
    jsonResponse({ detail: "boom" }, 500),
    jsonResponse({
      ok: true,
      status: "success",
      updated_at: "t1",
      progress: { stage: "complete", completed: 1, total: 1, label: "Done" },
      result: { rows_written: 1, datasets_updated: 0, datasets_recalculated: 0, failures: [] },
    }),
  ];
  const terminal = await waitForDatasetTypesChangeJob({
    fetchImpl: async () => responses.shift(),
    projectName: "Demo",
    jobId: "psdtc_1",
    waitForPoll: async () => {},
  });
  assert.equal(terminal.status, "success");
});

test("an unknown status keeps polling and never counts as a failure or a stall", async () => {
  let now = 0;
  const unknown = () => jsonResponse({ ok: true, project_name: "Demo", job_id: "psdtc_1", found: false, unknown: true });
  const responses = [
    jsonResponse(processingStatus()),
    ...Array.from({ length: 20 }, unknown),
    jsonResponse(processingStatus()),
    jsonResponse({
      ok: true,
      status: "success",
      updated_at: "t9",
      progress: { stage: "complete", completed: 2, total: 2, label: "Done" },
      result: { rows_written: 1, datasets_updated: 0, datasets_recalculated: 0, failures: [] },
    }),
  ];
  const labels = [];
  const terminal = await waitForDatasetTypesChangeJob({
    fetchImpl: async () => responses.shift(),
    projectName: "Demo",
    jobId: "psdtc_1",
    onProgress: (progress) => labels.push(progress.label),
    waitForPoll: async () => { now += 1000; },
    now: () => now,
    staleStatusMs: 5000,
    maxStatusRetries: 2,
  });
  assert.equal(terminal.status, "success");
  assert.ok(labels.includes("Waiting for the server to answer..."));
});

test("a job identity the workspace never received is reported as missing", async () => {
  await assert.rejects(
    waitForDatasetTypesChangeJob({
      fetchImpl: async () => jsonResponse({ detail: "Dataset type change job was not found." }, 404),
      projectName: "Demo",
      jobId: "psdtc_1",
      waitForPoll: async () => {},
    }),
    (error) => error.code === "DATASET_TYPES_CHANGE_STATUS_NOT_FOUND",
  );
});

// ------------------------------------------------------- auto-save watchdog ---

/** A controllable clock so a hung save can be observed without waiting. */
function fakeTimers() {
  let now = 0;
  let nextId = 1;
  const scheduled = new Map();
  return {
    setTimeoutImpl(fn, delay) {
      const id = nextId++;
      scheduled.set(id, { fn, at: now + Number(delay || 0) });
      return id;
    },
    clearTimeoutImpl(id) {
      scheduled.delete(id);
    },
    async advance(ms) {
      now += ms;
      const due = [...scheduled.entries()]
        .filter(([, item]) => item.at <= now)
        .sort((a, b) => a[1].at - b[1].at);
      for (const [id, item] of due) {
        scheduled.delete(id);
        item.fn();
        await Promise.resolve();
      }
      await Promise.resolve();
    },
  };
}

test("a save that never answers cannot disable auto-save for the project", async () => {
  const timers = fakeTimers();
  const started = [];
  const stalled = [];
  let releaseFirst;
  const schedule = createAutoSaveScheduler(
    (projectName) => {
      started.push(projectName);
      // The first save hangs the way a request on a dead share does.
      if (started.length === 1) return new Promise((resolve) => { releaseFirst = resolve; });
      return Promise.resolve(true);
    },
    {
      onStalled: (projectName) => stalled.push(projectName),
      debounceMs: 700,
      watchdogMs: 5000,
      setTimeoutImpl: timers.setTimeoutImpl,
      clearTimeoutImpl: timers.clearTimeoutImpl,
    },
  );

  schedule("Demo");
  await timers.advance(700);
  assert.deepEqual(started, ["Demo"]);

  // An edit made while the first save hangs is queued, not sent.
  schedule("Demo");
  await timers.advance(700);
  assert.deepEqual(started, ["Demo"]);

  // The watchdog gives the slot back and says so, and the queued edit is saved.
  await timers.advance(5000);
  assert.deepEqual(stalled, ["Demo"]);
  await timers.advance(700);
  assert.deepEqual(started, ["Demo", "Demo"]);

  // The original request finally answering must not disturb anything.
  releaseFirst?.(true);
  await timers.advance(0);
  assert.deepEqual(started, ["Demo", "Demo"]);
});

test("a rejected save still releases the slot and keeps the queued edit", async () => {
  const timers = fakeTimers();
  const started = [];
  const schedule = createAutoSaveScheduler(
    (projectName) => {
      started.push(projectName);
      return Promise.reject(new Error("network down"));
    },
    {
      debounceMs: 700,
      watchdogMs: 5000,
      setTimeoutImpl: timers.setTimeoutImpl,
      clearTimeoutImpl: timers.clearTimeoutImpl,
    },
  );

  schedule("Demo");
  await timers.advance(700);
  schedule("Demo");
  await timers.advance(700);
  assert.equal(started.length, 2);
});

test("saves for different projects do not share one slot", async () => {
  const timers = fakeTimers();
  const started = [];
  const schedule = createAutoSaveScheduler(
    (projectName) => {
      started.push(projectName);
      return new Promise(() => {});
    },
    {
      debounceMs: 700,
      watchdogMs: 5000,
      setTimeoutImpl: timers.setTimeoutImpl,
      clearTimeoutImpl: timers.clearTimeoutImpl,
    },
  );
  schedule("Demo");
  schedule("Other");
  await timers.advance(700);
  assert.deepEqual(started.sort(), ["Demo", "Other"]);
});

// ------------------------------------------------------------ result wording ---

test("the outcome is reported in datasets, not in dependency graphs", () => {
  assert.equal(
    describeDatasetTypesChangeResult({
      result: { rows_written: 248, datasets_updated: 258, classes_total: 19, classes_affected: 19 },
    }),
    "248 dataset types saved. 258 datasets updated across 19 reserving classes.",
  );
  // A change that reached only some classes says how many were left alone,
  // and a rename that moved instances with it is counted on its own.
  assert.equal(
    describeDatasetTypesChangeResult({
      result: {
        rows_written: 248,
        datasets_updated: 3,
        datasets_renamed: 2,
        classes_total: 19,
        classes_affected: 2,
      },
    }),
    "248 dataset types saved. 3 datasets updated across 2 of 19 reserving classes. 2 datasets renamed with its type.",
  );
  // Singulars read naturally, including the irregular one.
  assert.equal(
    describeDatasetTypesChangeResult({
      result: { rows_written: 1, datasets_updated: 1, classes_total: 1, classes_affected: 1 },
    }),
    "1 dataset type saved. 1 dataset updated across 1 reserving class.",
  );
  // A change with no downstream effect says so rather than showing a bare zero.
  assert.equal(
    describeDatasetTypesChangeResult({
      result: { rows_written: 248, datasets_updated: 0, classes_total: 19 },
    }),
    "248 dataset types saved. No datasets needed updating.",
  );
});

// ------------------------------------------------------------- progress bar ---

test("a job with a known denominator gets a bar, one without keeps the spinner", () => {
  assert.equal(describeProgressBar(null), null);
  assert.equal(describeProgressBar({ completed: 0, total: 0 }), null);
  // A job that has not counted its work yet must not read as finished.
  assert.equal(describeProgressBar({ completed: 7, total: 0 }), null);

  assert.deepEqual(describeProgressBar({ completed: 129, total: 258, unit: "datasets" }), {
    completed: 129,
    total: 258,
    percent: 50,
    text: "129 of 258 datasets (50%)",
  });
  // A count that overshoots its total is clamped rather than shown past 100%.
  assert.equal(describeProgressBar({ completed: 500, total: 258 }).percent, 100);
  assert.equal(describeProgressBar({ completed: 1, total: 4 }).text, "1 of 4 (25%)");
});

test("a measured progress card is sized once instead of following its message", async () => {
  // Each step names a reserving class, and those paths run from ~20 to ~80
  // characters. Without these rules the window resizes on every poll.
  const css = await readFile(
    new URL("../ui/shared/components/progress_popup/progress_popup.css", import.meta.url),
    "utf8",
  );
  const card = css.match(/\.arcrho-load-popup-card\.is-measured\s*\{([^}]*)\}/u);
  assert.ok(card, "the measured card has no rule of its own");
  assert.match(card[1], /width:\s*min\(/u);
  assert.match(card[1], /max-width:\s*none/u);

  const message = css.match(
    /\.arcrho-load-popup-card\.is-measured \.arcrho-load-popup-msg\s*\{([^}]*)\}/u,
  );
  assert.ok(message, "the measured message has no rule of its own");
  // Two lines are reserved and the third is clipped, so a long path cannot
  // make the card taller.
  assert.match(message[1], /-webkit-line-clamp:\s*2/u);
  assert.match(message[1], /min-height:/u);

  const count = css.match(
    /\.arcrho-load-popup-card\.is-measured \.arcrho-load-popup-progress-count\s*\{([^}]*)\}/u,
  );
  assert.ok(count, "the measured count has no rule of its own");
  assert.match(count[1], /min-height:/u);
});
