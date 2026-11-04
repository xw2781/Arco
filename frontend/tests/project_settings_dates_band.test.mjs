import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The main page's dates band only shows the project dates; the whole band is
// the one way into the Project Dates panel (plan project_dates_panel.md step 7).

const uiUrl = (name) => new URL(`../ui/project_settings/${name}`, import.meta.url);
const read = async (name) => (await readFile(uiUrl(name), "utf8")).replaceAll("\r\n", "\n");

const html = await read("project_settings.html");
const coordinatorSource = await read("project_settings.js");
const generalSettingsSource = await read("project_settings_general_settings.js");
const sourceDataSource = await read("project_settings_source_data.js");
const summaryCss = await read("project_settings_summary.css");
const datesCss = await read("project_settings_project_dates.css");
const lockSource = await read("project_settings_project_lock.js");

/** Load a page module with its site-absolute imports pointed at the files on disk. */
async function importPageModule(name) {
  const source = (await read(name)).replace(
    /"\/ui\/project_settings\/([a-z_]+\.js)\?v=[^"]+"/g,
    (_match, file) => JSON.stringify(uiUrl(file).href),
  );
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const { createProjectDatesFeature } = await importPageModule("project_settings_project_dates.js");
const { createGeneralSettingsFeature } = await importPageModule("project_settings_general_settings.js");

function fakeElement(id) {
  const listeners = new Map();
  const attributes = new Map();
  const classes = new Set();
  return {
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    hidden: false,
    disabled: false,
    tabIndex: 0,
    style: {},
    focused: 0,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, force) => {
        const on = force === undefined ? !classes.has(name) : !!force;
        if (on) classes.add(name);
        else classes.delete(name);
        return on;
      },
    },
    setAttribute: (key, value) => attributes.set(key, String(value)),
    getAttribute: (key) => (attributes.has(key) ? attributes.get(key) : null),
    addEventListener: (type, handler) => {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(handler);
    },
    dispatch(type, event = {}) {
      const full = { defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...event };
      for (const handler of listeners.get(type) || []) handler(full);
      return full;
    },
    contains: () => false,
    focus() { this.focused += 1; },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }),
  };
}

function fakeDocument() {
  const elements = new Map();
  return {
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, fakeElement(id));
      return elements.get(id);
    },
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
  };
}

function setup({ project = "Fake", locked = false } = {}) {
  const documentRef = fakeDocument();
  const state = { project: project ? { name: project } : null, locked, loads: [] };
  const feature = createProjectDatesFeature({
    fetchImpl: async () => { throw new Error("no network in this test"); },
    setStatus() {},
    publishShellProgress() {},
    readResponseErrorDetail: async () => "",
    getSelectedProject: () => state.project,
    isProjectLocked: () => state.locked,
    loadDates: async (name) => {
      state.loads.push(name);
      return { originStartDate: "201701", originEndDate: "202612", developmentEndDate: "202612" };
    },
    reloadDates: async () => {},
    documentRef,
  });
  const band = documentRef.getElementById("summaryPeriodsBand");
  return { feature, band, state, documentRef };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a click anywhere on the band opens the panel on the selected project's dates", async () => {
  const { feature, band, state, documentRef } = setup();
  assert.equal(band.getAttribute("aria-disabled"), "false");
  assert.equal(band.tabIndex, 0);
  band.dispatch("click");
  await settle();
  assert.equal(feature.isOpen(), true);
  assert.deepEqual(state.loads, ["Fake"]);
  assert.equal(documentRef.getElementById("pdOriginStartInput").value, "Jan 2017");
  assert.equal(documentRef.getElementById("pdDevelopmentEndInput").value, "Dec 2026");
});

