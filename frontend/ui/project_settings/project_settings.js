/**
 * Project Settings - Workspace coordinator
 *
 * Owns the page shell: DOM lookups, feature composition, project selection,
 * the Source Data table-summary load, dialogs, context menus, and the ribbon.
 * Domain logic lives in the sibling feature modules:
 *   - project map document + folder structure -> project_settings_project_map.js
 *   - Project Explorer tree                   -> project_settings_tree_view.js
 *   - project/folder create-rename-delete     -> project_settings_project_ops.js
 *   - origin/development boundary months      -> project_settings_general_settings.js
 *   - shared table column sizing              -> project_settings_table_columns.js
 */
import { AuditLogStore } from "/ui/project_settings/project_settings_audit.js?v=20260901dup1";
import { createFieldMappingFeature } from "/ui/project_settings/project_settings_field_mapping.js?v=20260927smb18";
import { createDatasetTypesFeature } from "/ui/project_settings/project_settings_dataset_types.js?v=20260927smb18";
import { createReservingClassTypesFeature } from "/ui/project_settings/project_settings_reserving_class_types.js?v=20260901dup1";
import { createDataProcessingRulesFeature } from "/ui/project_settings/project_settings_data_processing_rules.js?v=20260927smb18";
import { createSourceDataFeature } from "/ui/project_settings/project_settings_source_data.js?v=20261012combined3";
import { createSourceImport } from "/ui/project_settings/project_settings_source_import.js?v=20261012combined3";
import {
  applyProjectSettingsTablePreferences,
  getConfiguredTableColumnWidthMap,
  initTableColumnResizing,
  normalizeTableColumnPreferenceKey,
  resizeCellTextarea,
  wireProjectSettingsTableScrollbarActivity,
} from "/ui/project_settings/project_settings_table_columns.js?v=20261012combined3";
import {
  createGeneralSettingsFeature,
  formatBoundaryYmDisplay,
  normalizeBoundaryYmCanonical,
} from "/ui/project_settings/project_settings_general_settings.js?v=20261012combined3";
import { createProjectMapStore } from "/ui/project_settings/project_settings_project_map.js?v=20261012combined3";
import { createTreeViewFeature } from "/ui/project_settings/project_settings_tree_view.js?v=20261012combined3";
import { createProjectOpsFeature } from "/ui/project_settings/project_settings_project_ops.js?v=20261012combined3";
import { createAutoSaveScheduler } from "/ui/project_settings/project_settings_auto_save.js?v=20260901dup1";
import { createProjectLockFeature } from "/ui/project_settings/project_settings_project_lock.js?v=20261004lock1";
import { createSwitchCover } from "/ui/project_settings/project_settings_switch_cover.js?v=20261009switch1";
import { createSourceRefreshFeature } from "/ui/project_settings/project_settings_source_refresh.js?v=20260927smb18";
import { loadProjectUserPreferences } from "/ui/shared/services/project_user_preferences.js?v=20260816a";
import "/ui/shared/integrations/zoom_bridge.js?v=20260521a";

const DEFAULT_SOURCE = "project_map";

window.ArcRhoZoomBridge?.wirePageZoomBridge();

// ============ DOM Elements ============
const treeContent = document.getElementById("treeContent");
const detailEmpty = document.getElementById("detailEmpty");
const detailView = document.getElementById("detailView");
const detailTitle = document.getElementById("detailTitle");
const detailForm = document.getElementById("detailForm");
const switchCover = createSwitchCover(document.getElementById("detailSwitchCover"));
const openProjectFolderBtn = document.getElementById("openProjectFolderBtn");
const treePanel = document.getElementById("treePanel");
const resizeHandle = document.getElementById("resizeHandle");
const treeHeader = document.querySelector(".tree-header");
const contextMenu = document.getElementById("contextMenu");
const folderContextMenu = document.getElementById("folderContextMenu");
const treeContextMenu = document.getElementById("treeContextMenu");
const summaryTablePathInput = document.getElementById("summaryTablePathInput");
const summaryTablePathReloadBtn = document.getElementById("summaryTablePathReloadBtn");
const summaryOriginStartInput = document.getElementById("summaryOriginStartInput");
const summaryOriginEndInput = document.getElementById("summaryOriginEndInput");
const summaryDevelopmentEndInput = document.getElementById("summaryDevelopmentEndInput");
const dialogOverlay = document.getElementById("dialogOverlay");
const dialogTitle = document.getElementById("dialogTitle");
const dialogInput = document.getElementById("dialogInput");
const dialogOk = document.getElementById("dialogOk");
const dialogCancel = document.getElementById("dialogCancel");
const projectOperationProgress = document.getElementById("projectOperationProgress");
const projectOperationProgressTitle = document.getElementById("projectOperationProgressTitle");
const confirmOverlay = document.getElementById("confirmOverlay");
const confirmTitle = document.getElementById("confirmTitle");
const confirmMessage = document.getElementById("confirmMessage");
const confirmOk = document.getElementById("confirmOk");
const confirmCancel = document.getElementById("confirmCancel");
const confirmBox = document.getElementById("confirmBox");
const fieldMappingBody = document.getElementById("fieldMappingBody");
const fieldMappingStatus = document.getElementById("fieldMappingStatus");
const saveFieldMappingBtn = document.getElementById("saveFieldMappingBtn");
const datasetTypesBody = document.getElementById("datasetTypesBody");
const datasetTypesStatus = document.getElementById("datasetTypesStatus");
const datasetTypesRowContextMenu = document.getElementById("datasetTypesRowContextMenu");
const datasetTypesErrorOverlay = document.getElementById("datasetTypesErrorOverlay");
const datasetTypesErrorBody = document.getElementById("datasetTypesErrorBody");
const datasetTypesErrorClose = document.getElementById("datasetTypesErrorClose");
const reservingClassTypesBody = document.getElementById("reservingClassTypesBody");
const reservingClassTypesStatus = document.getElementById("reservingClassTypesStatus");
const reservingClassTypesRowContextMenu = document.getElementById("reservingClassTypesRowContextMenu");
const dataProcessingRulesBody = document.getElementById("dataProcessingRulesBody");
const dataProcessingRulesStatus = document.getElementById("dataProcessingRulesStatus");
const dataProcessingRulesRowContextMenu = document.getElementById("dataProcessingRulesRowContextMenu");
const addDataProcessingRuleBtn = document.getElementById("addDataProcessingRuleBtn");
const validateDataProcessingRulesBtn = document.getElementById("validateDataProcessingRulesBtn");
const dataProcessingRulesJsonBtn = document.getElementById("dataProcessingRulesJsonBtn");
const dataProcessingRuleEditor = document.getElementById("dataProcessingRuleEditor");
const dataProcessingRuleEditorTitle = document.getElementById("dataProcessingRuleEditorTitle");
const dataProcessingRuleEditorClose = document.getElementById("dataProcessingRuleEditorClose");
const dprEditName = document.getElementById("dprEditName");
const dprEditEnabled = document.getElementById("dprEditEnabled");
const dprAutoNamePill = document.getElementById("dprAutoNamePill");
const dprEditEnabledLabel = document.getElementById("dprEditEnabledLabel");
const dprEditSourceMeasure = document.getElementById("dprEditSourceMeasure");
const dprRequestConditions = document.getElementById("dprRequestConditions");
const dprAddRequestConditionBtn = document.getElementById("dprAddRequestConditionBtn");
const dprThenConditions = document.getElementById("dprThenConditions");
const dprAddThenConditionBtn = document.getElementById("dprAddThenConditionBtn");
const dprActionVerbGroup = document.getElementById("dprActionVerbGroup");
const dprKeepHint = document.getElementById("dprKeepHint");
const dprVocabWarning = document.getElementById("dprVocabWarning");
const dprEditSummary = document.getElementById("dprEditSummary");
const dprEditError = document.getElementById("dprEditError");
const dprEditorCancelBtn = document.getElementById("dprEditorCancelBtn");
const dprEditorSaveBtn = document.getElementById("dprEditorSaveBtn");
const dataProcessingRulesJsonOverlay = document.getElementById("dataProcessingRulesJsonOverlay");
const dataProcessingRulesJsonBody = document.getElementById("dataProcessingRulesJsonBody");
const dataProcessingRulesJsonClose = document.getElementById("dataProcessingRulesJsonClose");
const auditLogBody = document.getElementById("auditLogBody");
const auditLogStatus = document.getElementById("auditLogStatus");
const reservingClassTypeEditor = document.getElementById("reservingClassTypeEditor");
const reservingClassTypeEditorHeader = document.getElementById("reservingClassTypeEditorHeader");
const reservingClassTypeEditorResizer = document.getElementById("reservingClassTypeEditorResizer");
const reservingClassTypeEditorTitle = document.getElementById("reservingClassTypeEditorTitle");
const reservingClassTypeEditorClose = document.getElementById("reservingClassTypeEditorClose");
const rctEditName = document.getElementById("rctEditName");
const rctEditLevel = document.getElementById("rctEditLevel");
const rctEditFormula = document.getElementById("rctEditFormula");
const rctFormulaReview = document.getElementById("rctFormulaReview");
const rctEditorCancelBtn = document.getElementById("rctEditorCancelBtn");
const rctEditorSaveBtn = document.getElementById("rctEditorSaveBtn");
const datasetTypeEditor = document.getElementById("datasetTypeEditor");
const datasetTypeEditorHeader = document.getElementById("datasetTypeEditorHeader");
const datasetTypeEditorTitle = document.getElementById("datasetTypeEditorTitle");
const datasetTypeEditorClose = document.getElementById("datasetTypeEditorClose");
const dtEditName = document.getElementById("dtEditName");
const dtEditDataFormat = document.getElementById("dtEditDataFormat");
const dtFormatSelect = document.getElementById("dtFormatSelect");
const dtFormatTrigger = document.getElementById("dtFormatTrigger");
const dtFormatValue = document.getElementById("dtFormatValue");
const dtFormatList = document.getElementById("dtFormatList");
const dtCategoryCombo = document.getElementById("dtCategoryCombo");
const dtEditCategory = document.getElementById("dtEditCategory");
const dtCategoryToggle = document.getElementById("dtCategoryToggle");
const dtCategoryList = document.getElementById("dtCategoryList");
const dtCategoryNewTip = document.getElementById("dtCategoryNewTip");
const dtCategoryNewTipText = document.getElementById("dtCategoryNewTipText");
const dtEditCalculated = document.getElementById("dtEditCalculated");
const dtEditFormula = document.getElementById("dtEditFormula");
const dtEditorCancelBtn = document.getElementById("dtEditorCancelBtn");
const dtEditorSaveBtn = document.getElementById("dtEditorSaveBtn");

