// Small controls the Dashboards page builds its panels from: app-styled pick lists (single and
// multi), a modal frame, and the two structural glyphs. Everything is created with DOM calls and
// text nodes, so a field or project name can never be read as markup.

import { attachArcrhoTooltip } from "/ui/shared/components/tooltip/tooltip.js?v=20260925a";

const SVG_NS = "http://www.w3.org/2000/svg";

// The app's shared tooltip, for an icon-only button or a row whose name needs a sentence.
export function tip(node, text) {
  if (text) attachArcrhoTooltip(node, text);
  return node;
}

export function el(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function icon(name) {
  const node = el("span", "dbIcon");
  node.dataset.dbIcon = name;
  node.setAttribute("aria-hidden", "true");
  return node;
}

function glyph(paths, circles = []) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "dbGlyph");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  }
  for (const [cx, cy] of circles) {
    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", cy);
    dot.setAttribute("r", 1.2);
    svg.appendChild(dot);
  }
  return svg;
}

// Structural marks, not artwork: two crossing lines, three dots, a plus, a tick.
export const closeGlyph = () => glyph(["M4 4l8 8M12 4l-8 8"]);
export const moreGlyph = () => glyph([], [[3.5, 8], [8, 8], [12.5, 8]]);
export const plusGlyph = () => glyph(["M8 3.5v9M3.5 8h9"]);
export const checkGlyph = () => glyph(["M3.5 8.5l3 3 6-6.5"]);

