// Project Settings feature: the Project Dates panel.
//
// A floating window holds Origin Start, Origin End and Development End. Apply
// checks the date rule, asks the server what the change touches, and shows a
// confirmation; confirming submits one Engine job that saves the dates and
// moves the whole project, followed in the shell's progress window. The poll
// loop, the request id and the sentences live in the sibling job module.
//
// The main page's dates band is the panel's one entry point: a click, Enter or
// Space anywhere on it opens the panel, and it stays inert while no project is
// selected or the project is locked.

import {
  formatBoundaryYmDisplay,
  normalizeBoundaryYmCanonical,
} from "/ui/project_settings/project_settings_general_settings.js?v=20261103panel1";
import {
  createProjectDatesRequestId,
  describeProjectDatesMove,
  describeProjectDatesPreview,
  describeProjectDatesResult,
  projectDatesBandProgress,
  projectDatesJobRequestBody,
  projectDatesPreviewUrl,
  projectInstanceOpenMessage,
  validateProjectDates,
  waitForProjectDatesJob,
} from "/ui/project_settings/project_settings_project_dates_job.js?v=20261103panel1";

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
 * @param {Function} [deps.isProjectLocked] true while the selected project is locked
 * @param {Function} deps.loadDates `(projectName) => Promise<{originStartDate, ...}>`
 * @param {Function} deps.reloadDates `(projectName) => Promise` after a change
 * @param {Function} [deps.postShellMessage] posts one message to the shell (opens a review row)
 * @param {Document} [deps.documentRef]
 */
