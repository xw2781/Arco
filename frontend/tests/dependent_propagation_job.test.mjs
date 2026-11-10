import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pollerSource = await readFile(
  new URL("../ui/shared/services/dependent_propagation_job.js", import.meta.url),
  "utf8",
);
const {
  dependentPropagationStatusUrl,
  isEngineUnavailableSaveError,
  trackSavePropagation,
  waitForDependentPropagationJob,
  waitForDependentPropagationOutcome,
} = await import(
  `data:text/javascript;base64,${Buffer.from(pollerSource).toString("base64")}`
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
    job_id: "job-1",
    contract_version: 1,
    status,
    updated_at: "2026-08-06T00:00:00+00:00",
    request_id: "job-1",
    progress: { stage: "dfm", completed: 1, total: 4, label: "Refreshing DFM methods" },
    ...overrides,
  };
}

const immediatePoll = () => Promise.resolve();

test("outcome waiter resolves terminally for success, error, and missing jobs without throwing", async () => {
  const success = await waitForDependentPropagationOutcome("job-1", {
    fetchImpl: async () => response(statusPayload("success")),
    waitForPoll: immediatePoll,
  });
  assert.deepEqual({ ok: success.ok, terminal: success.terminal }, { ok: true, terminal: true });

  const failed = await waitForDependentPropagationOutcome("job-1", {
    fetchImpl: async () => response(statusPayload("error", { message: "walk failed" })),
    waitForPoll: immediatePoll,
  });
  assert.deepEqual({ ok: failed.ok, terminal: failed.terminal }, { ok: false, terminal: true });

  const missing = await waitForDependentPropagationOutcome("   ");
  assert.deepEqual(missing, { ok: false, terminal: false });
});

test("status URL encodes the job id", () => {
  assert.equal(
    dependentPropagationStatusUrl("job one"),
    "/dependent_propagation/refresh_dependents/status/job%20one",
  );
});

test("engine-unavailable detection matches status code and message text", () => {
  assert.ok(isEngineUnavailableSaveError({ status: 503 }));
  assert.ok(
    isEngineUnavailableSaveError(
      new Error("The Arco Engine service is not available. Please try again later or contact the administrator."),
    ),
  );
  assert.ok(!isEngineUnavailableSaveError(new Error("HTTP 500")));
});

test("poller resolves on terminal success and reports tier progress", async () => {
  const responses = [
    response(statusPayload("processing")),
    response(statusPayload("success", {
      progress: { stage: "complete", completed: 1, total: 1, label: "Dependent updates complete" },
    })),
  ];
  const seenLabels = [];
  const result = await waitForDependentPropagationJob({
    fetchImpl: async () => responses.shift(),
    statusUrl: "/status",
    jobId: "job-1",
    onProgress: ({ label }) => seenLabels.push(label),
    waitForPoll: immediatePoll,
  });
  assert.equal(result.status, "success");
  assert.deepEqual(seenLabels, ["Refreshing DFM methods", "Dependent updates complete"]);
});

test("poller raises a coded error for a terminal error status", async () => {
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => response(statusPayload("error", { message: "walk failed" })),
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "PROPAGATION_JOB_ERROR" && /walk failed/u.test(error.message),
  );
});

test("poller retries transient failures then reports unavailability", async () => {
  let calls = 0;
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => {
        calls += 1;
        return response({ detail: "locked" }, 423);
      },
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
      maxStatusRetries: 3,
    }),
    (error) => error.code === "PROPAGATION_STATUS_UNAVAILABLE" && /locked/u.test(error.message),
  );
  assert.equal(calls, 4);
});

test("poller flags a missing status distinctly", async () => {
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => response({ detail: "gone" }, 404),
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "PROPAGATION_STATUS_NOT_FOUND",
  );
});

test("poller detects a stale unchanged status", async () => {
  let clock = 0;
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => response(statusPayload("processing")),
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
      pollIntervalMs: 1,
      staleStatusMs: 5,
      now: () => (clock += 10),
    }),
    (error) => error.code === "PROPAGATION_STATUS_STALE",
  );
});

test("a queued status gets the longer no-heartbeat allowance before going stale", async () => {
  // Processing statuses are heartbeat-republished by the Engine worker, so an
  // unchanged one means a dead worker; a queued status has no heartbeat owner
  // and must be tolerated for the longer queued window.
  let processingPolls = 0;
  let clock = 0;
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => {
        processingPolls += 1;
        return response(statusPayload("processing"));
      },
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
      pollIntervalMs: 1,
      staleStatusMs: 5,
      queuedStaleStatusMs: 50,
      now: () => (clock += 10),
    }),
    (error) => error.code === "PROPAGATION_STATUS_STALE",
  );

  let queuedPolls = 0;
  clock = 0;
  await assert.rejects(
    waitForDependentPropagationJob({
      fetchImpl: async () => {
        queuedPolls += 1;
        return response(statusPayload("queued"));
      },
      statusUrl: "/status",
      jobId: "job-1",
      waitForPoll: immediatePoll,
      pollIntervalMs: 1,
      staleStatusMs: 5,
      queuedStaleStatusMs: 50,
      now: () => (clock += 10),
    }),
    (error) => error.code === "PROPAGATION_STATUS_STALE",
  );
  assert.ok(
    queuedPolls > processingPolls,
    `queued statuses must outlast processing ones (queued ${queuedPolls} <= processing ${processingPolls})`,
  );
});

