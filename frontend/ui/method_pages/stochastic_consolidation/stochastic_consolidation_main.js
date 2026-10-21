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
import { createDetailsDependenciesController } from "/ui/shared/tabs/details/details_dependencies.js?v=20261020b";
import { applyHostFixedDetailsFields } from "/ui/shared/tabs/details/details_host_fields.js?v=20260820b";
import { createAuditLogView } from "/ui/shared/tabs/audit_log/audit_log_view.js?v=20260714c";
import {
  formatSidecarAuditEventDate,
  normalizeSidecarAuditEntries,
} from "/ui/shared/tabs/audit_log/sidecar_audit_entries.js?v=20260714c";
import { attachArcrhoTooltip } from "/ui/shared/components/tooltip/tooltip.js?v=20260925a";
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
import { STOCHASTIC_CONSOLIDATION_TAB_DEFS, windowTabIds } from "/ui/shared/tabs/window_tab_catalog.js?v=20260903a";
import { createDistributionChart } from "/ui/shared/components/reserve_range/reserve_distribution_chart.js?v=20260924b";
import { createMethodGridSelection, tagMethodGridCells } from "/ui/shared/components/spreadsheet/method_grid_selection.js";
import { showSimulationRun } from "/ui/shared/components/simulation_run/simulation_run.js";
import { wireFramedScrollActivity } from "/ui/shared/styles/framed_scroll_activity.js";
import { createFanChart } from "/ui/shared/components/reserve_range/reserve_fan_chart.js?v=20260924b";
import {
  escapeRangeHtml as escapeHtml,
  formatRangeNumber as formatNumber,
  formatRangePercent as formatPercent,
  ladderLoadingMarkup,
  ladderTableParts,
  summaryTableMarkup,
} from "/ui/shared/components/reserve_range/reserve_range_table.js?v=20260924b";
import { createVirtualRows } from "/ui/shared/components/virtual_rows/virtual_rows.js";
import {
  RANGE_DEFAULT_PERCENTILES,
  RANGE_LADDER_INTERVAL_OPTIONS,
  RANGE_MEASURE_OPTIONS,
  RANGE_STORED_LADDER_INTERVAL,
  distributionChartData,
  fanChartData,
  formatPercentileList,
  formatRunDuration,
  ladderIntervalIsStored,
  parsePercentileList,
  resultsClipboardText,
  resultsCsvText,
  resultsView,
} from "/ui/shared/components/reserve_range/reserve_range_model.js?v=20260924a";
import {
  consolidateStochasticConsolidation,
  listStochasticConsolidationCandidates,
  loadStochasticConsolidation,
  saveStochasticConsolidation,
} from "/ui/method_pages/stochastic_consolidation/stochastic_consolidation_method_api.js?v=20260923a";
import {
  SCON_CORRELATION_OPTIONS,
  SCON_DEPENDENCY_OPTIONS,
  SCON_MATRIX_VIEWS,
  SCON_METHOD_TYPE,
  achievedMatrices,
  applyConsolidationSettings,
  availableCandidates,
  baseTypeChoices,
  commonSimulationCount,
  consolidationRunState,
  hasConsolidationRun,
  newRandomSeed,
  optionLabel,
  optionTargetMatrix,
  parseCorrelationInput,
  readConsolidationSettings,
  reorderTargetMatrix,
  runInputSnapshot,
  segmentBreakdown,
  segmentInfoMap,
  segmentKey,
  segmentRows,
  segmentShortLabel,
  setTargetCorrelation,
  storedAdjustedMatrix,
  usedCorrelationMatrix,
} from "/ui/method_pages/stochastic_consolidation/stochastic_consolidation_page_model.js?v=20260924a";
import { bootTableColors } from "/ui/shared/components/spreadsheet/table_colors.js?v=20260927b";

// The user's table colours, shared by every method page.
bootTableColors();

const ALLOWED_TABS = windowTabIds("stochastic_consolidation");
const params = new URLSearchParams(window.location.search || "");
const inst = text(params.get("inst")) || `scon_${Date.now()}`;

const state = {
  project: text(params.get("project")),
  reservingClass: text(params.get("class") || params.get("path")),
  method: null,
  persisted: false,
  settings: readConsolidationSettings({}),
  cachedRows: [],
  ownedRevision: "",
  derivedRevision: "",
  needsReview: false,
  // What the page knows about each included bootstrap (load, run, picker).
  segmentInfo: new Map(),
  candidates: null,
  candidatesPromise: null,
  selectedSegment: -1,
  // The run on screen: the settings it was made from (null when the stored
  // run does not describe the stored settings), whether a segment changed
  // since, and whether it came from Consolidate and is not saved yet.
  runSnapshot: null,
  segmentChanged: false,
  runUnsaved: false,
  running: false,
  lastRunMs: null,
  matrixView: "target",
  matrixError: "",
  invalidCell: null,
  // Results view choices: page state, never saved with the method.
  results: {
    measure: "reserves",
    percentiles: RANGE_DEFAULT_PERCENTILES.slice(),
    fullLadder: false,
    interval: RANGE_STORED_LADDER_INTERVAL,
  },
  // The run's finest ladder ({ run, scaled }), which Consolidate hands over
  // with the run, and the request working one out for a stored run.
  finerLadder: null,
  ladderRequest: null,
};

let cleanSnapshot = "";
let isDirty = false;
let tabbedPage = null;
let distributionChart = null;
let fanChart = null;
let menuState = null;

const els = {
  consolidateBtn: document.getElementById("sconConsolidateBtn"),
  saveBtn: document.getElementById("sconSaveBtn"),
  cancelBtn: document.getElementById("sconCancelBtn"),
  nameInput: document.getElementById("sconNameInput"),
  outputTypeInput: document.getElementById("sconOutputTypeInput"),
  outputTypeBtn: document.getElementById("sconOutputTypeBtn"),
  projectInput: document.getElementById("sconProjectInput"),
  classInput: document.getElementById("sconClassInput"),
  baseTypeButton: document.getElementById("sconBaseTypeButton"),
  originLengthInput: document.getElementById("sconOriginLengthInput"),
  developmentLengthInput: document.getElementById("sconDevelopmentLengthInput"),
  simulationCountInput: document.getElementById("sconSimulationCountInput"),
  seedInput: document.getElementById("sconSeedInput"),
  newSeedBtn: document.getElementById("sconNewSeedBtn"),
  addSegmentBtn: document.getElementById("sconAddSegmentBtn"),
  removeSegmentBtn: document.getElementById("sconRemoveSegmentBtn"),
  moveUpBtn: document.getElementById("sconMoveUpBtn"),
  moveDownBtn: document.getElementById("sconMoveDownBtn"),
  segmentsBody: document.getElementById("sconSegmentsBody"),
  segmentsCaption: document.getElementById("sconSegmentsCaption"),
  correlationControl: document.getElementById("sconCorrelationControl"),
  dependencyButton: document.getElementById("sconDependencyButton"),
  degreesField: document.getElementById("sconDegreesField"),
  degreesInput: document.getElementById("sconDegreesInput"),
  matrixViewControl: document.getElementById("sconMatrixViewControl"),
  matrices: document.getElementById("sconMatrices"),
  matrixError: document.getElementById("sconMatrixError"),
  matrixCaption: document.getElementById("sconMatrixCaption"),
  resultsBody: document.getElementById("sconResultsBody"),
  resultsEmpty: document.getElementById("sconResultsEmpty"),
  resultsEmptyText: document.getElementById("sconResultsEmptyText"),
  emptyConsolidateBtn: document.getElementById("sconEmptyConsolidateBtn"),
  measureControl: document.getElementById("sconMeasureControl"),
  percentileInput: document.getElementById("sconPercentileInput"),
  percentileResetBtn: document.getElementById("sconPercentileResetBtn"),
  fullLadderInput: document.getElementById("sconFullLadderInput"),
  intervalButton: document.getElementById("sconIntervalButton"),
  copyResultsBtn: document.getElementById("sconCopyResultsBtn"),
  downloadResultsBtn: document.getElementById("sconDownloadResultsBtn"),
  resultsStale: document.getElementById("sconResultsStale"),
  resultsStaleText: document.getElementById("sconResultsStaleText"),
  staleConsolidateBtn: document.getElementById("sconStaleConsolidateBtn"),
  resultsHead: document.getElementById("sconResultsHead"),
  resultsTableBody: document.getElementById("sconResultsTableBody"),
  resultsCaption: document.getElementById("sconResultsCaption"),
  distributionTitle: document.getElementById("sconDistributionTitle"),
  distributionChart: document.getElementById("sconDistributionChart"),
  distributionEmpty: document.getElementById("sconDistributionEmpty"),
  distributionTooltip: document.getElementById("sconDistributionTooltip"),
  fanTitle: document.getElementById("sconFanTitle"),
  fanChart: document.getElementById("sconFanChart"),
  fanLegend: document.getElementById("sconFanLegend"),
  fanEmpty: document.getElementById("sconFanEmpty"),
  fanTooltip: document.getElementById("sconFanTooltip"),
  breakdownBody: document.getElementById("sconBreakdownBody"),
  breakdownCaption: document.getElementById("sconBreakdownCaption"),
  menu: document.getElementById("sconMenu"),
  cellContextMenu: document.getElementById("sconCellContextMenu"),
};

