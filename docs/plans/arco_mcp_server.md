# Arco MCP Server

Status: Design proposed 2026-10-23. MVP of step 2 built 2026-10-30; see [MVP](#mvp-2026-10-30).

## Goal

Any agent (Claude Code, Codex, Claude Desktop, an ArcBot turn, a scheduled cloud routine) and any enrolled user can read and edit Arco projects through one set of tool calls, without a clone of this repository, a local Python 3.10, or a path to `python-api/src`.

## Why now: what a study needs today

The `Reserve Ranges - High` study (`Documents\Agent Projects\Reserve Ranges - High`) reaches Arco through the repository in four ways:

| Need | How the study does it today | Problem |
| :--- | :--- | :--- |
| Read and save methods | `arcrho_api.gateway.GatewayClient` imported from the clone | Needs the clone and Python 3.10 on every agent machine |
| Recalculate a DFM before saving | `arcrho_api.dfm_contract.preview_dfm_method`, run locally | Calculation code runs on the client, at whatever version the clone has |
| Compare High with the regular project, dry runs | `make_report.py`, `dryrun.py`, `ue_check.py`, `pd_dry.py` open method JSON on `E:\ArcRho Server\projects` | Reads project data over SMB, against [Server-Hosted Project Data I/O](../../AGENT_GUIDELINES.md#server-hosted-project-data-io-must) |
| Import a ResQ class | `import_resq_reserving_class.create_import_request` from `python-api/macros`, then `wait_for_import_result`, which polls status files under the server root | Polls the share directly for the result |

The only thing stopping a save to the wrong project is an `assert` in the study's own `gw.py`. The Gateway authenticates a user but does not limit which projects or method types that user may change.

ArcBot already serves tools to the Claude CLI as a per-turn MCP server (`frontend/electron/arcbot_claude_cli.js`, `arcbot_project_read.js`), with a read tool generated from `WORKSPACE_READ_KINDS`. That is the pattern to grow, not a second one to build beside.

## Recommendation

One tool layer, owned in `python-api`, served two ways.

1. **The tool layer** is a new package, `python-api/src/arcrho_mcp/`. It defines every tool once: its name, input schema, scope it needs, and the Gateway reads, mutations and saves it calls. Generic tools are generated from `WORKSPACE_READ_KINDS`, `WORKSPACE_MUTATION_KINDS` and `SAVE_JOB_KINDS`, so a new registered read becomes a tool with no MCP change.
2. **Hosted first-class transport: the Gateway serves `/mcp`** (Streamable HTTP) on the Server PC. The tools run beside the data, so there is no SMB, no client Python, and one deploy updates every agent. This is the target.
3. **Local stdio transport** (`python -m arcrho_mcp`, also frozen to `arco_mcp.exe` and published to `E:\ArcRho Server\shared\tools`) runs the same tools through the caller's own `GatewayClient` credential. It ships first because it needs no Gateway change, and it stays for desktop agents afterwards.

ArcBot's per-turn tools then become a filtered view of the same layer (read-only, skill-scoped), so `arcbot_project_read.js` stops carrying its own Python policy script.

### Why not the alternatives

- **Stdio only** still needs Python and the package on each machine, and cloud agents cannot reach it.
- **One MCP tool per registry kind, exposed raw** gives an agent 60 reads and whole-method JSON round trips. That costs context and invites a malformed save. Task tools with small structured edits are safer.
- **A separate MCP service** beside the Gateway duplicates its auth, audit, locks and deploy. The Gateway already owns all four.

## Tools

### Discovery and reads (scope `read`)

| Tool | Does |
| :--- | :--- |
| `arco_catalog` | Lists read kinds and their arguments (as ArcBot's `kind=catalog`) |
| `arco_read` | Runs any registered read kind |
| `list_projects`, `list_reserving_classes`, `list_methods` | Discovery, compact |
| `get_dfm_summary` | Selected averages, exclusions, LDFs and ultimates per column, from `DfmMethod.agent_summary` |
| `get_result_selection` | Weights, method values and selected ultimate per origin |
| `compare_methods` | One reserving class in two projects: what changed per method, ultimate deltas. Replaces the study's share reads |

### Previews (scope `read`, never saves)

| Tool | Does |
| :--- | :--- |
| `preview_dfm_edit` | Applies a structured edit to a freshly loaded DFM and returns the recalculated averages and ultimates beside the current ones |
| `preview_result_selection_weights` | Same for Result Selection weights |

### Edits (scope `edit`)

| Tool | Does |
| :--- | :--- |
| `apply_dfm_edit` | Same edit as the preview; loads, edits, saves with the loaded revision, waits for the dependent walk, returns before and after |
| `set_result_selection_weights` | Same for Result Selection |
| `wait_for_dependents` | Polls `propagation_busy` until the class is idle |
| `import_resq_class` | Publishes the import request and waits on a hosted status read |

A structured edit names cells and rows by label, never by index or whole JSON:

```json
{"exclude": [{"origin": "2019", "development": "12-24"}],
 "include": [],
 "select_average": [{"development": "12-24", "average": "Vol Wtd 5"}]}
```

The server resolves labels against the method it just loaded, so an agent cannot save a stale or hand-edited payload. Study rules (which ratio to drop, "higher LDFs") stay in the study's scripts or skill; the server offers the operations, not the judgement.

### Prompts and resources

- Each team skill under `E:\ArcRho Server\shared\agent-skills` (already read by `agent_skills`) is offered as an MCP prompt, so the same skill reaches ArcBot and outside agents.
- Large payloads (a full triangle, a method JSON) are MCP resources an agent opens on request; tools return the compact summary first.

## Safety and identity

- **One Gateway user per agent identity**, as the study's `Claude Sonnet` already is, so the audit log names who changed what.
- **Scopes live on the server, not in a client `assert`.** Each agent credential carries an allowlist: read-only by default; `edit` names the projects and the method types it may save (the High study: one project, DFM and Result Selection only). The Gateway checks it on every save and mutation, for MCP and for any other caller using that credential.
- **Hosted auth.** MCP clients send a fixed header rather than signing each request, so the Gateway issues a per-agent bearer token (hashed at rest, revocable from Admin Control, mapped to a Gateway user and its scopes). The stdio transport keeps the existing HMAC signing.
- **Edits are optimistic:** every save sends the revision it loaded and fails on a conflict rather than overwriting.
- Every call is logged with the tool name and user, under the 30-day log rule.

## Gaps to close in the Gateway first

1. **`dfm_method_preview` read kind**: runs `preview_dfm_method` on the server, so no client needs `arcrho_api` to calculate.
2. **`reserving_class_methods` read kind**: lists method names and types in a class; today the study lists the methods folder on the share.
3. **`resq_import_status` read kind**: the import result the macro's `wait_for_import_result` reads from status files today.
4. **Per-credential scopes** checked on save and mutation.

## Steps

| # | Step | Needs |
| :--- | :--- | :--- |
| 1 | Add the three read kinds above, with tests | Bridge, Engine, Gateway deploy |
| 2 | `arcrho_mcp` tool layer and stdio transport; read and preview tools only | `mcp` Python SDK |
| 3 | Edit tools with label-based edits, revision check, dependent wait | Step 1 |
| 4 | Per-credential scopes in the Gateway | Gateway deploy |
| 5 | Port the High study onto the MCP tools; drop its clone imports and share reads | Steps 2-4 |
| 6 | Gateway `/mcp` route with bearer tokens, issued from Admin Control | Step 4 |
| 7 | ArcBot uses the shared layer; skills offered as MCP prompts | Step 6 |
| 8 | Frozen `arco_mcp.exe` published to the shared tools folder, plus a one-page setup guide for agents | Step 2 |

Step 5 is the acceptance test: the study runs a segment end to end with no repository on the agent's machine.

## MVP (2026-10-30)

Step 2, built as [python-api/src/arcrho_mcp](../../python-api/src/arcrho_mcp/README.md) and registered for Claude Code in the repository's `.mcp.json`. Decisions taken for it:

- **Scope:** reads and previews only, over stdio. `compare_methods` is not in it.
- **Previews calculate in the MCP process.** The DFM preview calls `preview_dfm_method`; the Result Selection preview calls `arcrho_api.result_selection_contract`, which the app server's Result Selection service now imports too. The `dfm_method_preview` read kind waits for the hosted `/mcp` step.
- **Methods are listed from the class index** (`dataset_index` rows carry the method type), so the `reserving_class_methods` read kind is not needed.
- **`arco_read` takes a curated list**, `arcrho_mcp/reads.py`, which ArcBot's read tool also imports. This settles the first open decision.
- **DFM edits are `exclude`, `include` and `select_average` only.** Labels must match exactly; an unknown label or a new average is refused.
- **The MCP SDK is the optional `mcp` extra (2.x).** `reads.py` and `tools.py` do not import it, so ArcBot and the app wheel stay dependency-free.
- **Identity:** the server uses the running user's Gateway credential; `ARCRHO_GATEWAY_CONFIG` points it at an agent user's credential instead.

## Open decisions

- Whether outside agents may call `arco_read` with any read kind, or only a curated list as ArcBot does today.
- Who may issue an `edit` token, and whether a token expires.
- Whether cloud agents (outside the corporate network) are in scope; that would need TLS on the Gateway, which [hosted_save_http_transport.md](hosted_save_http_transport.md) already lists as remaining.
