import { openDatasetNamePicker } from "/ui/shared/components/pickers/dataset_name_picker.js";
import { datasetInstanceCategory } from "/ui/shared/dataset/dataset_category.js?v=20260920a";
import { reviewStatusIconSvg } from "/ui/shared/components/status_icon/status_icon.js?v=20260911a";
import { createTableGroupRow } from "/ui/shared/components/table_group_row/table_group_row.js?v=20261013a";
import {
  STATUS_CURRENT,
  STATUS_REVIEW_NEEDED,
  normalizeReviewStatus,
  statusNeedsReview,
} from "/ui/shared/dataset/review_status.js";
import { formatDetailsFormulaText } from "/ui/shared/tabs/details/details_dependencies.js?v=20261021c";
import {
  BERQUIST_SHERMAN_VARIANTS,
  berquistShermanDisplayLabel,
  getBerquistShermanContract,
  normalizeBerquistShermanVariant,
} from "/ui/shared/dataset/berquist_sherman_contract.js";
import {
  attachSettingsFileDropZone,
  buildSettingsFile,
  confirmSaveBeforeLoad,
  loadRecentSettingsFiles,
  openSettingsFile,
  openSettingsFileMenu,
  readSettingsFile,
  rememberRecentSettingsFile,
  saveSettingsFile,
} from "/ui/shared/components/settings_file/settings_file.js?v=20260925a";

import { allFilterValuesSelected as isDatasetFilterAllValuesSelected, renderValueFilterMenu } from "/ui/shared/components/value_filter_menu/value_filter_menu.js?v=20260920a";

export function installProjectInstanceDatasetTable(ctx) {
  const { api, els, projectName, state } = ctx;
  const {
    fetchProjectDatasetTypes,
    loadProjectUserPreferences,
    scheduleProjectUserPreferencesSave,
  } = ctx;
  const { DATASET_TABLE_COLUMNS, DATASET_COLUMNS, DATASET_TABLE_DEFAULT_WIDTHS, DATASET_TABLE_AUTOFIT_MAX_WIDTH, DATASET_TABLE_AUTOFIT_CELL_EXTRA_WIDTH, DATASET_TABLE_AUTOFIT_HEADER_EXTRA_WIDTH, DATASET_TABLE_BLANK_LABEL } = ctx.constants;
  const { datasetTablePreferenceWidthKeys, datasetTableView, cachedDatasetFilter, datasetTableSelection } = state;
  const DATASET_COLUMN_DRAG_TYPE = "text/x-pi-column";
  const DATASET_GROUP_DRAG_TYPE = "text/x-pi-group-key";
  const DATASET_FILTER_DRAG_TYPE = "text/x-pi-filter-key";
  const DATASET_TABLE_PREFERENCES_LOAD_TIMEOUT_MS = 5000;
  const DATASET_VIEW_CONFIG_KIND = "arcrho.project_instance_dataset_view";
  const DATASET_VIEW_CONFIG_VERSION = 1;
  const DATASET_VIEW_CONFIG_LABEL = "group and filter settings";
  const DATASET_VIEW_CONFIG_FILTER_NAME = "Group And Filter Settings";
  const DATASET_VIEW_CONFIG_MENU_LABEL = "Group And Filter";
  const applyCachedDatasetSnapshot = (...args) => api.applyCachedDatasetSnapshot(...args);
  const beginPageLoading = (...args) => api.beginPageLoading(...args);
  const captureDatasetTableScroll = (...args) => api.captureDatasetTableScroll(...args);
  const finishPageLoading = (...args) => api.finishPageLoading(...args);
  const focusProjectInstancePage = (...args) => api.focusProjectInstancePage(...args);
  const getCachedDatasetKey = (...args) => api.getCachedDatasetKey(...args);
  const getExcelLinkStatus = (...args) => api.getExcelLinkStatus?.(...args) || null;
  const getExcelLinkStatusSentence = (...args) => api.getExcelLinkStatusSentence?.(...args) || "";
  const hasCachedDatasetMetadataForSelectedPath = (...args) => api.hasCachedDatasetMetadataForSelectedPath(...args);
  const isDatasetRecordCached = (...args) => api.isDatasetRecordCached(...args);
  const isTemporaryDatasetView = (...args) => api.isTemporaryDatasetView(...args);
  const loadCachedDatasetFilterForSelectedPath = (...args) => api.loadCachedDatasetFilterForSelectedPath(...args);
  const normalizeLookupKey = (...args) => api.normalizeLookupKey(...args);
  const normalizePath = (...args) => api.normalizePath(...args);
  const openDatasetWindow = (...args) => api.openDatasetWindow(...args);
  const openDfmWindow = (...args) => api.openDfmWindow(...args);
  const openBerquistShermanWindow = (...args) => api.openBerquistShermanWindow(...args);
  const openBornhuetterFergusonWindow = (...args) => api.openBornhuetterFergusonWindow(...args);
  const openCapeCodWindow = (...args) => api.openCapeCodWindow(...args);
  const openBootstrapWindow = (...args) => api.openBootstrapWindow(...args);
  const openStochasticConsolidationWindow = (...args) => api.openStochasticConsolidationWindow(...args);
  const openResultSelectionWindow = (...args) => api.openResultSelectionWindow(...args);
  const openNewDatasetDraftWindow = (...args) => api.openNewDatasetDraftWindow(...args);
  const postProjectInstanceStatus = (...args) => api.postProjectInstanceStatus(...args);
  const restoreDatasetTableScroll = (...args) => api.restoreDatasetTableScroll(...args);
  const setStatus = (...args) => api.setStatus(...args);
  const shouldUseCachedDatasetFilter = (...args) => api.shouldUseCachedDatasetFilter(...args);
  const syncCachedDatasetToolbar = (...args) => api.syncCachedDatasetToolbar(...args);
  const toText = (...args) => api.toText(...args);
  const addDatasetSelectionInFlightKeys = new Set();

function isTemporaryViewActive() {
  return isTemporaryDatasetView();
}

function isDatasetColumnFilterable(key) {
  const normalized = toText(key);
  return normalized !== "status" && !!getDatasetColumn(normalized);
}

function hasDataTransferType(dataTransfer, type) {
  return Array.from(dataTransfer?.types || []).includes(type);
}

function isDatasetColumnGroupable(key) {
  return !!getDatasetColumn(toText(key));
}

function getDatasetFilterActiveValues(key, context = null) {
  if (!isDatasetColumnFilterable(key)) return [];
  if (!context) {
    const selected = datasetTableView.filters.get(key);
    return selected instanceof Set ? Array.from(selected).map((value) => String(value)) : [];
  }
  const options = getDatasetColumnOptions(key, context);
  if (!options.length) return [];
  const selected = context?.selectionsByKey?.get?.(key) || getDatasetFilterSelection(key, options);
  if (!(selected instanceof Set) || selected.size === 0 || selected.size === options.length) return [];
  const optionLabels = new Map(options.map((opt) => [opt.key, opt.label]));
  return options
    .filter((opt) => selected.has(opt.key))
    .map((opt) => opt.label || opt.key)
    .concat(
      Array.from(selected)
        .filter((keyValue) => !optionLabels.has(keyValue))
        .map((keyValue) => String(keyValue))
    );
}

function isDatasetExplicitAllFilter(key, context = null) {
  const normalized = toText(key);
  if (!isDatasetColumnFilterable(normalized)) return false;
  if (!state.datasetTableExplicitAllFilterKeys?.has?.(normalized)) return false;
  const options = getDatasetColumnOptions(normalized, context);
  if (!options.length) return false;
  const selected = context?.selectionsByKey?.get?.(normalized) || getDatasetFilterSelection(normalized, options);
  if (!(selected instanceof Set)) return false;
  if (selected.size === 0) return true;
  return isDatasetFilterAllValuesSelected(selected, options);
}

function isPointInsideDatasetActiveFiltersFrame(clientX, clientY) {
  if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) return true;
  if (clientX === 0 && clientY === 0) return true;
  const rect = els.datasetActiveFilters?.getBoundingClientRect?.();
  if (!rect) return true;
  return (
    clientX >= rect.left
    && clientX <= rect.right
    && clientY >= rect.top
    && clientY <= rect.bottom
  );
}

function getDatasetActiveFilterSummaries(context = null) {
  const summaries = [];
  for (const col of DATASET_TABLE_COLUMNS) {
    const values = getDatasetFilterActiveValues(col.key, context);
    const explicitAll = isDatasetExplicitAllFilter(col.key, context);
    if (!values.length && !explicitAll) continue;
    summaries.push({
      key: col.key,
      label: col.label,
      explicitAll,
    });
  }
  return summaries;
}

function clearDatasetColumnFilter(key) {
  const normalized = toText(key);
  if (!normalized) return;
  state.datasetTableExplicitAllFilterKeys?.delete?.(normalized);
  if (!isDatasetColumnFilterable(normalized)) {
    datasetTableView.filters.delete(normalized);
    return;
  }
  if (!getDatasetColumn(normalized) || !datasetTableView.filters.has(normalized)) return;
  datasetTableView.filters.delete(normalized);
  closeDatasetTableFilterPopover();
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function syncDatasetActiveFiltersToolbar(context = null) {
  const wrap = els.datasetActiveFilters;
  if (!wrap) return;
  const summaries = getDatasetActiveFilterSummaries(context);
  wrap.replaceChildren();
  wrap.hidden = false;
  wrap.setAttribute("aria-label", summaries.length ? "Active dataset table filters" : "Dataset table filters: none");
  const frameLabel = document.createElement("span");
  frameLabel.className = "dataset-filter-label";
  frameLabel.textContent = "Filter:";
  wrap.appendChild(frameLabel);
  if (!summaries.length) {
    const none = document.createElement("span");
    none.className = "dataset-filter-none";
    none.textContent = "None";
    wrap.appendChild(none);
    if (state.datasetTableFilterOpenMode === "active-filter") closeDatasetTableFilterPopover();
    return;
  }
  for (const item of summaries) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "dataset-filter-chip";
    chip.classList.toggle("is-all", !!item.explicitAll);
    chip.dataset.filterKey = item.key;
    chip.draggable = true;
    chip.setAttribute("aria-label", item.explicitAll ? `Show ${item.label} filter: All` : `Show ${item.label} filter`);
    chip.setAttribute("aria-haspopup", "menu");
    const label = document.createElement("span");
    label.className = "dataset-filter-chip-label";
    label.textContent = item.label;
    chip.append(label);
    chip.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData(DATASET_FILTER_DRAG_TYPE, item.key);
      event.dataTransfer?.setData("text/plain", item.label);
      event.dataTransfer.effectAllowed = "move";
      state.datasetTableFilterDragSourceKey = item.key;
      chip.classList.add("dragging");
      closeDatasetTableFilterPopover();
    });
    chip.addEventListener("dragend", (event) => {
      chip.classList.remove("dragging");
      const key = event.dataTransfer?.getData(DATASET_FILTER_DRAG_TYPE) || state.datasetTableFilterDragSourceKey || item.key;
      state.datasetTableFilterDragSourceKey = "";
      if (isPointInsideDatasetActiveFiltersFrame(event.clientX, event.clientY)) return;
      clearDatasetColumnFilter(key);
    });
    chip.addEventListener("mouseenter", () => openDatasetActiveFilterChipPopover(chip));
    chip.addEventListener("mouseleave", () => {
      state.datasetTableFilterHoveringTrigger = false;
      scheduleDatasetTableFilterHoverClose();
    });
    chip.addEventListener("focus", () => openDatasetActiveFilterChipPopover(chip));
    chip.addEventListener("blur", () => {
      state.datasetTableFilterHoveringTrigger = false;
      scheduleDatasetTableFilterHoverClose();
    });
    wrap.appendChild(chip);
  }
  if (state.datasetTableFilterOpenMode === "active-filter" && state.datasetTableFilterColumn) {
    const nextAnchor = findDatasetActiveFilterChip(state.datasetTableFilterColumn);
    if (nextAnchor) {
      state.datasetTableFilterAnchor = nextAnchor;
      positionDatasetTableFilterPopover();
    } else {
      closeDatasetTableFilterPopover();
    }
  }
}

function clearDatasetGroupDropState() {
  els.datasetGroupByStatus?.classList?.remove("drag-over", "drag-invalid");
  els.datasetTableWrap?.classList?.remove("group-remove-target");
  for (const chip of els.datasetGroupByStatus?.querySelectorAll?.(".dataset-group-chip.group-drag-before, .dataset-group-chip.group-drag-after") || []) {
    chip.classList.remove("group-drag-before", "group-drag-after");
  }
}

function clearDatasetActiveFilterDropState() {
  els.datasetActiveFilters?.classList?.remove("drag-over", "drag-invalid");
}

function syncDatasetGroupByToolbar() {
  const wrap = els.datasetGroupByStatus;
  if (!wrap) return;
  const keys = getDatasetGroupByKeys();
  wrap.replaceChildren();
  wrap.classList.toggle("has-groups", keys.length > 0);
  const label = document.createElement("span");
  label.className = "dataset-group-label";
  label.textContent = "Group by:";
  const placeholder = document.createElement("span");
  placeholder.className = "dataset-group-placeholder";
  if (keys.length) {
    placeholder.classList.add("dataset-group-add-hint");
    placeholder.setAttribute("aria-label", "Drag a column header here to group by ...");
    placeholder.innerHTML = `
      <svg viewBox="0 0 12 12" aria-hidden="true" focusable="false">
        <path d="M6 2v8M2 6h8"></path>
      </svg>
      <span class="dataset-group-hint-tooltip" role="tooltip">Drag a column header here to group by ...</span>
    `;
  } else {
    placeholder.textContent = "Drag a column header here to group by that column";
  }
  wrap.appendChild(label);
  if (!keys.length) {
    wrap.appendChild(placeholder);
    return;
  }
  for (const key of keys) {
    const col = getDatasetColumn(key);
    if (!col) continue;
    const chip = document.createElement("span");
    chip.className = "dataset-group-chip";
    chip.draggable = true;
    chip.dataset.groupKey = key;
    const label = document.createElement("span");
    label.className = "dataset-group-chip-label";
    label.textContent = col.label;
    chip.append(label);
    chip.addEventListener("dragstart", (event) => {
      event.dataTransfer?.setData(DATASET_GROUP_DRAG_TYPE, key);
      event.dataTransfer?.setData(DATASET_COLUMN_DRAG_TYPE, key);
      event.dataTransfer?.setData("text/plain", col.label);
      event.dataTransfer.effectAllowed = "move";
      state.datasetGroupDragSourceKey = key;
      state.datasetTableColumnDragSourceKey = key;
      setDatasetColumnDragImage(event, col.label);
    });
    chip.addEventListener("dragover", (event) => {
      if (!hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) return;
      event.preventDefault();
      event.stopPropagation();
      updateDatasetGroupChipDragIndicator(chip, event.dataTransfer?.getData(DATASET_GROUP_DRAG_TYPE) || state.datasetGroupDragSourceKey || "", key, getDatasetGroupChipDropPosition(event, chip));
    });
    chip.addEventListener("dragleave", () => {
      chip.classList.remove("group-drag-before", "group-drag-after");
    });
    chip.addEventListener("drop", (event) => {
      if (!hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) return;
      event.preventDefault();
      event.stopPropagation();
      const sourceKey = event.dataTransfer?.getData(DATASET_GROUP_DRAG_TYPE) || state.datasetGroupDragSourceKey || "";
      const position = getDatasetGroupChipDropPosition(event, chip);
      clearDatasetGroupDropState();
      reorderDatasetGroupKey(sourceKey, key, position);
    });
    chip.addEventListener("dragend", () => {
      clearDatasetGroupDropState();
      clearDatasetActiveFilterDropState();
      clearDatasetColumnDragIndicators();
      removeDatasetColumnDragImage();
      state.datasetGroupDragSourceKey = "";
      state.datasetTableColumnDragSourceKey = "";
    });
    wrap.appendChild(chip);
  }
  wrap.appendChild(placeholder);
}

function getDatasetGroupChipDropPosition(event, chip) {
  const rect = chip?.getBoundingClientRect?.();
  if (!rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.width) || rect.width <= 0) return "before";
  return event.clientX > rect.left + rect.width / 2 ? "after" : "before";
}

function updateDatasetGroupChipDragIndicator(targetChip, sourceKey, targetKey, position = "before") {
  for (const chip of els.datasetGroupByStatus?.querySelectorAll?.(".dataset-group-chip.group-drag-before, .dataset-group-chip.group-drag-after") || []) {
    chip.classList.remove("group-drag-before", "group-drag-after");
  }
  if (!targetChip || !sourceKey || !targetKey || sourceKey === targetKey) return;
  targetChip.classList.add(position === "after" ? "group-drag-after" : "group-drag-before");
}

function reorderDatasetGroupKey(sourceKey, targetKey, position = "before") {
  const source = toText(sourceKey);
  const target = toText(targetKey);
  const keys = getDatasetGroupByKeys();
  if (!keys.includes(source) || !keys.includes(target) || source === target) return false;
  const next = keys.filter((key) => key !== source);
  const targetIndex = next.indexOf(target);
  if (targetIndex < 0) return false;
  next.splice(targetIndex + (position === "after" ? 1 : 0), 0, source);
  applyDatasetGroupByKeys(next);
  return true;
}


function getDatasetRecordKey(record) {
  const rowIndex = Number(record?.rowIndex);
  if (Number.isInteger(rowIndex) && rowIndex >= 0) return `row-${rowIndex}`;
  const name = toText(record?.datasetName);
  return name ? `name-${name.toLowerCase()}` : "";
}

function getDatasetSelectionName(record) {
  return normalizeLookupKey(record?.datasetName || getDatasetRecordValue(record, "name"));
}

function captureDatasetTableSelection() {
  pruneDatasetTableSelection();
  const selectedNames = [];
  for (const record of getSelectedDatasetRecords()) {
    const name = getDatasetSelectionName(record);
    if (name) selectedNames.push(name);
  }
  return {
    selectedNames,
    anchorName: getDatasetSelectionName(getDatasetRecordByKey(datasetTableSelection.anchorKey)),
    activeName: getDatasetSelectionName(getDatasetRecordByKey(datasetTableSelection.activeKey)),
    selectedKeys: Array.from(datasetTableSelection.selectedKeys),
    anchorKey: datasetTableSelection.anchorKey,
    activeKey: datasetTableSelection.activeKey,
  };
}