// ============ State ============
let selectedProject = null;    // Currently selected project
let contextMenuProject = null; // Project for context menu actions
let contextMenuFolder = null;  // Folder node for context menu (create subfolder)
let activeProjectSettingsRibbon = "summary";
let tableSummaryLoadSeq = 0;
let currentFieldNames = [];

// ============ Shared helpers ============
function setStatus(msg) {
  // Send status to app's statusbar
  window.parent.postMessage({ type: "arcrho:status", text: msg || "" }, "*");
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeProjectKey(name) {
  return String(name || "").trim().toLowerCase();
}

/** Best available failure message for a non-OK app-server response. */
async function readResponseErrorDetail(res) {
  let detail = "";
  try {
    const body = await res.json();
    detail = String(body?.detail || "").trim();
  } catch {
    const text = await res.text();
    detail = String(text || "").trim();
  }
  return detail || `HTTP ${res.status}`;
}

function showProjectOperationProgress(title) {
  if (!projectOperationProgress || !projectOperationProgressTitle) return;
  projectOperationProgressTitle.textContent = String(title || "Working...").trim() || "Working...";
  projectOperationProgress.hidden = false;
}

function hideProjectOperationProgress() {
  if (!projectOperationProgress) return;
  projectOperationProgress.hidden = true;
}

function notifyProjectSettingsRibbonChanged() {
  window.parent.postMessage(
    {
      type: "arcrho:project-settings-ribbon-changed",
      ribbon: String(activeProjectSettingsRibbon || "").trim().toLowerCase(),
    },
    "*",
  );
}

// ============ Shell integration ============
window.addEventListener("message", (e) => {
  if (e.origin !== window.location.origin || e.source !== window.parent) return;
  const msgType = String(e?.data?.type || "");
  if (msgType === "arcrho:project-settings-reserving-class-types-save-local") {
    handleShellReservingClassTypesLocalSave();
    return;
  }
  if (msgType === "arcrho:project-settings-reserving-class-types-load-local") {
    handleShellReservingClassTypesLocalLoad();
    return;
  }
  if (msgType === "arcrho:project-settings-dataset-types-save-local") {
    handleShellDatasetTypesLocalSave();
    return;
  }
  if (msgType === "arcrho:project-settings-dataset-types-load-local") {
    handleShellDatasetTypesLocalLoad();
    return;
  }
  if (msgType === "arcrho:project-settings-progress-cancel") {
    projectOpsFeature.cancelDuplicateProject(String(e?.data?.progressId || ""));
    return;
  }
  if (msgType === "arcrho:server-connection-updated") {
    void reloadProjectSettingsForWorkspace(e?.data?.config);
  }
});

window.addEventListener("mousedown", () => {
  window.parent.postMessage({ type: "arcrho:close-shell-menus" }, "*");
}, { capture: true });

window.addEventListener("keydown", (e) => {
  const key = (e.key || "").toLowerCase();
  if (e.altKey && key === "w") {
    e.preventDefault();
    window.parent.postMessage({ type: "arcrho:close-active-tab" }, "*");
    return;
  }
  if (e.ctrlKey && key === "q") {
    e.preventDefault();
    window.parent.postMessage({ type: "arcrho:hotkey", action: "app_shutdown" }, "*");
    return;
  }
}, { capture: true });

/** Guard a shell-triggered local file action on the matching ribbon and selection. */
function requireActiveRibbonProject(ribbonKey, tabLabel, setFeatureStatus) {
  if (String(activeProjectSettingsRibbon || "").trim().toLowerCase() !== ribbonKey) {
    setStatus(`${tabLabel} tab is not active.`);
    return "";
  }
  const projectName = String(selectedProject?.name || "").trim();
  if (!projectName) {
    setFeatureStatus("Select a project first.", true);
    setStatus("Select a project first.");
    return "";
  }
  return projectName;
}

async function handleShellDatasetTypesLocalSave() {
  const projectName = requireActiveRibbonProject("dataset-types", "Dataset Types", (...args) => datasetTypesFeature?.setDatasetTypesStatus(...args));
  if (!projectName) return;
  await datasetTypesFeature?.saveDatasetTypesToLocalFile(projectName);
}

async function handleShellDatasetTypesLocalLoad() {
  const projectName = requireActiveRibbonProject("dataset-types", "Dataset Types", (...args) => datasetTypesFeature?.setDatasetTypesStatus(...args));
  if (!projectName) return;
  await datasetTypesFeature?.loadDatasetTypesFromLocalFile(projectName);
}

async function handleShellReservingClassTypesLocalSave() {
  const projectName = requireActiveRibbonProject("reserving-class-types", "Reserving Class Types", (...args) => reservingClassTypesFeature?.setReservingClassTypesStatus(...args));
  if (!projectName) return;
  await reservingClassTypesFeature?.saveReservingClassTypesToLocalFile(projectName);
}

async function handleShellReservingClassTypesLocalLoad() {
  const projectName = requireActiveRibbonProject("reserving-class-types", "Reserving Class Types", (...args) => reservingClassTypesFeature?.setReservingClassTypesStatus(...args));
  if (!projectName) return;
  await reservingClassTypesFeature?.loadReservingClassTypesFromLocalFile(projectName);
}

// ============ Audit log ============
const auditLogStore = new AuditLogStore({
  auditLogBody,
  auditLogStatus,
  initTableColumnResizing,
  fetchImpl: fetch.bind(window),
});

async function loadAuditLog(projectName, force = false) {
  return auditLogStore.load(projectName, force);
}

async function appendAuditLogAction(projectName, action) {
  return auditLogStore.append(projectName, action);
}

const scheduleDatasetTypesAutoSave = createAutoSaveScheduler(
  (projectName) => datasetTypesFeature?.saveDatasetTypes(projectName),
  {
    normalizeProjectKey,
    onStalled: (projectName) => {
      datasetTypesFeature?.setDatasetTypesStatus(
        "The dataset types save has not answered. Your changes are still unsaved - edit any row to try again.",
        true,
      );
      setStatus(`Dataset types save did not answer: ${projectName}`);
    },
  },
);
const scheduleReservingClassTypesAutoSave = createAutoSaveScheduler(
  (projectName) => reservingClassTypesFeature?.saveReservingClassTypes(projectName),
  {
    normalizeProjectKey,
    onStalled: (projectName) => {
      reservingClassTypesFeature?.setReservingClassTypesStatus(
        "The reserving class types save has not answered. Your changes are still unsaved - edit any row to try again.",
        true,
      );
      setStatus(`Reserving class types save did not answer: ${projectName}`);
    },
  },
);

async function syncDatasetTypeSourcesAfterFieldMappingSave(projectName) {
  const name = String(projectName || "").trim();
  if (!name) {
    return { ok: false, message: "Project name is missing." };
  }
  if (!datasetTypesFeature) {
    return { ok: false, message: "Dataset Types feature is unavailable." };
  }

  const loadedOk = await datasetTypesFeature.ensureDatasetTypesLoaded(name);
  if (!loadedOk) {
    return { ok: false, message: "Unable to load Dataset Types for source sync." };
  }

  const savedOk = await datasetTypesFeature.saveDatasetTypes(name);
  if (!savedOk) {
    return { ok: false, message: "Unable to save Dataset Types after Field Mapping update." };
  }
  return { ok: true };
}

// ============ Feature composition ============
let fieldMappingFeature = null;
let datasetTypesFeature = null;
let reservingClassTypesFeature = null;
let dataProcessingRulesFeature = null;

const projectMapStore = createProjectMapStore({
  defaultSource: DEFAULT_SOURCE,
  fetchImpl: fetch.bind(window),
  setStatus,
  reloadProjectData: (...args) => loadProjectData(...args),
});

const sourceDataFeature = createSourceDataFeature({
  escapeHtml,
  setStatus,
  normalizeMonth: normalizeBoundaryYmCanonical,
  formatMonth: formatBoundaryYmDisplay,
  // Project Settings runs in the shell's iframe, so the bridge lives on the
  // host window; `window.ADAHost` alone is undefined here.
  getHostApi: () => window.ADAHost || window.parent?.ADAHost || window.top?.ADAHost,
  onProfileSave: (...args) => sourceImport.saveImportSettings(...args),
  onListTables: (...args) => listSourceTables(...args),
  onListConnections: () => listSourceConnections(),
  onForgetConnection: (...args) => forgetSourceConnection(...args),
  onCsvPathPick: (...args) => pickTablePathFromHost(...args),
  onImportData: (...args) => sourceImport.importSourceData(...args),
  onLoadImportScope: () => loadImportScopeOptions(),
  onSourceFileStatus: () => loadSourceFileStatus(),
  fetchImpl: fetch.bind(window),
  getSelectedProject: () => selectedProject,
  // Admin-editable defaults stay owned by the shared table preference JSON.
  getConfiguredColumnWidths: () => {
    const configured = getConfiguredTableColumnWidthMap("summaryColumnsTable");
    if (!configured) return null;
    return {
      name: configured.get(normalizeTableColumnPreferenceKey("Column Name")),
      type: configured.get(normalizeTableColumnPreferenceKey("Data Type")),
    };
  },
});

const generalSettingsFeature = createGeneralSettingsFeature({
  setStatus,
  normalizeProjectKey,
  readResponseErrorDetail,
  getSelectedProject: () => selectedProject,
  onInputsChanged: () => sourceDataFeature.refreshOriginSpanNote(),
  fetchImpl: fetch.bind(window),
  controls: {
    originStartDate: { input: summaryOriginStartInput },
    originEndDate: { input: summaryOriginEndInput },
    developmentEndDate: { input: summaryDevelopmentEndInput },
  },
});

const projectLockFeature = createProjectLockFeature({
  getSelectedProject: () => selectedProject,
  fetchImpl: fetch.bind(window),
});

const treeViewFeature = createTreeViewFeature({
  treeContent,
  fetchImpl: fetch.bind(window),
  getTreeData: () => projectMapStore.getTreeData(),
  getSelectedProject: () => selectedProject,
  selectProject: (...args) => selectProject(...args),
  openProjectInstanceTab: (...args) => openProjectInstanceTab(...args),
  moveProjectToFolder: (...args) => projectOpsFeature.moveProjectToFolder(...args),
  moveFolderToFolder: (...args) => projectOpsFeature.moveFolderToFolder(...args),
  showProjectContextMenu,
  showFolderContextMenu,
});

const projectOpsFeature = createProjectOpsFeature({
  defaultSource: DEFAULT_SOURCE,
  fetchImpl: fetch.bind(window),
  store: projectMapStore,
  treeView: treeViewFeature,
  setStatus,
  showDialog,
  showConfirm,
  publishShellProgress: (message) => window.parent.postMessage(message, window.location.origin),
  appendAuditLogAction,
  getSelectedProject: () => selectedProject,
  setSelectedProject: (project) => { selectedProject = project; },
  selectProject: (...args) => selectProject(...args),
  showProjectDetails: (...args) => showProjectDetails(...args),
  clearProjectSelection,
  reloadProjectData: (...args) => loadProjectData(...args),
});

const sourceRefreshFeature = createSourceRefreshFeature({
  fetchImpl: fetch.bind(window),
  setStatus,
  publishShellProgress: (message) => window.parent.postMessage(message, window.location.origin),
  readResponseErrorDetail,
});

/** Re-attach to a refresh this page left running, then show what it produced. */
async function resumePendingSourceRefresh(projectName) {
  const outcome = await sourceRefreshFeature.resumePending(projectName);
  if (!outcome) return false;
  await reloadSourceDataViews(projectName, { forceRefresh: false });
  return !!outcome.ok;
}

window.__arcrho_request_close = () => projectOpsFeature.requestClose();

async function resolveWorkspaceConfig(config = null) {
  const suppliedRoot = String(config?.workspace_root || "").trim();
  if (suppliedRoot) return config;
  try {
    const response = await fetch("/workspace_paths", { cache: "no-store" });
    if (!response.ok) return {};
    const payload = await response.json();
    return payload?.config && typeof payload.config === "object" ? payload.config : {};
  } catch {
    return {};
  }
}

async function reloadProjectSettingsForWorkspace(config = null) {
  const workspaceConfig = await resolveWorkspaceConfig(config);
  const workspaceRoot = String(workspaceConfig?.workspace_root || "").trim();
  projectOpsFeature.setWorkspaceRoot(workspaceConfig);
  sourceRefreshFeature.setWorkspaceRoot(workspaceConfig);
  await loadProjectData(DEFAULT_SOURCE);
  if (workspaceRoot) await projectOpsFeature.resumePendingDuplicateProject();
}

datasetTypesFeature = createDatasetTypesFeature({
  datasetTypesBody,
  datasetTypesStatus,
  datasetTypesRowContextMenu,
  datasetTypesErrorOverlay,
  datasetTypesErrorBody,
  datasetTypesErrorClose,
  initTableColumnResizing,
  resizeCellTextarea,
  normalizeProjectKey,
  fetchImpl: fetch.bind(window),
  setStatus,
  loadAuditLog,
  getSelectedProject: () => selectedProject,
  getCurrentFieldNames: () => currentFieldNames,
  ensureFieldMappingLoaded: (...args) => fieldMappingFeature?.ensureFieldMappingLoaded(...args),
  findDatasetTypeOwnerInFieldMapping: (...args) => fieldMappingFeature?.findDatasetTypeOwner(...args) || "",
  getMappedDatasetTypeNamesInFieldMapping: (...args) => fieldMappingFeature?.getMappedDatasetTypeNames(...args) || [],
  renderFieldMappingTable: (...args) => fieldMappingFeature?.renderFieldMappingTable(...args),
  hideContextMenu,
  hideFolderContextMenu,
  hideTreeContextMenu,
  hideReservingClassTypesRowContextMenu: (...args) => reservingClassTypesFeature?.hideReservingClassTypesRowContextMenu(...args),
  positionContextMenu,
  datasetTypeEditor,
  datasetTypeEditorHeader,
  datasetTypeEditorTitle,
  dtEditName,
  dtEditDataFormat,
  dtFormatSelect,
  dtFormatTrigger,
  dtFormatValue,
  dtFormatList,
  dtCategoryCombo,
  dtEditCategory,
  dtCategoryToggle,
  dtCategoryList,
  dtCategoryNewTip,
  dtCategoryNewTipText,
  dtEditCalculated,
  dtEditFormula,
  scheduleDatasetTypesAutoSave,
});

fieldMappingFeature = createFieldMappingFeature({
  fieldMappingBody,
  fieldMappingStatus,
  saveFieldMappingBtn,
  initTableColumnResizing,
  normalizeProjectKey,
  fetchImpl: fetch.bind(window),
  setStatus,
  getDatasetTypeNamesForProject: (...args) => datasetTypesFeature?.getDatasetTypeNamesForProject(...args) || [],
  getCurrentFieldNames: () => currentFieldNames,
  loadAuditLog,
  syncDatasetTypesSources: (...args) => syncDatasetTypeSourcesAfterFieldMappingSave(...args),
});

reservingClassTypesFeature = createReservingClassTypesFeature({
  reservingClassTypesBody,
  reservingClassTypesStatus,
  reservingClassTypesRowContextMenu,
  reservingClassTypeEditor,
  reservingClassTypeEditorHeader,
  reservingClassTypeEditorTitle,
  rctEditName,
  rctEditLevel,
  rctEditFormula,
  rctFormulaReview,
  initTableColumnResizing,
  normalizeProjectKey,
  fetchImpl: fetch.bind(window),
  setStatus,
  loadAuditLog,
  hideContextMenu,
  hideFolderContextMenu,
  hideTreeContextMenu,
  hideDatasetTypesRowContextMenu: (...args) => datasetTypesFeature?.hideDatasetTypesRowContextMenu(...args),
  scheduleReservingClassTypesAutoSave,
  positionContextMenu,
});

dataProcessingRulesFeature = createDataProcessingRulesFeature({
  rulesBody: dataProcessingRulesBody,
  rulesStatus: dataProcessingRulesStatus,
  rowContextMenu: dataProcessingRulesRowContextMenu,
  addButton: addDataProcessingRuleBtn,
  validateButton: validateDataProcessingRulesBtn,
  jsonButton: dataProcessingRulesJsonBtn,
  editor: dataProcessingRuleEditor,
  editorTitle: dataProcessingRuleEditorTitle,
  editorClose: dataProcessingRuleEditorClose,
  editName: dprEditName,
  editEnabled: dprEditEnabled,
  autoNamePill: dprAutoNamePill,
  editEnabledLabel: dprEditEnabledLabel,
  editSourceMeasure: dprEditSourceMeasure,
  requestConditions: dprRequestConditions,
  addRequestConditionButton: dprAddRequestConditionBtn,
  thenConditions: dprThenConditions,
  addThenConditionButton: dprAddThenConditionBtn,
  actionVerbGroup: dprActionVerbGroup,
  keepHint: dprKeepHint,
  dprVocabWarning,
  editSummary: dprEditSummary,
  editError: dprEditError,
  editorCancelButton: dprEditorCancelBtn,
  editorSaveButton: dprEditorSaveBtn,
  jsonOverlay: dataProcessingRulesJsonOverlay,
  jsonBody: dataProcessingRulesJsonBody,
  jsonClose: dataProcessingRulesJsonClose,
  fetchImpl: fetch.bind(window),
  setStatus,
  publishShellProgress: (message) => window.parent.postMessage(message, window.location.origin),
  loadAuditLog,
  showConfirm,
  initTableColumnResizing,
  positionContextMenu,
  hideContextMenu,
  hideFolderContextMenu,
  hideTreeContextMenu,
  hideDatasetTypesRowContextMenu: (...args) => datasetTypesFeature?.hideDatasetTypesRowContextMenu(...args),
  hideReservingClassTypesRowContextMenu: (...args) => reservingClassTypesFeature?.hideReservingClassTypesRowContextMenu(...args),
});

// ============ Load JSON Data ============
async function loadProjectData(sourceKey = DEFAULT_SOURCE) {
  setStatus("Loading projects...");
  generalSettingsFeature.clearCache();
  try {
    const { path } = await projectMapStore.load(sourceKey);
    treeViewFeature.render();
    restoreSelectedProjectFromSession();
    setStatus(`Loaded ${projectMapStore.countProjects()} projects from ${path}`);
  } catch (err) {
    setStatus(`Error loading: ${err.message}`);
    console.error(err);
  }
}

// ============ Project Selection ============
function clearProjectSelection() {
  selectedProject = null;
  treeViewFeature.clearSelectedProjectFromSession();
  switchCover.cancel();
  detailEmpty.style.display = "flex";
  detailView.style.display = "none";
}

function restoreSelectedProjectFromSession() {
  const snapshot = treeViewFeature.loadSelectedProjectFromSession()
    || treeViewFeature.buildSelectedProjectSnapshot(selectedProject);
  if (!snapshot) return false;

  const project = projectMapStore.findProjectBySnapshot(snapshot);
  if (!project) {
    clearProjectSelection();
    return false;
  }

  selectProject(project);
  return true;
}

/**
 * Blank every detail panel for a newly selected project.
 *
 * Each ribbon page loads from the project folder on a network drive, so the
 * first rendered content is seconds away. Until then the previous project's
 * rows would still be on screen under the new project's title; this replaces
 * them with the same flowing placeholder Source Data shows, so switching
 * projects reads as one busy page rather than six unrelated states.
 */
function clearProjectDetailPanels(project) {
  detailEmpty.style.display = "none";
  detailView.style.display = "flex";
  detailTitle.textContent = String(project?.name || "");
  detailForm.innerHTML = "";
  detailForm.style.display = "none";
  currentFieldNames = [];

  datasetTypesFeature?.closeDatasetTypeEditor();
  sourceDataFeature.resetForProjectChange();

  fieldMappingFeature?.renderFieldMappingLoading();
  fieldMappingFeature?.setFieldMappingStatus("");
  // The previous project's unsaved edits must not leave Save actionable here.
  fieldMappingFeature?.updateSaveFieldMappingButton(project?.name);
  reservingClassTypesFeature?.renderReservingClassTypesLoading();
  reservingClassTypesFeature?.setReservingClassTypesStatus("");
  datasetTypesFeature?.renderDatasetTypesLoading();
  datasetTypesFeature?.setDatasetTypesStatus("");
  dataProcessingRulesFeature?.renderRulesLoading();
  dataProcessingRulesFeature?.setRulesStatus("");
  auditLogStore.renderLoading();
  auditLogStore.setStatus("");
}

async function selectProject(project) {
  reservingClassTypesFeature?.closeReservingClassTypeEditor();
  dataProcessingRulesFeature?.closeEditor();
  const selectionKey = normalizeProjectKey(project?.name);
  let coverHandle = null;
  // Reselecting the current project refreshes it in place; only a real
  // selection change has stale content to drop.
  if (normalizeProjectKey(selectedProject?.name) !== selectionKey) {
    coverHandle = switchCover.show(project?.name);
    clearProjectDetailPanels(project);
  }
  selectedProject = project;
  treeViewFeature.saveSelectedProjectToSession(project);
  treeViewFeature.render(); // Update active state
  let preferences = {};
  try {
    preferences = await loadProjectUserPreferences(project?.name, { forceReload: true });
  } catch (err) {
    console.warn("Failed to load Project Settings table defaults:", err);
  }
  if (!selectedProject || normalizeProjectKey(selectedProject.name) !== selectionKey) return;
  applyProjectSettingsTablePreferences(preferences);
  sourceDataFeature.applyConfiguredColumnWidths();
  const loads = showProjectDetails(project);
  void switchCover.hide(coverHandle, loads);
  // Update tree header to show the last part of the folder name
  if (treeHeader && project.folder) {
    const parts = project.folder.split("\\");
    treeHeader.textContent = parts[parts.length - 1];
  }
}

function showProjectDetails(project) {
  detailEmpty.style.display = "none";
  detailView.style.display = "flex";
  detailTitle.textContent = project.name;
  treeViewFeature.saveSelectedProjectToSession(project);

  // Ensure rename button exists next to title
  let renameBtn = document.getElementById("detailRenameBtn");
  if (!renameBtn) {
    renameBtn = document.createElement("button");
    renameBtn.id = "detailRenameBtn";
    renameBtn.className = "detail-rename-btn";
    renameBtn.title = "Rename project";
    renameBtn.innerHTML = `<svg viewBox="0 0 32 32" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 4 L28 10 L12 26 L4 28 L6 20 Z"/><line x1="19" y1="7" x2="25" y2="13"/></svg>`;
    detailTitle.parentNode.insertBefore(renameBtn, detailTitle.nextSibling);
  }
  renameBtn.onclick = () => projectOpsFeature.renameProject(project);

  // Detail form fields were moved to ribbon panels.
  detailForm.innerHTML = "";
  detailForm.style.display = "none";
  bindSummaryTablePathEditor(project);
  generalSettingsFeature.bindEditor(project);
  void projectLockFeature.load(project.name);

  // Load the summary of the table this project has imported.
  const summaryLoad = loadTableSummary(project.name);
  // A refresh submitted before the page was reloaded is still running on the
  // server; re-attach to it so its progress is visible again.
  void resumePendingSourceRefresh(project.name);
  // Returned so a project switch can wait on the page loads.
  return [summaryLoad, datasetTypesFeature?.loadDatasetTypes(project.name),
    reservingClassTypesFeature?.loadReservingClassTypes(project.name),
    dataProcessingRulesFeature?.loadRules(project.name), loadAuditLog(project.name)];
}

// ============ Source Table Path ============
function getDirFromPath(filePath) {
  const s = String(filePath || "").trim();
  if (!s) return "";
  const slash = Math.max(s.lastIndexOf("\\"), s.lastIndexOf("/"));
  if (slash <= 0) return "";
  return s.slice(0, slash);
}

/** Open the desktop file picker, starting beside the currently entered path. */
async function pickTablePathFromHost(currentPath = "") {
  const hostApi = window.ADAHost
    || window.parent?.ADAHost
    || window.top?.ADAHost;
  if (!hostApi?.pickOpenTableFile) {
    setStatus("Browse is available in the desktop app only.");
    return "";
  }
  const startDir = getDirFromPath(currentPath) || getDirFromPath(summaryTablePathInput?.value);
  try {
    const selected = await hostApi.pickOpenTableFile(startDir || "");
    return String(selected || "");
  } catch {
    return "";
  }
}

/**
 * Bind the Source Data header to a project.
 *
 * The hidden path input stays the page's record of the current CSV selection:
 * the folder actions read it and `/source_table` responses fill it through
 * `applySourceState`. Reload re-reads what this page shows; re-importing the
 * external source and rebuilding what depends on it is Import Data's job.
 */
function bindSummaryTablePathEditor(project) {
  if (!summaryTablePathInput || !summaryTablePathReloadBtn) return;

  summaryTablePathInput.value = "";
  summaryTablePathReloadBtn.disabled = false;
  sourceDataFeature.syncPathDisplay(summaryTablePathInput.value);

  let reloading = false;
  const isCurrentProject = () => !!selectedProject && selectedProject.name === project.name;

  summaryTablePathReloadBtn.onclick = async () => {
    if (!isCurrentProject() || reloading) return;
    reloading = true;
    summaryTablePathReloadBtn.disabled = true;
    try {
      setStatus("Reloading table summary...");
      // Read-only on purpose. A forced refresh re-imports the source table,
      // deletes every generated dataset cache in the project and rebuilds the
      // reserving-class values - minutes of SMB work for a button that only
      // redraws this page. The plain read is Server-hosted, so the summary is
      // built where the data lives and only its payload crosses the network.
      const refreshed = await loadTableSummary(project.name, {
        forceFieldMappingReload: true,
        forceReservingClassTypesReload: true,
        forceDerivedDates: true,
      });
      if (!refreshed) throw new Error("Unable to reload table summary.");
      setStatus("Reloaded table summary.");
    } catch (err) {
      alert(`Failed to reload table summary: ${err.message}`);
      setStatus(`Failed to reload table summary: ${err.message}`);
    } finally {
      if (isCurrentProject()) summaryTablePathReloadBtn.disabled = false;
      reloading = false;
    }
  };
}

// ============ Import Source (CSV file / SQL Server) ============
/** Load the project's import-source record and hand it to the Source Data tab. */
async function loadSourceTableState(projectName) {
  const name = String(projectName || "").trim();
  if (!name) return sourceDataFeature.applySourceState(null);
  try {
    const res = await fetch(`/source_table?project_name=${encodeURIComponent(name)}`);
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    return sourceDataFeature.applySourceState(await res.json());
  } catch (err) {
    setStatus(`Could not read the import source: ${err.message}`);
    return sourceDataFeature.applySourceState(null);
  }
}

/**
 * Live identity of the external source file, for the table details panel.
 *
 * The import record only knows what the file's modified time was when the copy
 * was taken, so the panel asks the file itself each time it opens. A failed
 * read leaves the panel on the recorded time rather than raising an alert over
 * a hover.
 */
async function loadSourceFileStatus() {
  const name = String(selectedProject?.name || "").trim();
  if (!name) return null;
  try {
    const res = await fetch(`/source_table/file_status?project_name=${encodeURIComponent(name)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/** Tables and views available in the database the panel is pointed at. */
async function listSourceTables(profile) {
  try {
    const res = await fetch("/source_table/tables", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) return { ok: false, error: await readResponseErrorDetail(res), tables: [] };
    return await res.json();
  } catch (err) {
    return { ok: false, error: err.message || "Could not reach the app server.", tables: [] };
  }
}

/** Server-shared list of previously used SQL Server server/database pairs. */
async function listSourceConnections() {
  try {
    const res = await fetch("/source_table/connections");
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    return await res.json();
  } catch (err) {
    setStatus(`Could not read saved SQL Server connections: ${err.message}`);
    return { connections: [] };
  }
}

/** Drop one saved pair, or every pair for a server when no database is given. */
async function forgetSourceConnection(server, database) {
  try {
    const res = await fetch("/source_table/connections/forget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ server, database: database || null }),
    });
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    return await res.json();
  } catch (err) {
    sourceDataFeature.setSourceStatus(
      err.message || "Could not remove the saved connection.",
      "error",
    );
    return listSourceConnections();
  }
}

/**
 * What the Import Scope step can offer for the selected project.
 *
 * The lists are read fresh from the app server rather than from the Dataset
 * Types and Reserving Class Types panes: the pane state carries only the
 * columns it displays, and the `Generated` flag that says whether a dataset
 * type is engine-built from a source column is not one of them.
 */
async function loadImportScopeOptions() {
  const name = String(selectedProject?.name || "").trim();
  if (!name) return { ok: false, error: "Select a project first." };
  const query = new URLSearchParams({ project_name: name }).toString();
  try {
    const [typesRes, classTypesRes] = await Promise.all([
      fetch(`/dataset_types?${query}`),
      fetch(`/reserving_class_types?${query}`),
    ]);
    if (!typesRes.ok) throw new Error(await readResponseErrorDetail(typesRes));
    if (!classTypesRes.ok) throw new Error(await readResponseErrorDetail(classTypesRes));
    const types = await typesRes.json();
    const classTypes = await classTypesRes.json();
    const generated = types?.data?.generated_by_name || {};
    const datasetTypes = (types?.data?.rows || [])
      .map((row) => ({ name: String(row?.[0] ?? "").trim(), category: String(row?.[2] ?? "").trim() }))
      .filter((item) => item.name && generated[item.name] === true);
    const reservingClassTypes = (classTypes?.data?.rows || [])
      .map((row) => ({ name: String(row?.[0] ?? "").trim(), level: Number(row?.[1]) }))
      .filter((item) => item.name && Number.isInteger(item.level) && item.level >= 1);
    return { ok: true, datasetTypes, reservingClassTypes };
  } catch (err) {
    return { ok: false, error: err.message || "Could not read the project's types." };
  }
}

/** Everything the page shows about the source table, reloaded after a refresh. */
async function reloadSourceDataViews(name, { forceRefresh }) {
  await loadSourceTableState(name);
  await loadTableSummary(name, {
    forceRefresh,
    forceFieldMappingReload: true,
    forceReservingClassTypesReload: true,
  });
}

/** Save the settings and run an import; see project_settings_source_import.js. */
const sourceImport = createSourceImport({
  fetchImpl: fetch.bind(window),
  readResponseErrorDetail,
  getProjectName: () => selectedProject?.name,
  sourceRefresh: sourceRefreshFeature,
  applySourceState: (state) => sourceDataFeature.applySourceState(state),
  setSourceStatus: (...args) => sourceDataFeature.setSourceStatus(...args),
  setStatus,
  showProgress: showProjectOperationProgress,
  hideProgress: hideProjectOperationProgress,
  reloadViews: reloadSourceDataViews,
});

// ============ Table Summary ============
function normalizeSummaryColumnKey(value) {
  return String(value || "").trim().toLowerCase();
}

function findSummaryColumnByName(summaryColumns, fieldName) {
  const key = normalizeSummaryColumnKey(fieldName);
  if (!key) return null;
  for (const column of Array.isArray(summaryColumns) ? summaryColumns : []) {
    const name = normalizeSummaryColumnKey(column?.name);
    if (name && name === key) return column;
  }
  return null;
}

function extractRangeBoundsFromSummary(column) {
  const values = String(column?.values || "").trim();
  if (!values) return { min: "", max: "" };

  const m = values.match(/^range:\s*(.+)$/i);
  if (!m) return { min: "", max: "" };
  const range = String(m[1] || "").trim();
  if (!range) return { min: "", max: "" };

  const dtype = String(column?.dtype || "").toLowerCase();
  const friendlyType = String(column?.type || "").toLowerCase();
  if (friendlyType === "datetime" || dtype.includes("datetime")) {
    const sep = " - ";
    const idx = range.indexOf(sep);
    if (idx > 0) {
      return {
        min: range.slice(0, idx).trim(),
        max: range.slice(idx + sep.length).trim(),
      };
    }
  }

  const numericMatches = range.match(/-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?/g);
  if (Array.isArray(numericMatches) && numericMatches.length >= 2) {
    return {
      min: String(numericMatches[0] || "").trim(),
      max: String(numericMatches[numericMatches.length - 1] || "").trim(),
    };
  }
  return { min: "", max: "" };
}

async function fetchMappedDateFields(projectName) {
  const result = { originField: "", developmentField: "" };
  const name = String(projectName || "").trim();
  if (!name) return result;

  try {
    const res = await fetch(`/field_mapping?project_name=${encodeURIComponent(name)}`);
    if (!res.ok) return result;
    const out = await res.json();
    const rows = Array.isArray(out?.data?.rows) ? out.data.rows : [];

    for (const row of rows) {
      const significance = String(row?.significance || "").trim();
      const fieldName = String(row?.field_name || "").trim();
      if (!fieldName) continue;
      if (significance === "Origin Date" && !result.originField) result.originField = fieldName;
      if (significance === "Development Date" && !result.developmentField) result.developmentField = fieldName;
      if (result.originField && result.developmentField) break;
    }
  } catch {
    // Ignore mapping load failures here; field mapping panel has its own explicit errors.
  }
  return result;
}

function deriveSummaryDateInputs(summaryColumns, mappedDateFields) {
  const originCol = findSummaryColumnByName(summaryColumns, mappedDateFields?.originField);
  const developmentCol = findSummaryColumnByName(summaryColumns, mappedDateFields?.developmentField);
  const originRange = extractRangeBoundsFromSummary(originCol);
  const developmentRange = extractRangeBoundsFromSummary(developmentCol);
  return {
    originStart: originRange.min || "",
    originEnd: originRange.max || "",
    developmentEnd: developmentRange.max || "",
  };
}

async function clearArcRhoHeadersCacheForProject(projectName) {
  const name = String(projectName || "").trim();
  if (!name) return { ok: true, cleared_count: 0 };
  try {
    const res = await fetch("/arcrho/headers/cache/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ProjectName: name }),
    });
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    return res.json();
  } catch (err) {
    setStatus(`Warning: failed to clear the project header cache for "${name}": ${err.message}`);
    return { ok: false, error: String(err.message || err) };
  }
}

async function clearGeneratedDatasetCsvCachesForProject(projectName) {
  const name = String(projectName || "").trim();
  if (!name) return { ok: true, cleared_count: 0, preserved_count: 0 };
  try {
    const res = await fetch(`/project_settings/${DEFAULT_SOURCE}/generated_dataset_cache/clear`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_name: name }),
    });
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    return res.json();
  } catch (err) {
    setStatus(`Warning: failed to clear generated dataset caches for "${name}": ${err.message}`);
    return { ok: false, error: String(err.message || err), cleared_count: 0, preserved_count: 0 };
  }
}

/** Apply a stored General Settings record to the period inputs. */
function applyStoredPeriodsToInputs(values) {
  generalSettingsFeature.setDerivedDateInputs({
    originStart: values.originStartDate,
    originEnd: values.originEndDate,
    developmentEnd: values.developmentEndDate,
  });
}

async function loadTableSummary(projectName = "", options = {}) {
  const forceRefresh = !!options?.forceRefresh;
  const forceFieldMappingReload = !!options?.forceFieldMappingReload;
  const forceReservingClassTypesReload = !!options?.forceReservingClassTypesReload;
  // Re-deriving the period boundaries is page state, not source data, so a
  // read-only reload can ask for it without asking for the whole rebuild.
  const forceDerivedDates = forceRefresh || !!options?.forceDerivedDates;
  const summaryEl = document.getElementById("tableSummary");
  const requestSeq = ++tableSummaryLoadSeq;
  const isStale = () => requestSeq !== tableSummaryLoadSeq;

  summaryEl.style.display = "flex";
  const sourceState = await loadSourceTableState(projectName);
  if (isStale()) return true;

  // Nothing to summarize until an import source is configured or a table has
  // already been imported into the project folder.
  const isSqlSource = sourceState.sourceType === "mssql";
  const hasSource = isSqlSource
    ? (sourceState.masterTableExists || !!sourceState.mssql.table)
    : (!!sourceState.csvPath || sourceState.masterTableExists);
  if (!hasSource) {
    sourceDataFeature.showNoPath(
      isSqlSource
        ? "No SQL Server table is configured for this project."
        : "No source file is configured for this project.",
    );
    const existingGeneralSettings = await generalSettingsFeature.ensureLoaded(projectName, { applyToInputs: false });
    if (isStale()) return true;
    applyStoredPeriodsToInputs(existingGeneralSettings);
    currentFieldNames = [];
    fieldMappingFeature?.renderFieldMappingEmpty("No source table is configured for this project.");
    fieldMappingFeature?.setFieldMappingStatus("");
    if (forceReservingClassTypesReload) {
      await reservingClassTypesFeature?.loadReservingClassTypes(projectName, { force: true });
    }
    return true;
  }

  sourceDataFeature.showLoading();
  // The field list arrives with this summary, so both tabs stay busy together.
  fieldMappingFeature?.renderFieldMappingLoading();

  try {
    if (forceRefresh && projectName) {
      await clearArcRhoHeadersCacheForProject(projectName);
      const generatedCacheClear = await clearGeneratedDatasetCsvCachesForProject(projectName);
      if (generatedCacheClear?.ok && Number(generatedCacheClear.cleared_count || 0) > 0) {
        setStatus(`Cleared ${generatedCacheClear.cleared_count} generated dataset cache file(s).`);
      }
      if (isStale()) return true;
    }

    let res = null;
    if (forceRefresh) {
      res = await fetch("/table_summary/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: projectName || "",
          refresh_reserving: true,
        }),
      });
    } else {
      const q = new URLSearchParams({ project_name: projectName || "" });
      res = await fetch(`/table_summary?${q.toString()}`);
    }
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));

    const data = await res.json();
    if (isStale()) return true;

    // A CSV refresh may have re-copied the master table; pick up its provenance.
    if (forceRefresh) {
      await loadSourceTableState(projectName);
      if (isStale()) return true;
    }
    currentFieldNames = Array.isArray(data.columns)
      ? data.columns.map(col => String(col?.name || "").trim()).filter(Boolean)
      : [];
    const existingGeneralSettings = await generalSettingsFeature.ensureLoaded(projectName, { applyToInputs: false });
    if (isStale()) return true;
    // Source Data reads each column's date role off the summary payload. This
    // copy stays only for deriving the reserving-period boundary inputs.
    const mappedDateFields = await fetchMappedDateFields(projectName);
    if (isStale()) return true;
    const derivedValues = deriveSummaryDateInputs(data.columns, mappedDateFields);
    const shouldApplyDerived = (
      !generalSettingsFeature.hasValues(existingGeneralSettings)
      || (forceDerivedDates && !!existingGeneralSettings.autoGenerated)
    );
    if (shouldApplyDerived) {
      generalSettingsFeature.setDerivedDateInputs(derivedValues);
      await generalSettingsFeature.save(
        projectName,
        {
          originStartDate: derivedValues.originStart || "",
          originEndDate: derivedValues.originEnd || "",
          developmentEndDate: derivedValues.developmentEnd || "",
        },
        {
          autoGenerated: true,
          force: !!existingGeneralSettings.projectNameMismatch,
        },
      );
    } else {
      applyStoredPeriodsToInputs(existingGeneralSettings);
      // A duplicated or renamed project keeps its dates, re-saved under the new name.
      if (existingGeneralSettings.projectNameMismatch) await generalSettingsFeature.save(projectName, existingGeneralSettings, { autoGenerated: existingGeneralSettings.autoGenerated, force: true });
    }
    if (isStale()) return true;
    sourceDataFeature.renderSummary(data);
    await fieldMappingFeature?.ensureFieldMappingLoaded(projectName, {
      force: forceRefresh || forceFieldMappingReload,
    });
    if (isStale()) return true;
    fieldMappingFeature?.renderFieldMappingTable(currentFieldNames, projectName);
    fieldMappingFeature?.setFieldMappingStatus("");
    if (forceReservingClassTypesReload) {
      await reservingClassTypesFeature?.loadReservingClassTypes(projectName, { force: true });
    }
    return true;

  } catch (err) {
    if (isStale()) return true;
    sourceDataFeature.showError(err.message || "Unable to read the source table.");
    const existingGeneralSettings = await generalSettingsFeature.ensureLoaded(projectName, { applyToInputs: false });
    if (isStale()) return true;
    applyStoredPeriodsToInputs(existingGeneralSettings);
    currentFieldNames = [];
    fieldMappingFeature?.renderFieldMappingEmpty("Unable to load fields from Table Summary.");
    fieldMappingFeature?.setFieldMappingStatus(err.message || "Unable to load table summary.", true);
    return false;
  }
}

// ============ Open Project Instance ============
function openProjectInstanceTab(project) {
  window.parent.postMessage({
    type: "arcrho:open-project-instance",
    project: {
      name: project.name,
      folder: project.folder,
    },
  }, "*");

  setStatus(`Opening datasets: ${project.name}`);
}

async function openProjectFolderInExplorer(project) {
  const projectName = String(project?.name || "").trim();
  if (!projectName) {
    setStatus("Select a project first.");
    return;
  }

  if (openProjectFolderBtn) openProjectFolderBtn.disabled = true;
  setStatus(`Opening project folder: ${projectName}`);
  try {
    const res = await fetch(`/project_settings/${DEFAULT_SOURCE}/open_project_folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_name: projectName }),
    });
    if (!res.ok) throw new Error(await readResponseErrorDetail(res));
    const out = await res.json();
    const path = String(out?.path || "").trim();
    setStatus(path ? `Opened project folder: ${path}` : `Opened project folder: ${projectName}`);
  } catch (err) {
    const msg = err?.message || "Unable to open project folder.";
    alert(`Failed to open project folder: ${msg}`);
    setStatus(`Failed to open project folder: ${msg}`);
  } finally {
    if (openProjectFolderBtn) openProjectFolderBtn.disabled = false;
  }
}

