// Client half of the Engine-hosted project dates change.
//
// The change runs on the ArcRho Server host: it saves the three dates, then
// regenerates, reshapes and refreshes every reserving class. This module has
// no DOM or shell dependency: it holds the date rule the panel checks before
// the confirmation, the request id, the poll loop and its status rules, and
// the plain sentences the panel shows. The panel feature owns everything the
// user sees.

const POLL_INTERVAL_MS = 750;
const MAX_STATUS_RETRIES = 8;
// The worker republishes its "processing" status every ~5 s even while one
// class is still running (PROJECT_DATES_JOB_STATUS_HEARTBEAT_SECONDS), so a
// status whose updated_at stops moving means the worker died. A queued job
// waits for an Engine slot and has no heartbeat owner, so it gets longer.
const STALE_STATUS_MS = 45 * 1000;
const QUEUED_STALE_STATUS_MS = 180 * 1000;
const SUCCESS_STATUSES = new Set(["success", "completed", "complete", "succeeded"]);
const ERROR_STATUSES = new Set(["error", "failed", "failure", "cancelled", "canceled"]);

const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function codedError(code, message, statusCode = 0) {
  const error = new Error(message);
  error.code = code;
  if (statusCode) error.statusCode = statusCode;
  return error;
}

function monthNumber(value) {
  const match = String(value || "").trim().match(/^(\d{4})(\d{2})$/u);
  if (!match) return null;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return Number(match[1]) * 12 + (month - 1);
}

function displayMonth(value) {
  const index = monthNumber(value);
  if (index === null) return "";
  return `${MONTH_ABBR[index % 12]} ${Math.floor(index / 12)}`;
}

function count(value) {
  const number = Math.max(0, Math.trunc(Number(value) || 0));
  return number.toLocaleString("en-US");
}

/** "1 dataset", "2 datasets": a count with its noun in the right number. */
export function plural(value, singular, pluralForm = `${singular}s`) {
  const number = Math.max(0, Math.trunc(Number(value) || 0));
  return `${count(number)} ${number === 1 ? singular : pluralForm}`;
}

/**
 * Decision 4: origin start <= origin end <= development end, all `YYYYMM`.
 * Returns the first problem as one short sentence, or "" when the set is valid.
 */
export function validateProjectDates({ originStartDate, originEndDate, developmentEndDate }) {
  const start = monthNumber(originStartDate);
  const end = monthNumber(originEndDate);
  const development = monthNumber(developmentEndDate);
  if (start === null) return "Enter an Origin Start month.";
  if (end === null) return "Enter an Origin End month.";
  if (development === null) return "Enter a Development End month.";
  if (start > end) return "Origin Start is after Origin End.";
  if (end > development) return "Origin End is after Development End.";
  return "";
}

