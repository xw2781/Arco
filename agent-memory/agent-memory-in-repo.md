---
name: agent-memory-in-repo
description: Project memories are stored in the tracked repo folder agent-memory/ and reach the harness path through a directory junction
metadata: 
  node_type: memory
  type: project
  originSessionId: 05c09575-2234-4404-bf4e-fcede99def6e
  modified: 2026-08-21T03:56:13.106Z
---

Claude Code memories for ArcRho are **tracked in the repository**, not left under the user
profile. The files live in `agent-memory/` at the repo root and are committed to `main` like
any other doc.

The harness memory path is not configurable, so `%USERPROFILE%\.claude\projects\<slug>\memory`
is a Windows **directory junction** pointing at `<repo>\agent-memory`. Writes through the
harness path land in the working tree and show up in `git status`. The `<slug>` is the repo's
absolute path with the drive letter lowercased and `:\` / `\` collapsed to `-` — for
`c:\Users\xwei\Repos\Arco` that is `c--Users-xwei-Repos-Arco`.

Recreate the junction on a new machine or a fresh clone with
`pwsh tools/link_agent_memory.ps1` (see `AGENT_GUIDELINES.md` -> Agent Memory). It is idempotent, needs
no elevation, and refuses to clobber a non-empty real memory directory.

Because memories are now shared across machines, a note that depends on one workstation's
layout (installed interpreters, drive letters, `node-portable` presence, pre-existing test
failure counts) must say so in its own text rather than being written as a universal fact.

**The Stop hook's memory sync pushes the whole branch, not just memory commits.** The hook
commits only `agent-memory/` paths, but its `git push` is branch-level, so any local code
commits sitting on `main` ride along to the remote at the end of the turn (observed
2026-08-20: fix commit `bcffffb` reached the remote under the memory commit on top of it).
**How to apply:** never tell the user a `main` commit is "local until you approve the push" —
it will be pushed by the next memory sync. Work needing push approval must stay on a branch
or uncommitted.
