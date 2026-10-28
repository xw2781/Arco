/* Pure view model for the Stochastic Consolidation page: the settings a user
   edits, how they are read from and written back into the persisted method,
   the correlation matrix rules, the per-segment checks and the run state.
   Nothing here touches the DOM, so the page and its tests share one owner for
   every rule. The Results views come from the shared reserve-range model.

   The persisted contract is owned by
   python-api/src/arcrho_api/stochastic_consolidation_contract.py; the page only
   edits the owned fields its apply_owned_patch accepts and never computes a
   derived value a run would recompute. */

import { hasRangeRun, rangeSummary } from "../../shared/components/reserve_range/reserve_range_model.js?v=20260924a";

export const SCON_METHOD_TYPE = "Stochastic Consolidation";
export const SCON_JSON_FORMAT = "arcrho-stochastic-consolidation-v4";
export const SCON_FILE_PREFIX = "SCON@";
export const SCON_DEFAULT_DEGREES_OF_FREEDOM = 20;

export const SCON_CORRELATION_OPTIONS = Object.freeze([
  { value: "independent", label: "Independent" },
  { value: "fully_correlated", label: "Fully Correlated" },
  { value: "specified", label: "Specified" },
  { value: "as_generated", label: "As Generated" },
]);

export const SCON_DEPENDENCY_OPTIONS = Object.freeze([
  { value: "normal", label: "Normal" },
  { value: "uniform", label: "Uniform" },
  { value: "gamma", label: "Gamma" },
  { value: "student_t", label: "Student's T" },
]);

export const SCON_MATRIX_VIEWS = Object.freeze([
  { value: "target", label: "Target" },
  { value: "used", label: "Used" },
  { value: "achieved", label: "Achieved" },
]);

const MAX_SEED = 2147483646;

function text(value) {
  return String(value ?? "").trim();
}

