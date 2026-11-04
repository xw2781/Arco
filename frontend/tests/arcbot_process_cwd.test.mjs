import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const testRoot = fs.mkdtempSync(path.join(TESTS_DIR, "arcbot-process-cwd-"));
const documentsDir = path.join(testRoot, "Documents");
const userDataDir = path.join(testRoot, "UserData");
const installDir = path.join(testRoot, "Install", "ArcRho");
const resourcesDir = path.join(installDir, "resources");
const cliRoot = path.join(testRoot, "Install", "ArcBot CLI");
const packagedAppRoot = path.join(resourcesDir, "app.asar");
const expectedHostCwd = path.join(documentsDir, "ArcRho");
fs.mkdirSync(userDataDir, { recursive: true });
fs.mkdirSync(resourcesDir, { recursive: true });

const originalCodexCommand = process.env.ARCRHO_CODEX_CMD;
const hadResourcesPath = Object.prototype.hasOwnProperty.call(process, "resourcesPath");
const originalResourcesPath = process.resourcesPath;
process.env.ARCRHO_CODEX_CMD = path.join(testRoot, "fake-codex.exe");
process.resourcesPath = resourcesDir;

const require = createRequire(import.meta.url);
const { registerArcBotIpc, testHooks } = require("../electron/arcbot_host.js");
const handlers = new Map();
const hostCommandCalls = [];
const detachedSpawnCalls = [];

const successfulCommand = (stdout = "") => ({
  ok: true,
  code: 0,
  signal: null,
  stdout,
  stderr: "",
  timedOut: false,
  canceled: false,
  error: "",
});

const failedCommand = (error) => ({
  ok: false,
  code: -1,
  signal: null,
  stdout: "",
  stderr: "",
  timedOut: false,
  canceled: false,
  error,
});

const arcBotHost = registerArcBotIpc({
  ipcMain: {
    handle(name, handler) {
      handlers.set(name, handler);
    },
  },
  app: {
    isPackaged: true,
    getPath(name) {
      if (name === "documents") return documentsDir;
      if (name === "userData") return userDataDir;
      return testRoot;
    },
  },
  APP_ROOT: packagedAppRoot,
  REPO_ROOT: testRoot,
  PYTHON_EXE: "python",
  getPrefsDir: () => userDataDir,
  getWorkspacePathsPath: () => path.join(userDataDir, "missing-workspace-paths.json"),
  findExecutableOnPath: () => "",
  runHostCommand: async (command, args, options) => {
    hostCommandCalls.push({ command, args, options });
    if (args[0] === "--version") return successfulCommand("codex-cli 0.139.0\n");
    if (args[0] === "login" && args[1] === "status") return failedCommand("Not logged in");
    if (command === "powershell.exe") return failedCommand("spawn EPERM");
    return successfulCommand();
  },
  spawnProcess: (command, args, options) => {
    detachedSpawnCalls.push({ command, args, options });
    const child = new EventEmitter();
    child.unref = () => {};
    queueMicrotask(() => child.emit("error", Object.assign(new Error("spawn EPERM"), { code: "EPERM" })));
    return child;
  },
});

test.after(() => {
  arcBotHost.stop();
  if (originalCodexCommand === undefined) delete process.env.ARCRHO_CODEX_CMD;
  else process.env.ARCRHO_CODEX_CMD = originalCodexCommand;
  if (hadResourcesPath) process.resourcesPath = originalResourcesPath;
  else delete process.resourcesPath;
  fs.rmSync(testRoot, { recursive: true, force: true });
});

test("packaged ArcBot status, install, and fallback commands use a writable host cwd", async () => {
  const status = await handlers.get("codex-assistant-status")();
  assert.equal(status.installed, true);
  assert.equal(status.authenticated, false);
  assert.equal(status.error, "Not logged in");
  assert.equal(hostCommandCalls.length, 2);
  assert.ok(hostCommandCalls.every((call) => call.options.cwd === expectedHostCwd));
  assert.ok(fs.statSync(expectedHostCwd).isDirectory());
  assert.doesNotMatch(expectedHostCwd, /\.asar(?:[\\/]|$)/iu);

  const install = await handlers.get("codex-assistant-install")();
  assert.deepEqual(install, { ok: false, output: "", error: "spawn EPERM" });
  const installCall = hostCommandCalls.at(-1);
  assert.equal(installCall.options.cwd, expectedHostCwd);
  const installPrefixAt = installCall.args.indexOf("-InstallPrefix");
  assert.ok(installPrefixAt >= 0);
  assert.equal(installCall.args[installPrefixAt + 1], path.join(cliRoot, "codex-cli"));

  const requestedCwd = path.join(testRoot, "requested-workspace");
  await testHooks.runCodexCommand(["exec", "--cd", requestedCwd]);
  assert.equal(hostCommandCalls.at(-1).options.cwd, expectedHostCwd);
  assert.deepEqual(hostCommandCalls.at(-1).args, ["exec", "--cd", requestedCwd]);

  await testHooks.runCodexCommand(["--version"], { cwd: requestedCwd });
  assert.equal(hostCommandCalls.at(-1).options.cwd, requestedCwd);
});

