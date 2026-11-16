export function installProjectInstanceLoading(ctx) {
  const { api, els, projectName, state } = ctx;
  const { datasetWindows, pageLoadingTasks, pageLoadingLabels } = state;
  const toText = (...args) => api.toText(...args);

function postZoomToDatasetFrame(iframe, detail = state.lastZoomDetail) {
  if (!iframe?.contentWindow || !detail) return;
  try {
    iframe.contentWindow.postMessage({
      type: "arcrho:set-zoom",
      zoom: detail.zoom,
      statusBarHeight: detail.statusBarHeight,
    }, "*");
  } catch {
    // ignore nested iframe zoom sync failures
  }
}

function broadcastZoomToDatasetWindows(detail = state.lastZoomDetail) {
  for (const frame of datasetWindows.values()) {
    postZoomToDatasetFrame(frame?.querySelector?.("iframe"), detail);
  }
}

window.ArcRhoZoomBridge?.wirePageZoomBridge({
  onApplied: (detail) => {
    state.lastZoomDetail = detail;
    broadcastZoomToDatasetWindows(detail);
  },
});


async function applyHostFrameCornerStyle() {
  let frame = "";
  if (typeof window.ADAHost?.windowsFrameStyle === "function") {
    try {
      frame = await window.ADAHost.windowsFrameStyle();
    } catch {
      frame = "";
    }
  }

  document.body.classList.toggle("win11-frame", frame === "win11");
  document.body.classList.toggle("win10-borders", frame === "win10");
}


function setStatus(text, isError = false) {
  if (isError) console.warn(toText(text));
}

function postProjectInstanceStatus(text, tone = "") {
  const statusText = toText(text);
  if (!statusText) return;
  try {
    window.parent?.postMessage({
      type: "arcrho:status",
      text: statusText,
      ...(tone ? { tone } : {}),
    }, "*");
  } catch {}
}


function getPageLoadingMessage() {
  const loadingPaths = pageLoadingTasks.has("paths");
  const loadingDatasets = pageLoadingTasks.has("datasets");
  const loadingPreferences = pageLoadingTasks.has("preferences");
  if (loadingPaths && loadingDatasets) return "Loading reserving class paths and dataset types...";
  if (loadingPaths) return "Loading reserving class paths...";
  if (loadingDatasets) return "Loading dataset types...";
  if (loadingPreferences) return "Loading project preferences...";
  return "Loading project contents...";
}

function updatePageLoadingText() {
  // A task that named itself owns the card, so an action such as a delete reads
  // as itself instead of borrowing the project-load wording. Map keeps
  // insertion order, so the most recent labelled task wins.
  const labels = Array.from(pageLoadingLabels.values()).at(-1) || null;
  if (els.pageLoadingTitle) {
    els.pageLoadingTitle.textContent = labels?.title || "Loading Project Instance";
  }
  if (els.pageLoadingMessage) {
    els.pageLoadingMessage.textContent = labels?.message || getPageLoadingMessage();
  }
}

function stopPageLoadingTimer() {
  if (!state.pageLoadingFrameTimer) return;
  cancelAnimationFrame(state.pageLoadingFrameTimer);
  state.pageLoadingFrameTimer = 0;
}

function tickPageLoadingElapsed() {
  if (!els.pageLoadingOverlay?.classList?.contains("open")) {
    stopPageLoadingTimer();
    return;
  }
  const sec = (performance.now() - state.pageLoadingStartedAt) / 1000;
  if (els.pageLoadingElapsed) els.pageLoadingElapsed.textContent = `Elapsed: ${sec.toFixed(1)}s`;
  state.pageLoadingFrameTimer = requestAnimationFrame(tickPageLoadingElapsed);
}

function beginPageLoading(task, labels = null) {
  if (!els.pageLoadingOverlay) return;
  const wasEmpty = pageLoadingTasks.size === 0;
  pageLoadingTasks.add(task);
  const title = toText(labels?.title);
  const message = toText(labels?.message);
  if (title || message) pageLoadingLabels.set(task, { title, message });
  updatePageLoadingText();
  if (!wasEmpty) return;
  state.pageLoadingStartedAt = performance.now();
  if (els.pageLoadingElapsed) els.pageLoadingElapsed.textContent = "Elapsed: 0.0s";
  els.pageLoadingOverlay.classList.add("open");
  stopPageLoadingTimer();
  state.pageLoadingFrameTimer = requestAnimationFrame(tickPageLoadingElapsed);
}

function finishPageLoading(task) {
  if (!task) {
    pageLoadingTasks.clear();
    pageLoadingLabels.clear();
  } else {
    pageLoadingTasks.delete(task);
    pageLoadingLabels.delete(task);
  }
  updatePageLoadingText();
  if (pageLoadingTasks.size > 0) return;
  els.pageLoadingOverlay?.classList?.remove("open");
  stopPageLoadingTimer();
}

  Object.assign(api, {
    applyHostFrameCornerStyle,
    beginPageLoading,
    broadcastZoomToDatasetWindows,
    finishPageLoading,
    getPageLoadingMessage,
    postProjectInstanceStatus,
    postZoomToDatasetFrame,
    setStatus,
    stopPageLoadingTimer,
    tickPageLoadingElapsed,
    updatePageLoadingText
  });
}
