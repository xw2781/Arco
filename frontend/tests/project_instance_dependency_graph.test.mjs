import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stubUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const tooltipStubUrl = stubUrl("export function attachArcrhoTooltip() {}");
const contextMenuStubUrl = stubUrl("export function openContextMenu() {}");

const layoutUrl = new URL("../ui/project_instance/dependency_graph_layout.js", import.meta.url).href;
const {
  buildDependencyGraph,
  dependencyGraphIsolatedKeys,
  dependencyGraphReach,
  dependencyNodeKind,
  layoutDependencyGraph,
  pruneDependencyGraph,
} = await import(layoutUrl);

// The page module reads the DOM and starts a load as soon as it is imported;
// only its exported pure helpers are exercised here.
const rawWindowSource = (await readFile(
  new URL("../ui/project_instance/dependency_graph_window.js", import.meta.url),
  "utf8",
)).replaceAll("\r\n", "\n");
const windowModule = await import(stubUrl(
  rawWindowSource
    .replace(/"\/ui\/shared\/components\/context_menu\/context_menu\.js\?v=\d{8}[a-z]"/, JSON.stringify(contextMenuStubUrl))
    .replace(/"\/ui\/shared\/components\/tooltip\/tooltip\.js\?v=\d{8}[a-z]"/, JSON.stringify(tooltipStubUrl))
    .replace(/"\/ui\/project_instance\/dependency_graph_layout\.js\?v=\d{8}[a-z]"/, JSON.stringify(layoutUrl))
    .replace(/^import "\/ui\/shared\/integrations\/zoom_bridge\.js[^"]*";$/m, "")
    .replace(/"\/ui\/([^"]+)"/g, (_, path) => JSON.stringify(new URL(`../ui/${path}`, import.meta.url).href))
    .replace(/^const params = new URLSearchParams[\s\S]*$/m, ""),
));
const {
  dependencyGraphFitScale,
  dependencyGraphOpenRequest,
  dependencyGraphPortList,
  dependencyGraphScrollTo,
  dependencyGraphSummary,
  dependencyGraphViewport,
} = windowModule;

const read = async (path) => (await readFile(new URL(path, import.meta.url), "utf8")).replaceAll("\r\n", "\n");

const PAYLOAD = {
  ok: true,
  nodes: [
    { name: "Paid", dataset_type: "Paid", source_kind: "input", method_type: "None", status: 0 },
    { name: "Incurred", dataset_type: "Incurred", source_kind: "input", method_type: "None", status: 0 },
    { name: "Paid Vector", dataset_type: "Paid Vector", source_kind: "calculated", method_type: "None", formula: "Paid / 2", status: 0 },
    { name: "Paid DFM", dataset_type: "Paid Ultimate", source_kind: "dfm", method_type: "DFM", method_name: "Paid DFM Method", status: 2 },
    { name: "Incurred DFM", dataset_type: "Incurred Ultimate", source_kind: "dfm", method_type: "DFM", status: 0 },
    { name: "Selected Ultimate", dataset_type: "Selected Ultimate", source_kind: "result_selection", method_type: "Result Selection", status: 0 },
    { name: "Gone Vector", dataset_type: "Gone Vector", source_kind: "", method_type: "None", status: 0, in_index: false },
  ],
  edges: [
    { source: "Paid", target: "Paid Vector" },
    { source: "Paid Vector", target: "Paid DFM" },
    { source: "Incurred", target: "Incurred DFM" },
    { source: "Paid DFM", target: "Selected Ultimate" },
    { source: "Incurred DFM", target: "Selected Ultimate" },
    { source: "Gone Vector", target: "Incurred DFM" },
    { source: "Paid", target: "Gone Vector" },
    { source: "paid", target: "PAID VECTOR" },
    { source: "Paid", target: "Nobody" },
    { source: "Paid", target: "Paid" },
  ],
};

