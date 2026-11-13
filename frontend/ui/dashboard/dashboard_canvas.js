// The dashboard page canvas: widgets on a 12-column grid, drawn from the current page, with
// moving and resizing by pointer and drops from the library and field lists.

import { buildWidgetResult } from "./dashboard_data.js";
import { GRID_COLUMNS, MIN_WIDGET_HEIGHT, MIN_WIDGET_WIDTH, WIDGET_TYPES, gridRows } from "./dashboard_model.js";
import { hideTooltip, renderWidget } from "./dashboard_charts.js";
import { el, moreGlyph, openPickMenu } from "./dashboard_controls.js";

export const ASSET_DRAG_TYPE = "application/x-arco-dashboard-asset";
export const FIELD_DRAG_TYPE = "application/x-arco-dashboard-field";

const ROW_HEIGHT = 56;
const GAP = 12;
const DRAG_THRESHOLD = 4;

// A widget's result, including what only a number tile needs: its own value beside the change
// a comparison gives, and the trend behind it when a category is set.
export function computeWidgetResult(table, widget, filters) {
  if (widget.type === "text") return null;
  if (!table) return null;
  const result = buildWidgetResult(table, widget, filters);
  if (widget.type !== "kpi" || result.error) return result;
  const compare = widget.compare;
  const scoped = compare ? [...filters, { field: compare.field, values: [compare.target] }] : filters;
  const kpi = { value: result.series[0].values[0] };
  if (compare) {
    const plain = buildWidgetResult(table, { ...widget, compare: undefined }, scoped);
    kpi.delta = kpi.value;
    kpi.deltaMeasure = result.measures[0];
    kpi.value = plain.series?.[0]?.values[0] ?? null;
  }
  if (widget.category) {
    const trend = buildWidgetResult(table, { ...widget, type: "line", series: "", compare: undefined, sort: undefined, limit: undefined }, scoped);
    if (!trend.error) kpi.trend = trend.series[0].values;
  }
  result.kpi = kpi;
  result.empty = kpi.value == null;
  return result;
}

