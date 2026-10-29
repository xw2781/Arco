import { getHostApi, registerShellApi } from "/ui/arcode/shared/host_context.js?v=20260614a";
import {
  initAiAssistant,
  isAiAssistantLauncherVisible,
  toggleAiAssistantLauncherVisible,
} from "/ui/ai-assistant/arcode.js?v=20260927smb24";
import { createFileIconResolver } from "/ui/shared/file-icons/fileIconResolver.js?v=20260722a";
import { closeAllCascadeSubmenus, initCascadeMenus } from "/ui/shared/components/cascade_menu/cascade_menu.js?v=20260817a";
import { createDatabaseConnectionsDialog } from "/ui/arcode/database-connections/dialog.js?v=20260818a";
import { confirmDiscardClose } from "/ui/shared/components/close_confirm/close_confirm.js";

const UI_VERSION_PARAM = new URLSearchParams(window.location.search).get("v") || String(Date.now());
const initialOpenPath = new URLSearchParams(window.location.search).get("path") || "";
// A window opened with "New Arcode Window" starts empty and leaves the saved tab list alone.
const initialFreshWindow = new URLSearchParams(window.location.search).get("fresh") === "1";
const MAX_SAVED_TABS = 30;
const OPEN_TABS_SAVE_DELAY_MS = 400;
// A DFM's "Open DFM JSON" names its method: the tab loads it through the
// hosted DFM load and is read only (see code-editor/index.js).
const initialProjectJsonParam = new URLSearchParams(window.location.search).get("projectJson") || "";
const initialDfmMethodParam = new URLSearchParams(window.location.search).get("dfm") || "";
const RECENT_KEY = "arcode_recent_files_v1";
const WORKSPACE_FOLDERS_KEY = "arcode_workspace_folders_v1";
const ACTIVE_WORKSPACE_FOLDER_KEY = "arcode_active_workspace_folder_v1";
const EXPANDED_EXPLORER_PATHS_KEY = "arcode_expanded_explorer_paths_v1";
const ZOOM_STORAGE_KEY = "arcode_ui_zoom_pct";
const ZOOM_MODE_KEY = "arcode_zoom_mode";
const STATUSBAR_H_KEY = "arcode_statusbar_h";
const EXPLORER_WIDTH_KEY = "arcode_explorer_sidebar_width_v1";
const CLEAR_CACHE_RESTORE_KIND = "arcode-clear-cache-reload-restore-v1";
const DEFAULT_ZOOM_PERCENT = 100;
const MIN_ZOOM_PERCENT = 70;
const MAX_ZOOM_PERCENT = 160;
const ZOOM_STEP = 10;
const DEFAULT_EXPLORER_WIDTH = 286;
const MIN_EXPLORER_WIDTH = 210;
const MAX_EXPLORER_WIDTH = 520;
const EXPLORER_RESIZE_STEP = 16;
const EXPLORER_REFRESH_DEBOUNCE_MS = 220;
const NOTEBOOK_FILE_EXTENSIONS = new Set([".ipynb", ".arcnb"]);
const CODE_FILE_EXTENSIONS = new Set([".py", ".r", ".sql", ".js", ".ts", ".json", ".md", ".txt", ".css", ".html", ".htm"]);
const DROP_FILE_EXTENSIONS = new Set([...NOTEBOOK_FILE_EXTENSIONS, ...CODE_FILE_EXTENSIONS]);
const TAB_DRAG_THRESHOLD_PX = 6;
const EMPTY_NOTEBOOK_TEMPLATE = {
  cells: [],
  metadata: {
    kernelspec: {
      display_name: "Python 3",
      language: "python",
      name: "python3",
    },
    language_info: {
      name: "python",
      pygments_lexer: "ipython3",
    },
  },
  nbformat: 4,
  nbformat_minor: 5,
};
const HOME_CREATE_ITEMS = [
  { kind: "python", title: "Python File", extension: ".py", icon: "/ui/arcode/shared/launch-card-icons/jupyterlab-python.svg" },
  { kind: "notebook", title: "Notebook", extension: ".ipynb", icon: "/ui/arcode/shared/launch-card-icons/jupyter.png" },
  { kind: "text", title: "Text File", extension: ".txt", icon: "/ui/arcode/shared/launch-card-icons/jupyterlab-text-editor.svg" },
  { kind: "markdown", title: "Markdown File", extension: ".md", icon: "/ui/arcode/shared/launch-card-icons/jupyterlab-markdown.svg" },
  { kind: "sqlserver", title: "SQL Server", extension: ".sql", icon: "/ui/arcode/shared/launch-card-icons/sql-server.png" },
  { kind: "snowflake", title: "Snowflake", extension: ".sql", icon: "/ui/arcode/shared/launch-card-icons/snowflake.png" },
  { kind: "terminal", title: "Terminal", extension: "", icon: "/ui/arcode/shared/launch-card-icons/jupyterlab-terminal.svg" },
];
const HOME_CREATE_GROUPS = [
  { title: "Scripting", icon: "notebook", kinds: ["python", "notebook"] },
  { title: "Data & Query", icon: "database", kinds: ["sqlserver", "snowflake"] },
  { title: "Other", icon: "terminal", kinds: ["terminal", "text", "markdown"] },
];
const FILE_ICON_BASE_PATH = "/ui/shared/file-icons/";
const FILE_ICON_MAP_URL = `${FILE_ICON_BASE_PATH}file-icon-map.json?v=20260722a`;
let resolveFileIconPath = null;

const state = {
  tabs: [],
  activeId: "home",
  nextId: 1,
  zoomPercent: DEFAULT_ZOOM_PERCENT,
  recentFiles: [],
  workspaceFolders: readWorkspaceFolders(),
  activeWorkspaceFolder: readActiveWorkspaceFolder(),
  expandedExplorerPaths: readExpandedExplorerPaths(),
  folderListings: {},
  explorerWidth: readExplorerWidth(),
  savedOpenTabs: [],
  savedActiveTabPath: "",
  // Open tabs are written only once the saved ones are back, so start-up cannot overwrite them.
  openTabsPersistReady: false,
};

let openTabsSaveTimer = 0;
let lastSavedOpenTabsKey = "";

const explorerFolderWatchers = new Map();
let explorerRefreshTimer = 0;
const pendingExplorerRefreshRoots = new Set();
let explorerResizeState = null;

if (!state.expandedExplorerPaths && state.workspaceFolders.length) {
  state.expandedExplorerPaths = [state.activeWorkspaceFolder || state.workspaceFolders[0]];
} else if (!state.expandedExplorerPaths) {
  state.expandedExplorerPaths = [];
}

const $ = (id) => document.getElementById(id);

function filenameFromPath(pathLike) {
  const normalized = String(pathLike || "").replace(/\\/g, "/").trim();
  if (!normalized) return "";
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : "";
}

function joinPath(folderPath, fileName) {
  const folder = String(folderPath || "").trim();
  const name = String(fileName || "").trim();
  if (!folder) return name;
  const separator = folder.includes("\\") ? "\\" : "/";
  return `${folder.replace(/[\\/]+$/, "")}${separator}${name.replace(/^[\\/]+/, "")}`;
}

function timestampForFileName() {
  const value = new Date().toISOString().replace(/[-:]/g, "").replace(/\..+$/, "");
  return value.replace("T", "_");
}

function normalizeRecentFiles(value) {
  const entries = Array.isArray(value) ? value : [];
  const seen = new Set();
  const files = [];
  for (const item of entries) {
    const filePath = String(item || "").trim();
    if (!filePath) continue;
    const key = filePath.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    files.push(filePath);
    if (files.length >= 20) break;
  }
  return files;
}

function normalizeWorkspaceFolders(value) {
  const entries = Array.isArray(value) ? value : [];
  const seen = new Set();
  const folders = [];
  for (const item of entries) {
    const folderPath = String(item || "").trim();
    if (!folderPath) continue;
    const key = folderPath.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    folders.push(folderPath);
    if (folders.length >= 20) break;
  }
  return folders;
}

function normalizeZoomPercent(value, fallback = DEFAULT_ZOOM_PERCENT) {
  const numeric = Math.round(Number(value));
  const safeFallback = Number.isFinite(Number(fallback)) ? Math.round(Number(fallback)) : DEFAULT_ZOOM_PERCENT;
  if (!Number.isFinite(numeric)) return Math.max(MIN_ZOOM_PERCENT, Math.min(MAX_ZOOM_PERCENT, safeFallback));
  return Math.max(MIN_ZOOM_PERCENT, Math.min(MAX_ZOOM_PERCENT, numeric));
}

function normalizeExplorerWidth(value, fallback = DEFAULT_EXPLORER_WIDTH) {
  const numeric = Math.round(Number(value));
  const safeFallback = Number.isFinite(Number(fallback)) ? Math.round(Number(fallback)) : DEFAULT_EXPLORER_WIDTH;
  if (!Number.isFinite(numeric)) {
    return Math.max(MIN_EXPLORER_WIDTH, Math.min(MAX_EXPLORER_WIDTH, safeFallback));
  }
  return Math.max(MIN_EXPLORER_WIDTH, Math.min(MAX_EXPLORER_WIDTH, numeric));
}

function readExplorerWidth() {
  try {
    return normalizeExplorerWidth(localStorage.getItem(EXPLORER_WIDTH_KEY));
  } catch {
    return DEFAULT_EXPLORER_WIDTH;
  }
}

function readRecentFilesFallback() {
  try {
    const parsed = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return normalizeRecentFiles(parsed);
  } catch {
    return [];
  }
}

function readRecentFiles() {
  return normalizeRecentFiles(state.recentFiles);
}

function currentOpenTabsSetting() {
  const tabs = state.tabs
    .filter((tab) => String(tab.path || "").trim() && !tab.dfmMethod)
    .slice(0, MAX_SAVED_TABS)
    .map((tab) => ({ path: String(tab.path).trim() }));
  const active = state.tabs.find((tab) => tab.id === state.activeId);
  return { openTabs: tabs, activeTabPath: String(active?.path || "").trim() };
}

function currentUserSettingsPayload() {
  const workspaceFolders = normalizeWorkspaceFolders(state.workspaceFolders);
  const activeWorkspaceFolder = String(state.activeWorkspaceFolder || workspaceFolders[0] || "").trim();
  const payload = {
    recentFiles: readRecentFiles(),
    workspaceFolders,
    activeWorkspaceFolder,
    lastWorkspaceFolderPath: activeWorkspaceFolder,
    windowScalePercent: normalizeZoomPercent(state.zoomPercent),
    explorerSidebarWidth: normalizeExplorerWidth(state.explorerWidth),
  };
  if (state.openTabsPersistReady) {
    const openTabsSetting = currentOpenTabsSetting();
    Object.assign(payload, openTabsSetting);
    lastSavedOpenTabsKey = JSON.stringify(openTabsSetting);
  }
  return payload;
}

// Saves the tab list a moment after it changes, so opening or dragging tabs writes once.
function scheduleOpenTabsSave() {
  if (!state.openTabsPersistReady) return;
  window.clearTimeout(openTabsSaveTimer);
  openTabsSaveTimer = window.setTimeout(() => {
    if (JSON.stringify(currentOpenTabsSetting()) === lastSavedOpenTabsKey) return;
    void saveArcodeUserSettings();
  }, OPEN_TABS_SAVE_DELAY_MS);
}

function restoreSavedOpenTabs() {
  const entries = state.savedOpenTabs.slice(0, MAX_SAVED_TABS);
  const opened = entries.map((entry) => openCodeTab({ path: entry.path, restoring: true }));
  const activePath = state.savedActiveTabPath.toLowerCase();
  const active = activePath ? opened.find((tab) => String(tab.path || "").toLowerCase() === activePath) : null;
  setActiveTab(active ? active.id : "home");
  if (opened.length) updateStatus(`Restored ${opened.length === 1 ? "1 tab" : `${opened.length} tabs`}.`);
  return opened.length > 0;
}

function buildClearCacheReloadRestorePayload() {
  const activeIndex = state.tabs.findIndex((tab) => tab.id === state.activeId);
  return {
    kind: CLEAR_CACHE_RESTORE_KIND,
    createdAt: Date.now(),
    activeIndex,
    activeWasHome: state.activeId === "home",
    tabs: state.tabs.map((tab) => ({
      title: tabTitle(tab),
      path: String(tab.path || "").trim(),
      forceFresh: !String(tab.path || "").trim() || !!tab.forceFresh,
      ...(tab.dfmMethod ? { dfmMethod: tab.dfmMethod } : {}),
      ...(tab.projectJson ? { projectJson: tab.projectJson } : {}),
    })),
  };
}

function normalizeRestoreTabs(value) {
  const entries = Array.isArray(value) ? value : [];
  return entries.slice(0, 30).map((entry) => {
    const path = String(entry?.path || "").trim();
    const title = String(entry?.title || "").trim();
    return {
      path,
      title: title || filenameFromPath(path) || "Untitled Notebook",
      forceFresh: !path || !!entry?.forceFresh,
      dfmMethod: entry?.dfmMethod || null,
      projectJson: entry?.projectJson || null,
    };
  });
}

