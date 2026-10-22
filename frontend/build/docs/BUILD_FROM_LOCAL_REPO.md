# ArcRho and Arcode Local Release Build

## Purpose

Use this workflow when the repository, build toolchain, and authenticated `gh` CLI all live
on the same Windows PC. It supports both the legacy one-step release and a safer
build-test-publish sequence, without a second PC, build share, source ZIP, or listener.

```text
This PC's repository
    -> build_app_from_local_repo.bat --build-only <version>
    -> prerequisite checks
    -> in-place build of frontend\ (Python + Electron + NSIS)
    -> pending installer record outside the repository
    -> local installer test
    -> explicit publish action
    -> published GitHub Release
    -> release bookkeeping committed in this repository
```

The [two-PC ZIP workflow](BUILD_FROM_ZIP_ON_SECOND_PC.md) is unchanged and remains the route
to use when the PC holding the repository cannot run the full toolchain. Both entry points
run the same packaging body in `build_app_via_local_workspace.bat`.

## Build-Only And Publishing Are Deliberately Separate

Build-only mode temporarily applies the requested version only for packaging, records the
installer SHA-256, release-fragment names and hashes, and the ArcRho Python API wheel. It then
restores `package.json`, `package-lock.json`, the About dialog, and the splash page to their
exact pre-build contents.

The one file it leaves behind is `docs\releases\<version>.md`. Every build writes that before
packaging, because the app reads its Release History from the notes bundled inside it, and notes
written after packaging would miss the build that shipped them. It stays uncommitted until the
release is published, and the publish keeps it rather than rendering it again.

The pending-release record lives under `%USERPROFILE%\Documents\ArcRho Local Build\pending_releases`
by default, outside the working tree. Build-only mode does not create a GitHub Release,
publish the shared Python API wheel, archive release fragments, or commit release bookkeeping.

The later publish action rechecks the installer and fragment hashes. It creates the GitHub
Release, publishes the matching Python API wheel for ArcRho, then delegates source updates to
`sync_published_release.py`. That preserves the canonical version metadata, release-note,
fragment-archive, documentation-index, and optional local-commit behavior. If a post-GitHub
step fails, the record becomes `remote published` and can be retried without reuploading the
installer.

The previous no-argument command is retained for operators who intentionally want the
one-step build-and-publish sequence.

## Prerequisites

`build_app_from_local_repo.bat --check` verifies build prerequisites without building:

- Windows PowerShell 5.1 or later.
- Python 3.10.6 or newer within the Python 3.10 line. The build rejects Python 3.11 or later.
- `frontend\node-portable\node.exe` with a complete ArcBot/Codex payload. This directory is
  not in Git, so a fresh clone must copy it from a prepared machine and refresh it with
  `build\arcbot_runtime\refresh_bundled_codex_runtime.ps1`.
- `frontend\node_modules\electron-builder\cli.js`. Run `npm install` in `frontend` if absent.
- An authenticated GitHub CLI account with release permission for the repository named in
  `release_channel.json`. It supplies the version history, publication, history view, and
  revocation action.
- Valid release fragments under `changes\unreleased`.

An ArcRho publish additionally needs a reachable `PYTHON_API_PACKAGE_DIR` (default:
`E:\ArcRho Server\packages`). Build-only mode retains the wheel locally, so it can run while
that mapped workspace is unavailable.

## Build, Test, And Publish

The desktop GUI is the recommended route:

```bat
frontend\build\release_manager.bat
```

It provides a custom version field, suggested next version, locally built installer list,
publish history, and guarded release revocation. See [RELEASE_MANAGER.md](RELEASE_MANAGER.md)
for the full GUI workflow.

The command-line equivalent is:

```bat
frontend\build\build_app_from_local_repo.bat --check
frontend\build\build_app_from_local_repo.bat --build-only 1.3.0
frontend\build\build_app_from_local_repo.bat --publish 1.3.0
```

`--build-only` may omit the version to use the next patch derived from GitHub release history.
Pass an explicit semantic version to use a custom version instead. The version must be newer
than published history and must not be lower than the package version when the build begins;
publishing checks the live history again before creating the release.

