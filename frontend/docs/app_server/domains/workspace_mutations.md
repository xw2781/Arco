# App Server Domain: Workspace Mutations (Server-Hosted Transport)

## Purpose
<!-- MANUAL:BEGIN -->
- The ResQ review macro publishes through `resq_review_request_publish` into the existing sync queue. It shares the import publisher's identity checks, signed-user stamping and idempotence by request id; Gateway failures never cause a client request-file write.
Run reserving-class file mutations that a Client PC would otherwise perform one SMB round trip at a time on the ArcRho Server host over HTTP. Like [`workspace_reads`](workspace_reads.md) this is a transport, not a domain of its own: the canonical `app_server` service function still owns the operation and runs unchanged either locally or inside the machine-wide ArcRho Gateway.

It is a separate registry and a separate route from workspace reads because the reasoning that makes a read safe does not carry over. A read is a pure function of the workspace, so an uncertain answer may simply be asked again or answered locally instead; a mutation may not. Every registered mutation kind must either be **idempotent** — running it twice leaves the same end state as running it once, so a lost answer is safe to ask about again — or be marked `receipt`, in which case the Gateway keeps the first run's outcome under the signed user and request id and answers a repeat from it (see "Receipts" below). Anything that needs an Engine claim or the reserving-class lease belongs on the hosted-save path (`arcrho_hosted_save_http_contract`).
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->
No new browser-facing route. This existing route selects the transport per request through `workspace_mutation_client.run_workspace_mutation`:

