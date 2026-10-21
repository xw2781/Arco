import { fetchProjectDatasetTypes, normalizeDatasetTypesPayload as normalizeDatasetTypesPayloadShared } from "/ui/shared/dataset/dataset_types_source.js";
import {
  buildDatasetTypeColumnFilterOptionsFromRows,
  getDatasetTypeCategoryKey,
  getDatasetTypeCategoryLabel,
  getDatasetTypeColumnFilterValueKeyFromRow,
  isDatasetTypeSelectionFilterActive,
} from "/ui/shared/dataset/dataset_types_view_model.js";
import { createArcRhoProgressPopup } from "/ui/shared/components/progress_popup/progress_popup.js?v=20260824a";
import {
  createDatasetTypesChangeRequestId,
  datasetTypesRowsSignature,
  describeDatasetTypesChangeResult,
  waitForDatasetTypesChangeJob,
} from "/ui/project_settings/project_settings_dataset_types_job.js?v=20260927smb18";
import { createDatasetTypeCategoryCombo } from "/ui/project_settings/project_settings_dataset_type_category_combo.js?v=20260811dtcategory1";
import { createDatasetTypeFormatSelect } from "/ui/project_settings/project_settings_dataset_type_format_select.js?v=20260812dtformat2";
import { formatDetailsFormulaText } from "/ui/shared/tabs/details/details_dependencies.js?v=20261021c";
import { createTableGroupRow } from "/ui/shared/components/table_group_row/table_group_row.js?v=20261013a";
import {
  clearTableSkeletonRows,
  renderTableSkeletonRows,
} from "./project_settings_skeleton.js?v=20260821pstree1";

