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
  describeProjectDatesMove,
  describeProjectDatesPreview,
  describeProjectDatesResult,
  plural,
  projectDatesBandProgress,
  projectDatesJobRequestBody,
  projectDatesJobStatusUrl,
  projectDatesPreviewUrl,
  projectInstanceOpenMessage,
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
  assert.equal(droppedLine, "Drops 1 annual origin and 4 quarterly origins, with their data and selections.");
  assert.equal(describeProjectDatesPreview({ origin_changes: [{ origin_length: 12, dropped: 0 }] }).droppedLine, "");
});

test("counts read in the right number", () => {
  assert.equal(plural(1, "dataset"), "1 dataset");
  assert.equal(plural(0, "dataset"), "0 datasets");
  assert.equal(plural(1288, "dataset"), "1,288 datasets");
  assert.equal(plural(2, "reserving class", "reserving classes"), "2 reserving classes");
});

test("the confirmation compares the dates before and after, row by row", () => {
  assert.deepEqual(
    describeProjectDatesMove(
      { origin_start_date: "201701", origin_end_date: "202612", development_end_date: "202612" },
      { origin_start_date: "201801", origin_end_date: "202712", development_end_date: "202612" },
    ),
    [
      { label: "Origin Start", before: "Jan 2017", after: "Jan 2018", changed: true },
      { label: "Origin End", before: "Dec 2026", after: "Dec 2027", changed: true },
      { label: "Development End", before: "Dec 2026", after: "Dec 2026", changed: false },
    ],
  );
  // Only the changed dates are bold; the table replaces the one wrapped line.
  assert.match(featureSource, /row\.changed \? ' class="is-changed"'/);
  assert.match(html, /<table class="pd-dates-table" id="pdConfirmDates"><\/table>/);
  assert.doesNotMatch(moduleSource, /formatProjectDateSet/);
});

test("a clean change reads as one line and groups its review list by reason", () => {
  const clean = describeProjectDatesResult({
    classes_total: 33,
    classes_refreshed: 33,
    datasets_regenerated: 1288,
    datasets_reshaped: 16,
    methods_reshaped: 14,
    methods_updated: 380,
    review: [
      { reserving_class: "NJ\\MA BI Total", name: "Paid Benchmark", kind: "dataset", method_type: "None", reasons: ["hand-entered or imported"] },
      { reserving_class: "NJ\\MA BI Total", name: "Linked", kind: "dataset", method_type: "None", reasons: ["hand-entered or imported", "has cell links"] },
      { reserving_class: "NJ\\NY BI Total", name: "Other Benchmark", kind: "dataset", reasons: ["hand-entered or imported"] },
      { reserving_class: "NJ\\NY BI Total", name: "Current Qtr", kind: "method", method_type: "Result Selection", reasons: ["periods moved to the new dates"] },
      { reserving_class: "", name: "", reasons: [] },
    ],
    failures: [],
  });
  assert.equal(clean.text, "Project dates changed. Refreshed 1,304 datasets and 394 methods in 33 of 33 reserving classes.");
  assert.equal(clean.failed, false);
  assert.equal(clean.rerun, false);
  assert.equal(clean.review.length, 4);
  assert.deepEqual(clean.groups.map((group) => [group.heading, group.rows.length]), [
    ["Hand-Entered Datasets", 2],
    ["Cell Links", 1],
    ["Reshaped Methods", 1],
  ]);
  const linked = clean.groups[1].rows[0];
  assert.equal(linked.detail, "NJ\\MA BI Total\\Linked — hand-entered or imported; has cell links");
  assert.deepEqual(clean.groups[2].rows[0].open, {
    reservingClass: "NJ\\NY BI Total",
    name: "Current Qtr",
    methodType: "Result Selection",
  });
  assert.equal(
    describeProjectDatesResult({ classes_total: 1, classes_refreshed: 1, datasets_regenerated: 1, methods_updated: 1 }).text,
    "Project dates changed. Refreshed 1 dataset and 1 method in 1 of 1 reserving class.",
  );
  assert.equal(describeProjectDatesResult({ unchanged: true }).text, "The project already has these dates.");
});

