import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (name) => readFile(new URL(`../ui/project_settings/${name}`, import.meta.url), "utf8");

const moduleSource = await read("project_settings_project_dates_job.js");
const featureSource = await read("project_settings_project_dates.js");
const coordinatorSource = await read("project_settings.js");
const lockSource = await read("project_settings_project_lock.js");
const html = await read("project_settings.html");
const {
  createProjectDatesRequestId,
  describeProjectDatesPreview,
  describeProjectDatesResult,
  formatProjectDateSet,
  projectDatesJobRequestBody,
  projectDatesJobStatusUrl,
  projectDatesPreviewUrl,
  validateProjectDates,
  waitForProjectDatesJob,
} = await import(`data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`);

function response(body, status = 200) {
  const raw = JSON.stringify(body);
  return { ok: status >= 200 && status < 300, status, json: async () => body, text: async () => raw };
}

function statusPayload(status, overrides = {}) {
  return {
    ok: true,
    job_id: "psdates_1",
    found: true,
    busy: status === "queued" || status === "processing",
    status,
    updated_at: "2026-11-03T00:00:00+00:00",
    progress: { stage: "classes", completed: 1, total: 3, label: "MA BI Total: Paid Loss" },
    ...overrides,
  };
}

const immediatePoll = () => Promise.resolve();
const START_OF_YEAR = { originStartDate: "201801", originEndDate: "202712", developmentEndDate: "202712" };

test("the date rule is start <= end <= development end", () => {
  assert.equal(validateProjectDates(START_OF_YEAR), "");
  assert.equal(validateProjectDates({ ...START_OF_YEAR, originStartDate: "202801" }), "Origin Start is after Origin End.");
  assert.equal(validateProjectDates({ ...START_OF_YEAR, developmentEndDate: "202711" }), "Origin End is after Development End.");
  assert.equal(validateProjectDates({ ...START_OF_YEAR, originEndDate: "" }), "Enter an Origin End month.");
  assert.equal(validateProjectDates({ ...START_OF_YEAR, developmentEndDate: "202713" }), "Enter a Development End month.");
  // Equal months are allowed.
  assert.equal(validateProjectDates({ originStartDate: "202712", originEndDate: "202712", developmentEndDate: "202712" }), "");
});

