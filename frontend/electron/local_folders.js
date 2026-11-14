// Where the app keeps things on this PC. Every folder is named once here.
//
// LOCAL_APP_FOLDER_NAME mirrors `LOCAL_APP_FOLDER_NAME` in
// python-api/src/arcrho_api/config.py, which owns the name; this host cannot
// import Python, and tests/local_folders.test.mjs pins the mirror.
const fs = require("fs");
const os = require("os");
const path = require("path");

const LOCAL_APP_FOLDER_NAME = "Arco";
const ARCODE_FOLDER_NAME = "Arcode";

function roamingRoot(env = process.env) {
  return String(env.APPDATA || "").trim() || path.join(os.homedir(), "AppData", "Roaming");
}

function localRoot(env = process.env) {
  return String(env.LOCALAPPDATA || "").trim() || path.join(os.homedir(), "AppData", "Local");
}

// %APPDATA%\Arco (or \Arcode for standalone Arcode): the server connection, the
// Gateway sign-in, the preferences that belong to this PC, the running-app markers.
function configDir(appMode = "arcrho", env = process.env) {
  return path.join(roamingRoot(env), appMode === "arcode" ? ARCODE_FOLDER_NAME : LOCAL_APP_FOLDER_NAME);
}

// %APPDATA%\Arco\profile: the browser profile, host logs and downloaded updates.
function profileDir(env = process.env) {
  return path.join(configDir("arcrho", env), "profile");
}

// Documents\Arco: the user's own macros, scripts, workflows and templates.
function documentsDir(documentsPath = "") {
  return path.join(String(documentsPath || "").trim() || path.join(os.homedir(), "Documents"), LOCAL_APP_FOLDER_NAME);
}

// Scratch that a restart may lose.
function tempDir(tempPath = os.tmpdir()) {
  return path.join(tempPath, LOCAL_APP_FOLDER_NAME);
}

// The folders this app used while it was named ArcRho, each with the folder
// that replaces it. Order matters: the config folder moves before the profile
// that now sits inside it.
// `documentsPaths` are the Documents folders to look in: the one Windows
// reports and the one under the home folder, which differ when Documents is
// redirected.
function renamedFolders({ env = process.env, documentsPaths = [path.join(os.homedir(), "Documents")] } = {}) {
  const roaming = roamingRoot(env);
  const local = localRoot(env);
  const documents = [...new Set(documentsPaths.filter(Boolean))];
  return [
    [path.join(roaming, "ArcRho"), configDir("arcrho", env)],
    [path.join(roaming, "arcrho-electron"), profileDir(env)],
    [path.join(local, "ArcRho"), path.join(local, LOCAL_APP_FOLDER_NAME)],
    ...documents.map((folder) => [path.join(folder, "ArcRho"), documentsDir(folder)]),
  ];
}

// Moves `from` to `to`. When `to` is already there (the Excel add-in or a tool
// made it first), what `from` holds that `to` lacks moves into it instead,
// folder by folder; a file both hold stays as `to` has it.
function moveFolder(from, to) {
  if (!fs.existsSync(to)) {
    fs.mkdirSync(path.dirname(to), { recursive: true });
    fs.renameSync(from, to);
    return;
  }
  if (!fs.statSync(from).isDirectory() || !fs.statSync(to).isDirectory()) return;
  for (const name of fs.readdirSync(from)) moveFolder(path.join(from, name), path.join(to, name));
  if (!fs.readdirSync(from).length) fs.rmdirSync(from);
}

// Moves each old folder that still exists to its new name. Returns the move
// that failed, which happens when another program has something inside the
// folder open.
function moveRenamedFolders(options = {}) {
  const failures = [];
  for (const [from, to] of renamedFolders(options)) {
    if (!fs.existsSync(from)) continue;
    try {
      moveFolder(from, to);
    } catch (err) {
      // Later folders may sit inside this one, so nothing after it is tried.
      failures.push({ from, to, error: String(err?.message || err) });
      return failures;
    }
  }
  try {
    // The updater cache of an updater this app no longer uses.
    fs.rmSync(path.join(localRoot(options.env), "arcrho-electron-updater"), { recursive: true, force: true });
  } catch {
    // A leftover cache changes nothing.
  }
  return failures;
}

module.exports = {
  LOCAL_APP_FOLDER_NAME,
  configDir,
  profileDir,
  documentsDir,
  tempDir,
  renamedFolders,
  moveRenamedFolders,
};
