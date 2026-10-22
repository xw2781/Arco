# ArcRho and Arcode Automated Two-PC ZIP Build Workflow

## Purpose

Use this workflow when the ArcRho repository is maintained on one Windows PC, but ArcRho or standalone Arcode packaging must run on another Windows PC because the source PC cannot execute the complete build toolchain with the required permissions.

> If the PC holding the repository **can** run the toolchain and has an authenticated `gh` CLI, use the [local release build](BUILD_FROM_LOCAL_REPO.md) instead. It needs no ZIP, no build share, and no listener, and it records the release in the repository as the build runs. Both workflows share the same build body in `build_app_via_local_workspace.bat`.

The ZIP is a transport artifact. A listener on the source PC creates it only when the build PC requests one. The build PC then copies the requested ZIP to a local workspace, extracts it locally, and runs the complete build from that local workspace.

```text
Source PC repository
    -> shared build_app_listener
    -> curated ArcRho.zip
    -> build_app_one_click or build_arcode_one_click request and response
    -> product-specific build PC local Documents workspace
    -> Python + Electron + NSIS build
    -> installer and published GitHub Release
```

## Roles and Default Paths

| Role | Example path | Purpose |
| --- | --- | --- |
| Source repository | `E:\XWSpace\Repos\ArcRho` on the source PC | Source of truth for files placed in the build ZIP. |
| Source ZIP | `E:\XWSpace\Build ArcRho App\ArcRho.zip` on the source PC | Curated build input copied across the network. |
| Network view from build PC | `E:\XWSpace\Build ArcRho App\ArcRho.zip` | The build PC's permanent `E:` mapping to the source PC. |
| Source-PC listener | `E:\XWSpace\Build ArcRho App\build_app_listener.bat` | Visible long-running process that receives requests and creates a fresh ZIP. |
| Build-PC launcher | `E:\XWSpace\Build ArcRho App\build_app_one_click.bat` | Requests a fresh ZIP, waits for it, then runs the local build. |
| Arcode build-PC launcher | `E:\XWSpace\Build ArcRho App\build_arcode_one_click.bat` | Uses the same listener and source ZIP, then selects the standalone Arcode build. |
| Local build workspace | `%USERPROFILE%\Documents\build_arcrho_app` on the build PC | Disposable local extraction and build directory. |
| Arcode local build workspace | `%USERPROFILE%\Documents\build_arcode_app` on the build PC | Separate disposable extraction and build directory for Arcode. |
| Local installer output | `%USERPROFILE%\Documents\build_arcrho_app\frontend\dist` | Installer produced by the local build. |
| Published release | GitHub Releases in the repository named by `frontend\build\release\release_channel.json` | Installer and checksum published after a successful build. This is the only publication target and the only durable record of what has shipped. |
| Retired installer feed | `E:\ArcRho Server\releases\installers` and `E:\Arcode Server\releases\arcode-installers` | No longer written by the build. Kept for clients installed before the GitHub update checker shipped; publish to it manually with `build\release\publish_update_feed.ps1` when a migration build is needed. |
| Shared build logs | `E:\XWSpace\Build ArcRho App\logs\<COMPUTERNAME>` | Timestamped ZIP-creation and application-build logs from both PCs. |

This workflow assumes that `E:` on the build PC is permanently mapped to `E:` on the source PC. The default ZIP and wrapper paths already use that mapping, so `ARCRHO_LOCAL_BUILD_SOURCE_ZIP` does not need to be set.

## Build Share Scripts Are Deployed, Not Edited

The launchers in the build share cannot run from the repository. The share is the one path both PCs agree on, and the listener resolves its request folders from wherever it sits. But an unversioned script that drives releases has no review and no history, so the repository owns them and the share holds deployed copies.

