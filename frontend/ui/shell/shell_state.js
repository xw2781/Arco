import { isFloatingTab, normalizeFloatRect } from "./floating_tabs.js?v=20260510a";
import { normalizeBrowsingHistoryEntry } from "/ui/shell/browsing_history.js";
import { normalizeProjectInstanceState } from "/ui/shell/shell_activity_history.js";

const STORAGE_KEY = "arcrho_ui_shell_state_v4";
const LEGACY_STORAGE_KEYS = ["arcrho_ui_shell_state_v3"];

export const state = {
  tabs: [{ id: "home", title: "Home", type: "home" }],
  activeId: "home",
  nextId: 1,
  lastDockedActiveId: "home",
  nextFloatZ: 1,
};

export function ensureHomeTabFirst(tabs = state.tabs) {
  if (!Array.isArray(tabs)) return;
  const homeIndex = tabs.findIndex(t => t?.id === "home");
  if (homeIndex < 0) {
    tabs.unshift({ id: "home", title: "Home", type: "home" });
    return;
  }
  if (homeIndex === 0) return;
  const [home] = tabs.splice(homeIndex, 1);
  tabs.unshift(home);
}

function getSavedShellStateRaw() {
  try {
    const current = localStorage.getItem(STORAGE_KEY);
    if (current) return current;
    for (const key of LEGACY_STORAGE_KEYS) {
      const raw = localStorage.getItem(key);
      if (raw) return raw;
    }
  } catch {
    // ignore
  }
  return "";
}

function normalizeDfmInitialInputs(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const project = String(source.project || source.projectName || source.project_name || "").trim();
  const reservingClass = String(source.reservingClass || source.reserving_class || source.path || source.class || "").trim();
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
  return Object.keys(out).length ? out : undefined;
}

export function getFirstDockedTabId() {
  const docked = state.tabs.find(t => t.id !== "home" && !isFloatingTab(t));
  return docked?.id || "home";
}

export function ensureActiveTabInvariant() {
  ensureHomeTabFirst();
  if (!state.tabs.some(t => t.id === state.activeId)) {
    state.activeId = "home";
  }
  const lastDocked = state.tabs.find(t => t.id === state.lastDockedActiveId && !isFloatingTab(t));
  if (!lastDocked) state.lastDockedActiveId = getFirstDockedTabId();
  const active = state.tabs.find(t => t.id === state.activeId);
  if (active && !isFloatingTab(active)) state.lastDockedActiveId = active.id;
}

export function loadState() {
  try {
    const raw = getSavedShellStateRaw();
    if (!raw) return;
    const s = JSON.parse(raw);
    if (!s || !Array.isArray(s.tabs) || !s.activeId) return;

    ensureHomeTabFirst(s.tabs);

    state.tabs = s.tabs.map(t => ({
      id: t.id,
      title: t.title,
      type: t.type,
      datasetId: t.datasetId,
      datasetInputs: normalizeBrowsingHistoryEntry(t.datasetInputs || null) || undefined,
      dfmInputs: t.type === "dfm" ? normalizeDfmInitialInputs(t.dfmInputs || null) : undefined,
      dsInst: t.dsInst || (
        t.type === "dataset" || t.type === "result_selection" || t.type === "bornhuetter_ferguson" || t.type === "cape_cod"
          ? `${t.type === "dataset" ? "ds" : t.type === "result_selection" ? "rs" : t.type === "cape_cod" ? "cc" : "bf"}_${t.id}`
          : undefined
      ),
      bfTab: t.type === "bornhuetter_ferguson" ? String(t.bfTab || "details") : undefined,
      ccTab: t.type === "cape_cod" ? String(t.ccTab || "details") : undefined,
      rsTab: t.type === "result_selection" ? String(t.rsTab || "details") : undefined,
      wfInst: t.wfInst,
      wfFresh: t.wfFresh,
      scInst: t.scInst || (t.type === "scripting" ? `sc_${t.id}` : undefined),
      scFresh: !!t.scFresh,
      scPath: t.type === "scripting" ? String(t.scPath || t.scOpenPath || "").trim() || undefined : undefined,
      scOpenPath: t.type === "scripting" ? String(t.scOpenPath || "").trim() || undefined : undefined,
      projectName: t.type === "project_instance" ? String(t.projectName || t.title || "").trim() : undefined,
      projectFolder: t.type === "project_instance" ? String(t.projectFolder || "").trim() : undefined,
      projectTablePath: t.type === "project_instance" ? String(t.projectTablePath || "").trim() : undefined,
      projectInstanceState: t.type === "project_instance" ? normalizeProjectInstanceState(t.projectInstanceState || null) || undefined : undefined,
      fileExplorerPath: t.type === "file_explorer" ? String(t.fileExplorerPath || "").trim() || undefined : undefined,
      dashboardPath: t.type === "dashboard" ? String(t.dashboardPath || "").trim() || undefined : undefined,
      projectSettingsRibbon: t.type === "project_settings"
        ? (String(t.projectSettingsRibbon || "").trim().toLowerCase() || "summary")
        : undefined,
      taskDesignerOptions: t.type === "task_designer" && t.taskDesignerOptions && typeof t.taskDesignerOptions === "object"
        ? {
          title: String(t.taskDesignerOptions.title || "Task Designer"),
          contextLabel: String(t.taskDesignerOptions.contextLabel || "Active DFM validation"),
          macroId: String(t.taskDesignerOptions.macroId || ""),
          autoRun: false,
          contextTabId: String(t.taskDesignerOptions.contextTabId || ""),
        }
        : undefined,
      layout: t.id === "home" ? "docked" : (t.layout === "floating" ? "floating" : "docked"),
      floatRect: normalizeFloatRect(t.floatRect),
      floatZ: Number.isFinite(Number(t.floatZ)) ? Number(t.floatZ) : 0,
      floatMinimized: t.layout === "floating" ? !!t.floatMinimized : false,
      isDirty: false,
      iframe: null,
    }));
    state.activeId = s.activeId;
    state.nextId = s.nextId || 1;
    state.lastDockedActiveId = String(s.lastDockedActiveId || "home");
    state.nextFloatZ = Number.isFinite(Number(s.nextFloatZ)) ? Number(s.nextFloatZ) : 1;

    for (const t of state.tabs) {
      if (t.id === "home") {
        t.type = "home";
        t.title = "Home";
        t.datasetId = undefined;
        t.layout = "docked";
        t.floatRect = null;
        t.floatZ = 0;
        t.floatMinimized = false;
      }
    }

    const maxId = Math.max(
      0,
      ...state.tabs.map(t => {
        const m = String(t.id).match(/_(\d+)$/);
        return m ? parseInt(m[1], 10) : 0;
      })
    );
    state.nextId = Math.max(state.nextId, maxId + 1);
    const maxZ = Math.max(0, ...state.tabs.map(t => Number(t.floatZ) || 0));
    state.nextFloatZ = Math.max(state.nextFloatZ, maxZ + 1);
    ensureActiveTabInvariant();
  } catch {
    // ignore
  }
}

