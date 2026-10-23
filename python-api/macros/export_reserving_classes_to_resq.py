# <arcrho-macro>
# Title: Export Reserving Classes to ResQ
# Version: 1.1.0
# Release Note: Every exportable item of each class is sent, instead of the items its last single-class export ticked.
# Description: Offer the default reserving classes this project holds in a review table, compare each ticked class with ResQ through the ArcRho Bridge, show one plan table with what each class would write and how many newer ResQ copies it would overwrite, then export every exportable item of each accepted class, one class at a time, and show one results row per class.
# Scope: Project
# Icon: upload
# </arcrho-macro>

"""Push several ArcRho reserving classes into ResQ, one class at a time.

Each class goes through the same two Bridge queue phases the single-class
Export macro runs -- ``transfer_preview``, then ``export`` -- so a class is
written exactly as that macro writes it. There is no per-class item review:
every item the export supports is sent. The export request carries no
selection, which pushes the whole class and leaves the selection the
single-class macro remembers for that class untouched.
"""

from __future__ import annotations

from typing import Any

TITLE = "Export Reserving Classes to ResQ"
PROGRESS_ID = "export-reserving-classes-to-resq"
MAX_REPORTED_FAILURES = 12
NOT_IN_ARCRHO_LABEL = "Not in Arco"


def _load_class_list() -> list[str]:
    """The default class list, owned by the batch import macro beside this one.

    The macro runner puts the running macro's folder on ``sys.path``, and the
    batch import is deployed to the same folder, so both batches offer the
    same classes in the same order.
    """

    try:
        import import_resq_reserving_classes as batch_import
    except ImportError as exc:
        raise RuntimeError(
            "This macro needs the 'Import ResQ Reserving Classes' macro in the "
            "same macros folder. Load or update it from the Macro Library, "
            "then run this macro again."
        ) from exc
    return list(batch_import.RC_PATHS)


def _message(ui, text, *, title=TITLE, kind="info", auto_close_ms=None, buttons=None):
    return ui.message_box(
        str(text or ""),
        title=title,
        kind=kind,
        auto_close_ms=auto_close_ms,
        buttons=buttons,
        timeout_sec=600,
    )


def _context_value(context, *names):
    if not isinstance(context, dict):
        return ""
    for name in names:
        value = str(context.get(name) or "").strip()
        if value:
            return value
    return ""


def _report_activity() -> None:
    cancel_checker = globals().get("check_macro_cancelled")
    if callable(cancel_checker):
        cancel_checker()
    reporter = globals().get("report_macro_activity")
    if callable(reporter):
        reporter()


def listed_classes(project_name: str, rc_paths: list[str]) -> list[dict[str, Any]]:
    """The default classes, each marked as held by the project or not."""

    from arcrho_api.gateway import GatewayClient

    existing = GatewayClient().read("resq_class_inventory", project_name=project_name)
    return [
        {
            "path": rc_path,
            "exists": rc_path.casefold() in existing,
            "dataset_count": existing.get(rc_path.casefold()),
        }
        for rc_path in rc_paths
    ]


def class_selection_payload(classes: list[dict[str, Any]], project_name: str) -> dict[str, Any]:
    """The class picker: every class the project holds is ticked; the others cannot be."""

    rows = []
    for item in classes:
        count = item.get("dataset_count")
        rows.append({
            "id": item["path"],
            "selected": bool(item["exists"]),
            "disabled": not item["exists"],
            "cells": {
                "path": item["path"],
                "datasets": (
                    NOT_IN_ARCRHO_LABEL if not item["exists"] else "" if count is None else str(count)
                ),
            },
        })
    return {
        "title": TITLE,
        "host": "projectInstance",
        "summary": (
            f"Project: {project_name}\n"
            "Each ticked class is compared with ResQ first; nothing is written "
            "until you accept the plan that follows."
        ),
        "columns": [
            {"key": "path", "label": "Reserving Class", "width": 420},
            {"key": "datasets", "label": "Indexed Items", "width": 130},
        ],
        "rows": rows,
        "acceptLabel": "Compare with ResQ",
        "cancelLabel": "Cancel",
        "searchPlaceholder": "Filter reserving classes",
        "emptyMessage": "No default reserving class is listed.",
    }


def preview_names(preview: list[dict[str, Any]]) -> list[str]:
    """Every name the export can write, whatever the class's saved selection ticks."""

    return [
        str(row.get("name") or "")
        for row in preview
        if row.get("transfer_supported") and str(row.get("name") or "").strip()
    ]


