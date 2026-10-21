/*
 * Details dependency map: the one-step neighbourhood of a dataset, drawn like a
 * slice of the Project Instance Dependency Graph.
 *
 * Precedents stand in the left column, the dataset itself in the middle, and
 * its dependents on the right, each as a small box with the family stripe and
 * kind label the full graph uses, joined by arrows into what reads them. The
 * boxes are ordinary HTML laid out by the stylesheet; only the arrows are
 * measured, after layout, into an SVG behind them, so the map follows the
 * width of the Details tab without a layout engine.
 *
 * The map draws; the host decides what a box does. `onOpenEntry` opens a
 * related dataset or method, `onOpenGraph` opens the full graph (usually
 * through `requestDependencyGraph`), and the tooltip callbacks show a box's
 * name and formula on hover.
 */
import { dependencyNodeKind } from "../../../project_instance/dependency_graph_layout.js?v=20260920c";
import { DEPENDENCY_GRAPH_OPEN_MESSAGE } from "../../../project_instance/dependency_graph_contract.js?v=20261020a";
import { attachArcrhoTooltip } from "../../components/tooltip/tooltip.js?v=20260925a";

const SVG_NS = "http://www.w3.org/2000/svg";
const ARROW_IDS = Object.freeze({
  edge: "arDetailsDepMapArrow",
  in: "arDetailsDepMapArrowIn",
  out: "arDetailsDepMapArrowOut",
});

const SIDES = Object.freeze({
  in: { title: "Precedents", empty: "No precedents" },
  out: { title: "Dependents", empty: "No dependents" },
});

/**
 * The family and label one box is drawn with, read the way the full graph
 * reads a node: a method output by its method type, a dataset with a formula
 * as Calculated, anything else as a Dataset.
 */
export function dependencyMapNodeKind({ methodType = "", formula = "" } = {}) {
  return dependencyNodeKind({
    method_type: methodType,
    source_kind: String(formula || "").trim() ? "calculated" : "",
  });
}

/** One arrow from the right edge of one box to the left edge of the next. */
export function dependencyMapEdgePath(source, target) {
  const sx = source.right;
  const sy = source.top + source.height / 2;
  const tx = target.left;
  const ty = target.top + target.height / 2;
  const reach = Math.max(12, (tx - sx) / 2);
  return `M${sx} ${sy}C${sx + reach} ${sy},${tx - reach} ${ty},${tx} ${ty}`;
}

/**
 * Asks the Project Instance page to open the full Dependency Graph for one
 * reserving class with one dataset in focus. The graph window belongs to that
 * page, so a dataset window can only ask.
 */
export function requestDependencyGraph({ windowRef = globalThis.window, instanceId = "", reservingClass = "", datasetName = "" } = {}) {
  windowRef?.parent?.postMessage({
    type: DEPENDENCY_GRAPH_OPEN_MESSAGE,
    inst: instanceId,
    reservingClass: String(reservingClass || "").trim(),
    focusDatasetName: String(datasetName || "").trim(),
  }, "*");
}

