import { ensureAiAssistantDom } from "./template.js?v=20260927smb24";
import {
  ATTACHMENT_EXTENSIONS as ASSISTANT_ATTACHMENT_EXTENSIONS,
  PANEL_DEFAULT_HEIGHT as ASSISTANT_PANEL_DEFAULT_HEIGHT,
  VISIBLE_WORK_STEP_IDS as ASSISTANT_VISIBLE_WORK_STEP_IDS,
  WORK_STEP_DEFS as ASSISTANT_WORK_STEP_DEFS,
  WORK_TYPING_CHARS_PER_FRAME as ASSISTANT_WORK_TYPING_CHARS_PER_FRAME,
  WORK_TYPING_FRAME_MS as ASSISTANT_WORK_TYPING_FRAME_MS,
} from "./state.js";
import {
  applyAssistantModelCatalog,
  assistantModelSupportsReasoning,
  getAssistantModelOptions,
  getAssistantReasoningOptionsForModel,
  getAssistantModelProvider,
  getDefaultAssistantModel,
  getDefaultAssistantModelFor,
  getDefaultAssistantReasoningEffort,
  getAssistantModelLabelFor,
  getAssistantReasoningLabelFor,
  isClaudeAssistantModel,
  normalizeAssistantModel,
  normalizeAssistantReasoningEffort,
  reconcileAssistantReasoningEffort,
  shouldShowTokenAlertFor,
} from "./models.js";
import {
  appendAssistantInlineMarkdown,
  createAssistantUserAvatarSvg,
  renderAssistantMessageContent,
  typeAssistantMessage as typeAssistantMessageContent,
} from "./messages.js?v=20260622a";
import {
  normalizeActivities,
  normalizeDebugLogs,
  normalizeMessages,
  nowIso,
} from "./sessions.js";
import {
  formatContextPercent,
  formatContextWindowUsage,
  formatTokenCount,
  getUsagePercent,
  normalizeAssistantContextForPanel,
} from "./context.js";
import {
  getAttachmentIconKind,
  getAttachmentIconSvg,
  getAttachmentTypeLabel,
} from "./attachments.js";
import { formatElapsed, formatWorkDuration } from "./activity.js";
import { installVoiceInput } from "./voice.js";
import { addComposerTip } from "./composer-tip.js";
import { arcBotEditScopeError } from "./edit-scope.js";
import { installAssistantSelectMenu, syncAssistantSelectMenu } from "./select-menu.js";
import { installAssistantAccounts } from "./accounts.js";
import { getAssistantToolLabel } from "./tool-labels.js";

let assistantVoice = null;
let assistantAccounts = null;
// The one account every chat runs under; its provider decides which models a chat can use.
let assistantAccount = null;
let preparationGeneration = 0;
async function prepareAssistantSession() {
  const host = getHostApi();
  if (!currentSessionId || assistantBusy || !host?.codexAssistantPrepare) return;
  const generation = ++preparationGeneration;
  const status = $("aiAssistantSessionStatus");
  if (status) status.textContent = "";
  try {
    const result = await host.codexAssistantPrepare({ sessionId: currentSessionId, model: assistantModel });
    if (generation !== preparationGeneration) return;
    if (status) {
      status.textContent = result?.ok ? "" : "Preparation failed · retry on send";
      status.title = result?.error || "";
    }
  } catch (error) {
    if (generation === preparationGeneration && status) {
      status.textContent = "Preparation failed · retry on send";
      status.title = String(error.message || error);
    }
  }
}
import { normalizeReadableRootList } from "./settings.js";
import { clampAssistantPanelSize } from "./layout.js";
import { getHostErrorMessage } from "./host.js";
import { createAssistantRunGate } from "./run-gate.js?v=20260726a";
import {
  SQL_FORMAT_VALIDATION_SKILL,
  SQL_AI_REVIEW_RESPONSE_SCHEMA,
  SQL_CODING_STANDARDS_MARKDOWN_LINK,
  buildSqlFormatFindings,
  buildSqlReviewPrompt,
  inferSqlDialect,
  renderSqlAiReviewResponse,
  requestSqlFormatPreview,
} from "./skills.js?v=20260726a";

const defaultShell = {};
const assistantRunGate = createAssistantRunGate();
let shell = defaultShell;
let getHostApi = () => window.ADAHost || null;
let $ = (id) => document.getElementById(id);
let assistantConfig = {
  appName: "Arcode",
  botName: "ArcBot",
  messageNamespace: "arcode",
  storagePrefix: "arcode",
  contextTimeoutMs: 900,
  projectInstanceContextTimeoutMs: 900,
  enableDfmApproval: false,
  getAppContextTooltipRows: null,
};
let ASSISTANT_LAUNCHER_VISIBLE_KEY = "arcode_ai_assistant_launcher_visible";
let ASSISTANT_LAUNCHER_POSITION_KEY = "arcode_ai_assistant_launcher_position";
let ASSISTANT_PANEL_SIZE_KEY = "arcode_ai_assistant_panel_size";
let ASSISTANT_PANEL_OPENED_SESSION_KEY = "arcode_ai_assistant_panel_opened_session";

let assistantMessages = [];
let assistantActivities = [];
let assistantDebugLogs = [];
let assistantAttachments = [];
let currentSessionId = "";
let currentSessionTitle = "New ArcBot Chat";
let currentContext = null;
let currentUsage = null;
let currentRequestId = "";
let currentPendingMessageEl = null;
let currentAssistantStreamText = "";
let currentRunStartedAt = 0;
let currentStepStartedAt = 0;
let currentWorkCardEl = null;
let assistantWorkCardExpanded = false;
const assistantOpenCommandKeys = new Set();
let assistantProgressSteps = [];
let assistantProgressTicker = null;
let latestSessionList = [];
let assistantMode = "edit";
let assistantModel = "codex";
let assistantReasoningEffort = normalizeAssistantReasoningEffort("");
let assistantReadableRoots = [];
let assistantReady = false;
let assistantBusy = false;
let assistantCancelRequested = false;
let assistantHostRequestSubmitted = false;
let assistantAppContextEnabled = true;
let assistantStatusChecked = false;
let assistantModelCatalogChecked = false;
let assistantModelDefaultVerified = false;
let assistantModelCatalogRequest = null;
let assistantInstallJustSucceeded = false;
let assistantLoginPending = false;
let suppressLauncherClick = false;
let assistantLauncherVisible = true;
let assistantUserAvatarName = "Arcode";
const assistantActivityTypingStates = new Map();
let assistantActivityTypingTimer = null;
let assistantSkillMenuOpen = false;
let assistantSkillFilter = "";
let assistantSqlReviewState = null;
let assistantSqlReviewDragState = null;
let assistantSqlReviewDialogPosition = null;
let assistantSqlReviewResizeState = null;
let assistantSqlReviewDialogSize = null;
const assistantSkills = [SQL_FORMAT_VALIDATION_SKILL];
// Skills the team keeps on the server (shared\agent-skills); they run as chat turns.
let serverAssistantSkills = [];
const SQL_REVIEW_DIALOG_MIN_WIDTH = 520;
const SQL_REVIEW_DIALOG_MIN_HEIGHT = 360;
const SQL_REVIEW_DIALOG_Z = 9400;
const SQL_REVIEW_DIALOG_ACTIVE_Z = 9500;
const ASSISTANT_PANEL_FRONT_Z = 9600;
const SQL_DIFF_KEYWORDS = new Set([
  "ADD", "ALL", "ALTER", "AND", "AS", "ASC", "BEGIN", "BETWEEN", "BY", "CASE", "CREATE",
  "CROSS", "DELETE", "DESC", "DISTINCT", "DROP", "ELSE", "END", "EXCEPT", "EXEC", "EXISTS",
  "FROM", "FULL", "GROUP", "HAVING", "IF", "IN", "INNER", "INSERT", "INTERSECT", "INTO",
  "IS", "JOIN", "LEFT", "LIKE", "MERGE", "NOT", "NULL", "ON", "OR", "ORDER", "OUTER",
  "OVER", "PARTITION", "RIGHT", "SELECT", "SET", "TABLE", "THEN", "TOP", "TRUNCATE",
  "UNION", "UPDATE", "VALUES", "WHEN", "WHERE", "WITH",
]);
const SQL_DIFF_FUNCTIONS = new Set([
  "AVG", "CAST", "COALESCE", "CONVERT", "COUNT", "DATEADD", "DATEDIFF", "DATENAME",
  "DATEPART", "EOMONTH", "GETDATE", "IIF", "ISNULL", "LEN", "LOWER", "MAX", "MIN",
  "NULLIF", "REPLACE", "ROUND", "ROW_NUMBER", "RTRIM", "SUM", "TRY_CAST", "TRY_CONVERT", "UPPER",
]);
const SQL_DIFF_DATATYPES = new Set([
  "BIGINT", "BINARY", "BIT", "CHAR", "DATE", "DATETIME", "DATETIME2", "DECIMAL", "FLOAT",
  "INT", "MONEY", "NCHAR", "NUMERIC", "NVARCHAR", "REAL", "SMALLDATETIME", "SMALLINT",
  "TEXT", "TIME", "TIMESTAMP", "TINYINT", "UNIQUEIDENTIFIER", "VARBINARY", "VARCHAR", "XML",
]);

export function configureAiAssistant(config = {}) {
  assistantConfig = {
    ...assistantConfig,
    ...config,
  };
  shell = config.shell || shell || defaultShell;
  getHostApi = typeof config.getHostApi === "function" ? config.getHostApi : getHostApi;
  $ = typeof config.$ === "function" ? config.$ : $;
  const storagePrefix = String(assistantConfig.storagePrefix || assistantConfig.messageNamespace || "arcode").trim() || "arcode";
  assistantConfig.storagePrefix = storagePrefix;
  ASSISTANT_LAUNCHER_VISIBLE_KEY = `${storagePrefix}_ai_assistant_launcher_visible`;
  ASSISTANT_LAUNCHER_POSITION_KEY = `${storagePrefix}_ai_assistant_launcher_position`;
  ASSISTANT_PANEL_SIZE_KEY = `${storagePrefix}_ai_assistant_panel_size`;
  ASSISTANT_PANEL_OPENED_SESSION_KEY = `${storagePrefix}_ai_assistant_panel_opened_session`;
  assistantLauncherVisible = readAssistantLauncherVisibleFallback();
  assistantUserAvatarName = String(assistantConfig.appName || "Arcode").trim() || "Arcode";
}

function assistantMessageType(name) {
  const namespace = String(assistantConfig.messageNamespace || "arcode").trim() || "arcode";
  return `${namespace}:assistant-${name}`;
}

function setText(el, text) {
  if (el) el.textContent = text || "";
}

let assistantStatusDetail = "";

function setAssistantConnectionStatus(online, detail = "") {
  const el = $("aiAssistantConnectionStatus");
  if (!el) return;
  assistantStatusDetail = detail;
  el.classList.toggle("online", !!online);
  el.classList.toggle("offline", !online);
  el.textContent = online ? "Online" : "Offline";
  el.setAttribute("aria-label", online ? "ArcBot online" : "ArcBot offline");
  el.title = [
    online ? "ArcBot is online" : "ArcBot is offline",
    detail,
    `Account: ${formatAssistantAccount()}`,
  ].filter(Boolean).join("\n");
  updateAssistantSettingsPanel();
}

function setStatus(text, _tone = "") {
  setAssistantConnectionStatus(assistantReady, text);
}

function getAssistantModelLabel(model = assistantModel) {
  return getAssistantModelLabelFor(model);
}

function getAssistantReasoningLabel(effort = assistantReasoningEffort) {
  return getAssistantReasoningLabelFor(effort);
}

function isClaudeModel(model = assistantModel) {
  return isClaudeAssistantModel(model);
}

function assistantModelHasReasoning(model = assistantModel) {
  return assistantModelSupportsReasoning(model);
}

function shouldShowAssistantTokenAlert() {
  return shouldShowTokenAlertFor(assistantModel, assistantReasoningEffort);
}

function getAssistantAccountProvider() {
  if (!assistantAccount) return "";
  return assistantAccount.provider === "claude" ? "anthropic" : "openai";
}

// A chat runs on the selected account, so a model from the other provider falls back to that provider's default.
function accountModel(model) {
  const normalized = normalizeAssistantModel(model);
  const provider = getAssistantAccountProvider();
  if (!provider || getAssistantModelProvider(normalized) === provider) return normalized;
  return getDefaultAssistantModelFor(provider) || normalized;
}

function formatAssistantAccount() {
  if (!assistantAccount) return "Loading…";
  const provider = assistantAccount.provider === "claude" ? "Anthropic" : "OpenAI";
  const state = assistantAccount.pending
    ? "signing in"
    : assistantAccount.signedIn ? (assistantAccount.email || assistantAccount.plan) : "not signed in";
  return `${assistantAccount.label} (${[provider, state].filter(Boolean).join(", ")})`;
}

// Both providers keep a conversation's saved prompt cache for about an hour.
const ASSISTANT_CACHE_WARM_MS = 60 * 60 * 1000;

function isAssistantCacheWarm() {
  const last = [...assistantMessages].reverse().find((message) => message.role === "assistant");
  const age = last ? Date.now() - Date.parse(last.timestamp) : Infinity;
  return age >= 0 && age < ASSISTANT_CACHE_WARM_MS;
}

// A quiet line at the end of the chat; it goes away once the conversation continues.
function showAssistantChatNotice(text) {
  const container = $("aiAssistantMessages");
  if (!container) return;
  container.querySelectorAll(".aiAssistantChatNotice").forEach((node) => node.remove());
  const notice = document.createElement("div");
  notice.className = "aiAssistantChatNotice";
  notice.setAttribute("role", "status");
  notice.textContent = text;
  container.appendChild(notice);
  container.scrollTop = container.scrollHeight;
}

const ASSISTANT_SLOWER_REPLY_NOTE = "The first reply may be slower.";

function noticeAssistantModelSwitch() {
  if (!assistantMessages.length) return;
  showAssistantChatNotice([`Switched to ${getAssistantModelLabel()}.`, isAssistantCacheWarm() ? ASSISTANT_SLOWER_REPLY_NOTE : ""].filter(Boolean).join(" "));
}

function handleAssistantAccountActive(account) {
  const previousAccount = assistantAccount;
  const previousModel = assistantModel;
  const providerChanged = (account?.provider || "") !== (assistantAccount?.provider || "");
  assistantAccount = account;
  if (providerChanged) {
    if (accountModel(assistantModel) !== assistantModel) setAssistantModel(assistantModel, { save: !!currentSessionId });
    else renderAssistantModelOptions();
  }
  if (previousAccount && account && account.id !== previousAccount.id && assistantMessages.length) {
    if (assistantModel !== previousModel) {
      showAssistantChatNotice(`Continuing this chat on ${getAssistantModelLabel()} with ${account.label}.`);
    } else {
      showAssistantChatNotice([`Account changed to ${account.label}.`, isAssistantCacheWarm() ? ASSISTANT_SLOWER_REPLY_NOTE : ""].filter(Boolean).join(" "));
    }
  }
  updateContextPanel();
  setAssistantConnectionStatus(assistantReady, assistantStatusDetail);
}

function renderAssistantModelOptions() {
  const select = $("aiAssistantSettingsModelSelect");
  if (!select) return;
  const defaultModel = getDefaultAssistantModel();
  const accountProvider = getAssistantAccountProvider();
  const options = getAssistantModelOptions(assistantModel)
    .filter((option) => !accountProvider || option.provider === accountProvider);
  const providerGroups = [
    ["openai", "OpenAI"],
    ["anthropic", "Anthropic"],
  ];
  select.textContent = "";
  for (const [provider, label] of providerGroups) {
    const providerOptions = options.filter((option) => option.provider === provider);
    if (!providerOptions.length) continue;
    const group = document.createElement("optgroup");
    group.label = label;
    for (const modelOption of providerOptions) {
      const option = document.createElement("option");
      option.value = modelOption.value;
      option.textContent = modelOption.label;
      if ((modelOption.isDefault || modelOption.value === defaultModel) && modelOption.available !== false) {
        option.dataset.note = "Default";
      }
      option.disabled = modelOption.available === false;
      group.appendChild(option);
    }
    select.appendChild(group);
  }
  select.value = assistantModel;
  syncAssistantSelectMenu(select);
}

function renderAssistantReasoningOptions() {
  const select = $("aiAssistantSettingsReasoningSelect");
  if (!select) return;
  const options = getAssistantReasoningOptionsForModel(assistantModel);
  select.textContent = "";
  for (const reasoningOption of options) {
    const option = document.createElement("option");
    option.value = reasoningOption.value;
    option.textContent = reasoningOption.label;
    select.appendChild(option);
  }
  select.value = assistantReasoningEffort;
  syncAssistantSelectMenu(select);
}

function setSetup({ open = false, text = "", install = false, installLabel = "Install", login = false } = {}) {
  const setup = $("aiAssistantSetup");
  const setupText = $("aiAssistantSetupText");
  const installBtn = $("aiAssistantSetupBtn");
  const loginBtn = $("aiAssistantLoginBtn");
  setup?.classList.toggle("open", !!open);
  setText(setupText, text);
  if (installBtn) {
    installBtn.style.display = install ? "inline-block" : "none";
    installBtn.textContent = installLabel;
  }
  if (loginBtn) loginBtn.style.display = login ? "inline-block" : "none";
}

function getSessionPayload() {
  return {
    id: currentSessionId,
    title: currentSessionTitle,
    mode: assistantMode,
    model: assistantModel,
    reasoningEffort: assistantReasoningEffort,
    messages: assistantMessages,
    activities: assistantActivities,
    debugLogs: assistantDebugLogs,
    context: currentContext,
    usage: currentUsage,
  };
}

async function saveCurrentSession() {
  const host = getHostApi();
  if (!host?.codexAssistantSaveSession || !currentSessionId) return;
  try {
    const result = await host.codexAssistantSaveSession(getSessionPayload());
    if (result?.ok && result.session) {
      currentSessionId = result.session.id || currentSessionId;
      currentSessionTitle = result.session.title || currentSessionTitle;
      updateSessionSelectLabel();
    }
  } catch {
    // Session persistence failures should not block chat.
  }
}

function renderMessages() {
  const container = $("aiAssistantMessages");
  if (!container) return;
  container.textContent = "";
  currentWorkCardEl = null;
  assistantWorkCardExpanded = false;
  appendAssistantDisclaimer(container);
  for (const message of assistantMessages) {
    appendMessage(message.role, message.content, { save: false });
  }
  renderActivities();
}

function appendAssistantDisclaimer(container) {
  if (!container) return;
  const notice = document.createElement("div");
  notice.className = "aiAssistantDisclaimer";
  notice.textContent = "ArcBot is AI-powered and can make mistakes. Double-check important responses.";
  container.appendChild(notice);
}

function getAssistantContextTitle(context = currentContext) {
  const title = String(context?.title || "").trim();
  if (title) return title;
  const tabType = String(context?.tabType || "").trim();
  if (tabType && tabType !== "home") return tabType;
  return "active app tab";
}

function getAssistantContextKind(context = currentContext) {
  const tabType = String(context?.tabType || "").trim().toLowerCase();
  const nestedType = String(context?.nestedPageType || context?.activeNestedWindow?.kind || "").trim().toLowerCase();
  if (tabType === "project_instance" && nestedType === "dfm") return "Project Instance DFM window";
  if (tabType === "project_instance" && nestedType === "dataset") return "Project Instance Dataset window";
  if (tabType === "project_instance") return "Project Instance";
  if (tabType === "dfm") return "DFM page";
  if (tabType === "dataset") return "Dataset Viewer";
  if (tabType === "scripting") return "notebook";
  if (tabType === "off") return "app context";
  return tabType || "active app tab";
}

function getAssistantTargetKind(context = currentContext) {
  const target = String(context?.targetPath || context?.path || "").trim().toLowerCase();
  if (target.endsWith(".ipynb") || target.endsWith(".arcnb")) return "notebook file";
  if (target.endsWith(".json")) return "JSON-backed app file";
  if (context?.tabType === "project_instance" && context?.activeNestedWindow?.kind === "dfm") return "active Project Instance DFM method data";
  if (context?.tabType === "project_instance" && context?.activeNestedWindow?.kind === "dataset") return "active Project Instance dataset window";
  if (context?.tabType === "dfm") return "DFM method data";
  if (context?.tabType === "scripting") return "notebook data";
  return "active app data";
}

function isAssistantDfmWork(context = currentContext) {
  if (!assistantConfig.enableDfmApproval) return false;
  const tabType = String(context?.tabType || context?.pageType || "").trim().toLowerCase();
  const title = String(context?.title || "").trim().toLowerCase();
  const target = String(context?.targetPath || context?.path || "").trim().toLowerCase();
  return tabType === "dfm" || title.includes("dfm") || /(^|[\\/])dfm@/i.test(target);
}

function formatAssistantContextScanStatus(context, fallback = "") {
  if (context?.disabled) return "App Context is off, so Codex will use only the chat and attachments.";
  if (!context?.available) return fallback || "No active app tab data was available for this request.";
  return `Reading ${getAssistantContextKind(context)} context from "${getAssistantContextTitle(context)}".`;
}

function formatAssistantUsageStatus(usage) {
  const tokens = Number(usage?.estimatedTokens || 0);
  const percent = Number(usage?.contextPercentUsed || 0);
  const parts = [];
  if (tokens) parts.push(`about ${tokens.toLocaleString()} tokens${percent ? ` (${formatContextPercent(percent)} of window)` : ""}`);
  if (Number(usage?.attachmentCount || 0)) parts.push(`${Number(usage.attachmentCount).toLocaleString()} attachment(s)`);
  if (Number(usage?.activeJsonChars || 0)) parts.push("active page JSON");
  if (usage?.truncated) parts.push("trimmed to fit");
  return parts.length
    ? `Packed ${parts.join(", ")} for Codex.`
    : "Packed the chat request for Codex.";
}

