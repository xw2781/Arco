import { shell } from "./shell_context.js?v=20260510a";
import { isAiAssistantLauncherVisible, toggleAiAssistantLauncherVisible } from "../ai-assistant/arcrho.js?v=20260927smb24";
import { closeMacroContextMenus, isMacroContextMenuOpen, openMacroWindow } from "../macro/macro_window.js?v=20260908b";
import { isFlightDeckVisible, toggleFlightDeck } from "../flight_deck/flight_deck.js?v=20260906a";
import { initReleaseNotesDialog, openReleaseHistory } from "./release_notes_dialog.js?v=20260820a";
import { openUserGuide } from "./user_guide.js?v=20261003a";
import { closeAllCascadeSubmenus, initCascadeMenus } from "../shared/components/cascade_menu/cascade_menu.js?v=20260817a";

const fileMenuBtn = document.querySelector('.menu[data-menu="file"]');
const fileMenuDropdown = document.getElementById("fileMenuDropdown");
const recentNotebookMenuItem = document.getElementById("recentNotebookMenuItem");
const recentNotebookSubmenu = document.getElementById("recentNotebookSubmenu");
const editMenuBtn = document.querySelector('.menu[data-menu="edit"]');
const editMenuDropdown = document.getElementById("editMenuDropdown");
const viewMenuBtn = document.querySelector('.menu[data-menu="view"]');
const viewMenuDropdown = document.getElementById("viewMenuDropdown");
const settingsMenuBtn = document.querySelector('.menu[data-menu="settings"]');
const settingsMenuDropdown = document.getElementById("settingsMenuDropdown");
const helpMenuBtn = document.querySelector('.menu[data-menu="help"]');
const helpMenuDropdown = document.getElementById("helpMenuDropdown");
const menuBarEl = document.getElementById("menubar");
const aboutOverlay = document.getElementById("aboutOverlay");
const aboutVersion = document.getElementById("aboutVersion");
const aboutCheckUpdatesBtn = document.getElementById("aboutCheckUpdatesBtn");
const aboutReleaseHistoryBtn = document.getElementById("aboutReleaseHistoryBtn");
let dfmEditEnabled = false;
let dfmUndoEnabled = false;
let dfmRedoEnabled = false;
let shellMenusWired = false;
let recentNotebookLoadToken = 0;
let aboutUpdateCheckRunning = false;
let aboutVersionLoaded = false;

function positionDropdown(btn, dropdown) {
  if (!btn || !dropdown) return;
  const r = btn.getBoundingClientRect();
  dropdown.style.left = `${Math.round(r.left)}px`;
  dropdown.style.top = `${Math.round(r.bottom + 6)}px`;
}
function toggleDropdown(btn, dropdown, forceOpen) {
  if (!dropdown) return;
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : !dropdown.classList.contains("open");
  dropdown.classList.toggle("open", shouldOpen);
  if (btn?.hasAttribute?.("aria-haspopup")) btn.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
  if (shouldOpen) positionDropdown(btn, dropdown);
}
function toggleFileMenu(forceOpen) { toggleDropdown(fileMenuBtn, fileMenuDropdown, forceOpen); }
function toggleEditMenu(forceOpen) { toggleDropdown(editMenuBtn, editMenuDropdown, forceOpen); }
function toggleViewMenu(forceOpen) { toggleDropdown(viewMenuBtn, viewMenuDropdown, forceOpen); }
function toggleSettingsMenu(forceOpen) { toggleDropdown(settingsMenuBtn, settingsMenuDropdown, forceOpen); }
function toggleHelpMenu(forceOpen) { toggleDropdown(helpMenuBtn, helpMenuDropdown, forceOpen); }

const shellMenuToggles = { file: toggleFileMenu, edit: toggleEditMenu, view: toggleViewMenu, settings: toggleSettingsMenu, help: toggleHelpMenu };
const shellMenuDropdowns = { file: fileMenuDropdown, edit: editMenuDropdown, view: viewMenuDropdown, settings: settingsMenuDropdown, help: helpMenuDropdown };

