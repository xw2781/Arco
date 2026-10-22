import assert from "node:assert/strict";
import crypto from "node:crypto";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import Module from "node:module";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const userDataDir = fs.mkdtempSync(path.join(TESTS_DIR, "electron-host-modules-"));
const downloadsDir = fs.mkdtempSync(path.join(TESTS_DIR, "electron-host-downloads-"));
test.after(() => {
  fs.rmSync(userDataDir, { recursive: true, force: true });
  fs.rmSync(downloadsDir, { recursive: true, force: true });
});

const electronStub = {
  app: {
    getPath: (name) => (name === "downloads" ? downloadsDir : userDataDir),
    getVersion: () => "0.0.1",
    getName: () => "ArcRho",
    isPackaged: false,
    quit: () => {},
    exit: () => {},
  },
  dialog: {
    showMessageBox: async () => ({ response: 1 }),
  },
};

const originalLoad = Module._load;
Module._load = function patchedLoad(request, ...rest) {
  if (request === "electron") return electronStub;
  return originalLoad.call(this, request, ...rest);
};
test.after(() => {
  Module._load = originalLoad;
});

const require = createRequire(import.meta.url);
const hostSupport = require("../electron/host_support.js");
const updateChecker = require("../electron/update_checker.js");
const backendLifecycle = require("../electron/backend_lifecycle.js");

test("host_support exports work outside the update/backend modules", async () => {
  assert.equal(typeof hostSupport.sleep, "function");
  await hostSupport.sleep(1);
  assert.match(hostSupport.getTimestampForFileName(), /^\d{4}-\d{2}-\d{2}T/);
  const text = hostSupport.formatJsonForSave({ rows: [[1, 2], [3, 4]], name: "x" });
  assert.ok(text.endsWith("\n"));
  assert.deepEqual(JSON.parse(text), { rows: [[1, 2], [3, 4]], name: "x" });
  assert.equal(await hostSupport.withTimeout(Promise.resolve("ok"), 500, "test"), "ok");
  assert.equal(hostSupport.isProcessAlive(process.pid), true);
  assert.equal(hostSupport.isProcessAlive(0), false);
  hostSupport.appendElectronLog("electron host module test entry");
  assert.ok(fs.existsSync(hostSupport.getElectronLogPath()));
});

test("update_checker initializes and reports development mode for unpackaged apps", async () => {
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null });
  const result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  assert.deepEqual(result, { status: "development" });
});

// The release channel file owns the feed location, so the stubs match its asset
// name rather than restating the repository.
const FEED_URL_RE = /\/releases\/download\/update-feed\/Arco-update\.json$/;
const isFeedUrl = (url) => FEED_URL_RE.test(String(url));

function feedEntry(version, body = "", publishedAt = "2026-08-01T00:00:00Z") {
  return { version, publishedAt, body };
}

function feedFixture(releases, sha256 = "a".repeat(64)) {
  const [latest] = releases;
  return {
    product: "Arco",
    version: latest.version,
    installer: `Arco-Setup-${latest.version}.exe`,
    url: `https://dl.example/Arco-Setup-${latest.version}.exe`,
    sha256,
    releases,
  };
}

function feedResponse(manifest) {
  return { ok: true, status: 200, json: async () => manifest };
}

test("update_checker reports up to date when the feed's version does not beat the current one", async () => {
  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  const fetchStub = async (url) => {
    assert.ok(isFeedUrl(url), `the check reads only the update feed, got ${url}`);
    return feedResponse(feedFixture([feedEntry("0.0.1")]));
  };
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null, fetchImpl: fetchStub });
  const result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
  assert.deepEqual(result, { status: "none" });
});

test("update_checker reports the update location unavailable when the feed request fails", async () => {
  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  const fetchStub = async () => ({ ok: false, status: 404 });
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null, fetchImpl: fetchStub });
  const result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
  assert.deepEqual(result, { status: "unavailable" });

  const log = fs.readFileSync(path.join(path.dirname(hostSupport.getElectronLogPath()), "update.log"), "utf8");
  assert.match(log, /Check failed after \d+ ms\n.*status 404/, "a failed check is written to update.log");
});

