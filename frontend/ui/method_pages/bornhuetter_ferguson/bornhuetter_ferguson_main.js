import {
  ensureDatasetOriginLabels,
  formatDatasetOriginLabel,
  validateDatasetOriginLabels,
} from "/ui/shared/dataset/dataset_origin_labels.js";
import { statusNeedsReview } from "/ui/shared/dataset/review_status.js";
import { openDatasetNamePicker } from "/ui/shared/components/pickers/dataset_name_picker.js";
import {
  applyTabbedPageSaveBar,
  createTabbedPage,
  requestTabbedPageWindowClose,
  updateTabbedPageSaveControls,
} from "/ui/shared/tabbed_page/tabbed_page.js?v=20260913a";
import { wireTabPopoutWindows } from "/ui/shared/tabbed_page/tab_popout_window.js?v=20260722a";
import { mountNotesTab } from "/ui/shared/tabs/notes/notes_tab.js?v=20260911b";
import { syncDetailsLabelWidth } from "/ui/shared/tabs/details/details_form_layout.js?v=20260820b";
import { createDetailsDependenciesController } from "/ui/shared/tabs/details/details_dependencies.js?v=20261021c";
import { applyHostFixedDetailsFields } from "/ui/shared/tabs/details/details_host_fields.js?v=20260820b";
import { createAuditLogView } from "/ui/shared/tabs/audit_log/audit_log_view.js?v=20260714c";
import {
  formatSidecarAuditEventDate,
  normalizeSidecarAuditEntries,
} from "/ui/shared/tabs/audit_log/sidecar_audit_entries.js?v=20260714c";
import { createBornhuetterFergusonChart } from "/ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_chart.js?v=20260722a";
import { createPageCloseConfirm } from "/ui/shared/components/close_confirm/close_confirm.js";
import { showMethodSaveReviewWarning } from "/ui/shared/components/message_box/method_save_review_warning.js?v=20260925a";
import { showPageMessageBox } from "/ui/shared/components/message_box/message_box.js?v=20260925a";
import { createArcRhoSaveProgress, showSavedDependentsNotice } from "/ui/shared/components/progress_popup/save_progress.js?v=20261004lock1";
import {
  isEngineUnavailableSaveError,
  trackSavePropagation,
} from "/ui/shared/services/dependent_propagation_job.js?v=20260813e";
import {
  createMethodObjectChangeWatchController,
  showObjectUpdatedAlert,
  wireSamePropagationScopePause,
} from "/ui/shared/services/object_change_watch.js?v=20260927c";
import { createSpreadsheetTableController } from "/ui/shared/components/spreadsheet/spreadsheet_table.js?v=20260712c";
import { readProjectInstanceDatasetSnapshot } from "/ui/shared/dataset/project_instance_dataset_snapshot.js?v=20260725a";
import {
  BORN_HUETTER_FERGUSON_METHOD_TYPE,
  buildBornhuetterFergusonMethodPayload,
  isBornhuetterFergusonV3Method,
  rebaseBornhuetterFergusonWeightsByOriginLabel,
  roundBornhuetterFergusonNumber,
} from "/ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_json_contract.js?v=20260903a";
import {
  loadBornhuetterFergusonMethod,
  saveBornhuetterFergusonMethod,
} from "/ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_method_api.js?v=20260814b";
import {
  BORNHUETTER_FERGUSON_TAB_DEFS,
  windowTabIds,
} from "/ui/shared/tabs/window_tab_catalog.js?v=20260903a";
import { bootTableColors } from "/ui/shared/components/spreadsheet/table_colors.js?v=20260927b";

// The user's table colours, shared by every method page.
bootTableColors();

const BF_METHOD_TYPE = BORN_HUETTER_FERGUSON_METHOD_TYPE;
const DEFAULT_ORIGIN_LENGTH = 12;
const VALID_ORIGIN_LENGTHS = [12, 6, 3, 1];
const BF_TABS = BORNHUETTER_FERGUSON_TAB_DEFS;
const ALLOWED_BF_TABS = windowTabIds("bornhuetter_ferguson");

const params = new URLSearchParams(window.location.search || "");
const inst = text(params.get("inst")) || `bf_${Date.now()}`;

const state = {
  project: text(params.get("project")),
  reservingClass: text(params.get("class") || params.get("path")),
  cachedRows: [],
  originLabels: [],
  sidecarOriginLabels: [],
  latestValues: [],
  dfmUltimateValues: [],
  priorSources: [],
  selectedPriorValues: [],
  percentDevelopedValues: [],
  newUltimateValues: [],
  showWeights: true,
  showEffectiveWeights: false,
  statisticDecimalPlaces: 1,
  datasetCategory: text(params.get("category")),
  methodMetadata: {},
  ownedRevision: "",
  derivedRevision: "",
  publicationRevision: "",
  methodLastModified: new Date().toISOString(),
  methodHighlight: null,
  methodHighlightDragging: false,
  weightEditSession: null,
  needsReview: false,
};

let cleanSnapshot = "";
let isDirty = false;
let programmatic = false;
let tabbedPage = null;
let bfChart = null;
let aggregateLoadSequence = 0;
const bfCloseConfirm = createPageCloseConfirm({ subject: BF_METHOD_TYPE });
// Open-window change alert (advisory): fires once when another user or the
// dependent-propagation job rewrites this method while it is open.
const bfObjectChangeWatch = createMethodObjectChangeWatchController({
  methodType: "bornhuetter_ferguson",
  onChange: (attribution) => {
    void showObjectUpdatedAlert({
      showMessageBox: showPageMessageBox,
      attribution,
      isDirty: () => isDirty,
      onBlockedRefresh: () => {
        postStatus("Unsaved changes block the refresh. Save or discard them, then reopen the window.", "warn");
      },
    });
  },
});
wireSamePropagationScopePause({
  watch: bfObjectChangeWatch,
  getProject: () => state.project,
  getReservingClass: () => state.reservingClass,
});
const activeDependencyPreviews = new Map();
const bfNotesController = mountNotesTab({
  container: document.getElementById("bfNotesMount"),
  ariaLabel: "Bornhuetter Ferguson notes",
  onChange: () => markDirty(),
  onStatus: postStatus,
});

const els = {
  title: document.getElementById("bfTitle"),
  subtitle: document.getElementById("bfSubtitle"),
  projectInput: document.getElementById("bfProjectInput"),
  classInput: document.getElementById("bfClassInput"),
  nameInput: document.getElementById("bfNameInput"),
  outputTypeInput: document.getElementById("bfOutputTypeInput"),
  outputTypeBtn: document.getElementById("bfOutputTypeBtn"),
  originLengthInput: document.getElementById("bfOriginLengthInput"),
  originLengthDropdown: document.getElementById("bfOriginLengthDropdown"),
  originLengthButton: document.getElementById("bfOriginLengthButton"),
  originLengthLabel: document.getElementById("bfOriginLengthLabel"),
  originLengthMenu: document.getElementById("bfOriginLengthMenu"),
  latestInput: document.getElementById("bfLatestInput"),
  dfmInput: document.getElementById("bfDfmInput"),
  showWeightsInput: document.getElementById("bfShowWeightsInput"),
  weightDisplayDropdown: document.getElementById("bfWeightDisplayDropdown"),
  weightDisplayButton: document.getElementById("bfWeightDisplayButton"),
  weightDisplayLabel: document.getElementById("bfWeightDisplayLabel"),
  weightDisplayMenu: document.getElementById("bfWeightDisplayMenu"),
  methodDecimalsInput: document.getElementById("bfMethodDecimalsInput"),
  methodDecimalsUp: document.getElementById("bfMethodDecimalsUp"),
  methodDecimalsDown: document.getElementById("bfMethodDecimalsDown"),
  methodTable: document.querySelector(".bfMethodTable"),
  methodCols: document.getElementById("bfMethodCols"),
  methodHead: document.getElementById("bfMethodHead"),
  methodGrid: document.getElementById("bfMethodGrid"),
  chartCanvas: document.getElementById("bfChartCanvas"),
  chartLegend: document.getElementById("bfChartLegend"),
  chartEmpty: document.getElementById("bfChartEmpty"),
  chartTooltip: document.getElementById("bfChartTooltip"),
  cellContextMenu: document.getElementById("bfCellContextMenu"),
  auditLogMount: document.getElementById("bfAuditLogMount"),
  notesInput: bfNotesController.elements.input,
  saveBtn: document.getElementById("bfSaveBtn"),
  cancelBtn: document.getElementById("bfCancelBtn"),
};

const auditLogView = createAuditLogView({
  container: els.auditLogMount,
  ariaLabel: "Bornhuetter Ferguson audit log",
  emptyDescription: "Method saves will appear here after the first save.",
  normalizeEntries: normalizeSidecarAuditEntries,
  formatEventDate: formatSidecarAuditEventDate,
});

