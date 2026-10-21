/*
 * Shared Details "inputs and dependencies" surface.
 *
 * The Dataset Viewer and every method page show the same things in the second
 * Details section: the formula or pickers the output is computed from, and one
 * Data Flow map of the Precedents it reads and the Dependents that read it.
 * This module owns how those read - the plain-text formula, the map, the click
 * that opens a related dataset or method, and the button that opens the full
 * Dependency Graph - so no page can drift from another.
 *
 * Everything a host differs on is injected: which elements to fill, what the
 * output is called and which method publishes it, how to resolve a dataset
 * type's own formula, and how to report status. The module itself knows
 * nothing about any one page.
 */

import { createDetailsDependencyMap, requestDependencyGraph } from "./details_dependency_map.js?v=20261021c";

export const DETAILS_DEPENDENCY_CLASS_NAMES = Object.freeze({
  chipLabel: "arDetailsChipLabel",
  formulaBox: "arDetailsFormulaBox",
  formulaText: "arDetailsFormulaText",
  formulaOperator: "arDetailsFormulaOperator",
  formulaComponent: "arDetailsFormulaComponent",
});

const METHOD_TYPE_LABELS = Object.freeze({
  dfm: "DFM",
  "result selection": "Result Selection",
  "bornhuetter ferguson": "Bornhuetter Ferguson",
  "cape cod": "Cape Cod",
  bootstrap: "Bootstrap",
  "stochastic consolidation": "Stochastic Consolidation",
});

export function normalizeDependencyText(value) {
  return String(value || "").trim().replace(/\s+/gu, " ").toLowerCase();
}

/**
 * Flattens whatever the sidecar graph returned - names, or objects under either
 * the persisted snake_case keys or the camelCase ones a caller already mapped -
 * into one deduplicated shape.
 */
export function normalizeDependencyEntries(entries = []) {
  if (!Array.isArray(entries)) return [];
  const seen = new Set();
  return entries
    .map((entry) => {
      const source = entry && typeof entry === "object" ? entry : { dataset_type_name: entry };
      const datasetName = String(
        source.dataset_name
          ?? source.datasetName
          ?? source.dataset_type_name
          ?? source.datasetTypeName
          ?? source.name
          ?? "",
      ).trim();
      const datasetTypeName = String(
        source.dataset_type_name
          ?? source.datasetTypeName
          ?? source.dataset_type
          ?? source.datasetType
          ?? datasetName,
      ).trim();
      const name = datasetName || datasetTypeName;
      if (!name) return null;
      const key = normalizeDependencyText(name);
      if (seen.has(key)) return null;
      seen.add(key);
      return {
        datasetName: name,
        datasetTypeName: datasetTypeName || name,
        formula: String(source.formula ?? source.Formula ?? "").trim(),
        methodType: String(source.method_type ?? source.methodType ?? "").trim(),
      };
    })
    .filter(Boolean);
}

/**
 * Reads one dataset's dependency graph.
 *
 * Every Details tab asks the same route for the same reason, and the enriched
 * entries - the `formula` a hover shows and the `method_type` a click routes on
 * - are built by that route, not by the raw persisted sidecar. A page that
 * happens to hold a raw payload should still come through here.
 *
 * For a method page the dataset is the one the method publishes, not the method
 * itself: the graph is keyed by dataset name.
 */
