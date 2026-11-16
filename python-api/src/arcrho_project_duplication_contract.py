"""Canonical request and status contract for Arco project duplication.

Project duplication is executed by Arco Engine on the machine hosting the
Arco Server workspace. Callers identify projects by logical name plus a
normalized, server-root-relative project-store directory; the engine derives
every absolute filesystem path from its own configured server root.

This module intentionally uses only the Python standard library so the
frontend app server and the frozen data engine can load the same source file.
It owns the request shape, project-folder encoding, status shape, path layout,
and atomic JSON publication rules for this workflow.
"""

from __future__ import annotations

import json
import os
import re
import stat as stat_module
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_DUPLICATION_FUNCTION = "ArcRhoDuplicateProject"
PROJECT_DUPLICATION_CONTRACT_VERSION = 1
PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION = 1
PROJECT_DUPLICATION_REQUIRED_FIELDS = (
    "Function",
    "ContractVersion",
    "RequestId",
    "SourceProjectName",
    "TargetProjectName",
    "ProjectsDirectory",
    "UserName",
)
PROJECT_DUPLICATION_STATUS_VALUES = (
    "queued",
    "processing",
    "success",
    "error",
    "cancelled",
)
PROJECT_DUPLICATION_TERMINAL_STATUS_VALUES = frozenset(
    {"success", "error", "cancelled"}
)
PROJECT_DUPLICATION_CANCEL_VERSION = 1
PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES = frozenset(
    {".arcrho-resq-import-staging", "tmp"}
)

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
_PROGRESS_FIELDS = frozenset({"stage", "completed", "total", "label"})
_ATOMIC_REPLACE_ATTEMPTS = 8
_ATOMIC_REPLACE_DELAY_SECONDS = 0.04


class ProjectDuplicationContractError(ValueError):
    """Raised when a project-duplication payload violates the contract."""


def stat_is_reparse_point(metadata: Any) -> bool:
    """Return whether Windows metadata identifies a filesystem reparse point."""

    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(reparse_flag and attributes & reparse_flag)


def path_is_link_or_reparse(path: str | os.PathLike[str]) -> bool:
    """Inspect a path itself without following symlinks or Windows junctions."""

    candidate = Path(path)
    try:
        if candidate.is_symlink():
            return True
        metadata = candidate.stat(follow_symlinks=False)
    except FileNotFoundError:
        return False
    return stat_is_reparse_point(metadata)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectDuplicationContractError(f"{field_name} is required.")
    return value.strip()


def encode_filename_segment(value: Any) -> str:
    """Encode one logical name exactly as the frontend path configuration does."""

    replacements = {
        "\\": "_%5C_",
        "/": "_%2F_",
        ":": "_%3A_",
        "*": "_%2A_",
        "?": "_%3F_",
        '"': "_%22_",
        "<": "_%3C_",
        ">": "_%3E_",
        "|": "_%7C_",
    }
    encoded: list[str] = []
    for character in str(value if value is not None else ""):
        if character in replacements:
            encoded.append(replacements[character])
        elif ord(character) < 32:
            encoded.append(f"_%{ord(character):02X}_")
        else:
            encoded.append(character)
    return "".join(encoded)


def encode_project_directory_segment(value: Any) -> str:
    """Return the one direct-child folder segment for a logical project name."""

    return encode_filename_segment(str(value if value is not None else "").strip())


def validate_request_id(value: Any) -> str:
    request_id = _required_text(value, "RequestId")
    if not _REQUEST_ID_RE.fullmatch(request_id):
        raise ProjectDuplicationContractError(
            "RequestId must be a safe token containing only letters, numbers, "
            "underscores, and hyphens (maximum 128 characters)."
        )
    return request_id


def _validate_source_key(value: Any) -> str:
    source_key = _required_text(value, "source_key")
    if not _REQUEST_ID_RE.fullmatch(source_key):
        raise ProjectDuplicationContractError(
            "source_key must be a safe token containing only letters, numbers, "
            "underscores, and hyphens (maximum 128 characters)."
        )
    return source_key