To retain the original one-step behavior:

```bat
frontend\build\build_app_from_local_repo.bat 1.3.0
```

To write release bookkeeping but review it before committing, add `--no-commit` to the publish
or one-step command:

```bat
frontend\build\build_app_from_local_repo.bat --publish 1.3.0 --no-commit
```

For standalone Arcode, select the product first. Arcode has no Python API wheel:

```bat
set ARCRHO_BUILD_PRODUCT=arcode
frontend\build\build_app_from_local_repo.bat --build-only 1.3.0
```

### Environment Overrides

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARCRHO_BUILD_PRODUCT` | `arco` | Select `arco` or `arcode`. |
| `ARCRHO_LOCAL_RELEASE_WORK_DIR` | `%USERPROFILE%\Documents\ArcRho Local Build` | Build logs and pending-release records, outside the repository. |
| `PYTHON_API_PACKAGE_DIR` | `E:\ArcRho Server\packages` | Shared Python API wheel destination used at ArcRho publish time. |
| `PYTHON_EXE` | resolved via `py -3.10` | Python 3.10 interpreter used for packaging and workflow actions. |

## What Each Stage Writes

Build-only mode writes ignored build output (`dist\`, `python_dist\`, `python_build\`, and
`build\generated\`) plus a pending-release record outside the repository. It restores these
tracked files to their pre-build byte content:

- `package.json`, `package-lock.json`, `ui\index.html`, and `ui\splash.html`.

Publishing the recorded installer writes:

- version metadata in `package.json`, `package-lock.json`, `ui\index.html`, and `ui\splash.html`;
- `docs\releases\<version>.md` and a regenerated `docs\releases\INDEX.md`;
- `changes\unreleased\*.json` moved into `changes\archive\<version>`;
- `docs\generated\file_manifest.md` refreshed by the documentation index builder; and
- a local bookkeeping commit unless `--no-commit` was selected.

Only those bookkeeping paths are staged; unrelated work in the worktree is never staged or
pushed. The build retains the Python API wheel until its matching pending release is published.

## Verifying The Result

A successful build-only run produces:

- `frontend\dist\Arco-Setup-<version>.exe`; and
- a matching pending-release record under the local release work directory.

It does not create a GitHub Release, shared Python API wheel, or release-bookkeeping change.

A successful publish additionally produces a GitHub Release tagged `Arco-v<version>` with
the installer and `.sha256` attached, the matching shared Python API wheel for ArcRho, and the
optional local bookkeeping commit. The publish then rebuilds the update feed
(`publish_update_manifest.ps1`), the `<Product>-update.json` asset on the `update-feed`
prerelease that installed apps read to find this version. The tag name, target repository,
and feed names come from `release_channel.json`; do not duplicate them in a script or GUI
setting.

## When Something Fails

A build-only failure restores the version metadata snapshot before it returns. If restoration
itself fails, the batch file retains the snapshot path and reports it so the source files can
be restored deliberately.

If publication succeeds but a later wheel or repository-bookkeeping step fails, do not rebuild.
Select the `remote published` record in Release Manager and publish it again, or run:

```bat
frontend\build\build_app_from_local_repo.bat --publish <version>
```

This finishes the remaining local steps without reuploading the installer.

### The ArcBot runtime check fails

`node-portable` is not in Git and a copied runtime can be missing the Codex shim. Refresh it:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File frontend\build\arcbot_runtime\refresh_bundled_codex_runtime.ps1
```

### Electron Builder reports `spawn EPERM` for `app-builder.exe`

```bat
powershell -NoProfile -Command "Get-Item '.\node_modules\app-builder-bin\win\x64\app-builder.exe' | Unblock-File"
```

## Completion Checklist

- `--check` passed before the build was started.
- The build exited with code `0`.
- The local installer was tested before it was published.
- The GitHub Release has the installer and checksum.
- The pre-build and `win-unpacked` ArcBot runtime checks passed.
- The matching fragments moved into `changes\archive\<version>`.
- The local release-bookkeeping commit was reviewed before pushing.
