---
name: resq-dfm-mid-period-valuation
description: A ResQ triangle stored at development 12 puts a May valuation's values at ages 12/24/..., so its DFM interpolates a MonthlyPattern and disagrees with Arco on young origins; store it at development 1 (12/1) and both read 5m/17m
metadata:
  type: project
---

Found and fixed 2026-11-09 in step 10 of [[fake-project-refresh]] (Fake project, valuation
202605, annual 12/12 DFMs). Inputs and selected factors were identical in Arco and ResQ, yet a
DFM on a ResQ triangle stored at 12/12 differed on the youngest origins (HOPxCAT F 23 C 2026:
Arco latest x 0.99, ResQ latest x 2.14).

**Why:** stored at development 12, ResQ's columns are ages 12, 24, ... and its DFM labels ratios
"12-24"; it then divides the latest value by `MonthlyPattern(true age)`, a spline
(`InterpolationOptions.Method` 0) through the period-end % developed (`CumulativePattern`). Arco
labels the same columns 5m, 17m, ... ([[triangle-rollup-valuation-anchor]]) and applies the
factors from there, with no interpolation. A triangle stored at development **1** shows the
annual grid at the true ages in ResQ too: the DFM reads "(1) 5-17" and its ultimates match Arco to
the unit. Imported triangles are already stored 1/1, so only hand-written ResQ triangles stored at
12/12 (the Fake project's "Adjusted" ones) were affected.

**How to apply:** write such a triangle as ClearData, show at 12/12, `StoredDevelopmentLength = 1`,
write the annual grid by index (lands at 5m, 17m: rule B2 of
docs/reference/resq_stored_and_display_lengths.md), Save; then re-save the DFMs (the Export macro)
so ResQ's stored outputs follow. `tools/push_fake_values_to_resq.py` does this. Getters used to
diagnose: `dfm.MonthlyPattern(m)`, `CumulativePattern(j)`, `Ultimates(i)`, `DevelopmentLabel(j)`
([[resq-com-probe-dont-call-blindly]]).