def validate_project_name(value: Any, field_name: str = "ProjectName") -> str:
    """Validate a logical project name and return its trimmed representation."""

    logical_name = _required_text(value, field_name)
    segment = encode_project_directory_segment(logical_name)
    if not segment or segment in {".", ".."} or segment.endswith((".", " ")):
        raise ProjectDuplicationContractError(
            f"{field_name} does not produce a safe project folder name."
        )
    device_stem = segment.split(".", 1)[0].upper()
    if device_stem in _WINDOWS_DEVICE_NAMES:
        raise ProjectDuplicationContractError(
            f"{field_name} uses a reserved Windows folder name."
        )
    return logical_name


def validate_projects_directory(value: Any) -> str:
    """Return one location-independent project-store path below the server root."""

    raw = _required_text(value, "ProjectsDirectory").replace("\\", "/")
    if raw.startswith("/") or re.match(r"(?i)^[a-z]:", raw):
        raise ProjectDuplicationContractError(
            "ProjectsDirectory must be relative to the Arco Server root."
        )
    parts = [part for part in raw.split("/") if part]
    if not parts:
        raise ProjectDuplicationContractError("ProjectsDirectory is required.")
    for part in parts:
        if part in {".", ".."} or part.endswith((".", " ")):
            raise ProjectDuplicationContractError(
                "ProjectsDirectory contains an unsafe folder segment."
            )
        if any(ord(character) < 32 or character in ':*?"<>|' for character in part):
            raise ProjectDuplicationContractError(
                "ProjectsDirectory contains an unsafe folder segment."
            )
        if part.split(".", 1)[0].upper() in _WINDOWS_DEVICE_NAMES:
            raise ProjectDuplicationContractError(
                "ProjectsDirectory contains a reserved Windows folder name."
            )
    return "/".join(parts)


def project_duplication_projects_directory_identity(value: Any) -> str:
    """Return the Windows path identity used for idempotent layout matching."""

    return validate_projects_directory(value).casefold()


def build_project_duplication_request(
    *,
    request_id: Any,
    source_project_name: Any,
    target_project_name: Any,
    projects_directory: Any = "projects",
    user_name: Any,
) -> dict[str, Any]:
    """Build the complete canonical request payload."""

    return validate_project_duplication_request(
        {
            "Function": PROJECT_DUPLICATION_FUNCTION,
            "ContractVersion": PROJECT_DUPLICATION_CONTRACT_VERSION,
            "RequestId": request_id,
            "SourceProjectName": source_project_name,
            "TargetProjectName": target_project_name,
            "ProjectsDirectory": projects_directory,
            "UserName": user_name,
        }
    )


def validate_project_duplication_request(payload: Any) -> dict[str, Any]:
    """Return the normalized exact request, rejecting paths and extensions.

    The required fields are also the complete allow-list. Machine-local paths
    are impossible: ``ProjectsDirectory`` is a normalized relative workspace
    layout value, and every consumer derives absolute paths from its local
    Arco Server root.
    """

    if not isinstance(payload, Mapping):
        raise ProjectDuplicationContractError(
            "Project duplication request must be a JSON object."
        )

    supplied = set(payload)
    allowed = set(PROJECT_DUPLICATION_REQUIRED_FIELDS)
    missing = [
        field for field in PROJECT_DUPLICATION_REQUIRED_FIELDS if field not in supplied
    ]
    if missing:
        raise ProjectDuplicationContractError(
            "Missing request field(s): " + ", ".join(missing) + "."
        )
    extra = sorted((str(field) for field in supplied - allowed), key=str.casefold)
    if extra:
        raise ProjectDuplicationContractError(
            "Unexpected request field(s): " + ", ".join(extra) + ". "
            "Filesystem paths must not be supplied by request producers; only "
            "canonical relative workspace layout fields are allowed."
        )

    function = _required_text(payload.get("Function"), "Function")
    if function != PROJECT_DUPLICATION_FUNCTION:
        raise ProjectDuplicationContractError(
            f"Function must be {PROJECT_DUPLICATION_FUNCTION}."
        )

    version = payload.get("ContractVersion")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectDuplicationContractError(
            "ContractVersion must be the integer "
            f"{PROJECT_DUPLICATION_CONTRACT_VERSION}."
        )
    if version != PROJECT_DUPLICATION_CONTRACT_VERSION:
        raise ProjectDuplicationContractError(
            f"Unsupported ContractVersion {version!r}; expected "
            f"{PROJECT_DUPLICATION_CONTRACT_VERSION}."
        )

    request_id = validate_request_id(payload.get("RequestId"))
    source_name = validate_project_name(
        payload.get("SourceProjectName"), "SourceProjectName"
    )
    target_name = validate_project_name(
        payload.get("TargetProjectName"), "TargetProjectName"
    )
    if (
        encode_project_directory_segment(source_name).casefold()
        == encode_project_directory_segment(target_name).casefold()
    ):
        raise ProjectDuplicationContractError(
            "SourceProjectName and TargetProjectName must be different."
        )

    return {
        "Function": PROJECT_DUPLICATION_FUNCTION,
        "ContractVersion": PROJECT_DUPLICATION_CONTRACT_VERSION,
        "RequestId": request_id,
        "SourceProjectName": source_name,
        "TargetProjectName": target_name,
        "ProjectsDirectory": validate_projects_directory(
            payload.get("ProjectsDirectory")
        ),
        "UserName": _required_text(payload.get("UserName"), "UserName"),
    }