function updateTokenUsageRing() {
  const usageEl = $("aiAssistantTokenUsage");
  const textEl = $("aiAssistantTokenUsageText");
  const fillEl = usageEl?.querySelector?.(".aiAssistantTokenRingFill");
  if (!usageEl || !textEl || !fillEl) return;
  const usage = currentUsage || {};
  const used = Math.max(0, Math.round(Number(usage.estimatedTokens || 0)));
  const windowTokens = Math.max(0, Math.round(Number(usage.contextWindowTokens || 0)));
  const percent = windowTokens ? getUsagePercent(usage) : 0;
  const measured = !!windowTokens;
  const rows = [["Model", getAssistantModelLabel()]];
  if (assistantModelHasReasoning()) rows.push(["Reasoning", getAssistantReasoningLabel()]);
  rows.push(["Context", measured
    ? `${formatTokenCount(used)} / ${formatTokenCount(windowTokens)} (${formatContextPercent(percent)})`
    : "Not measured yet"]);
  const ariaLabel = rows.map(([label, value]) => `${label}: ${value}`).join(". ");
  textEl.replaceChildren(...rows.flatMap(([label, value]) => {
    const labelEl = document.createElement("span");
    labelEl.className = "aiAssistantTokenUsageLabel";
    labelEl.textContent = label;
    const valueEl = document.createElement("span");
    valueEl.textContent = value;
    return [labelEl, valueEl];
  }));
  fillEl.setAttribute("stroke-dasharray", `${Math.min(100, Math.max(0, percent))} 100`);
  usageEl.classList.toggle("not-measured", !measured);
  usageEl.classList.toggle("high", measured && percent >= 75 && percent < 90);
  usageEl.classList.toggle("critical", measured && percent >= 90);
  usageEl.removeAttribute("title");
  usageEl.setAttribute("aria-label", ariaLabel);
}

function formatAssistantActivityForCard(text, event = {}) {
  if (["command", "command-output", "commentary", "thinking"].includes(event.type)) return String(text || "");
  const raw = String(text || "").trim();
  const lower = raw.toLowerCase();
  const modeLabel = getModeLabel();
  const contextTitle = getAssistantContextTitle();
  const contextKind = getAssistantContextKind();
  const targetKind = getAssistantTargetKind();
  if (!raw) return "";
  if (lower.includes("asking the page to undo")) return "Asking the page to undo the latest ArcBot edit.";
  if (lower.includes("resolving arcbot project")) return "Preparing the local ArcBot workspace and checking the configured server root.";
  if (lower.includes("arcbot can read the configured folders")) return "ArcBot can read the configured folders for this request.";
  if (lower.includes("arcbot can read the configured server root")) return "ArcBot can read the configured server folder for this request.";
  if (lower.includes("creating editable local json")) return `Creating a temporary editable copy of the active ${targetKind}.`;
  if (lower.includes("context estimate")) return formatAssistantUsageStatus(event.usage || currentUsage);
  if (lower.includes("starting warm codex session")) return `ArcBot is sending the request in ${modeLabel} for "${contextTitle}".`;
  if (lower.includes("warm codex session accepted")) return "ArcBot accepted the request and is starting the turn.";
  if (lower.includes("warm codex session unavailable")) return "ArcBot is switching to a one-shot request.";
  if (lower.includes("starting codex cli")) return "ArcBot is starting the prepared request.";
  if (lower.includes("codex is drafting") || lower.includes("arcbot is drafting")) return "ArcBot is drafting the response.";
  if (lower.includes("codex is running a command") || lower.includes("arcbot is running a local check")) return `ArcBot is running a local check in the workspace for the active ${contextKind}.`;
  if (lower.includes("codex is searching") || lower.includes("arcbot is searching")) return "ArcBot is searching for supporting context.";
  if (lower.includes("codex is using a tool") || lower.includes("arcbot is using a tool")) return `ArcBot is using a tool to inspect or validate the active ${targetKind}.`;
  if (lower.includes("codex is preparing file changes") || lower.includes("arcbot is preparing file changes")) return `ArcBot is preparing changes against the temporary ${targetKind} copy.`;
  if (lower.includes("codex updated the task plan") || lower.includes("arcbot updated the task plan")) return "ArcBot updated its task plan before continuing.";
  if (lower.includes("codex response received") || lower.includes("arcbot response received")) return "ArcBot finished drafting and is checking whether a validated update needs to be applied.";
  if (lower.includes("cleaned explanatory text")) return "ArcBot extracted the edited JSON from Codex's response and normalized the temp copy.";
  if (lower.includes("handing the edit to the page")) return `ArcBot is handing the edited ${targetKind} to the page, which applies it and saves it through its own save.`;
  if (lower.includes("request canceled")) return "The request was canceled before completion.";
  if (lower.includes("cancel requested")) return "Stopping the current ArcBot request.";
  if (lower.includes("failed") || lower.includes("could not") || lower.includes("error:")) return raw;
  return raw;
}

function createAssistantProgressSteps() {
  return ASSISTANT_WORK_STEP_DEFS.map((step) => ({
    ...step,
    state: "pending",
    status: "",
    details: [],
    elapsedMs: 0,
    startedAt: 0,
  }));
}

function getAssistantProgressStepIndex(stepId) {
  return ASSISTANT_WORK_STEP_DEFS.findIndex((step) => step.id === stepId);
}

function normalizeAssistantProgressStatus(status) {
  const text = String(status || "").trim();
  if (!text) return "";
  const lower = text.toLowerCase();
  if (lower.includes("checking read/write access")) return "Checking whether the active page can be read and updated.";
  if (lower.includes("creating a temporary editable copy")) return "Preparing a safe app-data working copy before changing anything.";
  if (lower.includes("codex is preparing changes")) return "Preparing the requested app change.";
  if (lower.includes("codex finished drafting")) return "Checking whether the response includes an app update.";
  if (lower.includes("extracted the edited json")) return "Reading the proposed app-data update from the response.";
  if (lower.includes("validating the temp copy")) return "Validating the update, saving a backup, and applying the change.";
  if (lower.includes("applied json-backed edit")) return "Applied the requested app data change after validation.";
  if (lower.includes("response completed")) return "Finished the response.";
  if (lower.includes("request canceled")) return "Request canceled.";
  return "";
}

function appendAssistantProgressDetail(step, status) {
  if (!step) return "";
  if (!isAssistantDfmWork()) return "";
  const detail = normalizeAssistantProgressStatus(status);
  if (!detail) return "";
  if (!Array.isArray(step.details)) step.details = [];
  if (step.details.at(-1) !== detail && !step.details.includes(detail)) {
    step.details.push(detail);
  }
  return detail;
}

function finishAssistantProgressStep(step, state = "completed", status = "") {
  if (!step) return;
  const now = performance.now();
  if (step.startedAt) {
    step.elapsedMs += Math.max(0, now - step.startedAt);
    step.startedAt = 0;
  }
  step.state = state;
  if (status) {
    step.status = isAssistantDfmWork()
      ? (appendAssistantProgressDetail(step, status) || normalizeAssistantProgressStatus(status) || step.status)
      : String(status).trim();
  }
}

function updateAssistantProgressStep(stepId, state = "active", status = "", options = {}) {
  if (!assistantProgressSteps.length) assistantProgressSteps = createAssistantProgressSteps();
  const index = getAssistantProgressStepIndex(stepId);
  if (index < 0) return;
  const now = performance.now();
  assistantProgressSteps.forEach((step, stepIndex) => {
    if (stepIndex < index && (step.state === "pending" || step.state === "active")) {
      finishAssistantProgressStep(step, "completed");
    } else if (stepIndex !== index && step.state === "active") {
      finishAssistantProgressStep(step, stepIndex < index ? "completed" : "pending");
    }
  });
  const step = assistantProgressSteps[index];
  const displayStatus = isAssistantDfmWork()
    ? appendAssistantProgressDetail(step, status)
    : String(status || "").trim();
  if (state === "active") {
    if (step.state !== "active") step.startedAt = now;
    step.state = "active";
    if (displayStatus) step.status = displayStatus;
  } else {
    finishAssistantProgressStep(step, state, displayStatus || status);
  }
  if (options.render !== false) renderActivities();
}

function getAssistantProgressElapsed(step) {
  if (!step) return 0;
  const liveMs = step.state === "active" && step.startedAt
    ? performance.now() - step.startedAt
    : 0;
  return Math.max(0, Math.round(Number(step.elapsedMs || 0) + liveMs));
}

function completeAssistantProgress(status = "Completed") {
  if (!assistantProgressSteps.length) assistantProgressSteps = createAssistantProgressSteps();
  assistantProgressSteps.forEach((step, index) => {
    const finalStatus = index === assistantProgressSteps.length - 1 ? status : "";
    if (step.state !== "failed") finishAssistantProgressStep(step, "completed", finalStatus);
  });
  assistantWorkCardExpanded = false;
  renderActivities();
}

function failAssistantProgress(status = "Request failed") {
  if (!assistantProgressSteps.length) assistantProgressSteps = createAssistantProgressSteps();
  const activeStep = assistantProgressSteps.find((step) => step.state === "active") ||
    assistantProgressSteps.find((step) => step.state === "pending") ||
    assistantProgressSteps.at(-1);
  finishAssistantProgressStep(activeStep, "failed", status);
  assistantWorkCardExpanded = false;
  renderActivities();
}

function classifyAssistantActivity(activity) {
  const text = formatAssistantActivityForCard(activity?.rawText || activity?.text, activity) || String(activity?.text || "");
  const raw = String(activity?.rawText || activity?.text || "");
  const lower = `${text}\n${raw}`.toLowerCase();
  const type = String(activity?.type || "").toLowerCase();
  if (type === "error" || lower.includes("failed") || lower.includes("could not") || lower.includes("error:")) {
    return { stepId: "finalizing", state: "failed", status: text || "Request failed" };
  }
  if (lower.includes("request canceled") || lower.includes("cancel requested")) {
    return { stepId: "finalizing", state: "failed", status: text || "Request canceled" };
  }
  if (lower.includes("request received") || lower.includes("understanding") || lower.includes("reading your request")) {
    return { stepId: "understanding", state: "active", status: text || "Reading the request" };
  }
  if (
    lower.includes("active context") ||
    lower.includes("active app") ||
    lower.includes("active page") ||
    lower.includes("active json") ||
    lower.includes("active file") ||
    lower.includes("context estimate") ||
    lower.includes("scanned")
  ) {
    return { stepId: "scanning", state: "active", status: text };
  }
  if (
    lower.includes("codex") ||
    lower.includes("editable local") ||
    lower.includes("edit started") ||
    lower.includes("session prepared") ||
    lower.includes("resolving arcbot project") ||
    lower.includes("warm session") ||
    lower.includes("cli")
  ) {
    return { stepId: "executing", state: "active", status: text };
  }
  if (
    lower.includes("validating") ||
    lower.includes("applying") ||
    lower.includes("response received") ||
    lower.includes("response completed") ||
    lower.includes("edit completed") ||
    lower.includes("applied json") ||
    lower.includes("cleaned edited json")
  ) {
    const complete = lower.includes("response completed") || lower.includes("applied json");
    return { stepId: "finalizing", state: complete ? "completed" : "active", status: text };
  }
  return null;
}

function updateAssistantProgressFromActivity(activity, options = {}) {
  const progress = classifyAssistantActivity(activity);
  if (!progress) return;
  updateAssistantProgressStep(progress.stepId, progress.state, progress.status, options);
}

function inferAssistantProgressSteps(activities) {
  const savedSteps = createAssistantProgressSteps();
  const previousSteps = assistantProgressSteps;
  assistantProgressSteps = savedSteps;
  for (const activity of activities || []) {
    updateAssistantProgressFromActivity(activity, { render: false });
  }
  if ((activities || []).length && !savedSteps.some((step) => step.state === "failed")) {
    savedSteps.forEach((step) => {
      if (step.state === "active" || step.state === "pending") finishAssistantProgressStep(step, "completed");
    });
  }
  assistantProgressSteps = previousSteps;
  return savedSteps;
}

function startAssistantProgressTicker() {
  stopAssistantProgressTicker();
  assistantProgressTicker = window.setInterval(() => {
    if (!currentRunStartedAt) {
      stopAssistantProgressTicker();
      return;
    }
    renderActivities();
  }, 900);
}

function stopAssistantProgressTicker() {
  if (!assistantProgressTicker) return;
  window.clearInterval(assistantProgressTicker);
  assistantProgressTicker = null;
}

function stopAssistantActivityTypingTimer() {
  if (!assistantActivityTypingTimer) return;
  window.clearTimeout(assistantActivityTypingTimer);
  assistantActivityTypingTimer = null;
}

function resetAssistantActivityTyping() {
  assistantActivityTypingStates.clear();
  stopAssistantActivityTypingTimer();
}

function appendDebugLog(text, type = "debug") {
  const raw = String(text || "").trim();
  if (!raw) return;
  assistantDebugLogs.push({ type, text: raw, timestamp: nowIso() });
  assistantDebugLogs = assistantDebugLogs.slice(-300);
  renderDebugLog();
}

function renderDebugLog() {
  const log = $("aiAssistantDebugLog");
  if (!log) return;
  log.textContent = assistantDebugLogs
    .map((entry) => `[${entry.timestamp}] ${entry.type}: ${entry.text}`)
    .join("\n");
  log.scrollTop = log.scrollHeight;
}

function appendActivity(text, type = "activity", options = {}) {
  const now = performance.now();
  const elapsedMs = Number.isFinite(options.elapsedMs)
    ? options.elapsedMs
    : (currentStepStartedAt ? now - currentStepStartedAt : 0);
  if (currentRunStartedAt) currentStepStartedAt = now;
  const activity = {
    type,
    text: String(options.displayText || text || "").trim(),
    rawText: String(text || "").trim(),
    elapsedMs: Math.round(Math.max(0, elapsedMs)),
    timestamp: nowIso(),
  };
  if (!activity.text) return;
  assistantActivities.push(activity);
  assistantActivities = assistantActivities.slice(-120);
  updateAssistantProgressFromActivity(activity, { render: false });
  renderActivities();
  if (options.save !== false) saveCurrentSession();
}

function shouldShowAssistantActivity(activity, text) {
  if (["command", "command-output", "commentary", "thinking"].includes(activity?.type)) return !!text;
  const visible = String(text || "").trim();
  if (!visible) return false;
  const raw = String(activity?.rawText || activity?.text || "").trim();
  const lower = `${visible}\n${raw}`.toLowerCase();
  if (String(activity?.type || "").toLowerCase() === "error") return true;
  if (lower.includes("proposed") && lower.includes("update is valid")) return true;
  if (lower.includes("running command:") || lower.includes("codex is running a command")) return true;
  if (lower.includes("reading file:") || lower.includes("editing file:")) return true;
  if (lower.includes("configured server root") || lower.includes("configured server folder") || lower.includes("configured folders")) return true;
  if (lower.includes("checking read/write access")) return true;
  if (lower.includes("temporary editable copy")) return true;
  if (lower.includes("validating the temp copy")) return true;
  if (lower.includes("extracted the edited json")) return true;
  if (lower.includes("active notebook")) return true;
  if (lower.includes("request canceled") || lower.includes("failed") || lower.includes("could not") || lower.includes("error:")) return true;
  return false;
}

function getAssistantActivityItems() {
  const items = [];
  for (const activity of assistantActivities) {
    const text = formatAssistantActivityForCard(activity.rawText || activity.text, activity) || String(activity.text || "").trim();
    if (!shouldShowAssistantActivity(activity, text)) continue;
    const previous = items.at(-1);
    if (previous?.text === text) continue;
    items.push({
      text,
      type: activity.type || "activity",
      elapsedMs: Number.isFinite(activity.elapsedMs) ? Math.max(0, activity.elapsedMs) : 0,
      timestamp: activity.timestamp || "",
    });
  }
  return items;
}

function getAssistantActivityElapsedMs() {
  if (currentRunStartedAt) return Math.max(0, performance.now() - currentRunStartedAt);
  return assistantActivities.reduce((sum, item) => (
    sum + (Number.isFinite(item.elapsedMs) ? Math.max(0, item.elapsedMs) : 0)
  ), 0);
}

function ensureAssistantWorkElement(container, isRunning) {
  const desiredTag = isRunning ? "DIV" : "DETAILS";
  if (!currentWorkCardEl || !currentWorkCardEl.isConnected || currentWorkCardEl.tagName !== desiredTag) {
    currentWorkCardEl?.remove();
    currentWorkCardEl = document.createElement(isRunning ? "div" : "details");
  }
  const pendingRow = currentPendingMessageEl?.closest?.(".aiAssistantMessageRow") || null;
  const assistantRows = [...container.querySelectorAll(".aiAssistantMessageRow.assistant")];
  const anchor = pendingRow || assistantRows.at(-1) || null;
  if (anchor && anchor !== currentWorkCardEl.nextSibling) {
    container.insertBefore(currentWorkCardEl, anchor);
  } else if (!currentWorkCardEl.parentNode) {
    container.appendChild(currentWorkCardEl);
  }
  return currentWorkCardEl;
}

function getAssistantActivityTypingKey(item, index) {
  return `${item.timestamp || index}:${item.type || "activity"}:${item.text}`;
}

function getAssistantActivityTypingState(item, index, enableTyping) {
  if (!enableTyping) return { text: item.text, isTyping: false };
  const key = getAssistantActivityTypingKey(item, index);
  let state = assistantActivityTypingStates.get(key);
  if (!state) {
    state = { text: item.text, visibleChars: 0 };
    assistantActivityTypingStates.set(key, state);
  } else if (state.text !== item.text) {
    state.text = item.text;
    state.visibleChars = Math.min(state.visibleChars, item.text.length);
  }
  const visibleChars = Math.min(state.visibleChars, state.text.length);
  return {
    text: state.text.slice(0, visibleChars),
    isTyping: visibleChars < state.text.length,
    key,
  };
}

function scheduleAssistantActivityTyping(keysInUse) {
  if (!currentRunStartedAt) {
    resetAssistantActivityTyping();
    return;
  }
  for (const key of assistantActivityTypingStates.keys()) {
    if (!keysInUse.has(key)) assistantActivityTypingStates.delete(key);
  }
  const hasPending = [...assistantActivityTypingStates.values()].some((state) => (
    state.visibleChars < state.text.length
  ));
  if (!hasPending || assistantActivityTypingTimer) return;
  assistantActivityTypingTimer = window.setTimeout(() => {
    assistantActivityTypingTimer = null;
    for (const state of assistantActivityTypingStates.values()) {
      if (state.visibleChars < state.text.length) {
        state.visibleChars = Math.min(
          state.text.length,
          state.visibleChars + ASSISTANT_WORK_TYPING_CHARS_PER_FRAME,
        );
      }
    }
    renderActivities();
  }, ASSISTANT_WORK_TYPING_FRAME_MS);
}

// One collapsed line per command; the full command and output open on click.
// An ArcBot tool call reads in plain words; a shell command shows its first line.
function getAssistantCommandHeadline(text) {
  const toolLabel = getAssistantToolLabel(text);
  if (toolLabel) return toolLabel;
  const first = String(text || "").split(/\r?\n/).map(line => line.trim()).find(Boolean) || "";
  return first.replace(/^"?[^"\s]*powershell(?:\.exe)?"?\s+(?:-\w+\s+)*?-Command\s+/i, "");
}

function createAssistantCommandStep(item, index) {
  const key = `${item.timestamp || ""}:${index}`;
  const step = document.createElement("details");
  step.className = "aiAssistantCommandStep";
  const exit = /\nExit:\s*(-?\d+)/.exec(item.text);
  if (exit && exit[1] !== "0") step.classList.add("failed");
  step.open = assistantOpenCommandKeys.has(key);
  step.ontoggle = () => {
    if (step.open) assistantOpenCommandKeys.add(key);
    else assistantOpenCommandKeys.delete(key);
  };
  const summary = document.createElement("summary");
  const headline = document.createElement("span");
  headline.className = "aiAssistantCommandHeadline";
  headline.textContent = getAssistantCommandHeadline(item.text);
  if (getAssistantToolLabel(item.text)) step.classList.add("tool");
  summary.appendChild(headline);
  const output = document.createElement("pre");
  output.className = "aiAssistantCommandOutput";
  output.textContent = String(item.text || "").replace(/^\s+/, "");
  step.append(summary, output);
  return step;
}

function createAssistantActivityList(items, options = {}) {
  const list = document.createElement("ul");
  list.className = "aiAssistantWorkList";
  const typingKeys = new Set();
  const enableTyping = !!options.typing;
  items.forEach((item, index) => {
    const isCommand = item.type === "command" || item.type === "command-output";
    // A thinking summary already arrives piece by piece; typing it out again would restart on every piece.
    const typingState = getAssistantActivityTypingState(item, index, enableTyping && !isCommand && item.type !== "thinking");
    if (typingState.key) typingKeys.add(typingState.key);
    const bullet = document.createElement("li");
    bullet.className = [
      item.type === "error" ? "error" : "",
      typingState.isTyping ? "typing" : "",
    ].filter(Boolean).join(" ");
    bullet.setAttribute("aria-label", item.text);
    if (item.type === "thinking") bullet.classList.add("thinking");
    if (isCommand) {
      bullet.classList.add("command");
      bullet.appendChild(createAssistantCommandStep(item, index));
    } else if (typingState.isTyping && !typingState.text) {
      bullet.appendChild(document.createTextNode("\u00a0"));
    } else if (typingState.isTyping) {
      bullet.appendChild(document.createTextNode(typingState.text));
    } else {
      appendAssistantInlineMarkdown(bullet, item.text);
    }
    list.appendChild(bullet);
  });
  if (enableTyping) scheduleAssistantActivityTyping(typingKeys);
  return list;
}