export function createProjectDatesRequestId(cryptoImpl) {
  let cryptoSource = cryptoImpl;
  if (cryptoSource === undefined) {
    try { cryptoSource = globalThis.crypto; } catch { cryptoSource = null; }
  }
  if (typeof cryptoSource?.randomUUID === "function") {
    const uuid = String(cryptoSource.randomUUID()).trim().toLowerCase();
    if (/^[a-z0-9][a-z0-9-]{0,120}$/u.test(uuid)) return `psdates_${uuid}`;
  }
  if (typeof cryptoSource?.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoSource.getRandomValues(bytes);
    return `psdates_${[...bytes].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
  }
  throw new Error("Secure browser request-ID generation is unavailable.");
}

function dateParams(projectName, dates) {
  return {
    project_name: String(projectName || "").trim(),
    origin_start_date: String(dates?.originStartDate || "").trim(),
    origin_end_date: String(dates?.originEndDate || "").trim(),
    development_end_date: String(dates?.developmentEndDate || "").trim(),
  };
}

export function projectDatesPreviewUrl(projectName, dates) {
  return `/general_settings/dates/preview?${new URLSearchParams(dateParams(projectName, dates)).toString()}`;
}

export function projectDatesJobStatusUrl(projectName, jobId) {
  const params = new URLSearchParams({
    project_name: String(projectName || "").trim(),
    job_id: String(jobId || "").trim(),
  });
  return `/general_settings/dates/job/status?${params.toString()}`;
}

export function projectDatesJobRequestBody(projectName, dates, requestId) {
  return { ...dateParams(projectName, dates), request_id: String(requestId || "").trim() };
}

const ORIGIN_LENGTH_NAMES = new Map([[12, "annual"], [6, "semi-annual"], [3, "quarterly"], [1, "monthly"]]);

function originLengthName(length) {
  return ORIGIN_LENGTH_NAMES.get(Number(length)) || `${count(length)}-month`;
}

/**
 * What the confirmation shows for one preview: the counts as rows, and the
 * dropped-origins line (empty when no origin drops out).
 */
export function describeProjectDatesPreview(preview) {
  const engine = Number(preview?.engine_datasets) || 0;
  const calculated = Number(preview?.calculated_datasets) || 0;
  const imported = Number(preview?.imported_datasets) || 0;
  const rows = [
    { label: "Reserving Classes", value: count(preview?.classes) },
    { label: "Datasets", value: count(engine + calculated + imported) },
    { label: "Methods", value: count(preview?.methods) },
    { label: "Hand-Entered Datasets", value: count(preview?.imported_reshaped) },
  ];
  const dropped = (Array.isArray(preview?.origin_changes) ? preview.origin_changes : [])
    .filter((change) => Number(change?.dropped) > 0)
    .map((change) => plural(change.dropped, `${originLengthName(change.origin_length)} origin`));
  let droppedLine = "";
  if (dropped.length) {
    const list = dropped.length > 1
      ? `${dropped.slice(0, -1).join(", ")} and ${dropped[dropped.length - 1]}`
      : dropped[0];
    droppedLine = `Drops ${list}, with their data and selections.`;
  }
  return { rows, droppedLine };
}

const DATE_ROWS = [
  ["Origin Start", "origin_start_date", "originStartDate"],
  ["Origin End", "origin_end_date", "originEndDate"],
  ["Development End", "development_end_date", "developmentEndDate"],
];

/**
 * The confirmation's before-and-after table: one row per date, `changed`
 * when the new month differs from the saved one.
 */
export function describeProjectDatesMove(before, after) {
  return DATE_ROWS.map(([label, snake, camel]) => {
    const old = displayMonth(before?.[snake] ?? before?.[camel]);
    const next = displayMonth(after?.[snake] ?? after?.[camel]);
    return { label, before: old, after: next, changed: !!old && old !== next };
  });
}

// Group headings for the reasons the job writes (period_reshape.py and
// project_dates_jobs.py); an unknown reason shows as written.
const REVIEW_HEADINGS = new Map([
  ["hand-entered or imported", "Hand-Entered Datasets"],
  ["has cell links", "Cell Links"],
  ["dropped origins held data", "Dropped Origins Held Data"],
  ["periods moved to the new dates", "Reshaped Methods"],
  ["could not be reshaped", "Not Reshaped"],
  ["origin labels do not match the project dates; not reshaped", "Labels Off The Project Dates"],
]);
export const PROBLEM_GROUP = "Could Not Refresh";

function reviewHeading(reason) {
  const text = String(reason || "").trim();
  return REVIEW_HEADINGS.get(text.toLowerCase()) || (text.charAt(0).toUpperCase() + text.slice(1));
}

function splitOnce(text) {
  const value = String(text || "");
  const cut = value.indexOf(": ");
  return cut < 0 ? [value, ""] : [value.slice(0, cut), value.slice(cut + 2)];
}

/** One job problem line, `"<class>: <name>: <reason>"`, as a review row. */
function problemRow(line) {
  const [reservingClass, rest] = splitOnce(line);
  if (!rest) return { reservingClass: "", name: "", reason: line, detail: line, open: null };
  const [name, reason] = splitOnce(rest);
  return reason
    ? { reservingClass, name, reason, detail: line, open: null }
    : { reservingClass, name: "", reason: rest, detail: line, open: null };
}

/**
 * Summarize a finished change for the status line and the panel.
 *
 * `text` is one short line. `groups` is the review list grouped by reason,
 * with the refresh problems first as their own group. A review row carries
 * `open`, what the project tree would open; a problem row names its dependent
 * only by text, so it opens nothing. `rerun` says whether running the same
 * change again can still help (the job kept its unfinished-change record).
 */
export function describeProjectDatesResult(result, message = "") {
  const outcome = result && typeof result === "object" ? result : {};
  const review = (Array.isArray(outcome.review) ? outcome.review : [])
    .filter((item) => item && typeof item === "object" && String(item.name || "").trim())
    .map((item) => ({
      reservingClass: String(item.reserving_class || "").trim(),
      name: String(item.name || "").trim(),
      kind: String(item.kind || "").trim(),
      methodType: String(item.method_type || "").trim(),
      reasons: (Array.isArray(item.reasons) ? item.reasons : []).map((reason) => String(reason || "").trim()).filter(Boolean),
    }));
  const lines = (value) => (Array.isArray(value) ? value : []).map((item) => String(item || "").trim()).filter(Boolean);
  const dependentProblems = lines(outcome.dependent_problems);
  // A class's walk failure repeats its first dependent problem, maybe with "(+N more)".
  const listed = new Set(dependentProblems);
  const otherFailures = lines(outcome.failures)
    .filter((line) => !listed.has(line.replace(/ \(\+\d+ more\)$/u, "")));
  const problems = [...otherFailures, ...dependentProblems].map(problemRow);

  const groups = [];
  if (problems.length) groups.push({ heading: PROBLEM_GROUP, problem: true, rows: problems });
  const byHeading = new Map();
  for (const item of review) {
    // The last reason is the most specific; hover shows every one.
    const heading = reviewHeading(item.reasons[item.reasons.length - 1] || "");
    if (!byHeading.has(heading)) byHeading.set(heading, []);
    const reason = item.reasons.join("; ");
    byHeading.get(heading).push({
      reservingClass: item.reservingClass,
      name: item.name,
      reason,
      detail: `${[item.reservingClass, item.name].filter(Boolean).join("\\")}${reason ? ` — ${reason}` : ""}`,
      open: item.reservingClass
        ? { reservingClass: item.reservingClass, name: item.name, methodType: item.methodType }
        : null,
    });
  }
  [...byHeading.entries()]
    .sort((a, b) => b[1].length - a[1].length)
    .forEach(([heading, rows]) => groups.push({ heading, problem: false, rows }));

  const failed = problems.length > 0;
  let text;
  if (outcome.unchanged) {
    text = "The project already has these dates.";
  } else if (failed) {
    const datasetsFailed = Math.max(0, Number(outcome.datasets_failed) || 0);
    text = datasetsFailed === problems.length
      ? `Saved. ${plural(datasetsFailed, "dataset")} could not refresh.`
      : `Saved. ${plural(problems.length, "item")} could not refresh.`;
  } else if (String(message || "").trim()) {
    text = String(message).trim();
  } else {
    const datasets = (Number(outcome.datasets_regenerated) || 0) + (Number(outcome.datasets_reshaped) || 0);
    const methods = (Number(outcome.methods_updated) || 0) + (Number(outcome.methods_reshaped) || 0);
    text = `Project dates changed. Refreshed ${plural(datasets, "dataset")} and ${plural(methods, "method")} `
      + `in ${count(outcome.classes_refreshed)} of ${plural(outcome.classes_total, "reserving class", "reserving classes")}.`;
  }
  return { text, review, groups, failed, rerun: failed && !!outcome.rerun_needed };
}

/**
 * The shell message that opens a review row the way the project tree does:
 * the project's Project Instance tab, on the row's reserving class, with that
 * dataset or method window open.
 */
export function projectInstanceOpenMessage(project, target) {
  const methodType = String(target?.methodType || "").trim();
  const key = methodType.toLowerCase();
  const kind = key === "dfm" ? "dfm" : key === "result selection" ? "result_selection" : "dataset";
  const entry = { kind, name: String(target?.name || "").trim(), active: true };
  if (methodType && key !== "none") entry.methodType = methodType;
  return {
    type: "arcrho:open-project-instance",
    project: {
      name: String(project?.name || "").trim(),
      folder: String(project?.folder || "").trim(),
      projectInstanceState: {
        selectedPath: String(target?.reservingClass || "").trim(),
        windows: [entry],
      },
    },
  };
}

/** The band's text while a change runs: "Changing dates… 12 of 33". */
export function projectDatesBandProgress(progress) {
  const total = Math.max(0, Number(progress?.total) || 0);
  const completed = Math.max(0, Number(progress?.completed) || 0);
  return progress?.stage === "classes" && total > 0
    ? `Changing dates… ${count(Math.min(completed, total))} of ${count(total)}`
    : "Changing dates…";
}

async function readResponseError(response) {
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

/**
 * Poll one submitted dates change until the Engine reports a terminal state.
 *
 * Resolves with the terminal status, whose `result` is the job's summary and
 * whose `message` says how to finish a change that fell short. A change the
 * Engine refused rejects with code `PROJECT_DATES_JOB_ERROR` and the HTTP
 * `statusCode` the job recorded.
 */
export async function waitForProjectDatesJob({
  fetchImpl,
  projectName,
  jobId,
  onProgress = () => {},
  waitForPoll = (delayMs) => new Promise((resolve) => globalThis.setTimeout(resolve, delayMs)),
  pollIntervalMs = POLL_INTERVAL_MS,
  maxStatusRetries = MAX_STATUS_RETRIES,
  staleStatusMs = STALE_STATUS_MS,
  queuedStaleStatusMs = QUEUED_STALE_STATUS_MS,
  now = () => Date.now(),
}) {
  const statusUrl = projectDatesJobStatusUrl(projectName, jobId);
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
      if (response) lastFailure = await readResponseError(response);
      consecutiveFailures += 1;
      if (consecutiveFailures > maxStatusRetries) {
        throw codedError(
          "PROJECT_DATES_STATUS_UNAVAILABLE",
          `The dates change status is unavailable after repeated checks. Job "${jobId}" may still be running on Arco Engine.${lastFailure ? ` Last error: ${lastFailure}` : ""}`,
        );
      }
      onProgress({ stage: "", label: "Waiting for the dates change status...", completed: 0, total: 0 });
      await waitForPoll(pollIntervalMs);
      continue;
    }
    if (!response.ok) {
      const detail = await readResponseError(response);
      if (response.status === 404) {
        throw codedError("PROJECT_DATES_STATUS_NOT_FOUND", `The dates change status was not found (${detail}).`);
      }
      throw new Error(`The dates change status check failed: ${detail}`);
    }

    consecutiveFailures = 0;
    const result = await response.json();
    const progress = result?.progress || {};
    const total = Math.max(0, Number(progress.total) || 0);
    const completed = Math.max(0, Number(progress.completed) || 0);
    onProgress({
      stage: String(progress.stage || "").trim(),
      label: String(progress.label || progress.stage || "Changing the project dates...").trim(),
      completed,
      total,
    });

    const status = String(result?.status || "").trim().toLowerCase();
    if (SUCCESS_STATUSES.has(status)) return result;
    if (ERROR_STATUSES.has(status)) {
      throw codedError(
        "PROJECT_DATES_JOB_ERROR",
        String(result.message || "The project dates change failed."),
        Number(result.status_code) || 0,
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
        "PROJECT_DATES_STATUS_STALE",
        `The dates change has stopped reporting progress. Job "${jobId}" appears to have stalled on Arco Engine. Run the same change again to finish it.`,
      );
    }
    await waitForPoll(pollIntervalMs);
  }
}
