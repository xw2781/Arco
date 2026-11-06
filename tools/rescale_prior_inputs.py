#!/usr/bin/env python3
"""Put a project's prior and expected-ratio input vectors on the scale of its current results.

When a project's data is replaced (fake_project_refresh.md, step 12) the
hand-entered vectors the methods read as priors keep the old figures while the
Result Selections move. This tool rewrites each one from the Result Selection
outputs of its own class, times a small seeded factor per origin:

- "x 81 - Prior Qtr Indicated" from "x 91";
- "x 82 - Prior Qtr Selected" and the BF priors ("x 42 - Prior for BF ...",
  "C 42a", "F 42 B") from "x 92";
- the expected ratios: P 01, P 02, P 03 and P 04 A are E, E1, E2 and G 92 over
  D 92; P 04 B is G 92 over F 92; P 05, P 06 and P 07 are G, F and D 92 over
  Total Earned Premium.

Each vector is written at the shortest period its counterpart and its
dependents use (a calculated dependent reads it at its counterpart's period
even when shown coarser); a source stored finer is summed into it. A vector stored at another period (ResQ often
stored them monthly) is re-stored with the project's origin labels. Values are
read just before each save, so a vector saved later reads Result Selections
the earlier saves' walks refreshed; a second run settles what the first moved.
Every write goes through the hosted dataset save, so the dependent walk runs.

Usage
-----
    py -3.10 tools/rescale_prior_inputs.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake --dry-run
    py -3.10 tools/rescale_prior_inputs.py --root ... --project ...          # saves through the Gateway
    py -3.10 tools/rescale_prior_inputs.py --root ... --project ... --check  # each vector vs its counterpart
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from arcrho_api.paths import sanitize_file_name_part  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("rescale_resq_stored_triangles", Path(__file__).with_name("rescale_resq_stored_triangles.py"))
assert _SPEC is not None and _SPEC.loader is not None
triangles = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault(_SPEC.name, triangles)
_SPEC.loader.exec_module(triangles)

PREMIUM = "Total Earned Premium"
CHECK_LOW, CHECK_HIGH = 0.5, 2.0
# Expected ratio prefix -> (numerator, denominator); a code names "<code> 92".
RATIOS = {
    "P 01": ("E", "D"), "P 02": ("E1", "D"), "P 03": ("E2", "D"), "P 04 A": ("G", "D"),
    "P 04 B": ("G", "F"), "P 05": ("G", PREMIUM), "P 06": ("F", PREMIUM), "P 07": ("D", PREMIUM),
}
# Processed in this order: indicated priors feed the x 92 selections the rest read.
STAGES = ("81", "82", "42", "ratio")


@dataclass
class Vector:
    reserving_class: str
    dataset_name: str
    stage: str
    sources: tuple[str, ...]  # one counterpart, or numerator and denominator
    period: int = 0
    stored_period: int = 0
    problem: str = ""


def classify(name: str) -> tuple[str, tuple[str, ...]] | None:
    """The stage and source codes of an input vector this tool rewrites, or None."""

    for prefix, (numerator, denominator) in RATIOS.items():
        if re.match(rf"^{re.escape(prefix)}\b(?! [A-Z]\b)", name) or name.startswith(prefix + "-"):
            return "ratio", (numerator, denominator)
    match = re.match(r"^(\S+) (81|82) - Prior Qtr", name)
    if match:
        return match.group(2), (f"{match.group(1)} {'91' if match.group(2) == '81' else '92'}",)
    match = re.match(r"^(\S+) 42\S*(?: [A-Z])? - Prior for BF", name)
    if match:
        return "42", (f"{match.group(1)} 92",)
    return None


def _period(sidecar: dict[str, Any]) -> int:
    return int(sidecar.get("period_length") or sidecar.get("origin_length") or 0)


def _stored_period(sidecar: dict[str, Any]) -> int:
    return int(sidecar.get("stored_period_length") or sidecar.get("stored_origin_length") or _period(sidecar))


def _source_name(sidecars: dict[str, dict], code: str) -> str:
    """The class's dataset a source code names; a BF prior with no "x 92" follows "x 91"."""

    if code == PREMIUM:
        return PREMIUM if PREMIUM in sidecars else ""
    code = code if " " in code else f"{code} 92"
    for candidate in (code, code[:-2] + "91") if code.endswith(" 92") else (code,):
        name = next((name for name in sidecars if name.startswith(f"{candidate} - ")), "")
        if name:
            return name
    return ""


