// The dashboard document: its shape, its defaults, and the grid layout rules.
//
// A dashboard is plain JSON (see docs/ui/dashboard.md). Everything here is a pure function of
// that JSON, so the page, the tests, and ArcBot's edits all go through the same normalization.

export const DASHBOARD_FORMAT = "arco-dashboard";
export const DASHBOARD_VERSION = 1;
export const GRID_COLUMNS = 12;
export const MIN_WIDGET_WIDTH = 2;
export const MIN_WIDGET_HEIGHT = 2;

// One entry per widget type: its menu label, the size a new one gets, and which fields it reads.
// `series` and `measures` say whether the inspector offers them; `maxMeasures` caps the list.
export const WIDGET_TYPES = {
  bar: { label: "Bar Chart", w: 6, h: 5, category: true, series: true, maxMeasures: 8 },
  line: { label: "Line Chart", w: 6, h: 5, category: true, series: true, maxMeasures: 8 },
  area: { label: "Area Chart", w: 6, h: 5, category: true, series: true, maxMeasures: 8 },
  scatter: { label: "Scatter Plot", w: 6, h: 5, category: true, series: true, maxMeasures: 2, minMeasures: 2 },
  heatmap: { label: "Heat Map", w: 6, h: 6, category: true, series: true, maxMeasures: 1 },
  share: { label: "Share Bar", w: 6, h: 3, category: true, series: false, maxMeasures: 1 },
  kpi: { label: "Number Tile", w: 3, h: 2, category: true, series: false, maxMeasures: 1 },
  table: { label: "Table", w: 6, h: 5, category: true, series: true, maxMeasures: 12 },
  text: { label: "Text", w: 4, h: 2, category: false, series: false, maxMeasures: 0 },
};

export const AGGREGATIONS = [
  { id: "sum", label: "Sum" },
  { id: "latest", label: "Latest" },
  { id: "avg", label: "Average" },
  { id: "min", label: "Minimum" },
  { id: "max", label: "Maximum" },
  { id: "count", label: "Count" },
];

export const NUMBER_FORMATS = [
  { id: "auto", label: "Automatic" },
  { id: "number", label: "Number" },
  { id: "compact", label: "Compact" },
  { id: "percent", label: "Percent" },
  { id: "currency", label: "Currency" },
];

const SOURCE_KINDS = new Set(["arco_datasets", "arco_source_table", "csv", "sql"]);

const text = (value) => String(value ?? "").trim();
const isObject = (value) => !!value && typeof value === "object" && !Array.isArray(value);
const textList = (value) => (Array.isArray(value) ? value.map(text).filter(Boolean) : []);

export function newId(prefix, taken = []) {
  const used = new Set(taken);
  for (let index = 1; ; index += 1) {
    const id = `${prefix}${index}`;
    if (!used.has(id)) return id;
  }
}

function clampInt(value, low, high, fallback) {
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return fallback;
  return Math.max(low, Math.min(high, number));
}

export function normalizeLayout(raw, type) {
  const spec = WIDGET_TYPES[type] || WIDGET_TYPES.bar;
  const w = clampInt(raw?.w, MIN_WIDGET_WIDTH, GRID_COLUMNS, spec.w);
  return {
    x: clampInt(raw?.x, 0, GRID_COLUMNS - w, 0),
    y: clampInt(raw?.y, 0, 10000, 0),
    w,
    h: clampInt(raw?.h, MIN_WIDGET_HEIGHT, 40, spec.h),
  };
}

function normalizeMeasure(raw) {
  if (!isObject(raw)) return null;
  const expr = text(raw.expr);
  const field = text(raw.field);
  if (!expr && !field) return null;
  const measure = expr ? { expr } : { field, agg: text(raw.agg) };
  if (text(raw.label)) measure.label = text(raw.label);
  if (text(raw.format)) measure.format = text(raw.format);
  if (Number.isFinite(Number(raw.decimals)) && raw.decimals !== "" && raw.decimals != null) {
    measure.decimals = clampInt(raw.decimals, 0, 6, 0);
  }
  return measure;
}

export function normalizeFilter(raw) {
  if (!isObject(raw) || !text(raw.field)) return null;
  const filter = { field: text(raw.field), values: Array.isArray(raw.values) ? raw.values.map((value) => (value == null ? null : String(value))) : [] };
  if (raw.exclude) filter.exclude = true;
  return filter;
}

