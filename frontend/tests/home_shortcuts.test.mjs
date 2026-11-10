import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  MAX_CARDS_PER_GROUP,
  MAX_GROUPS,
  addCard,
  addGroup,
  createEmptyHomeShortcuts,
  moveGroup,
  placeCard,
  normalizeCardTarget,
  normalizeHomeShortcuts,
  removeCard,
  removeGroup,
  renameCard,
  renameGroup,
} from "../ui/shell/home_shortcuts.js";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

const PI_TARGET = { tabType: "project_instance", title: "NJ_Annual", projectName: "NJ_Annual" };
const WORKSPACE_TARGET = { tabType: "file_explorer", title: "Rates", path: "E:\\Arco Server\\rates" };

function seedGroup(title = "Q3 Close") {
  const created = addGroup(createEmptyHomeShortcuts(), title);
  assert.equal(created.error, "");
  return created;
}

test("a card target is a browsing-history descriptor without the activity timestamp", () => {
  const target = normalizeCardTarget({ ...PI_TARGET, ts: 1737000000000 });
  assert.deepEqual(target, { tabType: "project_instance", title: "NJ_Annual", projectName: "NJ_Annual" });
  assert.ok(!("ts" in target));
});

test("File Browser targets keep the folder they were pinned from", () => {
  const target = normalizeCardTarget(WORKSPACE_TARGET);
  assert.equal(target.tabType, "file_explorer");
  assert.equal(target.path, "E:\\Arco Server\\rates");
});

test("a target the shell cannot reopen is rejected", () => {
  assert.equal(normalizeCardTarget({ tabType: "cape_cod", title: "Cape Cod" }), null);
  assert.equal(normalizeCardTarget({ tabType: "home", title: "Home" }), null);
  assert.equal(normalizeCardTarget(null), null);
});

test("normalization drops invalid cards, dedupes ids, and stamps the version", () => {
  const document = normalizeHomeShortcuts({
    groups: [
      {
        id: "grp_a",
        title: "  Reserving  ",
        cards: [
          { id: "crd_a", label: "Keep", target: PI_TARGET },
          { id: "crd_b", label: "Drop", target: { tabType: "cape_cod", title: "CC" } },
          { id: "crd_a", label: "Duplicate id gets a fresh one", target: WORKSPACE_TARGET },
          { label: "No id", target: WORKSPACE_TARGET },
        ],
      },
      "not a group",
    ],
  });

  assert.equal(document.version, 1);
  assert.equal(document.groups.length, 1);
  assert.equal(document.groups[0].title, "Reserving");
  const cards = document.groups[0].cards;
  assert.equal(cards.length, 3);
  assert.equal(new Set(cards.map((card) => card.id)).size, 3);
  assert.equal(cards[0].label, "Keep");
});

test("titles and labels are clipped and fall back rather than going blank", () => {
  const long = "x".repeat(200);
  const created = addGroup(createEmptyHomeShortcuts(), long);
  assert.equal(created.document.groups[0].title.length, 60);

  const blank = addGroup(createEmptyHomeShortcuts(), "   ");
  assert.equal(blank.document.groups[0].title, "Untitled group");

  const withCard = addCard(created.document, created.groupId, { label: "  ", target: PI_TARGET });
  assert.equal(withCard.error, "");
  assert.equal(withCard.document.groups[0].cards[0].label, "NJ_Annual");
});

test("group and card caps are enforced with a reported reason", () => {
  let document = createEmptyHomeShortcuts();
  for (let i = 0; i < MAX_GROUPS; i += 1) {
    const created = addGroup(document, `Group ${i}`);
    assert.equal(created.error, "");
    document = created.document;
  }
  const overflowGroup = addGroup(document, "One too many");
  assert.match(overflowGroup.error, /at most 24/u);
  assert.equal(overflowGroup.document.groups.length, MAX_GROUPS);

  let single = seedGroup().document;
  const groupId = single.groups[0].id;
  for (let i = 0; i < MAX_CARDS_PER_GROUP; i += 1) {
    const created = addCard(single, groupId, { label: `Card ${i}`, target: PI_TARGET });
    assert.equal(created.error, "");
    single = created.document;
  }
  const overflowCard = addCard(single, groupId, { label: "One too many", target: PI_TARGET });
  assert.match(overflowCard.error, /at most 48/u);
  assert.equal(overflowCard.document.groups[0].cards.length, MAX_CARDS_PER_GROUP);
});

test("adding a card to a missing group reports instead of throwing", () => {
  const result = addCard(createEmptyHomeShortcuts(), "grp_missing", { label: "x", target: PI_TARGET });
  assert.match(result.error, /no longer exists/u);
});

