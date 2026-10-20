import { attachArcrhoTooltip } from "/ui/shared/components/tooltip/tooltip.js?v=20260925a";
import { publishProjectInstanceDatasetSnapshot } from "/ui/shared/dataset/project_instance_dataset_snapshot.js?v=20260725a";
import { arcrhoTimestampSeconds, formatArcrhoTimestamp } from "/ui/shared/utils/timestamp.js?v=20260818a";

export function installProjectInstanceDatasetCache(ctx) {
  const { api, els, projectName, state } = ctx;
  const { cachedDatasetFilter, cachedDatasetSnapshotRequests, datasetIndexWatch } = state;
  const captureDatasetTableSelection = (...args) => api.captureDatasetTableSelection(...args);
  const closeDatasetTableFilterPopover = (...args) => api.closeDatasetTableFilterPopover(...args);
  const fetchDatasetTypeRowsForRefresh = (...args) => api.fetchDatasetTypeRowsForRefresh(...args);
  const getCachedDatasetKey = (...args) => api.getCachedDatasetKey(...args);
  const getDatasetName = (...args) => api.getDatasetName(...args);
  const normalizeLookupKey = (...args) => api.normalizeLookupKey(...args);
  const normalizePath = (...args) => api.normalizePath(...args);
  const renderDatasetTable = (...args) => api.renderDatasetTable(...args);
  const restoreDatasetTableSelection = (...args) => api.restoreDatasetTableSelection(...args);
  const setStatus = (...args) => api.setStatus(...args);
  const toText = (...args) => api.toText(...args);

function isTemporaryDatasetView() {
  return state.datasetViewMode === "temporary";
}

function createTemporaryDatasetSessionId() {
  try {
    if (typeof crypto?.randomUUID === "function") return crypto.randomUUID();
  } catch {}
  const randomHex = (length) => {
    let out = "";
    while (out.length < length) out += Math.floor(Math.random() * 0x100000000).toString(16).padStart(8, "0");
    return out.slice(0, length);
  };
  return `${randomHex(8)}-${randomHex(4)}-4${randomHex(3)}-8${randomHex(3)}-${randomHex(12)}`;
}

function captureNormalDatasetTableFilters() {
  const filters = new Map();
  const source = state.datasetTableView?.filters;
  if (source instanceof Map) {
    for (const [key, values] of source.entries()) {
      filters.set(key, values instanceof Set ? new Set(values) : new Set());
    }
  }
  return {
    filters,
    explicitAllFilterKeys: new Set(state.datasetTableExplicitAllFilterKeys || []),
  };
}

function restoreNormalDatasetTableFilters() {
  const saved = state.temporaryDatasetTableFilterState;
  state.temporaryDatasetTableFilterState = null;
  if (!saved || !(state.datasetTableView?.filters instanceof Map)) return;
  state.datasetTableView.filters.clear();
  for (const [key, values] of saved.filters || []) {
    state.datasetTableView.filters.set(key, values instanceof Set ? new Set(values) : new Set());
  }
  state.datasetTableExplicitAllFilterKeys?.clear?.();
  for (const key of saved.explicitAllFilterKeys || []) {
    state.datasetTableExplicitAllFilterKeys?.add?.(key);
  }
}

function syncDatasetIndexUpdatePrompt() {
  const btn = els.datasetIndexUpdateBtn;
  if (!btn) return;
  const show = !!datasetIndexWatch.pending && !!state.selectedPath && !cachedDatasetFilter.loading;
  btn.hidden = !show;
  btn.disabled = cachedDatasetFilter.loading || !state.selectedPath;
}

function syncCachedDatasetToolbar() {
  const temporaryView = isTemporaryDatasetView();
  const indexWarning = toText(cachedDatasetFilter.warning);
  if (els.datasetTempViewBtn) {
    els.datasetTempViewBtn.disabled = cachedDatasetFilter.loading || !state.selectedPath;
    els.datasetTempViewBtn.classList.toggle("active", temporaryView);
    els.datasetTempViewBtn.setAttribute("aria-pressed", temporaryView ? "true" : "false");
    const label = temporaryView ? "Return to normal dataset view" : "Show temporary dataset view";
    els.datasetTempViewBtn.setAttribute("aria-label", label);
  }
  if (els.datasetTempViewTooltipTitle) {
    els.datasetTempViewTooltipTitle.textContent = temporaryView
      ? "Temporary view is enabled"
      : "Temporary view is disabled";
  }
  if (els.datasetTempViewTooltipDescription) {
    els.datasetTempViewTooltipDescription.textContent = temporaryView
      ? "Temporary view shows all datasets that can be generated. Click to return to Normal view."
      : "Normal view shows saved datasets only. Click to enable Temporary view.";
  }
  if (els.datasetRefreshBtn) {
    els.datasetRefreshBtn.disabled = cachedDatasetFilter.loading || !state.selectedPath;
  }
  syncDatasetIndexUpdatePrompt();
  if (!els.cachedDatasetStatus) return;
  if (indexWarning) {
    els.cachedDatasetStatus.setAttribute("aria-label", indexWarning);
  } else {
    els.cachedDatasetStatus.removeAttribute("aria-label");
  }
  if (!state.selectedPath) {
    els.cachedDatasetStatus.textContent = "";
    return;
  }
  if (cachedDatasetFilter.loading) {
    els.cachedDatasetStatus.textContent = temporaryView
      ? "Checking dataset index..."
      : "Checking cached datasets...";
    return;
  }
  if (cachedDatasetFilter.error) {
    els.cachedDatasetStatus.textContent = temporaryView
      ? "Dataset index check failed"
      : "Cached dataset check failed";
    return;
  }
  const count = Number.isFinite(cachedDatasetFilter.visibleCount)
    ? cachedDatasetFilter.visibleCount
    : cachedDatasetFilter.names.size;
  if (temporaryView) {
    els.cachedDatasetStatus.textContent = `Temporary view | ${count} ${count === 1 ? "dataset" : "datasets"}${indexWarning ? " | Warning: index not saved" : ""}`;
    return;
  }
  els.cachedDatasetStatus.textContent = `(${count} ${count === 1 ? "record" : "records"}${indexWarning ? " | Warning: index not saved" : ""})`;
}

function getSnapshotFolderPaths(payload) {
  const raw = payload?.folder_paths && typeof payload.folder_paths === "object"
    ? payload.folder_paths
    : payload?.folderPaths && typeof payload.folderPaths === "object"
      ? payload.folderPaths
      : {};
  return raw && typeof raw === "object" ? raw : {};
}

function getSnapshotDataFolder(payload) {
  const folderPaths = getSnapshotFolderPaths(payload);
  return toText(folderPaths.data || payload?.folder_path || payload?.folderPath);
}

const DATASET_INDEX_POLL_MS = 8000;
// Brief hold after a reload so a poll racing the load's re-baseline cannot
// flag the reload's own index write. Self-write protection does not rest on
// this window: the snapshot payload carries the authoritative signature and
// the poll ignores observations older than the baseline (see
// checkDatasetIndexSignature), so this only needs to cover the fallback
// baseline fetch when an older server omits `index_signature`.
const DATASET_INDEX_SETTLE_SUPPRESS_MS = 1500;

/** Leading mtime (in ms) of an "mtime_ms:size" signature, NaN when unparseable. */
function parseDatasetIndexSignatureMtime(signature) {
  const text = toText(signature);
  const sep = text.indexOf(":");
  if (sep <= 0) return NaN;
  return Number(text.slice(0, sep));
}

async function fetchDatasetIndexSignature(selectedPath) {
  const url = new URL("/datasets/cached/index-signature", window.location.origin);
  url.searchParams.set("project_name", projectName);
  url.searchParams.set("reserving_class", selectedPath);
  const resp = await fetch(url.toString(), { cache: "no-store" });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok || payload?.ok === false) {
    throw new Error(payload?.detail || `Index signature lookup failed (${resp.status})`);
  }
  // The server could not be asked: skip this poll quietly and ask again.
  if (payload?.unknown) throw new Error("Index signature unknown.");
  return toText(payload?.signature);
}

