import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The dataset-index staleness watch must never flag this window's own writes.
// index.json is rewritten server-side (hosted saves, propagation, hosted index
// rebuilds), and a client stat over the mapped drive can echo pre-write
// metadata for ~10s afterwards, so the watch baselines on the signature the
// snapshot payload carries (statted by the process that wrote the file) and
// ignores polled signatures whose mtime is older than that baseline.

const cacheSource = await readFile(
  new URL("../ui/project_instance/project_instance_dataset_cache.js", import.meta.url),
  "utf8",
);
// The module is imported from a data: URL, which cannot resolve the app's
// absolute "/ui/..." specifiers, so every browser-only import is stubbed here.
const testableSource = cacheSource
  .replace(
    /^import \{ attachArcrhoTooltip \} from .*;\s*/u,
    "const attachArcrhoTooltip = () => {};\n",
  )
  .replace(
    /^import \{ publishProjectInstanceDatasetSnapshot \} from .*;\s*/mu,
    "const publishProjectInstanceDatasetSnapshot = () => true;\n",
  )
  .replace(
    /"\/ui\/shared\/utils\/timestamp\.js\?v=\d{8}[a-z]"/u,
    JSON.stringify(new URL("../ui/shared/utils/timestamp.js", import.meta.url).href),
  );
const { installProjectInstanceDatasetCache } = await import(
  `data:text/javascript;base64,${Buffer.from(testableSource).toString("base64")}`
);

function createHarness() {
  const signatureReads = [];
  const snapshotReads = [];
  const state = {
    selectedPath: "Direct Group/COLL",
    datasetViewMode: "normal",
    datasetRows: [],
    cachedDatasetFilter: {
      loading: false,
      loadedPath: "",
      names: new Set(),
      instanceRows: [],
      metadataByName: new Map(),
      methodTypesByName: new Map(),
      visibleCount: 0,
      error: "",
      warning: "",
      requestSeq: 0,
    },
    cachedDatasetSnapshotRequests: new Map(),
    datasetIndexWatch: {
      path: "",
      selectedPath: "",
      signature: "",
      pending: false,
      checking: false,
      error: "",
      suppressUntil: 0,
      timer: 0,
      visibilityWired: false,
    },
  };
  const api = {
    captureDatasetTableSelection: () => ({}),
    closeDatasetTableFilterPopover: () => {},
    fetchDatasetTypeRowsForRefresh: async () => null,
    getCachedDatasetKey: (value) => String(value || "").trim().toLowerCase(),
    getDatasetName: (row) => row?.name || "",
    normalizeLookupKey: (value) => String(value || "").trim().toLowerCase(),
    normalizePath: (value) => String(value || "").trim(),
    renderDatasetTable: () => {},
    restoreDatasetTableSelection: () => {},
    setStatus: () => {},
    toText: (value) => String(value ?? "").trim(),
  };
  const els = {
    datasetTableWrap: {
      scrollLeft: 120, scrollTop: 840,
      scrollWidth: 2000, scrollHeight: 3000,
      clientWidth: 500, clientHeight: 500,
    },
  };
  installProjectInstanceDatasetCache({
    api,
    els,
    projectName: "PI index watch test",
    state,
  });

  const previousFetch = globalThis.fetch;
  const previousWindow = globalThis.window;
  globalThis.window = {
    location: { origin: "http://127.0.0.1:28765" },
    requestAnimationFrame(callback) {
      callback();
      return 1;
    },
  };
  const harness = {
    api,
    els,
    nextPolledSignature: "",
    nextPolledAnswer: null,
    nextSnapshot: null,
    signatureReads,
    snapshotReads,
    state,
    async restore() {
      await api.stopDatasetIndexWatch();
      if (previousFetch === undefined) delete globalThis.fetch;
      else globalThis.fetch = previousFetch;
      if (previousWindow === undefined) delete globalThis.window;
      else globalThis.window = previousWindow;
    },
  };
  globalThis.fetch = async (url) => {
    if (/\/datasets\/cached\?/u.test(String(url)) && harness.nextSnapshot) {
      snapshotReads.push(String(url));
      return { ok: true, status: 200, json: async () => harness.nextSnapshot };
    }
    assert.match(String(url), /\/datasets\/cached\/index-signature\?/u);
    signatureReads.push(String(url));
    return {
      ok: true,
      status: 200,
      async json() {
        return harness.nextPolledAnswer || { ok: true, signature: harness.nextPolledSignature };
      },
    };
  };
  return harness;
}