function restoreDatasetTableSelection(selectionState) {
  if (!selectionState) return;
  const selectedNames = new Set(
    (Array.isArray(selectionState.selectedNames) ? selectionState.selectedNames : [])
      .map((name) => normalizeLookupKey(name))
      .filter(Boolean)
  );
  const oldSelectedKeys = new Set(
    (Array.isArray(selectionState.selectedKeys) ? selectionState.selectedKeys : [])
      .map((key) => toText(key))
      .filter(Boolean)
  );
  const anchorName = normalizeLookupKey(selectionState.anchorName);
  const oldAnchorKey = toText(selectionState.anchorKey);
  const activeName = normalizeLookupKey(selectionState.activeName);
  const oldActiveKey = toText(selectionState.activeKey);
  let nextAnchorKey = "";
  let nextActiveKey = "";

  datasetTableSelection.selectedKeys.clear();
  datasetTableSelection.anchorKey = "";
  datasetTableSelection.activeKey = "";

  for (const record of state.datasetTableVisibleRecords) {
    const recordKey = getDatasetRecordKey(record);
    if (!recordKey) continue;
    const name = getDatasetSelectionName(record);
    const selected = (name && selectedNames.has(name)) || (!selectedNames.size && oldSelectedKeys.has(recordKey));
    if (!selected) continue;
    datasetTableSelection.selectedKeys.add(recordKey);
    if (!nextAnchorKey && ((anchorName && name === anchorName) || (!anchorName && recordKey === oldAnchorKey))) {
      nextAnchorKey = recordKey;
    }
    if (!nextActiveKey && ((activeName && name === activeName) || (!activeName && recordKey === oldActiveKey))) {
      nextActiveKey = recordKey;
    }
  }

  datasetTableSelection.anchorKey = nextAnchorKey || datasetTableSelection.selectedKeys.values().next().value || "";
  datasetTableSelection.activeKey = nextActiveKey || datasetTableSelection.anchorKey;
  syncDatasetTableSelectionDom();
}

function pruneDatasetTableSelection() {
  const visibleKeys = new Set(state.datasetTableVisibleRecords.map(getDatasetRecordKey).filter(Boolean));
  for (const key of Array.from(datasetTableSelection.selectedKeys)) {
    if (!visibleKeys.has(key)) datasetTableSelection.selectedKeys.delete(key);
  }
  if (!visibleKeys.has(datasetTableSelection.anchorKey)) {
    datasetTableSelection.anchorKey = datasetTableSelection.selectedKeys.values().next().value || "";
  }
  if (!visibleKeys.has(datasetTableSelection.activeKey)) {
    datasetTableSelection.activeKey = datasetTableSelection.anchorKey;
  }
  updateDatasetSelectionStatusBar();
}

function getSelectedDatasetRecords() {
  pruneDatasetTableSelection();
  return state.datasetTableVisibleRecords.filter((record) => datasetTableSelection.selectedKeys.has(getDatasetRecordKey(record)));
}

function getDatasetRecordByKey(key) {
  const normalized = toText(key);
  return state.datasetTableVisibleRecords.find((record) => getDatasetRecordKey(record) === normalized) || null;
}

function getDatasetRecordIndexByKey(key) {
  const normalized = toText(key);
  if (!normalized) return -1;
  return state.datasetTableVisibleRecords.findIndex((record) => getDatasetRecordKey(record) === normalized);
}

function setDatasetRecordSelected(key, selected) {
  const normalized = toText(key);
  if (!normalized) return;
  if (selected) datasetTableSelection.selectedKeys.add(normalized);
  else datasetTableSelection.selectedKeys.delete(normalized);
}

function focusDatasetTableSurface() {
  const surface = els.datasetTableSurface;
  if (!surface) return;
  if (surface.tabIndex < 0) surface.tabIndex = 0;
  surface.focus?.({ preventScroll: true });
}

function scrollDatasetRecordIntoView(key) {
  const normalized = toText(key);
  if (!normalized) return;
  const row = els.datasetTableSurface?.querySelector?.(`tr[data-record-key="${CSS.escape(normalized)}"]`);
  const wrap = els.datasetTableWrap;
  if (!row || !wrap) return;
  const rowRect = row.getBoundingClientRect();
  const wrapRect = wrap.getBoundingClientRect();
  const headerHeight = Math.ceil(
    row.closest("table")?.querySelector?.("thead")?.getBoundingClientRect?.().height || 0,
  );
  const visibleTop = wrapRect.top + headerHeight;
  if (rowRect.top < visibleTop) {
    wrap.scrollTop -= visibleTop - rowRect.top;
  } else if (rowRect.bottom > wrapRect.bottom) {
    wrap.scrollTop += rowRect.bottom - wrapRect.bottom;
  }
}

function getActiveDatasetSelectionIndex() {
  for (const key of [datasetTableSelection.activeKey, datasetTableSelection.anchorKey]) {
    const index = getDatasetRecordIndexByKey(key);
    if (index >= 0 && datasetTableSelection.selectedKeys.has(key)) return index;
  }
  for (const key of datasetTableSelection.selectedKeys) {
    const selectedIndex = getDatasetRecordIndexByKey(key);
    if (selectedIndex >= 0) return selectedIndex;
  }
  return -1;
}

function selectDatasetRecordAtIndex(index) {
  if (!state.datasetTableVisibleRecords.length) return false;
  const clamped = Math.max(0, Math.min(state.datasetTableVisibleRecords.length - 1, Number(index)));
  const record = state.datasetTableVisibleRecords[clamped];
  const key = getDatasetRecordKey(record);
  if (!key) return false;
  datasetTableSelection.selectedKeys.clear();
  datasetTableSelection.selectedKeys.add(key);
  datasetTableSelection.anchorKey = key;
  datasetTableSelection.activeKey = key;
  syncDatasetTableSelectionDom();
  scrollDatasetRecordIntoView(key);
  focusDatasetTableSurface();
  return true;
}

function selectDatasetRecordByName(datasetName, { reveal = false } = {}) {
  const targetKey = normalizeLookupKey(datasetName);
  if (!targetKey) return false;
  if (reveal) {
    const context = buildDatasetTableRenderContext();
    const record = context.records.find((item) => normalizeLookupKey(item.datasetName) === targetKey);
    if (!record) return false;
    for (const [key, selected] of context.selectionsByKey) {
      if (isDatasetColumnFilterActive(key, context) && !selected.has(getDatasetFilterKey(getDatasetRecordValue(record, key)))) {
        datasetTableView.filters.delete(key);
        state.datasetTableExplicitAllFilterKeys?.delete(key);
      }
    }
    const path = [];
    for (const key of getDatasetGroupByKeys()) {
      path.push({ key, valueKey: getDatasetFilterKey(getDatasetRecordValue(record, key)) });
      datasetTableView.collapsedGroups.delete(getDatasetGroupId(path));
    }
    closeDatasetTableFilterPopover();
    renderDatasetTable();
    saveDatasetTablePreferences();
  }
  const record = state.datasetTableVisibleRecords.find((item) => normalizeLookupKey(item?.datasetName) === targetKey);
  const key = getDatasetRecordKey(record);
  if (!key) return false;
  datasetTableSelection.selectedKeys.clear();
  datasetTableSelection.selectedKeys.add(key);
  datasetTableSelection.anchorKey = key;
  datasetTableSelection.activeKey = key;
  syncDatasetTableSelectionDom();
  scrollDatasetRecordIntoView(key);
  focusDatasetTableSurface();
  return true;
}

function applyDatasetRowSelection(record, event = {}) {
  const key = getDatasetRecordKey(record);
  if (!key) return;
  const visibleKeys = state.datasetTableVisibleRecords.map(getDatasetRecordKey).filter(Boolean);
  const clickedIndex = visibleKeys.indexOf(key);
  const anchorIndex = visibleKeys.indexOf(datasetTableSelection.anchorKey);
  const additive = !!(event.ctrlKey || event.metaKey);

  if (event.shiftKey && clickedIndex >= 0 && anchorIndex >= 0) {
    const [start, end] = clickedIndex < anchorIndex ? [clickedIndex, anchorIndex] : [anchorIndex, clickedIndex];
    if (!additive) datasetTableSelection.selectedKeys.clear();
    for (const rangeKey of visibleKeys.slice(start, end + 1)) {
      datasetTableSelection.selectedKeys.add(rangeKey);
    }
  } else if (additive) {
    setDatasetRecordSelected(key, !datasetTableSelection.selectedKeys.has(key));
    datasetTableSelection.anchorKey = key;
  } else {
    if (datasetTableSelection.selectedKeys.has(key) && datasetTableSelection.selectedKeys.size === 1) {
      datasetTableSelection.selectedKeys.delete(key);
    } else {
      datasetTableSelection.selectedKeys.clear();
      datasetTableSelection.selectedKeys.add(key);
    }
    datasetTableSelection.anchorKey = key;
  }
  datasetTableSelection.activeKey = key;
  syncDatasetTableSelectionDom();
}

function handleDatasetTableKeyDown(event) {
  if (event.key === "Enter") {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const activeIndex = getActiveDatasetSelectionIndex();
    if (activeIndex < 0) return;
    event.preventDefault();
    event.stopPropagation();
    openDatasetRecord(state.datasetTableVisibleRecords[activeIndex]);
    return;
  }
  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const activeIndex = getActiveDatasetSelectionIndex();
  if (activeIndex < 0) return;
  const nextIndex = activeIndex + (event.key === "ArrowDown" ? 1 : -1);
  if (nextIndex < 0 || nextIndex >= state.datasetTableVisibleRecords.length) {
    event.preventDefault();
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  selectDatasetRecordAtIndex(nextIndex);
}

function isActiveDatasetSelectionKey(key) {
  return (
    datasetTableSelection.selectedKeys.size > 1
    && !!key
    && key === datasetTableSelection.activeKey
    && datasetTableSelection.selectedKeys.has(key)
  );
}

function syncDatasetTableSelectionDom() {
  for (const tr of els.datasetTableSurface?.querySelectorAll?.("tr[data-record-key]") || []) {
    const key = toText(tr.dataset.recordKey);
    const selected = datasetTableSelection.selectedKeys.has(key);
    tr.classList.toggle("selected", selected);
    tr.classList.toggle("multi", selected && datasetTableSelection.selectedKeys.size > 1);
    tr.classList.toggle("active", isActiveDatasetSelectionKey(key));
    tr.setAttribute("aria-selected", selected ? "true" : "false");
  }
  updateDatasetSelectionStatusBar();
}

function updateDatasetSelectionStatusBar() {
  const count = datasetTableSelection.selectedKeys.size;
  if (count > 1) {
    if (state.lastDatasetSelectionStatusCount !== count) {
      postProjectInstanceStatus(`${count} datasets selected`);
    }
    state.lastDatasetSelectionStatusCount = count;
    return;
  }
  if (state.lastDatasetSelectionStatusCount > 1) {
    postProjectInstanceStatus("Status: Ready");
  }
  state.lastDatasetSelectionStatusCount = count;
}


// The grouping and filtering the user can save to a settings file. The stored table
// preferences carry the same two fields, built here, so a file and the preference store
// can never describe the same view differently.
function getDatasetViewSettingsPayload() {
  const known = new Set(DATASET_TABLE_COLUMNS.map((col) => col.key));
  const filters = {};
  for (const col of DATASET_TABLE_COLUMNS) {
    const key = col.key;
    if (!isDatasetColumnFilterable(key)) {
      filters[key] = [];
      continue;
    }
    const selected = datasetTableView.filters.get(key);
    if (!known.has(key) || !(selected instanceof Set) || selected.size === 0) {
      filters[key] = [];
      continue;
    }
    const options = getDatasetColumnOptions(key);
    if (isDatasetFilterAllValuesSelected(selected, options)) {
      filters[key] = [];
      continue;
    }
    filters[key] = Array.from(selected).map((value) => String(value)).sort();
  }
  return { filters, groupBy: getDatasetGroupByKeys() };
}

function getDatasetTablePreferencePayload() {
  const known = new Set(DATASET_TABLE_COLUMNS.map((col) => col.key));
  const columns = datasetTableView.columns.filter((key) => known.has(key));
  const widths = {};
  for (const col of DATASET_TABLE_COLUMNS) {
    const width = Number(datasetTableView.widths[col.key]);
    if (Number.isFinite(width)) widths[col.key] = Math.round(Math.max(col.minWidth || 80, width));
  }
  const { filters, groupBy } = getDatasetViewSettingsPayload();
  const collapsedGroups = Array.from(datasetTableView.collapsedGroups || [])
    .map((id) => String(id || ""))
    .filter(Boolean)
    .sort();
  const sortKey = toText(datasetTableView.sort?.key);
  const sort = known.has(sortKey)
    ? { key: sortKey, dir: datasetTableView.sort?.dir === "desc" ? "desc" : "asc" }
    : { key: "", dir: "asc" };
  return { columns, widths, filters, groupBy, collapsedGroups, sort };
}

function saveDatasetTablePreferences() {
  if (isTemporaryViewActive()) return;
  if (!state.datasetTablePreferencesLoaded || !projectName) return;
  scheduleProjectUserPreferencesSave(projectName, {
    projectInstance: {
      datasetTable: getDatasetTablePreferencePayload(),
    },
  }, 500);
}

function getDatasetTablePreferencesSource(prefs) {
  const candidates = [
    prefs?.projectInstance?.datasetTable,
    prefs?.project_instance?.dataset_table,
    prefs?.datasetTableView,
  ];
  return candidates.find((item) => item && typeof item === "object" && !Array.isArray(item)) || null;
}

// The other half of the pair above: the grouping and filtering a stored preference or a
// settings file describes, applied to the live view.
function applyDatasetViewSettings(prefs) {
  const known = new Set(DATASET_TABLE_COLUMNS.map((col) => col.key));
  state.datasetTableExplicitAllFilterKeys?.clear?.();
  datasetTableView.filters.clear();
  const filters = prefs.filters && typeof prefs.filters === "object" && !Array.isArray(prefs.filters) ? prefs.filters : {};
  Object.entries(filters).forEach(([key, values]) => {
    const normalized = toText(key);
    if (!known.has(normalized) || !isDatasetColumnFilterable(normalized) || !Array.isArray(values)) return;
    const selected = new Set(values.map((value) => String(value)).filter(Boolean));
    if (selected.size) datasetTableView.filters.set(normalized, selected);
  });
  if (Array.isArray(prefs.groupBy)) {
    datasetTableView.groupBy = prefs.groupBy.map(toText).filter((key, index, list) => known.has(key) && list.indexOf(key) === index);
  }
}

function applyDatasetTablePreferences(source) {
  datasetTablePreferenceWidthKeys.clear();
  const prefs = source && typeof source === "object" && !Array.isArray(source) ? source : {};
  const known = new Set(DATASET_TABLE_COLUMNS.map((col) => col.key));
  if (Array.isArray(prefs.columns)) {
    const columns = [];
    prefs.columns.forEach((key) => {
      const normalized = toText(key);
      if (known.has(normalized) && !columns.includes(normalized)) columns.push(normalized);
    });
    DATASET_TABLE_COLUMNS.forEach((col) => {
      if (!columns.includes(col.key)) columns.push(col.key);
    });
    if (columns.length) datasetTableView.columns = columns;
  }
  const widths = prefs.widths && typeof prefs.widths === "object" && !Array.isArray(prefs.widths) ? prefs.widths : {};
  for (const col of DATASET_TABLE_COLUMNS) {
    const width = Number(widths[col.key]);
    if (!Number.isFinite(width)) continue;
    datasetTableView.widths[col.key] = Math.max(col.minWidth || 80, Math.round(width));
    datasetTablePreferenceWidthKeys.add(col.key);
  }
  applyDatasetViewSettings(prefs);
  datasetTableView.collapsedGroups = new Set(
    Array.isArray(prefs.collapsedGroups)
      ? prefs.collapsedGroups.map((id) => String(id || "")).filter(Boolean)
      : []
  );
  const sortKey = toText(prefs.sort?.key);
  datasetTableView.sort = {
    key: known.has(sortKey) ? sortKey : "",
    dir: prefs.sort?.dir === "desc" ? "desc" : "asc",
  };
}

function withDatasetTablePreferencesTimeout(promise) {
  let timer = 0;
  const timeout = new Promise((_, reject) => {
    timer = window.setTimeout(() => {
      reject(new Error("Project Instance dataset table preferences timed out."));
    }, DATASET_TABLE_PREFERENCES_LOAD_TIMEOUT_MS);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) window.clearTimeout(timer);
  });
}

async function loadDatasetTablePreferences() {
  if (!projectName || state.datasetTablePreferencesLoaded) {
    state.datasetTablePreferencesLoaded = true;
    return;
  }
  beginPageLoading("preferences");
  try {
    const prefs = await withDatasetTablePreferencesTimeout(loadProjectUserPreferences(projectName));
    applyDatasetTablePreferences(getDatasetTablePreferencesSource(prefs));
  } catch (err) {
    console.warn("Failed to load project instance dataset table preferences:", err);
    setStatus("Project Instance table preferences were not loaded; using defaults.", true);
  } finally {
    state.datasetTablePreferencesLoaded = true;
    finishPageLoading("preferences");
  }
}

function describeDatasetViewSettings(settings) {
  const filterCount = Object.values(settings?.filters || {})
    .filter((values) => Array.isArray(values) && values.length).length;
  const groupCount = Array.isArray(settings?.groupBy) ? settings.groupBy.length : 0;
  const parts = [];
  if (groupCount) parts.push(`${groupCount} grouping ${groupCount === 1 ? "column" : "columns"}`);
  if (filterCount) parts.push(`${filterCount} filtered ${filterCount === 1 ? "column" : "columns"}`);
  return { filterCount, groupCount, text: parts.join(" and ") || "no grouping or filters" };
}

// Two group and filter settings match when they filter the same columns to the same values
// and group by the same columns in the same order.
function datasetViewSettingsKey(settings) {
  const filters = settings?.filters && typeof settings.filters === "object" && !Array.isArray(settings.filters)
    ? settings.filters
    : {};
  const filterEntries = Object.keys(filters)
    .sort()
    .filter((key) => Array.isArray(filters[key]) && filters[key].length)
    .map((key) => [key, filters[key].map(String).sort()]);
  const groupBy = Array.isArray(settings?.groupBy) ? settings.groupBy.map(toText) : [];
  return JSON.stringify([filterEntries, groupBy]);
}

// Resolves to true once the file is written.
async function saveDatasetViewSettingsFile() {
  const settings = getDatasetViewSettingsPayload();
  const described = describeDatasetViewSettings(settings);
  if (!described.filterCount && !described.groupCount) {
    setStatus("There is no grouping or filtering to save yet.");
    return false;
  }
  const result = await saveSettingsFile({
    data: buildSettingsFile({
      kind: DATASET_VIEW_CONFIG_KIND,
      version: DATASET_VIEW_CONFIG_VERSION,
      projectName,
      data: settings,
    }),
    suggestedName: `${projectName} Group And Filter.json`,
    filterName: DATASET_VIEW_CONFIG_FILTER_NAME,
  });
  if (result.reason === "canceled") return false;
  if (result.reason === "no-host") {
    setStatus("Saving a group and filter settings file needs the desktop app.", true);
    return false;
  }
  if (!result.ok) {
    setStatus(`Failed to save group and filter settings: ${result.error}`, true);
    return false;
  }
  setStatus(`Saved group and filter settings to ${result.path || "the chosen file"}.`);
  await rememberRecentSettingsFile(DATASET_VIEW_CONFIG_KIND, result.path);
  return true;
}

