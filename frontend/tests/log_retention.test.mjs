// The Electron host mirrors the retention rule that
// python-api/src/arcrho_log_retention_contract.py owns, because JavaScript
// cannot import it. These tests pin the mirror to that file and cover the
// pruning the host does at launch.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { LOG_RETENTION_DAYS, pruneAgedLogFiles, trimAgedLogLines } = require("../electron/log_retention.js");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONTRACT_PATH = path.join(HERE, "..", "..", "python-api", "src", "arcrho_log_retention_contract.py");
const DAY_MS = 86400000;

const makeLog = (directory, name, ageDays) => {
  const filePath = path.join(directory, name);
  writeFileSync(filePath, "line\n", "utf8");
  const seconds = (Date.now() - ageDays * DAY_MS) / 1000;
  utimesSync(filePath, seconds, seconds);
  return filePath;
};

// Temporary files stay inside the repository, as the repository's validation
// rules require.
const withTempDirectory = (run) => {
  const directory = mkdtempSync(path.join(HERE, "log-retention-"));
  try {
    run(directory);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
};

test("the host keeps the same retention window as the Python contract", () => {
  const contract = readFileSync(CONTRACT_PATH, "utf8");
  const match = contract.match(/^LOG_RETENTION_DAYS\s*=\s*(\d+)$/m);
  assert.ok(match, "the contract defines LOG_RETENTION_DAYS");
  assert.equal(LOG_RETENTION_DAYS, Number(match[1]));
});

test("pruning drops the logs older than the window and keeps the rest", () => {
  withTempDirectory((directory) => {
    makeLog(directory, "electron-main-fresh.log", 1);
    makeLog(directory, "electron-main-edge.log", 29);
    makeLog(directory, "arcrho-server-old.log", 31);

    assert.equal(pruneAgedLogFiles(directory), 1);
    assert.deepEqual(
      readdirSync(directory).sort(),
      ["electron-main-edge.log", "electron-main-fresh.log"],
    );
  });
});

test("pruning covers rotated backups and leaves anything that is not a log", () => {
  withTempDirectory((directory) => {
    makeLog(directory, "gateway.log.1", 40);
    makeLog(directory, "notes.txt", 40);

    pruneAgedLogFiles(directory);

    assert.deepEqual(readdirSync(directory), ["notes.txt"]);
  });
});

test("ArcBot request logs prune by their own suffix", () => {
  withTempDirectory((directory) => {
    makeLog(directory, "2026-07-01_request.json", 40);

    assert.equal(pruneAgedLogFiles(directory), 0);
    assert.equal(pruneAgedLogFiles(directory, { suffixes: [".json"] }), 1);
  });
});

test("trimming drops the aged leading lines of a fixed-name log with their stack traces", () => {
  withTempDirectory((directory) => {
    const filePath = path.join(directory, "update.log");
    const old = new Date(Date.now() - 40 * DAY_MS).toISOString();
    const fresh = new Date(Date.now() - DAY_MS).toISOString();
    writeFileSync(filePath, `[${old}] old failure\nError: boom\n    at stack\n[${fresh}] fresh line\n`, "utf8");

    assert.equal(trimAgedLogLines(filePath), 3);
    assert.equal(readFileSync(filePath, "utf8"), `[${fresh}] fresh line\n`);
    assert.equal(trimAgedLogLines(filePath), 0);
  });
});

test("trimming leaves a log with no dated line, and a missing log, alone", () => {
  withTempDirectory((directory) => {
    const filePath = path.join(directory, "update.log");
    writeFileSync(filePath, "no date here\n", "utf8");

    assert.equal(trimAgedLogLines(filePath), 0);
    assert.equal(readFileSync(filePath, "utf8"), "no date here\n");
    assert.equal(trimAgedLogLines(path.join(directory, "absent.log")), 0);
  });
});

test("a directory that does not exist prunes nothing", () => {
  assert.equal(pruneAgedLogFiles(path.join(HERE, "absent-log-directory")), 0);
});
