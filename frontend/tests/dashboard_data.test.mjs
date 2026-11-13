import assert from "node:assert/strict";
import test from "node:test";

import {
  applyFilters,
  buildTable,
  buildWidgetResult,
  formatValue,
  niceTicks,
  parseExpression,
  resultToRows,
  runQuery,
} from "../ui/dashboard/dashboard_data.js";
import {
  ASSISTANT_GUIDE,
  applyDefaultFields,
  createDashboard,
  findFreeCell,
  fromAssistantJson,
  normalizeDashboard,
  normalizeWidget,
  resolveLayout,
  toAssistantJson,
} from "../ui/dashboard/dashboard_model.js";

// Two projects, one segment, two origins. `Paid` is a cumulative triangle column, `Ultimate` a
// vector whose value sits on a row with no development period.
const PAYLOAD = {
  columns: [
    { name: "Project", type: "text", role: "dimension", order: ["May", "Aug"] },
    { name: "Segment", type: "text", role: "dimension" },
    { name: "Origin", type: "text", role: "dimension", order: ["2024", "2025"] },
    { name: "Development", type: "text", role: "dimension", order: ["5m", "8m", "17m", "20m"] },
    { name: "Paid", type: "number", role: "measure", default_aggregation: "latest" },
    { name: "Ultimate", type: "number", role: "measure" },
  ],
  rows: [
    ["May", "BI", "2024", null, null, 500],
    ["May", "BI", "2024", "5m", 100, null],
    ["May", "BI", "2024", "17m", 300, null],
    ["May", "BI", "2025", null, null, 400],
    ["May", "BI", "2025", "5m", 80, null],
    ["Aug", "BI", "2024", null, null, 520],
    ["Aug", "BI", "2024", "8m", 150, null],
    ["Aug", "BI", "2024", "20m", 340, null],
    ["Aug", "BI", "2025", null, null, 450],
    ["Aug", "BI", "2025", "8m", 120, null],
  ],
  semi_additive: { partition: ["Project", "Segment", "Origin"], order: "Development" },
};

const table = buildTable(PAYLOAD);
const widget = (raw) => normalizeWidget({ type: "bar", source: "src1", ...raw });

test("latest totals the newest development period of each origin, never the whole triangle", () => {
  const [all] = runQuery(table, { measures: [{ field: "Paid", agg: "latest" }, { field: "Paid", agg: "sum" }, { field: "Ultimate", agg: "sum" }] });
  assert.deepEqual(all.values, [300 + 80 + 340 + 120, 100 + 300 + 80 + 150 + 340 + 120, 500 + 400 + 520 + 450]);
  const may = runQuery(table, { rows: applyFilters(table, [{ field: "Project", values: ["May"] }]), dims: ["Origin"], measures: [{ field: "Paid" }] });
  assert.deepEqual(may.map((group) => [group.keys[0], group.values[0]]), [["2024", 300], ["2025", 80]]);
});

test("a calculation combines aggregated fields and yields no value on a zero divisor", () => {
  const [group] = runQuery(table, {
    rows: applyFilters(table, [{ field: "Project", values: ["Aug"] }]),
    measures: [{ expr: "latest([Paid]) / sum([Ultimate])" }, { expr: "([Ultimate] - [Paid]) * 2" }, { expr: "sum([Paid]) / (1 - 1)" }],
  });
  assert.equal(group.values[0], (340 + 120) / (520 + 450));
  assert.equal(group.values[1], ((520 + 450) - (340 + 120)) * 2);
  assert.equal(group.values[2], null);
  assert.throws(() => parseExpression("latest([Paid]) /"), /incomplete/);
  assert.throws(() => parseExpression("median([Paid])"), /Unknown function/);
});

test("compare charts the movement between two values of a field", () => {
  const result = buildWidgetResult(table, widget({
    category: "Origin",
    measures: [{ field: "Paid", agg: "latest" }, { field: "Ultimate", agg: "sum" }],
    compare: { field: "Project", base: "May", target: "Aug", mode: "delta" },
  }));
  assert.deepEqual(result.categories.map((category) => category.label), ["2024", "2025"]);
  assert.deepEqual(result.series.map((series) => series.values), [[40, 40], [20, 50]]);
  assert.equal(result.series[0].label, "Paid Change");
  const percent = buildWidgetResult(table, widget({
    type: "kpi",
    measures: [{ field: "Ultimate", agg: "sum" }],
    compare: { field: "Project", base: "May", target: "Aug", mode: "percent" },
  }));
  assert.equal(percent.series[0].values[0], (970 - 900) / 900);
  assert.equal(formatValue(percent.series[0].values[0], percent.measures[0]), "+7.8%");
});

test("a breakdown makes one series per value in the field's own order, with filters applied", () => {
  const result = buildWidgetResult(
    table,
    widget({ category: "Origin", series: "Project", measures: [{ field: "Ultimate", agg: "sum" }] }),
    [{ field: "Origin", values: ["2025"] }],
  );
  assert.deepEqual(result.series.map((series) => [series.label, series.values]), [["May", [400]], ["Aug", [450]]]);
  assert.deepEqual(resultToRows(result), { header: ["Origin", "May", "Aug"], rows: [["2025", "400", "450"]] });
});

