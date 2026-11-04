"""Engine worker for ArcRho project dates change jobs.

One job moves a whole project to new Origin Start, Origin End and Development
End Dates (docs/plans/project_dates_panel.md, step 4). Under the
project-scope lease it checks the date rule, records the previous dates,
saves the new ones, and then visits every reserving class under that class's
own lease:

1. hand-entered and imported datasets are reshaped (rows follow their true
   origin, columns keep their position, new cells empty) and listed for
   review; their coarser ``@n`` views are deleted;
2. Result Selection and Berquist-Sherman methods are moved onto the new
   periods, because their refresh reads values without labels;
3. every engine dataset is regenerated at the new shape and one dependent walk
   refreshes the calculated datasets and the methods. Development Factor,
   Bornhuetter Ferguson, Cape Cod and Bootstrap methods reshape inside their
   own refresh; one that cannot be reshaped declines and is listed.

The dates are saved first (decision 2), so a failure leaves the project half
moved. The pending record in ``arcrho_project_dates_job_contract`` keeps the
previous dates and what is already done, and running the same change again
resumes from there without moving any dataset twice.
"""

from __future__ import annotations

import csv
import io
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_dependent_propagation_contract import (
    DependentPropagationLeaseUnavailable,
    acquire_project_scope_lease,
    release_project_scope_lease,
    start_project_scope_lease_heartbeat,
    stop_project_scope_lease_heartbeat,
)
from arcrho_engine_job_lease import engine_job_lease_is_owned
from arcrho_project_dates_job_contract import (
    PROJECT_DATE_FIELDS,
    PROJECT_DATES_JOB_STATUS_HEARTBEAT_SECONDS,
    ProjectDatesJobContractError,
    clear_pending_record,
    normalize_date_set,
    pending_item_key,
    project_dates_job_request_path,
    read_pending_record,
    read_project_dates_job_status,
    request_dates,
    validate_project_dates_job_request,
    validate_request_id,
    write_pending_record,
    write_project_dates_job_status,
)

from arcrho_engine.dependent_propagation import configure_canonical_runtime
from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_engine.runtime_log import append_runtime_log

PROJECT_DATES_JOB_LOG_FILENAME = "project_dates_jobs.log"

from arcrho_api.period_reshape import REVIEW_LABELS_OFF_GRID, is_imported_dataset

#: Why a reshaped method is listed, beside ``period_reshape``'s dataset reasons.
REVIEW_METHOD_RESHAPED = "periods moved to the new dates"

Progress = dict[str, Any]


def _log(server_root: Any, message: str, *, exc: BaseException | None = None) -> None:
    append_runtime_log(server_root, PROJECT_DATES_JOB_LOG_FILENAME, message, exc=exc)


class ProjectDatesJobLeaseLost(RuntimeError):
    """Raised when the project-scope lease is no longer owned mid-job."""