test("update_checker shows only user-facing release notes as plain text", async () => {
  const body = [
    "# Release 0.0.2",
    "",
    "Released on 2026-08-10.",
    "",
    "## User-Facing Changes",
    "",
    "### Improvements",
    "- **installer**: ArcRho setup now defaults to a per-user install folder.",
    "  - Fresh installs default to `E:\\<Windows login>\\ArcRho`.",
    "",
    "### Fixes",
    "- **dataset**: Add > Dataset can now save without editing a cell first.",
    "",
    "## Internal Notes",
    "",
    "- **build**: The packaged build no longer kills makensis part-way through.",
    "",
    "## Fragment Sources",
    "",
    "- `changes/unreleased/2026-08-10-example.json`",
    "",
  ].join("\n");

  const fetchStub = async (url) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.2", body)]));
    throw new Error(`Unexpected fetch URL in test: ${url}`);
  };

  let detail = "";
  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  electronStub.dialog.showMessageBox = async (winOrOptions, maybeOptions) => {
    const options = maybeOptions || winOrOptions || {};
    if ((options.buttons || []).includes("Update now")) detail = String(options.detail || "");
    return { response: 1 };
  };

  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  const fakeWin = { isDestroyed: () => false, webContents: { send: () => {}, executeJavaScript: async () => true } };
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => fakeWin, fetchImpl: fetchStub });
  let result;
  try {
    result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  } finally {
    delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
    electronStub.dialog.showMessageBox = originalShowMessageBox;
  }

  assert.equal(result.status, "deferred");
  assert.match(detail, /^Improvements$/m);
  assert.match(detail, /• installer: ArcRho setup now defaults to a per-user install folder\./);
  assert.match(detail, /^Fixes$/m);
  assert.doesNotMatch(detail, /User-Facing Changes|Internal Notes|Fragment Sources/);
  assert.doesNotMatch(detail, /makensis/, "internal notes must not reach the update dialog");
  assert.doesNotMatch(detail, /[*#`]|^Released on/m, "the dialog must not show markdown syntax");
  assert.doesNotMatch(detail, /Fresh installs/, "per-change detail bullets are dropped to bound the dialog height");
  assert.ok(detail.split("\n").length <= 14, `update dialog detail must stay short, got:\n${detail}`);
});

test("update_checker downloads a newer release with progress events and rejects a bad checksum", async () => {
  const installerContent = Buffer.from("fake-installer-bytes-for-test");
  const wrongSha256 = crypto.createHash("sha256").update("not-the-installer").digest("hex");

  async function* bodyChunks() {
    yield installerContent.subarray(0, 10);
    yield installerContent.subarray(10);
  }

  const fetchStub = async (url) => {
    const target = String(url);
    if (isFeedUrl(target)) {
      return feedResponse(feedFixture([feedEntry("0.0.2", "Release notes\nmandatory: true")], wrongSha256));
    }
    if (target.endsWith(".exe")) {
      return {
        ok: true,
        headers: { get: (name) => (name === "content-length" ? String(installerContent.length) : null) },
        body: bodyChunks(),
      };
    }
    throw new Error(`Unexpected fetch URL in test: ${target}`);
  };

  // The progress goes to the host's update window, never to the main window.
  const hostCalls = [];
  const updateHost = {
    begin: () => hostCalls.push(["begin"]),
    progress: (percent, text) => hostCalls.push(["progress", percent, text]),
    cancel: () => hostCalls.push(["cancel"]),
    shutdown: async () => hostCalls.push(["shutdown"]),
    exit: () => hostCalls.push(["exit"]),
  };
  const fakeWin = {
    isDestroyed: () => false,
    webContents: {
      send: () => assert.fail("the main window must not receive update progress"),
      executeJavaScript: async () => true,
    },
  };

  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  electronStub.dialog.showMessageBox = async (winOrOptions, maybeOptions) => {
    const options = maybeOptions || winOrOptions || {};
    return (options.buttons || []).includes("Update now") ? { response: 0 } : { response: 1 };
  };

  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => fakeWin, updateHost, fetchImpl: fetchStub });
  let result;
  try {
    result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  } finally {
    delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
    electronStub.dialog.showMessageBox = originalShowMessageBox;
  }

  assert.equal(result.status, "verification-failed");
  assert.equal(result.version, "0.0.2");
  assert.deepEqual(hostCalls.map((call) => call[0]), ["begin", "progress", "progress", "progress", "progress", "cancel"]);
  const [, first, second, third, verifying] = hostCalls;
  assert.deepEqual(first, ["progress", 0, "Downloading Arco 0.0.2... 0.0 MB / 0.0 MB"]);
  // The bar moves on every chunk; the caption is refreshed at most once a second.
  assert.deepEqual(second, ["progress", 34, undefined]);
  assert.deepEqual(third, ["progress", 100, undefined]);
  assert.deepEqual(verifying, ["progress", 100, "Verifying the download..."]);
  assert.ok(!hostCalls.some((call) => call[0] === "shutdown" || call[0] === "exit"),
    "a failed verification must leave the app running");

  const downloadedPath = path.join(downloadsDir, "Arco-Setup-0.0.2.exe");
  assert.ok(!fs.existsSync(downloadedPath), "a failed checksum verification must delete the downloaded installer");
  assert.ok(!fs.existsSync(`${downloadedPath}.part`), "no partial download may be left in the Downloads folder");
});