function renderActivities() {
  const legacyPanel = $("aiAssistantActivity");
  if (legacyPanel) legacyPanel.classList.remove("open");
  const container = $("aiAssistantMessages");
  if (!container) return;
  const isRunning = !!currentRunStartedAt;
  const activityItems = getAssistantActivityItems();
  if (!activityItems.length && !isRunning) {
    currentWorkCardEl?.remove();
    currentWorkCardEl = null;
    resetAssistantActivityTyping();
    return;
  }
  if (!isRunning) resetAssistantActivityTyping();
  const totalMs = getAssistantActivityElapsedMs();
  const workEl = ensureAssistantWorkElement(container, isRunning);
  workEl.textContent = "";
  if (isRunning) {
    workEl.className = "aiAssistantWorkLog running";
    workEl.appendChild(createAssistantActivityList(activityItems, { typing: true }));
  } else {
    const hasError = activityItems.some((item) => item.type === "error" || (item.type === "activity" && /failed|could not|error|canceled/i.test(item.text)));
    workEl.className = `aiAssistantWorkArchive${hasError ? " failed" : ""}`;
    workEl.open = assistantWorkCardExpanded;
    const summary = document.createElement("summary");
    workEl.ontoggle = () => {
      assistantWorkCardExpanded = workEl.open;
      if (workEl.open) {
        window.requestAnimationFrame(() => {
          scrollMessagesToBottom();
        });
      }
    };
    const title = document.createElement("span");
    title.className = "aiAssistantWorkArchiveTitle";
    title.textContent = hasError ? `Stopped after ${formatWorkDuration(totalMs)}` : `Worked for ${formatWorkDuration(totalMs)}`;
    const meta = document.createElement("span");
    meta.className = "aiAssistantWorkArchiveMeta";
    meta.textContent = `${activityItems.length} update${activityItems.length === 1 ? "" : "s"}`;
    summary.append(title, meta);
    workEl.appendChild(summary);
    const body = document.createElement("div");
    body.className = "aiAssistantWorkArchiveBody";
    body.appendChild(createAssistantActivityList(activityItems));
    workEl.appendChild(body);
  }
  scrollMessagesToBottom();
}

function updateContextPanel() {
  updateAssistantSettingsPanel();
  const panel = $("aiAssistantContextPanel");
  if (!panel) return;
  const context = currentContext || {};
  const usage = currentUsage || {};
  const rows = [
    ["Session", currentSessionTitle || currentSessionId || "New ArcBot Chat"],
    ["Account", formatAssistantAccount()],
    ["Tab", context.title || context.tabType || "No active tab context"],
    ["Type", context.tabType || "home"],
    ["File", context.targetPath || context.path || "No active JSON-backed file"],
    ["Context Window", formatContextWindowUsage(usage)],
    ["Prompt Size", usage.promptChars ? `${Number(usage.promptChars).toLocaleString()} chars, ~${formatTokenCount(usage.estimatedTokens)} tokens` : "Not measured yet"],
    ["Included", usage.includedMessages != null ? `${usage.includedMessages} messages${usage.truncated ? ", truncated" : ""}` : "Not measured yet"],
  ];
  panel.textContent = "";
  if (usage.contextWindowTokens && usage.estimatedTokens) {
    const meter = document.createElement("div");
    meter.className = "aiAssistantContextMeter";
    const meterFill = document.createElement("div");
    meterFill.className = "aiAssistantContextMeterFill";
    meterFill.style.width = `${Math.min(100, Math.max(0, getUsagePercent(usage)))}%`;
    meter.appendChild(meterFill);
    const meterText = document.createElement("div");
    meterText.className = "aiAssistantContextMeterText";
    meterText.textContent = `Estimated context used: ${formatContextPercent(getUsagePercent(usage))}`;
    panel.append(meter, meterText);
  }
  const grid = document.createElement("div");
  grid.className = "aiAssistantContextGrid";
  for (const [label, value] of rows) {
    const labelEl = document.createElement("div");
    labelEl.className = "aiAssistantContextLabel";
    labelEl.textContent = label;
    const valueEl = document.createElement("div");
    valueEl.className = "aiAssistantContextValue";
    valueEl.title = String(value);
    valueEl.textContent = String(value);
    grid.append(labelEl, valueEl);
  }
  panel.appendChild(grid);
}

async function refreshAssistantModels(options = {}) {
  const host = getHostApi();
  if (!host?.codexAssistantModels) return false;
  if (assistantModelCatalogRequest && options.refresh !== true) return assistantModelCatalogRequest;
  const request = (async () => {
    try {
      const result = await host.codexAssistantModels({ refresh: options.refresh === true });
      if (!result?.ok || !Array.isArray(result.models)) {
        throw new Error(result?.error || "Codex did not return a model catalog.");
      }
      const previousModel = assistantModel;
      applyAssistantModelCatalog(result);
      assistantModelCatalogChecked = true;
      assistantModelDefaultVerified = (
        result.verified === true
        && result.upgradeRequired !== true
        && result.meetsMinimum === true
      );
      const shouldPromoteEmptyDefault = (
        options.promoteEmptyDefault === true
        && assistantModelDefaultVerified
        && previousModel === "codex"
        && assistantMessages.length === 0
      );
      const nextModel = shouldPromoteEmptyDefault ? getDefaultAssistantModel() : previousModel;
      setAssistantModel(nextModel, {
        save: shouldPromoteEmptyDefault && !!currentSessionId,
        refreshStatus: false,
        defaultEffort: shouldPromoteEmptyDefault,
      });
      if (result.warning) appendDebugLog(`Model discovery fallback: ${result.warning}`, "debug");
      return true;
    } catch (err) {
      assistantModelDefaultVerified = false;
      appendDebugLog(`Model discovery failed: ${String(err?.message || err)}`, "debug");
      return false;
    }
  })();
  assistantModelCatalogRequest = request;
  try {
    return await request;
  } finally {
    if (assistantModelCatalogRequest === request) assistantModelCatalogRequest = null;
  }
}

function setAssistantModel(model, options = {}) {
  const prevClaude = isClaudeModel();
  assistantModel = accountModel(model);
  void prepareAssistantSession();
  // A promoted default or a switch between OpenAI and Claude starts at the default effort.
  assistantReasoningEffort = options.defaultEffort === true || prevClaude !== isClaudeModel()
    ? getDefaultAssistantReasoningEffort(assistantModel)
    : reconcileAssistantReasoningEffort(assistantModel, assistantReasoningEffort);
  renderAssistantModelOptions();
  renderAssistantReasoningOptions();
  updateAssistantSettingsPanel();
  if (options.save !== false) saveCurrentSession();
  if (options.refreshStatus !== false && prevClaude !== isClaudeModel() && assistantStatusChecked) {
    refreshAssistantStatus();
  } else if (assistantReady) {
    setStatus(`${isClaudeModel() ? getAssistantModelLabel() : "Codex"} ready. ${getModeLabel()}.`);
  }
}

function setAssistantReasoningEffort(effort, options = {}) {
  assistantReasoningEffort = reconcileAssistantReasoningEffort(
    assistantModel,
    normalizeAssistantReasoningEffort(effort),
  );
  const select = $("aiAssistantSettingsReasoningSelect");
  if (select) select.value = assistantReasoningEffort;
  updateAssistantSettingsPanel();
  if (options.save !== false) saveCurrentSession();
}

function setFolderPermissionsStatus(text) {
  const el = $("aiAssistantFolderStatus");
  if (el) {
    el.textContent = text || "";
    el.title = text || "";
  }
}

function renderFolderPermissionsList() {
  const list = $("aiAssistantFolderPermissionsList");
  if (!list) return;
  list.textContent = "";
  if (!assistantReadableRoots.length) {
    const empty = document.createElement("div");
    empty.className = "aiAssistantFolderEmpty";
    empty.textContent = "No extra folders added.";
    list.appendChild(empty);
  } else {
    assistantReadableRoots.forEach((folder, index) => {
      const row = document.createElement("div");
      row.className = "aiAssistantFolderRow";
      const icon = document.createElement("span");
      icon.className = "aiAssistantFolderIcon";
      icon.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M3 6.5h6l2 2h10v9a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2z"></path>
        </svg>
      `;
      const pathEl = document.createElement("div");
      pathEl.className = "aiAssistantFolderPath";
      pathEl.textContent = folder;
      pathEl.title = folder;
      const removeBtn = document.createElement("button");
      removeBtn.className = "aiAssistantFolderRemoveBtn";
      removeBtn.type = "button";
      removeBtn.title = "Remove";
      removeBtn.setAttribute("aria-label", `Remove ${folder}`);
      removeBtn.innerHTML = `
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 6l12 12"></path>
          <path d="M18 6L6 18"></path>
        </svg>
      `;
      removeBtn.addEventListener("click", () => removeAssistantReadableRoot(index));
      row.append(icon, pathEl, removeBtn);
      list.appendChild(row);
    });
  }
  const countText = assistantReadableRoots.length
    ? `${assistantReadableRoots.length} extra folder${assistantReadableRoots.length === 1 ? "" : "s"} allowed.`
    : "Project data is read through the server.";
  setFolderPermissionsStatus(countText);
  updateAssistantSettingsPanel();
}

async function loadAssistantReadableRoots() {
  const host = getHostApi();
  if (!host?.codexAssistantLoadReadableRoots) {
    assistantReadableRoots = [];
    renderFolderPermissionsList();
    return;
  }
  try {
    const result = await host.codexAssistantLoadReadableRoots();
    assistantReadableRoots = normalizeReadableRootList(result?.folders || []);
    renderFolderPermissionsList();
  } catch {
    assistantReadableRoots = [];
    renderFolderPermissionsList();
  }
}

async function saveAssistantReadableRoots(nextFolders) {
  const host = getHostApi();
  const normalized = normalizeReadableRootList(nextFolders);
  if (!host?.codexAssistantSaveReadableRoots) {
    assistantReadableRoots = normalized;
    renderFolderPermissionsList();
    setFolderPermissionsStatus("Folder permissions are available in the desktop app only.");
    return false;
  }
  try {
    const result = await host.codexAssistantSaveReadableRoots(normalized);
    if (!result?.ok) throw new Error(result?.error || "Could not save folder permissions.");
    assistantReadableRoots = normalizeReadableRootList(result.folders || []);
    renderFolderPermissionsList();
    return true;
  } catch (err) {
    setFolderPermissionsStatus(String(err?.message || err || "Could not save folder permissions."));
    return false;
  }
}

function openFolderPermissionsPage() {
  closeAssistantSettingsPanel();
  $("aiAssistantDebugPanel")?.classList.remove("open");
  $("aiAssistantDebugBtn")?.setAttribute("aria-expanded", "false");
  $("aiAssistantFolderPermissionsPage")?.classList.add("open");
  renderFolderPermissionsList();
}

function closeFolderPermissionsPage() {
  $("aiAssistantFolderPermissionsPage")?.classList.remove("open");
}

async function addAssistantReadableRoot() {
  const host = getHostApi();
  if (!host?.pickFolder) {
    setFolderPermissionsStatus("Folder picker is available in the desktop app only.");
    return;
  }
  const startDir = assistantReadableRoots[assistantReadableRoots.length - 1] || "";
  const folder = await host.pickFolder(startDir);
  if (!folder) return;
  await saveAssistantReadableRoots([...assistantReadableRoots, folder]);
}

async function removeAssistantReadableRoot(index) {
  const next = assistantReadableRoots.filter((_folder, folderIndex) => folderIndex !== index);
  await saveAssistantReadableRoots(next);
}

async function openAssistantPromptGuide() {
  if (!shell?.openAgentGuideTab) {
    setStatus("ArcBot prompt guide is not available.", "error");
    return;
  }
  closeAssistantSettingsPanel();
  shell.openAgentGuideTab();
  setStatus("Opened ArcBot prompt guide.");
}

function updateAssistantSettingsPanel() {
  updateTokenUsageRing();
  const panel = $("aiAssistantSettingsPanel");
  if (!panel) return;
  const modelSelect = $("aiAssistantSettingsModelSelect");
  const reasoningSelect = $("aiAssistantSettingsReasoningSelect");
  const reasoningField = $("aiAssistantSettingsReasoningField");
  const reasoningLabel = $("aiAssistantSettingsReasoningLabel");
  const hasReasoning = assistantModelHasReasoning();
  const isClaudeProvider = isClaudeModel();
  if (modelSelect) {
    modelSelect.value = assistantModel;
    modelSelect.disabled = assistantBusy;
    syncAssistantSelectMenu(modelSelect);
  }
  if (reasoningSelect) {
    reasoningSelect.value = assistantReasoningEffort;
    reasoningSelect.disabled = assistantBusy;
    syncAssistantSelectMenu(reasoningSelect);
  }
  if (reasoningField) reasoningField.style.display = hasReasoning ? "" : "none";
  if (reasoningLabel) reasoningLabel.textContent = isClaudeProvider ? "Thinking" : "Reasoning";
  panel.querySelectorAll(".aiAssistantReasoningDetail").forEach((el) => {
    el.style.display = hasReasoning ? "" : "none";
  });
  $("aiAssistantTokenAlert")?.classList.toggle("visible", shouldShowAssistantTokenAlert());
  const rows = [
    ["session", currentSessionTitle || currentSessionId || "New ArcBot Chat"],
    ["model", getAssistantModelLabel()],
    ["reasoning", hasReasoning ? getAssistantReasoningLabel() : "—"],
    ["folders", assistantReadableRoots.length ? `${assistantReadableRoots.length} extra` : "None"],
    ["tokens", formatContextWindowUsage(currentUsage || {})],
    ["status", assistantReady ? "Online" : "Offline"],
    ["login", formatAssistantAccount()],
  ];
  for (const [key, value] of rows) {
    const node = panel.querySelector(`[data-ai-settings-detail="${key}"]`);
    if (node) {
      node.textContent = String(value);
      node.title = String(value);
    }
  }
}

function closeAssistantSettingsPanel() {
  assistantAccounts?.close();
  $("aiAssistantSettingsPanel")?.classList.remove("open");
  $("aiAssistantSettingsBtn")?.setAttribute("aria-expanded", "false");
}

function toggleAssistantSettingsPanel(forceOpen) {
  const panel = $("aiAssistantSettingsPanel");
  const button = $("aiAssistantSettingsBtn");
  if (!panel || !button) return;
  const open = forceOpen == null ? !panel.classList.contains("open") : !!forceOpen;
  panel.classList.toggle("open", open);
  button.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) {
    $("aiAssistantDebugPanel")?.classList.remove("open");
    $("aiAssistantDebugBtn")?.setAttribute("aria-expanded", "false");
    updateAssistantSettingsPanel();
    // Cheap while the host's discovered lists are fresh; picks up new models once they age out.
    void refreshAssistantModels();
    void assistantAccounts?.refresh();
  } else {
    assistantAccounts?.close();
  }
}

// The host has already restarted what held the old sign-in; re-read what the new account can do.
async function handleAssistantAccountChange() {
  if (assistantBusy) return;
  await refreshAssistantModels();
  await refreshAssistantStatus();
}

function renderAssistantAttachments() {
  const list = $("aiAssistantAttachmentList");
  if (!list) return;
  list.textContent = "";
  list.classList.toggle("open", assistantAttachments.length > 0);
  assistantAttachments.forEach((attachment, index) => {
    const chip = document.createElement("div");
    chip.className = "aiAssistantAttachmentChip";
    chip.title = attachment.path || attachment.name || "Attached file";
    const icon = document.createElement("span");
    const kind = getAttachmentIconKind(attachment.name || attachment.path || "");
    icon.className = `aiAssistantAttachmentIcon type-${kind}`;
    icon.innerHTML = getAttachmentIconSvg(kind);
    const textWrap = document.createElement("span");
    textWrap.className = "aiAssistantAttachmentText";
    const name = document.createElement("span");
    name.className = "aiAssistantAttachmentName";
    name.textContent = attachment.name || "Attached file";
    const type = document.createElement("span");
    type.className = "aiAssistantAttachmentType";
    type.textContent = getAttachmentTypeLabel(attachment.name || attachment.path || "");
    textWrap.append(name, type);
    const remove = document.createElement("button");
    remove.className = "aiAssistantAttachmentRemove";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${attachment.name || "attachment"}`);
    remove.textContent = "x";
    remove.addEventListener("click", () => {
      assistantAttachments.splice(index, 1);
      renderAssistantAttachments();
    });
    chip.append(icon, textWrap, remove);
    list.appendChild(chip);
  });
}

function closeAttachMenu() {
  $("aiAssistantAttachMenu")?.classList.remove("open");
  $("aiAssistantAttachBtn")?.setAttribute("aria-expanded", "false");
}

function toggleAttachMenu() {
  const menu = $("aiAssistantAttachMenu");
  const button = $("aiAssistantAttachBtn");
  const open = !menu?.classList.contains("open");
  menu?.classList.toggle("open", open);
  button?.setAttribute("aria-expanded", open ? "true" : "false");
}

async function attachAssistantContextFile() {
  closeAttachMenu();
  const host = getHostApi();
  if (!host?.pickOpenFile || !host?.readTextFile) {
    setStatus("File attachments are available in the desktop app only.", "error");
    return;
  }
  if (assistantAttachments.length >= 5) {
    setStatus("ArcBot can attach up to 5 files per request.", "error");
    return;
  }
  try {
    const filePath = await host.pickOpenFile({
      filters: [
        { name: "Context Files", extensions: ASSISTANT_ATTACHMENT_EXTENSIONS },
        { name: "All Files", extensions: ["*"] },
      ],
    });
    if (!filePath) return;
    if (assistantAttachments.some((item) => item.path === filePath)) {
      setStatus("That file is already attached.");
      return;
    }
    const result = await host.readTextFile({ path: filePath, maxBytes: 200000 });
    if (!result?.ok) {
      setStatus(result?.error || "Could not attach that file.", "error");
      return;
    }
    assistantAttachments.push({
      name: result.name || filePath.split(/[\\/]/).pop() || "attachment",
      path: result.path || filePath,
      size: Number(result.size || 0),
      text: String(result.text || ""),
    });
    renderAssistantAttachments();
    setStatus(`Attached ${result.name || "file"} as ArcBot context.`);
  } catch (err) {
    setStatus(String(err?.message || err || "Could not attach file."), "error");
  }
}

function getActiveTabPreviewContext() {
  const activeTab = shell.state?.tabs?.find?.((tab) => tab.id === shell.state.activeId) || null;
  return {
    available: !!activeTab && activeTab.type !== "home",
    tabId: activeTab?.id || "",
    tabType: activeTab?.type || "home",
    title: activeTab?.title || "Home",
    targetPath: "",
    fileState: "",
  };
}

function getAppContextTooltipRows(context) {
  if (!assistantAppContextEnabled) {
    return [
      { text: "App Context Off", strong: true },
      { text: "ArcBot will not receive active page, tab, file, or notebook contents." },
    ];
  }
  const ctx = context && typeof context === "object" ? context : getActiveTabPreviewContext();
  const title = String(ctx.title || "Home");
  const type = String(ctx.tabType || ctx.pageType || "home");
  const path = String(ctx.targetPath || ctx.path || "").trim();
  const state = String(ctx.fileState || (ctx.dirty ? "unsaved-changes" : "") || "").trim();
  if (typeof assistantConfig.getAppContextTooltipRows === "function") {
    const rows = assistantConfig.getAppContextTooltipRows(ctx, { title, type, path, state });
    if (Array.isArray(rows) && rows.length) return rows.filter(Boolean);
  }
  return [
    { text: "App Context", strong: true },
    { label: "Tab", value: `${title} (${type})` },
    { label: "File", value: path || "no active file" },
    state ? { label: "State", value: state } : null,
  ].filter(Boolean);
}

function formatAppContextTooltip(context) {
  return getAppContextTooltipRows(context).map((row) => (
    row.text || `${row.label}: ${row.value}`
  )).join("\n");
}

function renderAppContextTooltip(tooltip, context) {
  if (!tooltip) return;
  const rows = getAppContextTooltipRows(context);
  tooltip.textContent = "";
  tooltip.setAttribute("aria-label", rows.map((row) => row.text || `${row.label}: ${row.value}`).join("\n"));
  rows.forEach((row) => {
    const line = document.createElement("div");
    line.className = "aiAssistantAppContextTooltipLine";
    if (row.text) {
      line.textContent = row.text;
      if (row.strong) line.classList.add("aiAssistantAppContextTooltipTitle");
    } else {
      const label = document.createElement("span");
      label.className = "aiAssistantAppContextTooltipLabel";
      label.textContent = `${row.label}: `;
      const value = document.createElement("span");
      value.className = "aiAssistantAppContextTooltipValue";
      value.textContent = row.value;
      line.append(label, value);
    }
    tooltip.appendChild(line);
  });
}

async function refreshAppContextTooltip({ probe = false } = {}) {
  const tooltip = $("aiAssistantAppContextTooltip");
  const button = $("aiAssistantAppContextBtn");
  if (!tooltip && !button) return;
  let context = getActiveTabPreviewContext();
  if (probe && assistantAppContextEnabled) {
    try {
      context = await requestActivePageContext();
    } catch {
      // Keep shell-level preview when iframe context is unavailable.
    }
  }
  renderAppContextTooltip(tooltip, context);
  button?.removeAttribute("title");
}

function setAssistantContextPanelOpen(open) {
  const panel = $("aiAssistantContextPanel");
  panel?.classList.toggle("open", !!open);
  updateContextPanel();
}