// A file written from another project keeps only the columns this table has, and a
// filter value the column no longer offers drops itself on the next render. Resolves to
// true once the file's settings replace the current ones.
async function applyDatasetViewSettingsFile(config, fileName) {
  const current = getDatasetViewSettingsPayload();
  const described = describeDatasetViewSettings(current);
  if ((described.filterCount || described.groupCount) && !(await confirmSaveBeforeLoad({
    kind: DATASET_VIEW_CONFIG_KIND,
    label: DATASET_VIEW_CONFIG_LABEL,
    title: "Load Group And Filter Settings",
    currentKey: datasetViewSettingsKey(current),
    keyOf: datasetViewSettingsKey,
    save: saveDatasetViewSettingsFile,
  }))) {
    return false;
  }
  applyDatasetViewSettings(config);
  datasetTableView.collapsedGroups.clear();
  saveDatasetTablePreferences();
  renderDatasetTable();
  setStatus(`Loaded ${describeDatasetViewSettings(getDatasetViewSettingsPayload()).text} from ${fileName}.`);
  return true;
}

async function loadDatasetViewSettingsFile(file) {
  const fileName = toText(file?.name);
  let config = null;
  try {
    config = await readSettingsFile(file, {
      kind: DATASET_VIEW_CONFIG_KIND,
      label: DATASET_VIEW_CONFIG_LABEL,
    });
  } catch (err) {
    setStatus(toText(err?.message) || `${fileName} could not be read.`, true);
    return;
  }
  if (await applyDatasetViewSettingsFile(config, fileName)) {
    void rememberRecentSettingsFile(DATASET_VIEW_CONFIG_KIND, file);
  }
}

// With no `filePath`, the user picks the file in the open dialog.
async function pickDatasetViewSettingsFile(filePath = "") {
  const result = await openSettingsFile({
    kind: DATASET_VIEW_CONFIG_KIND,
    label: DATASET_VIEW_CONFIG_LABEL,
    filterName: DATASET_VIEW_CONFIG_FILTER_NAME,
    filePath,
  });
  if (result.reason === "canceled") return;
  if (result.reason === "no-host") {
    setStatus("Choosing a settings file needs the desktop app; drag the file onto the table instead.", true);
    return;
  }
  if (!result.ok) {
    setStatus(result.error, true);
    return;
  }
  if (await applyDatasetViewSettingsFile(result.data, result.path.split(/[\\/]/).pop() || result.path)) {
    void rememberRecentSettingsFile(DATASET_VIEW_CONFIG_KIND, result.path);
  }
}


function setEmptyTable(message, options = {}) {
  if (!els.datasetTableSurface) return;
  els.datasetTableSurface.innerHTML = "";
  if (options.allowAddDataset) {
    els.datasetTableSurface.dataset.emptyAddDataset = "1";
  } else {
    delete els.datasetTableSurface.dataset.emptyAddDataset;
  }
  syncDatasetGroupByToolbar();
  syncDatasetActiveFiltersToolbar();
  const table = document.createElement("table");
  table.className = "pi-table";
  const tbody = document.createElement("tbody");
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.className = "pi-table-empty";
  if (options.allowAddDataset) {
    td.dataset.emptyAction = "add-dataset";
    td.title = "Right-click to add a dataset";
  }
  td.colSpan = DATASET_COLUMNS;
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
  table.appendChild(tbody);
  els.datasetTableSurface.appendChild(table);
}

/*
Cached dataset lists come off a network drive, so the table surface stays empty
for as long as that read takes. The skeleton keeps the arriving table's shape
(real headers, real column widths) on screen for that window instead of a bare
"loading" line.
*/
const DATASET_TABLE_SKELETON_ROWS = 8;
const DATASET_TABLE_SKELETON_BAR_WIDTHS = [82, 54, 70, 46, 76, 60, 88, 52];

function createDatasetTableSkeletonBar(rowIndex, colIndex) {
  const bar = document.createElement("span");
  bar.className = "pi-table-skeleton-bar";
  const widths = DATASET_TABLE_SKELETON_BAR_WIDTHS;
  bar.style.width = `${widths[(rowIndex + colIndex * 3) % widths.length]}%`;
  return bar;
}

function setSkeletonTable() {
  if (!els.datasetTableSurface) return;
  els.datasetTableSurface.innerHTML = "";
  delete els.datasetTableSurface.dataset.emptyAddDataset;
  syncDatasetGroupByToolbar();
  syncDatasetActiveFiltersToolbar();

  const columns = getVisibleDatasetColumns();
  const group = document.createElement("div");
  group.className = "pi-table-group pi-table-skeleton";
  group.setAttribute("aria-busy", "true");
  group.setAttribute("aria-label", "Loading cached dataset list");

  const table = document.createElement("table");
  table.className = "pi-table";
  const tableWidth = Math.max(1, Math.round(getDatasetTableTotalWidth()));
  table.style.width = `${tableWidth}px`;
  table.style.minWidth = `${tableWidth}px`;

  const colgroup = document.createElement("colgroup");
  columns.forEach((col) => {
    const colEl = document.createElement("col");
    colEl.dataset.colKey = col.key;
    colEl.style.width = `${getDatasetTableWidth(col.key)}px`;
    colgroup.appendChild(colEl);
  });
  table.appendChild(colgroup);

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.dataset.colKey = col.key;
    const cell = document.createElement("div");
    cell.className = "pi-table-header-cell";
    const label = document.createElement("span");
    label.className = "pi-table-col-label";
    const labelText = document.createElement("span");
    labelText.className = "pi-table-col-label-text";
    labelText.textContent = col.label;
    label.appendChild(labelText);
    cell.appendChild(label);
    th.appendChild(cell);
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let rowIndex = 0; rowIndex < DATASET_TABLE_SKELETON_ROWS; rowIndex += 1) {
    const tr = document.createElement("tr");
    columns.forEach((col, colIndex) => {
      const td = document.createElement("td");
      td.appendChild(createDatasetTableSkeletonBar(rowIndex, colIndex));
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);

  group.appendChild(table);
  els.datasetTableSurface.appendChild(group);
}

function getDatasetName(row) {
  return toText(row?.[0]);
}

/**
 * How a formula reads in this table. One shared formatter serves this grid, the
 * Project Settings Dataset Types table, and the Dataset Viewer Formula field, so
 * the same formula never reads three ways. The dataset-type rows are the names
 * an unquoted formula can refer to; without them a name holding `-` or `/` -
 * "C 22 - CWOP DFM w/ Selected LDFs" - cannot be told from an expression.
 */
function displayDatasetFormula(formula) {
  const knownNames = state.datasetRows.map(getDatasetName).filter(Boolean);
  return formatDetailsFormulaText(formula, knownNames);
}

function getDatasetTypeRowByName(name) {
  const key = normalizeLookupKey(name);
  if (!key) return null;
  return state.datasetRows.find((row) => normalizeLookupKey(getDatasetName(row)) === key) || null;
}

function getInstanceDatasetName(item) {
  return toText(item?.name);
}

function getInstanceDatasetTypeName(item, instanceName = "") {
  return toText(item?.dataset_type) || instanceName;
}

function parseDatasetGeneratedFlag(value) {
  if (typeof value === "boolean") return value;
  const text = toText(value).toLowerCase();
  return text === "true" || text === "1" || text === "yes" || text === "y";
}

function normalizeDatasetSourceKind(value) {
  return toText(value).toLowerCase();
}

function getDatasetGenerated(row) {
  return parseDatasetGeneratedFlag(row?.[5]);
}

function getMethodType(row) {
  if (!state.selectedPath) return "None";
  if (normalizePath(cachedDatasetFilter.loadedPath).toLowerCase() !== normalizePath(state.selectedPath).toLowerCase()) {
    return "None";
  }
  return cachedDatasetFilter.methodTypesByName.get(normalizeLookupKey(getDatasetName(row))) || "None";
}

function getDatasetStatusLabel(needsReview) {
  return needsReview ? "Needs review" : "Updated";
}

function getDatasetStatus(record, instanceName = "") {
  const name = instanceName || record?.datasetName || getDatasetName(record?.row);
  const meta = record?.meta || getCachedDatasetMetadataByName(name) || getCachedDatasetMetadata(record?.row);
  return normalizeReviewStatus(meta?.status ?? record?.instance?.status ?? record?.status);
}

/**
 * Whether a row's Status reads Needs Review. Two things say so: the flag the
 * sidecar stores, and a linked Excel workbook that now holds numbers this
 * object has not loaded. The second is an observation of files no index
 * describes, so it only paints the column - nothing about it is stored, and
 * the row menu's Mark for review still reads the stored flag alone.
 */
function datasetNeedsReview(record, instanceName = "") {
  if (statusNeedsReview(getDatasetStatus(record, instanceName))) return true;
  // Temporary view's Status column answers a different question - whether the
  // type is in the index - so a link verdict has no place in it.
  if (isTemporaryViewActive()) return false;
  const name = instanceName || record?.datasetName || getDatasetName(record?.row);
  return !!getExcelLinkStatus(name)?.needsReview;
}

function getCachedDatasetMetadata(row) {
  if (!hasCachedDatasetMetadataForSelectedPath()) return null;
  const key = getCachedDatasetKey(getDatasetName(row));
  return key ? cachedDatasetFilter.metadataByName.get(key) || null : null;
}

function getCachedDatasetMetadataByName(name) {
  if (!hasCachedDatasetMetadataForSelectedPath()) return null;
  const key = getCachedDatasetKey(name);
  return key ? cachedDatasetFilter.metadataByName.get(key) || null : null;
}

function getDatasetColumn(key) {
  return DATASET_TABLE_COLUMNS.find((col) => col.key === key) || null;
}

function getOrderedDatasetColumns() {
  const known = new Set(DATASET_TABLE_COLUMNS.map((col) => col.key));
  const ordered = datasetTableView.columns.filter((key) => known.has(key));
  for (const col of DATASET_TABLE_COLUMNS) {
    if (!ordered.includes(col.key)) ordered.push(col.key);
  }
  datasetTableView.columns = ordered;
  return ordered.map(getDatasetColumn).filter(Boolean);
}

function getVisibleDatasetColumns() {
  const groupKeys = new Set(getDatasetGroupByKeys());
  return getOrderedDatasetColumns().filter((col) => !groupKeys.has(col.key));
}

function getDatasetGroupByKeys() {
  const raw = Array.isArray(datasetTableView.groupBy)
    ? datasetTableView.groupBy
    : [datasetTableView.groupBy];
  const keys = [];
  for (const key of raw) {
    const normalized = toText(key);
    if (!isDatasetColumnGroupable(normalized) || keys.includes(normalized)) continue;
    keys.push(normalized);
  }
  datasetTableView.groupBy = keys;
  return keys;
}

function applyDatasetGroupByKeys(keys) {
  datasetTableView.groupBy = (Array.isArray(keys) ? keys : [])
    .map(toText)
    .filter((key, index, list) => isDatasetColumnGroupable(key) && list.indexOf(key) === index);
  datasetTableView.collapsedGroups.clear();
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function addDatasetGroupByKey(key) {
  const normalized = toText(key);
  if (!isDatasetColumnGroupable(normalized)) return false;
  const keys = getDatasetGroupByKeys();
  if (keys.includes(normalized)) return true;
  applyDatasetGroupByKeys([...keys, normalized]);
  return true;
}

function removeDatasetGroupByKey(key) {
  const normalized = toText(key);
  const keys = getDatasetGroupByKeys();
  if (!keys.includes(normalized)) return false;
  applyDatasetGroupByKeys(keys.filter((item) => item !== normalized));
  return true;
}

function setDatasetGroupByKey(key) {
  const normalized = toText(key);
  if (!isDatasetColumnGroupable(normalized)) return;
  const keys = getDatasetGroupByKeys();
  const next = keys.includes(normalized)
    ? keys.filter((item) => item !== normalized)
    : [...keys, normalized];
  closeDatasetTableContextMenu();
  applyDatasetGroupByKeys(next);
}

function getDatasetCellValue(row, key) {
  const datasetName = getDatasetName(row);
  if (isTemporaryViewActive() && ["methodType", "lastModified", "created", "user"].includes(key)) {
    return "";
  }
  switch (key) {
    case "name":
    case "datasetTypeName":
      return datasetName;
    case "status":
      return getDatasetStatusLabel(datasetNeedsReview({ row }));
    case "dataFormat":
      return toText(row?.[1]);
    case "formula":
      return displayDatasetFormula(row?.[4]);
    case "category":
      return toText(row?.[2]);
    case "methodType":
      return berquistShermanDisplayLabel(getMethodType(row));
    case "lastModified":
      return getCachedDatasetMetadata(row)?.lastModified || "";
    case "created":
      return getCachedDatasetMetadata(row)?.created || "";
    case "user":
      return getCachedDatasetMetadata(row)?.user || "";
    default:
      return "";
  }
}

function getDatasetRecordCellValue(row, key, instance = null) {
  const instanceName = instance ? getInstanceDatasetName(instance) : getDatasetName(row);
  const datasetTypeName = instance ? getInstanceDatasetTypeName(instance, instanceName) : getDatasetName(row);
  const meta = instance ? getCachedDatasetMetadataByName(instanceName) : getCachedDatasetMetadata(row);
  if (isTemporaryViewActive() && ["methodType", "lastModified", "created", "user"].includes(key)) {
    return "";
  }
  switch (key) {
    case "name":
      return instanceName;
    case "datasetTypeName":
      return datasetTypeName;
    case "status":
      return getDatasetStatusLabel(datasetNeedsReview({ row, instance }, instanceName));
    case "dataFormat":
      return instance ? (toText(instance?.data_format) || toText(row?.[1])) : toText(row?.[1]);
    case "formula":
      return displayDatasetFormula(instance
        ? (meta?.formula || toText(instance?.formula) || toText(row?.[4]))
        : toText(row?.[4]));
    case "category":
      return datasetInstanceCategory(instance, row?.[2]);
    case "methodType":
      return berquistShermanDisplayLabel(
        instance?.method_type
        || cachedDatasetFilter.methodTypesByName.get(normalizeLookupKey(instanceName))
        || getMethodType(row),
      );
    case "lastModified":
      return meta?.lastModified || "";
    case "created":
      return meta?.created || "";
    case "user":
      return meta?.user || "";
    default:
      return "";
  }
}

function getDatasetFilterKey(value) {
  const text = toText(value);
  return text || DATASET_TABLE_BLANK_LABEL;
}

function compareTextValues(a, b) {
  return String(a || "").localeCompare(String(b || ""), undefined, {
    sensitivity: "base",
    numeric: true,
  });
}

function getDatasetRecordTimestamp(record, key) {
  const meta = record?.meta || getCachedDatasetMetadata(record?.row);
  const raw = key === "lastModified"
    ? meta?._lastModifiedTs
    : key === "created"
      ? meta?._createdTs
      : 0;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function compareTimestampValues(a, b, key, dir) {
  const left = getDatasetRecordTimestamp(a, key);
  const right = getDatasetRecordTimestamp(b, key);
  if (left && right && left !== right) return (left - right) * dir;
  if (left && !right) return -1;
  if (!left && right) return 1;
  return 0;
}

function buildDatasetRecord(row, rowIndex, instance = null) {
  const instanceName = instance ? getInstanceDatasetName(instance) : getDatasetName(row);
  const datasetTypeName = instance ? getInstanceDatasetTypeName(instance, instanceName) : getDatasetName(row);
  const typeRow = instance ? (getDatasetTypeRowByName(datasetTypeName) || row || []) : row;
  const values = {};
  for (const col of DATASET_TABLE_COLUMNS) {
    values[col.key] = getDatasetRecordCellValue(typeRow, col.key, instance);
  }
  const datasetName = values.name || instanceName || getDatasetName(typeRow);
  const sourceKind = instance ? toText(instance?.source_kind) : "";
  const generated = instance ? normalizeDatasetSourceKind(sourceKind) === "engine" : getDatasetGenerated(typeRow);
  const meta = getCachedDatasetMetadataByName(datasetName);
  const temporary = isTemporaryViewActive();
  return {
    row: typeRow,
    rowIndex,
    instance,
    datasetName,
    datasetTypeName,
    sourceKind,
    generated,
    values,
    meta,
    temporary,
    isIndexed: temporary && isDatasetRecordCached({ datasetName }),
  };
}

function getDatasetRecordValue(record, key) {
  return toText(record?.values?.[key] ?? getDatasetCellValue(record?.row, key));
}

function isDfmDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "dfm";
}

function isResultSelectionDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "result selection";
}

function isBornhuetterFergusonDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "bornhuetter ferguson";
}

function isCapeCodDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "cape cod";
}

function isBootstrapDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "bootstrap";
}

function isStochasticConsolidationDatasetRecord(record) {
  return normalizeLookupKey(getDatasetRecordValue(record, "methodType")) === "stochastic consolidation";
}

function getBerquistShermanRecordVariant(record) {
  return normalizeBerquistShermanVariant(
    getDatasetRecordValue(record, "methodType") || record?.sourceKind || record?.instance?.source_kind
  );
}

function isBerquistShermanDatasetRecord(record) {
  return !!getBerquistShermanRecordVariant(record);
}

function isMethodDatasetRecord(record) {
  // Every method type the index can report, without naming them one by one:
  // a row a method wrote carries something other than "None" here, and only
  // such a row has a review flag to set.
  const methodType = normalizeLookupKey(getDatasetRecordValue(record, "methodType"));
  return !!methodType && methodType !== "none";
}

