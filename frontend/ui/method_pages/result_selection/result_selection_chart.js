import {
  canHideChartLegendSeries,
  hiddenChartSeriesIdsAfterContextToggle,
  renderChartLegend,
} from "../../shared/components/chart_legend/chart_legend.js?v=20260724a";

const CHART_COLORS = [
  "#2b6df6",
  "#0f766e",
  "#b45309",
  "#7c3aed",
  "#be123c",
  "#0369a1",
  "#15803d",
  "#c2410c",
  "#4f46e5",
  "#0e7490",
  "#a21caf",
  "#475569",
];

const MIN_ZOOM_DRAG = 6;
// Keep the first and last points clear of the axes, and let a point sitting on a
// zoom-window edge paint whole instead of being sliced by the clip.
const SERIES_INSET = 7;
const SERIES_BLEED = 5;
const POINT_HIT_RADIUS = 7;
const CLICK_SLOP = 4;
// The Weight strip sits between the plot and the origin labels.
const STRIP_HEIGHT = 52;
const STRIP_GAP = 14;
const STRIP_DIVIDER_HIT = 4;
const STRIP_SNAPS = [0, 0.25, 0.5, 0.75, 1];
const STRIP_SNAP_RANGE = 0.04;
// Releasing the Selected Ultimate this close to a method's point uses that method.
const ULTIMATE_SNAP_PX = 6;
// Side panel width limits; its default width is in the stylesheet.
const SIDE_MIN_PX = 220;
const SIDE_MAX_PX = 560;
const SIDE_MAX_SHARE = 0.6;
const SIDE_KEY_STEP_PX = 16;
// Weight boxes step by whole units; a wheel burst commits once it rests.
const WEIGHT_STEP = 1;
const WHEEL_COMMIT_MS = 400;

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function weightNumber(value) {
  return Math.max(0, finiteNumber(value) ?? 0);
}

function roundWeight(value) {
  return Math.round(Math.max(0, value) * 10) / 10 || 0;
}

function sourceLabel(source, sourceIndex) {
  return String(source?.name || source?.datasetType || source?.dataset_type || `Source ${sourceIndex + 1}`).trim();
}

export const hiddenSeriesIdsAfterContextToggle = hiddenChartSeriesIdsAfterContextToggle;
export const canHideChartSeries = canHideChartLegendSeries;

export function buildResultSelectionChartSeries({
  sources = [],
  sourceIndexes = [],
  selectedUltimateValues = [],
  calculatedUltimateValues = [],
  overriddenRows = [],
  effectiveWeightAt = null,
  selectedUltimateLabel = "Selected Ultimate",
  rowCount = 0,
} = {}) {
  const count = Math.max(0, Number.parseInt(String(rowCount), 10) || 0);
  const rows = Array.from({ length: count }, (_, rowIndex) => rowIndex);
  const orderedIndexes = Array.isArray(sourceIndexes) && sourceIndexes.length
    ? sourceIndexes
    : sources.map((_, index) => index);
  const series = orderedIndexes
    .filter((sourceIndex) => Number.isInteger(sourceIndex) && sourceIndex >= 0 && sourceIndex < sources.length)
    .map((sourceIndex, orderIndex) => {
      const source = sources[sourceIndex] || {};
      const label = sourceLabel(source, sourceIndex);
      return {
        id: `source:${label.toLowerCase()}`,
        label,
        sourceIndex,
        color: CHART_COLORS[orderIndex % CHART_COLORS.length],
        values: rows.map((rowIndex) => finiteNumber(source?.values?.[rowIndex])),
        weights: rows.map((rowIndex) => weightNumber(source?.weights?.[rowIndex])),
        effective: rows.map((rowIndex) => (
          typeof effectiveWeightAt === "function" ? weightNumber(effectiveWeightAt(sourceIndex, rowIndex)) : 0
        )),
      };
    });

  series.push({
    id: "selected-ultimate",
    label: String(selectedUltimateLabel || "Selected Ultimate").trim(),
    color: "#111827",
    values: rows.map((rowIndex) => finiteNumber(selectedUltimateValues?.[rowIndex])),
    calculated: rows.map((rowIndex) => finiteNumber(calculatedUltimateValues?.[rowIndex])),
    overridden: rows.map((rowIndex) => !!overriddenRows?.[rowIndex]),
    emphasized: true,
  });
  return series;
}

// Dragging the divider between two adjacent methods in the Weight strip keeps
// their combined weight and splits it by the dragged share. The share snaps to
// quarters near them, and weights keep the one decimal the Method grid shows.
export function snapStripShare(share) {
  const clamped = Math.min(1, Math.max(0, Number(share) || 0));
  const snap = STRIP_SNAPS.find((value) => Math.abs(clamped - value) <= STRIP_SNAP_RANGE);
  return snap ?? clamped;
}

export function splitStripWeights({ lowerWeight = 0, upperWeight = 0, share = 0 } = {}) {
  const total = weightNumber(lowerWeight) + weightNumber(upperWeight);
  const lower = roundWeight(total * snapStripShare(share));
  return { lower, upper: roundWeight(total - lower) };
}

// Weight changes that leave only `keepSourceIndexes` counting in each row. A row
// where a kept method has no value is left alone.
export function useOnlyWeightChanges(series, rows, keepSourceIndexes, weight = 1) {
  const keep = new Set(keepSourceIndexes);
  const sourceSeries = series.filter((entry) => Number.isInteger(entry.sourceIndex));
  const changes = [];
  for (const rowIndex of rows) {
    const kept = sourceSeries.filter((entry) => keep.has(entry.sourceIndex));
    if (!kept.length || kept.some((entry) => entry.values[rowIndex] === null)) continue;
    for (const entry of sourceSeries) {
      if (entry.values[rowIndex] === null) continue;
      const next = keep.has(entry.sourceIndex) ? weightNumber(weight) : 0;
      if (next !== entry.weights[rowIndex]) changes.push({ sourceIndex: entry.sourceIndex, rowIndex, weight: next });
    }
  }
  return changes;
}

function niceStep(range, targetTickCount = 6) {
  const roughStep = Math.max(range, Number.EPSILON) / Math.max(1, targetTickCount);
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  if (normalized <= 1) return magnitude;
  if (normalized <= 2) return 2 * magnitude;
  if (normalized <= 2.5) return 2.5 * magnitude;
  if (normalized <= 5) return 5 * magnitude;
  return 10 * magnitude;
}

function chartRange(series) {
  const values = series.flatMap((entry) => entry.values.map(finiteNumber).filter((value) => value !== null));
  if (!values.length) return null;
  let dataMin = Math.min(...values);
  let dataMax = Math.max(...values);
  if (dataMin === dataMax) {
    const spread = Math.max(Math.abs(dataMin) * 0.05, 1);
    dataMin -= spread;
    dataMax += spread;
  }
  const padding = (dataMax - dataMin) * 0.06;
  const step = niceStep(dataMax - dataMin + padding * 2);
  const min = Math.floor((dataMin - padding) / step) * step;
  const max = Math.ceil((dataMax + padding) / step) * step;
  const ticks = [];
  for (let value = min; value <= max + step * 0.001; value += step) ticks.push(value);
  return { min, max, ticks };
}

function zoomedRange(valueMin, valueMax) {
  const step = niceStep(valueMax - valueMin);
  const ticks = [];
  for (let value = Math.ceil(valueMin / step) * step; value <= valueMax + step * 0.001; value += step) ticks.push(value);
  if (!ticks.length) ticks.push(valueMin, valueMax);
  return { min: valueMin, max: valueMax, ticks };
}

