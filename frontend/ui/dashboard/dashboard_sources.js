// The data source dialog: connect a dashboard to Arco projects, a CSV file, or a SQL query.
//
// Whatever the kind, the dialog ends the same way: it loads the table once, so the user sees the
// row count before the source is added, and hands back the source with that table attached.

import { api } from "./dashboard_api.js";
import { button, el, formRow, multiPickField, openModal, pickField, textInput } from "./dashboard_controls.js";

const KINDS = [
  { id: "arco_datasets", label: "Arco Datasets" },
  { id: "arco_source_table", label: "Arco Source Table" },
  { id: "csv", label: "CSV File" },
  { id: "sql", label: "SQL Query" },
];
const DATE_PARTS = [["year", "Year"], ["quarter", "Quarter"], ["month", "Month"]];

function hostApi() {
  return window.ADAHost || window.parent?.ADAHost || null;
}

function dimensionOptions(columns) {
  const options = [];
  for (const column of columns) {
    options.push({ value: column.name, label: column.name });
    if (column.date_role) {
      for (const [part, label] of DATE_PARTS) options.push({ value: `${column.name}:${part}`, label: `${column.name} ${label}`, tag: "Date" });
    }
  }
  return options;
}

// One row per chosen project: its name and the label its rows carry in charts.
function projectEditor(draft, projects, redraw) {
  const wrap = el("div", "dbProjectList");
  draft.projects.forEach((project, index) => {
    const row = el("div", "dbProjectRow");
    row.appendChild(el("span", "dbProjectName", project.name));
    const label = textInput({
      value: project.label === project.name ? "" : project.label,
      placeholder: "Label in charts",
      onChange: (value) => { draft.projects[index].label = value.trim() || project.name; },
    });
    row.appendChild(label);
    wrap.appendChild(row);
  });
  const picker = multiPickField({
    options: projects.map((name) => ({ value: name, label: name })),
    values: draft.projects.map((project) => project.name),
    placeholder: "Choose projects",
    summary: (values) => (values.length ? `${values.length} project${values.length === 1 ? "" : "s"}` : "Choose projects"),
    onChange: (names) => {
      draft.projects = names.map((name) => draft.projects.find((project) => project.name === name) || { name, label: name });
      redraw();
    },
  });
  return { picker, wrap };
}

