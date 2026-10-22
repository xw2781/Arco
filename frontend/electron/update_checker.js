// GitHub Releases update checking, download-with-progress, update-install prompting, and
// post-install installer cleanup for the desktop host.
const { app, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { sleep, withTimeout, getElectronLogPath, formatErrorForLog } = require("./host_support");

const SHA256_RE = /\b[a-fA-F0-9]{64}\b/;
const MANDATORY_MARKER_RE = /\bmandatory\s*:\s*true\b/i;
// HANDOFF: the release-list scan below still uses these until the update feed
// reader replaces it; see frontend/docs/plans/update_reliability_handoff.md.
const GITHUB_API_ROOT = "https://api.github.com";
const MAX_RELEASES_SCANNED = 30;
// The publisher's release channel file owns the repository and the update feed
// names; packaging copies it into the app's resources folder.
const RELEASE_CHANNEL_FILE = "release_channel.json";
const SOURCE_RELEASE_CHANNEL_PATH = path.resolve(__dirname, "..", "build", "release", RELEASE_CHANNEL_FILE);
const UPDATE_LOG_FILE = "update.log";
// A download that delivers nothing for this long is treated as dropped and resumed.
const DOWNLOAD_STALL_TIMEOUT_MS = 30000;
const USER_SECTION_HEADING_RE = /^##\s+user-facing changes\s*$/i;
const SECTION_HEADING_RE = /^##\s+/;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const BULLET_RE = /^[-*]\s+(.*)$/;
const NESTED_BULLET_RE = /^\s{2,}[-*]\s+/;
const RELEASED_ON_RE = /^released on .*\.$/i;
const MAX_RELEASE_NOTE_BULLETS = 12;
// Every installer ships the notes generated for it and for every release before
// it, so an installed app already holds its own complete history offline.
const LOCAL_RELEASE_NOTES_DIR = path.resolve(__dirname, "..", "docs", "releases");
const LOCAL_RELEASE_NOTE_FILE_RE = /^(\d+\.\d+\.\d+)\.md$/i;
const PENDING_CLEANUP_FILE = "pending_update_cleanup.json";
const CLEANUP_RETRY_DELAY_MS = 20000;
const BYTES_PER_MB = 1024 * 1024;
const PROGRESS_TEXT_INTERVAL_MS = 1000;
let lastProgressTextAt = 0;
const INSTALLER_LAUNCH_RETRY_DELAYS_MS = [400, 1200, 2500, 5000];
const TRANSIENT_LAUNCH_ERROR_CODES = new Set(["EBUSY", "ETXTBSY", "EACCES", "EPERM"]);
const MAX_INSTALLER_NAME_ATTEMPTS = 100;

let getMainWindow = () => null;
// The host's side of an update: hide the main window and show the small
// progress window, move its bar, bring the main window back, close the
// backend, and end the process. Provided by main.js; null outside the host.
let updateHost = null;
let fetchImpl = typeof fetch === "function" ? fetch : null;
let spawnImpl = spawn;
let UPDATE_GITHUB_REPO = "";
let UPDATE_FEED_URL = "";
let UPDATE_GITHUB_TOKEN = "";
let UPDATE_CHECK_TIMEOUT_MS = 15000;
let UPDATE_INSTALLER_NAME_RE = /$^/;
let DEV_UPDATE_CHECK_ENABLED = false;
let PRODUCT_LABEL = "Arco";
// Waits before each new download attempt; one attempt more than entries in all.
let downloadRetryDelaysMs = [2000, 5000, 10000];

function readReleaseChannel() {
  const channelPath = app.isPackaged
    ? path.join(process.resourcesPath, RELEASE_CHANNEL_FILE)
    : SOURCE_RELEASE_CHANNEL_PATH;
  return JSON.parse(fs.readFileSync(channelPath, "utf8"));
}

function initUpdateChecker({
  appMode,
  getMainWindow: getWin,
  updateHost: injectedHost,
  fetchImpl: injectedFetch,
  spawnImpl: injectedSpawn,
  downloadRetryDelaysMs: injectedRetryDelays,
} = {}) {
  getMainWindow = typeof getWin === "function" ? getWin : () => null;
  updateHost = injectedHost && typeof injectedHost === "object" ? injectedHost : null;
  if (typeof injectedFetch === "function") fetchImpl = injectedFetch;
  spawnImpl = typeof injectedSpawn === "function" ? injectedSpawn : spawn;
  downloadRetryDelaysMs = Array.isArray(injectedRetryDelays) ? injectedRetryDelays : [2000, 5000, 10000];
  PRODUCT_LABEL = appMode === "arcode" ? "Arcode" : "Arco";
  const channel = readReleaseChannel();
  UPDATE_GITHUB_REPO = (
    appMode === "arcode" ? process.env.ARCODE_UPDATE_GITHUB_REPO : process.env.ARCRHO_UPDATE_GITHUB_REPO
  ) || channel.githubRepo;
  UPDATE_FEED_URL = `https://github.com/${UPDATE_GITHUB_REPO}/releases/download/${channel.updateFeedTag}/`
    + String(channel.updateFeedAsset).replace("{product}", PRODUCT_LABEL);
  UPDATE_GITHUB_TOKEN = (
    appMode === "arcode" ? process.env.ARCODE_UPDATE_GITHUB_TOKEN : process.env.ARCRHO_UPDATE_GITHUB_TOKEN
  ) || "";
  UPDATE_CHECK_TIMEOUT_MS = Math.max(
    1000,
    parseInt(
      (appMode === "arcode" ? process.env.ARCODE_UPDATE_CHECK_TIMEOUT_MS : process.env.ARCRHO_UPDATE_CHECK_TIMEOUT_MS)
        || "15000",
      10
    ) || 15000
  );
  UPDATE_INSTALLER_NAME_RE = appMode === "arcode"
    ? /^Arcode-Setup-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\.exe$/i
    : /^Arco-Setup-(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)\.exe$/i;
  DEV_UPDATE_CHECK_ENABLED = String(
    appMode === "arcode" ? process.env.ARCODE_ENABLE_DEV_UPDATE_CHECK : process.env.ARCRHO_ENABLE_DEV_UPDATE_CHECK
  ).trim() === "1";
}

function parseVersion(value) {
  const text = String(value || "").trim().replace(/^v/i, "");
  const withoutBuild = text.split("+")[0];
  const [main, prerelease = ""] = withoutBuild.split("-", 2);
  const parts = main.split(".").map((part) => Number.parseInt(part, 10));
  if (parts.length < 3 || parts.some((part) => !Number.isInteger(part) || part < 0)) {
    return null;
  }
  return { parts, prerelease };
}

function compareVersions(left, right) {
  const leftVersion = parseVersion(left);
  const rightVersion = parseVersion(right);
  if (!leftVersion || !rightVersion) return 0;
  for (let i = 0; i < 3; i += 1) {
    const delta = leftVersion.parts[i] - rightVersion.parts[i];
    if (delta !== 0) return delta > 0 ? 1 : -1;
  }
  if (leftVersion.prerelease === rightVersion.prerelease) return 0;
  if (!leftVersion.prerelease) return 1;
  if (!rightVersion.prerelease) return -1;
  return leftVersion.prerelease.localeCompare(rightVersion.prerelease, undefined, { numeric: true });
}

function parseSha256Text(value) {
  const match = String(value || "").match(SHA256_RE);
  return match ? match[0].toLowerCase() : "";
}

function stripInlineMarkdown(text) {
  return String(text)
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

// The one reader of a release body. It keeps the user-facing section and drops
// the internal and fragment-source sections, so no surface built on it can leak
// build chatter to a user. `includeNested` is what separates the two surfaces:
// the in-app dialog scrolls and takes the per-change detail bullets, while a
// native message box cannot scroll and gets the summary bullets only.
function releaseNoteEntries(body, { includeNested = false } = {}) {
  const lines = String(body || "").replace(/\r\n/g, "\n").split("\n");
  const userSectionIndex = lines.findIndex((line) => USER_SECTION_HEADING_RE.test(line.trim()));
  let scoped = lines;
  if (userSectionIndex >= 0) {
    const rest = lines.slice(userSectionIndex + 1);
    const nextSection = rest.findIndex((line) => SECTION_HEADING_RE.test(line.trim()));
    scoped = nextSection >= 0 ? rest.slice(0, nextSection) : rest;
  }

  const entries = [];
  for (const line of scoped) {
    const trimmed = line.trim();
    if (!trimmed || RELEASED_ON_RE.test(trimmed)) continue;

    const heading = trimmed.match(HEADING_RE);
    if (heading) {
      // A body with no user-facing section is shown whole; its own release title
      // only repeats the version the dialog already states.
      if (heading[1].length > 1) entries.push({ kind: "title", text: stripInlineMarkdown(heading[2]) });
      continue;
    }

    const bullet = trimmed.match(BULLET_RE);
    if (!bullet) {
      entries.push({ kind: "text", text: stripInlineMarkdown(trimmed) });
      continue;
    }
    if (NESTED_BULLET_RE.test(line)) {
      if (includeNested) entries.push({ kind: "nested", text: stripInlineMarkdown(bullet[1]) });
      continue;
    }
    entries.push({ kind: "bullet", text: stripInlineMarkdown(bullet[1]) });
  }
  return entries;
}

function releasedOnFromBody(body) {
  const line = String(body || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((entry) => entry.trim())
    .find((entry) => RELEASED_ON_RE.test(entry));
  return line ? line.replace(/^released on\s*/i, "").replace(/\.$/, "").trim() : "";
}

// One version's notes in the shape every renderer surface consumes, so the
// update dialog and the release-history window cannot drift apart.
function releaseNotePresentation(version, body, publishedAt = "") {
  return {
    version,
    publishedAt: String(publishedAt || "").trim(),
    releasedOn: releasedOnFromBody(body),
    entries: releaseNoteEntries(body, { includeNested: true }),
  };
}

function formatReleaseNotesForDialog(body) {
  const entries = releaseNoteEntries(body);
  const rendered = [];
  let bullets = 0;
  let dropped = 0;

  for (let i = 0; i < entries.length; i += 1) {
    const entry = entries[i];
    if (entry.kind === "bullet" && bullets >= MAX_RELEASE_NOTE_BULLETS) {
      dropped = entries.slice(i).filter((remaining) => remaining.kind === "bullet").length;
      break;
    }
    if (entry.kind === "bullet") {
      bullets += 1;
      rendered.push(`   • ${entry.text}`);
    } else if (entry.kind === "title") {
      if (rendered.length) rendered.push("");
      rendered.push(entry.text);
    } else {
      rendered.push(entry.text);
    }
  }

  if (dropped > 0) {
    rendered.push(
      "",
      `and ${dropped} more change${dropped === 1 ? "" : "s"} - see https://github.com/${UPDATE_GITHUB_REPO}/releases`
    );
  }
  return rendered.join("\n").trim();
}

// `skipped` carries every release newer than the installed build up to and
// including the winning one, newest first. A user who jumps 1.4.0 -> 1.4.2 has
// never seen 1.4.1's notes, and the releases list already in hand holds them.
function createUpdateInfo(candidate, sha256, skipped) {
  const releases = skipped.map((entry) => ({
    version: entry.version,
    publishedAt: String(entry.release?.published_at || "").trim(),
    body: String(entry.release?.body || "").trim(),
  }));
  return {
    version: candidate.version,
    currentVersion: app.getVersion(),
    assetName: candidate.asset.name,
    downloadUrl: candidate.asset.browser_download_url,
    sha256,
    source: "github",
    releaseNotes: String(candidate.release?.body || "").trim(),
    releases,
    // A mandatory marker anywhere in the skipped span still makes this update
    // mandatory; the version that carried it is one the user never installed.
    mandatory: releases.some((entry) => MANDATORY_MARKER_RE.test(entry.body)),
    publishedAt: String(candidate.release?.published_at || "").trim(),
  };
}

function createUpdateIssue(status, version, assetName, message, detail = "") {
  return { status, version, assetName, source: "github", message, detail };
}

function areInstallerUpdateChecksEnabled() {
  return app.isPackaged || DEV_UPDATE_CHECK_ENABLED;
}

function githubRequestHeaders(extra = {}) {
  const headers = {
    "User-Agent": "ArcRho-Updater",
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    ...extra,
  };
  if (UPDATE_GITHUB_TOKEN) headers.Authorization = `Bearer ${UPDATE_GITHUB_TOKEN}`;
  return headers;
}

async function fetchReleases() {
  if (typeof fetchImpl !== "function") {
    throw new Error("No fetch implementation is available for the update check.");
  }
  const url = `${GITHUB_API_ROOT}/repos/${UPDATE_GITHUB_REPO}/releases?per_page=${MAX_RELEASES_SCANNED}`;
  const response = await fetchImpl(url, { headers: githubRequestHeaders() });
  if (!response.ok) {
    throw new Error(`GitHub releases request failed with status ${response.status}`);
  }
  const releases = await response.json();
  return Array.isArray(releases) ? releases : [];
}

async function readAssetText(url) {
  const response = await fetchImpl(url, { headers: githubRequestHeaders({ Accept: "application/octet-stream" }) });
  if (!response.ok) return "";
  return String(await response.text());
}

// Every published release carrying an installer for this product, newest first.
// No network here: the checksum is fetched only for the version that wins.
function installerReleaseCandidates(releases) {
  const candidates = [];
  const seenVersions = new Set();
  for (const release of releases) {
    if (release?.draft || release?.prerelease) continue;
    const assets = Array.isArray(release?.assets) ? release.assets : [];
    for (const asset of assets) {
      const match = String(asset?.name || "").match(UPDATE_INSTALLER_NAME_RE);
      if (!match) continue;
      const version = match[1];
      if (seenVersions.has(version)) continue;
      seenVersions.add(version);
      candidates.push({ version, release, asset, assets });
    }
  }
  candidates.sort((left, right) => compareVersions(right.version, left.version));
  return candidates;
}

async function findAvailableUpdateFromReleases(releases, options = {}) {
  const reportIssues = options.reportIssues === true;
  const newer = installerReleaseCandidates(releases)
    .filter((candidate) => compareVersions(candidate.version, app.getVersion()) > 0);
  let issue = null;

  // Highest version first, so the first candidate with a usable checksum wins
  // and a lower one is only reached when the higher one cannot be installed.
  for (const candidate of newer) {
    const checksumName = `${candidate.asset.name}.sha256`;
    const checksumAsset = candidate.assets.find((entry) => entry?.name === checksumName);
    if (!checksumAsset) {
      console.warn(`Arco update asset is missing a SHA-256 checksum asset: ${candidate.asset.name}`);
      issue = issue || createUpdateIssue(
        "missing-checksum",
        candidate.version,
        candidate.asset.name,
        "Arco found a newer installer, but it is missing a SHA-256 checksum.",
        `Add a ${checksumName} asset to the release.`
      );
      continue;
    }

    const sha256 = parseSha256Text(await readAssetText(checksumAsset.browser_download_url));
    if (!sha256) {
      console.warn(`Arco update checksum asset could not be read: ${checksumAsset.name}`);
      issue = issue || createUpdateIssue(
        "missing-checksum",
        candidate.version,
        candidate.asset.name,
        "Arco found a newer installer, but its SHA-256 checksum could not be read."
      );
      continue;
    }

    const skipped = newer.filter((entry) => compareVersions(entry.version, candidate.version) <= 0);
    return createUpdateInfo(candidate, sha256, skipped);
  }

  return reportIssues ? issue : null;
}

async function findAvailableUpdate(options = {}) {
  const releases = await fetchReleases();
  return findAvailableUpdateFromReleases(releases, options);
}

function calculateFileSha256(filePath) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(filePath);
    let digest = "";
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => { digest = hash.digest("hex").toLowerCase(); });
    // Resolve on "close" so the read handle on the installer is gone before the
    // caller tries to start it; at "end" the descriptor is still open.
    stream.on("close", () => resolve(digest));
  });
}

