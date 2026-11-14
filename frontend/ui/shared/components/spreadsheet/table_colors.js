/*
===============================================================================
Table Custom Colors - the live preference behind the Custom Colors window.

The colours belong to the user and every method page shares them. They are kept
in the `tableColors` section of the user's preferences on the Arco Server,
through the desktop host. A copy in localStorage paints a window at boot without
waiting for the host, and is all there is in a browser session without the
host. A change is painted at once, told to the other open pages over a
BroadcastChannel, and saved through the host shortly after the last edit.
===============================================================================
*/
import {
  TABLE_COLORS_ATTRIBUTE,
  normalizeTableColors,
  tableColorCssState,
  tableFontCss,
  TABLE_APPEARANCE_MENU_LABEL,
} from "/ui/shared/components/spreadsheet/table_colors_model.js?v=20261003a";

const STORAGE_KEY = "arcrho_table_colors";
const CHANNEL_NAME = "arcrho:table-colors";
const SAVE_DELAY_MS = 400;
// Any table menu item carrying this attribute opens the window. The click is
// seen on its way down, before a page's menu handler can stop it, and that
// handler then closes the menu as it does for any item.
const MENU_ITEM_SELECTOR = "[data-table-colors]";

const listeners = new Set();
let current = normalizeTableColors(null);
let appliedProperties = [];
let channel = null;
let saveTimer = 0;
let editedSinceBoot = false;
let booted = false;
let currentPage = "";

/** The desktop host bridge; a nested page reaches it through its top window. */
function hostApi() {
  try {
    return window.ADAHost || window.top?.ADAHost || null;
  } catch {
    return null;
  }
}

function readCachedColors() {
  try {
    return normalizeTableColors(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return normalizeTableColors(null);
  }
}

function writeCachedColors(prefs) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // Blocked storage only costs the next window its early paint.
  }
}

function applyToDocument(prefs) {
  const root = document.documentElement;
  const { tokens, properties } = tableColorCssState(prefs);
  for (const name of appliedProperties) {
    if (!(name in properties)) root.style.removeProperty(name);
  }
  for (const [name, value] of Object.entries(properties)) root.style.setProperty(name, value);
  appliedProperties = Object.keys(properties);
  if (tokens.length) root.setAttribute(TABLE_COLORS_ATTRIBUTE, tokens.join(" "));
  else root.removeAttribute(TABLE_COLORS_ATTRIBUTE);
  let fonts = document.getElementById("ar-table-font-overrides");
  if (!fonts) {
    fonts = document.createElement("style");
    fonts.id = "ar-table-font-overrides";
    document.head.appendChild(fonts);
  }
  fonts.textContent = tableFontCss(prefs);
}

/** Paints `prefs` and tells the listeners; false when nothing changed. */
function adopt(prefs) {
  const next = normalizeTableColors(prefs);
  if (JSON.stringify(next) === JSON.stringify(current)) return false;
  current = next;
  applyToDocument(current);
  listeners.forEach((listener) => listener(current));
  return true;
}

function saveToHost() {
  saveTimer = 0;
  const save = hostApi()?.saveTableColorPreferences;
  if (typeof save !== "function") return;
  Promise.resolve(save(current)).catch(() => {
    // A host that cannot write keeps the colours for this session only.
  });
}

export function getTableColors() {
  return current;
}

/** The page the colours were booted for, which picks the page's own parts. */
export function getTableColorsPage() {
  return currentPage;
}

export function subscribeTableColors(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setTableColors(prefs) {
  editedSinceBoot = true;
  if (!adopt(prefs)) return;
  writeCachedColors(current);
  channel?.postMessage(current);
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(saveToHost, SAVE_DELAY_MS);
}

/** Opens the Custom Colors window, or brings the open one forward. */
export function openTableColorsWindow() {
  void import("/ui/shared/components/spreadsheet/table_colors_window.js?v=20261003b")
    .then((module) => module.openTableColorsWindow());
}

function openFromMenu(event) {
  if (event.target?.closest?.(MENU_ITEM_SELECTOR)) openTableColorsWindow();
}

/**
 * Paints the stored colours, then keeps them current: the host file replaces
 * the local copy once it arrives, and other pages' edits arrive over the
 * channel. Also opens the window from any table menu item marked
 * `data-table-colors`. `page` names the page's own parts in the catalogue.
 */
export function bootTableColors({ page = "" } = {}) {
  if (booted) return;
  booted = true;
  currentPage = String(page || "");
  document.querySelectorAll(MENU_ITEM_SELECTOR).forEach(item => { item.textContent = TABLE_APPEARANCE_MENU_LABEL; });
  adopt(readCachedColors());
  if (typeof BroadcastChannel === "function") {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (event) => adopt(event.data);
  }
  window.addEventListener("pagehide", () => {
    if (saveTimer) {
      window.clearTimeout(saveTimer);
      saveToHost();
    }
  });
  document.addEventListener("click", openFromMenu, true);
  const load = hostApi()?.loadTableColorPreferences;
  if (typeof load !== "function") return;
  Promise.resolve(load())
    .then((result) => {
      if (editedSinceBoot || !result?.ok || !result.exists) return;
      if (adopt(result.preferences)) writeCachedColors(current);
    })
    .catch(() => {
      // Without the host file the local copy stands.
    });
}
