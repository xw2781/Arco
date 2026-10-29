import { FORMULA_CATALOG, quoteFormulaText } from "/ui/shared/components/formula_bar/formula_completion.js?v=20260917a";
import { ensureFormulaAssistStyles, installFormulaAutocomplete } from "/ui/shared/components/formula_bar/formula_autocomplete.js?v=20260917a";
import { formulaDatasets, formulaProjects, formulaReservingClasses, formulaPageIdentity } from "/ui/shared/components/formula_bar/formula_api.js?v=20260917a";
import { evaluateFormulaValues } from "/ui/shared/dataset/dataset_formula_values.js?v=20260919a";

const GROUPS = ["Arco Data", "Logic", "Math", "Array"];
const BUILTIN_GROUP = { IF: "Logic", IFERROR: "Logic", TAKE: "Array", INDEX: "Array", TRANSPOSE: "Array" };
const LABELS = {
  Path: "Reserving Class", ProjectName: "Project", TriangleName: "Triangle", VectorName: "Vector", DiagonalIndex: "Diagonal",
  logical_test: "Test", value_if_true: "If True", value_if_false: "If False", value_if_error: "If Error",
  num_digits: "Digits", row_num: "Row", column_num: "Column",
};
const LENGTHS = [["12", "Annual"], ["6", "Half-Year"], ["3", "Quarterly"], ["1", "Monthly"]];
const PREVIEW_ROWS = 50, PREVIEW_COLS = 20;
const TEXT_KINDS = ["project", "path", "dataset"];

const isArco = spec => spec.minimum != null;
const groupOf = spec => isArco(spec) ? "Arco Data" : BUILTIN_GROUP[spec.name] || "Math";
const isVariadic = spec => /…$/.test(spec.arguments.at(-1)?.name || "");
const labelOf = name => LABELS[name] || name.replace(/_/g, " ").replace(/([a-z])([A-Z0-9])/g, "$1 $2").replace(/\b\w/g, c => c.toUpperCase());
const sameText = (a, b) => String(a).trim().toLowerCase() === String(b).trim().toLowerCase();

function kindOf(spec, arg) {
  if (!isArco(spec)) return "expression";
  if (arg.name === "ProjectName") return "project";
  if (arg.name === "Path") return "path";
  if (["TriangleName", "VectorName"].includes(arg.name)) return "dataset";
  if (["ByTypeName", "SuppressWarnings"].includes(arg.name)) return "hidden";
  if (typeof arg.default === "boolean") return "bool";
  return /Length$/.test(arg.name) ? "length" : "integer";
}

/** The argument slots a function shows; a variadic list keeps one empty slot after the last value. */
function slotsFor(spec, values = []) {
  if (!isVariadic(spec)) return spec.arguments;
  const stem = spec.arguments[0].name.replace(/\d+$/, "");
  const count = Math.max(2, values.findLastIndex(value => String(value ?? "").trim()) + 2);
  return Array.from({ length: count }, (_, i) => ({ name: `${stem}${i + 1}`, optional: i > 0 }));
}

/** Split `=NAME(a, b)` into its name and top-level arguments; null for anything else. */
export function splitFormulaCall(text) {
  const head = /^\s*=?\s*([A-Za-z_]\w*)\s*\(/.exec(String(text || ""));
  if (!head) return null;
  const parts = [];
  let depth = 0, quote = "", current = "";
  for (let i = head[0].length; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      current += ch;
      if (ch === quote) {
        if (text[i + 1] === quote) { current += ch; i++; } else quote = "";
      }
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; current += ch; continue; }
    if (ch === ")" && !depth) {
      parts.push(current.trim());
      if (text.slice(i + 1).trim()) return null;
      return { name: head[1], parts: parts.length === 1 && !parts[0] ? [] : parts };
    }
    if ("([{".includes(ch)) depth++;
    if (")]}".includes(ch)) depth--;
    if (ch === "," && !depth) { parts.push(current.trim()); current = ""; continue; }
    current += ch;
  }
  return null;
}