| | |
| --- | --- |
| Canonical copy | `frontend\build\build_share\` in the repository |
| Deployed copy | `E:\XWSpace\Build ArcRho App\` |
| Deploy command | `frontend\build\deploy_build_share.bat` |

Covered scripts: `build_app_listener.bat`, `build_app_listener.ps1`, `build_app_one_click.bat`, `build_arcode_one_click.bat`, and `publish_pending_github_release.bat`.

Edit the repository copy, then deploy:

```bat
frontend\build\deploy_build_share.bat            REM publish the scripts that differ
frontend\build\deploy_build_share.bat --verify   REM report drift, write nothing, non-zero on drift
frontend\build\deploy_build_share.bat --force    REM overwrite a share copy that is newer
```

Only files that differ are copied, and nothing else in the share is touched or removed — build artifacts, logs, request folders, and fragment snapshots all stay. If a share copy differs **and** is newer than the repository copy, the deploy reports it and leaves it alone: that pattern means someone edited the share directly, and the fix is to copy that edit back into `build_share` rather than lose it. `--force` overrides once you have decided the repository copy wins.

The listener compares itself against the repository copy when it starts and warns if they differ, because PowerShell loads the script once and a listener left running after a deploy keeps serving the previous version. That warning means: restart it.

## Build-PC Prerequisites

Before starting a full build, confirm that the build PC has:

- Windows PowerShell 5.1 or later.
- Python 3.10.6 or newer within the Python 3.10 line. The build rejects Python 3.11 or later.
- Permission to install missing Python build dependencies, or all required dependencies already installed.
- Permission to execute files from the local workspace, including portable Node, `app-builder.exe`, PyInstaller, and NSIS.
- Read access to the source-PC share and write access to the local workspace.
- Write access through the mapped `E:` drive to `E:\ArcRho Server\packages`, or an appropriate `PYTHON_API_PACKAGE_DIR` override for the Python package destination.
- The `gh` CLI installed and authenticated (`gh auth login`, or a `GH_TOKEN` environment variable) with permission to create releases on the target GitHub repository. This is now required twice: the version step reads the published release history to decide the next version, and the publish step creates the release the packaged app's update checker reads. An unauthenticated `gh` fails the build at Step 1 rather than after a full package.
- Enough local disk space for the copied ZIP, its expanded contents, PyInstaller work files, Electron output, and the installer.

The wrapper deletes the entire local build workspace before each extraction. Never set `ARCRHO_LOCAL_BUILD_ROOT` to a directory containing files that must be preserved.

## Step 1: Start the Listener on the Source PC

On the source PC, run this once and leave its visible terminal window open while the build PC should be able to request builds:

```bat
call "E:\XWSpace\Build ArcRho App\build_app_listener.bat"
```

The shared listener checks `build_requests`, processes ArcRho and Arcode requests one at a time, creates a fresh curated ZIP, and writes a success or failure response in `build_responses`. Press Ctrl+C in its terminal to stop it. Only one listener process is needed for both products.

To check the listener prerequisites without starting it:

```bat
call "E:\XWSpace\Build ArcRho App\build_app_listener.bat" --check
```

### How the Listener Creates the Curated ZIP

Do not ZIP the live repository folder directly. A raw repository ZIP includes `.git`, agent metadata, old build outputs, caches, and logs. Those files make the archive much larger and can trigger Windows path-length and extraction failures.

Use the clean ZIP creator beside the build scripts. It creates a disposable curated staging tree, validates required build inputs, and only replaces the existing ZIP after the new archive passes validation.

The listener invokes the clean ZIP creator beside the repository build scripts. To check that creator directly without creating an archive:

```bat
call "E:\XWSpace\Repos\ArcRho\frontend\build\create_build_source_zip.bat" --check
```

For maintenance or troubleshooting, it can also be run manually:

```bat
call "E:\XWSpace\Repos\ArcRho\frontend\build\create_build_source_zip.bat"
```

With the repository at the standard location, the default outputs are:

```text
E:\XWSpace\Build ArcRho App\ArcRho.zip
E:\XWSpace\Build ArcRho App\ArcRho.zip.sha256
E:\XWSpace\Build ArcRho App\ArcRho.zip.ready
```

The `.ready` flag is published only after both the ZIP and checksum have been finalized successfully. It contains a unique token for that ZIP creation run. A failed or still-running ZIP creation leaves no readiness flag.

Disposable `.arczip-*` staging folders, `.building-*` files, and atomic `.backup-*` files are also kept under `E:\XWSpace\Build ArcRho App`. They are removed after success; a replacement backup is retained and reported if publication fails.

To use another repository or output path, call the PowerShell implementation directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File 'E:\XWSpace\Repos\ArcRho\frontend\build\transport\create_build_source_zip.ps1' `
  -SourceRoot 'E:\XWSpace\Repos\ArcRho' `
  -OutputZip 'E:\XWSpace\Build ArcRho App\ArcRho.zip'
```

Staging runs through `prepare_local_build_workspace.ps1`, which normalizes every staged `.bat` and `.cmd` file to CRLF line endings, skipping `node_modules`, `node-portable`, and `venvs`. `cmd.exe` resolves `call :label` by byte offset and cannot find a label in an LF-only batch file once that label sits past a certain position, so a batch file saved with LF endings can fail the build with `The system cannot find the batch label specified`. Repository batch files are pinned to CRLF by `.gitattributes`; this normalization protects the workspace when an editor has rewritten one of them with LF endings.

