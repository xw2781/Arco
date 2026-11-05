"""Republish Bornhuetter Ferguson and Cape Cod methods that no longer match their own snapshots.

A BF origin with no Latest value yet -- a quarter beyond the valuation in a
quarterly class -- used to leave its New Ultimate blank. It now takes the whole
Selected Prior, so a quarterly method covers the full year. Every saved BF
keeps its stored New Ultimate until something recalculates it, and the app
refuses to open, save, or refresh a method whose stored column no longer
matches the rule, so this is an explicit, one-time restatement of one project.

Each affected method is recalculated from its own embedded snapshots -- no
precedent is re-read -- and republished exactly as a precedent refresh would
publish it: method JSON, output sidecar, and output vector, with the output
flagged for review because its values changed. Every method of a reserving
class is rewritten before that class's single dependent walk is queued on the
Engine, so the walk never meets a sibling BF the app cannot yet open.

Cape Cod methods are held to the same rule -- a stored trend rate, trend
factor or percentage developed must be what the method's own snapshots give --
and are restated the same way. ``--kind`` limits a run to one of the two.

Examples:

    python tools/restate_bf_unobserved_origin_ultimates.py --project "NJ_Annual_Prod_2026 Q3-Aug" --dry-run
    python tools/restate_bf_unobserved_origin_ultimates.py --project "NJ_Annual_Prod_2026 Q3-Aug" --apply
    python tools/restate_bf_unobserved_origin_ultimates.py --all-projects --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "frontend"))
sys.path.insert(0, str(REPO_ROOT / "python-api" / "src"))

from app_server import config  # noqa: E402
from app_server.services import (  # noqa: E402
    bornhuetter_ferguson_service as bf,
    cape_cod_service as cc,
    dataset_sidecar_status_service,
    dependent_propagation_service as propagation,
)
from arcrho_api.bornhuetter_ferguson_contract import (  # noqa: E402
    normalize_bornhuetter_ferguson_method,
    recalculate_bornhuetter_ferguson_method,
)
from arcrho_api.cape_cod_contract import (  # noqa: E402
    CC_DERIVED_COLUMNS,
    normalize_cape_cod_method,
    recalculate_cape_cod_method,
)
from restate_percentage_developed import (  # noqa: E402
    BF_PREFIX,
    CC_PREFIX,
    RestateError,
    _changed_rows,
    _method_names,
    _read_json,
    _reserving_classes,
    _wait_for_class,
)

WALK_POLL_SECONDS = 5.0
WALK_TIMEOUT_SECONDS = 1800.0


# kind -> (method file prefix, service, snapshot recalculation, the check the
# app runs before it opens one, the method_tab columns compared row by row).
KINDS = {
    "BF": (BF_PREFIX, bf, recalculate_bornhuetter_ferguson_method, normalize_bornhuetter_ferguson_method, ("new_ultimate",)),
    "Cape Cod": (CC_PREFIX, cc, recalculate_cape_cod_method, normalize_cape_cod_method, CC_DERIVED_COLUMNS),
}
KIND_OPTIONS = {"bf": ("BF",), "cc": ("Cape Cod",), "all": tuple(KINDS)}


def _is_current(normalize: Any, method: Dict[str, Any]) -> bool:
    try:
        normalize(method)
    except Exception:  # noqa: BLE001 - any refusal means the method needs restating
        return False
    return True


def _plan_one(project: str, reserving_class: str, method_name: str, kind: str = "BF") -> Dict[str, Any]:
    _prefix, service, recalculate, normalize, columns = KINDS[kind]
    method = _read_json(Path(service._method_path(project, reserving_class, method_name)))
    refreshed = recalculate(method, update_refresh_timestamp=False)
    old_tab = method.get("method_tab") or {}
    new_tab = refreshed["method_tab"]
    old = old_tab.get(columns[0]) or []
    new = new_tab[columns[0]]
    changed = set()
    for column in columns:
        before = old_tab.get(column) if isinstance(old_tab.get(column), list) else []
        after = new_tab.get(column) if isinstance(new_tab.get(column), list) else []
        changed.update(
            index for index in range(max(len(before), len(after)))
            if _changed_rows(before[index:index + 1], after[index:index + 1])
        )
    return {
        "kind": kind,
        "reserving_class": reserving_class,
        "method": method_name,
        "origins": len(new),
        "changed_rows": len(changed),
        "filled_blanks": sum(
            1 for index in range(len(new))
            if (index >= len(old) or old[index] is None) and new[index] is not None
        ),
        # A method the app refuses is restated even when no row moves past the
        # comparison tolerance (a Cape Cod trend rate alone), or it stays refused.
        "needs_restating": bool(changed) or not _is_current(normalize, method),
        "refreshed": refreshed,
    }


def _publish_one(project: str, reserving_class: str, plan: Dict[str, Any]) -> Tuple[str, str]:
    refreshed = plan["refreshed"]
    service = KINDS[plan["kind"]][1]
    _method_name, output_dataset = service._identity(refreshed)
    sidecar_path = service._sidecar_path(project, reserving_class, output_dataset)
    with dataset_sidecar_status_service.sidecar_write_lock(sidecar_path):
        existing_sidecar = service._read_json(sidecar_path)
        if not existing_sidecar:
            raise RestateError(f"{plan['kind']} output sidecar is missing.")
        service._publish(
            project,
            reserving_class,
            refreshed,
            existing_sidecar,
            notes=None,
            changed=True,
            automatic=True,
            write_outputs=True,
        )
    output_type = str((refreshed.get("details_tab") or {}).get("output_type") or "").strip()
    return output_dataset, output_type or output_dataset


def _apply_class(project: str, reserving_class: str, plans: List[Dict[str, Any]]) -> Dict[str, Any]:
    _wait_for_class(project, reserving_class)
    roots = []
    for kind, (_prefix, service, *_rest) in KINDS.items():
        kind_plans = [plan for plan in plans if plan["kind"] == kind]
        if not kind_plans:
            continue
        with service._lock(project, reserving_class):
            for plan in kind_plans:
                output_dataset, output_type = _publish_one(project, reserving_class, plan)
                roots.append(propagation.changed_root(output_dataset, output_type))
                print(f"  restated {kind:8} {reserving_class} / {plan['method']}")
    return propagation.enqueue_save_propagation(project, reserving_class, roots)


def _wait_for_walks(jobs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Poll every queued walk to a terminal status; return the ones that failed."""

    pending = dict(jobs)
    failed: List[Tuple[str, str]] = []
    deadline = time.monotonic() + WALK_TIMEOUT_SECONDS
    while pending and time.monotonic() < deadline:
        for reserving_class, job_id in list(pending.items()):
            status = propagation.get_dependent_propagation_status(job_id)
            state = str(status.get("status") or "")
            if state not in ("success", "error"):
                continue
            del pending[reserving_class]
            if state == "error":
                failed.append((reserving_class, str(status.get("message") or status.get("error") or job_id)))
            print(f"  walk {state:7} {reserving_class}")
        if pending:
            time.sleep(WALK_POLL_SECONDS)
    for reserving_class, job_id in pending.items():
        failed.append((reserving_class, f"walk still running after {WALK_TIMEOUT_SECONDS:.0f}s: job {job_id}"))
    return failed