test("overlapping save refreshes retain selection and both scroll offsets", async () => {
  const harness = createHarness();
  const { api, state, els } = harness;
  const originalSelection = { selectedNames: ["Paid Loss", "Reported Loss"], anchorName: "Paid Loss" };
  let selection = originalSelection;
  const reads = [];
  state.cachedDatasetFilter.loadedPath = state.selectedPath;
  state.datasetIndexWatch.selectedPath = state.selectedPath;
  api.captureDatasetTableSelection = () => selection;
  api.restoreDatasetTableSelection = (saved) => { selection = saved; };
  api.renderDatasetTable = () => {
    // The real loading render prunes highlighted rows and collapses the table.
    if (state.cachedDatasetFilter.loading) {
      selection = {};
      els.datasetTableWrap.scrollTop = 0;
      els.datasetTableWrap.scrollLeft = 0;
    }
  };
  globalThis.fetch = () => new Promise((resolve) => reads.push(resolve));
  const finishRead = (index) => reads[index]({
    ok: true,
    json: async () => ({ files: [{ name: "Paid Loss" }], index_signature: "2000:64" }),
  });
  try {
    const first = api.refreshCachedDatasetTableFromDisk();
    const second = api.refreshCachedDatasetTableFromDisk();
    assert.equal(reads.length, 1);
    finishRead(0);
    await Promise.all([first, second]);
    assert.deepEqual(selection, originalSelection);
    assert.equal(els.datasetTableWrap.scrollTop, 840);
    assert.equal(els.datasetTableWrap.scrollLeft, 120);

    // A different reserving class must not inherit the old table position.
    state.selectedPath = "Direct Group/OTHER";
    const nextPath = api.loadCachedDatasetFilterForSelectedPath();
    await Promise.resolve();
    finishRead(1);
    await nextPath;
    assert.deepEqual(selection, {});
    assert.equal(els.datasetTableWrap.scrollTop, 0);
  } finally {
    await harness.restore();
  }
});

test("the snapshot payload's signature baselines the watch without a client stat", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { index_signature: "2000.5:64" },
      harness.state.selectedPath,
    );

    assert.equal(harness.state.datasetIndexWatch.signature, "2000.5:64");
    assert.equal(harness.signatureReads.length, 0);
  } finally {
    await harness.restore();
  }
});

test("a payload without a signature falls back to the polling endpoint", async () => {
  const harness = createHarness();
  try {
    harness.nextPolledSignature = "1500:32";
    await harness.api.startDatasetIndexWatchForSnapshot({}, harness.state.selectedPath);

    assert.equal(harness.state.datasetIndexWatch.signature, "1500:32");
    assert.equal(harness.signatureReads.length, 1);
  } finally {
    await harness.restore();
  }
});

test("an observation older than the baseline is an SMB cache echo, not new work", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    harness.nextPolledSignature = "1000:48";
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.state.datasetIndexWatch.pending, false);
    // Not adopted either: lowering the baseline would make the next fresh
    // stat of the same old write read as an external update.
    assert.equal(harness.state.datasetIndexWatch.signature, "2000:64");
  } finally {
    await harness.restore();
  }
});

test("an observation newer than the baseline raises the refresh prompt", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    harness.nextPolledSignature = "3000:80";
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.state.datasetIndexWatch.pending, true);
  } finally {
    await harness.restore();
  }
});

test("a newer observation inside the settle window is adopted silently", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    harness.state.datasetIndexWatch.suppressUntil = Date.now() + 60000;
    harness.nextPolledSignature = "3000:80";
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.state.datasetIndexWatch.pending, false);
    assert.equal(harness.state.datasetIndexWatch.signature, "3000:80");
  } finally {
    await harness.restore();
  }
});

const PAID = { name: "Paid Loss", last_modified: "2026-10-01 09:00:00", origin_length: 12 };
const REPORTED = { name: "Reported Loss", last_modified: "2026-10-01 09:05:00", origin_length: 12 };

test("an index rewrite that leaves every row unchanged is adopted silently", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { files: [PAID, REPORTED], index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    // A new length-view cache file changes only the folder listing, so the
    // rebuilt index carries the same rows, possibly in another order.
    harness.nextPolledSignature = "3000:80";
    harness.nextSnapshot = { files: [REPORTED, PAID], index_signature: "3000.5:80" };
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.snapshotReads.length, 1);
    assert.equal(harness.state.datasetIndexWatch.pending, false);
    assert.equal(harness.state.datasetIndexWatch.signature, "3000.5:80");
  } finally {
    await harness.restore();
  }
});

test("an index rewrite that changes a row raises the refresh prompt", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { files: [PAID, REPORTED], index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    harness.nextPolledSignature = "3000:80";
    harness.nextSnapshot = {
      files: [PAID, { ...REPORTED, last_modified: "2026-10-02 10:00:00" }],
      index_signature: "3000.5:80",
    };
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.state.datasetIndexWatch.pending, true);
  } finally {
    await harness.restore();
  }
});

test("an unknown answer (the server could not be asked) never raises the prompt", async () => {
  const harness = createHarness();
  try {
    await harness.api.startDatasetIndexWatchForSnapshot(
      { index_signature: "2000:64" },
      harness.state.selectedPath,
    );
    harness.nextPolledAnswer = { ok: true, signature: "", unknown: true };
    await harness.api.checkDatasetIndexSignature();

    assert.equal(harness.state.datasetIndexWatch.pending, false);
    assert.equal(harness.state.datasetIndexWatch.signature, "2000:64");

    harness.nextPolledAnswer = null;
    harness.nextPolledSignature = "3000:80";
    await harness.api.checkDatasetIndexSignature();
    assert.equal(harness.state.datasetIndexWatch.pending, true, "the next known answer still decides");
  } finally {
    await harness.restore();
  }
});
