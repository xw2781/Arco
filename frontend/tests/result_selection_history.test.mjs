import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createResultSelectionHistory } from "../ui/method_pages/result_selection/result_selection_history.js";

const frontendRoot = new URL("../", import.meta.url);

// A page stand-in: `state.value` is the method, and flushes run only when the
// test calls `settle()`, the way the page's deferred capture runs after a change.
function harness({ mergeMs = 1500 } = {}) {
  const page = { value: "a", clock: 0, queued: null, restored: [] };
  const history = createResultSelectionHistory({
    capture: () => page.value,
    restore: async (snapshot) => {
      page.restored.push(snapshot);
      page.value = snapshot;
    },
    mergeMs,
    now: () => page.clock,
    schedule: (callback) => {
      page.queued = callback;
      return 1;
    },
    cancelSchedule: () => {
      page.queued = null;
    },
  });
  const settle = () => {
    const callback = page.queued;
    page.queued = null;
    callback?.();
  };
  const edit = (value, key = "") => {
    page.value = value;
    history.noteEdit(key);
    settle();
  };
  history.reset();
  return { page, history, settle, edit };
}

test("undo and redo walk back and forth through edits", async () => {
  const { page, history, edit } = harness();
  edit("b");
  edit("c");
  assert.equal(history.canUndo, true);
  await history.undo();
  assert.equal(page.value, "b");
  await history.undo();
  assert.equal(page.value, "a");
  assert.equal(history.canUndo, false);
  await history.redo();
  assert.equal(page.value, "b");
  assert.equal(history.canRedo, true);
});

test("a new edit after undo discards the redo branch", async () => {
  const { page, history, edit } = harness();
  edit("b");
  await history.undo();
  edit("x");
  assert.equal(history.canRedo, false);
  await history.undo();
  assert.equal(page.value, "a");
});

test("a render after an edit joins that edit's step", async () => {
  const { page, history, edit, settle } = harness();
  edit("b");
  // A source finishes loading for the same edit.
  page.value = "b-loaded";
  history.noteRender();
  settle();
  await history.undo();
  assert.equal(page.value, "a");
  await history.redo();
  assert.equal(page.value, "b-loaded");
});

test("typing into one field within the merge window is one step", async () => {
  const { page, history, edit } = harness();
  edit("1", "field:weight");
  page.clock += 400;
  edit("15", "field:weight");
  page.clock += 5000;
  edit("150", "field:weight");
  await history.undo();
  assert.equal(page.value, "15");
  await history.undo();
  assert.equal(page.value, "a");
});

test("an edit that leaves the method unchanged records no step", () => {
  const { history, edit } = harness();
  edit("a");
  assert.equal(history.canUndo, false);
});

test("reset forgets every step", () => {
  const { history, edit } = harness();
  edit("b");
  history.reset();
  assert.equal(history.canUndo, false);
  assert.equal(history.canRedo, false);
});

test("edits reported while a step is being restored are ignored", async () => {
  const page = { value: "a" };
  let history = null;
  history = createResultSelectionHistory({
    capture: () => page.value,
    restore: async (snapshot) => {
      page.value = snapshot;
      history.noteEdit("");
    },
    schedule: (callback) => setTimeout(callback, 0),
  });
  history.reset();
  page.value = "b";
  history.noteEdit("");
  history.flush();
  await history.undo();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(page.value, "a");
  assert.equal(history.canRedo, true);
  assert.equal(history.canUndo, false);
});

test("Result Selection wires page-wide undo through the save bar and Ctrl+Z", async () => {
  const [html, main, ui, data, grids, model] = await Promise.all([
    "result_selection.html",
    "result_selection_main.js",
    "result_selection_ui.js",
    "result_selection_data.js",
    "result_selection_grids.js",
    "result_selection_model.js",
  ].map((name) => readFile(new URL(`ui/method_pages/result_selection/${name}`, frontendRoot), "utf8")));
  assert.match(html, /class="rsSaveBar">[\s\S]*id="rsUndoBtn"[\s\S]*id="rsRedoBtn"[\s\S]*id="rsSaveBtn"/u);
  assert.match(main, /ctx\.rsHistory = createResultSelectionHistory\(\{/u);
  assert.match(ui, /ctx\.rsHistory\?\.noteEdit\(historyEditKey\(\)\)/u);
  assert.match(ui, /historyKey === "z" \|\| historyKey === "y"/u);
  assert.match(data, /async function restoreHistorySnapshot\(snapshotText\)/u);
  assert.match(grids, /ctx\.rsHistory\?\.noteRender\(\)/u);
  // Snapshots must compare equal for an unchanged method.
  assert.match(model, /delete method\.method_metadata;/u);
});
