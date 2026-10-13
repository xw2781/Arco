import { getHostApi, registerShellApi } from "./shell_context.js?v=20260510a";
import { buildShellStateSnapshot, ensureActiveTabInvariant, getFirstDockedTabId, loadState, persistShellStateSnapshot, saveState, state } from "./shell_state.js?v=20260808a";
import { applyAppFont, applyZoom, adjustZoomByDelta, broadcastAppFont, broadcastColorTheme, broadcastZoomToIframes, closeFontSettingsModal, closeForceRebuildSettingsModal, getColorTheme, getForceRebuildEnabled, getZoomPercent, hideGlobalTooltip, hostZoomAvailable, initFontSettingsModal, initForceRebuildSettingsModal, initShellPreferences, initZoomControls, loadAppFont, loadColorTheme, openFontSettingsModal, openForceRebuildSettingsModal, setColorTheme, setForceRebuildEnabled, setZoomPercent, showGlobalTooltip, updateColorThemeMenuState, ZOOM_STEP } from "./shell_preferences.js?v=20260731a";
import { clearSavedStatusOnDirty, formatStatusTimestamp, getStatusBarHeight, initClock, initStatusSignIn, updateStatusBar } from "./status_bar.js?v=20260927a";
import { closeRootPathSettingsModal, initRootPathSettingsModal, openRootPathSettingsModal } from "./root_path_settings.js?v=20260927a";
import { clearCacheAndReload, customHardRefresh, initAppLifecycle, refreshActiveTab, restartApplication, sendShutdownSignal, showAppConfirm, shutdownApplication } from "./app_lifecycle.js?v=20260930a";
import { clearTestData, getLastWorkflowDir, getLastWorkflowPath, getWorkflowTabState, importWorkflow, postToWorkflowTab, setLastWorkflowPath } from "./workflow_host_actions.js?v=20260510a";
import { buildShellActivityEntry, closeTab, closeTabsExcept, dockTab, floatTab, openAgentGuideTab, openBornhuetterFergusonTab, openBrowsingHistoryTab, openDatasetTab, openDFMTab, openFileExplorerTab, openProjectInstanceTab, openProjectSettingsTab, openResultSelectionTab, openScriptingTab, openServerTab, openShellActivityHistoryEntry, openTaskDesigner, openWorkflowTab, recordActiveTabHistory, setActive, setDockedActive } from "./tab_actions.js?v=20260926a";
import { applyDockedIframeLayout, clampFloatingTabsToContent, clampFloatRect, defaultFloatRectFromPointer, ensureContentContainers, ensureIframe, notifyBrowsingHistoryTabs, notifyCalculatedDatasetTabs, notifyServerConnectionUpdated, notifyTabActivated, printActiveTab, removeFloatPreview, renderContent, renderFloatingWindows, updateFloatPreview } from "./shell_content.js?v=20260926a";
import { closeTabCtxMenu, initTabStrip, isTabStripDragging, openTabCtxMenu, renderTabs } from "./tab_strip.js?v=20260821a";
import { closeAllShellMenus, initShellMenus, isActiveDatasetTab, isActiveDFMDetailsTab, isActiveDFMTab, isActiveProjectInstanceTab, isActiveProjectSettingsDatasetTypesTab, isActiveProjectSettingsReservingClassTypesTab, isActiveScriptingTab, isActiveWorkflowTab, openDevPanel, sendDatasetCommand, sendDFMCommand, sendProjectInstanceCommand, sendProjectSettingsCommand, sendScriptingCommand, sendWorkflowCommand, setDfmEditEnabled, setDfmHistoryEnabled, toggleNavigationPanel, updateEditMenuState, updateFileMenuState, updateHelpMenuState, updateViewMenuState } from "./shell_menus.js?v=20260927smb24";
import { initHotkeys, resolveHotkeyAction, runHotkeyAction } from "./shell_hotkeys.js?v=20260831a";
import { initShellMessages } from "./shell_messages.js?v=20260929smb";
import { initUiAutomation } from "./ui_automation.js?v=20260904resize2";
import { handleShellFileDragOver, handleShellFileDrop, initShellFileDrops } from "./shell_file_drop.js?v=20260920a";
import { initTitlebarControls } from "./titlebar_controls.js?v=20260517a";
import { initServerBadge } from "./server_badge.js?v=20260927b";
import { initFullscreenChrome, setFullscreenChrome, syncFullscreenChromeFromHost } from "./fullscreen_chrome.js?v=20260913b";
import { initAiAssistant } from "../ai-assistant/arcrho.js?v=20260927smb24";
import { closeMacroWindow, initMacroWindow, openMacroWindow } from "../macro/macro_window.js?v=20260908b";
import { addMacroToFlightDeck, closeFlightDeck, initFlightDeck, isFlightDeckVisible, openFlightDeck, toggleFlightDeck } from "../flight_deck/flight_deck.js?v=20260906a";

const UI_VERSION_PARAM = new URLSearchParams(window.location.search).get("v") || String(Date.now());
const CLEAR_CACHE_RESTORE_KIND = "arcrho-clear-cache-reload-restore-v1";

function render() {
  if (isTabStripDragging()) return;
  renderTabs();
  renderContent();
  updateFileMenuState();
  updateEditMenuState();
  updateViewMenuState();
  updateHelpMenuState();
  saveState();
}