function openShellMenu(type, forceOpen) {
  const toggle = shellMenuToggles[type];
  const dropdown = shellMenuDropdowns[type];
  if (!toggle || !dropdown) return;
  if (type === "file") updateFileMenuState();
  if (type === "edit") updateEditMenuState();
  if (type === "view") updateViewMenuState();
  if (type === "settings") shell.updateColorThemeMenuState?.();
  if (type === "help") updateHelpMenuState();
  const isOpen = dropdown.classList.contains("open");
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : !isOpen;
  closeAllShellMenus();
  if (shouldOpen && !hasVisibleMenuItems(dropdown)) return;
  if (shouldOpen) toggle(true);
}

export function closeAllShellMenus() {
  closeAllCascadeSubmenus();
  toggleFileMenu(false);
  toggleEditMenu(false);
  toggleViewMenu(false);
  toggleSettingsMenu(false);
  toggleHelpMenu(false);
  shell.closeTabCtxMenu?.();
  closeMacroContextMenus();
}

function setAboutVersionText(version) {
  const text = String(version || "").trim();
  if (aboutVersion && text) aboutVersion.textContent = `Version ${text}`;
}

async function refreshAboutVersion() {
  if (aboutVersionLoaded) return;
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.getAppInfo !== "function") return;
  try {
    const info = await hostApi.getAppInfo();
    setAboutVersionText(info?.displayVersion || info?.version);
    aboutVersionLoaded = true;
  } catch {
    // Keep the build-time version text if host app info is unavailable.
  }
}

function openAboutDialog() {
  void refreshAboutVersion();
  aboutOverlay?.classList.add("open");
}
function closeAboutDialog() { aboutOverlay?.classList.remove("open"); }
async function checkForUpdatesFromAbout() {
  if (aboutUpdateCheckRunning) return;
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.checkForUpdates !== "function") {
    shell.updateStatusBar?.("Update checks are available in the desktop app.");
    return;
  }

  aboutUpdateCheckRunning = true;
  const previousLabel = aboutCheckUpdatesBtn?.textContent || "Check for Updates";
  if (aboutCheckUpdatesBtn) {
    aboutCheckUpdatesBtn.disabled = true;
    aboutCheckUpdatesBtn.textContent = "Checking...";
  }
  shell.updateStatusBar?.("Checking for updates...");

  try {
    const result = await hostApi.checkForUpdates();
    const status = String(result?.status || "");
    if (status === "none") shell.updateStatusBar?.("Arco is up to date.");
    else if (status === "missing-checksum") shell.updateStatusBar?.("Newer installer found, but checksum is missing.");
    else if (status === "failed" || status === "unsupported" || status === "unavailable") shell.updateStatusBar?.("Update check unavailable.");
    else if (status === "launching") shell.updateStatusBar?.("Starting update installer...");
    else shell.updateStatusBar?.("Update check finished.");
  } catch {
    shell.updateStatusBar?.("Update check unavailable.");
  } finally {
    aboutUpdateCheckRunning = false;
    if (aboutCheckUpdatesBtn) {
      aboutCheckUpdatesBtn.disabled = false;
      aboutCheckUpdatesBtn.textContent = previousLabel;
    }
  }
}
export function setDfmEditEnabled(enabled) { dfmEditEnabled = !!enabled; updateEditMenuState(); }
export function setDfmHistoryEnabled({ canUndo = false, canRedo = false } = {}) {
  dfmUndoEnabled = !!canUndo;
  dfmRedoEnabled = !!canRedo;
  updateEditMenuState();
}
function getActiveTab() { return shell.state.tabs.find(t => t.id === shell.state.activeId) || null; }
function isStandaloneDFMTab(tab = getActiveTab()) { return !!tab && tab.type === "dfm"; }
function isProjectInstanceDfmActive(tab = getActiveTab()) { return !!tab && tab.type === "project_instance" && !!tab.piDfmActive; }
export function isActiveWorkflowTab() { const tab = getActiveTab(); return !!tab && tab.type === "workflow"; }
export function isActiveDatasetTab() { const tab = getActiveTab(); return !!tab && tab.type === "dataset"; }
export function isActiveDFMTab() { const tab = getActiveTab(); return isStandaloneDFMTab(tab) || isProjectInstanceDfmActive(tab); }
function getActiveDFMSubTab() {
  const tab = getActiveTab();
  if (isStandaloneDFMTab(tab)) return String(tab.dfmTab || "details").trim().toLowerCase();
  if (isProjectInstanceDfmActive(tab)) return String(tab.dfmTab || "ratios").trim().toLowerCase();
  return "";
}
export function isActiveDFMDetailsTab() { return isActiveDFMTab() && getActiveDFMSubTab() === "details"; }
export function isActiveScriptingTab() { const tab = getActiveTab(); return !!tab && tab.type === "scripting"; }
export function isActiveProjectInstanceTab() { const tab = getActiveTab(); return !!tab && tab.type === "project_instance"; }
function isActiveProjectSettingsTab() { const tab = getActiveTab(); return !!tab && tab.type === "project_settings"; }
function getActiveProjectSettingsRibbon() { const tab = getActiveTab(); return !tab || tab.type !== "project_settings" ? "" : String(tab.projectSettingsRibbon || "").trim().toLowerCase(); }
export function isActiveProjectSettingsDatasetTypesTab() { return isActiveProjectSettingsTab() && getActiveProjectSettingsRibbon() === "dataset-types"; }
export function isActiveProjectSettingsReservingClassTypesTab() { return isActiveProjectSettingsTab() && getActiveProjectSettingsRibbon() === "reserving-class-types"; }
function getActiveTabType() { const tab = getActiveTab(); return String(tab?.type || "").toLowerCase(); }

