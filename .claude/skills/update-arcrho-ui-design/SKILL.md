---
name: update-arcrho-ui-design
description: Update the ArcRho UI Design skill after a completed and user-tested ArcRho frontend UI fix. Use only after the user says a specific UI bug fix or visual consistency decision is finished/tested and asks to add, record, codify, document, or turn that fix into durable ArcRho UI design guidance.
---

# Update ArcRho UI Design

## Purpose

Convert a completed, user-tested ArcRho UI fix into concise, reusable guidance in `.claude/skills/arcrho-ui-design/SKILL.md` so future UI work repeats the improved pattern.

## Workflow

1. Confirm the user is asking to document a specific UI fix that is already completed and tested by the user. If the fix is still being designed, implemented, or validated, do not use this skill yet.
2. Read the current request and recent implementation context. Identify the durable design principle behind the verified fix, not just the specific bug.
3. Read `frontend/FRONTEND_AGENT_GUIDELINES.md` and `.claude/skills/arcrho-ui-design/SKILL.md` before editing.
4. Check the requested lesson against the current ArcRho UI Design rules before making changes:
   - If the requested lesson is already covered, explicitly tell the user which existing rule covers it and do not edit unless the user asks for a wording refinement.
   - If the requested lesson conflicts with an existing rule, explicitly name both the requested lesson and the conflicting rule, explain the conflict, and ask for clarification before editing.
   - If the requested lesson partially overlaps an existing rule, say what is already covered and what narrower addition would be new before editing.
5. Choose the narrowest existing section in the ArcRho UI Design skill:
   - Use **Controls And States** for buttons, inputs, dropdowns, toggles, pickers, menus, chips, focus, hover, selected, disabled, and keyboard state rules.
   - Use **Layout System** for spacing, page frame, tabbed page, panel, and responsive layout rules.
   - Use **Typography** for label weight, casing, text scale, and fit rules.
   - Use **Table Design Rules** only for table-specific behavior.
   - Use **What To Avoid** for prohibitions that apply broadly.
6. Write one compact future-facing bullet or sentence that names the reusable pattern and expected visual behavior. Keep it app-design-specific and avoid implementation details unless they are essential.
7. Do not overfit to a single page. Mention a page only when the rule is intentionally page-specific.
8. Add or update an unreleased fragment when repository rules require it.
9. Check the edited skill still opens with valid frontmatter: a `name` that matches its folder name and a one-line `description` that says when to use it.
10. Run the frontend docs workflow from the repo root: `py -3.10 frontend/tools/docs_index_builder.py --write`, then `py -3.10 frontend/tools/docs_index_builder.py --check`. If a release fragment changed, also run `py -3.10 frontend/build/release/release_notes.py check`.

## Rule Writing Style

- Prefer direct bullets that match the existing design guide tone.
- Use "should" for expectations and "must" only for hard constraints.
- Include the opened state for controls that reveal UI, such as dropdown menus and popovers.
- Name visible states: rest, hover, selected, disabled, focus, keyboard navigation, and sizing, when relevant.
- Keep examples short; the skill is the rulebook, not the implementation diary.
