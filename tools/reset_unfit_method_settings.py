#!/usr/bin/env python3
"""Reset method settings that were made for a project's old data and no longer fit the new.

After a project's data is replaced (fake_project_refresh.md, step 8), some
hand-made choices stop making sense and some stop a method from refreshing
at all. This tool resets them, saving every method through its hosted save
so the dependent walk runs:

- **Exclusions on empty cells.** A DFM whose refresh is refused with
  "previously excluded ratio cells" (named in a walk report written by
  ``tools/recalculate_project_methods.py --out``) has every ratio exclusion
  cleared.
- **Deleted candidates.** A Result Selection candidate whose dataset no longer
  exists is removed, and the origins it carried move to the selection's
  first DFM candidate (or its first remaining one).
- **Hand-typed factors.** A DFM development column whose selected factor is a
  hand-typed User Entry more than 25% away from the column's default average
  ("Volume - all", else the first calculated average) selects that average;
  a column the new data has no ratio in keeps its typed factor.
- **Unselected columns.** A development column with ratios but no selected row
  selects the default average, which Arco already computes it from; without a
  row the Export macro leaves ResQ's old selection in place.
- **Tails.** A Curves-tab tail taken from a column whose tail is outside
  1.0-1.5 goes back to the Ratios tab's own tail.

Usage
-----
    py -3.10 tools/reset_unfit_method_settings.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake --walks walks.json --dry-run
    py -3.10 tools/reset_unfit_method_settings.py --root ... --project ... --walks walks.json   # saves through the Gateway
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from arcrho_api.dfm_curves import curves_table  # noqa: E402

EXCLUSION_REASON = "previously excluded ratio cells"
DEFAULT_AVERAGE = "Volume - all"
USER_ENTRY_BAND = (0.8, 1.25)
TAIL_BAND = (1.0, 1.5)


@dataclass
class Reset:
    reserving_class: str
    kind: str  # "DFM" or "RS"
    name: str
    method: dict[str, Any]
    changes: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else float(value)
    except (TypeError, ValueError):
        return None


def excluded_dfms(walks: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(class, DFM name) of every refusal for exclusions on cells that are now empty."""

    found = set()
    for outcome in walks:
        message = str(outcome.get("message") or "")
        for match in re.finditer(r"(?:^|; |: )([^;:]+?): 422: DFM input values are missing for previously excluded", message):
            found.add((str(outcome["reserving_class"]).casefold(), match.group(1).strip()))
    return found


def clear_exclusions(method: dict[str, Any]) -> bool:
    ratio = (method.get("ratios_tab") or {}).get("ratio_triangle") or {}
    excluded = ratio.get("excluded") or []
    if not any(any(row) for row in excluded):
        return False
    ratio["excluded"] = [[0] * len(row) for row in excluded]
    return True


def default_average_row(formulas: dict[str, Any]) -> int | None:
    labels = formulas.get("label") or []
    types = (formulas.get("custom_average_formula_settings") or {}).get("average_type") or []
    if DEFAULT_AVERAGE in labels:
        return labels.index(DEFAULT_AVERAGE)
    return next((i for i, kind in enumerate(types) if kind == "custom"), None)


def reset_user_entries(method: dict[str, Any]) -> list[str]:
    """Select the default average where a hand-typed factor is far from it; returns the columns moved."""

    formulas = (method.get("ratios_tab") or {}).get("average_formulas") or {}
    labels = formulas.get("label") or []
    types = (formulas.get("custom_average_formula_settings") or {}).get("average_type") or []
    selected, values, inputs = formulas.get("selected") or [], formulas.get("values") or [], formulas.get("inputs") or []
    default = default_average_row(formulas)
    if default is None:
        return []
    ratios = ((method.get("ratios_tab") or {}).get("ratio_triangle") or {}).get("ratio_values") or []
    moved = []
    width = max((len(row) for row in selected), default=0)
    # The last column is the tail ("- Ult"); the Curves tab rule covers it.
    for column in range(max(0, width - 1)):
        row = next((i for i, flags in enumerate(selected) if column < len(flags) and flags[column]), None)
        if row is None or row == default or row >= len(types) or types[row] != "user_entry":
            continue
        if column < len(inputs[row]) and str(inputs[row][column] or "").strip():
            continue  # a formula, not a typed figure
        if not any(column < len(cells) and _number(cells[column]) is not None for cells in ratios):
            continue  # the data has no ratio here, so its average says nothing
        typed = _number(values[row][column]) if column < len(values[row]) else None
        average = _number(values[default][column]) if column < len(values[default]) else None
        if typed is None or not average or USER_ENTRY_BAND[0] <= typed / average <= USER_ENTRY_BAND[1]:
            continue
        selected[row][column] = 0
        selected[default][column] = 1
        moved.append(f"{column + 1}: {labels[row]} {typed:.4g} -> {labels[default]} {average:.4g}")
    return moved


