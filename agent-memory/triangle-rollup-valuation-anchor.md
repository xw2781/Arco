---
name: triangle-rollup-valuation-anchor
description: "A coarser view counts development periods back from the Development End Date, except a hand-entered triangle kept from an earlier valuation, read by position (2026-10-26) (ResQ's 8m/20m/32m labels), so rollup_triangle needs valuation_months and service tests with a fake project must patch get_general_settings_path"
metadata: 
  node_type: memory
  type: project
  originSessionId: 944c6b93-0786-4e77-8b7b-978ffae46444
  modified: 2026-09-06T19:40:28.097Z
---

Fixed 2026-09-06: a ResQ-imported triangle stored at 12/1 and shown at 12/12 (NJ_Annual_Prod_2026 Q3-Aug, HOL "Net Loss--Incurred Adjusted*") showed zeros and lost its latest diagonal, because `arcrho_api.triangle_rollup` read the 12th, 24th, ... stored columns and sized the view as `columns // 12`. ArcRho's own geometry (`dataset_service._empty_dataset_geometry_from_general_settings`) values every row's newest cell on the Development End Date, so in a project valued at August a yearly view is at 8, 20, 32, ... 116 months of age (the labels ResQ shows) and the first development period is the short one. `rollup_triangle` now takes `valuation_months` (months from Origin Start Date through Development End Date, `dataset_service.valuation_months(project_name)`), phases each row as `(last_month - row_start) % development_length`, and has `E // target_dev + 1` columns and `ceil(rows / origin_factor)` rows. Calendar-aligned (and vector) roll-ups stay positional: columns run forward from the anchor and the last period is the short one.

**Why:** the stored CSV holds no figure at 12, 24, ... months in an August-valued project, and ResQ reshapes a stored 12/1 triangle to any display length by counting back from the evaluation date; the import already writes both display and stored lengths, the display arithmetic was the only gap.

**How to apply:** every caller of `rollup_triangle` / `precedent_cache_service.rollup_rows(project_name, ...)` needs the project's General Settings, so a service test that rolls up under a fake project must write a `general_settings.json` and patch `config.get_general_settings_path` (see `frontend/tests/test_manual_dataset_rollup_view.py`); a 24-month fixture valued on a period boundary keeps the old expectations. Related: [[origin-length-is-not-row-count]], [[arcrho-dataset-types-win-over-resq]].

**Positional exception (user rule, 2026-10-26):** a hand-entered triangle carried into a project valued a month later (Sep project holding Aug-valued 116-column adjusted triangles) is read by cell position, not by label. `dataset_service.rollup_valuation_months` anchors on the stored width (`width * stored_dev`) whenever it differs from the project grid's width; otherwise the project valuation is unchanged. Used by `rollup_rows`, the dataset-window roll-up handle, and the ArcRhoTri input roll-up. Scatter (writing at a coarse view) still uses the project valuation, so an edit re-stores the triangle at the current valuation.