// ============ Resize Handle ============
let isResizing = false;

resizeHandle.addEventListener("mousedown", (e) => {
  isResizing = true;
  document.body.style.cursor = "col-resize";
  e.preventDefault();
});

document.addEventListener("mousemove", (e) => {
  if (!isResizing) return;
  const newWidth = e.clientX;
  if (newWidth >= 200 && newWidth <= 500) {
    treePanel.style.width = `${newWidth}px`;
  }
});

document.addEventListener("mouseup", () => {
  if (isResizing) {
    isResizing = false;
    document.body.style.cursor = "";
  }
});

// ============ Event Handlers ============
openProjectFolderBtn?.addEventListener("click", async () => {
  if (!selectedProject) return;
  await openProjectFolderInExplorer(selectedProject);
});

saveFieldMappingBtn?.addEventListener("click", () => {
  if (!selectedProject) {
    fieldMappingFeature?.setFieldMappingStatus("Select a project first.", true);
    return;
  }
  fieldMappingFeature?.saveFieldMapping(selectedProject);
});

// ============ Custom Prompt Dialog ============
let dialogResolve = null;

function showDialog(title, defaultValue = "") {
  return new Promise((resolve) => {
    dialogResolve = resolve;
    dialogTitle.textContent = title;
    dialogInput.value = defaultValue;
    dialogInput.removeAttribute("readonly");
    dialogInput.removeAttribute("disabled");
    dialogOverlay.classList.add("show");
    // Defer focus so the dialog is painted and context menu / other UI has released focus (fixes Electron/iframe)
    setTimeout(() => {
      dialogInput.focus();
      dialogInput.select();
    }, 50);
  });
}