The creator always includes `frontend\node-portable` and `frontend\node_modules`. They are required when the restricted build PC cannot restore Node dependencies itself. Before publication, the ZIP creator validates the complete ArcBot runtime chain: portable Node, npm, the Codex JavaScript entry point, the bundled Windows Codex executable, and the minimum CLI/model values in `frontend\electron\arcbot_runtime_contract.json`. If the local payload is stale, run `frontend\build\arcbot_runtime\refresh_bundled_codex_runtime.ps1` on the connected source PC before creating the ZIP.

### Required ZIP Content

The ZIP may contain one top-level `ArcRho` folder or the repository contents directly. It must contain at least:

- `frontend\build\build_app_via_local_workspace.bat`
- `frontend\build\transport\prepare_local_build_workspace_from_zip.ps1`
- `frontend\build\arcbot_runtime\refresh_bundled_codex_runtime.ps1`
- `frontend\package.json`
- `frontend\node-portable\node.exe`
- `frontend\node-portable\npm.cmd`
- `frontend\node-portable\node_modules\@openai\codex\bin\codex.js`
- The platform-specific Codex Windows executable under `frontend\node-portable\node_modules\@openai\codex\node_modules\@openai\codex-win32-x64\vendor`.
- `frontend\node_modules\electron-builder\cli.js`
- `frontend\node_modules\app-builder-bin\win\x64\app-builder.exe`
- The frontend application source, Electron host, icons, build resources, release fragments, and documentation.
- `python-api\pyproject.toml`
- `python-api\src`
- `python-api\tools`
- `BUILD_SOURCE_MANIFEST.json`, containing the ZIP creation time and available Git revision state.

The ZIP creator excludes generated content such as `frontend\dist`, `frontend\python_dist`, `frontend\python_build`, logs, cached Python packages, notebooks, editor/agent state, virtual environments, and Python cache files. The curated staging process never copies root repository metadata such as `.git`, `.agents`, or `.codex`.

## Step 2: Verify the Permanent E: Mapping on the Build PC

The build PC is expected to keep the source PC mapped as `E:`. Confirm the mapping and required files before each build:

```bat
net use E:
dir "E:\XWSpace\Build ArcRho App\ArcRho.zip"
dir "E:\XWSpace\Build ArcRho App\build_app_one_click.bat"
```

If `E:` is unavailable or points somewhere else, restore the established mapping before continuing. Do not substitute another drive letter for this workflow.

## Step 3: Check the One-Click Launcher on the Build PC

Open CMD on the build PC. The launcher defaults to `E:\XWSpace\Build ArcRho App\ArcRho.zip`; the local workspace override remains optional through `ARCRHO_LOCAL_BUILD_ROOT`:

```bat
set "ARCRHO_LOCAL_BUILD_ROOT=%USERPROFILE%\Documents\build_arcrho_app"
call "E:\XWSpace\Build ArcRho App\build_app_one_click.bat" --check
```

The `--check` command prints the resolved shared-folder and local-wrapper paths. Ensure the source-PC listener is already running before starting a build.

## Step 4: Run the One-Click Build on the Build PC

Run:

```bat
call "E:\XWSpace\Build ArcRho App\build_app_one_click.bat"
```

To use a specific semantic version instead of auto-incrementing the patch version:

```bat
call "E:\XWSpace\Build ArcRho App\build_app_one_click.bat" 1.2.0
```

For standalone Arcode, use the separate launcher in the same shared folder:

```bat
call "E:\XWSpace\Build ArcRho App\build_arcode_one_click.bat"
```

An explicit Arcode version can be supplied in the same way:

```bat
call "E:\XWSpace\Build ArcRho App\build_arcode_one_click.bat" 1.2.0
```

