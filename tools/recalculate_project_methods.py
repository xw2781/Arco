#!/usr/bin/env python3
"""Recalculate every method of a project, class by class, and report how plausible the results look.

After a project's data is replaced (fake_project_refresh.md, step 7) every
method has to be refreshed on the new figures. This tool submits one
dependent-propagation walk per reserving class through the Gateway, rooted at
every dataset of the class that is not a method output, so the walk refreshes
each DFM, BF, Cape Cod, Result Selection, Berquist-Sherman, Bootstrap and
Stochastic Consolidation in dependency order. Classes run in an order where a
class whose methods read another class comes after it. Each walk's outcome
and failure reasons are written to a JSON report.

``--report`` reads the method files only and prints, per method, the first
selected development factor (DFM), the largest ultimate-to-latest ratio, and
the loss ratio against the method's ratio basis where it has one.

Usage
-----
    py -3.10 tools/recalculate_project_methods.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake --dry-run
    py -3.10 tools/recalculate_project_methods.py --root ... --project ... --out walks.json   # submits the walks
    py -3.10 tools/recalculate_project_methods.py --root ... --project ... --report plausibility.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

TERMINAL = ("success", "error")


@dataclass
class ClassWalk:
    reserving_class: str
    folder: Path
    roots: list[dict[str, str]]
    methods: int
    reads_from: set[str] = field(default_factory=set)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def plan_classes(project_dir: Path) -> list[ClassWalk]:
    """Every class with a method, upstream classes first."""

    walks: dict[str, ClassWalk] = {}
    for folder in sorted((project_dir / "data").iterdir()):
        index_path = folder / "index.json"
        if not folder.is_dir() or not index_path.exists():
            continue
        index = _read_json(index_path)
        files = index.get("files") or []
        methods = sum(1 for item in files if str(item.get("method_type") or "None") != "None")
        if not methods:
            continue
        roots = [
            {"dataset_name": str(item["name"]), "dataset_type": str(item.get("dataset_type") or "")}
            for item in files
            if str(item.get("method_type") or "None") == "None" and item.get("source_kind") in ("engine", "input")
        ]
        walk = ClassWalk(str(index["reserving_class"]), folder, roots, methods)
        for sidecar in (folder / "sidecars").glob("*.json"):
            for precedent in _read_json(sidecar).get("precedents") or []:
                other = str((precedent or {}).get("reserving_class") or "")
                if other and other.casefold() != walk.reserving_class.casefold():
                    walk.reads_from.add(other)
        walks[walk.reserving_class.casefold()] = walk

    ordered: list[ClassWalk] = []
    placed: set[str] = set()

    def place(key: str, trail: tuple[str, ...] = ()) -> None:
        if key in placed or key not in walks or key in trail:
            return
        for upstream in sorted(walks[key].reads_from):
            place(upstream.casefold(), trail + (key,))
        placed.add(key)
        ordered.append(walks[key])

    for key in walks:
        place(key)
    return ordered


def _wait_for_class(gateway: Any, project: str, reserving_class: str, timeout: float = 1800.0) -> None:
    deadline = time.time() + timeout
    while gateway.read("propagation_busy", project_name=project, reserving_class=reserving_class).get("busy"):
        if time.time() > deadline:
            raise TimeoutError(f"{reserving_class} is still busy after {timeout:.0f}s")
        time.sleep(2)


def run_walks(plan: list[ClassWalk], project: str) -> list[dict[str, Any]]:
    from arcrho_api.gateway import GatewayClient

    gateway = GatewayClient()
    print(f"walking as {gateway.user} through {gateway.url}", flush=True)
    outcomes = []
    for walk in plan:
        started = time.time()
        _wait_for_class(gateway, project, walk.reserving_class)
        outcome: dict[str, Any] = {"reserving_class": walk.reserving_class, "roots": len(walk.roots), "methods": walk.methods}
        try:
            job = gateway.mutate(
                "propagation_submit",
                project_name=project,
                reserving_class=walk.reserving_class,
                changed_roots=walk.roots,
                request_id=uuid.uuid4().hex,
            )
            status: dict[str, Any] = {}
            while status.get("status") not in TERMINAL:
                time.sleep(3)
                status = gateway.read("propagation_status", request_id=job["job_id"])
            outcome.update(job_id=job["job_id"], status=status["status"], message=status.get("message") or "")
        except Exception as err:  # record and carry on with the next class
            outcome.update(status="error", message=f"submit failed: {err}")
        outcome["seconds"] = round(time.time() - started)
        outcomes.append(outcome)
        print(f"{outcome['status']:7} {walk.reserving_class} ({outcome['seconds']}s)"
              + (f": {outcome['message']}" if outcome["message"] else ""), flush=True)
    return outcomes


# ---------------------------------------------------------------------------
# Plausibility report
# ---------------------------------------------------------------------------


def _numbers(values: Any) -> list[float | None]:
    out: list[float | None] = []
    for value in values or []:
        try:
            out.append(None if value is None or value == "" else float(value))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _latest(triangle: Any) -> list[float | None]:
    latest = []
    for row in triangle or []:
        cells = [cell for cell in _numbers(row) if cell is not None]
        latest.append(cells[-1] if cells else None)
    return latest


def _max_ratio(ultimate: list[float | None], latest: list[float | None]) -> float | None:
    ratios = [u / l for u, l in zip(ultimate, latest) if u is not None and l and l > 0]
    return max(ratios) if ratios else None


def _loss_ratio(ultimate: list[float | None], basis: list[float | None]) -> float | None:
    pairs = [(u, b) for u, b in zip(ultimate, basis) if u is not None and b]
    total = sum(b for _, b in pairs)
    return sum(u for u, _ in pairs) / total if total else None


def selected_factors(dfm: dict[str, Any]) -> list[float | None]:
    averages = (dfm.get("ratios_tab") or {}).get("average_formulas") or {}
    selected, values = averages.get("selected") or [], averages.get("values") or []
    width = max((len(row) for row in selected), default=0)
    factors: list[float | None] = []
    for column in range(width):
        row = next((i for i, flags in enumerate(selected) if column < len(flags) and flags[column]), None)
        factors.append(None if row is None else _numbers(values[row])[column] if column < len(values[row]) else None)
    return factors


def method_measures(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "DFM":
        results = payload.get("results_tab") or {}
        ultimate = _numbers(results.get("ultimate_vector"))
        latest = _latest((payload.get("data_tab") or {}).get("input_data_triangle_values"))
        factors = selected_factors(payload)
        return {
            "first_factor": factors[0] if factors else None,
            "max_ult_to_latest": _max_ratio(ultimate, latest),
            # Only a premium basis gives a loss ratio; other bases are counts or exposures.
            "loss_ratio": _loss_ratio(ultimate, _numbers(results.get("ratio_basis_values")))
            if "premium" in str(results.get("ratio_basis_dataset") or "").lower() else None,
        }
    tab = payload.get("method_tab") or {}
    if kind == "BF":
        return {"max_ult_to_latest": _max_ratio(_numbers(tab.get("new_ultimate")), _numbers(tab.get("latest_values")))}
    if kind == "CC":
        ultimate = _numbers(tab.get("cape_cod_ultimate"))
        return {
            "max_ult_to_latest": _max_ratio(ultimate, _numbers(tab.get("latest_values"))),
            "loss_ratio": _loss_ratio(ultimate, _numbers(tab.get("exposure_values"))),
        }
    if kind == "RS":
        active = (payload.get("details_tab") or {}).get("active_ratio_basis_dataset")
        basis = next((item.get("values") for item in tab.get("ratio_basis_values") or []
                      if isinstance(item, dict) and item.get("name") == active), None)
        if not active or "premium" not in str(active).lower():
            return {}
        return {"loss_ratio": _loss_ratio(_numbers(tab.get("selected_ultimate")), _numbers(basis))}
    return {}


def plausibility(project_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for folder in sorted((project_dir / "data").iterdir()):
        index_path = folder / "index.json"
        if not index_path.exists() or not (folder / "methods").is_dir():
            continue
        reserving_class = _read_json(index_path)["reserving_class"]
        for path in sorted((folder / "methods").glob("*.json")):
            kind = path.stem.split("@", 1)[0]
            if kind not in ("DFM", "BF", "CC", "RS"):
                continue
            rows.append({"reserving_class": reserving_class, "file": path.name, "kind": kind,
                         **method_measures(kind, _read_json(path))})
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def spread(key: str, kind: str | None = None) -> dict[str, Any]:
        values = sorted(r[key] for r in rows if r.get(key) is not None and (kind is None or r["kind"] == kind))
        if not values:
            return {}
        return {"n": len(values), "median": round(statistics.median(values), 3),
                "p90": round(values[int(0.9 * (len(values) - 1))], 3), "max": round(values[-1], 3)}

    return {
        "methods": len(rows),
        "dfm_first_factor": spread("first_factor", "DFM"),
        "max_ult_to_latest": spread("max_ult_to_latest"),
        "dfm_loss_ratio": spread("loss_ratio", "DFM"),
        "rs_loss_ratio": spread("loss_ratio", "RS"),
        "ult_over_20x_latest": sum(1 for r in rows if (r.get("max_ult_to_latest") or 0) > 20),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", required=True, help="server root holding projects\\<project>")
    parser.add_argument("--project", required=True)
    parser.add_argument("--only", default="", help="only reserving classes whose path ends with this text")
    parser.add_argument("--out", default="", help="write the walk outcomes as JSON here")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the class order; reads files only")
    mode.add_argument("--report", metavar="PATH", help="write the plausibility report as JSON; reads files only")
    args = parser.parse_args(argv)
    project_dir = Path(args.root) / "projects" / args.project
    if args.report:
        rows = plausibility(project_dir)
        summary = summarize(rows)
        Path(args.report).write_text(json.dumps({"summary": summary, "methods": rows}, indent=1), encoding="utf-8")
        print(json.dumps(summary, indent=1))
        return 0
    plan = [walk for walk in plan_classes(project_dir) if walk.reserving_class.endswith(args.only)]
    for walk in plan:
        print(f"plan {walk.reserving_class}: {walk.methods} methods, {len(walk.roots)} roots"
              + (f", after {', '.join(sorted(walk.reads_from))}" if walk.reads_from else ""))
    if args.dry_run:
        return 0
    if os.environ.get("ARCRHO_SERVER_ROOT", "").rstrip("\\/").casefold() != str(Path(args.root)).rstrip("\\/").casefold():
        print("ARCRHO_SERVER_ROOT does not name --root; refusing to submit.")
        return 2
    outcomes = run_walks(plan, args.project)
    if args.out:
        Path(args.out).write_text(json.dumps(outcomes, indent=1), encoding="utf-8")
    return 1 if any(o["status"] != "success" for o in outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
