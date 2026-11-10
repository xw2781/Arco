# Local Runtime Log Retention Plan

Version: v1.0
Last updated: 2026-08-09
Status: Audit complete; remediation not started

## Summary

ArcRho currently has several frontend and data-engine log families that grow
without an automatic age limit, file-count limit, directory-size limit, or
rotation policy. The measured footprint on the audited computer is small, so
there is no immediate disk-capacity incident. The retention gap is nevertheless
real: normal launches accumulate thousands of small files, and access-heavy or
repeating-error paths can grow a single file indefinitely.

This plan records the measured state, identifies each code owner, and proposes
one coordinated retention policy for the desktop frontend, ArcBot, the Bridge
ResQ migration runtime, Admin Control, and retained data-engine job statuses.

## Scope

In scope:

- Files explicitly written by the ArcRho/Arcode Electron host or its packaged
  Python app server on a client computer.
- ArcBot diagnostic files written under the user's local Documents folder.
- Files written by deployed data-engine components under `E:\Arco Server`.
- Retained request/status artifacts that are not conventional logs but have the
  same indefinite disk-growth characteristic.
- Build packaging that seeds a deployed runtime with existing debug logs.

Out of scope:

- Project business data and intentional per-object audit history.
- Chromium-owned HTTP and code caches. They are currently the largest part of
  Electron user data, but Chromium owns normal eviction and ArcRho exposes an
  explicit clear-cache action.
- Codex CLI storage outside ArcRho-owned folders. ArcBot starts ephemeral Codex
  threads, and storage shared with other Codex clients cannot be attributed to
  ArcRho safely.
- Recovery artifacts that must be retained after an ambiguous failed commit.
  These require an operator-visible recovery workflow, not blind age deletion.

## Measured Snapshot (2026-08-09)

The audit inspected file metadata and sizes without deleting or modifying any
runtime file.

| Location | Files | Logical bytes | Oldest observed | Notes |
| --- | ---: | ---: | --- | --- |
| `%APPDATA%\arcrho-electron\logs\electron-main-*.log` | 4,450 | 2,823,728 | 2026-06-01 | One file per Electron process. |
| `%APPDATA%\arcrho-electron\logs\arcrho-server-*.log` | 12 | 169,448 | 2026-06-01 | Largest file was 64,889 bytes; routine HTTP access records dominated the largest file. |
| `%APPDATA%\Arcode\logs\electron-main-*.log` | 32 | 15,074 | 2026-06-13 | Same shared frontend logging implementation. |
| `Documents\ArcRho\ArcBot\request_logs` | 53 | 837,947 | 2026-05-20 | One JSON timing/event log per ArcBot request. |
| Deployed Bridge `resq_data_migration_debug.log` | 1 | 4,746,525 | Deployed 2026-08-09 | The build copied an existing 8,128-line source log into the deployed app. |
| Source migration `resq_data_migration_debug.log` | 1 | 4,746,525 | 2026-06-19 | Ignored working-tree artifact that the Bridge build currently includes. |
| `E:\Arco Server\runtime\logs\arcrho_admin.log` | 1 | 28,225 | 2026-05-24 | Append-only Admin Control log. |
| Deployed Admin Control `arcrho_admin.log` | 1 | 3,304 | 2026-08-07 | Duplicate destination for the same Admin events. |

The normal runtime-owned log footprint is currently under 10 MiB when the
working-tree source copy is excluded. Current usage therefore does not threaten
the disk, but the absence of limits means historical growth continues for as
long as the corresponding features are used.

The server request tree also contained 544 retained protocol files totaling
1,012,674 bytes:

- 432 dependent-propagation status files (153,566 bytes).
- 100 ResQ-import status files (856,221 bytes).
- 4 project-duplication status files (1,354 bytes).
- 8 project-duplication submission/receipt files (1,533 bytes).

Bridge staging under `E:\Arco Server\r` was empty, confirming that the normal
transactional cleanup path was functioning at the time of the audit.