const methodSpreadsheetTable = createSpreadsheetTableController({
  getRoot: () => els.methodTable,
  getBounds: () => ({
    maxRow: rowCount(),
    maxCol: methodColumnCount() - 1,
  }),
  readSelection: () => {
    const highlight = state.methodHighlight;
    if (!highlight) return { ranges: [], activeCell: null, anchorCell: null };
    return {
      ranges: [{
        r0: highlight.startRow,
        r1: highlight.endRow,
        c0: highlight.startCol,
        c1: highlight.endCol,
      }],
      activeCell: { r: highlight.endRow, c: highlight.endCol },
      anchorCell: { r: highlight.startRow, c: highlight.startCol },
    };
  },
  writeSelection: ({ ranges, activeCell, anchorCell }) => {
    const range = ranges[0];
    if (!range) {
      state.methodHighlight = null;
      return;
    }
    let anchor = anchorCell || { r: range.r0, c: range.c0 };
    let active = activeCell || { r: range.r1, c: range.c1 };
    const directionalRange = {
      r0: Math.min(anchor.r, active.r),
      r1: Math.max(anchor.r, active.r),
      c0: Math.min(anchor.c, active.c),
      c1: Math.max(anchor.c, active.c),
    };
    if (
      directionalRange.r0 !== range.r0
      || directionalRange.r1 !== range.r1
      || directionalRange.c0 !== range.c0
      || directionalRange.c1 !== range.c1
    ) {
      anchor = { r: range.r0, c: range.c0 };
      active = { r: range.r1, c: range.c1 };
    }
    state.methodHighlight = {
      startCol: anchor.c,
      startRow: anchor.r,
      endCol: active.c,
      endRow: active.r,
    };
  },
  cellSelector: "td.bfMethodCell[data-row-index][data-col-index]",
  rowHeaderSelector: "td.bfOriginCell[data-row-index]",
  columnHeaderSelector: "thead th[data-col-index]",
  getCellPosition: (cell) => ({
    r: Number(cell?.dataset?.rowIndex),
    c: Number(cell?.dataset?.colIndex),
  }),
  getRowHeaderIndex: (header) => Number(header?.dataset?.rowIndex),
  getColumnHeaderIndex: (header) => Number(header?.dataset?.colIndex),
  selectedClasses: ["bfHighlightedCell"],
  anchorClasses: ["bfHighlightAnchorCell", "arSpreadsheetSelectionAnchor"],
  rowSelectedLabelClasses: ["bfHighlightedRowLabel", "arSpreadsheetSelectedLabel"],
  columnSelectedLabelClasses: ["bfHighlightedColumnLabel", "arSpreadsheetSelectedLabel"],
  getCellValue: (_position, cell) => cell?.dataset?.copyValue || "",
  onAfterCopy: () => postStatus("Copied selected Bornhuetter Ferguson values."),
  scrollCellIntoView: scrollMethodCellIntoView,
});

function text(value) {
  return String(value ?? "").trim();
}

function norm(value) {
  return text(value).replace(/\s+/g, " ").toLowerCase();
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function validOriginLength(value, fallback = DEFAULT_ORIGIN_LENGTH) {
  const n = Number.parseInt(String(value ?? ""), 10);
  return VALID_ORIGIN_LENGTHS.includes(n) ? n : fallback;
}

function statisticDecimalPlaces(value, fallback = 1) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(8, parsed));
}

function getDetails() {
  return {
    name: text(els.nameInput?.value),
    outputType: text(els.outputTypeInput?.value),
    datasetCategory: state.datasetCategory,
    originLength: validOriginLength(els.originLengthInput?.value),
    latestDataset: text(els.latestInput?.value),
    dfmDataset: text(els.dfmInput?.value),
    priorDatasets: state.priorSources.map((source) => source.name).filter(Boolean),
    showWeights: state.showWeights,
    statisticDecimalPlaces: state.statisticDecimalPlaces,
  };
}

let detailsDependencies = null;

function getDetailsDependencies() {
  if (!detailsDependencies) {
    detailsDependencies = createDetailsDependenciesController({
      dependencyMap: "bfDependencyMap",
      getSelfMethodType: () => "Bornhuetter Ferguson",
      // The graph is keyed by the dataset this method publishes, not the method.
      getIdentity: () => ({
        projectName: state.project,
        reservingClass: state.reservingClass,
        datasetName: getDetails().name,
      }),
      instanceId: inst,
      isProjectInstanceHost: window.parent !== window,
      setStatus: (message) => postStatus(message),
    });
  }
  return detailsDependencies;
}

function refreshDetailsDependencies() {
  return getDetailsDependencies().refresh().catch(() => null);
}

function withProgrammatic(fn) {
  programmatic = true;
  try {
    return fn();
  } finally {
    programmatic = false;
  }
}

function postStatus(message, tone = "") {
  const msg = text(message);
  try {
    window.parent?.postMessage({ type: "arcrho:status", text: msg, ...(tone ? { tone } : {}) }, "*");
  } catch {}
}

function syncSaveControls() {
  updateTabbedPageSaveControls({
    saveButton: els.saveBtn,
    cancelButton: els.cancelBtn,
    dirty: isDirty,
    needsReview: state.needsReview,
  });
}

// The Needs Review flag decides whether Save stays available while the window
// is clean, so a change to it has to reach the save bar.
function setNeedsReview(value) {
  const next = !!value;
  if (state.needsReview === next) return;
  state.needsReview = next;
  syncSaveControls();
}

function postDirty(dirty, force = false) {
  const next = !!dirty;
  if (!force && isDirty === next) return;
  isDirty = next;
  syncSaveControls();
  try {
    window.parent?.postMessage({ type: "arcrho:dataset-dirty", inst, dirty: next }, "*");
  } catch {}
}

function markDirty() {
  if (programmatic) return;
  postDirty(snapshotPayload() !== cleanSnapshot);
}

function syncTitles() {
  const details = getDetails();
  const title = details.name ? `${details.name} - ${BF_METHOD_TYPE}` : BF_METHOD_TYPE;
  document.title = title;
  if (els.title) els.title.textContent = title;
  if (els.subtitle) els.subtitle.textContent = [state.project, state.reservingClass].filter(Boolean).join(" / ");
  renderInputSlots();
}

function displayNumber(value, decimals = 0) {
  const n = numberOrNull(value);
  if (n === null) return "";
  return n.toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

function displayPercent(value) {
  const n = numberOrNull(value);
  if (n === null) return "";
  return `${(n * 100).toLocaleString(undefined, {
    maximumFractionDigits: state.statisticDecimalPlaces,
    minimumFractionDigits: state.statisticDecimalPlaces,
  })}%`;
}

function csvBaseName(value) {
  return text(value).split(/[\\/]/).pop();
}

function normalizeCachedRow(row) {
  const rawName = text(row?.datasetName || row?.dataset_name || row?.name || row?.datasetTypeName || row?.dataset_type);
  const name = rawName;
  return {
    ...row,
    name,
    datasetName: name,
    datasetType: text(row?.datasetTypeName || row?.dataset_type || row?.datasetType || name),
    dataFormat: text(row?.dataFormat || row?.data_format || row?.meta?.dataFormat),
    methodType: text(row?.methodType || row?.method_type || row?.meta?.methodType),
    sourceKind: text(row?.sourceKind || row?.source_kind || row?.meta?.sourceKind),
    category: text(row?.category || row?.dataset_category || row?.meta?.category),
    csvFile: text(row?.csvFile || row?.csv_file || row?.meta?.csvFile || csvBaseName(row?.path)),
    originLength: validOriginLength(row?.meta?.originLength ?? row?.originLength ?? row?.origin_length, 0),
  };
}

async function loadCachedRows(force = false) {
  if (!state.project || !state.reservingClass) return [];
  const sharedPayload = !force && params.get("project_instance") === "1"
    ? readProjectInstanceDatasetSnapshot(state.project, state.reservingClass)
    : null;
  if (sharedPayload) {
    state.cachedRows = sharedPayload.files.map(normalizeCachedRow).filter((row) => row.name);
    return state.cachedRows;
  }
  const qs = new URLSearchParams({
    project_name: state.project,
    reserving_class: state.reservingClass,
  });
  if (force) qs.set("refresh", "1");
  const resp = await fetch(`/datasets/cached?${qs.toString()}`, { cache: "no-store" });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload?.ok === false) throw new Error(payload?.detail || payload?.error || `Dataset cache failed (${resp.status}).`);
  const rows = Array.isArray(payload?.files)
    ? payload.files
    : Array.isArray(payload?.rows)
      ? payload.rows
      : Array.isArray(payload?.items)
        ? payload.items
        : Array.isArray(payload?.datasets)
          ? payload.datasets
          : [];
  state.cachedRows = rows.map(normalizeCachedRow).filter((row) => row.name);
  return state.cachedRows;
}

function cachedRecordByName(name) {
  const key = norm(name);
  return state.cachedRows.find((row) => norm(row.name) === key || norm(row.datasetType) === key) || null;
}

async function loadDatasetValues(datasetName, options = {}) {
  const name = text(datasetName);
  if (!state.project || !state.reservingClass || !name) throw new Error("Missing project, reserving class, or dataset name.");
  const body = {
    project_name: state.project,
    reserving_class: state.reservingClass,
    dataset_name: name,
  };
  const csvFile = text(options.csvFile || options.csv_file);
  const originLength = validOriginLength(options.originLength ?? options.origin_length, 0);
  const developmentLength = validOriginLength(options.developmentLength ?? options.development_length, 0);
  if (csvFile) body.csv_file = csvFile;
  if (originLength && developmentLength) {
    body.origin_length = originLength;
    body.development_length = developmentLength;
    body.cumulative = options.cumulative !== false;
    body.calendar = !!options.calendar;
  }
  const resp = await fetch("/dataset/cache/load", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload?.ok === false) throw new Error(payload?.detail || payload?.error || `Dataset load failed (${resp.status}).`);
  return payload;
}

async function loadConfiguredSourcePayload(datasetName, details = getDetails()) {
  const record = cachedRecordByName(datasetName);
  return loadDatasetValues(datasetName, {
    csvFile: record?.csvFile,
    originLength: record?.originLength || details.originLength,
    developmentLength: record?.originLength || details.originLength,
    cumulative: true,
    calendar: false,
  });
}

async function loadDevelopmentPattern(datasetName) {
  // The percentage developed comes from the DFM's selected development factors.
  // Reading it here keeps the BF grid showing the same figure the DFM's
  // % Developed row shows, and the same one a save embeds.
  const name = text(datasetName);
  if (!state.project || !state.reservingClass || !name) return [];
  const qs = new URLSearchParams({
    project_name: state.project,
    reserving_class: state.reservingClass,
    dataset_name: name,
  });
  const resp = await fetch(`/dfm/development-pattern?${qs.toString()}`, { cache: "no-store" });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload?.ok === false) {
    throw new Error(payload?.detail || payload?.error || `Development pattern load failed (${resp.status}).`);
  }
  return Array.isArray(payload?.percentage_developed)
    ? payload.percentage_developed.map(numberOrNull)
    : [];
}