test("preview, submit and status reach the step-5 routes", () => {
  assert.equal(
    projectDatesPreviewUrl("Demo Project", START_OF_YEAR),
    "/general_settings/dates/preview?project_name=Demo+Project&origin_start_date=201801&origin_end_date=202712&development_end_date=202712",
  );
  assert.equal(
    projectDatesJobStatusUrl("Demo Project", "psdates_1"),
    "/general_settings/dates/job/status?project_name=Demo+Project&job_id=psdates_1",
  );
  assert.deepEqual(projectDatesJobRequestBody("Demo Project", START_OF_YEAR, "psdates_1"), {
    project_name: "Demo Project",
    origin_start_date: "201801",
    origin_end_date: "202712",
    development_end_date: "202712",
    request_id: "psdates_1",
  });
  assert.match(featureSource, /fetchImpl\("\/general_settings\/dates\/job", \{\s*method: "POST"/);
});

test("request ids are generated in the accepted request-id shape", () => {
  assert.equal(
    createProjectDatesRequestId({ randomUUID: () => "ABCDEF01-2345-6789-ABCD-EF0123456789" }),
    "psdates_abcdef01-2345-6789-abcd-ef0123456789",
  );
  assert.match(createProjectDatesRequestId({ getRandomValues: (bytes) => bytes.fill(7) }), /^psdates_(07){16}$/);
  assert.throws(() => createProjectDatesRequestId(null), /unavailable/);
});

test("the confirmation counts every dataset kind and names the dropped origins", () => {
  const { rows, droppedLine } = describeProjectDatesPreview({
    classes: 32,
    engine_datasets: 1288,
    calculated_datasets: 85,
    imported_datasets: 214,
    imported_reshaped: 16,
    methods: 589,
    origin_changes: [
      { origin_length: 12, before: 10, after: 10, dropped: 1, added: 1 },
      { origin_length: 3, before: 40, after: 40, dropped: 4, added: 4 },
      { origin_length: 1, before: 120, after: 120, dropped: 0, added: 0 },
    ],
  });
  assert.deepEqual(rows, [
    { label: "Reserving Classes", value: "32" },
    { label: "Datasets", value: "1,587" },
    { label: "Methods", value: "589" },
    { label: "Hand-Entered Datasets", value: "16" },
  ]);
  assert.equal(droppedLine, "Drops 1 annual and 4 quarterly origin(s), with their data and selections.");
  assert.equal(describeProjectDatesPreview({ origin_changes: [{ origin_length: 12, dropped: 0 }] }).droppedLine, "");
});

test("a date set reads as one line", () => {
  assert.equal(
    formatProjectDateSet({ origin_start_date: "201701", origin_end_date: "202612", development_end_date: "202612" }),
    "Jan 2017 – Dec 2026, Dec 2026",
  );
  assert.equal(formatProjectDateSet({}), "");
});

test("a finished change reports its counts, its problem and the review list", () => {
  const clean = describeProjectDatesResult({
    classes_total: 33,
    classes_refreshed: 33,
    datasets_regenerated: 1288,
    datasets_reshaped: 16,
    methods_reshaped: 14,
    methods_updated: 380,
    review: [
      { reserving_class: "MA BI Total", name: "Paid Benchmark", kind: "dataset", reasons: ["hand-entered or imported"] },
      { reserving_class: "", name: "", reasons: [] },
    ],
    failures: [],
  });
  assert.equal(clean.text, "Project dates changed. Refreshed 1,304 dataset(s) and 394 method(s) in 33 of 33 reserving class(es).");
  assert.equal(clean.failed, false);
  assert.deepEqual(clean.review, [
    { reservingClass: "MA BI Total", name: "Paid Benchmark", kind: "dataset", reasons: ["hand-entered or imported"] },
  ]);
  const short = describeProjectDatesResult({ failures: ["NY: boom"] }, "The dates were saved, but 1 reserving class(es) were not finished.");
  assert.equal(short.text, "The dates were saved, but 1 reserving class(es) were not finished.");
  assert.equal(short.failed, true);
  assert.equal(describeProjectDatesResult({ unchanged: true }).text, "The project already has these dates.");
});

test("the poll follows progress to success and returns the terminal status", async () => {
  const seen = [];
  const statuses = [
    response(statusPayload("queued", { progress: {} })),
    response({ detail: "locked" }, 423),
    response(statusPayload("processing")),
    response(statusPayload("success", { result: { classes_total: 3 }, progress: { stage: "complete", completed: 3, total: 3, label: "Project dates changed" } })),
  ];
  const urls = [];
  const terminal = await waitForProjectDatesJob({
    fetchImpl: async (url) => { urls.push(url); return statuses.shift(); },
    projectName: "Demo",
    jobId: "psdates_1",
    onProgress: (progress) => seen.push(progress),
    waitForPoll: immediatePoll,
  });
  assert.equal(terminal.result.classes_total, 3);
  assert.equal(urls[0], "/general_settings/dates/job/status?project_name=Demo&job_id=psdates_1");
  assert.deepEqual(seen.map((item) => item.stage), ["", "", "classes", "complete"]);
  assert.equal(seen[2].label, "MA BI Total: Paid Loss");
});

test("a refused change rejects with its status code; a silent worker is stale", async () => {
  await assert.rejects(
    waitForProjectDatesJob({
      fetchImpl: async () => response(statusPayload("error", { message: "Other dates are unfinished.", status_code: 409 })),
      projectName: "Demo",
      jobId: "psdates_1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "PROJECT_DATES_JOB_ERROR" && error.statusCode === 409 && /unfinished/.test(error.message),
  );
  let clock = 0;
  await assert.rejects(
    waitForProjectDatesJob({
      fetchImpl: async () => response(statusPayload("processing")),
      projectName: "Demo",
      jobId: "psdates_1",
      waitForPoll: immediatePoll,
      now: () => { clock += 10_000; return clock; },
    }),
    (error) => error.code === "PROJECT_DATES_STATUS_STALE",
  );
  await assert.rejects(
    waitForProjectDatesJob({
      fetchImpl: async () => response({ detail: "missing" }, 404),
      projectName: "Demo",
      jobId: "psdates_1",
      waitForPoll: immediatePoll,
    }),
    (error) => error.code === "PROJECT_DATES_STATUS_NOT_FOUND",
  );
});

test("the panel is wired into Project Settings and guarded by the project lock", () => {
  for (const id of [
    "projectDatesPanel",
    "pdOriginStartInput",
    "pdOriginEndInput",
    "pdDevelopmentEndInput",
    "pdApplyBtn",
    "projectDatesConfirmOverlay",
    "pdConfirmOk",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`), `${id} is missing from the page`);
  }
  // The panel reuses the page's one month picker.
  assert.match(html, /data-month-picker-for="pdDevelopmentEndInput"/);
  assert.match(html, /project_settings_project_dates\.css\?v=20261027map1/);
  assert.match(coordinatorSource, /project_settings_project_dates\.js\?v=20261103dates1/);
  assert.match(coordinatorSource, /const projectDatesFeature = createProjectDatesFeature\(/);
  assert.match(lockSource, /"pdApplyBtn"/);
  // One version URL per shared module.
  assert.match(featureSource, /project_settings_general_settings\.js\?v=20261103dates1/);
  assert.match(coordinatorSource, /project_settings_general_settings\.js\?v=20261103dates1/);
  // Drags follow the pointer-capture rule.
  assert.match(featureSource, /setPointerCapture/);
  assert.doesNotMatch(featureSource, /document\.addEventListener\("mousemove"/);
});
