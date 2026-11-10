"""Server-worker bridge from the ResQ migration to the ArcRho data-engine.

Generated datasets use the same file request contract as the Excel add-in:
the migration atomically publishes JSON under ``<server_root>/requests`` and an
Arco Engine worker writes the requested CSV.  Each request writes to a unique
staging path first.  The migration moves a completed staging CSV into its
canonical cache path, so a failed or timed-out request cannot damage an existing
cache.  Status-aware workers also publish an atomic processing/success/error JSON
beside the staging output; workers already running on the legacy CSV-only
contract remain compatible.

The migration remains responsible for the canonical sidecar.  Its processing
provenance comes from the authoritative ``app_server`` helper so the
``config_hash`` matches the app's cache-freshness calculation.
"""
from __future__ import annotations

import csv
import getpass
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# .../python-api/migration/resq_migration/engine.py -> ArcRho repo root
_MIGRATION_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MIGRATION_PKG_DIR.parents[2]
_FRONTEND_ROOT = Path(
    os.environ.get("ARCRHO_FRONTEND_ROOT") or (_REPO_ROOT / "frontend")
).expanduser()
_CANONICAL_SRC_ROOT = _REPO_ROOT / "python-api" / "src"
if _CANONICAL_SRC_ROOT.is_dir() and str(_CANONICAL_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_CANONICAL_SRC_ROOT))

from arcrho_dependent_propagation_contract import (  # noqa: E402
    ENGINE_HEARTBEAT_MAX_AGE_SECONDS as _CANONICAL_HEARTBEAT_MAX_AGE_SEC,
    discover_fresh_engine_heartbeats as _canonical_discover_fresh_engine_heartbeats,
    engine_instances_directory as _canonical_engine_instances_directory,
)

_DEFAULT_SERVER_ROOT = r"E:\Arco Server"
ENGINE_HEARTBEAT_MAX_AGE_SEC = _CANONICAL_HEARTBEAT_MAX_AGE_SEC
ENGINE_REQUEST_TIMEOUT_SEC = 60.0
ENGINE_REQUEST_POLL_INTERVAL_SEC = 0.05
_ENGINE_JOB_DIR_NAME = ".arcrho-engine-jobs"


class EngineGenerationError(RuntimeError):
    """Raised when the data-engine cannot generate a requested dataset."""


class EngineUnavailableError(EngineGenerationError):
    """Raised when no recently active Arco Engine worker is available."""


@dataclass(frozen=True)
class EngineRequestJob:
    """One published-or-pending data-engine request.

    ``output_path`` is unique to the job.  Workers never write directly to
    ``target_path``; :func:`finalize_engine_request` performs that replacement
    only after the staged output is complete.
    """

    request_id: str
    server_root: Path
    target_path: Path
    output_path: Path
    status_path: Path
    request_path: Path
    request_temp_path: Path
    payload: dict[str, Any]


def _prepend_sys_path(path: Path) -> None:
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _ensure_provenance_importable() -> None:
    _prepend_sys_path(_FRONTEND_ROOT)


def import_user_identity_service():
    """The app-server identity resolver, so a migrated sidecar names the user the app would."""

    _ensure_provenance_importable()
    from app_server.services import user_identity_service

    return user_identity_service


def _resolve_server_root(server_root: object = None) -> Path:
    root = str(server_root).strip() if server_root else ""
    if not root:
        root = os.environ.get("ARCRHO_ROOT", _DEFAULT_SERVER_ROOT)
    return Path(root).expanduser().resolve()


def discover_fresh_engine_heartbeats(
    server_root: object = None,
    *,
    max_age_sec: float = ENGINE_HEARTBEAT_MAX_AGE_SEC,
    now: float | None = None,
) -> tuple[Path, ...]:
    """Return engine heartbeat files modified within ``max_age_sec``.

    The discovery rule is owned by ``arcrho_dependent_propagation_contract``;
    this wrapper only adds the migration's server-root resolution.
    """

    return _canonical_discover_fresh_engine_heartbeats(
        _resolve_server_root(server_root),
        max_age_sec=max_age_sec,
        now=now,
    )


def require_engine_workers(
    server_root: object = None,
    *,
    max_age_sec: float = ENGINE_HEARTBEAT_MAX_AGE_SEC,
) -> tuple[Path, ...]:
    """Return fresh worker heartbeats or raise :class:`EngineUnavailableError`."""

    root = _resolve_server_root(server_root)
    heartbeats = discover_fresh_engine_heartbeats(root, max_age_sec=max_age_sec)
    if heartbeats:
        return heartbeats
    instance_dir = _canonical_engine_instances_directory(root)
    raise EngineUnavailableError(
        "No active Arco Engine worker was found. "
        f"Expected a heartbeat newer than {max_age_sec:g} seconds under [{instance_dir}]."
    )


