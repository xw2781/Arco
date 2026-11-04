"""Build the ABC_Group_Quarterly_Review_202608 demo project on the Server PC.

The project is a quarterly reserve review of ABC Insurance Group, a fictional
insurer whose source tables come from ``arcrho_api.demo_data.abc_group`` (the
generator that ships with the app). Its 17 reserving classes and their method
templates are taken from NJ_Annual_Prod_202608_Fake and renamed to generic
companies, channels and coverages.

Each step is a subcommand and can be re-run:

  scaffold   create the project through the running app, write the four
             import tables into the project, import them as one combined
             source, and save dates, field mapping, dataset types,
             reserving-class types and data processing rules
  templates  copy the 17 template classes with renamed paths, dataset names
             and authors, without notes, audit history or outside links
  refresh    regenerate every Engine dataset from the imported source and
             recalculate the methods that read them
  inputs     write the hand-entered priors, patterns and adjusted triangles
  methods    set DFM, Result Selection and other method selections and notes
  finish     give every author label the demo author and check the project

The app routes own every save after the template copy, so sidecars, indexes,
dependency graphs and propagation are written by ArcRho itself.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "python-api" / "src"))

from arcrho_api.bornhuetter_ferguson_contract import recalculate_bornhuetter_ferguson_method  # noqa: E402
from arcrho_api.cape_cod_contract import recalculate_cape_cod_method  # noqa: E402
from arcrho_api.demo_data import abc_group  # noqa: E402
from arcrho_api.dfm_contract import recalculate_dfm_method  # noqa: E402
from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.ui import _request_json  # noqa: E402

PROJECT = "ABC_Group_Quarterly_Review_202608"
TEMPLATE = "NJ_Annual_Prod_202608_Fake"
OLD_TEMPLATE_NAMES = ("NJ_Annual_Prod_202608_Fake", "NJ_Annual_Prod_202605_Fake")
REGISTRY_FOLDER = "Test\\Demos"
SERVER_ROOT = Path(r"E:\ArcRho Server")
PROJECTS_DIR = SERVER_ROOT / "projects"
IMPORT_TABLES_DIR = "source/import_tables"
DEMO_AUTHOR = "Jordan Lee"
AUTHOR_FIELDS = frozenset({"modified_by", "user", "imported_by", "chosen_by", "updated_by"})
BS = "\\"

# Class paths stay short on purpose: the project name is long, and every
# ArcRho write adds a 41-character temporary suffix to a file name under
# the Windows 260-character path limit.
CLASS_MAP = {
    r"PRNJ - PA\PA\NY\Direct Group\BI Total": r"ABC Auto\PPA\NY\Exclusive\BI Total",
    r"PRNJ - PA\PA\NY\Direct Group\MP+PIP": r"ABC Auto\PPA\NY\Exclusive\Medical and PIP",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\BI Total": r"ABC Auto\PPA\PA+CT\Exclusive\BI Total",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\MP+PIP": r"ABC Auto\PPA\PA+CT\Exclusive\Medical and PIP",
    r"PRNJ - PA\PA\All States\Direct Group\PD+UMPD": r"ABC Auto\PPA\All States\Exclusive\PD Total",
    r"PRNJ - PA\PA\All States\Direct Group\COL": r"ABC Auto\PPA\All States\Exclusive\Collision",
    r"PRNJ - PA\PA\All States\Direct Group\CMPxCAT": r"ABC Auto\PPA\All States\Exclusive\Comp ex Cat",
    r"PRNJ - PA\PA\NJ\Direct Group\MP+PIP": r"ABC Auto\PPA\NJ\Exclusive\Medical and PIP",
    r"PRNJ - PA\PA\NJ\Direct Group\BIR51+UMBIR51": r"ABC Auto\PPA\NJ\Exclusive\BI Limited Tort",
    r"PRNJ - PA\PA\NJ\Direct Group\BIx51+UMBIx51": r"ABC Auto\PPA\NJ\Exclusive\BI Full Tort",
    r"HPPREF\HO+DF\NJ\Legacy\HOL": r"ABC Home\HO+DF\NJ\Legacy\Home Liability",
    r"HPPREF\HO+DF\NJ\Legacy\HOPxCAT": r"ABC Home\HO+DF\NJ\Legacy\Home Property ex Cat",
    r"Rider\MC\All States\Direct Group\BI+PIP": r"ABC Moto\MC\All States\Exclusive\Injury Total",
    r"Rider\MC\All States\Direct Group\PD+UMPD": r"ABC Moto\MC\All States\Exclusive\PD Total",
    r"Rider\MC\All States\Direct Group\PhysDxCat": r"ABC Moto\MC\All States\Exclusive\Phys Dmg ex Cat",
    r"PRNJ - PA\PA\MA\Direct Group\BI Total": r"ABC Auto\PPA\MA\Exclusive\BI Total",
    r"PRNJ - PA\PA\MA\Direct Group\MP+PIP": r"ABC Auto\PPA\MA\Exclusive\Medical and PIP",
}
CLASSES = tuple(CLASS_MAP.values())

# The demo imports full-year premium and exposure, so the template's remaining
# budget types and the totals that added them go; their readers read the
# earned figures instead.
DATASET_RENAMES = {"Total Earned Premium": "Earned Premium", "Total Earned Exposure": "Earned Exposure"}
DROPPED_TYPES = frozenset({"Remaining Budget Premium", "Remaining Budget Exposure", *DATASET_RENAMES})
FORMULA_REWRITES = (
    ("(Earned Premium + Remaining Budget Premium)", "Earned Premium"),
    ("(Earned Exposure + Remaining Budget Exposure)", "Earned Exposure"),
)
# ResQ-era names shortened to fit the path budget and drop the "*" marks,
# applied in this order to every dataset and method name that contains them.
NAME_EDITS = (
    ("Net Loss--Incurred Adjusted***", "Net Loss--Incurred Adj 3"),
    ("Net Loss--Incurred Adjusted**", "Net Loss--Incurred Adj 2"),
    ("Net Loss--Incurred Adjusted*", "Net Loss--Incurred Adj 1"),
    ("Net Loss--Incurred Adjusted", "Net Loss--Incurred Adj"),
    ("Net Loss--Paid Adjusted*", "Net Loss--Paid Adj 1"),
    ("Net Loss--Paid Adjusted", "Net Loss--Paid Adj"),
    ("Gross Loss--Incurred Adjusted*", "Gross Loss--Incurred Adj 1"),
    ("Severity--Adjusted Net Incurred", "Severity--Adj Net Incurred"),
    (" - B&S Case Reserve Adequacy Adjustment", " - B&S Case Adj"),
    (" - B&S Settlement Rate Adjustment", " - B&S Settle Adj"),
    (" per Earned Exposure", " per Exposure"),
    ("P 01 Recoveries--Expected % of Selected Ultimate Gross Loss - Indicated",
     "P 01 Recoveries--Expected % of Ultimate Gross Loss"),
    ("P 02 Salvage--Expected % of Ultimate Gross Loss - Indicated", "P 02 Salvage--Expected % of Ultimate Gross Loss"),
    ("P 03 Subro--Expected % of Ultimate Gross Loss - Indicated", "P 03 Subro--Expected % of Ultimate Gross Loss"),
    ("P 04 A-ALAE--Expected % of Ultimate Gross Loss - Indicated", "P 04 A ALAE--Expected % of Ultimate Gross Loss"),
    ("P 04 B-ALAE--Expected % of Ultimate Net Loss - Indicated", "P 04 B ALAE--Expected % of Ultimate Net Loss"),
)


def demo_name(name: str) -> str:
    """The demo's name for a template dataset, type or method name."""
    text = " ".join(str(name).split())
    if text in DATASET_RENAMES:
        return DATASET_RENAMES[text]
    for old, new in NAME_EDITS:
        text = text.replace(old, new)
    return text


def demo_formula(formula: str) -> str:
    """Rename the dataset names a formula quotes or brackets."""
    text = re.sub(r'"([^"]*)"', lambda m: '"' + demo_name(m.group(1)) + '"', str(formula or ""))
    text = re.sub(r"\[([^\]]*)\]", lambda m: "[" + demo_name(m.group(1)) + "]"
                  if not re.fullmatch(r"[0-9: ,]*", m.group(1)) else m.group(0), text)
    for old, new in FORMULA_REWRITES:
        text = text.replace(old, new)
    return text


def encode_file_name(name: str) -> str:
    return "".join(f"_%{ord(ch):02X}_" if ch in '\\/*:?"<>|' else ch for ch in name)


def decode_file_name(name: str) -> str:
    return re.sub(r"_%([0-9A-F]{2})_", lambda m: chr(int(m.group(1), 16)), name)


DATASET_TYPE_COLUMNS = ["Name", "Data Format", "Category", "Calculated", "Formula"]

SOURCE_MEASURES = {
    "gross_paid": "Gross Loss--Paid",
    "expense": "ALAE--Paid",
    "salvage": "Salvage--Received",
    "subro": "Subro--Received",
    "reserve": "Gross Loss--OS",
    "recovery": "Recoveries--Received",
    "net_incurred": "Net Loss--Incurred",
    "gross_incurred": "Gross Loss--Incurred",
    "net_incurred_capped_50k": "Net Loss--Incurred Capped at 50K",
    "net_paid_capped_50k": "Net Loss--Paid Capped at 50K",
    "net_incurred_capped_100k": "Net Loss--Incurred Capped at 100K",
    "net_paid_capped_100k": "Net Loss--Paid Capped at 100K",
    "net_incurred_capped_1000k": "Net Loss--Incurred Capped at 1M",
    "net_paid_capped_1000k": "Net Loss--Paid Capped at 1M",
    "CWP": "Claim Counts--CWP",
    "CWOP": "Claim Counts--CWOP",
    "CWP_ex_50k": "Claim Counts--CWP Excess of 50K",
    "CWP_ex_100k": "Claim Counts--CWP Excess of 100K",
    "CWP_ex_1000k": "Claim Counts--CWP Excess of 1M",
    "reported": "Claim Counts--Reported",
    "reported_ex_50k": "Claim Counts--Reported Excess of 50K",
    "reported_ex_100k": "Claim Counts--Reported Excess of 100K",
    "reported_ex_1000k": "Claim Counts--Reported Excess of 1M",
    "Earned_Premium": "Earned Premium",
    "Earned_Exposure": "Earned Exposure",
}
KEY_FIELDS = ("CO_CD", "PROD_CD", "STATE_CD", "CHANNEL", "Coverage")