function parsePageScopes(raw) {
  if (!raw) return null;
  const scopes = String(raw).split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  return scopes.length ? scopes : null;
}
function applyScopedMenuVisibility(dropdown) {
  if (!dropdown) return;
  const activeType = getActiveTabType();
  const effectiveScopes = new Set(activeType ? [activeType] : []);
  if (isProjectInstanceDfmActive()) effectiveScopes.add("dfm");
  const requiresScope = dropdown.hasAttribute("data-requires-page-scope");
  dropdown.querySelectorAll(".menuItem").forEach((el) => {
    const scopes = parsePageScopes(el.getAttribute("data-page-scopes"));
    if (!scopes) { el.hidden = requiresScope; return; }
    if (scopes.includes("*")) { el.hidden = false; return; }
    el.hidden = !scopes.some((scope) => effectiveScopes.has(scope));
  });
}
function normalizeMenuSeparators(dropdown) {
  if (!dropdown) return;
  const children = Array.from(dropdown.children);
  children.forEach((el) => { if (el.classList.contains("menuSep")) el.hidden = false; });
  children.forEach((el) => {
    if (!el.classList.contains("menuSep")) return;
    let prev = el.previousElementSibling;
    while (prev && prev.hidden) prev = prev.previousElementSibling;
    let next = el.nextElementSibling;
    while (next && next.hidden) next = next.nextElementSibling;
    el.hidden = !(!!prev && prev.classList.contains("menuItem") && !!next && next.classList.contains("menuItem"));
  });
}
function hasVisibleMenuItems(dropdown) { return !!dropdown && Array.from(dropdown.querySelectorAll(".menuItem")).some((el) => !el.hidden); }

function getFilenameFromPath(pathLike) {
  const normalized = String(pathLike || "").replace(/\\/g, "/").trim();
  if (!normalized) return "";
  const parts = normalized.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : normalized;
}

function renderRecentNotebookSubmenu(paths = [], { loading = false } = {}) {
  if (!recentNotebookMenuItem || !recentNotebookSubmenu) return;
  recentNotebookSubmenu.innerHTML = "";
  const recentPaths = Array.isArray(paths) ? paths.slice(0, 5).map((p) => String(p || "").trim()).filter(Boolean) : [];
  recentNotebookMenuItem.classList.toggle("disabled", loading || recentPaths.length === 0);

  if (loading) {
    const item = document.createElement("div");
    item.className = "menuItem disabled";
    item.innerHTML = "<span>Loading...</span>";
    recentNotebookSubmenu.appendChild(item);
    return;
  }

  if (!recentPaths.length) {
    const item = document.createElement("div");
    item.className = "menuItem disabled";
    item.innerHTML = "<span>No recent notebooks</span>";
    recentNotebookSubmenu.appendChild(item);
    return;
  }

  recentPaths.forEach((notebookPath) => {
    const item = document.createElement("div");
    item.className = "menuItem";
    item.dataset.action = "open-recent-notebook";
    item.dataset.path = notebookPath;
    item.dataset.pageScopes = "scripting";

    const label = document.createElement("span");
    label.className = "menuPathLabel";
    label.textContent = getFilenameFromPath(notebookPath);
    label.title = notebookPath;
    item.appendChild(label);
    recentNotebookSubmenu.appendChild(item);
  });
}

