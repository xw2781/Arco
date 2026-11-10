# Client SMB Retirement: Remaining Rollout and Follow-ups

Status: Implementation, server deployment, the desktop release and macro publication are complete. Remaining: validation without share access, fresh-profile validation, installer-supplied Gateway address, and server config permissions.
Last updated: 2026-11-09
Completed work: [implementation, decisions and validation record](completed/client_smb_retirement_implementation.md)
Related: [hosted save transport](hosted_save_http_transport.md), [hosted workspace transport](hosted_workspace_http_transport.md)

This file owns the outstanding work. The completed record owns the original 24 steps and the six September 29 audit fixes. Do not repeat the server deployments merely to close the original checklist. General Arcode editing remains enabled by the user's decision; no new restriction on explicitly opened project files is planned.

## 1. Release the desktop app

- [x] Build and validate a desktop release containing the September 29 fixes, then publish it and verify the installed app.
- [ ] With client share access unavailable, check Project Instance JSON previews, active DFM macro reads/saves, dataset loads after a Gateway restart, and adding a server. Check that ordinary Arcode file editing still works.

The server additions are already deployed. The September 29 fixes shipped in Arco 2.0.0 (2026-10-06) and are in 2.0.1 (2026-10-22). The check without share access has not been recorded.

## 2. Publish compatible macros

- [x] Verify the installed app recognizes `resq_import_request_publish`, `resq_review_request_publish` and `resq_class_inventory` before publishing the macros that call them.
- [x] Publish the active shared macro library following [the macro deployment rules](../../python-api/macros/README.md).
- [ ] Validate the import and review flows using the released app.

On 2026-11-09 every active macro in the shared library matched its source version: the single-class import is 1.15.1, the batch import 1.10.1 and the review 1.2.0. The three request kinds are in the contracts released with Arco 2.0.0. Local copies update when users load them from the Macro Library window.

## 3. Validate a fresh Windows profile

- [ ] On a fresh Windows profile with no saved credential and no access to the server share, configure the Gateway address, enroll, read project data and perform a hosted save.
- [ ] Check first-time Excel credential-helper enrollment after the app has supplied the Gateway address.

A fresh credential was successfully enrolled under the existing Windows account against the isolated packaged Gateway. That does not replace testing a newly created Windows profile.

## 4. Supply the Gateway address during installation

- [ ] Make the installer write the production Gateway address into the default server profile's `gateway_url` in `workspace_paths.json`, using the canonical profile configuration contract.
- [ ] Verify a clean installation reaches first-run sign-in without asking the user to type the address, and preserves an existing user's configured server.

The installer does not currently write this profile file. First run therefore asks for the address in the Server Connection dialog. The configuration owner is [arcrho_api/config.py](../../python-api/src/arcrho_api/config.py); the installer lives under [frontend/build/installer](../../frontend/build/installer).

## 5. Restrict server config permissions

- [ ] After verifying the updated clients no longer read the shared registry, inspect the permissions on `<root>\config\arcrho_gateway.json` and its containing folder.
- [ ] Restrict registry access to the server/service and administrator accounts that require it. Check inheritance and verify ordinary client users cannot read other users' secrets.
- [ ] Verify Gateway operation, enrollment, reads and saves still work with each client's own local credential.

The shared registry holds every enrolled user's Gateway secret. Clients should use their own local credential. Determine the actual service accounts before changing permissions; this is an operational follow-up, not an application-code change.

## Known limitations

- A sign-in error shown only inline, without reaching the status bar, still has no adjacent Sign in again action. The Server tab and status bar already provide it. This remains a UI follow-up without an implementation step.
- ArcBot is directed to Gateway reads, but whether it can independently open a mapped drive depends on its sandbox. The implementation does not itself revoke filesystem access. This limitation is separate from the user's decision to retain general Arcode editing.

TLS remains owned by the hosted-save transport plan, not this checklist. Record validation and completion against each remaining item here; move this file to `completed/` only after its rollout and operational work is resolved.
