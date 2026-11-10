# App Server Domain: User Identity

## Purpose
<!-- MANUAL:BEGIN -->
Resolve the current Windows login to the display name used by the ArcRho Home brand and by every user-facing metadata field ArcRho writes, including dataset and method sidecar `user`/`modified_by` values and audit-log records. Also decide *whose* name that is when the write runs on a shared host: a save or dependent walk executed on Arco Engine acts as the user who submitted it, not as the account the Engine instance runs under.
<!-- MANUAL:END -->

## Entry Points
<!-- MANUAL:BEGIN -->

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/app/user-identity` | Return the current `login_name` and resolved `display_name`. |
<!-- MANUAL:END -->

## Key Files
<!-- MANUAL:BEGIN -->
- `app_server/api/user_identity_router.py` - Thin identity API route.
- `app_server/services/user_identity_service.py` - Windows-login and username-index resolution, and the session cache in front of it.
- `app_server/config.py` - Canonical workspace-root and username-index path resolution.
- `app_server/services/dataset_service.py`, `calculated_dataset_service.py`, `result_selection_service.py`, `dfm_service.py`, `bornhuetter_ferguson_service.py`, `cape_cod_service.py`, `bootstrap_service.py`, `arcrho_runtime_service.py`, `audit_service.py` - Writers that stamp the resolved display name onto persisted metadata.
- `app_server/services/engine_hosted_save_service.py`, `dependent_propagation_service.py` - Send the submitting user with the request they publish to Arco Engine.
- `server-components/src/arcrho_engine/save_jobs.py`, `dependent_propagation.py` - Bind `acting_identity(...)` around the work they run on the server host.
- `server-components/src/arcrho_bridge/resq_import_runner.py`, `python-api/migration/resq_data_migration.py`, `resq_migration/extractors.py` - The Bridge hands the import request's `UserName` to the migration as `requested_by`; the migration binds it as the acting identity, and the engine-generated sidecar it writes stamps the resolved display name through the same service the app's engine writer uses.
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- The mapping is read from `<workspace_root>/config/username_index.json`.
- `GET /app/user-identity` is the `user_identity` hosted read: on a Client PC the Gateway answers for the login the request is signed with and resolves its name against the server's copy of the index, so the Home brand never reads the index over the share. The route answers `503` when the Gateway is unavailable. A Client PC never opens the index at all: `load_username_display_names` answers with an empty mapping unless the process runs with `ARCRHO_RUNTIME_SERVER_ROOT` set, and every request a Client PC sends (reads, mutations, calculations, hosted saves) carries the login only, with an empty display name the server resolves.
- `login_name` matching is case-insensitive.
- A matching row uses its non-empty `full_name`; a missing, invalid, or unmapped entry falls back to the unchanged Windows login name.
- The parsed mapping and the current account's resolved display name are cached for the life of the app-server process, keyed by index path, because every dataset save now resolves a name and the index is workspace-global configuration that rarely changes. A mapping edit takes effect for a running session only after the app server restarts.
- Resolution happens where a value is written, not where it is read. Sidecars store the display name, and the reserving-class `index.json`, the Project Instance table, and the audit tabs pass that stored text through unchanged. `index.json` therefore needs no identity logic of its own: its `user` column is projected from the sidecar it indexes.
- `acting_identity(login, display_name="")` binds the user a server-side job runs for, in a `contextvars` scope around the job. While it is bound, `get_windows_login_name()` and `get_current_display_name()` answer with that user instead of the process account, so every writer below keeps asking for "the current user" without knowing where it runs. A supplied `display_name` wins over re-resolution because the submitting app server is started per app launch while an Engine instance can run for days on the mapping it cached at startup; an empty login leaves the process identity in place.
- Machine-facing identity stays on the raw login: engine and bridge request `UserName` fields, dependent-propagation requests, and the per-user preference folder name are not remapped, since a display name is many-to-one and cannot key an account.
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Without an acting identity the login comes from the backend process account. If the app server runs under a service account, that account is resolved instead of the interactive desktop user.
- Sidecars written before this resolution keep whatever text they already hold, so a reserving class can show a mix of full names and login names until each row is saved again. Rows written by an Engine instance between the move to Engine-hosted saves and this change hold that instance's service account and are only corrected by saving the object again. Engine-generated datasets imported from ResQ before 2026-08-27 hold the login of the Bridge worker that ran the import and are corrected by importing the class again.
- The acting identity is scoped to the thread that runs the job (a `contextvars` binding). Work a job hands to another thread or process does not inherit it and falls back to the process account.
<!-- MANUAL:END -->