function normalizeCompare(raw) {
  if (!isObject(raw) || !text(raw.field) || !text(raw.base) || !text(raw.target)) return null;
  return {
    field: text(raw.field),
    base: text(raw.base),
    target: text(raw.target),
    mode: raw.mode === "percent" ? "percent" : "delta",
  };
}

export function normalizeWidget(raw, takenIds = []) {
  const source = isObject(raw) ? raw : {};
  const type = WIDGET_TYPES[source.type] ? source.type : "bar";
  const spec = WIDGET_TYPES[type];
  const id = text(source.id) && !takenIds.includes(text(source.id)) ? text(source.id) : newId("w", takenIds);
  const widget = {
    id,
    type,
    title: text(source.title),
    layout: normalizeLayout(source.layout, type),
  };
  if (type === "text") {
    widget.text = String(source.text ?? "");
    return widget;
  }
  widget.source = text(source.source);
  widget.category = spec.category ? text(source.category) : "";
  widget.series = spec.series ? text(source.series) : "";
  widget.measures = (Array.isArray(source.measures) ? source.measures : [])
    .map(normalizeMeasure)
    .filter(Boolean)
    .slice(0, spec.maxMeasures);
  widget.filters = (Array.isArray(source.filters) ? source.filters : []).map(normalizeFilter).filter(Boolean);
  const compare = normalizeCompare(source.compare);
  if (compare) widget.compare = compare;
  const sort = isObject(source.sort) ? source.sort : {};
  if (sort.by === "value" || sort.by === "category") {
    widget.sort = { by: sort.by, dir: sort.dir === "asc" ? "asc" : "desc" };
  }
  const limit = clampInt(source.limit, 1, 500, 0);
  if (limit) widget.limit = limit;
  const options = isObject(source.options) ? source.options : {};
  widget.options = {};
  for (const flag of ["stacked", "horizontal", "table", "labels"]) {
    if (options[flag]) widget.options[flag] = true;
  }
  return widget;
}

function normalizeSource(raw, takenIds) {
  if (!isObject(raw) || !SOURCE_KINDS.has(raw.kind)) return null;
  const id = text(raw.id) && !takenIds.includes(text(raw.id)) ? text(raw.id) : newId("src", takenIds);
  const source = { id, name: text(raw.name) || id, kind: raw.kind };
  if (raw.kind === "arco_datasets" || raw.kind === "arco_source_table") {
    const projects = (Array.isArray(raw.projects) && raw.projects.length ? raw.projects : [raw.project])
      .map((item) => (isObject(item) ? { name: text(item.name), label: text(item.label) || text(item.name) } : { name: text(item), label: text(item) }))
      .filter((item) => item.name);
    source.projects = projects;
  }
  if (raw.kind === "arco_datasets") {
    source.reserving_classes = textList(raw.reserving_classes);
    source.datasets = textList(raw.datasets);
    source.level_names = textList(raw.level_names);
  } else if (raw.kind === "arco_source_table" || raw.kind === "csv") {
    if (raw.kind === "csv") source.path = text(raw.path);
    source.dimensions = textList(raw.dimensions);
    source.measures = textList(raw.measures);
  } else {
    source.engine = raw.engine === "snowflake" ? "snowflake" : "sqlserver";
    source.connection = text(raw.connection);
    source.sql = String(raw.sql ?? "");
  }
  if (isObject(raw.extract) && Array.isArray(raw.extract.columns) && Array.isArray(raw.extract.rows)) {
    source.extract = raw.extract;
  }
  return source;
}

function normalizePage(raw, takenIds) {
  const source = isObject(raw) ? raw : {};
  const id = text(source.id) && !takenIds.includes(text(source.id)) ? text(source.id) : newId("p", takenIds);
  const widgetIds = [];
  const widgets = [];
  for (const item of Array.isArray(source.widgets) ? source.widgets : []) {
    const widget = normalizeWidget(item, widgetIds);
    widgetIds.push(widget.id);
    widgets.push(widget);
  }
  const filters = [];
  for (const item of Array.isArray(source.filters) ? source.filters : []) {
    const filter = normalizeFilter(item);
    if (!filter || filters.some((existing) => existing.field === filter.field)) continue;
    if (text(item.label)) filter.label = text(item.label);
    filters.push(filter);
  }
  return { id, name: text(source.name) || "Page", filters, widgets: resolveLayout(widgets) };
}

