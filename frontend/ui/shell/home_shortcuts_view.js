// Home custom groups and shortcut cards: rendering, context menus, and dialogs.
//
// The document model, validation, and persistence live in `home_shortcuts.js`; this module is the
// presentation and interaction layer only. Card targets are built from live tabs with
// `buildShellActivityEntry` and opened with `openShellActivityHistoryEntry`, so a card behaves
// exactly like restoring that page from Browsing History.

import { $, shell } from "./shell_context.js?v=20260510a";
import { homeCardIconForTabType } from "./home_card_icons.js?v=20260926a";
import { buildRestoreSummary } from "./shell_activity_history.js";
import { attachArcrhoTooltip } from "../shared/components/tooltip/tooltip.js?v=20260925a";
import {
  MAX_CARDS_PER_GROUP,
  addCard,
  addGroup,
  createEmptyHomeShortcuts,
  loadHomeShortcuts,
  moveGroup,
  placeCard,
  removeCard,
  removeGroup,
  renameCard,
  renameGroup,
  saveHomeShortcuts,
} from "./home_shortcuts.js?v=20260808c";

const TAB_TYPE_LABELS = {
  dataset: "Dataset",
  dfm: "DFM",
  workflow: "Workflow",
  project_settings: "Project Explorer",
  project_instance: "Project Instance",
  scripting: "Arcode",
  agent_guide: "ArcBot Guide",
  file_explorer: "File Browser",
  browsing_history: "Browsing History",
  server: "Server Connections",
  dashboard: "Dashboard",
};

let shortcutsDocument = createEmptyHomeShortcuts();
let containerEl = null;
let wired = false;
let loadPromise = null;
let menuContext = null;
let namePromptResolve = null;
let addCardResolve = null;

// Press-and-hold reordering has a brief threshold to distinguish a drag from an intentional card
// activation. A quick click activates the card; an incomplete hold cancels without activation.
const CLICK_TO_OPEN_MS = 200;
const HOLD_TO_DRAG_MS = 500;
const HOLD_CANCEL_DISTANCE = 6;
const CLICK_SUPPRESS_MS = 400;
const DROP_SETTLE_MS = 140;

let holdState = null;
let dragState = null;
let pendingDrop = null;
let suppressClickUntil = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function tabTypeLabel(tabType) {
  return TAB_TYPE_LABELS[String(tabType || "").trim().toLowerCase()] || "Page";
}

function reportError(message) {
  shell.updateStatusBar?.(String(message || "Could not update Home shortcuts."), { tone: "error" });
}

/* ---------------------------------------------------------------- rendering */

function renderCard(group, card) {
  const summary = buildRestoreSummary(card.target);
  return `
    <div class="card clickable homeShortcutCard" role="button" tabindex="0"
         data-group-id="${escapeHtml(group.id)}" data-card-id="${escapeHtml(card.id)}">
      ${homeCardIconForTabType(card.target.tabType)}
      <div class="homeShortcutCardText">
        <h3>${escapeHtml(card.label)}</h3>
        <div class="muted">${escapeHtml(summary || tabTypeLabel(card.target.tabType))}</div>
      </div>
      <button class="homeCardMenuBtn" type="button" data-menu="card"
              aria-label="${escapeHtml(card.label)} options">&#8943;</button>
    </div>
  `;
}

// Every custom group ends with this slot rather than only empty ones: the group header buttons are
// hover-only, so the tile is the always-visible way to pin another tab.
function renderAddCardSlot(group) {
  const empty = !group.cards.length;
  const label = `Add a card to ${escapeHtml(group.title)}`;
  return `
    <button class="homeShortcutAddCard${empty ? " isEmptyGroup" : ""}" type="button" data-action="add-card"
            title="${label}" aria-label="${label}">
      <span class="homeShortcutAddCardPlus" aria-hidden="true">+</span>
      <span class="homeShortcutAddCardText">${empty ? "Pin an open tab to this group" : "Add card"}</span>
    </button>
  `;
}

function renderGroup(group) {
  const cards = group.cards.map((card) => renderCard(group, card)).join("") + renderAddCardSlot(group);
  return `
    <div class="homeGroup homeCustomGroup" data-group-id="${escapeHtml(group.id)}">
      <div class="groupTitle homeCustomGroupTitle">
        <span class="homeCustomGroupName">${escapeHtml(group.title)}</span>
        <span class="homeGroupActions">
          <button class="homeGroupActionBtn" type="button" data-menu="group"
                  aria-label="${escapeHtml(group.title)} options" title="Group options">&#8943;</button>
        </span>
      </div>
      <div class="cards">${cards}</div>
    </div>
  `;
}