export async function loadDetailsDependencies({
  projectName,
  reservingClass,
  datasetName,
  fetchImpl = globalThis.fetch,
} = {}) {
  const empty = { exists: false, formula: "", precedents: [], dependents: [] };
  const body = {
    project_name: String(projectName || "").trim(),
    reserving_class: String(reservingClass || "").trim(),
    dataset_name: String(datasetName || "").trim(),
  };
  if (!body.project_name || !body.reserving_class || !body.dataset_name) return empty;

  const response = await fetchImpl("/dataset/sidecar/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false || !payload?.exists) return empty;
  return {
    exists: true,
    formula: String(payload.formula || "").trim(),
    precedents: normalizeDependencyEntries(payload.precedents),
    dependents: normalizeDependencyEntries(payload.dependents),
  };
}

function escapeFormulaRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

/**
 * The names a formula may refer to, longest first so "Paid Loss Ratio" wins over
 * "Paid Loss".
 */
export function formulaComponentNames(precedents = [], extraNames = []) {
  const names = [];
  const seen = new Set();
  const add = (value) => {
    const text = String(value || "").trim();
    const key = normalizeDependencyText(text);
    if (!text || !key || seen.has(key)) return;
    seen.add(key);
    names.push(text);
  };
  for (const entry of normalizeDependencyEntries(precedents)) {
    add(entry.datasetName);
    add(entry.datasetTypeName);
  }
  for (const name of extraNames || []) add(name);
  return names.sort((a, b) => b.length - a.length);
}

function findFormulaComponentMatches(formula, names) {
  const text = String(formula || "");
  if (!text.trim()) return [];
  const matches = [];

  // A quoted name is authoritative: it is what the author wrote, and it can
  // hold characters the name matcher below would treat as operators.
  const quotedRe = /"([^"]+)"/gu;
  let quotedMatch;
  while ((quotedMatch = quotedRe.exec(text)) !== null) {
    const token = String(quotedMatch[1] || "").trim();
    if (!token) continue;
    matches.push({
      start: quotedMatch.index,
      end: quotedMatch.index + String(quotedMatch[0] || "").length,
      token,
    });
  }

  for (const name of names || []) {
    const re = new RegExp(`(^|[^A-Za-z0-9_])(${escapeFormulaRegExp(name)})(?=$|[^A-Za-z0-9_])`, "giu");
    let match;
    while ((match = re.exec(text)) !== null) {
      const prefixLen = String(match[1] || "").length;
      const token = String(match[2] || "").trim();
      const start = match.index + prefixLen;
      if (token) matches.push({ start, end: start + token.length, token });
      if (re.lastIndex === match.index) re.lastIndex += 1;
    }
  }

  matches.sort((a, b) => (a.start - b.start) || ((b.end - b.start) - (a.end - a.start)));
  const used = [];
  const out = [];
  for (const hit of matches) {
    if (used.some((range) => hit.start < range.end && hit.end > range.start)) continue;
    if (!normalizeDependencyText(hit.token)) continue;
    used.push({ start: hit.start, end: hit.end });
    out.push(hit);
  }
  return out.sort((a, b) => a.start - b.start);
}

function pushOperatorTokens(out, text) {
  const segment = String(text || "");
  if (!segment) return;
  const operatorRe = /[+\-*/()]/gu;
  let cursor = 0;
  let match;
  while ((match = operatorRe.exec(segment)) !== null) {
    const before = segment.slice(cursor, match.index).trim();
    if (before) out.push({ type: "text", value: before });
    out.push({ type: "operator", value: match[0] });
    cursor = match.index + match[0].length;
  }
  const tail = segment.slice(cursor).trim();
  if (tail) out.push({ type: "text", value: tail });
}

/**
 * Splits a formula into the parts every ArcRho surface shows it as: the dataset
 * names it refers to, the operators between them, and any leftover text.
 *
 * `names` is what makes an unquoted name resolve. With none of them matched the
 * formula is returned as a single text token rather than split on `+-*\/()`,
 * because those characters occur *inside* dataset names - "C 22 - CWOP DFM w/
 * Selected LDFs" is three operators and a fragment to a splitter that does not
 * know it is one name.
 */
export function tokenizeDetailsFormula(formula, names = []) {
  const text = String(formula || "").trim();
  if (!text) return [];
  const matches = findFormulaComponentMatches(text, names);
  if (!matches.length) return [{ type: "text", value: text }];

  const out = [];
  let cursor = 0;
  for (const hit of matches) {
    if (hit.start > cursor) pushOperatorTokens(out, text.slice(cursor, hit.start));
    out.push({ type: "component", value: hit.token });
    cursor = hit.end;
  }
  if (cursor < text.length) pushOperatorTokens(out, text.slice(cursor));
  return out;
}

