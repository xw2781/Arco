const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const { StringDecoder } = require("string_decoder");
const { PreparedArcBotSessions } = require("./arcbot_prepared_session");
const { arcBotTurnActivity } = require("./arcbot_turn_events");
const { registerArcBotVoice } = require("./arcbot_voice");
const { PROJECT_READ_TOOL, readArcBotProject } = require("./arcbot_project_read");
const { RUN_MACRO_TOOL, buildSkillPrompt, runSkillMacro } = require("./arcbot_skill_tools");
const { createArcBotAccounts, decodeJwtPayload } = require("./arcbot_accounts");
const { currentAgent, isCertTrustError, loadWindowsRootAgent } = require("./arcbot_windows_roots");
const { runClaudeCliTurn } = require("./arcbot_claude_cli");
const preparedSessions = new PreparedArcBotSessions();
let arcBotAccounts = null;
const { formatJsonForSave } = require("./persisted_json_text");
const { pruneAgedLogFiles } = require("./log_retention");
const {
  buildClaudeModelCatalog,
  buildCodexModelCatalog,
  getFallbackClaudeModelCatalog,
  getFallbackCodexModelCatalog,
  normalizeModelId,
  normalizeReasoningEffort,
} = require("./arcbot_model_catalog");

let ipcMain = null;
let app = null;
let APP_ROOT = "";
let REPO_ROOT = "";
let PYTHON_EXE = "python";
let PYTHON_API_SRC = "";
let PYTHON_API_WHEEL_DIR = "";
let getPrefsDir = () => "";
let getWorkspacePathsPath = () => "";
let getAppServerUrl = () => "";
let findExecutableOnPath = () => "";
let runHostCommandBase = null;
let spawnProcessBase = spawn;

const ARCBOT_PROMPT_TEMPLATE_PATH = path.join(__dirname, "prompts", "arcbot_prompt.md");
// Shown in the Prompt Guide for an instruction file the server does not hold
// yet; never written anywhere.
const ARCBOT_SERVER_INSTRUCTION_PLACEHOLDERS = [
  ["data_labels.md", "# Data Labels\n\nAdd shared definitions for dataset labels, triangle names, abbreviations, and common naming patterns.\n"],
  ["dfm_workflow.md", "# DFM Workflow\n\nAdd DFM-specific review, analysis, and editing practices.\n"],
  ["reserving_practice.md", "# Reserving Practice\n\nAdd reserving workflow expectations, review standards, and business judgment notes.\n"],
  ["project_workflow.md", "# Project Workflow\n\nAdd project, reserving class, and folder conventions.\n"],
  ["scripting_console.md", "# Arcode Scripting\n\nAdd notebook-editor and code-editor usage guidance.\n"],
  ["excel_addin.md", "# Excel Add-in\n\nAdd Excel add-in, UDF, and request-handler workflow guidance.\n"],
];

const ARCBOT_READABLE_ROOTS_FILE = "arcbot_readable_roots.json";
const ARCBOT_UI_SETTINGS_FILE = "arcbot_ui_settings.json";
const ARCBOT_CHAT_SESSIONS_DIR = "arcbot_chat_sessions";
const ARCBOT_CODEX_COMMAND_HINT_FILE = "arcbot_codex_command.json";
const CODEX_ASSISTANT_TIMEOUT_MS = Math.max(
  15000,
  parseInt(process.env.ARCRHO_CODEX_ASSISTANT_TIMEOUT_MS || "1800000", 10) || 1800000
);
const CODEX_ASSISTANT_CONTEXT_WINDOW_TOKENS = Math.max(
  1000,
  parseInt(process.env.ARCRHO_CODEX_ASSISTANT_CONTEXT_WINDOW_TOKENS || "200000", 10) || 200000
);
const CODEX_APP_SERVER_MAX_FRAME_CHARS = 16 * 1024 * 1024;
const CODEX_APP_SERVER_ENABLED = process.env.ARCRHO_CODEX_APP_SERVER !== "0";
const ARCBOT_PROMPT_FILES_TIMEOUT_MS = 15000;
const mappedDriveRemoteCache = new Map();
const activeCodexAssistantRequests = new Map();
const arcBotRequestLoggers = new Map();
let codexAppServerClient = null;
let codexModelCatalogCache = null;
let codexModelCatalogRequest = null;
let codexModelCatalogGeneration = 0;
// Discovered model lists are re-read after this long, so a long-running app still picks up new models.
const ARCBOT_MODEL_CATALOG_TTL_MS = 6 * 60 * 60 * 1000;
let codexModelCatalogCachedAt = 0;
let claudeModelCatalogCache = null;
let claudeModelCatalogCachedAt = 0;

  const runHostCommand = (command, args = [], options = {}) => {
    if (typeof runHostCommandBase !== "function") {
      return Promise.resolve({ ok: false, code: null, stdout: "", stderr: "Host command runner is unavailable" });
    }
    let commandOptions;
    try {
      commandOptions = withArcBotHostCwd(options);
    } catch (err) {
      return Promise.resolve({
        ok: false,
        code: -1,
        signal: null,
        stdout: "",
        stderr: "",
        timedOut: false,
        canceled: false,
        error: `ArcBot working directory is unavailable: ${String(err?.message || err || "unknown error")}`,
      });
    }
    return runHostCommandBase(command, args, {
      ...commandOptions,
      cancelRegistry: activeCodexAssistantRequests,
    });
  };

function getArcBotReadableRootsPath() {
  return path.join(getPrefsDir(), ARCBOT_READABLE_ROOTS_FILE);
}

function getArcBotUiSettingsPath() {
  return path.join(getPrefsDir(), ARCBOT_UI_SETTINGS_FILE);
}

function getPythonApiWheelPath() {
  try {
    const wheels = fs.readdirSync(PYTHON_API_WHEEL_DIR)
      .filter((name) => /^arcrho_api-.*\.whl$/iu.test(name))
      .sort();
    return wheels.length ? path.join(PYTHON_API_WHEEL_DIR, wheels[wheels.length - 1]) : "";
  } catch {
    return "";
  }
}

function getArcBotChatSessionsDir() {
  return path.join(app.getPath("userData"), ARCBOT_CHAT_SESSIONS_DIR);
}

function getArcBotCodexCommandHintPath() {
  return path.join(app.getPath("userData"), ARCBOT_CODEX_COMMAND_HINT_FILE);
}

function readArcBotCodexCommandHint() {
  try {
    const raw = fs.readFileSync(getArcBotCodexCommandHintPath(), "utf8");
    const parsed = JSON.parse(raw);
    const command = String(parsed?.command || "").trim();
    if (command && fs.existsSync(command) && !isWindowsAppsPath(command)) return command;
  } catch {
    // Missing or stale hints are ignored; normal command discovery still runs.
  }
  return "";
}

function writeArcBotCodexCommandHint(command) {
  const value = String(command || "").trim();
  if (!value) return;
  try {
    fs.mkdirSync(path.dirname(getArcBotCodexCommandHintPath()), { recursive: true });
    fs.writeFileSync(getArcBotCodexCommandHintPath(), JSON.stringify({
      command: value,
      updatedAt: new Date().toISOString(),
    }, null, 2), "utf8");
  } catch {
    // A hint failure should not turn a successful CLI install into a failed install.
  }
}

function sanitizeArcBotSessionId(value) {
  return String(value || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 80);
}

function createArcBotChatSessionId() {
  return `chat-${new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 14)}-${crypto.randomBytes(4).toString("hex")}`;
}

function getArcBotChatSessionPath(sessionId) {
  const safeId = sanitizeArcBotSessionId(sessionId);
  if (!safeId) return "";
  return path.join(getArcBotChatSessionsDir(), `${safeId}.json`);
}

function normalizeArcBotMessages(messages) {
  if (!Array.isArray(messages)) return [];
  return messages.slice(-80).map((message) => ({
    role: String(message?.role || "").toLowerCase() === "assistant" ? "assistant"
      : String(message?.role || "").toLowerCase() === "system" ? "system"
      : "user",
    content: String(message?.content || ""),
    timestamp: String(message?.timestamp || new Date().toISOString()),
  })).filter((message) => message.content.trim());
}

function normalizeArcBotActivities(activities) {
  if (!Array.isArray(activities)) return [];
  return activities.slice(-120).map((activity) => ({
    type: String(activity?.type || "info").slice(0, 32),
    text: String(activity?.text || "").slice(0, 16000),
    elapsedMs: Number.isFinite(activity?.elapsedMs) ? Math.max(0, Math.round(activity.elapsedMs)) : null,
    timestamp: String(activity?.timestamp || new Date().toISOString()),
  })).filter((activity) => activity.text.trim());
}

function normalizeArcBotDebugLogs(logs) {
  if (!Array.isArray(logs)) return [];
  return logs.slice(-300).map((entry) => ({
    type: String(entry?.type || "debug").slice(0, 32),
    text: String(entry?.text || "").slice(0, 8000),
    timestamp: String(entry?.timestamp || new Date().toISOString()),
  })).filter((entry) => entry.text.trim());
}

function normalizeArcBotModel(model) {
  return normalizeModelId(model, "codex");
}

function normalizeArcBotReasoningEffort(effort) {
  return normalizeReasoningEffort(effort);
}

function isClaudeArcBotModel(model) {
  return String(model || "").startsWith("claude-");
}

function getClaudeCredentialsPath() {
  return arcBotAccounts
    ? arcBotAccounts.authFilePath(arcBotAccounts.active("claude"))
    : path.join(os.homedir(), ".claude", ".credentials.json");
}

function loadClaudeAuthToken() {
  try {
    const raw = fs.readFileSync(getClaudeCredentialsPath(), "utf8");
    const creds = JSON.parse(raw);
    const oauth = creds?.claudeAiOauth;
    if (!oauth?.accessToken) return null;
    const expiresAt = Number(oauth.expiresAt || 0);
    if (expiresAt && Date.now() > expiresAt) return null;
    return String(oauth.accessToken);
  } catch {
    return null;
  }
}

// The CLI renews an expired access token itself, so a refresh token is enough.
function hasClaudeSignIn() {
  try {
    const oauth = JSON.parse(fs.readFileSync(getClaudeCredentialsPath(), "utf8"))?.claudeAiOauth;
    return !!(oauth?.refreshToken || loadClaudeAuthToken());
  } catch {
    return false;
  }
}

function extractEmailFromText(value) {
  const match = String(value || "").match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/iu);
  return match ? match[0] : "";
}

function findEmailInCodexAuthValue(value, depth = 0, keyHint = "") {
  if (depth > 8 || value == null) return "";
  if (typeof value === "string") {
    const direct = extractEmailFromText(value);
    if (direct) return direct;
    if (/token|jwt/iu.test(keyHint)) {
      const decoded = decodeJwtPayload(value);
      const decodedEmail = findEmailInCodexAuthValue(decoded, depth + 1);
      if (decodedEmail) return decodedEmail;
    }
    return "";
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const email = findEmailInCodexAuthValue(item, depth + 1);
      if (email) return email;
    }
    return "";
  }
  if (typeof value !== "object") return "";

  const entries = Object.entries(value);
  const emailEntry = entries.find(([key, entryValue]) => (
    /email/iu.test(key) && typeof entryValue === "string" && extractEmailFromText(entryValue)
  ));
  if (emailEntry) return extractEmailFromText(emailEntry[1]);

  for (const [key, entryValue] of entries) {
    const email = findEmailInCodexAuthValue(entryValue, depth + 1, key);
    if (email) return email;
  }
  return "";
}

function getCodexAuthCandidatePaths() {
  const candidates = new Set();
  const addAuthFiles = (root) => {
    const cleanRoot = String(root || "").trim();
    if (!cleanRoot) return;
    for (const name of ["auth.json", "credentials.json", "profile.json", "config.json"]) {
      candidates.add(path.join(cleanRoot, name));
    }
  };
  const account = arcBotAccounts?.active("codex");
  // An added account's sign-in lives only in its own folder.
  if (account && !account.builtin) return [path.join(account.configDir, "auth.json")];
  addAuthFiles(account ? account.configDir : path.join(os.homedir(), ".codex"));
  addAuthFiles(process.env.APPDATA ? path.join(process.env.APPDATA, "OpenAI", "Codex") : "");
  addAuthFiles(process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "OpenAI", "Codex") : "");
  return Array.from(candidates);
}

function readCodexLoginEmail(authOutput = "") {
  const outputEmail = extractEmailFromText(authOutput);
  if (outputEmail) return outputEmail;

  for (const filePath of getCodexAuthCandidatePaths()) {
    try {
      if (!fs.existsSync(filePath)) continue;
      const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
      const email = findEmailInCodexAuthValue(parsed);
      if (email) return email;
    } catch {
      // Auth/profile file formats vary by Codex version; unreadable candidates are ignored.
    }
  }
  return "";
}

function getUserClaudeInstallPrefix() {
  return path.join(getArcBotCliRoot(), "claude-cli");
}

function getClaudeCommand() {
  const installed = cliCommandIn(getUserClaudeInstallPrefix(), "claude");
  if (fs.existsSync(installed)) return installed;
  const legacy = cliCommandIn(path.join(getLegacyCliRoot(), "claude-cli"), "claude");
  if (fs.existsSync(legacy)) return legacy;
  if (process.platform === "win32") {
    const candidates = [
      process.env.APPDATA ? path.join(process.env.APPDATA, "npm", "claude.cmd") : "",
      findExecutableOnPath(["claude.cmd", "claude.exe"]),
    ].filter(Boolean);
    for (const candidate of candidates) {
      try {
        if (fs.existsSync(candidate)) return candidate;
      } catch {}
    }
    return "";
  }
  return findExecutableOnPath(["claude"]) || "";
}

// A dashboard page sends its whole document (without its saved tables), how to
// edit it, and the numbers its charts show. A Claude turn has no file to edit,
// so in Edit Mode it returns the edited document in its reply instead and the
// host hands that to the page exactly as a Codex edit is handed over.
const CLAUDE_DASHBOARD_JSON_LIMIT = 120000;
const JSON_FENCE = "```";

function isArcBotDashboardContext(activeContext) {
  return String(activeContext?.pageType || "").trim().toLowerCase() === "dashboard";
}

function buildClaudeDashboardPrompt(mode, activeContext, activeJson) {
  const parts = [];
  if (activeContext?.assistantGuide) parts.push(String(activeContext.assistantGuide));
  if (activeContext?.dashboardPage) {
    const shown = JSON.stringify(activeContext.dashboardPage).slice(0, 40000);
    parts.push(["What the open dashboard page shows now:", `${JSON_FENCE}json`, shown, JSON_FENCE].join("\n"));
  }
  const jsonText = activeJson && !activeJson.error ? JSON.stringify(activeJson) : "";
  if (!jsonText) return parts;
  parts.push(["The dashboard document:", `${JSON_FENCE}json`, jsonText.slice(0, CLAUDE_DASHBOARD_JSON_LIMIT), JSON_FENCE].join("\n"));
  // An edit replaces the whole document, so it is offered only when the whole document was sent.
  if (mode === "edit" && jsonText.length <= CLAUDE_DASHBOARD_JSON_LIMIT) {
    parts.push([
      "To change the dashboard, reply with one JSON object and nothing else:",
      '{"action":"edited","reply":"<short summary for the user>","dashboard":{...the complete updated dashboard document...}}',
      "Return the whole document, not a fragment. When the request needs no change, answer in plain text instead.",
    ].join("\n"));
  }
  return parts;
}

// The edited dashboard a Claude reply carries, or null when the reply is an answer.
function extractClaudeDashboardEdit(rawText) {
  const structured = extractJsonObject(rawText);
  const dashboard = structured?.action === "edited" ? structured.dashboard : null;
  if (!dashboard || typeof dashboard !== "object" || !Array.isArray(dashboard.pages)) return null;
  return { reply: String(structured.reply || "").trim(), dashboard };
}

// A skill needs the whole ratio triangle, so a skill turn lifts the active-data cap.
function buildClaudeSystemPrompt(mode, activeContext, activeJson, skill = null) {
  const parts = [
    "You are ArcBot, an AI assistant embedded in Arco Workspace, an actuarial reserving and analytics platform.",
    mode === "edit"
      ? "You are in Edit Mode. Provide clear, actionable guidance to help the user work with their data and models."
      : "You are in Read-Only Review Mode. Analyze and explain; do not modify any data or files.",
  ];
  if (activeContext?.available) {
    const tabLabel = activeContext.title || activeContext.tabType || "active tab";
    parts.push(`Current app context: ${tabLabel}${activeContext.tabType ? ` (${activeContext.tabType})` : ""}.`);
    if (activeContext.targetPath) parts.push(`Active file: ${withFileNamesOnly(activeContext.targetPath)}`);
  }
  if (isArcBotDashboardContext(activeContext)) {
    parts.push(...buildClaudeDashboardPrompt(mode, activeContext, activeJson));
  } else if (activeJson && typeof activeJson === "object" && !activeJson.error) {
    const jsonStr = JSON.stringify(activeJson, null, skill ? 0 : 2).slice(0, skill ? 150000 : 12000);
    parts.push(`Active page data:\n\`\`\`json\n${jsonStr}\n\`\`\``);
  }
  if (skill) {
    parts.push(`Project, class and method open in the UI:\n${JSON.stringify(withFileNamesOnly({ fields: activeContext?.fields, activeNestedWindow: activeContext?.activeNestedWindow }))}`);
    parts.push("Use the arco_project_read tool for any data not shown above (call kind=catalog first).");
    parts.push(buildSkillPrompt(skill));
  }
  return parts.join("\n\n");
}

