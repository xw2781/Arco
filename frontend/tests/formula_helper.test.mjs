import "./ui_module_loader.mjs";
import assert from "node:assert/strict";
import test from "node:test";
import { openFormulaHelper, splitFormulaCall } from "../ui/shared/components/formula_bar/formula_helper.js";

// DOM lifecycle fixture; geometry and painting require a browser check.
class Element extends EventTarget {
  constructor(tag, doc) {
    super(); Object.assign(this, {tagName: tag.toUpperCase(), ownerDocument: doc, children: [], attributes: {}, dataset: {}, style: {}, value: "", className: "", selectionStart: 0, selectionEnd: 0});
    const names = () => this.className.split(" ").filter(Boolean);
    this.classList = {
      add: name => { if (!names().includes(name)) this.className = [...names(), name].join(" "); },
      remove: name => { this.className = names().filter(item => item !== name).join(" "); },
      toggle: (name, on) => { (on ?? !names().includes(name)) ? this.classList.add(name) : this.classList.remove(name); },
      contains: name => names().includes(name),
    };
  }
  append(...nodes) { for (let node of nodes) { if (typeof node === "string") { const text = new Element("text", this.ownerDocument); text.textContent = node; node = text; } node.remove(); node.parent = this; this.children.push(node); } }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) { this.children.forEach(node => { node.parent = null; }); this.children = []; this._text = ""; this.append(...nodes); }
  set textContent(value) { this.replaceChildren(); this._text = value; }
  get textContent() { return (this._text || "") + this.children.map(node => node.textContent).join(""); }
  setAttribute(key, value) { this.attributes[key] = value; }
  getAttribute(key) { return this.attributes[key]; }
  removeAttribute(key) { delete this.attributes[key]; }
  focus() { const doc = this.ownerDocument; if (doc.activeElement === this) return; doc.activeElement?.dispatchEvent(new Event("blur")); doc.activeElement = this; this.dispatchEvent(new Event("focus")); }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; }
  get isConnected() { return !!this.parent || this === this.ownerDocument.body; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  getBoundingClientRect() { return {left: 10, top: 10, right: 310, bottom: 40, width: 300, height: 30}; }
  scrollIntoView() {}
}
const walk = node => [node, ...node.children.flatMap(walk)];
const settle = () => new Promise(resolve => setTimeout(resolve, 5));

function fixture({ value = "", ...options } = {}) {
  const doc = { activeElement: null, defaultView: Object.assign(new EventTarget(), {innerWidth: 1000, innerHeight: 700}) };
  doc.createElement = tag => new Element(tag, doc);
  doc.body = doc.createElement("body"); doc.head = doc.createElement("head");
  doc.getElementById = id => [...walk(doc.body), ...walk(doc.head)].find(node => node.id === id);
  const input = doc.createElement("input"); input.value = value; doc.body.append(input); input.focus();
  const evaluated = [];
  let inserts = 0;
  const helper = openFormulaHelper(input, {
    identityProvider: () => ({project_name: "Current", reserving_class: "Current\\RC"}),
    sources: {
      projects: async () => ["Current", "Other"],
      reservingClasses: async () => ["Current\\RC", "Other\\RC"],
      datasets: async () => [{name: "Paid Claims", format: "Triangle"}, {name: "Premium", format: "Vector"}],
    },
    evaluate: async formula => { evaluated.push(formula); return {ok: true, rows: 1, cols: 2, values: [[1, 2]]}; },
    previewDelay: 0, onInsert: () => inserts++, ...options,
  });
  const nodes = () => walk(doc.body);
  const button = text => nodes().find(node => node.tagName === "BUTTON" && node.textContent === text);
  const click = text => { const node = button(text); assert.ok(node, text); if (!node.disabled) node.dispatchEvent(new Event("click")); };
  const field = label => {
    const node = nodes().find(item => item.tagName === "LABEL" && item.className === "arFxLabel" && item.textContent === label);
    assert.ok(node, label); return doc.getElementById(node.htmlFor);
  };
  const flag = label => nodes().find(node => node.className === "arFxFlag" && node.textContent === label).children[0];
  const edit = (node, text) => { node.value = text; node.dispatchEvent(new Event("input")); node.dispatchEvent(new Event("change")); };
  const draft = () => nodes().find(node => node.attributes["aria-label"] === "Formula");
  const labels = () => nodes().filter(node => node.className === "arFxLabel").map(node => node.textContent);
  return {doc, input, helper, nodes, button, click, field, flag, edit, draft, labels, evaluated, inserts: () => inserts};
}

test("an Arco call is built from plain fields, previewed live, and inserted", async () => {
  const f = fixture({value: "5007.8"});
  assert.equal(f.button("ArcoTri").attributes["aria-pressed"], "true");
  assert.deepEqual(f.labels(), ["Project", "Reserving Class", "Triangle", "Origin Length", "Development Length"]);
  assert.equal(f.field("Project").placeholder, "Current");
  assert.equal(f.evaluated.length, 0, "no preview before the dataset is chosen");
  assert.equal(f.button("Insert").disabled, true);

  f.edit(f.field("Triangle"), "Paid Claims"); await settle();
  assert.equal(f.draft().value, '=ArcoTri(, "Paid Claims")');
  assert.deepEqual(f.evaluated, ['=ArcoTri(, "Paid Claims")']);
  assert.equal(f.input.value, "5007.8", "a preview never applies");

  f.click("Insert");
  assert.equal(f.input.value, '=ArcoTri(, "Paid Claims")'); assert.equal(f.inserts(), 1);
  assert.equal(f.input.dataset.formulaHelperOpen, undefined); assert.equal(f.doc.activeElement, f.input);
});

