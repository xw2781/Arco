---
name: excel-linked-cells-keep-absolute-position
description: "On a project date change, in-cell formulas linked to Excel stay at their absolute cell position and are never shifted or rewritten"
metadata:
  node_type: memory
  type: feedback
  originSessionId: ecf4b740-051e-40c0-880c-9ba2649ea1d9
  modified: 2026-11-03T20:28:10.654Z
---

When the project dates change and datasets reshape, an in-cell formula linked to an Excel workbook keeps its absolute cell location: no row shift by origin label, no rewrite of its range text.

**Why:** in practice the user retargets the linked workbook (Change Link) to match Arco's new labels, so the link must stay where it is. This differs from hand-entered values and datasets imported from ResQ, whose data follows its true origin label (user decision 2026-11-03, docs/plans/project_dates_panel.md).

**How to apply:** any reshape or date-shift code treats Excel-linked cells as position-fixed. Only hard-coded data (manual entry, imports) moves with origin labels. Related: [[linked-origin-is-the-stored-origin]], [[excel-link-reads-gateway-first]].
