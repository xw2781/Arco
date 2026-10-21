import { state } from "/ui/shared/dataset/dataset_state.js";
import {
  formatDatasetOriginLabel,
  getDatasetOriginLabelText,
} from "/ui/shared/dataset/dataset_origin_labels.js";
import {
  formatDatasetChartValue,
  renderTable,
} from "/ui/shared/tabs/data/dataset_grid_view.js?v=20260919a";
import { normalizeRange } from "/ui/shared/components/spreadsheet/table_selection.js?v=20260726a";
import { createLineChart } from "/ui/dataset_viewer/tabs/dataset_chart_renderer.js?v=20261020d";
import { createTriangleMinimap } from "/ui/dataset_viewer/tabs/dataset_chart_minimap.js?v=20261020d";
import {
  addFocusedSeries,
  buildChartMatrix,
  buildChartSeries,
  defaultFocusIds,
  effectiveDevLabels,
  focusColorIndex,
  removeFocusedSeries,
} from "/ui/dataset_viewer/tabs/dataset_chart_series.js?v=20261020c";

// Focus and context: every series is drawn as grey context, each focused
// series gets a colour, and the minimap picks what to focus.
const COMPACT_AXIS_FROM = 10000;
// The triangle panel is resizable; below LIST_BELOW_PX its cells are too small
// to pick from, so it becomes a checkbox list of the plotted series.
const MINIMAP_DEFAULT_PX = 280;
const MINIMAP_MIN_PX = 120;
const MINIMAP_MAX_PX = 560;
const MINIMAP_MAX_SHARE = 0.6;
const MINIMAP_LIST_BELOW_PX = 200;
const MINIMAP_KEY_STEP_PX = 16;
// More focused series than this draw without end labels, which would pile up.
const END_LABELS_UP_TO = 10;
const VALUE_TITLES = {
  value: "Value",
  incremental: "Incremental Value",
  ratio: "Age-To-Age Factor",
};
const compactFormat = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

const chart = {
  plot: "byRow",
  values: "value",
  range: null,
  // A box zoom's value window; null lets the axis fit the focused lines.
  yRange: null,
  shapeKey: "",
  // Right-clicking a series in the triangle or the list shows it alone.
  solo: { byRow: null, byCol: null },
  // The last series picked, where a shift-click range starts.
  anchor: { byRow: null, byCol: null },
  focus: { byRow: null, byCol: null },
  slots: { byRow: {}, byCol: {} },
};
let ui = null;
let view = null;
let minimapWidth = MINIMAP_DEFAULT_PX;

function focusFor(plot) {
  if (!chart.focus[plot]) {
    chart.focus[plot] = [];
    chart.slots[plot] = {};
  }
  return chart.focus[plot];
}

function addFocus(plot, id) {
  addFocusedSeries(focusFor(plot), chart.slots[plot], id);
}

// Series per year along the focused axis: origins for origin curves, ages for the age trend.
function focusPeriodsPerYear(plot) {
  return periodsPerYear(selectedLength(plot === "byRow" ? "originLenSelect" : "devLenSelect"));
}

function resetFocusToDefault(plot, list) {
  chart.focus[plot] = [];
  chart.slots[plot] = {};
  for (const id of defaultFocusIds(list, plot, focusPeriodsPerYear(plot))) addFocus(plot, id);
}

const slotClass = (slot) => `dsChartSlot${focusColorIndex(slot)}`;

function clearZoom() {
  chart.range = null;
  chart.yRange = null;
}

// A second right-click on the series already shown alone brings the rest back.
function toggleSolo(plot, id) {
  setPlot(plot);
  chart.solo[plot] = chart.solo[plot] === id ? null : id;
  if (chart.solo[plot]) addFocus(plot, id);
  chart.yRange = null;
  renderDatasetChart();
}

function toggleFocus(id) {
  chart.solo[chart.plot] = null;
  const ids = focusFor(chart.plot);
  if (ids.includes(id)) removeFocusedSeries(ids, chart.slots[chart.plot], id);
  else addFocus(chart.plot, id);
  renderDatasetChart();
}

