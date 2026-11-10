"""The lists the Excel add-in offers while a formula is being written.

The Insert Function panel, Select Datasets, and Load Reserving Classes all pick
from the same three lists: the registered projects, one project's reserving
classes, and that project's dataset types. They are answered by one hosted
read, so Excel pays a single round trip for all three and keeps them for the
session. Each list keeps its existing owner; this module only gathers them.
The answer also names the latest project, which Connect and Login offers as a
new workbook's default project.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app_server.services import (
    calculated_dataset_service,
    dataset_types_service,
    project_settings_service,
)

# The dataset-type columns a picker shows. The formulas and sources the full
# table carries stay on the server.
DATASET_TYPE_COLUMNS = ("Name", "Data Format", "Category")


def _dataset_type_rows(project_name: str) -> List[List[Any]]:
    table = dataset_types_service.load_dataset_types_data(project_name)
    columns = list(table.get("columns") or [])
    positions = [columns.index(name) for name in DATASET_TYPE_COLUMNS]
    return [[row[i] for i in positions] for row in table.get("rows") or []]


def _latest_project(projects: List[str]) -> str:
    """The project with the latest Development End Date.

    Among projects sharing that date the one registered first wins, because a
    Subchannel, allocation, or backup copy is registered after its original.
    """

    latest, latest_end = "", 0
    for name in projects:
        end = str(project_settings_service.get_general_settings(name)["data"]["development_end_date"])
        if end.isdigit() and int(end) > latest_end:
            latest, latest_end = name, int(end)
    return latest


def list_formula_choices(project_name: str = "") -> Dict[str, Any]:
    folders = {item["name"]: item["folder"] for item in project_settings_service._read_project_index()["projects"]}
    projects = list(folders)
    names = sorted(projects, key=str.casefold)
    payload: Dict[str, Any] = {
        "ok": True,
        "projects": names,
        # Each project's folder in the project tree, in the order of "projects".
        "project_folders": [folders[name] for name in names],
        "latest_project": _latest_project(projects),
        "project_name": "",
        "reserving_classes": [],
        "dataset_types": {"columns": list(DATASET_TYPE_COLUMNS), "rows": []},
    }
    name = str(project_name or "").strip()
    if name:
        payload["project_name"] = name
        payload["reserving_classes"] = calculated_dataset_service.project_reserving_classes(name)
        payload["dataset_types"]["rows"] = _dataset_type_rows(name)
    return payload
