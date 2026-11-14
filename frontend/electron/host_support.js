// Shared host-process utilities: logging, timing, JSON save formatting.
const { app } = require("electron");
const { execFile } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { formatJsonForSave } = require("./persisted_json_text");
const { pruneAgedLogFiles } = require("./log_retention");
const { isProcessAlive } = require("./backend_port");
const { profileDir } = require("./local_folders");

let electronLogPath = "";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getTimestampForFileName() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}


// The host log and the app-server log share this folder, so pruning it once
// per launch — this path is resolved once and remembered — covers both.
function getElectronLogPath() {
  if (electronLogPath) return electronLogPath;
  try {
    const logDir = path.join(app.getPath("userData"), "logs");
    fs.mkdirSync(logDir, { recursive: true });
    pruneAgedLogFiles(logDir);
    electronLogPath = path.join(logDir, `electron-main-${getTimestampForFileName()}.log`);
  } catch {
    const fallbackDir = path.join(profileDir(), "logs");
    fs.mkdirSync(fallbackDir, { recursive: true });
    pruneAgedLogFiles(fallbackDir);
    electronLogPath = path.join(fallbackDir, `electron-main-${getTimestampForFileName()}.log`);
  }
  return electronLogPath;
}

function formatErrorForLog(err) {
  if (!err) return "";
  if (err instanceof Error) return err.stack || err.message || String(err);
  return String(err);
}

function appendElectronLog(message, err = null) {
  try {
    const lines = [`[${new Date().toISOString()}] ${message}`];
    if (err) lines.push(formatErrorForLog(err));
    fs.appendFileSync(getElectronLogPath(), `${lines.join("\n")}\n`, "utf8");
  } catch {}
}

process.on("uncaughtException", (err) => {
  appendElectronLog("Uncaught exception", err);
});

process.on("unhandledRejection", (reason) => {
  appendElectronLog("Unhandled promise rejection", reason);
});

function withTimeout(promise, timeoutMs, label) {
  let timeoutId = null;
  const timeout = new Promise((_, reject) => {
    timeoutId = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timeoutId) clearTimeout(timeoutId);
  });
}

function execFileAsync(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

module.exports = {
  sleep,
  getTimestampForFileName,
  formatJsonForSave,
  getElectronLogPath,
  formatErrorForLog,
  appendElectronLog,
  withTimeout,
  execFileAsync,
  isProcessAlive,
};