// The host asks the renderer for a choice by evaluating a snippet in the page.
// Running that snippet against a stub window is what a real renderer does, so the
// test covers the serialization the main process actually performs.
function rendererWindow({ onUpdatePayload = () => {}, choice = null } = {}) {
  return {
    isDestroyed: () => false,
    webContents: {
      send: () => {},
      executeJavaScript: async (code) => {
        const pageWindow = choice === null ? {} : {
          __arcrho_show_update_dialog: (payload) => {
            onUpdatePayload(payload);
            return { choice };
          },
        };
        return new Function("window", `return (${code});`)(pageWindow);
      },
    },
  };
}

function skippedReleaseFixture() {
  const notes = (version, extra = "") => [
    `# Release ${version}`,
    "",
    `Released on 2026-08-1${version.at(-1)}.`,
    "",
    "## User-Facing Changes",
    "",
    "### Improvements",
    `- **dataset**: Change shipped in ${version}.`,
    `  - Detail bullet for ${version}.`,
    extra,
    "",
    "## Internal Notes",
    "",
    `- **build**: makensis note for ${version}.`,
    "",
  ].filter((line) => line !== "").join("\n");

  return feedFixture([
    feedEntry("0.0.4", notes("0.0.4")),
    feedEntry("0.0.3", notes("0.0.3")),
    feedEntry("0.0.2", `${notes("0.0.2")}\nmandatory: true`),
    feedEntry("0.0.1", notes("0.0.1")),
  ], "b".repeat(64));
}

async function runSkippedVersionCheck(win) {
  const fetchStub = async (url) => {
    if (isFeedUrl(url)) return feedResponse(skippedReleaseFixture());
    throw new Error(`Unexpected fetch URL in test: ${url}`);
  };
  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  updateChecker.initUpdateChecker({
    appMode: "arcrho",
    getMainWindow: () => win,
    fetchImpl: fetchStub,
    downloadRetryDelaysMs: [],
  });
  try {
    return await updateChecker.checkForUpdate({ showNoUpdate: false });
  } finally {
    delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
  }
}

test("update_checker sends every skipped version's notes to the in-app dialog", async () => {
  let payload = null;
  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  let nativeBoxShown = false;
  electronStub.dialog.showMessageBox = async (...args) => {
    nativeBoxShown = true;
    return originalShowMessageBox(...args);
  };

  let result;
  try {
    result = await runSkippedVersionCheck(rendererWindow({
      onUpdatePayload: (value) => { payload = value; },
      choice: "later",
    }));
  } finally {
    electronStub.dialog.showMessageBox = originalShowMessageBox;
  }

  assert.equal(result.status, "deferred");
  assert.equal(result.version, "0.0.4");
  assert.equal(nativeBoxShown, false, "the in-app dialog replaces the native message box");

  assert.equal(payload.mode, "update");
  assert.equal(payload.currentVersion, "0.0.1");
  assert.equal(payload.version, "0.0.4");
  assert.deepEqual(
    payload.releases.map((release) => release.version),
    ["0.0.4", "0.0.3", "0.0.2"],
    "a 0.0.1 -> 0.0.4 jump must carry the notes for 0.0.3 and 0.0.2 the user never saw"
  );

  const flattened = JSON.stringify(payload.releases);
  assert.match(flattened, /Change shipped in 0\.0\.3/);
  assert.match(flattened, /Detail bullet for 0\.0\.4/, "the scrollable dialog keeps per-change detail bullets");
  assert.doesNotMatch(flattened, /makensis/, "internal notes must not reach the update dialog");
  assert.doesNotMatch(flattened, /Released on/, "the released-on line is carried as a field, not a note");
  assert.equal(payload.releases[0].releasedOn, "2026-08-14");
  assert.ok(payload.releases[0].entries.some((entry) => entry.kind === "nested"));
  assert.ok(payload.mandatory, "a mandatory marker on a skipped version still applies to this update");
});