function refreshRecentNotebookMenu() {
  if (!recentNotebookMenuItem || !recentNotebookSubmenu || !isActiveScriptingTab()) return;
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.loadRecentScriptingNotebooks !== "function") {
    renderRecentNotebookSubmenu([]);
    return;
  }
  const token = ++recentNotebookLoadToken;
  renderRecentNotebookSubmenu([], { loading: true });
  Promise.resolve(hostApi.loadRecentScriptingNotebooks())
    .then((result) => {
      if (token !== recentNotebookLoadToken) return;
      renderRecentNotebookSubmenu(result?.recentPaths || []);
    })
    .catch(() => {
      if (token !== recentNotebookLoadToken) return;
      renderRecentNotebookSubmenu([]);
    });
}

function updateFileSaveMenuLabels() {
  if (!fileMenuDropdown) return;
  const saveLabel = fileMenuDropdown.querySelector('.menuItem[data-action="save"] > span:not(.menuShortcut)');
  const saveAsLabel = fileMenuDropdown.querySelector('.menuItem[data-action="save-as"] > span:not(.menuShortcut)');
  const reservingClassTypesMode = isActiveProjectSettingsReservingClassTypesTab();
  const datasetTypesMode = isActiveProjectSettingsDatasetTypesTab();
  if (saveLabel) saveLabel.textContent = reservingClassTypesMode ? "Save Reserving Class Types As..." : datasetTypesMode ? "Save Dataset Types" : "Save";
  if (saveAsLabel) saveAsLabel.textContent = reservingClassTypesMode ? "Load Reserving Class Types From..." : datasetTypesMode ? "Load Dataset Types" : isActiveDFMDetailsTab() ? "Save as Template" : "Save As...";
}

export function updateFileMenuState() {
  if (!fileMenuDropdown) return;
  applyScopedMenuVisibility(fileMenuDropdown);
  updateFileSaveMenuLabels();
  refreshRecentNotebookMenu();
  const saveEnabled = isActiveWorkflowTab() || isActiveDatasetTab() || isActiveDFMTab() || isActiveProjectInstanceTab() || isActiveScriptingTab() || isActiveProjectSettingsReservingClassTypesTab() || isActiveProjectSettingsDatasetTypesTab();
  fileMenuDropdown.querySelectorAll(".menuItem").forEach((el) => {
    if (recentNotebookSubmenu?.contains(el)) return;
    if (el.hidden) { el.classList.remove("disabled"); return; }
    const action = el.getAttribute("data-action") || "";
    if (action === "recent-notebooks") return;
    const shouldDisable = (!saveEnabled && (action === "save" || action === "save-as")) || (action === "close-tab" && shell.state.activeId === "home");
    el.classList.toggle("disabled", shouldDisable);
  });
  normalizeMenuSeparators(fileMenuDropdown);
}

export function updateEditMenuState() {
  if (!editMenuDropdown) return;
  applyScopedMenuVisibility(editMenuDropdown);
  const isDfm = isActiveDFMTab();
  const isScripting = isActiveScriptingTab();
  const activeTab = getActiveTab();
  const editEnabled = isDfm && (isProjectInstanceDfmActive(activeTab) ? !!activeTab.dfmEditEnabled : dfmEditEnabled);
  const canUndo = isProjectInstanceDfmActive(activeTab) ? !!activeTab.dfmCanUndo : dfmUndoEnabled;
  const canRedo = isProjectInstanceDfmActive(activeTab) ? !!activeTab.dfmCanRedo : dfmRedoEnabled;
  editMenuDropdown.querySelectorAll(".menuItem").forEach((el) => {
    if (el.hidden) { el.classList.remove("disabled"); return; }
    const action = el.getAttribute("data-action") || "";
    const shouldDisable = action === "render-all-markdown"
      ? !isScripting
      : action === "dfm-undo"
        ? !isDfm || !canUndo
        : action === "dfm-redo"
          ? !isDfm || !canRedo
          : action === "dfm-include-all"
            ? !isDfm
            : !editEnabled;
    el.classList.toggle("disabled", shouldDisable);
  });
  normalizeMenuSeparators(editMenuDropdown);
}

