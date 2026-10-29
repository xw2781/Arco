import { confirmDiscardClose } from "/ui/shared/components/close_confirm/close_confirm.js";
import { shell } from "./shell_context.js?v=20260510a";
import { isFloatingTab } from "./floating_tabs.js?v=20260510a";
import {
  getLastViewedDatasetInputs,
  normalizeBrowsingHistoryEntry,
} from "/ui/shell/browsing_history.js";
import {
  normalizeFolderKey,
  normalizeProjectInstanceState,
  normalizeShellActivityEntry,
  pushShellActivityHistoryEntry,
} from "/ui/shell/shell_activity_history.js";
import { ALLOWED_DFM_TABS } from "/ui/method_pages/dfm/dfm_tab_config.js";

// The single list of tab types that can be turned back into a tab from a saved descriptor.
// Browsing History and Home shortcut cards both reach it through `buildShellActivityEntry`, so
// neither can offer a target the shell cannot actually reopen.
const RESTORABLE_ACTIVITY_TYPES = new Set([
  "dataset",
  "dfm",
  "workflow",
  "project_settings",
  "project_instance",
  "scripting",
  "agent_guide",
  "file_explorer",
  "browsing_history",
  "server",
]);
const TASK_DESIGNER_TYPE = "task_designer";
let activeHistorySaveTimer = 0;
let pendingActiveHistoryEntry = null;

export function buildShellActivityEntry(tab) {
  if (!tab || !RESTORABLE_ACTIVITY_TYPES.has(tab.type)) return null;
  const entry = {
    tabType: tab.type,
    title: tab.title || tab.type,
  };
  if (tab.type === "dataset") {
    entry.datasetInputs = tab.datasetInputs || undefined;
  } else if (tab.type === "dfm") {
    entry.dfmInputs = tab.dfmInputs || undefined;
    entry.dfmTab = tab.dfmTab || "details";
  } else if (tab.type === "project_instance") {
    entry.projectName = String(tab.projectName || tab.title || "").trim();
    entry.projectFolder = String(tab.projectFolder || "").trim() || undefined;
    entry.projectTablePath = String(tab.projectTablePath || "").trim() || undefined;
    entry.projectInstanceState = normalizeProjectInstanceState(tab.projectInstanceState || null) || undefined;
  } else if (tab.type === "project_settings") {
    entry.projectSettingsRibbon = String(tab.projectSettingsRibbon || "summary").trim().toLowerCase();
  } else if (tab.type === "scripting") {
    entry.path = String(tab.scPath || tab.scOpenPath || "").trim() || undefined;
  } else if (tab.type === "file_explorer") {
    entry.path = String(tab.fileExplorerPath || "").trim() || undefined;
  }
  return normalizeShellActivityEntry(entry);
}

export function recordActiveTabHistory(tabOrId = null) {
  const tab = typeof tabOrId === "string"
    ? shell.state.tabs.find((item) => item.id === tabOrId)
    : (tabOrId || shell.state.tabs.find((item) => item.id === shell.state.activeId));
  const entry = buildShellActivityEntry(tab);
  if (!entry) return;
  pendingActiveHistoryEntry = entry;
  if (activeHistorySaveTimer) window.clearTimeout(activeHistorySaveTimer);
  activeHistorySaveTimer = window.setTimeout(() => {
    const next = pendingActiveHistoryEntry;
    pendingActiveHistoryEntry = null;
    activeHistorySaveTimer = 0;
    if (!next) return;
    pushShellActivityHistoryEntry(next)
      .then(() => shell.notifyBrowsingHistoryTabs?.({ activity: next }))
      .catch((err) => console.warn("Failed to save shell activity history:", err));
  }, 450);
}

export function setActive(id) {
  const tab = shell.state.tabs.find(t => t.id === id) || shell.state.tabs.find(t => t.id === "home");
  if (!tab) return;
  shell.state.activeId = tab.id;
  if (isFloatingTab(tab)) tab.floatZ = shell.state.nextFloatZ++;
  else shell.state.lastDockedActiveId = tab.id;
  if (tab.type !== "dfm") {
    shell.setDfmEditEnabled?.(false);
    shell.setDfmHistoryEnabled?.({ canUndo: false, canRedo: false });
  } else {
    shell.setDfmHistoryEnabled?.({ canUndo: !!tab.dfmCanUndo, canRedo: !!tab.dfmCanRedo });
  }
  shell.render?.();
  shell.saveState?.();
  recordActiveTabHistory(tab);
}