async function restoreTabsAfterClearCacheReload() {
  const host = getHostApi();
  if (typeof host?.consumeClearCacheReloadRestore !== "function") return false;
  let payload = null;
  try {
    payload = await host.consumeClearCacheReloadRestore();
  } catch {
    return false;
  }
  if (payload?.kind !== CLEAR_CACHE_RESTORE_KIND) return false;
  const restoreTabs = normalizeRestoreTabs(payload.tabs);
  const openedTabs = [];
  for (const tab of restoreTabs) {
    openedTabs.push(openCodeTab({
      path: tab.path,
      title: tab.title,
      forceFresh: tab.forceFresh,
      dfmMethod: tab.dfmMethod,
      projectJson: tab.projectJson,
    }));
  }
  if (payload.activeWasHome || !openedTabs.length) {
    setActiveTab("home");
  } else {
    const activeIndex = Number.parseInt(String(payload.activeIndex ?? -1), 10);
    const activeTab = openedTabs[Math.max(0, Math.min(openedTabs.length - 1, activeIndex))] || openedTabs[0];
    if (activeTab) setActiveTab(activeTab.id);
  }
  updateStatus(openedTabs.length
    ? `Restored ${openedTabs.length === 1 ? "1 tab" : `${openedTabs.length} tabs`} after reload.`
    : "Reloaded Arcode.");
  return true;
}

async function saveArcodeUserSettings({ reportFailure = false } = {}) {
  const host = getHostApi();
  const payload = currentUserSettingsPayload();
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(payload.recentFiles));
    localStorage.setItem(WORKSPACE_FOLDERS_KEY, JSON.stringify(payload.workspaceFolders));
    localStorage.setItem(ACTIVE_WORKSPACE_FOLDER_KEY, payload.activeWorkspaceFolder || "");
  } catch {
    // Browser fallback only.
  }
  if (typeof host?.saveArcodeUserSettings !== "function") return { ok: true, fallback: true };
  try {
    const result = await host.saveArcodeUserSettings(payload);
    if (result?.ok) return result;
    if (reportFailure) updateStatus(`Unable to save Arcode settings: ${result?.error || "Unknown error"}`);
    return { ok: false, error: result?.error || "Unknown error" };
  } catch (err) {
    const error = String(err?.message || err);
    if (reportFailure) updateStatus(`Unable to save Arcode settings: ${error}`);
    return { ok: false, error };
  }
}

function normalizeLoadedArcodeSettings(result) {
  if (result?.settings && typeof result.settings === "object" && !Array.isArray(result.settings)) {
    return result.settings;
  }
  if (result && typeof result === "object" && !Array.isArray(result) && result.ok !== false) {
    return result;
  }
  return {};
}

async function loadArcodeUserSettings() {
  const host = getHostApi();
  if (typeof host?.loadArcodeUserSettings === "function") {
    try {
      const result = await host.loadArcodeUserSettings();
      const settings = normalizeLoadedArcodeSettings(result);
      const recentFiles = normalizeRecentFiles(settings.recentFiles);
      const settingsFolders = normalizeWorkspaceFolders(settings.workspaceFolders);
      const fallbackFolders = readWorkspaceFolders();
      const workspaceFolders = settingsFolders.length ? settingsFolders : fallbackFolders;
      const activeWorkspaceFolder = String(
        settings.activeWorkspaceFolder
        || settings.lastWorkspaceFolderPath
        || readActiveWorkspaceFolder()
        || workspaceFolders[0]
        || "",
      ).trim();
      state.recentFiles = recentFiles.length ? recentFiles : readRecentFilesFallback();
      state.workspaceFolders = workspaceFolders;
      state.activeWorkspaceFolder = activeWorkspaceFolder;
      if (activeWorkspaceFolder && !state.workspaceFolders.some((item) => item.toLowerCase() === activeWorkspaceFolder.toLowerCase())) {
        state.workspaceFolders = [activeWorkspaceFolder, ...state.workspaceFolders].slice(0, 20);
      }
      state.zoomPercent = normalizeZoomPercent(settings.windowScalePercent, DEFAULT_ZOOM_PERCENT);
      state.savedOpenTabs = (Array.isArray(settings.openTabs) ? settings.openTabs : [])
        .map((entry) => ({ path: String(entry?.path || "").trim() }))
        .filter((entry) => entry.path);
      state.savedActiveTabPath = String(settings.activeTabPath || "").trim();
      state.explorerWidth = normalizeExplorerWidth(settings.explorerSidebarWidth, readExplorerWidth());
      persistExplorerWidth(state.explorerWidth);
      saveWorkspaceFolders({ persistSettings: false });
      if (activeWorkspaceFolder && !isExplorerPathExpanded(activeWorkspaceFolder)) {
        setExplorerPathExpanded(activeWorkspaceFolder, true, { rerender: false });
      }
      const needsSettingsBackfill = !Object.prototype.hasOwnProperty.call(settings, "recentFiles")
        || !Object.prototype.hasOwnProperty.call(settings, "workspaceFolders")
        || !Object.prototype.hasOwnProperty.call(settings, "activeWorkspaceFolder")
        || !Object.prototype.hasOwnProperty.call(settings, "lastWorkspaceFolderPath")
        || !Object.prototype.hasOwnProperty.call(settings, "explorerSidebarWidth");
      if (needsSettingsBackfill) await saveArcodeUserSettings();
      return;
    } catch (err) {
      updateStatus(`Unable to load Arcode settings: ${String(err?.message || err)}`);
    }
  }
  state.recentFiles = readRecentFilesFallback();
  state.workspaceFolders = readWorkspaceFolders();
  state.activeWorkspaceFolder = readActiveWorkspaceFolder() || state.workspaceFolders[0] || "";
  state.zoomPercent = DEFAULT_ZOOM_PERCENT;
}

function saveRecentFile(pathLike) {
  const filePath = String(pathLike || "").trim();
  if (!filePath) return;
  const lower = filePath.toLowerCase();
  state.recentFiles = [filePath, ...readRecentFiles().filter((item) => item.toLowerCase() !== lower)].slice(0, 20);
  renderRecentFilesMenu();
  void saveArcodeUserSettings();
}

function readWorkspaceFolders() {
  try {
    const parsed = JSON.parse(localStorage.getItem(WORKSPACE_FOLDERS_KEY) || sessionStorage.getItem(WORKSPACE_FOLDERS_KEY) || "[]");
    return normalizeWorkspaceFolders(parsed);
  } catch {
    return [];
  }
}

function readActiveWorkspaceFolder() {
  try {
    return String(localStorage.getItem(ACTIVE_WORKSPACE_FOLDER_KEY) || sessionStorage.getItem(ACTIVE_WORKSPACE_FOLDER_KEY) || "").trim();
  } catch {
    return "";
  }
}

function persistExplorerWidth(width) {
  try {
    localStorage.setItem(EXPLORER_WIDTH_KEY, String(normalizeExplorerWidth(width)));
  } catch {
    // Browser fallback only.
  }
}

function applyExplorerWidth(width, { persist = true } = {}) {
  state.explorerWidth = normalizeExplorerWidth(width);
  document.querySelectorAll(".arcodeWorkspaceLayout, .arcodeFrameWorkspace").forEach((layout) => {
    layout.style.setProperty("--arcode-explorer-width", `${state.explorerWidth}px`);
  });
  document.querySelectorAll("#arcodeExplorerResizer").forEach((resizer) => {
    resizer.setAttribute("aria-valuenow", String(state.explorerWidth));
  });
  if (persist) {
    persistExplorerWidth(state.explorerWidth);
    void saveArcodeUserSettings();
  }
}

function normalizeExplorerPaths(value) {
  const entries = Array.isArray(value) ? value : [];
  const seen = new Set();
  const paths = [];
  for (const item of entries) {
    const pathLike = String(item || "").trim();
    if (!pathLike) continue;
    const key = pathLike.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    paths.push(pathLike);
  }
  return paths;
}

function readExpandedExplorerPaths() {
  try {
    const raw = sessionStorage.getItem(EXPANDED_EXPLORER_PATHS_KEY);
    if (raw == null) return null;
    return normalizeExplorerPaths(JSON.parse(raw || "[]"));
  } catch {
    return [];
  }
}

function saveWorkspaceFolders({ persistSettings = true } = {}) {
  const workspaceFolders = normalizeWorkspaceFolders(state.workspaceFolders);
  const activeWorkspaceFolder = String(state.activeWorkspaceFolder || workspaceFolders[0] || "").trim();
  state.workspaceFolders = workspaceFolders;
  state.activeWorkspaceFolder = activeWorkspaceFolder;
  try {
    sessionStorage.setItem(WORKSPACE_FOLDERS_KEY, JSON.stringify(workspaceFolders));
    sessionStorage.setItem(ACTIVE_WORKSPACE_FOLDER_KEY, activeWorkspaceFolder);
    localStorage.setItem(WORKSPACE_FOLDERS_KEY, JSON.stringify(workspaceFolders));
    localStorage.setItem(ACTIVE_WORKSPACE_FOLDER_KEY, activeWorkspaceFolder);
  } catch {
    // Browser fallback only.
  }
  syncExplorerFolderWatchers();
  if (persistSettings) void saveArcodeUserSettings();
}

function saveExpandedExplorerPaths() {
  try {
    sessionStorage.setItem(EXPANDED_EXPLORER_PATHS_KEY, JSON.stringify(normalizeExplorerPaths(state.expandedExplorerPaths)));
  } catch {
    // Explorer expansion is scoped to this window and best-effort.
  }
}

function isExplorerPathExpanded(pathLike) {
  const pathKey = String(pathLike || "").trim().toLowerCase();
  if (!pathKey) return false;
  return normalizeExplorerPaths(state.expandedExplorerPaths).some((item) => item.toLowerCase() === pathKey);
}

function setExplorerPathExpanded(pathLike, expanded, { rerender = true } = {}) {
  const folderPath = String(pathLike || "").trim();
  if (!folderPath) return;
  const folderKey = folderPath.toLowerCase();
  const existing = normalizeExplorerPaths(state.expandedExplorerPaths)
    .filter((item) => item.toLowerCase() !== folderKey);
  state.expandedExplorerPaths = expanded ? [folderPath, ...existing] : existing;
  saveExpandedExplorerPaths();
  syncExplorerFolderWatchers();
  if (rerender) render();
}

function addWorkspaceFolder(pathLike, { replace = false } = {}) {
  const folderPath = String(pathLike || "").trim();
  if (!folderPath) return;
  const lower = folderPath.toLowerCase();
  const existing = replace ? [] : state.workspaceFolders.filter((item) => item.toLowerCase() !== lower);
  state.workspaceFolders = [folderPath, ...existing];
  state.activeWorkspaceFolder = folderPath;
  setExplorerPathExpanded(folderPath, true, { rerender: false });
  saveWorkspaceFolders();
  render();
  updateStatus(replace ? `Selected workspace folder ${folderPath}.` : `Added workspace folder ${folderPath}.`);
}

function removeWorkspaceFolder(pathLike) {
  const folderPath = String(pathLike || "").trim();
  if (!folderPath) return;
  const folderKey = explorerPathKey(folderPath);
  const current = normalizeWorkspaceFolders(state.workspaceFolders);
  const remaining = current.filter((item) => explorerPathKey(item) !== folderKey);
  if (remaining.length === current.length) return;
  state.workspaceFolders = remaining;
  if (explorerPathKey(state.activeWorkspaceFolder) === folderKey) {
    state.activeWorkspaceFolder = remaining[0] || "";
  }
  state.expandedExplorerPaths = normalizeExplorerPaths(state.expandedExplorerPaths)
    .filter((item) => !explorerPathWithin(folderPath, item));
  Object.keys(state.folderListings).forEach((listedPath) => {
    if (explorerPathWithin(folderPath, listedPath)) delete state.folderListings[listedPath];
  });
  saveExpandedExplorerPaths();
  saveWorkspaceFolders();
  render();
  updateStatus(`Removed workspace folder ${folderPath}.`);
}

async function pickWorkspaceFolder({ replace = false } = {}) {
  const host = getHostApi();
  if (typeof host?.pickFolder !== "function") {
    updateStatus("Folder selection requires the desktop app host.");
    return;
  }
  const folderPath = await host.pickFolder(state.activeWorkspaceFolder || "");
  if (folderPath) addWorkspaceFolder(folderPath, { replace });
}

function isSupportedCodeFile(pathLike) {
  return DROP_FILE_EXTENSIONS.has(getPathExtension(pathLike));
}

function isNotebookPath(pathLike) {
  return NOTEBOOK_FILE_EXTENSIONS.has(getPathExtension(pathLike));
}

function isCodeEditorPath(pathLike) {
  return CODE_FILE_EXTENSIONS.has(getPathExtension(pathLike));
}