const closeConfirm = createPageCloseConfirm({ subject: SCON_METHOD_TYPE });
const saveProgress = createArcRhoSaveProgress({ subject: SCON_METHOD_TYPE, projectName: () => state.project });
const notesController = mountNotesTab({
  container: document.getElementById("sconNotesMount"),
  ariaLabel: "Stochastic Consolidation notes",
  onChange: () => markDirty(),
  onStatus: postStatus,
});
const auditLogView = createAuditLogView({
  container: document.getElementById("sconAuditLogMount"),
  ariaLabel: "Stochastic Consolidation audit log",
  emptyDescription: "Method saves will appear here after the first save.",
  normalizeEntries: normalizeSidecarAuditEntries,
  formatEventDate: formatSidecarAuditEventDate,
});
// Open-window change alert (advisory): fires once when another user or the
// dependent-propagation job rewrites this method while it is open.
const objectChangeWatch = createMethodObjectChangeWatchController({
  methodType: "stochastic_consolidation",
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
  watch: objectChangeWatch,
  getProject: () => state.project,
  getReservingClass: () => state.reservingClass,
});
const detailsDependencies = createDetailsDependenciesController({
  dependencyMap: "sconDependencyMap",
  getSelfMethodType: () => "Stochastic Consolidation",
  getIdentity: () => ({
    projectName: state.project,
    reservingClass: state.reservingClass,
    datasetName: state.settings.name,
  }),
  instanceId: inst,
  isProjectInstanceHost: window.parent !== window,
  setStatus: (message) => postStatus(message),
});
// The value grids select and copy like the other method pages' grids. The
// correlation matrices join as they are drawn, since each draw builds new
// tables.
// A full ladder longer than this draws only the rows in view: a 0.01% ladder
// is some 10,000 rows.
const VIRTUAL_LADDER_ROWS = 300;
let ladderParts = null;
const resultsRows = createVirtualRows({
  host: els.resultsTableBody.closest(".sconTableWrap"),
  body: els.resultsTableBody,
  onRender: () => cellSelection.applyDom(),
});
const resultsVirtual = {
  bounds: () => (resultsRows.isActive()
    ? { maxRow: resultsRows.rowCount() - 1, maxCol: ladderParts.rows[0].values.length - 1 }
    : undefined),
  cellValue: ({ r, c }) => (resultsRows.isActive() ? ladderParts.copyValue(r, c) : undefined),
  scrollToRow: (r) => {
    if (resultsRows.isActive()) resultsRows.scrollToRow(r);
  },
};
const cellSelection = createMethodGridSelection({
  tables: [els.resultsTableBody, els.breakdownBody].map((body, index) => {
    const table = body.closest("table");
    return {
      key: `grid${index}`,
      table,
      scrollHost: table.closest(".sconTableWrap"),
      virtual: index === 0 ? resultsVirtual : null,
    };
  }),
  contextMenu: els.cellContextMenu,
  onCopied: () => postStatus("Copied the selected values."),
});
let postedRunState = "";

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

function postStatus(message, tone = "") {
  try {
    window.parent?.postMessage({ type: "arcrho:status", text: text(message), ...(tone ? { tone } : {}) }, "*");
  } catch {}
}

function snapshotPage() {
  return JSON.stringify({ settings: state.settings, notes: notesController.elements.input?.value || "" });
}

function hasRun() {
  return hasConsolidationRun(state.method);
}

function currentRunState() {
  return consolidationRunState({
    hasRun: hasRun(),
    settingsMatchRun: state.runSnapshot !== null && state.runSnapshot === runInputSnapshot(state.settings),
    segmentChanged: state.segmentChanged,
    running: state.running,
  });
}

// A selected cell copies its raw figure rather than the formatted text.
function copyValue(value) {
  const n = numberOrNull(value);
  return n === null ? "" : String(n);
}

function refreshGrid(body) {
  tagMethodGridCells(body.closest("table"));
  cellSelection.applyDom();
}

// The run state shows as a chip beside the window title, which Project
// Instance draws.
function postRunState(run) {
  const key = `${run.key}|${run.label}`;
  if (key === postedRunState) return;
  postedRunState = key;
  try {
    window.parent?.postMessage({ type: "arcrho:window-run-state", inst, state: run.key, label: run.label }, "*");
  } catch {}
}

function syncHeader() {
  const name = state.settings.name;
  document.title = name ? `${name} - ${SCON_METHOD_TYPE}` : SCON_METHOD_TYPE;
  const run = currentRunState();
  postRunState(run);
  const canRun = !state.running && state.settings.segments.length > 0;
  for (const button of [els.consolidateBtn, els.emptyConsolidateBtn, els.staleConsolidateBtn]) button.disabled = !canRun;
  const stale = run.key === "changed" || run.key === "segment";
  els.resultsStale.hidden = !stale;
  els.resultsStaleText.textContent = run.key === "segment"
    ? "A segment's bootstrap changed since this run, so these results describe the bootstraps as they were."
    : "The inputs changed since this run, so these results describe the earlier settings.";
}

function syncSaveControls() {
  updateTabbedPageSaveControls({
    saveButton: els.saveBtn,
    cancelButton: els.cancelBtn,
    dirty: isDirty,
    needsReview: state.needsReview,
  });
}

function postDirty(dirty, force = false) {
  const next = !!dirty;
  if (!force && isDirty === next) {
    syncHeader();
    return;
  }
  isDirty = next;
  syncSaveControls();
  syncHeader();
  try {
    window.parent?.postMessage({ type: "arcrho:dataset-dirty", inst, dirty: next }, "*");
  } catch {}
}

/* The page is dirty when a setting or the notes differ from the last load or
   save, or when a Consolidate produced a run that is not saved yet. */
function markDirty() {
  postDirty(snapshotPage() !== cleanSnapshot || state.runUnsaved);
}

function markClean() {
  cleanSnapshot = snapshotPage();
  notesController.markClean();
  postDirty(false, true);
}

function updateSettings(patch) {
  state.settings = { ...state.settings, ...patch };
  markDirty();
}

/* ---------------------------------------------------------------------------
   One dropdown menu serves every select-like control on the page, so each
   opened list looks and behaves the same.
--------------------------------------------------------------------------- */

function closeMenu({ focusAnchor = false } = {}) {
  if (!menuState) return;
  const { anchor } = menuState;
  anchor.setAttribute("aria-expanded", "false");
  anchor.classList.remove("open");
  els.menu.hidden = true;
  els.menu.innerHTML = "";
  menuState = null;
  if (focusAnchor) anchor.focus();
}

/* Options carry a value and a label, and optionally a second line (meta)
   and a tooltip (title), which the segment picker uses. */
