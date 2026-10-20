// Dataset Viewer chart minimap: the whole triangle drawn to fit its panel, with
// edge strips for picking an origin or an age, a loupe for small cells, and a
// drag box that zooms the chart.

const TOP_STRIP_PX = 18;
const MAX_CELL_PX = 18;
const MIN_CELL_PX = 0.5;
const CRISP_CELL_PX = 6;
const ROW_LABEL_GAP_PX = 12;
const LOUPE_RADIUS = 3;
const LOUPE_CELL_PX = 14;
const LOUPE_BELOW_CELL_PX = 10;
const DRAG_START_PX = 4;
const LABEL_FONT = "10px Arial, \"Segoe UI\", Tahoma, sans-serif";

const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

// Label every `step` rows or columns: whole years when the cells are too small
// to label each period, doubling until labels clear `minGapPx`.
export function labelStep(cellPx, perYear, minGapPx) {
  let step = perYear > 1 && cellPx < minGapPx ? perYear : 1;
  while (step * cellPx < minGapPx) step *= 2;
  return step;
}

export function yearText(label) {
  return String(label).match(/\d{4}/)?.[0] || String(label);
}

export function columnShade(values) {
  const cols = values.reduce((n, row) => Math.max(n, row.length), 0);
  const range = [];
  for (let c = 0; c < cols; c++) {
    let lo = Infinity;
    let hi = -Infinity;
    for (const row of values) {
      const v = row[c];
      if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    }
    range.push([lo, hi]);
  }
  return (r, c) => {
    const v = values[r]?.[c];
    if (v == null) return null;
    const [lo, hi] = range[c];
    return hi > lo ? (v - lo) / (hi - lo) : 0.5;
  };
}

function readColors(host) {
  const style = getComputedStyle(host);
  const read = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
  return {
    cellRgb: read("--ds-chart-minimap-rgb", "43, 109, 246"),
    mark: read("--ds-chart-minimap-mark", "rgba(15, 23, 42, 0.22)"),
    cross: read("--ds-chart-minimap-cross", "rgba(15, 23, 42, 0.08)"),
    text: read("--ds-chart-text-muted", "#64748b"),
    strong: read("--ds-chart-text-strong", "#0f172a"),
    accent: read("--ds-chart-accent", "#2b6df6"),
    focus: [1, 2, 3, 4].map((n) => read(`--ds-chart-focus-${n}`, "#2a78d6")),
  };
}

