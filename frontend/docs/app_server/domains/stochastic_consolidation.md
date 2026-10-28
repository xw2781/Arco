# App Server Domain: stochastic_consolidation

## Purpose
<!-- MANUAL:BEGIN -->
Load, run, and save a Stochastic Consolidation, which combines the simulated reserves of several Bootstrap methods ("segments") into one total distribution. The segments live in other reserving classes and are named by class path and method name; a segment that also names a `project_name` lives in that other project. The consolidation never reads its host class's datasets. Every number comes from `python-api/src/arcrho_api/stochastic_consolidation_contract.py`; the service only reads, checks, and publishes.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.stochastic_consolidation.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/stochastic-consolidation/consolidate` | `consolidate_stochastic_consolidation` | `StochasticConsolidationRunRequest` | [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) | `stochastic_consolidation_service.consolidate_stochastic_consolidation_method`, `workspace_read_client.run_workspace_read` |
| `POST` | `/stochastic-consolidation/load` | `load_stochastic_consolidation` | `StochasticConsolidationIdentityRequest` | [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) | `stochastic_consolidation_service.load_stochastic_consolidation_method`, `workspace_read_client.run_workspace_read` |
| `POST` | `/stochastic-consolidation/save` | `save_stochastic_consolidation` | `StochasticConsolidationSaveRequest` | [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) | `engine_hosted_save_service.run_hosted_save` |
| `POST` | `/stochastic-consolidation/save/plan` | `plan_stochastic_consolidation_save` | `StochasticConsolidationSaveRequest` | [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) | `engine_hosted_save_service.run_hosted_save_plan` |
| `POST` | `/stochastic-consolidation/segments/candidates` | `list_stochastic_consolidation_candidates` | `StochasticConsolidationClassRequest` | [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) | `stochastic_consolidation_service.list_stochastic_consolidation_candidates`, `workspace_read_client.run_workspace_read` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.stochastic_consolidation.key_files -->
- [`app_server/api/stochastic_consolidation_router.py`](../../../app_server/api/stochastic_consolidation_router.py) - Stochastic Consolidation load/consolidate/candidates/save routes.
- [`app_server/services/stochastic_consolidation_service.py`](../../../app_server/services/stochastic_consolidation_service.py) - Cross-class segment reads, freshness report, run without writing, and transactional publication.
- [`app_server/schemas/stochastic_consolidation.py`](../../../app_server/schemas/stochastic_consolidation.py) - Stochastic Consolidation identity, run, picker and revision-aware save request models.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Used by the Stochastic Consolidation method page.
- **Load** (`stochastic_consolidation_load`, hosted read) returns the method JSON and its output sidecar, validated as a pair, plus one `segments` row per included bootstrap: class, method, factor, `status` (`current`, `changed`, `missing`, or `not_consolidated`), the bootstrap's simulation count, seed, base triangle type (its DFM's input triangle), standalone scaled mean, standard deviation and CV, and `problems` (`missing`, `no_run`, `simulation_count_mismatch`, `base_type_mismatch`) for the row to show inline. `stale_segments` lists the non-current rows and `run_state` is `up_to_date`, `not_run`, `inputs_changed` (the run's own settings moved since `results_tab.input_revision`), or `segment_changed`.
- **Consolidate** (`stochastic_consolidation_consolidate`, hosted read) runs the page's current settings: it re-simulates every segment from its bootstrap's seed and combines them. It writes nothing; the route drops `results_tab` from the request because a run rebuilds it. A missing segment is refused with 404 and a mismatched base type or simulation count with 422, each naming `class / method`.
- **Segment picker** (`stochastic_consolidation_candidates`, hosted read) lists every Bootstrap in the project's other reserving classes with the same figures as a segment row. With `source_project_name` it lists every Bootstrap in that project instead, each row carrying its `project_name`; the page reaches it through Add Segment's "From another project…".
- **Segments from another project.** A segment's optional `project_name` is written only when it is not the host project, so a same-project consolidation keeps its shape and revisions. Its bootstrap (and DFM) is read from that project, its identity is project, class and method, and its sidecar precedent carries `project` beside `reserving_class`.
- **Different accident years.** Segments line up at their latest origin; one with fewer origins must hold the latest origins of the longest and counts as zero in the others (ResQ refuses this). `results_tab.origin_labels` and the summary keep every origin, and `results_tab.output_origin_labels` names the latest origins the output vector publishes: the longest host-project segment's, or every origin when no segment is in the host project. The output CSVs, the sidecar's `origin_labels` and the publication revision use only those rows, because the host project's datasets have only those origins.
- **Save** and **save/plan** are the `stochastic_consolidation_method` hosted save. Save is revision-aware like every method (a stale owned revision is 409; derived state rebases). It consolidates again whenever there is no stored run, the run's settings changed, or any segment is not current, so a saved consolidation always publishes the run of its saved inputs; a notes-only save keeps the stored run (`consolidated: false`). The method JSON and CSVs are written first and the sidecar last, with rollback on failure.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- The method file is `methods/SCON@<Name>.json` (`arcrho-stochastic-consolidation-v4`); the output vector is the consolidated mean ultimate by origin, with aggregated 3/6/12 variants.
- Simulations are never persisted, for the consolidation or its segments: each run rebuilds them from the seeds, and the method keeps a summary rich enough for every Results view.
- Each segment records the revision of the bootstrap it consumed (`bootstrap_revision`), which is how the load tells a changed segment.
- The output sidecar lists each segment as a precedent carrying its `reserving_class`. No reverse `dependents` edge is written onto a bootstrap's sidecar.
- The ResQ import (`python-api/migration/resq_migration/extractors.py`, `export_stochastic_consolidation`) writes the same files as a first save: ResQ's owned settings go onto an empty method and are consolidated from the segment bootstraps already imported into their own classes. When a segment is not in Arco yet, the method is written unrun (ResQ's origin labels, blank values) and the import reports which segments are missing; the page then shows `not_run` and offers Consolidate.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change the payload only in `arcrho_api/stochastic_consolidation_contract.py` and its parity tests.
2. Keep every segment read addressed by the segment's own reserving class.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- **Cross-class propagation is deferred.** Saving a bootstrap does not refresh the consolidations that include it; freshness is checked on open instead, and the page offers Consolidate. Deleting or renaming a bootstrap is not blocked by a consolidation that includes it; the load then reports that segment `missing`.
- A 10,000-simulation run re-simulates every segment (roughly 1.4 seconds each) inside the host class's lock on Save.
<!-- MANUAL:END -->