function openMenu(anchor, options, current, onSelect, { emptyText = "" } = {}) {
  if (menuState?.anchor === anchor) {
    closeMenu();
    return;
  }
  closeMenu();
  els.menu.innerHTML = options.length
    ? options.map((option, index) => {
      const rich = !!option.meta;
      return `<button class="sconMenuOption${rich ? " sconCandidateOption" : ""}" type="button" role="option"
        data-index="${index}" aria-selected="${option.value === current ? "true" : "false"}">${rich
          ? `<span class="sconCandidateName">${escapeHtml(option.label)}</span><span class="sconCandidateMeta">${escapeHtml(option.meta)}</span>`
          : escapeHtml(option.label)}</button>`;
    }).join("")
    : `<div class="sconMenuEmpty">${escapeHtml(emptyText || "Nothing to choose.")}</div>`;
  for (const button of els.menu.querySelectorAll(".sconMenuOption")) {
    const option = options[Number(button.dataset.index)];
    if (option?.title) attachArcrhoTooltip(button, option.title);
  }
  const rect = anchor.getBoundingClientRect();
  els.menu.style.minWidth = `${Math.round(rect.width)}px`;
  els.menu.style.maxWidth = `${Math.max(240, Math.min(560, window.innerWidth - 16))}px`;
  els.menu.hidden = false;
  const menuHeight = els.menu.offsetHeight;
  const below = rect.bottom + 3 + menuHeight <= window.innerHeight - 4;
  els.menu.style.left = `${Math.round(Math.max(4, Math.min(rect.left, window.innerWidth - els.menu.offsetWidth - 4)))}px`;
  els.menu.style.top = `${Math.round(below ? rect.bottom + 3 : Math.max(4, rect.top - 3 - menuHeight))}px`;
  anchor.setAttribute("aria-expanded", "true");
  anchor.classList.add("open");
  menuState = { anchor, onSelect, options };
  (els.menu.querySelector("[aria-selected='true']") || els.menu.querySelector(".sconMenuOption"))?.focus();
}

function wireMenu() {
  els.menu.addEventListener("click", (event) => {
    const button = event.target.closest(".sconMenuOption");
    if (!button || !menuState) return;
    const { onSelect, options } = menuState;
    const option = options[Number(button.dataset.index)];
    closeMenu({ focusAnchor: true });
    if (option) onSelect(option.value, option);
  });
  els.menu.addEventListener("keydown", (event) => {
    const options = Array.from(els.menu.querySelectorAll(".sconMenuOption"));
    const index = options.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      options[(index + step + options.length) % options.length]?.focus();
    } else if (event.key === "Escape" || event.key === "Tab") {
      event.preventDefault();
      closeMenu({ focusAnchor: true });
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!menuState) return;
    if (els.menu.contains(event.target) || menuState.anchor.contains(event.target)) return;
    closeMenu();
  }, true);
  window.addEventListener("resize", () => closeMenu());
  document.querySelector(".sconPageHost")?.addEventListener("scroll", () => closeMenu(), true);
}

function setDropdown(button, options, value, disabled = false) {
  button.querySelector(".sconDropdownValue").textContent = optionLabel(options, value) || "(None)";
  button.disabled = disabled;
}

function segmentedMarkup(options, current, available = null) {
  return options.map((option) => {
    const enabled = !available || available.includes(option.value);
    return `<button class="sconSegment" type="button" role="radio" data-value="${option.value}"
      aria-checked="${option.value === current ? "true" : "false"}" ${enabled ? "" : "disabled"}>${escapeHtml(option.label)}</button>`;
  }).join("");
}

/* ---------------------------------------------------------------------------
   Details
--------------------------------------------------------------------------- */

function currentSegmentRows() {
  return segmentRows(state.settings, state.segmentInfo, { hasRun: hasRun() });
}

function renderDetails() {
  const s = state.settings;
  els.nameInput.value = s.name;
  els.nameInput.readOnly = state.persisted;
  els.outputTypeInput.value = s.outputType;
  setDropdown(els.baseTypeButton, baseTypeChoices(s, state.segmentInfo), s.baseTriangleType);
  els.originLengthInput.value = String(s.originLength);
  els.developmentLengthInput.value = String(s.developmentLength);
  els.simulationCountInput.value = commonSimulationCount(currentSegmentRows()).text;
  if (document.activeElement !== els.seedInput) els.seedInput.value = String(s.randomSeed);
}

/* ---------------------------------------------------------------------------
   Segments
--------------------------------------------------------------------------- */

function issueMarkup(row) {
  const issues = row.issues.map((issue) => `<span class="sconIssue${
    issue.kind === "missing" || issue.kind === "duplicate" ? " isError" : ""}">${escapeHtml(issue.text)}</span>`);
  if (row.note) issues.push(`<span class="sconIssueNote">${escapeHtml(row.note)}</span>`);
  return issues.length ? issues.join("") : `<span class="sconIssueOk">Ready</span>`;
}

function renderSegments() {
  const rows = currentSegmentRows();
  if (state.selectedSegment >= rows.length) state.selectedSegment = rows.length - 1;
  if (!rows.length) {
    els.segmentsBody.innerHTML = `<tr><td class="sconEmptyRow" colspan="9">No segments yet. Add Segment lists the bootstraps in the project's other reserving classes.</td></tr>`;
  } else {
    els.segmentsBody.innerHTML = rows.map((row) => `<tr data-segment-row="${row.index}"${
      row.index === state.selectedSegment ? " class=\"isSelected\" aria-selected=\"true\"" : ""}>
      <td class="sconIndexCell">${row.index + 1}</td>
      <td class="sconCell sconTextCell" data-full-class="${escapeHtml(row.reservingClass)}">${escapeHtml(row.shortLabel)}</td>
      <td class="sconCell sconEntryCell sconMethodCell">
        <button class="sconCellDropdown" type="button" data-method-row="${row.index}" aria-haspopup="listbox" aria-expanded="false"
          aria-label="${escapeHtml(`Method for ${row.shortLabel}`)}">
          <span class="sconDropdownValue">${escapeHtml(row.methodName)}</span><span class="sconDropdownCaret" aria-hidden="true"></span>
        </button>
      </td>
      <td class="sconCell sconEntryCell"><input class="sconCellInput" type="text" inputmode="decimal" data-factor-row="${row.index}"
        value="${escapeHtml(String(row.factor))}" aria-label="${escapeHtml(`Factor for ${row.shortLabel}`)}"></td>
      <td class="sconCell sconDerivedCell">${formatNumber(row.simulationCount)}</td>
      <td class="sconCell sconDerivedCell">${formatNumber(row.mean)}</td>
      <td class="sconCell sconDerivedCell">${formatNumber(row.sd)}</td>
      <td class="sconCell sconDerivedCell">${formatPercent(row.cv)}</td>
      <td class="sconCell sconIssueCell">${issueMarkup(row)}</td>
    </tr>`).join("");
    for (const cell of els.segmentsBody.querySelectorAll("[data-full-class]")) {
      attachArcrhoTooltip(cell, cell.dataset.fullClass);
    }
  }
  const selected = state.selectedSegment;
  els.removeSegmentBtn.disabled = selected < 0;
  els.moveUpBtn.disabled = selected <= 0;
  els.moveDownBtn.disabled = selected < 0 || selected >= rows.length - 1;
  const problems = rows.filter((row) => row.issues.length).length;
  els.segmentsCaption.textContent = rows.length
    ? [
      "Mean reserve, standard deviation and CV are each bootstrap's own saved scaled results.",
      problems ? `${problems} of ${rows.length} segments cannot be consolidated as they stand.` : "",
    ].filter(Boolean).join(" ")
    : "";
}

/* Applies a new segment list: `order` names, for each new position, the old
   index it came from (-1 for a new segment), so the correlations follow. */
function applySegmentOrder(segments, order, selected) {
  updateSettings({
    segments,
    targetCorrelations: reorderTargetMatrix(state.settings.targetCorrelations, order),
  });
  state.selectedSegment = selected;
  renderSetupTabs();
}