test("rename, remove, and reorder operate without mutating the previous document", () => {
  const seeded = seedGroup();
  const groupId = seeded.groupId;
  const withCards = ["First", "Second"].reduce((document, label) => {
    const created = addCard(document, groupId, { label, target: PI_TARGET });
    assert.equal(created.error, "");
    return created.document;
  }, seeded.document);
  const [firstId, secondId] = withCards.groups[0].cards.map((card) => card.id);

  const renamed = renameCard(withCards, groupId, firstId, "Renamed");
  assert.equal(renamed.groups[0].cards[0].label, "Renamed");
  assert.equal(withCards.groups[0].cards[0].label, "First", "the source document is left untouched");

  const reordered = placeCard(withCards, groupId, secondId, groupId, 0);
  assert.deepEqual(reordered.groups[0].cards.map((card) => card.label), ["Second", "First"]);
  assert.equal(placeCard(withCards, groupId, firstId, groupId, -1).groups[0].cards[0].label, "First");

  const removed = removeCard(withCards, groupId, firstId);
  assert.deepEqual(removed.groups[0].cards.map((card) => card.label), ["Second"]);

  const renamedGroup = renameGroup(withCards, groupId, "Renamed Group");
  assert.equal(renamedGroup.groups[0].title, "Renamed Group");
  assert.equal(removeGroup(withCards, groupId).groups.length, 0);
});

test("groups reorder", () => {
  const first = seedGroup("First");
  const second = addGroup(first.document, "Second");
  const withCard = addCard(second.document, first.groupId, { label: "Pinned", target: PI_TARGET });

  const reordered = moveGroup(withCard.document, second.groupId, -1);
  assert.deepEqual(reordered.groups.map((group) => group.title), ["Second", "First"]);
  assert.deepEqual(
    moveGroup(withCard.document, first.groupId, -1).groups.map((group) => group.title),
    ["First", "Second"],
    "moving past the first slot is a no-op",
  );
});

test("a dragged card lands on an absolute slot and out-of-range drops clamp", () => {
  const seeded = seedGroup();
  const groupId = seeded.groupId;
  const withCards = ["A", "B", "C"].reduce((document, label) => {
    const created = addCard(document, groupId, { label, target: PI_TARGET });
    assert.equal(created.error, "");
    return created.document;
  }, seeded.document);
  const [, , thirdId] = withCards.groups[0].cards.map((card) => card.id);
  const labels = (document) => document.groups[0].cards.map((card) => card.label);

  assert.deepEqual(labels(placeCard(withCards, groupId, thirdId, groupId, 0)), ["C", "A", "B"]);
  assert.deepEqual(labels(placeCard(withCards, groupId, thirdId, groupId, 9)), ["A", "B", "C"], "clamped to the last slot");
  assert.deepEqual(labels(placeCard(withCards, groupId, thirdId, groupId, -4)), ["C", "A", "B"], "clamped to the first slot");
  assert.deepEqual(labels(withCards), ["A", "B", "C"], "the source document is left untouched");
  assert.deepEqual(labels(placeCard(withCards, groupId, "crd_missing", groupId, 0)), ["A", "B", "C"]);
});

test("a card dropped on another group lands on the slot it was dropped, and a full group refuses it", () => {
  const first = seedGroup("First");
  const second = addGroup(first.document, "Second");
  let document = ["A", "B"].reduce((doc, label) => addCard(doc, second.groupId, { label, target: PI_TARGET }).document, second.document);
  document = addCard(document, first.groupId, { label: "Moved", target: WORKSPACE_TARGET }).document;
  const cardId = document.groups[0].cards[0].id;
  const labels = (doc, group) => doc.groups[group].cards.map((card) => card.label);

  const atFront = placeCard(document, first.groupId, cardId, second.groupId, 0);
  assert.deepEqual(labels(atFront, 1), ["Moved", "A", "B"]);
  assert.deepEqual(labels(atFront, 0), [], "the card leaves its old group");

  assert.deepEqual(labels(placeCard(document, first.groupId, cardId, second.groupId, 1), 1), ["A", "Moved", "B"]);
  assert.deepEqual(
    labels(placeCard(document, first.groupId, cardId, second.groupId, 2), 1),
    ["A", "B", "Moved"],
    "the tile slot appends, unlike a same-group move where the last slot is length - 1",
  );
  assert.deepEqual(labels(placeCard(document, first.groupId, cardId, second.groupId, 99), 1), ["A", "B", "Moved"]);
  assert.deepEqual(labels(document, 0), ["Moved"], "the source document is left untouched");

  let full = seedGroup("Full").document;
  const fullId = full.groups[0].id;
  for (let i = 0; i < MAX_CARDS_PER_GROUP; i += 1) full = addCard(full, fullId, { label: `Card ${i}`, target: PI_TARGET }).document;
  const spare = addGroup(full, "Spare");
  const withSpare = addCard(spare.document, spare.groupId, { label: "Stays", target: PI_TARGET }).document;
  const spareCardId = withSpare.groups[1].cards[0].id;
  const refused = placeCard(withSpare, spare.groupId, spareCardId, fullId, 0);
  assert.equal(refused.groups[0].cards.length, MAX_CARDS_PER_GROUP);
  assert.deepEqual(labels(refused, 1), ["Stays"], "a full group refuses the drop instead of losing the card");
});