// Click toggles one series; shift-click focuses every series from the last one
// picked through this one. Picking a series of the other plot switches to it.
function pickSeries(plot, id, { extend = false } = {}) {
  const list = view?.list || [];
  if (chart.plot !== plot) {
    setPlot(plot);
    chart.solo[plot] = null;
    addFocus(plot, id);
  } else {
    chart.solo[plot] = null;
    const from = list.findIndex((series) => series.id === chart.anchor[plot]);
    const to = list.findIndex((series) => series.id === id);
    if (extend && from >= 0 && to >= 0) {
      for (let i = Math.min(from, to); i <= Math.max(from, to); i++) addFocus(plot, list[i].id);
    } else {
      const ids = focusFor(plot);
      if (ids.includes(id)) removeFocusedSeries(ids, chart.slots[plot], id);
      else addFocus(plot, id);
    }
  }
  chart.anchor[plot] = id;
  renderDatasetChart();
}

function focusState(list, ids) {
  const count = list.filter((series) => ids.includes(series.id)).length;
  return count === 0 ? "none" : count === list.length ? "all" : "some";
}

// The select-all box: with every series focused it clears them, otherwise it
// focuses them all, like a tri-state checkbox.
function toggleAllFocus() {
  const list = view?.list || [];
  const plot = chart.plot;
  chart.solo[plot] = null;
  if (focusState(list, focusFor(plot)) === "all") {
    chart.focus[plot] = [];
    chart.slots[plot] = {};
  } else {
    for (const series of list) addFocus(plot, series.id);
  }
  renderDatasetChart();
}

function resetAllFocus() {
  chart.solo[chart.plot] = null;
  resetFocusToDefault(chart.plot, view?.list || []);
  renderDatasetChart();
}

const defaultFocusText = (plot) => (plot === "byRow" ? "the latest 3 years" : "the first 3 years");

function setPlot(plot) {
  if (chart.plot === plot) return;
  chart.plot = plot;
  clearZoom();
}

function selectedLength(id) {
  return Number(document.getElementById(id)?.value) || 12;
}

const periodsPerYear = (months) => (months < 12 && 12 % months === 0 ? 12 / months : 1);

function isTransposed() {
  return document.getElementById("transposedChk")?.checked === true;
}

function activeModelCell() {
  const cell = state.activeCell;
  if (!cell) return null;
  return isTransposed() ? { r: cell.c, c: cell.r } : { r: cell.r, c: cell.c };
}

// The chart's active cell is the Data grid's active cell.
function selectModelCell(r, c) {
  const cell = isTransposed() ? { r: c, c: r } : { r, c };
  state.activeCell = cell;
  state.selectionAnchor = cell;
  state.selRanges = [normalizeRange(cell.r, cell.c, cell.r, cell.c)];
  renderTable();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function setSegment(group, value, disabled = () => false) {
  for (const button of group.querySelectorAll("button[data-value]")) {
    const on = button.dataset.value === value;
    button.classList.toggle("isOn", on);
    button.setAttribute("aria-pressed", String(on));
    button.disabled = disabled(button.dataset.value);
  }
}

function onSegment(group, handler) {
  group.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-value]");
    if (button && !button.disabled) handler(button.dataset.value);
  });
}

function setMinimapWidth(width) {
  const room = ui.body.clientWidth;
  const max = room > 0 ? Math.min(MINIMAP_MAX_PX, Math.floor(room * MINIMAP_MAX_SHARE)) : MINIMAP_MAX_PX;
  minimapWidth = Math.round(Math.min(Math.max(width, MINIMAP_MIN_PX), Math.max(max, MINIMAP_MIN_PX)));
  ui.body.style.setProperty("--ds-chart-minimap-width", `${minimapWidth}px`);
}

function wireMinimapResizer() {
  const handle = ui.resizer;
  let frame = 0;
  const resizeTo = (width) => {
    setMinimapWidth(width);
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      renderDatasetChart();
    });
  };
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = minimapWidth;
    ui.body.classList.add("isResizing");
    const move = (moveEvent) => resizeTo(startWidth + moveEvent.clientX - startX);
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      handle.removeEventListener("lostpointercapture", end);
      ui.body.classList.remove("isResizing");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end);
  });
  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    resizeTo(minimapWidth + (event.key === "ArrowRight" ? MINIMAP_KEY_STEP_PX : -MINIMAP_KEY_STEP_PX));
  });
  handle.addEventListener("dblclick", () => resizeTo(MINIMAP_DEFAULT_PX));
}