export function createDatasetTypesFeature(deps = {}) {
  const {
    datasetTypesBody = null,
    datasetTypesStatus = null,
    datasetTypesRowContextMenu = null,
    datasetTypesErrorOverlay = null,
    datasetTypesErrorBody = null,
    datasetTypesErrorClose = null,
    initTableColumnResizing = () => {},
    getCollapsedGroups = () => new Set(),
    saveCollapsedGroups = () => {},
    showTableGroupContextMenu = () => {},
    resizeCellTextarea = () => {},
    normalizeProjectKey = (name) => String(name || "").trim().toLowerCase(),
    fetchImpl = fetch,
    setStatus = () => {},
    loadAuditLog = async () => {},
    getSelectedProject = () => null,
    getCurrentFieldNames = () => [],
    ensureFieldMappingLoaded = async () => {},
    findDatasetTypeOwnerInFieldMapping = () => "",
    getMappedDatasetTypeNamesInFieldMapping = () => [],
    renderFieldMappingTable = () => {},
    hideContextMenu = () => {},
    hideFolderContextMenu = () => {},
    hideTreeContextMenu = () => {},
    hideReservingClassTypesRowContextMenu = () => {},
    positionContextMenu = (menu, x, y) => { menu.style.left = `${x}px`; menu.style.top = `${y}px`; menu.classList.add("show"); },
    datasetTypeEditor = null,
    datasetTypeEditorHeader = null,
    datasetTypeEditorTitle = null,
    dtEditName = null,
    dtEditDataFormat = null,
    dtFormatSelect = null,
    dtFormatTrigger = null,
    dtFormatValue = null,
    dtFormatList = null,
    dtCategoryCombo = null,
    dtEditCategory = null,
    dtCategoryToggle = null,
    dtCategoryList = null,
    dtCategoryNewTip = null,
    dtCategoryNewTipText = null,
    dtEditCalculated = null,
    dtEditFormula = null,
    scheduleDatasetTypesAutoSave = () => {},
  } = deps;

  const DATASET_TYPES_COLUMNS = ["Name", "Data Format", "Category", "Calculated", "Formula"];

  /**
   * How a formula reads in this table. One shared formatter serves this grid,
   * the Project Instance dataset table, and the Dataset Viewer Formula field,
   * so the same formula never reads three ways. The stored text is untouched;
   * the raw value stays on the cell for copy and for the row editor.
   */
  function displayDatasetTypeFormula(rows, formula) {
    const knownNames = (rows || [])
      .map((row) => String(row?.[0] ?? "").trim())
      .filter(Boolean);
    return formatDetailsFormulaText(formula, knownNames);
  }

  const DATASET_TYPES_SORTABLE_COLS = new Set([...DATASET_TYPES_COLUMNS]);
  const DATASET_TYPES_FILTERABLE_COLS = new Set(["Name", "Data Format", "Category", "Calculated"]);
  const DATASET_TYPES_BLANK_CATEGORY_KEY = "__blank__";
  const datasetTypesByProject = new Map();
  const loadedDatasetTypesByProject = new Set();
  // One entry per project whose change job is still running. The table is
  // read-only while it is present: the Engine holds the whole project, so an
  // edit made now could not be saved anyway, and queueing it would leave the
  // grid disagreeing with the file again.
  const runningChangeJobByProject = new Map();
  // The last submission for a project, kept so a retry of the *same* table
  // replays its request id instead of applying the change twice.
  const lastSubmissionByProject = new Map();
  // The follow-up for the job this page most recently submitted, so a caller
  // that does want the finished outcome can wait for it.
  let runningChangeJobPromise = Promise.resolve(true);
  // The change job's own blocking window. It covers Project Settings for the
  // whole job, because every reserving class of the project is held while it
  // runs: there is nothing on this page the user could usefully do meanwhile,
  // and a status line is too easy to miss for work that takes minutes.
  const changeProgressPopup = createArcRhoProgressPopup({
    title: "Applying Dataset Type Changes",
    // Every step names a reserving class, so the card is sized once rather
    // than re-sized to each path it reports.
    measured: true,
  });
  const datasetTypesInvalidFormulaByProject = new Map();
  const datasetTypesSortStateByProject = new Map();
  const datasetTypesDataFormatFilterStateByProject = new Map();
  const datasetTypesDataFormatOptionsByProject = new Map();
  const datasetTypesCategoryFilterStateByProject = new Map();
  const datasetTypesCategoryOptionsByProject = new Map();
  const datasetTypesCalculatedFilterStateByProject = new Map();
  const datasetTypesCalculatedOptionsByProject = new Map();
  const datasetTypesNameFilterStateByProject = new Map();
  const datasetTypesNameOptionsByProject = new Map();
  let datasetTypesContextProject = "";
  let datasetTypesContextRowIndex = -1;
  let datasetTypesContextCellText = "";
  let datasetTypesLoadSeq = 0;
  let dtEditorProject = "";
  let dtEditorRowIndex = -1;
  let dtEditorMode = "edit";
  let dtEditorInsertAfterIndex = -1;
  let dtEditorDragState = null;
  let dtEditorInitialCalculated = false;
  let datasetTypesFilterPopover = null;
  let datasetTypesFilterPopoverProject = "";
  let datasetTypesFilterPopoverColLabel = "";
  let datasetTypesFilterPopoverAnchor = null;
  let datasetTypesFilterPopoverSearchText = "";
  let datasetTypesFilterPopoverWired = false;
  let datasetTypesErrorUiWired = false;
  let datasetTypesLoadModeDialog = null;
  let datasetTypesLoadModeDialogResolve = null;
  const formatSelect = createDatasetTypeFormatSelect({
    root: dtFormatSelect,
    select: dtEditDataFormat,
    trigger: dtFormatTrigger,
    valueEl: dtFormatValue,
    list: dtFormatList,
  });
  const categoryCombo = createDatasetTypeCategoryCombo({
    root: dtCategoryCombo,
    input: dtEditCategory,
    toggle: dtCategoryToggle,
    list: dtCategoryList,
    newTip: dtCategoryNewTip,
    newTipText: dtCategoryNewTipText,
  });

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function copyTextToClipboard(rawText, doc = window.document) {
    const text = String(rawText ?? "");

    try {
      const nav = doc?.defaultView?.navigator || window.navigator;
      if (nav?.clipboard && typeof nav.clipboard.writeText === "function") {
        await nav.clipboard.writeText(text);
        return true;
      }
    } catch {
      // fallback below
    }

    try {
      const ta = doc.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "readonly");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      ta.style.pointerEvents = "none";
      ta.style.left = "-9999px";
      ta.style.top = "0";
      doc.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = typeof doc.execCommand === "function" ? doc.execCommand("copy") : false;
      if (ta.parentNode) ta.parentNode.removeChild(ta);
      return !!ok;
    } catch {
      return false;
    }
  }

  function setDatasetTypesStatus(msg, isError = false) {
    if (!datasetTypesStatus) return;
    const text = String(msg || "").trim();
    datasetTypesStatus.innerHTML = "";
    datasetTypesStatus.classList.toggle("error", !!isError);
    if (!text) return;

    if (!isError) {
      const plain = document.createElement("span");
      plain.className = "dataset-types-status-text";
      plain.textContent = text;
      datasetTypesStatus.appendChild(plain);
      return;
    }

    const detailLines = buildDatasetTypesErrorLines(text);
    const summaryText = buildDatasetTypesErrorSummary(text, detailLines);
    const summary = document.createElement("span");
    summary.className = "dataset-types-status-text";
    summary.textContent = summaryText;
    datasetTypesStatus.appendChild(summary);

    const seeMoreBtn = document.createElement("button");
    seeMoreBtn.type = "button";
    seeMoreBtn.className = "dataset-types-status-see-more";
    seeMoreBtn.textContent = "see more";
    seeMoreBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openDatasetTypesErrorOverlay(detailLines);
    });
    datasetTypesStatus.appendChild(seeMoreBtn);
  }

  function buildDatasetTypesErrorLines(rawMessage) {
    const raw = String(rawMessage || "").trim();
    if (!raw) return [];
    const normalized = raw
      .replace(/\r/g, "\n")
      .replace(/\.\s+(?=E\s+\d+\b)/g, ";\n");
    const parts = normalized
      .split(/\n|;\s*/g)
      .map((v) => String(v || "").trim())
      .filter(Boolean);
    return parts.length > 0 ? parts : [raw];
  }

  function buildDatasetTypesErrorSummary(rawMessage, lines) {
    const first = String((Array.isArray(lines) && lines[0]) || rawMessage || "").trim();
    if (!first) return "";
    const extra = Math.max(0, (Array.isArray(lines) ? lines.length : 0) - 1);
    return extra > 0 ? `${first} (+${extra} more)` : first;
  }

  function closeDatasetTypesErrorOverlay() {
    if (!datasetTypesErrorOverlay) return;
    datasetTypesErrorOverlay.classList.remove("show");
    datasetTypesErrorOverlay.setAttribute("aria-hidden", "true");
  }

  function ensureDatasetTypesErrorUiWired() {
    if (datasetTypesErrorUiWired) return;
    datasetTypesErrorUiWired = true;
    if (datasetTypesErrorClose) {
      datasetTypesErrorClose.addEventListener("click", () => {
        closeDatasetTypesErrorOverlay();
      });
    }
    if (datasetTypesErrorOverlay) {
      datasetTypesErrorOverlay.addEventListener("mousedown", (e) => {
        if (e.target === datasetTypesErrorOverlay) closeDatasetTypesErrorOverlay();
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!datasetTypesErrorOverlay || !datasetTypesErrorOverlay.classList.contains("show")) return;
      closeDatasetTypesErrorOverlay();
    });
  }

  function openDatasetTypesErrorOverlay(lines) {
    if (!datasetTypesErrorOverlay || !datasetTypesErrorBody) return;
    ensureDatasetTypesErrorUiWired();
    const detailLines = Array.isArray(lines) ? lines : [];
    datasetTypesErrorBody.innerHTML = "";
    if (detailLines.length === 0) {
      const line = document.createElement("div");
      line.className = "dataset-types-error-line";
      line.textContent = "No additional details.";
      datasetTypesErrorBody.appendChild(line);
    } else {
      for (const item of detailLines) {
        const line = document.createElement("div");
        line.className = "dataset-types-error-line";
        line.textContent = String(item || "").trim();
        datasetTypesErrorBody.appendChild(line);
      }
    }
    datasetTypesErrorOverlay.classList.add("show");
    datasetTypesErrorOverlay.setAttribute("aria-hidden", "false");
  }

  function getProjectDatasetTypesState(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!datasetTypesByProject.has(key)) {
      datasetTypesByProject.set(key, {
        columns: [...DATASET_TYPES_COLUMNS],
        rows: [],
        // Name edits since the table was last saved, keyed by the saved name:
        // the server cannot tell a rename from one type removed and another
        // added, and a rename has to reach the instances of the old type.
        renames: new Map(),
      });
    }
    return datasetTypesByProject.get(key);
  }

  /**
   * Record one Name edit against the name the saved table knows.
   *
   * Renaming A to B and then B to C is one rename, A to C; renaming B back
   * to A is no rename at all.
   */
  function recordDatasetTypeRename(projectName, previousName, nextName) {
    const state = getProjectDatasetTypesState(projectName);
    const previousKey = canonDatasetTypeName(previousName);
    const nextKey = canonDatasetTypeName(nextName);
    if (!previousKey || !nextKey || previousKey === nextKey) return;
    let savedName = previousName;
    for (const [savedKey, entry] of state.renames) {
      if (canonDatasetTypeName(entry.to) === previousKey) {
        savedName = entry.from;
        state.renames.delete(savedKey);
        break;
      }
    }
    if (canonDatasetTypeName(savedName) === nextKey) return;
    state.renames.set(canonDatasetTypeName(savedName), { from: savedName, to: nextName });
  }

  /** Forget the rename that produced a row the grid no longer holds. */
  function forgetDatasetTypeRenameTo(projectName, name) {
    const state = getProjectDatasetTypesState(projectName);
    const key = canonDatasetTypeName(name);
    for (const [savedKey, entry] of state.renames) {
      if (canonDatasetTypeName(entry.to) === key) state.renames.delete(savedKey);
    }
  }

  function canonDatasetTypeName(value) {
    return String(value ?? "").trim().replace(/\s+/g, " ").toLowerCase();
  }

  function datasetTypeRenames(projectName) {
    return Array.from(getProjectDatasetTypesState(projectName).renames.values());
  }

  function getInvalidFormulaSet(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!datasetTypesInvalidFormulaByProject.has(key)) {
      datasetTypesInvalidFormulaByProject.set(key, new Set());
    }
    return datasetTypesInvalidFormulaByProject.get(key);
  }

  function clearInvalidFormulaSet(projectName) {
    const key = normalizeProjectKey(projectName);
    datasetTypesInvalidFormulaByProject.delete(key);
  }

  function clearInvalidFormulaName(projectName, name) {
    const set = getInvalidFormulaSet(projectName);
    const key = normalizeProjectKey(name);
    if (key) set.delete(key);
  }

  function setInvalidFormulaNames(projectName, names) {
    const set = getInvalidFormulaSet(projectName);
    set.clear();
    for (const n of names || []) {
      const key = normalizeProjectKey(n);
      if (key) set.add(key);
    }
  }

  function parseInvalidFormulaDatasetNames(detailText) {
    const out = new Set();
    const text = String(detailText || "");
    const re = /([A-Za-z0-9_ .\-]+):\s*unresolved in formula/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const name = String(m[1] || "").trim();
      const key = normalizeProjectKey(name);
      if (key) out.add(name);
    }
    return Array.from(out);
  }

  function parseCalculatedFlag(value) {
    if (typeof value === "boolean") return value;
    const s = String(value ?? "").trim().toLowerCase();
    return s === "true" || s === "1" || s === "yes" || s === "y";
  }

  function ensureDatasetTypesLoadModeDialog() {
    if (datasetTypesLoadModeDialog) return datasetTypesLoadModeDialog;

    const overlay = document.createElement("div");
    overlay.className = "dialog-overlay";
    overlay.innerHTML = `
      <div class="dialog-box" role="dialog" aria-modal="true" aria-labelledby="dtLoadModeTitle">
        <div class="dialog-title" id="dtLoadModeTitle">Load Dataset Types</div>
        <div class="dialog-message" data-role="message"></div>
        <div class="dialog-buttons">
          <button class="dialog-btn" type="button" data-role="cancel">Cancel</button>
          <button class="dialog-btn danger" type="button" data-role="overwrite">Overwrite</button>
          <button class="dialog-btn primary" type="button" data-role="merge">Merge</button>
        </div>
      </div>
    `;
    overlay.setAttribute("aria-hidden", "true");
    document.body.appendChild(overlay);

    const box = overlay.querySelector(".dialog-box");
    const cancelBtn = overlay.querySelector('[data-role="cancel"]');
    const overwriteBtn = overlay.querySelector('[data-role="overwrite"]');
    const mergeBtn = overlay.querySelector('[data-role="merge"]');

    const close = (mode) => {
      overlay.classList.remove("show");
      overlay.setAttribute("aria-hidden", "true");
      const resolve = datasetTypesLoadModeDialogResolve;
      datasetTypesLoadModeDialogResolve = null;
      if (typeof resolve === "function") resolve(mode || "cancel");
    };

    cancelBtn?.addEventListener("click", () => close("cancel"));
    overwriteBtn?.addEventListener("click", () => close("overwrite"));
    mergeBtn?.addEventListener("click", () => close("merge"));

    overlay.addEventListener("mousedown", (e) => {
      if (!box || !box.contains(e.target)) close("cancel");
    });

    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close("cancel");
      } else if (e.key === "Enter") {
        e.preventDefault();
        close("merge");
      }
    });

    overlay._dtLoadModeFocusBtn = mergeBtn;
    datasetTypesLoadModeDialog = overlay;
    return overlay;
  }

  function showDatasetTypesLoadModeDialog(messageText) {
    const overlay = ensureDatasetTypesLoadModeDialog();
    const messageEl = overlay.querySelector('[data-role="message"]');
    if (messageEl) {
      messageEl.textContent = String(messageText || "").trim();
    }

    if (datasetTypesLoadModeDialogResolve) {
      const prevResolve = datasetTypesLoadModeDialogResolve;
      datasetTypesLoadModeDialogResolve = null;
      prevResolve("cancel");
    }

    overlay.classList.add("show");
    overlay.setAttribute("aria-hidden", "false");

    setTimeout(() => {
      try {
        const focusBtn = overlay._dtLoadModeFocusBtn;
        if (focusBtn && typeof focusBtn.focus === "function") {
          focusBtn.focus();
        }
      } catch {
        // ignore focus failures
      }
    }, 30);

    return new Promise((resolve) => {
      datasetTypesLoadModeDialogResolve = resolve;
    });
  }

  function createEmptyDatasetTypesRow() {
    return ["", "", "", false, ""];
  }

  function sanitizeDatasetTypeRow(rowLike) {
    const out = createEmptyDatasetTypesRow();
    out[0] = String(rowLike?.[0] ?? "").trim();
    out[1] = String(rowLike?.[1] ?? "").trim();
    out[2] = String(rowLike?.[2] ?? "").trim();
    out[3] = parseCalculatedFlag(rowLike?.[3]);
    out[4] = out[3] ? String(rowLike?.[4] ?? "").trim() : "";
    return out;
  }

  function buildPersistableRows(rowList) {
    return (Array.isArray(rowList) ? rowList : [])
      .map((row) => sanitizeDatasetTypeRow(row))
      .filter((row) => row[0] !== "" || row[1] !== "" || row[2] !== "" || row[4] !== "" || row[3] === true);
  }

  function areDatasetTypeRowsExactlyEqual(rowsA, rowsB) {
    const left = Array.isArray(rowsA) ? rowsA.map((row) => sanitizeDatasetTypeRow(row)) : [];
    const right = Array.isArray(rowsB) ? rowsB.map((row) => sanitizeDatasetTypeRow(row)) : [];
    if (left.length !== right.length) return false;
    for (let i = 0; i < left.length; i += 1) {
      const l = left[i];
      const r = right[i];
      if (
        String(l?.[0] ?? "") !== String(r?.[0] ?? "")
        || String(l?.[1] ?? "") !== String(r?.[1] ?? "")
        || String(l?.[2] ?? "") !== String(r?.[2] ?? "")
        || Boolean(l?.[3]) !== Boolean(r?.[3])
        || String(l?.[4] ?? "") !== String(r?.[4] ?? "")
      ) {
        return false;
      }
    }
    return true;
  }

  function sanitizeFileStem(value) {
    return String(value || "").trim().replace(/[\\/:*?"<>|]/g, "_");
  }

  function joinWinPath(...parts) {
    const cleaned = parts
      .map((part) => String(part || "").trim().replace(/[\\/]+/g, "\\"))
      .filter(Boolean);
    return cleaned.join("\\");
  }

  function getDatasetTypesSortState(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!datasetTypesSortStateByProject.has(key)) {
      datasetTypesSortStateByProject.set(key, { colLabel: "", dir: "" });
    }
    return datasetTypesSortStateByProject.get(key);
  }

  function toggleDatasetTypesSort(projectName, colLabel) {
    const col = String(colLabel || "").trim();
    if (!DATASET_TYPES_SORTABLE_COLS.has(col)) return;
    const state = getDatasetTypesSortState(projectName);
    if (state.colLabel !== col) {
      state.colLabel = col;
      state.dir = "asc";
      return;
    }
    if (state.dir === "asc") {
      state.dir = "desc";
      return;
    }
    if (state.dir === "desc") {
      state.colLabel = "";
      state.dir = "";
      return;
    }
    state.dir = "asc";
  }

  function compareDatasetTypeSortValues(a, b, colLabel, dir) {
    const direction = String(dir || "").toLowerCase() === "desc" ? "desc" : "asc";
    let cmp = 0;
    if (colLabel === "Calculated") {
      cmp = (parseCalculatedFlag(a) ? 1 : 0) - (parseCalculatedFlag(b) ? 1 : 0);
    } else {
      const av = String(a ?? "").trim();
      const bv = String(b ?? "").trim();
      const an = Number(av);
      const bn = Number(bv);
      const aNum = av !== "" && Number.isFinite(an);
      const bNum = bv !== "" && Number.isFinite(bn);
      if (aNum && bNum) cmp = an - bn;
      else cmp = av.localeCompare(bv, undefined, { sensitivity: "base", numeric: true });
    }
    return direction === "desc" ? -cmp : cmp;
  }

  function getDatasetTypesFilterState(stateMap, projectName, options = []) {
    const key = normalizeProjectKey(projectName);
    if (!stateMap.has(key)) {
      const initialKeys = options.map((opt) => opt.key);
      stateMap.set(key, {
        selected: new Set(),
        known: new Set(initialKeys),
      });
    }
    const state = stateMap.get(key);
    const optionKeys = new Set((options || []).map((opt) => opt.key));

    for (const knownKey of Array.from(state.known)) {
      if (optionKeys.has(knownKey)) continue;
      state.known.delete(knownKey);
      state.selected.delete(knownKey);
    }
    for (const optionKey of optionKeys) {
      if (state.known.has(optionKey)) continue;
      state.known.add(optionKey);
    }
    return state;
  }

  function buildDatasetTypeNameOptions(projectName) {
    const state = getProjectDatasetTypesState(projectName);
    const options = buildDatasetTypeColumnFilterOptionsFromRows(state.rows || [], "Name", {
      blankKey: DATASET_TYPES_BLANK_CATEGORY_KEY,
    });
    datasetTypesNameOptionsByProject.set(normalizeProjectKey(projectName), options);
    return options;
  }
  function buildDatasetTypeDataFormatOptions(projectName) {
    const state = getProjectDatasetTypesState(projectName);
    const options = buildDatasetTypeColumnFilterOptionsFromRows(state.rows || [], "Data Format", {
      blankKey: DATASET_TYPES_BLANK_CATEGORY_KEY,
    });
    datasetTypesDataFormatOptionsByProject.set(normalizeProjectKey(projectName), options);
    return options;
  }

  function buildDatasetTypeCategoryOptions(projectName) {
    const state = getProjectDatasetTypesState(projectName);
    const options = buildDatasetTypeColumnFilterOptionsFromRows(state.rows || [], "Category", {
      blankKey: DATASET_TYPES_BLANK_CATEGORY_KEY,
    });
    datasetTypesCategoryOptionsByProject.set(normalizeProjectKey(projectName), options);
    return options;
  }

  function buildDatasetTypeCalculatedOptions(projectName) {
    const state = getProjectDatasetTypesState(projectName);
    const options = buildDatasetTypeColumnFilterOptionsFromRows(state.rows || [], "Calculated", {
      blankKey: DATASET_TYPES_BLANK_CATEGORY_KEY,
    });
    datasetTypesCalculatedOptionsByProject.set(normalizeProjectKey(projectName), options);
    return options;
  }

  function getDatasetTypeDataFormatFilterState(projectName, options = []) {
    return getDatasetTypesFilterState(datasetTypesDataFormatFilterStateByProject, projectName, options);
  }

  function getDatasetTypeNameFilterState(projectName, options = []) {
    return getDatasetTypesFilterState(datasetTypesNameFilterStateByProject, projectName, options);
  }

  function getDatasetTypeCategoryFilterState(projectName, options = []) {
    return getDatasetTypesFilterState(datasetTypesCategoryFilterStateByProject, projectName, options);
  }

  function getDatasetTypeCalculatedFilterState(projectName, options = []) {
    return getDatasetTypesFilterState(datasetTypesCalculatedFilterStateByProject, projectName, options);
  }

  function getDatasetTypesColumnFilterMeta(projectName, colLabel) {
    const project = String(projectName || "").trim();
    const col = String(colLabel || "").trim();
    if (!project || !col) return null;
    const key = normalizeProjectKey(project);

    if (col === "Name") {
      const options = datasetTypesNameOptionsByProject.get(key) || buildDatasetTypeNameOptions(project);
      const filterState = getDatasetTypeNameFilterState(project, options);
      return { col, options, filterState, title: "Name Filter", emptyText: "No dataset type names" };
    }
    if (col === "Category") {
      const options = datasetTypesCategoryOptionsByProject.get(key) || buildDatasetTypeCategoryOptions(project);
      const filterState = getDatasetTypeCategoryFilterState(project, options);
      return { col, options, filterState, title: "Category Filter", emptyText: "No categories" };
    }
    if (col === "Data Format") {
      const options = datasetTypesDataFormatOptionsByProject.get(key) || buildDatasetTypeDataFormatOptions(project);
      const filterState = getDatasetTypeDataFormatFilterState(project, options);
      return { col, options, filterState, title: "Data Format Filter", emptyText: "No data formats" };
    }
    if (col === "Calculated") {
      const options = datasetTypesCalculatedOptionsByProject.get(key) || buildDatasetTypeCalculatedOptions(project);
      const filterState = getDatasetTypeCalculatedFilterState(project, options);
      return { col, options, filterState, title: "Calculated Filter", emptyText: "No calculated values" };
    }
    return null;
  }

  function getDatasetTypesColumnFilterValueKey(colLabel, row) {
    return getDatasetTypeColumnFilterValueKeyFromRow(colLabel, row, {
      blankKey: DATASET_TYPES_BLANK_CATEGORY_KEY,
    });
  }

  function findDatasetTypesFilterButton(colLabel) {
    const table = document.getElementById("datasetTypesTable");
    if (!table) return null;
    const wanted = String(colLabel || "").trim();
    const headers = table.querySelectorAll("thead th");
    for (const th of headers) {
      if (String(th?.dataset?.dtColLabel || "").trim() !== wanted) continue;
      const btn = th.querySelector(".dt-filter-btn");
      if (btn) return btn;
    }
    return null;
  }

  function findDatasetTypesCategoryFilterButton() {
    return findDatasetTypesFilterButton("Category");
  }

  function closeDatasetTypesFilterPopover() {
    if (!datasetTypesFilterPopover) return;
    datasetTypesFilterPopover.style.display = "none";
    datasetTypesFilterPopover.classList.remove("open");
    datasetTypesFilterPopoverProject = "";
    datasetTypesFilterPopoverColLabel = "";
    datasetTypesFilterPopoverAnchor = null;
    datasetTypesFilterPopoverSearchText = "";
  }

  function closeDatasetTypesCategoryFilterPopover() {
    closeDatasetTypesFilterPopover();
  }

  function positionDatasetTypesFilterPopover() {
    if (!datasetTypesFilterPopover || datasetTypesFilterPopover.style.display === "none") return;
    const anchor =
      datasetTypesFilterPopoverAnchor
      || findDatasetTypesFilterButton(datasetTypesFilterPopoverColLabel || "Category");
    if (!anchor) {
      closeDatasetTypesFilterPopover();
      return;
    }

    const anchorRect = anchor.getBoundingClientRect();
    const pop = datasetTypesFilterPopover;
    pop.style.left = `${Math.round(anchorRect.left)}px`;
    pop.style.top = `${Math.round(anchorRect.bottom + 6)}px`;

    const rect = pop.getBoundingClientRect();
    const pad = 8;
    let left = rect.left;
    let top = rect.top;
    if (rect.right > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - rect.width - pad);
    }
    if (rect.bottom > window.innerHeight - pad) {
      top = Math.max(pad, anchorRect.top - rect.height - 6);
    }
    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  }

  function positionDatasetTypesCategoryFilterPopover() {
    positionDatasetTypesFilterPopover();
  }

  function ensureDatasetTypesFilterPopoverWired() {
    if (datasetTypesFilterPopoverWired) return;
    datasetTypesFilterPopoverWired = true;
    document.addEventListener("mousedown", (e) => {
      if (!datasetTypesFilterPopover || datasetTypesFilterPopover.style.display === "none") return;
      const target = e.target;
      if (datasetTypesFilterPopover.contains(target)) return;
      if (datasetTypesFilterPopoverAnchor && datasetTypesFilterPopoverAnchor.contains(target)) return;
      closeDatasetTypesFilterPopover();
    }, true);
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      closeDatasetTypesFilterPopover();
    }, true);
    window.addEventListener("resize", () => {
      positionDatasetTypesFilterPopover();
    });
    window.addEventListener("scroll", () => {
      positionDatasetTypesFilterPopover();
    }, true);
  }

  function ensureDatasetTypesFilterPopover() {
    ensureDatasetTypesFilterPopoverWired();
    if (datasetTypesFilterPopover) return datasetTypesFilterPopover;
    datasetTypesFilterPopover = document.createElement("div");
    datasetTypesFilterPopover.className = "dt-filter-popover";
    datasetTypesFilterPopover.style.display = "none";
    document.body.appendChild(datasetTypesFilterPopover);
    return datasetTypesFilterPopover;
  }

  function openDatasetTypesColumnFilterPopover(projectName, colLabel, anchorEl = null) {
    const project = String(projectName || "").trim();
    const col = String(colLabel || "").trim();
    if (!project || !col) return;
    const meta = getDatasetTypesColumnFilterMeta(project, col);
    if (!meta) return;

    const pop = ensureDatasetTypesFilterPopover();
    const { options, filterState, title: filterTitle, emptyText } = meta;
    const selectedSet = filterState.selected;

    pop.innerHTML = "";

    const title = document.createElement("div");
    title.className = "dt-filter-title";
    title.textContent = filterTitle;
    pop.appendChild(title);

    const search = document.createElement("input");
    search.className = "dt-filter-search";
    search.type = "search";
    search.autocomplete = "off";
    search.placeholder = "Type to search";
    search.setAttribute("aria-label", `Search ${col} filter values`);
    search.value = datasetTypesFilterPopoverProject === project && datasetTypesFilterPopoverColLabel === col
      ? datasetTypesFilterPopoverSearchText
      : "";
    pop.appendChild(search);

    const list = document.createElement("div");
    list.className = "dt-filter-list";
    pop.appendChild(list);

    const renderOptions = () => {
      list.replaceChildren();
      const searchText = String(search.value || "").trim().toLocaleLowerCase();
      const visibleOptions = searchText
        ? options.filter((opt) => String(opt.label || "").toLocaleLowerCase().includes(searchText))
        : options;

      const allRow = document.createElement("label");
      allRow.className = "dt-filter-option";
      const allCb = document.createElement("input");
      allCb.type = "checkbox";
      allCb.checked = selectedSet.size === 0 || !isDatasetTypeSelectionFilterActive(options, selectedSet);
      allCb.addEventListener("change", () => {
        selectedSet.clear();
        renderDatasetTypesTable(project, { preserveColumnWidths: true });
      });
      const allText = document.createElement("span");
      allText.textContent = "All";
      allRow.append(allCb, allText);
      list.appendChild(allRow);

      for (const opt of visibleOptions) {
        const row = document.createElement("label");
        row.className = "dt-filter-option";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = selectedSet.has(opt.key);
        cb.addEventListener("change", () => {
          if (cb.checked) selectedSet.add(opt.key);
          else selectedSet.delete(opt.key);
          renderDatasetTypesTable(project, { preserveColumnWidths: true });
        });
        row.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          event.stopPropagation();
          selectedSet.clear();
          for (const item of options) {
            if (item.key !== opt.key) selectedSet.add(item.key);
          }
          renderDatasetTypesTable(project, { preserveColumnWidths: true });
        });
        const text = document.createElement("span");
        text.textContent = opt.label;
        row.append(cb, text);
        list.appendChild(row);
      }

      if (!visibleOptions.length) {
        const none = document.createElement("div");
        none.className = "dt-filter-empty";
        none.textContent = options.length ? "No matching values" : emptyText;
        list.appendChild(none);
      }
    };
    search.addEventListener("input", () => {
      datasetTypesFilterPopoverSearchText = search.value;
      renderOptions();
    });
    renderOptions();

    datasetTypesFilterPopoverProject = project;
    datasetTypesFilterPopoverColLabel = col;
    datasetTypesFilterPopoverAnchor = anchorEl || findDatasetTypesFilterButton(col);
    pop.style.display = "block";
    pop.classList.add("open");
    positionDatasetTypesFilterPopover();
    search.focus({ preventScroll: true });
  }

  function openDatasetTypesCategoryFilterPopover(projectName, anchorEl = null) {
    openDatasetTypesColumnFilterPopover(projectName, "Category", anchorEl);
  }

  function syncDatasetTypesHeaderUi(projectName) {
    const table = document.getElementById("datasetTypesTable");
    if (!table) return;

    const sortState = getDatasetTypesSortState(projectName);

    const headers = table.querySelectorAll("thead th");
    headers.forEach((th, idx) => {
      const colLabel = DATASET_TYPES_COLUMNS[idx] || String(th.textContent || "").trim();
      th.dataset.dtColLabel = colLabel;
      th.dataset.dtProjectName = String(projectName || "");
      th.classList.add("dt-sortable-col");

      if (th.dataset.dtSortWired !== "1") {
        th.dataset.dtSortWired = "1";
        th.addEventListener("click", (e) => {
          const target = e.target;
          if (target?.closest?.(".table-col-resizer")) return;
          if (target?.closest?.(".dt-filter-btn")) return;
          const header = e.currentTarget;
          const col = String(header?.dataset?.dtColLabel || "").trim();
          const project = String(header?.dataset?.dtProjectName || "").trim();
          if (!col || !project) return;
          toggleDatasetTypesSort(project, col);
          renderDatasetTypesTable(project);
        });
      }

      const labelEl = th.querySelector(".table-col-label");
      if (!labelEl) {
        const wrapped = document.createElement("span");
        wrapped.className = "table-col-label";
        const nodesToMove = Array.from(th.childNodes).filter((node) => {
          return !(node.nodeType === 1 && node.classList?.contains("table-col-resizer"));
        });
        nodesToMove.forEach((node) => wrapped.appendChild(node));
        th.insertBefore(wrapped, th.querySelector(".table-col-resizer"));
      }
      const nextLabelEl = th.querySelector(".table-col-label");
      if (!nextLabelEl) return;
      nextLabelEl.innerHTML = "";
      nextLabelEl.classList.add("dt-col-label-wrap");

      const text = document.createElement("span");
      text.className = "dt-col-label-text";
      text.textContent = colLabel;
      nextLabelEl.appendChild(text);

      const indicator = document.createElement("span");
      indicator.className = "dt-sort-indicator";
      const isActiveSort = sortState.colLabel === colLabel && (sortState.dir === "asc" || sortState.dir === "desc");
      indicator.textContent = isActiveSort ? (sortState.dir === "asc" ? "\u25B2" : "\u25BC") : "";
      nextLabelEl.appendChild(indicator);
      th.classList.toggle("dt-col-sorted", isActiveSort);

      if (DATASET_TYPES_FILTERABLE_COLS.has(colLabel)) {
        const filterMeta = getDatasetTypesColumnFilterMeta(projectName, colLabel);
        const options = filterMeta?.options || [];
        const filterState = filterMeta?.filterState;
        const hasActiveFilter = !!filterState
          && isDatasetTypeSelectionFilterActive(options, filterState.selected);

        const filterBtn = document.createElement("button");
        filterBtn.type = "button";
        filterBtn.className = "dt-filter-btn";
        filterBtn.title = `${colLabel} Filter`;
        filterBtn.innerHTML = `
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M2 3h12L9.5 8v4l-3 1V8z"></path>
          </svg>
        `;
        filterBtn.classList.toggle("active", hasActiveFilter);
        filterBtn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const sameProjectOpen =
            datasetTypesFilterPopover
            && datasetTypesFilterPopover.style.display !== "none"
            && normalizeProjectKey(datasetTypesFilterPopoverProject) === normalizeProjectKey(projectName)
            && String(datasetTypesFilterPopoverColLabel || "").trim() === colLabel;
          if (sameProjectOpen) {
            closeDatasetTypesFilterPopover();
            return;
          }
          openDatasetTypesColumnFilterPopover(projectName, colLabel, filterBtn);
        });
        nextLabelEl.appendChild(filterBtn);
      }
    });

    const shouldReopenFilter =
      datasetTypesFilterPopover
      && datasetTypesFilterPopover.style.display !== "none"
      && normalizeProjectKey(datasetTypesFilterPopoverProject) === normalizeProjectKey(projectName)
      && String(datasetTypesFilterPopoverColLabel || "").trim() !== "";
    if (shouldReopenFilter) {
      const nextCol = String(datasetTypesFilterPopoverColLabel || "").trim();
      const nextAnchor = findDatasetTypesFilterButton(nextCol);
      if (nextAnchor) openDatasetTypesColumnFilterPopover(projectName, nextCol, nextAnchor);
      else closeDatasetTypesFilterPopover();
    }
  }

  function getDatasetTypeNamesForProject(projectName, opts = {}) {
    const onlyFormulaEmpty = !!opts?.formulaEmptyOnly;
    const state = getProjectDatasetTypesState(projectName);
    const out = [];
    const seen = new Set();
    for (const row of state.rows || []) {
      const name = String(row?.[0] ?? "").trim();
      if (!name) continue;
      if (onlyFormulaEmpty && String(row?.[4] ?? "").trim() !== "") continue;
      const key = name.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(name);
    }
    return out;
  }

  async function getFieldMappingDatasetTypeOwner(projectName, datasetTypeName) {
    const project = String(projectName || "").trim();
    const datasetType = String(datasetTypeName || "").trim();
    if (!project || !datasetType) return "";
    try {
      await ensureFieldMappingLoaded(project);
    } catch {
      // ignore read errors; save-time guard still runs against current state
    }
    return String(findDatasetTypeOwnerInFieldMapping(project, datasetType) || "").trim();
  }

  async function getFieldMappingDatasetTypeNames(projectName) {
    const project = String(projectName || "").trim();
    if (!project) return [];
    try {
      await ensureFieldMappingLoaded(project);
    } catch {
      // ignore read errors; caller will use the current in-memory state
    }
    const raw = getMappedDatasetTypeNamesInFieldMapping(project);
    const out = [];
    const seen = new Set();
    for (const value of Array.isArray(raw) ? raw : []) {
      const name = String(value || "").trim();
      const key = normalizeProjectKey(name);
      if (!name || !key || seen.has(key)) continue;
      seen.add(key);
      out.push(name);
    }
    return out;
  }

  function normalizeLocalDatasetTypesPayload(raw) {
    if (Array.isArray(raw)) return normalizeDatasetTypesPayload({ rows: raw });
    if (raw && typeof raw === "object") {
      if (raw.data && typeof raw.data === "object") {
        return normalizeDatasetTypesPayload(raw.data);
      }
      return normalizeDatasetTypesPayload(raw);
    }
    return normalizeDatasetTypesPayload(null);
  }

  function buildCalculatedBlockedMessage(datasetTypeName, ownerFieldName = "") {
    const name = String(datasetTypeName || "").trim() || "(unnamed)";
    const owner = String(ownerFieldName || "").trim();
    if (owner) {
      return `Cannot enable Calculated for '${name}' because it is used by field mapping field '${owner}'.`;
    }
    return `Cannot enable Calculated for '${name}' because it is used in field mapping.`;
  }

  function normalizeDatasetTypesPayload(payload) {
    const normalized = normalizeDatasetTypesPayloadShared(payload);
    const rows = [];
    for (const r of Array.isArray(normalized?.rows) ? normalized.rows : []) {
      const row = createEmptyDatasetTypesRow();
      row[0] = String(r?.[0] ?? "");
      row[1] = String(r?.[1] ?? "");
      row[2] = String(r?.[2] ?? "");
      row[3] = parseCalculatedFlag(r?.[3]);
      row[4] = String(r?.[4] ?? "");
      if (!row[3]) row[4] = "";
      rows.push(row);
    }
    return { columns: [...DATASET_TYPES_COLUMNS], rows };
  }

  /** Flowing placeholder rows while the types are read from the project folder. */
  function renderDatasetTypesLoading() {
    if (!datasetTypesBody) return;
    closeDatasetTypesCategoryFilterPopover();
    renderTableSkeletonRows(datasetTypesBody, { columns: 5 });
  }

  function renderDatasetTypesEmpty(message) {
    if (!datasetTypesBody) return;
    closeDatasetTypesCategoryFilterPopover();
    clearTableSkeletonRows(datasetTypesBody);
    datasetTypesBody.innerHTML = `
      <tr>
        <td colspan="5" class="dataset-types-empty">${escapeHtml(message || "No rows found.")}</td>
      </tr>
    `;
  }

  async function ensureDatasetTypesLoaded(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!key) return false;
    if (loadedDatasetTypesByProject.has(key)) return true;

    const state = getProjectDatasetTypesState(projectName);
    try {
      const fetched = await fetchProjectDatasetTypes(projectName, { fetchImpl });
      const parsed = normalizeDatasetTypesPayload(fetched?.data);
      state.columns = [...DATASET_TYPES_COLUMNS];
      state.rows = parsed.rows.map((r) => [
        String(r[0] ?? ""),
        String(r[1] ?? ""),
        String(r[2] ?? ""),
        parseCalculatedFlag(r[3]),
        String(r[4] ?? ""),
      ]);
      state.renames = new Map();
      loadedDatasetTypesByProject.add(key);
      return true;
    } catch (err) {
      setDatasetTypesStatus(`Load error: ${err.message}`, true);
      state.columns = [...DATASET_TYPES_COLUMNS];
      state.rows = [];
      return false;
    }
  }

  function showDatasetTypesRowContextMenu(x, y, projectName, rowIndex, cellText = "") {
    if (!datasetTypesRowContextMenu) return;
    closeDatasetTypesCategoryFilterPopover();
    datasetTypesContextProject = projectName || "";
    datasetTypesContextRowIndex = rowIndex;
    datasetTypesContextCellText = String(cellText ?? "");
    positionContextMenu(datasetTypesRowContextMenu, x, y);
  }

  function hideDatasetTypesRowContextMenu() {
    if (!datasetTypesRowContextMenu) return;
    datasetTypesRowContextMenu.classList.remove("show");
    datasetTypesContextProject = "";
    datasetTypesContextRowIndex = -1;
    datasetTypesContextCellText = "";
  }

  function closeDatasetTypeEditor() {
    if (!datasetTypeEditor) return;
    categoryCombo.close({ hideNewTip: true });
    formatSelect.close();
    datasetTypeEditor.classList.remove("show");
    datasetTypeEditor.style.left = "";
    datasetTypeEditor.style.top = "";
    datasetTypeEditor.style.transform = "translateX(-50%)";
    dtEditorProject = "";
    dtEditorRowIndex = -1;
    dtEditorMode = "edit";
    dtEditorInsertAfterIndex = -1;
    dtEditorDragState = null;
    dtEditorInitialCalculated = false;
  }

  function openDatasetTypeEditor(projectName, rowIndex, options = {}) {
    if (!datasetTypeEditor || !projectName) return;
    if (blockedByRunningChange(projectName)) return;
    const mode = String(options?.mode || "edit").toLowerCase() === "add" ? "add" : "edit";
    const state = getProjectDatasetTypesState(projectName);
    if (!Array.isArray(state.rows)) return;
    if (mode === "edit" && (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length)) return;
    const row = mode === "edit" ? state.rows[rowIndex] : null;

    if (datasetTypeEditorTitle) {
      datasetTypeEditorTitle.textContent = mode === "add"
        ? "Add Dataset Type"
        : "Edit Dataset Type";
    }
    if (dtEditName) dtEditName.value = mode === "add" ? "" : String(row?.[0] ?? "");
    formatSelect.setValue(mode === "add" ? "" : String(row?.[1] ?? ""));
    categoryCombo.setOptions(state.rows.map((item) => item?.[2]));
    categoryCombo.setValue(mode === "add" ? "" : String(row?.[2] ?? ""));
    const initialCalculated = mode === "add" ? false : parseCalculatedFlag(row?.[3]);
    if (dtEditCalculated) dtEditCalculated.checked = initialCalculated;
    if (dtEditFormula) {
      dtEditFormula.value = mode === "add" ? "" : String(row?.[4] ?? "");
      dtEditFormula.disabled = !(dtEditCalculated?.checked);
    }

    dtEditorProject = projectName;
    dtEditorMode = mode;
    dtEditorRowIndex = mode === "edit" ? rowIndex : -1;
    dtEditorInitialCalculated = initialCalculated;
    dtEditorInsertAfterIndex = Number.isInteger(options?.insertAfterIndex)
      ? options.insertAfterIndex
      : (Number.isInteger(rowIndex) ? rowIndex : -1);
    datasetTypeEditor.style.transform = "translateX(-50%)";
    datasetTypeEditor.style.left = "50%";
    datasetTypeEditor.style.top = "140px";
    datasetTypeEditor.classList.add("show");
    setTimeout(() => {
      if (dtEditName && !dtEditName.disabled) dtEditName.focus();
    }, 0);
  }

  async function applyDatasetTypeEditor() {
    const projectName = dtEditorProject;
    const mode = dtEditorMode;
    const rowIndex = dtEditorRowIndex;
    if (!projectName) return;
    if (blockedByRunningChange(projectName)) return;

    const state = getProjectDatasetTypesState(projectName);
    if (!Array.isArray(state.rows)) return;

    const nameValue = String(dtEditName?.value ?? "").trim();
    const dataFormatValue = String(dtEditDataFormat?.value ?? "").trim();
    const categoryValue = categoryCombo.getValue();
    const calculatedValue = !!(dtEditCalculated?.checked);
    const formulaValue = calculatedValue ? String(dtEditFormula?.value ?? "").trim() : "";

    if (!nameValue) {
      setDatasetTypesStatus("Name is required.", true);
      if (dtEditName) dtEditName.focus();
      return;
    }
    const isAllowedDataFormat = Array.from(dtEditDataFormat?.options || [])
      .some((option) => option.value === dataFormatValue && !option.disabled);
    if (!isAllowedDataFormat) {
      setDatasetTypesStatus("Choose Triangle or Vector for Data Format.", true);
      if (dtEditDataFormat) dtEditDataFormat.focus();
      return;
    }

    if (calculatedValue && !dtEditorInitialCalculated) {
      const owner = await getFieldMappingDatasetTypeOwner(projectName, nameValue);
      if (owner) {
        if (dtEditCalculated) dtEditCalculated.checked = false;
        if (dtEditFormula) dtEditFormula.disabled = true;
        setDatasetTypesStatus(buildCalculatedBlockedMessage(nameValue, owner), true);
        return;
      }
    }

    let target = null;
    if (mode === "edit") {
      if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length) return;
      target = state.rows[rowIndex];
    } else {
      const newRow = createEmptyDatasetTypesRow();
      const after = Number.isInteger(dtEditorInsertAfterIndex) ? dtEditorInsertAfterIndex : -1;
      const insertPos = Math.max(0, Math.min(state.rows.length, after + 1));
      state.rows.splice(insertPos, 0, newRow);
      target = state.rows[insertPos];
    }
    if (!Array.isArray(target)) return;

    if (mode === "edit") recordDatasetTypeRename(projectName, target[0], nameValue);
    target[0] = nameValue;
    target[1] = dataFormatValue;
    target[2] = categoryValue;
    target[3] = calculatedValue;
    target[4] = formulaValue;

    renderDatasetTypesTable(projectName);
    setDatasetTypesStatus("");
    scheduleDatasetTypesAutoSave(projectName);
    closeDatasetTypeEditor();
  }

  async function handleDatasetTypeEditorCalculatedToggle() {
    if (!dtEditCalculated) return;
    if (!dtEditCalculated.checked) {
      if (dtEditFormula) dtEditFormula.disabled = true;
      return;
    }
    const projectName = String(dtEditorProject || "").trim();
    const nameValue = String(dtEditName?.value ?? "").trim();
    if (!projectName || !nameValue) {
      if (dtEditFormula) dtEditFormula.disabled = false;
      return;
    }
    const owner = await getFieldMappingDatasetTypeOwner(projectName, nameValue);
    if (owner) {
      dtEditCalculated.checked = false;
      if (dtEditFormula) dtEditFormula.disabled = true;
      setDatasetTypesStatus(buildCalculatedBlockedMessage(nameValue, owner), true);
      return;
    }
    if (dtEditFormula) dtEditFormula.disabled = false;
    setDatasetTypesStatus("");
  }

  function onEditorHeaderMouseDown(e) {
    if (!datasetTypeEditor || e.button !== 0) return;
    const rect = datasetTypeEditor.getBoundingClientRect();
    datasetTypeEditor.style.left = `${rect.left}px`;
    datasetTypeEditor.style.top = `${rect.top}px`;
    datasetTypeEditor.style.transform = "none";
    dtEditorDragState = {
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    e.preventDefault();
  }

  function onEditorMouseMove(e) {
    if (!datasetTypeEditor || !dtEditorDragState) return;
    const left = Math.max(8, Math.min(window.innerWidth - datasetTypeEditor.offsetWidth - 8, e.clientX - dtEditorDragState.offsetX));
    const top = Math.max(8, Math.min(window.innerHeight - datasetTypeEditor.offsetHeight - 8, e.clientY - dtEditorDragState.offsetY));
    datasetTypeEditor.style.left = `${left}px`;
    datasetTypeEditor.style.top = `${top}px`;
    categoryCombo.positionFloating();
    formatSelect.positionFloating();
  }

  function onEditorMouseUp() {
    dtEditorDragState = null;
  }

  function addDatasetTypesRow(projectName, insertIndex) {
    if (blockedByRunningChange(projectName)) return;
    const state = getProjectDatasetTypesState(projectName);
    const blank = createEmptyDatasetTypesRow();
    const idx = Number(insertIndex);
    const pos = Number.isInteger(idx) ? Math.max(0, Math.min(state.rows.length, idx)) : state.rows.length;
    state.rows.splice(pos, 0, blank);
    renderDatasetTypesTable(projectName);
  }

  function deleteDatasetTypesRow(projectName, rowIndex) {
    if (blockedByRunningChange(projectName)) return;
    const state = getProjectDatasetTypesState(projectName);
    if (!state.rows.length) return;
    if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length) return;
    forgetDatasetTypeRenameTo(projectName, state.rows[rowIndex]?.[0]);
    state.rows.splice(rowIndex, 1);
    if (!state.rows.length) {
      state.rows.push(createEmptyDatasetTypesRow());
    }
    renderDatasetTypesTable(projectName);
    scheduleDatasetTypesAutoSave(projectName);
  }

  function renderDatasetTypesTable(projectName, options = {}) {
    if (!datasetTypesBody) return;
    if (!projectName) {
      renderDatasetTypesEmpty("Select a project to load dataset types.");
      return;
    }

    const state = getProjectDatasetTypesState(projectName);
    const invalidSet = getInvalidFormulaSet(projectName);
    if (!Array.isArray(state.rows) || state.rows.length === 0) {
      state.rows = [createEmptyDatasetTypesRow()];
    }

    for (let rowIndex = 0; rowIndex < state.rows.length; rowIndex++) {
      const rowValues = state.rows[rowIndex];
      if (!Array.isArray(rowValues)) {
        state.rows[rowIndex] = createEmptyDatasetTypesRow();
        continue;
      }
      if (rowValues.length < DATASET_TYPES_COLUMNS.length) {
        const fallback = createEmptyDatasetTypesRow();
        for (let i = 0; i < rowValues.length && i < DATASET_TYPES_COLUMNS.length; i++) {
          fallback[i] = rowValues[i];
        }
        state.rows[rowIndex] = fallback;
      }
    }

    const dataFormatOptions = buildDatasetTypeDataFormatOptions(projectName);
    const dataFormatFilter = getDatasetTypeDataFormatFilterState(projectName, dataFormatOptions);
    const nameOptions = buildDatasetTypeNameOptions(projectName);
    const nameFilter = getDatasetTypeNameFilterState(projectName, nameOptions);
    const categoryOptions = buildDatasetTypeCategoryOptions(projectName);
    const categoryFilter = getDatasetTypeCategoryFilterState(projectName, categoryOptions);
    const calculatedOptions = buildDatasetTypeCalculatedOptions(projectName);
    const calculatedFilter = getDatasetTypeCalculatedFilterState(projectName, calculatedOptions);
    const dataFormatSelected = dataFormatFilter.selected;
    const nameSelected = nameFilter.selected;
    const categorySelected = categoryFilter.selected;
    const calculatedSelected = calculatedFilter.selected;
    const collapsedGroups = getCollapsedGroups("datasetTypesTable");
    const sortState = getDatasetTypesSortState(projectName);
    const sortColIdx = DATASET_TYPES_COLUMNS.indexOf(String(sortState.colLabel || "").trim());
    const sortDir = String(sortState.dir || "").trim().toLowerCase();

    const groups = new Map();
    state.rows.forEach((row, rowIndex) => {
      if (nameSelected.size > 0 && !nameSelected.has(getDatasetTypesColumnFilterValueKey("Name", row))) return;
      if (dataFormatSelected.size > 0 && !dataFormatSelected.has(getDatasetTypesColumnFilterValueKey("Data Format", row))) return;
      if (calculatedSelected.size > 0 && !calculatedSelected.has(getDatasetTypesColumnFilterValueKey("Calculated", row))) return;
      const categoryLabel = getDatasetTypeCategoryLabel(row?.[2]);
      const categoryKey = getDatasetTypeCategoryKey(row?.[2]);
      if (!groups.has(categoryKey)) {
        groups.set(categoryKey, {
          key: categoryKey,
          label: categoryLabel,
          rows: [],
        });
      }
      groups.get(categoryKey).rows.push({ row, rowIndex });
    });

    const sortedGroups = Array.from(groups.values()).sort((a, b) =>
      String(a.label || "").localeCompare(String(b.label || ""), undefined, { sensitivity: "base", numeric: true }),
    );
    const visibleGroups = categorySelected.size > 0
      ? sortedGroups.filter((group) => categorySelected.has(group.key))
      : sortedGroups;

    clearTableSkeletonRows(datasetTypesBody);
    datasetTypesBody.innerHTML = "";

    if (visibleGroups.length === 0) {
      datasetTypesBody.innerHTML = `
        <tr>
          <td colspan="5" class="dataset-types-empty">No rows for selected filters.</td>
        </tr>
      `;
    } else {
      for (const group of visibleGroups) {
        const isCollapsed = collapsedGroups.has(group.key);
        const setCollapsed = (keys, collapsed) => {
          for (const key of keys) {
            if (collapsed) collapsedGroups.add(key);
            else collapsedGroups.delete(key);
          }
          saveCollapsedGroups("datasetTypesTable");
          renderDatasetTypesTable(projectName);
        };
        const allKeys = visibleGroups.map((item) => item.key);
        datasetTypesBody.appendChild(createTableGroupRow({
          text: `Category: ${group.label}`,
          colSpan: DATASET_TYPES_COLUMNS.length,
          collapsed: isCollapsed,
          count: group.rows.length,
          onToggle: () => setCollapsed([group.key], !isCollapsed),
          onContextMenu: (event) => showTableGroupContextMenu(event.clientX, event.clientY, {
            collapseAll: () => setCollapsed(allKeys, true),
            expandAll: () => setCollapsed(allKeys, false),
          }),
        }));

        if (isCollapsed) continue;

        const rowsToRender = group.rows.slice();
        if (sortColIdx >= 0 && (sortDir === "asc" || sortDir === "desc")) {
          rowsToRender.sort((a, b) => {
            const cmp = compareDatasetTypeSortValues(
              a?.row?.[sortColIdx],
              b?.row?.[sortColIdx],
              DATASET_TYPES_COLUMNS[sortColIdx],
              sortDir,
            );
            if (cmp !== 0) return cmp;
            return (a?.rowIndex ?? 0) - (b?.rowIndex ?? 0);
          });
        }

        for (const rowItem of rowsToRender) {
          const rowIndex = rowItem.rowIndex;
          const tr = document.createElement("tr");
          tr.dataset.rowIndex = String(rowIndex);

          DATASET_TYPES_COLUMNS.forEach((colName, colIndex) => {
            const td = document.createElement("td");
            td.dataset.col = colName;
            td.dataset.colIndex = String(colIndex);
            const rowName = String(state.rows[rowIndex][0] ?? "").trim();
            const isInvalidFormulaCell = colName === "Formula" && invalidSet.has(normalizeProjectKey(rowName));

            if (colName === "Calculated") {
              const checkbox = document.createElement("input");
              checkbox.type = "checkbox";
              checkbox.checked = parseCalculatedFlag(state.rows[rowIndex][3]);
              checkbox.disabled = true;
              td.style.textAlign = "center";
              td.appendChild(checkbox);
            } else {
              const raw = String(state.rows[rowIndex][colIndex] ?? "");
              const span = document.createElement("span");
              span.textContent = colName === "Formula"
                ? displayDatasetTypeFormula(state.rows, raw)
                : raw;
              // Copy and the row editor want what is stored, not how it reads.
              if (colName === "Formula" && span.textContent !== raw) td.dataset.rawValue = raw;
              td.appendChild(span);
            }
            if (isInvalidFormulaCell) {
              td.classList.add("invalid-formula-cell");
              td.title = "Invalid formula: unresolved source value.";
            }

            tr.appendChild(td);
          });

          tr.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            e.stopPropagation();
            hideContextMenu();
            hideFolderContextMenu();
            hideTreeContextMenu();
            hideReservingClassTypesRowContextMenu();
            const cell = e.target?.closest?.("td");
            let cellText = cell ? String(cell.dataset?.rawValue ?? cell.textContent ?? "") : "";
            const checkbox = cell?.querySelector?.('input[type="checkbox"]');
            if (checkbox) cellText = checkbox.checked ? "TRUE" : "FALSE";
            showDatasetTypesRowContextMenu(e.clientX, e.clientY, projectName, rowIndex, cellText);
          });

          datasetTypesBody.appendChild(tr);
        }
      }
    }

    datasetTypesBody.querySelectorAll("textarea").forEach(resizeCellTextarea);
    syncDatasetTypesHeaderUi(projectName);
    if (!options || !options.preserveColumnWidths) {
      initTableColumnResizing("datasetTypesTable", [150, 120, 130, 110, 140]);
    }
  }

  async function loadDatasetTypes(projectName) {
    const requestSeq = ++datasetTypesLoadSeq;
    if (!projectName) {
      closeDatasetTypesCategoryFilterPopover();
      renderDatasetTypesEmpty("Select a project to load dataset types.");
      setDatasetTypesStatus("");
      return;
    }

    if (
      datasetTypesFilterPopover
      && datasetTypesFilterPopover.style.display !== "none"
      && normalizeProjectKey(datasetTypesFilterPopoverProject) !== normalizeProjectKey(projectName)
    ) {
      closeDatasetTypesCategoryFilterPopover();
    }

    setDatasetTypesStatus("Loading dataset types...");
    // A cached project renders in the same tick; only a real read needs the frame.
    if (!loadedDatasetTypesByProject.has(normalizeProjectKey(projectName))) {
      renderDatasetTypesLoading();
    }
    const loadedOk = await ensureDatasetTypesLoaded(projectName);
    if (requestSeq !== datasetTypesLoadSeq) return;
    renderDatasetTypesTable(projectName);
    const selectedProject = getSelectedProject();
    const currentFieldNames = getCurrentFieldNames();
    if (
      selectedProject &&
      normalizeProjectKey(selectedProject.name) === normalizeProjectKey(projectName) &&
      Array.isArray(currentFieldNames) &&
      currentFieldNames.length > 0
    ) {
      renderFieldMappingTable(currentFieldNames, projectName);
    }
    if (loadedOk) setDatasetTypesStatus("");
  }

  /**
   * Report what one finished dataset-type change did, or why it stopped.
   *
   * A change to this table is rare and rebuilds data the user cannot see from
   * here, so its outcome gets a dialog rather than a status line that the next
   * message would overwrite.
   */
  function showDatasetTypesChangeDialog({ summary, failures = [], failed = false }) {
    const summaryText = String(summary || "").trim();
    const failureLines = (failures || [])
      .map((line) => String(line || "").trim())
      .filter(Boolean);
    if (!summaryText && !failureLines.length) return;

    const overlay = document.createElement("div");
    overlay.className = "datasetTypesRecalcOverlay";
    const box = document.createElement("div");
    box.className = "datasetTypesRecalcBox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    const close = document.createElement("button");
    close.className = "datasetTypesRecalcClose";
    close.type = "button";
    close.setAttribute("aria-label", "Close");
    close.textContent = "x";
    const title = document.createElement("div");
    title.className = "datasetTypesRecalcTitle";
    title.textContent = failed ? "Dataset Type Change Failed" : "Dataset Type Change Complete";
    const summaryEl = document.createElement("div");
    summaryEl.className = "datasetTypesRecalcSummary";
    summaryEl.textContent = summaryText;
    // Only a run with something to list gets the list. An empty bordered box
    // reads as a progress bar that never filled, which is exactly the wrong
    // thing to show beside "complete".
    const list = document.createElement("div");
    list.className = "datasetTypesRecalcList";
    failureLines.forEach((line, index) => {
      const item = document.createElement("div");
      item.className = "datasetTypesRecalcItem";
      const name = document.createElement("div");
      name.className = "datasetTypesRecalcName";
      name.textContent = `${index + 1}. Not completed`;
      const meta = document.createElement("div");
      meta.className = "datasetTypesRecalcMeta";
      meta.textContent = line;
      item.append(name, meta);
      list.appendChild(item);
    });
    const actions = document.createElement("div");
    actions.className = "datasetTypesRecalcActions";
    const ok = document.createElement("button");
    ok.className = "dataset-types-action";
    ok.type = "button";
    ok.textContent = "OK";
    actions.appendChild(ok);
    box.append(close, title, summaryEl);
    if (failureLines.length) box.appendChild(list);
    box.appendChild(actions);
    overlay.appendChild(box);
    const dismiss = () => overlay.remove();
    close.addEventListener("click", dismiss);
    ok.addEventListener("click", dismiss);
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) dismiss();
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") dismiss();
    });
    document.body.appendChild(overlay);
    ok.focus();
  }

  /**
   * Show which reserving classes a change reaches, and let the user decide.
   *
   * Apply submits the very same table with the plan attached, which is what
   * turns it into the Engine job; the Engine checks the plan again under its
   * lock before it writes anything. Cancel throws the edit away and shows the
   * saved table, because a change the user declined must not sit in the grid
   * looking saved.
   */
  function showDatasetTypesPlanDialog(projectName, planned) {
    const affected = Array.isArray(planned?.plan?.affected) ? planned.plan.affected : [];
    const classesTotal = Math.max(0, Number(planned?.classes_total) || 0);
    const renamed = Array.isArray(planned?.renames) ? planned.renames : [];
    const plural = (count, singular, pluralWord = `${singular}s`) =>
      `${count} ${count === 1 ? singular : pluralWord}`;

    const overlay = document.createElement("div");
    overlay.className = "datasetTypesRecalcOverlay";
    const box = document.createElement("div");
    box.className = "datasetTypesRecalcBox";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    const title = document.createElement("div");
    title.className = "datasetTypesRecalcTitle";
    title.textContent = "Confirm Dataset Type Change";
    const summaryEl = document.createElement("div");
    summaryEl.className = "datasetTypesRecalcSummary";
    const renameText = renamed.length
      ? ` ${renamed.map((entry) => `"${entry.from}" becomes "${entry.to}"`).join("; ")}.`
      : "";
    summaryEl.textContent =
      `This change reaches ${plural(affected.length, "reserving class", "reserving classes")}`
      + (classesTotal ? ` of ${classesTotal}` : "")
      + ". Only those are locked while it is applied; every other reserving class stays available."
      + renameText;
    const list = document.createElement("div");
    list.className = "datasetTypesRecalcList";
    affected.forEach((entry) => {
      const item = document.createElement("div");
      item.className = "datasetTypesRecalcItem";
      const name = document.createElement("div");
      name.className = "datasetTypesRecalcName";
      name.textContent = String(entry.reserving_class || "");
      const meta = document.createElement("div");
      meta.className = "datasetTypesRecalcMeta";
      const parts = [plural(Number(entry.instances) || 0, "dataset")];
      if (entry.reason) parts.push(String(entry.reason));
      const adopting = Number(entry.adopting) || 0;
      const renaming = Number(entry.renaming) || 0;
      if (adopting) {
        parts.push(
          `${adopting} take the new type name`
          + (renaming ? `, ${renaming} of them renamed with it` : ""),
        );
      }
      meta.textContent = parts.join(" - ");
      item.append(name, meta);
      list.appendChild(item);
    });
    const actions = document.createElement("div");
    actions.className = "datasetTypesRecalcActions rct-row-editor-actions";
    const cancel = document.createElement("button");
    cancel.className = "dialog-btn";
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const apply = document.createElement("button");
    apply.className = "dialog-btn primary";
    apply.type = "button";
    apply.textContent = "Apply";
    actions.append(cancel, apply);
    box.append(title, summaryEl, list, actions);
    overlay.appendChild(box);

    const dismiss = () => overlay.remove();
    cancel.addEventListener("click", async () => {
      dismiss();
      await discardDatasetTypesEdits(projectName);
    });
    apply.addEventListener("click", async () => {
      dismiss();
      // The planner rewrote the formulas that named a renamed type, so the
      // grid adopts its rows: what the Engine writes is what is on screen.
      const state = getProjectDatasetTypesState(projectName);
      state.rows = buildPersistableRows(planned.rows);
      renderDatasetTypesTable(projectName);
      await saveDatasetTypes(projectName, {
        plan: planned.plan,
        rows: buildPersistableRows(state.rows),
      });
    });
    overlay.addEventListener("keydown", (event) => {
      if (event.key === "Escape") cancel.click();
    });
    document.body.appendChild(overlay);
    apply.focus();
  }

  /** Put the saved table back after a declined change. */
  async function discardDatasetTypesEdits(projectName) {
    const key = normalizeProjectKey(projectName);
    loadedDatasetTypesByProject.delete(key);
    lastSubmissionByProject.delete(key);
    clearInvalidFormulaSet(projectName);
    await loadDatasetTypes(projectName);
    setDatasetTypesStatus("Dataset type change cancelled. The saved table is shown.");
    setStatus(`Dataset type change cancelled: ${projectName}`);
  }

  /** Whether a project's dataset-type change job is still running. */
  function isDatasetTypesChangeRunning(projectName) {
    return runningChangeJobByProject.has(normalizeProjectKey(projectName));
  }

  /**
   * Refuse an edit while the project is being rebuilt, and say why.
   *
   * Called by every mutating entry point rather than by the save: a change
   * accepted into the grid now would sit there unsaved until the job ended,
   * which is exactly the divergence this whole flow exists to prevent.
   */
  function blockedByRunningChange(projectName) {
    if (!isDatasetTypesChangeRunning(projectName)) return false;
    setDatasetTypesStatus(
      "Dataset types are being applied for this project. Please wait for that to finish.",
      true,
    );
    return true;
  }

  /**
   * Reuse the previous request id when this is a retry of the same table.
   *
   * The server returns an already-published job untouched, so replaying an id
   * under different rows would silently drop the newer edit.
   */
  function requestIdForSubmission(projectName, rows) {
    const key = normalizeProjectKey(projectName);
    const signature = datasetTypesRowsSignature(rows);
    const previous = lastSubmissionByProject.get(key);
    if (previous && previous.signature === signature && previous.requestId) {
      return { requestId: previous.requestId, signature };
    }
    return { requestId: createDatasetTypesChangeRequestId(), signature };
  }

  // The job counts different things in different stages, and a bar labelled in
  // the wrong unit is worse than no bar. The stage says which.
  const CHANGE_PROGRESS_UNITS = {
    scanning: "reserving classes",
    recalculate: "reserving classes",
    index: "reserving classes",
  };

  function reportChangeProgress(projectName, progress) {
    const label = String(progress?.label || "").trim() || "Applying dataset type changes...";
    const total = Math.max(0, Number(progress?.total) || 0);
    const completed = Math.max(0, Number(progress?.completed) || 0);
    const stage = String(progress?.stage || "").trim().toLowerCase();
    changeProgressPopup.show(label, {
      progress: {
        completed,
        total,
        unit: CHANGE_PROGRESS_UNITS[stage] || "datasets",
      },
    });
    // The shell status bar is the only place this is still worth echoing: the
    // page itself is behind the popup.
    setStatus(`Dataset types: ${label}`);
  }

  /**
   * Follow a submitted change job, then show the project's saved table again.
   *
   * The job wrote the file, so the rows held here are no longer the authority:
   * on success the cache is dropped and the table is re-read, which is also
   * what makes a change another user made visible.
   */
  async function followDatasetTypesChangeJob(projectName, jobId) {
    const key = normalizeProjectKey(projectName);
    runningChangeJobByProject.set(key, jobId);
    renderDatasetTypesTable(projectName);
    changeProgressPopup.show("Queued for Arco Engine", {
      progress: { completed: 0, total: 0, unit: "datasets" },
    });
    try {
      const terminal = await waitForDatasetTypesChangeJob({
        fetchImpl,
        projectName,
        jobId,
        onProgress: (progress) => reportChangeProgress(projectName, progress),
      });
      runningChangeJobByProject.delete(key);
      changeProgressPopup.hide();
      // The grid is read-only for the life of the job, but not while the
      // submission itself was in flight: an edit made in that window is newer
      // than the table the Engine just wrote and must survive the reload.
      const submitted = lastSubmissionByProject.get(key);
      const pendingRows = buildPersistableRows(
        getProjectDatasetTypesState(projectName).rows || [],
      );
      const editedWhileSubmitting = Boolean(submitted)
        && submitted.signature !== datasetTypesRowsSignature(pendingRows);
      lastSubmissionByProject.delete(key);
      // The renames the job carried have reached every instance; an edit made
      // while it ran starts its own list from the table the job wrote.
      getProjectDatasetTypesState(projectName).renames = new Map();
      clearInvalidFormulaSet(projectName);
      const summary = describeDatasetTypesChangeResult(terminal);

      if (editedWhileSubmitting) {
        const message = `${summary} Your later edits are not saved yet - saving them now.`;
        renderDatasetTypesTable(projectName);
        setDatasetTypesStatus(message);
        setStatus(`Dataset types applied with later edits pending: ${projectName}`);
        showDatasetTypesChangeDialog({ summary: message });
        scheduleDatasetTypesAutoSave(projectName);
        await loadAuditLog(projectName, true);
        return true;
      }

      // Re-read rather than trust the rows that were submitted: the Engine
      // resolved each row's Source and Generated while it wrote them.
      loadedDatasetTypesByProject.delete(key);
      await loadDatasetTypes(projectName);
      setDatasetTypesStatus(summary);
      setStatus(`Dataset types applied: ${projectName}`);
      showDatasetTypesChangeDialog({ summary });
      await loadAuditLog(projectName, true);
      return true;
    } catch (err) {
      runningChangeJobByProject.delete(key);
      changeProgressPopup.hide();
      // The table stays on screen exactly as the user left it: the file may or
      // may not have been written, so the next save is the user's decision.
      const message = String(err?.message || err || "The dataset type change failed.");
      // A job the Engine finished in error is a decided outcome, so the next
      // attempt must be a new submission. A status this page could not read is
      // not: keeping that id lets the retry re-attach to the same running job.
      if (err?.code === "DATASET_TYPES_CHANGE_JOB_ERROR") {
        lastSubmissionByProject.delete(key);
      }
      renderDatasetTypesTable(projectName);
      setDatasetTypesStatus(`Dataset type change failed: ${message}`, true);
      setStatus(`Dataset type change failed: ${message}`);
      showDatasetTypesChangeDialog({
        summary: "The dataset type table on screen has not been confirmed as saved.",
        failures: [message],
        failed: true,
      });
      await loadAuditLog(projectName, true);
      return false;
    }
  }

  /**
   * Save the table, directly or as a project-wide job.
   *
   * The request itself always answers quickly. A change that re-derives
   * nothing outside the table is written by the app server and confirmed here.
   * Anything that touches names, formulas or formats comes back first as a
   * plan naming the reserving classes it reaches; the user confirms that
   * list, the confirming request submits the ArcRho Engine job that holds
   * exactly those classes, and this module then follows the job to its end.
   *
   * ``confirmed`` is the plan the user accepted, passed by the dialog's own
   * submission; an auto-save never carries one.
   */
  async function saveDatasetTypes(projectName, confirmed = null) {
    if (!projectName) return false;
    if (isDatasetTypesChangeRunning(projectName)) return false;
    const key = normalizeProjectKey(projectName);
    const state = getProjectDatasetTypesState(projectName);
    const rows = confirmed ? confirmed.rows : buildPersistableRows(state.rows || []);
    const renames = datasetTypeRenames(projectName);
    const { requestId, signature } = requestIdForSubmission(projectName, rows);

    setDatasetTypesStatus(confirmed ? "Submitting dataset type change..." : "Saving dataset types...");
    let res;
    try {
      res = await fetchImpl("/dataset_types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: projectName,
          columns: [...DATASET_TYPES_COLUMNS],
          rows,
          renames,
          plan: confirmed ? confirmed.plan : null,
          request_id: requestId,
        }),
      });
    } catch (err) {
      // The request may or may not have reached the server, so the id is kept:
      // replaying it is what makes the retry safe.
      lastSubmissionByProject.set(key, { requestId, signature });
      const detail = String(err?.message || err || "Network request failed.");
      setDatasetTypesStatus(`Save error: ${detail}`, true);
      setStatus(`Dataset types save error: ${detail}`);
      return false;
    }

    if (!res.ok) {
      let detail = "";
      try {
        const body = await res.json();
        detail = String(body?.detail || "").trim();
      } catch {
        try {
          detail = String((await res.text()) || "").trim();
        } catch {
          detail = "";
        }
      }
      detail = detail || `HTTP ${res.status}`;
      // A refusal is a decision, not a lost request: the server did not accept
      // this id, so the next attempt must submit a new one.
      lastSubmissionByProject.delete(key);
      const invalidNames = parseInvalidFormulaDatasetNames(detail);
      setInvalidFormulaNames(projectName, invalidNames);
      renderDatasetTypesTable(projectName);
      setDatasetTypesStatus(`Save error: ${detail}`, true);
      setStatus(`Dataset types save error: ${detail}`);
      return false;
    }

    const out = await res.json();
    clearInvalidFormulaSet(projectName);

    if (String(out?.applied || "") === "plan") {
      // Nothing was submitted: the dialog's Apply sends this same request
      // again with the plan, and Cancel puts the saved table back.
      lastSubmissionByProject.delete(key);
      setDatasetTypesStatus("Review the reserving classes this change affects.");
      showDatasetTypesPlanDialog(projectName, out);
      return true;
    }

    if (String(out?.applied || "") !== "job") {
      lastSubmissionByProject.delete(key);
      state.renames = new Map();
      renderDatasetTypesTable(projectName);
      setDatasetTypesStatus(`Saved dataset types to ${out.path}`);
      setStatus(`Saved dataset types: ${projectName}`);
      await loadAuditLog(projectName, true);
      return true;
    }

    const jobId = String(out?.job?.job_id || "").trim();
    if (!jobId) {
      lastSubmissionByProject.delete(key);
      setDatasetTypesStatus("Save error: Arco Engine did not return a job id.", true);
      return false;
    }
    lastSubmissionByProject.set(key, { requestId, signature });
    // The job runs for as long as the project needs; following it is not part
    // of this request. Awaiting it here would hold the auto-save scheduler's
    // single-flight slot for minutes, and the running-job state below is what
    // actually keeps the table from being edited meanwhile.
    runningChangeJobPromise = followDatasetTypesChangeJob(projectName, jobId);
    return true;
  }

  /** Resolve once the running change job (if any) has finished. */
  async function waitForRunningDatasetTypesChange() {
    await runningChangeJobPromise;
  }

  async function saveDatasetTypesToLocalFile(projectName) {
    const name = String(projectName || "").trim();
    if (!name) {
      setDatasetTypesStatus("Select a project first.", true);
      return;
    }

    const hostApi = window.ADAHost || window.parent?.ADAHost || window.top?.ADAHost;
    if (!hostApi?.saveJsonFile) {
      setDatasetTypesStatus("Local save is available in the desktop app only.", true);
      return;
    }

    const state = getProjectDatasetTypesState(name);
    const rows = buildPersistableRows(state.rows || []);
    const safeName = sanitizeFileStem(name) || "project";
    const suggestedName = `${safeName}_dataset_types.json`;
    let startDir = "";
    try {
      const docsPath = String((await hostApi.getDocumentsPath?.()) || "").trim();
      if (docsPath) {
        startDir = joinWinPath(docsPath, "ArcRho", "templates");
      }
    } catch {
      startDir = "";
    }

    setDatasetTypesStatus("Saving dataset types to local file...");
    try {
      const result = await hostApi.saveJsonFile({
        data: {
          project_name: name,
          columns: [...DATASET_TYPES_COLUMNS],
          rows,
        },
        suggestedName,
        startDir,
        filters: [{ name: "JSON", extensions: ["json"] }],
      });
      if (result?.canceled) {
        setDatasetTypesStatus("Local save canceled.");
        return;
      }
      if (result?.error) {
        throw new Error(String(result.error || "Unable to save local file."));
      }
      const outPath = String(result?.path || "").trim();
      setDatasetTypesStatus(outPath ? `Saved local dataset types: ${outPath}` : "Saved local dataset types.");
      setStatus(outPath ? `Saved Dataset Types local file: ${outPath}` : "Saved Dataset Types local file.");
    } catch (err) {
      const msg = String(err?.message || err || "Unable to save local file.");
      setDatasetTypesStatus(`Local save failed: ${msg}`, true);
      setStatus(`Dataset types local save error: ${msg}`);
    }
  }

  async function loadDatasetTypesFromLocalFile(projectName) {
    const name = String(projectName || "").trim();
    if (!name) {
      setDatasetTypesStatus("Select a project first.", true);
      return;
    }
    if (blockedByRunningChange(name)) return;

    const hostApi = window.ADAHost || window.parent?.ADAHost || window.top?.ADAHost;
    if (!hostApi?.pickOpenFile) {
      setDatasetTypesStatus("Local load is available in the desktop app only.", true);
      return;
    }

    let startDir = "";
    try {
      const docsPath = String((await hostApi.getDocumentsPath?.()) || "").trim();
      if (docsPath) {
        startDir = joinWinPath(docsPath, "ArcRho", "templates");
      }
    } catch {
      startDir = "";
    }

    const pickedPath = String(
      (await hostApi.pickOpenFile({
        startDir,
        filters: [
          { name: "Dataset Types", extensions: ["json", "xlsx"] },
          { name: "JSON", extensions: ["json"] },
          { name: "Excel", extensions: ["xlsx"] },
        ],
      })) || "",
    ).trim();
    if (!pickedPath) {
      setDatasetTypesStatus("Local load canceled.");
      return;
    }

    setDatasetTypesStatus("Loading dataset types from local file...");
    try {
      const parseRes = await fetchImpl("/dataset_types/import_local_file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: pickedPath }),
      });
      if (!parseRes.ok) {
        let detail = "";
        try {
          const body = await parseRes.json();
          detail = String(body?.detail || "").trim();
        } catch {
          const text = await parseRes.text();
          detail = String(text || "").trim();
        }
        throw new Error(detail || `HTTP ${parseRes.status}`);
      }
      const parseOut = await parseRes.json();
      const parsed = normalizeLocalDatasetTypesPayload(parseOut?.data);
      const importedRows = buildPersistableRows(parsed.rows || []);

      const state = getProjectDatasetTypesState(name);
      const currentRows = buildPersistableRows(state.rows || []);

      // Skip merge/overwrite prompt when imported content is exactly the same as current UI rows.
      if (areDatasetTypeRowsExactlyEqual(currentRows, importedRows)) {
        const fileFormat = String(parseOut?.format || "").trim().toUpperCase();
        const formatText = fileFormat ? ` (${fileFormat})` : "";
        const sameMsg = `Loaded local dataset types from ${pickedPath}${formatText}: no changes detected.`;
        setDatasetTypesStatus(sameMsg);
        setStatus(sameMsg);
        return;
      }

      const mappedNames = await getFieldMappingDatasetTypeNames(name);
      const mappedKeySet = new Set(mappedNames.map((v) => normalizeProjectKey(v)).filter(Boolean));

      const selectedMode = await showDatasetTypesLoadModeDialog(
        "Choose how to load Dataset Types.\nMerge: add/update imported rows.\nOverwrite: remove existing rows not used by Field Mapping, then load imported rows.",
      );
      if (selectedMode !== "merge" && selectedMode !== "overwrite") {
        setDatasetTypesStatus("Local load canceled.");
        return;
      }
      const mode = selectedMode;

      let nextRows = [];
      const preservedMappedNames = [];
      if (mode === "overwrite") {
        nextRows = importedRows.map((row) => sanitizeDatasetTypeRow(row));
        const indexByName = new Map();
        for (let i = 0; i < nextRows.length; i += 1) {
          const rowNameKey = normalizeProjectKey(nextRows[i]?.[0]);
          if (!rowNameKey || indexByName.has(rowNameKey)) continue;
          indexByName.set(rowNameKey, i);
        }

        // Keep field-mapping-relevant dataset type rows if they are not present in imported content.
        for (const existing of currentRows) {
          const currentRow = sanitizeDatasetTypeRow(existing);
          const rowNameKey = normalizeProjectKey(currentRow[0]);
          if (!rowNameKey || !mappedKeySet.has(rowNameKey)) continue;
          if (indexByName.has(rowNameKey)) continue;
          indexByName.set(rowNameKey, nextRows.length);
          nextRows.push(currentRow);
          preservedMappedNames.push(currentRow[0]);
        }
      } else {
        nextRows = currentRows.map((row) => sanitizeDatasetTypeRow(row));
        const indexByName = new Map();
        for (let i = 0; i < nextRows.length; i += 1) {
          const rowNameKey = normalizeProjectKey(nextRows[i]?.[0]);
          if (!rowNameKey || indexByName.has(rowNameKey)) continue;
          indexByName.set(rowNameKey, i);
        }

        for (const incoming of importedRows) {
          const row = sanitizeDatasetTypeRow(incoming);
          const rowNameKey = normalizeProjectKey(row[0]);
          if (!rowNameKey) continue;

          if (mappedKeySet.has(rowNameKey)) {
            const existingIndex = indexByName.get(rowNameKey);
            if (existingIndex == null) {
              indexByName.set(rowNameKey, nextRows.length);
              nextRows.push(row);
            } else {
              preservedMappedNames.push(nextRows[existingIndex][0]);
            }
            continue;
          }

          const existingIndex = indexByName.get(rowNameKey);
          if (existingIndex == null) {
            indexByName.set(rowNameKey, nextRows.length);
            nextRows.push(row);
          } else {
            nextRows[existingIndex] = row;
          }
        }
      }

      state.rows = nextRows.length > 0 ? nextRows : [createEmptyDatasetTypesRow()];
      // An imported table replaces the grid's rows outright; nothing in it is
      // a rename of a saved row.
      state.renames = new Map();
      clearInvalidFormulaSet(name);
      renderDatasetTypesTable(name);

      const selectedProject = getSelectedProject();
      const currentFieldNames = getCurrentFieldNames();
      if (
        selectedProject &&
        normalizeProjectKey(selectedProject.name) === normalizeProjectKey(name) &&
        Array.isArray(currentFieldNames) &&
        currentFieldNames.length > 0
      ) {
        renderFieldMappingTable(currentFieldNames, name);
      }

      scheduleDatasetTypesAutoSave(name);

      const preservedUnique = Array.from(new Set(preservedMappedNames.map((v) => String(v || "").trim()).filter(Boolean)));
      const preservedMsg = preservedUnique.length
        ? ` Preserved mapped names: ${preservedUnique.slice(0, 6).join(", ")}${preservedUnique.length > 6 ? "..." : ""}.`
        : "";
      const modeText = mode;
      const fileFormat = String(parseOut?.format || "").trim().toUpperCase();
      const formatText = fileFormat ? ` (${fileFormat})` : "";
      const finalMsg = `Loaded local dataset types from ${pickedPath}${formatText} using ${modeText} mode.${preservedMsg}`;
      setDatasetTypesStatus(finalMsg);
      setStatus(finalMsg);
    } catch (err) {
      const msg = String(err?.message || err || "Unable to load local dataset types.");
      setDatasetTypesStatus(`Local load failed: ${msg}`, true);
      setStatus(`Dataset types local load error: ${msg}`);
    }
  }

  async function handleDatasetTypesRowContextAction(action) {
    if (!action || !datasetTypesContextProject) return;
    const projectName = datasetTypesContextProject;
    const rowIndex = datasetTypesContextRowIndex;
    const cellText = datasetTypesContextCellText;
    hideDatasetTypesRowContextMenu();
    if (action === "copy-cell") {
      const ok = await copyTextToClipboard(cellText);
      if (ok) {
        setDatasetTypesStatus("Cell value copied.");
      } else {
        setDatasetTypesStatus("Unable to copy cell value.", true);
      }
    } else if (action === "edit-row") {
      openDatasetTypeEditor(projectName, rowIndex);
    } else if (action === "add-row") {
      openDatasetTypeEditor(projectName, rowIndex, {
        mode: "add",
        insertAfterIndex: Number.isInteger(rowIndex) ? rowIndex : -1,
      });
    } else if (action === "delete-row") {
      deleteDatasetTypesRow(projectName, rowIndex);
    }
  }

  return {
    getDatasetTypeNamesForProject,
    isDatasetTypesChangeRunning,
    waitForRunningDatasetTypesChange,
    setDatasetTypesStatus,
    renderDatasetTypesEmpty,
    renderDatasetTypesLoading,
    ensureDatasetTypesLoaded,
    showDatasetTypesRowContextMenu,
    hideDatasetTypesRowContextMenu,
    addDatasetTypesRow,
    deleteDatasetTypesRow,
    renderDatasetTypesTable,
    loadDatasetTypes,
    saveDatasetTypes,
    saveDatasetTypesToLocalFile,
    loadDatasetTypesFromLocalFile,
    handleDatasetTypesRowContextAction,
    openDatasetTypeEditor,
    closeDatasetTypeEditor,
    applyDatasetTypeEditor,
    handleDatasetTypeEditorCalculatedToggle,
    onEditorHeaderMouseDown,
    onEditorMouseMove,
    onEditorMouseUp,
  };
}