test("every custom group ends with an add-card tile that opens the pin dialog", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /group\.cards\.map\(\(card\) => renderCard\(group, card\)\)\.join\(""\) \+ renderAddCardSlot\(group\)/u);
  assert.match(shortcutsView, /class="homeShortcutAddCard\$\{empty \? " isEmptyGroup" : ""\}" type="button" data-action="add-card"/u);
  assert.match(styles, /\.homeShortcutAddCard\s*\{[^}]*border:\s*1px dashed/su);
});

test("Home adds groups from a context menu below the last group", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");

  assert.doesNotMatch(shortcutsView, /homeAddGroupBtn/u);
  assert.match(shortcutsView, /function openHomeShortcutAreaMenu\(x, y\)/u);
  assert.match(shortcutsView, /\{ label: "Add new group", action: "add-group" \}/u);
  assert.match(shortcutsView, /if \(action === "add-group"\) return void openAddGroupFlow\(\);/u);
  assert.match(shortcutsView, /homePageEl\?\.addEventListener\("contextmenu"/u);
  assert.match(shortcutsView, /e\.clientY < lastGroup\.getBoundingClientRect\(\)\.bottom/u);
});

test("Home reveals a full-width click hint below the last group", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const styles = await read("../ui/shell/shell.css");
  const darkStyles = await read("../ui/shared/styles/themes/dark.css");

  assert.match(shortcutsView, /<div class="homeShortcutsFooter">/u);
  assert.doesNotMatch(shortcutsView, /<div class="homeShortcutsFooter"[^>]*data-action=/u);
  assert.match(shortcutsView, /<button class="homeAddGroupHint" type="button" data-action="add-group"/u);
  assert.match(shortcutsView, /class="homeAddGroupHint" type="button" data-action="add-group"[^>]*>\+ New group</u);
  assert.match(styles, /\.homeLaunchPage\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column/su);
  assert.match(styles, /\.homeShortcutsFooter\s*\{[^}]*flex:\s*1 1 0[^}]*border-top:\s*1px solid/su);
  assert.match(styles, /\.homeAddGroupHint\s*\{[^}]*display:\s*flex[^}]*justify-content:\s*center[^}]*border:\s*1px solid/su);
  assert.match(styles, /\.homeShortcutsFooter:hover \.homeAddGroupHint,\s*\.homeShortcutsFooter:focus-within \.homeAddGroupHint\s*\{[^}]*background:\s*var\(--ar-color-accent-soft/su);
  assert.match(darkStyles, /\.homeAddGroupHint\s*\{[^}]*background-color:\s*var\(--ar-color-canvas-subtle/su);
});

test("a card opens on a quick click, cancels an incomplete hold, and drags after a half-second", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /CLICK_TO_OPEN_MS = 200/u);
  assert.match(shortcutsView, /HOLD_TO_DRAG_MS = 500/u);
  assert.match(shortcutsView, /setTimeout\(startDrag, HOLD_TO_DRAG_MS\)/u);
  assert.match(shortcutsView, /isHoldPending/u);
  assert.match(shortcutsView, /const holdWasPending = !dragState && !!holdState;/u);
  assert.match(shortcutsView, /const holdElapsedMs = holdWasPending \? performance\.now\(\) - holdState\.startedAt : 0;/u);
  assert.match(shortcutsView, /const isQuickClick = e\.type === "pointerup" && holdElapsedMs <= CLICK_TO_OPEN_MS;/u);
  assert.match(shortcutsView, /if \(holdWasPending && !isQuickClick\) suppressClickUntil = performance\.now\(\) \+ CLICK_SUPPRESS_MS;/u);
  assert.match(shortcutsView, /endGesture\(!holdWasPending\);/u);
  assert.match(shortcutsView, /placeCard\(shortcutsDocument, sourceGroup\.groupId, cardId, targetGroup\.groupId, toIndex\)/u);
  assert.match(styles, /\.homeShortcutCard\.isHoldPending::after\s*\{[^}]*transform:\s*scaleX\(0\);[^}]*animation:\s*homeCardHoldFill 300ms linear 200ms forwards/su);
});