function wire() {
  initZoomControls();
  initFontSettingsModal();
  initRootPathSettingsModal();
  initForceRebuildSettingsModal();
  initShellMenus();
  initTabStrip();
  initShellMessages();
  initUiAutomation();
  initShellFileDrops();
  initHotkeys();
  initFullscreenChrome();
  initAppLifecycle();
  initAiAssistant();
  void initServerBadge();
  void initMacroWindow();
  void initFlightDeck();
}

registerShellApi({
  ZOOM_STEP,
  addMacroToFlightDeck,
  adjustZoomByDelta,
  applyAppFont,
  applyDockedIframeLayout,
  applyZoom,
  broadcastAppFont,
  broadcastColorTheme,
  broadcastZoomToIframes,
  buildShellActivityEntry,
  buildShellStateSnapshot,
  clampFloatingTabsToContent,
  clampFloatRect,
  clearCacheAndReload,
  clearSavedStatusOnDirty,
  clearTestData,
  closeAllShellMenus,
  closeFlightDeck,
  closeFontSettingsModal,
  closeForceRebuildSettingsModal,
  closeMacroWindow,
  closeRootPathSettingsModal,
  closeTab,
  closeTabCtxMenu,
  closeTabsExcept,
  customHardRefresh,
  defaultFloatRectFromPointer,
  dockTab,
  ensureActiveTabInvariant,
  ensureContentContainers,
  ensureIframe,
  floatTab,
  formatStatusTimestamp,
  getColorTheme,
  getFirstDockedTabId,
  getForceRebuildEnabled,
  getHostApi,
  getLastWorkflowDir,
  getLastWorkflowPath,
  getStatusBarHeight,
  getWorkflowTabState,
  getZoomPercent,
  handleShellFileDragOver,
  handleShellFileDrop,
  hideGlobalTooltip,
  hostZoomAvailable,
  importWorkflow,
  isActiveDatasetTab,
  isActiveDFMDetailsTab,
  isActiveDFMTab,
  isActiveProjectInstanceTab,
  isActiveProjectSettingsDatasetTypesTab,
  isActiveProjectSettingsReservingClassTypesTab,
  isActiveScriptingTab,
  isActiveWorkflowTab,
  isFlightDeckVisible,
  loadAppFont,
  loadColorTheme,
  loadState,
  notifyBrowsingHistoryTabs,
  notifyCalculatedDatasetTabs,
  notifyServerConnectionUpdated,
  notifyTabActivated,
  openBrowsingHistoryTab,
  openAgentGuideTab,
  openBornhuetterFergusonTab,
  openDatasetTab,
  openDFMTab,
  openFileExplorerTab,
  openDevPanel,
  openFlightDeck,
  openFontSettingsModal,
  openForceRebuildSettingsModal,
  openMacroWindow,
  openTaskDesigner,
  openProjectSettingsTab,
  openShellActivityHistoryEntry,
  openProjectInstanceTab,
  openResultSelectionTab,
  openRootPathSettingsModal,
  openTabCtxMenu,
  openScriptingTab,
  openServerTab,
  openWorkflowTab,
  postToWorkflowTab,
  printActiveTab,
  recordActiveTabHistory,
  refreshActiveTab,
  resolveHotkeyAction,
  removeFloatPreview,
  render,
  renderContent,
  renderFloatingWindows,
  renderTabs,
  restartApplication,
  runHotkeyAction,
  saveState,
  sendDatasetCommand,
  sendDFMCommand,
  sendProjectInstanceCommand,
  sendProjectSettingsCommand,
  sendScriptingCommand,
  sendShutdownSignal,
  sendWorkflowCommand,
  setActive,
  setColorTheme,
  setDfmEditEnabled,
  setDfmHistoryEnabled,
  setDockedActive,
  setForceRebuildEnabled,
  setFullscreenChrome,
  setLastWorkflowPath,
  setZoomPercent,
  showAppConfirm,
  showGlobalTooltip,
  shutdownApplication,
  state,
  toggleFlightDeck,
  toggleNavigationPanel,
  uiVersionParam: UI_VERSION_PARAM,
  updateEditMenuState,
  updateColorThemeMenuState,
  updateFileMenuState,
  updateHelpMenuState,
  updateFloatPreview,
  updateStatusBar,
  updateViewMenuState,
});

async function restoreShellStateAfterClearCacheReload() {
  const hostApi = getHostApi();
  if (typeof hostApi?.consumeClearCacheReloadRestore !== "function") return false;
  try {
    const payload = await hostApi.consumeClearCacheReloadRestore();
    if (payload?.kind !== CLEAR_CACHE_RESTORE_KIND) return false;
    return persistShellStateSnapshot(payload.shellState || null);
  } catch {
    return false;
  }
}

async function bootShell() {
  initShellPreferences();
  await restoreShellStateAfterClearCacheReload();
  loadState();
  ensureContentContainers();
  wire();
  render();

  if (getHostApi()) initTitlebarControls();
  window.addEventListener("adaHostReady", () => {
    initTitlebarControls();
    void syncFullscreenChromeFromHost();
  });
  initClock();
  initStatusSignIn();
}

void bootShell();