def run(project: str, *, apply: bool, verbose: bool, kinds: Tuple[str, ...] = tuple(KINDS)) -> int:
    classes = _reserving_classes(project)
    plans: List[Dict[str, Any]] = []
    failures: List[Tuple[str, str, str]] = []
    for reserving_class in classes:
        for kind in kinds:
            for method_name in _method_names(project, reserving_class, KINDS[kind][0]):
                try:
                    plans.append(_plan_one(project, reserving_class, method_name, kind))
                except Exception as err:  # noqa: BLE001 - reported, never fatal
                    failures.append((reserving_class, method_name, str(err)))

    touched = [plan for plan in plans if plan["needs_restating"]]
    print(f"Project              : {project}")
    print(f"Reserving classes    : {len(classes)}")
    print(f"Methods inspected    : {len(plans)}")
    print(f"Methods to restate   : {len(touched)}")
    print(f"Rows changing        : {sum(plan['changed_rows'] for plan in touched)}")
    print(f"Blank rows filled    : {sum(plan['filled_blanks'] for plan in touched)}")
    if failures:
        print(f"Could not be read    : {len(failures)}")
        for reserving_class, method_name, reason in failures:
            print(f"  ! {reserving_class} / {method_name}: {reason}")
    if verbose:
        for plan in touched:
            print(
                f"  {plan['kind']:8} {plan['reserving_class']} / {plan['method']}: "
                f"{plan['changed_rows']} of {plan['origins']} rows"
                f" ({plan['filled_blanks']} previously blank)"
            )

    if not apply:
        print("\nDry run: nothing was written.")
        return 1 if failures else 0

    by_class: Dict[str, List[Dict[str, Any]]] = {}
    for plan in touched:
        by_class.setdefault(plan["reserving_class"], []).append(plan)
    applied = 0
    jobs: List[Tuple[str, str]] = []
    apply_failures: List[Tuple[str, str]] = []
    for reserving_class, class_plans in by_class.items():
        try:
            result = _apply_class(project, reserving_class, class_plans)
            applied += len(class_plans)
            if result.get("ok") and result.get("job_id"):
                jobs.append((reserving_class, str(result["job_id"])))
            else:
                apply_failures.append((reserving_class, f"walk not queued: {result.get('message') or result}"))
        except Exception as err:  # noqa: BLE001 - reported, never fatal
            apply_failures.append((reserving_class, str(err)))
            print(f"  ! FAILED {reserving_class}: {err}")

    print(f"\nRestated {applied} of {len(touched)} methods; {len(jobs)} dependent walks queued.")
    apply_failures.extend(_wait_for_walks(jobs))
    if apply_failures:
        print(f"{len(apply_failures)} reserving classes need attention:")
        for reserving_class, reason in apply_failures:
            print(f"  ! {reserving_class}: {reason}")
    return 1 if apply_failures or failures else 0


def _all_projects() -> List[str]:
    return sorted(
        entry.name
        for entry in os.scandir(config.PROJECT_SETTINGS_DIR)
        if entry.is_dir() and not entry.name.startswith(".")
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", action="append", default=[], help="Project folder name; repeatable, run in order.")
    parser.add_argument("--all-projects", action="store_true", help="Every project folder, after any --project given.")
    parser.add_argument("--apply", action="store_true", help="Write the restated methods and queue the walks.")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing (default).")
    parser.add_argument("--verbose", action="store_true", help="List every method that changes.")
    parser.add_argument("--kind", choices=sorted(KIND_OPTIONS), default="all", help="Method kind (default: all).")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("Choose either --apply or --dry-run.")
    projects = list(args.project)
    if args.all_projects:
        projects.extend(name for name in _all_projects() if name not in projects)
    if not projects:
        parser.error("Give --project or --all-projects.")
    exit_code = 0
    for index, project in enumerate(projects):
        if index:
            print()
        exit_code = max(
            exit_code,
            run(project, apply=bool(args.apply), verbose=bool(args.verbose), kinds=KIND_OPTIONS[args.kind]),
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