export function normalizeDashboard(raw) {
  const source = isObject(raw) ? raw : {};
  const sources = [];
  for (const item of Array.isArray(source.sources) ? source.sources : []) {
    const normalized = normalizeSource(item, sources.map((entry) => entry.id));
    if (normalized) sources.push(normalized);
  }
  const pages = [];
  for (const item of Array.isArray(source.pages) ? source.pages : []) {
    pages.push(normalizePage(item, pages.map((entry) => entry.id)));
  }
  if (!pages.length) pages.push(normalizePage({ name: "Page 1" }, []));
  return {
    format: DASHBOARD_FORMAT,
    version: DASHBOARD_VERSION,
    name: text(source.name) || "Untitled Dashboard",
    description: text(source.description),
    sources,
    pages,
  };
}

export function createDashboard(name = "Untitled Dashboard") {
  return normalizeDashboard({ name, pages: [{ name: "Page 1" }] });
}

// ---------------------------------------------------------------------------
// Grid layout
// ---------------------------------------------------------------------------

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

// Settle a page's widgets so none overlap and none floats over an empty row. The widget named
// `anchorId` keeps the cell the user just gave it; the rest move down out of its way, then every
// widget rises as far as it can.
export function resolveLayout(widgets, anchorId = "") {
  const items = widgets.map((widget) => ({ ...widget, layout: { ...widget.layout } }));
  const order = [...items].sort((a, b) => {
    if (a.id === anchorId) return -1;
    if (b.id === anchorId) return 1;
    return a.layout.y - b.layout.y || a.layout.x - b.layout.x;
  });
  const placed = [];
  for (const item of order) {
    while (placed.some((other) => overlaps(item.layout, other.layout))) item.layout.y += 1;
    placed.push(item);
  }
  const rising = [...placed].sort((a, b) => a.layout.y - b.layout.y || a.layout.x - b.layout.x);
  for (const item of rising) {
    while (item.layout.y > 0) {
      const lifted = { ...item.layout, y: item.layout.y - 1 };
      if (rising.some((other) => other !== item && overlaps(lifted, other.layout))) break;
      item.layout = lifted;
    }
  }
  return items;
}

// The first free cell that fits a `w` by `h` widget, scanning rows from the top.
export function findFreeCell(widgets, w, h) {
  for (let y = 0; ; y += 1) {
    for (let x = 0; x + w <= GRID_COLUMNS; x += 1) {
      const cell = { x, y, w, h };
      if (!widgets.some((widget) => overlaps(cell, widget.layout))) return { x, y };
    }
  }
}

export function gridRows(widgets) {
  return widgets.reduce((rows, widget) => Math.max(rows, widget.layout.y + widget.layout.h), 0);
}

// ---------------------------------------------------------------------------
// Fields and defaults
// ---------------------------------------------------------------------------

export function sourceColumns(source) {
  return Array.isArray(source?.extract?.columns) ? source.extract.columns : [];
}

export function defaultAggregation(column) {
  return text(column?.default_aggregation) || "sum";
}

export function measureLabel(measure, compare = null) {
  const base = text(measure?.label) || text(measure?.field) || text(measure?.expr) || "Value";
  if (!compare) return base;
  return compare.mode === "percent" ? `${base} % Change` : `${base} Change`;
}

