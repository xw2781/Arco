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
import { createCapeCodRatiosChart } from "/ui/method_pages/cape_cod/cape_cod_ratios_chart.js?v=20260804a";
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
  CC_METHOD_TYPE,
  buildCapeCodMethodPayload,
  calculateCapeCodColumns,
  computeCapeCodUltimatesTriangle,
  fitCapeCodTrendRate,
  isCapeCodV1Method,
  normalizeCapeCodPriorUltimateMode,
  normalizeCapeCodScalingType,
  rebaseCapeCodTrendFactorOverridesByOriginLabel,
  roundCapeCodRate,
  roundCapeCodVector,
} from "/ui/method_pages/cape_cod/cape_cod_json_contract.js?v=20260830a";
import {
  loadCapeCodMethod,
  saveCapeCodMethod,
} from "/ui/method_pages/cape_cod/cape_cod_method_api.js?v=20260814b";
import {
  CAPE_COD_TAB_DEFS,
  windowTabIds,
} from "/ui/shared/tabs/window_tab_catalog.js?v=20260903a";
import { bootTableColors } from "/ui/shared/components/spreadsheet/table_colors.js?v=20260927b";

// The user's table colours, shared by every method page.
bootTableColors();

const DEFAULT_ORIGIN_LENGTH = 12;
const DFM_METHOD_TYPE = "DFM";
const VALID_ORIGIN_LENGTHS = [12, 6, 3, 1];
const CC_TABS = CAPE_COD_TAB_DEFS;
const ALLOWED_CC_TABS = windowTabIds("cape_cod");
const PRIOR_MODE_LABELS = {
  latest_ultimates: "Latest / Ultimates",
  pattern: "Pattern",
};
const SCALING_LABELS = {
  percentage: "Percentage",
  unscaled: "Unscaled",
  auto_scaled: "Auto-scaled",
};

const params = new URLSearchParams(window.location.search || "");
const inst = text(params.get("inst")) || `cc_${Date.now()}`;

function emptyDerivedColumns() {
  return {
    trendRate: 0,
    trendFactorOverrides: [],
    trendFactors: [],
    trendedLatestValues: [],
    percentageDeveloped: [],
    developmentFactors: [],
    developedExposureValues: [],
    futureExposureValues: [],
    trendedDevelopedRatios: [],
    expectedUltimateRatios: [],
    detrendedExpectedRatios: [],
    futureLatestValues: [],
    capeCodUltimate: [],
    capeCodUltimateRatios: [],
  };
}

const state = {
  project: text(params.get("project")),
  reservingClass: text(params.get("class") || params.get("path")),
  cachedRows: [],
  originLabels: [],
  sidecarOriginLabels: [],
  latestValues: [],
  latestTriangleRows: [],
  latestDevelopmentLabels: [],
  exposureValues: [],
  priorUltimateValues: [],
  priorUltimatePercentageDeveloped: [],
  priorUltimateMode: "latest_ultimates",
  trendRate: 0,
  autoTrendFit: false,
  decayFactor: 0,
  scalingType: "percentage",
  alternativeUltimateCalculation: false,
  trendFactorOverrides: [],
  derived: emptyDerivedColumns(),
  localUltimatesTriangle: null,
  serverUltimatesTriangle: null,
  statisticDecimalPlaces: 2,
  datasetCategory: text(params.get("category")),
  methodMetadata: {},
  ownedRevision: "",
  derivedRevision: "",
  publicationRevision: "",
  methodLastModified: new Date().toISOString(),
  methodHighlight: null,
  methodHighlightDragging: false,
  trendFactorEditSession: null,
  needsReview: false,
};

let cleanSnapshot = "";
let isDirty = false;
let programmatic = false;
let tabbedPage = null;
let ccChart = null;
let aggregateLoadSequence = 0;
const ccCloseConfirm = createPageCloseConfirm({ subject: CC_METHOD_TYPE });
// Open-window change alert (advisory): fires once when another user or the
// dependent-propagation job rewrites this method while it is open.
const ccObjectChangeWatch = createMethodObjectChangeWatchController({
  methodType: "cape_cod",
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
  watch: ccObjectChangeWatch,
  getProject: () => state.project,
  getReservingClass: () => state.reservingClass,
});
const activeDependencyPreviews = new Map();
const ccNotesController = mountNotesTab({
  container: document.getElementById("ccNotesMount"),
  ariaLabel: "Cape Cod notes",
  onChange: () => markDirty(),
  onStatus: postStatus,
});

const els = {
  projectInput: document.getElementById("ccProjectInput"),
  classInput: document.getElementById("ccClassInput"),
  nameInput: document.getElementById("ccNameInput"),
  outputTypeInput: document.getElementById("ccOutputTypeInput"),
  outputTypeBtn: document.getElementById("ccOutputTypeBtn"),
  originLengthInput: document.getElementById("ccOriginLengthInput"),
  originLengthDropdown: document.getElementById("ccOriginLengthDropdown"),
  originLengthButton: document.getElementById("ccOriginLengthButton"),
  originLengthLabel: document.getElementById("ccOriginLengthLabel"),
  originLengthMenu: document.getElementById("ccOriginLengthMenu"),
  latestInput: document.getElementById("ccLatestInput"),
  exposureInput: document.getElementById("ccExposureInput"),
  priorUltimateInput: document.getElementById("ccPriorUltimateInput"),
  priorModeDropdown: document.getElementById("ccPriorModeDropdown"),
  priorModeButton: document.getElementById("ccPriorModeButton"),
  priorModeLabel: document.getElementById("ccPriorModeLabel"),
  priorModeMenu: document.getElementById("ccPriorModeMenu"),
  trendRateInput: document.getElementById("ccTrendRateInput"),
  fitBtn: document.getElementById("ccFitBtn"),
  autoFitInput: document.getElementById("ccAutoFitInput"),
  decayInput: document.getElementById("ccDecayInput"),
  decayUp: document.getElementById("ccDecayUp"),
  decayDown: document.getElementById("ccDecayDown"),
  scalingDropdown: document.getElementById("ccScalingDropdown"),
  scalingButton: document.getElementById("ccScalingButton"),
  scalingLabel: document.getElementById("ccScalingLabel"),
  scalingMenu: document.getElementById("ccScalingMenu"),
  methodDecimalsInput: document.getElementById("ccMethodDecimalsInput"),
  methodDecimalsUp: document.getElementById("ccMethodDecimalsUp"),
  methodDecimalsDown: document.getElementById("ccMethodDecimalsDown"),
  altUltimateInput: document.getElementById("ccAltUltimateInput"),
  methodTable: document.querySelector(".ccMethodTable"),
  methodCols: document.getElementById("ccMethodCols"),
  methodHead: document.getElementById("ccMethodHead"),
  methodGrid: document.getElementById("ccMethodGrid"),
  ultimatesTable: document.querySelector(".ccUltimatesTable"),
  ultimatesCols: document.getElementById("ccUltimatesCols"),
  ultimatesHead: document.getElementById("ccUltimatesHead"),
  ultimatesGrid: document.getElementById("ccUltimatesGrid"),
  ultimatesEmpty: document.getElementById("ccUltimatesEmpty"),
  chartCanvas: document.getElementById("ccChartCanvas"),
  chartLegend: document.getElementById("ccChartLegend"),
  chartEmpty: document.getElementById("ccChartEmpty"),
  chartTooltip: document.getElementById("ccChartTooltip"),
  cellContextMenu: document.getElementById("ccCellContextMenu"),
  auditLogMount: document.getElementById("ccAuditLogMount"),
  notesInput: ccNotesController.elements.input,
  saveBtn: document.getElementById("ccSaveBtn"),
  cancelBtn: document.getElementById("ccCancelBtn"),
};

