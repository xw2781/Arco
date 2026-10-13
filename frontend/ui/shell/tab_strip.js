import { $, shell } from "./shell_context.js?v=20260510a";
import { FLOAT_VERTICAL_RETURN_THRESHOLD_PX, FLOAT_VERTICAL_THRESHOLD_PX, isFloatingTab } from "./floating_tabs.js?v=20260520b";

let draggedTabId = null;
let dragEl = null;
let placeholderEl = null;
let tabsHostPrevStyle = null;
let dragElPrevStyle = null;
let dragElBaseLeft = 0;
let dragElBaseTop = 0;
let dragElPrevVisibility = null;
let ptrActive = false;
let ptrId = null;
let ptrStartX = 0;
let ptrStartY = 0;
let ptrMoved = false;
let tabDragMode = null;
let isDragging = false;
let lastPlaceholderIndex = -1;
let tabCtxId = null;
let tabStripWired = false;
const DRAG_THRESHOLD_PX = 6;
const SCRIPTING_PATH_ACTIONS = new Set(["open-file-location", "copy-file-path"]);
const SCRIPTING_PATH_TOOLTIP_DELAY_MS = 2000;

export function isTabStripDragging() { return isDragging; }

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

// The glyph on the left edge of a tab. Which drawing a tab type gets is decided entirely in
// /ui/shell/tab-type-icons/tab_type_icons.css, keyed off this element's data-tab-type, so a new
// tab type needs no change here and an unmapped one falls back to a generic page icon on its own.
function createTabTypeIcon(tabType) {
  const icon = document.createElement("span");
  icon.className = "tabTypeIcon";
  icon.dataset.tabType = String(tabType || "").trim().toLowerCase();
  icon.setAttribute("aria-hidden", "true");
  return icon;
}

function getScriptingFilePath(tab) {
  if (!tab || tab.type !== "scripting") return "";
  return String(tab.scPath || tab.scOpenPath || "").trim();
}

function getParentDirectory(pathLike) {
  const raw = String(pathLike || "").trim();
  if (!raw) return "";
  const slash = Math.max(raw.lastIndexOf("\\"), raw.lastIndexOf("/"));
  return slash >= 0 ? raw.slice(0, slash) : "";
}

function attachScriptingPathTooltip(el, tab) {
  const path = getScriptingFilePath(tab);
  if (!el || !path) return;
  let hoverTimer = null;
  let hoverPointer = { x: 0, y: 0 };
  let visible = false;

  const clear = () => {
    if (hoverTimer) window.clearTimeout(hoverTimer);
    hoverTimer = null;
  };
  const hide = () => {
    clear();
    visible = false;
    shell.hideGlobalTooltip?.();
  };
  const schedule = (event) => {
    hoverPointer = { x: event.clientX, y: event.clientY };
    if (isDragging || hoverTimer || visible) return;
    hoverTimer = window.setTimeout(() => {
      hoverTimer = null;
      if (isDragging) return;
      visible = true;
      shell.showGlobalTooltip?.(path, hoverPointer.x + 12, hoverPointer.y + 18);
    }, SCRIPTING_PATH_TOOLTIP_DELAY_MS);
  };

  el.addEventListener("pointerenter", schedule);
  el.addEventListener("pointermove", hide);
  el.addEventListener("pointerleave", hide);
  el.addEventListener("pointerdown", hide);
  el.addEventListener("contextmenu", hide);
}

async function copyTextToClipboard(text) {
  const value = String(text || "");
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    textarea.remove();
    return ok;
  }
}

async function openScriptingFileLocation(tab) {
  const filePath = getScriptingFilePath(tab);
  if (!filePath) {
    shell.updateStatusBar?.("No saved file path for this scripting tab.", { tone: "warning" });
    return;
  }
  const host = shell.getHostApi?.();
  if (host?.showItemInFolder) {
    try {
      const result = await host.showItemInFolder({ path: filePath });
      if (result?.ok) {
        shell.updateStatusBar?.(`Opened file location: ${filePath}`);
        return;
      }
      shell.updateStatusBar?.(`Could not open file location: ${result?.error || filePath}`, { tone: "error" });
      return;
    } catch (err) {
      shell.updateStatusBar?.(`Could not open file location: ${String(err?.message || err)}`, { tone: "error" });
      return;
    }
  }
  const folder = getParentDirectory(filePath);
  if (host?.openPath && folder) {
    try {
      const result = await host.openPath({ path: folder });
      shell.updateStatusBar?.(result?.ok ? `Opened folder: ${folder}` : `Could not open folder: ${result?.error || folder}`, { tone: result?.ok ? "" : "error" });
      return;
    } catch (err) {
      shell.updateStatusBar?.(`Could not open folder: ${String(err?.message || err)}`, { tone: "error" });
      return;
    }
  }
  shell.updateStatusBar?.("Open File Location requires the desktop app host.", { tone: "error" });
}

