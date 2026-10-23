const { app, BrowserWindow, dialog, globalShortcut, ipcMain, screen, shell } = require("electron");
const path = require("path");
const { spawn, execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
const crypto = require("crypto");
const { registerArcBotIpc } = require("./arcbot_host");
const { registerUiAutomationIpc } = require("./ui_automation_host");
const { createAgentWindowControl } = require("./agent_control/agent_control_host");
const {
  appendElectronLog,
  getElectronLogPath,
  formatJsonForSave,
} = require("./host_support");
const {
  initUpdateChecker,
  checkForUpdate,
  checkForStartupUpdate,
  cleanupCompletedUpdateInstaller,
  readLocalReleaseHistory,
} = require("./update_checker");
const {
  initBackendLifecycle,
  getBackendPort,
  startBackendWithRetry,
  requestBackendShutdown,
  getSharedBackendClientCount,
  stopBackendForUpdate,
  registerBackendClient,
  unregisterBackendClient,
  cleanupBackendEndpoint,
} = require("./backend_lifecycle");
const { createBackendLaunchToken } = require("./backend_health_compatibility");
const { publishAppEntry, unpublishAppEntry } = require("./backend_port");

// Which Windows frame the renderer draws: "win11" (build >= 22000), "win10", or "" off
// Windows, where the app draws no frame of its own.
function windowsFrameStyle() {
  if (process.platform !== "win32") return "";
  const release = os.release(); // e.g., "10.0.22000"
  const parts = release.split(".");
  const build = parseInt(parts[2], 10);
  return !isNaN(build) && build >= 22000 ? "win11" : "win10";
}

const WINDOWS_FRAME_STYLE = windowsFrameStyle();

const PACKAGED_PRODUCT_NAME = String(app.getName?.() || "").trim().toLowerCase();
const APP_MODE = (
  String(process.env.ARCRHO_APP_MODE || "").trim().toLowerCase() === "arcode"
  || (app.isPackaged && PACKAGED_PRODUCT_NAME.includes("arcode"))
)
  ? "arcode"
  : "arcrho";
if (APP_MODE === "arcode") {
  app.setName("Arcode");
  app.setAppUserModelId("com.arcode.app");
} else {
  app.setAppUserModelId("com.arcrho.app");
}
// A launch against another server root (tools/local_server) gets its own Electron
// profile, so it never reuses the backend, window state, or storage of an app
// already running against the production root.
const USER_DATA_OVERRIDE = String(process.env.ARCRHO_USER_DATA_DIR || "").trim();
if (USER_DATA_OVERRIDE) app.setPath("userData", path.resolve(USER_DATA_OVERRIDE));
const HOST = process.env.ARCRHO_HOST || "127.0.0.1";
const UI_VERSION = process.env.ARCRHO_UI_VERSION || process.env.ARCODE_UI_VERSION || String(Date.now());
const DISPLAY_VERSION_OVERRIDE = APP_MODE === "arcode"
  ? process.env.ARCODE_DISPLAY_VERSION
  : process.env.ARCRHO_DISPLAY_VERSION;
const APP_DISPLAY_VERSION = String(
  DISPLAY_VERSION_OVERRIDE
  || (app.isPackaged ? app.getVersion() : `${app.getVersion()}+`)
).trim() || app.getVersion();
const BACKEND_TOKEN = createBackendLaunchToken({
  appMode: APP_MODE,
  userDataPath: app.getPath("userData"),
  nonce: crypto.randomBytes(16).toString("hex"),
});
const START_BACKEND = (APP_MODE === "arcode" ? process.env.ARCODE_START_BACKEND : process.env.ARCRHO_START_BACKEND) !== "0";
const PYTHON_EXE = process.env.PYTHON_EXE || process.env.PYTHON || "python";
const APP_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(APP_ROOT, "..");

// Deterministic launch profile for the UI regression harness.
//
// Baseline screenshot comparison needs byte-stable geometry and theme, and a test run must not
// leave the user's persisted window prefs changed. `ARCRHO_UI_TEST_PROFILE=1` freezes both: window
// size and theme come from env instead of the prefs file, and pref writes become no-ops.
const UI_TEST_PROFILE = String(process.env.ARCRHO_UI_TEST_PROFILE || "").trim() === "1";
const UI_TEST_WINDOW_SIZE = (() => {
  if (!UI_TEST_PROFILE) return null;
  const raw = String(process.env.ARCRHO_UI_TEST_WINDOW_SIZE || "1600x1000").trim();
  const match = /^(\d{3,5})\s*[xX*]\s*(\d{3,5})$/.exec(raw);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (width < 820 || height < 620) return null;
  return { width, height };
})();
const UI_TEST_COLOR_THEME = UI_TEST_PROFILE
  ? String(process.env.ARCRHO_UI_TEST_COLOR_THEME || "").trim().toLowerCase()
  : "";

initBackendLifecycle({
  appMode: APP_MODE,
  host: HOST,
  backendToken: BACKEND_TOKEN,
  appRoot: APP_ROOT,
  pythonExe: PYTHON_EXE,
});
initUpdateChecker({
  appMode: APP_MODE,
  getMainWindow: () => win,
  updateHost: {
    // The startup splash doubles as the update window: same size, same
    // progress bar, and already outside the main window.
    begin: () => {
      if (win && !win.isDestroyed()) win.hide();
      createSplashWindow();
    },
    progress: (progress, text) => updateSplashProgress(progress, text),
    cancel: () => {
      closeSplash();
      if (win && !win.isDestroyed()) {
        win.show();
        win.focus();
      }
    },
    shutdown: () => prepareQuit({ forUpdate: true }),
    // exit(), not quit(): everything quit() would do has been done, and the
    // installer is already waiting for this process to be gone.
    exit: () => app.exit(0),
  },
});

function getDfmRatioUndoRoot() {
  return path.join(app.getPath("temp"), "ArcRho", "dfm-ratio-undo");
}

function sanitizeDfmRatioUndoSessionId(value) {
  const text = String(value || "").trim().replace(/[^a-zA-Z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "");
  return text || `dfm_${Date.now()}`;
}

function resolveDfmRatioUndoDir(dirPath) {
  const root = path.resolve(getDfmRatioUndoRoot());
  const resolved = path.resolve(String(dirPath || ""));
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error("Invalid DFM ratio undo temp path.");
  }
  return resolved;
}

const PRELOAD_PATH = path.join(__dirname, "preload.js");
const MAIN_WINDOW_PREFS_FILE = "main_window_prefs.json";
const WINDOW_BACKGROUND_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const COLOR_THEMES = new Set(["light", "dark"]);
const TABLE_STYLES = new Set(["revolutionary", "classic"]);
const HOST_WINDOW_BACKGROUND_FALLBACK_COLOR = "#ffffff";
const ARCODE_WINDOW_BACKGROUND_COLOR = "#f7f8fa";

function readCanonicalLightWindowBackgroundColor() {
  try {
    const lightThemePath = path.join(APP_ROOT, "ui", "shared", "styles", "themes", "light.css");
    const lightThemeCss = fs.readFileSync(lightThemePath, "utf8");
    const match = lightThemeCss.match(/--ar-native-window-background:\s*(#[0-9a-fA-F]{6})/);
    if (WINDOW_BACKGROUND_COLOR_RE.test(match?.[1] || "")) return match[1].toLowerCase();
  } catch {
    // Keep the host safe if packaged theme assets are temporarily unavailable.
  }
  return HOST_WINDOW_BACKGROUND_FALLBACK_COLOR;
}

const DEFAULT_WINDOW_BACKGROUND_COLOR = readCanonicalLightWindowBackgroundColor();
const HOME_FOLDERS_PREFS_FILE = "home_folders.json";
const ARCODE_USER_SETTINGS_FILE = "user_settings.json";
const ARCODE_LEGACY_USER_SETTINGS_FILE = "settings.json";
const SCRIPTING_SHORTCUTS_FILE = "scripting_shortcuts.json";
const SCRIPTING_NOTEBOOK_PREFS_FILE = "scripting_notebook_prefs.json";
const MACRO_PREFS_FILE = "macro_prefs.json";
const FLIGHT_DECK_PREFS_FILE = "flight_deck.json";
const NOTES_PANEL_PREFS_FILE = "notes_panel_prefs.json";
const TABLE_COLORS_PREFS_FILE = "table_colors.json";
const RECENT_SETTINGS_FILES_PREFS_FILE = "recent_settings_files.json";
const WORKSPACE_PATHS_FILE = "workspace_paths.json";
const arcodeFolderWatchers = new Map();
const arcodeFolderWatchCleanupWindowIds = new Set();

let win = null;
let arcodeWin = null;
let splashWin = null;
let allowClose = false;
let pseudoMaximized = false;
let lastBounds = null;
let pendingClearCacheReloadRestore = null;
function toggleDevPanelForWindow(target = BrowserWindow.getFocusedWindow() || win) {
  if (!target || target.isDestroyed()) return { ok: false, error: "Window unavailable." };
  target.webContents.toggleDevTools();
  return { ok: true, open: target.webContents.isDevToolsOpened() };
}




function getMainWindowPrefsPath() {
  return path.join(getPrefsDir(), MAIN_WINDOW_PREFS_FILE);
}

function getPrefsDir() {
  return path.join(app.getPath("appData"), "ArcRho", "prefs");
}

// Sibling of app_endpoint.json, but written only once the main window is actually visible.
// An automation harness polls for this before its first screenshot.
function getUiReadyMarkerPath() {
  return path.join(
    app.getPath("appData"),
    APP_MODE === "arcode" ? "Arcode" : "ArcRho",
    "app_ui_ready.json"
  );
}

// Lists every running app, newest first, like app_endpoint.json, so a harness can wait for a
// named process rather than whichever app painted last.
function writeUiReadyMarker() {
  try {
    publishAppEntry(getUiReadyMarkerPath(), {
      format: "arcrho.app_ui_ready.v1",
      app: APP_MODE,
      pid: process.pid,
      port: getBackendPort(),
      window_id: win && !win.isDestroyed() ? win.id : null,
      test_profile: UI_TEST_PROFILE,
      shown_at: new Date().toISOString(),
    });
  } catch (err) {
    appendElectronLog("Failed to write UI ready marker", err);
  }
}

function removeUiReadyMarker() {
  // Only our own entry goes, so a second instance's entry survives.
  unpublishAppEntry(getUiReadyMarkerPath(), process.pid);
}

function getScriptingShortcutsPath() {
  return path.join(getPrefsDir(), SCRIPTING_SHORTCUTS_FILE);
}

function getScriptingNotebookPrefsPath() {
  return path.join(getPrefsDir(), SCRIPTING_NOTEBOOK_PREFS_FILE);
}

function getHomeFoldersPrefsPath() {
  return path.join(getPrefsDir(), HOME_FOLDERS_PREFS_FILE);
}

function getMacroPrefsPath() {
  return path.join(getPrefsDir(), MACRO_PREFS_FILE);
}

function getFlightDeckPrefsPath() {
  return path.join(getPrefsDir(), FLIGHT_DECK_PREFS_FILE);
}

function getNotesPanelPrefsPath() {
  return path.join(getPrefsDir(), NOTES_PANEL_PREFS_FILE);
}

function getTableColorsPrefsPath() {
  return path.join(getPrefsDir(), TABLE_COLORS_PREFS_FILE);
}

function getRecentSettingsFilesPrefsPath() {
  return path.join(getPrefsDir(), RECENT_SETTINGS_FILES_PREFS_FILE);
}

function normalizeRecentIpynbPaths(value, fallbackPath = "") {
  const inputs = Array.isArray(value) ? value : [];
  if (fallbackPath) inputs.unshift(fallbackPath);
  const seen = new Set();
  const paths = [];
  for (const item of inputs) {
    const notebookPath = String(item || "").trim();
    if (!notebookPath || path.extname(notebookPath).toLowerCase() !== ".ipynb") continue;
    const key = path.resolve(notebookPath).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    paths.push(notebookPath);
    if (paths.length >= 5) break;
  }
  return paths;
}

function getWorkspacePathsPath() {
  return path.join(app.getPath("appData"), "ArcRho", WORKSPACE_PATHS_FILE);
}

function getArcodeUserSettingsPath() {
  return path.join(app.getPath("appData"), "Arcode", ARCODE_USER_SETTINGS_FILE);
}

function getArcodeLegacyUserSettingsPath() {
  return path.join(app.getPath("appData"), "Arcode", ARCODE_LEGACY_USER_SETTINGS_FILE);
}

function readJsonObjectFile(filePath) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function readArcodeUserSettingsFile() {
  const settings = readJsonObjectFile(getArcodeUserSettingsPath());
  if (Object.keys(settings).length) return settings;
  return readJsonObjectFile(getArcodeLegacyUserSettingsPath());
}

function writeArcodeUserSettingsFile(settingsLike) {
  const settings = settingsLike && typeof settingsLike === "object" && !Array.isArray(settingsLike)
    ? settingsLike
    : {};
  const filePath = getArcodeUserSettingsPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const current = readJsonObjectFile(filePath);
  const legacy = Object.keys(current).length ? {} : readJsonObjectFile(getArcodeLegacyUserSettingsPath());
  const existing = Object.keys(current).length ? current : legacy;
  const payload = {
    ...existing,
    ...settings,
    updatedAt: new Date().toISOString(),
  };
  const tmpPath = `${filePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), "utf8");
  fs.renameSync(tmpPath, filePath);
  return { ok: true, path: filePath, settings: payload };
}

function isWindowsAppsPath(filePath) {
  return /\\WindowsApps\\/iu.test(String(filePath || ""));
}

function isAsarPath(filePath) {
  return /(?:^|[\\/])[^\\/]+\.asar(?:[\\/]|$)/iu.test(String(filePath || ""));
}

// Windows rejects a working directory that does not exist on disk, and the failure surfaces as
// "spawn <command> ENOENT" -- which reads as a missing executable rather than a bad cwd. In a
// packaged build APP_ROOT resolves inside `resources\app.asar`, a virtual path that only Electron's
// patched `fs` can see, so every host command launched from it failed that way. Launch host
// processes from a real directory instead.
let cachedHostSpawnCwd = "";
function getHostSpawnCwd() {
  if (cachedHostSpawnCwd) return cachedHostSpawnCwd;
  const candidates = [APP_ROOT];
  try {
    candidates.push(app.getPath("userData"));
  } catch {
    // The app may not expose userData yet; fall through to the temp directory.
  }
  candidates.push(os.tmpdir());
  for (const candidate of candidates.filter(Boolean)) {
    if (isAsarPath(candidate)) continue;
    try {
      if (fs.statSync(candidate).isDirectory()) {
        cachedHostSpawnCwd = candidate;
        return cachedHostSpawnCwd;
      }
    } catch {
      // Try the next candidate.
    }
  }
  return os.tmpdir();
}

// Resolve powershell.exe absolutely so the spawn never depends on the launching shell's PATH.
function getWindowsPowerShellCommand() {
  const systemRoot = String(process.env.SystemRoot || process.env.windir || "").trim();
  if (systemRoot) {
    const absolute = path.join(systemRoot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
    try {
      if (fs.existsSync(absolute)) return absolute;
    } catch {
      // Fall back to the PATH lookup.
    }
  }
  return findExecutableOnPath(["powershell.exe"]) || "powershell.exe";
}

function findExecutableOnPath(names) {
  const pathText = String(process.env.PATH || process.env.Path || "");
  const pathParts = pathText.split(path.delimiter).filter(Boolean);
  for (const dir of pathParts) {
    if (isWindowsAppsPath(dir)) continue;
    for (const name of names) {
      const candidate = path.join(dir, name);
      try {
        if (fs.existsSync(candidate)) return candidate;
      } catch {
        // Skip inaccessible PATH entries.
      }
    }
  }
  return "";
}

function runHostCommand(command, args = [], options = {}) {
  const {
    cwd = getHostSpawnCwd(),
    env = process.env,
    input = "",
    timeoutMs = 15000,
    windowsHide = true,
    shell: useShell = process.platform === "win32",
    onStdout = null,
    onStderr = null,
    cancelKey = "",
    cancelRegistry = null,
  } = options;
  return new Promise((resolve) => {
    let settled = false;
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let canceled = false;
    let proc = null;
    const registry = cancelRegistry && typeof cancelRegistry.get === "function"
      && typeof cancelRegistry.set === "function"
      && typeof cancelRegistry.delete === "function"
      ? cancelRegistry
      : null;
    const unregisterCancel = () => {
      if (!cancelKey || !registry) return;
      const active = registry.get(cancelKey);
      if (active === cancelProcess) {
        registry.delete(cancelKey);
      } else if (active && typeof active === "object" && active.cancelProcess === cancelProcess) {
        active.cancelProcess = null;
      }
    };
    const killProcessTree = () => {
      if (!proc || !proc.pid) return;
      if (process.platform === "win32") {
        try {
          spawn("taskkill", ["/pid", String(proc.pid), "/t", "/f"], {
            windowsHide: true,
            stdio: "ignore",
          });
        } catch {
          // Fall back to killing the immediate process.
        }
      }
      try {
        proc.kill();
      } catch {
        // ignore
      }
    };
    const cancelProcess = () => {
      if (settled) return false;
      canceled = true;
      killProcessTree();
      return true;
    };
    const finish = (result) => {
      if (settled) return;
      settled = true;
      unregisterCancel();
      resolve({
        ok: result.code === 0 && !timedOut && !canceled,
        code: result.code,
        signal: result.signal,
        stdout,
        stderr,
        timedOut,
        canceled,
        error: result.error || "",
      });
    };

    try {
      proc = spawn(command, args, {
        cwd,
        env,
        shell: useShell,
        windowsHide,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (err) {
      finish({ code: -1, signal: null, error: String(err?.message || err) });
      return;
    }

    if (cancelKey && registry) {
      const active = registry.get(cancelKey);
      if (active && typeof active === "object") {
        active.cancelProcess = cancelProcess;
        if (active.canceled) cancelProcess();
      } else {
        registry.set(cancelKey, cancelProcess);
      }
    }

    const timer = setTimeout(() => {
      timedOut = true;
      killProcessTree();
    }, Math.max(1000, timeoutMs));

    proc.stdout?.on("data", (chunk) => {
      const text = String(chunk || "");
      stdout += text;
      if (stdout.length > 200000) stdout = stdout.slice(-200000);
      if (typeof onStdout === "function") onStdout(text);
    });
    proc.stderr?.on("data", (chunk) => {
      const text = String(chunk || "");
      stderr += text;
      if (stderr.length > 200000) stderr = stderr.slice(-200000);
      if (typeof onStderr === "function") onStderr(text);
    });
    proc.once("error", (err) => {
      clearTimeout(timer);
      finish({ code: -1, signal: null, error: String(err?.message || err) });
    });
    proc.once("close", (code, signal) => {
      clearTimeout(timer);
      finish({ code: Number.isFinite(code) ? code : -1, signal });
    });

    if (input) proc.stdin?.write(String(input));
    proc.stdin?.end();
  });
}

function getVsCodeCommand() {
  const configured = String(process.env.ARCRHO_VSCODE_CMD || "").trim();
  if (configured) return configured;
  if (process.platform === "win32") {
    const candidates = [
      process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Programs", "Microsoft VS Code", "Code.exe") : "",
      process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Programs", "Microsoft VS Code", "bin", "code.cmd") : "",
      process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Programs", "Microsoft VS Code Insiders", "Code - Insiders.exe") : "",
      process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "Programs", "Microsoft VS Code Insiders", "bin", "code-insiders.cmd") : "",
      process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Microsoft VS Code", "Code.exe") : "",
      process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Microsoft VS Code", "bin", "code.cmd") : "",
      process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Microsoft VS Code", "Code.exe") : "",
      process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Microsoft VS Code", "bin", "code.cmd") : "",
      findExecutableOnPath(["code.cmd", "code.exe", "code-insiders.cmd", "code-insiders.exe"]),
    ].filter(Boolean);
    for (const candidate of candidates) {
      try {
        if (fs.existsSync(candidate) && !isWindowsAppsPath(candidate)) return candidate;
      } catch {
        // Try the next candidate.
      }
    }
    return "";
  }
  return findExecutableOnPath(["code", "code-insiders"]) || "code";
}

async function openPathInVsCode(targetPath) {
  const codeCommand = getVsCodeCommand();
  if (!codeCommand) return { ok: false, missing: true, error: "VS Code command not found." };
  try {
    const child = spawn(codeCommand, ["-r", targetPath], {
      cwd: fs.statSync(targetPath).isDirectory() ? targetPath : path.dirname(targetPath),
      detached: true,
      shell: process.platform === "win32" && /\.cmd$/i.test(codeCommand),
      stdio: "ignore",
      windowsHide: true,
    });
    child.unref();
    return { ok: true, opener: "vscode" };
  } catch (err) {
    return { ok: false, error: `VS Code open failed: ${String(err?.message || err)}` };
  }
}

function isExcelWorkbookPath(targetPath) {
  return /\.(xlsx|xlsm|xlsb|xls)$/iu.test(String(targetPath || "").trim());
}

function getExcelCommand() {
  const configured = String(process.env.ARCRHO_EXCEL_CMD || "").trim();
  if (configured) return configured;
  if (process.platform !== "win32") {
    return findExecutableOnPath(["excel"]) || "";
  }
  const officeVersions = ["Office16", "Office15", "Office14", "Office12"];
  const roots = [
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Microsoft Office", "root") : "",
    process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Microsoft Office", "root") : "",
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Microsoft Office") : "",
    process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Microsoft Office") : "",
  ].filter(Boolean);
  const candidates = [];
  for (const root of roots) {
    for (const version of officeVersions) {
      candidates.push(path.join(root, version, "EXCEL.EXE"));
    }
  }
  candidates.push(findExecutableOnPath(["EXCEL.EXE", "excel.exe"]));
  for (const candidate of candidates.filter(Boolean)) {
    try {
      if (fs.existsSync(candidate) && !isWindowsAppsPath(candidate)) return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return "";
}

function quotePowerShellString(value) {
  return `'${String(value ?? "").replace(/'/g, "''")}'`;
}

function spawnDetachedOpen(command, args = []) {
  return new Promise((resolve) => {
    let settled = false;
    let child = null;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      try {
        child?.unref?.();
      } catch {
        // ignore
      }
      resolve(result);
    };
    try {
      child = spawn(command, args, {
        cwd: getHostSpawnCwd(),
        detached: true,
        shell: false,
        stdio: "ignore",
        windowsHide: true,
      });
    } catch (err) {
      finish({ ok: false, error: String(err?.message || err) });
      return;
    }
    child.once("spawn", () => finish({ ok: true }));
    child.once("error", (err) => finish({ ok: false, error: String(err?.message || err) }));
  });
}