## Findings

### 1. Electron main-process logs accumulate by launch

Owner: `frontend/electron/host_support.js:63-97`.

`getElectronLogPath` selects a new timestamped
`<userData>\logs\electron-main-*.log` for every Electron process.
`appendElectronLog` appends startup milestones, uncaught exceptions, and
unhandled promise rejections. No startup or shutdown path enumerates and prunes
older files. The current 4,450-file inventory demonstrates the missing cleanup
even though the total bytes remain small.

The installer also sets `deleteAppDataOnUninstall: false` in
`frontend/package.json`, so uninstalling does not provide a fallback cleanup.

### 2. Packaged app-server logs have unbounded per-file growth

Owners:

- `frontend/electron/backend_lifecycle.js:102-140,416-430`
- `frontend/build/server_entry.py:37-42`

Every packaged backend start opens a new
`<userData>\logs\arcrho-server-*.log` (or `arcode-server-*.log`) and pipes the
child's complete stdout and stderr into it. The bundled server runs Uvicorn at
`info` level without disabling access logging, so ordinary API traffic grows
the file for the entire backend lifetime. Shutdown closes the stream but does
not rotate, truncate, or delete it.

This is the highest log-specific overflow risk because one long-running process
or repeating error can grow one file without waiting for repeated launches.

### 3. ArcBot request diagnostics accumulate by request

Owner: `frontend/electron/arcbot_host.js:571-588,1638-1816`.

Each ArcBot request writes a unique JSON file under
`Documents\ArcRho\ArcBot\request_logs`. Individual field values are truncated,
but the event array, file size, file count, and retention period are not capped.
There is no automatic deletion path.

Related local ArcBot storage also lacks age-based pruning:

- Unique edit-session metadata folders under `ArcBot\sessions`.
- Persistent staged JSON/CSV copies under `ArcBot\workspace`.
- Chat-session count (each session's internal messages and activities are
  bounded, and explicit user deletion is supported).
- Applied-edit backup/manifest history beside the edited target.

Only diagnostic request logs should be governed by the default log-retention
policy. User-visible chat history and edit-recovery history need separate,
explicit product decisions before automatic deletion.

### 4. Bridge migration logging is append-only and bundled with history

Owners:

- `python-api/migration/resq_data_migration.py:192,233-245`
- `python-api/migration/resq_migration/dfm.py:638-679`
- `server-components/src/arcrho_bridge/bundled_sources.py:59-67`
- `server-components/src/arcrho_bridge/build_exe.py:163-169`

The migration `_debug_log` function appends one JSON object per line to
`migration\logs\resq_data_migration_debug.log` and never rotates it. DFM export
invokes that logger. The Bridge bundles the entire `python-api/migration` tree,
so ignored source logs and validation output are copied into every deployed
Bridge. In a frozen Bridge, future imports resolve `DEBUG_LOG_PATH` inside that
deployed bundle and continue appending there.

The current deployed 4.75 MB log was a build seed rather than post-deploy
growth. It still proves both problems: historical diagnostics are shipped as
application data, and the deployed file remains the live append target.

### 5. Admin Control duplicates append-only events

Owner: `server-components/src/arcrho_admin/main.py:12-23,123-124,197-225,281-299`.

Admin Control appends every event to both its deployed application directory
and `E:\Arco Server\runtime\logs\arcrho_admin.log`. Neither destination has
rotation or retention. Normal event volume is low, but a persistent heartbeat
write failure records a traceback on every retry and can amplify growth.

The two destinations also create unnecessary duplication. The server runtime
log should be the sole durable owner; the deployed application folder should
remain immutable.

### 6. Terminal data-engine statuses are retained indefinitely

Owners include:

- `python-api/src/arcrho_dependent_propagation_contract.py:18-20`
- `server-components/src/arcrho_bridge/main.py:453-559,641-727`
- The canonical project-duplication request/status contract.