class ProjectDatesJobRefused(RuntimeError):
    """The change was refused before anything was written; carries an HTTP code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


def _progress(stage: str, completed: int, total: int, label: str) -> Progress:
    return {
        "stage": str(stage or "").strip() or "processing",
        "completed": max(0, int(completed)),
        "total": max(0, int(total), int(completed)),
        "label": str(label or "").strip() or "Changing the project dates",
    }


def _safe_status_message(exc: BaseException) -> str:
    return _redact_machine_paths(exc) or "The project dates change failed."


def _empty_result(dates: Mapping[str, str]) -> dict[str, Any]:
    return {
        "dates": dict(dates),
        "previous_dates": {},
        "unchanged": False,
        "resumed": False,
        "classes_total": 0,
        "classes_refreshed": 0,
        "datasets_regenerated": 0,
        "datasets_failed": 0,
        "datasets_reshaped": 0,
        "methods_reshaped": 0,
        "methods_updated": 0,
        "review": [],
        "dependent_problems": [],
        "failures": [],
        "rerun_needed": False,
    }


def _current_dates(project_name: str) -> dict[str, str]:
    from app_server.services import project_settings_service

    data = project_settings_service.get_general_settings(project_name).get("data") or {}
    return {field: str(data.get(field) or "").strip() for field in PROJECT_DATE_FIELDS}


def _http_refusal(exc: BaseException) -> ProjectDatesJobRefused | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and 400 <= status_code < 600:
        return ProjectDatesJobRefused(status_code, str(getattr(exc, "detail", "") or exc))
    return None


# ---------------------------------------------------------------------------
# Hand-entered and imported datasets
# ---------------------------------------------------------------------------


def _read_grid(path: str) -> list[list[Any]]:
    """The stored cells as text, one list per row; a blank line is an empty origin."""

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        text = handle.read()
    rows = []
    for line in text.splitlines():
        cells = next(csv.reader([line]), []) if line else []
        rows.append([cell if cell.strip() else None for cell in cells])
    return rows


def _grid_text(values: list[list[Any]]) -> str:
    buffer = io.StringIO()
    for row in values:
        cells = ["" if cell is None else str(cell) for cell in row]
        if all(cell == "" for cell in cells) and len(cells) <= 1:
            buffer.write("\n")
            continue
        csv.writer(buffer, lineterminator="\n").writerow(cells)
    return buffer.getvalue()


def _write_text_atomic(path: str, text: str) -> None:
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)


def _delete_sibling_views(data_dir: str, dataset_name: str, csv_file: str) -> list[str]:
    """Delete the coarser ``@n`` copies beside a hand-entered dataset's own CSV."""

    from app_server.services.dataset_service import sanitize_dataset_file_name

    prefix = f"{sanitize_dataset_file_name(dataset_name)}@".casefold()
    keep = os.path.basename(csv_file).casefold()
    removed = []
    try:
        names = os.listdir(data_dir)
    except OSError:
        return removed
    for name in names:
        folded = name.casefold()
        if folded == keep or not folded.endswith(".csv") or not folded.startswith(prefix):
            continue
        try:
            os.remove(os.path.join(data_dir, name))
            removed.append(name)
        except OSError:
            pass
    return removed


def reshape_input_dataset_file(
    project_name: str,
    reserving_class: str,
    dataset_name: str,
    previous_dates: Mapping[str, str],
    dates: Mapping[str, str],
) -> dict[str, Any] | None:
    """Reshape one hand-entered or imported dataset on disk.

    Returns ``{"changed": bool, "review": [...]}``, or ``None`` when the
    dataset is not a stored hand-entered one (a calculated dataset is the
    dependent walk's). The CSV is written at its stored length first and the
    sidecar last, as every dataset save does.
    """

    from app_server import config
    from app_server.services import dataset_service
    from arcrho_api.period_reshape import (
        REVIEW_HAND_ENTERED,
        plan_input_dataset_reshape,
        reshape_input_dataset,
    )

    sidecar_path = dataset_service._get_dataset_sidecar_path(
        project_name, reserving_class, dataset_name
    )
    sidecar = dataset_service._read_dataset_sidecar(sidecar_path)
    if not sidecar or sidecar.get("calculated"):
        return None
    if not is_imported_dataset(sidecar):
        return None

    data_dir = config.get_project_dataset_cache_dir(project_name, reserving_class)
    csv_file = os.path.basename(str(sidecar.get("csv_file") or "").strip())
    csv_path = os.path.join(data_dir, csv_file) if csv_file else ""
    values = _read_grid(csv_path) if csv_path and os.path.isfile(csv_path) else []
    old_width = max((len(row) for row in values), default=0)
    shape = plan_input_dataset_reshape(sidecar, old_width, previous_dates, dates)
    plan = shape["origins"]
    if plan is None:
        return {"changed": False, "review": [REVIEW_HAND_ENTERED, REVIEW_LABELS_OFF_GRID]}
    if not shape["changed"]:
        return {"changed": False, "review": []}
    values = values + [[] for _ in range(len(plan["old"]) - len(values))]
    width = shape["width"]
    columns = shape["columns"]

    reshaped = reshape_input_dataset(
        sidecar, values, plan["old"], plan["new"], columns, column_count=width
    )
    out = reshaped["sidecar"]
    if plan["style"] != "index":
        out["origin_labels"] = list(plan["labels"])
    if columns is not None and "development_count" in out:
        out["development_count"] = len(columns)
    elif width is not None and "development_count" in out and out["development_count"] == old_width:
        out["development_count"] = width
    now = dataset_service._now_utc_iso()
    out["updated_at"] = now
    dataset_service._append_dataset_audit_entry(out, "Update", event_date=now)

    if csv_path:
        _write_text_atomic(csv_path, _grid_text(reshaped["values"]))
        _delete_sibling_views(data_dir, dataset_name, csv_file)
    dataset_service._write_dataset_sidecar_payload(sidecar_path, out)
    return {
        "changed": True,
        "review": list(reshaped["review"]),
        "link_rows_past_grid": reshaped["link_rows_past_grid"],
    }


