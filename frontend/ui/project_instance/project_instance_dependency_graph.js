// Project Instance host for the Dependency Graph nested window.
//
// The diagram itself lives in dependency_graph_window.html and runs inside a
// normal pi-window, so it drags, resizes, minimizes to the dock, maximizes,
// and closes exactly like a Dataset or DFM window. This module only opens that
// window - from the dataset toolbar, or for a dataset window that asks, with
// that dataset brought into view - and tells every open graph window when the
// page has reloaded its dataset table from disk, so the diagram follows a
// save, a delete, or an import.
//
// The window is pinned to the reserving class it was opened on, like every
// other nested window: selecting another class in the tree leaves it alone and
// opens a second window for that class instead.
import { attachArcrhoTooltip } from "/ui/shared/components/tooltip/tooltip.js?v=20260925a";
import {
  DEPENDENCY_GRAPH_ACTION_MESSAGE,
  DEPENDENCY_GRAPH_ACTION_RESULT_MESSAGE,
  DEPENDENCY_GRAPH_FOCUS_MESSAGE,
  DEPENDENCY_GRAPH_OPEN_MESSAGE,
} from "./dependency_graph_contract.js?v=20261020a";

export const DEPENDENCY_GRAPH_WINDOW_KIND = "dependency_graph";
export const DEPENDENCY_GRAPH_REFRESH_MESSAGE = "arcrho:dependency-graph-refresh";

export function installProjectInstanceDependencyGraph(ctx) {
  const { api, els, state, projectName } = ctx;
  const normalizePath = (...args) => api.normalizePath(...args);
  const setStatus = (...args) => api.setStatus(...args);

  function getDependencyGraphWindowKey(path) {
    // Same shape as the dataset and method window keys: a kind tag, the unit
    // separator, then the normalized reserving-class path.
    return `${DEPENDENCY_GRAPH_WINDOW_KIND}${normalizePath(path)}`;
  }

  function buildDependencyGraphWindowUrl(inst, path, focus = "") {
    const params = new URLSearchParams();
    params.set("project", projectName);
    params.set("class", path);
    params.set("inst", inst);
    if (focus) params.set("focus", focus);
    params.set("project_instance", "1");
    params.set("v", String(Date.now()));
    return `/ui/project_instance/dependency_graph_window.html?${params.toString()}`;
  }

  function isDependencyGraphWindow(frame) {
    return frame?.dataset?.windowKind === DEPENDENCY_GRAPH_WINDOW_KIND;
  }

  /**
   * Opens the graph for one class - the selected one unless a caller names
   * another - and, when `focus` names a dataset, brings its box into view.
   */
  function openDependencyGraph({ path: requestedPath = "", focus = "" } = {}) {
    const path = normalizePath(requestedPath || state.selectedPath);
    if (!path) {
      setStatus("Select a reserving class path before opening the dependency graph.", true);
      return null;
    }
    const focusName = String(focus || "").trim();
    const inst = `pi_dependency_graph_${Date.now()}_${state.windowSeq++}`;
    // An already-open window for this class is re-activated rather than duplicated.
    const frame = api.createFloatingContentWindow({
      kind: DEPENDENCY_GRAPH_WINDOW_KIND,
      name: "Dependency Graph",
      itemName: "Dependency Graph",
      title: `${path}\\Dependency Graph`,
      windowKey: getDependencyGraphWindowKey(path),
      inst,
      iframeSrc: buildDependencyGraphWindowUrl(inst, path, focusName),
      path,
    });
    // A new window reads the focus from its URL; a re-activated one is told.
    if (frame && focusName && frame.dataset.windowId !== inst) {
      try {
        frame.querySelector("iframe")?.contentWindow?.postMessage({ type: DEPENDENCY_GRAPH_FOCUS_MESSAGE, datasetName: focusName }, "*");
      } catch {}
    }
    return frame;
  }

  /** Tells every graph window of one reserving class to reload its diagram. */
  function notifyDependencyGraphWindows(path) {
    const target = normalizePath(path);
    const frames = els.windowLayer?.querySelectorAll(`.pi-window[data-window-kind="${DEPENDENCY_GRAPH_WINDOW_KIND}"]`) || [];
    for (const frame of frames) {
      if (normalizePath(frame.dataset.windowPath) !== target) continue;
      try {
        frame.querySelector("iframe")?.contentWindow?.postMessage({ type: DEPENDENCY_GRAPH_REFRESH_MESSAGE }, "*");
      } catch {}
    }
  }

  function initDependencyGraph() {
    if (!els.dependencyGraphBtn || els.dependencyGraphBtn.dataset.wired === "1") return;
    els.dependencyGraphBtn.dataset.wired = "1";
    attachArcrhoTooltip(els.dependencyGraphBtn, "Dependency Graph");
    els.dependencyGraphBtn.addEventListener("click", () => void openDependencyGraph({}));
  }

  async function handleDependencyGraphAction(event) {
    const message = event.data;
    if (message?.type !== DEPENDENCY_GRAPH_ACTION_MESSAGE) return;
    const frame = api.findWindowByMessageSource(event.source);
    if (!isDependencyGraphWindow(frame)) return;
    const path = normalizePath(api.getWindowPath(frame));
    const name = String(message.datasetName || "").trim();
    if (!path || !name) return;
    let result;
    try {
      if (message.action === "set-reviewed") {
        if (normalizePath(state.selectedPath) === path && api.isReservingClassBusy?.()) {
          throw new Error("Dependent updates are running for this reserving class. Try again when they finish.");
        }
        result = await api.setDatasetRowsReviewStatus([
          { datasetName: name, values: { methodType: message.methodType } },
        ], false, { reservingClass: path });
      } else if (message.action === "view-in-table") {
        if (api.isTemporaryDatasetView() && !await api.toggleDatasetViewMode()) {
          throw new Error("Could not leave temporary dataset view.");
        }
        if (normalizePath(state.selectedPath) !== path) await api.setSelectedPath(path);
        else if (!api.hasCachedDatasetSnapshotForSelectedPath()) await api.loadCachedDatasetFilterForSelectedPath();
        if (normalizePath(state.selectedPath) !== path) throw new Error("The selected class changed. Try View in Dataset Table again.");
        if (state.cachedDatasetFilter.error) throw new Error(state.cachedDatasetFilter.error);
        if (!api.selectDatasetRecordByName(name, { reveal: true })) throw new Error(`${name} is no longer in the dataset table.`);
        await api.hideDatasetWindow(frame);
        api.focusProjectInstancePage();
        api.focusDatasetTableSurface();
        await api.revealPathTreeSelection(path);
        result = { ok: true, message: `Selected ${name} in the dataset table.` };
        setStatus(result.message);
      } else return;
    } catch (error) {
      result = { ok: false, message: error.message || "The graph action failed." };
      setStatus(result.message, true);
    }
    event.source.postMessage({ type: DEPENDENCY_GRAPH_ACTION_RESULT_MESSAGE, ...result }, "*");
  }

  window.addEventListener("message", (event) => {
    if (event.data?.type === DEPENDENCY_GRAPH_OPEN_MESSAGE) {
      openDependencyGraph({ path: event.data.reservingClass, focus: event.data.focusDatasetName });
      return;
    }
    void handleDependencyGraphAction(event);
  });

  Object.assign(api, {
    initDependencyGraph,
    handleDependencyGraphAction,
    isDependencyGraphWindow,
    notifyDependencyGraphWindows,
    openDependencyGraph,
  });
}