export function renderHomeShortcuts() {
  if (!containerEl) return;
  const groups = shortcutsDocument.groups.map(renderGroup).join("");
  const empty = shortcutsDocument.groups.length
    ? ""
    : `<span class="homeShortcutsIntro">Group the projects, datasets, and pages you use most. Cards are created from tabs you already have open.</span>`;
  containerEl.innerHTML = `
    ${groups}
    <div class="homeShortcutsFooter">
      ${empty}
      <button class="homeAddGroupHint" type="button" data-action="add-group" aria-label="Add a new group">+ New group</button>
    </div>
  `;
  containerEl.querySelectorAll(".homeShortcutCard").forEach((card) => {
    attachArcrhoTooltip(card, "Hold to drag and reorder");
  });
}

/* ------------------------------------------------------------- persistence */

async function commit(nextDocument) {
  const previous = shortcutsDocument;
  shortcutsDocument = nextDocument;
  renderHomeShortcuts();
  try {
    shortcutsDocument = await saveHomeShortcuts(nextDocument);
    renderHomeShortcuts();
  } catch (err) {
    shortcutsDocument = previous;
    renderHomeShortcuts();
    reportError(`Could not save Home shortcuts. ${err?.message || err}`);
  }
}

/* ----------------------------------------------------------------- dialogs */

function closeNameDialog(result) {
  const overlay = $("homeNameOverlay");
  overlay?.classList.remove("open");
  const resolve = namePromptResolve;
  namePromptResolve = null;
  resolve?.(result);
}

function promptForName({ title, label, value, okText }) {
  const overlay = $("homeNameOverlay");
  const titleEl = $("homeNameTitle");
  const labelEl = $("homeNameLabel");
  const input = $("homeNameInput");
  const okBtn = $("homeNameOkBtn");
  if (!overlay || !titleEl || !labelEl || !input || !okBtn) return Promise.resolve(null);
  if (namePromptResolve) closeNameDialog(null);
  titleEl.textContent = title;
  labelEl.textContent = label;
  okBtn.textContent = okText || "Save";
  input.value = value || "";
  overlay.classList.add("open");
  window.setTimeout(() => { input.focus(); input.select(); }, 0);
  return new Promise((resolve) => { namePromptResolve = resolve; });
}

// Reached through the shell API rather than importing tab_actions.js directly: the shell already
// loads that module under its own `?v=` specifier, and a second specifier would create a duplicate
// module instance with its own history-save timer state.
function eligibleShortcutTabs() {
  return shell.state.tabs
    .map((tab) => ({ tab, target: shell.buildShellActivityEntry?.(tab) || null }))
    .filter((item) => !!item.target);
}

function closeAddCardDialog(result) {
  const overlay = $("homeAddCardOverlay");
  overlay?.classList.remove("open");
  const resolve = addCardResolve;
  addCardResolve = null;
  resolve?.(result);
}