function hideDialog(result) {
  dialogOverlay.classList.remove("show");
  if (dialogResolve) {
    dialogResolve(result);
    dialogResolve = null;
  }
}

dialogOk.addEventListener("click", () => {
  hideDialog(dialogInput.value.trim());
});

dialogCancel.addEventListener("click", () => {
  hideDialog(null);
});

dialogInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    hideDialog(dialogInput.value.trim());
  } else if (e.key === "Escape") {
    hideDialog(null);
  }
});

// Keep focus inside dialog: stop events from bubbling to parent (helps in Electron/iframe)
const dialogBox = document.getElementById("dialogBox");
dialogOverlay.addEventListener("mousedown", (e) => {
  if (dialogBox.contains(e.target)) {
    e.stopPropagation();
  }
});
dialogOverlay.addEventListener("click", (e) => {
  if (dialogBox.contains(e.target)) {
    e.stopPropagation();
  }
});

// ============ Custom Confirm Dialog ============
let confirmResolve = null;

function showConfirm(message, title = "Confirm") {
  return new Promise((resolve) => {
    confirmResolve = resolve;
    confirmTitle.textContent = title;
    confirmMessage.textContent = message;
    confirmOverlay.classList.add("show");
    setTimeout(() => confirmOk.focus(), 50);
  });
}