function isDfmVectorDatasetRecord(record) {
  return (
    isDfmDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function isResultSelectionVectorDatasetRecord(record) {
  return (
    isResultSelectionDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function isBornhuetterFergusonVectorDatasetRecord(record) {
  return (
    isBornhuetterFergusonDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function isCapeCodVectorDatasetRecord(record) {
  return (
    isCapeCodDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function isBootstrapVectorDatasetRecord(record) {
  return (
    isBootstrapDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function isStochasticConsolidationVectorDatasetRecord(record) {
  return (
    isStochasticConsolidationDatasetRecord(record)
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
  );
}

function openDfmTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  const methodName = toText(record?.instance?.method_name) || datasetName;
  openDfmWindow(methodName, {
    methodType: getDatasetRecordValue(record, "methodType"),
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    outputDataset: datasetName,
  });
}

// Opening an existing method names no tab: the window layer applies the user's
// Default Tabs preference for that kind. Only the add-a-new-method handlers
// below pin Details, because a fresh method has nothing to show until its
// inputs are chosen.
function openResultSelectionTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  openResultSelectionWindow(datasetName, {
    methodType: getDatasetRecordValue(record, "methodType"),
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
}

function openBornhuetterFergusonTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  openBornhuetterFergusonWindow(datasetName, {
    methodType: getDatasetRecordValue(record, "methodType") || "Bornhuetter Ferguson",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
}

function openCapeCodTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  openCapeCodWindow(datasetName, {
    methodType: getDatasetRecordValue(record, "methodType") || "Cape Cod",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
}

function openBootstrapTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  openBootstrapWindow(datasetName, {
    methodType: getDatasetRecordValue(record, "methodType") || "Bootstrap",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
  });
}

function openStochasticConsolidationTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName || !state.selectedPath) return;
  openStochasticConsolidationWindow(datasetName, {
    methodType: getDatasetRecordValue(record, "methodType") || "Stochastic Consolidation",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
  });
}

function openBerquistShermanTabForDataset(record) {
  const datasetName = toText(record?.datasetName);
  const variant = getBerquistShermanRecordVariant(record);
  if (!datasetName || !variant || !state.selectedPath) return;
  const contract = getBerquistShermanContract(variant);
  openBerquistShermanWindow(datasetName, {
    variant,
    methodType: contract?.methodType,
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
}

function openDatasetRecordAsDataset(record) {
  if (!record) return;
  const temporaryView = isTemporaryViewActive();
  openDatasetWindow(record.datasetName, {
    datasetTypeName: getDatasetRecordValue(record, "datasetTypeName"),
    dataFormat: getDatasetRecordValue(record, "dataFormat"),
    methodType: getDatasetRecordValue(record, "methodType"),
    // The viewer owns source-based grid protection; only temporary views block all saves.
    readOnly: temporaryView,
    temporaryViewSessionId: temporaryView ? toText(state.temporaryDatasetSessionId) : "",
  });
}

function canAddDfmForDataset(record) {
  return (
    !!record
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "triangle"
    && ["", "none"].includes(normalizeLookupKey(getDatasetRecordValue(record, "methodType")))
  );
}

function addDfmForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a dataset before adding a DFM object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a DFM object.", true);
    return;
  }
  if (!canAddDfmForDataset(record)) {
    setStatus("DFM can be added only to triangle datasets with Method Type None.", true);
    return;
  }
  openDfmWindow(datasetName, {
    fresh: true,
    initialTab: "details",
    inputTriangle: datasetName,
    methodType: "DFM",
  });
  setStatus(`Opened DFM for ${datasetName}.`);
}

function canAddResultSelectionForDataset(record) {
  return (
    !!record
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "vector"
    && ["", "none"].includes(normalizeLookupKey(getDatasetRecordValue(record, "methodType")))
  );
}

function canAddBerquistShermanForDataset(record) {
  const originLength = Number(record?.meta?.originLength || record?.instance?.origin_length);
  const developmentLength = Number(record?.meta?.developmentLength || record?.instance?.development_length);
  return (
    !!record
    && normalizeLookupKey(getDatasetRecordValue(record, "dataFormat")) === "triangle"
    && ["", "none"].includes(normalizeLookupKey(getDatasetRecordValue(record, "methodType")))
    && originLength === 12
    && developmentLength === 12
  );
}

function addBerquistShermanForDataset(record, variant) {
  const datasetName = toText(record?.datasetName);
  const contract = getBerquistShermanContract(variant);
  if (!datasetName || !contract) {
    setStatus("Select an annual triangle before adding a Berquist Sherman object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Berquist Sherman object.", true);
    return;
  }
  if (!canAddBerquistShermanForDataset(record)) {
    setStatus("Berquist Sherman methods can be added only to annual triangles with Method Type None.", true);
    return;
  }
  openBerquistShermanWindow(datasetName, {
    fresh: true,
    initialTab: "details",
    inputTriangle: datasetName,
    variant: contract.variant,
    methodType: contract.methodType,
  });
  setStatus(`Opened ${contract.methodType} for ${datasetName}.`);
}

function addResultSelectionForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a vector dataset before adding a Result Selection object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Result Selection object.", true);
    return;
  }
  if (!canAddResultSelectionForDataset(record)) {
    setStatus("Result Selection can be added only to vector datasets with Method Type None.", true);
    return;
  }
  openResultSelectionWindow(datasetName, {
    initialTab: "details",
    methodType: "Result Selection",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
  setStatus(`Opened Result Selection for ${datasetName}.`);
}

function addBornhuetterFergusonForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a vector dataset before adding a Bornhuetter Ferguson object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Bornhuetter Ferguson object.", true);
    return;
  }
  if (!canAddResultSelectionForDataset(record)) {
    setStatus("Bornhuetter Ferguson can be added only to vector datasets with Method Type None.", true);
    return;
  }
  openBornhuetterFergusonWindow(datasetName, {
    initialTab: "details",
    methodType: "Bornhuetter Ferguson",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
  setStatus(`Opened Bornhuetter Ferguson for ${datasetName}.`);
}

function addCapeCodForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a vector dataset before adding a Cape Cod object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Cape Cod object.", true);
    return;
  }
  if (!canAddResultSelectionForDataset(record)) {
    setStatus("Cape Cod can be added only to vector datasets with Method Type None.", true);
    return;
  }
  openCapeCodWindow(datasetName, {
    initialTab: "details",
    methodType: "Cape Cod",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
    originLength: Number(record?.meta?.originLength) || undefined,
  });
  setStatus(`Opened Cape Cod for ${datasetName}.`);
}

function addBootstrapForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a vector dataset before adding a Bootstrap object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Bootstrap object.", true);
    return;
  }
  if (!canAddResultSelectionForDataset(record)) {
    setStatus("Bootstrap can be added only to vector datasets with Method Type None.", true);
    return;
  }
  openBootstrapWindow(datasetName, {
    initialTab: "details",
    methodType: "Bootstrap",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
  });
  setStatus(`Opened Bootstrap for ${datasetName}.`);
}

function addStochasticConsolidationForDataset(record) {
  const datasetName = toText(record?.datasetName);
  if (!datasetName) {
    setStatus("Select a vector dataset before adding a Stochastic Consolidation object.", true);
    return;
  }
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before adding a Stochastic Consolidation object.", true);
    return;
  }
  if (!canAddResultSelectionForDataset(record)) {
    setStatus("Stochastic Consolidation can be added only to vector datasets with Method Type None.", true);
    return;
  }
  openStochasticConsolidationWindow(datasetName, {
    initialTab: "details",
    methodType: "Stochastic Consolidation",
    outputType: getDatasetRecordValue(record, "datasetTypeName"),
    category: getDatasetRecordValue(record, "category"),
  });
  setStatus(`Opened Stochastic Consolidation for ${datasetName}.`);
}

function recordSelectedDfmObject(methodName) {
  const name = toText(methodName);
  if (!projectName || !state.selectedPath || !name) return;
  scheduleProjectUserPreferencesSave(projectName, {
    lastReservingClassPath: state.selectedPath,
    dfmObject: {
      methodName: name,
      outputVector: name,
      updated_at: new Date().toISOString(),
    },
  });
}

function measureDatasetTableText(text) {
  if (!state.datasetTableMeasureCanvas) {
    state.datasetTableMeasureCanvas = document.createElement("canvas");
  }
  const ctx = state.datasetTableMeasureCanvas.getContext?.("2d");
  if (!ctx) return String(text || "").length * 7;
  ctx.font = "12px Segoe UI, Arial, sans-serif";
  return ctx.measureText(String(text || "")).width;
}

function clampInitialDatasetTableWidth(width, col) {
  const minWidth = col?.minWidth || 80;
  const measured = Math.ceil(Number(width) || minWidth);
  return Math.max(minWidth, Math.min(DATASET_TABLE_AUTOFIT_MAX_WIDTH, measured));
}

function getDatasetStatusAutoFitWidth(col = getDatasetColumn("status")) {
  return Math.max(col?.minWidth || 52, 58);
}

function getInitialDatasetTableColumnWidth(col, rows = state.datasetRows) {
  if (!col) return 120;
  if (col.key === "status") return getDatasetStatusAutoFitWidth(col);
  let width = measureDatasetTableText(col.label) + DATASET_TABLE_AUTOFIT_HEADER_EXTRA_WIDTH;
  const sourceRows = Array.isArray(rows) ? rows : [];
  for (const row of sourceRows) {
    const value = getDatasetCellValue(row, col.key);
    if (!value) continue;
    width = Math.max(width, measureDatasetTableText(value) + DATASET_TABLE_AUTOFIT_CELL_EXTRA_WIDTH);
    if (width >= DATASET_TABLE_AUTOFIT_MAX_WIDTH) return DATASET_TABLE_AUTOFIT_MAX_WIDTH;
  }
  return clampInitialDatasetTableWidth(width, col);
}

function autoFitInitialDatasetTableWidths(rows = state.datasetRows) {
  for (const col of DATASET_TABLE_COLUMNS) {
    if (datasetTablePreferenceWidthKeys.has(col.key)) continue;
    datasetTableView.widths[col.key] = getInitialDatasetTableColumnWidth(col, rows);
  }
}

function buildDatasetTableRenderContext() {
  const sourceRecords = isTemporaryViewActive()
    ? state.datasetRows
      .filter((row) => getDatasetGenerated(row))
      .map((row, rowIndex) => buildDatasetRecord(row, rowIndex))
    : shouldUseCachedDatasetFilter()
    ? (Array.isArray(cachedDatasetFilter.instanceRows) ? cachedDatasetFilter.instanceRows : [])
      .map((item, rowIndex) => {
        const instanceName = getInstanceDatasetName(item);
        const datasetTypeName = getInstanceDatasetTypeName(item, instanceName);
        return buildDatasetRecord(getDatasetTypeRowByName(datasetTypeName) || [], rowIndex, item);
      })
    : state.datasetRows.map((row, rowIndex) => buildDatasetRecord(row, rowIndex));
  const records = sourceRecords.filter((record) => record.datasetName);
  const optionsByKey = new Map();
  const selectionsByKey = new Map();

  for (const col of DATASET_TABLE_COLUMNS) {
    if (!isDatasetColumnFilterable(col.key)) {
      optionsByKey.set(col.key, []);
      continue;
    }
    const seen = new Set();
    const options = [];
    for (const record of records) {
      const optionKey = getDatasetFilterKey(getDatasetRecordValue(record, col.key));
      if (seen.has(optionKey)) continue;
      seen.add(optionKey);
      options.push({
        key: optionKey,
        label: optionKey,
      });
    }
    options.sort((a, b) => {
      if (a.key === DATASET_TABLE_BLANK_LABEL) return 1;
      if (b.key === DATASET_TABLE_BLANK_LABEL) return -1;
      return compareTextValues(a.label, b.label);
    });
    optionsByKey.set(col.key, options);
    selectionsByKey.set(col.key, getDatasetFilterSelection(col.key, options));
  }

  return { records, optionsByKey, selectionsByKey };
}

function compareDatasetRecords(a, b) {
  const sortKey = toText(datasetTableView.sort?.key);
  const dir = datasetTableView.sort?.dir === "desc" ? -1 : 1;
  if (!getDatasetColumn(sortKey)) return (a?.rowIndex ?? 0) - (b?.rowIndex ?? 0);
  if (sortKey === "lastModified" || sortKey === "created") {
    const timestampCmp = compareTimestampValues(a, b, sortKey, dir);
    if (timestampCmp !== 0) return timestampCmp;
  } else {
    const cmp = compareTextValues(
      getDatasetRecordValue(a, sortKey),
      getDatasetRecordValue(b, sortKey)
    );
    if (cmp !== 0) return cmp * dir;
  }
  return (a?.rowIndex ?? 0) - (b?.rowIndex ?? 0);
}

function sortDatasetRecords(records) {
  const list = Array.isArray(records) ? records.slice() : [];
  if (!getDatasetColumn(datasetTableView.sort?.key)) return list;
  return list.sort(compareDatasetRecords);
}

function toggleDatasetTableSort(key) {
  if (!getDatasetColumn(key)) return;
  const currentKey = toText(datasetTableView.sort?.key);
  const currentDir = datasetTableView.sort?.dir === "desc" ? "desc" : "asc";
  if (currentKey === key && currentDir === "desc") {
    datasetTableView.sort = { key: "", dir: "asc" };
  } else {
    datasetTableView.sort = {
      key,
      dir: currentKey === key && currentDir === "asc" ? "desc" : "asc",
    };
  }
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function getSortIconSvg(dir) {
  const isDesc = dir === "desc";
  return isDesc
    ? `<svg class="pi-table-sort-icon" viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M6 9.5L2.2 4h7.6L6 9.5z"></path></svg>`
    : `<svg class="pi-table-sort-icon" viewBox="0 0 12 12" aria-hidden="true" focusable="false"><path d="M6 2.5L9.8 8H2.2L6 2.5z"></path></svg>`;
}

function getDatasetColumnOptions(key, context = null) {
  if (!isDatasetColumnFilterable(key)) return [];
  const cached = context?.optionsByKey?.get?.(key);
  if (cached) return cached;
  const seen = new Set();
  const options = [];
  const records = state.datasetRows.map((row, rowIndex) => buildDatasetRecord(row, rowIndex));
  for (const record of records) {
    const value = getDatasetRecordValue(record, key);
    const optionKey = getDatasetFilterKey(value);
    if (seen.has(optionKey)) continue;
    seen.add(optionKey);
    options.push({
      key: optionKey,
      label: optionKey,
    });
  }
  options.sort((a, b) => {
    if (a.key === DATASET_TABLE_BLANK_LABEL) return 1;
    if (b.key === DATASET_TABLE_BLANK_LABEL) return -1;
    return compareTextValues(a.label, b.label);
  });
  return options;
}

function getDatasetFilterSelection(key, options = getDatasetColumnOptions(key)) {
  if (!isDatasetColumnFilterable(key)) {
    datasetTableView.filters.delete(key);
    return new Set();
  }
  const optionKeys = new Set(options.map((opt) => opt.key));
  let selected = datasetTableView.filters.get(key);
  if (!(selected instanceof Set)) {
    selected = new Set();
    datasetTableView.filters.set(key, selected);
    return selected;
  }
  for (const selectedKey of Array.from(selected)) {
    if (!optionKeys.has(selectedKey)) selected.delete(selectedKey);
  }
  return selected;
}

function isDatasetColumnFilterActive(key, context = null) {
  if (!isDatasetColumnFilterable(key)) return false;
  const options = getDatasetColumnOptions(key, context);
  if (!options.length) return false;
  const selected = context?.selectionsByKey?.get?.(key) || getDatasetFilterSelection(key, options);
  if (!(selected instanceof Set) || selected.size === 0) return false;
  if (selected.size !== options.length) return true;
  return options.some((opt) => !selected.has(opt.key));
}

function rowMatchesDatasetTableFilters(record, context) {
  for (const col of DATASET_TABLE_COLUMNS) {
    if (!isDatasetColumnFilterable(col.key)) continue;
    const options = getDatasetColumnOptions(col.key, context);
    if (!options.length) continue;
    const selected = context?.selectionsByKey?.get?.(col.key) || getDatasetFilterSelection(col.key, options);
    if (!(selected instanceof Set) || selected.size === 0 || selected.size === options.length) continue;
    if (!selected.has(getDatasetFilterKey(getDatasetRecordValue(record, col.key)))) return false;
  }
  return true;
}

function getDatasetTableWidth(key) {
  const col = getDatasetColumn(key);
  const width = Number(datasetTableView.widths[key]);
  return Math.max(col?.minWidth || 80, Number.isFinite(width) ? width : col?.minWidth || 120);
}

function getDatasetTableTotalWidth() {
  return getVisibleDatasetColumns().reduce((sum, col) => sum + getDatasetTableWidth(col.key), 0);
}

function syncDatasetTableTotalWidth() {
  const width = Math.max(1, Math.round(getDatasetTableTotalWidth()));
  for (const table of els.datasetTableSurface?.querySelectorAll?.(".pi-table") || []) {
    table.style.width = `${width}px`;
    table.style.minWidth = `${width}px`;
  }
}

function setDatasetTableColumnWidth(key, width) {
  const col = getDatasetColumn(key);
  if (!col) return;
  const next = Math.max(col.minWidth || 80, Math.round(Number(width) || col.minWidth || 120));
  datasetTableView.widths[key] = next;
  for (const colEl of els.datasetTableSurface?.querySelectorAll?.(`col[data-col-key="${CSS.escape(key)}"]`) || []) {
    colEl.style.width = `${next}px`;
  }
  syncDatasetTableTotalWidth();
}

function getDatasetTableRecords(context) {
  const records = Array.isArray(context?.records) ? context.records : state.datasetRows.map((row, rowIndex) => buildDatasetRecord(row, rowIndex));
  return records.filter((item) => (
    item.datasetName
    && rowMatchesDatasetTableFilters(item, context)
  ));
}

function clearDatasetColumnDragIndicators() {
  for (const header of els.datasetTableSurface?.querySelectorAll?.(".pi-table th.pi-col-drag-before, .pi-table th.pi-col-drag-after") || []) {
    header.classList.remove("pi-col-drag-before", "pi-col-drag-after");
  }
}

function removeDatasetColumnDragImage() {
  state.datasetColumnDragImage?.remove?.();
  state.datasetColumnDragImage = null;
}

function setDatasetColumnDragImage(event, label) {
  removeDatasetColumnDragImage();
  if (!event.dataTransfer?.setDragImage) return;
  const ghost = document.createElement("div");
  ghost.className = "pi-table-column-drag-image";
  ghost.textContent = label || "Column";
  document.body.appendChild(ghost);
  state.datasetColumnDragImage = ghost;
  const rect = ghost.getBoundingClientRect();
  event.dataTransfer.setDragImage(ghost, Math.min(110, Math.max(24, rect.width / 2)), 15);
}

function getDatasetColumnDropPosition(event, targetHeader) {
  const rect = targetHeader?.getBoundingClientRect?.();
  if (!rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.width) || rect.width <= 0) return "before";
  return event.clientX > rect.left + rect.width / 2 ? "after" : "before";
}

function updateDatasetColumnDragIndicator(targetHeader, sourceKey, targetKey, position = "before") {
  clearDatasetColumnDragIndicators();
  if (!targetHeader || !sourceKey || !targetKey || sourceKey === targetKey) return;
  const columns = datasetTableView.columns.slice();
  const sourceIndex = columns.indexOf(sourceKey);
  const targetIndex = columns.indexOf(targetKey);
  if (sourceIndex < 0 || targetIndex < 0) return;
  targetHeader.classList.add(position === "after" ? "pi-col-drag-after" : "pi-col-drag-before");
}

function createDatasetTableHeaderCell(col, colIndex, context = null) {
  const th = document.createElement("th");
  th.dataset.colKey = col.key;
  th.addEventListener("dragover", (event) => {
    if (!hasDataTransferType(event.dataTransfer, DATASET_COLUMN_DRAG_TYPE)) return;
    event.preventDefault();
    updateDatasetColumnDragIndicator(
      th,
      event.dataTransfer?.getData(DATASET_COLUMN_DRAG_TYPE) || state.datasetTableColumnDragSourceKey || "",
      col.key,
      getDatasetColumnDropPosition(event, th)
    );
  });
  th.addEventListener("dragleave", () => th.classList.remove("pi-col-drag-before", "pi-col-drag-after"));
  th.addEventListener("drop", (event) => {
    const sourceKey = event.dataTransfer?.getData(DATASET_COLUMN_DRAG_TYPE) || "";
    clearDatasetColumnDragIndicators();
    if (!sourceKey || sourceKey === col.key) return;
    event.preventDefault();
    event.stopPropagation();
    const position = getDatasetColumnDropPosition(event, th);
    if (hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) {
      moveDatasetGroupedColumnToTable(sourceKey, col.key, position);
    } else {
      moveDatasetTableColumn(sourceKey, col.key, position);
    }
  });

  const cell = document.createElement("div");
  cell.className = "pi-table-header-cell";

  const label = document.createElement("span");
  label.className = "pi-table-col-label";
  label.title = "Click to sort. Drag to reorder columns.";
  label.draggable = true;
  const labelText = document.createElement("span");
  labelText.className = "pi-table-col-label-text";
  labelText.textContent = col.label;
  label.appendChild(labelText);
  const isSorted = datasetTableView.sort?.key === col.key;
  if (isSorted) {
    label.classList.add("is-sorted");
    label.insertAdjacentHTML("beforeend", getSortIconSvg(datasetTableView.sort?.dir));
  }
  label.addEventListener("click", (event) => {
    if (state.datasetTableColumnDragStarted) return;
    event.preventDefault();
    event.stopPropagation();
    toggleDatasetTableSort(col.key);
  });
  label.addEventListener("dragstart", (event) => {
    state.datasetTableColumnDragStarted = true;
    state.datasetTableColumnDragSourceKey = col.key;
    event.dataTransfer?.setData(DATASET_COLUMN_DRAG_TYPE, col.key);
    event.dataTransfer?.setData("text/plain", col.label);
    event.dataTransfer.effectAllowed = "move";
    setDatasetColumnDragImage(event, col.label);
  });
  label.addEventListener("dragend", () => {
    clearDatasetActiveFilterDropState();
    clearDatasetColumnDragIndicators();
    removeDatasetColumnDragImage();
    window.setTimeout(() => {
      state.datasetTableColumnDragStarted = false;
      state.datasetTableColumnDragSourceKey = "";
    }, 0);
  });
  cell.appendChild(label);

  if (isDatasetColumnFilterable(col.key)) {
    const filterBtn = document.createElement("button");
    filterBtn.type = "button";
    filterBtn.className = "pi-table-filter-btn";
    filterBtn.title = `${col.label} Filter`;
    filterBtn.classList.toggle("active", isDatasetColumnFilterActive(col.key, context));
    filterBtn.innerHTML = `
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <path d="M2 3h12L9.5 8v4l-3 1V8z"></path>
      </svg>
    `;
    filterBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleDatasetTableFilterPopover(col.key, filterBtn);
    });
    cell.appendChild(filterBtn);
  }

  const resizer = document.createElement("div");
  resizer.className = "pi-table-col-resizer";
  resizer.title = "Resize column";
  resizer.addEventListener("mousedown", (event) => startDatasetTableColumnResize(event, col.key));
  resizer.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    resetDatasetTableColumnDefaultWidth(col.key);
  });
  cell.appendChild(resizer);
  th.appendChild(cell);
  return th;
}