function setAssistantAppContextEnabled(enabled) {
  assistantAppContextEnabled = !!enabled;
  const button = $("aiAssistantAppContextBtn");
  button?.classList.toggle("active", assistantAppContextEnabled);
  button?.setAttribute("aria-pressed", assistantAppContextEnabled ? "true" : "false");
  button?.setAttribute("aria-label", assistantAppContextEnabled ? "App Context on" : "App Context off");
  if (!assistantAppContextEnabled) {
    currentContext = {
      available: false,
      tabType: "off",
      title: "App Context Off",
      targetPath: "",
      fileState: "disabled",
    };
    setAssistantContextPanelOpen(false);
  }
  updateContextPanel();
  refreshAppContextTooltip({ probe: assistantAppContextEnabled });
}

function updateSessionSelectLabel() {
  updateContextPanel();
}

async function refreshSessionList(selectedId = currentSessionId) {
  const host = getHostApi();
  if (!host?.codexAssistantListSessions) return [];
  try {
    const result = await host.codexAssistantListSessions({ includeArchived: false });
    const sessions = result?.ok && Array.isArray(result.sessions) ? result.sessions : [];
    latestSessionList = sessions;
    return sessions;
  } catch {
    return [];
  }
}

async function loadAssistantSession(sessionId) {
  if (assistantBusy) return false;
  assistantVoice?.stop();
  const host = getHostApi();
  if (!host?.codexAssistantLoadSession || !sessionId) return false;
  const result = await host.codexAssistantLoadSession(sessionId);
  if (!result?.ok || !result.session) return false;
  const session = result.session;
  currentSessionId = session.id || "";
  currentSessionTitle = session.title || "ArcBot Chat";
  assistantMode = normalizeAssistantMode(session.mode);
  assistantModel = accountModel(session.model);
  assistantReasoningEffort = reconcileAssistantReasoningEffort(
    assistantModel,
    normalizeAssistantReasoningEffort(session.reasoningEffort),
  );
  assistantMessages = normalizeMessages(session.messages);
  assistantActivities = normalizeActivities(session.activities);
  resetAssistantActivityTyping();
  assistantDebugLogs = normalizeDebugLogs(session.debugLogs);
  currentContext = session.context || null;
  currentUsage = session.usage || null;
  setAssistantMode(assistantMode, { save: false });
  renderAssistantModelOptions();
  renderAssistantReasoningOptions();
  renderMessages();
  renderActivities();
  updateAssistantSettingsPanel();
  renderDebugLog();
  await refreshSessionList(currentSessionId);
  updateSessionSelectLabel();
  void prepareAssistantSession();
  return true;
}

async function createAssistantSession() {
  if (assistantBusy && currentSessionId) return false;
  assistantVoice?.stop();
  const host = getHostApi();
  if (!host?.codexAssistantCreateSession) return false;
  // A new chat starts on the verified default model and effort; until discovery verifies one, it keeps the current pick.
  const model = accountModel(assistantModelDefaultVerified ? getDefaultAssistantModel() : assistantModel);
  const result = await host.codexAssistantCreateSession({
    mode: assistantMode,
    model,
    reasoningEffort: assistantModelDefaultVerified ? getDefaultAssistantReasoningEffort(model) : assistantReasoningEffort,
  });
  if (!result?.ok || !result.session) return false;
  currentSessionId = result.session.id;
  currentSessionTitle = result.session.title || "New ArcBot Chat";
  assistantModel = accountModel(result.session.model);
  assistantReasoningEffort = reconcileAssistantReasoningEffort(
    assistantModel,
    normalizeAssistantReasoningEffort(result.session.reasoningEffort),
  );
  assistantMessages = [];
  assistantActivities = [];
  resetAssistantActivityTyping();
  assistantDebugLogs = [];
  currentContext = null;
  currentUsage = null;
  refreshAppContextTooltip();
  renderAssistantModelOptions();
  renderAssistantReasoningOptions();
  renderMessages();
  renderActivities();
  updateAssistantSettingsPanel();
  renderDebugLog();
  await refreshSessionList(currentSessionId);
  updateSessionSelectLabel();
  void prepareAssistantSession();
  return true;
}

function findEmptyAssistantSession(sessions) {
  return (Array.isArray(sessions) ? sessions : []).find((session) => (
    session?.id &&
    session.archived !== true &&
    Number(session.messageCount || 0) === 0
  )) || null;
}

async function openOrCreateEmptyAssistantSession() {
  if (assistantBusy) {
    setStatus("Finish or cancel the current request before changing chats.");
    return { ok: false };
  }
  const sessions = await refreshSessionList(currentSessionId);
  const emptySession = findEmptyAssistantSession(sessions);
  if (emptySession) {
    if (emptySession.id !== currentSessionId) {
      await loadAssistantSession(emptySession.id);
      return { ok: true, created: false, alreadyCurrent: false };
    }
    renderMessages();
    renderActivities();
    updateSessionSelectLabel();
    return { ok: true, created: false, alreadyCurrent: true };
  }
  const created = await createAssistantSession();
  return { ok: created, created: true, alreadyCurrent: false };
}

async function ensureAssistantSession() {
  const sessions = await refreshSessionList();
  if (sessions.length && await loadAssistantSession(sessions[0].id)) return;
  await createAssistantSession();
}

function formatSessionDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function getAssistantHistoryIcon(action) {
  if (action === "archive") {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M6 7v12h12V7"></path><path d="M9 11h6"></path></svg>';
  }
  if (action === "restore") {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M6 7v12h12V7"></path><path d="M12 16V10"></path><path d="M9 13l3-3 3 3"></path></svg>';
  }
  if (action === "delete") {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14"></path><path d="M9 7V5h6v2"></path><path d="M8 10l1 9h6l1-9"></path><path d="M10.5 12.5v4"></path><path d="M13.5 12.5v4"></path></svg>';
  }
  return "";
}

function createAssistantHistoryIconButton(action, label, onClick) {
  const button = document.createElement("button");
  button.className = `aiAssistantHistoryIconBtn${action === "delete" ? " danger" : ""}`;
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.innerHTML = getAssistantHistoryIcon(action);
  button.addEventListener("click", onClick);
  return button;
}

async function refreshHistoryPage() {
  const host = getHostApi();
  const list = $("aiAssistantHistoryList");
  if (!host?.codexAssistantListSessions || !list) return;
  list.textContent = "";
  const result = await host.codexAssistantListSessions({ includeArchived: true });
  const sessions = result?.ok && Array.isArray(result.sessions) ? result.sessions : [];
  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "aiAssistantHistoryEmpty";
    empty.textContent = "No chat sessions yet.";
    list.appendChild(empty);
    return;
  }
  for (const session of sessions) {
    const row = document.createElement("div");
    row.className = `aiAssistantHistoryRow${session.archived ? " archived" : ""}`;
    const info = document.createElement("div");
    info.className = "aiAssistantHistoryInfo";
    info.tabIndex = 0;
    info.setAttribute("role", "button");
    info.setAttribute("aria-label", `Open ${session.title || "ArcBot Chat"}`);
    const name = document.createElement("div");
    name.className = "aiAssistantHistoryName";
    name.textContent = session.title || "ArcBot Chat";
    name.title = session.title || "ArcBot Chat";
    const meta = document.createElement("div");
    meta.className = "aiAssistantHistoryMeta";
    const updated = formatSessionDate(session.updatedAt);
    meta.textContent = `${session.messageCount || 0} messages${updated ? ` - ${updated}` : ""}${session.archived ? " - Archived" : ""}`;
    info.append(name, meta);
    const openSession = async () => {
      if (assistantBusy) { setStatus("Finish or cancel the current request before changing chats."); return; }
      if (session.archived && host.codexAssistantArchiveSession) {
        await host.codexAssistantArchiveSession(session.id, false);
      }
      await loadAssistantSession(session.id);
      await closeHistoryPage();
    };
    info.addEventListener("click", openSession);
    info.addEventListener("keydown", async (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      await openSession();
    });

    const actions = document.createElement("div");
    actions.className = "aiAssistantHistoryActions";
    const archiveBtn = createAssistantHistoryIconButton(session.archived ? "restore" : "archive", session.archived ? "Restore chat" : "Archive chat", async () => {
      if (assistantBusy) return;
      if (!host.codexAssistantArchiveSession) return;
      await host.codexAssistantArchiveSession(session.id, !session.archived);
      if (session.id === currentSessionId && !session.archived) {
        await createAssistantSession();
      }
      await refreshSessionList(currentSessionId);
      await refreshHistoryPage();
    });
    const deleteBtn = createAssistantHistoryIconButton("delete", "Delete chat", async () => {
      if (assistantBusy) return;
      if (!host.codexAssistantDeleteSession) return;
      const confirmed = window.confirm(`Delete this ArcBot chat session?\n\n${session.title || "ArcBot Chat"}`);
      if (!confirmed) return;
      await host.codexAssistantDeleteSession(session.id);
      if (session.id === currentSessionId) {
        await createAssistantSession();
      }
      await refreshSessionList(currentSessionId);
      await refreshHistoryPage();
    });
    actions.append(archiveBtn, deleteBtn);
    row.append(info, actions);
    list.appendChild(row);
  }
}

async function openHistoryPage() {
  const panel = $("aiAssistantPanel");
  closeAssistantSettingsPanel();
  panel?.classList.add("history-open");
  $("aiAssistantHistoryPage")?.classList.add("open");
  $("aiAssistantHistoryBtn")?.setAttribute("aria-expanded", "true");
  await refreshHistoryPage();
}

async function closeHistoryPage() {
  const panel = $("aiAssistantPanel");
  panel?.classList.remove("history-open");
  $("aiAssistantHistoryPage")?.classList.remove("open");
  $("aiAssistantHistoryBtn")?.setAttribute("aria-expanded", "false");
  await refreshSessionList(currentSessionId);
}

function readAssistantLauncherVisibleFallback() {
  try {
    return localStorage.getItem(ASSISTANT_LAUNCHER_VISIBLE_KEY) !== "0";
  } catch {
    return true;
  }
}

function persistAssistantLauncherVisibleFallback(show) {
  try {
    localStorage.setItem(ASSISTANT_LAUNCHER_VISIBLE_KEY, show ? "1" : "0");
  } catch {}
}

function getAssistantUiSettingsPayload() {
  const prefix = String(assistantConfig.storagePrefix || assistantConfig.messageNamespace || "arcode").trim() || "arcode";
  return {
    launcherVisibleByApp: {
      [prefix]: assistantLauncherVisible,
    },
  };
}

async function loadAssistantUiSettings() {
  const host = getHostApi();
  if (!host?.codexAssistantLoadUiSettings) {
    setAiAssistantLauncherVisible(readAssistantLauncherVisibleFallback(), { save: false });
    return;
  }
  try {
    const result = await host.codexAssistantLoadUiSettings();
    const settings = result?.settings && typeof result.settings === "object" ? result.settings : {};
    const visibleByApp = settings.launcherVisibleByApp && typeof settings.launcherVisibleByApp === "object"
      ? settings.launcherVisibleByApp
      : {};
    const prefix = String(assistantConfig.storagePrefix || assistantConfig.messageNamespace || "arcode").trim() || "arcode";
    const savedValue = visibleByApp[prefix];
    setAiAssistantLauncherVisible(typeof savedValue === "boolean" ? savedValue : readAssistantLauncherVisibleFallback(), { save: false });
  } catch {
    setAiAssistantLauncherVisible(readAssistantLauncherVisibleFallback(), { save: false });
  }
}

async function saveAssistantUiSettings() {
  const host = getHostApi();
  if (!host?.codexAssistantSaveUiSettings) return;
  try {
    await host.codexAssistantSaveUiSettings(getAssistantUiSettingsPayload());
  } catch {
    // Launcher visibility still falls back to localStorage if host JSON persistence fails.
  }
}

export function isAiAssistantLauncherVisible() {
  return assistantLauncherVisible;
}

export function setAiAssistantLauncherVisible(visible, options = {}) {
  const show = !!visible;
  assistantLauncherVisible = show;
  persistAssistantLauncherVisibleFallback(show);
  const launcher = $("aiAssistantLauncher");
  const panel = $("aiAssistantPanel");
  if (launcher) launcher.style.display = show ? "" : "none";
  if (show && launcher) applyLauncherPosition(launcher, loadLauncherPosition(launcher));
  if (!show) {
    launcher?.classList.remove("assistant-open");
    panel?.classList.remove("open");
  } else if (panel?.classList.contains("open")) {
    launcher?.classList.add("assistant-open");
  }
  shell.updateViewMenuState?.();
  if (options.save !== false) void saveAssistantUiSettings();
  return show;
}

export function toggleAiAssistantLauncherVisible() {
  return setAiAssistantLauncherVisible(!isAiAssistantLauncherVisible());
}

function ensureAssistantLauncherContextMenu() {
  let menu = $("aiAssistantLauncherContextMenu");
  if (menu) return menu;
  menu = document.createElement("div");
  menu.id = "aiAssistantLauncherContextMenu";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", "ArcBot launcher menu");

  const hideBtn = document.createElement("button");
  hideBtn.id = "aiAssistantLauncherHideBtn";
  hideBtn.type = "button";
  hideBtn.setAttribute("role", "menuitem");
  hideBtn.textContent = "Hide";
  hideBtn.addEventListener("click", () => {
    closeAssistantLauncherContextMenu();
    setAiAssistantLauncherVisible(false);
    setStatus("ArcBot icon hidden. Use View > Show AI Bot Icon to restore it.");
  });

  menu.appendChild(hideBtn);
  document.body.appendChild(menu);
  return menu;
}

function closeAssistantLauncherContextMenu() {
  const menu = $("aiAssistantLauncherContextMenu");
  if (menu) menu.classList.remove("open");
}

function openAssistantLauncherContextMenu(event) {
  const menu = ensureAssistantLauncherContextMenu();
  const width = menu.offsetWidth || 132;
  const height = menu.offsetHeight || 36;
  const margin = 6;
  const left = Math.min(Math.max(margin, event.clientX), Math.max(margin, window.innerWidth - width - margin));
  const top = Math.min(Math.max(margin, event.clientY), Math.max(margin, window.innerHeight - height - margin));
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.classList.add("open");
  menu.querySelector("button")?.focus?.();
}

function normalizeAssistantMode(mode) {
  const key = String(mode || "").trim().toLowerCase();
  if (key === "review" || key === "approve") return key;
  return "edit";
}

function getModeLabel() {
  if (assistantMode === "review") return "Read Only";
  if (assistantMode === "approve") return "Ask for Approval";
  return "Edit Automatically";
}

function setModeIcon() {
  const icon = $("aiAssistantModeIcon");
  if (!icon) return;
  icon.innerHTML = assistantMode === "review"
    ? '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"></path><circle cx="12" cy="12" r="3"></circle>'
    : '<path d="M18 11V7a2 2 0 0 0-4 0v3"></path><path d="M14 10V6a2 2 0 0 0-4 0v7"></path><path d="M10 13V8a2 2 0 1 0-4 0v6"></path><path d="M18 11a2 2 0 1 1 4 0v3a8 8 0 0 1-16 0"></path>';
}

function setAssistantMode(mode, options = {}) {
  assistantMode = normalizeAssistantMode(mode);
  setText($("aiAssistantModeLabel"), getModeLabel());
  setModeIcon();
  $("aiAssistantReviewModeOption")?.classList.toggle("active", assistantMode === "review");
  $("aiAssistantApprovalModeOption")?.classList.toggle("active", assistantMode === "approve");
  $("aiAssistantEditModeOption")?.classList.toggle("active", assistantMode === "edit");
  setStatus(assistantReady ? `${isClaudeModel() ? getAssistantModelLabel() : "Codex"} ready. ${getModeLabel()}.` : `${getModeLabel()} selected.`);
  updateAssistantSettingsPanel();
  if (!assistantMessages.length) renderMessages();
  if (options.save !== false) saveCurrentSession();
}

function setComposerEnabled(enabled) {
  const input = $("aiAssistantInput");
  const sendBtn = $("aiAssistantSendBtn");
  if (input) input.disabled = false;
  if (sendBtn) {
    const isCancel = !!assistantBusy && !!currentRequestId;
    sendBtn.disabled = !isCancel && !enabled;
    sendBtn.classList.toggle("cancel", isCancel);
    sendBtn.classList.toggle("canceling", isCancel && assistantCancelRequested);
    sendBtn.setAttribute("aria-label", isCancel ? "Cancel request" : "Send");
    sendBtn.title = isCancel ? "Cancel request" : "Send";
  }
  updateAssistantSettingsPanel();
}

function autoGrowAssistantInput() {
  const input = $("aiAssistantInput");
  if (!input) return;
  input.style.height = "auto";
  const nextHeight = Math.min(300, Math.max(38, input.scrollHeight));
  input.style.height = `${nextHeight}px`;
  input.style.overflowY = input.scrollHeight > 300 ? "auto" : "hidden";
}

function isSlashSkillQuery(input) {
  if (!input) return false;
  const value = String(input.value || "");
  const cursor = Number(input.selectionStart ?? value.length);
  const before = value.slice(0, cursor);
  const after = value.slice(cursor);
  if (before.includes("\n") || after.trim()) return false;
  return /^\s*\/[A-Za-z0-9_-]*$/.test(before);
}

function getSlashSkillFilter(input) {
  if (!input) return "";
  const value = String(input.value || "");
  const cursor = Number(input.selectionStart ?? value.length);
  const match = value.slice(0, cursor).match(/\/([A-Za-z0-9_-]*)$/);
  return String(match?.[1] || "").toLowerCase();
}

async function loadServerAssistantSkills() {
  const host = getHostApi();
  if (!host?.codexAssistantListSkills) return;
  try {
    const answer = await host.codexAssistantListSkills();
    serverAssistantSkills = (answer?.skills || []).map((skill) => ({
      id: skill.id,
      title: skill.title,
      subtitle: skill.description,
      badge: String(skill.scope || "AI").toUpperCase(),
    }));
    if (assistantSkillMenuOpen) renderAssistantSkillMenu();
  } catch {
    serverAssistantSkills = [];
  }
}

function getFilteredAssistantSkills(filter = assistantSkillFilter) {
  const text = String(filter || "").trim().toLowerCase();
  const allSkills = [...assistantSkills, ...serverAssistantSkills];
  if (!text) return allSkills;
  return allSkills.filter((skill) => (
    `${skill.title} ${skill.subtitle} ${skill.badge}`.toLowerCase().includes(text)
  ));
}

function ensureAssistantSkillDom() {
  const composer = $("aiAssistantComposer");
  if (composer && !$("aiAssistantSkillsMenu")) {
    const menu = document.createElement("div");
    menu.id = "aiAssistantSkillsMenu";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", "ArcBot skills");
    composer.appendChild(menu);
  }
  if (!$("aiAssistantSqlReviewDialog")) {
    const dialog = document.createElement("section");
    dialog.id = "aiAssistantSqlReviewDialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", "SQL Format Validation review");
    dialog.innerHTML = `
      <div class="aiAssistantSqlReviewHeader">
        <div class="aiAssistantSqlReviewTitleWrap">
          <div class="aiAssistantSqlReviewTitle">SQL Format Validation</div>
          <div id="aiAssistantSqlReviewSubtitle" class="aiAssistantSqlReviewSubtitle"></div>
        </div>
        <button id="aiAssistantSqlReviewCloseBtn" class="aiAssistantSqlReviewIconBtn" type="button" title="Close" aria-label="Close">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 7l10 10"></path><path d="M17 7L7 17"></path></svg>
        </button>
      </div>
      <div id="aiAssistantSqlReviewStatus" class="aiAssistantSqlReviewStatus"></div>
      <div id="aiAssistantSqlReviewFindings" class="aiAssistantSqlReviewFindings"></div>
      <div class="aiAssistantSqlReviewDiff">
        <div class="aiAssistantSqlReviewPane">
          <div class="aiAssistantSqlReviewPaneLabel">Review diff</div>
          <pre id="aiAssistantSqlReviewUnified" class="aiAssistantSqlReviewCode" aria-label="SQL formatting diff"></pre>
        </div>
      </div>
      <div class="aiAssistantSqlReviewFooter">
        <div id="aiAssistantSqlReviewMeta" class="aiAssistantSqlReviewMeta"></div>
        <button id="aiAssistantSqlReviewApplyBtn" class="aiAssistantBtn primary" type="button">Apply formatted SQL</button>
        <button id="aiAssistantSqlReviewCancelBtn" class="aiAssistantBtn" type="button">Cancel</button>
      </div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeNw" data-sql-review-resize-edge="nw" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeN" data-sql-review-resize-edge="n" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeNe" data-sql-review-resize-edge="ne" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeE" data-sql-review-resize-edge="e" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeSe" data-sql-review-resize-edge="se" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeS" data-sql-review-resize-edge="s" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeSw" data-sql-review-resize-edge="sw" aria-hidden="true"></div>
      <div class="aiAssistantSqlReviewResizeHandle aiAssistantSqlReviewResizeW" data-sql-review-resize-edge="w" aria-hidden="true"></div>
    `;
    document.body.appendChild(dialog);
    $("aiAssistantSqlReviewCloseBtn")?.addEventListener("click", closeSqlReviewDialog);
    $("aiAssistantSqlReviewCancelBtn")?.addEventListener("click", closeSqlReviewDialog);
    $("aiAssistantSqlReviewApplyBtn")?.addEventListener("click", () => {
      void applySqlReviewReplacement();
    });
    dialog.querySelector(".aiAssistantSqlReviewHeader")?.addEventListener("pointerdown", startSqlReviewDialogDrag);
    dialog.addEventListener("pointerdown", bringSqlReviewDialogToFront);
    dialog.querySelectorAll(".aiAssistantSqlReviewResizeHandle").forEach((handle) => {
      handle.addEventListener("pointerdown", startSqlReviewDialogResize);
    });
  }
}

