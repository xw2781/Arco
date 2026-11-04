---
name: abc-demo-project-build
description: "2026-11-04: the general demo project is ABC_Group_Quarterly_Review_202608 (Test\\Demos), built by tools/build_abc_group_demo_project.py from 202608_Fake templates; Monthly_Insurance_Dataset was deleted; pitfalls of copying template classes"
metadata:
  node_type: memory
  type: project
  originSessionId: 1f17b373-c95a-4ad2-af0a-7a7d24fffc3d
  modified: 2026-11-04T19:52:33.101Z
---

Since 2026-11-04 the general-purpose demo is `ABC_Group_Quarterly_Review_202608` under `Test\Demos` (Server PC production root). `Monthly_Insurance_Dataset` and its toolkit were deleted at the user's request; the user manual text was retargeted but its screenshots in `assets/monthly-insurance/` still show the old project.

- Source: four tables from the shipped, seeded generator `arcrho_api.demo_data.abc_group` (stored in the project's `source/import_tables`, imported as one combined source).
- Build: `tools/build_abc_group_demo_project.py` steps `scaffold templates inputs refresh methods finish` (plus `inputs --triangles-through-app`, `methods --rs-only`). Re-running from scratch: delete the `data\ABC*` class folders first.

- Volatility (added 2026-11-04 after the user saw a 5% bootstrap CV): independent claim noise averages out, so the generator carries shared shocks (`Shocks`, keyed per accident/calendar year and month) plus a Pareto large-loss share; tuned so factor spreads sit near the real-data template (PD 8-20 sd ~0.06, BI NY 20-32 ~0.09). Re-measure against the template before retuning.
- COVID-19 pattern in PPA/MC (user request): 2020 frequency drop, 15% Apr-May 2020 premium payback, court-closure delays on BI/UM closes Apr 2020-Jun 2021, severity bump, theft wave; vehicle DFMs exclude AY 2020 factors where 3+ others remain.

**Pitfalls found while copying template classes (each cost a refresh cycle):**
- Renaming anything in a DFM payload breaks `owned_revision`; restamp through `recalculate_dfm_method` / the BF and CC recalculators.
- Writing a hand-entered dataset straight to disk starts no dependents walk, and a DFM save never re-reads its input; save inputs through `/dataset/sidecar/save`.
- Hand-entered triangles need sidecar `development_labels` for the new valuation and the Engine's square width (columns = origins); dev ages count back from the valuation (8, 20, 32... at August).
- A hand-entered vector or triangle cannot be rolled up for a reader at another length; store it at the reader's length.
- Template Result Selections carry `ultimate_overrides` that silently beat the weights.
- Project name length + the 41-char `.uuid4.tmp` suffix: class names were kept short to stay under 260 chars.

Related: [[fake-project-refresh]] [[bulk-method-restatement-hold]] [[triangle-rollup-valuation-anchor]]
