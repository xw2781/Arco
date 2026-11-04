---
name: project-dates-change-job
description: "2026-11-04: the Project Dates panel's Engine job moves a whole project to new dates; its pending record changes how every method reads its precedents until it clears; where to look when a change is stuck or reports problems"
metadata:
  node_type: memory
  type: project
  modified: 2026-11-04T07:00:00.000Z
---

Since 2026-11-04 (plan `docs/plans/completed/project_dates_panel.md`, deployed to the Bridge,
Engine and Gateway that day) the project dates change only through the Project Dates panel. The
panel submits one durable Engine job (`arcrho_project_dates_job_contract`, worker
`server-components/src/arcrho_engine/project_dates_jobs.py`, queue
`requests/project_dates/{requests,statuses,pending}`), which saves the dates, reshapes hand-entered
datasets, Result Selection and Berquist-Sherman methods, regenerates the engine datasets, and walks
the dependents class by class. The reshape rule (origins by label, developments by position) lives
once in `python-api/src/arcrho_api/period_reshape.py`.

**The pending record changes method reads.** While `requests/project_dates/pending/<project>.json` exists,
`precedent_cache_service.precedent_origin_labels` labels a precedent's rows with the *new* origins
whenever the method still carries the previous dates' grid. With no record every loader reads
exactly as before, which is why the deploy was safe for clients that predate the panel. A record
left behind (a crashed run, or classes kept for a retry) makes the preview answer "resumed" and
refuses other dates with 409 until the same dates are run again.

**Diagnosing a change.** The status JSON under `requests/project_dates/statuses/` holds every
failure, `dependent_problems` (one line per declined dependent, not just the first), the `review`
items and `rerun_needed`. A start-of-year move on the Fake project needs two runs (~17 then ~11
min); problems the project had before the change (BF snapshot mismatch, mixed origin lengths)
stay and never hold the record.

**Testing on the Server PC.** Production's Gateway answers on 127.0.0.1:28767 too, so a local-root
Gateway there must move to another port (28777 was used) for the test and back afterwards. Move
the port in `C:\Arco Server\config\arcrho_gateway.json` *before* `local_server.py deploy gateway`:
the build relaunches the local Gateway at once, and on 2026-11-04 it bound 127.0.0.1:28767 beside
production's 0.0.0.0:28767 (the narrower bind wins loopback traffic) until it was stopped. See
[[local-test-root]]. Related: [[adding-a-project-level-engine-job]],
[[excel-linked-cells-keep-absolute-position]], [[mixed-origin-length-precedents]].
