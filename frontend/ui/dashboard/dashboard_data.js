// The dashboard's query engine: filter a table, group it, aggregate measures, and shape the
// answer a chart draws. Pure functions over the table payload `dashboard_data_service` returns,
// so every widget type and the tests share one implementation of each rule.

import { measureLabel, sourceColumns } from "./dashboard_model.js";

export const MAX_SERIES = 8;
export const OTHER_LABEL = "Other";
const BLANK_LABEL = "(Blank)";

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
const keyOf = (value) => (value == null ? "\u0000" : String(value));

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

export function buildTable(payload) {
  const columns = Array.isArray(payload?.columns) ? payload.columns : [];
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  const index = new Map(columns.map((column, position) => [column.name, position]));
  const ranks = new Map();
  for (const column of columns) {
    if (Array.isArray(column.order) && column.order.length) {
      ranks.set(column.name, new Map(column.order.map((value, rank) => [String(value), rank])));
    }
  }
  let semi = null;
  const rule = payload?.semi_additive;
  if (rule && index.has(rule.order) && Array.isArray(rule.partition)) {
    semi = {
      partition: rule.partition.filter((name) => index.has(name)).map((name) => index.get(name)),
      order: index.get(rule.order),
      rank: ranks.get(rule.order) || new Map(),
    };
  }
  return { columns, rows, index, ranks, semi };
}

export function tableOfSource(source) {
  return buildTable({ ...(source?.extract || {}), columns: sourceColumns(source) });
}

export function compareValues(table, field) {
  const rank = table.ranks.get(field);
  return (a, b) => {
    if (a == null || b == null) return (a == null) - (b == null);
    if (rank) {
      const ra = rank.get(String(a));
      const rb = rank.get(String(b));
      if (ra != null && rb != null) return ra - rb;
      if (ra != null || rb != null) return ra != null ? -1 : 1;
    }
    if (isNumber(a) && isNumber(b)) return a - b;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  };
}

export function distinctValues(table, field, rows = table.rows) {
  const position = table.index.get(field);
  if (position == null) return [];
  const seen = new Map();
  for (const row of rows) {
    const value = row[position];
    if (value != null && !seen.has(String(value))) seen.set(String(value), value);
  }
  return [...seen.values()].sort(compareValues(table, field));
}

export function applyFilters(table, filters) {
  const active = [];
  for (const filter of filters || []) {
    const position = table.index.get(filter?.field);
    if (position == null || !Array.isArray(filter.values) || !filter.values.length) continue;
    active.push({ position, values: new Set(filter.values.map(keyOf)), exclude: !!filter.exclude });
  }
  if (!active.length) return table.rows;
  return table.rows.filter((row) => active.every((filter) => filter.values.has(keyOf(row[filter.position])) !== filter.exclude));
}

// ---------------------------------------------------------------------------
// Aggregation
// ---------------------------------------------------------------------------

function latestTotal(table, rows, position) {
  const semi = table.semi;
  if (!semi) return sumOf(rows, position);
  // Per partition (one reserving class and origin), the value at the newest development period
  // that has one. A vector's value sits on its own row with no period, ranked below every period.
  const newest = new Map();
  for (const row of rows) {
    const value = row[position];
    if (!isNumber(value)) continue;
    let key = "";
    for (const part of semi.partition) key += `${keyOf(row[part])}\u0001`;
    const rank = row[semi.order] == null ? -1 : (semi.rank.get(String(row[semi.order])) ?? -1);
    const held = newest.get(key);
    if (!held || rank >= held.rank) newest.set(key, { rank, value });
  }
  if (!newest.size) return null;
  let total = 0;
  for (const held of newest.values()) total += held.value;
  return total;
}

function sumOf(rows, position) {
  let total = 0;
  let found = false;
  for (const row of rows) {
    if (isNumber(row[position])) { total += row[position]; found = true; }
  }
  return found ? total : null;
}

