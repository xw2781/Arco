#!/usr/bin/env python3
"""Write the stored period lengths into every dataset sidecar on the server.

A sidecar used to record one period length per axis and it meant two things at
once: the granularity of its own CSV and the shape the dataset is displayed
at. Those are now separate fields -- ``stored_origin_length`` /
``stored_development_length`` on a triangle, ``stored_period_length`` on a
vector -- and every writer emits them, but a file written before that change
carries only the single shape. This walks every project's sidecars once and
fills the stored fields in, so no reader needs a missing-field fallback.

The value is the shape the file already records, which for a hand-entered,
imported, calculated or method-output dataset is the granularity of its CSV;
the file name confirms it, and every sidecar whose recorded lengths disagree
with the ``@origin@development@`` in its own ``csv_file`` is reported rather
than guessed at. A regenerable Engine dataset takes the same value for now and
is counted separately in the report: its real granularity is the source data's,
which nothing records until the project field mapping carries it.

Nothing else about a file changes, and one that already carries the stored
fields is left alone, so the run is repeatable. Nothing is written at all
without ``--apply``; ``--rebuild-index`` then rebuilds every reserving-class
index so its rows carry the pair too.

Usage
-----
    py -3.10 tools/backfill_stored_period_lengths.py
    py -3.10 tools/backfill_stored_period_lengths.py --apply --rebuild-index
    py -3.10 tools/backfill_stored_period_lengths.py --project "NJ_Annual_Prod_202605_Fake"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend"))

from arcrho_api.io import ArcRhoApiError, write_json_atomic
from arcrho_api.sidecar_core_contract import (
    SIDECAR_AUDIT_LOG_FIELD,
    SIDECAR_STORED_DEVELOPMENT_FIELD,
    SIDECAR_STORED_ORIGIN_FIELD,
    SIDECAR_STORED_PERIOD_FIELD,
    SidecarContractError,
    is_vector_format,
    stored_length_fields_from_display,
    validate_period_lengths,
    validate_sidecar_core,
)

DEFAULT_WORKSPACE = r"E:\Arco Server"
SIDECAR_DIR_NAME = "sidecars"
STAGING_DIR_NAME = ".arcrho-resq-import-staging"
ENGINE_SOURCE_KIND = "engine"

# ``<Name>@<origin>@<development>@...csv`` -- the shape the file itself is at.
_CSV_LENGTHS = re.compile(r"@(\d+)@(\d+)@")

# The stored fields go straight after the display ones, which is where every
# canonical builder writes them, so a backfilled file and a freshly saved one
# read the same way.
_DISPLAY_FIELDS = ("period_length", "origin_length", "development_length")


@dataclass
class Report:
    """What one walk found, and what it wrote."""

    workspace: str
    apply: bool
    projects: list[str] = field(default_factory=list)
    # (project folder, the reserving class's own name) of every class walked.
    # The folder name is the sanitized spelling, so the name a rebuild needs is
    # taken from the sidecars themselves rather than decoded back out of it.
    classes: list[tuple[str, str]] = field(default_factory=list)
    already_stored: int = 0
    written: int = 0
    by_source_kind: Counter = field(default_factory=Counter)
    engine_display_shape: int = 0
    csv_disagreements: list[dict[str, Any]] = field(default_factory=list)
    pre_v4_core_gaps: list[dict[str, str]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    indexes_rebuilt: list[str] = field(default_factory=list)
    index_failures: list[dict[str, str]] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "mode": "applied" if self.apply else "dry-run",
            "projects": self.projects,
            "sidecars_already_stored": self.already_stored,
            "sidecars_written": self.written,
            "written_by_source_kind": dict(sorted(self.by_source_kind.items())),
            "engine_sidecars_taking_the_display_shape": self.engine_display_shape,
            "csv_disagreements": self.csv_disagreements,
            "pre_v4_core_gaps": self.pre_v4_core_gaps,
            "failures": self.failures,
            "reserving_classes_walked": len(self.classes),
            "indexes_rebuilt": len(self.indexes_rebuilt),
            "index_failures": self.index_failures,
        }


def _long(path: Path) -> Path:
    """The path in the form Windows accepts beyond 260 characters.

    A staged ResQ import nests a session id and an escaped reserving-class name
    under the project, and the ``.json.tmp`` the atomic write puts beside such
    a sidecar can be the four characters that push it past the limit.
    """

    text = os.path.abspath(path)
    if os.name != "nt" or text.startswith("\\\\"):
        # Already extended, or a UNC path, which takes a different prefix and
        # which nothing here produces: the workspace is always a drive letter.
        return Path(text)
    return Path("\\\\?\\" + text)


def _read_sidecar(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise ValueError("A sidecar must hold a JSON object.")
    return dict(payload)


def stored_fields_missing(payload: Mapping[str, Any]) -> bool:
    """Whether *payload* still lacks the stored fields its format takes."""

    if is_vector_format(payload.get("data_format")):
        return SIDECAR_STORED_PERIOD_FIELD not in payload
    return (
        SIDECAR_STORED_ORIGIN_FIELD not in payload
        or SIDECAR_STORED_DEVELOPMENT_FIELD not in payload
    )


def with_stored_lengths(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return *payload* carrying the stored fields, beside the display ones.

    Nothing else about the file moves: the fields go in behind the last
    display length -- or in front of ``audit_log``, which is always last, for
    a file that records no length at all -- and every other key keeps the
    place and the value it had.
    """

    stored = stored_length_fields_from_display(payload)
    present = [key for key in payload if key in _DISPLAY_FIELDS]
    after = present[-1] if present else ""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if not after and key == SIDECAR_AUDIT_LOG_FIELD:
            out.update(stored)
        out[key] = value
        if key == after:
            out.update(stored)
    for key, value in stored.items():
        out.setdefault(key, value)
    return out


