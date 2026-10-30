"""The workspace reads an agent may run, shared by the MCP server and ArcBot.

The registry owns read kinds and their arguments; this list only picks the
ones useful to an agent: every method load, dataset loads, and the discovery
reads. Simulations, job statuses and UI-internal reads stay out. This module
imports nothing beyond the registry, so ArcBot's Python can use it without the
MCP library installed.
"""

from __future__ import annotations

from typing import Any

from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS, WorkspaceReadKind

_DISCOVERY_READS = frozenset({
    "project_names",
    "general_settings",
    "project_audit_log",
    "reserving_class_combinations",
    "reserving_classes_with_data",
    "dataset_index",
    "dataset_dependency_graph",
    "dataset_cache_load",
    "dataset_sidecar_load",
})


def _is_agent_read(name: str, spec: WorkspaceReadKind) -> bool:
    return name in _DISCOVERY_READS or (spec.function.startswith("load_") and "method_name" in spec.required)


AGENT_READ_KINDS: dict[str, WorkspaceReadKind] = {
    name: spec for name, spec in WORKSPACE_READ_KINDS.items() if _is_agent_read(name, spec)
}


def agent_read_catalog() -> dict[str, dict[str, Any]]:
    """Each agent read kind with its required and optional arguments."""

    return {name: {"required": spec.required, "optional": spec.optional} for name, spec in AGENT_READ_KINDS.items()}


def agent_read_spec(kind: str) -> WorkspaceReadKind:
    spec = AGENT_READ_KINDS.get(kind)
    if spec is None:
        raise ValueError(f"{kind!r} is not an agent read; agents may run method loads, dataset loads and discovery reads only")
    return spec
