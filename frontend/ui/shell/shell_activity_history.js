import { localDayKey } from "/ui/shared/services/local_day.js?v=20260828a";

const LOCAL_PROJECT_PREFS_ENDPOINT = "/local-project/preferences";
const MAX_ACTIVITY_ENTRIES = 60;

function toText(value) {
  return String(value || "").trim();
}

function toNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

// Canonical comparison key for a Windows folder path. Shared by the activity-history dedupe key
// and by folder-keyed File Browser tab matching so both agree on when two folders are the same.
export function normalizeFolderKey(pathLike) {
  return toText(pathLike)
    .replace(/\//g, "\\")
    .replace(/\\+$/, "")
    .toLowerCase();
}

function normalizeRect(raw) {
  if (!raw || typeof raw !== "object") return null;
  const x = toNumber(raw.x, NaN);
  const y = toNumber(raw.y, NaN);
  const width = toNumber(raw.width, NaN);
  const height = toNumber(raw.height, NaN);
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  return {
    x: Math.round(x),
    y: Math.round(y),
    width: Math.round(width),
    height: Math.round(height),
  };
}

function normalizeNestedWindow(raw) {
  if (!raw || typeof raw !== "object") return null;
  const rawKind = toText(raw.kind).toLowerCase();
  const methodType = toText(raw.methodType || raw.method_type);
  const title = toText(raw.title) || toText(raw.name || raw.datasetName || raw.methodName);
  const isLegacyResultSelectionMethod = (
    rawKind === "dataset"
    && methodType.toLowerCase() === "result selection"
    && /(^|[\\/])result selection([\\/]|$)/i.test(title)
  );
  const kind = rawKind === "dfm"
    ? "dfm"
    : rawKind === "result_selection" || isLegacyResultSelectionMethod
      ? "result_selection"
      : "dataset";
  const name = toText(raw.name || raw.datasetName || raw.methodName);
  if (!name) return null;
  const hidden = !!raw.hidden;
  const active = !!raw.active;
  const maximized = !!raw.maximized;
  const dirty = !!raw.dirty;
  const dfmTab = toText(raw.dfmTab || raw.tab).toLowerCase();
  const rsTab = toText(raw.rsTab || raw.resultSelectionTab || raw.tab).toLowerCase();
  const out = { kind, name, title, hidden, active, maximized, dirty };
  if (methodType) out.methodType = methodType;
  if (dfmTab && kind === "dfm") out.dfmTab = dfmTab;
  if (rsTab && kind === "result_selection") out.rsTab = rsTab;
  const rect = normalizeRect(raw.rect);
  if (rect) out.rect = rect;
  return out;
}

export function normalizeProjectInstanceState(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const selectedPath = toText(source.selectedPath || source.path || source.reservingClass);
  const windowsRaw = Array.isArray(source.windows) ? source.windows : [];
  const windows = [];
  const seen = new Set();
  for (const item of windowsRaw) {
    const normalized = normalizeNestedWindow(item);
    if (!normalized) continue;
    const key = `${normalized.kind}\u0001${normalized.name.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    windows.push(normalized);
    if (windows.length >= 20) break;
  }
  const activeWindow = windows.find((item) => item.active) || null;
  const out = {};
  if (selectedPath) out.selectedPath = selectedPath;
  if (windows.length) out.windows = windows;
  if (activeWindow) out.activeWindow = { kind: activeWindow.kind, name: activeWindow.name };
  return Object.keys(out).length ? out : null;
}

export function normalizeShellActivityEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const tabType = toText(raw.tabType || raw.type).toLowerCase();
  const title = toText(raw.title) || tabType || "Untitled";
  const ts = Math.max(1, Math.floor(toNumber(raw.ts, Date.now())));
  const entry = { tabType, title, ts };

  if (tabType === "dataset") {
    const inputs = raw.datasetInputs && typeof raw.datasetInputs === "object" ? raw.datasetInputs : {};
    const project = toText(inputs.project || raw.project);
    const path = toText(inputs.path || raw.path);
    const tri = toText(inputs.tri || raw.tri || raw.datasetName);
    if (!project || !path || !tri) return null;
    entry.datasetInputs = { project, path, tri };
  } else if (tabType === "dfm") {
    const inputs = raw.dfmInputs && typeof raw.dfmInputs === "object" ? raw.dfmInputs : {};
    entry.dfmInputs = {
      project: toText(inputs.project || raw.project),
      reservingClass: toText(inputs.reservingClass || inputs.path || raw.path),
      methodName: toText(inputs.methodName || raw.methodName),
      outputType: toText(inputs.outputType || raw.outputType),
      outputDataset: toText(inputs.outputDataset || raw.outputDataset || raw.output_dataset),
      inputTriangle: toText(inputs.inputTriangle || raw.inputTriangle),
    };
    Object.keys(entry.dfmInputs).forEach((key) => {
      if (!entry.dfmInputs[key]) delete entry.dfmInputs[key];
    });
    entry.dfmTab = toText(raw.dfmTab || raw.tab).toLowerCase() || "details";
  } else if (tabType === "project_instance") {
    const projectName = toText(raw.projectName || raw.project || raw.title);
    if (!projectName) return null;
    entry.projectName = projectName;
    const projectFolder = toText(raw.projectFolder || raw.folder);
    const projectTablePath = toText(raw.projectTablePath || raw.tablePath);
    if (projectFolder) entry.projectFolder = projectFolder;
    if (projectTablePath) entry.projectTablePath = projectTablePath;
    const nested = normalizeProjectInstanceState(raw.projectInstanceState || raw.nested || raw);
    if (nested) entry.projectInstanceState = nested;
  } else if (tabType === "project_settings") {
    entry.projectSettingsRibbon = toText(raw.projectSettingsRibbon || raw.ribbon).toLowerCase() || "summary";
  } else if (tabType === "scripting") {
    const path = toText(raw.path || raw.scPath || raw.notebookPath);
    if (path) entry.path = path;
  } else if (tabType === "file_explorer") {
    const path = toText(raw.path || raw.fileExplorerPath);
    if (path) entry.path = path;
  } else if (tabType === "dashboard") {
    const path = toText(raw.path || raw.dashboardPath);
    if (path) entry.path = path;
  } else if (!["workflow", "agent_guide", "browsing_history", "server"].includes(tabType)) {
    return null;
  }

  return entry;
}

// One record per page per day: opening the same page again today replaces today's record, while
// the records it left on earlier days stay.
function getActivityKey(entry) {
  const identity = getActivityIdentity(entry);
  return identity ? `${identity}|${localDayKey(entry.ts)}` : "";
}

function getActivityIdentity(entry) {
  if (!entry) return "";
  if (entry.tabType === "dataset") {
    const d = entry.datasetInputs || {};
    return `dataset|${toText(d.project).toLowerCase()}|${toText(d.path).toLowerCase()}|${toText(d.tri).toLowerCase()}`;
  }
  if (entry.tabType === "dfm") {
    const d = entry.dfmInputs || {};
    return `dfm|${toText(d.project).toLowerCase()}|${toText(d.reservingClass).toLowerCase()}|${toText(d.methodName || d.outputType).toLowerCase()}`;
  }
  if (entry.tabType === "project_instance") {
    return `project_instance|${toText(entry.projectName).toLowerCase()}`;
  }
  if (entry.tabType === "scripting" && entry.path) return `scripting|${entry.path.toLowerCase()}`;
  if (entry.tabType === "file_explorer") return `file_explorer|${normalizeFolderKey(entry.path)}`;
  if (entry.tabType === "dashboard") return `dashboard|${toText(entry.path).toLowerCase()}`;
  return `${entry.tabType}|${entry.title.toLowerCase()}`;
}

export function normalizeShellActivityEntries(rawEntries) {
  const out = [];
  const seen = new Set();
  for (const item of Array.isArray(rawEntries) ? rawEntries : []) {
    const entry = normalizeShellActivityEntry(item);
    const key = getActivityKey(entry);
    if (!entry || !key || seen.has(key)) continue;
    seen.add(key);
    out.push(entry);
    if (out.length >= MAX_ACTIVITY_ENTRIES) break;
  }
  return out;
}

async function loadLocalProjectPreferences() {
  const response = await fetch(LOCAL_PROJECT_PREFS_ENDPOINT, { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
  const payload = await response.json().catch(() => ({}));
  return payload?.preferences && typeof payload.preferences === "object" ? payload.preferences : payload;
}

async function saveLocalProjectPreferences(prefs) {
  const response = await fetch(LOCAL_PROJECT_PREFS_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs || {}),
  });
  if (!response.ok) throw new Error(await response.text().catch(() => `HTTP ${response.status}`));
  const payload = await response.json().catch(() => ({}));
  return payload?.preferences && typeof payload.preferences === "object" ? payload.preferences : payload;
}

export async function loadShellActivityHistory() {
  const prefs = await loadLocalProjectPreferences();
  const history = prefs?.shellActivityHistory && typeof prefs.shellActivityHistory === "object"
    ? prefs.shellActivityHistory
    : {};
  return normalizeShellActivityEntries(history.entries);
}

export async function pushShellActivityHistoryEntry(rawEntry) {
  const entry = normalizeShellActivityEntry({ ...rawEntry, ts: Date.now() });
  if (!entry) return [];
  const existing = await loadShellActivityHistory().catch(() => []);
  const targetKey = getActivityKey(entry);
  const next = [entry];
  for (const item of existing) {
    if (getActivityKey(item) === targetKey) continue;
    next.push(item);
    if (next.length >= MAX_ACTIVITY_ENTRIES) break;
  }
  await saveLocalProjectPreferences({
    shellActivityHistory: {
      entries: next,
    },
  });
  return next;
}

export function buildRestoreSummary(entry) {
  if (!entry) return "";
  if (entry.tabType === "project_instance") {
    const nested = entry.projectInstanceState;
    const count = Array.isArray(nested?.windows) ? nested.windows.length : 0;
    const hidden = (nested?.windows || []).filter((item) => item.hidden).length;
    const path = toText(nested?.selectedPath);
    const pieces = [];
    if (path) pieces.push(path);
    if (count) pieces.push(`${count} nested window${count === 1 ? "" : "s"}`);
    if (hidden) pieces.push(`${hidden} hidden`);
    return pieces.join(" | ");
  }
  if (entry.tabType === "dataset") {
    const d = entry.datasetInputs || {};
    return [d.project, d.path, d.tri].map(toText).filter(Boolean).join(" | ");
  }
  if (entry.tabType === "dfm") {
    const d = entry.dfmInputs || {};
    return [d.project, d.reservingClass, d.methodName || d.outputType].map(toText).filter(Boolean).join(" | ");
  }
  if (entry.tabType === "scripting" || entry.tabType === "file_explorer" || entry.tabType === "dashboard") return toText(entry.path);
  return "";
}