function moveSelectedSegment(step) {
  const from = state.selectedSegment;
  const to = from + step;
  const count = state.settings.segments.length;
  if (from < 0 || to < 0 || to >= count) return;
  const order = Array.from({ length: count }, (_, index) => index);
  [order[from], order[to]] = [order[to], order[from]];
  applySegmentOrder(order.map((index) => state.settings.segments[index]), order, to);
}

function removeSelectedSegment() {
  const index = state.selectedSegment;
  if (index < 0) return;
  const order = state.settings.segments.map((_, i) => i).filter((i) => i !== index);
  applySegmentOrder(order.map((i) => state.settings.segments[i]), order, Math.min(index, order.length - 1));
}

async function loadCandidates() {
  if (state.candidates) return state.candidates;
  if (!state.candidatesPromise) {
    state.candidatesPromise = listStochasticConsolidationCandidates({
      project_name: state.project,
      reserving_class: state.reservingClass,
    }).then((result) => {
      state.candidates = Array.isArray(result?.candidates) ? result.candidates : [];
      state.segmentInfo = segmentInfoMap(state.candidates, Array.from(state.segmentInfo.values()));
      return state.candidates;
    }).catch((err) => {
      state.candidatesPromise = null;
      throw err;
    });
  }
  return state.candidatesPromise;
}

function candidateMeta(row) {
  return [
    row.has_run === false ? "no saved run" : `mean ${formatNumber(row.mean)}`,
    row.has_run === false ? "" : `CV ${formatPercent(row.cv)}`,
    row.simulation_count ? `${formatNumber(row.simulation_count)} simulations` : "",
  ].filter(Boolean).join(" · ");
}

async function openAddSegmentMenu() {
  let candidates;
  try {
    candidates = await loadCandidates();
  } catch (err) {
    postStatus(`Could not list the project's bootstraps: ${String(err?.message || err)}`, "error");
    return;
  }
  const options = availableCandidates(candidates, state.settings).map((row) => ({
    value: segmentKey(row),
    label: `${segmentShortLabel(row)} · ${text(row.method_name)}`,
    meta: candidateMeta(row),
    title: text(row.reserving_class),
    row,
  }));
  openMenu(els.addSegmentBtn, options, "", (_value, option) => {
    const row = option.row;
    const segments = [...state.settings.segments, {
      reservingClass: text(row.reserving_class),
      methodName: text(row.method_name),
      factor: 1,
    }];
    const order = [...state.settings.segments.map((_, index) => index), -1];
    applySegmentOrder(segments, order, segments.length - 1);
  }, { emptyText: candidates.length ? "Every bootstrap in the project is already included." : "No bootstraps in the project's other reserving classes." });
}

async function openMethodMenu(button, rowIndex) {
  let candidates;
  try {
    candidates = await loadCandidates();
  } catch (err) {
    postStatus(`Could not list the project's bootstraps: ${String(err?.message || err)}`, "error");
    return;
  }
  const segment = state.settings.segments[rowIndex];
  if (!segment) return;
  const classKey = norm(segment.reservingClass);
  const taken = new Set(state.settings.segments.filter((_, i) => i !== rowIndex).map(segmentKey));
  const options = candidates
    .filter((row) => norm(row.reserving_class) === classKey && !taken.has(segmentKey(row)))
    .map((row) => ({ value: text(row.method_name), label: text(row.method_name), meta: candidateMeta(row) }));
  if (!options.some((option) => norm(option.value) === norm(segment.methodName))) {
    options.unshift({ value: segment.methodName, label: segment.methodName, meta: "not found" });
  }
  openMenu(button, options, segment.methodName, (value) => {
    if (norm(value) === norm(segment.methodName)) return;
    const segments = state.settings.segments.map((item, i) => (i === rowIndex ? { ...item, methodName: value } : item));
    updateSettings({ segments });
    renderSetupTabs();
  });
}

/* ---------------------------------------------------------------------------
   Correlation
--------------------------------------------------------------------------- */

function matrixLabels() {
  return state.settings.segments.map((segment) => segmentShortLabel(segment));
}

function matrixMarkup(title, matrix, { editable = false, labels = matrixLabels() } = {}) {
  const size = labels.length;
  const head = `<tr><th class="sconOriginHead"></th>${labels.map((label) => `<th>${escapeHtml(label)}</th>`).join("")}</tr>`;
  const body = labels.map((label, i) => `<tr><td class="sconOriginCell">${escapeHtml(label)}</td>${
    Array.from({ length: size }, (_, j) => {
      const value = numberOrNull(matrix?.[i]?.[j]);
      if (i === j) return `<td class="sconCell sconDiagonalCell" data-copy-value="1">${formatNumber(1, 4)}</td>`;
      if (editable && j > i) {
        const invalid = state.invalidCell && state.invalidCell[0] === i && state.invalidCell[1] === j;
        return `<td class="sconCell sconEntryCell"><input class="sconCellInput" type="text" inputmode="decimal"
          data-matrix-row="${i}" data-matrix-col="${j}" value="${value === null ? "" : escapeHtml(String(+value.toFixed(6)))}"
          ${invalid ? "aria-invalid=\"true\"" : ""} aria-label="${escapeHtml(`Target correlation of ${labels[i]} and ${labels[j]}`)}"></td>`;
      }
      return `<td class="sconCell${editable ? " sconMirrorCell" : ""}" data-copy-value="${copyValue(value)}">${formatNumber(value, 4)}</td>`;
    }).join("")}</tr>`).join("");
  return `<div class="sconMatrixBlock">
    ${title ? `<h3 class="sconMatrixTitle">${escapeHtml(title)}</h3>` : ""}
    <div class="ar-framed-scroll sconTableWrap sconMatrixWrap">
      <table class="arSpreadsheetTable sconTable sconMatrixTable" aria-label="${escapeHtml(title || "Correlation matrix")}">
        <thead>${head}</thead><tbody>${body}</tbody>
      </table>
    </div>
  </div>`;
}

const OPTION_CAPTIONS = Object.freeze({
  independent: "Independent: every pair of segments is uncorrelated.",
  fully_correlated: "Fully correlated: every pair moves together; a run repairs the all-ones matrix to 0.999999 so it can be factored.",
  as_generated: "As generated: each segment's simulations pair in the order they were generated, which leaves the segments uncorrelated.",
});

function renderCorrelation() {
  renderCorrelationView();
  els.matrices.querySelectorAll("table").forEach((table, index) => {
    tagMethodGridCells(table);
    cellSelection.addTable({ key: `matrix${index}`, table, scrollHost: table.closest(".sconTableWrap") });
  });
}