test("ArcBot login reports asynchronous spawn failures from the writable host cwd", async () => {
  const result = await handlers.get("codex-assistant-login")(null, { provider: "openai" });
  assert.deepEqual(result, { ok: false, error: "spawn EPERM" });
  const loginCall = detachedSpawnCalls.at(-1);
  assert.equal(loginCall.command, "cmd.exe");
  assert.equal(loginCall.options.cwd, expectedHostCwd);
  assert.notEqual(loginCall.options.cwd, packagedAppRoot);
});

test("repeat ArcBot sign-in clicks share one launch instead of opening a window each", async () => {
  const before = detachedSpawnCalls.length;
  const login = handlers.get("codex-assistant-login");
  const results = await Promise.all([1, 2, 3].map(() => login(null, { provider: "openai" })));
  assert.equal(detachedSpawnCalls.length - before, 1);
  assert.ok(results.every((result) => result.ok === false && result.error === "spawn EPERM"));

  await login(null, { provider: "openai" });
  assert.equal(detachedSpawnCalls.length - before, 2);
});

function fakeAppServerProcess() {
  const proc = new EventEmitter();
  proc.stdout = new EventEmitter();
  proc.stderr = new EventEmitter();
  proc.stdin = new EventEmitter();
  proc.exitCode = null;
  proc.killed = false;
  proc.kill = () => {
    proc.killed = true;
    return true;
  };
  proc.stdin.write = (serialized, callback) => {
    const message = JSON.parse(serialized);
    if (message.method === "initialize") {
      queueMicrotask(() => {
        proc.stdout.emit("data", Buffer.from(`${JSON.stringify({ id: message.id, result: {} })}\n`, "utf8"));
      });
    }
    queueMicrotask(() => callback?.());
    return true;
  };
  return proc;
}

test("warm Codex app-server launch cwd stays separate from the requested thread cwd", async () => {
  let spawnOptions = null;
  const client = new testHooks.CodexAppServerClient({
    resolveSpawnSpec: () => ({ command: "fake-codex", args: [], shell: false }),
    resolveHostCwd: () => expectedHostCwd,
    spawnProcess: (_command, _args, options) => {
      spawnOptions = options;
      return fakeAppServerProcess();
    },
  });
  await client.startFresh();
  assert.equal(spawnOptions.cwd, expectedHostCwd);

  const requestedCwd = path.join(testRoot, "thread-workspace");
  let threadRequest = null;
  client.request = async (method, params) => {
    threadRequest = { method, params };
    return { thread: { id: "thread-1" } };
  };
  assert.equal(await client.startThread("review", requestedCwd, "codex"), "thread-1");
  assert.equal(threadRequest.method, "thread/start");
  assert.equal(threadRequest.params.cwd, requestedCwd);
  client.stop();
});

test("a repaired per-user Codex install still runs through bundled Node", () => {
  const bundledNode = path.join(resourcesDir, "node-portable", "node.exe");
  const userCodex = path.join(cliRoot, "codex-cli", "codex.cmd");
  const userCodexJs = path.join(
    cliRoot,
    "codex-cli",
    "node_modules",
    "@openai",
    "codex",
    "bin",
    "codex.js",
  );
  fs.mkdirSync(path.dirname(bundledNode), { recursive: true });
  fs.mkdirSync(path.dirname(userCodexJs), { recursive: true });
  fs.writeFileSync(bundledNode, "node");
  fs.writeFileSync(userCodex, "codex");
  fs.writeFileSync(userCodexJs, "codex-js");

  assert.deepEqual(
    testHooks.getNodeBackedCodexSpec(userCodex, ["--version"]),
    {
      command: bundledNode,
      args: [userCodexJs, "--version"],
      shell: false,
    },
  );
});

test("CLI copies left in the profile move beside the install folder", async () => {
  const legacyClaude = path.join(userDataDir, "claude-cli", "claude.cmd");
  fs.mkdirSync(path.dirname(legacyClaude), { recursive: true });
  fs.writeFileSync(legacyClaude, "claude");
  // Until it moves, ArcBot still runs the old copy.
  assert.equal(testHooks.getClaudeCommand(), legacyClaude);

  // A link from a manual move is dropped; the copy it points at stays.
  const movedCodex = path.join(cliRoot, "codex-cli");
  fs.mkdirSync(movedCodex, { recursive: true });
  fs.writeFileSync(path.join(movedCodex, "codex.cmd"), "codex");
  fs.symlinkSync(movedCodex, path.join(userDataDir, "codex-cli"), "junction");

  await testHooks.migrateLegacyCliInstalls();

  const newClaude = path.join(cliRoot, "claude-cli", "claude.cmd");
  assert.equal(fs.readFileSync(newClaude, "utf8"), "claude");
  assert.equal(fs.existsSync(path.join(userDataDir, "claude-cli")), false);
  assert.equal(testHooks.getClaudeCommand(), newClaude);
  assert.equal(fs.existsSync(path.join(userDataDir, "codex-cli")), false);
  assert.equal(fs.readFileSync(path.join(movedCodex, "codex.cmd"), "utf8"), "codex");
  assert.equal(testHooks.getUserInstalledCodexCommand(), path.join(movedCodex, "codex.cmd"));
});
