import { FORMULA_CATALOG, formulaCompletionQuery, formulaCompletionIdentity, completionEdit, quoteFormulaText } from "/ui/shared/components/formula_bar/formula_completion.js?v=20260917a";
import { formulaDatasetNames, formulaContextOptions, formulaPageIdentity } from "/ui/shared/components/formula_bar/formula_api.js?v=20260917a";

let sequence = 0;
const controllers = new WeakMap();

export function ensureFormulaAssistStyles(doc = document) {
  if (doc.getElementById("arFormulaAssistStyle")) return;
  const link = doc.createElement("link");
  link.id = "arFormulaAssistStyle"; link.rel = "stylesheet";
  link.href = "/ui/shared/components/formula_bar/formula_assist.css?v=20260917a";
  doc.head.appendChild(link);
}

export function installFormulaAutocomplete(input, { identityProvider = formulaPageIdentity, datasetProvider = formulaDatasetNames, popupParent } = {}) {
  if (!input || controllers.has(input)) return controllers.get(input);
  const doc = input.ownerDocument, win = doc.defaultView;
  ensureFormulaAssistStyles(doc);
  const controller = new AbortController(), { signal } = controller;
  const popup = doc.createElement("div");
  popup.id = `arFormulaAutocomplete${++sequence}`; popup.className = "arFormulaAutocomplete"; popup.hidden = true;
  const hint = doc.createElement("div"); hint.className = "arFormulaArgumentHint"; hint.id = `${popup.id}Hint`;
  const list = doc.createElement("div"); list.className = "arFormulaSuggestions"; list.id = `${popup.id}List`;
  list.setAttribute("role", "listbox"); list.setAttribute("aria-label", "Formula suggestions");
  popup.append(hint, list); (popupParent || doc.body).appendChild(popup);
  let query = null, options = [], selected = 0, generation = 0;
  const catalogs = new Map();
  input.setAttribute("role", "combobox"); input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", list.id); input.setAttribute("aria-expanded", "false");

  function close() {
    generation++; popup.hidden = true;
    input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant");
  }
  function position() {
    const rect = input.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 320), win.innerWidth - 16);
    popup.style.width = `${width}px`;
    popup.style.left = `${Math.max(8, Math.min(rect.left, win.innerWidth - width - 8))}px`;
    const height = Math.min(popup.scrollHeight, 300);
    const below = win.innerHeight - rect.bottom;
    popup.style.top = `${below < height + 8 && rect.top > below ? Math.max(8, rect.top - height - 4) : Math.min(rect.bottom + 4, win.innerHeight - height - 8)}px`;
  }
  function choose(index) {
    if (!options[index] || !query) return;
    const edit = completionEdit(input.value, query, options[index].value);
    input.value = edit.value; input.setSelectionRange(edit.caret, edit.caret);
    close(); input.focus({ preventScroll: true });
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function render(status = "") {
    list.replaceChildren();
    options.forEach((item, index) => {
      const option = doc.createElement("div"); option.className = "arFormulaSuggestion";
      option.id = `${list.id}-${index}`; option.setAttribute("role", "option");
      option.setAttribute("aria-selected", String(index === selected)); option.textContent = item.label;
      option.addEventListener("pointerdown", event => { event.preventDefault(); event.stopPropagation(); choose(index); });
      list.appendChild(option);
    });
    if (status) { const el = doc.createElement("div"); el.className = "arFormulaSuggestionStatus"; el.textContent = status; list.appendChild(el); }
    if (options[selected]) {
      input.setAttribute("aria-activedescendant", `${list.id}-${selected}`);
      list.children[selected]?.scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
    position();
  }
  async function refresh() {
    const next = formulaCompletionQuery(input.value, input.selectionStart);
    if (!next || doc.activeElement !== input || input.disabled || input.readOnly) { close(); return; }
    const request = ++generation;
    query = next; selected = 0; options = [];
    popup.hidden = false; input.setAttribute("aria-expanded", "true");
    hint.replaceChildren();
    const call = query.spec ? query : query.call;
    if (call) {
      hint.append(`${call.spec.name}(`);
      call.spec.arguments.forEach((arg, i) => {
        if (i) hint.append(", ");
        const label = doc.createElement(i === Math.min(call.argument, call.spec.arguments.length - 1) ? "strong" : "span");
        label.textContent = arg.optional ? `[${arg.name}]` : arg.name; hint.append(label);
      });
      hint.append(")");
    } else hint.textContent = query.kind === "function" ? "Choose a function · Tab or Enter to insert" : "";
    hint.hidden = !hint.textContent;
    const filter = query.query?.replace(/^"|"$/g, "").replaceAll('""', '"').toLowerCase() || "";
    if (query.kind === "function") {
      options = FORMULA_CATALOG.filter(item => item.name.toLowerCase().startsWith(filter))
        .map(item => ({ label: `${item.name}(${item.arguments.map(arg => arg.optional ? `[${arg.name}]` : arg.name).join(", ")})`, value: `${item.name}(` }));
    } else if (query.kind === "boolean") {
      options = ["TRUE", "FALSE"].filter(value => value.toLowerCase().startsWith(filter)).map(value => ({ label: value, value }));
    } else if (query.kind === "contextArgument") {
      render("Loading choices…");
      try {
        const choices = await formulaContextOptions(query.spec.arguments[query.argument].name, formulaCompletionIdentity(input.value, query, identityProvider()));
        if (request !== generation || doc.activeElement !== input) return;
        options = choices.filter(item => !item.value || item.value.toLowerCase().includes(filter)).map(item => ({ label: item.label, value: quoteFormulaText(item.value) }));
      } catch (error) { if (request === generation) render(error.message); return; }
    } else if (["dataset", "datasetArgument"].includes(query.kind)) {
      const identity = formulaCompletionIdentity(input.value, query, identityProvider());
      const key = JSON.stringify(identity);
      render("Loading datasets…");
      try {
        if (!catalogs.has(key)) catalogs.set(key, Promise.resolve(datasetProvider(identity, signal)).catch(error => { catalogs.delete(key); throw error; }));
        const names = await catalogs.get(key);
        if (request !== generation || doc.activeElement !== input) return;
        options = [...new Set(names)].filter(name => name.toLowerCase().includes(filter)).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
          .slice(0, 50).map(name => ({ label: name, value: query.kind === "dataset" ? `[${name}][` : quoteFormulaText(name) }));
      } catch (error) {
        if (request === generation) render(error.message || "Dataset list could not be loaded.");
        return;
      }
    }
    render(!options.length && query.kind.startsWith("dataset") ? "No matching datasets." : "");
  }
  input.addEventListener("input", refresh, { signal });
  input.addEventListener("click", refresh, { signal });
  input.addEventListener("focus", () => { catalogs.clear(); void refresh(); }, { signal });
  input.addEventListener("keyup", event => { if (!["Enter", "Tab", "Escape", "ArrowUp", "ArrowDown"].includes(event.key)) void refresh(); }, { signal });
  input.addEventListener("blur", close, { signal });
  input.addEventListener("keydown", event => {
    if (popup.hidden) return;
    if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); }
    else if (["Enter", "Tab"].includes(event.key) && options[selected]) {
      event.preventDefault(); event.stopImmediatePropagation(); choose(selected);
    } else if (["ArrowDown", "ArrowUp"].includes(event.key) && options.length) {
      event.preventDefault(); event.stopImmediatePropagation();
      selected = (selected + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length; render();
    }
  }, { capture: true, signal });
  const reposition = () => { if (!popup.hidden) position(); };
  win.addEventListener("resize", reposition, { signal }); win.addEventListener("scroll", reposition, { capture: true, signal });
  const handle = { close, destroy() { close(); controller.abort(); popup.remove(); controllers.delete(input); } };
  controllers.set(input, handle); return handle;
}
