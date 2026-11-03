// Project Settings feature: the Project Dates panel.
//
// A floating window holds Origin Start, Origin End and Development End. Apply
// checks the date rule, asks the server what the change touches, and shows a
// confirmation; confirming submits one Engine job that saves the dates and
// moves the whole project, followed in the shell's progress window. The poll
// loop, the request id and the sentences live in the sibling job module.

import {
  formatBoundaryYmDisplay,
  normalizeBoundaryYmCanonical,
} from "/ui/project_settings/project_settings_general_settings.js?v=20261103dates1";
import {
  createProjectDatesRequestId,
  describeProjectDatesPreview,
  describeProjectDatesResult,
  formatProjectDateSet,
  projectDatesJobRequestBody,
  projectDatesPreviewUrl,
  validateProjectDates,
  waitForProjectDatesJob,
} from "/ui/project_settings/project_settings_project_dates_job.js?v=20261103dates1";

const FIELD_KEYS = ["originStartDate", "originEndDate", "developmentEndDate"];

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * @param {object} deps
 * @param {Function} deps.fetchImpl
 * @param {Function} deps.setStatus
 * @param {Function} deps.publishShellProgress posts one shell progress message
 * @param {Function} deps.readResponseErrorDetail
 * @param {Function} deps.getSelectedProject
 * @param {Function} deps.loadDates `(projectName) => Promise<{originStartDate, ...}>`
 * @param {Function} deps.reloadDates `(projectName) => Promise` after a change
 * @param {Document} [deps.documentRef]
 */