/**
 * One canonical display string for a formula, used by the Dataset Viewer
 * Details tab, the Project Settings Dataset Types table, and the Project
 * Instance dataset table so the same formula never reads three ways.
 *
 * Names are quoted whether or not the stored text quoted them: a dataset name
 * contains spaces, so unquoted it runs into the operators beside it. The stored
 * text itself is never rewritten - this is presentation only.
 */
export function formatDetailsFormulaText(formula, names = []) {
  const tokens = tokenizeDetailsFormula(formula, names);
  if (!tokens.length) return "";
  if (tokens.length === 1 && tokens[0].type === "text") return tokens[0].value;
  return tokens
    .map((token) => (token.type === "component" ? `"${token.value}"` : token.value))
    .join(" ");
}

export function createDetailsDependenciesView({
  formulaBox = null,
  dependencyMap = null,
  getSelfName = () => "",
  getSelfMethodType = () => "",
  getDatasetTypeFormula = () => "",
  getExtraComponentNames = () => [],
  getBerquistShermanContract = () => null,
  getContext = () => ({}),
  instanceId = "",
  isProjectInstanceHost = false,
  setStatus = () => {},
  documentRef = globalThis.document,
  windowRef = globalThis.window,
} = {}) {
  const doc = documentRef;
  const win = windowRef;

  function resolveElement(target) {
    if (!target) return null;
    if (typeof target === "string") return doc?.getElementById?.(target) || null;
    return target;
  }

  // A related dataset whose sidecar entry carries no formula may still be
  // calculated by its Dataset Type, which is what its box is labelled by.
  function entryFormula(entry) {
    const datasetTypeName = String(entry?.datasetTypeName || entry?.datasetName || "").trim();
    return String(entry?.formula || getDatasetTypeFormula(datasetTypeName) || "").trim();
  }

  // Routing keeps the canonical method type; only the labels a user reads use
  // the ResQ wording.
  function normalizeMethodType(value) {
    const text = normalizeDependencyText(value);
    if (METHOD_TYPE_LABELS[text]) return METHOD_TYPE_LABELS[text];
    return getBerquistShermanContract(text)?.methodType || "";
  }

  function appendChipLabel(parent, text) {
    const label = doc.createElement("span");
    label.className = DETAILS_DEPENDENCY_CLASS_NAMES.chipLabel;
    label.textContent = text;
    parent.appendChild(label);
  }

  function appendFormulaText(parent, text) {
    const value = String(text || "").trim();
    if (!value || !parent) return;
    const span = doc.createElement("span");
    span.className = DETAILS_DEPENDENCY_CLASS_NAMES.formulaText;
    span.textContent = value;
    parent.appendChild(span);
  }

  // Operators read as the characters the user typed. The box lays its parts out
  // with a gap, so a literal `+` still separates two names without a token
  // shape around it.
  function appendFormulaOperator(parent, value) {
    const op = String(value || "").trim();
    if (!op || !parent) return;
    const span = doc.createElement("span");
    span.className = DETAILS_DEPENDENCY_CLASS_NAMES.formulaOperator;
    span.textContent = op;
    parent.appendChild(span);
  }

  // A formula component is the name the user wrote, so it reads as text. Opening
  // the dataset it refers to belongs to the Data Flow map directly below,
  // which shows the same sources as boxes; a second, differently-shaped way in
  // would only make the expression harder to read.
  //
  // The quotes are always drawn, whether or not the source text carried them:
  // a dataset name contains spaces, so unquoted it runs into the operators
  // beside it and a two-word name reads as two operands.
  function appendFormulaComponent(parent, label) {
    const component = doc.createElement("span");
    component.className = DETAILS_DEPENDENCY_CLASS_NAMES.formulaComponent;
    appendChipLabel(component, `"${String(label ?? "").trim()}"`);
    parent.appendChild(component);
  }

  // Painting walks the same tokens `formatDetailsFormulaText` joins, so what the
  // Formula field shows and what the Project Settings and Project Instance
  // tables print are the same string by construction.
  function renderFormulaTokens(parent, formula, precedents = []) {
    if (!parent) return;
    const names = formulaComponentNames(precedents, getExtraComponentNames());
    for (const token of tokenizeDetailsFormula(formula, names)) {
      if (token.type === "component") appendFormulaComponent(parent, token.value);
      else if (token.type === "operator") appendFormulaOperator(parent, token.value);
      else appendFormulaText(parent, token.value);
    }
  }

  function openRelated(entry, options = {}) {
    const datasetName = String(entry?.datasetName || "").trim();
    if (!datasetName) return;
    if (!isProjectInstanceHost) {
      setStatus("Dataset links open from Project Instance windows.");
      return;
    }
    const context = getContext() || {};
    try {
      win.parent?.postMessage({
        type: "arcrho:project-instance-open-dependent-dataset",
        inst: instanceId,
        datasetName,
        datasetTypeName: String(entry?.datasetTypeName || datasetName).trim(),
        methodType: normalizeMethodType(entry?.methodType),
        openMethod: !!options.openMethod,
        projectName: String(context.projectName || "").trim(),
        reservingClass: String(context.reservingClass || "").trim(),
      }, "*");
      setStatus(options.openMethod
        ? `Opening related item: ${datasetName}`
        : `Opening dataset: ${datasetName}`);
    } catch {
      setStatus("Could not open dataset from this window.");
    }
  }

  // The full graph belongs to the Project Instance page, so the map's button
  // asks it to open the graph for this class with this output in focus.
  function openDependencyGraph() {
    try {
      requestDependencyGraph({
        windowRef: win,
        instanceId,
        reservingClass: (getContext() || {}).reservingClass,
        datasetName: getSelfName(),
      });
      setStatus("Opening Dependency Graph...");
    } catch {
      setStatus("Could not open the Dependency Graph from this window.");
    }
  }

  // The button is drawn only where there is a Project Instance page to ask.
  const mapContainer = resolveElement(dependencyMap);
  const map = mapContainer && createDetailsDependencyMap({
    container: mapContainer,
    canOpenGraph: isProjectInstanceHost,
    onOpenEntry: (entry) => openRelated(entry, { openMethod: true }),
    onOpenGraph: openDependencyGraph,
    documentRef: doc,
    windowRef: win,
  });
  const mapState = { formula: "", precedents: [], dependents: [], inputs: [] };
  const withFormula = (entries) => normalizeDependencyEntries(entries)
    .map((entry) => ({ ...entry, formula: entryFormula(entry) }));
  const entryKeys = (entry) => [entry.datasetName, entry.datasetTypeName].map(normalizeDependencyText);
  // Every name an input slot has held since the graph was last read. The
  // graph is the saved one, so a precedent that was an input and has since
  // been replaced must not stay on the map beside its replacement.
  let inputKeysSinceGraph = new Set();

  function slotEntries(slot) {
    return withFormula(slot.values || []).map((entry) => {
      const keys = entryKeys(entry);
      const saved = mapState.precedents.find((item) => entryKeys(item).some((key) => keys.includes(key)));
      return saved ? { ...saved, datasetName: entry.datasetName } : entry;
    });
  }

  function paintMap(changes) {
    Object.assign(mapState, changes);
    const inputs = mapState.inputs.map((slot) => ({ slot, values: slotEntries(slot) }));
    for (const { values } of inputs) {
      for (const entry of values) for (const key of entryKeys(entry)) inputKeysSinceGraph.add(key);
    }
    map?.render({
      self: { name: getSelfName(), formula: mapState.formula, methodType: getSelfMethodType() },
      inputs,
      precedents: mapState.precedents.filter((entry) => !entryKeys(entry).some((key) => inputKeysSinceGraph.has(key))),
      dependents: mapState.dependents,
    });
  }

  return {
    normalizeEntries: normalizeDependencyEntries,

    /**
     * Paints the formula field. `precedents` is what makes a bare name in the
     * text resolve to a dataset, so pass the same list the map got.
     */
    renderFormula(formula, precedents = []) {
      const box = resolveElement(formulaBox);
      if (!box) return null;
      const formulaText = String(formula || "").trim();
      box.replaceChildren();
      box.removeAttribute("title");
      box.classList.toggle("empty", !formulaText);
      paintMap({ formula: formulaText });
      if (!formulaText) return "";
      renderFormulaTokens(box, formulaText, precedents);
      return formulaText;
    },

    renderPrecedents(entries = []) {
      inputKeysSinceGraph = new Set();
      paintMap({ precedents: withFormula(entries) });
      return mapState.precedents;
    },

    renderDependents(entries = []) {
      paintMap({ dependents: withFormula(entries) });
      return mapState.dependents;
    },

    /**
     * Hands the map the method's input slots, so they are chosen on the map.
     * Each slot is { key, label, values, multiple, max, disabled, pick, remove }:
     * `values` the dataset names chosen now, `pick(anchor, { index })` opens
     * the page's picker, and `remove(index)`, when given, drops one value.
     * Call it again whenever a value changes.
     */
    renderInputs(slots = []) {
      paintMap({ inputs: Array.isArray(slots) ? slots : [] });
    },

    clear() {
      inputKeysSinceGraph = new Set();
      const box = resolveElement(formulaBox);
      if (box) {
        box.replaceChildren();
        box.classList.add("empty");
      }
      paintMap({ formula: "", precedents: [], dependents: [] });
    },
  };
}