| Route | Mutation kind | Service |
| --- | --- | --- |
| `POST /datasets/cached/delete` | `cached_dataset_delete` | `dataset_service.delete_cached_datasets` |
| `POST /datasets/review-status` | `dataset_review_status_set` | `dataset_service.set_dataset_review_status` |
| `POST /dfm/rpc-bridge/sync` | `dfm_rpc_bridge_sync` | `dfm_rpc_bridge_service.hosted_send_sync_request` |
| `POST /dfm/rpc-bridge/keep-local` | `dfm_rpc_bridge_keep_local` | `dfm_rpc_bridge_service.hosted_keep_local` |
| `POST /dfm/rpc-bridge/cleanup` | `dfm_rpc_bridge_cleanup` | `dfm_rpc_bridge_service.hosted_cleanup_tmp` |
| `POST /dfm/rpc-bridge/update-remote` | `dfm_rpc_bridge_update_remote` | `dfm_rpc_bridge_service.hosted_update_remote` |
| (no route; the ResQ sync and export macros call `run_workspace_mutation` directly through `arcrho_api.resq_sync_queue.submit_sync_request`) | `resq_sync_request_publish` | `resq_sync_queue_service.publish_resq_sync_request` |
| (no route; the two ResQ import macros call `run_workspace_mutation` directly through `arcrho_api.resq_import_backup.back_up_reserving_class`) | `resq_import_backup` | `resq_import_backup_service.back_up_reserving_class_for_import` |
| (no route; the two ResQ import macros call `run_workspace_mutation` directly from `publish_import_request`, Gateway-required) | `resq_import_request_publish` | `resq_import_queue_service.publish_resq_import_request` |
| `POST /audit_log`, and every client-process caller of `audit_service.safe_append_project_audit_log` (see [`audit_log`](audit_log.md)) | `project_audit_log_append` | `audit_service.append_project_audit_log` |
| `POST /reserving_class_hidden_paths` | `reserving_class_hidden_paths_save` | `reserving_class_service.save_hidden_paths` |
| `POST /reserving_class_filter_spec` | `reserving_class_filter_spec_save` | `reserving_class_service.save_filter_spec` |
| `POST /project-user-preferences` | `project_user_preferences_update` | `project_user_preferences_service.update_preferences` |
| `POST /arcrho/headers/cache/clear` | `arcrho_headers_cache_clear` | `arcrho_runtime_service.clear_arcrho_headers_cache` |
| `POST /project_settings/{source}/create_project_folder` | `project_folder_create` (receipt) | `project_settings_service.create_project_folder` |
| `POST /project_settings/{source}/rename_project_folder` | `project_folder_rename` (receipt) | `project_settings_service.rename_project_folder` |
| `POST /project_settings/{source}/delete_project_folder` | `project_folder_delete` (receipt) | `project_settings_service.delete_project_folder` |
| `POST /project_settings/{source}` | `project_registry_save` (receipt) | `project_settings_service.update_project_settings` |
| `POST /general_settings` | `general_settings_save` (receipt) | `project_settings_service.update_general_settings` |
| `POST /project_settings/{source}/generated_dataset_cache/clear` | `generated_dataset_cache_clear` | `project_settings_service.clear_generated_dataset_csv_caches` |
| `PUT /dataset/number-format-defaults` | `dataset_number_format_defaults_save` (receipt) | `dataset_number_format_service.save_preferences` |
| `POST /dataset_types` | `dataset_types_save` | `dataset_types_change_service.save_dataset_types` |
| `POST /project_settings/{source}/duplicate_project_folder` | `project_duplication_submit` | `project_settings_service.duplicate_project_folder` |
| `POST /project_settings/{source}/duplicate_project_folder/cancel/{request_id}` | `project_duplication_cancel` | `project_settings_service.cancel_duplicate_project_folder` |
| `POST /field_mapping` | `field_mapping_save` (receipt) | `field_mapping_service.save_field_mapping` |
| `POST /source_table/profile` | `source_profile_save` (receipt) | `source_table_service.save_source_profile` |
| `POST /source_table/scope` | `source_scope_save` | `source_table_service.record_refresh_scope` |
| (no route yet; the combined source save) | `source_combined_save` (receipt) | `source_table_service.save_combined_source` |
| `GET /source_table/refresh_job/plan` (only when the stored CSV path is a drive letter this PC can translate) | `source_csv_path_rewrite` | `source_table_service.rewrite_source_csv_path` |
| `POST /reserving_class_types` | `reserving_class_types_save` (receipt) | `reserving_class_service.save_reserving_class_types` |
| `POST /table_summary/refresh` | `table_summary_rebuild` | `table_summary_service.rebuild_table_summary` |
| (no route; `source_table_service.submit_mssql_connection_remember`, after a SQL Server listing or import on this PC) | `mssql_connection_remember` | `source_table_service.remember_mssql_connection` |
| `POST /source_table/connections/forget` | `mssql_connection_forget` | `source_table_service.forget_mssql_connection` |
| `POST /source_table/import`, `POST /source_table/refresh` (one per chunk of a source only this PC can read) | `source_table_upload_chunk` | `source_table_upload_service.receive_source_table_chunk` |
| `POST /source_table/import`, `POST /source_table/refresh` (once, after the last chunk) | `source_table_upload_commit` | `source_table_upload_service.commit_source_table_upload` |
| `POST /source_table/refresh_job` | `source_table_refresh_submit` | `source_refresh_service.submit_source_table_refresh_job` |

The three preference writes (step 8 of [client_smb_retirement.md](../../../../docs/plans/client_smb_retirement.md)) change only the signed-in user's own `users/<login>/preferences.json`: the login is the acting identity of the signed request, never an argument. Each is Gateway-required. They are idempotent because each is a whole-value write: the hidden-path list and the filter spec (with the tree preferences when sent) replace the stored value outright, and a preferences patch sets each value it names, so a repeat lands the same state and only `updated_at` moves.

The header cache clear (step 11) is Gateway-required. It deletes the project's period-heading CSVs so the Engine rebuilds them; it is idempotent because a repeat finds the files already gone and answers `cleared_count: 0`.