// The fake project's generated-formula chain: two Engine-built inputs, each
// one source column, feeding a type the Engine evaluates as a formula over
// them, which three methods read.
const GENERATED_PAYLOAD = {
  ok: true,
  nodes: [
    { name: "Earned Premium", dataset_type: "Earned Premium", source_kind: "engine", method_type: "None", formula: "", status: 0 },
    { name: "Remaining Budget Premium", dataset_type: "Remaining Budget Premium", source_kind: "engine", method_type: "None", formula: "", status: 0 },
    { name: "Total Earned Premium", dataset_type: "Total Earned Premium", source_kind: "engine", method_type: "None", formula: '"Earned Premium" + "Remaining Budget Premium"', status: 0 },
    { name: "D 13 - Paid DFM w/ Selected LDFs", dataset_type: "Paid Ultimate", source_kind: "dfm", method_type: "DFM", status: 0 },
    { name: "D 18 - BS Paid DFM", dataset_type: "BS Paid Ultimate", source_kind: "dfm", method_type: "DFM", status: 0 },
    { name: "D 92 - Current Qtr Selected", dataset_type: "Current Qtr Selected", source_kind: "result_selection", method_type: "Result Selection", status: 0 },
  ],
  edges: [
    { source: "Earned Premium", target: "Total Earned Premium" },
    { source: "Remaining Budget Premium", target: "Total Earned Premium" },
    { source: "Total Earned Premium", target: "D 13 - Paid DFM w/ Selected LDFs" },
    { source: "Total Earned Premium", target: "D 18 - BS Paid DFM" },
    { source: "Total Earned Premium", target: "D 92 - Current Qtr Selected" },
  ],
};

test("the graph keeps indexed nodes and their links, dropping non-indexed, unknown and self edges", () => {
  const graph = buildDependencyGraph(PAYLOAD);
  assert.equal(graph.nodes.length, 6);
  assert.equal(graph.edges.length, 5);
  assert.equal(graph.byKey.has("gone vector"), false);
  assert.deepEqual(graph.byKey.get("paid").dependents, ["paid vector"]);
  assert.deepEqual(graph.byKey.get("incurred dfm").precedents, ["incurred"]);
  assert.deepEqual(graph.byKey.get("paid dfm").precedents, ["paid vector"]);
  assert.deepEqual(graph.byKey.get("paid dfm").dependents, ["selected ultimate"]);
  assert.equal(graph.byKey.get("paid dfm").methodName, "Paid DFM Method");
  assert.equal(graph.byKey.get("paid").methodType, "");
});

test("node families come from the method type, then the source kind", () => {
  assert.deepEqual(dependencyNodeKind({ source_kind: "input", method_type: "None" }), { family: "dataset", label: "Dataset" });
  assert.deepEqual(dependencyNodeKind({ source_kind: "calculated" }), { family: "calculated", label: "Calculated" });
  // An engine-built dataset reads as where its numbers came from: one source
  // column is Imported, a formula the Engine evaluates over other types is
  // Generated.
  assert.deepEqual(dependencyNodeKind({ source_kind: "engine" }), { family: "engine", label: "Imported" });
  assert.deepEqual(dependencyNodeKind({ source_kind: "engine", formula: "  " }), { family: "engine", label: "Imported" });
  assert.deepEqual(
    dependencyNodeKind({ source_kind: "engine", formula: '"Earned Premium" + "Remaining Budget Premium"' }),
    { family: "generated", label: "Generated" },
  );
  // A formula never overrides a method output.
  assert.deepEqual(dependencyNodeKind({ source_kind: "dfm", method_type: "DFM", formula: "A + B" }), { family: "method", label: "DFM" });
  assert.deepEqual(dependencyNodeKind({ source_kind: "dfm", method_type: "DFM" }), { family: "method", label: "DFM" });
});