export function createProjectDatesFeature({
  fetchImpl,
  setStatus,
  publishShellProgress,
  readResponseErrorDetail,
  getSelectedProject,
  isProjectLocked = () => false,
  loadDates,
  reloadDates,
  postShellMessage = (message) => window.parent.postMessage(message, window.location.origin),
  documentRef = document,
  requestIdFactory = createProjectDatesRequestId,
  pollOptions = {},
}) {
  const el = (id) => documentRef.getElementById(id);
  const dom = {
    band: el("summaryPeriodsBand"),
    bandProgress: el("summaryDatesProgress"),
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
  // A finished change: Close leads, and Apply waits for an edit unless running
  // the same dates again can still help (`rerun`, decision 2).
  let finished = null;
  let reviewGroups = [];
  // The running change, so the band can show and reopen its progress.
  let run = null;

  const publishProgress = (action, progressId, details = {}) => publishShellProgress?.({
    type: "arcrho:project-settings-progress",
    action,
    progressId,
    ...details,
  });

  /* ---------------- panel state ---------------- */

  function setMessage(text = "", { error = false, warning = false } = {}) {
    if (!dom.message) return;
    dom.message.textContent = text;
    dom.message.hidden = !text;
    dom.message.classList.toggle("is-error", !!error && !!text);
    dom.message.classList.toggle("is-warning", !error && !!warning && !!text);
  }

  function reviewRowHtml(row, groupIndex, rowIndex) {
    // A class path is long; its last part tells rows apart, the hover holds the rest.
    const label = `<span class="pd-review-name"><span class="pd-review-class">${escapeHtml(row.reservingClass.split("\\").pop())}</span>`
      + `${escapeHtml(row.name)}</span>`;
    const reason = row.open ? "" : `<span class="pd-review-reason">${escapeHtml(row.reason)}</span>`;
    const title = `title="${escapeHtml(row.detail)}"`;
    return row.open
      ? `<button class="pd-review-row" type="button" role="listitem" data-group="${groupIndex}" data-row="${rowIndex}" ${title}>${label}</button>`
      : `<div class="pd-review-row is-text" role="listitem" ${title}>${row.reservingClass ? label : ""}${reason}</div>`;
  }

  /** The review list, one collapsed group per reason, each headed by its count. */
  function renderReview(groups = []) {
    reviewGroups = groups;
    if (!dom.review) return;
    const total = groups.reduce((sum, group) => sum + group.rows.length, 0);
    if (!total) {
      dom.review.hidden = true;
      dom.review.innerHTML = "";
      return;
    }
    dom.review.hidden = false;
    dom.review.innerHTML = `<div class="pd-review-head">For Review (${total.toLocaleString("en-US")})</div>`
      + '<div class="pd-review-list">'
      + groups.map((group, groupIndex) => (
        `<details class="pd-review-group${group.problem ? " is-problem" : ""}">`
        + `<summary><span class="pd-review-heading">${escapeHtml(group.heading)}</span>`
        + `<span class="pd-review-count">${group.rows.length.toLocaleString("en-US")}</span></summary>`
        + `<div role="list">${group.rows.map((row, rowIndex) => reviewRowHtml(row, groupIndex, rowIndex)).join("")}</div>`
        + "</details>"
      )).join("")
      + "</div>";
  }

  function openReviewRow(event) {
    const button = event.target?.closest?.("button.pd-review-row");
    if (!button) return;
    const row = reviewGroups[Number(button.dataset.group)]?.rows?.[Number(button.dataset.row)];
    const project = getSelectedProject();
    if (!row?.open || String(project?.name || "").trim() !== panelProject) return;
    postShellMessage(projectInstanceOpenMessage(project, row.open));
  }

  function syncControls() {
    const locked = busy || running;
    const settled = !!finished && !finished.rerun;
    for (const key of FIELD_KEYS) {
      if (dom.inputs[key]) dom.inputs[key].disabled = locked;
    }
    dom.pickerButtons.forEach((button) => { button.disabled = locked; });
    if (dom.apply) {
      dom.apply.disabled = locked || settled;
      dom.apply.textContent = finished?.rerun ? "Run Again" : "Apply";
      dom.apply.classList.toggle("primary", !settled);
    }
    if (dom.cancel) {
      dom.cancel.textContent = finished ? "Close" : "Cancel";
      dom.cancel.classList.toggle("primary", settled);
    }
    dom.panel?.setAttribute("aria-busy", String(locked));
  }

  /** A date edited after a finished change makes Apply the next step again. */
  function clearFinished() {
    if (!finished || running) return;
    finished = null;
    syncControls();
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

  /** Open the panel on the selected project's saved dates; false with no project. */
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
      finished = null;
    }
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
    // Keyboard focus goes back to the band that opened the panel.
    const hadFocus = dom.panel.contains(documentRef.activeElement);
    dom.panel.classList.remove("show");
    dom.panel.setAttribute("aria-hidden", "true");
    if (!running) panelProject = "";
    if (hadFocus && dom.band?.getAttribute("aria-disabled") !== "true") dom.band.focus();
  }

  /* ---------------- dates band ---------------- */

  function bandCanOpen() {
    return !!String(getSelectedProject()?.name || "").trim() && !isProjectLocked();
  }

  /** True while the selected project's dates change runs. */
  function bandShowsRun() {
    return !!run && String(getSelectedProject()?.name || "").trim() === run.project;
  }

  /**
   * Reflect what the band does: while the selected project's change runs it
   * shows the progress and reopens the progress window; otherwise it opens the
   * panel, and no project or a lock makes it inert.
   */
  function syncEntryPoint() {
    if (!dom.band) return;
    const showsRun = bandShowsRun();
    const enabled = showsRun || bandCanOpen();
    dom.band.setAttribute("aria-disabled", String(!enabled));
    dom.band.tabIndex = enabled ? 0 : -1;
    dom.band.classList.toggle("is-running", showsRun);
    if (dom.bandProgress) {
      dom.bandProgress.textContent = showsRun ? projectDatesBandProgress(run.progress) : "";
      dom.bandProgress.hidden = !showsRun;
    }
  }

  function openFromBand() {
    syncEntryPoint();
    if (bandShowsRun()) {
      publishProgress("open", run.progressId, { title: "Change Project Dates", ...run.window });
      return;
    }
    if (!bandCanOpen()) return;
    void open();
  }

  /* ---------------- confirmation ---------------- */

  function showConfirm(preview) {
    if (!dom.confirmOverlay) return Promise.resolve(false);
    const { rows, droppedLine } = describeProjectDatesPreview(preview);
    if (dom.confirmTitle) {
      dom.confirmTitle.textContent = preview?.resumed ? "Finish Project Dates Change" : "Change Project Dates";
    }
    if (dom.confirmDates) {
      // Before and after, one row per date; only the dates that change are bold.
      dom.confirmDates.innerHTML = '<thead><tr><td></td><th scope="col">Before</th><th scope="col">After</th></tr></thead><tbody>'
        + describeProjectDatesMove(preview?.previous_dates, preview?.dates).map((row) => (
          `<tr${row.changed ? ' class="is-changed"' : ""}><th scope="row">${escapeHtml(row.label)}</th>`
          + `<td>${escapeHtml(row.before)}</td><td>${escapeHtml(row.after)}</td></tr>`
        )).join("")
        + "</tbody>";
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
    if (finished) {
      // Run Again resends the dates that just ran; it is offered only while
      // the job kept the unfinished change, so no new confirmation is asked.
      if (finished.rerun) await runJob(panelProject, finished.dates);
      return;
    }
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
    finished = null;
    renderReview([]);
    syncControls();
    setMessage("Changing the project dates...");
    run = {
      project: name,
      progressId,
      progress: null,
      window: { label: `Submitting the change for "${name}"...`, completed: 0, total: 0, countText: "Working..." },
    };
    publishProgress("open", progressId, { title: "Change Project Dates", ...run.window });
    syncEntryPoint();
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
        onProgress: (progress) => {
          run.progress = progress;
          run.window = {
            label: progress.label,
            completed: progress.completed,
            total: progress.total,
            countText: progress.total > 0 ? "" : "Working...",
          };
          publishProgress("update", progressId, run.window);
          syncEntryPoint();
        },
        ...pollOptions,
      });
      const outcome = describeProjectDatesResult(terminal?.result, terminal?.message);
      publishProgress("update", progressId, { label: "Project dates changed.", completed: 1, total: 1, countText: "" });
      publishProgress("close", progressId, { autoCloseMs: 850 });
      setStatus(outcome.text);
      if (panelProject === name) {
        setMessage(outcome.text, { warning: outcome.failed });
        renderReview(outcome.groups);
        finished = { dates, rerun: outcome.rerun };
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
      run = null;
      syncControls();
      syncEntryPoint();
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

  dom.band?.addEventListener("click", openFromBand);
  dom.band?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (!event.repeat) openFromBand();
  });
  syncEntryPoint();
  dom.header?.addEventListener("pointerdown", onHeaderPointerDown);
  dom.header?.addEventListener("pointermove", onHeaderPointerMove);
  dom.header?.addEventListener("pointerup", onHeaderPointerEnd);
  dom.header?.addEventListener("pointercancel", onHeaderPointerEnd);
  dom.header?.addEventListener("lostpointercapture", onHeaderPointerEnd);
  dom.close?.addEventListener("click", close);
  dom.cancel?.addEventListener("click", close);
  dom.apply?.addEventListener("click", () => void apply());
  dom.review?.addEventListener("click", openReviewRow);
  for (const key of FIELD_KEYS) {
    const input = dom.inputs[key];
    input?.addEventListener("input", clearFinished);
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

  return { open, close, isOpen, isRunning: () => running, syncEntryPoint };
}