function renderAssistantSkillMenu() {
  ensureAssistantSkillDom();
  const menu = $("aiAssistantSkillsMenu");
  if (!menu) return;
  const skills = getFilteredAssistantSkills();
  menu.textContent = "";
  const header = document.createElement("div");
  header.className = "aiAssistantSkillsHeader";
  header.textContent = "Skills";
  menu.appendChild(header);
  if (!skills.length) {
    const empty = document.createElement("div");
    empty.className = "aiAssistantSkillsEmpty";
    empty.textContent = "No matching skills";
    menu.appendChild(empty);
  }
  skills.forEach((skill, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `aiAssistantSkillItem${index === 0 ? " active" : ""}`;
    button.dataset.skillId = skill.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", index === 0 ? "true" : "false");
    button.innerHTML = `
      <span class="aiAssistantSkillIcon" aria-hidden="true"></span>
      <span class="aiAssistantSkillText">
        <span class="aiAssistantSkillTitle"></span>
        <span class="aiAssistantSkillSubtitle"></span>
      </span>
    `;
    button.querySelector(".aiAssistantSkillIcon").textContent = skill.badge || "/";
    button.querySelector(".aiAssistantSkillTitle").textContent = skill.title;
    button.querySelector(".aiAssistantSkillSubtitle").textContent = skill.subtitle;
    button.addEventListener("click", () => {
      closeAssistantSkillMenu();
      void runAssistantSkill(skill.id);
    });
    menu.appendChild(button);
  });
  menu.classList.toggle("open", assistantSkillMenuOpen);
}

function openAssistantSkillMenu() {
  assistantSkillMenuOpen = true;
  renderAssistantSkillMenu();
  void loadServerAssistantSkills();
}

function closeAssistantSkillMenu() {
  assistantSkillMenuOpen = false;
  $("aiAssistantSkillsMenu")?.classList.remove("open");
}

function updateAssistantSkillMenuFromInput() {
  const input = $("aiAssistantInput");
  if (!isSlashSkillQuery(input)) {
    closeAssistantSkillMenu();
    return;
  }
  assistantSkillFilter = getSlashSkillFilter(input);
  openAssistantSkillMenu();
}

function moveAssistantSkillSelection(delta) {
  const menu = $("aiAssistantSkillsMenu");
  const items = Array.from(menu?.querySelectorAll?.(".aiAssistantSkillItem") || []);
  if (!items.length) return;
  const current = Math.max(0, items.findIndex((item) => item.classList.contains("active")));
  const next = (current + delta + items.length) % items.length;
  items.forEach((item, index) => {
    item.classList.toggle("active", index === next);
    item.setAttribute("aria-selected", index === next ? "true" : "false");
  });
}

function activateSelectedAssistantSkill() {
  const item = $("aiAssistantSkillsMenu")?.querySelector?.(".aiAssistantSkillItem.active")
    || $("aiAssistantSkillsMenu")?.querySelector?.(".aiAssistantSkillItem");
  const skillId = item?.dataset?.skillId || "";
  if (!skillId) return false;
  closeAssistantSkillMenu();
  void runAssistantSkill(skillId);
  return true;
}

function isSqlAssistantContext(context) {
  const language = String(context?.language || "").trim().toLowerCase();
  const path = String(context?.targetPath || context?.path || "").trim().toLowerCase();
  const tabType = String(context?.tabType || context?.pageType || "").trim().toLowerCase();
  return language === "sql" || path.endsWith(".sql") || tabType === "snowflake";
}

function countChangedLines(original, proposed) {
  const oldLines = normalizeDiffText(original).split("\n");
  const newLines = normalizeDiffText(proposed).split("\n");
  const max = Math.max(oldLines.length, newLines.length);
  let changed = 0;
  for (let i = 0; i < max; i += 1) {
    if ((oldLines[i] || "") !== (newLines[i] || "")) changed += 1;
  }
  return changed;
}

function normalizeDiffText(value) {
  return String(value ?? "").replace(/\r\n?/g, "\n").replace(/\s+$/g, "");
}

function computeUnifiedDiff(original, proposed) {
  const oldLines = normalizeDiffText(original).split("\n");
  const newLines = normalizeDiffText(proposed).split("\n");
  const oldCount = oldLines.length;
  const newCount = newLines.length;
  if (oldCount * newCount > 120000) {
    if (normalizeDiffText(original) === normalizeDiffText(proposed)) {
      return {
        lines: oldLines.map((text, index) => ({ text, type: "same", oldLine: index + 1, newLine: index + 1 })),
      };
    }
    return {
      lines: [
        ...oldLines.map((text, index) => ({ text, type: "deleted", oldLine: index + 1, newLine: null })),
        ...newLines.map((text, index) => ({ text, type: "added", oldLine: null, newLine: index + 1 })),
      ],
    };
  }
  const dp = Array.from({ length: oldCount + 1 }, () => Array(newCount + 1).fill(0));
  for (let i = oldCount - 1; i >= 0; i -= 1) {
    for (let j = newCount - 1; j >= 0; j -= 1) {
      dp[i][j] = oldLines[i] === newLines[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const lines = [];
  let i = 0;
  let j = 0;
  while (i < oldCount || j < newCount) {
    if (i < oldCount && j < newCount && oldLines[i] === newLines[j]) {
      lines.push({ text: oldLines[i], type: "same", oldLine: i + 1, newLine: j + 1 });
      i += 1;
      j += 1;
    } else if (i < oldCount && (j >= newCount || dp[i + 1][j] >= dp[i][j + 1])) {
      lines.push({ text: oldLines[i], type: "deleted", oldLine: i + 1, newLine: null });
      i += 1;
    } else {
      lines.push({ text: newLines[j], type: "added", oldLine: null, newLine: j + 1 });
      j += 1;
    }
  }
  return { lines };
}

function appendSqlDiffToken(parent, text, className = "") {
  if (!text) return;
  if (!className) {
    parent.appendChild(document.createTextNode(text));
    return;
  }
  const token = document.createElement("span");
  token.className = `aiAssistantSqlToken ${className}`;
  token.textContent = text;
  parent.appendChild(token);
}

function appendHighlightedSqlDiffCode(parent, text) {
  const source = String(text || " ");
  let index = 0;
  while (index < source.length) {
    const rest = source.slice(index);
    if (rest.startsWith("--")) {
      appendSqlDiffToken(parent, rest, "comment");
      return;
    }
    if (rest.startsWith("/*")) {
      const end = source.indexOf("*/", index + 2);
      const next = end >= 0 ? end + 2 : source.length;
      appendSqlDiffToken(parent, source.slice(index, next), "comment");
      index = next;
      continue;
    }
    const ch = source[index];
    if (ch === "'" || ch === '"') {
      const quote = ch;
      const start = index;
      index += 1;
      while (index < source.length) {
        if (source[index] === quote && source[index + 1] === quote) {
          index += 2;
        } else if (source[index] === quote) {
          index += 1;
          break;
        } else {
          index += 1;
        }
      }
      appendSqlDiffToken(parent, source.slice(start, index), "string");
      continue;
    }
    if (ch === "[") {
      const end = source.indexOf("]", index + 1);
      if (end >= 0) {
        appendSqlDiffToken(parent, source.slice(index, end + 1), "identifier");
        index = end + 1;
        continue;
      }
    }
    const number = rest.match(/^\b\d+(?:\.\d+)?\b/);
    if (number) {
      appendSqlDiffToken(parent, number[0], "number");
      index += number[0].length;
      continue;
    }
    const word = rest.match(/^[A-Za-z_][A-Za-z0-9_]*/);
    if (word) {
      const value = word[0];
      const upper = value.toUpperCase();
      const after = source.slice(index + value.length).trimStart();
      if (SQL_DIFF_KEYWORDS.has(upper)) appendSqlDiffToken(parent, value, "keyword");
      else if (SQL_DIFF_FUNCTIONS.has(upper) && after.startsWith("(")) appendSqlDiffToken(parent, value, "function");
      else if (SQL_DIFF_DATATYPES.has(upper)) appendSqlDiffToken(parent, value, "datatype");
      else appendSqlDiffToken(parent, value);
      index += value.length;
      continue;
    }
    appendSqlDiffToken(parent, ch);
    index += 1;
  }
}

function renderUnifiedDiff(container, lines) {
  if (!container) return;
  container.textContent = "";
  container.style.removeProperty("--ai-assistant-sql-diff-width");
  lines.forEach((line) => {
    const row = document.createElement("div");
    row.className = `aiAssistantSqlDiffLine ${line.type || "same"}`;
    const oldNumber = document.createElement("span");
    oldNumber.className = "aiAssistantSqlDiffNumber old";
    oldNumber.textContent = line.oldLine == null ? "" : String(line.oldLine);
    const newNumber = document.createElement("span");
    newNumber.className = "aiAssistantSqlDiffNumber new";
    newNumber.textContent = line.newLine == null ? "" : String(line.newLine);
    const marker = document.createElement("span");
    marker.className = "aiAssistantSqlDiffMarker";
    marker.textContent = line.type === "added" ? "+" : line.type === "deleted" ? "-" : " ";
    const code = document.createElement("span");
    code.className = "aiAssistantSqlDiffCode";
    appendHighlightedSqlDiffCode(code, line.text || " ");
    row.append(oldNumber, newNumber, marker, code);
    container.appendChild(row);
  });
  window.requestAnimationFrame(() => {
    if (!container.isConnected) return;
    const rows = Array.from(container.querySelectorAll(".aiAssistantSqlDiffLine"));
    const widest = rows.reduce((max, row) => Math.max(max, row.scrollWidth), container.clientWidth);
    if (widest > 0) container.style.setProperty("--ai-assistant-sql-diff-width", `${Math.ceil(widest)}px`);
  });
}

function renderSqlReviewDialog({ allowOpen = true } = {}) {
  ensureAssistantSkillDom();
  const state = assistantSqlReviewState;
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog || !state) return;
  const wasOpen = dialog.classList.contains("open");
  const changedLines = countChangedLines(state.original, state.proposed);
  const diff = computeUnifiedDiff(state.original, state.proposed);
  const subtitle = state.selectionOnly
    ? `${state.context?.title || state.context?.targetPath || "Active SQL tab"} - selected lines`
    : state.context?.title || state.context?.targetPath || "Active SQL tab";
  setText($("aiAssistantSqlReviewSubtitle"), subtitle);
  setText($("aiAssistantSqlReviewStatus"), state.status || "Review the proposed formatting before applying it to the active tab.");
  const dialectLabel = state.dialect === "snowflake" ? "Snowflake" : "T-SQL";
  const engineName = String(state.preview?.engine?.name || state.preview?.engine?.formatter || "SQLFluff").trim();
  const elapsedMs = Number(state.preview?.elapsed_ms);
  const meta = [
    dialectLabel,
    `${changedLines} changed line${changedLines === 1 ? "" : "s"}`,
    engineName,
    Number.isFinite(elapsedMs) ? `${Math.round(elapsedMs)} ms` : "",
  ].filter(Boolean).join(" · ");
  setText($("aiAssistantSqlReviewMeta"), meta);
  const applyButton = $("aiAssistantSqlReviewApplyBtn");
  if (applyButton) {
    const canApply = state.safeToApply && state.changed;
    applyButton.disabled = !canApply;
    applyButton.textContent = !state.safeToApply
      ? "Formatting unavailable"
      : state.changed
        ? "Apply formatted SQL"
        : "Already formatted";
  }
  renderUnifiedDiff($("aiAssistantSqlReviewUnified"), diff.lines);
  const findingsEl = $("aiAssistantSqlReviewFindings");
  if (findingsEl) {
    findingsEl.textContent = "";
    const list = document.createElement("ul");
    (state.findings || []).forEach((finding) => {
      const item = document.createElement("li");
      item.textContent = finding;
      list.appendChild(item);
    });
    findingsEl.appendChild(list);
  }
  if (!allowOpen) return;
  dialog.classList.add("open");
  if (!wasOpen) bringSqlReviewDialogToFront();
  applyStoredSqlReviewDialogPosition();
}

function closeSqlReviewDialog() {
  assistantSqlReviewState = null;
  stopSqlReviewDialogDrag();
  stopSqlReviewDialogResize();
  $("aiAssistantSqlReviewDialog")?.classList.remove("open");
}

function bringSqlReviewDialogToFront() {
  const dialog = $("aiAssistantSqlReviewDialog");
  const panel = $("aiAssistantPanel");
  if (dialog?.classList.contains("open")) dialog.style.zIndex = String(SQL_REVIEW_DIALOG_ACTIVE_Z);
  if (panel) panel.style.zIndex = "";
}

function bringAssistantPanelToFront() {
  const panel = $("aiAssistantPanel");
  const dialog = $("aiAssistantSqlReviewDialog");
  if (panel?.classList.contains("open")) panel.style.zIndex = String(ASSISTANT_PANEL_FRONT_Z);
  if (dialog) dialog.style.zIndex = String(SQL_REVIEW_DIALOG_Z);
}

function clampSqlReviewDialogPosition(left, top, rect) {
  const margin = 12;
  const width = rect?.width || $("aiAssistantSqlReviewDialog")?.getBoundingClientRect?.().width || 980;
  const height = rect?.height || $("aiAssistantSqlReviewDialog")?.getBoundingClientRect?.().height || 720;
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  const maxTop = Math.max(margin, window.innerHeight - height - margin);
  return {
    left: Math.min(maxLeft, Math.max(margin, left)),
    top: Math.min(maxTop, Math.max(margin, top)),
  };
}

function applySqlReviewDialogPosition(left, top, rect = null) {
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog) return;
  const position = clampSqlReviewDialogPosition(left, top, rect);
  assistantSqlReviewDialogPosition = position;
  dialog.style.left = `${position.left}px`;
  dialog.style.top = `${position.top}px`;
  dialog.style.transform = "none";
}

function clampSqlReviewDialogSize(width, height) {
  const margin = 12;
  const maxWidth = Math.max(SQL_REVIEW_DIALOG_MIN_WIDTH, window.innerWidth - (margin * 2));
  const maxHeight = Math.max(SQL_REVIEW_DIALOG_MIN_HEIGHT, window.innerHeight - (margin * 2));
  return {
    width: Math.min(maxWidth, Math.max(SQL_REVIEW_DIALOG_MIN_WIDTH, width)),
    height: Math.min(maxHeight, Math.max(SQL_REVIEW_DIALOG_MIN_HEIGHT, height)),
  };
}

function applySqlReviewDialogSize(width, height) {
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog) return null;
  const size = clampSqlReviewDialogSize(width, height);
  assistantSqlReviewDialogSize = size;
  dialog.style.width = `${Math.round(size.width)}px`;
  dialog.style.height = `${Math.round(size.height)}px`;
  return size;
}

function resetSqlReviewDialogPosition() {
  assistantSqlReviewDialogPosition = null;
  assistantSqlReviewDialogSize = null;
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog) return;
  dialog.style.left = "";
  dialog.style.top = "";
  dialog.style.width = "";
  dialog.style.height = "";
  dialog.style.transform = "";
  dialog.style.zIndex = "";
}

function applyStoredSqlReviewDialogPosition() {
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog || (!assistantSqlReviewDialogPosition && !assistantSqlReviewDialogSize)) return;
  window.requestAnimationFrame(() => {
    if (assistantSqlReviewDialogSize) {
      applySqlReviewDialogSize(assistantSqlReviewDialogSize.width, assistantSqlReviewDialogSize.height);
    }
    const rect = dialog.getBoundingClientRect();
    if (assistantSqlReviewDialogPosition) {
      applySqlReviewDialogPosition(assistantSqlReviewDialogPosition.left, assistantSqlReviewDialogPosition.top, rect);
    }
  });
}

function clampOpenSqlReviewDialogToViewport() {
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog?.classList.contains("open")) return;
  if (assistantSqlReviewDialogSize) applySqlReviewDialogSize(assistantSqlReviewDialogSize.width, assistantSqlReviewDialogSize.height);
  const rect = dialog.getBoundingClientRect();
  if (assistantSqlReviewDialogPosition) applySqlReviewDialogPosition(rect.left, rect.top, rect);
}

function updateSqlReviewDialogDrag(event) {
  if (!assistantSqlReviewDragState) return;
  const nextLeft = assistantSqlReviewDragState.startLeft + (event.clientX - assistantSqlReviewDragState.startX);
  const nextTop = assistantSqlReviewDragState.startTop + (event.clientY - assistantSqlReviewDragState.startY);
  applySqlReviewDialogPosition(nextLeft, nextTop, assistantSqlReviewDragState.rect);
}

function stopSqlReviewDialogDrag(event = null) {
  if (!assistantSqlReviewDragState) return;
  const handle = assistantSqlReviewDragState.handle;
  if (event?.pointerId != null && handle?.hasPointerCapture?.(event.pointerId)) {
    handle.releasePointerCapture(event.pointerId);
  }
  document.body.classList.remove("aiAssistantSqlReviewDragging");
  window.removeEventListener("pointermove", updateSqlReviewDialogDrag);
  window.removeEventListener("pointerup", stopSqlReviewDialogDrag);
  window.removeEventListener("pointercancel", stopSqlReviewDialogDrag);
  assistantSqlReviewDragState = null;
}

function startSqlReviewDialogDrag(event) {
  if (event.button !== 0 || event.target?.closest?.("button")) return;
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog) return;
  bringSqlReviewDialogToFront();
  const rect = dialog.getBoundingClientRect();
  assistantSqlReviewDragState = {
    handle: event.currentTarget,
    rect,
    startX: event.clientX,
    startY: event.clientY,
    startLeft: rect.left,
    startTop: rect.top,
  };
  dialog.style.width = `${rect.width}px`;
  dialog.style.height = `${rect.height}px`;
  applySqlReviewDialogPosition(rect.left, rect.top, rect);
  document.body.classList.add("aiAssistantSqlReviewDragging");
  event.currentTarget?.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", updateSqlReviewDialogDrag);
  window.addEventListener("pointerup", stopSqlReviewDialogDrag);
  window.addEventListener("pointercancel", stopSqlReviewDialogDrag);
  event.preventDefault();
}

function updateSqlReviewDialogResize(event) {
  if (!assistantSqlReviewResizeState) return;
  const state = assistantSqlReviewResizeState;
  const dx = event.clientX - state.startX;
  const dy = event.clientY - state.startY;
  let width = state.width;
  let height = state.height;
  let left = state.left;
  let top = state.top;
  if (state.edge.includes("e")) width = state.width + dx;
  if (state.edge.includes("w")) width = state.width - dx;
  if (state.edge.includes("s")) height = state.height + dy;
  if (state.edge.includes("n")) height = state.height - dy;
  const nextSize = applySqlReviewDialogSize(width, height);
  if (!nextSize) return;
  if (state.edge.includes("w")) left = state.left + state.width - nextSize.width;
  if (state.edge.includes("n")) top = state.top + state.height - nextSize.height;
  applySqlReviewDialogPosition(left, top, { width: nextSize.width, height: nextSize.height });
}

function stopSqlReviewDialogResize(event = null) {
  if (!assistantSqlReviewResizeState) return;
  const handle = assistantSqlReviewResizeState.handle;
  if (event?.pointerId != null && handle?.hasPointerCapture?.(event.pointerId)) {
    handle.releasePointerCapture(event.pointerId);
  }
  document.body.classList.remove("aiAssistantSqlReviewResizing");
  window.removeEventListener("pointermove", updateSqlReviewDialogResize);
  window.removeEventListener("pointerup", stopSqlReviewDialogResize);
  window.removeEventListener("pointercancel", stopSqlReviewDialogResize);
  assistantSqlReviewResizeState = null;
}

function startSqlReviewDialogResize(event) {
  if (event.button !== 0) return;
  const dialog = $("aiAssistantSqlReviewDialog");
  if (!dialog) return;
  bringSqlReviewDialogToFront();
  const rect = dialog.getBoundingClientRect();
  assistantSqlReviewResizeState = {
    handle: event.currentTarget,
    edge: String(event.currentTarget?.dataset?.sqlReviewResizeEdge || "se"),
    startX: event.clientX,
    startY: event.clientY,
    left: rect.left,
    top: rect.top,
    width: rect.width,
    height: rect.height,
  };
  dialog.style.transform = "none";
  applySqlReviewDialogSize(rect.width, rect.height);
  applySqlReviewDialogPosition(rect.left, rect.top, rect);
  document.body.classList.add("aiAssistantSqlReviewResizing");
  event.currentTarget?.setPointerCapture?.(event.pointerId);
  window.addEventListener("pointermove", updateSqlReviewDialogResize);
  window.addEventListener("pointerup", stopSqlReviewDialogResize);
  window.addEventListener("pointercancel", stopSqlReviewDialogResize);
  event.preventDefault();
  event.stopPropagation();
}

