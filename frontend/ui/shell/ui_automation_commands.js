// Shell-level UI automation commands for the ArcRho regression harness.
//
// `ui_automation.js` owns the poll loop and the dialog/progress/macro commands. This module owns
// the commands the harness needs to reach a deterministic starting state and to observe or drive
// the shell itself: tab lifecycle, screenshots, synthetic input, and the pointer overlay.
//
// Everything here delegates to APIs already registered on the `shell` object; none of it
// reimplements tab behavior.

// Only `shell_context.js` (which imports nothing) and the pointer overlay are pulled in here.
// Importing `shell_state.js` would drag a large slice of the shell module graph into
// `ui_automation.js`, which `ui_shell.js` loads early - that cycle leaves bindings undefined at
// evaluation time and silently kills the automation poll loop. Read live state off `shell` instead.
import { shell, getHostApi } from "./shell_context.js?v=20260510a";
import {
  movePointer,
  pulsePointer,
  setPointerEnabled,
  isPointerEnabled,
  getPointerPosition,
  withPointerHidden,
} from "./ui_automation_pointer.js?v=20260804a";

const CLICK_TRAVEL_MS = 260;
const CLICK_SETTLE_MS = 60;

function toText(value) {
  return value == null ? "" : String(value).trim();
}

function hostApi() {
  const host = getHostApi();
  if (!host) throw new Error("Electron host API is unavailable; automation requires the desktop app.");
  return host;
}

function tabSummary(tab) {
  if (!tab) return null;
  return {
    id: tab.id,
    type: tab.type,
    title: tab.title,
    isDirty: !!tab.isDirty,
    layout: tab.layout === "floating" ? "floating" : "docked",
    projectName: toText(tab.projectName) || undefined,
  };
}

function listTabs() {
  return {
    activeId: shell.state?.activeId || "",
    tabs: (shell.state?.tabs || []).map(tabSummary).filter(Boolean),
  };
}

function findTab(args = {}) {
  const tabs = shell.state?.tabs || [];
  const id = toText(args.id);
  if (id) return tabs.find((tab) => tab.id === id) || null;
  const type = toText(args.type || args.match);
  const title = toText(args.title);
  if (title) {
    return tabs.find((tab) => toText(tab.title) === title)
      || tabs.find((tab) => toText(tab.title).includes(title))
      || null;
  }
  if (type) {
    // Prefer the active tab when several of the requested type are open, so a scenario that just
    // opened one acts on that one.
    const ofType = tabs.filter((tab) => tab.type === type);
    if (!ofType.length) return null;
    return ofType.find((tab) => tab.id === shell.state?.activeId) || ofType[ofType.length - 1];
  }
  return null;
}

const TAB_OPENERS = {
  project_instance: (args) =>
    shell.openProjectInstanceTab?.(
      {
        name: toText(args.project || args.projectName),
        folder: toText(args.projectFolder),
        tablePath: toText(args.projectTablePath),
      },
      { activate: true }
    ),
  project_settings: () => shell.openProjectSettingsTab?.(),
  dataset: (args) => shell.openDatasetTab?.({ ...(args.options || {}) }),
  dfm: (args) => shell.openDFMTab?.({ ...(args.options || {}) }),
  bornhuetter_ferguson: () => shell.openBornhuetterFergusonTab?.(),
  result_selection: () => shell.openResultSelectionTab?.(),
  workflow: () => shell.openWorkflowTab?.(),
  file_explorer: () => shell.openFileExplorerTab?.(),
  browsing_history: () => shell.openBrowsingHistoryTab?.(),
  dashboard: (args) => shell.openDashboardTab?.({ ...(args.options || {}) }),
  agent_guide: () => shell.openAgentGuideTab?.(),
  task_designer: (args) => shell.openTaskDesigner?.({ ...(args.options || {}) }),
};