test("a generated formula is drawn between its inputs and the methods that read it", () => {
  const graph = buildDependencyGraph(GENERATED_PAYLOAD);
  const b = graph.byKey.get("total earned premium");
  assert.deepEqual(b.kind, { family: "generated", label: "Generated" });
  assert.deepEqual(graph.byKey.get("earned premium").kind, { family: "engine", label: "Imported" });
  assert.deepEqual(graph.byKey.get("remaining budget premium").kind, { family: "engine", label: "Imported" });

  // Both inputs now have a dependent, so the default view draws them: nothing
  // in the class is hidden.
  assert.deepEqual([...dependencyGraphIsolatedKeys(graph)], []);

  // The left port of the formula lists what it is made from, the right port of
  // an input lists the formula that reads it.
  assert.deepEqual(dependencyGraphPortList(b, graph, "in"), {
    title: "Precedents (2)",
    empty: "",
    entries: [
      { key: "earned premium", name: "Earned Premium", label: "Imported", family: "engine" },
      { key: "remaining budget premium", name: "Remaining Budget Premium", label: "Imported", family: "engine" },
    ],
  });
  assert.deepEqual(dependencyGraphPortList(graph.byKey.get("earned premium"), graph, "out").entries, [
    { key: "total earned premium", name: "Total Earned Premium", label: "Generated", family: "generated" },
  ]);

  // Selecting an input lights the formula and everything the formula feeds.
  const reach = dependencyGraphReach(graph, "earned premium");
  assert.deepEqual([...reach.downstream].sort(), [
    "d 13 - paid dfm w/ selected ldfs",
    "d 18 - bs paid dfm",
    "d 92 - current qtr selected",
    "total earned premium",
  ]);
  assert.equal(reach.upstream.size, 0);
  assert.deepEqual([...dependencyGraphReach(graph, "d 13 - paid dfm w/ selected ldfs").upstream].sort(), [
    "earned premium",
    "remaining budget premium",
    "total earned premium",
  ]);

  // A class with no generated formula type draws exactly as before.
  const plain = buildDependencyGraph(PAYLOAD);
  assert.deepEqual(plain.nodes.map((node) => node.kind.family), [
    "dataset", "dataset", "calculated", "method", "method", "method",
  ]);
});

test("layers follow the longest chain of inputs and every edge runs left to right", () => {
  const graph = buildDependencyGraph(PAYLOAD);
  const layout = layoutDependencyGraph(graph);
  const layer = Object.fromEntries(layout.nodes.map((node) => [node.name, node.layer]));
  assert.equal(layer.Paid, 0);
  assert.equal(layer.Incurred, 0);
  assert.equal(layer["Gone Vector"], undefined);
  assert.equal(layer["Paid Vector"], 1);
  assert.equal(layer["Incurred DFM"], 1);
  assert.equal(layer["Paid DFM"], 2);
  assert.equal(layer["Selected Ultimate"], 3);
  const at = Object.fromEntries(layout.nodes.map((node) => [node.name, node]));
  for (const edge of layout.edges) {
    const source = layout.nodes.find((node) => node.key === edge.source);
    const target = layout.nodes.find((node) => node.key === edge.target);
    assert.ok(source.x + source.width < target.x, `${source.name} -> ${target.name}`);
    assert.equal(edge.back, false);
    assert.match(edge.path, /^M[\d.]+ [\d.]+C/);
  }
  // Rows inside a layer sit next to their neighbours: Paid Vector reads Paid,
  // Incurred DFM reads Incurred, so their relative order matches.
  assert.equal(at.Paid.row < at.Incurred.row, at["Paid Vector"].row < at["Incurred DFM"].row);
  assert.ok(layout.width > 0 && layout.height > 0);
  // Every node fits inside the reported extent.
  for (const node of layout.nodes) {
    assert.ok(node.x >= 0 && node.x + node.width <= layout.width);
    assert.ok(node.y >= 0 && node.y + node.height <= layout.height);
  }
});

test("a cycle is drawn rather than hanging the layout: its closing edge is marked back", () => {
  const graph = buildDependencyGraph({
    nodes: [{ name: "A" }, { name: "B" }, { name: "C" }],
    edges: [
      { source: "A", target: "B" },
      { source: "B", target: "C" },
      { source: "C", target: "A" },
    ],
  });
  const layout = layoutDependencyGraph(graph);
  const layer = Object.fromEntries(layout.nodes.map((node) => [node.name, node.layer]));
  assert.deepEqual(layer, { A: 0, B: 1, C: 2 });
  assert.deepEqual(
    layout.edges.map((edge) => [edge.source, edge.target, edge.back]),
    [["a", "b", false], ["b", "c", false], ["c", "a", true]],
  );
});

test("an empty class lays out to nothing", () => {
  const layout = layoutDependencyGraph(buildDependencyGraph({ nodes: [], edges: [] }));
  assert.deepEqual(layout, { nodes: [], edges: [], width: 0, height: 0 });
});