Validated terminal dependent-propagation statuses intentionally have no
automatic pruning. ResQ-import and project-duplication workflows likewise leave
unique completed statuses/receipts. Individual payloads are small, but the file
count increases with durable jobs forever.

This is a server-storage retention issue rather than a conventional log issue.
Cleanup must preserve queued/processing jobs, active locks and leases, uncertain
commits, and recovery evidence.

### 7. Existing cleanup that is working

The following paths are bounded or cleaned and should not be treated as defects:

- Engine, Bridge, and Orchestrator executables use `--noconsole` and do not
  directly redirect stdout/stderr to log files.
- Orchestrator removes stale Engine, Bridge, and Orchestrator heartbeat files.
- Normal Bridge import staging is removed after successful commit or safe
  rollback; ambiguous recovery backups are deliberately preserved.
- Project audit logging is capped at 5,000 entries.
- Dataset sidecar audit history is capped independently.
- The Engine's in-memory source-table cache evicts old entries.
- DFM ratio undo history is bounded within a live session and cleared on normal
  tab closure, although crash-orphaned temporary folders need a startup sweep.

## Canonical Retention Policy

Implementation must introduce one canonical, machine-readable retention policy
rather than defining limits independently in JavaScript and Python. Proposed
owner: `config/runtime_retention_policy.json`, packaged unchanged into the
frontend, Bridge, Engine, and Admin applications. Component adapters may resolve
paths and active-file state, but must not copy the numeric defaults.

Proposed defaults, subject to owner confirmation before implementation:

| Class | Maximum age | Per-file limit | Directory limit | Additional rule |
| --- | ---: | ---: | ---: | --- |
| Electron main logs | 30 days | 10 MiB | 100 MiB | Delete oldest closed files first. |
| Packaged app-server logs | 30 days | 10 MiB | 100 MiB | Keep up to 5 rotated segments for the active session. |
| ArcBot request diagnostics | 30 days | 10 MiB | 100 MiB | Protect active request files. |
| Bridge migration debug log | 30 days | 10 MiB | 50 MiB | Write under server `runtime\logs`, not the deployed app. |
| Admin Control log | 30 days | 10 MiB | 50 MiB | Use only the server runtime destination; keep 5 rotations. |
| Validated terminal job statuses | 90 days | Not applicable | 250 MiB | Never remove nonterminal, leased, locked, or recovery-required jobs. |
| Crash-orphaned temporary files | 7 days | Not applicable | 250 MiB | Delete only files proven to be ArcRho-owned and inactive. |

Age and aggregate-size limits are both required. An application with low event
volume should not retain files forever, and an error storm must not consume the
entire age allowance before cleanup runs.

## Safety and I/O Requirements

1. Cleanup is best-effort and must never prevent application startup or mask the
   original runtime error.
2. Resolve and validate every cleanup root before deleting. Never accept an
   arbitrary caller-provided directory or operate outside the named ArcRho
   folder.
3. Never delete an open/current log. Rotation must close or rename the segment
   before pruning it.
4. Enumerate each network-drive folder once, classify entries from that listing,
   and delete in bounded batches. Do not perform sequential per-file re-stat
   loops on `E:\Arco Server`.
5. Delete oldest eligible files first, with deterministic name ordering as a
   tie-breaker.
6. Status cleanup must parse and validate only candidate terminal status files.
   It must preserve malformed files for diagnosis rather than guessing that
   they are safe to remove.
7. Status cleanup must not touch active leases, locks, request files, staging
   directories, recovery journals, submission receipts still referenced by a
   pending client, or rollback backups.
8. A transient permission or network error must leave remaining files intact
   and report a bounded warning; it must not retry in a tight logging loop.
9. The Bridge build must exclude `python-api/migration/logs`, validation output,
   caches, and other ignored runtime artifacts. A build contract test must list
   the allowed bundled files or assert the exclusions.

## Implementation Phases

### Phase 1: Canonical policy and shared behavior tests