function openTab(args = {}) {
  const type = toText(args.type);
  const opener = TAB_OPENERS[type];
  if (!opener) {
    return {
      ok: false,
      error: `Unsupported tab type: ${type || "(none)"}. Known types: ${Object.keys(TAB_OPENERS).sort().join(", ")}.`,
    };
  }
  const before = new Set((shell.state?.tabs || []).map((tab) => tab.id));
  opener(args);
  const after = shell.state?.tabs || [];
  const created = after.find((tab) => !before.has(tab.id)) || null;
  const target = created || after.find((tab) => tab.id === shell.state?.activeId) || null;
  return { ok: true, result: { opened: tabSummary(target), created: !!created, ...listTabs() } };
}

function activateTab(args = {}) {
  const tab = findTab(args);
  if (!tab) return { ok: false, error: "No tab matched the request." };
  shell.setActive?.(tab.id);
  return { ok: true, result: { activated: tabSummary(tab), ...listTabs() } };
}

function closeTab(args = {}) {
  const tab = findTab(args);
  if (!tab) return { ok: false, error: "No tab matched the request." };
  const summary = tabSummary(tab);
  // Default to skipping the confirmation. A native confirm() would block the same event loop the
  // automation poll loop runs on, deadlocking the whole run.
  const skipConfirm = args.skipConfirm !== false;
  shell.closeTab?.(tab.id, skipConfirm);
  const stillOpen = (shell.state?.tabs || []).some((item) => item.id === tab.id);
  return {
    ok: !stillOpen,
    result: { closed: summary, stillOpen, ...listTabs() },
    error: stillOpen ? "Tab did not close; it may be showing a confirmation." : "",
  };
}

async function captureScreenshot(args = {}) {
  const host = hostApi();
  // Hide the pointer glyph first, or it lands in the baseline and every later run diffs on it.
  const payload = await withPointerHidden(() =>
    host.automationCapturePage({
      window: toText(args.window) || undefined,
      windowId: args.windowId,
      rect: args.rect || undefined,
      path: toText(args.path) || undefined,
    })
  );
  if (!payload?.ok) {
    return { ok: false, error: toText(payload?.error) || "Screenshot capture failed." };
  }
  return {
    ok: true,
    result: {
      name: toText(args.name) || "screenshot",
      review: !!args.review,
      path: payload.path || "",
      dataUrl: payload.dataUrl || "",
      width: payload.width,
      height: payload.height,
    },
  };
}

async function sendInput(args = {}) {
  const host = hostApi();
  const events = Array.isArray(args.events) ? args.events : [];
  if (!events.length) return { ok: false, error: "ui.sendInput requires an events array." };
  const payload = await host.automationSendInput({
    window: toText(args.window) || undefined,
    windowId: args.windowId,
    events,
  });
  if (!payload?.ok) return { ok: false, error: toText(payload?.error) || "sendInputEvent failed." };
  return { ok: true, result: { sent: payload.sent } };
}

/**
 * Move the pointer to a point and click it for real. Coordinates are window-relative CSS pixels,
 * normally produced by `page.locate`.
 */
async function clickAt(args = {}) {
  const x = Number(args.x);
  const y = Number(args.y);
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return { ok: false, error: "ui.clickAt requires numeric x and y." };
  }
  const host = hostApi();
  const button = toText(args.button) || "left";
  const clickCount = Math.max(1, Number(args.clickCount) || 1);
  const travelMs = isPointerEnabled() ? Math.max(0, Number(args.travelMs ?? CLICK_TRAVEL_MS)) : 0;

  await movePointer(x, y, travelMs);
  await host.automationSendInput({
    window: toText(args.window) || undefined,
    events: [{ type: "mouseMove", x, y }],
  });
  const pulse = pulsePointer();
  const payload = await host.automationSendInput({
    window: toText(args.window) || undefined,
    events: [
      { type: "mouseDown", x, y, button, clickCount, modifiers: args.modifiers || [] },
      { type: "mouseUp", x, y, button, clickCount, modifiers: args.modifiers || [] },
    ],
  });
  await pulse;
  if (!payload?.ok) return { ok: false, error: toText(payload?.error) || "Click failed." };
  // Let the click's handlers run before the harness asserts on the result.
  await new Promise((resolve) => setTimeout(resolve, CLICK_SETTLE_MS));
  return { ok: true, result: { x, y, button, clickCount } };
}