// The signed-in Claude Code token is only ever sent to api.anthropic.com.
function getClaudeApiHeaders(authToken) {
  return {
    "Authorization": `Bearer ${authToken}`,
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
  };
}

function listClaudeModelEntries(authToken, agent = currentAgent()) {
  const https = require("https");
  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: "api.anthropic.com",
      path: "/v1/models?limit=100",
      method: "GET",
      headers: getClaudeApiHeaders(authToken),
      timeout: 10000,
      agent,
    }, (res) => {
      let body = "";
      res.on("data", (chunk) => { body += chunk; });
      res.on("end", () => {
        if (res.statusCode !== 200) {
          reject(new Error(`Anthropic models API error ${res.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body)?.data);
        } catch (err) {
          reject(err);
        }
      });
      res.on("error", reject);
    });
    req.on("timeout", () => req.destroy(new Error("Anthropic models API timed out.")));
    req.on("error", (err) => {
      if (agent || !isCertTrustError(err)) { reject(err); return; }
      loadWindowsRootAgent().then((rootAgent) => (rootAgent
        ? listClaudeModelEntries(authToken, rootAgent).then(resolve, reject)
        : reject(err)));
    });
    req.end();
  });
}

async function getClaudeModelCatalog(options = {}) {
  const fresh = Date.now() - claudeModelCatalogCachedAt < ARCBOT_MODEL_CATALOG_TTL_MS;
  if (claudeModelCatalogCache && fresh && options.refresh !== true) return claudeModelCatalogCache;
  const authToken = loadClaudeAuthToken();
  if (!authToken) return claudeModelCatalogCache || getFallbackClaudeModelCatalog();
  try {
    claudeModelCatalogCache = buildClaudeModelCatalog(await listClaudeModelEntries(authToken));
    claudeModelCatalogCachedAt = Date.now();
    return claudeModelCatalogCache;
  } catch (err) {
    return {
      ...(claudeModelCatalogCache || getFallbackClaudeModelCatalog()),
      warning: String(err?.message || err || "Claude model discovery failed."),
    };
  }
}

// The Claude CLI to run a turn with: its native program, or Node with its script.
// The .cmd launcher is skipped, because cmd.exe would mangle the JSON arguments.
function getClaudeCliSpawnSpec() {
  const configured = String(process.env.ARCRHO_CLAUDE_CMD || "").trim();
  if (configured) {
    return /\.(c?js|mjs)$/iu.test(configured)
      ? { command: process.execPath, commandArgs: [configured] }
      : { command: configured, commandArgs: [] };
  }
  const launcher = getClaudeCommand();
  if (!launcher) return null;
  if (!/\.(cmd|bat)$/iu.test(launcher)) return { command: launcher, commandArgs: [] };
  const packageDir = path.join(path.dirname(launcher), "node_modules", "@anthropic-ai", "claude-code");
  const nativeCli = path.join(packageDir, "bin", "claude.exe");
  if (fs.existsSync(nativeCli)) return { command: nativeCli, commandArgs: [] };
  const scriptCli = path.join(packageDir, "cli.js");
  const bundledNode = path.join(getBundledNodePortableRoot(), "node.exe");
  if (fs.existsSync(scriptCli) && fs.existsSync(bundledNode)) return { command: bundledNode, commandArgs: [scriptCli] };
  return null;
}

// A Claude turn runs through the Claude CLI under the active Claude account. A
// skill turn hands the CLI ArcBot's tools; each call shows in the work log.
async function runClaudeArcBotRequest({ event, requestId, requestState, model, reasoningEffort, systemText, messages, attachments, usage, tools = [], runTool = null, cwd }) {
  const spec = getClaudeCliSpawnSpec();
  if (!spec) {
    void installClaudeCli();
    return { ok: false, error: "The Claude CLI is being installed. Try again in a minute." };
  }
  // Current Claude models think adaptively; effort is the only depth control, and Haiku takes none.
  const modelOption = (claudeModelCatalogCache || getFallbackClaudeModelCatalog()).models
    .find((entry) => entry.value === model);
  const supportedEfforts = (modelOption?.supportedReasoningEfforts || []).map((entry) => entry.value);
  const effort = supportedEfforts.includes(reasoningEffort)
    ? reasoningEffort
    : modelOption?.defaultReasoningEffort || "";
  const chat = (Array.isArray(messages) ? messages : [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m, i, arr) => {
      let content = String(m.content || "");
      if (m.role === "user" && i === arr.length - 1 && Array.isArray(attachments) && attachments.length) {
        content += attachments.map((a) => `\n\n--- Attached: ${a.name} ---\n${a.text}`).join("");
      }
      return { role: m.role, content };
    });
  const loggedTool = runTool && (async (params) => {
    sendArcBotActivity(event, requestId, "command", `${params.tool}\n${JSON.stringify(params.arguments)}`, { itemId: params.callId });
    try {
      const output = await runTool(params);
      sendArcBotActivity(event, requestId, "command-output", `\n${output}`, { itemId: params.callId });
      return output;
    } catch (error) {
      sendArcBotActivity(event, requestId, "command-output", `\n${String(error?.message || error || "Tool call failed.")}`, { itemId: params.callId });
      throw error;
    }
  });
  const result = await runClaudeCliTurn({
    ...spec,
    env: arcBotAccounts ? arcBotAccounts.envFor(arcBotAccounts.active("claude"), process.env) : { ...process.env },
    cwd: cwd || getArcBotHostCwd(),
    model,
    effort,
    systemText,
    messages: chat,
    tools,
    runTool: loggedTool,
    requestState,
    // The reply streams into the chat bubble; commentary and thinking go to the work log.
    onText: (chunk) => sendArcBotActivity(event, requestId, "assistant-delta", chunk),
    onReset: (text) => {
      sendArcBotActivity(event, requestId, "assistant-reset", "");
      if (text) sendArcBotActivity(event, requestId, "assistant-delta", text);
    },
    onCommentary: ({ id, text }) => sendArcBotActivity(event, requestId, "commentary", text, { itemId: id }),
    onThinking: ({ id, text }) => sendArcBotActivity(event, requestId, "thinking", text, { itemId: id }),
    onThinkingTokens: (tokens) => sendArcBotActivity(event, requestId, "thinking-tokens", "", { tokens }),
  });
  if (!result.ok) return result;
  const { inputTokens, outputTokens } = result.usage || {};
  if (inputTokens || outputTokens) {
    const total = inputTokens + outputTokens;
    sendArcBotActivity(event, requestId, "usage",
      `Context: ~${total.toLocaleString()} tokens (${inputTokens.toLocaleString()} in, ${outputTokens.toLocaleString()} out).`,
      { usage: { ...(usage || {}), estimatedTokens: total } });
  }
  return { ok: true, stdout: result.stdout };
}

function getArcBotRuntimeModel(model) {
  const normalized = normalizeArcBotModel(model);
  if (normalized !== "codex") return normalized;
  const detectedDefault = String(codexModelCatalogCache?.defaultModel || "").trim();
  return detectedDefault && detectedDefault !== "codex" ? detectedDefault : null;
}

function reconcileArcBotReasoningEffort(model, effort) {
  const normalizedEffort = normalizeArcBotReasoningEffort(effort);
  const runtimeModel = getArcBotRuntimeModel(model);
  const option = runtimeModel
    ? codexModelCatalogCache?.models?.find((entry) => entry.value === runtimeModel)
    : null;
  const supported = Array.isArray(option?.supportedReasoningEfforts)
    ? option.supportedReasoningEfforts.map((entry) => String(entry?.value || "").trim()).filter(Boolean)
    : [];
  if (!supported.length || supported.includes(normalizedEffort)) return normalizedEffort;
  const catalogDefault = String(option?.defaultReasoningEffort || "").trim();
  return supported.includes(catalogDefault) ? catalogDefault : supported[0];
}

function deriveArcBotSessionTitle(messages, fallback = "New ArcBot Chat") {
  const firstUser = normalizeArcBotMessages(messages).find((message) => message.role === "user");
  const title = String(firstUser?.content || fallback).replace(/\s+/g, " ").trim();
  return title.length > 42 ? `${title.slice(0, 39)}...` : title || fallback;
}

function readArcBotChatSession(sessionId) {
  const filePath = getArcBotChatSessionPath(sessionId);
  if (!filePath || !fs.existsSync(filePath)) return null;
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    if (!parsed || sanitizeArcBotSessionId(parsed.id) !== sanitizeArcBotSessionId(sessionId)) return null;
    return {
      id: sanitizeArcBotSessionId(parsed.id),
      title: String(parsed.title || "ArcBot Chat"),
      createdAt: String(parsed.createdAt || new Date().toISOString()),
      updatedAt: String(parsed.updatedAt || parsed.createdAt || new Date().toISOString()),
      mode: String(parsed.mode || "edit"),
      model: normalizeArcBotModel(parsed.model),
      reasoningEffort: normalizeArcBotReasoningEffort(parsed.reasoningEffort),
      archived: parsed.archived === true,
      messages: normalizeArcBotMessages(parsed.messages),
      activities: normalizeArcBotActivities(parsed.activities),
      debugLogs: normalizeArcBotDebugLogs(parsed.debugLogs),
      context: parsed.context && typeof parsed.context === "object" ? parsed.context : null,
      usage: parsed.usage && typeof parsed.usage === "object" ? parsed.usage : null,
    };
  } catch {
    return null;
  }
}

function writeArcBotChatSession(sessionLike) {
  const now = new Date().toISOString();
  const existing = sessionLike?.id ? readArcBotChatSession(sessionLike.id) : null;
  const id = sanitizeArcBotSessionId(sessionLike?.id) || createArcBotChatSessionId();
  const messages = normalizeArcBotMessages(sessionLike?.messages || existing?.messages || []);
  const session = {
    id,
    title: String(sessionLike?.title || existing?.title || deriveArcBotSessionTitle(messages)).slice(0, 80),
    createdAt: String(existing?.createdAt || sessionLike?.createdAt || now),
    updatedAt: now,
    mode: String(sessionLike?.mode || existing?.mode || "edit"),
    model: normalizeArcBotModel(sessionLike?.model || existing?.model),
    reasoningEffort: normalizeArcBotReasoningEffort(sessionLike?.reasoningEffort || existing?.reasoningEffort),
    archived: Object.prototype.hasOwnProperty.call(sessionLike || {}, "archived")
      ? sessionLike?.archived === true
      : existing?.archived === true,
    messages,
    activities: normalizeArcBotActivities(sessionLike?.activities || existing?.activities || []),
    debugLogs: normalizeArcBotDebugLogs(sessionLike?.debugLogs || existing?.debugLogs || []),
    context: sessionLike?.context && typeof sessionLike.context === "object" ? sessionLike.context : existing?.context || null,
    usage: sessionLike?.usage && typeof sessionLike.usage === "object" ? sessionLike.usage : existing?.usage || null,
  };
  fs.mkdirSync(getArcBotChatSessionsDir(), { recursive: true });
  const filePath = getArcBotChatSessionPath(id);
  const tmpPath = `${filePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(session, null, 2), "utf8");
  fs.renameSync(tmpPath, filePath);
  return session;
}

function listArcBotChatSessions(options = {}) {
  const includeArchived = options?.includeArchived === true;
  fs.mkdirSync(getArcBotChatSessionsDir(), { recursive: true });
  return fs.readdirSync(getArcBotChatSessionsDir())
    .filter((name) => /\.json$/i.test(name))
    .map((name) => readArcBotChatSession(path.basename(name, ".json")))
    .filter(Boolean)
    .filter((session) => includeArchived || !session.archived)
    .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)))
    .map((session) => ({
      id: session.id,
      title: session.title,
      updatedAt: session.updatedAt,
      createdAt: session.createdAt,
      messageCount: session.messages.length,
      archived: session.archived === true,
    }));
}

function archiveArcBotChatSession(sessionId, archived = true) {
  const session = readArcBotChatSession(sessionId);
  if (!session) return null;
  return writeArcBotChatSession({ ...session, archived: !!archived });
}

function deleteArcBotChatSession(sessionId) {
  const filePath = getArcBotChatSessionPath(sessionId);
  if (!filePath || !fs.existsSync(filePath)) return false;
  fs.unlinkSync(filePath);
  return true;
}

// The configured server folder, as text only. ArcBot never opens it and never
// names it to the model: it only strips it from a staged file's path so the
// exchange copy keeps the project's layout.
function getConfiguredWorkspaceRoot() {
  // The launch override wins, as it does for the app server (arcrho_api.config).
  const launchRoot = String(process.env.ARCRHO_SERVER_ROOT || "").trim();
  if (launchRoot) return launchRoot;
  try {
    const filePath = getWorkspacePathsPath();
    if (!fs.existsSync(filePath)) return "";
    const raw = fs.readFileSync(filePath, "utf8");
    const parsed = JSON.parse(raw);
    return String(parsed?.workspace_root || "").trim();
  } catch {
    return "";
  }
}

function getLocalArcRhoAssistantRoot() {
  let documentsPath = "";
  try {
    documentsPath = String(app?.getPath?.("documents") || "").trim();
  } catch {
    // Fall back to the conventional user-local Documents folder.
  }
  if (!documentsPath) {
    const userHome = process.env.USERPROFILE || os.homedir();
    documentsPath = path.join(userHome, "Documents");
  }
  return path.join(documentsPath, "ArcRho");
}

function ensureLocalArcRhoAssistantRoot() {
  const localRoot = getLocalArcRhoAssistantRoot();
  fs.mkdirSync(localRoot, { recursive: true });
  return localRoot;
}

function getArcBotHostCwd() {
  const hostCwd = ensureLocalArcRhoAssistantRoot();
  if (/(?:^|[\\/])[^\\/]+\.asar(?:[\\/]|$)/iu.test(hostCwd)) {
    throw new Error(`ArcBot cannot launch a process from an ASAR path: ${hostCwd}`);
  }
  fs.accessSync(hostCwd, fs.constants.W_OK);
  return hostCwd;
}

function withArcBotHostCwd(options = {}, resolveHostCwd = getArcBotHostCwd) {
  const requestedCwd = String(options?.cwd || "").trim();
  return {
    ...options,
    cwd: requestedCwd || resolveHostCwd(),
  };
}

function launchDetachedArcBotProcess(command, args = [], options = {}) {
  const {
    spawnProcess = spawnProcessBase,
    resolveHostCwd = getArcBotHostCwd,
    ...requestedOptions
  } = options;
  return new Promise((resolve) => {
    let child;
    try {
      child = spawnProcess(command, args, withArcBotHostCwd({
        detached: true,
        stdio: "ignore",
        windowsHide: false,
        shell: false,
        ...requestedOptions,
      }, resolveHostCwd));
    } catch (err) {
      resolve({ ok: false, error: String(err?.message || err || "ArcBot could not launch the sign-in window.") });
      return;
    }

    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    child.once("error", (err) => {
      finish({ ok: false, error: String(err?.message || err || "ArcBot could not launch the sign-in window.") });
    });
    child.once("spawn", () => {
      child.unref();
      finish({ ok: true });
    });
  });
}

function parseNetUseRemoteName(output) {
  const match = String(output || "").match(/^\s*Remote name\s+(.+?)\s*$/im);
  return match ? match[1].trim() : "";
}

function toMappedDriveUncPath(localPath, remoteName) {
  const text = String(localPath || "").trim();
  const remote = String(remoteName || "").trim();
  if (!/^[A-Za-z]:[\\/]/u.test(text) || !/^\\\\[^\\]+\\[^\\]+/u.test(remote)) return text;
  const rest = text.slice(2).replace(/^[\\/]+/u, "");
  return rest ? path.win32.join(remote, rest) : remote;
}

function normalizeComparablePath(filePath) {
  return String(filePath || "")
    .trim()
    .replace(/[\\/]+/g, "\\")
    .replace(/\\+$/u, "")
    .toLowerCase();
}

function isPathWithinRoot(filePath, rootPath) {
  const file = normalizeComparablePath(filePath);
  const root = normalizeComparablePath(rootPath);
  if (!file || !root) return false;
  return file === root || file.startsWith(`${root}\\`);
}

async function resolveMappedDrivePath(localPath) {
  const text = String(localPath || "").trim();
  if (process.platform !== "win32" || !/^[A-Za-z]:[\\/]/u.test(text)) return text;

  const drive = text.slice(0, 2).toUpperCase();
  if (!mappedDriveRemoteCache.has(drive)) {
    const result = await runHostCommand("net", ["use", drive], {
      timeoutMs: 3000,
      shell: false,
    });
    mappedDriveRemoteCache.set(drive, result.ok ? parseNetUseRemoteName(combinedCommandOutput(result)) : "");
  }

  const remoteName = mappedDriveRemoteCache.get(drive);
  return remoteName ? toMappedDriveUncPath(text, remoteName) : text;
}

async function getArcBotReadableRootsForSandbox() {
  const roots = [];
  for (const root of readArcBotReadableRoots()) {
    roots.push(await resolveMappedDrivePath(root));
  }
  return normalizeSandboxRoots(roots);
}

function getBundledNpmCommand() {
  if (process.platform === "win32") {
    const bundled = path.join(getBundledNodePortableRoot(), "npm.cmd");
    return fs.existsSync(bundled) ? bundled : "";
  }
  const bundled = path.join(getBundledNodePortableRoot(), "npm");
  return fs.existsSync(bundled) ? bundled : "";
}

function getBundledResourceRoot() {
  return app?.isPackaged && process.resourcesPath ? process.resourcesPath : APP_ROOT;
}

function getBundledNodePortableRoot() {
  return path.join(getBundledResourceRoot(), "node-portable");
}

function getNpmCommand() {
  const configured = String(process.env.ARCRHO_NPM_CMD || "").trim();
  if (configured) return configured;
  return getBundledNpmCommand() || "npm";
}

const ARCBOT_CLI_FOLDER = "ArcBot CLI";
const ARCBOT_CLI_NAMES = ["codex-cli", "claude-cli"];

// Where copies before 2026-11 went: the Electron profile, always on C:.
function getLegacyCliRoot() {
  let userDataRoot = "";
  try {
    userDataRoot = String(app?.getPath?.("userData") || "").trim();
  } catch {
    // Fall through to the existing ArcRho preferences root.
  }
  return userDataRoot || getPrefsDir() || getLocalArcRhoAssistantRoot();
}

// The CLIs sit beside the install folder, on the drive the user installed to.
// Not inside it: every update empties the install folder. A dev run keeps them
// in the repo's ignored tmp_data folder.
function getArcBotCliRoot() {
  if (app?.isPackaged && process.resourcesPath) {
    const installDir = path.dirname(process.resourcesPath);
    const parent = path.dirname(installDir);
    if (parent && parent !== installDir) return path.join(parent, ARCBOT_CLI_FOLDER);
  } else if (REPO_ROOT) {
    return path.join(REPO_ROOT, "tmp_data", "arcbot-cli");
  }
  return getLegacyCliRoot();
}

function getUserCodexInstallPrefix() {
  return path.join(getArcBotCliRoot(), "codex-cli");
}

// Moves copies left in the profile to the new folder. Runs in the background;
// until a copy has moved, the command lookups still find it at the old place.
let cliMigration = null;
function migrateLegacyCliInstalls() {
  if (cliMigration) return cliMigration;
  cliMigration = (async () => {
    const legacyRoot = getLegacyCliRoot();
    const newRoot = getArcBotCliRoot();
    if (path.resolve(legacyRoot).toLowerCase() === path.resolve(newRoot).toLowerCase()) return;
    for (const name of ARCBOT_CLI_NAMES) {
      const from = path.join(legacyRoot, name);
      const to = path.join(newRoot, name);
      try {
        if (!fs.existsSync(from)) continue;
        // A link left by a manual move points at the copy; drop only the link.
        if (fs.lstatSync(from).isSymbolicLink()) {
          if (fs.existsSync(to)) fs.rmSync(from, { recursive: true, force: true });
          continue;
        }
        if (!fs.existsSync(to)) {
          await fs.promises.mkdir(newRoot, { recursive: true });
          try {
            await fs.promises.rename(from, to);
            continue;
          } catch {
            // Another drive: copy to a staging folder so a half copy is never used.
          }
          const staging = `${to}.moving`;
          await fs.promises.rm(staging, { recursive: true, force: true });
          await fs.promises.cp(from, staging, { recursive: true, verbatimSymlinks: true });
          await fs.promises.rename(staging, to);
        }
        await fs.promises.rm(from, { recursive: true, force: true, maxRetries: 3 });
      } catch (error) {
        // A running CLI can lock its files; the next start tries again.
        console.warn(`[ArcBot] Could not move ${from} to ${to}: ${error?.message || error}`);
      }
    }
  })().finally(() => {
    cliMigration = null;
  });
  return cliMigration;
}

function cliCommandIn(prefix, name) {
  return process.platform === "win32"
    ? path.join(prefix, `${name}.cmd`)
    : path.join(prefix, "bin", name);
}

function getUserInstalledCodexCommand() {
  const installed = cliCommandIn(getUserCodexInstallPrefix(), "codex");
  if (fs.existsSync(installed)) return installed;
  const legacy = cliCommandIn(path.join(getLegacyCliRoot(), "codex-cli"), "codex");
  return fs.existsSync(legacy) ? legacy : installed;
}

function isWindowsAppsPath(filePath) {
  return /\\WindowsApps\\/iu.test(String(filePath || ""));
}

function getCodexCommand() {
  const configured = String(process.env.ARCRHO_CODEX_CMD || "").trim();
  if (configured) return configured;

  if (process.platform === "win32") {
    const candidates = [
      getUserInstalledCodexCommand(),
      path.join(getBundledNodePortableRoot(), "codex.cmd"),
      readArcBotCodexCommandHint(),
      process.env.APPDATA ? path.join(process.env.APPDATA, "npm", "codex.cmd") : "",
      process.env.LOCALAPPDATA
        ? path.join(process.env.LOCALAPPDATA, "OpenAI", "Codex", "bin", "codex.cmd")
        : "",
      findExecutableOnPath(["codex.cmd", "codex.exe"]),
    ].filter(Boolean);
    for (const candidate of candidates) {
      try {
        if (fs.existsSync(candidate) && !isWindowsAppsPath(candidate)) return candidate;
      } catch {
        // Try the next candidate.
      }
    }
    return "";
  }

  return findExecutableOnPath(["codex"]) || "codex";
}

function extractCodexCommandFromInstallOutput(output) {
  const match = String(output || "").match(/^ARCRHO_CODEX_CMD=(.+)$/imu);
  return match ? match[1].trim() : "";
}

// ArcBot's Python imports this app's own arcrho_api: the source folder in
// development, else the bundled wheel, which is pure Python and imports
// straight from the path. Its Gateway client then signs with this app's
// credential and knows the same read kinds as the app. Codex itself runs
// under the active ArcBot account unless the caller names another.
function getArcBotCodexEnv(env = process.env, account = arcBotAccounts?.active("codex")) {
  const nextEnv = account ? arcBotAccounts.envFor(account, env) : { ...env };
  const wheelPath = getPythonApiWheelPath();
  const importRoot = fs.existsSync(PYTHON_API_SRC) ? PYTHON_API_SRC : wheelPath;
  if (importRoot) {
    const existing = String(nextEnv.PYTHONPATH || nextEnv.PythonPath || "");
    nextEnv.PYTHONPATH = existing
      ? `${importRoot}${path.delimiter}${existing}`
      : importRoot;
  }
  if (fs.existsSync(PYTHON_API_SRC)) nextEnv.ARCRHO_PYTHON_API_SRC = PYTHON_API_SRC;
  nextEnv.ARCRHO_PYTHON_API_WHEEL_DIR = PYTHON_API_WHEEL_DIR;
  if (wheelPath) nextEnv.ARCRHO_PYTHON_API_WHEEL = wheelPath;
  return nextEnv;
}

function quoteWindowsCmdArg(value) {
  const text = String(value ?? "");
  if (!text) return '""';
  if (!/[\s"]/u.test(text)) return text;
  return `"${text.replace(/"/g, '""')}"`;
}

function runWindowsCmdCommand(command, args = [], options = {}) {
  const commandLine = [command, ...args].map(quoteWindowsCmdArg).join(" ");
  return runHostCommand("cmd.exe", ["/d", "/c", "call", commandLine], {
    ...options,
    shell: false,
  });
}

function getNodeBackedCodexSpec(command, args = []) {
  if (process.platform !== "win32" || !/\.cmd$/iu.test(String(command || ""))) return null;
  const bundledNode = path.join(getBundledNodePortableRoot(), "node.exe");
  const codexJs = path.join(
    path.dirname(command),
    "node_modules",
    "@openai",
    "codex",
    "bin",
    "codex.js",
  );
  if (!fs.existsSync(bundledNode) || !fs.existsSync(codexJs)) return null;
  return {
    command: bundledNode,
    args: [codexJs, ...args.map((arg) => String(arg))],
    shell: false,
  };
}

function runCodexCommand(args = [], options = {}) {
  const command = getCodexCommand();
  if (!command) {
    return Promise.resolve({
      ok: false,
      code: -1,
      signal: null,
      stdout: "",
      stderr: "",
      timedOut: false,
      error: "Codex CLI was not found. Install Codex CLI before using ArcBot.",
    });
  }
  if (process.platform === "win32") {
    const nodeSpec = getNodeBackedCodexSpec(command, args);
    if (nodeSpec) {
      return runHostCommand(nodeSpec.command, nodeSpec.args, {
        ...options,
        env: getArcBotCodexEnv(options.env || process.env, options.account),
        shell: false,
      });
    }
    if (/\.(cmd|bat)$/iu.test(command)) {
      return runWindowsCmdCommand(command, args, {
        ...options,
        env: getArcBotCodexEnv(options.env || process.env, options.account),
      });
    }
    return runHostCommand(command, args, {
      ...options,
      env: getArcBotCodexEnv(options.env || process.env, options.account),
      shell: false,
    });
  }
  return runHostCommand(command, args, {
    ...options,
    env: getArcBotCodexEnv(options.env || process.env, options.account),
    shell: false,
  });
}

function getCodexSpawnSpec(args = []) {
  const command = getCodexCommand();
  if (!command) return null;
  const nextArgs = args.map((arg) => String(arg));
  if (process.platform === "win32") {
    const nodeSpec = getNodeBackedCodexSpec(command, nextArgs);
    if (nodeSpec) return nodeSpec;
    if (/\.(cmd|bat)$/iu.test(command)) {
      const commandLine = [command, ...nextArgs].map(quoteWindowsCmdArg).join(" ");
      return { command: "cmd.exe", args: ["/d", "/c", "call", commandLine], shell: false };
    }
  }
  return { command, args: nextArgs, shell: false };
}

function normalizeSandboxRoots(paths = []) {
  const seen = new Set();
  const roots = [];
  for (const candidate of paths) {
    const value = String(candidate || "").trim();
    if (!value) continue;
    const key = normalizeComparablePath(value);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    roots.push(value);
  }
  return roots;
}

function normalizeArcBotReadableRootEntries(paths = []) {
  const seen = new Set();
  const roots = [];
  for (const candidate of Array.isArray(paths) ? paths : []) {
    const raw = String(candidate || "").trim();
    if (!raw) continue;
    const resolved = path.resolve(raw);
    const key = normalizeComparablePath(resolved);
    if (!key || seen.has(key)) continue;
    try {
      if (!fs.existsSync(resolved) || !fs.statSync(resolved).isDirectory()) continue;
    } catch {
      continue;
    }
    seen.add(key);
    roots.push(resolved);
  }
  return roots.slice(0, 30);
}

function readArcBotReadableRoots() {
  const filePath = getArcBotReadableRootsPath();
  if (!fs.existsSync(filePath)) return [];
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, "utf8"));
    return normalizeArcBotReadableRootEntries(parsed?.folders || parsed?.roots || []);
  } catch {
    return [];
  }
}

function writeArcBotReadableRoots(paths = []) {
  const roots = normalizeArcBotReadableRootEntries(paths);
  const filePath = getArcBotReadableRootsPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify({
    version: 1,
    updatedAt: new Date().toISOString(),
    folders: roots,
  }, null, 2), "utf8");
  fs.renameSync(tmpPath, filePath);
  return roots;
}