The six Project Settings writes (step 13 of the plan) are Gateway-required. Creating, renaming and deleting a project folder and saving the registry are not idempotent — a repeated create or rename meets the folder the first run made and refuses with `409`, a repeated registry save meets the revision the first run moved — and the General Settings save appends an audit entry each run, so all five carry a receipt. Clearing the generated CSV caches is idempotent: a repeat finds nothing left to clear and writes no audit entry. Opening a project folder in Explorer stays on the client, because it hands a path to a program on this PC.

The dataset number-format defaults save (step 19) is Gateway-required and carries a receipt: it is checked against the revision the window read and moves it, so a repeat would meet its own revision and refuse with `409`. The row names the signed user as `updated_by`.

The dataset-type table save and the project duplication submit and cancel (step 14) are Gateway-required. The two job submits are already keyed by the client's request id, so they are idempotent without a Gateway receipt, and that same id travels as the mutation's own: a replayed dataset-type change returns the job already queued (`resumed: true`), and a replayed duplication answers from the duplication's own submission receipt, which also refuses the id under a different source or target. The table save also decides whether the change needs the job at all; its direct write of a presentation-only change skips a table that already holds those rows, so a replay writes nothing and appends no second audit entry. A duplication cancel writes an advisory marker, and a repeat writes the same one.

The Source Data writes (step 15) are Gateway-required. The field mapping, import profile and reserving class types saves append an audit entry each run, so they carry a receipt. A CSV path is translated from this PC's drive letters into the share it stands for on the client, because only this PC has that mapping, and reaches the server as data: the profile save and the field mapping save receive the share path, and the refresh plan's `source_csv_path_rewrite` names both spellings and changes the stored path only while it still reads the drive letter, so a repeat writes nothing. The table-summary rebuild derives the summary and the reserving-class values from the imported table alone, and remembering or forgetting a SQL Server pair sets the same list again, so those are idempotent. The source refresh submit also became Gateway-required here, so a Client PC no longer writes the job's request file over the share. A source only this PC can read (`POST /source_table/import`, `POST /source_table/refresh`) is read on the client and uploaded (step 22): each `source_table_upload_chunk` is stored as its numbered part of the upload, so a resent chunk overwrites the same part, and `source_table_upload_commit` checks the chunk count, byte total and row count, swaps the master table in atomically and keeps its answer with the upload, so a repeat answers from it; neither needs a receipt. The chunks stay well inside the 256 KiB request limit. See [`source_table`](source_table.md).

The review-status set is the Project Instance `Mark For Review` / `Set
Reviewed` action, shared by the dataset table and Dependency Graph context
menu. Like every mutation it requires the Gateway on Client PCs and is refused
when the Gateway is not signed in, does not offer it, or does not answer. Server processes retain
the canonical local service. It rewrites one sidecar per selected method output
on the server's local disk. It is a human sign-off on values nobody
touched: it writes `status`, `updated_at` and `modified_by`, appends the one
audit record naming the decision, and does nothing else -- it marks no
dependent and enqueues no propagation walk, exactly as a notes edit does. The
audit record is an `Update` carrying the moment and the signer, with
`change_info` of `Marked For Review` or `Set Reviewed`
(`arcrho_api.sidecar_audit_contract`) rather than the `Values` default, since
the decision moved no number. It refuses nothing and raises nothing for an
object it cannot act on -- a dataset no method wrote, or a name with no
sidecar -- and reports it under
`skipped` instead. It is idempotent because an object already carrying the
requested flag is reported under `unchanged` rather than rewritten, so a repeat
leaves the same status, timestamp, user and audit log the first run wrote.

The ResQ sync-queue publish is the request file the Sync and Export Reserving
Class with ResQ macros hand to a ResQ-connected Bridge worker. The payload and
the on-disk write are `arcrho_api.resq_sync_queue`'s own; the service adds only
the place it is written from and stamps the acting user's login as the
request's `UserName`. It is idempotent by request id — an id that already has
a request or a status file is returned as `resumed` — and the macro's polling
of that request's status is the hosted `bridge_worker_liveness` read, so
inside the app neither half of the exchange crosses the share.