test("reach walks precedents and dependents transitively without the node itself", () => {
  const graph = buildDependencyGraph(PAYLOAD);
  const reach = dependencyGraphReach(graph, "paid dfm");
  assert.deepEqual([...reach.upstream].sort(), ["paid", "paid vector"]);
  assert.deepEqual([...reach.downstream].sort(), ["selected ultimate"]);
  const top = dependencyGraphReach(graph, "selected ultimate");
  assert.deepEqual([...top.upstream].sort(), ["incurred", "incurred dfm", "paid", "paid dfm", "paid vector"]);
  assert.equal(top.downstream.size, 0);
});

test("a click opens a method output as its method and a dataset as a dataset, never a missing name", () => {
  const graph = buildDependencyGraph(PAYLOAD);
  const identity = { projectName: "Demo", reservingClass: "COL" };
  assert.deepEqual(dependencyGraphOpenRequest(graph.byKey.get("paid dfm"), identity), {
    datasetName: "Paid DFM",
    datasetTypeName: "Paid Ultimate",
    projectName: "Demo",
    reservingClass: "COL",
    openMethod: true,
    methodType: "DFM",
    methodName: "Paid DFM Method",
  });
  assert.deepEqual(dependencyGraphOpenRequest(graph.byKey.get("paid vector"), identity), {
    datasetName: "Paid Vector",
    datasetTypeName: "Paid Vector",
    projectName: "Demo",
    reservingClass: "COL",
    openMethod: false,
  });
  assert.equal(dependencyGraphOpenRequest(graph.byKey.get("gone vector"), identity), null);
});

test("the status line reads the graph in plain words, hidden datasets included", () => {
  assert.equal(dependencyGraphSummary({ nodeCount: 7, edgeCount: 6, reviewCount: 1 }), "7 objects, 6 links. 1 needs review.");
  assert.equal(dependencyGraphSummary({ nodeCount: 1, edgeCount: 0, reviewCount: 0 }), "1 object, 0 links.");
  assert.equal(dependencyGraphSummary({ nodeCount: 5, edgeCount: 4, reviewCount: 0, hiddenCount: 2 }), "5 objects, 4 links. 2 datasets hidden.");
  assert.equal(dependencyGraphSummary({ nodeCount: 0, hiddenCount: 1 }), "1 dataset hidden.");
  assert.equal(dependencyGraphSummary({ nodeCount: 0 }), "");
});

test("isolated datasets and methods are hidden while connected chain endpoints remain", () => {
  const graph = buildDependencyGraph({
    ...PAYLOAD,
    nodes: [
      ...PAYLOAD.nodes,
      { name: "Orphan Vector", dataset_type: "Orphan Vector", source_kind: "calculated", method_type: "None", status: 0 },
      { name: "Idle Engine Table", dataset_type: "Idle Engine Table", source_kind: "engine", method_type: "None", status: 0 },
      { name: "Unused DFM", dataset_type: "Unused Ultimate", source_kind: "dfm", method_type: "DFM", status: 0 },
    ],
    edges: [...PAYLOAD.edges, { source: "Orphan Vector", target: "Gone Vector" }],
  });
  const hidden = dependencyGraphIsolatedKeys(graph);
  assert.deepEqual([...hidden].sort(), ["idle engine table", "orphan vector", "unused dfm"]);

  const pruned = pruneDependencyGraph(graph, hidden);
  assert.deepEqual(pruned.nodes.map((node) => node.name), [
    "Paid", "Incurred", "Paid Vector", "Paid DFM", "Incurred DFM", "Selected Ultimate",
  ]);
  assert.equal(pruned.edges.length, graph.edges.length, "no edge touched a hidden dataset");
  assert.equal(pruneDependencyGraph(graph, new Set()), graph, "nothing hidden is the same graph");
  assert.equal(graph.byKey.has("gone vector"), false, "names outside the index stay excluded");

  // A non-method endpoint with inputs remains part of its dependency chain.
  const withEdge = buildDependencyGraph({
    nodes: [
      { name: "Paid", source_kind: "input", method_type: "None" },
      { name: "Paid Copy", source_kind: "calculated", method_type: "None" },
      { name: "Paid DFM", source_kind: "dfm", method_type: "DFM" },
    ],
    edges: [{ source: "Paid", target: "Paid Copy" }, { source: "Paid", target: "Paid DFM" }],
  });
  const trimmed = pruneDependencyGraph(withEdge, dependencyGraphIsolatedKeys(withEdge));
  assert.deepEqual(trimmed.byKey.get("paid").dependents, ["paid copy", "paid dfm"]);
  assert.deepEqual(trimmed.edges, withEdge.edges);
  assert.ok(!withEdge.byKey.get("paid").dependents.includes(undefined), "the full graph is left untouched");
  assert.deepEqual(withEdge.byKey.get("paid").dependents, ["paid copy", "paid dfm"]);
});

