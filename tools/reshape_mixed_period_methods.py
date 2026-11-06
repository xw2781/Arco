#!/usr/bin/env python3
"""Move each method that reads another method at a different origin length onto that method's length.

A Cape Cod or DFM refuses a method-output precedent stored at another origin
length, and a Result Selection refuses a candidate coarser than itself (a finer
one is read from the candidate's own coarser copy). ResQ rolls the finer method
up; Arco does not, so the method is moved to its precedent's length instead
(fake_project_refresh.md, step 13). Every change goes through the app's own
saves, so the dependent walk runs:

- **Result Selection.** Saved with the new (annual) origin length and labels,
  each candidate's weights averaged over the quarters of each year; the save
  of a review-needed selection re-reads every candidate and ratio basis at
  that length. A selection that is not review-needed is left for a person.
- **Cape Cod and DFM.** Their saves keep a stored method's origin labels
  (Cape Cod) or triangle (DFM) when only the length changes, and a DFM refresh
  refuses a triangle whose development steps differ, so the method is deleted
  (the Project Instance delete) and saved again as a new method, which reads
  every source at the new length. A Cape Cod keeps its settings. A DFM takes
  its ratio-basis DFM's average-formula rows, which sit at those lengths, and
  selects in every column the row its old selection used most; hand-typed
  factors, exclusions and Curves-tab choices start fresh. Only a method that
  nothing reads is moved this way.

Re-planning after each pass picks up what a move exposes (a selection that
reads the one just moved).

Usage
-----
    py -3.10 tools/reshape_mixed_period_methods.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake --dry-run
    py -3.10 tools/reshape_mixed_period_methods.py --root ... --project ...   # saves through the Gateway
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

METHOD_OUTPUT_KINDS = {"dfm", "cape_cod", "bornhuetter_ferguson", "result_selection"}
MOVABLE = {"dfm": "DFM", "cape_cod": "CC", "result_selection": "RS"}
REVIEW_NEEDED = 2


@dataclass
class Move:
    reserving_class: str
    folder: Path
    kind: str  # "DFM", "CC" or "RS"
    name: str
    length: int
    target: int
    precedent: str


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _key(name: Any) -> str:
    return " ".join(str(name or "").split()).casefold()


def _length(sidecar: dict[str, Any]) -> int:
    return int(sidecar.get("period_length") or 12)


def class_sidecars(folder: Path) -> dict[str, dict[str, Any]]:
    return {_key(s.get("dataset_name")): s for s in map(_read_json, (folder / "sidecars").glob("*.json"))}


def conflicts(sidecars: dict[str, dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(method sidecar, precedent sidecar) for every method-output precedent the method cannot read."""

    found = []
    for sidecar in sidecars.values():
        kind = str(sidecar.get("source_kind") or "")
        if kind not in MOVABLE:
            continue
        for item in sidecar.get("precedents") or []:
            if (item or {}).get("reserving_class"):
                continue  # another class's method keeps its own length
            precedent = sidecars.get(_key((item or {}).get("dataset_name")))
            if not precedent or str(precedent.get("source_kind") or "") not in METHOD_OUTPUT_KINDS:
                continue
            own, theirs = _length(sidecar), _length(precedent)
            if own == theirs or (kind == "result_selection" and theirs < own):
                continue
            found.append((sidecar, precedent))
    return found


def plan_project(project_dir: Path) -> list[Move]:
    moves = []
    for folder in sorted((project_dir / "data").iterdir()):
        index_path = folder / "index.json"
        if not index_path.exists() or not (folder / "sidecars").is_dir():
            continue
        reserving_class = str(_read_json(index_path)["reserving_class"])
        seen: set[str] = set()
        for sidecar, precedent in conflicts(class_sidecars(folder)):
            name = str(sidecar["dataset_name"])
            if _key(name) in seen:
                continue
            seen.add(_key(name))
            moves.append(Move(reserving_class, folder, MOVABLE[str(sidecar["source_kind"])], name,
                              _length(sidecar), _length(precedent), str(precedent["dataset_name"])))
    return moves


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


