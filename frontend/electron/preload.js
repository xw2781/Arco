const { contextBridge, ipcRenderer, webUtils } = require("electron");

const invoke = (channel, payload) => ipcRenderer.invoke(channel, payload);

// Splash screen progress API
contextBridge.exposeInMainWorld("electronAPI", {
  onSplashProgress: (callback) => {
    ipcRenderer.on("splash-progress", (_event, data) => callback(data));
  },
});

contextBridge.exposeInMainWorld("ADAHost", {
  windowsFrameStyle: () => invoke("windows-frame-style"),
  getWindowsUserName: () => invoke("get-windows-user-name"),
  pickOpenWorkflowFile: (startDir) => invoke("pick-open-workflow", { startDir }),
  pickOpenTableFile: (startDir) => invoke("pick-open-table-file", { startDir }),
  pickFolder: (startDir) => invoke("pick-folder", { startDir }),
  findArcRhoServerRoot: () => invoke("find-arcrho-server-root"),
  pickSaveWorkflowFile: (suggestedName, startDir) =>
    invoke("pick-save-workflow", { suggestedName, startDir }),
  shutdownApp: () => invoke("app-shutdown"),
  getSharedWindowCount: () => invoke("app-shared-window-count"),
  getAppInfo: () => invoke("app-info"),
  checkForUpdates: () => invoke("app-check-for-update"),
  getReleaseHistory: () => invoke("app-release-history"),
  toggleDevPanel: () => invoke("app-toggle-dev-panel"),
  minimizeWindow: () => invoke("window-minimize"),
  maximizeWindow: () => invoke("window-maximize"),
  restoreWindow: () => invoke("window-restore-native"),
  closeWindow: () => invoke("window-close"),
  isMaximized: () => invoke("window-is-maximized"),
  isFullscreen: () => invoke("window-is-fullscreen"),
  setFullscreen: (enabled) => invoke("window-set-fullscreen", { enabled }),
  exitFullscreenToLast: () => invoke("window-restore-to-last"),
  getWindowSize: () => invoke("window-get-size"),
  resizeWindow: (width, height) => invoke("window-resize", { width, height }),
  isPseudoMaximized: () => invoke("window-is-pseudo-maximized"),
  pseudoMaximize: (margin) => invoke("window-pseudo-maximize", { margin }),
  restoreToLast: () => invoke("window-restore-to-last"),
  getZoomFactor: () => invoke("zoom-get"),
  setZoomFactor: (factor) => invoke("zoom-set", { factor }),
  setWindowBackgroundColor: (color) => invoke("window-set-background-color", { color }),
  loadColorThemePreference: () => invoke("color-theme-preference-load"),
  saveColorThemePreference: (theme) => invoke("color-theme-preference-save", { theme }),
  loadTableStylePreference: () => invoke("table-style-preference-load"),
  saveTableStylePreference: (tableStyle) => invoke("table-style-preference-save", { tableStyle }),
  getDocumentsPath: () => invoke("get-documents-path"),
  loadHomeFolderPreferences: () => invoke("home-folders-preferences-load"),
  saveHomeFolderPreferences: (preferences) => invoke("home-folders-preferences-save", { preferences }),
  loadMacroPreferences: () => invoke("macro-preferences-load"),
  saveMacroPreferences: (preferences) => invoke("macro-preferences-save", { preferences }),
  loadFlightDeckPreferences: () => invoke("flight-deck-preferences-load"),
  saveFlightDeckPreferences: (preferences) => invoke("flight-deck-preferences-save", { preferences }),
  loadNotesPanelPreferences: () => invoke("notes-panel-preferences-load"),
  saveNotesPanelPreferences: (preferences) => invoke("notes-panel-preferences-save", { preferences }),
  loadTableColorPreferences: () => invoke("table-colors-preferences-load"),
  saveTableColorPreferences: (preferences) => invoke("table-colors-preferences-save", { preferences }),
  loadRecentSettingsFilePreferences: () => invoke("recent-settings-files-preferences-load"),
  saveRecentSettingsFilePreferences: (preferences) => invoke("recent-settings-files-preferences-save", { preferences }),
  saveJsonFile: (payload) => invoke("save-json-file", payload),
  formatPersistedJsonText: (payload) => invoke("format-persisted-json-text", payload),
  saveTextFile: (payload) => invoke("save-text-file", payload),
  readTextFile: (payload) => invoke("read-text-file", payload),
  readJsonFile: (payload) => invoke("read-json-file", payload),
  getFileRevision: (payload) => invoke("get-file-revision", payload),
  renameFile: (payload) => invoke("rename-file", payload),
  createDfmRatioUndoSession: (payload) => invoke("dfm-ratio-undo-session-create", payload),
  saveDfmRatioUndoStep: (payload) => invoke("dfm-ratio-undo-step-save", payload),
  clearDfmRatioUndoSession: (payload) => invoke("dfm-ratio-undo-session-clear", payload),
  getPathForFile: (file) => {
    try {
      if (webUtils && typeof webUtils.getPathForFile === "function") {
        return webUtils.getPathForFile(file) || "";
      }
    } catch {
      // ignore
    }
    return file && typeof file.path === "string" ? file.path : "";
  },
  loadLastScriptingNotebook: () => invoke("scripting-last-notebook-load"),
  loadRecentScriptingNotebooks: () => invoke("scripting-recent-notebooks-load"),
  saveLastScriptingNotebook: (path) => invoke("scripting-last-notebook-save", { path }),
  loadArcodeUserSettings: () => invoke("arcode-user-settings-load"),
  saveArcodeUserSettings: (settings) => invoke("arcode-user-settings-save", { settings }),
  loadScriptingShortcuts: () => invoke("scripting-shortcuts-load"),
  saveScriptingShortcuts: (bindings) => invoke("scripting-shortcuts-save", { bindings }),
  openArcodeWindow: (payload) => invoke("arcode-window-open", payload),
  pickOpenFile: (payload) => invoke("pick-open-file", payload),
  listFolder: (payload) => invoke("arcode-list-folder", payload),
  startArcodeFolderWatch: (payload) => invoke("arcode-folder-watch-start", payload),
  stopArcodeFolderWatch: (payload) => invoke("arcode-folder-watch-stop", payload),
  onArcodeFolderChanged: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("arcode-folder-changed", listener);
    return () => ipcRenderer.removeListener("arcode-folder-changed", listener);
  },
  openPath: (payload) => invoke("open-path", payload),
  openExternalUrl: (payload) => invoke("open-external-url", payload),
  showItemInFolder: (payload) => invoke("show-item-in-folder", payload),
  openTerminal: (payload) => invoke("open-terminal", payload),
  codexAssistantStatus: () => invoke("codex-assistant-status"),
  codexAssistantPrepare: (payload) => invoke("codex-assistant-prepare", payload),
  codexAssistantRelease: () => invoke("codex-assistant-release"),
  arcBotVoiceStart: (requestId) => invoke("arcbot-voice-start", { requestId }),
  arcBotVoiceStop: () => invoke("arcbot-voice-stop"),
  onArcBotVoice: (callback) => {
    const handler = (_event, value) => callback(value);
    ipcRenderer.on("arcbot-voice-event", handler);
    return () => ipcRenderer.removeListener("arcbot-voice-event", handler);
  },
  codexAssistantModels: (payload) => invoke("codex-assistant-models", payload),
  codexAssistantInstall: () => invoke("codex-assistant-install"),
  codexAssistantLogin: (payload) => invoke("codex-assistant-login", payload),
  codexAssistantListAccounts: () => invoke("codex-assistant-accounts-list"),
  codexAssistantCreateAccount: (provider, label) => invoke("codex-assistant-account-create", { provider, label }),
  codexAssistantActivateAccount: (provider, accountId) =>
    invoke("codex-assistant-account-activate", { provider, accountId }),
  codexAssistantSignOutAccount: (accountId) => invoke("codex-assistant-account-logout", { accountId }),
  codexAssistantRemoveAccount: (accountId) => invoke("codex-assistant-account-remove", { accountId }),
  codexAssistantLoadPromptGuide: () => invoke("codex-assistant-prompt-guide-load"),
  codexAssistantListSkills: () => invoke("codex-assistant-skills-list"),
  codexAssistantLoadUiSettings: () => invoke("codex-assistant-ui-settings-load"),
  codexAssistantSaveUiSettings: (settings) => invoke("codex-assistant-ui-settings-save", { settings }),
  codexAssistantLoadReadableRoots: () => invoke("codex-assistant-readable-roots-load"),
  codexAssistantSaveReadableRoots: (folders) => invoke("codex-assistant-readable-roots-save", { folders }),
  codexAssistantListSessions: (payload) => invoke("codex-assistant-sessions-list", payload),
  codexAssistantCreateSession: (payload) => invoke("codex-assistant-session-create", payload),
  codexAssistantLoadSession: (sessionId) => invoke("codex-assistant-session-load", { sessionId }),
  codexAssistantSaveSession: (session) => invoke("codex-assistant-session-save", { session }),
  codexAssistantArchiveSession: (sessionId, archived = true) =>
    invoke("codex-assistant-session-archive", { sessionId, archived }),
  codexAssistantDeleteSession: (sessionId) => invoke("codex-assistant-session-delete", { sessionId }),
  codexAssistantSend: (payload) => invoke("codex-assistant-send", payload),
  codexAssistantCancel: (requestId) => invoke("codex-assistant-cancel", { requestId }),
  onCodexAssistantEvent: (callback) => {
    if (typeof callback !== "function") return () => {};
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("codex-assistant-event", listener);
    return () => ipcRenderer.removeListener("codex-assistant-event", listener);
  },
  clearAppCache: (payload) => invoke("app-clear-cache", payload),
  clearCacheAndReload: (payload) => invoke("app-clear-cache-reload", payload),
  consumeClearCacheReloadRestore: () => invoke("app-consume-clear-cache-reload-restore"),
  focusWindow: () => invoke("focus-window"),
  automationListWindows: () => invoke("automation-window-list"),
  automationCapturePage: (payload) => invoke("automation-capture-page", payload),
  automationSendInput: (payload) => invoke("automation-send-input", payload),
  automationFocusWindow: (payload) => invoke("automation-window-focus", payload),
});

