// Chart renderers. Each takes the result `buildWidgetResult` produced and draws it into a host
// element at a given size. Marks take their colour from the `--db-*` tokens in dashboard.css, so
// a theme change repaints without a redraw, and every label is set as text, never as markup.
//
// Mark rules (bar width, corner radius, gaps, line weight, one axis per chart) follow the
// dashboard chart guide in docs/ui/dashboard.md.

import { formatValue, niceTicks } from "./dashboard_data.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHAR_WIDTH = 6.1;
const AXIS_FONT = 11;
const MAX_BAR = 24;
const BAR_RADIUS = 4;
const GAP = 2;
const SHARE_PARTS = 6;

function svg(tag, attrs = {}, text = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value != null) node.setAttribute(name, String(value));
  }
  if (text != null) node.textContent = text;
  return node;
}

function html(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function clip(label, maxChars) {
  const text = String(label ?? "");
  if (maxChars < 2) return "";
  return text.length > maxChars ? `${text.slice(0, Math.max(1, maxChars - 1))}…` : text;
}

export function seriesColor(index, series = null) {
  if (series?.foldedOther) return "var(--db-series-other)";
  return `var(--db-series-${(index % 8) + 1})`;
}

// ---------------------------------------------------------------------------
// Tooltip: one element for the whole page
// ---------------------------------------------------------------------------

let tooltipEl = null;

function tooltip() {
  if (!tooltipEl) {
    tooltipEl = html("div", "dbTooltip");
    tooltipEl.hidden = true;
    document.body.appendChild(tooltipEl);
  }
  return tooltipEl;
}

// `rows` are {color, value, label}; the value leads and the series name follows.
export function showTooltip(event, title, rows) {
  const tip = tooltip();
  tip.replaceChildren();
  if (title) tip.appendChild(html("div", "dbTooltipTitle", title));
  for (const row of rows) {
    const line = html("div", "dbTooltipRow");
    const key = html("span", "dbTooltipKey");
    if (row.color) key.style.background = row.color;
    else key.hidden = true;
    line.append(key, html("strong", "", row.value), html("span", "dbTooltipLabel", row.label || ""));
    tip.appendChild(line);
  }
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  const left = Math.min(window.innerWidth - box.width - 8, event.clientX + 14);
  const top = event.clientY + 16 + box.height > window.innerHeight ? event.clientY - box.height - 10 : event.clientY + 16;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}

export function hideTooltip() {
  if (tooltipEl) tooltipEl.hidden = true;
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

function message(host, text) {
  host.replaceChildren(html("div", "dbWidgetMessage", text));
}

function legend(host, entries) {
  const row = html("div", "dbLegend");
  for (const entry of entries) {
    const item = html("span", "dbLegendItem");
    const swatch = html("span", entry.line ? "dbLegendLine" : "dbLegendSwatch");
    swatch.style.background = entry.color;
    item.append(swatch, html("span", "", entry.label));
    row.appendChild(item);
  }
  host.appendChild(row);
  return row;
}

function note(host, result) {
  const parts = [];
  if (result.folded) parts.push(`${result.folded} smaller series are grouped as Other`);
  if (result.cut) parts.push(`${result.cut} more not shown`);
  if (parts.length) host.appendChild(html("div", "dbChartNote", parts.join(" · ")));
}

function valueDomain(values, { includeZero = true } = {}) {
  let low = Infinity;
  let high = -Infinity;
  for (const value of values) {
    if (value == null) continue;
    if (value < low) low = value;
    if (value > high) high = value;
  }
  if (low === Infinity) return [0, 1];
  if (includeZero) { low = Math.min(0, low); high = Math.max(0, high); }
  const ticks = niceTicks(low, high, 4);
  return [ticks[0], ticks[ticks.length - 1], ticks];
}

// The frame every axis chart shares: a legend row, then an SVG sized to what is left.
function chartFrame(host, result, size, { lineKeys = false } = {}) {
  host.replaceChildren();
  if (result.series.length > 1) {
    legend(host, result.series.map((series, index) => ({ label: series.label, color: seriesColor(index, series), line: lineKeys })));
  }
  note(host, result);
  const used = [...host.children].reduce((total, child) => total + child.getBoundingClientRect().height, 0);
  const width = Math.max(120, size.width);
  const height = Math.max(90, size.height - used);
  const root = svg("svg", { class: "dbChart", width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
  host.appendChild(root);
  return { root, width, height };
}

function tooltipRows(result, categoryIndex) {
  return result.series
    .map((series, index) => ({
      color: seriesColor(index, series),
      value: formatValue(series.values[categoryIndex], result.measures[series.measure]) || "–",
      label: series.label,
    }));
}

function drawValueAxis(root, { ticks, scale, x0, x1, measure, horizontal = false, y0 = 0, y1 = 0 }) {
  const group = svg("g", { class: "dbAxis" });
  for (const tick of ticks) {
    const position = scale(tick);
    if (horizontal) {
      group.appendChild(svg("line", { class: tick === 0 ? "dbBaseline" : "dbGrid", x1: position, x2: position, y1: y0, y2: y1 }));
      group.appendChild(svg("text", { class: "dbTick", x: position, y: y1 + 14, "text-anchor": "middle" }, formatValue(tick, measure, { short: true })));
    } else {
      group.appendChild(svg("line", { class: tick === 0 ? "dbBaseline" : "dbGrid", x1: x0, x2: x1, y1: position, y2: position }));
      group.appendChild(svg("text", { class: "dbTick", x: x0 - 6, y: position + 3.5, "text-anchor": "end" }, formatValue(tick, measure, { short: true })));
    }
  }
  root.appendChild(group);
}

function axisLabelWidth(ticks, measure) {
  return Math.max(...ticks.map((tick) => formatValue(tick, measure, { short: true }).length)) * CHAR_WIDTH + 12;
}

function drawCategoryLabels(root, labels, { x0, band, y }) {
  const group = svg("g", { class: "dbAxis" });
  const widest = Math.max(...labels.map((label) => label.length), 1) * CHAR_WIDTH;
  const step = Math.max(1, Math.ceil((Math.min(widest, 90) + 8) / band));
  const room = Math.floor((band * step - 6) / CHAR_WIDTH);
  labels.forEach((label, index) => {
    if (index % step) return;
    group.appendChild(svg("text", { class: "dbTick", x: x0 + band * (index + 0.5), y, "text-anchor": "middle" }, clip(label, room)));
  });
  root.appendChild(group);
}

// A bar from the baseline to its value, rounded only at the data end.
function barPath(x, y, width, height, { up = true, horizontal = false, round = true } = {}) {
  const radius = round ? Math.min(BAR_RADIUS, width / 2, height) : 0;
  if (horizontal) {
    // `x` is the baseline edge, `width` runs along the value, `height` is the thickness.
    const r = round ? Math.min(BAR_RADIUS, height / 2, width) : 0;
    if (up) return `M${x},${y}h${width - r}a${r},${r} 0 0 1 ${r},${r}v${height - 2 * r}a${r},${r} 0 0 1 ${-r},${r}h${-(width - r)}z`;
    return `M${x},${y}h${-(width - r)}a${r},${r} 0 0 0 ${-r},${r}v${height - 2 * r}a${r},${r} 0 0 0 ${r},${r}h${width - r}z`;
  }
  if (up) return `M${x},${y + height}v${-(height - radius)}a${radius},${radius} 0 0 1 ${radius},${-radius}h${width - 2 * radius}a${radius},${radius} 0 0 1 ${radius},${radius}v${height - radius}z`;
  return `M${x},${y}v${height - radius}a${radius},${radius} 0 0 0 ${radius},${radius}h${width - 2 * radius}a${radius},${radius} 0 0 0 ${radius},${-radius}v${-(height - radius)}z`;
}

function wireCategoryHits(root, result, ctx, rects) {
  rects.forEach((rect, index) => {
    const category = result.categories[index];
    rect.addEventListener("pointermove", (event) => {
      root.querySelectorAll("[data-cat]").forEach((mark) => mark.classList.toggle("dbDim", mark.dataset.cat !== String(index)));
      showTooltip(event, category.label, tooltipRows(result, index));
    });
    rect.addEventListener("pointerleave", () => {
      root.querySelectorAll(".dbDim").forEach((mark) => mark.classList.remove("dbDim"));
      hideTooltip();
    });
    if (result.categoryField && ctx.onSelect) {
      rect.classList.add("dbClickable");
      rect.addEventListener("click", () => ctx.onSelect(result.categoryField, category.key));
    }
  });
}

// ---------------------------------------------------------------------------
// Bar
// ---------------------------------------------------------------------------

function stackExtents(result) {
  const totals = result.categories.map((_, index) => {
    let positive = 0;
    let negative = 0;
    for (const series of result.series) {
      const value = series.values[index];
      if (value > 0) positive += value;
      else if (value < 0) negative += value;
    }
    return [negative, positive];
  });
  return totals.flat();
}

function renderBar(host, widget, result, ctx) {
  const stacked = !!widget.options?.stacked && result.series.length > 1;
  const horizontal = !!widget.options?.horizontal;
  const { root, width, height } = chartFrame(host, result, ctx.size);
  const measure = result.measures[result.series[0].measure];
  const [low, high, ticks] = valueDomain(stacked ? stackExtents(result) : result.series.flatMap((series) => series.values));
  const labels = result.categories.map((category) => category.label);
  const count = labels.length;
  const hits = [];

  if (horizontal) {
    const labelWidth = Math.min(width * 0.38, Math.max(...labels.map((label) => label.length), 3) * CHAR_WIDTH + 10);
    const plot = { x0: labelWidth, x1: width - 44, y0: 4, y1: height - 20 };
    const band = (plot.y1 - plot.y0) / count;
    const scale = (value) => plot.x0 + ((value - low) / (high - low)) * (plot.x1 - plot.x0);
    drawValueAxis(root, { ticks, scale, measure, horizontal: true, y0: plot.y0, y1: plot.y1 });
    const perBand = stacked ? 1 : result.series.length;
    const thickness = Math.max(2, Math.min(MAX_BAR, (band * 0.78 - GAP * (perBand - 1)) / perBand));
    result.categories.forEach((category, index) => {
      const top = plot.y0 + band * index + (band - (thickness * perBand + GAP * (perBand - 1))) / 2;
      root.appendChild(svg("text", { class: "dbTick", x: plot.x0 - 6, y: plot.y0 + band * (index + 0.5) + 3.5, "text-anchor": "end" }, clip(category.label, Math.floor((labelWidth - 8) / CHAR_WIDTH))));
      let positive = 0;
      let negative = 0;
      result.series.forEach((series, seriesIndex) => {
        const value = series.values[index];
        if (value == null || value === 0) return;
        const from = stacked ? (value > 0 ? positive : negative) : 0;
        const to = from + value;
        if (stacked) { if (value > 0) positive = to; else negative = to; }
        const start = scale(from);
        const length = Math.max(1, Math.abs(scale(to) - start) - (stacked && from !== 0 ? GAP : 0));
        const y = stacked ? top : top + seriesIndex * (thickness + GAP);
        const lastOfStack = !stacked || result.series.slice(seriesIndex + 1).every((later) => !((later.values[index] || 0) * value > 0));
        const edge = value > 0 ? start + (stacked && from !== 0 ? GAP : 0) : start - (stacked && from !== 0 ? GAP : 0);
        root.appendChild(svg("path", { class: "dbMark", d: barPath(edge, y, length, thickness, { up: value > 0, horizontal: true, round: lastOfStack }), fill: seriesColor(seriesIndex, series), "data-cat": index }));
      });
      if (result.series.length === 1 && result.series[0].values[index] != null) {
        const value = result.series[0].values[index];
        root.appendChild(svg("text", { class: "dbValueLabel", x: scale(Math.max(value, 0)) + 5, y: plot.y0 + band * (index + 0.5) + 3.5 }, formatValue(value, measure, { short: true })));
      }
      const hit = svg("rect", { class: "dbHit", x: 0, y: plot.y0 + band * index, width, height: band });
      root.appendChild(hit);
      hits.push(hit);
    });
    wireCategoryHits(root, result, ctx, hits);
    return;
  }

  const left = axisLabelWidth(ticks, measure);
  const plot = { x0: left, x1: width - 6, y0: 8, y1: height - 22 };
  const band = (plot.x1 - plot.x0) / count;
  const scale = (value) => plot.y1 - ((value - low) / (high - low)) * (plot.y1 - plot.y0);
  drawValueAxis(root, { ticks, scale, x0: plot.x0, x1: plot.x1, measure });
  drawCategoryLabels(root, labels, { x0: plot.x0, band, y: plot.y1 + 15 });
  const perBand = stacked ? 1 : result.series.length;
  const thickness = Math.max(2, Math.min(MAX_BAR, (band * 0.8 - GAP * (perBand - 1)) / perBand));
  const showLabels = !!widget.options?.labels && result.series.length === 1 && band >= 34;
  result.categories.forEach((category, index) => {
    const start = plot.x0 + band * index + (band - (thickness * perBand + GAP * (perBand - 1))) / 2;
    let positive = 0;
    let negative = 0;
    result.series.forEach((series, seriesIndex) => {
      const value = series.values[index];
      if (value == null || value === 0) return;
      const from = stacked ? (value > 0 ? positive : negative) : 0;
      const to = from + value;
      if (stacked) { if (value > 0) positive = to; else negative = to; }
      const gap = stacked && from !== 0 ? GAP : 0;
      const yFrom = scale(from);
      const yTo = scale(to);
      const barHeight = Math.max(1, Math.abs(yFrom - yTo) - gap);
      const x = stacked ? start : start + seriesIndex * (thickness + GAP);
      const lastOfStack = !stacked || result.series.slice(seriesIndex + 1).every((later) => !((later.values[index] || 0) * value > 0));
      const y = value > 0 ? yTo : yFrom + gap;
      root.appendChild(svg("path", { class: "dbMark", d: barPath(x, y, thickness, barHeight, { up: value > 0, round: lastOfStack }), fill: seriesColor(seriesIndex, series), "data-cat": index }));
      if (showLabels) {
        root.appendChild(svg("text", { class: "dbValueLabel", x: x + thickness / 2, y: value > 0 ? yTo - 4 : yTo + 12, "text-anchor": "middle" }, formatValue(value, measure, { short: true })));
      }
    });
    const hit = svg("rect", { class: "dbHit", x: plot.x0 + band * index, y: 0, width: band, height });
    root.appendChild(hit);
    hits.push(hit);
  });
  wireCategoryHits(root, result, ctx, hits);
}

// ---------------------------------------------------------------------------
// Line and area
// ---------------------------------------------------------------------------

function renderLine(host, widget, result, ctx) {
  const area = widget.type === "area";
  const { root, width, height } = chartFrame(host, result, ctx.size, { lineKeys: !area });
  const measure = result.measures[result.series[0].measure];
  const [low, high, ticks] = valueDomain(result.series.flatMap((series) => series.values), { includeZero: area });
  const left = axisLabelWidth(ticks, measure);
  const plot = { x0: left, x1: width - 10, y0: 8, y1: height - 22 };
  const count = result.categories.length;
  const band = (plot.x1 - plot.x0) / count;
  const xAt = (index) => plot.x0 + band * (index + 0.5);
  const scale = (value) => plot.y1 - ((value - low) / (high - low)) * (plot.y1 - plot.y0);
  drawValueAxis(root, { ticks, scale, x0: plot.x0, x1: plot.x1, measure });
  drawCategoryLabels(root, result.categories.map((category) => category.label), { x0: plot.x0, band, y: plot.y1 + 15 });
  const floor = scale(Math.max(low, Math.min(high, 0)));
  const markers = count <= 24;

  result.series.forEach((series, seriesIndex) => {
    const color = seriesColor(seriesIndex, series);
    const runs = [];
    let run = [];
    series.values.forEach((value, index) => {
      if (value == null) { if (run.length) runs.push(run); run = []; return; }
      run.push([xAt(index), scale(value)]);
    });
    if (run.length) runs.push(run);
    for (const points of runs) {
      const line = points.map((point, index) => `${index ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join("");
      if (area && points.length > 1) {
        root.appendChild(svg("path", { class: "dbArea", d: `${line}L${points[points.length - 1][0].toFixed(1)},${floor}L${points[0][0].toFixed(1)},${floor}Z`, fill: color }));
      }
      root.appendChild(svg("path", { class: "dbLine", d: line, stroke: color }));
      if (markers || points.length === 1) {
        for (const point of points) root.appendChild(svg("circle", { class: "dbDot", cx: point[0], cy: point[1], r: 3.5, fill: color }));
      }
    }
  });

  const cross = svg("line", { class: "dbCrosshair", y1: plot.y0, y2: plot.y1, visibility: "hidden" });
  const hit = svg("rect", { class: "dbHit", x: plot.x0, y: 0, width: plot.x1 - plot.x0, height });
  root.append(cross, hit);
  const indexAt = (event) => {
    const box = root.getBoundingClientRect();
    const x = (event.clientX - box.left) * (width / box.width);
    return Math.max(0, Math.min(count - 1, Math.floor((x - plot.x0) / band)));
  };
  hit.addEventListener("pointermove", (event) => {
    const index = indexAt(event);
    cross.setAttribute("x1", xAt(index));
    cross.setAttribute("x2", xAt(index));
    cross.setAttribute("visibility", "visible");
    showTooltip(event, result.categories[index].label, tooltipRows(result, index));
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTooltip(); });
  if (result.categoryField && ctx.onSelect) {
    hit.classList.add("dbClickable");
    hit.addEventListener("click", (event) => ctx.onSelect(result.categoryField, result.categories[indexAt(event)].key));
  }
}

// ---------------------------------------------------------------------------
// Scatter
// ---------------------------------------------------------------------------

function renderScatter(host, widget, result, ctx) {
  host.replaceChildren();
  const names = result.seriesNames || [];
  if (names.length > 1) legend(host, names.map((name, index) => ({ label: name, color: seriesColor(index) })));
  const used = [...host.children].reduce((total, child) => total + child.getBoundingClientRect().height, 0);
  const width = Math.max(120, ctx.size.width);
  const height = Math.max(90, ctx.size.height - used);
  const root = svg("svg", { class: "dbChart", width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
  host.appendChild(root);
  const [xMeasure, yMeasure] = result.measures;
  const [xLow, xHigh, xTicks] = valueDomain(result.points.map((point) => point.x), { includeZero: false });
  const [yLow, yHigh, yTicks] = valueDomain(result.points.map((point) => point.y), { includeZero: false });
  const left = axisLabelWidth(yTicks, yMeasure) + 14;
  const plot = { x0: left, x1: width - 14, y0: 8, y1: height - 36 };
  const xScale = (value) => plot.x0 + ((value - xLow) / (xHigh - xLow)) * (plot.x1 - plot.x0);
  const yScale = (value) => plot.y1 - ((value - yLow) / (yHigh - yLow)) * (plot.y1 - plot.y0);
  drawValueAxis(root, { ticks: yTicks, scale: yScale, x0: plot.x0, x1: plot.x1, measure: yMeasure });
  drawValueAxis(root, { ticks: xTicks, scale: xScale, measure: xMeasure, horizontal: true, y0: plot.y0, y1: plot.y1 });
  root.appendChild(svg("text", { class: "dbAxisTitle", x: (plot.x0 + plot.x1) / 2, y: height - 4, "text-anchor": "middle" }, clip(xMeasure.label, 60)));
  root.appendChild(svg("text", { class: "dbAxisTitle", x: 10, y: (plot.y0 + plot.y1) / 2, "text-anchor": "middle", transform: `rotate(-90 10 ${(plot.y0 + plot.y1) / 2})` }, clip(yMeasure.label, 40)));
  const placed = result.points.map((point) => {
    const dot = svg("circle", { class: "dbDot", cx: xScale(point.x), cy: yScale(point.y), r: 4.5, fill: seriesColor(Math.max(0, names.indexOf(point.series))) });
    root.appendChild(dot);
    return { point, dot, x: xScale(point.x), y: yScale(point.y) };
  });
  // The pointer only has to be nearest a dot, not on it.
  const hit = svg("rect", { class: "dbHit", x: 0, y: 0, width, height });
  root.appendChild(hit);
  const nearest = (event) => {
    const box = root.getBoundingClientRect();
    const x = (event.clientX - box.left) * (width / box.width);
    const y = (event.clientY - box.top) * (height / box.height);
    let best = null;
    for (const item of placed) {
      const distance = Math.hypot(item.x - x, item.y - y);
      if (distance <= 28 && (!best || distance < best.distance)) best = { ...item, distance };
    }
    return best;
  };
  hit.addEventListener("pointermove", (event) => {
    const found = nearest(event);
    placed.forEach((item) => item.dot.classList.toggle("dbFocus", found?.dot === item.dot));
    if (!found) return hideTooltip();
    showTooltip(event, found.point.series ? `${found.point.label} · ${found.point.series}` : found.point.label, [
      { value: formatValue(found.point.x, xMeasure), label: xMeasure.label },
      { value: formatValue(found.point.y, yMeasure), label: yMeasure.label },
    ]);
  });
  hit.addEventListener("pointerleave", () => { placed.forEach((item) => item.dot.classList.remove("dbFocus")); hideTooltip(); });
  if (result.categoryField && ctx.onSelect) {
    hit.addEventListener("click", (event) => { const found = nearest(event); if (found) ctx.onSelect(result.categoryField, found.point.key); });
  }
}

// ---------------------------------------------------------------------------
// Heat map
// ---------------------------------------------------------------------------

function renderHeatmap(host, widget, result, ctx) {
  host.replaceChildren();
  const measure = result.measures[0];
  const values = result.series.flatMap((series) => series.values).filter((value) => value != null);
  const low = Math.min(...values);
  const high = Math.max(...values);
  // A change (compare) or a measure crossing zero has two directions, so it gets two hues around
  // a neutral middle; anything else is one hue from light to dark.
  const diverging = measure.compare || (low < 0 && high > 0);
  const reach = Math.max(Math.abs(low), Math.abs(high)) || 1;
  const strength = (value) => (diverging ? Math.abs(value) / reach : high === low ? 0.6 : (value - low) / (high - low));

  const scaleRow = html("div", "dbHeatScale");
  const ramp = html("span", diverging ? "dbHeatRamp dbHeatRampDiverging" : "dbHeatRamp");
  scaleRow.append(html("span", "", formatValue(diverging ? -reach : low, measure, { short: true })), ramp, html("span", "", formatValue(diverging ? reach : high, measure, { short: true })));
  host.appendChild(scaleRow);
  const used = scaleRow.getBoundingClientRect().height;
  const width = Math.max(120, ctx.size.width);
  const height = Math.max(90, ctx.size.height - used);
  const root = svg("svg", { class: "dbChart", width, height, viewBox: `0 0 ${width} ${height}`, role: "img" });
  host.appendChild(root);

  const rows = result.categories;
  const columns = result.series;
  const labelWidth = Math.min(width * 0.3, Math.max(...rows.map((row) => row.label.length), 3) * CHAR_WIDTH + 10);
  const plot = { x0: labelWidth, x1: width - 2, y0: 18, y1: height - 2 };
  const cellWidth = (plot.x1 - plot.x0) / columns.length;
  const cellHeight = (plot.y1 - plot.y0) / rows.length;
  const columnStep = Math.max(1, Math.ceil(46 / cellWidth));
  columns.forEach((column, index) => {
    if (index % columnStep) return;
    root.appendChild(svg("text", { class: "dbTick", x: plot.x0 + cellWidth * (index + 0.5), y: 12, "text-anchor": "middle" }, clip(column.label, Math.floor((cellWidth * columnStep - 4) / CHAR_WIDTH))));
  });
  const rowStep = Math.max(1, Math.ceil(13 / cellHeight));
  const showValues = cellWidth >= 40 && cellHeight >= 17;
  rows.forEach((row, rowIndex) => {
    if (!(rowIndex % rowStep)) {
      root.appendChild(svg("text", { class: "dbTick", x: plot.x0 - 6, y: plot.y0 + cellHeight * (rowIndex + 0.5) + 3.5, "text-anchor": "end" }, clip(row.label, Math.floor((labelWidth - 8) / CHAR_WIDTH))));
    }
    columns.forEach((column, columnIndex) => {
      const value = column.values[rowIndex];
      if (value == null) return;
      const weight = strength(value);
      const cell = svg("rect", {
        class: "dbCell",
        x: plot.x0 + cellWidth * columnIndex + 1,
        y: plot.y0 + cellHeight * rowIndex + 1,
        width: Math.max(1, cellWidth - GAP),
        height: Math.max(1, cellHeight - GAP),
        rx: 2,
        fill: diverging ? (value < 0 ? "var(--db-diverge-low)" : "var(--db-diverge-high)") : "var(--db-sequential)",
        "fill-opacity": (0.06 + 0.94 * weight).toFixed(3),
      });
      cell.addEventListener("pointermove", (event) => {
        cell.classList.add("dbFocus");
        showTooltip(event, `${row.label} · ${column.label}`, [{ value: formatValue(value, measure), label: measure.label }]);
      });
      cell.addEventListener("pointerleave", () => { cell.classList.remove("dbFocus"); hideTooltip(); });
      if (ctx.onSelect) {
        cell.classList.add("dbClickable");
        cell.addEventListener("click", () => ctx.onSelect(result.categoryField, row.key));
      }
      root.appendChild(cell);
      if (showValues) {
        root.appendChild(svg("text", {
          class: weight > 0.6 ? "dbCellLabel dbCellLabelStrong" : "dbCellLabel",
          x: plot.x0 + cellWidth * (columnIndex + 0.5),
          y: plot.y0 + cellHeight * (rowIndex + 0.5) + 3.5,
          "text-anchor": "middle",
        }, formatValue(value, measure, { short: true })));
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Share bar, number tile, table, text
// ---------------------------------------------------------------------------

function renderShare(host, widget, result) {
  host.replaceChildren();
  const measure = result.measures[0];
  let parts = result.categories
    .map((category, index) => ({ label: category.label, value: result.series[0].values[index] }))
    .filter((part) => part.value > 0)
    .sort((a, b) => b.value - a.value);
  if (parts.length > SHARE_PARTS) {
    const rest = parts.slice(SHARE_PARTS - 1);
    parts = [...parts.slice(0, SHARE_PARTS - 1), { label: `Other (${rest.length})`, value: rest.reduce((sum, part) => sum + part.value, 0), other: true }];
  }
  const total = parts.reduce((sum, part) => sum + part.value, 0);
  if (!total) return message(host, "Nothing to show.");
  const bar = html("div", "dbShareBar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", parts.map((part) => `${part.label} ${((part.value / total) * 100).toFixed(0)}%`).join(", "));
  parts.forEach((part, index) => {
    const block = html("div", "dbShareBlock");
    const share = part.value / total;
    block.style.flexGrow = String(share);
    block.style.background = part.other ? "var(--db-series-other)" : seriesColor(index);
    const text = `${(share * 100).toFixed(share < 0.1 ? 1 : 0)}%`;
    const label = html("span", `dbShareLabel dbShareLabel${index === 3 && !part.other ? "Dark" : "Light"}`, text);
    block.appendChild(label);
    block.addEventListener("pointermove", (event) => showTooltip(event, part.label, [
      { value: formatValue(part.value, measure), label: measure.label },
      { value: text, label: "Share" },
    ]));
    block.addEventListener("pointerleave", hideTooltip);
    bar.appendChild(block);
  });
  host.appendChild(bar);
  // A block too narrow for its figure prints none; the tooltip and the table view still carry it.
  for (const block of bar.children) {
    const label = block.firstChild;
    if (label.scrollWidth + 12 > block.clientWidth) label.hidden = true;
  }
  legend(host, parts.map((part, index) => ({ label: part.label, color: part.other ? "var(--db-series-other)" : seriesColor(index) })));
}

function sparkline(points, width, height) {
  const known = points.filter((value) => value != null);
  if (known.length < 2) return null;
  const low = Math.min(...known);
  const high = Math.max(...known);
  const root = svg("svg", { class: "dbSpark", width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  const xAt = (index) => 3 + (index / (points.length - 1)) * (width - 6);
  const yAt = (value) => height - 4 - ((value - low) / (high - low || 1)) * (height - 8);
  let path = "";
  let last = null;
  points.forEach((value, index) => {
    if (value == null) return;
    path += `${path ? "L" : "M"}${xAt(index).toFixed(1)},${yAt(value).toFixed(1)}`;
    last = [xAt(index), yAt(value)];
  });
  root.appendChild(svg("path", { class: "dbSparkLine", d: path }));
  root.appendChild(svg("circle", { class: "dbSparkDot", cx: last[0], cy: last[1], r: 3 }));
  return root;
}

// `result.kpi` is {value, delta, deltaMeasure, trend} prepared by the canvas.
function renderKpi(host, widget, result, ctx) {
  host.replaceChildren();
  const measure = result.measures[0];
  const kpi = result.kpi || { value: result.series[0].values[0] };
  const tile = html("div", "dbKpi");
  tile.appendChild(html("div", "dbKpiValue", formatValue(kpi.value, { ...measure, compare: false, compareMode: "" }, { short: true }) || "–"));
  if (kpi.delta != null) {
    const delta = html("div", "dbKpiDelta");
    delta.append(
      html("span", "dbKpiArrow", kpi.delta > 0 ? "▲" : kpi.delta < 0 ? "▼" : "●"),
      html("span", "", formatValue(kpi.delta, kpi.deltaMeasure, { short: true })),
      html("span", "dbKpiBase", `vs ${widget.compare.base}`),
    );
    tile.appendChild(delta);
  }
  host.appendChild(tile);
  if (kpi.trend) {
    const spark = sparkline(kpi.trend, Math.max(60, Math.min(220, ctx.size.width - 8)), Math.max(22, Math.min(44, ctx.size.height - tile.getBoundingClientRect().height - 4)));
    if (spark) host.appendChild(spark);
  }
}

export function renderTable(host, result, ctx = {}) {
  host.replaceChildren();
  const scroller = html("div", "dbTableScroll");
  const table = html("table", "dbTable");
  const head = html("tr");
  const columns = result.points
    ? [result.categoryField || "Item", result.measures[0].label, result.measures[1].label]
    : [...(result.categoryField ? [result.categoryField] : []), ...result.series.map((series) => series.label)];
  columns.forEach((name, index) => {
    const cell = html("th", index === 0 && (result.points || result.categoryField) ? "" : "dbNumber", name);
    head.appendChild(cell);
  });
  const thead = html("thead");
  thead.appendChild(head);
  const body = html("tbody");
  const addRow = (cells, key) => {
    const row = html("tr");
    cells.forEach((cell, index) => row.appendChild(html("td", index === 0 && (result.points || result.categoryField) ? "" : "dbNumber", cell)));
    if (key !== undefined && result.categoryField && ctx.onSelect) {
      row.classList.add("dbClickable");
      row.addEventListener("click", () => ctx.onSelect(result.categoryField, key));
    }
    body.appendChild(row);
  };
  if (result.points) {
    for (const point of result.points) addRow([point.label, formatValue(point.x, result.measures[0]), formatValue(point.y, result.measures[1])], point.key);
  } else {
    result.categories.forEach((category, index) => {
      const values = result.series.map((series) => formatValue(series.values[index], result.measures[series.measure]));
      addRow(result.categoryField ? [category.label, ...values] : values, category.key);
    });
  }
  table.append(thead, body);
  scroller.appendChild(table);
  host.appendChild(scroller);
  note(host, result);
}

export function renderText(host, widget) {
  host.replaceChildren();
  const block = html("div", "dbText");
  let list = null;
  for (const raw of String(widget.text || "").split(/\r?\n/)) {
    const line = raw.trimEnd();
    if (line.startsWith("- ")) {
      if (!list) { list = html("ul"); block.appendChild(list); }
      list.appendChild(html("li", "", line.slice(2)));
      continue;
    }
    list = null;
    if (line.startsWith("# ")) block.appendChild(html("h3", "", line.slice(2)));
    else if (line.trim()) block.appendChild(html("p", "", line));
  }
  if (!block.children.length) block.appendChild(html("p", "dbMuted", "Empty text"));
  host.appendChild(block);
}

const RENDERERS = { bar: renderBar, line: renderLine, area: renderLine, scatter: renderScatter, heatmap: renderHeatmap, share: renderShare, kpi: renderKpi };

// Draw one widget's result into `host`. `ctx` is {size:{width,height}, onSelect(field, value)}.
export function renderWidget(host, widget, result, ctx) {
  hideTooltip();
  if (widget.type === "text") return renderText(host, widget);
  if (!result) return message(host, "Choose a data source.");
  if (result.error) return message(host, result.error);
  if (result.empty) return message(host, "No data for these filters.");
  if (widget.type === "table" || widget.options?.table) return renderTable(host, result, ctx);
  return RENDERERS[widget.type](host, widget, result, ctx);
}
