import { getHostApi, shell } from "../shell/shell_context.js?v=20260510a";
import { macroContextFingerprint } from "./macro_context_fingerprint.js?v=20260722a";
import { syncLibraryMacros } from "./macro_library_client.js?v=20260908a";
import { openMacroLibraryWindow } from "./macro_library_window.js?v=20260908a";
import { createMacroWindowFrame } from "./macro_window_frame.js?v=20260808b";
// Same version stamp as the shell's own import, so both share one module and one window identity.
import { AUTOMATION_CLIENT_ID } from "../shell/ui_automation.js?v=20260904resize2";
import { focusMacroListItem, initMacroListDrag, initMacroListKeyboard, syncMacroListSelection } from "./macro_list_interactions.js?v=20260908a";

const API_BASE = window.location.origin;
const MACRO_WINDOW_FRAGMENT_URL = "/ui/macro/macro_window.html?v=20260731b";
const TASK_DESIGNER_COMMAND_MESSAGE = "arcrho:task-designer-automation-command";
const MACRO_WINDOW_POSITION_KEY = "arcrho_macro_window_position";
const MACRO_SPLIT_HEIGHT_KEY = "arcrho_macro_window_split_height";
const MACRO_PINNED_KEY = "arcrho_macro_window_pinned";
const MACRO_MIN_LIST_HEIGHT = 100;
const MACRO_MIN_DESCRIPTION_HEIGHT = 76;
const EXTERNAL_MACRO_CAPTURE_TTL_MS = 5 * 60 * 1000;
const MACRO_SCOPE_LABELS = {
  dfm: "DFM",
  "result selection": "Result Selection",
  result_selection: "Result Selection",
  "restult selection": "Result Selection",
  "reserving class": "Reserving Class",
  reserving_class: "Reserving Class",
  project: "Project",
};

let macroWindow = null;
let macroCloseBtn = null;
let macroRefreshBtn = null;
let macroLibraryBtn = null;
let macroPinBtn = null;
let macroRunBtn = null;
let macroEditBtn = null;
let macroList = null;
let macroDescription = null;
let macroStatus = null;
let macroHeader = null;
let macroContent = null;
let macroSplitHandle = null;
let macros = [];
let selectedMacroId = "";
let macroWindowWired = false;
let macroWindowLoadPromise = null;
let macroSplitCustomized = false;
let macroSplitContextMenu = null;
let macroItemContextMenu = null;
let macroWindowFrame = null;
const capturedExternalMacroTargets = new Map();

function refreshMacroElements() {
  macroWindow = document.getElementById("macroWindow");
  macroCloseBtn = document.getElementById("macroCloseBtn");
  macroRefreshBtn = document.getElementById("macroRefreshBtn");
  macroLibraryBtn = document.getElementById("macroLibraryBtn");
  macroPinBtn = document.getElementById("macroPinBtn");
  macroRunBtn = document.getElementById("macroRunBtn");
  macroEditBtn = document.getElementById("macroEditBtn");
  macroList = document.getElementById("macroList");
  macroDescription = document.getElementById("macroDescription");
  macroStatus = document.getElementById("macroStatus");
  macroHeader = document.getElementById("macroHeader");
  macroContent = document.getElementById("macroContent") || macroWindow?.querySelector?.(".macroContent") || null;
  macroSplitHandle = document.getElementById("macroSplitHandle");
  return !!macroWindow;
}

async function ensureMacroWindowDom() {
  if (refreshMacroElements()) return true;
  if (!macroWindowLoadPromise) {
    macroWindowLoadPromise = fetch(MACRO_WINDOW_FRAGMENT_URL)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then((markup) => {
        if (document.getElementById("macroWindow")) return;
        const template = document.createElement("template");
        template.innerHTML = markup.trim();
        const fragment = template.content;
        const tabContextMenu = document.getElementById("tabCtxMenu");
        if (tabContextMenu) {
          tabContextMenu.before(fragment);
        } else {
          document.body.appendChild(fragment);
        }
      })
      .catch((err) => {
        macroWindowLoadPromise = null;
        throw err;
      });
  }
  try {
    await macroWindowLoadPromise;
  } catch (err) {
    const message = String(err?.message || err || "unable to load macro window");
    shell.updateStatusBar?.(`Macro window failed to load: ${message}`, { tone: "error" });
    return false;
  }
  return refreshMacroElements();
}

function setMacroStatus(text, tone = "", options = {}) {
  const message = String(text || "");
  if (macroStatus) {
    macroStatus.textContent = message;
    macroStatus.title = message;
    macroStatus.dataset.tone = tone || "";
  }
  if (options.statusBar && message) {
    shell.updateStatusBar?.(message, { tone: tone || "" });
  }
}

function readMacroPinned() {
  try {
    return localStorage.getItem(MACRO_PINNED_KEY) === "1";
  } catch {
    return false;
  }
}

function saveMacroPinned(pinned) {
  try {
    localStorage.setItem(MACRO_PINNED_KEY, pinned ? "1" : "0");
  } catch {}
}

function applyMacroPinned(pinned) {
  if (!macroWindow) return;
  const isPinned = !!pinned;
  macroWindow.classList.toggle("pinned", isPinned);
  if (macroPinBtn) {
    macroPinBtn.classList.toggle("active", isPinned);
    macroPinBtn.setAttribute("aria-pressed", isPinned ? "true" : "false");
    macroPinBtn.title = isPinned ? "Unpin macros from top" : "Pin macros on top";
    macroPinBtn.setAttribute("aria-label", isPinned ? "Unpin macros from top" : "Pin macros on top");
  }
}

function toggleMacroPinned() {
  const next = !macroWindow?.classList.contains("pinned");
  applyMacroPinned(next);
  saveMacroPinned(next);
}

function normalizeMacroScope(value) {
  const key = String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
  return MACRO_SCOPE_LABELS[key] || "";
}

function macroScopes(macro) {
  const raw = Array.isArray(macro?.scopes) && macro.scopes.length ? macro.scopes : [macro?.scope];
  const out = [];
  const seen = new Set();
  raw.forEach((item) => {
    const label = normalizeMacroScope(item);
    if (!label || seen.has(label)) return;
    seen.add(label);
    out.push(label);
  });
  return out.length ? out : ["DFM"];
}