function promptForCard(preferredGroupId) {
  const overlay = $("homeAddCardOverlay");
  const list = $("homeAddCardList");
  const groupSelect = $("homeAddCardGroup");
  const labelInput = $("homeAddCardLabel");
  const okBtn = $("homeAddCardOkBtn");
  if (!overlay || !list || !groupSelect || !labelInput || !okBtn) return Promise.resolve(null);
  if (addCardResolve) closeAddCardDialog(null);

  const candidates = eligibleShortcutTabs();
  list.innerHTML = candidates.length
    ? candidates.map((item, index) => `
        <label class="homeAddCardOption">
          <input type="radio" name="homeAddCardTarget" value="${index}"${index === 0 ? " checked" : ""} />
          <span class="homeAddCardOptionBody">
            <span class="homeAddCardOptionTitle">${escapeHtml(item.target.title)}</span>
            <span class="homeAddCardOptionMeta">
              <span class="homeAddCardChip">${escapeHtml(tabTypeLabel(item.target.tabType))}</span>
              <span class="homeAddCardSummary">${escapeHtml(buildRestoreSummary(item.target))}</span>
            </span>
          </span>
        </label>
      `).join("")
    : `<div class="homeAddCardEmpty">No open tab can be pinned yet. Open a project, dataset, workflow, or workspace tab first.</div>`;

  groupSelect.innerHTML = shortcutsDocument.groups
    .map((group) => `<option value="${escapeHtml(group.id)}">${escapeHtml(group.title)}</option>`)
    .join("");
  if (preferredGroupId) groupSelect.value = preferredGroupId;
  labelInput.value = candidates.length ? candidates[0].target.title : "";
  okBtn.disabled = !candidates.length;

  const syncLabel = () => {
    const selected = list.querySelector('input[name="homeAddCardTarget"]:checked');
    const candidate = candidates[Number(selected?.value ?? -1)];
    if (candidate) labelInput.value = candidate.target.title;
  };
  list.addEventListener("change", syncLabel);

  overlay.classList.add("open");
  return new Promise((resolve) => {
    addCardResolve = (result) => {
      list.removeEventListener("change", syncLabel);
      if (!result) return resolve(null);
      const selected = list.querySelector('input[name="homeAddCardTarget"]:checked');
      const candidate = candidates[Number(selected?.value ?? -1)];
      if (!candidate) return resolve(null);
      resolve({
        groupId: groupSelect.value,
        label: labelInput.value,
        target: candidate.target,
      });
    };
  });
}

/* -------------------------------------------------------------- popup menu */

function closeHomeShortcutMenu() {
  const menu = $("homeShortcutMenu");
  menu?.classList.remove("open");
  menuContext = null;
}

function openHomeShortcutMenu(items, x, y) {
  const menu = $("homeShortcutMenu");
  if (!menu) return;
  menu.innerHTML = items
    .map((item) => (item.separator
      ? `<div class="homeShortcutMenuSep"></div>`
      : `<div class="tabCtxItem homeShortcutMenuItem${item.disabled ? " disabled" : ""}${item.danger ? " isDanger" : ""}" data-action="${escapeHtml(item.action)}">${escapeHtml(item.label)}</div>`))
    .join("");
  menu.classList.add("open");
  const pad = 8;
  const maxX = window.innerWidth - menu.offsetWidth - pad;
  const maxY = window.innerHeight - menu.offsetHeight - pad;
  menu.style.left = `${Math.max(pad, Math.min(x, maxX))}px`;
  menu.style.top = `${Math.max(pad, Math.min(y, maxY))}px`;
}

function openGroupMenu(groupId, x, y) {
  const index = shortcutsDocument.groups.findIndex((group) => group.id === groupId);
  if (index < 0) return;
  menuContext = { kind: "group", groupId };
  openHomeShortcutMenu([
    { label: "Add card...", action: "add-card" },
    { label: "Rename group...", action: "rename-group" },
    { separator: true },
    { label: "Move up", action: "move-group-up", disabled: index === 0 },
    { label: "Move down", action: "move-group-down", disabled: index === shortcutsDocument.groups.length - 1 },
    { separator: true },
    { label: "Delete group", action: "delete-group" },
  ], x, y);
}

function openCardMenu(groupId, cardId, x, y) {
  const group = shortcutsDocument.groups.find((item) => item.id === groupId);
  const index = group ? group.cards.findIndex((card) => card.id === cardId) : -1;
  if (index < 0) return;
  menuContext = { kind: "card", groupId, cardId };
  // Placement is the drag's job. The menu keeps only what a drag cannot express.
  openHomeShortcutMenu([
    { label: "Rename card...", action: "rename-card" },
    { separator: true },
    { label: "Delete", action: "remove-card", danger: true },
  ], x, y);
}

function openHomeShortcutAreaMenu(x, y) {
  menuContext = { kind: "home" };
  openHomeShortcutMenu([
    { label: "Add new group", action: "add-group" },
  ], x, y);
}

