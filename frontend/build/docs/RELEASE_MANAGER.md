# ArcRho Release Manager

Release Manager is the control surface for locally building an installer, testing
it, and publishing it only when it is ready. Run it from the repository root with:

```bat
frontend\build\release_manager.bat
```

It requires Python 3.10, the local frontend build prerequisites, and an authenticated
GitHub CLI (`gh`) for version suggestions, release history, publishing, and revocation.

## How It Runs

The batch file starts a small HTTP server bound to `127.0.0.1` on a free port and
opens the UI in the default browser. The console window it starts from is part of the
tool: it prints the URL and must stay open while you build, publish, or revoke.
Choose **Quit** in the UI or press Ctrl+C in that window to stop the server.

The UI ships a dark theme by default and a light theme behind the theme button in the
title bar; the choice is remembered per browser.

Every request carries the one-time session token in the launch URL, and the server
rejects requests that arrive with an unexpected `Host` header, so another page in the
browser cannot drive a build or a publication. Opening the URL without that token
shows the UI but no data. `--port` pins a port and `--no-browser` prints the URL
instead of launching a browser.

Only one build, publish, or revoke runs at a time; a build that publishes afterwards is
one such operation of two steps. Its output streams into the **Activity** panel; the
panel is served from the server's buffer, so reloading the page or opening it in a
second tab still shows the operation in progress.

## Build And Test

Choose ArcRho or Arcode, enter a semantic version, and select the build button. The
suggested version is the next patch after the newest relevant GitHub Release; selecting
it fills the Version field, but any valid custom version can be entered instead.

**Publish after build** is enabled by default: the build button reads **Build and
publish**, one dialog confirms both steps, and a successful build is published straight
away with the same workflow, checks, and **Commit bookkeeping** setting that
**Publish selected** uses. A failed build publishes nothing. Clear the checkbox to build
only, test the installer, and publish later from panel 2.

The build-only workflow:

1. Validates the requested version against the package and published-release history.
2. Applies that version only while packaging the installer.
3. Records the installer hash, release-fragment names and hashes, and—when applicable—the
   Python API wheel in `%USERPROFILE%\Documents\ArcRho Local Build\pending_releases`.
4. Restores `package.json`, `package-lock.json`, the About dialog, and the splash page to
   their exact pre-build contents.

No GitHub Release, shared Python API wheel, release-note file, fragment archive, or
release-bookkeeping commit is produced by a build-only run. Select a recorded installer
and choose **Open installer** to test it locally.

## Publish

After testing, select the pending record and choose **Publish selected**. The workflow
rechecks the installer and fragment hashes before it creates the GitHub Release, so a
changed installer or release fragment must be rebuilt rather than silently published.

For ArcRho, the stored Python API wheel is published to the destination recorded during
the build (normally `E:\ArcRho Server\packages`) only after the GitHub Release succeeds.
Then the existing repository bookkeeping workflow writes version metadata, release notes,
and the matching fragment archive. The **Commit bookkeeping** setting is
enabled by default; it never pushes a branch.

If GitHub succeeds but a later wheel or bookkeeping step fails, the local record is marked
`remote published`. Select it and publish again to complete the remaining local steps; the
installer is not uploaded a second time.

## History And Revocation

The history panel lists the latest 20 releases for the selected product from the canonical
repository and tag format in `build/release/release_channel.json`, ordered newest first by
publication time. A draft that was never published has no publication time and sorts last.
`release_workflow.list_release_history` owns that order, so the `history` command prints the
same sequence.

To revoke a release, select it, choose **Revoke selected**, and type the displayed version
again. This permanently deletes the GitHub Release, its assets, and its Git tag through
`gh release delete --cleanup-tag`, then rebuilds the update feed so installed apps stop being
offered the deleted installer. It intentionally leaves repository bookkeeping and
release-note history intact: undoing a published release commit or re-opening archived
fragments can conflict with later releases and must be handled deliberately.

## Command-Line Equivalent

Release Manager runs the same commands available to automation:

```bat
frontend\build\build_app_from_local_repo.bat --build-only 1.3.0
frontend\build\build_app_from_local_repo.bat --publish 1.3.0
```

Omit `--build-only` to retain the previous one-step build-and-publish behavior.
