import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The history stores are browser modules with site-absolute imports, so each one is loaded from a
// data: URL after its imports are pointed at the real files on disk.
const fileUrl = (path) => new URL(path, import.meta.url).href;
const read = async (path) => (await readFile(new URL(path, import.meta.url), "utf8")).replaceAll("\r\n", "\n");
const loadModule = (source) => import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

class MemoryStorage {
  constructor() { this.map = new Map(); }
  getItem(key) { return this.map.has(key) ? this.map.get(key) : null; }
  setItem(key, value) { this.map.set(key, String(value)); }
  removeItem(key) { this.map.delete(key); }
  clear() { this.map.clear(); }
}
globalThis.localStorage = new MemoryStorage();

const localDay = await loadModule(await read("../ui/shared/services/local_day.js"));
const workspaceHistory = await loadModule(
  (await read("../ui/shared/services/workspace_history.js"))
    .replace('"/ui/shared/services/local_day.js?v=20260828a"', JSON.stringify(fileUrl("../ui/shared/services/local_day.js"))),
);
const browsingHistory = await loadModule(
  (await read("../ui/shell/browsing_history.js"))
    .replace('"/ui/shared/services/valid_value_lists.js"', JSON.stringify(fileUrl("../ui/shared/services/valid_value_lists.js")))
    .replace('"/ui/shared/services/local_day.js?v=20260828a"', JSON.stringify(fileUrl("../ui/shared/services/local_day.js"))),
);

const DAY = 24 * 60 * 60 * 1000;
// Noon today and noon yesterday: far from midnight, so the two stay on different local days
// however long the test takes.
const today = new Date();
today.setHours(12, 0, 0, 0);
const TODAY = today.getTime();
const YESTERDAY = TODAY - DAY;

test("localDayKey names the local calendar day and rejects a missing timestamp", () => {
  const { localDayKey } = localDay;
  assert.equal(localDayKey(TODAY), `${today.getFullYear()}-${today.getMonth() + 1}-${today.getDate()}`);
  assert.equal(localDayKey(TODAY), localDayKey(TODAY + 60 * 60 * 1000));
  assert.notEqual(localDayKey(TODAY), localDayKey(YESTERDAY));
  assert.equal(localDayKey(0), "");
  assert.equal(localDayKey("nope"), "");
});

test("a File Browser folder opened again today keeps its record from yesterday", () => {
  localStorage.clear();
  const { pushWorkspaceHistoryEntry, getWorkspaceHistoryEntries } = workspaceHistory;
  pushWorkspaceHistoryEntry({ path: "E:\\Arco Server\\shared\\macros", ts: YESTERDAY });
  pushWorkspaceHistoryEntry({ path: "E:\\Arco Server\\shared\\macros", ts: TODAY });
  let entries = getWorkspaceHistoryEntries();
  assert.deepEqual(entries.map((entry) => entry.ts), [TODAY, YESTERDAY]);

  // Opening it once more today replaces only today's record, however the path is spelled.
  pushWorkspaceHistoryEntry({ path: "e:/arco server/shared/macros", ts: TODAY + 1000 });
  entries = getWorkspaceHistoryEntries();
  assert.deepEqual(entries.map((entry) => entry.ts), [TODAY + 1000, YESTERDAY]);
});

test("a dataset viewed again today keeps its record from yesterday", () => {
  localStorage.clear();
  const { pushBrowsingHistoryEntry, getBrowsingHistoryEntries } = browsingHistory;
  const dataset = { project: "Commercial Auto 2026Q2", path: "Commercial Auto/Liability", tri: "Paid Loss" };
  pushBrowsingHistoryEntry({ ...dataset, ts: YESTERDAY });
  pushBrowsingHistoryEntry({ ...dataset, ts: TODAY });
  let entries = getBrowsingHistoryEntries();
  assert.deepEqual(entries.map((entry) => entry.ts), [TODAY, YESTERDAY]);

  pushBrowsingHistoryEntry({ ...dataset, tri: "paid loss", ts: TODAY + 1000 });
  entries = getBrowsingHistoryEntries();
  assert.deepEqual(entries.map((entry) => entry.ts), [TODAY + 1000, YESTERDAY]);
  assert.equal(entries[0].tri, "paid loss");
});

test("the shell activity store keys its records by page and day and keeps enough of them", async () => {
  const source = await read("../ui/shell/shell_activity_history.js");
  assert.match(source, /import \{ localDayKey \} from "\/ui\/shared\/services\/local_day\.js\?v=/u);
  assert.match(source, /return identity \? `\$\{identity\}\|\$\{localDayKey\(entry\.ts\)\}` : "";/u);
  assert.match(source, /const MAX_ACTIVITY_ENTRIES = 60;/u);
});
