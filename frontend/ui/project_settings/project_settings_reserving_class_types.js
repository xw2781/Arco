import {
  clearTableSkeletonRows,
  renderTableSkeletonRows,
} from "./project_settings_skeleton.js?v=20260821pstree1";
import { createTableGroupRow } from "/ui/shared/components/table_group_row/table_group_row.js?v=20261013a";

export function createReservingClassTypesFeature(deps = {}) {
  const {
    reservingClassTypesBody = null,
    reservingClassTypesStatus = null,
    reservingClassTypesRowContextMenu = null,
    reservingClassTypeEditor = null,
    reservingClassTypeEditorHeader = null,
    reservingClassTypeEditorTitle = null,
    rctEditName = null,
    rctEditLevel = null,
    rctEditFormula = null,
    rctFormulaReview = null,
    initTableColumnResizing = () => {},
    getCollapsedGroups = () => new Set(),
    saveCollapsedGroups = () => {},
    showTableGroupContextMenu = () => {},
    normalizeProjectKey = (name) => String(name || "").trim().toLowerCase(),
    fetchImpl = fetch,
    setStatus = () => {},
    loadAuditLog = async () => {},
    hideContextMenu = () => {},
    hideFolderContextMenu = () => {},
    hideTreeContextMenu = () => {},
    hideDatasetTypesRowContextMenu = () => {},
    scheduleReservingClassTypesAutoSave = () => {},
    positionContextMenu = (menu, x, y) => { menu.style.left = `${x}px`; menu.style.top = `${y}px`; menu.classList.add("show"); },
  } = deps;

  const RESERVING_CLASS_TYPES_COLUMNS = ["Name", "Level", "Formula"];
  const RESERVING_CLASS_TYPES_SORTABLE_COLS = new Set(["Name", "Formula"]);
  const RESERVING_CLASS_TYPES_SORT_STORAGE_KEY = "arcrho_ps_rct_sort";
  const RESERVING_CLASS_TYPES_DEFAULT_SORT = { colLabel: "Formula", dir: "asc", explicit: false };
  const RCT_FORMULA_COMPONENT_DRAG_MIME = "application/x-arcrho-rct-formula-component";
  const RCT_FORMULA_OPERATOR_VALUES = ["+", "-"];
  const reservingClassTypesByProject = new Map();
  const loadedReservingClassTypesByProject = new Set();
  const reservingClassTypesSourceNamesByProject = new Map();

  let reservingClassTypesContextProject = "";
  let reservingClassTypesContextRowIndex = -1;
  let reservingClassTypesContextCellText = "";
  let rctEditorProject = "";
  let rctEditorRowIndex = -1;
  let rctEditorMode = "edit";
  let rctEditorInsertAfterIndex = -1;
  let rctEditorDragState = null;
  let rctEditorResizeState = null;
  let reservingClassTypesLoadSeq = 0;
  let reservingClassTypesSortState = loadReservingClassTypesSortState();
  let reservingClassTypesValidationTooltip = null;
  let reservingClassTypesValidationTooltipWired = false;
  let rctFormulaComponentsBox = null;
  let rctFormulaComponentsLabel = null;
  let rctFormulaComponentsToggle = null;
  let rctFormulaComponentsWired = false;
  let rctFormulaComponentsMenu = null;
  let rctFormulaComponentDragPayload = null;
  let rctFormulaReviewBox = rctFormulaReview;
  let rctFormulaMode = "review";
  let rctFormulaReviewClickTimer = null;
  let rctFormulaComponentsCollapsed = false;
  let rctFormulaPendingOperator = "+";

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

  function setReservingClassTypesStatus(msg, isError = false) {
    if (!reservingClassTypesStatus) return;
    reservingClassTypesStatus.textContent = msg || "";
    reservingClassTypesStatus.classList.toggle("error", !!isError);
  }

  function getProjectReservingClassTypesState(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!reservingClassTypesByProject.has(key)) {
      reservingClassTypesByProject.set(key, {
        columns: [...RESERVING_CLASS_TYPES_COLUMNS],
        rows: [],
      });
    }
    return reservingClassTypesByProject.get(key);
  }

  function getReservingClassTypesSourceSet(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!reservingClassTypesSourceNamesByProject.has(key)) {
      reservingClassTypesSourceNamesByProject.set(key, new Set());
    }
    return reservingClassTypesSourceNamesByProject.get(key);
  }

  function setReservingClassTypesSourceNames(projectName, names) {
    const set = getReservingClassTypesSourceSet(projectName);
    set.clear();
    for (const raw of names || []) {
      const v = String(raw || "").trim();
      if (!v) continue;
      set.add(canonReservingClassTypeName(v));
    }
  }

  function sanitizeReservingClassTypesSortState(raw) {
    const explicit = !!raw?.explicit;
    const colLabel = RESERVING_CLASS_TYPES_SORTABLE_COLS.has(String(raw?.colLabel || "").trim())
      ? String(raw.colLabel).trim()
      : "";
    const dir = String(raw?.dir || "").trim().toLowerCase();
    const dirNorm = dir === "asc" || dir === "desc" ? dir : "";
    if (colLabel && dirNorm) return { colLabel, dir: dirNorm, explicit: true };
    if (explicit) return { colLabel: "", dir: "", explicit: true };
    return { ...RESERVING_CLASS_TYPES_DEFAULT_SORT };
  }

  function loadReservingClassTypesSortState() {
    try {
      const raw = localStorage.getItem(RESERVING_CLASS_TYPES_SORT_STORAGE_KEY);
      if (!raw) return { ...RESERVING_CLASS_TYPES_DEFAULT_SORT };
      const parsed = JSON.parse(raw);
      return sanitizeReservingClassTypesSortState(parsed);
    } catch {
      return { ...RESERVING_CLASS_TYPES_DEFAULT_SORT };
    }
  }

  function persistReservingClassTypesSortState() {
    try {
      localStorage.setItem(RESERVING_CLASS_TYPES_SORT_STORAGE_KEY, JSON.stringify({
        colLabel: reservingClassTypesSortState.colLabel,
        dir: reservingClassTypesSortState.dir,
        explicit: true,
      }));
    } catch {
      // ignore storage errors
    }
  }

  function getReservingClassTypesSortState() {
    return reservingClassTypesSortState;
  }

  function toggleReservingClassTypesSort(colLabel) {
    const state = reservingClassTypesSortState;
    const target = String(colLabel || "").trim();
    if (!target) return;
    if (state.colLabel !== target) {
      state.colLabel = target;
      state.dir = "asc";
      persistReservingClassTypesSortState();
      return;
    }
    if (state.dir === "asc") {
      state.dir = "desc";
      persistReservingClassTypesSortState();
      return;
    }
    if (state.dir === "desc") {
      state.colLabel = "";
      state.dir = "";
      persistReservingClassTypesSortState();
      return;
    }
    state.dir = "asc";
    persistReservingClassTypesSortState();
  }

  function compareReservingClassTypeSortValues(a, b, dir) {
    const av = String(a ?? "").trim();
    const bv = String(b ?? "").trim();
    const an = Number(av);
    const bn = Number(bv);
    const aNum = av !== "" && Number.isFinite(an);
    const bNum = bv !== "" && Number.isFinite(bn);
    let cmp = 0;
    if (aNum && bNum) cmp = an - bn;
    else cmp = av.localeCompare(bv, undefined, { sensitivity: "base", numeric: true });
    return dir === "desc" ? -cmp : cmp;
  }

  function getReservingClassLevelKey(value) {
    return String(value ?? "").trim();
  }

  function getReservingClassTypeColIndexes(columns) {
    const safe = Array.isArray(columns) && columns.length ? columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    return {
      name: Math.max(0, safe.findIndex((c) => String(c || "").trim().toLowerCase() === "name")),
      level: safe.findIndex((c) => String(c || "").trim().toLowerCase() === "level"),
      formula: safe.findIndex((c) => String(c || "").trim().toLowerCase() === "formula"),
    };
  }

  function normalizeOperatorSpacing(value) {
    const text = String(value ?? "").trim();
    if (!text) return "";
    const segments = text.match(/"[^"]*"|[^"]+/g) || [];
    let normalizedText = "";
    segments.forEach((segment) => {
      if (segment.startsWith("\"") && segment.endsWith("\"")) {
        normalizedText += segment;
        return;
      }
      let normalized = segment
        .replace(/\s*([+\-*/])\s*/g, " $1 ")
        .replace(/\s+/g, " ");
      if (!normalizedText) normalized = normalized.replace(/^\s+/, "");
      normalizedText += normalized;
    });
    return normalizedText.trim();
  }

  function canonReservingClassTypeName(value) {
    return String(value ?? "").trim().replace(/\s+/g, " ").toLowerCase();
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

  function sanitizeReservingClassTypesRow(rowLike) {
    const out = createEmptyReservingClassTypesRow();
    out[0] = String(rowLike?.[0] ?? "").trim();
    out[1] = String(rowLike?.[1] ?? "").trim();
    out[2] = normalizeOperatorSpacing(rowLike?.[2] ?? "");
    return out;
  }

  function buildPersistableReservingClassTypesRows(rowList) {
    return (Array.isArray(rowList) ? rowList : [])
      .map((row) => sanitizeReservingClassTypesRow(row))
      .filter((row) => row[0] !== "" || row[1] !== "" || row[2] !== "");
  }

  function ensureReservingClassTypesValidationTooltip() {
    if (reservingClassTypesValidationTooltip) return reservingClassTypesValidationTooltip;
    const el = document.createElement("div");
    el.className = "rct-validation-tooltip";
    el.setAttribute("role", "tooltip");
    el.setAttribute("aria-hidden", "true");
    document.body.appendChild(el);
    reservingClassTypesValidationTooltip = el;
    return el;
  }

  function hideReservingClassTypesValidationTooltip() {
    const tooltip = reservingClassTypesValidationTooltip;
    if (!tooltip) return;
    tooltip.classList.remove("show");
    tooltip.setAttribute("aria-hidden", "true");
    tooltip.textContent = "";
    delete tooltip.dataset.fieldLabel;
  }

  function showReservingClassTypesValidationTooltip(anchor, messageText) {
    if (!anchor || typeof anchor.getBoundingClientRect !== "function") return;
    const tooltip = ensureReservingClassTypesValidationTooltip();
    const text = String(messageText || "").trim();
    if (!text) return;
    tooltip.textContent = text;
    tooltip.classList.add("show");
    tooltip.setAttribute("aria-hidden", "false");

    const rect = anchor.getBoundingClientRect();
    const margin = 8;
    const maxWidth = Math.min(360, Math.max(220, window.innerWidth - 24));
    tooltip.style.maxWidth = `${maxWidth}px`;
    tooltip.style.left = "0px";
    tooltip.style.top = "0px";

    const tipRect = tooltip.getBoundingClientRect();
    let left = rect.left;
    if (left + tipRect.width > window.innerWidth - 12) {
      left = window.innerWidth - 12 - tipRect.width;
    }
    left = Math.max(12, left);

    let top = rect.top - tipRect.height - margin;
    if (top < 12) {
      top = rect.bottom + margin;
    }
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  function ensureReservingClassTypesValidationTooltipWiring() {
    if (reservingClassTypesValidationTooltipWired) return;
    reservingClassTypesValidationTooltipWired = true;
    rctEditFormula?.addEventListener("input", () => {
      hideReservingClassTypesValidationTooltip();
      autoSizeReservingClassFormulaInput();
      renderReservingClassFormulaReview();
      renderReservingClassFormulaComponents();
    });
  }

  function autoSizeReservingClassFormulaInput() {
    autoSizeReservingClassFormulaInputForTarget(rctEditFormula);
  }

  function autoSizeReservingClassFormulaInputForTarget(target) {
    if (!target) return;
    target.style.height = "auto";
    const minHeight = 58;
    const scrollHeight = Number(target.scrollHeight || 0);
    const nextHeight = Math.max(minHeight, scrollHeight + 2);
    target.style.height = `${nextHeight}px`;
  }

  function sanitizeReservingClassFormulaSyntax(value) {
    const text = normalizeOperatorSpacing(value);
    if (!text) return "";

    const tokens = [];
    let current = "";
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      if (ch === "\"") {
        if (current.trim()) tokens.push({ type: "operand", value: current.trim() });
        current = "\"";
        i += 1;
        while (i < text.length) {
          current += text[i];
          if (text[i] === "\"") break;
          i += 1;
        }
        tokens.push({ type: "operand", value: current.trim() });
        current = "";
        continue;
      }
      if (/[+\-*/]/.test(ch)) {
        if (current.trim()) tokens.push({ type: "operand", value: current.trim().replace(/\s+/g, " ") });
        tokens.push({ type: "operator", value: ch });
        current = "";
        continue;
      }
      current += ch;
    }
    if (current.trim()) tokens.push({ type: "operand", value: current.trim().replace(/\s+/g, " ") });

    const out = [];
    let expectOperand = true;
    for (const token of tokens) {
      if (token.type === "operand") {
        if (!expectOperand && out.length) out.push("+");
        out.push(token.value);
        expectOperand = false;
        continue;
      }
      if (expectOperand) continue;
      out.push(token.value);
      expectOperand = true;
    }
    while (out.length && /^[+\-*/]$/.test(out[out.length - 1])) out.pop();
    return normalizeOperatorSpacing(out.join(" "));
  }

  function normalizeReservingClassFormulaInputSyntax(target) {
    if (!target) return "";
    const cleaned = sanitizeReservingClassFormulaSyntax(target.value ?? "");
    if (!target.disabled && String(target.value ?? "") !== cleaned) {
      target.value = cleaned;
      if (target === rctEditFormula) autoSizeReservingClassFormulaInputForTarget(target);
    }
    return cleaned;
  }

  function formatReservingClassFormulaComponent(value) {
    const text = String(value ?? "").trim();
    if (!text) return "";
    return `"${text}"`;
  }

  function createReservingClassFormulaSvgIcon(paths) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    for (const d of paths) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      svg.appendChild(path);
    }
    return svg;
  }

  function createReservingClassFormulaOperatorIcon(value) {
    const op = String(value || "").trim();
    if (op === "+") return createReservingClassFormulaSvgIcon(["M12 5v14", "M5 12h14"]);
    if (op === "-") return createReservingClassFormulaSvgIcon(["M5 12h14"]);
    if (op === "*") return createReservingClassFormulaSvgIcon(["M6 6l12 12", "M18 6L6 18"]);
    if (op === "/") return createReservingClassFormulaSvgIcon(["M16 5L8 19"]);
    return document.createTextNode(op);
  }

  function normalizeReservingClassFormulaPendingOperator(value) {
    const op = String(value ?? "").trim();
    return RCT_FORMULA_OPERATOR_VALUES.includes(op) ? op : "+";
  }

  function getReservingClassFormulaTargetKind(target) {
    return "formula";
  }

  function getReservingClassFormulaTargetByKind(targetKind) {
    return rctEditFormula;
  }

  function getReservingClassFormulaReviewBoxByKind(targetKind) {
    return rctFormulaReviewBox;
  }

  function getReservingClassFormulaModeByKind(targetKind) {
    return rctFormulaMode;
  }

  function setReservingClassFormulaModeByKind(targetKind, mode, options = {}) {
    const target = rctEditFormula;
    const reviewBox = rctFormulaReviewBox;
    if (!target || !reviewBox) return;
    const nextMode = String(mode || "") === "edit" && !target.disabled ? "edit" : "review";
    rctFormulaMode = nextMode;
    const control = target.closest?.(".rct-formula-control");
    control?.classList.toggle("editing", nextMode === "edit");
    reviewBox.classList.toggle("editing", nextMode === "edit");
    target.setAttribute("aria-hidden", nextMode === "edit" ? "false" : "true");
    reviewBox.setAttribute("aria-hidden", nextMode === "edit" ? "true" : "false");
    renderReservingClassFormulaReviewForTarget("formula");
    if (nextMode === "edit") {
      autoSizeReservingClassFormulaInputForTarget(target);
      if (options.focus) target.focus();
    } else if (options.blur !== false) {
      target.blur();
    }
  }

  function getReservingClassFormulaPendingOperator(targetKind) {
    return rctFormulaPendingOperator;
  }

  function setReservingClassFormulaPendingOperatorForTarget(targetKind, value) {
    const op = normalizeReservingClassFormulaPendingOperator(value);
    rctFormulaPendingOperator = op;
    renderReservingClassFormulaComponents();
  }

  function createReservingClassFormulaCalculatedIcon() {
    const icon = document.createElement("span");
    icon.className = "rct-formula-calculated-icon";
    icon.title = "Calculated class type";
    icon.appendChild(createReservingClassFormulaSvgIcon(["M4 7h8v6H4zM12 11h8v6h-8zM12 3h8v6h-8z"]));
    return icon;
  }

  function formatReservingClassFormulaReviewComponent(value) {
    const text = String(value ?? "").trim();
    if (text.length >= 2 && text.startsWith("\"") && text.endsWith("\"")) {
      return text.slice(1, -1);
    }
    return text;
  }

  function updateReservingClassFormulaComponentsCollapsedState() {
    const updateToggle = (box, toggle, collapsed) => {
      if (!box) return;
      box.classList.toggle("collapsed", collapsed);
      if (!toggle) return;
      const label = collapsed ? "Show all components" : "Hide all components";
      toggle.classList.toggle("collapsed", collapsed);
      toggle.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M9 18l6-6-6-6"></path>
        </svg>
        <span>${label}</span>
      `;
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.setAttribute("aria-label", label);
      toggle.title = label;
    };
    updateToggle(rctFormulaComponentsBox, rctFormulaComponentsToggle, rctFormulaComponentsCollapsed);
  }

  function tokenizeReservingClassFormulaForReview(value) {
    const text = normalizeOperatorSpacing(value);
    if (!text) return [];
    const tokens = [];
    let current = "";

    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i];
      if (ch === "\"") {
        if (current.trim()) tokens.push({ type: "component", value: current.trim() });
        current = "\"";
        i += 1;
        while (i < text.length) {
          current += text[i];
          if (text[i] === "\"") break;
          i += 1;
        }
        if (current.trim()) tokens.push({ type: "component", value: current.trim() });
        current = "";
        continue;
      }
      if (/[+\-*/]/.test(ch)) {
        if (current.trim()) tokens.push({ type: "component", value: current.trim().replace(/\s+/g, " ") });
        tokens.push({ type: "operator", value: ch });
        current = "";
        continue;
      }
      current += ch;
    }
    if (current.trim()) tokens.push({ type: "component", value: current.trim().replace(/\s+/g, " ") });
    return tokens;
  }

  function getReservingClassFormulaReviewMetadata(projectName) {
    const state = getProjectReservingClassTypesState(projectName);
    const columns = Array.isArray(state.columns) && state.columns.length ? state.columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    const idx = getReservingClassTypeColIndexes(columns);
    const nameIdx = idx.name >= 0 ? idx.name : 0;
    const formulaIdx = idx.formula >= 0 ? idx.formula : 2;
    const knownKeys = new Set();
    const calculatedKeys = new Set();
    const sourceKeys = getReservingClassTypesSourceSet(projectName);

    for (const row of Array.isArray(state.rows) ? state.rows : []) {
      if (!Array.isArray(row)) continue;
      const name = String(row?.[nameIdx] ?? "").trim();
      const key = canonReservingClassTypeName(name);
      if (!key) continue;
      knownKeys.add(key);
      if (String(row?.[formulaIdx] ?? "").trim()) calculatedKeys.add(key);
    }

    return { knownKeys, calculatedKeys, sourceKeys };
  }

  function renderReservingClassFormulaReviewForTarget(targetKind) {
    const kind = "formula";
    const target = rctEditFormula;
    const reviewBox = rctFormulaReviewBox;
    if (!target || !reviewBox) return;
    reviewBox.innerHTML = "";
    reviewBox.classList.toggle("disabled", !!target.disabled);
    const formulaText = getReservingClassFormulaModeByKind(kind) === "edit"
      ? normalizeOperatorSpacing(target.value ?? "")
      : normalizeReservingClassFormulaInputSyntax(target);
    const tokens = tokenizeReservingClassFormulaForReview(formulaText);
    const meta = getReservingClassFormulaReviewMetadata(rctEditorProject);
    for (const token of tokens) {
      const el = document.createElement("span");
      if (token.type === "operator") {
        const opClass = token.value === "+" ? " plus" : (token.value === "-" ? " minus" : "");
        el.className = `rct-formula-token operator${opClass}`;
        el.appendChild(createReservingClassFormulaOperatorIcon(token.value));
        el.title = token.value === "*" ? "x" : token.value;
      } else {
        const displayValue = formatReservingClassFormulaReviewComponent(token.value);
        const key = canonReservingClassTypeName(displayValue);
        const isKnown = !!key && meta.knownKeys.has(key);
        const isCalculated = isKnown && meta.calculatedKeys.has(key);
        const isSourceDerived = isKnown && meta.sourceKeys.has(key);
        el.className = "rct-formula-token component";
        el.classList.toggle("unknown", !isKnown);
        el.classList.toggle("calculated", isCalculated);
        el.classList.toggle("source-derived", isSourceDerived && !isCalculated);
        el.draggable = !target.disabled;
        if (isCalculated) el.appendChild(createReservingClassFormulaCalculatedIcon());
        const label = document.createElement("span");
        label.className = "rct-formula-token-text";
        label.textContent = displayValue;
        el.appendChild(label);
        el.title = isKnown
          ? `${displayValue} - click to remove, double-click to edit raw text`
          : `${displayValue} - not found in reserving class types`;
        el.addEventListener("click", (evt) => {
          evt.preventDefault();
          evt.stopPropagation();
          if (target.disabled || getReservingClassFormulaModeByKind(kind) !== "review") return;
          scheduleReservingClassFormulaReviewTokenRemoval(el, kind, target, displayValue);
        });
        el.addEventListener("dblclick", (evt) => {
          evt.preventDefault();
          evt.stopPropagation();
          clearReservingClassFormulaReviewClickTimer();
          if (target.disabled) return;
          setReservingClassFormulaModeByKind(kind, "edit", { focus: true });
        });
        el.addEventListener("dragstart", (evt) => {
          if (getReservingClassFormulaModeByKind(kind) === "edit") setReservingClassFormulaModeByKind(kind, "review");
          const payload = { type: "rct_formula_review_component", target: kind, value: displayValue };
          setReservingClassFormulaComponentDragPayload(evt, payload);
        });
      }
      reviewBox.appendChild(el);
    }
  }

  function renderReservingClassFormulaReview() {
    renderReservingClassFormulaReviewForTarget("formula");
  }

  function clearReservingClassFormulaReviewClickTimer() {
    if (!rctFormulaReviewClickTimer) return;
    clearTimeout(rctFormulaReviewClickTimer);
    rctFormulaReviewClickTimer = null;
  }

  function scheduleReservingClassFormulaReviewTokenRemoval(tokenEl, targetKind, target, displayValue) {
    clearReservingClassFormulaReviewClickTimer();
    const win = tokenEl?.ownerDocument?.defaultView || window;
    rctFormulaReviewClickTimer = win.setTimeout(() => {
      rctFormulaReviewClickTimer = null;
      if (!target || target.disabled || getReservingClassFormulaModeByKind(targetKind) !== "review") return;
      animateReservingClassFormulaReviewTokenRemoval(tokenEl, targetKind);
      removeReservingClassFormulaComponentFromTarget(target, displayValue);
    }, 220);
  }

  function animateReservingClassFormulaReviewTokenRemoval(tokenEl, targetKind) {
    const doc = tokenEl?.ownerDocument || document;
    const win = doc.defaultView || window;
    const sourceRect = tokenEl?.getBoundingClientRect?.();
    if (!sourceRect || !sourceRect.width || !sourceRect.height || !doc.body) return;

    const destinationEl = rctFormulaComponentsBox && !rctFormulaComponentsBox.classList.contains("collapsed")
      ? rctFormulaComponentsBox
      : rctFormulaComponentsToggle;
    const destinationRect = destinationEl?.getBoundingClientRect?.();
    const sourceCenterX = sourceRect.left + sourceRect.width / 2;
    const sourceCenterY = sourceRect.top + sourceRect.height / 2;
    const destinationCenterX = destinationRect ? destinationRect.left + destinationRect.width / 2 : sourceCenterX;
    const destinationCenterY = destinationRect ? destinationRect.top + destinationRect.height / 2 : Math.min(win.innerHeight - 18, sourceCenterY + 56);
    const dx = destinationCenterX - sourceCenterX;
    const dy = destinationCenterY - sourceCenterY;

    const ghost = tokenEl.cloneNode(true);
    ghost.classList.add("rct-formula-token-removal-ghost");
    ghost.style.left = `${sourceRect.left}px`;
    ghost.style.top = `${sourceRect.top}px`;
    ghost.style.width = `${sourceRect.width}px`;
    ghost.style.height = `${sourceRect.height}px`;
    doc.body.appendChild(ghost);

    const cleanup = () => {
      if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
    };
    if (typeof ghost.animate === "function") {
      const animation = ghost.animate([
        { transform: "translate(0, 0) scale(1)", opacity: 0.96 },
        { transform: `translate(${dx * 0.55}px, ${dy * 0.25 - 14}px) scale(0.92)`, opacity: 0.82, offset: 0.55 },
        { transform: `translate(${dx}px, ${dy}px) scale(0.68)`, opacity: 0 },
      ], {
        duration: 360,
        easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
        fill: "forwards",
      });
      animation.addEventListener("finish", cleanup, { once: true });
      animation.addEventListener("cancel", cleanup, { once: true });
    } else {
      ghost.style.opacity = "0";
      ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.68)`;
      setTimeout(cleanup, 360);
    }
  }

  function animateReservingClassFormulaComponentSelection(chipEl, targetKind) {
    const doc = chipEl?.ownerDocument || document;
    const win = doc.defaultView || window;
    const sourceRect = chipEl?.getBoundingClientRect?.();
    if (!sourceRect || !sourceRect.width || !sourceRect.height || !doc.body) return;

    const destinationEl = rctFormulaReviewBox || rctEditFormula;
    const destinationRect = destinationEl?.getBoundingClientRect?.();
    const sourceCenterX = sourceRect.left + sourceRect.width / 2;
    const sourceCenterY = sourceRect.top + sourceRect.height / 2;
    const destinationCenterX = destinationRect ? destinationRect.left + destinationRect.width / 2 : sourceCenterX;
    const destinationCenterY = destinationRect ? destinationRect.top + Math.min(destinationRect.height - 12, 18) : Math.max(18, sourceCenterY - 56);
    const dx = destinationCenterX - sourceCenterX;
    const dy = destinationCenterY - sourceCenterY;

    const ghost = chipEl.cloneNode(true);
    ghost.classList.add("rct-formula-token-selection-ghost");
    ghost.style.left = `${sourceRect.left}px`;
    ghost.style.top = `${sourceRect.top}px`;
    ghost.style.width = `${sourceRect.width}px`;
    ghost.style.height = `${sourceRect.height}px`;
    doc.body.appendChild(ghost);

    const cleanup = () => {
      if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
    };
    if (typeof ghost.animate === "function") {
      const animation = ghost.animate([
        { transform: "translate(0, 0) scale(1)", opacity: 0.96 },
        { transform: `translate(${dx * 0.45}px, ${dy * 0.25 - 12}px) scale(0.96)`, opacity: 0.86, offset: 0.5 },
        { transform: `translate(${dx}px, ${dy}px) scale(0.72)`, opacity: 0 },
      ], {
        duration: 360,
        easing: "cubic-bezier(0.2, 0.8, 0.2, 1)",
        fill: "forwards",
      });
      animation.addEventListener("finish", cleanup, { once: true });
      animation.addEventListener("cancel", cleanup, { once: true });
    } else {
      ghost.style.opacity = "0";
      ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.72)`;
      setTimeout(cleanup, 360);
    }
  }

  function setReservingClassFormulaMode(mode, options = {}) {
    setReservingClassFormulaModeByKind("formula", mode, options);
  }

  function getReservingClassFormulaComponentKeys(formula, knownNames = []) {
    const text = String(formula ?? "").trim();
    const keys = new Set();
    if (!text) return keys;

    const used = [];
    for (const match of Array.from(text.matchAll(/"([^"]*)"/g))) {
      const value = String(match?.[1] ?? "").trim();
      const start = Number(match?.index ?? -1);
      const end = start >= 0 ? start + String(match?.[0] ?? "").length : -1;
      if (start >= 0 && end >= start) used.push({ start, end });
      const key = canonReservingClassTypeName(value);
      if (key) keys.add(key);
    }

    const uniqueNames = uniqueReservingClassTypeNames(knownNames).sort((a, b) => b.length - a.length);
    for (const name of uniqueNames) {
      const key = canonReservingClassTypeName(name);
      if (!key || keys.has(key)) continue;
      const pattern = new RegExp(`(?<![A-Za-z0-9_])${escapeRegExp(name)}(?![A-Za-z0-9_])`, "gi");
      let match;
      while ((match = pattern.exec(text)) !== null) {
        const start = match.index;
        const end = start + match[0].length;
        const overlapsQuotedToken = used.some((entry) => start < entry.end && end > entry.start);
        if (overlapsQuotedToken) continue;
        keys.add(key);
        break;
      }
    }

    return keys;
  }

  function closeReservingClassFormulaComponentsMenu() {
    if (!rctFormulaComponentsMenu) return;
    const { menu, onMouseDown, onKeyDown, onContextMenu } = rctFormulaComponentsMenu;
    document.removeEventListener("mousedown", onMouseDown, true);
    document.removeEventListener("keydown", onKeyDown, true);
    document.removeEventListener("contextmenu", onContextMenu, true);
    if (menu?.parentNode) menu.parentNode.removeChild(menu);
    rctFormulaComponentsMenu = null;
  }

  function getReservingClassFormulaComponentValues(projectName) {
    const selectedLevel = String(rctEditLevel?.value ?? "").trim();
    const calculatedKeys = new Set();
    if (!projectName || !selectedLevel) return { level: selectedLevel, values: [], calculatedKeys };

    const state = getProjectReservingClassTypesState(projectName);
    const columns = Array.isArray(state.columns) && state.columns.length ? state.columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    const idx = getReservingClassTypeColIndexes(columns);
    const nameIdx = idx.name >= 0 ? idx.name : 0;
    const levelIdx = idx.level >= 0 ? idx.level : 1;
    const formulaIdx = idx.formula >= 0 ? idx.formula : 2;
    const seen = new Set();
    const values = [];

    for (const row of Array.isArray(state.rows) ? state.rows : []) {
      if (!Array.isArray(row)) continue;
      const level = String(row?.[levelIdx] ?? "").trim();
      if (level !== selectedLevel) continue;
      const name = String(row?.[nameIdx] ?? "").trim();
      const key = canonReservingClassTypeName(name);
      if (!name || !key) continue;
      if (String(row?.[formulaIdx] ?? "").trim()) calculatedKeys.add(key);
      if (seen.has(key)) continue;
      seen.add(key);
      values.push(name);
    }

    values.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));
    return { level: selectedLevel, values, calculatedKeys };
  }

  function appendReservingClassFormulaComponentsToTarget(target, rawValues, options = {}) {
    if (!target || target.disabled) return false;
    const values = Array.isArray(rawValues) ? rawValues : [rawValues];
    if (options.replaceFormula) {
      target.value = "";
    }
    const existing = sanitizeReservingClassFormulaSyntax(target.value ?? "");
    const tokens = [];
    const seenInThisAppend = new Set();
    let existingKeys = null;

    if (options.skipExisting) {
      const knownValues = getReservingClassFormulaComponentValues(rctEditorProject).values;
      existingKeys = getReservingClassFormulaComponentKeys(existing, knownValues);
    }

    for (const raw of values) {
      const value = String(raw ?? "").trim();
      const key = canonReservingClassTypeName(value);
      if (!value || !key || seenInThisAppend.has(key)) continue;
      if (existingKeys?.has(key)) continue;
      const token = formatReservingClassFormulaComponent(value);
      if (!token) continue;
      seenInThisAppend.add(key);
      tokens.push(token);
    }

    if (!tokens.length) return false;
    const targetKind = getReservingClassFormulaTargetKind(target);
    const usePendingOperator =
      target === rctEditFormula
      && !options.replaceFormula
      && options.usePendingOperator === true;
    const leadingOperator = usePendingOperator
      ? normalizeReservingClassFormulaPendingOperator(getReservingClassFormulaPendingOperator(targetKind))
      : normalizeReservingClassFormulaPendingOperator(options.operator);
    const appended = tokens.length <= 1
      ? tokens.join(" + ")
      : `${tokens[0]} + ${tokens.slice(1).join(" + ")}`;
    const next = existing ? `${existing} ${leadingOperator} ${appended}` : appended;
    target.value = sanitizeReservingClassFormulaSyntax(next);
    hideReservingClassTypesValidationTooltip();
    try {
      target.dispatchEvent(new Event("input", { bubbles: true }));
    } catch {
      // ignore synthetic event failures
    }
    autoSizeReservingClassFormulaInputForTarget(target);
    renderReservingClassFormulaComponents();
    setReservingClassFormulaModeByKind(targetKind, "review");
    getReservingClassFormulaReviewBoxByKind(targetKind)?.focus();
    return true;
  }

  function appendReservingClassFormulaComponents(rawValues, options = {}) {
    const nextOptions = { ...options };
    if (!Object.prototype.hasOwnProperty.call(nextOptions, "usePendingOperator")) {
      nextOptions.usePendingOperator = !Array.isArray(rawValues) && !nextOptions.replaceFormula;
    }
    return appendReservingClassFormulaComponentsToTarget(rctEditFormula, rawValues, nextOptions);
  }

  function appendReservingClassFormulaOperator(rawOperator) {
    if (!rctEditFormula || rctEditFormula.disabled) return false;
    const operator = String(rawOperator ?? "").trim();
    if (!RCT_FORMULA_OPERATOR_VALUES.includes(operator)) return false;
    const existing = sanitizeReservingClassFormulaSyntax(rctEditFormula.value ?? "");
    const next = existing ? `${existing} ${operator}` : operator;
    rctEditFormula.value = normalizeOperatorSpacing(next);
    hideReservingClassTypesValidationTooltip();
    try {
      rctEditFormula.dispatchEvent(new Event("input", { bubbles: true }));
    } catch {
      // ignore synthetic event failures
    }
    autoSizeReservingClassFormulaInput();
    renderReservingClassFormulaComponents();
    setReservingClassFormulaMode("review");
    rctFormulaReviewBox?.focus();
    return true;
  }

  function removeReservingClassFormulaComponentFromTarget(target, rawValue) {
    if (!target || target.disabled) return false;
    const targetKind = getReservingClassFormulaTargetKind(target);
    const key = canonReservingClassTypeName(rawValue);
    if (!key) return false;

    const tokens = tokenizeReservingClassFormulaForReview(target.value ?? "");
    let removed = false;
    const kept = [];
    for (const token of tokens) {
      if (token.type === "component") {
        const value = formatReservingClassFormulaReviewComponent(token.value);
        if (canonReservingClassTypeName(value) === key) {
          removed = true;
          continue;
        }
      }
      kept.push(token.value);
    }
    if (!removed) return false;

    target.value = sanitizeReservingClassFormulaSyntax(kept.join(" "));
    hideReservingClassTypesValidationTooltip();
    try {
      target.dispatchEvent(new Event("input", { bubbles: true }));
    } catch {
      // ignore synthetic event failures
    }
    autoSizeReservingClassFormulaInputForTarget(target);
    renderReservingClassFormulaComponents();
    setReservingClassFormulaModeByKind(targetKind, "review");
    getReservingClassFormulaReviewBoxByKind(targetKind)?.focus();
    return true;
  }

  function parseReservingClassFormulaComponentDragPayload(evt) {
    if (rctFormulaComponentDragPayload) return rctFormulaComponentDragPayload;

    let raw = "";
    try {
      raw = String(evt?.dataTransfer?.getData(RCT_FORMULA_COMPONENT_DRAG_MIME) || "").trim();
    } catch {
      raw = "";
    }
    if (!raw) {
      try {
        raw = String(evt?.dataTransfer?.getData("application/json") || "").trim();
      } catch {
        raw = "";
      }
    }
    if (!raw) return null;

    try {
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") return parsed;
    } catch {
      // text fallback below
    }
    return { value: raw };
  }

  function isReservingClassFormulaComponentDrag(evt) {
    if (rctFormulaComponentDragPayload) return true;

    const types = Array.from(evt?.dataTransfer?.types || []).map((type) => String(type || "").toLowerCase());
    if (types.includes(RCT_FORMULA_COMPONENT_DRAG_MIME)) return true;
    if (!types.includes("application/json")) return false;
    try {
      const raw = String(evt?.dataTransfer?.getData("application/json") || "").trim();
      if (!raw) return false;
      const parsed = JSON.parse(raw);
      return ["rct_formula_component", "rct_formula_operator", "rct_formula_review_component"].includes(String(parsed?.type || ""));
    } catch {
      return false;
    }
  }

  function isReservingClassFormulaDropTarget(evt) {
    if (!rctEditFormula || rctEditFormula.disabled) return false;
    const payloadTarget = String(rctFormulaComponentDragPayload?.target || "formula");
    if (evt?.target === rctEditFormula || evt?.target === rctFormulaReviewBox) return payloadTarget === "formula";
    const path = typeof evt?.composedPath === "function" ? evt.composedPath() : [];
    if (!Array.isArray(path)) return false;
    return payloadTarget === "formula" && (path.includes(rctEditFormula) || path.includes(rctFormulaReviewBox));
  }

  function isReservingClassFormulaComponentReturnDropTarget(evt) {
    if (!rctFormulaComponentsBox || !rctEditFormula || rctEditFormula.disabled) return false;
    const payloadType = String(rctFormulaComponentDragPayload?.type || "");
    if (payloadType !== "rct_formula_review_component") return false;
    const payloadTarget = String(rctFormulaComponentDragPayload?.target || "formula");
    if (payloadTarget !== "formula") return false;
    const returnBox = rctFormulaComponentsBox;
    const target = rctEditFormula;
    if (!returnBox || !target || target.disabled) return false;
    if (evt?.target === returnBox) return true;
    const path = typeof evt?.composedPath === "function" ? evt.composedPath() : [];
    return Array.isArray(path) && path.includes(returnBox);
  }

  function removeDroppedReviewComponentOutsideFormula(evt) {
    const payload = parseReservingClassFormulaComponentDragPayload(evt);
    if (String(payload?.type || "") !== "rct_formula_review_component") return false;
    evt.preventDefault();
    evt.stopPropagation();
    if (evt.dataTransfer) evt.dataTransfer.dropEffect = "move";
    if (String(evt?.type || "") === "drop") {
      const target = getReservingClassFormulaTargetByKind(String(payload?.target || "formula"));
      removeReservingClassFormulaComponentFromTarget(target, payload?.value ?? payload?.name);
      rctFormulaComponentDragPayload = null;
    }
    return true;
  }

  function blockReservingClassFormulaComponentDropOutsideFormula(evt) {
    if (!isReservingClassFormulaComponentDrag(evt)) return;
    if (isReservingClassFormulaDropTarget(evt)) return;
    if (isReservingClassFormulaComponentReturnDropTarget(evt)) return;
    if (removeDroppedReviewComponentOutsideFormula(evt)) {
      rctEditFormula?.classList.remove("rct-formula-drop-target");
      rctFormulaReviewBox?.classList.remove("rct-formula-drop-target");
      rctFormulaComponentsBox?.classList.remove("rct-formula-return-drop-target");
      return;
    }
    evt.preventDefault();
    evt.stopPropagation();
    if (evt.dataTransfer) evt.dataTransfer.dropEffect = "none";
    if (String(evt?.type || "") === "drop") rctFormulaComponentDragPayload = null;
    rctEditFormula?.classList.remove("rct-formula-drop-target");
    rctFormulaReviewBox?.classList.remove("rct-formula-drop-target");
    rctFormulaComponentsBox?.classList.remove("rct-formula-return-drop-target");
  }

  function wireReservingClassFormulaComponentGlobalDropGuard() {
    const doc = rctEditFormula?.ownerDocument || document;
    doc.addEventListener("dragover", blockReservingClassFormulaComponentDropOutsideFormula, true);
    doc.addEventListener("drop", blockReservingClassFormulaComponentDropOutsideFormula, true);
    doc.addEventListener("dragend", () => {
      rctFormulaComponentDragPayload = null;
      rctEditFormula?.classList.remove("rct-formula-drop-target");
      rctFormulaReviewBox?.classList.remove("rct-formula-drop-target");
      rctFormulaComponentsBox?.classList.remove("rct-formula-return-drop-target");
    });
  }

  function setReservingClassFormulaComponentDragPayload(evt, payload) {
    rctFormulaComponentDragPayload = payload;
    if (!evt?.dataTransfer) return;
    const serialized = JSON.stringify(payload);
    evt.dataTransfer.effectAllowed = String(payload?.type || "") === "rct_formula_review_component" ? "move" : "copy";
    try {
      evt.dataTransfer.setData(RCT_FORMULA_COMPONENT_DRAG_MIME, serialized);
    } catch {}
    try {
      evt.dataTransfer.setData("application/json", serialized);
    } catch {}
    try {
      evt.dataTransfer.setData("text/uri-list", "");
    } catch {
      // Some runtimes require a text type but it must not contain the payload.
    }
  }

  function handleReservingClassFormulaComponentDrop(evt, dropTarget) {
    evt.preventDefault();
    evt.stopPropagation();
    const targetKind = getReservingClassFormulaTargetKind(dropTarget);
    const target = getReservingClassFormulaTargetByKind(targetKind);
    if (!target || target.disabled || !rctEditFormula || rctEditFormula.disabled) return false;
    dropTarget?.classList?.remove("rct-formula-drop-target");
    const payload = parseReservingClassFormulaComponentDragPayload(evt);
    rctFormulaComponentDragPayload = null;
    const payloadTarget = String(payload?.target || "formula");
    if (payloadTarget !== targetKind) return false;
    if (String(payload?.type || "") === "rct_formula_operator") {
      return appendReservingClassFormulaOperator(payload?.value);
    }
    if (String(payload?.type || "") === "rct_formula_review_component") return false;
    const selected = getReservingClassFormulaComponentValues(rctEditorProject);
    const payloadLevel = String(payload?.level ?? payload?.level_number ?? "").trim();
    if (payloadLevel && selected.level && payloadLevel !== selected.level) return false;
    const value = String(payload?.value ?? payload?.name ?? "").trim();
    const validKeys = new Set(selected.values.map((item) => canonReservingClassTypeName(item)).filter(Boolean));
    if (!validKeys.has(canonReservingClassTypeName(value))) return false;
    return appendReservingClassFormulaComponentsToTarget(target, value, { usePendingOperator: true });
  }

  function wireReservingClassFormulaComponentDropTarget(dropTarget) {
    if (!dropTarget) return;
    dropTarget.addEventListener("dragover", (evt) => {
      const target = getReservingClassFormulaTargetByKind(getReservingClassFormulaTargetKind(dropTarget));
      if (rctEditFormula?.disabled || target?.disabled) return;
      if (!isReservingClassFormulaDropTarget(evt)) return;
      evt.preventDefault();
      if (evt.dataTransfer) evt.dataTransfer.dropEffect = "copy";
      dropTarget.classList.add("rct-formula-drop-target");
    });
    dropTarget.addEventListener("dragleave", () => {
      dropTarget.classList.remove("rct-formula-drop-target");
    });
    dropTarget.addEventListener("drop", (evt) => {
      handleReservingClassFormulaComponentDrop(evt, dropTarget);
    });
  }

  function handleReservingClassFormulaComponentReturnDrop(evt) {
    evt.preventDefault();
    evt.stopPropagation();
    rctFormulaComponentsBox?.classList.remove("rct-formula-return-drop-target");
    const payload = parseReservingClassFormulaComponentDragPayload(evt);
    rctFormulaComponentDragPayload = null;
    if (String(payload?.type || "") !== "rct_formula_review_component") return false;
    const target = getReservingClassFormulaTargetByKind(String(payload?.target || "formula"));
    return removeReservingClassFormulaComponentFromTarget(target, payload?.value ?? payload?.name);
  }

  function wireReservingClassFormulaComponentReturnDropTarget(target) {
    if (!target) return;
    target.addEventListener("dragover", (evt) => {
      if (!isReservingClassFormulaComponentReturnDropTarget(evt)) return;
      evt.preventDefault();
      evt.stopPropagation();
      if (evt.dataTransfer) evt.dataTransfer.dropEffect = "move";
      target.classList.add("rct-formula-return-drop-target");
    });
    target.addEventListener("dragleave", () => {
      target.classList.remove("rct-formula-return-drop-target");
    });
    target.addEventListener("drop", (evt) => {
      if (!isReservingClassFormulaComponentReturnDropTarget(evt)) return;
      handleReservingClassFormulaComponentReturnDrop(evt);
    });
  }

  function ensureReservingClassFormulaComponentsSection() {
    if (!rctEditFormula) return null;
    const doc = rctEditFormula.ownerDocument || document;
    rctFormulaReviewBox = doc.getElementById("rctFormulaReview") || rctFormulaReviewBox;
    rctFormulaComponentsBox = doc.getElementById("rctFormulaComponentsBox") || rctFormulaComponentsBox;
    rctFormulaComponentsLabel = doc.getElementById("rctFormulaComponentsLabel") || rctFormulaComponentsLabel;
    rctFormulaComponentsToggle = doc.getElementById("rctFormulaComponentsToggle") || rctFormulaComponentsToggle;

    if (!rctFormulaReviewBox) {
      const control = rctEditFormula.closest?.(".rct-formula-control") || rctEditFormula.parentElement;
      if (control) {
        rctFormulaReviewBox = doc.createElement("div");
        rctFormulaReviewBox.id = "rctFormulaReview";
        rctFormulaReviewBox.className = "rct-formula-review";
        rctFormulaReviewBox.setAttribute("role", "textbox");
        rctFormulaReviewBox.setAttribute("tabindex", "0");
        rctFormulaReviewBox.setAttribute("aria-label", "Formula");
        control.appendChild(rctFormulaReviewBox);
      }
    }
    if (!rctFormulaComponentsBox) {
      const body = rctEditFormula.closest?.(".rct-row-editor-body");
      const frame = rctEditFormula.closest?.(".rct-formula-frame") || rctEditFormula.closest?.(".rct-formula-control")?.parentElement;
      if (!body) return null;
      rctFormulaComponentsLabel = doc.createElement("div");
      rctFormulaComponentsLabel.id = "rctFormulaComponentsLabel";
      rctFormulaComponentsLabel.className = "rct-formula-components-label-row";
      rctFormulaComponentsToggle = doc.createElement("button");
      rctFormulaComponentsToggle.id = "rctFormulaComponentsToggle";
      rctFormulaComponentsToggle.className = "rct-formula-components-toggle";
      rctFormulaComponentsToggle.type = "button";
      rctFormulaComponentsLabel.appendChild(rctFormulaComponentsToggle);

      rctFormulaComponentsBox = doc.createElement("div");
      rctFormulaComponentsBox.id = "rctFormulaComponentsBox";
      rctFormulaComponentsBox.className = "rct-formula-components-box";
      rctFormulaComponentsBox.setAttribute("role", "listbox");
      rctFormulaComponentsBox.setAttribute("tabindex", "0");
      rctFormulaComponentsBox.setAttribute("aria-label", "Formula components for selected level");

      if (frame?.classList?.contains("rct-formula-frame")) {
        frame.appendChild(rctFormulaComponentsLabel);
        frame.appendChild(rctFormulaComponentsBox);
      } else {
        const next = rctEditFormula.nextSibling;
        body.insertBefore(rctFormulaComponentsLabel, next);
        body.insertBefore(rctFormulaComponentsBox, next);
      }
    }
    if (rctFormulaComponentsLabel && !rctFormulaComponentsToggle) {
      rctFormulaComponentsLabel.classList.add("rct-formula-components-label-row");
      rctFormulaComponentsLabel.textContent = "";
      rctFormulaComponentsToggle = doc.createElement("button");
      rctFormulaComponentsToggle.id = "rctFormulaComponentsToggle";
      rctFormulaComponentsToggle.className = "rct-formula-components-toggle";
      rctFormulaComponentsToggle.type = "button";
      rctFormulaComponentsLabel.appendChild(rctFormulaComponentsToggle);
    }
    updateReservingClassFormulaComponentsCollapsedState();

    if (!rctFormulaComponentsWired) {
      rctFormulaComponentsWired = true;
      rctEditLevel?.addEventListener("input", () => renderReservingClassFormulaComponents());
      rctEditLevel?.addEventListener("change", () => renderReservingClassFormulaComponents());

      wireReservingClassFormulaComponentDropTarget(rctEditFormula);
      wireReservingClassFormulaComponentDropTarget(rctFormulaReviewBox);
      wireReservingClassFormulaComponentReturnDropTarget(rctFormulaComponentsBox);
      wireReservingClassFormulaComponentGlobalDropGuard();
      const wireReviewModeControl = (targetKind) => {
        const target = getReservingClassFormulaTargetByKind(targetKind);
        const reviewBox = getReservingClassFormulaReviewBoxByKind(targetKind);
        reviewBox?.addEventListener("dblclick", () => {
          clearReservingClassFormulaReviewClickTimer();
          setReservingClassFormulaModeByKind(targetKind, "edit", { focus: true });
        });
        reviewBox?.addEventListener("keydown", (evt) => {
          if (String(evt?.key || "") !== "Enter") return;
          evt.preventDefault();
          setReservingClassFormulaModeByKind(targetKind, "edit", { focus: true });
        });
        target?.addEventListener("keydown", (evt) => {
          if (String(evt?.key || "") !== "Escape") return;
          evt.preventDefault();
          evt.stopPropagation();
          if (typeof evt.stopImmediatePropagation === "function") evt.stopImmediatePropagation();
          setReservingClassFormulaModeByKind(targetKind, "review");
        });
      };
      wireReviewModeControl("formula");
      doc.addEventListener("mousedown", (evt) => {
        const path = typeof evt?.composedPath === "function" ? evt.composedPath() : [];
        if (rctFormulaMode === "edit") {
          if (!Array.isArray(path) || !path.includes(rctEditFormula)) {
            setReservingClassFormulaModeByKind("formula", "review");
          }
        }
      });

      rctFormulaComponentsBox.addEventListener("contextmenu", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        openReservingClassFormulaComponentsMenu(evt.clientX, evt.clientY, "formula");
      });
      rctFormulaComponentsToggle?.addEventListener("click", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        rctFormulaComponentsCollapsed = !rctFormulaComponentsCollapsed;
        updateReservingClassFormulaComponentsCollapsedState();
      });
    }

    return rctFormulaComponentsBox;
  }

  function openReservingClassFormulaComponentsMenu(x, y, targetKind = "formula") {
    closeReservingClassFormulaComponentsMenu();
    const target = getReservingClassFormulaTargetByKind(targetKind);
    const selected = getReservingClassFormulaComponentValues(rctEditorProject);
    const canAppend = !target?.disabled && selected.values.length > 0;
    const sourceSet = getReservingClassTypesSourceSet(rctEditorProject);
    const importedValues = selected.values.filter((value) => sourceSet.has(canonReservingClassTypeName(value)));
    const canAppendImported = !target?.disabled && importedValues.length > 0;
    const menu = document.createElement("div");
    menu.className = "context-menu rct-formula-components-menu show";

    const appendMenuItem = (label, enabled, onClick) => {
      const item = document.createElement("div");
      item.className = `context-menu-item${enabled ? "" : " disabled"}`;
      item.textContent = label;
      item.setAttribute("role", "menuitem");
      item.setAttribute("aria-disabled", enabled ? "false" : "true");
      item.addEventListener("click", (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        if (!enabled) return;
        onClick();
        closeReservingClassFormulaComponentsMenu();
      });
      menu.appendChild(item);
    };

    appendMenuItem("Select All Components", canAppend, () => {
      appendReservingClassFormulaComponentsToTarget(target, selected.values, { replaceFormula: true });
    });
    appendMenuItem("Select All Imported Items", canAppendImported, () => {
      appendReservingClassFormulaComponentsToTarget(target, importedValues, { replaceFormula: true });
    });
    document.body.appendChild(menu);

    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(window.innerWidth - rect.width - 8, Number(x) || 0));
    const top = Math.max(8, Math.min(window.innerHeight - rect.height - 8, Number(y) || 0));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;

    const onMouseDown = (evt) => {
      if (menu.contains(evt.target)) return;
      closeReservingClassFormulaComponentsMenu();
    };
    const onKeyDown = (evt) => {
      if (String(evt?.key || "") !== "Escape") return;
      evt.preventDefault();
      evt.stopPropagation();
      closeReservingClassFormulaComponentsMenu();
    };
    const onContextMenu = (evt) => {
      if (menu.contains(evt.target)) return;
      closeReservingClassFormulaComponentsMenu();
    };
    document.addEventListener("mousedown", onMouseDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("contextmenu", onContextMenu, true);
    rctFormulaComponentsMenu = { menu, onMouseDown, onKeyDown, onContextMenu };
  }

  function renderReservingClassFormulaComponentsForTarget(targetKind) {
    const box = rctFormulaComponentsBox;
    const target = rctEditFormula;
    if (!box || !target) return;
    const selected = getReservingClassFormulaComponentValues(rctEditorProject);
    const locked = !!target.disabled;
    box.innerHTML = "";
    box.classList.toggle("disabled", locked);

    const appendEmpty = (message) => {
      const empty = document.createElement("div");
      empty.className = "rct-formula-components-empty";
      empty.textContent = message;
      box.appendChild(empty);
    };

    if (locked) {
      appendEmpty("Formula is locked.");
      return;
    }
    for (const operator of RCT_FORMULA_OPERATOR_VALUES) {
      const chip = document.createElement("span");
      const isActiveOperator = normalizeReservingClassFormulaPendingOperator(getReservingClassFormulaPendingOperator(targetKind)) === operator;
      const opClass = operator === "+" ? " plus" : " minus";
      chip.className = `rct-formula-component-chip operator rct-formula-token${opClass}${isActiveOperator ? " active" : ""}`;
      chip.draggable = false;
      chip.appendChild(createReservingClassFormulaOperatorIcon(operator));
      chip.title = `Use ${operator} before the next component`;
      chip.setAttribute("role", "button");
      chip.setAttribute("tabindex", "0");
      chip.setAttribute("aria-pressed", isActiveOperator ? "true" : "false");
      chip.addEventListener("mousedown", () => {
        if (getReservingClassFormulaModeByKind(targetKind) === "edit") setReservingClassFormulaModeByKind(targetKind, "review");
      });
      chip.addEventListener("click", () => {
        setReservingClassFormulaPendingOperatorForTarget(targetKind, operator);
      });
      chip.addEventListener("keydown", (evt) => {
        const key = String(evt?.key || "");
        if (key !== "Enter" && key !== " ") return;
        evt.preventDefault();
        setReservingClassFormulaPendingOperatorForTarget(targetKind, operator);
      });
      box.appendChild(chip);
    }
    if (!selected.level) {
      appendEmpty("Enter a level to show components.");
      return;
    }
    if (!selected.values.length) {
      appendEmpty("No components at selected level.");
      return;
    }

    const formulaRefs = getReservingClassFormulaComponentKeys(target.value ?? "", selected.values);
    let availableCount = 0;
    for (const value of selected.values) {
      const selectedInFormula = formulaRefs.has(canonReservingClassTypeName(value));
      if (selectedInFormula) continue;
      availableCount += 1;
      const chip = document.createElement("span");
      chip.className = "rct-formula-component-chip";
      chip.draggable = true;
      if (selected.calculatedKeys?.has(canonReservingClassTypeName(value))) {
        chip.appendChild(createReservingClassFormulaCalculatedIcon());
      }
      const label = document.createElement("span");
      label.className = "rct-formula-component-text";
      label.textContent = value;
      chip.appendChild(label);
      chip.title = "Drag to Formula, or click to add";
      chip.setAttribute("role", "option");
      chip.addEventListener("mousedown", () => {
        if (getReservingClassFormulaModeByKind(targetKind) === "edit") setReservingClassFormulaModeByKind(targetKind, "review");
      });
      chip.addEventListener("dragstart", (evt) => {
        if (getReservingClassFormulaModeByKind(targetKind) === "edit") setReservingClassFormulaModeByKind(targetKind, "review");
        const payload = { type: "rct_formula_component", target: String(targetKind || "formula"), level: selected.level, value };
        setReservingClassFormulaComponentDragPayload(evt, payload);
      });
      chip.addEventListener("click", () => {
        animateReservingClassFormulaComponentSelection(chip, targetKind);
        appendReservingClassFormulaComponentsToTarget(target, value, { usePendingOperator: true });
      });
      box.appendChild(chip);
    }
    if (!availableCount) appendEmpty("All selected-level components are in the formula.");
  }

  function renderReservingClassFormulaComponents() {
    ensureReservingClassFormulaComponentsSection();
    renderReservingClassFormulaComponentsForTarget("formula");
  }

  function uniqueReservingClassTypeNames(names) {
    const out = [];
    const seen = new Set();
    for (const raw of Array.isArray(names) ? names : []) {
      const value = String(raw ?? "").trim();
      const key = canonReservingClassTypeName(value);
      if (!value || !key || seen.has(key)) continue;
      seen.add(key);
      out.push(value);
    }
    return out;
  }

  function uniqueExactStrings(values) {
    const out = [];
    const seen = new Set();
    for (const raw of Array.isArray(values) ? values : []) {
      const value = String(raw ?? "");
      if (!value || seen.has(value)) continue;
      seen.add(value);
      out.push(value);
    }
    return out;
  }

  function escapeRegExp(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function reservingFormulaNameRequiresQuotes(value) {
    return /[+\-*/]/.test(String(value ?? ""));
  }

  function extractFormulaComponentRefs(formula, knownNames = []) {
    const text = String(formula ?? "").trim();
    if (!text) return [];

    const out = [];
    const quotedSeen = new Set();
    const used = [];
    for (const match of Array.from(text.matchAll(/"([^"]*)"/g))) {
      const value = String(match?.[1] ?? "");
      const start = Number(match?.index ?? -1);
      const end = start >= 0 ? start + String(match?.[0] ?? "").length : -1;
      if (start >= 0 && end >= start) used.push({ start, end });
      if (!value || quotedSeen.has(value)) continue;
      quotedSeen.add(value);
      out.push({ name: value, quoted: true });
    }

    const uniqueNames = uniqueReservingClassTypeNames(knownNames).sort((a, b) => b.length - a.length);
    const matches = [];
    for (const name of uniqueNames) {
      const pattern = new RegExp(`(?<![A-Za-z0-9_])${escapeRegExp(name)}(?![A-Za-z0-9_])`, "gi");
      let match;
      while ((match = pattern.exec(text)) !== null) {
        matches.push({ start: match.index, end: match.index + match[0].length, name });
      }
    }

    const seenKeys = new Set();
    let residual = text;
    if (used.length || matches.length) {
      const chars = Array.from(text);
      for (const entry of used) {
        for (let i = entry.start; i < entry.end && i < chars.length; i += 1) chars[i] = " ";
      }
      matches.sort((a, b) => (a.start - b.start) || ((b.end - b.start) - (a.end - a.start)));
      for (const match of matches) {
        const overlap = used.some((entry) => match.start < entry.end && match.end > entry.start);
        if (overlap) continue;
        used.push({ start: match.start, end: match.end });
        const key = canonReservingClassTypeName(match.name);
        if (!key || seenKeys.has(key)) continue;
        seenKeys.add(key);
        out.push({ name: match.name, quoted: false });
        for (let i = match.start; i < match.end && i < chars.length; i += 1) chars[i] = " ";
      }
      residual = chars.join("");
    }

    const tokenParts = residual
      .replace(/[()]/g, " ")
      .split(/[+\-*/]/)
      .map((part) => String(part ?? "").trim())
      .filter(Boolean)
      .filter((part) => !/^\d+(\.\d+)?$/.test(part));
    for (const token of tokenParts) {
      const key = canonReservingClassTypeName(token);
      if (!key || seenKeys.has(key)) continue;
      seenKeys.add(key);
      out.push({ name: token, quoted: false });
    }
    return out;
  }

  function collectInvalidFormulaReferences(projectName, rows, columns, options = {}) {
    const idx = getReservingClassTypeColIndexes(columns);
    const nameIdx = idx.name >= 0 ? idx.name : 0;
    const formulaIdx = idx.formula >= 0 ? idx.formula : 2;
    const allKnownNames = (Array.isArray(rows) ? rows : [])
      .map((row) => String(row?.[nameIdx] ?? "").trim())
      .filter(Boolean);
    const knownNames = uniqueReservingClassTypeNames(allKnownNames);
    const knownExactNames = new Set(allKnownNames);
    const knownKeys = new Set(knownNames.map((name) => canonReservingClassTypeName(name)).filter(Boolean));
    const targetRowIndexes = Array.isArray(options?.rowIndexes)
      ? new Set(options.rowIndexes.filter((value) => Number.isInteger(value) && value >= 0))
      : null;
    const issues = [];

    for (let rowIndex = 0; rowIndex < (Array.isArray(rows) ? rows.length : 0); rowIndex += 1) {
      if (targetRowIndexes && !targetRowIndexes.has(rowIndex)) continue;
      const row = rows[rowIndex];
      const rowName = String(row?.[nameIdx] ?? "").trim() || `Row ${rowIndex + 1}`;
      for (const field of [{ label: "Formula", idx: formulaIdx }]) {
        const formula = normalizeOperatorSpacing(row?.[field.idx] ?? "");
        if (!formula) continue;
        const components = extractFormulaComponentRefs(formula, knownNames);
        const invalid = [];
        for (const component of components) {
          const value = String(component?.name ?? "");
          if (!value) continue;
          if (!component?.quoted && reservingFormulaNameRequiresQuotes(value)) {
            invalid.push(value);
            continue;
          }
          const isValid = component?.quoted
            ? knownExactNames.has(value)
            : knownKeys.has(canonReservingClassTypeName(value));
          if (isValid) continue;
          invalid.push(value);
        }
        if (!invalid.length) continue;
        issues.push({
          rowIndex,
          rowName,
          fieldLabel: field.label,
          invalidComponents: uniqueExactStrings(invalid),
        });
      }
    }

    return issues;
  }

  function buildInvalidFormulaWarningMessage(projectName, issues) {
    const issue = Array.isArray(issues) && issues.length ? issues[0] : null;
    if (!issue) return "Invalid component(s) in formula.";
    const fieldLabel = String(issue.fieldLabel || "Formula").trim().toLowerCase();
    return `Invalid component(s) in ${fieldLabel}: ${issue.invalidComponents.join(", ")}. Check spacing and spelling. Names containing +, -, *, or / must be quoted.`;
  }

  function validateReservingClassTypesRows(projectName, rows, columns, options = {}) {
    const issues = collectInvalidFormulaReferences(projectName, rows, columns, options);
    if (!issues.length) return { ok: true, issues: [] };
    setReservingClassTypesStatus("Formula can only reference existing reserving class types; names containing +, -, *, or / must be quoted.", true);
    if (options.showTooltip !== false) {
      showReservingClassTypesValidationTooltip(
        options.formulaAnchorElement,
        buildInvalidFormulaWarningMessage(projectName, issues),
      );
    }
    return { ok: false, issues };
  }

  function normalizeLocalReservingClassTypesPayload(raw) {
    const fallback = { columns: [...RESERVING_CLASS_TYPES_COLUMNS], rows: [] };
    if (!raw || typeof raw !== "object") return fallback;

    const rawColumns = Array.isArray(raw.columns) ? raw.columns : [];
    const columnIndexByName = new Map();
    for (let i = 0; i < rawColumns.length; i += 1) {
      const key = String(rawColumns[i] ?? "").trim().toLowerCase();
      if (!key || columnIndexByName.has(key)) continue;
      columnIndexByName.set(key, i);
    }

    const rawRows = Array.isArray(raw.rows) ? raw.rows : [];
    const rows = [];
    for (const rawRow of rawRows) {
      if (!Array.isArray(rawRow)) continue;
      const pickValue = (name, fallbackIndex) => {
        const idx = columnIndexByName.has(name) ? columnIndexByName.get(name) : fallbackIndex;
        return String(rawRow?.[idx] ?? "").trim();
      };
      const row = sanitizeReservingClassTypesRow([
        pickValue("name", 0),
        pickValue("level", 1),
        pickValue("formula", 2),
      ]);
      if (row[0] !== "" || row[1] !== "" || row[2] !== "") {
        rows.push(row);
      }
    }

    return { columns: [...RESERVING_CLASS_TYPES_COLUMNS], rows };
  }

  function closeReservingClassTypeEditor() {
    hideReservingClassTypesValidationTooltip();
    closeReservingClassFormulaComponentsMenu();
    clearReservingClassFormulaReviewClickTimer();
    if (!reservingClassTypeEditor) return;
    reservingClassTypeEditor.classList.remove("show");
    rctEditFormula?.classList.remove("rct-formula-drop-target");
    rctFormulaReviewBox?.classList.remove("rct-formula-drop-target");
    reservingClassTypeEditor.style.left = "";
    reservingClassTypeEditor.style.top = "";
    reservingClassTypeEditor.style.transform = "translateX(-50%)";
    rctEditorProject = "";
    rctEditorRowIndex = -1;
    rctEditorMode = "edit";
    rctEditorInsertAfterIndex = -1;
    rctEditorDragState = null;
    rctEditorResizeState = null;
    rctFormulaMode = "review";
    rctFormulaPendingOperator = "+";
  }

  function openReservingClassTypeEditor(projectName, rowIndex, options = {}) {
    hideReservingClassTypesValidationTooltip();
    ensureReservingClassTypesValidationTooltipWiring();
    ensureReservingClassFormulaComponentsSection();
    if (!reservingClassTypeEditor || !projectName) return;
    const mode = String(options?.mode || "edit").toLowerCase() === "add" ? "add" : "edit";
    const state = getProjectReservingClassTypesState(projectName);
    const columns = Array.isArray(state.columns) && state.columns.length ? state.columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    if (!Array.isArray(state.rows)) return;
    if (mode === "edit" && (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length)) return;
    const idx = getReservingClassTypeColIndexes(columns);
    const row = mode === "edit" ? state.rows[rowIndex] : null;
    const rowName = mode === "edit" ? canonReservingClassTypeName(row?.[idx.name] ?? "") : "";
    const sourceSet = getReservingClassTypesSourceSet(projectName);
    const isSourceDerived = mode === "edit" ? (!!rowName && sourceSet.has(rowName)) : false;
    const defaultLevel = (() => {
      if (options && Object.prototype.hasOwnProperty.call(options, "seedLevel")) {
        return String(options.seedLevel ?? "").trim();
      }
      if (mode === "edit") {
        const levelIdx = idx.level >= 0 ? idx.level : 1;
        return String(row?.[levelIdx] ?? "");
      }
      if (Number.isInteger(rowIndex) && rowIndex >= 0 && rowIndex < state.rows.length) {
        const levelIdx = idx.level >= 0 ? idx.level : 1;
        return String(state.rows[rowIndex]?.[levelIdx] ?? "");
      }
      return "";
    })();

    if (reservingClassTypeEditorTitle) {
      reservingClassTypeEditorTitle.textContent = mode === "add"
        ? "Add User Defined Reserving Class Type"
        : `Edit Reserving Class Type (Row ${rowIndex + 1})`;
    }
    if (rctEditName) {
      rctEditName.value = mode === "add" ? "" : String(row?.[idx.name] ?? "");
    }
    if (rctEditLevel) {
      rctEditLevel.value = defaultLevel;
    }
    if (rctEditFormula) {
      const formulaIdx = idx.formula >= 0 ? idx.formula : 2;
      rctEditFormula.value = mode === "add" ? "" : String(row?.[formulaIdx] ?? "");
      rctEditFormula.disabled = isSourceDerived;
      rctEditFormula.style.height = "";
    }
    rctEditorProject = projectName;
    rctEditorMode = mode;
    rctEditorRowIndex = mode === "edit" ? rowIndex : -1;
    rctEditorInsertAfterIndex = Number.isInteger(options?.insertAfterIndex)
      ? options.insertAfterIndex
      : (Number.isInteger(rowIndex) ? rowIndex : -1);
    autoSizeReservingClassFormulaInput();
    setReservingClassFormulaMode("review", { blur: false });
    renderReservingClassFormulaComponents();
    reservingClassTypeEditor.style.transform = "translateX(-50%)";
    reservingClassTypeEditor.style.left = "50%";
    reservingClassTypeEditor.style.top = "140px";
    reservingClassTypeEditor.classList.add("show");
    setTimeout(() => {
      if (rctEditName && !rctEditName.disabled) rctEditName.focus();
      else if (rctEditLevel && !rctEditLevel.disabled) rctEditLevel.focus();
    }, 0);
  }

  function applyReservingClassTypeEditor() {
    const projectName = rctEditorProject;
    const mode = rctEditorMode;
    const rowIndex = rctEditorRowIndex;
    if (!projectName) return;

    const state = getProjectReservingClassTypesState(projectName);
    const columns = Array.isArray(state.columns) && state.columns.length ? state.columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    const idx = getReservingClassTypeColIndexes(columns);
    if (!Array.isArray(state.rows)) return;

    const nameValue = String(rctEditName?.value ?? "").trim();
    const levelValue = String(rctEditLevel?.value ?? "").trim();
    const formulaValue = normalizeReservingClassFormulaInputSyntax(rctEditFormula);
    renderReservingClassFormulaReview();
    renderReservingClassFormulaComponents();
    hideReservingClassTypesValidationTooltip();
    if (!nameValue) {
      setReservingClassTypesStatus("Name is required.", true);
      if (rctEditName) rctEditName.focus();
      return;
    }
    if (mode === "add" && !formulaValue) {
      setReservingClassTypesStatus("Formula is required for Add (user defined type).", true);
      setReservingClassFormulaMode("edit", { focus: true });
      return;
    }

    let targetRowIndex = rowIndex;
    let target = null;
    if (mode === "edit") {
      if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length) return;
      const row = state.rows[rowIndex];
      if (!Array.isArray(row)) return;
      if (row.length < columns.length) {
        const fallback = createEmptyReservingClassTypesRow(columns.length);
        for (let i = 0; i < row.length && i < columns.length; i++) fallback[i] = row[i];
        state.rows[rowIndex] = fallback;
      }
      target = state.rows[rowIndex];
    } else {
      const key = canonReservingClassTypeName(nameValue);
      const existingIdx = state.rows.findIndex((r) => {
        if (!Array.isArray(r)) return false;
        const n = String(r[idx.name] ?? "").trim();
        return canonReservingClassTypeName(n) === key;
      });
      if (existingIdx >= 0) {
        targetRowIndex = existingIdx;
        if (state.rows[existingIdx].length < columns.length) {
          const fallback = createEmptyReservingClassTypesRow(columns.length);
          for (let i = 0; i < state.rows[existingIdx].length && i < columns.length; i++) fallback[i] = state.rows[existingIdx][i];
          state.rows[existingIdx] = fallback;
        }
        target = state.rows[existingIdx];
      } else {
        const newRow = createEmptyReservingClassTypesRow(columns.length);
        const after = Number.isInteger(rctEditorInsertAfterIndex) ? rctEditorInsertAfterIndex : -1;
        const insertPos = Math.max(0, Math.min(state.rows.length, after + 1));
        state.rows.splice(insertPos, 0, newRow);
        targetRowIndex = insertPos;
        target = state.rows[insertPos];
      }
    }
    if (!Array.isArray(target)) return;

    const formulaIdx = idx.formula >= 0 ? idx.formula : 2;
    const nextRow = target.slice();
    nextRow[idx.name] = nameValue;
    if (idx.level >= 0) {
      nextRow[idx.level] = levelValue;
    } else if (nextRow.length > 1) {
      nextRow[1] = levelValue;
    }
    if (!(rctEditFormula?.disabled)) nextRow[formulaIdx] = formulaValue;

    const nextRows = state.rows.map((row, currentIndex) => (currentIndex === targetRowIndex ? nextRow : row));
    const validation = validateReservingClassTypesRows(projectName, nextRows, columns, {
      rowIndexes: [targetRowIndex],
      formulaAnchorElement: rctEditFormula,
    });
    if (!validation.ok) {
      setReservingClassFormulaMode("edit", { focus: true });
      showReservingClassTypesValidationTooltip(rctEditFormula, buildInvalidFormulaWarningMessage(projectName, validation.issues));
      if (mode === "add" && targetRowIndex >= 0 && targetRowIndex < state.rows.length && target === state.rows[targetRowIndex]) {
        state.rows.splice(targetRowIndex, 1);
      }
      return;
    }

    for (let i = 0; i < nextRow.length; i += 1) target[i] = nextRow[i];
    if (!(rctEditFormula?.disabled) && rctEditFormula) rctEditFormula.value = formulaValue;

    renderReservingClassTypesTable(projectName);
    setReservingClassTypesStatus("");
    scheduleReservingClassTypesAutoSave(projectName);
    closeReservingClassTypeEditor();
  }

  function createEmptyReservingClassTypesRow(columnCount = RESERVING_CLASS_TYPES_COLUMNS.length) {
    return Array.from({ length: Math.max(1, Number(columnCount) || RESERVING_CLASS_TYPES_COLUMNS.length) }, () => "");
  }

  function normalizeReservingClassTypesPayload(payload) {
    const fallback = {
      columns: [...RESERVING_CLASS_TYPES_COLUMNS],
      rows: [],
    };
    if (!payload || typeof payload !== "object") return fallback;

    const rawColumns = Array.isArray(payload.columns) ? payload.columns : RESERVING_CLASS_TYPES_COLUMNS;
    const columnIndexByName = new Map();
    rawColumns.forEach((value, index) => {
      const key = String(value || "").trim().toLowerCase();
      if (key && !columnIndexByName.has(key)) columnIndexByName.set(key, index);
    });

    const rawRows = Array.isArray(payload.rows) ? payload.rows : [];
    const rows = [];
    for (const rawRow of rawRows) {
      if (!Array.isArray(rawRow)) continue;
      const row = sanitizeReservingClassTypesRow([
        rawRow[columnIndexByName.get("name") ?? 0],
        rawRow[columnIndexByName.get("level") ?? 1],
        rawRow[columnIndexByName.get("formula") ?? 2],
      ]);
      if (row.some((v) => String(v).trim() !== "")) {
        rows.push(row);
      }
    }
    return { columns: [...RESERVING_CLASS_TYPES_COLUMNS], rows };
  }

  /**
   * Flowing placeholder rows while the types are read from the project folder.
   *
   * The visible column count is read from the live header, which this tab
   * rebuilds for itself, so the placeholder always matches the arriving grid.
   */
  function renderReservingClassTypesLoading() {
    renderTableSkeletonRows(reservingClassTypesBody, { columns: 2 });
  }

  function renderReservingClassTypesEmpty(message, colspan = 3) {
    if (!reservingClassTypesBody) return;
    clearTableSkeletonRows(reservingClassTypesBody);
    const span = Math.max(1, Number(colspan) || 3);
    reservingClassTypesBody.innerHTML = `
      <tr>
        <td colspan="${span}" class="dataset-types-empty">${escapeHtml(message || "No rows found.")}</td>
      </tr>
    `;
  }

  async function ensureReservingClassTypesLoaded(projectName, options = {}) {
    const force = !!options?.force;
    const key = normalizeProjectKey(projectName);
    if (!key) return false;
    if (!force && loadedReservingClassTypesByProject.has(key)) return true;
    if (force) loadedReservingClassTypesByProject.delete(key);

    const state = getProjectReservingClassTypesState(projectName);
    try {
      const res = await fetchImpl(`/reserving_class_types?project_name=${encodeURIComponent(projectName)}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      const out = await res.json();
      const parsed = normalizeReservingClassTypesPayload(out?.data);
      state.columns = [...parsed.columns];
      state.rows = parsed.rows.map((r) => r.map((v) => String(v ?? "")));
      setReservingClassTypesSourceNames(projectName, Array.isArray(out?.source_derived_names) ? out.source_derived_names : []);
      loadedReservingClassTypesByProject.add(key);
      return true;
    } catch (err) {
      setReservingClassTypesStatus(`Load error: ${err.message}`, true);
      state.columns = [...RESERVING_CLASS_TYPES_COLUMNS];
      state.rows = [];
      setReservingClassTypesSourceNames(projectName, []);
      return false;
    }
  }

  function showReservingClassTypesRowContextMenu(x, y, projectName, rowIndex, cellText = "") {
    if (!reservingClassTypesRowContextMenu) return;
    reservingClassTypesContextProject = projectName || "";
    reservingClassTypesContextRowIndex = rowIndex;
    reservingClassTypesContextCellText = String(cellText ?? "");
    positionContextMenu(reservingClassTypesRowContextMenu, x, y);
  }

  function hideReservingClassTypesRowContextMenu() {
    if (!reservingClassTypesRowContextMenu) return;
    reservingClassTypesRowContextMenu.classList.remove("show");
    reservingClassTypesContextProject = "";
    reservingClassTypesContextRowIndex = -1;
    reservingClassTypesContextCellText = "";
  }

  function deleteReservingClassTypesRow(projectName, rowIndex) {
    const state = getProjectReservingClassTypesState(projectName);
    if (!state.rows.length) return;
    if (!Number.isInteger(rowIndex) || rowIndex < 0 || rowIndex >= state.rows.length) return;
    state.rows.splice(rowIndex, 1);
    if (!state.rows.length) {
      state.rows.push(createEmptyReservingClassTypesRow((state.columns || []).length || RESERVING_CLASS_TYPES_COLUMNS.length));
    }
    renderReservingClassTypesTable(projectName);
    scheduleReservingClassTypesAutoSave(projectName);
  }

  function renderReservingClassTypesTable(projectName) {
    if (!reservingClassTypesBody) return;
    if (!projectName) {
      renderReservingClassTypesEmpty("Select a project to load reserving class types.");
      return;
    }

    const table = document.getElementById("reservingClassTypesTable");
    const state = getProjectReservingClassTypesState(projectName);
    const sourceSet = getReservingClassTypesSourceSet(projectName);
    const collapsedSet = getCollapsedGroups("reservingClassTypesTable");
    const sortState = getReservingClassTypesSortState();
    const columns = Array.isArray(state.columns) && state.columns.length ? state.columns : [...RESERVING_CLASS_TYPES_COLUMNS];
    state.columns = [...columns];
    const idx = getReservingClassTypeColIndexes(columns);
    const nameColIdx = idx.name;
    const levelColIdx = idx.level;
    const formulaColIdx = idx.formula;
    const visibleCols = [
      {
        label: "Name",
        idx: nameColIdx >= 0 ? nameColIdx : 0,
        width: "300px",
        minWidth: 130,
      },
      {
        label: "Formula",
        idx: formulaColIdx >= 0 ? formulaColIdx : 2,
        width: "420px",
        minWidth: 130,
      },
    ];

    if (!Array.isArray(state.rows) || state.rows.length === 0) {
      state.rows = [createEmptyReservingClassTypesRow(columns.length)];
    }

    if (table) {
      const colgroup = table.querySelector("colgroup");
      if (colgroup) {
        colgroup.innerHTML = "";
        visibleCols.forEach((c) => {
          const col = document.createElement("col");
          col.style.width = c.width;
          colgroup.appendChild(col);
        });
      }

      const thead = table.querySelector("thead");
      if (thead) {
        thead.innerHTML = "";
        const tr = document.createElement("tr");
        visibleCols.forEach((c) => {
          const th = document.createElement("th");
          const isActiveSort = sortState.colLabel === c.label && (sortState.dir === "asc" || sortState.dir === "desc");
          const icon = isActiveSort ? (sortState.dir === "asc" ? " \u25B2" : " \u25BC") : "";
          th.textContent = `${c.label}${icon}`;
          th.title = isActiveSort
            ? `${c.label}: ${sortState.dir === "asc" ? "ascending" : "descending"} (click to toggle)`
            : `${c.label}: unsorted (click to sort ascending)`;
          th.style.cursor = "pointer";
          th.addEventListener("click", (event) => {
            if (!event.target.closest(".table-col-label")) return;
            toggleReservingClassTypesSort(c.label);
            renderReservingClassTypesTable(projectName);
          });
          tr.appendChild(th);
        });
        thead.appendChild(tr);
      }
    }

    for (let i = 0; i < state.rows.length; i++) {
      if (!Array.isArray(state.rows[i])) {
        state.rows[i] = createEmptyReservingClassTypesRow(columns.length);
        continue;
      }
      if (state.rows[i].length < columns.length) {
        const fallback = createEmptyReservingClassTypesRow(columns.length);
        for (let j = 0; j < state.rows[i].length && j < columns.length; j++) {
          fallback[j] = state.rows[i][j];
        }
        state.rows[i] = fallback;
      }
    }

    const groups = new Map();
    state.rows.forEach((row, rowIndex) => {
      const levelKey = getReservingClassLevelKey(levelColIdx >= 0 ? row[levelColIdx] : "");
      if (!groups.has(levelKey)) {
        groups.set(levelKey, {
          key: levelKey,
          label: levelKey ? `Level: ${levelKey}` : "Level: (blank)",
          rows: [],
        });
      }
      groups.get(levelKey).rows.push({ row, rowIndex });
    });

    const sortedGroups = Array.from(groups.values()).sort((a, b) => {
      const aKey = String(a.key || "");
      const bKey = String(b.key || "");
      const aNum = Number(aKey);
      const bNum = Number(bKey);
      const aIsNum = Number.isFinite(aNum) && aKey !== "";
      const bIsNum = Number.isFinite(bNum) && bKey !== "";
      if (aIsNum && bIsNum) return aNum - bNum;
      if (aIsNum && !bIsNum) return -1;
      if (!aIsNum && bIsNum) return 1;
      if (!aKey && bKey) return 1;
      if (aKey && !bKey) return -1;
      return aKey.localeCompare(bKey);
    });

    clearTableSkeletonRows(reservingClassTypesBody);
    reservingClassTypesBody.innerHTML = "";
    for (const group of sortedGroups) {
      const collapsed = collapsedSet.has(group.key);
      const setCollapsed = (keys, nextCollapsed) => {
        for (const key of keys) {
          if (nextCollapsed) collapsedSet.add(key);
          else collapsedSet.delete(key);
        }
        saveCollapsedGroups("reservingClassTypesTable");
        renderReservingClassTypesTable(projectName);
      };
      const allKeys = sortedGroups.map((item) => item.key);
      reservingClassTypesBody.appendChild(createTableGroupRow({
        text: group.label,
        colSpan: visibleCols.length,
        collapsed,
        count: group.rows.length,
        onToggle: () => setCollapsed([group.key], !collapsed),
        onContextMenu: (event) => showTableGroupContextMenu(event.clientX, event.clientY, {
          collapseAll: () => setCollapsed(allKeys, true),
          expandAll: () => setCollapsed(allKeys, false),
        }),
      }));

      if (collapsed) continue;

      const sortCol = visibleCols.find((c) => c.label === sortState.colLabel);
      const sortIdx = sortCol ? sortCol.idx : -1;
      const sortDir = sortState.dir === "desc" ? "desc" : "asc";
      const rowsToRender = group.rows.slice();
      if (sortIdx >= 0 && sortState.dir) {
        rowsToRender.sort((a, b) => {
          const cmp = compareReservingClassTypeSortValues(
            a?.row?.[sortIdx],
            b?.row?.[sortIdx],
            sortDir,
          );
          if (cmp !== 0) return cmp;
          return (a?.rowIndex ?? 0) - (b?.rowIndex ?? 0);
        });
      }

      for (const item of rowsToRender) {
        const { row, rowIndex } = item;
        const tr = document.createElement("tr");
        tr.dataset.rowIndex = String(rowIndex);

        const rowName = canonReservingClassTypeName(row[nameColIdx >= 0 ? nameColIdx : 0] ?? "");
        const isSourceDerived = !!rowName && sourceSet.has(rowName);

        visibleCols.forEach((c) => {
          const td = document.createElement("td");
          td.dataset.col = c.label;
          const text = document.createElement("div");
          text.className = "rct-cell-text";
          text.textContent = String(row[c.idx] ?? "");
          if (isSourceDerived && c.idx === formulaColIdx) {
            td.title = "Source-derived rows lock formula fields.";
          }
          td.appendChild(text);
          tr.appendChild(td);
        });

        tr.addEventListener("contextmenu", (e) => {
          e.preventDefault();
          e.stopPropagation();
          hideContextMenu();
          hideFolderContextMenu();
          hideTreeContextMenu();
          hideDatasetTypesRowContextMenu();
          const cell = e.target?.closest?.("td");
          const cellText = cell ? String(cell.textContent ?? "") : "";
          showReservingClassTypesRowContextMenu(e.clientX, e.clientY, projectName, rowIndex, cellText);
        });

        reservingClassTypesBody.appendChild(tr);
      }
    }

    initTableColumnResizing("reservingClassTypesTable", visibleCols.map((c) => c.minWidth));
  }

  async function loadReservingClassTypes(projectName, options = {}) {
    const requestSeq = ++reservingClassTypesLoadSeq;
    if (!projectName) {
      renderReservingClassTypesEmpty("Select a project to load reserving class types.");
      setReservingClassTypesStatus("");
      return;
    }

    setReservingClassTypesStatus("Loading reserving class types...");
    // A cached project renders in the same tick; only a real read needs the frame.
    if (options?.force || !loadedReservingClassTypesByProject.has(normalizeProjectKey(projectName))) {
      renderReservingClassTypesLoading();
    }
    const loadedOk = await ensureReservingClassTypesLoaded(projectName, options);
    if (requestSeq !== reservingClassTypesLoadSeq) return;
    renderReservingClassTypesTable(projectName);
    if (loadedOk) setReservingClassTypesStatus("");
  }

  async function saveReservingClassTypes(projectName) {
    if (!projectName) return false;
    const state = getProjectReservingClassTypesState(projectName);
    const columns = [...RESERVING_CLASS_TYPES_COLUMNS];
    const rows = buildPersistableReservingClassTypesRows(state.rows || []);

    setReservingClassTypesStatus("Saving reserving class types...");
    try {
      const res = await fetchImpl("/reserving_class_types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_name: projectName,
          columns,
          rows,
        }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          const body = await res.json();
          detail = String(body?.detail || "").trim();
        } catch {
          const text = await res.text();
          detail = String(text || "").trim();
        }
        throw new Error(detail || `HTTP ${res.status}`);
      }

      const out = await res.json();
      const parsed = normalizeReservingClassTypesPayload(out?.data);
      state.columns = [...parsed.columns];
      state.rows = parsed.rows.map((r) => r.map((v) => String(v ?? "")));
      setReservingClassTypesSourceNames(projectName, Array.isArray(out?.source_derived_names) ? out.source_derived_names : []);
      renderReservingClassTypesTable(projectName);
      setReservingClassTypesStatus(`Saved reserving class types to ${out.path}`);
      setStatus(`Saved reserving class types: ${projectName}`);
      await loadAuditLog(projectName, true);
      return true;
    } catch (err) {
      setReservingClassTypesStatus(`Save error: ${err.message}`, true);
      setStatus(`Reserving class types save error: ${err.message}`);
      return false;
    }
  }

  async function saveReservingClassTypesToLocalFile(projectName) {
    const name = String(projectName || "").trim();
    if (!name) {
      setReservingClassTypesStatus("Select a project first.", true);
      return;
    }

    const hostApi = window.ADAHost || window.parent?.ADAHost || window.top?.ADAHost;
    if (!hostApi?.saveJsonFile) {
      setReservingClassTypesStatus("Local save is available in the desktop app only.", true);
      return;
    }

    const state = getProjectReservingClassTypesState(name);
    const columns = Array.isArray(state.columns) && state.columns.length ? [...state.columns] : [...RESERVING_CLASS_TYPES_COLUMNS];
    const rows = buildPersistableReservingClassTypesRows(state.rows || []);
    const safeName = sanitizeFileStem(name) || "project";
    const suggestedName = `${safeName}_reserving_class_types.json`;
    let startDir = "";
    try {
      const docsPath = String((await hostApi.getDocumentsPath?.()) || "").trim();
      if (docsPath) {
        startDir = joinWinPath(docsPath, "ArcRho", "templates");
      }
    } catch {
      startDir = "";
    }

    setReservingClassTypesStatus("Saving reserving class types to local file...");
    try {
      const result = await hostApi.saveJsonFile({
        data: {
          project_name: name,
          columns: [...RESERVING_CLASS_TYPES_COLUMNS],
          rows,
        },
        suggestedName,
        startDir,
        filters: [{ name: "JSON", extensions: ["json"] }],
      });
      if (result?.canceled) {
        setReservingClassTypesStatus("Local save canceled.");
        return;
      }
      if (result?.error) {
        throw new Error(String(result.error || "Unable to save local file."));
      }
      const outPath = String(result?.path || "").trim();
      setReservingClassTypesStatus(outPath ? `Saved local reserving class types: ${outPath}` : "Saved local reserving class types.");
      setStatus(outPath ? `Saved Reserving Class Types local file: ${outPath}` : "Saved Reserving Class Types local file.");
    } catch (err) {
      const msg = String(err?.message || err || "Unable to save local file.");
      setReservingClassTypesStatus(`Local save failed: ${msg}`, true);
      setStatus(`Reserving class types local save error: ${msg}`);
    }
  }

  async function loadReservingClassTypesFromLocalFile(projectName) {
    const name = String(projectName || "").trim();
    if (!name) {
      setReservingClassTypesStatus("Select a project first.", true);
      return;
    }

    const hostApi = window.ADAHost || window.parent?.ADAHost || window.top?.ADAHost;
    if (!hostApi?.pickOpenFile) {
      setReservingClassTypesStatus("Local load is available in the desktop app only.", true);
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
          { name: "Reserving Class Types", extensions: ["json", "xlsx"] },
          { name: "JSON", extensions: ["json"] },
          { name: "Excel", extensions: ["xlsx"] },
        ],
      })) || "",
    ).trim();
    if (!pickedPath) {
      setReservingClassTypesStatus("Local load canceled.");
      return;
    }

    setReservingClassTypesStatus("Loading reserving class types from local file...");
    try {
      const parseRes = await fetchImpl("/reserving_class_types/import_local_file", {
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
      const parsed = normalizeLocalReservingClassTypesPayload(parseOut?.data);
      const state = getProjectReservingClassTypesState(name);
      state.columns = [...parsed.columns];
      state.rows = parsed.rows.length > 0 ? parsed.rows : [createEmptyReservingClassTypesRow(parsed.columns.length)];
      renderReservingClassTypesTable(name);
      scheduleReservingClassTypesAutoSave(name);

      const fileFormat = String(parseOut?.format || "").trim().toUpperCase();
      const formatText = fileFormat ? ` (${fileFormat})` : "";
      const finalMsg = `Loaded local reserving class types from ${pickedPath}${formatText}.`;
      setReservingClassTypesStatus(finalMsg);
      setStatus(finalMsg);
    } catch (err) {
      const msg = String(err?.message || err || "Unable to load local reserving class types.");
      setReservingClassTypesStatus(`Local load failed: ${msg}`, true);
      setStatus(`Reserving class types local load error: ${msg}`);
    }
  }

  async function handleReservingClassTypesRowContextAction(action) {
    if (!action || !reservingClassTypesContextProject) return;
    const projectName = reservingClassTypesContextProject;
    const rowIndex = reservingClassTypesContextRowIndex;
    const cellText = reservingClassTypesContextCellText;
    hideReservingClassTypesRowContextMenu();
    if (action === "copy-cell") {
      const ok = await copyTextToClipboard(cellText);
      if (ok) {
        setReservingClassTypesStatus("Cell value copied.");
      } else {
        setReservingClassTypesStatus("Unable to copy cell value.", true);
      }
    } else if (action === "edit-row") {
      openReservingClassTypeEditor(projectName, rowIndex);
    } else if (action === "add-type") {
      openReservingClassTypeEditor(projectName, rowIndex, {
        mode: "add",
        insertAfterIndex: Number.isInteger(rowIndex) ? rowIndex : -1,
      });
    } else if (action === "delete-row") {
      deleteReservingClassTypesRow(projectName, rowIndex);
    }
  }

  function onEditorHeaderMouseDown(e) {
    if (!reservingClassTypeEditor || e.button !== 0) return;
    const rect = reservingClassTypeEditor.getBoundingClientRect();
    // Convert to absolute pixel position before removing transform to avoid jump
    reservingClassTypeEditor.style.left = `${rect.left}px`;
    reservingClassTypeEditor.style.top = `${rect.top}px`;
    reservingClassTypeEditor.style.transform = "none";
    rctEditorDragState = {
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
    };
    e.preventDefault();
  }

  function pinReservingClassTypeEditorPosition(rect) {
    reservingClassTypeEditor.style.left = `${rect.left}px`;
    reservingClassTypeEditor.style.top = `${rect.top}px`;
    reservingClassTypeEditor.style.transform = "none";
  }

  function reservingClassTypeEditorSizeLimits() {
    const style = typeof getComputedStyle === "function"
      ? getComputedStyle(reservingClassTypeEditor)
      : null;
    const positiveNumber = (value, fallback) => {
      const parsed = parseFloat(value);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
    };
    return {
      minWidth: positiveNumber(style?.minWidth, 520),
      minHeight: positiveNumber(style?.minHeight, 320),
    };
  }

  function onEditorResizerMouseDown(e) {
    if (!reservingClassTypeEditor || e.button !== 0) return;
    const rect = reservingClassTypeEditor.getBoundingClientRect();
    pinReservingClassTypeEditorPosition(rect);
    rctEditorResizeState = {
      startX: e.clientX,
      startY: e.clientY,
      startWidth: rect.width,
      startHeight: rect.height,
      ...reservingClassTypeEditorSizeLimits(),
    };
    e.preventDefault();
    e.stopPropagation();
  }

  function onEditorMouseMove(e) {
    if (!reservingClassTypeEditor) return;
    if (rctEditorResizeState) {
      const state = rctEditorResizeState;
      const rect = reservingClassTypeEditor.getBoundingClientRect();
      const maxWidth = Math.max(state.minWidth, window.innerWidth - rect.left - 8);
      const maxHeight = Math.max(state.minHeight, window.innerHeight - rect.top - 8);
      const width = state.startWidth + (e.clientX - state.startX);
      const height = state.startHeight + (e.clientY - state.startY);
      reservingClassTypeEditor.style.width = `${Math.max(state.minWidth, Math.min(maxWidth, width))}px`;
      reservingClassTypeEditor.style.height = `${Math.max(state.minHeight, Math.min(maxHeight, height))}px`;
      return;
    }
    if (!rctEditorDragState) return;
    const left = Math.max(8, Math.min(window.innerWidth - reservingClassTypeEditor.offsetWidth - 8, e.clientX - rctEditorDragState.offsetX));
    const top = Math.max(8, Math.min(window.innerHeight - reservingClassTypeEditor.offsetHeight - 8, e.clientY - rctEditorDragState.offsetY));
    reservingClassTypeEditor.style.left = `${left}px`;
    reservingClassTypeEditor.style.top = `${top}px`;
  }

  function onEditorMouseUp() {
    rctEditorDragState = null;
    rctEditorResizeState = null;
  }

  return {
    setReservingClassTypesStatus,
    renderReservingClassTypesEmpty,
    renderReservingClassTypesLoading,
    closeReservingClassTypeEditor,
    openReservingClassTypeEditor,
    applyReservingClassTypeEditor,
    showReservingClassTypesRowContextMenu,
    hideReservingClassTypesRowContextMenu,
    deleteReservingClassTypesRow,
    renderReservingClassTypesTable,
    loadReservingClassTypes,
    saveReservingClassTypes,
    saveReservingClassTypesToLocalFile,
    loadReservingClassTypesFromLocalFile,
    handleReservingClassTypesRowContextAction,
    onEditorHeaderMouseDown,
    onEditorResizerMouseDown,
    onEditorMouseMove,
    onEditorMouseUp,
  };
}
