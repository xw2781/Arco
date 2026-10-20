// Dataset Viewer chart data: turns the dataset model into chart series and
// keeps the focused-series colour slots. No DOM access, so tests import it directly.

export const MAX_FOCUSED_SERIES = 4;
const DEFAULT_FOCUSED_SERIES = 3;

export function effectiveDevLabels(model) {
  const devs = Array.isArray(model?.dev_labels) ? model.dev_labels.map(String) : [];
  const width = (model?.values || []).reduce((n, row) => Math.max(n, Array.isArray(row) ? row.length : 0), 0);
  if (!width) return devs;
  if (devs.length >= width) return devs.slice(0, width);
  return devs.concat(Array(width - devs.length).fill(""));
}

// Rows are origins, columns are development ages (or age intervals for ratios).
export function buildChartMatrix(model, mode = "value") {
  if (!Array.isArray(model?.values) || !Array.isArray(model?.mask)) return null;
  const devs = effectiveDevLabels(model);
  const cells = model.values.map((row, r) => devs.map((_, c) => {
    const v = row?.[c];
    return model.mask[r]?.[c] && typeof v === "number" && Number.isFinite(v) ? v : null;
  }));
  const originLabels = cells.map((_, r) => String(model.origin_labels?.[r] ?? r + 1));
  if (mode === "incremental") {
    return {
      originLabels,
      colKeys: devs,
      colLabels: devs,
      values: cells.map((row) => row.map((v, c) => {
        if (v == null || c === 0) return v;
        return row[c - 1] == null ? null : v - row[c - 1];
      })),
    };
  }
  if (mode === "ratio") {
    const colKeys = devs.slice(0, -1);
    return {
      originLabels,
      colKeys,
      colLabels: colKeys.map((dev, c) => `${dev}-${devs[c + 1]}`),
      values: cells.map((row) => colKeys.map((_, c) => (
        row[c] != null && row[c + 1] != null && row[c] !== 0 ? row[c + 1] / row[c] : null
      ))),
    };
  }
  return { originLabels, colKeys: devs, colLabels: devs, values: cells };
}

export function buildChartSeries(matrix, plot, formatOrigin = String) {
  if (plot === "byCol") {
    return {
      xLabels: matrix.originLabels.map(formatOrigin),
      list: matrix.colKeys.map((key, c) => ({
        id: `d:${key}`,
        label: matrix.colLabels[c] === key ? `Age ${key}` : matrix.colLabels[c],
        values: matrix.values.map((row) => row[c]),
        index: c,
      })),
    };
  }
  return {
    xLabels: matrix.colLabels,
    list: matrix.values.map((row, r) => ({
      id: `o:${matrix.originLabels[r]}`,
      label: formatOrigin(matrix.originLabels[r]),
      values: row,
      index: r,
    })),
  };
}

const pointCount = (values) => values.reduce((n, v) => n + (v == null ? 0 : 1), 0);

// Newest origins for origin curves, earliest ages for the age trend.
export function defaultFocusIds(list, plot) {
  const plotted = list.filter((series) => pointCount(series.values) >= 2);
  const picked = plot === "byRow"
    ? plotted.slice(-DEFAULT_FOCUSED_SERIES)
    : plotted.slice(0, DEFAULT_FOCUSED_SERIES);
  return picked.map((series) => series.id);
}

// A slot is a colour; a series keeps its slot while it stays focused, so
// removing one focused series never repaints the others.
export function addFocusedSeries(ids, slots, id) {
  if (ids.includes(id)) return true;
  if (ids.length >= MAX_FOCUSED_SERIES) return false;
  const used = new Set(Object.values(slots));
  let slot = 0;
  while (used.has(slot)) slot++;
  slots[id] = slot;
  ids.push(id);
  return true;
}

export function removeFocusedSeries(ids, slots, id) {
  const at = ids.indexOf(id);
  if (at < 0) return;
  ids.splice(at, 1);
  delete slots[id];
}
