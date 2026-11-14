const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const { configDir } = require("./local_folders");

const APP_ENDPOINT_FILE = "app_endpoint.json";
const APP_ENDPOINT_FORMAT = "arcrho-app-endpoint-v1";

function resolvePreferredBackendPort({ appMode, env = process.env } = {}) {
  const defaultPort = appMode === "arcode" ? 28766 : 28765;
  const configured = parseInt(String(env.ARCRHO_PORT || env.ARCODE_PORT || ""), 10);
  if (Number.isInteger(configured) && configured > 0 && configured <= 65535) return configured;
  return defaultPort;
}

function tryBindPort(host, port) {
  return new Promise((resolve) => {
    const probe = net.createServer();
    probe.unref();
    probe.once("error", () => resolve(null));
    probe.listen(port, host, () => {
      const boundPort = probe.address().port;
      probe.close(() => resolve(boundPort));
    });
  });
}

async function findAvailableBackendPort(host, preferredPort) {
  if ((await tryBindPort(host, preferredPort)) === preferredPort) {
    return { port: preferredPort, fallback: false };
  }
  const freePort = await tryBindPort(host, 0);
  if (freePort == null) {
    throw new Error(`No free local port is available on ${host}.`);
  }
  return { port: freePort, fallback: true };
}

// Decides what a starting app may do with a listener on its preferred port that it cannot reuse.
// "leave" keeps the listener and sends the app to a free port; "clear" stops a server no live
// window is using; "take" means nothing is listening. `livePorts` are the ports claimed by the
// other live windows of this profile.
function decidePreferredPortListener({ port, health, sameProfile, livePorts = [], listenerPids = [] }) {
  if (health?.ok === true && !sameProfile) {
    return { action: "leave", reason: "it belongs to another or an unscoped user profile" };
  }
  if (livePorts.map(Number).includes(Number(port))) {
    return { action: "leave", reason: "another live Arco window is using it" };
  }
  if (!listenerPids.length) return { action: "take", reason: "" };
  return { action: "clear", reason: "no live Arco window is using it" };
}

// Decides whether a departing window stops the app server it uses. Only the other live windows of
// the same app on the same port count; which window started the server does not matter.
function decideBackendShutdownOnExit({ pid, port, mode, markers = [] }) {
  const others = markers.filter((marker) => (
    Number(marker.pid) !== Number(pid)
    && Number(marker.port) === Number(port)
    && (!marker.mode || marker.mode === mode)
  )).length;
  return { stop: others === 0, others };
}

function getAppEndpointPath({ appMode, env = process.env } = {}) {
  return path.join(configDir(appMode, env), APP_ENDPOINT_FILE);
}

function isProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  if (pid === process.pid) return true;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// A published-app file (the endpoint file, the window-ready marker) lists every running app under
// `apps`, newest first, one entry per process. The newest entry is also spread at the top level so
// a reader that knows only the single-app shape still finds an app.
function readPublishedAppEntries(filePath) {
  try {
    const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (Array.isArray(payload?.apps)) return payload.apps.filter((entry) => entry && typeof entry === "object");
    if (payload && typeof payload === "object" && payload.pid != null) return [payload];
  } catch {
    // A missing or unreadable file lists no apps.
  }
  return [];
}

function writePublishedAppEntries(filePath, entries, pid) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${pid}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify({ ...entries[0], apps: entries }, null, 2), "utf8");
  fs.renameSync(tempPath, filePath);
}

// Puts this process's entry first and drops its old entry and every entry whose process is gone.
function publishAppEntry(filePath, entry, { isAlive = isProcessAlive } = {}) {
  const pid = Number(entry.pid);
  const others = readPublishedAppEntries(filePath)
    .filter((item) => Number(item.pid) !== pid && isAlive(Number(item.pid)));
  writePublishedAppEntries(filePath, [entry, ...others], pid);
  return filePath;
}

// Removes only this process's entry; the file goes when no entry is left.
function unpublishAppEntry(filePath, pid) {
  const entries = readPublishedAppEntries(filePath);
  const rest = entries.filter((item) => Number(item.pid) !== Number(pid));
  if (rest.length === entries.length) return false;
  try {
    if (rest.length) writePublishedAppEntries(filePath, rest, pid);
    else fs.unlinkSync(filePath);
    return true;
  } catch {
    return false;
  }
}

function writeAppEndpointFile({ appMode, host, port, pid, env = process.env, isAlive } = {}) {
  return publishAppEntry(getAppEndpointPath({ appMode, env }), {
    format: APP_ENDPOINT_FORMAT,
    app: appMode === "arcode" ? "arcode" : "arcrho",
    url: `http://${host}:${port}`,
    host: String(host),
    port: Number(port),
    pid: Number(pid),
    updated_at: new Date().toISOString(),
  }, { isAlive });
}

function removeAppEndpointFile({ appMode, pid, env = process.env } = {}) {
  return unpublishAppEntry(getAppEndpointPath({ appMode, env }), pid);
}

module.exports = {
  APP_ENDPOINT_FORMAT,
  resolvePreferredBackendPort,
  findAvailableBackendPort,
  decidePreferredPortListener,
  decideBackendShutdownOnExit,
  isProcessAlive,
  readPublishedAppEntries,
  publishAppEntry,
  unpublishAppEntry,
  getAppEndpointPath,
  writeAppEndpointFile,
  removeAppEndpointFile,
};