def select_unselected(method: dict[str, Any]) -> list[str]:
    """Select the default average in a column that has ratios but no selected row; returns the columns.

    Arco already computes such a column from the default average, but the export
    sends no selection for it, so ResQ keeps whatever row it had selected before.
    """

    formulas = (method.get("ratios_tab") or {}).get("average_formulas") or {}
    selected = formulas.get("selected") or []
    default = default_average_row(formulas)
    if default is None or default >= len(selected):
        return []
    ratios = ((method.get("ratios_tab") or {}).get("ratio_triangle") or {}).get("ratio_values") or []
    width = max((len(row) for row in selected), default=0)
    moved = []
    for column in range(max(0, width - 1)):
        if any(column < len(flags) and flags[column] for flags in selected):
            continue
        if not any(column < len(cells) and _number(cells[column]) is not None for cells in ratios):
            continue
        selected[default][column] = 1
        moved.append(f"{column + 1}: no row -> {formulas['label'][default]}")
    return moved


def reset_tail(method: dict[str, Any]) -> str:
    curves = method.get("curves_tab") or {}
    if not curves or int(curves.get("selected_tail_factor") or 1) == 1:
        return ""
    chain = [_number(value) for value in curves.get("selected_values") or []]
    if len(chain) < 2:
        return ""
    formulas = (method.get("ratios_tab") or {}).get("average_formulas") or {}
    selected, values = formulas.get("selected") or [], formulas.get("values") or []
    last = len(chain) - 1
    row = next((i for i, flags in enumerate(selected) if last < len(flags) and flags[last]), None)
    ratios_tail = _number(values[row][last]) if row is not None and last < len(values[row]) else 1.0
    table = curves_table(chain[:-1], ratios_tail or 1.0, curves)
    tail = table.get("selected_tail") if isinstance(table, dict) else None
    tail = _number(tail) if tail is not None else chain[-1]
    if tail is not None and TAIL_BAND[0] <= tail <= TAIL_BAND[1]:
        return ""
    curves["selected_tail_factor"] = 1
    return f"tail {tail} -> Ratios tab tail {ratios_tail}"


def _key(name: Any) -> str:
    # ResQ type names may carry doubled spaces the methods do not (memory resq-double-space-type-names).
    return " ".join(str(name or "").split()).casefold()


def drop_missing_candidates(method: dict[str, Any], existing: set[str]) -> list[str]:
    tab = method.get("method_tab") or {}
    loaded = tab.get("loaded_datasets") or []
    gone = [item for item in loaded if _key(item.get("name")) not in existing]
    if not gone:
        return []
    kept = [item for item in loaded if item not in gone]
    heir = next((item for item in kept if item.get("method_type") == "DFM"), kept[0] if kept else None)
    if heir is not None:
        for item in gone:
            for index, weight in enumerate(item.get("weights") or []):
                if weight and index < len(heir.get("weights") or []):
                    heir["weights"][index] = (heir["weights"][index] or 0) + weight
    tab["loaded_datasets"] = kept
    return [f"dropped {item['name']}" + (f", weights to {heir['name']}" if heir else "") for item in gone]


PARTS = ("refusals", "selections")


