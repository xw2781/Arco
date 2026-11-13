# Dashboard Icons

Small glyphs for the Dashboards page: one per widget type, one per field kind, and the few
toolbar actions that carry an icon.

## Contents

- `bar`, `line`, `area`, `scatter`, `heatmap`, `share`, `kpi`, `table`, `text`: one icon per
  widget type. The file name is the widget `type` in the dashboard JSON, so the library and the
  inspector need no lookup table.
- `source`, `dimension`, `measure`: a data source and the two kinds of field it lists.
- `assistant`, `refresh`: toolbar actions.
- `dashboard_icons.css`: the name-to-artwork mapping and the mask mechanics.

## Drawing Rules

The set follows the tab-type icons (`ui/shell/tab-type-icons/README.md`) so the page reads as
part of the same app:

- A `0 0 16 16` canvas, drawn for a 16px box.
- Outline only, `stroke-width` `1.25`, round caps and joins; a fill only for the few solid
  dots and cells that need weight.
- `stroke="currentColor"`, never a literal color.
- About 2 units of clearance inside the canvas edge, and about five elements at most.

## Usage

```html
<link rel="stylesheet" href="./icons/dashboard_icons.css?v=20261113a"/>
<span class="dbIcon" data-db-icon="heatmap" aria-hidden="true"></span>
```

## Adding An Icon

1. Draw the SVG under the rules above and save it as `<name>.svg`.
2. Add the matching `[data-db-icon="<name>"]` rule to `dashboard_icons.css`.
3. Check the set together with `python tools/svg_icon_preview.py frontend/ui/dashboard/icons`.