function inferTabType(pathLike, fallback = "notebook") {
  const filePath = String(pathLike || "").trim();
  if (!filePath) return fallback;
  if (isSnowflakeSqlPath(filePath)) return "snowflake";
  if (isSqlServerSqlPath(filePath)) return "sqlserver";
  if (isNotebookPath(filePath)) return "notebook";
  if (isCodeEditorPath(filePath)) return "editor";
  return fallback;
}

async function loadExplorerFileIcons() {
  try {
    const response = await fetch(FILE_ICON_MAP_URL, { cache: "force-cache" });
    if (!response.ok) throw new Error(`Icon map request failed: ${response.status}`);
    resolveFileIconPath = createFileIconResolver(await response.json());
  } catch (err) {
    console.warn("Arcode explorer file icon map could not load.", err);
    resolveFileIconPath = null;
  }
}

function getFallbackExplorerIconPath(pathLike, options = {}) {
  if (options.isDirectory) return "icons/folder-base.svg";
  const name = filenameFromPath(pathLike).toLowerCase();
  if (name === "package.json" || name === "package-lock.json") return "icons/npm.svg";
  if (name === "readme.md" || name === "readme") return "icons/readme.svg";
  if (name === ".gitignore") return "icons/git.svg";
  const extension = getPathExtension(pathLike);
  if (extension === ".py") return "icons/python.svg";
  if (extension === ".ipynb") return "icons/jupyter.svg";
  if (extension === ".html" || extension === ".htm") return "icons/html.svg";
  if (extension === ".js" || extension === ".mjs" || extension === ".cjs") return "icons/javascript.svg";
  if (extension === ".json" || extension === ".jsonc") return "icons/json.svg";
  if (extension === ".css") return "icons/css.svg";
  if (extension === ".md") return "icons/markdown.svg";
  if (extension === ".sql") return "icons/database.svg";
  return "icons/document.svg";
}

function getExplorerIconAssetPath(pathLike, options = {}) {
  const relativePath = (typeof resolveFileIconPath === "function"
    ? resolveFileIconPath(pathLike, options)
    : "") || getFallbackExplorerIconPath(pathLike, options);
  return `${FILE_ICON_BASE_PATH}${String(relativePath).replace(/^\/+/, "")}`;
}

function getExplorerIconImg(pathLike, options = {}) {
  const src = getExplorerIconAssetPath(pathLike, options);
  return `<img src="${escapeHtml(src)}" alt="" aria-hidden="true" draggable="false">`;
}

function getExplorerIconSvg(kind) {
  if (kind === "chevron") {
    return [
      '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">',
      '<path d="M6 4l4 4-4 4"></path>',
      "</svg>",
    ].join("");
  }
  return "";
}

function explorerDepthAttr(depth) {
  const safeDepth = Math.max(0, Math.min(12, Number(depth) || 0));
  return ` style="--explorer-depth:${safeDepth}"`;
}

function renderExplorerRow({ path, name, kind, depth, supported = false, active = false }) {
  const isFolder = kind === "folder" || kind === "root-folder";
  const expanded = isFolder && isExplorerPathExpanded(path);
  const classes = [
    "arcodeExplorerEntry",
    isFolder ? "folder" : "file",
    kind === "root-folder" ? "root" : "",
    expanded ? "expanded" : "",
    supported ? "supported" : "",
    active ? "active" : "",
  ].filter(Boolean).join(" ");
  return `
    <button class="${classes}" type="button" data-path="${encodeURIComponent(path)}" data-kind="${kind}" role="treeitem"${isFolder ? ` aria-expanded="${expanded ? "true" : "false"}"` : ""} title="${escapeHtml(path)}"${explorerDepthAttr(depth)}>
      <span class="arcodeExplorerTwistie${isFolder ? "" : " placeholder"}" aria-hidden="true">${isFolder ? getExplorerIconSvg("chevron") : ""}</span>
      <span class="arcodeExplorerFileIcon" aria-hidden="true">${getExplorerIconImg(path, { isDirectory: isFolder, isOpen: expanded })}</span>
      <span class="arcodeExplorerEntryName">${escapeHtml(name || filenameFromPath(path) || path)}</span>
    </button>
  `;
}

async function loadWorkspaceFolder(folderPath) {
  const path = String(folderPath || "").trim();
  if (!path || state.folderListings[path]?.loading) return;
  const host = getHostApi();
  if (typeof host?.listFolder !== "function") {
    state.folderListings[path] = { ok: false, error: "Folder listing requires the desktop app host.", entries: [] };
    render();
    return;
  }
  state.folderListings[path] = { loading: true, entries: [] };
  render();
  try {
    const result = await host.listFolder({ path, limit: 200 });
    state.folderListings[path] = {
      ok: !!result?.ok,
      error: result?.ok ? "" : String(result?.error || "Could not list folder."),
      entries: Array.isArray(result?.entries) ? result.entries : [],
    };
  } catch (err) {
    state.folderListings[path] = { ok: false, error: String(err?.message || err || "Could not list folder."), entries: [] };
  }
  render();
}

function renderExplorerChildren(folderPath, depth = 1) {
  if (!isExplorerPathExpanded(folderPath)) return "";
  const listing = state.folderListings[folderPath];
  if (!listing) {
    void loadWorkspaceFolder(folderPath);
    return `<div class="arcodeExplorerLoading"${explorerDepthAttr(depth)}>Loading...</div>`;
  }
  if (listing.loading) return `<div class="arcodeExplorerLoading"${explorerDepthAttr(depth)}>Loading...</div>`;
  if (listing.error) return `<div class="arcodeExplorerLoading error"${explorerDepthAttr(depth)}>${escapeHtml(listing.error)}</div>`;
  const entries = Array.isArray(listing.entries) ? listing.entries.slice(0, 80) : [];
  if (!entries.length) return `<div class="arcodeExplorerLoading"${explorerDepthAttr(depth)}>Folder is empty.</div>`;
  return `
    <div class="arcodeExplorerChildren" role="group">
      ${entries.map((entry) => {
    const entryPath = String(entry.path || "");
    const supported = !entry.isDirectory && isSupportedCodeFile(entryPath);
    return [
      renderExplorerRow({
        path: entryPath,
        name: entry.name || filenameFromPath(entryPath) || entryPath,
        kind: entry.isDirectory ? "folder" : "file",
        depth,
        supported,
      }),
      entry.isDirectory ? renderExplorerChildren(entryPath, depth + 1) : "",
    ].join("");
  }).join("")}
    </div>
  `;
}

function updateStatus(text) {
  const value = String(text || "").trim() || "Ready";
  const status = $("arcodeStatusText");
  if (status) status.textContent = value;
}

function activeTab() {
  return state.tabs.find((tab) => tab.id === state.activeId) || null;
}

function postToTab(tab, message) {
  if (!tab?.iframe?.contentWindow) return;
  try {
    tab.iframe.contentWindow.postMessage(message, "*");
  } catch {
    // Stale frames can disappear during close.
  }
}

function tabTitle(tab) {
  return tab?.title || filenameFromPath(tab?.path) || "Untitled Notebook";
}

function getHomeCreateItem(kind) {
  return HOME_CREATE_ITEMS.find((item) => item.kind === kind) || null;
}

function baseFileNameForCreateItem(item) {
  if (item?.kind === "python") return "python_script";
  if (item?.kind === "notebook") return "notebook";
  if (item?.kind === "text") return "text_file";
  if (item?.kind === "markdown") return "markdown_file";
  if (item?.kind === "sqlserver") return "sql_server";
  if (item?.kind === "snowflake") return "snowflake_query";
  return "untitled";
}

function refreshWorkspaceFolder(folderPath) {
  const folder = String(folderPath || "").trim();
  if (!folder) return;
  delete state.folderListings[folder];
  if (isExplorerPathExpanded(folder)) void loadWorkspaceFolder(folder);
}

function normalizeExplorerWatchPath(pathLike) {
  return String(pathLike || "").trim();
}

function explorerPathKey(pathLike) {
  return normalizeExplorerWatchPath(pathLike).replace(/[\\/]+$/, "").toLowerCase();
}

function explorerPathWithin(rootPath, candidatePath) {
  const root = explorerPathKey(rootPath);
  const candidate = explorerPathKey(candidatePath);
  if (!root || !candidate) return false;
  return candidate === root || candidate.startsWith(`${root}\\`) || candidate.startsWith(`${root}/`);
}

function getExplorerVisibleFolderPaths() {
  const folders = [];
  const add = (pathLike) => {
    const folder = normalizeExplorerWatchPath(pathLike);
    if (!folder) return;
    if (!folders.some((item) => explorerPathKey(item) === explorerPathKey(folder))) folders.push(folder);
  };
  normalizeWorkspaceFolders(state.workspaceFolders).forEach(add);
  normalizeExplorerPaths(state.expandedExplorerPaths).forEach((folderPath) => {
    if (state.workspaceFolders.some((rootPath) => explorerPathWithin(rootPath, folderPath))) add(folderPath);
  });
  return folders;
}

async function stopExplorerFolderWatcher(folderPath) {
  const key = explorerPathKey(folderPath);
  const watcher = explorerFolderWatchers.get(key);
  if (!watcher) return;
  explorerFolderWatchers.delete(key);
  const host = getHostApi();
  if (typeof host?.stopArcodeFolderWatch !== "function") return;
  try {
    await host.stopArcodeFolderWatch({ watchId: watcher.watchId });
  } catch {
    // Watch cleanup is best-effort when windows are closing.
  }
}

async function syncExplorerFolderWatchers() {
  const host = getHostApi();
  if (typeof host?.startArcodeFolderWatch !== "function" || typeof host?.stopArcodeFolderWatch !== "function") return;
  const folders = getExplorerVisibleFolderPaths();
  const wantedKeys = new Set(folders.map(explorerPathKey));
  for (const [key, watcher] of Array.from(explorerFolderWatchers.entries())) {
    if (!wantedKeys.has(key)) await stopExplorerFolderWatcher(watcher.path);
  }
  for (const folderPath of folders) {
    const key = explorerPathKey(folderPath);
    if (!key || explorerFolderWatchers.has(key)) continue;
    try {
      const result = await host.startArcodeFolderWatch({ path: folderPath });
      if (result?.ok && result.watchId) {
        explorerFolderWatchers.set(key, { path: result.path || folderPath, watchId: result.watchId });
      }
    } catch {
      // Manual refresh remains available if a folder cannot be watched.
    }
  }
}

function refreshExplorerVisibleFolders(rootPath = "") {
  const root = normalizeExplorerWatchPath(rootPath);
  const candidates = getExplorerVisibleFolderPaths().filter((folderPath) => !root || explorerPathWithin(root, folderPath));
  if (!candidates.length && root) candidates.push(root);
  candidates.forEach(refreshWorkspaceFolder);
}

function scheduleExplorerAutoRefresh(folderPath) {
  const folder = normalizeExplorerWatchPath(folderPath);
  if (folder) pendingExplorerRefreshRoots.add(folder);
  window.clearTimeout(explorerRefreshTimer);
  explorerRefreshTimer = window.setTimeout(() => {
    const roots = Array.from(pendingExplorerRefreshRoots);
    pendingExplorerRefreshRoots.clear();
    explorerRefreshTimer = 0;
    if (!roots.length) {
      refreshExplorerVisibleFolders();
    } else {
      roots.forEach((root) => refreshExplorerVisibleFolders(root));
    }
    updateStatus("File explorer refreshed.");
  }, EXPLORER_REFRESH_DEBOUNCE_MS);
}

async function refreshExplorerFromButton() {
  const activeFolder = String(state.activeWorkspaceFolder || state.workspaceFolders[0] || "").trim();
  if (!activeFolder) {
    updateStatus("Select a workspace folder before refreshing the explorer.");
    return;
  }
  refreshExplorerVisibleFolders(activeFolder);
  await syncExplorerFolderWatchers();
  updateStatus("File explorer refreshed.");
}

function initExplorerFolderWatchEvents() {
  const host = getHostApi();
  if (typeof host?.onArcodeFolderChanged !== "function") return;
  host.onArcodeFolderChanged((payload = {}) => {
    const folderPath = String(payload.path || "").trim();
    if (!folderPath) return;
    if (payload.error) {
      updateStatus(`File explorer watch stopped: ${payload.error}`);
      explorerFolderWatchers.delete(explorerPathKey(folderPath));
      return;
    }
    scheduleExplorerAutoRefresh(folderPath);
  });
  void syncExplorerFolderWatchers();
}

function stopExplorerResize(event) {
  if (!explorerResizeState) return;
  const resizer = explorerResizeState.resizer;
  if (event?.pointerId != null && resizer?.hasPointerCapture?.(event.pointerId)) {
    resizer.releasePointerCapture(event.pointerId);
  }
  document.body.classList.remove("arcodeExplorerResizing");
  window.removeEventListener("pointermove", updateExplorerResize);
  window.removeEventListener("pointerup", stopExplorerResize);
  window.removeEventListener("pointercancel", stopExplorerResize);
  applyExplorerWidth(state.explorerWidth);
  explorerResizeState = null;
}

