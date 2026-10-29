import {
  getBerquistShermanContract,
  normalizeBerquistShermanVariant,
} from "/ui/shared/dataset/berquist_sherman_contract.js";
import { resolveWindowTab } from "/ui/shared/tabs/window_tab_catalog.js?v=20260903a";
import { confirmDiscardClose } from "/ui/shared/components/close_confirm/close_confirm.js";

export function installProjectInstanceWindows(ctx) {
  const { api, els, projectName, state } = ctx;
  const { DATASET_WINDOW_MIN_WIDTH, DATASET_WINDOW_MIN_HEIGHT, DATASET_WINDOW_DEFAULT_WIDTH_RATIO, DATASET_WINDOW_DEFAULT_HEIGHT_RATIO, DATASET_WINDOW_EDGE_VISIBLE_WIDTH, DATASET_WINDOW_TITLEBAR_HEIGHT } = ctx.constants;
  const { hiddenWindows, datasetWindows } = state;
  const activateDatasetWindow = (...args) => api.activateDatasetWindow(...args);
  const clampNumber = (...args) => api.clampNumber(...args);
  const closeActiveDatasetWindowFromShortcut = (...args) => api.closeActiveDatasetWindowFromShortcut(...args);
  const hideDatasetWindow = (...args) => api.hideDatasetWindow(...args);
  const markPathTreeActive = (...args) => api.markPathTreeActive(...args);
  const normalizePath = (...args) => api.normalizePath(...args);
  const normalizeLookupKey = (...args) => api.normalizeLookupKey(...args);
  const postZoomToDatasetFrame = (...args) => api.postZoomToDatasetFrame(...args);
  const recordSelectedDfmObject = (...args) => api.recordSelectedDfmObject(...args);
  const routeDfmRatioHotkey = (...args) => api.routeDfmRatioHotkey(...args);
  const routeDfmWindowCommand = (...args) => api.routeDfmWindowCommand(...args);
  const setSelectedPath = (...args) => api.setSelectedPath(...args);
  const setStatus = (...args) => api.setStatus(...args);
  const toText = (...args) => api.toText(...args);
  const updateHiddenTabsArea = (...args) => api.updateHiddenTabsArea(...args);
  const waitForPathTreeRender = (...args) => api.waitForPathTreeRender(...args);

  /* The tab a window opens on: whatever the caller asked for, then the user's
     saved default for that window kind, then the app default. `state` holds the
     saved defaults, which boot reads once from the project-user preferences. */
  const windowTab = (kind, requestedTab) => resolveWindowTab(kind, requestedTab, state.defaultWindowTabs);

function getDatasetWindowKey(datasetName, path = state.selectedPath, temporaryViewSessionId = "") {
  const baseKey = `${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
  const sessionId = toText(temporaryViewSessionId);
  return sessionId ? `${baseKey}\u0001temporary\u0001${sessionId}` : baseKey;
}


function getDfmWindowKey(datasetName, path = state.selectedPath) {
  return `dfm\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getBornhuetterFergusonWindowKey(datasetName, path = state.selectedPath) {
  return `bf\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getCapeCodWindowKey(datasetName, path = state.selectedPath) {
  return `cc\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getBootstrapWindowKey(datasetName, path = state.selectedPath) {
  return `bst\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getStochasticConsolidationWindowKey(datasetName, path = state.selectedPath) {
  return `scon\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getBerquistShermanWindowKey(datasetName, variant, path = state.selectedPath) {
  return `bs\u0001${normalizeBerquistShermanVariant(variant)}\u0001${normalizePath(path)}\u0001${toText(datasetName).toLowerCase()}`;
}

function getWindowPath(frame) {
  return normalizePath(frame?.dataset?.windowPath || "");
}

function isWindowOnSelectedPath(frame) {
  const windowPath = getWindowPath(frame);
  const currentPath = normalizePath(state.selectedPath);
  return !!windowPath && !!currentPath && windowPath.toLowerCase() === currentPath.toLowerCase();
}

function getWindowFullTitle(frame) {
  return toText(frame?.dataset?.windowTitle || frame?.getAttribute?.("aria-label") || frame?.dataset?.windowDatasetName || "Dataset");
}

function getWindowShortTitle(frame) {
  return toText(frame?.dataset?.windowDatasetName || frame?.dataset?.windowItemName || getWindowFullTitle(frame));
}

function getWindowMethodType(frame) {
  const explicit = toText(frame?.dataset?.windowMethodType);
  if (explicit) return explicit;
  if (isDfmWindow(frame)) return "DFM";
  if (isResultSelectionWindow(frame)) return "Result Selection";
  if (isBornhuetterFergusonWindow(frame)) return "Bornhuetter Ferguson";
  if (isCapeCodWindow(frame)) return "Cape Cod";
  if (isBootstrapWindow(frame)) return "Bootstrap";
  if (isStochasticConsolidationWindow(frame)) return "Stochastic Consolidation";
  if (isBerquistShermanWindow(frame)) {
    return getBerquistShermanContract(frame?.dataset?.bsVariant)?.methodType || "None";
  }
  const key = normalizeLookupKey(frame?.dataset?.windowItemName || frame?.dataset?.windowDatasetName || "");
  return key ? state.cachedDatasetFilter.methodTypesByName.get(key) || "None" : "None";
}

function updateDatasetWindowTitle(frame) {
  if (!frame) return;
  const fullTitle = getWindowFullTitle(frame);
  const displayTitle = isWindowOnSelectedPath(frame) ? getWindowShortTitle(frame) : fullTitle;
  const titleEl = frame.querySelector?.(".pi-window-title");
  if (titleEl) {
    titleEl.textContent = displayTitle;
    titleEl.removeAttribute("title");
  }
  frame.dataset.windowDisplayTitle = displayTitle;
  frame.setAttribute("aria-label", fullTitle);
}

function syncDatasetWindowChrome() {
  const active = getActiveDatasetWindow();
  for (const frame of datasetWindows.values()) {
    if (!frame?.isConnected) continue;
    const visible = frame.dataset.hidden !== "1" && frame.style.display !== "none";
    frame.classList.toggle("active", visible && frame === active);
    updateDatasetWindowTitle(frame);
  }
}

function getFrameRect(frame) {
  return {
    x: Number.parseFloat(frame.style.left) || 0,
    y: Number.parseFloat(frame.style.top) || 0,
    width: Number.parseFloat(frame.style.width) || frame.getBoundingClientRect().width || DATASET_WINDOW_MIN_WIDTH,
    height: Number.parseFloat(frame.style.height) || frame.getBoundingClientRect().height || DATASET_WINDOW_MIN_HEIGHT,
  };
}

function getProjectInstanceWindowSnapshot(frame) {
  if (!frame?.isConnected) return null;
  if (toText(frame.dataset?.temporaryViewSessionId)) return null;
  // Review-table windows belong to a live macro session, and the Excel Link
  // Manager and the Dependency Graph are tool windows rather than objects;
  // none is persisted into or restored from the saved Project Instance state.
  if (frame.dataset?.windowKind === "review_table") return null;
  if (frame.dataset?.windowKind === "excel_links") return null;
  if (frame.dataset?.windowKind === "dependency_graph") return null;
  const kind = isDfmWindow(frame)
    ? "dfm"
    : isResultSelectionWindow(frame)
      ? "result_selection"
      : isBornhuetterFergusonWindow(frame)
        ? "bornhuetter_ferguson"
        : isCapeCodWindow(frame)
          ? "cape_cod"
          : isBootstrapWindow(frame)
            ? "bootstrap"
            : isStochasticConsolidationWindow(frame)
              ? "stochastic_consolidation"
              : isBerquistShermanWindow(frame)
                ? "berquist_sherman"
                : "dataset";
  const name = toText(frame.dataset.windowItemName || frame.dataset.windowDatasetName || "");
  if (!name) return null;
  const active = getActiveDatasetWindow() === frame;
  const hiddenItem = hiddenWindows.get(frame.dataset.windowId || "");
  return {
    windowId: toText(frame.dataset.windowId || ""),
    kind,
    name,
    title: toText(frame.dataset.windowTitle || frame.getAttribute("aria-label") || name),
    path: getWindowPath(frame),
    hidden: frame.dataset.hidden === "1" || frame.style.display === "none",
    active,
    maximized: frame.dataset.maximized === "1",
    dirty: frame.dataset.dirty === "1",
    methodType: getWindowMethodType(frame),
    outputDataset: kind === "dfm" ? toText(frame.dataset.windowOutputDataset || "") : "",
    dfmTab: kind === "dfm" ? toText(frame.dataset.dfmTab || "") : "",
    rsTab: kind === "result_selection" ? toText(frame.dataset.rsTab || "") : "",
    bfTab: kind === "bornhuetter_ferguson" ? toText(frame.dataset.bfTab || "") : "",
    ccTab: kind === "cape_cod" ? toText(frame.dataset.ccTab || "") : "",
    bstTab: kind === "bootstrap" ? toText(frame.dataset.bstTab || "") : "",
    sconTab: kind === "stochastic_consolidation" ? toText(frame.dataset.sconTab || "") : "",
    bsTab: kind === "berquist_sherman" ? toText(frame.dataset.bsTab || "") : "",
    bsVariant: kind === "berquist_sherman" ? normalizeBerquistShermanVariant(frame.dataset.bsVariant) : "",
    rect: hiddenItem?.restoreRect || getFrameRect(frame),
  };
}

function buildProjectInstanceStateSnapshot() {
  const windows = [];
  for (const frame of datasetWindows.values()) {
    const snapshot = getProjectInstanceWindowSnapshot(frame);
    if (snapshot) windows.push(snapshot);
  }
  windows.sort((a, b) => {
    if (a.active && !b.active) return -1;
    if (b.active && !a.active) return 1;
    return a.title.localeCompare(b.title);
  });
  const active = windows.find((item) => item.active);
  const snapshotState = {
    selectedPath: state.selectedPath,
    windows,
  };
  if (active) snapshotState.activeWindow = { kind: active.kind, name: active.name };
  return snapshotState;
}

function getVisibleProjectInstanceWindowSummaries() {
  const windows = [];
  for (const frame of datasetWindows.values()) {
    const snapshot = getProjectInstanceWindowSnapshot(frame);
    if (!snapshot || snapshot.hidden) continue;
    windows.push({
      windowId: snapshot.windowId,
      kind: snapshot.kind,
      name: snapshot.name,
      title: snapshot.title,
      path: snapshot.path,
      active: !!snapshot.active,
      dirty: !!snapshot.dirty,
      maximized: !!snapshot.maximized,
      methodType: snapshot.methodType || getWindowMethodType(frame),
      outputDataset: snapshot.outputDataset || "",
      dfmTab: snapshot.dfmTab || "",
      rsTab: snapshot.rsTab || "",
      bfTab: snapshot.bfTab || "",
      ccTab: snapshot.ccTab || "",
      bstTab: snapshot.bstTab || "",
      sconTab: snapshot.sconTab || "",
      bsTab: snapshot.bsTab || "",
      bsVariant: snapshot.bsVariant || "",
      zIndex: Number.parseInt(frame.style.zIndex || "0", 10) || 0,
    });
  }
  windows.sort((a, b) => {
    if (a.active && !b.active) return -1;
    if (b.active && !a.active) return 1;
    return b.zIndex - a.zIndex || a.title.localeCompare(b.title);
  });
  return windows.map(({ zIndex: _zIndex, ...item }) => item);
}

function getProjectInstanceAssistantContextSummary() {
  const openNestedWindows = getVisibleProjectInstanceWindowSummaries();
  return {
    projectName,
    selectedPath: state.selectedPath,
    activeNestedWindow: openNestedWindows.find((item) => item.active) || null,
    openNestedWindows,
    ignoredMinimizedWindowCount: hiddenWindows.size,
  };
}

function notifyProjectInstanceStateChanged() {
  try {
    window.parent?.postMessage({
      type: "arcrho:project-instance-state",
      state: buildProjectInstanceStateSnapshot(),
    }, "*");
  } catch {}
}


function getWindowBounds() {
  const rect = els.root?.getBoundingClientRect?.();
  return {
    width: Math.max(480, Number(rect?.width || window.innerWidth || 900)),
    height: Math.max(360, Number(rect?.height || window.innerHeight || 640)),
  };
}

function getWindowTopLimit() {
  const rootRect = els.root?.getBoundingClientRect?.();
  const toolbarRect = els.toolbar?.getBoundingClientRect?.();
  if (!rootRect || !toolbarRect) return 0;
  return Math.max(0, Math.round(toolbarRect.bottom - rootRect.top));
}

function getWindowHorizontalLimits(width, bounds = getWindowBounds()) {
  const visibleWidth = Math.min(DATASET_WINDOW_EDGE_VISIBLE_WIDTH, Math.max(1, Number(width) || 1));
  return {
    minX: Math.min(0, visibleWidth - width),
    maxX: Math.max(0, bounds.width - visibleWidth),
  };
}

function clampWindowRect(rect) {
  const bounds = getWindowBounds();
  const minY = getWindowTopLimit();
  const maxHeight = Math.max(DATASET_WINDOW_MIN_HEIGHT, bounds.height - minY);
  const width = Math.max(DATASET_WINDOW_MIN_WIDTH, Math.min(Number(rect.width) || 760, bounds.width));
  const height = Math.max(DATASET_WINDOW_MIN_HEIGHT, Math.min(Number(rect.height) || 500, maxHeight));
  const { minX, maxX } = getWindowHorizontalLimits(width, bounds);
  const maxY = Math.max(minY, bounds.height - DATASET_WINDOW_TITLEBAR_HEIGHT);
  const x = Math.max(minX, Math.min(Number(rect.x) || 0, maxX));
  const y = Math.max(minY, Math.min(Number(rect.y) || minY, maxY));
  return { x, y, width, height };
}

function rememberDatasetWindowSize(rect) {
  const width = Number(rect?.width);
  const height = Number(rect?.height);
  if (!Number.isFinite(width) || !Number.isFinite(height)) return;
  state.lastDatasetWindowSize = {
    width: Math.max(DATASET_WINDOW_MIN_WIDTH, Math.round(width)),
    height: Math.max(DATASET_WINDOW_MIN_HEIGHT, Math.round(height)),
  };
}

function applyWindowRect(frame, rect, options = {}) {
  const next = clampWindowRect(rect);
  frame.style.left = `${Math.round(next.x)}px`;
  frame.style.top = `${Math.round(next.y)}px`;
  frame.style.width = `${Math.round(next.width)}px`;
  frame.style.height = `${Math.round(next.height)}px`;
  if (
    frame?.classList?.contains("pi-window")
    && frame.dataset.maximized !== "1"
    && options.rememberSize !== false
  ) {
    rememberDatasetWindowSize(next);
  }
  return next;
}

function isDatasetWindowMaximized(frame) {
  return frame?.dataset?.maximized === "1";
}

function getMaximizedWindowRect() {
  const bounds = getWindowBounds();
  const minY = getWindowTopLimit();
  return {
    x: 0,
    y: minY,
    width: bounds.width,
    height: Math.max(DATASET_WINDOW_MIN_HEIGHT, bounds.height - minY),
  };
}

function getPointerRestoreRect(frame, pointerEvent, restoreRect) {
  const rootRect = els.root?.getBoundingClientRect?.();
  const currentRect = frame?.getBoundingClientRect?.();
  if (!rootRect || !currentRect || !pointerEvent) return restoreRect;
  const pointerX = pointerEvent.clientX - rootRect.left;
  const pointerY = pointerEvent.clientY - rootRect.top;
  const ratioX = clampNumber(
    (pointerEvent.clientX - currentRect.left) / Math.max(1, currentRect.width),
    0.12,
    0.88
  );
  const titleOffsetY = clampNumber(pointerEvent.clientY - currentRect.top, 8, 24);
  return {
    ...restoreRect,
    x: pointerX - restoreRect.width * ratioX,
    y: pointerY - titleOffsetY,
  };
}

function maximizeDatasetWindow(frame) {
  if (!frame) return;
  if (!isDatasetWindowMaximized(frame)) {
    frame.__piRestoreRect = getFrameRect(frame);
  }
  frame.dataset.maximized = "1";
  applyWindowRect(frame, getMaximizedWindowRect(), { rememberSize: false });
  updateDatasetWindowMaximizeControl(frame);
  raiseWindow(frame);
  notifyProjectInstanceStateChanged();
}

function restoreDatasetWindow(frame, pointerEvent = null) {
  if (!frame) return;
  const stored = frame.__piRestoreRect || getNextDatasetWindowRect(0);
  const restoreRect = pointerEvent
    ? getPointerRestoreRect(frame, pointerEvent, stored)
    : stored;
  frame.dataset.maximized = "0";
  applyWindowRect(frame, restoreRect);
  updateDatasetWindowMaximizeControl(frame);
  raiseWindow(frame);
  notifyProjectInstanceStateChanged();
}

function toggleDatasetWindowMaximized(frame) {
  if (isDatasetWindowMaximized(frame)) {
    restoreDatasetWindow(frame);
  } else {
    maximizeDatasetWindow(frame);
  }
}

function syncMaximizedDatasetWindows() {
  for (const frame of datasetWindows.values()) {
    if (!frame?.isConnected || frame.dataset.hidden === "1" || !isDatasetWindowMaximized(frame)) continue;
    applyWindowRect(frame, getMaximizedWindowRect(), { rememberSize: false });
  }
}

function updateDatasetWindowMaximizeControl(frame) {
  const button = frame?.querySelector?.(".pi-window-maximize");
  if (!button) return;
  const maximized = isDatasetWindowMaximized(frame);
  button.title = maximized ? "Restore" : "Maximize";
  button.setAttribute("aria-label", maximized ? "Restore" : "Maximize");
}

function getNextDatasetWindowRect(offset = 0) {
  const bounds = getWindowBounds();
  const minY = getWindowTopLimit();
  const availableHeight = Math.max(DATASET_WINDOW_MIN_HEIGHT, bounds.height - minY);
  const preferredWidth = state.lastDatasetWindowSize?.width
    || Math.round(bounds.width * DATASET_WINDOW_DEFAULT_WIDTH_RATIO);
  const preferredHeight = state.lastDatasetWindowSize?.height
    || Math.round(availableHeight * DATASET_WINDOW_DEFAULT_HEIGHT_RATIO);
  const width = Math.max(DATASET_WINDOW_MIN_WIDTH, Math.min(preferredWidth, bounds.width));
  const height = Math.max(DATASET_WINDOW_MIN_HEIGHT, Math.min(preferredHeight, availableHeight));
  return clampWindowRect({
    x: Math.round((bounds.width - width) / 2) + offset,
    y: Math.round(minY + (availableHeight - height) / 2) + offset,
    width,
    height,
  });
}

function raiseWindow(frame) {
  frame.style.zIndex = String(++state.nextWindowZ);
  if (frame?.classList?.contains("pi-window") && frame.dataset.hidden !== "1") {
    state.projectInstancePageFocused = false;
    state.activeDatasetWindow = frame;
  }
  syncDatasetWindowChrome();
  notifyActiveDfmWindowState();
  notifyProjectInstanceStateChanged();
}

function getActiveDatasetWindow() {
  if (state.projectInstancePageFocused) return null;
  if (
    state.activeDatasetWindow?.isConnected
    && state.activeDatasetWindow.dataset.hidden !== "1"
    && state.activeDatasetWindow.style.display !== "none"
  ) {
    return state.activeDatasetWindow;
  }
  let nextActive = null;
  let topZ = -1;
  for (const frame of datasetWindows.values()) {
    if (!frame?.isConnected || frame.dataset.hidden === "1" || frame.style.display === "none") continue;
    const z = Number.parseInt(frame.style.zIndex || "0", 10);
    if (z >= topZ) {
      topZ = z;
      nextActive = frame;
    }
  }
  state.activeDatasetWindow = nextActive;
  return nextActive;
}

function focusProjectInstancePage() {
  if (state.projectInstancePageFocused && !state.activeDatasetWindow) return;
  state.projectInstancePageFocused = true;
  state.activeDatasetWindow = null;
  syncDatasetWindowChrome();
  notifyActiveDfmWindowState();
  notifyProjectInstanceStateChanged();
}

// A dirty window asks first; the close finishes after the answer, so this returns false until then.
function closeDatasetWindow(frame, { status = true, skipChildCloseRequest = false, skipDirtyConfirm = false } = {}) {
  if (!frame?.isConnected) return false;
  const iframe = getWindowIframe(frame);
  if (!skipChildCloseRequest && iframe?.contentWindow) {
    try {
      const requestClose = iframe.contentWindow.__arcrho_request_close;
      if (typeof requestClose === "function" && requestClose() === true) return false;
    } catch {}
  }
  if (!skipDirtyConfirm && frame.dataset.dirty === "1") {
    const titleForPrompt = frame.dataset.windowDatasetName || frame.dataset.windowTitle || "this window";
    void confirmDiscardClose({ message: `Unsaved changes in ${titleForPrompt} will be lost.` }).then((ok) => {
      if (ok) closeDatasetWindow(frame, { status, skipChildCloseRequest: true, skipDirtyConfirm: true });
    });
    return false;
  }
  const title = frame.dataset.windowDatasetName || frame.dataset.windowTitle || frame.getAttribute("aria-label") || "dataset window";
  hiddenWindows.delete(frame.dataset.windowId || "");
  datasetWindows.delete(frame.dataset.windowKey || "");
  if (state.activeDatasetWindow === frame) state.activeDatasetWindow = null;
  frame.remove();
  syncDatasetWindowChrome();
  updateHiddenTabsArea();
  notifyProjectInstanceDirtyState();
  notifyActiveDfmWindowState();
  notifyProjectInstanceStateChanged();
  if (status) setStatus(`Closed ${title}`);
  return true;
}


function isDfmWindow(frame) {
  return frame?.dataset?.windowKind === "dfm";
}

function isResultSelectionWindow(frame) {
  return frame?.dataset?.windowKind === "result_selection";
}

function isBornhuetterFergusonWindow(frame) {
  return frame?.dataset?.windowKind === "bornhuetter_ferguson";
}

function isCapeCodWindow(frame) {
  return frame?.dataset?.windowKind === "cape_cod";
}

function isBootstrapWindow(frame) {
  return frame?.dataset?.windowKind === "bootstrap";
}

function isStochasticConsolidationWindow(frame) {
  return frame?.dataset?.windowKind === "stochastic_consolidation";
}

function isBerquistShermanWindow(frame) {
  return frame?.dataset?.windowKind === "berquist_sherman";
}

function findWindowByInstance(inst) {
  const id = toText(inst);
  if (!id) return null;
  for (const frame of datasetWindows.values()) {
    if (frame?.dataset?.windowId === id) return frame;
  }
  return null;
}

function findWindowByMessageSource(source) {
  if (!source) return null;
  for (const frame of datasetWindows.values()) {
    const iframe = getWindowIframe(frame);
    if (iframe?.contentWindow === source) return frame;
  }
  return null;
}

function getWindowIframe(frame) {
  return frame?.querySelector?.(".pi-window-body iframe") || null;
}

function postMessageToDatasetWindows(message, excludeSource = null, options = {}) {
  const includeDfm = !!options?.includeDfm;
  for (const frame of datasetWindows.values()) {
    if (!frame || (!includeDfm && isDfmWindow(frame))) continue;
    const iframe = getWindowIframe(frame);
    if (!iframe?.contentWindow || iframe.contentWindow === excludeSource) continue;
    try { iframe.contentWindow.postMessage(message, "*"); } catch {}
  }
}

function setWindowDirtyState(frame, dirty) {
  if (!frame) return;
  frame.dataset.dirty = dirty ? "1" : "0";
  frame.classList.toggle("dirty", !!dirty);
  const closeBtn = frame.querySelector(".pi-window-close");
  if (closeBtn) {
    closeBtn.title = dirty ? "Unsaved changes (close)" : "Close";
    closeBtn.setAttribute("aria-label", dirty ? "Unsaved changes (close)" : "Close");
  }
  if (frame.dataset.hidden === "1") updateHiddenTabsArea();
  notifyProjectInstanceDirtyState();
  notifyProjectInstanceStateChanged();
}

// A method page that runs a model reports its run state for a chip beside the
// window title; an empty label removes the chip.
function setWindowRunState(frame, runState, label) {
  const title = frame?.querySelector(".pi-window-title");
  if (!title) return;
  let chip = frame.querySelector(".pi-window-run-state");
  if (!label) {
    chip?.remove();
    return;
  }
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "pi-window-run-state";
    chip.innerHTML = '<span class="pi-window-run-state-dot" aria-hidden="true"></span><span class="pi-window-run-state-label"></span>';
    title.after(chip);
  }
  chip.dataset.state = toText(runState);
  chip.querySelector(".pi-window-run-state-label").textContent = label;
}

function hasDirtyDfmWindow() {
  for (const frame of datasetWindows.values()) {
    if (frame?.dataset?.dirty === "1") return true;
  }
  return false;
}

function notifyProjectInstanceDirtyState() {
  try {
    window.parent?.postMessage({
      type: "arcrho:project-instance-dirty",
      dirty: hasDirtyDfmWindow(),
    }, "*");
  } catch {}
}

function notifyActiveDfmWindowState() {
  const frame = getActiveDfmWindow();
  try {
    window.parent?.postMessage({
      type: "arcrho:project-instance-dfm-active-state",
      active: !!frame,
      inst: frame?.dataset?.windowId || "",
      title: frame?.dataset?.windowTitle || "",
      tab: frame?.dataset?.dfmTab || "",
      canUndo: frame?.dataset?.dfmCanUndo === "1",
      canRedo: frame?.dataset?.dfmCanRedo === "1",
      editEnabled: frame?.dataset?.dfmEditEnabled === "1",
    }, "*");
  } catch {}
}

function getActiveDfmWindow() {
  if (state.projectInstancePageFocused) return null;
  const active = getActiveDatasetWindow();
  if (isDfmWindow(active)) return active;
  let topDfm = null;
  let topZ = -1;
  for (const frame of datasetWindows.values()) {
    if (!isDfmWindow(frame) || !frame?.isConnected || frame.dataset.hidden === "1" || frame.style.display === "none") continue;
    const z = Number.parseInt(frame.style.zIndex || "0", 10);
    if (z >= topZ) {
      topZ = z;
      topDfm = frame;
    }
  }
  return topDfm;
}


function resizeRectFromCorner(start, corner, dx, dy) {
  const bounds = getWindowBounds();
  const minY = getWindowTopLimit();
  const { minX } = getWindowHorizontalLimits(start.width, bounds);
  const next = {
    x: start.x,
    y: start.y,
    width: start.width,
    height: start.height,
  };

  if (corner.includes("e")) {
    next.width = clampNumber(start.width + dx, DATASET_WINDOW_MIN_WIDTH, bounds.width);
  }
  if (corner.includes("s")) {
    next.height = clampNumber(start.height + dy, DATASET_WINDOW_MIN_HEIGHT, bounds.height - minY);
  }
  if (corner.includes("w")) {
    const right = start.x + start.width;
    next.x = clampNumber(start.x + dx, minX, right - DATASET_WINDOW_MIN_WIDTH);
    next.width = right - next.x;
  }
  if (corner.includes("n")) {
    const bottom = start.y + start.height;
    next.y = clampNumber(start.y + dy, minY, bottom - DATASET_WINDOW_MIN_HEIGHT);
    next.height = bottom - next.y;
  }

  return next;
}

function lockDatasetViewerInputs(iframe, datasetTypeName, pathValue = state.selectedPath) {
  let doc = null;
  try {
    doc = iframe.contentDocument || iframe.contentWindow?.document || null;
  } catch {
    return;
  }
  if (!doc) return;

  const projectInput = doc.getElementById("projectSelect");
  const pathInput = doc.getElementById("pathInput");
  const triInput = doc.getElementById("triInput");
  if (projectInput) {
    projectInput.value = projectName;
    projectInput.readOnly = true;
    projectInput.title = "Project is set by the project instance tab.";
  }
  if (pathInput) {
    pathInput.value = pathValue;
    pathInput.readOnly = true;
    pathInput.title = "Reserving class path is set by the project instance tab.";
  }
  if (triInput && datasetTypeName) {
    triInput.value = datasetTypeName;
  }
  // Segment has no picker at all any more, so only the project button is left
  // to disable here.
  const projectButton = doc.getElementById("projectTreeBtn");
  if (projectButton) {
    projectButton.disabled = true;
    projectButton.title = "Set by the project instance tab";
  }
}

function wireDatasetViewerWindowShortcuts(iframe, frame) {
  let doc = null;
  try {
    doc = iframe.contentDocument || iframe.contentWindow?.document || null;
  } catch {
    return;
  }
  if (!doc || doc.__piWindowShortcutsWired) return;
  doc.__piWindowShortcutsWired = true;
  doc.addEventListener("mousedown", () => raiseWindow(frame), true);
  doc.addEventListener("focusin", () => raiseWindow(frame), true);
  doc.addEventListener("keydown", (event) => {
    if (event.defaultPrevented) return;
    if (isDfmWindow(frame) && routeDfmRatioHotkey(event)) return;
    if (
      isDfmWindow(frame)
      && event.ctrlKey
      && !event.altKey
      && !event.metaKey
      && String(event.key || "").toLowerCase() === "s"
    ) {
      event.preventDefault();
      event.stopPropagation();
      routeDfmWindowCommand(event.shiftKey ? "arcrho:dfm-save-as" : "arcrho:dfm-save");
      return;
    }
    closeActiveDatasetWindowFromShortcut(event, frame);
  }, true);
}

function buildDatasetViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  params.set("project", projectName);
  params.set("path", toText(options?.path) || state.selectedPath);
  const instanceName = toText(datasetName);
  const datasetTypeName = toText(options?.datasetTypeName) || instanceName;
  if (datasetTypeName) params.set("tri", datasetTypeName);
  if (instanceName && instanceName !== datasetTypeName) params.set("instance_name", instanceName);
  if (options?.originLen) params.set("origin_len", String(options.originLen));
  if (options?.devLen) params.set("dev_len", String(options.devLen));
  if (options?.dataFormat) params.set("data_format", toText(options.dataFormat));
  if (options?.numberFormat) params.set("number_format", toText(options.numberFormat));
  if (options?.decimalPlaces !== undefined && options?.decimalPlaces !== null) {
    params.set("decimal_places", String(options.decimalPlaces));
  }
  if (options?.dsId) params.set("ds", toText(options.dsId));
  if (options?.readOnly) params.set("readonly", "1");
  if (options?.temporaryViewSessionId) {
    params.set("temporary_view", "1");
    params.set("temporary_session_id", toText(options.temporaryViewSessionId));
  }
  if (options?.draft) params.set("draft_instance", "1");
  if (options?.initialTab) params.set("tab", toText(options.initialTab));
  const methodType = toText(options?.methodType).toLowerCase();
  if (["dfm", "result selection", "rs", "bornhuetter ferguson", "bf", "cape cod", "cc", "bootstrap", "stochastic consolidation"].includes(methodType)) {
    params.set("vector_column_label", "Ultimate");
  }
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/dataset_viewer/dataset_viewer.html?${params.toString()}`;
}

function buildDfmViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("dfm", options?.initialTab || options?.dfmTab);
  const methodName = options?.fresh ? "" : toText(options?.methodName || name);
  const outputType = options?.fresh ? "" : toText(options?.outputType || name);
  const outputDataset = options?.fresh
    ? ""
    : toText(options?.outputDataset || options?.output_dataset || "");
  const inputTriangle = toText(options?.inputTriangle || "");
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (methodName) params.set("method_name", methodName);
  if (outputType) params.set("output_type", outputType);
  if (outputDataset) params.set("output_dataset", outputDataset);
  if (inputTriangle) params.set("input_triangle", inputTriangle);
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/dfm/dfm.html?${params.toString()}`;
}

function buildResultSelectionViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("result_selection", options?.initialTab || options?.rsTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (name) params.set("name", name);
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.datasetTypeName) params.set("dataset_type", toText(options.datasetTypeName));
  if (options?.category) params.set("category", toText(options.category));
  if (options?.originLength) params.set("origin_length", toText(options.originLength));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/result_selection/result_selection.html?${params.toString()}`;
}

function buildBornhuetterFergusonViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("bornhuetter_ferguson", options?.initialTab || options?.bfTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (name) params.set("name", name);
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.datasetTypeName) params.set("dataset_type", toText(options.datasetTypeName));
  if (options?.category) params.set("category", toText(options.category));
  if (options?.originLength) params.set("origin_length", toText(options.originLength));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html?${params.toString()}`;
}

function buildCapeCodViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("cape_cod", options?.initialTab || options?.ccTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (name) params.set("name", name);
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.datasetTypeName) params.set("dataset_type", toText(options.datasetTypeName));
  if (options?.category) params.set("category", toText(options.category));
  if (options?.originLength) params.set("origin_length", toText(options.originLength));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/cape_cod/cape_cod.html?${params.toString()}`;
}

function buildBootstrapViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("bootstrap", options?.initialTab || options?.bstTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (name) params.set("name", name);
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.category) params.set("category", toText(options.category));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/bootstrap/bootstrap.html?${params.toString()}`;
}

function buildStochasticConsolidationViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const initialTab = windowTab("stochastic_consolidation", options?.initialTab || options?.sconTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  if (name) params.set("name", name);
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.category) params.set("category", toText(options.category));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/stochastic_consolidation/stochastic_consolidation.html?${params.toString()}`;
}

function buildBerquistShermanViewerUrl(datasetName, inst, options = {}) {
  const params = new URLSearchParams();
  const name = toText(datasetName);
  const variant = normalizeBerquistShermanVariant(options?.variant || options?.methodType || options?.sourceKind);
  const initialTab = windowTab("berquist_sherman", options?.initialTab || options?.bsTab);
  const targetPath = normalizePath(options?.path || state.selectedPath);
  params.set("project", projectName);
  params.set("class", targetPath);
  params.set("variant", variant);
  if (!options?.fresh && name) params.set("name", toText(options?.methodName || name));
  if (options?.outputType) params.set("output_type", toText(options.outputType));
  if (options?.datasetTypeName) params.set("dataset_type", toText(options.datasetTypeName));
  if (options?.category) params.set("category", toText(options.category));
  if (options?.originLength) params.set("origin_length", toText(options.originLength));
  if (options?.fresh) params.set("fresh", "1");
  if (options?.inputTriangle) params.set("input_triangle", toText(options.inputTriangle));
  params.set("tab", initialTab);
  params.set("inst", inst);
  params.set("project_instance", "1");
  params.set("v", String(Date.now()));
  return `/ui/method_pages/berquist_sherman/berquist_sherman.html?${params.toString()}`;
}

function beginWindowDragCapture(mode) {
  const shield = document.createElement("div");
  shield.className = `pi-window-drag-shield ${mode || "moving"}`;
  els.windowLayer?.appendChild(shield);
  return () => {
    if (shield.parentNode) shield.parentNode.removeChild(shield);
  };
}

// Follows every pointer event of one gesture on the handle that received the
// pointerdown (arcrho-ui-design L16): the handle captures the pointer, so a
// fast drag across an embedded iframe or out of the app never loses the window.
function trackPointerDrag(handle, event, onMove, onEnd) {
  const pointerId = event.pointerId;
  let ended = false;
  const move = (e) => {
    if (e.pointerId === pointerId) onMove(e);
  };
  const end = (e) => {
    if (e.pointerId !== pointerId || ended) return;
    ended = true;
    handle.removeEventListener("pointermove", move);
    handle.removeEventListener("pointerup", end);
    handle.removeEventListener("pointercancel", end);
    handle.removeEventListener("lostpointercapture", end);
    if (handle.hasPointerCapture?.(pointerId)) handle.releasePointerCapture(pointerId);
    onEnd();
  };
  handle.addEventListener("pointermove", move);
  handle.addEventListener("pointerup", end);
  handle.addEventListener("pointercancel", end);
  handle.addEventListener("lostpointercapture", end);
  handle.setPointerCapture?.(pointerId);
  event.preventDefault();
}

function startMove(frame, event) {
  if (event.button !== 0) return;
  raiseWindow(frame);
  const releaseDragCapture = beginWindowDragCapture("moving");
  const getStart = (sourceEvent) => {
    const startRect = frame.getBoundingClientRect();
    const rootRect = els.root.getBoundingClientRect();
    return {
      x: startRect.left - rootRect.left,
      y: startRect.top - rootRect.top,
      width: startRect.width,
      height: startRect.height,
      px: sourceEvent.clientX,
      py: sourceEvent.clientY,
    };
  };
  let start = getStart(event);

  trackPointerDrag(event.currentTarget || frame, event, (e) => {
    if (isDatasetWindowMaximized(frame)) {
      restoreDatasetWindow(frame, e);
      start = getStart(e);
    }
    applyWindowRect(frame, {
      x: start.x + e.clientX - start.px,
      y: start.y + e.clientY - start.py,
      width: start.width,
      height: start.height,
    });
  }, () => {
    releaseDragCapture();
    notifyProjectInstanceStateChanged();
  });
}

function startResize(frame, event, corner = "se") {
  if (event.button !== 0) return;
  if (isDatasetWindowMaximized(frame)) {
    restoreDatasetWindow(frame);
  }
  raiseWindow(frame);
  const resizeCorner = String(corner || "se").toLowerCase();
  const releaseDragCapture = beginWindowDragCapture(`resizing-${resizeCorner}`);
  const startRect = frame.getBoundingClientRect();
  const rootRect = els.root.getBoundingClientRect();
  const start = {
    x: startRect.left - rootRect.left,
    y: startRect.top - rootRect.top,
    width: startRect.width,
    height: startRect.height,
    px: event.clientX,
    py: event.clientY,
  };

  trackPointerDrag(event.currentTarget || frame, event, (e) => {
    applyWindowRect(
      frame,
      resizeRectFromCorner(start, resizeCorner, e.clientX - start.px, e.clientY - start.py)
    );
  }, () => {
    releaseDragCapture();
    notifyProjectInstanceStateChanged();
  });
}

function createFloatingContentWindow(options = {}) {
  const name = toText(options.name);
  const title = toText(options.title) || name;
  const windowKey = toText(options.windowKey);
  const inst = toText(options.inst) || `pi_window_${Date.now()}_${state.windowSeq++}`;
  const iframeSrc = toText(options.iframeSrc);
  if (!name || !title || !windowKey || !iframeSrc) return null;

  const existing = datasetWindows.get(windowKey);
  if (existing?.isConnected) {
    if (toText(options.kind).toLowerCase() === "dfm") {
      const outputDataset = toText(options.outputDataset || options.output_dataset || "");
      if (outputDataset) existing.dataset.windowOutputDataset = outputDataset;
    }
    void activateDatasetWindow(existing);
    return existing;
  }
  datasetWindows.delete(windowKey);

  const frame = document.createElement("section");
  frame.className = "pi-window";
  frame.dataset.windowId = inst;
  frame.dataset.windowKey = windowKey;
  frame.dataset.windowDatasetName = name;
  frame.dataset.windowItemName = toText(options.itemName) || name;
  frame.dataset.windowPath = normalizePath(options.path || state.selectedPath);
  frame.dataset.windowTitle = title;
  frame.dataset.windowKind = toText(options.kind) || "dataset";
  if (frame.dataset.windowKind === "dfm") {
    const outputDataset = toText(options.outputDataset || options.output_dataset || "");
    if (outputDataset) frame.dataset.windowOutputDataset = outputDataset;
  }
  const temporaryViewSessionId = toText(options.temporaryViewSessionId);
  if (temporaryViewSessionId) frame.dataset.temporaryViewSessionId = temporaryViewSessionId;
  frame.dataset.dirty = "0";
  const methodType = toText(options.methodType || (
    frame.dataset.windowKind === "dfm"
      ? "DFM"
      : frame.dataset.windowKind === "bornhuetter_ferguson"
        ? "Bornhuetter Ferguson"
        : frame.dataset.windowKind === "cape_cod"
          ? "Cape Cod"
          : frame.dataset.windowKind === "bootstrap"
            ? "Bootstrap"
            : frame.dataset.windowKind === "stochastic_consolidation"
              ? "Stochastic Consolidation"
              : frame.dataset.windowKind === "berquist_sherman"
                ? getBerquistShermanContract(options.bsVariant || options.variant)?.methodType || ""
                : ""
  ));
  if (methodType) frame.dataset.windowMethodType = methodType;
  if (frame.dataset.windowKind === "dfm") {
    frame.dataset.dfmTab = windowTab("dfm", options.dfmTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "result_selection") {
    frame.dataset.rsTab = windowTab("result_selection", options.rsTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "bornhuetter_ferguson") {
    frame.dataset.bfTab = windowTab("bornhuetter_ferguson", options.bfTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "cape_cod") {
    frame.dataset.ccTab = windowTab("cape_cod", options.ccTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "bootstrap") {
    frame.dataset.bstTab = windowTab("bootstrap", options.bstTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "stochastic_consolidation") {
    frame.dataset.sconTab = windowTab("stochastic_consolidation", options.sconTab || options.initialTab);
  }
  if (frame.dataset.windowKind === "berquist_sherman") {
    frame.dataset.bsTab = windowTab("berquist_sherman", options.bsTab || options.initialTab);
    frame.dataset.bsVariant = normalizeBerquistShermanVariant(options.bsVariant || options.variant || methodType);
  }
  frame.setAttribute("aria-label", title);
  frame.innerHTML = `
    <header class="pi-window-titlebar">
      <span class="pi-window-title"></span>
      <span class="pi-window-dirty" title="Unsaved changes" aria-hidden="true"></span>
      <div class="pi-window-titlebar-controls">
        <button class="pi-window-titlebar-btn pi-window-minimize" type="button" title="Minimize" aria-label="Minimize">
          <svg class="pi-window-titlebar-icon" viewBox="0 0 10 10" aria-hidden="true">
            <line x1="2" y1="7" x2="8" y2="7"></line>
          </svg>
        </button>
        <button class="pi-window-titlebar-btn pi-window-maximize" type="button" title="Maximize" aria-label="Maximize">
          <svg class="pi-window-titlebar-icon" viewBox="0 0 10 10" aria-hidden="true">
            <rect x="2" y="2" width="6" height="6" rx="0.6"></rect>
          </svg>
        </button>
        <button class="pi-window-titlebar-btn pi-window-close" type="button" title="Close" aria-label="Close">
          <svg class="pi-window-titlebar-icon" viewBox="0 0 10 10" aria-hidden="true">
            <line x1="2" y1="2" x2="8" y2="8"></line>
            <line x1="8" y1="2" x2="2" y2="8"></line>
          </svg>
        </button>
      </div>
    </header>
    <div class="pi-window-body"></div>
    <div class="pi-window-resize pi-window-resize-nw" data-corner="nw" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-edge pi-window-resize-n" data-corner="n" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-ne" data-corner="ne" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-edge pi-window-resize-e" data-corner="e" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-se" data-corner="se" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-edge pi-window-resize-s" data-corner="s" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-sw" data-corner="sw" title="Resize"></div>
    <div class="pi-window-resize pi-window-resize-edge pi-window-resize-w" data-corner="w" title="Resize"></div>
  `;

  updateDatasetWindowTitle(frame);

  const body = frame.querySelector(".pi-window-body");
  const iframe = document.createElement("iframe");
  iframe.src = iframeSrc;
  iframe.addEventListener("load", () => {
    wireDatasetViewerWindowShortcuts(iframe, frame);
    postZoomToDatasetFrame(iframe);
    if (isDfmWindow(frame)) {
      try { iframe.contentWindow?.postMessage({ type: "arcrho:dfm-request-state" }, "*"); } catch {}
      notifyActiveDfmWindowState();
    }
    if (typeof options.onIframeLoad === "function") {
      options.onIframeLoad(iframe, frame);
    }
  });
  body.appendChild(iframe);

  const titlebar = frame.querySelector(".pi-window-titlebar");
  titlebar?.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    startMove(frame, e);
  });
  titlebar?.addEventListener("dblclick", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    toggleDatasetWindowMaximized(frame);
  });
  titlebar?.addEventListener("contextmenu", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    hideDatasetWindow(frame, getFrameRect(frame));
  });
  for (const handle of frame.querySelectorAll(".pi-window-resize")) {
    handle.addEventListener("pointerdown", (e) => {
      startResize(frame, e, handle.getAttribute("data-corner") || "se");
    });
  }
  frame.querySelector(".pi-window-minimize")?.addEventListener("click", () => {
    hideDatasetWindow(frame, getFrameRect(frame));
  });
  frame.querySelector(".pi-window-maximize")?.addEventListener("click", () => {
    toggleDatasetWindowMaximized(frame);
  });
  frame.querySelector(".pi-window-close")?.addEventListener("click", () => closeDatasetWindow(frame));
  frame.addEventListener("mousedown", () => raiseWindow(frame));

  const offset = ((state.windowSeq - 1) % 5) * 26;
  els.windowLayer.appendChild(frame);
  datasetWindows.set(windowKey, frame);
  applyWindowRect(frame, getNextDatasetWindowRect(offset));
  raiseWindow(frame);
  notifyProjectInstanceStateChanged();
  setStatus(`Opened ${title}`);
  return frame;
}

function openDatasetWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  const datasetTypeName = toText(options?.datasetTypeName) || name;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!name) return;
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a dataset.", true);
    return;
  }

  const temporaryViewSessionId = toText(options?.temporaryViewSessionId);
  const windowKey = getDatasetWindowKey(name, targetPath, temporaryViewSessionId);
  const title = temporaryViewSessionId
    ? `Temporary view: ${targetPath}\\${name}`
    : `${targetPath}\\${name}`;
  const inst = `pi_ds_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "dataset",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildDatasetViewerUrl(name, inst, {
      datasetTypeName,
      path: targetPath,
      dataFormat: options?.dataFormat,
      readOnly: options?.readOnly,
      methodType: options?.methodType,
      temporaryViewSessionId,
      initialTab: windowTab("dataset", options?.initialTab),
    }),
    path: targetPath,
    methodType: options?.methodType,
    temporaryViewSessionId,
    onIframeLoad: (iframe) => {
      lockDatasetViewerInputs(iframe, datasetTypeName, targetPath);
      window.setTimeout(() => lockDatasetViewerInputs(iframe, datasetTypeName, targetPath), 250);
    },
  });
}