function latestDiagonal(values) {
  const rows = Array.isArray(values) ? values : [];
  return rows.map((row) => {
    const cells = Array.isArray(row) ? row : [row];
    for (let i = cells.length - 1; i >= 0; i -= 1) {
      const n = numberOrNull(cells[i]);
      if (n !== null) return n;
    }
    return null;
  });
}

function vectorValues(values) {
  const rows = Array.isArray(values) ? values : [];
  return rows.map((row) => {
    if (Array.isArray(row)) return numberOrNull(row[0]);
    return numberOrNull(row);
  });
}

function sourceRowCount() {
  const priorValueCount = state.priorSources.reduce((max, source) => Math.max(max, source.values?.length || 0), 0);
  return Math.max(
    state.latestValues.length,
    state.dfmUltimateValues.length,
    priorValueCount,
  );
}

function rowCount() {
  return Math.max(
    state.originLabels.length,
    sourceRowCount(),
    1,
  );
}

function normalizePriorWeights(weights, count, fallback = 1) {
  const source = Array.isArray(weights) ? weights : [];
  return Array.from({ length: count }, (_, index) => Math.max(0, numberOrNull(source[index]) ?? fallback));
}

function normalizePriorSource(raw, count = rowCount()) {
  const source = raw && typeof raw === "object" ? raw : {};
  return {
    name: text(source.name || source.dataset_name || source.dataset),
    values: Array.isArray(source.values) ? source.values.map(numberOrNull) : [],
    weights: normalizePriorWeights(source.weights, count, 1),
  };
}

function normalizedReservingClassPath(value) {
  return text(value).replace(/\\+/g, "\\").toLowerCase();
}

function dependencyMessageNames(message = {}) {
  return new Set([
    ...(Array.isArray(message.names) ? message.names : []),
    message.datasetName,
    message.datasetTypeName,
    message.name,
  ].map(norm).filter(Boolean));
}

function dependencyMessageMatchesContext(message = {}) {
  if (!message || typeof message !== "object") return false;
  if (text(message.inst) && text(message.inst) === inst) return false;
  const project = text(message.project || message.project_name);
  if (project && norm(project) !== norm(state.project)) return false;
  const reservingClass = text(message.reservingClass || message.reserving_class);
  if (reservingClass && normalizedReservingClassPath(reservingClass) !== normalizedReservingClassPath(state.reservingClass)) return false;
  return true;
}

function dependencyRolesMatchingMessage(message = {}) {
  if (!dependencyMessageMatchesContext(message)) return [];
  const names = dependencyMessageNames(message);
  if (!names.size) return [];
  const details = getDetails();
  const roles = [];
  if (details.latestDataset && names.has(norm(details.latestDataset))) {
    roles.push({ key: "latest", kind: "latest", name: details.latestDataset });
  }
  if (details.dfmDataset && names.has(norm(details.dfmDataset))) {
    roles.push({ key: "dfm", kind: "dfm", name: details.dfmDataset });
  }
  for (const source of state.priorSources) {
    if (!source?.name || !names.has(norm(source.name))) continue;
    roles.push({ key: `prior:${norm(source.name)}`, kind: "prior", name: source.name });
  }
  return roles;
}

function dependencyPreviewValues(message = {}) {
  if (Array.isArray(message.values)) return message.values.map(numberOrNull);
  const matrix = Array.isArray(message.matrixValues)
    ? message.matrixValues
    : (Array.isArray(message.matrix_values) ? message.matrix_values : []);
  if (!matrix.length) return [];
  return norm(message.dataFormat || message.data_format) === "triangle"
    ? latestDiagonal(matrix)
    : vectorValues(matrix);
}

function applyDependencyValuesToRole(role, values, message = {}) {
  const normalizedValues = Array.isArray(values) ? values.map(numberOrNull) : [];
  if (role.kind === "latest") {
    state.latestValues = normalizedValues;
    return true;
  }
  if (role.kind === "dfm") {
    state.dfmUltimateValues = normalizedValues;
    const pattern = message.percentageDeveloped || message.percentage_developed;
    if (Array.isArray(pattern)) state.percentDevelopedValues = pattern.map(numberOrNull);
    return true;
  }
  if (role.kind === "prior") {
    const source = state.priorSources.find((item) => norm(item.name) === norm(role.name));
    if (!source) return false;
    source.values = normalizedValues;
    source.weights = normalizePriorWeights(source.weights, Math.max(normalizedValues.length, rowCount()), 1);
    return true;
  }
  return false;
}

function reapplyActiveDependencyPreviews() {
  let changed = false;
  for (const [roleKey, preview] of Array.from(activeDependencyPreviews.entries())) {
    const role = dependencyRolesMatchingMessage(preview.message).find((item) => item.key === roleKey);
    if (!role) {
      activeDependencyPreviews.delete(roleKey);
      continue;
    }
    changed = applyDependencyValuesToRole(role, preview.values, preview.message) || changed;
  }
  return changed;
}

function applyDependencySourcePreview(message = {}) {
  const roles = dependencyRolesMatchingMessage(message);
  const values = dependencyPreviewValues(message);
  if (!roles.length || !values.length) return false;
  let changed = false;
  for (const role of roles) {
    activeDependencyPreviews.set(role.key, { message: { ...message }, values: values.slice() });
    changed = applyDependencyValuesToRole(role, values, message) || changed;
  }
  if (!changed) return false;
  calculateOutputs();
  renderMethodGrid();
  return true;
}

async function clearDependencySourcePreview(message = {}) {
  const roles = dependencyRolesMatchingMessage(message)
    .filter((role) => activeDependencyPreviews.has(role.key));
  if (!roles.length) return false;
  for (const role of roles) activeDependencyPreviews.delete(role.key);
  return reloadPersistedBornhuetterFerguson({ preserveOwnedState: isDirty });
}

// The inputs are chosen on the Details Data Flow map.
function renderInputSlots() {
  getDetailsDependencies().setInputs([
    {
      key: "latest",
      label: "Latest",
      values: [text(els.latestInput?.value)].filter(Boolean),
      pick: (anchor) => openPicker("latest", anchor),
    },
    {
      key: "dfm",
      label: "Development Pattern",
      values: [text(els.dfmInput?.value)].filter(Boolean),
      pick: (anchor) => openPicker("dfm", anchor),
    },
    {
      key: "prior",
      label: "Prior Vector",
      multiple: true,
      values: state.priorSources.map((source) => source.name),
      pick: (anchor) => openPicker("prior", anchor),
      remove: (index) => removePriorSource(index),
    },
  ]);
}

function addPriorSource(name) {
  const clean = text(name);
  if (!clean || state.priorSources.some((source) => norm(source.name) === norm(clean))) return false;
  state.priorSources.push({ name: clean, values: [], weights: normalizePriorWeights([], rowCount(), 1) });
  renderInputSlots();
  return true;
}

async function removePriorSource(sourceIndex) {
  if (!Number.isInteger(sourceIndex) || sourceIndex < 0 || sourceIndex >= state.priorSources.length) return;
  state.priorSources.splice(sourceIndex, 1);
  renderInputSlots();
  await refreshCalculations({ mark: false }).catch((err) => postStatus(`Prior refresh failed: ${String(err?.message || err)}`, "error"));
  markDirty();
}

function originLabel(index) {
  const label = text(state.originLabels[index]);
  return label ? formatDatasetOriginLabel(label, getDetails().originLength) : "";
}

async function refreshOriginLabels({ render = true } = {}) {
  const details = getDetails();
  const expectedCount = sourceRowCount();
  const validationOptions = {
    originLen: details.originLength,
    requireMatchingPeriod: true,
    ...(expectedCount > 0 ? { expectedCount } : {}),
  };
  const current = validateDatasetOriginLabels(state.originLabels, validationOptions);
  const sidecar = validateDatasetOriginLabels(state.sidecarOriginLabels, validationOptions);
  if (current.ok) state.originLabels = current.labels;
  else if (sidecar.ok) state.originLabels = sidecar.labels;
  else {
    state.originLabels = [];
    state.originLabels = await ensureDatasetOriginLabels(state.project, details.originLength, {
      requireMatchingPeriod: true,
      ...(expectedCount > 0 ? { expectedCount } : {}),
    });
  }
  if (render) renderMethodGrid();
}

function clearCalculatedOutputs() {
  state.selectedPriorValues = [];
  state.newUltimateValues = [];
}

function calculateOutputs() {
  const count = rowCount();
  clearCalculatedOutputs();
  for (let i = 0; i < count; i += 1) {
    const latest = numberOrNull(state.latestValues[i]);
    // Percentage Developed belongs to the development pattern, never to the
    // Latest figure: an origin whose latest is zero still has a development age.
    const pct = numberOrNull(state.percentDevelopedValues[i]);
    let priorNumerator = 0;
    let priorDenominator = 0;
    for (const source of state.priorSources) {
      const prior = numberOrNull(source.values?.[i]);
      const weight = Math.max(0, numberOrNull(source.weights?.[i]) ?? 0);
      if (prior === null || weight <= 0) continue;
      priorNumerator += prior * weight;
      priorDenominator += weight;
    }
    const selectedPrior = priorDenominator > 0 ? priorNumerator / priorDenominator : null;
    let ultimate;
    if (latest === null) {
      // Nothing observed yet -- a quarter beyond the valuation in a quarterly
      // class -- still expects its whole prior, so the method covers the year.
      ultimate = selectedPrior;
    } else if (selectedPrior === null) {
      ultimate = latest;
    } else {
      ultimate = pct !== null
        // Six decimals like every other BF vector: a whole-number ultimate
        // drifts from ResQ in everything that reads the BF output.
        ? roundBornhuetterFergusonNumber(latest + (1 - pct) * selectedPrior)
        : null;
    }
    state.selectedPriorValues.push(selectedPrior);
    state.newUltimateValues.push(ultimate);
  }
  renderBfChart();
}

function renderBfChart() {
  bfChart?.render({
    originLabels: Array.from({ length: rowCount() }, (_, index) => originLabel(index)),
    latestValues: state.latestValues,
    percentDevelopedValues: state.percentDevelopedValues,
    selectedPriorValues: state.selectedPriorValues,
    newUltimateValues: state.newUltimateValues,
    decimalPlaces: state.statisticDecimalPlaces,
  });
}

