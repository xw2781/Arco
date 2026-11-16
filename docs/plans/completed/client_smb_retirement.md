# Client SMB Retirement: Rollout and Follow-ups

Status: Closed 2026-11-16. Implementation, server deployment, the desktop release and macro publication are complete. The remaining validation and operational items were closed by the user's decision on 2026-11-16, recorded under each section below.
Last updated: 2026-11-16
Completed work: [implementation, decisions and validation record](client_smb_retirement_implementation.md)
Related: [hosted save transport](hosted_save_http_transport.md), [hosted workspace transport](../hosted_workspace_http_transport.md)

This file records how the rollout was closed. The completed record owns the original 24 steps and the six September 29 audit fixes. General Arcode editing remains enabled by the user's decision; no new restriction on explicitly opened project files is planned.

## 1. Release the desktop app

- [x] Build and validate a desktop release containing the September 29 fixes, then publish it and verify the installed app.
- [x] Check without client share access: closed without a new run.

The server additions are deployed. The September 29 fixes shipped in Arco 2.0.0 (2026-10-06) and are in 2.0.1 (2026-10-22).

**Decision 2026-11-16.** The user accepted the validation in the completed record in place of a separate run with the share unavailable. Project Instance JSON previews, active DFM macro reads and saves, dataset loads after a Gateway restart, and adding a server were not re-checked with the drive disconnected.

## 2. Publish compatible macros

- [x] Verify the installed app recognizes `resq_import_request_publish`, `resq_review_request_publish` and `resq_class_inventory` before publishing the macros that call them.
- [x] Publish the active shared macro library following [the macro deployment rules](../../../python-api/macros/README.md).
- [x] Validate the import and review flows using the released app: closed without a new run.

On 2026-11-09 every active macro in the shared library matched its source version: the single-class import is 1.15.1, the batch import 1.10.1 and the review 1.2.0. The three request kinds are in the contracts released with Arco 2.0.0. Local copies update when users load them from the Macro Library window.

**Decision 2026-11-16.** The user closed the flow validation on the existing evidence; no dedicated run in the released app was recorded.

## 3. Validate a fresh Windows profile

- [x] Fresh Windows profile test: closed on existing evidence.
- [x] First-time Excel credential-helper enrollment: closed on existing evidence.

A fresh credential was successfully enrolled under the existing Windows account against the isolated packaged Gateway.

**Decision 2026-11-16.** The user accepted that enrollment as sufficient. No newly created Windows profile was tested.

## 4. Supply the Gateway address during installation

- [x] Dropped: the installer does not write the Gateway address.

**Decision 2026-11-16.** The user chose to keep the current behaviour. The installer writes no server profile; first run asks for the address in the Server Connection dialog, and the app remembers it. Each new user is given the address and types it once.

## 5. Restrict server config permissions

- [x] Inspected the permissions on `<root>\config\arcrho_gateway.json` and its containing folder.
- [x] Restriction not applied: accepted risk.

**Findings 2026-11-16.** The registry inherits full control for every domain user from the server root, so any domain user can read or change every enrolled user's Gateway secret. Only the Gateway reads and writes the file, and the Gateway and Engine run under the developer's account. The desktop app and the Excel add-in use their own local credential and never open the registry.

A permission set on the file alone would not last: the Gateway replaces the file with a new copy on each sign-up, and the copy inherits the folder's permissions. The folder cannot be restricted whole because it also holds the general server configuration. A lasting restriction therefore needs the registry moved into its own folder, which is a change to the path's owner in [arcrho_hosted_save_http_contract.py](../../../python-api/src/arcrho_hosted_save_http_contract.py) and a Gateway redeploy.

**Decision 2026-11-16.** The user accepted the file as it is. No permission or code change was made.

## Known limitations

- A sign-in error shown only inline, without reaching the status bar, still has no adjacent Sign in again action. The Server tab and status bar already provide it. This remains a UI follow-up without an implementation step.
- ArcBot is directed to Gateway reads, but whether it can independently open a mapped drive depends on its sandbox. The implementation does not itself revoke filesystem access. This limitation is separate from the user's decision to retain general Arcode editing.
- The Gateway registry is readable and writable by every domain user (section 5).

TLS remains owned by the hosted-save transport plan, not this checklist.
