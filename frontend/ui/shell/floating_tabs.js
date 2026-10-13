export const FLOAT_MIN_W = 360;
export const FLOAT_MIN_H = 240;
export const FLOAT_DEFAULT_RATIO = 0.8;
export const FLOAT_TITLEBAR_H = 31;
export const FLOAT_TITLEBAR_REACHABLE_H = 36;
export const FLOAT_VERTICAL_THRESHOLD_PX = 30;
export const FLOAT_VERTICAL_RETURN_THRESHOLD_PX = 15;
export const FLOAT_HORIZONTAL_OFFSCREEN_RATIO = 0.8;
export const FLOAT_SNAP_EDGE_THRESHOLD_PX = 18;
export const FLOAT_RESTORE_DRAG_THRESHOLD_PX = 8;
export const FLOAT_DEFAULT_ASPECT_W = 16;
export const FLOAT_DEFAULT_ASPECT_H = 10;
export const FLOAT_DOCK_TARGET_EXIT_PAD_PX = 8;
export const FLOAT_DOCK_TARGET_TRIGGER_OFFSET_PX = Math.round(FLOAT_TITLEBAR_H / 2);
const SCRIPTING_PATH_TOOLTIP_DELAY_MS = 2000;

export function isFloatingTab(tab) {
  return !!tab && tab.layout === "floating" && tab.id !== "home";
}

export function normalizeFloatRect(raw) {
  if (!raw || typeof raw !== "object") return null;
  const x = Number(raw.x);
  const y = Number(raw.y);
  const width = Number(raw.width);
  const height = Number(raw.height);
  if (![x, y, width, height].every(Number.isFinite)) return null;
  return {
    x,
    y,
    width: Math.max(FLOAT_MIN_W, width),
    height: Math.max(FLOAT_MIN_H, height),
  };
}

