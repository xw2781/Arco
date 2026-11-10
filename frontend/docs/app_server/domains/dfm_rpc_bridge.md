# App Server Domain: DFM RPC Bridge

## Purpose
<!-- MANUAL:BEGIN -->
DFM RPC bridge routes create request files for remote data-engine DFM owned-state sync, compare local and returned metadata, apply an approved owned patch through the canonical DFM v2 calculator/save service, finalize keeping local JSON without sending a `SyncDFM` request, and send confirmed write-back requests to the RPC server through `arcrho_bridge`.
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->
Routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/dfm/rpc-bridge/sync` | Write `Function = DFM` request, wait up to the requested timeout for remote DFM JSON, and return comparison metadata plus local/remote JSON snapshots. |
| `POST` | `/dfm/rpc-bridge/compare` | Compare current local and remote DFM JSON file metadata without sending a request, returning the same snapshot fields. |
| `POST` | `/dfm/rpc-bridge/apply` | Validate the remote owned-patch marker, merge approved owned components over the newest local derived snapshot, canonically recalculate/save v2, return the saved payload for frontend reload, and delete the temporary response. |
| `POST` | `/dfm/rpc-bridge/keep-local` | Keep the local DFM JSON unchanged after `Keep Using Local` and delete the remote RPC JSON without writing a `SyncDFM` request. |
| `POST` | `/dfm/rpc-bridge/cleanup` | Delete temporary remote DFM JSON and `SyncDFM` status JSON for the current project/reserving-class/method after the sync dialog is dismissed or a pending sync returns after dismissal. |
| `POST` | `/dfm/rpc-bridge/update-remote` | Require explicit RPC server write confirmation, write `Function = SyncDFM` request with the local method JSON path, wait for the `SyncDFM...json` status response, return pass/fail message, and delete the stale remote RPC JSON. |
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `app_server/api/dfm_rpc_bridge_router.py` - Thin API routes.
- `app_server/schemas/dfm_rpc_bridge.py` - Request schemas.
- `app_server/services/dfm_rpc_bridge_service.py` - Path resolution, request-file writes, wait/compare/apply/update-remote behavior.
- `ui/method_pages/dfm/dfm_rpc_bridge_client.js` - Frontend route calls and sync flow.
- `ui/method_pages/dfm/dfm_rpc_bridge_dialog.js` - Floating comparison/status UI.
<!-- MANUAL:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- Transport: `apply` rewrites the method and walks its dependents, so it is the `dfm_rpc_bridge_apply` hosted save: it runs on Arco Engine under the reserving-class lease, like the page's own Save, and never saves from the client process. `dfm_rpc_bridge_service.apply_remote_to_local_save` is the Engine's entry point (the route body travels third, so the save log names the method, and a body naming another project or class than the job is refused with 400), and its `save_propagation_roots` names the stored DFM's output. Every other route selects its transport per request. `compare` is a workspace read (`dfm_rpc_bridge_compare`) and `sync`, `keep-local`, `cleanup`, and `update-remote` are workspace mutations (`dfm_rpc_bridge_*`), so they run inside the Arco Gateway on the server host when it advertises the kind and over the mapped drive otherwise. The request file, its fields, the `tmp_rpc` locations, and the Bridge contract are identical either way; what changes is which machine writes the request and waits for the answer. A Client PC reaches those folders over SMB while the Bridge that serves them runs on the server host, where they are local disk and the wait is a file-system event instead of a probe-and-poll loop. `UserName` carries the acting user rather than the process account, which is what makes the hosted request name the person who clicked Sync.
- Before writing each `Function = DFM` request, the app server deletes any existing returned DFM JSON and `SyncDFM` status JSON for that project/reserving-class/method from `projects/<project>/data/<ReservingClassFolder>/methods/tmp_rpc`, so the sync comparison can only use a fresh RPC bridge response. `Function = DFM` request files contain Details page fields plus `DataPath`, where `DataPath` points to the expected returned remote DFM method JSON under that RPC temp folder.
- `Function = SyncDFM` request files contain the same Details page fields plus `DataPath`, where `DataPath` points to an expected `SyncDFM...json` status file. They also include `MethodJsonPath` for the local DFM JSON to write into the RPC server and `RPCServerWriteConfirmed = true`; the app-server route rejects update-remote requests without this explicit confirmation. When the local output sidecar is readable, the request also carries its `notes` value as `MethodNotes` — including an empty value — because Method Notes are not stored in the method JSON the bridge reads; the field is omitted only when the notes owner is unavailable.
- Request files are flat JSON `request-*.json` payloads with native booleans/numbers. Temporary `.tmp` files are atomically renamed to `.json`, and `arcrho_bridge` scans JSON requests only.
- `SyncDFM` status JSON must include fields that let the frontend report final result, for example `ok`, `status`, and `message`. It also carries `last modified`: the `Modified` value ResQ stamped on the method when the confirmed write-back saved it, read after `Save()` and spelled as the DFM export spells it. An empty value means the property could not be read.
- After a successful `SyncDFM`, the app server records that reported value as the local method's `method metadata.last modified` through `dfm_service.record_rpc_sync_last_modified`, and reports the outcome under `last_modified_record`. Without it the two copies hold identical settings under different times, and the next comparison ranks the remote newer and offers to pull back what was just pushed. The value must be ResQ's own rather than this machine's clock: the comparison matches on the instant, so a local `now` differs by the round trip and by whatever the two clocks disagree about, which on a slower client leaves the remote newer anyway. The record is not a save — it touches only that field, which sits outside the owned, derived, and publication projections, so no revision shifts, no open editor loses its save token, and no dependent is disturbed. A Bridge that does not report the value, a missing method, or a legacy v1 file leaves the local timestamp untouched; the upload already succeeded, so a failure to record is reported beside it rather than turned into a failed sync.
- `arcrho_bridge` handles confirmed `SyncDFM` requests by reading `MethodJsonPath`, writing excluded ratio cells, User Entry average-formula values with `SetUserRatios`, and selected average formula indexes with `SetSelectedRatios` to the RPC server DFM method, calling `Save()`, and writing the status JSON to `DataPath`. ResQ exposes DFM cell notes as a read-side `CellNotes` string, so RPC bridge imports them into returned DFM JSON and local apply syncs them, while remote write-back leaves existing ResQ cell notes unchanged until a safe per-cell setter is available.
- A DFM read response also carries ResQ method-level `Notes` as transient `method metadata.method notes`. The comparison shows it as a Method Notes diff against the local output-sidecar `notes` value, and a confirmed remote-to-local apply writes the present remote note into the output sidecar, which remains the only persisted ArcRho owner — an empty ResQ note clears the sidecar notes. Only an absent `method notes` field (an older bridge payload) keeps the local sidecar notes. A confirmed `SyncDFM` write-back sets ResQ method `Notes` from the request's `MethodNotes` with line breaks normalized to `\r\n` (ResQ renders `\n`-only text as one line) — an empty `MethodNotes` clears ResQ method `Notes`, an absent field leaves them unchanged, and the status JSON reports the write under `updated["method notes"]`.
- A DFM read response uses `payload format = arcrho-dfm-owned-patch-v1` and contains only RPC-owned settings. It is not a complete v2 method and must never be persisted directly. Compare responses still project exclusions, average definitions/selections, cell notes, and other owned components for the review dialog.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Local DFM method JSON path: `projects/<project>/data/<ReservingClassFolder>/methods/DFM@<Name>.json`.
- Remote DFM method JSON path: `projects/<project>/data/<ReservingClassFolder>/methods/tmp_rpc/DFM@<Name>.json`.
- Remote update status JSON path: `projects/<project>/data/<ReservingClassFolder>/methods/tmp_rpc/SyncDFM@<Name>.json`.
- `<ReservingClassFolder>` and `<Name>` use the shared reversible `_%XX_` filename escaping rule for Windows-invalid filename characters.
- Applying a remote patch delegates to the same owned projection and preview/save contract used by normal DFM v2 saves. Embedded input/basis snapshots, calculated ratios/averages, ultimates, source revisions, and publication metadata always come from the canonical local base and recalculation.
- Sparse RPC fields are interpreted through the canonical DFM owned-state projection. Supported Details settings, exclusions, formula definitions/selections/inputs and owned stored values, ratio-cell notes, and Ratio Basis selection are applied when present; omitted owned fields retain their local values. Method Notes are not part of the owned method projection: apply writes a non-empty `method metadata.method notes` value to the output sidecar `notes` field only.
- `json format`, embedded source snapshots, derived arrays, revisions, and absolute paths are never accepted as RPC-owned fields. The apply response reports the fields that were actually applied; a sparse patch does not produce a competing required-component list.
- JSON request files are kept for audit/debug. Returned RPC bridge JSON files are deleted before each new sync request, after the user completes the final action, closes the sync review window without choosing an action, or closes the window while a pending sync later returns.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Change DFM request-file contract: update schema/service, frontend client payloads, and this domain doc.
2. Change comparison actions: update `dfm_rpc_bridge_dialog.js`, `dfm_rpc_bridge_client.js`, and route behavior.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Request and return-path filename rules must match data-engine expectations exactly.
- Timestamp comparison uses the canonical `last modified` value inside each DFM JSON file, parsed by `helpers.parse_method_last_modified_timestamp` (the single owner shared with the Result Selection RPC bridge). ResQ writes `Modified` as a timezone-less wall-clock string in the machine's own timezone and an ArcRho save writes an absolute ISO value with `Z` or an offset, so a timezone-less value is read as local time. Reading it as UTC instead put the `NEW` seal on the wrong card by the UTC offset whenever the two versions were saved less than that offset apart.
- Sync waits are intentionally short; timeout handling must remain clear to users.
<!-- MANUAL:END -->
