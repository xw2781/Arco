import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MAX_FOCUSED_SERIES,
  addFocusedSeries,
  buildChartMatrix,
  buildChartSeries,
  defaultFocusIds,
  removeFocusedSeries,
} from "../ui/dataset_viewer/tabs/dataset_chart_series.js";
import { columnShade, labelStep, yearText } from "../ui/dataset_viewer/tabs/dataset_chart_minimap.js";
import { niceTicks } from "../ui/dataset_viewer/tabs/dataset_chart_renderer.js";

const frontendRoot = new URL("../", import.meta.url);

const model = {
  origin_labels: ["2021", "2022", "2023"],
  dev_labels: ["12", "24", "36"],
  values: [[100, 150, 180], [110, 160, "x"], [120, 0, 0]],
  mask: [[true, true, true], [true, true, true], [true, false, false]],
};

test("chart matrix keeps only masked numeric cells", () => {
  const matrix = buildChartMatrix(model);
  assert.deepEqual(matrix.values, [[100, 150, 180], [110, 160, null], [120, null, null]]);
  assert.deepEqual(matrix.colLabels, ["12", "24", "36"]);
  assert.equal(buildChartMatrix({ values: [[1]] }), null);
});

test("incremental and age-to-age views derive from the stored values", () => {
  assert.deepEqual(buildChartMatrix(model, "incremental").values, [[100, 50, 30], [110, 50, null], [120, null, null]]);
  const ratio = buildChartMatrix(model, "ratio");
  assert.deepEqual(ratio.colLabels, ["12-24", "24-36"]);
  assert.deepEqual(ratio.colKeys, ["12", "24"]);
  assert.deepEqual(ratio.values, [[1.5, 1.2], [160 / 110, null], [null, null]]);
});

test("origin curves and the age trend read the same matrix both ways", () => {
  const matrix = buildChartMatrix(model);
  const byRow = buildChartSeries(matrix, "byRow");
  assert.deepEqual(byRow.xLabels, ["12", "24", "36"]);
  assert.deepEqual(byRow.list.map((s) => s.id), ["o:2021", "o:2022", "o:2023"]);
  const byCol = buildChartSeries(matrix, "byCol", (label) => `AY ${label}`);
  assert.deepEqual(byCol.xLabels, ["AY 2021", "AY 2022", "AY 2023"]);
  assert.deepEqual(byCol.list.map((s) => s.label), ["Age 12", "Age 24", "Age 36"]);
  assert.deepEqual(byCol.list[1].values, [150, 160, null]);
  assert.deepEqual(buildChartSeries(buildChartMatrix(model, "ratio"), "byCol").list.map((s) => [s.id, s.label]), [
    ["d:12", "12-24"],
    ["d:24", "24-36"],
  ]);
});

test("default focus picks the newest plottable origins or the earliest ages", () => {
  const list = buildChartSeries(buildChartMatrix(model), "byRow").list;
  assert.deepEqual(defaultFocusIds(list, "byRow"), ["o:2021", "o:2022"]);
  const ages = buildChartSeries(buildChartMatrix(model), "byCol").list;
  assert.deepEqual(defaultFocusIds(ages, "byCol"), ["d:12", "d:24"]);
});

test("a focused series keeps its colour slot when another is removed", () => {
  const ids = [];
  const slots = {};
  for (const id of ["a", "b", "c", "d"]) assert.equal(addFocusedSeries(ids, slots, id), true);
  assert.equal(ids.length, MAX_FOCUSED_SERIES);
  assert.equal(addFocusedSeries(ids, slots, "e"), false);
  removeFocusedSeries(ids, slots, "b");
  assert.deepEqual(slots, { a: 0, c: 2, d: 3 });
  addFocusedSeries(ids, slots, "e");
  assert.equal(slots.e, 1);
});

test("the minimap labels whole years when monthly cells are too small", () => {
  assert.equal(labelStep(18, 1, 12), 1);
  assert.equal(labelStep(2, 12, 12), 12);
  assert.equal(labelStep(0.5, 12, 12), 24);
  assert.equal(labelStep(4, 1, 12), 4);
  assert.equal(yearText("Jan 2019"), "2019");
  assert.equal(yearText("Q1"), "Q1");
});

test("minimap shading is relative within each age", () => {
  const shade = columnShade([[10, 100], [20, null], [30, 300]]);
  assert.equal(shade(0, 0), 0);
  assert.equal(shade(2, 0), 1);
  assert.equal(shade(1, 1), null);
  assert.equal(shade(2, 1), 1);
});

test("axis ticks land on round steps that cover the range", () => {
  const { lo, hi, ticks } = niceTicks(0, 7.3e6, 6);
  assert.equal(lo, 0);
  assert.ok(hi >= 7.3e6);
  assert.deepEqual(ticks.slice(0, 3), [0, 2e6, 4e6]);
});

test("the Chart tab mounts the focus-and-context layout through the versioned chain", async () => {
  const [html, main, view, tab] = await Promise.all([
    "ui/dataset_viewer/dataset_viewer.html",
    "ui/dataset_viewer/dataset_viewer_main.js",
    "ui/dataset_viewer/dataset_viewer_view.js",
    "ui/dataset_viewer/tabs/dataset_chart_tab.js",
  ].map((path) => readFile(new URL(path, frontendRoot), "utf8")));
  assert.match(html, /dataset_viewer\.css\?v=20261020c/u);
  assert.doesNotMatch(html, /chart_legend\.css/u);
  assert.match(main, /dataset_chart_tab\.js\?v=20261020c/u);
  assert.match(view, /id="dsChartRoot"[\s\S]*id="dsChartFocusBar"[\s\S]*id="dsChartMinimap"[\s\S]*id="dsChartPlot"[\s\S]*id="dsChartZoom"/u);
  // The chart's length buttons write through the Data tab's own length lists.
  assert.match(view, /id="dsChartOriginLen"[^>]*data-len-select="originLenSelect"/u);
  assert.match(view, /id="dsChartDevLen"[^>]*data-len-select="devLenSelect"/u);
  assert.match(view, /id="dsChartMinimapPanel"[\s\S]*id="dsChartFilterList"[\s\S]*id="dsChartMinimapResizer"/u);
  assert.match(tab, /setPointerCapture/u);
  assert.match(tab, /dataset_chart_renderer\.js\?v=20261020b/u);
  assert.match(tab, /dataset_chart_minimap\.js\?v=20261020a/u);
  assert.match(tab, /dataset_chart_series\.js\?v=20261020b/u);
  assert.doesNotMatch(view, /dsChartAverage/u);
});