export function button(label, { primary = false, iconName = "", title = "", onClick = null, small = false } = {}) {
  const node = el("button", `dbBtn${primary ? " primary" : ""}${small ? " small" : ""}`);
  node.type = "button";
  if (iconName) node.appendChild(icon(iconName));
  if (label) node.appendChild(el("span", "", label));
  if (title) node.setAttribute("aria-label", title);
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

export function iconButton(glyphNode, title, onClick) {
  const node = el("button", "dbIconBtn");
  node.type = "button";
  node.setAttribute("aria-label", title);
  tip(node, title);
  node.appendChild(glyphNode);
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

// ---------------------------------------------------------------------------
// Pick lists
// ---------------------------------------------------------------------------

let openMenu = null;

export function closeMenus() {
  if (!openMenu) return;
  openMenu.menu.remove();
  openMenu.trigger?.setAttribute("aria-expanded", "false");
  document.removeEventListener("pointerdown", openMenu.onOutside, true);
  document.removeEventListener("keydown", openMenu.onKey, true);
  window.removeEventListener("blur", closeMenus);
  openMenu = null;
}

// Open a list under `trigger`. `options` are {value, label, tag?, group?}; `selected` is a Set of
// values. In multi mode a row toggles and the list stays open; otherwise it picks and closes.
export function openPickMenu(trigger, { options, selected, multi = false, search = false, onPick, emptyText = "Nothing to choose" }) {
  closeMenus();
  const menu = el("div", "dbMenu");
  menu.setAttribute("role", "listbox");
  const list = el("div", "dbMenuList");
  let filterInput = null;
  if (search || options.length > 12) {
    filterInput = el("input", "dbMenuSearch");
    filterInput.type = "text";
    filterInput.placeholder = "Search";
    filterInput.spellcheck = false;
    menu.appendChild(filterInput);
  }
  menu.appendChild(list);

  function draw() {
    const needle = (filterInput?.value || "").trim().toLowerCase();
    list.replaceChildren();
    let group = "";
    let shown = 0;
    for (const option of options) {
      if (needle && !String(option.label).toLowerCase().includes(needle)) continue;
      if (option.group && option.group !== group) {
        group = option.group;
        list.appendChild(el("div", "dbMenuGroup", group));
      }
      const row = el("button", "dbMenuRow");
      row.type = "button";
      row.setAttribute("role", "option");
      const isSelected = selected.has(option.value);
      row.setAttribute("aria-selected", String(isSelected));
      const mark = el("span", "dbMenuCheck");
      if (isSelected) mark.appendChild(checkGlyph());
      row.append(mark, el("span", "dbMenuLabel", option.label));
      if (option.tag) row.appendChild(el("span", "dbMenuTag", option.tag));
      row.addEventListener("click", () => {
        if (multi) {
          if (selected.has(option.value)) selected.delete(option.value);
          else selected.add(option.value);
          onPick([...selected]);
          draw();
        } else {
          closeMenus();
          onPick(option.value);
        }
      });
      list.appendChild(row);
      shown += 1;
    }
    if (!shown) list.appendChild(el("div", "dbMenuEmpty", needle ? "No match" : emptyText));
  }
  draw();
  filterInput?.addEventListener("input", draw);

  document.body.appendChild(menu);
  const box = trigger.getBoundingClientRect();
  menu.style.minWidth = `${Math.max(160, box.width)}px`;
  const menuBox = menu.getBoundingClientRect();
  const below = window.innerHeight - box.bottom - 8;
  const top = below >= Math.min(menuBox.height, 180) ? box.bottom + 2 : Math.max(8, box.top - menuBox.height - 2);
  menu.style.maxHeight = `${Math.max(140, (top >= box.bottom ? below : box.top - 16))}px`;
  menu.style.top = `${top}px`;
  menu.style.left = `${Math.max(8, Math.min(box.left, window.innerWidth - menuBox.width - 8))}px`;
  trigger.setAttribute("aria-expanded", "true");
  const onOutside = (event) => {
    if (!menu.contains(event.target) && !trigger.contains(event.target)) closeMenus();
  };
  const onKey = (event) => { if (event.key === "Escape") { event.stopPropagation(); closeMenus(); trigger.focus(); } };
  document.addEventListener("pointerdown", onOutside, true);
  document.addEventListener("keydown", onKey, true);
  window.addEventListener("blur", closeMenus);
  openMenu = { menu, trigger, onOutside, onKey };
  (filterInput || list.querySelector(".dbMenuRow"))?.focus();
}

// A select-like control. `get` returns the current value and `set` stores a new one.
export function pickField({ options, value, placeholder = "Choose", onChange, search = false, allowNone = "" }) {
  const trigger = el("button", "dbPick");
  trigger.type = "button";
  trigger.setAttribute("aria-haspopup", "listbox");
  const label = el("span", "dbPickLabel");
  trigger.append(label, el("span", "dbCaret"));
  const all = allowNone ? [{ value: "", label: allowNone }, ...options] : options;
  const show = (current) => {
    const match = all.find((option) => option.value === current);
    label.textContent = match ? match.label : (current || placeholder);
    label.classList.toggle("dbPlaceholder", !current);
    // A stored value the source no longer offers stays visible, marked, until the user changes it.
    trigger.classList.toggle("dbPickMissing", !!current && !match);
  };
  show(value);
  trigger.addEventListener("click", () => {
    openPickMenu(trigger, {
      options: all,
      selected: new Set([value]),
      search,
      onPick: (next) => { value = next; show(next); onChange(next); },
    });
  });
  return trigger;
}

export function multiPickField({ options, values, placeholder = "All", onChange, search = true, summary = null }) {
  const trigger = el("button", "dbPick");
  trigger.type = "button";
  trigger.setAttribute("aria-haspopup", "listbox");
  const label = el("span", "dbPickLabel");
  trigger.append(label, el("span", "dbCaret"));
  let current = [...values];
  const show = () => {
    const names = current.map((value) => options.find((option) => option.value === value)?.label ?? value);
    label.textContent = summary ? summary(current) : !current.length ? placeholder : current.length <= 2 ? names.join(", ") : `${current.length} selected`;
    label.classList.toggle("dbPlaceholder", !current.length);
  };
  show();
  trigger.addEventListener("click", () => {
    openPickMenu(trigger, {
      options,
      selected: new Set(current),
      multi: true,
      search,
      onPick: (next) => {
        // Keep the options' own order rather than the order of the clicks.
        current = options.map((option) => option.value).filter((value) => next.includes(value));
        show();
        onChange(current);
      },
    });
  });
  return trigger;
}

export function textInput({ value = "", placeholder = "", onChange, multiline = false, mono = false }) {
  const node = el(multiline ? "textarea" : "input", `dbInput${mono ? " mono" : ""}`);
  if (!multiline) node.type = "text";
  node.value = value;
  node.placeholder = placeholder;
  node.spellcheck = false;
  node.addEventListener("change", () => onChange(node.value));
  return node;
}

export function formRow(labelText, control) {
  const row = el("div", "dbRow");
  row.append(el("label", "dbRowLabel", labelText), control);
  return row;
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

// A centered dialog. Returns {body, footer, close, setError}. `onClose` runs once however it ends.
export function openModal({ title, wide = false, onClose = null }) {
  const overlay = el("div", "dbOverlay");
  const dialog = el("div", `dbDialog${wide ? " wide" : ""}`);
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  const header = el("div", "dbDialogHeader");
  header.appendChild(el("div", "dbDialogTitle", title));
  const body = el("div", "dbDialogBody");
  const error = el("div", "dbDialogError");
  error.hidden = true;
  const footer = el("div", "dbDialogFooter");
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    closeMenus();
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    onClose?.();
  };
  const onKey = (event) => { if (event.key === "Escape" && !document.querySelector(".dbMenu")) { event.stopPropagation(); close(); } };
  header.appendChild(iconButton(closeGlyph(), "Close", close));
  dialog.append(header, body, error, footer);
  overlay.appendChild(dialog);
  overlay.addEventListener("pointerdown", (event) => { if (event.target === overlay) close(); });
  document.addEventListener("keydown", onKey, true);
  document.body.appendChild(overlay);
  return {
    body,
    footer,
    close,
    setError(message) {
      error.textContent = message || "";
      error.hidden = !message;
    },
  };
}

export function confirmDialog({ title, message, confirmLabel = "OK" }) {
  return new Promise((resolve) => {
    let answer = false;
    const modal = openModal({ title, onClose: () => resolve(answer) });
    modal.body.appendChild(el("div", "dbDialogMessage", message));
    modal.footer.append(
      button("Cancel", { onClick: modal.close }),
      button(confirmLabel, { primary: true, onClick: () => { answer = true; modal.close(); } }),
    );
  });
}

export function promptDialog({ title, label, value = "", confirmLabel = "OK" }) {
  return new Promise((resolve) => {
    let answer = null;
    const modal = openModal({ title, onClose: () => resolve(answer) });
    const input = textInput({ value, onChange: () => {} });
    modal.body.appendChild(formRow(label, input));
    const accept = () => {
      const text = input.value.trim();
      if (!text) return modal.setError("Enter a name.");
      answer = text;
      modal.close();
    };
    input.addEventListener("keydown", (event) => { if (event.key === "Enter") accept(); });
    modal.footer.append(button("Cancel", { onClick: modal.close }), button(confirmLabel, { primary: true, onClick: accept }));
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}