export function updateViewMenuState() {
  if (!viewMenuDropdown) return;
  applyScopedMenuVisibility(viewMenuDropdown);
  const isWorkflow = isActiveWorkflowTab();
  const isScripting = isActiveScriptingTab();
  const aiBotIconLabel = viewMenuDropdown.querySelector('.menuItem[data-action="toggle-ai-bot-icon"] > span:not(.menuShortcut)');
  if (aiBotIconLabel) aiBotIconLabel.textContent = isAiAssistantLauncherVisible() ? "Hide AI Bot Icon" : "Show AI Bot Icon";
  const flightDeckLabel = viewMenuDropdown.querySelector('.menuItem[data-action="toggle-flight-deck"] > span:not(.menuShortcut)');
  if (flightDeckLabel) flightDeckLabel.textContent = isFlightDeckVisible() ? "Hide Flight Deck" : "Show Flight Deck";
  viewMenuDropdown.querySelectorAll(".menuItem").forEach((el) => {
    if (el.hidden) { el.classList.remove("disabled"); return; }
    const action = el.getAttribute("data-action") || "";
    const shouldDisable = (action === "toggle-nav" && !isWorkflow) || ((action === "toggle-line-numbers" || action === "toggle-exec-time") && !isScripting);
    el.classList.toggle("disabled", shouldDisable);
  });
  normalizeMenuSeparators(viewMenuDropdown);
}

export function updateHelpMenuState() {
  if (!helpMenuDropdown) return;
  applyScopedMenuVisibility(helpMenuDropdown);
  const activeTab = getActiveTab();
  const selectedProjectPath = String(activeTab?.projectInstanceState?.selectedPath || "").trim();
  const projectWindows = Array.isArray(activeTab?.projectInstanceState?.windows) ? activeTab.projectInstanceState.windows : [];
  const activeProjectWindow = projectWindows.find((item) => item?.active) || activeTab?.projectInstanceState?.activeWindow || null;
  const activeProjectWindowMethod = String(activeProjectWindow?.methodType || activeProjectWindow?.method_type || "").trim().toLowerCase();
  const activeProjectWindowKind = String(activeProjectWindow?.kind || "").trim().toLowerCase();
  const hasActiveProjectWindow = !!activeProjectWindow?.name;
  const hasActiveMethodJson = hasActiveProjectWindow && (
    activeProjectWindowKind === "dfm"
    || activeProjectWindowKind === "result_selection"
    || activeProjectWindowMethod === "dfm"
    || activeProjectWindowMethod === "result selection"
  );
  helpMenuDropdown.querySelectorAll(".menuItem").forEach((el) => {
    if (el.hidden) { el.classList.remove("disabled"); return; }
    const action = el.getAttribute("data-action") || "";
    const shouldDisable = (action === "reveal-project-instance-path" && !selectedProjectPath)
      || (action === "open-project-instance-dataset-sidecar" && !hasActiveProjectWindow)
      || (action === "open-project-instance-dataset-json" && !hasActiveMethodJson);
    el.classList.toggle("disabled", shouldDisable);
  });
  normalizeMenuSeparators(helpMenuDropdown);
}