test("update_checker accepts the in-app dialog's update choice", async () => {
  const result = await runSkippedVersionCheck(rendererWindow({ choice: "update" }));
  // The download runs against a stub checksum that cannot match the payload.
  assert.equal(result.status, "download-failed");
  assert.equal(result.version, "0.0.4");
});

test("update_checker falls back to the native prompt when the renderer cannot answer", async () => {
  let detail = "";
  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  electronStub.dialog.showMessageBox = async (winOrOptions, maybeOptions) => {
    const options = maybeOptions || winOrOptions || {};
    if ((options.buttons || []).includes("Update now")) detail = String(options.detail || "");
    return { response: 1 };
  };

  let result;
  try {
    result = await runSkippedVersionCheck(rendererWindow({ choice: null }));
  } finally {
    electronStub.dialog.showMessageBox = originalShowMessageBox;
  }

  assert.equal(result.status, "deferred");
  assert.match(detail, /Available version: 0\.0\.4/);
  assert.match(detail, /Also includes 0\.0\.3, 0\.0\.2\./);
  assert.doesNotMatch(detail, /Detail bullet/, "a native box cannot scroll, so detail bullets stay out of it");
  assert.doesNotMatch(detail, /makensis/);
});

test("update_checker reads the release notes bundled with the installed build", async () => {
  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null });
  const history = await updateChecker.readLocalReleaseHistory();

  assert.equal(history.mode, "history");
  assert.equal(history.available, true, "every build ships frontend/docs/releases");
  assert.ok(history.releases.length > 1);
  assert.match(history.releasesUrl, /^https:\/\/github\.com\/.+\/releases$/);

  const versions = history.releases.map((release) => release.version);
  assert.deepEqual(
    versions,
    [...versions].sort((left, right) => {
      const parse = (value) => value.split(".").map(Number);
      const [leftParts, rightParts] = [parse(right), parse(left)];
      return leftParts[0] - rightParts[0] || leftParts[1] - rightParts[1] || leftParts[2] - rightParts[2];
    }),
    "the history reads newest first"
  );
  assert.ok(history.releases.every((release) => Array.isArray(release.entries)));
  assert.doesNotMatch(JSON.stringify(history.releases), /Fragment Sources/);
});

test("update_checker deletes the installer recorded for cleanup and legacy update downloads", async () => {
  const installerPath = path.join(downloadsDir, "Arco-Setup-0.0.3.exe");
  fs.writeFileSync(installerPath, "completed installer");
  const markerPath = path.join(userDataDir, "pending_update_cleanup.json");
  fs.writeFileSync(markerPath, JSON.stringify({ installerPath, version: "0.0.3" }));
  const legacyDir = path.join(userDataDir, "updates");
  fs.mkdirSync(legacyDir, { recursive: true });
  fs.writeFileSync(path.join(legacyDir, "Arco-Setup-0.0.2.exe"), "old installer");
  fs.writeFileSync(path.join(legacyDir, "Arco-Setup-0.0.2.exe.part"), "old partial");

  updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null });
  const result = await updateChecker.cleanupCompletedUpdateInstaller();

  assert.equal(result.status, "removed");
  assert.ok(!fs.existsSync(installerPath), "the installer that produced this launch must be deleted");
  assert.ok(!fs.existsSync(markerPath), "the cleanup marker must not survive a successful cleanup");
  assert.ok(!fs.existsSync(legacyDir), "the legacy user-data updates folder must be removed once it is empty");

  assert.deepEqual(await updateChecker.cleanupCompletedUpdateInstaller(), { status: "none" });
});