/**
 * What the table shows from a snapshot, independent of row order. index.json
 * also records the folder listing, so a new cache file (a length view the
 * Engine wrote) rewrites it without changing any row; comparing rows keeps
 * that rewrite from raising the refresh prompt. "" when there is nothing to
 * compare.
 */
function datasetIndexRowsFingerprint(payload) {
  const files = payload?.files;
  if (!Array.isArray(files)) return "";
  return JSON.stringify(files.map((item) => JSON.stringify(item ?? null)).sort());
}

/** Reads index.json's signature once and treats it as the loaded baseline. */
async function baselineDatasetIndexSignature(selectedPath) {
  try {
    const signature = await fetchDatasetIndexSignature(selectedPath);
    if (normalizePath(datasetIndexWatch.selectedPath).toLowerCase() !== selectedPath.toLowerCase()) return;
    datasetIndexWatch.signature = signature;
    datasetIndexWatch.error = "";
  } catch (err) {
    datasetIndexWatch.error = toText(err?.message) || "Could not read the dataset index signature.";
  }
}

/**
 * Re-reads the index after its signature moved and adopts the new signature
 * when the rows match the loaded table. False when the rows differ or cannot
 * be compared, so the caller still offers the refresh.
 */
async function datasetIndexRowsUnchanged(selectedPath, polledSignature) {
  const baseline = datasetIndexWatch.rowsFingerprint;
  if (!baseline) return false;
  let payload;
  try {
    payload = await fetchCachedDatasetSnapshot(selectedPath);
  } catch {
    return false;
  }
  if (normalizePath(datasetIndexWatch.selectedPath).toLowerCase() !== selectedPath.toLowerCase()) return true;
  if (datasetIndexRowsFingerprint(payload) !== baseline) return false;
  datasetIndexWatch.signature = toText(payload?.index_signature) || polledSignature;
  return true;
}

