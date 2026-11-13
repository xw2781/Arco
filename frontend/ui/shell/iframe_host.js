export function createIframeHost(deps) {
  const {
    closeAllShellMenus,
    getColorTheme,
    getIframeHost,
    getState,
    normalizeBrowsingHistoryEntry,
    refreshActiveTab,
    resolveHotkeyAction,
    runHotkeyAction,
    setActive,
    handleShellFileDragOver,
    handleShellFileDrop,
    uiVersionParam,
  } = deps;

  function wireIframeMenuAutoClose(iframe) {
    if (!iframe) return;
    const attachBridge = () => {
      try {
        const frameWin = iframe.contentWindow;
        const frameDoc = frameWin?.document;
        if (!frameWin || !frameDoc) return;
        if (frameWin.__arcRhoShellBridgeWiredV2) return;

        const suppressFrameEvent = (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        };

        const shouldSuppressActivationFollowup = () => {
          const until = Number(frameWin.__arcRhoActivationSuppressUntil || 0);
          return until && Date.now() <= until;
        };

        const activateFrameTab = (e) => {
          if (document.body?.classList?.contains("floatingTabDragActive")) return false;
          const tabId = iframe.dataset.tabId || "";
          if (!tabId) return false;
          const state = getState();
          const tab = state.tabs.find(t => t.id === tabId);
          if (!tab) return false;
          if (state.activeId === tabId) return false;
          frameWin.__arcRhoActivationSuppressUntil = Date.now() + 450;
          setActive(tabId);
          suppressFrameEvent(e);
          return true;
        };

        const closeMenus = () => {
          closeAllShellMenus();
        };

        frameDoc.addEventListener("pointerdown", (e) => {
          if (activateFrameTab(e)) return;
          closeMenus();
        }, true);
        for (const eventName of ["mousedown", "pointerup", "mouseup", "click", "dblclick"]) {
          frameDoc.addEventListener(eventName, (e) => {
            if (!shouldSuppressActivationFollowup()) return;
            suppressFrameEvent(e);
            if (eventName === "click" || eventName === "dblclick") {
              frameWin.__arcRhoActivationSuppressUntil = 0;
            }
          }, true);
        }
        frameWin.addEventListener("keydown", (e) => {
          if (e.key === "Escape") closeMenus();
          const key = String(e.key || "");
          const shellHotkeyAction = resolveHotkeyAction?.(e);
          if (shellHotkeyAction === "settings_clear_cache_reload" || shellHotkeyAction === "settings_toggle_color_theme") {
            e.preventDefault();
            e.stopPropagation();
            if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
            if (!e.repeat) runHotkeyAction?.(shellHotkeyAction);
            return;
          }
          const isRefreshKey = (key === "F5" && e.ctrlKey) || ((key === "r" || key === "R") && e.ctrlKey && !e.shiftKey);
          if (isRefreshKey) {
            e.preventDefault();
            e.stopPropagation();
            refreshActiveTab();
          }
        }, true);
        frameDoc.addEventListener("dragover", (e) => {
          if (typeof handleShellFileDragOver === "function" && handleShellFileDragOver(e)) return;
        }, true);
        frameDoc.addEventListener("drop", (e) => {
          if (typeof handleShellFileDrop === "function" && handleShellFileDrop(e)) return;
        }, true);
        frameWin.__arcRhoShellBridgeWiredV2 = true;
      } catch {
        // ignore cross-frame wiring failures
      }
    };

    iframe.addEventListener("load", attachBridge);
    attachBridge();
  }

  function ensureIframe(tab) {
    const iframeHost = getIframeHost();
    if (!iframeHost) return;

    if (tab.iframe && !tab.iframe.isConnected) {
      tab.iframe = null;
    }

    if (tab.iframe) {
      tab.iframe.dataset.tabId = tab.id;
      return;
    }

    const iframe = document.createElement("iframe");
    iframe.dataset.tabId = tab.id;
    iframe.style.width = "100%";
    iframe.style.height = "100%";
    iframe.style.border = "0";
    iframe.style.display = "none";
    wireIframeMenuAutoClose(iframe);
    iframe.addEventListener("load", () => {
      const theme = getColorTheme?.() || "light";
      const messageType = window.ArcRhoColorTheme?.MESSAGE_TYPE || "arcrho:set-color-theme";
      const themeApi = window.ArcRhoColorTheme;
      try {
        iframe.contentWindow?.postMessage({ type: messageType, theme }, "*");
        if (themeApi?.getTableStyle) {
          iframe.contentWindow?.postMessage({
            type: themeApi.TABLE_STYLE_MESSAGE_TYPE,
            tableStyle: themeApi.getTableStyle(),
          }, "*");
        }
      } catch {
        // The shared theme bootstrap still applies the persisted value if messaging is unavailable.
      }
    });

    if (tab.type === "dataset") {
      const params = new URLSearchParams();
      if (tab.datasetId) params.set("ds", tab.datasetId);
      const initial = normalizeBrowsingHistoryEntry(tab.datasetInputs || null);
      if (initial) {
        params.set("project", initial.project);
        params.set("path", initial.path);
        params.set("tri", initial.tri);
      }
      const inst = tab.dsInst || tab.id || `ds_${Date.now()}`;
      params.set("inst", inst);
      params.set("v", uiVersionParam);
      iframe.src = `/ui/dataset_viewer/dataset_viewer.html?${params.toString()}`;
    } else if (tab.type === "dfm") {
      const params = new URLSearchParams();
      if (tab.datasetId) params.set("ds", tab.datasetId);
      const inst = tab.dsInst || tab.id || `dfm_${Date.now()}`;
      params.set("inst", inst);
      params.set("v", uiVersionParam);
      if (tab.dfmTab) params.set("tab", tab.dfmTab);
      const inputs = tab.dfmInputs && typeof tab.dfmInputs === "object" ? tab.dfmInputs : {};
      if (inputs.project) params.set("project", String(inputs.project));
      if (inputs.reservingClass) params.set("class", String(inputs.reservingClass));
      if (inputs.methodName) params.set("method_name", String(inputs.methodName));
      if (inputs.outputType) params.set("output_type", String(inputs.outputType));
      if (inputs.outputDataset) params.set("output_dataset", String(inputs.outputDataset));
      if (inputs.inputTriangle) params.set("input_triangle", String(inputs.inputTriangle));
      iframe.src = `/ui/method_pages/dfm/dfm.html?${params.toString()}`;
    } else if (tab.type === "bornhuetter_ferguson") {
      const params = new URLSearchParams();
      params.set("inst", tab.dsInst || tab.id || `bf_${Date.now()}`);
      params.set("v", uiVersionParam);
      if (tab.bfTab) params.set("tab", tab.bfTab);
      iframe.src = `/ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html?${params.toString()}`;
    } else if (tab.type === "cape_cod") {
      const params = new URLSearchParams();
      params.set("inst", tab.dsInst || tab.id || `cc_${Date.now()}`);
      params.set("v", uiVersionParam);
      if (tab.ccTab) params.set("tab", tab.ccTab);
      iframe.src = `/ui/method_pages/cape_cod/cape_cod.html?${params.toString()}`;
    } else if (tab.type === "result_selection") {
      const params = new URLSearchParams();
      params.set("inst", tab.dsInst || tab.id || `rs_${Date.now()}`);
      params.set("v", uiVersionParam);
      if (tab.rsTab) params.set("tab", tab.rsTab);
      iframe.src = `/ui/method_pages/result_selection/result_selection.html?${params.toString()}`;
    } else if (tab.type === "workflow") {
      const inst = tab.wfInst || tab.id || `wf_${Date.now()}`;
      const params = new URLSearchParams();
      params.set("inst", inst);
      params.set("v", uiVersionParam);
      if (tab.wfFresh) params.set("fresh", "1");
      iframe.src = `/ui/workflow/workflow.html?${params.toString()}`;
      tab.wfFresh = false;
    } else if (tab.type === "project_settings") {
      iframe.src = `/ui/project_settings/project_settings.html?v=${encodeURIComponent(uiVersionParam)}`;
    } else if (tab.type === "project_instance") {
      const params = new URLSearchParams();
      params.set("project", String(tab.projectName || tab.title || "").trim());
      if (tab.projectFolder) params.set("folder", String(tab.projectFolder || ""));
      if (tab.projectTablePath) params.set("tablePath", String(tab.projectTablePath || ""));
      params.set("v", uiVersionParam);
      iframe.addEventListener("load", () => {
        const state = tab.projectInstanceState && typeof tab.projectInstanceState === "object"
          ? tab.projectInstanceState
          : null;
        if (!state) return;
        try {
          iframe.contentWindow?.postMessage({ type: "arcrho:project-instance-restore-state", state }, "*");
        } catch {
          // ignore
        }
      });
      iframe.src = `/ui/project_instance/project_instance.html?${params.toString()}`;
    } else if (tab.type === "browsing_history") {
      iframe.src = `/ui/shell/browsing_history.html?v=${encodeURIComponent(uiVersionParam)}`;
    } else if (tab.type === "file_explorer") {
      iframe.addEventListener("load", () => {
        try {
          iframe.contentWindow?.postMessage({
            type: "arcrho:file-explorer-visibility",
            visible: iframe.style.display !== "none",
          }, "*");
          if (tab.fileExplorerPath) iframe.contentWindow?.postMessage({ type: "arcrho:file-explorer-open-path", path: tab.fileExplorerPath }, "*");
        } catch {
          // ignore
        }
      });
      iframe.src = `/ui/file_explorer/file_explorer.html?v=${encodeURIComponent(uiVersionParam)}`;
    } else if (tab.type === "agent_guide") {
      iframe.src = `/ui/agent_guide/agent_guide.html?v=${encodeURIComponent(uiVersionParam)}`;
    } else if (tab.type === "server") {
      iframe.src = `/ui/server/server.html?v=${encodeURIComponent(uiVersionParam)}`;
    } else if (tab.type === "dashboard") {
      const params = new URLSearchParams();
      params.set("v", uiVersionParam);
      if (tab.dashboardPath) params.set("path", String(tab.dashboardPath));
      iframe.src = `/ui/dashboard/dashboard.html?${params.toString()}`;
    } else if (tab.type === "task_designer") {
      const params = new URLSearchParams();
      const options = tab.taskDesignerOptions && typeof tab.taskDesignerOptions === "object" ? tab.taskDesignerOptions : {};
      params.set("v", uiVersionParam);
      if (options.title) params.set("title", String(options.title));
      if (options.contextLabel) params.set("context", String(options.contextLabel));
      if (options.macroId) params.set("macro", String(options.macroId));
      if (options.autoRun) params.set("autorun", "1");
      if (options.contextTabId) params.set("contextTabId", String(options.contextTabId));
      iframe.src = `/ui/task_designer/task_designer.html?${params.toString()}`;
    } else if (tab.type === "scripting") {
      const inst = tab.scInst || tab.id || `sc_${Date.now()}`;
      const openPath = String(tab.scOpenPath || "").trim();
      const params = new URLSearchParams();
      params.set("inst", inst);
      params.set("v", uiVersionParam);
      if (tab.scFresh) params.set("fresh", "1");
      if (openPath) {
        params.set("skipLast", "1");
        iframe.addEventListener("load", () => {
          try {
            iframe.contentWindow?.postMessage({ type: "arcode:scripting-open-path", path: openPath }, "*");
          } catch {
            // ignore
          }
          tab.scOpenPath = "";
        }, { once: true });
      }
      iframe.src = `/ui/arcode/notebook-editor/?${params.toString()}`;
      tab.scFresh = false;
    }

    iframeHost.appendChild(iframe);
    tab.iframe = iframe;
  }

  return {
    ensureIframe,
  };
}