# An aggregate coverage would add the same cars or homes once per coverage, so
# its exposure keeps the members that count each unit once.
EXPOSURE_RULES = (
    ("Bodily Injury", ["BI Total", "Injury Total", "Auto Liability Total"],
     ["Bodily Injury", "Bodily Injury Limited Tort"]),
    ("Bodily Injury full tort", ["BI Full Tort"], ["Bodily Injury"]),
    ("Bodily Injury limited tort", ["BI Limited Tort"], ["Bodily Injury Limited Tort"]),
    ("Property Damage", ["PD Total"], ["Property Damage"]),
    ("Comprehensive", ["Comp ex Cat", "Phys Dmg ex Cat"], ["Comprehensive"]),
    ("Home Property", ["Home Total ex Cat"], ["Home Property"]),
)


# ---------------------------------------------------------------- app client


def call(path: str, payload: dict | None = None, *, timeout: float = 120.0, method: str | None = None) -> dict:
    """One app request; a 423 class hold is waited out, anything else raises."""
    deadline = time.monotonic() + 1800
    while True:
        try:
            return _request_json(path, method=method or ("POST" if payload is not None else "GET"),
                                 payload=payload, timeout_sec=timeout)
        except Exception as err:  # noqa: BLE001 - only a hold is worth waiting out
            text = str(err)
            if ("(423)" not in text and "(503)" not in text) or time.monotonic() > deadline:
                raise
            time.sleep(3)


def get(path: str, **params: Any) -> dict:
    from urllib.parse import urlencode

    return call(f"{path}?{urlencode(params)}" if params else path)


def hosted_save(route: str, payload: dict, *, timeout: float = 900.0) -> dict:
    """The app's two-step save: plan the dependents, then save against that plan."""
    plan = call(f"{route}/plan", payload, timeout=timeout)
    fingerprint = str(plan.get("plan_fingerprint") or plan.get("fingerprint") or "")
    return call(route, {**payload, "plan_fingerprint": fingerprint}, timeout=timeout)


def project_dir() -> Path:
    return PROJECTS_DIR / PROJECT


