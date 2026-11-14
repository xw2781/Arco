---
name: deploy-ref-main-resolves-stale-branch
description: "deploy.py --ref main builds the buildbot clone's stale local main; pass the full commit hash instead"
metadata:
  node_type: memory
  type: project
  originSessionId: 02340404-4d02-42e5-9394-8619af4a40a8
  modified: 2026-11-14T18:05:26.782Z
---

`server-components/deploy.py --ref main` on the Server PC built an old commit (ea15a683) on 2026-11-14: the listener resolves `main` before `origin/main`, and the buildbot clone (`E:\XWSpace\Repos\ArcRho-buildbot`) keeps a stale local `main` branch. Its remotes also still pointed at the pre-rename `ArcRho.git` and the missing `E:\XWSpace\Repos\ArcRho` folder; repointed that day to `Arco.git` and `E:/XWSpace/Repos/Arco`.

**Why:** an old checkout fails in `utils.find_project_root` ("Could not find parent folder named one of [ArcRho Server, ArcRho, ADAS]"), which looks like a code bug but is just the wrong commit.

**How to apply:** after pushing, deploy with `--ref <full hash>`. If a Bridge deploy aborts with "did not stop within 60s" and no Bridge process exists, run `tools\arcrho_service_control.ps1 -Action clear-stale-heartbeats` and retry. Related: [[remote-component-deploy]].
