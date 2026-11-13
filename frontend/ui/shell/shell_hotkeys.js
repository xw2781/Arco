import { shell } from "./shell_context.js?v=20260510a";
import {
  TABBED_PAGE_NEXT_MESSAGE,
  TABBED_PAGE_PREVIOUS_MESSAGE,
} from "/ui/shared/tabbed_page/tabbed_page.js?v=20260913a";

let lastKeyCombo = "";
let lastKeyTime = 0;
let hotkeysWired = false;

function normalizeKeyCombo(e) {
  const parts = [];
  if (e.ctrlKey) parts.push("Ctrl");
  if (e.altKey) parts.push("Alt");
  if (e.shiftKey) parts.push("Shift");
  let k = e.key;
  if ((!k || k === "Unidentified") && e.code === "KeyQ") k = "Q";
  if ((!k || k === "Unidentified") && e.code === "KeyD") k = "D";
  if (k === "r" || k === "R") k = "R";
  if (k === "q" || k === "Q") k = "Q";
  if (k === "F5") k = "F5";
  if (k && k.length === 1 && k >= "a" && k <= "z") k = k.toUpperCase();
  parts.push(k);
  return parts.join("+");
}

function shouldIgnoreHotkey(e) {
  const el = e.target;
  if (!el) return false;
  const tag = el.tagName?.toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return true;
  if (el.isContentEditable) return true;
  return false;
}

const hotkeys = {
  "Ctrl+R": "custom_refresh",
  "Ctrl+Shift+R": "custom_hard_refresh",
  "Ctrl+Shift+K": "clear_test_data",
  "Alt+W": "tab_close",
  "Ctrl+H": "dfm_exclude_high",
  "Ctrl+L": "dfm_exclude_low",
  "Ctrl+I": "dfm_include_all",
  "Ctrl+E": "dfm_toggle_ratios_mode",
  "Ctrl+Z": "dfm_undo",
  "Ctrl+Y": "dfm_redo",
  "Ctrl+PageUp": "tabbed_page_prev",
  "Ctrl+PageDown": "tabbed_page_next",
  "Ctrl+S": "file_save",
  "Ctrl+Shift+S": "file_save_as",
  "Ctrl+O": "file_import",
  "Ctrl+P": "file_print",
  "Ctrl+B": "view_toggle_flight_deck",
  "Ctrl+Shift+F": "view_toggle_nav",
  "Ctrl+Shift+L": "view_toggle_line_numbers",
  "Ctrl+Shift+E": "view_toggle_exec_time",
  "Ctrl+Shift+I": "help_view_dev_panel",
  "Ctrl+Q": "app_shutdown",
  "Alt+D": "settings_toggle_color_theme",
  "Alt+Q": "settings_clear_cache_reload",
  "Ctrl+Alt+R": "file_restart",
};

export function resolveHotkeyAction(event) {
  return hotkeys[normalizeKeyCombo(event)] || "";
}

function tryConsumeActiveFrameCloseShortcut() {
  const active = shell.state.tabs.find((tab) => tab.id === shell.state.activeId);
  const frameWin = active?.iframe?.contentWindow;
  if (!frameWin) return false;
  try {
    const consume = frameWin.__arcrho_consume_close_shortcut;
    return typeof consume === "function" && consume() === true;
  } catch {
    return false;
  }
}

const TABBED_PAGE_TYPES = new Set([
  "dataset",
  "dfm",
  "bornhuetter_ferguson",
  "cape_cod",
  "result_selection",
  "berquist_sherman",
  "project_instance",
]);

function sendActiveTabbedPageCommand(type) {
  const active = shell.state.tabs.find((tab) => tab.id === shell.state.activeId);
  if (!active || !TABBED_PAGE_TYPES.has(active.type)) return false;
  shell.ensureIframe?.(active);
  try {
    active.iframe?.contentWindow?.postMessage({ type }, "*");
    return true;
  } catch {
    return false;
  }
}

