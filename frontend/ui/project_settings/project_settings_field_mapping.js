import { clearTableSkeletonRows } from "./project_settings_skeleton.js?v=20260821pstree1";

/**
 * Field Mapping - the Field Mapping step of the Import Settings window.
 *
 * The step lists the columns the chosen source will import, so a renamed or
 * new column is mapped before the import runs. Mapped columns the source no
 * longer has are named above the table and unmapped by the next save. The
 * window saves the mapping with its settings, with or without importing.
 */
export function createFieldMappingFeature(deps = {}) {
  const {
    fieldMappingBody = null,
    fieldMappingStatus = null,
    fieldMappingMissing = null,
    initTableColumnResizing = () => {},
    normalizeProjectKey = (name) => String(name || "").trim().toLowerCase(),
    fetchImpl = fetch,
    setStatus = () => {},
    getDatasetTypeNamesForProject = () => [],
    loadAuditLog = async () => {},
    syncDatasetTypesSources = async () => ({ ok: true }),
  } = deps;

  const FIELD_SIGNIFICANCE_OPTIONS = [
    "Not Used",
    "Reserving Class",
    "Origin Date",
    "Development Date",
    "Dataset",
  ];
  const DATASET_TYPE_PROMPT = "-- Select Dataset Type --";
  const DATASET_TYPE_NA = "-- N/A --";
  const fieldMappingByProject = new Map();
  const savedFieldMappingByProject = new Map();
  const loadedFieldMappingByProject = new Set();
  // The columns the step shows: what the chosen source will import.
  let currentFieldNames = [];
  let fieldMappingDatasetTypeDropdown = null;
  let fieldMappingDatasetTypeDropdownList = null;
  let fieldMappingDatasetTypeDropdownInput = null;
  let fieldMappingDatasetTypeDropdownOptions = [];
  let fieldMappingDatasetTypeDropdownCommit = null;
  let fieldMappingDatasetTypeDropdownWired = false;
  let fieldMappingDatasetTypeDropdownShowAll = false;
  let fieldMappingDatasetTypeDropdownGrid = null;

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setFieldMappingStatus(msg, isError = false) {
    if (!fieldMappingStatus) return;
    fieldMappingStatus.textContent = msg || "";
    fieldMappingStatus.classList.toggle("error", !!isError);
  }

  function renderFieldMappingEmpty(message) {
    if (!fieldMappingBody) return;
    closeFieldMappingDatasetTypeDropdown();
    clearTableSkeletonRows(fieldMappingBody);
    fieldMappingBody.innerHTML = `
      <tr>
        <td colspan="4" class="field-mapping-empty">${escapeHtml(message || "No fields available.")}</td>
      </tr>
    `;
  }

  function getProjectFieldMappingState(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!fieldMappingByProject.has(key)) {
      fieldMappingByProject.set(key, new Map());
    }
    return fieldMappingByProject.get(key);
  }

  function normalizeFieldMappingRow(row = {}) {
    const significance = getSignificanceOptionMatchName(row.significance) || "Not Used";
    return {
      significance,
      datasetType: significance === "Dataset" ? String(row.datasetType || "").trim() : "",
      level: significance === "Reserving Class" ? sanitizeLevel(row.level) : null,
    };
  }

  function fieldMappingRowsMatch(left, right) {
    return (
      left.significance === right.significance
      && left.datasetType === right.datasetType
      && left.level === right.level
    );
  }

  /** Saved mapped columns the shown source does not have: [{ fieldName, significance, datasetType, level }]. */
  function getMissingMappedFields(projectName) {
    const key = normalizeProjectKey(projectName);
    const saved = savedFieldMappingByProject.get(key) || new Map();
    const shown = new Set(currentFieldNames);
    const missing = [];
    for (const [fieldName, row] of saved.entries()) {
      if (shown.has(fieldName) || row.significance === "Not Used") continue;
      missing.push({ fieldName, ...row });
    }
    return missing;
  }

  /** A shown column that differs from its saved row, or a saved mapped column the source lost. */
  function hasUnsavedFieldMappingChanges(projectName) {
    const key = normalizeProjectKey(projectName);
    if (!key || !currentFieldNames.length) return false;
    const current = getProjectFieldMappingState(projectName);
    const saved = savedFieldMappingByProject.get(key) || new Map();
    return getMissingMappedFields(projectName).length > 0 || currentFieldNames.some((fieldName) => !fieldMappingRowsMatch(
      normalizeFieldMappingRow(current.get(fieldName)),
      normalizeFieldMappingRow(saved.get(fieldName)),
    ));
  }

  function describeMappedRole(row) {
    if (row.significance === "Dataset") return row.datasetType || "Dataset";
    if (row.significance === "Reserving Class") return `Reserving Class, Level ${row.level}`;
    return row.significance;
  }

  /** Name the mapped columns the source lost; the next save unmaps them. */
  function renderMissingMappedFields(projectName) {
    if (!fieldMappingMissing) return;
    const missing = getMissingMappedFields(projectName);
    fieldMappingMissing.hidden = !missing.length;
    fieldMappingMissing.textContent = missing.length
      ? `Not in this source, so saving unmaps them: ${missing
        .map((row) => `${row.fieldName} (${describeMappedRole(row)})`)
        .join(", ")}.`
      : "";
  }

  function captureSavedFieldMapping(projectName, rows) {
    const key = normalizeProjectKey(projectName);
    if (!key) return;
    const saved = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      const fieldName = String(row?.field_name || "").trim();
      if (!fieldName) continue;
      saved.set(fieldName, normalizeFieldMappingRow({
        significance: row.significance,
        datasetType: row.dataset_type,
        level: row.level,
      }));
    }
    savedFieldMappingByProject.set(key, saved);
  }

  function sanitizeLevel(levelValue) {
    const n = Number(levelValue);
    if (!Number.isInteger(n) || n < 1) return null;
    return n;
  }

  function upsertFieldMappingRow(projectName, fieldName, significance, levelValue, datasetTypeValue = "") {
    const state = getProjectFieldMappingState(projectName);
    const sig = String(significance || "").trim();
    const level = sig === "Reserving Class" ? sanitizeLevel(levelValue) : null;
    const datasetType = sig === "Dataset" ? String(datasetTypeValue || "").trim() : "";
    state.set(fieldName, {
      significance: sig,
      datasetType,
      level,
    });
  }

  function getNextReservingClassLevel(projectName, excludeFieldName = "") {
    const state = getProjectFieldMappingState(projectName);
    const exclude = String(excludeFieldName || "").trim();
    let maxLevel = 0;
    for (const [fieldName, row] of state.entries()) {
      if (fieldName === exclude) continue;
      const significance = String(row?.significance || "").trim();
      if (significance !== "Reserving Class") continue;
      const level = sanitizeLevel(row?.level);
      if (level != null && level > maxLevel) maxLevel = level;
    }
    return maxLevel + 1;
  }

  function canonDatasetType(value) {
    return String(value ?? "").trim().replace(/\s+/g, " ").toLowerCase();
  }

  function buildDatasetTypeOptionIndex(datasetTypeOptions) {
    const byCanon = new Map();
    for (const raw of Array.isArray(datasetTypeOptions) ? datasetTypeOptions : []) {
      const name = String(raw || "").trim();
      const key = canonDatasetType(name);
      if (!name || !key || byCanon.has(key)) continue;
      byCanon.set(key, name);
    }
    return byCanon;
  }

  function getDatasetTypeOptionMatchName(rawValue, datasetTypeOptionIndex) {
    const key = canonDatasetType(rawValue);
    if (!key) return "";
    return String(datasetTypeOptionIndex?.get(key) || "");
  }

  function getSignificanceOptionMatchName(rawValue) {
    const key = canonDatasetType(rawValue);
    if (!key) return "";
    for (const value of FIELD_SIGNIFICANCE_OPTIONS) {
      if (canonDatasetType(value) === key) return value;
    }
    return "";
  }

  function filterDatasetTypeOptions(datasetTypeOptions, queryText, showAll = false) {
    const options = Array.isArray(datasetTypeOptions) ? datasetTypeOptions : [];
    if (showAll) return options.slice();
    const tokens = String(queryText || "")
      .toLowerCase()
      .split(/\s+/)
      .map((v) => String(v || "").trim())
      .filter(Boolean);
    if (tokens.length === 0) return options.slice();
    return options.filter((name) => {
      const text = String(name || "").toLowerCase();
      return tokens.every((token) => text.includes(token));
    });
  }

  function closeFieldMappingDatasetTypeDropdown() {
    if (!fieldMappingDatasetTypeDropdown) return;
    fieldMappingDatasetTypeDropdown.classList.remove("open");
    fieldMappingDatasetTypeDropdown.style.display = "none";
    fieldMappingDatasetTypeDropdownInput = null;
    fieldMappingDatasetTypeDropdownOptions = [];
    fieldMappingDatasetTypeDropdownCommit = null;
    fieldMappingDatasetTypeDropdownShowAll = false;
    fieldMappingDatasetTypeDropdownGrid = null;
  }

  function positionFieldMappingDatasetTypeDropdown() {
    if (!fieldMappingDatasetTypeDropdown || fieldMappingDatasetTypeDropdown.style.display === "none") return;
    const input = fieldMappingDatasetTypeDropdownInput;
    if (!input || !document.body.contains(input) || input.disabled) {
      closeFieldMappingDatasetTypeDropdown();
      return;
    }

    const rect = input.getBoundingClientRect();
    const gridRect = (
      fieldMappingDatasetTypeDropdownGrid
      && document.body.contains(fieldMappingDatasetTypeDropdownGrid)
      && fieldMappingDatasetTypeDropdownGrid.getBoundingClientRect
    )
      ? fieldMappingDatasetTypeDropdownGrid.getBoundingClientRect()
      : null;
    const bounds = gridRect && gridRect.width > 0 && gridRect.height > 0
      ? {
          left: gridRect.left + 2,
          top: gridRect.top + 2,
          right: gridRect.right - 2,
          bottom: gridRect.bottom - 2,
        }
      : {
          left: 8,
          top: 8,
          right: window.innerWidth - 8,
          bottom: window.innerHeight - 8,
        };
    const pop = fieldMappingDatasetTypeDropdown;
    const maxWidth = Math.max(60, Math.round(bounds.right - bounds.left));
    const minWidth = Math.min(maxWidth, Math.max(220, Math.round(rect.width)));
    const anchorTop = Math.round(rect.bottom + 4);
    const gridSpaceBelow = Math.round(bounds.bottom - anchorTop);
    const viewportSpaceBelow = Math.round(window.innerHeight - anchorTop - 8);
    const maxHeight = Math.max(24, gridSpaceBelow > 24 ? gridSpaceBelow : viewportSpaceBelow);
    pop.style.minWidth = `${minWidth}px`;
    pop.style.maxWidth = `${maxWidth}px`;
    pop.style.maxHeight = `${maxHeight}px`;
    if (fieldMappingDatasetTypeDropdownList) {
      fieldMappingDatasetTypeDropdownList.style.maxHeight = `${Math.max(20, maxHeight - 8)}px`;
    }
    pop.style.left = `${Math.round(rect.left)}px`;
    pop.style.top = `${anchorTop}px`;

    const popRect = pop.getBoundingClientRect();
    let left = popRect.left;
    const top = anchorTop;
    if (popRect.right > bounds.right) left = bounds.right - popRect.width;
    if (left < bounds.left) left = bounds.left;
    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  }

  function renderFieldMappingDatasetTypeDropdown() {
    if (!fieldMappingDatasetTypeDropdownList || !fieldMappingDatasetTypeDropdownInput) return;
    const filtered = filterDatasetTypeOptions(
      fieldMappingDatasetTypeDropdownOptions,
      fieldMappingDatasetTypeDropdownInput.value,
      fieldMappingDatasetTypeDropdownShowAll,
    );
    const currentKey = canonDatasetType(fieldMappingDatasetTypeDropdownInput.value);
    fieldMappingDatasetTypeDropdownList.innerHTML = "";

    if (filtered.length === 0) {
      const empty = document.createElement("div");
      empty.className = "fm-dataset-type-empty";
      empty.textContent = "No matches";
      fieldMappingDatasetTypeDropdownList.appendChild(empty);
      return;
    }

    for (const optionName of filtered) {
      const name = String(optionName || "").trim();
      if (!name) continue;
      const row = document.createElement("button");
      row.type = "button";
      row.className = "fm-dataset-type-option";
      if (currentKey && canonDatasetType(name) === currentKey) row.classList.add("active");
      row.textContent = name;
      row.addEventListener("mousedown", (e) => {
        // Prevent input blur before click handler runs.
        e.preventDefault();
      });
      row.addEventListener("click", (e) => {
        e.preventDefault();
        if (!fieldMappingDatasetTypeDropdownInput) return;
        fieldMappingDatasetTypeDropdownInput.value = name;
        if (typeof fieldMappingDatasetTypeDropdownCommit === "function") {
          fieldMappingDatasetTypeDropdownCommit({ source: "dropdown" });
        }
        closeFieldMappingDatasetTypeDropdown();
      });
      fieldMappingDatasetTypeDropdownList.appendChild(row);
    }
  }

  function ensureFieldMappingDatasetTypeDropdown() {
    if (fieldMappingDatasetTypeDropdown) return fieldMappingDatasetTypeDropdown;
    const pop = document.createElement("div");
    pop.className = "fm-dataset-type-dropdown";
    pop.style.display = "none";

    const list = document.createElement("div");
    list.className = "fm-dataset-type-dropdown-list";
    pop.appendChild(list);

    document.body.appendChild(pop);
    fieldMappingDatasetTypeDropdown = pop;
    fieldMappingDatasetTypeDropdownList = list;
    return pop;
  }

  function ensureFieldMappingDatasetTypeDropdownWired() {
    if (fieldMappingDatasetTypeDropdownWired) return;
    fieldMappingDatasetTypeDropdownWired = true;
    document.addEventListener("mousedown", (e) => {
      if (!fieldMappingDatasetTypeDropdown || fieldMappingDatasetTypeDropdown.style.display === "none") return;
      const target = e.target;
      if (fieldMappingDatasetTypeDropdown.contains(target)) return;
      if (fieldMappingDatasetTypeDropdownInput && target === fieldMappingDatasetTypeDropdownInput) return;
      if (fieldMappingDatasetTypeDropdownInput) {
        const wrap = fieldMappingDatasetTypeDropdownInput.closest(".fm-inline-dropdown-wrap");
        if (wrap && wrap.contains(target)) return;
      }
      closeFieldMappingDatasetTypeDropdown();
    }, true);
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      closeFieldMappingDatasetTypeDropdown();
    }, true);
    window.addEventListener("resize", () => {
      positionFieldMappingDatasetTypeDropdown();
    });
    window.addEventListener("scroll", () => {
      positionFieldMappingDatasetTypeDropdown();
    }, true);
  }

  function openFieldMappingDatasetTypeDropdown(inputEl, datasetTypeOptions, commitCallback = null, options = {}) {
    if (!inputEl || inputEl.disabled) {
      closeFieldMappingDatasetTypeDropdown();
      return;
    }
    ensureFieldMappingDatasetTypeDropdownWired();
    const pop = ensureFieldMappingDatasetTypeDropdown();
    fieldMappingDatasetTypeDropdownInput = inputEl;
    fieldMappingDatasetTypeDropdownOptions = Array.isArray(datasetTypeOptions) ? datasetTypeOptions.slice() : [];
    fieldMappingDatasetTypeDropdownCommit = commitCallback;
    fieldMappingDatasetTypeDropdownShowAll = !!options.showAll;
    fieldMappingDatasetTypeDropdownGrid = options.gridEl || inputEl?.closest?.(".field-mapping-grid") || null;
    renderFieldMappingDatasetTypeDropdown();
    pop.style.display = "block";
    pop.classList.add("open");
    positionFieldMappingDatasetTypeDropdown();
  }

  function findDatasetTypeOwner(projectName, datasetType, excludeFieldName = "") {
    const key = canonDatasetType(datasetType);
    if (!key) return "";
    const exclude = String(excludeFieldName || "").trim();
    const state = getProjectFieldMappingState(projectName);
    for (const [fieldName, row] of state.entries()) {
      const significance = String(row?.significance || "").trim();
      if (significance !== "Dataset") continue;
      const selected = String(row?.datasetType || "").trim();
      if (!selected) continue;
      if (canonDatasetType(selected) === key && fieldName !== exclude) {
        return fieldName;
      }
    }
    return "";
  }

  function getMappedDatasetTypeNames(projectName) {
    const state = getProjectFieldMappingState(projectName);
    const out = [];
    const seen = new Set();
    for (const row of state.values()) {
      const significance = String(row?.significance || "").trim();
      if (significance !== "Dataset") continue;
      const name = String(row?.datasetType || "").trim();
      if (!name) continue;
      const key = canonDatasetType(name);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(name);
    }
    return out;
  }

  async function ensureFieldMappingLoaded(projectName, options = {}) {
    const force = !!options?.force;
    const key = normalizeProjectKey(projectName);
    if (!key) return;
    if (!force && loadedFieldMappingByProject.has(key)) return;

    const state = getProjectFieldMappingState(projectName);
    if (force) {
      loadedFieldMappingByProject.delete(key);
      state.clear();
    }
    try {
      const res = await fetchImpl(`/field_mapping?project_name=${encodeURIComponent(projectName)}`);
      if (!res.ok) {
        loadedFieldMappingByProject.add(key);
        return;
      }
      const out = await res.json();
      const rows = Array.isArray(out?.data?.rows) ? out.data.rows : [];
      for (const row of rows) {
        const fieldName = String(row?.field_name || "").trim();
        if (!fieldName) continue;
        const significance = String(row?.significance || "").trim();
        const datasetType = String(row?.dataset_type || "").trim();
        const level = sanitizeLevel(row?.level);
        state.set(fieldName, { significance, datasetType, level });
      }
      captureSavedFieldMapping(projectName, rows);
    } catch {
      // ignore load errors; user can still edit/save
    }
    loadedFieldMappingByProject.add(key);
  }

  /**
   * Show the columns the chosen source will import. Rows for columns it no
   * longer has leave the editable state, so their dataset types are free to
   * map onto the new columns; a column that comes back picks up its saved row.
   */
  function renderFieldMappingTable(fieldNames, projectName) {
    if (!fieldMappingBody) return;
    closeFieldMappingDatasetTypeDropdown();
    setFieldMappingStatus("");
    currentFieldNames = Array.isArray(fieldNames) ? fieldNames.map(String) : [];
    const state = getProjectFieldMappingState(projectName);
    const saved = savedFieldMappingByProject.get(normalizeProjectKey(projectName)) || new Map();
    for (const fieldName of [...state.keys()]) {
      if (!currentFieldNames.includes(fieldName)) state.delete(fieldName);
    }
    for (const fieldName of currentFieldNames) {
      if (!state.has(fieldName) && saved.has(fieldName)) state.set(fieldName, { ...saved.get(fieldName) });
    }
    renderMissingMappedFields(projectName);
    if (!currentFieldNames.length) {
      renderFieldMappingEmpty("The source has no columns.");
      return;
    }

    const datasetTypeOptions = getDatasetTypeNamesForProject(projectName, { formulaEmptyOnly: true });
    const datasetTypeOptionIndex = buildDatasetTypeOptionIndex(datasetTypeOptions);
    clearTableSkeletonRows(fieldMappingBody);
    fieldMappingBody.innerHTML = "";

    for (const fieldName of fieldNames) {
      const saved = state.get(fieldName) || { significance: "", datasetType: "", level: null };
      const row = document.createElement("tr");

      const nameTd = document.createElement("td");
      nameTd.textContent = fieldName;

      const sigTd = document.createElement("td");
      const sigWrap = document.createElement("div");
      sigWrap.className = "fm-inline-dropdown-wrap";
      const sigInput = document.createElement("input");
      sigInput.type = "text";
      sigInput.setAttribute("data-role", "significance");
      sigInput.autocomplete = "off";
      sigInput.spellcheck = false;
      sigInput.readOnly = true;
      sigInput.value = FIELD_SIGNIFICANCE_OPTIONS.includes(saved.significance) ? saved.significance : "Not Used";
      const sigArrow = document.createElement("button");
      sigArrow.type = "button";
      sigArrow.className = "fm-inline-dropdown-arrow";
      sigArrow.title = "Show Significance options";
      sigArrow.setAttribute("aria-label", "Show Significance options");
      sigArrow.innerHTML = `
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4 6l4 4l4-4z"></path>
        </svg>
      `;
      sigWrap.appendChild(sigInput);
      sigWrap.appendChild(sigArrow);
      sigTd.appendChild(sigWrap);

      const datasetTypeTd = document.createElement("td");
      const datasetTypeWrap = document.createElement("div");
      datasetTypeWrap.className = "fm-inline-dropdown-wrap";
      const datasetTypeInput = document.createElement("input");
      datasetTypeInput.type = "text";
      datasetTypeInput.setAttribute("data-role", "dataset-type");
      datasetTypeInput.autocomplete = "off";
      datasetTypeInput.spellcheck = false;
      datasetTypeInput.placeholder = DATASET_TYPE_PROMPT;
      const savedMatched = getDatasetTypeOptionMatchName(saved.datasetType, datasetTypeOptionIndex);
      datasetTypeInput.value = savedMatched || String(saved.datasetType || "").trim();
      datasetTypeInput.disabled = getSignificanceOptionMatchName(sigInput.value) !== "Dataset";
      const datasetTypeArrow = document.createElement("button");
      datasetTypeArrow.type = "button";
      datasetTypeArrow.className = "fm-inline-dropdown-arrow";
      datasetTypeArrow.title = "Show all Dataset Types";
      datasetTypeArrow.setAttribute("aria-label", "Show all Dataset Types");
      datasetTypeArrow.innerHTML = `
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4 6l4 4l4-4z"></path>
        </svg>
      `;
      datasetTypeWrap.appendChild(datasetTypeInput);
      datasetTypeWrap.appendChild(datasetTypeArrow);
      datasetTypeTd.appendChild(datasetTypeWrap);

      const levelTd = document.createElement("td");
      const levelStepper = document.createElement("div");
      levelStepper.className = "decimalPlacesWrap field-mapping-level-stepper";
      const levelInput = document.createElement("input");
      levelInput.type = "number";
      levelInput.min = "1";
      levelInput.step = "1";
      levelInput.inputMode = "numeric";
      levelInput.setAttribute("aria-label", `Level for ${fieldName}`);
      levelInput.value = saved.level != null ? String(saved.level) : "";
      levelInput.disabled = getSignificanceOptionMatchName(sigInput.value) !== "Reserving Class";
      const levelStepperControls = document.createElement("div");
      levelStepperControls.className = "decimalPlacesStepper";
      const levelUpButton = document.createElement("button");
      levelUpButton.type = "button";
      levelUpButton.className = "decimalPlacesStepBtn";
      levelUpButton.setAttribute("aria-label", `Increase Level for ${fieldName}`);
      levelUpButton.innerHTML = '<span class="datasetStepperCaret datasetStepperCaretUp" aria-hidden="true"></span>';
      const levelDownButton = document.createElement("button");
      levelDownButton.type = "button";
      levelDownButton.className = "decimalPlacesStepBtn";
      levelDownButton.setAttribute("aria-label", `Decrease Level for ${fieldName}`);
      levelDownButton.innerHTML = '<span class="datasetStepperCaret" aria-hidden="true"></span>';
      levelStepperControls.append(levelUpButton, levelDownButton);
      levelStepper.append(levelInput, levelStepperControls);
      levelTd.appendChild(levelStepper);

      const getCurrentSignificance = () => {
        const matched = getSignificanceOptionMatchName(sigInput.value);
        return matched || "Not Used";
      };
      let lastSignificanceValue = getCurrentSignificance();

      const persistRowState = () => {
        const significanceValue = getCurrentSignificance();
        const becameReservingClass = lastSignificanceValue !== "Reserving Class" && significanceValue === "Reserving Class";
        if (sigInput.value !== significanceValue) sigInput.value = significanceValue;
        if (significanceValue !== "Reserving Class") {
          levelInput.value = "";
          levelInput.disabled = true;
          levelUpButton.disabled = true;
          levelDownButton.disabled = true;
        } else {
          levelInput.disabled = false;
          levelUpButton.disabled = false;
          levelDownButton.disabled = false;
          if (becameReservingClass) {
            levelInput.value = String(getNextReservingClassLevel(projectName, fieldName));
          }
        }
        if (significanceValue !== "Dataset") {
          datasetTypeInput.placeholder = DATASET_TYPE_NA;
          datasetTypeInput.value = "";
          datasetTypeInput.disabled = true;
          datasetTypeArrow.disabled = true;
        } else {
          datasetTypeInput.placeholder = DATASET_TYPE_PROMPT;
          datasetTypeInput.disabled = false;
          datasetTypeArrow.disabled = false;
          const matched = getDatasetTypeOptionMatchName(datasetTypeInput.value, datasetTypeOptionIndex);
          if (matched && datasetTypeInput.value !== matched) datasetTypeInput.value = matched;
        }
        lastSignificanceValue = significanceValue;
        upsertFieldMappingRow(projectName, fieldName, significanceValue, levelInput.value, datasetTypeInput.value);
      };

      const commitSignificanceInput = () => {
        const matched = getSignificanceOptionMatchName(sigInput.value);
        sigInput.value = matched || "Not Used";
        persistRowState();
      };
      const openSignificanceDropdown = () => {
        openFieldMappingDatasetTypeDropdown(sigInput, FIELD_SIGNIFICANCE_OPTIONS, commitSignificanceInput, {
          showAll: true,
          gridEl: sigTd.closest(".field-mapping-grid"),
        });
      };
      sigArrow.addEventListener("mousedown", (e) => {
        e.preventDefault();
      });
      sigArrow.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        sigInput.focus();
        openSignificanceDropdown();
      });
      sigInput.addEventListener("focus", () => {
        openSignificanceDropdown();
      });
      sigInput.addEventListener("click", () => {
        openSignificanceDropdown();
      });
      sigInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          closeFieldMappingDatasetTypeDropdown();
          return;
        }
        if (e.key === "Enter" || e.key === "ArrowDown") {
          e.preventDefault();
          openSignificanceDropdown();
        }
      });
      sigInput.addEventListener("blur", () => {
        commitSignificanceInput();
      });

      const handleSignificanceChange = () => {
        persistRowState();
        if (getCurrentSignificance() !== "Dataset" && fieldMappingDatasetTypeDropdownInput === datasetTypeInput) {
          closeFieldMappingDatasetTypeDropdown();
        }
      };
      const commitDatasetTypeInput = () => {
        if (getCurrentSignificance() === "Dataset") {
          const typed = String(datasetTypeInput.value || "").trim();
          const matched = getDatasetTypeOptionMatchName(typed, datasetTypeOptionIndex);
          if (matched) {
            if (datasetTypeInput.value !== matched) datasetTypeInput.value = matched;
            const owner = findDatasetTypeOwner(projectName, matched, fieldName);
            if (owner) {
              datasetTypeInput.value = "";
              setFieldMappingStatus(`Dataset Type '${matched}' is already used by '${owner}'.`, true);
            } else {
              setFieldMappingStatus("");
            }
          } else if (!typed) {
            setFieldMappingStatus("");
          }
        }
        persistRowState();
      };
      const openDatasetTypeDropdown = () => {
        if (getCurrentSignificance() !== "Dataset" || datasetTypeInput.disabled) {
          if (fieldMappingDatasetTypeDropdownInput === datasetTypeInput) closeFieldMappingDatasetTypeDropdown();
          return;
        }
        openFieldMappingDatasetTypeDropdown(datasetTypeInput, datasetTypeOptions, commitDatasetTypeInput, {
          showAll: false,
          gridEl: datasetTypeTd.closest(".field-mapping-grid"),
        });
      };
      datasetTypeArrow.addEventListener("mousedown", (e) => {
        e.preventDefault();
      });
      datasetTypeArrow.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (getCurrentSignificance() !== "Dataset" || datasetTypeInput.disabled) return;
        datasetTypeInput.focus();
        openFieldMappingDatasetTypeDropdown(datasetTypeInput, datasetTypeOptions, commitDatasetTypeInput, {
          showAll: true,
          gridEl: datasetTypeTd.closest(".field-mapping-grid"),
        });
      });
      datasetTypeInput.addEventListener("focus", () => {
        openDatasetTypeDropdown();
      });
      datasetTypeInput.addEventListener("click", () => {
        openDatasetTypeDropdown();
      });
      datasetTypeInput.addEventListener("input", () => {
        persistRowState();
        if (fieldMappingDatasetTypeDropdownInput === datasetTypeInput) {
          fieldMappingDatasetTypeDropdownShowAll = false;
        }
        openDatasetTypeDropdown();
      });
      datasetTypeInput.addEventListener("change", () => {
        commitDatasetTypeInput();
        openDatasetTypeDropdown();
      });
      datasetTypeInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
          closeFieldMappingDatasetTypeDropdown();
          return;
        }
        if (e.key === "Enter") {
          e.preventDefault();
          commitDatasetTypeInput();
          closeFieldMappingDatasetTypeDropdown();
        }
      });
      datasetTypeInput.addEventListener("blur", () => {
        commitDatasetTypeInput();
        setTimeout(() => {
          if (fieldMappingDatasetTypeDropdownInput !== datasetTypeInput) return;
          const active = document.activeElement;
          if (fieldMappingDatasetTypeDropdown?.contains(active)) return;
          closeFieldMappingDatasetTypeDropdown();
        }, 0);
      });
      const adjustLevel = (delta) => {
        if (levelInput.disabled) return;
        const current = sanitizeLevel(levelInput.value) ?? 1;
        levelInput.value = String(Math.max(1, current + delta));
        persistRowState();
      };
      levelUpButton.addEventListener("click", () => adjustLevel(1));
      levelDownButton.addEventListener("click", () => adjustLevel(-1));
      levelInput.addEventListener("wheel", (e) => e.preventDefault(), { passive: false });
      levelInput.addEventListener("input", persistRowState);
      levelInput.addEventListener("change", persistRowState);
      handleSignificanceChange();

      row.appendChild(nameTd);
      row.appendChild(sigTd);
      row.appendChild(datasetTypeTd);
      row.appendChild(levelTd);
      fieldMappingBody.appendChild(row);

      persistRowState();
    }
    initTableColumnResizing("fieldMappingTable", [90, 100, 120, 70]);
  }

  function collectFieldMappingRows(projectName, fieldNames) {
    const state = getProjectFieldMappingState(projectName);
    const datasetTypeOptions = getDatasetTypeNamesForProject(projectName, { formulaEmptyOnly: true });
    const datasetTypeOptionIndex = buildDatasetTypeOptionIndex(datasetTypeOptions);
    const usedDatasetTypes = new Map();
    const rows = [];
    const invalidLevel = [];
    const invalidDatasetType = [];
    const duplicateDatasetType = [];

    for (const fieldName of fieldNames) {
      const row = state.get(fieldName) || {};
      const significance = String(row.significance || "").trim();
      if (!FIELD_SIGNIFICANCE_OPTIONS.includes(significance) || significance === "Not Used") {
        continue;
      }

      let level = null;
      let datasetType = null;
      if (significance === "Reserving Class") {
        level = sanitizeLevel(row.level);
        if (level == null) {
          invalidLevel.push(fieldName);
          continue;
        }
      } else if (significance === "Dataset") {
        const selectedRaw = String(row.datasetType || "").trim();
        const selectedMatched = getDatasetTypeOptionMatchName(selectedRaw, datasetTypeOptionIndex);
        const selected = selectedMatched || (datasetTypeOptionIndex.size === 0 ? selectedRaw : "");
        if (!selected) {
          invalidDatasetType.push(fieldName);
          continue;
        }
        const key = canonDatasetType(selected);
        const existingField = usedDatasetTypes.get(key);
        if (existingField && existingField !== fieldName) {
          duplicateDatasetType.push(`${selected} (${existingField}, ${fieldName})`);
          continue;
        }
        usedDatasetTypes.set(key, fieldName);
        datasetType = selected;
      }

      rows.push({
        field_name: fieldName,
        significance,
        dataset_type: datasetType,
        level,
      });
    }

    if (invalidLevel.length > 0) {
      throw new Error(`Level must be an integer >= 1 for Reserving Class fields. Invalid: ${invalidLevel.slice(0, 5).join(", ")}${invalidLevel.length > 5 ? "..." : ""}`);
    }
    if (invalidDatasetType.length > 0) {
      throw new Error(`Dataset Type is required for Dataset significance. Invalid: ${invalidDatasetType.slice(0, 5).join(", ")}${invalidDatasetType.length > 5 ? "..." : ""}`);
    }
    if (duplicateDatasetType.length > 0) {
      throw new Error(`Dataset Type cannot be used twice. Duplicates: ${duplicateDatasetType.slice(0, 5).join("; ")}${duplicateDatasetType.length > 5 ? "..." : ""}`);
    }

    return rows;
  }

  /** The first problem that would stop a save, or "" when the mapping can be saved. */
  function validateFieldMapping(projectName) {
    try {
      collectFieldMappingRows(projectName, currentFieldNames);
      return "";
    } catch (err) {
      return err.message || "The field mapping is not valid.";
    }
  }

  /**
   * Save the mapping for the shown columns when it changed: `{ ok, saved, error }`.
   *
   * The Import Settings window calls this after saving the source and before
   * importing, so the import reads the new mapping.
   */
  async function saveFieldMapping(project) {
    if (!project || !project.name) return { ok: false, saved: false, error: "Select a project first." };
    if (!hasUnsavedFieldMappingChanges(project.name)) return { ok: true, saved: false, error: "" };
    try {
      const rows = collectFieldMappingRows(project.name, currentFieldNames);
      const res = await fetchImpl("/field_mapping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // table_path is omitted on purpose: the stored CSV selection is owned
        // by the import-profile save and is preserved by the app server.
        body: JSON.stringify({
          project_name: project.name,
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
      await res.json();
      captureSavedFieldMapping(project.name, rows);
      renderMissingMappedFields(project.name);

      let syncError = "";
      try {
        const syncOut = await syncDatasetTypesSources(project.name);
        if (syncOut && syncOut.ok === false) syncError = String(syncOut.message || "").trim() || "Dataset Type sources were not synced.";
      } catch (syncErr) {
        syncError = String(syncErr?.message || syncErr || "").trim() || "Dataset Type sources were not synced.";
      }
      setStatus(syncError
        ? `Saved field mapping, but dataset type source sync failed: ${project.name}`
        : `Saved field mapping and synced dataset type sources: ${project.name}`);
      await loadAuditLog(project.name, true);
      return { ok: !syncError, saved: true, error: syncError };
    } catch (err) {
      setStatus(`Field mapping save error: ${err.message}`);
      return { ok: false, saved: false, error: err.message || "The field mapping was not saved." };
    }
  }

  return {
    setFieldMappingStatus,
    ensureFieldMappingLoaded,
    findDatasetTypeOwner,
    getMappedDatasetTypeNames,
    renderFieldMappingTable,
    validateFieldMapping,
    saveFieldMapping,
    hasUnsavedFieldMappingChanges,
  };
}