// The chart's length buttons are a view of the Data tab's length lists: a click
// writes the list and fires its change, so the reload runs exactly as it would
// from the Data tab, and a length the Data tab mutes or locks is disabled here.
function lengthSelectFor(group) {
  return document.getElementById(group.dataset.lenSelect);
}

function renderLengthControls() {
  for (const group of ui.lengths) {
    const select = lengthSelectFor(group);
    const options = [...(select?.options || [])];
    const locked = !!select?.closest(".lenSelectWrap")?.hasAttribute("data-locked-value");
    group.replaceChildren(...options.map((option) => {
      const button = el("button", null, option.textContent || option.value);
      button.type = "button";
      button.dataset.value = option.value;
      return button;
    }));
    const unavailable = new Set(options.filter((o) => o.disabled || o.dataset.unavailable === "1").map((o) => o.value));
    setSegment(group, select?.value ?? "", (value) => locked || unavailable.has(value));
  }
}

function wireLengthControls() {
  for (const group of ui.lengths) {
    onSegment(group, (value) => {
      const select = lengthSelectFor(group);
      if (!select || select.value === value) return;
      select.value = value;
      select.dispatchEvent(new Event("change"));
      renderLengthControls();
    });
    lengthSelectFor(group)?.addEventListener("change", () => {
      if (ui?.root.isConnected) renderLengthControls();
    });
  }
}

function ensureUi() {
  if (ui?.root.isConnected) return true;
  const root = document.getElementById("dsChartRoot");
  if (!root) return false;
  const byId = (id) => document.getElementById(id);
  ui = {
    root,
    plotMode: byId("dsChartPlotMode"),
    valuesMode: byId("dsChartValuesMode"),
    lengths: [byId("dsChartOriginLen"), byId("dsChartDevLen")].filter(Boolean),
    status: byId("dsChartStatus"),
    body: byId("dsChartBody"),
    minimapPanel: byId("dsChartMinimapPanel"),
    panelHead: byId("dsChartPanelHead"),
    filterList: byId("dsChartFilterList"),
    resizer: byId("dsChartMinimapResizer"),
  };
  setMinimapWidth(minimapWidth);
  wireMinimapResizer();
  wireLengthControls();
  ui.chart = createLineChart(byId("dsChartPlot"), byId("dsChartZoom"), {
    onPick: (id) => toggleFocus(id),
    onHoverX: (index) => ui.minimap.setCross(index),
    onRangeChange: (range, yRange) => {
      chart.range = range;
      chart.yRange = yRange || null;
      renderDatasetChart();
    },
  });
  ui.minimap = createTriangleMinimap(byId("dsChartMinimap"), {
    onPickOrigin: (r, how) => pickSeries("byRow", `o:${view.matrix.originLabels[r]}`, how),
    onPickAge: (c, how) => pickSeries("byCol", `d:${view.matrix.colKeys[c]}`, how),
    onPickAll: toggleAllFocus,
    onResetAll: resetAllFocus,
    onPickCell: (r, c) => {
      chart.solo[chart.plot] = null;
      addFocus(chart.plot, chart.plot === "byRow" ? `o:${view.matrix.originLabels[r]}` : `d:${view.matrix.colKeys[c]}`);
      selectModelCell(r, c);
    },
    onZoomBox: ({ r0, r1, c0, c1 }) => {
      const [a, b] = chart.plot === "byRow" ? [c0, c1] : [r0, r1];
      if (b - a < 1) return;
      chart.range = [a, b];
      chart.yRange = null;
      renderDatasetChart();
    },
    onSoloOrigin: (r) => toggleSolo("byRow", `o:${view.matrix.originLabels[r]}`),
    onSoloAge: (c) => toggleSolo("byCol", `d:${view.matrix.colKeys[c]}`),
  });
  onSegment(ui.plotMode, (plot) => {
    setPlot(plot);
    renderDatasetChart();
  });
  onSegment(ui.valuesMode, (mode) => {
    if (mode === chart.values) return;
    chart.values = mode;
    clearZoom();
    renderDatasetChart();
  });
  return true;
}

// The panel's head names the panel, counts the focused series, and says when
// one series is shown alone.
function renderPanelHead(title, list, ids) {
  const head = ui.panelHead;
  head.replaceChildren(
    el("span", "dsChartPanelTitle", title),
    el("span", "dsChartFocusCount", `${list.filter((series) => ids.includes(series.id)).length} of ${list.length} focused`),
  );
  const solo = chart.solo[chart.plot];
  if (!solo) return;
  const label = list.find((series) => series.id === solo)?.label ?? "";
  const showAll = el("button", "dsChartLinkButton", "Show all");
  showAll.type = "button";
  showAll.addEventListener("click", () => toggleSolo(chart.plot, solo));
  head.append(el("span", "dsChartPanelSolo", `Only ${label}`), showAll);
}