async function openExcelWorkbookReadOnly(targetPath) {
  if (!isExcelWorkbookPath(targetPath)) {
    return { ok: false, error: "Read-only open is only available for Excel workbook files." };
  }
  if (process.platform !== "win32") {
    return { ok: false, error: "Excel read-only open is only supported on Windows." };
  }

  const excelCommand = getExcelCommand();
  if (excelCommand) {
    const directResult = await spawnDetachedOpen(excelCommand, ["/r", targetPath]);
    if (directResult?.ok) return { ok: true, opener: "excel-read-only" };
  }

  const excelReadOnlyArgs = `/r "${targetPath}"`;
  const script = [
    "$ErrorActionPreference = 'Stop'",
    `Start-Process -FilePath 'excel.exe' -ArgumentList ${quotePowerShellString(excelReadOnlyArgs)}`,
  ].join("; ");
  const result = await runHostCommand(getWindowsPowerShellCommand(), [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-Command",
    script,
  ], {
    cwd: getHostSpawnCwd(),
    shell: false,
    timeoutMs: 10000,
  });
  if (result?.ok) return { ok: true, opener: "excel-read-only" };
  const detail = String(result?.stderr || result?.stdout || result?.error || "").trim();
  return { ok: false, error: detail || "Excel read-only open failed." };
}