async function copyScriptingFilePath(tab) {
  const filePath = getScriptingFilePath(tab);
  if (!filePath) {
    shell.updateStatusBar?.("No saved file path for this scripting tab.", { tone: "warning" });
    return;
  }
  const ok = await copyTextToClipboard(filePath);
  shell.updateStatusBar?.(ok ? `Copied file path: ${filePath}` : "Could not copy file path.", { tone: ok ? "" : "error" });
}

function lockTabsOverflowDuringDrag() {
  const host = $("tabs");
  if (!host) return;
  if (host.dataset.prevOverflowX == null) host.dataset.prevOverflowX = host.style.overflowX || "";
  host.style.overflowX = "hidden";
}

function restoreTabsOverflowAfterDrag() {
  const host = $("tabs");
  if (!host) return;
  if (host.dataset.prevOverflowX != null) {
    host.style.overflowX = host.dataset.prevOverflowX;
    delete host.dataset.prevOverflowX;
  } else host.style.overflowX = "";
}

function lockTabsHostLayout(host) {
  if (!host || tabsHostPrevStyle) return;
  const r = host.getBoundingClientRect();
  tabsHostPrevStyle = {
    height: host.style.height,
    minHeight: host.style.minHeight,
    flexWrap: host.style.flexWrap,
    overflowX: host.style.overflowX,
    overflowY: host.style.overflowY,
    alignItems: host.style.alignItems,
  };
  host.style.height = `${Math.ceil(r.height)}px`;
  host.style.minHeight = host.style.height;
  host.style.flexWrap = "nowrap";
  host.style.overflowX = "hidden";
  host.style.overflowY = "hidden";
  host.style.alignItems = "flex-end";
}

function unlockTabsHostLayout() {
  const host = $("tabs");
  if (!host || !tabsHostPrevStyle) return;
  host.style.height = tabsHostPrevStyle.height;
  host.style.minHeight = tabsHostPrevStyle.minHeight;
  host.style.flexWrap = tabsHostPrevStyle.flexWrap;
  host.style.overflowX = tabsHostPrevStyle.overflowX;
  host.style.overflowY = tabsHostPrevStyle.overflowY;
  host.style.alignItems = tabsHostPrevStyle.alignItems;
  tabsHostPrevStyle = null;
}

function cleanupDragUI() {
  restoreTabsOverflowAfterDrag();
  shell.removeFloatPreview?.();
  if (dragEl) dragEl.classList.remove("dragging");
  if (placeholderEl && placeholderEl.parentNode) placeholderEl.parentNode.removeChild(placeholderEl);
  placeholderEl = null;
  if (dragEl && dragElPrevStyle) {
    dragEl.style.position = dragElPrevStyle.position;
    dragEl.style.left = dragElPrevStyle.left;
    dragEl.style.top = dragElPrevStyle.top;
    dragEl.style.width = dragElPrevStyle.width;
    dragEl.style.height = dragElPrevStyle.height;
    dragEl.style.zIndex = dragElPrevStyle.zIndex;
    dragEl.style.pointerEvents = dragElPrevStyle.pointerEvents;
    dragEl.style.transform = dragElPrevStyle.transform;
    dragEl.style.visibility = dragElPrevStyle.visibility;
  } else if (dragEl && dragElPrevVisibility != null) {
    dragEl.style.visibility = dragElPrevVisibility;
  }
  dragElPrevStyle = null;
  dragElPrevVisibility = null;
  dragElBaseLeft = 0;
  dragElBaseTop = 0;
  dragEl = null;
  draggedTabId = null;
  ptrActive = false;
  ptrId = null;
  ptrMoved = false;
  tabDragMode = null;
  isDragging = false;
  lastPlaceholderIndex = -1;
  unlockTabsHostLayout();
  document.body.classList.remove("tab-dragging");
  try { document.body.style.cursor = ""; } catch {}
}