export function createCanvas({ host, getView, handlers }) {
  let metrics = { cell: 60 };
  let gesture = null;

  function measure() {
    const width = host.clientWidth;
    metrics = { cell: Math.max(24, (width - GAP * (GRID_COLUMNS - 1)) / GRID_COLUMNS) };
  }

  function place(node, layout) {
    node.style.left = `${layout.x * (metrics.cell + GAP)}px`;
    node.style.top = `${layout.y * (ROW_HEIGHT + GAP)}px`;
    node.style.width = `${layout.w * metrics.cell + (layout.w - 1) * GAP}px`;
    node.style.height = `${layout.h * ROW_HEIGHT + (layout.h - 1) * GAP}px`;
  }

  function cellAt(clientX, clientY) {
    const box = host.getBoundingClientRect();
    return {
      x: Math.round((clientX - box.left) / (metrics.cell + GAP)),
      y: Math.max(0, Math.round((clientY - box.top) / (ROW_HEIGHT + GAP))),
    };
  }

  function drawBody(body, widget, view) {
    const table = view.tables.get(widget.source);
    if (widget.type !== "text" && widget.source && !table) {
      body.replaceChildren(el("div", "dbWidgetMessage", view.sourceStatus(widget.source)));
      return;
    }
    const result = computeWidgetResult(table, widget, view.filtersFor(widget, table));
    // The drawing area is the body inside its padding.
    const style = getComputedStyle(body);
    const width = body.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const height = body.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    renderWidget(body, widget, result, {
      size: { width: Math.floor(width), height: Math.floor(height) },
      onSelect: view.mode === "view" ? (field, value) => handlers.onCrossFilter(widget, field, value) : null,
    });
  }

  function endGesture() {
    if (!gesture) return;
    const { handle, pointerId, onMove, onEnd, ghost } = gesture;
    gesture = null;
    handle.removeEventListener("pointermove", onMove);
    handle.removeEventListener("pointerup", onEnd);
    handle.removeEventListener("pointercancel", onEnd);
    handle.removeEventListener("lostpointercapture", onEnd);
    if (handle.hasPointerCapture?.(pointerId)) handle.releasePointerCapture(pointerId);
    ghost?.remove();
    host.classList.remove("dbDragging");
  }

  // Move (from the header) or resize (from the corner): the pointer is captured on the handle
  // itself, the widget follows it freely, and a ghost shows the grid cell it will settle in.
  function startGesture(event, handle, node, widget, kind) {
    if (event.button !== 0 || gesture) return;
    const start = { x: event.clientX, y: event.clientY };
    const origin = { ...widget.layout };
    const box = { left: node.offsetLeft, top: node.offsetTop, width: node.offsetWidth, height: node.offsetHeight };
    let target = { ...origin };
    let moved = false;
    const ghost = el("div", "dbGhost");
    const onMove = (move) => {
      if (move.pointerId !== event.pointerId) return;
      const dx = move.clientX - start.x;
      const dy = move.clientY - start.y;
      if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
      if (!moved) {
        moved = true;
        hideTooltip();
        host.classList.add("dbDragging");
        node.classList.add("dbLifted");
        host.appendChild(ghost);
      }
      if (kind === "move") {
        node.style.left = `${box.left + dx}px`;
        node.style.top = `${box.top + dy}px`;
        const x = Math.round((box.left + dx) / (metrics.cell + GAP));
        const y = Math.round((box.top + dy) / (ROW_HEIGHT + GAP));
        target = { ...origin, x: Math.max(0, Math.min(GRID_COLUMNS - origin.w, x)), y: Math.max(0, y) };
      } else {
        const width = Math.max(40, box.width + dx);
        const height = Math.max(40, box.height + dy);
        node.style.width = `${width}px`;
        node.style.height = `${height}px`;
        const w = Math.round((width + GAP) / (metrics.cell + GAP));
        const h = Math.round((height + GAP) / (ROW_HEIGHT + GAP));
        target = {
          ...origin,
          w: Math.max(MIN_WIDGET_WIDTH, Math.min(GRID_COLUMNS - origin.x, w)),
          h: Math.max(MIN_WIDGET_HEIGHT, h),
        };
      }
      place(ghost, target);
    };
    const onEnd = (end) => {
      if (end.pointerId !== event.pointerId) return;
      endGesture();
      node.classList.remove("dbLifted");
      if (!moved) return handlers.onSelect(widget.id);
      const changed = ["x", "y", "w", "h"].some((key) => target[key] !== origin[key]);
      if (changed) handlers.onLayout(widget.id, target);
      else render();
    };
    gesture = { handle, pointerId: event.pointerId, onMove, onEnd, ghost };
    handle.setPointerCapture(event.pointerId);
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onEnd);
    handle.addEventListener("pointercancel", onEnd);
    handle.addEventListener("lostpointercapture", onEnd);
  }

  function widgetMenu(trigger, widget, view) {
    const options = [];
    if (widget.type !== "text" && widget.type !== "table" && widget.type !== "kpi") {
      options.push({ value: "table", label: widget.options?.table ? "Show as chart" : "Show as table" });
    }
    if (widget.type !== "text") options.push({ value: "ask", label: "Explain with ArcBot" });
    if (view.mode === "edit") {
      options.push({ value: "duplicate", label: "Duplicate" }, { value: "library", label: "Save to Library" }, { value: "delete", label: "Delete" });
    }
    openPickMenu(trigger, { options, selected: new Set(), onPick: (action) => handlers.onAction(widget.id, action) });
  }

  function buildWidget(widget, view) {
    const node = el("section", "dbWidget");
    node.dataset.id = widget.id;
    node.dataset.type = widget.type;
    if (view.mode === "edit" && view.selectedId === widget.id) node.classList.add("selected");
    const header = el("header", "dbWidgetHeader");
    header.appendChild(el("span", "dbWidgetTitle", widget.title || WIDGET_TYPES[widget.type].label));
    const menu = el("button", "dbIconBtn dbWidgetMenu");
    menu.type = "button";
    menu.setAttribute("aria-label", "Chart actions");
    menu.appendChild(moreGlyph());
    menu.addEventListener("pointerdown", (event) => event.stopPropagation());
    menu.addEventListener("click", (event) => { event.stopPropagation(); widgetMenu(menu, widget, view); });
    header.appendChild(menu);
    const body = el("div", "dbWidgetBody");
    node.append(header, body);
    if (view.mode === "edit") {
      header.classList.add("dbDragHandle");
      header.addEventListener("pointerdown", (event) => startGesture(event, header, node, widget, "move"));
      body.addEventListener("click", () => handlers.onSelect(widget.id));
      const corner = el("div", "dbResize");
      corner.addEventListener("pointerdown", (event) => { event.stopPropagation(); startGesture(event, corner, node, widget, "resize"); });
      node.appendChild(corner);
      node.addEventListener("dragover", (event) => {
        if (!event.dataTransfer.types.includes(FIELD_DRAG_TYPE)) return;
        event.preventDefault();
        event.stopPropagation();
        node.classList.add("dbDropTarget");
      });
      node.addEventListener("dragleave", () => node.classList.remove("dbDropTarget"));
      node.addEventListener("drop", (event) => {
        node.classList.remove("dbDropTarget");
        const raw = event.dataTransfer.getData(FIELD_DRAG_TYPE);
        if (!raw) return;
        event.preventDefault();
        event.stopPropagation();
        handlers.onDropField(widget.id, JSON.parse(raw));
      });
    }
    place(node, widget.layout);
    return { node, body };
  }

  function render() {
    endGesture();
    hideTooltip();
    const view = getView();
    measure();
    host.replaceChildren();
    host.classList.toggle("dbEditing", view.mode === "edit");
    const widgets = view.page?.widgets || [];
    host.style.height = `${Math.max(4, gridRows(widgets) + (view.mode === "edit" ? 3 : 0)) * (ROW_HEIGHT + GAP)}px`;
    if (!widgets.length) {
      host.appendChild(el("div", "dbCanvasEmpty", view.mode === "edit" ? "Drag a chart here from the library" : "This page has no charts yet"));
      return;
    }
    const built = widgets.map((widget) => ({ widget, ...buildWidget(widget, view) }));
    for (const item of built) host.appendChild(item.node);
    // Bodies are drawn after every widget is in the document, when their sizes are known.
    for (const item of built) drawBody(item.body, item.widget, view);
  }

  host.addEventListener("dragover", (event) => {
    if (getView().mode !== "edit" || !event.dataTransfer.types.includes(ASSET_DRAG_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    host.classList.add("dbDropTarget");
  });
  host.addEventListener("dragleave", (event) => { if (event.target === host) host.classList.remove("dbDropTarget"); });
  host.addEventListener("drop", (event) => {
    host.classList.remove("dbDropTarget");
    const assetId = event.dataTransfer.getData(ASSET_DRAG_TYPE);
    if (!assetId) return;
    event.preventDefault();
    handlers.onDropAsset(assetId, cellAt(event.clientX, event.clientY));
  });
  host.addEventListener("click", (event) => { if (event.target === host) handlers.onSelect(""); });

  let frame = 0;
  let lastWidth = 0;
  new ResizeObserver(() => {
    if (host.clientWidth === lastWidth || gesture) return;
    lastWidth = host.clientWidth;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(render);
  }).observe(host);

  return { render };
}
