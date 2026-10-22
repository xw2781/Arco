# Auto-Update Reliability — Handoff

Started 2026-10-22 on the Client PC (`L-H2MQ6280FVP`); to be finished on the Server PC.

## Why

Users report that auto-update often fails and has to be retried several times. Causes found:

1. **GitHub API limit.** The app lists releases through `api.github.com`, which allows 60 unauthenticated requests per hour per public IP. Every office user shares one IP, so checks fail with "could not reach the update location" until the hour resets.
2. **Renamed repository.** The repo moved from `xw2781/ArcRho` to `xw2781/Arco`. The old name still works through a 301, but each check then costs 2 of the 60 requests.
3. **3-second check timeout.** The release list is about 500 KB (30 releases with full notes), plus a checksum fetch with redirects. Slow connections exceed 3 seconds; the startup check then fails silently.
4. **Installer download with no retry.** The installer is about 366 MB. A dropped connection fails the update and the next try starts from zero. A stalled connection leaves the update window open forever with the main window hidden.
5. **No diagnostics.** Update failures only go to `console.warn`, which an installed app never shows.

## Design (approved by the user: "make all suggested changes, plus add a local log")

- **Update feed file.** Each publish rebuilds `<Product>-update.json` from the published releases and uploads it to a fixed prerelease tag (`update-feed`). The app downloads it from `https://github.com/<repo>/releases/download/update-feed/Arco-update.json`. Release asset downloads are not subject to the 60/hour API limit. One small request replaces the release list plus the checksum fetch.
- **Manifest shape:** `{ product, version, installer, url, sha256, releases: [{ version, publishedAt, body }] }`. `releases` holds the newest 10 releases of the product, newest first, so the dialog can still show the notes of skipped versions. The client keeps deriving `mandatory` from the bodies with `MANDATORY_MARKER_RE`.
- **Single source of truth.** `frontend/build/release/release_channel.json` owns `githubRepo`, `updateFeedTag` and `updateFeedAsset`. Packaging copies it into the app's resources folder (`extraResources` in `package.json` and `electron-builder.arcode.json`). The client reads it from `process.resourcesPath` when packaged, and from the source tree otherwise. The `ARCRHO_UPDATE_GITHUB_REPO`/`ARCODE_UPDATE_GITHUB_REPO` overrides stay.
- **Old clients** (2.0.0 and earlier) keep scanning the API. Releases still carry the installer and the `.sha256` asset, and the feed release is a prerelease, which they skip. Per the `all-users-run-latest-app-version` memory, the new client needs no API fallback.

## Done (committed with this note)

- `release_channel.json`: repository renamed to `xw2781/Arco`; `updateFeedTag` and `updateFeedAsset` added.
- `build/release/publish_update_manifest.ps1` (new): builds and uploads the feed from `gh api`. It is stateless, so running it again is safe. It creates the `update-feed` prerelease on first run.
- `publish_github_release.ps1`: calls the manifest script after every publish.
- `package.json`, `electron-builder.arcode.json`: ship `release_channel.json` as an extra resource.
- `electron/update_checker.js`, partial:
  - `initUpdateChecker` reads the channel file and computes `UPDATE_FEED_URL`.
  - The check timeout default is now 15000 ms.
  - A `downloadRetryDelaysMs` init option exists (tests inject `[]` or small values).
  - New constants: `UPDATE_LOG_FILE`, `DOWNLOAD_STALL_TIMEOUT_MS`.
  - `getElectronLogPath` and `formatErrorForLog` are imported.
  - **The release-list scan still runs**, using the temporary `GITHUB_API_ROOT`/`MAX_RELEASES_SCANNED` constants marked `HANDOFF`, so the app keeps working in this state. The updater tests pass (13/13).

## Remaining steps

1. **Seed the feed once on the Server PC** (where `gh` is authenticated): `powershell -File frontend\build\release\publish_update_manifest.ps1 -ProductName Arco`. Check that `https://github.com/xw2781/Arco/releases/download/update-feed/Arco-update.json` downloads and holds 2.0.0 with its sha256. The script has never been run; check the `tagPattern` built from `tagFormat`, the `gh release download --pattern` call, and the BOM-free UTF-8 write.
2. **Feed reader in `update_checker.js`.** Replace `fetchReleases`, `readAssetText`, `installerReleaseCandidates`, `findAvailableUpdateFromReleases` and `createUpdateIssue` with one function:
   - Fetch `UPDATE_FEED_URL` and fail on a non-OK status.
   - Return `null` unless `manifest.version` is newer than `app.getVersion()`.
   - Build `updateInfo` from the manifest: `assetName` = `installer`, `downloadUrl` = `url`, `releases` = entries newer than the current version.
   - Delete the `HANDOFF` constants. Drop the `missing-checksum` branch in `checkForUpdate` and the `reportIssues` option.
3. **Download retry and resume** in `downloadReleaseAsset`:
   - Make up to `downloadRetryDelaysMs.length + 1` attempts.
   - Resume with `Range: bytes=<received>-`: append to the `.part` file on a `206` response, restart on a `200`.
   - Arm an `AbortController` stall timer (`DOWNLOAD_STALL_TIMEOUT_MS`) and reset it on every chunk; report "No data received for 30 seconds".
   - Treat a body shorter than `content-length` as a failed attempt.
   - Keep the single "start" progress event and the existing `.part` cleanup on final failure.
4. **Update log.** Add `logUpdate(message, err)`, which appends a timestamped line to `path.join(path.dirname(getElectronLogPath()), UPDATE_LOG_FILE)` and still calls `console.warn`. Use it for:
   - check start, result and elapsed time;
   - feed errors;
   - download start (size), each retry or stall with the byte offset, and completion;
   - verify result, launch attempts, launch outcome and cleanup.

   Replace the existing `console.warn` calls. Log retention (30 days, `log_retention.js`) already covers `.log` files in that folder.
5. **Tests** in `frontend/tests/electron_host_modules.test.mjs`:
   - Rewrite the fetch stubs from `/releases?` plus `.sha256` to the feed URL.
   - Remove the missing-checksum test.
   - Add tests for resume after a mid-body error (a second request carries `Range` and gets a 206), for the stall timeout (inject a short stall constant or option), and for `update.log` being written.
   - Pass `downloadRetryDelaysMs: []` where a download is meant to fail fast.
   - Extend the release-channel test in `tests/bundled_codex_runtime.test.mjs` to assert the new keys and that `publish_github_release.ps1` calls `publish_update_manifest.ps1`.
6. **Docs:**
   - `frontend/docs/ui/shell.md` (update bullets around lines 104–110 and line 210): feed instead of the API scan, the 15 s timeout, 10 releases of notes, retry/resume/stall, and `update.log`.
   - `frontend/build/README.md`, `build/docs/BUILD_FROM_LOCAL_REPO.md`, `build/docs/RELEASE_MANAGER.md`, `build/docs/BUILD_FROM_ZIP_ON_SECOND_PC.md`: the new script and channel keys.
   - Add `publish_update_manifest.ps1` to both file lists in `build/transport/create_build_source_zip.ps1`.
   - Run `python tools/docs_index_builder.py --write` then `--check`.
7. **Release fragment** `frontend/changes/unreleased/update_reliability.json`: type `fix`, scope `update`, audience `user`. Summary along the lines of "Updates no longer fail on slow or shared office connections". Validate with `python build/release/release_notes.py check`.
8. **Memory:** update `agent-memory/update-asset-name-strands-old-clients.md` (new clients read the feed, not asset names) and `installer-close-processes-and-one-click-update.md` as needed.
9. Delete this handoff file once all steps are done.