def plan_project(project_dir: Path, walks: list[dict[str, Any]], parts: tuple[str, ...] = PARTS) -> list[Reset]:
    """``refusals``: exclusions and deleted candidates; ``selections``: typed factors and tails."""

    excluded = excluded_dfms(walks)
    plan: list[Reset] = []
    for folder in sorted((project_dir / "data").iterdir()):
        index_path = folder / "index.json"
        if not index_path.exists() or not (folder / "methods").is_dir():
            continue
        reserving_class = str(_read_json(index_path)["reserving_class"])
        existing = {_key(_read_json(path).get("dataset_name")) for path in (folder / "sidecars").glob("*.json")}
        for path in sorted((folder / "methods").glob("*.json")):
            kind = path.stem.split("@", 1)[0]
            if kind not in ("DFM", "RS"):
                continue
            method = _read_json(path)
            name = str((method.get("details_tab") or {}).get("name") or "")
            reset = Reset(reserving_class, kind, name, copy.deepcopy(method))
            if kind == "DFM":
                if "refusals" in parts and (reserving_class.casefold(), name) in excluded and clear_exclusions(reset.method):
                    reset.changes.append("cleared exclusions")
                if "selections" in parts:
                    reset.changes += [f"column {text}" for text in reset_user_entries(reset.method)]
                    reset.changes += [f"column {text}" for text in select_unselected(reset.method)]
                    tail = reset_tail(reset.method)
                    if tail:
                        reset.changes.append(tail)
            elif "refusals" in parts:
                reset.changes += drop_missing_candidates(reset.method, existing)
            if reset.changes:
                plan.append(reset)
    return plan


def _wait_for_class(gateway: Any, project: str, reserving_class: str, timeout: float = 900.0) -> None:
    deadline = time.time() + timeout
    while gateway.read("propagation_busy", project_name=project, reserving_class=reserving_class).get("busy"):
        if time.time() > deadline:
            raise TimeoutError(f"{reserving_class} is still busy after {timeout:.0f}s")
        time.sleep(2)


SAVE_KINDS = {"DFM": "dfm_method", "RS": "result_selection_method"}


def run_saves(plan: list[Reset], project: str) -> int:
    from arcrho_api.gateway import GatewayClient

    gateway = GatewayClient()
    print(f"saving as {gateway.user} through {gateway.url}")
    failures = 0
    for item in plan:
        _wait_for_class(gateway, project, item.reserving_class)
        try:
            result = gateway.save(SAVE_KINDS[item.kind], project, item.reserving_class, item.method)
        except Exception as err:  # report and carry on with the next method
            failures += 1
            print(f"FAIL {item.reserving_class} | {item.name}: {err}")
            continue
        propagation = (result or {}).get("calculated_updates") or (result or {}).get("propagation") or {}
        ok = propagation.get("ok", True)
        print(f"{'ok  ' if ok else 'WALK'} {item.reserving_class} | {item.name}: {'; '.join(item.changes)}"
              + ("" if ok else f" walk: {str(propagation.get('message') or propagation.get('reason'))[:300]}"))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="server root holding projects\\<project>")
    parser.add_argument("--project", required=True)
    parser.add_argument("--walks", default="", help="walk report from recalculate_project_methods.py --out")
    parser.add_argument("--part", choices=PARTS, action="append", help="reset only this part (repeatable); default both")
    parser.add_argument("--dry-run", action="store_true", help="print the plan; reads files only")
    args = parser.parse_args(argv)
    project_dir = Path(args.root) / "projects" / args.project
    walks = json.loads(Path(args.walks).read_text(encoding="utf-8")) if args.walks else []
    plan = plan_project(project_dir, walks, tuple(args.part or PARTS))
    for item in plan:
        print(f"plan {item.reserving_class} | {item.name}: {'; '.join(item.changes)}")
    print(f"{len(plan)} methods to reset")
    if args.dry_run:
        return 0
    if os.environ.get("ARCRHO_SERVER_ROOT", "").rstrip("\\/").casefold() != str(Path(args.root)).rstrip("\\/").casefold():
        print("ARCRHO_SERVER_ROOT does not name --root; refusing to save.")
        return 2
    return 1 if run_saves(plan, args.project) else 0


if __name__ == "__main__":
    raise SystemExit(main())
