---
name: project-duplication-diagnostics
description: "How to debug an ArcRho project-duplication failure — the shared status message is redacted by contract, so read the status JSONs and the engine-local log"
metadata: 
  node_type: memory
  type: project
  originSessionId: b0ec034e-0a3d-47bf-a13b-25fdc7f5fd6e
  modified: 2026-09-27T21:54:31.663Z
---

Project-duplication failures surface to the UI as "The ArcRho Server filesystem
could not complete project duplication." That string is deliberate: any
`OSError`/`shutil.Error` is redacted in `_safe_status_error`
(`server-components/src/arcrho_engine/project_duplication.py`) so shared status JSON
stays location-independent. The Engine exe is built `--noconsole` with no
logging, so `print()` diagnostics are lost on deployed machines.

Where to look instead:
- `E:\ArcRho Server\requests\project_duplication\status\psdup_*.json` — one file
  per attempt, with `progress.completed`/`total` and the redacted message. The
  history across attempts is the diagnosis: a *fixed* stop point means a
  structural bug, a *varying* stop point means transient I/O.
- `E:\ArcRho Server\runtime\logs\project_duplication.log` — added 2026-08-09;
  unredacted errno + traceback, plus one line per copy retry.

**Why:** without the varying-vs-fixed stop point signal I chased a plausible but
wrong MAX_PATH theory for two rounds.

Two known causes seen 2026-09-27 (source NJ_Annual_Prod_2026 Q3-Aug):
- "source project changed during duplication": the app rewrote
  `users/<user>/preferences.json` inside the source project mid-copy. Fixed and
  deployed the same day: the comparison now skips `users/`, the self-validating
  caches and each class's `index.json`, and lock/tmp files are not copied.
- Redacted "filesystem could not complete": a *progress* status write lost its
  `os.replace` retries (~1.1 s) to the app polling the status file every 750 ms,
  and any progress-write failure aborts the whole copy.

A third cause, seen 2026-11-11 (source IBNR_Allocation_2026 Sep), was a real
MAX_PATH hit with a *fixed* stop point (class 2,859 of 3,614, every attempt):
the staging folder name is 36 characters longer than that project's name, which
carried a 224-character cache-provenance file to exactly 260, and the Server PC
has `LongPathsEnabled=0` (the user cannot change it). The log shows it as
`[Errno 2] No such file or directory` on the *staging* path, not as a length
error. Fixed the same day: the copy addresses the projects folder as `\\?\...`.
Only the copy job does this; the rest of the server code still uses plain
paths, so a class whose own files pass 259 characters still cannot be saved.
That project's longest file was 231 characters that day.

**How to apply:** read the status JSON history *before* theorizing. Client PCs
reach the server over a mapped network drive (`\\NE7SASWPN02\E`), so every
duplication byte crosses SMB and transient sharing violations / session drops
are normal — that is why the copy retries. See [[arcrho-server-client-topology]].