async function checkDatasetIndexSignature() {
  const selectedPath = normalizePath(datasetIndexWatch.selectedPath);
  if (!selectedPath || datasetIndexWatch.checking) return;
  // A poll that lands mid-load would compare against a baseline the load is
  // about to replace, so let the load re-baseline instead.
  if (cachedDatasetFilter.loading || datasetIndexWatch.pending) return;
  datasetIndexWatch.checking = true;
  try {
    const signature = await fetchDatasetIndexSignature(selectedPath);
    if (normalizePath(datasetIndexWatch.selectedPath).toLowerCase() !== selectedPath.toLowerCase()) return;
    datasetIndexWatch.error = "";
    if (!datasetIndexWatch.signature) {
      datasetIndexWatch.signature = signature;
      return;
    }
    if (signature === datasetIndexWatch.signature) return;
    // The server stats index.json on its own disk, but a stat over a mapped
    // drive could be answered from the SMB redirector's cache and report
    // metadata from before the baseline write, so the rule stays. Staleness only ever
    // reports an older state than the truth (business logic contract rule 15),
    // so an observation older than the baseline is that cache echoing the
    // past — never new work. Ignore it without adopting it, or the next fresh
    // stat would read as an external update.
    const baselineMtime = parseDatasetIndexSignatureMtime(datasetIndexWatch.signature);
    const observedMtime = parseDatasetIndexSignatureMtime(signature);
    if (Number.isFinite(baselineMtime) && Number.isFinite(observedMtime) && observedMtime < baselineMtime) {
      return;
    }
    // Writes this window just made are not news to it, so adopt them silently.
    if (Date.now() < Number(datasetIndexWatch.suppressUntil || 0)) {
      datasetIndexWatch.signature = signature;
      return;
    }
    if (await datasetIndexRowsUnchanged(selectedPath, signature)) return;
    if (normalizePath(datasetIndexWatch.selectedPath).toLowerCase() !== selectedPath.toLowerCase()) return;
    if (cachedDatasetFilter.loading) return;
    datasetIndexWatch.pending = true;
    syncDatasetIndexUpdatePrompt();
  } catch (err) {
    datasetIndexWatch.error = toText(err?.message) || "Could not read the dataset index signature.";
  } finally {
    datasetIndexWatch.checking = false;
  }
}

function stopDatasetIndexPollTimer() {
  if (datasetIndexWatch.timer) {
    clearInterval(datasetIndexWatch.timer);
    datasetIndexWatch.timer = 0;
  }
}

function startDatasetIndexPollTimer() {
  stopDatasetIndexPollTimer();
  if (!datasetIndexWatch.selectedPath) return;
  // A hidden window cannot show the prompt anyway, so polling it only spends
  // round trips; the visibility handler re-checks the moment it comes back.
  if (typeof document !== "undefined" && document.hidden) return;
  datasetIndexWatch.timer = setInterval(() => {
    void checkDatasetIndexSignature();
  }, DATASET_INDEX_POLL_MS);
  // Node's timer object keeps its event loop alive; the browser's numeric
  // handle has no unref, so this only matters when a test loads this module.
  datasetIndexWatch.timer?.unref?.();
}