function hideConfirm(result) {
  confirmOverlay.classList.remove("show");
  if (confirmResolve) {
    confirmResolve(result);
    confirmResolve = null;
  }
}

confirmOk.addEventListener("click", () => hideConfirm(true));
confirmCancel.addEventListener("click", () => hideConfirm(false));
confirmOverlay.addEventListener("keydown", (e) => {
  if (e.key === "Enter") hideConfirm(true);
  else if (e.key === "Escape") hideConfirm(false);
});
confirmOverlay.addEventListener("mousedown", (e) => {
  if (confirmBox.contains(e.target)) e.stopPropagation();
});
confirmOverlay.addEventListener("click", (e) => {
  if (confirmBox.contains(e.target)) e.stopPropagation();
});

// ============ Context Menu ============
function positionContextMenu(menu, x, y) {
  menu.style.left = `${x}px`;
  menu.style.top = `${y}px`;
  menu.classList.add("show");
  // Adjust if overflowing viewport
  const rect = menu.getBoundingClientRect();
  if (rect.bottom > window.innerHeight) {
    menu.style.top = `${Math.max(0, y - (rect.bottom - window.innerHeight))}px`;
  }
  if (rect.right > window.innerWidth) {
    menu.style.left = `${Math.max(0, x - (rect.right - window.innerWidth))}px`;
  }
}

