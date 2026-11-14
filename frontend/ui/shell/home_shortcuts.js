// Canonical owner of the Home custom shortcut document.
//
// A shortcut card stores the same normalized descriptor Browsing History uses, so a card target is
// always something `openShellActivityHistoryEntry` can reopen, and clicking a card follows each
// page's own open/focus rule instead of inventing a second one.
//
// Persisted as `homeShortcuts` in the `shell` section of the user's preferences on the Arco
// Server, through the existing `/local-project/preferences` routes. Saves post only that section; the app-server merges by key, so shortcuts and the shell
// activity history written beside them never overwrite each other.

// Relative specifier resolves to the same `/ui/shell/shell_activity_history.js` URL the rest of the
// shell imports, so this stays one module instance in the browser and stays loadable under Node.
import { normalizeShellActivityEntry } from "./shell_activity_history.js";

const LOCAL_PROJECT_PREFS_ENDPOINT = "/local-project/preferences";

export const HOME_SHORTCUTS_VERSION = 1;
export const MAX_GROUPS = 24;
export const MAX_CARDS_PER_GROUP = 48;
export const MAX_TITLE_LENGTH = 60;

let idCounter = 0;

function toText(value) {
  return String(value ?? "").trim();
}

function clampTitle(value, fallback) {
  const text = toText(value).slice(0, MAX_TITLE_LENGTH).trim();
  return text || fallback;
}

function nextId(prefix) {
  idCounter += 1;
  return `${prefix}_${Date.now().toString(36)}${idCounter.toString(36)}`;
}

// A pinned shortcut has no meaningful "when did I last view this", so the descriptor's activity
// timestamp is dropped rather than persisted as a stale value.
export function normalizeCardTarget(raw) {
  const entry = normalizeShellActivityEntry(raw);
  if (!entry) return null;
  const { ts, ...target } = entry;
  return target;
}

function normalizeCard(raw, usedIds) {
  if (!raw || typeof raw !== "object") return null;
  const target = normalizeCardTarget(raw.target || raw);
  if (!target) return null;
  let id = toText(raw.id);
  if (!id || usedIds.has(id)) id = nextId("crd");
  usedIds.add(id);
  return {
    id,
    label: clampTitle(raw.label || target.title, target.title || "Shortcut"),
    target,
  };
}

function normalizeGroup(raw, usedIds) {
  if (!raw || typeof raw !== "object") return null;
  let id = toText(raw.id);
  if (!id || usedIds.has(id)) id = nextId("grp");
  usedIds.add(id);
  const cards = [];
  for (const item of Array.isArray(raw.cards) ? raw.cards : []) {
    const card = normalizeCard(item, usedIds);
    if (!card) continue;
    cards.push(card);
    if (cards.length >= MAX_CARDS_PER_GROUP) break;
  }
  return { id, title: clampTitle(raw.title, "Untitled group"), cards };
}

export function normalizeHomeShortcuts(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const usedIds = new Set();
  const groups = [];
  for (const item of Array.isArray(source.groups) ? source.groups : []) {
    const group = normalizeGroup(item, usedIds);
    if (!group) continue;
    groups.push(group);
    if (groups.length >= MAX_GROUPS) break;
  }
  return { version: HOME_SHORTCUTS_VERSION, groups };
}

export function createEmptyHomeShortcuts() {
  return { version: HOME_SHORTCUTS_VERSION, groups: [] };
}

export async function loadHomeShortcuts() {
  const response = await fetch(LOCAL_PROJECT_PREFS_ENDPOINT, { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
  const payload = await response.json().catch(() => ({}));
  const prefs = payload?.preferences && typeof payload.preferences === "object" ? payload.preferences : payload;
  return normalizeHomeShortcuts(prefs?.homeShortcuts);
}

export async function saveHomeShortcuts(document) {
  const normalized = normalizeHomeShortcuts(document);
  const response = await fetch(LOCAL_PROJECT_PREFS_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ homeShortcuts: normalized }),
  });
  if (!response.ok) throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
  return normalized;
}

function cloneDocument(document) {
  return normalizeHomeShortcuts(document);
}

function findGroupIndex(document, groupId) {
  return document.groups.findIndex((group) => group.id === groupId);
}

