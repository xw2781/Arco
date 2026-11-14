---
name: arcrho-plan-breakdown
description: Restructure an ArcRho plan document into steps that one agent context (one session or one subagent) can finish end to end, put a plain-language progress checklist at the top that the executing agents keep current, and run the finished plan with one subagent per step. Use when the user asks to break a plan into sessions or session-sized steps, add a progress checklist or progress tracking to a plan, make a plan agent-executable, prepare a plan doc for implementation, or run, execute, or work through a plan that carries the Progress table (unattended or step by step).
---

# ArcRho Plan Breakdown

## Purpose

A plan doc in `docs/plans/` or `frontend/docs/plans/` is written for two readers: the user, who wants to see progress without reading code, and the agent that will execute one step in one fresh context. This skill produces a plan that serves both, tells an executing agent how to keep the progress record current, and describes how the whole plan is run unattended with one subagent per step.

## When invoked to restructure a plan

1. Read the whole plan, the repo instructions (`AGENT_GUIDELINES.md`, `docs/plans/README.md`), and enough of the code the plan cites to judge each step's real size. Do not change the plan's decisions; if a decision is missing, record it under an "Open decisions" section with a recommended answer rather than choosing silently.
2. Keep every section the plan already has that explains *why* (the question, the investigation, the measurements, the decisions). Agents read those before starting a step. Only the "Plan" section is restructured.
3. Split the work into steps that each fit one context. A step fits when all of these hold:
   - One goal a user could describe in one sentence.
   - One commit. Nothing in the step depends on a decision that is still open, because a subagent cannot ask the user anything.
   - The files it touches are listable by name and fit in roughly a dozen; a step that touches every producer of a contract, or every reader of a field, is its own step.
   - Its tests are part of the step, not a later one.
   - It crosses at most one component boundary (app server, frontend, Engine, Bridge, Gateway, tools). A change that needs the same contract on several components becomes "contract and producers", then "readers", then "backfill" as separate steps.
   - A deploy is always its own final step.
   Order the steps so each one's inputs already exist, and say which steps are independent.
4. Write each step with this template, using the plan's own headings style:
   - `### Step N — <title>`
   - **Goal.** One or two sentences.
   - **Read first.** The sections of the plan and the code ranges the agent must read, as links; skills or memory notes that apply. Nothing more, so the session stays small.
   - **Do.** A checkbox list of the concrete changes.
   - **Tests.** Which test files gain what.
   - **Done when.** An observable condition, not "the code is written".
5. Put the Progress table and the "How agents work this plan" section at the top, directly under the `Status:` and `Last updated:` lines, using the formats below.
6. Update the `Status:` line, `Last updated:`, and the plan's row in `docs/plans/README.md` (or the frontend plans index) to say the plan is broken into N session-sized steps and where implementation stands.

## The Progress table

Plain language only. No file names, function names, field names, endpoints or component names. Each row says what a user would notice when the step is done.

```markdown
## Progress

Plain-language tracking. The agent that finishes a step ticks its box, fills in the date, and leaves one short line on what a user would notice. Nothing technical goes here.

| # | Step | Done | Date | What changed for the user |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Coarser views of a hand-entered triangle add up correctly | [ ] | | |
| 2 | Every dataset records the shape its data is really stored at | [ ] | | |

Overall: 0 of N steps done.
```

- A ticked row reads `[x]`, the date is `YYYY-MM-DD`, and the last cell is one sentence in the same plain register as the step title.
- A step that was skipped or dropped is not ticked; its last cell says "Dropped: <one plain reason>" and the Overall line counts it out of the total.
- A step that is started but not finished stays unticked; the last cell may say "In progress" with the date, and is replaced when the step lands.

## The "How agents work this plan" section

Include it verbatim, adjusting only the file links:

```markdown
## How agents work this plan

- Take the first unticked step in the Progress table. One step is one context (a session or one subagent), one commit.
- Read the sections between here and the Plan before starting, then only the files the step names. Do not read ahead into later steps.
- A step is done when its "Done when" list holds, its tests pass, and the commit is in. In that same commit: tick the Progress row, write the date and the one-line user note, update the "Overall" count, and update the `Status:` line at the top and this plan's row in the plans index.
- If a step turns out to need a decision that is not in "Open decisions", stop, record the question there, commit that note alone, and report it rather than guessing.
- Do not start a step while the previous one is uncommitted.
```

## When invoked while executing a step

- Before starting, confirm the previous row is ticked and the tree is clean of that step's work. If not, stop and report.
- Do the step as written. If the step's "Read first" list turns out to be insufficient, read what is needed, then add the missing item to that step's list in the same commit so the next reader benefits.
- On completion, in the same commit as the code: tick the row, date it, write the plain-language note, update the Overall line, the `Status:` line, `Last updated:`, and the plans-index row. Use the `arcrho-commit-workflow` skill for the commit; the user's request to run the plan is the authorization to commit each step.
- When the last step lands, move the plan to the `completed/` folder and update the plans index, as `docs/plans/README.md` describes.

## Running the whole plan unattended

The user runs a prepared plan unattended by asking to "run the plan" with subagents. That request is the authorization to spawn the subagents and for every per-step commit. The orchestrating session does this with the Agent tool:

1. Read the plan's Progress table and its "Plan" section only far enough to list the unticked steps, their order, and which are independent.
2. Launch one subagent per step, **in order**: start a step only after the previous step's subagent has reported back. Run two steps at the same time only when the plan says they are independent; never parallelise steps that touch the same files or the same contract.
3. Pass the `model` parameter on every launch, as `CLAUDE.md` requires: Opus for a step that writes real code, changes behaviour, or touches a persisted contract; Sonnet for a mechanical step such as a rename, a doc move, or a repeated edit. Never Fable unless the user asked for it in this conversation.
4. Each subagent's prompt is short and self-contained. It names the plan file and the step number, says to invoke this skill and follow the plan's "How agents work this plan" rules, and asks for a final report with: `status` (`done` or `blocked`), the commit hash, the plain-language note written into the Progress row, and for `blocked` the question recorded under "Open decisions".
5. After each step, check the report. On `done`, continue. On `blocked` or an error, stop and report what is known; do not start the next step, because it would build on an unfinished one.
6. Before the deploy step, stop and report unless the user's request explicitly included deploying. A deploy is outward-facing and stays a user decision.
7. When the run ends, re-read the Progress table from disk, confirm the ticks match the commits (`git log --oneline` since the run started), and report in plain language: steps done, the commit list, and any blocker with its question.

Keep one subagent per step; do not split a step across subagents.

## What not to do

- Do not put technical detail in the Progress table; the step sections hold it.
- Do not renumber steps once execution has started; append a new step instead and note where it fits.
- Do not merge steps to save sessions; a step that cannot be finished and tested in one context is split, not stretched.
- Do not tick a row for work that is not committed.
- Do not let a subagent guess at an open decision, push to the remote, or deploy; those stay with the user.