def _method_file(folder: Path, prefix: str, name: str) -> Path:
    for path in (folder / "methods").glob(f"{prefix}@*.json"):
        if _key((_read_json(path).get("details_tab") or {}).get("name")) == _key(name):
            return path
    raise FileNotFoundError(f"{prefix} method {name!r} not found in {folder.name}")


def regroup_weights(weights: list[Any], old_labels: list[str], new_labels: list[str]) -> list[float]:
    """Annual weights: the mean of the finer origins' weights inside each year."""

    if any(" " in str(label) for label in new_labels):
        raise ValueError("only a move to annual origins is supported")
    out = []
    for label in new_labels:
        inside = [float(w or 0) for old, w in zip(old_labels, weights) if str(old).split()[0] == str(label)]
        out.append(sum(inside) / len(inside) if inside else 0.0)
    return out


def result_selection_payload(method: dict[str, Any], target: int, labels: list[str]) -> dict[str, Any]:
    payload = copy.deepcopy(method)
    tab = payload["method_tab"]
    old = [str(x) for x in tab.get("origin_labels") or []]
    payload["details_tab"]["origin_length"] = target
    tab["origin_labels"] = list(labels)
    blank = [None] * len(labels)
    for source in tab.get("loaded_datasets") or []:
        source["weights"] = regroup_weights(source.get("weights") or [], old, labels)
        source["values"] = list(blank)
    for basis in tab.get("ratio_basis_values") or []:
        basis["values"] = list(blank)
    for key in ("calculated_ultimate", "selected_ultimate", "ultimate_overrides"):
        tab[key] = list(blank)
    return payload


def predominant_row(formulas: dict[str, Any]) -> int | None:
    """The calculated average the old selection used in most development columns."""

    types = (formulas.get("custom_average_formula_settings") or {}).get("average_type") or []
    counts: Counter[int] = Counter()
    for row, flags in enumerate(formulas.get("selected") or []):
        if row < len(types) and types[row] == "custom":
            counts[row] += sum(1 for flag in flags if flag)
    return counts.most_common(1)[0][0] if counts else None


