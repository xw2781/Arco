import assert from "node:assert/strict";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const {
  resolvePreferredBackendPort,
  findAvailableBackendPort,
  decidePreferredPortListener,
  getAppEndpointPath,
  writeAppEndpointFile,
  removeAppEndpointFile,
  APP_ENDPOINT_FORMAT,
} = (await import(new URL("../electron/backend_port.js", import.meta.url))).default;

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));

function makeTempAppData() {
  return fs.mkdtempSync(path.join(TESTS_DIR, "arcrho-endpoint-test-"));
}

test("resolvePreferredBackendPort uses mode defaults", () => {
  assert.equal(resolvePreferredBackendPort({ appMode: "arcrho", env: {} }), 28765);
  assert.equal(resolvePreferredBackendPort({ appMode: "arcode", env: {} }), 28766);
});

test("resolvePreferredBackendPort prefers env overrides and rejects invalid values", () => {
  assert.equal(resolvePreferredBackendPort({ appMode: "arcrho", env: { ARCRHO_PORT: "31000" } }), 31000);
  assert.equal(resolvePreferredBackendPort({ appMode: "arcrho", env: { ARCODE_PORT: "31001" } }), 31001);
  assert.equal(
    resolvePreferredBackendPort({ appMode: "arcrho", env: { ARCRHO_PORT: "31000", ARCODE_PORT: "31001" } }),
    31000,
  );
  assert.equal(resolvePreferredBackendPort({ appMode: "arcrho", env: { ARCRHO_PORT: "not-a-port" } }), 28765);
  assert.equal(resolvePreferredBackendPort({ appMode: "arcrho", env: { ARCRHO_PORT: "0" } }), 28765);
});

test("findAvailableBackendPort keeps a free preferred port", async () => {
  const probe = net.createServer();
  await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const freePort = probe.address().port;
  await new Promise((resolve) => probe.close(resolve));

  const result = await findAvailableBackendPort("127.0.0.1", freePort);
  assert.equal(result.port, freePort);
  assert.equal(result.fallback, false);
});

test("findAvailableBackendPort falls back to a different free port when occupied", async () => {
  const blocker = net.createServer();
  await new Promise((resolve) => blocker.listen(0, "127.0.0.1", resolve));
  const occupiedPort = blocker.address().port;
  try {
    const result = await findAvailableBackendPort("127.0.0.1", occupiedPort);
    assert.equal(result.fallback, true);
    assert.notEqual(result.port, occupiedPort);
    assert.ok(Number.isInteger(result.port) && result.port > 0 && result.port <= 65535);
  } finally {
    await new Promise((resolve) => blocker.close(resolve));
  }
});

test("decidePreferredPortListener leaves a port a live sibling window is using", () => {
  const result = decidePreferredPortListener({
    port: 28765,
    health: { ok: true, app: "arcrho" },
    sameProfile: true,
    livePorts: [28765],
    listenerPids: [5100],
  });
  assert.equal(result.action, "leave");
  assert.match(result.reason, /live Arco window/);
});

test("decidePreferredPortListener clears a server no live window is using", () => {
  const result = decidePreferredPortListener({
    port: 28765,
    health: { ok: true, app: "arcrho" },
    sameProfile: true,
    livePorts: [31000],
    listenerPids: [5100],
  });
  assert.equal(result.action, "clear");
});

test("decidePreferredPortListener leaves another profile's listener alone", () => {
  const result = decidePreferredPortListener({
    port: 28765,
    health: { ok: true, app: "arcrho" },
    sameProfile: false,
    livePorts: [],
    listenerPids: [5100],
  });
  assert.equal(result.action, "leave");
  assert.match(result.reason, /another or an unscoped user profile/);
});

test("decidePreferredPortListener takes a free preferred port", () => {
  const result = decidePreferredPortListener({ port: 28765, health: null, sameProfile: false });
  assert.equal(result.action, "take");
});

test("getAppEndpointPath derives the per-user AppData location by mode", () => {
  const env = { APPDATA: "C:\\Users\\demo\\AppData\\Roaming" };
  assert.equal(
    getAppEndpointPath({ appMode: "arcrho", env }),
    path.join(env.APPDATA, "Arco", "app_endpoint.json"),
  );
  assert.equal(
    getAppEndpointPath({ appMode: "arcode", env }),
    path.join(env.APPDATA, "Arcode", "app_endpoint.json"),
  );
});

test("writeAppEndpointFile publishes the endpoint and removeAppEndpointFile respects ownership", () => {
  const appdata = makeTempAppData();
  const env = { APPDATA: appdata };
  try {
    const endpointPath = writeAppEndpointFile({
      appMode: "arcrho",
      host: "127.0.0.1",
      port: 31555,
      pid: 4242,
      env,
    });
    assert.equal(endpointPath, getAppEndpointPath({ appMode: "arcrho", env }));
    const payload = JSON.parse(fs.readFileSync(endpointPath, "utf8"));
    assert.equal(payload.format, APP_ENDPOINT_FORMAT);
    assert.equal(payload.app, "arcrho");
    assert.equal(payload.url, "http://127.0.0.1:31555");
    assert.equal(payload.port, 31555);
    assert.equal(payload.pid, 4242);

    assert.equal(removeAppEndpointFile({ appMode: "arcrho", pid: 9999, env }), false);
    assert.ok(fs.existsSync(endpointPath));
    assert.equal(removeAppEndpointFile({ appMode: "arcrho", pid: 4242, env }), true);
    assert.ok(!fs.existsSync(endpointPath));
    assert.equal(removeAppEndpointFile({ appMode: "arcrho", pid: 4242, env }), false);
  } finally {
    fs.rmSync(appdata, { recursive: true, force: true });
  }
});

test("the endpoint file lists every running app, newest first, and drops dead ones", () => {
  const appdata = makeTempAppData();
  const env = { APPDATA: appdata };
  const alive = new Set([101, 102]);
  const isAlive = (pid) => alive.has(pid);
  const write = (pid, port) => writeAppEndpointFile({ appMode: "arcrho", host: "127.0.0.1", port, pid, env, isAlive });
  const read = () => JSON.parse(fs.readFileSync(getAppEndpointPath({ appMode: "arcrho", env }), "utf8"));
  try {
    write(101, 28765);
    write(102, 31002);
    let payload = read();
    assert.deepEqual(payload.apps.map((entry) => entry.pid), [102, 101]);
    // The newest entry stays readable in the single-app shape.
    assert.equal(payload.pid, 102);
    assert.equal(payload.url, "http://127.0.0.1:31002");

    alive.delete(101);
    write(103, 31003);
    assert.deepEqual(read().apps.map((entry) => entry.pid), [103, 102]);

    // An app removes only its own entry, and the next newest takes the top level.
    assert.equal(removeAppEndpointFile({ appMode: "arcrho", pid: 103, env }), true);
    payload = read();
    assert.deepEqual(payload.apps.map((entry) => entry.pid), [102]);
    assert.equal(payload.port, 31002);
  } finally {
    fs.rmSync(appdata, { recursive: true, force: true });
  }
});
