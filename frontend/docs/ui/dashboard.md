# Frontend: Dashboard

## Purpose
<!-- MANUAL:BEGIN -->
Dashboards tab: build and view interactive charts over Arco project data, a CSV file, or a SQL query, without code. A dashboard is one file with data sources, pages, and widgets on a grid.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.dashboard.entry_points -->
- `ui/dashboard/dashboard.html`: external scripts `./dashboard_main.js?v=20261113a`, `/ui/shared/services/color_theme.js?v=20260923c`; inline imports _none_.

Detected `arcrho:*` message types in key JS files:
- `arcrho:assistant-ask`
- `arcrho:assistant-context-result`
- `arcrho:dashboard-state`
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.dashboard.key_files -->
- [`ui/dashboard/dashboard.html`](../../ui/dashboard/dashboard.html) - Dashboards tab iframe entrypoint: the dashboard list and the open dashboard's frame.
- [`ui/dashboard/dashboard_main.js`](../../ui/dashboard/dashboard_main.js) - Page state and every change to it: list, open, save, undo, pages, filters, library, data sources, and the ArcBot hooks.
- [`ui/dashboard/dashboard_model.js`](../../ui/dashboard/dashboard_model.js) - The dashboard document: normalization, widget types, grid layout rules, defaults, and the ArcBot view of it.
- [`ui/dashboard/dashboard_data.js`](../../ui/dashboard/dashboard_data.js) - Query engine: filters, grouping, aggregations including latest, calculations, comparisons, and number formats.
- [`ui/dashboard/dashboard_charts.js`](../../ui/dashboard/dashboard_charts.js) - SVG and HTML renderers for every widget type, the shared tooltip, and the table view.
- [`ui/dashboard/dashboard_canvas.js`](../../ui/dashboard/dashboard_canvas.js) - The 12-column canvas: drawing, pointer-captured move and resize, and drops from the library and field lists.
- [`ui/dashboard/dashboard_inspector.js`](../../ui/dashboard/dashboard_inspector.js) - The selected widget's properties as pick lists, text boxes and switches, and the field list.
- [`ui/dashboard/dashboard_sources.js`](../../ui/dashboard/dashboard_sources.js) - Data source dialog for Arco datasets, the Arco source table, a CSV file, or a SQL query.
- [`ui/dashboard/dashboard_controls.js`](../../ui/dashboard/dashboard_controls.js) - App-styled pick lists, modal, prompt and confirm dialogs, and structural glyphs.
- [`ui/dashboard/dashboard_api.js`](../../ui/dashboard/dashboard_api.js) - App-server calls the page makes.
- [`ui/dashboard/dashboard.css`](../../ui/dashboard/dashboard.css) - Page styling on the shared theme tokens, plus the chart colour tokens for Light and Dark.
- [`ui/dashboard/icons/dashboard_icons.css`](../../ui/dashboard/icons/dashboard_icons.css) - Widget-type, field-kind and toolbar icon mapping.
- [`app_server/services/dashboard_service.py`](../../app_server/services/dashboard_service.py) - Dashboard files, the library, and loading a data source into a table.
- [`app_server/services/dashboard_data_service.py`](../../app_server/services/dashboard_data_service.py) - Project data as flat tables; the two Server-hosted dashboard reads.
- [`app_server/default_dashboards/library.json`](../../app_server/default_dashboards/library.json) - The built-in library of widgets and chart templates.
- [`../tools/build_sample_dashboards.py`](../../../tools/build_sample_dashboards.py) - Rebuilds the sample dashboards that ship with the app.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Opened from the Home Dashboards card as a restorable `dashboard` shell tab, one tab per dashboard file. A tab with no file shows the list: the user's dashboards and the samples.
- Calls the `/dashboard/*` routes ([app-server domain](../app_server/domains/dashboard.md)) and the existing listings `/arcrho/projects`, `/reserving_class_paths_with_data`, `/datasets/cached`, `/sqlserver/connections` and `/snowflake/connections`.
- Shell messages. The page posts `arcrho:dashboard-state` `{path, title, dirty}` whenever its file, name or unsaved state changes; the shell uses it for the tab title, the unsaved-changes prompt on close, and browsing history. The shell posts `arcrho:dashboard-save` and `arcrho:dashboard-save-as` for File > Save, Save As and Ctrl+S. `arcrho:dashboard-open` `{path}` opens a dashboard file in its own tab.
- **View and Edit.** View is the dashboard in use: tooltips, the filter row, and a click on a bar, point, cell or table row filters the other charts on the page to that value (a chip in the filter row clears it). Edit adds the Library and Data panels on the left and the inspector on the right.
- **No-code building.** Drag a library item onto the canvas, or click it to place it in the first free cell. Drag a widget by its header and resize it from its corner; both capture the pointer on the handle and snap to the 12-column grid, and the other widgets move out of the way and close gaps. Drag a field from the Data panel onto a chart: a number becomes a measure, any other field the category, then the breakdown. Every property is a pick list, a text box or a switch in the inspector. Undo and Redo cover every edit.
- **Widget types** (`WIDGET_TYPES`): `bar` (grouped, stacked, horizontal), `line`, `area`, `scatter` (two measures, one point per category), `heatmap` (two fields and one measure), `share` (one whole split into its largest six parts), `kpi` (a number tile with an optional trend and change), `table`, and `text`. Any chart can be shown as its table from the widget menu.
- **Measures.** A measure is a field with an aggregation (`sum`, `latest`, `avg`, `min`, `max`, `count`) or a calculation over aggregated fields such as `latest([Net Loss--Paid]) / sum([Earned Premium])`. **Compare** charts the change, or percent change, in every measure between two values of a field, which is how two projects (two valuations) are set against each other.
- **Library.** Built-in charts, widgets and reserving templates come from the shipped `library.json`. Save to Library on a widget's menu stores it, with its fields and options, as one file per item under `dashboards\library`; a template dropped on a source that lacks its fields falls back to that source's first fields.
- **ArcBot.** The page answers `arcrho:assistant-context-request` with the dashboard document (without its saved tables, each source listing its fields instead), a short guide to the document, and the rows every chart on the open page is showing, so ArcBot can summarize what the page shows and gather more through its project reads. In Edit Mode ArcBot returns an edited document; the page applies it through `arcrho:assistant-apply-json-edit` as one undoable, unsaved change and refreshes any source the edit added, and `arcrho:assistant-revert-json-edit` undoes it while it is still the latest change. Ask ArcBot and a widget's Explain with ArcBot post `arcrho:assistant-ask` `{prompt}`, which opens ArcBot with the question in its composer for the user to send.
- **Chart rules.** One value axis per chart, never two. A breakdown beyond eight series folds the smallest into Other. Series colours are assigned in a fixed order from the `--db-series-*` tokens, with Dark values chosen for the Dark surface; both sets pass the palette validator's lightness, chroma, colour-vision and normal-vision checks against the app's Light (`#ffffff`) and Dark (`#282c34`) surfaces. Magnitude uses one hue, a change uses two around a neutral middle. A legend appears for two or more series, text never takes a series colour, and the tooltip and table view carry every value.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- A dashboard is a `.arcdash` JSON file in the user's `Documents\ArcRho\dashboards` folder; samples ship read-only with the app, and saving one writes a copy to the user's folder.
- Document shape (`normalizeDashboard` is the owner): `{format: "arco-dashboard", version, name, description, sources: [...], pages: [{id, name, filters: [{field, values}], widgets: [...]}]}`. A widget is `{id, type, title, layout: {x, y, w, h}, source, category, series, measures, filters, compare, sort, limit, options}`.
- A source is one of four kinds: `arco_datasets` (`projects`, `reserving_classes`, `datasets`, optional `level_names`), `arco_source_table` (`projects`, `dimensions`, `measures`), `csv` (`path`, optional `dimensions` and `measures`), and `sql` (`engine`, `connection`, `sql`). `projects` is a list of `{name, label}`; with more than one, every row carries its project's label in the `Project` field.
- Each source keeps the last table it returned in `extract`, so a dashboard opens with its charts drawn and without waiting for the server. Refresh Data reads every source again; a source with no saved table is read when the dashboard opens.
- An `arco_datasets` table has one row per reserving class, origin and development period and one number field per dataset. A cumulative triangle field defaults to the `latest` aggregation: the newest development period of each origin, totalled. Datasets are read at the period each is stored at, so `Origin Year` is the grouping annual, quarterly and monthly datasets share.
- Filter choices are saved with the dashboard; a value clicked on a chart is not.
- The samples are rebuilt from live project data with `tools/build_sample_dashboards.py`.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Add a widget type: `WIDGET_TYPES` in `dashboard_model.js`, a renderer in `dashboard_charts.js`, an icon, and a library entry.
2. Add an aggregation or format: `dashboard_data.js`, the lists in `dashboard_model.js`, and `tests/dashboard_data.test.mjs`.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A cumulative triangle column must be aggregated with `latest`, never summed across development periods.
- Charts keep one axis and at most eight series; do not add a second y-axis.
<!-- MANUAL:END -->