test("Home shortcut tooltips use the shared press-dismissed tooltip surface", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const sharedTooltip = await read("../ui/shared/components/tooltip/tooltip.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /import \{ attachArcrhoTooltip \} from "\.\.\/shared\/components\/tooltip\/tooltip\.js/u);
  assert.match(shortcutsView, /attachArcrhoTooltip\(card, "Hold to drag and reorder"\)/u);
  assert.match(sharedTooltip, /target\.addEventListener\("mousedown", cancel\)/u);
  assert.doesNotMatch(shortcutsView, /document\.body\.appendChild\(homeCardTooltipEl\)/u);
  assert.doesNotMatch(styles, /\.homeCardTooltip/u);
});

// The preview flickered while it reordered the DOM on every pointer move: each move re-measured
// boxes that were still animating, and hover state kept switching on the cards under the cursor.
test("the drop preview moves cards by transform against frozen slots instead of reordering the DOM", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /slots: slotsFor\(groupEl, tile \? \[\.\.\.cards, tile\] : cards\)/u);
  assert.match(shortcutsView, /previewDrop\(group, slotIndexIn\(group, e\.clientX, e\.clientY\)\)/u);
  assert.match(shortcutsView, /el\.style\.transform = `translate\(\$\{to\.x - from\.x\}px, \$\{to\.y - from\.y\}px\)`/u);
  assert.doesNotMatch(shortcutsView, /targetEl\.(after|before)\(cardEl\)/u, "the drag never reorders the DOM");
  assert.doesNotMatch(shortcutsView, /elementFromPoint/u, "the drop slot comes from frozen geometry");
  assert.match(styles, /\.homeShortcutGroups\.isCardDragging \.homeShortcutCard\s*\{[^}]*pointer-events:\s*none/su);
});

// The tile marks the slot an arriving card lands on, so its box has to survive the drag.
test("a drag measures every custom group and carries the card between them", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /containerEl\.querySelectorAll\("\.homeCustomGroup"\)/u);
  assert.match(shortcutsView, /full: cards\.length >= MAX_CARDS_PER_GROUP/u);
  assert.match(shortcutsView, /group === dragState\.sourceGroup \? group\.cards\.length : group\.cards\.length \+ 1/u);
  assert.match(shortcutsView, /classList\.toggle\("isDropTarget", group === targetGroup && group !== sourceGroup\)/u);
  assert.match(styles, /\.homeShortcutGroups\.isCardDragging \.homeShortcutAddCard\s*\{[^}]*visibility:\s*hidden/su);
  assert.match(styles, /\.homeCustomGroup\.isDropTarget\s*\{/su);
});

// Placement belongs to the drag, so the menu carries no second way to do it and the model carries
// no second definition of the move.
test("the card menu offers only rename and a red Delete", async () => {
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const model = await read("../ui/shell/home_shortcuts.js");
  const styles = await read("../ui/shell/shell.css");

  assert.match(shortcutsView, /\{ label: "Delete", action: "remove-card", danger: true \}/u);
  assert.doesNotMatch(shortcutsView, /move-card-left|move-card-right|move-card-to-group/u);
  assert.doesNotMatch(model, /export function (moveCard|moveCardToIndex|moveCardToGroup)\b/u);
  assert.match(styles, /\.homeShortcutMenuItem\.isDanger\s*\{[^}]*color:\s*var\(--ar-color-danger/su);
});

test("shortcuts persist under homeShortcuts in the local-user preferences document", async () => {
  const source = await read("../ui/shell/home_shortcuts.js");
  assert.match(source, /\/local-project\/preferences/u);
  assert.match(source, /JSON\.stringify\(\{ homeShortcuts: normalized \}\)/u);
});

test("Home renders custom groups and opens cards through the shared restore path", async () => {
  const view = await read("../ui/shell/home_view.js");
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");

  assert.match(view, /id="homeShortcutGroups"/u);
  assert.ok(
    view.indexOf('id="homeLaunchAutomationGroup"') < view.indexOf('id="homeShortcutGroups"'),
    "custom groups render below the fixed built-in groups",
  );
  assert.match(shortcutsView, /shell\.openShellActivityHistoryEntry\?\.\(card\.target\)/u);
  assert.match(shortcutsView, /shell\.buildShellActivityEntry/u);
  assert.doesNotMatch(shortcutsView, /from "\.\/tab_actions\.js/u);
});

test("built-in and custom cards share one icon source", async () => {
  const view = await read("../ui/shell/home_view.js");
  const shortcutsView = await read("../ui/shell/home_shortcuts_view.js");
  const icons = await read("../ui/shell/home_card_icons.js");

  assert.match(view, /homeCardIcon\("files"\)/u);
  assert.doesNotMatch(view, /<svg class="homeIcon"/u);
  assert.match(shortcutsView, /homeCardIconForTabType\(card\.target\.tabType\)/u);
  assert.match(icons, /project_instance: "projectInstance"/u);
});