function normalizeWindowBackgroundColor(value, fallback = DEFAULT_WINDOW_BACKGROUND_COLOR) {
  const color = String(value || "").trim();
  return WINDOW_BACKGROUND_COLOR_RE.test(color) ? color.toLowerCase() : fallback;
}

function isDarkWindowBackgroundColor(value) {
  const color = normalizeWindowBackgroundColor(value);
  const red = Number.parseInt(color.slice(1, 3), 16);
  const green = Number.parseInt(color.slice(3, 5), 16);
  const blue = Number.parseInt(color.slice(5, 7), 16);
  return ((red * 299) + (green * 587) + (blue * 114)) / 1000 < 128;
}

function readMainWindowPrefsData() {
  try {
    const prefPath = getMainWindowPrefsPath();
    if (!fs.existsSync(prefPath)) return {};
    const raw = fs.readFileSync(prefPath, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeMainWindowPrefsData(value) {
  try {
    const prefPath = getMainWindowPrefsPath();
    fs.mkdirSync(path.dirname(prefPath), { recursive: true });
    const payload = {
      ...(value && typeof value === "object" && !Array.isArray(value) ? value : {}),
      updated_at: new Date().toISOString(),
    };
    const tmpPath = `${prefPath}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), "utf8");
    fs.renameSync(tmpPath, prefPath);
    return true;
  } catch {
    return false;
  }
}

function loadMainWindowPrefs() {
  if (UI_TEST_WINDOW_SIZE) return { ...UI_TEST_WINDOW_SIZE };
  try {
    const parsed = readMainWindowPrefsData();
    const width = Math.round(Number(parsed?.width || 0));
    const height = Math.round(Number(parsed?.height || 0));
    if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
    if (width < 820 || height < 620) return null;
    return { width, height };
  } catch {
    return null;
  }
}

function saveMainWindowPrefs(sizeLike) {
  // A test run must not mutate the user's persisted geometry.
  if (UI_TEST_PROFILE) return;
  const width = Math.round(Number(sizeLike?.width || 0));
  const height = Math.round(Number(sizeLike?.height || 0));
  if (!Number.isFinite(width) || !Number.isFinite(height)) return;
  if (width < 820 || height < 620) return;
  writeMainWindowPrefsData({
    ...readMainWindowPrefsData(),
    width,
    height,
  });
}

function loadCachedWindowBackgroundColor() {
  return normalizeWindowBackgroundColor(readMainWindowPrefsData()?.theme_background_color);
}

function saveCachedWindowBackgroundColor(value) {
  const color = normalizeWindowBackgroundColor(value, "");
  if (!color) return false;
  return writeMainWindowPrefsData({
    ...readMainWindowPrefsData(),
    theme_background_color: color,
  });
}

function normalizeColorThemePreference(value, fallback = "") {
  const theme = String(value || "").trim().toLowerCase();
  return COLOR_THEMES.has(theme) ? theme : fallback;
}

function loadColorThemePreference() {
  if (UI_TEST_COLOR_THEME) {
    const forced = normalizeColorThemePreference(UI_TEST_COLOR_THEME);
    if (forced) return forced;
  }
  return normalizeColorThemePreference(readMainWindowPrefsData()?.color_theme);
}

function saveColorThemePreference(value) {
  const theme = normalizeColorThemePreference(value);
  if (!theme) return false;
  return writeMainWindowPrefsData({
    ...readMainWindowPrefsData(),
    color_theme: theme,
  });
}

function normalizeTableStylePreference(value, fallback = "") {
  const style = String(value || "").trim().toLowerCase();
  return TABLE_STYLES.has(style) ? style : fallback;
}

function loadTableStylePreference() {
  return normalizeTableStylePreference(readMainWindowPrefsData()?.table_style);
}

function saveTableStylePreference(value) {
  const style = normalizeTableStylePreference(value);
  if (!style) return false;
  return writeMainWindowPrefsData({
    ...readMainWindowPrefsData(),
    table_style: style,
  });
}

function createSplashWindow() {
  const startupBackgroundColor = loadCachedWindowBackgroundColor();
  const startupTheme = loadColorThemePreference()
    || (isDarkWindowBackgroundColor(startupBackgroundColor) ? "dark" : "light");
  splashWin = new BrowserWindow({
    width: 500,
    height: 400,
    frame: false,
    transparent: true,
    backgroundColor: startupBackgroundColor,
    resizable: false,
    center: true,
    alwaysOnTop: false,
    skipTaskbar: true,
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const splashPath = APP_MODE === "arcode"
    ? path.join(APP_ROOT, "ui", "arcode", "splash.html")
    : path.join(APP_ROOT, "ui", "splash.html");
  splashWin.loadFile(splashPath, {
    query: {
      version: APP_DISPLAY_VERSION,
      theme: startupTheme,
    },
  });
  return splashWin;
}

function updateSplashProgress(progress, text) {
  if (splashWin && !splashWin.isDestroyed()) {
    splashWin.webContents.send("splash-progress", { progress, text });
  }
}

function closeSplash() {
  if (splashWin && !splashWin.isDestroyed()) {
    splashWin.close();
    splashWin = null;
  }
}


function wireAppWindowInput(targetWindow) {
  if (!targetWindow || targetWindow.isDestroyed()) return;

  // The window is frameless, so its title bar and menu bar are page chrome the renderer draws.
  // Only the host knows when the window enters or leaves full screen, whichever way it was asked
  // for - the default menu's F11 accelerator, a maximize gesture, or the host API.
  // Each event carries its own answer rather than asking the window: on Windows `isFullScreen()`
  // still reports the state the window is leaving while these fire, which showed the chrome in
  // full screen and hid it in a normal window - exactly the wrong way round.
  const sendFullscreenState = (fullscreen) => {
    if (!targetWindow || targetWindow.isDestroyed()) return;
    const prefix = (APP_MODE === "arcode" || targetWindow === arcodeWin) ? "arcode" : "arcrho";
    targetWindow.webContents.send(`${prefix}:fullscreen-change`, { fullscreen });
  };
  targetWindow.on("enter-full-screen", () => sendFullscreenState(true));
  targetWindow.on("leave-full-screen", () => sendFullscreenState(false));

  targetWindow.webContents.on("before-input-event", (event, input) => {
    if (!targetWindow || targetWindow.isDestroyed()) return;
    const messagePrefix = (APP_MODE === "arcode" || targetWindow === arcodeWin) ? "arcode" : "arcrho";

    const key = String(input.key || "").toUpperCase();
    const ctrl = !!input.control;
    const alt = !!input.alt;
    const shift = !!input.shift;
    const type = String(input.type || "");

    const sendHotkey = (action) => {
      targetWindow.webContents.send(`${messagePrefix}:hotkey`, { action });
    };

    if (ctrl && !alt && shift && key === "I") {
      event.preventDefault();
      toggleDevPanelForWindow(targetWindow);
      return;
    }

    if (type === "mouseWheel" && ctrl) {
      event.preventDefault();
      const deltaY = Number(input.deltaY || 0);
      targetWindow.webContents.send(`${messagePrefix}:zoom`, { deltaY });
      return;
    }

    if (ctrl && !alt && (key === "-" || key === "_")) {
      event.preventDefault();
      targetWindow.webContents.send(`${messagePrefix}:zoom-step`, { delta: -1 });
      return;
    }
    if (ctrl && !alt && (key === "=" || key === "+")) {
      event.preventDefault();
      targetWindow.webContents.send(`${messagePrefix}:zoom-step`, { delta: 1 });
      return;
    }
    if (ctrl && !alt && key === "0") {
      event.preventDefault();
      targetWindow.webContents.send(`${messagePrefix}:zoom-reset`);
      return;
    }

    if (!alt && key === "F5") {
      event.preventDefault();
      return;
    }
    if (ctrl && !alt && key === "R" && shift) {
      event.preventDefault();
      sendHotkey("custom_hard_refresh");
      return;
    }
    if (ctrl && !alt && key === "R" && !shift) {
      event.preventDefault();
      sendHotkey("custom_refresh");
      return;
    }

    if (ctrl && !alt && !shift && key === "S") {
      event.preventDefault();
      sendHotkey("file_save");
      return;
    }
    if (ctrl && !alt && shift && key === "S") {
      event.preventDefault();
      sendHotkey("file_save_as");
      return;
    }
    if (ctrl && !alt && !shift && key === "O") {
      event.preventDefault();
      sendHotkey("file_import");
      return;
    }
    if (ctrl && !alt && !shift && key === "P") {
      event.preventDefault();
      sendHotkey("file_print");
      return;
    }
    if (ctrl && !alt && shift && key === "F") {
      event.preventDefault();
      sendHotkey("view_toggle_nav");
      return;
    }
    if (ctrl && !alt && !shift && key === "Q") {
      event.preventDefault();
      sendHotkey("app_shutdown");
      return;
    }
    if (ctrl && alt && key === "R") {
      event.preventDefault();
      sendHotkey("file_restart");
      return;
    }
    if (ctrl && !alt && shift && key === "K") {
      event.preventDefault();
      sendHotkey("clear_test_data");
      return;
    }

    if (alt && !ctrl && !shift && key === "W") {
      event.preventDefault();
      targetWindow.webContents.send(`${messagePrefix}:close-active-tab`);
      return;
    }
    if (ctrl && !alt && !shift && key === "W") {
      event.preventDefault();
      targetWindow.webContents.send(`${messagePrefix}:close-active-tab`);
    }
  });
}

function buildArcodeUrl(options = {}) {
  const params = new URLSearchParams();
  params.set("v", String(options.uiVersion || UI_VERSION));
  const theme = loadColorThemePreference();
  if (theme) params.set("theme", theme);
  const openPath = String(options.path || options.openPath || "").trim();
  if (openPath) params.set("path", openPath);
  if (options.projectJson) params.set("projectJson", JSON.stringify(options.projectJson));
  if (options.dfmMethod) params.set("dfm", JSON.stringify(options.dfmMethod));
  if (options.fresh) params.set("fresh", "1");
  return `http://${HOST}:${getBackendPort()}/ui/arcode/main.html?${params.toString()}`;
}

function buildArcRhoUrl(options = {}) {
  const params = new URLSearchParams();
  params.set("v", String(options.uiVersion || UI_VERSION));
  const theme = loadColorThemePreference();
  if (theme) params.set("theme", theme);
  const tableStyle = loadTableStylePreference();
  if (tableStyle) params.set("tableStyle", tableStyle);
  return `http://${HOST}:${getBackendPort()}/ui/?${params.toString()}`;
}

function createWindow() {
  const savedSize = loadMainWindowPrefs();
  const startupBackgroundColor = loadCachedWindowBackgroundColor();
  const primaryDisplay = screen.getPrimaryDisplay();
  const screenWidth = Math.round(Number(primaryDisplay?.size?.width || 0));
  const screenHeight = Math.round(Number(primaryDisplay?.size?.height || 0));
  const launchMaxWidth = screenWidth > 0 ? Math.max(320, Math.floor(screenWidth * 0.9)) : 1400;
  const launchMaxHeight = screenHeight > 0 ? Math.max(320, Math.floor(screenHeight * 0.93)) : 900;
  const launchWidth = Math.min(Math.round(savedSize?.width || 1400), launchMaxWidth);
  const launchHeight = Math.min(Math.round(savedSize?.height || 900), launchMaxHeight);
  win = new BrowserWindow({
    width: launchWidth,
    height: launchHeight,
    frame: false,
    thickFrame: true,  // Adds Windows border for resize handles and visibility on Win10
    show: false,  // Hidden until splash closes
    backgroundColor: startupBackgroundColor,
    title: APP_MODE === "arcode" ? "Arcode" : "Arco Workspace",
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.on("close", async (e) => {
    if (allowClose) return;
    e.preventDefault();
    try {
      const shouldIntercept = await win.webContents.executeJavaScript(
        "window.__arcrho_should_intercept_close && window.__arcrho_should_intercept_close()"
      );
      if (shouldIntercept) {
        win.webContents.executeJavaScript(
          "window.postMessage({type:'arcrho:close-active-tab'}, '*');"
        );
        return;
      }
    } catch {
      // ignore
    }

    try {
      const confirmed = await win.webContents.executeJavaScript(
        "window.__arcrho_confirm_app_shutdown ? window.__arcrho_confirm_app_shutdown() : (window.__arcode_confirm_window_close ? window.__arcode_confirm_window_close() : true)"
      );
      if (!confirmed) {
        return;
      }
    } catch {
      // ignore
    }

    allowClose = true;
    await requestBackendShutdown();
    setTimeout(() => {
      try { win.close(); } catch {}
    }, 0);
  });

  let windowSizeSaveTimer = null;
  const scheduleWindowSizeSave = () => {
    if (windowSizeSaveTimer) clearTimeout(windowSizeSaveTimer);
    windowSizeSaveTimer = setTimeout(() => {
      windowSizeSaveTimer = null;
      if (!win || win.isDestroyed()) return;
      if (win.isMinimized() || win.isMaximized() || win.isFullScreen() || pseudoMaximized) return;
      const [width, height] = win.getSize();
      saveMainWindowPrefs({ width, height });
    }, 200);
  };
  win.on("resize", scheduleWindowSizeSave);
  win.on("closed", () => {
    if (windowSizeSaveTimer) clearTimeout(windowSizeSaveTimer);
    windowSizeSaveTimer = null;
  });

  win.loadURL(APP_MODE === "arcode" ? buildArcodeUrl() : buildArcRhoUrl());
  wireAppWindowInput(win);
}

function createArcodeWindow(options = {}) {
  if (arcodeWin && !arcodeWin.isDestroyed()) {
    const openPath = String(options.path || options.openPath || "").trim();
    if (arcodeWin.isMinimized()) arcodeWin.restore();
    arcodeWin.show();
    arcodeWin.focus();
    if (openPath || options.dfmMethod || options.projectJson) {
      arcodeWin.webContents.send("arcode:open-file", { path: openPath, dfmMethod: options.dfmMethod || null, projectJson: options.projectJson || null });
    }
    return arcodeWin;
  }

  const cachedBackgroundColor = loadCachedWindowBackgroundColor();
  const startupBackgroundColor = isDarkWindowBackgroundColor(cachedBackgroundColor)
    ? cachedBackgroundColor
    : ARCODE_WINDOW_BACKGROUND_COLOR;
  arcodeWin = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 560,
    frame: false,
    thickFrame: true,
    show: false,
    backgroundColor: startupBackgroundColor,
    title: "Arcode",
    webPreferences: {
      preload: PRELOAD_PATH,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  let arcodeAllowClose = false;
  arcodeWin.on("close", (event) => {
    if (arcodeAllowClose) return;
    event.preventDefault();
    try {
      arcodeWin.webContents.executeJavaScript(
        "window.__arcode_confirm_window_close ? window.__arcode_confirm_window_close() : true"
      ).then((confirmed) => {
        if (!confirmed || !arcodeWin || arcodeWin.isDestroyed()) return;
        arcodeAllowClose = true;
        arcodeWin.close();
      }).catch(() => {
        if (!arcodeWin || arcodeWin.isDestroyed()) return;
        arcodeAllowClose = true;
        arcodeWin.close();
      });
    } catch {
      arcodeAllowClose = true;
      arcodeWin.close();
    }
  });
  arcodeWin.on("closed", () => {
    arcodeWin = null;
  });
  arcodeWin.loadURL(buildArcodeUrl(options));
  arcodeWin.once("ready-to-show", () => {
    if (!arcodeWin || arcodeWin.isDestroyed()) return;
    arcodeWin.show();
    arcodeWin.focus();
  });
  wireAppWindowInput(arcodeWin);
  return arcodeWin;
}

ipcMain.handle("pick-open-workflow", async (event, payload) => {
  const startDir = payload?.startDir || "";
  const result = await dialog.showOpenDialog(getIpcWindow(event), {
    defaultPath: startDir || undefined,
    properties: ["openFile"],
    filters: [{ name: "Workflow", extensions: ["arcwf", "json"] }],
  });
  if (result.canceled || !result.filePaths?.length) return "";
  return result.filePaths[0];
});

ipcMain.handle("pick-open-table-file", async (event, payload) => {
  const startDir = payload?.startDir || "";
  const result = await dialog.showOpenDialog(getIpcWindow(event), {
    defaultPath: startDir || undefined,
    properties: ["openFile"],
    filters: [
      { name: "Data Files", extensions: ["csv", "txt", "parquet", "xlsx", "xlsm", "xls"] },
      { name: "All Files", extensions: ["*"] },
    ],
  });
  if (result.canceled || !result.filePaths?.length) return "";
  return result.filePaths[0];
});

ipcMain.handle("pick-folder", async (event, payload) => {
  const startDir = String(payload?.startDir || "").trim();
  const defaultPath = startDir && fs.existsSync(startDir) ? startDir : undefined;
  const result = await dialog.showOpenDialog(getIpcWindow(event), {
    defaultPath,
    properties: ["openDirectory"],
  });
  if (result.canceled || !result.filePaths?.length) return "";
  return result.filePaths[0];
});

ipcMain.handle("find-arcrho-server-root", async () => {
  if (process.platform !== "win32") return { found: false, path: "" };
  for (let code = 68; code <= 90; code++) {
    const drive = `${String.fromCharCode(code)}:\\`;
    const candidate = path.join(drive, "ArcRho Server");
    try {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
        return { found: true, path: candidate };
      }
    } catch {
      // Skip unavailable or inaccessible drives.
    }
  }
  return { found: false, path: "" };
});

ipcMain.handle("pick-save-workflow", async (event, payload) => {
  const suggestedName = payload?.suggestedName || "workflow.arcwf";
  const startDir = payload?.startDir || "";
  const defaultPath = startDir ? path.join(startDir, suggestedName) : suggestedName;
  const result = await dialog.showSaveDialog(getIpcWindow(event), {
    defaultPath,
    filters: [{ name: "Workflow", extensions: ["arcwf", "json"] }],
  });
  if (result.canceled || !result.filePath) return "";
  return result.filePath;
});

ipcMain.handle("pick-open-file", async (event, payload) => {
  const startDir = payload?.startDir || "";
  const filters = Array.isArray(payload?.filters) && payload.filters.length
    ? payload.filters
    : [{ name: "All Files", extensions: ["*"] }];
  const result = await dialog.showOpenDialog(getIpcWindow(event), {
    defaultPath: startDir || undefined,
    properties: ["openFile"],
    filters,
  });
  if (result.canceled || !result.filePaths?.length) return "";
  return result.filePaths[0];
});

ipcMain.handle("arcode-list-folder", async (_event, payload) => {
  const folderPath = String(payload?.path || "").trim();
  const includeHidden = !!payload?.includeHidden;
  const includeMetadata = !!payload?.includeMetadata;
  if (!folderPath) return { ok: false, error: "Empty folder path.", entries: [] };
  try {
    const stat = await fs.promises.stat(folderPath);
    if (!stat.isDirectory()) return { ok: false, error: `Not a folder: ${folderPath}`, entries: [] };
    const dirents = await fs.promises.readdir(folderPath, { withFileTypes: true });
    const visibleDirents = dirents.filter((entry) => includeHidden || !entry.name.startsWith("."));
    const entries = await Promise.all(visibleDirents.map(async (entry) => {
      const entryPath = path.join(folderPath, entry.name);
      let entryStat = null;
      if (includeMetadata) {
        try {
          entryStat = await fs.promises.stat(entryPath);
        } catch {
          entryStat = null;
        }
      }
      const isDirectory = entryStat ? entryStat.isDirectory() : entry.isDirectory();
      const isFile = entryStat ? entryStat.isFile() : entry.isFile();
      return {
        name: entry.name,
        path: entryPath,
        isDirectory,
        isFile,
        ...(includeMetadata ? {
          size: isFile && Number.isFinite(entryStat?.size) ? entryStat.size : null,
          mtimeMs: Number.isFinite(entryStat?.mtimeMs) ? entryStat.mtimeMs : null,
        } : {}),
      };
    }));
    entries.sort((a, b) => {
      if (a.isDirectory !== b.isDirectory) return a.isDirectory ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });
    return { ok: true, path: folderPath, entries };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not list folder."), entries: [] };
  }
});

function closeArcodeFolderWatch(watchId) {
  const id = String(watchId || "").trim();
  if (!id) return false;
  const entry = arcodeFolderWatchers.get(id);
  if (!entry) return false;
  arcodeFolderWatchers.delete(id);
  try {
    entry.watcher.close();
  } catch {
    // Watchers may already be closed while a window is tearing down.
  }
  return true;
}

function closeArcodeFolderWatchesForWindow(windowId) {
  for (const [watchId, entry] of Array.from(arcodeFolderWatchers.entries())) {
    if (entry.windowId === windowId) closeArcodeFolderWatch(watchId);
  }
  arcodeFolderWatchCleanupWindowIds.delete(windowId);
}

ipcMain.handle("arcode-folder-watch-start", async (event, payload) => {
  const folderPath = String(payload?.path || "").trim();
  if (!folderPath) return { ok: false, error: "Empty folder path." };
  const targetWindow = getIpcWindow(event);
  if (!targetWindow || targetWindow.isDestroyed()) return { ok: false, error: "Window is unavailable." };
  const targetFrame = event.senderFrame || null;
  const sendToRequester = (channel, message) => {
    try {
      if (targetFrame && !targetFrame.isDestroyed()) {
        targetFrame.send(channel, message);
        return true;
      }
    } catch {
      // Fall back to the window if the original frame is already gone.
    }
    if (!targetWindow.isDestroyed()) {
      targetWindow.webContents.send(channel, message);
      return true;
    }
    return false;
  };
  try {
    const resolvedFolderPath = path.resolve(folderPath);
    for (const [existingWatchId, entry] of arcodeFolderWatchers.entries()) {
      if (entry.windowId === targetWindow.id && path.resolve(entry.path) === resolvedFolderPath) {
        return { ok: true, watchId: existingWatchId, path: entry.path };
      }
    }
    const stat = await fs.promises.stat(resolvedFolderPath);
    if (!stat.isDirectory()) return { ok: false, error: `Not a folder: ${folderPath}` };
    const watchId = `arcode_watch_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const watcher = fs.watch(resolvedFolderPath, { persistent: false }, (eventType, filename) => {
      if (targetWindow.isDestroyed()) {
        closeArcodeFolderWatch(watchId);
        return;
      }
      targetWindow.webContents.send("arcode-folder-changed", {
        watchId,
        path: resolvedFolderPath,
        eventType: String(eventType || ""),
        filename: filename ? String(filename) : "",
      });
    });
    watcher.on("error", (err) => {
      if (!targetWindow.isDestroyed()) {
        targetWindow.webContents.send("arcode-folder-changed", {
          watchId,
          path: resolvedFolderPath,
          error: String(err?.message || err || "Folder watch failed."),
        });
      }
      closeArcodeFolderWatch(watchId);
    });
    arcodeFolderWatchers.set(watchId, { watcher, path: resolvedFolderPath, windowId: targetWindow.id });
    if (!arcodeFolderWatchCleanupWindowIds.has(targetWindow.id)) {
      arcodeFolderWatchCleanupWindowIds.add(targetWindow.id);
      targetWindow.once("closed", () => closeArcodeFolderWatchesForWindow(targetWindow.id));
    }
    return { ok: true, watchId, path: resolvedFolderPath };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not watch folder.") };
  }
});

ipcMain.handle("arcode-folder-watch-stop", async (_event, payload) => {
  return { ok: closeArcodeFolderWatch(payload?.watchId) };
});

ipcMain.handle("open-path", async (_event, payload) => {
  const targetPath = String(payload?.path || "").trim();
  const preferredApp = String(payload?.preferredApp || payload?.preferred_app || "").trim().toLowerCase();
  const readOnly = !!payload?.readOnly
    || !!payload?.read_only
    || preferredApp === "excel-read-only"
    || String(payload?.openMode || payload?.open_mode || "").trim().toLowerCase() === "read-only";
  // "Open DFM JSON" names a method, not a file: Arcode loads it through the
  // hosted DFM load and shows it read only, so nothing here touches the share.
  if (preferredApp === "arcode" && payload?.projectJson) {
    createArcodeWindow({ projectJson: payload.projectJson });
    return { ok: true, opener: "arcode" };
  }
  if (preferredApp === "arcode" && payload?.dfmMethod) {
    createArcodeWindow({ dfmMethod: payload.dfmMethod });
    return { ok: true, opener: "arcode" };
  }
  if (!targetPath) return { ok: false, error: "Empty path." };
  try {
    if (!fs.existsSync(targetPath)) {
      return { ok: false, error: `Path not found: ${targetPath}` };
    }
    if (readOnly) {
      return openExcelWorkbookReadOnly(targetPath);
    }
    let preferredError = "";
    if (preferredApp === "arcode") {
      createArcodeWindow({ path: targetPath });
      return { ok: true, opener: "arcode" };
    }
    if (preferredApp === "vscode" || preferredApp === "code") {
      const preferred = await openPathInVsCode(targetPath);
      if (preferred?.ok) return { ok: true, opener: preferred.opener || "vscode" };
      if (!preferred?.missing) return { ok: false, error: String(preferred?.error || "VS Code open failed.") };
      preferredError = String(preferred?.error || "").trim();
    }
    const openErr = await shell.openPath(targetPath);
    if (openErr) return { ok: false, error: preferredError ? `${preferredError}; ${String(openErr)}` : String(openErr) };
    return { ok: true, opener: "default" };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("show-item-in-folder", async (_event, payload) => {
  const targetPath = String(payload?.path || "").trim();
  if (!targetPath) return { ok: false, error: "Empty path." };
  try {
    if (!fs.existsSync(targetPath)) {
      return { ok: false, error: `Path not found: ${targetPath}` };
    }
    shell.showItemInFolder(targetPath);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("open-external-url", async (_event, payload) => {
  try {
    const url = new URL(String(payload?.url || ""));
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
      return { ok: false, error: "Only HTTP and HTTPS web addresses can be opened." };
    }
    await shell.openExternal(url.href);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("open-terminal", async (_event, payload) => {
  const folderPath = String(payload?.cwd || payload?.path || "").trim();
  if (!folderPath) return { ok: false, error: "Empty terminal folder." };
  try {
    const stat = await fs.promises.stat(folderPath);
    if (!stat.isDirectory()) return { ok: false, error: `Not a folder: ${folderPath}` };
    if (process.platform === "win32") {
      const folder = quotePowerShellString(folderPath);
      const script = [
        `$folder = ${folder}`,
        "if (Get-Command wt.exe -ErrorAction SilentlyContinue) {",
        "  Start-Process -FilePath 'wt.exe' -ArgumentList @('-d', $folder)",
        "} else {",
        "  Start-Process -FilePath 'powershell.exe' -WorkingDirectory $folder",
        "}",
      ].join("; ");
      const result = await runHostCommand(getWindowsPowerShellCommand(), [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
      ], {
        cwd: folderPath,
        shell: false,
        timeoutMs: 5000,
      });
      if (!result.ok) {
        return { ok: false, error: result.stderr || result.stdout || result.error || "Could not open terminal." };
      }
      return { ok: true, cwd: folderPath };
    }
    const opener = process.platform === "darwin" ? "open" : "x-terminal-emulator";
    const args = process.platform === "darwin" ? ["-a", "Terminal", folderPath] : [];
    const result = await runHostCommand(opener, args, {
      cwd: folderPath,
      shell: false,
      timeoutMs: 5000,
      windowsHide: false,
    });
    return result.ok
      ? { ok: true, cwd: folderPath }
      : { ok: false, error: result.stderr || result.stdout || result.error || "Could not open terminal." };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("save-json-file", async (event, payload) => {
  const data = payload?.data ?? null;
  const suggestedName = payload?.suggestedName || "data.json";
  const startDir = payload?.startDir || "";
  const filters = Array.isArray(payload?.filters) && payload.filters.length
    ? payload.filters
    : [{ name: "JSON", extensions: ["json"] }];
  let filePath = payload?.path || "";

  if (!filePath) {
    const defaultPath = startDir ? path.join(startDir, suggestedName) : suggestedName;
    const result = await dialog.showSaveDialog(getIpcWindow(event), {
      defaultPath,
      filters,
    });
    if (result.canceled || !result.filePath) return { path: "", canceled: true };
    filePath = result.filePath;
  }

  try {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    const content = formatJsonForSave(data);
    fs.writeFileSync(filePath, content, "utf8");
    return { path: filePath, canceled: false };
  } catch (err) {
    return { path: "", canceled: false, error: String(err?.message || err) };
  }
});

// Lays out a JSON value the way ArcRho writes it to disk, for a read-only view
// such as a DFM method opened in Arcode. Nothing is written.
ipcMain.handle("format-persisted-json-text", (_event, payload) => formatJsonForSave(payload?.data ?? null));

ipcMain.handle("save-text-file", async (event, payload) => {
  const data = payload?.data ?? "";
  const suggestedName = payload?.suggestedName || "data.txt";
  const startDir = payload?.startDir || "";
  let filePath = payload?.path || "";

  if (!filePath) {
    const defaultPath = startDir ? path.join(startDir, suggestedName) : suggestedName;
    const result = await dialog.showSaveDialog(getIpcWindow(event), { defaultPath });
    if (result.canceled || !result.filePath) return { path: "", canceled: true };
    filePath = result.filePath;
  }

  try {
    const dir = path.dirname(filePath);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(filePath, String(data), "utf8");
    return { path: filePath, canceled: false };
  } catch (err) {
    return { path: "", canceled: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("read-text-file", async (_event, payload) => {
  const filePath = String(payload?.path || "");
  const maxBytes = Math.max(1024, Math.min(500000, Number(payload?.maxBytes || 200000) || 200000));
  if (!filePath) return { ok: false, error: "Empty path." };
  try {
    if (!fs.existsSync(filePath)) return { ok: false, error: `File not found: ${filePath}` };
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) return { ok: false, error: "Path is not a file." };
    if (stat.size > maxBytes) {
      return { ok: false, error: `File is too large for ArcBot context (${stat.size.toLocaleString()} bytes).` };
    }
    const raw = fs.readFileSync(filePath);
    if (raw.includes(0)) return { ok: false, error: "Binary files cannot be attached as ArcBot text context." };
    return {
      ok: true,
      path: filePath,
      name: path.basename(filePath),
      size: stat.size,
      revision: {
        path: filePath,
        size: stat.size,
        mtimeMs: stat.mtimeMs,
        hash: crypto.createHash("sha256").update(raw).digest("hex"),
      },
      text: raw.toString("utf8"),
    };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not read file.") };
  }
});

ipcMain.handle("read-json-file", async (_event, payload) => {
  const filePath = String(payload?.path || "");
  if (!filePath) return { exists: false };
  try {
    const [raw, stat] = await Promise.all([
      fs.promises.readFile(filePath, "utf8"),
      fs.promises.stat(filePath),
    ]);
    const hash = crypto.createHash("sha256").update(raw).digest("hex");
    return { exists: true, data: JSON.parse(raw), revision: { path: filePath, size: stat.size, mtimeMs: stat.mtimeMs, hash } };
  } catch (err) {
    if (err?.code === "ENOENT") return { exists: false };
    return { exists: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("get-file-revision", async (_event, payload) => {
  const filePath = String(payload?.path || "");
  if (!filePath) return { exists: false };
  try {
    const [stat, raw] = await Promise.all([
      fs.promises.stat(filePath),
      fs.promises.readFile(filePath),
    ]);
    if (!stat.isFile()) return { exists: false, error: "Path is not a file." };
    const hash = crypto.createHash("sha256").update(raw).digest("hex");
    return { exists: true, revision: { path: filePath, size: stat.size, mtimeMs: stat.mtimeMs, hash } };
  } catch (err) {
    if (err?.code === "ENOENT") return { exists: false };
    return { exists: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("rename-file", async (_event, payload) => {
  const filePath = String(payload?.path || "").trim();
  const newName = String(payload?.newName || "").trim();
  if (!filePath) return { ok: false, error: "Empty path." };
  if (!newName) return { ok: false, error: "Empty filename." };
  if (/[\\/:*?"<>|]/.test(newName) || path.basename(newName) !== newName) {
    return { ok: false, error: "Filename cannot include path separators or Windows filename characters." };
  }
  try {
    if (!fs.existsSync(filePath)) return { ok: false, error: `File not found: ${filePath}` };
    const stat = fs.statSync(filePath);
    if (!stat.isFile()) return { ok: false, error: "Path is not a file." };
    const targetPath = path.join(path.dirname(filePath), newName);
    if (path.resolve(targetPath) === path.resolve(filePath)) {
      const raw = fs.readFileSync(filePath);
      const hash = crypto.createHash("sha256").update(raw).digest("hex");
      return { ok: true, path: filePath, revision: { path: filePath, size: stat.size, mtimeMs: stat.mtimeMs, hash } };
    }
    if (fs.existsSync(targetPath)) return { ok: false, error: `File already exists: ${targetPath}` };
    fs.renameSync(filePath, targetPath);
    const nextStat = fs.statSync(targetPath);
    const raw = fs.readFileSync(targetPath);
    const hash = crypto.createHash("sha256").update(raw).digest("hex");
    return { ok: true, path: targetPath, revision: { path: targetPath, size: nextStat.size, mtimeMs: nextStat.mtimeMs, hash } };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("dfm-ratio-undo-session-create", async (_event, payload) => {
  try {
    const root = getDfmRatioUndoRoot();
    const sessionId = sanitizeDfmRatioUndoSessionId(payload?.inst || payload?.sessionId || "");
    const dir = path.join(root, `${sessionId}-${Date.now()}`);
    const resolved = resolveDfmRatioUndoDir(dir);
    fs.rmSync(resolved, { recursive: true, force: true });
    fs.mkdirSync(resolved, { recursive: true });
    return { ok: true, dir: resolved };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not create DFM ratio undo temp session.") };
  }
});

ipcMain.handle("dfm-ratio-undo-step-save", async (_event, payload) => {
  try {
    const dir = resolveDfmRatioUndoDir(payload?.dir);
    fs.mkdirSync(dir, { recursive: true });
    const index = Math.max(0, Math.min(9999, Number.parseInt(String(payload?.index ?? "0"), 10) || 0));
    const filePath = path.join(dir, `step-${String(index).padStart(4, "0")}.json`);
    fs.writeFileSync(filePath, formatJsonForSave(payload?.data ?? null), "utf8");
    return { ok: true, path: filePath };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not save DFM ratio undo step.") };
  }
});

ipcMain.handle("dfm-ratio-undo-session-clear", async (_event, payload) => {
  try {
    const dir = resolveDfmRatioUndoDir(payload?.dir);
    fs.rmSync(dir, { recursive: true, force: true });
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not clear DFM ratio undo temp session.") };
  }
});

ipcMain.handle("scripting-shortcuts-load", async () => {
  const filePath = getScriptingShortcutsPath();
  try {
    if (!fs.existsSync(filePath)) return { exists: false };
    const raw = fs.readFileSync(filePath, "utf8");
    const parsed = JSON.parse(raw);
    const bindings = parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed.bindings && typeof parsed.bindings === "object" && !Array.isArray(parsed.bindings)
        ? parsed.bindings
        : parsed)
      : null;
    if (!bindings || typeof bindings !== "object" || Array.isArray(bindings)) {
      return { exists: false, error: "Invalid shortcut settings format" };
    }
    return { exists: true, bindings };
  } catch (err) {
    return { exists: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("scripting-shortcuts-save", async (_event, payload) => {
  const bindings = payload?.bindings;
  if (!bindings || typeof bindings !== "object" || Array.isArray(bindings)) {
    return { ok: false, error: "Invalid shortcuts payload" };
  }
  const filePath = getScriptingShortcutsPath();
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    const data = {
      bindings,
      updated_at: new Date().toISOString(),
    };
    const tmpPath = `${filePath}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), "utf8");
    fs.renameSync(tmpPath, filePath);
    return { ok: true, path: filePath };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("arcode-user-settings-load", async () => {
  try {
    return readArcodeUserSettingsFile();
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not load Arcode settings.") };
  }
});

ipcMain.handle("arcode-user-settings-save", async (_event, payload) => {
  try {
    const settings = payload?.settings && typeof payload.settings === "object" ? payload.settings : {};
    return writeArcodeUserSettingsFile(settings);
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not save Arcode settings.") };
  }
});

// A local-user preference kept as one JSON object in its own file under `%APPDATA%\ArcRho\prefs`,
// read and written whole. Each preference has its own file because one window saving would
// otherwise erase what another window had just stored in a shared one.
function preferencesFileHandlers(getPath, label) {
  return {
    async load() {
      const filePath = getPath();
      try {
        if (!fs.existsSync(filePath)) return { ok: true, exists: false, preferences: {} };
        const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error(`${label} preferences must contain a JSON object.`);
        }
        return { ok: true, exists: true, preferences: parsed };
      } catch (err) {
        return { ok: false, exists: false, preferences: {}, error: String(err?.message || err || `Could not load ${label} preferences.`) };
      }
    },
    async save(_event, payload) {
      const preferences = payload?.preferences;
      if (!preferences || typeof preferences !== "object" || Array.isArray(preferences)) {
        return { ok: false, error: `Invalid ${label} preferences payload.` };
      }
      const filePath = getPath();
      try {
        fs.mkdirSync(path.dirname(filePath), { recursive: true });
        const stored = { ...preferences, updatedAt: new Date().toISOString() };
        const tmpPath = `${filePath}.tmp`;
        fs.writeFileSync(tmpPath, JSON.stringify(stored, null, 2), "utf8");
        fs.renameSync(tmpPath, filePath);
        return { ok: true, path: filePath, preferences: stored };
      } catch (err) {
        return { ok: false, error: String(err?.message || err || `Could not save ${label} preferences.`) };
      }
    },
  };
}

const homeFolderPreferences = preferencesFileHandlers(getHomeFoldersPrefsPath, "Home folder");
ipcMain.handle("home-folders-preferences-load", homeFolderPreferences.load);
ipcMain.handle("home-folders-preferences-save", homeFolderPreferences.save);

const macroPreferences = preferencesFileHandlers(getMacroPrefsPath, "macro");
ipcMain.handle("macro-preferences-load", macroPreferences.load);
ipcMain.handle("macro-preferences-save", macroPreferences.save);

const flightDeckPreferences = preferencesFileHandlers(getFlightDeckPrefsPath, "Flight Deck");
ipcMain.handle("flight-deck-preferences-load", flightDeckPreferences.load);
ipcMain.handle("flight-deck-preferences-save", flightDeckPreferences.save);

// The notes panel size is a file rather than browser storage: File > Restart and Clear Cache
// & Reload clear that storage, and a fallback backend port moves the app to another origin.
const notesPanelPreferences = preferencesFileHandlers(getNotesPanelPrefsPath, "notes panel");
ipcMain.handle("notes-panel-preferences-load", notesPanelPreferences.load);
ipcMain.handle("notes-panel-preferences-save", notesPanelPreferences.save);

// The table Custom Colors, shared by every method page of this user.
const tableColorPreferences = preferencesFileHandlers(getTableColorsPrefsPath, "table colors");
ipcMain.handle("table-colors-preferences-load", tableColorPreferences.load);
ipcMain.handle("table-colors-preferences-save", tableColorPreferences.save);

// The paths of the settings files each panel saved or loaded last, keyed by the file's kind.
const recentSettingsFilePreferences = preferencesFileHandlers(getRecentSettingsFilesPrefsPath, "recent settings files");
ipcMain.handle("recent-settings-files-preferences-load", recentSettingsFilePreferences.load);
ipcMain.handle("recent-settings-files-preferences-save", recentSettingsFilePreferences.save);

ipcMain.handle("scripting-last-notebook-load", async () => {
  const filePath = getScriptingNotebookPrefsPath();
  try {
    if (!fs.existsSync(filePath)) return { exists: false };
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    const recentPaths = normalizeRecentIpynbPaths(parsed?.recentIpynbPaths, parsed?.lastIpynbPath || parsed?.lastNotebookPath || "");
    const notebookPath = recentPaths[0] || "";
    if (!notebookPath || path.extname(notebookPath).toLowerCase() !== ".ipynb") {
      return { exists: false, recentPaths };
    }
    if (!fs.existsSync(notebookPath)) {
      return { exists: false, path: notebookPath, missing: true, recentPaths };
    }
    const stat = fs.statSync(notebookPath);
    if (!stat.isFile()) return { exists: false, path: notebookPath, error: "Path is not a file.", recentPaths };
    return { exists: true, path: notebookPath, recentPaths, updated_at: String(parsed?.updated_at || "") };
  } catch (err) {
    return { exists: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("scripting-recent-notebooks-load", async () => {
  const filePath = getScriptingNotebookPrefsPath();
  try {
    if (!fs.existsSync(filePath)) return { exists: false, recentPaths: [] };
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    const recentPaths = normalizeRecentIpynbPaths(parsed?.recentIpynbPaths, parsed?.lastIpynbPath || parsed?.lastNotebookPath || "")
      .filter((notebookPath) => {
        try {
          return fs.existsSync(notebookPath) && fs.statSync(notebookPath).isFile();
        } catch {
          return false;
        }
      });
    return { exists: recentPaths.length > 0, recentPaths, updated_at: String(parsed?.updated_at || "") };
  } catch (err) {
    return { exists: false, recentPaths: [], error: String(err?.message || err) };
  }
});

ipcMain.handle("scripting-last-notebook-save", async (_event, payload) => {
  const notebookPath = String(payload?.path || "").trim();
  if (!notebookPath) return { ok: false, error: "Empty notebook path." };
  if (path.extname(notebookPath).toLowerCase() !== ".ipynb") {
    return { ok: false, error: "Only .ipynb notebook paths are stored." };
  }
  const filePath = getScriptingNotebookPrefsPath();
  try {
    let existing = {};
    if (fs.existsSync(filePath)) {
      try { existing = JSON.parse(fs.readFileSync(filePath, "utf8")) || {}; } catch { existing = {}; }
    }
    const recentIpynbPaths = normalizeRecentIpynbPaths(existing?.recentIpynbPaths, notebookPath);
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    const data = {
      lastIpynbPath: recentIpynbPaths[0] || notebookPath,
      recentIpynbPaths,
      updated_at: new Date().toISOString(),
    };
    const tmpPath = `${filePath}.tmp`;
    fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2), "utf8");
    fs.renameSync(tmpPath, filePath);
    return { ok: true, path: filePath };
  } catch (err) {
    return { ok: false, error: String(err?.message || err) };
  }
});

ipcMain.handle("app-shutdown", async () => {
  allowClose = true;
  await requestBackendShutdown();
  app.quit();
  return true;
});

ipcMain.handle("app-shared-window-count", () => getSharedBackendClientCount());

ipcMain.handle("app-check-for-update", async () => checkForUpdate({ showNoUpdate: true }));

ipcMain.handle("app-release-history", async () => readLocalReleaseHistory());

ipcMain.handle("app-info", async () => ({
  mode: APP_MODE,
  version: app.getVersion(),
  displayVersion: APP_DISPLAY_VERSION,
  isPackaged: app.isPackaged,
}));

ipcMain.handle("app-toggle-dev-panel", () => {
  return toggleDevPanelForWindow();
});

ipcMain.handle("arcode-window-open", async (_event, payload) => {
  createArcodeWindow(payload || {});
  return { ok: true };
});

async function clearWindowCacheAndStorage(targetWindow, payload) {
  if (!targetWindow || targetWindow.isDestroyed()) return false;
  pendingClearCacheReloadRestore = payload?.restore && typeof payload.restore === "object"
    ? payload.restore
    : null;
  const requestedTheme = normalizeColorThemePreference(payload?.colorTheme);
  if (requestedTheme) saveColorThemePreference(requestedTheme);
  const requestedTableStyle = normalizeTableStylePreference(payload?.tableStyle);
  if (requestedTableStyle) saveTableStylePreference(requestedTableStyle);
  try {
    await targetWindow.webContents.session.clearCache();
    await targetWindow.webContents.session.clearStorageData();
    return true;
  } catch {
    return false;
  }
}

ipcMain.handle("app-clear-cache", async (event, payload) => {
  const targetWindow = getIpcWindow(event) || win;
  return clearWindowCacheAndStorage(targetWindow, payload);
});

ipcMain.handle("app-clear-cache-reload", async (event, payload) => {
  const targetWindow = getIpcWindow(event) || win;
  if (!targetWindow || targetWindow.isDestroyed()) return false;
  await clearWindowCacheAndStorage(targetWindow, payload);
  const webContents = targetWindow.webContents;
  const allowForcedReload = (unloadEvent) => {
    // Clear Cache & Reload is an explicit destructive navigation. Electron's
    // preventDefault here ignores renderer beforeunload cancellation.
    unloadEvent.preventDefault();
  };
  webContents.on("will-prevent-unload", allowForcedReload);
  try {
    const uiVersion = String(Date.now());
    const isArcodeReload = APP_MODE === "arcode"
      || targetWindow === arcodeWin
      || pendingClearCacheReloadRestore?.kind === "arcode-clear-cache-reload-restore-v1";
    const reloadUrl = isArcodeReload
      ? buildArcodeUrl({ uiVersion })
      : buildArcRhoUrl({ uiVersion });
    await targetWindow.loadURL(reloadUrl);
    return true;
  } catch (error) {
    console.error("Clear Cache & Reload navigation failed:", error);
    return false;
  } finally {
    if (!webContents.isDestroyed()) {
      webContents.removeListener("will-prevent-unload", allowForcedReload);
    }
  }
});

ipcMain.handle("app-consume-clear-cache-reload-restore", async () => {
  const restore = pendingClearCacheReloadRestore;
  pendingClearCacheReloadRestore = null;
  return restore || null;
});

const arcBotHost = registerArcBotIpc({
  ipcMain,
  app,
  APP_ROOT,
  REPO_ROOT,
  PYTHON_EXE,
  getPrefsDir,
  getWorkspacePathsPath,
  findExecutableOnPath,
  runHostCommand,
  getAppServerUrl: () => `http://${HOST}:${getBackendPort()}`,
});
registerUiAutomationIpc({
  ipcMain,
  BrowserWindow,
  getMainWindow: () => win,
  getArcodeWindow: () => arcodeWin,
  getSplashWindow: () => splashWin,
});

// Lets an agent drive an Arco window, and only that window; see tools/arco_window_control.
const agentWindowControl = createAgentWindowControl({
  BrowserWindow,
  globalShortcut,
  screen,
  getMainWindow: () => win,
  getArcodeWindow: () => arcodeWin,
  entryPath: path.join(app.getPath("appData"), APP_MODE === "arcode" ? "Arcode" : "ArcRho", "agent_window_control.json"),
  appMode: APP_MODE,
  log: appendElectronLog,
});

function getIpcWindow(event) {
  return BrowserWindow.fromWebContents(event?.sender) || BrowserWindow.getFocusedWindow() || win;
}

ipcMain.handle("focus-window", (event) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow || targetWindow.isDestroyed()) return;
  if (targetWindow.isMinimized()) targetWindow.restore();
  targetWindow.show();
  targetWindow.focus();
});
ipcMain.handle("get-documents-path", () => {
  try {
    return app.getPath("documents") || "";
  } catch {
    return "";
  }
});
ipcMain.handle("get-windows-user-name", () => {
  const envUser = String(process.env.USERNAME || process.env.USER || "").trim();
  if (envUser) return envUser;
  try {
    return String(os.userInfo()?.username || "").trim();
  } catch {
    return "";
  }
});
ipcMain.handle("windows-frame-style", () => WINDOWS_FRAME_STYLE);
ipcMain.handle("window-minimize", (event) => getIpcWindow(event)?.minimize());
ipcMain.handle("window-maximize", (event) => getIpcWindow(event)?.maximize());
ipcMain.handle("window-restore-native", (event) => getIpcWindow(event)?.restore());
ipcMain.handle("window-close", (event) => getIpcWindow(event)?.close());
ipcMain.handle("window-is-maximized", (event) => !!getIpcWindow(event)?.isMaximized());
ipcMain.handle("window-is-fullscreen", (event) => !!getIpcWindow(event)?.isFullScreen());
ipcMain.handle("window-set-fullscreen", (event, payload) => {
  const enabled = !!payload?.enabled;
  getIpcWindow(event)?.setFullScreen(enabled);
});
ipcMain.handle("window-get-size", (event) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return { width: 0, height: 0 };
  const [width, height] = targetWindow.getSize();
  return { width, height };
});
ipcMain.handle("window-resize", (event, payload) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return;
  const w = Math.max(200, Number(payload?.width || 0));
  const h = Math.max(200, Number(payload?.height || 0));
  if (w && h) targetWindow.setSize(Math.round(w), Math.round(h));
});

ipcMain.handle("window-set-background-color", (event, payload) => {
  const color = normalizeWindowBackgroundColor(payload?.color, "");
  if (!color) return false;
  const targetWindow = getIpcWindow(event);
  if (!targetWindow || targetWindow.isDestroyed()) return false;
  try {
    targetWindow.setBackgroundColor(color);
    saveCachedWindowBackgroundColor(color);
    return true;
  } catch {
    return false;
  }
});

ipcMain.handle("color-theme-preference-load", () => {
  const theme = loadColorThemePreference();
  return { exists: !!theme, theme: theme || "light" };
});

ipcMain.handle("color-theme-preference-save", (_event, payload) => {
  const theme = normalizeColorThemePreference(payload?.theme);
  if (!theme) return { ok: false, error: "Invalid color theme." };
  return saveColorThemePreference(theme)
    ? { ok: true, theme }
    : { ok: false, error: "Could not save the color theme preference." };
});

ipcMain.handle("table-style-preference-load", () => {
  const tableStyle = loadTableStylePreference();
  return { exists: !!tableStyle, tableStyle: tableStyle || "revolutionary" };
});

ipcMain.handle("table-style-preference-save", (_event, payload) => {
  const tableStyle = normalizeTableStylePreference(payload?.tableStyle);
  if (!tableStyle) return { ok: false, error: "Invalid table style." };
  return saveTableStylePreference(tableStyle)
    ? { ok: true, tableStyle }
    : { ok: false, error: "Could not save the table style preference." };
});

ipcMain.handle("zoom-get", (event) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return 1;
  return targetWindow.webContents.getZoomFactor();
});

ipcMain.handle("zoom-set", (event, payload) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return 1;
  const factor = Number(payload?.factor || 1);
  const safe = Math.max(0.5, Math.min(2, factor));
  targetWindow.webContents.setZoomFactor(safe);
  return safe;
});

ipcMain.handle("window-pseudo-maximize", (event, payload) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return;
  const margin = Math.max(0, Number(payload?.margin ?? 1));
  lastBounds = targetWindow.getBounds();
  const display = screen.getDisplayMatching(lastBounds);
  const wa = display.workArea;
  const w = Math.max(200, wa.width - margin * 2);
  const h = Math.max(200, wa.height - margin * 2);
  targetWindow.setBounds({ x: wa.x + margin, y: wa.y + margin, width: w, height: h }, true);
  pseudoMaximized = true;
});

ipcMain.handle("window-is-pseudo-maximized", () => !!pseudoMaximized);

ipcMain.handle("window-restore-to-last", (event) => {
  const targetWindow = getIpcWindow(event);
  if (!targetWindow) return;
  if (lastBounds) targetWindow.setBounds(lastBounds, true);
  pseudoMaximized = false;
});

app.whenReady().then(async () => {
  appendElectronLog(
    `Arco startup begin. packaged=${app.isPackaged}; version=${app.getVersion()}; appPath=${app.getAppPath()}; resourcesPath=${process.resourcesPath}`
  );
  registerBackendClient();
  agentWindowControl.listen();

  // Show splash screen first
  appendElectronLog("Creating splash window.");
  createSplashWindow();

  // Small delay to ensure splash is visible
  await new Promise((r) => setTimeout(r, 300));

  try {
    if (START_BACKEND) {
      updateSplashProgress(10, "Starting app server...");

      updateSplashProgress(30, "Waiting for server...");
      appendElectronLog("Starting bundled/backend app server.");
      await startBackendWithRetry();
      registerBackendClient();

      updateSplashProgress(60, "Server connected");
      appendElectronLog("App server connected.");
    }

    updateSplashProgress(80, "Loading interface...");
    appendElectronLog("Creating main window.");
    createWindow();

    // Wait for main window to be ready before closing splash
    win.webContents.once("did-finish-load", () => {
      appendElectronLog("Main window finished loading.");
      updateSplashProgress(100, "Launching application...");
      setTimeout(() => {
        closeSplash();
        win.show();
        win.focus();
        // app_endpoint.json appears when the BACKEND is ready, well before the window paints, so a
        // harness that waits on it screenshots the splash. This marker means the UI is visible.
        writeUiReadyMarker();
        // Deletes the installer this launch was produced by; it is still locked
        // while setup exits, so this runs after the window is up, not before.
        cleanupCompletedUpdateInstaller().catch((err) => {
          console.warn(`Arco update installer cleanup failed: ${err?.message || err}`);
        });
        if (APP_MODE !== "arcode") {
          setTimeout(() => {
            checkForStartupUpdate().catch((err) => {
              console.warn(`Arco startup update check failed: ${err?.message || err}`);
            });
          }, 750);
        }
      }, 400);
    });

  } catch (err) {
    appendElectronLog("Startup error", err);
    console.error("Startup error:", err);
    closeSplash();
    dialog.showErrorBox(
      "Arco startup failed",
      `${String(err?.message || err)}\n\nLog: ${getElectronLogPath()}`
    );
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// Everything that has to be gone before this process ends. For an update the
// backend is stopped outright and its exit confirmed, since setup replaces
// the files it runs from; a normal quit leaves a backend other windows share.
async function prepareQuit({ forUpdate = false } = {}) {
  allowClose = true;
  for (const watchId of Array.from(arcodeFolderWatchers.keys())) {
    closeArcodeFolderWatch(watchId);
  }
  arcBotHost?.stop();
  agentWindowControl.dispose();
  removeUiReadyMarker();
  const backendStopped = forUpdate ? await stopBackendForUpdate() : (await requestBackendShutdown(), true);
  unregisterBackendClient();
  cleanupBackendEndpoint();
  return backendStopped;
}

// Electron does not wait for an async before-quit handler, so the shutdown
// used to race the exit: the backend's stop request could be cut off and its
// client marker left behind. Hold the quit until the cleanup is done, then
// let the second pass through.
let quitPrepared = false;
app.on("before-quit", (event) => {
  if (quitPrepared) return;
  event.preventDefault();
  prepareQuit()
    .catch((err) => appendElectronLog("Shutdown cleanup failed", err))
    .finally(() => {
      quitPrepared = true;
      app.quit();
    });
});