function normalizeArcBotStoragePrefix(value) {
  return String(value || "arcrho").trim().replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 40) || "arcrho";
}

function normalizeArcBotUiSettings(settingsLike) {
  const raw = settingsLike && typeof settingsLike === "object" && !Array.isArray(settingsLike)
    ? settingsLike
    : {};
  const launcherVisibleByApp = raw.launcherVisibleByApp && typeof raw.launcherVisibleByApp === "object" && !Array.isArray(raw.launcherVisibleByApp)
    ? raw.launcherVisibleByApp
    : {};
  const normalized = {};
  for (const [key, value] of Object.entries(launcherVisibleByApp)) {
    const prefix = normalizeArcBotStoragePrefix(key);
    if (typeof value === "boolean") normalized[prefix] = value;
  }
  return {
    version: 1,
    launcherVisibleByApp: normalized,
  };
}

function readArcBotUiSettings() {
  const filePath = getArcBotUiSettingsPath();
  if (!fs.existsSync(filePath)) return normalizeArcBotUiSettings();
  try {
    return normalizeArcBotUiSettings(JSON.parse(fs.readFileSync(filePath, "utf8")));
  } catch {
    return normalizeArcBotUiSettings();
  }
}

function writeArcBotUiSettings(settingsLike) {
  const current = readArcBotUiSettings();
  const incoming = normalizeArcBotUiSettings(settingsLike);
  const payload = {
    version: 1,
    updatedAt: new Date().toISOString(),
    launcherVisibleByApp: {
      ...current.launcherVisibleByApp,
      ...incoming.launcherVisibleByApp,
    },
  };
  const filePath = getArcBotUiSettingsPath();
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(payload, null, 2), "utf8");
  fs.renameSync(tmpPath, filePath);
  return payload;
}

function getCodexSandboxPolicy(sandboxMode, codexCwd) {
  if (sandboxMode === "workspace-write") {
    return {
      type: "workspaceWrite",
      writableRoots: [codexCwd],
      networkAccess: false,
      excludeTmpdirEnvVar: false,
      excludeSlashTmp: false,
    };
  }
  return {
    type: "readOnly",
    networkAccess: false,
  };
}

function extractAgentTextFromTurn(turn) {
  const items = Array.isArray(turn?.items) ? turn.items : [];
  const messages = items
    .filter((item) => item?.type === "agentMessage" && String(item?.text || "").trim())
    .map((item) => String(item.text || "").trim());
  return messages.length ? messages[messages.length - 1] : "";
}

function getCodexNotificationIdentity(message) {
  return {
    threadId: String(message?.params?.threadId || message?.params?.turn?.threadId || ""),
    turnId: String(message?.params?.turnId || message?.params?.turn?.id || ""),
  };
}

function isCodexNotificationForTurn(
  message,
  { threadId, turnId = "", allowPendingTurn = false } = {}
) {
  const identity = getCodexNotificationIdentity(message);
  if (identity.threadId && identity.threadId !== threadId) return false;
  if (!turnId) {
    return !!allowPendingTurn && identity.threadId === threadId && !!identity.turnId;
  }
  if (identity.turnId && identity.turnId !== turnId) return false;
  return !!(identity.threadId || identity.turnId);
}

function getCodexInterruptParams(threadId, turnId) {
  const normalizedThreadId = String(threadId || "");
  const normalizedTurnId = String(turnId || "");
  return normalizedThreadId && normalizedTurnId
    ? { threadId: normalizedThreadId, turnId: normalizedTurnId }
    : null;
}

class CodexAppServerClient {
  constructor(options = {}) {
    this.spawnProcess = typeof options.spawnProcess === "function" ? options.spawnProcess : spawnProcessBase;
    this.resolveSpawnSpec = typeof options.resolveSpawnSpec === "function"
      ? options.resolveSpawnSpec
      : getCodexSpawnSpec;
    this.resolveHostCwd = typeof options.resolveHostCwd === "function"
      ? options.resolveHostCwd
      : getArcBotHostCwd;
    this.proc = null;
    this.started = false;
    this.starting = null;
    this.nextId = 1;
    this.pending = new Map();
    this.notificationHandlers = new Set();
    this.toolHandlers = new Map();
    this.disconnectHandlers = new Set();
    this.stdoutBuffer = "";
    this.stdoutDecoder = new StringDecoder("utf8");
    this.stderr = "";
    this.lastError = "";
  }

  isAlive() {
    return !!this.proc && !this.proc.killed && this.proc.exitCode == null;
  }

  async start() {
    if (this.started && this.isAlive()) return this;
    if (this.starting) {
      await this.starting;
      return this;
    }
    this.starting = this.startFresh();
    try {
      await this.starting;
      return this;
    } finally {
      this.starting = null;
    }
  }

  async startFresh() {
    this.stop();
    const spec = this.resolveSpawnSpec(["app-server", "--listen", "stdio://"]);
    if (!spec) throw new Error("Codex CLI was not found. Install Codex CLI before using ArcBot.");
    const proc = this.spawnProcess(spec.command, spec.args, withArcBotHostCwd({
      env: getArcBotCodexEnv(process.env),
      shell: spec.shell,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    }, this.resolveHostCwd));
    this.proc = proc;
    this.started = false;
    this.stdoutBuffer = "";
    this.stdoutDecoder = new StringDecoder("utf8");
    this.stderr = "";
    this.lastError = "";
    proc.stdout?.on("data", (chunk) => this.handleStdout(chunk, proc));
    proc.stderr?.on("data", (chunk) => {
      if (this.proc !== proc) return;
      const text = String(chunk || "");
      this.stderr += text;
      if (this.stderr.length > 200000) this.stderr = this.stderr.slice(-200000);
    });
    proc.stdin?.on("error", (err) => {
      this.handleProcessFailure(
        proc,
        `Codex app-server input failed: ${String(err?.message || err || "unknown error")}`,
      );
    });
    proc.once("error", (err) => {
      this.handleProcessFailure(proc, String(err?.message || err || "Codex app-server failed."));
    });
    proc.once("close", (code, signal) => {
      this.handleProcessFailure(
        proc,
        `Codex app-server exited (code=${code ?? "unknown"}, signal=${signal || "none"}).`,
      );
    });
    await this.request("initialize", {
      clientInfo: { name: "Arco ArcBot", title: "Arco ArcBot", version: "0.1.0" },
      capabilities: {
        experimentalApi: true,
      },
    }, 15000);
    this.notify("initialized");
    this.started = true;
  }

