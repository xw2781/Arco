"""One retention rule for finished job status files: ninety days, then gone.

Every durable job on the Arco Server -- a dependent refresh, a source refresh,
a dataset-type change, a rules save, a project dates change, a project
duplication, a ResQ import or sync -- leaves one small status file behind when
it ends. Pollers and operators read it afterwards, and nothing ever removed it.
This module owns the single answer: a status file that says its job finished is
kept for :data:`JOB_STATUS_RETENTION_DAYS` days after it was last written.

Only a file that parses and names a finished state is removed. A queued or
processing status, a file that cannot be read, and every request, lock, lease
and pending marker are left exactly as they are. Like log retention, this is
best effort and never fails the component that runs it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from arcrho_api.bridge_liveness import QUEUE_STATUS_DIRS
from arcrho_data_processing_rules_job_contract import (
    data_processing_rules_job_statuses_directory,
)
from arcrho_dataset_types_change_contract import dataset_types_change_statuses_directory
from arcrho_dependent_propagation_contract import dependent_propagation_statuses_directory
from arcrho_project_dates_job_contract import project_dates_job_statuses_directory
from arcrho_project_duplication_contract import (
    project_duplication_cancel_path,
    project_duplication_status_directory,
    project_duplication_submission_receipt_path,
)
from arcrho_source_refresh_contract import source_refresh_statuses_directory

# Three months outlasts a quarterly reserve review, so the status of anything
# run for one review is still there when the next one starts.
JOB_STATUS_RETENTION_DAYS = 90

# What a status file's ``status`` says once its job will never write again.
FINISHED_JOB_STATUS_VALUES = frozenset({"success", "error", "cancelled"})


def job_status_directories(server_root: str | os.PathLike[str]) -> tuple[Path, ...]:
    """Every folder that holds one status file per durable job."""

    root = Path(os.fspath(server_root))
    return (
        dependent_propagation_statuses_directory(server_root),
        source_refresh_statuses_directory(server_root),
        dataset_types_change_statuses_directory(server_root),
        data_processing_rules_job_statuses_directory(server_root),
        project_dates_job_statuses_directory(server_root),
        project_duplication_status_directory(server_root),
        *(root / relative for relative in QUEUE_STATUS_DIRS.values()),
    )


def _discard_project_duplication_companions(
    server_root: str | os.PathLike[str], request_id: str
) -> None:
    """Drop the submission receipt, its lock and the cancel marker of one job."""

    try:
        receipt = project_duplication_submission_receipt_path(server_root, request_id)
        companions = (
            receipt,
            receipt.with_name(f".{receipt.name}.lock"),
            project_duplication_cancel_path(server_root, request_id),
        )
    except ValueError:
        return
    for path in companions:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def prune_finished_job_statuses(
    server_root: str | os.PathLike[str],
    *,
    days: int = JOB_STATUS_RETENTION_DAYS,
    now: float | None = None,
) -> int:
    """Delete every finished job status last written before the cutoff.

    ``now`` is a Unix timestamp and exists for tests. Returns how many status
    files were deleted.
    """

    cutoff = (time.time() if now is None else now) - days * 86400
    duplication_directory = project_duplication_status_directory(server_root)
    removed = 0
    for directory in job_status_directories(server_root):
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if not entry.name.endswith(".json") or not entry.is_file():
                    continue
                if entry.stat().st_mtime >= cutoff:
                    continue
                with open(entry.path, encoding="utf-8-sig") as stream:
                    payload = json.load(stream)
                if not isinstance(payload, dict):
                    continue
                if payload.get("status") not in FINISHED_JOB_STATUS_VALUES:
                    continue
                os.unlink(entry.path)
            except (OSError, ValueError):
                continue
            removed += 1
            if directory == duplication_directory:
                _discard_project_duplication_companions(server_root, entry.name[: -len(".json")])
    return removed