window.addEventListener("DOMContentLoaded", () => {
  try {
    window.dispatchEvent(new Event("adaHostReady"));
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:close-active-tab", () => {
  try {
    window.postMessage({ type: "arcrho:close-active-tab" }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:close-active-tab", () => {
  try {
    window.postMessage({ type: "arcode:close-active-tab" }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:hotkey", (_event, payload) => {
  try {
    window.postMessage({ type: "arcrho:hotkey", action: payload?.action }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:hotkey", (_event, payload) => {
  try {
    window.postMessage({ type: "arcode:hotkey", action: payload?.action }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:fullscreen-change", (_event, payload) => {
  try {
    window.postMessage({ type: "arcrho:fullscreen-change", fullscreen: !!payload?.fullscreen }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:fullscreen-change", (_event, payload) => {
  try {
    window.postMessage({ type: "arcode:fullscreen-change", fullscreen: !!payload?.fullscreen }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:zoom", (_event, payload) => {
  try {
    window.postMessage({ type: "arcrho:zoom", deltaY: payload?.deltaY }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:zoom", (_event, payload) => {
  try {
    window.postMessage({ type: "arcode:zoom", deltaY: payload?.deltaY }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:open-file", (_event, payload) => {
  try {
    window.postMessage({ type: "arcode:open-file", path: payload?.path || "", dfmMethod: payload?.dfmMethod || null, projectJson: payload?.projectJson || null }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:zoom-step", (_event, payload) => {
  try {
    window.postMessage({ type: "arcrho:zoom-step", delta: payload?.delta }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:zoom-step", (_event, payload) => {
  try {
    window.postMessage({ type: "arcode:zoom-step", delta: payload?.delta }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcrho:zoom-reset", () => {
  try {
    window.postMessage({ type: "arcrho:zoom-reset" }, "*");
  } catch {
    // ignore
  }
});

ipcRenderer.on("arcode:zoom-reset", () => {
  try {
    window.postMessage({ type: "arcode:zoom-reset" }, "*");
  } catch {
    // ignore
  }
});