test("options and other scopes write only the arguments that differ from the defaults", async () => {
  const f = fixture();
  f.edit(f.field("Triangle"), "Paid Claims");
  f.flag("Transposed").checked = true; f.flag("Transposed").dispatchEvent(new Event("change"));
  f.edit(f.field("Project"), "Other");
  assert.equal(f.draft().value, '=ArcoTri(, "Paid Claims", , TRUE, , "Other")');
  f.edit(f.field("Project"), "current");
  assert.equal(f.draft().value, '=ArcoTri(, "Paid Claims", , TRUE)', "the current project stays implicit");
  f.flag("Cumulative").checked = false; f.flag("Cumulative").dispatchEvent(new Event("change"));
  assert.equal(f.draft().value, '=ArcoTri(, "Paid Claims", FALSE, TRUE)');
  f.click("ArcoTriCell");
  assert.equal(f.field("Triangle").value, "Paid Claims", "shared arguments carry over");
  assert.ok(f.labels().includes("Origin Period"));
});

test("editing the formula text drives the fields until it stops being one call", async () => {
  const f = fixture();
  f.edit(f.draft(), "=TAKE({1,2;3,4}, -1)"); await settle();
  assert.equal(f.button("TAKE").attributes["aria-pressed"], "true");
  assert.equal(f.field("Array").value, "{1,2;3,4}"); assert.equal(f.field("Rows").value, "-1");
  assert.equal(f.button("Insert").disabled, false);
  f.edit(f.draft(), "=1+TAKE({1,2;3,4}, -1)"); await settle();
  assert.equal(f.field("Array").disabled, true, "fields cannot show a larger expression");
  assert.deepEqual(f.evaluated.at(-1), "=1+TAKE({1,2;3,4}, -1)");
  f.click("Insert");
  assert.equal(f.input.value, "=1+TAKE({1,2;3,4}, -1)");
});

test("changing a draft cancels its preview and prevents stale insertion", async () => {
  let finish, signal;
  const f = fixture({value: "=SUM(1,2)", evaluate: (_raw, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); }});
  f.edit(f.draft(), "=SUM(1,2)"); await settle();
  f.edit(f.draft(), "=SUM(8,9)"); assert.equal(signal.aborted, true);
  finish({ok: true, rows: 1, cols: 1, values: [[3]]}); await settle();
  f.click("Insert");
  assert.equal(f.inserts(), 0); assert.equal(f.input.value, "=SUM(1,2)");
  f.click("Cancel"); assert.equal(f.input.value, "=SUM(1,2)"); assert.equal(f.doc.activeElement, f.input);
});

test("preview errors show in the status line and keep Insert disabled", async () => {
  const f = fixture({evaluate: async () => ({ok: false, error: "Dataset not found."})});
  f.edit(f.field("Triangle"), "Missing"); await settle();
  const status = f.nodes().find(node => node.className.startsWith("arFxStatus"));
  assert.equal(status.textContent, "Dataset not found."); assert.ok(status.classList.contains("isError"));
  assert.equal(f.button("Insert").disabled, true);
});

test("an existing call opens with its function and fields filled", () => {
  const f = fixture({value: '=ArcoVec("Other\\RC", "Premium", , "Other", 3)'});
  assert.equal(f.button("ArcoVec").attributes["aria-pressed"], "true");
  assert.equal(f.field("Reserving Class").value, "Other\\RC");
  assert.equal(f.field("Vector").value, "Premium");
  assert.equal(f.field("Project").value, "Other");
  assert.equal(f.field("Period Length").value, "Quarterly");
  assert.equal(f.draft().value, '=ArcoVec("Other\\RC", "Premium", , "Other", 3)');
});

test("a larger formula opens as it stands, with its preview", async () => {
  const f = fixture({value: '=ArcoVec("", "Premium")/1000'});
  assert.equal(f.draft().value, '=ArcoVec("", "Premium")/1000');
  assert.equal(f.field("Triangle").disabled, true);
  await settle();
  assert.deepEqual(f.evaluated, ['=ArcoVec("", "Premium")/1000']);
  f.click("SUM");
  assert.equal(f.draft().value, "=SUM()", "choosing a function starts over");
});

test("typing in a dropdown filters it; the text counts once it is committed", async () => {
  const f = fixture();
  const triangle = f.field("Triangle");
  triangle.value = "paid"; triangle.dispatchEvent(new Event("input")); await settle();
  assert.equal(f.draft().value, "=ArcoTri()");
  const options = f.nodes().filter(node => node.className === "arFxMenuItem").map(node => node.textContent);
  assert.deepEqual(options, ["Paid Claims"], "only triangles that match every word");
  triangle.dispatchEvent(Object.assign(new Event("keydown"), {key: "Enter"}));
  assert.equal(f.draft().value, '=ArcoTri(, "Paid Claims")');
});

test("a list function grows one argument at a time", () => {
  const f = fixture({value: "=SUM()"});
  assert.deepEqual(f.labels(), ["Number 1", "Number 2"]);
  f.edit(f.field("Number 1"), "1"); f.edit(f.field("Number 2"), "2");
  assert.deepEqual(f.labels(), ["Number 1", "Number 2", "Number 3"]);
  assert.equal(f.draft().value, "=SUM(1, 2)");
});

test("splitFormulaCall keeps nested and quoted commas inside one argument", () => {
  assert.deepEqual(splitFormulaCall('=IF(SUM(1,2)>2, "a,b", {1,2})'), {name: "IF", parts: ["SUM(1,2)>2", '"a,b"', "{1,2}"]});
  assert.equal(splitFormulaCall("=SUM(1)+1"), null);
  assert.deepEqual(splitFormulaCall("=SUM()"), {name: "SUM", parts: []});
});