function renderCorrelationView() {
  const s = state.settings;
  els.correlationControl.innerHTML = segmentedMarkup(SCON_CORRELATION_OPTIONS, s.correlationOption);
  setDropdown(els.dependencyButton, SCON_DEPENDENCY_OPTIONS, s.dependencyType);
  els.degreesField.hidden = s.dependencyType !== "student_t";
  if (document.activeElement !== els.degreesInput) els.degreesInput.value = String(s.degreesOfFreedom);
  const run = hasRun();
  if (state.matrixView === "achieved" && !run) state.matrixView = "target";
  els.matrixViewControl.innerHTML = segmentedMarkup(
    SCON_MATRIX_VIEWS,
    state.matrixView,
    run ? null : ["target", "used"],
  );
  els.matrixError.textContent = state.matrixError;
  if (!s.segments.length) {
    els.matrices.innerHTML = `<div class="sconMatrixEmpty">Add segments on the Segments tab to set their correlations.</div>`;
    els.matrixCaption.textContent = "";
    return;
  }
  const settingsMatchRun = state.runSnapshot !== null && state.runSnapshot === runInputSnapshot(s);
  if (state.matrixView === "target") {
    const editable = s.correlationOption === "specified";
    els.matrices.innerHTML = matrixMarkup("Target Rank Correlations", optionTargetMatrix(s), { editable });
    els.matrixCaption.textContent = editable
      ? "Enter each pair above the diagonal as a rank correlation from -1 to 1; the cell below the diagonal mirrors it."
      : OPTION_CAPTIONS[s.correlationOption] || "";
  } else if (state.matrixView === "used") {
    if (run && settingsMatchRun) {
      const labels = state.method?.segments_tab?.segments?.map((segment) => segmentShortLabel(segment)) || matrixLabels();
      els.matrices.innerHTML = matrixMarkup("Correlations Used", storedAdjustedMatrix(state.method), { labels });
      els.matrixCaption.textContent = "The linear correlations the last run used: each target converted with 2·sin(π·ρ/6), repaired where the matrix was not positive definite.";
    } else {
      const used = usedCorrelationMatrix(s);
      els.matrices.innerHTML = matrixMarkup("Correlations Used", used.matrix);
      els.matrixCaption.textContent = [
        "Each target converted to the linear correlation a normal copula needs, 2·sin(π·ρ/6).",
        used.repairNeeded
          ? "This matrix is not positive definite; Consolidate repairs it by raising its smallest eigenvalues, so the values it uses will differ slightly."
          : "",
      ].filter(Boolean).join(" ");
    }
  } else {
    const achieved = achievedMatrices(state.method);
    const labels = state.method?.segments_tab?.segments?.map((segment) => segmentShortLabel(segment)) || matrixLabels();
    els.matrices.innerHTML = matrixMarkup("Achieved Rank Correlations", achieved.rank, { labels })
      + matrixMarkup("Achieved Linear Correlations", achieved.linear, { labels });
    els.matrixCaption.textContent = [
      "What the last run achieved: the rank correlation of the segments' pairings and the linear correlation of their reserves.",
      settingsMatchRun ? "" : "The settings changed since that run.",
    ].filter(Boolean).join(" ");
  }
}

function commitMatrixInput(input) {
  const row = Number(input.dataset.matrixRow);
  const column = Number(input.dataset.matrixCol);
  const parsed = parseCorrelationInput(input.value);
  if (!parsed.ok) {
    state.matrixError = parsed.error;
    state.invalidCell = [row, column];
    renderCorrelation();
    els.matrices.querySelector(`[data-matrix-row="${row}"][data-matrix-col="${column}"]`)?.focus();
    return;
  }
  state.matrixError = "";
  state.invalidCell = null;
  const current = numberOrNull(state.settings.targetCorrelations?.[row]?.[column]) ?? 0;
  if (parsed.value !== current) {
    updateSettings({ targetCorrelations: setTargetCorrelation(state.settings.targetCorrelations, row, column, parsed.value) });
  }
  renderCorrelation();
}

/* ---------------------------------------------------------------------------
   Results: one view feeds the table and both charts, and the chosen
   percentiles are shared by all three. A consolidation combines scaled
   reserves only, so there is no Scaled / Unscaled switch.
--------------------------------------------------------------------------- */

// A run is known by its seed, size and means, so a Save or a reload of the
// same run keeps the ladder that came with it.
function runKey(method) {
  const summary = method?.results_tab?.simulation_summary || {};
  return JSON.stringify([summary.random_seed, summary.simulation_count, summary.scaled?.mean]);
}

// The full ladder at a finer interval than the stored one reads the run's
// finest ladder; until the page has it, the table waits for it.
function finerLadderNeeded() {
  return state.results.fullLadder && !ladderIntervalIsStored(state.results.interval);
}

function finerLadderReady() {
  return state.finerLadder?.run === runKey(state.method);
}

function currentResultsView() {
  const finerLadder = finerLadderNeeded() && finerLadderReady() ? state.finerLadder.scaled : null;
  return resultsView(state.method, { basis: "scaled", measure: state.results.measure, finerLadder });
}

// Consolidate hands the finest ladder over with each run. A stored run gets it
// by consolidating its own inputs again, taken only when that reproduces the
// stored run, since a segment may have changed since.
async function loadFinerLadder() {
  const method = state.method;
  const run = runKey(method);
  if (finerLadderReady() || state.ladderRequest?.run === run) return;
  const request = { run };
  state.ladderRequest = request;
  try {
    const result = await consolidateStochasticConsolidation({
      project_name: state.project,
      reserving_class: state.reservingClass,
      method,
    });
    if (state.ladderRequest !== request) return;
    if (runKey(result?.method) !== run || !result?.finer_ladder) {
      throw new Error("the segments changed since this run; consolidate again to see a finer interval.");
    }
    state.finerLadder = { run, scaled: result.finer_ladder.scaled };
  } catch (err) {
    if (state.ladderRequest !== request) return;
    postStatus(`Could not work out the finer percentiles: ${String(err?.message || err)}`, "error");
    state.results.interval = RANGE_STORED_LADDER_INTERVAL;
  } finally {
    if (state.ladderRequest === request) state.ladderRequest = null;
  }
  renderResults();
}

function renderResultsTable(view) {
  if (finerLadderNeeded() && !finerLadderReady()) {
    resultsRows.hide();
    const { head, body } = ladderLoadingMarkup(view, { cssPrefix: "scon" });
    els.resultsHead.innerHTML = head;
    els.resultsTableBody.innerHTML = body;
    void loadFinerLadder();
    return;
  }
  const options = { cssPrefix: "scon", interval: state.results.interval };
  if (!state.results.fullLadder) {
    resultsRows.hide();
    const { head, body } = summaryTableMarkup(view, state.results.percentiles, options);
    els.resultsHead.innerHTML = head;
    els.resultsTableBody.innerHTML = body;
    refreshGrid(els.resultsTableBody);
    return;
  }
  ladderParts = ladderTableParts(view, state.results.percentiles, options);
  const { head, rows, rowMarkup } = ladderParts;
  els.resultsHead.innerHTML = head;
  if (rows.length <= VIRTUAL_LADDER_ROWS) {
    resultsRows.hide();
    els.resultsTableBody.innerHTML = rows.map((_, r) => rowMarkup(r)).join("");
    refreshGrid(els.resultsTableBody);
    return;
  }
  // The statistics at the top and the far end of the ladder hold the widest
  // figures, so the columns are sized with them drawn.
  const last = rows.length - 1;
  resultsRows.show({
    rowCount: rows.length,
    columnCount: rows[0].values.length + 1,
    rowMarkup,
    rowLabel: (r) => rows[r]?.label,
    widthRows: [0, 1, 2, 3, 4, last - 1, last],
  });
}

function renderBreakdown() {
  const breakdown = segmentBreakdown(state.method);
  if (!breakdown) {
    els.breakdownBody.innerHTML = `<tr><td class="sconEmptyRow" colspan="7">The stored run has no segment figures.</td></tr>`;
    refreshGrid(els.breakdownBody);
    els.breakdownCaption.textContent = "";
    return;
  }
  const rowMarkup = (row) => `<tr>
    <td class="sconCell sconTextCell" data-full-class="${escapeHtml(row.reservingClass)}">${escapeHtml(row.shortLabel)}</td>
    <td class="sconCell sconTextCell">${escapeHtml(row.methodName)}</td>
    <td class="sconCell" data-copy-value="${copyValue(row.factor)}">${formatNumber(row.factor, 2)}</td>
    <td class="sconCell" data-copy-value="${copyValue(row.mean)}">${formatNumber(row.mean)}</td>
    <td class="sconCell" data-copy-value="${copyValue(row.sd)}">${formatNumber(row.sd)}</td>
    <td class="sconCell" data-copy-value="${copyValue(row.cv)}">${formatPercent(row.cv)}</td>
    <td class="sconCell" data-copy-value="${copyValue(row.share)}">${formatPercent(row.share)}</td>
  </tr>`;
  els.breakdownBody.innerHTML = breakdown.rows.map(rowMarkup).join("") + `<tr class="sconTotalRow">
    <td class="sconCell sconTextCell">Total</td>
    <td class="sconCell sconTextCell"></td>
    <td class="sconCell"></td>
    <td class="sconCell" data-copy-value="${copyValue(breakdown.total.mean)}">${formatNumber(breakdown.total.mean)}</td>
    <td class="sconCell" data-copy-value="${copyValue(breakdown.total.sd)}">${formatNumber(breakdown.total.sd)}</td>
    <td class="sconCell" data-copy-value="${copyValue(breakdown.total.cv)}">${formatPercent(breakdown.total.cv)}</td>
    <td class="sconCell" data-copy-value="${copyValue(breakdown.total.share)}">${formatPercent(breakdown.total.share)}</td>
  </tr>`;
  refreshGrid(els.breakdownBody);
  for (const cell of els.breakdownBody.querySelectorAll("[data-full-class]")) {
    attachArcrhoTooltip(cell, cell.dataset.fullClass);
  }
  els.breakdownCaption.textContent = breakdown.standaloneSd !== null
    ? `Standalone scaled reserves. The total's standard deviation is ${formatNumber(breakdown.total.sd)} against ${
      formatNumber(breakdown.standaloneSd)} for the segments on their own: the correlations take off ${
      formatNumber(breakdown.benefit)}${breakdown.benefitRatio !== null ? ` (${formatPercent(breakdown.benefitRatio)})` : ""}.`
    : "Standalone scaled reserves.";
}

