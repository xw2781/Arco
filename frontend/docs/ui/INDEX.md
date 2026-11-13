# Frontend Index

## Purpose
<!-- MANUAL:BEGIN -->
Frontend module map for page entrypoints, shell orchestration, and feature-specific scripts.
<!-- MANUAL:END -->

## Entry Points
<!-- AUTO-GEN:BEGIN frontend.index.entry_points -->
| HTML Entrypoint | External Scripts | Inline Imports |
| --- | --- | --- |
| `ui/index.html` | 2 external scripts | - |
| `ui/file_explorer/file_explorer.html` | 2 external scripts | - |
| `ui/server/server.html` | 2 external scripts | - |
| `ui/dashboard/dashboard.html` | 2 external scripts | - |
| `ui/dataset_viewer/dataset_viewer.html` | 2 external scripts | 1 inline import |
| `ui/method_pages/dfm/dfm.html` | 2 external scripts | 4 inline imports |
| `ui/method_pages/bornhuetter_ferguson/bornhuetter_ferguson.html` | 3 external scripts | - |
| `ui/method_pages/cape_cod/cape_cod.html` | 3 external scripts | - |
| `ui/method_pages/bootstrap/bootstrap.html` | 3 external scripts | - |
| `ui/method_pages/stochastic_consolidation/stochastic_consolidation.html` | 3 external scripts | - |
| `ui/method_pages/berquist_sherman/berquist_sherman.html` | 3 external scripts | - |
| `ui/method_pages/result_selection/result_selection.html` | 7 external scripts | - |
| `ui/workflow/workflow.html` | 2 external scripts | - |
| `ui/project_settings/project_settings.html` | 2 external scripts | - |
| `ui/project_instance/project_instance.html` | 2 external scripts | - |
| `ui/arcode/main.html` | 2 external scripts | - |
| `ui/arcode/notebook-editor/index.html` | 14 external scripts | - |
| `ui/arcode/code-editor/index.html` | 5 external scripts | - |
<!-- AUTO-GEN:END -->

## Key Files
<!-- AUTO-GEN:BEGIN frontend.index.key_files -->
- [`docs/ui/shell.md`](shell.md) - Shell tab host index.
- [`docs/ui/file_explorer.md`](file_explorer.md) - File Explorer feature index.
- [`docs/ui/server.md`](server.md) - Server tab index.
- [`docs/ui/dataset.md`](dataset.md) - Dataset feature index.
- [`docs/ui/dfm.md`](dfm.md) - DFM feature index.
- [`docs/ui/bornhuetter_ferguson.md`](bornhuetter_ferguson.md) - Bornhuetter Ferguson method-page index.
- [`docs/ui/cape_cod.md`](cape_cod.md) - Cape Cod method-page index.
- [`docs/ui/bootstrap.md`](bootstrap.md) - Bootstrap method-page index.
- [`docs/ui/stochastic_consolidation.md`](stochastic_consolidation.md) - Stochastic Consolidation method-page index.
- [`docs/ui/berquist_sherman.md`](berquist_sherman.md) - Berquist Sherman method-page index.
- [`docs/ui/result_selection.md`](result_selection.md) - Result Selection method-page index.
- [`docs/ui/workflow.md`](workflow.md) - Workflow feature index.
- [`docs/ui/project_settings.md`](project_settings.md) - Project settings feature index.
- [`docs/ui/arcode.md`](arcode.md) - Arcode scripting workspace feature index.
- [`docs/ui/ai_assistant.md`](ai_assistant.md) - Shared ArcBot assistant widget index.
<!-- AUTO-GEN:END -->

## Non-Negotiable Contracts
<!-- MANUAL:BEGIN -->
Mandatory before frontend behavior changes:
1. [`../contracts/frontend_behavior_contract.md`](../contracts/frontend_behavior_contract.md)
2. [`../contracts/business_logic_contract.md`](../contracts/business_logic_contract.md)
3. [`../architecture/architecture_guardrails.md`](../architecture/architecture_guardrails.md)

High-risk files that must follow contracts:
- `ui/shell/ui_shell.js`
- `ui/workflow/workflow_main.js`
- `ui/dataset_viewer/dataset_viewer.html`, `ui/dataset_viewer/*`, and `ui/shared/tabs/data/*`
- `ui/method_pages/dfm/dfm.html` and `ui/method_pages/dfm/dfm_*.js`
- `ui/method_pages/bornhuetter_ferguson/*` and `ui/method_pages/result_selection/*`
- `ui/project_settings/project_settings.js`
- `ui/arcode/main.js`, `ui/arcode/main.html`, `ui/arcode/notebook-editor/*`, `ui/arcode/code-editor/*`, and `ui/arcode/shared/editor_shared.js`
- `ui/ai-assistant/*`
<!-- MANUAL:END -->

## Design References
<!-- MANUAL:BEGIN -->
- [`ArcRho UI Design skill`](../../../.claude/skills/arcrho-ui-design/SKILL.md) - Atlas-based global UI design reference for future ArcRho interface work.
- [`global_app_ui_demo.html`](global_app_ui_demo.html) - Standalone UI style demo with Workbench, Atlas, and Assistant Studio concepts.
<!-- MANUAL:END -->

## External Interfaces
<!-- MANUAL:BEGIN -->
- App-server HTTP interface via `fetch(...)` calls.
- Cross-iframe messaging via `window.postMessage` (`arcrho:*` message types).
<!-- MANUAL:END -->

## Data/State/Caches
<!-- MANUAL:BEGIN -->
- Shell/tab state persisted in browser storage (`localStorage`, IndexedDB handles DB).
- Per-page state lives in each iframe module.
<!-- MANUAL:END -->

## Common Change Tasks
<!-- MANUAL:BEGIN -->
1. Shell tab lifecycle change -> [`shell.md`](shell.md).
2. Dataset behavior change -> [`dataset.md`](dataset.md).
3. DFM behavior change -> [`dfm.md`](dfm.md).
4. Result Selection method change -> [`result_selection.md`](result_selection.md).
5. Workflow editor change -> [`workflow.md`](workflow.md).
6. Project settings flow change -> [`project_settings.md`](project_settings.md).
7. Arcode scripting app or notebook/editor change -> [`arcode.md`](arcode.md).
8. Shared ArcBot widget change -> [`ai_assistant.md`](ai_assistant.md).
<!-- MANUAL:END -->

## Known Risks
<!-- MANUAL:BEGIN -->
- Shell/iframe messaging changes can break hotkeys and dirty-state sync.
- Endpoint path changes in JS can silently break page-level features.
- Arcode is the canonical scripting UI; keep ArcRho shell launch and macro edit flows coordinated with Arcode window/file-opening behavior.
<!-- MANUAL:END -->