  stop() {
    const proc = this.proc;
    this.toolHandlers.clear();
    this.proc = null;
    this.started = false;
    this.stdoutBuffer = "";
    this.stdoutDecoder = new StringDecoder("utf8");
    if (proc && proc.exitCode == null && !proc.killed) {
      try {
        proc.kill();
      } catch {
        // ignore
      }
    }
    this.failAll("Codex app-server stopped.");
  }

  handleProcessFailure(proc, message) {
    if (!proc || this.proc !== proc) return false;
    const detail = String(message || "Codex app-server disconnected.");
    this.proc = null;
    this.started = false;
    this.stdoutBuffer = "";
    this.stdoutDecoder = new StringDecoder("utf8");
    this.lastError = detail;
    if (proc.exitCode == null && !proc.killed) {
      try {
        proc.kill();
      } catch {
        // ignore
      }
    }
    this.failAll(detail);
    return true;
  }

  failAll(message) {
    for (const [, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error(message));
    }
    this.pending.clear();
    for (const handler of this.disconnectHandlers) {
      try {
        handler(String(message || "Codex app-server disconnected."));
      } catch {
        // One stale listener should not block other disconnect observers.
      }
    }
  }

  handleStdout(chunk, proc = this.proc) {
    if (proc && this.proc !== proc) return;
    const bytes = Buffer.isBuffer(chunk)
      ? chunk
      : Buffer.from(String(chunk ?? ""), "utf8");
    this.stdoutBuffer += this.stdoutDecoder.write(bytes);
    let newlineIndex = this.stdoutBuffer.indexOf("\n");
    while (newlineIndex >= 0) {
      if (newlineIndex > CODEX_APP_SERVER_MAX_FRAME_CHARS) {
        this.handleProcessFailure(proc, "Codex app-server returned an oversized protocol frame.");
        return;
      }
      const line = this.stdoutBuffer.slice(0, newlineIndex).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
      if (line) this.handleMessageLine(line);
      newlineIndex = this.stdoutBuffer.indexOf("\n");
    }
    if (this.stdoutBuffer.length > CODEX_APP_SERVER_MAX_FRAME_CHARS) {
      this.handleProcessFailure(proc, "Codex app-server returned an oversized protocol frame.");
    }
  }