test("each port lists the direct precedents or dependents with the label their box shows", () => {
  const graph = buildDependencyGraph(PAYLOAD);
  assert.deepEqual(dependencyGraphPortList(graph.byKey.get("selected ultimate"), graph, "in"), {
    title: "Precedents (2)",
    empty: "",
    entries: [
      { key: "paid dfm", name: "Paid DFM", label: "DFM", family: "method" },
      { key: "incurred dfm", name: "Incurred DFM", label: "DFM", family: "method" },
    ],
  });
  assert.deepEqual(dependencyGraphPortList(graph.byKey.get("incurred dfm"), graph, "in").entries.map((e) => e.name), ["Incurred"]);
  assert.deepEqual(dependencyGraphPortList(graph.byKey.get("selected ultimate"), graph, "out"), {
    title: "Dependents",
    empty: "No dependents",
    entries: [],
  });
  assert.deepEqual(dependencyGraphPortList(graph.byKey.get("paid"), graph, "out").entries.map((e) => e.family), ["calculated"]);
});

test("the scroll surface keeps half a canvas of margin on every side of the graph", () => {
  const layout = { width: 400, height: 200 };
  // Half of the 800x600 canvas on each side, so any edge of the graph reaches
  // the middle of the window.
  const small = dependencyGraphViewport(layout, { width: 800, height: 600 }, 1, 16);
  assert.deepEqual(small, { width: 1200, height: 800, offsetX: 400, offsetY: 300 });
  const large = dependencyGraphViewport(layout, { width: 300, height: 100 }, 2, 16);
  assert.deepEqual(large, { width: 1100, height: 500, offsetX: 150, offsetY: 50 });
  // A canvas too small to have been measured yet falls back to the padding.
  assert.deepEqual(
    dependencyGraphViewport(layout, { width: 0, height: 0 }, 1, 16),
    { width: 432, height: 232, offsetX: 16, offsetY: 16 },
  );
  // A node centred at graph (100, 50) lands in the middle of the 300x100 canvas.
  assert.deepEqual(
    dependencyGraphScrollTo(large, 2, { x: 100, y: 50 }, { x: 150, y: 50 }),
    { scrollLeft: 200, scrollTop: 100 },
  );
  // The leftmost box, at the graph's own left edge, reaches that middle too.
  assert.deepEqual(
    dependencyGraphScrollTo(large, 2, { x: 0, y: 0 }, { x: 150, y: 50 }),
    { scrollLeft: 0, scrollTop: 0 },
  );
});

test("the fit zoom shows the whole graph and never magnifies past 1:1", () => {
  const layout = { width: 400, height: 200 };
  // A graph wider than the canvas is shrunk until both sides fit inside the
  // padding: (300 - 32) / 400 is tighter than (200 - 32) / 200.
  assert.equal(dependencyGraphFitScale(layout, { width: 300, height: 200 }, 16), 0.67);
  // A graph with room to spare stays at 1:1 rather than being blown up.
  assert.equal(dependencyGraphFitScale(layout, { width: 900, height: 700 }, 16), 1);
  // A canvas too small to reach even the smallest zoom stops at that zoom.
  assert.equal(dependencyGraphFitScale(layout, { width: 40, height: 40 }, 16), 0.2);
  // Nothing to measure yet.
  assert.equal(dependencyGraphFitScale(layout, { width: 0, height: 0 }, 16), 0);
  assert.equal(dependencyGraphFitScale(null, { width: 800, height: 600 }, 16), 0);
});