export function runHotkeyAction(action) {
  if (action === "custom_refresh") return shell.refreshActiveTab?.();
  if (action === "custom_hard_refresh") return shell.customHardRefresh?.();
  if (action === "clear_test_data") return shell.clearTestData?.();
  if (action === "tab_close") return shell.closeTab?.(shell.state.activeId);
  if (action === "dfm_exclude_high") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-exclude-high"); return; }
  if (action === "dfm_exclude_low") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-exclude-low"); return; }
  if (action === "dfm_include_all") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-include-all"); return; }
  if (action === "dfm_toggle_ratios_mode") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-toggle-ratios-mode"); return; }
  if (action === "dfm_undo") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-undo"); return; }
  if (action === "dfm_redo") { if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-redo"); return; }
  if (action === "tabbed_page_prev") return sendActiveTabbedPageCommand(TABBED_PAGE_PREVIOUS_MESSAGE);
  if (action === "tabbed_page_next") return sendActiveTabbedPageCommand(TABBED_PAGE_NEXT_MESSAGE);
  if (action === "file_save") {
    if (shell.isActiveWorkflowTab?.()) shell.sendWorkflowCommand?.("arcrho:workflow-save");
    else if (shell.isActiveDashboardTab?.()) shell.sendDashboardCommand?.("arcrho:dashboard-save");
    else if (shell.isActiveDatasetTab?.()) shell.sendDatasetCommand?.("arcrho:dataset-save");
    else if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.("arcrho:dfm-save");
    else if (shell.isActiveProjectInstanceTab?.()) shell.sendProjectInstanceCommand?.("arcrho:dfm-save");
    else if (shell.isActiveScriptingTab?.()) shell.sendScriptingCommand?.("arcrho:scripting-save");
    else if (shell.isActiveProjectSettingsReservingClassTypesTab?.()) shell.sendProjectSettingsCommand?.("arcrho:project-settings-reserving-class-types-save-local");
    else if (shell.isActiveProjectSettingsDatasetTypesTab?.()) shell.sendProjectSettingsCommand?.("arcrho:project-settings-dataset-types-save-local");
    return;
  }
  if (action === "file_save_as") {
    if (shell.isActiveWorkflowTab?.()) shell.sendWorkflowCommand?.("arcrho:workflow-save-as");
    else if (shell.isActiveDashboardTab?.()) shell.sendDashboardCommand?.("arcrho:dashboard-save-as");
    else if (shell.isActiveDatasetTab?.()) shell.sendDatasetCommand?.("arcrho:dataset-save");
    else if (shell.isActiveDFMTab?.()) shell.sendDFMCommand?.(shell.isActiveDFMDetailsTab?.() ? "arcrho:dfm-save-template" : "arcrho:dfm-save-as");
    else if (shell.isActiveProjectInstanceTab?.()) shell.sendProjectInstanceCommand?.("arcrho:dfm-save-as");
    else if (shell.isActiveScriptingTab?.()) shell.sendScriptingCommand?.("arcrho:scripting-save-as");
    else if (shell.isActiveProjectSettingsReservingClassTypesTab?.()) shell.sendProjectSettingsCommand?.("arcrho:project-settings-reserving-class-types-load-local");
    else if (shell.isActiveProjectSettingsDatasetTypesTab?.()) shell.sendProjectSettingsCommand?.("arcrho:project-settings-dataset-types-load-local");
    return;
  }
  if (action === "file_import") {
    if (shell.isActiveScriptingTab?.()) shell.sendScriptingCommand?.("arcrho:scripting-open");
    else if (shell.isActiveWorkflowTab?.()) shell.importWorkflow?.();
    return;
  }
  if (action === "file_print") return shell.printActiveTab?.();
  if (action === "view_toggle_flight_deck") return shell.toggleFlightDeck?.();
  if (action === "view_toggle_nav") return shell.toggleNavigationPanel?.();
  if (action === "view_toggle_line_numbers") { if (shell.isActiveScriptingTab?.()) shell.sendScriptingCommand?.("arcrho:scripting-toggle-line-numbers"); return; }
  if (action === "view_toggle_exec_time") { if (shell.isActiveScriptingTab?.()) shell.sendScriptingCommand?.("arcrho:scripting-toggle-exec-time"); return; }
  if (action === "help_view_dev_panel") return shell.openDevPanel?.();
  if (action === "settings_toggle_color_theme") {
    const themes = window.ArcRhoColorTheme?.THEMES || ["light", "dark"];
    const currentTheme = shell.getColorTheme?.();
    const currentIndex = themes.indexOf(currentTheme);
    const nextTheme = themes[(currentIndex + 1 + themes.length) % themes.length] || "light";
    shell.setColorTheme?.(nextTheme);
    const label = nextTheme.split("-").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    shell.updateStatusBar?.(`Color theme changed to ${label}.`);
    return;
  }
  if (action === "settings_clear_cache_reload") {
    return Promise.resolve(shell.clearCacheAndReload?.()).catch((err) => {
      console.error("Clear Cache & Reload failed:", err);
      shell.updateStatusBar?.("Clear Cache & Reload failed.");
    });
  }
  if (action === "file_restart") return shell.restartApplication?.();
  if (action === "app_shutdown") return shell.shutdownApplication?.();
}

export function initHotkeys() {
  if (hotkeysWired) return;
  hotkeysWired = true;
  window.__arcrho_should_intercept_close = function () {
    return lastKeyCombo === "Ctrl+W" && (Date.now() - lastKeyTime) < 900;
  };
  window.addEventListener("keydown", (e) => {
    if (!shell.hostZoomAvailable?.() && e.ctrlKey && !e.altKey) {
      if (e.key === "-" || e.key === "_") { e.preventDefault(); shell.setZoomPercent?.((shell.getZoomPercent?.() || 100) - shell.ZOOM_STEP, true); return; }
      if (e.key === "=" || e.key === "+") { e.preventDefault(); shell.setZoomPercent?.((shell.getZoomPercent?.() || 100) + shell.ZOOM_STEP, true); return; }
      if (e.key === "0") { e.preventDefault(); shell.setZoomPercent?.(100, true); return; }
    }
    if (!e.altKey && e.key === "F5") {
      e.preventDefault();
      e.stopPropagation();
      return;
    }
    const combo = normalizeKeyCombo(e);
    lastKeyCombo = combo;
    lastKeyTime = Date.now();
    if (combo === "Ctrl+Shift+I") {
      e.preventDefault();
      e.stopPropagation();
      runHotkeyAction("help_view_dev_panel");
      return;
    }
    const action = resolveHotkeyAction(e);
    if (action === "dfm_toggle_ratios_mode") {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) runHotkeyAction(action);
      return;
    }
    if (action === "settings_clear_cache_reload" || action === "settings_toggle_color_theme") {
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) runHotkeyAction(action);
      return;
    }
    if (shouldIgnoreHotkey(e)) return;
    if (combo === "Ctrl+W") {
      e.preventDefault();
      e.stopPropagation();
      if (tryConsumeActiveFrameCloseShortcut()) return;
      shell.closeTab?.(shell.state.activeId);
      return;
    }
    if (!action) return;
    e.preventDefault();
    e.stopPropagation();
    runHotkeyAction(action);
  }, { capture: true });
  window.addEventListener("wheel", (e) => {
    if (!e.ctrlKey) return;
    if (shell.hostZoomAvailable?.()) return;
    e.preventDefault();
    shell.adjustZoomByDelta?.(e.deltaY || 0);
  }, { capture: true, passive: false });
}