# ---------------------------------------------------------------------------
# Methods whose refresh reads values without labels
# ---------------------------------------------------------------------------


def reshape_result_selection_file(
    project_name: str,
    reserving_class: str,
    name: str,
    previous_dates: Mapping[str, str],
    dates: Mapping[str, str],
) -> dict[str, Any]:
    """Move one Result Selection and its output sidecar onto the new origins."""

    from app_server.services import dataset_sidecar_status_service
    from app_server.services import result_selection_service as service
    from arcrho_api.period_reshape import project_dates_origin_plan
    from arcrho_api.result_selection_contract import reshape_result_selection_origins

    method_path = service._method_path(project_name, reserving_class, name)
    payload = service._read_json(method_path)
    if not payload:
        return {"changed": False, "review": []}
    payload = service.normalize_method_payload(payload, require_complete_basis=False)
    length = int(payload["details_tab"]["origin_length"])
    plan = project_dates_origin_plan(
        payload["method_tab"].get("origin_labels") or [], length, previous_dates, dates
    )
    if plan is None or plan["style"] == "index":
        return {"changed": False, "review": [REVIEW_LABELS_OFF_GRID]}
    if plan["old"] == plan["new"]:
        return {"changed": False, "review": []}
    reshape_result_selection_origins(payload, plan["labels"])

    sidecar_path = service._sidecar_path(project_name, reserving_class, name)
    with dataset_sidecar_status_service.sidecar_write_lock(sidecar_path):
        sidecar = service._read_json(sidecar_path)
        files = {
            method_path: service._json_text(payload),
            **service._output_files(project_name, reserving_class, payload),
        }
        if sidecar:
            sidecar = dict(sidecar)
            # The load check refuses a method whose output sidecar names
            # other origins, so the two move together.
            sidecar["origin_labels"] = list(plan["labels"])
            sidecar["updated_at"] = service._now()
            files[sidecar_path] = service._json_text(sidecar)
        service._commit_text_files(files, last_paths=[sidecar_path])
    return {"changed": True, "review": [REVIEW_METHOD_RESHAPED]}


def reshape_berquist_sherman_file(
    project_name: str,
    reserving_class: str,
    name: str,
    method_type: str,
    previous_dates: Mapping[str, str],
    dates: Mapping[str, str],
) -> dict[str, Any]:
    """Move one Berquist-Sherman method onto the new origins and columns."""

    from app_server.services import berquist_sherman_service as service
    from arcrho_api.berquist_sherman_contract import (
        BS_ANNUAL_PERIOD_LENGTH,
        reshape_berquist_sherman_periods,
    )
    from arcrho_api.period_reshape import (
        project_dates_development_labels,
        project_dates_origin_plan,
    )
    from arcrho_api.io import persisted_json_text

    sidecar = service._read_json(service._sidecar_path(project_name, reserving_class, name))
    method_name = str(sidecar.get("method_name") or "").strip() or name
    method_path = service.berquist_sherman_method_path(
        project_name, reserving_class, method_type, method_name
    )
    method = service._read_json(method_path)
    tab = method.get("method_tab") if isinstance(method.get("method_tab"), Mapping) else {}
    if not method:
        return {"changed": False, "review": []}
    plan = project_dates_origin_plan(
        tab.get("origin_labels") or [], BS_ANNUAL_PERIOD_LENGTH, previous_dates, dates
    )
    if plan is None or plan["style"] == "index":
        return {"changed": False, "review": [REVIEW_LABELS_OFF_GRID]}
    old_columns = [str(label) for label in tab.get("development_labels") or []]
    columns = project_dates_development_labels(
        old_columns, BS_ANNUAL_PERIOD_LENGTH, previous_dates, dates
    )
    columns = old_columns if columns is None else columns
    if plan["old"] == plan["new"] and columns == old_columns:
        return {"changed": False, "review": []}
    reshaped = reshape_berquist_sherman_periods(method, plan["labels"], columns)
    files = {method_path: persisted_json_text(reshaped)}
    if sidecar:
        # The output triangle's sidecar names its periods too, and the
        # methods built on it read their columns from there.
        from arcrho_api.sidecar_core_contract import finalize_sidecar

        out = dict(sidecar)
        if isinstance(out.get("origin_labels"), list):
            out["origin_labels"] = list(plan["labels"])
        if isinstance(out.get("development_labels"), list):
            out["development_labels"] = list(columns)
        files[service._sidecar_path(project_name, reserving_class, name)] = persisted_json_text(
            finalize_sidecar(out)
        )
    service._commit_text_files(files)
    return {"changed": True, "review": [REVIEW_METHOD_RESHAPED]}