async function refreshOriginLabelsForCalculations() {
  try {
    await refreshOriginLabels({ render: false });
  } catch (err) {
    clearCalculatedOutputs();
    renderMethodGrid();
    renderBfChart();
    throw err;
  }
}

async function refreshCalculations({ mark = false } = {}) {
  const details = getDetails();
  if (!details.latestDataset || !details.dfmDataset) {
    if (!details.dfmDataset) state.percentDevelopedValues = [];
    reapplyActiveDependencyPreviews();
    await refreshOriginLabelsForCalculations();
    calculateOutputs();
    renderMethodGrid();
    if (mark) markDirty();
    return;
  }
  const tasks = [
    { kind: "latest", name: details.latestDataset },
    { kind: "dfm", name: details.dfmDataset },
    ...state.priorSources.map((source) => ({ kind: "prior", name: source.name, source })),
  ];
  const loaded = await mapWithConcurrency(tasks, 4, async (task) => {
    try {
      const payload = await loadConfiguredSourcePayload(task.name, details);
      if (task.kind !== "prior") return { ...task, payload };
      const values = vectorValues(payload?.values);
      return {
        ...task,
        source: {
          ...task.source,
          values,
          weights: normalizePriorWeights(task.source.weights, Math.max(values.length, rowCount()), 1),
        },
      };
    } catch (err) {
      if (task.kind !== "prior") throw err;
      postStatus(`Prior source unavailable (${task.name}): ${String(err?.message || err)}`, "warn");
      return { ...task, source: { ...task.source, values: [] } };
    }
  });
  const latestPayload = loaded[0]?.payload || {};
  const dfmPayload = loaded[1]?.payload || {};
  const priorSources = loaded.slice(2).map((item) => item.source);
  state.latestValues = latestDiagonal(latestPayload?.values);
  state.dfmUltimateValues = vectorValues(dfmPayload?.values);
  state.percentDevelopedValues = await loadDevelopmentPattern(details.dfmDataset);
  state.priorSources = priorSources;
  reapplyActiveDependencyPreviews();
  const labels = Array.isArray(latestPayload?.origin_labels) ? latestPayload.origin_labels : [];
  if (!state.originLabels.length && labels.length) state.originLabels = labels.map(String);
  await refreshOriginLabelsForCalculations();
  calculateOutputs();
  renderMethodGrid();
  if (mark) markDirty();
}

