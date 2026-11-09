---
name: resq-dfm-mid-period-valuation
description: At a valuation inside a development period (e.g. May on annual periods) ResQ DFM ultimates = latest / MonthlyPattern(true age), a spline through period-end % developed; Arco applies the factors from the shifted ages (5m, 17m) and disagrees on young origins
metadata:
  type: project
---

Found 2026-11-09 in step 10 of [[fake-project-refresh]] (Fake project, valuation 202605, annual
12/12 DFMs). Inputs and selected factors were identical in Arco and ResQ, yet ultimates differed on
the youngest origins (NJ MP+PIP F 23 C 2026: Arco latest x 1.247, ResQ latest x 2.757).

**ResQ's rule** (read over COM, nothing saved): the DFM treats triangle columns as period-end ages
12, 24, ... and builds `CumulativePattern(j)` (% developed at age 12j, i.e. 1/CDF) from the selected
factors. `MonthlyPattern(m)` (132 points) interpolates that pattern month by month
(`InterpolationOptions.Method` 0, a spline; members BoundedAbove/Below, CubicSplineFlatStart/End,
GogolAdjustment). The ultimate is latest / MonthlyPattern(true age of the latest value), so a
5-month-old origin is grossed up by 1/MonthlyPattern(5) = 2.757, and a 17-month one by
1/MonthlyPattern(17). `FinalPeriodExposureAdjustment` was 0, so that is not the cause.

**Arco's rule**: development labels follow the valuation (5m, 17m, 29m ...; [[triangle-rollup-valuation-anchor]]),
ratios are read as 5-17, 17-29, and the latest value is developed by the product of the factors from
its own column on. No interpolation, so the two agree only where the valuation is a period end.

**Why it matters:** every project valued inside a development period (May on annual, Aug on annual
or a non-quarter-end month on quarterly) differs from ResQ on the latest origins, not just the Fake
project. **How to apply:** before chasing a young-origin DFM difference, compare
`dfm.MonthlyPattern(true_age)` with Arco's factor product; parity needs a product decision on
which rule Arco follows. Probe pattern: `temp/resq_dfm_probe.py`-style getters only
([[resq-com-probe-dont-call-blindly]]).