test("a part failure is one short line and its detail becomes the first group", () => {
  const datasetOnly = describeProjectDatesResult({
    datasets_failed: 1,
    failures: ["NJ\\Penn+CT: The Engine cannot build Paid Loss at 3 months"],
    dependent_problems: [],
    rerun_needed: true,
  }, "The dates were saved, but 1 dataset(s) could not be refreshed. Run the same change again to finish it.");
  assert.equal(datasetOnly.text, "Saved. 1 dataset could not refresh.");
  assert.equal(datasetOnly.failed, true);
  assert.equal(datasetOnly.rerun, true);
  assert.deepEqual(datasetOnly.groups[0], {
    heading: "Could Not Refresh",
    problem: true,
    rows: [{
      reservingClass: "NJ\\Penn+CT",
      name: "",
      reason: "The Engine cannot build Paid Loss at 3 months",
      detail: "NJ\\Penn+CT: The Engine cannot build Paid Loss at 3 months",
      open: null,
    }],
  });

  // A class's walk failure repeats its first dependent problem; it is listed once.
  const walk = describeProjectDatesResult({
    failures: ["NJ\\HOL: B 12: must match the primary triangle row length (+1 more)"],
    dependent_problems: [
      "NJ\\HOL: B 12: must match the primary triangle row length",
      "NJ\\HOL: B 13: must match the primary triangle row length",
    ],
    rerun_needed: false,
  });
  assert.equal(walk.text, "Saved. 2 items could not refresh.");
  assert.equal(walk.rerun, false, "Run Again is offered only while running again can help");
  assert.deepEqual(walk.groups[0].rows.map((row) => [row.reservingClass, row.name, row.reason]), [
    ["NJ\\HOL", "B 12", "must match the primary triangle row length"],
    ["NJ\\HOL", "B 13", "must match the primary triangle row length"],
  ]);
});

test("a review row opens in the project's Project Instance the way the tree does", () => {
  assert.deepEqual(
    projectInstanceOpenMessage(
      { name: "Fake", folder: "E:\\Fake" },
      { reservingClass: "NJ\\HOL", name: "Current Qtr", methodType: "Result Selection" },
    ),
    {
      type: "arcrho:open-project-instance",
      project: {
        name: "Fake",
        folder: "E:\\Fake",
        projectInstanceState: {
          selectedPath: "NJ\\HOL",
          windows: [{ kind: "result_selection", name: "Current Qtr", active: true, methodType: "Result Selection" }],
        },
      },
    },
  );
  const dataset = projectInstanceOpenMessage({ name: "Fake" }, { reservingClass: "NJ\\HOL", name: "Paid Benchmark", methodType: "None" });
  assert.deepEqual(dataset.project.projectInstanceState.windows, [{ kind: "dataset", name: "Paid Benchmark", active: true }]);
  const bs = projectInstanceOpenMessage({ name: "Fake" }, { reservingClass: "NJ\\HOL", name: "BS SR", methodType: "B&S Settlement Rate Adjustment" });
  assert.deepEqual(bs.project.projectInstanceState.windows, [
    { kind: "dataset", name: "BS SR", active: true, methodType: "B&S Settlement Rate Adjustment" },
  ]);
});

test("the band's progress text follows the class count", () => {
  assert.equal(projectDatesBandProgress({ stage: "saving", completed: 0, total: 0 }), "Changing dates…");
  assert.equal(projectDatesBandProgress({ stage: "classes", completed: 12, total: 33 }), "Changing dates… 12 of 33");
  assert.equal(projectDatesBandProgress(null), "Changing dates…");
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
  assert.match(html, /project_settings_project_dates\.css\?v=20261103panel1/);
  assert.match(coordinatorSource, /project_settings_project_dates\.js\?v=20261103panel1/);
  assert.match(coordinatorSource, /const projectDatesFeature = createProjectDatesFeature\(/);
  assert.match(lockSource, /"pdApplyBtn"/);
  // One version URL per shared module.
  assert.match(featureSource, /project_settings_general_settings\.js\?v=20261103panel1/);
  assert.match(coordinatorSource, /project_settings_general_settings\.js\?v=20261103panel1/);
  // Drags follow the pointer-capture rule.
  assert.match(featureSource, /setPointerCapture/);
  assert.doesNotMatch(featureSource, /document\.addEventListener\("mousemove"/);
});