  handleMessageLine(line) {
    let message = null;
    try {
      message = JSON.parse(line);
    } catch {
      this.stderr += `${line}\n`;
      return;
    }
    if (message?.method) {
      if (Object.prototype.hasOwnProperty.call(message, "id")) {
        const handler = message.method === "item/tool/call" && this.toolHandlers.get(message.params?.threadId);
        if (handler) {
          const proc = this.proc;
          void Promise.resolve().then(() => handler(message.params)).then(
            text => ({ success: true, contentItems: [{ type: "inputText", text: String(text) }] }),
            error => ({ success: false, contentItems: [{ type: "inputText", text: String(error.message || error) }] }),
          ).then(result => { if (this.proc === proc && this.isAlive()) this.writeMessage({ id: message.id, result }); }).catch(() => {});
          return;
        }
        this.respondUnsupported(message.id, message.method);
        return;
      }
      for (const handler of this.notificationHandlers) {
        try {
          handler(message);
        } catch {
          // One stale listener should not break the app-server stream.
        }
      }
      return;
    }
    if (message && Object.prototype.hasOwnProperty.call(message, "id")) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) {
        const detail = String(message.error?.message || message.error || "Codex app-server request failed.");
        pending.reject(new Error(detail));
      } else {
        pending.resolve(message.result);
      }
      return;
    }
  }

  writeMessage(message) {
    const proc = this.proc;
    if (!proc || proc.killed || proc.exitCode != null || typeof proc.stdin?.write !== "function") {
      throw new Error("Codex app-server is not running.");
    }
    const serialized = `${JSON.stringify(message)}\n`;
    try {
      proc.stdin.write(serialized, (err) => {
        if (!err) return;
        this.handleProcessFailure(
          proc,
          `Codex app-server input failed: ${String(err?.message || err || "unknown error")}`,
        );
      });
    } catch (err) {
      this.handleProcessFailure(
        proc,
        `Codex app-server input failed: ${String(err?.message || err || "unknown error")}`,
      );
      throw err;
    }
  }

  request(method, params, timeoutMs = CODEX_ASSISTANT_TIMEOUT_MS) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Codex app-server ${method} timed out.`));
      }, Math.max(1000, timeoutMs));
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.writeMessage({ id, method, params });
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  notify(method, params) {
    this.writeMessage(params === undefined ? { method } : { method, params });
  }

  respondUnsupported(id, method) {
    try {
      this.writeMessage({
        id,
        error: {
          code: -32601,
          message: `Arco does not handle Codex app-server request '${method}'.`,
        },
      });
    } catch {
      // ignore
    }
  }

  onNotification(handler) {
    this.notificationHandlers.add(handler);
    return () => this.notificationHandlers.delete(handler);
  }

  onDisconnect(handler) {
    this.disconnectHandlers.add(handler);
    return () => this.disconnectHandlers.delete(handler);
  }

  async listModels(options = {}) {
    const pageLimit = Math.min(100, Math.max(1, Number(options.limit) || 100));
    const maxPages = Math.min(5, Math.max(1, Number(options.maxPages) || 3));
    const timeoutMs = Math.min(15000, Math.max(1000, Number(options.timeoutMs) || 5000));
    const models = [];
    const seenCursors = new Set();
    let cursor = "";

    for (let page = 0; page < maxPages; page += 1) {
      const result = await this.request("model/list", {
        limit: pageLimit,
        includeHidden: false,
        ...(cursor ? { cursor } : {}),
      }, timeoutMs);
      if (Array.isArray(result?.data)) models.push(...result.data);
      const nextCursor = String(result?.nextCursor || "").trim();
      if (!nextCursor || seenCursors.has(nextCursor)) break;
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    }
    return models;
  }

  async startThread(mode, codexCwd, model) {
    const result = await this.request("thread/start", {
      model: getArcBotRuntimeModel(model),
      cwd: codexCwd,
      approvalPolicy: "never",
      sandbox: mode === "edit" ? "workspace-write" : "read-only",
      ephemeral: true,
      dynamicTools: [PROJECT_READ_TOOL, RUN_MACRO_TOOL],
    });
    const threadId = String(result?.thread?.id || "");
    if (!threadId) throw new Error("Codex app-server did not return a thread id.");
    return threadId;
  }
}

async function ensureCodexAppServerStarted() {
  if (!CODEX_APP_SERVER_ENABLED) throw new Error("Codex app-server is disabled.");
  if (!codexAppServerClient) codexAppServerClient = new CodexAppServerClient();
  return codexAppServerClient.start();
}

function resetCodexAppServerClient() {
  preparedSessions.clear();
  codexAppServerClient?.stop();
  codexAppServerClient = null;
  codexModelCatalogCache = null;
  codexModelCatalogRequest = null;
  codexModelCatalogGeneration += 1;
}

async function discoverCodexModelCatalog() {
  const fresh = Date.now() - codexModelCatalogCachedAt < ARCBOT_MODEL_CATALOG_TTL_MS;
  if (codexModelCatalogCache && fresh) return codexModelCatalogCache;
  if (!codexModelCatalogRequest) {
    const requestGeneration = codexModelCatalogGeneration;
    const previous = codexModelCatalogCache;
    const request = (async () => {
      try {
        const client = await ensureCodexAppServerStarted();
        const entries = await client.listModels();
        const catalog = buildCodexModelCatalog(entries);
        if (catalog.source !== "codex-app-server") {
          throw new Error("Codex app-server returned no visible models.");
        }
        if (requestGeneration === codexModelCatalogGeneration) {
          codexModelCatalogCache = catalog;
          codexModelCatalogCachedAt = Date.now();
        }
        return catalog;
      } catch (err) {
        // A failed timed re-read keeps the last verified list rather than blocking sends.
        if (previous) return previous;
        throw err;
      }
    })();
    codexModelCatalogRequest = request;
    const clearRequest = () => {
      if (codexModelCatalogRequest === request) codexModelCatalogRequest = null;
    };
    void request.then(clearRequest, clearRequest);
  }
  return codexModelCatalogRequest;
}

async function getCodexModelCatalog(options = {}) {
  if (options.refresh === true) {
    if (activeCodexAssistantRequests.size === 0) resetCodexAppServerClient();
    else codexModelCatalogCache = null;
  }
  try {
    const catalog = await discoverCodexModelCatalog();
    return { ok: true, ...catalog, warning: "" };
  } catch (err) {
    return {
      ok: true,
      ...getFallbackCodexModelCatalog(),
      warning: String(err?.message || err || "Codex model discovery failed."),
    };
  }
}

async function startCodexWarmThread({ isCanceled, mode, codexCwd, model, ensureClient = ensureCodexAppServerStarted }) {
  if (isCanceled()) return { canceled: true, client: null, threadId: "" };
  const client = await ensureClient();
  if (isCanceled()) return { canceled: true, client, threadId: "" };
  const threadId = await client.startThread(mode, codexCwd, model);
  if (isCanceled()) return { canceled: true, client, threadId };
  return { canceled: false, client, threadId };
}

async function runCodexWarmTurn({ event, requestId, requestState, payload, mode, model, reasoningEffort, codexCwd, codexSandbox, prompt, skill = null, ensureClient = ensureCodexAppServerStarted }) {
  let client = null;
  let threadId = "";
  let turnId = "";
  let agentText = "";
  let canceled = false;
  let agentStartedSent = false;
  let lastNotificationSummary = "";
  let waitTimer = null;
  let assistantDeltaTimer = null;
  let assistantDeltaBuffer = "";
  let removeNotificationHandler = null;
  let removeDisconnectHandler = null;
  let earlyDisconnectError = null;
  let resolveCompletedTurn = null;
  let rejectCompletedTurn = null;
  const queuedNotifications = [];
  const cancelTurn = () => {
    canceled = true;
    const interruptParams = getCodexInterruptParams(threadId, turnId);
    if (client && interruptParams) {
      client.request("turn/interrupt", interruptParams, 8000).catch(() => {});
    }
    return true;
  };
  if (requestState) {
    requestState.cancelProcess = cancelTurn;
    if (requestState.canceled) cancelTurn();
  }
  const startup = payload?.sessionId ? await (async () => {
    const warmClient = await ensureClient();
    const prepared = await preparedSessions.take(event.sender.id, payload.sessionId, model, codexCwd, warmClient);
    return { ...prepared, canceled: canceled || !!requestState?.canceled };
  })() : await startCodexWarmThread({
    isCanceled: () => canceled || !!requestState?.canceled,
    mode,
    codexCwd,
    model,
    ensureClient,
  });
  client = startup.client;
  threadId = startup.threadId;
  if (startup.canceled) {
    void client?.request("thread/unsubscribe", { threadId }, 5000).catch(() => {});
    return { ok: false, canceled: true, stdout: "", stderr: "", error: "Request canceled." };
  }
  const flushAssistantDelta = () => {
    if (!assistantDeltaBuffer) return;
    const delta = assistantDeltaBuffer;
    assistantDeltaBuffer = "";
    sendArcBotActivity(event, requestId, "assistant-delta", delta);
  };
  const queueAssistantDelta = (delta) => {
    if (!delta || payload?.streamDeltas === false) return;
    assistantDeltaBuffer += delta;
    if (assistantDeltaTimer) return;
    assistantDeltaTimer = setTimeout(() => {
      assistantDeltaTimer = null;
      flushAssistantDelta();
    }, 32);
  };
  const cleanupTurnWait = () => {
    client.toolHandlers.delete(threadId);
    if (waitTimer) clearTimeout(waitTimer);
    waitTimer = null;
    if (assistantDeltaTimer) clearTimeout(assistantDeltaTimer);
    assistantDeltaTimer = null;
    flushAssistantDelta();
    removeNotificationHandler?.();
    removeNotificationHandler = null;
    removeDisconnectHandler?.();
    removeDisconnectHandler = null;
  };
  const completedTurn = new Promise((resolve, reject) => {
    resolveCompletedTurn = resolve;
    rejectCompletedTurn = reject;
  });
  const handleTurnNotification = (message) => {
    if (!turnId) {
      if (isCodexNotificationForTurn(message, { threadId, allowPendingTurn: true })) {
        queuedNotifications.push(message);
      }
      return;
    }
    if (!isCodexNotificationForTurn(message, { threadId, turnId })) return;

    const activity = arcBotTurnActivity(message);
    if (activity?.text) sendArcBotActivity(event, requestId, activity.type, activity.text, { itemId: activity.itemId });
    if (message?.method === "item/started" && message.params?.item?.type === "agentMessage") {
      agentText = "";
      assistantDeltaBuffer = "";
      sendArcBotActivity(event, requestId, "assistant-reset", "");
    }
    if (message?.method === "item/completed" && message.params?.item?.type === "agentMessage") {
      agentText = String(message.params.item.text || agentText);
      if (message.params.item.phase === "commentary") {
        // The work log already shows this commentary; drop its streamed copy from the reply bubble.
        if (assistantDeltaTimer) clearTimeout(assistantDeltaTimer);
        assistantDeltaTimer = null;
        assistantDeltaBuffer = "";
        sendArcBotActivity(event, requestId, "assistant-reset", "");
      }
    }
    if (message?.method === "item/agentMessage/delta") {
      const delta = String(message.params?.delta || "");
      agentText += delta;
      queueAssistantDelta(delta);
      if (!agentStartedSent) {
        agentStartedSent = true;
        sendArcBotActivity(event, requestId, "activity", "ArcBot is drafting a response.");
      }
    } else if (!activity) {
      const notificationSummary = summarizeCodexTurnNotification(message);
      const summary = typeof notificationSummary === "string"
        ? notificationSummary
        : String(notificationSummary?.text || "");
      if (summary && summary !== lastNotificationSummary) {
        lastNotificationSummary = summary;
        const extra = notificationSummary && typeof notificationSummary === "object"
          ? { debugText: notificationSummary.debugText || "" }
          : {};
        sendArcBotActivity(event, requestId, "activity", summary, extra);
      }
    }
    if (message?.method === "turn/completed") {
      cleanupTurnWait();
      resolveCompletedTurn(message.params?.turn || null);
    } else if (message?.method === "error") {
      const turnError = message.params?.error;
      const detail = String(
        turnError?.message
        || turnError?.additionalDetails
        || message.params?.message
        || "Codex app-server turn failed."
      );
      if (message.params?.willRetry) {
        sendArcBotActivity(event, requestId, "activity", "Codex is retrying the current turn.", {
          debugText: detail,
        });
        return;
      }
      cleanupTurnWait();
      rejectCompletedTurn(new Error(detail));
    }
  };
  removeNotificationHandler = client.onNotification(handleTurnNotification);
  client.toolHandlers.set(threadId, async params => {
    if (canceled || requestState?.canceled || (turnId && params.turnId !== turnId)) throw new Error("The ArcBot turn is no longer active.");
    sendArcBotActivity(event, requestId, "command", `${params.tool}\n${JSON.stringify(params.arguments)}`, { itemId: params.callId });
    const output = await executeArcBotTool(params, payload.activeContext, skill).catch(error => {
      sendArcBotActivity(event, requestId, "command-output", `\n${error.message || error}`, { itemId: params.callId });
      throw error;
    });
    sendArcBotActivity(event, requestId, "command-output", `\n${output}`, { itemId: params.callId });
    return output;
  });
  removeDisconnectHandler = client.onDisconnect((message) => {
    const error = new Error(String(message || "Codex app-server disconnected."));
    if (!turnId) {
      earlyDisconnectError = error;
      return;
    }
    cleanupTurnWait();
    rejectCompletedTurn(error);
  });

  try {
    const outputSchema = payload?.outputSchema && typeof payload.outputSchema === "object"
      ? payload.outputSchema
      : null;
    const started = await client.request("turn/start", {
      threadId,
      input: [{ type: "text", text: prompt, text_elements: [] }],
      cwd: codexCwd,
      model: getArcBotRuntimeModel(model),
      effort: normalizeArcBotReasoningEffort(reasoningEffort),
      approvalPolicy: "never",
      sandboxPolicy: getCodexSandboxPolicy(codexSandbox, codexCwd),
      ...(outputSchema ? { outputSchema } : {}),
    });
    turnId = String(started?.turn?.id || "");
    if (!turnId) throw new Error("Codex app-server did not return a turn id.");
    if (earlyDisconnectError) throw earlyDisconnectError;
    sendArcBotActivity(event, requestId, "activity", "Codex warm session accepted the request.");
    if (canceled || requestState?.canceled) {
      cancelTurn();
      return { ok: false, canceled: true, stdout: "", stderr: "", error: "Request canceled." };
    }
    let turn = null;
    if (["completed", "failed", "interrupted"].includes(String(started?.turn?.status || ""))) {
      queuedNotifications.length = 0;
      cleanupTurnWait();
      turn = started.turn;
    } else {
      waitTimer = setTimeout(() => {
        cleanupTurnWait();
        rejectCompletedTurn(new Error("Codex app-server turn timed out."));
      }, CODEX_ASSISTANT_TIMEOUT_MS);
      queuedNotifications.splice(0).forEach(handleTurnNotification);
      turn = await completedTurn;
    }
    if (canceled || requestState?.canceled) {
      return { ok: false, canceled: true, stdout: "", stderr: "", error: "Request canceled." };
    }
    const turnStatus = String(turn?.status || "");
    if (turnStatus === "failed") {
      throw new Error(String(turn?.error?.message || turn?.error?.additionalDetails || "Codex app-server turn failed."));
    }
    if (turnStatus === "interrupted") {
      return { ok: false, canceled: true, stdout: "", stderr: "", error: "Request canceled." };
    }
    const turnText = extractAgentTextFromTurn(turn);
    return {
      ok: true,
      code: 0,
      signal: null,
      stdout: String(turnText || agentText || "").trim(),
      stderr: "",
      timedOut: false,
      canceled: false,
    };
  } finally {
    cleanupTurnWait();
    if (threadId) void client.request("thread/unsubscribe", { threadId }, 5000).catch(() => {});
  }
}

function combinedCommandOutput(result) {
  return `${result?.stdout || ""}\n${result?.stderr || ""}`.trim();
}

function normalizeHostError(result, fallback) {
  if (result?.canceled) return "Request canceled.";
  if (result?.timedOut) return "The command timed out.";
  return combinedCommandOutput(result) || result?.error || fallback;
}

function isAuthFailure(result) {
  const raw = combinedCommandOutput(result).toLowerCase();
  return /not\s+logged\s+in|not\s+authenticated|authentication|required|sign\s*in|login/.test(raw);
}

function getArcBotSessionRoot() {
  return path.join(ensureLocalArcRhoAssistantRoot(), "ArcBot", "sessions");
}

function getArcBotWorkspaceRoot() {
  return path.join(ensureLocalArcRhoAssistantRoot(), "ArcBot", "workspace");
}

function getArcBotRequestLogsDir() {
  return path.join(ensureLocalArcRhoAssistantRoot(), "ArcBot", "request_logs");
}

// One request writes one file here, so the folder is pruned on the first
// request of each host process rather than on every request.
let requestLogsPruned = false;

function sanitizeLogFilePart(value, fallback = "request") {
  const cleaned = String(value || "")
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  return cleaned || fallback;
}

function truncateLogValue(value, maxLength = 4000) {
  const text = typeof value === "string" ? value : (() => {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value ?? "");
    }
  })();
  return text.length > maxLength ? `${text.slice(0, maxLength)}... [truncated ${text.length - maxLength} chars]` : text;
}

function safeLogDetails(details = {}) {
  if (!details || typeof details !== "object") return {};
  const safe = {};
  for (const [key, value] of Object.entries(details)) {
    if (value == null || typeof value === "number" || typeof value === "boolean") {
      safe[key] = value;
    } else if (typeof value === "string") {
      safe[key] = truncateLogValue(value);
    } else {
      safe[key] = truncateLogValue(value, 8000);
    }
  }
  return safe;
}

function createArcBotRequestLogger({ requestId, payload, mode, model, reasoningEffort }) {
  const startedAtMs = Date.now();
  const startedAtIso = new Date(startedAtMs).toISOString();
  const sessionId = sanitizeArcBotSessionId(payload?.sessionId || "");
  const logDir = getArcBotRequestLogsDir();
  fs.mkdirSync(logDir, { recursive: true });
  if (!requestLogsPruned) {
    requestLogsPruned = true;
    pruneAgedLogFiles(logDir, { suffixes: [".json"] });
  }
  const fileName = `${startedAtIso.replace(/[:.]/g, "-")}_${sanitizeLogFilePart(requestId || sessionId)}.json`;
  const filePath = path.join(logDir, fileName);
  let lastMs = startedAtMs;
  let finalized = false;
  const activePhases = new Map();
  const log = {
    requestId,
    sessionId,
    mode,
    model,
    reasoningEffort,
    startedAt: startedAtIso,
    endedAt: "",
    totalMs: 0,
    status: "running",
    filePath,
    events: [],
    phases: [],
  };
  const nowRelative = () => {
    const nowMs = Date.now();
    const elapsedMs = nowMs - startedAtMs;
    const deltaMs = nowMs - lastMs;
    lastMs = nowMs;
    return { nowMs, elapsedMs, deltaMs };
  };
  let lastFlushMs = 0;
  const flush = () => {
    try {
      fs.writeFileSync(filePath, JSON.stringify(log, null, 2) + "\n", "utf8");
    } catch {
      // Diagnostics logging must not break ArcBot requests.
    }
  };
  const flushSoon = (nowMs, force = false) => {
    if (!force && nowMs - lastFlushMs < 1000) return;
    lastFlushMs = nowMs;
    flush();
  };
  const mark = (name, details = {}) => {
    if (finalized) return;
    const timing = nowRelative();
    log.events.push({
      type: "mark",
      name,
      elapsedMs: timing.elapsedMs,
      deltaMs: timing.deltaMs,
      timestamp: new Date(timing.nowMs).toISOString(),
      details: safeLogDetails(details),
    });
    flushSoon(timing.nowMs);
  };
  const start = (name, details = {}) => {
    if (finalized) return;
    const timing = nowRelative();
    activePhases.set(name, { startMs: timing.elapsedMs, details: safeLogDetails(details) });
    log.events.push({
      type: "phase-start",
      name,
      elapsedMs: timing.elapsedMs,
      deltaMs: timing.deltaMs,
      timestamp: new Date(timing.nowMs).toISOString(),
      details: safeLogDetails(details),
    });
    flushSoon(timing.nowMs, true);
  };
  const end = (name, details = {}) => {
    if (finalized) return;
    const timing = nowRelative();
    const phase = activePhases.get(name);
    activePhases.delete(name);
    const startMs = Number.isFinite(phase?.startMs) ? phase.startMs : timing.elapsedMs;
    const mergedDetails = { ...(phase?.details || {}), ...safeLogDetails(details) };
    log.phases.push({
      name,
      startMs,
      endMs: timing.elapsedMs,
      durationMs: Math.max(0, timing.elapsedMs - startMs),
      details: mergedDetails,
    });
    log.events.push({
      type: "phase-end",
      name,
      elapsedMs: timing.elapsedMs,
      deltaMs: timing.deltaMs,
      timestamp: new Date(timing.nowMs).toISOString(),
      details: mergedDetails,
    });
    flushSoon(timing.nowMs, true);
  };
  const activity = (type, text, extra = {}) => {
    if (finalized) return;
    const timing = nowRelative();
    log.events.push({
      type: "activity",
      activityType: String(type || "activity"),
      elapsedMs: timing.elapsedMs,
      deltaMs: timing.deltaMs,
      timestamp: new Date(timing.nowMs).toISOString(),
      text: truncateLogValue(text || "", 3000),
      details: safeLogDetails(extra),
    });
    flushSoon(timing.nowMs);
  };
  const finish = (status = "completed", details = {}) => {
    if (finalized) return filePath;
    for (const phaseName of Array.from(activePhases.keys())) {
      end(phaseName, { autoClosed: true });
    }
    const timing = nowRelative();
    log.status = status;
    log.endedAt = new Date(timing.nowMs).toISOString();
    log.totalMs = timing.elapsedMs;
    log.events.push({
      type: "finish",
      name: status,
      elapsedMs: timing.elapsedMs,
      deltaMs: timing.deltaMs,
      timestamp: new Date(timing.nowMs).toISOString(),
      details: safeLogDetails(details),
    });
    finalized = true;
    flushSoon(timing.nowMs, true);
    return filePath;
  };
  return { filePath, mark, start, end, activity, finish };
}

function sha256Text(text) {
  return crypto.createHash("sha256").update(String(text || ""), "utf8").digest("hex");
}


function formatJsonForArcBot(data) {
  return formatJsonForSave(data);
}

function extractJsonObject(text) {
  const raw = String(text || "").trim();
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // Continue with fenced/object extraction.
  }
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) {
    try {
      return JSON.parse(fenced[1].trim());
    } catch {
      // Continue with first object extraction.
    }
  }
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start >= 0 && end > start) {
    try {
      return JSON.parse(raw.slice(start, end + 1));
    } catch {
      return null;
    }
  }
  return null;
}

function extractJsonText(text) {
  const raw = String(text || "").trim();
  if (!raw) return "";
  try {
    JSON.parse(raw);
    return raw;
  } catch {
    // Continue with fenced/object extraction.
  }
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced) {
    const candidate = fenced[1].trim();
    try {
      JSON.parse(candidate);
      return candidate;
    } catch {
      // Continue with first object extraction.
    }
  }
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start >= 0 && end > start) {
    const candidate = raw.slice(start, end + 1);
    try {
      JSON.parse(candidate);
      return candidate;
    } catch {
      return "";
    }
  }
  return "";
}

function getAssistantTargetJsonPath(activeContext) {
  const page = activeContext && typeof activeContext === "object" ? activeContext : {};
  const candidates = [
    page.methodPath,
    page.filePath,
    page.targetPath,
    page?.dfm?.methodPath,
  ];
  return String(candidates.find((candidate) => String(candidate || "").trim()) || "").trim();
}

function isArcBotEditableTarget(targetPath) {
  const extension = path.extname(String(targetPath || "").trim()).toLowerCase();
  return [".json", ".ipynb", ".arcnb", ".arcdash"].includes(extension);
}

// ArcBot never reads or writes the target file. It edits the JSON the open
// page sent (a method page's in-memory payload, a notebook's cells, or a JSON
// file's editor text) and hands the result back to that page, which applies it
// as unsaved changes and saves it through its own save.
function getArcBotActivePageJson(activeContext, targetPath) {
  const ctx = activeContext && typeof activeContext === "object" ? activeContext : {};
  if (ctx.activeJson != null && typeof ctx.activeJson === "object" && !Array.isArray(ctx.activeJson)) {
    return { json: ctx.activeJson, source: "active_context" };
  }
  if (path.extname(String(targetPath || "")).toLowerCase() === ".json" && typeof ctx.fullText === "string") {
    try {
      const parsed = JSON.parse(ctx.fullText);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return { json: parsed, source: "editor_text" };
    } catch {
      return { json: { error: "The JSON in the active editor could not be parsed." }, source: "editor_text" };
    }
  }
  return { json: null, source: "" };
}

function cloneJsonValue(value) {
  return JSON.parse(JSON.stringify(value));
}

function findRootForPath(filePath, roots = []) {
  return roots.find((root) => root && isPathWithinRoot(filePath, root)) || "";
}

function relativePathForPrompt(fromDir, targetPath) {
  const relative = path.relative(fromDir, targetPath) || path.basename(targetPath);
  return relative.startsWith("..") ? targetPath : relative;
}

function isArcBotDfmContext(activeContext) {
  const ctx = activeContext && typeof activeContext === "object" ? activeContext : {};
  const pageType = String(ctx.pageType || ctx.tabType || "").trim().toLowerCase();
  const nestedPageType = String(ctx.nestedPageType || ctx.activeNestedWindow?.kind || "").trim().toLowerCase();
  return pageType === "dfm" || nestedPageType === "dfm";
}

function createArcBotEditSession({ targetPath, activeJson, serverRoot = "" }) {
  if (activeJson == null || typeof activeJson !== "object" || Array.isArray(activeJson)) {
    return null;
  }
  const sessionsRoot = getArcBotSessionRoot();
  fs.mkdirSync(sessionsRoot, { recursive: true });
  const sessionDir = fs.mkdtempSync(path.join(sessionsRoot, "session-"));
  const sharedWorkspaceRoot = getArcBotWorkspaceRoot();
  const matchedRoot = findRootForPath(targetPath, [serverRoot]);
  const exchangeRoot = sharedWorkspaceRoot;
  const relativeTarget = matchedRoot ? path.relative(matchedRoot, targetPath) : "";
  const jsonPath = matchedRoot
    ? path.join(exchangeRoot, relativeTarget)
    : path.join(exchangeRoot, "_active", path.basename(targetPath) || "active-method.json");
  const metaPath = path.join(sessionDir, "session.json");
  const exchangeJson = cloneJsonValue(activeJson);
  // Only the page's own JSON is staged. A current method names no CSV and
  // keeps none beside it (its datasets are in the class's datasets folder),
  // so nothing is copied from the share.
  const beforeText = formatJsonForArcBot(exchangeJson);
  const manifestFiles = [{
    role: "dfm",
    serverPath: String(targetPath || ""),
    localPath: jsonPath,
    writable: true,
    beforeSha256: sha256Text(beforeText),
  }];
  const session = {
    sessionDir,
    exchangeRoot,
    jsonPath,
    metaPath,
    codexCwd: exchangeRoot || sessionDir,
    editablePathForPrompt: relativePathForPrompt(exchangeRoot || sessionDir, jsonPath),
    targetPath: String(targetPath || ""),
    beforeSha256: sha256Text(beforeText),
    manifestFiles,
  };
  fs.mkdirSync(path.dirname(jsonPath), { recursive: true });
  fs.writeFileSync(jsonPath, beforeText, "utf8");
  fs.writeFileSync(metaPath, formatJsonForArcBot({
    type: "arcbot-edit-session",
    createdAt: new Date().toISOString(),
    targetPath: session.targetPath,
    editableFile: jsonPath,
    exchangeRoot,
    editablePathForPrompt: session.editablePathForPrompt,
    files: manifestFiles,
  }), "utf8");
  return session;
}

function getCodexInstallScriptPath() {
  return path.join(app.getPath("userData"), "install_codex_cli.ps1");
}

function writeCodexInstallScript() {
  const scriptPath = getCodexInstallScriptPath();
  fs.mkdirSync(path.dirname(scriptPath), { recursive: true });
  const script = [
    "param([string]$NpmCommand = 'npm', [Parameter(Mandatory = $true)][string]$InstallPrefix)",
    "$ErrorActionPreference = 'Stop'",
    "Write-Output \"Arco is installing a per-user Codex CLI under: $InstallPrefix\"",
    "$resolvedNpm = $null",
    "if (Test-Path -LiteralPath $NpmCommand) {",
    "  $resolvedNpm = Resolve-Path -LiteralPath $NpmCommand",
    "} else {",
    "  $resolvedNpm = Get-Command $NpmCommand -ErrorAction SilentlyContinue",
    "  if (-not $resolvedNpm) { throw 'npm was not found. Install Node.js/npm, then try again.' }",
    "}",
    "$npmPath = if ($resolvedNpm.Path) { $resolvedNpm.Path } else { [string]$resolvedNpm }",
    "$npmDir = Split-Path -Parent $npmPath",
    "if ($npmDir) { $env:Path = \"$npmDir;$env:Path\" }",
    "New-Item -ItemType Directory -Path $InstallPrefix -Force | Out-Null",
    "& $NpmCommand install --global --prefix $InstallPrefix @openai/codex",
    "if ($LASTEXITCODE -ne 0) { throw \"npm installation failed (exit $LASTEXITCODE). See the npm error above. If it reports ENOSPC, free space on the installation/cache drive, then retry.\" }",
    "$codexCmd = Join-Path $InstallPrefix 'codex.cmd'",
    "if (-not (Test-Path -LiteralPath $codexCmd -PathType Leaf)) { throw \"npm returned success but did not create $codexCmd. Check npm's bin-links setting and retry Repair.\" }",
    "& $codexCmd --version",
    "if ($LASTEXITCODE -ne 0) { throw \"The installed Codex CLI could not start (exit $LASTEXITCODE). Retry Repair after resolving the error above.\" }",
    "Write-Output \"ARCRHO_CODEX_CMD=$codexCmd\"",
    "Write-Output 'Codex CLI install completed.'",
    "",
  ].join("\r\n");
  fs.writeFileSync(scriptPath, script, "utf8");
  return scriptPath;
}

function readBundledArcBotPromptTemplate() {
  try {
    return fs.readFileSync(ARCBOT_PROMPT_TEMPLATE_PATH, "utf8");
  } catch (err) {
    throw new Error(`ArcBot prompt template could not be read: ${ARCBOT_PROMPT_TEMPLATE_PATH}: ${err?.message || err}`);
  }
}

// ArcBot's entry prompt and the team's instruction files live on the server
// under config\arcbot. They are read through the app server, which asks the
// Gateway; nothing here opens or seeds that folder over the share. When the
// server holds no entry prompt, or cannot be asked, ArcBot uses the prompt
// bundled with the app.
function requestAppServerJson(route, body = null, timeoutMs = ARCBOT_PROMPT_FILES_TIMEOUT_MS) {
  const baseUrl = String(getAppServerUrl() || "").trim();
  if (!baseUrl) return Promise.resolve({ error: "The Arco app server is not available." });
  return new Promise((resolve) => {
    const payloadText = body == null ? "" : JSON.stringify(body);
    const req = http.request(`${baseUrl}${route}`, {
      method: body == null ? "GET" : "POST",
      headers: body == null ? {} : { "content-type": "application/json", "content-length": Buffer.byteLength(payloadText) },
    }, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        text += chunk;
      });
      res.on("end", () => {
        let parsed = null;
        try {
          parsed = JSON.parse(text || "{}");
        } catch {
          parsed = null;
        }
        if (res.statusCode === 200 && parsed && typeof parsed === "object") {
          resolve(parsed);
          return;
        }
        const detail = parsed?.detail ? String(parsed.detail) : `HTTP ${res.statusCode || "error"}`;
        resolve({ error: detail });
      });
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error("timed out")));
    req.on("error", (err) => resolve({ error: String(err?.message || err || "request failed") }));
    req.end(payloadText);
  });
}

function requestArcBotPromptFiles() {
  return requestAppServerJson("/arcbot/prompt-files");
}

// ArcBot's skills live on the server under shared\agent-skills and are read the
// same way as the prompt files. Without a skill id the answer is the menu list;
// with one, that skill also carries its instructions and reference files.
function requestAgentSkills(skillId = "") {
  return requestAppServerJson(`/arcbot/agent-skills${skillId ? `?skill_id=${encodeURIComponent(skillId)}` : ""}`);
}

// The running skill must still fit the page the user has open: a DFM skill needs a DFM window.
function skillAppliesToContext(skill, context) {
  if (!skill.scope) return true;
  return [context?.pageType, context?.nestedPageType, context?.activeNestedWindow?.kind].includes(skill.scope);
}

async function runArcBotPython(script, input) {
  const result = await runHostCommand(PYTHON_EXE, ["-X", "utf8", "-c", script], {
    // No shell: a Python path with spaces ("C:\Program Files\...") breaks cmd.exe parsing.
    input, env: getArcBotCodexEnv(), windowsHide: true, shell: false, timeoutMs: CODEX_ASSISTANT_TIMEOUT_MS,
  });
  if (!result.ok) throw new Error(result.stderr || result.error || "Project read failed.");
  return result.stdout;
}

// One place runs a tool call for both providers; the macro tool answers only for the running skill.
async function executeArcBotTool(params, context, skill) {
  if (params.tool === RUN_MACRO_TOOL.name) {
    return runSkillMacro(params, skill, async (route, body) => {
      const answer = await requestAppServerJson(route, body, CODEX_ASSISTANT_TIMEOUT_MS);
      if (answer.error) throw new Error(answer.error);
      return answer;
    });
  }
  return readArcBotProject(params, context, runArcBotPython);
}

function readArcBotSharedInstructions(promptFiles) {
  if (promptFiles?.error) return `Shared instruction files could not be read: ${promptFiles.error}`;
  const files = Array.isArray(promptFiles?.instructions) ? promptFiles.instructions : [];
  if (!files.length) return "No shared instruction files were found.";
  const parts = [];
  const maxFileChars = 30000;
  const maxTotalChars = 80000;
  for (const file of files) {
    let text = String(file?.text || "").trim();
    if (!text) continue;
    if (text.length > maxFileChars) {
      text = `${text.slice(0, maxFileChars)}\n\n[Instruction file truncated at ${maxFileChars} characters.]`;
    }
    parts.push(`## ${String(file?.name || "")}\n\n${text}`);
  }
  if (!parts.length) return "No shared instruction files contain content yet.";
  const combined = parts.join("\n\n---\n\n");
  return combined.length > maxTotalChars
    ? `${combined.slice(0, maxTotalChars)}\n\n[Shared instruction files truncated at ${maxTotalChars} characters.]`
    : combined;
}

