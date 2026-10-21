/*
===============================================================================
Result Selection History - page-wide undo/redo

Every step is a whole-method snapshot (the same text the page keeps for
Cancel), taken after a change settles rather than before each edit. A user
edit marks the next difference as a new step; a later render that changes the
method without an edit, such as a source finishing loading, joins the step
that started it. Repeated edits to one field within a short window, typing a
number for example, merge into one step.
===============================================================================
*/

const DEFAULT_LIMIT = 100;
const DEFAULT_MERGE_MS = 1500;

export function createResultSelectionHistory({
  capture,
  restore,
  onStateChange = () => {},
  limit = DEFAULT_LIMIT,
  mergeMs = DEFAULT_MERGE_MS,
  now = () => Date.now(),
  schedule = (callback) => setTimeout(callback, 0),
  cancelSchedule = (handle) => clearTimeout(handle),
} = {}) {
  let current = null;
  let undoStack = [];
  let redoStack = [];
  let pendingEdit = null;
  let lastEdit = null;
  let timer = null;
  let applying = false;

  function notify() {
    onStateChange({ canUndo: undoStack.length > 0, canRedo: redoStack.length > 0 });
  }

  function cancelPending() {
    if (timer !== null) cancelSchedule(timer);
    timer = null;
  }

  function scheduleFlush() {
    if (applying || timer !== null) return;
    timer = schedule(() => {
      timer = null;
      flush();
    });
  }

  function flush() {
    cancelPending();
    if (applying) return;
    const snapshot = capture();
    const edit = pendingEdit;
    pendingEdit = null;
    if (current === null) {
      current = snapshot;
      return;
    }
    if (snapshot === current) return;
    if (edit) {
      const merges = !!edit.key
        && lastEdit?.key === edit.key
        && edit.at - lastEdit.at <= mergeMs
        && undoStack.length > 0;
      if (!merges) {
        undoStack.push(current);
        while (undoStack.length > limit) undoStack.shift();
      }
      redoStack = [];
      lastEdit = edit;
    }
    current = snapshot;
    notify();
  }

  function noteEdit(key = "") {
    if (applying) return;
    pendingEdit = { key: String(key || ""), at: now() };
    scheduleFlush();
  }

  function noteRender() {
    scheduleFlush();
  }

  function reset() {
    cancelPending();
    pendingEdit = null;
    lastEdit = null;
    undoStack = [];
    redoStack = [];
    current = capture();
    notify();
  }

  async function travel(from, to) {
    if (applying) return false;
    flush();
    if (!from.length) return false;
    const target = from.pop();
    to.push(current);
    applying = true;
    try {
      await restore(target);
    } finally {
      applying = false;
      cancelPending();
      pendingEdit = null;
      lastEdit = null;
      current = target;
      notify();
    }
    return true;
  }

  return {
    noteEdit,
    noteRender,
    flush,
    reset,
    undo: () => travel(undoStack, redoStack),
    redo: () => travel(redoStack, undoStack),
    get canUndo() { return undoStack.length > 0; },
    get canRedo() { return redoStack.length > 0; },
    get applying() { return applying; },
  };
}
