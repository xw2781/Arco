#!/usr/bin/env python3
"""Put a project's ResQ-stored "Adjusted" / ad hoc triangles on the scale of its own data.

A ResQ import stores some triangles the Engine cannot rebuild (``source``
``resq_triangle``): "Net Loss--Incurred Adjusted*", "Net Loss - ad hoc" and
the like. When the source table is replaced (fake_project_refresh.md, step 6)
they keep the old figures while everything around them moves. This tool sets
each one to its base triangle times a small seeded factor per origin:

- the base is the type name without " Adjusted" and its stars
  ("Net Loss--Paid Adjusted*" -> "Net Loss--Paid"); an ad hoc type reads the
  incurred triangle ("Net Loss - ad hoc" -> "Net Loss--Incurred");
- the values are written at the shortest lengths the dataset's dependents use,
  because an Engine-kind ResQ triangle cannot be read at another length;
- a calculated triangle is skipped: its dependent walk rebuilds it.

Every write goes through the hosted dataset save, so the dependent walk runs.
Plan decision 7 turns Penn+CT MP+PIP "Net Loss--Incurred Adjusted*" into a
hand-entered triangle, which rolls up to the 12-month severity it feeds.

Usage
-----
    py -3.10 tools/rescale_resq_stored_triangles.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake --dry-run
    py -3.10 tools/rescale_resq_stored_triangles.py --root ... --project ...          # saves through the Gateway
    py -3.10 tools/rescale_resq_stored_triangles.py --root ... --project ... --check  # latest diagonal vs base
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from arcrho_api.paths import sanitize_file_name_part  # noqa: E402
from arcrho_api.period_reshape import origin_labels_for  # noqa: E402

DEFAULT_SEED = 20261106
DEVIATION = 0.05
CHECK_TOLERANCE = 0.10
LABEL_STYLES = {12: "year", 6: "half", 3: "quarter", 1: "month_name"}
# Plan decision 7: stored as a hand-entered triangle so it rolls up.
INPUT_KIND = {("PRNJ - PA\\PA\\Penn+CT\\Direct Group\\MP+PIP", "Net Loss--Incurred Adjusted*")}
# Step 8: hand-entered stores whose sidecar keeps ResQ's monthly development
# labels, which a DFM reads as they stand. Stored like the other ResQ
# triangles instead, they are read on the project's own development grid.
ENGINE_KIND = {
    ("PRNJ - PA\\PA\\NY\\Direct Group\\BI Total", "Net Loss--Incurred Adjusted*"),
    ("PRNJ - PA\\PA\\MA\\Direct Group\\BI Total", "Net Loss--Incurred Adjusted*"),
}


@dataclass
class Rescale:
    reserving_class: str
    dataset_name: str
    dataset_type: str
    base: str
    origin_length: int
    development_length: int
    source_kind: str
    reshape: bool
    values: list[list[float | None]] = field(default_factory=list)
    # A hand-entered store finer on the origin axis than its dependents keeps
    # its own rows: they are written back at the store, rescaled per origin.
    write_lengths: tuple[int, int] | None = None
    display_at: tuple[int, int] | None = None
    origin_labels: list[str] = field(default_factory=list)
    problem: str = ""


def base_dataset(dataset_type: str) -> str:
    adhoc = re.match(r"^(.*?)\s+-\s+ad hoc$", dataset_type)
    if adhoc:
        return f"{adhoc.group(1)}--Incurred"
    return re.sub(r"\s+Adjusted\**$", "", dataset_type)


def _number(cell: str) -> float | None:
    try:
        return float(cell)
    except ValueError:  # blank, or the error text a failed Engine build leaves in its file
        return None


def read_rows(path: Path) -> list[list[float | None]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [[_number(cell) for cell in record] for record in csv.reader(stream)]


def group_latest(rows: list[list[float | None]], groups: int) -> list[float]:
    """Latest total of each of ``groups`` equal runs of rows (finer origins summed into coarser ones)."""

    step = max(1, len(rows) // groups)
    return [latest_total(rows[index * step:(index + 1) * step]) for index in range(groups)]


def latest_total(rows: list[list[float | None]]) -> float:
    """Sum of each row's last non-zero figure (a scattered store holds zeros between ages)."""

    return sum(next((v for v in reversed(row) if v), 0.0) for row in rows)