function aggregate(table, rows, position, agg) {
  if (agg === "latest") return latestTotal(table, rows, position);
  if (agg === "sum") return sumOf(rows, position);
  let count = 0;
  let total = 0;
  let low = Infinity;
  let high = -Infinity;
  for (const row of rows) {
    const value = row[position];
    if (agg === "count") { if (value != null) count += 1; continue; }
    if (!isNumber(value)) continue;
    count += 1;
    total += value;
    if (value < low) low = value;
    if (value > high) high = value;
  }
  if (agg === "count") return count;
  if (!count) return null;
  if (agg === "avg") return total / count;
  if (agg === "min") return low;
  if (agg === "max") return high;
  return total;
}

const AGG_NAMES = new Set(["sum", "latest", "avg", "min", "max", "count"]);

function tokenize(expr) {
  const tokens = [];
  let position = 0;
  while (position < expr.length) {
    const char = expr[position];
    if (/\s/.test(char)) { position += 1; continue; }
    if (char === "[") {
      const end = expr.indexOf("]", position);
      if (end < 0) throw new Error("A field name is missing its closing bracket.");
      tokens.push({ type: "field", value: expr.slice(position + 1, end).trim() });
      position = end + 1;
    } else if (/[0-9.]/.test(char)) {
      const match = /^[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?/.exec(expr.slice(position));
      if (!match) throw new Error(`Unexpected "${char}".`);
      tokens.push({ type: "number", value: Number(match[0]) });
      position += match[0].length;
    } else if (/[A-Za-z_]/.test(char)) {
      const match = /^[A-Za-z_]+/.exec(expr.slice(position));
      tokens.push({ type: "name", value: match[0].toLowerCase() });
      position += match[0].length;
    } else if ("+-*/()".includes(char)) {
      tokens.push({ type: char });
      position += 1;
    } else {
      throw new Error(`Unexpected "${char}".`);
    }
  }
  return tokens;
}

// Parse a calculation such as `latest([Paid]) / sum([Premium]) - 1` into a tree of
// {num} | {agg, field} | {op, left, right} | {neg}. A bare `[Field]` takes the field's own
// default aggregation.
export function parseExpression(expr) {
  const tokens = tokenize(String(expr || ""));
  let position = 0;
  const peek = () => tokens[position];
  const take = (type) => {
    const token = tokens[position];
    if (!token || token.type !== type) throw new Error(type === ")" ? "A bracket is not closed." : "The calculation is incomplete.");
    position += 1;
    return token;
  };
  function primary() {
    const token = peek();
    if (!token) throw new Error("The calculation is incomplete.");
    if (token.type === "number") { position += 1; return { num: token.value }; }
    if (token.type === "field") { position += 1; return { agg: "", field: token.value }; }
    if (token.type === "name") {
      if (!AGG_NAMES.has(token.value)) throw new Error(`Unknown function "${token.value}".`);
      position += 1;
      take("(");
      const field = take("field");
      take(")");
      return { agg: token.value, field: field.value };
    }
    if (token.type === "(") { position += 1; const inner = sum(); take(")"); return inner; }
    if (token.type === "-") { position += 1; return { neg: primary() }; }
    throw new Error("The calculation is incomplete.");
  }
  function product() {
    let left = primary();
    while (peek() && (peek().type === "*" || peek().type === "/")) {
      const op = tokens[position++].type;
      left = { op, left, right: primary() };
    }
    return left;
  }
  function sum() {
    let left = product();
    while (peek() && (peek().type === "+" || peek().type === "-")) {
      const op = tokens[position++].type;
      left = { op, left, right: product() };
    }
    return left;
  }
  const tree = sum();
  if (position < tokens.length) throw new Error("The calculation has something extra at the end.");
  return tree;
}

function expressionFields(tree, found = []) {
  if (tree.field != null) found.push(tree.field);
  for (const key of ["left", "right", "neg"]) if (tree[key]) expressionFields(tree[key], found);
  return found;
}

// Turn one widget measure into `rows -> number | null`. Throws with a sentence the widget shows
// when the measure names a field its source does not have.
export function compileMeasure(table, measure) {
  const columnAgg = (field) => table.columns[table.index.get(field)]?.default_aggregation || "sum";
  const requireField = (field) => {
    if (!table.index.has(field)) throw new Error(`This data source has no field named "${field}".`);
    return table.index.get(field);
  };
  if (measure.expr) {
    const tree = parseExpression(measure.expr);
    expressionFields(tree).forEach(requireField);
    const evaluate = (node, rows) => {
      if (node.num != null) return node.num;
      if (node.field != null) return aggregate(table, rows, table.index.get(node.field), node.agg || columnAgg(node.field));
      if (node.neg) { const value = evaluate(node.neg, rows); return value == null ? null : -value; }
      const left = evaluate(node.left, rows);
      const right = evaluate(node.right, rows);
      if (left == null || right == null) return null;
      if (node.op === "+") return left + right;
      if (node.op === "-") return left - right;
      if (node.op === "*") return left * right;
      return right === 0 ? null : left / right;
    };
    return (rows) => evaluate(tree, rows);
  }
  const position = requireField(measure.field);
  const agg = AGG_NAMES.has(measure.agg) ? measure.agg : columnAgg(measure.field);
  return (rows) => aggregate(table, rows, position, agg);
}

function withCompare(table, evaluate, compare) {
  const position = table.index.get(compare.field);
  if (position == null) throw new Error(`This data source has no field named "${compare.field}".`);
  return (rows) => {
    const target = evaluate(rows.filter((row) => String(row[position]) === compare.target));
    const base = evaluate(rows.filter((row) => String(row[position]) === compare.base));
    if (target == null || base == null) return null;
    if (compare.mode === "percent") return base === 0 ? null : (target - base) / Math.abs(base);
    return target - base;
  };
}

// Group `rows` by `dims` and evaluate every measure per group. A dim is a field name or
// `{field, map}` where `map` rewrites the value before grouping (used to fold a tail into Other).
export function runQuery(table, { rows = table.rows, dims = [], measures = [], compare = null } = {}) {
  const accessors = dims.map((dim) => {
    const field = typeof dim === "string" ? dim : dim.field;
    const position = table.index.get(field);
    if (position == null) throw new Error(`This data source has no field named "${field}".`);
    const map = typeof dim === "string" ? null : dim.map;
    return map ? (row) => map(row[position]) : (row) => row[position];
  });
  const evaluators = measures.map((measure) => {
    const evaluate = compileMeasure(table, measure);
    return compare ? withCompare(table, evaluate, compare) : evaluate;
  });
  const groups = new Map();
  for (const row of rows) {
    const keys = accessors.map((accessor) => accessor(row));
    const id = keys.map(keyOf).join("\u0001");
    let group = groups.get(id);
    if (!group) { group = { keys, rows: [] }; groups.set(id, group); }
    group.rows.push(row);
  }
  if (!dims.length && !groups.size) groups.set("", { keys: [], rows: [] });
  return [...groups.values()].map((group) => ({
    keys: group.keys,
    values: evaluators.map((evaluate) => evaluate(group.rows)),
  }));
}

// ---------------------------------------------------------------------------
// Widget result
// ---------------------------------------------------------------------------

const CAPPED_TYPES = new Set(["bar", "line", "area", "scatter"]);

function label(value) {
  return value == null ? BLANK_LABEL : String(value);
}

// The answer one widget draws: `categories` along the main dimension and one `series` per
// breakdown value or per measure, each with a value per category. `error` carries a sentence
// instead when the widget cannot be drawn.
export function buildWidgetResult(table, widget, extraFilters = []) {
  const measures = widget.measures || [];
  if (!measures.length) return { error: "Choose a measure." };
  const compare = widget.compare || null;
  try {
    const rows = applyFilters(table, [...(widget.filters || []), ...extraFilters]);
    const hasCategory = !!widget.category && widget.type !== "kpi";
    const breakdown = widget.series && widget.type !== "scatter" ? widget.series : "";
    const dims = [];
    if (hasCategory) dims.push(widget.category);
    if (breakdown) dims.push(breakdown);
    if (widget.type === "scatter") {
      if (!hasCategory) return { error: "Choose the field that makes each point." };
      if (measures.length < 2) return { error: "A scatter plot needs two measures." };
      if (widget.series) dims.push(widget.series);
    }
    const queried = measures.length && breakdown ? [measures[0]] : measures;
    let groups = runQuery(table, { rows, dims, measures: queried, compare });
    groups = groups.filter((group) => group.values.some((value) => value != null));

    const seriesPosition = hasCategory ? 1 : 0;
    let folded = 0;
    if (breakdown && CAPPED_TYPES.has(widget.type)) {
      const totals = new Map();
      for (const group of groups) {
        const key = keyOf(group.keys[seriesPosition]);
        totals.set(key, (totals.get(key) || 0) + Math.abs(group.values[0] || 0));
      }
      if (totals.size > MAX_SERIES) {
        const kept = new Set([...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, MAX_SERIES - 1).map((entry) => entry[0]));
        folded = totals.size - kept.size;
        const foldedDims = [...dims];
        foldedDims[seriesPosition] = { field: breakdown, map: (value) => (kept.has(keyOf(value)) ? value : OTHER_LABEL) };
        groups = runQuery(table, { rows, dims: foldedDims, measures: queried, compare })
          .filter((group) => group.values.some((value) => value != null));
      }
    }

    const format = (index) => ({ ...measures[index], label: measureLabel(measures[index], compare), compare: !!compare, compareMode: compare?.mode });
    const result = { categoryField: hasCategory ? widget.category : "", seriesField: breakdown, folded, measures: measures.map((_, index) => format(index)) };

    if (widget.type === "scatter") {
      result.points = groups
        .filter((group) => group.values[0] != null && group.values[1] != null)
        .map((group) => ({
          label: label(group.keys[0]),
          key: group.keys[0],
          series: widget.series ? label(group.keys[1]) : "",
          x: group.values[0],
          y: group.values[1],
        }));
      const names = [...new Set(result.points.map((point) => point.series))];
      // Every pair of dots must stay distinguishable, which holds for three series only.
      result.seriesNames = names.length > 3 ? [] : names;
      if (names.length > 3) result.points.forEach((point) => { point.series = ""; });
      if (!result.points.length) result.empty = true;
      return result;
    }

    let categories = hasCategory ? [...new Map(groups.map((group) => [keyOf(group.keys[0]), group.keys[0]])).values()] : [null];
    if (hasCategory) categories.sort(compareValues(table, widget.category));
    let seriesKeys = [];
    if (breakdown) {
      seriesKeys = [...new Map(groups.map((group) => [keyOf(group.keys[seriesPosition]), group.keys[seriesPosition]])).values()];
      seriesKeys.sort(compareValues(table, breakdown));
      const other = seriesKeys.findIndex((value) => value === OTHER_LABEL);
      if (folded && other >= 0) seriesKeys.push(...seriesKeys.splice(other, 1));
    }
    const cell = new Map();
    for (const group of groups) {
      const categoryKey = hasCategory ? keyOf(group.keys[0]) : "";
      if (breakdown) cell.set(`${categoryKey}\u0001${keyOf(group.keys[seriesPosition])}`, group.values[0]);
      else group.values.forEach((value, index) => cell.set(`${categoryKey}\u0001${index}`, value));
    }
    const valueAt = (category, seriesId) => cell.get(`${hasCategory ? keyOf(category) : ""}\u0001${seriesId}`) ?? null;

    const sort = widget.sort;
    if (hasCategory && sort?.by === "value") {
      const total = (category) => (breakdown
        ? seriesKeys.reduce((sum, key) => sum + (valueAt(category, keyOf(key)) || 0), 0)
        : (valueAt(category, 0) ?? -Infinity));
      categories.sort((a, b) => (sort.dir === "asc" ? total(a) - total(b) : total(b) - total(a)));
    } else if (hasCategory && sort?.by === "category" && sort.dir === "desc") {
      categories.reverse();
    }
    if (widget.limit && categories.length > widget.limit) {
      result.cut = categories.length - widget.limit;
      categories = categories.slice(0, widget.limit);
    }

    result.categories = categories.map((value) => ({ key: value, label: label(value) }));
    result.series = breakdown
      ? seriesKeys.map((key) => ({
          key,
          label: label(key),
          measure: 0,
          foldedOther: folded > 0 && key === OTHER_LABEL,
          values: categories.map((category) => valueAt(category, keyOf(key))),
        }))
      : measures.map((_, index) => ({
          key: index,
          label: result.measures[index].label,
          measure: index,
          values: categories.map((category) => valueAt(category, index)),
        }));
    result.empty = !result.series.some((series) => series.values.some((value) => value != null));
    return result;
  } catch (error) {
    return { error: String(error?.message || error) };
  }
}

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

function compact(value, decimals) {
  const size = Math.abs(value);
  const units = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
  for (const [scale, suffix] of units) {
    if (size >= scale) {
      const scaled = value / scale;
      const places = decimals ?? (Math.abs(scaled) >= 100 ? 0 : 1);
      return `${scaled.toFixed(places)}${suffix}`;
    }
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: decimals ?? (size < 10 ? 2 : 0) });
}