The ResQ import backup is the copy both import macros take of the reserving
class they are about to rewrite. It is the largest of these kinds by file
count -- every method, every sidecar a person could have edited, every data
file those sidecars name, and the class index -- so from a Client PC it was one
SMB round trip per file, plus a class-folder lookup that can read one index per
reserving class of the project. Hosted, the whole copy is local disk and the
macro pays one request. The copy itself, the folder layout, the retention rule
and what it leaves out are all `arcrho_api.resq_import_backup`'s; the service
adds only the place it runs and stamps the acting user's login into the
manifest. It is idempotent by backup id: the macro owns the id, and an id whose
copy this host already finished -- which its `backup.json` records -- is
reported as it stands rather than copied again under a second folder. A copy
that died part way leaves no manifest and is never presented as a restore
point. Because a backup that cannot be taken never stops an import, the macro
turns a transport failure into a warning rather than an error, and words an
unconfirmed outcome as unknown rather than as "no restore point".

The ResQ import request itself is published the same way as the sync
request (added by step 16 of client_smb_retirement.md). The macro builds the
request -- a macro must stand on its own -- so the service restates none of
its fields: it checks that the request names the project, reserving class and
id the mutation was validated for, stamps the signed user's login, and writes
it into the Bridge's import queue on the server's own disk. It is idempotent
by request id, like the sync publish. The macro calls it Gateway-required, so
a Gateway that cannot take the request stops the import rather than writing
the queue over the share. Macro version 1.15.0 carries this and needs the app
release that registers the kind; the released app's contract does not know it.

The RPC-bridge kinds are the one family whose work is not finished when the
service returns from local disk: `sync` and `update-remote` publish a request
file and then wait for the ArcRho Bridge to answer. The Bridge runs on the
server host, so hosting these puts both halves of that exchange on local disk,
where the wait is a file-system event rather than a poll that must write and
delete a probe file to defeat the SMB redirector's cached "not found". Their
keyword arguments are the route schema's own fields and the service rebuilds
its request model from them, so pydantic stays the only validator; the wait a
caller may ask the Gateway to hold a thread for is clamped by
`clamp_rpc_bridge_wait`.