test("update_checker retries a busy installer launch and records the cleanup marker", async () => {
  const installerContent = Buffer.from("retry-installer-bytes");
  const sha256 = crypto.createHash("sha256").update(installerContent).digest("hex");

  async function* bodyChunks() {
    yield installerContent;
  }

  const fetchStub = async (url) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.4")], sha256));
    return {
      ok: true,
      status: 200,
      headers: { get: (name) => (name === "content-length" ? String(installerContent.length) : null) },
      body: bodyChunks(),
    };
  };

  // Windows reports a busy installer either way: spawn() throws EBUSY
  // synchronously, while other launch failures arrive as an "error" event.
  const spawnCalls = [];
  const sequence = [];
  const spawnStub = (command, args) => {
    spawnCalls.push({ command, args });
    sequence.push("spawn");
    const busy = Object.assign(new Error("spawn EBUSY"), { code: "EBUSY" });
    if (spawnCalls.length === 1) throw busy;
    const child = new EventEmitter();
    child.unref = () => {};
    setImmediate(() => child.emit(spawnCalls.length === 2 ? "error" : "spawn", spawnCalls.length === 2 ? busy : undefined));
    return child;
  };

  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  electronStub.dialog.showMessageBox = async (winOrOptions, maybeOptions) => {
    const options = maybeOptions || winOrOptions || {};
    return (options.buttons || []).includes("Update now") ? { response: 0 } : { response: 1 };
  };

  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  const fakeWin = { isDestroyed: () => false, webContents: { send: () => {}, executeJavaScript: async () => true } };
  const updateHost = {
    begin: () => sequence.push("begin"),
    progress: () => {},
    cancel: () => sequence.push("cancel"),
    shutdown: async () => sequence.push("shutdown"),
    exit: () => sequence.push("exit"),
  };
  updateChecker.initUpdateChecker({
    appMode: "arcrho",
    getMainWindow: () => fakeWin,
    updateHost,
    fetchImpl: fetchStub,
    spawnImpl: spawnStub,
  });
  let result;
  try {
    result = await updateChecker.checkForUpdate({ showNoUpdate: false });
  } finally {
    delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
    electronStub.dialog.showMessageBox = originalShowMessageBox;
    updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null });
  }

  assert.deepEqual(result, { status: "launching", version: "0.0.4" });
  assert.equal(spawnCalls.length, 3, "a busy launch must be retried rather than reported to the user");
  // The app is closed before setup starts, and the process ends only after
  // setup is running; the main window is never brought back on this path.
  assert.deepEqual(sequence, ["begin", "shutdown", "spawn", "spawn", "spawn", "exit"]);
  assert.ok(spawnCalls.every((call) => call.args[0] === "--updated"),
    "setup started by the app must run as an update");

  const installerPath = path.join(downloadsDir, "Arco-Setup-0.0.4.exe");
  assert.ok(fs.existsSync(installerPath), "a launched installer stays until the next launch deletes it");
  const marker = JSON.parse(fs.readFileSync(path.join(userDataDir, "pending_update_cleanup.json"), "utf8"));
  assert.deepEqual(marker, { installerPath, version: "0.0.4" });

  assert.equal((await updateChecker.cleanupCompletedUpdateInstaller()).status, "removed");
  assert.ok(!fs.existsSync(installerPath));
});

function launchingSpawnStub() {
  return () => {
    const child = new EventEmitter();
    child.unref = () => {};
    setImmediate(() => child.emit("spawn"));
    return child;
  };
}

const acceptingUpdateHost = () => ({
  begin: () => {},
  progress: () => {},
  cancel: () => {},
  shutdown: async () => {},
  exit: () => {},
});

async function runAcceptedUpdate(fetchStub, options = {}) {
  const originalShowMessageBox = electronStub.dialog.showMessageBox;
  const dialogs = [];
  electronStub.dialog.showMessageBox = async (winOrOptions, maybeOptions) => {
    const dialogOptions = maybeOptions || winOrOptions || {};
    dialogs.push(dialogOptions);
    return (dialogOptions.buttons || []).includes("Update now") ? { response: 0 } : { response: 1 };
  };
  process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK = "1";
  const fakeWin = { isDestroyed: () => false, webContents: { send: () => {}, executeJavaScript: async () => true } };
  updateChecker.initUpdateChecker({
    appMode: "arcrho",
    getMainWindow: () => fakeWin,
    updateHost: acceptingUpdateHost(),
    fetchImpl: fetchStub,
    spawnImpl: launchingSpawnStub(),
    ...options,
  });
  try {
    return { result: await updateChecker.checkForUpdate({ showNoUpdate: false }), dialogs };
  } finally {
    delete process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK;
    electronStub.dialog.showMessageBox = originalShowMessageBox;
    updateChecker.initUpdateChecker({ appMode: "arcrho", getMainWindow: () => null });
  }
}

