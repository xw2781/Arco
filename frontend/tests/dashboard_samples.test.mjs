import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { buildWidgetResult, tableOfSource } from "../ui/dashboard/dashboard_data.js";
import { WIDGET_TYPES, normalizeDashboard, normalizeWidget, resolveLayout } from "../ui/dashboard/dashboard_model.js";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..");
const SHIPPED = join(FRONTEND, "app_server", "default_dashboards");
const read = (...parts) => readFileSync(join(FRONTEND, ...parts), "utf8");
const sampleFiles = readdirSync(SHIPPED).filter((name) => name.endsWith(".arcdash"));

test("four sample dashboards ship, each with its data and every chart drawable", () => {
  assert.equal(sampleFiles.length, 4);
  for (const file of sampleFiles) {
    const raw = JSON.parse(readFileSync(join(SHIPPED, file), "utf8"));
    const dashboard = normalizeDashboard(raw);
    assert.equal(`${dashboard.name}.arcdash`, file, "a sample's file is named for it");
    assert.ok(dashboard.description, `${file} says what it answers`);
    // The document is already in the shape the page saves, so opening it changes nothing.
    assert.deepEqual(dashboard.pages, raw.pages, `${file} pages are normalized`);
    const tables = new Map(dashboard.sources.map((source) => [source.id, tableOfSource(source)]));
    for (const source of dashboard.sources) {
      assert.ok(source.extract?.rows.length > 0, `${file} ships the table of ${source.name}`);
    }
    for (const page of dashboard.pages) {
      assert.deepEqual(resolveLayout(page.widgets).map((widget) => widget.layout), page.widgets.map((widget) => widget.layout), `${file} / ${page.name} has no overlapping widgets`);
      for (const filter of page.filters) {
        assert.ok([...tables.values()].some((table) => table.index.has(filter.field)), `${file} filters on a real field: ${filter.field}`);
      }
      for (const widget of page.widgets) {
        if (widget.type === "text") continue;
        const result = buildWidgetResult(tables.get(widget.source), widget, page.filters.filter((filter) => filter.values.length));
        assert.equal(result.error, undefined, `${file} / ${page.name} / ${widget.title}: ${result.error}`);
        assert.notEqual(result.empty, true, `${file} / ${page.name} / ${widget.title} has data`);
      }
    }
  }
});

test("one sample reads two projects and charts the movement between them", () => {
  const movement = normalizeDashboard(JSON.parse(readFileSync(join(SHIPPED, "Quarter Over Quarter Movement.arcdash"), "utf8")));
  const [source] = movement.sources;
  assert.equal(source.projects.length, 2);
  const table = tableOfSource(source);
  const labels = source.projects.map((project) => project.label);
  assert.deepEqual(table.columns[0], { name: "Project", type: "text", role: "dimension", order: labels });
  const compared = movement.pages.flatMap((page) => page.widgets).filter((widget) => widget.compare);
  assert.ok(compared.length >= 4);
  for (const widget of compared) {
    assert.deepEqual([widget.compare.field, widget.compare.base, widget.compare.target], ["Project", ...labels]);
  }
});

test("every built-in library item is a widget the page can place", () => {
  const library = JSON.parse(read("app_server", "default_dashboards", "library.json"));
  const ids = new Set();
  for (const asset of library.assets) {
    assert.ok(asset.name && asset.category && asset.description, `${asset.id} is described`);
    assert.ok(!ids.has(asset.id), `${asset.id} is unique`);
    ids.add(asset.id);
    assert.ok(WIDGET_TYPES[asset.widget.type], `${asset.id} names a widget type`);
    assert.equal(normalizeWidget(asset.widget).type, asset.widget.type);
    assert.ok(read("ui", "dashboard", "icons", "dashboard_icons.css").includes(`data-db-icon="${asset.widget.type}"`) || asset.widget.type === "bar", `${asset.widget.type} has an icon`);
  }
  for (const type of Object.keys(WIDGET_TYPES)) {
    assert.ok(library.assets.some((asset) => asset.widget.type === type), `the library offers a ${type}`);
    assert.match(read("ui", "dashboard", "icons", `${type}.svg`), /viewBox="0 0 16 16"[^>]*stroke="currentColor"/);
  }
});

test("the shell opens a dashboard as a file-keyed tab and takes its state from the page", () => {
  const tabActions = read("ui", "shell", "tab_actions.js");
  assert.match(tabActions, /export function openDashboardTab\(options = \{\}\)/);
  assert.match(tabActions, /t\.type === "dashboard" && String\(t\.dashboardPath \|\| ""\)\.trim\(\)\.toLowerCase\(\) === fileKey/);
  assert.match(tabActions, /normalized\.tabType === "dashboard"\) return openDashboardTab\(\{ path: normalized\.path/);
  assert.match(read("ui", "shell", "iframe_host.js"), /tab\.type === "dashboard"[\s\S]*?\/ui\/dashboard\/dashboard\.html\?/);
  const messages = read("ui", "shell", "shell_messages.js");
  assert.match(messages, /msg\.type === "arcrho:dashboard-state"[\s\S]*?tab\.dashboardPath = [\s\S]*?tab\.isDirty = dirty/);
  assert.match(messages, /msg\.type === "arcrho:assistant-ask"[\s\S]*?shell\.askAiAssistant/);
  assert.match(read("ui", "shell", "shell_hotkeys.js"), /isActiveDashboardTab\?\.\(\)\) shell\.sendDashboardCommand\?\.\("arcrho:dashboard-save"\)/);
  assert.match(read("ui", "shell", "shell_state.js"), /dashboardPath: t\.type === "dashboard"/);
  assert.match(read("ui", "shell", "home_view.js"), /id="cardDashboards">\$\{homeCardIcon\("dashboard"\)\}/);
  assert.match(read("ui", "shell", "home-card-icons", "home_card_icons.css"), /data-home-icon="dashboard"/);
  assert.match(read("ui", "shell", "tab-type-icons", "tab_type_icons.css"), /data-tab-type="dashboard"/);

  const page = read("ui", "dashboard", "dashboard_main.js");
  for (const type of ["arcrho:dashboard-state", "arcrho:dashboard-save", "arcrho:assistant-context-request", "arcrho:assistant-apply-json-edit", "arcrho:assistant-revert-json-edit"]) {
    assert.ok(page.includes(type), `the page handles ${type}`);
  }
});

test("ArcBot may edit a dashboard file and a Claude reply can carry the edit", () => {
  const host = read("electron", "arcbot_host.js");
  assert.match(host, /\[".json", ".ipynb", ".arcnb", ".arcdash"\]\.includes\(extension\)/);
  assert.match(host, /function extractClaudeDashboardEdit\(rawText\)/);
  assert.match(host, /isArcBotDashboardContext\(activeContext\) && isArcBotEditableTarget\(targetPath\)/);
});