function getDatasetStatusIconSvg(needsReview) {
  // The shared glyphs, so the Excel Link Manager's Status column reads the same.
  return reviewStatusIconSvg(needsReview === true);
}

function getTemporaryDatasetStatusIconSvg(isIndexed) {
  return `
    <svg class="pi-status-icon ${isIndexed ? "temp-indexed" : "temp-unindexed"}" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
      <circle class="pi-status-stroke" cx="9" cy="9" r="7"></circle>
      <path class="pi-status-stroke" d="m5.5 9 2.2 2.2 4.8-4.8"></path>
    </svg>
  `;
}

function appendDatasetStatusCell(td, item) {
  if (isTemporaryViewActive()) {
    const isIndexed = !!item?.isIndexed;
    const wrap = document.createElement("span");
    wrap.className = `pi-status-cell ${isIndexed ? "temp-indexed" : "temp-unindexed"}`;
    wrap.title = isIndexed
      ? "Dataset is already listed in index.json."
      : "Dataset is not listed in index.json.";
    wrap.setAttribute("aria-label", isIndexed
      ? "Dataset is listed in index.json"
      : "Dataset is not listed in index.json");
    wrap.innerHTML = getTemporaryDatasetStatusIconSvg(isIndexed);
    td.appendChild(wrap);
    return;
  }
  const status = getDatasetStatus(item);
  const needsReview = datasetNeedsReview(item);
  const label = getDatasetStatusLabel(needsReview);
  const excelSentence = getExcelLinkStatusSentence(item?.datasetName || getDatasetName(item?.row));
  const wrap = document.createElement("span");
  wrap.className = `pi-status-cell ${needsReview ? "warning" : "updated"}`;
  wrap.title = [
    statusNeedsReview(status)
      ? "Needs review because an input dependency was updated after this method output, or because it was marked for review."
      : excelSentence ? "" : "Dataset is updated.",
    excelSentence,
  ].filter(Boolean).join("\n");
  wrap.setAttribute("aria-label", label);
  wrap.innerHTML = getDatasetStatusIconSvg(needsReview);
  td.appendChild(wrap);
}

function createDatasetRecordRow(item, columns) {
  state.datasetTableVisibleRecords.push(item);
  const tr = document.createElement("tr");
  const recordKey = getDatasetRecordKey(item);
  if (recordKey) {
    tr.dataset.recordKey = recordKey;
    const selected = datasetTableSelection.selectedKeys.has(recordKey);
    tr.classList.toggle("selected", selected);
    tr.classList.toggle("multi", selected && datasetTableSelection.selectedKeys.size > 1);
    tr.classList.toggle("active", isActiveDatasetSelectionKey(recordKey));
    tr.setAttribute("aria-selected", selected ? "true" : "false");
  }
  for (const col of columns) {
    const value = getDatasetRecordValue(item, col.key);
    const td = document.createElement("td");
    if (col.key === "status") {
      td.className = "pi-table-status-td";
      appendDatasetStatusCell(td, item);
      tr.appendChild(td);
      continue;
    }
    const text = document.createElement("span");
    text.className = "pi-table-cell-text";
    text.textContent = value;
    td.appendChild(text);
    tr.appendChild(td);
  }
  tr.addEventListener("dblclick", () => openDatasetRecord(item));
  tr.addEventListener("click", (event) => {
    applyDatasetRowSelection(item, event);
    focusDatasetTableSurface();
  });
  tr.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!recordKey) return;
    if (!datasetTableSelection.selectedKeys.has(recordKey)) {
      datasetTableSelection.selectedKeys.clear();
      datasetTableSelection.selectedKeys.add(recordKey);
      datasetTableSelection.anchorKey = recordKey;
    }
    datasetTableSelection.activeKey = recordKey;
    syncDatasetTableSelectionDom();
    focusDatasetTableSurface();
    showDatasetRowContextMenu(recordKey, event.clientX, event.clientY);
  });
  return tr;
}

function getDatasetGroupId(parts) {
  return JSON.stringify(parts.map((part) => [part.key, part.valueKey]));
}

function createDatasetGroupRow(part, depth, columns) {
  const groupId = getDatasetGroupId(part.path);
  const tr = createTableGroupRow({
    text: `${part.label}: ${part.valueLabel}`,
    colSpan: columns.length,
    collapsed: datasetTableView.collapsedGroups.has(groupId),
    depth,
    count: depth === 0 ? part.records.length : null,
    onToggle: () => {
      if (datasetTableView.collapsedGroups.has(groupId)) datasetTableView.collapsedGroups.delete(groupId);
      else datasetTableView.collapsedGroups.add(groupId);
      saveDatasetTablePreferences();
      renderDatasetTable();
    },
    onContextMenu: (event) => showDatasetGroupContextMenu(groupId, event.clientX, event.clientY),
  });
  tr.dataset.groupId = groupId;
  tr.dataset.groupDepth = String(depth);
  return tr;
}

function buildDatasetGroupParts(records, groupKeys, depth = 0, path = []) {
  const groupKey = groupKeys[depth];
  const col = getDatasetColumn(groupKey);
  if (!col) return [];
  const groups = new Map();
  for (const record of records) {
    const valueKey = getDatasetFilterKey(getDatasetRecordValue(record, groupKey));
    if (!groups.has(valueKey)) groups.set(valueKey, []);
    groups.get(valueKey).push(record);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => {
      if (a === DATASET_TABLE_BLANK_LABEL) return 1;
      if (b === DATASET_TABLE_BLANK_LABEL) return -1;
      return compareTextValues(a, b);
    })
    .map(([valueKey, groupRecords]) => ({
      key: groupKey,
      label: col.label,
      valueKey,
      valueLabel: valueKey,
      records: groupRecords,
      path: [...path, { key: groupKey, valueKey }],
    }));
}

function appendGroupedDatasetRows(tbody, records, groupKeys, columns, depth = 0, path = []) {
  if (depth >= groupKeys.length) {
    for (const item of sortDatasetRecords(records)) {
      tbody.appendChild(createDatasetRecordRow(item, columns));
    }
    return;
  }
  for (const part of buildDatasetGroupParts(records, groupKeys, depth, path)) {
    tbody.appendChild(createDatasetGroupRow(part, depth, columns));
    const groupId = getDatasetGroupId(part.path);
    if (datasetTableView.collapsedGroups.has(groupId)) continue;
    appendGroupedDatasetRows(tbody, part.records, groupKeys, columns, depth + 1, part.path);
  }
}

function createDatasetTable(records, context = null) {
  state.datasetTableVisibleRecords = [];
  const group = document.createElement("div");
  group.className = "pi-table-group";

  const table = document.createElement("table");
  table.className = "pi-table";
  const tableWidth = Math.max(1, Math.round(getDatasetTableTotalWidth()));
  table.style.width = `${tableWidth}px`;
  table.style.minWidth = `${tableWidth}px`;
  const colgroup = document.createElement("colgroup");
  const columns = getVisibleDatasetColumns();
  columns.forEach((col) => {
    const colEl = document.createElement("col");
    colEl.dataset.colKey = col.key;
    colEl.style.width = `${getDatasetTableWidth(col.key)}px`;
    colgroup.appendChild(colEl);
  });
  table.appendChild(colgroup);

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  columns.forEach((col, colIndex) => headerRow.appendChild(createDatasetTableHeaderCell(col, colIndex, context)));
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  if (!records.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.className = "pi-table-empty";
    td.colSpan = columns.length;
    td.textContent = isTemporaryViewActive()
      ? "No data-engine datasets match the selected table filters."
      : "No cached datasets match the selected table filters.";
    tr.appendChild(td);
    tbody.appendChild(tr);
  } else {
    const groupKeys = getDatasetGroupByKeys();
    if (groupKeys.length) appendGroupedDatasetRows(tbody, records, groupKeys, columns);
    else for (const item of sortDatasetRecords(records)) tbody.appendChild(createDatasetRecordRow(item, columns));
  }
  syncDatasetGroupByToolbar();
  syncDatasetActiveFiltersToolbar(context);
  pruneDatasetTableSelection();
  syncDatasetTableSelectionDom();
  table.appendChild(tbody);
  group.appendChild(table);
  return group;
}

function getDatasetColumnInsertIndex(columns, sourceKey, targetKey, position = "before") {
  const withoutSource = columns.filter((key) => key !== sourceKey);
  const targetIndex = withoutSource.indexOf(targetKey);
  if (targetIndex < 0) return -1;
  return targetIndex + (position === "after" ? 1 : 0);
}