function ensureDatasetIndexVisibilityListener() {
  if (datasetIndexWatch.visibilityWired || typeof document === "undefined") return;
  datasetIndexWatch.visibilityWired = true;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopDatasetIndexPollTimer();
      return;
    }
    startDatasetIndexPollTimer();
    void checkDatasetIndexSignature();
  });
}

async function stopDatasetIndexWatch(options = {}) {
  stopDatasetIndexPollTimer();
  datasetIndexWatch.selectedPath = "";
  datasetIndexWatch.path = "";
  datasetIndexWatch.signature = "";
  datasetIndexWatch.rowsFingerprint = "";
  datasetIndexWatch.checking = false;
  datasetIndexWatch.error = "";
  datasetIndexWatch.suppressUntil = 0;
  if (options?.clearPending !== false) datasetIndexWatch.pending = false;
  syncDatasetIndexUpdatePrompt();
}

async function startDatasetIndexWatchForSnapshot(payload, selectedPath) {
  const folderPath = getSnapshotDataFolder(payload);
  const normalizedSelectedPath = normalizePath(selectedPath);
  if (!normalizedSelectedPath) {
    await stopDatasetIndexWatch();
    return;
  }
  const samePath = normalizePath(datasetIndexWatch.selectedPath).toLowerCase()
    === normalizedSelectedPath.toLowerCase();
  datasetIndexWatch.selectedPath = normalizedSelectedPath;
  datasetIndexWatch.path = folderPath;
  datasetIndexWatch.pending = false;
  // The snapshot just loaded is the new baseline whether or not the path
  // changed, so a refresh always clears what the poll had flagged.
  datasetIndexWatch.signature = "";
  datasetIndexWatch.rowsFingerprint = datasetIndexRowsFingerprint(payload);
  ensureDatasetIndexVisibilityListener();
  startDatasetIndexPollTimer();
  syncDatasetIndexUpdatePrompt();
  const payloadSignature = toText(payload?.index_signature);
  if (payloadSignature) {
    // Statted by the process that wrote or validated index.json — the Gateway
    // for hosted reads — so it cannot be an SMB attribute-cache echo of the
    // pre-write file the way a client-side stat taken right after a hosted
    // save can be. Baselining on it means this window's own writes can never
    // out-run the baseline and raise the refresh prompt.
    datasetIndexWatch.signature = payloadSignature;
    datasetIndexWatch.error = "";
  } else {
    // Older server without index_signature in the snapshot payload: fall back
    // to a client-side stat, guarded by the settle suppression window.
    await baselineDatasetIndexSignature(normalizedSelectedPath);
  }
  if (!samePath) syncDatasetIndexUpdatePrompt();
}


function shouldUseCachedDatasetFilter() {
  return (
    !cachedDatasetFilter.loading
    && !cachedDatasetFilter.error
    && state.selectedPath
    && normalizePath(cachedDatasetFilter.loadedPath).toLowerCase() === normalizePath(state.selectedPath).toLowerCase()
  );
}

function hasCachedDatasetMetadataForSelectedPath() {
  return (
    state.selectedPath
    && normalizePath(cachedDatasetFilter.loadedPath).toLowerCase() === normalizePath(state.selectedPath).toLowerCase()
    && cachedDatasetFilter.metadataByName instanceof Map
  );
}

function hasCachedDatasetSnapshotForSelectedPath() {
  return (
    hasCachedDatasetMetadataForSelectedPath()
    && !cachedDatasetFilter.loading
    && !cachedDatasetFilter.error
  );
}

function isDatasetRecordCached(record) {
  if (!hasCachedDatasetSnapshotForSelectedPath()) return false;
  const key = getCachedDatasetKey(record?.datasetName || getDatasetName(record?.row));
  return !!key && cachedDatasetFilter.names.has(key);
}