function ensureArcBotSharedInstructionsPlaceholder(template) {
  const text = String(template || "");
  if (text.includes("{{SHARED_INSTRUCTIONS}}")) return text;
  if (text.includes("{{MODE_INSTRUCTIONS}}")) {
    return text.replace(
      "{{MODE_INSTRUCTIONS}}",
      "{{MODE_INSTRUCTIONS}}\n\nShared team instructions:\n{{SHARED_INSTRUCTIONS}}"
    );
  }
  return `${text}\n\nShared team instructions:\n{{SHARED_INSTRUCTIONS}}\n`;
}

function readArcBotPromptComponentsForGuide(promptFiles) {
  const serverPrompt = typeof promptFiles?.prompt === "string" ? promptFiles.prompt : null;
  const components = [{
    id: "entry",
    title: "Entry Prompt",
    path: serverPrompt != null ? String(promptFiles.prompt_path || "") : ARCBOT_PROMPT_TEMPLATE_PATH,
    text: ensureArcBotSharedInstructionsPlaceholder(serverPrompt ?? readBundledArcBotPromptTemplate()),
  }];
  const instructionsDir = String(promptFiles?.instructions_dir || "");
  const serverFiles = new Map(
    (Array.isArray(promptFiles?.instructions) ? promptFiles.instructions : [])
      .map((file) => [String(file?.name || "").toLowerCase(), file])
  );
  const componentFor = (fileName, text) => ({
    id: fileName.replace(/[^a-z0-9]+/giu, "-").replace(/^-+|-+$/g, ""),
    title: fileName,
    path: instructionsDir ? path.join(instructionsDir, fileName) : fileName,
    text,
  });
  const included = new Set();
  for (const [fileName, placeholderText] of ARCBOT_SERVER_INSTRUCTION_PLACEHOLDERS) {
    included.add(fileName.toLowerCase());
    const serverFile = serverFiles.get(fileName.toLowerCase());
    components.push(componentFor(fileName, serverFile ? String(serverFile.text || "") : placeholderText));
  }
  const extraFiles = [...serverFiles.values()]
    .filter((file) => !included.has(String(file?.name || "").toLowerCase()))
    .sort((a, b) => String(a.name).localeCompare(String(b.name)));
  for (const file of extraFiles) components.push(componentFor(String(file.name), String(file.text || "")));
  return components;
}

function readArcBotPromptTemplate(promptFiles) {
  const serverPrompt = typeof promptFiles?.prompt === "string" ? promptFiles.prompt : null;
  return ensureArcBotSharedInstructionsPlaceholder(serverPrompt ?? readBundledArcBotPromptTemplate());
}

function extractArcBotPromptSection(template, sectionName) {
  const name = String(sectionName || "").trim().toUpperCase();
  const pattern = new RegExp(`<!--\\s*ARCBOT:${name}\\s*-->([\\s\\S]*?)<!--\\s*ARCBOT:END_${name}\\s*-->`, "u");
  const match = String(template || "").match(pattern);
  if (!match) throw new Error(`ArcBot prompt template is missing section ${name}.`);
  return match[1].trim();
}

function renderArcBotPromptTemplate(template, values) {
  return String(template || "").replace(/\{\{([A-Z0-9_]+)\}\}/gu, (_match, key) => {
    const value = values?.[key];
    return value == null ? "" : String(value);
  });
}

// The model is told a file's name, never where it lives: a page's path points
// into the server folder, and ArcBot reads project data through the server.
function withFileNamesOnly(value) {
  if (typeof value === "string") {
    return /^(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*$/u.test(value) ? path.win32.basename(value) : value;
  }
  if (Array.isArray(value)) return value.map(withFileNamesOnly);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, withFileNamesOnly(item)]));
  }
  return value;
}

function buildAssistantPrompt(
  messages,
  mode = "edit",
  workingFolder = "",
  readableFolders = [],
  activeContext = null,
  activeJson = null,
  editSession = null,
  attachments = [],
  promptFiles = null,
  skill = null
) {
  const safeMessages = Array.isArray(messages) ? messages.slice(-12) : [];
  const safeAttachments = Array.isArray(attachments)
    ? attachments.slice(0, 5).map((item) => ({
        name: String(item?.name || path.basename(String(item?.path || "")) || "attachment"),
        path: String(item?.path || ""),
        size: Number.isFinite(item?.size) ? Math.max(0, Math.round(item.size)) : 0,
        text: String(item?.text || "").slice(0, 60000),
      })).filter((item) => item.text.trim())
    : [];
  const transcript = safeMessages
    .map((message) => {
      const role = String(message?.role || "").toLowerCase() === "assistant" ? "Assistant" : "User";
      const text = String(message?.content || "").trim();
      return text ? `${role}: ${text}` : "";
    })
    .filter(Boolean)
    .join("\n\n");
  const contextForPrompt = activeContext && typeof activeContext === "object"
    ? { ...activeContext }
    : { available: false };
  delete contextForPrompt.activeJson;
  const contextNamesOnly = withFileNamesOnly(contextForPrompt);
  const attachmentText = safeAttachments.length
    ? safeAttachments.map((item, index) => [
        `Attachment ${index + 1}: ${item.name}`,
        item.path ? `Path: ${item.path}` : "",
        item.size ? `Size: ${item.size} bytes` : "",
        "Content:",
        item.text,
      ].filter(Boolean).join("\n")).join("\n\n---\n\n")
    : "No additional files were attached.";
  const template = readArcBotPromptTemplate(promptFiles);
  const baseSection = extractArcBotPromptSection(template, "BASE");
  const modeSection = extractArcBotPromptSection(template, mode === "edit" ? "EDIT_MODE" : "REVIEW_MODE");
  const activeJsonName = editSession?.editablePathForPrompt || (editSession?.jsonPath ? path.basename(editSession.jsonPath) : "active-method.json");
  const exchangeRoot = editSession?.exchangeRoot || "";
  const pythonApiWheelPath = getPythonApiWheelPath();
  return renderArcBotPromptTemplate(baseSection, {
    MODE_LABEL: mode === "edit" ? "Edit Mode" : "Review Mode",
    CLI_ROOT: workingFolder,
    READABLE_FOLDERS: readableFolders.length ? readableFolders.join("; ") : "None.",
    MODE_INSTRUCTIONS: renderArcBotPromptTemplate(modeSection, {
      EDITABLE_JSON_BASENAME: activeJsonName,
      EXCHANGE_SERVER_ROOT: exchangeRoot || "No local exchange workspace is available.",
      EDITABLE_JSON_NOTE: editSession?.jsonPath
        ? `Editable active JSON-backed copy: ${activeJsonName}.${exchangeRoot ? ` Local Arco exchange server root: ${exchangeRoot}.` : ""}`
        : "No editable active JSON-backed copy is available for this request.",
    }),
    PYTHON_API_SRC,
    PYTHON_API_WHEEL_DIR,
    PYTHON_API_WHEEL_PATH: pythonApiWheelPath || "No bundled arcrho-api wheel was found.",
    PYTHON_API_INSTALL_COMMAND: pythonApiWheelPath ? `${PYTHON_EXE} -m pip install ${quoteWindowsCmdArg(pythonApiWheelPath)}` : "",
    PYTHON_API_COMMAND: `${PYTHON_EXE} -m arcrho_api.agent --file ${quoteWindowsCmdArg(activeJsonName)}`,
    ACTIVE_CONTEXT_JSON: JSON.stringify(contextNamesOnly, null, 2),
    ACTIVE_JSON_DATA: editSession?.jsonPath
      ? `The active JSON-backed file is available as ${activeJsonName} in the current working folder. Use the Arco Python API helper for DFM reads and edits before falling back to raw JSON inspection. When using the public Arco Python API directly, use ArcRhoClient(${JSON.stringify(exchangeRoot || ".")}) so API reads and writes stay inside the local exchange workspace.`
      : (activeJson ? JSON.stringify(activeJson, null, 2) : "No active JSON-backed data was loaded."),
    SHARED_INSTRUCTIONS: `${readArcBotSharedInstructions(promptFiles)}\n\n${fs.readFileSync(path.join(__dirname, "prompts", "arcbot_runtime_workflow.md"), "utf8")}${skill ? `\n\n${buildSkillPrompt(skill)}` : ""}`,
    ATTACHMENT_TEXT: attachmentText,
    TRANSCRIPT: transcript || "User: Hello",
  });
}

function clampCodexPrompt(prompt) {
  const text = String(prompt || "");
  const maxChars = 200000;
  if (text.length <= maxChars) return text;
  return [
    text.slice(0, 150000),
    "",
    "[Prompt was truncated to keep the Codex CLI request bounded.]",
    "",
    text.slice(-45000),
  ].join("\n");
}

function estimateArcBotContextUsage(prompt, messages, activeContext, activeJson, clampedPrompt, attachments = []) {
  const promptText = String(prompt || "");
  const clampedText = String(clampedPrompt || promptText);
  const estimatedTokens = Math.ceil(clampedText.length / 4);
  const contextPercentUsed = Math.min(100, Math.max(0, (estimatedTokens / CODEX_ASSISTANT_CONTEXT_WINDOW_TOKENS) * 100));
  const activeJsonText = activeJson ? JSON.stringify(activeJson) : "";
  const contextText = activeContext ? JSON.stringify(activeContext) : "";
  const attachmentText = Array.isArray(attachments)
    ? attachments.map((item) => String(item?.text || "")).join("\n")
    : "";
  const chatText = Array.isArray(messages)
    ? messages.map((message) => String(message?.content || "")).join("\n")
    : "";
  return {
    promptChars: clampedText.length,
    estimatedTokens,
    contextWindowTokens: CODEX_ASSISTANT_CONTEXT_WINDOW_TOKENS,
    contextPercentUsed,
    maxPromptChars: 200000,
    maxPromptTokens: Math.ceil(200000 / 4),
    truncated: clampedText.length < promptText.length,
    includedMessages: Array.isArray(messages) ? Math.min(messages.length, 12) : 0,
    chatChars: chatText.length,
    activeContextChars: contextText.length,
    activeJsonChars: activeJsonText.length,
    attachmentChars: attachmentText.length,
    attachmentCount: Array.isArray(attachments) ? attachments.length : 0,
  };
}

function sendArcBotActivity(event, requestId, type, text, extra = {}) {
  const logger = arcBotRequestLoggers.get(String(requestId || ""));
  // Streamed pieces would flood the request log; the finished reply is logged instead.
  if (logger && !["assistant-delta", "thinking", "thinking-tokens"].includes(type)) logger.activity(type, text, extra);
  if (!event?.sender || !requestId) return;
  try {
    event.sender.send("codex-assistant-event", {
      requestId,
      type,
      text: String(text || ""),
      timestamp: new Date().toISOString(),
      ...extra,
    });
  } catch {
    // ignore stale renderer activity updates
  }
}

function describeArcRhoApiAgentAction(action) {
  const normalized = String(action || "").trim().toLowerCase();
  const labels = {
    inspect: "ArcBot is bundling the active DFM method details in one helper read.",
    summary: "ArcBot is reading the active DFM method summary.",
    component: "ArcBot is inspecting a DFM method component.",
    "ratio-row": "ArcBot is reading ratio-row details from the DFM method.",
    "exclude-ratio": "ArcBot is marking selected ratio cells as excluded.",
    "include-ratio": "ArcBot is restoring selected ratio cells.",
    "select-average": "ArcBot is updating the selected average formula.",
    "set-user-entry": "ArcBot is setting a user-entered selected factor.",
    validate: "ArcBot is checking that the proposed DFM update is valid.",
  };
  return labels[normalized] || "ArcBot is using the Arco Python helper for the active DFM method.";
}