def load_sidecars(class_dir: Path) -> dict[str, dict]:
    sidecars = {}
    for path in (class_dir / "sidecars").glob("*.json"):
        sidecar = triangles._read_json(path)
        sidecars[str(sidecar.get("dataset_name") or "")] = sidecar
    return sidecars


def plan_project(project_dir: Path) -> list[Vector]:
    plan: list[Vector] = []
    for class_dir in sorted((project_dir / "data").iterdir()):
        if not (class_dir / "sidecars").is_dir():
            continue
        sidecars = load_sidecars(class_dir)
        for name, sidecar in sorted(sidecars.items()):
            kind = classify(name)
            if not kind or sidecar.get("data_format") != "Vector" or sidecar.get("source_kind") != "input":
                continue
            stage, codes = kind
            sources = tuple(_source_name(sidecars, code) for code in codes)
            item = Vector(str(sidecar["reserving_class"]), name, stage, sources, stored_period=_stored_period(sidecar))
            dependents = [sidecars.get(str(entry.get("dataset_name"))) for entry in sidecar.get("dependents") or []]
            periods = [_period(dep) for dep in dependents if dep and _period(dep)]
            counterpart = sidecars.get(sources[0]) if sources[0] else None
            if counterpart and _period(counterpart):
                periods.append(_period(counterpart))
            item.period = min(periods) if periods else _period(sidecar)
            missing = [code for code, source in zip(codes, sources) if not source]
            if missing:
                item.problem = f"no {' / '.join(missing)} in the class"
            plan.append(item)
    plan.sort(key=lambda item: (STAGES.index(item.stage), item.reserving_class, item.dataset_name))
    return plan


def _column(rows: list[list[float | None]]) -> list[float]:
    return [(row[0] if row and row[0] is not None else 0.0) for row in rows]


def source_values(
    project_dir: Path, class_dir: Path, sidecar: dict[str, Any], period: int, *, split: bool = False
) -> list[float]:
    """A source vector at ``period``: an Engine dataset's own file, or a stored one summed up to it.

    ``split`` spreads a counterpart stored coarser than ``period`` evenly over
    its finer origins (a yearly selection whose BF prior is read quarterly).
    """

    name = str(sidecar["dataset_name"])
    if sidecar.get("source_kind") == "engine":
        # The Engine writes one file per period it was asked for; take the
        # coarsest one built from the current source table that adds up to
        # ``period``.
        table = Path(triangles._read_json(project_dir / "field_mapping.json")["table_path"])
        fresh_after = table.stat().st_mtime if table.exists() else 0.0
        stem = sanitize_file_name_part(name, "dataset")
        for stored in sorted((p for p in (12, 6, 3, 1) if period % p == 0), reverse=True):
            path = class_dir / "datasets" / f"{stem}@{stored}.csv"
            if path.exists() and path.stat().st_mtime >= fresh_after:
                break
        else:
            raise ValueError(f"no {stem} file built from the source table adds up to {period} months")
        values = _column(triangles.read_rows(path))
        step = period // stored
        return [sum(values[index:index + step]) for index in range(0, len(values), step)]
    stored = _stored_period(sidecar)
    if split and stored > period and stored % period == 0:
        step = stored // period
        values = _column(triangles.read_rows(class_dir / "datasets" / str(sidecar["csv_file"])))
        return [value / step for value in values for _ in range(step)]
    if period % stored:
        raise ValueError(f"{name} is stored at {stored} months and cannot give {period}")
    values = _column(triangles.read_rows(class_dir / "datasets" / str(sidecar["csv_file"])))
    step = period // stored
    return [sum(values[index:index + step]) for index in range(0, len(values), step)]


def target_values(project_dir: Path, item: Vector, seed: int) -> tuple[list[float], list[float]]:
    """The values to write and the current counterpart they follow (numerator over denominator for a ratio)."""

    class_dir = project_dir / "data" / sanitize_file_name_part(item.reserving_class, "class")
    sidecars = load_sidecars(class_dir)
    columns = [source_values(project_dir, class_dir, sidecars[name], item.period, split=True) for name in item.sources]
    if item.stage == "ratio":
        numerator, denominator = columns
        current = [n / d if d else 0.0 for n, d in zip(numerator, denominator)]
    else:
        current = columns[0]
    labels = triangles.project_origin_labels(project_dir, item.period)
    if len(current) != len(labels):
        raise ValueError(f"{item.sources[0]} has {len(current)} origins at {item.period} months, expected {len(labels)}")
    factors = triangles.origin_factors(seed, item.reserving_class, item.dataset_name, len(current))
    return [value * factor for value, factor in zip(current, factors)], current