async function typeText(args = {}) {
  const text = String(args.text ?? "");
  if (!text) return { ok: false, error: "ui.typeText requires text." };
  const host = hostApi();
  const events = [];
  for (const char of text) {
    events.push({ type: "char", keyCode: char });
  }
  const payload = await host.automationSendInput({ window: toText(args.window) || undefined, events });
  if (!payload?.ok) return { ok: false, error: toText(payload?.error) || "Typing failed." };
  return { ok: true, result: { length: text.length } };
}

async function pressKey(args = {}) {
  const keyCode = toText(args.key || args.keyCode);
  if (!keyCode) return { ok: false, error: "ui.pressKey requires a key." };
  const host = hostApi();
  const modifiers = Array.isArray(args.modifiers) ? args.modifiers : [];
  const payload = await host.automationSendInput({
    window: toText(args.window) || undefined,
    events: [
      { type: "keyDown", keyCode, modifiers },
      { type: "keyUp", keyCode, modifiers },
    ],
  });
  if (!payload?.ok) return { ok: false, error: toText(payload?.error) || "Key press failed." };
  return { ok: true, result: { keyCode, modifiers } };
}

/**
 * Force-close every automation dialog and progress window. Teardown safety net: an unexpected
 * modal otherwise stalls the sequential poll loop for the full service timeout on every
 * subsequent command.
 */
function dismissDialogs() {
  let dismissed = 0;
  for (const overlay of document.querySelectorAll(".uiAutomationOverlay")) {
    overlay.remove();
    dismissed += 1;
  }
  return { ok: true, result: { dismissed } };
}

function listWindows() {
  return hostApi()
    .automationListWindows()
    .then((windows) => ({ ok: true, result: { windows } }));
}

/** Dispatch a shell-level automation command. Returns null when the name is not ours. */
export function executeShellAutomationCommand(command) {
  const name = toText(command?.command);
  const args = command?.args || {};

  switch (name) {
    case "shell.listTabs":
      return Promise.resolve({ ok: true, result: listTabs() });
    case "shell.openTab":
      return Promise.resolve(openTab(args));
    case "shell.activateTab":
      return Promise.resolve(activateTab(args));
    case "shell.closeTab":
      return Promise.resolve(closeTab(args));
    case "shell.state":
      return Promise.resolve({ ok: true, result: listTabs() });
    case "ui.captureScreenshot":
      return captureScreenshot(args);
    case "ui.sendInput":
      return sendInput(args);
    case "ui.clickAt":
      return clickAt(args);
    case "ui.typeText":
      return typeText(args);
    case "ui.pressKey":
      return pressKey(args);
    case "ui.dismissDialogs":
      return Promise.resolve(dismissDialogs());
    case "ui.listWindows":
      return listWindows();
    case "ui.pointer": {
      if (args.enabled !== undefined) setPointerEnabled(args.enabled);
      if (args.x !== undefined && args.y !== undefined) {
        return movePointer(args.x, args.y, args.travelMs ?? 0).then((position) => ({
          ok: true,
          result: { enabled: isPointerEnabled(), ...position },
        }));
      }
      return Promise.resolve({
        ok: true,
        result: { enabled: isPointerEnabled(), ...getPointerPosition() },
      });
    }
    default:
      return null;
  }
}

export const SHELL_AUTOMATION_COMMANDS = [
  "shell.listTabs",
  "shell.openTab",
  "shell.activateTab",
  "shell.closeTab",
  "shell.state",
  "ui.captureScreenshot",
  "ui.sendInput",
  "ui.clickAt",
  "ui.typeText",
  "ui.pressKey",
  "ui.dismissDialogs",
  "ui.listWindows",
  "ui.pointer",
];