// One value as text. `measure` carries the format the user chose; `short` asks for the compact
// form an axis tick or a tile uses when the format is left on automatic.
export function formatValue(value, measure = {}, { short = false } = {}) {
  if (value == null || !Number.isFinite(value)) return "";
  const decimals = Number.isFinite(measure.decimals) ? measure.decimals : null;
  const format = measure.compareMode === "percent" ? "percent" : (measure.format || "auto");
  const sign = measure.compare && value > 0 ? "+" : "";
  if (format === "percent") return `${sign}${(value * 100).toFixed(decimals ?? 1)}%`;
  if (format === "compact" || (format === "auto" && short && Math.abs(value) >= 10000)) return `${sign}${compact(value, decimals)}`;
  const size = Math.abs(value);
  const places = decimals ?? (size >= 1000 || Number.isInteger(value) ? 0 : size >= 10 ? 1 : size >= 1 ? 2 : 3);
  const body = value.toLocaleString(undefined, { minimumFractionDigits: decimals ?? 0, maximumFractionDigits: places });
  if (format === "currency") return `${value < 0 ? "-" : sign}$${body.replace("-", "")}`;
  return `${sign}${body}`;
}

// Round tick values covering [low, high], about `count` of them.
export function niceTicks(low, high, count = 5) {
  if (!Number.isFinite(low) || !Number.isFinite(high)) return [0, 1];
  if (low === high) { low = Math.min(0, low); high = Math.max(0, high); if (low === high) high = 1; }
  const rough = (high - low) / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((factor) => factor * power).find((candidate) => candidate >= rough) || power * 10;
  const start = Math.floor(low / step) * step;
  const ticks = [];
  for (let tick = start; tick < high + step * 0.999; tick += step) ticks.push(Number(tick.toPrecision(12)));
  return ticks;
}

// The same result as rows of text: the widget's table view, and what ArcBot is told a chart shows.
export function resultToRows(result) {
  if (!result || result.error) return { header: [], rows: [] };
  if (result.points) {
    const header = [result.categoryField || "Item", ...(result.seriesNames?.length ? [result.seriesField || "Series"] : []), result.measures[0].label, result.measures[1].label];
    return {
      header,
      rows: result.points.map((point) => [point.label, ...(result.seriesNames?.length ? [point.series] : []), formatValue(point.x, result.measures[0]), formatValue(point.y, result.measures[1])]),
    };
  }
  const header = [result.categoryField || "", ...result.series.map((series) => series.label)];
  const rows = result.categories.map((category, index) => [
    category.label,
    ...result.series.map((series) => formatValue(series.values[index], result.measures[series.measure])),
  ]);
  return { header: result.categoryField ? header : header.slice(1), rows: result.categoryField ? rows : rows.map((row) => row.slice(1)) };
}
