// Advisory reserving-class busy watch: while Arco Engine runs a dependent
// walk for the selected reserving class -- this app instance's save or another
// user's -- Project Instance pauses its own dataset edit actions. There is no
// visible banner; live propagation updates stream inside the saving window's
// popup, and a blocked action explains itself in the status bar. The app
// server enforces the same hold by refusing writes with 423, so this freeze
// is purely UX; a missed poll can never corrupt anything.

const BUSY_POLL_INTERVAL_MS = 5000;

export function installProjectInstanceBusyBanner(ctx) {
  const { api, projectName, state } = ctx;

  let pollTimer = 0;
  let checkSeq = 0;

  function selectedReservingClassPath() {
    const normalize = api.normalizePath || ((value) => String(value || "").trim());
    return normalize(state.selectedPath);
  }

  async function checkReservingClassBusy() {
    const path = selectedReservingClassPath();
    const seq = ++checkSeq;
    if (!projectName || !path) {
      state.reservingClassBusy = false;
      return;
    }
    let busy = false;
    try {
      const url = new URL("/dependent_propagation/reserving_class_busy", window.location.origin);
      url.searchParams.set("project_name", projectName);
      url.searchParams.set("reserving_class", path);
      const resp = await fetch(url.toString(), { cache: "no-store" });
      const payload = await resp.json().catch(() => ({}));
      if (resp.ok && payload?.ok) busy = !!payload.busy;
    } catch {
      // Advisory probe: a failed poll is skipped, never surfaced.
    }
    // A newer check (path switch or manual refresh) supersedes this result.
    if (seq !== checkSeq || path !== selectedReservingClassPath()) return;
    state.reservingClassBusy = busy;
  }

  function startReservingClassBusyWatch() {
    if (pollTimer) return;
    pollTimer = window.setInterval(() => void checkReservingClassBusy(), BUSY_POLL_INTERVAL_MS);
    void checkReservingClassBusy();
  }

  /** Re-probes immediately, e.g. right after the selected path changes. */
  function refreshReservingClassBusyNow() {
    void checkReservingClassBusy();
  }

  function isReservingClassBusy() {
    return !!state.reservingClassBusy;
  }

  window.addEventListener("pagehide", () => {
    if (pollTimer) {
      window.clearInterval(pollTimer);
      pollTimer = 0;
    }
  });

  Object.assign(api, {
    startReservingClassBusyWatch,
    refreshReservingClassBusyNow,
    isReservingClassBusy,
  });
}