def build_project_duplication_submission_receipt(
    *,
    source_key: Any,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical path-free app-server submission receipt."""

    return validate_project_duplication_submission_receipt(
        {
            "receipt_version": PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION,
            "source_key": source_key,
            "request": request,
        }
    )


def validate_project_duplication_submission_receipt(
    payload: Any,
    *,
    expected_request_id: Any = None,
) -> dict[str, Any]:
    """Validate the exact durable receipt used to make POST retries idempotent."""

    if not isinstance(payload, Mapping):
        raise ProjectDuplicationContractError(
            "Project duplication submission receipt must be a JSON object."
        )
    required = {"receipt_version", "source_key", "request"}
    supplied = set(payload)
    missing = sorted(required - supplied)
    extra = sorted((str(field) for field in supplied - required), key=str.casefold)
    if missing:
        raise ProjectDuplicationContractError(
            "Missing submission receipt field(s): " + ", ".join(missing) + "."
        )
    if extra:
        raise ProjectDuplicationContractError(
            "Unexpected submission receipt field(s): " + ", ".join(extra) + "."
        )

    version = payload.get("receipt_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectDuplicationContractError(
            "receipt_version must be the integer "
            f"{PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION}."
        )
    if version != PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION:
        raise ProjectDuplicationContractError(
            f"Unsupported receipt_version {version!r}; expected "
            f"{PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION}."
        )

    request = validate_project_duplication_request(payload.get("request"))
    if expected_request_id is not None:
        expected = validate_request_id(expected_request_id)
        if request["RequestId"] != expected:
            raise ProjectDuplicationContractError(
                "Submission receipt RequestId does not match the requested job."
            )
    return {
        "receipt_version": PROJECT_DUPLICATION_SUBMISSION_RECEIPT_VERSION,
        "source_key": _validate_source_key(payload.get("source_key")),
        "request": request,
    }


def _root_path(server_root: str | os.PathLike[str]) -> Path:
    raw = os.fspath(server_root)
    if not str(raw).strip():
        raise ProjectDuplicationContractError("Arco Server root is required.")
    return Path(raw).expanduser()


def project_duplication_request_path(
    server_root: str | os.PathLike[str], request_id: Any
) -> Path:
    """Return the top-level engine request path for a duplication job."""

    return _root_path(server_root) / "requests" / f"{validate_request_id(request_id)}.json"


def project_duplication_projects_path(
    server_root: str | os.PathLike[str],
    projects_directory: Any = "projects",
) -> Path:
    """Return the canonical project-folder parent for duplication jobs."""

    path = _root_path(server_root)
    for part in validate_projects_directory(projects_directory).split("/"):
        path /= part
    return path


def project_duplication_lock_directory(
    server_root: str | os.PathLike[str],
) -> Path:
    """Return the canonical cross-worker target-lock directory."""

    return _root_path(server_root) / "requests" / "project_duplication" / "locks"


def project_duplication_status_directory(
    server_root: str | os.PathLike[str],
) -> Path:
    """Return the folder holding one status file per duplication job."""

    return _root_path(server_root) / "requests" / "project_duplication" / "status"


def project_duplication_status_path(
    server_root: str | os.PathLike[str], request_id: Any
) -> Path:
    """Return the server-root-relative status path for a duplication job."""

    return (
        project_duplication_status_directory(server_root)
        / f"{validate_request_id(request_id)}.json"
    )


def project_duplication_submission_receipt_path(
    server_root: str | os.PathLike[str], request_id: Any
) -> Path:
    """Return the durable app-server receipt path for an idempotency key."""

    return (
        _root_path(server_root)
        / "requests"
        / "project_duplication"
        / "submissions"
        / f"{validate_request_id(request_id)}.json"
    )


def project_duplication_cancel_path(
    server_root: str | os.PathLike[str], request_id: Any
) -> Path:
    """Return the cancel-marker path a user writes to stop a running job.

    The marker lives beside the other protocol folders, never inside the
    top-level ``requests`` queue the Engine scans, so it can never be mistaken
    for a request of its own.
    """

    return (
        _root_path(server_root)
        / "requests"
        / "project_duplication"
        / "cancel"
        / f"{validate_request_id(request_id)}.json"
    )


def build_project_duplication_cancel_request(
    request_id: Any,
    *,
    user_name: Any = "",
    requested_at: Any = None,
) -> dict[str, Any]:
    """Build the location-independent cancel marker for one job."""

    if requested_at is None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        timestamp = _required_text(requested_at, "requested_at")
    return {
        "contract_version": PROJECT_DUPLICATION_CANCEL_VERSION,
        "request_id": validate_request_id(request_id),
        "requested_at": timestamp,
        "user_name": str(user_name if user_name is not None else "").strip(),
    }


def write_project_duplication_cancel_request(
    server_root: str | os.PathLike[str],
    request_id: Any,
    *,
    user_name: Any = "",
) -> Path:
    """Atomically publish the cancel marker for one job."""

    payload = build_project_duplication_cancel_request(request_id, user_name=user_name)
    return write_json_atomic(
        project_duplication_cancel_path(server_root, payload["request_id"]),
        payload,
    )


def project_duplication_cancel_requested(
    server_root: str | os.PathLike[str], request_id: Any
) -> bool:
    """Return True when a cancel marker exists for the job.

    The Engine calls this between copy steps, so an unreadable marker counts
    as no request: a transient share error must never stop a copy on its own.
    """

    try:
        return project_duplication_cancel_path(server_root, request_id).is_file()
    except OSError:
        return False


def clear_project_duplication_cancel_request(
    server_root: str | os.PathLike[str], request_id: Any
) -> bool:
    """Remove a job's cancel marker; True when none remains."""

    try:
        project_duplication_cancel_path(server_root, request_id).unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _normalize_progress(progress: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(progress, Mapping):
        raise ProjectDuplicationContractError("progress must be a JSON object.")
    supplied = set(progress)
    missing = sorted(_PROGRESS_FIELDS - supplied)
    extra = sorted(
        (str(field) for field in supplied - _PROGRESS_FIELDS), key=str.casefold
    )
    if missing:
        raise ProjectDuplicationContractError(
            "Missing progress field(s): " + ", ".join(missing) + "."
        )
    if extra:
        raise ProjectDuplicationContractError(
            "Unexpected progress field(s): " + ", ".join(extra) + "."
        )

    completed = progress.get("completed")
    total = progress.get("total")
    for field_name, value in (("completed", completed), ("total", total)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProjectDuplicationContractError(
                f"progress.{field_name} must be a non-negative integer."
            )
    if completed > total:
        raise ProjectDuplicationContractError(
            "progress.completed must not be greater than progress.total."
        )

    return {
        "stage": _required_text(progress.get("stage"), "progress.stage"),
        "completed": completed,
        "total": total,
        "label": _required_text(progress.get("label"), "progress.label"),
    }


def build_project_duplication_status(
    request: Mapping[str, Any],
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    updated_at: Any = None,
) -> dict[str, Any]:
    """Build one complete location-independent job status payload."""

    normalized_request = validate_project_duplication_request(request)
    return build_project_duplication_status_for_request_id(
        normalized_request["RequestId"],
        status,
        progress=progress,
        message=message,
        updated_at=updated_at,
    )


def build_project_duplication_status_for_request_id(
    request_id: Any,
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    updated_at: Any = None,
) -> dict[str, Any]:
    """Build canonical status when only a safe request ID is recoverable."""

    normalized_request_id = validate_request_id(request_id)
    normalized_status = str(status if status is not None else "").strip()
    if normalized_status not in PROJECT_DUPLICATION_STATUS_VALUES:
        raise ProjectDuplicationContractError(
            f"Invalid project duplication status: {status!r}."
        )
    if updated_at is None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        timestamp = _required_text(updated_at, "updated_at")

    payload: dict[str, Any] = {
        "contract_version": PROJECT_DUPLICATION_CONTRACT_VERSION,
        "status": normalized_status,
        "updated_at": timestamp,
        "request_id": normalized_request_id,
        "progress": _normalize_progress(progress),
    }
    normalized_message = str(message if message is not None else "").strip()
    if normalized_message:
        payload["message"] = normalized_message
    return payload


def validate_project_duplication_status(
    payload: Any,
    *,
    expected_request_id: Any = None,
) -> dict[str, Any]:
    """Validate a persisted status and return only its canonical fields."""

    if not isinstance(payload, Mapping):
        raise ProjectDuplicationContractError(
            "Project duplication status must be a JSON object."
        )
    required = {
        "contract_version",
        "status",
        "updated_at",
        "request_id",
        "progress",
    }
    allowed = required | {"message"}
    supplied = set(payload)
    missing = sorted(required - supplied)
    extra = sorted((str(field) for field in supplied - allowed), key=str.casefold)
    if missing:
        raise ProjectDuplicationContractError(
            "Missing status field(s): " + ", ".join(missing) + "."
        )
    if extra:
        raise ProjectDuplicationContractError(
            "Unexpected status field(s): " + ", ".join(extra) + "."
        )

    version = payload.get("contract_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectDuplicationContractError(
            "contract_version must be the integer "
            f"{PROJECT_DUPLICATION_CONTRACT_VERSION}."
        )
    if version != PROJECT_DUPLICATION_CONTRACT_VERSION:
        raise ProjectDuplicationContractError(
            f"Unsupported contract_version {version!r}; expected "
            f"{PROJECT_DUPLICATION_CONTRACT_VERSION}."
        )

    status = _required_text(payload.get("status"), "status")
    if status not in PROJECT_DUPLICATION_STATUS_VALUES:
        raise ProjectDuplicationContractError(
            f"Invalid project duplication status: {payload.get('status')!r}."
        )
    request_id = validate_request_id(payload.get("request_id"))
    if expected_request_id is not None:
        expected = validate_request_id(expected_request_id)
        if request_id != expected:
            raise ProjectDuplicationContractError(
                "Project duplication status RequestId does not match the requested job."
            )

    normalized: dict[str, Any] = {
        "contract_version": PROJECT_DUPLICATION_CONTRACT_VERSION,
        "status": status,
        "updated_at": _required_text(payload.get("updated_at"), "updated_at"),
        "request_id": request_id,
        "progress": _normalize_progress(payload.get("progress")),
    }
    if "message" in payload:
        normalized["message"] = _required_text(payload.get("message"), "message")
    return normalized


def write_json_atomic(path: str | os.PathLike[str], payload: Any) -> Path:
    """Write JSON through a unique sibling and atomically replace ``path``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_ATOMIC_REPLACE_ATTEMPTS):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt + 1 >= _ATOMIC_REPLACE_ATTEMPTS:
                    raise
                time.sleep(_ATOMIC_REPLACE_DELAY_SECONDS * (attempt + 1))
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return target


def write_project_duplication_status(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    updated_at: Any = None,
) -> Path:
    """Build and atomically publish one project-duplication status."""

    normalized_request = validate_project_duplication_request(request)
    return write_project_duplication_status_for_request_id(
        server_root,
        normalized_request["RequestId"],
        status,
        progress=progress,
        message=message,
        updated_at=updated_at,
    )


def write_project_duplication_status_for_request_id(
    server_root: str | os.PathLike[str],
    request_id: Any,
    status: str,
    *,
    progress: Mapping[str, Any],
    message: Any = "",
    updated_at: Any = None,
) -> Path:
    """Atomically publish status for a rejected but identifiable request."""

    normalized_request_id = validate_request_id(request_id)
    payload = build_project_duplication_status_for_request_id(
        normalized_request_id,
        status,
        progress=progress,
        message=message,
        updated_at=updated_at,
    )
    path = project_duplication_status_path(server_root, normalized_request_id)
    return write_json_atomic(path, payload)