def new_dfm_payload(old: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """A new DFM at the template's lengths with the template's average rows and the old method's choice."""

    old_formulas = old["ratios_tab"]["average_formulas"]
    rows = template["ratios_tab"]["average_formulas"]
    row = predominant_row(old_formulas)
    if row is None or row >= len(rows["label"]):
        row = rows["label"].index("Volume - all") if "Volume - all" in rows["label"] else 0
    width = max((len(flags) for flags in rows.get("selected") or []), default=0)
    details = dict(old["details_tab"])
    details["origin_length"] = template["details_tab"]["origin_length"]
    details["development_length"] = template["details_tab"]["development_length"]
    types = rows["custom_average_formula_settings"]["average_type"]
    return {
        "json_format": old["json_format"],
        "details_tab": details,
        # A new DFM reads its sources on these axes, as the page's new DFM does.
        "data_tab": {
            "origin_labels": list(template["data_tab"]["origin_labels"]),
            "development_labels": list(template["data_tab"]["development_labels"]),
        },
        "ratios_tab": {
            "average_formulas": {
                "label": list(rows["label"]),
                "custom_average_formula_settings": copy.deepcopy(rows["custom_average_formula_settings"]),
                "selected": [[1 if r == row else 0] * width for r in range(len(rows["label"]))],
                # Formula rows keep their formula; typed factors belong to the old geometry.
                "inputs": [list(rows["inputs"][r]) if types[r] == "user_entry" else [""] * width
                           for r in range(len(rows["label"]))],
            },
        },
        "results_tab": {
            "ratio_basis_dataset": old["results_tab"].get("ratio_basis_dataset") or "",
            "ultimate_ratio_decimal_places": old["results_tab"].get("ultimate_ratio_decimal_places", 2),
        },
    }


def new_cape_cod_payload(old: dict[str, Any], target: int, labels: list[str]) -> dict[str, Any]:
    """A new Cape Cod at ``target`` months with the old settings; every per-origin column is reloaded."""

    payload = {key: copy.deepcopy(old[key]) for key in ("json_format", "details_tab", "method_tab")}
    payload["details_tab"]["origin_length"] = target
    tab = payload["method_tab"]
    rows = len(tab.get("origin_labels") or [])
    for key, value in list(tab.items()):
        if isinstance(value, list) and len(value) == rows:
            tab[key] = []
        elif key.endswith("_source_revision"):
            tab[key] = ""
    tab["origin_labels"] = list(labels)
    return payload


# ---------------------------------------------------------------------------
# Saves
# ---------------------------------------------------------------------------


def _wait_for_class(gateway: Any, project: str, reserving_class: str, timeout: float = 900.0) -> None:
    deadline = time.time() + timeout
    while gateway.read("propagation_busy", project_name=project, reserving_class=reserving_class).get("busy"):
        if time.time() > deadline:
            raise TimeoutError(f"{reserving_class} is still busy after {timeout:.0f}s")
        time.sleep(2)


def apply_move(gateway: Any, project: str, move: Move) -> str:
    sidecars = class_sidecars(move.folder)
    sidecar = sidecars[_key(move.name)]
    labels = [str(x) for x in sidecars[_key(move.precedent)].get("origin_labels") or []]
    if move.kind == "RS":
        if int(sidecar.get("status") or 0) != REVIEW_NEEDED:
            return "skipped: not review-needed, so its save would trust the values sent"
        method = _read_json(_method_file(move.folder, "RS", move.name))
        result = gateway.save("result_selection_method", project, move.reserving_class,
                              result_selection_payload(method, move.target, labels),
                              notes=sidecar.get("notes") or "")
    else:
        # The Cape Cod and DFM saves keep a stored method's origin labels or
        # triangle when only its length changes, so the method is created anew.
        if sidecar.get("dependents"):
            return "skipped: other objects read this method"
        if move.kind == "CC":
            from arcrho_api.cape_cod_contract import normalize_cape_cod_method as check

            payload = new_cape_cod_payload(_read_json(_method_file(move.folder, "CC", move.name)), move.target, labels)
            kind = "cape_cod_method"
        else:
            from arcrho_api.dfm_contract import normalize_dfm_method as check

            template = _read_json(_method_file(move.folder, "DFM", move.precedent))
            payload = new_dfm_payload(_read_json(_method_file(move.folder, "DFM", move.name)), template)
            kind = "dfm_method"
        check(payload, require_complete=False)  # refuse here, before anything is deleted
        gateway.mutate("cached_dataset_delete", project_name=project,
                       reserving_class=move.reserving_class, dataset_names=[move.name])
        _wait_for_class(gateway, project, move.reserving_class)
        result = gateway.save(kind, project, move.reserving_class, payload, notes=sidecar.get("notes"))
    propagation = (result or {}).get("calculated_updates") or (result or {}).get("propagation") or {}
    return "ok" if propagation.get("ok", True) else f"walk: {str(propagation.get('message'))[:300]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="server root holding projects\\<project>")
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the plan; reads files only")
    parser.add_argument("--passes", type=int, default=3, help="re-plan after each pass, at most this often")
    args = parser.parse_args(argv)
    project_dir = Path(args.root) / "projects" / args.project
    gateway = None
    failures = 0
    for number in range(1, args.passes + 1):
        plan = plan_project(project_dir)
        for move in plan:
            print(f"plan {move.reserving_class} | {move.kind} {move.name}: {move.length} -> {move.target} months"
                  f" (reads {move.precedent})")
        if args.dry_run or not plan:
            break
        if gateway is None:
            if os.environ.get("ARCRHO_SERVER_ROOT", "").rstrip("\\/").casefold() \
                    != str(Path(args.root)).rstrip("\\/").casefold():
                print("ARCRHO_SERVER_ROOT does not name --root; refusing to save.")
                return 2
            from arcrho_api.gateway import GatewayClient

            gateway = GatewayClient()
            print(f"saving as {gateway.user} through {gateway.url}")
        moved = 0
        for move in plan:
            _wait_for_class(gateway, args.project, move.reserving_class)
            try:
                outcome = apply_move(gateway, args.project, move)
            except Exception as err:  # report and carry on with the next method
                failures += 1
                outcome = f"FAIL {err}"
            moved += outcome.startswith("ok") or outcome.startswith("walk")
            print(f"pass {number} {move.reserving_class} | {move.name}: {outcome}", flush=True)
        if not moved:
            break
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
