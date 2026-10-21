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
 * related dataset or method, and `onOpenGraph` opens the full graph (usually
 * through `requestDependencyGraph`). The map shows no tooltips: hovering a box
 * only lights its arrow.
 *
 * On a method page the precedents column is also where the method's inputs are
 * chosen. Each input slot the page hands over is drawn as one box per chosen
 * dataset, labelled with the input's role instead of its kind, with a "..."
 * button that opens the page's picker and an x where the page allows removal.
 * An empty slot is a dashed "Choose" box and a slot that takes several
 * datasets ends in a dashed "Add" box; both open the picker anchored to
 * themselves. The page keeps owning the value; the map only asks.
 */
import { dependencyNodeKind } from "../../../project_instance/dependency_graph_layout.js?v=20260920c";
import { DEPENDENCY_GRAPH_OPEN_MESSAGE } from "../../../project_instance/dependency_graph_contract.js?v=20261020a";

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

// The arrows between the columns never get shorter than `min`, so a crowded map
// still reads as a flow, nor longer than `max`. A box grows with spare room up
// to `cardMax`, or to its full text when that is wider; past both caps the
// room is left empty on the right of the map.
const DEP_MAP_LIMITS = Object.freeze({ arrowMin: 48, arrowMax: 160, cardMax: 360, arrowShare: 0.5 });

/**
 * How the three columns share the map's width. `naturalWidths` is what each
 * column needs to show its longest name in full, `stageWidth` the room the map
 * has, and `columnMin` the narrowest a column may be.
 *
 * When every name fits, half of the room left over lengthens the two arrows
 * and the rest widens the boxes, each up to its cap, and `columns` gives each
 * column's width. When the names do not fit, `columns` is null: the arrows
 * stay at their minimum and the stylesheet shrinks the columns evenly.
 */