async function mapWithConcurrency(items, limit, mapper) {
  const values = Array.isArray(items) ? items : [];
  const results = new Array(values.length);
  let cursor = 0;
  async function worker() {
    while (cursor < values.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await mapper(values[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(Math.max(1, limit), values.length) }, worker));
  return results;
}

function sumMethodValues(values) {
  const numbers = (Array.isArray(values) ? values : []).map(numberOrNull).filter((value) => value !== null);
  return numbers.length ? numbers.reduce((sum, value) => sum + value, 0) : null;
}

function methodColumns() {
  const columns = [
    { type: "origin", label: "Accident Year", className: "bfOriginCell", colClass: "bfMethodOriginCol" },
    { type: "latest", label: "Latest", className: "bfLatestCell", colClass: "bfMethodValueCol" },
    { type: "percentage", label: "Percentage Developed", className: "bfPercentCell", colClass: "bfMethodValueCol" },
  ];
  state.priorSources.forEach((source, sourceIndex) => {
    columns.push({ type: "prior", label: source.name, sourceIndex, className: "bfPriorCell", colClass: "bfMethodValueCol" });
    if (state.showWeights) {
      columns.push({
        type: "weight",
        label: state.showEffectiveWeights ? "Weight %" : "Weight",
        sourceIndex,
        className: "bfWeightCell",
        colClass: "bfMethodWeightCol",
      });
    }
  });
  columns.push(
    { type: "selectedPrior", label: "Selected Prior", className: "bfSelectedPriorCell", colClass: "bfMethodValueCol" },
    { type: "ultimate", label: "New Ultimate", className: "bfUltimateCell", colClass: "bfMethodValueCol" },
  );
  return columns;
}

function methodColumnCount() {
  return methodColumns().length;
}

function effectivePriorWeight(sourceIndex, rowIndex) {
  const source = state.priorSources[sourceIndex];
  if (!source || numberOrNull(source.values?.[rowIndex]) === null) return null;
  const targetWeight = Math.max(0, numberOrNull(source.weights?.[rowIndex]) ?? 0);
  let denominator = 0;
  for (const prior of state.priorSources) {
    if (numberOrNull(prior.values?.[rowIndex]) === null) continue;
    denominator += Math.max(0, numberOrNull(prior.weights?.[rowIndex]) ?? 0);
  }
  return denominator > 0 ? targetWeight / denominator : 0;
}

// The weight a prior's cell holds: the effective share when those are shown,
// otherwise the entered weight, and nothing for a row the prior has no value in.
function weightValue(sourceIndex, rowIndex) {
  if (numberOrNull(state.priorSources[sourceIndex]?.values?.[rowIndex]) === null) return null;
  if (state.showEffectiveWeights) return effectivePriorWeight(sourceIndex, rowIndex);
  return numberOrNull(state.priorSources[sourceIndex]?.weights?.[rowIndex]) ?? 0;
}

function displayWeight(value) {
  if (value === null) return "";
  if (state.showEffectiveWeights) return `${(value * 100).toFixed(state.statisticDecimalPlaces)}%`;
  return value.toFixed(1);
}

// The figure a method cell holds, unrounded; a copy takes this, the text
// shows `methodCellDisplay`.
function methodCellValue(column, rowIndex, count = rowCount()) {
  if (rowIndex === count) {
    if (column.type === "origin") return "Total";
    if (column.type === "latest") return sumMethodValues(state.latestValues);
    if (column.type === "prior") return sumMethodValues(state.priorSources[column.sourceIndex]?.values);
    if (column.type === "selectedPrior") return sumMethodValues(state.selectedPriorValues);
    if (column.type === "ultimate") return sumMethodValues(state.newUltimateValues);
    return null;
  }
  if (column.type === "origin") return originLabel(rowIndex);
  if (column.type === "latest") return state.latestValues[rowIndex];
  if (column.type === "percentage") return state.percentDevelopedValues[rowIndex];
  if (column.type === "prior") return state.priorSources[column.sourceIndex]?.values?.[rowIndex];
  if (column.type === "weight") return weightValue(column.sourceIndex, rowIndex);
  if (column.type === "selectedPrior") return state.selectedPriorValues[rowIndex];
  if (column.type === "ultimate") return state.newUltimateValues[rowIndex];
  return null;
}

function methodCellDisplay(column, value) {
  if (column.type === "origin") return String(value ?? "");
  if (column.type === "percentage") return displayPercent(value);
  if (column.type === "weight") return displayWeight(value);
  return displayNumber(value);
}

function normalizedMethodHighlight() {
  const highlight = state.methodHighlight;
  if (!highlight) return null;
  const lastRow = rowCount();
  const clampCol = (value) => Math.max(0, Math.min(methodColumnCount() - 1, Number(value) || 0));
  const clampRow = (value) => Math.max(0, Math.min(lastRow, Number(value) || 0));
  const firstCol = clampCol(highlight.startCol);
  const lastCol = clampCol(highlight.endCol);
  const firstRow = clampRow(highlight.startRow);
  const endRow = clampRow(highlight.endRow);
  return {
    startCol: Math.min(firstCol, lastCol),
    endCol: Math.max(firstCol, lastCol),
    startRow: Math.min(firstRow, endRow),
    endRow: Math.max(firstRow, endRow),
  };
}

function applyMethodHighlightDom() {
  methodSpreadsheetTable.applyDom();
}

function focusMethodTable() {
  try {
    els.methodTable?.focus({ preventScroll: true });
  } catch {
    els.methodTable?.focus?.();
  }
}

function clearMethodHighlight() {
  state.methodHighlightDragging = false;
  methodSpreadsheetTable.clear();
}

function methodCellAt(colIndex, rowIndex) {
  return els.methodGrid?.querySelector(`.bfMethodCell[data-col-index="${colIndex}"][data-row-index="${rowIndex}"]`) || null;
}

function scrollMethodCellIntoView({ r, c }) {
  const table = els.methodTable;
  const host = table?.closest(".bfTableWrap");
  if (!host) return;
  const cell = methodCellAt(c, r);
  if (!cell) return;
  const hostRect = host.getBoundingClientRect();
  const cellRect = cell.getBoundingClientRect();
  const headerHeight = table.tHead?.getBoundingClientRect().height || 0;
  const originWidth = table.querySelector("tbody td:first-child")?.getBoundingClientRect().width || 0;
  const visibleTop = hostRect.top + headerHeight;
  const visibleLeft = hostRect.left + (c > 0 ? originWidth : 0);
  if (cellRect.top < visibleTop) host.scrollTop -= visibleTop - cellRect.top;
  else if (cellRect.bottom > hostRect.bottom) host.scrollTop += cellRect.bottom - hostRect.bottom;
  if (cellRect.left < visibleLeft) host.scrollLeft -= visibleLeft - cellRect.left;
  else if (cellRect.right > hostRect.right) host.scrollLeft += cellRect.right - hostRect.right;
}

async function copyHighlightedMethodValues() {
  return methodSpreadsheetTable.copy();
}

async function readMethodClipboardText() {
  if (!navigator.clipboard?.readText) throw new Error("Clipboard paste is not available in this browser.");
  return navigator.clipboard.readText();
}

function setPriorWeight(sourceIndex, rowIndex, rawValue) {
  const source = state.priorSources[sourceIndex];
  if (!source || rowIndex < 0 || rowIndex >= rowCount() || numberOrNull(source.values?.[rowIndex]) === null) return false;
  const value = Math.max(0, numberOrNull(rawValue) ?? 0);
  while (source.weights.length <= rowIndex) source.weights.push(1);
  source.weights[rowIndex] = value;
  return true;
}

function highlightedWeightTargets() {
  const highlight = normalizedMethodHighlight();
  const columns = methodColumns();
  if (!highlight) return [];
  const targets = [];
  const seen = new Set();
  for (let rowIndex = highlight.startRow; rowIndex <= Math.min(highlight.endRow, rowCount() - 1); rowIndex += 1) {
    for (let colIndex = highlight.startCol; colIndex <= highlight.endCol; colIndex += 1) {
      const column = columns[colIndex];
      if (!column || (column.type !== "prior" && column.type !== "weight")) continue;
      if (numberOrNull(state.priorSources[column.sourceIndex]?.values?.[rowIndex]) === null) continue;
      const key = `${column.sourceIndex}:${rowIndex}`;
      if (seen.has(key)) continue;
      seen.add(key);
      targets.push({ sourceIndex: column.sourceIndex, rowIndex, colIndex });
    }
  }
  return targets;
}

function finishWeightEdit() {
  calculateOutputs();
  renderMethodGrid();
  markDirty();
}

function applyHighlightedWeightValue(rawValue) {
  const targets = highlightedWeightTargets();
  if (!targets.length) return false;
  let changed = false;
  for (const target of targets) changed = setPriorWeight(target.sourceIndex, target.rowIndex, rawValue) || changed;
  if (changed) finishWeightEdit();
  return changed;
}

function applyHighlightedWeightKey(key) {
  if (!/^[0-9.]$/.test(key || "") || !highlightedWeightTargets().length) return false;
  const highlight = normalizedMethodHighlight();
  const sessionKey = highlight ? `${highlight.startCol}:${highlight.startRow}:${highlight.endCol}:${highlight.endRow}` : "";
  const current = state.weightEditSession?.key === sessionKey ? state.weightEditSession.value : "";
  if (key === "." && current.includes(".")) return false;
  const next = current ? `${current}${key}` : key === "." ? "0." : key;
  state.weightEditSession = { key: sessionKey, value: next };
  return applyHighlightedWeightValue(next);
}

async function pasteHighlightedWeights() {
  const raw = await readMethodClipboardText();
  const highlight = normalizedMethodHighlight();
  if (!raw || !highlight) return false;
  const grid = String(raw).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").filter((row, index, rows) => row || index < rows.length - 1).map((row) => row.split("\t"));
  if (!grid.length) return false;
  if (grid.length === 1 && grid[0].length === 1) return applyHighlightedWeightValue(grid[0][0]);
  const columns = methodColumns();
  let changed = false;
  const visited = new Set();
  for (let rowIndex = highlight.startRow; rowIndex <= Math.min(rowCount() - 1, highlight.startRow + grid.length - 1); rowIndex += 1) {
    for (let colIndex = highlight.startCol; colIndex <= Math.min(columns.length - 1, highlight.startCol + grid[rowIndex - highlight.startRow].length - 1); colIndex += 1) {
      const column = columns[colIndex];
      if (!column || (column.type !== "prior" && column.type !== "weight")) continue;
      const key = `${column.sourceIndex}:${rowIndex}`;
      if (visited.has(key)) continue;
      visited.add(key);
      changed = setPriorWeight(column.sourceIndex, rowIndex, grid[rowIndex - highlight.startRow][colIndex - highlight.startCol]) || changed;
    }
  }
  if (changed) finishWeightEdit();
  return changed;
}

function closeMethodCellContextMenu() {
  if (!els.cellContextMenu) return;
  els.cellContextMenu.classList.remove("open");
  els.cellContextMenu.setAttribute("aria-hidden", "true");
}

function openMethodCellContextMenu(event, colIndex, rowIndex) {
  const menu = els.cellContextMenu;
  if (!menu) return;
  event.preventDefault();
  methodSpreadsheetTable.prepareContextCell({ r: rowIndex, c: colIndex });
  const pasteButton = menu.querySelector('[data-bf-cell-action="paste"]');
  if (pasteButton) pasteButton.hidden = !highlightedWeightTargets().length;
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(event.clientX, window.innerWidth - rect.width - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(event.clientY, window.innerHeight - rect.height - 8))}px`;
}

function wireMethodGridInteractions() {
  const table = els.methodTable;
  if (!table) return;
  table.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    closeMethodCellContextMenu();
    const header = event.target.closest("thead th[data-col-index]");
    if (header) {
      event.preventDefault();
      const colIndex = Number(header.dataset.colIndex);
      methodSpreadsheetTable.selectColumn(colIndex, { extend: event.shiftKey });
      focusMethodTable();
      return;
    }
    const cell = event.target.closest("td.bfMethodCell");
    if (!cell) return;
    event.preventDefault();
    const colIndex = Number(cell.dataset.colIndex);
    const rowIndex = Number(cell.dataset.rowIndex);
    if (colIndex === 0) {
      methodSpreadsheetTable.selectRow(rowIndex, { extend: event.shiftKey });
    } else {
      methodSpreadsheetTable.selectCell({ r: rowIndex, c: colIndex }, { extend: event.shiftKey });
    }
    state.weightEditSession = null;
    state.methodHighlightDragging = colIndex !== 0;
    focusMethodTable();
  });
  table.addEventListener("dblclick", (event) => {
    const cell = event.target.closest('td.bfMethodCell[data-cell-type="prior"], td.bfMethodCell[data-cell-type="weight"]');
    if (!cell) return;
    if (cell.dataset.cellType === "weight" && state.showEffectiveWeights) return;
    event.preventDefault();
    event.stopPropagation();
    const sourceIndex = Number(cell.dataset.sourceIndex);
    const rowIndex = Number(cell.dataset.rowIndex);
    const current = Math.max(0, numberOrNull(state.priorSources[sourceIndex]?.weights?.[rowIndex]) ?? 0);
    if (setPriorWeight(sourceIndex, rowIndex, current === 0 ? 1 : 0)) finishWeightEdit();
  });
  table.addEventListener("mouseover", (event) => {
    if (!state.methodHighlightDragging || !(event.buttons & 1)) return;
    const cell = event.target.closest("td.bfMethodCell");
    if (!cell) return;
    const anchor = methodSpreadsheetTable.selection().anchorCell;
    if (!anchor) return;
    methodSpreadsheetTable.setRange(anchor, {
      r: Number(cell.dataset.rowIndex),
      c: Number(cell.dataset.colIndex),
    });
  });
  document.addEventListener("mouseup", () => {
    state.methodHighlightDragging = false;
  });
  table.addEventListener("contextmenu", (event) => {
    const cell = event.target.closest("td.bfMethodCell");
    if (!cell) return;
    openMethodCellContextMenu(event, Number(cell.dataset.colIndex), Number(cell.dataset.rowIndex));
  });
  els.cellContextMenu?.addEventListener("click", (event) => {
    const action = event.target.closest("button[data-bf-cell-action]")?.dataset.bfCellAction;
    if (action === "copy") {
      void copyHighlightedMethodValues().catch((err) => postStatus(`Copy failed: ${String(err?.message || err)}`, "error"));
    } else if (action === "paste") {
      void pasteHighlightedWeights().catch((err) => postStatus(`Paste failed: ${String(err?.message || err)}`, "error"));
    } else if (action === "remove-highlights") {
      clearMethodHighlight();
    }
    closeMethodCellContextMenu();
    focusMethodTable();
  });
  document.addEventListener("mousedown", (event) => {
    if (!els.cellContextMenu?.classList.contains("open")) return;
    if (!event.target.closest("#bfCellContextMenu")) closeMethodCellContextMenu();
  });
  table.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.methodHighlight) {
      event.preventDefault();
      closeMethodCellContextMenu();
      clearMethodHighlight();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c" && state.methodHighlight) {
      event.preventDefault();
      void copyHighlightedMethodValues().catch((err) => postStatus(`Copy failed: ${String(err?.message || err)}`, "error"));
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v" && state.methodHighlight) {
      event.preventDefault();
      void pasteHighlightedWeights().catch((err) => postStatus(`Paste failed: ${String(err?.message || err)}`, "error"));
      return;
    }
    if ((event.key === "Delete" || event.key === "Backspace") && highlightedWeightTargets().length) {
      event.preventDefault();
      state.weightEditSession = null;
      applyHighlightedWeightValue(0);
      return;
    }
    if (!event.ctrlKey && !event.metaKey && !event.altKey && applyHighlightedWeightKey(event.key)) {
      event.preventDefault();
      return;
    }
    const deltas = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const delta = deltas[event.key];
    if (!delta || event.altKey || !state.methodHighlight) return;
    if (methodSpreadsheetTable.move(delta[1], delta[0], {
      extend: event.shiftKey,
      jump: event.ctrlKey || event.metaKey,
    })) {
      event.preventDefault();
      event.stopPropagation();
    }
  });
}

function methodCellMarkup(column, colIndex, rowIndex, count) {
  const value = methodCellValue(column, rowIndex, count);
  const display = methodCellDisplay(column, value);
  const copyValue = Number.isFinite(value) || typeof value === "string" ? String(value) : "";
  const isNullCell = rowIndex < rowCount() && display === "";
  const visibleDisplay = isNullCell ? "null" : display;
  const source = Number.isInteger(column.sourceIndex) ? state.priorSources[column.sourceIndex] : null;
  const weight = source ? Math.max(0, numberOrNull(source.weights?.[rowIndex]) ?? 0) : 0;
  const hasSourceValue = source ? numberOrNull(source.values?.[rowIndex]) !== null : false;
  const classes = ["bfMethodCell", column.className || ""];
  if (isNullCell) classes.push("bfNullCell");
  if (column.type === "prior" && rowIndex < rowCount() && hasSourceValue && weight > 0) classes.push("bfSelectedSourceCell");
  if (column.type === "weight" && rowIndex < rowCount() && hasSourceValue && weight > 0) classes.push("bfWeightNonZero");
  const sourceAttr = Number.isInteger(column.sourceIndex) ? ` data-source-index="${column.sourceIndex}"` : "";
  return `<td class="${classes.join(" ")}" data-col-index="${colIndex}" data-row-index="${rowIndex}" data-cell-type="${column.type}"${sourceAttr} data-copy-value="${escapeHtml(copyValue)}" aria-selected="false">${escapeHtml(visibleDisplay)}</td>`;
}

function renderMethodGrid() {
  if (!els.methodGrid || !els.methodHead || !els.methodCols) return;
  const count = rowCount();
  const columns = methodColumns();
  els.methodCols.innerHTML = columns.map((column) => `<col class="${column.colClass}">`).join("");
  els.methodHead.innerHTML = `<tr>${columns.map((column, colIndex) => `<th class="${column.type === "weight" ? "bfWeightHeader" : ""}" data-col-index="${colIndex}"><span class="bfMethodHeaderText">${escapeHtml(column.label)}</span></th>`).join("")}</tr>`;
  const rows = [];
  for (let rowIndex = 0; rowIndex < count; rowIndex += 1) {
    rows.push(`<tr>${columns.map((column, colIndex) => methodCellMarkup(column, colIndex, rowIndex, count)).join("")}</tr>`);
  }
  rows.push(`<tr class="bfTotalRow">${columns.map((column, colIndex) => methodCellMarkup(column, colIndex, count, count)).join("")}</tr>`);
  els.methodGrid.innerHTML = rows.join("");
  applyMethodHighlightDom();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildPayload(options = {}) {
  const details = getDetails();
  const count = rowCount();
  return buildBornhuetterFergusonMethodPayload({
    details,
    originLabels: Array.from({ length: count }, (_, index) => originLabel(index)),
    latestValues: state.latestValues,
    dfmUltimateValues: state.dfmUltimateValues,
    priorSources: state.priorSources,
    percentageDeveloped: state.percentDevelopedValues,
    selectedPriorValues: state.selectedPriorValues,
    newUltimate: state.newUltimateValues,
    showWeights: state.showWeights,
    showEffectiveWeights: state.showEffectiveWeights,
    methodMetadata: state.methodMetadata,
    lastModified: text(options.lastModified) || state.methodLastModified,
  });
}

async function applyPayload(payload) {
  const data = payload && typeof payload === "object" ? payload : {};
  const details = data.details_tab || {};
  const method = data.method_tab || {};
  const metadata = data.method_metadata && typeof data.method_metadata === "object"
    ? data.method_metadata
    : {};
  withProgrammatic(() => {
    els.nameInput.value = text(details.name || els.nameInput.value);
    els.outputTypeInput.value = text(details.output_type || els.outputTypeInput.value);
    els.originLengthInput.value = String(validOriginLength(details.origin_length || els.originLengthInput.value));
    els.latestInput.value = text(method.latest_dataset || els.latestInput.value);
    els.dfmInput.value = text(method.dfm_dataset || els.dfmInput.value);
  });
  syncOriginLengthControl();
  state.statisticDecimalPlaces = statisticDecimalPlaces(details.statistic_decimal_places, 1);
  state.datasetCategory = text(details.dataset_category);
  state.showWeights = method.show_weights !== false;
  state.showEffectiveWeights = method.show_effective_weights === true;
  state.originLabels = Array.isArray(method.origin_labels) ? method.origin_labels.map(String) : [];
  state.latestValues = Array.isArray(method.latest_values) ? method.latest_values.map(numberOrNull) : [];
  state.dfmUltimateValues = Array.isArray(method.dfm_ultimate_values) ? method.dfm_ultimate_values.map(numberOrNull) : [];
  state.percentDevelopedValues = Array.isArray(method.percentage_developed) ? method.percentage_developed.map(numberOrNull) : [];
  const storedPriorSources = Array.isArray(method.prior_datasets) ? method.prior_datasets : [];
  state.priorSources = storedPriorSources.map((source) => normalizePriorSource(source, rowCount())).filter((source) => source.name);
  state.selectedPriorValues = Array.isArray(method.selected_prior_values) ? method.selected_prior_values.map(numberOrNull) : [];
  state.newUltimateValues = Array.isArray(method.new_ultimate) ? method.new_ultimate.map(numberOrNull) : [];
  state.methodMetadata = { ...metadata };
  state.methodLastModified = text(metadata.last_modified) || state.methodLastModified;
  syncTitles();
  syncFormattingControls();
  renderInputSlots();
  renderMethodGrid();
  renderBfChart();
}

function snapshotPayload() {
  return JSON.stringify({ method: buildPayload(), notes: els.notesInput?.value || "" });
}

function markClean() {
  cleanSnapshot = snapshotPayload();
  bfNotesController.markClean();
  postDirty(false, true);
}

function applyOutputSidecar(sidecar, options = {}) {
  const payload = sidecar && typeof sidecar === "object" ? sidecar : {};
  if (payload.exists === false) {
    state.sidecarOriginLabels = [];
    setNeedsReview(false);
    if (!options.preserveNotes) setNotesText("");
    auditLogView.clear();
    return false;
  }
  setNeedsReview(statusNeedsReview(payload.status));
  state.sidecarOriginLabels = Array.isArray(payload.origin_labels)
    ? payload.origin_labels.map(String)
    : [];
  if (!options.preserveNotes) setNotesText(String(payload.notes ?? ""));
  auditLogView.render(payload.audit_log);
  return true;
}

function applyAggregateRevisions(result, method = {}) {
  const metadata = method?.method_metadata && typeof method.method_metadata === "object"
    ? method.method_metadata
    : {};
  state.ownedRevision = text(result?.owned_revision || metadata.owned_revision);
  state.derivedRevision = text(result?.derived_revision || metadata.derived_revision);
  state.publicationRevision = text(result?.publication_revision || metadata.publication_revision);
}

function captureLocalOwnedState() {
  return {
    details: getDetails(),
    originLabels: state.originLabels.slice(),
    latestValues: state.latestValues.slice(),
    dfmUltimateValues: state.dfmUltimateValues.slice(),
    percentDevelopedValues: state.percentDevelopedValues.slice(),
    priorSources: state.priorSources.map((source) => ({
      name: source.name,
      values: Array.isArray(source.values) ? source.values.slice() : [],
      weights: Array.isArray(source.weights) ? source.weights.slice() : [],
    })),
    showWeights: state.showWeights,
    showEffectiveWeights: state.showEffectiveWeights,
    statisticDecimalPlaces: state.statisticDecimalPlaces,
    notes: els.notesInput?.value || "",
  };
}

function restoreLocalOwnedState(local, persisted) {
  if (!local || !persisted) return;
  const localDetails = local.details || {};
  const persistedDetails = persisted.details || {};
  withProgrammatic(() => {
    els.nameInput.value = text(localDetails.name);
    els.outputTypeInput.value = text(localDetails.outputType);
    els.originLengthInput.value = String(validOriginLength(localDetails.originLength));
    els.latestInput.value = text(localDetails.latestDataset);
    els.dfmInput.value = text(localDetails.dfmDataset);
  });
  state.showWeights = local.showWeights !== false;
  state.showEffectiveWeights = local.showEffectiveWeights === true;
  state.statisticDecimalPlaces = statisticDecimalPlaces(local.statisticDecimalPlaces, 1);
  state.datasetCategory = text(localDetails.datasetCategory);
  state.latestValues = norm(localDetails.latestDataset) === norm(persistedDetails.latestDataset)
    ? persisted.latestValues.slice()
    : local.latestValues.slice();
  const dfmUnchanged = norm(localDetails.dfmDataset) === norm(persistedDetails.dfmDataset);
  state.dfmUltimateValues = dfmUnchanged
    ? persisted.dfmUltimateValues.slice()
    : local.dfmUltimateValues.slice();
  state.percentDevelopedValues = dfmUnchanged
    ? persisted.percentDevelopedValues.slice()
    : local.percentDevelopedValues.slice();
  const persistedPriors = new Map(
    persisted.priorSources.map((source) => [norm(source.name), source]),
  );
  const usePersistedOriginLabels = validOriginLength(localDetails.originLength)
    === validOriginLength(persistedDetails.originLength)
    && persisted.originLabels.length > 0;
  const nextOriginLabels = usePersistedOriginLabels
    ? persisted.originLabels.slice()
    : local.originLabels.slice();
  state.priorSources = local.priorSources.map((source) => ({
    name: source.name,
    values: persistedPriors.get(norm(source.name))?.values?.slice() || source.values.slice(),
    weights: usePersistedOriginLabels
      ? rebaseBornhuetterFergusonWeightsByOriginLabel({
          localOriginLabels: local.originLabels,
          localWeights: source.weights,
          persistedOriginLabels: nextOriginLabels,
          persistedWeights: persistedPriors.get(norm(source.name))?.weights,
        })
      : source.weights.slice(),
  }));
  state.originLabels = nextOriginLabels;
  setNotesText(local.notes);
  syncOriginLengthControl();
  syncTitles();
  syncFormattingControls();
  renderInputSlots();
  calculateOutputs();
  renderMethodGrid();
}

async function applyPersistedAggregate(result, options = {}) {
  const method = result?.method;
  if (!method || !isBornhuetterFergusonV3Method(method)) {
    throw new Error(`${BF_METHOD_TYPE} load did not return a canonical v3 method.`);
  }
  const local = options.preserveOwnedState ? captureLocalOwnedState() : null;
  applyOutputSidecar(result?.sidecar || {}, { preserveNotes: !!local });
  await applyPayload(method);
  applyAggregateRevisions(result, method);
  if (local) {
    const persisted = captureLocalOwnedState();
    restoreLocalOwnedState(local, persisted);
  }
  const previewChanged = reapplyActiveDependencyPreviews();
  if (previewChanged) {
    calculateOutputs();
    renderMethodGrid();
  }
  const savedName = text(getDetails().name);
  bfObjectChangeWatch.ensure({
    projectName: state.project,
    reservingClass: state.reservingClass,
    methodName: savedName,
    outputDataset: savedName,
    selfWriteStamp: result?.sidecar?.updated_at,
  });
  return true;
}

async function fetchPersistedBornhuetterFerguson() {
  return loadBornhuetterFergusonMethod({
    project_name: state.project,
    reserving_class: state.reservingClass,
    method_name: getDetails().name,
  });
}

async function tryLoadExistingMethod() {
  if (!getDetails().name) return false;
  const requestSequence = ++aggregateLoadSequence;
  let result;
  try {
    result = await fetchPersistedBornhuetterFerguson();
  } catch (err) {
    if (Number(err?.status) === 404) return false;
    throw err;
  }
  if (requestSequence !== aggregateLoadSequence) return true;
  await applyPersistedAggregate(result);
  postStatus(`Loaded ${BF_METHOD_TYPE}: ${getDetails().name}`);
  return true;
}

async function reloadPersistedBornhuetterFerguson(options = {}) {
  if (!getDetails().name) return false;
  const requestSequence = ++aggregateLoadSequence;
  const result = await fetchPersistedBornhuetterFerguson();
  if (requestSequence !== aggregateLoadSequence) return false;
  await applyPersistedAggregate(result, options);
  if (options.preserveOwnedState) {
    postDirty(snapshotPayload() !== cleanSnapshot, true);
  } else {
    markClean();
  }
  return true;
}

// The window blocks edits behind the shared saving animation for the whole
// round trip: recalculation, method write, then dependent-propagation queueing.
const bfSaveProgress = createArcRhoSaveProgress({ subject: BF_METHOD_TYPE, projectName: () => state.project });

async function saveBornhuetterFerguson() {
  return bfSaveProgress.run((progress) => runBornhuetterFergusonSave(progress));
}

async function runBornhuetterFergusonSave(progress) {
  const details = getDetails();
  if (!details.name || !details.outputType) {
    postStatus(`${BF_METHOD_TYPE} save requires Name and Output Type.`, "error");
    return { ok: false };
  }
  if (!details.latestDataset || !details.dfmDataset || !details.priorDatasets.length) {
    postStatus(`${BF_METHOD_TYPE} save requires Latest, Development Pattern, and at least one Prior Vector.`, "error");
    return { ok: false };
  }
  await refreshOriginLabels({ render: false });
  calculateOutputs();
  renderMethodGrid();
  const vector = state.newUltimateValues;
  if (!vector.some((value) => numberOrNull(value) !== null)) {
    postStatus(`${BF_METHOD_TYPE} output vector is blank. Check source selections.`, "error");
    return { ok: false };
  }
  const method = buildPayload({ lastModified: new Date().toISOString() });
  const saveInput = {
    project_name: state.project,
    reserving_class: state.reservingClass,
    method,
    notes: els.notesInput?.value || "",
    expected_owned_revision: state.ownedRevision,
    expected_derived_revision: state.derivedRevision,
  };
  let result;
  bfObjectChangeWatch.pause();
  try {
    try {
      progress.writing();
      result = await saveBornhuetterFergusonMethod(saveInput);
    } catch (err) {
      progress.finish();
      if (isEngineUnavailableSaveError(err)) {
        // The save was refused before anything was written; unsaved work stays
        // in this window. The spinner is already gone, so the message box
        // cannot open behind it.
        void showPageMessageBox({
          title: "Arco Engine Unavailable",
          message: String(err?.message || err),
          tone: "warn",
        });
      }
      throw err;
    }
    await applyPersistedAggregate(result);
    markClean();
    // A save rewrites the graph on both sides, so the Details rows are stale
    // until it is re-read.
    void refreshDetailsDependencies();
    try {
      window.parent?.postMessage({ type: "arcrho:project-instance-refresh-datasets" }, "*");
    } catch {}
    const aggregatedCsvPaths = Array.isArray(result?.aggregated_csv_paths)
      ? result.aggregated_csv_paths
      : [];
    postStatus(
      result?.propagation_ok === false
        ? `${BF_METHOD_TYPE} saved, but some dependent updates did not complete: ${
            String(result?.propagation?.message || "").trim() || details.name
          }`
        : `${BF_METHOD_TYPE} saved: ${details.name}${aggregatedCsvPaths.length ? ` (+${aggregatedCsvPaths.length} aggregated)` : ""}`,
      result?.propagation_ok === false ? "warn" : "",
    );
    // Engine-hosted saves return with the dependent walk already finished;
    // a null outcome (walk failures) keeps the window open and leaves the
    // dataset table as the failure surface.
    const propagationOutcome = await trackSavePropagation(result?.propagation, {
      onStatus: (text, statusOptions) => {
        progress.setMessage?.(text, statusOptions);
        postStatus(text, statusOptions?.tone === "warn" ? "warn" : "");
      },
      onComplete: () => {
        try {
          window.parent?.postMessage({ type: "arcrho:project-instance-refresh-datasets" }, "*");
        } catch {}
      },
    });
    // The save and its dependent walk are done; drop the spinner before the
    // review dialog.
    progress.finish();
    await showMethodSaveReviewWarning(result, {
      instanceId: inst,
      projectName: state.project,
      reservingClass: state.reservingClass,
    });
    return {
      ...result,
      propagationClean: propagationOutcome !== null,
      refreshedDatasets: propagationOutcome?.review_flagged_datasets || [],
      linkWarnings: propagationOutcome?.link_warnings || [],
    };
  } finally {
    bfObjectChangeWatch.resume();
  }
}

function setNotesText(value) {
  const next = String(value ?? "");
  bfNotesController.setValue(next, { markClean: true });
}

async function openPicker(kind, anchor) {
  await loadCachedRows().catch(() => {});
  const titles = {
    output: "Select Output Vector",
    latest: "Select Latest",
    dfm: "Select Development Pattern",
    prior: "Select Prior Vector",
  };
  const allowedDataFormats = kind === "latest" ? ["Triangle"] : ["Vector"];
  await openDatasetNamePicker({
    projectName: state.project,
    initialName: kind === "output"
      ? els.outputTypeInput?.value
      : kind === "latest"
        ? els.latestInput?.value
        : kind === "dfm"
          ? els.dfmInput?.value
          : state.priorSources.at(-1)?.name || "",
    anchorElement: anchor instanceof Element ? anchor : null,
    title: titles[kind] || "Select Dataset",
    allowedDataFormats,
    includeCalculated: true,
    emptyMessage: kind === "latest" ? "No cached triangle datasets found." : "No cached vector datasets found.",
    itemFilter: (item) => {
      const record = cachedRecordByName(item?.name);
      if (!record && kind !== "output") return false;
      if (kind === "dfm") return norm(record?.methodType) === "dfm" && norm(record?.dataFormat) === "vector";
      if (kind === "latest") return norm(record?.dataFormat) === "triangle";
      if (kind === "prior") return norm(record?.dataFormat) === "vector";
      return true;
    },
    setStatus: (message) => {
      const msg = text(message);
      if (msg) postStatus(msg, "warn");
    },
    onError: (err) => {
      console.error(`Failed to open ${kind} picker:`, err);
      postStatus(`Error loading dataset names: ${String(err?.message || err)}`, "error");
    },
    onSelect: async (name, item) => {
      const selected = text(name);
      if (!selected) return;
      if (kind === "prior" && !addPriorSource(selected)) {
        postStatus(`Prior Vector is already selected: ${selected}`, "warn");
        return;
      }
      if (kind === "output") {
        const record = cachedRecordByName(selected);
        state.datasetCategory = text(item?.dataset_category || item?.category || record?.category);
      }
      withProgrammatic(() => {
        if (kind === "output") els.outputTypeInput.value = selected;
        if (kind === "latest") els.latestInput.value = selected;
        if (kind === "dfm") els.dfmInput.value = selected;
        if (kind === "output" && !els.nameInput.value) els.nameInput.value = selected;
        if (item?.origin_length || item?.originLength) {
          els.originLengthInput.value = String(validOriginLength(item.origin_length || item.originLength));
        }
      });
      syncOriginLengthControl();
      syncTitles();
      try {
        await refreshCalculations({ mark: false });
      } catch (err) {
        postStatus(`Source refresh failed: ${String(err?.message || err)}`, "error");
      }
      markDirty();
    },
  });
}

function requestConfirmedClose() {
  requestTabbedPageWindowClose({
    messageType: "arcrho:dataset-close-confirmed",
    inst,
  });
}

async function closeOrConfirm() {
  if (isDirty) {
    const discard = await bfCloseConfirm.confirm({ reason: "close" });
    if (!discard) return;
  }
  requestConfirmedClose();
}

async function initTabbedPage() {
  const container = document.getElementById("bfTabbedPage");
  tabbedPage = createTabbedPage(container, {
    tabs: BF_TABS,
    cssPrefix: "bf",
    initialTab: ALLOWED_BF_TABS.has(text(params.get("tab") || params.get("initial_tab"))) ? text(params.get("tab") || params.get("initial_tab")) : "details",
    onTabChange: (tabId) => {
      if (tabId === "chart") requestAnimationFrame(() => bfChart?.refresh());
      try {
        window.parent?.postMessage({ type: "arcrho:bf-tab-changed", inst, tab: tabId }, "*");
      } catch {}
    },
  });
  applyTabbedPageSaveBar(document.getElementById("bfSaveBar"));
  wireTabPopoutWindows({
    cssPrefix: "bf",
    tabs: BF_TABS,
    tabSystem: () => tabbedPage,
    getTitle: () => `${getDetails().name || BF_METHOD_TYPE} - ${BF_METHOD_TYPE}`,
  });
  bfChart = createBornhuetterFergusonChart({
    canvas: els.chartCanvas,
    legend: els.chartLegend,
    emptyState: els.chartEmpty,
    tooltip: els.chartTooltip,
  });
  renderBfChart();
}

function syncFormattingControls() {
  if (els.showWeightsInput) els.showWeightsInput.checked = state.showWeights;
  if (els.methodDecimalsInput) els.methodDecimalsInput.value = String(state.statisticDecimalPlaces);
  if (els.weightDisplayLabel) els.weightDisplayLabel.textContent = state.showEffectiveWeights ? "Effective %" : "Index";
  if (els.weightDisplayButton) els.weightDisplayButton.disabled = !state.showWeights;
  for (const option of els.weightDisplayMenu?.querySelectorAll("[data-value]") || []) {
    option.setAttribute("aria-selected", option.dataset.value === (state.showEffectiveWeights ? "effective" : "actual") ? "true" : "false");
  }
}

function originLengthOptions() {
  return Array.from(els.originLengthMenu?.querySelectorAll("button[data-value]") || []);
}

function syncOriginLengthControl() {
  const value = String(validOriginLength(els.originLengthInput?.value));
  if (els.originLengthInput) els.originLengthInput.value = value;
  if (els.originLengthLabel) els.originLengthLabel.textContent = value;
  for (const option of originLengthOptions()) {
    option.setAttribute("aria-selected", option.dataset.value === value ? "true" : "false");
  }
}

function closeOriginLengthDropdown({ focusButton = false } = {}) {
  els.originLengthDropdown?.classList.remove("open");
  els.originLengthButton?.setAttribute("aria-expanded", "false");
  if (focusButton) els.originLengthButton?.focus();
}

function openOriginLengthDropdown({ focusSelected = false } = {}) {
  closeWeightDisplayDropdown();
  els.originLengthDropdown?.classList.add("open");
  els.originLengthButton?.setAttribute("aria-expanded", "true");
  if (focusSelected) {
    const selected = originLengthOptions().find((option) => option.getAttribute("aria-selected") === "true");
    selected?.focus();
  }
}

function setOriginLength(value) {
  const nextValue = String(validOriginLength(value));
  const changed = els.originLengthInput?.value !== nextValue;
  if (els.originLengthInput) els.originLengthInput.value = nextValue;
  syncOriginLengthControl();
  closeOriginLengthDropdown({ focusButton: true });
  if (!changed || !els.originLengthInput) return;
  els.originLengthInput.dispatchEvent(new Event("input", { bubbles: true }));
  els.originLengthInput.dispatchEvent(new Event("change", { bubbles: true }));
}

function closeWeightDisplayDropdown() {
  els.weightDisplayDropdown?.classList.remove("open");
  els.weightDisplayButton?.setAttribute("aria-expanded", "false");
}

function setStatisticDecimals(value) {
  state.statisticDecimalPlaces = statisticDecimalPlaces(value, state.statisticDecimalPlaces);
  syncFormattingControls();
  renderMethodGrid();
  renderBfChart();
  markDirty();
}

function wireInputs() {
  wireMethodGridInteractions();
  for (const input of [els.nameInput, els.outputTypeInput, els.originLengthInput]) {
    input?.addEventListener("input", () => {
      if (input === els.originLengthInput) syncOriginLengthControl();
      syncTitles();
      markDirty();
    });
    input?.addEventListener("change", async () => {
      syncTitles();
      try {
        await refreshCalculations({ mark: false });
      } catch (err) {
        postStatus(`Refresh failed: ${String(err?.message || err)}`, "error");
      }
      markDirty();
    });
  }
  els.outputTypeBtn?.addEventListener("click", () => openPicker("output", els.outputTypeBtn));
  els.showWeightsInput?.addEventListener("change", () => {
    state.showWeights = !!els.showWeightsInput.checked;
    if (!state.showWeights) closeWeightDisplayDropdown();
    state.methodHighlight = null;
    syncFormattingControls();
    renderMethodGrid();
    markDirty();
  });
  els.weightDisplayButton?.addEventListener("click", () => {
    if (els.weightDisplayButton.disabled) return;
    const open = !els.weightDisplayDropdown?.classList.contains("open");
    if (open) closeOriginLengthDropdown();
    els.weightDisplayDropdown?.classList.toggle("open", open);
    els.weightDisplayButton.setAttribute("aria-expanded", open ? "true" : "false");
  });
  els.weightDisplayMenu?.addEventListener("click", (event) => {
    const option = event.target.closest("button[data-value]");
    if (!option) return;
    const nextShowEffectiveWeights = option.dataset.value === "effective";
    const changed = state.showEffectiveWeights !== nextShowEffectiveWeights;
    state.showEffectiveWeights = nextShowEffectiveWeights;
    state.weightEditSession = null;
    closeWeightDisplayDropdown();
    syncFormattingControls();
    renderMethodGrid();
    if (changed) markDirty();
  });
  els.originLengthButton?.addEventListener("click", () => {
    const open = !els.originLengthDropdown?.classList.contains("open");
    if (open) openOriginLengthDropdown();
    else closeOriginLengthDropdown();
  });
  els.originLengthButton?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeOriginLengthDropdown();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    openOriginLengthDropdown({ focusSelected: true });
  });
  els.originLengthMenu?.addEventListener("click", (event) => {
    const option = event.target.closest("button[data-value]");
    if (option) setOriginLength(option.dataset.value);
  });
  els.originLengthMenu?.addEventListener("keydown", (event) => {
    const options = originLengthOptions();
    if (!options.length) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeOriginLengthDropdown({ focusButton: true });
      return;
    }
    if (event.key === "Tab") {
      closeOriginLengthDropdown();
      return;
    }
    const currentIndex = Math.max(0, options.indexOf(document.activeElement));
    let nextIndex = currentIndex;
    if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % options.length;
    else if (event.key === "ArrowUp") nextIndex = (currentIndex - 1 + options.length) % options.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = options.length - 1;
    else return;
    event.preventDefault();
    options[nextIndex].focus();
  });
  document.addEventListener("mousedown", (event) => {
    if (els.weightDisplayDropdown?.classList.contains("open") && !event.target.closest("#bfWeightDisplayDropdown")) closeWeightDisplayDropdown();
    if (els.originLengthDropdown?.classList.contains("open") && !event.target.closest("#bfOriginLengthDropdown")) closeOriginLengthDropdown();
  });
  els.methodDecimalsInput?.addEventListener("input", () => setStatisticDecimals(els.methodDecimalsInput.value));
  els.methodDecimalsInput?.addEventListener("change", () => setStatisticDecimals(els.methodDecimalsInput.value));
  els.methodDecimalsUp?.addEventListener("click", () => setStatisticDecimals(state.statisticDecimalPlaces + 1));
  els.methodDecimalsDown?.addEventListener("click", () => setStatisticDecimals(state.statisticDecimalPlaces - 1));
  syncFormattingControls();
  syncOriginLengthControl();
  renderInputSlots();
  els.saveBtn?.addEventListener("click", async () => {
    try {
      const saved = await saveBornhuetterFerguson();
      // A save keeps the window open; only Cancel and a confirmed dirty close
      // dismiss it.
      if (saved?.ok && saved?.propagationClean) {
        await showSavedDependentsNotice(saved.refreshedDatasets, { linkWarnings: saved.linkWarnings });
      }
    } catch (err) {
      console.error(err);
      postStatus(`Save failed: ${String(err?.message || err)}`, "error");
    }
  });
  els.cancelBtn?.addEventListener("click", closeOrConfirm);
  window.__arcrho_request_close = () => {
    if (!isDirty) return false;
    if (bfCloseConfirm.isOpen) return true;
    void closeOrConfirm();
    return true;
  };
  window.__arcrho_consume_close_shortcut = window.__arcrho_request_close;
}

function wireMessages() {
  window.addEventListener("message", async (event) => {
    const msg = event?.data && typeof event.data === "object" ? event.data : {};
    if (msg.type === "arcrho:dataset-save") {
      try {
        const saved = await saveBornhuetterFerguson();
        if (saved?.ok && saved?.propagationClean) {
          await showSavedDependentsNotice(saved.refreshedDatasets, { linkWarnings: saved.linkWarnings });
        }
      } catch (err) {
        postStatus(`Save failed: ${String(err?.message || err)}`, "error");
      }
      return;
    }
    if (msg.type === "arcrho:dependency-source-preview") {
      applyDependencySourcePreview(msg);
      return;
    }
    if (msg.type === "arcrho:dependency-source-cleared") {
      try {
        await clearDependencySourcePreview(msg);
      } catch (err) {
        postStatus(`Source preview reload failed: ${String(err?.message || err)}`, "error");
      }
      return;
    }
    if (msg.type === "arcrho:close-active-tab" || msg.type === "arcrho:dataset-close-request") {
      await closeOrConfirm();
    }
  });
}

async function init() {
  applyHostFixedDetailsFields({ root: "#bfDetailsPage" });
  syncDetailsLabelWidth({
    root: "#bfDetailsPage",
    labelSelector: ".arDetailsLabel",
  });
  withProgrammatic(() => {
    els.projectInput.value = state.project;
    els.classInput.value = state.reservingClass;
    els.nameInput.value = text(params.get("name") || params.get("dataset") || "");
    els.outputTypeInput.value = text(params.get("output_type") || params.get("dataset_type") || params.get("datasetType") || "");
    els.originLengthInput.value = String(validOriginLength(params.get("origin_length") || params.get("originLength")));
  });
  syncOriginLengthControl();
  syncTitles();
  await initTabbedPage();
  wireInputs();
  wireMessages();
  let loadError = null;
  const loaded = await tryLoadExistingMethod().catch((err) => {
    loadError = err;
    postStatus(`Could not load existing ${BF_METHOD_TYPE}: ${String(err?.message || err)}`, "error");
    return false;
  });
  void refreshDetailsDependencies();
  if (loaded) {
    postStatus(`${BF_METHOD_TYPE} ready.`);
  } else if (!loadError) {
    try {
      await refreshOriginLabels({ render: false });
      calculateOutputs();
      renderMethodGrid();
    } catch (err) {
      state.originLabels = [];
      calculateOutputs();
      renderMethodGrid();
      postStatus(`Origin labels unavailable: ${String(err?.message || err)}`, "error");
    }
  }
  markClean();
}

// The window is held blank until the opening tab is rendered; see
// ui/shared/tabbed_page/initial_tab_paint.js.
void init().finally(() => window.arcrhoRevealPage?.());
