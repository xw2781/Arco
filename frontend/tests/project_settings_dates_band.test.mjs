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
