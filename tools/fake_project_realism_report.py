#!/usr/bin/env python3
"""Report how realistic a project's stored triangles look. Read only.

For every development triangle CSV under ``data/<class>/datasets`` the report
counts, per dataset name across every reserving class and period length:

- the share of filled cells that are negative;
- for a cumulative triangle, the share of cells below the cell to their left
  in the same origin row (a cumulative figure that went down);
- the triangles whose every filled cell is zero.

It then states three checks (plan decision 5 of fake_project_refresh.md):

- no negative pending claim counts (the excess layers are exempt: a closed
  claim a later recovery takes under the layer leaves the reported layer only);
- no decreasing cumulative reported claim counts (incurred losses may fall
  as case reserves are taken down);
- no all-zero claim count triangle outside the excess layers, in a class with
  at least ``MIN_REPORTED_CLAIMS`` reported claims (a young book may have no
  closed claim yet).

Exit code 1 when a check fails.

Usage
-----
    py -3.10 tools/fake_project_realism_report.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


MIN_REPORTED_CLAIMS = 50


@dataclass
class Tally:
    triangles: int = 0
    cells: int = 0
    negative: int = 0
    steps: int = 0
    decreasing: int = 0
    all_zero: int = 0
    zero_classes: list[str] = field(default_factory=list)


def _parse_triangle_name(file_name: str) -> tuple[str, bool] | None:
    """``name@o@d@cum@dev.csv`` -> (name, cumulative); anything else -> None."""

    if not file_name.endswith(".csv"):
        return None
    parts = file_name[:-4].split("@")
    if len(parts) != 5 or parts[4] != "dev":
        return None
    return parts[0], parts[3] == "cum"


def _read_rows(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for record in csv.reader(stream):
            values = []
            for cell in record:
                text = cell.strip()
                if not text:
                    continue
                try:
                    values.append(float(text))
                except ValueError:
                    values = []
                    break
            rows.append(values)
    return rows


def _tally_triangle(tally: Tally, rows: list[list[float]], cumulative: bool) -> bool:
    """Add one triangle; True when every filled cell is zero."""
    tally.triangles += 1
    filled = [value for row in rows for value in row]
    tally.cells += len(filled)
    tally.negative += sum(1 for value in filled if value < 0)
    if cumulative:
        for row in rows:
            for left, right in zip(row, row[1:]):
                tally.steps += 1
                if right < left - 1e-6 * max(1.0, abs(left)):
                    tally.decreasing += 1
    if filled and all(value == 0 for value in filled):
        tally.all_zero += 1
        return True
    return False


def scan(project_root: Path) -> tuple[dict[str, Tally], dict[str, float]]:
    """Tallies per dataset name, and each class folder's reported claim count."""

    tallies: dict[str, Tally] = defaultdict(Tally)
    reported: dict[str, float] = {}
    for class_dir, _subdirs, files in os.walk(project_root / "data"):
        if os.path.basename(class_dir) != "datasets":
            continue
        class_name = os.path.basename(os.path.dirname(class_dir))
        reported.setdefault(class_name, 0.0)
        for file_name in files:
            parsed = _parse_triangle_name(file_name)
            if parsed is None:
                continue
            name, cumulative = parsed
            rows = _read_rows(Path(class_dir) / file_name)
            if _tally_triangle(tallies[name], rows, cumulative):
                tallies[name].zero_classes.append(class_name)
            if name == "Claim Counts--Reported" and cumulative:
                # The latest diagonal of a cumulative triangle is every claim reported.
                reported[class_name] = max(reported[class_name], sum(row[-1] for row in rows if row))
    return dict(tallies), reported


def _share(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:6.2f}%" if whole else "      -"


def _is_count(name: str) -> bool:
    return name.startswith("Claim Counts--") and " as % " not in name


def checks(tallies: dict[str, Tally], reported: dict[str, float]) -> list[tuple[str, list[str]]]:
    pending = [
        name for name, t in tallies.items()
        if name == "Claim Counts--Pending" and t.negative
    ]
    decreasing = [
        name for name, t in tallies.items()
        if name == "Claim Counts--Reported" and t.decreasing
    ]
    zero_counts = sorted(
        f"{name} in {class_name}"
        for name, t in tallies.items()
        if _is_count(name) and "Excess" not in name
        for class_name in t.zero_classes
        if reported.get(class_name, 0.0) >= MIN_REPORTED_CLAIMS
    )
    return [
        ("No negative pending claim counts", pending),
        ("No decreasing cumulative reported claim counts", decreasing),
        (
            "No all-zero claim count triangle outside the excess layers "
            f"(classes with {MIN_REPORTED_CLAIMS}+ reported claims)",
            zero_counts,
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="Arco Server root")
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)

    tallies, reported = scan(Path(args.root) / "projects" / args.project)
    width = max((len(name) for name in tallies), default=10)
    print(f"{'Dataset':<{width}}  Tri   Cells  Negative  Decreasing  All-zero")
    for name in sorted(tallies):
        t = tallies[name]
        print(
            f"{name:<{width}}  {t.triangles:>3} {t.cells:>7}   {_share(t.negative, t.cells)}"
            f"     {_share(t.decreasing, t.steps)}  {t.all_zero:>4}"
        )
    total = Tally()
    for t in tallies.values():
        for key in ("triangles", "cells", "negative", "steps", "decreasing", "all_zero"):
            setattr(total, key, getattr(total, key) + getattr(t, key))
    print(
        f"\nAll {total.triangles} triangles: negative {_share(total.negative, total.cells).strip()}, "
        f"decreasing {_share(total.decreasing, total.steps).strip()}, all-zero {total.all_zero}"
    )
    failed = False
    for label, names in checks(tallies, reported):
        print(f"{'PASS' if not names else 'FAIL'}  {label}" + (": " + ", ".join(sorted(names)) if names else ""))
        failed = failed or bool(names)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
