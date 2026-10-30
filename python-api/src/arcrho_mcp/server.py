"""The Arco MCP server over stdio: the tools in ``arcrho_mcp.tools``, signed with this user's Gateway credential."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from typing_extensions import NotRequired, TypedDict

from arcrho_api.exceptions import ArcRhoApiError
from arcrho_api.gateway import GatewayClient

from . import tools

INSTRUCTIONS = (
    "Read Arco projects and preview method edits through the Arco Gateway, as the user whose credential "
    "this server runs with. Nothing here saves. Start with list_projects, list_reserving_classes and "
    "list_methods; name origins, developments, averages and sources by their labels exactly as the "
    "summaries return them."
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


class RatioCell(TypedDict):
    origin: str
    development: str


class AverageChoice(TypedDict):
    development: str
    average: str


class DfmEdit(TypedDict):
    exclude: NotRequired[list[RatioCell]]
    include: NotRequired[list[RatioCell]]
    select_average: NotRequired[list[AverageChoice]]


class WeightChange(TypedDict):
    source: str
    weight: float
    origin: NotRequired[str]


@lru_cache(maxsize=1)
def _gateway() -> GatewayClient:
    return GatewayClient()


def build_server(gateway=None) -> MCPServer:
    """The server with every tool registered; ``gateway`` replaces this user's client in tests."""

    def run(tool, *args):
        # A refused label or a Gateway refusal is the agent's to read and correct,
        # so its text reaches the client; anything else stays a hidden crash.
        try:
            return tool(gateway if gateway is not None else _gateway(), *args)
        except (ValueError, ArcRhoApiError) as err:
            raise ToolError(str(err)) from err

    server = MCPServer("arco", instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def arco_catalog() -> dict[str, Any]:
        """List the read kinds arco_read accepts, with their required and optional arguments."""
        return tools.arco_catalog()

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def arco_read(kind: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one Gateway read from arco_catalog, such as dfm_method_load, with its arguments. Returns the full payload; prefer the summary tools."""
        return run(tools.arco_read, kind, arguments)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def list_projects() -> dict[str, Any]:
        """List the Arco project names on the server."""
        return {"projects": run(tools.list_projects)}

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def list_reserving_classes(project_name: str) -> dict[str, Any]:
        """List the reserving classes of a project that hold data."""
        return {"reserving_classes": run(tools.list_reserving_classes, project_name)}

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def list_methods(project_name: str, reserving_class: str) -> dict[str, Any]:
        """List the methods in a reserving class with their method types."""
        return {"methods": run(tools.list_methods, project_name, reserving_class)}

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def get_dfm_summary(project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
        """Summarize a DFM: selected average and LDF per development, tail, excluded ratios, ultimate per origin."""
        return run(tools.get_dfm_summary, project_name, reserving_class, method_name)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def get_result_selection(project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
        """Summarize a Result Selection: method values, weights, override and selected ultimate per origin."""
        return run(tools.get_result_selection, project_name, reserving_class, method_name)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def preview_dfm_edit(project_name: str, reserving_class: str, method_name: str, edit: DfmEdit) -> dict[str, Any]:
        """Preview a DFM edit without saving: exclude or include ratio cells, or select an existing average per development.

        Returns the changed developments and every origin's ultimate before and after. Labels must match the
        method exactly; an unknown label is refused.
        """
        return run(tools.preview_dfm_edit, project_name, reserving_class, method_name, edit)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def preview_result_selection_weights(
        project_name: str, reserving_class: str, method_name: str, changes: list[WeightChange],
    ) -> dict[str, Any]:
        """Preview new Result Selection weights without saving. A change without an origin sets that source's weight for every origin."""
        return run(tools.preview_result_selection_weights, project_name, reserving_class, method_name, changes)

    return server


def main() -> None:
    build_server().run("stdio")