// A widget placed from the library or the palette has no fields yet. Give it the first sensible
// ones from its source so it draws something the user can then change.
export function applyDefaultFields(widget, source) {
  if (widget.type === "text" || !source) return widget;
  const columns = sourceColumns(source);
  const dimensions = columns.filter((column) => column.role !== "measure");
  const measures = columns.filter((column) => column.role === "measure" && column.name !== "Rows");
  const spec = WIDGET_TYPES[widget.type];
  const next = { ...widget, source: source.id, measures: [...(widget.measures || [])] };
  if (columns.length) {
    // A template may name fields this source does not have; those fall back to the defaults.
    const names = new Set(columns.map((column) => column.name));
    if (next.category && !names.has(next.category)) next.category = "";
    if (next.series && !names.has(next.series)) next.series = "";
    next.measures = next.measures.filter((measure) => measure.expr || names.has(measure.field));
  }
  const preferred = dimensions.find((column) => column.name === "Origin Year") || dimensions.find((column) => column.name === "Origin") || dimensions[0];
  if (spec.category && !next.category && widget.type !== "kpi" && preferred) next.category = preferred.name;
  if (!next.measures.length && measures.length) {
    const count = Math.max(1, spec.minMeasures || 1);
    // Across development periods only a triangle has anything to show.
    const acrossDevelopment = next.category === "Development" || next.series === "Development";
    const ranked = acrossDevelopment
      ? [...measures.filter((column) => column.data_format === "Triangle"), ...measures.filter((column) => column.data_format !== "Triangle")]
      : measures;
    next.measures = ranked.slice(0, count).map((column) => ({ field: column.name, agg: defaultAggregation(column) }));
  }
  if (widget.type === "heatmap" && !next.series) {
    const second = dimensions.find((column) => column.name === "Development") || dimensions.find((column) => column.name !== next.category);
    if (second) next.series = second.name;
  }
  return next;
}

export function createWidget(type, takenIds, template = null) {
  const spec = WIDGET_TYPES[type] || WIDGET_TYPES.bar;
  const base = template && isObject(template) ? template : {};
  return normalizeWidget({
    ...base,
    type: WIDGET_TYPES[base.type] ? base.type : type,
    id: "",
    title: text(base.title) || spec.label,
    layout: { w: base.layout?.w || spec.w, h: base.layout?.h || spec.h, x: 0, y: 0 },
  }, takenIds);
}

// ---------------------------------------------------------------------------
// ArcBot
// ---------------------------------------------------------------------------

// The dashboard as ArcBot reads and edits it: the same document without the saved tables, which
// are large and not ArcBot's to change. Each source lists its fields instead.
export function toAssistantJson(dashboard) {
  return {
    ...dashboard,
    sources: dashboard.sources.map((source) => {
      const { extract, ...rest } = source;
      return {
        ...rest,
        fields: sourceColumns(source).map((column) => ({
          name: column.name,
          role: column.role,
          ...(column.default_aggregation ? { default_aggregation: column.default_aggregation } : {}),
        })),
      };
    }),
  };
}

// Take ArcBot's edited document back: normalize it and put each surviving source's saved table
// back in place. A source whose definition changed keeps its old table until it is refreshed.
export function fromAssistantJson(edited, current) {
  const next = normalizeDashboard(edited);
  const extracts = new Map(current.sources.map((source) => [source.id, source.extract]));
  for (const source of next.sources) {
    delete source.fields;
    if (extracts.get(source.id)) source.extract = extracts.get(source.id);
  }
  return next;
}

export const ASSISTANT_GUIDE = [
  "The active page is an Arco dashboard. Its JSON has `sources` (tables), and `pages` holding `widgets` on a 12-column grid.",
  "Each source lists `fields`: a `dimension` groups, a `measure` is a number. Use field names exactly as listed; never invent one.",
  "Widget: {id, type, title, layout:{x,y,w,h}, source:<source id>, category:<dimension>, series:<dimension or \"\">, measures:[...], filters:[{field, values:[...]}], compare, sort:{by:\"value\"|\"category\", dir}, limit, options:{stacked, horizontal, table, labels}}.",
  `Widget types: ${Object.keys(WIDGET_TYPES).join(", ")}. bar/line/area chart measures by category; heatmap needs category, series and one measure; scatter needs two measures; kpi and share take one measure; text has only {text}.`,
  "A measure is {field, agg, label, format, decimals} with agg one of sum, latest, avg, min, max, count, or a calculation {expr, label, format} such as `latest([Net Loss--Paid]) / sum([Earned Premium])`. Use `latest` for a cumulative triangle column. format is auto, number, compact, percent or currency.",
  "compare:{field, base, target, mode:\"delta\"|\"percent\"} charts the change in each measure between two values of a field, such as two projects.",
  "A page's `filters` list the fields offered in the filter row: [{field, values:[]}] where empty values means no filtering.",
  "Never use two y-axes, and keep a chart to eight series or fewer. Leave `sources` unchanged unless the user asks to change the data; do not add an `extract`.",
  "To add a widget give it a new id and a layout that does not overlap the others. Keep every existing id.",
].join("\n");