function requestActiveTextReplacement({
  proposed,
  original,
  range = null,
  expectedTabId,
  expectedTargetPath,
}) {
  const activeTab = shell.state?.tabs?.find?.((tab) => tab.id === shell.state.activeId) || null;
  if (!expectedTabId || activeTab?.id !== expectedTabId) {
    return Promise.resolve({
      ok: false,
      error: "The reviewed SQL tab is no longer active. Run the skill again before applying.",
    });
  }
  const iframe = activeTab?.iframe || null;
  if (!iframe?.contentWindow) {
    return Promise.resolve({ ok: false, error: "No active editor tab is available." });
  }
  return new Promise((resolve) => {
    const requestId = `arcbot_replace_text_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let done = false;
    const finish = (payload) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      resolve(payload || { ok: false, error: "The active editor did not return a replacement result." });
    };
    const onMessage = (event) => {
      if (event.source !== iframe.contentWindow) return;
      const msg = event.data || {};
      if (msg.type !== assistantMessageType("replace-text-result") || msg.requestId !== requestId) return;
      finish(msg);
    };
    window.addEventListener("message", onMessage);
    try {
      iframe.contentWindow.postMessage({
        type: assistantMessageType("replace-text"),
        requestId,
        text: proposed,
        expectedText: original,
        expectedTargetPath: String(expectedTargetPath || ""),
        range,
      }, "*");
    } catch (err) {
      finish({ ok: false, error: String(err?.message || err || "Could not send replacement to the active editor.") });
      return;
    }
    window.setTimeout(() => finish({ ok: false, error: "Timed out waiting for the active editor to apply the SQL." }), 120000);
  });
}

async function applySqlReviewReplacement() {
  const state = assistantSqlReviewState;
  if (!state) return;
  if (!state.safeToApply) {
    const message = "The parser-backed safety checks did not approve this formatting preview; the SQL was not changed.";
    setText($("aiAssistantSqlReviewStatus"), message);
    setStatus(message, "error");
    return;
  }
  if (!state.changed) {
    setText($("aiAssistantSqlReviewStatus"), "The active SQL already matches the formatter profile.");
    return;
  }
  setText($("aiAssistantSqlReviewStatus"), "Applying formatted SQL to the active tab...");
  const result = await requestActiveTextReplacement({
    proposed: state.proposed,
    original: state.original,
    range: state.selection || null,
    expectedTabId: state.context?.tabId || "",
    expectedTargetPath: state.context?.targetPath || state.context?.path || "",
  });
  if (!result?.ok) {
    const message = result?.error || "Could not apply formatted SQL.";
    setText($("aiAssistantSqlReviewStatus"), message);
    setStatus(message, "error");
    return;
  }
  closeSqlReviewDialog();
  const message = state.selectionOnly
    ? "Applied formatted SQL to the selected lines."
    : "Applied formatted SQL to the active tab.";
  setStatus(message);
  shell.updateStatusBar?.(message);
}

function deterministicSqlReviewStatus(state, suffix) {
  if (!state?.safeToApply) return `${suffix}; the unsafe formatting preview was left unchanged.`;
  if (!state?.changed) return `${suffix}; the SQL already matches the deterministic formatter profile.`;
  return `${suffix}; deterministic formatting remains ready to apply.`;
}

function matchesSqlReviewRequest(state, { context, original, dialect, preview }) {
  return !!state
    && state.original === original
    && state.dialect === dialect
    && state.context?.tabId === context?.tabId
    && state.preview?.source_hash === preview?.source_hash;
}

async function updateSqlReviewWithLlm(context, original, proposed, findings, dialect, preview) {
  const host = getHostApi();
  if (!host?.codexAssistantSend || !assistantReady || assistantBusy) {
    if (matchesSqlReviewRequest(assistantSqlReviewState, { context, original, dialect, preview })) {
      assistantSqlReviewState.status = deterministicSqlReviewStatus(assistantSqlReviewState, "Optional AI review skipped");
      renderSqlReviewDialog();
    }
    return;
  }
  const runToken = assistantRunGate.tryAcquire("sql-review");
  if (!runToken) return;
  assistantBusy = true;
  setComposerEnabled(false);
  try {
    if (!currentSessionId) await ensureAssistantSession();
  } catch (err) {
    assistantRunGate.release(runToken);
    assistantBusy = false;
    setComposerEnabled(assistantReady);
    const message = `Optional AI review unavailable: ${String(err?.message || err)}`;
    if (matchesSqlReviewRequest(assistantSqlReviewState, { context, original, dialect, preview })) {
      assistantSqlReviewState.status = message;
      renderSqlReviewDialog();
    }
    return;
  }
  const title = String(context?.title || context?.targetPath || context?.path || "Active SQL tab").trim();
  const visiblePrompt = [
    context?.selectionOnly ? `Run ${dialect} SQL Format Validation AI review on selected SQL lines.` : `Run ${dialect} SQL Format Validation AI review on the entire SQL file.`,
    title ? `File: ${title}` : "",
    context?.selectionOnly
      ? "Review the deterministic formatting changes and call out SQL risks before I apply them."
      : "Review every SQL block in the file, not only the first section, and call out SQL risks before I apply the formatting.",
  ].filter(Boolean).join("\n");
  assistantMessages.push({ role: "user", content: visiblePrompt, timestamp: nowIso() });
  appendMessage("user", visiblePrompt);
  currentSessionTitle = assistantMessages.find((message) => message.role === "user")?.content?.slice(0, 42) || currentSessionTitle;
  updateAssistantSettingsPanel();
  currentRequestId = `arcbot_sql_review_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  currentRunStartedAt = performance.now();
  currentStepStartedAt = currentRunStartedAt;
  assistantProgressSteps = createAssistantProgressSteps();
  assistantWorkCardExpanded = true;
  startAssistantProgressTicker();
  assistantCancelRequested = false;
  assistantHostRequestSubmitted = false;
  assistantActivities = [];
  resetAssistantActivityTyping();
  assistantDebugLogs = [];
  renderActivities();
  renderDebugLog();
  appendActivity("Reading your SQL Format Validation review request.", "activity", { elapsedMs: 0 });
  appendActivity("Reviewing deterministic SQL formatting changes.", "activity", { save: false });
  const pending = appendMessage("assistant", "Thinking ...");
  pending?.classList.add("thinking");
  currentPendingMessageEl = pending;
  currentAssistantStreamText = "";
  try {
    await saveCurrentSession();
  } catch (err) {
    assistantRunGate.release(runToken);
    assistantBusy = false;
    currentRequestId = "";
    currentRunStartedAt = 0;
    currentStepStartedAt = 0;
    stopAssistantProgressTicker();
    currentPendingMessageEl = null;
    currentAssistantStreamText = "";
    assistantCancelRequested = false;
    assistantHostRequestSubmitted = false;
    setComposerEnabled(assistantReady);
    const message = `Optional AI review unavailable: ${String(err?.message || err)}`;
    await resolveAssistantPendingMessage(pending, message);
    return;
  }
  assistantHostRequestSubmitted = true;
  setComposerEnabled(false);
  if (matchesSqlReviewRequest(assistantSqlReviewState, { context, original, dialect, preview })) {
    assistantSqlReviewState.status = "Deterministic formatting is ready. Optional AI review is running...";
    renderSqlReviewDialog();
  }
  try {
    const activeContext = {
      available: true,
      tabId: context?.tabId || "",
      pageType: context?.pageType || "",
      tabType: context?.tabType || "",
      title: context?.title || "",
      targetPath: context?.targetPath || context?.path || "",
      language: context?.language || "sql",
      sqlDialect: dialect,
      selectionOnly: !!context?.selectionOnly,
      selection: context?.selection || null,
      sqlFormatPreview: {
        sourceHash: preview?.source_hash || "",
        formattedHash: preview?.formatted_hash || "",
        safeToApply: !!preview?.safety?.safe_to_apply,
      },
    };
    const result = await host.codexAssistantSend({
      requestId: currentRequestId,
      sessionId: currentSessionId,
      mode: "review",
      model: assistantModel,
      reasoningEffort: assistantReasoningEffort,
      messages: [{ role: "user", content: buildSqlReviewPrompt({ title: context?.title, path: context?.targetPath || context?.path, original, proposed, findings, dialect }) }],
      activeContext,
      attachments: [],
      outputSchema: SQL_AI_REVIEW_RESPONSE_SCHEMA,
      streamDeltas: false,
    });
    const reviewStateMatches = matchesSqlReviewRequest(
      assistantSqlReviewState,
      { context, original, dialect, preview },
    );
    if (assistantCancelRequested) {
      const message = "SQL AI review canceled.";
      await resolveAssistantPendingMessage(pending, message);
      assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
      appendActivity("SQL AI review canceled.", "activity");
      failAssistantProgress("Review canceled");
      if (reviewStateMatches) assistantSqlReviewState.status = deterministicSqlReviewStatus(assistantSqlReviewState, "Optional AI review canceled");
    } else if (result?.ok && result?.text) {
      const reviewText = renderSqlAiReviewResponse(result.text, { expectedDialect: dialect });
      const reply = [
        "**SQL Format Validation AI Review**",
        title ? `For: ${title}${context?.selectionOnly ? " (selected lines)" : ""}` : "",
        `Reference: ${SQL_CODING_STANDARDS_MARKDOWN_LINK}`,
        "",
        reviewText,
      ].filter((part) => part !== "").join("\n");
      await resolveAssistantPendingMessage(pending, reply, { animate: !currentAssistantStreamText });
      assistantMessages.push({ role: "assistant", content: reply, timestamp: nowIso() });
      appendActivity("SQL AI review completed.", "activity");
      completeAssistantProgress("Review completed");
      if (reviewStateMatches) assistantSqlReviewState.status = deterministicSqlReviewStatus(assistantSqlReviewState, "Optional AI review completed");
    } else {
      const message = result?.error
        ? `Optional AI review unavailable: ${result.error}`
        : "Optional AI review unavailable; deterministic formatting is ready to apply.";
      await resolveAssistantPendingMessage(pending, message);
      assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
      appendActivity("SQL AI review unavailable.", "error");
      failAssistantProgress("Review unavailable");
      if (reviewStateMatches) assistantSqlReviewState.status = message;
    }
  } catch (err) {
    const message = `Optional AI review unavailable: ${String(err?.message || err)}`;
    await resolveAssistantPendingMessage(pending, message);
    assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
    appendActivity("SQL AI review failed.", "error");
    failAssistantProgress("Review failed");
    if (matchesSqlReviewRequest(assistantSqlReviewState, { context, original, dialect, preview })) {
      assistantSqlReviewState.status = message;
    }
  } finally {
    currentRequestId = "";
    currentRunStartedAt = 0;
    currentStepStartedAt = 0;
    stopAssistantProgressTicker();
    renderActivities();
    currentPendingMessageEl = null;
    currentAssistantStreamText = "";
    try {
      await saveCurrentSession();
      await refreshSessionList(currentSessionId);
    } finally {
      if (assistantRunGate.release(runToken)) assistantBusy = false;
      assistantCancelRequested = false;
      assistantHostRequestSubmitted = false;
      setComposerEnabled(assistantReady);
    }
  }
  renderSqlReviewDialog();
}

async function runSqlFormatValidationSkill() {
  const input = $("aiAssistantInput");
  if (input && isSlashSkillQuery(input)) {
    input.value = "";
    autoGrowAssistantInput();
  }
  setStatus("Preparing SQL Format Validation...");
  let context = null;
  try {
    context = await requestActivePageContext();
  } catch (err) {
    setStatus(String(err?.message || err || "Could not read the active tab."), "error");
    return;
  }
  if (!context?.available || !String(context?.text || "").trim()) {
    setStatus("Open an Arcode SQL editor tab before running SQL Format Validation.", "error");
    return;
  }
  if (!isSqlAssistantContext(context)) {
    setStatus("SQL Format Validation only runs on active SQL tabs.", "error");
    return;
  }
  const original = String(context.text || "");
  let dialect = "tsql";
  let preview = null;
  try {
    dialect = inferSqlDialect(context);
    setStatus(`Running parser-backed ${dialect === "snowflake" ? "Snowflake" : "T-SQL"} formatting checks...`);
    preview = await requestSqlFormatPreview({ sql: original, dialect });
  } catch (err) {
    const message = String(err?.message || err || "SQL formatting is unavailable.");
    setStatus(message, "error");
    return;
  }
  const proposed = preview.formatted_sql;
  const findings = buildSqlFormatFindings(preview);
  const safeToApply = !!preview.safety?.safe_to_apply;
  const firstDiagnostic = preview.diagnostics
    .map((entry) => String(entry?.message || entry?.detail || entry || "").trim())
    .find(Boolean);
  resetSqlReviewDialogPosition();
  assistantSqlReviewState = {
    context,
    preview,
    dialect,
    original,
    proposed,
    findings,
    safeToApply,
    changed: !!preview.changed,
    selection: context.selection || null,
    selectionOnly: !!context.selectionOnly,
    status: !safeToApply
      ? `${firstDiagnostic || "Parser-backed safety checks did not approve this preview."} The SQL was left unchanged.`
      : preview.changed
        ? "Review the parser-backed formatting diff before applying it to the active tab."
        : "The active SQL already matches the parser-backed formatter profile.",
  };
  renderSqlReviewDialog();
  setStatus(safeToApply
    ? preview.changed ? "SQL formatting preview is ready." : "SQL already matches the formatter profile."
    : firstDiagnostic || "SQL formatting failed its safety checks.",
  safeToApply ? "" : "error");
  void updateSqlReviewWithLlm(context, original, proposed, findings, dialect, preview);
}

async function runAssistantSkill(skillId) {
  if (skillId === SQL_FORMAT_VALIDATION_SKILL.id) {
    await runSqlFormatValidationSkill();
    return;
  }
  const skill = serverAssistantSkills.find((item) => item.id === skillId);
  if (skill) await sendAssistantMessage({ skill });
}

async function loadAssistantUserAvatarName() {
  const host = getHostApi();
  if (!host?.getWindowsUserName) return;
  try {
    const userName = String(await host.getWindowsUserName() || "").trim();
    if (!userName) return;
    assistantUserAvatarName = userName;
    document.querySelectorAll(".aiAssistantAvatarUser").forEach((avatar) => {
      avatar.innerHTML = createAssistantUserAvatarSvg(assistantUserAvatarName);
    });
    updateAssistantSettingsPanel();
  } catch {
    // Keep the default initial avatar if the host name is unavailable.
  }
}

function getMessageAvatar(role) {
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "aiAssistantAvatar aiAssistantAvatarArcBot";
    avatar.setAttribute("aria-hidden", "true");
    const img = document.createElement("img");
    img.className = "arcbot-mini-img";
    img.src = "/icons/ArcBot%20mini.png";
    img.alt = "";
    img.draggable = false;
    avatar.appendChild(img);
    return avatar;
  }
  const avatar = document.createElement("div");
  avatar.className = "aiAssistantAvatar aiAssistantAvatarUser";
  avatar.setAttribute("aria-hidden", "true");
  avatar.innerHTML = createAssistantUserAvatarSvg(assistantUserAvatarName);
  return avatar;
}

async function typeAssistantMessage(el, text) {
  return typeAssistantMessageContent(el, text, { scrollToBottom: scrollMessagesToBottom });
}

function appendMessage(role, text) {
  const container = $("aiAssistantMessages");
  if (!container) return null;
  container.querySelectorAll(".aiAssistantChatNotice").forEach((node) => node.remove());
  const normalizedRole = role === "assistant" ? "assistant" : "user";
  const el = document.createElement("div");
  el.className = `aiAssistantMessage ${normalizedRole}`;
  renderAssistantMessageContent(el, normalizedRole, text);
  const row = document.createElement("div");
  row.className = `aiAssistantMessageRow ${normalizedRole}`;
  row.append(getMessageAvatar(normalizedRole), el);
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
  return el;
}

async function resolveAssistantPendingMessage(el, text, { animate = false } = {}) {
  if (!el) return;
  el.classList.remove("thinking");
  if (animate) {
    await typeAssistantMessage(el, text);
  } else {
    renderAssistantMessageContent(el, "assistant", text);
    el.classList.remove("typing");
  }
}

function scrollMessagesToBottom() {
  const container = $("aiAssistantMessages");
  if (container) container.scrollTop = container.scrollHeight;
}

function applyStatus(status) {
  const usingClaude = isClaudeModel();
  if (usingClaude) {
    assistantReady = !!status?.claudeAuthenticated;
    if (!assistantReady) {
      setStatus("Claude is not signed in.", "error");
      setSetup({
        open: true,
        install: false,
        login: true,
        text: "Sign in to link this computer to your Claude account.",
      });
      setComposerEnabled(false);
      return;
    }
    setStatus(`${getAssistantModelLabel()} ready. ${getModeLabel()}.`);
    setSetup({ open: false });
    setComposerEnabled(!assistantBusy);
    updateAssistantSettingsPanel();
    return;
  }
  assistantReady = !!status?.installed && !!status?.authenticated;
  if (!status?.installed) {
    if (assistantInstallJustSucceeded) {
      setStatus(`Codex CLI installed, but ${assistantConfig.appName} cannot find it yet.`, "error");
      setSetup({
        open: true,
        install: false,
        login: false,
        text: `Restart ${assistantConfig.appName}, then refresh ArcBot status so the updated npm command path is picked up.`,
      });
      setComposerEnabled(false);
      return;
    }
    const setupAction = String(status?.setupAction || "install");
    const repair = setupAction === "repair";
    const canInstall = setupAction === "install" || repair;
    const launchError = String(status?.error || "").trim();
    setStatus(repair ? "Codex CLI could not start." : "Codex CLI is not installed.", "error");
    setSetup({
      open: true,
      install: canInstall,
      installLabel: repair ? "Repair" : "Install",
      login: false,
      text: launchError && canInstall
        ? `${launchError} ${repair ? "Repair installs a fresh per-user Codex CLI copy." : "Install creates a per-user Codex CLI copy."}`
        : launchError || "Install creates a per-user Codex CLI copy.",
    });
    setComposerEnabled(false);
    return;
  }
  assistantInstallJustSucceeded = false;
  if (status?.modelUpgradeRequired) {
    assistantReady = false;
    const minimumModel = String(status?.minimumDefaultModel || "the current default model");
    setStatus("Codex CLI update required.", "error");
    setSetup({
      open: true,
      install: true,
      installLabel: "Repair",
      login: false,
      text: `This Codex CLI does not advertise ${minimumModel}. Repair installs the current per-user CLI, then ArcBot will detect the available model catalog again.`,
    });
    setComposerEnabled(false);
    return;
  }
  if (!status?.authenticated) {
    setStatus("Codex CLI is installed but not signed in.", "error");
    setSetup({
      open: true,
      install: false,
      login: true,
      text: "Sign in to link this computer to your Codex account.",
    });
    setComposerEnabled(false);
    return;
  }
  if (status?.modelCatalogVerified === false) {
    assistantReady = false;
    const warning = String(status?.modelCatalogWarning || "").trim();
    setStatus("Codex model detection unavailable.", "error");
    setSetup({
      open: true,
      install: true,
      installLabel: "Repair",
      login: false,
      text: `Refresh ArcBot status to retry model detection, or Repair the per-user Codex CLI.${warning ? ` ${warning}` : ""}`,
    });
    setComposerEnabled(false);
    return;
  }
  setStatus(`Codex ready (${status.version || "installed"}). ${getModeLabel()}.`);
  setSetup({ open: false });
  setComposerEnabled(!assistantBusy);
  updateAssistantSettingsPanel();
}

function requestActivePageContext() {
  const activeTab = shell.state?.tabs?.find?.((tab) => tab.id === shell.state.activeId) || null;
  const baseContext = {
    available: false,
    tabId: activeTab?.id || "",
    tabType: activeTab?.type || "home",
    title: activeTab?.title || "",
  };
  const iframe = activeTab?.iframe || null;
  if (!iframe?.contentWindow) return Promise.resolve(baseContext);

  return new Promise((resolve) => {
    const requestId = `arcbot_context_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      resolve({ ...baseContext, ...(value || {}), available: !!value?.available });
    };
    const onMessage = (event) => {
      if (event.source !== iframe.contentWindow) return;
      const msg = event.data || {};
      if (msg.type !== assistantMessageType("context-result") || msg.requestId !== requestId) return;
      finish(msg.context || {});
    };
    window.addEventListener("message", onMessage);
    try {
      iframe.contentWindow.postMessage({ type: assistantMessageType("context-request"), requestId }, "*");
    } catch {
      finish(baseContext);
      return;
    }
    const timeoutMs = activeTab?.type === "project_instance"
      ? Number(assistantConfig.projectInstanceContextTimeoutMs || assistantConfig.contextTimeoutMs || 900)
      : Number(assistantConfig.contextTimeoutMs || 900);
    setTimeout(() => finish(baseContext), Math.max(1, timeoutMs));
  });
}

// ArcBot never writes a page's file. The tab that sent the context applies an
// edit as unsaved changes and saves it through its own save, and "revert the
// latest ArcBot edit" is that page's undo. The tab is addressed by id, so
// switching tabs while ArcBot works cannot send the edit to another page.
let lastArcBotEdit = null;

async function requestPageArcBotEdit(tabId, name, payload = {}, timeoutMs = 120000) {
  if (shell.state?.activeId !== tabId) {
    return { ok: false, error: "The page ArcBot worked on must still be active. Nothing was changed." };
  }
  const active = await requestActivePageContext();
  const scopeError = arcBotEditScopeError(tabId, shell.state?.activeId, active, payload.targetPath);
  if (scopeError) return { ok: false, error: scopeError };
  const tab = shell.state?.tabs?.find?.((item) => item.id === tabId) || null;
  const iframe = tab?.iframe || null;
  if (!tabId || !iframe?.contentWindow) {
    return Promise.resolve({ ok: false, error: "The page ArcBot worked on is no longer open. Nothing was changed." });
  }
  return new Promise((resolve) => {
    const requestId = `arcbot_${name}_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      window.removeEventListener("message", onMessage);
      resolve(result || { ok: false, error: "The page did not answer ArcBot." });
    };
    const onMessage = (event) => {
      if (event.source !== iframe.contentWindow) return;
      const msg = event.data || {};
      if (msg.type !== assistantMessageType(`${name}-result`) || msg.requestId !== requestId) return;
      finish(msg);
    };
    window.addEventListener("message", onMessage);
    try {
      iframe.contentWindow.postMessage({ type: assistantMessageType(name), requestId, ...payload }, "*");
    } catch (err) {
      finish({ ok: false, error: String(err?.message || err || "Could not reach the page.") });
      return;
    }
    window.setTimeout(() => finish({ ok: false, error: "The page did not answer ArcBot in time. Check the page before saving." }), timeoutMs);
  });
}

function isRevertLatestArcBotEditRequest(text) {
  const lower = String(text || "").toLowerCase();
  return /\b(revert|undo|restore)\b/.test(lower) && /\b(latest|last|previous|arcbot)\b/.test(lower);
}

