/**
 * Project Settings - project switch cover.
 *
 * Dims the whole detail panel and shows a small message box for a moment
 * after the user picks another project, so the change reads clearly even when
 * the new project loads instantly. Its bar glides toward the end while the
 * pages load, finishes once they settle and the minimum time has passed, and
 * then the cover fades. Past the maximum wait, each page's own loading
 * placeholder takes over.
 */

const MIN_VISIBLE_MS = 1000;
const MAX_WAIT_MS = 3000;
const FINISH_MS = 260;
const LEAVE_MS = 180;
// The glide never reaches the end on its own; only a finished load fills it.
const GLIDE_TO = "88%";
const GLIDE_EASE = "cubic-bezier(0.1, 0.65, 0.25, 1)";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));

/** `cover` holds a `.detail-switch-label` for the project name and a `.detail-switch-fill` bar. */
export function createSwitchCover(cover) {
  const label = cover?.querySelector(".detail-switch-label");
  const fill = cover?.querySelector(".detail-switch-fill");
  let token = 0;
  let leaveTimer = 0;

  /** Show the cover for a project; returns the handle `hide` needs. */
  function show(projectName) {
    if (!cover) return null;
    clearTimeout(leaveTimer);
    cover.classList.remove("is-leaving");
    if (label) label.textContent = `Loading ${String(projectName || "project")}...`;
    cover.hidden = false;
    if (fill) {
      fill.style.transition = "none";
      fill.style.width = "0";
      void fill.offsetWidth; // Restart the glide from empty.
      fill.style.transition = `width ${MAX_WAIT_MS}ms ${GLIDE_EASE}`;
      fill.style.width = GLIDE_TO;
    }
    token += 1;
    return { token, startedAt: performance.now() };
  }

  /** Lift the cover after the minimum time, once `loads` settle or time out. */
  async function hide(handle, loads = []) {
    if (!cover || !handle) return;
    const elapsed = () => performance.now() - handle.startedAt;
    await Promise.race([Promise.allSettled(loads), wait(MAX_WAIT_MS - elapsed())]);
    await wait(MIN_VISIBLE_MS - elapsed());
    if (handle.token !== token) return; // A later switch owns the cover.
    if (fill) {
      fill.style.transition = `width ${FINISH_MS}ms ease-out`;
      fill.style.width = "100%";
      await wait(FINISH_MS);
      if (handle.token !== token) return;
    }
    cover.classList.add("is-leaving");
    leaveTimer = setTimeout(() => {
      if (handle.token !== token) return;
      cover.hidden = true;
      cover.classList.remove("is-leaving");
    }, LEAVE_MS);
  }

  /** Drop the cover at once, e.g. when the selection is cleared. */
  function cancel() {
    if (!cover) return;
    token += 1;
    clearTimeout(leaveTimer);
    cover.hidden = true;
    cover.classList.remove("is-leaving");
  }

  return { show, hide, cancel };
}