export function setDockedActive(id) {
  shell.state.activeId = id;
  shell.state.lastDockedActiveId = id;
  recordActiveTabHistory(id);
}

export function floatTab(id, rect) {
  const tab = shell.state.tabs.find(t => t.id === id);
  if (!tab || tab.id === "home") return;
  shell.ensureIframe?.(tab);
  tab.layout = "floating";
  tab.floatRect = shell.clampFloatRect?.(rect || shell.defaultFloatRectFromPointer?.(window.innerWidth / 2, window.innerHeight / 2));
  tab.floatZ = shell.state.nextFloatZ++;
  tab.floatMinimized = false;
  tab.floatAnimateIn = true;
  shell.state.activeId = tab.id;
  if (shell.state.lastDockedActiveId === tab.id) shell.state.lastDockedActiveId = shell.getFirstDockedTabId?.() || "home";
  shell.ensureActiveTabInvariant?.();
  shell.render?.();
  shell.saveState?.();
}

export function dockTab(id) {
  const tab = shell.state.tabs.find(t => t.id === id);
  if (!tab || tab.id === "home") return;
  tab.layout = "docked";
  tab.floatRect = null;
  tab.floatZ = 0;
  tab.floatMinimized = false;
  tab.floatRestoreRect = null;
  setDockedActive(tab.id);
  shell.render?.();
  shell.saveState?.();
}

export function closeTab(id, skipConfirm = false) {
  if (id === "home") return;
  const idx = shell.state.tabs.findIndex(t => t.id === id);
  if (idx < 0) return;
  const tab = shell.state.tabs[idx];
  if (!skipConfirm && tab.iframe?.contentWindow) {
    try {
      const requestClose = tab.iframe.contentWindow.__arcrho_request_close;
      if (typeof requestClose === "function" && requestClose() === true) return;
    } catch {}
  }
  if (!skipConfirm && tab.isDirty) {
    void confirmDiscardClose({ message: "Unsaved changes in this tab will be lost." })
      .then((confirmed) => { if (confirmed) closeTab(id, true); });
    return;
  }
  const wasActive = shell.state.activeId === id;
  cleanupDfmRatioHistory(tab);
  if (tab.iframe && tab.iframe.parentNode) tab.iframe.parentNode.removeChild(tab.iframe);
  shell.state.tabs.splice(idx, 1);
  if (wasActive) {
    const fallback = shell.state.tabs[Math.max(0, idx - 1)];
    shell.state.activeId = fallback ? fallback.id : "home";
  }
  if (shell.state.lastDockedActiveId === id) shell.state.lastDockedActiveId = shell.getFirstDockedTabId?.() || "home";
  shell.ensureActiveTabInvariant?.();
  shell.render?.();
  shell.saveState?.();
}