def origin_factors(seed: int, reserving_class: str, dataset_name: str, count: int) -> list[float]:
    rng = random.Random(f"{seed}|{reserving_class}|{dataset_name}")
    return [1.0 + rng.uniform(-DEVIATION, DEVIATION) for _ in range(count)]


def scaled(rows: list[list[float | None]], factors: list[float]) -> list[list[float | None]]:
    return [[None if v is None else v * factor for v in row] for row, factor in zip(rows, factors)]


def rescaled_store(
    store: list[list[float | None]], base: list[list[float | None]], factors: list[float]
) -> list[list[float | None]] | None:
    """Scale each group of store rows so its latest figures add up to its base origin's, times its factor.

    A group that holds nothing stays empty: there is no old figure to rescale.
    """

    if not base or len(store) % len(base):
        return None
    step = len(store) // len(base)
    out: list[list[float | None]] = []
    for index, (row, factor) in enumerate(zip(base, factors)):
        group = store[index * step:(index + 1) * step]
        old, new = latest_total(group), latest_total([row]) * factor
        ratio = new / old if old else 0.0
        out.extend([[None if v is None else v * ratio for v in cells] for cells in group])
    return out


def project_origin_labels(project_dir: Path, length: int) -> list[str]:
    settings = json.loads((project_dir / "general_settings.json").read_text(encoding="utf-8"))

    def month(text: str) -> int:
        return int(text[:4]) * 12 + int(text[4:6]) - 1

    months = list(range(month(settings["origin_start_date"]), month(settings["origin_end_date"]) + 1, length))
    return origin_labels_for(months, LABEL_STYLES[length])


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dependent_lengths(class_dir: Path, sidecars: dict[str, dict], dependents: list[str]) -> list[tuple[int, int]]:
    methods: dict[str, dict] = {}
    methods_dir = class_dir / "methods"
    if methods_dir.is_dir():
        for path in methods_dir.glob("*.json"):
            method = _read_json(path)
            methods[str(method.get("details_tab", {}).get("name") or "")] = method
    lengths = []
    for name in dependents:
        if name in methods:
            tabs = {**methods[name].get("details_tab", {}), **methods[name].get("method_tab", {})}
            origin = int(tabs.get("origin_length") or 0)
            lengths.append((origin, int(tabs.get("development_length") or origin)))
        elif name in sidecars and sidecars[name].get("data_format") == "Triangle":
            lengths.append((int(sidecars[name]["origin_length"]), int(sidecars[name]["development_length"])))
    return [pair for pair in lengths if pair[0] > 0 and pair[1] > 0]