async function runMenuAction(action) {
  const context = menuContext;
  closeHomeShortcutMenu();
  if (!context) return;
  if (action === "add-group") return void openAddGroupFlow();
  const { groupId, cardId } = context;
  const group = shortcutsDocument.groups.find((item) => item.id === groupId);
  if (!group) return;

  if (action === "add-card") return void openAddCardFlow(groupId);
  if (action === "rename-group") {
    const title = await promptForName({ title: "Rename Group", label: "Group name", value: group.title });
    if (title === null) return;
    return void commit(renameGroup(shortcutsDocument, groupId, title));
  }
  if (action === "move-group-up") return void commit(moveGroup(shortcutsDocument, groupId, -1));
  if (action === "move-group-down") return void commit(moveGroup(shortcutsDocument, groupId, 1));
  if (action === "delete-group") {
    const confirmed = await shell.showAppConfirm?.({
      title: "Delete Group",
      message: group.cards.length
        ? `Delete "${group.title}" and its ${group.cards.length} card(s)?`
        : `Delete "${group.title}"?`,
      okText: "Delete",
    });
    if (!confirmed) return;
    return void commit(removeGroup(shortcutsDocument, groupId));
  }

  const card = group.cards.find((item) => item.id === cardId);
  if (!card) return;
  if (action === "rename-card") {
    const label = await promptForName({ title: "Rename Card", label: "Card name", value: card.label });
    if (label === null) return;
    return void commit(renameCard(shortcutsDocument, groupId, cardId, label));
  }
  if (action === "remove-card") return void commit(removeCard(shortcutsDocument, groupId, cardId));
}

/* ------------------------------------------------------------------- flows */

async function openAddGroupFlow() {
  const title = await promptForName({ title: "New Group", label: "Group name", value: "", okText: "Create" });
  if (title === null) return;
  const result = addGroup(shortcutsDocument, title);
  if (result.error) return reportError(result.error);
  await commit(result.document);
}

async function openAddCardFlow(preferredGroupId) {
  if (!shortcutsDocument.groups.length) {
    const title = await promptForName({ title: "New Group", label: "Group name", value: "", okText: "Create" });
    if (title === null) return;
    const created = addGroup(shortcutsDocument, title);
    if (created.error) return reportError(created.error);
    await commit(created.document);
    return void openAddCardFlow(created.groupId);
  }
  const picked = await promptForCard(preferredGroupId || shortcutsDocument.groups[0].id);
  if (!picked) return;
  const result = addCard(shortcutsDocument, picked.groupId, { label: picked.label, target: picked.target });
  if (result.error) return reportError(result.error);
  await commit(result.document);
}

function activateCard(groupId, cardId) {
  const group = shortcutsDocument.groups.find((item) => item.id === groupId);
  const card = group?.cards.find((item) => item.id === cardId);
  if (!card) return;
  shell.openShellActivityHistoryEntry?.(card.target);
}

/* ------------------------------------------------ press-and-hold reordering */

function cardElements(groupEl) {
  return Array.from(groupEl.querySelectorAll(".homeShortcutCard"));
}

// A drag never touches the DOM: the card order stays put and every card is drawn at its slot with a
// transform. Reordering the DOM mid-drag meant every pointer move re-measured boxes that were still
// animating from the previous move, and the cards under the cursor kept switching hover state, so
// the preview fought itself. Fixed slots make each move one settled 120ms transform instead.
//
// Every custom group is measured, not just the one the card came from, so a card can be carried
// into another group. A group's last slot is its Add card tile: that is exactly where an incoming
// card lands, which is why the tile is measured with the cards and hidden for the drag.
function slotsFor(groupEl, elements) {
  const base = groupEl.getBoundingClientRect();
  return elements.map((el) => {
    const rect = el.getBoundingClientRect();
    return { x: rect.left - base.left, y: rect.top - base.top, w: rect.width, h: rect.height };
  });
}

function dragGroups() {
  return Array.from(containerEl.querySelectorAll(".homeCustomGroup")).map((groupEl) => {
    const cards = cardElements(groupEl);
    const tile = groupEl.querySelector(".homeShortcutAddCard");
    return {
      groupEl,
      groupId: groupEl.getAttribute("data-group-id") || "",
      cards,
      slots: slotsFor(groupEl, tile ? [...cards, tile] : cards),
      full: cards.length >= MAX_CARDS_PER_GROUP,
    };
  });
}

// Slots are stored relative to their group so a scroll during the drag cannot stale them.
function groupOrigin(group) {
  const base = group.groupEl.getBoundingClientRect();
  return { left: base.left, top: base.top };
}

function positionDraggedCard() {
  const { cardEl, sourceGroup, fromIndex, grabX, grabY, x, y } = dragState;
  const origin = groupOrigin(sourceGroup);
  const slot = sourceGroup.slots[fromIndex];
  cardEl.style.transform = `translate(${x - grabX - origin.left - slot.x}px, ${y - grabY - origin.top - slot.y}px)`;
}