export function createProjectDatesFeature({
  fetchImpl,
  setStatus,
  publishShellProgress,
  readResponseErrorDetail,
  getSelectedProject,
  loadDates,
  reloadDates,
  documentRef = document,
  requestIdFactory = createProjectDatesRequestId,
  pollOptions = {},
}) {
  const el = (id) => documentRef.getElementById(id);
  const dom = {
    panel: el("projectDatesPanel"),
    header: el("projectDatesPanelHeader"),
    close: el("projectDatesPanelClose"),
    inputs: {
      originStartDate: el("pdOriginStartInput"),
      originEndDate: el("pdOriginEndInput"),
      developmentEndDate: el("pdDevelopmentEndInput"),
    },
    pickerButtons: Array.from(documentRef.querySelectorAll("#projectDatesPanel .sd-month-picker-btn")),
    message: el("pdMessage"),
    review: el("pdReview"),
    cancel: el("pdCancelBtn"),
    apply: el("pdApplyBtn"),
    confirmOverlay: el("projectDatesConfirmOverlay"),
    confirmBox: el("projectDatesConfirmBox"),
    confirmTitle: el("pdConfirmTitle"),
    confirmDates: el("pdConfirmDates"),
    confirmCounts: el("pdConfirmCounts"),
    confirmDropped: el("pdConfirmDropped"),
    confirmCancel: el("pdConfirmCancel"),
    confirmOk: el("pdConfirmOk"),
  };

  let panelProject = "";
  let busy = false;
  let running = false;
  let pendingDates = null;
  let confirmResolve = null;
  let drag = null;

  const publishProgress = (action, progressId, details = {}) => publishShellProgress?.({
    type: "arcrho:project-settings-progress",
    action,
    progressId,
    ...details,
  });

  /* ---------------- panel state ---------------- */

  function setMessage(text = "", { error = false } = {}) {
    if (!dom.message) return;
    dom.message.textContent = text;
    dom.message.hidden = !text;
    dom.message.classList.toggle("is-error", !!error && !!text);
  }

  function renderReview(items = []) {
    if (!dom.review) return;
    if (!items.length) {
      dom.review.hidden = true;
      dom.review.innerHTML = "";
      return;
    }
    dom.review.hidden = false;
    dom.review.innerHTML = `<div class="pd-review-head">For Review (${items.length.toLocaleString("en-US")})</div>`
      + '<div class="pd-review-list" role="list">'
      + items.map((item) => (
        '<div class="pd-review-row" role="listitem">'
        + `<span class="pd-review-name" title="${escapeHtml(`${item.reservingClass} / ${item.name}`)}">`
        // A class path is long; its last part tells rows apart, the title holds the rest.
        + `<span class="pd-review-class">${escapeHtml(item.reservingClass.split("\\").pop())}</span>${escapeHtml(item.name)}</span>`
        + `<span class="pd-review-reason" title="${escapeHtml(item.reasons.join("; "))}">${escapeHtml(item.reasons.join("; "))}</span>`
        + "</div>"
      )).join("")
      + "</div>";
  }

  function syncControls() {
    const locked = busy || running;
    for (const key of FIELD_KEYS) {
      if (dom.inputs[key]) dom.inputs[key].disabled = locked;
    }
    dom.pickerButtons.forEach((button) => { button.disabled = locked; });
    if (dom.apply) dom.apply.disabled = locked;
    dom.panel?.setAttribute("aria-busy", String(locked));
  }

  function readDates() {
    const dates = {};
    for (const key of FIELD_KEYS) {
      dates[key] = normalizeBoundaryYmCanonical(dom.inputs[key]?.value || "");
    }
    return dates;
  }

  function writeDates(values = {}) {
    for (const key of FIELD_KEYS) {
      if (dom.inputs[key]) dom.inputs[key].value = formatBoundaryYmDisplay(values?.[key] || "");
    }
  }

  /** Rewrite a typed month in the panel's display spelling; keep text it cannot read. */
  function normalizeInput(input) {
    const canonical = normalizeBoundaryYmCanonical(input?.value || "");
    if (canonical) input.value = formatBoundaryYmDisplay(canonical);
  }

  function isOpen() {
    return !!dom.panel?.classList.contains("show");
  }

  /**
   * Open the panel on the selected project's saved dates.
   *
   * Step 7 wires the main page's dates band to this. Returns false when no
   * project is selected.
   */
  async function open() {
    const project = getSelectedProject();
    const name = String(project?.name || "").trim();
    if (!name || !dom.panel) return false;
    if (isOpen() && panelProject === name) {
      dom.inputs.originStartDate?.focus();
      return true;
    }
    panelProject = name;
    if (!running) {
      setMessage("");
      renderReview([]);
    }
    if (dom.cancel) dom.cancel.textContent = "Cancel";
    // Re-center on every open so a dragged window never opens off-screen.
    dom.panel.style.left = "50%";
    dom.panel.style.top = "140px";
    dom.panel.style.transform = "translateX(-50%)";
    dom.panel.classList.add("show");
    dom.panel.setAttribute("aria-hidden", "false");
    busy = true;
    syncControls();
    try {
      const values = await loadDates(name);
      if (panelProject !== name) return true;
      writeDates(values);
    } catch (error) {
      setMessage(`Could not read the project dates: ${error?.message || error}`, { error: true });
    } finally {
      busy = false;
      syncControls();
    }
    if (!running) dom.inputs.originStartDate?.focus();
    return true;
  }

  function close() {
    if (!dom.panel || !isOpen()) return;
    endDrag();
    hideConfirm(false);
    dom.panel.classList.remove("show");
    dom.panel.setAttribute("aria-hidden", "true");
    if (!running) panelProject = "";
  }

  /* ---------------- confirmation ---------------- */

  function showConfirm(preview) {
    if (!dom.confirmOverlay) return Promise.resolve(false);
    const { rows, droppedLine } = describeProjectDatesPreview(preview);
    const before = formatProjectDateSet(preview?.previous_dates);
    const after = formatProjectDateSet(preview?.dates);
    if (dom.confirmTitle) {
      dom.confirmTitle.textContent = preview?.resumed ? "Finish Project Dates Change" : "Change Project Dates";
    }
    if (dom.confirmDates) {
      dom.confirmDates.innerHTML = before && before !== after
        ? `<span class="pd-confirm-before">${escapeHtml(before)}</span>`
          + '<span class="pd-confirm-arrow" aria-label="to">→</span>'
          + `<span class="pd-confirm-after">${escapeHtml(after)}</span>`
        : `<span class="pd-confirm-after">${escapeHtml(after)}</span>`;
    }
    if (dom.confirmCounts) {
      dom.confirmCounts.innerHTML = rows.map((row) => (
        `<div class="pd-count"><span class="pd-count-label">${escapeHtml(row.label)}</span>`
        + `<span class="pd-count-value">${escapeHtml(row.value)}</span></div>`
      )).join("");
    }
    if (dom.confirmDropped) {
      dom.confirmDropped.textContent = droppedLine;
      dom.confirmDropped.hidden = !droppedLine;
    }
    dom.confirmOverlay.classList.add("show");
    dom.confirmOverlay.setAttribute("aria-hidden", "false");
    setTimeout(() => dom.confirmOk?.focus(), 30);
    return new Promise((resolve) => { confirmResolve = resolve; });
  }

  function hideConfirm(result) {
    dom.confirmOverlay?.classList.remove("show");
    dom.confirmOverlay?.setAttribute("aria-hidden", "true");
    const resolve = confirmResolve;
    confirmResolve = null;
    resolve?.(result);
  }

  /* ---------------- apply and the job ---------------- */

  async function readPreview(name, dates) {
    const response = await fetchImpl(projectDatesPreviewUrl(name, dates), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(await readResponseErrorDetail(response));
    return response.json();
  }

  async function apply() {
    if (busy || running || !panelProject) return;
    FIELD_KEYS.forEach((key) => normalizeInput(dom.inputs[key]));
    const dates = readDates();
    const problem = validateProjectDates(dates);
    if (problem) {
      setMessage(problem, { error: true });
      return;
    }
    const name = panelProject;
    setMessage("");
    renderReview([]);
    busy = true;
    syncControls();
    let preview;
    try {
      preview = await readPreview(name, dates);
    } catch (error) {
      setMessage(String(error?.message || error), { error: true });
      return;
    } finally {
      busy = false;
      syncControls();
    }
    if (preview?.unchanged) {
      setMessage("The project already has these dates.");
      return;
    }
    pendingDates = dates;
    const confirmed = await showConfirm(preview);
    const chosen = pendingDates;
    pendingDates = null;
    if (!confirmed || !chosen || panelProject !== name) return;
    await runJob(name, chosen);
  }

  async function runJob(name, dates) {
    const requestId = requestIdFactory();
    const progressId = `project-dates-${requestId}`;
    running = true;
    syncControls();
    setMessage("Changing the project dates...");
    publishProgress("open", progressId, {
      title: "Change Project Dates",
      label: `Submitting the change for "${name}"...`,
      completed: 0,
      total: 0,
      countText: "Working...",
    });
    try {
      const response = await fetchImpl("/general_settings/dates/job", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(projectDatesJobRequestBody(name, dates, requestId)),
      });
      if (!response.ok) throw new Error(await readResponseErrorDetail(response));
      const submitted = await response.json();
      setStatus(`Changing the project dates for "${name}" on Arco Server...`);
      const terminal = await waitForProjectDatesJob({
        fetchImpl,
        projectName: name,
        jobId: submitted?.job_id || requestId,
        onProgress: (progress) => publishProgress("update", progressId, {
          label: progress.label,
          completed: progress.completed,
          total: progress.total,
          countText: progress.total > 0 ? "" : "Working...",
        }),
        ...pollOptions,
      });
      const outcome = describeProjectDatesResult(terminal?.result, terminal?.message);
      publishProgress("update", progressId, { label: "Project dates changed.", completed: 1, total: 1, countText: "" });
      publishProgress("close", progressId, { autoCloseMs: 850 });
      setStatus(outcome.text);
      if (panelProject === name) {
        setMessage(outcome.text, { error: outcome.failed });
        renderReview(outcome.review);
        if (dom.cancel) dom.cancel.textContent = "Close";
      }
      try {
        await reloadDates(name);
      } catch {
        // The band rereads the dates on the next project load.
      }
      return { ok: true, result: terminal?.result || null };
    } catch (error) {
      publishProgress("close", progressId);
      const message = String(error?.message || error || "The project dates change failed.");
      setStatus(message);
      if (panelProject === name) setMessage(message, { error: true });
      // A change that stopped part way may have saved the dates already.
      try { await reloadDates(name); } catch { /* ignore */ }
      return { ok: false, error: message };
    } finally {
      running = false;
      syncControls();
    }
  }

  /* ---------------- window drag ---------------- */

  function endDrag() {
    if (!drag) return;
    const { pointerId } = drag;
    drag = null;
    if (dom.header?.hasPointerCapture?.(pointerId)) dom.header.releasePointerCapture(pointerId);
  }

  function onHeaderPointerDown(event) {
    if (!dom.panel || event.button !== 0 || event.target.closest("button")) return;
    const rect = dom.panel.getBoundingClientRect();
    // Drop the centering transform so `left` names the real left edge.
    dom.panel.style.transform = "none";
    dom.panel.style.left = `${rect.left}px`;
    dom.panel.style.top = `${rect.top}px`;
    drag = { pointerId: event.pointerId, offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top };
    dom.header.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  function onHeaderPointerMove(event) {
    if (!drag || event.pointerId !== drag.pointerId || !dom.panel) return;
    const view = documentRef.defaultView || window;
    const maxLeft = view.innerWidth - dom.panel.offsetWidth - 8;
    const maxTop = view.innerHeight - dom.panel.offsetHeight - 8;
    dom.panel.style.left = `${Math.max(8, Math.min(maxLeft, event.clientX - drag.offsetX))}px`;
    dom.panel.style.top = `${Math.max(8, Math.min(maxTop, event.clientY - drag.offsetY))}px`;
  }

  function onHeaderPointerEnd(event) {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    endDrag();
  }

  /* ---------------- wiring ---------------- */

  dom.header?.addEventListener("pointerdown", onHeaderPointerDown);
  dom.header?.addEventListener("pointermove", onHeaderPointerMove);
  dom.header?.addEventListener("pointerup", onHeaderPointerEnd);
  dom.header?.addEventListener("pointercancel", onHeaderPointerEnd);
  dom.header?.addEventListener("lostpointercapture", onHeaderPointerEnd);
  dom.close?.addEventListener("click", close);
  dom.cancel?.addEventListener("click", close);
  dom.apply?.addEventListener("click", () => void apply());
  for (const key of FIELD_KEYS) {
    const input = dom.inputs[key];
    input?.addEventListener("change", () => {
      normalizeInput(input);
      setMessage("");
    });
    input?.addEventListener("blur", () => normalizeInput(input));
    input?.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      void apply();
    });
  }
  dom.panel?.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || confirmResolve) return;
    // The month picker owns the first Escape while it is open.
    if (documentRef.getElementById("summaryMonthPicker")?.hidden === false) return;
    event.stopPropagation();
    close();
  });
  dom.confirmOk?.addEventListener("click", () => hideConfirm(true));
  dom.confirmCancel?.addEventListener("click", () => hideConfirm(false));
  dom.confirmOverlay?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      hideConfirm(false);
    }
  });
  dom.confirmOverlay?.addEventListener("mousedown", (event) => {
    if (dom.confirmBox?.contains(event.target)) event.stopPropagation();
  });

  return { open, close, isOpen, isRunning: () => running };
}
