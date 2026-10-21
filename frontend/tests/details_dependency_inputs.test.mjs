import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const { createDetailsDependenciesController } = await import("../ui/shared/tabs/details/details_dependencies.js");

// Just enough of a DOM for the map to build its boxes. Nothing is laid out, so
// the arrows are never measured; the tests read the boxes the map appends.
class FakeElement {
  constructor(doc, tagName) {
    this.ownerDocument = doc;
    this.tagName = tagName;
    this.children = [];
    this.parent = null;
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.listeners = {};
    this.text = "";
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
      toggle: (name, on = !classes.has(name)) => (on ? classes.add(name) : classes.delete(name), on),
    };
    this.classes = classes;
  }

  set className(value) {
    this.classes.clear();
    String(value).split(/\s+/u).filter(Boolean).forEach((name) => this.classes.add(name));
  }

  get className() { return [...this.classes].join(" "); }

  set textContent(value) {
    this.children = [];
    this.text = String(value);
  }

  get textContent() { return this.text + this.children.map((child) => child.textContent).join(""); }

  append(...nodes) {
    for (const node of nodes) {
      node.parent = this;
      this.children.push(node);
    }
  }

  appendChild(node) {
    this.append(node);
    return node;
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
  }

  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  get firstElementChild() { return this.children[0] || null; }
  get childElementCount() { return this.children.length; }

  fire(type) {
    const event = { target: this, key: "", stopPropagation() {}, preventDefault() {} };
    for (const handler of this.listeners[type] || []) handler(event);
  }
}

function fakeDocument() {
  const doc = {
    createElement: (tag) => new FakeElement(doc, tag),
    createElementNS: (_ns, tag) => new FakeElement(doc, tag),
    getElementById: () => null,
  };
  return doc;
}

function mountController() {
  const doc = fakeDocument();
  const container = new FakeElement(doc, "div");
  const controller = createDetailsDependenciesController({
    dependencyMap: container,
    getIdentity: () => ({ datasetName: "C 41 - BF" }),
    getSelfMethodType: () => "Bornhuetter Ferguson",
    documentRef: doc,
    windowRef: {},
  });
  // header, then the scroll box holding the stage: [arrows, in, self, out].
  const precedentBoxes = () => container.children[1].children[0].children[1].children;
  return { controller, precedentBoxes };
}

const describe = (box) => ({
  name: box.children[0].textContent,
  label: box.children[1]?.classList.contains("arDetailsDepNodeKind") ? box.children[1].textContent : "",
  placeholder: box.classList.contains("is-placeholder"),
  actions: box.children.find((child) => child.classList.contains("arDetailsDepNodeActions"))
    ?.children.map((button) => button.attributes["aria-label"]) || [],
});

function bfSlots({ latest = "", dfm = "", priors = [], disabled = false, calls = [] } = {}) {
  const pick = (key) => (anchor, options) => calls.push(["pick", key, anchor, options]);
  return [
    { key: "latest", label: "Latest", values: [latest].filter(Boolean), disabled, pick: pick("latest") },
    { key: "dfm", label: "Development Pattern", values: [dfm].filter(Boolean), disabled, pick: pick("dfm") },
    {
      key: "prior",
      label: "Prior Vector",
      multiple: true,
      max: 2,
      values: priors,
      disabled,
      pick: pick("prior"),
      remove: (index) => calls.push(["remove", "prior", index]),
    },
  ];
}

test("each input is a box labelled with its role, with Choose and Add boxes for what is missing", () => {
  const { controller, precedentBoxes } = mountController();
  controller.setInputs(bfSlots({ latest: "Claims ex CWOP", priors: ["Prior A"] }));

  assert.deepEqual(precedentBoxes().map(describe), [
    { name: "Claims ex CWOP", label: "Latest", placeholder: false, actions: ["Change Latest"] },
    { name: "Choose Development Pattern", label: "", placeholder: true, actions: [] },
    { name: "Prior A", label: "Prior Vector", placeholder: false, actions: ["Remove Prior A"] },
    { name: "+ Add Prior Vector", label: "", placeholder: true, actions: [] },
  ]);
});

test("a list input stops offering Add at its limit", () => {
  const { controller, precedentBoxes } = mountController();
  controller.setInputs(bfSlots({ latest: "L", dfm: "D", priors: ["Prior A", "Prior B"] }));

  assert.deepEqual(precedentBoxes().map((box) => box.children[0].textContent), ["L", "D", "Prior A", "Prior B"]);
});