function updateExplorerResize(event) {
  if (!explorerResizeState) return;
  const nextWidth = explorerResizeState.startWidth + (event.clientX - explorerResizeState.startX);
  applyExplorerWidth(nextWidth, { persist: false });
}

function startExplorerResize(event) {
  if (event.button !== 0) return;
  const resizer = event.currentTarget;
  explorerResizeState = {
    resizer,
    startX: event.clientX,
    startWidth: normalizeExplorerWidth(state.explorerWidth),
  };
  document.body.classList.add("arcodeExplorerResizing");
  resizer.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", updateExplorerResize);
  window.addEventListener("pointerup", stopExplorerResize);
  window.addEventListener("pointercancel", stopExplorerResize);
  event.preventDefault();
}

function handleExplorerResizerKeydown(event) {
  let nextWidth = state.explorerWidth;
  if (event.key === "ArrowLeft") nextWidth -= EXPLORER_RESIZE_STEP;
  else if (event.key === "ArrowRight") nextWidth += EXPLORER_RESIZE_STEP;
  else if (event.key === "Home") nextWidth = MIN_EXPLORER_WIDTH;
  else if (event.key === "End") nextWidth = MAX_EXPLORER_WIDTH;
  else return;
  event.preventDefault();
  applyExplorerWidth(nextWidth);
}

function initExplorerResizer() {
  const resizer = $("arcodeExplorerResizer");
  if (!resizer) return;
  resizer.addEventListener("pointerdown", startExplorerResize);
  resizer.addEventListener("keydown", handleExplorerResizerKeydown);
  applyExplorerWidth(state.explorerWidth, { persist: false });
}

async function createHomeFile(kind) {
  const item = getHomeCreateItem(kind);
  if (item?.kind === "terminal") {
    await openTerminalFromHome();
    return;
  }
  if (!item?.extension) return;
  const folderPath = String(state.activeWorkspaceFolder || state.workspaceFolders[0] || "").trim();
  if (!folderPath) {
    window.alert("Select a workspace folder before creating a file.");
    return;
  }
  const host = getHostApi();
  if (typeof host?.saveTextFile !== "function" || typeof host?.saveJsonFile !== "function") {
    window.alert("File creation requires the desktop app host.");
    return;
  }
  const fileName = `${baseFileNameForCreateItem(item)}_${timestampForFileName()}${item.extension}`;
  const filePath = joinPath(folderPath, fileName);
  updateStatus(`Creating ${fileName}...`);
  const result = item.kind === "notebook"
    ? await host.saveJsonFile({ path: filePath, data: EMPTY_NOTEBOOK_TEMPLATE })
    : await host.saveTextFile({ path: filePath, data: "" });
  if (result?.error) {
    updateStatus(`Could not create ${fileName}: ${result.error}`);
    window.alert(`Could not create ${fileName}.\n\n${result.error}`);
    return;
  }
  const createdPath = String(result?.path || filePath).trim();
  refreshWorkspaceFolder(folderPath);
  openCodeTab({ path: createdPath, type: inferTabType(createdPath) });
  updateStatus(`Created ${createdPath}.`);
}

async function openTerminalFromHome() {
  const folderPath = String(state.activeWorkspaceFolder || state.workspaceFolders[0] || "").trim();
  if (!folderPath) {
    window.alert("Select a workspace folder before opening a terminal.");
    return;
  }
  const host = getHostApi();
  if (typeof host?.openTerminal !== "function") {
    window.alert("Terminal launch requires the desktop app host.");
    return;
  }
  updateStatus(`Opening terminal in ${folderPath}...`);
  const result = await host.openTerminal({ cwd: folderPath });
  if (result?.error || result?.ok === false) {
    const error = String(result?.error || "Could not open terminal.");
    updateStatus(`Could not open terminal: ${error}`);
    window.alert(`Could not open terminal.\n\n${error}`);
    return;
  }
  updateStatus(`Opened terminal in ${folderPath}.`);
}

function renderHomeCreateCard(item) {
  return `
    <button class="arcodeCreateCard" type="button" data-create-kind="${item.kind}">
      <span class="arcodeCreateCardIcon" aria-hidden="true">
        <img class="arcodeCreateCardLogo" src="${escapeHtml(item.icon || "")}" alt="" loading="lazy" />
        <span class="arcodeCreateCardExtension">${escapeHtml(item.extension || "--")}</span>
      </span>
      <span class="arcodeCreateCardTitle">${escapeHtml(item.title)}</span>
    </button>
  `;
}

function renderHomeGroupIcon(kind) {
  if (kind === "database") {
    return `
      <svg class="arcodeCreateGroupIcon" viewBox="0 0 24 24" aria-hidden="true">
        <ellipse cx="12" cy="5.5" rx="7" ry="3"></ellipse>
        <path d="M5 5.5v8c0 1.7 3.1 3 7 3s7-1.3 7-3v-8"></path>
        <path d="M5 9.5c0 1.7 3.1 3 7 3s7-1.3 7-3"></path>
      </svg>
    `;
  }
  if (kind === "terminal") {
    return `
      <svg class="arcodeCreateGroupIcon" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6h16v12H4z"></path>
        <path d="m8 10 3 2-3 2"></path>
        <path d="M13 15h4"></path>
      </svg>
    `;
  }
  return `
    <svg class="arcodeCreateGroupIcon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 4h10v16l-5-3-5 3z"></path>
      <path d="M9.5 7h5"></path>
    </svg>
  `;
}