export function openDatasetTab(options = {}) {
  const requestedInputs = normalizeBrowsingHistoryEntry(options?.datasetInputs || null);
  const lastViewedInputs = getLastViewedDatasetInputs();
  const datasetInputs = requestedInputs || lastViewedInputs || null;
  const id = `ds_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: "Dataset View",
    type: "dataset",
    iframe: null,
    layout: "docked",
    dsInst: `ds_${id}_${Date.now()}`,
    datasetInputs: datasetInputs || undefined,
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

function cleanupDfmRatioHistory(tab) {
  if (!tab || tab.type !== "dfm") return;
  try {
    tab.iframe?.contentWindow?.postMessage({ type: "arcrho:dfm-tab-closing" }, "*");
  } catch {}
  const dir = String(tab.dfmRatioHistoryDir || "").trim();
  if (!dir) return;
  tab.dfmRatioHistoryDir = "";
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.clearDfmRatioUndoSession === "function") {
    Promise.resolve(hostApi.clearDfmRatioUndoSession({ dir })).catch(() => {});
  }
}

function normalizeDfmInitialInputs(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const project = String(source.project || source.projectName || source.project_name || "").trim();
  const reservingClass = String(
    source.reservingClass
    || source.reserving_class
    || source.path
    || source.class
    || "",
  ).trim();
  const methodName = String(source.methodName || source.method_name || source.name || "").trim();
  const outputType = String(source.outputType || source.output_type || source.outputVector || source.output_vector || "").trim();
  const outputDataset = String(source.outputDataset || source.output_dataset || "").trim();
  const inputTriangle = String(source.inputTriangle || source.input_triangle || source.datasetName || source.dataset_name || "").trim();
  const out = {};
  if (project) out.project = project;
  if (reservingClass) out.reservingClass = reservingClass;
  if (methodName) out.methodName = methodName;
  if (outputType) out.outputType = outputType;
  if (outputDataset) out.outputDataset = outputDataset;
  if (inputTriangle) out.inputTriangle = inputTriangle;
  return Object.keys(out).length ? out : null;
}

export function openDFMTab(options = {}) {
  const dfmInputs = normalizeDfmInitialInputs(options?.dfmInputs || options?.inputs || null);
  const requestedDfmTab = String(options?.dfmTab || "").trim().toLowerCase();
  const dfmTab = ALLOWED_DFM_TABS.has(requestedDfmTab) ? requestedDfmTab : "details";
  const id = `dfm_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: dfmInputs?.methodName || dfmInputs?.outputType || "DFM",
    type: "dfm",
    iframe: null,
    layout: "docked",
    dsInst: `dfm_${id}_${Date.now()}`,
    dfmTab,
    dfmInputs: dfmInputs || undefined,
    isDirty: false,
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

export function openBornhuetterFergusonTab() {
  const id = `bf_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: "Bornhuetter Ferguson",
    type: "bornhuetter_ferguson",
    iframe: null,
    layout: "docked",
    dsInst: `bf_${id}_${Date.now()}`,
    bfTab: "details",
    isDirty: false,
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

export function openCapeCodTab() {
  const id = `cc_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: "Cape Cod",
    type: "cape_cod",
    iframe: null,
    layout: "docked",
    dsInst: `cc_${id}_${Date.now()}`,
    ccTab: "details",
    isDirty: false,
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

export function openResultSelectionTab() {
  const id = `rs_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: "Result Selection",
    type: "result_selection",
    iframe: null,
    layout: "docked",
    dsInst: `rs_${id}_${Date.now()}`,
    rsTab: "details",
    isDirty: false,
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

export function openWorkflowTab() {
  const id = `wf_${shell.state.nextId++}`;
  const wfInst = `wf_${shell.state.nextId - 1}_${Date.now()}`;
  const tab = {
    id,
    title: `Workflow ${shell.state.nextId - 1}`,
    type: "workflow",
    iframe: null,
    layout: "docked",
    wfInst,
    isDirty: false,
  };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

export function openProjectSettingsTab() {
  const existing = shell.state.tabs.find(t => t.type === "project_settings");
  if (existing) {
    if (!existing.projectSettingsRibbon) existing.projectSettingsRibbon = "summary";
    setActive(existing.id);
    return;
  }
  const id = `ps_${shell.state.nextId++}`;
  shell.state.tabs.push({
    id,
    title: "Project Explorer",
    type: "project_settings",
    projectSettingsRibbon: "summary",
    iframe: null,
    layout: "docked",
  });
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
}

function postProjectInstanceRestoreState(tab) {
  const state = normalizeProjectInstanceState(tab?.projectInstanceState || null);
  const iframe = tab?.iframe;
  if (!state || !iframe?.contentWindow) return false;
  try {
    iframe.contentWindow.postMessage({ type: "arcrho:project-instance-restore-state", state }, "*");
    return true;
  } catch {
    return false;
  }
}

export function openProjectInstanceTab(project = {}, options = {}) {
  const projectName = String(project?.name || project?.projectName || "").trim();
  if (!projectName) return null;
  const existing = !options?.forceNew
    ? shell.state.tabs.find(t => t.type === "project_instance" && String(t.projectName || "").trim().toLowerCase() === projectName.toLowerCase())
    : null;
  if (existing) {
    const restoreState = normalizeProjectInstanceState(project?.projectInstanceState || options?.projectInstanceState || null);
    if (restoreState) {
      existing.projectInstanceState = restoreState;
      shell.ensureIframe?.(existing);
      postProjectInstanceRestoreState(existing);
      shell.saveState?.();
    }
    setActive(existing.id);
    return existing;
  }
  const id = `pi_${shell.state.nextId++}`;
  const tab = {
    id,
    title: projectName,
    type: "project_instance",
    projectName,
    projectFolder: String(project?.folder || "").trim(),
    projectTablePath: String(project?.tablePath || "").trim(),
    projectInstanceState: normalizeProjectInstanceState(project?.projectInstanceState || options?.projectInstanceState || null) || undefined,
    iframe: null,
    layout: "docked",
  };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

export function openShellActivityHistoryEntry(entry) {
  const normalized = normalizeShellActivityEntry(entry);
  if (!normalized) return null;
  if (normalized.tabType === "dataset") {
    openDatasetTab({ datasetInputs: normalized.datasetInputs });
    return null;
  }
  if (normalized.tabType === "dfm") {
    openDFMTab({ dfmInputs: normalized.dfmInputs, dfmTab: normalized.dfmTab });
    return null;
  }
  if (normalized.tabType === "project_settings") {
    const tab = openProjectSettingsTab();
    const active = shell.state.tabs.find(t => t.type === "project_settings");
    if (active) active.projectSettingsRibbon = normalized.projectSettingsRibbon || "summary";
    shell.render?.();
    shell.saveState?.();
    return tab || active || null;
  }
  if (normalized.tabType === "project_instance") {
    return openProjectInstanceTab({
      name: normalized.projectName,
      folder: normalized.projectFolder || "",
      tablePath: normalized.projectTablePath || "",
      projectInstanceState: normalized.projectInstanceState || null,
    });
  }
  if (normalized.tabType === "scripting") {
    return openScriptingTab({ forceNew: true, notebookPath: normalized.path || "" });
  }
  if (normalized.tabType === "workflow") return openWorkflowTab();
  if (normalized.tabType === "agent_guide") return openAgentGuideTab();
  if (normalized.tabType === "browsing_history") return openBrowsingHistoryTab();
  if (normalized.tabType === "file_explorer") return openFileExplorerTab({ path: normalized.path || "" });
  if (normalized.tabType === "server") return openServerTab();
  return null;
}

export function openBrowsingHistoryTab() {
  const existing = shell.state.tabs.find(t => t.type === "browsing_history");
  if (existing) {
    setActive(existing.id);
    return existing;
  }
  const id = `bh_${shell.state.nextId++}`;
  const tab = { id, title: "Browsing History", type: "browsing_history", iframe: null, layout: "docked" };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

// File Browser is multi-instance and folder-keyed: a request for a specific folder focuses the tab
// already showing that folder, and anything else opens a new instance. `forceNew` skips the match.
export function openFileExplorerTab(options = {}) {
  const path = String(options.path || "").trim();
  const folderKey = normalizeFolderKey(path);
  const existing = !options.forceNew && folderKey
    ? shell.state.tabs.find(t => t.type === "file_explorer" && normalizeFolderKey(t.fileExplorerPath) === folderKey)
    : null;
  if (existing) {
    setActive(existing.id);
    return existing;
  }
  const id = `fe_${shell.state.nextId++}`;
  const tab = {
    id,
    title: "File Browser",
    type: "file_explorer",
    fileExplorerPath: path,
    iframe: null,
    layout: "docked",
  };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

export function openAgentGuideTab() {
  const existing = shell.state.tabs.find(t => t.type === "agent_guide");
  if (existing) {
    setActive(existing.id);
    return existing;
  }
  const id = `ag_${shell.state.nextId++}`;
  const tab = {
    id,
    title: "ArcBot Prompt Guide",
    type: "agent_guide",
    iframe: null,
    layout: "docked",
  };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

// One Server Connections tab: it lists this PC's servers and switches between them.
export function openServerTab() {
  const existing = shell.state.tabs.find(t => t.type === "server");
  if (existing) {
    setActive(existing.id);
    return existing;
  }
  const id = `sv_${shell.state.nextId++}`;
  const tab = { id, title: "Server Connections", type: "server", iframe: null, layout: "docked" };
  shell.state.tabs.push(tab);
  setDockedActive(id);
  shell.render?.();
  shell.saveState?.();
  return tab;
}

export function openTaskDesigner(options = {}) {
  const existing = shell.state.tabs.find(t => t.type === TASK_DESIGNER_TYPE);
  const title = String(options?.title || "Task Designer").trim() || "Task Designer";
  const contextLabel = String(options?.contextLabel || options?.context || "Active DFM validation").trim();
  const macroId = String(options?.macroId || options?.macro_id || "").trim();
  const activeDfm = shell.state.tabs.find(t => (
    t.id === shell.state.activeId
    && (t.type === "dfm" || (t.type === "project_instance" && t.piDfmActive))
  ));
  const lastDockedDfm = shell.state.tabs.find(t => (
    t.id === shell.state.lastDockedActiveId
    && (t.type === "dfm" || (t.type === "project_instance" && t.piDfmActive))
  ));
  const contextTabId = String(options?.contextTabId || activeDfm?.id || lastDockedDfm?.id || "").trim();
  const sessionId = String(options?.sessionId || options?.session_id || "").trim();
  const taskDesignerOptions = {
    title,
    contextLabel,
    macroId,
    autoRun: !!options?.autoRun,
    contextTabId,
    sessionId,
    reset: options?.reset === true,
  };
  const tab = existing || {
    id: `td_${shell.state.nextId++}`,
    title,
    type: TASK_DESIGNER_TYPE,
    iframe: null,
  };
  tab.title = title;
  tab.taskDesignerOptions = taskDesignerOptions;
  tab.layout = "floating";
  tab.floatRect = shell.clampFloatRect?.(
    tab.floatRect || shell.defaultFloatRectFromPointer?.(window.innerWidth * 0.64, window.innerHeight * 0.42),
  );
  tab.floatZ = shell.state.nextFloatZ++;
  tab.floatMinimized = false;
  tab.floatAnimateIn = true;
  if (!existing) shell.state.tabs.push(tab);
  shell.state.activeId = tab.id;
  if (shell.state.lastDockedActiveId === tab.id) shell.state.lastDockedActiveId = shell.getFirstDockedTabId?.() || "home";
  shell.ensureIframe?.(tab);
  if (tab.iframe?.contentWindow) {
    try {
      tab.iframe.contentWindow.postMessage({
        type: "arcrho:task-designer-open",
        options: taskDesignerOptions,
      }, "*");
    } catch {}
  }
  shell.render?.();
  shell.saveState?.();
  return tab;
}

function getFilenameFromPath(pathLike) {
  const normalized = String(pathLike || "").replace(/\\/g, "/").trim();
  if (!normalized) return "";
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

export function openScriptingTab(options = {}) {
  const notebookPath = String(options?.notebookPath || options?.openPath || "").trim();
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.openArcodeWindow === "function") {
    Promise.resolve(hostApi.openArcodeWindow({ path: notebookPath }))
      .then((result) => {
        if (!result?.ok) {
          shell.updateStatusBar?.(String(result?.error || "Could not open Arcode."), { tone: "error" });
        } else {
          shell.updateStatusBar?.(notebookPath ? `Opening ${getFilenameFromPath(notebookPath)} in Arcode...` : "Opening Arcode...");
        }
      })
      .catch((err) => {
        shell.updateStatusBar?.(String(err?.message || err || "Could not open Arcode."), { tone: "error" });
      });
    return null;
  }
  const params = new URLSearchParams();
  params.set("v", String(Date.now()));
  if (notebookPath) params.set("path", notebookPath);
  const url = `/ui/arcode/main.html?${params.toString()}`;
  window.open(url, "_blank", "noopener");
  shell.updateStatusBar?.(notebookPath ? `Opening ${getFilenameFromPath(notebookPath)} in Arcode...` : "Opening Arcode...");
  return null;
}

function removeTabById(id) {
  if (id === "home") return;
  const idx = shell.state.tabs.findIndex(t => t.id === id);
  if (idx < 0) return;
  const tab = shell.state.tabs[idx];
  cleanupDfmRatioHistory(tab);
  if (tab.iframe && tab.iframe.parentNode) tab.iframe.parentNode.removeChild(tab.iframe);
  shell.state.tabs.splice(idx, 1);
}

export function closeTabsExcept(keepIds, skipConfirm = false) {
  const keep = new Set(keepIds || []);
  keep.add("home");
  const toRemove = shell.state.tabs.filter(t => !keep.has(t.id));
  const dirtyTabs = toRemove.filter(t => t.isDirty);
  if (!skipConfirm && dirtyTabs.length > 0) {
    const count = dirtyTabs.length;
    void confirmDiscardClose({ message: `Unsaved changes in ${count} ${count === 1 ? "tab" : "tabs"} will be lost.` })
      .then((confirmed) => { if (confirmed) closeTabsExcept(keepIds, true); });
    return;
  }
  toRemove.forEach(t => removeTabById(t.id));
  if (!keep.has(shell.state.activeId)) shell.state.activeId = keepIds && keepIds.length ? keepIds[0] : "home";
  shell.ensureActiveTabInvariant?.();
  shell.render?.();
  shell.saveState?.();
}