export function buildShellStateSnapshot() {
  ensureHomeTabFirst();
  return {
    tabs: state.tabs.map(t => ({
      id: t.id,
      title: t.title,
      type: t.type,
      datasetId: t.datasetId,
      datasetInputs: t.datasetInputs || undefined,
      dfmInputs: t.type === "dfm" ? normalizeDfmInitialInputs(t.dfmInputs || null) : undefined,
      dsInst: t.dsInst,
      bfTab: t.type === "bornhuetter_ferguson" ? String(t.bfTab || "details") : undefined,
      ccTab: t.type === "cape_cod" ? String(t.ccTab || "details") : undefined,
      rsTab: t.type === "result_selection" ? String(t.rsTab || "details") : undefined,
      wfInst: t.wfInst,
      wfFresh: t.wfFresh,
      scInst: t.scInst,
      scFresh: t.scFresh,
      scPath: t.type === "scripting" ? String(t.scPath || t.scOpenPath || "").trim() || undefined : undefined,
      scOpenPath: t.type === "scripting" ? String(t.scOpenPath || "").trim() || undefined : undefined,
      projectName: t.type === "project_instance" ? String(t.projectName || t.title || "").trim() : undefined,
      projectFolder: t.type === "project_instance" ? String(t.projectFolder || "").trim() : undefined,
      projectTablePath: t.type === "project_instance" ? String(t.projectTablePath || "").trim() : undefined,
      projectInstanceState: t.type === "project_instance" ? normalizeProjectInstanceState(t.projectInstanceState || null) || undefined : undefined,
      fileExplorerPath: t.type === "file_explorer" ? String(t.fileExplorerPath || "").trim() || undefined : undefined,
      dashboardPath: t.type === "dashboard" ? String(t.dashboardPath || "").trim() || undefined : undefined,
      projectSettingsRibbon: t.type === "project_settings"
        ? String(t.projectSettingsRibbon || "").trim().toLowerCase()
        : undefined,
      taskDesignerOptions: t.type === "task_designer" && t.taskDesignerOptions && typeof t.taskDesignerOptions === "object"
        ? {
          title: String(t.taskDesignerOptions.title || "Task Designer"),
          contextLabel: String(t.taskDesignerOptions.contextLabel || "Active DFM validation"),
          macroId: String(t.taskDesignerOptions.macroId || ""),
          autoRun: false,
          contextTabId: String(t.taskDesignerOptions.contextTabId || ""),
        }
        : undefined,
      layout: isFloatingTab(t) ? "floating" : "docked",
      floatRect: isFloatingTab(t) ? t.floatRect : undefined,
      floatZ: isFloatingTab(t) ? t.floatZ : undefined,
      floatMinimized: isFloatingTab(t) ? !!t.floatMinimized : undefined,
    })),
    activeId: state.activeId,
    nextId: state.nextId,
    lastDockedActiveId: state.lastDockedActiveId,
    nextFloatZ: state.nextFloatZ,
  };
}

export function persistShellStateSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || !Array.isArray(snapshot.tabs) || !snapshot.activeId) {
    return false;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot));
    return true;
  } catch {
    return false;
  }
}

export function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(buildShellStateSnapshot()));
  } catch {
    // ignore quota / privacy errors
  }
}