async function revertLatestArcBotEdit() {
  if (!lastArcBotEdit) return { ok: false, error: "There is no ArcBot edit to revert in this window." };
  appendActivity("Asking the page to undo the latest ArcBot edit.", "activity");
  const reverted = await requestPageArcBotEdit(lastArcBotEdit.tabId, "revert-json-edit", {
    targetPath: lastArcBotEdit.targetPath,
  });
  if (!reverted?.ok) return { ok: false, error: reverted?.error || "The page could not revert the latest ArcBot edit." };
  lastArcBotEdit = null;
  return { ok: true, text: reverted.message || "Reverted the latest ArcBot edit." };
}

async function refreshAssistantStatus() {
  const host = getHostApi();
  if (!host?.codexAssistantStatus) {
    setStatus("ArcBot is available in the desktop app only.", "error");
    setSetup({ open: false });
    setComposerEnabled(false);
    return;
  }
  if (!isClaudeModel()) {
    await refreshAssistantModels({
      refresh: assistantModelCatalogChecked,
      promoteEmptyDefault: true,
    });
  }
  assistantStatusChecked = true;
  setStatus(isClaudeModel() ? "Checking Claude credentials..." : "Checking Codex CLI...");
  setComposerEnabled(false);
  try {
    const status = await host.codexAssistantStatus();
    applyStatus(status);
  } catch (err) {
    assistantReady = false;
    setStatus(getHostErrorMessage(err, "Codex status check failed."), "error");
    setComposerEnabled(false);
  }
}

function openAssistant() {
  void prepareAssistantSession();
  const panel = $("aiAssistantPanel");
  applyFirstSessionOpenPanelSize(panel);
  $("aiAssistantLauncher")?.classList.add("assistant-open");
  panel?.classList.add("open");
  closeAssistantSettingsPanel();
  refreshAppContextTooltip();
  if (!assistantStatusChecked) refreshAssistantStatus();
  setTimeout(() => $("aiAssistantInput")?.focus(), 0);
}

// A page hands ArcBot a question: the panel opens with the text in the composer, ready to edit.
// Sending stays the user's own act, as it is for dictated text.
export function askAiAssistant(text) {
  const prompt = String(text || "").trim();
  if (!isAiAssistantLauncherVisible()) setAiAssistantLauncherVisible(true);
  openAssistant();
  const input = $("aiAssistantInput");
  if (!input || !prompt) return;
  input.value = prompt;
  autoGrowAssistantInput();
  setTimeout(() => input.setSelectionRange(prompt.length, prompt.length), 0);
}

function closeAssistant() {
  assistantVoice?.stop();
  if (isAiAssistantLauncherVisible()) $("aiAssistantLauncher")?.classList.remove("assistant-open");
  $("aiAssistantPanel")?.classList.remove("open");
  closeAssistantSettingsPanel();
}

function closeModeMenu() {
  const button = $("aiAssistantModeButton");
  $("aiAssistantModeMenu")?.classList.remove("open");
  button?.setAttribute("aria-expanded", "false");
}

function closeSelectMenus() {
  closeModeMenu();
}

function toggleModeMenu(forceOpen) {
  const button = $("aiAssistantModeButton");
  const menu = $("aiAssistantModeMenu");
  if (!button || !menu) return;
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : !menu.classList.contains("open");
  menu.classList.toggle("open", shouldOpen);
  button.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function getLauncherDefaultPosition(launcher) {
  const rect = launcher.getBoundingClientRect();
  const width = rect.width || 42;
  const height = rect.height || 42;
  const statusbarHeight = Number(shell.getStatusBarHeight?.() || 0);
  return {
    left: window.innerWidth - width - 18,
    top: window.innerHeight - statusbarHeight - height - 18,
  };
}

function readLauncherPosition() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ASSISTANT_LAUNCHER_POSITION_KEY) || "null");
    if (parsed && Number.isFinite(parsed.left) && Number.isFinite(parsed.top)) return parsed;
  } catch {}
  return null;
}

function loadLauncherPosition(launcher) {
  const parsed = readLauncherPosition();
  if (parsed) return adaptLauncherPositionToWindow(launcher, parsed);
  return getLauncherDefaultPosition(launcher);
}

function saveLauncherPosition(launcher, left, top) {
  const tucked = getLauncherTuckedEdges(launcher, left, top);
  const anchor = getLauncherResizeAnchor(launcher, left, top, tucked);
  const payload = {
    left: Math.round(left),
    top: Math.round(top),
    tuckedX: tucked.x,
    tuckedY: tucked.y,
  };
  if (anchor) {
    payload.anchorCornerX = anchor.cornerX;
    payload.anchorCornerY = anchor.cornerY;
    payload.anchorOffsetX = anchor.offsetX;
    payload.anchorOffsetY = anchor.offsetY;
  }
  try {
    localStorage.setItem(ASSISTANT_LAUNCHER_POSITION_KEY, JSON.stringify(payload));
  } catch {}
}

function getLauncherMetrics(launcher) {
  const rect = launcher.getBoundingClientRect();
  const width = rect.width || 42;
  const height = rect.height || 42;
  const statusbarHeight = Number(shell.getStatusBarHeight?.() || 0);
  return {
    width,
    height,
    halfWidth: Math.round(width / 2),
    halfHeight: Math.round(height / 2),
    viewportWidth: Math.max(0, window.innerWidth),
    viewportHeight: Math.max(0, window.innerHeight - statusbarHeight),
  };
}

function getLauncherTuckedEdges(launcher, left, top) {
  const metrics = getLauncherMetrics(launcher);
  return {
    x: left < 0 ? "left" : (left + metrics.width > metrics.viewportWidth ? "right" : ""),
    y: top < 0 ? "top" : (top + metrics.height > metrics.viewportHeight ? "bottom" : ""),
  };
}

function getLauncherResizeAnchor(launcher, left, top, tucked) {
  if (!tucked?.x && !tucked?.y) return null;
  const metrics = getLauncherMetrics(launcher);
  const centerX = left + metrics.halfWidth;
  const centerY = top + metrics.halfHeight;
  const cornerX = tucked.x || (centerX <= metrics.viewportWidth / 2 ? "left" : "right");
  const cornerY = tucked.y || (centerY <= metrics.viewportHeight / 2 ? "top" : "bottom");
  return {
    cornerX,
    cornerY,
    offsetX: Math.round(Math.max(0, cornerX === "right" ? metrics.viewportWidth - centerX : centerX)),
    offsetY: Math.round(Math.max(0, cornerY === "bottom" ? metrics.viewportHeight - centerY : centerY)),
  };
}

function adaptLauncherPositionToWindow(launcher, position) {
  const metrics = getLauncherMetrics(launcher);
  let left = Number(position?.left || 0);
  let top = Number(position?.top || 0);
  const hasAnchor = ["left", "right"].includes(position?.anchorCornerX)
    && ["top", "bottom"].includes(position?.anchorCornerY)
    && Number.isFinite(position?.anchorOffsetX)
    && Number.isFinite(position?.anchorOffsetY);
  if (hasAnchor && (position?.tuckedX || position?.tuckedY)) {
    let centerX = position.anchorCornerX === "right"
      ? metrics.viewportWidth - Math.max(0, Number(position.anchorOffsetX))
      : Math.max(0, Number(position.anchorOffsetX));
    let centerY = position.anchorCornerY === "bottom"
      ? metrics.viewportHeight - Math.max(0, Number(position.anchorOffsetY))
      : Math.max(0, Number(position.anchorOffsetY));
    if (position.tuckedX === "left") centerX = 0;
    else if (position.tuckedX === "right") centerX = metrics.viewportWidth;
    if (position.tuckedY === "top") centerY = 0;
    else if (position.tuckedY === "bottom") centerY = metrics.viewportHeight;
    left = centerX - metrics.halfWidth;
    top = centerY - metrics.halfHeight;
  } else {
    if (position?.tuckedX === "left") left = -metrics.halfWidth;
    else if (position?.tuckedX === "right") left = metrics.viewportWidth - metrics.halfWidth;
    if (position?.tuckedY === "top") top = -metrics.halfHeight;
    else if (position?.tuckedY === "bottom") top = metrics.viewportHeight - metrics.halfHeight;
  }
  return { left, top };
}

function clampLauncherPosition(launcher, left, top, options = {}) {
  const { snap = true } = options;
  const metrics = getLauncherMetrics(launcher);
  const fullMaxLeft = Math.max(0, metrics.viewportWidth - metrics.width);
  const fullMaxTop = Math.max(0, metrics.viewportHeight - metrics.height);
  let nextLeft = Math.min(Math.max(left, -metrics.halfWidth), metrics.viewportWidth - metrics.halfWidth);
  let nextTop = Math.min(Math.max(top, -metrics.halfHeight), metrics.viewportHeight - metrics.halfHeight);
  if (snap) {
    if (nextLeft < 0) nextLeft = -metrics.halfWidth;
    else if (nextLeft > fullMaxLeft) nextLeft = metrics.viewportWidth - metrics.halfWidth;
    if (nextTop < 0) nextTop = -metrics.halfHeight;
    else if (nextTop > fullMaxTop) nextTop = metrics.viewportHeight - metrics.halfHeight;
  }
  return {
    left: nextLeft,
    top: nextTop,
  };
}

function updateLauncherTuckedState(launcher, left, top) {
  const tucked = getLauncherTuckedEdges(launcher, left, top);
  const nearLeft = tucked.x === "left";
  const nearRight = tucked.x === "right";
  const nearTop = tucked.y === "top";
  const nearBottom = tucked.y === "bottom";
  launcher.classList.toggle("tucked", nearLeft || nearRight || nearTop || nearBottom);
  launcher.classList.toggle("tucked-left", nearLeft);
  launcher.classList.toggle("tucked-right", nearRight);
  launcher.classList.toggle("tucked-top", nearTop);
  launcher.classList.toggle("tucked-bottom", nearBottom);
}

function applyLauncherPosition(launcher, position, options = {}) {
  const next = clampLauncherPosition(launcher, Number(position?.left || 0), Number(position?.top || 0), options);
  launcher.style.left = `${Math.round(next.left)}px`;
  launcher.style.top = `${Math.round(next.top)}px`;
  launcher.style.right = "auto";
  launcher.style.bottom = "auto";
  updateLauncherTuckedState(launcher, next.left, next.top);
  return next;
}

function initAssistantLauncherDrag(launcher) {
  let dragState = null;
  launcher.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const rect = launcher.getBoundingClientRect();
    dragState = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
      moved: false,
    };
    try { launcher.setPointerCapture(event.pointerId); } catch {}
  });

  launcher.addEventListener("pointermove", (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    const dx = event.clientX - dragState.startX;
    const dy = event.clientY - dragState.startY;
    if (!dragState.moved && Math.hypot(dx, dy) < 4) return;
    dragState.moved = true;
    launcher.classList.add("dragging");
    applyLauncherPosition(launcher, {
      left: dragState.left + dx,
      top: dragState.top + dy,
    }, { snap: false });
    event.preventDefault();
  });

  const endDrag = (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    try { launcher.releasePointerCapture(event.pointerId); } catch {}
    launcher.classList.remove("dragging");
    if (dragState.moved) {
      const rect = launcher.getBoundingClientRect();
      const next = applyLauncherPosition(launcher, { left: rect.left, top: rect.top });
      saveLauncherPosition(launcher, next.left, next.top);
      suppressLauncherClick = true;
      setTimeout(() => { suppressLauncherClick = false; }, 150);
    }
    dragState = null;
  };

  launcher.addEventListener("pointerup", endDrag);
  launcher.addEventListener("pointercancel", endDrag);
  window.addEventListener("resize", () => {
    if (!isAiAssistantLauncherVisible()) return;
    const next = applyLauncherPosition(launcher, loadLauncherPosition(launcher));
    saveLauncherPosition(launcher, next.left, next.top);
  });
}

function clampPanelPosition(panel, left, top) {
  const margin = 8;
  const rect = panel.getBoundingClientRect();
  const width = rect.width || 420;
  const height = rect.height || 420;
  const maxLeft = Math.max(margin, window.innerWidth - width - margin);
  const maxTop = Math.max(margin, window.innerHeight - height - margin);
  return {
    left: Math.min(Math.max(margin, left), maxLeft),
    top: Math.min(Math.max(margin, top), maxTop),
  };
}

function readPanelSize() {
  try {
    const parsed = JSON.parse(localStorage.getItem(ASSISTANT_PANEL_SIZE_KEY) || "null");
    if (parsed && Number.isFinite(parsed.width) && Number.isFinite(parsed.height)) return parsed;
  } catch {}
  return null;
}

function savePanelSize(panel) {
  if (!panel) return;
  const rect = panel.getBoundingClientRect();
  try {
    localStorage.setItem(ASSISTANT_PANEL_SIZE_KEY, JSON.stringify({
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    }));
  } catch {}
}

function hasOpenedPanelThisSession() {
  try {
    return sessionStorage.getItem(ASSISTANT_PANEL_OPENED_SESSION_KEY) === "1";
  } catch {
    return false;
  }
}

function markPanelOpenedThisSession() {
  try {
    sessionStorage.setItem(ASSISTANT_PANEL_OPENED_SESSION_KEY, "1");
  } catch {}
}

function clampPanelSize(width, height) {
  const statusbarHeight = Number(shell.getStatusBarHeight?.() || 0);
  const minWidth = parseFloat(getComputedStyle($("aiAssistantPanel")).minWidth);
  const maxWidth = Math.max(minWidth, window.innerWidth - 16);
  const maxHeight = Math.max(340, window.innerHeight - statusbarHeight - 16);
  return clampAssistantPanelSize(width, height, {
    minWidth,
    minHeight: 340,
    maxWidth,
    maxHeight,
    fallbackWidth: minWidth,
    fallbackHeight: ASSISTANT_PANEL_DEFAULT_HEIGHT,
  });
}

function applyPanelSize(panel, size = readPanelSize()) {
  if (!panel || !size) return;
  const next = clampPanelSize(size.width, size.height);
  panel.style.width = `${Math.round(next.width)}px`;
  panel.style.height = `${Math.round(next.height)}px`;
}

function applyFirstSessionOpenPanelSize(panel) {
  if (!panel || hasOpenedPanelThisSession()) return;
  const saved = readPanelSize();
  const rect = panel.getBoundingClientRect();
  applyPanelSize(panel, {
    width: undefined,
    height: saved?.height || rect.height || ASSISTANT_PANEL_DEFAULT_HEIGHT,
  });
  markPanelOpenedThisSession();
}

function applyPanelPosition(panel, left, top) {
  const next = clampPanelPosition(panel, left, top);
  panel.style.left = `${Math.round(next.left)}px`;
  panel.style.top = `${Math.round(next.top)}px`;
  panel.style.right = "auto";
  panel.style.bottom = "auto";
}

function initAssistantResize(panel) {
  const handles = Array.from(document.querySelectorAll(".aiAssistantResizeHandle"));
  if (!handles.length) return;
  applyPanelSize(panel);
  let resizeState = null;

  const startResize = (event) => {
    if (event.button !== 0) return;
    const handle = event.currentTarget;
    const rect = panel.getBoundingClientRect();
    resizeState = {
      pointerId: event.pointerId,
      edge: String(handle?.dataset?.resizeEdge || "se"),
      startX: event.clientX,
      startY: event.clientY,
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    };
    try { handle.setPointerCapture(event.pointerId); } catch {}
    event.preventDefault();
  };

  const moveResize = (event) => {
    if (!resizeState || resizeState.pointerId !== event.pointerId) return;
    const dx = event.clientX - resizeState.startX;
    const dy = event.clientY - resizeState.startY;
    const edge = resizeState.edge;
    let width = resizeState.width;
    let height = resizeState.height;
    let left = resizeState.left;
    let top = resizeState.top;
    if (edge.includes("e")) width = resizeState.width + dx;
    if (edge.includes("w")) width = resizeState.width - dx;
    if (edge.includes("s")) height = resizeState.height + dy;
    if (edge.includes("n")) height = resizeState.height - dy;
    const next = clampPanelSize(width, height);
    if (edge.includes("w")) left = resizeState.left + resizeState.width - next.width;
    if (edge.includes("n")) top = resizeState.top + resizeState.height - next.height;
    applyPanelSize(panel, next);
    applyPanelPosition(panel, left, top);
  };

  const stopResize = (event) => {
    if (!resizeState || resizeState.pointerId !== event.pointerId) return;
    try { event.currentTarget?.releasePointerCapture?.(event.pointerId); } catch {}
    savePanelSize(panel);
    resizeState = null;
  };

  handles.forEach((handle) => {
    handle.addEventListener("pointerdown", startResize);
    handle.addEventListener("pointermove", moveResize);
    handle.addEventListener("pointerup", stopResize);
    handle.addEventListener("pointercancel", stopResize);
  });
}

function initAssistantDrag(panel) {
  const header = $("aiAssistantHeader");
  if (!header) return;
  let dragState = null;

  header.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (event.target?.closest?.("button")) return;
    const rect = panel.getBoundingClientRect();
    dragState = {
      pointerId: event.pointerId,
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    try { header.setPointerCapture(event.pointerId); } catch {}
    event.preventDefault();
  });

  header.addEventListener("pointermove", (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    applyPanelPosition(panel, event.clientX - dragState.offsetX, event.clientY - dragState.offsetY);
  });

  const stopDrag = (event) => {
    if (!dragState || dragState.pointerId !== event.pointerId) return;
    try { header.releasePointerCapture(event.pointerId); } catch {}
    dragState = null;
  };

  header.addEventListener("pointerup", stopDrag);
  header.addEventListener("pointercancel", stopDrag);
  window.addEventListener("resize", () => {
    if (!panel.classList.contains("open")) return;
    const rect = panel.getBoundingClientRect();
    applyPanelPosition(panel, rect.left, rect.top);
  });
}

async function installCodexCli() {
  const host = getHostApi();
  if (!host?.codexAssistantInstall) return;
  assistantInstallJustSucceeded = false;
  const confirmed = window.confirm(
    `Install or repair Codex CLI now?\n\n${assistantConfig.appName} will install a per-user copy without changing system-wide npm settings.`
  );
  if (!confirmed) return;
  assistantBusy = true;
  setStatus("Installing Codex CLI...");
  setSetup({ open: false });
  setComposerEnabled(false);
  try {
    const result = await host.codexAssistantInstall();
    if (!result?.ok) {
      setStatus(result?.error || "Codex CLI installation failed.", "error");
      setSetup({
        open: true,
        install: true,
        installLabel: "Retry",
        login: false,
        text: result?.error || "The per-user Codex CLI install failed.",
      });
      return;
    }
    shell.updateStatusBar?.("Codex CLI installed.");
    assistantInstallJustSucceeded = true;
    await refreshAssistantStatus();
  } catch (err) {
    setStatus(String(err?.message || err || "Codex CLI installation failed."), "error");
  } finally {
    assistantBusy = false;
    setComposerEnabled(assistantReady);
  }
}

async function loginCodexCli() {
  const host = getHostApi();
  if (!host?.codexAssistantLogin || assistantLoginPending) return;
  const usingClaude = isClaudeModel();
  const confirmed = window.confirm(
    usingClaude
      ? "Open Claude sign-in now?\n\nA terminal window will run: claude auth login"
      : "Open Codex sign-in now?\n\nA terminal window will run: codex login"
  );
  if (!confirmed) return;
  // The first Claude sign-in installs the CLI first, so the window can take a minute to appear.
  assistantLoginPending = true;
  const loginBtn = $("aiAssistantLoginBtn");
  if (loginBtn) loginBtn.disabled = true;
  setStatus(usingClaude
    ? "Opening Claude sign-in... The first time can take a minute while the Claude CLI installs."
    : "Opening Codex sign-in...");
  try {
    // Signs in the account chosen in Settings; ArcBot notices when the window finishes.
    const result = await host.codexAssistantLogin({ provider: usingClaude ? "anthropic" : "openai" });
    if (!result?.ok) {
      setStatus(result?.error || `Could not start ${usingClaude ? "Claude" : "Codex"} sign-in.`, "error");
      return;
    }
    setStatus(`Finish ${usingClaude ? "Claude" : "Codex"} sign-in in the new window.`);
    void assistantAccounts?.refresh();
  } catch (err) {
    setStatus(String(err?.message || err || `Could not start ${usingClaude ? "Claude" : "Codex"} sign-in.`), "error");
  } finally {
    assistantLoginPending = false;
    if (loginBtn) loginBtn.disabled = false;
  }
}

async function cancelAssistantMessage() {
  if (!assistantBusy || !currentRequestId || assistantCancelRequested) return;
  const host = getHostApi();
  assistantCancelRequested = true;
  setComposerEnabled(false);
  appendActivity("Cancel requested", "activity");
  setStatus("Canceling ArcBot request...");
  try {
    if (!host?.codexAssistantCancel) throw new Error("ArcBot cancel is not available.");
    const result = await host.codexAssistantCancel(currentRequestId);
    if (!result?.ok && assistantHostRequestSubmitted) {
      setStatus(result?.error || "Could not cancel ArcBot request.", "error");
    }
  } catch (err) {
    setStatus(String(err?.message || err || "Could not cancel ArcBot request."), "error");
  }
}

