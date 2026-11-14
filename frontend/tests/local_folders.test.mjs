import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const folders = require("../electron/local_folders.js");
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

function scratch(t) {
  const root = path.join(repoRoot, "tmp_data");
  fs.mkdirSync(root, { recursive: true });
  const dir = fs.mkdtempSync(path.join(root, "local-folders-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function write(file, text = "x") {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

test("the folder name is the one the Python API owns", () => {
  const source = fs.readFileSync(path.join(repoRoot, "python-api", "src", "arcrho_api", "config.py"), "utf8");
  const match = source.match(/^LOCAL_APP_FOLDER_NAME = "([^"]+)"$/m);
  assert.ok(match, "LOCAL_APP_FOLDER_NAME is defined in arcrho_api/config.py");
  assert.equal(folders.LOCAL_APP_FOLDER_NAME, match[1]);
});

test("every per-user folder is named Arco, with the profile inside the config folder", () => {
  const env = { APPDATA: "C:\\Users\\demo\\AppData\\Roaming" };
  assert.equal(folders.configDir("arcrho", env), path.join(env.APPDATA, "Arco"));
  assert.equal(folders.configDir("arcode", env), path.join(env.APPDATA, "Arcode"));
  assert.equal(folders.profileDir(env), path.join(env.APPDATA, "Arco", "profile"));
  assert.equal(folders.documentsDir("D:\\Docs"), path.join("D:\\Docs", "Arco"));
  assert.equal(folders.tempDir("C:\\Temp"), path.join("C:\\Temp", "Arco"));
});

test("the folders named for ArcRho are renamed once, contents intact", (t) => {
  const root = scratch(t);
  const env = { APPDATA: path.join(root, "Roaming"), LOCALAPPDATA: path.join(root, "Local") };
  const documents = path.join(root, "Documents");
  write(path.join(env.APPDATA, "ArcRho", "workspace_paths.json"), "connection");
  write(path.join(env.APPDATA, "arcrho-electron", "logs", "a.log"));
  write(path.join(env.LOCALAPPDATA, "ArcRho", "config.txt"));
  write(path.join(env.LOCALAPPDATA, "arcrho-electron-updater", "pending", "x"));
  write(path.join(documents, "ArcRho", "macros", "m.py"));

  assert.deepEqual(folders.moveRenamedFolders({ env, documentsPaths: [documents] }), []);

  assert.equal(fs.readFileSync(path.join(env.APPDATA, "Arco", "workspace_paths.json"), "utf8"), "connection");
  assert.ok(fs.existsSync(path.join(env.APPDATA, "Arco", "profile", "logs", "a.log")));
  assert.ok(fs.existsSync(path.join(env.LOCALAPPDATA, "Arco", "config.txt")));
  assert.ok(fs.existsSync(path.join(documents, "Arco", "macros", "m.py")));
  for (const gone of [
    path.join(env.APPDATA, "ArcRho"),
    path.join(env.APPDATA, "arcrho-electron"),
    path.join(env.LOCALAPPDATA, "ArcRho"),
    path.join(env.LOCALAPPDATA, "arcrho-electron-updater"),
    path.join(documents, "ArcRho"),
  ]) assert.equal(fs.existsSync(gone), false, gone);

  // A second start finds nothing left to move.
  assert.deepEqual(folders.moveRenamedFolders({ env, documentsPaths: [documents] }), []);
});

test("a new folder something else made first receives what it lacks and keeps what it has", (t) => {
  const root = scratch(t);
  const env = { APPDATA: path.join(root, "Roaming"), LOCALAPPDATA: path.join(root, "Local") };
  write(path.join(env.APPDATA, "ArcRho", "workspace_paths.json"), "connection");
  write(path.join(env.APPDATA, "ArcRho", "arcrho_gateway.json"), "old sign-in");
  write(path.join(env.APPDATA, "Arco", "arcrho_gateway.json"), "new sign-in");
  // An empty folder made under the new name must not strand the files of the old one.
  const documents = path.join(root, "Documents");
  write(path.join(documents, "ArcRho", "macros", "m.py"), "macro");
  fs.mkdirSync(path.join(documents, "Arco", "macros"), { recursive: true });

  assert.deepEqual(folders.moveRenamedFolders({ env, documentsPaths: [documents] }), []);

  assert.equal(fs.readFileSync(path.join(env.APPDATA, "Arco", "workspace_paths.json"), "utf8"), "connection");
  assert.equal(fs.readFileSync(path.join(env.APPDATA, "Arco", "arcrho_gateway.json"), "utf8"), "new sign-in");
  assert.equal(fs.readFileSync(path.join(documents, "Arco", "macros", "m.py"), "utf8"), "macro");
  assert.equal(fs.existsSync(path.join(documents, "ArcRho")), false);
});

test("a folder that cannot be moved is reported and nothing after it is tried", (t) => {
  const root = scratch(t);
  const env = { APPDATA: path.join(root, "Roaming"), LOCALAPPDATA: path.join(root, "Local") };
  write(path.join(env.APPDATA, "ArcRho", "workspace_paths.json"));
  write(path.join(env.APPDATA, "arcrho-electron", "logs", "a.log"));
  const blocked = t.mock.method(fs, "renameSync", () => {
    throw new Error("EBUSY");
  });
  const failed = folders.moveRenamedFolders({ env, documentsPaths: [path.join(root, "Documents")] });
  blocked.mock.restore();
  assert.equal(failed.length, 1);
  assert.equal(failed[0].from, path.join(env.APPDATA, "ArcRho"));
  assert.ok(fs.existsSync(path.join(env.APPDATA, "arcrho-electron", "logs", "a.log")));
});
