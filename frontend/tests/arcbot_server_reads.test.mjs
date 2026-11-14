import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// ArcBot reads project data only through the server (client_smb_retirement.md
// step 24, decision 7): its prompt and its Codex start never name the server
// folder or resolve it as a mapped drive, the run starts in the local exchange
// folder, the folders the user added still reach the prompt, and its Python
// imports this app's own arcrho_api, whose Gateway client does the reading.

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const TEST_TEMP_ROOT = path.resolve(TESTS_DIR, "..", "..", "test");
fs.mkdirSync(TEST_TEMP_ROOT, { recursive: true });
const testRoot = fs.mkdtempSync(path.join(TEST_TEMP_ROOT, "arcbot-server-reads-"));
const documentsDir = path.join(testRoot, "Documents");
const userDataDir = path.join(testRoot, "UserData");
const appRoot = path.join(testRoot, "app");
const wheelDir = path.join(appRoot, "build", "python_packages");
const wheelPath = path.join(wheelDir, "arcrho_api-0.2.1-py3-none-any.whl");
const extraFolder = path.join(testRoot, "Team Notes");
const exchangeFolder = path.join(documentsDir, "Arco", "ArcBot", "workspace");
// Use a different drive from the local fixture: resolving the explicitly
// allowed Team Notes folder must not look like resolving the server drive.
const serverDrive = path.parse(testRoot).root.toUpperCase().startsWith("Z:") ? "Y:" : "Z:";
const serverRoot = `${serverDrive}\\Fake Arco Server`;
const methodPath = `${serverRoot}\\projects\\Fake Project\\Auto\\methods\\F 1 - Paid DFM.json`;
fs.mkdirSync(userDataDir, { recursive: true });
fs.mkdirSync(wheelDir, { recursive: true });
fs.mkdirSync(extraFolder, { recursive: true });
fs.writeFileSync(wheelPath, "", "utf8");
const workspacePathsPath = path.join(userDataDir, "workspace_paths.json");
fs.writeFileSync(workspacePathsPath, JSON.stringify({ workspace_root: serverRoot }), "utf8");
fs.writeFileSync(path.join(userDataDir, "arcbot_readable_roots.json"), JSON.stringify({ folders: [extraFolder] }), "utf8");

const saved = Object.fromEntries(
  ["ARCRHO_CODEX_CMD", "ARCRHO_CODEX_APP_SERVER", "ARCRHO_SERVER_ROOT", "PYTHONPATH"].map((name) => [name, process.env[name]]),
);
process.env.ARCRHO_CODEX_CMD = path.join(testRoot, "fake-codex.exe");
process.env.ARCRHO_CODEX_APP_SERVER = "0";
delete process.env.ARCRHO_SERVER_ROOT;
delete process.env.PYTHONPATH;

const require = createRequire(import.meta.url);
const { registerArcBotIpc } = require("../electron/arcbot_host.js");
const handlers = new Map();
const hostCommands = [];

const arcBotHost = registerArcBotIpc({
  ipcMain: { handle: (name, handler) => handlers.set(name, handler) },
  app: {
    isPackaged: false,
    getPath: (name) => (name === "documents" ? documentsDir : name === "userData" ? userDataDir : testRoot),
  },
  APP_ROOT: appRoot,
  REPO_ROOT: testRoot,
  PYTHON_EXE: "python",
  getPrefsDir: () => userDataDir,
  getWorkspacePathsPath: () => workspacePathsPath,
  findExecutableOnPath: () => "",
  getAppServerUrl: () => "",
  runHostCommand: async (command, args, options) => {
    hostCommands.push({ command, args, options });
    return { ok: true, code: 0, signal: null, stdout: "Done.", stderr: "", timedOut: false, canceled: false, error: "" };
  },
});

test.after(() => {
  arcBotHost.stop();
  for (const [name, value] of Object.entries(saved)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
  fs.rmSync(testRoot, { recursive: true, force: true });
});

async function send(mode, activeContext) {
  hostCommands.length = 0;
  const result = await handlers.get("codex-assistant-send")(
    { sender: { send() {} } },
    {
      requestId: `test_${Math.random().toString(36).slice(2)}`,
      mode,
      model: "codex",
      reasoningEffort: "low",
      messages: [{ role: "user", content: "Compare this with the Liability class." }],
      activeContext,
    },
  );
  assert.equal(result.ok, true, result.error);
  const exec = hostCommands.find((call) => call.args[0] === "exec");
  assert.ok(exec, "the one-shot Codex run started");
  return { exec, prompt: String(exec.options.input || "") };
}

function assertNoServerFolder({ exec, prompt }) {
  assert.doesNotMatch(prompt, /Fake Arco Server/u, "the prompt never names the server folder");
  assert.ok(exec.args.every((arg) => !/Fake Arco Server/u.test(arg)), "the Codex start never names it");
  assert.ok(
    hostCommands.every((call) => !(call.command === "net" && String(call.args[1] || "").toUpperCase() === serverDrive)),
    "the server folder's drive is never resolved to its share",
  );
}

const dfmContext = {
  available: true,
  pageType: "dfm",
  tabType: "dfm",
  methodPath,
  targetPath: methodPath,
  fields: { project: "Fake Project", reservingClass: "Auto", methodName: "F 1 - Paid DFM" },
};

test("a review starts in the exchange folder and points the model at the Gateway client", async () => {
  const run = await send("review", dfmContext);
  assertNoServerFolder(run);
  assert.equal(run.exec.args[run.exec.args.indexOf("--cd") + 1], exchangeFolder);
  assert.ok(fs.statSync(exchangeFolder).isDirectory());
  assert.match(run.prompt, /arco_project_read/u);
  assert.match(run.prompt, /"methodPath": "F 1 - Paid DFM\.json"/u, "the page's file is named, not located");
  assert.match(run.prompt, /"project": "Fake Project"/u);
  assert.ok(run.prompt.includes(`Extra folders the user allowed you to read: ${extraFolder}`));
});

test("an edit stages the page's JSON under the exchange folder without naming the server folder", async () => {
  const run = await send("edit", { ...dfmContext, activeJson: { method: "F 1 - Paid DFM" } });
  assertNoServerFolder(run);
  const staged = path.join(exchangeFolder, "projects", "Fake Project", "Auto", "methods", "F 1 - Paid DFM.json");
  assert.ok(fs.existsSync(staged), "the copy keeps the project's layout under the exchange folder");
  assert.equal(run.exec.args[run.exec.args.indexOf("--cd") + 1], exchangeFolder);
  assert.ok(run.prompt.includes("projects\\Fake Project\\Auto\\methods\\F 1 - Paid DFM.json"));
});

test("ArcBot's Python imports this app's own arcrho_api", async () => {
  const run = await send("review", { available: false });
  const [first] = String(run.exec.options.env.PYTHONPATH || "").split(path.delimiter);
  assert.equal(first, wheelPath, "with no source folder the bundled wheel is on the import path");
});