export function createTriangleMinimap(host, { onPickOrigin, onPickAge, onPickCell, onZoomBox } = {}) {
  const canvas = document.createElement("canvas");
  canvas.className = "dsChartMinimapCanvas";
  host.appendChild(canvas);
  const tip = document.createElement("div");
  tip.className = "dsChartMinimapTip";
  document.body.appendChild(tip);

  let data = null;
  let layout = null;
  let cross = null;
  let hover = null;
  let dragBox = null;
  let shade = null;

  function computeLayout(ctx, width, height) {
    const rows = data.values.length;
    const cols = data.colLabels.length;
    // Small cells stay fractional so a large triangle still fills the panel.
    const fit = (left) => {
      const size = clamp(Math.min((width - left - 6) / cols, (height - TOP_STRIP_PX - 6) / rows), MIN_CELL_PX, MAX_CELL_PX);
      return size >= CRISP_CELL_PX ? Math.floor(size) : size;
    };
    ctx.font = LABEL_FONT;
    let cell = fit(56);
    const rowStep = labelStep(cell, data.rowsPerYear, ROW_LABEL_GAP_PX);
    const rowText = (r) => (data.rowsPerYear > 1 && rowStep % data.rowsPerYear === 0 ? yearText(data.rowLabels[r]) : String(data.rowLabels[r]));
    let widest = 0;
    for (let r = 0; r < rows; r += rowStep) widest = Math.max(widest, ctx.measureText(rowText(r)).width);
    const left = Math.max(28, Math.ceil(widest) + 12);
    cell = fit(left);
    const colWidest = data.colLabels.reduce((w, label) => Math.max(w, ctx.measureText(String(label)).width), 0);
    const colStep = labelStep(cell, data.colsPerYear, colWidest + 4);
    // Whole-year age labels sit on the year's last period (12, 24, ...).
    const colOffset = data.colsPerYear > 1 && colStep % data.colsPerYear === 0 ? data.colsPerYear - 1 : 0;
    return { rows, cols, cell, left, top: TOP_STRIP_PX, gap: cell >= CRISP_CELL_PX ? 1 : 0, rowStep, colStep, colOffset, rowText };
  }

  function draw() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    layout = null;
    if (!data || !data.values.length || !data.colLabels.length || width < 40 || height < 40) return;
    const colors = readColors(host);
    const L = computeLayout(ctx, width, height);
    layout = L;
    const { rows, cols, cell, left, top, gap } = L;
    const byRow = data.plot === "byRow";

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const t = shade(r, c);
        if (t == null) continue;
        ctx.fillStyle = `rgba(${colors.cellRgb}, ${(0.06 + 0.5 * t).toFixed(3)})`;
        ctx.fillRect(left + c * cell, top + r * cell, cell - gap, cell - gap);
      }
    }

    ctx.strokeStyle = colors.mark;
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (data.colsPerYear > 1 && cell < 8) {
      for (let c = data.colsPerYear; c < cols; c += data.colsPerYear) {
        const xx = Math.round(left + c * cell) + 0.5;
        ctx.moveTo(xx, top);
        ctx.lineTo(xx, top + rows * cell);
      }
    }
    if (data.rowsPerYear > 1 && cell < 8) {
      for (let r = data.rowsPerYear; r < rows; r += data.rowsPerYear) {
        const yy = Math.round(top + r * cell) + 0.5;
        ctx.moveTo(left, yy);
        ctx.lineTo(left + cols * cell, yy);
      }
    }
    ctx.stroke();

    if (cross != null) {
      ctx.fillStyle = colors.cross;
      if (byRow && cross < cols) ctx.fillRect(left + cross * cell, top, cell, rows * cell);
      if (!byRow && cross < rows) ctx.fillRect(left, top + cross * cell, cols * cell, cell);
    }

    if (data.range) {
      const [a, b] = data.range;
      ctx.fillStyle = colors.accent;
      if (byRow) ctx.fillRect(left + a * cell, top - 3, (b - a + 1) * cell, 2);
      else ctx.fillRect(left - 3, top + a * cell, 2, (b - a + 1) * cell);
    }

    const focused = new Map((data.focus || []).map(({ index, slot }) => [index, slot]));
    for (const [index, slot] of focused) {
      ctx.fillStyle = colors.focus[slot] || colors.accent;
      if (byRow) ctx.fillRect(left - 5, top + index * cell, 3, Math.max(cell - gap, 2));
      else ctx.fillRect(left + index * cell, top - 6, Math.max(cell - gap, 2), 3);
    }

    ctx.font = LABEL_FONT;
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    for (let r = 0; r < rows; r += L.rowStep) {
      const isFocused = byRow && focused.has(r);
      const isLit = (!byRow && cross === r) || (hover?.zone === "row" && hover.r === r);
      ctx.fillStyle = isFocused || isLit ? colors.strong : colors.text;
      ctx.fillText(L.rowText(r), left - 8, top + r * cell + cell / 2);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    for (let c = L.colOffset; c < cols; c += L.colStep) {
      const isFocused = !byRow && focused.has(c);
      const isLit = (byRow && cross === c) || (hover?.zone === "col" && hover.c === c);
      ctx.fillStyle = isFocused || isLit ? colors.strong : colors.text;
      const text = String(data.colLabels[c]);
      const half = ctx.measureText(text).width / 2;
      ctx.fillText(text, Math.min(left + c * cell + cell / 2, width - half - 1), top - 8);
    }

    const outline = (r, c, lineWidth) => {
      const size = Math.max(cell, 5);
      const offset = (size - cell) / 2;
      ctx.lineWidth = lineWidth;
      ctx.strokeRect(left + c * cell - offset + lineWidth / 2, top + r * cell - offset + lineWidth / 2, size - lineWidth, size - lineWidth);
    };
    ctx.strokeStyle = colors.strong;
    if (hover?.zone === "cell" && !dragBox) outline(hover.r, hover.c, 1);
    if (data.active && data.active.r < rows && data.active.c < cols) outline(data.active.r, data.active.c, 2);

    if (dragBox) {
      const x0 = left + dragBox.c0 * cell;
      const y0 = top + dragBox.r0 * cell;
      const w = (dragBox.c1 - dragBox.c0 + 1) * cell;
      const h = (dragBox.r1 - dragBox.r0 + 1) * cell;
      ctx.fillStyle = `rgba(${colors.cellRgb}, 0.08)`;
      ctx.fillRect(x0, y0, w, h);
      ctx.strokeStyle = colors.accent;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 2]);
      ctx.strokeRect(x0 + 0.5, y0 + 0.5, w - 1, h - 1);
      ctx.setLineDash([]);
    }
  }

  function hitTest(clientX, clientY) {
    if (!layout) return null;
    const rect = canvas.getBoundingClientRect();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const { left, top, cell, rows, cols } = layout;
    const c = Math.floor((px - left) / cell);
    const r = Math.floor((py - top) / cell);
    if (py < top && c >= 0 && c < cols) return { zone: "col", c };
    if (px < left && r >= 0 && r < rows) return { zone: "row", r };
    if (r >= 0 && r < rows && c >= 0 && c < cols) return { zone: "cell", r, c, hasValue: data.values[r]?.[c] != null };
    return null;
  }

  function drawLoupe(r, c) {
    const size = (LOUPE_RADIUS * 2 + 1) * LOUPE_CELL_PX;
    const loupe = document.createElement("canvas");
    loupe.className = "dsChartMinimapLoupe";
    const dpr = window.devicePixelRatio || 1;
    loupe.width = size * dpr;
    loupe.height = size * dpr;
    loupe.style.width = `${size}px`;
    loupe.style.height = `${size}px`;
    const ctx = loupe.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const colors = readColors(host);
    for (let dr = -LOUPE_RADIUS; dr <= LOUPE_RADIUS; dr++) {
      for (let dc = -LOUPE_RADIUS; dc <= LOUPE_RADIUS; dc++) {
        const t = shade(r + dr, c + dc);
        if (t == null) continue;
        ctx.fillStyle = `rgba(${colors.cellRgb}, ${(0.06 + 0.5 * t).toFixed(3)})`;
        ctx.fillRect((dc + LOUPE_RADIUS) * LOUPE_CELL_PX, (dr + LOUPE_RADIUS) * LOUPE_CELL_PX, LOUPE_CELL_PX - 1, LOUPE_CELL_PX - 1);
      }
    }
    ctx.strokeStyle = colors.strong;
    ctx.lineWidth = 2;
    ctx.strokeRect(LOUPE_RADIUS * LOUPE_CELL_PX + 1, LOUPE_RADIUS * LOUPE_CELL_PX + 1, LOUPE_CELL_PX - 3, LOUPE_CELL_PX - 3);
    return loupe;
  }

  function line(className, text) {
    const el = document.createElement("div");
    el.className = className;
    el.textContent = text;
    return el;
  }

  function showTip(target, clientX, clientY) {
    tip.replaceChildren();
    if (target.zone === "row") {
      tip.append(line("dsChartMinimapTipTitle", String(data.rowLabels[target.r])), line("dsChartMinimapTipNote", data.rowAction));
    } else if (target.zone === "col") {
      tip.append(line("dsChartMinimapTipTitle", `Age ${data.colLabels[target.c]}`), line("dsChartMinimapTipNote", data.colAction));
    } else if (target.hasValue) {
      tip.append(line("dsChartMinimapTipTitle", `${data.rowLabels[target.r]} · Age ${data.colLabels[target.c]}`));
      if (layout.cell < LOUPE_BELOW_CELL_PX) tip.appendChild(drawLoupe(target.r, target.c));
      tip.append(line("dsChartMinimapTipValue", data.formatValue(data.values[target.r][target.c])));
    } else {
      hideTip();
      return;
    }
    tip.style.display = "block";
    const tw = tip.offsetWidth;
    const th = tip.offsetHeight;
    let x = clientX + 14;
    let y = clientY + 14;
    if (x + tw > window.innerWidth - 4) x = clientX - 14 - tw;
    if (y + th > window.innerHeight - 4) y = clientY - 14 - th;
    tip.style.left = `${Math.max(4, x)}px`;
    tip.style.top = `${Math.max(4, y)}px`;
  }

  function hideTip() {
    tip.style.display = "none";
  }

  function setHover(target) {
    const same = target?.zone === hover?.zone && target?.r === hover?.r && target?.c === hover?.c;
    hover = target;
    if (!same) draw();
  }

  canvas.addEventListener("pointermove", (event) => {
    if (dragBox) return;
    const target = hitTest(event.clientX, event.clientY);
    setHover(target);
    canvas.classList.toggle("isPickable", !!target && (target.zone !== "cell" || target.hasValue));
    if (target) showTip(target, event.clientX, event.clientY);
    else hideTip();
  });
  canvas.addEventListener("pointerleave", () => {
    if (dragBox) return;
    setHover(null);
    hideTip();
  });
  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const start = hitTest(event.clientX, event.clientY);
    if (!start) return;
    canvas.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startY = event.clientY;
    let dragging = false;
    const move = (moveEvent) => {
      if (start.zone !== "cell") return;
      if (!dragging && Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < DRAG_START_PX) return;
      dragging = true;
      hideTip();
      const { left, top, cell, rows, cols } = layout;
      const rect = canvas.getBoundingClientRect();
      const r = clamp(Math.floor((moveEvent.clientY - rect.top - top) / cell), 0, rows - 1);
      const c = clamp(Math.floor((moveEvent.clientX - rect.left - left) / cell), 0, cols - 1);
      dragBox = { r0: Math.min(start.r, r), r1: Math.max(start.r, r), c0: Math.min(start.c, c), c1: Math.max(start.c, c) };
      draw();
    };
    const end = () => {
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", end);
      canvas.removeEventListener("pointercancel", end);
      const box = dragBox;
      dragBox = null;
      draw();
      if (dragging && box) onZoomBox?.(box);
      else if (start.zone === "row") onPickOrigin?.(start.r);
      else if (start.zone === "col") onPickAge?.(start.c);
      else if (start.hasValue) onPickCell?.(start.r, start.c);
    };
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
  });

  window.addEventListener("arcrho:color-theme-changed", () => draw());

  return {
    render(next) {
      data = next;
      shade = next ? columnShade(next.values) : null;
      if (!next) hideTip();
      draw();
    },
    setCross(index) {
      if (cross === index) return;
      cross = index;
      draw();
    },
  };
}
