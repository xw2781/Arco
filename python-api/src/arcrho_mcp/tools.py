"""Arco agent tools: every read goes through the Gateway, every preview runs in memory.

Each tool takes a ``gateway`` with the ``read`` method of
``arcrho_api.gateway.GatewayClient``. Nothing here saves. Edits name cells and
rows by label; a label the freshly loaded method does not hold is refused, never
guessed, so an agent cannot aim an edit at the wrong cell.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from arcrho_api.dataset_index_contract import METHOD_TYPE_NONE
from arcrho_api.dfm_contract import preview_dfm_method
from arcrho_api.result_selection_contract import recalculate_result_selection

from .reads import agent_read_catalog, agent_read_spec

DFM_EDIT_OPERATIONS = ("exclude", "include", "select_average")


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _index(labels: list[Any], wanted: str, what: str) -> int:
    key = _text(wanted).casefold()
    for index, label in enumerate(labels):
        if _text(label).casefold() == key:
            return index
    raise ValueError(f"No {what} labelled {wanted!r}; the method has: {', '.join(_text(label) for label in labels)}")


def _total(values: list[Any]) -> float:
    return sum(float(value) for value in values if isinstance(value, (int, float)))


# Discovery and reads


def arco_catalog() -> dict[str, Any]:
    return agent_read_catalog()


def arco_read(gateway, kind: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
    agent_read_spec(kind)
    return gateway.read(kind, **dict(arguments or {}))


def list_projects(gateway) -> list[str]:
    return gateway.read("project_names")["projects"]


def list_reserving_classes(gateway, project_name: str) -> list[str]:
    return gateway.read("reserving_classes_with_data", project_name=project_name)["reserving_classes"]


def list_methods(gateway, project_name: str, reserving_class: str) -> list[dict[str, str]]:
    index = gateway.read("dataset_index", project_name=project_name, reserving_class=reserving_class)
    return [
        {"method_name": row.get("method_name") or row["name"], "method_type": row["method_type"]}
        for row in index.get("files", [])
        if _text(row.get("method_type")) not in ("", METHOD_TYPE_NONE)
    ]


# DFM


def _load_dfm(gateway, project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
    return gateway.read(
        "dfm_method_load", project_name=project_name, reserving_class=reserving_class, method_name=method_name,
    )


def dfm_summary(method: Mapping[str, Any]) -> dict[str, Any]:
    """Selected averages, LDFs, exclusions and ultimates of one DFM payload, by label."""

    origins = list(method["data_tab"]["origin_labels"])
    ratio = method["ratios_tab"]["ratio_triangle"]
    developments = list(ratio["development_labels"])
    formulas = method["ratios_tab"]["average_formulas"]
    averages = list(formulas["label"])
    selected_values = list(method["curves_tab"].get("selected_values") or [])
    columns = []
    for col, development in enumerate(developments):
        row = next((r for r, flags in enumerate(formulas["selected"]) if col < len(flags) and flags[col] == 1), None)
        columns.append({
            "development": development,
            "selected_average": averages[row] if row is not None else "",
            "selected_ratio": formulas["values"][row][col] if row is not None else None,
            "ldf": selected_values[col] if col < len(selected_values) else None,
        })
    ultimates = list(method["results_tab"]["ultimate_vector"])
    return {
        "averages": averages,
        "developments": columns,
        "tail": selected_values[len(developments)] if len(selected_values) > len(developments) else None,
        "excluded": [
            {"origin": origins[r], "development": developments[c]}
            for r, flags in enumerate(ratio["excluded"])
            for c, flag in enumerate(flags)
            if flag == 1
        ],
        "ultimates": [{"origin": origin, "ultimate": ultimates[r] if r < len(ultimates) else None}
                      for r, origin in enumerate(origins)],
        "total_ultimate": _total(ultimates),
    }


def get_dfm_summary(gateway, project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
    loaded = _load_dfm(gateway, project_name, reserving_class, method_name)
    return {"method_name": method_name, "method_revision": loaded["method_revision"], **dfm_summary(loaded["method"])}


def apply_dfm_edit(method: Mapping[str, Any], edit: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of ``method`` with the label-based edit applied, not yet recalculated."""

    unknown = sorted(set(edit) - set(DFM_EDIT_OPERATIONS))
    if unknown:
        raise ValueError(f"Unknown DFM edit operation: {', '.join(unknown)}")
    edited = deepcopy(dict(method))
    origins = edited["data_tab"]["origin_labels"]
    ratio = edited["ratios_tab"]["ratio_triangle"]
    developments = ratio["development_labels"]
    for operation, flag in (("exclude", 1), ("include", 0)):
        for cell in edit.get(operation) or []:
            row = _index(origins, cell["origin"], "origin")
            col = _index(developments, cell["development"], "development")
            if col >= len(ratio["excluded"][row]):
                raise ValueError(f"No ratio at origin {cell['origin']!r}, development {cell['development']!r}")
            ratio["excluded"][row][col] = flag
    formulas = edited["ratios_tab"]["average_formulas"]
    for choice in edit.get("select_average") or []:
        col = _index(developments, choice["development"], "development")
        chosen = _index(formulas["label"], choice["average"], "average")
        for row, flags in enumerate(formulas["selected"]):
            flags[col] = 1 if row == chosen else 0
    return edited