function key(value) {
  return text(value).replace(/\s+/gu, " ").toLowerCase();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function tab(method, name) {
  const value = method?.[name];
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function choice(value, options, fallback) {
  const wanted = text(value).toLowerCase().replace(/[\s-]+/gu, "_");
  return options.some((option) => option.value === wanted) ? wanted : fallback;
}

function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

export function optionLabel(options, value) {
  return options.find((option) => option.value === value)?.label || text(value);
}

/* The project a segment is taken from; blank for the consolidation's own. */
export function segmentProject(segment) {
  return text(segment?.projectName ?? segment?.project_name);
}

/* The identity a segment is matched by: its project, reserving class and
   method name, compared the way the server compares them. */
export function segmentKey(segment) {
  return [
    key(segmentProject(segment)),
    key(segment?.reservingClass ?? segment?.reserving_class),
    key(segment?.methodName ?? segment?.method_name),
  ].join("\u0001");
}

/* The last level of a reserving-class path, which is what tells the segments
   of one consolidation apart. */
export function segmentShortLabel(segment) {
  const path = text(segment?.reservingClass ?? segment?.reserving_class);
  const parts = path.split("\\").map(text).filter(Boolean);
  return parts.at(-1) || path;
}

/* ---------------------------------------------------------------------------
   Correlation matrices
--------------------------------------------------------------------------- */

export function identityMatrix(size) {
  return Array.from({ length: size }, (_, i) => Array.from({ length: size }, (__, j) => (i === j ? 1 : 0)));
}

/* A square target matrix of the given size, the upper triangle authoritative
   and mirrored below, with a unit diagonal: the rule the contract applies. */
export function squareTargetMatrix(raw, size) {
  const source = Array.isArray(raw) ? raw : [];
  const result = identityMatrix(size);
  for (let i = 0; i < size; i += 1) {
    for (let j = i + 1; j < size; j += 1) {
      const value = numberOrNull(source[i]?.[j]);
      const clamped = value === null ? 0 : Math.max(-1, Math.min(1, value));
      result[i][j] = clamped;
      result[j][i] = clamped;
    }
  }
  return result;
}

/* Reads a typed correlation. A blank cell means 0; anything outside -1..1 is
   refused with the reason, so the cell can say it inline. */
export function parseCorrelationInput(value) {
  const raw = text(value).replaceAll(",", "");
  if (raw === "") return { ok: true, value: 0 };
  const percent = raw.endsWith("%");
  const n = Number(percent ? raw.slice(0, -1) : raw);
  if (!Number.isFinite(n)) return { ok: false, error: `${text(value)} is not a number.` };
  const result = percent ? n / 100 : n;
  if (result < -1 || result > 1) return { ok: false, error: `${text(value)} is outside -1 to 1.` };
  return { ok: true, value: result };
}

/* Sets one off-diagonal pair and mirrors it; the diagonal stays 1. */
export function setTargetCorrelation(matrix, row, column, value) {
  const size = Array.isArray(matrix) ? matrix.length : 0;
  const next = squareTargetMatrix(matrix, size);
  if (row === column || row < 0 || column < 0 || row >= size || column >= size) return next;
  next[row][column] = value;
  next[column][row] = value;
  return next;
}

/* The target matrix after the segment list changed: `order` names, for each
   new position, the old index the segment came from, or -1 for a new one, so
   every pair of segments keeps its correlation through a move, and a removed
   segment takes its row and column with it. */
export function reorderTargetMatrix(matrix, order) {
  const old = squareTargetMatrix(matrix, Array.isArray(matrix) ? matrix.length : 0);
  const size = order.length;
  const next = identityMatrix(size);
  for (let i = 0; i < size; i += 1) {
    for (let j = 0; j < size; j += 1) {
      if (i === j) continue;
      const a = order[i];
      const b = order[j];
      next[i][j] = a >= 0 && b >= 0 ? old[a][b] : 0;
    }
  }
  return next;
}

/* The matrix a correlation option stands for, before conversion. */
export function optionTargetMatrix(settings) {
  const size = settings?.segments?.length || 0;
  const option = settings?.correlationOption;
  if (option === "specified") return squareTargetMatrix(settings.targetCorrelations, size);
  if (option === "fully_correlated") {
    return Array.from({ length: size }, () => Array.from({ length: size }, () => 1));
  }
  return identityMatrix(size);
}

/* The linear correlation a normal copula needs for a target rank
   correlation: 2·sin(π·ρ/6). */
export function rankToLinear(rho) {
  return 2 * Math.sin((Math.PI * rho) / 6);
}

/* Whether a symmetric matrix has a Cholesky factor. A run repairs one that
   does not, by clipping its eigenvalues, so the page only says so. */
export function isPositiveDefinite(matrix) {
  const size = Array.isArray(matrix) ? matrix.length : 0;
  const lower = Array.from({ length: size }, () => new Array(size).fill(0));
  for (let i = 0; i < size; i += 1) {
    for (let j = 0; j <= i; j += 1) {
      let sum = Number(matrix[i][j]);
      for (let k = 0; k < j; k += 1) sum -= lower[i][k] * lower[j][k];
      if (i === j) {
        if (!(sum > 1e-12)) return false;
        lower[i][i] = Math.sqrt(sum);
      } else {
        lower[i][j] = sum / lower[j][j];
      }
    }
  }
  return true;
}

/* The matrix the run uses for the settings on screen: the option's target,
   converted cell by cell. `repairNeeded` says the run will repair it. */
export function usedCorrelationMatrix(settings) {
  const target = optionTargetMatrix(settings);
  const matrix = target.map((row, i) => row.map((value, j) => (i === j ? 1 : rankToLinear(value))));
  return { matrix, repairNeeded: matrix.length > 1 && !isPositiveDefinite(matrix) };
}

/* ---------------------------------------------------------------------------
   Settings
--------------------------------------------------------------------------- */

/* Every setting the page edits, read out of a persisted method (or out of an
   empty object for a new one). The defaults are the contract's defaults. */
export function readConsolidationSettings(method = {}) {
  const details = tab(method, "details_tab");
  const correlation = tab(method, "correlation_tab");
  const rawSegments = Array.isArray(tab(method, "segments_tab").segments) ? tab(method, "segments_tab").segments : [];
  const segments = rawSegments.map((segment) => ({
    projectName: text(segment?.project_name),
    reservingClass: text(segment?.reserving_class),
    methodName: text(segment?.method_name),
    factor: numberOrNull(segment?.factor) ?? 1,
  }));
  const seed = Number.parseInt(String(details.random_seed ?? ""), 10);
  const degrees = numberOrNull(correlation.degrees_of_freedom);
  const origin = Number.parseInt(String(details.origin_length ?? ""), 10);
  const development = Number.parseInt(String(details.development_length ?? ""), 10);
  return {
    name: text(details.name),
    outputType: text(details.output_type),
    datasetCategory: text(details.dataset_category),
    baseTriangleType: text(details.base_triangle_type),
    originLength: Number.isFinite(origin) && origin > 0 ? origin : 12,
    developmentLength: Number.isFinite(development) && development > 0 ? development : 12,
    randomSeed: Number.isFinite(seed) && seed >= 0 ? seed : 0,
    segments,
    correlationOption: choice(correlation.correlation_option, SCON_CORRELATION_OPTIONS, "specified"),
    dependencyType: choice(correlation.dependency_type, SCON_DEPENDENCY_OPTIONS, "normal"),
    degreesOfFreedom: degrees && degrees > 0 ? degrees : SCON_DEFAULT_DEGREES_OF_FREEDOM,
    targetCorrelations: squareTargetMatrix(correlation.target_correlations, segments.length),
  };
}

/* The method to send to Consolidate or Save: the loaded method (or a new
   skeleton) with every edited setting written back. A segment keeps the
   bootstrap revision it was consolidated with only while it names the same
   bootstrap, as the server's rebase does. Writing back what
   readConsolidationSettings read leaves the method unchanged. */
export function applyConsolidationSettings(method, settings) {
  const next = clone(method && typeof method === "object" ? method : {}) || {};
  const s = settings || {};
  next.json_format = SCON_JSON_FORMAT;
  next.details_tab = {
    ...tab(next, "details_tab"),
    name: text(s.name),
    method_type: SCON_METHOD_TYPE,
    output_type: text(s.outputType),
    dataset_category: text(s.datasetCategory),
    base_triangle_type: text(s.baseTriangleType),
    origin_length: s.originLength,
    development_length: s.developmentLength,
    random_seed: s.randomSeed,
  };
  const consumed = new Map(
    (Array.isArray(tab(next, "segments_tab").segments) ? tab(next, "segments_tab").segments : [])
      .map((segment) => [segmentKey(segment), text(segment?.bootstrap_revision)]),
  );
  const segments = (s.segments || []).map((segment) => ({
    ...(segmentProject(segment) ? { project_name: segmentProject(segment) } : {}),
    reserving_class: text(segment.reservingClass),
    method_name: text(segment.methodName),
    factor: numberOrNull(segment.factor) ?? 1,
    bootstrap_revision: consumed.get(segmentKey(segment)) || "",
  }));
  next.segments_tab = { ...tab(next, "segments_tab"), segments };
  next.correlation_tab = {
    ...tab(next, "correlation_tab"),
    correlation_option: s.correlationOption,
    dependency_type: s.dependencyType,
    degrees_of_freedom: s.degreesOfFreedom,
    target_correlations: squareTargetMatrix(s.targetCorrelations, segments.length),
  };
  return next;
}

export function newRandomSeed(random = Math.random) {
  return 1 + Math.floor(random() * MAX_SEED);
}

/* A snapshot of exactly what a run depends on, so the page can tell whether
   the run on screen still describes the settings on screen. Name, output type
   and notes do not change a run. */
export function runInputSnapshot(settings) {
  const s = settings || {};
  return JSON.stringify({
    base: key(s.baseTriangleType),
    seed: s.randomSeed,
    segments: (s.segments || []).map((segment) => [segmentKey(segment), numberOrNull(segment.factor)]),
    option: s.correlationOption,
    dependency: s.dependencyType,
    degrees: s.degreesOfFreedom,
    target: squareTargetMatrix(s.targetCorrelations, (s.segments || []).length),
  });
}

/* ---------------------------------------------------------------------------
   Segments
--------------------------------------------------------------------------- */

/* What the page knows about each included bootstrap, keyed by segmentKey:
   the rows the load or a run returned, and the picker's candidates. */
export function segmentInfoMap(...lists) {
  const map = new Map();
  for (const list of lists) {
    for (const row of Array.isArray(list) ? list : []) {
      if (!row) continue;
      const current = map.get(segmentKey(row)) || {};
      map.set(segmentKey(row), { ...current, ...row });
    }
  }
  return map;
}

const STATUS_NOTES = Object.freeze({
  changed: "Changed since the last run.",
  not_consolidated: "Not in the last run.",
});

/* One row per included segment, with its standalone figures and every reason
   it cannot be consolidated as it stands. The checks mirror the server's so a
   row added from the picker shows its problem before any run. */
export function segmentRows(settings, infoByKey, { hasRun = false } = {}) {
  const segments = settings?.segments || [];
  const base = key(settings?.baseTriangleType);
  const seen = new Set();
  let firstCount = null;
  let firstLabel = "";
  return segments.map((segment, index) => {
    const info = infoByKey?.get?.(segmentKey(segment)) || null;
    const issues = [];
    const identity = segmentKey(segment);
    if (seen.has(identity)) issues.push({ kind: "duplicate", text: "Included more than once." });
    seen.add(identity);
    const missing = !info || (Array.isArray(info.problems) && info.problems.includes("missing"));
    // A bootstrap that is not there has no simulation count to show.
    const count = missing ? null : numberOrNull(info?.simulation_count);
    if (missing) {
      issues.push({ kind: "missing", text: text(info?.error) || "Bootstrap not found." });
    } else {
      if (info.has_run === false) issues.push({ kind: "no_run", text: "The bootstrap has no saved run." });
      if (firstCount === null) {
        firstCount = count;
        firstLabel = segmentShortLabel(segment);
      } else if (count !== null && count !== firstCount) {
        issues.push({
          kind: "simulation_count_mismatch",
          text: `Runs ${count.toLocaleString()} simulations; ${firstLabel} runs ${firstCount.toLocaleString()}.`,
        });
      }
      const segmentBase = key(info.base_triangle_type);
      if (base && segmentBase && segmentBase !== base) {
        issues.push({
          kind: "base_type_mismatch",
          text: `Based on ${text(info.base_triangle_type)}, not ${text(settings.baseTriangleType)}.`,
        });
      }
    }
    const status = text(info?.status);
    const note = hasRun && STATUS_NOTES[status] ? STATUS_NOTES[status] : "";
    return {
      index,
      projectName: segmentProject(segment),
      reservingClass: segment.reservingClass,
      methodName: segment.methodName,
      shortLabel: segmentShortLabel(segment),
      factor: numberOrNull(segment.factor) ?? 1,
      simulationCount: count,
      baseTriangleType: text(info?.base_triangle_type),
      mean: numberOrNull(info?.mean),
      sd: numberOrNull(info?.standard_error),
      cv: numberOrNull(info?.cv),
      status,
      note,
      issues,
    };
  });
}

/* The simulation count the segments agree on, or why there is none. */
export function commonSimulationCount(rows) {
  const counts = Array.from(new Set((rows || []).map((row) => row.simulationCount).filter((n) => n !== null)));
  if (!counts.length) return { count: null, text: "" };
  if (counts.length > 1) return { count: null, text: "Segments disagree" };
  return { count: counts[0], text: counts[0].toLocaleString() };
}

/* The base triangle types a user can choose: the one stored and every one the
   segments' DFMs are built on. */
export function baseTypeChoices(settings, infoByKey) {
  const seen = new Map();
  const add = (value) => {
    const label = text(value);
    if (label && !seen.has(key(label))) seen.set(key(label), label);
  };
  add(settings?.baseTriangleType);
  for (const segment of settings?.segments || []) add(infoByKey?.get?.(segmentKey(segment))?.base_triangle_type);
  return [{ value: "", label: "(None)" }, ...Array.from(seen.values()).map((value) => ({ value, label: value }))];
}

/* Candidates a user can add: every bootstrap not already included. */
export function availableCandidates(candidates, settings) {
  const included = new Set((settings?.segments || []).map(segmentKey));
  return (Array.isArray(candidates) ? candidates : []).filter((row) => !included.has(segmentKey(row)));
}

/* ---------------------------------------------------------------------------
   Run state and results
--------------------------------------------------------------------------- */

/* The header chip. A run in flight wins; then whether a run is on screen at
   all, whether it was made from the settings on screen, and whether a segment
   bootstrap changed since it. */
export function consolidationRunState({ hasRun = false, settingsMatchRun = true, segmentChanged = false, running = false } = {}) {
  if (running) return { key: "running", label: "Consolidating" };
  if (!hasRun) return { key: "not-run", label: "Not run yet" };
  if (!settingsMatchRun) return { key: "changed", label: "Inputs changed — run again" };
  if (segmentChanged) return { key: "segment", label: "A segment changed" };
  return { key: "current", label: "Up to date" };
}

export function hasConsolidationRun(method) {
  return hasRangeRun(method);
}

/* The segment breakdown on the Results tab: each segment's standalone mean,
   standard deviation and CV, its share of the total mean, then the
   diversification the correlations give. It reads the stored run only, and
   names the segments the run was made from. */
export function segmentBreakdown(method) {
  const summary = rangeSummary(method);
  if (!summary) return null;
  const figures = Array.isArray(summary.segments) ? summary.segments : [];
  const segments = Array.isArray(tab(method, "segments_tab").segments) ? tab(method, "segments_tab").segments : [];
  if (!figures.length) return null;
  const rows = figures.map((figure, index) => {
    const segment = segments[index] || {};
    return {
      projectName: segmentProject(segment),
      reservingClass: text(segment.reserving_class),
      methodName: text(segment.method_name),
      shortLabel: segmentShortLabel(segment),
      factor: numberOrNull(figure?.factor),
      mean: numberOrNull(figure?.mean),
      sd: numberOrNull(figure?.standard_error),
      cv: numberOrNull(figure?.cv),
      share: numberOrNull(figure?.share_of_mean),
    };
  });
  const diversification = summary.diversification && typeof summary.diversification === "object"
    ? summary.diversification
    : {};
  const totalMean = numberOrNull(Array.isArray(summary.scaled?.mean) ? summary.scaled.mean[0] : null);
  const totalSd = numberOrNull(diversification.total_standard_error)
    ?? numberOrNull(Array.isArray(summary.scaled?.standard_error) ? summary.scaled.standard_error[0] : null);
  const standaloneSd = numberOrNull(diversification.sum_of_standalone_standard_errors);
  const benefit = numberOrNull(diversification.benefit)
    ?? (totalSd !== null && standaloneSd !== null ? standaloneSd - totalSd : null);
  return {
    rows,
    total: {
      mean: totalMean,
      sd: totalSd,
      cv: totalMean !== null && totalSd !== null && totalMean > 1e-9 ? totalSd / totalMean : null,
      share: rows.some((row) => row.share !== null) ? rows.reduce((sum, row) => sum + (row.share ?? 0), 0) : null,
    },
    standaloneSd,
    benefit,
    benefitRatio: standaloneSd ? (benefit ?? 0) / standaloneSd : null,
  };
}

/* The achieved correlations of the stored run, as two matrices. */
export function achievedMatrices(method) {
  const summary = rangeSummary(method);
  const read = (value) => (Array.isArray(value) ? value.map((row) => (Array.isArray(row) ? row.map(numberOrNull) : [])) : []);
  return {
    rank: read(summary?.achieved_rank_correlations),
    linear: read(summary?.achieved_linear_correlations),
  };
}

/* The adjusted matrix the stored run used. */
export function storedAdjustedMatrix(method) {
  const value = tab(method, "correlation_tab").adjusted_correlations;
  return Array.isArray(value) ? value.map((row) => (Array.isArray(row) ? row.map(numberOrNull) : [])) : [];
}
