import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildResultSelectionChartSeries,
  canHideChartSeries,
  hiddenSeriesIdsAfterContextToggle,
  snapStripShare,
  splitStripWeights,
  useOnlyWeightChanges,
  wheelStepWeight,
} from "../ui/method_pages/result_selection/result_selection_chart.js";

const frontendRoot = new URL("../", import.meta.url);

test("Result Selection chart series follow Method source order and include selected output", () => {
  const series = buildResultSelectionChartSeries({
    sources: [
      { name: "Vector B", values: [20, "21", null] },
      { name: "Triangle A", values: [10, undefined, 12] },
    ],
    sourceIndexes: [1, 0],
    selectedUltimateValues: [15, 21, 18],
    selectedUltimateLabel: "Selected Loss",
    rowCount: 3,
  });

  assert.deepEqual(series.map((entry) => entry.id), ["source:triangle a", "source:vector b", "selected-ultimate"]);
  assert.deepEqual(series.map((entry) => entry.label), ["Triangle A", "Vector B", "Selected Loss"]);
  assert.deepEqual(series[0].values, [10, null, 12]);
  assert.deepEqual(series[1].values, [20, 21, null]);
  assert.deepEqual(series[2].values, [15, 21, 18]);
  assert.equal(series[2].emphasized, true);
});

test("Result Selection chart item context toggle isolates a line and then restores all lines", () => {
  const series = [
    { id: "source:paid" },
    { id: "source:incurred" },
    { id: "selected-ultimate" },
  ];
  const hidden = hiddenSeriesIdsAfterContextToggle(series, "selected-ultimate");

  assert.deepEqual([...hidden], ["source:paid", "source:incurred"]);

  const restored = hiddenSeriesIdsAfterContextToggle(series, "selected-ultimate", hidden);
  assert.deepEqual([...restored], []);
});

test("Result Selection chart keeps the final visible item checked", () => {
  const series = [
    { id: "source:paid" },
    { id: "source:incurred" },
    { id: "selected-ultimate" },
  ];

  assert.equal(canHideChartSeries(series, "selected-ultimate", ["source:paid", "source:incurred"]), false);
  assert.equal(canHideChartSeries(series, "source:incurred", ["source:paid"]), true);
});