function numberFormatter(decimalPlaces) {
  const decimals = Math.max(0, Math.min(8, Number.parseInt(String(decimalPlaces ?? 1), 10) || 0));
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatWeight(value) {
  return weightNumber(value).toFixed(1);
}

// Scrolling over a weight box steps it like its stepper arrows: up adds,
// down subtracts, never below 0.
export function wheelStepWeight(input, event) {
  if (!input || input.disabled || !event?.deltaY) return false;
  event.preventDefault();
  if (event.deltaY < 0) input.stepUp();
  else input.stepDown();
  input.value = formatWeight(input.value);
  return true;
}

function formatShare(value) {
  return `${(weightNumber(value) * 100).toFixed(1)}%`;
}

function setCanvasSize(canvas) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
  const pixelWidth = Math.floor(width * pixelRatio);
  const pixelHeight = Math.floor(height * pixelRatio);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth;
    canvas.height = pixelHeight;
  }
  const context = canvas.getContext("2d");
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  return { context, width, height };
}

function element(tag, className = "", textContent = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textContent) node.textContent = textContent;
  return node;
}

export function createResultSelectionChart({
  canvas,
  legendList,
  legendCount,
  emptyState,
  tooltip,
  zoomBox,
  toolbar = {},
  selectionBar = {},
  inspector = {},
  sidePanel = {},
  menu = null,
  onEdit = () => {},
  previewRow = null,
} = {}) {
  if (!canvas) return null;

  // Colours resolve on the canvas, so page-owned chart tokens apply as well as
  // the theme's.
  const getChartColor = (propertyName, fallback) => (
    window.ArcRhoColorTheme?.getCssColor?.(propertyName, fallback, canvas) || fallback
  );
  let data = { originLabels: [], series: [], decimalPlaces: 1 };
  let points = [];
  let strip = { top: 0, bottom: 0, bars: [] };
  let animationFrame = null;
  let legendSignature = "";
  let plotArea = null;
  let zoomWindow = null;
  let drag = null;
  let mode = "weights";
  let showStrip = toolbar.stripToggle ? toolbar.stripToggle.checked : true;
  let activeRow = null;
  let selection = new Set();
  const hiddenSeriesIds = new Set();
  const resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => scheduleRender())
    : null;

  resizeObserver?.observe(canvas);

  const sourceSeries = () => data.series.filter((series) => Number.isInteger(series.sourceIndex));
  const ultimateSeries = () => data.series.find((series) => series.id === "selected-ultimate") || null;
  const rowCount = () => Math.max(data.originLabels.length, ...data.series.map((entry) => entry.values.length), 0);
  const originText = (rowIndex) => String(data.originLabels[rowIndex] ?? rowIndex + 1);
  const selectionKey = (sourceIndex, rowIndex) => `${sourceIndex}:${rowIndex}`;
  const seriesBySource = (sourceIndex) => sourceSeries().find((entry) => entry.sourceIndex === sourceIndex) || null;

  function effectiveAt(series, rowIndex) {
    if (drag?.type === "strip" && drag.rowIndex === rowIndex && drag.preview) {
      return drag.preview.effective.get(series.sourceIndex) ?? 0;
    }
    return series.effective?.[rowIndex] ?? 0;
  }

  function weightAt(series, rowIndex) {
    if (drag?.type === "strip" && drag.rowIndex === rowIndex && drag.weights.has(series.sourceIndex)) {
      return drag.weights.get(series.sourceIndex);
    }
    return series.weights?.[rowIndex] ?? 0;
  }

  function ultimateAt(rowIndex) {
    const ultimate = ultimateSeries();
    if (drag?.type === "ultimate" && drag.rowIndex === rowIndex && drag.value !== null) return drag.value;
    if (drag?.type === "strip" && drag.rowIndex === rowIndex && drag.preview) return drag.preview.ultimate;
    return ultimate?.values[rowIndex] ?? null;
  }

  function hideTooltip() {
    if (tooltip) tooltip.hidden = true;
  }

  function visibleSeries() {
    return data.series.filter((series) => !hiddenSeriesIds.has(series.id));
  }

  function updateLegendCount() {
    if (!legendCount) return;
    const visibleCount = visibleSeries().length;
    legendCount.textContent = `${visibleCount} of ${data.series.length}`;
  }

  function renderLegend() {
    if (!legendList) return;
    const signature = data.series.map((series) => `${series.id}\u0000${series.label}\u0000${series.color}`).join("\u0001");
    if (signature === legendSignature) {
      updateLegendCount();
      return;
    }
    legendSignature = signature;
    renderChartLegend({
      listElement: legendList,
      countElement: legendCount,
      series: data.series,
      hiddenIds: hiddenSeriesIds,
      onVisibilityChange: () => {
        hideTooltip();
        scheduleRender();
      },
    });
  }

  function emit(edit) {
    if (!edit.weights?.length && !edit.ultimates?.length) return;
    onEdit({ weights: [], ultimates: [], ...edit });
  }

  function draw() {
    animationFrame = null;
    const { context, width, height } = setCanvasSize(canvas);
    context.clearRect(0, 0, width, height);
    context.fillStyle = getChartColor("--ar-chart-background", "#ffffff");
    context.fillRect(0, 0, width, height);
    points = [];
    strip = { top: 0, bottom: 0, bars: [] };

    const series = visibleSeries();
    const labels = Array.isArray(data.originLabels) ? data.originLabels.map(String) : [];
    const count = rowCount();
    const lastRowIndex = Math.max(0, count - 1);
    let indexMin = 0;
    let indexMax = lastRowIndex;
    let range = drag?.type === "ultimate" ? drag.range : chartRange(series);
    if (zoomWindow && range) {
      const low = Math.min(Math.max(0, zoomWindow.indexMin), lastRowIndex);
      const high = Math.min(Math.max(0, zoomWindow.indexMax), lastRowIndex);
      if (high - low >= 1e-6) {
        indexMin = low;
        indexMax = high;
      }
      range = zoomedRange(zoomWindow.valueMin, zoomWindow.valueMax);
    }
    const hasChartSpace = width >= 240 && height >= 180;
    const isEmpty = !series.length || !range || count === 0 || !hasChartSpace;
    plotArea = null;
    if (emptyState) {
      emptyState.hidden = !isEmpty;
      emptyState.textContent = !hasChartSpace
        ? "Expand the window to view the chart."
        : !series.length
          ? "Select at least one column in the legend."
          : "Add source or selected output values to plot dataset vectors.";
    }
    canvas.classList.toggle("isEmpty", isEmpty);
    canvas.setAttribute(
      "aria-label",
      isEmpty
        ? "Result Selection dataset vector chart. No visible values are available."
        : `Result Selection dataset vector chart with ${count} origin periods and ${series.length} visible columns.${mode === "weights" ? " Click a point to include or exclude it." : ""}${zoomWindow ? " Zoomed in; double-click to restore the full view." : ""}`,
    );
    if (toolbar.fullViewButton) toolbar.fullViewButton.disabled = !zoomWindow;
    if (isEmpty) return;

    const firstLabelIndex = Math.max(0, Math.ceil(indexMin - 1e-9));
    const lastLabelIndex = Math.min(lastRowIndex, Math.floor(indexMax + 1e-9));
    const labelCount = Math.max(1, lastLabelIndex - firstLabelIndex + 1);
    const format = numberFormatter(data.decimalPlaces);
    const regularFont = '11px Arial, "Segoe UI", sans-serif';
    const boldFont = 'bold 11px Arial, "Segoe UI", sans-serif';
    context.font = regularFont;
    const widestTick = Math.max(...range.ticks.map((tick) => context.measureText(format.format(tick)).width));
    const rotateLabels = labelCount > 10 || labels.some((label) => label.length > 8);
    const stripSpace = showStrip ? STRIP_HEIGHT + STRIP_GAP : 0;
    const padding = {
      top: 14,
      right: 18 + SERIES_INSET,
      bottom: (rotateLabels ? 72 : 38) + stripSpace,
      left: Math.max(58, Math.ceil(widestTick) + 16),
    };
    const x0 = padding.left;
    const x1 = width - padding.right;
    const y0 = padding.top;
    const y1 = height - padding.bottom;
    const stripTop = y1 + STRIP_GAP;
    const labelTop = y1 + stripSpace + 10;
    const xStart = x0 + SERIES_INSET;
    const xEnd = x1 - SERIES_INSET;
    const xSpan = indexMax - indexMin;
    const xFor = (index) => xSpan <= 0 ? (xStart + xEnd) / 2 : xStart + ((index - indexMin) / xSpan) * (xEnd - xStart);
    const yFor = (value) => y1 - ((value - range.min) / (range.max - range.min)) * (y1 - y0);
    const band = xSpan <= 0 ? xEnd - xStart : (xEnd - xStart) / xSpan;
    plotArea = {
      x0, x1, y0, y1, xStart, xEnd, indexMin, indexMax, valueMin: range.min, valueMax: range.max, labelTop, band, xFor, yFor,
    };

    if (activeRow !== null && activeRow >= firstLabelIndex && activeRow <= lastLabelIndex) {
      const bandWidth = Math.max(12, Math.min(band * 0.9, 44));
      context.fillStyle = getChartColor("--rs-chart-active-origin", "rgba(43, 109, 246, 0.07)");
      context.fillRect(xFor(activeRow) - bandWidth / 2, y0, bandWidth, (showStrip ? stripTop + STRIP_HEIGHT : y1) - y0);
    }

    context.lineWidth = 1;
    context.textBaseline = "middle";
    context.textAlign = "right";
    for (const tick of range.ticks) {
      const y = yFor(tick);
      context.strokeStyle = getChartColor("--ar-chart-grid", "#e5eaf0");
      context.beginPath();
      context.moveTo(x0, y);
      context.lineTo(x1, y);
      context.stroke();
      context.fillStyle = getChartColor("--ar-chart-text-muted", "#5f6b7a");
      context.fillText(format.format(tick), x0 - 8, y);
    }

    context.strokeStyle = getChartColor("--ar-chart-axis", "#aeb8c5");
    context.beginPath();
    context.moveTo(x0, y0);
    context.lineTo(x0, y1);
    context.lineTo(x1, y1);
    context.stroke();

    const maxLabels = Math.max(2, Math.floor((x1 - x0) / (rotateLabels ? 44 : 70)));
    const labelEvery = Math.max(1, Math.ceil(labelCount / maxLabels));
    context.textBaseline = "top";
    for (let index = firstLabelIndex; index <= lastLabelIndex; index += 1) {
      const isActive = index === activeRow;
      if ((index - firstLabelIndex) % labelEvery !== 0 && index !== lastLabelIndex && !isActive) continue;
      const label = labels[index] || String(index + 1);
      const x = xFor(index);
      context.font = isActive ? boldFont : regularFont;
      context.fillStyle = isActive ? getChartColor("--rs-chart-active-text", "#1d4ed8") : getChartColor("--ar-chart-text", "#4b5563");
      context.save();
      if (rotateLabels) {
        context.translate(x - 2, labelTop);
        context.rotate(-Math.PI / 4);
        context.textAlign = "right";
        context.fillText(label, 0, 0);
      } else {
        context.textAlign = "center";
        context.fillText(label, x, labelTop);
      }
      context.restore();
    }
    context.font = regularFont;

    context.save();
    context.beginPath();
    context.rect(x0 - SERIES_BLEED, y0 - SERIES_BLEED, x1 - x0 + SERIES_BLEED * 2, y1 - y0 + SERIES_BLEED * 2);
    context.clip();
    const inPlot = (x, y) => x >= x0 - SERIES_BLEED && x <= x1 + SERIES_BLEED && y >= y0 - SERIES_BLEED && y <= y1 + SERIES_BLEED;
    const pointFill = getChartColor("--ar-chart-point-fill", "#ffffff");
    for (const entry of series) {
      if (entry.emphasized) continue;
      context.strokeStyle = entry.color;
      context.globalAlpha = 0.7;
      context.lineWidth = 1.6;
      context.lineJoin = "round";
      context.lineCap = "round";
      context.beginPath();
      let segmentOpen = false;
      for (let index = 0; index < count; index += 1) {
        const value = entry.values[index];
        if (value === null || value === undefined) {
          segmentOpen = false;
          continue;
        }
        if (segmentOpen) context.lineTo(xFor(index), yFor(value));
        else context.moveTo(xFor(index), yFor(value));
        segmentOpen = true;
      }
      context.stroke();
      context.globalAlpha = 1;

      for (let index = 0; index < count; index += 1) {
        const value = entry.values[index];
        if (value === null || value === undefined) continue;
        const x = xFor(index);
        const y = yFor(value);
        const share = effectiveAt(entry, index);
        const included = weightAt(entry, index) > 0;
        const radius = included ? 3 + share * 3.2 : 2.8;
        if (selection.has(selectionKey(entry.sourceIndex, index))) {
          context.strokeStyle = getChartColor("--rs-chart-selection", "#2b6df6");
          context.lineWidth = 1.5;
          context.setLineDash([2, 2]);
          context.beginPath();
          context.arc(x, y, radius + 3.5, 0, Math.PI * 2);
          context.stroke();
          context.setLineDash([]);
        }
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        if (included) {
          context.fillStyle = entry.color;
          context.fill();
          context.strokeStyle = pointFill;
          context.lineWidth = 1;
          context.stroke();
        } else {
          context.fillStyle = pointFill;
          context.fill();
          context.strokeStyle = entry.color;
          context.lineWidth = 1.4;
          context.stroke();
        }
        if (inPlot(x, y)) points.push({ kind: "source", x, y, radius, value, rowIndex: index, series: entry });
      }
    }

    const ultimate = series.find((entry) => entry.emphasized);
    if (ultimate) {
      const ultimateColor = getChartColor("--rs-chart-ultimate", "#111827");
      const overrideColor = getChartColor("--rs-chart-override", "#be123c");
      context.strokeStyle = ultimateColor;
      context.lineWidth = 2.4;
      context.lineJoin = "round";
      context.beginPath();
      let segmentOpen = false;
      for (let index = 0; index < count; index += 1) {
        const value = ultimateAt(index);
        if (value === null) {
          segmentOpen = false;
          continue;
        }
        if (segmentOpen) context.lineTo(xFor(index), yFor(value));
        else context.moveTo(xFor(index), yFor(value));
        segmentOpen = true;
      }
      context.stroke();
      for (let index = 0; index < count; index += 1) {
        const value = ultimateAt(index);
        if (value === null) continue;
        const x = xFor(index);
        const y = yFor(value);
        const overridden = drag?.type === "ultimate" && drag.rowIndex === index && drag.value !== null
          ? drag.snapSourceIndex === null
          : !!ultimate.overridden?.[index];
        context.beginPath();
        context.moveTo(x, y - 5);
        context.lineTo(x + 5, y);
        context.lineTo(x, y + 5);
        context.lineTo(x - 5, y);
        context.closePath();
        context.fillStyle = overridden ? overrideColor : ultimateColor;
        context.fill();
        context.strokeStyle = pointFill;
        context.lineWidth = 1.2;
        context.stroke();
        if (inPlot(x, y)) points.push({ kind: "ultimate", x, y, radius: 5, value, rowIndex: index, series: ultimate });
      }
      if (drag?.type === "ultimate" && drag.value !== null) {
        const y = yFor(drag.value);
        context.strokeStyle = drag.snapSourceIndex === null
          ? overrideColor
          : (seriesBySource(drag.snapSourceIndex)?.color || ultimateColor);
        context.lineWidth = 1;
        context.setLineDash([4, 3]);
        context.beginPath();
        context.moveTo(x0, y);
        context.lineTo(x1, y);
        context.stroke();
        context.setLineDash([]);
      }
    }
    context.restore();

    if (showStrip) drawStrip(context, { x0, x1, stripTop, firstLabelIndex, lastLabelIndex, xFor, band, regularFont, boldFont });
  }

  function drawStrip(context, { x0, x1, stripTop, firstLabelIndex, lastLabelIndex, xFor, band, regularFont, boldFont }) {
    const stripBottom = stripTop + STRIP_HEIGHT;
    strip = { top: stripTop, bottom: stripBottom, bars: [] };
    context.font = boldFont;
    context.textAlign = "right";
    context.textBaseline = "middle";
    context.fillStyle = getChartColor("--ar-chart-text-muted", "#5f6b7a");
    context.fillText("Weight", x0 - 8, stripTop + STRIP_HEIGHT / 2);
    context.font = regularFont;
    context.strokeStyle = getChartColor("--ar-chart-grid", "#e5eaf0");
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(x0, stripTop - STRIP_GAP / 2);
    context.lineTo(x1, stripTop - STRIP_GAP / 2);
    context.stroke();

    const barWidth = Math.max(4, Math.min(band * 0.56, 26));
    const all = sourceSeries();
    for (let rowIndex = firstLabelIndex; rowIndex <= lastLabelIndex; rowIndex += 1) {
      const x = xFor(rowIndex);
      const segments = [];
      let filled = 0;
      for (const entry of all) {
        const share = entry.values[rowIndex] === null ? 0 : effectiveAt(entry, rowIndex);
        if (share <= 0) continue;
        const bottom = stripBottom - filled * STRIP_HEIGHT;
        const top = stripBottom - (filled + share) * STRIP_HEIGHT;
        context.globalAlpha = hiddenSeriesIds.has(entry.id) ? 0.3 : 0.9;
        context.fillStyle = entry.color;
        context.fillRect(x - barWidth / 2, top, barWidth, bottom - top);
        context.globalAlpha = 1;
        segments.push({ series: entry, from: filled, to: filled + share, top, bottom });
        filled += share;
      }
      if (!segments.length) {
        context.strokeStyle = getChartColor("--ar-chart-axis", "#aeb8c5");
        context.setLineDash([3, 2]);
        context.strokeRect(x - barWidth / 2 + 0.5, stripTop + 0.5, barWidth - 1, STRIP_HEIGHT - 1);
        context.setLineDash([]);
      }
      context.strokeStyle = getChartColor("--ar-chart-background", "#ffffff");
      for (let index = 0; index < segments.length - 1; index += 1) {
        const y = Math.round(segments[index].top) + 0.5;
        context.beginPath();
        context.moveTo(x - barWidth / 2, y);
        context.lineTo(x + barWidth / 2, y);
        context.stroke();
      }
      if (drag?.type === "strip" && drag.rowIndex === rowIndex) {
        const y = segments.find((segment) => segment.series.sourceIndex === drag.lowerSourceIndex)?.top;
        if (y !== undefined) {
          context.strokeStyle = getChartColor("--ar-chart-text", "#4b5563");
          context.lineWidth = 2;
          context.beginPath();
          context.moveTo(x - barWidth / 2 - 3, y);
          context.lineTo(x + barWidth / 2 + 3, y);
          context.stroke();
          context.lineWidth = 1;
        }
      }
      strip.bars.push({ rowIndex, x, width: barWidth, segments });
    }
  }

  function scheduleRender() {
    if (animationFrame !== null) return;
    animationFrame = window.requestAnimationFrame(draw);
  }

  function canvasPoint(event) {
    const bounds = canvas.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function insidePlot(point) {
    return !!plotArea && point.x >= plotArea.x0 && point.x <= plotArea.x1
      && point.y >= plotArea.y0 && point.y <= plotArea.y1;
  }

  function hitPoint(point) {
    let nearest = null;
    let nearestScore = Infinity;
    for (const candidate of points) {
      const distance = Math.hypot(candidate.x - point.x, candidate.y - point.y);
      if (distance > Math.max(POINT_HIT_RADIUS, candidate.radius + 3)) continue;
      // The Selected Ultimate wins a tie, since it is drawn on top.
      const score = distance - (candidate.kind === "ultimate" ? 1.5 : 0);
      if (score < nearestScore) {
        nearest = candidate;
        nearestScore = score;
      }
    }
    return nearest;
  }

  function hitStrip(point) {
    if (!showStrip || !plotArea || point.y < strip.top - STRIP_DIVIDER_HIT || point.y > strip.bottom + STRIP_DIVIDER_HIT) return null;
    const reach = Math.max(6, plotArea.band / 2);
    const bar = strip.bars.find((candidate) => Math.abs(point.x - candidate.x) <= reach);
    if (!bar) return null;
    if (Math.abs(point.x - bar.x) <= bar.width / 2 + STRIP_DIVIDER_HIT) {
      for (let index = 0; index < bar.segments.length - 1; index += 1) {
        if (Math.abs(point.y - bar.segments[index].top) <= STRIP_DIVIDER_HIT) {
          return { kind: "divider", bar, lower: bar.segments[index], upper: bar.segments[index + 1] };
        }
      }
    }
    return { kind: "column", bar };
  }

  function rowAtLabel(point) {
    if (!plotArea || point.y < plotArea.labelTop - 4) return null;
    const span = plotArea.indexMax - plotArea.indexMin;
    const index = Math.round(plotArea.indexMin + ((point.x - plotArea.xStart) / Math.max(1, plotArea.xEnd - plotArea.xStart)) * span);
    return index >= 0 && index < rowCount() ? index : null;
  }

  function showTooltipAt(point, title, lines, hint = "") {
    if (!tooltip) return;
    const children = [element("strong", "", title)];
    for (const line of lines) children.push(element("span", "", line));
    if (hint) children.push(element("span", "rsChartTooltipHint", hint));
    tooltip.replaceChildren(...children);
    tooltip.hidden = false;
    const left = canvas.offsetLeft + point.x + 12;
    const maxLeft = canvas.offsetLeft + canvas.clientWidth - tooltip.offsetWidth - 4;
    tooltip.style.left = `${Math.max(canvas.offsetLeft + 4, Math.min(left, maxLeft))}px`;
    tooltip.style.top = `${Math.max(4, canvas.offsetTop + point.y - tooltip.offsetHeight - 10)}px`;
  }

  function showPointTooltip(point, hit) {
    const format = numberFormatter(data.decimalPlaces);
    if (hit.kind === "ultimate") {
      const overridden = !!hit.series.overridden?.[hit.rowIndex];
      const lines = [`${originText(hit.rowIndex)}: ${format.format(hit.value)}`];
      if (overridden) lines.push(`Calculated: ${format.format(hit.series.calculated?.[hit.rowIndex] ?? 0)}`);
      const hint = mode === "weights"
        ? `Drag to set a custom ultimate${overridden ? "; double-click to revert" : ""}`
        : "";
      showTooltipAt(point, hit.series.label, lines, hint);
      return;
    }
    const weight = weightAt(hit.series, hit.rowIndex);
    showTooltipAt(
      point,
      hit.series.label,
      [
        `${originText(hit.rowIndex)}: ${format.format(hit.value)}`,
        `Weight ${formatWeight(weight)} (${formatShare(effectiveAt(hit.series, hit.rowIndex))})`,
      ],
      mode === "weights" ? `Click to ${weight > 0 ? "exclude" : "include"}; right-click for more` : "",
    );
  }

  function showStripTooltip(point, hit) {
    const rowIndex = hit.bar.rowIndex;
    const lines = [...hit.bar.segments].reverse()
      .map((segment) => `${formatShare(segment.to - segment.from)} · ${segment.series.label}`);
    showTooltipAt(
      point,
      `${originText(rowIndex)} weights`,
      lines.length ? lines : ["No method counts toward this origin."],
      hit.kind === "divider" ? "Drag to shift weight" : "Click to inspect",
    );
  }

  function setActiveRow(rowIndex) {
    const count = rowCount();
    if (!count) {
      activeRow = null;
    } else {
      activeRow = Math.max(0, Math.min(count - 1, rowIndex));
    }
    renderInspector();
    scheduleRender();
  }

  // ---------- Origin inspector ----------
  function renderInspector() {
    if (!inspector.body) return;
    const count = rowCount();
    const rowIndex = activeRow;
    const format = numberFormatter(data.decimalPlaces);
    if (inspector.title) inspector.title.textContent = rowIndex === null ? "Origin" : `Origin ${originText(rowIndex)}`;
    if (inspector.prevButton) inspector.prevButton.disabled = rowIndex === null || rowIndex <= 0;
    if (inspector.nextButton) inspector.nextButton.disabled = rowIndex === null || rowIndex >= count - 1;
    const rows = [];
    if (rowIndex !== null) {
      for (const entry of sourceSeries()) {
        const value = entry.values[rowIndex];
        const weight = weightAt(entry, rowIndex);
        const row = element("tr");
        row.classList.toggle("isExcluded", !(weight > 0) || value === null);
        const name = element("td", "rsChartInspectorName");
        const swatch = element("span", "rsChartInspectorSwatch");
        swatch.style.setProperty("--rs-chart-series", entry.color);
        name.append(swatch, entry.label);
        name.title = entry.label;
        const valueCell = element("td", "rsChartInspectorNumber", value === null ? "" : format.format(value));
        const weightCell = element("td", "rsChartInspectorNumber");
        const input = element("input", "rsChartWeightInput");
        input.type = "number";
        input.min = "0";
        input.step = String(WEIGHT_STEP);
        input.value = formatWeight(weight);
        input.disabled = value === null;
        input.classList.toggle("isZero", !(weight > 0));
        input.setAttribute("aria-label", `${entry.label} weight for ${originText(rowIndex)}`);
        input.dataset.sourceIndex = String(entry.sourceIndex);
        let wheelTimer = null;
        const commit = () => {
          window.clearTimeout(wheelTimer);
          wheelTimer = null;
          const next = weightNumber(input.value);
          if (next === weightNumber(entry.weights[rowIndex])) {
            input.value = formatWeight(next);
            return;
          }
          emit({
            label: `${entry.label} ${originText(rowIndex)} weight set to ${formatWeight(next)}.`,
            weights: [{ sourceIndex: entry.sourceIndex, rowIndex, weight: next }],
          });
        };
        input.addEventListener("change", commit);
        // A burst of wheel steps lands as one edit once the wheel rests.
        input.addEventListener("wheel", (event) => {
          if (!wheelStepWeight(input, event)) return;
          window.clearTimeout(wheelTimer);
          wheelTimer = window.setTimeout(commit, WHEEL_COMMIT_MS);
        }, { passive: false });
        input.addEventListener("pointerleave", () => { if (wheelTimer !== null) commit(); });
        weightCell.appendChild(input);
        const shareCell = element("td", "rsChartInspectorNumber", value === null ? "" : formatShare(effectiveAt(entry, rowIndex)));
        row.append(name, valueCell, weightCell, shareCell);
        rows.push(row);
      }
    }
    inspector.body.replaceChildren(...rows);
    const ultimate = ultimateSeries();
    const overridden = rowIndex !== null && !!ultimate?.overridden?.[rowIndex];
    const value = rowIndex === null ? null : ultimateAt(rowIndex);
    if (inspector.ultimate) {
      inspector.ultimate.textContent = value === null ? "" : format.format(value);
      inspector.ultimate.classList.toggle("isOverridden", overridden);
    }
    if (inspector.calculated) {
      const calculated = rowIndex === null ? null : ultimate?.calculated?.[rowIndex];
      inspector.calculated.textContent = overridden && calculated !== null && calculated !== undefined
        ? `Calculated ${format.format(calculated)}`
        : "";
    }
    if (inspector.revertButton) inspector.revertButton.hidden = !overridden;
  }

  // ---------- Selection bar ----------
  function hideSelectionBar() {
    if (selectionBar.root) selectionBar.root.hidden = true;
  }

  function clearSelection() {
    if (!selection.size) return;
    selection = new Set();
    hideSelectionBar();
    scheduleRender();
  }

  function showSelectionBar(anchor) {
    const root = selectionBar.root;
    if (!root) return;
    if (!selection.size) {
      root.hidden = true;
      return;
    }
    if (selectionBar.count) {
      selectionBar.count.textContent = `${selection.size} ${selection.size === 1 ? "point" : "points"}`;
    }
    root.hidden = false;
    const host = root.offsetParent || canvas.parentElement;
    const maxLeft = (host?.clientWidth || canvas.clientWidth) - root.offsetWidth - 8;
    const maxTop = (host?.clientHeight || canvas.clientHeight) - root.offsetHeight - 8;
    root.style.left = `${Math.max(8, Math.min(canvas.offsetLeft + anchor.x - root.offsetWidth / 2, maxLeft))}px`;
    root.style.top = `${Math.max(8, Math.min(canvas.offsetTop + anchor.y + 10, maxTop))}px`;
  }

  function selectedPairs() {
    return [...selection].map((key) => key.split(":").map(Number));
  }

  function applySelection(action) {
    const pairs = selectedPairs();
    if (!pairs.length) return;
    const weight = weightNumber(selectionBar.weightInput?.value ?? 1);
    const count = pairs.length;
    const noun = count === 1 ? "point" : "points";
    let weights = [];
    let label = "";
    if (action === "only") {
      const byRow = new Map();
      for (const [sourceIndex, rowIndex] of pairs) {
        if (!byRow.has(rowIndex)) byRow.set(rowIndex, []);
        byRow.get(rowIndex).push(sourceIndex);
      }
      for (const [rowIndex, keep] of byRow) {
        weights.push(...useOnlyWeightChanges(data.series, [rowIndex], keep, weight));
      }
      label = `Used only ${count} selected ${noun} at weight ${formatWeight(weight)}.`;
    } else {
      const next = action === "exclude" ? 0 : weight;
      weights = pairs
        .filter(([sourceIndex, rowIndex]) => weightNumber(seriesBySource(sourceIndex)?.weights[rowIndex]) !== next)
        .map(([sourceIndex, rowIndex]) => ({ sourceIndex, rowIndex, weight: next }));
      label = action === "exclude"
        ? `Excluded ${count} ${noun}.`
        : `Set ${count} ${noun} to weight ${formatWeight(next)}.`;
    }
    clearSelection();
    emit({ label, weights });
  }

  // ---------- Point menu ----------
  function closeMenu() {
    if (!menu) return;
    menu.classList.remove("open");
    menu.setAttribute("aria-hidden", "true");
  }

  function openMenu(event, hit) {
    if (!menu) return;
    const items = [];
    const rowIndex = hit.rowIndex;
    const origin = originText(rowIndex);
    if (hit.kind === "ultimate") {
      items.push({ title: `${hit.series.label} · ${origin}` });
      items.push({ label: "Edit In Origin Panel", run: () => setActiveRow(rowIndex) });
      items.push({
        label: "Revert To Calculated",
        disabled: !hit.series.overridden?.[rowIndex],
        run: () => emit({ label: `Reverted the ${origin} custom ultimate.`, ultimates: [{ rowIndex, value: null }] }),
      });
    } else {
      const entry = hit.series;
      const included = weightAt(entry, rowIndex) > 0;
      const lastRow = rowCount() - 1;
      const laterRows = Array.from({ length: lastRow - rowIndex + 1 }, (_, offset) => rowIndex + offset);
      items.push({ title: `${entry.label} · ${origin}` });
      items.push({ label: included ? "Exclude This Point" : "Include This Point", run: () => togglePoint(hit) });
      items.push({
        label: `Use Only This Method For ${origin}`,
        run: () => emit({
          label: `${origin} uses only ${entry.label}.`,
          weights: useOnlyWeightChanges(data.series, [rowIndex], [entry.sourceIndex]),
          ultimates: ultimateRevertsFor([rowIndex]),
        }),
      });
      items.push({
        label: `Use Only This Method From ${origin} On`,
        disabled: rowIndex >= lastRow,
        run: () => emit({
          label: `${origin} onward uses only ${entry.label}.`,
          weights: useOnlyWeightChanges(data.series, laterRows, [entry.sourceIndex]),
          ultimates: ultimateRevertsFor(laterRows),
        }),
      });
      items.push({ separator: true });
      items.push({
        label: "Type Exact Weights",
        run: () => {
          setActiveRow(rowIndex);
          inspector.body?.querySelector?.(`input[data-source-index="${entry.sourceIndex}"]`)?.focus();
        },
      });
    }
    const children = items.map((item) => {
      if (item.title) return element("div", "rsChartMenuTitle", item.title);
      if (item.separator) return element("div", "rsChartMenuSeparator");
      const button = element("button", "", item.label);
      button.type = "button";
      button.setAttribute("role", "menuitem");
      button.disabled = !!item.disabled;
      button.addEventListener("click", () => {
        closeMenu();
        item.run();
      });
      return button;
    });
    menu.replaceChildren(...children);
    menu.classList.add("open");
    menu.setAttribute("aria-hidden", "false");
    const left = Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8);
    const top = Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8);
    menu.style.left = `${Math.max(8, left)}px`;
    menu.style.top = `${Math.max(8, top)}px`;
  }

  // A row given a single method no longer needs its custom ultimate.
  function ultimateRevertsFor(rows) {
    const ultimate = ultimateSeries();
    return rows.filter((rowIndex) => ultimate?.overridden?.[rowIndex]).map((rowIndex) => ({ rowIndex, value: null }));
  }

  function togglePoint(hit) {
    const weight = weightAt(hit.series, hit.rowIndex) > 0 ? 0 : 1;
    emit({
      label: `${weight > 0 ? "Included" : "Excluded"} ${hit.series.label} for ${originText(hit.rowIndex)}.`,
      weights: [{ sourceIndex: hit.series.sourceIndex, rowIndex: hit.rowIndex, weight }],
    });
  }

  // ---------- Pointer handling ----------
  function drawBox(start, end) {
    if (!zoomBox) return;
    zoomBox.classList.toggle("isSelecting", drag?.type === "select");
    zoomBox.style.left = `${canvas.offsetLeft + Math.min(start.x, end.x)}px`;
    zoomBox.style.top = `${canvas.offsetTop + Math.min(start.y, end.y)}px`;
    zoomBox.style.width = `${Math.abs(end.x - start.x)}px`;
    zoomBox.style.height = `${Math.abs(end.y - start.y)}px`;
    zoomBox.hidden = false;
  }

  function clampToPlot(point) {
    return {
      x: Math.min(Math.max(point.x, plotArea.x0), plotArea.x1),
      y: Math.min(Math.max(point.y, plotArea.y0), plotArea.y1),
    };
  }

  function releaseDrag(event) {
    if (drag && canvas.hasPointerCapture?.(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    if (zoomBox) zoomBox.hidden = true;
  }

  function startStripDrag(hit) {
    const rowIndex = hit.bar.rowIndex;
    const lower = hit.lower.series;
    const upper = hit.upper.series;
    drag = {
      type: "strip",
      rowIndex,
      lowerSourceIndex: lower.sourceIndex,
      upperSourceIndex: upper.sourceIndex,
      from: hit.lower.from,
      to: hit.upper.to,
      lowerWeight: weightNumber(lower.weights[rowIndex]),
      upperWeight: weightNumber(upper.weights[rowIndex]),
      weights: new Map(),
      preview: null,
    };
  }

  function updateStripDrag(point) {
    const fraction = (strip.bottom - point.y) / STRIP_HEIGHT;
    const clamped = Math.min(Math.max(fraction, drag.from), drag.to);
    const share = (clamped - drag.from) / Math.max(1e-9, drag.to - drag.from);
    const split = splitStripWeights({ lowerWeight: drag.lowerWeight, upperWeight: drag.upperWeight, share });
    drag.weights = new Map([[drag.lowerSourceIndex, split.lower], [drag.upperSourceIndex, split.upper]]);
    drag.preview = typeof previewRow === "function" ? previewRow(drag.rowIndex, drag.weights) : null;
    const lower = seriesBySource(drag.lowerSourceIndex);
    const upper = seriesBySource(drag.upperSourceIndex);
    const bar = strip.bars.find((candidate) => candidate.rowIndex === drag.rowIndex);
    if (bar && lower && upper) {
      showTooltipAt(
        { x: bar.x, y: strip.top },
        originText(drag.rowIndex),
        [
          `${formatShare(effectiveAt(upper, drag.rowIndex))} (${formatWeight(split.upper)}) · ${upper.label}`,
          `${formatShare(effectiveAt(lower, drag.rowIndex))} (${formatWeight(split.lower)}) · ${lower.label}`,
        ],
      );
    }
    renderInspector();
    scheduleRender();
  }

  function updateUltimateDrag(point) {
    if (!drag.moved && Math.abs(point.y - drag.start.y) < CLICK_SLOP) return;
    drag.moved = true;
    const y = Math.min(Math.max(point.y, plotArea.y0), plotArea.y1);
    const snap = sourceSeries().find((entry) => (
      !hiddenSeriesIds.has(entry.id)
      && entry.values[drag.rowIndex] !== null
      && Math.abs(plotArea.yFor(entry.values[drag.rowIndex]) - y) <= ULTIMATE_SNAP_PX
    ));
    drag.snapSourceIndex = snap ? snap.sourceIndex : null;
    drag.value = snap
      ? snap.values[drag.rowIndex]
      : plotArea.valueMax - ((y - plotArea.y0) / (plotArea.y1 - plotArea.y0)) * (plotArea.valueMax - plotArea.valueMin);
    const format = numberFormatter(data.decimalPlaces);
    const ultimate = ultimateSeries();
    showTooltipAt(
      { x: plotArea.xFor(drag.rowIndex), y },
      `${ultimate?.label || "Selected Ultimate"} · ${originText(drag.rowIndex)}`,
      [`New: ${format.format(drag.value)}`, `Calculated: ${format.format(ultimate?.calculated?.[drag.rowIndex] ?? 0)}`],
      snap ? `Release to use only ${snap.label}` : "Release to set a custom ultimate",
    );
    scheduleRender();
  }

  function onPointerDown(event) {
    if (event.button !== 0 || !plotArea) return;
    closeMenu();
    hideTooltip();
    const point = canvasPoint(event);
    if (mode === "zoom") {
      if (!insidePlot(point)) return;
      drag = { type: "zoom", pointerId: event.pointerId, start: point, end: point };
    } else {
      const hit = hitPoint(point);
      const stripHit = hit ? null : hitStrip(point);
      const labelRow = hit || stripHit ? null : rowAtLabel(point);
      if (hit?.kind === "ultimate") {
        drag = {
          type: "ultimate",
          pointerId: event.pointerId,
          rowIndex: hit.rowIndex,
          start: point,
          moved: false,
          value: null,
          snapSourceIndex: null,
          // The value axis holds still while the point is dragged past its edge.
          range: chartRange(visibleSeries()),
        };
      } else if (hit) {
        drag = { type: "point", pointerId: event.pointerId, start: point, hit };
      } else if (stripHit?.kind === "divider") {
        startStripDrag(stripHit);
        drag.pointerId = event.pointerId;
        setActiveRow(stripHit.bar.rowIndex);
      } else if (stripHit) {
        setActiveRow(stripHit.bar.rowIndex);
        return;
      } else if (labelRow !== null) {
        setActiveRow(labelRow);
        return;
      } else if (insidePlot(point)) {
        const additive = event.ctrlKey || event.metaKey;
        if (!additive) clearSelection();
        drag = { type: "select", pointerId: event.pointerId, start: point, end: point, base: new Set(selection) };
      } else {
        return;
      }
    }
    canvas.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function onPointerMove(event) {
    const point = canvasPoint(event);
    if (!drag || event.pointerId !== drag.pointerId) {
      updateHover(point);
      return;
    }
    if (!plotArea) return;
    if (drag.type === "zoom" || drag.type === "select") {
      drag.end = clampToPlot(point);
      drawBox(drag.start, drag.end);
      if (drag.type === "select") {
        const left = Math.min(drag.start.x, drag.end.x);
        const right = Math.max(drag.start.x, drag.end.x);
        const top = Math.min(drag.start.y, drag.end.y);
        const bottom = Math.max(drag.start.y, drag.end.y);
        selection = new Set(drag.base);
        for (const candidate of points) {
          if (candidate.kind !== "source") continue;
          if (candidate.x >= left && candidate.x <= right && candidate.y >= top && candidate.y <= bottom) {
            selection.add(selectionKey(candidate.series.sourceIndex, candidate.rowIndex));
          }
        }
        scheduleRender();
      }
    } else if (drag.type === "strip") {
      updateStripDrag(point);
    } else if (drag.type === "ultimate") {
      updateUltimateDrag(point);
    }
  }

  function updateHover(point) {
    const hit = hitPoint(point);
    if (hit) {
      showPointTooltip(point, hit);
      // Edit Weights uses the stylesheet's pencil except over a drag handle.
      canvas.style.cursor = mode === "weights" && hit.kind === "ultimate" ? "ns-resize" : "";
      return;
    }
    const stripHit = mode === "weights" ? hitStrip(point) : null;
    if (stripHit) {
      showStripTooltip(point, stripHit);
      canvas.style.cursor = stripHit.kind === "divider" ? "ns-resize" : "";
      return;
    }
    hideTooltip();
    canvas.style.cursor = "";
  }

  function onPointerUp(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const current = drag;
    const point = canvasPoint(event);
    releaseDrag(event);
    if (current.type === "zoom") {
      drag = null;
      applyZoom(current);
      return;
    }
    if (current.type === "select") {
      drag = null;
      const moved = Math.abs(current.end.x - current.start.x) >= CLICK_SLOP || Math.abs(current.end.y - current.start.y) >= CLICK_SLOP;
      if (!moved) {
        selection = current.base;
        scheduleRender();
        return;
      }
      showSelectionBar({
        x: (current.start.x + current.end.x) / 2,
        y: Math.max(current.start.y, current.end.y),
      });
      return;
    }
    if (current.type === "point") {
      drag = null;
      if (Math.hypot(point.x - current.start.x, point.y - current.start.y) >= CLICK_SLOP) return;
      const { hit } = current;
      activeRow = hit.rowIndex;
      if (event.ctrlKey || event.metaKey) {
        const key = selectionKey(hit.series.sourceIndex, hit.rowIndex);
        if (selection.has(key)) selection.delete(key);
        else selection.add(key);
        showSelectionBar({ x: hit.x, y: hit.y });
        renderInspector();
        scheduleRender();
        return;
      }
      togglePoint(hit);
      return;
    }
    if (current.type === "strip") {
      hideTooltip();
      const changes = [...current.weights]
        .filter(([sourceIndex, weight]) => weight !== weightNumber(seriesBySource(sourceIndex)?.weights[current.rowIndex]))
        .map(([sourceIndex, weight]) => ({ sourceIndex, rowIndex: current.rowIndex, weight }));
      const lower = seriesBySource(current.lowerSourceIndex);
      const upper = seriesBySource(current.upperSourceIndex);
      // The drag stays drawn until the page renders the committed weights.
      drag = null;
      if (changes.length) {
        emit({ label: `Shifted ${originText(current.rowIndex)} weight between ${lower?.label} and ${upper?.label}.`, weights: changes });
      } else {
        renderInspector();
        scheduleRender();
      }
      return;
    }
    if (current.type === "ultimate") {
      hideTooltip();
      drag = null;
      const rowIndex = current.rowIndex;
      if (!current.moved || current.value === null) {
        setActiveRow(rowIndex);
        return;
      }
      activeRow = rowIndex;
      if (current.snapSourceIndex !== null) {
        const entry = seriesBySource(current.snapSourceIndex);
        emit({
          label: `${originText(rowIndex)} uses only ${entry?.label}.`,
          weights: useOnlyWeightChanges(data.series, [rowIndex], [current.snapSourceIndex]),
          ultimates: ultimateRevertsFor([rowIndex]),
        });
        scheduleRender();
        return;
      }
      const format = numberFormatter(data.decimalPlaces);
      emit({
        label: `Set a custom ${originText(rowIndex)} ultimate of ${format.format(current.value)}.`,
        ultimates: [{ rowIndex, value: current.value }],
      });
    }
  }

  function onPointerCancel(event) {
    releaseDrag(event);
    if (drag?.type === "select") selection = drag.base;
    drag = null;
    hideTooltip();
    renderInspector();
    scheduleRender();
  }

  function applyZoom(current) {
    const left = Math.min(current.start.x, current.end.x);
    const right = Math.max(current.start.x, current.end.x);
    const top = Math.min(current.start.y, current.end.y);
    const bottom = Math.max(current.start.y, current.end.y);
    const area = plotArea;
    if (!area || right - left < MIN_ZOOM_DRAG || bottom - top < MIN_ZOOM_DRAG) return;
    const indexSpan = area.indexMax - area.indexMin;
    const indexAt = (x) => area.indexMin + ((x - area.xStart) / (area.xEnd - area.xStart)) * indexSpan;
    const valueAt = (y) => area.valueMax - ((y - area.y0) / (area.y1 - area.y0)) * (area.valueMax - area.valueMin);
    zoomWindow = {
      indexMin: indexAt(left),
      indexMax: indexAt(right),
      valueMin: valueAt(bottom),
      valueMax: valueAt(top),
    };
    scheduleRender();
  }

  function resetZoom() {
    if (!zoomWindow) return;
    zoomWindow = null;
    hideTooltip();
    scheduleRender();
  }

  function onDoubleClick(event) {
    const hit = mode === "weights" ? hitPoint(canvasPoint(event)) : null;
    if (hit?.kind === "ultimate" && hit.series.overridden?.[hit.rowIndex]) {
      emit({ label: `Reverted the ${originText(hit.rowIndex)} custom ultimate.`, ultimates: [{ rowIndex: hit.rowIndex, value: null }] });
      return;
    }
    if (!hit) resetZoom();
  }

  function onContextMenu(event) {
    if (mode !== "weights") return;
    const hit = hitPoint(canvasPoint(event));
    if (!hit) return;
    event.preventDefault();
    hideTooltip();
    openMenu(event, hit);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      if (activeRow === null) return;
      event.preventDefault();
      setActiveRow(activeRow + (event.key === "ArrowLeft" ? -1 : 1));
    } else if (event.key === "Escape") {
      clearSelection();
      closeMenu();
    }
  }

  function onDocumentPointerDown(event) {
    if (menu?.classList.contains("open") && !menu.contains(event.target)) closeMenu();
  }

  function setMode(next) {
    mode = next === "zoom" ? "zoom" : "weights";
    for (const [button, value] of [[toolbar.weightsModeButton, "weights"], [toolbar.zoomModeButton, "zoom"]]) {
      if (!button) continue;
      button.classList.toggle("isActive", mode === value);
      button.setAttribute("aria-pressed", String(mode === value));
    }
    canvas.dataset.chartMode = mode;
    clearSelection();
    closeMenu();
    hideTooltip();
    scheduleRender();
  }

  // ---------- Side panel width ----------
  // The width lives in a CSS custom property on the chart body, so the
  // stylesheet keeps the default; it is a view setting and is not saved.
  function sideWidth() {
    return sidePanel.panel?.getBoundingClientRect().width || 0;
  }

  function setSideWidth(width) {
    const body = sidePanel.body;
    if (!body) return;
    const room = body.clientWidth;
    const max = Math.max(SIDE_MIN_PX, Math.min(SIDE_MAX_PX, Math.floor(room * SIDE_MAX_SHARE)));
    const next = Math.round(Math.min(Math.max(width, SIDE_MIN_PX), max));
    body.style.setProperty("--rs-chart-side-width", `${next}px`);
    sidePanel.resizer?.setAttribute("aria-valuenow", String(next));
  }

  function onResizerPointerDown(event) {
    const handle = sidePanel.resizer;
    if (event.button !== 0 || !handle) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = sideWidth();
    sidePanel.body?.classList.add("isResizingSide");
    hideTooltip();
    // Dragging left widens the panel, which sits to the right of the handle.
    const move = (moveEvent) => setSideWidth(startWidth - (moveEvent.clientX - startX));
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      handle.removeEventListener("lostpointercapture", end);
      sidePanel.body?.classList.remove("isResizingSide");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    handle.addEventListener("lostpointercapture", end);
  }

  function onResizerKeyDown(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setSideWidth(sideWidth() + (event.key === "ArrowLeft" ? SIDE_KEY_STEP_PX : -SIDE_KEY_STEP_PX));
  }

  function resetSideWidth() {
    sidePanel.body?.style.removeProperty("--rs-chart-side-width");
    sidePanel.resizer?.setAttribute("aria-valuenow", String(Math.round(sideWidth())));
  }

  const listeners = [
    [canvas, "pointerdown", onPointerDown],
    [canvas, "pointermove", onPointerMove],
    [canvas, "pointerup", onPointerUp],
    [canvas, "pointercancel", onPointerCancel],
    [canvas, "dblclick", onDoubleClick],
    [canvas, "contextmenu", onContextMenu],
    [canvas, "keydown", onKeyDown],
    [canvas, "pointerleave", () => { if (!drag) hideTooltip(); }],
    [document, "pointerdown", onDocumentPointerDown, true],
    [window, "arcrho:color-theme-changed", scheduleRender],
    [toolbar.weightsModeButton, "click", () => setMode("weights")],
    [toolbar.zoomModeButton, "click", () => setMode("zoom")],
    [toolbar.stripToggle, "change", () => { showStrip = !!toolbar.stripToggle.checked; hideTooltip(); scheduleRender(); }],
    [toolbar.fullViewButton, "click", resetZoom],
    [sidePanel.resizer, "pointerdown", onResizerPointerDown],
    [sidePanel.resizer, "keydown", onResizerKeyDown],
    [sidePanel.resizer, "dblclick", resetSideWidth],
    [selectionBar.weightInput, "wheel", (event) => wheelStepWeight(selectionBar.weightInput, event), { passive: false }],
    [selectionBar.setButton, "click", () => applySelection("set")],
    [selectionBar.onlyButton, "click", () => applySelection("only")],
    [selectionBar.excludeButton, "click", () => applySelection("exclude")],
    [selectionBar.closeButton, "click", clearSelection],
    [inspector.prevButton, "click", () => activeRow !== null && setActiveRow(activeRow - 1)],
    [inspector.nextButton, "click", () => activeRow !== null && setActiveRow(activeRow + 1)],
    [inspector.revertButton, "click", () => {
      if (activeRow === null) return;
      emit({ label: `Reverted the ${originText(activeRow)} custom ultimate.`, ultimates: [{ rowIndex: activeRow, value: null }] });
    }],
  ].filter(([target]) => !!target);
  for (const [target, type, handler, capture] of listeners) target.addEventListener(type, handler, capture || false);
  if (!canvas.hasAttribute("tabindex")) canvas.tabIndex = 0;
  setMode(mode);

  return {
    render(nextData = {}) {
      data = {
        originLabels: Array.isArray(nextData.originLabels) ? nextData.originLabels : [],
        series: Array.isArray(nextData.series) ? nextData.series : [],
        decimalPlaces: nextData.decimalPlaces,
      };
      const count = rowCount();
      if (activeRow === null || activeRow >= count) activeRow = count ? count - 1 : null;
      for (const key of [...selection]) {
        const [sourceIndex, rowIndex] = key.split(":").map(Number);
        if (!seriesBySource(sourceIndex) || rowIndex >= count) selection.delete(key);
      }
      if (!selection.size) hideSelectionBar();
      renderLegend();
      renderInspector();
      if (!drag) hideTooltip();
      scheduleRender();
    },
    refresh: scheduleRender,
    destroy() {
      resizeObserver?.disconnect();
      for (const [target, type, handler, capture] of listeners) target.removeEventListener(type, handler, capture || false);
      if (animationFrame !== null) window.cancelAnimationFrame(animationFrame);
    },
  };
}