Gateway side: `POST /api/workspace-mutations` on the Gateway (`arcrho_workspace_mutation_contract.WORKSPACE_MUTATION_PATH`), authenticated with the same per-user HMAC headers as hosted saves and workspace reads. `GET /api/capabilities` advertises `workspace_mutation_kinds`.
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `python-api/src/arcrho_workspace_mutation_contract.py` - The canonical `WORKSPACE_MUTATION_KINDS` registry (kind → service module, function, required/optional keyword arguments, and which of them are name lists), request validation, route path, and timeout.
- `app_server/services/workspace_mutation_client.py` - Client transport and the unconfirmed-after-acceptance rule. It reuses the read transport's signing, capability probe cache, `post_signed_json`, and path rebasing rather than repeating them.
- `server-components/src/arcrho_gateway/workspace_mutations.py` - Server-side executor: authenticates, validates against the registry, imports the bundled service, runs it under `acting_identity`, and maps a service `HTTPException` to the same status while preserving a structured refusal detail.
- `server-components/src/arcrho_gateway/receipts.py` - The Gateway's one receipt store (atomic write, read, per-receipt lock, startup expiry), shared with hosted saves.
- `server-components/src/arcrho_gateway/main.py` - Route dispatch and the capability field; the handler is the one `_handle_hosted_execution` shared with reads and calculations.
- `server-components/src/arcrho_gateway/build_exe.py` - Registered mutation service modules join the hidden-import list and the pre-build import probe automatically.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Transport selection matches workspace reads exactly (`require_client_gateway`): a process running with `ARCRHO_RUNTIME_SERVER_ROOT` set (Engine, Bridge, Gateway) always runs in place so the gateway can never route back to itself; a Client PC always sends the mutation to its Gateway and never writes the workspace itself. Not signed in, a silent Gateway, a Gateway without the kind, and a refused signature are the same `401` / `503` answers a read gives.
- The one real difference from reads: a timeout or a connection lost after the request was sent surfaces as `504` telling the user to refresh and look, because the server may already have applied it.
- A refusal raised by the hosted service itself is recognized by the `X-ArcRho-Workspace-Root` header the gateway sets whenever the operation ran, and passes through with the status the local path would have raised.
- Structured refusals survive the wire. `POST /datasets/cached/delete` answers `409` with an object (`error`, `message`, `blocked_datasets`) that Project Instance renders as the dependents window, so the transport preserves a mapping `detail` instead of flattening it to text; only its free text is redacted for server paths.
- Path rebasing is the read transport's: every string in the response that starts with the server's workspace root is rewritten onto this PC's own root, so `deleted_files[].path` and the returned `index.folder_paths` look exactly as a local delete would have produced them.
- Identity: the request carries the enrolled `UserName` and an empty display name, which the server resolves from the signed login; the gateway binds `user_identity_service.acting_identity` around the mutation so anything it stamps on disk names the person who asked.
- Receipts: a kind marked `receipt` (`WorkspaceMutationKind.receipt`) is not idempotent, so the Gateway writes `runtime\arcrho_gateway\receipts\mutations\<user>\<request id>.json` (`mutation_receipt_path`) before running it and records the outcome — the response, or the refusal's status and detail — when it finishes, holding one lock per receipt for the whole run. A repeat of the same request under that id waits on the lock and answers from the receipt without running the service; a different request under the same id is refused with `409`; a receipt left `accepted` by a Gateway that stopped part way answers `409` telling the user to refresh. Keying by the signed user means two users never meet each other's outcome. A route may take the request id from its body (`request_id`) so a caller's repeat of one action reuses it; otherwise the client makes one per call, and when the answer is lost after the server had the request (a dropped connection or an unreadable reply, not a timeout) the client sends that same request once more and reports the replayed outcome. Receipts share the hosted-save receipt store and its retention: the Gateway removes terminal receipts older than `receipt_retention_hours` (24 by default) when it starts. Idempotent kinds keep no receipt.
- Project lock: a kind whose `locked_project_arg` names one of its arguments changes that project's shared data, so `project_lock_service.require_mutation_allowed` refuses it with `423` while the project is locked. The Gateway executor runs that check before the service, and so does a server process running the kind in place. Leave the field empty for a kind that touches only a user's own preferences, a regenerable cache or a preview.
- Diagnostics: one record per mutation in `client_read_latency.jsonl`, keyed `read_kind: "mutation:<kind>"`, with the same `transport` / `reason` / timing fields the reads use.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Move another mutation to the server: decide whether it is idempotent (mark it `receipt=True` if not), add one `WorkspaceMutationKind` entry naming the service function and its keyword arguments (listing any list-valued argument in `list_args`), then wrap the route's service call in `workspace_mutation_client.run_workspace_mutation(...)`. `test_workspace_mutations.py` fails if the registry names an argument the function lacks or omits one it requires; the gateway build validates the import graph and bundles the module automatically. Rebuild and redeploy the gateway.
2. If the operation needs an Engine claim or the reserving-class lease, do not add it here — put it on the hosted-save path instead.
3. A refusal the page acts on rather than merely displays should raise a mapping `detail` from the service. Both transports deliver the same object, so the page needs one shape; keep any server path out of the structured fields, because only free text is redacted.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- The idempotence requirement is a contract promise, not something the transport can verify. A kind registered without `receipt` that quietly stops being idempotent would turn a lost response into a silently wrong end state.
- The gateway is one process for the whole fleet, and a mutation holds a handler thread for its whole run; a large delete competes with hosted saves and reads in the same process.
- The pilot transport is plain HTTP with HMAC, so dataset names travel unencrypted on the internal network. TLS is the first gate before broader rollout.
<!-- MANUAL:END -->