def preview_classes(ui, root, project_name: str, rc_paths: list[str]) -> list[dict[str, Any]]:
    """Run the Bridge comparison for each class; a failed class keeps its error."""

    from arcrho_api.resq_sync_queue import (
        DIRECTION_EXPORT,
        PHASE_TRANSFER_PREVIEW,
        PREVIEW_TIMEOUT_SEC,
        BridgeUnavailableError,
        run_bridge_phase,
    )
    from arcrho_api.resq_transfer_review import edits_at_risk

    plans: list[dict[str, Any]] = []
    total = len(rc_paths)
    progress = ui.progress_bar(progress_id=f"{PROGRESS_ID}-preview", title=TITLE, label="Comparing with ResQ", total=total)
    try:
        for position, rc_path in enumerate(rc_paths, start=1):
            label = f"Comparing Arco and ResQ: {rc_path} ({position} of {total})"
            try:
                result = run_bridge_phase(
                    server_root=root,
                    project_name=project_name,
                    rc_path=rc_path,
                    phase=PHASE_TRANSFER_PREVIEW,
                    direction=DIRECTION_EXPORT,
                    timeout_sec=PREVIEW_TIMEOUT_SEC,
                    progress=progress,
                    progress_label=label,
                    on_poll=_report_activity,
                )
            except BridgeUnavailableError:
                raise
            except Exception as exc:
                plans.append({"path": rc_path, "error": str(exc), "names": []})
                continue
            preview = [row for row in result.get("preview") or [] if isinstance(row, dict)]
            names = preview_names(preview)
            plans.append({
                "path": rc_path,
                "error": "",
                "names": names,
                "connection_name": str(result.get("connection_name") or ""),
                "created": sum(
                    1 for row in preview
                    if row.get("transfer_supported") and str(row.get("presence") or "") == "arcrho"
                ),
                "at_risk": len(edits_at_risk(preview, DIRECTION_EXPORT)),
            })
    finally:
        progress.close()
    return plans


def plan_table_payload(plans: list[dict[str, Any]], project_name: str) -> dict[str, Any]:
    """One row per compared class; a class that failed the comparison or has nothing to write cannot be ticked."""

    rows = []
    at_risk_total = 0
    for plan in plans:
        writable = not plan["error"] and bool(plan["names"])
        at_risk_total += int(plan.get("at_risk") or 0) if writable else 0
        if plan["error"]:
            detail = {"text": plan["error"], "tone": "error"}
        elif not plan["names"]:
            detail = {"text": "Nothing to export", "tone": "muted"}
        else:
            detail = {"text": "", "tone": "muted"}
        at_risk = int(plan.get("at_risk") or 0)
        rows.append({
            "id": plan["path"],
            "selected": writable,
            "disabled": not writable,
            "cells": {
                "path": plan["path"],
                "items": str(len(plan["names"])) if not plan["error"] else "-",
                "created": str(plan.get("created") or 0) if not plan["error"] else "-",
                "at_risk": {"text": str(at_risk), "tone": "warn" if at_risk else "muted"},
                "detail": detail,
            },
        })
    return {
        "title": TITLE,
        "host": "projectInstance",
        "summary": (
            f"Project: {project_name}\n"
            "Each ticked class sends every item it can, overwriting the matching ResQ objects "
            "with the Arco copies"
            + (f"; {at_risk_total} of them carry a ResQ change that would be lost." if at_risk_total else ".")
        ),
        "columns": [
            {"key": "path", "label": "Reserving Class", "width": 380},
            {"key": "items", "label": "Items", "width": 80},
            {"key": "created", "label": "Created in ResQ", "width": 130},
            {"key": "at_risk", "label": "Overwrites Newer ResQ", "width": 170},
            {"key": "detail", "label": "Details", "width": 420},
        ],
        "rows": rows,
        "acceptLabel": "Export Selected to ResQ",
        "cancelLabel": "Cancel",
        "searchPlaceholder": "Filter reserving classes",
        "emptyMessage": "No reserving class was compared.",
    }