- Add the canonical JSON policy and schema validation.
- Add JavaScript and Python adapters that read the same packaged policy.
- Add a cross-runtime parity test for every limit and inclusion/exclusion rule.
- Implement a deterministic retention selector against file metadata so tests
  can run without depending on wall-clock timing.

### Phase 2: Frontend runtime logs

- Prune closed `electron-main-*`, `arcrho-server-*`, and `arcode-server-*` logs
  during startup.
- Add size-based rotation for packaged backend stdout/stderr.
- Decide whether routine Uvicorn access logging should be disabled in production
  or written to a separately rotated access log.
- Apply the same age/aggregate policy to ArcBot request diagnostics.
- Preserve useful error context by retaining the newest files even when the age
  sweep and directory cap run together.

### Phase 3: Bridge and Admin logging

- Move Bridge migration diagnostics to
  `E:\Arco Server\runtime\logs\resq_data_migration_debug.log`.
- Replace append-only writes with rotation driven by the canonical policy.
- Exclude the migration `logs` and `validation` folders from the Bridge bundle.
- Consolidate Admin Control onto its server runtime log and add rotation.
- Add rate limiting or deduplication for repeated heartbeat-write failures.

### Phase 4: Durable status and temporary-artifact retention

- Add a server-host cleanup job for validated terminal statuses older than the
  retention window.
- Keep cleanup ownership server-side so multiple clients do not race over the
  same network-drive directory.
- Define the product retention rule for project-duplication submission receipts
  before deleting them.
- Add startup cleanup for provably orphaned DFM undo, macro runtime, updater
  `.part`, and Admin splash temporary files.
- Treat ArcBot workspace/chat/history retention as a separate user-data feature
  decision rather than silently applying diagnostic-log limits.

### Phase 5: Rollout and observability

- Log one compact cleanup summary per run: examined, retained, deleted, bytes
  reclaimed, and failures. Never emit one log entry per deleted file.
- Surface current log/status storage totals in Admin Control.
- Perform one cleanup dry run in the deployed environment before enabling
  deletion, and record the exact candidate counts and bytes.
- Rebuild/redeploy each frozen component only after its targeted tests pass.

## Acceptance Criteria

1. No ArcRho-owned diagnostic log can grow beyond its configured rotation and
   aggregate-directory limits.
2. Repeated launches do not leave files older than the configured retention
   window.
3. Active Electron, app-server, ArcBot, Bridge, and Admin logs survive cleanup.
4. A simulated access-log or heartbeat-error storm rotates files without
   blocking the owning process.
5. Frontend and Python adapters load the exact same canonical policy values.
6. A Bridge build contains no source debug log or migration validation output.
7. Terminal-status cleanup removes only validated, expired terminal artifacts
   and preserves all active or recovery-related state.
8. Cleanup on a missing, disconnected, or permission-denied network path exits
   safely without a retry/log storm.
9. Tests use repository-local temporary directories and complete within the
   repository's validation runtime limit.

## Validation Plan

- Frontend host unit tests for age pruning, aggregate caps, active-file
  protection, deterministic ordering, and backend log rotation.
- ArcBot tests for completed/active request-log retention.
- Python 3.10 tests for migration/Admin rotation and terminal-status selection.
- Bridge build-contract test proving ignored migration runtime artifacts are not
  bundled.
- Failure-injection tests for locked files, permission failures, concurrent
  writers, and disconnected server roots.
- A read-only deployed smoke check that reports counts/bytes before and after a
  dry run, followed by an explicitly scoped cleanup verification.

## Open Decisions

1. Confirm or revise the proposed 30-day log and 90-day terminal-status windows.
2. Decide whether production Uvicorn access logs are needed for support, or only
   warnings/errors should be retained.
3. Decide whether Admin Control should expose a manual `Clean now` action in
   addition to automatic retention.
4. Define separate retention semantics for ArcBot chat history, edit backups,
   and staged workspace files.
5. Decide how long project-duplication receipts must remain available for client
   recovery and reconciliation.