The Arcode launcher sets the common local-workspace wrapper to Arcode mode. It installs missing package-mapped build dependencies into the selected Python 3.10 interpreter, generates Windows icons from `icons\icon_wing_geo_v8.svg`, builds `arcode_server`, packages with `electron-builder.arcode.json`, publishes `Arcode-Setup-<version>.exe` to a GitHub Release (the update checker's source), and opens the locally built installer. The Arcode NSIS include observes native file-copy progress out of process so its percentage continues updating while NSIS installs files. It does not publish the external Python API wheel; that remains owned by the ArcRho application release workflow.

The launcher and its delegated local-workspace wrapper perform these steps:

1. Atomically writes a unique request into the shared `build_requests` folder.
2. Waits for the source-PC listener to create a fresh ZIP and return the matching response.
3. Waits for the fresh readiness token, then deletes and recreates the local build workspace.
4. Copies and extracts the ZIP locally while rejecting unsafe paths and skipping repository/agent metadata.
5. Builds the Python API wheel, PyInstaller app server, Electron application, and NSIS installer.
6. Verifies that the `win-unpacked` application still contains the portable Node, npm, Codex JavaScript entry point, and native Codex executable required by ArcBot.
7. Publishes a GitHub Release with the installer and checksum (the update checker's source), records the consumed readiness token after success, asks the source-PC listener to record the release in the repository, and opens the locally built installer from the workspace `dist` folder.

Do not run build tooling directly from the mapped repository. The one-click workflow ensures that dependency execution, PyInstaller, Electron Builder, and NSIS all run from a local filesystem on the build PC.

## Step 5: Verify Outputs and Preserve Logs

A successful build reports exit code `0` and produces:

- `%ARCRHO_LOCAL_BUILD_ROOT%\frontend\dist\Arco-Setup-<version>.exe`
- A GitHub Release tagged `Arco-v<version>` with `Arco-Setup-<version>.exe` and `Arco-Setup-<version>.exe.sha256` attached — the history the next build's version number is derived from.
- `Arco-update.json` rewritten on the `update-feed` prerelease by `publish_update_manifest.ps1` — the only file the packaged app's update checker reads.
- `E:\ArcRho Server\packages\arcrho_api-latest.whl`, unless `PYTHON_API_PACKAGE_DIR` overrides that destination.

The tag name, target repository, and update feed names come from `frontend\build\release\release_channel.json`, which `publish_github_release.ps1`, `publish_update_manifest.ps1`, `version_manager.py`, and the installed app read. Change them there rather than in any script.

ZIP-creation and application-build logs from both PCs are written directly to the shared handoff folder, separated by Windows computer name:

```text
E:\XWSpace\Build ArcRho App\logs\<COMPUTERNAME>\create_build_source_zip_<timestamp>.log
E:\XWSpace\Build ArcRho App\logs\<COMPUTERNAME>\build_app_via_local_workspace_<timestamp>.log
```

The build-PC local-workspace log covers ZIP validation, local copying and extraction, the complete application build, publishing, and the final exit code. Logs no longer need to be copied back from the build PC's local workspace.

## Step 6: Repository Sync (Automatic)

The build runs from a disposable local workspace, so everything it writes back into the source tree is destroyed with that workspace: the version bump in `package.json`, `package-lock.json`, `ui\index.html`, and `ui\splash.html`; the generated `docs\releases\<version>.md`; and the archiving of the changelog fragments the release consumed. None of it can reach the repository from the build PC, which does not hold the repository at all.

Left unrecorded, the repository reports a version older than what shipped, and `changes\unreleased` never drains — so every later release regenerates notes covering the entire fragment history until the body outgrows the GitHub release limit.

**This now happens by itself.** After publishing the GitHub Release, the build wrapper sends a `syncRelease` request to the same source-PC listener that produced the ZIP, and waits for the outcome. The listener runs `sync_published_release.py`, which:

1. Verifies the release tag exists on the remote through `git ls-remote`, so the source PC does not need the `gh` CLI.
2. Writes the version into every file that carries it.
3. Generates the release notes and archives the fragments the release consumed into `changes\archive\<version>`.
4. Regenerates the documentation index.
5. Commits **only** that release bookkeeping and stops. Nothing is pushed, and unrelated work in the worktree is never staged.

Which fragments count as consumed comes from a snapshot the listener captures when it builds the ZIP, stored under `build_zip_fragments\<readySignal>.json` and keyed by that ZIP's ready signal. The release consumes exactly the fragments it was built from even if a later build has already replaced the ZIP. Fragments written after the ZIP was cut stay unreleased and belong to the next version.

### When the automatic sync does not run

A sync failure never invalidates the installer that was already published — only the repository bookkeeping is missing. The build reports a warning with the command to finish it by hand on the **source PC**:

```bat
frontend\build\sync_published_release.bat 1.2.5
```

The manual command behaves the same way but does not commit unless you add `--commit`. Add `--dry-run` to see the version change and the fragment split without writing anything.

The most likely cause is that the listener is not running on the source PC, in which case the build waits ten minutes before giving up. Start it with `build_app_listener.bat` and re-run the manual command.

> The listener loads its script once at start. After changing `build_app_listener.ps1`, restart it or it keeps running the previous version.

## ZIP Freshness Rules

- Run `build_app_one_click.bat` after every source change that must be included in the final app; it requests a fresh ZIP automatically.
- The ZIP is a snapshot; editing the repository after ZIP creation does not update the build input.
- The local build wrapper waits while the readiness token matches the archive used by the previous successful build. Each listener-created ZIP publishes a new token.
- A failed build does not update the consumed-signal marker, so another one-click run retries with a newly requested ZIP.
- The ZIP creator writes `ArcRho.zip.sha256`. For important releases, compare that value with `Get-FileHash -Algorithm SHA256` on the build PC.

## Troubleshooting

### ZIP extraction fails on `.agents` or another directory entry

Use the current `prepare_local_build_workspace_from_zip.ps1`. It handles standard forward-slash ZIP directory entries that Windows PowerShell 5.1 `Expand-Archive` can misinterpret.

### The one-click launcher waits without receiving a response

Confirm that `build_app_listener.bat` is still running visibly on the source PC. Its terminal and logs report any ZIP-creation failure. The build-PC launcher leaves a failed response in `E:\XWSpace\Build ArcRho App\build_responses` for troubleshooting.

### ZIP extraction reports a very long `.git\refs\codex` path

The archive was created from the raw repository instead of the clean ZIP creator. Regenerate it using Step 1. The current extractor skips root `.git`, `.agents`, and `.codex` entries, but those files should not be transported in the first place.

### The build stops with `The system cannot find the batch label specified`

The batch file holding that label was saved with LF-only line endings. `cmd.exe` locates a `call :label` target by byte offset, and the search fails once the label sits past a certain position, so the error appears even though the label is present. Restore CRLF endings in the affected `.bat` file on the source PC, regenerate the ZIP, and rebuild. `.gitattributes` pins `*.bat` and `*.cmd` to CRLF, and workspace staging normalizes them, so this should only surface if a batch file was edited outside those paths.

### NSIS reports `macro named "MUI_HEADER_TEXT" not found`

This is an installer-source/include-order problem, not a ZIP, mapped-drive, or permission problem. Fix `frontend\build\installer\installer.nsh` so `MUI2.nsh` is available before `MUI_HEADER_TEXT` is expanded, regenerate the ZIP, and rebuild.

### Electron Builder reports `spawn EPERM` for `app-builder.exe`

From the local `frontend` workspace on the build PC, unblock the executable and rerun the build:

```bat
powershell -NoProfile -Command "Get-Item '.\node_modules\app-builder-bin\win\x64\app-builder.exe' | Unblock-File"
```

### Python validation fails

Install Python 3.10.6 or newer within the Python 3.10 line, or set `PYTHON_EXE` to the compatible interpreter before invoking the wrapper.

### Publishing fails after the installer builds

If the version step or the GitHub Release publish step fails, confirm `gh auth status` succeeds on the build PC (or that `GH_TOKEN` is set) and that the authenticated account can create releases on the target repository. The version step deliberately fails instead of falling back to `package.json`: the build runs from a disposable workspace, so `package.json` lags behind what has shipped, and a silent fallback would rebuild a version number that is already public. If the Python API package step fails, verify that the build PC can write through its mapped `E:` drive to the configured Python package destination on the source PC.

### ArcBot reports that Codex cannot launch after installation

Confirm that the build log's ArcBot runtime validation passed and that the installed application contains the same portable Node/npm/Codex files verified in `win-unpacked`. ArcBot launches those child processes from the user's writable `Documents\ArcRho` folder rather than from `app.asar`. Its Repair action uses an ArcRho-owned per-user npm prefix and should not require administrator access or a machine-global Node installation.

## Completion Checklist

- The source-PC listener was running before the build request was sent.
- The one-click launcher received a fresh ZIP response from the listener.
- The build PC's permanent `E:` mapping is available and can read the source ZIP.
- The build ran from `%USERPROFILE%\Documents\build_arcrho_app`, not the network share.
- The build exited with code `0`.
- The GitHub Release the update checker reads was created with the installer and checksum attached, and the release notes and Python API package were published.
- The pre-build and `win-unpacked` ArcBot runtime checks found portable Node, npm, the Codex JavaScript entry point, and the native Windows Codex executable.
- The timestamped build log was retained when troubleshooting was required.
