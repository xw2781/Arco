// Thirty-day retention for the log files the Electron host writes.
//
// The host opens a new file per app launch and ArcBot opens one per request,
// so nothing here is ever overwritten and a machine kept every log it had ever
// produced. The rule itself is owned by
// python-api/src/arcrho_log_retention_contract.py; this is the host's mirror of
// it, because JavaScript cannot import the Python module, and
// frontend/tests/log_retention.test.mjs pins the two together.
//
// Retention never fails a launch: every error is swallowed, so a locked file
// only leaves an old log behind.
const fs = require("fs");
const path = require("path");

const LOG_RETENTION_DAYS = 30;
const LOG_FILE_SUFFIXES = [".log", ".jsonl"];

function isLogName(name, suffixes) {
  const lastDot = name.lastIndexOf(".");
  const tail = lastDot < 0 ? "" : name.slice(lastDot + 1);
  const base = tail && /^\d+$/.test(tail) ? name.slice(0, lastDot) : name;
  const lowered = base.toLowerCase();
  return suffixes.some((suffix) => lowered.endsWith(suffix));
}

// Deletes every log file in the directory last written before the cutoff and
// returns how many went. Returns 0 for a directory that does not exist yet.
function pruneAgedLogFiles(directory, { suffixes = LOG_FILE_SUFFIXES, days = LOG_RETENTION_DAYS, now = null } = {}) {
  const lowered = suffixes.map((suffix) => String(suffix).toLowerCase());
  const cutoff = (now === null ? Date.now() : now) - days * 86400000;
  let entries = [];
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch {
    return 0;
  }
  let removed = 0;
  for (const entry of entries) {
    try {
      if (!entry.isFile() || !isLogName(entry.name, lowered)) continue;
      const filePath = path.join(directory, entry.name);
      if (fs.statSync(filePath).mtimeMs >= cutoff) continue;
      fs.unlinkSync(filePath);
      removed += 1;
    } catch {
      continue;
    }
  }
  return removed;
}

// Every host log line starts with an ISO timestamp; a short window keeps a date
// mentioned later in a message from counting as the line's own.
const DATE_PATTERN = /\d{4}-\d{2}-\d{2}/;
const DATE_SEARCH_WINDOW = 64;

function localDateText(timestampMs) {
  const date = new Date(timestampMs);
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Drops the leading lines of a log appended under a fixed name that predate the
// cutoff and returns how many went. A line with no date near its start (a
// stack trace) shares the fate of the dated line above it, and a log with no
// dated line at all is left alone.
function trimAgedLogLines(filePath, { days = LOG_RETENTION_DAYS, now = null } = {}) {
  const cutoff = localDateText((now === null ? Date.now() : now) - days * 86400000);
  let text = "";
  try {
    text = fs.readFileSync(filePath, "utf8");
  } catch {
    return 0;
  }
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) || [];
  let keepFrom = null;
  let datedLineSeen = false;
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].slice(0, DATE_SEARCH_WINDOW).match(DATE_PATTERN);
    if (!match) continue;
    datedLineSeen = true;
    if (match[0] >= cutoff) {
      keepFrom = index;
      break;
    }
  }
  if (!datedLineSeen) return 0;
  if (keepFrom === null) keepFrom = lines.length;
  if (keepFrom === 0) return 0;

  const temporary = `${filePath}.trim`;
  try {
    fs.writeFileSync(temporary, lines.slice(keepFrom).join(""), "utf8");
    fs.renameSync(temporary, filePath);
  } catch {
    try {
      fs.unlinkSync(temporary);
    } catch {}
    return 0;
  }
  return keepFrom;
}

module.exports = {
  LOG_RETENTION_DAYS,
  LOG_FILE_SUFFIXES,
  pruneAgedLogFiles,
  trimAgedLogLines,
};