function legacyUpdatesDownloadDir() {
  return path.join(app.getPath("userData"), "updates");
}

function installerDownloadDir() {
  // The installer is a user-visible download, so it belongs in the user's own
  // Downloads folder rather than inside the app's user-data tree on C:.
  try {
    const downloads = app.getPath("downloads");
    if (downloads) return downloads;
  } catch (err) {
    console.warn(`Arco could not resolve the Downloads folder: ${err?.message || err}`);
  }
  return legacyUpdatesDownloadDir();
}

// The cleanup pass deletes only what ArcRho itself downloaded, so never reuse a
// name that already exists; an installer the user downloaded by hand keeps it.
function reserveInstallerPath(destDir, assetName) {
  const ext = path.extname(assetName);
  const base = path.basename(assetName, ext);
  for (let attempt = 0; attempt < MAX_INSTALLER_NAME_ATTEMPTS; attempt += 1) {
    const candidate = path.join(destDir, attempt === 0 ? assetName : `${base} (${attempt})${ext}`);
    if (!fs.existsSync(candidate) && !fs.existsSync(`${candidate}.part`)) return candidate;
  }
  return path.join(destDir, `${base} (${Date.now()})${ext}`);
}

function pendingCleanupMarkerPath() {
  return path.join(app.getPath("userData"), PENDING_CLEANUP_FILE);
}