function moveDatasetTableColumn(sourceKey, targetKey, position = "before") {
  const columns = datasetTableView.columns.slice();
  if (!columns.includes(sourceKey) || !columns.includes(targetKey) || sourceKey === targetKey) return;
  const next = columns.filter((key) => key !== sourceKey);
  const insertIndex = getDatasetColumnInsertIndex(columns, sourceKey, targetKey, position);
  if (insertIndex < 0) return;
  next.splice(insertIndex, 0, sourceKey);
  datasetTableView.columns = next;
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function moveDatasetGroupedColumnToTable(sourceKey, targetKey, position = "before") {
  const normalized = toText(sourceKey);
  if (!getDatasetGroupByKeys().includes(normalized) || !getDatasetColumn(targetKey) || normalized === targetKey) return;
  const columns = datasetTableView.columns.slice();
  if (!columns.includes(normalized)) columns.push(normalized);
  const next = columns.filter((key) => key !== normalized);
  const insertIndex = getDatasetColumnInsertIndex(columns, normalized, targetKey, position);
  if (insertIndex < 0) return;
  next.splice(insertIndex, 0, normalized);
  datasetTableView.columns = next;
  datasetTableView.groupBy = getDatasetGroupByKeys().filter((key) => key !== normalized);
  datasetTableView.collapsedGroups.clear();
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function startDatasetTableColumnResize(event, key) {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  closeDatasetTableFilterPopover();
  const startX = event.clientX;
  const startWidth = getDatasetTableWidth(key);
  document.body.classList.add("pi-resizing-table-column");

  const onMove = (moveEvent) => {
    setDatasetTableColumnWidth(key, startWidth + moveEvent.clientX - startX);
  };
  const onUp = () => {
    document.body.classList.remove("pi-resizing-table-column");
    document.removeEventListener("mousemove", onMove, true);
    document.removeEventListener("mouseup", onUp, true);
    datasetTablePreferenceWidthKeys.add(key);
    saveDatasetTablePreferences();
  };
  document.addEventListener("mousemove", onMove, true);
  document.addEventListener("mouseup", onUp, true);
}

function resetDatasetTableColumnDefaultWidth(key) {
  const col = getDatasetColumn(key);
  if (!col) return;
  const defaultWidth = Number(DATASET_TABLE_DEFAULT_WIDTHS?.[key]);
  const width = Number.isFinite(defaultWidth) ? defaultWidth : col.minWidth || 120;
  setDatasetTableColumnWidth(key, width);
  datasetTablePreferenceWidthKeys.add(key);
  saveDatasetTablePreferences();
}

function renderDatasetTable() {
  if (!els.datasetTableSurface) return;
  state.datasetTableVisibleRecords = [];
  delete els.datasetTableSurface.dataset.emptyAddDataset;
  if (!state.datasetRows.length) {
    cachedDatasetFilter.visibleCount = 0;
    syncCachedDatasetToolbar();
    els.datasetTableSurface.innerHTML = "";
    pruneDatasetTableSelection();
    setEmptyTable("No dataset types are defined for this project.");
    return;
  }
  if (!state.selectedPath) {
    cachedDatasetFilter.visibleCount = 0;
    syncCachedDatasetToolbar();
    els.datasetTableSurface.innerHTML = "";
    pruneDatasetTableSelection();
    setEmptyTable(isTemporaryViewActive()
      ? "Select a reserving class path to show data-engine datasets."
      : "Select a reserving class path to show cached datasets.");
    return;
  }
  if (state.selectedPath) {
    if (cachedDatasetFilter.loading) {
      cachedDatasetFilter.visibleCount = 0;
      syncCachedDatasetToolbar();
      els.datasetTableSurface.innerHTML = "";
      pruneDatasetTableSelection();
      setSkeletonTable();
      return;
    }
    if (cachedDatasetFilter.error) {
      cachedDatasetFilter.visibleCount = 0;
      syncCachedDatasetToolbar();
      els.datasetTableSurface.innerHTML = "";
      pruneDatasetTableSelection();
      setEmptyTable(cachedDatasetFilter.error);
      return;
    }
    if (!shouldUseCachedDatasetFilter()) {
      void loadCachedDatasetFilterForSelectedPath();
      cachedDatasetFilter.visibleCount = 0;
      syncCachedDatasetToolbar();
      els.datasetTableSurface.innerHTML = "";
      pruneDatasetTableSelection();
      setSkeletonTable();
      return;
    }
    if (!isTemporaryViewActive() && cachedDatasetFilter.names.size === 0) {
      cachedDatasetFilter.visibleCount = 0;
      syncCachedDatasetToolbar();
      els.datasetTableSurface.innerHTML = "";
      pruneDatasetTableSelection();
      setEmptyTable("No dataset found in this path.", { allowAddDataset: true });
      return;
    }
  }

  const context = buildDatasetTableRenderContext();
  const records = getDatasetTableRecords(context);
  cachedDatasetFilter.visibleCount = isTemporaryViewActive()
    ? records.length
    : records.filter(isDatasetRecordCached).length;
  syncCachedDatasetToolbar();
  if (!records.length) {
    const fragment = document.createDocumentFragment();
    fragment.appendChild(createDatasetTable([], context));
    els.datasetTableSurface.replaceChildren(fragment);
    return;
  }

  const fragment = document.createDocumentFragment();
  fragment.appendChild(createDatasetTable(records, context));
  els.datasetTableSurface.replaceChildren(fragment);
}

function positionFixedMenu(el, x, y) {
  if (!el) return;
  el.style.left = `${Math.round(x)}px`;
  el.style.top = `${Math.round(y)}px`;
  const rect = el.getBoundingClientRect();
  const pad = 8;
  const left = Math.max(pad, Math.min(rect.left, window.innerWidth - rect.width - pad));
  const top = Math.max(pad, Math.min(rect.top, window.innerHeight - rect.height - pad));
  el.style.left = `${Math.round(left)}px`;
  el.style.top = `${Math.round(top)}px`;
}

function positionContextSubmenus(menu) {
  if (!menu) return;
  const pad = 8;
  for (const submenu of menu.querySelectorAll(".pi-context-submenu")) {
    const panel = Array.from(submenu.children).find((child) => child.classList?.contains("pi-context-submenu-menu"));
    if (!panel) continue;
    panel.style.left = "";
    panel.style.top = "";
    panel.style.visibility = "hidden";
    panel.style.display = "block";
    const triggerRect = submenu.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    panel.style.display = "";
    panel.style.visibility = "";

    const maxLeft = Math.max(pad, window.innerWidth - panelRect.width - pad);
    const preferredLeft = triggerRect.right + 4;
    const flippedLeft = triggerRect.left - panelRect.width - 4;
    const viewportLeft = preferredLeft <= maxLeft || flippedLeft < pad
      ? Math.min(preferredLeft, maxLeft)
      : flippedLeft;
    const maxTop = Math.max(pad, window.innerHeight - panelRect.height - pad);
    const viewportTop = Math.max(pad, Math.min(triggerRect.top - 4, maxTop));
    panel.style.left = `${Math.round(viewportLeft - triggerRect.left)}px`;
    panel.style.top = `${Math.round(viewportTop - triggerRect.top)}px`;
  }
}

function closeDatasetTableContextMenu() {
  els.datasetTableContextMenu?.classList?.remove("open");
  els.datasetTableContextMenu?.setAttribute("aria-hidden", "true");
}

function closeDatasetGroupContextMenu() {
  els.datasetGroupContextMenu?.classList?.remove("open");
  els.datasetGroupContextMenu?.setAttribute("aria-hidden", "true");
  state.datasetGroupContextId = "";
}

function closeDatasetRowContextMenu() {
  els.datasetRowContextMenu?.classList?.remove("open");
  els.datasetRowContextMenu?.setAttribute("aria-hidden", "true");
  state.datasetRowContextKey = "";
}

function showDatasetTableContextMenu(x, y) {
  const menu = els.datasetTableContextMenu;
  if (!menu) return;
  closeDatasetTableFilterPopover();
  closeDatasetGroupContextMenu();
  closeDatasetRowContextMenu();
  const groupKeys = getDatasetGroupByKeys();
  for (const item of menu.querySelectorAll("[data-group-key]")) {
    item.classList.toggle("active", groupKeys.includes(toText(item.dataset.groupKey)));
  }
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  positionFixedMenu(menu, x, y);
  positionContextSubmenus(menu);
}

function showDatasetGroupContextMenu(groupId, x, y) {
  const menu = els.datasetGroupContextMenu;
  if (!menu || !groupId) return;
  state.datasetGroupContextId = groupId;
  closeDatasetTableContextMenu();
  closeDatasetRowContextMenu();
  closeDatasetTableFilterPopover();
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  positionFixedMenu(menu, x, y);
}

function showDatasetRowContextMenu(recordKey, x, y, options = {}) {
  const menu = els.datasetRowContextMenu;
  const emptyContext = !!options.emptyContext;
  const temporaryView = isTemporaryViewActive();
  if (!menu || (!recordKey && !emptyContext)) return;
  state.datasetRowContextKey = recordKey || "";
  closeDatasetTableContextMenu();
  closeDatasetGroupContextMenu();
  closeDatasetTableFilterPopover();
  const viewItem = menu.querySelector("[data-row-action='view']");
  const viewRecord = emptyContext ? null : getDatasetRowViewRecord();
  if (viewItem) viewItem.disabled = emptyContext || !viewRecord;
  const makePermanentItem = menu.querySelector("[data-row-action='make-permanent']");
  if (makePermanentItem) {
    const canMakePermanent = temporaryView && !!viewRecord && !viewRecord.isIndexed;
    makePermanentItem.hidden = !temporaryView;
    makePermanentItem.disabled = !canMakePermanent;
    makePermanentItem.title = canMakePermanent
      ? "Generate and save this dataset to the selected reserving class."
      : "Dataset is already saved in the selected reserving class.";
  }
  const showAsVectorItem = menu.querySelector("[data-row-action='show-as-vector']");
  if (showAsVectorItem) {
    const showAsVector = !temporaryView && !!viewRecord && (
      isDfmVectorDatasetRecord(viewRecord)
      || isResultSelectionVectorDatasetRecord(viewRecord)
      || isBornhuetterFergusonVectorDatasetRecord(viewRecord)
      || isCapeCodVectorDatasetRecord(viewRecord)
      || isBootstrapVectorDatasetRecord(viewRecord)
      || isStochasticConsolidationVectorDatasetRecord(viewRecord)
    );
    showAsVectorItem.hidden = !showAsVector;
    showAsVectorItem.disabled = !showAsVector;
  }
  const viewAsTriangleItem = menu.querySelector("[data-row-action='view-as-triangle']");
  if (viewAsTriangleItem) {
    const viewAsTriangle = !temporaryView && !!viewRecord
      && normalizeLookupKey(getDatasetRecordValue(viewRecord, "dataFormat")) === "triangle";
    viewAsTriangleItem.hidden = !viewAsTriangle;
    viewAsTriangleItem.disabled = !viewAsTriangle;
  }
  const addDfmItem = menu.querySelector("[data-row-action='add-dfm']");
  if (addDfmItem) {
    const canAdd = !temporaryView && !emptyContext && canAddDfmForDataset(viewRecord);
    addDfmItem.hidden = temporaryView || emptyContext;
    addDfmItem.disabled = !canAdd;
    addDfmItem.title = canAdd ? "" : "DFM can be added only to triangle datasets with Method Type None.";
  }
  const addResultSelectionItem = menu.querySelector("[data-row-action='add-result-selection']");
  if (addResultSelectionItem) {
    const canAdd = !temporaryView && !emptyContext && canAddResultSelectionForDataset(viewRecord);
    addResultSelectionItem.hidden = temporaryView || emptyContext;
    addResultSelectionItem.disabled = !canAdd;
    addResultSelectionItem.title = canAdd ? "" : "Result Selection can be added only to vector datasets with Method Type None.";
  }
  const addBornhuetterFergusonItem = menu.querySelector("[data-row-action='add-bornhuetter-ferguson']");
  if (addBornhuetterFergusonItem) {
    const canAdd = !temporaryView && !emptyContext && canAddResultSelectionForDataset(viewRecord);
    addBornhuetterFergusonItem.hidden = temporaryView || emptyContext;
    addBornhuetterFergusonItem.disabled = !canAdd;
    addBornhuetterFergusonItem.title = canAdd ? "" : "Bornhuetter Ferguson can be added only to vector datasets with Method Type None.";
  }
  const addCapeCodItem = menu.querySelector("[data-row-action='add-cape-cod']");
  if (addCapeCodItem) {
    const canAdd = !temporaryView && !emptyContext && canAddResultSelectionForDataset(viewRecord);
    addCapeCodItem.hidden = temporaryView || emptyContext;
    addCapeCodItem.disabled = !canAdd;
    addCapeCodItem.title = canAdd ? "" : "Cape Cod can be added only to vector datasets with Method Type None.";
  }
  const addBootstrapItem = menu.querySelector("[data-row-action='add-bootstrap']");
  if (addBootstrapItem) {
    const canAdd = !temporaryView && !emptyContext && canAddResultSelectionForDataset(viewRecord);
    addBootstrapItem.hidden = temporaryView || emptyContext;
    addBootstrapItem.disabled = !canAdd;
    addBootstrapItem.title = canAdd ? "" : "Bootstrap can be added only to vector datasets with Method Type None.";
  }
  const addConsolidationItem = menu.querySelector("[data-row-action='add-stochastic-consolidation']");
  if (addConsolidationItem) {
    const canAdd = !temporaryView && !emptyContext && canAddResultSelectionForDataset(viewRecord);
    addConsolidationItem.hidden = temporaryView || emptyContext;
    addConsolidationItem.disabled = !canAdd;
    addConsolidationItem.title = canAdd
      ? ""
      : "Stochastic Consolidation can be added only to vector datasets with Method Type None.";
  }
  for (const variant of BERQUIST_SHERMAN_VARIANTS) {
    const addBerquistShermanItem = menu.querySelector(`[data-row-action='add-berquist-sherman-${variant}']`);
    if (!addBerquistShermanItem) continue;
    const canAdd = !temporaryView && !emptyContext && canAddBerquistShermanForDataset(viewRecord);
    addBerquistShermanItem.hidden = temporaryView || emptyContext;
    addBerquistShermanItem.disabled = !canAdd;
    addBerquistShermanItem.title = canAdd
      ? ""
      : "Berquist Sherman methods can be added only to annual triangles with Method Type None.";
  }
  // Only a method output has a review flag, so a selection that holds none
  // shows neither item. Marking for review is offered only when every method
  // row in the selection is already up to date; a selection that mixes the
  // two states -- or is entirely flagged -- offers clearing the flag instead,
  // so one click lands the whole selection on the same status.
  const reviewRecords = temporaryView || emptyContext
    ? []
    : getDatasetRowActionRecords().filter(isMethodDatasetRecord);
  const offerMarkForReview = reviewRecords.length > 0
    && reviewRecords.every((record) => getDatasetStatus(record) === STATUS_CURRENT);
  const markForReviewItem = menu.querySelector("[data-row-action='mark-for-review']");
  if (markForReviewItem) markForReviewItem.hidden = !offerMarkForReview;
  const setReviewedItem = menu.querySelector("[data-row-action='set-reviewed']");
  if (setReviewedItem) setReviewedItem.hidden = offerMarkForReview || !reviewRecords.length;
  const selectedCount = emptyContext ? 0 : getSelectedDatasetRecords().length;
  const deleteItem = menu.querySelector("[data-row-action='delete']");
  if (deleteItem) {
    deleteItem.hidden = temporaryView;
    deleteItem.disabled = temporaryView || selectedCount === 0;
  }
  const addSubmenu = menu.querySelector(".pi-context-submenu");
  if (addSubmenu) addSubmenu.hidden = temporaryView;
  menu.classList.add("open");
  menu.setAttribute("aria-hidden", "false");
  positionFixedMenu(menu, x, y);
  positionContextSubmenus(menu);
}

function canShowDatasetEmptyAddContextMenu() {
  return (
    els.datasetTableSurface?.dataset?.emptyAddDataset === "1"
    && !!projectName
    && !!state.selectedPath
  );
}

function showDatasetEmptyAddContextMenu(x, y) {
  if (!canShowDatasetEmptyAddContextMenu()) return false;
  datasetTableSelection.selectedKeys.clear();
  datasetTableSelection.anchorKey = "";
  datasetTableSelection.activeKey = "";
  syncDatasetTableSelectionDom();
  focusDatasetTableSurface();
  showDatasetRowContextMenu("", x, y, { emptyContext: true });
  return true;
}

function parseDatasetGroupId(groupId) {
  try {
    const parsed = JSON.parse(groupId);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => ({
        key: toText(Array.isArray(item) ? item[0] : item?.key),
        valueKey: toText(Array.isArray(item) ? item[1] : item?.valueKey),
      }))
      .filter((item) => item.key && item.valueKey);
  } catch {
    return [];
  }
}

function collectDatasetSameLevelGroupIds(records, groupKeys, depth, targetDepth, path, out) {
  if (depth > targetDepth || depth >= groupKeys.length) return;
  for (const part of buildDatasetGroupParts(records, groupKeys, depth, path)) {
    const id = getDatasetGroupId(part.path);
    if (depth === targetDepth) out.push(id);
    else collectDatasetSameLevelGroupIds(part.records, groupKeys, depth + 1, targetDepth, part.path, out);
  }
}

function getDatasetSameLevelGroupIds(groupId) {
  const path = parseDatasetGroupId(groupId);
  if (!path.length) return [];
  const groupKeys = getDatasetGroupByKeys();
  const targetDepth = path.length - 1;
  if (targetDepth < 0 || targetDepth >= groupKeys.length) return [];
  const context = buildDatasetTableRenderContext();
  const records = getDatasetTableRecords(context);
  const ids = [];
  collectDatasetSameLevelGroupIds(records, groupKeys, 0, targetDepth, [], ids);
  return ids;
}

function applyDatasetGroupContextAction(action) {
  const ids = getDatasetSameLevelGroupIds(state.datasetGroupContextId);
  if (action === "collapse-all") {
    for (const id of ids) datasetTableView.collapsedGroups.add(id);
  } else if (action === "expand-all") {
    for (const id of ids) datasetTableView.collapsedGroups.delete(id);
  }
  closeDatasetGroupContextMenu();
  saveDatasetTablePreferences();
  renderDatasetTable();
}

function openDatasetRecord(record) {
  if (!record) return;
  if (isTemporaryViewActive()) {
    openDatasetRecordAsDataset(record);
    return;
  }
  if (isDfmDatasetRecord(record)) {
    openDfmTabForDataset(record);
    return;
  }
  if (isResultSelectionDatasetRecord(record)) {
    openResultSelectionTabForDataset(record);
    return;
  }
  if (isBornhuetterFergusonDatasetRecord(record)) {
    openBornhuetterFergusonTabForDataset(record);
    return;
  }
  if (isCapeCodDatasetRecord(record)) {
    openCapeCodTabForDataset(record);
    return;
  }
  if (isBootstrapDatasetRecord(record)) {
    openBootstrapTabForDataset(record);
    return;
  }
  if (isStochasticConsolidationDatasetRecord(record)) {
    openStochasticConsolidationTabForDataset(record);
    return;
  }
  if (isBerquistShermanDatasetRecord(record)) {
    openBerquistShermanTabForDataset(record);
    return;
  }
  openDatasetRecordAsDataset(record);
}

function getDatasetRowActionRecords() {
  const contextRecord = getDatasetRecordByKey(state.datasetRowContextKey);
  const selectedRecords = getSelectedDatasetRecords();
  if (contextRecord && selectedRecords.some((record) => getDatasetRecordKey(record) === state.datasetRowContextKey)) {
    return selectedRecords;
  }
  return contextRecord ? [contextRecord] : selectedRecords;
}

function getDatasetRowViewRecord() {
  return getDatasetRecordByKey(state.datasetRowContextKey) || getSelectedDatasetRecords()[0] || null;
}

function buildAddDatasetTriPayload(record, lengths) {
  const originLen = Number(lengths?.originLen) || 12;
  const devLen = Number(lengths?.devLen) || 12;
  return {
    Path: state.selectedPath,
    TriangleName: record.datasetName,
    DatasetTypeName: record.datasetName,
    ProjectName: projectName,
    InstanceName: record.datasetName,
    Cumulative: true,
    Calendar: false,
    OriginLength: originLen,
    DevelopmentLength: devLen,
  };
}

function buildMakePermanentDatasetPayload(record, lengths) {
  const originLen = Number(lengths?.originLen) || 12;
  const devLen = Number(lengths?.devLen) || 12;
  const datasetTypeName = toText(record?.datasetTypeName || record?.datasetName);
  const dataFormat = normalizeLookupKey(getDatasetRecordValue(record, "dataFormat"));
  const base = {
    Path: state.selectedPath,
    DatasetTypeName: datasetTypeName,
    ProjectName: projectName,
    InstanceName: record.datasetName,
    Cumulative: true,
    Calendar: false,
  };
  if (dataFormat === "vector") {
    return {
      route: "/arcrho/vec/refresh",
      body: {
        ...base,
        VectorName: datasetTypeName,
        PeriodLength: originLen,
      },
    };
  }
  return {
    route: "/arcrho/tri/refresh",
    body: {
      ...base,
      TriangleName: datasetTypeName,
      OriginLength: originLen,
      DevelopmentLength: devLen,
    },
  };
}

async function getAddDatasetDefaultLengths() {
  return { originLen: 12, devLen: 12 };
}

async function refreshDatasetsAfterAdd(datasetName = "") {
  await loadCachedDatasetFilterForSelectedPath();
  renderDatasetTable();
  return selectDatasetRecordByName(datasetName);
}

async function ensureCachedDatasetSnapshotForAdd() {
  const loadedPath = normalizePath(cachedDatasetFilter.loadedPath).toLowerCase();
  const selectedPath = normalizePath(state.selectedPath).toLowerCase();
  if (!selectedPath) return;
  if (loadedPath !== selectedPath || cachedDatasetFilter.loading) {
    await loadCachedDatasetFilterForSelectedPath();
  }
  if (cachedDatasetFilter.error) {
    throw new Error(cachedDatasetFilter.error);
  }
}

function datasetInstanceExistsInSelectedPath(instanceName) {
  const key = getCachedDatasetKey(instanceName);
  return !!key && cachedDatasetFilter.names instanceof Set && cachedDatasetFilter.names.has(key);
}

function hideDatasetAddMessageBox() {
  els.datasetAddMessageOverlay?.setAttribute("hidden", "");
}

function showAddDatasetMessageBox(message, title = "Add Dataset") {
  const text = toText(message);
  if (!text) return;
  setStatus(text, true);
  if (!els.datasetAddMessageOverlay || !els.datasetAddMessageText) return;
  if (els.datasetAddMessageTitle) els.datasetAddMessageTitle.textContent = toText(title) || "Add Dataset";
  els.datasetAddMessageText.textContent = text;
  if (els.datasetAddMessageBox) {
    els.datasetAddMessageBox.style.left = "50%";
    els.datasetAddMessageBox.style.top = "50%";
    els.datasetAddMessageBox.style.transform = "translate(-50%, -50%)";
  }
  els.datasetAddMessageOverlay.removeAttribute("hidden");
  els.datasetAddMessageOk?.focus?.({ preventScroll: true });
}

async function addGeneratedDataset(record, lengths) {
  await ensureCachedDatasetSnapshotForAdd();
  if (datasetInstanceExistsInSelectedPath(record.datasetName)) {
    showAddDatasetMessageBox(
      `Dataset "${record.datasetName}" already exists in this reserving class path.`,
      "Dataset Already Exists",
    );
    return;
  }
  setStatus(`Requesting generated dataset ${record.datasetName}...`);
  const res = await fetch("/arcrho/tri/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildAddDatasetTriPayload(record, lengths)),
  });
  const out = await res.json().catch(() => ({}));
  if (res.ok && out?.ok === false && toText(out?.request_file)) {
    await refreshDatasetsAfterAdd(record.datasetName);
    setStatus(`Generated dataset request sent for ${record.datasetName}. Waiting for data engine output.`);
    return;
  }
  if (!res.ok || out?.ok === false) {
    const detail = toText(out?.detail || out?.status) || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  const selected = await refreshDatasetsAfterAdd(record.datasetName);
  setStatus(selected
    ? `Generated dataset request completed for ${record.datasetName}. Selected the new dataset.`
    : `Generated dataset request completed for ${record.datasetName}.`);
}

async function makeTemporaryDatasetPermanent(record) {
  if (!isTemporaryViewActive() || !record || record.isIndexed) return;
  if (!projectName || !state.selectedPath) {
    setStatus("Select a reserving class path before making a dataset permanent.", true);
    return;
  }
  const datasetName = toText(record.datasetName);
  if (!datasetName) return;
  const lengths = await getAddDatasetDefaultLengths();
  const request = buildMakePermanentDatasetPayload(record, lengths);
  setStatus(`Making ${datasetName} permanent...`);
  const res = await fetch(request.route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request.body),
  });
  const out = await res.json().catch(() => ({}));
  if (res.ok && out?.ok === false && toText(out?.request_file)) {
    await refreshDatasetsAfterAdd(datasetName);
    setStatus(`Permanent dataset request sent for ${datasetName}. Waiting for data engine output.`);
    return;
  }
  if (!res.ok || out?.ok === false) {
    const detail = toText(out?.detail || out?.status) || `HTTP ${res.status}`;
    throw new Error(detail);
  }
  await refreshDatasetsAfterAdd(datasetName);
  setStatus(`${datasetName} is now permanent.`);
}

function openNonGeneratedDatasetDraft(record, lengths) {
  const frame = openNewDatasetDraftWindow(record.datasetName, {
    datasetTypeName: record.datasetTypeName || record.datasetName,
    dataFormat: getDatasetRecordValue(record, "dataFormat") || "Triangle",
    originLen: lengths.originLen,
    devLen: lengths.devLen,
    initialTab: "details",
    draft: true,
  });
  if (frame) {
    setStatus(`Opened new dataset draft for ${record.datasetName}.`);
  }
}

function buildDatasetRowFromPickerItem(item) {
  if (!item || typeof item !== "object") return null;
  const name = toText(item.name);
  if (!name) return null;
  return [
    name,
    toText(item.dataFormat),
    toText(item.category),
    !!item.calculated,
    toText(item.formula),
    !!item.generated,
  ];
}

function getDatasetAddRecordFromPickerSelection(name, item) {
  const datasetName = toText(name || item?.name);
  if (!datasetName) return null;
  const existingRow = getDatasetTypeRowByName(datasetName);
  const row = existingRow || buildDatasetRowFromPickerItem(item);
  if (!row) return null;
  const rowIndex = existingRow ? state.datasetRows.indexOf(existingRow) : state.datasetRows.length;
  return buildDatasetRecord(row, rowIndex);
}

async function processDatasetAddSelection(selected) {
  const datasetName = toText(selected?.datasetName);
  if (!datasetName) return;
  const key = `${selected.generated ? "generated" : "draft"}\u0001${normalizeLookupKey(datasetName)}`;
  if (addDatasetSelectionInFlightKeys.has(key)) return;
  addDatasetSelectionInFlightKeys.add(key);
  try {
    const lengths = await getAddDatasetDefaultLengths();
    if (selected.generated) {
      await addGeneratedDataset(selected, lengths);
    } else {
      openNonGeneratedDatasetDraft(selected, lengths);
    }
  } catch (err) {
    setStatus(`Add dataset failed: ${toText(err?.message) || "Unknown error."}`, true);
  } finally {
    addDatasetSelectionInFlightKeys.delete(key);
  }
}

