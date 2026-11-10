// Shared poller for Engine-hosted dependent-propagation jobs.
// A save returns `propagation: {job_id, status: "queued"}` (or
// {status: "unchanged"} for a no-op save); pages track the job through the
// app-server status endpoint and surface "Updating dependents..." progress.
// Failed jobs are not auto-retried: downstream methods stay Review Needed and
// the next save or a manual refresh enqueues a fresh walk.

const POLL_INTERVAL_MS = 750;
const MAX_STATUS_RETRIES = 8;
// The Engine worker republishes a "processing" status every ~5s even when
// progress has not advanced (DEPENDENT_PROPAGATION_STATUS_HEARTBEAT_SECONDS
// in arcrho_dependent_propagation_contract.py), so a processing status whose
// updated_at stops moving means the worker died. Queued statuses have no
// heartbeat owner — the job is waiting for an Engine slot — so they get a
// separate, longer allowance before the poller gives up.
const STALE_STATUS_MS = 45 * 1000;
const QUEUED_STALE_STATUS_MS = 180 * 1000;
const SUCCESS_STATUSES = new Set(["success", "completed", "complete", "succeeded"]);
const ERROR_STATUSES = new Set(["error", "failed", "failure", "cancelled", "canceled"]);

function codedError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

export function dependentPropagationStatusUrl(jobId) {
  return `/dependent_propagation/refresh_dependents/status/${encodeURIComponent(String(jobId || "").trim())}`;
}

export function isEngineUnavailableSaveError(error) {
  if (Number(error?.status) === 503) return true;
  return /Arco Engine service is not available/iu.test(String(error?.message || error || ""));
}

async function readStatusResponseError(response) {
  const raw = await response.text();
  try {
    const body = JSON.parse(raw);
    return String(body?.detail || body?.message || raw || `HTTP ${response.status}`).trim();
  } catch {
    return String(raw || `HTTP ${response.status}`).trim();
  }
}

function isRetryableStatusResponse(response) {
  return response?.status === 423 || Number(response?.status) >= 500;
}