function renderResults() {
  const run = hasRun();
  els.resultsEmpty.hidden = run;
  els.resultsBody.hidden = !run;
  syncHeader();
  if (!run) {
    els.resultsEmptyText.textContent = state.settings.segments.length
      ? "Not run yet. Consolidate combines the segments' simulations with the chosen correlations."
      : "Add segments on the Segments tab, then consolidate.";
    return;
  }
  const view = currentResultsView();
  els.measureControl.innerHTML = segmentedMarkup(RANGE_MEASURE_OPTIONS, state.results.measure);
  if (document.activeElement !== els.percentileInput) {
    els.percentileInput.value = formatPercentileList(state.results.percentiles);
  }
  els.fullLadderInput.checked = state.results.fullLadder;
  setDropdown(els.intervalButton, RANGE_LADDER_INTERVAL_OPTIONS, state.results.interval, !state.results.fullLadder);
  if (!view) return;
  els.resultsBody.classList.toggle("isFullLadder", state.results.fullLadder);
  renderResultsTable(view);
  els.resultsCaption.textContent = `Consolidated scaled ${view.measure} over ${formatNumber(view.simulationCount)} simulations, seed ${view.randomSeed ?? ""}.`;
  const noun = view.measure === "ultimates" ? "Ultimate" : "Reserve";
  els.distributionTitle.textContent = `Distribution Of Total ${noun}`;
  els.fanTitle.textContent = `${noun}s By Origin`;
  distributionChart?.render(distributionChartData(view, state.results.percentiles));
  fanChart?.render(fanChartData(view, state.results.percentiles));
  renderBreakdown();
}

function commitPercentiles() {
  const parsed = parsePercentileList(els.percentileInput.value);
  if (!parsed.ok) {
    postStatus(parsed.error, "warn");
    els.percentileInput.value = formatPercentileList(state.results.percentiles);
    return;
  }
  state.results.percentiles = parsed.values;
  els.percentileInput.value = formatPercentileList(parsed.values);
  renderResults();
}

// A table action shows its done label with a check for a moment.
function flashDone(button) {
  const label = button.querySelector(".sconTableActionLabel");
  button.classList.add("isDone");
  label.textContent = button.dataset.doneLabel;
  clearTimeout(button.doneTimer);
  button.doneTimer = setTimeout(() => {
    button.classList.remove("isDone");
    label.textContent = button.dataset.label;
  }, 1400);
}

// The table as shown; null while a finer ladder is still being worked out.
function resultsTableOptions() {
  if (finerLadderNeeded() && !finerLadderReady()) {
    postStatus("The percentiles are still being worked out.", "warn");
    return null;
  }
  const { percentiles, fullLadder, interval } = state.results;
  return { percentiles, fullLadder, interval };
}

// Download CSV saves the Results table as it is shown, through the desktop
// host's save dialog.
async function downloadResultsCsv() {
  const options = resultsTableOptions();
  if (!options) return;
  const payload = resultsCsvText(currentResultsView(), options);
  const host = window.ADAHost || window.top?.ADAHost || null;
  if (!payload) return;
  if (typeof host?.saveTextFile !== "function") {
    postStatus("Downloading a CSV needs the desktop app.", "error");
    return;
  }
  const name = state.settings.name || SCON_METHOD_TYPE;
  const result = await host.saveTextFile({ data: payload, suggestedName: `${name} - Results.csv` });
  if (result?.canceled) return;
  if (result?.error || !result?.path) {
    postStatus(`Download failed: ${result?.error || "the file was not written"}`, "error");
    return;
  }
  postStatus(`Saved the results to ${result.path}.`);
  flashDone(els.downloadResultsBtn);
}

async function copyResults() {
  const options = resultsTableOptions();
  if (!options) return;
  const payload = resultsClipboardText(currentResultsView(), options);
  if (!payload) return;
  try {
    await navigator.clipboard.writeText(payload);
    postStatus(`Copied ${payload.split("\r\n").length - 1} rows of results.`);
    flashDone(els.copyResultsBtn);
  } catch (err) {
    postStatus(`Copy failed: ${String(err?.message || err)}`, "error");
  }
}

function renderSetupTabs() {
  renderDetails();
  renderSegments();
  renderCorrelation();
  syncHeader();
}

function renderAll() {
  renderSetupTabs();
  renderResults();
}

/* ---------------------------------------------------------------------------
   Load, consolidate and save
--------------------------------------------------------------------------- */

function applyOutputSidecar(sidecar) {
  const payload = sidecar && typeof sidecar === "object" ? sidecar : {};
  if (payload.exists === false) {
    state.needsReview = false;
    notesController.setValue("", { markClean: true });
    auditLogView.clear();
    return;
  }
  state.needsReview = statusNeedsReview(payload.status);
  notesController.setValue(String(payload.notes ?? ""), { markClean: true });
  auditLogView.render(payload.audit_log);
}

/* A load or a save: the stored method, its segments' freshness, and whether
   the stored run describes the stored settings. */
function applyLoaded(result) {
  const method = result?.method;
  if (!method || text(method.json_format) !== "arcrho-stochastic-consolidation-v4") {
    throw new Error("Stochastic Consolidation load did not return a current method.");
  }
  state.method = method;
  state.persisted = true;
  state.settings = readConsolidationSettings(method);
  state.ownedRevision = text(result?.owned_revision);
  state.derivedRevision = text(result?.derived_revision);
  state.segmentInfo = segmentInfoMap(state.candidates, result?.segments);
  const runState = text(result?.run_state);
  state.runSnapshot = runState === "up_to_date" || runState === "segment_changed"
    ? runInputSnapshot(state.settings)
    : null;
  state.segmentChanged = runState === "segment_changed";
  state.runUnsaved = false;
  applyOutputSidecar(result?.sidecar);
  renderAll();
  objectChangeWatch.ensure({
    projectName: state.project,
    reservingClass: state.reservingClass,
    methodName: state.settings.name,
    outputDataset: text(result?.output_dataset) || state.settings.name,
    selfWriteStamp: result?.sidecar?.updated_at,
  });
}

async function tryLoadExistingMethod() {
  if (!state.settings.name) return false;
  try {
    const result = await loadStochasticConsolidation({
      project_name: state.project,
      reserving_class: state.reservingClass,
      method_name: state.settings.name,
    });
    applyLoaded(result);
    return true;
  } catch (err) {
    if (Number(err?.status) === 404) return false;
    throw err;
  }
}

function requirementError(action) {
  const s = state.settings;
  if (!s.name || !s.outputType) return `Stochastic Consolidation ${action} requires Name and Output Type.`;
  if (!s.segments.length) return `Stochastic Consolidation ${action} requires at least one segment.`;
  const duplicate = currentSegmentRows().find((row) => row.issues.some((issue) => issue.kind === "duplicate"));
  if (duplicate) return `${duplicate.shortLabel} / ${duplicate.methodName} is included more than once.`;
  return "";
}