function hideContextMenu() {
  contextMenu.classList.remove("show");
  contextMenuProject = null;
}

function hideFolderContextMenu() {
  folderContextMenu.classList.remove("show");
  contextMenuFolder = null;
}

function hideTreeContextMenu() {
  treeContextMenu.classList.remove("show");
}

function hideFeatureRowContextMenus() {
  datasetTypesFeature?.hideDatasetTypesRowContextMenu();
  reservingClassTypesFeature?.hideReservingClassTypesRowContextMenu();
}

function showProjectContextMenu(project, x, y) {
  contextMenuProject = project;
  contextMenuFolder = null;
  hideFolderContextMenu();
  hideTreeContextMenu();
  hideFeatureRowContextMenus();
  positionContextMenu(contextMenu, x, y);
}

function showFolderContextMenu(folderNode, x, y) {
  contextMenuFolder = folderNode;
  contextMenuProject = null;
  hideContextMenu();
  hideTreeContextMenu();
  hideFeatureRowContextMenus();
  positionContextMenu(folderContextMenu, x, y);
}

// Hide context menus on click outside
document.addEventListener("click", (e) => {
  if (!contextMenu.contains(e.target)) hideContextMenu();
  if (!folderContextMenu.contains(e.target)) hideFolderContextMenu();
  if (!treeContextMenu.contains(e.target)) hideTreeContextMenu();
  if (!datasetTypesRowContextMenu?.contains(e.target)) datasetTypesFeature?.hideDatasetTypesRowContextMenu();
  if (!reservingClassTypesRowContextMenu?.contains(e.target)) reservingClassTypesFeature?.hideReservingClassTypesRowContextMenu();
});