function closeTemporaryDatasetWindows(temporaryViewSessionId) {
  const sessionId = toText(temporaryViewSessionId);
  if (!sessionId) return true;
  const frames = Array.from(datasetWindows.values())
    .filter((frame) => frame?.isConnected && toText(frame.dataset?.temporaryViewSessionId) === sessionId);
  for (const frame of frames) {
    if (!closeDatasetWindow(frame, { status: false })) return false;
  }
  return true;
}

function openNewDatasetDraftWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  const datasetTypeName = toText(options?.datasetTypeName) || name;
  if (!name) return null;
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a dataset.", true);
    return null;
  }

  const windowKey = `${getDatasetWindowKey(name)}\u0001draft\u0001${Date.now()}`;
  const isDraft = options?.draft !== false;
  const title = isDraft ? `${state.selectedPath}\\New Dataset: ${name}` : `${state.selectedPath}\\${name}`;
  const inst = `pi_ds_new_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "dataset",
    name: isDraft ? `New: ${name}` : name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildDatasetViewerUrl(name, inst, {
      datasetTypeName,
      originLen: options?.originLen || 12,
      devLen: options?.devLen || 12,
      dataFormat: options?.dataFormat,
      numberFormat: isDraft ? (options?.numberFormat || "0,000") : options?.numberFormat,
      decimalPlaces: isDraft ? (options?.decimalPlaces ?? 0) : options?.decimalPlaces,
      dsId: options?.dsId,
      readOnly: options?.readOnly,
      draft: isDraft,
      // A draft opens on Details whatever the saved default is: its Dataset
      // Type, lengths and format have to be filled in before there is data.
      initialTab: options?.initialTab || "details",
    }),
    methodType: options?.methodType,
    onIframeLoad: (iframe) => {
      lockDatasetViewerInputs(iframe, datasetTypeName);
      window.setTimeout(() => lockDatasetViewerInputs(iframe, datasetTypeName), 250);
    },
  });
}

function openDfmWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a DFM object.", true);
    return;
  }

  recordSelectedDfmObject(name);
  const windowKey = getDfmWindowKey(name, targetPath);
  const title = `${targetPath}\\DFM\\${name}`;
  const initialTab = windowTab("dfm", options.initialTab || options.dfmTab);
  const inst = `pi_dfm_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "dfm",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildDfmViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    initialTab,
    methodType: options.methodType || "DFM",
    outputDataset: toText(options.outputDataset || options.output_dataset || ""),
  });
}

