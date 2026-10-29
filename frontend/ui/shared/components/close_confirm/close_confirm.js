const STYLE_ID = "pageCloseConfirmStyles";
let confirmSequence = 0;

function ensureStyles(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const link = doc.createElement("link");
  link.id = STYLE_ID;
  link.rel = "stylesheet";
  link.href = "/ui/shared/components/close_confirm/close_confirm.css?v=20260715a";
  doc.head.appendChild(link);
}

function closeCopy(reason) {
  const isClose = reason === "close";
  return {
    title: isClose ? "Close without saving?" : "Discard changes?",
    message: "Unsaved changes will be lost.",
    confirmLabel: isClose ? "Close" : "Discard",
    cancelLabel: "Keep editing",
  };
}

export function createPageCloseConfirm({ documentRef = document } = {}) {
  const doc = documentRef;
  ensureStyles(doc);

  const id = `pageCloseConfirm${++confirmSequence}`;
  const overlay = doc.createElement("div");
  overlay.className = "pageCloseConfirmOverlay";
  overlay.hidden = true;
  overlay.setAttribute("aria-hidden", "true");
  overlay.innerHTML = `
    <div class="pageCloseConfirmBox" role="dialog" aria-modal="true" aria-labelledby="${id}Title" aria-describedby="${id}Message">
      <button class="pageCloseConfirmClose" type="button" aria-label="Close dialog">
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <path d="M4 4l8 8M12 4l-8 8"></path>
        </svg>
      </button>
      <div class="pageCloseConfirmTitle" id="${id}Title"></div>
      <div class="pageCloseConfirmMessage" id="${id}Message"></div>
      <div class="pageCloseConfirmActions">
        <button class="pageCloseConfirmButton primary" type="button" data-close-confirm-value="yes">Close</button>
        <button class="pageCloseConfirmButton secondary" type="button" data-close-confirm-value="cancel">Keep editing</button>
      </div>
    </div>
  `;
  doc.body.appendChild(overlay);

  const titleEl = overlay.querySelector(".pageCloseConfirmTitle");
  const messageEl = overlay.querySelector(".pageCloseConfirmMessage");
  const yesButton = overlay.querySelector("[data-close-confirm-value='yes']");
  const cancelButton = overlay.querySelector("[data-close-confirm-value='cancel']");
  const closeButton = overlay.querySelector(".pageCloseConfirmClose");
  let pending = null;
  let returnFocus = null;
  let inertSiblings = [];

  function setPageInert(value) {
    if (value) {
      inertSiblings = Array.from(doc.body.children)
        .filter((element) => element !== overlay)
        .map((element) => ({ element, inert: !!element.inert }));
      for (const item of inertSiblings) item.element.inert = true;
      return;
    }
    for (const item of inertSiblings) {
      if (item.element?.isConnected) item.element.inert = item.inert;
    }
    inertSiblings = [];
  }

  function focusableElements() {
    return Array.from(overlay.querySelectorAll("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])"));
  }

  function finish(value) {
    if (!pending) return;
    const resolve = pending.resolve;
    pending = null;
    overlay.hidden = true;
    overlay.setAttribute("aria-hidden", "true");
    setPageInert(false);
    const focusTarget = returnFocus;
    returnFocus = null;
    if (focusTarget?.isConnected && typeof focusTarget.focus === "function") {
      requestAnimationFrame(() => focusTarget.focus());
    }
    resolve(!!value);
  }

  function handleKeydown(event) {
    if (!pending) return;
    event.stopImmediatePropagation();
    if (event.key === "Escape") {
      event.preventDefault();
      finish(false);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements();
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && doc.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && doc.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  overlay.addEventListener("click", (event) => {
    const action = event.target.closest("[data-close-confirm-value]")?.dataset.closeConfirmValue;
    if (action === "yes") finish(true);
    else if (action === "cancel" || event.target === overlay) finish(false);
  });
  closeButton.addEventListener("click", () => finish(false));
  overlay.addEventListener("wheel", (event) => event.preventDefault(), { passive: false });
  doc.addEventListener("keydown", handleKeydown, true);

  function confirm({ reason = "close", title = "", message = "", confirmLabel = "", cancelLabel = "" } = {}) {
    if (pending) return pending.promise;
    const copy = closeCopy(reason);
    titleEl.textContent = String(title || copy.title);
    messageEl.textContent = String(message || copy.message);
    yesButton.textContent = String(confirmLabel || copy.confirmLabel);
    cancelButton.textContent = String(cancelLabel || copy.cancelLabel);
    returnFocus = doc.activeElement;
    overlay.hidden = false;
    overlay.setAttribute("aria-hidden", "false");
    setPageInert(true);
    const promise = new Promise((resolve) => {
      pending = { resolve, promise: null };
    });
    pending.promise = promise;
    requestAnimationFrame(() => yesButton.focus());
    return promise;
  }

  function destroy() {
    if (pending) finish(false);
    doc.removeEventListener("keydown", handleKeydown, true);
    overlay.remove();
  }

  return {
    confirm,
    close: () => finish(false),
    destroy,
    get isOpen() { return !!pending; },
    elements: { overlay, yesButton, cancelButton },
  };
}

// One dialog per document for hosts that close things from several places (tabs, windows, quit).
let sharedConfirm = null;
let sharedConfirmDoc = null;

export function confirmDiscardClose(options = {}) {
  if (!sharedConfirm || sharedConfirmDoc !== document || !sharedConfirm.elements.overlay.isConnected) {
    sharedConfirm = createPageCloseConfirm({ documentRef: document });
    sharedConfirmDoc = document;
  }
  return sharedConfirm.confirm(options);
}