def preview_dfm_edit(
    gateway, project_name: str, reserving_class: str, method_name: str, edit: Mapping[str, Any],
) -> dict[str, Any]:
    """Recalculate a freshly loaded DFM with ``edit`` applied, beside the current results."""

    loaded = _load_dfm(gateway, project_name, reserving_class, method_name)
    before = dfm_summary(loaded["method"])
    after = dfm_summary(preview_dfm_method(apply_dfm_edit(loaded["method"], edit)))
    return {
        "method_name": method_name,
        "method_revision": loaded["method_revision"],
        "developments": [
            {"development": old["development"],
             "before": {"selected_average": old["selected_average"], "ldf": old["ldf"]},
             "after": {"selected_average": new["selected_average"], "ldf": new["ldf"]}}
            for old, new in zip(before["developments"], after["developments"])
            if old != new
        ],
        "tail": {"before": before["tail"], "after": after["tail"]},
        "excluded": after["excluded"],
        "ultimates": _ultimate_changes(before["ultimates"], after["ultimates"]),
        "total_ultimate": {"before": before["total_ultimate"], "after": after["total_ultimate"]},
    }


def _ultimate_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes = []
    for old, new in zip(before, after):
        delta = (new["ultimate"] - old["ultimate"]
                 if isinstance(old["ultimate"], (int, float)) and isinstance(new["ultimate"], (int, float)) else None)
        changes.append({"origin": old["origin"], "before": old["ultimate"], "after": new["ultimate"], "change": delta})
    return changes


# Result Selection


def _load_result_selection(gateway, project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
    return gateway.read(
        "result_selection_load", project_name=project_name, reserving_class=reserving_class, method_name=method_name,
    )


def result_selection_summary(method: Mapping[str, Any]) -> dict[str, Any]:
    """Weights, method values and selected ultimate per origin of one Result Selection payload."""

    tab = method["method_tab"]
    sources = tab["loaded_datasets"]
    rows = []
    for r, origin in enumerate(tab["origin_labels"]):
        rows.append({
            "origin": origin,
            "values": {source["name"]: source["values"][r] for source in sources},
            "weights": {source["name"]: source["weights"][r] for source in sources},
            "override": tab["ultimate_overrides"][r],
            "selected_ultimate": tab["selected_ultimate"][r],
        })
    return {
        "sources": [source["name"] for source in sources],
        "origins": rows,
        "total_selected_ultimate": _total(tab["selected_ultimate"]),
    }


def get_result_selection(gateway, project_name: str, reserving_class: str, method_name: str) -> dict[str, Any]:
    loaded = _load_result_selection(gateway, project_name, reserving_class, method_name)
    return {
        "method_name": method_name,
        "method_revision": loaded["method_revision"],
        **result_selection_summary(loaded["method"]),
    }


def apply_weight_changes(method: Mapping[str, Any], changes: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a recalculated copy of ``method`` with the weights set; a change naming no origin sets every origin."""

    edited = deepcopy(dict(method))
    tab = edited["method_tab"]
    sources = tab["loaded_datasets"]
    names = [source["name"] for source in sources]
    for change in changes:
        source = sources[_index(names, change["source"], "source")]
        weight = float(change["weight"])
        if weight < 0:
            raise ValueError(f"Weight for {change['source']!r} must not be negative")
        origin = _text(change.get("origin"))
        rows = [_index(tab["origin_labels"], origin, "origin")] if origin else range(len(tab["origin_labels"]))
        for row in rows:
            source["weights"][row] = weight
    recalculate_result_selection(edited)
    return edited


def preview_result_selection_weights(
    gateway, project_name: str, reserving_class: str, method_name: str, changes: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Recalculate a freshly loaded Result Selection with new weights, beside the current selection."""

    loaded = _load_result_selection(gateway, project_name, reserving_class, method_name)
    before = result_selection_summary(loaded["method"])
    after = result_selection_summary(apply_weight_changes(loaded["method"], changes))
    return {
        "method_name": method_name,
        "method_revision": loaded["method_revision"],
        "origins": [
            {"origin": old["origin"], "weights": new["weights"],
             "before": old["selected_ultimate"], "after": new["selected_ultimate"],
             "change": (new["selected_ultimate"] - old["selected_ultimate"]
                        if old["selected_ultimate"] is not None and new["selected_ultimate"] is not None else None)}
            for old, new in zip(before["origins"], after["origins"])
        ],
        "total_selected_ultimate": {
            "before": before["total_selected_ultimate"], "after": after["total_selected_ultimate"],
        },
    }