/** Field values for a call's raw arguments, or null when a field cannot show one of them. */
function valuesFromParts(spec, parts) {
  const slots = slotsFor(spec, parts);
  if (parts.length > slots.length) return null;
  const values = [];
  for (const [i, arg] of slots.entries()) {
    const raw = parts[i] ?? "", kind = kindOf(spec, arg);
    if (!raw || kind === "expression" || kind === "hidden") { values.push(raw); continue; }
    if (TEXT_KINDS.includes(kind)) {
      if (!/^"(?:[^"]|"")*"$/.test(raw)) return null;
      const text = raw.slice(1, -1).replaceAll('""', '"');
      values.push(kind === "project" && sameText(text, "Default") ? "" : text);
    } else if (kind === "bool") {
      if (!/^(TRUE|FALSE)$/i.test(raw)) return null;
      values.push(raw.toUpperCase());
    } else if (kind === "length") {
      if (!LENGTHS.some(([value]) => value === raw)) return null;
      values.push(raw);
    } else {
      if (!/^[+-]?\d+$/.test(raw)) return null;
      values.push(raw);
    }
  }
  return values;
}

function argumentText(spec, arg, value) {
  const kind = kindOf(spec, arg), text = String(value ?? "").trim();
  if (!text) return "";
  if (TEXT_KINDS.includes(kind)) return quoteFormulaText(text);
  if (kind === "bool") return text === String(arg.default).toUpperCase() ? "" : text;
  if (kind === "length") return text === String(arg.default) ? "" : text;
  return text;
}

export function buildFormulaCall(spec, values) {
  const slots = slotsFor(spec, values);
  const parts = slots.map((arg, i) => argumentText(spec, arg, values[i]));
  while (parts.length && parts.at(-1) === "" && (isArco(spec) || slots[parts.length - 1].optional)) parts.pop();
  return `=${spec.name}(${parts.join(", ")})`;
}