function summarizeCodexTurnNotification(message) {
  const method = String(message?.method || "").toLowerCase();
  if (!method || method === "item/agentmessage/delta" || method === "turn/completed") return "";
  const paramsText = (() => {
    try {
      return JSON.stringify(message?.params || {});
    } catch {
      return "";
    }
  })();
  const apiMatch = paramsText.match(/arcrho_api\.agent[^"'`]*?\s(inspect|summary|component|ratio-row|exclude-ratio|include-ratio|select-average|set-user-entry|validate)\b/iu);
  if (apiMatch) {
    return {
      text: describeArcRhoApiAgentAction(apiMatch[1]),
      debugText: `Arco Python API helper call notification: ${message?.method || ""} ${paramsText}`.trim(),
    };
  }
  if (method.includes("command") || method.includes("exec") || method.includes("shell")) return "ArcBot is running a local check.";
  if (method.includes("web") || method.includes("search")) return "ArcBot is searching for supporting context.";
  if (method.includes("tool")) return "ArcBot is using a tool.";
  if (method.includes("patch") || method.includes("file")) return "ArcBot is preparing file changes.";
  if (method.includes("plan")) return "ArcBot updated the task plan.";
  return "";
}

function registerArcBotIpc(deps = {}) {
  ({
    ipcMain,
    app,
    APP_ROOT,
    REPO_ROOT,
    PYTHON_EXE,
    getPrefsDir,
    getWorkspacePathsPath,
    findExecutableOnPath,
    runHostCommand: runHostCommandBase,
  } = deps);
  getAppServerUrl = typeof deps.getAppServerUrl === "function" ? deps.getAppServerUrl : () => "";
  if (!ipcMain || !app) {
    throw new Error("registerArcBotIpc requires ipcMain and app dependencies");
  }
  spawnProcessBase = typeof deps.spawnProcess === "function" ? deps.spawnProcess : spawn;
  arcBotAccounts = createArcBotAccounts({ getRootDir: getPrefsDir, homeDir: deps.homeDir || os.homedir() });
  resetCodexAppServerClient();
  const voice = registerArcBotVoice(ipcMain);
  PYTHON_API_SRC = path.join(REPO_ROOT, "python-api", "src");
  PYTHON_API_WHEEL_DIR = app.isPackaged
    ? path.join(process.resourcesPath, "python_packages")
    : path.join(APP_ROOT, "build", "python_packages");
  void migrateLegacyCliInstalls();

ipcMain.handle("codex-assistant-prepare", async (event, payload) => {
  const owner = event.sender.id;
  if (!event.sender.__arcBotPreparedCleanup) {
    event.sender.__arcBotPreparedCleanup = true;
    event.sender.once("destroyed", () => preparedSessions.release(owner));
  }
  if (!payload?.sessionId || isClaudeArcBotModel(payload?.model) || !CODEX_APP_SERVER_ENABLED) {
    preparedSessions.release(owner);
    return { ok: true, state: "on-demand" };
  }
  try {
    const cwd = getArcBotWorkspaceRoot();
    fs.mkdirSync(cwd, { recursive: true });
    const client = await ensureCodexAppServerStarted();
    await preparedSessions.prepare(owner, payload.sessionId, normalizeArcBotModel(payload.model), cwd, client);
    return { ok: true, state: "ready" };
  } catch (error) {
    return { ok: false, state: "failed", error: String(error.message || error) };
  }
});
ipcMain.handle("codex-assistant-release", (event) => {
  preparedSessions.release(event.sender.id);
  return { ok: true };
});

ipcMain.handle("codex-assistant-status", async () => {
  const codexCommand = getCodexCommand();
  const version = await runCodexCommand(["--version"], {
    timeoutMs: 8000,
  });
  if (!version.ok) {
    const error = normalizeHostError(version, "Codex CLI was not found.");
    const setupAction = /^ArcBot working directory is unavailable:/iu.test(error)
      ? "none"
      : codexCommand ? "repair" : "install";
    return {
      installed: false,
      authenticated: false,
      claudeAuthenticated: hasClaudeSignIn(),
      version: "",
      loginEmail: "",
      setupAction,
      error,
    };
  }

  const auth = await runCodexCommand(["login", "status"], {
    timeoutMs: 8000,
  });
  let modelCatalogStatus = null;
  if (CODEX_APP_SERVER_ENABLED) {
    modelCatalogStatus = await getCodexModelCatalog();
  }
  const authOutput = combinedCommandOutput(auth);
  return {
    installed: true,
    authenticated: auth.ok,
    claudeAuthenticated: hasClaudeSignIn(),
    version: combinedCommandOutput(version).split(/\r?\n/)[0] || "codex",
    loginEmail: auth.ok ? readCodexLoginEmail(authOutput) : extractEmailFromText(authOutput),
    authStatus: authOutput,
    modelUpgradeRequired: modelCatalogStatus?.upgradeRequired === true,
    modelCatalogVerified: !CODEX_APP_SERVER_ENABLED || modelCatalogStatus?.verified === true,
    minimumDefaultModel: String(modelCatalogStatus?.minimumDefaultModel || ""),
    modelCatalogWarning: String(modelCatalogStatus?.warning || ""),
    error: auth.ok ? "" : normalizeHostError(auth, "Codex CLI is not signed in."),
  };
});

ipcMain.handle("codex-assistant-models", async (_event, payload) => {
  const refresh = payload?.refresh === true;
  const [catalog, claude] = await Promise.all([
    getCodexModelCatalog({ refresh }),
    getClaudeModelCatalog({ refresh }),
  ]);
  return { ...catalog, claude };
});

ipcMain.handle("codex-assistant-readable-roots-load", async () => {
  try {
    const folders = readArcBotReadableRoots();
    return { ok: true, folders };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not load ArcBot readable folders.") };
  }
});

ipcMain.handle("codex-assistant-readable-roots-save", async (_event, payload) => {
  try {
    const folders = writeArcBotReadableRoots(payload?.folders || []);
    return { ok: true, folders };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not save ArcBot readable folders.") };
  }
});

ipcMain.handle("codex-assistant-ui-settings-load", async () => {
  try {
    return { ok: true, settings: readArcBotUiSettings() };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not load ArcBot UI settings.") };
  }
});

ipcMain.handle("codex-assistant-ui-settings-save", async (_event, payload) => {
  try {
    const settings = payload?.settings && typeof payload.settings === "object" ? payload.settings : {};
    return { ok: true, settings: writeArcBotUiSettings(settings) };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not save ArcBot UI settings.") };
  }
});

ipcMain.handle("codex-assistant-prompt-guide-load", async () => {
  try {
    const promptFiles = await requestArcBotPromptFiles();
    const components = readArcBotPromptComponentsForGuide(promptFiles);
    return {
      ok: true,
      serverRoot: getConfiguredWorkspaceRoot(),
      instructionsDir: String(promptFiles?.instructions_dir || ""),
      entryPromptPath: components[0].path,
      components,
    };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not load ArcBot prompt guide.") };
  }
});

ipcMain.handle("codex-assistant-skills-list", async () => {
  const answer = await requestAgentSkills();
  return answer.error ? { ok: false, error: String(answer.error), skills: [] } : { ok: true, skills: answer.skills || [] };
});

ipcMain.handle("codex-assistant-install", async () => {
  await cliMigration;
  if (process.platform === "win32") {
    const scriptPath = writeCodexInstallScript();
    const result = await runHostCommand("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      scriptPath,
      "-NpmCommand",
      getNpmCommand(),
      "-InstallPrefix",
      getUserCodexInstallPrefix(),
    ], {
      timeoutMs: 10 * 60 * 1000,
      windowsHide: false,
      shell: false,
    });
    const output = combinedCommandOutput(result);
    if (result.ok) {
      writeArcBotCodexCommandHint(extractCodexCommandFromInstallOutput(output) || getCodexCommand());
      resetCodexAppServerClient();
    }
    return {
      ok: result.ok,
      output,
      error: result.ok ? "" : normalizeHostError(result, "Codex CLI installation failed."),
    };
  }

  const installPrefix = getUserCodexInstallPrefix();
  const result = await runHostCommand(getNpmCommand(), [
    "install", "--global", "--prefix", installPrefix, "@openai/codex",
  ], {
    timeoutMs: 10 * 60 * 1000,
    windowsHide: false,
  });
  if (result.ok) {
    writeArcBotCodexCommandHint(getUserInstalledCodexCommand());
    resetCodexAppServerClient();
  }
  return {
    ok: result.ok,
    output: combinedCommandOutput(result),
    error: result.ok ? "" : normalizeHostError(result, "Codex CLI installation failed."),
  };
});

// Sign-in needs the Claude CLI, so a machine without one gets a per-user copy first.
let claudeCliInstall = null;

// One install at a time; the list of accounts starts it in the background and a sign-in waits on it.
function installClaudeCli() {
  if (claudeCliInstall) return claudeCliInstall;
  const args = ["install", "--global", "--prefix", getUserClaudeInstallPrefix(), "@anthropic-ai/claude-code"];
  // The package's install script runs `node`, so the bundled Node folder goes on PATH.
  const options = {
    timeoutMs: 10 * 60 * 1000,
    shell: false,
    env: { ...process.env, PATH: `${getBundledNodePortableRoot()}${path.delimiter}${process.env.PATH || ""}` },
  };
  // Bundled Node runs npm directly: an install path with spaces breaks cmd.exe quoting.
  const bundledNode = path.join(getBundledNodePortableRoot(), process.platform === "win32" ? "node.exe" : "bin/node");
  const npmCli = path.join(getBundledNodePortableRoot(), "node_modules", "npm", "bin", "npm-cli.js");
  const npm = getNpmCommand();
  claudeCliInstall = Promise.resolve(cliMigration)
    .then(() => (fs.existsSync(bundledNode) && fs.existsSync(npmCli)
      ? runHostCommand(bundledNode, [npmCli, ...args], options)
      : process.platform === "win32" && /\.(cmd|bat)$/iu.test(npm)
        ? runWindowsCmdCommand(npm, args, options)
        : runHostCommand(npm, args, options)))
    .then((result) => (result.ok ? "" : normalizeHostError(result, "Claude CLI installation failed.")))
    .finally(() => { claudeCliInstall = null; });
  return claudeCliInstall;
}

// A sign-in can wait minutes on the CLI install; repeat clicks share it instead of each opening a window.
const arcBotLoginLaunches = new Map();

function launchArcBotAccountLogin(account) {
  const pending = arcBotLoginLaunches.get(account.id);
  if (pending) return pending;
  const launch = launchArcBotAccountLoginWindow(account)
    .finally(() => { arcBotLoginLaunches.delete(account.id); });
  arcBotLoginLaunches.set(account.id, launch);
  return launch;
}

// Opens the vendor sign-in in its own window under the account's folder.
async function launchArcBotAccountLoginWindow(account) {
  let result;
  if (account.provider === "claude") {
    let claudeCmd = getClaudeCommand();
    if (!claudeCmd) {
      const installError = await installClaudeCli();
      claudeCmd = getClaudeCommand();
      if (!claudeCmd) return { ok: false, error: installError || "Claude CLI (claude) could not be installed." };
    }
    const env = arcBotAccounts.envFor(account, process.env);
    result = process.platform === "win32"
      ? await launchDetachedArcBotProcess("cmd.exe", ["/d", "/k", `${quoteWindowsCmdArg(claudeCmd)} auth login`], { env })
      : await launchDetachedArcBotProcess(claudeCmd, ["auth", "login"], { env });
  } else {
    const codexSpec = getCodexSpawnSpec(["login"]);
    if (!codexSpec) {
      return { ok: false, error: "Codex CLI was not found. Install Codex CLI before signing in." };
    }
    const env = getArcBotCodexEnv(process.env, account);
    result = process.platform === "win32"
      ? await launchDetachedArcBotProcess(
        "cmd.exe",
        ["/d", "/k", [codexSpec.command, ...codexSpec.args].map(quoteWindowsCmdArg).join(" ")],
        { env },
      )
      : await launchDetachedArcBotProcess(codexSpec.command, codexSpec.args, { shell: codexSpec.shell, env });
  }
  if (result.ok) arcBotAccounts.markLoginPending(account.id);
  return result;
}

function arcBotAccountProvider(value) {
  const provider = String(value || "").trim().toLowerCase();
  return provider === "anthropic" || provider === "claude" ? "claude" : "codex";
}

// Switching an account restarts what holds the old sign-in, which would fail a running reply.
function arcBotAccountBusyError() {
  return activeCodexAssistantRequests.size ? "Wait for the current reply to finish." : "";
}

function afterArcBotAccountChange(provider) {
  if (provider === "codex") {
    resetCodexAppServerClient();
  } else {
    claudeModelCatalogCache = null;
    claudeModelCatalogCachedAt = 0;
  }
}

function arcBotAccountsResult() {
  return { ok: true, accounts: arcBotAccounts.views() };
}

async function handleArcBotAccountChange(change) {
  try {
    return await change();
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "The account could not be changed.") };
  }
}

ipcMain.handle("codex-assistant-login", async (_event, payload) => handleArcBotAccountChange(() => (
  launchArcBotAccountLogin(payload?.accountId
    ? arcBotAccounts.get(String(payload.accountId))
    : arcBotAccounts.active(arcBotAccountProvider(payload?.provider)))
)));

ipcMain.handle("codex-assistant-accounts-list", async () => handleArcBotAccountChange(() => {
  if (!getClaudeCommand()) void installClaudeCli();
  return arcBotAccountsResult();
}));

ipcMain.handle("codex-assistant-account-create", async (_event, payload) => handleArcBotAccountChange(async () => {
  const busy = arcBotAccountBusyError();
  if (busy) return { ok: false, error: busy };
  const provider = arcBotAccountProvider(payload?.provider);
  const account = arcBotAccounts.create(provider, payload?.label);
  arcBotAccounts.setActive(provider, account.id);
  afterArcBotAccountChange(provider);
  const login = await launchArcBotAccountLogin(account);
  return { ...arcBotAccountsResult(), ok: login.ok, error: login.error || "" };
}));

ipcMain.handle("codex-assistant-account-activate", async (_event, payload) => handleArcBotAccountChange(() => {
  const provider = arcBotAccountProvider(payload?.provider);
  if (arcBotAccounts.current().id === payload?.accountId) return arcBotAccountsResult();
  const busy = arcBotAccountBusyError();
  if (busy) return { ok: false, error: busy };
  arcBotAccounts.setActive(provider, String(payload?.accountId || ""));
  afterArcBotAccountChange(provider);
  return arcBotAccountsResult();
}));

ipcMain.handle("codex-assistant-account-logout", async (_event, payload) => handleArcBotAccountChange(async () => {
  const account = arcBotAccounts.get(String(payload?.accountId || ""));
  const isActive = arcBotAccounts.active(account.provider).id === account.id;
  const busy = isActive ? arcBotAccountBusyError() : "";
  if (busy) return { ok: false, error: busy };
  let result;
  if (account.provider === "codex") {
    result = await runCodexCommand(["logout"], { account, timeoutMs: 15000 });
  } else {
    const claudeCmd = getClaudeCommand();
    if (!claudeCmd) return { ok: false, error: "Claude CLI (claude) was not found." };
    const options = { env: arcBotAccounts.envFor(account, process.env), timeoutMs: 15000 };
    result = /\.(cmd|bat)$/iu.test(claudeCmd)
      ? await runWindowsCmdCommand(claudeCmd, ["auth", "logout"], options)
      : await runHostCommand(claudeCmd, ["auth", "logout"], { ...options, shell: false });
  }
  if (isActive) afterArcBotAccountChange(account.provider);
  if (!result.ok) return { ok: false, error: normalizeHostError(result, "Sign-out failed.") };
  return arcBotAccountsResult();
}));

ipcMain.handle("codex-assistant-account-remove", async (_event, payload) => handleArcBotAccountChange(() => {
  const account = arcBotAccounts.get(String(payload?.accountId || ""));
  const isActive = arcBotAccounts.active(account.provider).id === account.id;
  const busy = isActive ? arcBotAccountBusyError() : "";
  if (busy) return { ok: false, error: busy };
  arcBotAccounts.remove(account.id);
  if (isActive) afterArcBotAccountChange(account.provider);
  return arcBotAccountsResult();
}));

ipcMain.handle("codex-assistant-sessions-list", async (_event, payload) => {
  try {
    return { ok: true, sessions: listArcBotChatSessions({ includeArchived: payload?.includeArchived === true }) };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not list ArcBot sessions.") };
  }
});

ipcMain.handle("codex-assistant-session-create", async (_event, payload) => {
  try {
    const session = writeArcBotChatSession({
      title: String(payload?.title || "New ArcBot Chat"),
      mode: String(payload?.mode || "edit"),
      model: normalizeArcBotModel(payload?.model),
      reasoningEffort: normalizeArcBotReasoningEffort(payload?.reasoningEffort),
      messages: [],
      activities: [],
    });
    return { ok: true, session };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not create ArcBot session.") };
  }
});

ipcMain.handle("codex-assistant-session-load", async (_event, payload) => {
  try {
    const session = readArcBotChatSession(payload?.sessionId);
    return session ? { ok: true, session } : { ok: false, error: "ArcBot session was not found." };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not load ArcBot session.") };
  }
});

ipcMain.handle("codex-assistant-session-save", async (_event, payload) => {
  try {
    const session = writeArcBotChatSession(payload?.session || {});
    return { ok: true, session };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not save ArcBot session.") };
  }
});

ipcMain.handle("codex-assistant-session-archive", async (_event, payload) => {
  try {
    const session = archiveArcBotChatSession(payload?.sessionId, payload?.archived !== false);
    return session ? { ok: true, session } : { ok: false, error: "ArcBot session was not found." };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not archive ArcBot session.") };
  }
});

ipcMain.handle("codex-assistant-session-delete", async (_event, payload) => {
  try {
    const deleted = deleteArcBotChatSession(payload?.sessionId);
    return deleted ? { ok: true } : { ok: false, error: "ArcBot session was not found." };
  } catch (err) {
    return { ok: false, error: String(err?.message || err || "Could not delete ArcBot session.") };
  }
});

