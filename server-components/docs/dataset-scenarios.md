# Dataset Scenario Matrix

## Purpose
This note defines how dataset type metadata, dataset instances, and cache rebuild behavior should be categorized. It is intended to keep the frontend app, app server, Excel add-in, and data engine aligned on the same dataset rules.

## Scenario Matrix

| Scenario | Canonical `source_kind` | Instances Per Dataset Type | Editable Cells | Calculated | Engine Request | Cache Rebuild / Clear Behavior | Primary Rebuild Trigger | Storage |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| Pure data-engine dataset | `engine` | 1 | No | No | Yes | Existing cache may be reused. Frontend force refresh may delete the matching CSV and request a fresh engine output. | Frontend run or source refresh | `data/<ReservingClass>/datasets/*.csv` plus `sidecars/*.json` |
| Calculated from only generated/rebuildable components | `calculated` | 1 | No | Yes | Yes, allowed when the engine can resolve every formula dependency | Treat as generated-class for refresh purposes. Frontend force refresh may clear the matching CSV and request a fresh output, or the app may recalculate eagerly after a component rebuild. | Direct request, component engine output save, or explicit recalculation | `data/<ReservingClass>/datasets/*.csv` plus `sidecars/*.json` |
| Calculated from any manual/imported component | `calculated` | 1 | No | Yes | No | Treat as non-generated-class for cache-clearing purposes. Do not delete because of Excel refresh; recalculate eagerly when editable/imported components change. | Component save/import or explicit recalculation | `data/<ReservingClass>/datasets/*.csv` plus `sidecars/*.json` |
| Manual user-entered dataset | `input` | Many allowed | Yes | No | No | Never cleared by data-engine refresh or Excel refresh. Users can paste/edit values. | User save / paste | `data/<ReservingClass>/datasets/*.csv` plus `sidecars/*.json` |
| Imported dataset | `import` | Many allowed unless a type explicitly opts into single-instance | Usually no after import; optionally editable if the import flow marks it editable | No | No | Never cleared by data-engine refresh or Excel refresh. Replaced only by an import action or an explicit user save if editable. | Import action / optional user save | `data/<ReservingClass>/datasets/*.csv` plus `sidecars/*.json` |
| Method-owned dataset output, such as DFM result data | `method` | Usually 1 per method output name | No for output cells; method settings are edited through method UI | Yes, method-calculated | No direct ArcoTri engine request | Rebuilt when the owning method is saved or recalculated. The dataset cache should not be manually edited. | Method save / method recalculation | `data/<ReservingClass>/datasets/*.csv`, `methods/*.json`, plus `sidecars/*.json` when needed |
| Helper cache, such as headers/project settings | `helper` | Not a dataset instance | No | No | May request engine/helper output | Not listed as a reserving-class dataset instance. May use project data-root helper cache files. | Helper request | `data/*.csv` or another helper-specific cache path |

## Derived Behavior

| Derived Behavior | Rule |
| --- | --- |
| `editable` | True only for `source_kind=input`, and optionally for imported datasets when the import flow explicitly allows user edits. False for `engine`, `calculated`, `method`, and `helper`. |
| `calculated` | True for `source_kind=calculated` or `source_kind=method`; false for `engine`, `input`, `import`, and `helper`. |
| `single_instance` | True for `engine`, `calculated`, and method-owned outputs. False for manual/imported input types unless a type-specific rule says otherwise. |
| `engine_request` | True for `source_kind=engine` and engine-backed helper caches. Also true for `source_kind=calculated` when every formula dependency is generated/rebuildable and the engine can resolve the formula. False for calculated outputs with any input/import/manual-bound dependency. |
| `generated_class` | True for `source_kind=engine`; true for `source_kind=calculated` only when every dependency is generated-class. False when any dependency is input/import/manual-bound. |
| Excel refresh | Read every sidecar-backed instance as published; never clear or regenerate it. Validate source/configuration provenance before reusing a sidecar-less generated cache. |
| User can create multiple instances | Only useful for manual/imported source kinds. Generated and calculated dataset types should stay single-instance because duplicate instances would have the same deterministic result unless the type has explicit parameters. |

## Minimal JSON Categorization

Use one authoritative type-level field instead of several independent booleans:

```json
{
  "name": "Expected Net Loss % * Earned Premium",
  "source_kind": "calculated",
  "formula": "[Expected Net Loss %] * [Earned Premium]"
}
```

Recommended canonical fields:

| Field | Level | Required | Purpose |
| --- | --- | --- | --- |
| `name` | dataset type | Yes | Stable dataset type name. |
| `source_kind` | dataset type | Yes | One of `engine`, `input`, `import`, `calculated`, `method`, or `helper`. This replaces independent `Generated`, `Calculated`, and default editability flags. |
| `formula` | dataset type | Only for calculated types | Formula used to derive app-calculated outputs and dependency graph. |
| `instance_name` | dataset instance sidecar | Yes for instance metadata | User-visible instance Name. May differ from dataset type for `input`/`import`. Usually equals type name for `engine`/`calculated`. |
| `dataset_type` | dataset instance sidecar | Yes for instance metadata | Links an instance back to its dataset type rule. |
| `csv_file` | dataset instance sidecar | Yes for instance metadata | Physical cache filename for the current instance. |

Fields that should be derived instead of user-authored in `dataset_types.json`:

| Derived Field | Derive From |
| --- | --- |
| `editable` | `source_kind`, plus optional import edit policy. |
| `calculated` | `source_kind`. |
| `single_instance` | `source_kind`. |
| `generated_class` | `source_kind` plus calculated dependency graph. |
| `cache_clear_allowed` | `generated_class` and whether the output is an engine request output. |

Persisting derived values in sidecars or `index.json` is acceptable as a cache snapshot for fast UI rendering, but the source of truth should remain `source_kind`, `formula`, and the dependency graph.

## Instance Naming Rule

Dataset type name and instance name are distinct:

- `dataset_type` identifies the row in `dataset_types.json` and determines source behavior.
- `instance_name` identifies the user-visible dataset instance and physical CSV/sidecar identity.
- `engine`, `calculated`, and method output types should normally force `instance_name == dataset_type`.
- `input` and `import` types may allow multiple instance names for the same dataset type.

## Excel Add-In Lookup Rule

Add-in 3.0.1 opens and ordinarily recalculates from the saved workbook snapshot. Entering, editing, or pasting an ArcRho formula sends missing requests over HTTP to the Gateway and stores successful results in that snapshot. Refresh Worksheet and Refresh Workbook also fetch requests already saved. Excel never looks for CSVs or sidecars over the workspace share.

The hosted Excel reader uses the requested instance's sidecar and its declared `csv_file` as the permanent publication. It never rewrites a publication, and a publication that is missing or stale at its own shape is reported rather than regenerated. Compatible manual/input and Engine-generated triangle/vector period rollups are computed in memory from that publication. Engine rollups use the CSV's native periods rather than the finer source-table granularity recorded in its sidecar. An Engine-generated dataset asked for at a shape or mode its publication cannot provide (a finer period, a non-multiple, another cumulative/calendar mode) is built by the Engine into a technical cache beside the publication, reused under the same provenance rules as a sidecar-less request. Manual/input, calculated, and method outputs at an unsupported shape or mode are refused, naming the published and requested periods. Source, formula, configuration, and dependency changes are handled by the frontend's publishing workflows.

A sidecar-less generated request may reuse a matching technical cache only while the source-table identity and processing configuration are unchanged. Temporary formula requests evaluate their dependencies under the same ownership rule and publish no permanent sidecar or index entry. Corrupt or unreadable sidecars are errors, not evidence that a dataset is temporary. Refresh is refused while a propagation job holds the class.

## ResQ Reserving-Class Migration

The ResQ reserving-class migration uses the same external worker contract as the Excel add-in for generated datasets. Before opening ResQ, it requires at least one fresh heartbeat under `runtime/instances/arcrho_engine`; if none exists, the import stops without changing the selected reserving class.

Generated triangle and vector requests are atomically published under `<ArcRho Server>/requests` and target unique staging paths. The migration publishes the batch before waiting so the configured data-engine worker pool can claim requests concurrently. Migration requests also provide optional `RequestId` and `StatusPath` fields. Status-aware workers atomically report `processing`, then `success` or `error`; the migration finalizes a status-aware result only after `success`, so an error CSV cannot become a canonical dataset. Workers that predate the optional fields remain compatible through the original atomic CSV completion contract. Only a completed staging CSV replaces its canonical dataset cache. The migration process does not import the data-engine calculation module or launch a private engine instance. It builds engine-owned sidecars through the same `arcrho_api.engine_dataset_sidecar_contract` used by the frontend runtime, omitting ResQ axis labels/formulas/users/timestamps; cached frontend reads hydrate labels and formulas from their canonical project sources. Migration remains responsible for processing provenance, graph enrichment, and `index.json`.

### Bridge-backed remote ResQ import

The `Import ResQ Reserving Class` macro can run on a separate PC without a local ResQ COM connection. It first requires a fresh, ResQ-connected Bridge worker heartbeat; if no Bridge is available, the macro publishes no request and leaves the selected reserving class unchanged.

The macro publishes only logical fields to the versioned `resq_reserving_class_import_contract.json` queue under `<ArcRho Server>/requests/RPC bridge/resq_reserving_class_import/requests`. The Bridge writes progress and terminal status to the matching `statuses/<RequestId>.json` file, which the macro polls synchronously. Before the dataset total is known, the progress label reports live ResQ inventory counts. After inventory, the numeric bar remains a truthful completed-dataset count while labels identify generated-dataset submission and engine waits, dependency refresh, index rebuild, and commit work.