test("Result Selection exposes Chart immediately after Method with a right-side visibility panel", async () => {
  const [html, chartSource, sharedLegendSource] = await Promise.all([
    readFile(new URL("ui/method_pages/result_selection/result_selection.html", frontendRoot), "utf8"),
    readFile(new URL("ui/method_pages/result_selection/result_selection_chart.js", frontendRoot), "utf8"),
    readFile(new URL("ui/shared/components/chart_legend/chart_legend.js", frontendRoot), "utf8"),
  ]);
  assert.match(html, /data-page="method"[\s\S]*data-page="chart"[\s\S]*data-page="results"/u);
  assert.match(html, /id="rsChartPage"[\s\S]*id="rsChartCanvas"[\s\S]*class="arChartLegendPanel[^"]*"[\s\S]*id="rsChartLegendList"/u);
  assert.doesNotMatch(html, /Click to show or hide|arChartLegendHint/u);
  assert.match(chartSource, /renderChartLegend\(\{/u);
  assert.match(sharedLegendSource, /item\.addEventListener\("contextmenu"/u);
});

test("Result Selection chart has a mode toolbar instead of a header and keeps rectangle zoom", async () => {
  const [html, css, chartSource] = await Promise.all([
    readFile(new URL("ui/method_pages/result_selection/result_selection.html", frontendRoot), "utf8"),
    readFile(new URL("ui/method_pages/result_selection/result_selection.css", frontendRoot), "utf8"),
    readFile(new URL("ui/method_pages/result_selection/result_selection_chart.js", frontendRoot), "utf8"),
  ]);
  assert.doesNotMatch(html, /rsChartHeader|rsChartTitle|rsChartSubtitle/u);
  assert.doesNotMatch(css, /\.rsChartHeader|\.rsChartTitle|\.rsChartSubtitle/u);
  assert.match(html, /id="rsChartModeWeights"[\s\S]*id="rsChartModeZoom"[\s\S]*id="rsChartShowStrip"/u);
  assert.match(html, /id="rsChartZoomBox"/u);
  assert.match(html, /id="rsChartInspectorBody"/u);
  assert.match(html, /id="rsChartSideResizer" role="separator"/u);
  assert.match(css, /grid-template-columns: minmax\(0, 1fr\) var\(--rs-chart-side-width, 290px\);/u);
  assert.match(chartSource, /body\.style\.setProperty\("--rs-chart-side-width"/u);
  assert.match(css, /\.rsChartZoomBox \{/u);
  assert.match(css, /#rsChartPage \.rsChartSegment button \{/u);
  assert.match(chartSource, /\[canvas, "pointerdown", onPointerDown\]/u);
  assert.match(chartSource, /canvas\.setPointerCapture\(event\.pointerId\)/u);
  assert.match(chartSource, /\[canvas, "dblclick", onDoubleClick\]/u);
});

test("Result Selection chart series carry weights, effective shares, and override state", () => {
  const series = buildResultSelectionChartSeries({
    sources: [
      { name: "Paid", values: [10, 20], weights: [1, 0] },
      { name: "Incurred", values: [12, null], weights: [3, 1] },
    ],
    selectedUltimateValues: [11.5, 25],
    calculatedUltimateValues: [11.5, 20],
    overriddenRows: [false, true],
    effectiveWeightAt: (sourceIndex, rowIndex) => [[0.25, 0], [0.75, 0]][sourceIndex][rowIndex],
    rowCount: 2,
  });
  assert.deepEqual(series.map((entry) => entry.sourceIndex), [0, 1, undefined]);
  assert.deepEqual(series[0].weights, [1, 0]);
  assert.deepEqual(series[1].effective, [0.75, 0]);
  assert.deepEqual(series[2].calculated, [11.5, 20]);
  assert.deepEqual(series[2].overridden, [false, true]);
});

test("Weight strip drags keep the pair total and snap to quarters", () => {
  assert.equal(snapStripShare(0.52), 0.5);
  assert.equal(snapStripShare(0.4), 0.4);
  assert.deepEqual(splitStripWeights({ lowerWeight: 1, upperWeight: 1, share: 0.27 }), { lower: 0.5, upper: 1.5 });
  assert.deepEqual(splitStripWeights({ lowerWeight: 2, upperWeight: 1, share: 0.4 }), { lower: 1.2, upper: 1.8 });
  assert.deepEqual(splitStripWeights({ lowerWeight: 1, upperWeight: 2, share: 0.98 }), { lower: 3, upper: 0 });
});

test("Use-only weight changes zero the other methods and skip rows the kept method lacks", () => {
  const series = buildResultSelectionChartSeries({
    sources: [
      { name: "Paid", values: [10, null, 30], weights: [1, 1, 0] },
      { name: "Incurred", values: [12, 22, 32], weights: [1, 1, 2] },
    ],
    rowCount: 3,
  });
  assert.deepEqual(useOnlyWeightChanges(series, [0, 1, 2], [0]), [
    { sourceIndex: 1, rowIndex: 0, weight: 0 },
    { sourceIndex: 0, rowIndex: 2, weight: 1 },
    { sourceIndex: 1, rowIndex: 2, weight: 0 },
  ]);
});

test("Result Selection weight boxes step by 1 on the wheel and the steppers", async () => {
  const fakeInput = (value) => ({
    value,
    disabled: false,
    stepUp() { this.value = String(Number(this.value) + 1); },
    stepDown() { this.value = String(Math.max(0, Number(this.value) - 1)); },
  });
  const wheel = (deltaY) => ({ deltaY, prevented: false, preventDefault() { this.prevented = true; } });
  const input = fakeInput("1.0");
  const up = wheel(-100);
  assert.equal(wheelStepWeight(input, up), true);
  assert.equal(up.prevented, true);
  assert.equal(input.value, "2.0");
  wheelStepWeight(input, wheel(100));
  wheelStepWeight(input, wheel(100));
  wheelStepWeight(input, wheel(100));
  assert.equal(input.value, "0.0");
  const disabled = { ...fakeInput("1.0"), disabled: true };
  assert.equal(wheelStepWeight(disabled, wheel(-100)), false);
  assert.equal(disabled.value, "1.0");

  const [html, css, chartSource] = await Promise.all([
    readFile(new URL("ui/method_pages/result_selection/result_selection.html", frontendRoot), "utf8"),
    readFile(new URL("ui/method_pages/result_selection/result_selection.css", frontendRoot), "utf8"),
    readFile(new URL("ui/method_pages/result_selection/result_selection_chart.js", frontendRoot), "utf8"),
  ]);
  assert.match(html, /id="rsChartSelectionWeight"[^>]*step="1"/u);
  assert.match(chartSource, /const WEIGHT_STEP = 1;/u);
  assert.match(chartSource, /\[selectionBar\.weightInput, "wheel"/u);
  assert.match(css, /\.rsChartCanvas\[data-chart-mode="weights"\] \{\s*cursor: url\("data:image\/svg\+xml/u);
});