test("the Project Instance page wires the toolbar icon, the window kind, and the redraw hook", async () => {
  const html = await read("../ui/project_instance/project_instance.html");
  const button = html.match(/<button class="dataset-toolbar-btn" id="dependencyGraphBtn"[\s\S]*?<\/button>/)?.[0];
  assert.ok(button, "the dataset toolbar carries the dependency graph button");
  assert.match(button, /<use href="\/ui\/project_instance\/dependency-graph\.svg\?v=\d{8}[a-z]#dependency-graph"><\/use>/);
  // Between the Excel links button and the refresh button, like the manual says.
  assert.ok(html.indexOf('id="excelLinksBtn"') < html.indexOf('id="dependencyGraphBtn"'));
  assert.ok(html.indexOf('id="dependencyGraphBtn"') < html.indexOf('id="datasetRefreshBtn"'));

  const icon = await read("../ui/project_instance/dependency-graph.svg");
  assert.match(icon, /<symbol id="dependency-graph" viewBox="0 0 24 24">/);
  assert.doesNotMatch(icon, /#[0-9a-f]{3,6}/i, "the icon takes its colour from the host");

  const context = await read("../ui/project_instance/project_instance_context.js");
  assert.match(context, /dependencyGraphBtn: document\.getElementById\("dependencyGraphBtn"\)/);

  const boot = await read("../ui/project_instance/project_instance_boot.js");
  assert.match(boot, /import \{ installProjectInstanceDependencyGraph \} from "\.\/project_instance_dependency_graph\.js\?v=\d{8}[a-z]";/);
  assert.match(boot, /installProjectInstanceDependencyGraph\(ctx\);/);
  assert.match(boot, /api\.initDependencyGraph\(\);/);

  const host = await read("../ui/project_instance/project_instance_dependency_graph.js");
  assert.match(host, /kind: DEPENDENCY_GRAPH_WINDOW_KIND,/);
  assert.match(host, /export const DEPENDENCY_GRAPH_WINDOW_KIND = "dependency_graph";/);
  assert.match(host, /iframeSrc: buildDependencyGraphWindowUrl\(inst, path, focusName\),/);
  assert.match(host, /\/ui\/project_instance\/dependency_graph_window\.html\?/);

  // A tool window: never part of the persisted Project Instance state.
  const windows = await read("../ui/project_instance/project_instance_windows.js");
  assert.match(windows, /if \(frame\.dataset\?\.windowKind === "dependency_graph"\) return null;/);

  // Every disk-backed table reload tells the open graph windows to redraw.
  const cache = await read("../ui/project_instance/project_instance_dataset_cache.js");
  assert.match(cache, /api\.notifyDependencyGraphWindows\?\.\(normalizedPath\);/);
  assert.match(rawWindowSource, /event\.data\?\.type === "arcrho:dependency-graph-refresh"/);
  assert.match(rawWindowSource, /"arcrho:project-instance-open-dependent-dataset"/);
});

test("the graph page and its read are registered end to end", async () => {
  const pageHtml = await read("../ui/project_instance/dependency_graph_window.html");
  assert.match(pageHtml, /dependency_graph_window\.css\?v=\d{8}[a-z]/);
  assert.match(pageHtml, /dependency_graph_window\.js\?v=\d{8}[a-z]/);
  for (const id of ["dependencyGraphSearch", "dependencyGraphMatchedOnly", "dependencyGraphZoomOut", "dependencyGraphZoomIn", "dependencyGraphFit", "dependencyGraphRefresh", "dependencyGraphCanvas", "dependencyGraphSvg", "dependencyGraphState", "dependencyGraphStatus"]) {
    assert.ok(pageHtml.includes(`id="${id}"`), id);
  }
  assert.ok(!pageHtml.includes("dependencyGraphShowAll"));
  assert.match(pageHtml, /id="dependencyGraphMatchedOnly"[^>]*checked/);
  // Each legend swatch spells the same label the boxes of that family show,
  // the Engine's two included.
  for (const node of [{ source_kind: "input" }, { source_kind: "calculated" }, { source_kind: "engine" }, { source_kind: "engine", formula: "A + B" }]) {
    const kind = dependencyNodeKind(node);
    assert.ok(pageHtml.includes(`<span data-family="${kind.family}">${kind.label}</span>`), kind.label);
  }
  // Every family the legend spells has its own accent, shared by the node
  // stripe, the popover row, and the swatch. The colours live in one shared
  // sheet the Dataset Viewer's dependency map reads too.
  const familyCss = await read("../ui/project_instance/dependency_graph_window.css");
  const familyTokens = await read("../ui/shared/styles/dependency_families.css");
  assert.match(pageHtml, /\/ui\/shared\/styles\/dependency_families\.css\?v=\d{8}[a-z]/);
  for (const family of ["dataset", "calculated", "engine", "generated", "method"]) {
    assert.match(familyTokens, new RegExp(`--dg-family-${family}:`), family);
    assert.doesNotMatch(familyCss, new RegExp(`--dg-family-${family}:`), family);
    assert.ok(
      familyCss.includes(`.dg-node[data-family="${family}"], .dg-port-popover-row[data-family="${family}"], .pi-dependency-graph-legend [data-family="${family}"]`),
      family,
    );
  }
  assert.match(rawWindowSource, /const GRAPH_ENDPOINT = "\/datasets\/dependency-graph";/);
  // The drag handle captures the pointer (arcrho-ui-design L16).
  assert.match(rawWindowSource, /svg\.setPointerCapture\(event\.pointerId\);/);

  // The canvas scrolls to pan but draws no scrollbars; only the port list keeps
  // the framed ArcRho ones.
  assert.match(pageHtml, /\/ui\/shared\/styles\/framed_scrollbars\.css\?v=\d{8}[a-z]/);
  assert.match(pageHtml, /class="pi-dependency-graph-canvas" id="dependencyGraphCanvas"/);
  assert.match(rawWindowSource, /scrollCanvasTo\(drag\.scrollLeft - dx, drag\.scrollTop - dy\);/);
  // The graph sits in a pannable margin, so the fit centres it instead of
  // scrolling to the origin.
  assert.doesNotMatch(rawWindowSource, /scrollCanvasTo\(0, 0\)/);

  // Zooming out stops once the whole graph is on screen, and the button with it.
  assert.match(rawWindowSource, /const floor = factor < 1 \? Math\.min\(zoomOutFloor\(\), view\.scale\) : ZOOM_MIN;/);
  assert.match(rawWindowSource, /const next = Math\.max\(floor, Math\.min\(ZOOM_MAX, view\.scale \* factor\)\);/);
  assert.match(rawWindowSource, /els\.zoomOut\.disabled = busy \|\| empty \|\| wholeGraphShowing;/);
  assert.doesNotMatch(rawWindowSource, /canvas\.classList\.add\("isScrolling"\)/);

  // Single click selects and pins the chain, double click opens, and a box
  // carries two ports instead of a tooltip.
  assert.match(rawWindowSource, /if \(event\.detail <= 1\) view\.chainBeforeClick = view\.selectedKey;\n\s+setSelection\(node\.key\);/);
  // Opening a box leaves the lit chain alone: the double click puts back what
  // its own first click replaced.
  assert.match(rawWindowSource, /box\.addEventListener\("dblclick", \(event\) => \{\n\s+event\.preventDefault\(\);\n\s+setSelection\(view\.chainBeforeClick\);\n\s+openNode\(node\);/);
  assert.doesNotMatch(rawWindowSource, /attachArcrhoTooltip\(box/);
  assert.match(rawWindowSource, /wrap\.appendChild\(buildPortElement\(node, "in"\)\);\n\s+wrap\.appendChild\(buildPortElement\(node, "out"\)\);/);
  const css = await read("../ui/project_instance/dependency_graph_window.css");
  assert.match(css, /\.pi-dependency-graph-canvas::-webkit-scrollbar \{ width: 0; height: 0; \}/);
  assert.match(css, /\.pi-dependency-graph-canvas \{[^}]*scrollbar-width: none;/);
  for (const selector of [".dg-port.is-in", ".dg-port.is-out", ".dg-port-popover", ".dg-port-popover-row", ".dg-node.is-upstream", ".dg-node.is-downstream", ".dg-node.is-target", ".dg-node.is-context-target"]) {
    assert.ok(css.includes(selector), selector);
  }
  assert.match(pageHtml, /id="dependencyGraphFilters"/);
  assert.doesNotMatch(pageHtml, /pi-dependency-graph-cue/);

  // A hovered box walks a name too long to fit from end to end: the page
  // measures that one name's overflow and times the turns, the stylesheet
  // owns the slide, and a name that fits keeps its resting ellipsis.
  assert.match(rawWindowSource, /box\.addEventListener\("pointerenter", \(\) => startNameScroll\(nameText\)\);/);
  assert.match(rawWindowSource, /box\.addEventListener\("pointerleave", \(\) => stopNameScroll\(nameText\)\);/);
  assert.match(rawWindowSource, /const shift = textEl\.scrollWidth - textEl\.clientWidth;\n\s+if \(shift < NAME_SCROLL_MIN_PX\) return;/);
  assert.match(rawWindowSource, /textEl\.style\.setProperty\("--dg-name-shift", `\$\{-shift\}px`\);/);
  // Even a name hanging a few pixels over travels, but no quicker than the
  // floor, and it rests at each end for a fixed while before turning back.
  assert.ok(Number(rawWindowSource.match(/const NAME_SCROLL_MIN_PX = (\d+);/)?.[1]) <= 3);
  assert.ok(Number(rawWindowSource.match(/const NAME_SCROLL_MIN_MS = (\d+);/)?.[1]) >= 1000);
  assert.ok(Number(rawWindowSource.match(/const NAME_SCROLL_HOLD_MS = (\d+);/)?.[1]) >= 1000);
  assert.match(rawWindowSource, /Math\.round\(Math\.max\(NAME_SCROLL_MIN_MS, \(shift \/ NAME_SCROLL_PX_PER_S\) \* 1000\)\)/);
  assert.match(rawWindowSource, /nameScroll\.timer = window\.setTimeout\(turn, travelMs \+ NAME_SCROLL_HOLD_MS\);/);
  assert.match(rawWindowSource, /nameScroll\.timer = window\.setTimeout\(turn, NAME_SCROLL_START_MS\);/);
  // A redraw or a pointer that left stops the trip and puts the name back.
  assert.match(rawWindowSource, /nameScroll\.el\?\.classList\.remove\("is-scrolling", "is-scrolled"\);/);
  assert.match(rawWindowSource, /closeNodeMenu\(\);\n\s+stopNameScroll\(\);/);
  assert.match(css, /\.dg-node-name-text \{[^}]*text-overflow: ellipsis;/);
  // It travels on `left`, not on a transform: an animating transform is lifted
  // onto its own layer, which the zoomed diagram rasterizes at the wrong scale
  // and the name goes soft for exactly as long as it moves.
  assert.match(css, /\.dg-node-name-text\.is-scrolling \{[^}]*transition: left var\(--dg-name-duration, 2s\) ease-in-out;/);
  assert.match(css, /\.dg-node-name-text\.is-scrolled \{ left: var\(--dg-name-shift, 0px\); \}/);
  assert.doesNotMatch(css, /\.dg-node-name-text[^{]*\{[^}]*transform:/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\.dg-node-name-text\.is-scrolling \{[^}]*transition: none;/);

  // The right-click menu offers the same open action without selecting the box.
  assert.match(pageHtml, /context_menu\.css\?v=\d{8}[a-z]/);
  const menu = pageHtml.match(/<div class="ctx-menu pi-dependency-graph-menu" id="dependencyGraphMenu"[\s\S]*?<\/div>\s*<\/div>/)?.[0];
  assert.ok(menu, "the page carries the box context menu");
  assert.match(menu, /<button class="ctx-item" type="button" role="menuitem" data-action="open">Show Dataset<\/button>/);
  assert.match(css, /\.pi-dependency-graph-menu \{ display: none;/);
  assert.match(rawWindowSource, /box\.addEventListener\("contextmenu", \(event\) => \{\n\s+event\.preventDefault\(\);\n\s+openNodeMenu\(node, box, event\);/);
  assert.match(rawWindowSource, /item\.textContent = node\.methodType \? "Show Method" : "Show Dataset";/);
  // The menu marks its box instead of selecting it, so the chain survives.
  assert.match(rawWindowSource, /box\.classList\.add\("is-context-target"\);/);

  const router = await read("../app_server/api/dataset_router.py");
  assert.match(router, /@router\.get\("\/datasets\/dependency-graph"\)/);
  assert.match(router, /"dataset_dependency_graph",/);
  const contract = await read("../../python-api/src/arcrho_workspace_read_contract.py");
  assert.match(contract, /"dataset_dependency_graph": WorkspaceReadKind\(\n\s+"dataset_dependency_graph_service",\n\s+"build_reserving_class_dependency_graph",\n\s+\("project_name", "reserving_class"\),/);
});