test("trackSavePropagation frames per-dataset ticks and passes stage banners through", async () => {
  const responses = [
    response(statusPayload("processing", {
      progress: { stage: "marking", completed: 0, total: 0, label: "Marking dependents for review" },
    })),
    response(statusPayload("processing", {
      progress: { stage: "calculated_datasets", completed: 3, total: 8, label: "Paid Loss Ratio" },
    })),
    response(statusPayload("success")),
  ];
  const seen = [];
  await trackSavePropagation(
    { ok: true, job_id: "job-1", status: "queued" },
    {
      fetchImpl: async () => responses.shift(),
      onStatus: (text) => seen.push(text),
      waitForPoll: immediatePoll,
    },
  );
  assert.ok(
    seen.includes("Updating dataset Paid Loss Ratio..."),
    `per-dataset ticks must read "Updating dataset <name>...", got: ${JSON.stringify(seen)}`,
  );
  assert.ok(
    seen.includes("Marking dependents for review"),
    `stage banners must pass through unframed, got: ${JSON.stringify(seen)}`,
  );
});

test("trackSavePropagation resolves an Engine-hosted completed save without polling", async () => {
  let completedWith = "unset";
  const shown = [];
  const result = await trackSavePropagation(
    { ok: true, status: "completed", refreshed_datasets: ["C 61", "C 91"] },
    {
      fetchImpl: async () => { throw new Error("a completed save must not poll"); },
      onComplete: (payload) => { completedWith = payload; },
      showFailure: (message) => shown.push(message),
    },
  );
  assert.deepEqual(result?.refreshed_datasets, ["C 61", "C 91"]);
  assert.deepEqual(completedWith?.refreshed_datasets, ["C 61", "C 91"]);
  assert.deepEqual(shown, []);

  // A completed payload whose walk reported failures resolves null so the
  // window stays open, and shows the server's reason (user decision,
  // 2026-09-21).
  const reason = "Dependent update(s) did not refresh: F 63: Earned Premium could not be generated at 3 months: no quarterly dates.";
  const failed = await trackSavePropagation(
    { ok: false, status: "completed", refreshed_datasets: [], message: reason },
    {
      fetchImpl: async () => { throw new Error("no polling"); },
      onComplete: () => {},
      showFailure: (message) => shown.push(message),
    },
  );
  assert.equal(failed, null);
  assert.deepEqual(shown, [reason]);
});

test("trackSavePropagation ignores a no-op save", async () => {
  let statusCalls = 0;
  const result = await trackSavePropagation(
    { ok: true, status: "unchanged" },
    { onStatus: () => { statusCalls += 1; }, fetchImpl: async () => { throw new Error("no fetch"); } },
  );
  assert.deepEqual(result, { status: "unchanged" });
  assert.equal(statusCalls, 0);
});

test("trackSavePropagation warns when submission failed without a job", async () => {
  const seen = [];
  const result = await trackSavePropagation(
    { ok: false, status: "error", message: "engine offline" },
    { onStatus: (text, options) => seen.push([text, options?.tone]) },
  );
  assert.equal(result, null);
  assert.equal(seen.length, 1);
  assert.match(seen[0][0], /engine offline/u);
  assert.equal(seen[0][1], "warn");
});

test("trackSavePropagation completes a queued job and fires onComplete", async () => {
  const responses = [
    response(statusPayload("processing")),
    response(statusPayload("success")),
  ];
  const seen = [];
  let completed = null;
  const result = await trackSavePropagation(
    { ok: true, job_id: "job-1", status: "queued" },
    {
      fetchImpl: async () => responses.shift(),
      onStatus: (text, options) => seen.push([text, options?.tone]),
      onComplete: (payload) => { completed = payload; },
      waitForPoll: immediatePoll,
    },
  );
  assert.equal(result.status, "success");
  assert.equal(completed.status, "success");
  assert.equal(seen[0][0], "Updating dependents...");
  assert.ok(seen.every(([, tone]) => tone !== "warn"));
});

test("trackSavePropagation shows a failed job's reason and still fires onComplete", async () => {
  // A failed walk shows the server's reason in a message box (user decision,
  // 2026-09-21) rather than a warning status line, and onComplete still fires
  // so the table refresh happens after the walk finalized downstream statuses.
  const seen = [];
  const shown = [];
  let completed = "unset";
  const result = await trackSavePropagation(
    { ok: true, job_id: "job-1", status: "queued" },
    {
      fetchImpl: async () => response(statusPayload("error", { message: "walk failed" })),
      onStatus: (text, options) => seen.push([text, options?.tone]),
      onComplete: (payload) => { completed = payload; },
      showFailure: (message) => shown.push(message),
      waitForPoll: immediatePoll,
    },
  );
  assert.equal(result, null);
  assert.equal(completed, null);
  assert.deepEqual(shown, ["walk failed"]);
  assert.ok(seen.every(([, tone]) => tone !== "warn"));
  assert.match(seen.at(-1)[0], /Dependent updates finished/u);

  // A status that could not be read is not a walk failure and stays quiet.
  const quiet = [];
  await trackSavePropagation(
    { ok: true, job_id: "job-1", status: "queued" },
    {
      fetchImpl: async () => response({ detail: "gone" }, 404),
      showFailure: (message) => quiet.push(message),
      waitForPoll: immediatePoll,
    },
  );
  assert.deepEqual(quiet, []);
});
