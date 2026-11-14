# Frontend Agent Guidelines

This file defines mandatory guardrails for any code agent working in this repository.
  
## Mandatory Read Before Editing
Before changing frontend, app-server API behavior, or runtime architecture, read:
1. `docs/contracts/frontend_behavior_contract.md`
2. `docs/contracts/business_logic_contract.md`
3. `docs/architecture/architecture_guardrails.md`

These contracts are mandatory whenever a task touches:
- Frontend shell or feature entry/coordinator files under `ui/` (for example shell, dataset, workflow, DFM, or project settings).
- App-server API, service, or runtime config files under `app_server/api/`, `app_server/services/`, or `app_server/config.py`.
- Electron runtime bridge/host files under `electron/`.

## UI Design Reference
Before any frontend UI work — a new window, table, layout, or styling task, or a UI fix or visual/control change — use the `arcrho-ui-design` skill and apply its rules during implementation. Do not edit that skill unless the user explicitly asks to record, update, or codify a durable design rule; use the `update-arcrho-ui-design` skill for that.

## Hard Rules (MUST)
1. Keep `arcrho:*` message names backward-compatible unless all producers/consumers are updated in the same change.
2. Preserve tab dirty-state semantics and close-confirmation behavior.
3. Keep workflow save/load payload compatibility unless explicitly approved to break.
4. Keep router -> service -> config/schema layering; do not move business logic into routers.
5. Any behavior/logic/architecture change must update the corresponding MANUAL doc sections in the same change.
6. Any meaningful user-facing feature, fix, improvement, or breaking change must add a release fragment under `changes/unreleased/` with a short user-facing summary.

## Release Fragment Schema
Before adding or editing a release fragment, read `changes/README.md` and keep the fragment valid for `python build/release/release_notes.py check`.

Required JSON fields:
- `type`: one of `feature`, `improvement`, `fix`, or `breaking`
- `scope`: short area name such as `workflow`, `dataset`, `dfm`, `project settings`, or `build`
- `audience`: `user` or `internal`
- `summary`: one short sentence

Optional field:
- `details`: array of short supporting strings

Do not use obsolete fields or values such as `category`, `areas`, `type: "fixed"`, or `type: "changed"`. Use `type: "fix"` for fixes and `type: "improvement"` for changed behavior that is not a bug fix.

## Required Documentation Workflow
After relevant code changes:
1. Update contract docs (or explicitly state "no contract impact").
2. Keep index docs concise. Put feature-specific behavior notes in the relevant module doc under `docs/ui/`, `docs/app_server/domains/`, or `docs/runtime/`; do not paste long changelog/spec text into `INDEX.md` files.
3. When a plan has both `.md` and `.html` versions, treat the `.md` file as the source of truth. Update the Markdown first, then mirror material user-facing changes into the HTML companion.
4. Run `python tools/docs_index_builder.py --write`.
5. Run `python tools/docs_index_builder.py --check`.
6. If `--check` fails, fix docs before finishing.

## Commit and Push Workflow
When the user asks an agent to commit and/or push frontend code, use the `arcrho-commit-workflow` skill.

Frontend-specific additions:
1. Use `-Pathspec frontend` or a comma-list such as `-Pathspec frontend,tools` when intentionally limiting commit scope.
2. Use `-StageMode none` only when intentionally committing already staged changes.
3. The compatibility wrapper at `frontend/tools/agent_commit_push.ps1` delegates to the same root helper, but prefer running the root helper from `ArcRho/`.

## CSS Rules
Apply the root `AGENT_GUIDELINES.md` single-source-of-truth rule to styling: CSS rules and CSS custom properties own static visual defaults. Do not duplicate those defaults in JavaScript or write them as inline styles during initialization. JavaScript may set a visual CSS property only when the value is dynamically computed from runtime state or when a caller explicitly supplies an override; omitted override options must leave the stylesheet value untouched.
For sticky table headers inside scroll wrappers, keep header seam/bleed-through fixes out of layout flow. Do not add spacer or mask pseudo-elements on the scroll wrapper that create height, margin, or padding. Prefer `border-collapse: separate; border-spacing: 0;` for sticky-header tables and put any paint-only cover on the sticky `th` cells themselves, such as an absolutely positioned `th::before`, so body content cannot show through without creating a visible gap above the header.

## Change Safety
Before modifying code, stop and ask when the request is unclear or missing important implementation details, or when it conflicts with existing code logic, contracts, or architecture. Call out the concern, ask a targeted question or propose a better option, and proceed only after the user confirms the direction.

If a requested change appears to violate these contracts:
1. Stop and call out the exact contract rule.
2. Propose compliant alternatives.
3. Proceed only after explicit user confirmation for intentional exception.