test("Enter and Space open the panel; other keys do not", async () => {
  for (const key of ["Enter", " "]) {
    const { feature, band } = setup();
    const event = band.dispatch("keydown", { key });
    await settle();
    assert.equal(event.defaultPrevented, true, `${JSON.stringify(key)} scrolled the page`);
    assert.equal(feature.isOpen(), true, `${JSON.stringify(key)} did not open the panel`);
  }
  const { feature, band } = setup();
  band.dispatch("keydown", { key: "a" });
  band.dispatch("keydown", { key: "Enter", repeat: true });
  await settle();
  assert.equal(feature.isOpen(), false);
});

test("the band is inert while the project is locked or none is selected", async () => {
  for (const options of [{ locked: true }, { project: "" }]) {
    const { feature, band, state } = setup(options);
    assert.equal(band.getAttribute("aria-disabled"), "true");
    assert.equal(band.tabIndex, -1);
    band.dispatch("click");
    band.dispatch("keydown", { key: "Enter" });
    await settle();
    assert.equal(feature.isOpen(), false);
    assert.deepEqual(state.loads, []);
  }
});

test("a lock read or a project switch re-syncs the band", async () => {
  const { feature, band, state } = setup();
  state.locked = true;
  feature.syncEntryPoint();
  assert.equal(band.getAttribute("aria-disabled"), "true");
  state.locked = false;
  state.project = null;
  feature.syncEntryPoint();
  assert.equal(band.getAttribute("aria-disabled"), "true");
  state.project = { name: "Fake" };
  // A click re-checks on its own, so a stale state never blocks an open.
  band.dispatch("click");
  await settle();
  assert.equal(feature.isOpen(), true);
  assert.equal(band.getAttribute("aria-disabled"), "false");
});

test("the band shows the saved dates as text and offers no way to edit them", () => {
  const displays = {
    originStartDate: fakeElement("summaryOriginStartValue"),
    originEndDate: fakeElement("summaryOriginEndValue"),
    developmentEndDate: fakeElement("summaryDevelopmentEndValue"),
  };
  let shown = 0;
  const feature = createGeneralSettingsFeature({
    setStatus() {},
    normalizeProjectKey: (name) => String(name || "").toLowerCase(),
    readResponseErrorDetail: async () => "",
    getSelectedProject: () => ({ name: "Fake" }),
    onDatesShown: () => { shown += 1; },
    fetchImpl: async () => { throw new Error("no network in this test"); },
    displays,
  });
  feature.showDates({ originStart: "201701", originEnd: "202612", developmentEnd: "2026-12" });
  assert.equal(displays.originStartDate.textContent, "Jan 2017");
  assert.equal(displays.originEndDate.textContent, "Dec 2026");
  assert.equal(displays.developmentEndDate.textContent, "Dec 2026");
  assert.equal(shown, 1);
  assert.equal("bindEditor" in feature, false, "the per-input save path is back");

  const band = html.match(/<div class="sd-band" id="summaryPeriodsBand"[^>]*>[\s\S]*?\n {16}<\/div>/)?.[0] || "";
  assert.ok(band, "the dates band is missing");
  assert.match(band, /role="button" tabindex="0" aria-haspopup="dialog" aria-controls="projectDatesPanel"/);
  assert.doesNotMatch(band, /<input|<button|data-month-picker-for/, "the band still holds an editable control");
  for (const id of ["summaryOriginStartValue", "summaryOriginEndValue", "summaryDevelopmentEndValue"]) {
    assert.match(band, new RegExp(`class="sd-date" id="${id}"`));
  }
  // The panel still owns the page's one month picker.
  assert.match(html, /id="summaryMonthPicker"/);
  assert.match(html, /data-month-picker-for="pdOriginStartInput"/);

  // The retired editor and the step-6 temporary entry point are gone.
  assert.doesNotMatch(generalSettingsSource, /bindEditor|onwheel|commitPending|shiftBoundaryYmCanonical/);
  assert.doesNotMatch(coordinatorSource, /bindEditor|TEMPORARY|summaryOriginLabel/);
  assert.doesNotMatch(datesCss, /TEMPORARY/);
  assert.match(sourceDataSource, /monthIndex\(dom\.originStart\?\.textContent\)/);
  assert.match(coordinatorSource, /isProjectLocked: \(\) => projectLockFeature\.isSelectedProjectLocked\(\)/);
  assert.match(coordinatorSource, /onChange: \(\) => projectDatesFeature\.syncEntryPoint\(\)/);
  assert.match(lockSource, /onChange\?\.\(\);/);
});