function syncDfmWindowIdentity(frame, methodName, outputDataset = "") {
  if (!frame?.isConnected || !isDfmWindow(frame)) return false;
  const name = toText(methodName);
  const targetPath = getWindowPath(frame);
  if (!name || !targetPath) return false;

  const previousKey = toText(frame.dataset.windowKey);
  const canonicalKey = getDfmWindowKey(name, targetPath);
  let nextKey = canonicalKey;
  const existing = datasetWindows.get(canonicalKey);
  if (existing && existing !== frame) {
    if (existing.isConnected) {
      // A server-side Save As should normally make this impossible. Keep both
      // frames addressable if another live window nevertheless owns the key.
      nextKey = `${canonicalKey}\u0001instance\u0001${toText(frame.dataset.windowId) || Date.now()}`;
      setStatus(`DFM ${name} is already open; both windows were kept.`, true);
    } else {
      datasetWindows.delete(canonicalKey);
    }
  }
  if (previousKey && datasetWindows.get(previousKey) === frame) {
    datasetWindows.delete(previousKey);
  }

  const title = `${targetPath}\\DFM\\${name}`;
  frame.dataset.windowKey = nextKey;
  frame.dataset.windowDatasetName = name;
  frame.dataset.windowItemName = name;
  frame.dataset.windowTitle = title;
  const declaredOutputDataset = toText(outputDataset);
  if (declaredOutputDataset) frame.dataset.windowOutputDataset = declaredOutputDataset;
  frame.setAttribute("aria-label", title);
  datasetWindows.set(nextKey, frame);

  const hiddenItem = hiddenWindows.get(frame.dataset.windowId || "");
  if (hiddenItem) {
    hiddenItem.title = name;
    hiddenItem.fullTitle = title;
  }
  syncDatasetWindowChrome();
  updateHiddenTabsArea();
  notifyProjectInstanceStateChanged();
  return true;
}

function openResultSelectionWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Result Selection object.", true);
    return;
  }

  const windowKey = `rs\u0001${targetPath}\u0001${name.toLowerCase()}`;
  const title = `${targetPath}\\Result Selection\\${name}`;
  const initialTab = windowTab("result_selection", options.initialTab || options.rsTab);
  const inst = `pi_rs_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "result_selection",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildResultSelectionViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    methodType: options.methodType || "Result Selection",
    initialTab,
  });
}

function openBornhuetterFergusonWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Bornhuetter Ferguson object.", true);
    return;
  }

  const windowKey = getBornhuetterFergusonWindowKey(name, targetPath);
  const title = `${targetPath}\\Bornhuetter Ferguson\\${name}`;
  const initialTab = windowTab("bornhuetter_ferguson", options.initialTab || options.bfTab);
  const inst = `pi_bf_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "bornhuetter_ferguson",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildBornhuetterFergusonViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    methodType: options.methodType || "Bornhuetter Ferguson",
    initialTab,
  });
}

function openCapeCodWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Cape Cod object.", true);
    return;
  }

  const windowKey = getCapeCodWindowKey(name, targetPath);
  const title = `${targetPath}\\Cape Cod\\${name}`;
  const initialTab = windowTab("cape_cod", options.initialTab || options.ccTab);
  const inst = `pi_cc_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "cape_cod",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildCapeCodViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    methodType: options.methodType || "Cape Cod",
    initialTab,
  });
}

function openBootstrapWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Bootstrap object.", true);
    return;
  }

  const windowKey = getBootstrapWindowKey(name, targetPath);
  const title = `${targetPath}\\Bootstrap\\${name}`;
  const initialTab = windowTab("bootstrap", options.initialTab || options.bstTab);
  const inst = `pi_bst_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "bootstrap",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildBootstrapViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    methodType: options.methodType || "Bootstrap",
    initialTab,
  });
}

function openStochasticConsolidationWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Stochastic Consolidation object.", true);
    return;
  }

  const windowKey = getStochasticConsolidationWindowKey(name, targetPath);
  const title = `${targetPath}\\Stochastic Consolidation\\${name}`;
  const initialTab = windowTab("stochastic_consolidation", options.initialTab || options.sconTab);
  const inst = `pi_scon_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "stochastic_consolidation",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildStochasticConsolidationViewerUrl(name, inst, { ...options, path: targetPath, initialTab }),
    path: targetPath,
    methodType: options.methodType || "Stochastic Consolidation",
    initialTab,
  });
}

function openBerquistShermanWindow(datasetName, options = {}) {
  const name = toText(datasetName);
  if (!name) return;
  const targetPath = normalizePath(options?.path || state.selectedPath);
  if (!targetPath) {
    setStatus("Select a reserving class path before opening a Berquist Sherman object.", true);
    return;
  }
  const contract = getBerquistShermanContract(options.variant || options.bsVariant || options.methodType || options.sourceKind);
  if (!contract) {
    setStatus("Choose a Berquist Sherman method variant before opening the object.", true);
    return;
  }

  const windowKey = getBerquistShermanWindowKey(name, contract.variant, targetPath);
  const title = `${targetPath}\\${contract.displayLabel}\\${name}`;
  const initialTab = windowTab("berquist_sherman", options.initialTab || options.bsTab);
  const inst = `pi_bs_${contract.variant}_${Date.now()}_${state.windowSeq++}`;
  return createFloatingContentWindow({
    kind: "berquist_sherman",
    name,
    itemName: name,
    title,
    windowKey,
    inst,
    iframeSrc: buildBerquistShermanViewerUrl(name, inst, {
      ...options,
      variant: contract.variant,
      path: targetPath,
      initialTab,
    }),
    path: targetPath,
    methodType: contract.methodType,
    initialTab,
    bsVariant: contract.variant,
  });
}

function syncBerquistShermanWindowIdentity(frame, datasetName, variant = "") {
  if (!frame?.isConnected || !isBerquistShermanWindow(frame)) return false;
  const name = toText(datasetName);
  const contract = getBerquistShermanContract(variant || frame.dataset.bsVariant || getWindowMethodType(frame));
  const targetPath = getWindowPath(frame);
  if (!name || !contract || !targetPath) return false;

  const previousKey = toText(frame.dataset.windowKey);
  const nextKey = getBerquistShermanWindowKey(name, contract.variant, targetPath);
  const existing = datasetWindows.get(nextKey);
  if (existing && existing !== frame) {
    if (existing.isConnected) {
      setStatus(`${contract.displayLabel} ${name} is already open.`, true);
      return false;
    }
    datasetWindows.delete(nextKey);
  }
  if (previousKey && datasetWindows.get(previousKey) === frame) {
    datasetWindows.delete(previousKey);
  }

  const title = `${targetPath}\\${contract.displayLabel}\\${name}`;
  frame.dataset.windowKey = nextKey;
  frame.dataset.windowDatasetName = name;
  frame.dataset.windowItemName = name;
  frame.dataset.windowTitle = title;
  frame.dataset.windowMethodType = contract.methodType;
  frame.dataset.bsVariant = contract.variant;
  frame.setAttribute("aria-label", title);
  datasetWindows.set(nextKey, frame);

  const hiddenItem = hiddenWindows.get(frame.dataset.windowId || "");
  if (hiddenItem) {
    hiddenItem.title = name;
    hiddenItem.fullTitle = title;
  }
  syncDatasetWindowChrome();
  updateHiddenTabsArea();
  notifyProjectInstanceStateChanged();
  return true;
}

function applyRestoredWindowState(frame, item = {}) {
  if (!frame?.isConnected) return;
  const rect = item?.rect && typeof item.rect === "object" ? item.rect : null;
  if (!item?.maximized) {
    frame.dataset.maximized = "0";
    delete frame.__piRestoreRect;
    updateDatasetWindowMaximizeControl(frame);
  }
  if (rect) applyWindowRect(frame, rect);
  if (item?.maximized) maximizeDatasetWindow(frame);
  if (toText(item?.dfmTab) && isDfmWindow(frame)) {
    frame.dataset.dfmTab = toText(item.dfmTab);
  }
  if (toText(item?.rsTab) && isResultSelectionWindow(frame)) {
    frame.dataset.rsTab = toText(item.rsTab);
  }
  if (toText(item?.bfTab) && isBornhuetterFergusonWindow(frame)) {
    frame.dataset.bfTab = toText(item.bfTab);
  }
  if (toText(item?.ccTab) && isCapeCodWindow(frame)) {
    frame.dataset.ccTab = toText(item.ccTab);
  }
  if (toText(item?.bstTab) && isBootstrapWindow(frame)) {
    frame.dataset.bstTab = toText(item.bstTab);
  }
  if (toText(item?.sconTab) && isStochasticConsolidationWindow(frame)) {
    frame.dataset.sconTab = toText(item.sconTab);
  }
  if (isBerquistShermanWindow(frame)) {
    if (toText(item?.bsTab)) frame.dataset.bsTab = toText(item.bsTab);
    const variant = normalizeBerquistShermanVariant(item?.bsVariant || item?.methodType);
    if (variant) frame.dataset.bsVariant = variant;
  }
  const id = frame.dataset.windowId || "";
  if (item?.hidden) {
    hiddenWindows.set(id, {
      frame,
      title: frame.dataset.windowDatasetName || frame.dataset.windowTitle || "Dataset",
      fullTitle: frame.dataset.windowTitle || frame.getAttribute("aria-label") || "Dataset",
      restoreRect: rect || getFrameRect(frame),
    });
    frame.dataset.hidden = "1";
    frame.style.display = "none";
    if (state.activeDatasetWindow === frame) state.activeDatasetWindow = null;
  } else {
    hiddenWindows.delete(id);
    frame.dataset.hidden = "0";
    frame.style.display = "";
  }
}

async function applyProjectInstanceRestoreState(rawState) {
  const restoreState = rawState && typeof rawState === "object" ? rawState : {};
  const path = normalizePath(restoreState.selectedPath || restoreState.path || "");
  if (path) {
    setSelectedPath(path, { persist: false });
    await waitForPathTreeRender();
    markPathTreeActive(path);
  }
  const windows = Array.isArray(restoreState.windows) ? restoreState.windows : [];
  let activeTarget = null;
  for (const item of windows) {
    const rawKind = toText(item?.kind).toLowerCase();
    const methodType = toText(item?.methodType || item?.method_type);
    const bsVariant = normalizeBerquistShermanVariant(item?.bsVariant || item?.bs_variant || methodType);
    const title = toText(item?.title);
    const isLegacyResultSelectionMethod = (
      rawKind === "dataset"
      && methodType.toLowerCase() === "result selection"
      && /(^|[\\/])result selection([\\/]|$)/i.test(title)
    );
    const isBornhuetterFergusonMethod = methodType.toLowerCase() === "bornhuetter ferguson";
    const isCapeCodMethod = methodType.toLowerCase() === "cape cod";
    const isBootstrapMethod = methodType.toLowerCase() === "bootstrap";
    const isStochasticConsolidationMethod = methodType.toLowerCase() === "stochastic consolidation";
    const kind = rawKind === "dfm"
      ? "dfm"
      : rawKind === "result_selection" || isLegacyResultSelectionMethod
        ? "result_selection"
        : rawKind === "bornhuetter_ferguson" || isBornhuetterFergusonMethod
          ? "bornhuetter_ferguson"
          : rawKind === "cape_cod" || isCapeCodMethod
            ? "cape_cod"
            : rawKind === "bootstrap" || isBootstrapMethod
              ? "bootstrap"
              : rawKind === "stochastic_consolidation" || isStochasticConsolidationMethod
                ? "stochastic_consolidation"
                : rawKind === "berquist_sherman" || !!bsVariant
                  ? "berquist_sherman"
                  : "dataset";
    const name = toText(item?.name || item?.datasetName || item?.methodName);
    if (!name) continue;
    const frame = kind === "dfm"
      ? openDfmWindow(name, {
        initialTab: item?.dfmTab,
        methodType,
        outputDataset: toText(item?.outputDataset || item?.output_dataset || ""),
      })
      : kind === "result_selection"
        ? openResultSelectionWindow(name, { initialTab: item?.rsTab, rsTab: item?.rsTab, methodType })
        : kind === "bornhuetter_ferguson"
          ? openBornhuetterFergusonWindow(name, { initialTab: item?.bfTab, bfTab: item?.bfTab, methodType })
          : kind === "cape_cod"
            ? openCapeCodWindow(name, { initialTab: item?.ccTab, ccTab: item?.ccTab, methodType })
            : kind === "bootstrap"
              ? openBootstrapWindow(name, { initialTab: item?.bstTab, bstTab: item?.bstTab, methodType })
              : kind === "stochastic_consolidation"
                ? openStochasticConsolidationWindow(name, { initialTab: item?.sconTab, sconTab: item?.sconTab, methodType })
              : kind === "berquist_sherman"
              ? openBerquistShermanWindow(name, {
                path: item?.path,
                initialTab: item?.bsTab,
                bsTab: item?.bsTab,
                bsVariant,
                methodType,
              })
              : openDatasetWindow(name, { methodType });
    applyRestoredWindowState(frame, item);
    if (item?.active) activeTarget = frame;
  }
  updateHiddenTabsArea();
  if (activeTarget?.isConnected && activeTarget.dataset.hidden !== "1") {
    raiseWindow(activeTarget);
  } else {
    notifyActiveDfmWindowState();
  }
  notifyProjectInstanceStateChanged();
}

  Object.assign(api, {
    applyProjectInstanceRestoreState,
    applyRestoredWindowState,
    applyWindowRect,
    beginWindowDragCapture,
    buildBornhuetterFergusonViewerUrl,
    buildCapeCodViewerUrl,
    buildBootstrapViewerUrl,
    buildStochasticConsolidationViewerUrl,
    buildBerquistShermanViewerUrl,
    buildDatasetViewerUrl,
    buildDfmViewerUrl,
    buildResultSelectionViewerUrl,
    buildProjectInstanceStateSnapshot,
    clampWindowRect,
    closeDatasetWindow,
    closeTemporaryDatasetWindows,
    createFloatingContentWindow,
    findWindowByInstance,
    findWindowByMessageSource,
    focusProjectInstancePage,
    getActiveDatasetWindow,
    getActiveDfmWindow,
    getDatasetWindowKey,
    getDfmWindowKey,
    getCapeCodWindowKey,
    getBootstrapWindowKey,
    getStochasticConsolidationWindowKey,
    getBerquistShermanWindowKey,
    getFrameRect,
    getMaximizedWindowRect,
    getNextDatasetWindowRect,
    getPointerRestoreRect,
    getProjectInstanceWindowSnapshot,
    getProjectInstanceAssistantContextSummary,
    getWindowBounds,
    getWindowFullTitle,
    getWindowHorizontalLimits,
    getWindowIframe,
    getWindowMethodType,
    getWindowPath,
    getWindowShortTitle,
    getWindowTopLimit,
    hasDirtyDfmWindow,
    isBornhuetterFergusonWindow,
    isCapeCodWindow,
    isBootstrapWindow,
    isStochasticConsolidationWindow,
    isBerquistShermanWindow,
    isDatasetWindowMaximized,
    isDfmWindow,
    isResultSelectionWindow,
    isWindowOnSelectedPath,
    postMessageToDatasetWindows,
    lockDatasetViewerInputs,
    maximizeDatasetWindow,
    notifyActiveDfmWindowState,
    notifyProjectInstanceDirtyState,
    notifyProjectInstanceStateChanged,
    openDatasetWindow,
    openNewDatasetDraftWindow,
    openBornhuetterFergusonWindow,
    openCapeCodWindow,
    openBootstrapWindow,
    openStochasticConsolidationWindow,
    openBerquistShermanWindow,
    openDfmWindow,
    openResultSelectionWindow,
    raiseWindow,
    rememberDatasetWindowSize,
    resizeRectFromCorner,
    restoreDatasetWindow,
    setWindowDirtyState,
    setWindowRunState,
    startMove,
    startResize,
    syncDfmWindowIdentity,
    syncBerquistShermanWindowIdentity,
    syncDatasetWindowChrome,
    syncMaximizedDatasetWindows,
    toggleDatasetWindowMaximized,
    updateDatasetWindowMaximizeControl,
    updateDatasetWindowTitle,
    wireDatasetViewerWindowShortcuts
  });
}