function getCachedFileDatasetNames(item) {
  const names = [];
  const add = (value) => {
    const text = toText(value);
    if (text) names.push(text);
  };
  add(item?.name);

  const seen = new Set();
  return names.filter((name) => {
    const key = getCachedDatasetKey(name);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// The timestamp rule this table established now lives in a shared module, so
// the Excel Link Manager's Created and Last Modified read identically to these.
const getTimestampNumber = arcrhoTimestampSeconds;
const formatCachedTimestamp = formatArcrhoTimestamp;

function mergeCachedDatasetMetadata(existing, item) {
  const meta = existing || {
    lastModified: "",
    created: "",
    user: "",
    formula: "",
    status: 0,
    _lastModifiedTs: 0,
    _createdTs: 0,
    _userModifiedTs: 0,
    _formulaModifiedTs: 0,
  };

  const lastModifiedRaw = item?.last_modified || item?.last_modified_timestamp || item?.mtime;
  const lastModified = formatCachedTimestamp(lastModifiedRaw);
  const lastModifiedTs = getTimestampNumber(lastModifiedRaw) || getTimestampNumber(item?.last_modified_timestamp) || getTimestampNumber(item?.mtime);
  if (lastModified && (!meta.lastModified || lastModifiedTs >= meta._lastModifiedTs)) {
    meta.lastModified = lastModified;
    meta._lastModifiedTs = lastModifiedTs;
  }

  const createdRaw = item?.created || item?.created_timestamp;
  const created = formatCachedTimestamp(createdRaw);
  const createdTs = getTimestampNumber(createdRaw) || getTimestampNumber(item?.created_timestamp);
  if (created && (!meta.created || !meta._createdTs || (createdTs && createdTs < meta._createdTs))) {
    meta.created = created;
    meta._createdTs = createdTs;
  }

  const user = toText(item?.user);
  if (user && (!meta.user || lastModifiedTs >= meta._userModifiedTs)) {
    meta.user = user;
    meta._userModifiedTs = lastModifiedTs;
  }

  const formula = toText(item?.formula);
  if (formula && (!meta.formula || lastModifiedTs >= meta._formulaModifiedTs)) {
    meta.formula = formula;
    meta._formulaModifiedTs = lastModifiedTs;
  }

  const originLength = Number(item?.origin_length);
  if (Number.isFinite(originLength) && originLength > 0 && (!meta.originLength || lastModifiedTs >= (meta._originLengthModifiedTs || 0))) {
    meta.originLength = Math.trunc(originLength);
    meta._originLengthModifiedTs = lastModifiedTs;
  }
  const developmentLength = Number(item?.development_length);
  if (
    Number.isFinite(developmentLength)
    && developmentLength > 0
    && (!meta.developmentLength || lastModifiedTs >= (meta._developmentLengthModifiedTs || 0))
  ) {
    meta.developmentLength = Math.trunc(developmentLength);
    meta._developmentLengthModifiedTs = lastModifiedTs;
  }
  const status = Number(item?.status);
  if (Number.isFinite(status) && (status === 0 || status === 2) && (!meta._statusModifiedTs || lastModifiedTs >= meta._statusModifiedTs)) {
    meta.status = status;
    meta._statusModifiedTs = lastModifiedTs;
  }
  return meta;
}

function normalizeCachedDatasetSnapshot(payload) {
  const files = Array.isArray(payload?.files) ? payload.files : [];
  const metadataByName = new Map();
  const methodTypesByName = new Map();
  const datasetKeys = new Set();
  const addDatasetKey = (name) => {
    const key = getCachedDatasetKey(name);
    if (key) datasetKeys.add(key);
  };
  const addMethodType = (name, methodType) => {
    const key = normalizeLookupKey(name);
    const type = toText(methodType);
    if (key && type) methodTypesByName.set(key, type);
  };
  for (const item of files) {
    const itemNames = getCachedFileDatasetNames(item);
    for (const name of itemNames) {
      addDatasetKey(name);
      const key = getCachedDatasetKey(name);
      if (!key) continue;
      metadataByName.set(key, mergeCachedDatasetMetadata(metadataByName.get(key), item));
    }
    if (item?.method_type) {
      for (const name of itemNames) addMethodType(name, item.method_type);
    }
  }
  return {
    names: datasetKeys,
    instanceRows: files,
    metadataByName,
    methodTypesByName,
  };
}

async function fetchCachedDatasetSnapshot(path, options = {}) {
  const normalizedPath = normalizePath(path);
  // A reload the user asked for gets its own request key so it never joins a
  // background read that started before their change landed. It does not ask the
  // server to force a rebuild: /datasets/cached compares the reserving-class
  // folder signature and rebuilds only when the folder actually changed, which
  // keeps an unchanged reload to three directory listings on a network drive.
  const userInitiated = !!options?.userInitiated;
  const requestKey = `${normalizeLookupKey(projectName)}\u0001${normalizedPath.toLowerCase()}\u0001${userInitiated ? "user" : "background"}`;
  const existing = cachedDatasetSnapshotRequests.get(requestKey);
  if (existing) return existing;

  const request = (async () => {
    const url = new URL("/datasets/cached", window.location.origin);
    url.searchParams.set("project_name", projectName);
    url.searchParams.set("reserving_class", normalizedPath);
    const resp = await fetch(url.toString(), { cache: "no-store" });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok || payload?.ok === false) {
      throw new Error(payload?.detail || `Cached dataset lookup failed (${resp.status})`);
    }
    return payload;
  })();

  cachedDatasetSnapshotRequests.set(requestKey, request);
  try {
    return await request;
  } finally {
    if (cachedDatasetSnapshotRequests.get(requestKey) === request) {
      cachedDatasetSnapshotRequests.delete(requestKey);
    }
  }
}

function applyCachedDatasetSnapshot(payload, path = state.selectedPath) {
  const normalizedPath = normalizePath(path);
  const snapshot = normalizeCachedDatasetSnapshot(payload);
  publishProjectInstanceDatasetSnapshot(projectName, normalizedPath, payload);
  cachedDatasetFilter.names = snapshot.names;
  cachedDatasetFilter.instanceRows = snapshot.instanceRows;
  cachedDatasetFilter.metadataByName = snapshot.metadataByName;
  cachedDatasetFilter.methodTypesByName = snapshot.methodTypesByName;
  cachedDatasetFilter.loadedPath = normalizedPath;
  cachedDatasetFilter.error = "";
  cachedDatasetFilter.rebuildReason = toText(payload?.index_rebuild_reason);
  cachedDatasetFilter.elapsedMs = Number(payload?.index_elapsed_ms) || 0;
  cachedDatasetFilter.warning = payload?.index_persisted === false
    ? toText(payload?.index_warning) || "Dataset table loaded, but index.json could not be updated."
    : "";
  void startDatasetIndexWatchForSnapshot(payload, normalizedPath);
  // The Status column also reports a linked workbook that now holds different
  // numbers, which is a question about files the index knows nothing about.
  api.startExcelLinkStatusWatch?.(normalizedPath);
  // The disk-backed inventory moved on, so any open graph of this class redraws.
  api.notifyDependencyGraphWindows?.(normalizedPath);
}

let pendingDatasetTableState = null;

async function loadCachedDatasetFilterForSelectedPath(options = {}) {
  const path = normalizePath(state.selectedPath);
  const samePath = path && path.toLowerCase() === normalizePath(cachedDatasetFilter.loadedPath).toLowerCase();
  // Overlapping save notifications must share the state from before the
  // loading table cleared the selection and collapsed the scroll area.
  pendingDatasetTableState = samePath
    ? pendingDatasetTableState || {
      selection: captureDatasetTableSelection(),
      scroll: captureDatasetTableScroll(),
    }
    : null;
  const seq = cachedDatasetFilter.requestSeq + 1;
  cachedDatasetFilter.requestSeq = seq;
  cachedDatasetFilter.error = "";
  cachedDatasetFilter.warning = "";
  cachedDatasetFilter.rebuildReason = "";
  cachedDatasetFilter.elapsedMs = 0;
  cachedDatasetFilter.names = new Set();
  cachedDatasetFilter.instanceRows = [];
  cachedDatasetFilter.metadataByName = new Map();
  cachedDatasetFilter.methodTypesByName = new Map();
  cachedDatasetFilter.loadedPath = path;
  if (!path || normalizePath(datasetIndexWatch.selectedPath).toLowerCase() !== path.toLowerCase()) {
    await stopDatasetIndexWatch();
  }

  if (!projectName || !path) {
    api.stopExcelLinkStatusWatch?.();
    cachedDatasetFilter.loading = false;
    syncCachedDatasetToolbar();
    renderDatasetTable();
    return;
  }

  cachedDatasetFilter.loading = true;
  syncCachedDatasetToolbar();
  renderDatasetTable();

  try {
    // The index reports each instance's dataset type; Dataset Types owns that
    // type's Data Format, Category, and Formula. Refresh both together so a type
    // added or edited in Project Settings after this page opened cannot leave a
    // saved instance rendering with a blank category. The two reads run
    // concurrently, and the rows land under the same request guard as the
    // snapshot so a superseded refresh cannot overwrite newer dataset types.
    const [payload, datasetTypeRows] = await Promise.all([
      fetchCachedDatasetSnapshot(path, { userInitiated: !!options?.userInitiated }),
      fetchDatasetTypeRowsForRefresh(),
    ]);
    if (seq !== cachedDatasetFilter.requestSeq) return;
    if (Array.isArray(datasetTypeRows)) state.datasetRows = datasetTypeRows;
    applyCachedDatasetSnapshot(payload, path);
  } catch (err) {
    if (seq !== cachedDatasetFilter.requestSeq) return;
    cachedDatasetFilter.names = new Set();
    cachedDatasetFilter.instanceRows = [];
    cachedDatasetFilter.metadataByName = new Map();
    cachedDatasetFilter.methodTypesByName = new Map();
    cachedDatasetFilter.error = toText(err?.message) || "Cached dataset lookup failed.";
    cachedDatasetFilter.warning = "";
    setStatus(cachedDatasetFilter.error, true);
  } finally {
    if (seq !== cachedDatasetFilter.requestSeq) return;
    cachedDatasetFilter.loading = false;
    syncCachedDatasetToolbar();
    renderDatasetTable();
    const tableState = pendingDatasetTableState;
    pendingDatasetTableState = null;
    if (tableState && path.toLowerCase() === normalizePath(state.selectedPath).toLowerCase()) {
      restoreDatasetTableSelection(tableState.selection);
      restoreDatasetTableScroll(tableState.scroll);
    }
  }
}

function describeIndexReadCost() {
  const reason = toText(cachedDatasetFilter.rebuildReason);
  if (!reason) return "";
  const seconds = Number(cachedDatasetFilter.elapsedMs) / 1000;
  const elapsed = Number.isFinite(seconds) && seconds > 0 ? `, ${seconds.toFixed(1)}s` : "";
  return `index rebuilt: ${reason}${elapsed}`;
}

async function refreshCachedDatasetTableFromDisk() {
  if (!state.selectedPath) {
    setStatus("Select a reserving-class path before refreshing the dataset table.", true);
    return false;
  }
  closeDatasetTableFilterPopover();
  datasetIndexWatch.suppressUntil = Date.now() + DATASET_INDEX_SETTLE_SUPPRESS_MS;
  setStatus(isTemporaryDatasetView()
    ? "Refreshing dataset index status..."
    : "Refreshing dataset table...");
  await loadCachedDatasetFilterForSelectedPath({ userInitiated: true });
  if (!cachedDatasetFilter.error) {
    datasetIndexWatch.pending = false;
    syncDatasetIndexUpdatePrompt();
    if (cachedDatasetFilter.warning) {
      setStatus(cachedDatasetFilter.warning, true);
      return true;
    }
    // A rebuild is the slow path, so name it rather than leaving a long wait
    // looking like an unexplained stall.
    const cost = describeIndexReadCost();
    setStatus(`${isTemporaryDatasetView()
      ? "Dataset index status refreshed."
      : "Dataset table refreshed."}${cost ? ` (${cost})` : ""}`);
    return true;
  }
  return false;
}

async function enterTemporaryDatasetView() {
  if (!state.selectedPath) {
    setStatus("Select a reserving class path before opening temporary view.", true);
    return false;
  }
  state.temporaryDatasetTableFilterState = captureNormalDatasetTableFilters();
  state.datasetTableView?.filters?.clear?.();
  state.datasetTableExplicitAllFilterKeys?.clear?.();
  state.datasetViewMode = "temporary";
  state.temporaryDatasetSessionId = createTemporaryDatasetSessionId();
  state.datasetTableSelection?.selectedKeys?.clear?.();
  if (state.datasetTableSelection) state.datasetTableSelection.anchorKey = "";
  syncCachedDatasetToolbar();
  renderDatasetTable();
  if (!shouldUseCachedDatasetFilter()) await loadCachedDatasetFilterForSelectedPath();
  setStatus("Temporary view is active. Opened datasets are read-only; generated CSV caches are retained without sidecars or index entries.");
  return true;
}

async function leaveTemporaryDatasetView() {
  if (!isTemporaryDatasetView()) return true;
  const sessionId = toText(state.temporaryDatasetSessionId);
  const closeTemporaryDatasetWindows = api.closeTemporaryDatasetWindows;
  if (typeof closeTemporaryDatasetWindows === "function") {
    const closed = closeTemporaryDatasetWindows(sessionId);
    if (closed === false) {
      setStatus("Close the temporary dataset window before leaving temporary view.", true);
      return false;
    }
  }
  state.datasetViewMode = "normal";
  state.temporaryDatasetSessionId = "";
  restoreNormalDatasetTableFilters();
  state.datasetTableSelection?.selectedKeys?.clear?.();
  if (state.datasetTableSelection) state.datasetTableSelection.anchorKey = "";
  syncCachedDatasetToolbar();
  renderDatasetTable();
  setStatus("Returned to normal dataset view.");
  return true;
}

async function toggleDatasetViewMode() {
  return isTemporaryDatasetView()
    ? leaveTemporaryDatasetView()
    : enterTemporaryDatasetView();
}

function captureDatasetTableScroll() {
  return {
    left: Number(els.datasetTableWrap?.scrollLeft) || 0,
    top: Number(els.datasetTableWrap?.scrollTop) || 0,
  };
}

function restoreDatasetTableScroll(scrollState) {
  const wrap = els.datasetTableWrap;
  if (!wrap || !scrollState) return;
  const apply = () => {
    const maxLeft = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    const maxTop = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    wrap.scrollLeft = Math.max(0, Math.min(Number(scrollState.left) || 0, maxLeft));
    wrap.scrollTop = Math.max(0, Math.min(Number(scrollState.top) || 0, maxTop));
  };
  apply();
  window.requestAnimationFrame(apply);
}

function initCachedDatasetToolbar() {
  if (els.datasetRefreshBtn && els.datasetRefreshBtn.dataset.wired !== "1") {
    els.datasetRefreshBtn.dataset.wired = "1";
    attachArcrhoTooltip(els.datasetRefreshBtn, "Refresh Dataset Table");
    els.datasetRefreshBtn.addEventListener("click", () => {
      void refreshCachedDatasetTableFromDisk();
    });
  }
  if (els.datasetTempViewBtn && els.datasetTempViewBtn.dataset.wired !== "1") {
    els.datasetTempViewBtn.dataset.wired = "1";
    els.datasetTempViewBtn.addEventListener("click", () => {
      void toggleDatasetViewMode();
    });
  }
  if (els.datasetIndexUpdateBtn && els.datasetIndexUpdateBtn.dataset.wired !== "1") {
    els.datasetIndexUpdateBtn.dataset.wired = "1";
    els.datasetIndexUpdateBtn.addEventListener("click", () => {
      void refreshCachedDatasetTableFromDisk();
    });
  }
  if (typeof window !== "undefined") {
    window.addEventListener("pagehide", () => {
      void stopDatasetIndexWatch();
    }, { once: true });
  }
  syncCachedDatasetToolbar();
}

  Object.assign(api, {
    applyCachedDatasetSnapshot,
    captureDatasetTableScroll,
    checkDatasetIndexSignature,
    fetchCachedDatasetSnapshot,
    formatCachedTimestamp,
    getCachedFileDatasetNames,
    getTimestampNumber,
    hasCachedDatasetMetadataForSelectedPath,
    hasCachedDatasetSnapshotForSelectedPath,
    initCachedDatasetToolbar,
    isDatasetRecordCached,
    loadCachedDatasetFilterForSelectedPath,
    mergeCachedDatasetMetadata,
    normalizeCachedDatasetSnapshot,
    refreshCachedDatasetTableFromDisk,
    restoreDatasetTableScroll,
    startDatasetIndexWatchForSnapshot,
    shouldUseCachedDatasetFilter,
    stopDatasetIndexWatch,
    syncCachedDatasetToolbar,
    toggleDatasetViewMode,
    isTemporaryDatasetView,
  });
}
