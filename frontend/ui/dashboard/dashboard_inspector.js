// The inspector: every property of the selected widget as a pick list, a text box, or a switch.
// It never edits the dashboard itself; each control hands `change` a function that edits a
// draft of the widget, and the page commits that as one undoable step.

import { distinctValues } from "./dashboard_data.js";
import { AGGREGATIONS, NUMBER_FORMATS, WIDGET_TYPES, defaultAggregation } from "./dashboard_model.js";
import { button, closeGlyph, el, formRow, icon, iconButton, multiPickField, pickField, textInput } from "./dashboard_controls.js";

const SERIES_LABELS = { heatmap: "Columns", scatter: "Color By", table: "Columns" };
const CATEGORY_LABELS = { heatmap: "Rows", scatter: "Points", kpi: "Trend By", share: "Parts", table: "Rows" };
const TOGGLES = {
  bar: [["stacked", "Stacked"], ["horizontal", "Horizontal"], ["labels", "Value Labels"]],
};

function section(host, title) {
  const block = el("section", "dbInspectorSection");
  if (title) block.appendChild(el("div", "dbSectionLabel", title));
  host.appendChild(block);
  return block;
}

function switchRow(label, on, onChange) {
  const control = el("button", "dbSwitch");
  control.type = "button";
  control.setAttribute("role", "switch");
  control.setAttribute("aria-checked", String(!!on));
  control.addEventListener("click", () => onChange(!on));
  return formRow(label, control);
}

function fieldOptions(columns) {
  const dimensions = columns.filter((column) => column.role !== "measure");
  const measures = columns.filter((column) => column.role === "measure");
  return {
    dimensions: [
      ...dimensions.map((column) => ({ value: column.name, label: column.name, group: "Fields" })),
      ...measures.map((column) => ({ value: column.name, label: column.name, group: "Numbers" })),
    ],
    measures: measures.map((column) => ({ value: column.name, label: column.name, tag: column.data_format || "" })),
  };
}

function measureEditor(measure, index, { columns, options, change }) {
  const card = el("div", "dbMeasure");
  const head = el("div", "dbMeasureHead");
  if (measure.expr != null) {
    head.appendChild(textInput({
      value: measure.expr,
      placeholder: "sum([Paid]) / sum([Premium])",
      mono: true,
      onChange: (value) => change((draft) => { draft.measures[index] = { ...draft.measures[index], expr: value }; }),
    }));
  } else {
    head.appendChild(pickField({
      options: options.measures,
      value: measure.field,
      search: true,
      onChange: (value) => change((draft) => {
        const column = columns.find((item) => item.name === value);
        draft.measures[index] = { ...draft.measures[index], field: value, agg: defaultAggregation(column) };
      }),
    }));
    head.appendChild(pickField({
      options: AGGREGATIONS.map((item) => ({ value: item.id, label: item.label })),
      value: measure.agg || defaultAggregation(columns.find((item) => item.name === measure.field)),
      onChange: (value) => change((draft) => { draft.measures[index].agg = value; }),
    }));
  }
  head.appendChild(iconButton(closeGlyph(), "Remove measure", () => change((draft) => { draft.measures.splice(index, 1); })));
  const detail = el("div", "dbMeasureDetail");
  detail.appendChild(textInput({
    value: measure.label || "",
    placeholder: "Label",
    onChange: (value) => change((draft) => { draft.measures[index].label = value.trim(); }),
  }));
  detail.appendChild(pickField({
    options: NUMBER_FORMATS.map((item) => ({ value: item.id, label: item.label })),
    value: measure.format || "auto",
    onChange: (value) => change((draft) => { draft.measures[index].format = value === "auto" ? "" : value; }),
  }));
  card.append(head, detail);
  return card;
}

function filterEditor(filter, index, { table, options, change }) {
  const row = el("div", "dbFilterRow");
  row.appendChild(pickField({
    options: options.dimensions,
    value: filter.field,
    search: true,
    onChange: (value) => change((draft) => { draft.filters[index] = { field: value, values: [] }; }),
  }));
  const values = table ? distinctValues(table, filter.field).map((value) => ({ value: String(value), label: String(value) })) : [];
  row.appendChild(multiPickField({
    options: values,
    values: filter.values.map(String),
    onChange: (next) => change((draft) => { draft.filters[index].values = next; }),
  }));
  row.appendChild(iconButton(closeGlyph(), "Remove filter", () => change((draft) => { draft.filters.splice(index, 1); })));
  return row;
}

