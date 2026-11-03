---
name: ho-oil-bootstrap-parity-open
description: HO cross-project consolidation work — 2026-10-28 cross-project segments + year alignment built; HO consolidation lives in HPPREF\HO+DF\NJ\Legacy\HOPxCAT+HOL
metadata:
  node_type: memory
  type: project
  originSessionId: ca2f46e9-0377-4d4a-be03-cca0752b3658
  modified: 2026-10-28T15:10:45.347Z
---

Goal (user, 2026-10-27): one Arco Stochastic Consolidation for HO in `NJ_Annual_Prod_2026 Q3-Aug` that replaces the Excel "3Q2026 Reserve Ranges HO Consolidated.xlsm". YTD/through-Aug adjustment and the final report ("3Q2026 Reserve Ranges with Booked.xlsx", HO sheet) stay in Excel.

Done 2026-10-27: F 72 A bootstraps for HOPxCAT, HOL (Aug project) and OIL (Aug Oil project), Oil matching ResQ (zero-cell and excluded-ratio rules, committed 6d09a320 on 2026-10-28).

Done 2026-10-28: a consolidation segment may carry `project_name` (written only when not the host project); segments with fewer origins line up at the latest origin and count as zero elsewhere; `results_tab.output_origin_labels` limits the published vector to the host project's origins. Page: Add Segment → "From another project…". User decisions: host class is `HPPREF\HO+DF\NJ\Legacy\HOPxCAT+HOL` (one consolidation of HOPxCAT + HOL + Oil; no HOPxCAT+HOLxOil class in Arco); no new ResQ-layout export — the existing 0.01% Full Ladder copy/CSV is the table for Excel.

Open: the HOPxCAT–HOL target correlation in ResQ's inner consolidation was never read from ResQ (0 assumed; spreads suggest ~0). AY 2026 means differ from ResQ because ResQ's saved simulations predate the current F 92 (ResQ HO x Oil AY 2026 mean ult 22,990 vs F 92 25,012; Oil 1,743 vs 1,476).

**Why:** the user wants the Excel HO consolidation template retired in favour of one Arco method.
**How to apply:** check the HO consolidation still loads up to date before quoting its numbers; ask the user for the ResQ correlation if it matters.