def plan_project(project_dir: Path, seed: int = DEFAULT_SEED) -> list[Rescale]:
    table = Path(_read_json(project_dir / "field_mapping.json")["table_path"])
    table_mtime = table.stat().st_mtime if table.exists() else 0.0
    plan: list[Rescale] = []
    for class_dir in sorted((project_dir / "data").iterdir()):
        sidecar_dir = class_dir / "sidecars"
        if not sidecar_dir.is_dir():
            continue
        sidecars = {}
        for path in sidecar_dir.glob("*.json"):
            sidecar = _read_json(path)
            sidecars[str(sidecar.get("dataset_name") or "")] = sidecar
        for name, sidecar in sorted(sidecars.items()):
            if sidecar.get("source") != "resq_triangle" or sidecar.get("calculated"):
                continue
            rc = str(sidecar["reserving_class"])
            dependents = [str(entry.get("dataset_name")) for entry in sidecar.get("dependents") or []]
            lengths = _dependent_lengths(class_dir, sidecars, dependents)
            if lengths:
                origin = min(pair[0] for pair in lengths)
                development = min(pair[1] for pair in lengths)
            else:
                origin = int(sidecar["origin_length"])
                development = int(sidecar["development_length"])
            source_kind = (
                "input" if (rc, name) in INPUT_KIND else "engine" if (rc, name) in ENGINE_KIND else str(sidecar["source_kind"])
            )
            stored_origin = int(sidecar.get("stored_origin_length") or origin)
            stored_development = int(sidecar.get("stored_development_length") or development)
            # A hand-entered store keeps a finer development axis (values are
            # scattered into it); anything else is rewritten at the new shape.
            reshape = stored_origin != origin or development % stored_development != 0
            if source_kind != "input":
                reshape = (stored_origin, stored_development) != (origin, development)
            # Moving a hand-entered store would take its ResQ development
            # labels with it, which a DFM reads as they stand; keep it instead.
            keep_store = source_kind == "input" and stored_origin < origin
            item = Rescale(rc, name, str(sidecar["dataset_type"]), base_dataset(str(sidecar["dataset_type"])),
                           origin, development, source_kind, reshape and not keep_store)
            base_file = class_dir / "datasets" / f"{sanitize_file_name_part(item.base, 'dataset')}@{origin}@{development}@cum@dev.csv"
            item.origin_labels = project_origin_labels(project_dir, origin)
            if not base_file.exists():
                item.problem = f"no {item.base} cache at {origin}x{development}"
            elif base_file.stat().st_mtime < table_mtime:
                item.problem = f"{base_file.name} is older than the source table"
            else:
                rows = read_rows(base_file)
                if len(rows) != len(item.origin_labels):
                    item.problem = f"{base_file.name} has {len(rows)} rows, expected {len(item.origin_labels)}"
                elif keep_store:
                    store = read_rows(class_dir / "datasets" / str(sidecar["csv_file"]))
                    values = rescaled_store(store, rows, origin_factors(seed, rc, name, len(rows)))
                    if values is None:
                        item.problem = f"{sidecar['csv_file']} cannot be rescaled per {origin}-month origin"
                    else:
                        item.values = values
                        item.write_lengths = (stored_origin, stored_development)
                        item.display_at = (int(sidecar["origin_length"]), int(sidecar["development_length"]))
                else:
                    item.values = scaled(rows, origin_factors(seed, rc, name, len(rows)))
            plan.append(item)
    return plan


def save_arguments(item: Rescale) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "dataset_type": item.dataset_type,
        "source_kind": item.source_kind,
        "data_format": "Triangle",
        "origin_length": (item.write_lengths or (item.origin_length,))[0],
        "development_length": (item.write_lengths or (0, item.development_length))[1],
        "cumulative": True,
        "values": [[0.0 if v is None else v for v in row] for row in item.values],
        "mask": [[v is not None for v in row] for row in item.values],
    }
    if item.display_at:
        kwargs["display_at"] = list(item.display_at)
    if item.reshape:
        kwargs["stored_values_cleared"] = True
        kwargs["origin_labels"] = item.origin_labels
    return kwargs


def _wait_for_class(gateway: Any, project: str, reserving_class: str, timeout: float = 900.0) -> None:
    deadline = time.time() + timeout
    while gateway.read("propagation_busy", project_name=project, reserving_class=reserving_class).get("busy"):
        if time.time() > deadline:
            raise TimeoutError(f"{reserving_class} is still busy after {timeout:.0f}s")
        time.sleep(2)


