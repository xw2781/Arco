# Project Registry And Source Table Lookup

## Canonical Files

Project discovery and source table lookup are intentionally split:

| File | Owner | Purpose |
| --- | --- | --- |
| `projects/index.json` | Frontend/project registry | Lists project names and their virtual UI folders. It does not store source CSV paths. |
| `projects/<ProjectName>/field_mapping.json` | Project settings and data-engine | Stores the project source CSV `table_path` plus field mapping rows. |

## `projects/index.json`

The project index is a UI/project-discovery registry:

```json
{
  "version": 1,
  "projects": [
    {
      "name": "NJ_Annual_Prod_202605_Fake",
      "folder": "Fake Project"
    }
  ],
  "folders": [
    {
      "name": "Fake Project",
      "path": "Fake Project",
      "parent": ""
    }
  ]
}
```

`folder` is a virtual folder path shown in the UI. It is not a Windows file-system path.

## Data-Engine Lookup

Data-engine does not read `projects/index.json` for source table paths. For a request with `ProjectName`, it resolves:

`projects/<ProjectName>/field_mapping.json`

and reads `table_path` from that file. If the project folder, `field_mapping.json`, or `table_path` is missing, the request is invalid.

## Project Duplication Jobs

Project Settings delegates project-folder duplication to an Arco Engine worker on the ArcRho Server host. The client app publishes a versioned `ArcRhoDuplicateProject` request containing a request ID, source and target logical project names, the requesting user, and the canonical server-root-relative projects-directory setting. Client drive letters, UNC aliases, absolute paths, and producer-selected target paths are not part of the contract. The dedicated duplication protocol always uses `<server-root>/requests`, which is the queue Arco Engine monitors; a custom projects-directory setting remains location-independent and is validated before the Engine derives its absolute path.

The canonical request/status contract lives in `python-api/src/arcrho_project_duplication_contract.py`. Each worker derives the project paths and the matching status path from its own ArcRho Server root. The top-level request remains durable until a validated terminal status exists. A renewable per-request lease prevents concurrent workers from handling the same job, while progress and terminal status are atomically replaced under `requests/project_duplication/status`. One bounded background worker runs duplication with at most one additional queued job, so a long folder copy does not block the Engine's ordinary calculation requests; the durable filesystem queue remains the backlog. The Engine rescans the top-level request queue every five seconds, so a request submitted while the Engine is offline or while that worker is full is picked up later.

The worker copies the source into a same-parent staging folder, publishes indeterminate progress while copying project-level files, then reports completed/total counts while copying the materialized reserving-class folders under `data`. Transient data-root folders such as `.arcrho-resq-import-staging` and `tmp` are excluded. The worker addresses the projects folder in Windows' extended-length form (`\\?\`), so a long reserving-class folder under the longer staging name is not stopped by the 260-character path limit, whatever the machine's long-path setting. A successful copy is exposed by renaming the completed staging folder to the target name and publishing terminal success while the target lock is still held. If success publication fails, the worker atomically quarantines the target under its private staging name before verifying and removing an unchanged copy. A changed or unverifiable copy is restored to the target when possible; if restoration is unsafe or blocked, its staging folder is retained for operator recovery rather than deleted.

Before publishing the target, the worker records an atomic recovery journal containing the exact request, verified staged-copy manifest, and reserving-class total. After a process restart, the retained request and journal let the Engine safely discard an unverified partial staging folder and restart, publish a verified staging folder, or republish success for an unchanged target. Changed, missing, unverifiable, or ambiguous recovery artifacts produce a terminal `recovery_required` error and are preserved for operator inspection. Project Settings likewise retains the job ID and never deletes a possibly completed target when polling or metadata finalization is uncertain.

The lease heartbeat substantially narrows stale-worker takeover risk, but ordinary filesystems cannot atomically combine an owner-token check with unlinking the lease or target-lock file. Strict fencing across that theoretical check/unlink race would require an OS-backed lock or owner-specific immutable fencing artifacts.