def export_classes(ui, root, project_name: str, plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Export each accepted class whole; a Bridge that falls silent skips the rest."""

    from arcrho_api.resq_sync_queue import WRITE_TIMEOUT_SEC, BridgeUnavailableError, run_bridge_phase

    results: list[dict[str, Any]] = []
    total = len(plans)
    progress = ui.progress_bar(progress_id=PROGRESS_ID, title=TITLE, label="Exporting to ResQ", total=total)
    try:
        for position, plan in enumerate(plans, start=1):
            rc_path = plan["path"]
            try:
                result = run_bridge_phase(
                    server_root=root,
                    project_name=project_name,
                    rc_path=rc_path,
                    phase="export",
                    timeout_sec=WRITE_TIMEOUT_SEC,
                    progress=progress,
                    progress_label=f"Exporting to ResQ: {rc_path} ({position} of {total})",
                    on_poll=_report_activity,
                )
            except BridgeUnavailableError as exc:
                results.append({"path": rc_path, "error": str(exc)})
                results.extend(
                    {"path": rest["path"], "error": "Skipped: the Arco Bridge stopped responding, so this class was not sent."}
                    for rest in plans[position:]
                )
                break
            except Exception as exc:
                results.append({"path": rc_path, "error": str(exc)})
                continue
            items = [item for item in result.get("results") or [] if isinstance(item, dict)]
            counts = {"exported": 0, "saved": 0, "skipped": 0, "failed": 0}
            for item in items:
                outcome = str(item.get("outcome") or "")
                counts[outcome if outcome in counts else "failed"] += 1
            problems = [
                f"{item.get('name')}: {item.get('message')}"
                for item in items
                if str(item.get("outcome") or "") not in ("exported", "saved")
            ]
            results.append({"path": rc_path, "error": "", "counts": counts, "problems": problems})
    finally:
        progress.close(auto_close_ms=1500)
    return results


def result_table_payload(results: list[dict[str, Any]], project_name: str) -> dict[str, Any]:
    rows = []
    failed_classes = 0
    for index, item in enumerate(results, start=1):
        counts = item.get("counts") or {}
        if item["error"]:
            failed_classes += 1
            outcome = {"text": "Failed", "tone": "error"}
            detail = item["error"]
        elif counts.get("failed") or counts.get("skipped"):
            outcome = {"text": "Partly exported", "tone": "warn"}
            shown = item["problems"][:MAX_REPORTED_FAILURES]
            more = len(item["problems"]) - len(shown)
            detail = "; ".join(shown) + (f"; ... and {more} more" if more > 0 else "")
        else:
            outcome = {"text": "Exported", "tone": "ok"}
            detail = ""
        rows.append({
            "id": f"result-{index}",
            "cells": {
                "path": item["path"],
                "outcome": outcome,
                "exported": str(counts.get("exported", "")),
                "saved": str(counts.get("saved", "")),
                "skipped": str(counts.get("skipped", "")),
                "failed": str(counts.get("failed", "")),
                "detail": detail,
            },
        })
    exported = len(results) - failed_classes
    return {
        "title": "ResQ Batch Export Results",
        "host": "projectInstance",
        "selectable": False,
        "summary": (
            f"{'Export to ResQ completed with errors.' if failed_classes else 'Export to ResQ completed.'}\n"
            f"Project: {project_name} | Reserving classes exported: {exported} of {len(results)}"
        ),
        "columns": [
            {"key": "path", "label": "Reserving Class", "width": 360},
            {"key": "outcome", "label": "Outcome", "width": 130},
            {"key": "exported", "label": "Exported", "width": 90},
            {"key": "saved", "label": "Saved", "width": 80},
            {"key": "skipped", "label": "Skipped", "width": 80},
            {"key": "failed", "label": "Failed", "width": 80},
            {"key": "detail", "label": "Details", "width": 560},
        ],
        "rows": rows,
        "acceptLabel": "Close",
        "searchPlaceholder": "Filter results",
    }


def _selected_ids(completion) -> list[str]:
    selected = completion.get("selectedRowIds") or completion.get("selected_row_ids") or []
    return [str(value) for value in selected if str(value).strip()]


def run_macro(active_dfm=None, active_context=None):
    from arcrho_api import ArcRhoUI, get_server_root
    from arcrho_api.resq_sync_queue import BridgeUnavailableError, require_live_bridge_workers
    from arcrho_api.ui import await_review_table

    ui = ArcRhoUI()
    try:
        context = (
            active_context
            if _context_value(active_context, "projectName", "project_name")
            else ui.project_instance.context(timeout_sec=10)
        )
        project_name = _context_value(context, "projectName", "project_name")
        if not project_name:
            raise ValueError("The active Project Instance page does not expose a project.")
    except Exception as exc:
        message = f"Activate a Project Instance page for the project to export before running this macro.\n\n{exc}"
        _message(ui, message, kind="warning")
        return {"status": "cancelled", "message": message}

    try:
        root = get_server_root(required=True)
        require_live_bridge_workers(root)
        classes = listed_classes(project_name, _load_class_list())
        completion = await_review_table(ui, class_selection_payload(classes, project_name), on_poll=_report_activity)
        chosen = _selected_ids(completion) if completion.get("accepted") else []
        if not chosen:
            _message(ui, "Export cancelled; nothing was written to ResQ.", auto_close_ms=3000)
            return {"status": "cancelled", "message": "Export cancelled."}

        plans = preview_classes(ui, root, project_name, chosen)
        completion = await_review_table(ui, plan_table_payload(plans, project_name), on_poll=_report_activity)
        accepted = set(_selected_ids(completion)) if completion.get("accepted") else set()
        to_export = [plan for plan in plans if plan["path"] in accepted and plan["names"] and not plan["error"]]
        if not to_export:
            _message(ui, "Export cancelled; nothing was written to ResQ.", auto_close_ms=3000)
            return {"status": "cancelled", "message": "Export cancelled.", "plans": plans}

        results = export_classes(ui, root, project_name, to_export)
        payload = result_table_payload(results, project_name)
        await_review_table(ui, payload, on_poll=_report_activity)
        return {
            "status": "error" if any(item["error"] for item in results) else "success",
            "message": payload["summary"],
            "results": results,
        }
    except BridgeUnavailableError as exc:
        _message(ui, str(exc), title="Arco Bridge Unavailable", kind="warning")
        return {"status": "unavailable", "message": str(exc)}
    except Exception as exc:
        message = f"Export to ResQ failed.\n\nProject: {project_name}\n\n{exc}"
        _message(ui, message, kind="error")
        return {"status": "error", "message": message}


if __name__ == "__main__":
    print(run_macro())