async function openDatasetAddSharedPicker() {
  closeDatasetRowContextMenu();
  closeDatasetTableContextMenu();
  closeDatasetGroupContextMenu();
  closeDatasetTableFilterPopover();

  await openDatasetNamePicker({
    projectName,
    initialName: "",
    anchorElement: els.datasetTableSurface || els.datasetTableWrap || null,
    title: "Add Dataset",
    emptyMessage: "No dataset types are available.",
    setStatus: (message) => {
      const text = toText(message);
      if (text) setStatus(text, true);
    },
    onError: (err) => {
      console.error("Failed to open dataset add picker:", err);
      setStatus(`Dataset type picker failed: ${toText(err?.message || err) || "Unknown error."}`, true);
    },
    onSelect: (name, item) => {
      void processDatasetAddSelection(getDatasetAddRecordFromPickerSelection(name, item));
    },
  }).catch((err) => {
    console.error("Failed to open dataset add picker:", err);
    setStatus(`Dataset type picker failed: ${toText(err?.message || err) || "Unknown error."}`, true);
  });
}

async function addDatasetFromTypePicker() {
  if (!projectName || !state.selectedPath) {
    setStatus("Select a reserving class path before adding a dataset.", true);
    return;
  }
  await openDatasetAddSharedPicker();
}

function resolveDatasetDeleteConfirm(value) {
  const overlay = els.datasetDeleteConfirmOverlay;
  const resolve = state.datasetDeleteConfirmResolve;
  state.datasetDeleteConfirmResolve = null;
  overlay?.setAttribute("hidden", "");
  if (resolve) resolve(!!value);
}

function showDatasetDeleteConfirm(records) {
  if (state.datasetDeleteConfirmResolve) return Promise.resolve(false);
  const names = records.map((record) => toText(record?.datasetName)).filter(Boolean);
  if (!names.length) return Promise.resolve(false);
  const countText = names.length === 1 ? "1 selected dataset" : `${names.length} selected datasets`;
  if (els.datasetDeleteConfirmMessage) {
    els.datasetDeleteConfirmMessage.textContent = `Delete cached files related to ${countText} for the selected reserving-class path?`;
  }
  if (els.datasetDeleteConfirmList) {
    els.datasetDeleteConfirmList.replaceChildren();
    for (const name of names.slice(0, 8)) {
      const item = document.createElement("div");
      item.className = "pi-delete-confirm-item";
      item.textContent = name;
      els.datasetDeleteConfirmList.appendChild(item);
    }
    if (names.length > 8) {
      const more = document.createElement("div");
      more.className = "pi-delete-confirm-more";
      more.textContent = `+${names.length - 8} more`;
      els.datasetDeleteConfirmList.appendChild(more);
    }
  }
  if (els.datasetDeleteConfirmBox) {
    els.datasetDeleteConfirmBox.style.left = "50%";
    els.datasetDeleteConfirmBox.style.top = "50%";
    els.datasetDeleteConfirmBox.style.transform = "translate(-50%, -50%)";
  }
  els.datasetDeleteConfirmOverlay?.removeAttribute("hidden");
  els.datasetDeleteConfirmDelete?.focus?.();
  return new Promise((resolve) => {
    state.datasetDeleteConfirmResolve = resolve;
  });
}

async function deleteSelectedDatasetRows(records) {
  const requestedNames = records.map((record) => toText(record?.datasetName)).filter(Boolean);
  if (!projectName || !state.selectedPath || !requestedNames.length) return;
  const confirmed = await showDatasetDeleteConfirm(records);
  if (!confirmed) return;
  // A refusal naming the downstream chain may turn into one confirmed
  // resubmission carrying the chain, and that wider request can itself be
  // refused when the graph moved in between, so the delete runs as a loop:
  // each round either succeeds, stops, or grows the name list the user
  // approved in the blocked-chain dialog.
  let names = requestedNames;
  const label = requestedNames.length === 1 ? requestedNames[0] : `${requestedNames.length} datasets`;
  setStatus(`Deleting cached files for ${label}...`);
  // The server removes the files and rebuilds index.json in one request with no
  // intermediate progress to report, so this shows the shared indeterminate
  // spinner and its elapsed counter rather than a percentage nothing measures.
  beginPageLoading("delete-datasets", {
    title: "Deleting cached files",
    message: `Removing cached files for ${label} and rebuilding the dataset index...`,
  });
  try {
    let resp;
    let payload;
    for (;;) {
      resp = await fetch("/datasets/cached/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: projectName,
          reserving_class: state.selectedPath,
          dataset_names: names,
        }),
      });
      payload = await resp.json().catch(() => ({}));
      if (resp.ok) break;
      // Nothing was deleted when dependents block the request, so the table is
      // still correct; the user gets the chain window instead of an error line
      // and either opens a dependent to clear the input or confirms deleting
      // the whole chain, which resubmits with the chain included.
      const blocked = api.readDeleteBlockedDetail?.(payload);
      if (!blocked) break;
      finishPageLoading("delete-datasets");
      setStatus("Delete blocked: the selection is still used as input.", true);
      const decision = await api.showDeleteBlockedByDependents(blocked);
      if (!decision?.deleteChainNames?.length) return;
      const seen = new Set(names.map((name) => name.toLowerCase()));
      for (const name of decision.deleteChainNames) {
        if (!seen.has(name.toLowerCase())) {
          seen.add(name.toLowerCase());
          names = [...names, name];
        }
      }
      setStatus(`Deleting cached files for ${names.length} datasets...`);
      beginPageLoading("delete-datasets", {
        title: "Deleting cached files",
        message: `Removing cached files for ${names.length} datasets and rebuilding the dataset index...`,
      });
    }
    if (!resp.ok || payload?.ok === false) {
      const detail = payload?.detail;
      throw new Error(
        (typeof detail === "string" ? detail : "") || payload?.message || `Delete failed (${resp.status})`
      );
    }
    datasetTableSelection.selectedKeys.clear();
    datasetTableSelection.anchorKey = "";
    // The delete already rebuilt and returned the index, so re-reading it would
    // cost a second round trip over the share for data we are holding.
    const freshIndex = payload?.index;
    if (freshIndex?.ok && Array.isArray(freshIndex.files)) {
      // The returned index carries the authoritative post-delete signature,
      // so the watch re-baselines from the payload; this brief hold only
      // covers a poll racing applyCachedDatasetSnapshot (see
      // DATASET_INDEX_SETTLE_SUPPRESS_MS in project_instance_dataset_cache.js).
      state.datasetIndexWatch.suppressUntil = Date.now() + 1500;
      applyCachedDatasetSnapshot(freshIndex, state.selectedPath);
      state.datasetIndexWatch.pending = false;
      syncCachedDatasetToolbar();
    } else {
      await loadCachedDatasetFilterForSelectedPath();
    }
    renderDatasetTable();
    const deletedCount = Number(payload?.deleted_count || 0);
    setStatus(
      deletedCount
        ? `Deleted ${deletedCount} cached ${deletedCount === 1 ? "file" : "files"}.`
        : "No matching cached files were found."
    );
  } catch (err) {
    setStatus(toText(err?.message) || "Failed to delete cached dataset files.", true);
  } finally {
    finishPageLoading("delete-datasets");
  }
}

async function setDatasetRowsReviewStatus(records, needsReview, { reservingClass = state.selectedPath } = {}) {
  // A row no method wrote has no review flag; the menu already hides the
  // items for such a selection, and this keeps a mixed selection acting only
  // on the method outputs inside it.
  const names = (records || [])
    .filter(isMethodDatasetRecord)
    .map((record) => toText(record?.datasetName))
    .filter(Boolean);
  const path = normalizePath(reservingClass);
  if (!projectName || !path || !names.length) return { ok: false, message: "Select a method-output dataset to update its review status." };
  const isSelectedPath = () => normalizePath(state.selectedPath).toLowerCase() === path.toLowerCase();
  const label = names.length === 1 ? names[0] : `${names.length} objects`;
  const title = needsReview ? "Marking for review" : "Setting reviewed";
  // The reload below rebuilds every row, so the rows the user picked and the
  // place they had scrolled to are remembered here and put back afterwards;
  // signing an object off must not send the reader back to the top of a long
  // class.
  const scrollState = captureDatasetTableScroll();
  const selectionState = captureDatasetTableSelection();
  const selectionPath = normalizePath(state.selectedPath);
  setStatus(`${needsReview ? "Marking" : "Clearing"} the review flag for ${label}...`);
  beginPageLoading("review-status", {
    title,
    message: `Updating the review status of ${label}...`,
  });
  try {
    const resp = await fetch("/datasets/review-status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_name: projectName,
        reserving_class: path,
        dataset_names: names,
        status: needsReview ? STATUS_REVIEW_NEEDED : STATUS_CURRENT,
      }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok || payload?.ok === false) {
      const detail = payload?.detail;
      throw new Error(
        (typeof detail === "string" ? detail : "") || payload?.message || `Review status failed (${resp.status})`
      );
    }
    // The sidecar writes changed the reserving-class folder, so the index the
    // reload asks for is rebuilt; the suppression window keeps the poll from
    // offering a Refresh Table prompt for the write the user just made.
    if (isSelectedPath()) {
      state.datasetIndexWatch.suppressUntil = Date.now() + 1500;
      await loadCachedDatasetFilterForSelectedPath();
      if (isSelectedPath()) {
        state.datasetIndexWatch.pending = false;
        syncCachedDatasetToolbar();
        renderDatasetTable();
        if (selectionPath.toLowerCase() === path.toLowerCase()) {
          restoreDatasetTableSelection(selectionState);
          restoreDatasetTableScroll(scrollState);
        }
      }
    }
    if (!isSelectedPath()) api.notifyDependencyGraphWindows?.(path);
    const updated = Array.isArray(payload?.updated) ? payload.updated.length : 0;
    const noun = updated === 1 ? "object" : "objects";
    const message = updated
        ? (needsReview
          ? `Marked ${updated} ${noun} for review.`
          : `Set ${updated} ${noun} to reviewed.`)
        : "No review status changes were needed.";
    setStatus(message);
    return { ok: true, message };
  } catch (err) {
    const message = toText(err?.message) || "Failed to update the review status.";
    setStatus(message, true);
    return { ok: false, message };
  } finally {
    finishPageLoading("review-status");
  }
}

function applyDatasetRowContextAction(action) {
  const normalized = toText(action);
  const records = getDatasetRowActionRecords();
  const viewRecord = getDatasetRowViewRecord();
  closeDatasetRowContextMenu();
  if (isTemporaryViewActive() && !["view", "make-permanent"].includes(normalized)) {
    setStatus("Temporary view supports opening datasets only.");
    return;
  }
  // Opening windows stays allowed while a dependent walk holds this class;
  // actions that write into the class wait until it finishes (the app server
  // refuses them with 423 anyway -- this guard just explains the pause).
  if (api.isReservingClassBusy?.() && !["view", "show-as-vector", "view-as-triangle"].includes(normalized)) {
    setStatus("Dependent updates are running for this reserving class. Try again when they finish.");
    return;
  }
  if (normalized === "view") {
    openDatasetRecord(viewRecord);
  } else if (normalized === "make-permanent") {
    void makeTemporaryDatasetPermanent(viewRecord).catch((err) => {
      setStatus(`Could not make dataset permanent: ${toText(err?.message) || "Unknown error."}`, true);
    });
  } else if (normalized === "show-as-vector") {
    openDatasetRecordAsDataset(viewRecord);
  } else if (normalized === "view-as-triangle") {
    openDatasetRecordAsDataset(viewRecord);
  } else if (normalized === "add-dataset") {
    void addDatasetFromTypePicker();
  } else if (normalized === "add-dfm") {
    addDfmForDataset(viewRecord);
  } else if (normalized === "add-result-selection") {
    addResultSelectionForDataset(viewRecord);
  } else if (normalized === "add-bornhuetter-ferguson") {
    addBornhuetterFergusonForDataset(viewRecord);
  } else if (normalized === "add-cape-cod") {
    addCapeCodForDataset(viewRecord);
  } else if (normalized === "add-bootstrap") {
    addBootstrapForDataset(viewRecord);
  } else if (normalized === "add-stochastic-consolidation") {
    addStochasticConsolidationForDataset(viewRecord);
  } else if (normalized === "add-berquist-sherman-sr") {
    addBerquistShermanForDataset(viewRecord, "sr");
  } else if (normalized === "add-berquist-sherman-cra") {
    addBerquistShermanForDataset(viewRecord, "cra");
  } else if (normalized === "mark-for-review") {
    void setDatasetRowsReviewStatus(records, true);
  } else if (normalized === "set-reviewed") {
    void setDatasetRowsReviewStatus(records, false);
  } else if (normalized === "delete") {
    void deleteSelectedDatasetRows(records);
  }
}

function clearDatasetTableFilterHoverCloseTimer() {
  if (!state.datasetTableFilterHoverCloseTimer) return;
  window.clearTimeout(state.datasetTableFilterHoverCloseTimer);
  state.datasetTableFilterHoverCloseTimer = 0;
}

function scheduleDatasetTableFilterHoverClose() {
  if (state.datasetTableFilterOpenMode !== "active-filter") return;
  clearDatasetTableFilterHoverCloseTimer();
  state.datasetTableFilterHoverCloseTimer = window.setTimeout(() => {
    state.datasetTableFilterHoverCloseTimer = 0;
    if (state.datasetTableFilterHoveringTrigger || state.datasetTableFilterHoveringPopover) return;
    closeDatasetTableFilterPopover();
  }, 160);
}

function getDatasetTableFilterReopenAnchor(key, mode) {
  if (mode === "active-filter") return findDatasetActiveFilterChip(key);
  return findDatasetFilterButton(key);
}

function reopenDatasetTableFilterPopoverAfterChange(key) {
  const mode = state.datasetTableFilterOpenMode || "button";
  const searchText = state.datasetTableFilterSearchText;
  const nextAnchor = getDatasetTableFilterReopenAnchor(key, mode);
  if (!nextAnchor) {
    closeDatasetTableFilterPopover();
    return;
  }
  openDatasetTableFilterPopover(key, nextAnchor, { mode, searchText });
}

function openDatasetActiveFilterChipPopover(chip) {
  const key = toText(chip?.dataset?.filterKey);
  if (!key || !isDatasetColumnFilterable(key)) return;
  state.datasetTableFilterHoveringTrigger = true;
  clearDatasetTableFilterHoverCloseTimer();
  openDatasetTableFilterPopover(key, chip, { mode: "active-filter" });
}

function closeDatasetTableFilterPopover() {
  const pop = els.datasetTableFilterPopover;
  if (!pop) return;
  clearDatasetTableFilterHoverCloseTimer();
  pop.classList.remove("open");
  pop.setAttribute("aria-hidden", "true");
  pop.innerHTML = "";
  state.datasetTableFilterColumn = "";
  state.datasetTableFilterSearchText = "";
  state.datasetTableFilterAnchor = null;
  state.datasetTableFilterOpenMode = "";
  state.datasetTableFilterHoveringTrigger = false;
  state.datasetTableFilterHoveringPopover = false;
}

function positionDatasetTableFilterPopover() {
  const pop = els.datasetTableFilterPopover;
  const anchor = state.datasetTableFilterAnchor;
  if (!pop?.classList?.contains("open") || !anchor?.getBoundingClientRect) return;
  const rect = anchor.getBoundingClientRect();
  positionFixedMenu(pop, rect.left, rect.bottom + 6);
}

function openDatasetTableFilterPopover(key, anchor, popoverOptions = {}) {
  const col = getDatasetColumn(key);
  const pop = els.datasetTableFilterPopover;
  if (!col || !pop || !isDatasetColumnFilterable(key)) return;
  closeDatasetTableContextMenu();
  closeDatasetGroupContextMenu();
  closeDatasetRowContextMenu();
  // Keep popup options aligned with the rows currently rendered from the
  // selected reserving class's index-backed instance snapshot. Falling back to
  // dataset-type definitions omits method outputs whose instance name differs
  // from their configured Dataset Type Name.
  const context = buildDatasetTableRenderContext();
  const options = getDatasetColumnOptions(key, context);
  const selected = getDatasetFilterSelection(key, options);
  const { search } = renderValueFilterMenu(pop, {
    label: col.label,
    options,
    selected,
    searchText: toText(popoverOptions.searchText ?? state.datasetTableFilterSearchText),
    onSearch(value) { state.datasetTableFilterSearchText = value; },
    onChange({ action, allSelected }) {
      if (action === "all" || (action === "value" && allSelected)) {
        state.datasetTableExplicitAllFilterKeys?.add?.(key);
      } else {
        state.datasetTableExplicitAllFilterKeys?.delete?.(key);
      }
      saveDatasetTablePreferences();
      renderDatasetTable();
      reopenDatasetTableFilterPopoverAfterChange(key);
    },
  });

  state.datasetTableFilterColumn = key;
  state.datasetTableFilterAnchor = anchor || findDatasetFilterButton(key);
  state.datasetTableFilterOpenMode = popoverOptions.mode || "button";
  pop.classList.add("open");
  pop.setAttribute("aria-hidden", "false");
  positionDatasetTableFilterPopover();
  if (state.datasetTableFilterOpenMode === "button") {
    search.focus({ preventScroll: true });
  }
}

function toggleDatasetTableFilterPopover(key, anchor) {
  if (!isDatasetColumnFilterable(key)) {
    closeDatasetTableFilterPopover();
    return;
  }
  const pop = els.datasetTableFilterPopover;
  if (
    pop?.classList?.contains("open")
    && state.datasetTableFilterColumn === key
  ) {
    closeDatasetTableFilterPopover();
    return;
  }
  openDatasetTableFilterPopover(key, anchor);
}

function findDatasetFilterButton(key) {
  const th = els.datasetTableSurface?.querySelector?.(`th[data-col-key="${CSS.escape(key)}"]`);
  return th?.querySelector?.(".pi-table-filter-btn") || null;
}

function findDatasetActiveFilterChip(key) {
  return els.datasetActiveFilters?.querySelector?.(`.dataset-filter-chip[data-filter-key="${CSS.escape(key)}"]`) || null;
}

function getDatasetColumnDragKey(event) {
  return event.dataTransfer?.getData(DATASET_COLUMN_DRAG_TYPE) || state.datasetTableColumnDragSourceKey || "";
}

function addDatasetColumnFilterFromDrop(key) {
  const normalized = toText(key);
  if (!isDatasetColumnFilterable(normalized)) {
    const col = getDatasetColumn(normalized);
    setStatus(`${col?.label || "This column"} cannot be filtered.`);
    return false;
  }
  const options = getDatasetColumnOptions(normalized);
  if (!options.length) {
    const col = getDatasetColumn(normalized);
    setStatus(`${col?.label || "This column"} has no filter values.`);
    return false;
  }
  const selected = getDatasetFilterSelection(normalized, options);
  selected.clear();
  state.datasetTableExplicitAllFilterKeys?.add?.(normalized);
  saveDatasetTablePreferences();
  renderDatasetTable();
  const chip = findDatasetActiveFilterChip(normalized);
  if (chip) openDatasetActiveFilterChipPopover(chip);
  return true;
}