test("more than eight series fold into Other without losing their total", () => {
  const rows = [];
  for (let index = 0; index < 12; index += 1) rows.push([`S${index}`, "A", 12 - index]);
  const wide = buildTable({
    columns: [{ name: "Name", type: "text", role: "dimension" }, { name: "Group", type: "text", role: "dimension" }, { name: "Value", type: "number", role: "measure" }],
    rows,
  });
  const result = buildWidgetResult(wide, widget({ category: "Group", series: "Name", measures: [{ field: "Value", agg: "sum" }] }));
  assert.equal(result.series.length, 8);
  assert.equal(result.series.at(-1).label, "Other");
  assert.equal(result.series.at(-1).values[0], 5 + 4 + 3 + 2 + 1);
  assert.equal(result.folded, 5);
});

test("sorting by value and a limit keep the largest categories", () => {
  const result = buildWidgetResult(table, widget({
    category: "Origin",
    measures: [{ field: "Ultimate", agg: "sum" }],
    sort: { by: "value", dir: "desc" },
    limit: 1,
  }));
  assert.deepEqual(result.categories.map((category) => category.label), ["2024"]);
  assert.equal(result.cut, 1);
});

test("a widget naming a missing field reports it instead of drawing", () => {
  assert.match(buildWidgetResult(table, widget({ category: "Origin", measures: [{ field: "Nope" }] })).error, /no field named "Nope"/);
  assert.equal(buildWidgetResult(table, widget({ category: "Origin" })).error, "Choose a measure.");
});

test("numbers format by the measure's choice", () => {
  assert.equal(formatValue(1234567.8, {}), "1,234,568");
  assert.equal(formatValue(1234567.8, {}, { short: true }), "1.2M");
  assert.equal(formatValue(0.4567, { format: "percent" }), "45.7%");
  assert.equal(formatValue(-1500, { format: "currency" }), "-$1,500");
  assert.equal(formatValue(null, {}), "");
  assert.deepEqual(niceTicks(0, 970), [0, 200, 400, 600, 800, 1000]);
});

test("the layout keeps a moved widget's cell and closes gaps above the rest", () => {
  const widgets = [
    normalizeWidget({ id: "a", type: "bar", layout: { x: 0, y: 0, w: 6, h: 4 } }),
    normalizeWidget({ id: "b", type: "bar", layout: { x: 0, y: 2, w: 6, h: 4 } }),
    normalizeWidget({ id: "c", type: "kpi", layout: { x: 8, y: 9, w: 3, h: 2 } }),
  ];
  const settled = Object.fromEntries(resolveLayout(widgets, "b").map((item) => [item.id, item.layout]));
  assert.deepEqual([settled.b.y, settled.a.y, settled.c.y], [0, 4, 0]);
  assert.deepEqual(findFreeCell(resolveLayout(widgets), 6, 3), { x: 6, y: 2 });
});

test("ArcBot edits a dashboard without its saved tables and gets them back on apply", () => {
  const dashboard = normalizeDashboard({
    name: "Review",
    sources: [{ id: "src1", kind: "arco_datasets", projects: ["P"], reserving_classes: ["A\\B"], datasets: ["Paid"], extract: PAYLOAD }],
    pages: [{ name: "Overview", widgets: [{ id: "w1", type: "bar", source: "src1", category: "Origin", measures: [{ field: "Paid", agg: "latest" }] }] }],
  });
  const shared = toAssistantJson(dashboard);
  assert.equal(shared.sources[0].extract, undefined);
  assert.deepEqual(shared.sources[0].fields[4], { name: "Paid", role: "measure", default_aggregation: "latest" });
  shared.pages[0].widgets.push({ type: "kpi", source: "src1", measures: [{ field: "Ultimate", agg: "sum" }], layout: { x: 0, y: 0, w: 3, h: 2 } });
  const applied = fromAssistantJson(shared, dashboard);
  assert.equal(applied.sources[0].extract, PAYLOAD);
  assert.equal(applied.sources[0].fields, undefined);
  assert.deepEqual(applied.pages[0].widgets.map((item) => item.id), ["w1", "w2"]);
  assert.match(ASSISTANT_GUIDE, /latest/);
});

test("a new widget takes its first fields from the source it is dropped on", () => {
  const dashboard = normalizeDashboard({ sources: [{ id: "src1", kind: "csv", path: "x.csv", extract: PAYLOAD }] });
  const heatmap = applyDefaultFields(normalizeWidget({ type: "heatmap" }), dashboard.sources[0]);
  assert.deepEqual([heatmap.source, heatmap.category, heatmap.series, heatmap.measures], ["src1", "Origin", "Development", [{ field: "Paid", agg: "latest" }]]);
  assert.equal(createDashboard("X").pages.length, 1);
});