export function createFloatingTabsController(deps) {
  const {
    closeTab,
    dockTab,
    ensureIframe,
    getContentElement,
    getFloatingHost,
    getState,
    hideGlobalTooltip,
    openTabContextMenu,
    render,
    saveState,
    setActive,
    showGlobalTooltip,
  } = deps;

  let floatPreviewEl = null;
  let snapPreviewEl = null;
  let dockPlaceholderEl = null;
  let dockPreviewBeforeId = null;
  let lastUserFloatSize = null;
  const dockingTabIds = new Set();

  function getContentRect() {
    const content = getContentElement();
    return content ? content.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  }

  function clampFloatRect(rect) {
    const hostRect = getContentRect();
    const hostW = Math.max(FLOAT_MIN_W, hostRect.width || window.innerWidth || FLOAT_MIN_W);
    const hostH = Math.max(FLOAT_MIN_H, hostRect.height || window.innerHeight || FLOAT_MIN_H);
    const width = Math.max(FLOAT_MIN_W, Math.min(Number(rect?.width) || FLOAT_MIN_W, hostW));
    const height = Math.max(FLOAT_MIN_H, Math.min(Number(rect?.height) || FLOAT_MIN_H, hostH));
    const horizontalOffscreen = Math.round(width * FLOAT_HORIZONTAL_OFFSCREEN_RATIO);
    const minX = -horizontalOffscreen;
    const maxX = Math.max(0, hostW - width + horizontalOffscreen);
    const maxY = Math.max(0, hostH - FLOAT_TITLEBAR_REACHABLE_H);
    const x = Math.max(minX, Math.min(Number(rect?.x) || 0, maxX));
    const y = Math.max(0, Math.min(Number(rect?.y) || 0, maxY));
    return { x, y, width, height };
  }

  function defaultFloatRectFromPointer(clientX, clientY) {
    const hostRect = getContentRect();
    const hostW = Math.max(FLOAT_MIN_W, hostRect.width || window.innerWidth || FLOAT_MIN_W);
    const hostH = Math.max(FLOAT_MIN_H, hostRect.height || window.innerHeight || FLOAT_MIN_H);
    const maxW = Math.max(FLOAT_MIN_W, Math.round(hostW * FLOAT_DEFAULT_RATIO));
    const maxH = Math.max(FLOAT_MIN_H, Math.round(hostH * FLOAT_DEFAULT_RATIO));
    let width;
    let height;
    if (lastUserFloatSize) {
      width = Math.max(FLOAT_MIN_W, Math.min(Number(lastUserFloatSize.width) || maxW, hostW));
      height = Math.max(FLOAT_MIN_H, Math.min(Number(lastUserFloatSize.height) || maxH, hostH));
    } else {
      width = maxW;
      height = Math.round(width * FLOAT_DEFAULT_ASPECT_H / FLOAT_DEFAULT_ASPECT_W);
      if (height > maxH) {
        height = maxH;
        width = Math.round(height * FLOAT_DEFAULT_ASPECT_W / FLOAT_DEFAULT_ASPECT_H);
      }
      width = Math.max(FLOAT_MIN_W, width);
      height = Math.max(FLOAT_MIN_H, Math.round(width * FLOAT_DEFAULT_ASPECT_H / FLOAT_DEFAULT_ASPECT_W));
      if (height > hostH) {
        height = Math.max(FLOAT_MIN_H, hostH);
        width = Math.max(FLOAT_MIN_W, Math.round(height * FLOAT_DEFAULT_ASPECT_W / FLOAT_DEFAULT_ASPECT_H));
      }
    }
    const x = (clientX - hostRect.left) - width / 2;
    const y = (clientY - hostRect.top) - 18;
    return clampFloatRect({ x, y, width, height });
  }

  function getScriptingFilePath(tab) {
    if (!tab || tab.type !== "scripting") return "";
    return String(tab.scPath || tab.scOpenPath || "").trim();
  }

  function createFloatingTabPathTooltipHandlers(tab) {
    const filePath = getScriptingFilePath(tab);
    let hoverTimer = null;
    let visible = false;
    let hoverPointer = { x: 0, y: 0 };

    const clear = () => {
      if (hoverTimer) window.clearTimeout(hoverTimer);
      hoverTimer = null;
    };
    const hide = () => {
      clear();
      visible = false;
      hideGlobalTooltip?.();
    };
    const schedule = (event) => {
      if (!filePath) return;
      hoverPointer = { x: event.clientX, y: event.clientY };
      if (hoverTimer || visible) return;
      hoverTimer = window.setTimeout(() => {
        hoverTimer = null;
        visible = true;
        showGlobalTooltip?.(filePath, hoverPointer.x + 12, hoverPointer.y + 18);
      }, SCRIPTING_PATH_TOOLTIP_DELAY_MS);
    };

    return { schedule, hide };
  }

  function rememberUserFloatSize(rect) {
    const normalized = normalizeFloatRect(rect);
    if (!normalized) return;
    const clamped = clampFloatRect({ x: 0, y: 0, width: normalized.width, height: normalized.height });
    lastUserFloatSize = {
      width: clamped.width,
      height: clamped.height,
    };
  }

  function ensureFloatPreview() {
    if (floatPreviewEl && floatPreviewEl.isConnected) return floatPreviewEl;
    const content = getContentElement();
    if (!content) return null;
    const el = document.createElement("div");
    el.id = "floatingTabPreview";
    content.appendChild(el);
    floatPreviewEl = el;
    return el;
  }

  function updateFloatPreview(clientX, clientY) {
    const el = ensureFloatPreview();
    if (!el) return;
    const r = defaultFloatRectFromPointer(clientX, clientY);
    el.style.left = `${Math.round(r.x)}px`;
    el.style.top = `${Math.round(r.y)}px`;
    el.style.width = `${Math.round(r.width)}px`;
    el.style.height = `${Math.round(r.height)}px`;
  }

  function removeFloatPreview() {
    if (floatPreviewEl && floatPreviewEl.parentNode) {
      floatPreviewEl.parentNode.removeChild(floatPreviewEl);
    }
    floatPreviewEl = null;
  }

  function getHorizontalSnapSide(clientX) {
    const hostRect = getContentRect();
    if (clientX <= hostRect.left + FLOAT_SNAP_EDGE_THRESHOLD_PX) return "left";
    if (clientX >= hostRect.right - FLOAT_SNAP_EDGE_THRESHOLD_PX) return "right";
    return null;
  }

  function getHorizontalSnapRect(side) {
    const hostRect = getContentRect();
    const hostW = Math.max(FLOAT_MIN_W, hostRect.width || window.innerWidth || FLOAT_MIN_W);
    const hostH = Math.max(FLOAT_MIN_H, hostRect.height || window.innerHeight || FLOAT_MIN_H);
    const width = Math.round(hostW / 2);
    return clampFloatRect({
      x: side === "right" ? hostW - width : 0,
      y: 0,
      width,
      height: hostH,
    });
  }

  function restorePreSnapRectForDrag(tab, currentRect, clientX, clientY) {
    const restoreRect = normalizeFloatRect(tab?.floatRestoreRect);
    if (!tab || !restoreRect) return currentRect;
    const hostRect = getContentRect();
    const pointerX = clientX - hostRect.left;
    const pointerY = clientY - hostRect.top;
    const currentWidth = Math.max(1, Number(currentRect?.width) || 1);
    const currentX = Number(currentRect?.x) || 0;
    const pointerRatioX = Math.max(0.15, Math.min(0.85, (pointerX - currentX) / currentWidth));
    const next = clampFloatRect({
      ...restoreRect,
      x: pointerX - restoreRect.width * pointerRatioX,
      y: pointerY - FLOAT_TITLEBAR_H / 2,
    });
    tab.floatRect = next;
    tab.floatRestoreRect = null;
    applyFloatingFrameRect(tab, next);
    saveState();
    return next;
  }

  function ensureSnapPreview() {
    if (snapPreviewEl && snapPreviewEl.isConnected) return snapPreviewEl;
    const content = getContentElement();
    if (!content) return null;
    const el = document.createElement("div");
    el.id = "floatingSnapPreview";
    content.appendChild(el);
    snapPreviewEl = el;
    return el;
  }

  function updateSnapPreview(side) {
    const el = ensureSnapPreview();
    if (!el) return;
    const r = getHorizontalSnapRect(side);
    el.style.left = `${Math.round(r.x)}px`;
    el.style.top = `${Math.round(r.y)}px`;
    el.style.width = `${Math.round(r.width)}px`;
    el.style.height = `${Math.round(r.height)}px`;
    requestAnimationFrame(() => el.classList.add("show"));
  }

  function removeSnapPreview() {
    if (snapPreviewEl) {
      snapPreviewEl.classList.remove("show");
      if (snapPreviewEl.parentNode) snapPreviewEl.parentNode.removeChild(snapPreviewEl);
    }
    snapPreviewEl = null;
  }

  function getDockTargetElement() {
    return document.getElementById("tabs");
  }

  function isDockTargetPointer(clientX, clientY) {
    const target = getDockTargetElement();
    if (!target) return false;
    const stripRect = target.closest(".topbar")?.getBoundingClientRect?.() || target.getBoundingClientRect();
    return (
      clientX >= stripRect.left &&
      clientX <= stripRect.right &&
      clientY <= stripRect.top + FLOAT_DOCK_TARGET_TRIGGER_OFFSET_PX &&
      clientY >= stripRect.top - Math.max(stripRect.height, FLOAT_TITLEBAR_H) - FLOAT_DOCK_TARGET_EXIT_PAD_PX
    );
  }

  function setDockTargetActive(active) {
    getDockTargetElement()?.classList.toggle("floatingDockTarget", !!active);
  }

  function removeDockOrderPreview() {
    if (dockPlaceholderEl?.parentNode) dockPlaceholderEl.parentNode.removeChild(dockPlaceholderEl);
    dockPlaceholderEl = null;
    dockPreviewBeforeId = null;
  }

  function ensureDockOrderPreview(tab) {
    if (dockPlaceholderEl?.isConnected) return dockPlaceholderEl;
    const el = document.createElement("div");
    el.className = "tab placeholder floatingDockPlaceholder";
    el.textContent = tab?.title || "Tab";
    dockPlaceholderEl = el;
    return el;
  }

  function updateDockOrderPreview(tab, clientX) {
    const host = getDockTargetElement();
    if (!host || !tab) return null;
    const placeholder = ensureDockOrderPreview(tab);
    const dockedTabEls = [...host.querySelectorAll('.tab[data-tab-id]')]
      .filter((el) => {
        const id = el.getAttribute("data-tab-id");
        return id && id !== "home" && id !== tab.id;
      });
    let beforeNode = null;
    for (const node of dockedTabEls) {
      const rect = node.getBoundingClientRect();
      if (clientX < rect.left + rect.width / 2) {
        beforeNode = node;
        break;
      }
    }
    if (beforeNode) host.insertBefore(placeholder, beforeNode);
    else host.appendChild(placeholder);
    dockPreviewBeforeId = beforeNode?.getAttribute("data-tab-id") || null;
    return dockPreviewBeforeId;
  }

  function applyDockOrderPreview(tabId) {
    const state = getState();
    const index = state.tabs.findIndex(t => t.id === tabId);
    if (index < 0) return;
    const [tab] = state.tabs.splice(index, 1);
    const beforeIndex = dockPreviewBeforeId ? state.tabs.findIndex(t => t.id === dockPreviewBeforeId) : -1;
    if (beforeIndex >= 0) {
      state.tabs.splice(beforeIndex, 0, tab);
      return;
    }
    let insertIndex = state.tabs.length;
    for (let i = 0; i < state.tabs.length; i++) {
      if (!isFloatingTab(state.tabs[i])) insertIndex = i + 1;
    }
    state.tabs.splice(insertIndex, 0, tab);
  }

  function runFloatIntroAnimation(tab, frame) {
    if (!tab?.floatAnimateIn || !frame) return;
    tab.floatAnimateIn = false;
    const nodes = [frame, tab.iframe].filter(Boolean);
    nodes.forEach((node) => {
      node.classList.remove("floatingTabAnimateIn");
      void node.offsetWidth;
      node.classList.add("floatingTabAnimateIn");
      window.setTimeout(() => node.classList.remove("floatingTabAnimateIn"), 220);
    });
  }

  function animateDockTab(tabId) {
    const state = getState();
    const tab = state.tabs.find(t => t.id === tabId);
    if (!tab || dockingTabIds.has(tabId)) return;
    const frame = getFloatingHost()?.querySelector?.(`.floatingTabWindow[data-tab-id="${CSS.escape(tabId)}"]`);
    if (!frame) {
      dockTab(tabId);
      return;
    }
    dockingTabIds.add(tabId);
    const nodes = [frame, tab.iframe].filter(Boolean);
    nodes.forEach((node) => {
      node.classList.remove("floatingTabAnimateDock");
      void node.offsetWidth;
      node.classList.add("floatingTabAnimateDock");
    });
    window.setTimeout(() => {
      dockingTabIds.delete(tabId);
      nodes.forEach((node) => node.classList.remove("floatingTabAnimateDock"));
      dockTab(tabId);
    }, window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? 0 : 150);
  }

  function getTopFloatingTab(excludeId = null) {
    const state = getState();
    return state.tabs
      .filter(t => isFloatingTab(t) && t.id !== excludeId)
      .sort((a, b) => (Number(b.floatZ) || 0) - (Number(a.floatZ) || 0))[0] || null;
  }

  function getDockedFocusFallback(excludeId = null) {
    const state = getState();
    const lastDocked = state.tabs.find(t => t.id === state.lastDockedActiveId && t.id !== excludeId && !isFloatingTab(t));
    if (lastDocked) return lastDocked.id;
    return state.tabs.find(t => t.id !== excludeId && !isFloatingTab(t))?.id || "home";
  }

  function commitDockTabToStripEndWithoutFocus(tabId) {
    const state = getState();
    const index = state.tabs.findIndex(t => t.id === tabId);
    if (index < 0) return;
    const topFloating = getTopFloatingTab(tabId);
    const fallbackDockedId = getDockedFocusFallback(tabId);
    const [tab] = state.tabs.splice(index, 1);
    tab.layout = "docked";
    tab.floatRect = null;
    tab.floatZ = 0;
    tab.floatMinimized = false;
    tab.floatRestoreRect = null;

    let insertIndex = state.tabs.length;
    for (let i = 0; i < state.tabs.length; i++) {
      if (!isFloatingTab(state.tabs[i])) insertIndex = i + 1;
    }
    state.tabs.splice(insertIndex, 0, tab);
    state.lastDockedActiveId = fallbackDockedId;
    state.activeId = topFloating?.id || fallbackDockedId;
    render?.();
    saveState();
  }

  function dockTabToStripEndWithoutFocus(tabId) {
    const state = getState();
    const tab = state.tabs.find(t => t.id === tabId);
    if (!tab || dockingTabIds.has(tabId)) return;
    const frame = getFloatingHost()?.querySelector?.(`.floatingTabWindow[data-tab-id="${CSS.escape(tabId)}"]`);
    if (!frame) {
      commitDockTabToStripEndWithoutFocus(tabId);
      return;
    }
    dockingTabIds.add(tabId);
    const nodes = [frame, tab.iframe].filter(Boolean);
    nodes.forEach((node) => {
      node.classList.remove("floatingTabAnimateDock");
      void node.offsetWidth;
      node.classList.add("floatingTabAnimateDock");
    });
    window.setTimeout(() => {
      dockingTabIds.delete(tabId);
      nodes.forEach((node) => node.classList.remove("floatingTabAnimateDock"));
      commitDockTabToStripEndWithoutFocus(tabId);
    }, window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? 0 : 150);
  }

  function getFloatingLayerBase(tab) {
    return 100 + (Number(tab?.floatZ) || 0) * 10;
  }

  function applyFloatingFrameRect(tab, rect) {
    if (!tab) return;
    const minimized = !!tab.floatMinimized;
    const layerBase = getFloatingLayerBase(tab);
    const floatingHost = getFloatingHost();
    const frame = floatingHost?.querySelector?.(`.floatingTabWindow[data-tab-id="${CSS.escape(tab.id)}"]`);
    if (frame) {
      frame.style.left = `${Math.round(rect.x)}px`;
      frame.style.top = `${Math.round(rect.y)}px`;
      frame.style.width = `${Math.round(rect.width)}px`;
      frame.style.height = `${Math.round(minimized ? FLOAT_TITLEBAR_H + 2 : rect.height)}px`;
      frame.style.zIndex = String(layerBase + 1);
    }
    if (tab.iframe) {
      tab.iframe.classList.add("floatingTabIframe");
      tab.iframe.style.position = "absolute";
      tab.iframe.style.display = minimized ? "none" : "block";
      tab.iframe.style.left = `${Math.round(rect.x)}px`;
      tab.iframe.style.top = `${Math.round(rect.y + FLOAT_TITLEBAR_H)}px`;
      tab.iframe.style.width = `${Math.round(rect.width)}px`;
      tab.iframe.style.height = `${Math.max(0, Math.round((minimized ? FLOAT_TITLEBAR_H : rect.height) - FLOAT_TITLEBAR_H))}px`;
      tab.iframe.style.zIndex = String(layerBase);
      tab.iframe.style.background = "#fff";
      tab.iframe.style.pointerEvents = minimized ? "none" : "auto";
    }
  }

  function applyDockedIframeLayout(tab) {
    if (!tab?.iframe) return;
    tab.iframe.classList.remove("floatingTabIframe");
    tab.iframe.style.position = "absolute";
    tab.iframe.style.left = "0";
    tab.iframe.style.top = "0";
    tab.iframe.style.width = "100%";
    tab.iframe.style.height = "100%";
    tab.iframe.style.zIndex = "1";
    tab.iframe.style.pointerEvents = "auto";
  }

  function beginFloatingPointerInteraction(target, pointerId) {
    try { target?.setPointerCapture?.(pointerId); } catch {}
    try { document.body.classList.add("floatingTabDragActive"); } catch {}
  }

  function endFloatingPointerInteraction(target, pointerId) {
    try { target?.releasePointerCapture?.(pointerId); } catch {}
    try { document.body.classList.remove("floatingTabDragActive"); } catch {}
  }

  function startFloatingMove(tabId, e) {
    if (e.button !== 0) return;
    const state = getState();
    const tab = state.tabs.find(t => t.id === tabId);
    if (!tab) return;
    const pointerTarget = e.currentTarget;
    const pointerId = e.pointerId;
    const startX = e.clientX;
    const startY = e.clientY;
    let startRect = clampFloatRect(tab.floatRect || defaultFloatRectFromPointer(e.clientX, e.clientY));
    let didRestorePreSnapRect = false;
    let snapSide = null;
    let dockTargetActive = false;
    beginFloatingPointerInteraction(pointerTarget, pointerId);

    const onMove = (ev) => {
      const moved = Math.hypot(ev.clientX - startX, ev.clientY - startY);
      if (!didRestorePreSnapRect && moved >= FLOAT_RESTORE_DRAG_THRESHOLD_PX) {
        startRect = restorePreSnapRectForDrag(tab, startRect, ev.clientX, ev.clientY);
        didRestorePreSnapRect = true;
      }
      dockTargetActive = isDockTargetPointer(ev.clientX, ev.clientY);
      snapSide = dockTargetActive ? null : getHorizontalSnapSide(ev.clientX);
      const next = clampFloatRect({
        ...startRect,
        x: startRect.x + (ev.clientX - startX),
        y: startRect.y + (ev.clientY - startY),
      });
      tab.floatRect = next;
      applyFloatingFrameRect(tab, next);
      setDockTargetActive(dockTargetActive);
      if (dockTargetActive) {
        removeSnapPreview();
        updateDockOrderPreview(tab, ev.clientX);
      }
      else if (snapSide) updateSnapPreview(snapSide);
      else {
        removeSnapPreview();
        removeDockOrderPreview();
      }
    };

    const finish = (ev) => {
      document.removeEventListener("pointermove", onMove, true);
      document.removeEventListener("pointerup", finish, true);
      document.removeEventListener("pointercancel", finish, true);
      endFloatingPointerInteraction(pointerTarget, pointerId);
      setDockTargetActive(false);
      if (dockTargetActive && ev?.type !== "pointercancel") {
        removeSnapPreview();
        applyDockOrderPreview(tabId);
        removeDockOrderPreview();
        animateDockTab(tabId);
        return;
      }
      removeDockOrderPreview();
      if (snapSide && ev?.type !== "pointercancel") {
        tab.floatRestoreRect = normalizeFloatRect(tab.floatRestoreRect) || startRect;
        tab.floatRect = getHorizontalSnapRect(snapSide);
        applyFloatingFrameRect(tab, tab.floatRect);
      } else {
        tab.floatRect = clampFloatRect(tab.floatRect || startRect);
      }
      removeSnapPreview();
      saveState();
    };

    document.addEventListener("pointermove", onMove, true);
    document.addEventListener("pointerup", finish, true);
    document.addEventListener("pointercancel", finish, true);
    e.preventDefault();
  }

  function startFloatingResize(tabId, e, corner = "se") {
    if (e.button !== 0) return;
    const state = getState();
    const tab = state.tabs.find(t => t.id === tabId);
    if (!tab || tab.floatMinimized) return;
    const pointerTarget = e.currentTarget;
    const pointerId = e.pointerId;
    const startX = e.clientX;
    const startY = e.clientY;
    const startRect = clampFloatRect(tab.floatRect || defaultFloatRectFromPointer(e.clientX, e.clientY));
    tab.floatRestoreRect = null;
    beginFloatingPointerInteraction(pointerTarget, pointerId);

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      let next = { ...startRect };
      if (corner.includes("e")) next.width = startRect.width + dx;
      if (corner.includes("s")) next.height = startRect.height + dy;
      if (corner.includes("w")) {
        next.x = startRect.x + dx;
        next.width = startRect.width - dx;
      }
      if (corner.includes("n")) {
        next.y = startRect.y + dy;
        next.height = startRect.height - dy;
      }
      if (next.width < FLOAT_MIN_W && corner.includes("w")) {
        next.x = startRect.x + startRect.width - FLOAT_MIN_W;
        next.width = FLOAT_MIN_W;
      }
      if (next.height < FLOAT_MIN_H && corner.includes("n")) {
        next.y = startRect.y + startRect.height - FLOAT_MIN_H;
        next.height = FLOAT_MIN_H;
      }
      next = clampFloatRect(next);
      tab.floatRect = next;
      applyFloatingFrameRect(tab, next);
    };

    const finish = (ev) => {
      document.removeEventListener("pointermove", onMove, true);
      document.removeEventListener("pointerup", finish, true);
      document.removeEventListener("pointercancel", finish, true);
      endFloatingPointerInteraction(pointerTarget, pointerId);
      tab.floatRect = clampFloatRect(tab.floatRect || startRect);
      if (ev?.type !== "pointercancel") rememberUserFloatSize(tab.floatRect);
      saveState();
    };

    document.addEventListener("pointermove", onMove, true);
    document.addEventListener("pointerup", finish, true);
    document.addEventListener("pointercancel", finish, true);
    e.preventDefault();
  }

  function renderFloatingWindows() {
    const floatingHost = getFloatingHost();
    if (!floatingHost) return;
    const state = getState();
    const floatingIds = new Set(state.tabs.filter(isFloatingTab).map(t => t.id));
    floatingHost.querySelectorAll(".floatingTabWindow").forEach((frame) => {
      const id = frame.getAttribute("data-tab-id");
      if (!floatingIds.has(id)) frame.remove();
    });

    for (const tab of state.tabs) {
      if (!isFloatingTab(tab)) continue;
      ensureIframe(tab);
      if (tab.iframe && tab.iframe.dataset.floatingFocusWired !== "1") {
        tab.iframe.dataset.floatingFocusWired = "1";
        tab.iframe.addEventListener("pointerdown", () => {
          if (isFloatingTab(tab)) setActive(tab.id);
        });
      }
      tab.floatRect = clampFloatRect(tab.floatRect || defaultFloatRectFromPointer(window.innerWidth / 2, window.innerHeight / 2));
      if (!tab.floatZ) tab.floatZ = state.nextFloatZ++;

      let frame = floatingHost.querySelector(`.floatingTabWindow[data-tab-id="${CSS.escape(tab.id)}"]`);
      if (!frame) {
        frame = document.createElement("section");
        frame.className = "floatingTabWindow";
        frame.setAttribute("data-tab-id", tab.id);
        frame.innerHTML = `
          <header class="floatingTabTitlebar">
            <span class="floatingTabTitle"></span>
            <span class="floatingTabDirty" aria-hidden="true"></span>
            <span class="floatingTabControls">
              <button class="titlebarBtn floatingTabButton" data-action="minimize" type="button" title="Dock to tab strip" aria-label="Dock to tab strip">
                <svg class="titlebarIcon" viewBox="0 0 10 10" aria-hidden="true">
                  <line x1="2" y1="7" x2="8" y2="7"></line>
                </svg>
              </button>
              <button class="titlebarBtn floatingTabButton" data-action="dock" type="button" title="Dock" aria-label="Dock">
                <svg class="titlebarIcon" viewBox="0 0 10 10" aria-hidden="true">
                  <rect x="2" y="2" width="6" height="6" rx="0.6"></rect>
                </svg>
              </button>
              <button class="titlebarBtn floatingTabButton" data-action="close" type="button" title="Close" aria-label="Close">
                <svg class="titlebarIcon" viewBox="0 0 10 10" aria-hidden="true">
                  <line x1="2" y1="2" x2="8" y2="8"></line>
                  <line x1="8" y1="2" x2="2" y2="8"></line>
                </svg>
              </button>
            </span>
          </header>
          <div class="floatingTabBody"></div>
          <div class="floatingTabResizeHandle floatingTabResizeNw" data-corner="nw" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeEdge floatingTabResizeN" data-corner="n" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeNe" data-corner="ne" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeEdge floatingTabResizeE" data-corner="e" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeSw" data-corner="sw" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeEdge floatingTabResizeS" data-corner="s" title="Resize"></div>
          <div class="floatingTabResizeHandle floatingTabResizeSe" data-corner="se" title="Resize"><span class="resizeIcon"></span></div>
          <div class="floatingTabResizeHandle floatingTabResizeEdge floatingTabResizeW" data-corner="w" title="Resize"></div>
        `;
        frame.addEventListener("pointerdown", () => setActive(tab.id));
        const titlebar = frame.querySelector(".floatingTabTitlebar");
        const pathTooltip = createFloatingTabPathTooltipHandlers(tab);
        titlebar?.addEventListener("pointerdown", (e) => {
          if (e.target?.closest?.("button")) return;
          pathTooltip?.hide?.();
          e.stopPropagation();
          setActive(tab.id);
          startFloatingMove(tab.id, e);
        });
        titlebar?.addEventListener("pointerenter", (e) => pathTooltip?.schedule?.(e));
        titlebar?.addEventListener("pointermove", () => pathTooltip?.hide?.());
        titlebar?.addEventListener("pointerleave", () => pathTooltip?.hide?.());
        titlebar?.addEventListener("contextmenu", (e) => {
          if (e.target?.closest?.("button")) return;
          e.preventDefault();
          e.stopPropagation();
          pathTooltip?.hide?.();
          setActive(tab.id);
          openTabContextMenu?.(tab.id, e.clientX, e.clientY);
        });
        titlebar?.addEventListener("dblclick", (e) => {
          if (e.target?.closest?.("button")) return;
          animateDockTab(tab.id);
        });
        frame.querySelectorAll(".floatingTabButton").forEach((button) => {
          button.addEventListener("pointerdown", (e) => e.stopPropagation());
        });
        frame.querySelector('[data-action="minimize"]')?.addEventListener("click", (e) => {
          e.stopPropagation();
          dockTabToStripEndWithoutFocus(tab.id);
        });
        frame.querySelector('[data-action="dock"]')?.addEventListener("click", (e) => {
          e.stopPropagation();
          animateDockTab(tab.id);
        });
        frame.querySelector('[data-action="close"]')?.addEventListener("click", (e) => {
          e.stopPropagation();
          closeTab(tab.id);
        });
        frame.querySelectorAll(".floatingTabResizeHandle").forEach((handle) => handle.addEventListener("pointerdown", (e) => {
          e.stopPropagation();
          setActive(tab.id);
          startFloatingResize(tab.id, e, handle.getAttribute("data-corner") || "se");
        }));
        floatingHost.appendChild(frame);
      }

      frame.classList.toggle("active", tab.id === state.activeId);
      frame.classList.toggle("minimized", !!tab.floatMinimized);
      applyFloatingFrameRect(tab, tab.floatRect);
      const title = frame.querySelector(".floatingTabTitle");
      if (title) title.textContent = tab.title || "Untitled";
      const dirty = frame.querySelector(".floatingTabDirty");
      if (dirty) dirty.classList.toggle("show", !!tab.isDirty);
      const minimizeButton = frame.querySelector('[data-action="minimize"]');
      if (minimizeButton) {
        minimizeButton.title = "Dock to tab strip";
        minimizeButton.setAttribute("aria-label", "Dock to tab strip");
      }
      runFloatIntroAnimation(tab, frame);
    }
  }

  function clampFloatingTabsToContent() {
    const state = getState();
    let changed = false;
    for (const tab of state.tabs) {
      if (!isFloatingTab(tab)) continue;
      const next = clampFloatRect(tab.floatRect || defaultFloatRectFromPointer(window.innerWidth / 2, window.innerHeight / 2));
      const prev = tab.floatRect || {};
      if (prev.x !== next.x || prev.y !== next.y || prev.width !== next.width || prev.height !== next.height) {
        tab.floatRect = next;
        changed = true;
      }
    }
    if (changed) {
      renderFloatingWindows();
      saveState();
    }
  }

  return {
    applyDockedIframeLayout,
    clampFloatRect,
    clampFloatingTabsToContent,
    defaultFloatRectFromPointer,
    animateDockTab,
    removeFloatPreview,
    renderFloatingWindows,
    updateFloatPreview,
  };
}
