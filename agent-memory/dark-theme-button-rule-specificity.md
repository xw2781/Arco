---
name: dark-theme-button-rule-specificity
description: "dark.css restyles every button/input via :root[data-arcrho-theme=\"dark\"] :is(...), beating feature class rules; scope feature button rules under the page id"
metadata:
  node_type: memory
  type: project
  originSessionId: 1b9132a3-05e3-4482-b2f2-a03caa4bede7
  modified: 2026-10-20T18:44:01.653Z
---

`frontend/ui/shared/styles/themes/dark.css` has a global rule `:root[data-arcrho-theme="dark"] :is(input, textarea, select, option, button, [contenteditable="true"])` that sets background, border and colour. Its specificity (0,2,1) beats a feature rule like `.dsChartLinkButton` (0,1,0), so in Dark a link-style button grows a filled box and a segmented control loses its "selected" fill — found 2026-10-20 on the Dataset Viewer Chart tab toolbar.

**Why:** light mode looks right, so the bug only shows when the theme is switched; screenshot both themes.

**How to apply:** prefix feature button and input rules with the page id (`#dsChartPage .dsChartSegment button`), which wins in both themes without touching dark.css. Feature-owned colour tokens can carry their own dark values in the feature stylesheet under `:root[data-arcrho-theme="dark"] #pageId { ... }`, avoiding a theme-CSS version bump (see [[theme-css-version-pins]]).
