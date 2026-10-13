import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Home stays fixed while other docked tabs are reordered", async () => {
  const strip = await read("../ui/shell/tab_strip.js");
  const state = await read("../ui/shell/shell_state.js");

  assert.match(
    strip,
    /return id && id !== "home" && id !== draggedTabId;/u,
    "Home must not be a reorder-preview target",
  );
  assert.match(
    strip,
    /if \(!id \|\| id === "home" \|\| id === draggedTabId \|\| el\.classList\.contains\("placeholder"\)\) return;/u,
    "Home must not participate in reorder-preview animation",
  );
  assert.match(state, /export function ensureHomeTabFirst\(tabs = state\.tabs\)/u);
  assert.match(state, /const \[home\] = tabs\.splice\(homeIndex, 1\);\s*tabs\.unshift\(home\);/u);
  assert.match(state, /export function ensureActiveTabInvariant\(\) \{\s*ensureHomeTabFirst\(\);/u);
  assert.match(state, /export function buildShellStateSnapshot\(\) \{\s*ensureHomeTabFirst\(\);/u);
});
