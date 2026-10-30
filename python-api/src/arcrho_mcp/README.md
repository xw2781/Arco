# Arco MCP server

Agents read Arco projects and preview method edits through these tools. Every read goes through the Arco Gateway under the Gateway credential of the user running the server. Previews recalculate in memory. Nothing saves.

Design and later steps: [docs/plans/arco_mcp_server.md](../../../docs/plans/arco_mcp_server.md).

## Tools

| Tool | Does |
| :--- | :--- |
| `arco_catalog` | Lists the read kinds `arco_read` accepts |
| `arco_read` | Runs one read from that list and returns its full payload |
| `list_projects`, `list_reserving_classes`, `list_methods` | Discovery |
| `get_dfm_summary` | Selected average and LDF per development, tail, excluded ratios, ultimate per origin |
| `get_result_selection` | Method values, weights, override and selected ultimate per origin |
| `preview_dfm_edit` | Excludes or includes ratio cells, or selects an existing average, then returns the changed LDFs and ultimates |
| `preview_result_selection_weights` | Sets source weights, then returns the selected ultimate per origin before and after |

Edits name origins, developments, averages and sources by label, exactly as the summaries return them. An unknown label is refused.

The read list in `reads.py` is shared with ArcBot. Change it there, not in ArcBot.

## Setup

The server needs Python 3.10 or later, the Arco Gateway credential that Arco writes when it enrols the user, and the MCP SDK:

```
py -3.10 -m pip install "mcp>=2.3,<3"
```

Claude Code in this repository picks it up from `.mcp.json` at the repository root. Other agents run the same command with `python-api/src` on `PYTHONPATH`. For example, Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.arco]
command = "py"
args = ["-3.10", "-m", "arcrho_mcp"]
env = { PYTHONPATH = 'E:\XWSpace\Repos\ArcRho\python-api\src' }
```

To run as a separate agent user, set `ARCRHO_GATEWAY_CONFIG` in the server's `env` to that user's Gateway credential file.
