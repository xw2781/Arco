# App Server Domain: Workspace Reads (Server-Hosted Transport)

## Purpose
<!-- MANUAL:BEGIN -->
Run the expensive workspace reads a Client PC performs — the reserving-class dataset/method index, a cached-dataset load, a method-window load, and the Project Settings table summary — on the ArcRho Server host over HTTP instead of over the mapped drive. This is a transport, not a domain of its own: the canonical `app_server` service function still owns each read, and it runs unchanged either locally or inside the machine-wide Arco Gateway, which freezes the same `frontend/app_server` and `python-api/src` trees the Engine does.
- Project Instance Help JSON views use `project_instance_json`, which reads the raw method or sidecar on the server and rejects filenames outside the selected class folder. The batch ResQ import uses `resq_class_inventory` for its class counts.
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->
No new browser-facing route. These existing routes select the transport per request through `workspace_read_client.run_workspace_read`:

| Route | Read kind | Service |
| --- | --- | --- |
| `GET /datasets/cached`, `GET /dfm/method-index` | `dataset_index` | `dataset_service.list_cached_dataset_names` / `dataset_instance_index_service.get_index` |
| `POST /dataset/cache/load` | `dataset_cache_load` | `dataset_service.load_cached_dataset_values` |
| `GET /dataset/{ds_id}` | `dataset_grid_load` | `dataset_service.get_dataset` |
| `POST /dfm/method/load` | `dfm_method_load` | `dfm_service.load_dfm_method` |
| `POST /result-selection/load` | `result_selection_load` | `result_selection_service.load_result_selection` |
| `POST /bornhuetter-ferguson/load` | `bornhuetter_ferguson_load` | `bornhuetter_ferguson_service.load_bornhuetter_ferguson_method` |
| `POST /cape-cod/load` | `cape_cod_load` | `cape_cod_service.load_cape_cod_method` |
| `POST /bootstrap/load` | `bootstrap_load` | `bootstrap_service.load_bootstrap_method` |
| `POST /bootstrap/simulate` | `bootstrap_simulate` | `bootstrap_service.simulate_bootstrap_method` |
| `POST /stochastic-consolidation/load` | `stochastic_consolidation_load` | `stochastic_consolidation_service.load_stochastic_consolidation_method` |
| `POST /stochastic-consolidation/consolidate` | `stochastic_consolidation_consolidate` | `stochastic_consolidation_service.consolidate_stochastic_consolidation_method` |
| `POST /stochastic-consolidation/segments/candidates` | `stochastic_consolidation_candidates` | `stochastic_consolidation_service.list_stochastic_consolidation_candidates` |
| `POST /excel_links/list` | `excel_link_listing` | `excel_link_service.list_reserving_class_excel_links` |
| `POST /excel_links/check` | `excel_link_value_check` | `excel_link_service.check_reserving_class_excel_link_values` |
| `POST /excel/read_cells_batch` | `excel_cell_values` | `excel_service.excel_read_cells_batch` |
| `GET /datasets/dependency-graph` | `dataset_dependency_graph` | `dataset_dependency_graph_service.build_reserving_class_dependency_graph` |
| `GET /reserving_class_paths_with_data` | `reserving_classes_with_data` | `reserving_class_service.list_reserving_classes_with_data` |
| `GET /table_summary` | `table_summary` | `table_summary_service.get_table_summary` |
| `POST /dfm/rpc-bridge/compare` | `dfm_rpc_bridge_compare` | `dfm_rpc_bridge_service.hosted_compare` |
| (no route; the ResQ import and sync macros call `run_workspace_read` directly through `arcrho_api.bridge_liveness.observe_bridge_liveness`) | `bridge_worker_liveness` | `bridge_liveness_service.get_bridge_worker_liveness` |
| `GET /server/status` (only for a server folder that is not on a fixed disk of this PC) | `server_component_status` | `server_component_status_service.get_server_component_status` |
| `GET /audit_log` | `project_audit_log` | `audit_service.read_audit_log` |
| `GET /project_settings` | `project_settings_sources` | `project_settings_service.list_project_settings_sources` |
| `GET /project_settings/{source}/folders` | `project_folders` | `project_settings_service.get_project_folders` |
| `GET /project_settings/{source}` | `project_registry` | `project_settings_service.get_project_settings` |
| `GET /arcrho/projects` | `project_names` | `arcrho_runtime_service.arcrho_projects` |
| `GET /general_settings` | `general_settings` | `project_settings_service.get_general_settings` |
| `GET /dataset_types` | `dataset_types_table` | `dataset_types_service.get_dataset_types_table` |
| `GET /field_mapping` | `field_mapping` | `field_mapping_service.get_field_mapping` |
| `GET /source_table`, `GET /source_table/file_status` | `source_table_settings` | `source_table_service.read_source_table_settings` (the client adds its own `driver_available` and stats the external CSV itself) |
| `GET /source_table/connections` | `mssql_connections` | `source_table_service.load_mssql_connections` |
| `GET /dataset/number-format-defaults` | `dataset_number_format_defaults` | `dataset_number_format_service.get_preferences` |
| `GET /app/user-identity` | `user_identity` | `user_identity_service.get_current_identity` (under the signed user's acting identity) |
| `GET /data_processing_rules` | `data_processing_rules` | `data_processing_rules_service.read_data_processing_rules` |
| `POST /data_processing_rules/validate` | `data_processing_rules_validate` | `data_processing_rules_service.check_data_processing_rules` |
| `GET /reserving_class_combinations` | `reserving_class_combinations` | `reserving_class_service.read_reserving_class_combinations` |
| `GET /reserving_class_path_tree/children` | `reserving_class_path_tree_children` | `reserving_class_service.read_reserving_class_path_tree_children` (writes nothing) |
| `GET /reserving_class_types` | `reserving_class_types` | `reserving_class_service.read_reserving_class_types` (writes nothing) |
| `GET /reserving_class_hidden_paths` | `reserving_class_hidden_paths` | `reserving_class_service.read_hidden_paths` (the signed user's file) |
| `GET /reserving_class_filter_spec` | `reserving_class_filter_spec` | `reserving_class_service.read_filter_spec` (the signed user's file) |
| `GET /project-user-preferences` | `project_user_preferences` | `project_user_preferences_service.get_preferences` (the signed user's file) |
| `POST /dataset/sidecar/load` | `dataset_sidecar_load` | `dataset_service.load_dataset_sidecar` |
| `POST /dataset/calculated/preview` | `dataset_calculated_preview` | `calculated_dataset_service.preview_dependents` |
| `POST /dfm/method/dataset-references/resolve` | `dfm_dataset_references_resolve` | `dfm_service.resolve_dfm_dataset_references` |
| `GET /dfm/percent-developed-curve` | `dfm_percent_developed_curve` | `dataset_instance_index_service.get_percent_developed_curve` |
| `GET /dfm/development-pattern` | `dfm_development_pattern` | `dataset_instance_index_service.get_development_pattern` |
| `POST /object_change/fingerprint` | `object_change_fingerprint` | `object_change_watch_service.object_change_fingerprint` |
| `POST /object_change/attribution` | `object_change_attribution` | `object_change_watch_service.object_change_attribution` |
| `GET /datasets/cached/index-signature` | `dataset_index_signature` | `dataset_service.get_cached_dataset_index_signature` |
| `POST /arcrho/headers` | `arcrho_headers` | `arcrho_runtime_service.get_project_headers` |
| `GET /dataset_types/change_job/status` | `dataset_types_change_status` | `dataset_types_change_service.get_dataset_types_change_status` |
| `GET /project_settings/{source}/duplicate_project_folder/status/{request_id}` | `project_duplication_status` | `project_settings_service.get_duplicate_project_folder_status` |
| `GET /source_table/refresh_job/status`, and the busy check of `GET /source_table/refresh_job/plan` | `source_refresh_status` | `source_refresh_service.get_source_table_refresh_status` |
| `POST /source_table/refresh` (before resuming an interrupted upload) | `source_table_upload_status` | `source_table_upload_service.get_source_table_upload_status` |
| `GET /scripting/macro-library`, `POST /scripting/macro-library/sync` | `macro_library_listing` | `macro_library_service.read_library_files` |
| `POST /scripting/macro-library/install`, and the check before `POST /scripting/run-macro` | `macro_library_file` | `macro_library_service.read_library_file` |
| `GET /arcbot/prompt-files` (called by the Electron host's ArcBot) | `arcbot_prompt_files` | `arcbot_prompt_service.read_arcbot_prompt_files` |
| `GET /arcbot/agent-skills` (called by the Electron host's ArcBot; also read by the Show Diagnostic Triangle macro) | `agent_skills` | `agent_skill_service.read_agent_skills` |
| `POST /dashboard/source/load` for an Arco Datasets source, once per project | `dashboard_dataset_table` | `dashboard_data_service.read_dataset_table` |
| `POST /dashboard/source/load` and `POST /dashboard/source/fields` for an Arco Source Table source, once per project | `dashboard_source_table` | `dashboard_data_service.read_source_table` |

The project configuration reads from `project_settings_sources` down were added by step 7 of [client_smb_retirement.md](../../../../docs/plans/client_smb_retirement.md). Each was Gateway-required from the start (since step 18 every read is), so a Client PC answers `401` or `503` rather than reading the share, and each service returns the route's whole answer, refusals included, so the two transports answer alike.

The reserving-class and project-user-preference reads from `reserving_class_combinations` down were added by step 8, on the same terms; step 8 also made the existing `reserving_classes_with_data` read Gateway-required.

The dataset and method side reads from `dataset_sidecar_load` down were added by step 9, on the same terms. The dependents preview sends the whole edited grid, so a workspace-read request may be as large as a hosted save request (`MAX_WORKSPACE_READ_REQUEST_BYTES` is the hosted save contract's `MAX_REQUEST_BYTES`).

The three change-detection reads from `object_change_fingerprint` down were added by step 10. They are polled on a timer, so they go through `workspace_read_client.run_polled_workspace_read`: Gateway-required, but a `503` or `504` becomes the route's answer with `unknown: true` rather than an error, and the window asks again on its next poll. The server's stat is authoritative; a Client PC never stats the share for them.

The period headings (`arcrho_headers`) were added by step 11 and are Gateway-required. The settings check, the heading cache lookup and, on a miss, the Engine run all happen on the server host, so a Client PC neither publishes a request file nor reads the heading CSV; the route's pairs, including `StoredPeriodLength`, reach the service unchanged. See [`engine_calculations`](engine_calculations.md).

The two job status reads (`dataset_types_change_status`, `project_duplication_status`) were added by step 14. Both jobs are polled while they run, so they go through `run_polled_workspace_read` like the change-detection reads: a poll the Gateway cannot answer is `unknown: true`, and the page keeps polling without counting the gap as a stalled job. The status is read from the server's own disk, never over the share. The old `dataset_types_change_plan` read is gone: the plan is now built inside the `dataset_types_save` mutation.

The three supporting-file reads (`macro_library_listing`, `macro_library_file`, `arcbot_prompt_files`) were added by step 16 and are Gateway-required. The macro library reads return each macro's exact text, and the client compares it with its own macros folder and writes only there; a library the Gateway cannot answer for is reported as unavailable, and the check before a run leaves the local copy alone. The ArcBot read returns the entry prompt (`null` when the server has none) and every instruction file, bounded in size; the Electron host falls back to the prompt bundled with the app in memory, and nothing seeds the server's copy, which an administrator edits on the server. ArcBot's edit staging copies nothing from the share any more: a current method names no CSV and keeps none beside it, so step 4's class-CSV and linked-CSV copies had nothing to copy and were removed rather than given a read.

The source refresh status (`source_refresh_status`) became Gateway-required with step 15. The job poll goes through `run_polled_workspace_read` in the same way, so a poll the Gateway cannot answer is `unknown: true`; the refresh plan asks it once, without a job, for whether the project is busy.

Gateway side: `POST /api/workspace-reads` on the Gateway (`arcrho_workspace_read_contract.WORKSPACE_READ_PATH`), authenticated with the same per-user HMAC headers as hosted saves. `GET /api/capabilities` advertises `workspace_read_kinds`.
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `python-api/src/arcrho_workspace_read_contract.py` - The canonical `WORKSPACE_READ_KINDS` registry (kind → service module, function, required/optional keyword arguments), request validation, route path, timeout, and the `X-ArcRho-Workspace-Root` response header name.
- `app_server/services/workspace_read_client.py` - Client transport selection, capability probe cache (`cached_gateway_capabilities`), request signing and posting (`post_signed_json`, `GatewayTransportFailure` with its `accepted` flag), server-root path rebasing, `require_client_gateway` (the one Client-PC selection every hosted transport uses) and `failure_error`, and the read-latency record. The Engine calculation transport ([`engine_calculations`](engine_calculations.md)) reuses these helpers.
- `app_server/services/client_save_latency_log_service.py` - `append_client_read_latency` writes `%LOCALAPPDATA%\ArcRho\logs\client_read_latency.jsonl` (rotated like the save log).
- `server-components/src/arcrho_gateway/workspace_reads.py` - Server-side executor: authenticates, validates against the registry, imports the bundled service, runs it under `acting_identity`, and maps a service `HTTPException` to the same status.
- `server-components/src/arcrho_gateway/main.py` - Route dispatch and the capability field.
- `server-components/src/arcrho_gateway/build_exe.py` - Bundles `ENGINE_BUNDLED_SOURCES` and every registered service module into the gateway executable.
- The routers listed above - Each passes only the registry's arguments and supplies its local service call.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Transport selection, per request (`require_client_gateway`): a process running with `ARCRHO_RUNTIME_SERVER_ROOT` set (Engine, Bridge, Gateway) always reads in place so the gateway can never route a read back to itself. A Client PC always asks its Gateway and never runs the read itself or reads the share for it (decision 1 of the SMB retirement plan, 2026-09-27): a missing or unreadable `%APPDATA%\ArcRho\arcrho_gateway.json` credential is `401` "This PC is not signed in to the server. Sign in to the server again.", a Gateway whose `/api/capabilities` (cached 30 s on success, 10 s on failure) does not answer is `503` "The server can't be reached. Try again once it is back.", and one that does not list the read kind is `503` "The server needs updating before it can do this."
- Server identity: sign-up stores the `server_id` the Gateway reports in the local credential, and every capability probe (`hosted_save_http_client.probe_gateway`, behind `cached_gateway_capabilities` and the hosted-save probe) compares the Gateway's `server_id` with the credential's, so the check reads nothing from the server's folder. They must be equal; a credential signed up before ids were stored adopts the id of the first Gateway it probes (`remember_server_id`), and a Gateway without an id is accepted only by a credential without one. Anything else raises `GatewayServerMismatch` (409, "The server at this address is not the one this PC signed in to."), before the credential is sent. It protects against the hazard the id was introduced for (a credential used against a different server): the folder the app is pointed at is no longer where a Client PC gets its data, so it is not compared. Server processes skip the check.
- Failure rule: a refusal raised by the hosted service itself (404 method not found, 409 legacy pair, 423 lock, …) is recognized by the `X-ArcRho-Workspace-Root` header the gateway sets whenever the read ran, and passes through with the same status. A gateway-layer failure (`GatewayTransportFailure`) becomes the user's error through `failure_error`: a refused signature (401/403) is `401` "The server did not accept this PC's sign-in. Sign in to the server again." (the status bar and the Server tab offer Sign in again for both sign-in messages; see the `workspace_paths` domain), a Gateway without the route (404) is "needs updating", anything else "can't be reached". A gateway timeout (`WORKSPACE_READ_TIMEOUT_SECONDS`, 120 s) surfaces as `504`. A read a window polls on a timer (`run_polled_workspace_read`) answers `unknown` for a 401, 503 or 504 instead.
- Path rebasing: the gateway answers with the server's workspace root in `X-ArcRho-Workspace-Root`; the client rewrites every string in the payload that starts with that root onto its own `config.get_root_path()`, so `folder_paths`, the cached CSV `path`, `sidecar_path`, and the master table path look exactly as a local read would have produced them. Nothing else in the payload is touched.
- Per-process dataset handles carry their registered workspace-relative CSV location with `dataset_grid_load`. The Gateway validates that it is a CSV inside the named project and reads it on its own disk, including after a Gateway restart. Missing handles return 404; the client never reads the CSV as a fallback.
- Identity: the request carries the enrolled `UserName` and an empty display name, which the server resolves from the signed login (a Client PC never opens the username index); the gateway binds `user_identity_service.acting_identity` around the read so a load that performs a one-time on-disk upgrade (legacy DFM/RS) stamps the opening user, not the gateway's service profile.
- No idempotency receipt: reads keep no receipt and no request-ID replay; a lost response is simply retried by the caller.
- Bridge liveness (`bridge_worker_liveness`): the ResQ macros poll this once per second while a Bridge request runs. It answers with every worker heartbeat's age and usability, plus the polled request's status payload and the age of its status file, all measured on the server host — over the mapped drive Windows serves those timestamps from a cache that can lag a heartbeat written every second by about ten seconds, which is why a Client PC's own reading is not trusted. The rule that turns the looks into a verdict lives in `arcrho_api.bridge_liveness`: a live heartbeat or a status file touched within the six-second window is life, and only thirty seconds of consecutive silent looks (`BRIDGE_SILENCE_LIMIT_SEC`) abandon the wait. In a server process the read is the same look on local disk. The sync and export macros poll their request's status through this same look, and publish the request through the `resq_sync_request_publish` hosted mutation, so inside the app the sync queue is never touched over the drive. The import macros publish theirs through `resq_import_request_publish` (Gateway-required, from macro version 1.15.0, which needs the app release that carries the kind).
- Component status (`server_component_status`): the Server tab's panel. It is Gateway-required: a server whose folder is on a fixed disk of this PC is read straight from disk by `server_profile_service.server_component_status` without asking the Gateway (so a stopped Gateway still shows), and any other server is asked through its Gateway only. A Gateway that does not answer, or one too old to advertise the kind, gives an `answering: false` payload with a plain `detail` and no rows; nothing is ever read over the share. The heartbeat and stop-switch rules are `arcrho_server_component_status`, shared with Admin Control.
- Diagnostics: one record per read in `client_read_latency.jsonl` with `read_kind`, `transport` (`http_gateway` or `smb`), `reason` when local (`gateway_disabled`, `gateway_unreachable`, `kind_not_advertised`, `gateway_rejected:<code>`, `server_process`, `gateway_config_invalid`), `total_ms`, `remote_ms`, `http_status`, `response_bytes`, and the logical project/class/object names — never payload data. Engine calculation requests append to the same file with `read_kind: engine_calculation`.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Move another read to the server: add one `WorkspaceReadKind` entry naming the service function and its keyword arguments, then wrap the route's service call in `workspace_read_client.run_workspace_read(...)`. `test_workspace_reads.py` fails if the registry names an argument the function lacks or omits one it requires; the gateway build validates the import graph and bundles the module automatically. Rebuild and redeploy the gateway.
2. A read that registers process-local state (like the dataset handle registry) must supply a `finalize` hook so the client process adopts that state from a remote payload.
3. Machine-local values that are not paths (a driver-availability flag, the process account) must not be exposed through this transport; keep such reads local or split the machine-local part out. A machine-local *answer* is different from a machine-local value: `excel_link_listing` deliberately reports whether the server host can open each linked workbook, and `excel_link_value_check` and `excel_cell_values` open them there to read the linked cells, because that host is the one every retarget and refresh reads workbooks on, so the server's view is the truth the user needs and a Client PC's would mislead. `excel_cell_values` is also the one registered kind that names no project or reserving class: each item carries the workbook path it asks about, and the read touches no workspace file.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- The gateway is one process for the whole fleet. Its `ThreadingHTTPServer` gives every connection a thread but has no concurrency cap yet; a burst of loads competes with hosted saves in the same process. See `docs/plans/hosted_workspace_http_transport.md` for the bounded-server foundation work.
- A read whose service refusal text embeds a server path is redacted (`[path]`) on the wire, so the client sees slightly less detail than a local refusal would show.
- Rebasing matches on the server root string; a payload string that merely mentions the root (a note) is rebased too. That is harmless and arguably desirable, but it is not a typed field list.
- The pilot transport is plain HTTP with HMAC; full dataset and method payloads now travel unencrypted on the internal network. TLS is the first gate before broader rollout (see the plan's Authentication Posture).
<!-- MANUAL:END -->