test("the band reads as one button: pointer, hover, focus ring, inert look", () => {
  assert.match(summaryCss, /\.sd-band \{[\s\S]*?cursor: pointer;/);
  assert.match(summaryCss, /--sd-band-hover-bg: var\(--ar-color-surface-hover/);
  assert.match(summaryCss, /\.sd-band:hover \{[\s\S]*?background: var\(--sd-band-hover-bg\);/);
  assert.match(summaryCss, /\.sd-band:focus-visible \{[\s\S]*?box-shadow:/);
  assert.match(summaryCss, /\.sd-band\[aria-disabled="true"\] \{ cursor: default; \}/);
  assert.doesNotMatch(summaryCss, /\.table-summary\.is-loading \.sd-month/);
});

// ---- step 10: the run on the band, the finished states, the review rows ----

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const PREVIOUS = { origin_start_date: "201701", origin_end_date: "202612", development_end_date: "202612" };

/** A panel wired to a fake server; `result` is what the finished job reports. */
function runSetup({ result, gate = null } = {}) {
  const documentRef = fakeDocument();
  const calls = { posts: [], progress: [], shell: [], statusPolls: 0 };
  const state = { project: { name: "Fake", folder: "E:\\Fake" } };
  const fetchImpl = async (url, init = {}) => {
    if (url.startsWith("/general_settings/dates/preview")) {
      return jsonResponse({ unchanged: false, previous_dates: PREVIOUS, dates: { ...PREVIOUS, development_end_date: "202703" } });
    }
    if (url === "/general_settings/dates/job") {
      calls.posts.push(JSON.parse(init.body));
      return jsonResponse({ ok: true, job_id: `job${calls.posts.length}` });
    }
    calls.statusPolls += 1;
    if (gate && calls.statusPolls === 1) {
      await gate.promise;
      return jsonResponse({ status: "processing", progress: { stage: "classes", completed: 12, total: 33, label: "MA BI Total" } });
    }
    return jsonResponse({ status: "success", result, progress: { stage: "complete", completed: 33, total: 33 } });
  };
  const feature = createProjectDatesFeature({
    fetchImpl,
    setStatus() {},
    publishShellProgress: (message) => calls.progress.push(message),
    readResponseErrorDetail: async () => "",
    getSelectedProject: () => state.project,
    loadDates: async () => ({ originStartDate: "201701", originEndDate: "202612", developmentEndDate: "202612" }),
    reloadDates: async () => {},
    postShellMessage: (message) => calls.shell.push(message),
    documentRef,
    requestIdFactory: () => `psdates_${calls.posts.length + 1}`,
    pollOptions: { waitForPoll: () => Promise.resolve() },
  });
  const get = (id) => documentRef.getElementById(id);
  return { feature, calls, state, get, band: get("summaryPeriodsBand") };
}

async function applyAndConfirm({ get }) {
  get("pdDevelopmentEndInput").value = "Mar 2027";
  get("pdApplyBtn").dispatch("click");
  await settle();
  await settle();
  get("pdConfirmOk").dispatch("click");
  for (let index = 0; index < 8; index += 1) await settle();
}

const CLEAN = { classes_total: 2, classes_refreshed: 2, datasets_regenerated: 4, methods_updated: 3, review: [], failures: [] };

test("the confirmation shows a before-and-after table with only the changed date bold", async () => {
  const setupState = runSetup({ result: CLEAN });
  setupState.band.dispatch("click");
  await settle();
  setupState.get("pdDevelopmentEndInput").value = "Mar 2027";
  setupState.get("pdApplyBtn").dispatch("click");
  await settle();
  await settle();
  const table = setupState.get("pdConfirmDates").innerHTML;
  assert.match(table, /<th scope="col">Before<\/th><th scope="col">After<\/th>/);
  assert.match(table, /<tr><th scope="row">Origin Start<\/th><td>Jan 2017<\/td><td>Jan 2017<\/td><\/tr>/);
  assert.match(table, /<tr class="is-changed"><th scope="row">Development End<\/th><td>Dec 2026<\/td><td>Mar 2027<\/td><\/tr>/);
  assert.equal((table.match(/is-changed/g) || []).length, 1);
  setupState.get("pdConfirmCancel").dispatch("click");
});

test("while the change runs the band shows its progress and reopens the progress window", async () => {
  let release;
  const gate = { promise: new Promise((resolve) => { release = resolve; }) };
  const setupState = runSetup({ result: CLEAN, gate });
  const { band, get, calls, feature } = setupState;
  band.dispatch("click");
  await settle();
  get("pdDevelopmentEndInput").value = "Mar 2027";
  get("pdApplyBtn").dispatch("click");
  await settle();
  await settle();
  get("pdConfirmOk").dispatch("click");
  for (let index = 0; index < 4; index += 1) await settle();
  assert.equal(feature.isRunning(), true);
  assert.equal(band.classList.contains("is-running"), true);
  assert.equal(get("summaryDatesProgress").hidden, false);
  assert.equal(get("summaryDatesProgress").textContent, "Changing dates…");
  assert.equal(get("pdCancelBtn").textContent, "Close", "a running change cannot be cancelled");

  feature.close();
  const before = calls.progress.length;
  band.dispatch("click");
  await settle();
  assert.equal(feature.isOpen(), false, "a click during the run opened the panel");
  assert.deepEqual(calls.progress.slice(before).map((message) => message.action), ["open"]);
  assert.equal(calls.progress.at(-1).title, "Change Project Dates");

  // Another project selected: its band shows its own dates.
  setupState.state.project = { name: "Other" };
  feature.syncEntryPoint();
  assert.equal(band.classList.contains("is-running"), false);
  setupState.state.project = { name: "Fake", folder: "E:\\Fake" };
  feature.syncEntryPoint();

  release();
  for (let index = 0; index < 6; index += 1) await settle();
  assert.equal(feature.isRunning(), false);
  assert.equal(band.classList.contains("is-running"), false);
  assert.equal(get("summaryDatesProgress").hidden, true);

  // The panel was closed during the run: reopening it shows the result, once.
  band.dispatch("click");
  await settle();
  assert.equal(feature.isOpen(), true);
  assert.match(get("pdMessage").textContent, /^Project dates changed\./);
  assert.equal(get("pdCancelBtn").textContent, "Close");
  feature.close();
  band.dispatch("click");
  await settle();
  assert.equal(get("pdMessage").textContent, "");
  assert.equal(get("pdCancelBtn").textContent, "Cancel");
});

test("after a clean change Close leads and Apply waits for an edit", async () => {
  const setupState = runSetup({ result: CLEAN });
  const { band, get, calls } = setupState;
  band.dispatch("click");
  await settle();
  await applyAndConfirm(setupState);
  assert.equal(calls.posts.length, 1);
  assert.equal(get("pdMessage").textContent, "Project dates changed. Refreshed 4 datasets and 3 methods in 2 of 2 reserving classes.");
  assert.equal(get("pdCancelBtn").textContent, "Close");
  assert.equal(get("pdCancelBtn").classList.contains("primary"), true);
  assert.equal(get("pdApplyBtn").disabled, true);
  assert.equal(get("pdApplyBtn").classList.contains("primary"), false);

  get("pdOriginEndInput").dispatch("input");
  assert.equal(get("pdApplyBtn").disabled, false);
  assert.equal(get("pdApplyBtn").textContent, "Apply");
  assert.equal(get("pdApplyBtn").classList.contains("primary"), true);
  assert.equal(get("pdCancelBtn").textContent, "Cancel");
});

test("a part failure reads as one line and Run Again resends the same dates", async () => {
  const result = {
    classes_total: 2,
    classes_refreshed: 2,
    datasets_failed: 1,
    failures: ["NJ\\HOL: Paid Loss could not be built"],
    dependent_problems: [],
    review: [],
    rerun_needed: true,
  };
  const setupState = runSetup({ result });
  const { band, get, calls } = setupState;
  band.dispatch("click");
  await settle();
  await applyAndConfirm(setupState);
  assert.equal(get("pdMessage").textContent, "Saved. 1 dataset could not refresh.");
  assert.equal(get("pdMessage").classList.contains("is-warning"), true);
  assert.equal(get("pdMessage").classList.contains("is-error"), false);
  assert.match(get("pdReview").innerHTML, /<details class="pd-review-group is-problem"><summary><span class="pd-review-heading">Could Not Refresh<\/span><span class="pd-review-count">1<\/span><\/summary>/);
  assert.doesNotMatch(get("pdReview").innerHTML, /<details[^>]* open/, "groups start collapsed");
  assert.equal(get("pdApplyBtn").textContent, "Run Again");
  assert.equal(get("pdApplyBtn").disabled, false);
  assert.equal(get("pdApplyBtn").classList.contains("primary"), true);

  get("pdApplyBtn").dispatch("click");
  for (let index = 0; index < 8; index += 1) await settle();
  assert.equal(calls.posts.length, 2, "Run Again did not resend");
  const { request_id: _first, ...firstDates } = calls.posts[0];
  const { request_id: _second, ...secondDates } = calls.posts[1];
  assert.deepEqual(secondDates, firstDates);
  assert.equal(secondDates.development_end_date, "202703");
});

test("a review row shows its full reason on hover and a click opens it in the project", async () => {
  const result = {
    classes_total: 1,
    classes_refreshed: 1,
    failures: [],
    review: [{ reserving_class: "NJ\\HOL", name: "Current Qtr", kind: "method", method_type: "Result Selection", reasons: ["periods moved to the new dates"] }],
  };
  const setupState = runSetup({ result });
  const { band, get, calls } = setupState;
  band.dispatch("click");
  await settle();
  await applyAndConfirm(setupState);
  const review = get("pdReview").innerHTML;
  assert.equal(get("projectDatesPanel").classList.contains("has-review"), true, "the panel widens for the review list");
  assert.match(review, /<span class="pd-review-heading">Reshaped Methods<\/span><span class="pd-review-count">1<\/span>/);
  assert.match(review, /<button class="pd-review-row" type="button" role="listitem" data-group="0" data-row="0" title="NJ\\HOL\\Current Qtr — periods moved to the new dates">/);
  const button = { dataset: { group: "0", row: "0" } };
  get("pdReview").dispatch("click", { target: { closest: (selector) => (selector === "button.pd-review-row" ? button : null) } });
  assert.deepEqual(calls.shell, [{
    type: "arcrho:open-project-instance",
    project: {
      name: "Fake",
      folder: "E:\\Fake",
      projectInstanceState: {
        selectedPath: "NJ\\HOL",
        windows: [{ kind: "result_selection", name: "Current Qtr", active: true, methodType: "Result Selection" }],
      },
    },
  }]);
});

test("the band's hover border is the focus blue and the run hides the dates", () => {
  assert.match(summaryCss, /\.sd-band:hover \{\s*border-color: var\(--ar-color-border-focus/);
  assert.match(summaryCss, /\.sd-band\.is-running \.sd-band-group \{ display: none; \}/);
  assert.match(html, /<span class="sd-band-progress" id="summaryDatesProgress" role="status" hidden><\/span>/);
});
