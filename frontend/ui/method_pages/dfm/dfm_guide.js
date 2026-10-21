import { attachArcrhoTooltip, ensureArcrhoTooltipStyles } from "/ui/shared/components/tooltip/tooltip.js?v=20260715a";
import { DFM_GUIDE } from "./dfm_guide_content.js?v=20261021a";

export function initDfmGuide() {
  const toggle = document.getElementById("dfmGuideToggle");
  if (!toggle || toggle.dataset.guideReady) return;
  toggle.dataset.guideReady = "true";
  const tabs = document.querySelector(".dfmTabBar");
  ensureArcrhoTooltipStyles();
  attachArcrhoTooltip(toggle, "Toggle guide mode. Hover outlined components or focus a numbered marker. Esc exits.");
  const layer = document.createElement("div");
  layer.id = "dfmGuide";
  layer.className = "dfmGuideLayer";
  layer.hidden = true;
  layer.setAttribute("role", "group");
  layer.setAttribute("aria-label", "DFM component help");
  const tooltip = document.createElement("div");
  tooltip.id = "dfmGuideTooltip";
  tooltip.className = "dfmGuideTooltip arcrho-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.append(layer, tooltip);
  let enabled = false;
  let page = null;
  let entries = [];
  let active = null;
  let hideTimer = 0;
  let layoutFrame = 0;

  function hide() {
    clearTimeout(hideTimer);
    active = null;
    tooltip.hidden = true;
    tooltip.classList.remove("is-open");
  }
  function show(entry, target) {
    clearTimeout(hideTimer);
    active = { entry, target };
    const [, title, brief, details] = entry.copy;
    const heading = document.createElement("strong");
    heading.textContent = title;
    const summary = document.createElement("p");
    summary.className = "dfmGuideBrief";
    summary.textContent = brief;
    const list = document.createElement("ul");
    list.className = "dfmGuideDetail";
    for (const text of details) {
      const item = document.createElement("li");
      item.textContent = text;
      list.append(item);
    }
    tooltip.replaceChildren(heading, summary, list);
    tooltip.hidden = false;
    tooltip.classList.add("is-open");
    positionTooltip();
  }
  function positionTooltip() {
    if (!active) return;
    const rect = visibleRect(active.target);
    if (!rect) { hide(); return; }
    const box = tooltip.getBoundingClientRect();
    const viewport = document.body.getBoundingClientRect();
    let left = rect.right + 6;
    let top = rect.top;
    if (left + box.width > viewport.right - 8) left = rect.left - box.width - 6;
    if (left < 8) {
      left = rect.left;
      top = rect.bottom + 6;
      if (top + box.height > viewport.bottom - 8) top = rect.top - box.height - 6;
    }
    if (rect.top < tabs.getBoundingClientRect().bottom) {
      left = rect.left;
      top = tabs.getBoundingClientRect().bottom + 6;
    }
    left = Math.max(8, Math.min(left, viewport.right - box.width - 8));
    top = Math.max(8, Math.min(top, viewport.bottom - box.height - 8));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }
  // Intersect scroll containers so hidden/offscreen components have no marker.
  function visibleRect(target) {
    if (!target.isConnected || !target.getClientRects().length) return null;
    const rect = target.getBoundingClientRect();
    let { left, right, top, bottom } = rect;
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      const style = getComputedStyle(parent);
      const bounds = parent.getBoundingClientRect();
      if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) {
        left = Math.max(left, bounds.left); right = Math.min(right, bounds.right);
      }
      if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) {
        top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom);
      }
    }
    return right > left && bottom > top ? { left, right, top, bottom } : null;
  }
  function layout() {
    layoutFrame = 0;
    if (!enabled) return;
    const placed = [];
    for (const entry of entries) {
      const target = entry.targets.find(target => visibleRect(target));
      const rect = target && visibleRect(target);
      entry.marker.hidden = !rect;
      entry.target = target;
      if (!rect) continue;
      const size = entry.marker.offsetWidth;
      const left = Math.max(rect.left, rect.right - size);
      let top = rect.top;
      while (placed.some(p => Math.abs(p.left - left) < size && Math.abs(p.top - top) < size)) top += size;
      entry.marker.style.left = `${left}px`;
      entry.marker.style.top = `${top}px`;
      placed.push({ left, top });
    }
    positionTooltip();
  }
  function scheduleLayout() {
    if (enabled && !layoutFrame) layoutFrame = requestAnimationFrame(layout);
  }
  function clearTargets() {
    for (const entry of entries) for (const target of entry.targets) target.classList.remove("dfmGuideTarget");
    entries = [];
    layer.replaceChildren();
    hide();
  }
  function refresh() {
    if (!enabled) return;
    contentObserver.disconnect();
    resize.disconnect();
    clearTargets();
    const tab = tabs.querySelector(".dfmTab.active")?.dataset.page;
    page = document.querySelector(`div[data-page="${tab}"][id]`);
    if (!page) return;
    const copies = [...(DFM_GUIDE[tab] || []), [".dfmTab.active", "Tab Windows", "Right-click a tab to pop it out or dock it.", ["Use separate tab windows to compare views."]]];
    for (const copy of copies) {
      const targets = [...document.querySelectorAll(copy[0])].filter(target => page.contains(target) || target.closest(".dfmTabBar"));
      if (!targets.length) continue;
      for (const target of targets) { target.classList.add("dfmGuideTarget"); resize.observe(target); }
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "dfmGuideMarker";
      marker.textContent = String(entries.length + 1);
      marker.setAttribute("aria-label", `Help: ${copy[1]}`);
      marker.setAttribute("aria-describedby", tooltip.id);
      const entry = { copy, targets, marker, target: null };
      const inspect = () => { if (entry.target) show(entry, marker); };
      marker.addEventListener("mouseenter", inspect);
      marker.addEventListener("focus", inspect);
      marker.addEventListener("click", inspect);
      entries.push(entry);
      layer.append(marker);
    }
    contentObserver.observe(page, { childList: true, subtree: true });
    resize.observe(document.body);
    layout();
  }
  const contentObserver = new MutationObserver(refresh);
  const resize = new ResizeObserver(scheduleLayout);
  const tabObserver = new MutationObserver(() => {
    const tab = tabs.querySelector(".dfmTab.active")?.dataset.page;
    if (enabled && tab !== page?.dataset.page) refresh();
  });
  tabObserver.observe(tabs, { attributes: true, attributeFilter: ["class"], subtree: true });
  function setEnabled(value) {
    enabled = value;
    toggle.setAttribute("aria-pressed", String(value));
    layer.hidden = !value;
    contentObserver.disconnect();
    resize.disconnect();
    clearTargets();
    if (value) refresh();
  }
  toggle.addEventListener("click", () => setEnabled(!enabled));
  function inspect(event) {
    if (!enabled || layer.contains(event.target)) return;
    const entry = entries.find(entry => entry.targets.some(target => target.contains(event.target)));
    if (entry) show(entry, event.target.closest("td, th, input, select, button") || entry.targets.find(target => target.contains(event.target)));
  }
  document.addEventListener("pointerover", inspect);
  document.addEventListener("focusin", inspect);
  for (const type of ["pointerout", "focusout"]) document.addEventListener(type, event => {
    if (!active) return;
    const next = event.relatedTarget;
    if (next && (active.target.contains(next) || active.entry.marker.contains(next))) return;
    hideTimer = setTimeout(hide, 150);
  });
  // Keep help from covering a real click or context menu.
  document.addEventListener("pointerdown", event => { if (!layer.contains(event.target)) hide(); }, true);
  document.addEventListener("keydown", event => {
    if (!enabled || event.key !== "Escape" || event.defaultPrevented) return;
    const guideFocused = layer.contains(document.activeElement);
    setEnabled(false);
    if (guideFocused) toggle.focus();
  });
  document.addEventListener("scroll", scheduleLayout, true);
  window.addEventListener("pagehide", () => {
    setEnabled(false);
    tabObserver.disconnect();
    cancelAnimationFrame(layoutFrame);
  }, { once: true });
}