/* Runs the settings on screen on the server without writing; the result
   stays on screen, unsaved, until Save. */
async function consolidateFromUser() {
  if (state.running) return;
  const problem = requirementError("run");
  if (problem) {
    postStatus(problem, "error");
    return;
  }
  const settings = state.settings;
  const method = applyConsolidationSettings(state.method || {}, settings);
  const started = performance.now();
  state.running = true;
  syncHeader();
  postStatus(`Consolidating ${settings.segments.length} segments.`);
  const runCard = showSimulationRun({
    title: "Consolidating",
    detail: `${formatNumber(settings.segments.length)} segments`,
  });
  try {
    const result = await consolidateStochasticConsolidation({
      project_name: state.project,
      reserving_class: state.reservingClass,
      method,
    });
    state.lastRunMs = performance.now() - started;
    state.method = { ...(state.method || {}), ...result.method };
    // The run's finest ladder comes with it and serves every finer interval
    // until the next run.
    state.finerLadder = result.finer_ladder ? { run: runKey(state.method), scaled: result.finer_ladder.scaled } : null;
    state.segmentInfo = segmentInfoMap(state.candidates, Array.from(state.segmentInfo.values()), result?.segments);
    state.runSnapshot = runInputSnapshot(settings);
    state.segmentChanged = false;
    state.runUnsaved = true;
    postStatus(`Consolidated ${formatNumber(result?.method?.details_tab?.simulation_count)} simulations in ${formatRunDuration(state.lastRunMs)}. Save keeps the run.`);
  } catch (err) {
    console.error(err);
    postStatus(`Consolidate failed: ${String(err?.message || err)}`, "error");
  } finally {
    await runCard.finish();
    state.running = false;
    renderAll();
    markDirty();
  }
}

async function runSave(progress) {
  const problem = requirementError("save");
  if (problem) {
    postStatus(problem, "error");
    return { ok: false };
  }
  const s = state.settings;
  const method = applyConsolidationSettings(state.method || {}, s);
  const rerun = currentRunState().key !== "current";
  let result;
  objectChangeWatch.pause();
  try {
    const started = performance.now();
    state.running = rerun;
    syncHeader();
    try {
      if (rerun) progress.setMessage(`Consolidating ${s.segments.length} segments and saving the results.`);
      else progress.writing();
      result = await saveStochasticConsolidation({
        project_name: state.project,
        reserving_class: state.reservingClass,
        method,
        notes: notesController.elements.input?.value || "",
        expected_owned_revision: state.ownedRevision,
        expected_derived_revision: state.derivedRevision,
      });
    } catch (err) {
      progress.finish();
      if (isEngineUnavailableSaveError(err)) {
        void showPageMessageBox({ title: "Arco Engine Unavailable", message: String(err?.message || err), tone: "warn" });
      }
      throw err;
    } finally {
      state.running = false;
    }
    if (result?.consolidated) state.lastRunMs = performance.now() - started;
    applyLoaded(result);
    markClean();
    void detailsDependencies.refresh().catch(() => null);
    try {
      window.parent?.postMessage({ type: "arcrho:project-instance-refresh-datasets" }, "*");
    } catch {}
    postStatus(
      result?.propagation_ok === false
        ? `Stochastic Consolidation saved, but some dependent updates did not complete: ${text(result?.propagation?.message) || s.name}`
        : `Stochastic Consolidation ${result?.consolidated ? "consolidated and saved" : "saved"}: ${s.name}`,
      result?.propagation_ok === false ? "warn" : "",
    );
    const propagationOutcome = await trackSavePropagation(result?.propagation, {
      onStatus: (message, statusOptions) => {
        progress.setMessage?.(message, statusOptions);
        postStatus(message, statusOptions?.tone === "warn" ? "warn" : "");
      },
      onComplete: () => {
        try {
          window.parent?.postMessage({ type: "arcrho:project-instance-refresh-datasets" }, "*");
        } catch {}
      },
    });
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
    objectChangeWatch.resume();
  }
}

async function saveFromUser() {
  if (state.running) return;
  try {
    const saved = await saveProgress.run((progress) => runSave(progress));
    if (saved?.ok && saved?.propagationClean) {
      await showSavedDependentsNotice(saved.refreshedDatasets, { linkWarnings: saved.linkWarnings });
    }
  } catch (err) {
    console.error(err);
    postStatus(`Save failed: ${String(err?.message || err)}`, "error");
  } finally {
    syncHeader();
  }
}

/* ---------------------------------------------------------------------------
   Pickers
--------------------------------------------------------------------------- */

async function openOutputPicker(anchor) {
  await openDatasetNamePicker({
    projectName: state.project,
    initialName: state.settings.outputType,
    anchorElement: anchor,
    title: "Select Output Vector",
    allowedDataFormats: ["Vector"],
    includeCalculated: true,
    emptyMessage: "No cached vector datasets found.",
    itemFilter: () => true,
    setStatus: (message) => {
      if (text(message)) postStatus(message, "warn");
    },
    onError: (err) => postStatus(`Error loading dataset names: ${String(err?.message || err)}`, "error"),
    onSelect: (name, item) => {
      const selected = text(name);
      if (!selected) return;
      const patch = {
        outputType: selected,
        datasetCategory: text(item?.dataset_category || item?.category) || state.settings.datasetCategory,
      };
      if (!state.settings.name) patch.name = selected;
      updateSettings(patch);
      renderAll();
    },
  });
}

/* ---------------------------------------------------------------------------
   Wiring
--------------------------------------------------------------------------- */

