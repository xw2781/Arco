---
name: source-column-names-with-spaces
description: Since 2026-10-26 the Engine evaluates dataset-type Sources with spaced column names; a column rename must also touch field mapping, dataset_types Source, and rule source_measure
metadata:
  type: project
---

The Engine computes a dataset type by `eval`-ing its `Source` from dataset_types.json. Until 2026-10-26 that meant every mapped source column had to be a Python identifier; `eval_triangle_formula` now swaps each column name for a placeholder first, so "Earned Premium" works.

A source column rename touches three project files, not one: `field_mapping.json` field_name, the derived `Source` column of `dataset_types.json` (re-derive with `dataset_types_service.resolve_persisted_rows`, the field-mapping save does not do it), and every `target.source_measure` in `data_processing_rules.json`. `data_processing_values.json` rebuilds itself from the mapping.

**Why:** on 2026-10-26 NJ_Annual_Prod_2026 Sep moved to a five-table combined import whose SAS premium/exposure files use spaced names; 242 datasets failed until the four columns were remapped (backup of the old files in tmp_data/sep_remap_backup).

**How to apply:** when an import fails with "does not resolve to any numeric source columns", compare the master table header against field_mapping.json first. The user wants field mapping moved into the import flow so this is caught before the job runs ([[source-refresh-job-diagnosis]]).
