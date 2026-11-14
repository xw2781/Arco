# Agent Memory Setup

How the tracked agent memories reach the agent harness on each machine, and how they are committed.

Claude Code project memories are tracked in this repository under `agent-memory/`, with `agent-memory/MEMORY.md` as the index. They are reviewed and committed to `main` like any other documentation, so a hard-won debugging technique survives a machine rebuild and reaches every clone.

The agent harness derives its memory directory from the repository's absolute path (`%USERPROFILE%\.claude\projects\<slug>\memory`) and offers no setting to move it. Run `tools/link_agent_memory.ps1` once per machine and per clone path to make that directory a junction pointing at `agent-memory/`; memory writes then land in the working tree. The script is idempotent, needs no elevation, and refuses to replace a non-empty real memory directory without `-Force`. Restart Claude Code afterwards so the index is loaded at session start.

**Setting up a new clone is two steps, and skipping either one silently loses memories.** Run `tools/link_agent_memory.ps1`, then restart. Without the junction the harness writes into a real directory outside the tree, nothing commits it, and that machine's memories never reach anyone else — a divergence that is invisible until an agent gives a wrong answer from a stale index.

Committing memories is automatic and is the one exception to the push rule in the `arcrho-commit-workflow` skill (no push without separate approval). The `Stop` hook in `.claude/settings.json` runs `tools/sync_agent_memory.sh`, which commits and pushes `agent-memory/` — and only `agent-memory/` — at the end of each turn. It uses the pathspec form of `git commit`, so work staged elsewhere is never swept in, and it does nothing during a rebase, merge, cherry-pick, or on a detached HEAD. A rejected push leaves the commit local for the next run to carry. Do not commit `agent-memory/` by hand as part of another change; let the hook own it, so a memory edit never rides along in an unrelated commit.

`.claude/settings.json` is tracked for this reason: a hook that exists on only one machine cannot keep two machines in sync. Keep machine-specific paths out of it — resolve the repository root at runtime with `git rev-parse --show-toplevel`. Per-machine overrides belong in `.claude/settings.local.json`, which stays ignored.

Because these notes are now shared across machines, a memory that depends on one workstation's layout — installed interpreters, drive letters, a bundled `node-portable`, a count of tests already failing at HEAD — must say so in its own text instead of being written as a universal fact.
