---
name: fake-202608-is-a-roll-forward-of-202605
description: "2026-11-13: NJ_Annual_Prod_202608_Fake reads a source that continues the 202605 Fake table by three months (generator --roll-forward-from); its methods and prior-quarter inputs were NOT rebuilt"
metadata:
  node_type: memory
  type: project
  originSessionId: 1b99a8a9-1617-4690-9f04-35c11b44a92a
  modified: 2026-11-13T17:15:59.291Z
---

On 2026-11-13 the user asked for the 202608 Fake project's data to be made reasonable for a quarter-over-quarter dashboard demo. Before that it read a dead "combined" source (three CSVs under a clone path that no longer exists) on about 1/40th of 202605's scale.

- **Source.** `\\NE7SASWPN02\E\ResQ\IBNR_SQL_Codes\202608\ResQ_Channel_202608_Fake_3.csv`, written by `py -3.10 tools/generate_fake_project_source.py --template <202605 ..._Fake_2.csv> --roll-forward-from 202605 --valuation 202608`. Every row through May is byte-identical to the 202605 table; June to August add development, new accident months and premium. The template must be the original `ResQ_Channel_202605_Fake_2.csv`: only that reproduces the 202605 table byte for byte.
- **Applied through the app server**: `POST /source_table/profile` (csv) then `POST /source_table/refresh_job` (job `dashdemo-56f1d7c34ade`), about 2.5 minutes per reserving class, 34 classes.
- **Result.** 233,745 rows imported, 32 of 32 classes and 1,288 engine datasets regenerated, 372 methods updated. The job still ends as `error` because methods in about ten classes refused to recalculate on the new data (stale exclusions, mixed period lengths, blocked dependents); its status JSON lists them.
- **Not done.** Method selections, exclusions and the prior-quarter inputs (`F 81`/`F 82` and their C and G twins) in 202608 were set on the old data and were not reset; the 202605 clean-up took plan steps 6-8, 12 and 13 of [docs/plans/completed/fake_project_refresh.md](docs/plans/completed/fake_project_refresh.md). Selected ultimates in 202608 may therefore still be implausible; the shipped dashboard sample compares only source-built datasets (paid, incurred, counts, premium).

**Why:** a later session comparing the two Fake valuations should know which figures line up and which do not.

**How to apply:** treat paid, incurred, claim counts and premium as comparable between the two Fake projects; check a method output before quoting it. Rebuild the samples after any change with `py -3.10 tools/build_sample_dashboards.py --on-server`. Related: [[abc-demo-project-build]], [[fake-ma-bi-total-f63-test-class]].
