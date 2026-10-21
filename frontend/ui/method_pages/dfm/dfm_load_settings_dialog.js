/*
===============================================================================
DFM Load Settings From Another Method - the Details-tab button, its picker
(a reserving-class tree beside that class's DFMs) and the copy itself.

The copy is one undoable edit that leaves the window unsaved: the source's
settings are laid over the open method (see dfm_settings_copy.js for what is
copied and what is kept), the preview recalculates, and nothing is written
until the user saves. When the lengths differ, the input triangle is first
reloaded at the source's lengths so the copied rows land on that geometry.
===============================================================================
*/
import {
  applyDfmDirtyCheckResult,
  getResolvedProjectName,
  getResolvedReservingClass,
  markDfmDirty,
  runDfmProgrammaticSync,
} from "/ui/method_pages/dfm/dfm_state.js";
import {
  applyDfmOwnedPatchPayload,
  buildDfmMethodPayload,
  cancelDfmMethodAsyncTasks,
} from "/ui/method_pages/dfm/dfm_persistence.js?v=20261020a";
import { loadDfmMethod } from "/ui/method_pages/dfm/dfm_method_api.js?v=20260910a";
import { ensureResultsRatioBasisAligned } from "/ui/method_pages/dfm/dfm_results_tab.js?v=20260914c";
import {
  recordMethodHistoryStep,
  setMethodHistoryHandlers,
} from "/ui/method_pages/dfm/dfm_ratio_history.js";
import {
  dfmSettingsLengthChange,
  listDfmCopySources,
  projectDfmSettingsCopy,
} from "/ui/method_pages/dfm/dfm_settings_copy.js?v=20260923b";
import { openReservingClassPicker } from "/ui/shared/components/pickers/reserving_class_picker.js?v=20260925a";
import { closeFloatingPathTreePicker } from "/ui/shared/components/pickers/path_tree_picker.js?v=20260925a";

const STYLE_ID = "dfmLoadSettingsDialogStyles";
const DIALOG_TITLE = "Load Settings From Another Method";
let dialogOpen = false;
let copyInFlight = false;

function toText(value) {
  return String(value ?? "").trim();
}

function postStatus(text, tone = "") {
  try {
    window.parent.postMessage({ type: "arcrho:status", text: String(text || ""), ...(tone ? { tone } : {}) }, "*");
  } catch {
    // ignore stale shell messaging
  }
}

function ensureStyles(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const link = doc.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = "/ui/method_pages/dfm/dfm_load_settings_dialog.css?v=20260923a";
  doc.head.appendChild(link);
}

async function fetchClassDfms(projectName, reservingClass, options = {}) {
  const query = new URLSearchParams({ project_name: projectName, reserving_class: reservingClass });
  const response = await fetch(`/dfm/method-index?${query.toString()}`, { signal: options.signal });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload?.ok === false) {
    throw new Error(toText(payload?.detail || payload?.error) || `HTTP ${response.status}`);
  }
  return payload;
}

/**
 * Opens the picker. Resolves with `{ reservingClass, methodName,
 * outputDataset }` for the chosen DFM, or null when the user cancels.
 */