export function sendWorkflowCommand(type) { const tab = shell.state.tabs.find(t => t.id === shell.state.activeId); if (!tab || tab.type !== "workflow") return; shell.ensureIframe?.(tab); try { tab.iframe?.contentWindow?.postMessage({ type }, "*"); } catch {} }
export function sendDFMCommand(type) {
  const tab = shell.state.tabs.find(t => t.id === shell.state.activeId);
  if (!tab) return;
  if (tab.type !== "dfm" && !isProjectInstanceDfmActive(tab)) return;
  shell.ensureIframe?.(tab);
  try { tab.iframe?.contentWindow?.postMessage({ type }, "*"); } catch {}
}
export function sendDatasetCommand(type) { const tab = shell.state.tabs.find(t => t.id === shell.state.activeId); if (!tab || tab.type !== "dataset") return; shell.ensureIframe?.(tab); try { tab.iframe?.contentWindow?.postMessage({ type }, "*"); } catch {} }
export function sendProjectInstanceCommand(type) { const tab = shell.state.tabs.find(t => t.id === shell.state.activeId); if (!tab || tab.type !== "project_instance") return; shell.ensureIframe?.(tab); try { tab.iframe?.contentWindow?.postMessage({ type }, "*"); } catch {} }
export function sendScriptingCommand(type) {
  const tab = shell.state.tabs.find(t => t.id === shell.state.activeId);
  if (!tab || tab.type !== "scripting") return;
  shell.ensureIframe?.(tab);
  const messageType = String(type || "").replace(/^arcrho:scripting-/, "arcode:scripting-");
  try { tab.iframe?.contentWindow?.postMessage({ type: messageType }, "*"); } catch {}
}
export function sendProjectSettingsCommand(type) { const tab = shell.state.tabs.find(t => t.id === shell.state.activeId); if (!tab || tab.type !== "project_settings") return; shell.ensureIframe?.(tab); try { tab.iframe?.contentWindow?.postMessage({ type }, "*"); } catch {} }
export function toggleNavigationPanel() { sendWorkflowCommand("arcrho:workflow-toggle-nav"); }
export async function openDevPanel() {
  const hostApi = shell.getHostApi?.();
  if (typeof hostApi?.toggleDevPanel !== "function") {
    shell.updateStatusBar?.("Dev panel is available in the desktop app.");
    return;
  }
  try {
    await hostApi.toggleDevPanel();
    shell.updateStatusBar?.("Dev panel toggled.");
  } catch {
    shell.updateStatusBar?.("Unable to open dev panel.");
  }
}