function scopeClassName(scope) {
  return String(scope || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function getSelectedMacro() {
  return macros.find((macro) => macro.id === selectedMacroId) || null;
}

function isDfmTab(tab) {
  return !!tab && (tab.type === "dfm" || (tab.type === "project_instance" && tab.piDfmActive));
}

function isTaskDesignerWrapperMacro(macro) {
  if (!macro) return false;
  if (macro.task_designer_wrapper || macro.taskDesignerWrapper) return true;
  const haystack = `${macro.name || ""} ${macro.description || ""} ${macro.id || ""}`.toLowerCase();
  return haystack.includes("task designer wrapper") || haystack.includes("task instance");
}

function canDeleteMacro(macro) {
  return !!macro?.path;
}

// The display order belongs to the user, so it is kept in the `macros` section of their
// preferences on the Arco Server, through the desktop host, rather than in browser storage.
async function readMacroOrder() {
  const result = await getHostApi()?.loadMacroPreferences?.();
  const order = result?.preferences?.order;
  return Array.isArray(order) ? order.map((id) => String(id || "")).filter(Boolean) : [];
}

function saveMacroOrder(order) {
  void getHostApi()?.saveMacroPreferences?.({ version: 1, order });
}

function orderedMacroList(items, order) {
  const list = Array.isArray(items) ? items : [];
  if (!order.length) return list;
  const rank = new Map(order.map((id, index) => [id, index]));
  return [...list].sort((a, b) => {
    const aRank = rank.has(a.id) ? rank.get(a.id) : Number.MAX_SAFE_INTEGER;
    const bRank = rank.has(b.id) ? rank.get(b.id) : Number.MAX_SAFE_INTEGER;
    if (aRank !== bRank) return aRank - bRank;
    return list.indexOf(a) - list.indexOf(b);
  });
}

function persistCurrentMacroOrder() {
  saveMacroOrder(macros.map((macro) => macro.id).filter(Boolean));
}

function moveSelectedMacro(delta) {
  const index = macros.findIndex((macro) => macro.id === selectedMacroId);
  if (index < 0) {
    setMacroStatus("Select a macro before moving it.", "error", { statusBar: true });
    return;
  }
  const nextIndex = index + delta;
  if (nextIndex < 0 || nextIndex >= macros.length) {
    setMacroStatus(delta < 0 ? "Macro is already at the top." : "Macro is already at the bottom.", "", { statusBar: true });
    return;
  }
  const [item] = macros.splice(index, 1);
  macros.splice(nextIndex, 0, item);
  persistCurrentMacroOrder();
  renderMacroList();
  renderMacroDescription();
  setMacroStatus(`Moved ${item.name || item.id} ${delta < 0 ? "up" : "down"}.`, "", { statusBar: true });
}

function reorderMacro(id, beforeId) {
  const [item] = macros.splice(macros.findIndex((macro) => macro.id === id), 1);
  const to = beforeId ? macros.findIndex((macro) => macro.id === beforeId) : macros.length;
  macros.splice(to, 0, item);
  persistCurrentMacroOrder();
  renderMacroList();
  focusMacroListItem(macroList, id);
  setMacroStatus(`Moved ${item.name || item.id}.`, "", { statusBar: true });
}

function selectMacro(id) {
  selectedMacroId = id;
  syncMacroListSelection(macroList, id);
  renderMacroDescription();
}

function libraryUpdateMessage(updated) {
  const names = updated.map((entry) => `${entry.name || entry.macro_id} to v${entry.version}`);
  return `Updated ${names.join(", ")} from the shared macro library.`;
}

// The library sits on the server workspace, so it is read after the local list
// is already on screen. Every loaded macro the library holds a newer version of
// is replaced on the spot; the status bar names what changed, and the
// local-macros event the sync raises reloads the list. An unreachable library
// leaves the list as it is without delaying or failing it.
async function applyMacroLibraryUpdates() {
  let updated = [];
  try {
    updated = await syncLibraryMacros();
  } catch {
    return;
  }
  if (updated.length) setMacroStatus(libraryUpdateMessage(updated), "", { statusBar: true });
}

function renderMacroList() {
  if (!macroList) return;
  const items = macros;
  macroList.textContent = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "macroEmpty";
    empty.textContent = "No macros found.";
    macroList.appendChild(empty);
    return;
  }
  if (!selectedMacroId || !items.some((macro) => macro.id === selectedMacroId)) {
    selectedMacroId = items[0]?.id || "";
  }
  items.forEach((macro) => {
    const item = document.createElement("button");
    item.className = "macroListItem";
    item.type = "button";
    item.dataset.id = macro.id;
    item.classList.toggle("active", macro.id === selectedMacroId);
    item.setAttribute("aria-selected", macro.id === selectedMacroId ? "true" : "false");
    const topRow = document.createElement("span");
    topRow.className = "macroListItemTop";
    const title = document.createElement("span");
    title.className = "macroListItemName";
    title.textContent = macro.name || macro.id;
    topRow.appendChild(title);
    const tags = document.createElement("span");
    tags.className = "macroScopeTags";
    macroScopes(macro).forEach((scope) => {
      const tag = document.createElement("span");
      tag.className = `macroScopeTag ${scopeClassName(scope)}`;
      tag.textContent = scope;
      tags.appendChild(tag);
    });
    topRow.appendChild(tags);
    item.appendChild(topRow);
    item.addEventListener("click", () => selectMacro(macro.id));
    item.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      event.stopPropagation();
      selectMacro(macro.id);
      showMacroItemContextMenu(event.clientX, event.clientY);
    });
    macroList.appendChild(item);
  });
}

function renderMacroDescription() {
  const macro = getSelectedMacro();
  if (!macroDescription) return;
  if (!macro) {
    macroDescription.textContent = "Select a macro to view its description.";
    if (macroRunBtn) macroRunBtn.disabled = true;
    if (macroEditBtn) macroEditBtn.disabled = true;
    return;
  }
  macroDescription.textContent = macro.description || "This macro has no description section yet.";
  if (macroRunBtn) macroRunBtn.disabled = false;
  if (macroEditBtn) macroEditBtn.disabled = false;
}

async function loadMacros() {
  setMacroStatus("Loading macros...");
  try {
    const [loadedMacros, order] = await Promise.all([
      fetch(`${API_BASE}/scripting/macros`).then((response) => response.json()),
      readMacroOrder(),
    ]);
    const liveMacros = Array.isArray(loadedMacros) ? loadedMacros : [];
    macros = orderedMacroList(liveMacros, order);
    renderMacroList();
    renderMacroDescription();
    setMacroStatus(`${liveMacros.length} macro(s) available.`);
    void applyMacroLibraryUpdates();
  } catch (err) {
    macros = [];
    renderMacroList();
    renderMacroDescription();
    const message = String(err?.message || err || "Failed to load macros.");
    setMacroStatus(`Failed to load macros. ${message}`, "error");
  }
}

function openSharedMacroLibrary() {
  void openMacroLibraryWindow();
}

function getActiveDfmTab(preferredTabId = "") {
  const tabs = shell.state?.tabs || [];
  const preferred = preferredTabId ? tabs.find((tab) => tab.id === preferredTabId) : null;
  if (isDfmTab(preferred)) return preferred;
  const active = tabs.find((tab) => tab.id === shell.state.activeId);
  if (isDfmTab(active)) return active;
  const lastDocked = tabs.find((tab) => tab.id === shell.state.lastDockedActiveId);
  if (isDfmTab(lastDocked)) return lastDocked;
  return null;
}

