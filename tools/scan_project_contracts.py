#!/usr/bin/env python3
"""Report every file of a project that is not in the current format. Read only.

Each file is held to the canonical contract that owns it in
``python-api/src/arcrho_api``:

- a dataset sidecar to ``sidecar_core_contract.validate_sidecar_core``, and
  its ``csv_file`` to a CSV that exists;
- a method JSON to the normalizer of its kind, with ``require_complete``, which
  is what the app runs before it loads, saves or refreshes the method, so a
  stored result that disagrees with its own source snapshots is reported;
- a reserving-class ``index.json`` to ``dataset_index_contract.index_rebuild_reason``;
- the text of every JSON above to ``io.persisted_json_text``;
- leftovers nothing reads: ResQ-import staging folders, a class folder with no
  dataset, method or sidecar folder, backups at the project root, lock files,
  and empty files.

A problem is something the app refuses or a contract check fails on, and makes
the exit code 1. A notice is something the app repairs by itself the next time
it touches the file -- a DFM without ``curves_tab``, an index that is missing
or out of date -- and is listed without failing the run.

Usage
-----
    py -3.10 tools/scan_project_contracts.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake
    py -3.10 tools/scan_project_contracts.py --root ... --project ... --examples 10 --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend"))

from arcrho_api.bootstrap_contract import BST_JSON_FORMAT, normalize_bootstrap_method  # noqa: E402
from arcrho_api.bornhuetter_ferguson_contract import (  # noqa: E402
    BF_JSON_FORMAT,
    normalize_bornhuetter_ferguson_method,
)
from arcrho_api.cape_cod_contract import CC_JSON_FORMAT, normalize_cape_cod_method  # noqa: E402
from arcrho_api.dataset_index_contract import (  # noqa: E402
    BS_CRA_JSON_FORMAT,
    BS_SR_JSON_FORMAT,
    DATASET_DIR_NAME,
    INDEX_FILE_NAME,
    METHOD_DIR_NAME,
    RS_JSON_FORMAT,
    SIDECAR_DIR_NAME,
    decode_filename_segment,
    index_rebuild_reason,
    scan_folder_signature,
)
from arcrho_api.dfm_contract import DFM_JSON_FORMAT, normalize_dfm_method  # noqa: E402
from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.persisted_json_v4_upgrade import (  # noqa: E402
    METHOD_FORMAT_UPGRADES,
    UNCONVERTIBLE_METHOD_FORMATS,
)
from arcrho_api.sidecar_core_contract import validate_sidecar_core  # noqa: E402
from arcrho_api.stochastic_consolidation_contract import (  # noqa: E402
    SCON_JSON_FORMAT,
    normalize_stochastic_consolidation_method,
)
# The Result Selection normalizer is the one method contract that lives app-side.
from app_server.services.result_selection_service import (  # noqa: E402
    normalize_method_payload as normalize_result_selection_method,
)


STAGING_DIR_NAME = ".arcrho-resq-import-staging"
CLASS_FOLDERS = (DATASET_DIR_NAME, METHOD_DIR_NAME, SIDECAR_DIR_NAME)
BACKUP_NAME = re.compile(r"\.bak$|\.before[-_]", re.IGNORECASE)

KIND_SIDECAR = "sidecar"
KIND_INDEX = "index"
KIND_LEFTOVER = "leftover"


def _no_contract(payload: Mapping[str, Any]) -> Any:
    # Berquist Sherman has no Python contract; its shape is owned browser-side.
    return payload


# json_format -> (kind label, the check the app applies before it opens one).
METHOD_CONTRACTS: dict[str, tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    DFM_JSON_FORMAT: ("DFM method", normalize_dfm_method),
    BF_JSON_FORMAT: ("BF method", normalize_bornhuetter_ferguson_method),
    CC_JSON_FORMAT: ("CC method", normalize_cape_cod_method),
    BST_JSON_FORMAT: ("Bootstrap method", normalize_bootstrap_method),
    SCON_JSON_FORMAT: ("Stochastic Consolidation method", normalize_stochastic_consolidation_method),
    RS_JSON_FORMAT: ("RS method", lambda payload: normalize_result_selection_method(dict(payload))),
    BS_SR_JSON_FORMAT: ("BS SR method", _no_contract),
    BS_CRA_JSON_FORMAT: ("BS CRA method", _no_contract),
}
# Old stamps name the kind they were, so a dead file is reported under it.
_KIND_BY_OLD_FORMAT = {
    old: METHOD_CONTRACTS[new][0] for old, new in METHOD_FORMAT_UPGRADES.items()
}
_KIND_BY_OLD_FORMAT.update({
    "arcrho-dfm-method-by-tab-v1": "DFM method",
    "arcrho-bornhuetter-ferguson-method-by-tab-v2": "BF method",
})


def _long(path: str) -> str:
    """The form Windows accepts beyond 260 characters; a staged import nests deep."""

    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    return "\\\\?\\" + os.path.abspath(path)


def _error_text(error: Exception) -> str:
    detail = getattr(error, "detail", None)  # the app-side normalizer raises HTTPException
    return str(detail if detail is not None else error) or type(error).__name__


@dataclass
class Report:
    project_dir: str
    scanned: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    problems: dict[tuple[str, str], list[str]] = field(default_factory=lambda: defaultdict(list))
    notices: dict[tuple[str, str], list[str]] = field(default_factory=lambda: defaultdict(list))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _relative(self, path: str) -> str:
        return os.path.relpath(path, self.project_dir)

    def problem(self, kind: str, problem: str, path: str) -> None:
        with self.lock:
            self.problems[(kind, problem)].append(self._relative(path))

    def notice(self, kind: str, problem: str, path: str) -> None:
        with self.lock:
            self.notices[(kind, problem)].append(self._relative(path))

    def as_dict(self, examples: int) -> dict[str, Any]:
        def rows(source: Mapping[tuple[str, str], list[str]]) -> list[dict[str, Any]]:
            return [
                {"kind": kind, "problem": problem, "files": len(paths), "examples": sorted(paths)[:examples]}
                for (kind, problem), paths in sorted(source.items())
            ]

        return {
            "project_dir": self.project_dir,
            "scanned": dict(sorted(self.scanned.items())),
            "problems": rows(self.problems),
            "notices": rows(self.notices),
        }


def _read_text(path: str) -> str:
    with open(_long(path), "r", encoding="utf-8") as handle:
        return handle.read()


def _parse(report: Report, kind: str, path: str) -> Any:
    """The parsed file, or ``None`` after reporting why it could not be read."""

    try:
        text = _read_text(path)
        payload = json.loads(text)
    except (OSError, ValueError) as error:
        report.problem(kind, f"cannot be read: {type(error).__name__}", path)
        return None
    if persisted_json_text(payload) != text:
        report.problem(kind, "text is not in the persisted JSON layout", path)
    return payload


def _check_sidecar(report: Report, path: str, csv_names: set[str]) -> None:
    payload = _parse(report, KIND_SIDECAR, path)
    if payload is None:
        return
    try:
        validate_sidecar_core(payload)
    except Exception as error:  # noqa: BLE001 - every refusal is a finding
        report.problem(KIND_SIDECAR, _error_text(error), path)
    csv_file = str(payload.get("csv_file") or "").strip() if isinstance(payload, Mapping) else ""
    if csv_file and csv_file.casefold() not in csv_names:
        report.problem(KIND_SIDECAR, "csv_file names a CSV that does not exist", path)


def _check_method(report: Report, path: str) -> None:
    payload = _parse(report, "method", path)
    if not isinstance(payload, Mapping):
        if payload is not None:
            report.problem("method", "not a JSON object", path)
        return
    json_format = str(payload.get("json_format") or "").strip()
    contract = METHOD_CONTRACTS.get(json_format)
    if contract is None:
        kind = _KIND_BY_OLD_FORMAT.get(json_format, "method")
        if json_format in UNCONVERTIBLE_METHOD_FORMATS:
            report.problem(kind, f"dead format {json_format}", path)
        elif json_format in METHOD_FORMAT_UPGRADES:
            report.problem(kind, f"pre-v4 format {json_format}", path)
        else:
            report.problem(kind, f"unknown format {json_format or '(none)'}", path)
        return
    kind, normalize = contract
    try:
        normalize(payload)
    except Exception as error:  # noqa: BLE001
        report.problem(kind, _error_text(error), path)
    if json_format == DFM_JSON_FORMAT and "curves_tab" not in payload:
        report.notice(kind, "no curves_tab (filled on next save)", path)


def _check_index(report: Report, project_name: str, rc_dir: str) -> None:
    path = os.path.join(rc_dir, INDEX_FILE_NAME)
    if not os.path.isfile(_long(path)):
        report.notice(KIND_INDEX, "missing (rebuilt on read)", path)
        return
    payload = _parse(report, KIND_INDEX, path)
    if payload is None:
        return
    reason = index_rebuild_reason(
        payload,
        expected_project_name=project_name,
        expected_reserving_class=decode_filename_segment(os.path.basename(rc_dir)),
        expected_folder_signature=scan_folder_signature(_long(rc_dir)).signature,
    )
    if reason:
        report.notice(KIND_INDEX, f"not current: {reason} (rebuilt on read)", path)


def _listing(folder: str) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(_long(folder)) as entries:
            return list(entries)
    except (FileNotFoundError, NotADirectoryError):
        return []


def _walk_leftovers(report: Report) -> None:
    """Lock files and empty files anywhere; backups at the project root."""

    for directory, _dirs, files in os.walk(_long(report.project_dir)):
        for name in files:
            path = os.path.join(directory, name)
            if path.startswith("\\\\?\\"):
                path = path[4:]
            if name.casefold().endswith(".lock"):
                report.problem(KIND_LEFTOVER, "lock file", path)
            elif os.path.getsize(_long(path)) == 0:
                report.problem(KIND_LEFTOVER, "empty file", path)
    for entry in _listing(report.project_dir):
        if entry.is_file() and BACKUP_NAME.search(entry.name):
            report.problem(KIND_LEFTOVER, "backup at the project root", os.path.join(report.project_dir, entry.name))


def _count_files(folder: str) -> list[str]:
    found: list[str] = []
    for directory, _dirs, files in os.walk(_long(folder)):
        found.extend(os.path.join(directory, name) for name in files)
    return found


def scan_project(project_dir: str, *, max_workers: int = 16) -> Report:
    project_dir = os.path.abspath(project_dir)
    report = Report(project_dir)
    project_name = os.path.basename(project_dir)
    data_dir = os.path.join(project_dir, "data")
    jobs: list[tuple[Callable[..., None], tuple[Any, ...]]] = []
    for entry in sorted(_listing(data_dir), key=lambda item: item.name.casefold()):
        if not entry.is_dir():
            continue
        rc_dir = os.path.join(data_dir, entry.name)
        if entry.name == STAGING_DIR_NAME:
            for path in _count_files(rc_dir):
                report.problem(KIND_LEFTOVER, "ResQ-import staging folder", path[4:] if path.startswith("\\\\?\\") else path)
            continue
        if entry.name.startswith("."):
            continue
        listings = {name: _listing(os.path.join(rc_dir, name)) for name in CLASS_FOLDERS}
        if not any(os.path.isdir(_long(os.path.join(rc_dir, name))) for name in CLASS_FOLDERS):
            report.problem(KIND_LEFTOVER, "class folder with no datasets, methods or sidecars", rc_dir)
            continue
        csv_names = {item.name.casefold() for item in listings[DATASET_DIR_NAME] if item.is_file()}
        for item in listings[SIDECAR_DIR_NAME]:
            if item.is_file() and item.name.casefold().endswith(".json"):
                report.scanned[KIND_SIDECAR] += 1
                jobs.append((_check_sidecar, (report, os.path.join(rc_dir, SIDECAR_DIR_NAME, item.name), csv_names)))
        for item in listings[METHOD_DIR_NAME]:
            if item.is_file() and item.name.casefold().endswith(".json"):
                report.scanned["method"] += 1
                jobs.append((_check_method, (report, os.path.join(rc_dir, METHOD_DIR_NAME, item.name))))
        report.scanned[KIND_INDEX] += 1
        jobs.append((_check_index, (report, project_name, rc_dir)))
    # Bounded parallel reads: over the share every open is a round trip.
    with ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="arcrho-contract-scan") as pool:
        for future in [pool.submit(check, *args) for check, args in jobs]:
            future.result()
    _walk_leftovers(report)
    return report


def print_report(data: Mapping[str, Any]) -> None:
    print(f"Project: {data['project_dir']}")
    print("Scanned: " + ", ".join(f"{count} {kind}" for kind, count in data["scanned"].items()))
    for title, rows in (("Problems", data["problems"]), ("Notices (self-healing)", data["notices"])):
        print(f"\n{title}: {sum(row['files'] for row in rows)} findings")
        for row in rows:
            print(f"  {row['files']:>5}  {row['kind']}: {row['problem']}")
            for example in row["examples"]:
                print(f"           {example}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", required=True, help="server root that holds projects\\")
    parser.add_argument("--project", required=True)
    parser.add_argument("--examples", type=int, default=3, help="example paths per finding (default 3)")
    parser.add_argument("--workers", type=int, default=16, help="parallel file reads (default 16)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    project_dir = os.path.join(args.root, "projects", args.project)
    if not os.path.isdir(project_dir):
        print(f"No project folder at {project_dir}", file=sys.stderr)
        return 2
    data = scan_project(project_dir, max_workers=args.workers).as_dict(args.examples)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print_report(data)
    return 1 if data["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