def save_arguments(project_dir: Path, item: Vector, values: list[float]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "source_kind": "input",
        "data_format": "Vector",
        "origin_length": item.period,
        "development_length": item.period,
        "values": [[value] for value in values],
        "mask": [[True] for _ in values],
    }
    if item.period != item.stored_period:
        kwargs["stored_values_cleared"] = True
        kwargs["origin_labels"] = triangles.project_origin_labels(project_dir, item.period)
    return kwargs


def run_saves(project_dir: Path, plan: list[Vector], project: str, seed: int) -> int:
    from arcrho_api.gateway import GatewayClient

    gateway = GatewayClient()
    print(f"saving as {gateway.user} through {gateway.url}", flush=True)
    failures = 0
    for item in plan:
        if item.problem:
            continue
        triangles._wait_for_class(gateway, project, item.reserving_class)
        label = f"{item.reserving_class} | {item.dataset_name} @{item.period}"
        try:
            values, _ = target_values(project_dir, item, seed)
            result = gateway.save("dataset_sidecar", project, item.reserving_class, item.dataset_name,
                                  **save_arguments(project_dir, item, values))
        except Exception as err:  # report and carry on with the next vector
            failures += 1
            print(f"FAIL {label}: {err}", flush=True)
            continue
        propagation = (result or {}).get("calculated_updates") or (result or {}).get("propagation") or {}
        ok = propagation.get("ok", True)
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'WALK'} {label} walk={propagation.get('status')}"
              + ("" if ok else f" message={propagation.get('message') or propagation.get('reason')}"), flush=True)
    return failures


def check_ratio(stored: list[float], current: list[float]) -> float | None:
    """Total of the vector over the total of its counterpart, over origins where both hold a figure."""

    pairs = [(mine, theirs) for mine, theirs in zip(stored, current) if mine and theirs]
    if not pairs:
        return None
    total = sum(theirs for _, theirs in pairs)
    return sum(mine for mine, _ in pairs) / total if total else None


def check_project(project_dir: Path) -> int:
    failures = 0
    for item in plan_project(project_dir):
        label = f"{item.reserving_class} | {item.dataset_name}"
        if item.problem:
            print(f"skip {label}: {item.problem}")
            continue
        class_dir = project_dir / "data" / sanitize_file_name_part(item.reserving_class, "class")
        sidecar = load_sidecars(class_dir)[item.dataset_name]
        try:
            _, current = target_values(project_dir, item, 0)
            stored = source_values(project_dir, class_dir, sidecar, item.period)
        except (ValueError, OSError) as err:
            failures += 1
            print(f"FAIL {label}: {err}")
            continue
        ratio = check_ratio(stored, current)
        good = ratio is None or CHECK_LOW <= ratio <= CHECK_HIGH
        failures += 0 if good else 1
        print(f"{'ok  ' if good else 'FAIL'} {label} @{item.period}: "
              + ("both empty" if ratio is None else f"vector/current={ratio:.3f}"))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="server root holding projects\\<project>")
    parser.add_argument("--project", required=True)
    parser.add_argument("--seed", type=int, default=triangles.DEFAULT_SEED)
    parser.add_argument("--only", default="", help="only reserving classes whose path ends with this text")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan; reads files only")
    mode.add_argument("--check", action="store_true", help="compare each vector with its current counterpart")
    args = parser.parse_args(argv)
    project_dir = Path(args.root) / "projects" / args.project
    if args.check:
        return 1 if check_project(project_dir) else 0
    plan = [item for item in plan_project(project_dir) if item.reserving_class.endswith(args.only)]
    for item in plan:
        reshape = f" (stored at {item.stored_period})" if item.stored_period != item.period else ""
        print(f"{'SKIP' if item.problem else 'plan'} {item.reserving_class} | {item.dataset_name}"
              f" <- {' / '.join(item.sources)} @{item.period}{reshape}{' : ' + item.problem if item.problem else ''}")
    if args.dry_run:
        return 1 if any(item.problem for item in plan) else 0
    if os.environ.get("ARCRHO_SERVER_ROOT", "").rstrip("\\/").casefold() != str(Path(args.root)).rstrip("\\/").casefold():
        print("ARCRHO_SERVER_ROOT does not name --root; refusing to save.")
        return 2
    return 1 if run_saves(project_dir, plan, args.project, args.seed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