function wireInputs() {
  els.nameInput.addEventListener("input", () => {
    state.settings = { ...state.settings, name: text(els.nameInput.value) };
    markDirty();
  });
  els.outputTypeBtn.addEventListener("click", () => void openOutputPicker(els.outputTypeBtn));
  els.baseTypeButton.addEventListener("click", () => {
    openMenu(els.baseTypeButton, baseTypeChoices(state.settings, state.segmentInfo), state.settings.baseTriangleType, (value) => {
      updateSettings({ baseTriangleType: value });
      renderSetupTabs();
    });
  });
  els.seedInput.addEventListener("change", () => {
    const n = Number.parseInt(text(els.seedInput.value).replaceAll(",", ""), 10);
    if (!Number.isFinite(n) || n < 0 || n > 4294967295) {
      postStatus("Enter a seed from 0 to 4,294,967,295.", "warn");
      els.seedInput.value = String(state.settings.randomSeed);
      return;
    }
    if (n !== state.settings.randomSeed) updateSettings({ randomSeed: n });
    els.seedInput.value = String(n);
  });
  els.seedInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") els.seedInput.blur();
  });
  els.newSeedBtn.addEventListener("click", () => {
    updateSettings({ randomSeed: newRandomSeed() });
    els.seedInput.value = String(state.settings.randomSeed);
  });

  els.addSegmentBtn.addEventListener("click", () => void openAddSegmentMenu());
  els.removeSegmentBtn.addEventListener("click", removeSelectedSegment);
  els.moveUpBtn.addEventListener("click", () => moveSelectedSegment(-1));
  els.moveDownBtn.addEventListener("click", () => moveSelectedSegment(1));
  els.segmentsBody.addEventListener("click", (event) => {
    const methodButton = event.target.closest("[data-method-row]");
    const row = event.target.closest("[data-segment-row]");
    if (row) {
      const index = Number(row.dataset.segmentRow);
      if (index !== state.selectedSegment) {
        state.selectedSegment = index;
        for (const item of els.segmentsBody.querySelectorAll("[data-segment-row]")) {
          const selected = Number(item.dataset.segmentRow) === index;
          item.classList.toggle("isSelected", selected);
          if (selected) item.setAttribute("aria-selected", "true");
          else item.removeAttribute("aria-selected");
        }
        const count = state.settings.segments.length;
        els.removeSegmentBtn.disabled = false;
        els.moveUpBtn.disabled = index <= 0;
        els.moveDownBtn.disabled = index >= count - 1;
      }
    }
    if (methodButton) void openMethodMenu(methodButton, Number(methodButton.dataset.methodRow));
  });
  els.segmentsBody.addEventListener("change", (event) => {
    const input = event.target.closest("[data-factor-row]");
    if (!input) return;
    const index = Number(input.dataset.factorRow);
    const value = Number(text(input.value).replaceAll(",", ""));
    if (!text(input.value) || !Number.isFinite(value)) {
      postStatus("A factor must be a number.", "warn");
      input.value = String(state.settings.segments[index]?.factor ?? 1);
      return;
    }
    const segments = state.settings.segments.map((segment, i) => (i === index ? { ...segment, factor: value } : segment));
    updateSettings({ segments });
  });
  els.segmentsBody.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.closest("[data-factor-row]")) event.target.blur();
  });

  els.correlationControl.addEventListener("click", (event) => {
    const button = event.target.closest(".sconSegment");
    if (!button || button.dataset.value === state.settings.correlationOption) return;
    state.matrixError = "";
    state.invalidCell = null;
    updateSettings({ correlationOption: button.dataset.value });
    renderCorrelation();
  });
  els.dependencyButton.addEventListener("click", () => {
    openMenu(els.dependencyButton, SCON_DEPENDENCY_OPTIONS, state.settings.dependencyType, (value) => {
      updateSettings({ dependencyType: value });
      renderCorrelation();
    });
  });
  els.degreesInput.addEventListener("change", () => {
    const value = Number(text(els.degreesInput.value));
    if (!Number.isFinite(value) || value <= 0) {
      postStatus("Degrees of freedom must be more than zero.", "warn");
      els.degreesInput.value = String(state.settings.degreesOfFreedom);
      return;
    }
    if (value !== state.settings.degreesOfFreedom) updateSettings({ degreesOfFreedom: value });
  });
  els.degreesInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") els.degreesInput.blur();
  });
  els.matrixViewControl.addEventListener("click", (event) => {
    const button = event.target.closest(".sconSegment");
    if (!button || button.disabled || button.dataset.value === state.matrixView) return;
    state.matrixView = button.dataset.value;
    renderCorrelation();
  });
  els.matrices.addEventListener("change", (event) => {
    const input = event.target.closest("[data-matrix-row]");
    if (input) commitMatrixInput(input);
  });
  els.matrices.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.closest("[data-matrix-row]")) event.target.blur();
  });

  els.measureControl.addEventListener("click", (event) => {
    const button = event.target.closest(".sconSegment");
    if (!button || button.dataset.value === state.results.measure) return;
    state.results.measure = button.dataset.value;
    renderResults();
  });
  els.percentileInput.addEventListener("change", commitPercentiles);
  els.percentileInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") els.percentileInput.blur();
    if (event.key === "Escape") {
      els.percentileInput.value = formatPercentileList(state.results.percentiles);
      els.percentileInput.blur();
    }
  });
  els.percentileResetBtn.addEventListener("click", () => {
    state.results.percentiles = RANGE_DEFAULT_PERCENTILES.slice();
    renderResults();
  });
  els.fullLadderInput.addEventListener("change", () => {
    state.results.fullLadder = els.fullLadderInput.checked;
    renderResults();
  });
  els.intervalButton.addEventListener("click", () => {
    openMenu(els.intervalButton, RANGE_LADDER_INTERVAL_OPTIONS, state.results.interval, (value) => {
      state.results.interval = value;
      renderResults();
    });
  });
  els.copyResultsBtn.addEventListener("click", () => void copyResults());
  els.downloadResultsBtn.addEventListener("click", () => void downloadResultsCsv());
  // The two show only their icons, so the tooltip names them.
  for (const button of [els.copyResultsBtn, els.downloadResultsBtn]) {
    attachArcrhoTooltip(button, button.dataset.label);
  }
  for (const button of [els.consolidateBtn, els.emptyConsolidateBtn, els.staleConsolidateBtn]) {
    button.addEventListener("click", () => void consolidateFromUser());
  }

  els.saveBtn.addEventListener("click", () => void saveFromUser());
  els.cancelBtn.addEventListener("click", () => void closeOrConfirm());
  window.__arcrho_request_close = () => {
    if (!isDirty) return false;
    if (closeConfirm.isOpen) return true;
    void closeOrConfirm();
    return true;
  };
  window.__arcrho_consume_close_shortcut = window.__arcrho_request_close;
}

async function closeOrConfirm() {
  if (isDirty) {
    const discard = await closeConfirm.confirm({ reason: "close" });
    if (!discard) return;
  }
  requestTabbedPageWindowClose({ messageType: "arcrho:dataset-close-confirmed", inst });
}

function wireMessages() {
  window.addEventListener("message", async (event) => {
    const msg = event?.data && typeof event.data === "object" ? event.data : {};
    if (msg.type === "arcrho:dataset-save") {
      await saveFromUser();
    } else if (msg.type === "arcrho:close-active-tab" || msg.type === "arcrho:dataset-close-request") {
      await closeOrConfirm();
    }
  });
}

function initTabbedPage() {
  const requested = text(params.get("tab") || params.get("initial_tab"));
  tabbedPage = createTabbedPage(document.getElementById("sconTabbedPage"), {
    tabs: STOCHASTIC_CONSOLIDATION_TAB_DEFS,
    cssPrefix: "scon",
    initialTab: ALLOWED_TABS.has(requested) ? requested : "details",
    onTabChange: (tabId) => {
      closeMenu();
      if (tabId === "results") {
        requestAnimationFrame(() => {
          distributionChart?.refresh();
          fanChart?.refresh();
        });
      }
      try {
        window.parent?.postMessage({ type: "arcrho:scon-tab-changed", inst, tab: tabId }, "*");
      } catch {}
    },
  });
  wireTabPopoutWindows({
    cssPrefix: "scon",
    tabs: STOCHASTIC_CONSOLIDATION_TAB_DEFS,
    tabSystem: () => tabbedPage,
    getTitle: () => `${state.settings.name || SCON_METHOD_TYPE} - ${SCON_METHOD_TYPE}`,
  });
}

async function init() {
  applyHostFixedDetailsFields({ root: "#sconDetailsPage" });
  syncDetailsLabelWidth({ root: "#sconDetailsPage", labelSelector: ".arDetailsLabel" });
  els.projectInput.value = state.project;
  els.classInput.value = state.reservingClass;
  state.settings = {
    ...state.settings,
    name: text(params.get("name") || params.get("dataset")),
    outputType: text(params.get("output_type") || params.get("dataset_type")),
    datasetCategory: text(params.get("category")),
    randomSeed: newRandomSeed(),
  };
  distributionChart = createDistributionChart({
    canvas: els.distributionChart,
    tooltip: els.distributionTooltip,
    emptyState: els.distributionEmpty,
  });
  fanChart = createFanChart({
    canvas: els.fanChart,
    legend: els.fanLegend,
    tooltip: els.fanTooltip,
    emptyState: els.fanEmpty,
    cssPrefix: "scon",
  });
  initTabbedPage();
  applyTabbedPageSaveBar(document.getElementById("sconSaveBar"));
  wireFramedScrollActivity(document);
  wireMenu();
  wireInputs();
  wireMessages();
  let loaded = false;
  try {
    loaded = await tryLoadExistingMethod();
  } catch (err) {
    postStatus(`Could not load existing Stochastic Consolidation: ${String(err?.message || err)}`, "error");
  }
  if (!loaded) renderAll();
  void detailsDependencies.refresh().catch(() => null);
  markClean();
  postStatus(loaded
    ? "Stochastic Consolidation ready."
    : "New Stochastic Consolidation: add segments, set their correlations, then consolidate.");
}

// The window is held blank until the opening tab is rendered; see
// ui/shared/tabbed_page/initial_tab_paint.js.
void init().finally(() => window.arcrhoRevealPage?.());
