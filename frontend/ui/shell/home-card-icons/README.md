# Home Card Icons

Artwork for the launch cards on the Home page, one file per card kind.

## Contents

- `*.svg`: one icon per card kind. The file name is the kind `home_card_icons.js` renders.
- `shortcut.svg`: the fallback glyph for a kind with no rule in the stylesheet.
- `home_card_icons.css`: the kind-to-artwork mapping and the mask mechanics.

Older card kinds still carry their path data in `ui/shell/home_card_icons.js`, which predates
the rule that artwork lives in files. Add new kinds here, and move an older one here when its
drawing is next revised.

## Drawing Rules

- A `0 0 24 24` canvas, drawn for the 34px box a card gives it.
- Outline only, `stroke-width` `1.8`, round caps and joins.
- `stroke="currentColor"`, never a literal color. The card's accent comes from
  `.homeIconBox.<kind>` in `shell.css`.
- About 3 units of clearance inside the canvas edge, and no more than about five elements.
- The same subject as the matching tab icon in `ui/shell/tab-type-icons/`, so a page looks
  like itself on its card and on its tab.

## Adding An Icon

1. Draw the SVG under the rules above and save it as `<kind>.svg`.
2. Add the `[data-home-icon="<kind>"]` rule to `home_card_icons.css`.
3. Add the kind to `FILE_ICON_KINDS` in `ui/shell/home_card_icons.js`, and its accent color to
   `shell.css`.