test("the map's buttons and empty boxes hand the page its picker anchored to the box", () => {
  const calls = [];
  const { controller, precedentBoxes } = mountController();
  controller.setInputs(bfSlots({ latest: "L", priors: ["Prior A"], calls }));
  const [latest, choose, prior, add] = precedentBoxes();

  latest.children[2].children[0].fire("click");
  choose.fire("click");
  prior.children[2].children[0].fire("click");
  add.fire("click");

  assert.deepEqual(calls, [
    ["pick", "latest", latest, { index: 0 }],
    ["pick", "dfm", choose, { index: null }],
    ["remove", "prior", 0],
    ["pick", "prior", add, { index: null }],
  ]);
});

test("a disabled input shows its value but offers no way to change it", () => {
  const { controller, precedentBoxes } = mountController();
  controller.setInputs(bfSlots({ latest: "L", priors: ["Prior A"], disabled: true }));
  const boxes = precedentBoxes();

  assert.deepEqual(boxes.map((box) => describe(box).actions), [[], [], [], []]);
  assert.equal(boxes[1].attributes["aria-disabled"], "true");
  assert.equal(boxes[1].attributes.role, undefined);
});

test("saved precedents dress the inputs, others follow them, and a replaced input leaves no stale box", () => {
  const { controller, precedentBoxes } = mountController();
  controller.setInputs(bfSlots({ latest: "L", dfm: "C 42 DFM" }));
  controller.apply({
    precedents: [
      { dataset_name: "L" },
      { dataset_name: "C 42 DFM", method_type: "DFM" },
      { dataset_name: "Target Ultimate" },
    ],
  });

  assert.deepEqual(precedentBoxes().map((box) => [box.children[0].textContent, box.dataset.family]), [
    ["L", "dataset"],
    ["C 42 DFM", "method"],
    ["+ Add Prior Vector", undefined],
    ["Target Ultimate", "dataset"],
  ]);

  // The graph is the saved one; until a save rewrites it, the old Latest must
  // not stand beside the new one.
  controller.setInputs(bfSlots({ latest: "L2", dfm: "C 42 DFM" }));
  assert.deepEqual(precedentBoxes().map((box) => box.children[0].textContent), [
    "L2",
    "C 42 DFM",
    "+ Add Prior Vector",
    "Target Ultimate",
  ]);
});

// [page script, the slot labels it hands the map]. Stochastic Consolidation
// has no dataset input to choose, so it keeps the read-only map.
const INPUT_HOSTS = [
  ["../ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson_main.js", ["Latest", "Development Pattern", "Prior Vector"]],
  ["../ui/method_pages/cape_cod/cape_cod_main.js", ["Latest", "Exposure", "Prior Ultimate"]],
  ["../ui/method_pages/bootstrap/bootstrap_main.js", ["DFM"]],
  ["../ui/method_pages/dfm/dfm_details_dependencies.js", ["Input Triangle"]],
  ["../ui/method_pages/result_selection/result_selection_ui.js", ["Ratio Basis"]],
];

test("every method page with dataset inputs chooses them on the Data Flow map", async () => {
  for (const [scriptPath, labels] of INPUT_HOSTS) {
    const source = await readFile(new URL(scriptPath, import.meta.url), "utf8");
    assert.match(source, /setInputs|setDetailsInputs/u, scriptPath);
    for (const label of labels) assert.match(source, new RegExp(`"${label}"`, "u"), `${scriptPath}: ${label}`);
  }
  // Berquist-Sherman hands over its variant's role definitions.
  const bs = await readFile(new URL("../ui/method_pages/berquist_sherman/berquist_sherman_main.js", import.meta.url), "utf8");
  assert.match(bs, /setInputs\(roleDefinitions\(\)\.map\(/u);

  // No page keeps a separate picker field for an input the map now owns.
  const pages = ["bornhuetter_ferguson/bornhuetter_ferguson", "cape_cod/cape_cod", "bootstrap/bootstrap", "dfm/dfm", "result_selection/result_selection", "berquist_sherman/berquist_sherman"];
  for (const page of pages) {
    const markup = await readFile(new URL(`../ui/method_pages/${page}.html`, import.meta.url), "utf8");
    assert.doesNotMatch(markup, /id="(?:bfLatestBtn|bfDfmBtn|bfPriorList|ccLatestBtn|ccExposureBtn|ccPriorUltimateBtn|bstDfmBtn|dfmTriTypeBtn|rsRatioBasisAddBtn)"|data-picker-role=/u, page);
  }
});