const readUpdateLog = () =>
  fs.readFileSync(path.join(path.dirname(hostSupport.getElectronLogPath()), "update.log"), "utf8");

test("update_checker resumes a dropped download from the bytes already received", async () => {
  const installerContent = Buffer.from("resumable-installer-bytes-for-test");
  const sha256 = crypto.createHash("sha256").update(installerContent).digest("hex");
  const downloadRequests = [];

  const fetchStub = async (url, options = {}) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.5")], sha256));
    const range = options.headers?.Range || "";
    downloadRequests.push(range);
    if (!range) {
      async function* droppedBody() {
        yield installerContent.subarray(0, 12);
        throw new Error("socket hang up");
      }
      return {
        ok: true,
        status: 200,
        headers: { get: (name) => (name === "content-length" ? String(installerContent.length) : null) },
        body: droppedBody(),
      };
    }
    const offset = Number(range.match(/^bytes=(\d+)-$/)[1]);
    async function* restBody() {
      yield installerContent.subarray(offset);
    }
    return {
      ok: true,
      status: 206,
      headers: { get: (name) => (name === "content-length" ? String(installerContent.length - offset) : null) },
      body: restBody(),
    };
  };

  const { result } = await runAcceptedUpdate(fetchStub, { downloadRetryDelaysMs: [1] });

  assert.deepEqual(result, { status: "launching", version: "0.0.5" });
  assert.deepEqual(downloadRequests, ["", "bytes=12-"], "the second request asks only for the missing bytes");
  const installerPath = path.join(downloadsDir, "Arco-Setup-0.0.5.exe");
  assert.deepEqual(fs.readFileSync(installerPath), installerContent);
  assert.match(readUpdateLog(), /Download attempt 1 failed at byte 12; retrying in 1 ms/);
  assert.equal((await updateChecker.cleanupCompletedUpdateInstaller()).status, "removed");
});

test("update_checker keeps a failed download's bytes and resumes them on the next update", async () => {
  const installerContent = Buffer.from("installer-resumed-across-updates");
  const sha256 = crypto.createHash("sha256").update(installerContent).digest("hex");
  const partPath = path.join(downloadsDir, "Arco-Setup-0.0.9.exe.part");
  const downloadRequests = [];
  let connectionDrops = true;

  const fetchStub = async (url, options = {}) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.9")], sha256));
    const range = options.headers?.Range || "";
    downloadRequests.push(range);
    const offset = range ? Number(range.match(/^bytes=(\d+)-$/)[1]) : 0;
    async function* body() {
      yield installerContent.subarray(offset, connectionDrops ? 9 : undefined);
      if (connectionDrops) throw new Error("socket hang up");
    }
    return {
      ok: true,
      status: offset ? 206 : 200,
      headers: { get: () => String(installerContent.length - offset) },
      body: body(),
    };
  };

  const first = await runAcceptedUpdate(fetchStub, { downloadRetryDelaysMs: [] });
  assert.equal(first.result.status, "download-failed");
  assert.equal(fs.statSync(partPath).size, 9, "the bytes already received survive a failed update");

  connectionDrops = false;
  const second = await runAcceptedUpdate(fetchStub, { downloadRetryDelaysMs: [] });
  assert.deepEqual(second.result, { status: "launching", version: "0.0.9" });
  assert.deepEqual(downloadRequests, ["", "bytes=9-"], "the next update asks only for the missing bytes");
  assert.deepEqual(fs.readFileSync(path.join(downloadsDir, "Arco-Setup-0.0.9.exe")), installerContent);
  assert.ok(!fs.existsSync(partPath));
  assert.equal((await updateChecker.cleanupCompletedUpdateInstaller()).status, "removed");
});