def create_engine_request_job(
    *,
    project_name: str,
    rc_path: str,
    dataset_type: str,
    data_path: str | os.PathLike,
    origin_length: int,
    development_length: int,
    is_vector: bool,
    server_root: object = None,
    cumulative: bool = True,
    calendar: bool = False,
    user_name: str | None = None,
) -> EngineRequestJob:
    """Build a request job without publishing it."""

    root = _resolve_server_root(server_root)
    target = Path(data_path).expanduser().resolve()
    request_id = uuid.uuid4().hex
    request_dir = root / "requests"
    request_path = request_dir / f"request-migration-{request_id}.json"
    request_temp_path = request_dir / f".request-migration-{request_id}.tmp"
    output_path = (
        target.parent
        / _ENGINE_JOB_DIR_NAME
        / request_id
        / target.name
    )
    status_path = output_path.parent / "status.json"
    payload: dict[str, Any] = {
        "Function": "ArcRhoVec" if is_vector else "ArcRhoTri",
        "RequestId": request_id,
        "ProjectName": str(project_name),
        "Path": str(rc_path),
        "DatasetName": str(dataset_type),
        "OriginLength": int(origin_length),
        "DevelopmentLength": int(development_length),
        "Cumulative": bool(cumulative),
        "Transposed": False,
        "Calendar": bool(calendar),
        "DataPath": str(output_path),
        "StatusPath": str(status_path),
        "UserName": str(user_name or getpass.getuser()),
    }
    return EngineRequestJob(
        request_id=request_id,
        server_root=root,
        target_path=target,
        output_path=output_path,
        status_path=status_path,
        request_path=request_path,
        request_temp_path=request_temp_path,
        payload=payload,
    )


def publish_engine_request(
    job: EngineRequestJob,
    *,
    heartbeat_max_age_sec: float = ENGINE_HEARTBEAT_MAX_AGE_SEC,
    check_workers: bool = True,
) -> Path:
    """Atomically publish ``job`` so filesystem-watching workers can claim it."""

    if check_workers:
        require_engine_workers(job.server_root, max_age_sec=heartbeat_max_age_sec)
    if job.output_path.exists():
        raise EngineGenerationError(
            f"Engine request staging output already exists: [{job.output_path}]."
        )

    try:
        job.request_path.parent.mkdir(parents=True, exist_ok=True)
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        with job.request_temp_path.open("x", encoding="utf-8") as stream:
            json.dump(job.payload, stream, indent=2)
            stream.write("\n")
        os.replace(job.request_temp_path, job.request_path)
    except Exception as exc:
        _safe_unlink(job.request_temp_path)
        raise EngineGenerationError(
            f"Could not publish data-engine request [{job.request_id}]: {exc}"
        ) from exc
    return job.request_path


def wait_for_engine_request(
    job: EngineRequestJob,
    *,
    timeout_sec: float = ENGINE_REQUEST_TIMEOUT_SEC,
    poll_interval_sec: float = ENGINE_REQUEST_POLL_INTERVAL_SEC,
    on_poll: Callable[[], None] | None = None,
) -> Path:
    """Wait until the worker atomically publishes this job's staged CSV."""

    if timeout_sec <= 0:
        raise ValueError("timeout_sec must be positive.")
    if poll_interval_sec <= 0:
        raise ValueError("poll_interval_sec must be positive.")

    deadline = time.monotonic() + float(timeout_sec)
    while True:
        if on_poll is not None:
            on_poll()
        status = _read_request_status(job)
        if status is not None:
            state = str(status.get("status") or "").strip().lower()
            if state == "error":
                detail = str(status.get("message") or "unknown data-engine error").strip()
                raise EngineGenerationError(
                    f"Data-engine request [{job.request_id}] failed while generating "
                    f"[{job.payload['DatasetName']}] for [{job.payload['Path']}]: {detail}"
                )
            if state == "success" and job.output_path.is_file():
                return job.output_path
            # A status-aware worker writes "processing" before it starts. Once
            # observed, do not mistake its error/output CSV for legacy success.
        elif job.output_path.is_file():
            # Backward compatibility for already-running workers that predate
            # RequestId/StatusPath. Reject their recognizable error rows before
            # accepting the original atomic CSV completion contract.
            legacy_error = _legacy_engine_error_message(job.output_path)
            if legacy_error:
                raise EngineGenerationError(
                    f"Data-engine request [{job.request_id}] failed while generating "
                    f"[{job.payload['DatasetName']}] for [{job.payload['Path']}]: "
                    f"{legacy_error}"
                )
            return job.output_path
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(float(poll_interval_sec), remaining))

    raise EngineGenerationError(
        f"Data-engine request [{job.request_id}] timed out after {timeout_sec:g} seconds "
        f"while generating [{job.payload['DatasetName']}] for [{job.payload['Path']}]."
    )