export function openDfmLoadSettingsDialog({
  projectName,
  currentClass = "",
  currentMethodName = "",
  documentRef = document,
} = {}) {
  const doc = documentRef;
  ensureStyles(doc);
  const overlay = doc.createElement("div");
  overlay.className = "dfmLoadSettingsOverlay";
  overlay.innerHTML = `
    <div class="dfmLoadSettingsDialog" role="dialog" aria-modal="true" aria-labelledby="dfmLoadSettingsTitle">
      <div class="dfmLoadSettingsHeader">
        <div class="dfmLoadSettingsTitle" id="dfmLoadSettingsTitle"></div>
        <button class="dfmLoadSettingsClose" type="button" aria-label="Close">
          <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M4 4l8 8M12 4l-8 8"></path></svg>
        </button>
      </div>
      <div class="dfmLoadSettingsBody">
        <div class="dfmLoadSettingsPane">
          <div class="dfmLoadSettingsPaneLabel">Reserving Class</div>
          <div class="dfmLoadSettingsTree"></div>
        </div>
        <div class="dfmLoadSettingsPane">
          <div class="dfmLoadSettingsPaneLabel dfmLoadSettingsListHeader">
            <span>DFM Method</span><span>Status</span>
          </div>
          <div class="dfmLoadSettingsList" role="listbox" aria-label="DFM methods"></div>
        </div>
      </div>
      <div class="dfmLoadSettingsFooter">
        <div class="dfmLoadSettingsHint" aria-live="polite"></div>
        <button class="dfmLoadSettingsButton dfmLoadSettingsPrimary" type="button" disabled>Load</button>
        <button class="dfmLoadSettingsButton" type="button" data-role="cancel">Cancel</button>
      </div>
    </div>
  `;
  overlay.querySelector(".dfmLoadSettingsTitle").textContent = DIALOG_TITLE;
  doc.body.appendChild(overlay);

  const treeHost = overlay.querySelector(".dfmLoadSettingsTree");
  const listEl = overlay.querySelector(".dfmLoadSettingsList");
  const hintEl = overlay.querySelector(".dfmLoadSettingsHint");
  const loadButton = overlay.querySelector(".dfmLoadSettingsPrimary");
  const cancelButton = overlay.querySelector('[data-role="cancel"]');
  const closeButton = overlay.querySelector(".dfmLoadSettingsClose");
  const returnFocus = doc.activeElement;

  let selectedClass = "";
  let selectedRow = null;
  let listRequest = 0;
  let listAbort = null;

  const setHint = (text) => { hintEl.textContent = String(text || ""); };

  function renderMessage(text) {
    listEl.innerHTML = "";
    const empty = doc.createElement("div");
    empty.className = "dfmLoadSettingsEmpty";
    empty.textContent = text;
    listEl.appendChild(empty);
  }

  function selectRow(row, element) {
    selectedRow = row;
    listEl.querySelectorAll(".dfmLoadSettingsRow").forEach((item) => {
      const active = item === element;
      item.classList.toggle("is-selected", active);
      item.setAttribute("aria-selected", active ? "true" : "false");
    });
    loadButton.disabled = !row;
  }

  return new Promise((resolve) => {
    let open = true;
    function finish(choice) {
      if (!open) return;
      open = false;
      listAbort?.abort?.();
      doc.removeEventListener("keydown", handleKeydown, true);
      closeFloatingPathTreePicker("dialog_closed");
      overlay.remove();
      if (returnFocus?.isConnected && typeof returnFocus.focus === "function") {
        requestAnimationFrame(() => returnFocus.focus({ preventScroll: true }));
      }
      resolve(choice || null);
    }
    function choose() {
      if (!selectedRow || !selectedClass) return;
      finish({
        reservingClass: selectedClass,
        methodName: selectedRow.methodName,
        outputDataset: selectedRow.outputDataset,
      });
    }

    async function showClass(path) {
      const reservingClass = toText(path);
      if (!reservingClass || !open) return;
      selectedClass = reservingClass;
      selectRow(null, null);
      const request = ++listRequest;
      listAbort?.abort?.();
      const controller = new AbortController();
      listAbort = controller;
      renderMessage("Loading...");
      setHint(reservingClass);
      try {
        const payload = await fetchClassDfms(projectName, reservingClass, { signal: controller.signal });
        if (request !== listRequest || !open) return;
        const rows = listDfmCopySources(payload, { reservingClass, currentClass, currentMethodName });
        if (!rows.length) {
          renderMessage("No other DFM in this class.");
          return;
        }
        listEl.innerHTML = "";
        for (const row of rows) {
          const item = doc.createElement("div");
          item.className = "dfmLoadSettingsRow";
          item.setAttribute("role", "option");
          item.setAttribute("aria-selected", "false");
          item.tabIndex = 0;
          const name = doc.createElement("span");
          name.className = "dfmLoadSettingsRowName";
          name.textContent = row.methodName;
          const status = doc.createElement("span");
          status.className = "dfmLoadSettingsRowStatus";
          status.textContent = row.status;
          item.append(name, status);
          item.title = row.outputDataset && row.outputDataset !== row.methodName
            ? `${row.methodName} (${row.outputDataset})`
            : row.methodName;
          item.addEventListener("click", () => selectRow(row, item));
          item.addEventListener("dblclick", () => { selectRow(row, item); choose(); });
          item.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              selectRow(row, item);
              choose();
            }
          });
          listEl.appendChild(item);
        }
      } catch (error) {
        if (error?.name === "AbortError" || request !== listRequest) return;
        renderMessage(`Could not list this class's DFMs: ${toText(error?.message || error)}`);
      }
    }

    function handleKeydown(event) {
      if (event.key === "Escape" && !event.target?.closest?.(".ptree-window input")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        finish(null);
      }
    }

    loadButton.addEventListener("click", choose);
    cancelButton.addEventListener("click", () => finish(null));
    closeButton.addEventListener("click", () => finish(null));
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) finish(null);
    });
    doc.addEventListener("keydown", handleKeydown, true);

    void openReservingClassPicker({
      projectName,
      inlineContainer: treeHost,
      initialPath: currentClass,
      ignoreSavedFilterSpec: true,
      title: "Reserving Class",
      setStatus: (message) => setHint(message),
      onError: (error) => setHint(toText(error?.message) || "Could not load the reserving classes."),
      onSelect: (path) => { void showClass(path); },
    }).then((result) => {
      if (!open) {
        closeFloatingPathTreePicker("dialog_closed");
        return;
      }
      if (!result?.ok && !treeHost.querySelector(".ptree-window")) {
        treeHost.innerHTML = '<div class="dfmLoadSettingsEmpty">No reserving classes found.</div>';
      }
    });
    if (currentClass) void showClass(currentClass);
    requestAnimationFrame(() => cancelButton.focus({ preventScroll: true }));
  });
}