test("update_checker installs a matching installer already in Downloads without downloading it", async () => {
  const installerContent = Buffer.from("installer-already-downloaded");
  const sha256 = crypto.createHash("sha256").update(installerContent).digest("hex");
  const installerPath = path.join(downloadsDir, "Arco-Setup-0.0.7.exe");
  fs.writeFileSync(installerPath, installerContent);

  const fetchStub = async (url) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.7")], sha256));
    throw new Error(`a verified installer must not be downloaded again: ${url}`);
  };
  const { result } = await runAcceptedUpdate(fetchStub);

  assert.deepEqual(result, { status: "launching", version: "0.0.7" });
  assert.match(readUpdateLog(), /Found .*Arco-Setup-0\.0\.7\.exe; checksum matches, skipping the download/);
  const marker = JSON.parse(fs.readFileSync(path.join(userDataDir, "pending_update_cleanup.json"), "utf8"));
  assert.equal(marker.installerPath, installerPath);
  assert.equal((await updateChecker.cleanupCompletedUpdateInstaller()).status, "removed");
});

test("update_checker keeps a different file under the installer's name and downloads beside it", async () => {
  const installerContent = Buffer.from("the-published-installer");
  const sha256 = crypto.createHash("sha256").update(installerContent).digest("hex");
  const otherPath = path.join(downloadsDir, "Arco-Setup-0.0.8.exe");
  fs.writeFileSync(otherPath, "not the published installer");

  const fetchStub = async (url) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.8")], sha256));
    async function* body() {
      yield installerContent;
    }
    return { ok: true, status: 200, headers: { get: () => String(installerContent.length) }, body: body() };
  };
  const { result } = await runAcceptedUpdate(fetchStub);

  assert.deepEqual(result, { status: "launching", version: "0.0.8" });
  assert.equal(fs.readFileSync(otherPath, "utf8"), "not the published installer");
  assert.deepEqual(fs.readFileSync(path.join(downloadsDir, "Arco-Setup-0.0.8 (1).exe")), installerContent);
  assert.equal((await updateChecker.cleanupCompletedUpdateInstaller()).status, "removed");
  fs.rmSync(otherPath);
});

test("update_checker gives up on a download that stops sending data", async () => {
  const fetchStub = async (url, options = {}) => {
    if (isFeedUrl(url)) return feedResponse(feedFixture([feedEntry("0.0.6")]));
    // Never yields: the body ends only when the stall timer aborts the request.
    async function* silentBody() {
      await new Promise((_, reject) => {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
      });
    }
    return { ok: true, status: 200, headers: { get: () => "100" }, body: silentBody() };
  };

  const { result, dialogs } = await runAcceptedUpdate(fetchStub, {
    downloadRetryDelaysMs: [],
    downloadStallTimeoutMs: 20,
  });

  assert.deepEqual(result, { status: "download-failed", version: "0.0.6" });
  const failure = dialogs.find((options) => options.title === "Update could not be downloaded");
  assert.match(String(failure?.detail), /^No data received for \d+ seconds\.$/);
  assert.match(readUpdateLog(), /Download failed\n.*No data received/);
  assert.ok(!fs.existsSync(path.join(downloadsDir, "Arco-Setup-0.0.6.exe.part")));
});

test("backend_lifecycle initializes, resolves its port, and manages client markers", async () => {
  // A port nothing listens on: the update stop below would end a real backend
  // found on the preferred port of a development machine.
  process.env.ARCRHO_PORT = "28799";
  try {
    backendLifecycle.initBackendLifecycle({
      appMode: "arcrho",
      host: "127.0.0.1",
      backendToken: "test-token",
      appRoot: userDataDir,
      pythonExe: "python",
    });
  } finally {
    delete process.env.ARCRHO_PORT;
  }
  const port = backendLifecycle.getBackendPort();
  assert.equal(port, 28799);
  // Nothing was started and nothing listens, so the update stop reports the
  // backend gone without waiting.
  assert.equal(await backendLifecycle.stopBackendForUpdate(), true);

  backendLifecycle.registerBackendClient();
  const markerPath = path.join(userDataDir, "backend_clients", `${process.pid}.json`);
  const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
  assert.equal(marker.pid, process.pid);
  assert.equal(marker.port, port);
  backendLifecycle.unregisterBackendClient();
  assert.ok(!fs.existsSync(markerPath));

  backendLifecycle.clearBackendControlFlags();
});