def csv_disagreement(payload: Mapping[str, Any]) -> tuple[int, int] | None:
    """The ``(origin, development)`` its CSV name states, when it differs."""

    match = _CSV_LENGTHS.search(str(payload.get("csv_file") or ""))
    if not match:
        return None
    origin, development = int(match.group(1)), int(match.group(2))
    if is_vector_format(payload.get("data_format")):
        recorded = payload.get("period_length")
        if recorded is None:
            recorded = payload.get("origin_length")
        return None if recorded == origin else (origin, development)
    if payload.get("origin_length") == origin and payload.get("development_length") == development:
        return None
    return (origin, development)


def _class_sidecar_dirs(data_dir: Path) -> Iterator[Path]:
    if not data_dir.is_dir():
        return
    for child in sorted(data_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            folder = child / SIDECAR_DIR_NAME
            if folder.is_dir():
                yield folder


def _sidecar_dirs(project_dir: Path) -> Iterator[tuple[Path, bool]]:
    """Every sidecar folder of a project, and whether it is a staged import.

    An import that was reviewed but never merged keeps its own copy of the
    class under ``.arcrho-resq-import-staging``. Those files are filled in too,
    so merging one later cannot put a record with no stored shape back on the
    share, but the class they belong to is not indexed until they are merged.
    """

    data = project_dir / "data"
    for folder in _class_sidecar_dirs(data):
        yield folder, False
    staging = data / STAGING_DIR_NAME
    if staging.is_dir():
        for session in sorted(staging.iterdir()):
            if session.is_dir():
                for folder in _class_sidecar_dirs(session / "data"):
                    yield folder, True


def backfill_project(project_dir: Path, report: Report, *, apply: bool, workers: int) -> None:
    for folder, staged in _sidecar_dirs(project_dir):
        paths = sorted(folder.glob("*.json"))
        # The share costs a round trip per file, not per byte, so one sidecar
        # at a time would make this run for hours. The reserving-class index
        # scan reads the same folder the same way.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(lambda path: _backfill_sidecar(path, apply=apply), paths))
        for outcome in outcomes:
            _record(outcome, project_dir.name, report, staged=staged)


def _backfill_sidecar(path: Path, *, apply: bool) -> dict[str, Any]:
    """Read one sidecar, write its stored fields in, and say what happened."""

    try:
        payload = _read_sidecar(path)
    except (OSError, ValueError) as error:
        return {"path": str(path), "failure": f"{type(error).__name__}: {error}"}
    outcome: dict[str, Any] = {
        "path": str(path),
        "reserving_class": str(payload.get("reserving_class") or "").strip(),
        "source_kind": str(payload.get("source_kind") or "").strip() or "(none)",
    }
    disagreement = csv_disagreement(payload)
    if disagreement:
        outcome["csv_disagreement"] = {
            "path": str(path),
            "csv_file": payload.get("csv_file"),
            "csv_lengths": list(disagreement),
            "origin_length": payload.get("origin_length"),
            "development_length": payload.get("development_length"),
            "period_length": payload.get("period_length"),
        }
    if not stored_fields_missing(payload):
        outcome["already_stored"] = True
        return outcome
    try:
        updated = with_stored_lengths(payload)
        # Only the rule this run is responsible for. A share written before
        # the v4 conversion script ran also holds files the shared core
        # validator refuses for older reasons -- no ``status``, a method
        # output not marked calculated -- and
        # ``tools/migrate_persisted_json_v4.py`` is what fixes those. They are
        # counted here and left otherwise untouched.
        validate_period_lengths(updated)
    except (SidecarContractError, ValueError) as error:
        outcome["failure"] = f"{type(error).__name__}: {error}"
        return outcome
    try:
        validate_sidecar_core(updated)
    except SidecarContractError as error:
        outcome["core_gap"] = str(error)
    if apply:
        try:
            write_json_atomic(_long(path), updated)
        except (ArcRhoApiError, OSError) as error:
            outcome["failure"] = f"{type(error).__name__}: {error}"
            return outcome
    outcome["written"] = True
    return outcome


def _record(outcome: Mapping[str, Any], project: str, report: Report, *, staged: bool) -> None:
    reserving_class = str(outcome.get("reserving_class") or "")
    if not staged and reserving_class and (project, reserving_class) not in report.classes:
        report.classes.append((project, reserving_class))
    if outcome.get("csv_disagreement"):
        report.csv_disagreements.append(outcome["csv_disagreement"])
    if outcome.get("failure"):
        report.failures.append({"path": outcome["path"], "detail": outcome["failure"]})
        return
    if outcome.get("already_stored"):
        report.already_stored += 1
        return
    if outcome.get("core_gap"):
        report.pre_v4_core_gaps.append({"path": outcome["path"], "detail": outcome["core_gap"]})
    if not outcome.get("written"):
        return
    source_kind = str(outcome.get("source_kind") or "(none)")
    report.written += 1
    report.by_source_kind[source_kind] += 1
    if source_kind == ENGINE_SOURCE_KIND:
        report.engine_display_shape += 1


def rebuild_indexes(report: Report) -> None:
    """Rebuild every reserving-class index so the rows carry the stored pair."""

    from app_server.services.dataset_instance_index_service import rebuild_index

    for number, (project, reserving_class) in enumerate(report.classes, start=1):
        print(f"[{number}/{len(report.classes)}] index {project}", file=sys.stderr, flush=True)
        try:
            response = rebuild_index(project, reserving_class)
        except Exception as error:  # noqa: BLE001 - reported, never fatal
            report.index_failures.append({
                "project": project,
                "reserving_class": reserving_class,
                "detail": f"{type(error).__name__}: {error}",
            })
            continue
        if not response.get("index_persisted"):
            report.index_failures.append({
                "project": project,
                "reserving_class": reserving_class,
                "detail": str(response.get("warning") or "index.json was not written"),
            })
            continue
        report.indexes_rebuilt.append(f"{project}/{reserving_class}")


def print_summary(report: Report) -> None:
    payload = report.payload()
    print()
    print(f"{payload['mode']}: {report.workspace}")
    print(f"Projects walked:                   {len(report.projects):>7,}")
    print(f"Reserving classes walked:          {len(report.classes):>7,}")
    print(f"Sidecars already carrying a shape: {report.already_stored:>7,}")
    print(f"Sidecars {'written':<26}{report.written:>7,}" if report.apply
          else f"Sidecars {'to write':<26}{report.written:>7,}")
    for kind, count in sorted(report.by_source_kind.items()):
        print(f"    {kind:<28}{count:>7,}")
    if report.engine_display_shape:
        print()
        print(
            f"{report.engine_display_shape:,} generated datasets took the shape they were last "
            "built at,\nbecause nothing records the granularity of the source data yet."
        )
    if report.csv_disagreements:
        print()
        print(f"RECORDED LENGTHS THAT DISAGREE WITH THEIR OWN CSV NAME ({len(report.csv_disagreements)}):")
        for entry in report.csv_disagreements[:20]:
            print(f"  {entry['path']}")
            print(f"      csv {entry['csv_lengths']} vs recorded "
                  f"{entry['origin_length']}/{entry['development_length']}/{entry['period_length']}")
    if report.pre_v4_core_gaps:
        print()
        print(
            f"{len(report.pre_v4_core_gaps):,} of them still miss something else the shared core asks for,\n"
            "which the v4 conversion script fills in and this run leaves alone:"
        )
        reasons = Counter(entry["detail"] for entry in report.pre_v4_core_gaps)
        for detail, count in reasons.most_common():
            print(f"    {count:>5,}  {detail}")
    if report.failures:
        print()
        print(f"FAILED ({len(report.failures)}):")
        for entry in report.failures[:20]:
            print(f"  {entry['path']}")
            print(f"      {entry['detail']}")
    if report.indexes_rebuilt or report.index_failures:
        print()
        print(f"Reserving-class indexes rebuilt:   {len(report.indexes_rebuilt):>7,}")
        for entry in report.index_failures:
            print(f"  {entry['project']} / {entry['reserving_class']}: {entry['detail']}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE, help="Workspace root (default: %(default)s)")
    parser.add_argument("--project", action="append", default=[], help="Project folder name; repeatable, default every project")
    parser.add_argument("--apply", action="store_true", help="Write the stored fields (default is a dry run)")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild every reserving-class index after writing")
    parser.add_argument("--workers", type=int, default=32, help="Sidecars read at once (default: %(default)s)")
    parser.add_argument("--report", default="", help="Write the full JSON report to this path")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    projects_root = workspace / "projects"
    if not projects_root.is_dir():
        print(f"Projects folder not found: {projects_root}", file=sys.stderr)
        return 2

    names = list(args.project)
    if not names:
        names = sorted(
            entry.name for entry in projects_root.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        )

    report = Report(workspace=str(workspace), apply=args.apply)
    for number, name in enumerate(names, start=1):
        project_dir = projects_root / name
        if not project_dir.is_dir():
            print(f"Project not found: {project_dir}", file=sys.stderr)
            return 2
        report.projects.append(name)
        # A whole-share walk runs for the best part of an hour, so say where it
        # has got to rather than going silent until the summary.
        print(f"[{number}/{len(names)}] {name}", file=sys.stderr, flush=True)
        backfill_project(project_dir, report, apply=args.apply, workers=args.workers)

    if args.rebuild_index and args.apply:
        rebuild_indexes(report)

    print_summary(report)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.payload(), indent=2), encoding="utf-8")
        print()
        print(f"Report: {report_path}")
    return 1 if report.failures or report.index_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