function requestActiveDfmContext(tabOverride = null, targetWindowId = "") {
  const isTargetedProjectInstance = !!targetWindowId && tabOverride?.type === "project_instance";
  const tab = isDfmTab(tabOverride) || isTargetedProjectInstance ? tabOverride : getActiveDfmTab();
  if (!tab) return Promise.resolve({ available: false, error: "Open or activate a DFM tab/window before running a macro." });
  shell.ensureIframe?.(tab);
  const iframe = tab.iframe;
  if (!iframe?.contentWindow) {
    return Promise.resolve({ available: false, error: "The active DFM target is not ready yet." });
  }
  return new Promise((resolve) => {
    const requestId = `macro_context_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let done = false;
    const finish = (context) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      resolve(context || { available: false, error: "DFM context failed." });
    };
    const onMessage = (event) => {
      if (event.source !== iframe.contentWindow) return;
      const msg = event.data || {};
      if (msg.type !== "arcrho:assistant-context-result" || msg.requestId !== requestId) return;
      finish(msg.context || {});
    };
    window.addEventListener("message", onMessage);
    try {
      iframe.contentWindow.postMessage({
        type: "arcrho:assistant-context-request",
        requestId,
        targetWindowId: String(targetWindowId || ""),
      }, "*");
    } catch {
      finish({ available: false, error: "Could not request DFM context." });
      return;
    }
    setTimeout(() => finish({ available: false, error: "Timed out reading active DFM context." }), 1500);
  });
}

function cleanupCapturedExternalMacroTargets() {
  const cutoff = Date.now() - EXTERNAL_MACRO_CAPTURE_TTL_MS;
  capturedExternalMacroTargets.forEach((capture, token) => {
    if (Number(capture?.createdAt || 0) < cutoff) capturedExternalMacroTargets.delete(token);
  });
}

export async function captureActiveDfmContextForMacro() {
  cleanupCapturedExternalMacroTargets();
  const tab = getActiveDfmTab();
  const token = globalThis.crypto?.randomUUID?.()
    || `macro_capture_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  if (!tab) {
    const activeTab = (shell.state?.tabs || []).find((item) => item.id === shell.state?.activeId) || null;
    const activeContext = {
      available: false,
      pageType: String(activeTab?.type || ""),
      tabType: String(activeTab?.type || ""),
      title: String(activeTab?.title || activeTab?.name || ""),
      error: "No active DFM is available; active_dfm will be None.",
    };
    const target = { token, kind: "ui", tabId: "", tabType: "", nestedWindowId: "", methodPath: "" };
    capturedExternalMacroTargets.set(token, {
      ...target,
      createdAt: Date.now(),
      fingerprint: "",
      hasDfm: false,
    });
    return { ok: true, activeContext, target };
  }
  const activeContext = await requestActiveDfmContext(tab);
  if (!activeContext?.available || !activeContext?.activeJson) {
    return { ok: false, error: activeContext?.error || "Active DFM JSON is not available." };
  }
  const nestedWindowId = String(activeContext?.activeNestedWindow?.windowId || "");
  if (tab.type === "project_instance" && !nestedWindowId) {
    return { ok: false, error: "Arco could not identify the active Project Instance DFM window." };
  }
  const target = {
    token,
    kind: "dfm",
    tabId: String(tab.id || ""),
    tabType: String(tab.type || ""),
    nestedWindowId,
    methodPath: String(activeContext.methodPath || activeContext.targetPath || ""),
  };
  capturedExternalMacroTargets.set(token, {
    ...target,
    createdAt: Date.now(),
    fingerprint: macroContextFingerprint(activeContext),
    hasDfm: true,
  });
  return { ok: true, activeContext, target };
}

function macroTaskRows(macro) {
  const tasks = Array.isArray(macro?.tasks) ? macro.tasks : [];
  return tasks.map((task, index) => ({
    taskId: String(task.task_id || task.taskId || `task_${index + 1}`),
    name: String(task.name || task.macro_id || task.macroId || `Task ${index + 1}`),
    description: String(task.description || ""),
    status: "pending",
    message: "",
  }));
}

function taskDesignerTitleForMacro(macro) {
  return String(macro?.name || "Task Designer").replace(/\s+Task\s+Instance\s*$/i, "").trim() || "Task Designer";
}

function waitForIframeReady(iframe, timeoutMs = 2500) {
  if (!iframe) return Promise.resolve(false);
  try {
    const doc = iframe.contentDocument;
    if (doc && (doc.readyState === "interactive" || doc.readyState === "complete")) {
      return Promise.resolve(true);
    }
  } catch {}
  return new Promise((resolve) => {
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      iframe.removeEventListener("load", onLoad);
      window.clearTimeout(timer);
      resolve(!!ok);
    };
    const onLoad = () => finish(true);
    const timer = window.setTimeout(() => finish(false), timeoutMs);
    iframe.addEventListener("load", onLoad, { once: true });
  });
}

async function seedTaskDesignerRows(tab, rows, sessionId = "") {
  if (!tab || !rows.length) return;
  shell.ensureIframe?.(tab);
  const iframe = tab.iframe;
  if (!iframe?.contentWindow) return;
  await waitForIframeReady(iframe);
  try {
    iframe.contentWindow.postMessage({
      type: TASK_DESIGNER_COMMAND_MESSAGE,
      requestId: `macro_task_seed_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      command: "taskDesigner.setTasks",
      args: { windowId: "task-designer-main", sessionId, tasks: rows },
    }, "*");
  } catch {}
}

function applyPayloadToDfmTarget(payload, target = null) {
  const targetTabId = String(target?.tabId || "");
  const tab = targetTabId
    ? (shell.state?.tabs || []).find((item) => item.id === targetTabId)
    : getActiveDfmTab();
  const validTarget = tab?.type === "dfm"
    || (
      tab?.type === "project_instance"
      && (target ? !!String(target?.nestedWindowId || "") : !!tab.piDfmActive)
    );
  if (!tab || !validTarget) {
    return Promise.resolve({ ok: false, error: "The DFM captured for this macro is no longer open." });
  }
  shell.ensureIframe?.(tab);
  const iframe = tab.iframe;
  if (!iframe?.contentWindow) {
    return Promise.resolve({ ok: false, error: "The active DFM target is not ready yet." });
  }
  return new Promise((resolve) => {
    const requestId = `macro_apply_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      resolve(result || { ok: false, error: "DFM apply failed." });
    };
    const onMessage = (event) => {
      if (event.source !== iframe.contentWindow) return;
      const msg = event.data || {};
      if (msg.type !== "arcrho:dfm-apply-method-payload-result" || msg.requestId !== requestId) return;
      finish({ ok: !!msg.ok, error: String(msg.error || "") });
    };
    window.addEventListener("message", onMessage);
    try {
      iframe.contentWindow.postMessage({
        type: "arcrho:dfm-apply-method-payload",
        requestId,
        payload,
        targetWindowId: String(target?.nestedWindowId || ""),
      }, "*");
    } catch {
      finish({ ok: false, error: "Could not apply macro result to the DFM tab." });
      return;
    }
    setTimeout(() => finish({ ok: false, error: "Timed out applying macro result." }), 3000);
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

function ensureMacroPreviewStyles() {
  if (document.getElementById("macro-notes-preview-style")) return;
  const style = document.createElement("style");
  style.id = "macro-notes-preview-style";
  style.textContent = `
    .macroNotesPreviewOverlay {
      position: fixed;
      inset: 0;
      z-index: 13000;
      background: rgba(15, 23, 42, 0.18);
      box-sizing: border-box;
    }
    .macroNotesPreviewWindow {
      position: fixed;
      width: min(980px, calc(100vw - 32px));
      min-width: min(620px, calc(100vw - 32px));
      height: min(720px, calc(100vh - 96px));
      min-height: 360px;
      max-width: calc(100vw - 16px);
      max-height: calc(100vh - 96px);
      display: flex;
      flex-direction: column;
      border: 1px solid #c8d0dc;
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 22px 54px rgba(15, 23, 42, 0.24);
      font-family: "Segoe UI", Tahoma, Arial, sans-serif;
      color: #172033;
      overflow: hidden;
      resize: both;
    }
    .macroNotesPreviewHeader {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 32px;
      padding: 3px 12px;
      border-bottom: 1px solid #e2e7ef;
      background: #f7f9fc;
      cursor: move;
      user-select: none;
    }
    .macroNotesPreviewTitle {
      margin: 0;
      font-size: 13px;
      font-weight: 700;
    }
    .macroNotesPreviewClose {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      box-sizing: border-box;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      cursor: pointer;
      font-size: 16px;
      line-height: 1;
      color: #5b6678;
    }
    .macroNotesPreviewClose:hover { background: #edf1f7; color: #1f2937; }
    .macroNotesPreviewBody {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
      padding: 16px;
      overflow: auto;
      scrollbar-gutter: stable;
    }
    .macroNotesPreviewStatus {
      margin: 0 0 14px;
      padding: 12px 14px;
      border-radius: 7px;
      border: 1px solid #c9d9f7;
      background: #eef5ff;
      color: #244a86;
      font-size: 13px;
      line-height: 1.4;
    }
    .macroNotesPreviewGrid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      min-height: 0;
    }
    .macroNotesPreviewCard {
      display: flex;
      flex-direction: column;
      min-width: 0;
      border: 1px solid #d9e0ea;
      border-radius: 7px;
      background: #fbfcff;
      padding: 12px;
    }
    .macroNotesPreviewCard.newest {
      border-color: #78b997;
      box-shadow: inset 0 0 0 1px #a8d9bd;
      background: #f3fbf6;
    }
    .macroNotesPreviewSourceLabel {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      width: fit-content;
      padding: 2px 9px;
      border: 1px solid #2457a6;
      border-radius: 6px;
      background: #e8f0ff;
      color: #173d78;
      font-weight: 800;
      font-size: 13px;
      line-height: 1.2;
      white-space: nowrap;
      margin-bottom: 9px;
    }
    .macroNotesPreviewText {
      flex: 1 1 auto;
      min-height: 0;
      max-height: 470px;
      margin: 0;
      padding: 10px;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #fff;
      overflow: auto;
      white-space: pre-wrap;
      font: 12px Consolas, "Courier New", monospace;
      color: #172033;
    }
    .macroNotesDeleted {
      background: #ffe3e3;
      color: #8f1d1d;
      border-radius: 2px;
    }
    .macroNotesAdded {
      background: #dcfce7;
      color: #14532d;
      border-radius: 2px;
    }
    .macroNotesPreviewActions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 10px 12px;
      border-top: 1px solid #e2e7ef;
      background: #fbfcff;
    }
    .macroNotesPreviewBtn {
      min-width: 82px;
      height: 28px;
      padding: 0 12px;
      border: 1px solid #cbd5e1;
      border-radius: 6px;
      background: #fff;
      color: #172033;
      cursor: pointer;
      font-size: 12px;
    }
    .macroNotesPreviewBtn.primary {
      border-color: #9bbcf7;
      background: #eff6ff;
      color: #1d4ed8;
      font-weight: 700;
    }
  `;
  document.head.appendChild(style);
}

function tokenizeDiffText(text) {
  return String(text || "").match(/\s+|[^\s]+/g) || [];
}

function buildTextDiff(oldText, newText) {
  const oldTokens = tokenizeDiffText(oldText);
  const newTokens = tokenizeDiffText(newText);
  const dp = Array.from({ length: oldTokens.length + 1 }, () => new Array(newTokens.length + 1).fill(0));
  for (let i = oldTokens.length - 1; i >= 0; i -= 1) {
    for (let j = newTokens.length - 1; j >= 0; j -= 1) {
      dp[i][j] = oldTokens[i] === newTokens[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const deleted = new Array(oldTokens.length).fill(false);
  const added = new Array(newTokens.length).fill(false);
  let i = 0;
  let j = 0;
  while (i < oldTokens.length && j < newTokens.length) {
    if (oldTokens[i] === newTokens[j]) {
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      deleted[i] = true;
      i += 1;
    } else {
      added[j] = true;
      j += 1;
    }
  }
  while (i < oldTokens.length) {
    deleted[i] = true;
    i += 1;
  }
  while (j < newTokens.length) {
    added[j] = true;
    j += 1;
  }
  return { oldTokens, newTokens, deleted, added };
}

function renderDiffTokens(tokens, flags, className) {
  const isWhitespaceToken = (token) => /^\s+$/.test(String(token || ""));
  const wordHighlighted = tokens.map((token, index) => !!flags[index] && !isWhitespaceToken(token));
  // Whitespace between two highlighted words joins the highlight so a changed
  // phrase renders as one connected fill instead of per-word patches.
  const effective = tokens.map((token, index) => {
    if (!isWhitespaceToken(token)) return wordHighlighted[index];
    return !!(wordHighlighted[index - 1] && wordHighlighted[index + 1]);
  });
  let html = "";
  let buffer = "";
  let highlighted = false;
  const flush = () => {
    if (!buffer) return;
    const text = escapeHtml(buffer);
    html += highlighted ? `<span class="${className}">${text}</span>` : text;
    buffer = "";
  };
  tokens.forEach((token, index) => {
    if (effective[index] !== highlighted) {
      flush();
      highlighted = effective[index];
    }
    buffer += token;
  });
  flush();
  return html;
}

function placeMacroPreviewWindow(dialogWindow) {
  const rect = dialogWindow.getBoundingClientRect();
  const top = Math.min(64, Math.max(16, Math.floor(window.innerHeight * 0.08)));
  const left = Math.max(8, Math.round((window.innerWidth - rect.width) / 2));
  dialogWindow.style.left = `${left}px`;
  dialogWindow.style.top = `${top}px`;
}

function enableMacroPreviewDrag(dialogWindow, header) {
  if (!dialogWindow || !header) return;
  header.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target?.closest?.("button")) return;
    const rect = dialogWindow.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const startLeft = rect.left;
    const startTop = rect.top;
    header.setPointerCapture?.(event.pointerId);
    event.preventDefault();
    const onMove = (moveEvent) => {
      dialogWindow.style.left = `${startLeft + moveEvent.clientX - startX}px`;
      dialogWindow.style.top = `${startTop + moveEvent.clientY - startY}px`;
    };
    const onUp = () => {
      header.releasePointerCapture?.(event.pointerId);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.removeEventListener("pointercancel", onUp);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  });
}

function showMacroNotesPreview(preview, options = {}) {
  ensureMacroPreviewStyles();
  const oldText = String(preview?.original_notes || "");
  const newText = String(preview?.suggested_notes || "");
  const diff = buildTextDiff(oldText, newText);
  const overlay = document.createElement("div");
  overlay.className = "macroNotesPreviewOverlay";
  const summary = String(preview?.summary || "Review the suggested Notes correction.");
  overlay.innerHTML = `
    <div class="macroNotesPreviewWindow" role="dialog" aria-modal="true" aria-labelledby="macroNotesPreviewTitle">
      <div class="macroNotesPreviewHeader">
        <h2 class="macroNotesPreviewTitle" id="macroNotesPreviewTitle">${escapeHtml(preview?.title || "Validate Notes")}</h2>
        <button class="macroNotesPreviewClose" type="button" aria-label="Close">&times;</button>
      </div>
      <div class="macroNotesPreviewBody">
        <div class="macroNotesPreviewStatus">${escapeHtml(summary)}</div>
        <div class="macroNotesPreviewGrid">
          <div class="macroNotesPreviewCard">
            <span class="macroNotesPreviewSourceLabel">Current Notes</span>
            <pre class="macroNotesPreviewText">${renderDiffTokens(diff.oldTokens, diff.deleted, "macroNotesDeleted") || "No notes"}</pre>
          </div>
          <div class="macroNotesPreviewCard newest">
            <span class="macroNotesPreviewSourceLabel">Suggested Notes</span>
            <pre class="macroNotesPreviewText">${renderDiffTokens(diff.newTokens, diff.added, "macroNotesAdded") || "No notes"}</pre>
          </div>
        </div>
      </div>
      <div class="macroNotesPreviewActions">
        <button class="macroNotesPreviewBtn primary" type="button" data-action="accept">Accept Corrected Notes</button>
        <button class="macroNotesPreviewBtn" type="button" data-action="cancel">Cancel</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  const dialogWindow = overlay.querySelector(".macroNotesPreviewWindow");
  const header = overlay.querySelector(".macroNotesPreviewHeader");
  placeMacroPreviewWindow(dialogWindow);
  enableMacroPreviewDrag(dialogWindow, header);
  return new Promise((resolve) => {
    let done = false;
    let expiryTimer = 0;
    const finish = (accepted, expired = false) => {
      if (done) return;
      done = true;
      if (expiryTimer) window.clearTimeout(expiryTimer);
      overlay.remove();
      resolve({ accepted: !!accepted, expired: !!expired });
    };
    overlay.querySelector(".macroNotesPreviewClose")?.addEventListener("click", () => finish(false));
    overlay.querySelector("[data-action='cancel']")?.addEventListener("click", () => finish(false));
    overlay.querySelector("[data-action='accept']")?.addEventListener("click", () => finish(true));
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") finish(false);
    });
    overlay.tabIndex = -1;
    overlay.focus();
    const expiresAt = Number(options.expiresAt || 0);
    if (expiresAt > 0) {
      expiryTimer = window.setTimeout(
        () => finish(false, true),
        Math.max(0, expiresAt - Date.now()),
      );
    }
  });
}

async function reviewAndApplyMacroResult(result = {}, target = null, options = {}) {
  const expiresAt = Number(options.expiresAt || 0);
  const isExpired = () => expiresAt > 0 && Date.now() >= expiresAt;
  if (isExpired()) {
    return { ok: false, error: "Macro review expired before the result could be applied." };
  }
  const preview = result.preview || null;
  if (preview?.type === "notes_diff") {
    if (!preview.has_changes) {
      return {
        ok: true,
        applied: false,
        message: String(preview.summary || "Validate Notes found no required changes."),
      };
    }
    const decision = await showMacroNotesPreview(preview, { expiresAt });
    if (decision.expired || isExpired()) {
      return { ok: false, error: "Macro review expired before the result could be applied." };
    }
    if (!decision.accepted) {
      return {
        ok: true,
        applied: false,
        cancelled: true,
        message: "Macro suggestion was not applied.",
      };
    }
  }
  if (result.payload && typeof result.payload === "object") {
    if (isExpired()) {
      return { ok: false, error: "Macro review expired before the result could be applied." };
    }
    if (typeof options.beforeApply === "function") {
      const validation = await options.beforeApply();
      if (!validation?.ok) {
        return { ok: false, error: validation?.error || "The captured DFM changed before apply." };
      }
    }
    if (isExpired()) {
      return { ok: false, error: "Macro review expired before the result could be applied." };
    }
    const applied = await applyPayloadToDfmTarget(result.payload, target);
    if (!applied?.ok) {
      return { ok: false, error: applied?.error || "Macro ran, but the DFM did not accept the result." };
    }
    return { ok: true, applied: true, message: "Macro applied to the captured DFM." };
  }
  return {
    ok: true,
    applied: false,
    message: String(result.message || "Macro completed."),
  };
}

export async function reviewAndApplyCapturedMacroResult(args = {}) {
  cleanupCapturedExternalMacroTargets();
  const token = String(args?.target?.token || "");
  const capture = capturedExternalMacroTargets.get(token);
  if (token) capturedExternalMacroTargets.delete(token);
  if (!capture) {
    return { ok: false, error: "The captured DFM context expired. Run the script again." };
  }
  if (args.discard) {
    return { ok: true, applied: false, message: "Discarded captured DFM context." };
  }

  const expiresAt = Number(args.expiresAt || 0);
  if (expiresAt > 0 && Date.now() >= expiresAt) {
    return { ok: false, error: "Macro review expired before the result could be applied." };
  }
  if (!capture.hasDfm) {
    if (args.payload && typeof args.payload === "object") {
      return { ok: false, error: "The script returned a DFM payload, but no DFM was active when it started." };
    }
    return reviewAndApplyMacroResult({
      preview: args.preview,
      message: args.message,
    }, null, { expiresAt });
  }

  const tab = (shell.state?.tabs || []).find((item) => item.id === capture.tabId);
  const validTarget = tab?.type === "dfm"
    || (tab?.type === "project_instance" && !!capture.nestedWindowId);
  if (!tab || !validTarget) {
    return { ok: false, error: "The DFM captured for this macro is no longer open." };
  }
  const validateCapturedContext = async () => {
    const currentContext = await requestActiveDfmContext(tab, capture.nestedWindowId);
    if (!currentContext?.available || !currentContext?.activeJson) {
      return { ok: false, error: currentContext?.error || "The captured DFM is no longer available." };
    }
    if (macroContextFingerprint(currentContext) !== capture.fingerprint) {
      return {
        ok: false,
        error: "The captured DFM changed while the macro was running. Its result was not applied; run it again.",
      };
    }
    return { ok: true };
  };
  const initialValidation = await validateCapturedContext();
  if (!initialValidation.ok) return initialValidation;
  return reviewAndApplyMacroResult({
    payload: args.payload,
    preview: args.preview,
    message: args.message,
  }, capture, { beforeApply: validateCapturedContext, expiresAt });
}

// One run path for every caller: the Run button, the macro context menu, and the Flight Deck.
// Returns whether the run finished so a caller can show its own success or failure feedback.
async function runMacro(macro) {
  if (!macro?.id) {
    const message = "Selected macro is missing an id.";
    setMacroStatus(message, "error", { statusBar: true });
    return { ok: false, message };
  }
  setMacroStatus(`Running macro: ${macro.name || macro.id}...`, "", { statusBar: true });
  if (macroRunBtn) macroRunBtn.disabled = true;
  try {
    const isTaskWrapper = isTaskDesignerWrapperMacro(macro);
    const contextTab = getActiveDfmTab();
    const taskSessionId = isTaskWrapper ? `macro_task_${Date.now()}_${Math.random().toString(36).slice(2)}` : "";
    if (isTaskWrapper) {
      const taskTab = shell.openTaskDesigner?.({
        title: taskDesignerTitleForMacro(macro),
        contextLabel: contextTab ? "Preparing active DFM validation..." : "Activate a DFM tab/window to validate live DFM data.",
        macroId: macro.id,
        contextTabId: contextTab?.id || "",
        sessionId: taskSessionId,
        reset: true,
      });
      setMacroStatus("Opened Task Designer; preparing validation context...", "", { statusBar: true });
      await seedTaskDesignerRows(taskTab, macroTaskRows(macro), taskSessionId);
    }
    const hasActiveDfm = !!contextTab;
    const activeContext = hasActiveDfm ? await requestActiveDfmContext(contextTab) : {
      available: false,
      pageType: shell.state?.tabs?.find?.((tab) => tab.id === shell.state.activeId)?.type || "",
      error: "Open or activate a DFM tab/window before running a macro.",
    };
    if (hasActiveDfm && (!activeContext?.available || !activeContext?.activeJson)) {
      throw new Error(activeContext?.error || "Active DFM JSON is not available.");
    }
    const response = await fetch(`${API_BASE}/scripting/run-macro`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        macro_id: macro.id,
        active_context: activeContext,
        task_window_id: isTaskWrapper ? "task-designer-main" : "",
        task_session_id: taskSessionId,
        task_mode: isTaskWrapper ? "wrapper" : "",
        client_id: AUTOMATION_CLIENT_ID,
      }),
    });
    const result = await response.json();
    // The app server replaced the local copy with a newer library version
    // before running it, so the list and the library window catch up.
    if (result?.library_update) {
      setMacroStatus(libraryUpdateMessage([result.library_update]), "", { statusBar: true });
      window.dispatchEvent(new CustomEvent("arcrho:local-macros-changed"));
    }
    if (!result?.success) {
      if (isTaskWrapper) {
        const message = result?.message || "Task Designer validation completed with issues.";
        setMacroStatus(message, "error", { statusBar: true });
        return { ok: false, message };
      }
      throw new Error(result?.message || "Macro failed.");
    }
    const reviewed = await reviewAndApplyMacroResult(result);
    if (!reviewed?.ok) throw new Error(reviewed?.error || "Macro ran, but its result could not be applied.");
    if (reviewed?.cancelled || (result.preview?.type === "notes_diff" && !result.preview?.has_changes)) {
      const skipped = reviewed.message || "Macro result was not applied.";
      setMacroStatus(skipped, "", { statusBar: true });
      return { ok: true, cancelled: true, message: skipped };
    }
    const output = String(result.stdout || "").trim();
    const message = output
      ? `Macro completed. ${output}`
      : (reviewed.message || (result.payload ? "Macro applied to the active DFM." : "Macro completed."));
    setMacroStatus(message, "", { statusBar: true });
    return { ok: true, message };
  } catch (err) {
    const message = String(err?.message || err || "Macro failed.");
    setMacroStatus(`Macro failed: ${message}`, "error", { statusBar: true });
    return { ok: false, message };
  } finally {
    if (macroRunBtn) macroRunBtn.disabled = false;
  }
}

async function runSelectedMacro() {
  const macro = getSelectedMacro();
  if (!macro) {
    setMacroStatus("Select a macro before running.", "error", { statusBar: true });
    return { ok: false, message: "Select a macro before running." };
  }
  return runMacro(macro);
}

// Entry point for the Flight Deck, which knows a macro only by its id.
export async function runMacroById(macroId) {
  const id = String(macroId || "").trim();
  if (!id) return { ok: false, message: "That button is not pointing at a macro." };
  if (!(await initMacroWindow())) return { ok: false, message: "The macro runner is not available." };
  if (!macros.length) await loadMacros();
  const macro = macros.find((item) => item.id === id);
  if (!macro) {
    const message = `Macro "${id}" is no longer installed.`;
    setMacroStatus(message, "error", { statusBar: true });
    return { ok: false, message };
  }
  return runMacro(macro);
}

function editSelectedMacro() {
  const macro = getSelectedMacro();
  if (!macro) {
    setMacroStatus("Select a macro before editing.", "error", { statusBar: true });
    return;
  }
  if (!macro.path) {
    setMacroStatus("Selected macro does not have a file path to edit.", "error", { statusBar: true });
    return;
  }
  shell.openScriptingTab?.({ forceNew: true, notebookPath: macro.path });
  setMacroStatus(`Opened ${macro.name || macro.id} in Arcode.`, "", { statusBar: true });
}

function openSelectedMacroInTaskDesigner() {
  const macro = getSelectedMacro();
  const macroId = macro ? macro.id : "";
  shell.openTaskDesigner?.({
    title: "DFM Validation",
    contextLabel: "Active DFM validation",
    macroId,
  });
  setMacroStatus("Opened Task Designer.", "", { statusBar: true });
}

async function deleteMacro(macro = getSelectedMacro()) {
  if (!canDeleteMacro(macro)) {
    setMacroStatus("Select a macro before deleting.", "error", { statusBar: true });
    return;
  }
  const name = String(macro.name || macro.id);
  const confirmed = window.confirm(`Delete macro "${name}"?\n\nThis removes the Python file from the macros folder.`);
  if (!confirmed) return;
  setMacroStatus(`Deleting macro: ${name}...`);
  try {
    const response = await fetch(`${API_BASE}/scripting/delete-macro`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ macro_id: macro.id }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result?.success) {
      throw new Error(result?.message || "Macro delete failed.");
    }
    selectedMacroId = "";
    await loadMacros();
    setMacroStatus(`Deleted macro: ${name}.`, "", { statusBar: true });
  } catch (err) {
    const message = String(err?.message || err || "Macro delete failed.");
    setMacroStatus(`Macro delete failed: ${message}`, "error", { statusBar: true });
  }
}

async function renameSelectedMacro() {
  const macro = getSelectedMacro();
  if (!canDeleteMacro(macro)) {
    setMacroStatus("Select a macro before renaming.", "error", { statusBar: true });
    return;
  }
  const currentName = String(macro.id || macro.name || "").replace(/\.py$/i, "");
  const nextName = window.prompt("Rename macro file:", currentName);
  if (nextName == null) return;
  const trimmed = String(nextName || "").trim();
  if (!trimmed) {
    setMacroStatus("Macro rename canceled; name is empty.", "error", { statusBar: true });
    return;
  }
  setMacroStatus(`Renaming macro: ${macro.name || macro.id}...`);
  try {
    const response = await fetch(`${API_BASE}/scripting/rename-macro`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ macro_id: macro.id, new_name: trimmed }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result?.success) {
      throw new Error(result?.message || "Macro rename failed.");
    }
    const nextId = String(result.macro_id || "").trim();
    if (nextId) {
      saveMacroOrder(macros.map((item) => (item.id === macro.id ? nextId : item.id)));
      selectedMacroId = nextId;
    }
    await loadMacros();
    setMacroStatus(result.message || "Macro renamed.", "", { statusBar: true });
  } catch (err) {
    const message = String(err?.message || err || "Macro rename failed.");
    setMacroStatus(`Macro rename failed: ${message}`, "error", { statusBar: true });
  }
}

function syncMacroSplitContextMenu() {
  if (!macroSplitContextMenu) return;
  const macro = getSelectedMacro();
  const runItem = macroSplitContextMenu.querySelector("[data-action='run']");
  const editItem = macroSplitContextMenu.querySelector("[data-action='edit']");
  const deleteItem = macroSplitContextMenu.querySelector("[data-action='delete']");
  if (runItem) runItem.disabled = !macro?.id;
  if (editItem) editItem.disabled = !macro?.path;
  if (deleteItem) deleteItem.disabled = !canDeleteMacro(macro);
}

function hideMacroSplitContextMenu() {
  if (!macroSplitContextMenu) return;
  macroSplitContextMenu.classList.remove("open");
  macroSplitContextMenu.setAttribute("aria-hidden", "true");
}

function hideMacroItemContextMenu() {
  if (!macroItemContextMenu) return;
  macroItemContextMenu.classList.remove("open");
  macroItemContextMenu.setAttribute("aria-hidden", "true");
}

function hideMacroContextMenus() {
  hideMacroSplitContextMenu();
  hideMacroItemContextMenu();
}

export function closeMacroContextMenus() {
  hideMacroContextMenus();
}

export function isMacroContextMenuOpen() {
  return !!(
    macroSplitContextMenu?.classList.contains("open")
    || macroItemContextMenu?.classList.contains("open")
  );
}

function positionMacroContextMenu(menu, x, y) {
  if (!menu) return;
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  const rect = menu.getBoundingClientRect();
  const margin = 6;
  const left = Math.min(Math.max(margin, x), Math.max(margin, window.innerWidth - rect.width - margin));
  const top = Math.min(Math.max(margin, y), Math.max(margin, window.innerHeight - rect.height - margin));
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.querySelector("button:not(:disabled)")?.focus?.();
}

function ensureMacroSplitContextMenu() {
  if (macroSplitContextMenu) return macroSplitContextMenu;
  const menu = document.createElement("div");
  menu.className = "macroSplitContextMenu";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-hidden", "true");
  menu.innerHTML = `
    <button type="button" role="menuitem" data-action="run">Run</button>
    <button type="button" role="menuitem" data-action="edit">Edit</button>
    <button type="button" role="menuitem" class="danger" data-action="delete">Delete</button>
  `;
  menu.addEventListener("click", (event) => {
    const item = event.target?.closest?.("[data-action]");
    if (!item || item.disabled) return;
    const action = item.dataset.action;
    hideMacroContextMenus();
    if (action === "run") void runSelectedMacro();
    else if (action === "edit") editSelectedMacro();
    else if (action === "delete") void deleteMacro();
  });
  document.body.appendChild(menu);
  macroSplitContextMenu = menu;
  return menu;
}

function showMacroSplitContextMenu(x, y) {
  const menu = ensureMacroSplitContextMenu();
  syncMacroSplitContextMenu();
  hideMacroItemContextMenu();
  positionMacroContextMenu(menu, x, y);
}

function syncMacroItemContextMenu() {
  if (!macroItemContextMenu) return;
  const macro = getSelectedMacro();
  const index = macros.findIndex((item) => item.id === selectedMacroId);
  const runItem = macroItemContextMenu.querySelector("[data-action='run']");
  const renameItem = macroItemContextMenu.querySelector("[data-action='rename']");
  const deleteItem = macroItemContextMenu.querySelector("[data-action='delete']");
  const upItem = macroItemContextMenu.querySelector("[data-action='move-up']");
  const downItem = macroItemContextMenu.querySelector("[data-action='move-down']");
  if (runItem) runItem.disabled = !macro?.id;
  if (renameItem) renameItem.disabled = !canDeleteMacro(macro);
  if (deleteItem) deleteItem.disabled = !canDeleteMacro(macro);
  if (upItem) upItem.disabled = index <= 0;
  if (downItem) downItem.disabled = index < 0 || index >= macros.length - 1;
}

function ensureMacroItemContextMenu() {
  if (macroItemContextMenu) return macroItemContextMenu;
  const menu = document.createElement("div");
  menu.className = "macroItemContextMenu";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-hidden", "true");
  menu.innerHTML = `
    <button type="button" role="menuitem" data-action="run">Run</button>
    <button type="button" role="menuitem" data-action="rename">Rename</button>
    <button type="button" role="menuitem" data-action="delete" class="danger">Delete</button>
    <div class="macroContextMenuSep" role="separator"></div>
    <button type="button" role="menuitem" data-action="move-up">Move Up</button>
    <button type="button" role="menuitem" data-action="move-down">Move Down</button>
  `;
  menu.addEventListener("click", (event) => {
    const item = event.target?.closest?.("[data-action]");
    if (!item || item.disabled) return;
    const action = item.dataset.action;
    hideMacroItemContextMenu();
    if (action === "run") void runSelectedMacro();
    else if (action === "rename") void renameSelectedMacro();
    else if (action === "delete") void deleteMacro();
    else if (action === "move-up") moveSelectedMacro(-1);
    else if (action === "move-down") moveSelectedMacro(1);
  });
  document.body.appendChild(menu);
  macroItemContextMenu = menu;
  return menu;
}

function showMacroItemContextMenu(x, y) {
  const menu = ensureMacroItemContextMenu();
  syncMacroItemContextMenu();
  hideMacroSplitContextMenu();
  positionMacroContextMenu(menu, x, y);
}

function getMacroSplitMetrics() {
  if (!macroContent || !macroSplitHandle) return null;
  const contentRect = macroContent.getBoundingClientRect();
  const handleRect = macroSplitHandle.getBoundingClientRect();
  if (!contentRect.height) return null;
  const contentStyles = getComputedStyle(macroContent);
  const rowGap = Number.parseFloat(contentStyles.rowGap || contentStyles.gap || "0") || 0;
  const handleHeight = handleRect.height || 8;
  const available = Math.max(0, contentRect.height - handleHeight - (rowGap * 2));
  const minList = Math.min(MACRO_MIN_LIST_HEIGHT, available);
  const minDescription = Math.min(MACRO_MIN_DESCRIPTION_HEIGHT, Math.max(0, available - minList));
  const maxList = Math.max(minList, available - minDescription);
  return { available, handleHeight, minList, maxList };
}

function updateMacroSplitAccessibility(height, metrics) {
  if (!macroSplitHandle || !metrics) return;
  macroSplitHandle.setAttribute("aria-valuemin", String(Math.round(metrics.minList)));
  macroSplitHandle.setAttribute("aria-valuemax", String(Math.round(metrics.maxList)));
  macroSplitHandle.setAttribute("aria-valuenow", String(Math.round(height)));
}

function applyMacroSplitHeight(height, options = {}) {
  if (!macroContent) return null;
  const metrics = getMacroSplitMetrics();
  if (!metrics) return null;
  const nextHeight = Math.min(Math.max(metrics.minList, Number(height) || metrics.minList), metrics.maxList);
  macroContent.style.gridTemplateRows = `${Math.round(nextHeight)}px ${Math.round(metrics.handleHeight)}px minmax(0, 1fr)`;
  updateMacroSplitAccessibility(nextHeight, metrics);
  if (options.markCustom) macroSplitCustomized = true;
  if (options.save) {
    try { localStorage.setItem(MACRO_SPLIT_HEIGHT_KEY, String(Math.round(nextHeight))); } catch {}
  }
  return nextHeight;
}

function clampMacroSplitHeight() {
  if (!macroSplitCustomized || !macroList) return;
  applyMacroSplitHeight(macroList.getBoundingClientRect().height);
}

function restoreMacroSplitHeight() {
  try {
    const saved = Number(localStorage.getItem(MACRO_SPLIT_HEIGHT_KEY));
    if (Number.isFinite(saved) && saved > 0) {
      macroSplitCustomized = true;
      applyMacroSplitHeight(saved);
      return;
    }
  } catch {}
  const metrics = getMacroSplitMetrics();
  if (macroList && metrics) updateMacroSplitAccessibility(macroList.getBoundingClientRect().height, metrics);
}

function initMacroContentSplit() {
  if (!macroContent || !macroSplitHandle || !macroList) return;
  let splitState = null;

  const cleanupSplitListeners = () => {
    document.removeEventListener("pointermove", moveSplit);
    document.removeEventListener("pointerup", stopSplit);
    document.removeEventListener("pointercancel", stopSplit);
    window.removeEventListener("blur", stopSplit);
  };

  const startSplit = (event) => {
    if (event.button !== 0) return;
    hideMacroContextMenus();
    splitState = {
      pointerId: event.pointerId,
      startY: event.clientY,
      listHeight: macroList.getBoundingClientRect().height,
    };
    document.body.classList.add("macroSplitResizeActive");
    try { macroSplitHandle.setPointerCapture(event.pointerId); } catch {}
    document.addEventListener("pointermove", moveSplit);
    document.addEventListener("pointerup", stopSplit);
    document.addEventListener("pointercancel", stopSplit);
    window.addEventListener("blur", stopSplit);
    event.preventDefault();
    event.stopPropagation();
  };

  const moveSplit = (event) => {
    if (!splitState || splitState.pointerId !== event.pointerId) return;
    applyMacroSplitHeight(splitState.listHeight + event.clientY - splitState.startY, { markCustom: true });
  };

  const stopSplit = (event) => {
    if (!splitState || (event?.pointerId != null && splitState.pointerId !== event.pointerId)) return;
    try { macroSplitHandle.releasePointerCapture(splitState.pointerId); } catch {}
    document.body.classList.remove("macroSplitResizeActive");
    const applied = applyMacroSplitHeight(macroList.getBoundingClientRect().height, { markCustom: true, save: true });
    if (applied == null) {
      try { localStorage.removeItem(MACRO_SPLIT_HEIGHT_KEY); } catch {}
    }
    cleanupSplitListeners();
    splitState = null;
  };

  macroSplitHandle.addEventListener("pointerdown", startSplit);
  macroSplitHandle.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    showMacroSplitContextMenu(event.clientX, event.clientY);
  });
  macroSplitHandle.addEventListener("keydown", (event) => {
    if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
      const rect = macroSplitHandle.getBoundingClientRect();
      event.preventDefault();
      showMacroSplitContextMenu(rect.left + rect.width / 2, rect.bottom);
      return;
    }
    const metrics = getMacroSplitMetrics();
    if (!metrics) return;
    const current = macroList.getBoundingClientRect().height;
    let next = current;
    if (event.key === "ArrowUp") next = current - 16;
    else if (event.key === "ArrowDown") next = current + 16;
    else if (event.key === "Home") next = metrics.minList;
    else if (event.key === "End") next = metrics.maxList;
    else return;
    event.preventDefault();
    applyMacroSplitHeight(next, { markCustom: true, save: true });
  });
  document.addEventListener("mousedown", (event) => {
    const anyMenuOpen = macroSplitContextMenu?.classList.contains("open") || macroItemContextMenu?.classList.contains("open");
    if (!anyMenuOpen) return;
    if (event.target?.closest?.(".macroSplitContextMenu, .macroItemContextMenu")) return;
    hideMacroContextMenus();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isMacroContextMenuOpen()) return;
    hideMacroContextMenus();
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
  }, true);
}

function initTaskDesignerButton() {
  if (!macroHeader || macroHeader.querySelector("[data-macro-task-designer='1']")) return;
  const button = document.createElement("button");
  button.className = "macroIconBtn";
  button.type = "button";
  button.title = "Open Task Designer";
  button.setAttribute("aria-label", "Open Task Designer");
  button.dataset.macroTaskDesigner = "1";
  button.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 6h13"></path>
      <path d="M8 12h13"></path>
      <path d="M8 18h13"></path>
      <path d="M3 6h.01"></path>
      <path d="M3 12h.01"></path>
      <path d="M3 18h.01"></path>
    </svg>
  `;
  button.addEventListener("click", openSelectedMacroInTaskDesigner);
  macroEditBtn?.insertAdjacentElement("beforebegin", button);
}

export async function openMacroWindow() {
  if (!(await initMacroWindow())) return;
  applyMacroPinned(readMacroPinned());
  macroWindowFrame?.restorePosition();
  macroWindowFrame?.lockSize();
  macroWindow?.classList.add("open");
  restoreMacroSplitHeight();
  void loadMacros();
}

export function closeMacroWindow() {
  refreshMacroElements();
  hideMacroContextMenus();
  macroWindow?.classList.remove("open");
}

export async function initMacroWindow() {
  if (macroWindowWired && refreshMacroElements()) return true;
  if (!(await ensureMacroWindowDom())) return false;
  if (macroWindowWired) return true;
  macroWindowFrame = createMacroWindowFrame({
    getWindow: () => macroWindow,
    getHeader: () => macroHeader,
    storageKey: MACRO_WINDOW_POSITION_KEY,
    onRectApplied: clampMacroSplitHeight,
  });
  macroWindowFrame.init();
  macroWindowWired = true;
  macroCloseBtn?.addEventListener("click", closeMacroWindow);
  macroRefreshBtn?.addEventListener("click", () => loadMacros());
  macroLibraryBtn?.addEventListener("click", openSharedMacroLibrary);
  macroPinBtn?.addEventListener("click", toggleMacroPinned);
  macroRunBtn?.addEventListener("click", runSelectedMacro);
  macroEditBtn?.addEventListener("click", editSelectedMacro);
  applyMacroPinned(readMacroPinned());
  initTaskDesignerButton();
  initMacroContentSplit();
  initMacroListKeyboard(macroList, {
    getIds: () => macros.map((macro) => macro.id),
    onSelect: selectMacro,
  });
  initMacroListDrag(macroList, macroWindow, {
    getMacro: (id) => macros.find((macro) => macro.id === id) || null,
    reorder: true,
    outsideTarget: (element) => {
      const flightDeck = element?.closest?.("#flightDeck");
      return flightDeck ? { kind: "deck", highlight: flightDeck } : { kind: "remove" };
    },
    onStart: (macro) => selectMacro(macro.id),
    onDrop: (macro, target) => {
      if (target.kind === "reorder") reorderMacro(macro.id, target.beforeId);
      else if (target.kind === "deck") window.dispatchEvent(new CustomEvent("arcrho:flight-deck-add-macro", { detail: { macro } }));
      else void deleteMacro(macro);
    },
  });
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (isMacroContextMenuOpen()) {
      hideMacroContextMenus();
      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
      return;
    }
    if (macroWindow?.classList.contains("open")) closeMacroWindow();
  }, true);
  window.addEventListener("arcrho:local-macros-changed", () => {
    if (!macroWindow?.classList.contains("open")) return;
    void loadMacros();
  });
  return true;
}