function renderHomeCreateGroups() {
  return HOME_CREATE_GROUPS.map((group) => {
    const cards = group.kinds
      .map(getHomeCreateItem)
      .filter(Boolean)
      .map(renderHomeCreateCard)
      .join("");
    if (!cards) return "";
    const groupId = `arcode-create-group-${group.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    return `
      <section class="arcodeCreateGroup" aria-labelledby="${escapeHtml(groupId)}">
        <div class="arcodeCreateGroupHeader">
          ${renderHomeGroupIcon(group.icon)}
          <h2 id="${escapeHtml(groupId)}" class="arcodeCreateGroupTitle">${escapeHtml(group.title)}</h2>
        </div>
        <div class="arcodeCreateCards">
          ${cards}
        </div>
      </section>
    `;
  }).join("");
}

function renderExplorerWorkspacePanel() {
  const folders = state.workspaceFolders || [];
  const activeFolder = state.activeWorkspaceFolder || folders[0] || "";
  return `
    <aside class="arcodeHomeSidebar" aria-label="Explorer">
      <div class="arcodeExplorerWorkspace">
        <span class="arcodeExplorerWorkspaceLabel">Workspace</span>
        <button id="arcodeExplorerAddFolderBtn" class="arcodeExplorerHeaderBtn" type="button" title="Add workspace folder" aria-label="Add workspace folder">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 18.5v-13h5l2 2.5h9v10.5H4z"></path>
            <path d="M12 11v6"></path>
            <path d="M9 14h6"></path>
          </svg>
        </button>
        <button id="arcodeExplorerRefreshBtn" class="arcodeExplorerHeaderBtn" type="button" title="Refresh file explorer" aria-label="Refresh file explorer">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M20 6v5h-5"></path>
            <path d="M4 18v-5h5"></path>
            <path d="M18 9a7 7 0 0 0-11-3"></path>
            <path d="M6 15a7 7 0 0 0 11 3"></path>
          </svg>
        </button>
      </div>
      <div class="arcodeExplorerFolders" role="tree" aria-label="Workspace folders">
        ${folders.length ? folders.map((folderPath) => {
    const folderName = filenameFromPath(folderPath) || folderPath;
    return `
          <div class="arcodeExplorerRootRow" role="none">
            ${renderExplorerRow({
      path: folderPath,
      name: folderName,
      kind: "root-folder",
      depth: 0,
      active: folderPath === activeFolder,
    })}
            <button class="arcodeExplorerRemoveRootBtn" type="button" data-path="${encodeURIComponent(folderPath)}" title="Remove ${escapeHtml(folderName)} from the workspace" aria-label="Remove ${escapeHtml(folderName)} from the workspace">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 7l10 10"></path>
                <path d="M17 7 7 17"></path>
              </svg>
            </button>
          </div>
          ${renderExplorerChildren(folderPath)}
        `;
  }).join("") : `
          <div class="arcodeExplorerEmpty">
            <div>No folder selected.</div>
            <button id="arcodeExplorerEmptySelectBtn" class="arcodeHomeBtn primary" type="button">Select Folder</button>
          </div>
        `}
      </div>
    </aside>
    <div
      id="arcodeExplorerResizer"
      class="arcodeExplorerResizer"
      role="separator"
      aria-label="Resize file explorer"
      aria-orientation="vertical"
      aria-valuemin="${MIN_EXPLORER_WIDTH}"
      aria-valuemax="${MAX_EXPLORER_WIDTH}"
      aria-valuenow="${normalizeExplorerWidth(state.explorerWidth)}"
      tabindex="0"
      title="Resize file explorer"
    ></div>
  `;
}

function wireExplorerWorkspace(container) {
  const root = container || document;
  initExplorerResizer();
  root.querySelector("#arcodeExplorerEmptySelectBtn")?.addEventListener("click", () => pickWorkspaceFolder({ replace: true }));
  root.querySelector("#arcodeExplorerAddFolderBtn")?.addEventListener("click", () => {
    void pickWorkspaceFolder({ replace: false });
  });
  root.querySelector("#arcodeExplorerRefreshBtn")?.addEventListener("click", () => {
    void refreshExplorerFromButton();
  });
  root.querySelectorAll(".arcodeExplorerRemoveRootBtn").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      removeWorkspaceFolder(decodeURIComponent(button.getAttribute("data-path") || ""));
    });
  });
  root.querySelectorAll(".arcodeExplorerEntry").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const filePath = decodeURIComponent(button.getAttribute("data-path") || "");
      if (!filePath) return;
      if (button.dataset.kind === "folder" || button.dataset.kind === "root-folder") {
        state.activeWorkspaceFolder = button.dataset.kind === "root-folder" ? filePath : state.activeWorkspaceFolder;
        saveWorkspaceFolders();
        const expanded = button.getAttribute("aria-expanded") === "true";
        setExplorerPathExpanded(filePath, !expanded);
        updateStatus(`${expanded ? "Collapsed" : "Expanded"} folder ${filePath}.`);
        return;
      }
      if (isSupportedCodeFile(filePath)) openCodeTab({ path: filePath });
      else updateStatus("Only notebook, code, SQL, JSON, Markdown, and text files open in Arcode tabs right now.");
    });
  });
}

function renderHome() {
  const home = $("arcodeHome");
  if (!home) return;
  if (state.activeId !== "home") {
    home.textContent = "";
    return;
  }
  home.innerHTML = `
    <div class="arcodeHomeLayout arcodeWorkspaceLayout" style="--arcode-explorer-width: ${normalizeExplorerWidth(state.explorerWidth)}px;">
      ${renderExplorerWorkspacePanel()}
      <section class="arcodeHomeContent" aria-label="Arcode home content">
        <div class="arcodeCreateGroups" aria-label="Create files">
          ${renderHomeCreateGroups()}
        </div>
      </section>
    </div>
  `;
  wireExplorerWorkspace(home);
  home.querySelectorAll(".arcodeCreateCard").forEach((button) => {
    button.addEventListener("click", () => {
      void createHomeFile(button.dataset.createKind || "");
    });
  });
}
function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

let tabPointerDrag = null;
let suppressNextTabClick = false;
let tabDragEl = null;
let tabPlaceholderEl = null;
let tabHostPrevStyle = null;
let tabDragPrevStyle = null;
let tabDragBaseLeft = 0;
let tabDragBaseTop = 0;
let tabDragPrevVisibility = null;
let tabLastPlaceholderIndex = -1;

function consumeSuppressedTabClick(event) {
  if (!suppressNextTabClick) return false;
  event.preventDefault();
  event.stopPropagation();
  return true;
}

function codeTabElements() {
  return Array.from($("arcodeTabs")?.querySelectorAll(".arcodeTab[data-tab-id]:not(.arcodeHomeTab):not(.placeholder)") || []);
}

function lockTabHostLayout(host) {
  if (!host || tabHostPrevStyle) return;
  const rect = host.getBoundingClientRect();
  tabHostPrevStyle = {
    height: host.style.height,
    minHeight: host.style.minHeight,
    flexWrap: host.style.flexWrap,
    overflowX: host.style.overflowX,
    overflowY: host.style.overflowY,
    alignItems: host.style.alignItems,
  };
  host.style.height = `${Math.ceil(rect.height)}px`;
  host.style.minHeight = host.style.height;
  host.style.flexWrap = "nowrap";
  host.style.overflowX = "hidden";
  host.style.overflowY = "hidden";
  host.style.alignItems = "flex-end";
}

function unlockTabHostLayout() {
  const host = $("arcodeTabs");
  if (!host || !tabHostPrevStyle) return;
  host.style.height = tabHostPrevStyle.height;
  host.style.minHeight = tabHostPrevStyle.minHeight;
  host.style.flexWrap = tabHostPrevStyle.flexWrap;
  host.style.overflowX = tabHostPrevStyle.overflowX;
  host.style.overflowY = tabHostPrevStyle.overflowY;
  host.style.alignItems = tabHostPrevStyle.alignItems;
  tabHostPrevStyle = null;
}

function ensureTabPlaceholderFrom(el) {
  if (tabPlaceholderEl && tabPlaceholderEl.isConnected) return tabPlaceholderEl;
  const rect = el.getBoundingClientRect();
  const placeholder = document.createElement("div");
  placeholder.className = "arcodeTab placeholder";
  placeholder.innerHTML = "&nbsp;";
  placeholder.style.width = `${Math.ceil(rect.width)}px`;
  placeholder.style.height = `${Math.ceil(rect.height)}px`;
  tabPlaceholderEl = placeholder;
  return placeholder;
}

function flipAnimateArcodeTabs(host, beforeRects) {
  host.querySelectorAll(".arcodeTab[data-tab-id]:not(.arcodeHomeTab)").forEach((el) => {
    const id = el.dataset.tabId;
    if (!id || id === tabPointerDrag?.tabId || el.classList.contains("placeholder")) return;
    const before = beforeRects.get(id);
    const after = el.getBoundingClientRect();
    if (!before || !after) return;
    const dx = before.left - after.left;
    if (Math.abs(dx) < 0.5) return;
    if (el.__arcodeFlipAnim) {
      try { el.__arcodeFlipAnim.cancel(); } catch {}
      el.__arcodeFlipAnim = null;
    }
    el.__arcodeFlipAnim = el.animate(
      [{ transform: `translateX(${dx}px)` }, { transform: "translateX(0px)" }],
      { duration: 140, easing: "ease-out" },
    );
  });
}

function startTabReorderDrag(host, el, pointerId) {
  if (!host || !el || tabDragPrevStyle) return;
  tabPointerDrag.dragging = true;
  tabDragEl = el;
  lockTabHostLayout(host);
  document.body.classList.add("tab-dragging");
  try { document.body.style.cursor = "grabbing"; } catch {}
  el.classList.add("dragging");
  const hostRect = host.getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  tabDragPrevStyle = {
    position: el.style.position,
    left: el.style.left,
    top: el.style.top,
    width: el.style.width,
    height: el.style.height,
    zIndex: el.style.zIndex,
    pointerEvents: el.style.pointerEvents,
    transform: el.style.transform,
    visibility: el.style.visibility,
  };
  tabDragPrevVisibility = el.style.visibility;
  tabDragBaseLeft = (rect.left - hostRect.left) + host.scrollLeft;
  tabDragBaseTop = rect.top - hostRect.top;
  el.style.width = `${Math.ceil(rect.width)}px`;
  el.style.height = `${Math.ceil(rect.height)}px`;
  el.style.position = "absolute";
  el.style.left = `${Math.round(tabDragBaseLeft)}px`;
  el.style.top = `${Math.round(tabDragBaseTop)}px`;
  el.style.zIndex = "1000";
  el.style.pointerEvents = "none";
  el.style.transform = "translate3d(0px, 0px, 0px)";
  host.insertBefore(ensureTabPlaceholderFrom(el), el);
  closeTabContextMenu();
  try { el.setPointerCapture(pointerId); } catch {}
}

function updateTabReorderDrag(clientX) {
  const host = $("arcodeTabs");
  if (!host || !tabDragEl || !tabPlaceholderEl) return;
  const tabs = codeTabElements().filter((el) => el.dataset.tabId !== tabPointerDrag?.tabId);
  let targetNode = null;
  for (const node of tabs) {
    const rect = node.getBoundingClientRect();
    if (clientX < rect.left + rect.width / 2) {
      targetNode = node;
      break;
    }
  }
  const beforeRects = new Map();
  tabs.forEach((el) => {
    const id = el.dataset.tabId;
    if (id) beforeRects.set(id, el.getBoundingClientRect());
  });
  if (targetNode) {
    if (tabPlaceholderEl.nextSibling !== targetNode) host.insertBefore(tabPlaceholderEl, targetNode);
  } else {
    const plusTab = $("arcodePlusTab");
    if (plusTab?.parentNode === host) {
      if (tabPlaceholderEl.nextSibling !== plusTab) host.insertBefore(tabPlaceholderEl, plusTab);
    } else if (tabPlaceholderEl.parentNode !== host || tabPlaceholderEl !== host.lastChild) {
      host.appendChild(tabPlaceholderEl);
    }
  }
  const newIndex = Array.from(host.children).indexOf(tabPlaceholderEl);
  if (newIndex !== tabLastPlaceholderIndex) {
    tabLastPlaceholderIndex = newIndex;
    flipAnimateArcodeTabs(host, beforeRects);
  }
}

function commitTabOrderFromDom() {
  const host = $("arcodeTabs");
  if (!host || !tabPointerDrag?.tabId || !tabPlaceholderEl) return;
  const sequence = [];
  for (const child of host.children) {
    if (child === tabPlaceholderEl) {
      sequence.push("__PLACEHOLDER__");
      continue;
    }
    if (!child.classList?.contains("arcodeTab") || child.classList.contains("arcodeHomeTab")) continue;
    const id = child.dataset.tabId;
    if (!id || id === tabPointerDrag.tabId) continue;
    sequence.push(id);
  }
  const placeholderIndex = sequence.indexOf("__PLACEHOLDER__");
  if (placeholderIndex < 0) return;
  const ids = sequence.filter((id) => id !== "__PLACEHOLDER__");
  ids.splice(Math.max(0, Math.min(ids.length, placeholderIndex)), 0, tabPointerDrag.tabId);
  const map = new Map(state.tabs.map((tab) => [tab.id, tab]));
  const reordered = ids.map((id) => map.get(id)).filter(Boolean);
  for (const tab of state.tabs) {
    if (!reordered.some((item) => item.id === tab.id)) reordered.push(tab);
  }
  state.tabs = reordered;
}

function clearTabPointerDrag({ suppressClick = false } = {}) {
  if (suppressClick) {
    suppressNextTabClick = true;
    window.setTimeout(() => {
      suppressNextTabClick = false;
    }, 0);
  }
  if (tabDragEl) tabDragEl.classList.remove("dragging");
  if (tabPlaceholderEl?.parentNode) tabPlaceholderEl.parentNode.removeChild(tabPlaceholderEl);
  if (tabDragEl && tabDragPrevStyle) {
    tabDragEl.style.position = tabDragPrevStyle.position;
    tabDragEl.style.left = tabDragPrevStyle.left;
    tabDragEl.style.top = tabDragPrevStyle.top;
    tabDragEl.style.width = tabDragPrevStyle.width;
    tabDragEl.style.height = tabDragPrevStyle.height;
    tabDragEl.style.zIndex = tabDragPrevStyle.zIndex;
    tabDragEl.style.pointerEvents = tabDragPrevStyle.pointerEvents;
    tabDragEl.style.transform = tabDragPrevStyle.transform;
    tabDragEl.style.visibility = tabDragPrevStyle.visibility;
  } else if (tabDragEl && tabDragPrevVisibility != null) {
    tabDragEl.style.visibility = tabDragPrevVisibility;
  }
  tabPlaceholderEl = null;
  tabDragPrevStyle = null;
  tabDragPrevVisibility = null;
  tabDragBaseLeft = 0;
  tabDragBaseTop = 0;
  tabDragEl = null;
  tabLastPlaceholderIndex = -1;
  tabPointerDrag = null;
  document.body.classList.remove("tab-dragging");
  try { document.body.style.cursor = ""; } catch {}
  unlockTabHostLayout();
  window.removeEventListener("pointermove", handleTabPointerMove, true);
  window.removeEventListener("pointerup", handleTabPointerUp, true);
  window.removeEventListener("pointercancel", handleTabPointerCancel, true);
}

function handleTabPointerMove(event) {
  if (!tabPointerDrag || event.pointerId !== tabPointerDrag.pointerId) return;
  const dx = event.clientX - tabPointerDrag.startX;
  if (!tabPointerDrag.dragging) {
    if (Math.abs(dx) < TAB_DRAG_THRESHOLD_PX) return;
    startTabReorderDrag($("arcodeTabs"), tabPointerDrag.el, event.pointerId);
  }
  if (!tabPointerDrag.dragging || !tabDragEl) return;
  event.preventDefault();
  tabDragEl.style.transform = `translate3d(${dx}px, 0px, 0px)`;
  updateTabReorderDrag(event.clientX);
}

function handleTabPointerUp(event) {
  if (!tabPointerDrag || event.pointerId !== tabPointerDrag.pointerId) return;
  const wasDragging = !!tabPointerDrag.dragging;
  const tab = state.tabs.find((item) => item.id === tabPointerDrag.tabId);
  if (wasDragging) event.preventDefault();
  if (wasDragging) commitTabOrderFromDom();
  clearTabPointerDrag({ suppressClick: wasDragging });
  if (wasDragging) {
    render();
    if (tab) updateStatus(`Moved ${tabTitle(tab)}.`);
  }
}

function handleTabPointerCancel(event) {
  if (!tabPointerDrag || event.pointerId !== tabPointerDrag.pointerId) return;
  clearTabPointerDrag({ suppressClick: !!tabPointerDrag.dragging });
}

function startTabPointerDrag(event, tabId) {
  if (event.button !== 0 || event.target?.closest?.(".arcodeTabClose")) return;
  if (tabPointerDrag) clearTabPointerDrag();
  tabPointerDrag = {
    tabId,
    el: event.currentTarget,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    dragging: false,
  };
  try { event.currentTarget?.setPointerCapture?.(event.pointerId); } catch {}
  window.addEventListener("pointermove", handleTabPointerMove, true);
  window.addEventListener("pointerup", handleTabPointerUp, true);
  window.addEventListener("pointercancel", handleTabPointerCancel, true);
}

function createTabCloseIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "tabCloseIcon");
  svg.setAttribute("viewBox", "0 0 10 10");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  const lineA = document.createElementNS("http://www.w3.org/2000/svg", "line");
  lineA.setAttribute("x1", "2.5");
  lineA.setAttribute("y1", "2.5");
  lineA.setAttribute("x2", "7.5");
  lineA.setAttribute("y2", "7.5");

  const lineB = document.createElementNS("http://www.w3.org/2000/svg", "line");
  lineB.setAttribute("x1", "7.5");
  lineB.setAttribute("y1", "2.5");
  lineB.setAttribute("x2", "2.5");
  lineB.setAttribute("y2", "7.5");

  svg.append(lineA, lineB);
  return svg;
}

function renderTabs() {
  const container = $("arcodeTabs");
  if (!container) return;
  container.textContent = "";
  const homeItem = document.createElement("div");
  homeItem.className = `arcodeTab arcodeHomeTab${state.activeId === "home" ? " active" : ""}`;
  homeItem.dataset.tabId = "home";
  homeItem.title = "Home";
  const homeTitle = document.createElement("div");
  homeTitle.className = "arcodeTabTitle";
  homeTitle.textContent = "Home";
  homeItem.appendChild(homeTitle);
  homeItem.addEventListener("click", (event) => {
    if (consumeSuppressedTabClick(event)) return;
    setActiveTab("home");
  });
  container.appendChild(homeItem);

  for (const tab of state.tabs) {
    const item = document.createElement("div");
    item.className = `arcodeTab${tab.id === state.activeId ? " active" : ""}${tab.dirty ? " dirty" : ""}`;
    item.title = tab.path || tabTitle(tab);
    item.dataset.tabId = tab.id;

    const title = document.createElement("div");
    title.className = "arcodeTabTitle";
    title.textContent = tabTitle(tab);

    const close = document.createElement("button");
    close.className = "arcodeTabClose";
    close.type = "button";
    close.title = "Close";
    close.setAttribute("aria-label", `Close ${tabTitle(tab)}`);
    close.appendChild(createTabCloseIcon());
    if (tab.dirty) {
      close.classList.add("dirty");
      close.title = "Unsaved changes (close tab)";
      const dot = document.createElement("span");
      dot.className = "dirtyDot";
      close.appendChild(dot);
    }
    close.addEventListener("click", (event) => {
      event.stopPropagation();
      closeTab(tab.id);
    });

    item.append(title, close);
    item.addEventListener("pointerdown", (event) => startTabPointerDrag(event, tab.id));
    item.addEventListener("click", (event) => {
      if (consumeSuppressedTabClick(event)) return;
      setActiveTab(tab.id);
    });
    item.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      setActiveTab(tab.id);
      openTabContextMenu(tab.id, event.clientX, event.clientY);
    });
    container.appendChild(item);
  }
  const plusItem = document.createElement("div");
  plusItem.className = "arcodePlusTab";
  plusItem.id = "arcodePlusTab";
  plusItem.textContent = "+";
  plusItem.title = "New";
  plusItem.setAttribute("role", "button");
  plusItem.setAttribute("aria-label", "New");
  plusItem.tabIndex = 0;
  plusItem.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleCreateMenu();
  });
  plusItem.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    event.stopPropagation();
    toggleCreateMenu();
  });
  container.appendChild(plusItem);
  const count = $("arcodeTabCount");
  if (count) {
    count.textContent = state.tabs.length === 1
      ? "1 file open"
      : `${state.tabs.length} files open`;
  }
}

function renderFrames() {
  const home = $("arcodeHome");
  const host = $("arcodeFrameHost");
  const tab = activeTab();
  const hasActiveTab = !!tab;
  // Every editor-framework tab - the code editor and both SQL editors - shows
  // the workspace explorer; the notebook editor brings its own side panel.
  const usesExplorerWorkspace = tab?.type === "editor" || isSqlConsoleTabType(tab?.type);
  home?.classList.toggle("open", !hasActiveTab);
  host?.classList.toggle("open", hasActiveTab);
  renderFrameExplorerWorkspace(usesExplorerWorkspace);
  for (const tab of state.tabs) {
    tab.iframe?.classList.toggle("active", tab.id === state.activeId);
  }
  document.title = hasActiveTab ? `${tabTitle(activeTab())} - Arcode` : "Arcode";
}

function renderFrameExplorerWorkspace(enabled) {
  const workspace = $("arcodeFrameWorkspace");
  const explorerHost = $("arcodeFrameExplorerHost");
  if (!workspace || !explorerHost) return;
  workspace.classList.toggle("withExplorer", !!enabled);
  if (!enabled) {
    explorerHost.textContent = "";
    return;
  }
  explorerHost.innerHTML = renderExplorerWorkspacePanel();
  wireExplorerWorkspace(explorerHost);
}

function render() {
  renderHome();
  renderTabs();
  renderFrames();
  updateMenuState();
  scheduleOpenTabsSave();
}

function setActiveTab(id) {
  const tab = state.tabs.find((item) => item.id === id);
  if (!tab) {
    state.activeId = "home";
  } else {
    state.activeId = tab.id;
  }
  render();
}

function buildNotebookEditorUrl(tab) {
  const params = new URLSearchParams();
  params.set("inst", tab.scInst);
  if (tab.forceFresh) params.set("fresh", "1");
  if (tab.path) params.set("skipLast", "1");
  params.set("v", UI_VERSION_PARAM);
  return `/ui/arcode/notebook-editor/?${params.toString()}`;
}

function isSnowflakeSqlPath(pathLike) {
  const name = filenameFromPath(pathLike).toLowerCase();
  return getPathExtension(pathLike) === ".sql" && (name.includes("snowflake") || name.endsWith(".sf.sql"));
}

// Every `.sql` file belongs in a SQL editor, where Run reaches an engine, so
// SQL Server takes each one a Snowflake name has not already claimed. A file
// no longer has to name its engine to escape the plain code editor.
function isSqlServerSqlPath(pathLike) {
  return getPathExtension(pathLike) === ".sql" && !isSnowflakeSqlPath(pathLike);
}

function isSqlConsoleTabType(tabType) {
  return tabType === "snowflake" || tabType === "sqlserver";
}

function buildSqlConsoleUrl(tab) {
  const params = new URLSearchParams();
  params.set("inst", tab.scInst);
  if (tab.path) params.set("path", tab.path);
  params.set("v", UI_VERSION_PARAM);
  const consoleFolder = tab.type === "sqlserver" ? "sql-server-console" : "snowflake-console";
  return `/ui/arcode/${consoleFolder}/?${params.toString()}`;
}

function buildCodeEditorUrl(tab) {
  const params = new URLSearchParams();
  params.set("inst", tab.scInst);
  if (tab.path) params.set("path", tab.path);
  if (tab.projectJson) params.set("projectJson", JSON.stringify(tab.projectJson));
  if (tab.dfmMethod) params.set("dfm", JSON.stringify(tab.dfmMethod));
  params.set("v", UI_VERSION_PARAM);
  return `/ui/arcode/code-editor/?${params.toString()}`;
}

function buildFrameUrl(tab) {
  if (isSqlConsoleTabType(tab.type)) return buildSqlConsoleUrl(tab);
  if (tab.type === "editor") return buildCodeEditorUrl(tab);
  return buildNotebookEditorUrl(tab);
}

function createFrameForTab(tab) {
  const iframe = document.createElement("iframe");
  iframe.className = "arcodeFrame";
  iframe.dataset.tabId = tab.id;
  iframe.src = buildFrameUrl(tab);
  iframe.addEventListener("load", () => {
    if (tab.path && isSqlConsoleTabType(tab.type)) {
      postToTab(tab, { type: "arcode:sql-console-open-path", path: tab.path });
    } else if (tab.path && tab.type === "notebook") {
      postToTab(tab, { type: "arcode:scripting-open-path", path: tab.path });
    }
    postToTab(tab, { type: "arcode:set-zoom", zoom: state.zoomPercent, statusBarHeight: 28 });
    wireFrameFileDropTarget(iframe);
  });
  ($("arcodeFrameStack") || $("arcodeFrameHost"))?.appendChild(iframe);
  tab.iframe = iframe;
}

function openCodeTab(options = {}) {
  const projectJson = options.projectJson || null;
  const dfmMethod = options.dfmMethod || null;
  const filePath = (dfmMethod || projectJson) ? "" : String(options.path || options.openPath || "").trim();
  const dfmKey = (dfmMethod || projectJson) ? JSON.stringify(dfmMethod || projectJson) : "";
  const existing = dfmKey
    ? state.tabs.find((tab) => (tab.dfmMethod || tab.projectJson) && JSON.stringify(tab.dfmMethod || tab.projectJson) === dfmKey)
    : (filePath ? state.tabs.find((tab) => String(tab.path || "").toLowerCase() === filePath.toLowerCase()) : null);
  if (existing) {
    saveRecentFile(filePath);
    setActiveTab(existing.id);
    updateStatus(`Opened ${tabTitle(existing)}.`);
    return existing;
  }

  const id = `arcode_${state.nextId++}`;
  const tab = {
    id,
    title: String(options.title || "").trim()
      || projectJson?.filename || (dfmMethod ? `${dfmMethod.method_name}.json` : "")
      || filenameFromPath(filePath) || "Untitled Notebook",
    type: (dfmMethod || projectJson) ? "editor" : (String(options.type || "").trim() || inferTabType(filePath, "notebook")),
    path: filePath,
    dfmMethod,
    projectJson,
    scInst: `${id}_${Date.now()}`,
    dirty: false,
    forceFresh: !!options.forceFresh || !filePath,
    iframe: null,
  };
  state.tabs.push(tab);
  createFrameForTab(tab);
  if (filePath && !options.restoring) saveRecentFile(filePath);
  setActiveTab(tab.id);
  updateStatus((dfmMethod || projectJson) ? `Opening ${tab.title} read only...` : (filePath ? `Opening ${filePath}...` : "New notebook opened."));
  return tab;
}

async function closeTab(id, skipConfirm = false) {
  let index = state.tabs.findIndex((tab) => tab.id === id);
  if (index < 0) return;
  const tab = state.tabs[index];
  if (!skipConfirm && tab.dirty) {
    const confirmed = await confirmDiscardClose({ message: `Unsaved changes in ${tabTitle(tab)} will be lost.` });
    if (!confirmed) return;
    index = state.tabs.indexOf(tab);
    if (index < 0) return;
  }
  tab.iframe?.remove();
  state.tabs.splice(index, 1);
  if (state.activeId === id) {
    const fallback = state.tabs[Math.max(0, index - 1)] || state.tabs[0] || null;
    state.activeId = fallback?.id || "home";
  }
  render();
}

async function openFileDialog() {
  const host = getHostApi();
  if (!host?.pickOpenFile) {
    updateStatus("Open file requires the desktop app host.");
    return;
  }
  const filePath = await host.pickOpenFile({
    filters: [
      { name: "Arcode Files", extensions: ["ipynb", "arcnb", "py", "r", "sql", "js", "ts", "json", "md", "txt", "css", "html", "htm"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (filePath) openCodeTab({ path: filePath });
}

const databaseConnectionsDialog = createDatabaseConnectionsDialog({
  setStatus: updateStatus,
  // Open SQL editors hold a connection picker, so they reload it rather than
  // keeping a list the dialog has already changed.
  onChanged: () => broadcastToTabs({ type: "arcode:database-connections-changed" }),
});

function broadcastToTabs(message) {
  for (const tab of state.tabs) postToTab(tab, message);
}

function sendScriptingCommand(type) {
  const tab = activeTab();
  if (!tab) return;
  postToTab(tab, { type });
}

function handleHotkey(action) {
  if (action === "file_save") return sendScriptingCommand("arcode:scripting-save");
  if (action === "file_save_as") return sendScriptingCommand("arcode:scripting-save-as");
  if (action === "file_import") return openFileDialog();
  if (action === "custom_refresh" || action === "custom_hard_refresh") {
    const tab = activeTab();
    if (tab?.iframe) tab.iframe.contentWindow?.location?.reload();
    return;
  }
  if (action === "app_shutdown") {
    window.ADAHost?.shutdownApp?.();
  }
}

function updateTabFromMessage(msg, source) {
  const inst = String(msg.inst || "").trim();
  return state.tabs.find((tab) => (
    (inst && tab.scInst === inst) || tab.iframe?.contentWindow === source
  ));
}

function initMessages() {
  window.addEventListener("message", (event) => {
    const msg = event.data || {};
    if (msg.type === "arcode:update-active-tab-title") {
      const tab = updateTabFromMessage(msg, event.source);
      if (!tab) return;
      tab.title = String(msg.title || "").trim() || tab.title;
      const path = String(msg.path || "").trim();
      if (path) {
        tab.path = path;
        saveRecentFile(path);
      }
      render();
      return;
    }
    if (msg.type === "arcode:scripting-dirty") {
      const tab = updateTabFromMessage(msg, event.source);
      if (!tab) return;
      tab.dirty = !!msg.dirty;
      renderTabs();
      return;
    }
    if (msg.type === "arcode:status") {
      updateStatus(msg.text || "");
      return;
    }
    if (msg.type === "arcode:hotkey") {
      handleHotkey(String(msg.action || ""));
      return;
    }
    if (msg.type === "arcode:close-active-tab") {
      const tab = activeTab();
      if (tab) closeTab(tab.id);
      return;
    }
    if (msg.type === "arcode:open-file") {
      const filePath = String(msg.path || "").trim();
      if (msg.projectJson) openCodeTab({ projectJson: msg.projectJson });
      else if (msg.dfmMethod) openCodeTab({ dfmMethod: msg.dfmMethod });
      else if (filePath) openCodeTab({ path: filePath });
      return;
    }
    if (msg.type === "arcode:zoom") {
      adjustZoomByDelta(msg.deltaY, { quiet: true });
      return;
    }
    if (msg.type === "arcode:zoom-step") {
      const delta = Number(msg.delta || 0);
      if (Number.isFinite(delta) && delta) setZoomPercent(state.zoomPercent + delta * ZOOM_STEP, { quiet: true });
      return;
    }
    if (msg.type === "arcode:zoom-reset") {
      setZoomPercent(100, { quiet: true });
      return;
    }
  });
}

function initWindowControls() {
  const host = window.ADAHost;
  const toggleMaximize = async () => {
    if (!host) return;
    const maximized = await host.isMaximized?.();
    if (maximized) host.restoreWindow?.();
    else host.maximizeWindow?.();
  };
  $("titlebarMinBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    host?.minimizeWindow?.();
  });
  $("titlebarMaxBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMaximize().catch(() => host?.maximizeWindow?.());
  });
  $("titlebarCloseBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    host?.closeWindow?.();
  });
  $("customTitlebar")?.addEventListener("dblclick", (event) => {
    if (event.target?.closest?.(".host-nodrag")) return;
    toggleMaximize().catch(() => host?.maximizeWindow?.());
  });
  $("customTitlebar")?.addEventListener("mousedown", async (event) => {
    if (event.target?.closest?.(".host-nodrag")) return;
    try {
      if (!(await host?.isMaximized?.())) return;
      const startX = event.clientX;
      const startY = event.clientY;
      const onMove = (moveEvent) => {
        if (Math.abs(moveEvent.clientX - startX) < 5 && Math.abs(moveEvent.clientY - startY) < 5) return;
        window.removeEventListener("mousemove", onMove);
        host?.restoreWindow?.();
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp, { once: true });
    } catch {
      // Native drag behavior still works when maximize state cannot be read.
    }
  });
}

function closeAllShellMenus() {
  closeAllCascadeSubmenus();
  document.querySelectorAll(".menuDropdown.open").forEach((el) => el.classList.remove("open"));
  document.querySelectorAll(".menu.open").forEach((el) => el.classList.remove("open"));
  document.querySelectorAll('.menu[aria-expanded="true"]').forEach((el) => el.setAttribute("aria-expanded", "false"));
  closeTabContextMenu();
}

function positionMenu(button, dropdown) {
  if (!button || !dropdown) return;
  const rect = button.getBoundingClientRect();
  dropdown.style.left = `${Math.round(rect.left)}px`;
  dropdown.style.top = `${Math.round(rect.bottom + 6)}px`;
}

function toggleMenu(menuName, forceOpen) {
  const button = document.querySelector(`.menu[data-menu="${menuName}"]`);
  const dropdown = $(`${menuName}MenuDropdown`);
  if (!button || !dropdown) return;
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : !dropdown.classList.contains("open");
  closeAllShellMenus();
  button.classList.toggle("open", shouldOpen);
  dropdown.classList.toggle("open", shouldOpen);
  if (button.hasAttribute("aria-haspopup")) button.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
  if (shouldOpen) {
    updateMenuState();
    positionMenu(button, dropdown);
  }
}

function setMenuItemDisabled(action, disabled) {
  document.querySelectorAll(`.menuItem[data-action="${action}"], .tabCtxItem[data-action="${action}"]`).forEach((el) => {
    el.classList.toggle("disabled", !!disabled);
  });
}

function renderRecentFilesMenu() {
  const menuItem = $("recentFilesMenuItem");
  const submenu = $("recentFilesSubmenu");
  if (!menuItem || !submenu) return;
  const recentFiles = readRecentFiles();
  submenu.textContent = "";
  menuItem.classList.toggle("disabled", recentFiles.length === 0);
  if (!recentFiles.length) {
    const empty = document.createElement("div");
    empty.className = "menuItem disabled";
    const label = document.createElement("span");
    label.textContent = "No recent files";
    empty.appendChild(label);
    submenu.appendChild(empty);
    return;
  }
  recentFiles.slice(0, 10).forEach((filePath) => {
    const item = document.createElement("div");
    item.className = "menuItem";
    item.dataset.action = "open-recent-file";
    item.dataset.path = encodeURIComponent(filePath);
    item.title = filePath;

    const label = document.createElement("span");
    label.className = "menuPath";
    label.textContent = filePath;

    item.appendChild(label);
    submenu.appendChild(item);
  });
}

function updateMenuState() {
  const hasTab = !!activeTab();
  const hasPath = !!activeTab()?.path;
  const aiBotIconLabel = document.querySelector('.menuItem[data-action="toggle-ai-bot-icon"] > span');
  if (aiBotIconLabel) {
    aiBotIconLabel.textContent = isAiAssistantLauncherVisible() ? "Hide AI Bot Icon" : "Show AI Bot Icon";
  }
  const colorTheme = window.ArcRhoColorTheme?.getTheme?.() || "light";
  const themes = window.ArcRhoColorTheme?.THEMES || ["light", "dark"];
  for (const theme of themes) {
    document.querySelector(`.menuItem[data-action="color-theme-${theme}"]`)
      ?.setAttribute("aria-checked", theme === colorTheme ? "true" : "false");
  }
  // A DFM method opened from its page is read only: it has nothing to save.
  const readOnly = !!(activeTab()?.dfmMethod || activeTab()?.projectJson);
  ["save", "save-as", "close-tab", "close-others", "close-all", "render-markdown", "toggle-line-numbers", "toggle-exec-time", "refresh-tab", "hard-refresh", "rename"].forEach((action) => {
    setMenuItemDisabled(action, !hasTab || (readOnly && (action === "save" || action === "save-as")));
  });
  // The shortcut editor belongs to notebook tabs.
  setMenuItemDisabled("keyboard-shortcuts", activeTab()?.type !== "notebook");
  setMenuItemDisabled("open-file-location", !hasPath);
  setMenuItemDisabled("copy-file-path", !hasPath);
  renderRecentFilesMenu();
}

async function closeTabsExcept(keepId) {
  const keep = state.tabs.find((tab) => tab.id === keepId) || null;
  const closing = state.tabs.filter((tab) => tab.id !== keepId);
  const dirty = closing.filter((tab) => tab.dirty);
  if (dirty.length) {
    const confirmed = await confirmDiscardClose({ message: `Unsaved changes in ${dirty.length} ${dirty.length === 1 ? "file" : "files"} will be lost.` });
    if (!confirmed) return;
  }
  for (const tab of closing) await closeTab(tab.id, true);
  if (keep) setActiveTab(keep.id);
}

async function closeAllTabs() {
  const dirty = state.tabs.filter((tab) => tab.dirty);
  if (dirty.length) {
    const confirmed = await confirmDiscardClose({ message: `Unsaved changes in ${dirty.length} ${dirty.length === 1 ? "file" : "files"} will be lost.` });
    if (!confirmed) return;
  }
  for (const tab of [...state.tabs]) closeTab(tab.id, true);
}

function reloadActiveTab({ hard = false } = {}) {
  const tab = activeTab();
  if (!tab?.iframe) return;
  if (hard) {
    tab.forceFresh = false;
    tab.scInst = `${tab.id}_${Date.now()}`;
    tab.iframe.src = buildFrameUrl(tab);
  } else {
    tab.iframe.contentWindow?.location?.reload();
  }
  updateStatus(hard ? "Reloading tab without cache..." : "Reloading tab...");
}

function hostZoomAvailable() {
  return typeof window.ADAHost?.setZoomFactor === "function";
}

function updateZoomUI() {
  const range = $("zoomRange");
  const value = $("zoomValue");
  if (range) range.value = String(state.zoomPercent);
  if (value) value.textContent = `${state.zoomPercent}%`;
}

function broadcastZoom() {
  broadcastToTabs({ type: "arcode:set-zoom", zoom: state.zoomPercent, statusBarHeight: 28 });
}

function setZoomPercent(value, { quiet = false } = {}) {
  const next = normalizeZoomPercent(value, DEFAULT_ZOOM_PERCENT);
  state.zoomPercent = Number.isFinite(next) ? next : DEFAULT_ZOOM_PERCENT;
  const scale = state.zoomPercent / 100;
  try { localStorage.setItem(ZOOM_STORAGE_KEY, String(state.zoomPercent)); } catch {}
  try { localStorage.setItem(STATUSBAR_H_KEY, "28"); } catch {}
  if (hostZoomAvailable()) {
    try { localStorage.setItem(ZOOM_MODE_KEY, "host"); } catch {}
    window.ADAHost.setZoomFactor(scale);
  } else {
    try { localStorage.setItem(ZOOM_MODE_KEY, "css"); } catch {}
    document.documentElement.style.zoom = String(scale);
  }
  updateZoomUI();
  broadcastZoom();
  void saveArcodeUserSettings();
  if (!quiet) updateStatus(`Zoom ${state.zoomPercent}%.`);
}

function adjustZoomByDelta(deltaY, options = {}) {
  const delta = Number(deltaY || 0);
  if (!Number.isFinite(delta) || !delta) return;
  setZoomPercent(state.zoomPercent + (delta > 0 ? -ZOOM_STEP : ZOOM_STEP), options);
}

function initZoomControls() {
  state.zoomPercent = normalizeZoomPercent(state.zoomPercent, DEFAULT_ZOOM_PERCENT);
  $("zoomOutBtn")?.addEventListener("click", () => setZoomPercent(state.zoomPercent - ZOOM_STEP));
  $("zoomInBtn")?.addEventListener("click", () => setZoomPercent(state.zoomPercent + ZOOM_STEP));
  $("zoomRange")?.addEventListener("input", (event) => {
    const value = $("zoomValue");
    if (value) value.textContent = `${event.target.value}%`;
  });
  $("zoomRange")?.addEventListener("change", (event) => setZoomPercent(event.target.value));
  setZoomPercent(state.zoomPercent, { quiet: true });
}

function activePath() {
  return String(activeTab()?.path || "").trim();
}

async function openActiveFileLocation() {
  const path = activePath();
  if (!path) return updateStatus("No file path for this tab.");
  const result = await window.ADAHost?.showItemInFolder?.({ path });
  updateStatus(result?.ok === false ? (result.error || "Could not reveal file.") : "Opened file location.");
}

async function copyActiveFilePath() {
  const path = activePath();
  if (!path) return updateStatus("No file path for this tab.");
  try {
    await navigator.clipboard.writeText(path);
    updateStatus("Copied file path.");
  } catch {
    updateStatus("Could not copy file path.");
  }
}

function toggleCreateMenu(forceOpen) {
  const button = $("arcodePlusTab");
  const dropdown = $("arcodeCreateMenu");
  if (!button || !dropdown) return;
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : !dropdown.classList.contains("open");
  closeAllShellMenus();
  dropdown.classList.toggle("open", shouldOpen);
  if (shouldOpen) positionMenu(button, dropdown);
}
// The open tabs are saved with the settings, so the restarted app opens them again.
async function restartArcode() {
  if (!(await confirmWindowClose())) {
    updateStatus("Restart canceled.");
    return;
  }
  const saved = await saveArcodeUserSettings({ reportFailure: true });
  if (saved?.ok === false) {
    updateStatus(`Restart canceled: ${saved.error || "Unable to save Arcode settings."}`);
    return;
  }
  updateStatus("Restarting Arcode...");
  try { await fetch("/app/restart_electron", { method: "POST" }); } catch {}
}

async function runShellAction(action, detail = {}) {
  if (!action) return;
  if (action === "create-notebook") return openCodeTab({ forceFresh: true });
  if (action === "create-python") return createHomeFile("python");
  if (action === "create-mssql") return createHomeFile("sqlserver");
  if (action === "create-snowflake") return createHomeFile("snowflake");
  if (action === "open-file") return openFileDialog();
  if (action === "recent-files") return;
  if (action === "open-recent-file") {
    const filePath = String(detail.path || "").trim();
    if (filePath) return openCodeTab({ path: filePath });
    return updateStatus("Recent file path is unavailable.");
  }
  if (action === "select-folder") return pickWorkspaceFolder({ replace: true });
  if (action === "add-folder") return pickWorkspaceFolder({ replace: false });
  if (action === "save") return sendScriptingCommand("arcode:scripting-save");
  if (action === "save-as") return sendScriptingCommand("arcode:scripting-save-as");
  if (action === "close-tab") return activeTab() ? closeTab(state.activeId) : undefined;
  if (action === "quit") {
    void confirmWindowClose().then((ok) => { if (ok) window.ADAHost?.closeWindow?.(); });
    return;
  }
  if (action === "restart-app") return restartArcode();
  if (action === "render-markdown") return sendScriptingCommand("arcode:scripting-render-all-markdown");
  if (action === "toggle-ai-bot-icon") {
    const visible = toggleAiAssistantLauncherVisible();
    updateStatus(`AI bot icon ${visible ? "shown" : "hidden"}.`);
    return;
  }
  if (action === "toggle-line-numbers") return sendScriptingCommand("arcode:scripting-toggle-line-numbers");
  if (action === "toggle-exec-time") return sendScriptingCommand("arcode:scripting-toggle-exec-time");
  if (action === "zoom-in") return setZoomPercent(state.zoomPercent + ZOOM_STEP);
  if (action === "zoom-out") return setZoomPercent(state.zoomPercent - ZOOM_STEP);
  if (action === "zoom-reset") return setZoomPercent(100);
  if (action === "refresh-tab") return reloadActiveTab();
  if (action === "hard-refresh") return reloadActiveTab({ hard: true });
  if (action.startsWith("color-theme-")) {
    const theme = window.ArcRhoColorTheme?.normalizeTheme?.(action.slice("color-theme-".length)) || "light";
    window.ArcRhoColorTheme?.setTheme?.(theme, { source: "arcode-settings" });
    updateMenuState();
    const label = theme.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    updateStatus(`Color theme changed to ${label}.`);
    return;
  }
  if (action === "database-connections") return databaseConnectionsDialog.open();
  if (action === "keyboard-shortcuts") return sendScriptingCommand("arcode:scripting-open-shortcuts");
  if (action === "clear-cache-reload") {
    if (typeof window.ADAHost?.clearCacheAndReload !== "function") {
      updateStatus("Clear Cache & Reload requires the desktop app host.");
      return;
    }
    if (!(await confirmWindowClose())) {
      updateStatus("Clear Cache & Reload canceled.");
      return;
    }
    const saved = await saveArcodeUserSettings({ reportFailure: true });
    if (saved?.ok === false) {
      updateStatus(`Clear Cache & Reload canceled: ${saved.error || "Unable to save Arcode settings."}`);
      return;
    }
    updateStatus("Clearing cache and reloading...");
    return window.ADAHost.clearCacheAndReload({
      restore: buildClearCacheReloadRestorePayload(),
      colorTheme: window.ArcRhoColorTheme?.getTheme?.() || "light",
    });
  }
  if (action === "new-window") return window.ADAHost?.openArcodeWindow?.({ fresh: true });
  if (action === "close-others") return activeTab() ? closeTabsExcept(state.activeId) : undefined;
  if (action === "close-all") return closeAllTabs();
  if (action === "minimize-window") return window.ADAHost?.minimizeWindow?.();
  if (action === "toggle-maximize") {
    const maximized = await window.ADAHost?.isMaximized?.();
    return maximized ? window.ADAHost?.restoreWindow?.() : window.ADAHost?.maximizeWindow?.();
  }
  if (action === "view-dev-panel") return window.ADAHost?.toggleDevPanel?.();
  if (action === "open-file-location") return openActiveFileLocation();
  if (action === "copy-file-path") return copyActiveFilePath();
}

function initShellMenus() {
  initCascadeMenus();
  window.ArcRhoColorTheme?.wireThemeMenus?.();
  document.querySelectorAll(".menu[data-menu]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleMenu(button.dataset.menu || "");
    });
  });
  document.querySelectorAll(".menuDropdown").forEach((dropdown) => {
    dropdown.addEventListener("click", (event) => {
      const item = event.target?.closest?.(".menuItem");
      if (!item || item.classList.contains("disabled")) return;
      if (item.dataset.action === "recent-files") return;
      closeAllShellMenus();
      const path = item.dataset.path ? decodeURIComponent(item.dataset.path) : "";
      void runShellAction(item.dataset.action || "", { path });
    });
  });
  window.addEventListener("click", () => closeAllShellMenus());
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") closeAllShellMenus(); });
  updateMenuState();
}

let tabCtxId = "";

function closeTabContextMenu() {
  const menu = $("tabCtxMenu");
  menu?.classList.remove("open");
  tabCtxId = "";
}

function openTabContextMenu(tabId, x, y) {
  const menu = $("tabCtxMenu");
  if (!menu) return;
  tabCtxId = tabId;
  updateMenuState();
  const tab = state.tabs.find((item) => item.id === tabId);
  menu.querySelectorAll(".tabCtxItem").forEach((item) => {
    const action = item.dataset.action || "";
    const disabled = !tab || ((action === "open-file-location" || action === "copy-file-path") && !tab.path);
    item.classList.toggle("disabled", disabled);
  });
  menu.classList.add("open");
  const pad = 8;
  const maxX = window.innerWidth - menu.offsetWidth - pad;
  const maxY = window.innerHeight - menu.offsetHeight - pad;
  menu.style.left = `${Math.max(pad, Math.min(x, maxX))}px`;
  menu.style.top = `${Math.max(pad, Math.min(y, maxY))}px`;
}

function initTabContextMenu() {
  $("tabCtxMenu")?.addEventListener("click", (event) => {
    const item = event.target?.closest?.(".tabCtxItem");
    if (!item || item.classList.contains("disabled")) return;
    const tab = state.tabs.find((entry) => entry.id === tabCtxId);
    if (tab) setActiveTab(tab.id);
    closeAllShellMenus();
    void runShellAction(item.dataset.action || "");
  });
}

function shouldIgnoreHotkey(event) {
  const tag = event.target?.tagName?.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || event.target?.isContentEditable;
}

function initHotkeys() {
  window.addEventListener("keydown", (event) => {
    if (event.ctrlKey && !event.altKey && (event.key === "-" || event.key === "_")) { event.preventDefault(); setZoomPercent(state.zoomPercent - ZOOM_STEP); return; }
    if (event.ctrlKey && !event.altKey && (event.key === "=" || event.key === "+")) { event.preventDefault(); setZoomPercent(state.zoomPercent + ZOOM_STEP); return; }
    if (event.ctrlKey && !event.altKey && event.key === "0") { event.preventDefault(); setZoomPercent(100); return; }
    if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "i") { event.preventDefault(); window.ADAHost?.toggleDevPanel?.(); return; }
    if (shouldIgnoreHotkey(event)) return;
    const key = event.key.toLowerCase();
    if (event.ctrlKey && !event.shiftKey && key === "n") { event.preventDefault(); openCodeTab({ forceFresh: true }); return; }
    if (event.ctrlKey && event.shiftKey && key === "n") { event.preventDefault(); window.ADAHost?.openArcodeWindow?.({}); return; }
    if (event.ctrlKey && !event.shiftKey && key === "o") { event.preventDefault(); openFileDialog(); return; }
    if (event.ctrlKey && !event.shiftKey && key === "s") { event.preventDefault(); sendScriptingCommand("arcode:scripting-save"); return; }
    if (event.ctrlKey && event.shiftKey && key === "s") { event.preventDefault(); sendScriptingCommand("arcode:scripting-save-as"); return; }
    if ((event.ctrlKey && key === "w") || (event.altKey && key === "w")) { event.preventDefault(); if (activeTab()) closeTab(state.activeId); return; }
    if (event.ctrlKey && !event.shiftKey && key === "r") { event.preventDefault(); reloadActiveTab(); return; }
    if (event.ctrlKey && event.shiftKey && key === "r") { event.preventDefault(); reloadActiveTab({ hard: true }); return; }
    if (event.ctrlKey && event.shiftKey && key === "l") { event.preventDefault(); sendScriptingCommand("arcode:scripting-toggle-line-numbers"); return; }
    if (event.ctrlKey && event.shiftKey && key === "e") { event.preventDefault(); sendScriptingCommand("arcode:scripting-toggle-exec-time"); return; }
    if (event.ctrlKey && key === "q") { event.preventDefault(); void confirmWindowClose().then((ok) => { if (ok) window.ADAHost?.closeWindow?.(); }); }
  }, { capture: true });
  window.addEventListener("wheel", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    adjustZoomByDelta(event.deltaY || event.deltaX, { quiet: true });
  }, { capture: true, passive: false });
}
let arcodeFileDropsWired = false;
let arcodeDropOverlayTimer = 0;
const arcodeFrameDropTargets = new WeakSet();

function getPathExtension(pathLike) {
  const value = String(pathLike || "").trim().toLowerCase();
  const dot = value.lastIndexOf(".");
  return dot >= 0 ? value.slice(dot) : "";
}

function hasExternalFiles(event) {
  const transfer = event?.dataTransfer;
  if (!transfer) return false;
  const types = Array.from(transfer.types || []);
  if (types.includes("Files")) return true;
  return Array.from(transfer.items || []).some((item) => item?.kind === "file");
}

function getDroppedFilePath(file) {
  if (!file) return "";
  const host = getHostApi();
  if (typeof host?.getPathForFile === "function") {
    try {
      const resolved = host.getPathForFile(file);
      if (resolved) return String(resolved);
    } catch {
      // Fall through to Electron's legacy file.path when available.
    }
  }
  return typeof file.path === "string" ? file.path : "";
}

function getDroppedEntries(event) {
  return Array.from(event?.dataTransfer?.files || []).map((file) => {
    const path = getDroppedFilePath(file);
    const name = String(file?.name || filenameFromPath(path) || "").trim();
    const extension = getPathExtension(path || name);
    return { file, path, name, extension, supported: DROP_FILE_EXTENSIONS.has(extension) };
  });
}

function getSupportedDroppedPaths(event) {
  const seen = new Set();
  const paths = [];
  for (const entry of getDroppedEntries(event)) {
    if (!entry.supported || !entry.path) continue;
    const key = entry.path.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    paths.push(entry.path);
  }
  return paths;
}

function ensureDropOverlay() {
  let overlay = $("arcodeFileDropOverlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "arcodeFileDropOverlay";
  overlay.setAttribute("aria-hidden", "true");
  overlay.innerHTML = `
    <div class="arcodeFileDropPanel">
      <div id="arcodeFileDropTitle" class="arcodeFileDropTitle">Drop to open in Arcode</div>
      <div id="arcodeFileDropDetail" class="arcodeFileDropDetail">Notebook, code, SQL, JSON, Markdown, and text files are supported.</div>
    </div>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

function showDropOverlay(event) {
  const overlay = ensureDropOverlay();
  const entries = getDroppedEntries(event);
  const supported = entries.filter((entry) => entry.supported);
  const unsupported = entries.length > 0 && supported.length === 0;
  const title = $("arcodeFileDropTitle");
  const detail = $("arcodeFileDropDetail");
  if (title) {
    title.textContent = unsupported
      ? "Drop a supported Arcode file"
      : supported.length > 1
        ? `Drop to open ${supported.length} files in Arcode`
        : "Drop to open in Arcode";
  }
  if (detail) {
    detail.textContent = unsupported
      ? "Only notebook, code, SQL, JSON, Markdown, and text files are supported."
      : supported.length === 1
        ? (supported[0].name || supported[0].path || "Notebook, code, SQL, JSON, Markdown, and text files are supported.")
        : "Notebook, code, SQL, JSON, Markdown, and text files are supported.";
  }
  overlay.classList.toggle("unsupported", unsupported);
  overlay.classList.add("open");
  window.clearTimeout(arcodeDropOverlayTimer);
  arcodeDropOverlayTimer = window.setTimeout(hideDropOverlay, 350);
}

function hideDropOverlay() {
  window.clearTimeout(arcodeDropOverlayTimer);
  arcodeDropOverlayTimer = 0;
  $("arcodeFileDropOverlay")?.classList.remove("open", "unsupported");
}

function handleArcodeFileDragOver(event) {
  if (!hasExternalFiles(event)) return false;
  event.preventDefault();
  event.stopPropagation();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  showDropOverlay(event);
  return true;
}

function handleArcodeFileDrop(event) {
  if (!hasExternalFiles(event)) return false;
  event.preventDefault();
  event.stopPropagation();
  hideDropOverlay();
  const paths = getSupportedDroppedPaths(event);
  if (!paths.length) {
    updateStatus("Drop a .py, .sql, .ipynb, .md, .txt, or .json file to open it in Arcode.");
    return true;
  }
  for (const path of paths) openCodeTab({ path });
  updateStatus(paths.length === 1 ? `Opened ${filenameFromPath(paths[0])}.` : `Opened ${paths.length} files.`);
  return true;
}

function wireFrameFileDropTarget(iframe) {
  const frameWindow = iframe?.contentWindow;
  if (!frameWindow || arcodeFrameDropTargets.has(frameWindow)) return;
  try {
    frameWindow.addEventListener("dragover", handleArcodeFileDragOver, true);
    frameWindow.addEventListener("drop", handleArcodeFileDrop, true);
    frameWindow.addEventListener("dragleave", () => {
      window.clearTimeout(arcodeDropOverlayTimer);
      arcodeDropOverlayTimer = window.setTimeout(hideDropOverlay, 120);
    }, true);
    arcodeFrameDropTargets.add(frameWindow);
  } catch {
    // If a frame is unavailable during navigation, the next load event will wire it.
  }
}

function initArcodeFileDrops() {
  if (arcodeFileDropsWired) return;
  arcodeFileDropsWired = true;
  window.addEventListener("dragover", handleArcodeFileDragOver, true);
  window.addEventListener("drop", handleArcodeFileDrop, true);
  window.addEventListener("dragleave", () => {
    window.clearTimeout(arcodeDropOverlayTimer);
    arcodeDropOverlayTimer = window.setTimeout(hideDropOverlay, 120);
  }, true);
  window.addEventListener("blur", hideDropOverlay);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideDropOverlay();
  }, true);
}
function initAppFrameStyle() {
  if (!window.ADAHost?.isWindows11) return;
  window.ADAHost.isWindows11()
    .then((isWin11) => {
      document.body.classList.toggle("win11-frame", !!isWin11);
      document.body.classList.toggle("win10-borders", !isWin11);
    })
    .catch(() => {});
}

async function confirmWindowClose() {
  const dirty = state.tabs.filter((tab) => tab.dirty);
  if (!dirty.length) return true;
  const label = dirty.length === 1 ? tabTitle(dirty[0]) : `${dirty.length} files`;
  return confirmDiscardClose({
    title: "Close Arcode without saving?",
    message: `Unsaved changes in ${label} will be lost.`,
  });
}

function initShellApi() {
  registerShellApi({
    state,
    getHostApi,
    updateStatusBar: updateStatus,
    updateViewMenuState: updateMenuState,
    render,
    saveState: () => {},
    ensureIframe: () => {},
  });
}

async function boot() {
  initShellApi();
  await loadArcodeUserSettings();
  initAppFrameStyle();
  initWindowControls();
  initShellMenus();
  window.addEventListener("arcrho:color-theme-changed", updateMenuState);
  initTabContextMenu();
  initZoomControls();
  initHotkeys();
  initArcodeFileDrops();
  initMessages();
  initExplorerFolderWatchEvents();
  window.__arcode_confirm_window_close = confirmWindowClose;
  await loadExplorerFileIcons();
  render();
  initAiAssistant();
  const restored = await restoreTabsAfterClearCacheReload();
  const restoredSaved = !restored && !initialFreshWindow && restoreSavedOpenTabs();
  if (!restored && initialProjectJsonParam) openCodeTab({ projectJson: JSON.parse(initialProjectJsonParam) });
  else if (!restored && initialDfmMethodParam) openCodeTab({ dfmMethod: JSON.parse(initialDfmMethodParam) });
  else if (!restored && initialOpenPath) openCodeTab({ path: initialOpenPath });
  else if (!restored && !restoredSaved) setActiveTab("home");
  state.openTabsPersistReady = !initialFreshWindow;
  scheduleOpenTabsSave();
}

void boot();
