#!/usr/bin/env python3
r"""Repair the dependency links of every Engine-built dataset on the server.

A dataset the Engine builds by evaluating a formula over other dataset types
now records what it is made from and what reads it, the way an app-calculated
one always did, and every regeneration keeps those two lists current. A
sidecar written before that change keeps whichever lists it was first written
with, and a regeneration only repairs the datasets it actually rebuilds, so
the few projects that already exist are repaired once, here.

Nothing but ``precedents`` and ``dependents`` moves. No ``updated_at`` is
stamped, no audit record is added, and no reserving-class index is rebuilt --
the index carries no link field. A file whose lists are already right is not
written at all, so a second run writes nothing and no method is moved to
Needs Review by the repair.

Run it on the Server PC (``NE7SASWPN02``), where ``E:\Arco Server`` is local
disk: it walks every sidecar of every reserving class, which over the share is
one network round trip per file. Nothing in the code checks which machine it
is on. Nothing is written without ``--apply``; each class is held under the
same reserving-class lease a dependent walk takes while it is being written,
so a save landing at that moment meets the 423 hold it already understands,
and a class another job is already holding is skipped and reported.

Usage
-----
    py -3.10 tools/repair_dataset_graph_fields.py
    py -3.10 tools/repair_dataset_graph_fields.py --project "NJ_Annual_Prod_202605_Fake" --apply
    py -3.10 tools/repair_dataset_graph_fields.py --apply --report temp/graph_repair.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend"))

from arcrho_dependent_propagation_contract import (  # noqa: E402
    DependentPropagationLeaseUnavailable,
    held_reserving_class_lease,
)


@dataclass
class Report:
    """What one walk found, and what it wrote."""

    apply: bool
    projects: list[str] = field(default_factory=list)
    classes_walked: int = 0
    classes_skipped: list[dict[str, str]] = field(default_factory=list)
    sidecars_read: int = 0
    sidecars_written: int = 0
    written: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "mode": "applied" if self.apply else "dry-run",
            "projects": self.projects,
            "reserving_classes_walked": self.classes_walked,
            "reserving_classes_skipped": self.classes_skipped,
            "sidecars_read": self.sidecars_read,
            "sidecars_written": self.sidecars_written,
            "datasets_repaired": self.written,
            "failures": self.failures,
        }


def repair_project(project_name: str, report: Report, *, server_root: str) -> None:
    """Repair every reserving class of one project, class by class."""

    from app_server.services import calculated_dataset_service

    classes = calculated_dataset_service.project_reserving_classes(project_name)
    for number, reserving_class in enumerate(classes, start=1):
        print(
            f"    [{number}/{len(classes)}] {reserving_class}",
            file=sys.stderr,
            flush=True,
        )
        try:
            outcome = _repair_class(
                calculated_dataset_service,
                project_name,
                reserving_class,
                apply=report.apply,
                server_root=server_root,
            )
        except DependentPropagationLeaseUnavailable as error:
            report.classes_skipped.append({
                "project": project_name,
                "reserving_class": reserving_class,
                "detail": str(error),
            })
            continue
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            report.failures.append({
                "project": project_name,
                "reserving_class": reserving_class,
                "dataset_name": "",
                "detail": f"{type(error).__name__}: {error}",
            })
            continue
        report.classes_walked += 1
        report.sidecars_read += int(outcome.get("sidecars_read") or 0)
        report.sidecars_written += int(outcome.get("sidecars_written") or 0)
        for name in outcome.get("written") or []:
            report.written.append(f"{project_name} / {reserving_class} / {name}")
        for entry in outcome.get("unreadable") or []:
            report.failures.append({
                "project": project_name,
                "reserving_class": reserving_class,
                "dataset_name": str(entry.get("dataset_name") or ""),
                "detail": str(entry.get("detail") or ""),
            })


def _repair_class(
    service: Any,
    project_name: str,
    reserving_class: str,
    *,
    apply: bool,
    server_root: str,
) -> dict[str, Any]:
    """One class, held under the propagation lease for the duration of a write.

    A report-only run writes nothing, so it takes no lease and can never make
    a save wait. ``timeout_seconds=0`` turns a class another job is holding
    into an immediate refusal rather than a wait.
    """

    if not apply:
        return service.repair_reserving_class_graph_fields(
            project_name, reserving_class, apply=False
        )
    with held_reserving_class_lease(
        server_root, project_name, reserving_class, timeout_seconds=0
    ):
        return service.repair_reserving_class_graph_fields(project_name, reserving_class)


def print_summary(report: Report) -> None:
    payload = report.payload()
    print()
    print(payload["mode"])
    print(f"Projects walked:                   {len(report.projects):>7,}")
    print(f"Reserving classes walked:          {report.classes_walked:>7,}")
    print(f"Sidecars read:                     {report.sidecars_read:>7,}")
    label = "Sidecars written" if report.apply else "Sidecars to write"
    print(f"{label + ':':<35}{report.sidecars_written:>7,}")
    for name in report.written[:40]:
        print(f"    {name}")
    if len(report.written) > 40:
        print(f"    ... and {len(report.written) - 40:,} more")
    if report.classes_skipped:
        print()
        print(f"SKIPPED, ANOTHER JOB HOLDS THE CLASS ({len(report.classes_skipped)}):")
        for entry in report.classes_skipped:
            print(f"  {entry['project']} / {entry['reserving_class']}")
    if report.failures:
        print()
        print(f"COULD NOT BE READ ({len(report.failures)}):")
        for entry in report.failures[:20]:
            print(f"  {entry['project']} / {entry['reserving_class']} / {entry['dataset_name']}")
            print(f"      {entry['detail']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        help="Project folder name; repeatable, default every project",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write the repaired links (default is a dry run)"
    )
    parser.add_argument("--report", default="", help="Write the full JSON report to this path")
    args = parser.parse_args(argv)

    from app_server import config

    config.refresh_runtime_paths()
    projects_root = Path(config.PROJECT_SETTINGS_DIR)
    if not projects_root.is_dir():
        print(f"Projects folder not found: {projects_root}", file=sys.stderr)
        return 2
    server_root = config.get_root_path()

    names = list(args.project)
    if not names:
        names = sorted(
            entry.name
            for entry in os.scandir(projects_root)
            if entry.is_dir() and not entry.name.startswith(".")
        )

    report = Report(apply=args.apply)
    for number, name in enumerate(names, start=1):
        if not (projects_root / name).is_dir():
            print(f"Project not found: {projects_root / name}", file=sys.stderr)
            return 2
        report.projects.append(name)
        print(f"[{number}/{len(names)}] {name}", file=sys.stderr, flush=True)
        repair_project(name, report, server_root=server_root)

    print_summary(report)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report.payload(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print()
        print(f"Report: {report_path}")
    return 1 if report.failures or report.classes_skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