function findCardIndex(group, cardId) {
  return group ? group.cards.findIndex((card) => card.id === cardId) : -1;
}

function moveWithin(list, index, delta) {
  const target = index + delta;
  if (index < 0 || target < 0 || target >= list.length) return false;
  const [item] = list.splice(index, 1);
  list.splice(target, 0, item);
  return true;
}

export function addGroup(document, title) {
  const next = cloneDocument(document);
  if (next.groups.length >= MAX_GROUPS) return { document: next, groupId: "", error: `Home allows at most ${MAX_GROUPS} custom groups.` };
  const group = { id: nextId("grp"), title: clampTitle(title, "Untitled group"), cards: [] };
  next.groups.push(group);
  return { document: next, groupId: group.id, error: "" };
}

export function renameGroup(document, groupId, title) {
  const next = cloneDocument(document);
  const index = findGroupIndex(next, groupId);
  if (index < 0) return next;
  next.groups[index].title = clampTitle(title, next.groups[index].title);
  return next;
}

export function removeGroup(document, groupId) {
  const next = cloneDocument(document);
  const index = findGroupIndex(next, groupId);
  if (index >= 0) next.groups.splice(index, 1);
  return next;
}

export function moveGroup(document, groupId, delta) {
  const next = cloneDocument(document);
  moveWithin(next.groups, findGroupIndex(next, groupId), delta);
  return next;
}

export function addCard(document, groupId, { label, target } = {}) {
  const next = cloneDocument(document);
  const group = next.groups[findGroupIndex(next, groupId)];
  if (!group) return { document: next, cardId: "", error: "That group no longer exists." };
  if (group.cards.length >= MAX_CARDS_PER_GROUP) {
    return { document: next, cardId: "", error: `A group holds at most ${MAX_CARDS_PER_GROUP} cards.` };
  }
  const normalizedTarget = normalizeCardTarget(target);
  if (!normalizedTarget) return { document: next, cardId: "", error: "That tab cannot be saved as a shortcut." };
  const card = {
    id: nextId("crd"),
    label: clampTitle(label || normalizedTarget.title, normalizedTarget.title || "Shortcut"),
    target: normalizedTarget,
  };
  group.cards.push(card);
  return { document: next, cardId: card.id, error: "" };
}

export function renameCard(document, groupId, cardId, label) {
  const next = cloneDocument(document);
  const group = next.groups[findGroupIndex(next, groupId)];
  const index = findCardIndex(group, cardId);
  if (index < 0) return next;
  group.cards[index].label = clampTitle(label, group.cards[index].label);
  return next;
}

export function removeCard(document, groupId, cardId) {
  const next = cloneDocument(document);
  const group = next.groups[findGroupIndex(next, groupId)];
  const index = findCardIndex(group, cardId);
  if (index >= 0) group.cards.splice(index, 1);
  return next;
}

// The one placement rule: take a card out of its group and put it at an absolute slot in any group,
// its own included. Dragging is the only way a card is placed - the card menu keeps just rename and
// delete - so a step-wise `moveCard`/`moveCardToGroup` pair would be a second, uncalled definition
// of the same move.
//
// A slot past the ends clamps rather than dropping the card. Within one group the last slot is
// `length - 1` because the card is already counted; landing in another group adds one, so its last
// slot is `length` - the position the Add card tile occupies.
export function placeCard(document, fromGroupId, cardId, toGroupId, toIndex) {
  const next = cloneDocument(document);
  const from = next.groups[findGroupIndex(next, fromGroupId)];
  const to = next.groups[findGroupIndex(next, toGroupId)];
  const index = findCardIndex(from, cardId);
  if (!to || index < 0) return next;
  const sameGroup = from === to;
  if (!sameGroup && to.cards.length >= MAX_CARDS_PER_GROUP) return next;
  const lastSlot = sameGroup ? from.cards.length - 1 : to.cards.length;
  const target = Math.max(0, Math.min(Math.trunc(Number(toIndex)) || 0, lastSlot));
  if (sameGroup && target === index) return next;
  const [card] = from.cards.splice(index, 1);
  to.cards.splice(target, 0, card);
  return next;
}
