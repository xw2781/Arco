// Dataset Viewer chart: an SVG line chart with a crosshair readout, plus the
// zoom strip drawn under it. Colours come from CSS classes so a theme change
// repaints without a redraw.

const SVG_NS = "http://www.w3.org/2000/svg";
const NEAR_LINE_PX = 16;
const MIN_MARKER_SPACING_PX = 8;
const END_LABEL_GAP_PX = 13;

function svgEl(tag, attrs, parent) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const key in attrs) {
    if (attrs[key] != null) el.setAttribute(key, attrs[key]);
  }
  if (parent) parent.appendChild(el);
  return el;
}

function htmlEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

export function niceTicks(min, max, count) {
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / Math.max(1, count);
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / magnitude;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * magnitude;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step * 1e-6; v += step) ticks.push(Number(v.toFixed(10)));
  return { lo, hi, ticks };
}

function seriesClass(series) {
  if (series.kind === "focus") return `dsChartLine dsChartSlot${series.slot}`;
  return "dsChartLine dsChartContext";
}

function segmentsOf(values, from, to, x, y) {
  const segments = [];
  let current = [];
  for (let i = from; i <= to; i++) {
    const v = values[i];
    if (v == null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push([x(i), y(v)]);
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

const pathData = (points) => "M" + points.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join("L");

export function createLineChart(plotHost, zoomHost, { onPick, onHoverX, onRangeChange } = {}) {
  const svg = svgEl("svg", { class: "dsChartSvg" });
  const tip = htmlEl("div", "dsChartTip");
  plotHost.append(svg, tip);
  const zoomSvg = svgEl("svg", { class: "dsChartZoomSvg" });
  zoomHost.appendChild(zoomSvg);

  let options = null;
  let geometry = null;
  let hoverIndex = null;
  let hoverY = 0;
  let hoverId = null;
  let externalEmphasis = null;
  let hoverLayer = null;
  let renderedEmphasis = null;
  let clipSeq = 0;
  let zoomMap = null;

  const emphasis = () => externalEmphasis || hoverId;

  function render(next) {
    if (next) options = next;
    if (!options) return;
    const width = plotHost.clientWidth;
    const height = plotHost.clientHeight;
    svg.replaceChildren();
    hoverLayer = null;
    geometry = null;
    if (width < 60 || height < 60) return;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);

    const { series, xLabels } = options;
    const count = xLabels.length;
    const [i0, i1] = options.range || [0, Math.max(0, count - 1)];
    let lo = Infinity;
    let hi = -Infinity;
    for (const s of series) {
      for (let i = i0; i <= i1; i++) {
        const v = s.values[i];
        if (v != null) {
          lo = Math.min(lo, v);
          hi = Math.max(hi, v);
        }
      }
    }
    if (!Number.isFinite(lo)) {
      tip.style.display = "none";
      svgEl("text", { x: width / 2, y: height / 2, class: "dsChartEmpty", "text-anchor": "middle" }, svg)
        .textContent = options.emptyText || "Not enough data to plot.";
      renderZoom();
      return;
    }
    if (options.yZero) {
      lo = Math.min(lo, 0);
      hi = Math.max(hi, 0);
    }
    const pad = (hi - lo) * 0.04 || 1;
    hi += pad;
    if (!(options.yZero && lo === 0)) lo -= pad;

    const mt = 14;
    const mb = 46;
    const nice = niceTicks(lo, hi, Math.max(3, Math.round((height - mt - mb) / 56)));
    const yLabels = nice.ticks.map((v) => options.formatAxis(v));
    const ml = Math.max(...yLabels.map((label) => label.length)) * 6.3 + 34;
    const mr = options.endLabelIds?.length ? 78 : 18;
    const pw = Math.max(10, width - ml - mr);
    const ph = Math.max(10, height - mt - mb);
    const span = Math.max(1, i1 - i0);
    const x = (i) => ml + ((i - i0) / span) * pw;
    const y = (v) => mt + (1 - (v - nice.lo) / (nice.hi - nice.lo)) * ph;
    geometry = { x, y, i0, i1, ml, mt, pw, ph, width, height };

    const axes = svgEl("g", {}, svg);
    nice.ticks.forEach((v, k) => {
      const yy = Math.round(y(v)) + 0.5;
      svgEl("line", { x1: ml, x2: ml + pw, y1: yy, y2: yy, class: v === 0 && options.yZero ? "dsChartAxis" : "dsChartGrid" }, axes);
      svgEl("text", { x: ml - 8, y: yy + 4, class: "dsChartTick", "text-anchor": "end" }, axes).textContent = yLabels[k];
    });
    const labelWidth = Math.max(...xLabels.map((label) => String(label).length)) * 6.3 + 10;
    const every = Math.max(1, Math.ceil(labelWidth / (pw / span)));
    for (let i = i0; i <= i1; i++) {
      if ((i - i0) % every) continue;
      const xx = Math.round(x(i)) + 0.5;
      svgEl("line", { x1: xx, x2: xx, y1: mt + ph, y2: mt + ph + 4, class: "dsChartAxis" }, axes);
      svgEl("text", { x: xx, y: mt + ph + 17, class: "dsChartTick", "text-anchor": "middle" }, axes).textContent = xLabels[i];
    }
    svgEl("line", { x1: ml, x2: ml + pw, y1: mt + ph + 0.5, y2: mt + ph + 0.5, class: "dsChartAxis" }, axes);
    svgEl("text", { x: ml + pw / 2, y: height - 8, class: "dsChartAxisTitle", "text-anchor": "middle" }, axes)
      .textContent = options.xTitle;
    svgEl("text", {
      class: "dsChartAxisTitle",
      "text-anchor": "middle",
      transform: `translate(12 ${mt + ph / 2}) rotate(-90)`,
    }, axes).textContent = options.yTitle;

    const clipId = `dsChartClip${++clipSeq}`;
    const clip = svgEl("clipPath", { id: clipId }, svgEl("defs", {}, svg));
    svgEl("rect", { x: ml - 6, y: mt - 6, width: pw + 12, height: ph + 12 }, clip);
    const plot = svgEl("g", { "clip-path": `url(#${clipId})` }, svg);

    const emph = emphasis();
    renderedEmphasis = emph;
    const rank = (s) => (s.id === emph ? 2 : s.kind === "context" ? 0 : 1);
    const markers = pw / span >= MIN_MARKER_SPACING_PX;
    const from = Math.max(0, i0 - 1);
    const to = Math.min(count - 1, i1 + 1);
    for (const s of [...series].sort((a, b) => rank(a) - rank(b))) {
      const state = s.id === emph ? " isEmphasis" : emph && s.kind !== "context" ? " isDimmed" : "";
      const group = svgEl("g", { class: seriesClass(s) + state }, plot);
      for (const segment of segmentsOf(s.values, from, to, x, y)) {
        if (segment.length > 1) svgEl("path", { d: pathData(segment) }, group);
        if ((markers && s.kind === "focus") || segment.length === 1) {
          for (const [px, py] of segment) svgEl("circle", { cx: px, cy: py, r: 2.75, class: "dsChartMarker" }, group);
        }
      }
    }

    const pinned = options.pinned;
    if (pinned && pinned.index >= i0 && pinned.index <= i1) {
      const v = series.find((s) => s.id === pinned.id)?.values[pinned.index];
      if (v != null) {
        svgEl("circle", { cx: x(pinned.index), cy: y(v), r: 6, class: "dsChartPinRing" }, svg);
        svgEl("circle", { cx: x(pinned.index), cy: y(v), r: 2, class: "dsChartPinDot" }, svg);
      }
    }

    drawEndLabels(series, emph);
    hoverLayer = svgEl("g", {}, svg);
    drawHover();
    svg.classList.toggle("isPickable", !!hoverId && !!onPick);
    renderZoom();
  }

  function drawEndLabels(series, emph) {
    const { x, y, i0, i1 } = geometry;
    const items = [];
    for (const id of options.endLabelIds || []) {
      const s = series.find((candidate) => candidate.id === id);
      if (!s) continue;
      let last = -1;
      for (let i = i1; i >= i0; i--) {
        if (s.values[i] != null) { last = i; break; }
      }
      if (last < 0) continue;
      const py = y(s.values[last]);
      items.push({ s, px: x(last), py, ty: py });
    }
    items.sort((a, b) => a.ty - b.ty);
    for (let k = 1; k < items.length; k++) {
      if (items[k].ty - items[k - 1].ty < END_LABEL_GAP_PX) items[k].ty = items[k - 1].ty + END_LABEL_GAP_PX;
    }
    for (const item of items) {
      const dimmed = emph && emph !== item.s.id ? " isDimmed" : "";
      const group = svgEl("g", { class: seriesClass(item.s) + " dsChartEndLabel" + dimmed }, svg);
      svgEl("path", { d: `M${item.px + 4},${item.py}L${item.px + 10},${item.ty}` }, group);
      svgEl("text", { x: item.px + 13, y: item.ty + 4 }, group).textContent = item.s.label;
    }
  }

  function drawHover() {
    if (!hoverLayer || !geometry) return;
    hoverLayer.replaceChildren();
    const { x, y, mt, ph, width, height, i0, i1 } = geometry;
    if (hoverIndex == null || hoverIndex < i0 || hoverIndex > i1) {
      tip.style.display = "none";
      return;
    }
    const xx = Math.round(x(hoverIndex)) + 0.5;
    svgEl("line", { x1: xx, x2: xx, y1: mt, y2: mt + ph, class: "dsChartCrosshair" }, hoverLayer);
    const emph = emphasis();
    const rows = [];
    const others = [];
    for (const s of options.series) {
      const v = s.values[hoverIndex];
      if (v == null) continue;
      if (s.kind === "context" && s.id !== emph) {
        others.push(v);
        continue;
      }
      svgEl("circle", {
        cx: x(hoverIndex), cy: y(v), r: s.id === emph ? 4.5 : 3.5,
        class: `${seriesClass(s)} dsChartHoverDot`,
      }, hoverLayer);
      rows.push({ s, v });
    }
    rows.sort((a, b) => b.v - a.v);
    tip.replaceChildren(htmlEl("div", "dsChartTipTitle", options.tipTitle(hoverIndex)));
    for (const { s, v } of rows) {
      const row = htmlEl("div", "dsChartTipRow" + (s.id === emph ? " isEmphasis" : ""));
      row.append(htmlEl("span", `dsChartTipKey ${seriesClass(s)}`), htmlEl("b", null, options.formatValue(v)), htmlEl("span", null, s.label));
      tip.appendChild(row);
    }
    if (others.length) {
      const row = htmlEl("div", "dsChartTipRow");
      const rangeText = `${options.formatValue(Math.min(...others))} – ${options.formatValue(Math.max(...others))}`;
      row.append(htmlEl("span", "dsChartTipKey"), htmlEl("b", null, rangeText), htmlEl("span", null, `${others.length} others`));
      tip.appendChild(row);
    }
    tip.style.display = "block";
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    let left = x(hoverIndex) + 14;
    if (left + tw > width - 4) left = x(hoverIndex) - 14 - tw;
    tip.style.left = `${Math.max(4, left)}px`;
    tip.style.top = `${clamp(hoverY - th / 2, 4, Math.max(4, height - th - 4))}px`;
  }

  function nearestSeries(fx, index, py) {
    let best = null;
    let bestDistance = NEAR_LINE_PX;
    for (const s of options.series) {
      const a = clamp(Math.floor(fx), 0, s.values.length - 1);
      const b = Math.min(a + 1, s.values.length - 1);
      const va = s.values[a];
      const vb = s.values[b];
      let v = null;
      if (va != null && vb != null) v = va + (vb - va) * (fx - a);
      else if (s.values[index] != null) v = s.values[index];
      if (v == null) continue;
      const distance = Math.abs(geometry.y(v) - py);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = s.id;
      }
    }
    return best;
  }

  function clearHover() {
    if (hoverIndex == null && hoverId == null) return;
    hoverIndex = null;
    const hadEmphasis = hoverId != null;
    hoverId = null;
    if (hadEmphasis && !externalEmphasis) render();
    else drawHover();
    svg.classList.remove("isPickable");
    onHoverX?.(null);
  }

  svg.addEventListener("pointermove", (event) => {
    if (!geometry) return;
    const rect = svg.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const { ml, mt, pw, ph, i0, i1 } = geometry;
    if (px < ml - 10 || px > ml + pw + 10 || py < mt - 10 || py > mt + ph + 10) {
      clearHover();
      return;
    }
    const fx = i0 + ((px - ml) / pw) * Math.max(1, i1 - i0);
    const index = clamp(Math.round(fx), i0, i1);
    const indexChanged = index !== hoverIndex;
    hoverIndex = index;
    hoverY = py;
    hoverId = nearestSeries(fx, index, py);
    if (emphasis() !== renderedEmphasis) render();
    else drawHover();
    svg.classList.toggle("isPickable", !!hoverId && !!onPick);
    if (indexChanged) onHoverX?.(index);
  });
  svg.addEventListener("pointerleave", clearHover);
  svg.addEventListener("click", () => {
    if (hoverId && hoverIndex != null) onPick?.(hoverId, hoverIndex);
  });

  function renderZoom() {
    zoomSvg.replaceChildren();
    zoomMap = null;
    const width = zoomHost.clientWidth;
    const height = zoomHost.clientHeight;
    const count = options?.xLabels.length || 0;
    if (!geometry || width < 60 || count < 3) return;
    zoomSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    zoomSvg.setAttribute("width", width);
    zoomSvg.setAttribute("height", height);
    const { ml, pw } = geometry;
    const bx = (i) => ml + (i / (count - 1)) * pw;
    let lo = Infinity;
    let hi = -Infinity;
    for (const s of options.series) {
      for (const v of s.values) {
        if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      }
    }
    const by = (v) => 5 + (1 - (v - lo) / (hi - lo || 1)) * (height - 10);
    svgEl("rect", { x: ml, y: 0.5, width: pw, height: height - 1, class: "dsChartZoomTrack" }, zoomSvg);
    const lines = svgEl("g", { class: "dsChartZoomLines" }, zoomSvg);
    for (const s of options.series) {
      for (const segment of segmentsOf(s.values, 0, count - 1, bx, by)) {
        if (segment.length > 1) svgEl("path", { d: pathData(segment) }, lines);
      }
    }
    const [i0, i1] = options.range || [0, count - 1];
    svgEl("rect", { x: ml, y: 0, width: Math.max(0, bx(i0) - ml), height, class: "dsChartZoomShade" }, zoomSvg);
    svgEl("rect", { x: bx(i1), y: 0, width: Math.max(0, ml + pw - bx(i1)), height, class: "dsChartZoomShade" }, zoomSvg);
    svgEl("rect", { x: bx(i0), y: 0.5, width: bx(i1) - bx(i0), height: height - 1, rx: 2, class: "dsChartZoomWindow" }, zoomSvg);
    for (const i of [i0, i1]) {
      svgEl("rect", { x: bx(i) - 3, y: height / 2 - 9, width: 6, height: 18, rx: 2, class: "dsChartZoomHandle" }, zoomSvg);
    }
    svgEl("text", { x: ml - 8, y: height / 2 + 4, class: "dsChartTick", "text-anchor": "end" }, zoomSvg).textContent = "Zoom";
    zoomMap = { ml, pw, count, bx };
  }

  zoomSvg.addEventListener("pointerdown", (event) => {
    if (!zoomMap || event.button !== 0) return;
    const { ml, pw, count, bx } = zoomMap;
    const rect = zoomSvg.getBoundingClientRect();
    const toIndex = (clientX) => clamp(Math.round(((clientX - rect.left - ml) / pw) * (count - 1)), 0, count - 1);
    const px = event.clientX - rect.left;
    const [i0, i1] = options.range || [0, count - 1];
    const start = toIndex(event.clientX);
    const span = i1 - i0;
    // With nothing zoomed, a drag anywhere draws a new window.
    let mode = "new";
    if (Math.abs(px - bx(i0)) < 8) mode = "start";
    else if (Math.abs(px - bx(i1)) < 8) mode = "end";
    else if (options.range && px > bx(i0) && px < bx(i1)) mode = "move";
    const offset = start - i0;
    zoomSvg.setPointerCapture(event.pointerId);
    const apply = (a, b) => {
      if (b - a < 1) return;
      const next = a === 0 && b === count - 1 ? null : [a, b];
      const current = options.range;
      if (next?.[0] === current?.[0] && next?.[1] === current?.[1]) return;
      onRangeChange?.(next);
    };
    const move = (moveEvent) => {
      const index = toIndex(moveEvent.clientX);
      if (mode === "start") apply(Math.min(index, i1 - 1), i1);
      else if (mode === "end") apply(i0, Math.max(index, i0 + 1));
      else if (mode === "move") {
        const a = clamp(index - offset, 0, count - 1 - span);
        apply(a, a + span);
      } else apply(Math.min(start, index), Math.max(start, index));
    };
    const end = () => {
      zoomSvg.removeEventListener("pointermove", move);
      zoomSvg.removeEventListener("pointerup", end);
      zoomSvg.removeEventListener("pointercancel", end);
    };
    zoomSvg.addEventListener("pointermove", move);
    zoomSvg.addEventListener("pointerup", end);
    zoomSvg.addEventListener("pointercancel", end);
  });
  zoomSvg.addEventListener("dblclick", () => onRangeChange?.(null));

  return {
    render,
    setEmphasis(id) {
      externalEmphasis = id || null;
      render();
    },
  };
}
