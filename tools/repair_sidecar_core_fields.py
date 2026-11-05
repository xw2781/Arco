#!/usr/bin/env python3
"""Fill the core fields older ResQ imports left out of a sidecar, in place.

Until 2026-11-04 the ResQ import wrote plain triangles and vectors without
``status``, and some without ``method_type``, and a few method outputs were
saved with ``calculated: false``. The app reads such a file as Current with
no method type, but ``sidecar_core_contract.validate_sidecar_core`` refuses
it. This writes exactly what a reader already assumed: each missing field
takes its value from ``persisted_json_v4_upgrade.SIDECAR_CORE_DEFAULTS``, and a
sidecar that names the method which wrote it is marked calculated. Nothing
else changes -- no timestamp, no audit entry, no other field or its order --
and a file that passes the check is not touched, so the run is repeatable.

``status`` goes where every builder writes it, after ``updated_at`` (or
``modified_by``); ``method_type`` goes in front of ``data_format``, where the
import writes it. Nothing is written without ``--apply``.

Usage
-----
    py -3.10 tools/repair_sidecar_core_fields.py --root "E:\\XWSpace\\Arco Server" --project NJ_Annual_Prod_202605_Fake
    py -3.10 tools/repair_sidecar_core_fields.py --root ... --project ... --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from arcrho_api.dataset_index_contract import SIDECAR_DIR_NAME  # noqa: E402
from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.persisted_json_v4_upgrade import SIDECAR_CORE_DEFAULTS  # noqa: E402
from arcrho_api.sidecar_core_contract import validate_sidecar_core  # noqa: E402

# missing field -> the fields it is placed after, first one present wins; with
# none present it goes in front of the field named by _PLACE_BEFORE.
_PLACE_AFTER = {"status": ("updated_at", "modified_by")}
_PLACE_BEFORE = {"method_type": "data_format", "status": "precedents", "show_subtotal": "number_format"}


def _insert(payload: dict[str, Any], field: str, value: Any) -> dict[str, Any]:
    keys = list(payload)
    anchors = [key for key in _PLACE_AFTER.get(field, ()) if key in payload]
    if anchors:
        position = keys.index(anchors[0]) + 1
    elif _PLACE_BEFORE.get(field) in payload:
        position = keys.index(_PLACE_BEFORE[field])
    else:
        position = len(keys) - 1  # in front of audit_log, which is always last
    keys.insert(position, field)
    return {key: (value if key == field else payload[key]) for key in keys}


def repaired(payload: dict[str, Any]) -> dict[str, Any] | None:
    """*payload* with its core completed, or None when it already passes."""

    try:
        validate_sidecar_core(payload)
        return None
    except ValueError:
        pass
    fixed = dict(payload)
    for field, default in SIDECAR_CORE_DEFAULTS.items():
        if field not in fixed:
            fixed = _insert(fixed, field, default)
    if str(fixed.get("method_name") or "").strip():
        fixed["calculated"] = True
    validate_sidecar_core(fixed)  # anything else wrong is reported, not guessed at
    return fixed


def sidecar_files(project_dir: Path) -> list[Path]:
    data_dir = project_dir / "data"
    found: list[Path] = []
    for entry in sorted(os.scandir(data_dir), key=lambda item: item.name):
        if entry.is_dir() and not entry.name.startswith("."):
            folder = Path(entry.path) / SIDECAR_DIR_NAME
            if folder.is_dir():
                found.extend(sorted(folder.glob("*.json")))
    return found


def repair(path: Path, apply: bool) -> list[str] | None:
    """Repair one sidecar; returns the fields that changed, or None."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    fixed = repaired(payload)
    if fixed is None:
        return None
    if apply:
        temp = path.with_name(f"{path.name}.{uuid.uuid4()}.tmp")
        try:
            temp.write_text(persisted_json_text(fixed), encoding="utf-8", newline="\n")
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()
    return sorted(key for key in fixed if payload.get(key, object()) != fixed[key])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", required=True, help="server root that holds projects\\")
    parser.add_argument("--project", required=True)
    parser.add_argument("--apply", action="store_true", help="write the repair (default is a dry run)")
    parser.add_argument("--workers", type=int, default=16, help="files read at once (default %(default)s)")
    args = parser.parse_args(argv)

    project_dir = Path(args.root) / "projects" / args.project
    if not (project_dir / "data").is_dir():
        print(f"No project data folder at {project_dir}", file=sys.stderr)
        return 2
    paths = sidecar_files(project_dir)

    def run(path: Path) -> tuple[Path, list[str] | None, str]:
        try:
            return path, repair(path, args.apply), ""
        except Exception as err:  # noqa: BLE001 - reported, never skipped silently
            return path, None, f"{type(err).__name__}: {err}"

    changed: list[tuple[Path, list[str]]] = []
    failures: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for path, fields, error in pool.map(run, paths):
            if error:
                failures.append((path, error))
            elif fields:
                changed.append((path, fields))

    print(f"Project: {project_dir}")
    print(f"Sidecars scanned:  {len(paths):,}")
    print(f"Sidecars repaired: {len(changed):,}{'' if args.apply else ' (dry run, nothing written)'}")
    for path, fields in changed:
        print(f"  {', '.join(fields):28} {path.relative_to(project_dir)}")
    for path, error in failures:
        print(f"  FAILED  {path.relative_to(project_dir)}: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
