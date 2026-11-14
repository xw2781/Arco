---
name: arcrho-sync-workspace
description: Bring an ArcRho clone back in line with its remote when moving the development workspace between NE7SASWPN02 and L-H2MQ6280FVP. Use proactively without asking for permission to use the skill when the user asks to sync, update, or refresh the local repo, pull the latest, check whether this machine is behind, or says they have switched machines. Fast-forwards on its own when the clone is clean and behind, and always asks before touching local commits or uncommitted work.
---

# ArcRho Workspace Sync

Two machines hold working clones of this repository and the user moves between
them. This skill makes the clone in front of it match the remote, without ever
losing work that exists only here.

## Invocation

Use this skill automatically for requests such as "sync the repo", "update the
local repo", "pull the latest", "I just switched machines", "is this machine
behind?", or "get a clean copy from the remote".

The survey in Step 2 is read-only and needs no approval — run it immediately.
Everything that moves a ref or the working tree follows the rules below.

## Step 1 — Refuse to sync the wrong clone

Ask git rather than reading inside `.git`, which the agent is usually not
allowed to open:

```powershell
git rev-parse --show-toplevel
git config --get remote.worktree.url
git symbolic-ref --quiet --short HEAD
git rev-parse --verify -q MERGE_HEAD
git rev-parse --verify -q CHERRY_PICK_HEAD
git status
```

Stop and report instead of syncing when any of these is true:

- **The listener's clone.** `remote.worktree.url` is set, or the path ends in
  `-buildbot`. That clone belongs to the ArcRho Build Listener, which
  force-detaches, resets and cleans it at the start of every build request.
  Never sync it as a workspace; updating it is the deploy task described in
  `AGENT_GUIDELINES.md`, not this skill.
- **An operation is half-finished.** `MERGE_HEAD` or `CHERRY_PICK_HEAD` resolves,
  or `git status` reports a rebase in progress. Report what is in flight and let
  the user finish or abort it first.
- **HEAD is detached** — `git symbolic-ref` fails — or the branch is not the one
  that tracks the remote. Report the branch and ask what to do before moving
  anything.

Then confirm which machine and which clone this actually is:

```powershell
hostname
$root = git rev-parse --show-toplevel
$drive = Split-Path -Qualifier $root
(Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$drive'").DriveType
```

`DriveType` is `3` for a local disk and `4` for a network drive. The Server PC
shares its whole workspace drive and the Client PC maps it to the same letter,
so the path alone proves nothing about which machine holds the files.

**If the clone sits on a network drive, it is the other machine's clone seen
through the share.** There is nothing to sync — both machines are already
editing the same files, and any reset here hits the other machine's work.
Say so and stop. On L-H2MQ6280FVP the machine's own clone is the one on `C:`,
not the mapped `E:`.

## Step 2 — Survey before deciding anything

```powershell
git fetch origin --prune
git status --short --branch
git rev-list --left-right --count '@{upstream}...HEAD'
git log --oneline '@{upstream}..HEAD'
git status --porcelain
```

The count prints `<behind><TAB><ahead>`. Fall back to `origin/main` when the
branch tracks no upstream, and say so in the report.

## Step 3 — Classify, then act

| State | Meaning | Action |
| :--- | :--- | :--- |
| behind 0, ahead 0, clean | already in step | Report and stop. |
| behind 0, ahead 0, dirty | in step, work in progress here | Nothing to sync. List the uncommitted files and stop — do not touch them. |
| behind N, ahead 0, clean | pure catch-up | **Fast-forward without asking.** |
| behind N, ahead 0, dirty | remote moved, uncommitted work here | Ask — Step 5. |
| ahead N, clean or dirty | work exists only here | Ask — Step 5. |
| behind N and ahead M | diverged | Ask — Step 5. |

A fast-forward is the only case that proceeds unasked, because it cannot destroy
anything:

```powershell
git merge --ff-only '@{upstream}'
```

If `--ff-only` is refused, the clone was not really in that state — re-survey
rather than reaching for a stronger command.

## Step 4 — Memory commits are not "valuable local changes"

A `Stop` hook (`tools/sync_agent_memory.sh`) commits and pushes `agent-memory/`
at the end of every turn, and leaves the commit local whenever that push loses a
race. So a clone that is "ahead" very often carries nothing but automatic memory
commits.

Before asking the user anything, check what the local-only commits touch:

```powershell
git log --oneline --name-only '@{upstream}..HEAD'
```

Treat a commit as hook-produced when its subject begins
`chore(memory): sync agent memories from` **and** every file it touches is under
`agent-memory/`. Those never warrant a question:

- **Ahead only by memory commits** → rebase them onto the remote
  (`git rebase '@{upstream}'`) and report that they are still waiting to be
  pushed. Do not offer to discard them; they are the user's memories.
- **Uncommitted changes confined to `agent-memory/`** → stash, fast-forward, pop.
  The hook will commit them at the end of the turn as usual.

Only when real work is involved do you go to Step 5. Say plainly in the question
which commits are memory ones so the user is not asked to judge them.

## Step 5 — Local work present, so ask first

Never merge, rebase, reset or discard on your own judgment here. Summarize what
exists only in this clone — uncommitted files, and local commits with their
subjects — and ask with `AskUserQuestion`, offering:

- **Rebase onto the remote** (recommended when the local commits are the user's
  own work): replays them on top, keeping history linear.
- **Merge the remote in**: keeps both sides with a merge commit.
- **Set the changes aside**: stash the uncommitted work, fast-forward, then pop
  it back and report any conflict. This is the safe answer when the user is
  unsure.
- **Discard the local changes**: reset to the remote, under the rules in Step 6.

Include enough detail in the question for the user to choose: how many commits,
how many files, and whether anything looks like work in progress rather than a
finished change.

If the answer is ambiguous, ask again rather than guessing. A wrong guess here
destroys work.

## Step 6 — What "discard" is allowed to destroy

Only after the user has explicitly chosen to discard:

```powershell
git reset --hard '@{upstream}'
```

Hard limits on that step:

- **Never run `git clean -x` or `-X`.** The ignored trees hold each component's
  virtual environments and frozen builds — gigabytes of them — and losing them
  costs a full rebuild of every component, not a download.
- **Leave untracked files alone by default.** Run `git clean -nd` and show the
  list; delete with `git clean -fd` only if the user asks for that too, after
  seeing what it would remove.
- **Say what was destroyed** in the report, including the commit hashes, so the
  user can recover them from the reflog if they change their mind.

## Step 7 — Pushing is a separate approval

Integrating local commits does not put them on the other machine; only a push
does. When the clone is left ahead of the remote after a rebase or merge, say so
and offer to push — but do not push until the user approves it in that turn.
This matches the repository's standing rule in the `arcrho-commit-workflow` skill.

The one exception is `agent-memory/`, which its own hook pushes unattended.

## Step 8 — Report what the switch means for this machine

Close with anything the pull changed that the user has to act on:

- **Rebuilt components.** Pulling source does not rebuild anything. If the
  update touched a component's sources, the deployed apps are now stale and need
  `server-components/deploy.py`.
- **Environments and builds are not in git.** A clone that has never built has no
  `server-components/venvs` or `server-components/builds`, so its first deploy is
  much slower than usual.
- **The memory junction.** Memories reach the agent through a junction created by
  `tools/link_agent_memory.ps1`. A clone that has never had it set up will not
  pick up pulled memories until that script has been run once.

Keep the report short: the state before, what was done, and what is left for the
user to decide.