# ---------------------------------------------------------------------------
# One class
# ---------------------------------------------------------------------------


def _reshape_class(
    project_name: str,
    reserving_class: str,
    previous_dates: Mapping[str, str],
    dates: Mapping[str, str],
    result: dict[str, Any],
    *,
    inputs_done: set[str],
    mark_input_done: Callable[[str], None],
) -> list[str]:
    """Reshape a class's hand-entered datasets and label-less methods.

    Runs under the class lease, before the engine datasets are regenerated.
    Returns the datasets the dependent walk has to start from as well.
    """

    from app_server.services import dataset_instance_index_service, dataset_sidecar_status_service
    from app_server.services.berquist_sherman_service import BERQUIST_SHERMAN_METHOD_TYPES

    roots: list[str] = []

    def review(name: str, kind: str, method_type: str, reasons: list[str], link_rows_past_grid: int = 0) -> None:
        # The method type lets the panel open the row the way the project tree does.
        if reasons:
            item = {
                "reserving_class": reserving_class,
                "name": name,
                "kind": kind,
                "method_type": method_type,
                "reasons": reasons,
            }
            if link_rows_past_grid:
                item["link_rows_past_grid"] = link_rows_past_grid
            result["review"].append(item)

    index = dataset_instance_index_service.get_index(project_name, reserving_class)
    for row in index.get("files") or []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        source_kind = str(row.get("source_kind") or "").strip().casefold()
        method_type = dataset_sidecar_status_service.normalize_method_type(
            row.get("method_type"), row.get("source_kind")
        )
        # A class walked again after problems must not move anything twice.
        key = pending_item_key(reserving_class, name)
        if key in inputs_done:
            continue
        try:
            if source_kind in {"input", "engine"}:
                outcome = reshape_input_dataset_file(
                    project_name, reserving_class, name, previous_dates, dates
                )
                if outcome is None:
                    continue
                source_kind = "input"
                if outcome["changed"]:
                    result["datasets_reshaped"] += 1
                    roots.append(name)
                review(name, "dataset", method_type, outcome["review"], outcome.get("link_rows_past_grid", 0))
                mark_input_done(key)
            elif method_type == dataset_sidecar_status_service.METHOD_TYPE_RESULT_SELECTION:
                outcome = reshape_result_selection_file(
                    project_name, reserving_class, name, previous_dates, dates
                )
            elif method_type in BERQUIST_SHERMAN_METHOD_TYPES:
                outcome = reshape_berquist_sherman_file(
                    project_name, reserving_class, name, method_type, previous_dates, dates
                )
            else:
                continue
        except Exception as exc:
            result["failures"].append(f"{reserving_class}: {name}: {_redact_machine_paths(exc)}")
            review(
                name,
                "dataset" if source_kind in {"input", "engine"} else "method",
                method_type,
                ["could not be reshaped"],
            )
            continue
        if source_kind != "input":
            if outcome["changed"]:
                result["methods_reshaped"] += 1
                roots.append(name)
            review(name, "method", method_type, outcome["review"])
            mark_input_done(key)
    return roots


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------


