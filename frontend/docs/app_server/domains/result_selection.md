# App Server Domain: Result Selection

## Purpose
<!-- MANUAL:BEGIN -->
Own the aggregate load, validation, persistence, and eager dependency refresh flow for Result Selection methods. A current Result Selection is a self-contained read model: its method JSON owns every source value, weight, calculated/final ultimate, override, and configured Ratio Basis vector needed by the UI, while its output dataset sidecar owns Notes, Audit Log, origin metadata, review status, and dependency graph edges.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN app_server.result_selection.entry_points -->
| Method | Path | Handler | Request Model | Schema | Service Calls |
| --- | --- | --- | --- | --- | --- |
| `POST` | `/result-selection/load` | `load_result_selection` | `ResultSelectionLoadRequest` | [`app_server/schemas/result_selection.py`](../../../app_server/schemas/result_selection.py) | `result_selection_service.load_result_selection`, `workspace_read_client.run_workspace_read` |
| `POST` | `/result-selection/save` | `save_result_selection` | `ResultSelectionSaveRequest` | [`app_server/schemas/result_selection.py`](../../../app_server/schemas/result_selection.py) | `engine_hosted_save_service.run_hosted_save` |
| `POST` | `/result-selection/save/plan` | `plan_result_selection_save` | `ResultSelectionSaveRequest` | [`app_server/schemas/result_selection.py`](../../../app_server/schemas/result_selection.py) | `engine_hosted_save_service.run_hosted_save_plan` |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN app_server.result_selection.key_files -->
- [`app_server/api/result_selection_router.py`](../../../app_server/api/result_selection_router.py) - Aggregate Result Selection load/save routes.
- [`app_server/services/result_selection_service.py`](../../../app_server/services/result_selection_service.py) - V2 contract validation, persistence, and eager dependency refresh.
- [`app_server/schemas/result_selection.py`](../../../app_server/schemas/result_selection.py) - Result Selection load/save request models.
- [`ui/method_pages/result_selection/result_selection_json_contract.js`](../../../ui/method_pages/result_selection/result_selection_json_contract.js) - Canonical frontend v2 payload builder.
<!-- AUTO-GEN:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- `POST /result-selection/load` accepts project, reserving-class path, and method name. For a current v2 method it performs exactly two bounded parallel JSON reads: `methods/RS@<Name>.json` and `sidecars/<Name>.json`. It does not read `index.json`, enumerate folders, or reopen source, Ratio Basis, or calculated-dependency JSON/CSV files.
- A legacy v1 load is an explicit one-time upgrade path. It bounded-parallel reads the configured source and Ratio Basis sidecars/caches, refreshes every stored vector, recalculates selected ultimates, persists v2 method/output/sidecar files, and repairs reverse dependency edges. If any required dependency cannot be read, the upgrade fails without replacing the last valid method, output, or sidecar.
- `POST /result-selection/save` validates the complete v2 payload, rejects self-reference or a wider dependency cycle before mutation, writes method JSON plus native/coarser output vector CSVs through one staged replacement set, and then saves the output sidecar. When the existing output needs review, Save bounded-parallel rereads and validates exactly the revised incoming source and Ratio Basis set and refreshes their snapshots while preserving weights and overrides. Removed stale precedents do not participate in this recovery validation. Missing or unreadable precedents remain blocking, while readable review-needed precedents are returned through `unreviewed_precedents` and `unreviewed_precedent_count` after the save commits. Every Save, including a no-op Save, acknowledges this Result Selection by writing its status as current and triggers downstream propagation. The response distinguishes a committed primary save from review, downstream propagation, and index warnings.
- Durable dataset, DFM, Bornhuetter Ferguson, app-calculated dataset, and Result Selection output writes use one reserving-class update lock and the shared recalculation flow. It follows registered `Dependents`, refreshes affected Result Selection source/basis vectors and source metadata, preserves weights and ultimate overrides, rewrites the self-contained method/output/sidecar set, and continues through refreshed method and app-calculated nodes. Each successful publication uses the shared content-based review policy: meaningful method JSON or any output CSV change sets Review Needed, unchanged content preserves green, and an existing review alert stays yellow; the newly refreshed values still remain traversal roots, and every successfully visited Result Selection output records a new `updated_at` even when its values held, while plain input and formula-calculated datasets stay Current but remain traversal links. Refresh/Sync does not acknowledge an existing Result Selection alert. Failed branches block only their descendants, independent successful branches continue, reachable cycles are rejected before RS mutation, and refresh or index failures are reported separately from review status.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- `POST /result-selection/load` is the `result_selection_load` Server-hosted workspace read: when the Gateway advertises it, the method JSON and sidecar are read on the server host and returned verbatim; otherwise the service runs locally. See [`workspace_reads`](workspace_reads.md).
- Current method marker: `arcrho-result-selection-method-by-tab-v2`. Legacy v1 remains readable only for the one-time upgrade.
- `method_tab.loaded_datasets[*]` owns source metadata plus one `values` and `weights` entry per `origin_labels` row. `method_tab.ratio_basis_values` is a deterministic configured-order array of `{name, values}` records, including inactive configured bases; every vector has exactly one entry per origin row. `calculated_ultimate`, `selected_ultimate`, and `ultimate_overrides` have the same row count.
- `details_tab.ratio_basis_datasets` contains at most three case-insensitively deduplicated names, and `active_ratio_basis_dataset` must be one of them or blank. Source and Ratio Basis names form the deterministic union persisted in sidecar `Precedents` and reverse source-sidecar `Dependents`.
- Persisted numeric arrays use symmetric half-away-from-zero rounding to six decimal places. The frontend builder, app-server normalizer, ResQ migration exporter, and data-engine RPC exporter are covered by an exact full-payload parity test.
- Refresh reads are bounded and deduplicated per frontier. Writes serialize per project/reserving-class path, including engine/runtime sidecar publication, use the shared per-sidecar lock for read/modify/write, stage paired CSV/sidecar files with rollback, write the RS sidecar last, preserve prior artifacts on dependency-read failure, and rebuild the reserving-class index once after a cascade. Exact period reads reject obsolete finer-grained cache files after a method's native Origin Length becomes coarser. A valid v2 load takes only its output-sidecar lock, so it does not wait for unrelated RS outputs in the same reserving class.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change the v2 shape: update the frontend contract builder, app-server normalizer, migration exporter, data-engine exporter, exact parity test, and this document together.
2. Change refresh traversal or writes: keep bounded deterministic reads, serialized transactional writes, sidecar-last publication, failure preservation, and transitive tests.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- A propagation refresh writes `method_metadata.data_refreshed` and leaves `last_modified` -- the last user Save -- untouched, matching DFM, BF, CC and bootstrap. The ResQ reserving-class sync reads `last_modified` as the ArcRho edit time, so a method recomputed because an input changed is not offered as a change to push.
- `method_revision` covers the method's content and deliberately excludes `method_metadata.last_modified` and `data_refreshed`, matching DFM, BF, CC and bootstrap, whose revisions come from `dfm_contract.method_revisions` projections that never reach them. That is what lets an RPC upload record ResQ's save time without invalidating the token an open editor saves with. A revision is minted where the method loads (a Client PC's app server, or the Gateway) and checked where it saves (always Arco Engine), and those upgrade separately, so `save_result_selection` also accepts `_legacy_method_revision` -- the whole-file hash minted before the exclusion. Remove that fallback once every installed app carries the change.
- Out-of-band edits that bypass ArcRho's durable save paths cannot publish a dependency event; use an ArcRho save or explicit refresh after external file changes.
- DFM and Bornhuetter Ferguson retain their own method-specific recalculation rules. Result Selection refresh begins when the dataset/output it directly references is durably rewritten; a method merely marked for review has not yet published a new output vector.
<!-- MANUAL:END -->