/** Poll one submitted propagation job until the Engine reports a terminal state. */
export async function waitForDependentPropagationJob({
  fetchImpl,
  statusUrl,
  jobId,
  onProgress = () => {},
  waitForPoll = (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs)),
  pollIntervalMs = POLL_INTERVAL_MS,
  maxStatusRetries = MAX_STATUS_RETRIES,
  staleStatusMs = STALE_STATUS_MS,
  queuedStaleStatusMs = QUEUED_STALE_STATUS_MS,
  now = () => Date.now(),
}) {
  let consecutiveFailures = 0;
  let lastFailure = "";
  let lastStatusSignature = "";
  const initialNow = Number(now());
  let lastActivityAt = Number.isFinite(initialNow) ? initialNow : Date.now();

  for (;;) {
    let response;
    try {
      response = await fetchImpl(statusUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
    } catch (error) {
      lastFailure = String(error?.message || error || "Network request failed.");
      response = null;
    }

    if (!response || (!response.ok && isRetryableStatusResponse(response))) {
      if (response) lastFailure = await readStatusResponseError(response);
      consecutiveFailures += 1;
      if (consecutiveFailures > maxStatusRetries) {
        throw codedError(
          "PROPAGATION_STATUS_UNAVAILABLE",
          `Dependent-update status is unavailable after repeated checks. Job "${jobId}" may still be running on Arco Engine.${lastFailure ? ` Last error: ${lastFailure}` : ""}`,
        );
      }
      onProgress({ label: "Waiting for dependent-update status...", completed: 0, total: 0 });
      await waitForPoll(pollIntervalMs);
      continue;
    }
    if (!response.ok) {
      const detail = await readStatusResponseError(response);
      if (response.status === 404) {
        // Queued statuses are published before the request file, so a missing
        // status means the job identity is wrong or the workspace changed.
        throw codedError(
          "PROPAGATION_STATUS_NOT_FOUND",
          `Dependent-update status was not found (${detail}).`,
        );
      }
      throw new Error(`Dependent-update status check failed: ${detail}`);
    }

    consecutiveFailures = 0;
    const result = await response.json();
    if (result?.ok === false) {
      throw new Error(String(result.message || result.error || "Dependent updates failed."));
    }
    const progress = result?.progress || {};
    const total = Math.max(0, Number(progress.total) || 0);
    const completed = Math.max(0, Number(progress.completed) || 0);
    onProgress({
      label: String(progress.label || progress.stage || "Updating dependents...").trim(),
      completed,
      total,
    });
    const status = String(result?.status || "").trim().toLowerCase();
    if (SUCCESS_STATUSES.has(status)) return result;
    if (ERROR_STATUSES.has(status)) {
      throw codedError(
        "PROPAGATION_JOB_ERROR",
        String(result.message || result.error || "Dependent updates failed."),
      );
    }

    const signature = JSON.stringify([
      status,
      result?.updated_at || "",
      progress.stage || "",
      completed,
      total,
      progress.label || "",
    ]);
    const allowedStaleMs = status === "queued" ? queuedStaleStatusMs : staleStatusMs;
    const currentNow = Number(now());
    const observedAt = Number.isFinite(currentNow) ? currentNow : lastActivityAt;
    if (signature !== lastStatusSignature) {
      lastStatusSignature = signature;
      lastActivityAt = observedAt;
    } else if (observedAt - lastActivityAt >= Math.max(pollIntervalMs, allowedStaleMs)) {
      throw codedError(
        "PROPAGATION_STATUS_STALE",
        `Dependent-update status has stopped updating. Job "${jobId}" appears to have stalled on Arco Engine.`,
      );
    }
    await waitForPoll(pollIntervalMs);
  }
}

/**
 * Resolve once a submitted propagation job reaches any terminal outcome.
 * Never throws: errors, stale statuses, and unavailable status checks all
 * resolve as `{ok: false, terminal: true}` so callers waiting to release
 * held UI state (live previews, paused watches) always proceed.
 */
export async function waitForDependentPropagationOutcome(jobId, {
  fetchImpl = (...args) => fetch(...args),
  onProgress = () => {},
  ...pollOptions
} = {}) {
  const id = String(jobId || "").trim();
  if (!id) return { ok: false, terminal: false };
  try {
    const result = await waitForDependentPropagationJob({
      fetchImpl,
      statusUrl: dependentPropagationStatusUrl(id),
      jobId: id,
      onProgress,
      ...pollOptions,
    });
    return { ok: true, terminal: true, result };
  } catch (error) {
    return { ok: false, terminal: true, error };
  }
}

// Loaded on first use so this module stays importable on its own.
async function showWalkFailure(message) {
  const { showPageMessageBox } = await import("/ui/shared/components/message_box/message_box.js");
  showPageMessageBox({ title: "Dependent updates", message, tone: "warn" });
}

async function reportWalkFailure(showFailure, message) {
  const text = String(message || "").trim();
  if (!text) return;
  try { await showFailure(text); } catch { /* the report must not break the save */ }
}

/**
 * Track a save response's `propagation` payload and report each live step.
 * Never throws. `onComplete(result)` fires at any terminal outcome (`result`
 * is null when the job failed) so callers refresh the dataset table either
 * way — a failed walk still finalized downstream objects at Review Needed.
 * A failed walk also shows the server's reason in a message box in the
 * window that saved (user decision, 2026-09-21, replacing the 2026-08-07
 * "no message" rule). A caller holding the save popup open awaits the
 * returned promise and treats a null resolution as "not clean".
 */
export async function trackSavePropagation(propagation, {
  fetchImpl = (...args) => fetch(...args),
  onStatus = () => {},
  onComplete = () => {},
  showFailure = showWalkFailure,
  ...pollOptions
} = {}) {
  if (!propagation || typeof propagation !== "object") return null;
  const status = String(propagation.status || "").trim().toLowerCase();
  if (status === "unchanged") return { status: "unchanged" };
  if (status === "completed") {
    // Engine-hosted saves run the dependent walk inline and the response
    // carries the finished outcome (with `refreshed_datasets`) — nothing to
    // poll. A walk that reported failures resolves null so the window stays
    // open.
    const clean = propagation.ok !== false;
    const payload = clean ? { ...propagation } : null;
    try { onComplete(payload); } catch { /* completion hooks must not break callers */ }
    if (!clean) await reportWalkFailure(showFailure, propagation.message);
    return payload;
  }
  const jobId = String(propagation.job_id || "").trim();
  if (!jobId) {
    const message = String(propagation.message || "Dependent updates could not be scheduled.").trim();
    onStatus(`Dependent updates were not scheduled: ${message}`, { tone: "warn" });
    return null;
  }

  onStatus("Updating dependents...", { tone: "info" });
  try {
    const result = await waitForDependentPropagationJob({
      fetchImpl,
      statusUrl: dependentPropagationStatusUrl(jobId),
      jobId,
      onProgress: ({ label, completed, total }) => {
        const text = String(label || "").trim() || "Updating dependents...";
        // Per-dataset ticks (non-zero total) name the dataset being
        // refreshed; stage banners pass through as-is. Only queued refresh
        // flows still poll — Engine-hosted saves complete inline above.
        const framed = total > 0 ? `Updating dataset ${text}...` : text;
        onStatus(framed, { tone: "info" });
      },
      ...pollOptions,
    });
    onStatus(`Dependent updates complete at ${new Date().toLocaleTimeString()}.`, { tone: "info" });
    try { onComplete(result); } catch { /* completion hooks must not break polling callers */ }
    return result;
  } catch (error) {
    onStatus(`Dependent updates finished at ${new Date().toLocaleTimeString()}.`, { tone: "info" });
    try { onComplete(null); } catch { /* completion hooks must not break polling callers */ }
    // Only a walk that ran and failed has a reason worth showing; a lost
    // status stays quiet.
    if (error?.code === "PROPAGATION_JOB_ERROR") await reportWalkFailure(showFailure, error.message);
    return null;
  }
}