def execute_project_dates_change(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    progress_callback: Callable[[Progress], None] | None = None,
    record_previous_dates: Callable[[Mapping[str, str]], None] | None = None,
) -> dict[str, Any]:
    """Run one validated dates change and return its result summary.

    ``record_previous_dates`` is called with the dates the project is moved
    from before the new ones are saved, so the job status names them.
    """

    normalized = validate_project_dates_job_request(request)
    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    configure_canonical_runtime(root)

    from app_server.services import (
        arcrho_runtime_service,
        project_settings_service,
        user_identity_service,
    )
    from arcrho_engine import source_table_refresh

    def notify(stage: str, completed: int, total: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback(_progress(stage, completed, total, label))

    project_name = normalized["ProjectName"]
    request_id = normalized["RequestId"]
    dates = request_dates(normalized)
    result = _empty_result(dates)
    started = time.monotonic()
    _log(root, f"{request_id} start project={project_name!r} dates={dates}")

    with user_identity_service.acting_identity(normalized["UserName"]):
        notify("checking", 0, 0, "Checking the project dates")
        try:
            current = _current_dates(project_name)
        except Exception as exc:
            refusal = _http_refusal(exc)
            if refusal is not None:
                raise refusal from exc
            raise
        try:
            pending = read_pending_record(root, project_name)
        except (OSError, ValueError) as exc:
            raise ProjectDatesJobRefused(
                409, "The record of an unfinished date change could not be read."
            ) from exc
        if pending is not None and pending["dates"] != dates:
            raise ProjectDatesJobRefused(
                409,
                "An earlier change of the project dates has not finished. "
                "Run that change again before choosing other dates.",
            )
        if pending is not None:
            previous = pending["previous_dates"]
            classes_done = list(pending["classes_done"])
            inputs_done = set(pending["inputs_done"])
            classes_retried = list(pending["classes_retried"])
            result["resumed"] = True
        else:
            if current == dates:
                result["previous_dates"] = dict(current)
                result["unchanged"] = True
                notify("complete", 0, 0, "The project dates are already these")
                return result
            try:
                previous = normalize_date_set(current, "previous_dates", enforce_rule=False)
            except ProjectDatesJobContractError as exc:
                raise ProjectDatesJobRefused(
                    422,
                    "The project's current dates are missing or invalid, so nothing can say "
                    "where its stored rows belong.",
                ) from exc
            classes_done = []
            inputs_done = set()
            classes_retried = []
        result["previous_dates"] = dict(previous)

        def save_pending() -> None:
            write_pending_record(
                root,
                project_name=project_name,
                request_id=request_id,
                previous_dates=previous,
                dates=dates,
                classes_done=classes_done,
                inputs_done=sorted(inputs_done),
                classes_retried=classes_retried,
            )

        # The previous dates are on disk before the new ones, so a run that
        # stops after the save can still be resumed.
        save_pending()
        if record_previous_dates is not None:
            record_previous_dates(previous)

        notify("saving", 0, 0, "Saving the project dates")
        if current != dates:
            try:
                project_settings_service.update_general_settings(
                    project_name,
                    origin_start_date=dates["origin_start_date"],
                    origin_end_date=dates["origin_end_date"],
                    development_end_date=dates["development_end_date"],
                )
            except Exception as exc:
                refusal = _http_refusal(exc)
                if refusal is not None:
                    if not result["resumed"]:
                        clear_pending_record(root, project_name)
                    raise refusal from exc
                raise
        try:
            arcrho_runtime_service.clear_arcrho_headers_cache(project_name)
        except Exception as exc:
            _log(root, "header cache clear failed", exc=exc)

        done_keys = {name.casefold() for name in classes_done}
        classes = [
            reserving_class
            for reserving_class in source_table_refresh._reserving_class_paths(project_name)
            if reserving_class.casefold() not in done_keys
        ]
        result["classes_total"] = len(classes)
        total = len(classes)

        def mark_input_done(key: str) -> None:
            inputs_done.add(key)
            save_pending()

        for index, reserving_class in enumerate(classes, start=1):
            def on_dataset(dataset_name: str, _class=reserving_class, _done=index - 1) -> None:
                notify("classes", _done, total, f"Refreshing {_class}: {dataset_name}")

            notify("classes", index - 1, total, f"Reshaping {reserving_class} ({index} of {total})")
            class_started = time.monotonic()
            problems_before = (len(result["failures"]), result["datasets_failed"])
            try:
                source_table_refresh._refresh_one_reserving_class(
                    root,
                    project_name,
                    reserving_class,
                    result,
                    on_dataset=on_dataset,
                    prepare=lambda _class=reserving_class: _reshape_class(
                        project_name,
                        _class,
                        previous,
                        dates,
                        result,
                        inputs_done=inputs_done,
                        mark_input_done=mark_input_done,
                    ),
                )
                result["classes_refreshed"] += 1
                problems_after = (len(result["failures"]), result["datasets_failed"])
                retried = reserving_class.casefold() in {name.casefold() for name in classes_retried}
                if problems_after == problems_before or retried:
                    classes_done.append(reserving_class)
                else:
                    # Decision 2: running the same change again walks this
                    # class once more, after the classes it may depend on.
                    classes_retried.append(reserving_class)
                save_pending()
            except DependentPropagationLeaseUnavailable as exc:
                result["failures"].append(_redact_machine_paths(exc))
                _log(root, f"{reserving_class} skipped: {exc}")
            except Exception as exc:
                result["failures"].append(f"{reserving_class}: {_redact_machine_paths(exc)}")
                _log(root, f"{reserving_class} failed", exc=exc)
            finally:
                _log(root, f"{reserving_class} took {time.monotonic() - class_started:.2f}s")

        done_keys = {name.casefold() for name in classes_done}
        unfinished = [name for name in classes if name.casefold() not in done_keys]
        result["rerun_needed"] = bool(unfinished)
        if not unfinished:
            clear_pending_record(root, project_name)
        notify("complete", total, total, "Project dates changed")

    _log(
        root,
        f"{request_id} done in {time.monotonic() - started:.2f}s "
        f"classes={result['classes_refreshed']}/{result['classes_total']} "
        f"regenerated={result['datasets_regenerated']} reshaped={result['datasets_reshaped']} "
        f"methods_reshaped={result['methods_reshaped']} methods_updated={result['methods_updated']} "
        f"failed={result['datasets_failed']} review={len(result['review'])}",
    )
    return result


def summarize_failures(result: Mapping[str, Any] | None) -> str:
    """One sentence for a change that saved the dates but fell short."""

    if not isinstance(result, Mapping):
        return ""
    failures = [str(item or "").strip() for item in result.get("failures") or []]
    failures = [item for item in failures if item]
    if not failures:
        return ""
    counts = []
    if int(result.get("datasets_failed") or 0):
        counts.append(f"{int(result['datasets_failed'])} dataset(s) could not be refreshed")
    unfinished = int(result.get("classes_total") or 0) - int(result.get("classes_refreshed") or 0)
    if unfinished > 0:
        counts.append(f"{unfinished} reserving class(es) were not finished")
    head = "; ".join(counts) if counts else "the refresh reported problems"
    # Only a change that kept its pending record can do more when run again;
    # otherwise every class has had its second walk and the rest is listed.
    action = (
        "Run the same change again to finish it."
        if result.get("rerun_needed")
        else "Running it again will not change them; review them in the list."
    )
    return f"The dates were saved, but {head}. {action} First problem: {failures[0]}"


# ---------------------------------------------------------------------------
# Durable queue processing
# ---------------------------------------------------------------------------


def _require_lease(lease) -> None:
    if lease.heartbeat_failed.is_set() or not engine_job_lease_is_owned(lease):
        raise ProjectDatesJobLeaseLost("Project dates job project ownership was lost.")


def _terminal_status_or_none(server_root: Path, request_id: str) -> dict[str, Any] | None:
    try:
        status = read_project_dates_job_status(server_root, request_id)
    except (OSError, ValueError, TypeError):
        return None
    if status is not None and status["status"] in {"success", "error"}:
        return status
    return None


def _remove_request_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"(project dates job queue cleanup error: {exc})")