def _read_request_status(job: EngineRequestJob) -> dict[str, Any] | None:
    try:
        with job.status_path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    request_id = str(payload.get("request_id") or payload.get("RequestId") or "").strip()
    if request_id and request_id != job.request_id:
        return None
    return payload


def _legacy_engine_error_message(output_path: Path) -> str:
    """Return a recognizable legacy worker error row, if present."""

    try:
        with output_path.open("r", encoding="utf-8-sig", newline="") as stream:
            row = next(csv.reader(stream), [])
    except (OSError, UnicodeError, csv.Error):
        return ""
    if len(row) != 1:
        return ""
    value = str(row[0] or "").strip()
    normalized = value.casefold()
    if normalized == "project settings not defined":
        return value
    prefixes = (
        "(project not found:",
        "(invalid function name",
        "(data processing rules error:",
        "(data processing configuration error:",
        "(error:",
    )
    return value if normalized.startswith(prefixes) else ""


def finalize_engine_request(job: EngineRequestJob) -> Path:
    """Atomically replace the canonical cache with a completed job output."""

    if not job.output_path.is_file():
        raise EngineGenerationError(
            f"Data-engine request [{job.request_id}] produced no staged CSV at "
            f"[{job.output_path}]."
        )
    try:
        job.target_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(job.output_path, job.target_path)
    except Exception as exc:
        raise EngineGenerationError(
            f"Could not finalize data-engine request [{job.request_id}] at "
            f"[{job.target_path}]: {exc}"
        ) from exc
    _remove_empty_job_directories(job)
    return job.target_path


def cleanup_engine_request_job(job: EngineRequestJob) -> None:
    """Remove only this job's unclaimed request and staged output artifacts."""

    _safe_unlink(job.request_temp_path)
    _safe_unlink(job.request_path)
    _safe_unlink(job.output_path)
    _safe_unlink(job.status_path)
    _remove_empty_job_directories(job)


def _safe_unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _remove_empty_job_directories(job: EngineRequestJob) -> None:
    # The worker uses an output-local ``tmp`` directory and atomically moves the
    # completed CSV out of it.  rmdir is deliberately non-recursive so concurrent
    # or late worker output can never be deleted.
    candidates = (
        job.output_path.parent / "tmp",
        job.output_path.parent,
        job.output_path.parent.parent,
    )
    for path in candidates:
        try:
            path.rmdir()
        except OSError:
            pass


def generate_engine_csv(
    *,
    project_name: str,
    rc_path: str,
    dataset_type: str,
    data_path: str | os.PathLike,
    origin_length: int,
    development_length: int,
    is_vector: bool,
    server_root: object = None,
    cumulative: bool = True,
    calendar: bool = False,
    timeout_sec: float = ENGINE_REQUEST_TIMEOUT_SEC,
    poll_interval_sec: float = ENGINE_REQUEST_POLL_INTERVAL_SEC,
    on_poll: Callable[[], None] | None = None,
) -> None:
    """Generate one dataset CSV through an external Arco Engine worker."""

    job = create_engine_request_job(
        project_name=project_name,
        rc_path=rc_path,
        dataset_type=dataset_type,
        data_path=data_path,
        origin_length=origin_length,
        development_length=development_length,
        is_vector=is_vector,
        server_root=server_root,
        cumulative=cumulative,
        calendar=calendar,
    )
    try:
        publish_engine_request(job)
        wait_for_engine_request(
            job,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            on_poll=on_poll,
        )
        finalize_engine_request(job)
    except EngineGenerationError:
        cleanup_engine_request_job(job)
        raise
    except Exception as exc:
        cleanup_engine_request_job(job)
        raise EngineGenerationError(
            f"Data-engine failed to generate [{dataset_type}] for [{rc_path}]: {exc}"
        ) from exc
    finally:
        _safe_unlink(job.request_temp_path)
        _safe_unlink(job.request_path)


def get_engine_processing_provenance(project_name: str) -> dict:
    """Return the authoritative processing provenance dict for ``project_name``.

    The returned dict (``config_hash``/``algorithm_version``/``rules_format``/
    ``rules_revision``) is recorded in the engine-generated sidecar so the app
    treats the migrated cache as fresh.
    """

    _ensure_provenance_importable()
    try:
        from app_server.services.data_processing_rules_service import (
            get_processing_provenance,
        )
    except Exception as exc:  # pragma: no cover - import/environment failure
        raise EngineGenerationError(
            f"Could not import the processing-provenance helper from app_server "
            f"(checked {_FRONTEND_ROOT}): {exc}"
        ) from exc

    try:
        provenance = get_processing_provenance(project_name)
    except Exception as exc:
        raise EngineGenerationError(
            f"Failed to compute processing provenance for [{project_name}]: {exc}"
        ) from exc

    if not isinstance(provenance, dict) or not str(provenance.get("config_hash") or "").strip():
        raise EngineGenerationError(
            f"Processing provenance for [{project_name}] is missing a config hash."
        )
    return provenance