The Bridge build declares the frontend HTTP dependency used by the canonical processing-provenance service and runs an import preflight before PyInstaller. A build therefore stops immediately if the bundled migration cannot load that frontend contract, instead of deploying an executable that discovers the missing dependency during a live import.

The Bridge stages the full reserving-class import under the project data root and commits it into place only after the ResQ-owned import, sidecar graph refresh, and canonical `index.json` rebuild have succeeded. The commit makes the live folder identical to the staged folder file by file, with bounded parallel I/O: staged files are moved in, live files ResQ no longer exports are removed, and `index.json` lands last so the published summary only ever describes contents that are already in place. Every replaced or removed live file is moved into the isolated Bridge staging backup first, so a commit that fails part way restores the exact previous contents and the live reserving class is never left partially updated. Deletion of that backup is attempted only after a successful commit; a cleanup failure retains it and is reported as a warning.

Only one import may hold a reserving class at a time. That claim is the canonical durable-job lease from `arcrho_engine_job_lease`, not a plain lock file: the running import renews it on a heartbeat thread, and a claim nobody has renewed for `RESQ_IMPORT_LOCK_STALE_SECONDS` is taken over by the next import. This matters because the Bridge worker is force-terminated by its own supervisor whenever the ResQ GUI disappears and by the deploy kill switch, neither of which runs an exception handler; a claim released only on a clean exit blocked its reserving class until an operator deleted the file by hand. For the same reason, a Bridge worker reconciles interrupted imports at startup: a `processing` status that no live worker has renewed for `RESQ_IMPORT_STATUS_STALE_SECONDS` is republished as an error, and that request's staged folder is reclaimed unless it holds a commit backup. A staged folder is also removed when an import fails before the commit begins, since nothing has been moved aside yet.


### Bridge-backed remote ResQ synchronization

The `Sync Reserving Class with ResQ` macro reaches ResQ the same way, through a sibling queue under `<ArcRho Server>/requests/RPC bridge/resq_reserving_class_sync/` described by `resq_reserving_class_sync_contract.json`. That contract restates none of the worker's identity or the queue's status vocabulary: one ResQ-connected Bridge worker serves both queues, so the worker role, heartbeat folder, freshness window, status values, and path-field ban are read from the import contract instead of being copied.

A synchronization is two requests rather than one, because a person reviews it in the middle. The `preview` phase is read-only and returns the review rows plus the `signature` of each observation. The `apply` phase sends the accepted rows back with those signatures; the Bridge rechecks each one against a freshly observed plan and writes nothing if any of them moved. Sending the reviewed signature over the queue is what preserves the guarantee the single-process macro used to get for free — and strengthens it, since the check now covers the whole time the review table was open rather than a few seconds inside one call.

Only the `apply` phase competes for the reserving class, and it takes the same `arcrho_engine_job_lease` claim a ResQ import takes, so a synchronization and an import can never write one reserving class at the same time. A `preview` takes no claim and never blocks a running import. Interrupted synchronizations are reconciled at worker startup exactly like interrupted imports; a synchronization owns no staging folder, so there is nothing to reclaim beyond the expiring lease.

The Bridge runs its frozen copy of the canonical session (`resq_migration.sync_session`) and of the ResQ exporter macro it drives, both listed in `arcrho_bridge/bundled_sources.py`. Editing either has no effect on a live synchronization until the Bridge is rebuilt, and a worker refuses a bundle whose `SYNC_SESSION_API_VERSION` it was not built against rather than driving it.

Both queued sessions -- the import and the synchronization -- connect to ResQ with the shared service account `resq_client.resq_connection_settings()` reads from the server `config.json`, the same account the RPC methods use; `ResQClient` hands it to each runner. Left to the migration's defaults they would connect with the claiming worker's Windows identity, and because a Bridge worker runs per signed-in user session, the projects a request could see then depended on which user's worker won the claim.

The commit never renames the reserving-class folder itself. Windows refuses to rename a folder while another process still holds any file below it open, which would let one unrelated reader discard a finished import; committing file by file narrows that to the single file a reader actually holds. Those transient reader locks are waited out for a bounded period, and a lock that outlasts the wait rolls the whole commit back and asks the user to close the file. The index update lock file is owned by whichever process holds it and is never moved or deleted by a commit. ResQ stored methods and other non-generated objects are read only by the Bridge. A DFM Ratio Basis snapshot is read directly from the related ResQ DFM through `SummaryRatioBasis.ValuesByIndex` at the DFM's `OriginCount`; it does not create a shape-specific data-engine request. Standalone generated triangle/vector datasets remain Arco Engine outputs. If the Engine component is unavailable or fails, the Bridge preserves the prior engine artifacts while committing the independently successful non-generated ResQ component.