/**
 * The whole Details dependency surface for one page: the view, the read, and
 * the guard against a stale read painting over a newer one.
 *
 * `refresh` is what a page calls after it loads or saves; `apply` is for a page
 * that already holds an enriched `/dataset/sidecar/load` payload and should not
 * pay for a second round trip.
 */
export function createDetailsDependenciesController({
  getIdentity = () => ({}),
  fetchImpl = globalThis.fetch,
  ...viewOptions
} = {}) {
  const view = createDetailsDependenciesView({
    // The map is centred on the dataset the graph is read for.
    getSelfName: () => (getIdentity() || {}).datasetName,
    ...viewOptions,
    getContext: () => {
      const identity = getIdentity() || {};
      return {
        projectName: identity.projectName,
        reservingClass: identity.reservingClass,
      };
    },
  });
  let sequence = 0;

  function paint(graph) {
    const precedents = graph?.precedents || [];
    view.renderPrecedents(precedents);
    view.renderDependents(graph?.dependents || []);
    view.renderFormula(graph?.formula || "", precedents);
    return graph;
  }

  return {
    view,

    apply(payload) {
      sequence += 1;
      return paint({
        formula: String(payload?.formula || "").trim(),
        precedents: normalizeDependencyEntries(payload?.precedents),
        dependents: normalizeDependencyEntries(payload?.dependents),
      });
    },

    clear() {
      sequence += 1;
      view.clear();
    },

    setInputs(slots) {
      view.renderInputs(slots);
    },

    async refresh() {
      const identity = getIdentity() || {};
      const requestSequence = ++sequence;
      let graph;
      try {
        graph = await loadDetailsDependencies({ ...identity, fetchImpl });
      } catch {
        // A page that cannot read its graph shows none rather than a stale one.
        graph = null;
      }
      if (requestSequence !== sequence) return null;
      if (!graph) {
        view.clear();
        return null;
      }
      return paint(graph);
    },
  };
}
