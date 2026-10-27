/**
 * Project Settings - Project Lock
 *
 * Owns the lock switch on the Project Settings tab and the guard that stops
 * this page's explicit save buttons on a locked project. The server refuses
 * every change to a locked project's data either way; the guard only answers
 * the click with the reason instead of a failed save.
 */

import {
  readProjectLock,
  showProjectLockedMessage,
} from "/ui/shared/services/project_lock.js?v=20261004lock1";

// Buttons on this page that write project data when clicked.
const GUARDED_BUTTON_IDS = [
  "dtEditorSaveBtn",
  "rctEditorSaveBtn",
  "dprEditorSaveBtn",
  "sdImportSaveBtn",
  "sdImportDataBtn",
  "detailRenameBtn",
];

function formatLockedAt(value) {
  const date = new Date(String(value || ""));
  return Number.isNaN(date.getTime()) ? String(value || "") : date.toLocaleString();
}

function newRequestId() {
  return crypto.randomUUID().replace(/-/g, "");
}

export function createProjectLockFeature({ getSelectedProject, fetchImpl = fetch, documentRef = document }) {
  const switchEl = documentRef.getElementById("projectLockSwitch");
  const statusEl = documentRef.getElementById("projectLockStatus");
  let state = { projectKey: "", locked: false, message: "" };
  let loadToken = 0;

  const projectKey = (name) => String(name || "").trim().toLowerCase();

  function render(lock, { error = "" } = {}) {
    if (!switchEl || !statusEl) return;
    switchEl.setAttribute("aria-checked", lock.locked ? "true" : "false");
    statusEl.classList.toggle("is-error", !!error);
    if (error) {
      statusEl.textContent = error;
    } else if (lock.locked) {
      const by = lock.locked_by ? ` by ${lock.locked_by}` : "";
      const at = lock.locked_at ? ` on ${formatLockedAt(lock.locked_at)}` : "";
      statusEl.textContent = `Locked${by}${at}. Methods, datasets and imports cannot be changed.`;
    } else {
      statusEl.textContent = "Unlocked. Lock to stop all users from changing methods, datasets and imports.";
    }
  }

  async function load(projectName) {
    const token = ++loadToken;
    state = { projectKey: projectKey(projectName), locked: false, message: "" };
    if (switchEl) switchEl.disabled = true;
    try {
      const lock = await readProjectLock(projectName, { fetchImpl });
      if (token !== loadToken) return;
      state.locked = lock.locked;
      state.message = lock.message;
      render(lock);
      if (switchEl) switchEl.disabled = false;
    } catch (err) {
      if (token !== loadToken) return;
      render({ locked: false }, { error: `Could not read the lock: ${err.message || err}` });
    }
  }

  async function toggle() {
    const project = getSelectedProject();
    if (!project?.name || !switchEl || switchEl.disabled) return;
    const token = ++loadToken;
    switchEl.disabled = true;
    try {
      const resp = await fetchImpl("/project_lock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: project.name, locked: !state.locked, request_id: newRequestId() }),
      });
      const payload = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(String(payload?.detail || `HTTP ${resp.status}`));
      if (token !== loadToken) return;
      state.locked = payload?.locked === true;
      state.message = String(payload?.message || "");
      render(payload);
    } catch (err) {
      if (token !== loadToken) return;
      render(state, { error: `Could not change the lock: ${err.message || err}` });
    } finally {
      if (token === loadToken) switchEl.disabled = false;
    }
  }

  function isSelectedProjectLocked() {
    return state.locked && state.projectKey === projectKey(getSelectedProject()?.name);
  }

  function guardSaveClick(event) {
    if (!isSelectedProjectLocked()) return;
    const button = event.target?.closest?.("button");
    if (!button || !GUARDED_BUTTON_IDS.includes(button.id)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void showProjectLockedMessage(state.message, { documentRef });
  }

  switchEl?.addEventListener("click", () => void toggle());
  documentRef.addEventListener("click", guardSaveClick, true);

  return { load };
}