def run_saves(plan: list[Rescale], project: str) -> int:
    from arcrho_api.gateway import GatewayClient

    gateway = GatewayClient()
    print(f"saving as {gateway.user} through {gateway.url}")
    failures = 0
    for item in plan:
        if item.problem:
            continue
        _wait_for_class(gateway, project, item.reserving_class)
        try:
            result = gateway.save("dataset_sidecar", project, item.reserving_class, item.dataset_name, **save_arguments(item))
        except Exception as err:  # report and carry on with the next triangle
            failures += 1
            print(f"FAIL {item.reserving_class} | {item.dataset_name}: {err}")
            continue
        # The dataset save reports its walk under ``calculated_updates``.
        propagation = (result or {}).get("calculated_updates") or (result or {}).get("propagation") or {}
        ok = propagation.get("ok", True)
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'WALK'} {item.reserving_class} | {item.dataset_name}"
              f" {item.origin_length}x{item.development_length} walk={propagation.get('status')}"
              f" refreshed={len(propagation.get('refreshed_datasets') or [])}"
              + ("" if ok else f" message={propagation.get('message') or propagation.get('reason')}"))
    return failures


def check_project(project_dir: Path) -> int:
    """Compare each triangle's latest figures with its base's at the lengths its dependents read."""

    failures = 0
    for item in plan_project(project_dir):
        class_dir = project_dir / "data" / sanitize_file_name_part(item.reserving_class, "class")
        sidecar = _read_json(class_dir / "sidecars" / f"{sanitize_file_name_part(item.dataset_name, 'dataset')}.json")
        base_file = class_dir / "datasets" / (
            f"{sanitize_file_name_part(item.base, 'dataset')}@{item.origin_length}@{item.development_length}@cum@dev.csv"
        )
        if not base_file.exists():
            failures += 1
            print(f"FAIL {item.reserving_class} | {item.dataset_name}: no {base_file.name}")
            continue
        store = read_rows(class_dir / "datasets" / str(sidecar["csv_file"]))
        base = read_rows(base_file)
        pairs = [(mine, theirs) for mine, theirs in zip(group_latest(store, len(base)), group_latest(base, len(base))) if mine]
        if not pairs:
            print(f"empty {item.reserving_class} | {item.dataset_name}: holds no figure to compare")
            continue
        ratio = sum(m for m, _ in pairs) / sum(t for _, t in pairs) if sum(t for _, t in pairs) else float("nan")
        good = abs(ratio - 1.0) <= CHECK_TOLERANCE
        failures += 0 if good else 1
        print(f"{'ok  ' if good else 'FAIL'} {item.reserving_class} | {item.dataset_name}"
              f" ({sidecar['source_kind']}, {sidecar['csv_file']}) latest/base={ratio:.3f} over {len(pairs)} of {len(base)} origins")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="server root holding projects\\<project>")
    parser.add_argument("--project", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--only", default="", help="only reserving classes whose path ends with this text")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan; reads files only")
    mode.add_argument("--check", action="store_true", help="compare each latest diagonal with its base")
    args = parser.parse_args(argv)
    project_dir = Path(args.root) / "projects" / args.project
    if args.check:
        return 1 if check_project(project_dir) else 0
    plan = [item for item in plan_project(project_dir, args.seed) if item.reserving_class.endswith(args.only)]
    for item in plan:
        print(f"{'SKIP' if item.problem else 'plan'} {item.reserving_class} | {item.dataset_name} <- {item.base}"
              f" at {item.origin_length}x{item.development_length} kind={item.source_kind}"
              f"{' reshape' if item.reshape else ''}{' : ' + item.problem if item.problem else ''}")
    if args.dry_run:
        return 1 if any(item.problem for item in plan) else 0
    if os.environ.get("ARCRHO_SERVER_ROOT", "").rstrip("\\/").casefold() != str(Path(args.root)).rstrip("\\/").casefold():
        print("ARCRHO_SERVER_ROOT does not name --root; refusing to save.")
        return 2
    return 1 if run_saves(plan, args.project) else 0


if __name__ == "__main__":
    raise SystemExit(main())
