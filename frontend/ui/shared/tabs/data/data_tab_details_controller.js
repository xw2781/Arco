// Owns formula/dependency details, audit presentation, and Data-tab chrome.

import {
  createDetailsDependenciesView,
  normalizeDependencyEntries,
} from "/ui/shared/tabs/details/details_dependencies.js?v=20261020b";

export function registerDataTabDetailsController(runtime) {
  const {
    DATASET_VIEWER_APP_DEFAULT_TAB,
    DATASET_VIEWER_TAB_IDS,
    instanceId,
    isProjectInstanceHost,
    qs,
  } = runtime;
  const defer = (name) => (...args) => runtime[name](...args);
  const { getDataTabAuditController, getDatasetTypeFormulaByName, getBerquistShermanContract, setStatus, buildDatasetSidecarContextPayload, renderTable } = new Proxy({}, { get: (_target, name) => defer(name) });
  let datasetAuditLog = null;

  function getDatasetAuditLog() {
    if (!datasetAuditLog) datasetAuditLog = getDataTabAuditController();
    return datasetAuditLog;
  }

  function renderDatasetAuditLog(entries = []) {
    getDatasetAuditLog()?.render(entries);
  }

  // The formula field and the Dependencies map are the shared Details surface
  // every method page also shows, so this controller only supplies the
  // Data-tab context it needs and delegates the rendering.
  let dependenciesView = null;

  function getDependenciesView() {
    if (dependenciesView) return dependenciesView;
    dependenciesView = createDetailsDependenciesView({
      formulaBox: "dsDetailFormulaBox",
      dependencyMap: "dsDependencyMap",
      getSelfName: () => buildDatasetSidecarContextPayload().dataset_name,
      getDatasetTypeFormula: (name) => getDatasetTypeFormulaByName(name),
      // The Data tab knows every dataset type in the project, so a formula can
      // name a source that is not in the persisted Precedents graph yet.
      getExtraComponentNames: () => runtime.allDatasetTypes || [],
      getBerquistShermanContract: (variant) => getBerquistShermanContract(variant),
      getContext: () => {
        const payload = buildDatasetSidecarContextPayload();
        return {
          projectName: payload.project_name,
          reservingClass: payload.reserving_class,
        };
      },
      instanceId,
      isProjectInstanceHost,
      setStatus: (message) => setStatus(message),
    });
    return dependenciesView;
  }

  function normalizeDatasetDependencyEntries(entries = []) {
    return normalizeDependencyEntries(entries);
  }

  function renderDetailFormula(formula, precedents = []) {
    const formulaText = String(formula || "").trim();
    const formulaInput = document.getElementById("dsDetailFormula");
    if (formulaInput) {
      formulaInput.value = formulaText;
      formulaInput.removeAttribute("title");
    }
    return getDependenciesView().renderFormula(formulaText, precedents);
  }

  function renderDatasetPrecedents(entries = []) {
    return getDependenciesView().renderPrecedents(entries);
  }

  function renderDatasetDependents(entries = []) {
    return getDependenciesView().renderDependents(entries);
  }

  function hideDependentFormulaTooltip() {
    getDependenciesView().hideTooltip();
  }

  function getDatasetInitialTab() {
    const requested = String(qs.get("tab") || qs.get("initial_tab") || "").trim();
    return DATASET_VIEWER_TAB_IDS.has(requested) ? requested : DATASET_VIEWER_APP_DEFAULT_TAB;
  }

  function setDatasetTopBarCollapsed(collapsed) {
    const dataPage = document.getElementById("dsDataPage");
    const topRow = dataPage?.querySelector(".topRow");
    const dataTab = document.querySelector('.dsTab[data-page="data"]');
    if (!dataPage || !topRow) return;

    const isCollapsed = !!collapsed;
    dataPage.classList.toggle("datasetTopBarCollapsed", isCollapsed);
    topRow.hidden = isCollapsed;
    if (dataTab) {
      dataTab.removeAttribute("title");
      if (isCollapsed) {
        dataTab.dataset.datasetTopBarCollapsed = "1";
        dataTab.dataset.tooltip = "Double-click to show Data controls";
        if (dataTab.matches(":hover") || document.activeElement === dataTab) {
          showDatasetDataTabTooltip(dataTab);
        }
      } else {
        hideDatasetDataTabTooltip();
        delete dataTab.dataset.datasetTopBarCollapsed;
        delete dataTab.dataset.tooltip;
      }
    }

    requestAnimationFrame(() => {
      renderTable();
    });
  }

  function isDatasetTopBarCollapsed() {
    return document.getElementById("dsDataPage")?.classList.contains("datasetTopBarCollapsed") === true;
  }

  function getDatasetDataTabTooltip() {
    let tooltip = document.getElementById("dsDataTabTooltip");
    if (tooltip) return tooltip;
    tooltip = document.createElement("div");
    tooltip.id = "dsDataTabTooltip";
    tooltip.className = "dsDataTabTooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.hidden = true;
    document.body.appendChild(tooltip);
    return tooltip;
  }

  function positionDatasetDataTabTooltip(tab, tooltip) {
    const rect = tab.getBoundingClientRect();
    const margin = 6;
    tooltip.style.left = "0px";
    tooltip.style.top = "0px";
    tooltip.hidden = false;
    const width = tooltip.offsetWidth || 0;
    const height = tooltip.offsetHeight || 0;
    const belowTop = rect.bottom + margin;
    const aboveTop = rect.top - height - margin;
    const useAbove = belowTop + height > window.innerHeight - margin && aboveTop >= margin;
    const top = useAbove ? aboveTop : belowTop;
    const centeredLeft = rect.left + (rect.width / 2) - (width / 2);
    const left = Math.max(margin, Math.min(centeredLeft, window.innerWidth - width - margin));
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(Math.max(margin, top))}px`;
  }

  function showDatasetDataTabTooltip(tab) {
    if (!tab || !isDatasetTopBarCollapsed()) return;
    const text = tab.dataset.tooltip || "";
    if (!text) return;
    const tooltip = getDatasetDataTabTooltip();
    tooltip.textContent = text;
    tooltip.hidden = false;
    positionDatasetDataTabTooltip(tab, tooltip);
    tooltip.classList.add("open");
  }

  function hideDatasetDataTabTooltip() {
    const tooltip = document.getElementById("dsDataTabTooltip");
    if (!tooltip) return;
    tooltip.classList.remove("open");
    tooltip.hidden = true;
  }

  function toggleDatasetTopBarCollapsed() {
    const dataPage = document.getElementById("dsDataPage");
    const collapsed = !dataPage?.classList.contains("datasetTopBarCollapsed");
    setDatasetTopBarCollapsed(collapsed);
    setStatus(collapsed ? "Dataset Data controls hidden." : "Dataset Data controls shown.");
  }

  function wireDatasetDataTabTopBarToggle(tabSystem) {
    const dataTab = document.querySelector('.dsTab[data-page="data"]');
    if (!dataTab || dataTab.dataset.datasetTopBarToggleWired === "1") return;
    dataTab.dataset.datasetTopBarToggleWired = "1";
    setDatasetTopBarCollapsed(false);
    dataTab.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (tabSystem?.getCurrentTab?.() !== "data") tabSystem?.setActive?.("data");
      toggleDatasetTopBarCollapsed();
    });
    dataTab.addEventListener("mouseenter", () => showDatasetDataTabTooltip(dataTab));
    dataTab.addEventListener("mouseleave", hideDatasetDataTabTooltip);
    dataTab.addEventListener("focus", () => showDatasetDataTabTooltip(dataTab));
    dataTab.addEventListener("blur", hideDatasetDataTabTooltip);
    window.addEventListener("resize", hideDatasetDataTabTooltip);
    window.addEventListener("scroll", hideDatasetDataTabTooltip, true);
  }


  Object.assign(runtime, {
    getDatasetAuditLog,
    renderDatasetAuditLog,
    normalizeDatasetDependencyEntries,
    renderDetailFormula,
    hideDependentFormulaTooltip,
    renderDatasetDependents,
    renderDatasetPrecedents,
    getDatasetInitialTab,
    setDatasetTopBarCollapsed,
    isDatasetTopBarCollapsed,
    getDatasetDataTabTooltip,
    positionDatasetDataTabTooltip,
    showDatasetDataTabTooltip,
    hideDatasetDataTabTooltip,
    toggleDatasetTopBarCollapsed,
    wireDatasetDataTabTopBarToggle,
  });
}