// `skill` starts a server skill: the turn carries its id and a fixed request in place of typed text.
async function sendAssistantMessage({ skill = null } = {}) {
  if (assistantBusy) return;
  assistantVoice?.stop();
  const host = getHostApi();
  const input = $("aiAssistantInput");
  const text = skill ? `Run the ${skill.title} skill.` : String(input?.value || "").trim();
  if ((!text && !assistantAttachments.length) || !host?.codexAssistantSend) return;
  if (!assistantReady) {
    setStatus("Install Codex CLI or sign in before sending.", "error");
    return;
  }
  const runToken = assistantRunGate.tryAcquire("chat");
  if (!runToken) return;
  assistantBusy = true;
  setComposerEnabled(false);
  try {
    if (!currentSessionId) await ensureAssistantSession();
  } catch (err) {
    assistantRunGate.release(runToken);
    assistantBusy = false;
    setComposerEnabled(assistantReady);
    setStatus(String(err?.message || err || "Could not create the ArcBot session."), "error");
    return;
  }

  const userText = text || "Use the attached file context.";
  const requestAttachments = assistantAttachments.map((attachment) => ({ ...attachment }));
  const visibleText = requestAttachments.length
    ? `${userText}\n\nAttached: ${requestAttachments.map((item) => item.name).join(", ")}`
    : userText;
  assistantMessages.push({ role: "user", content: visibleText, timestamp: nowIso() });
  appendMessage("user", visibleText);
  currentSessionTitle = assistantMessages.find((message) => message.role === "user")?.content?.slice(0, 42) || currentSessionTitle;
  updateAssistantSettingsPanel();
  if (input) input.value = "";
  assistantAttachments = [];
  renderAssistantAttachments();
  autoGrowAssistantInput();
  currentRequestId = `arcbot_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  preparationGeneration += 1;
  setText($("aiAssistantSessionStatus"), "");
  setComposerEnabled(false);
  currentWorkCardEl = null;
  currentRunStartedAt = performance.now();
  currentStepStartedAt = currentRunStartedAt;
  assistantProgressSteps = createAssistantProgressSteps();
  assistantWorkCardExpanded = true;
  startAssistantProgressTicker();
  assistantCancelRequested = false;
  assistantHostRequestSubmitted = false;
  assistantActivities = [];
  resetAssistantActivityTyping();
  assistantDebugLogs = [];
  renderActivities();
  renderDebugLog();
  appendActivity(`Reading your request: "${userText.slice(0, 90)}${userText.length > 90 ? "..." : ""}"`, "activity", { elapsedMs: 0 });
  const pending = appendMessage("assistant", "Thinking ...");
  pending?.classList.add("thinking");
  currentPendingMessageEl = pending;
  currentAssistantStreamText = "";
  try {
    await saveCurrentSession();
    setStatus(assistantAppContextEnabled ? "ArcBot is checking the active page context..." : "ArcBot is responding without app context...");
    appendActivity(
      assistantAppContextEnabled ? "Looking for usable data in the active app tab." : "App Context is off, so Codex will not receive active app contents.",
      "activity",
      { save: false },
    );
    const activeContext = assistantAppContextEnabled
      ? await requestActivePageContext()
      : {
          available: false,
          disabled: true,
          tabType: "off",
          title: "App Context Off",
          targetPath: "",
        };
    const panelActiveTab = shell.state?.tabs?.find?.((tab) => tab.id === shell.state.activeId) || null;
    currentContext = normalizeAssistantContextForPanel(activeContext, panelActiveTab);
    updateContextPanel();
    appendActivity(
      activeContext?.available
        ? formatAssistantContextScanStatus(activeContext)
        : formatAssistantContextScanStatus(activeContext, "No active app tab data was available for this request."),
      "activity",
      { save: false },
    );
    if (assistantCancelRequested) {
      const message = "Request canceled.";
      resolveAssistantPendingMessage(pending, message);
      assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
      appendActivity("Request canceled", "activity");
      failAssistantProgress("Request canceled");
      setStatus("ArcBot request canceled.");
      return;
    }
    setStatus(`ArcBot is responding in ${getModeLabel()}...`);
    assistantHostRequestSubmitted = true;
    const result = !skill && assistantMode === "edit" && isRevertLatestArcBotEditRequest(userText)
      ? await revertLatestArcBotEdit()
      : await host.codexAssistantSend({
          requestId: currentRequestId,
          sessionId: currentSessionId,
          mode: assistantMode,
          model: assistantModel,
          reasoningEffort: assistantReasoningEffort,
          messages: assistantMessages,
          activeContext,
          attachments: requestAttachments,
          ...(skill ? { skillId: skill.id } : {}),
        });
    currentUsage = result?.usage || currentUsage;
    updateContextPanel();
    if (assistantCancelRequested && result?.ok) {
      const message = "Request canceled.";
      resolveAssistantPendingMessage(pending, message);
      assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
      appendActivity("Request canceled", "activity");
      failAssistantProgress("Request canceled");
      setStatus("ArcBot request canceled.");
      return;
    }
    if (!result?.ok) {
      const wasCanceled = !!result?.canceled || assistantCancelRequested;
      const message = wasCanceled ? "Request canceled." : (result?.error || "ArcBot request failed.");
      resolveAssistantPendingMessage(pending, message);
      assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
      if (wasCanceled) {
        setStatus("ArcBot request canceled.");
        appendActivity("Request canceled", "activity");
        failAssistantProgress("Request canceled");
      } else if (result?.needsAuth) {
        assistantReady = false;
        const isClaudeProvider = isClaudeModel();
        setStatus(`${isClaudeProvider ? "Claude" : "Codex CLI"} needs sign-in.`, "error");
        setSetup({
          open: true,
          install: false,
          login: true,
          text: `Sign in to link this computer to your ${isClaudeProvider ? "Claude" : "Codex"} account.`,
        });
      } else if (result?.needsRepair) {
        assistantReady = false;
        setStatus("Codex CLI update required.", "error");
        appendActivity("Codex CLI update required", "error");
        failAssistantProgress(message);
        setSetup({
          open: true,
          install: true,
          installLabel: "Repair",
          login: false,
          text: message,
        });
      } else {
        setStatus(message, "error");
        appendActivity("Request failed", "error");
        failAssistantProgress(message);
      }
      return;
    }
    let reply = String(result?.text || "").trim() || "No response.";
    let editApplied = false;
    let editFailed = false;
    if (result?.editProposed) {
      const edit = { tabId: activeContext?.tabId || "", targetPath: result.targetPath || "" };
      const editPayload = {
        targetPath: edit.targetPath,
        originalJson: result.originalJson || null,
        proposedJson: result.proposedJson || null,
        proposedText: result.proposedText || "",
      };
      if (result.editPendingApproval && assistantConfig.enableDfmApproval) {
        appendActivity("Opening DFM version compare for approval.", "activity");
        setStatus("Review the proposed DFM edit before accepting it...");
        const approval = await requestPageArcBotEdit(edit.tabId, "dfm-edit-approval", { ...editPayload, reply: reply });
        if (approval?.ok && approval.accepted) {
          editApplied = true;
          reply = approval.message || reply || "Applied the approved DFM edit.";
          appendActivity("Approved and applied DFM edit.", "activity");
        } else if (approval?.ok && approval.accepted === false) {
          reply = approval.message || "DFM edit was rejected. No changes were applied.";
          appendActivity("Rejected DFM edit. No changes were applied.", "activity");
        } else {
          editFailed = true;
          reply = approval?.error || "DFM edit approval failed. No changes were applied.";
          appendActivity("DFM edit approval failed.", "error");
        }
        if (editApplied || approval?.applied) lastArcBotEdit = edit;
      } else {
        appendActivity("Waiting for the page to apply the edit.", "activity");
        const applied = await requestPageArcBotEdit(edit.tabId, "apply-json-edit", editPayload);
        if (applied?.ok) {
          editApplied = true;
          if (applied.message) reply = `${reply}\n\n${applied.message}`;
        } else {
          editFailed = true;
          reply = applied?.error || "The page could not apply ArcBot's edit. Nothing was changed.";
          appendActivity("The page did not apply the edit.", "error");
        }
        if (editApplied || applied?.applied) lastArcBotEdit = edit;
      }
    }
    await resolveAssistantPendingMessage(pending, reply, { animate: !currentAssistantStreamText });
    assistantMessages.push({ role: "assistant", content: reply, timestamp: nowIso() });
    appendActivity(editApplied ? "Edit completed." : "Response completed.", "activity");
    completeAssistantProgress(editApplied ? "Edit applied" : "Response completed");
    setStatus(
      editFailed
        ? "ArcBot edit was not completed."
        : editApplied ? "ArcBot edit completed." : `${isClaudeModel() ? getAssistantModelLabel() : "Codex"} ready. ${getModeLabel()}.`,
      editFailed ? "error" : "",
    );
  } catch (err) {
    const message = assistantCancelRequested ? "Request canceled." : String(err?.message || err || "ArcBot request failed.");
    resolveAssistantPendingMessage(pending, message);
    assistantMessages.push({ role: "assistant", content: message, timestamp: nowIso() });
    appendActivity(assistantCancelRequested ? "Request canceled" : "Request failed", assistantCancelRequested ? "activity" : "error");
    failAssistantProgress(message);
    setStatus(message, assistantCancelRequested ? "" : "error");
  } finally {
    currentRequestId = "";
    currentRunStartedAt = 0;
    currentStepStartedAt = 0;
    assistantWorkCardExpanded = false;
    stopAssistantProgressTicker();
    renderActivities();
    currentPendingMessageEl = null;
    currentAssistantStreamText = "";
    try {
      await saveCurrentSession();
      await refreshSessionList(currentSessionId);
    } finally {
      if (assistantRunGate.release(runToken)) assistantBusy = false;
      assistantCancelRequested = false;
      assistantHostRequestSubmitted = false;
      setComposerEnabled(assistantReady);
      void prepareAssistantSession();
    }
  }
}

// The model's running thinking-token estimate for the current request, when it reports one.
let assistantThinkingTokens = { requestId: "", tokens: 0 };

function getAssistantThinkingLabel() {
  const tokens = assistantThinkingTokens.requestId === currentRequestId ? assistantThinkingTokens.tokens : 0;
  return tokens ? `Thinking ... ~${tokens.toLocaleString()} tokens` : "Thinking ...";
}

function handleAssistantEvent(event) {
  if (!event || event.requestId !== currentRequestId) return;
  if (event.type === "assistant-reset") {
    currentAssistantStreamText = "";
    if (currentPendingMessageEl) {
      currentPendingMessageEl.textContent = getAssistantThinkingLabel();
      currentPendingMessageEl.classList.add("thinking");
    }
    return;
  }
  if (event.type === "thinking-tokens") {
    assistantThinkingTokens = { requestId: event.requestId, tokens: Number(event.tokens) || 0 };
    if (currentPendingMessageEl && !currentAssistantStreamText) {
      currentPendingMessageEl.textContent = getAssistantThinkingLabel();
    }
    return;
  }
  if (["command", "command-output", "commentary", "thinking"].includes(event.type)) {
    const existing = event.itemId && assistantActivities.find(item => item.itemId === event.itemId);
    if (existing) {
      existing.text = event.type === "command-output" ? existing.text + event.text : event.text;
      existing.rawText = existing.text;
      renderActivities();
    } else {
      appendActivity(event.text, event.type, { save: false });
      if (assistantActivities.length) assistantActivities.at(-1).itemId = event.itemId;
    }
    return;
  }
  if (event.type === "assistant-delta") {
    const delta = String(event.text || "");
    if (!delta || !currentPendingMessageEl) return;
    if (!currentAssistantStreamText) currentPendingMessageEl.textContent = "";
    currentAssistantStreamText += delta;
    currentPendingMessageEl.classList.remove("thinking", "typing");
    currentPendingMessageEl.append(document.createTextNode(delta));
    scrollMessagesToBottom();
    return;
  }
  if (event.type === "stdout") {
    appendDebugLog(event.text, "stdout");
    return;
  }
  if (event.type === "stderr") {
    appendDebugLog(event.text, "stderr");
    return;
  }
  if (event.type === "usage") {
    currentUsage = event.usage || currentUsage;
    updateContextPanel();
    appendDebugLog(event.text, "usage");
    return;
  }
  if (event.type === "context" && event.context) {
    currentContext = { ...(currentContext || {}), ...event.context };
    updateContextPanel();
    appendActivity(formatAssistantContextScanStatus(event.context), "activity");
    appendDebugLog(`${event.text}\n${JSON.stringify(event.context, null, 2)}`, "context");
    return;
  }
  const text = String(event.text || "").trim();
  if (!text) return;
  appendDebugLog(text, event.type || "activity");
  if (event.debugText) appendDebugLog(event.debugText, "debug");
  const displayText = formatAssistantActivityForCard(text, event);
  if (displayText) appendActivity(text, event.type || "activity", { displayText });
}

export function initAiAssistant() {
  ensureAiAssistantDom(assistantConfig);
  const launcher = $("aiAssistantLauncher");
  const panel = $("aiAssistantPanel");
  const composer = $("aiAssistantComposer");
  if (!launcher || !panel || !composer) return;
  installAssistantSelectMenu($("aiAssistantSettingsModelSelect"));
  installAssistantSelectMenu($("aiAssistantSettingsReasoningSelect"));
  assistantAccounts = installAssistantAccounts({
    container: $("aiAssistantAccountFields"),
    getHost: getHostApi,
    onChanged: () => void handleAssistantAccountChange(),
    onActive: handleAssistantAccountActive,
  });
  const host = getHostApi();
  if (!host) {
    launcher.style.display = "none";
    return;
  }
  const sessionStatus = document.createElement("span");
  sessionStatus.id = "aiAssistantSessionStatus";
  sessionStatus.setAttribute("role", "status");
  $("aiAssistantComposerTop")?.before(sessionStatus);
  addComposerTip($("aiAssistantAttachBtn"), "Attach files");
  assistantVoice = installVoiceInput({ host, input: $("aiAssistantInput"), controls: $("aiAssistantComposerControls"), onInput: autoGrowAssistantInput, getSessionId: () => currentSessionId });
  window.addEventListener("pagehide", () => { void host.codexAssistantRelease?.(); });
  panel.addEventListener("pointerdown", bringAssistantPanelToFront);
  panel.addEventListener("focusin", bringAssistantPanelToFront);
  ensureAssistantSkillDom();
  setAiAssistantLauncherVisible(isAiAssistantLauncherVisible(), { save: false });
  void loadAssistantUiSettings();
  const modelBootstrap = refreshAssistantModels({ promoteEmptyDefault: true });
  const sessionBootstrap = ensureAssistantSession();
  void Promise.allSettled([modelBootstrap, sessionBootstrap]).then(() => {
    if (
      assistantModelCatalogChecked
      && assistantModelDefaultVerified
      && assistantModel === "codex"
      && assistantMessages.length === 0
    ) {
      setAssistantModel(getDefaultAssistantModel(), {
        save: !!currentSessionId,
        refreshStatus: false,
        defaultEffort: true,
      });
    }
  });
  host.onCodexAssistantEvent?.(handleAssistantEvent);

  launcher.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!isAiAssistantLauncherVisible()) return;
    openAssistantLauncherContextMenu(event);
  });
  launcher.addEventListener("click", (event) => {
    if (suppressLauncherClick) {
      event.preventDefault();
      return;
    }
    if (panel.classList.contains("open")) closeAssistant();
    else openAssistant();
  });
  $("aiAssistantCloseBtn")?.addEventListener("click", closeAssistant);
  $("aiAssistantRefreshBtn")?.addEventListener("click", refreshAssistantStatus);
  $("aiAssistantSetupBtn")?.addEventListener("click", installCodexCli);
  $("aiAssistantLoginBtn")?.addEventListener("click", loginCodexCli);
  $("aiAssistantAttachBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAttachMenu();
  });
  $("aiAssistantAttachFileOption")?.addEventListener("click", attachAssistantContextFile);
  $("aiAssistantNewChatBtn")?.addEventListener("click", async () => {
    const result = await openOrCreateEmptyAssistantSession();
    if (!result?.ok) return;
    closeHistoryPage();
    setStatus(result?.created
      ? "New ArcBot chat started."
      : result?.alreadyCurrent
        ? "ArcBot is already on an empty chat."
        : "Opened existing empty ArcBot chat.");
  });
  $("aiAssistantHistoryBtn")?.addEventListener("click", () => {
    const page = $("aiAssistantHistoryPage");
    if (page?.classList.contains("open")) closeHistoryPage();
    else openHistoryPage();
  });
  $("aiAssistantHistoryCloseBtn")?.addEventListener("click", () => {
    closeHistoryPage();
  });
  $("aiAssistantAppContextBtn")?.addEventListener("click", async () => {
    setAssistantAppContextEnabled(!assistantAppContextEnabled);
    if (assistantAppContextEnabled) {
      const activeContext = await requestActivePageContext();
      currentContext = normalizeAssistantContextForPanel(activeContext);
      updateContextPanel();
    }
    refreshAppContextTooltip({ probe: assistantAppContextEnabled });
  });
  $("aiAssistantAppContextBtn")?.addEventListener("mouseenter", () => {
    const tooltip = $("aiAssistantAppContextTooltip");
    if (tooltip) {
      renderAppContextTooltip(tooltip, getActiveTabPreviewContext());
      tooltip.classList.add("open");
    }
    refreshAppContextTooltip({ probe: assistantAppContextEnabled });
  });
  $("aiAssistantAppContextBtn")?.addEventListener("mouseleave", () => {
    $("aiAssistantAppContextTooltip")?.classList.remove("open");
  });
  $("aiAssistantDebugBtn")?.addEventListener("click", () => {
    const panel = $("aiAssistantDebugPanel");
    const open = !panel?.classList.contains("open");
    closeAssistantSettingsPanel();
    panel?.classList.toggle("open", open);
    $("aiAssistantDebugBtn")?.setAttribute("aria-expanded", open ? "true" : "false");
    renderDebugLog();
  });
  $("aiAssistantSettingsBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleAssistantSettingsPanel();
  });
  $("aiAssistantFolderPermissionsBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    openFolderPermissionsPage();
  });
  $("aiAssistantFolderPermissionsCloseBtn")?.addEventListener("click", () => {
    closeFolderPermissionsPage();
  });
  $("aiAssistantFolderAddBtn")?.addEventListener("click", () => {
    addAssistantReadableRoot();
  });
  $("aiAssistantPromptGuideBtn")?.addEventListener("click", (event) => {
    event.stopPropagation();
    openAssistantPromptGuide();
  });
  $("aiAssistantSettingsModelSelect")?.addEventListener("change", (event) => {
    const previousModel = assistantModel;
    setAssistantModel(event.target?.value);
    if (assistantModel !== previousModel) noticeAssistantModelSwitch();
  });
  $("aiAssistantSettingsReasoningSelect")?.addEventListener("change", (event) => {
    setAssistantReasoningEffort(event.target?.value);
  });
  $("aiAssistantCopyDebugBtn")?.addEventListener("click", async () => {
    const text = $("aiAssistantDebugLog")?.textContent || "";
    try {
      await navigator.clipboard.writeText(text);
      setStatus("ArcBot debug log copied.");
    } catch {
      setStatus("Could not copy ArcBot debug log.", "error");
    }
  });
  $("aiAssistantModeButton")?.addEventListener("click", (event) => {
    event.stopPropagation();
    closeAttachMenu();
    toggleModeMenu();
  });
  $("aiAssistantReviewModeOption")?.addEventListener("click", () => {
    closeModeMenu();
    setAssistantMode("review");
  });
  $("aiAssistantApprovalModeOption")?.addEventListener("click", () => {
    closeModeMenu();
    setAssistantMode("approve");
  });
  $("aiAssistantEditModeOption")?.addEventListener("click", (event) => {
    event.preventDefault();
    closeModeMenu();
    setAssistantMode("edit");
  });
  composer.addEventListener("submit", (event) => {
    event.preventDefault();
    if (assistantBusy) {
      cancelAssistantMessage();
    } else {
      sendAssistantMessage();
    }
  });
  $("aiAssistantInput")?.addEventListener("keydown", (event) => {
    if (assistantSkillMenuOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveAssistantSkillSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveAssistantSkillSelection(-1);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeAssistantSkillMenu();
        return;
      }
      if ((event.key === "Enter" || event.key === "Tab") && activateSelectedAssistantSkill()) {
        event.preventDefault();
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!assistantBusy) sendAssistantMessage();
    }
  });
  $("aiAssistantInput")?.addEventListener("input", () => {
    autoGrowAssistantInput();
    updateAssistantSkillMenuFromInput();
  });
  autoGrowAssistantInput();

  document.addEventListener("pointerdown", (event) => {
    if (!event.target?.closest?.("#aiAssistantSettingsPanel") &&
        !event.target?.closest?.("#aiAssistantSettingsBtn")) {
      closeAssistantSettingsPanel();
    }
    if (!event.target?.closest?.("#aiAssistantLauncherContextMenu") &&
        !event.target?.closest?.("#aiAssistantLauncher")) {
      closeAssistantLauncherContextMenu();
    }
    if (event.target?.closest?.(".aiAssistantSelectWrap")) return;
    if (event.target?.closest?.("#aiAssistantAttachMenu") || event.target?.closest?.("#aiAssistantAttachBtn")) return;
    if (!event.target?.closest?.("#aiAssistantSkillsMenu") && !event.target?.closest?.("#aiAssistantInput")) {
      closeAssistantSkillMenu();
    }
    closeSelectMenus();
    closeAttachMenu();
  }, true);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSqlReviewDialog();
      closeAssistantLauncherContextMenu();
      closeAssistantSkillMenu();
      closeFolderPermissionsPage();
      closeAssistantSettingsPanel();
      closeSelectMenus();
      closeAttachMenu();
    }
  }, true);
  window.addEventListener("resize", () => {
    closeAssistantLauncherContextMenu();
    clampOpenSqlReviewDialogToViewport();
  });
  initAssistantDrag(panel);
  initAssistantResize(panel);
  initAssistantLauncherDrag(launcher);
  setAssistantAppContextEnabled(true);
  const tokenAlert = $("aiAssistantTokenAlert");
  if (tokenAlert) {
    tokenAlert.textContent = "Higher reasoning or thinking effort can use significantly more tokens per request.";
  }
  setAssistantModel(assistantModel, { save: false });
  setAssistantReasoningEffort(assistantReasoningEffort, { save: false });
  renderAssistantAttachments();
  loadAssistantReadableRoots();
  loadAssistantUserAvatarName();
  setComposerEnabled(false);
}
