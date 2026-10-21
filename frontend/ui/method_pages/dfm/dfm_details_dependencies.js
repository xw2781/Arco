/*
 * DFM Details - the Dependencies map.
 *
 * A leaf module on purpose. `dfm_details.js` already imports `dfm_persistence.js`,
 * and the persistence layer is what knows when the output identity is resolved,
 * so putting this in `dfm_details.js` would close an import cycle.
 */
import {
  getDfmInst,
  getResolvedProjectName,
  getResolvedReservingClass,
} from "/ui/method_pages/dfm/dfm_state.js";
import { createDetailsDependenciesController } from "/ui/shared/tabs/details/details_dependencies.js?v=20261020b";

let controller = null;
let outputDatasetName = "";

function postStatus(message) {
  const text = String(message ?? "").trim();
  if (!text) return;
  try {
    window.parent?.postMessage({ type: "arcrho:status", text }, "*");
  } catch {}
}

function getController() {
  if (controller) return controller;
  controller = createDetailsDependenciesController({
    dependencyMap: "dfmDependencyMap",
    getSelfMethodType: () => "DFM",
    // The graph is keyed by the dataset the DFM publishes - not by the method
    // name, and not by the input triangle the Data tab happens to be showing.
    getIdentity: () => ({
      projectName: getResolvedProjectName(),
      reservingClass: getResolvedReservingClass(),
      datasetName: outputDatasetName,
    }),
    instanceId: getDfmInst(),
    isProjectInstanceHost: window.parent !== window,
    setStatus: postStatus,
  });
  return controller;
}

/**
 * Repaints the Details Dependencies map for the dataset this DFM
 * publishes. Call it whenever the output identity is resolved: on load, and
 * after a save, which rewrites the graph on both sides.
 */
export function refreshDfmDetailsDependencies(outputDataset) {
  const name = String(outputDataset ?? "").trim();
  if (name) outputDatasetName = name;
  if (!outputDatasetName) {
    getController().clear();
    return Promise.resolve(null);
  }
  return getController().refresh().catch(() => null);
}

export function clearDfmDetailsDependencies() {
  outputDatasetName = "";
  getController().clear();
}