def process_durable_project_dates_request(
    server_root: str | os.PathLike[str],
    request_file: str | os.PathLike[str],
    request: Mapping[str, Any],
) -> bool:
    """Process one retained queue file under the project-scope lease."""

    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    request_path = Path(os.fspath(request_file))
    raw_request_id = request.get("RequestId") if isinstance(request, Mapping) else None
    try:
        request_id = validate_request_id(raw_request_id)
    except ProjectDatesJobContractError as exc:
        print(f"(project dates job request error: {_safe_status_message(exc)})")
        _remove_request_file(request_path)
        return False
    try:
        if request_path.resolve(strict=False) != project_dates_job_request_path(
            root, request_id
        ).resolve(strict=False):
            print("(project dates job request filename does not match RequestId)")
            return False
    except OSError:
        return False

    terminal = _terminal_status_or_none(root, request_id)
    if terminal is not None:
        _remove_request_file(request_path)
        return terminal["status"] == "success"

    try:
        normalized = validate_project_dates_job_request(request)
    except ProjectDatesJobContractError as exc:
        message = _safe_status_message(exc)
        try:
            write_project_dates_job_status(
                root,
                request_id,
                "error",
                progress=_progress("rejected", 0, 0, "Project dates change rejected"),
                message=message,
                status_code=400,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish rejected project dates job status: "
                f"{_redact_machine_paths(status_exc)})"
            )
            return False
        _remove_request_file(request_path)
        return False

    lease = acquire_project_scope_lease(root, normalized["ProjectName"])
    if lease is None:
        _log(root, f"{request_id} claim missed (project busy)")
        return False
    claimed_at = time.monotonic()
    heartbeat_stop, heartbeat_thread = start_project_scope_lease_heartbeat(lease)
    try:
        status_write_lock = threading.Lock()
        current_progress = _progress("starting", 0, 0, "Preparing the project dates change")
        previous_dates: dict[str, str] | None = None

        def publish(
            status: str,
            progress: Progress,
            *,
            message: str = "",
            status_code: int | None = None,
            result: Mapping[str, Any] | None = None,
        ) -> None:
            _require_lease(lease)
            with status_write_lock:
                write_project_dates_job_status(
                    root,
                    request_id,
                    status,
                    progress=progress,
                    message=message,
                    status_code=status_code,
                    previous_dates=previous_dates,
                    result=result,
                )

        def record_progress(progress: Progress) -> None:
            nonlocal current_progress
            current_progress = progress
            publish("processing", progress)

        def record_previous(dates: Mapping[str, str]) -> None:
            nonlocal previous_dates
            previous_dates = dict(dates)
            publish("processing", current_progress)

        heartbeat_stop_event = threading.Event()

        def status_heartbeat_loop() -> None:
            while not heartbeat_stop_event.wait(PROJECT_DATES_JOB_STATUS_HEARTBEAT_SECONDS):
                try:
                    publish("processing", current_progress)
                except Exception:
                    return

        status_heartbeat_thread = threading.Thread(
            target=status_heartbeat_loop,
            name=f"arcrho-project-dates-status-{request_id[:8]}",
            daemon=True,
        )

        terminal_result: dict[str, Any] | None = None
        terminal_code: int | None = None
        try:
            publish("processing", current_progress)
            status_heartbeat_thread.start()
            try:
                terminal_result = execute_project_dates_change(
                    root,
                    normalized,
                    progress_callback=record_progress,
                    record_previous_dates=record_previous,
                )
            finally:
                heartbeat_stop_event.set()
                status_heartbeat_thread.join(timeout=PROJECT_DATES_JOB_STATUS_HEARTBEAT_SECONDS * 2)
            # The dates are saved even when a class fell short, so the job
            # succeeds and its message says how to finish the rest.
            terminal_state = "success"
            terminal_message = summarize_failures(terminal_result)
            terminal_progress = _progress(
                "complete", current_progress["total"], current_progress["total"], "Project dates changed"
            )
        except ProjectDatesJobLeaseLost:
            _log(root, f"{request_id} project ownership was lost")
            return False
        except ProjectDatesJobRefused as exc:
            terminal_state = "error"
            terminal_message = _safe_status_message(exc)
            terminal_code = exc.status_code
            terminal_progress = current_progress
            _log(root, f"{request_id} refused {terminal_code}: {terminal_message}")
        except Exception as exc:
            terminal_state = "error"
            terminal_message = _safe_status_message(exc)
            terminal_code = 500
            terminal_progress = current_progress
            _log(root, f"{request_id} raised: {terminal_message}", exc=exc)

        _log(
            root,
            f"{request_id} {terminal_state} after {time.monotonic() - claimed_at:.2f}s"
            + (f": {terminal_message}" if terminal_message else ""),
        )
        try:
            publish(
                terminal_state,
                terminal_progress,
                message=terminal_message,
                status_code=terminal_code,
                result=terminal_result,
            )
        except Exception as status_exc:
            _log(
                root,
                f"could not publish project dates job status: {_redact_machine_paths(status_exc)}",
                exc=status_exc,
            )
            return False
        if _terminal_status_or_none(root, request_id) is not None:
            _remove_request_file(request_path)
        return terminal_state == "success"
    except ProjectDatesJobLeaseLost:
        return False
    finally:
        stop_project_scope_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        release_project_scope_lease(lease)