export function openSourceDialog({ source = null, existingNames = [] }) {
  return new Promise((resolve) => {
    let result = null;
    const modal = openModal({ title: source ? "Edit Data Source" : "Add Data Source", wide: true, onClose: () => resolve(result) });
    const draft = source
      ? JSON.parse(JSON.stringify({ ...source, extract: undefined }))
      : { kind: "arco_datasets", name: "", projects: [], reserving_classes: [], datasets: [], level_names: [], dimensions: [], measures: [], path: "", engine: "sqlserver", connection: "", sql: "" };
    draft.projects ||= [];
    draft.dimensions ||= [];
    draft.measures ||= [];
    const cache = { projects: null, classes: new Map(), datasets: new Map(), fields: new Map(), connections: new Map() };
    let table = null;
    let token = 0;

    const tabs = el("div", "dbSegment");
    const form = el("div", "dbSourceForm");
    const status = el("div", "dbSourceStatus");
    modal.body.append(tabs, form, status);
    const loadButton = button("Load Data", { onClick: () => void load() });
    const saveButton = button(source ? "Save" : "Add", { primary: true, onClick: () => finish() });
    modal.footer.append(button("Cancel", { onClick: modal.close }), loadButton, saveButton);

    function invalidate() {
      table = null;
      status.textContent = "";
      modal.setError("");
    }

    function definition() {
      const next = { id: source?.id || "", name: draft.name.trim(), kind: draft.kind };
      if (draft.kind === "arco_datasets") {
        Object.assign(next, { projects: draft.projects, reserving_classes: draft.reserving_classes, datasets: draft.datasets, level_names: draft.level_names });
      } else if (draft.kind === "arco_source_table") {
        Object.assign(next, { projects: draft.projects, dimensions: draft.dimensions, measures: draft.measures });
      } else if (draft.kind === "csv") {
        Object.assign(next, { path: draft.path.trim(), dimensions: draft.dimensions, measures: draft.measures });
      } else {
        Object.assign(next, { engine: draft.engine, connection: draft.connection, sql: draft.sql });
      }
      return next;
    }

    async function load() {
      modal.setError("");
      status.textContent = "Loading...";
      loadButton.disabled = true;
      const mine = ++token;
      try {
        const loaded = await api.loadSource(definition());
        if (mine !== token) return null;
        table = loaded;
        const parts = [`${loaded.row_count.toLocaleString()} rows`, `${loaded.columns.length} fields`];
        if (loaded.truncated) parts.push("cut at the row limit");
        if (loaded.missing?.length) parts.push(`${loaded.missing.length} dataset${loaded.missing.length === 1 ? "" : "s"} not found in some classes`);
        status.textContent = parts.join(" \u00b7 ");
        return loaded;
      } catch (error) {
        if (mine !== token) return null;
        status.textContent = "";
        modal.setError(String(error.message || error));
        return null;
      } finally {
        if (mine === token) loadButton.disabled = false;
      }
    }

    async function finish() {
      if (!draft.name.trim()) return modal.setError("Give the data source a name.");
      if (existingNames.includes(draft.name.trim())) return modal.setError("Another data source already has this name.");
      const loaded = table || await load();
      if (!loaded) return;
      result = { ...definition(), extract: loaded };
      modal.close();
    }

    async function cached(map, key, fetcher) {
      if (!map.has(key)) map.set(key, fetcher().catch((error) => { map.delete(key); throw error; }));
      return map.get(key);
    }

    function fail(error) {
      modal.setError(String(error.message || error));
    }

    async function drawProjectSource(pane) {
      if (!cache.projects) cache.projects = api.projects();
      let projects = [];
      try { projects = await cache.projects; } catch (error) { cache.projects = null; fail(error); }
      const editor = projectEditor(draft, projects, () => { invalidate(); void draw(); });
      pane.appendChild(formRow("Projects", editor.picker));
      if (draft.projects.length) pane.appendChild(formRow("", editor.wrap));
      const first = draft.projects[0]?.name;
      if (!first) return;

      if (draft.kind === "arco_datasets") {
        let classes = [];
        try { classes = await cached(cache.classes, first, () => api.reservingClasses(first)); } catch (error) { fail(error); }
        pane.appendChild(formRow("Reserving Classes", multiPickField({
          options: classes.map((name) => ({ value: name, label: name })),
          values: draft.reserving_classes,
          placeholder: "Choose reserving classes",
          summary: (values) => (values.length ? `${values.length} of ${classes.length} classes` : "Choose reserving classes"),
          onChange: (values) => { const hadNone = !draft.reserving_classes.length; draft.reserving_classes = values; invalidate(); if (hadNone || !values.length) void draw(); },
        })));
        const sample = draft.reserving_classes[0];
        if (!sample) return;
        let files = [];
        try { files = await cached(cache.datasets, `${first}\u0001${sample}`, () => api.datasets(first, sample)); } catch (error) { fail(error); }
        pane.appendChild(formRow("Datasets", multiPickField({
          options: files.map((file) => ({ value: file.name, label: file.name, tag: file.data_format || "" })),
          values: draft.datasets,
          placeholder: "Choose datasets",
          summary: (values) => (values.length ? `${values.length} dataset${values.length === 1 ? "" : "s"}` : "Choose datasets"),
          onChange: (values) => { draft.datasets = values; invalidate(); },
        })));
        pane.appendChild(formRow("Level Names", textInput({
          value: draft.level_names.join(", "),
          placeholder: "Company, Product, State, Channel, Coverage",
          onChange: (value) => { draft.level_names = value.split(",").map((item) => item.trim()).filter(Boolean); invalidate(); },
        })));
        return;
      }
      await drawGrouping(pane, `project:${first}`, { kind: "arco_source_table", projects: [{ name: first, label: first }] }, true);
    }

    // Group By and Totals for a table source. A project table must be grouped; a CSV may be
    // left as its own rows.
    async function drawGrouping(pane, key, fieldSource, required) {
      let columns = [];
      try { columns = (await cached(cache.fields, key, () => api.sourceFields(fieldSource))).columns || []; } catch (error) { return fail(error); }
      pane.appendChild(formRow("Group By", multiPickField({
        options: dimensionOptions(columns),
        values: draft.dimensions,
        placeholder: required ? "Choose fields" : "Keep every row",
        summary: (values) => (values.length ? values.map((value) => value.replace(":", " ")).join(", ") : (required ? "Choose fields" : "Keep every row")),
        onChange: (values) => { draft.dimensions = values; invalidate(); },
      })));
      pane.appendChild(formRow("Totals", multiPickField({
        options: columns.filter((column) => column.type === "number").map((column) => ({ value: column.name, label: column.name })),
        values: draft.measures,
        placeholder: "Choose numbers to total",
        summary: (values) => (values.length ? `${values.length} number${values.length === 1 ? "" : "s"}` : "Choose numbers to total"),
        onChange: (values) => { draft.measures = values; invalidate(); },
      })));
    }

    async function drawCsv(pane) {
      const row = el("div", "dbPathRow");
      const input = textInput({
        value: draft.path,
        placeholder: "C:\\Data\\claims.csv",
        onChange: (value) => { draft.path = value; draft.dimensions = []; draft.measures = []; invalidate(); void draw(); },
      });
      row.appendChild(input);
      const host = hostApi();
      if (host?.pickOpenFile) {
        row.appendChild(button("Browse...", { onClick: async () => {
          const picked = await host.pickOpenFile({ filters: [{ name: "CSV Files", extensions: ["csv", "txt"] }] });
          if (!picked) return;
          draft.path = picked;
          draft.dimensions = [];
          draft.measures = [];
          if (!draft.name) draft.name = picked.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
          invalidate();
          void draw();
        } }));
      }
      pane.appendChild(formRow("File", row));
      if (draft.path.trim()) await drawGrouping(pane, `csv:${draft.path.trim()}`, { kind: "csv", path: draft.path.trim() }, false);
    }

    async function drawSql(pane) {
      pane.appendChild(formRow("Database", pickField({
        options: [{ value: "sqlserver", label: "SQL Server" }, { value: "snowflake", label: "Snowflake" }],
        value: draft.engine,
        onChange: (value) => { draft.engine = value; draft.connection = ""; invalidate(); void draw(); },
      })));
      let connections = { names: [], fallback: "" };
      try { connections = await cached(cache.connections, draft.engine, () => api.connections(draft.engine)); } catch (error) { fail(error); }
      if (!draft.connection) draft.connection = connections.fallback || connections.names[0] || "";
      pane.appendChild(formRow("Connection", pickField({
        options: connections.names.map((name) => ({ value: name, label: name })),
        value: draft.connection,
        placeholder: connections.names.length ? "Choose a connection" : "Add a connection in Arcode first",
        onChange: (value) => { draft.connection = value; invalidate(); },
      })));
      pane.appendChild(formRow("Query", textInput({
        value: draft.sql,
        multiline: true,
        mono: true,
        placeholder: "SELECT State, AccidentYear, SUM(Paid) AS Paid\nFROM dbo.Claims\nGROUP BY State, AccidentYear",
        onChange: (value) => { draft.sql = value; invalidate(); },
      })));
    }

    let drawing = 0;
    async function draw() {
      const mine = ++drawing;
      tabs.replaceChildren();
      for (const kind of KINDS) {
        const tab = el("button", kind.id === draft.kind ? "active" : "", kind.label);
        tab.type = "button";
        tab.disabled = !!source && kind.id !== draft.kind;
        tab.addEventListener("click", () => { if (draft.kind !== kind.id) { draft.kind = kind.id; draft.dimensions = []; draft.measures = []; invalidate(); void draw(); } });
        tabs.appendChild(tab);
      }
      // Each draw fills its own pane and shows it only if no later draw has started, so a slow
      // answer for an earlier choice can never draw over a later one.
      const pane = el("div", "dbSourcePane");
      pane.appendChild(formRow("Name", textInput({ value: draft.name, placeholder: "Reserve datasets", onChange: (value) => { draft.name = value; } })));
      if (draft.kind === "csv") await drawCsv(pane);
      else if (draft.kind === "sql") await drawSql(pane);
      else await drawProjectSource(pane);
      if (mine === drawing) form.replaceChildren(pane);
    }

    void draw();
  });
}
