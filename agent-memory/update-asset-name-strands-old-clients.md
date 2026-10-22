---
name: update-asset-name-strands-old-clients
description: "Clients after 2.0.0 find updates only through the update-feed asset (Arco-update.json); 2.0.0 and earlier scan the release list by installer asset name, so a rename strands them"
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b08eeaa-1c7d-45d6-9211-6fb739f49858
  modified: 2026-10-22T00:00:00.000Z
---

Since 2026-10-22 the desktop updater reads one file: `Arco-update.json` on the fixed `update-feed` prerelease of `xw2781/Arco`, written by `frontend/build/release/publish_update_manifest.ps1` (run at the end of every publish and after every revoke). The installer's name, URL and SHA-256 come from that file, so the installer asset name is no longer a contract for these clients. If the feed is missing or stale, every new client reports "could not reach the update location" or misses the release; rerun the script.

Clients 2.0.0 and earlier still scan the GitHub release list and accept only assets matching their compiled-in name (`Arco-Setup-<version>.exe` plus a `.sha256` sibling). The 2026-09-20 Arco rename stranded 1.7.1 clients until byte-identical `ArcRho-Setup-*` copies were uploaded; that bridge ran through Arco-v1.7.3.

**Why:** the feed replaced the API scan because the GitHub API's 60 requests per hour per address was exhausted by the whole office sharing one address.

**How to apply:** never rename the installer asset while 2.0.0-or-earlier clients remain; for newer clients, check the feed file instead of asset names. As of 2026-10-22 the Server PC (NE7SASWPN02) has no `gh` installed, so publishing and seeding the feed must run where `gh auth login` was done. Windows PowerShell 5.1 passes a parsed JSON array down the pipeline as one object; unroll it with `ForEach-Object { $_ }`. Relates to [[all-users-run-latest-app-version]] and [[arcrho-local-release-build]].