// Clicks are handled on the row, so the checkbox never toggles itself: click
// toggles, shift-click focuses a range, right-click shows the series alone.
function filterRow(className, label, checked, onClick, onContext, hint) {
  const item = el("label", checked ? `${className} isChecked` : className);
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.tabIndex = -1;
  item.title = hint;
  item.addEventListener("click", (event) => {
    event.preventDefault();
    onClick(event);
  });
  item.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    onContext();
  });
  item.append(input, el("span", null, label));
  return { item, input };
}

function renderFilterList(list, ids, slots) {
  const box = ui.filterList;
  const scrollTop = box.scrollTop;
  const state = focusState(list, ids);
  const all = filterRow(
    "dsChartFilterItem isAll",
    "All",
    state === "all",
    toggleAllFocus,
    resetAllFocus,
    `Click to focus all or none; right-click for ${defaultFocusText(chart.plot)}`,
  );
  all.input.indeterminate = state === "some";
  box.replaceChildren(all.item, ...list.map((series) => {
    const checked = ids.includes(series.id);
    const { item } = filterRow(
      "dsChartFilterItem",
      series.label,
      checked,
      (event) => pickSeries(chart.plot, series.id, { extend: event.shiftKey }),
      () => toggleSolo(chart.plot, series.id),
      "Click to focus or drop; shift-click for a range; right-click to show it alone",
    );
    item.addEventListener("pointerenter", () => ui.chart.setEmphasis(series.id));
    item.addEventListener("pointerleave", () => ui.chart.setEmphasis(null));
    if (checked) item.appendChild(el("i", `dsChartChipKey ${slotClass(slots[series.id])}`));
    return item;
  }));
  box.scrollTop = scrollTop;
}

function renderStatus({ matrix, xLabels, active, formatValue }) {
  const status = ui.status;
  status.replaceChildren();
  const left = el("span");
  const activeValue = active ? matrix.values[active.r]?.[active.c] : null;
  if (activeValue != null) {
    left.append(
      el("span", "dsChartPinKey"),
      "Active cell ",
      el("b", null, `${matrix.originLabels[active.r]} · Age ${matrix.colLabels[active.c]}`),
      " = ",
      el("b", null, formatValue(activeValue)),
    );
  } else {
    left.textContent = "Click a grey line to focus it, or a coloured line to drop it.";
  }
  const right = el("span");
  if (chart.range || chart.yRange) {
    const reset = el("button", "dsChartLinkButton", "Reset zoom");
    reset.type = "button";
    reset.addEventListener("click", () => {
      clearZoom();
      renderDatasetChart();
    });
    const parts = [];
    if (chart.range) parts.push(`${xLabels[chart.range[0]]} to ${xLabels[chart.range[1]]}`);
    if (chart.yRange) parts.push(`values ${chart.yRange.map(formatValue).join(" to ")}`);
    right.append(`Showing ${parts.join(", ")} `, reset);
  } else {
    right.textContent = "Drag a box on the chart to zoom; double-click to reset.";
  }
  status.append(left, right);
}

