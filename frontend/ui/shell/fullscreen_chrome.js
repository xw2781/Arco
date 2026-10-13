import { $, getHostApi, shell } from "./shell_context.js?v=20260510a";

/*
 * Full screen hides the shell's own title bar, menu bar and tab strip the way a browser hides its
 * chrome: the three rows leave the layout, the page takes the whole screen, and moving the pointer
 * to the top edge of the screen brings them back over the content until the pointer moves away.
 */

const FULLSCREEN_CLASS = "app-fullscreen";
const REVEALED_CLASS = "chrome-revealed";
// The reveal reads the pointer's own position rather than sitting under a strip of its own: a
// strip pinned to the top edge would swallow the clicks that land on the top pixels of a tab.
const TOP_EDGE_PX = 5;
const HIDE_DELAY_MS = 400;
const BUSY_RECHECK_MS = 250;
const OPEN_MENU_SELECTOR = ".menuDropdown.open, .menuItem.menuSubmenuOpen, #tabCtxMenu.open";
const TAB_DRAG_CLASS = "tab-dragging";

let wired = false;
let fullscreen = false;
let pointerInsideChrome = false;
let hideTimer = null;

function chromeElements() {
  return [$("customTitlebar"), $("menubar"), document.querySelector(".topbar")].filter(Boolean);
}

function isMenuOpen() {
  return !!document.querySelector(OPEN_MENU_SELECTOR);
}

function isTabDragging() {
  return document.body.classList.contains(TAB_DRAG_CLASS);
}

function isFocusInsideChrome() {
  const active = document.activeElement;
  if (!active) return false;
  return chromeElements().some((el) => el.contains(active));
}

function cancelHide() {
  if (!hideTimer) return;
  clearTimeout(hideTimer);
  hideTimer = null;
}

function scheduleHide(delay = HIDE_DELAY_MS) {
  cancelHide();
  if (!fullscreen) return;
  hideTimer = setTimeout(() => {
    hideTimer = null;
    if (!fullscreen) return;
    // An open menu, a tab being dragged, a pointer still on the chrome, or the keyboard focus
    // sitting in it all mean the user is working in the chrome, so look again instead of pulling
    // it away underneath them.
    if (pointerInsideChrome || isMenuOpen() || isTabDragging() || isFocusInsideChrome()) {
      scheduleHide(BUSY_RECHECK_MS);
      return;
    }
    document.body.classList.remove(REVEALED_CLASS);
  }, delay);
}

function revealChrome() {
  if (!fullscreen) return;
  cancelHide();
  document.body.classList.add(REVEALED_CLASS);
}

export function isFullscreenChromeActive() {
  return fullscreen;
}

export function setFullscreenChrome(enabled) {
  const next = !!enabled;
  if (next === fullscreen) return;
  fullscreen = next;
  document.body.classList.toggle(FULLSCREEN_CLASS, fullscreen);
  cancelHide();
  pointerInsideChrome = false;
  document.body.classList.remove(REVEALED_CLASS);
  if (fullscreen) shell.closeAllShellMenus?.();
}

export async function syncFullscreenChromeFromHost() {
  const api = getHostApi();
  if (typeof api?.isFullscreen !== "function") return;
  try {
    setFullscreenChrome(await api.isFullscreen());
  } catch {
    // ignore
  }
}

export function initFullscreenChrome() {
  if (wired) return;
  wired = true;

  document.addEventListener("pointermove", (event) => {
    if (!fullscreen) return;
    if (Number(event?.clientY ?? TOP_EDGE_PX + 1) > TOP_EDGE_PX) return;
    revealChrome();
  });
  for (const el of chromeElements()) {
    el.addEventListener("pointerenter", () => {
      pointerInsideChrome = true;
      cancelHide();
    });
    el.addEventListener("pointerleave", () => {
      pointerInsideChrome = false;
      scheduleHide();
    });
  }

  void syncFullscreenChromeFromHost();
}