// Right-click on tree blank area: Create root folder
treeContent.addEventListener("contextmenu", (e) => {
  // Only when clicking on blank area (not on a folder or project)
  if (e.target.closest(".tree-folder") || e.target.closest(".tree-project")) return;
  if (!treeContent.contains(e.target)) return;
  e.preventDefault();
  contextMenuFolder = null;
  contextMenuProject = null;
  hideContextMenu();
  hideFolderContextMenu();
  hideFeatureRowContextMenus();
  positionContextMenu(treeContextMenu, e.clientX, e.clientY);
});

// Context menu actions (projects)
contextMenu.addEventListener("click", (e) => {
  const action = e.target.dataset.action;
  if (!action || !contextMenuProject) return;

  const project = contextMenuProject;
  hideContextMenu();

  if (action === "rename") {
    projectOpsFeature.renameProject(project);
  } else if (action === "duplicate") {
    projectOpsFeature.duplicateProject(project);
  } else if (action === "delete") {
    projectOpsFeature.deleteProject(project);
  }
});

// Folder context menu: Rename, Create New Project, Create subfolder, Delete
folderContextMenu.addEventListener("click", (e) => {
  const action = e.target.dataset.action;
  if (!action || !contextMenuFolder) return;
  const folderNode = contextMenuFolder;
  hideFolderContextMenu();
  if (action === "rename-folder") {
    projectOpsFeature.renameFolder(folderNode);
  } else if (action === "create-project-in-folder") {
    projectOpsFeature.createProjectInFolder(folderNode);
  } else if (action === "create-subfolder") {
    projectOpsFeature.createSubfolder(folderNode);
  } else if (action === "delete-folder") {
    projectOpsFeature.deleteFolder(folderNode);
  }
});