export function renderDatasetChart() {
  if (!ensureUi()) return;
  const matrix = buildChartMatrix(state.model, chart.values);
  const devCount = effectiveDevLabels(state.model).length;
  setSegment(ui.plotMode, chart.plot);
  setSegment(ui.valuesMode, chart.values, (mode) => mode !== "value" && devCount < 2);
  renderLengthControls();
  const compact = minimapWidth < MINIMAP_LIST_BELOW_PX;
  ui.minimapPanel.classList.toggle("isCompact", compact);

  if (!matrix || !matrix.values.length || !matrix.colLabels.length) {
    view = null;
    ui.chart.render({ series: [], xLabels: [], emptyText: "No data." });
    ui.minimap.render(null);
    ui.filterList.replaceChildren();
    ui.panelHead.textContent = "Triangle";
    ui.status.replaceChildren();
    return;
  }

  const shapeKey = `${chart.values}|${matrix.originLabels.join(",")}|${matrix.colLabels.join(",")}`;
  if (shapeKey !== chart.shapeKey) {
    chart.shapeKey = shapeKey;
    clearZoom();
  }
  const originLen = selectedLength("originLenSelect");
  const formatOrigin = (label) => formatDatasetOriginLabel(label, originLen);
  const plot = chart.plot;
  const { xLabels, list } = buildChartSeries(matrix, plot, formatOrigin);
  if (chart.range && chart.range[1] > xLabels.length - 1) clearZoom();

  if (!chart.focus[plot]) resetFocusToDefault(plot, list);
  const ids = focusFor(plot);
  const slots = chart.slots[plot];
  const known = new Set(list.map((series) => series.id));
  for (const id of [...ids]) if (!known.has(id)) removeFocusedSeries(ids, slots, id);

  if (chart.solo[plot] && !known.has(chart.solo[plot])) chart.solo[plot] = null;
  const solo = chart.solo[plot];
  const series = list
    .filter((s) => !solo || s.id === solo)
    .map((s) => (ids.includes(s.id)
      ? { ...s, kind: "focus", slot: focusColorIndex(slots[s.id]) }
      : { ...s, kind: "context" }));

  const active = activeModelCell();
  const pinned = active && (plot === "byRow"
    ? { id: `o:${matrix.originLabels[active.r]}`, index: active.c }
    : { id: `d:${matrix.colKeys[active.c]}`, index: active.r });
  const ratio = chart.values === "ratio";
  const formatValue = ratio ? (v) => v.toFixed(3) : formatDatasetChartValue;
  const largest = matrix.values.reduce((m, row) => row.reduce((n, v) => (v == null ? n : Math.max(n, Math.abs(v))), m), 0);
  const formatAxis = ratio
    ? (v) => v.toFixed(2)
    : largest >= COMPACT_AXIS_FROM ? (v) => compactFormat.format(v) : formatDatasetChartValue;

  view = { matrix, list };
  ui.chart.render({
    series,
    xLabels,
    xTitle: plot === "byRow" ? (ratio ? "Age Interval" : "Development Age") : getDatasetOriginLabelText(originLen),
    yTitle: VALUE_TITLES[chart.values],
    // Zoomed in, the axis fits the visible values instead of reaching down to zero.
    yZero: !ratio && !chart.range,
    range: chart.range,
    yRange: chart.yRange,
    pinned,
    endLabelIds: solo ? [solo] : ids.length <= END_LABELS_UP_TO ? ids : [],
    formatAxis,
    formatValue,
    tipTitle: (i) => (plot === "byRow" ? `Age ${xLabels[i]}` : xLabels[i]),
  });
  if (compact) {
    ui.minimap.render(null);
    renderFilterList(list, ids, slots);
  } else {
    ui.filterList.replaceChildren();
    ui.minimap.render({
      values: matrix.values,
      rowLabels: matrix.originLabels.map(formatOrigin),
      colLabels: matrix.colKeys,
      rowsPerYear: periodsPerYear(originLen),
      colsPerYear: periodsPerYear(selectedLength("devLenSelect")),
      plot,
      focus: (solo ? [solo] : ids).map((id) => ({ index: list.findIndex((s) => s.id === id), slot: focusColorIndex(slots[id]) })),
      active,
      range: chart.range,
      formatValue,
      rowAction: plot === "byRow"
        ? "Click to focus or drop; shift-click for a range; right-click to show it alone"
        : "Click to plot this origin's curve; right-click to show it alone",
      colAction: plot === "byCol"
        ? "Click to focus or drop; shift-click for a range; right-click to show it alone"
        : "Click to plot this age across origins; right-click to show it alone",
      allState: focusState(list, ids),
      allLabel: plot === "byRow" ? "All origins" : "All ages",
      allAction: `Click to focus all or none; right-click for ${defaultFocusText(plot)}`,
    });
  }
  renderPanelHead(compact ? (plot === "byRow" ? "Origins" : "Ages") : "Triangle", list, ids);
  renderStatus({ matrix: { ...matrix, originLabels: matrix.originLabels.map(formatOrigin) }, xLabels, active, formatValue });
}

export function redrawDatasetChartSafely() {
  const panel = document.getElementById("chartPanel");
  if (!panel) return;
  const rect = panel.getBoundingClientRect();
  if (rect.width < 50 || rect.height < 50) return;
  renderDatasetChart();
}