function recordPendingInstallerCleanup(installerPath, version) {
  // Written synchronously: app.quit() follows immediately, and a marker that
  // never lands leaves the installer in Downloads forever.
  try {
    fs.writeFileSync(
      pendingCleanupMarkerPath(),
      `${JSON.stringify({ installerPath, version }, null, 2)}\n`,
      "utf8"
    );
  } catch (err) {
    console.warn(`Arco could not record the update installer cleanup marker: ${err?.message || err}`);
  }
}

async function deleteInstallerFile(installerPath) {
  try {
    await fs.promises.unlink(installerPath);
    return true;
  } catch (err) {
    if (err?.code === "ENOENT") return true;
    console.warn(`Arco could not delete the update installer ${installerPath}: ${err?.message || err}`);
    return false;
  }
}

async function removeLegacyUpdateDownloads() {
  const dir = legacyUpdatesDownloadDir();
  let entries = [];
  try {
    entries = await fs.promises.readdir(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    const name = entry.endsWith(".part") ? entry.slice(0, -".part".length) : entry;
    if (!UPDATE_INSTALLER_NAME_RE.test(name)) continue;
    await deleteInstallerFile(path.join(dir, entry));
  }
  await fs.promises.rmdir(dir).catch(() => {});
}

// Runs at startup: the installer that produced this launch cannot delete itself,
// and it is still locked while it exits, so a failed delete is retried once and
// otherwise left for the next launch.
async function cleanupCompletedUpdateInstaller() {
  await removeLegacyUpdateDownloads();

  const markerPath = pendingCleanupMarkerPath();
  let installerPath = "";
  try {
    installerPath = String(JSON.parse(await fs.promises.readFile(markerPath, "utf8"))?.installerPath || "");
  } catch {
    return { status: "none" };
  }

  const dropMarker = () => fs.promises.unlink(markerPath).catch(() => {});
  if (!installerPath) {
    await dropMarker();
    return { status: "none" };
  }
  if (await deleteInstallerFile(installerPath)) {
    await dropMarker();
    return { status: "removed", installerPath };
  }

  setTimeout(() => {
    deleteInstallerFile(installerPath).then((removed) => {
      if (removed) dropMarker();
    });
  }, CLEANUP_RETRY_DELAY_MS).unref?.();
  return { status: "retry-scheduled", installerPath };
}

// The brand a caption shows. app.getName() is the packaging identity that also
// names the per-user data folder, so it is not what the user should read here.
function productName() {
  return PRODUCT_LABEL;
}

// Installers run to hundreds of megabytes, so both sides stay in MB rather than
// scaling per value: a unit that changes mid-download makes the readout jump.
function formatDownloadedSize(receivedBytes, totalBytes) {
  const megabytes = (bytes) => (bytes > 0 ? bytes / BYTES_PER_MB : 0).toFixed(1);
  const received = `${megabytes(receivedBytes)} MB`;
  return totalBytes > 0 ? `${received} / ${megabytes(totalBytes)} MB` : received;
}

// The progress window fades its caption on every text change, so the size
// readout moves once a second while the bar itself follows every chunk.
function sendDownloadProgress(payload) {
  if (!updateHost) return;
  const { phase, version, receivedBytes = 0, totalBytes = 0 } = payload;
  if (phase === "start" || phase === "progress") {
    const percent = totalBytes > 0 ? Math.min(100, Math.floor((receivedBytes / totalBytes) * 100)) : 0;
    const now = Date.now();
    let text;
    if (phase === "start" || now - lastProgressTextAt >= PROGRESS_TEXT_INTERVAL_MS) {
      lastProgressTextAt = now;
      text = `Downloading ${productName()} ${version}... ${formatDownloadedSize(receivedBytes, totalBytes)}`;
    }
    updateHost.progress(percent, text);
  } else if (phase === "verifying") {
    updateHost.progress(100, "Verifying the download...");
  } else if (phase === "closing") {
    updateHost.progress(100, `Closing ${productName()} so setup can start...`);
  }
}

async function downloadReleaseAsset(updateInfo) {
  const destDir = installerDownloadDir();
  await fs.promises.mkdir(destDir, { recursive: true });
  const destPath = reserveInstallerPath(destDir, updateInfo.assetName);
  const partPath = `${destPath}.part`;

  try {
    const response = await fetchImpl(updateInfo.downloadUrl, { headers: githubRequestHeaders() });
    if (!response.ok || !response.body) {
      throw new Error(`Update download request failed with status ${response.status}`);
    }
    const totalBytes = Number.parseInt(response.headers.get("content-length") || "", 10) || 0;
    let receivedBytes = 0;

    sendDownloadProgress({ phase: "start", version: updateInfo.version, receivedBytes: 0, totalBytes });
    const writeStream = fs.createWriteStream(partPath);
    try {
      for await (const chunk of response.body) {
        const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        await new Promise((resolve, reject) => {
          writeStream.write(buffer, (err) => (err ? reject(err) : resolve()));
        });
        receivedBytes += buffer.length;
        sendDownloadProgress({ phase: "progress", version: updateInfo.version, receivedBytes, totalBytes });
      }
    } finally {
      // "close", not the end() callback: that one fires on "finish", while the
      // file descriptor is still open, and Windows refuses to start an
      // executable that another handle is holding.
      await new Promise((resolve) => {
        writeStream.on("close", resolve);
        writeStream.end();
      });
    }

    await fs.promises.rename(partPath, destPath);
    return destPath;
  } catch (err) {
    // A partial file in the user's Downloads folder is litter nothing else clears.
    await fs.promises.unlink(partPath).catch(() => {});
    throw err;
  }
}

function showMainWindowMessageBox(options) {
  const win = getMainWindow();
  if (win && !win.isDestroyed()) {
    return dialog.showMessageBox(win, options);
  }
  return dialog.showMessageBox(options);
}

// Settles on the child's own outcome: spawn() throws EBUSY synchronously but
// reports EACCES/ENOENT as an "error" event, which with no listener would take
// the main process down instead of reaching the caller's error dialog.
// `--updated` is electron-builder's own flag for a setup the app started: the
// installer reinstalls into the existing location without asking, and this
// build's installer script skips its option and finish pages on it as well.
function spawnUpdateInstaller(installerPath) {
  return new Promise((resolve, reject) => {
    const child = spawnImpl(installerPath, ["--updated"], {
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.once("error", reject);
    child.once("spawn", () => {
      child.unref();
      resolve();
    });
  });
}

// A freshly written installer is briefly held by whatever inspects new
// executables - Windows Defender's real-time scan above all - and CreateProcess
// answers that with EBUSY. It clears on its own, so retry before giving up.
async function launchUpdateInstaller(installerPath) {
  let lastError = null;
  for (let attempt = 0; attempt <= INSTALLER_LAUNCH_RETRY_DELAYS_MS.length; attempt += 1) {
    if (attempt > 0) await sleep(INSTALLER_LAUNCH_RETRY_DELAYS_MS[attempt - 1]);
    try {
      await spawnUpdateInstaller(installerPath);
      return;
    } catch (err) {
      lastError = err;
      if (!TRANSIENT_LAUNCH_ERROR_CODES.has(String(err?.code || ""))) break;
      console.warn(`Arco update installer launch attempt ${attempt + 1} failed: ${err?.message || err}`);
    }
  }

  // ShellExecute goes through the shell rather than CreateProcess directly, so
  // it can still start a file the direct launch was refused.
  const openError = shell?.openPath ? await shell.openPath(installerPath) : "no shell available";
  if (!openError) return;
  throw new Error(`${String(lastError?.message || lastError)} (opening the installer also failed: ${openError})`);
}

async function downloadVerifyAndInstall(updateInfo) {
  // The main window goes away at once and the download, the verification and
  // the shutdown are shown in a small window of their own, so the user never
  // sits in front of a frozen main window while setup waits for it.
  updateHost?.begin();
  let installerPath = "";
  try {
    installerPath = await downloadReleaseAsset(updateInfo);
  } catch (err) {
    console.warn(`Arco update download failed: ${err?.message || err}`);
    updateHost?.cancel();
    await showMainWindowMessageBox({
      type: "error",
      title: "Update could not be downloaded",
      message: "Arco did not install the update.",
      detail: String(err?.message || err),
      buttons: ["OK"],
      noLink: true,
    });
    return { status: "download-failed", version: updateInfo.version };
  }

  sendDownloadProgress({ phase: "verifying", version: updateInfo.version });
  const actualSha256 = await calculateFileSha256(installerPath).catch(() => "");
  const verified = actualSha256 && actualSha256 === String(updateInfo.sha256 || "").toLowerCase();
  if (!verified) {
    await fs.promises.unlink(installerPath).catch(() => {});
    updateHost?.cancel();
    await showMainWindowMessageBox({
      type: "error",
      title: "Update could not be verified",
      message: "Arco did not install the update.",
      detail: "The downloaded installer checksum did not match the published SHA-256 value.",
      buttons: ["OK"],
      noLink: true,
    });
    return { status: "verification-failed", version: updateInfo.version };
  }

  // Setup replaces the files the backend runs from, so the backend has to be
  // gone - not merely asked to stop - before the installer starts. Quitting
  // right after the launch left that shutdown racing the process exit, and an
  // installer that then found the backend alive could only report that the
  // app cannot be closed.
  sendDownloadProgress({ phase: "closing", version: updateInfo.version });
  await updateHost?.shutdown();
  try {
    await launchUpdateInstaller(installerPath);
  } catch (err) {
    // The installer is downloaded and verified, so name it: running it by hand
    // is all that is left to do, and the app is already closed.
    updateHost?.cancel();
    await showMainWindowMessageBox({
      type: "error",
      title: "Update could not be started",
      message: "Arco could not launch the update installer.",
      detail: [
        String(err?.message || err),
        "",
        "The installer was downloaded and verified. You can run it yourself:",
        installerPath,
      ].join("\n"),
      buttons: ["OK"],
      noLink: true,
    });
    updateHost?.exit();
    return { status: "launch-failed", version: updateInfo.version, installerPath };
  }
  recordPendingInstallerCleanup(installerPath, updateInfo.version);
  updateHost?.exit();
  return { status: "launching", version: updateInfo.version };
}

function releasesPageUrl() {
  return `https://github.com/${UPDATE_GITHUB_REPO}/releases`;
}

function buildUpdateDialogPayload(updateInfo) {
  return {
    mode: "update",
    currentVersion: app.getVersion(),
    version: updateInfo.version,
    assetName: updateInfo.assetName,
    publishedAt: updateInfo.publishedAt || "",
    mandatory: !!updateInfo.mandatory,
    releasesUrl: releasesPageUrl(),
    releases: (updateInfo.releases || []).map((entry) =>
      releaseNotePresentation(entry.version, entry.body, entry.publishedAt)),
  };
}

// The renderer owns the scrollable dialog; a native message box cannot scroll,
// which is why the notes it shows have to stay truncated. Returns null whenever
// the window cannot answer, so the caller falls back to the native box instead
// of silently skipping the prompt.
async function requestInAppUpdateChoice(win, updateInfo) {
  const payloadJson = JSON.stringify(buildUpdateDialogPayload(updateInfo));
  try {
    const answer = await win.webContents.executeJavaScript(
      `window.__arcrho_show_update_dialog`
      + ` ? window.__arcrho_show_update_dialog(JSON.parse(${JSON.stringify(payloadJson)}))`
      + ` : null`,
      true
    );
    const choice = String(answer?.choice || "");
    return choice === "update" || choice === "later" ? choice : null;
  } catch (err) {
    console.warn(`Arco could not show the in-app update dialog: ${err?.message || err}`);
    return null;
  }
}

async function nativeUpdatePrompt(updateInfo) {
  const detailLines = [
    `Current version: ${app.getVersion()}`,
    `Available version: ${updateInfo.version}`,
    `Installer: ${updateInfo.assetName}`,
  ];
  if (updateInfo.publishedAt) detailLines.push(`Published: ${updateInfo.publishedAt}`);
  const releaseNotes = formatReleaseNotesForDialog(updateInfo.releaseNotes);
  if (releaseNotes) detailLines.push("", releaseNotes);
  const skipped = (updateInfo.releases || []).filter((entry) => entry.version !== updateInfo.version);
  if (skipped.length) {
    detailLines.push("", `Also includes ${skipped.map((entry) => entry.version).join(", ")}.`);
  }
  if (updateInfo.mandatory) detailLines.push("", "This update is marked as mandatory.");

  const response = await showMainWindowMessageBox({
    type: "info",
    title: "Arco update available",
    message: `Arco ${updateInfo.version} is available.`,
    detail: detailLines.join("\n"),
    buttons: ["Update now", "Later"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  return response.response === 0;
}

async function promptForUpdateInstall(updateInfo) {
  const win = getMainWindow();
  if (!updateInfo || !win || win.isDestroyed()) return { status: "unavailable" };

  const choice = await requestInAppUpdateChoice(win, updateInfo);
  const accepted = choice === null ? await nativeUpdatePrompt(updateInfo) : choice === "update";
  if (!accepted) return { status: "deferred", version: updateInfo.version };

  // "Update now" is the one click: it is the consent to close the app, so no
  // second "Quit the application?" prompt follows it.
  return downloadVerifyAndInstall(updateInfo);
}

// The notes shipped inside this build: complete from the first release up to the
// installed version, and readable with no network. Each upgrade replaces the set
// with a newer one, so the history stays current without anything to persist.
async function readLocalReleaseHistory() {
  const base = {
    mode: "history",
    currentVersion: app.getVersion(),
    releasesUrl: releasesPageUrl(),
    releases: [],
  };

  let names = [];
  try {
    names = await fs.promises.readdir(LOCAL_RELEASE_NOTES_DIR);
  } catch (err) {
    console.warn(`Arco could not read the bundled release notes: ${err?.message || err}`);
    return { ...base, available: false };
  }

  const files = names
    .map((name) => ({ name, match: name.match(LOCAL_RELEASE_NOTE_FILE_RE) }))
    .filter((entry) => entry.match)
    .map((entry) => ({ name: entry.name, version: entry.match[1] }))
    .sort((left, right) => compareVersions(right.version, left.version));

  const bodies = await Promise.all(files.map((entry) =>
    fs.promises.readFile(path.join(LOCAL_RELEASE_NOTES_DIR, entry.name), "utf8").catch(() => "")));

  const releases = files
    .map((entry, index) => ({ entry, body: bodies[index] }))
    .filter((pair) => pair.body.trim())
    .map((pair) => releaseNotePresentation(pair.entry.version, pair.body));

  return { ...base, available: true, releases };
}

async function checkForUpdate(options = {}) {
  const showNoUpdate = options.showNoUpdate === true;
  if (process.platform !== "win32") {
    if (showNoUpdate) {
      await showMainWindowMessageBox({
        type: "info",
        title: "Update check unavailable",
        message: "Arco update checks are available in the Windows desktop app.",
        buttons: ["OK"],
        noLink: true,
      });
    }
    return { status: "unsupported" };
  }
  if (!areInstallerUpdateChecksEnabled()) {
    if (showNoUpdate) {
      await showMainWindowMessageBox({
        type: "info",
        title: "Update check unavailable",
        message: "Arco installer update checks are disabled in development mode.",
        detail: [
          "Development launches run from the local source tree instead of an installed package.",
          "Set ARCRHO_ENABLE_DEV_UPDATE_CHECK=1 before launch to test installer update checks from a dev app.",
        ].join("\n"),
        buttons: ["OK"],
        noLink: true,
      });
    }
    return { status: "development" };
  }

  let updateInfo = null;
  try {
    updateInfo = await withTimeout(
      findAvailableUpdate({ reportIssues: showNoUpdate }),
      UPDATE_CHECK_TIMEOUT_MS,
      "Arco update check"
    );
  } catch (err) {
    console.warn(`Arco update check skipped: ${err?.message || err}`);
    if (showNoUpdate) {
      await showMainWindowMessageBox({
        type: "info",
        title: "Update location unavailable",
        message: "Arco could not reach the update location.",
        detail: [
          `Update location: https://github.com/${UPDATE_GITHUB_REPO}/releases`,
          String(err?.message || err),
        ].join("\n"),
        buttons: ["OK"],
        noLink: true,
      });
    }
    return { status: "unavailable" };
  }

  if (updateInfo?.status) {
    if (showNoUpdate) {
      await showMainWindowMessageBox({
        type: updateInfo.status === "missing-checksum" ? "warning" : "info",
        title: "Update installer is not ready",
        message: updateInfo.message || "Arco found an update, but it cannot be installed yet.",
        detail: [
          `Current version: ${app.getVersion()}`,
          updateInfo.version ? `Available version: ${updateInfo.version}` : "",
          updateInfo.assetName ? `Installer: ${updateInfo.assetName}` : "",
          updateInfo.detail || "",
        ].filter(Boolean).join("\n"),
        buttons: ["OK"],
        noLink: true,
      });
    }
    return {
      status: updateInfo.status,
      version: updateInfo.version || "",
      assetName: updateInfo.assetName || "",
    };
  }

  if (!updateInfo) {
    if (showNoUpdate) {
      await showMainWindowMessageBox({
        type: "info",
        title: "No update available",
        message: "Arco is up to date.",
        detail: `Current version: ${app.getVersion()}`,
        buttons: ["OK"],
        noLink: true,
      });
    }
    return { status: "none" };
  }

  return promptForUpdateInstall(updateInfo);
}

async function checkForStartupUpdate() {
  return checkForUpdate({ showNoUpdate: false });
}

module.exports = {
  initUpdateChecker,
  checkForUpdate,
  checkForStartupUpdate,
  cleanupCompletedUpdateInstaller,
  readLocalReleaseHistory,
};
