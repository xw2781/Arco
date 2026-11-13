import { $, getHostApi, shell } from "../shell/shell_context.js?v=20260510a";
import {
  askAiAssistant,
  configureAiAssistant,
  initAiAssistant as initSharedAiAssistant,
  isAiAssistantLauncherVisible,
  setAiAssistantLauncherVisible,
  toggleAiAssistantLauncherVisible,
} from "./index.js?v=20260927smb24";

function cleanText(value) {
  return String(value || "").trim();
}

function getArcRhoAppContextTooltipRows(context, fallback = {}) {
  const ctx = context && typeof context === "object" ? context : {};
  if (ctx.tabType !== "project_instance") return null;

  const fields = ctx.fields && typeof ctx.fields === "object" ? ctx.fields : {};
  const projectInstance = ctx.projectInstance && typeof ctx.projectInstance === "object" ? ctx.projectInstance : {};
  const activeWindow = ctx.activeNestedWindow && typeof ctx.activeNestedWindow === "object" ? ctx.activeNestedWindow : null;
  const visibleWindows = Array.isArray(ctx.openNestedWindows) ? ctx.openNestedWindows : [];
  const nestedType = cleanText(ctx.nestedPageType || activeWindow?.kind).toLowerCase();
  const project = cleanText(fields.project || projectInstance.projectName || ctx.projectName || fallback.title?.split(":")[0]);
  const path = cleanText(projectInstance.selectedPath || fields.reservingClass || activeWindow?.path || fallback.path);
  const state = cleanText(fallback.state || ctx.fileState || (ctx.dirty ? "unsaved-changes" : ""));
  const methodName = cleanText(fields.methodName || activeWindow?.name);
  const methodType = cleanText(activeWindow?.methodType) || (nestedType === "dfm" ? "DFM" : "None");

  if (nestedType === "dfm") {
    return [
      { text: "App Context", strong: true },
      project ? { label: "Project", value: project } : null,
      { label: "Path", value: path || "no active path" },
      { label: "Method Name", value: methodName || "no active DFM method" },
      cleanText(ctx.activeDfmTab || activeWindow?.dfmTab) ? { label: "DFM Tab", value: cleanText(ctx.activeDfmTab || activeWindow?.dfmTab) } : null,
      state ? { label: "State", value: state } : null,
    ].filter(Boolean);
  }

  return [
    { text: "App Context", strong: true },
    project ? { label: "Project", value: project } : null,
    { label: "Path", value: path || "no active path" },
    { label: "Active Window", value: cleanText(activeWindow?.name || activeWindow?.title) || "no visible nested window" },
    { label: "Method Type", value: methodType },
    { label: "Visible Windows", value: String(visibleWindows.length) },
    state ? { label: "State", value: state } : null,
  ].filter(Boolean);
}

configureAiAssistant({
  appName: "Arco",
  botName: "ArcBot",
  messageNamespace: "arcrho",
  storagePrefix: "arcrho",
  contextTimeoutMs: 900,
  projectInstanceContextTimeoutMs: 1700,
  enableDfmApproval: true,
  getAppContextTooltipRows: getArcRhoAppContextTooltipRows,
  $,
  getHostApi,
  shell,
});

export function initAiAssistant() {
  return initSharedAiAssistant();
}

export {
  askAiAssistant,
  isAiAssistantLauncherVisible,
  setAiAssistantLauncherVisible,
  toggleAiAssistantLauncherVisible,
};