const auditLogView = createAuditLogView({
  container: els.auditLogMount,
  ariaLabel: "Cape Cod audit log",
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
  cellSelector: "td.ccMethodCell[data-row-index][data-col-index]",
  rowHeaderSelector: "td.ccOriginCell[data-row-index]",
  columnHeaderSelector: "thead th[data-col-index]",
  getCellPosition: (cell) => ({
    r: Number(cell?.dataset?.rowIndex),
    c: Number(cell?.dataset?.colIndex),
  }),
  getRowHeaderIndex: (header) => Number(header?.dataset?.rowIndex),
  getColumnHeaderIndex: (header) => Number(header?.dataset?.colIndex),
  selectedClasses: ["ccHighlightedCell"],
  anchorClasses: ["ccHighlightAnchorCell", "arSpreadsheetSelectionAnchor"],
  rowSelectedLabelClasses: ["ccHighlightedRowLabel", "arSpreadsheetSelectedLabel"],
  columnSelectedLabelClasses: ["ccHighlightedColumnLabel", "arSpreadsheetSelectedLabel"],
  getCellValue: (_position, cell) => cell?.dataset?.copyValue || "",
  onAfterCopy: () => postStatus("Copied selected Cape Cod values."),
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

function columnFrom(values) {
  return Array.isArray(values) ? values.map(numberOrNull) : [];
}

function validOriginLength(value, fallback = DEFAULT_ORIGIN_LENGTH) {
  const n = Number.parseInt(String(value ?? ""), 10);
  return VALID_ORIGIN_LENGTHS.includes(n) ? n : fallback;
}

function statisticDecimalPlaces(value, fallback = 2) {
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
    exposureDataset: text(els.exposureInput?.value),
    priorUltimateDataset: text(els.priorUltimateInput?.value),
    statisticDecimalPlaces: state.statisticDecimalPlaces,
  };
}

let detailsDependencies = null;

function getDetailsDependencies() {
  if (!detailsDependencies) {
    detailsDependencies = createDetailsDependenciesController({
      dependencyMap: "ccDependencyMap",
      getSelfMethodType: () => "Cape Cod",
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
  const title = details.name ? `${details.name} - ${CC_METHOD_TYPE}` : CC_METHOD_TYPE;
  document.title = title;
  renderInputSlots();
}

// The inputs are chosen on the Details Data Flow map.
function renderInputSlots() {
  const slot = (key, label, input) => ({
    key,
    label,
    values: [text(input?.value)].filter(Boolean),
    pick: (anchor) => openPicker(key, anchor),
  });
  getDetailsDependencies().setInputs([
    slot("latest", "Latest", els.latestInput),
    slot("exposure", "Exposure", els.exposureInput),
    slot("prior_ultimate", "Prior Ultimate", els.priorUltimateInput),
  ]);
}

function displayNumber(value, decimals = 0) {
  const n = numberOrNull(value);
  if (n === null) return "";
  return n.toLocaleString(undefined, { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
}

function displayFactor(value) {
  const n = numberOrNull(value);
  if (n === null) return "";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: state.statisticDecimalPlaces,
    minimumFractionDigits: state.statisticDecimalPlaces,
  });
}

function displayPercent(value) {
  const n = numberOrNull(value);
  if (n === null) return "";
  return `${(n * 100).toLocaleString(undefined, {
    maximumFractionDigits: state.statisticDecimalPlaces,
    minimumFractionDigits: state.statisticDecimalPlaces,
  })}%`;
}

function effectiveScalingType() {
  if (state.scalingType !== "auto_scaled") return state.scalingType;
  const ratioColumns = [
    state.derived.trendedDevelopedRatios,
    state.derived.expectedUltimateRatios,
    state.derived.detrendedExpectedRatios,
    state.derived.capeCodUltimateRatios,
  ];
  let maxAbs = 0;
  for (const column of ratioColumns) {
    for (const value of Array.isArray(column) ? column : []) {
      const n = numberOrNull(value);
      if (n !== null) maxAbs = Math.max(maxAbs, Math.abs(n));
    }
  }
  return maxAbs >= 10 ? "unscaled" : "percentage";
}

function displayRatio(value) {
  const n = numberOrNull(value);
  if (n === null) return "";
  if (effectiveScalingType() === "unscaled") return displayFactor(n);
  return displayPercent(n);
}

function csvBaseName(value) {
  return text(value).split(/[\\/]/).pop();
}

async function loadDevelopmentPattern(datasetName) {
  // Only a DFM has development factors. Cape Cod also accepts a prior ultimate
  // from anywhere else, and that one legitimately has no pattern, so the
  // dataset's own method type decides whether there is anything to read.
  const name = text(datasetName);
  const record = cachedRecordByName(name);
  if (!state.project || !state.reservingClass || !name) return [];
  if (norm(record?.methodType) !== norm(DFM_METHOD_TYPE)) return [];
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
  return Math.max(
    state.latestValues.length,
    state.exposureValues.length,
    state.priorUltimateValues.length,
  );
}

function rowCount() {
  return Math.max(
    state.originLabels.length,
    sourceRowCount(),
    1,
  );
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
  if (details.exposureDataset && names.has(norm(details.exposureDataset))) {
    roles.push({ key: "exposure", kind: "exposure", name: details.exposureDataset });
  }
  if (details.priorUltimateDataset && names.has(norm(details.priorUltimateDataset))) {
    roles.push({ key: "prior_ultimate", kind: "prior_ultimate", name: details.priorUltimateDataset });
  }
  return roles;
}

function dependencyPreviewValues(message = {}) {
  if (Array.isArray(message.values)) return message.values.map(numberOrNull);
  const matrix = dependencyPreviewMatrix(message);
  if (!matrix.length) return [];
  return norm(message.dataFormat || message.data_format) === "triangle"
    ? latestDiagonal(matrix)
    : vectorValues(matrix);
}

function dependencyPreviewMatrix(message = {}) {
  const matrix = Array.isArray(message.matrixValues)
    ? message.matrixValues
    : (Array.isArray(message.matrix_values) ? message.matrix_values : []);
  return matrix;
}

function applyDependencyValuesToRole(role, values, matrix = [], message = {}) {
  const normalizedValues = Array.isArray(values) ? values.map(numberOrNull) : [];
  if (role.kind === "latest") {
    state.latestValues = normalizedValues;
    if (Array.isArray(matrix) && matrix.length) state.latestTriangleRows = matrix;
    return true;
  }
  if (role.kind === "exposure") {
    state.exposureValues = normalizedValues;
    return true;
  }
  if (role.kind === "prior_ultimate") {
    state.priorUltimateValues = normalizedValues;
    const pattern = message.percentageDeveloped || message.percentage_developed;
    if (Array.isArray(pattern)) state.priorUltimatePercentageDeveloped = pattern.map(numberOrNull);
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
    changed = applyDependencyValuesToRole(role, preview.values, preview.matrix, preview.message) || changed;
  }
  return changed;
}

function applyDependencySourcePreview(message = {}) {
  const roles = dependencyRolesMatchingMessage(message);
  const values = dependencyPreviewValues(message);
  if (!roles.length || !values.length) return false;
  const matrix = norm(message.dataFormat || message.data_format) === "triangle"
    ? dependencyPreviewMatrix(message)
    : [];
  let changed = false;
  for (const role of roles) {
    activeDependencyPreviews.set(role.key, {
      message: { ...message },
      values: values.slice(),
      matrix: matrix.slice(),
    });
    changed = applyDependencyValuesToRole(role, values, matrix, message) || changed;
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
  return reloadPersistedCapeCod({ preserveOwnedState: isDirty });
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

function calculateOutputs() {
  const count = rowCount();
  const labels = Array.from({ length: count }, (_, index) => text(state.originLabels[index]) || String(index + 1));
  const columns = calculateCapeCodColumns({
    originLabels: labels,
    latestValues: state.latestValues,
    exposureValues: state.exposureValues,
    priorUltimateValues: state.priorUltimateValues,
    priorUltimatePercentageDeveloped: state.priorUltimatePercentageDeveloped,
    priorUltimateMode: state.priorUltimateMode,
    trendRate: state.trendRate,
    autoTrendFit: state.autoTrendFit,
    decayFactor: state.decayFactor,
    alternativeUltimateCalculation: state.alternativeUltimateCalculation,
    trendFactorOverrides: state.trendFactorOverrides,
  });
  state.derived = columns;
  state.trendFactorOverrides = columns.trendFactorOverrides.slice();
  state.trendRate = columns.trendRate;
  syncMethodControls();
  recomputeUltimatesTriangle();
  renderCcChart();
}

function regularLatestTriangleRows() {
  const count = rowCount();
  const rows = state.latestTriangleRows;
  if (!count || !Array.isArray(rows) || rows.length !== count) return null;
  const ragged = [];
  for (let index = 0; index < count; index += 1) {
    const row = Array.isArray(rows[index]) ? rows[index].slice(0, count - index) : [];
    if (row.length !== count - index) return null;
    ragged.push(row);
  }
  return ragged;
}

function recomputeUltimatesTriangle() {
  const ragged = regularLatestTriangleRows();
  state.localUltimatesTriangle = ragged
    ? computeCapeCodUltimatesTriangle({
      exposureValues: state.exposureValues,
      percentageDeveloped: state.derived.percentageDeveloped,
      decayFactor: state.decayFactor,
      trendRate: state.trendRate,
      alternativeUltimateCalculation: state.alternativeUltimateCalculation,
    }, ragged)
    : null;
  renderUltimatesGrid();
}

function displayedUltimatesTriangle() {
  return state.localUltimatesTriangle || state.serverUltimatesTriangle;
}

function renderCcChart() {
  ccChart?.render({
    originLabels: Array.from({ length: rowCount() }, (_, index) => originLabel(index)),
    latestValues: state.latestValues,
    trendedLatestValues: state.derived.trendedLatestValues,
    exposureValues: state.exposureValues,
    trendedDevelopedRatios: state.derived.trendedDevelopedRatios,
    expectedUltimateRatios: state.derived.expectedUltimateRatios,
    detrendedExpectedRatios: state.derived.detrendedExpectedRatios,
    capeCodUltimateRatios: state.derived.capeCodUltimateRatios,
    decimalPlaces: state.statisticDecimalPlaces,
    scalingType: effectiveScalingType(),
  });
}

async function refreshOriginLabelsForCalculations() {
  try {
    await refreshOriginLabels({ render: false });
  } catch (err) {
    state.derived = emptyDerivedColumns();
    renderMethodGrid();
    renderCcChart();
    throw err;
  }
}

async function refreshCalculations({ mark = false } = {}) {
  const details = getDetails();
  const tasks = [
    ...(details.latestDataset ? [{ kind: "latest", name: details.latestDataset }] : []),
    ...(details.exposureDataset ? [{ kind: "exposure", name: details.exposureDataset }] : []),
    ...(details.priorUltimateDataset ? [{ kind: "prior_ultimate", name: details.priorUltimateDataset }] : []),
  ];
  if (!tasks.length) {
    reapplyActiveDependencyPreviews();
    await refreshOriginLabelsForCalculations();
    calculateOutputs();
    renderMethodGrid();
    if (mark) markDirty();
    return;
  }
  const loaded = await mapWithConcurrency(tasks, 3, async (task) => ({
    ...task,
    payload: await loadConfiguredSourcePayload(task.name, details),
  }));
  let latestLabels = [];
  for (const item of loaded) {
    const payload = item?.payload || {};
    if (item.kind === "latest") {
      state.latestTriangleRows = Array.isArray(payload?.values) ? payload.values : [];
      state.latestDevelopmentLabels = Array.isArray(payload?.dev_labels)
        ? payload.dev_labels.map(String)
        : [];
      state.latestValues = latestDiagonal(payload?.values);
      latestLabels = Array.isArray(payload?.origin_labels) ? payload.origin_labels : [];
    } else if (item.kind === "exposure") {
      state.exposureValues = vectorValues(payload?.values);
    } else if (item.kind === "prior_ultimate") {
      state.priorUltimateValues = vectorValues(payload?.values);
    }
  }
  state.priorUltimatePercentageDeveloped = await loadDevelopmentPattern(details.priorUltimateDataset);
  reapplyActiveDependencyPreviews();
  if (!state.originLabels.length && latestLabels.length) state.originLabels = latestLabels.map(String);
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

function totalRatio(numeratorValues, denominatorValues) {
  const numerator = sumMethodValues(numeratorValues);
  const denominator = sumMethodValues(denominatorValues);
  if (numerator === null || denominator === null || denominator === 0) return null;
  return numerator / denominator;
}

function methodColumns() {
  const details = getDetails();
  const latestName = details.latestDataset || "Latest";
  const exposureName = details.exposureDataset || "Exposure";
  return [
    { type: "origin", label: "Accident Year", className: "ccOriginCell", colClass: "ccMethodOriginCol" },
    { type: "latest", label: "Latest", className: "ccLatestCell", colClass: "ccMethodValueCol" },
    { type: "exposure", label: "Exposure", className: "ccExposureCell", colClass: "ccMethodValueCol" },
    { type: "trendFactor", label: "Trend Factor", className: "ccTrendFactorCell", colClass: "ccMethodFactorCol" },
    { type: "trendedLatest", label: `Trended ${latestName}`, className: "ccCalcCell", colClass: "ccMethodValueCol" },
    { type: "percentageDeveloped", label: "Percentage Developed", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
    { type: "developmentFactor", label: "Development Factor", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
    { type: "developedExposure", label: `Developed ${exposureName}`, className: "ccCalcCell", colClass: "ccMethodValueCol" },
    { type: "futureExposure", label: `Future ${exposureName}`, className: "ccCalcCell", colClass: "ccMethodValueCol" },
    { type: "trendedDevelopedRatio", label: "Trended Developed Ratio", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
    { type: "expectedUltimateRatio", label: "Expected Ultimate Ratio", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
    { type: "detrendedExpectedRatio", label: "Detrended Expected Ratio", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
    { type: "futureLatest", label: `Future ${latestName}`, className: "ccCalcCell", colClass: "ccMethodValueCol" },
    { type: "ultimate", label: "Cape Cod Ultimate", className: "ccUltimateCell", colClass: "ccMethodValueCol" },
    { type: "ultimateRatio", label: "Cape Cod Ultimate Ratio", className: "ccCalcCell", colClass: "ccMethodFactorCol" },
  ];
}

function methodColumnCount() {
  return methodColumns().length;
}

// The figure a method cell holds, unrounded; a copy takes this, the text
// shows `methodCellDisplay`.
function methodCellValue(column, rowIndex, count = rowCount()) {
  const derived = state.derived;
  if (rowIndex === count) {
    if (column.type === "origin") return "Total";
    if (column.type === "latest") return sumMethodValues(state.latestValues);
    if (column.type === "exposure") return sumMethodValues(state.exposureValues);
    if (column.type === "trendedLatest") return sumMethodValues(derived.trendedLatestValues);
    if (column.type === "developedExposure") return sumMethodValues(derived.developedExposureValues);
    if (column.type === "futureExposure") return sumMethodValues(derived.futureExposureValues);
    if (column.type === "futureLatest") return sumMethodValues(derived.futureLatestValues);
    if (column.type === "ultimate") return sumMethodValues(derived.capeCodUltimate);
    if (column.type === "trendedDevelopedRatio") return totalRatio(derived.trendedLatestValues, derived.developedExposureValues);
    if (column.type === "detrendedExpectedRatio") return totalRatio(derived.futureLatestValues, derived.futureExposureValues);
    if (column.type === "ultimateRatio") return totalRatio(derived.capeCodUltimate, state.exposureValues);
    return null;
  }
  if (column.type === "origin") return originLabel(rowIndex);
  if (column.type === "latest") return state.latestValues[rowIndex];
  if (column.type === "exposure") return state.exposureValues[rowIndex];
  if (column.type === "trendFactor") return derived.trendFactors?.[rowIndex];
  if (column.type === "trendedLatest") return derived.trendedLatestValues?.[rowIndex];
  if (column.type === "percentageDeveloped") return derived.percentageDeveloped?.[rowIndex];
  if (column.type === "developmentFactor") return derived.developmentFactors?.[rowIndex];
  if (column.type === "developedExposure") return derived.developedExposureValues?.[rowIndex];
  if (column.type === "futureExposure") return derived.futureExposureValues?.[rowIndex];
  if (column.type === "trendedDevelopedRatio") return derived.trendedDevelopedRatios?.[rowIndex];
  if (column.type === "expectedUltimateRatio") return derived.expectedUltimateRatios?.[rowIndex];
  if (column.type === "detrendedExpectedRatio") return derived.detrendedExpectedRatios?.[rowIndex];
  if (column.type === "futureLatest") return derived.futureLatestValues?.[rowIndex];
  if (column.type === "ultimate") return derived.capeCodUltimate?.[rowIndex];
  if (column.type === "ultimateRatio") return derived.capeCodUltimateRatios?.[rowIndex];
  return null;
}

const FACTOR_COLUMN_TYPES = new Set(["trendFactor", "developmentFactor"]);
const RATIO_COLUMN_TYPES = new Set([
  "trendedDevelopedRatio", "expectedUltimateRatio", "detrendedExpectedRatio", "ultimateRatio",
]);

function methodCellDisplay(column, value) {
  if (column.type === "origin") return String(value ?? "");
  if (column.type === "percentageDeveloped") return displayPercent(value);
  if (FACTOR_COLUMN_TYPES.has(column.type)) return displayFactor(value);
  if (RATIO_COLUMN_TYPES.has(column.type)) return displayRatio(value);
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
  return els.methodGrid?.querySelector(`.ccMethodCell[data-col-index="${colIndex}"][data-row-index="${rowIndex}"]`) || null;
}

function scrollMethodCellIntoView({ r, c }) {
  const table = els.methodTable;
  const host = table?.closest(".ccTableWrap");
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

function setTrendFactorOverride(rowIndex, rawValue) {
  if (state.autoTrendFit || rowIndex < 0 || rowIndex >= rowCount()) return false;
  const cleared = rawValue === null || rawValue === undefined || rawValue === "";
  const value = cleared ? null : numberOrNull(rawValue);
  if (!cleared && value === null) return false;
  while (state.trendFactorOverrides.length <= rowIndex) state.trendFactorOverrides.push(null);
  state.trendFactorOverrides[rowIndex] = value;
  return true;
}

function highlightedTrendFactorTargets() {
  if (state.autoTrendFit) return [];
  const highlight = normalizedMethodHighlight();
  const columns = methodColumns();
  if (!highlight) return [];
  const targets = [];
  for (let rowIndex = highlight.startRow; rowIndex <= Math.min(highlight.endRow, rowCount() - 1); rowIndex += 1) {
    for (let colIndex = highlight.startCol; colIndex <= highlight.endCol; colIndex += 1) {
      if (columns[colIndex]?.type !== "trendFactor") continue;
      targets.push({ rowIndex, colIndex });
    }
  }
  return targets;
}

function finishTrendFactorEdit() {
  calculateOutputs();
  renderMethodGrid();
  markDirty();
}

function applyHighlightedTrendFactorValue(rawValue) {
  const targets = highlightedTrendFactorTargets();
  if (!targets.length) return false;
  let changed = false;
  for (const target of targets) changed = setTrendFactorOverride(target.rowIndex, rawValue) || changed;
  if (changed) finishTrendFactorEdit();
  return changed;
}

function applyHighlightedTrendFactorKey(key) {
  if (!/^[0-9.]$/.test(key || "") || !highlightedTrendFactorTargets().length) return false;
  const highlight = normalizedMethodHighlight();
  const sessionKey = highlight ? `${highlight.startCol}:${highlight.startRow}:${highlight.endCol}:${highlight.endRow}` : "";
  const current = state.trendFactorEditSession?.key === sessionKey ? state.trendFactorEditSession.value : "";
  if (key === "." && current.includes(".")) return false;
  const next = current ? `${current}${key}` : key === "." ? "0." : key;
  state.trendFactorEditSession = { key: sessionKey, value: next };
  return applyHighlightedTrendFactorValue(next);
}

async function pasteHighlightedTrendFactors() {
  const raw = await readMethodClipboardText();
  const highlight = normalizedMethodHighlight();
  if (!raw || !highlight) return false;
  const grid = String(raw).replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").filter((row, index, rows) => row || index < rows.length - 1).map((row) => row.split("\t"));
  if (!grid.length) return false;
  if (grid.length === 1 && grid[0].length === 1) return applyHighlightedTrendFactorValue(grid[0][0]);
  const columns = methodColumns();
  let changed = false;
  for (let rowIndex = highlight.startRow; rowIndex <= Math.min(rowCount() - 1, highlight.startRow + grid.length - 1); rowIndex += 1) {
    for (let colIndex = highlight.startCol; colIndex <= Math.min(columns.length - 1, highlight.startCol + grid[rowIndex - highlight.startRow].length - 1); colIndex += 1) {
      if (columns[colIndex]?.type !== "trendFactor") continue;
      changed = setTrendFactorOverride(rowIndex, grid[rowIndex - highlight.startRow][colIndex - highlight.startCol]) || changed;
    }
  }
  if (changed) finishTrendFactorEdit();
  return changed;
}

function clearHighlightedTrendFactorOverrides() {
  return applyHighlightedTrendFactorValue(null);
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
  const hasTargets = !!highlightedTrendFactorTargets().length;
  const pasteButton = menu.querySelector('[data-cc-cell-action="paste"]');
  if (pasteButton) pasteButton.hidden = !hasTargets;
  const clearButton = menu.querySelector('[data-cc-cell-action="clear-override"]');
  if (clearButton) clearButton.hidden = !hasTargets;
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
    const cell = event.target.closest("td.ccMethodCell");
    if (!cell) return;
    event.preventDefault();
    const colIndex = Number(cell.dataset.colIndex);
    const rowIndex = Number(cell.dataset.rowIndex);
    if (colIndex === 0) {
      methodSpreadsheetTable.selectRow(rowIndex, { extend: event.shiftKey });
    } else {
      methodSpreadsheetTable.selectCell({ r: rowIndex, c: colIndex }, { extend: event.shiftKey });
    }
    state.trendFactorEditSession = null;
    state.methodHighlightDragging = colIndex !== 0;
    focusMethodTable();
  });
  table.addEventListener("dblclick", (event) => {
    const cell = event.target.closest('td.ccMethodCell[data-cell-type="trendFactor"]');
    if (!cell || state.autoTrendFit) return;
    event.preventDefault();
    event.stopPropagation();
    const rowIndex = Number(cell.dataset.rowIndex);
    if (numberOrNull(state.trendFactorOverrides[rowIndex]) === null) return;
    if (setTrendFactorOverride(rowIndex, null)) finishTrendFactorEdit();
  });
  table.addEventListener("mouseover", (event) => {
    if (!state.methodHighlightDragging || !(event.buttons & 1)) return;
    const cell = event.target.closest("td.ccMethodCell");
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
    const cell = event.target.closest("td.ccMethodCell");
    if (!cell) return;
    openMethodCellContextMenu(event, Number(cell.dataset.colIndex), Number(cell.dataset.rowIndex));
  });
  els.cellContextMenu?.addEventListener("click", (event) => {
    const action = event.target.closest("button[data-cc-cell-action]")?.dataset.ccCellAction;
    if (action === "copy") {
      void copyHighlightedMethodValues().catch((err) => postStatus(`Copy failed: ${String(err?.message || err)}`, "error"));
    } else if (action === "paste") {
      void pasteHighlightedTrendFactors().catch((err) => postStatus(`Paste failed: ${String(err?.message || err)}`, "error"));
    } else if (action === "clear-override") {
      clearHighlightedTrendFactorOverrides();
    } else if (action === "remove-highlights") {
      clearMethodHighlight();
    }
    closeMethodCellContextMenu();
    focusMethodTable();
  });
  document.addEventListener("mousedown", (event) => {
    if (!els.cellContextMenu?.classList.contains("open")) return;
    if (!event.target.closest("#ccCellContextMenu")) closeMethodCellContextMenu();
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
      void pasteHighlightedTrendFactors().catch((err) => postStatus(`Paste failed: ${String(err?.message || err)}`, "error"));
      return;
    }
    if ((event.key === "Delete" || event.key === "Backspace") && highlightedTrendFactorTargets().length) {
      event.preventDefault();
      state.trendFactorEditSession = null;
      clearHighlightedTrendFactorOverrides();
      return;
    }
    if (!event.ctrlKey && !event.metaKey && !event.altKey && applyHighlightedTrendFactorKey(event.key)) {
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
  const classes = ["ccMethodCell", column.className || ""];
  if (isNullCell) classes.push("ccNullCell");
  if (column.type === "trendFactor" && rowIndex < rowCount()) {
    if (numberOrNull(state.trendFactorOverrides[rowIndex]) !== null) classes.push("ccTrendOverrideCell");
    if (state.autoTrendFit) classes.push("ccTrendFactorReadOnly");
  }
  return `<td class="${classes.join(" ")}" data-col-index="${colIndex}" data-row-index="${rowIndex}" data-cell-type="${column.type}" data-copy-value="${escapeHtml(copyValue)}" aria-selected="false">${escapeHtml(visibleDisplay)}</td>`;
}

function renderMethodGrid() {
  if (!els.methodGrid || !els.methodHead || !els.methodCols) return;
  const count = rowCount();
  const columns = methodColumns();
  els.methodCols.innerHTML = columns.map((column) => `<col class="${column.colClass}">`).join("");
  els.methodHead.innerHTML = `<tr>${columns.map((column, colIndex) => `<th data-col-index="${colIndex}"><span class="ccMethodHeaderText">${escapeHtml(column.label)}</span></th>`).join("")}</tr>`;
  const rows = [];
  for (let rowIndex = 0; rowIndex < count; rowIndex += 1) {
    rows.push(`<tr>${columns.map((column, colIndex) => methodCellMarkup(column, colIndex, rowIndex, count)).join("")}</tr>`);
  }
  rows.push(`<tr class="ccTotalRow">${columns.map((column, colIndex) => methodCellMarkup(column, colIndex, count, count)).join("")}</tr>`);
  els.methodGrid.innerHTML = rows.join("");
  applyMethodHighlightDom();
}

function ultimatesDevelopmentLabel(columnIndex) {
  const label = text(state.latestDevelopmentLabels[columnIndex]);
  if (label) return label;
  return String((columnIndex + 1) * getDetails().originLength);
}

function renderUltimatesGrid() {
  if (!els.ultimatesGrid || !els.ultimatesHead || !els.ultimatesCols) return;
  const triangle = displayedUltimatesTriangle();
  const rows = Array.isArray(triangle) ? triangle : [];
  const columnCount = rows.reduce((max, row) => Math.max(max, Array.isArray(row) ? row.length : 0), 0);
  const hasData = rows.length > 0 && columnCount > 0;
  if (els.ultimatesEmpty) els.ultimatesEmpty.hidden = hasData;
  els.ultimatesTable?.classList.toggle("isEmpty", !hasData);
  if (!hasData) {
    els.ultimatesCols.innerHTML = "";
    els.ultimatesHead.innerHTML = "";
    els.ultimatesGrid.innerHTML = "";
    return;
  }
  els.ultimatesCols.innerHTML = `<col class="ccUltimatesOriginCol">${'<col class="ccUltimatesValueCol">'.repeat(columnCount)}`;
  const headerCells = Array.from({ length: columnCount }, (_, index) => `<th>${escapeHtml(ultimatesDevelopmentLabel(index))}</th>`).join("");
  els.ultimatesHead.innerHTML = `<tr><th>Accident Year</th>${headerCells}</tr>`;
  els.ultimatesGrid.innerHTML = rows.map((row, rowIndex) => {
    const cells = Array.from({ length: columnCount }, (_, columnIndex) => {
      const inRow = Array.isArray(row) && columnIndex < row.length;
      const value = inRow ? row[columnIndex] : null;
      const display = numberOrNull(value) === null ? "" : displayNumber(value);
      const classes = ["ccUltimatesCell"];
      if (!inRow) classes.push("ccUltimatesOutsideCell");
      return `<td class="${classes.join(" ")}">${escapeHtml(display)}</td>`;
    }).join("");
    return `<tr><td class="ccUltimatesOriginCell">${escapeHtml(originLabel(rowIndex))}</td>${cells}</tr>`;
  }).join("");
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
  return buildCapeCodMethodPayload({
    details,
    originLabels: Array.from({ length: count }, (_, index) => originLabel(index)),
    latestValues: state.latestValues,
    exposureValues: state.exposureValues,
    priorUltimateValues: state.priorUltimateValues,
    priorUltimatePercentageDeveloped: state.priorUltimatePercentageDeveloped,
    priorUltimateMode: state.priorUltimateMode,
    trendRate: state.trendRate,
    autoTrendFit: state.autoTrendFit,
    decayFactor: state.decayFactor,
    scalingType: state.scalingType,
    alternativeUltimateCalculation: state.alternativeUltimateCalculation,
    trendFactorOverrides: state.trendFactorOverrides,
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
    els.exposureInput.value = text(method.exposure_dataset || els.exposureInput.value);
    els.priorUltimateInput.value = text(method.prior_ultimate_dataset || els.priorUltimateInput.value);
  });
  syncOriginLengthControl();
  state.statisticDecimalPlaces = statisticDecimalPlaces(details.statistic_decimal_places, 2);
  state.datasetCategory = text(details.dataset_category);
  state.priorUltimateMode = normalizeCapeCodPriorUltimateMode(method.prior_ultimate_mode);
  state.trendRate = numberOrNull(method.trend_rate) ?? 0;
  state.autoTrendFit = method.auto_trend_fit === true;
  state.decayFactor = numberOrNull(method.decay_factor) ?? 0;
  state.scalingType = normalizeCapeCodScalingType(method.scaling_type);
  state.alternativeUltimateCalculation = method.alternative_ultimate_calculation === true;
  state.trendFactorOverrides = columnFrom(method.trend_factor_overrides);
  state.originLabels = Array.isArray(method.origin_labels) ? method.origin_labels.map(String) : [];
  state.latestValues = columnFrom(method.latest_values);
  state.exposureValues = columnFrom(method.exposure_values);
  state.priorUltimateValues = columnFrom(method.prior_ultimate_values);
  state.priorUltimatePercentageDeveloped = columnFrom(method.prior_ultimate_percentage_developed);
  state.latestTriangleRows = [];
  state.latestDevelopmentLabels = [];
  state.localUltimatesTriangle = null;
  state.derived = {
    trendRate: state.trendRate,
    trendFactorOverrides: state.trendFactorOverrides.slice(),
    trendFactors: columnFrom(method.trend_factors),
    trendedLatestValues: columnFrom(method.trended_latest_values),
    percentageDeveloped: columnFrom(method.percentage_developed),
    developmentFactors: columnFrom(method.development_factors),
    developedExposureValues: columnFrom(method.developed_exposure_values),
    futureExposureValues: columnFrom(method.future_exposure_values),
    trendedDevelopedRatios: columnFrom(method.trended_developed_ratios),
    expectedUltimateRatios: columnFrom(method.expected_ultimate_ratios),
    detrendedExpectedRatios: columnFrom(method.detrended_expected_ratios),
    futureLatestValues: columnFrom(method.future_latest_values),
    capeCodUltimate: columnFrom(method.cape_cod_ultimate),
    capeCodUltimateRatios: columnFrom(method.cape_cod_ultimate_ratios),
  };
  state.methodMetadata = { ...metadata };
  state.methodLastModified = text(metadata.last_modified) || state.methodLastModified;
  syncTitles();
  syncMethodControls();
  renderMethodGrid();
  renderUltimatesGrid();
  renderCcChart();
}

function snapshotPayload() {
  return JSON.stringify({ method: buildPayload(), notes: els.notesInput?.value || "" });
}

function markClean() {
  cleanSnapshot = snapshotPayload();
  ccNotesController.markClean();
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
    exposureValues: state.exposureValues.slice(),
    priorUltimateValues: state.priorUltimateValues.slice(),
    priorUltimatePercentageDeveloped: state.priorUltimatePercentageDeveloped.slice(),
    priorUltimateMode: state.priorUltimateMode,
    trendRate: state.trendRate,
    autoTrendFit: state.autoTrendFit,
    decayFactor: state.decayFactor,
    scalingType: state.scalingType,
    alternativeUltimateCalculation: state.alternativeUltimateCalculation,
    trendFactorOverrides: state.trendFactorOverrides.slice(),
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
    els.exposureInput.value = text(localDetails.exposureDataset);
    els.priorUltimateInput.value = text(localDetails.priorUltimateDataset);
  });
  state.priorUltimateMode = normalizeCapeCodPriorUltimateMode(local.priorUltimateMode);
  state.autoTrendFit = local.autoTrendFit === true;
  state.decayFactor = numberOrNull(local.decayFactor) ?? 0;
  state.scalingType = normalizeCapeCodScalingType(local.scalingType);
  state.alternativeUltimateCalculation = local.alternativeUltimateCalculation === true;
  if (!state.autoTrendFit) state.trendRate = numberOrNull(local.trendRate) ?? 0;
  state.statisticDecimalPlaces = statisticDecimalPlaces(local.statisticDecimalPlaces, 2);
  state.datasetCategory = text(localDetails.datasetCategory);
  state.latestValues = norm(localDetails.latestDataset) === norm(persistedDetails.latestDataset)
    ? persisted.latestValues.slice()
    : local.latestValues.slice();
  state.exposureValues = norm(localDetails.exposureDataset) === norm(persistedDetails.exposureDataset)
    ? persisted.exposureValues.slice()
    : local.exposureValues.slice();
  const priorUltimateUnchanged =
    norm(localDetails.priorUltimateDataset) === norm(persistedDetails.priorUltimateDataset);
  state.priorUltimateValues = priorUltimateUnchanged
    ? persisted.priorUltimateValues.slice()
    : local.priorUltimateValues.slice();
  state.priorUltimatePercentageDeveloped = priorUltimateUnchanged
    ? persisted.priorUltimatePercentageDeveloped.slice()
    : local.priorUltimatePercentageDeveloped.slice();
  const usePersistedOriginLabels = validOriginLength(localDetails.originLength)
    === validOriginLength(persistedDetails.originLength)
    && persisted.originLabels.length > 0;
  const nextOriginLabels = usePersistedOriginLabels
    ? persisted.originLabels.slice()
    : local.originLabels.slice();
  state.trendFactorOverrides = usePersistedOriginLabels
    ? rebaseCapeCodTrendFactorOverridesByOriginLabel({
      localOriginLabels: local.originLabels,
      localOverrides: local.trendFactorOverrides,
      persistedOriginLabels: nextOriginLabels,
      persistedOverrides: persisted.trendFactorOverrides,
    })
    : local.trendFactorOverrides.slice();
  state.originLabels = nextOriginLabels;
  setNotesText(local.notes);
  syncOriginLengthControl();
  syncTitles();
  calculateOutputs();
  renderMethodGrid();
}

async function applyPersistedAggregate(result, options = {}) {
  const method = result?.method;
  if (!method || !isCapeCodV1Method(method)) {
    throw new Error(`${CC_METHOD_TYPE} load did not return a canonical v1 method.`);
  }
  const local = options.preserveOwnedState ? captureLocalOwnedState() : null;
  applyOutputSidecar(result?.sidecar || {}, { preserveNotes: !!local });
  await applyPayload(method);
  applyAggregateRevisions(result, method);
  state.serverUltimatesTriangle = Array.isArray(result?.ultimates_triangle)
    ? result.ultimates_triangle
    : null;
  renderUltimatesGrid();
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
  ccObjectChangeWatch.ensure({
    projectName: state.project,
    reservingClass: state.reservingClass,
    methodName: savedName,
    outputDataset: savedName,
    selfWriteStamp: result?.sidecar?.updated_at,
  });
  return true;
}

async function fetchPersistedCapeCod() {
  return loadCapeCodMethod({
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
    result = await fetchPersistedCapeCod();
  } catch (err) {
    if (Number(err?.status) === 404) return false;
    throw err;
  }
  if (requestSequence !== aggregateLoadSequence) return true;
  await applyPersistedAggregate(result);
  postStatus(`Loaded ${CC_METHOD_TYPE}: ${getDetails().name}`);
  return true;
}

async function reloadPersistedCapeCod(options = {}) {
  if (!getDetails().name) return false;
  const requestSequence = ++aggregateLoadSequence;
  const result = await fetchPersistedCapeCod();
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
const ccSaveProgress = createArcRhoSaveProgress({ subject: CC_METHOD_TYPE, projectName: () => state.project });

async function saveCapeCod() {
  return ccSaveProgress.run((progress) => runCapeCodSave(progress));
}

async function runCapeCodSave(progress) {
  const details = getDetails();
  if (!details.name || !details.outputType) {
    postStatus(`${CC_METHOD_TYPE} save requires Name and Output Type.`, "error");
    return { ok: false };
  }
  if (!details.latestDataset || !details.exposureDataset || !details.priorUltimateDataset) {
    postStatus(`${CC_METHOD_TYPE} save requires Latest, Exposure, and Prior Ultimate.`, "error");
    return { ok: false };
  }
  await refreshOriginLabels({ render: false });
  calculateOutputs();
  renderMethodGrid();
  const vector = state.derived.capeCodUltimate || [];
  if (!vector.some((value) => numberOrNull(value) !== null)) {
    postStatus(`${CC_METHOD_TYPE} output vector is blank. Check source selections.`, "error");
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
  ccObjectChangeWatch.pause();
  try {
    try {
      progress.writing();
      result = await saveCapeCodMethod(saveInput);
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
        ? `${CC_METHOD_TYPE} saved, but some dependent updates did not complete: ${
            String(result?.propagation?.message || "").trim() || details.name
          }`
        : `${CC_METHOD_TYPE} saved: ${details.name}${aggregatedCsvPaths.length ? ` (+${aggregatedCsvPaths.length} aggregated)` : ""}`,
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
    ccObjectChangeWatch.resume();
  }
}

function setNotesText(value) {
  const next = String(value ?? "");
  ccNotesController.setValue(next, { markClean: true });
}

async function openPicker(kind, anchor) {
  await loadCachedRows().catch(() => {});
  const titles = {
    output: "Select Output Vector",
    latest: "Select Latest",
    exposure: "Select Exposure",
    prior_ultimate: "Select Prior Ultimate",
  };
  const allowedDataFormats = kind === "latest" ? ["Triangle"] : ["Vector"];
  await openDatasetNamePicker({
    projectName: state.project,
    initialName: kind === "output"
      ? els.outputTypeInput?.value
      : kind === "latest"
        ? els.latestInput?.value
        : kind === "exposure"
          ? els.exposureInput?.value
          : els.priorUltimateInput?.value,
    anchorElement: anchor instanceof Element ? anchor : null,
    title: titles[kind] || "Select Dataset",
    allowedDataFormats,
    includeCalculated: true,
    emptyMessage: kind === "latest" ? "No cached triangle datasets found." : "No cached vector datasets found.",
    itemFilter: (item) => {
      const record = cachedRecordByName(item?.name);
      if (!record && kind !== "output") return false;
      if (kind === "latest") return norm(record?.dataFormat) === "triangle";
      if (kind === "exposure" || kind === "prior_ultimate") return norm(record?.dataFormat) === "vector";
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
      if (kind === "output") {
        const record = cachedRecordByName(selected);
        state.datasetCategory = text(item?.dataset_category || item?.category || record?.category);
      }
      withProgrammatic(() => {
        if (kind === "output") els.outputTypeInput.value = selected;
        if (kind === "latest") els.latestInput.value = selected;
        if (kind === "exposure") els.exposureInput.value = selected;
        if (kind === "prior_ultimate") els.priorUltimateInput.value = selected;
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
    const discard = await ccCloseConfirm.confirm({ reason: "close" });
    if (!discard) return;
  }
  requestConfirmedClose();
}

async function initTabbedPage() {
  const container = document.getElementById("ccTabbedPage");
  tabbedPage = createTabbedPage(container, {
    tabs: CC_TABS,
    cssPrefix: "cc",
    initialTab: ALLOWED_CC_TABS.has(text(params.get("tab") || params.get("initial_tab"))) ? text(params.get("tab") || params.get("initial_tab")) : "details",
    onTabChange: (tabId) => {
      if (tabId === "ratios") requestAnimationFrame(() => ccChart?.refresh());
      try {
        window.parent?.postMessage({ type: "arcrho:cc-tab-changed", inst, tab: tabId }, "*");
      } catch {}
    },
  });
  applyTabbedPageSaveBar(document.getElementById("ccSaveBar"));
  wireTabPopoutWindows({
    cssPrefix: "cc",
    tabs: CC_TABS,
    tabSystem: () => tabbedPage,
    getTitle: () => `${getDetails().name || CC_METHOD_TYPE} - ${CC_METHOD_TYPE}`,
  });
  ccChart = createCapeCodRatiosChart({
    canvas: els.chartCanvas,
    legend: els.chartLegend,
    emptyState: els.chartEmpty,
    tooltip: els.chartTooltip,
  });
  renderCcChart();
}

function formatTrendRatePercent(rate) {
  const n = numberOrNull(rate);
  if (n === null) return "0.000000%";
  return `${(n * 100).toFixed(6)}%`;
}

function altUltimateRuleEnabled() {
  const count = rowCount();
  for (let index = 0; index < count; index += 1) {
    const latest = numberOrNull(state.latestValues[index]);
    const pct = numberOrNull(state.derived.percentageDeveloped?.[index]);
    if (latest !== null && latest !== 0 && pct === 0) return true;
  }
  return false;
}

function syncMethodControls() {
  if (els.trendRateInput && document.activeElement !== els.trendRateInput) {
    els.trendRateInput.value = formatTrendRatePercent(state.trendRate);
  }
  if (els.trendRateInput) els.trendRateInput.readOnly = state.autoTrendFit;
  if (els.fitBtn) els.fitBtn.disabled = state.autoTrendFit;
  if (els.autoFitInput) els.autoFitInput.checked = state.autoTrendFit;
  if (els.decayInput && document.activeElement !== els.decayInput) {
    els.decayInput.value = String(numberOrNull(state.decayFactor) ?? 0);
  }
  if (els.scalingLabel) els.scalingLabel.textContent = SCALING_LABELS[state.scalingType] || SCALING_LABELS.percentage;
  for (const option of els.scalingMenu?.querySelectorAll("[data-value]") || []) {
    option.setAttribute("aria-selected", option.dataset.value === state.scalingType ? "true" : "false");
  }
  if (els.priorModeLabel) els.priorModeLabel.textContent = PRIOR_MODE_LABELS[state.priorUltimateMode] || PRIOR_MODE_LABELS.latest_ultimates;
  for (const option of els.priorModeMenu?.querySelectorAll("[data-value]") || []) {
    option.setAttribute("aria-selected", option.dataset.value === state.priorUltimateMode ? "true" : "false");
  }
  if (els.methodDecimalsInput) els.methodDecimalsInput.value = String(state.statisticDecimalPlaces);
  if (els.altUltimateInput) {
    els.altUltimateInput.checked = state.alternativeUltimateCalculation;
    els.altUltimateInput.disabled = !altUltimateRuleEnabled();
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
  closeScalingDropdown();
  closePriorModeDropdown();
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

function closeScalingDropdown() {
  els.scalingDropdown?.classList.remove("open");
  els.scalingButton?.setAttribute("aria-expanded", "false");
}

function closePriorModeDropdown() {
  els.priorModeDropdown?.classList.remove("open");
  els.priorModeButton?.setAttribute("aria-expanded", "false");
}

function setStatisticDecimals(value) {
  state.statisticDecimalPlaces = statisticDecimalPlaces(value, state.statisticDecimalPlaces);
  syncMethodControls();
  renderMethodGrid();
  renderCcChart();
  markDirty();
}

function clearAllTrendFactorOverrides() {
  state.trendFactorOverrides = state.trendFactorOverrides.map(() => null);
}

function commitTrendRateInput() {
  const raw = text(els.trendRateInput?.value).replace(/%/g, "");
  const parsed = numberOrNull(raw);
  if (parsed === null) {
    syncMethodControls();
    return;
  }
  const nextRate = roundCapeCodRate(parsed / 100);
  if (nextRate === state.trendRate) {
    syncMethodControls();
    return;
  }
  state.trendRate = nextRate;
  clearAllTrendFactorOverrides();
  calculateOutputs();
  renderMethodGrid();
  markDirty();
}

function runTrendRateFit() {
  if (state.autoTrendFit) return;
  const fitted = fitCapeCodTrendRate(
    roundCapeCodVector(state.latestValues),
    state.derived.developedExposureValues,
  );
  state.trendRate = fitted;
  clearAllTrendFactorOverrides();
  calculateOutputs();
  renderMethodGrid();
  markDirty();
  postStatus(`Fitted trend rate: ${formatTrendRatePercent(fitted)}`);
}

function setDecayFactor(value) {
  const parsed = numberOrNull(value);
  if (parsed === null) {
    syncMethodControls();
    return;
  }
  const clamped = Math.max(0, Math.min(1, parsed));
  const next = roundCapeCodRate(clamped);
  if (next === state.decayFactor) {
    syncMethodControls();
    return;
  }
  state.decayFactor = next;
  calculateOutputs();
  renderMethodGrid();
  markDirty();
}

function stepDecayFactor(direction) {
  const current = numberOrNull(state.decayFactor) ?? 0;
  setDecayFactor(Math.round((current + direction * 0.05) * 100) / 100);
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
  els.priorModeButton?.addEventListener("click", () => {
    const open = !els.priorModeDropdown?.classList.contains("open");
    closeScalingDropdown();
    closeOriginLengthDropdown();
    els.priorModeDropdown?.classList.toggle("open", open);
    els.priorModeButton.setAttribute("aria-expanded", open ? "true" : "false");
  });
  els.priorModeMenu?.addEventListener("click", (event) => {
    const option = event.target.closest("button[data-value]");
    if (!option) return;
    const nextMode = normalizeCapeCodPriorUltimateMode(option.dataset.value);
    const changed = state.priorUltimateMode !== nextMode;
    state.priorUltimateMode = nextMode;
    closePriorModeDropdown();
    syncMethodControls();
    if (!changed) return;
    calculateOutputs();
    renderMethodGrid();
    markDirty();
  });
  els.trendRateInput?.addEventListener("change", commitTrendRateInput);
  els.trendRateInput?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitTrendRateInput();
    }
  });
  els.fitBtn?.addEventListener("click", runTrendRateFit);
  els.autoFitInput?.addEventListener("change", () => {
    state.autoTrendFit = !!els.autoFitInput.checked;
    if (state.autoTrendFit) clearAllTrendFactorOverrides();
    calculateOutputs();
    renderMethodGrid();
    markDirty();
  });
  els.decayInput?.addEventListener("change", () => setDecayFactor(els.decayInput.value));
  els.decayUp?.addEventListener("click", () => stepDecayFactor(1));
  els.decayDown?.addEventListener("click", () => stepDecayFactor(-1));
  els.scalingButton?.addEventListener("click", () => {
    const open = !els.scalingDropdown?.classList.contains("open");
    closePriorModeDropdown();
    closeOriginLengthDropdown();
    els.scalingDropdown?.classList.toggle("open", open);
    els.scalingButton.setAttribute("aria-expanded", open ? "true" : "false");
  });
  els.scalingMenu?.addEventListener("click", (event) => {
    const option = event.target.closest("button[data-value]");
    if (!option) return;
    const nextScaling = normalizeCapeCodScalingType(option.dataset.value);
    const changed = state.scalingType !== nextScaling;
    state.scalingType = nextScaling;
    closeScalingDropdown();
    syncMethodControls();
    renderMethodGrid();
    renderCcChart();
    if (changed) markDirty();
  });
  els.altUltimateInput?.addEventListener("change", () => {
    state.alternativeUltimateCalculation = !!els.altUltimateInput.checked;
    calculateOutputs();
    renderMethodGrid();
    markDirty();
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
    if (els.scalingDropdown?.classList.contains("open") && !event.target.closest("#ccScalingDropdown")) closeScalingDropdown();
    if (els.priorModeDropdown?.classList.contains("open") && !event.target.closest("#ccPriorModeDropdown")) closePriorModeDropdown();
    if (els.originLengthDropdown?.classList.contains("open") && !event.target.closest("#ccOriginLengthDropdown")) closeOriginLengthDropdown();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    closeScalingDropdown();
    closePriorModeDropdown();
  });
  els.methodDecimalsInput?.addEventListener("input", () => setStatisticDecimals(els.methodDecimalsInput.value));
  els.methodDecimalsInput?.addEventListener("change", () => setStatisticDecimals(els.methodDecimalsInput.value));
  els.methodDecimalsUp?.addEventListener("click", () => setStatisticDecimals(state.statisticDecimalPlaces + 1));
  els.methodDecimalsDown?.addEventListener("click", () => setStatisticDecimals(state.statisticDecimalPlaces - 1));
  syncMethodControls();
  syncOriginLengthControl();
  els.saveBtn?.addEventListener("click", async () => {
    try {
      const saved = await saveCapeCod();
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
    if (ccCloseConfirm.isOpen) return true;
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
        const saved = await saveCapeCod();
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
  applyHostFixedDetailsFields({ root: "#ccDetailsPage" });
  syncDetailsLabelWidth({
    root: "#ccDetailsPage",
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
    postStatus(`Could not load existing ${CC_METHOD_TYPE}: ${String(err?.message || err)}`, "error");
    return false;
  });
  void refreshDetailsDependencies();
  if (loaded) {
    postStatus(`${CC_METHOD_TYPE} ready.`);
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