// Groups stack vertically and span the row, so the pointer's y alone picks one. A pointer between
// groups keeps the current target rather than snapping back to the source.
function groupAt(y) {
  const { groups, targetGroup } = dragState;
  for (const group of groups) {
    if (group.full && group !== dragState.sourceGroup) continue;
    const rect = group.groupEl.getBoundingClientRect();
    if (y >= rect.top && y <= rect.bottom) return group;
  }
  return targetGroup;
}

// The slot the pointer sits on. Centers come from the frozen slot list, so the answer only changes
// when the pointer actually crosses into another slot. The source group offers one slot per card;
// any other group offers one more, for landing after its last card.
function slotIndexIn(group, x, y) {
  const origin = groupOrigin(group);
  const count = Math.min(
    group === dragState.sourceGroup ? group.cards.length : group.cards.length + 1,
    group.slots.length,
  );
  let best = 0;
  let bestDistance = Infinity;
  for (let index = 0; index < count; index += 1) {
    const slot = group.slots[index];
    const dx = x - (origin.left + slot.x + (slot.w / 2));
    const dy = y - (origin.top + slot.y + (slot.h / 2));
    const distance = (dx * dx) + (dy * dy);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return best;
}

function slideCard(el, group, fromSlot, toSlot) {
  const from = group.slots[fromSlot];
  const to = group.slots[toSlot] || from;
  // Left set even when it resolves to no offset: an inline transform keeps the stylesheet's hover
  // lift from nudging a card that the pointer happens to pass over.
  el.style.transform = `translate(${to.x - from.x}px, ${to.y - from.y}px)`;
}

function previewDrop(targetGroup, toIndex) {
  if (targetGroup === dragState.targetGroup && toIndex === dragState.toIndex) return;
  dragState.targetGroup = targetGroup;
  dragState.toIndex = toIndex;

  const { groups, sourceGroup, fromIndex, cardEl } = dragState;
  for (const group of groups) {
    group.groupEl.classList.toggle("isDropTarget", group === targetGroup && group !== sourceGroup);
    if (group === targetGroup && group === sourceGroup) {
      // A reorder inside one group: rebuild the order and send every other card to its new slot.
      const order = group.cards.filter((_, index) => index !== fromIndex);
      order.splice(toIndex, 0, cardEl);
      order.forEach((el, index) => {
        if (el !== cardEl) slideCard(el, group, group.cards.indexOf(el), index);
      });
    } else if (group === sourceGroup) {
      // The card is leaving: the cards behind it close the gap.
      group.cards.forEach((el, index) => {
        if (el !== cardEl) slideCard(el, group, index, index > fromIndex ? index - 1 : index);
      });
    } else if (group === targetGroup) {
      // The card is arriving: the cards from the drop slot on open one.
      group.cards.forEach((el, index) => slideCard(el, group, index, index >= toIndex ? index + 1 : index));
    } else {
      group.cards.forEach((el, index) => slideCard(el, group, index, index));
    }
  }
}

function endGesture(drop) {
  window.removeEventListener("pointermove", onGesturePointerMove, true);
  window.removeEventListener("pointerup", onGesturePointerEnd, true);
  window.removeEventListener("pointercancel", onGesturePointerEnd, true);

  if (holdState) {
    window.clearTimeout(holdState.timer);
    holdState.cardEl.classList.remove("isHoldPending");
    holdState = null;
  }
  if (!dragState) return;

  const { cardEl, sourceGroup, targetGroup, cardId, fromIndex, toIndex, pointerId } = dragState;
  dragState = null;
  try { cardEl.releasePointerCapture(pointerId); } catch { /* pointer already gone */ }
  suppressClickUntil = performance.now() + CLICK_SUPPRESS_MS;

  // A cancel or a same-slot drop still re-renders: that is what clears the preview transforms and
  // restores the persisted order after an Escape.
  if (!drop || (targetGroup === sourceGroup && toIndex === fromIndex)) {
    cardEl.classList.remove("isDragging");
    containerEl?.classList.remove("isCardDragging");
    return void renderHomeShortcuts();
  }

  // Land in the slot the preview has been holding open before the re-render swaps in the real
  // order, so the card settles into the gap instead of teleporting out of the cursor.
  const next = placeCard(shortcutsDocument, sourceGroup.groupId, cardId, targetGroup.groupId, toIndex);
  const from = groupOrigin(sourceGroup);
  const to = groupOrigin(targetGroup);
  const fromSlot = sourceGroup.slots[fromIndex];
  const toSlot = targetGroup.slots[toIndex];
  cardEl.style.transition = `transform ${DROP_SETTLE_MS}ms ease`;
  cardEl.style.transform = `translate(${(to.left + toSlot.x) - (from.left + fromSlot.x)}px, ${(to.top + toSlot.y) - (from.top + fromSlot.y)}px)`;
  pendingDrop = window.setTimeout(() => {
    pendingDrop = null;
    cardEl.classList.remove("isDragging");
    containerEl?.classList.remove("isCardDragging");
    void commit(next);
  }, DROP_SETTLE_MS);
}

function startDrag() {
  const { cardEl, pointerId, grabX, grabY, startX, startY } = holdState;
  const groupEl = cardEl.closest(".homeCustomGroup");
  if (!groupEl || !containerEl) return void endGesture(false);
  cardEl.classList.remove("isHoldPending");
  holdState = null;

  // Measured before the tiles are hidden, so a hidden tile still reports the slot it occupies.
  const groups = dragGroups();
  const sourceGroup = groups.find((group) => group.groupEl === groupEl);
  if (!sourceGroup) return void endGesture(false);
  const fromIndex = sourceGroup.cards.indexOf(cardEl);
  dragState = {
    cardEl,
    cardId: cardEl.getAttribute("data-card-id") || "",
    groups,
    sourceGroup,
    targetGroup: sourceGroup,
    fromIndex,
    toIndex: fromIndex,
    pointerId,
    grabX,
    grabY,
    x: startX,
    y: startY,
  };
  cardEl.classList.add("isDragging");
  containerEl.classList.add("isCardDragging");
  try { cardEl.setPointerCapture(pointerId); } catch { /* mouse without capture support */ }
  positionDraggedCard();
}

function onGesturePointerMove(e) {
  if (dragState) {
    if (e.pointerId !== dragState.pointerId) return;
    dragState.x = e.clientX;
    dragState.y = e.clientY;
    positionDraggedCard();
    const group = groupAt(e.clientY);
    previewDrop(group, slotIndexIn(group, e.clientX, e.clientY));
    return;
  }
  if (!holdState || e.pointerId !== holdState.pointerId) return;
  if (Math.abs(e.clientX - holdState.startX) > HOLD_CANCEL_DISTANCE
    || Math.abs(e.clientY - holdState.startY) > HOLD_CANCEL_DISTANCE) endGesture(false);
}

function onGesturePointerEnd(e) {
  const pointerId = dragState?.pointerId ?? holdState?.pointerId;
  if (pointerId !== undefined && e.pointerId !== pointerId) return;
  const holdWasPending = !dragState && !!holdState;
  const holdElapsedMs = holdWasPending ? performance.now() - holdState.startedAt : 0;
  const isQuickClick = e.type === "pointerup" && holdElapsedMs <= CLICK_TO_OPEN_MS;
  if (holdWasPending && !isQuickClick) suppressClickUntil = performance.now() + CLICK_SUPPRESS_MS;
  endGesture(!holdWasPending);
}

// A press that arrives while the previous drop is still settling is ignored: the re-render that
// closes that drop would detach the card this hold is about to track.
function beginHold(cardEl, e) {
  if (dragState || pendingDrop) return;
  endGesture(false);
  const rect = cardEl.getBoundingClientRect();
  holdState = {
    cardEl,
    pointerId: e.pointerId,
    startX: e.clientX,
    startY: e.clientY,
    grabX: e.clientX - rect.left,
    grabY: e.clientY - rect.top,
    startedAt: performance.now(),
    timer: window.setTimeout(startDrag, HOLD_TO_DRAG_MS),
  };
  cardEl.classList.add("isHoldPending");
  window.addEventListener("pointermove", onGesturePointerMove, true);
  window.addEventListener("pointerup", onGesturePointerEnd, true);
  window.addEventListener("pointercancel", onGesturePointerEnd, true);
}

/* ------------------------------------------------------------------ wiring */

function wireOnce() {
  if (wired) return;
  wired = true;

  document.addEventListener("click", (e) => {
    const menu = $("homeShortcutMenu");
    if (menu?.classList.contains("open") && !menu.contains(e.target)) closeHomeShortcutMenu();
  }, true);
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    endGesture(false);
    closeHomeShortcutMenu();
    if (namePromptResolve) closeNameDialog(null);
    if (addCardResolve) closeAddCardDialog(null);
  });

  $("homeShortcutMenu")?.addEventListener("click", (e) => {
    const item = e.target?.closest?.(".homeShortcutMenuItem");
    if (!item || item.classList.contains("disabled")) return;
    void runMenuAction(item.getAttribute("data-action") || "");
  });

  $("homeNameOkBtn")?.addEventListener("click", () => {
    const value = String($("homeNameInput")?.value || "").trim();
    if (!value) return;
    closeNameDialog(value);
  });
  $("homeNameCancelBtn")?.addEventListener("click", () => closeNameDialog(null));
  $("homeNameInput")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    $("homeNameOkBtn")?.click();
  });
  $("homeNameOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("homeNameOverlay")) closeNameDialog(null);
  });

  $("homeAddCardOkBtn")?.addEventListener("click", () => closeAddCardDialog(true));
  $("homeAddCardCancelBtn")?.addEventListener("click", () => closeAddCardDialog(null));
  $("homeAddCardOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("homeAddCardOverlay")) closeAddCardDialog(null);
  });

  containerEl?.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target?.closest?.("[data-menu]")) return;
    const cardEl = e.target?.closest?.(".homeShortcutCard");
    if (cardEl) beginHold(cardEl, e);
  });

  containerEl?.addEventListener("click", (e) => {
    // The click that ends a drag must not also open the card that was dragged.
    if (performance.now() < suppressClickUntil) {
      suppressClickUntil = 0;
      return;
    }
    const menuBtn = e.target?.closest?.("[data-menu]");
    if (menuBtn) {
      e.stopPropagation();
      const rect = menuBtn.getBoundingClientRect();
      const groupId = menuBtn.closest("[data-group-id]")?.getAttribute("data-group-id") || "";
      if (menuBtn.getAttribute("data-menu") === "group") openGroupMenu(groupId, rect.left, rect.bottom + 4);
      else openCardMenu(groupId, menuBtn.closest("[data-card-id]")?.getAttribute("data-card-id") || "", rect.left, rect.bottom + 4);
      return;
    }
    const actionBtn = e.target?.closest?.("[data-action]");
    if (actionBtn) {
      const action = actionBtn.getAttribute("data-action");
      if (action === "add-group") return void openAddGroupFlow();
      if (action === "add-card") {
        return void openAddCardFlow(actionBtn.closest("[data-group-id]")?.getAttribute("data-group-id") || "");
      }
      return;
    }
    const card = e.target?.closest?.(".homeShortcutCard");
    if (card) activateCard(card.getAttribute("data-group-id") || "", card.getAttribute("data-card-id") || "");
  });

  containerEl?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target?.closest?.(".homeShortcutCard");
    if (!card) return;
    e.preventDefault();
    activateCard(card.getAttribute("data-group-id") || "", card.getAttribute("data-card-id") || "");
  });

  containerEl?.addEventListener("contextmenu", (e) => {
    const card = e.target?.closest?.(".homeShortcutCard");
    if (card) {
      e.preventDefault();
      openCardMenu(card.getAttribute("data-group-id") || "", card.getAttribute("data-card-id") || "", e.clientX, e.clientY);
      return;
    }
    const groupTitle = e.target?.closest?.(".homeCustomGroupTitle");
    if (!groupTitle) return;
    e.preventDefault();
    openGroupMenu(groupTitle.closest("[data-group-id]")?.getAttribute("data-group-id") || "", e.clientX, e.clientY);
  });

  const homePageEl = containerEl?.closest(".homeLaunchPage");
  homePageEl?.addEventListener("contextmenu", (e) => {
    const lastGroup = Array.from(homePageEl.querySelectorAll(".homeGroup")).at(-1);
    if (!lastGroup || e.clientY < lastGroup.getBoundingClientRect().bottom) return;
    e.preventDefault();
    openHomeShortcutAreaMenu(e.clientX, e.clientY);
  });
}

export function initHomeShortcuts(container) {
  if (!container) return;
  containerEl = container;
  wireOnce();
  renderHomeShortcuts();
  if (loadPromise) return;
  loadPromise = loadHomeShortcuts()
    .then((document) => {
      shortcutsDocument = document;
      renderHomeShortcuts();
    })
    .catch((err) => {
      reportError(`Could not load Home shortcuts. ${err?.message || err}`);
    });
}
