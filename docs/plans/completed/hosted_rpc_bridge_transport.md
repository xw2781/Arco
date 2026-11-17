# Hosted RPC Bridge Transport: Moving the DFM and Result Selection Sync off SMB

Status: Implemented and deployed 2026-08-19 (Gateway, Engine, Bridge), except
the `apply` item under [Deferred and optional](#deferred-and-optional)
Related: [hosted_workspace_http_transport.md](hosted_workspace_http_transport.md) — this
plan fills the one gap that document names but does not cover: "the DFM/RS
RPC-bridge request files (`requests/RPC bridge/`), consumed by the Bridge, not
the Engine."

## Why

The DFM tab-bar Sync button (`dfmRpcSyncBtn`) and its Result Selection twin are
the last user-facing flows that talk to the workspace entirely through the
mapped drive. Every one of the six routes in
`frontend/app_server/api/dfm_rpc_bridge_router.py` does raw filesystem work from
the Client PC: it deletes stale temp files, writes a `request-*.json` into
`requests\RPC bridge\`, polls the share for the Bridge's answer, then stats and
reads both method JSONs to build the review dialog.

Measured 2026-08-18 from the Client PC (L-H2MQ6280FVP) against
`E:\ArcRho Server`, project `NJ_Annual_Prod_202605_Fake`:

| Operation | SMB | Gateway HTTP |
| --- | --- | --- |
| `open()+read()` a 4.7 KB method JSON | 582 ms median | — |
| write + exists + rename + delete a small request file | 982 ms median | — |
| one `wait_for_file` poll iteration (visibility probe + exists) | 647 ms | — |
| `GET /api/health` / `/api/capabilities` | — | 33–34 ms |
| load one DFM method (`dfm_method_load`) | 945 ms | 61–65 ms warm (**~15x**) |
| `POST /dfm/rpc-bridge/compare`, real method | 1.37–1.52 s, 20 share ops | — |

That `compare` measurement is the cheap case: the remote `tmp_rpc` JSON was
absent, so it read one side. With a response present it reads two more files.
Adding up one full sync — publish the request, wait for the reply, compare,
optionally Refresh, clean up twice on close — the Client PC pays roughly **4–7 s
of SMB latency that is not ResQ's work**. Cost on the share is per operation,
not per byte (a 0.2 KB file still took 415 ms), so only cutting round trips
helps.

The Bridge itself is not the problem. Heartbeats confirm it runs on the server
host (`bridge@NE7SASWPN02@xwei`, `@ysong`), where `requests\RPC bridge\` and the
project data are local disk. Only the client half of the exchange crosses SMB,
which is exactly the shape Phase 2 already solved for the Engine.

## What this changes

Nothing about the Bridge's contract. The request file, its fields, the response
JSON, and the `tmp_rpc` locations stay byte-for-byte what they are today; the
Bridge is untouched (with one optional exception in
[Deferred and optional](#deferred-and-optional)). What moves is *which machine
writes the request file and waits for the answer*: the Gateway, on local disk,
instead of the Client PC over the share. The browser keeps calling the same
local app-server routes with the same payloads and gets the same response
shapes back.

## Decisions

| Decision | Choice | Rationale |
| --- | --- | --- |
| Transport vehicle | The existing read and mutation registries, not a new route | These operations are ordinary `app_server` service calls; `arcrho_workspace_mutation_contract` already hosts exactly this shape, and the Gateway's hidden imports and build-time probe derive from both registries |
| `compare` | Workspace **read** kind | A pure function of the workspace, so it may fall back to SMB freely after any failure |
| `sync`, `keep-local`, `cleanup`, `update-remote` | Workspace **mutation** kinds | They write or delete; the mutation contract's "never fall back after acceptance" rule is the one that matters here |
| `apply` | Stays local in phase 1 | It saves the method, and it currently does so in a way that deserves its own decision (see [Deferred and optional](#deferred-and-optional)) |
| Request shape | The pydantic schema fields verbatim as contract kwargs | The hosted entry point rebuilds `DfmRpcBridgeRequest`, so validation has one owner and the two transports cannot diverge |
| DFM and RS | Parallel kinds against each service, not a merged service | The two services are near-duplicates, but merging them is a separate refactor with its own risk; see [Deferred and optional](#deferred-and-optional) |
| Rollback | Capability-probed per kind, as with every earlier phase | An older or stopped Gateway keeps the current SMB behavior with no client change |

## Design

### Kinds

Ten registry entries, five per method family.

| Route | Kind | Registry |
| --- | --- | --- |
| `POST /dfm/rpc-bridge/compare` | `dfm_rpc_bridge_compare` | read |
| `POST /dfm/rpc-bridge/sync` | `dfm_rpc_bridge_sync` | mutation |
| `POST /dfm/rpc-bridge/keep-local` | `dfm_rpc_bridge_keep_local` | mutation |
| `POST /dfm/rpc-bridge/cleanup` | `dfm_rpc_bridge_cleanup` | mutation |
| `POST /dfm/rpc-bridge/update-remote` | `dfm_rpc_bridge_update_remote` | mutation |
| the five `/result-selection/rpc-bridge/*` equivalents | `result_selection_rpc_bridge_*` | same split |

Every kind takes the same kwargs the route's schema takes:

- required: `project_name`, `reserving_class`, `method_name`, `output_vector`,
  `input_triangle`, `origin_length`, `development_length`
- optional: `decimal_places`, `timeout_sec`
- `*_update_remote` also requires `rpc_server_write_confirmed`

`compare`, `keep_local`, and `cleanup` do not read the Details fields, but they
are part of the route's schema and the frontend already sends them. Taking the
whole schema keeps one validation owner rather than a second, narrower shape
that could drift.

### Idempotency

The mutation contract admits only kinds whose second run leaves the same end
state as the first.

- `cleanup` and `keep_local` delete temp files; a file already gone is skipped,
  not failed.
- `sync` deletes the stale response and status files, writes a request, and
  waits. A repeat regenerates the same response from the same ResQ method. The
  cost of a repeat is a duplicate ResQ export, not a divergent workspace.
- `update_remote` writes the local method's owned settings into the RPC server
  and saves. A repeat writes the same values. It is the one kind that mutates a
  system outside the workspace, so it carries the strictest no-fallback rule:
  once the Gateway has accepted the request, an ambiguous outcome is reported,
  never retried over SMB.

### Identity

`_request_payload` stamps `UserName` with `getpass.getuser()`. Inside the
Gateway that would be the gateway's service profile, not the person who
clicked Sync. Both bridge services must stamp
`user_identity_service.get_windows_login_name()` instead, which returns the
acting identity the executor binds for the duration of the call. This is the
same substitution `arcrho_runtime_service` and every save writer already make.

Note that this fixes attribution, not routing: any live bridge worker claims any
request file in the folder regardless of `UserName` (`_process_claimed_file`
removes the file first and asks questions after), so with two ResQ sessions
running, either may serve a sync today. That behavior is unchanged by this plan
and is listed under [Risks](#risks).

### Paths and responses

The response carries server-rooted paths (`paths`, `local.path`,
`remote.path`). Both clients already run `rebase_workspace_paths` over the whole
payload, so those come back rewritten onto the Client PC's own workspace root
and the response is indistinguishable from a local run. The frontend never
sends `paths` back — `cleanupRemoteTmp` re-sends the original logical
payload — so nothing depends on the server spelling.

Refusals keep their status codes: a service `HTTPException` becomes a
`WorkspaceReadRefusal` with the same code and detail. Detail text is passed
through `_redact_machine_paths`, so a refusal that today reads
`JSON file is locked or inaccessible: E:\...` loses the server path. That is an
improvement, but it is a visible message change worth confirming with the
dialog's error rendering.

### Waits

`timeout_sec` (8.0 from the frontend) becomes the *server-side* wait. On the
server host the path is local, so `wait_for_file` takes its watchdog branch —
event-driven, no polling, no probe writes — and `watchdog==4.0.1` is already in
the Gateway's requirements. The Gateway is a `ThreadingHTTPServer`, so a
blocking wait occupies one thread rather than the whole server.

The contract must clamp the wait the way `clamp_engine_calculation_wait` does
(floor 0.1 s, ceiling 60 s) so a client cannot ask the Gateway to hold a thread
indefinitely. The client's HTTP budget is `WORKSPACE_MUTATION_TIMEOUT_SECONDS`
(180 s), comfortably above the ceiling.

### Expected result

Per sync, the client's workspace filesystem operations between request and
response go to zero, and the 4–7 s of SMB latency becomes 2–3 signed POSTs of
~35–65 ms each. `compare`/Refresh alone goes from 1.4–2.5 s to roughly 65 ms,
which is the measured cost of the equivalent hosted method read. The user-
visible sync becomes "ResQ's own time plus about a fifth of a second".

## Implementation

### 1. Contracts (`python-api/src/`)

1. `arcrho_workspace_read_contract.py` — add `dfm_rpc_bridge_compare` and
   `result_selection_rpc_bridge_compare` to `WORKSPACE_READ_KINDS`, naming
   module `dfm_rpc_bridge_service` / `result_selection_rpc_bridge_service` and
   function `hosted_compare`, with the required/optional kwarg tuples above.
2. `arcrho_workspace_mutation_contract.py` — add the eight mutation kinds,
   naming `hosted_send_sync_request`, `hosted_keep_local`, `hosted_cleanup_tmp`,
   and `hosted_update_remote` on the same two modules. Document each entry's
   idempotency argument in the comment beside it, as the existing two kinds do.
3. Add the wait clamp used by the sync and update-remote kinds. Put it in the
   mutation contract next to the kinds that use it, exported by name, so the
   service and the tests read the same ceiling.

Both `HTTP_*_KINDS` tuples and the Gateway's advertised capabilities derive from
these dicts; there is no second table to update.

### 2. App-server services (`frontend/app_server/services/`)

4. `dfm_rpc_bridge_service.py` — add the five `hosted_*` entry points. Each is a
   thin wrapper that builds the pydantic request from flat kwargs and calls the
   existing function:

   ```python
   def hosted_compare(**kwargs) -> Dict[str, Any]:
       return compare(DfmRpcBridgeRequest(**kwargs))
   ```

   `hosted_update_remote` builds `DfmRpcBridgeUpdateRemoteRequest`. The
   signatures must name the contract's kwargs exactly; a mismatch fails only on
   the Gateway, never locally.
5. Same five in `result_selection_rpc_bridge_service.py`.
6. Replace `getpass.getuser()` in `_request_payload` with
   `user_identity_service.get_windows_login_name()` in both services, and drop
   the now-unused `getpass` import.
7. Clamp `timeout_sec` in `send_sync_request` and `update_remote` through the
   contract's helper, so the ceiling holds on both transports.

### 3. App-server routes (`frontend/app_server/api/`)

8. `dfm_rpc_bridge_router.py` — wrap the five routes:

   ```python
   @router.post("/dfm/rpc-bridge/sync")
   def sync_dfm_rpc_bridge(req: DfmRpcBridgeRequest) -> Dict[str, Any]:
       return workspace_mutation_client.run_workspace_mutation(
           "dfm_rpc_bridge_sync",
           req.model_dump(),
           local=lambda: dfm_rpc_bridge_service.send_sync_request(req),
       )
   ```

   `compare` uses `workspace_read_client.run_workspace_read` with the same
   shape. `apply` is untouched.
9. Same in `result_selection_rpc_bridge_router.py`.

No router registration changes are needed — both routers are already wired into
`app_server/api/__init__.py` and `app_server/main.py`.

### 4. Gateway

10. Nothing to write. `build_exe.py` derives its `--hidden-import` list and its
    pre-build "Validating canonical workspace-read dependencies" probe from the
    two registries, so the bridge service modules are picked up automatically.
    Confirm the probe passes before the build, since these services import
    `arcrho_api.dfm_contract`, `dfm_service`, `result_selection_service`, and
    `dataset_sidecar_status_service` transitively.

### 5. Client-side redundancy worth fixing in the same pass

11. `compare` reads each method JSON **twice** — once in `_file_meta`
    (`_json_last_modified_meta`) and again in `_build_json_snapshot` — and then
    reads the local method JSON a third time inside
    `_sidecar_method_notes_snapshot` to find the output dataset name. Parse each
    file once and pass the payload down. Two fewer share reads per compare on
    the SMB fallback path (~1.2 s measured), and less work on the hosted path
    too. Do this before hosting, so the before/after measurement is honest about
    which change bought what.

### 6. Tests

12. `server-components/tests/test_workspace_mutations.py` and
    `test_workspace_reads.py` — the registry tests
    (`test_every_registered_kind_names_a_real_service_function`,
    `test_advertised_kinds_are_the_registry`) cover the new kinds for free once
    registered; confirm they do rather than assuming.
13. New executor coverage, following
    `test_execute_runs_the_registered_service_as_the_requesting_user`: a hosted
    `dfm_rpc_bridge_sync` writes its request file with the *submitting* user's
    `UserName`, not the process account.
14. New client-transport coverage in `frontend/tests/`, following
    `test_workspace_read_client.py` and the mutation client's
    `test_an_accepted_request_is_never_re_run_locally`: an accepted
    `update_remote` is never retried over SMB; a kind the gateway does not
    advertise runs locally and produces today's request file.
15. A response-parity test: the same logical sync run locally and through the
    executor returns the same payload once paths are rebased.
16. Contract tests for the wait clamp and for refusal of a machine-local
    `project_name` / `reserving_class` (the mutation contract's
    `validate_project_name` / `validate_reserving_class_path` already enforce
    this; pin it for these kinds).

### 7. Docs and release fragment

17. `frontend/docs/app_server/domains/dfm_rpc_bridge.md` and
    `result_selection_rpc_bridge.md` — add a transport paragraph to **External
    Interfaces** stating that these routes run on the Gateway when the
    capability is advertised, that the request file and Bridge contract are
    unchanged, and that `UserName` now names the submitting user.
18. `frontend/docs/app_server/domains/workspace_reads.md` and
    `workspace_mutations.md` — list the new kinds.
19. Append an "Implemented" note to
    [hosted_workspace_http_transport.md](hosted_workspace_http_transport.md),
    which currently records the RPC bridge as not moved.
20. One fragment in `frontend/changes/unreleased/`, `type: improvement`,
    `scope: dfm`, audience `user`: DFM and Result Selection sync now run on the
    ArcRho Server instead of the network drive.
21. Regenerate the generated indexes with
    `python frontend/tools/docs_index_builder.py --write` and confirm
    `--check` passes; only AUTO-GEN blocks are rewritten, so the manual
    paragraphs above stay as written.

### 8. Deploy and measure

22. Rebuild the Gateway through `python server-components/deploy.py gateway`, per the
    deployment authorization in `AGENTS.md` — the server-side Build Listener
    does the work; check its heartbeat `Repository` first.
23. Verify `GET http://NE7SASWPN02.PRCINS.NET:28767/api/capabilities` lists the
    new kinds under `workspace_read_kinds` and `workspace_mutation_kinds`.
24. Re-measure a real sync and read the transport back out of
    `%LOCALAPPDATA%\ArcRho\logs\client_read_latency.jsonl` — records appear as
    `read_kind: mutation:dfm_rpc_bridge_sync` with `transport`, `remote_ms`, and
    `reason`. Compare against the 2026-08-18 baseline at the top of this plan.

## Measured after the change

Same Client PC and project as the baseline, 2026-08-19, best of three warm
calls, with the Gateway advertising all ten kinds:

| Route | SMB | Hosted | |
| --- | --- | --- | --- |
| `POST /dfm/rpc-bridge/compare` | 848 ms | **49 ms** | 17x |
| `POST /result-selection/rpc-bridge/compare` | 414 ms | **71 ms** | 6x |
| `POST /dfm/rpc-bridge/cleanup` (nothing to delete) | 61 ms | 54 ms | 1.1x |

The SMB column is already the improved single-parse version. Against the
version at HEAD the DFM comparison went 1,360 ms to 49 ms, roughly 28x, of
which the parse fix accounts for the first third and the transport the rest.
`sync` and `update-remote` were not measured end to end: doing so publishes a
real request that a live ResQ session must serve, and two other users' bridges
were running. Their SMB legs are the ones already measured in the baseline --
about 1 s to publish the request file and 0.65 s per wait tick -- and both
become a single signed POST plus the Bridge's own time.

## Follow-on fix: the timestamp an upload leaves behind

Reported 2026-08-19 and fixed the same day for DFM. `update-remote` writes
ArcRho's settings into the RPC server and ResQ saves them under its own
`Modified`, so the moment an upload succeeded the two copies held identical
settings under different times and the next review window ranked the remote
newer -- inviting the user to pull back exactly what they had just pushed.

The fix records the time ResQ itself reported rather than stamping this
machine's clock. That distinction is the whole point: `_compare_state` matches
on the instant, so a local `now` is a different instant by the round trip plus
whatever the two clocks disagree about, and on a client whose clock trails the
server the remote still wins. Copying ResQ's value is the only version that
converges, which is what the reporter proposed.

- `resq_client.write_sync_dfm_payload` reads `OutputVector.Modified` *after*
  `Save()` and reports it as `last modified` on the status JSON.
- `dfm_contract.stamp_last_modified` owns the field, as it owns every other
  part of the method projection.
- `dfm_service.record_rpc_sync_last_modified` writes it under the reserving
  class lock through the same atomic commit a save uses.
- `dfm_rpc_bridge_service.update_remote` calls it after a successful status and
  reports the outcome as `last_modified_record`.

What makes this safe to do outside a save is that `last modified` is outside
the owned, derived, and publication projections -- pinned by a test -- so the
record cannot shift a revision, cannot invalidate the save token an open DFM
tab holds, and cannot make a dependent look stale. An older Bridge reports no
value, and the local timestamp is then left exactly as it is today.

**Result Selection followed the same day**, once the thing that blocked it was
dealt with. Its `method_revision` hashed the whole method file, timestamp
included, so recording ResQ's save time would have moved the token an open
editor saves with -- and the RS sync dialog does not reload after an upload.
`_revision_projection` now excludes `method_metadata.last_modified`, which makes
RS consistent with DFM, BF, CC and bootstrap: all four revision a projection
through `dfm_contract.method_revisions` that never reaches the timestamp.

That change crosses a version boundary and needed a shim. A revision is minted
where the method loads -- a Client PC's own app server, or the Gateway -- and
checked where it saves, which is always ArcRho Engine, and those upgrade
separately. Without care, a client app built before this change would mint the
old whole-file form while the Engine computed the new one, and *every* RS save
would be refused with no way for the user to recover by reloading.
`save_result_selection` therefore accepts either form, through
`_legacy_method_revision`, until every installed app carries the change; the
deploy order is Engine before Gateway for the same reason.

One existing test changed meaning rather than breaking:
`test_save_rejects_a_stale_open_method_revision` used a timestamp-only rewrite
as its stand-in for "somebody else edited this", which is exactly what no longer
counts as stale. It now edits the content, and two tests were added beside it for
the new contract -- a timestamp-only rewrite keeps an open method saveable, and a
legacy revision is still accepted.

## Deferred and optional

**`apply` and its double save.** `apply_remote_to_local` calls
`dfm_service.save_dfm_method` directly, in the app-server process on the Client
PC — so the merged method, its sidecar, the index refresh, and the dependent
enqueue all cross SMB, while every other DFM save goes through
`engine_hosted_save_service.run_hosted_save` on the Engine. The frontend then
saves *again*: `applyDfmOwnedPatchPayload` is followed by
`saveRatioSelectionPattern`, which uses the hosted route. Two candidate fixes:
have `apply` return the merged preview and let the frontend's existing hosted
save be the only write, or register `apply` as a hosted kind and leave the save
where it is. The first removes a redundant save entirely and puts the survivor
on its canonical owner, but it changes what is persisted when the tab save
fails, and it needs verification that the applied Method Notes reach the Notes
tab state so the frontend save still carries them. Worth its own decision
rather than riding along here.

**Bridge notice latency - done.** `run_bridge_worker`'s loop ended in
`time.sleep(1)`, so a watchdog event raised mid-sleep waited out the rest of
that second before `consume_scan_request` was checked: half a second of average
latency on every sync. The loop now idles in `handler.wait_for_scan_request(1)`,
which waits on the same event and leaves the flag set for the scan check at the
top of the loop, so a local event is answered immediately while the periodic
rescan a share needs keeps its one-second ceiling. Bridges are per user session,
so this lands for each user as their bridge restarts. Deployed 2026-08-19 on the
third attempt: two earlier deploys failed their folder swap with `WinError 5`
and the third, unchanged, swapped with no retry at all. The deploy waits for
every bridge heartbeat to disappear before renaming, so the live ResQ sessions
were never the holder.

**Service duplication.** `dfm_rpc_bridge_service.py` (663 lines) and
`result_selection_rpc_bridge_service.py` (495 lines) overlap heavily. Eleven
functions are byte-identical once the request type is renamed — 144 lines,
about 29% of the RS file — including the whole request-file writer
(`_write_request_file`), `_require_project_dir`, `_try_remove`, `_read_json`,
`_file_meta`, `_compare_state`, `send_sync_request`, and `cleanup_tmp`. Nine
more share a name and a shape while differing: `keep_local` only in its message
text, `build_paths` only in named-versus-inline locals.

What a shared core would have to parameterize is genuinely per-family, and one
item is more than a naming difference:

- **Metadata key spelling.** DFM method JSON uses spaced keys
  (`"method metadata"`, `"last modified"`); RS uses underscores
  (`method_metadata`, `last_modified`) — confirmed against a real RS file in
  `NJ_Annual_Prod_202605_Fake`. `_json_last_modified_meta` cannot be shared
  without a per-family key map, and the divergence itself deserves a separate
  look.
- **Request projection.** DFM sends `OutputVector`, `InputTriangle`,
  `DevelopmentLength`, and `DecimalPlaces`; RS sends `OutputVector` set to the
  method name plus `OutputType`, and neither length nor decimals.
- **Filename prefixes** and the sync-status file name.
- **Compare response.** RS returns server-built `labels` and `actions`; DFM
  returns neither and its dialog derives them client-side. The same dialog
  contract is therefore built in two places, one per transport side.
- **Snapshot extractors** (ratio pattern, average formulas, cell notes, method
  notes vs weights and sources) are correctly per-family and should stay that
  way, as should `apply_remote_to_local`.

The shape that follows is a frozen `RpcBridgeFamily` descriptor — function
names, filename prefixes, metadata key spellings, request-field projection, and
a snapshot builder — with one core module owning path building, the request
write, file metadata, compare state, and the sync/cleanup/keep-local trio. That
would delete ~144 lines outright and collapse perhaps 60 more.

Two things to fix while in there: `_build_method_filename` in the DFM service
takes an `include_lengths` keyword it explicitly discards (`_ = include_lengths`)
and that two of its three call sites still pass; and the compare double-read in
step 11 above.

The matching frontend pair (`result_selection_rpc_bridge_client.js` 205 lines,
`..._dialog.js` 795) is a weaker case — only 23% and 33% of their lines match
the DFM originals, because the DFM dialog has grown pattern grids, average
formulas, cell notes, method notes, and the ArcBot approval flow that RS has no
equivalent for. Leave the frontend alone.

Sequencing: do this **after** the transport lands, not before. The transport
change adds only five small wrappers per service, so consolidating first saves
little, while merging a wide rewrite into a measurable perf change would make
both harder to evaluate and to roll back. It also needs parity tests first —
today the only coverage is `test_dfm_rpc_bridge_owned_patch.py` and
`test_rpc_bridge_last_modified_timestamp.py`, neither of which would catch a
regression in path building or request-file contents.

## Risks

- **Any bridge worker claims any request.** With two ResQ sessions live, a sync
  submitted by one user can be served by another's ResQ. Pre-existing, unchanged
  here, but hosting makes the request's `UserName` accurate for the first time,
  which is the prerequisite for fixing it later.
- **Refusal text loses server paths** through `_redact_machine_paths`. Check how
  the sync dialog renders a locked-file error before and after.
- **A Client PC without the gateway credential** keeps the current behavior
  exactly; that is the rollback, and it needs no code path of its own.
- **The 10 s second cleanup call** after the dialog closes is deliberate — it
  catches a response the Bridge writes after the user walked away. Keep it; it
  becomes nearly free.
- **Timeout semantics move.** Today the 8 s budget is spent partly on SMB
  visibility lag; hosted, all 8 s is real Bridge time. A sync that used to time
  out because the client could not *see* the file will now succeed, and the
  timeout message should stop implying a stale share read.

## Open items

- Whether `compare` should return a payload digest so the dialog's Refresh can
  short-circuit when nothing changed.
- Whether `sync` should carry a client-owned request id, so a repeat after a
  lost response can be recognized rather than re-exported by ResQ.
- Whether the RS bridge's `apply` differs enough from DFM's to need its own
  decision in the deferred item above.
