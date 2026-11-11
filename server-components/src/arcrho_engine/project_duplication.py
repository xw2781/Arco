"""Transactional, server-local ArcRho project duplication."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
# Nothing here uses the alias directly: the reparse-point tests reach the
# Windows file-attribute constants through this module's attribute, so the
# import has to stay put.
import stat as stat_module  # pyright: ignore[reportUnusedImport]
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable, Mapping

from arcrho_engine_job_lease import (
    EngineJobLease,
    acquire_engine_job_lease,
    engine_job_lease_owner,
    refresh_engine_job_lease,
    start_engine_job_lease_heartbeat,
    stop_engine_job_lease_heartbeat,
)
from arcrho_project_duplication_contract import (
    PROJECT_DUPLICATION_TERMINAL_STATUS_VALUES,
    PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES,
    ProjectDuplicationContractError,
    clear_project_duplication_cancel_request,
    encode_project_directory_segment,
    path_is_link_or_reparse as _canonical_path_is_link_or_reparse,
    project_duplication_cancel_requested,
    project_duplication_lock_directory,
    project_duplication_projects_path,
    project_duplication_request_path,
    project_duplication_status_path,
    validate_project_duplication_request,
    validate_project_duplication_status,
    validate_request_id,
    stat_is_reparse_point as _canonical_stat_is_reparse_point,
    write_json_atomic,
    write_project_duplication_status,
    write_project_duplication_status_for_request_id,
)

from arcrho_engine.runtime_log import append_runtime_log


Progress = dict[str, Any]
ProgressCallback = Callable[[Progress], None]
CommitCallback = Callable[[int], None]
OwnershipCallback = Callable[[], None]

_STAGING_PREFIX = ".arcrho-project-duplication-"
_LOCK_SUFFIX = ".lock"
_DRIVE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\)[^\s\"']+")
PROJECT_DUPLICATION_LOCK_STALE_SECONDS = 6 * 60 * 60
PROJECT_DUPLICATION_CLAIM_STALE_SECONDS = 5 * 60.0
PROJECT_DUPLICATION_CLAIM_HEARTBEAT_SECONDS = 5.0
PROJECT_DUPLICATION_JOURNAL_VERSION = 1

# A duplication driven from a workstation copies every file over SMB, where a
# scanner holding a just-written handle or a momentary session drop raises a
# transient OSError. Without a retry one such error aborts the whole project,
# so each copy step is attempted again before the job is failed.
PROJECT_DUPLICATION_COPY_ATTEMPTS = 4
PROJECT_DUPLICATION_COPY_RETRY_SECONDS = (0.5, 1.5, 3.0)

# The app rewrites these while people merely have the source project open:
# per-user preferences and review exports, caches that check their own
# staleness when read, and each reserving class's index, which is rebuilt
# whenever its folder signature no longer matches. They are still copied, but
# a change to them during the copy leaves the copy consistent, so the
# "did the source change?" comparison skips them.
_UNCOMPARED_PROJECT_DIR_NAMES = frozenset({"users"})
_UNCOMPARED_PROJECT_FILE_NAMES = frozenset(
    {
        "table_summary.json",
        "reserving_class_combinations_cache.json",
        "reserving_class_path_tree_cache.json",
    }
)
_UNCOMPARED_CLASS_FILE_NAMES = frozenset({"index.json"})

# The shared status message is deliberately location-independent, so the real
# OSError is only recoverable from this server-local log. Its rotation and
# append semantics belong to `arcrho_engine.runtime_log`.
PROJECT_DUPLICATION_LOG_RELATIVE_PATH = ("runtime", "logs", "project_duplication.log")


class ProjectDuplicationError(RuntimeError):
    """Raised when a project cannot be duplicated safely."""


class ProjectDuplicationRecoveryRequired(ProjectDuplicationError):
    """Raised when a visible target must be preserved for manual recovery."""


class ProjectDuplicationLeaseLost(ProjectDuplicationError):
    """Raised when another Engine has taken ownership of the request."""


class ProjectDuplicationRetryableRecovery(ProjectDuplicationError):
    """Raised when durable recovery should be retried without terminal status."""


class ProjectDuplicationCancelled(ProjectDuplicationError):
    """Raised when the submitting user asked for the copy to stop.

    Only raised between copy steps and never after the staging folder has
    been renamed into place, so a cancelled job leaves nothing behind.
    """


def _raise_if_cancelled(server_root: str | os.PathLike[str], request_id: str) -> None:
    if project_duplication_cancel_requested(server_root, request_id):
        raise ProjectDuplicationCancelled(
            "Project duplication was cancelled before the copy was published."
        )


@dataclass(frozen=True)
class _TargetLock:
    path: Path
    owner_token: str


@dataclass(frozen=True)
class _RequestLease(EngineJobLease):
    request_id: str


def _progress(stage: str, completed: int, total: int, label: str) -> Progress:
    return {
        "stage": stage,
        "completed": completed,
        "total": total,
        "label": label,
    }


def _redact_machine_paths(message: Any) -> str:
    text = str(message if message is not None else "").strip()
    return _DRIVE_PATH_RE.sub("[path]", text) or "Project duplication failed."


def _safe_status_error(exc: Exception) -> str:
    """Return a location-independent error suitable for shared status JSON."""

    if isinstance(exc, (ProjectDuplicationError, ProjectDuplicationContractError)):
        return _redact_machine_paths(exc)
    if isinstance(exc, (OSError, shutil.Error)):
        return "The Arco Server filesystem could not complete project duplication."
    return "Project duplication failed."


def _duplication_log_path(server_root: str | os.PathLike[str]) -> Path:
    return Path(server_root).joinpath(*PROJECT_DUPLICATION_LOG_RELATIVE_PATH)


def log_duplication_event(
    server_root: str | os.PathLike[str],
    message: str,
    *,
    exc: BaseException | None = None,
) -> None:
    """Record the unredacted diagnosis beside the other ArcRho runtime logs.

    The Engine is packaged with ``--noconsole``, so a bare ``print`` is lost on
    every deployed machine. Logging must never fail a duplication, so every
    error here is swallowed.
    """

    append_runtime_log(
        server_root, PROJECT_DUPLICATION_LOG_RELATIVE_PATH[-1], message, exc=exc
    )


def _discard_failed_copy(destination: Path) -> None:
    """Clear a partial destination so the next copy attempt starts clean."""

    try:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination, ignore_errors=True)
        else:
            destination.unlink()
    except OSError:
        pass


def _copy_with_retry(
    server_root: str | os.PathLike[str],
    request_id: str,
    label: str,
    destination: Path,
    copy: Callable[[], Any],
) -> None:
    """Run one copy step, retrying the transient share errors that abort jobs."""

    attempts = max(1, PROJECT_DUPLICATION_COPY_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            copy()
            if attempt > 1:
                log_duplication_event(
                    server_root,
                    f"request={request_id} {label}: succeeded on attempt {attempt}",
                )
            return
        except (OSError, shutil.Error) as exc:
            if attempt >= attempts:
                log_duplication_event(
                    server_root,
                    f"request={request_id} {label}: failed after {attempt} attempts",
                    exc=exc,
                )
                raise
            log_duplication_event(
                server_root,
                f"request={request_id} {label}: attempt {attempt} failed, retrying",
                exc=exc,
            )
            _discard_failed_copy(destination)
            delays = PROJECT_DUPLICATION_COPY_RETRY_SECONDS
            time.sleep(delays[min(attempt - 1, len(delays) - 1)] if delays else 0)


def _direct_child(parent: Path, segment: str, label: str) -> Path:
    if not segment or segment in {".", ".."} or Path(segment).name != segment:
        raise ProjectDuplicationError(f"Unsafe {label} name.")
    resolved_parent = parent.resolve(strict=False)
    child = (resolved_parent / segment).resolve(strict=False)
    if child.parent != resolved_parent:
        raise ProjectDuplicationError(f"Unsafe {label} path.")
    return child


def _stat_is_reparse_point(metadata: Any) -> bool:
    return _canonical_stat_is_reparse_point(metadata)


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        return _canonical_path_is_link_or_reparse(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ProjectDuplicationError(
            "A project-duplication filesystem path could not be inspected safely."
        ) from exc
    return _stat_is_reparse_point(metadata)


def _verified_projects_directory_path(
    server_root: Path,
    projects_directory: str,
) -> Path:
    """Resolve the configured project store without following linked segments."""

    canonical = project_duplication_projects_path(
        server_root,
        projects_directory,
    )
    try:
        parts = canonical.relative_to(server_root).parts
    except ValueError as exc:
        raise ProjectDuplicationError(
            "Unsafe Arco Server projects directory."
        ) from exc

    current = server_root
    for part in parts:
        candidate = current / part
        try:
            linked = _path_is_link_or_reparse(candidate)
        except ProjectDuplicationError as exc:
            raise ProjectDuplicationError(
                "The Arco Server projects directory could not be inspected safely."
            ) from exc
        if linked:
            raise ProjectDuplicationError(
                "The Arco Server projects directory contains a symbolic link or "
                "reparse point."
            )
        current = candidate
    return _extended_length_path(current)


def _extended_length_path(path: Path) -> Path:
    """Return an absolute ``path`` in the form Windows exempts from MAX_PATH.

    A long reserving-class folder under the staging name passes 260
    characters, and the machine-wide long-path setting is off on the Server
    PC. Every path the copy derives from the projects folder inherits this.
    """

    text = str(path)
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


def _find_child_case_insensitive(parent: Path, segment: str) -> Path | None:
    """Find one direct child using the Windows case-insensitive identity rule."""

    direct = _direct_child(parent, segment, "project folder")
    if direct.exists() or direct.is_symlink():
        return direct
    target = segment.casefold()
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.casefold() == target:
                    return Path(entry.path)
    except FileNotFoundError:
        return None
    return None


def _verified_protocol_directory(server_root: Path, name: str) -> Path:
    """Create one protocol directory without traversing a symlink ancestor."""

    canonical_root = project_duplication_lock_directory(server_root).parent
    try:
        protocol_parts = canonical_root.relative_to(server_root).parts
    except ValueError as exc:
        raise ProjectDuplicationError(
            "Unsafe project-duplication protocol path."
        ) from exc

    current = server_root
    for part in protocol_parts:
        candidate = current / part
        if _path_is_link_or_reparse(candidate):
            raise ProjectDuplicationError(
                "Refusing to use a symbolic link or reparse point in the "
                "project-duplication "
                "protocol path."
            )
        candidate.mkdir(exist_ok=True)
        if _path_is_link_or_reparse(candidate) or not candidate.is_dir():
            raise ProjectDuplicationError(
                "The project-duplication protocol path is not a safe directory."
            )
        current = _direct_child(
            current,
            part,
            "project-duplication protocol folder",
        )

    directory = _direct_child(current, name, "project-duplication job folder")
    if _path_is_link_or_reparse(directory):
        raise ProjectDuplicationError(
            "Refusing to use a symbolic link or reparse point as a "
            "project-duplication job folder."
        )
    directory.mkdir(exist_ok=True)
    if _path_is_link_or_reparse(directory) or not directory.is_dir():
        raise ProjectDuplicationError(
            "The project-duplication job folder is not a safe directory."
        )
    return directory


def _engine_job_directory(server_root: Path, name: str) -> Path:
    return _verified_protocol_directory(server_root, name)


def _request_claim_path(server_root: Path, request_id: str) -> Path:
    claim_dir = _engine_job_directory(server_root, "claims")
    return _direct_child(claim_dir, f"{request_id}.json", "request claim")


def _recovery_journal_path(server_root: Path, request_id: str) -> Path:
    journal_dir = _engine_job_directory(server_root, "recovery")
    return _direct_child(journal_dir, f"{request_id}.json", "recovery journal")


def _read_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ProjectDuplicationError("Project-duplication metadata is invalid.")
    return payload


def _acquire_request_lease(
    server_root: Path,
    request_id: str,
) -> _RequestLease | None:
    """Claim a durable request, recovering only a genuinely stale lease."""

    claim_path = _request_claim_path(server_root, request_id)
    lease = acquire_engine_job_lease(
        claim_path,
        stale_seconds=PROJECT_DUPLICATION_CLAIM_STALE_SECONDS,
        payload_fields={"request_id": request_id},
    )
    if lease is None:
        return None
    return _RequestLease(
        path=lease.path,
        owner_token=lease.owner_token,
        heartbeat_failed=lease.heartbeat_failed,
        request_id=request_id,
    )


def _request_lease_owner(lease: _RequestLease) -> str | None:
    return engine_job_lease_owner(lease.path)


def _request_lease_is_owned(lease: _RequestLease) -> bool:
    return _request_lease_owner(lease) == lease.owner_token


def _require_request_lease(lease: _RequestLease) -> None:
    if lease.heartbeat_failed.is_set() or not _request_lease_is_owned(lease):
        raise ProjectDuplicationLeaseLost(
            "Project-duplication request ownership was lost."
        )


def _refresh_request_lease(lease: _RequestLease) -> bool:
    return refresh_engine_job_lease(lease)


def _release_request_lease(lease: _RequestLease | None) -> None:
    # Ownership is re-read through the module-level predicate so cooperating
    # tests (and the shared-lease comment on unfenced release) stay honest.
    if (
        lease is None
        or lease.heartbeat_failed.is_set()
        or not _request_lease_is_owned(lease)
    ):
        return
    try:
        lease.path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _start_request_lease_heartbeat(lease: _RequestLease) -> tuple[Event, Thread]:
    return start_engine_job_lease_heartbeat(
        lease,
        interval_seconds=PROJECT_DUPLICATION_CLAIM_HEARTBEAT_SECONDS,
        refresh=lambda: _refresh_request_lease(lease),
        thread_name=f"arcrho-project-duplication-lease-{lease.request_id}",
    )


def _stop_request_lease_heartbeat(stop_event: Event, thread: Thread) -> None:
    stop_engine_job_lease_heartbeat(
        stop_event,
        thread,
        interval_seconds=PROJECT_DUPLICATION_CLAIM_HEARTBEAT_SECONDS,
    )


def _build_recovery_journal(
    request: Mapping[str, Any],
    verified_manifest: str,
    reserving_class_total: int,
) -> dict[str, Any]:
    normalized = validate_project_duplication_request(request)
    if not re.fullmatch(r"[0-9a-f]{64}", str(verified_manifest)):
        raise ProjectDuplicationError("Verified project manifest is invalid.")
    if (
        isinstance(reserving_class_total, bool)
        or not isinstance(reserving_class_total, int)
        or reserving_class_total < 0
    ):
        raise ProjectDuplicationError("Reserving-class total is invalid.")
    return {
        "journal_version": PROJECT_DUPLICATION_JOURNAL_VERSION,
        "request": normalized,
        "verified_manifest": verified_manifest,
        "reserving_class_total": reserving_class_total,
    }


def _validate_recovery_journal(
    payload: Any,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal is invalid."
        )
    required = {
        "journal_version",
        "request",
        "verified_manifest",
        "reserving_class_total",
    }
    if set(payload) != required:
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal is invalid."
        )
    if payload.get("journal_version") != PROJECT_DUPLICATION_JOURNAL_VERSION:
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal version is unsupported."
        )
    try:
        journal_request = validate_project_duplication_request(payload.get("request"))
    except ProjectDuplicationContractError as exc:
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal request is invalid."
        ) from exc
    if journal_request != validate_project_duplication_request(request):
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal does not match its request."
        )
    manifest = payload.get("verified_manifest")
    if not isinstance(manifest, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest):
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal manifest is invalid."
        )
    total = payload.get("reserving_class_total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal total is invalid."
        )
    return {
        "journal_version": PROJECT_DUPLICATION_JOURNAL_VERSION,
        "request": journal_request,
        "verified_manifest": manifest,
        "reserving_class_total": total,
    }


def _write_recovery_journal(
    server_root: Path,
    request: Mapping[str, Any],
    verified_manifest: str,
    reserving_class_total: int,
) -> Path:
    normalized = validate_project_duplication_request(request)
    path = _recovery_journal_path(server_root, normalized["RequestId"])
    payload = _build_recovery_journal(
        normalized,
        verified_manifest,
        reserving_class_total,
    )
    return write_json_atomic(path, payload)


def _load_recovery_journal(
    server_root: Path,
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    normalized = validate_project_duplication_request(request)
    path = _recovery_journal_path(server_root, normalized["RequestId"])
    try:
        payload = _read_json_object(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, ProjectDuplicationError) as exc:
        raise ProjectDuplicationRecoveryRequired(
            "Project-duplication recovery journal could not be verified."
        ) from exc
    return _validate_recovery_journal(payload, normalized)


def _is_scratch_name(name: str) -> bool:
    """Lock and temporary files come and go mid-copy and are never copied."""

    folded = name.casefold()
    return folded.endswith((".lock", ".tmp")) or folded.startswith(".tmp")


def _ignore_scratch_names(_directory: str, names: list[str]) -> list[str]:
    return [name for name in names if _is_scratch_name(name)]


def _is_uncompared(relative: Path, name: str, is_dir: bool) -> bool:
    folded = name.casefold()
    parts = relative.parts
    if not parts:
        if is_dir:
            return folded in _UNCOMPARED_PROJECT_DIR_NAMES
        return folded in _UNCOMPARED_PROJECT_FILE_NAMES
    if len(parts) == 2 and parts[0].casefold() == "data" and not is_dir:
        return folded in _UNCOMPARED_CLASS_FILE_NAMES
    return False


def _source_manifest(
    project_dir: Path,
    *,
    include_transient: bool = False,
) -> str:
    """Hash relative names and metadata without reading project file contents.

    Without ``include_transient`` this is the "did the source change?"
    comparison: lock and temporary files are left out, and the entries the app
    rewrites while a project is merely open are inspected for links but not
    hashed.
    """

    if _path_is_link_or_reparse(project_dir):
        raise ProjectDuplicationError(
            "The inspected project root is an unsupported symbolic link or reparse point."
        )
    digest = hashlib.sha256()
    transient = {name.casefold() for name in PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES}

    def walk(folder: Path, relative: Path, compared: bool = True) -> None:
        try:
            with os.scandir(folder) as scan:
                entries = sorted(scan, key=lambda entry: (entry.name.casefold(), entry.name))
        except FileNotFoundError:
            if not compared:
                return
            raise ProjectDuplicationError(
                "The source project changed or became unavailable while it was being inspected."
            )
        except OSError as exc:
            raise ProjectDuplicationError(
                "The source project changed or became unavailable while it was being inspected."
            ) from exc

        for entry in entries:
            child_relative = relative / entry.name
            if (
                not include_transient
                and relative.as_posix().casefold() == "data"
                and entry.name.casefold() in transient
                and entry.is_dir(follow_symlinks=False)
            ):
                continue
            if not include_transient and _is_scratch_name(entry.name):
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                if not compared:
                    continue
                raise ProjectDuplicationError(
                    "The source project changed or became unavailable while it "
                    "was being inspected."
                )
            except OSError as exc:
                raise ProjectDuplicationError(
                    "The source project changed or became unavailable while it "
                    "was being inspected."
                ) from exc
            if entry.is_symlink() or _stat_is_reparse_point(entry_stat):
                raise ProjectDuplicationError(
                    "The source project contains an unsupported symbolic link or "
                    f"reparse point: {child_relative.as_posix()}"
                )

            if entry.is_dir(follow_symlinks=False):
                kind = "directory"
                size = 0
                mtime_ns = 0
            elif entry.is_file(follow_symlinks=False):
                kind = "file"
                size = int(entry_stat.st_size)
                mtime_ns = int(entry_stat.st_mtime_ns)
            else:
                raise ProjectDuplicationError(
                    "The source project contains an unsupported filesystem entry: "
                    f"{child_relative.as_posix()}"
                )
            child_compared = compared and (
                include_transient
                or not _is_uncompared(relative, entry.name, kind == "directory")
            )
            if child_compared:
                record = (
                    f"{kind}\0{child_relative.as_posix()}\0{size}\0{mtime_ns}\n"
                )
                digest.update(record.encode("utf-8", errors="surrogatepass"))
            if kind == "directory":
                walk(Path(entry.path), child_relative, child_compared)

    walk(project_dir, Path())
    return digest.hexdigest()


def _target_lock_path(server_root: Path, target_segment: str) -> Path:
    lock_dir = _verified_protocol_directory(server_root, "locks")
    digest = hashlib.sha256(target_segment.casefold().encode("utf-8")).hexdigest()
    return _direct_child(lock_dir, f"{digest}{_LOCK_SUFFIX}", "project lock")


def _acquire_target_lock(
    server_root: Path,
    target_segment: str,
    request_id: str,
) -> _TargetLock:
    lock_path = _target_lock_path(server_root, target_segment)
    lease = acquire_engine_job_lease(
        lock_path,
        stale_seconds=PROJECT_DUPLICATION_LOCK_STALE_SECONDS,
        payload_fields={"request_id": request_id},
    )
    if lease is None:
        raise ProjectDuplicationError(
            "Another project duplication is already creating the target project."
        )
    return _TargetLock(lease.path, lease.owner_token)


def _lock_is_owned(lock: _TargetLock) -> bool:
    return engine_job_lease_owner(lock.path) == lock.owner_token


def _refresh_target_lock(lock: _TargetLock | None) -> None:
    if lock is None or not _lock_is_owned(lock):
        return
    try:
        os.utime(lock.path, None)
    except OSError:
        pass


def _release_target_lock(lock: _TargetLock | None) -> None:
    if lock is None or not _lock_is_owned(lock):
        return
    try:
        lock.path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _staging_path(projects_dir: Path, target_segment: str, request_id: str) -> Path:
    identity = hashlib.sha256(
        f"{target_segment.casefold()}\0{request_id}".encode("utf-8")
    ).hexdigest()[:24]
    return _direct_child(
        projects_dir,
        f"{_STAGING_PREFIX}{identity}.staging",
        "project staging folder",
    )


def _data_inventory(data_dir: Path) -> tuple[list[Path], list[Path]]:
    """Return deterministic data-root files and materialized RC directories."""

    if not data_dir.exists():
        return [], []
    if not data_dir.is_dir() or data_dir.is_symlink():
        raise ProjectDuplicationError(
            "The source project's data entry is not a safe directory."
        )

    transient = {name.casefold() for name in PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES}
    files: list[Path] = []
    reserving_classes: list[Path] = []
    with os.scandir(data_dir) as scan:
        entries = sorted(scan, key=lambda entry: (entry.name.casefold(), entry.name))
    for entry in entries:
        path = Path(entry.path)
        if entry.is_symlink():
            raise ProjectDuplicationError(
                f"The project data folder contains an unsupported symbolic link: {entry.name}"
            )
        if entry.is_dir(follow_symlinks=False):
            if entry.name.casefold() not in transient:
                reserving_classes.append(path)
        elif entry.is_file(follow_symlinks=False):
            if not _is_scratch_name(entry.name):
                files.append(path)
        else:
            raise ProjectDuplicationError(
                f"The project data folder contains an unsupported filesystem entry: {entry.name}"
            )
    return files, reserving_classes


def _copy_non_data_project(source: Path, staging: Path) -> None:
    source_identity = os.path.normcase(os.path.normpath(source))

    def ignore_data_at_root(current_dir: str, names: list[str]) -> list[str]:
        ignored = _ignore_scratch_names(current_dir, names)
        if os.path.normcase(os.path.normpath(current_dir)) != source_identity:
            return ignored
        return ignored + [name for name in names if name.casefold() == "data"]

    shutil.copytree(source, staging, ignore=ignore_data_at_root, symlinks=True)


def duplicate_project(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    progress_callback: ProgressCallback,
    commit_callback: CommitCallback | None = None,
    ownership_callback: OwnershipCallback | None = None,
) -> int:
    """Copy one project transactionally and return its materialized RC count."""

    normalized = validate_project_duplication_request(request)
    root = Path(server_root).expanduser().resolve(strict=False)
    projects_dir = _verified_projects_directory_path(
        root,
        normalized["ProjectsDirectory"],
    )
    if not projects_dir.is_dir():
        raise ProjectDuplicationError("The Arco Server projects folder is unavailable.")

    source_segment = encode_project_directory_segment(
        normalized["SourceProjectName"]
    )
    target_segment = encode_project_directory_segment(
        normalized["TargetProjectName"]
    )
    source = _find_child_case_insensitive(projects_dir, source_segment)
    if (
        source is None
        or not source.is_dir()
        or _path_is_link_or_reparse(source)
    ):
        raise ProjectDuplicationError("The source project folder does not exist.")
    if _find_child_case_insensitive(projects_dir, target_segment) is not None:
        raise ProjectDuplicationError("The target project folder already exists.")
    target = _direct_child(projects_dir, target_segment, "target project folder")
    staging = _staging_path(projects_dir, target_segment, normalized["RequestId"])

    lock: _TargetLock | None = None
    staging_created = False
    committed = False
    preserve_staging = False
    try:
        lock = _acquire_target_lock(
            root, target_segment, normalized["RequestId"]
        )

        def ensure_owned() -> None:
            if ownership_callback is not None:
                ownership_callback()

        def report(progress: Progress) -> None:
            ensure_owned()
            # Every report sits between two copy steps, and the last one comes
            # before the staging folder is renamed into place, so this is the
            # one safe place to honour a cancel.
            _raise_if_cancelled(root, normalized["RequestId"])
            _refresh_target_lock(lock)
            progress_callback(progress)

        if _find_child_case_insensitive(projects_dir, target_segment) is not None:
            raise ProjectDuplicationError("The target project folder already exists.")
        if staging.exists() or staging.is_symlink():
            raise ProjectDuplicationError(
                "A staging folder already exists for this project duplication request."
            )

        report(
            _progress("discovering", 0, 0, "Discovering project files")
        )
        before_manifest = _source_manifest(source)
        data_files, reserving_classes = _data_inventory(source / "data")
        total = len(reserving_classes)

        report(
            _progress("project_files", 0, 0, "Copying project files")
        )
        staging_created = True
        request_id = normalized["RequestId"]
        _copy_with_retry(
            root,
            request_id,
            "project files",
            staging,
            lambda: _copy_non_data_project(source, staging),
        )

        source_data = source / "data"
        if source_data.is_dir():
            staging_data = staging / "data"
            staging_data.mkdir()
            report(
                _progress("data_files", 0, 0, "Copying project data files")
            )
            for source_file in data_files:
                staged_file = staging_data / source_file.name
                _copy_with_retry(
                    root,
                    request_id,
                    f"data file {source_file.name}",
                    staged_file,
                    lambda source_file=source_file, staged_file=staged_file: (
                        shutil.copy2(source_file, staged_file)
                    ),
                )

            report(
                _progress(
                    "reserving_classes",
                    0,
                    total,
                    f"Copying reserving classes (0 of {total})",
                )
            )
            for completed, source_rc in enumerate(reserving_classes, start=1):
                staged_rc = staging_data / source_rc.name
                _copy_with_retry(
                    root,
                    request_id,
                    f"reserving class {completed} of {total} ({source_rc.name})",
                    staged_rc,
                    lambda source_rc=source_rc, staged_rc=staged_rc: shutil.copytree(
                        source_rc,
                        staged_rc,
                        symlinks=True,
                        ignore=_ignore_scratch_names,
                    ),
                )
                report(
                    _progress(
                        "reserving_classes",
                        completed,
                        total,
                        f"Copying reserving classes ({completed} of {total})",
                    )
                )
            shutil.copystat(source_data, staging_data, follow_symlinks=False)
        else:
            report(
                _progress(
                    "reserving_classes",
                    0,
                    0,
                    "No reserving classes to copy",
                )
            )

        report(
            _progress("finalizing", 0, 0, "Finalizing duplicated project")
        )
        after_manifest = _source_manifest(source)
        if before_manifest != after_manifest:
            raise ProjectDuplicationError(
                "The source project changed during duplication; the target was not published."
            )
        staged_manifest = _source_manifest(staging)
        if before_manifest != staged_manifest:
            raise ProjectDuplicationError(
                "The staged project does not match the source; the target was not published."
            )
        if _find_child_case_insensitive(projects_dir, target_segment) is not None:
            raise ProjectDuplicationError("The target project folder already exists.")
        rollback_manifest = _source_manifest(staging, include_transient=True)
        ensure_owned()
        _write_recovery_journal(
            root,
            normalized,
            rollback_manifest,
            total,
        )
        ensure_owned()

        # ArcRho Server runs on Windows, where rename refuses an existing
        # directory.  The target lock and immediate existence check guard the
        # publication race for cooperating engine workers.
        os.rename(staging, target)
        try:
            ensure_owned()
            if commit_callback is not None:
                commit_callback(total)
        except Exception as status_exc:
            if isinstance(status_exc, ProjectDuplicationLeaseLost):
                raise
            # A visible target without a terminal success status cannot be
            # finalized safely by the frontend. First atomically quarantine
            # the target back under the private staging name, then verify it.
            # This avoids deleting a change made between verification and the
            # rename. If quarantine or verification is uncertain, preserve
            # the visible target (or the quarantined staging folder) for
            # operator recovery.
            try:
                os.rename(target, staging)
            except OSError as rollback_exc:
                raise ProjectDuplicationRecoveryRequired(
                    "Project duplication completed, but its success status could not "
                    "be published and the target could not be quarantined for rollback."
                ) from rollback_exc

            try:
                rollback_is_safe = (
                    _source_manifest(staging, include_transient=True)
                    == rollback_manifest
                )
            except Exception as verification_exc:
                try:
                    os.rename(staging, target)
                except OSError as restore_exc:
                    preserve_staging = True
                    raise ProjectDuplicationRecoveryRequired(
                        "Project duplication completed, but its success status could "
                        "not be published and the quarantined target could not be "
                        "verified or restored."
                    ) from restore_exc
                raise ProjectDuplicationRecoveryRequired(
                    "Project duplication completed, but its success status could not "
                    "be published; rollback could not be verified, so the target was "
                    "preserved."
                ) from verification_exc

            if not rollback_is_safe:
                try:
                    os.rename(staging, target)
                except OSError as restore_exc:
                    preserve_staging = True
                    raise ProjectDuplicationRecoveryRequired(
                        "Project duplication completed, but its success status could "
                        "not be published and the changed target could not be restored."
                    ) from restore_exc
                raise ProjectDuplicationRecoveryRequired(
                    "Project duplication completed, but its success status could not "
                    "be published and the target changed before rollback."
                ) from status_exc
            raise
        committed = True
        return total
    finally:
        if staging_created and not committed and not preserve_staging:
            try:
                shutil.rmtree(staging)
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(
                    "(project duplication cleanup error: "
                    f"{_redact_machine_paths(exc)})"
                )
        _release_target_lock(lock)


def execute_project_duplication(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    ownership_callback: OwnershipCallback | None = None,
) -> bool:
    """Execute a claimed request and publish every engine-owned status."""

    try:
        normalized = validate_project_duplication_request(request)
    except Exception as exc:
        message = _safe_status_error(exc)
        raw_request_id = request.get("RequestId") if isinstance(request, Mapping) else None
        log_duplication_event(
            server_root,
            f"request={raw_request_id!r} rejected: {message}",
            exc=exc,
        )
        try:
            if ownership_callback is not None:
                ownership_callback()
            request_id = validate_request_id(raw_request_id)
            write_project_duplication_status_for_request_id(
                server_root,
                request_id,
                "error",
                progress=_progress(
                    "rejected",
                    0,
                    0,
                    "Project duplication request rejected",
                ),
                message=message,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish rejected project duplication status: "
                f"{_redact_machine_paths(status_exc)})"
            )
        print(f"(project duplication request error: {message})")
        return False

    current_progress = _progress(
        "discovering", 0, 0, "Discovering project files"
    )

    def publish(progress: Progress) -> None:
        nonlocal current_progress
        if ownership_callback is not None:
            ownership_callback()
        current_progress = progress
        write_project_duplication_status(
            server_root,
            normalized,
            "processing",
            progress=progress,
        )

    def publish_success(total: int) -> None:
        nonlocal current_progress
        if ownership_callback is not None:
            ownership_callback()
        terminal_progress = _progress(
            "complete", total, total, "Project duplication complete"
        )
        write_project_duplication_status(
            server_root,
            normalized,
            "success",
            progress=terminal_progress,
        )
        current_progress = terminal_progress

    try:
        publish(current_progress)
        duplicate_project(
            server_root,
            normalized,
            progress_callback=publish,
            commit_callback=publish_success,
            ownership_callback=ownership_callback,
        )
        if current_progress["stage"] != "complete":
            raise ProjectDuplicationError(
                "Project duplication did not publish its terminal status."
            )
        return True
    except Exception as exc:
        if isinstance(exc, ProjectDuplicationLeaseLost):
            print("(project duplication request ownership was lost)")
            return False
        if isinstance(exc, ProjectDuplicationCancelled):
            log_duplication_event(
                server_root,
                f"request={normalized['RequestId']} cancelled at stage "
                f"{current_progress['stage']} "
                f"({current_progress['completed']}/{current_progress['total']})",
            )
            try:
                if ownership_callback is not None:
                    ownership_callback()
                write_project_duplication_status(
                    server_root,
                    normalized,
                    "cancelled",
                    progress=_progress(
                        "cancelled",
                        current_progress["completed"],
                        current_progress["total"],
                        "Project duplication cancelled",
                    ),
                    message=_safe_status_error(exc),
                )
            except Exception as status_exc:
                print(
                    "(error: could not publish project duplication cancelled status: "
                    f"{_redact_machine_paths(status_exc)})"
                )
            return False
        message = _safe_status_error(exc)
        # The shared status is redacted by contract; this is the only record of
        # which path and which errno actually failed.
        log_duplication_event(
            server_root,
            f"request={normalized['RequestId']} failed at stage "
            f"{current_progress['stage']} "
            f"({current_progress['completed']}/{current_progress['total']}): {message}",
            exc=exc,
        )
        if isinstance(exc, ProjectDuplicationRecoveryRequired):
            current_progress = _progress(
                "recovery_required",
                0,
                0,
                "Project duplication requires manual recovery",
            )
        try:
            if ownership_callback is not None:
                ownership_callback()
            write_project_duplication_status(
                server_root,
                normalized,
                "error",
                progress=current_progress,
                message=message,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish project duplication failure status: "
                f"{_redact_machine_paths(status_exc)})"
            )
        print(f"(project duplication error: {message})")
        return False


def _durable_job_paths(
    server_root: Path,
    request: Mapping[str, Any],
) -> tuple[Path, Path, Path, str]:
    normalized = validate_project_duplication_request(request)
    try:
        projects_dir = _verified_projects_directory_path(
            server_root,
            normalized["ProjectsDirectory"],
        )
    except ProjectDuplicationError as exc:
        raise ProjectDuplicationRecoveryRequired(
            "The Arco Server projects folder cannot be verified for recovery."
        ) from exc
    if not projects_dir.is_dir():
        raise ProjectDuplicationRetryableRecovery(
            "The Arco Server projects folder is temporarily unavailable."
        )
    target_segment = encode_project_directory_segment(
        normalized["TargetProjectName"]
    )
    target = _direct_child(projects_dir, target_segment, "target project folder")
    existing_target = _find_child_case_insensitive(projects_dir, target_segment)
    if existing_target is not None:
        target = existing_target
    staging = _staging_path(
        projects_dir,
        target_segment,
        normalized["RequestId"],
    )
    return projects_dir, target, staging, target_segment


def _validated_terminal_status(
    server_root: Path,
    request_id: str,
) -> dict[str, Any] | None:
    path = project_duplication_status_path(server_root, request_id)
    try:
        payload = _read_json_object(path)
        status = validate_project_duplication_status(
            payload,
            expected_request_id=request_id,
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, ProjectDuplicationError) as exc:
        raise ProjectDuplicationRetryableRecovery(
            "Existing project-duplication status could not be validated."
        ) from exc
    return (
        status
        if status["status"] in PROJECT_DUPLICATION_TERMINAL_STATUS_VALUES
        else None
    )


def _remove_recovery_journal(server_root: Path, request_id: str) -> bool:
    path = _recovery_journal_path(server_root, request_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _cleanup_durable_terminal(
    server_root: Path,
    request_path: Path,
    request_id: str,
    lease: _RequestLease | None = None,
) -> bool:
    """Remove durable metadata only after a validated terminal status exists."""

    terminal = _validated_terminal_status(server_root, request_id)
    if terminal is None:
        return False
    if lease is not None:
        _require_request_lease(lease)
    try:
        request_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    # The marker has done its work once a terminal status exists; a stale one
    # must not linger to stop an unrelated future job that reuses the ID.
    clear_project_duplication_cancel_request(server_root, request_id)
    if (
        terminal["status"] == "error"
        and terminal["progress"]["stage"] == "recovery_required"
    ):
        return True
    return _remove_recovery_journal(server_root, request_id)


def _remove_partial_staging(staging: Path) -> None:
    if staging.is_symlink():
        raise ProjectDuplicationRecoveryRequired(
            "The interrupted project staging folder cannot be verified."
        )
    try:
        shutil.rmtree(staging)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProjectDuplicationRetryableRecovery(
            "The interrupted project staging folder could not be cleaned."
        ) from exc


def _discard_same_request_target_lock(
    server_root: Path,
    target_segment: str,
    request_id: str,
) -> None:
    """Discard a prior worker's target lock after its request lease was taken."""

    lock_path = _target_lock_path(server_root, target_segment)
    try:
        payload = _read_json_object(lock_path)
    except FileNotFoundError:
        return
    except (OSError, ValueError, TypeError, ProjectDuplicationError):
        return
    if payload.get("request_id") != request_id:
        return
    stale_path = lock_path.with_name(
        f".{lock_path.name}.{uuid.uuid4().hex}.recovered"
    )
    try:
        os.rename(lock_path, stale_path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ProjectDuplicationRetryableRecovery(
            "The interrupted target lock could not be recovered."
        ) from exc
    try:
        stale_path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ProjectDuplicationRetryableRecovery(
            "The interrupted target lock could not be cleaned."
        ) from exc


def _publish_recovered_success(
    server_root: Path,
    request: Mapping[str, Any],
    total: int,
    lease: _RequestLease,
) -> None:
    _require_request_lease(lease)
    write_project_duplication_status(
        server_root,
        request,
        "success",
        progress=_progress(
            "complete",
            total,
            total,
            "Project duplication complete",
        ),
    )


def _publish_recovery_required(
    server_root: Path,
    request: Mapping[str, Any],
    lease: _RequestLease,
    message: str,
) -> None:
    _require_request_lease(lease)
    write_project_duplication_status(
        server_root,
        request,
        "error",
        progress=_progress(
            "recovery_required",
            0,
            0,
            "Project duplication requires manual recovery",
        ),
        message=message,
    )


def _recover_verified_staging(
    server_root: Path,
    request: Mapping[str, Any],
    journal: Mapping[str, Any],
    target: Path,
    staging: Path,
    target_segment: str,
    lease: _RequestLease,
) -> None:
    normalized = validate_project_duplication_request(request)
    request_id = normalized["RequestId"]
    _discard_same_request_target_lock(server_root, target_segment, request_id)
    target_lock = _acquire_target_lock(server_root, target_segment, request_id)
    try:
        _require_request_lease(lease)
        existing_target = _find_child_case_insensitive(target.parent, target_segment)
        if existing_target is not None:
            if staging.exists() or staging.is_symlink():
                raise ProjectDuplicationRecoveryRequired(
                    "Both the published target and private staging folder exist; "
                    "automatic recovery cannot choose between them."
                )
            try:
                manifest = _source_manifest(
                    existing_target,
                    include_transient=True,
                )
            except Exception as exc:
                raise ProjectDuplicationRecoveryRequired(
                    "The published target could not be verified during recovery."
                ) from exc
            if manifest != journal["verified_manifest"]:
                raise ProjectDuplicationRecoveryRequired(
                    "The published target changed before recovery completed."
                )
            _publish_recovered_success(
                server_root,
                normalized,
                journal["reserving_class_total"],
                lease,
            )
            return

        os.rename(staging, target)
        try:
            _publish_recovered_success(
                server_root,
                normalized,
                journal["reserving_class_total"],
                lease,
            )
        except ProjectDuplicationLeaseLost:
            raise
        except Exception as exc:
            raise ProjectDuplicationRetryableRecovery(
                "Completion status was unavailable during project recovery."
            ) from exc
    finally:
        _release_target_lock(target_lock)


def _recover_interrupted_job(
    server_root: Path,
    request: Mapping[str, Any],
    lease: _RequestLease,
) -> bool | None:
    """Return True after recovered success, or None to restart a clean copy."""

    normalized = validate_project_duplication_request(request)
    request_id = normalized["RequestId"]
    _projects, target, staging, target_segment = _durable_job_paths(
        server_root,
        normalized,
    )
    _discard_same_request_target_lock(server_root, target_segment, request_id)
    journal = _load_recovery_journal(server_root, normalized)
    if journal is None:
        if staging.exists() or staging.is_symlink():
            _remove_partial_staging(staging)
        return None

    target_exists = target.exists() or target.is_symlink()
    staging_exists = staging.exists() or staging.is_symlink()
    if target_exists and staging_exists:
        raise ProjectDuplicationRecoveryRequired(
            "Both the published target and private staging folder exist; "
            "automatic recovery cannot choose between them."
        )

    if target_exists:
        if target.is_symlink():
            raise ProjectDuplicationRecoveryRequired(
                "The published target cannot be verified during recovery."
            )
        try:
            target_manifest = _source_manifest(target, include_transient=True)
        except Exception as exc:
            raise ProjectDuplicationRecoveryRequired(
                "The published target could not be verified during recovery."
            ) from exc
        if target_manifest != journal["verified_manifest"]:
            raise ProjectDuplicationRecoveryRequired(
                "The published target changed before recovery completed."
            )
        try:
            _publish_recovered_success(
                server_root,
                normalized,
                journal["reserving_class_total"],
                lease,
            )
        except ProjectDuplicationLeaseLost:
            raise
        except Exception as exc:
            raise ProjectDuplicationRetryableRecovery(
                "Completion status was unavailable during project recovery."
            ) from exc
        return True

    if staging_exists:
        if staging.is_symlink():
            raise ProjectDuplicationRecoveryRequired(
                "The verified staging folder cannot be trusted during recovery."
            )
        try:
            staging_manifest = _source_manifest(staging, include_transient=True)
        except Exception as exc:
            raise ProjectDuplicationRecoveryRequired(
                "The verified staging folder could not be verified during recovery."
            ) from exc
        if staging_manifest != journal["verified_manifest"]:
            raise ProjectDuplicationRecoveryRequired(
                "The verified staging folder changed before recovery completed."
            )
        _recover_verified_staging(
            server_root,
            normalized,
            journal,
            target,
            staging,
            target_segment,
            lease,
        )
        return True

    raise ProjectDuplicationRecoveryRequired(
        "The verified project copy is missing during recovery."
    )


def process_durable_project_duplication_request(
    server_root: str | os.PathLike[str],
    request_file: str | os.PathLike[str],
    request: Mapping[str, Any],
) -> bool:
    """Process one retained queue file under an exclusive renewable lease."""

    root = Path(server_root).expanduser().resolve(strict=False)
    raw_request_id = request.get("RequestId") if isinstance(request, Mapping) else None
    try:
        request_id = validate_request_id(raw_request_id)
    except ProjectDuplicationContractError as exc:
        print(f"(project duplication request error: {_safe_status_error(exc)})")
        return False

    request_path = Path(request_file)
    expected_path = project_duplication_request_path(root, request_id)
    try:
        if request_path.resolve(strict=False) != expected_path.resolve(strict=False):
            print("(project duplication request filename does not match RequestId)")
            return False
    except OSError:
        return False
    try:
        request_is_link = _path_is_link_or_reparse(request_path)
    except ProjectDuplicationError as exc:
        print(f"(project duplication request path rejected: {_safe_status_error(exc)})")
        return False
    if request_is_link:
        print(
            "(project duplication request file must not be a symbolic link or "
            "reparse point)"
        )
        return False

    try:
        lease = _acquire_request_lease(root, request_id)
    except ProjectDuplicationError as exc:
        print(f"(project duplication protocol path rejected: {_safe_status_error(exc)})")
        return False
    if lease is None:
        return False
    heartbeat_stop, heartbeat_thread = _start_request_lease_heartbeat(lease)
    try:
        try:
            terminal = _validated_terminal_status(root, request_id)
        except ProjectDuplicationRetryableRecovery as exc:
            print(f"(project duplication status validation will retry: {exc})")
            return False
        if terminal is not None:
            try:
                normalized_terminal_request = validate_project_duplication_request(
                    request
                )
                _projects, _target, _staging, terminal_target_segment = (
                    _durable_job_paths(root, normalized_terminal_request)
                )
                _discard_same_request_target_lock(
                    root,
                    terminal_target_segment,
                    request_id,
                )
            except Exception:
                pass
            _cleanup_durable_terminal(root, request_path, request_id, lease)
            return terminal["status"] == "success"

        try:
            normalized = validate_project_duplication_request(request)
        except ProjectDuplicationContractError:
            execute_project_duplication(
                root,
                request,
                ownership_callback=lambda: _require_request_lease(lease),
            )
        else:
            try:
                recovered = _recover_interrupted_job(root, normalized, lease)
                if recovered is None:
                    execute_project_duplication(
                        root,
                        normalized,
                        ownership_callback=lambda: _require_request_lease(lease),
                    )
            except ProjectDuplicationLeaseLost:
                return False
            except ProjectDuplicationRetryableRecovery as exc:
                print(f"(project duplication recovery will retry: {exc})")
                return False
            except ProjectDuplicationRecoveryRequired as exc:
                try:
                    _publish_recovery_required(
                        root,
                        normalized,
                        lease,
                        _safe_status_error(exc),
                    )
                except Exception as status_exc:
                    print(
                        "(error: could not publish project recovery status: "
                        f"{_redact_machine_paths(status_exc)})"
                    )
                    return False

        try:
            terminal = _validated_terminal_status(root, request_id)
        except ProjectDuplicationRetryableRecovery as exc:
            print(f"(project duplication status validation will retry: {exc})")
            return False
        if terminal is None:
            return False
        _cleanup_durable_terminal(root, request_path, request_id, lease)
        return terminal["status"] == "success"
    finally:
        _stop_request_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        _release_request_lease(lease)