function ensurePlaceholderFrom(el) {
  if (placeholderEl && placeholderEl.isConnected) return placeholderEl;
  const r = el.getBoundingClientRect();
  const ph = document.createElement("div");
  ph.className = "tab placeholder";
  ph.innerHTML = "&nbsp;";
  ph.style.width = `${Math.ceil(r.width)}px`;
  ph.style.height = `${Math.ceil(r.height)}px`;
  placeholderEl = ph;
  return ph;
}

function removePlaceholder() {
  if (placeholderEl && placeholderEl.parentNode) placeholderEl.parentNode.removeChild(placeholderEl);
  placeholderEl = null;
  lastPlaceholderIndex = -1;
}

function tabStripFloatDistance(host, clientY) {
  const r = host?.getBoundingClientRect?.();
  return r ? clientY - r.bottom : 0;
}

function startDragIfNeeded(host, el, pointerId) {
  if (!host || !el || dragElPrevStyle) return;
  isDragging = true;
  lockTabsHostLayout(host);
  document.body.classList.add("tab-dragging");
  try { document.body.style.cursor = "grabbing"; } catch {}
  el.classList.add("dragging");
  const hostRect = host.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  dragElPrevStyle = {
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
  dragElPrevVisibility = el.style.visibility;
  dragElBaseLeft = (r.left - hostRect.left) + host.scrollLeft;
  dragElBaseTop = (r.top - hostRect.top);
  el.style.width = `${Math.ceil(r.width)}px`;
  el.style.height = `${Math.ceil(r.height)}px`;
  el.style.position = "absolute";
  el.style.left = `${Math.round(dragElBaseLeft)}px`;
  el.style.top = `${Math.round(dragElBaseTop)}px`;
  el.style.zIndex = "1000";
  el.style.pointerEvents = "none";
  el.style.transform = "translate3d(0px, 0px, 0px)";
  host.insertBefore(ensurePlaceholderFrom(el), el);
  try { el.setPointerCapture(pointerId); } catch {}
}

function setDraggedTabHidden(hidden) {
  if (!dragEl) return;
  if (dragElPrevVisibility == null) dragElPrevVisibility = dragEl.style.visibility;
  dragEl.style.visibility = hidden ? "hidden" : dragElPrevVisibility;
}

function enterFloatDragMode(clientX, clientY) {
  if (tabDragMode === "float") return;
  tabDragMode = "float";
  ptrMoved = true;
  isDragging = true;
  removePlaceholder();
  setDraggedTabHidden(true);
  try { document.body.style.cursor = "grabbing"; } catch {}
  shell.updateFloatPreview?.(clientX, clientY);
}

function enterReorderDragMode(host, pointerId) {
  if (!host || !dragEl) return;
  if (tabDragMode !== "reorder") {
    tabDragMode = "reorder";
    ptrMoved = true;
    shell.removeFloatPreview?.();
    setDraggedTabHidden(false);
    startDragIfNeeded(host, dragEl, pointerId);
    lockTabsOverflowDuringDrag();
  }
  if (!placeholderEl) {
    host.insertBefore(ensurePlaceholderFrom(dragEl), dragEl);
  }
}

function updateReorderDrag(clientX, pointerId) {
  const host = $("tabs");
  enterReorderDragMode(host, pointerId);
  if (!host || !placeholderEl) return;
  const tabs = [...host.querySelectorAll('.tab[data-tab-id]')].filter((node) => {
    const id = node.getAttribute("data-tab-id");
    return id && id !== "home" && id !== draggedTabId;
  });
  let targetNode = null;
  for (const node of tabs) {
    const rect = node.getBoundingClientRect();
    if (clientX < rect.left + rect.width / 2) { targetNode = node; break; }
  }
  const beforeRects = new Map();
  host.querySelectorAll('.tab[data-tab-id]').forEach(el => {
    const id = el.getAttribute("data-tab-id");
    if (!id || id === "home" || id === draggedTabId || el.classList.contains("placeholder")) return;
    beforeRects.set(id, el.getBoundingClientRect());
  });
  if (targetNode) { if (placeholderEl.nextSibling !== targetNode) host.insertBefore(placeholderEl, targetNode); }
  else if (placeholderEl.parentNode !== host || placeholderEl !== host.lastChild) host.appendChild(placeholderEl);
  const newIndex = Array.from(host.children).indexOf(placeholderEl);
  if (newIndex !== lastPlaceholderIndex) { lastPlaceholderIndex = newIndex; flipAnimateTabs(host, beforeRects); }
}

function commitOrderFromDom() {
  const host = $("tabs");
  if (!host || !draggedTabId || !placeholderEl) return;
  const seq = [];
  for (const child of host.children) {
    if (child === placeholderEl) { seq.push("__PLACEHOLDER__"); continue; }
    if (child.classList && child.classList.contains("tab")) {
      const id = child.getAttribute("data-tab-id");
      if (!id || id === draggedTabId) continue;
      seq.push(id);
    }
  }
  const phIndex = seq.indexOf("__PLACEHOLDER__");
  if (phIndex < 0) return;
  const ids = seq.filter(x => x !== "__PLACEHOLDER__");
  ids.splice(Math.max(0, Math.min(ids.length, phIndex)), 0, draggedTabId);
  const home = shell.state.tabs.find(t => t.id === "home");
  const map = new Map(shell.state.tabs.map(t => [t.id, t]));
  const nextDocked = [];
  if (home) nextDocked.push(home);
  for (const id of ids) {
    if (id === "home") continue;
    const t = map.get(id);
    if (t && !isFloatingTab(t)) nextDocked.push(t);
  }
  for (const t of shell.state.tabs) {
    if (t.id === "home" || isFloatingTab(t)) continue;
    if (!nextDocked.some(x => x.id === t.id)) nextDocked.push(t);
  }
  const dockedQueue = [...nextDocked];
  shell.state.tabs = shell.state.tabs.map((t) => isFloatingTab(t) ? t : (dockedQueue.shift() || t));
}

function wireTabDnDHostOnce() {
  const host = $("tabs");
  if (!host || host.dataset.dndWired === "1") return;
  host.dataset.dndWired = "1";
}

function flipAnimateTabs(host, beforeRects) {
  const after = new Map();
  host.querySelectorAll('.tab[data-tab-id]').forEach(el => {
    const id = el.getAttribute("data-tab-id");
    if (!id || id === "home" || id === draggedTabId || el.classList.contains("placeholder")) return;
    after.set(id, el.getBoundingClientRect());
  });
  host.querySelectorAll('.tab[data-tab-id]').forEach(el => {
    const id = el.getAttribute("data-tab-id");
    if (!id || id === "home" || id === draggedTabId || el.classList.contains("placeholder")) return;
    const b = beforeRects.get(id);
    const a = after.get(id);
    if (!b || !a) return;
    const dx = b.left - a.left;
    if (Math.abs(dx) < 0.5) return;
    if (el.__flipAnim) { try { el.__flipAnim.cancel(); } catch {} el.__flipAnim = null; }
    el.__flipAnim = el.animate([{ transform: `translateX(${dx}px)` }, { transform: "translateX(0px)" }], { duration: 140, easing: "ease-out" });
  });
}

export function renderTabs() {
  const host = $("tabs");
  if (!host) return;
  host.querySelectorAll(".tab").forEach(n => n.remove());
  wireTabDnDHostOnce();
  for (const t of shell.state.tabs) {
    if (isFloatingTab(t)) continue;
    const el = document.createElement("div");
    el.className = "tab" + (t.id === shell.state.activeId ? " active" : "");
    el.setAttribute("data-tab-id", t.id);
    attachScriptingPathTooltip(el, t);
    el.addEventListener("click", () => { if (!isDragging) shell.setActive?.(t.id); });
    el.addEventListener("contextmenu", (e) => { e.preventDefault(); openTabCtxMenu(t.id, e.clientX, e.clientY); });
    if (t.id !== "home") {
      el.draggable = false;
      el.addEventListener("pointerdown", (e) => {
        if (e.target?.closest?.("button.x")) return;
        if (e.button !== 0) return;
        ptrActive = true; ptrId = e.pointerId; ptrStartX = e.clientX; ptrStartY = e.clientY; ptrMoved = false; draggedTabId = t.id; dragEl = el;
        try { el.setPointerCapture(e.pointerId); } catch {}
      });
      el.addEventListener("pointermove", (e) => {
        if (!ptrActive || ptrId !== e.pointerId || !draggedTabId || !dragEl) return;
        const dx = e.clientX - ptrStartX;
        const dy = e.clientY - ptrStartY;
        const host = $("tabs");
        const floatDistance = tabStripFloatDistance(host, e.clientY);
        const shouldFloat = floatDistance >= FLOAT_VERTICAL_THRESHOLD_PX;
        const shouldReturnToReorder = floatDistance <= FLOAT_VERTICAL_RETURN_THRESHOLD_PX;
        if (!ptrMoved) {
          if (shouldFloat && dy > 0) { enterFloatDragMode(e.clientX, e.clientY); e.preventDefault(); return; }
          if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
          enterReorderDragMode(host, e.pointerId);
        }
        if (tabDragMode === "reorder" && shouldFloat && dy > 0) enterFloatDragMode(e.clientX, e.clientY);
        else if (tabDragMode === "float" && shouldReturnToReorder) enterReorderDragMode(host, e.pointerId);
        if (tabDragMode === "float") { shell.updateFloatPreview?.(e.clientX, e.clientY); e.preventDefault(); return; }
        if (tabDragMode !== "reorder" || !placeholderEl) return;
        if (dragEl) dragEl.style.transform = `translate3d(${dx}px, 0px, 0px)`;
        e.preventDefault();
        updateReorderDrag(e.clientX, e.pointerId);
      });
      el.addEventListener("pointerup", (e) => {
        if (!ptrActive || ptrId !== e.pointerId) return;
        if (!ptrMoved) { cleanupDragUI(); return; }
        if (tabDragMode === "float") {
          const rect = shell.defaultFloatRectFromPointer?.(e.clientX, e.clientY);
          const id = draggedTabId;
          cleanupDragUI();
          shell.floatTab?.(id, rect);
          return;
        }
        if (tabDragMode === "reorder") commitOrderFromDom();
        cleanupDragUI(); shell.render?.(); shell.saveState?.();
      });
      el.addEventListener("pointercancel", (e) => { if (ptrActive && ptrId === e.pointerId) cleanupDragUI(); });
    }
    el.appendChild(createTabTypeIcon(t.type));
    const label = document.createElement("span");
    label.textContent = t.title;
    el.appendChild(label);
    if (t.id !== "home") {
      const x = document.createElement("button");
      x.className = "x" + (t.isDirty ? " dirty" : "");
      x.type = "button";
      x.setAttribute("aria-label", "Close tab");
      x.appendChild(createTabCloseIcon());
      if (t.isDirty) { const dot = document.createElement("span"); dot.className = "dirtyDot"; x.appendChild(dot); x.title = "Unsaved changes (close tab)"; }
      else x.title = "Close";
      x.addEventListener("click", (e) => { e.stopPropagation(); shell.closeTab?.(t.id); });
      el.appendChild(x);
    }
    host.appendChild(el);
  }
}

const tabCtxMenu = document.getElementById("tabCtxMenu");

export function closeTabCtxMenu() {
  if (!tabCtxMenu) return;
  tabCtxMenu.classList.remove("open");
  tabCtxId = null;
}

function positionTabCtxMenu(x, y) {
  if (!tabCtxMenu) return;
  const pad = 8;
  const maxX = window.innerWidth - tabCtxMenu.offsetWidth - pad;
  const maxY = window.innerHeight - tabCtxMenu.offsetHeight - pad;
  tabCtxMenu.style.left = `${Math.max(pad, Math.min(x, maxX))}px`;
  tabCtxMenu.style.top = `${Math.max(pad, Math.min(y, maxY))}px`;
}

export function openTabCtxMenu(tabId, x, y) {
  if (!tabCtxMenu) return;
  tabCtxId = tabId;
  const tab = shell.state.tabs.find(t => t.id === tabId);
  const scriptingPath = getScriptingFilePath(tab);
  tabCtxMenu.querySelectorAll(".tabCtxItem").forEach((el) => {
    const action = el.getAttribute("data-action");
    const disabled = tabId === "home" ||
      (SCRIPTING_PATH_ACTIONS.has(action) && !scriptingPath);
    el.classList.toggle("disabled", disabled);
  });
  tabCtxMenu.classList.add("open");
  positionTabCtxMenu(x, y);
}

export function initTabStrip() {
  if (tabStripWired) return;
  tabStripWired = true;
  tabCtxMenu?.addEventListener("click", (e) => {
    const item = e.target?.closest?.(".tabCtxItem");
    const action = item?.getAttribute("data-action");
    if (!action || item.classList.contains("disabled")) return;
    const id = tabCtxId;
    closeTabCtxMenu();
    if (!id) return;
    if (action === "open-file-location") openScriptingFileLocation(shell.state.tabs.find(t => t.id === id));
    else if (action === "copy-file-path") copyScriptingFilePath(shell.state.tabs.find(t => t.id === id));
    else if (action === "close") shell.closeTab?.(id);
    else if (action === "close-others") shell.closeTabsExcept?.([id]);
    else if (action === "close-all") shell.closeTabsExcept?.([]);
  });
  window.addEventListener("click", () => closeTabCtxMenu());
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeTabCtxMenu(); });
}
