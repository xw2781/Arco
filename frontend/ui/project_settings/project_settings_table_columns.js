/**
 * Project Settings - Shared table column sizing
 *
 * Owns the explicit-width column model used by every Project Settings table:
 * admin-configured default widths, measurement, auto-fit, drag resizing, and
 * the scrollbar-activity affordance on scroll hosts. A user's dragged widths
 * and collapsed groups are saved to the project's user preference file under
 * projectSettings.tables.<tableId>, the same place the admin defaults are read.
 */

import { scheduleProjectUserPreferencesSave } from "/ui/shared/services/project_user_preferences.js?v=20260816a";

// Live widths per table id, so re-rendering a table keeps the user's sizing.
const tableColumnWidthsById = new Map();
// Reset-to-default target used by the resizer double-click.
const tableDefaultColumnWidthsById = new Map();
// Widths supplied by the server-side preference JSON, keyed by normalized label.
const configuredTableColumnWidthsById = new Map();
// Collapsed group keys per table id, from the preference JSON.
const collapsedGroupsById = new Map();
// The project whose preference file the tables read from and save to.
let preferencesProjectName = "";

export function wireProjectSettingsTableScrollbarActivity(scrollHost) {
  if (!scrollHost || scrollHost.dataset.scrollbarActivityWired === "1") return;
  scrollHost.dataset.scrollbarActivityWired = "1";
  let idleTimer = 0;

  scrollHost.addEventListener("scroll", () => {
    scrollHost.classList.add("isScrolling");
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => scrollHost.classList.remove("isScrolling"), 550);
  }, { passive: true });

  scrollHost.addEventListener("pointermove", (event) => {
    const rect = scrollHost.getBoundingClientRect();
    const verticalScrollbarWidth = Math.max(0, scrollHost.offsetWidth - scrollHost.clientWidth);
    const horizontalScrollbarHeight = Math.max(0, scrollHost.offsetHeight - scrollHost.clientHeight);
    const overVerticalLane = scrollHost.scrollHeight > scrollHost.clientHeight
      && verticalScrollbarWidth > 0
      && event.clientX >= rect.right - Math.max(verticalScrollbarWidth, 16);
    const overHorizontalLane = scrollHost.scrollWidth > scrollHost.clientWidth
      && horizontalScrollbarHeight > 0
      && event.clientY >= rect.bottom - Math.max(horizontalScrollbarHeight, 16);
    scrollHost.classList.toggle("isScrollbarHover", overVerticalLane || overHorizontalLane);
  }, { passive: true });

  scrollHost.addEventListener("pointerleave", () => {
    scrollHost.classList.remove("isScrollbarHover");
  }, { passive: true });
}