// Tree context menu: Create root folder
treeContextMenu.addEventListener("click", (e) => {
  if (e.target.dataset.action !== "create-root-folder") return;
  hideTreeContextMenu();
  projectOpsFeature.createRootFolder();
});

datasetTypesRowContextMenu?.addEventListener("click", (e) => {
  const action = e.target?.dataset?.action;
  if (!action) return;
  datasetTypesFeature?.handleDatasetTypesRowContextAction(action);
});

datasetTypeEditorClose?.addEventListener("click", () => {
  datasetTypesFeature?.closeDatasetTypeEditor();
});

dtEditorCancelBtn?.addEventListener("click", () => {
  datasetTypesFeature?.closeDatasetTypeEditor();
});

dtEditorSaveBtn?.addEventListener("click", () => {
  datasetTypesFeature?.applyDatasetTypeEditor();
});

datasetTypeEditorHeader?.addEventListener("mousedown", (e) => {
  datasetTypesFeature?.onEditorHeaderMouseDown(e);
});

dtEditCalculated?.addEventListener("change", () => {
  datasetTypesFeature?.handleDatasetTypeEditorCalculatedToggle();
});

reservingClassTypesRowContextMenu?.addEventListener("click", (e) => {
  const action = e.target?.dataset?.action;
  if (!action) return;
  reservingClassTypesFeature?.handleReservingClassTypesRowContextAction(action);
});

reservingClassTypeEditorClose?.addEventListener("click", () => {
  reservingClassTypesFeature?.closeReservingClassTypeEditor();
});

rctEditorCancelBtn?.addEventListener("click", () => {
  reservingClassTypesFeature?.closeReservingClassTypeEditor();
});

rctEditorSaveBtn?.addEventListener("click", () => {
  reservingClassTypesFeature?.applyReservingClassTypeEditor();
});

reservingClassTypeEditorHeader?.addEventListener("mousedown", (e) => {
  reservingClassTypesFeature?.onEditorHeaderMouseDown(e);
});

reservingClassTypeEditorResizer?.addEventListener("mousedown", (e) => {
  reservingClassTypesFeature?.onEditorResizerMouseDown(e);
});

document.addEventListener("mousemove", (e) => {
  reservingClassTypesFeature?.onEditorMouseMove(e);
  datasetTypesFeature?.onEditorMouseMove(e);
  sourceDataFeature?.onEditorMouseMove(e);
});

document.addEventListener("mouseup", () => {
  reservingClassTypesFeature?.onEditorMouseUp();
  datasetTypesFeature?.onEditorMouseUp();
  sourceDataFeature?.onEditorMouseUp();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (datasetTypeEditor?.classList.contains("show")) {
      datasetTypesFeature?.closeDatasetTypeEditor();
    }
  }
});

// ============ Ribbon Tab Switching ============
(function initRibbon() {
  const ribbonBar = document.getElementById("ribbonBar");
  if (!ribbonBar) return;

  const panelMap = {
    "summary": document.getElementById("ribbonSummary"),
    "field-mapping": document.getElementById("ribbonFieldMapping"),
    "reserving-class-types": document.getElementById("ribbonReservingClassTypes"),
    "dataset-types": document.getElementById("ribbonDatasetTypes"),
    "data-processing": document.getElementById("ribbonDataProcessing"),
    "audit-log": document.getElementById("ribbonAuditLog"),
    "project-settings": document.getElementById("ribbonProjectSettings"),
  };

  const initialActiveItem = ribbonBar.querySelector(".ribbon-item.active");
  const initialKey = String(initialActiveItem?.dataset?.ribbon || "").trim().toLowerCase();
  if (initialKey) {
    activeProjectSettingsRibbon = initialKey;
  }
  notifyProjectSettingsRibbonChanged();

  ribbonBar.addEventListener("click", (e) => {
    const item = e.target.closest(".ribbon-item");
    if (!item) return;
    const key = String(item.dataset.ribbon || "").trim().toLowerCase();
    if (!key) return;

    // Update active ribbon
    ribbonBar.querySelectorAll(".ribbon-item").forEach(r => r.classList.remove("active"));
    item.classList.add("active");

    // Show matching panel
    Object.entries(panelMap).forEach(([k, panel]) => {
      if (panel) panel.classList.toggle("active", k === key);
    });
    activeProjectSettingsRibbon = key;
    notifyProjectSettingsRibbonChanged();
    if (key === "audit-log" && selectedProject?.name) {
      loadAuditLog(selectedProject.name, true);
    }
  });
})();

// ============ Initialize ============
(async function init() {
  document
    .querySelectorAll(".tree-content, .sd-list, .field-mapping-grid, .dataset-types-grid")
    .forEach(wireProjectSettingsTableScrollbarActivity);
  sourceDataFeature.init();
  const restoredFromSession = await treeViewFeature.restoreExpandedFolders();
  // Expand first level by default only when no prior local or in-session state exists.
  if (!restoredFromSession) {
    treeViewFeature.expandFolder("New Jersey");
    treeViewFeature.persistExpandedFolders({ immediate: true });
  }

  await reloadProjectSettingsForWorkspace();
})();