def class_dir(project: str, reserving_class: str) -> Path:
    return PROJECTS_DIR / project / "data" / reserving_class.replace(BS, "_%5C_")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temp.write_text(persisted_json_text(payload), encoding="utf-8")
    os.replace(temp, path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def wait_for_job(status_path: str, job_id: str, label: str, *, timeout: float = 7200) -> dict:
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        status = get(status_path, project_name=PROJECT, job_id=job_id)
        state = str(status.get("status") or "")
        progress = json.dumps(status.get("progress") or {})[:160]
        if f"{state} {progress}" != last:
            print(f"  {label}: {state} {progress}", flush=True)
            last = f"{state} {progress}"
        if state in ("success", "error", "cancelled"):
            if state != "success":
                print(f"  ! {label} ended {state}: {json.dumps(status)[:1500]}")
            return status
        if time.monotonic() > deadline:
            raise TimeoutError(f"{label} did not finish: {status}")
        time.sleep(5)


# ---------------------------------------------------------------- scaffold


def combined_source_spec() -> dict:
    tables_dir = project_dir() / IMPORT_TABLES_DIR
    ids = {"Loss": "t1", "Claim Counts": "t2", "Premium": "t3", "Exposure": "t4"}
    tables = [
        {"id": ids[name], "nickname": name, "source_type": "csv", "csv_path": str(tables_dir / file_name)}
        for name, file_name in abc_group.TABLE_FILES.items()
    ]
    keys = [{"name": field, "map": {tid: {"column": field} for tid in ids.values()}} for field in abc_group.KEY_COLUMNS]
    keys.append({"name": "sys_yrmo", "map": {"t1": {"column": "sys_yrmo"}, "t2": {"column": "sys_yrmo"},
                                             "t3": {"fill": "0"}, "t4": {"fill": "0"}}})
    return {"tables": tables, "keys": keys, "rows": {"t2": "all", "t3": "all", "t4": "all"},
            "exclude": {}, "rename": {}}


def field_mapping_rows() -> list[dict]:
    rows = [{"field_name": field, "significance": "Reserving Class", "level": level}
            for level, field in enumerate(KEY_FIELDS, start=1)]
    rows += [{"field_name": "acc_yrmo", "significance": "Origin Date"},
             {"field_name": "sys_yrmo", "significance": "Development Date"}]
    rows += [{"field_name": field, "significance": "Dataset", "dataset_type": name}
             for field, name in SOURCE_MEASURES.items()]
    return rows


def template_dataset_type_rows(used_names: set[str]) -> list[list]:
    template = read_json(PROJECTS_DIR / TEMPLATE / "dataset_types.json")
    columns = template["columns"]
    index = {name: columns.index(name) for name in DATASET_TYPE_COLUMNS}
    source_types = set(SOURCE_MEASURES.values())
    rows = []
    for row in template["rows"]:
        # demo_name also collapses the doubled and trailing spaces ResQ left in
        # a few type names; the instances already use single spaces.
        raw_name = " ".join(str(row[index["Name"]]).split())
        name = demo_name(raw_name)
        if raw_name in DROPPED_TYPES or (name not in used_names and name not in source_types):
            continue
        calculated = bool(row[index["Calculated"]])
        formula = demo_formula(row[index["Formula"]]) if calculated else ""
        rows.append([name, row[index["Data Format"]], row[index["Category"]], calculated, formula])
    return rows


def used_dataset_types() -> set[str]:
    used = set()
    for old in CLASS_MAP:
        for path in (class_dir(TEMPLATE, old) / "sidecars").glob("*.json"):
            sidecar = read_json(path)
            if sidecar.get("dataset_type") not in DROPPED_TYPES or sidecar.get("dataset_type") in DATASET_RENAMES:
                used.add(demo_name(sidecar.get("dataset_type") or ""))
    return {name for name in used if name}


def reserving_class_type_rows() -> list[list]:
    return [[name, str(level), formula] for name, level, formula in abc_group.RESERVING_CLASS_AGGREGATES]


def processing_rules() -> list[dict]:
    rules = []
    for label, classes, members in EXPOSURE_RULES:
        rules.append({
            "id": "earned-exposure-keep-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
            "name": f"Earned_Exposure - keep {label}",
            "enabled": True,
            "target": {"source_measure": "Earned_Exposure"},
            "request_conditions": {"all": [{"field": "Coverage", "operator": "in", "level": 5, "value": classes}]},
            "row_conditions": {"all": []},
            "action": {"type": "keep_members", "field": "Coverage", "members": members, "level": 5},
        })
    return rules


def register_project() -> None:
    registry = get("/project_settings/project_map")
    folders = [str(v) for v in registry.get("folders", []) if str(v).strip()]
    paths = [str(v) for v in registry.get("project_paths", []) if str(v).strip()]
    if REGISTRY_FOLDER.casefold() not in {f.casefold() for f in folders}:
        folders.append(REGISTRY_FOLDER)
    if not any(p.split(BS)[-1].casefold() == PROJECT.casefold() for p in paths):
        paths.append(f"{REGISTRY_FOLDER}{BS}{PROJECT}")
    call("/project_settings/project_map", {"folders": folders, "project_paths": paths,
                                            "expected_revision": registry.get("revision", 0)})


def step_scaffold(args: argparse.Namespace) -> None:
    if not project_dir().is_dir():
        created = call("/project_settings/project_map/create_project_folder", {"name": PROJECT})
        print(f"Created {created.get('created_folder')}")
    tables = abc_group.generate(args.seed)
    written = abc_group.write_tables(tables, project_dir() / IMPORT_TABLES_DIR)
    print(f"Wrote {', '.join(p.name for p in written.values())}: {tables.summary()}")
    call("/source_table/combined/save", {"project_name": PROJECT, "combined": combined_source_spec()})
    imported = call("/source_table/combined/import", {"project_name": PROJECT}, timeout=1800)
    print(f"Imported the combined source: {json.dumps(imported)[:300]}")
    call("/general_settings", {"project_name": PROJECT, "origin_start_date": "201701",
                               "origin_end_date": "202612", "development_end_date": "202608",
                               "auto_generated": False})
    call("/field_mapping", {"project_name": PROJECT, "rows": field_mapping_rows()}, timeout=600)
    save_dataset_types(template_dataset_type_rows(used_dataset_types()))
    call("/reserving_class_types", {"project_name": PROJECT, "columns": ["Name", "Level", "Formula"],
                                    "rows": reserving_class_type_rows()}, timeout=600)
    save_processing_rules(processing_rules())
    register_project()
    print(f"Registered {PROJECT} under {REGISTRY_FOLDER}")


def save_dataset_types(rows: list[list]) -> None:
    request_id = uuid.uuid4().hex
    payload = {"project_name": PROJECT, "columns": DATASET_TYPE_COLUMNS, "rows": rows, "request_id": request_id}
    answer = call("/dataset_types", payload, timeout=600)
    if answer.get("applied") == "plan":
        plan = {k: v for k, v in answer.items() if k not in ("ok", "applied", "count")}
        answer = call("/dataset_types", {**payload, "plan": plan}, timeout=600)
    if answer.get("applied") == "job":
        wait_for_job("/dataset_types/change_job/status", str(answer.get("job_id") or request_id), "dataset types")
    print(f"Saved {len(rows)} dataset types ({answer.get('applied')})")


def save_processing_rules(rules: list[dict]) -> None:
    current = get("/data_processing_rules", project_name=PROJECT)
    data = {"json_format": "arcrho-data-processing-rules-v1", "rules": rules}
    request_id = uuid.uuid4().hex
    answer = call("/data_processing_rules/save_job", {
        "project_name": PROJECT, "expected_revision": int(current.get("revision") or current.get("data", {}).get("revision") or 0),
        "data": data, "request_id": request_id}, timeout=600)
    wait_for_job("/data_processing_rules/save_job/status", str(answer.get("job_id") or request_id), "processing rules")
    print(f"Saved {len(rules)} data processing rules")


# ---------------------------------------------------------------- templates


def rewrite_value(value: Any, renames: dict[str, str]) -> Any:
    """Rename paths, the project and dataset names wherever a string is one."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key in ("formula", "reference") and isinstance(child, str):
                out[key] = demo_formula(child)
            else:
                out[renames.get(key, demo_name(key) if key != demo_name(key) else key)] = rewrite_value(child, renames)
        return out
    if isinstance(value, list):
        return [rewrite_value(v, renames) for v in value]
    if isinstance(value, str):
        return renames.get(value) or demo_name(value) if value.strip() else value
    return value


def _dedupe_graph(entries: Any) -> Any:
    if not isinstance(entries, list):
        return entries
    seen, out = set(), []
    for entry in entries:
        key = json.dumps(entry, sort_keys=True)
        if key not in seen and not (isinstance(entry, dict) and entry.get("dataset_name") in DROPPED_TYPES):
            seen.add(key)
            out.append(entry)
    return out


def _strip_notes(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if key in ("notes", "notes_source") and isinstance(child, str):
                out[key] = ""
            elif key == "cell_notes" and isinstance(child, dict):
                out[key] = {name: {} for name in child}
            else:
                out[key] = _strip_notes(child)
        return out
    if isinstance(value, list):
        return [_strip_notes(v) for v in value]
    return value


def _set_authors(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (DEMO_AUTHOR if k in AUTHOR_FIELDS and isinstance(v, str) and v else _set_authors(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_set_authors(v) for v in value]
    return value


DEAD_BF_FORMAT = "arcrho-bornhuetter-ferguson-method-by-tab-v2"


def _bf_donors() -> list[dict]:
    """Current-format BF methods of the template classes, renamed, to rebuild retired ones from."""
    donors = []
    for old, new in CLASS_MAP.items():
        renames = {old: new, **{name: PROJECT for name in OLD_TEMPLATE_NAMES}, **DATASET_RENAMES}
        for path in sorted((class_dir(TEMPLATE, old) / "methods").glob("BF@*.json")):
            payload = read_json(path)
            if payload.get("json_format") != DEAD_BF_FORMAT and payload["method_tab"].get("prior_datasets"):
                donors.append(rewrite_value(payload, renames))
    return donors


def _rebuild_dead_bf(dead: dict, donors: list[dict]) -> dict | None:
    """A retired-format BF rebuilt on a current sibling of the same series and period length."""
    from copy import deepcopy

    details, old = dead["details_tab"], dead["method_tab"]
    if not old.get("dfm_dataset") or not old.get("prior_datasets"):
        return None
    series = str(details["name"]).split(" ")[0]
    donor = next((d for d in donors if str(d["details_tab"]["name"]).split(" ")[0] == series
                  and d["details_tab"].get("origin_length") == details.get("origin_length")), None)
    if donor is None:
        return None
    method = deepcopy(donor)
    method["details_tab"].update({key: details[key] for key in ("name", "output_type", "origin_length")})
    tab = method["method_tab"]
    rows = len(tab["origin_labels"])
    revision = donor["method_tab"]["prior_datasets"][0]["source_revision"]
    tab["latest_dataset"] = old["latest_dataset"]
    tab["dfm_dataset"] = old["dfm_dataset"]
    tab["prior_datasets"] = [{"name": prior["name"], "values": [0.0] * rows,
                              "weights": (prior.get("weights") or [1.0] * rows)[:rows],
                              "source_revision": revision} for prior in old["prior_datasets"]]
    return method


RECALCULATE = {
    "DFM": recalculate_dfm_method,
    "BF": recalculate_bornhuetter_ferguson_method,
    "CC": recalculate_cape_cod_method,
}


def _prepare_method(kind: str, payload: dict, origin_lengths: dict[str, int]) -> tuple[dict, str]:
    """Clean one renamed template method and restamp it through its canonical contract."""
    note = ""
    own = int(payload.get("details_tab", {}).get("origin_length") or 0)
    if kind == "RS":
        tab = payload["method_tab"]
        coarser = [s["name"] for s in tab.get("loaded_datasets") or []
                   if origin_lengths.get(s.get("name"), own) > own]
        if coarser:
            tab["loaded_datasets"] = [s for s in tab["loaded_datasets"] if s.get("name") not in coarser]
            note = f"dropped coarser sources {coarser}"
    if kind == "CC":
        tab = payload["method_tab"]
        prior = str(tab.get("prior_ultimate_dataset") or "")
        if prior in origin_lengths and origin_lengths[prior] != own:
            series = str(payload["details_tab"]["name"]).split(" ")[0]
            same = sorted((n for n, length in origin_lengths.items()
                           if length == own and n.startswith(series + " ") and "DFM" in n and "Incurred" in n),
                          key=lambda n: ("Selected" not in n and "for BF" not in n, n))
            if same:
                tab["prior_ultimate_dataset"] = same[0]
                note = f"prior ultimate {prior} -> {same[0]}"
    if kind == "DFM":
        ratio = payload.get("ratios_tab", {}).get("ratio_triangle", {})
        ratio["excluded"] = [[0 for _ in row] for row in ratio.get("excluded") or []]
        results = payload.get("results_tab", {})
        basis = str(results.get("ratio_basis_dataset") or "")
        own = int(payload["details_tab"].get("origin_length") or 0)
        if basis in origin_lengths and origin_lengths[basis] != own:
            results["ratio_basis_dataset"] = "Earned Exposure"
            note = f"ratio basis {basis} -> Earned Exposure"
    recalculate = RECALCULATE.get(kind)
    if recalculate is not None:
        payload = recalculate(payload, update_refresh_timestamp=False)
    return payload, note


def _link_method_output(target: Path, output: str, precedents: list[str]) -> None:
    """Record a rebuilt method's inputs on its output sidecar and the inputs' dependents."""
    path = target / "sidecars" / f"{encode_file_name(output)}.json"
    sidecar = read_json(path)
    sidecar["precedents"] = [{"dataset_name": name} for name in precedents if name]
    write_json(path, sidecar)
    for name in precedents:
        other = target / "sidecars" / f"{encode_file_name(name)}.json"
        if name and other.is_file():
            payload = read_json(other)
            dependents = payload.get("dependents") or []
            if not any(isinstance(d, dict) and d.get("dataset_name") == output for d in dependents):
                payload["dependents"] = [*dependents, {"dataset_name": output}]
                write_json(other, payload)


def copy_template_class(old: str, new: str, donors: list[dict]) -> dict[str, int]:
    source = class_dir(TEMPLATE, old)
    target = class_dir(PROJECT, new)
    if target.exists():
        shutil.rmtree(target)
    (target / "sidecars").mkdir(parents=True)
    (target / "methods").mkdir(parents=True)
    (target / "datasets").mkdir(parents=True)
    renames = {old: new, **{name: PROJECT for name in OLD_TEMPLATE_NAMES}, **DATASET_RENAMES}
    methods = {p.name: rewrite_value(read_json(p), renames) for p in (source / "methods").glob("*.json")}
    method_names = {str(m.get("details_tab", {}).get("name") or "") for m in methods.values()}
    origin_lengths = {str(m["details_tab"].get("name")): int(m["details_tab"].get("origin_length") or 0)
                      for m in methods.values() if isinstance(m.get("details_tab"), dict)}
    counts = {"methods": 0, "sidecars": 0, "csv": 0, "dropped": 0}
    sidecars = {}
    for path in sorted((source / "sidecars").glob("*.json")):
        sidecar = read_json(path)
        dataset_type = sidecar.get("dataset_type")
        if dataset_type in DROPPED_TYPES or sidecar.get("dataset_name") in DROPPED_TYPES:
            counts["dropped"] += 1
            continue
        kind = sidecar.get("source_kind")
        orphan_bootstrap = kind == "input" and sidecar.get("method_type") == "Bootstrap"             and sidecar.get("dataset_name") not in method_names
        if orphan_bootstrap and not sidecar.get("dependents"):
            counts["dropped"] += 1
            continue
        if kind == "engine" and sidecar.get("source"):
            # A ResQ-imported triangle the Engine cannot build from the source;
            # the demo enters its values by hand instead, unless its type is a
            # formula and nothing reads it.
            if sidecar.get("precedents") and not sidecar.get("dependents"):
                counts["dropped"] += 1
                continue
            sidecar["source_kind"] = "input"
            sidecar["method_type"] = "None"
        old_name = str(sidecar.get("dataset_name") or "")
        old_csv = str(sidecar.get("csv_file") or "")
        sidecar = _set_authors(_strip_notes(rewrite_value(sidecar, renames)))
        sidecar.pop("external_links", None)
        sidecar["audit_log"] = []
        sidecar["precedents"] = _dedupe_graph(sidecar.get("precedents"))
        sidecar["dependents"] = _dedupe_graph(sidecar.get("dependents"))
        new_name = str(sidecar.get("dataset_name") or "")
        old_prefix = encode_file_name(old_name)
        if old_csv.startswith(old_prefix):
            sidecar["csv_file"] = encode_file_name(new_name) + old_csv[len(old_prefix):]
        sidecars[new_name] = (sidecar, old_csv)
    # A hand-entered vector is stored at the finest period any reader uses: a
    # calculated vector needs the same shape, and a Result Selection can only
    # roll a hand-entered vector up, never split it.
    for name, (sidecar, old_csv) in sidecars.items():
        if sidecar.get("source_kind") != "input" or sidecar.get("data_format") != "Vector":
            continue
        own = int(sidecar.get("stored_period_length") or sidecar.get("period_length") or 12)
        lengths = []
        for dependent in sidecar.get("dependents") or []:
            other = sidecars.get(dependent.get("dataset_name") if isinstance(dependent, dict) else dependent)
            if other and other[0].get("data_format") == "Vector":
                lengths.append(int(other[0].get("stored_period_length") or other[0].get("period_length") or own))
            other_method = origin_lengths.get(dependent.get("dataset_name") if isinstance(dependent, dict) else dependent)
            if other_method:
                lengths.append(other_method)
        length = min([own, *lengths])
        if length != own:
            sidecar["period_length"] = sidecar["stored_period_length"] = length
            sidecar["csv_file"] = f"{encode_file_name(name)}@{length}.csv"
            sidecars[name] = (sidecar, "")
    # A hand-entered triangle cannot be rolled up either, so it is stored at
    # the shape of the methods that read it when they agree on one.
    shapes = {str(m["details_tab"].get("name")): (int(m["details_tab"].get("origin_length") or 0),
                                                  int(m["details_tab"].get("development_length") or 0))
              for m in methods.values() if isinstance(m.get("details_tab"), dict)}
    for name, (sidecar, old_csv) in sidecars.items():
        if sidecar.get("source_kind") != "input" or sidecar.get("data_format") != "Triangle":
            continue
        readers = {shapes[d.get("dataset_name")] for d in sidecar.get("dependents") or []
                   if isinstance(d, dict) and d.get("dataset_name") in shapes and all(shapes[d["dataset_name"]])}
        if len(readers) == 1:
            origin, development = readers.pop()
            if (origin, development) != (int(sidecar.get("stored_origin_length") or 0),
                                         int(sidecar.get("stored_development_length") or 0)):
                sidecar.update({"origin_length": origin, "development_length": development,
                                "stored_origin_length": origin, "stored_development_length": development,
                                "csv_file": f"{encode_file_name(name)}@{origin}@{development}@cum@dev.csv"})
                sidecars[name] = (sidecar, "")
    for name, (sidecar, old_csv) in sidecars.items():
        write_json(target / "sidecars" / f"{encode_file_name(name)}.json", sidecar)
        counts["sidecars"] += 1
        if old_csv and (source / "datasets" / old_csv).is_file():
            shutil.copy2(source / "datasets" / old_csv, target / "datasets" / sidecar["csv_file"])
            counts["csv"] += 1
    notes = []
    for file_name, payload in sorted(methods.items()):
        kind = file_name.split("@", 1)[0]
        if payload.get("json_format") == DEAD_BF_FORMAT:
            rebuilt = _rebuild_dead_bf(payload, donors)
            name = str(payload["details_tab"]["name"])
            if rebuilt is None:
                notes.append(f"{file_name}: retired BF format with no inputs, dropped")
                (target / "sidecars" / f"{encode_file_name(name)}.json").unlink(missing_ok=True)
                for csv_path in (target / "datasets").glob(f"{encode_file_name(name)}@*"):
                    csv_path.unlink()
                continue
            _link_method_output(target, name, [rebuilt["method_tab"]["latest_dataset"],
                                               rebuilt["method_tab"]["dfm_dataset"],
                                               *[p["name"] for p in rebuilt["method_tab"]["prior_datasets"]]])
            notes.append(f"{file_name}: retired BF format rebuilt on a current sibling")
            payload = rebuilt
        payload = _set_authors(_strip_notes(payload))
        try:
            payload, note = _prepare_method(kind, payload, origin_lengths)
        except Exception as err:  # noqa: BLE001 - reported; the refresh shows what it means
            note = f"recalculation refused: {err}"
        if note:
            notes.append(f"{file_name}: {note}")
        name = str(payload.get("details_tab", {}).get("name") or decode_file_name(file_name.split("@", 1)[1][:-5]))
        if kind == "RS" and note.startswith("dropped"):
            _link_method_output(target, name, [*(str(s.get("name")) for s in payload["method_tab"]["loaded_datasets"]),
                                               *payload["details_tab"].get("ratio_basis_datasets", [])])
        write_json(target / "methods" / f"{kind}@{encode_file_name(name)}.json", payload)
        counts["methods"] += 1
    for line in notes:
        print(f"  {line}")
    return counts


def step_templates(_args: argparse.Namespace) -> None:
    donors = _bf_donors()
    for old, new in CLASS_MAP.items():
        counts = copy_template_class(old, new, donors)
        print(f"{new}: {counts}")


# ---------------------------------------------------------------- class figures


VALUATION_INDEX = abc_group.month_index(abc_group.VALUATION_MONTH)
PRIOR_VALUATION_INDEX = VALUATION_INDEX - 3
MONTHS = abc_group.month_index(abc_group.LAST_PREMIUM_MONTH) + 1
LIABILITY_LEAVES = {"BI Total", "Medical and PIP", "BI Limited Tort", "BI Full Tort", "Home Liability", "Injury Total"}


class ClassFigures:
    """One reserving class's share of the generated tables, by accident month."""

    def __init__(self, tables: abc_group.GeneratedTables, reserving_class: str) -> None:
        self.path = reserving_class
        names = reserving_class.split(BS)
        self.members = [abc_group.reserving_class_signed_members(level, name)
                        for level, name in enumerate(names, start=1)]
        keep = next((members for _label, classes, members in EXPOSURE_RULES if names[-1] in classes), None)
        self.liability = names[-1] in LIABILITY_LEAVES
        zero = lambda: [0.0] * MONTHS  # noqa: E731
        self.premium, self.exposure = zero(), zero()
        self.plan = {key: zero() for key in ("gross", "net", "alae", "salvage", "subro", "counts")}
        for row in tables.premium:
            sign = self.sign(row)
            if sign:
                month = abc_group.month_index(row[5])
                coverage = abc_group.COVERAGES_BY_LINE[row[1]][row[4]]
                gross = row[6] * abc_group.plan_loss_ratio(row[1], row[4], row[2], row[5])
                self.premium[month] += sign * row[6]
                self.plan["gross"][month] += sign * gross
                self.plan["net"][month] += sign * gross * (1 - coverage.salvage - coverage.subrogation)
                self.plan["alae"][month] += sign * gross * coverage.alae_ratio
                self.plan["salvage"][month] -= sign * gross * coverage.salvage
                self.plan["subro"][month] -= sign * gross * coverage.subrogation
        for row in tables.exposure:
            sign = self.sign(row)
            if sign:
                month = abc_group.month_index(row[5])
                coverage = abc_group.COVERAGES_BY_LINE[row[1]][row[4]]
                self.plan["counts"][month] += sign * row[6] * coverage.frequency * (1 - coverage.closed_without_payment)
                if keep is None or row[4] in keep:
                    self.exposure[month] += sign * row[6]
        self.ultimate = {field: zero() for field in abc_group.ULTIMATE_FIELDS}
        for key, totals in tables.ultimates.items():
            sign = self.sign(key)
            if sign:
                for field, value in zip(abc_group.ULTIMATE_FIELDS, totals):
                    self.ultimate[field][key[5]] += sign * value
        self.movements: dict[str, dict[tuple[int, int], float]] = {
            key: {} for key in ("net_paid", "net_incurred", "gross_paid", "gross_incurred")}
        index = {name: len(abc_group.KEY_COLUMNS) + 1 + i for i, name in enumerate(abc_group.LOSS_COLUMNS)}
        for row in tables.loss:
            sign = self.sign(row)
            if not sign:
                continue
            cell = (abc_group.month_index(row[5]), abc_group.month_index(row[6]))
            values = {
                "net_paid": row[index["gross_paid"]] + row[index["recovery"]],
                "net_incurred": row[index["net_incurred"]],
                "gross_paid": row[index["gross_paid"]],
                "gross_incurred": row[index["gross_incurred"]],
            }
            for key, value in values.items():
                self.movements[key][cell] = self.movements[key].get(cell, 0.0) + sign * value

    def sign(self, row) -> int:
        sign = 1
        for level, members in enumerate(self.members):
            sign *= members.get(row[level], 0)
            if not sign:
                return 0
        return sign

    @staticmethod
    def by_origin(monthly: list[float], length: int, last_month: int = MONTHS - 1) -> list[float]:
        return [sum(monthly[m] for m in range(start, min(start + length, last_month + 1)))
                for start in range(0, MONTHS, length)]

    def triangle(self, key: str, origin_length: int, development_length: int, columns: int,
                 outstanding_factor: Callable[[int], float] | None = None) -> list[list[float | None]]:
        """Cumulative triangle at the stored lengths; ``outstanding_factor`` restates case reserves."""
        moves = self.movements[key]
        paid_key = "net_paid" if key.startswith("net") else "gross_paid"
        # Development ages count back from the valuation, so the latest
        # diagonal is the valuation month itself (8, 20, 32... months at August).
        latest_origin = VALUATION_INDEX // origin_length * origin_length
        first_age = (VALUATION_INDEX - latest_origin) % development_length + 1
        rows = []
        for start in range(0, MONTHS, origin_length):
            row: list[float | None] = []
            for column in range(columns):
                end = start + first_age + column * development_length - 1
                if start > VALUATION_INDEX or end > VALUATION_INDEX:
                    row.append(None)
                    continue
                value = sum(v for (a, t), v in moves.items() if start <= a < start + origin_length and t <= end)
                if outstanding_factor is not None:
                    paid = sum(v for (a, t), v in self.movements[paid_key].items()
                               if start <= a < start + origin_length and t <= end)
                    value = paid + (value - paid) * outstanding_factor(end)
                row.append(round(value, 2))
            rows.append(row)
        return rows


SERIES_PLAN = {"C": "counts", "D": "gross", "E": None, "E1": "salvage", "E2": "subro", "F": "net", "G": "alae"}
SERIES_ULTIMATE = {"C": ("cwp",), "D": ("gross_loss",), "E": ("salvage", "subro"), "E1": ("salvage",),
                   "E2": ("subro",), "F": ("net_loss",), "G": ("alae",)}
PATTERN_NOTES = {
    "P 01": "Expected salvage and subrogation together, as a share of ultimate gross loss, from the claims "
            "department's recovery study of the last three closed years.",
    "P 02": "Expected salvage as a share of ultimate gross loss, from the recovery study of the last three closed years.",
    "P 03": "Expected subrogation as a share of ultimate gross loss, from the recovery study of the last three closed years.",
    "P 04 A": "Expected ALAE as a share of ultimate gross loss, from the claims department's 2026 cost study.",
    "P 04 B": "Expected ALAE as a share of ultimate net loss, from the claims department's 2026 cost study.",
    "P 06": "Plan net loss ratio by accident period from the 2026 pricing review, premium-weighted across the "
            "coverages in this segment. 2022-2023 run higher because rates lagged the severity spike; the "
            "2024 rate increases bring 2025-2026 back toward target. A newly entered state carries a 15% "
            "load for its first two years.",
    "P 07": "Plan gross loss ratio by accident period from the 2026 pricing review, before salvage and "
            "subrogation. Same basis as P 06.",
}


def _ratio(numerator: list[float], denominator: list[float]) -> list[float]:
    return [round(n / d, 4) if abs(d) > 1e-9 else 0.0 for n, d in zip(numerator, denominator)]


def _noise(seed_text: str, row: int, spread: float) -> float:
    import random

    rng = random.Random(f"{seed_text}|{row}")
    return 1.0 + rng.gauss(0.0, spread)


def input_values(figures: ClassFigures, sidecar: dict, seed: int) -> tuple[list[list], str] | None:
    """Values at the stored shape and notes for one hand-entered dataset, or None to leave it."""
    name = str(sidecar.get("dataset_type") or sidecar.get("dataset_name") or "")
    if sidecar.get("data_format") == "Triangle":
        return _triangle_input(figures, sidecar, name)
    length = int(sidecar.get("stored_period_length") or sidecar.get("period_length") or 12)
    premium = ClassFigures.by_origin(figures.premium, length)
    plan = {key: ClassFigures.by_origin(values, length) for key, values in figures.plan.items()}
    pattern = re.match(r"^(P 0\d(?: [AB])?)\b", name)
    if pattern:
        code = pattern.group(1)
        values = {
            "P 01": _ratio([s + b for s, b in zip(plan["salvage"], plan["subro"])], plan["gross"]),
            "P 02": _ratio(plan["salvage"], plan["gross"]),
            "P 03": _ratio(plan["subro"], plan["gross"]),
            "P 04 A": _ratio(plan["alae"], plan["gross"]),
            "P 04 B": _ratio(plan["alae"], plan["net"]),
            "P 06": [round(v, 3) for v in _ratio(plan["net"], premium)],
            "P 07": [round(v, 3) for v in _ratio(plan["gross"], premium)],
        }.get(code)
        return ([[v] for v in values], PATTERN_NOTES[code]) if values else None
    prior = re.match(r"^(C|D|E1|E2|E|F|G) (42a?|42 B)\b", name)
    if prior:
        series = prior.group(1)
        if series == "E":
            expected = [s + b for s, b in zip(plan["salvage"], plan["subro"])]
        else:
            expected = plan[SERIES_PLAN[series]]
        load = 1.03 if prior.group(2) == "42 B" else 1.0
        basis = "expected claims with payment from earned exposure times plan frequency" if series == "C" \
            else "earned premium times the plan loss ratio in P 06/P 07, with the ALAE and recovery " \
                 "percentages in P 04 and P 01-P 03 where they apply"
        notes = f"A priori ultimate for the Bornhuetter-Ferguson method: {basis}."
        if load != 1.0:
            notes += " Loaded 3% for the higher-severity scenario the review committee asked to see."
        return [[round(v * load, 2)] for v in expected], notes
    quarter = re.match(r"^(C|D|E1|E2|E|F|G) (81|82)\b", name)
    if quarter:
        series, kind = quarter.group(1), quarter.group(2)
        truth = [sum(figures.ultimate[f][m] for f in SERIES_ULTIMATE[series]) for m in range(MONTHS)]
        by_origin = ClassFigures.by_origin(truth, length, PRIOR_VALUATION_INDEX)
        values = []
        for row, value in enumerate(by_origin):
            age = PRIOR_VALUATION_INDEX - row * length
            spread = 0.02 if age >= 36 else (0.05 if age >= 12 else 0.09)
            estimate = value * _noise(f"{seed}|{figures.path}|{series}|81", row, spread)
            if kind == "82":
                estimate *= _noise(f"{seed}|{figures.path}|{series}|82", row, 0.015)
            values.append([round(estimate, 2) if age >= 0 else 0.0])
        what = "indicated" if kind == "81" else "selected"
        return values, f"Ultimates {what} at the prior quarterly review (May 2026 valuation)."
    if name == "Accounting Cutoff":
        rows = len(premium)
        last = VALUATION_INDEX // length
        values = [[1.0 if row != last else 1.015] for row in range(rows)]
        return values, ("Adjusts the latest diagonal for transactions booked after the August 2026 "
                        "accounting close: +1.5% on the current accident period.")
    if name == "Growth Adjustment--Counts":
        exposure = ClassFigures.by_origin(figures.exposure, length)
        last = VALUATION_INDEX // length
        values = [[1.0] for _ in exposure]
        if last >= 1 and exposure[last - 1]:
            values[last] = [round(exposure[last] / exposure[last - 1], 4)]
        return values, "Exposure growth of the current accident period over the one before, used to scale expected counts."
    return None


def _triangle_input(figures: ClassFigures, sidecar: dict, name: str) -> tuple[list[list], str] | None:
    origin = int(sidecar.get("stored_origin_length") or sidecar.get("origin_length") or 12)
    development = int(sidecar.get("stored_development_length") or sidecar.get("development_length") or 12)
    columns = MONTHS // development  # square, like the Engine's triangles
    strengthening = abc_group.month_index(abc_group.STRENGTHENING_MONTH)
    variants = {"": 1.10, " 1": 1.15, " 2": 1.12, " 3": 1.18}
    adjusted = re.match(r"^(Net Loss--Incurred|Gross Loss--Incurred|Net Loss--Paid) Adj( \d)?$", name)
    if adjusted:
        base, variant = adjusted.group(1), adjusted.group(2) or ""
        key = {"Net Loss--Incurred": "net_incurred", "Gross Loss--Incurred": "gross_incurred",
               "Net Loss--Paid": "net_paid"}[base]
        if key == "net_paid":
            return (figures.triangle(key, origin, development, columns),
                    "Net paid loss paired with the restated incurred triangle; payments need no "
                    "restatement, so the figures equal Net Loss--Paid.")
        factor = variants[variant] if figures.liability else 1.03
        rows = figures.triangle(key, origin, development, columns,
                                lambda month: factor if month < strengthening else 1.0)
        percent = round((factor - 1) * 100)
        return rows, (f"Incurred loss restated to today's case reserve adequacy: open case reserves at "
                      f"evaluations before the January 2024 strengthening review are increased by {percent}%, "
                      f"so older diagonals are comparable with the current ones.")
    if name == "Net Loss - ad hoc":
        return (figures.triangle("net_incurred", origin, development, columns),
                "Net incurred loss at monthly detail for ad hoc review of large-loss emergence.")
    return None


def write_input(class_path: Path, sidecar_path: Path, sidecar: dict, values: list[list], notes: str) -> None:
    csv_path = class_path / "datasets" / str(sidecar["csv_file"])
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        for row in values:
            writer.writerow(["" if v is None else repr(float(v)) for v in row])
    sidecar["notes"] = notes
    sidecar["modified_by"] = DEMO_AUTHOR
    sidecar["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    write_json(sidecar_path, sidecar)


def triangle_development_labels(sidecar: dict) -> list[str]:
    """Ages at the stored development length, counted back from the valuation."""
    origin = int(sidecar.get("stored_origin_length") or sidecar.get("origin_length") or 12)
    development = int(sidecar.get("stored_development_length") or sidecar.get("development_length") or 12)
    first_age = (VALUATION_INDEX - VALUATION_INDEX // origin * origin) % development + 1
    return [f"{first_age + j * development}m" for j in range(MONTHS // development)]


def save_input_through_app(reserving_class: str, sidecar: dict, values: list[list], notes: str) -> None:
    """Save hand-entered values with the app's dataset save, which walks their dependents."""
    triangle = sidecar.get("data_format") == "Triangle"
    origin = int(sidecar.get("stored_origin_length" if triangle else "stored_period_length")
                 or sidecar.get("origin_length" if triangle else "period_length") or 12)
    development = int(sidecar.get("stored_development_length") or sidecar.get("development_length") or origin)         if triangle else origin
    hosted_save("/dataset/sidecar/save", {
        "project_name": PROJECT, "reserving_class": reserving_class, "dataset_name": sidecar["dataset_name"],
        "dataset_type": sidecar.get("dataset_type") or sidecar["dataset_name"], "source_kind": "input",
        "data_format": sidecar.get("data_format") or "Vector", "origin_length": origin,
        "development_length": development, "csv_file": sidecar.get("csv_file") or "",
        "cumulative": bool(sidecar.get("cumulative", True)), "stored_values_cleared": True,
        "values": values, "notes": notes,
    })


def step_inputs(args: argparse.Namespace) -> None:
    tables = abc_group.generate(args.seed)
    for reserving_class in CLASSES:
        if args.classes and reserving_class not in args.classes:
            continue
        figures = ClassFigures(tables, reserving_class)
        folder = class_dir(PROJECT, reserving_class)
        written, skipped = 0, []
        for sidecar_path in sorted((folder / "sidecars").glob("*.json")):
            sidecar = read_json(sidecar_path)
            if sidecar.get("source_kind") != "input":
                continue
            if args.triangles_through_app and sidecar.get("data_format") != "Triangle":
                continue
            answer = input_values(figures, sidecar, args.seed)
            if answer is None:
                skipped.append(str(sidecar.get("dataset_name")))
                continue
            if sidecar.get("data_format") == "Triangle":
                sidecar["development_labels"] = triangle_development_labels(sidecar)
                sidecar["development_count"] = len(sidecar["development_labels"])
                write_json(sidecar_path, sidecar)
            if args.triangles_through_app:
                save_input_through_app(reserving_class, sidecar, *answer)
            else:
                write_input(folder, sidecar_path, sidecar, *answer)
            written += 1
        print(f"{reserving_class}: wrote {written} inputs" + (f"; left {skipped}" if skipped else ""))


# ---------------------------------------------------------------- methods


SHORT_TAIL_LEAVES = {"PD Total", "Collision", "Comp ex Cat", "Phys Dmg ex Cat", "Home Property ex Cat"}
SPARSE_STATES = {"MA": "NY"}  # a newly entered state benchmarks to a mature one
MONTH_YEAR_LABEL = re.compile(r"^[A-Z][a-z]{2} \d{4}$")


def _segment(reserving_class: str) -> dict[str, Any]:
    names = reserving_class.split(BS)
    leaf = names[-1]
    family = "short" if leaf in SHORT_TAIL_LEAVES else "long"
    return {"leaf": leaf, "state": names[2], "family": family, "liability": leaf in LIABILITY_LEAVES,
            "benchmark_state": SPARSE_STATES.get(names[2])}


def _dev_labels(method: dict) -> list[str]:
    labels = [str(v) for v in method.get("data_tab", {}).get("development_labels") or []]
    return labels


def _period_text(method: dict, col: int) -> str:
    labels = _dev_labels(method)
    if col + 1 < len(labels):
        return f"{labels[col]}-{labels[col + 1]}"
    return f"{labels[col] if col < len(labels) else 'last'}-Ult"


def _row(af: dict, label: str) -> int | None:
    for i, value in enumerate(af.get("label") or []):
        if str(value) == label:
            return i
    return None


def _drop_rows(af: dict, predicate: Callable[[str], bool]) -> list[str]:
    labels = list(af.get("label") or [])
    keep = [i for i, label in enumerate(labels) if not predicate(str(label))]
    dropped = [labels[i] for i in range(len(labels)) if i not in keep]
    if not dropped:
        return []
    for key in ("label", "selected", "values", "inputs", "display_inputs"):
        if isinstance(af.get(key), list) and len(af[key]) == len(labels):
            af[key] = [af[key][i] for i in keep]
    settings = af.get("custom_average_formula_settings") or {}
    for key, values in list(settings.items()):
        if isinstance(values, list) and len(values) == len(labels):
            settings[key] = [values[i] for i in keep]
    return dropped


def _select(af: dict, label: str, col: int) -> None:
    row = _row(af, label)
    for line in af["selected"]:
        if col < len(line):
            line[col] = 0
    af["selected"][row][col] = 1


def _set_user(af: dict, label: str, col: int, value: float) -> None:
    row = _row(af, label)
    af["values"][row][col] = round(float(value), 4)
    if isinstance(af.get("inputs"), list) and row < len(af["inputs"]) and col < len(af["inputs"][row]):
        af["inputs"][row][col] = f"{float(value):.4f}"
    if isinstance(af.get("display_inputs"), list) and row < len(af["display_inputs"]) \
            and col < len(af["display_inputs"][row]):
        af["display_inputs"][row][col] = f"{float(value):.4f}"
    _select(af, label, col)


def _ratio_counts(method: dict) -> list[int]:
    ratios = method.get("ratios_tab", {}).get("ratio_triangle", {}).get("ratio_values") or []
    columns = max((len(r) for r in ratios), default=0)
    return [sum(1 for r in ratios if col < len(r) and isinstance(r[col], (int, float))) for col in range(columns)]


def _volume_factors(method: dict, drop_latest: bool) -> list[float]:
    """All-year volume-weighted factors, optionally as they stood one diagonal earlier."""
    triangle = method.get("data_tab", {}).get("input_data_triangle_values") or []
    filled = [max((j for j, v in enumerate(row) if isinstance(v, (int, float)) and v != 0), default=-1)
              for row in triangle]
    columns = max((len(r) for r in triangle), default=1)
    factors = []
    for col in range(columns - 1):
        top = bottom = 0.0
        for i, row in enumerate(triangle):
            last = filled[i] - (1 if drop_latest else 0)
            if col + 1 <= last and isinstance(row[col], (int, float)) and isinstance(row[col + 1], (int, float)) \
                    and row[col] > 0:
                top += row[col + 1]
                bottom += row[col]
        factors.append(top / bottom if bottom > 0 else 1.0)
    return factors


def _tail(segment: dict, method_name: str, origin_length: int) -> float:
    if segment["family"] == "short":
        return 1.0
    paid = "Paid" in method_name or "ALAE" in method_name
    if "Severity" in method_name or method_name.startswith("H "):
        return 1.0
    if method_name.startswith("C "):
        return 1.0
    return 1.03 if paid else 1.005


def _crossing_cells(method: dict) -> list[tuple[int, int]]:
    """Ratio cells whose development spans the January 2024 case reserve strengthening."""
    details = method.get("details_tab", {})
    origin = int(details.get("origin_length") or 12)
    development = int(details.get("development_length") or 12)
    strengthening = abc_group.month_index(abc_group.STRENGTHENING_MONTH)
    ratios = method.get("ratios_tab", {}).get("ratio_triangle", {}).get("ratio_values") or []
    cells = []
    for i, row in enumerate(ratios):
        start = i * origin
        for j, value in enumerate(row):
            if not isinstance(value, (int, float)):
                continue
            before = start + (j + 1) * development - 1
            after = start + (j + 2) * development - 1
            if before < strengthening <= after:
                cells.append((i, j))
    return cells


COVID_YEAR = 2020
VEHICLE_GROUPS = ("ABC Auto", "ABC Moto")
MIN_FACTORS_LEFT = 3


def _exclude_covid_year(method: dict) -> bool:
    """Exclude accident-year 2020 factors wherever at least three other factors remain."""
    details = method.get("details_tab", {})
    origin = int(details.get("origin_length") or 12)
    first_year = abc_group.FIRST_MONTH // 100
    triangle = method.get("ratios_tab", {}).get("ratio_triangle", {})
    ratios = triangle.get("ratio_values") or []
    excluded = triangle.get("excluded") or []
    rows = [i for i in range(len(ratios)) if first_year + (i * origin) // 12 == COVID_YEAR]
    changed = False
    columns = max((len(row) for row in ratios), default=0)
    for j in range(columns):
        def kept(i: int) -> bool:
            row = ratios[i]
            return j < len(row) and isinstance(row[j], (int, float)) and not (
                i < len(excluded) and j < len(excluded[i]) and excluded[i][j])
        targets = [i for i in rows if kept(i)]
        others = sum(1 for i in range(len(ratios)) if i not in rows and kept(i))
        if not targets or others < MIN_FACTORS_LEFT:
            continue
        for i in targets:
            if i < len(excluded) and j < len(excluded[i]):
                excluded[i][j] = 1
                changed = True
    return changed


def plan_dfm(method: dict, reserving_class: str, benchmark: list[float] | None) -> tuple[dict, str]:
    """Selections and the notes that describe them for one DFM payload."""
    details = method["details_tab"]
    name = str(details.get("name") or "")
    segment = _segment(reserving_class)
    af = method["ratios_tab"]["average_formulas"]
    _drop_rows(af, lambda label: bool(MONTH_YEAR_LABEL.match(label)))
    curves = method.get("curves_tab") or {}
    curves["user_columns"] = [c for c in curves.get("user_columns") or [] if c.get("column_type") == "user_entry"]
    counts = _ratio_counts(method)
    columns = len(af["selected"][0]) if af.get("selected") else 0
    if columns == 0:
        return method, ""
    if "selected_estimates" in curves:
        curves["selected_estimates"] = [1] * len(curves["selected_estimates"])
        curves["selected_tail_factor"] = 1
        curves["selected_tail_curve"] = 1
    origin_length = int(details.get("origin_length") or 12)
    tail = _tail(segment, name, origin_length)
    lines: list[str] = []
    excluded_note = ""
    if segment["liability"] and "Incurred" in name and "Adj" not in str(details.get("input_triangle")) \
            and "B&S" not in str(details.get("input_triangle")):
        cells = _crossing_cells(method)
        excluded = method["ratios_tab"]["ratio_triangle"].get("excluded") or []
        for i, j in cells:
            if i < len(excluded) and j < len(excluded[i]):
                excluded[i][j] = 1
        if cells:
            excluded_note = ("Excluded the factors on the diagonal that spans the January 2024 case reserve "
                             "strengthening review; they overstate development on the old reserving basis.")
    if "Prior LDFs" in name:
        factors = _volume_factors(method, drop_latest=True)
        for col in range(columns):
            value = factors[col] if col < len(factors) else tail
            _set_user(af, "User Entry", col, value if col < columns - 1 else tail)
        lines.append("All factors are the May 2026 review's selections: all-year volume-weighted averages "
                     "as they stood one quarter ago, entered in the User Entry row.")
        lines.append(f"Tail {tail:.3f}, unchanged from the prior review.")
    elif "External" in name:
        factors = _volume_factors(method, drop_latest=False)
        for col in range(columns):
            if col < columns - 1:
                load = 1.03 if col < 2 else 1.0
                _set_user(af, "User Entry", col, (factors[col] if col < len(factors) else 1.0) * load)
            else:
                _set_user(af, "User Entry", col, tail)
        lines.append("Factors from the 2025 industry development study for this coverage, entered in the "
                     "User Entry row. The industry's early factors run about 3% above ABC's own.")
        lines.append(f"Tail {tail:.3f} from the same study.")
    elif benchmark and segment["benchmark_state"]:
        row = _row(af, "Benchmark")
        if row is not None:
            af["custom_average_formula_settings"]["average_type"][row] = "user_entry"
            for col in range(columns):
                value = benchmark[col] if col < len(benchmark) else 1.0
                _set_user(af, "Benchmark", col, value)
            lines.append(f"{segment['state']} entered in April 2023 and has fewer than four years of its own "
                         f"data, so every factor is benchmarked to the {segment['benchmark_state']} "
                         f"selections for the same coverage (Benchmark row).")
    if not lines:
        quarterly = origin_length < 12
        early_label = "Simple - 20 Ex hi/lo" if quarterly else "Simple - 5 Ex hi/lo"
        if _row(af, early_label) is None:
            early_label = "Volume - 8" if _row(af, "Volume - 8") is not None else "Volume - all"
        middle_label = "Volume - 32" if quarterly and _row(af, "Volume - 32") is not None else (
            "Volume - 8" if _row(af, "Volume - 8") is not None else "Volume - all")
        if name.startswith("H ") or "Severity" in name:
            middle_label = early_label
        early_cols = 8 if quarterly else 2
        chosen: list[str] = []
        for col in range(columns - 1):
            if col >= len(counts) or counts[col] == 0:
                label = "User Entry"
                _set_user(af, label, col, 1.0)
            elif counts[col] < 3:
                label = "Volume - all"
                _select(af, label, col)
            else:
                label = early_label if col < early_cols else middle_label
                _select(af, label, col)
            chosen.append(label)
        _set_user(af, "User Entry", columns - 1, tail)
        groups: list[tuple[str, int, int]] = []
        for col, label in enumerate(chosen):
            if groups and groups[-1][0] == label:
                groups[-1] = (label, groups[-1][1], col)
            else:
                groups.append((label, col, col))
        reasons = {
            "Simple - 5 Ex hi/lo": "five-year simple average excluding the high and low, which keeps the 2020 "
                                   "frequency dip and the 2022-2023 severity spike from driving the early factors",
            "Simple - 20 Ex hi/lo": "five-year (20-quarter) simple average excluding the high and low, which keeps "
                                    "the 2020 frequency dip and the 2022-2023 severity spike from driving the "
                                    "early factors",
            "Volume - 8": "eight-year volume-weighted average",
            "Volume - 32": "eight-year (32-quarter) volume-weighted average",
            "Volume - all": "all-year volume-weighted average, as only a few factors are observed",
            "User Entry": "no observed factors; set to 1.000",
        }
        for label, first, last in groups:
            span = _period_text(method, first) if first == last else \
                f"{_period_text(method, first)} to {_period_text(method, last)}"
            lines.append(f"{span}: {reasons.get(label, label)}.")
        if tail == 1.0:
            tail_reason = "no development is expected beyond the last observed age"
        elif tail > 1.01:
            tail_reason = "a judgmental allowance, as liability claims are still paying at the last observed age"
        else:
            tail_reason = "a small allowance for late case development on the oldest open claims"
        lines.append(f"Tail {tail:.3f}: {tail_reason}.")
        if reserving_class.split(BS)[0] in VEHICLE_GROUPS and _exclude_covid_year(method):
            effects = ("cut its claim frequency, raised its injury severity and held its court settlements over"
                       if segment["liability"] else "cut its claim frequency by up to half in the spring")
            lines.append(f"Excluded accident year 2020: COVID-19 lockdowns {effects}, so its factors are not typical.")
    if excluded_note:
        lines.append(excluded_note)
    title = "Selections"
    return method, title + "\n" + "\n".join(f"- {line}" for line in lines)


RS_MATURITY = {"long": (48, 24), "short": (12, 6)}


def _classify_source(source: dict) -> str:
    name = str(source.get("name") or "")
    method_type = str(source.get("method_type") or "")
    if "Prior Qtr Selected" in name:
        return "prior_selected"
    if "Prior Qtr Indicated" in name:
        return "prior_indicated"
    if "Current Qtr Indicated" in name:
        return "current_indicated"
    if method_type == "DFM":
        if "Prior LDFs" in name or "External" in name:
            return "dfm_other"
        if " C - Adjusted" in name or "Adjusted" in name:
            return "dfm_adjusted"
        return "dfm"
    if method_type == "Bornhuetter Ferguson" or " BF " in f" {name} ":
        return "bf_alt" if re.search(r"\d+ [A-Z] - ", name) else "bf"
    if method_type == "Cape Cod":
        return "cc"
    if "Expected" in name:
        return "expected"
    if source.get("data_format") == "Triangle":
        return "triangle"
    return "other"


def plan_result_selection(method: dict, reserving_class: str, premium_by_origin: list[float]) -> tuple[dict, str]:
    segment = _segment(reserving_class)
    tab = method["method_tab"]
    labels = list(tab.get("origin_labels") or [])
    origin_length = int(method["details_tab"].get("origin_length") or 12)
    sources = tab.get("loaded_datasets") or []
    kinds = [_classify_source(source) for source in sources]
    # The template's manual overrides belong to its old figures.
    tab["ultimate_overrides"] = [None] * len(labels)
    for source in sources:
        source["weights"] = [0.0] * len(labels)
    find = lambda kind: next((i for i, k in enumerate(kinds) if k == kind), None)  # noqa: E731
    names = [str(s.get("name")) for s in sources]
    notes: list[str] = []
    current, prior = find("current_indicated"), find("prior_selected")
    if current is not None:
        kept, moved = [], []
        for row in range(len(labels)):
            now = (sources[current].get("values") or [None] * len(labels))[row]
            before = (sources[prior].get("values") or [None] * len(labels))[row] if prior is not None else None
            if not now:
                continue
            if before and abs(now / before - 1) < 0.02:
                sources[prior]["weights"][row] = 1.0
                kept.append(labels[row])
            else:
                sources[current]["weights"][row] = 1.0
                moved.append(labels[row])
        notes.append(f"Selected the current indication ({names[current]}) wherever it moved 2% or more "
                     f"from the prior quarter: {_spans(moved) or 'none'}.")
        if prior is not None:
            notes.append(f"Kept the prior selected ultimate ({names[prior]}) where the indication moved less "
                         f"than 2%: {_spans(kept) or 'none'}.")
        return method, "Selections\n" + "\n".join(f"- {line}" for line in notes)
    primary = _primary_development_method(sources, kinds, segment)
    immature = next((find(k) for k in ("bf", "cc", "expected") if find(k) is not None), primary)
    mature_age, middle_age = RS_MATURITY[segment["family"]]
    if segment["benchmark_state"]:
        mature_age += 12
    groups: dict[str, list[str]] = {"mature": [], "middle": [], "young": []}
    for row, label in enumerate(labels):
        start = row * origin_length
        if start > VALUATION_INDEX or (row < len(premium_by_origin) and not premium_by_origin[row]):
            continue
        age = VALUATION_INDEX - start + 1
        if primary is None:
            continue
        if age >= mature_age or immature is None or immature == primary:
            sources[primary]["weights"][row] = 1.0
            groups["mature"].append(label)
        elif age >= middle_age:
            sources[primary]["weights"][row] = 0.5
            sources[immature]["weights"][row] = 0.5
            groups["middle"].append(label)
        else:
            sources[immature]["weights"][row] = 1.0
            groups["young"].append(label)
    if primary is not None:
        notes.append(f"{_spans(groups['mature']) or 'No origins'}: {names[primary]} (100%), the origins are mature "
                     f"enough ({mature_age}+ months) for development to be reliable.")
    if groups["middle"] and immature is not None:
        notes.append(f"{_spans(groups['middle'])}: 50% {names[primary]} and 50% {names[immature]}, "
                     f"blending the indication with the a priori while development is still material.")
    if groups["young"] and immature is not None:
        notes.append(f"{_spans(groups['young'])}: {names[immature]} (100%); too little of the ultimate has "
                     f"emerged for a development method alone.")
    if segment["liability"] and primary is not None and kinds[primary] == "dfm_adjusted":
        notes.append("The restated-incurred DFM is preferred to the unadjusted one because the January 2024 "
                     "case reserve strengthening distorts the unadjusted incurred factors.")
    elif segment["liability"] and primary is not None and "BS Incurred" in names[primary]:
        notes.append("The Berquist-Sherman adjusted incurred DFM is preferred because it restates older case "
                     "reserves to the adequacy in place since the January 2024 strengthening.")
    if segment["benchmark_state"]:
        notes.append(f"{segment['state']} is a new state (entered April 2023), so the a priori carries more weight "
                     f"for a year longer than in the mature states.")
    return method, "Selections\n" + "\n".join(f"- {line}" for line in notes)


def _primary_development_method(sources: list[dict], kinds: list[str], segment: dict) -> int | None:
    """The development method an actuary would lean on for mature origins of this segment."""
    def rank(index: int) -> int:
        name = str(sources[index].get("name") or "")
        if kinds[index] == "dfm_adjusted":
            return 0 if segment["liability"] else 6
        if "BS Incurred" in name:
            return 1 if segment["liability"] else 6
        if "Incurred DFM" in name or "Reported ex CWOP DFM" in name:
            return 2
        if "Reported DFM" in name:
            return 3
        return 4 if "Selected LDFs" in name else 5
    candidates = [i for i, kind in enumerate(kinds) if kind in ("dfm", "dfm_adjusted")]
    if not candidates:
        # No DFM is loaded: a vector derived from DFM outputs stands in.
        candidates = [i for i, kind in enumerate(kinds) if kind == "other"]
    return min(candidates, key=lambda i: (rank(i), i)) if candidates else None


def _spans(labels: list[str]) -> str:
    if not labels:
        return ""
    if len(labels) <= 2:
        return ", ".join(labels)
    return f"{labels[0]} to {labels[-1]}"


def _method_files(reserving_class: str, prefix: str) -> list[Path]:
    return sorted((class_dir(PROJECT, reserving_class) / "methods").glob(f"{prefix}@*.json"))


def _dfm_selected_factors(reserving_class: str, method_name: str, origin_length: int) -> list[float] | None:
    path = class_dir(PROJECT, reserving_class) / "methods" / f"DFM@{encode_file_name(method_name)}.json"
    if not path.is_file():
        return None
    method = read_json(path)
    if int(method["details_tab"].get("origin_length") or 0) != origin_length:
        return None
    return [float(v) for v in method.get("curves_tab", {}).get("selected_values") or []] or None


def save_dfm(reserving_class: str, path: Path) -> None:
    loaded = call("/dfm/method/load", {"project_name": PROJECT, "reserving_class": reserving_class,
                                       "method_name": decode_file_name(path.stem.split("@", 1)[1])}, timeout=300)
    method = loaded.get("method") or read_json(path)
    segment = _segment(reserving_class)
    benchmark = None
    if segment["benchmark_state"]:
        names = reserving_class.split(BS)
        names[2] = segment["benchmark_state"]
        benchmark = _dfm_selected_factors(BS.join(names), method["details_tab"]["name"],
                                          int(method["details_tab"].get("origin_length") or 12))
    method, notes = plan_dfm(method, reserving_class, benchmark)
    hosted_save("/dfm/method/save", {"project_name": PROJECT, "reserving_class": reserving_class,
                                     "method": method, "notes": notes})


def save_result_selection_method(reserving_class: str, path: Path, figures: ClassFigures) -> None:
    name = decode_file_name(path.stem.split("@", 1)[1])
    loaded = call("/result-selection/load", {"project_name": PROJECT, "reserving_class": reserving_class,
                                             "method_name": name, "include_method": True}, timeout=300)
    method = loaded["method"]
    length = int(method["details_tab"].get("origin_length") or 12)
    method, notes = plan_result_selection(method, reserving_class, ClassFigures.by_origin(figures.premium, length))
    hosted_save("/result-selection/save", {"project_name": PROJECT, "reserving_class": reserving_class,
                                           "method": method, "notes": notes,
                                           "expected_revision": loaded.get("method_revision")})


def _rs_order(path: Path) -> tuple[int, int]:
    name = decode_file_name(path.stem.split("@", 1)[1])
    stage = 0 if " 91 " in f" {name} " or name.split(" - ")[0].endswith("91") else 1
    series = name.split(" ")[0]
    return stage, {"F": 0, "D": 1, "C": 2, "G": 3}.get(series, 4)


def _settlement_reason(reserving_class: str) -> str:
    if reserving_class.split(BS)[0] not in VEHICLE_GROUPS:
        return "settlement speed varies from year to year with claim volume and staffing"
    if reserving_class.split(BS)[-1] in LIABILITY_LEAVES:
        return ("court closures held injury settlements over from April 2020 to mid-2021, and settlement "
                "speed varies from year to year")
    return ("parts shortages lengthened repair times in 2021-2022, and settlement speed varies from year to year")


def other_method_notes(kind: str, method: dict, reserving_class: str = "") -> str:
    """Plain notes for the methods whose settings the demo keeps as the template set them."""
    tab = method.get("method_tab") or {}
    details = method.get("details_tab") or {}
    if kind == "BF":
        priors = ", ".join(p.get("name", "") for p in tab.get("prior_datasets") or []) or "the a priori vector"
        return ("Bornhuetter-Ferguson\n"
                f"- Latest: {tab.get('latest_dataset')}.\n"
                f"- A priori ultimate: {priors}, which is earned premium (or exposure) times the plan ratio.\n"
                f"- Percentage developed: from the selected factors of {tab.get('dfm_dataset')}.\n"
                "- Used for the youngest origins, where too little has emerged for a development method alone.")
    if kind == "CC":
        rate = float(tab.get("trend_rate") or 0)
        return ("Cape Cod\n"
                f"- Latest: {tab.get('latest_dataset')}; used-up exposure from {tab.get('exposure_dataset')} and the "
                f"percentage developed of {tab.get('prior_ultimate_dataset')}.\n"
                f"- Trend {rate:.1%} a year and decay {float(tab.get('decay_factor') or 0):.2f}, so nearby origins "
                "carry most of the weight in each origin's expected ratio.\n"
                "- A cross-check on the Bornhuetter-Ferguson a priori, which comes from the plan instead of the data.")
    if kind == "BSCRA":
        return ("Berquist-Sherman case reserve adequacy\n"
                f"- Restates {tab.get('incurred_claims')} so every diagonal carries the latest diagonal's average "
                "case reserve per open claim, detrended to each evaluation date.\n"
                "- Needed because the January 2024 strengthening review raised case reserves on open liability claims; "
                "unadjusted incurred factors that span it overstate development.")
    if kind == "BSSR":
        return ("Berquist-Sherman settlement rate\n"
                f"- Restates {tab.get('paid_claims')} to the latest diagonal's proportion of {tab.get('ultimate_claim_numbers')} "
                f"closed, using {tab.get('closed_claim_numbers')}.\n"
                f"- Needed because the closing pace has moved: {_settlement_reason(reserving_class)}.")
    if kind == "BST":
        simulation = method.get("simulation_tab") or {}
        results = method.get("results_tab") or {}
        return ("Bootstrap (ODP)\n"
                f"- Resamples the residuals of {details.get('dfm_method')} with "
                f"{int(simulation.get('simulation_count') or 0):,} simulations and a fixed seed, so the range "
                "repeats exactly.\n"
                f"- Means are scaled to the selected ultimates in {results.get('target_ultimate')}; the percentiles "
                "give the reserve range shown to the review committee.")
    return ""


def save_other_notes(reserving_class: str) -> list[str]:
    failures = []
    for path in sorted((class_dir(PROJECT, reserving_class) / "methods").glob("*.json")):
        kind = path.name.split("@", 1)[0]
        if kind not in ("BF", "CC", "BSCRA", "BSSR", "BST"):
            continue
        method = read_json(path)
        notes = other_method_notes(kind, method, reserving_class)
        name = str(method.get("details_tab", {}).get("name") or "")
        if not notes or not name:
            continue
        try:
            call("/dataset/notes/save", {"project_name": PROJECT, "reserving_class": reserving_class,
                                         "dataset_name": name, "notes": notes}, timeout=300)
        except Exception as err:  # noqa: BLE001
            failures.append(f"{path.name} notes: {str(err)[:300]}")
    return failures


def save_claim_count_severity(reserving_class: str) -> list[str]:
    """The hand-entered "F 31" vector: ultimate claims with payment times the selected severity."""
    folder = class_dir(PROJECT, reserving_class)
    path = folder / "sidecars" / "F 31 - Claim Count _%2A_ Severity.json"
    if not path.is_file() or read_json(path).get("source_kind") != "input":
        return []
    sidecar = read_json(path)
    length = int(sidecar.get("stored_period_length") or sidecar.get("period_length") or 12)

    def vector(name: str) -> list[float]:
        csv_path = folder / "datasets" / f"{encode_file_name(name)}@{length}.csv"
        rows = csv_path.read_text(encoding="utf-8").splitlines() if csv_path.is_file() else []
        return [float(r) if r.strip() else 0.0 for r in rows]

    counts = vector("C 91 - Current Qtr Indicated")
    severity = vector("H 02 - Net Incurred per Reported ex CWOP DFM w/ Selected LDFs")
    if not counts or len(counts) != len(severity):
        return [f"F 31: C 91 or H 02 is not stored at {length}-month origins"]
    values = [[round(c * s / 1000, 2)] for c, s in zip(counts, severity)]
    payload = {
        "project_name": PROJECT, "reserving_class": reserving_class, "dataset_name": sidecar["dataset_name"],
        "dataset_type": sidecar["dataset_type"], "source_kind": "input", "data_format": "Vector",
        "origin_length": length, "development_length": length, "csv_file": sidecar["csv_file"],
        "stored_values_cleared": True, "values": values,
        "notes": "Frequency-severity cross-check: ultimate claims with payment (C 91) times the selected net "
                 "severity per claim (H 02), in thousands.",
    }
    try:
        hosted_save("/dataset/sidecar/save", payload)
    except Exception as err:  # noqa: BLE001
        return [f"F 31: {str(err)[:300]}"]
    return []


def step_methods(args: argparse.Namespace) -> None:
    tables = abc_group.generate(args.seed)
    only = set(args.classes or [])
    for reserving_class in CLASSES:
        if only and reserving_class not in only:
            continue
        figures = ClassFigures(tables, reserving_class)
        failures = []
        dfms = [] if args.rs_only else _method_files(reserving_class, "DFM")
        for path in dfms:
            try:
                save_dfm(reserving_class, path)
            except Exception as err:  # noqa: BLE001 - reported, the next method still runs
                failures.append(f"{path.name}: {str(err)[:300]}")
        rs = sorted(_method_files(reserving_class, "RS"), key=_rs_order)
        for path in rs:
            try:
                save_result_selection_method(reserving_class, path, figures)
            except Exception as err:  # noqa: BLE001
                failures.append(f"{path.name}: {str(err)[:300]}")
        if not args.rs_only:
            failures += save_claim_count_severity(reserving_class)
            failures += save_other_notes(reserving_class)
        print(f"{reserving_class}: {len(dfms)} DFM, {len(rs)} RS saved" +
              (f"; {len(failures)} failed" if failures else ""), flush=True)
        for line in failures:
            print(f"  ! {line}", flush=True)


# ---------------------------------------------------------------- refresh


def step_refresh(_args: argparse.Namespace) -> None:
    request_id = uuid.uuid4().hex
    answer = call("/source_table/refresh_job", {"project_name": PROJECT, "request_id": request_id,
                                                "import_source": False, "force": True,
                                                "refresh_dependents": True}, timeout=300)
    job_id = str(answer.get("job_id") or request_id)
    status = wait_for_job("/source_table/refresh_job/status", job_id, "source refresh")
    for key in ("failures", "dependent_problems"):
        for line in status.get(key) or []:
            print(f"  ! {key}: {json.dumps(line)[:400]}")


# ---------------------------------------------------------------- finish


METHOD_SOURCE_KINDS = frozenset({"dfm", "result_selection", "bornhuetter_ferguson", "cape_cod", "bootstrap",
                                 "berquist_sherman_sr", "berquist_sherman_cra"})


def sign_off_reviews() -> None:
    """Mark method outputs that later walks refreshed as reviewed, as the reviewer would."""
    for reserving_class in CLASSES:
        names = []
        for path in sorted((class_dir(PROJECT, reserving_class) / "sidecars").glob("*.json")):
            sidecar = read_json(path)
            if sidecar.get("source_kind") in METHOD_SOURCE_KINDS and int(sidecar.get("status") or 0) != 0:
                names.append(sidecar["dataset_name"])
        if names:
            call("/datasets/review-status", {"project_name": PROJECT, "reserving_class": reserving_class,
                                             "dataset_names": names, "status": 0}, timeout=300)
            print(f"{reserving_class}: signed off {len(names)} reviewed outputs")


def step_finish(_args: argparse.Namespace) -> None:
    sign_off_reviews()
    root = project_dir()
    paths = [*root.glob("*.json"), *root.glob("source/*.json")]
    for reserving_class in CLASSES:
        folder = class_dir(PROJECT, reserving_class)
        paths += [*(folder / "sidecars").glob("*.json"), *(folder / "methods").glob("*.json")]
    changed = 0
    for path in paths:
        payload = read_json(path)
        renamed = _set_authors(payload)
        if renamed != payload:
            write_json(path, renamed)
            changed += 1
    print(f"Set {DEMO_AUTHOR} as the author in {changed} files")
    problems = 0
    for reserving_class in CLASSES:
        call(f"/datasets/cached?project_name={PROJECT}&reserving_class={reserving_class}&refresh=true"
             .replace(" ", "%20").replace("\\", "%5C").replace("+", "%2B"), timeout=120)
        review, silent = [], []
        for path in sorted((class_dir(PROJECT, reserving_class) / "sidecars").glob("*.json")):
            sidecar = read_json(path)
            if sidecar.get("source_kind") not in METHOD_SOURCE_KINDS:
                continue
            if int(sidecar.get("status") or 0) != 0:
                review.append(sidecar["dataset_name"])
            if not str(sidecar.get("notes") or "").strip():
                silent.append(sidecar["dataset_name"])
        problems += len(review)
        print(f"{reserving_class}: {len(review)} need review, {len(silent)} without notes")
        for name in review:
            print(f"  review: {name}")
        for name in silent:
            print(f"  no notes: {name}")
    print(f"{problems} method outputs still need review")


STEPS: dict[str, Callable[[argparse.Namespace], None]] = {
    "scaffold": step_scaffold,
    "templates": step_templates,
    "refresh": step_refresh,
    "inputs": step_inputs,
    "methods": step_methods,
    "finish": step_finish,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("steps", nargs="+", choices=sorted(STEPS))
    parser.add_argument("--seed", type=int, default=abc_group.DEFAULT_SEED)
    parser.add_argument("--classes", nargs="*", help="Limit the inputs and methods steps to these reserving classes.")
    parser.add_argument("--rs-only", action="store_true",
                        help="Methods step: save only the Result Selections, after the other methods settle.")
    parser.add_argument("--triangles-through-app", action="store_true",
                        help="Inputs step: save only the hand-entered triangles, through the app's dataset save.")
    args = parser.parse_args(argv)
    if os.environ.get("COMPUTERNAME", "").casefold() != "ne7saswpn02":
        parser.error("Run on the Server PC NE7SASWPN02, where the project folder is local disk.")
    for step in args.steps:
        print(f"== {step}", flush=True)
        STEPS[step](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