function setLengthSelect(id, value) {
  const select = document.getElementById(id);
  if (!select) return;
  const next = String(value);
  if (![...select.options].some((option) => String(option.value) === next)) {
    const option = document.createElement("option");
    option.value = next;
    option.textContent = next;
    select.appendChild(option);
  }
  select.value = next;
}

async function reloadInputAtLengths(lengths) {
  runDfmProgrammaticSync(() => {
    setLengthSelect("originLenSelect", lengths.originLength);
    setLengthSelect("devLenSelect", lengths.developmentLength);
  });
  // The window differs from its saved copy from here on; marking it now keeps
  // the reload that follows from re-reading the saved method over the copy.
  applyDfmDirtyCheckResult(true);
  const refresh = window.ADA_DFM_REFRESH_DATASET;
  if (typeof refresh !== "function") throw new Error("The input triangle cannot be reloaded here.");
  const result = await refresh();
  if (!result?.ok) {
    throw new Error(toText(result?.message) || "The input triangle could not be loaded at the copied lengths.");
  }
  await ensureResultsRatioBasisAligned().catch(() => null);
}

async function restoreMethodPayload(payload, reason = "restore") {
  cancelDfmMethodAsyncTasks();
  const applied = await applyDfmOwnedPatchPayload(payload, { reason });
  cancelDfmMethodAsyncTasks();
  return !!applied?.ok;
}

/**
 * Lays `sourceMethod`'s settings over the open DFM as one undoable edit.
 * Returns `{ ok, error? }`; on failure the window is put back as it was.
 */
export async function applyDfmSettingsFromMethod(sourceMethod, { sourceLabel = "" } = {}) {
  if (copyInFlight) return { ok: false, error: "A copy is already running." };
  copyInFlight = true;
  const before = buildDfmMethodPayload();
  let lengthsChanged = false;
  try {
    cancelDfmMethodAsyncTasks();
    const lengths = dfmSettingsLengthChange(before, sourceMethod);
    if (lengths) {
      lengthsChanged = true;
      await reloadInputAtLengths(lengths);
    }
    cancelDfmMethodAsyncTasks();
    const merged = projectDfmSettingsCopy(buildDfmMethodPayload(), sourceMethod);
    const applied = await applyDfmOwnedPatchPayload(merged, { reason: "load-settings" });
    cancelDfmMethodAsyncTasks();
    if (!applied?.ok) throw new Error(toText(applied?.error) || "The copied settings could not be applied.");
    recordMethodHistoryStep(before, "load-settings");
    markDfmDirty();
    postStatus(sourceLabel ? `Settings loaded from ${sourceLabel}. Save to keep them.` : "Settings loaded. Save to keep them.");
    return { ok: true };
  } catch (error) {
    if (lengthsChanged) await restoreMethodPayload(before, "load-settings-rollback").catch(() => false);
    markDfmDirty();
    return { ok: false, error: toText(error?.message || error) || "The settings could not be loaded." };
  } finally {
    copyInFlight = false;
  }
}

async function runLoadSettings() {
  if (dialogOpen || copyInFlight) return;
  const projectName = toText(getResolvedProjectName());
  const currentClass = toText(getResolvedReservingClass());
  const currentMethodName = toText(document.getElementById("dfmMethodName")?.value);
  if (!projectName || !currentClass) {
    postStatus("Choose a project and reserving class first.", "warn");
    return;
  }
  dialogOpen = true;
  let choice = null;
  try {
    choice = await openDfmLoadSettingsDialog({ projectName, currentClass, currentMethodName });
  } finally {
    dialogOpen = false;
  }
  if (!choice) return;
  postStatus(`Loading settings from ${choice.methodName}...`);
  let response = null;
  try {
    response = await loadDfmMethod({
      project_name: projectName,
      reserving_class: choice.reservingClass,
      method_name: choice.methodName,
      output_dataset: choice.outputDataset,
    });
  } catch (error) {
    postStatus(`Could not open ${choice.methodName}: ${toText(error?.message || error)}`, "warn");
    return;
  }
  const result = await applyDfmSettingsFromMethod(response?.method, { sourceLabel: choice.methodName });
  if (!result.ok) postStatus(`Settings were not loaded: ${result.error}`, "warn");
}

export function wireDfmLoadSettingsButton() {
  setMethodHistoryHandlers({
    capture: () => buildDfmMethodPayload(),
    restore: (payload, reason) => restoreMethodPayload(payload, `history-${reason || "restore"}`),
  });
  const button = document.getElementById("dfmLoadSettingsBtn");
  if (!button || button.dataset.wired === "1") return;
  button.dataset.wired = "1";
  button.addEventListener("click", (event) => {
    event.preventDefault();
    void runLoadSettings();
  });
}
