"""Write the Fake project's values the Export macro does not send into ResQ.

The Export macro (step 10 of docs/plans/completed/fake_project_refresh.md) sends Arco's
input datasets and methods. Two kinds of Arco value never reach ResQ through it:

- **ResQ-stored triangles** (``source`` ``resq_triangle``, ``source_kind``
  ``engine``): the "Adjusted" / ad hoc triangles step 6 rescaled. The export
  leaves every engine-kind dataset to ResQ. They are stored in ResQ at Arco's
  origin length and a monthly development, so the columns sit at their true ages.
- **Inputs ResQ calculates**: a prior-quarter vector such as ``C 81`` is an
  Arco input but a ResQ formula reading another vector of the class
  (``"C 91 - Current Qtr Indicated - Feb 2026"``). The export skips it. When the
  formula is a single reference to a plain ResQ vector, the Arco values are
  written into that vector, re-stored at Arco's period, so the formula gives
  them back. Any other formula is listed and left alone.

Vectors go through the Export macro's own writer
(``ResQReservingClassExporter._write_vector_values``) and triangles through its
length helpers, so the stored and display lengths follow the export's rules.

Server PC only (ResQ COM), outside the sandbox; writes only to the Fake project::

    py -3.10 tools/push_fake_values_to_resq.py            # survey, writes nothing
    py -3.10 tools/push_fake_values_to_resq.py --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python-api" / "migration"))
sys.path.insert(0, str(REPO / "python-api" / "macros"))

from resq_migration import core as migration  # noqa: E402
import import_resq_reserving_classes as batch_import  # noqa: E402

PROJECT = "NJ_Annual_Prod_202605_Fake"
SERVER_ROOT = Path(r"E:\ArcRho Server")
CONFIG = SERVER_ROOT / "config" / "config.json"
SINGLE_REFERENCE = re.compile(r'^\s*"([^"]+)"\s*$')


def _exporter_module():
    spec = importlib.util.spec_from_file_location(
        "export_reserving_class_to_resq", REPO / "python-api" / "macros" / "export_reserving_class_to_resq.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sidecars(rc_path: str) -> list[tuple[dict, Path]]:
    folder = SERVER_ROOT / "projects" / PROJECT / "data" / migration._encode_rc_folder(rc_path)
    found = []
    for path in sorted((folder / "sidecars").glob("*.json")):
        sidecar = json.loads(path.read_text(encoding="utf-8"))
        csv_path = folder / migration.DATASET_CACHE_DIR / str(sidecar.get("csv_file") or "")
        found.append((sidecar, csv_path))
    return found


def _plan_class(exporter, module, rc_path: str) -> list[dict]:
    plan = []
    for sidecar, csv_path in _sidecars(rc_path):
        name = module._clean_label(sidecar.get("dataset_name"))
        source = str(sidecar.get("source") or "")
        source_kind = str(sidecar.get("source_kind") or "").casefold()
        is_triangle = str(sidecar.get("data_format") or "").casefold() == "triangle"
        if not csv_path.is_file():
            continue
        if source == "resq_triangle" and source_kind == "engine" and is_triangle:
            target = exporter._find_triangle(name)
            if target is None:
                plan.append({"name": name, "action": "skip", "why": "not in ResQ"})
            elif bool(target.Calculated):
                plan.append({"name": name, "action": "skip", "why": f"calculated in ResQ: {target.Formula}"})
            else:
                plan.append({"name": name, "action": "triangle", "target": target, "sidecar": sidecar,
                             "csv": csv_path})
            continue
        if source_kind != "input" or is_triangle:
            continue
        resq = exporter._find_vector(name)
        if resq is None or not bool(resq.Calculated):
            continue  # the Export macro writes it, or it is missing in ResQ
        formula = str(resq.Formula or "")
        match = SINGLE_REFERENCE.match(formula)
        reference = exporter._find_vector(match.group(1)) if match else None
        if reference is None or bool(reference.Calculated):
            plan.append({"name": name, "action": "skip", "why": f"ResQ formula: {formula}"})
            continue
        arco_period = int(sidecar.get("stored_period_length") or sidecar.get("period_length") or 0)
        plan.append({"name": name, "action": "vector", "target": reference, "target_name": match.group(1).strip(),
                     "csv": csv_path, "period": arco_period})
    return plan


def _write_vector_at(exporter, vector, values, period: int) -> None:
    """Re-store *vector* at Arco's period and write Arco's values into it.

    ``ClearData`` empties the vector and moves its store to the display period,
    and while it is empty the store follows the display (rules E1 / F1 of
    docs/reference/resq_stored_and_display_lengths.md). So it is cleared, shown
    at Arco's period, written by index through the Export macro's writer, and
    shown at its old period again when that period is a multiple of the new
    store (ResQ refuses a display finer than the store).
    """
    display = int(vector.PeriodLength)
    vector.ClearData()
    vector.PeriodLength = period
    exporter._write_vector_values(vector, values)
    if int(vector.PeriodLength) != display and display % period == 0:
        vector.PeriodLength = display
        vector.Save()


def _write_triangle_monthly(exporter, triangle, sidecar, values, name):
    """Store *triangle* at Arco's origin length and a monthly development, with Arco's values.

    Arco reads the columns at their true ages (5m, 17m, ... at a May valuation).
    A ResQ triangle stored at development 12 puts them at 12, 24, ..., so a ResQ
    DFM on it develops the latest value along an interpolated monthly pattern
    (memory ``resq-dfm-mid-period-valuation``). Stored at development 1, the same
    grid written at the display lands at the true ages (rule B2 of
    docs/reference/resq_stored_and_display_lengths.md), so both read it alike.
    Order per rules A3/A4/B8: clear, show at Arco's lengths, set the development
    store, write by index, save.
    """
    origin_length = int(sidecar.get("origin_length") or 12)
    development_length = int(sidecar.get("development_length") or origin_length)
    triangle.ClearData()
    if int(triangle.StoredOriginLength) != origin_length:
        triangle = exporter._empty_and_reopen(triangle, name)
    exporter._show_triangle_at(triangle, origin_length, development_length)
    if int(triangle.StoredDevelopmentLength) != 1:
        triangle.StoredDevelopmentLength = 1
    for origin_index in range(1, min(int(triangle.OriginCount), len(values)) + 1):
        row = values[origin_index - 1]
        width = exporter._triangle_row_width(triangle, origin_index)
        for development_index in range(1, min(width, len(row)) + 1):
            if row[development_index - 1] is not None:
                triangle.SetValuesByIndex(origin_index, development_index, float(row[development_index - 1]))
    triangle.Save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write; without it the plan is only printed")
    parser.add_argument("--rc", action="append", help="only classes whose path contains this text")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    module = _exporter_module()
    credentials = json.loads(CONFIG.read_text(encoding="utf-8"))["resq"]
    rc_paths = [p for p in batch_import.RC_PATHS
                if not args.rc or any(t.casefold() in p.casefold() for t in args.rc)]
    for rc_path in rc_paths:
        exporter = module.ResQReservingClassExporter(
            migration, arcrho_project_name=PROJECT, rc_path=rc_path, server_root=SERVER_ROOT,
            connection_name=credentials["connection_name"], resq_user_name=credentials["user_name"],
            resq_password=credentials["password"])
        exporter.connect()
        try:
            print(f"== {rc_path}")
            for item in _plan_class(exporter, module, rc_path):
                if item["action"] == "skip":
                    print(f"  skip   {item['name']}: {item['why']}")
                    continue
                label = item["name"] if item["action"] == "triangle" else f"{item['name']} -> {item['target_name']}"
                if not args.apply:
                    print(f"  would  {item['action']} {label}")
                    continue
                values = module._read_csv_matrix(item["csv"])
                # A triangle write can reload the class (UnloadChildren), which frees
                # every wrapper the plan holds, so each target is looked up again.
                try:
                    if item["action"] == "triangle":
                        target = exporter._find_triangle(item["name"])
                        _write_triangle_monthly(exporter, target, item["sidecar"], values, item["name"])
                    else:
                        target = exporter._find_vector(item["target_name"])
                        _write_vector_at(exporter, target, values, item["period"])
                except module.ExportSkipped as skip:
                    print(f"  skip   {label}: {skip}")
                    continue
                print(f"  wrote  {item['action']} {label}")
        finally:
            exporter.disconnect()


if __name__ == "__main__":
    main()