export function createDetailsDependencyMap({
  container = null,
  canOpenGraph = false,
  onOpenEntry = () => {},
  onOpenGraph = () => {},
  showTooltip = () => {},
  moveTooltip = () => {},
  hideTooltip = () => {},
  documentRef = globalThis.document,
  windowRef = globalThis.window,
} = {}) {
  const doc = documentRef;
  const win = windowRef;
  let els = null;
  let edges = [];
  let drawFrame = 0;
  let centerPending = false;

  function el(tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function svgEl(tag, attributes = {}) {
    const node = doc.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
    return node;
  }

  function arrowMarker(id, className) {
    const marker = svgEl("marker", {
      id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto",
    });
    marker.appendChild(svgEl("path", { d: "M0 1L9 5L0 9z", class: className }));
    return marker;
  }

  function mount() {
    if (els || !container) return els;
    const header = el("div", "arDetailsDepMapHeader");
    const titles = {
      in: el("span", "arDetailsDepMapTitle is-in"),
      self: el("span", "arDetailsDepMapTitle is-self"),
      out: el("span", "arDetailsDepMapTitle is-out"),
    };
    header.append(titles.in, titles.self, titles.out);

    if (canOpenGraph) {
      const open = el("button", "arDetailsDepMapOpen");
      open.type = "button";
      open.setAttribute("aria-label", "Open Dependency Graph");
      const icon = svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
      icon.appendChild(svgEl("use", { href: "/ui/project_instance/dependency-graph.svg?v=20260920c#dependency-graph" }));
      open.appendChild(icon);
      open.addEventListener("click", () => onOpenGraph());
      attachArcrhoTooltip(open, "Open Dependency Graph");
      header.appendChild(open);
    }

    const scroll = el("div", "arDetailsDepMapScroll");
    const stage = el("div", "arDetailsDepMapStage");
    const svg = svgEl("svg", { class: "arDetailsDepMapEdges", "aria-hidden": "true" });
    const defs = svgEl("defs");
    defs.append(
      arrowMarker(ARROW_IDS.edge, "arDetailsDepMapArrow"),
      arrowMarker(ARROW_IDS.in, "arDetailsDepMapArrow is-in"),
      arrowMarker(ARROW_IDS.out, "arDetailsDepMapArrow is-out"),
    );
    svg.appendChild(defs);
    const columns = {
      in: el("div", "arDetailsDepMapColumn is-in"),
      self: el("div", "arDetailsDepMapColumn is-self"),
      out: el("div", "arDetailsDepMapColumn is-out"),
    };
    stage.append(svg, columns.in, columns.self, columns.out);
    scroll.appendChild(stage);
    container.replaceChildren(header, scroll);

    // The Details tab is hidden while another tab is showing, so the arrows
    // are measured again whenever the stage gets its size back.
    if (typeof win?.ResizeObserver === "function") {
      new win.ResizeObserver(() => scheduleDraw()).observe(stage);
    }
    els = { titles, scroll, stage, svg, columns };
    return els;
  }

  function buildNode(entry, side) {
    const kind = dependencyMapNodeKind(entry);
    // A box is a focusable div rather than a button: the Dark theme restyles
    // every button, and a box must keep the look the full graph gives it.
    const node = el("div", "arDetailsDepNode");
    node.dataset.family = kind.family;
    node.dataset.side = side;
    const name = el("span", "arDetailsDepNodeName", entry.name);
    const label = el("span", "arDetailsDepNodeKind", kind.label);
    node.append(name, label);
    if (side === "self") {
      node.setAttribute("aria-label", `${entry.methodType ? "This method" : "This dataset"}: ${entry.name}`);
    } else {
      node.tabIndex = 0;
      node.setAttribute("role", "button");
      node.setAttribute("aria-label", `Open ${kind.label} ${entry.name}`);
      node.addEventListener("click", () => onOpenEntry(entry.source));
      node.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onOpenEntry(entry.source);
      });
    }
    node.addEventListener("mouseenter", (event) => {
      setLit(node, true);
      showTooltip(entry, event);
    });
    node.addEventListener("mousemove", (event) => moveTooltip(event));
    node.addEventListener("mouseleave", () => {
      setLit(node, false);
      hideTooltip();
    });
    node.addEventListener("focus", () => setLit(node, true));
    node.addEventListener("blur", () => {
      setLit(node, false);
      hideTooltip();
    });
    return node;
  }

  function fillColumn(column, entries, side) {
    column.replaceChildren();
    if (!entries.length) {
      column.appendChild(el("div", "arDetailsDepMapEmpty", SIDES[side].empty));
      return [];
    }
    return entries.map((entry) => {
      const node = buildNode(entry, side);
      column.appendChild(node);
      return node;
    });
  }

  // Hovering a box lights the arrow it shares with this dataset - blue for an
  // input, green for a dependent, as the full graph colours a chain. Hovering
  // this dataset lights them all.
  function setLit(node, lit) {
    for (const edge of edges) {
      const on = lit && (edge.node === node || node.dataset.side === "self");
      edge.path.classList.toggle("is-lit", on);
      edge.path.setAttribute("marker-end", `url(#${on ? ARROW_IDS[edge.side] : ARROW_IDS.edge})`);
    }
  }

  function draw() {
    drawFrame = 0;
    if (!els) return;
    const { stage, svg } = els;
    const origin = stage.getBoundingClientRect();
    for (const edge of edges) edge.path.remove();
    if (!origin.width || !origin.height) return;
    svg.setAttribute("width", String(Math.round(origin.width)));
    svg.setAttribute("height", String(Math.round(origin.height)));
    const box = (node) => {
      const rect = node.getBoundingClientRect();
      return {
        left: rect.left - origin.left,
        right: rect.right - origin.left,
        top: rect.top - origin.top,
        height: rect.height,
      };
    };
    for (const edge of edges) {
      const self = box(edge.self);
      const other = box(edge.node);
      edge.path.setAttribute("d", edge.side === "in" ? dependencyMapEdgePath(other, self) : dependencyMapEdgePath(self, other));
      svg.appendChild(edge.path);
    }
    // A list longer than the map scrolls, and the dataset sits in the middle
    // of its column, so a fresh paint scrolls it into view.
    const selfNode = els.columns.self.firstElementChild;
    if (centerPending && selfNode) {
      centerPending = false;
      const self = box(selfNode);
      els.scroll.scrollTop = Math.max(0, self.top + self.height / 2 - els.scroll.clientHeight / 2);
    }
  }

  function scheduleDraw() {
    if (drawFrame || typeof win?.requestAnimationFrame !== "function") return;
    drawFrame = win.requestAnimationFrame(draw);
  }

  return {
    /**
     * Paints the map. `self` is this output ({ name, formula, methodType }, the
     * method type only on a method page); each entry is a normalized
     * dependency ({ datasetName, formula, methodType }).
     */
    render({ self = {}, precedents = [], dependents = [] } = {}) {
      const parts = mount();
      if (!parts) return;
      hideTooltip();
      const toNode = (entry) => ({
        name: entry.datasetName,
        formula: entry.formula,
        methodType: entry.methodType,
        source: entry,
      });
      const inputs = precedents.map(toNode);
      const outputs = dependents.map(toNode);
      parts.titles.in.textContent = inputs.length ? `${SIDES.in.title} (${inputs.length})` : SIDES.in.title;
      parts.titles.out.textContent = outputs.length ? `${SIDES.out.title} (${outputs.length})` : SIDES.out.title;

      // On a method page the middle box is the dataset the method publishes,
      // labelled with the method type as the full graph labels a method box.
      const selfIsMethod = !!String(self.methodType || "").trim();
      parts.titles.self.textContent = selfIsMethod ? "This Method" : "This Dataset";
      const selfNode = buildNode({
        name: String(self.name || "").trim() || (selfIsMethod ? "Unsaved Method" : "Unsaved Dataset"),
        formula: String(self.formula || "").trim(),
        methodType: String(self.methodType || "").trim(),
      }, "self");
      parts.columns.self.replaceChildren(selfNode);
      const inNodes = fillColumn(parts.columns.in, inputs, "in");
      const outNodes = fillColumn(parts.columns.out, outputs, "out");
      edges = [
        ...inNodes.map((node) => ({ side: "in", node })),
        ...outNodes.map((node) => ({ side: "out", node })),
      ].map((edge) => ({
        ...edge,
        self: selfNode,
        path: svgEl("path", { class: `arDetailsDepMapEdge is-${edge.side}`, "marker-end": `url(#${ARROW_IDS.edge})` }),
      }));
      centerPending = true;
      scheduleDraw();
    },
  };
}