export function dependencyMapLayout({ stageWidth = 0, naturalWidths = [], columnMin = 0 } = {}) {
  const { arrowMin, arrowMax, cardMax, arrowShare } = DEP_MAP_LIMITS;
  const widths = naturalWidths.map((width) => Math.max(Math.ceil(width), Math.ceil(columnMin)));
  const spare = stageWidth - widths.reduce((sum, width) => sum + width, 0) - 2 * arrowMin;
  if (spare < 0) return { gap: arrowMin, columns: null };
  const gap = Math.floor(Math.min(arrowMax, arrowMin + (spare * arrowShare) / 2));
  const perColumn = (spare - 2 * (gap - arrowMin)) / widths.length;
  const columns = widths.map((width) => Math.floor(Math.min(width + perColumn, Math.max(width, cardMax))));
  return { gap, columns };
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
    // The header holds only the open button. The column titles sit in the
    // stage's own grid, so each one lines up with a column sized to its names.
    const header = el("div", "arDetailsDepMapHeader");
    // Each title cell paints the title row's background; the text inside it is
    // what gets cut, so the cell itself can reach across the gaps.
    const titleCells = {};
    const titles = {};
    for (const side of ["in", "self", "out"]) {
      titleCells[side] = el("div", `arDetailsDepMapTitle is-${side}`);
      titles[side] = titleCells[side].appendChild(el("span", "arDetailsDepMapTitleText"));
    }

    if (canOpenGraph) {
      const open = el("button", "arDetailsDepMapOpen");
      open.type = "button";
      open.setAttribute("aria-label", "Open Dependency Graph");
      const icon = svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
      icon.appendChild(svgEl("use", { href: "/ui/project_instance/dependency-graph.svg?v=20260920c#dependency-graph" }));
      open.appendChild(icon);
      open.addEventListener("click", () => onOpenGraph());
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
    stage.append(svg, columns.in, columns.self, columns.out, titleCells.in, titleCells.self, titleCells.out);
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

  // Enter and Space act on the box itself, not on a button inside it.
  function onActivate(node, action) {
    node.tabIndex = 0;
    node.setAttribute("role", "button");
    node.addEventListener("click", action);
    node.addEventListener("keydown", (event) => {
      if (event.target !== node || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      action();
    });
  }

  function actionButton(className, ariaLabel, action) {
    const button = el("button", `arDetailsDepNodeAction ${className}`);
    button.type = "button";
    button.setAttribute("aria-label", ariaLabel);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      action();
    });
    return button;
  }

  function buildNode(entry, side) {
    const kind = dependencyMapNodeKind(entry);
    // A box is a focusable div rather than a button: the Dark theme restyles
    // every button, and a box must keep the look the full graph gives it.
    const node = el("div", "arDetailsDepNode");
    node.dataset.family = kind.family;
    node.dataset.side = side;
    const name = el("span", "arDetailsDepNodeName", entry.name);
    // An input box names the role it fills; its stripe still shows the kind.
    const label = el("span", "arDetailsDepNodeKind", entry.role || kind.label);
    node.append(name, label);
    if (side === "self") {
      node.setAttribute("aria-label", `${entry.methodType ? "This method" : "This dataset"}: ${entry.name}`);
    } else {
      onActivate(node, () => onOpenEntry(entry.source));
      node.setAttribute("aria-label", `Open ${entry.role || kind.label} ${entry.name}`);
    }
    const slot = entry.slot;
    if (slot && !slot.disabled) {
      const actions = el("span", "arDetailsDepNodeActions");
      // A single input is replaced in place; a list input is changed by
      // removing one entry and adding another.
      if (!slot.multiple) {
        const change = actionButton("is-change", `Change ${slot.label}`, () => slot.pick(node, { index: entry.index }));
        change.textContent = "...";
        actions.appendChild(change);
      }
      if (typeof slot.remove === "function") {
        const remove = actionButton("is-remove", `Remove ${entry.name}`, () => slot.remove(entry.index));
        const icon = svgEl("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" });
        icon.appendChild(svgEl("path", { d: "M6 6l12 12M18 6L6 18" }));
        remove.appendChild(icon);
        actions.appendChild(remove);
      }
      if (actions.childElementCount) node.appendChild(actions);
    }
    node.addEventListener("mouseenter", () => setLit(node, true));
    node.addEventListener("mouseleave", () => setLit(node, false));
    node.addEventListener("focus", () => setLit(node, true));
    node.addEventListener("blur", () => setLit(node, false));
    return node;
  }

  // A dashed box for an input still to choose: an empty slot, or the next
  // entry of a slot that takes several datasets.
  function buildPlaceholder(slot, text) {
    const node = el("div", "arDetailsDepNode is-placeholder");
    node.dataset.side = "in";
    node.appendChild(el("span", "arDetailsDepNodeName", text));
    if (slot.disabled) {
      node.setAttribute("aria-disabled", "true");
    } else {
      onActivate(node, () => slot.pick(node, { index: null }));
      node.setAttribute("aria-label", text);
    }
    return node;
  }

  function fillColumn(column, entries, side) {
    column.replaceChildren();
    if (!entries.length) {
      column.appendChild(el("div", "arDetailsDepMapEmpty", SIDES[side].empty));
      return [];
    }
    const linked = [];
    for (const entry of entries) {
      if (entry.placeholder) {
        column.appendChild(buildPlaceholder(entry.slot, entry.placeholder));
        continue;
      }
      const node = buildNode(entry, side);
      column.appendChild(node);
      linked.push(node);
    }
    return linked;
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

  // What a box needs to show its text in full: its width with the name's room
  // swapped for the name text's own width, which is wider when the name is cut
  // and narrower when a stretched box gives it spare room, plus whatever a cut
  // label hides. An empty-column note needs no more than the column floor.
  function naturalWidth(node) {
    const name = node.querySelector(".arDetailsDepNodeName");
    if (!name) return 0;
    const range = doc.createRange();
    range.selectNodeContents(name);
    const label = node.querySelector(".arDetailsDepNodeKind");
    return node.offsetWidth
      - name.clientWidth
      + Math.ceil(range.getBoundingClientRect().width)
      + (label ? Math.max(0, label.scrollWidth - label.clientWidth) : 0);
  }

  // The column floor is defined once, in the stylesheet, as a pixel width
  // capped at a share of the map.
  function columnMin(stageWidth) {
    const style = win.getComputedStyle(els.stage);
    const px = Number.parseFloat(style.getPropertyValue("--ar-dep-map-column-min-px")) || 0;
    const share = Number.parseFloat(style.getPropertyValue("--ar-dep-map-column-min-share")) || 0;
    return Math.min(px, share * stageWidth);
  }

  // Sizes the columns and arrows from the names they hold. When the names do
  // not fit, the stylesheet's own column template takes over.
  function fitColumns() {
    const { stage, columns } = els;
    const stageWidth = stage.clientWidth;
    const naturalWidths = ["in", "self", "out"].map((side) => Math.max(0, ...Array.from(columns[side].children, naturalWidth)));
    const layout = dependencyMapLayout({ stageWidth, naturalWidths, columnMin: columnMin(stageWidth) });
    stage.style.columnGap = `${layout.gap}px`;
    stage.style.gridTemplateColumns = layout.columns ? layout.columns.map((width) => `${width}px`).join(" ") : "";
  }

  function draw() {
    drawFrame = 0;
    if (!els) return;
    const { stage, svg } = els;
    if (stage.clientWidth) fitColumns();
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
     *
     * `inputs` is the method's input slots, each `{ slot, values }`: `slot`
     * is what the page handed over ({ label, multiple, max, disabled, pick,
     * remove }) and `values` the normalized entries chosen for it. Slot
     * boxes come first, in slot order, then `precedents` the method reads
     * some other way.
     */
    render({ self = {}, inputs = [], precedents = [], dependents = [] } = {}) {
      const parts = mount();
      if (!parts) return;
      const toNode = (entry) => ({
        name: entry.datasetName,
        formula: entry.formula,
        methodType: entry.methodType,
        source: entry,
      });
      const slotNodes = inputs.flatMap(({ slot, values }) => {
        const nodes = values.map((entry, index) => ({ ...toNode(entry), role: slot.label, slot, index }));
        if (slot.multiple && values.length < (slot.max || Infinity)) {
          nodes.push({ slot, placeholder: `+ Add ${slot.label}` });
        } else if (!values.length) {
          nodes.push({ slot, placeholder: `Choose ${slot.label}` });
        }
        return nodes;
      });
      const inputNodes = [...slotNodes, ...precedents.map(toNode)];
      const outputs = dependents.map(toNode);
      const inputCount = inputNodes.filter((node) => !node.placeholder).length;
      parts.titles.in.textContent = inputCount ? `${SIDES.in.title} (${inputCount})` : SIDES.in.title;
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
      const inNodes = fillColumn(parts.columns.in, inputNodes, "in");
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