/** A preview is read-only; Insert writes a draft, and Enter in the bar applies it. */
export function openFormulaHelper(input, {
  identityProvider = formulaPageIdentity, evaluate = evaluateFormulaValues,
  sources = { projects: formulaProjects, reservingClasses: formulaReservingClasses, datasets: formulaDatasets },
  previewDelay = 300, onInsert = () => {}, onClose = () => {},
} = {}) {
  if (input.disabled || input.readOnly || input.dataset.formulaHelperOpen === "1") return;
  const doc = input.ownerDocument, win = doc.defaultView;
  ensureFormulaAssistStyles(doc);
  input.dataset.formulaHelperOpen = "1";
  const original = input.value;
  const selection = [input.selectionStart ?? original.length, input.selectionEnd ?? original.length];
  const scope = identityProvider();
  const el = (tag, className, text) => {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const button = (text, action, className = "") => {
    const node = el("button", className, text); node.type = "button";
    node.addEventListener("click", action); return node;
  };

  const dialog = el("dialog", "arFormulaHelper"); dialog.setAttribute("aria-label", "Insert Formula");
  const header = el("header"), title = el("span", "", "Insert Formula");
  const closeButton = button("", () => close(), "arFxClose"); closeButton.setAttribute("aria-label", "Close");
  closeButton.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>';
  header.append(title, closeButton);
  const sidebar = el("div", "arFxSidebar"), search = el("input", "arFxSearch");
  search.placeholder = "Search"; search.setAttribute("aria-label", "Search functions"); search.spellcheck = false;
  const functionList = el("div", "arFxFunctions");
  sidebar.append(search, functionList);
  const main = el("div", "arFxMain"), heading = el("div", "arFxHeading"), form = el("div", "arFxForm");
  const draftRow = el("div", "arFxDraftRow"), draftMark = el("span", "arFxDraftMark", "fx");
  const draft = el("textarea", "arFormulaHelperDraft"); draft.rows = 2; draft.spellcheck = false; draft.setAttribute("aria-label", "Formula");
  draftRow.append(draftMark, draft);
  const preview = el("div", "arFxPreview"); preview.setAttribute("aria-live", "polite");
  main.append(heading, form, draftRow, preview);
  const body = el("div", "arFxBody"); body.append(sidebar, main);
  const footer = el("footer"), status = el("span", "arFxStatus");
  const insert = button("Insert", () => insertFormula(), "arFxAction arFormulaInsert"); insert.disabled = true;
  footer.append(status, button("Cancel", () => close(), "arFxAction"), insert);
  const menu = el("div", "arFxMenu"); menu.hidden = true; menu.setAttribute("role", "listbox");
  menu.addEventListener("pointerdown", event => event.preventDefault());
  dialog.append(header, body, footer, menu);
  doc.body.appendChild(dialog);
  const assists = [installFormulaAutocomplete(draft, { identityProvider, popupParent: dialog })];

  let spec = null, values = [], synced = true, validated = "", generation = 0, request = null, timer = null, menuOwner = null;
  const catalogs = new Map();
  const cached = (key, load) => {
    if (!catalogs.has(key)) catalogs.set(key, Promise.resolve().then(load).catch(error => { catalogs.delete(key); throw error; }));
    return catalogs.get(key);
  };
  const sortNames = names => [...new Set(names)].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
  function valueOf(kind) {
    const index = spec.arguments.findIndex(arg => kindOf(spec, arg) === kind);
    return index < 0 ? "" : String(values[index] || "").trim();
  }
  const projectName = () => valueOf("project") || scope.project_name || "";
  const classPath = () => valueOf("path") || scope.reserving_class || "";

  // ── Function list ───────────────────────────────────────────────────────────
  let visible = [];
  function renderFunctions() {
    const filter = search.value.trim().toLowerCase();
    functionList.replaceChildren(); visible = [];
    for (const group of GROUPS) {
      const items = FORMULA_CATALOG.filter(item => groupOf(item) === group && item.name.toLowerCase().includes(filter));
      if (!items.length) continue;
      functionList.append(el("div", "arFxGroup", group));
      for (const item of items) {
        const option = button(item.name, () => selectFunction(item), "arFxFunction");
        option.setAttribute("aria-pressed", String(item === spec)); option.tabIndex = -1;
        functionList.append(option); visible.push({ item, option });
      }
    }
    if (!visible.length) functionList.append(el("div", "arFxEmpty", "No matching functions"));
    visible.find(entry => entry.item === spec)?.option.scrollIntoView?.({ block: "nearest" });
  }

  function selectFunction(item, nextValues) {
    const carried = nextValues || (synced && spec ? item.arguments.map(arg => {
      const index = spec.arguments.findIndex(old => old.name === arg.name);
      return index < 0 ? "" : values[index] ?? "";
    }) : []);
    spec = item; values = carried; synced = true;
    renderFunctions(); renderForm();
    if (!nextValues) writeDraft();
  }

  // ── Argument form ───────────────────────────────────────────────────────────
  function setValue(index, value) {
    values[index] = value;
    writeDraft();
  }
  function writeDraft() {
    draft.value = buildFormulaCall(spec, values);
    synced = true; form.classList.remove("isDetached"); schedulePreview();
  }
  function row(text, control, id) {
    const label = el("label", "arFxLabel", text); if (id) label.htmlFor = id;
    form.append(label, control);
  }
  function renderForm() {
    menuClose(); assists.splice(1).forEach(item => item.destroy());
    heading.textContent = spec.name;
    form.replaceChildren(); form.classList.toggle("isDetached", !synced);
    const slots = slotsFor(spec, values).map((arg, index) => ({ arg, index, kind: kindOf(spec, arg) }));
    const order = ["project", "path", "dataset", "integer", "expression", "length"];
    for (const kind of order) {
      for (const { arg, index } of slots.filter(slot => slot.kind === kind)) {
        const id = `arFxArg${index}`, value = values[index] ?? "";
        if (kind === "expression" || kind === "integer") {
          const field = el("input", "arFxInput"); field.id = id; field.value = value; field.spellcheck = false;
          field.placeholder = arg.default != null ? String(arg.default) : arg.optional ? "Optional" : ""; field.disabled = !synced;
          if (kind === "integer") field.inputMode = "numeric";
          field.addEventListener("input", () => {
            const grows = isVariadic(spec) && index === slots.length - 1 && field.value.trim();
            setValue(index, field.value);
            if (!grows) return;
            renderForm();
            const next = doc.getElementById(id);
            next?.focus(); next?.setSelectionRange(next.value.length, next.value.length);
          });
          if (kind === "expression") assists.push(installFormulaAutocomplete(field, { identityProvider: () => ({ ...scope }), popupParent: dialog }));
          row(labelOf(arg.name), field, id);
        } else if (kind === "length") {
          row(labelOf(arg.name), combo({ id, value: value || String(arg.default), options: LENGTHS, onPick: next => setValue(index, next) }).wrap, id);
        } else {
          const load = kind === "project"
            ? () => cached("projects", sources.projects).then(sortNames)
            : kind === "path"
              ? () => { const project = projectName(); return cached(`rc\u001f${project}`, () => sources.reservingClasses(project)).then(sortNames); }
              : () => {
                const identity = { project_name: projectName(), reserving_class: classPath() };
                const format = arg.name === "VectorName" ? "Vector" : "Triangle";
                return cached(`ds\u001f${identity.project_name}\u001f${identity.reserving_class}`, () => sources.datasets(identity))
                  .then(list => sortNames(list.filter(item => !item.format || item.format === format).map(item => item.name)));
              };
          const current = kind === "project" ? scope.project_name : kind === "path" ? scope.reserving_class : "";
          row(labelOf(arg.name), combo({
            id, value, editable: true, placeholder: current || "", load,
            onPick: next => setValue(index, current && sameText(next, current) ? "" : next),
          }).wrap, id);
        }
      }
    }
    const flags = slots.filter(slot => slot.kind === "bool");
    if (flags.length) {
      const group = el("div", "arFxFlags");
      for (const { arg, index } of flags) {
        const label = el("label", "arFxFlag"), box = el("input");
        box.type = "checkbox"; box.disabled = !synced;
        box.checked = (values[index] || String(arg.default).toUpperCase()) === "TRUE";
        box.addEventListener("change", () => setValue(index, box.checked ? "TRUE" : "FALSE"));
        label.append(box, labelOf(arg.name)); group.append(label);
      }
      form.append(el("span"), group);
    }
  }

  // ── Dropdowns ───────────────────────────────────────────────────────────────
  function combo({ id, value, options, load, editable = false, placeholder = "", onPick }) {
    const wrap = el("div", "arFxCombo"), field = el("input", "arFxInput"), caret = el("button", "arFxCaret");
    field.id = id; field.spellcheck = false; field.autocomplete = "off"; field.placeholder = placeholder;
    field.readOnly = !editable; field.disabled = !synced;
    field.setAttribute("role", "combobox"); field.setAttribute("aria-expanded", "false");
    field.value = options ? options.find(([key]) => key === value)?.[1] ?? value : value;
    caret.type = "button"; caret.tabIndex = -1; caret.disabled = !synced; caret.setAttribute("aria-label", "Show choices");
    wrap.append(field, caret);
    const handle = { field, items: [], active: -1, token: 0 };
    handle.pick = index => {
      const [key, label] = handle.items[index] || [];
      if (key == null) return;
      field.value = options ? label : key; menuClose(); onPick(key);
    };
    handle.show = async filter => {
      menuOwner = handle; menu.hidden = false; field.setAttribute("aria-expanded", "true");
      const token = ++handle.token;
      if (!options) { menu.replaceChildren(el("div", "arFxMenuStatus", "Loading…")); menuPlace(wrap); }
      let all;
      try { all = options || (await load()).map(name => [name, name]); } catch (error) {
        if (token === handle.token && menuOwner === handle) { menu.replaceChildren(el("div", "arFxMenuStatus isError", error.message || String(error))); menuPlace(wrap); }
        return;
      }
      if (token !== handle.token || menuOwner !== handle) return;
      const words = String(filter || "").toLowerCase().split(/\s+/).filter(Boolean);
      handle.items = all.filter(([, label]) => words.every(word => label.toLowerCase().includes(word)));
      handle.active = handle.items.findIndex(([key, label]) => sameText(options ? key : label, options ? value : field.value));
      if (handle.active < 0 && words.length && handle.items.length) handle.active = 0;
      menuRender(handle); menuPlace(wrap);
    };
    const toggle = () => { if (menuOwner === handle) menuClose(); else void handle.show(""); };
    caret.addEventListener("pointerdown", event => { event.preventDefault(); field.focus(); toggle(); });
    field.addEventListener("click", () => { if (!editable || menuOwner !== handle) toggle(); });
    field.addEventListener("blur", () => { if (menuOwner === handle) menuClose(); });
    // Typing only filters; the text counts once it is picked, entered, or left.
    if (editable) {
      field.addEventListener("input", () => void handle.show(field.value));
      field.addEventListener("change", () => onPick(field.value.trim()));
    }
    field.addEventListener("keydown", event => {
      const open = menuOwner === handle;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!open) { void handle.show(""); return; }
        const count = handle.items.length;
        if (count) { handle.active = (handle.active + (event.key === "ArrowDown" ? 1 : -1) + count) % count; menuRender(handle); }
      } else if (event.key === "Enter" && open) {
        event.preventDefault(); event.stopPropagation();
        if (handle.active >= 0) handle.pick(handle.active); else { menuClose(); if (editable) onPick(field.value.trim()); }
      } else if (event.key === "Escape" && open) {
        event.preventDefault(); event.stopPropagation(); menuClose();
      } else if (!editable && event.key === " ") { event.preventDefault(); toggle(); }
    });
    return { wrap, field };
  }
  function menuRender(handle) {
    menu.replaceChildren();
    handle.items.forEach(([, label], index) => {
      const option = el("div", "arFxMenuItem", label); option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(index === handle.active));
      option.addEventListener("pointerdown", event => { event.preventDefault(); handle.pick(index); });
      menu.append(option);
    });
    if (!handle.items.length) menu.append(el("div", "arFxMenuStatus", "No matches"));
    menu.children[handle.active]?.scrollIntoView?.({ block: "nearest" });
  }
  function menuPlace(anchor) {
    const rect = anchor.getBoundingClientRect(), height = Math.min(menu.scrollHeight || 0, 240);
    const below = win.innerHeight - rect.bottom;
    menu.style.left = `${rect.left}px`; menu.style.width = `${rect.width}px`;
    menu.style.top = `${below < height + 8 && rect.top > below ? rect.top - height - 2 : rect.bottom + 2}px`;
  }
  function menuClose() {
    if (menuOwner) { menuOwner.token++; menuOwner.field.setAttribute("aria-expanded", "false"); }
    menuOwner = null; menu.hidden = true;
  }

  // ── Formula text and preview ────────────────────────────────────────────────
  function readDraft() {
    const call = splitFormulaCall(draft.value);
    const item = call && FORMULA_CATALOG.find(entry => sameText(entry.name, call.name));
    const parsed = item && valuesFromParts(item, call.parts);
    if (parsed) {
      if (item !== spec) { spec = item; renderFunctions(); }
      values = parsed; synced = true; renderForm();
    } else if (synced) { synced = false; renderForm(); }
    schedulePreview();
  }
  function complete() {
    return slotsFor(spec, values).every((arg, i) => {
      const kind = kindOf(spec, arg);
      const required = kind === "dataset" || (!arg.optional && ["integer", "expression"].includes(kind));
      return !required || String(values[i] ?? "").trim();
    });
  }
  function setStatus(text, error = false) { status.textContent = text; status.classList.toggle("isError", error); }
  function schedulePreview() {
    generation++; request?.abort(); clearTimeout(timer); validated = ""; insert.disabled = true;
    preview.classList.add("isStale");
    if (synced && !complete()) { preview.replaceChildren(); setStatus(""); return; }
    const ticket = generation, formula = draft.value;
    timer = setTimeout(() => void runPreview(ticket, formula), previewDelay);
  }
  async function runPreview(ticket, formula) {
    request = new AbortController();
    setStatus("Calculating…");
    try {
      const result = await evaluate(formula, { identity: identityProvider(), signal: request.signal });
      if (ticket !== generation || !dialog.isConnected) return;
      if (!result?.ok) throw new Error(result?.error || "Formula could not be evaluated.");
      renderPreview(result);
      setStatus(`${result.rows} row${result.rows === 1 ? "" : "s"} × ${result.cols} column${result.cols === 1 ? "" : "s"}`);
      validated = formula; insert.disabled = false;
    } catch (error) {
      if (ticket !== generation || error?.name === "AbortError") return;
      preview.replaceChildren(); preview.classList.remove("isStale"); setStatus(error.message || String(error), true);
    }
  }
  function renderPreview(result) {
    const table = el("table"), head = el("tr");
    const cols = Math.min(result.cols, PREVIEW_COLS);
    head.append(el("th"));
    for (let c = 0; c < cols; c++) head.append(el("th", "", String(c + 1)));
    table.append(head);
    result.values.slice(0, PREVIEW_ROWS).forEach((line, r) => {
      const tr = el("tr"); tr.append(el("th", "", String(r + 1)));
      line.slice(0, cols).forEach(value => tr.append(el("td", "", value == null || value === "" ? "" : Number.isFinite(Number(value)) ? Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 }) : String(value))));
      table.append(tr);
    });
    preview.replaceChildren(table); preview.classList.remove("isStale");
  }

  function close(value) {
    generation++; request?.abort(); clearTimeout(timer); menuClose();
    assists.forEach(item => item.destroy()); dialog.close(); dialog.remove();
    if (value != null) input.value = value;
    input.focus({ preventScroll: true });
    delete input.dataset.formulaHelperOpen;
    if (value != null) { input.setSelectionRange(value.length, value.length); input.dispatchEvent(new Event("input", { bubbles: true })); onInsert(value); }
    onClose();
  }
  function insertFormula() {
    if (validated !== draft.value || insert.disabled) return;
    const formulaBody = draft.value.replace(/^\s*=\s*/, "");
    const hasSelection = selection[0] !== selection[1];
    const value = hasSelection && original.trimStart().startsWith("=")
      ? original.slice(0, Math.max(original.indexOf("=") + 1, selection[0])) + formulaBody + original.slice(selection[1])
      : `=${formulaBody}`;
    close(value);
  }

  draft.addEventListener("input", readDraft);
  search.addEventListener("input", () => { renderFunctions(); if (visible.length && !visible.some(entry => entry.item === spec)) selectFunction(visible[0].item); });
  search.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const at = visible.findIndex(entry => entry.item === spec), step = event.key === "ArrowDown" ? 1 : -1;
      const next = visible[(at + step + visible.length) % visible.length];
      if (next) selectFunction(next.item);
    } else if (event.key === "Enter") {
      event.preventDefault();
      form.querySelector("input:not(:disabled)")?.focus();
    }
  });
  dialog.addEventListener("keydown", event => {
    if (event.key !== "Enter" || event.defaultPrevented) return;
    const inField = event.target?.tagName === "INPUT" && event.target !== search && event.target.type !== "checkbox";
    if (event.ctrlKey || event.metaKey || inField) { event.preventDefault(); insertFormula(); }
  });
  dialog.addEventListener("cancel", event => { event.preventDefault(); if (menuOwner) menuClose(); else close(); });

  const source = selection[0] !== selection[1] ? original.slice(selection[0], selection[1]) : original;
  const call = splitFormulaCall(source);
  const start = call && FORMULA_CATALOG.find(entry => sameText(entry.name, call.name));
  const startValues = start && valuesFromParts(start, call.parts);
  if (startValues) { selectFunction(start, startValues); draft.value = source.trim().replace(/^=?\s*/, "="); schedulePreview(); }
  else {
    selectFunction(FORMULA_CATALOG.find(item => groupOf(item) === GROUPS[0]) || FORMULA_CATALOG[0]);
    // A larger formula opens as it stands; choosing a function starts over.
    if (/^\s*=\s*\S/.test(source)) { draft.value = source.trim(); readDraft(); }
  }
  dialog.showModal(); search.focus();
  return { close };
}

/** Click opens the helper; moving the pointer keeps the existing fx drag gesture. */
export function wireFormulaHelper(button, input, options = {}) {
  button.setAttribute("role", "button"); button.setAttribute("tabindex", "0"); button.setAttribute("aria-label", "Insert formula");
  button.removeAttribute("aria-hidden"); button.removeAttribute("title");
  let start = null, dragged = false;
  const open = () => { if (input.disabled || input.readOnly) return; options.onOpen?.(); openFormulaHelper(input, options); };
  button.addEventListener("pointerdown", event => { start = { x: event.clientX, y: event.clientY }; dragged = false; event.preventDefault(); });
  button.addEventListener("pointermove", event => { if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 3) dragged = true; });
  button.addEventListener("click", () => { if (!dragged) open(); start = null; });
  button.addEventListener("keydown", event => {
    if (["Enter", " "].includes(event.key)) { event.preventDefault(); open(); }
  });
}