ipcMain.handle("codex-assistant-send", async (event, payload) => {
  const requestId = String(payload?.requestId || "");
  // A skill only advises, so its turn is always a read-only review.
  const requestedMode = payload?.skillId ? "review" : String(payload?.mode || "edit").trim().toLowerCase();
  const mode = requestedMode === "approve" ? "approve" : requestedMode;
  const promptMode = mode === "approve" ? "edit" : mode;
  const model = normalizeArcBotModel(payload?.model);
  let reasoningEffort = normalizeArcBotReasoningEffort(payload?.reasoningEffort);
  const requestLog = createArcBotRequestLogger({ requestId, payload, mode, model, reasoningEffort });
  if (requestId) arcBotRequestLoggers.set(requestId, requestLog);
  requestLog.mark("request_received", {
    messageCount: Array.isArray(payload?.messages) ? payload.messages.length : 0,
    attachmentCount: Array.isArray(payload?.attachments) ? payload.attachments.length : 0,
  });
  const finishArcBotRequest = (response, status = "") => {
    const ok = response && response.ok !== false;
    const finalStatus = status || (response?.canceled ? "canceled" : ok ? "completed" : "failed");
    requestLog.finish(finalStatus, {
      ok,
      error: response?.error || "",
      editProposed: !!response?.editProposed,
      targetPath: response?.targetPath || "",
      usageTokens: response?.usage?.estimatedTokens || 0,
    });
    if (requestId) arcBotRequestLoggers.delete(requestId);
    return response;
  };
  if (mode !== "edit" && mode !== "review" && mode !== "approve") {
    return finishArcBotRequest({
      ok: false,
      needsAuth: false,
      error: "Unsupported ArcBot mode.",
    }, "failed");
  }
  if (!isClaudeArcBotModel(model)) {
    const modelCatalog = await getCodexModelCatalog();
    if (modelCatalog.upgradeRequired === true) {
      return finishArcBotRequest({
        ok: false,
        needsAuth: false,
        needsRepair: true,
        error: `Codex CLI must be updated before ArcBot can use ${modelCatalog.minimumDefaultModel}. Run Repair, then refresh ArcBot status.`,
      }, "failed");
    }
    if (CODEX_APP_SERVER_ENABLED && modelCatalog.verified !== true) {
      return finishArcBotRequest({
        ok: false,
        needsAuth: false,
        needsRepair: true,
        error: `ArcBot could not verify the available Codex models. Refresh status to retry, or run Repair to update the per-user CLI. ${modelCatalog.warning || ""}`.trim(),
      }, "failed");
    }
    const reconciledEffort = reconcileArcBotReasoningEffort(model, reasoningEffort);
    if (reconciledEffort !== reasoningEffort) {
      requestLog.mark("reasoning_effort_reconciled", {
        requested: reasoningEffort,
        selected: reconciledEffort,
        runtimeModel: getArcBotRuntimeModel(model) || "codex",
      });
      reasoningEffort = reconciledEffort;
    }
  }
  const requestState = requestId ? { canceled: false, cancelProcess: null } : null;
  if (requestId) activeCodexAssistantRequests.set(requestId, requestState);
  const canceledResponse = (usage = null) => ({
    ok: false,
    needsAuth: false,
    canceled: true,
    error: "Request canceled.",
    ...(usage ? { usage } : {}),
  });
  sendArcBotActivity(event, requestId, "activity", "Resolving ArcBot working folders...");
  requestLog.start("resolve_working_folders");
  // ArcBot works in the local exchange folder and reads other project data
  // through the server; only folders the user added are named to it.
  const exchangeFolder = getArcBotWorkspaceRoot();
  fs.mkdirSync(exchangeFolder, { recursive: true });
  const readableFolders = await getArcBotReadableRootsForSandbox();
  requestLog.end("resolve_working_folders", { exchangeFolder, readableFolders });
  if (readableFolders.length) {
    sendArcBotActivity(event, requestId, "activity", "ArcBot can read the configured folders for this request.", {
      debugText: `ArcBot readable folders: ${readableFolders.join("; ")}`,
    });
  }
  const activeContext = payload?.activeContext && typeof payload.activeContext === "object"
    ? payload.activeContext
    : null;
  requestLog.mark("active_context_received", {
    available: !!activeContext?.available,
    tabType: activeContext?.tabType || "home",
    title: activeContext?.title || "",
    targetPath: activeContext?.targetPath || activeContext?.path || "",
  });
  sendArcBotActivity(event, requestId, "context", activeContext?.available ? "Loaded active tab context." : "No active tab context was provided.", {
    context: {
      tabType: activeContext?.tabType || "home",
      title: activeContext?.title || "",
      targetPath: activeContext?.targetPath || activeContext?.path || "",
    },
  });
  const targetPath = getAssistantTargetJsonPath(activeContext);
  const attachments = Array.isArray(payload?.attachments)
    ? payload.attachments.slice(0, 5).map((item) => ({
        name: String(item?.name || path.basename(String(item?.path || "")) || "attachment"),
        path: String(item?.path || ""),
        size: Number.isFinite(item?.size) ? Math.max(0, Math.round(item.size)) : 0,
        text: String(item?.text || "").slice(0, 60000),
      })).filter((item) => item.text.trim())
    : [];
  requestLog.mark("attachments_prepared", {
    attachmentCount: attachments.length,
    attachmentNames: attachments.map((item) => item.name),
    attachmentChars: attachments.reduce((sum, item) => sum + item.text.length, 0),
  });
  const activePageJson = getArcBotActivePageJson(activeContext, targetPath);
  const activeJson = activePageJson.json;
  requestLog.mark("active_json_source", { source: activePageJson.source || "none", targetPath });
  let editSession = null;
  const activeJsonIsError = activeJson && typeof activeJson.error === "string";
  const editLikeMode = mode === "edit" || mode === "approve";
  const deferDfmApproval = mode === "approve" && isArcBotDfmContext(activeContext);
  if (
    editLikeMode
    && isArcBotEditableTarget(targetPath)
    && activeJson
    && !activeJsonIsError
    && !isClaudeArcBotModel(model)
  ) {
    sendArcBotActivity(event, requestId, "activity", "Creating editable local JSON-backed copy...");
    requestLog.start("create_edit_session", { targetPath });
    editSession = createArcBotEditSession({ targetPath, activeJson, serverRoot: getConfiguredWorkspaceRoot() });
    requestLog.end("create_edit_session", {
      sessionDir: editSession.sessionDir,
      jsonPath: editSession.jsonPath,
      exchangeRoot: editSession.exchangeRoot || "",
      stagedFileCount: editSession.manifestFiles?.length || 0,
    });
  }
  const codexCwd = editSession?.codexCwd || exchangeFolder;
  const codexSandbox = editSession ? "workspace-write" : "read-only";
  requestLog.start("build_prompt", {
    mode,
    codexCwd,
    codexSandbox,
    hasEditSession: !!editSession,
  });
  const promptFiles = await requestArcBotPromptFiles();
  if (promptFiles?.error) requestLog.mark("prompt_files_unavailable", { error: promptFiles.error });
  let skill = null;
  if (payload?.skillId) {
    const skillAnswer = await requestAgentSkills(String(payload.skillId));
    skill = (skillAnswer.skills || []).find((item) => item.id === payload.skillId && item.instructions) || null;
    const skillError = skillAnswer.error
      || (!skill && `The skill "${payload.skillId}" was not found on the server.`)
      || (!skillAppliesToContext(skill, activeContext) && `The ${skill.title} skill needs a ${skill.scope.toUpperCase()} window open.`);
    if (skillError) {
      activeCodexAssistantRequests.delete(requestId);
      return finishArcBotRequest({ ok: false, needsAuth: false, error: String(skillError) }, "failed");
    }
    requestLog.mark("skill_loaded", { skillId: skill.id, version: skill.version });
  }
  const rawPrompt = buildAssistantPrompt(
    payload?.messages,
    promptMode,
    codexCwd,
    readableFolders,
    activeContext,
    activeJson,
    editSession,
    attachments,
    promptFiles,
    skill
  );
  const prompt = clampCodexPrompt(rawPrompt);
  requestLog.end("build_prompt", {
    rawPromptChars: rawPrompt.length,
    promptChars: prompt.length,
    truncated: prompt.length < rawPrompt.length,
  });
  requestLog.start("estimate_context_usage");
  const usage = estimateArcBotContextUsage(rawPrompt, payload?.messages, activeContext, activeJson, prompt, attachments);
  requestLog.end("estimate_context_usage", {
    estimatedTokens: usage.estimatedTokens,
    contextWindowTokens: usage.contextWindowTokens,
    contextPercentUsed: usage.contextPercentUsed,
  });
  if (requestState?.canceled) {
    activeCodexAssistantRequests.delete(requestId);
    return finishArcBotRequest(canceledResponse(usage), "canceled");
  }
  sendArcBotActivity(
    event,
    requestId,
    "usage",
    `Context estimate: ~${usage.estimatedTokens.toLocaleString()} of ${usage.contextWindowTokens.toLocaleString()} tokens (${usage.contextPercentUsed.toFixed(usage.contextPercentUsed < 10 ? 1 : 0)}%).`,
    { usage }
  );
  let result = null;
  if (isClaudeArcBotModel(model)) {
    requestLog.start("claude_request", { model, reasoningEffort });
    result = await runClaudeArcBotRequest({
      event,
      requestId,
      requestState,
      model,
      reasoningEffort,
      systemText: buildClaudeSystemPrompt(mode, activeContext, activeJson, skill),
      messages: payload?.messages,
      attachments,
      usage,
      cwd: codexCwd,
      // Claude has tools only while a skill runs.
      ...(skill ? { tools: [PROJECT_READ_TOOL, RUN_MACRO_TOOL], runTool: (params) => executeArcBotTool(params, activeContext, skill) } : {}),
    });
    requestLog.end("claude_request", {
      ok: !!result?.ok,
      canceled: !!result?.canceled,
      stdoutChars: String(result?.stdout || "").length,
      error: result?.error || "",
    });
  } else {
    sendArcBotActivity(event, requestId, "activity", `Starting warm Codex session with ${model === "codex" ? "the Codex default model" : model} at ${reasoningEffort} reasoning in ${editLikeMode ? "Edit Mode" : "Review Mode"}...`);
    requestLog.start("warm_codex_turn", {
      codexCwd,
      codexSandbox,
      mode,
      model,
      reasoningEffort,
      readableFolders,
    });
    try {
      result = await runCodexWarmTurn({
        event,
        requestId,
        requestState,
        payload,
        mode,
        model,
        reasoningEffort,
        codexCwd,
        codexSandbox,
        prompt,
        skill,
      });
      requestLog.end("warm_codex_turn", {
        ok: !!result?.ok,
        code: result?.code ?? null,
        canceled: !!result?.canceled,
        stdoutChars: String(result?.stdout || "").length,
        stderrChars: String(result?.stderr || "").length,
        error: result?.error || "",
      });
    } catch (err) {
      requestLog.end("warm_codex_turn", {
        ok: false,
        canceled: !!requestState?.canceled,
        error: String(err?.message || err || "Codex warm session failed."),
      });
      if (requestState?.canceled) {
        result = { ok: false, canceled: true, stdout: "", stderr: "", error: "Request canceled." };
      } else {
        const warmError = String(err?.message || err || "Codex warm session failed.");
        sendArcBotActivity(event, requestId, "stderr", `${warmError}\n`);
        sendArcBotActivity(event, requestId, "activity", "Warm Codex session unavailable; using one-shot Codex CLI.");
        const execArgs = [
          "exec",
          "--ephemeral",
          "--color",
          "never",
          "--sandbox",
          codexSandbox,
          "--skip-git-repo-check",
          "--cd",
          codexCwd,
          "--config",
          `model_reasoning_effort="${reasoningEffort}"`,
        ];
        const runtimeModel = getArcBotRuntimeModel(model);
        if (runtimeModel) execArgs.push("--model", runtimeModel);
        requestLog.start("fallback_codex_cli", {
          codexCwd,
          codexSandbox,
          mode,
          model,
          reasoningEffort,
        });
        try {
          result = await runCodexCommand(execArgs, {
            input: prompt,
            timeoutMs: CODEX_ASSISTANT_TIMEOUT_MS,
            cancelKey: requestId,
            onStdout: (chunk) => sendArcBotActivity(event, requestId, "stdout", chunk),
            onStderr: (chunk) => sendArcBotActivity(event, requestId, "stderr", chunk),
          });
          requestLog.end("fallback_codex_cli", {
            ok: !!result?.ok,
            code: result?.code ?? null,
            signal: result?.signal || "",
            timedOut: !!result?.timedOut,
            canceled: !!result?.canceled,
            stdoutChars: String(result?.stdout || "").length,
            stderrChars: String(result?.stderr || "").length,
            error: result?.error || "",
          });
        } catch (execErr) {
          requestLog.end("fallback_codex_cli", {
            ok: false,
            error: String(execErr?.message || execErr || "Codex CLI fallback failed."),
          });
          result = {
            ok: false,
            stdout: "",
            stderr: "",
            error: String(execErr?.message || execErr || "Codex CLI fallback failed."),
          };
        }
      }
    }
  }
  if (requestId && activeCodexAssistantRequests.get(requestId) === requestState) {
    activeCodexAssistantRequests.delete(requestId);
  }

  if (!result.ok) {
    sendArcBotActivity(event, requestId, "error", normalizeHostError(result, "Codex CLI request failed."));
    return finishArcBotRequest({
      ok: false,
      needsAuth: isAuthFailure(result),
      canceled: !!result.canceled,
      error: normalizeHostError(result, "Codex CLI request failed."),
      usage,
    }, result.canceled ? "canceled" : "failed");
  }
  const rawText = String(result.stdout || "").trim();
  requestLog.mark("response_received", {
    stdoutChars: rawText.length,
    stderrChars: String(result.stderr || "").length,
  });
  sendArcBotActivity(event, requestId, "activity", "ArcBot response received.");
  if (editLikeMode) {
    if (editSession) {
      let editedJson = null;
      let editedText = "";
      try {
        requestLog.start("read_edited_json_copy", { jsonPath: editSession.jsonPath });
        editedText = fs.readFileSync(editSession.jsonPath, "utf8");
        try {
          editedJson = JSON.parse(editedText);
        } catch {
          const extractedJsonText = extractJsonText(editedText);
          if (!extractedJsonText) throw new Error("Edited JSON copy did not contain a valid JSON object.");
          editedJson = JSON.parse(extractedJsonText);
          editedText = formatJsonForArcBot(editedJson);
          fs.writeFileSync(editSession.jsonPath, editedText, "utf8");
          sendArcBotActivity(event, requestId, "activity", "Cleaned explanatory text from the edited JSON-backed copy.");
        }
        requestLog.end("read_edited_json_copy", {
          ok: true,
          changed: sha256Text(editedText) !== editSession.beforeSha256,
          chars: editedText.length,
        });
      } catch (err) {
        requestLog.end("read_edited_json_copy", {
          ok: false,
          error: String(err?.message || err || "Edited JSON copy could not be read."),
        });
        const message = String(err?.message || err || "Edited JSON copy could not be read.");
        return finishArcBotRequest({
          ok: false,
          needsAuth: false,
          error: `ArcBot could not apply the temp JSON copy. ${message}`,
          usage,
        }, "failed");
      }
      if (sha256Text(editedText) !== editSession.beforeSha256) {
        const replacementJson = editedJson;
        const structured = extractJsonObject(rawText);
        // The open page applies the edit and saves it through its own save,
        // so nothing here writes the target file.
        sendArcBotActivity(
          event,
          requestId,
          "activity",
          deferDfmApproval ? "Prepared DFM edit for approval." : "Handing the edit to the page...",
        );
        requestLog.mark("edit_handed_to_page", {
          targetPath: editSession.targetPath,
          pendingApproval: deferDfmApproval,
          replyFromStructuredOutput: !!structured?.reply,
        });
        return finishArcBotRequest({
          ok: true,
          text: structured?.reply || rawText || (deferDfmApproval ? "Review the proposed DFM edit." : "Prepared the edit."),
          editProposed: true,
          editPendingApproval: deferDfmApproval,
          targetPath: editSession.targetPath,
          originalJson: activeJson,
          proposedJson: replacementJson,
          proposedText: formatJsonForArcBot(replacementJson),
          usage,
        });
      }
    }
    const dashboardEdit = !editSession && isArcBotDashboardContext(activeContext) && isArcBotEditableTarget(targetPath)
      ? extractClaudeDashboardEdit(rawText)
      : null;
    if (dashboardEdit) {
      sendArcBotActivity(event, requestId, "activity", "Handing the edit to the page...");
      requestLog.mark("edit_handed_to_page", { targetPath, pendingApproval: false, replyFromStructuredOutput: true });
      return finishArcBotRequest({
        ok: true,
        text: dashboardEdit.reply || "Prepared the edit.",
        editProposed: true,
        editPendingApproval: false,
        targetPath,
        originalJson: activeJson,
        proposedJson: dashboardEdit.dashboard,
        proposedText: formatJsonForArcBot(dashboardEdit.dashboard),
        usage,
      });
    }
    const structured = extractJsonObject(rawText);
    if (structured?.action === "answer" || structured?.action === "edited" || structured?.action === "no_edit") {
      return finishArcBotRequest({
        ok: true,
        text: String(structured.reply || "").trim() || "No response.",
        usage,
      });
    }
  }
  return finishArcBotRequest({
    ok: true,
    text: rawText,
    progress: String(result.stderr || "").trim(),
    usage,
  });
});

ipcMain.handle("codex-assistant-cancel", async (_event, payload) => {
  const requestId = String(payload?.requestId || "");
  if (!requestId) return { ok: false, error: "Missing ArcBot request id." };
  arcBotRequestLoggers.get(requestId)?.mark("cancel_requested");
  const active = activeCodexAssistantRequests.get(requestId);
  if (typeof active === "function") {
    const canceled = active();
    return canceled ? { ok: true } : { ok: false, error: "ArcBot request already completed." };
  }
  if (!active || typeof active !== "object") return { ok: false, error: "No active ArcBot request to cancel." };
  active.canceled = true;
  const canceled = typeof active.cancelProcess === "function" ? active.cancelProcess() : true;
  return canceled ? { ok: true } : { ok: false, error: "ArcBot request already completed." };
});

return {
  stop() {
    voice.stop();
    resetCodexAppServerClient();
  },
};

}

module.exports = {
  registerArcBotIpc,
  testHooks: {
    CodexAppServerClient,
    getCodexSandboxPolicy,
    getCodexInterruptParams,
    getCodexNotificationIdentity,
    buildCodexModelCatalog,
    getCodexModelCatalog,
    getFallbackCodexModelCatalog,
    isCodexNotificationForTurn,
    getArcBotCodexEnv,
    getArcBotHostCwd,
    getClaudeCredentialsPath,
    getNodeBackedCodexSpec,
    getClaudeCommand,
    getUserInstalledCodexCommand,
    launchDetachedArcBotProcess,
    migrateLegacyCliInstalls,
    listClaudeModelEntries,
    reconcileArcBotReasoningEffort,
    runClaudeArcBotRequest,
    runCodexCommand,
    runCodexWarmTurn,
    startCodexWarmThread,
    withArcBotHostCwd,
    writeCodexInstallScript,
  },
};
