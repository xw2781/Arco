---
name: resq-custom-average-api
description: "ResQ DFM average rows expose their real type and formula through CustomAverages; the Formula property is stale on rows that are not User Calculation, so always gate on AverageType"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 427fe4bc-9ba5-45c6-b0bf-80c94a582f26
  modified: 2026-08-31T20:04:15.344Z
---

A ResQ DFM's ratio average rows are readable one by one as `dfm.CustomAverages(i)` (1-based), with `dfm.RatioAverageCount` giving the row count — no probing needed. Each row exposes `Name`, `AverageType`, `Formula`, `PeriodsIncluded`, `PeriodInclusionRule`, `ExcludeHighLow2`, `WeightType` (0 simple, 1 volume), `MiddlePeriods`, `MiddleEliminationRule`, `SmoothingType`, `TailFactor`, `ExponentialWeight`.

`AverageType` is a plain integer in the manual's listed order: **0 atCustom, 1 atMedian, 2 atGeoMean, 3 atMin, 4 atMax, 5 atUserEntry, 6 atCalculated, 7 atPriorAnalysis, 8 atPattern, 9 atBenchmark.** "User Calculation" in the ResQ dialog is `atCalculated` (6) — *not* `atBenchmark`, whatever the row happens to be named.

**The trap: `Formula` is stale on rows whose type is not 6.** In the fake project's HOL class (seen 2026-08-31, before the 2026-11 refresh re-exported its methods), `C 12 - CWP DFM w/ Selected LDFs` row 7 ("Simple - 5 Ex hi/lo", type 0) and row 10 ("User Entry", type 5) both carry leftover `Average(...)` text that ResQ ignores. The automation help says the formula "only has any effect if the average type is set to atCalculated", so **gate on `AverageType == 6`, never on the formula being non-empty**. A row named "Benchmark" is likewise no evidence of anything — read the type.

A calculated formula may contain only scalars, `+ - * /`, parentheses, and `Average(<1-based row>)` references to other rows in the same column. That maps one-for-one onto an ArcRho User Entry cell formula, which names another summary row by quoting its label (`=("Simple - 5"+"Simple - 3")/2`).

Unlike `DatasetType.Calculated`, these properties read correctly under plain late-binding `Dispatch`, which is what the Bridge uses — verified 2026-08-31 against both bindings. Contrast [[resq-com-probe]], where late binding silently lies.

**The decompiled ResQ automation help is on the server at `E:\XWSpace\ResQ API Doc\reference\resq_help_manual_decompiled\html\`** — one HTML page per member (`xCustomAverage_*.htm`, `xDFMMethod_*.htm`, `DFM_Ratio_Averages.htm`). Strip the tags and read it before probing COM; it answers most API questions faster than a live session, and `E:\XWSpace\ResQ API Doc\reference\ResQToolBox2.py` shows real call sites.

**Why:** the ArcRho import used to infer every average row's settings from its *name*, which silently mis-typed the house "Benchmark" row as a frozen benchmark instead of a live calculation. Related: [[resq-benchmark-row-imports-as-user-entry]], [[arcrho-dataset-types-win-over-resq]].