export function renderInspector(host, { dashboard, widget, tables, change }) {
  host.replaceChildren();
  if (!widget) {
    host.appendChild(el("div", "dbPanelEmpty", "Select a chart to change it"));
    return;
  }
  const spec = WIDGET_TYPES[widget.type];
  const general = section(host, "");
  general.appendChild(formRow("Title", textInput({
    value: widget.title,
    onChange: (value) => change((draft) => { draft.title = value.trim(); }),
  })));
  general.appendChild(formRow("Type", pickField({
    options: Object.entries(WIDGET_TYPES).map(([value, item]) => ({ value, label: item.label })),
    value: widget.type,
    onChange: (value) => change((draft) => { draft.type = value; }),
  })));

  if (widget.type === "text") {
    const body = section(host, "Text");
    body.appendChild(textInput({
      value: widget.text || "",
      multiline: true,
      placeholder: "# Heading\nA line of text\n- A bullet",
      onChange: (value) => change((draft) => { draft.text = value; }),
    }));
    return;
  }

  const table = tables.get(widget.source) || null;
  const columns = table?.columns || [];
  const options = fieldOptions(columns);
  const shared = { columns, options, table, change };

  const data = section(host, "Data");
  data.appendChild(formRow("Source", pickField({
    options: dashboard.sources.map((source) => ({ value: source.id, label: source.name })),
    value: widget.source,
    placeholder: "Choose a source",
    onChange: (value) => change((draft) => { draft.source = value; }),
  })));
  if (!widget.source) return;
  if (spec.category) {
    data.appendChild(formRow(CATEGORY_LABELS[widget.type] || "Category", pickField({
      options: options.dimensions,
      value: widget.category,
      allowNone: "None",
      search: true,
      onChange: (value) => change((draft) => { draft.category = value; }),
    })));
  }
  if (spec.series) {
    data.appendChild(formRow(SERIES_LABELS[widget.type] || "Break Down By", pickField({
      options: options.dimensions,
      value: widget.series,
      allowNone: "None",
      search: true,
      onChange: (value) => change((draft) => { draft.series = value; }),
    })));
  }

  const measures = section(host, "Measures");
  widget.measures.forEach((measure, index) => measures.appendChild(measureEditor(measure, index, shared)));
  if (widget.measures.length < spec.maxMeasures) {
    const actions = el("div", "dbInlineActions");
    actions.append(
      button("Measure", { small: true, onClick: () => change((draft) => {
        const column = columns.find((item) => item.role === "measure" && !draft.measures.some((used) => used.field === item.name))
          || columns.find((item) => item.role === "measure");
        if (column) draft.measures.push({ field: column.name, agg: defaultAggregation(column) });
      }) }),
      button("Calculation", { small: true, onClick: () => change((draft) => {
        const first = columns.find((item) => item.role === "measure");
        draft.measures.push({ expr: first ? `[${first.name}]` : "", label: "Calculation" });
      }) }),
    );
    measures.appendChild(actions);
  }
  if (widget.series && widget.measures.length > 1 && widget.type !== "scatter") {
    measures.appendChild(el("div", "dbHint", "With a breakdown, only the first measure is drawn."));
  }

  const compare = section(host, "Compare");
  const compareField = widget.compare?.field || "";
  compare.appendChild(formRow("Field", pickField({
    options: options.dimensions,
    value: compareField,
    allowNone: "None",
    search: true,
    onChange: (value) => change((draft) => {
      if (!value) { delete draft.compare; return; }
      const values = distinctValues(table, value).map(String);
      draft.compare = { field: value, base: values[0] || "", target: values[values.length - 1] || "", mode: "delta" };
    }),
  })));
  if (widget.compare) {
    const values = table ? distinctValues(table, compareField).map((value) => ({ value: String(value), label: String(value) })) : [];
    compare.appendChild(formRow("From", pickField({ options: values, value: widget.compare.base, onChange: (value) => change((draft) => { draft.compare.base = value; }) })));
    compare.appendChild(formRow("To", pickField({ options: values, value: widget.compare.target, onChange: (value) => change((draft) => { draft.compare.target = value; }) })));
    compare.appendChild(formRow("Show", pickField({
      options: [{ value: "delta", label: "Change" }, { value: "percent", label: "Percent Change" }],
      value: widget.compare.mode,
      onChange: (value) => change((draft) => { draft.compare.mode = value; }),
    })));
  }

  const filters = section(host, "Filters");
  widget.filters.forEach((filter, index) => filters.appendChild(filterEditor(filter, index, shared)));
  const addFilter = el("div", "dbInlineActions");
  addFilter.appendChild(button("Filter", { small: true, onClick: () => change((draft) => {
    const first = columns.find((item) => item.role !== "measure");
    if (first) draft.filters.push({ field: first.name, values: [] });
  }) }));
  filters.appendChild(addFilter);

  const display = section(host, "Display");
  if (spec.category && widget.type !== "kpi" && widget.type !== "heatmap") {
    const sortValue = widget.sort ? `${widget.sort.by}:${widget.sort.dir}` : "";
    display.appendChild(formRow("Sort", pickField({
      options: [
        { value: "value:desc", label: "Largest First" },
        { value: "value:asc", label: "Smallest First" },
        { value: "category:desc", label: "Reverse Order" },
      ],
      value: sortValue,
      allowNone: "Natural Order",
      onChange: (value) => change((draft) => {
        if (!value) { delete draft.sort; return; }
        const [by, dir] = value.split(":");
        draft.sort = { by, dir };
      }),
    })));
    const limit = textInput({
      value: widget.limit ? String(widget.limit) : "",
      placeholder: "All",
      onChange: (value) => change((draft) => {
        const count = Math.round(Number(value));
        if (count > 0) draft.limit = count; else delete draft.limit;
      }),
    });
    limit.classList.add("dbShortInput");
    display.appendChild(formRow("Show Top", limit));
  }
  for (const [flag, label] of TOGGLES[widget.type] || []) {
    display.appendChild(switchRow(label, widget.options?.[flag], (on) => change((draft) => {
      draft.options = { ...draft.options, [flag]: on };
    })));
  }
  if (!["table", "kpi"].includes(widget.type)) {
    display.appendChild(switchRow("Show As Table", widget.options?.table, (on) => change((draft) => {
      draft.options = { ...draft.options, table: on };
    })));
  }
}

// The Data panel's field list for one source: drag a field onto a chart, or read what is there.
export function renderFieldList(host, source, table, dragType) {
  const list = el("div", "dbFieldList");
  for (const column of table?.columns || []) {
    const row = el("div", "dbField");
    row.draggable = true;
    row.append(icon(column.role === "measure" ? "measure" : "dimension"), el("span", "dbFieldName", column.name));
    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData(dragType, JSON.stringify({ source: source.id, field: column.name, role: column.role }));
      event.dataTransfer.effectAllowed = "copy";
    });
    list.appendChild(row);
  }
  host.appendChild(list);
}