function handleDatasetActiveFiltersDragOver(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_COLUMN_DRAG_TYPE)) return;
  event.preventDefault();
  event.stopPropagation();
  const key = getDatasetColumnDragKey(event);
  const valid = !key || isDatasetColumnFilterable(key);
  event.dataTransfer.dropEffect = valid ? "move" : "none";
  els.datasetActiveFilters?.classList?.toggle("drag-over", valid);
  els.datasetActiveFilters?.classList?.toggle("drag-invalid", !valid);
}

function handleDatasetActiveFiltersDrop(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_COLUMN_DRAG_TYPE)) return;
  event.preventDefault();
  event.stopPropagation();
  const key = getDatasetColumnDragKey(event);
  clearDatasetActiveFilterDropState();
  clearDatasetGroupDropState();
  addDatasetColumnFilterFromDrop(key);
}

function handleDatasetGroupZoneDragOver(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_COLUMN_DRAG_TYPE)) return;
  event.preventDefault();
  const key = getDatasetColumnDragKey(event);
  const valid = !key || isDatasetColumnGroupable(key);
  event.dataTransfer.dropEffect = valid ? "move" : "none";
  els.datasetGroupByStatus?.classList?.toggle("drag-over", valid);
  els.datasetGroupByStatus?.classList?.toggle("drag-invalid", !valid);
}

function handleDatasetGroupZoneDrop(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_COLUMN_DRAG_TYPE)) return;
  event.preventDefault();
  event.stopPropagation();
  if (hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) {
    const groupKey = event.dataTransfer?.getData(DATASET_GROUP_DRAG_TYPE) || state.datasetGroupDragSourceKey || "";
    const keys = getDatasetGroupByKeys();
    if (keys.includes(groupKey) && keys[keys.length - 1] !== groupKey) {
      applyDatasetGroupByKeys([...keys.filter((key) => key !== groupKey), groupKey]);
    }
    clearDatasetGroupDropState();
    return;
  }
  const key = event.dataTransfer?.getData(DATASET_COLUMN_DRAG_TYPE) || "";
  clearDatasetGroupDropState();
  if (!addDatasetGroupByKey(key)) {
    const col = getDatasetColumn(key);
    setStatus(`${col?.label || "This column"} cannot be grouped.`);
  }
}

function handleDatasetGroupRemoveDragOver(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) return;
  if (event.target?.closest?.(".pi-table thead th")) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  els.datasetTableWrap?.classList?.add("group-remove-target");
}

function handleDatasetGroupRemoveDrop(event) {
  if (!hasDataTransferType(event.dataTransfer, DATASET_GROUP_DRAG_TYPE)) return;
  event.preventDefault();
  event.stopPropagation();
  const key = event.dataTransfer?.getData(DATASET_GROUP_DRAG_TYPE) || "";
  clearDatasetGroupDropState();
  removeDatasetGroupByKey(key);
}

function wireScrollbarActivity(wrap) {
  if (!wrap || wrap.dataset.scrollbarActivityWired === "1") return;
  wrap.dataset.scrollbarActivityWired = "1";

  let idleTimer = null;
  const syncScrollbarHover = (event) => {
    const rect = wrap.getBoundingClientRect();
    const verticalScrollbarWidth = Math.max(0, wrap.offsetWidth - wrap.clientWidth);
    const horizontalScrollbarHeight = Math.max(0, wrap.offsetHeight - wrap.clientHeight);
    const hasVerticalScrollbar = wrap.scrollHeight > wrap.clientHeight && verticalScrollbarWidth > 0;
    const hasHorizontalScrollbar = wrap.scrollWidth > wrap.clientWidth && horizontalScrollbarHeight > 0;
    const nearVerticalScrollbar = hasVerticalScrollbar
      && event.clientX >= rect.right - Math.max(verticalScrollbarWidth, 16);
    const nearHorizontalScrollbar = hasHorizontalScrollbar
      && event.clientY >= rect.bottom - Math.max(horizontalScrollbarHeight, 16);

    wrap.classList.toggle("isScrollbarHover", nearVerticalScrollbar || nearHorizontalScrollbar);
  };

  wrap.addEventListener("scroll", () => {
    wrap.classList.add("isScrolling");
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      wrap.classList.remove("isScrolling");
    }, 550);
  }, { passive: true });
  wrap.addEventListener("pointermove", syncScrollbarHover, { passive: true });
  wrap.addEventListener("pointerleave", () => {
    wrap.classList.remove("isScrollbarHover");
  }, { passive: true });
}

function initDatasetTableInteractions() {
  if (els.rightPanel?.dataset?.tableInteractionsWired === "1") return;
  if (els.rightPanel) els.rightPanel.dataset.tableInteractionsWired = "1";
  syncDatasetGroupByToolbar();
  wireScrollbarActivity(els.datasetTableWrap);
  wireScrollbarActivity(els.datasetAddPickerTableWrap);
  if (els.datasetTableSurface) {
    els.datasetTableSurface.tabIndex = 0;
    els.datasetTableSurface.addEventListener("keydown", handleDatasetTableKeyDown);
  }
  els.datasetTableWrap?.addEventListener("mousedown", () => focusProjectInstancePage(), true);
  // The whole right panel takes the drop, so the file can be let go over the table
  // itself rather than aimed at the toolbar.
  attachSettingsFileDropZone(els.rightPanel, {
    name: "dataset-view-config",
    hint: "Drop a group and filter settings file to load it",
    onFile: (file) => void loadDatasetViewSettingsFile(file),
  });
  els.datasetToolbar?.addEventListener("contextmenu", async (event) => {
    event.preventDefault();
    event.stopPropagation();
    const recentFiles = await loadRecentSettingsFiles(DATASET_VIEW_CONFIG_KIND);
    openSettingsFileMenu({
      event,
      label: DATASET_VIEW_CONFIG_MENU_LABEL,
      onSave: () => void saveDatasetViewSettingsFile(),
      onLoad: () => void pickDatasetViewSettingsFile(),
      recentFiles,
      onLoadRecent: (filePath) => void pickDatasetViewSettingsFile(filePath),
    });
  });
  els.datasetGroupByStatus?.addEventListener("dragover", handleDatasetGroupZoneDragOver);
  els.datasetGroupByStatus?.addEventListener("dragleave", (event) => {
    if (els.datasetGroupByStatus?.contains(event.relatedTarget)) return;
    clearDatasetGroupDropState();
  });
  els.datasetGroupByStatus?.addEventListener("drop", handleDatasetGroupZoneDrop);
  els.datasetTableWrap?.addEventListener("dragover", handleDatasetGroupRemoveDragOver);
  els.datasetTableWrap?.addEventListener("dragleave", (event) => {
    if (els.datasetTableWrap?.contains(event.relatedTarget)) return;
    clearDatasetGroupDropState();
  });
  els.datasetTableWrap?.addEventListener("drop", handleDatasetGroupRemoveDrop);
  els.datasetTableSurface?.addEventListener("contextmenu", (event) => {
    if (event.target?.closest?.(".pi-table thead th")) {
      event.preventDefault();
      event.stopPropagation();
      showDatasetTableContextMenu(event.clientX, event.clientY);
      return;
    }
    if (!showDatasetEmptyAddContextMenu(event.clientX, event.clientY)) return;
    event.preventDefault();
    event.stopPropagation();
  });
  els.datasetTableContextMenu?.addEventListener("click", (event) => {
    const item = event.target?.closest?.("[data-group-key]");
    if (!item) return;
    event.preventDefault();
    event.stopPropagation();
    setDatasetGroupByKey(item.dataset.groupKey);
  });
  els.datasetGroupContextMenu?.addEventListener("click", (event) => {
    const item = event.target?.closest?.("[data-group-action]");
    if (!item) return;
    event.preventDefault();
    event.stopPropagation();
    applyDatasetGroupContextAction(item.dataset.groupAction);
  });
  els.datasetRowContextMenu?.addEventListener("click", (event) => {
    const item = event.target?.closest?.("[data-row-action]");
    if (!item || item.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    applyDatasetRowContextAction(item.dataset.rowAction);
  });
  els.datasetActiveFilters?.addEventListener("dragover", handleDatasetActiveFiltersDragOver);
  els.datasetActiveFilters?.addEventListener("dragleave", (event) => {
    if (els.datasetActiveFilters?.contains(event.relatedTarget)) return;
    clearDatasetActiveFilterDropState();
  });
  els.datasetActiveFilters?.addEventListener("drop", handleDatasetActiveFiltersDrop);
  els.datasetActiveFilters?.addEventListener("click", (event) => {
    const chip = event.target?.closest?.(".dataset-filter-chip");
    if (!chip) return;
    event.preventDefault();
    event.stopPropagation();
    openDatasetActiveFilterChipPopover(chip);
  });
  els.datasetTableFilterPopover?.addEventListener("mouseenter", () => {
    if (state.datasetTableFilterOpenMode !== "active-filter") return;
    state.datasetTableFilterHoveringPopover = true;
    clearDatasetTableFilterHoverCloseTimer();
  });
  els.datasetTableFilterPopover?.addEventListener("mouseleave", () => {
    if (state.datasetTableFilterOpenMode !== "active-filter") return;
    state.datasetTableFilterHoveringPopover = false;
    scheduleDatasetTableFilterHoverClose();
  });
  document.addEventListener("mousedown", (event) => {
    if (els.datasetTableContextMenu?.contains(event.target)) return;
    if (els.datasetGroupContextMenu?.contains(event.target)) return;
    if (els.datasetRowContextMenu?.contains(event.target)) return;
    if (els.datasetTableFilterPopover?.contains(event.target)) return;
    if (els.datasetAddPickerOverlay?.contains(event.target)) return;
    if (event.target?.closest?.(".pi-table-filter-btn")) return;
    if (event.target?.closest?.(".dataset-filter-chip")) return;
    closeDatasetTableContextMenu();
    closeDatasetGroupContextMenu();
    closeDatasetRowContextMenu();
    closeDatasetTableFilterPopover();
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!els.datasetAddMessageOverlay?.hasAttribute?.("hidden")) {
      hideDatasetAddMessageBox();
      return;
    }
    if (!els.datasetDeleteConfirmOverlay?.hasAttribute?.("hidden")) {
      resolveDatasetDeleteConfirm(false);
    }
    closeDatasetTableContextMenu();
    closeDatasetGroupContextMenu();
    closeDatasetRowContextMenu();
    closeDatasetTableFilterPopover();
  }, true);
  window.addEventListener("resize", () => {
    closeDatasetTableContextMenu();
    closeDatasetGroupContextMenu();
    closeDatasetRowContextMenu();
    positionDatasetTableFilterPopover();
  });
  els.datasetTableWrap?.addEventListener("scroll", positionDatasetTableFilterPopover, true);
  initDatasetAddMessageBoxInteractions();
  initDatasetDeleteConfirmInteractions();
}

function initDatasetAddMessageBoxInteractions() {
  if (!els.datasetAddMessageOverlay || els.datasetAddMessageOverlay.dataset.wired === "1") return;
  els.datasetAddMessageOverlay.dataset.wired = "1";
  els.datasetAddMessageOk?.addEventListener("click", hideDatasetAddMessageBox);
  els.datasetAddMessageClose?.addEventListener("click", hideDatasetAddMessageBox);
  els.datasetAddMessageOverlay.addEventListener("mousedown", (event) => {
    if (event.target === event.currentTarget) hideDatasetAddMessageBox();
  });
}

function initDatasetDeleteConfirmInteractions() {
  if (!els.datasetDeleteConfirmOverlay || els.datasetDeleteConfirmOverlay.dataset.wired === "1") return;
  els.datasetDeleteConfirmOverlay.dataset.wired = "1";
  els.datasetDeleteConfirmDelete?.addEventListener("click", () => resolveDatasetDeleteConfirm(true));
  els.datasetDeleteConfirmCancel?.addEventListener("click", () => resolveDatasetDeleteConfirm(false));
  els.datasetDeleteConfirmClose?.addEventListener("click", () => resolveDatasetDeleteConfirm(false));
  els.datasetDeleteConfirmOverlay.addEventListener("mousedown", (event) => {
    if (event.target === event.currentTarget) resolveDatasetDeleteConfirm(false);
  });
  const box = els.datasetDeleteConfirmBox;
  const header = box?.querySelector?.(".pi-delete-confirm-header");
  if (!box || !header) return;
  header.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const rect = box.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const startLeft = rect.left;
    const startTop = rect.top;
    box.style.transform = "none";
    box.style.left = `${Math.round(startLeft)}px`;
    box.style.top = `${Math.round(startTop)}px`;
    const onMove = (moveEvent) => {
      const pad = 10;
      const nextLeft = Math.max(pad, Math.min(startLeft + moveEvent.clientX - startX, window.innerWidth - rect.width - pad));
      const nextTop = Math.max(pad, Math.min(startTop + moveEvent.clientY - startY, window.innerHeight - rect.height - pad));
      box.style.left = `${Math.round(nextLeft)}px`;
      box.style.top = `${Math.round(nextTop)}px`;
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove, true);
      document.removeEventListener("mouseup", onUp, true);
    };
    document.addEventListener("mousemove", onMove, true);
    document.addEventListener("mouseup", onUp, true);
  });
}


async function fetchDatasetTypeRows() {
  const fetched = await fetchProjectDatasetTypes(projectName);
  return Array.isArray(fetched?.data?.rows)
    ? fetched.data.rows.filter((row) => getDatasetName(row))
    : [];
}

// Dataset Types owns the type-owned columns (Data Format, Category, Formula) that
// the table shows next to each instance. Project Settings can add or edit a type
// while this page stays open, so the boot snapshot goes stale and instances of a
// newer type render with a blank category. Reloaded with the dataset index;
// returns null when the read fails so the caller keeps the rows it already has.
async function fetchDatasetTypeRowsForRefresh() {
  if (!projectName) return null;
  try {
    return await fetchDatasetTypeRows();
  } catch (err) {
    console.error("Failed to reload dataset types:", err);
    return null;
  }
}

async function loadDatasets() {
  beginPageLoading("datasets");
  if (!projectName) {
    setEmptyTable("Project name is missing.");
    finishPageLoading("datasets");
    return;
  }
  try {
    state.datasetRows = await fetchDatasetTypeRows();
    autoFitInitialDatasetTableWidths(state.datasetRows);
    renderDatasetTable();
  } catch (err) {
    console.error("Failed to load dataset types:", err);
    setEmptyTable("Failed to load dataset types.");
    setStatus(toText(err?.message) || "Failed to load dataset types.", true);
  } finally {
    finishPageLoading("datasets");
  }
}

  Object.assign(api, {
    appendGroupedDatasetRows,
    applyDatasetGroupContextAction,
    applyDatasetRowContextAction,
    applyDatasetRowSelection,
    applyDatasetTablePreferences,
    autoFitInitialDatasetTableWidths,
    buildDatasetGroupParts,
    buildDatasetRecord,
    buildDatasetTableRenderContext,
    captureDatasetTableSelection,
    clampInitialDatasetTableWidth,
    clearDatasetColumnDragIndicators,
    clearDatasetColumnFilter,
    closeDatasetGroupContextMenu,
    closeDatasetRowContextMenu,
    closeDatasetTableContextMenu,
    closeDatasetTableFilterPopover,
    collectDatasetSameLevelGroupIds,
    compareDatasetRecords,
    compareTextValues,
    createDatasetGroupRow,
    createDatasetRecordRow,
    createDatasetTable,
    createDatasetTableHeaderCell,
    deleteSelectedDatasetRows,
    fetchDatasetTypeRowsForRefresh,
    findDatasetFilterButton,
    focusDatasetTableSurface,
    getActiveDatasetSelectionIndex,
    getCachedDatasetMetadata,
    getDatasetActiveFilterSummaries,
    getDatasetCellValue,
    getDatasetColumn,
    getDatasetColumnOptions,
    getDatasetFilterActiveValues,
    getDatasetFilterKey,
    getDatasetFilterSelection,
    getDatasetGroupByKeys,
    getDatasetGroupId,
    getDatasetName,
    getDatasetRecordByKey,
    getDatasetRecordIndexByKey,
    getDatasetRecordKey,
    getDatasetRecordValue,
    getDatasetRowActionRecords,
    getDatasetRowViewRecord,
    getDatasetSameLevelGroupIds,
    getDatasetTablePreferencePayload,
    getDatasetTablePreferencesSource,
    getDatasetTableRecords,
    getDatasetTableTotalWidth,
    getDatasetTableWidth,
    getInitialDatasetTableColumnWidth,
    getMethodType,
    getOrderedDatasetColumns,
    getSelectedDatasetRecords,
    getSortIconSvg,
    handleDatasetTableKeyDown,
    initDatasetDeleteConfirmInteractions,
    initDatasetTableInteractions,
    isBerquistShermanDatasetRecord,
    isBornhuetterFergusonDatasetRecord,
    isBornhuetterFergusonVectorDatasetRecord,
    isCapeCodDatasetRecord,
    isCapeCodVectorDatasetRecord,
    isBootstrapDatasetRecord,
    isBootstrapVectorDatasetRecord,
    isStochasticConsolidationDatasetRecord,
    isStochasticConsolidationVectorDatasetRecord,
    isDatasetColumnFilterActive,
    isDfmDatasetRecord,
    isMethodDatasetRecord,
    loadDatasetTablePreferences,
    loadDatasets,
    measureDatasetTableText,
    moveDatasetTableColumn,
    openDatasetRecord,
    addDatasetFromTypePicker,
    openDatasetTableFilterPopover,
    openBerquistShermanTabForDataset,
    openBornhuetterFergusonTabForDataset,
    openCapeCodTabForDataset,
    openBootstrapTabForDataset,
    openStochasticConsolidationTabForDataset,
    openDfmTabForDataset,
    parseDatasetGroupId,
    positionDatasetTableFilterPopover,
    positionFixedMenu,
    pruneDatasetTableSelection,
    recordSelectedDfmObject,
    renderDatasetTable,
    resetDatasetTableColumnDefaultWidth,
    resolveDatasetDeleteConfirm,
    restoreDatasetTableSelection,
    rowMatchesDatasetTableFilters,
    saveDatasetTablePreferences,
    scrollDatasetRecordIntoView,
    selectDatasetRecordByName,
    selectDatasetRecordAtIndex,
    setDatasetGroupByKey,
    setDatasetRecordSelected,
    setDatasetRowsReviewStatus,
    setDatasetTableColumnWidth,
    setEmptyTable,
    setSkeletonTable,
    showDatasetDeleteConfirm,
    showDatasetGroupContextMenu,
    showDatasetRowContextMenu,
    showDatasetTableContextMenu,
    sortDatasetRecords,
    startDatasetTableColumnResize,
    syncDatasetActiveFiltersToolbar,
    syncDatasetTableSelectionDom,
    syncDatasetTableTotalWidth,
    toggleDatasetTableFilterPopover,
    toggleDatasetTableSort,
    updateDatasetColumnDragIndicator,
    updateDatasetSelectionStatusBar
  });
}