export function initShellMenus() {
  if (shellMenusWired) return;
  shellMenusWired = true;
  initCascadeMenus();
  window.ArcRhoColorTheme?.wireThemeMenus?.();
  void refreshAboutVersion();
  window.addEventListener("adaHostReady", () => {
    aboutVersionLoaded = false;
    void refreshAboutVersion();
  });
  aboutCheckUpdatesBtn?.addEventListener("click", checkForUpdatesFromAbout);
  aboutReleaseHistoryBtn?.addEventListener("click", () => {
    closeAboutDialog();
    void openReleaseHistory();
  });
  initReleaseNotesDialog();
  aboutOverlay?.addEventListener("click", (e) => { if (e.target === aboutOverlay) closeAboutDialog(); });
  menuBarEl?.addEventListener("click", (e) => {
    const btn = e.target?.closest?.(".menu[data-menu]");
    if (!btn) return;
    const type = btn.getAttribute("data-menu") || "";
    if (type === "about") { closeAllShellMenus(); openAboutDialog(); return; }
    if (type === "macro") { closeAllShellMenus(); void openMacroWindow(); return; }
    if (!shellMenuToggles[type]) { closeAllShellMenus(); return; }
    e.stopPropagation();
    openShellMenu(type);
  });
  fileMenuDropdown?.addEventListener("click", (e) => {
    const item = e.target?.closest?.(".menuItem");
    const action = item?.getAttribute("data-action");
    if (!action || item.classList.contains("disabled")) return;
    if (action === "recent-notebooks") return;
    toggleFileMenu(false);
    if (action === "save-workflow") { shell.updateStatusBar?.("Saving..."); sendWorkflowCommand("arcrho:workflow-save"); }
    else if (action === "save-workflow-as") { shell.updateStatusBar?.("Saving as..."); sendWorkflowCommand("arcrho:workflow-save-as"); }
    else if (action === "open-notebook") { shell.updateStatusBar?.("Opening notebook..."); sendScriptingCommand("arcrho:scripting-open"); }
    else if (action === "open-recent-notebook") {
      const notebookPath = String(item.dataset.path || "").trim();
      if (notebookPath) {
        shell.updateStatusBar?.(`Opening ${getFilenameFromPath(notebookPath)}...`);
        shell.openScriptingTab?.({ forceNew: true, notebookPath });
      }
    }
    else if (action === "save") {
      if (isActiveWorkflowTab()) { shell.updateStatusBar?.("Saving..."); sendWorkflowCommand("arcrho:workflow-save"); }
      else if (isActiveDatasetTab()) { shell.updateStatusBar?.("Saving dataset..."); sendDatasetCommand("arcrho:dataset-save"); }
      else if (isActiveDFMTab()) { shell.updateStatusBar?.("Saving..."); sendDFMCommand("arcrho:dfm-save"); }
      else if (isActiveProjectInstanceTab()) { shell.updateStatusBar?.("Saving..."); sendProjectInstanceCommand("arcrho:dfm-save"); }
      else if (isActiveScriptingTab()) { shell.updateStatusBar?.("Saving..."); sendScriptingCommand("arcrho:scripting-save"); }
      else if (isActiveProjectSettingsReservingClassTypesTab()) { shell.updateStatusBar?.("Saving reserving class types to local file..."); sendProjectSettingsCommand("arcrho:project-settings-reserving-class-types-save-local"); }
      else if (isActiveProjectSettingsDatasetTypesTab()) { shell.updateStatusBar?.("Saving dataset types to local file..."); sendProjectSettingsCommand("arcrho:project-settings-dataset-types-save-local"); }
    } else if (action === "save-as") {
      if (isActiveWorkflowTab()) { shell.updateStatusBar?.("Saving as..."); sendWorkflowCommand("arcrho:workflow-save-as"); }
      else if (isActiveDatasetTab()) { shell.updateStatusBar?.("Saving dataset..."); sendDatasetCommand("arcrho:dataset-save"); }
      else if (isActiveDFMTab()) { shell.updateStatusBar?.(isActiveDFMDetailsTab() ? "Saving template..." : "Saving as..."); sendDFMCommand(isActiveDFMDetailsTab() ? "arcrho:dfm-save-template" : "arcrho:dfm-save-as"); }
      else if (isActiveProjectInstanceTab()) { shell.updateStatusBar?.("Saving as..."); sendProjectInstanceCommand("arcrho:dfm-save-as"); }
      else if (isActiveScriptingTab()) { shell.updateStatusBar?.("Saving as..."); sendScriptingCommand("arcrho:scripting-save-as"); }
      else if (isActiveProjectSettingsReservingClassTypesTab()) { shell.updateStatusBar?.("Loading reserving class types from local file..."); sendProjectSettingsCommand("arcrho:project-settings-reserving-class-types-load-local"); }
      else if (isActiveProjectSettingsDatasetTypesTab()) { shell.updateStatusBar?.("Loading dataset types from local file..."); sendProjectSettingsCommand("arcrho:project-settings-dataset-types-load-local"); }
    } else if (action === "import-workflow") shell.importWorkflow?.();
    else if (action === "close-tab") shell.closeTab?.(shell.state.activeId);
    else if (action === "print") shell.printActiveTab?.();
    else if (action === "restart-app") shell.restartApplication?.();
    else if (action === "shutdown-app") shell.shutdownApplication?.();
  });
  viewMenuDropdown?.addEventListener("click", (e) => {
    const item = e.target?.closest?.(".menuItem");
    const action = item?.getAttribute("data-action");
    if (!action || item.classList.contains("disabled")) return;
    toggleViewMenu(false);
    if (action === "toggle-flight-deck") {
      toggleFlightDeck();
    } else if (action === "toggle-ai-bot-icon") {
      const visible = toggleAiAssistantLauncherVisible();
      shell.updateStatusBar?.(`AI bot icon ${visible ? "shown" : "hidden"}.`);
    } else if (action === "toggle-nav") {
      toggleNavigationPanel();
    } else if (action === "toggle-line-numbers") {
      sendScriptingCommand("arcrho:scripting-toggle-line-numbers");
    } else if (action === "toggle-exec-time") {
      sendScriptingCommand("arcrho:scripting-toggle-exec-time");
    }
  });
  settingsMenuDropdown?.addEventListener("click", (e) => { const item = e.target?.closest?.(".menuItem"); const action = item?.getAttribute("data-action"); if (!action) return; toggleSettingsMenu(false); const theme = item?.getAttribute("data-color-theme-value"); if (theme) { shell.setColorTheme?.(theme); const label = item.querySelector?.("span")?.textContent?.trim() || theme; shell.updateStatusBar?.(`Color theme changed to ${label}.`); } else if (action === "font-settings") shell.openFontSettingsModal?.(); else if (action === "root-path-settings") shell.openRootPathSettingsModal?.(); else if (action === "force-rebuild-settings") shell.openForceRebuildSettingsModal?.(); else if (action === "refresh-page") shell.refreshActiveTab?.(); else if (action === "clear-cache-reload") Promise.resolve(shell.clearCacheAndReload?.()).catch((err) => { console.error("Clear Cache & Reload failed:", err); shell.updateStatusBar?.("Clear Cache & Reload failed."); }); });
  helpMenuDropdown?.addEventListener("click", (e) => { const item = e.target?.closest?.(".menuItem"); const action = item?.getAttribute("data-action"); if (!action || item.classList.contains("disabled")) return; toggleHelpMenu(false); if (action === "user-guide") void openUserGuide({ hostApi: shell.getHostApi?.(), updateStatus: shell.updateStatusBar }); else if (action === "view-dev-panel") openDevPanel(); else if (action === "reveal-project-instance-path") { shell.updateStatusBar?.("Opening reserving-class folder..."); sendProjectInstanceCommand("arcrho:project-instance-reveal-selected-path"); } else if (action === "open-project-instance-dataset-json") { shell.updateStatusBar?.("Opening dataset JSON file..."); sendProjectInstanceCommand("arcrho:project-instance-open-active-dataset-json"); } else if (action === "open-project-instance-dataset-sidecar") { shell.updateStatusBar?.("Opening dataset sidecar..."); sendProjectInstanceCommand("arcrho:project-instance-open-active-dataset-sidecar"); } else if (action === "open-dfm-json") { shell.updateStatusBar?.("Opening DFM JSON..."); sendDFMCommand("arcrho:dfm-open-method-json"); } });
  editMenuDropdown?.addEventListener("click", (e) => { const item = e.target?.closest?.(".menuItem"); const action = item?.getAttribute("data-action"); if (!action || item.classList.contains("disabled")) return; toggleEditMenu(false); if (action === "dfm-undo") sendDFMCommand("arcrho:dfm-undo"); else if (action === "dfm-redo") sendDFMCommand("arcrho:dfm-redo"); else if (action === "dfm-exclude-high") sendDFMCommand("arcrho:dfm-exclude-high"); else if (action === "dfm-exclude-low") sendDFMCommand("arcrho:dfm-exclude-low"); else if (action === "dfm-include-all") sendDFMCommand("arcrho:dfm-include-all"); else if (action === "render-all-markdown") sendScriptingCommand("arcrho:scripting-render-all-markdown"); });
  document.addEventListener("pointerdown", (e) => { const hit = e.target?.closest?.(".menu, .menuDropdown, #tabCtxMenu, .macroSplitContextMenu, .macroItemContextMenu"); if (!hit) closeAllShellMenus(); }, true);
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (isMacroContextMenuOpen()) {
      closeMacroContextMenus();
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
      return;
    }
    closeAllShellMenus();
  }, true);
  window.addEventListener("resize", () => { if (fileMenuDropdown?.classList.contains("open")) positionDropdown(fileMenuBtn, fileMenuDropdown); if (editMenuDropdown?.classList.contains("open")) positionDropdown(editMenuBtn, editMenuDropdown); if (viewMenuDropdown?.classList.contains("open")) positionDropdown(viewMenuBtn, viewMenuDropdown); if (settingsMenuDropdown?.classList.contains("open")) positionDropdown(settingsMenuBtn, settingsMenuDropdown); if (helpMenuDropdown?.classList.contains("open")) positionDropdown(helpMenuBtn, helpMenuDropdown); shell.clampFloatingTabsToContent?.(); });
}