export function normalizeTableColumnPreferenceKey(value) {
  return String(value || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
}

export function applyProjectSettingsTablePreferences(preferences, projectName = "") {
  preferencesProjectName = String(projectName || "").trim();
  configuredTableColumnWidthsById.clear();
  tableColumnWidthsById.clear();
  tableDefaultColumnWidthsById.clear();
  collapsedGroupsById.clear();

  const tables = preferences?.projectSettings?.tables;
  if (!tables || typeof tables !== "object" || Array.isArray(tables)) return;
  Object.entries(tables).forEach(([tableId, tablePreferences]) => {
    const collapsed = tablePreferences?.collapsedGroups;
    if (Array.isArray(collapsed)) collapsedGroupsById.set(tableId, new Set(collapsed.map(String)));
    const widths = tablePreferences?.widths;
    if (!widths || typeof widths !== "object" || Array.isArray(widths)) return;
    const normalizedWidths = new Map();
    Object.entries(widths).forEach(([columnName, rawWidth]) => {
      const key = normalizeTableColumnPreferenceKey(columnName);
      const width = Math.round(Number(rawWidth));
      if (key && Number.isFinite(width) && width > 0) normalizedWidths.set(key, width);
    });
    if (normalizedWidths.size) configuredTableColumnWidthsById.set(tableId, normalizedWidths);
  });
}

function saveTablePreferences(tableId, patch) {
  if (!preferencesProjectName) return;
  scheduleProjectUserPreferencesSave(preferencesProjectName, {
    projectSettings: { tables: { [tableId]: patch } },
  }, 500);
}

/** Saves a table's column widths, given as { "Column label": width }. */
export function saveProjectSettingsTableColumnWidths(tableId, widthsByLabel) {
  saveTablePreferences(tableId, { widths: widthsByLabel });
}

/** The live set of collapsed group keys for a table; edit it, then save it. */
export function getProjectSettingsCollapsedGroups(tableId) {
  if (!collapsedGroupsById.has(tableId)) collapsedGroupsById.set(tableId, new Set());
  return collapsedGroupsById.get(tableId);
}

export function saveProjectSettingsCollapsedGroups(tableId) {
  saveTablePreferences(tableId, { collapsedGroups: Array.from(getProjectSettingsCollapsedGroups(tableId)) });
}

function getHeaderLabelText(th) {
  const label = th?.querySelector?.(".dt-col-label-text") || th?.querySelector?.(".table-col-label");
  return String(label?.textContent || th?.textContent || "").trim();
}

function saveTableColumnWidths(tableId, cols, ths, minWidths) {
  const widths = captureTableColumnWidths(cols, minWidths);
  tableColumnWidthsById.set(tableId, widths);
  const byLabel = {};
  Array.from(ths).forEach((th, index) => {
    const label = getHeaderLabelText(th);
    if (label && index < widths.length) byLabel[label] = widths[index];
  });
  saveProjectSettingsTableColumnWidths(tableId, byLabel);
}

/** Configured widths for a table, keyed by normalized column label, or null. */
export function getConfiguredTableColumnWidthMap(tableId) {
  const configured = configuredTableColumnWidthsById.get(tableId);
  if (!(configured instanceof Map) || !configured.size) return null;
  return configured;
}

function getConfiguredTableColumnWidths(tableId, cols, ths, minWidths) {
  const configured = getConfiguredTableColumnWidthMap(tableId);
  if (!configured) return null;
  let matched = false;
  const widths = Array.from(cols).map((col, index) => {
    const key = normalizeTableColumnPreferenceKey(getHeaderLabelText(ths[index]));
    const configuredWidth = Number(configured.get(key));
    const minimumWidth = Number(minWidths?.[index]) || 40;
    if (Number.isFinite(configuredWidth) && configuredWidth > 0) {
      matched = true;
      return Math.max(minimumWidth, Math.round(configuredWidth));
    }
    return getTableColumnWidth(col, minimumWidth);
  });
  return matched ? widths : null;
}

export function resizeCellTextarea(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = textarea.scrollHeight + "px";
}

function measureTextWidth(text, font) {
  const span = document.createElement("span");
  span.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font:" + font;
  span.textContent = text;
  document.body.appendChild(span);
  const w = span.offsetWidth;
  document.body.removeChild(span);
  return w;
}

function measureHeaderLabelWidth(labelEl, fallbackText, fallbackFont) {
  if (!labelEl) return measureTextWidth(fallbackText, fallbackFont);
  const prevInline = {
    maxWidth: labelEl.style.maxWidth,
    whiteSpace: labelEl.style.whiteSpace,
    wordBreak: labelEl.style.wordBreak,
    overflowWrap: labelEl.style.overflowWrap,
    width: labelEl.style.width,
    display: labelEl.style.display,
  };
  const computedDisplay = getComputedStyle(labelEl).display;
  labelEl.style.maxWidth = "none";
  labelEl.style.whiteSpace = "nowrap";
  labelEl.style.wordBreak = "normal";
  labelEl.style.overflowWrap = "normal";
  labelEl.style.width = "max-content";
  if (computedDisplay === "inline") labelEl.style.display = "inline-block";
  const measured = Math.ceil(Math.max(labelEl.scrollWidth || 0, labelEl.getBoundingClientRect().width || 0));
  labelEl.style.maxWidth = prevInline.maxWidth;
  labelEl.style.whiteSpace = prevInline.whiteSpace;
  labelEl.style.wordBreak = prevInline.wordBreak;
  labelEl.style.overflowWrap = prevInline.overflowWrap;
  labelEl.style.width = prevInline.width;
  labelEl.style.display = prevInline.display;
  if (measured > 0) return measured;
  return measureTextWidth(fallbackText, fallbackFont);
}

function getTableColumnWidth(col, minimumWidth = 40) {
  const inlineWidth = Number.parseFloat(col?.style?.width);
  const renderedWidth = Number(col?.offsetWidth);
  const width = Number.isFinite(inlineWidth) && inlineWidth > 0
    ? inlineWidth
    : renderedWidth;
  return Math.max(minimumWidth, Math.round(Number.isFinite(width) && width > 0 ? width : minimumWidth));
}

function syncTableTotalWidth(table, cols, minWidths = []) {
  const totalWidth = Array.from(cols).reduce((sum, col, index) => (
    sum + getTableColumnWidth(col, Number(minWidths[index]) || 40)
  ), 0);
  const width = Math.max(1, Math.round(totalWidth));
  table.style.width = `${width}px`;
  table.style.minWidth = `${width}px`;
  return width;
}

function captureTableColumnWidths(cols, minWidths = []) {
  return Array.from(cols).map((col, index) => (
    getTableColumnWidth(col, Number(minWidths[index]) || 40)
  ));
}

function applyTableColumnWidths(table, cols, widths, minWidths = []) {
  Array.from(cols).forEach((col, index) => {
    const minimumWidth = Number(minWidths[index]) || 40;
    const width = Math.max(minimumWidth, Math.round(Number(widths[index]) || minimumWidth));
    col.style.width = `${width}px`;
  });
  syncTableTotalWidth(table, cols, minWidths);
}

function autoFitColumn(table, cols, ths, minWidths, index, maxColWidth) {
  if (index < 0 || index >= cols.length || index >= ths.length) return;
  const rows = table.querySelectorAll("tbody tr");
  const font = getComputedStyle(table).font;
  const headerFont = ths[0] ? getComputedStyle(ths[0]).font : font;
  const th = ths[index];
  const minW = (minWidths && minWidths[index]) || 40;
  const thStyles = getComputedStyle(th);
  const headerPadX = (parseFloat(thStyles.paddingLeft) || 0) + (parseFloat(thStyles.paddingRight) || 0);
  const labelEl = th.querySelector(".table-col-label");
  const headerText = String(labelEl ? labelEl.textContent : th.textContent || "");
  const headerContentW = measureHeaderLabelWidth(labelEl, headerText, headerFont);
  let maxW = Math.max(minW, headerContentW + headerPadX + 8);
  rows.forEach(tr => {
    const td = tr.children[index];
    if (!td) return;
    const textarea = td.querySelector("textarea");
    const select = td.querySelector("select");
    const input = td.querySelector("input");
    let text = "";
    if (textarea) text = textarea.value;
    else if (select) text = select.options[select.selectedIndex]?.text || "";
    else if (input && input.type === "checkbox") return;
    else if (input) text = input.value;
    else text = td.textContent;
    if (text) maxW = Math.max(maxW, measureTextWidth(text, font) + 28);
  });
  cols[index].style.width = `${Math.min(maxW, maxColWidth)}px`;
}

function autoFitColumns(table, cols, ths, minWidths, maxColWidth) {
  ths.forEach((_th, index) => autoFitColumn(table, cols, ths, minWidths, index, maxColWidth));
  syncTableTotalWidth(table, cols, minWidths);
  table.querySelectorAll("tbody textarea").forEach(resizeCellTextarea);
}

export function initTableColumnResizing(tableId, minWidths) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const cols = table.querySelectorAll("colgroup col");
  const ths = table.querySelectorAll("thead th");
  if (!cols.length || !ths.length) return;
  const configuredWidths = getConfiguredTableColumnWidths(tableId, cols, ths, minWidths);
  const defaultWidths = configuredWidths || captureTableColumnWidths(cols, minWidths);
  if (configuredWidths) {
    tableDefaultColumnWidthsById.set(tableId, defaultWidths);
  } else if (!tableDefaultColumnWidthsById.has(tableId)
      || tableDefaultColumnWidthsById.get(tableId).length !== cols.length) {
    tableDefaultColumnWidthsById.set(tableId, defaultWidths);
  }

  ths.forEach((th, idx) => {
    if (idx >= cols.length) return;

    // Wrap header text in a label span if not already wrapped
    if (!th.querySelector(".table-col-label")) {
      const label = document.createElement("span");
      label.className = "table-col-label";
      while (th.firstChild) label.appendChild(th.firstChild);
      th.appendChild(label);
    }

    // Remove existing resizer if any (in case of re-init)
    const existing = th.querySelector(".table-col-resizer");
    if (existing) existing.remove();

    const resizer = document.createElement("div");
    resizer.className = "table-col-resizer";
    th.appendChild(resizer);

    const minW = (minWidths && minWidths[idx]) || 40;

    // Drag to resize
    resizer.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const startX = e.clientX;
      const startW = getTableColumnWidth(cols[idx], minW);
      document.body.classList.add("ps-resizing-table-column");

      function onMove(ev) {
        const newW = Math.max(minW, startW + (ev.clientX - startX));
        cols[idx].style.width = `${Math.round(newW)}px`;
        syncTableTotalWidth(table, cols, minWidths);
      }
      function onUp() {
        document.removeEventListener("mousemove", onMove, true);
        document.removeEventListener("mouseup", onUp, true);
        document.body.classList.remove("ps-resizing-table-column");
        saveTableColumnWidths(tableId, cols, ths, minWidths);
        table.querySelectorAll("tbody textarea").forEach(resizeCellTextarea);
      }
      document.addEventListener("mousemove", onMove, true);
      document.addEventListener("mouseup", onUp, true);
    });

    // A click is emitted after mouseup even when the pointer was dragged. Keep
    // that synthetic click on the handle from reaching sortable table headers.
    resizer.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
    });

    resizer.addEventListener("dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const defaults = tableDefaultColumnWidthsById.get(tableId) || defaultWidths;
      const width = Math.max(minW, Math.round(Number(defaults[idx]) || minW));
      cols[idx].style.width = `${width}px`;
      syncTableTotalWidth(table, cols, minWidths);
      saveTableColumnWidths(tableId, cols, ths, minWidths);
      table.querySelectorAll("tbody textarea").forEach(resizeCellTextarea);
    });
  });

  const savedWidths = tableColumnWidthsById.get(tableId);
  if (Array.isArray(savedWidths) && savedWidths.length === cols.length) {
    applyTableColumnWidths(table, cols, savedWidths, minWidths);
  } else if (configuredWidths) {
    applyTableColumnWidths(table, cols, configuredWidths, minWidths);
    tableColumnWidthsById.set(tableId, captureTableColumnWidths(cols, minWidths));
  } else {
    autoFitColumns(table, cols, ths, minWidths, 380);
    tableColumnWidthsById.set(tableId, captureTableColumnWidths(cols, minWidths));
  }
}
