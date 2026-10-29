"""Canonical Arco reserving-class dataset index contract.

This module is deliberately standard-library-only so the frontend app server and
the ResQ migration can use the same scanner, row projection, signature, and JSON
serialization without maintaining parallel implementations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat as stat_module
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .bootstrap_contract import BST_JSON_FORMAT
from .bornhuetter_ferguson_contract import BF_JSON_FORMAT
from .cape_cod_contract import CC_JSON_FORMAT
from .io import persisted_json_text
from .sidecar_audit_contract import latest_audit_entry
from .stochastic_consolidation_contract import SCON_JSON_FORMAT, SCON_METHOD_TYPE


DATASET_INDEX_VERSION = 24
INDEX_FILE_NAME = "index.json"
DATASET_DIR_NAME = "datasets"
METHOD_DIR_NAME = "methods"
SIDECAR_DIR_NAME = "sidecars"
LEGACY_NOTES_FILE_PREFIX = "ArcRhoTriNotes@"

INDEX_ROW_FIELDS = (
    "name",
    "dataset_type",
    "dataset_category",
    "source_kind",
    "data_format",
    "origin_length",
    "development_length",
    "stored_origin_length",
    "stored_development_length",
    "method_type",
    "method_name",
    "status",
    "formula",
    "last_modified",
    "last_modified_timestamp",
    "created",
    "created_timestamp",
    "user",
)
FORBIDDEN_INDEX_ROW_FIELDS = frozenset(
    {
        "origin_labels",
        "calculated",
        "precedents",
        "dependents",
        "audit_log",
        "external_links",
        "internal_links",
        "formula_links",
        "show_subtotal",
        "values",
        "mask",
        "masks",
        "details_tab",
        "method_tab",
        "data_tab",
    }
)
INDEX_TOP_LEVEL_FIELDS = (
    "ok",
    "version",
    "exists",
    "project_name",
    "reserving_class",
    "folder_signature",
    "files",
)
FOLDER_PATH_FIELDS = ("data", DATASET_DIR_NAME, METHOD_DIR_NAME, SIDECAR_DIR_NAME)

METHOD_TYPE_NONE = "None"
METHOD_TYPE_DFM = "DFM"
METHOD_TYPE_RESULT_SELECTION = "Result Selection"
METHOD_TYPE_BF = "Bornhuetter Ferguson"
METHOD_TYPE_CAPE_COD = "Cape Cod"
METHOD_TYPE_BOOTSTRAP = "Bootstrap"
METHOD_TYPE_STOCHASTIC_CONSOLIDATION = SCON_METHOD_TYPE
METHOD_TYPE_BS_SR = "B&S Settlement Rate Adjustment"
METHOD_TYPE_BS_CRA = "B&S Case Reserve Adequacy Adjustment"
STATUS_CURRENT = 0
STATUS_REVIEW_NEEDED = 2

RS_JSON_FORMAT = "arcrho-result-selection-v4"
BS_SR_JSON_FORMAT = "arcrho-berquist-sherman-sr-v4"
BS_CRA_JSON_FORMAT = "arcrho-berquist-sherman-cra-v4"

_METHOD_CONTRACTS = {
    RS_JSON_FORMAT: (METHOD_TYPE_RESULT_SELECTION, "result_selection", "Vector"),
    BF_JSON_FORMAT: (METHOD_TYPE_BF, "bornhuetter_ferguson", "Vector"),
    CC_JSON_FORMAT: (METHOD_TYPE_CAPE_COD, "cape_cod", "Vector"),
    BST_JSON_FORMAT: (METHOD_TYPE_BOOTSTRAP, "bootstrap", "Vector"),
    SCON_JSON_FORMAT: (METHOD_TYPE_STOCHASTIC_CONSOLIDATION, "stochastic_consolidation", "Vector"),
    BS_SR_JSON_FORMAT: (METHOD_TYPE_BS_SR, "berquist_sherman_sr", "Triangle"),
    BS_CRA_JSON_FORMAT: (METHOD_TYPE_BS_CRA, "berquist_sherman_cra", "Triangle"),
}
_METHOD_PREFIX_CONTRACTS = {
    "DFM@": (METHOD_TYPE_DFM, "dfm", "Vector"),
    "RS@": _METHOD_CONTRACTS[RS_JSON_FORMAT],
    "BF@": _METHOD_CONTRACTS[BF_JSON_FORMAT],
    "CC@": _METHOD_CONTRACTS[CC_JSON_FORMAT],
    "BST@": _METHOD_CONTRACTS[BST_JSON_FORMAT],
    "SCON@": _METHOD_CONTRACTS[SCON_JSON_FORMAT],
    "BSSR@": _METHOD_CONTRACTS[BS_SR_JSON_FORMAT],
    "BSCRA@": _METHOD_CONTRACTS[BS_CRA_JSON_FORMAT],
}
_CACHED_JSON_PREFIXES = _METHOD_PREFIX_CONTRACTS
_METHOD_TYPE_BY_SOURCE_KIND = {
    "dfm": METHOD_TYPE_DFM,
    "result_selection": METHOD_TYPE_RESULT_SELECTION,
    "bornhuetter_ferguson": METHOD_TYPE_BF,
    "cape_cod": METHOD_TYPE_CAPE_COD,
    "bootstrap": METHOD_TYPE_BOOTSTRAP,
    "stochastic_consolidation": METHOD_TYPE_STOCHASTIC_CONSOLIDATION,
    "berquist_sherman_sr": METHOD_TYPE_BS_SR,
    "berquist_sherman_cra": METHOD_TYPE_BS_CRA,
}
_CANONICAL_METHOD_TYPES = {
    value.casefold(): value
    for value in (
        METHOD_TYPE_DFM,
        METHOD_TYPE_RESULT_SELECTION,
        METHOD_TYPE_BF,
        METHOD_TYPE_CAPE_COD,
        METHOD_TYPE_BOOTSTRAP,
        METHOD_TYPE_STOCHASTIC_CONSOLIDATION,
        METHOD_TYPE_BS_SR,
        METHOD_TYPE_BS_CRA,
    )
}
_MODIFIED_KEYS = (
    "last_modified",
    "updated_at",
    "updated",
    "modified_at",
    "modified",
)
_CREATED_KEYS = ("created_at", "created", "creation_time")
_USER_KEYS = (
    "user",
    "user_name",
    "username",
    "UserName",
    "created_by",
    "modified_by",
    "updated_by",
    "owner",
    "author",
)
_REQUIRED_ROW_FIELDS = frozenset(
    {
        "name",
        "dataset_type",
        "method_type",
        "status",
        "last_modified",
        "last_modified_timestamp",
        "created",
        "created_timestamp",
        "user",
    }
)
_SIGNATURE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DECODED_FILENAME_SEGMENT_RE = re.compile(r"_%([0-9A-Fa-f]{2})_")
_INDEX_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.35, 0.5)
_WINDOWS_LOCK_ERRORS = {32, 33}
_INDEX_UPDATE_LOCK_TIMEOUT_SECONDS = 30.0
_PROCESS_INDEX_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_INDEX_LOCKS_GUARD = threading.Lock()


def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_text(value))


def _json_tab(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def decode_filename_segment(value: Any) -> str:
    """Decode ArcRho's reversible ``_%XX_`` filename encoding."""

    def replace(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except (TypeError, ValueError):
            return match.group(0)

    return _DECODED_FILENAME_SEGMENT_RE.sub(replace, str(value or ""))


def canonical_existing_directory(
    path: str | os.PathLike[str],
) -> Path | None:
    """Return an existing directory with its filesystem-preserved casing."""

    candidate = Path(path)
    if not candidate.is_dir():
        return None
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_long_path_name = kernel32.GetLongPathNameW
        get_long_path_name.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
        )
        get_long_path_name.restype = ctypes.c_uint32
        buffer_size = 32768
        buffer = ctypes.create_unicode_buffer(buffer_size)
        result = get_long_path_name(str(candidate), buffer, buffer_size)
        if 0 < result < buffer_size:
            candidate = Path(buffer.value)
    try:
        wanted = candidate.name.casefold()
        with os.scandir(candidate.parent) as entries:
            for entry in entries:
                if entry.is_dir() and entry.name.casefold() == wanted:
                    return Path(entry.path)
    except OSError:
        pass
    return candidate


def resolve_canonical_index_identity(
    project_name: Any,
    reserving_class: Any,
    rc_dir: str | os.PathLike[str],
) -> tuple[str, str]:
    """Resolve persisted identity from filesystem-preserved project/RC names."""

    root = Path(rc_dir)
    canonical_root = canonical_existing_directory(root)
    canonical_project_dir = canonical_existing_directory(
        (canonical_root or root).parent.parent
    )
    project = _clean_text(project_name)
    if canonical_project_dir is not None and canonical_project_dir.name:
        project = canonical_project_dir.name
    rc = _clean_text(reserving_class)
    if canonical_root is not None:
        decoded = _clean_text(decode_filename_segment(canonical_root.name))
        if decoded:
            rc = decoded
    return project, rc


def _split_cache_variant_stem(stem: str) -> tuple[str, bool]:
    parts = str(stem or "").split("@")
    if (
        len(parts) >= 5
        and parts[-4].strip().isdigit()
        and parts[-3].strip().isdigit()
        and parts[-2].strip().casefold()
        in {"cum", "inc", "cumulative", "incremental"}
        and parts[-1].strip().casefold() in {"dev", "cal", "calendar"}
    ):
        return "@".join(parts[:-4]), True
    if (
        len(parts) >= 3
        and parts[-2].strip().isdigit()
        and parts[-1].strip().isdigit()
    ):
        return str(stem or ""), False
    if len(parts) >= 2 and parts[-1].strip().isdigit():
        return "@".join(parts[:-1]), True
    return str(stem or ""), False


def normalize_cached_dataset_name(value: Any) -> str:
    stem, _is_variant = _split_cache_variant_stem(_clean_text(value))
    return _clean_name(decode_filename_segment(stem))


def cached_dataset_name_from_filename(filename: Any) -> str:
    path = Path(_clean_text(filename))
    stem = path.stem
    if path.suffix.casefold() == ".json":
        stem_folded = stem.casefold()
        for prefix in _CACHED_JSON_PREFIXES:
            if stem_folded.startswith(prefix.casefold()):
                stem = stem[len(prefix) :]
                break
    return normalize_cached_dataset_name(stem)


def dataset_sidecar_path_for_cached_csv(csv_path: str | os.PathLike[str]) -> Path:
    path = Path(csv_path)
    dataset_stem, is_variant = _split_cache_variant_stem(path.stem)
    if path.parent.name.casefold() == DATASET_DIR_NAME:
        sidecar_dir = path.parent.parent / SIDECAR_DIR_NAME
    else:
        sidecar_dir = path.parent / SIDECAR_DIR_NAME
    return sidecar_dir / f"{dataset_stem if is_variant else path.stem}.json"


def _numeric_timestamp(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _canonical_datetime(value: Any) -> tuple[str, float]:
    text = _clean_text(value)
    if not text:
        return "", 0.0
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return text, 0.0
    if parsed.tzinfo is None:
        utc_value = parsed.replace(tzinfo=timezone.utc)
    else:
        utc_value = parsed.astimezone(timezone.utc)
    return (
        utc_value.isoformat(timespec="seconds").replace("+00:00", "Z"),
        utc_value.timestamp(),
    )


def _file_datetime(timestamp: float) -> str:
    try:
        value = datetime.fromtimestamp(float(timestamp), timezone.utc)
    except (OSError, TypeError, ValueError):
        return ""
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _first_text(metadata: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        text = _clean_text(metadata.get(key))
        if text:
            return text
    return ""


def _normalize_method_type(value: Any, source_kind: Any = "") -> str:
    text = _clean_text(value)
    if text and text.casefold() not in {"none", "null"}:
        key = text.casefold().replace("_", " ")
        return _CANONICAL_METHOD_TYPES.get(key, text)
    return _METHOD_TYPE_BY_SOURCE_KIND.get(
        _clean_text(source_kind).casefold(),
        METHOD_TYPE_NONE,
    )


def _normalize_status(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return STATUS_CURRENT
    return STATUS_REVIEW_NEEDED if parsed == STATUS_REVIEW_NEEDED else STATUS_CURRENT


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _nonempty_scalar(value: Any) -> bool:
    return _scalar(value) and value not in (None, "")


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _safe_read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return {}
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, (dict, list)) else {}


@dataclass(frozen=True)
class _FileStat:
    folder: str
    name: str
    path: Path
    size: int
    mtime: float
    mtime_ns: int


@dataclass(frozen=True)
class FolderScan:
    """One enumeration of a reserving-class folder and the signature it hashes to.

    Enumerating costs one directory listing per folder; reading the sidecar and
    method payloads costs one open/read/close per file. Callers that only need
    to know whether the folder changed take the first cost and skip the second.
    """

    files: tuple[_FileStat, ...]
    folder_exists: Mapping[str, bool]
    signature: str
    has_legacy_notes: bool


def _enumerate_folder(
    rc_dir: Path,
    folder_name: str,
) -> tuple[bool, list[_FileStat], bool]:
    """List one folder, keeping the stat data the directory listing already returned.

    ``DirEntry.stat()`` needs no extra system call on Windows, so re-statting the
    path would add one network round trip per file for data already in hand.
    """

    directory = rc_dir / folder_name
    files: list[_FileStat] = []
    has_legacy_notes = False
    try:
        with os.scandir(directory) as iterator:
            for item in iterator:
                suffix = Path(item.name).suffix.casefold()
                if suffix not in {".csv", ".json"}:
                    continue
                if item.name.casefold() == INDEX_FILE_NAME:
                    continue
                if folder_name == SIDECAR_DIR_NAME and item.name.casefold().startswith(LEGACY_NOTES_FILE_PREFIX.casefold()):
                    has_legacy_notes = True
                    continue
                try:
                    info = item.stat()
                except FileNotFoundError:
                    continue
                if not stat_module.S_ISREG(info.st_mode):
                    continue
                files.append(
                    _FileStat(
                        folder=folder_name,
                        name=item.name,
                        path=Path(item.path),
                        size=int(info.st_size),
                        mtime=float(info.st_mtime),
                        mtime_ns=int(info.st_mtime_ns),
                    )
                )
    except (FileNotFoundError, NotADirectoryError):
        return False, [], False
    return True, files, has_legacy_notes


def _enumerate_entries(
    rc_dir: Path,
    executor: ThreadPoolExecutor,
) -> tuple[list[_FileStat], dict[str, bool], bool]:
    root_future = executor.submit(rc_dir.is_dir)
    folder_futures = {
        folder_name: executor.submit(_enumerate_folder, rc_dir, folder_name)
        for folder_name in (DATASET_DIR_NAME, METHOD_DIR_NAME, SIDECAR_DIR_NAME)
    }
    exists = {"data": root_future.result()}
    files: list[_FileStat] = []
    has_legacy_notes = False
    for folder_name, future in folder_futures.items():
        folder_exists, folder_files, folder_has_legacy_notes = future.result()
        exists[folder_name] = folder_exists
        has_legacy_notes = has_legacy_notes or folder_has_legacy_notes
        files.extend(folder_files)
    files.sort(key=lambda item: (item.folder.casefold(), item.name.casefold(), item.name))
    return files, exists, has_legacy_notes


def scan_folder_signature(
    rc_dir: str | os.PathLike[str],
    *,
    max_workers: int = 12,
) -> FolderScan:
    """Enumerate the reserving-class folders and hash them without reading payloads."""

    worker_count = max(1, min(int(max_workers or 1), 32))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="arcrho-index-signature",
    ) as executor:
        files, folder_exists, has_legacy_notes = _enumerate_entries(Path(rc_dir), executor)
    return FolderScan(
        files=tuple(files),
        folder_exists=folder_exists,
        signature=make_folder_signature(files, folder_exists),
        has_legacy_notes=has_legacy_notes,
    )


def _read_payloads(
    files: Sequence[_FileStat],
    executor: ThreadPoolExecutor,
) -> dict[str, Any]:
    """Read every enumerated JSON file once, keyed by canonical path.

    Cached CSVs resolve to a sidecar that lives in ``sidecars`` and is therefore
    already part of this enumeration, so no CSV needs its own lookup pass.
    """

    payload_futures: dict[str, Future[Any]] = {
        _path_key(item.path): executor.submit(_safe_read_json, item.path)
        for item in files
        if item.path.suffix.casefold() == ".json"
    }
    return {key: future.result() for key, future in payload_futures.items()}


def _method_contract(
    payload: Mapping[str, Any],
    filename: str,
) -> tuple[str, str, str] | None:
    json_format = _clean_text(payload.get("json_format")).casefold()
    contract = _METHOD_CONTRACTS.get(json_format)
    if contract:
        return contract
    folded_name = filename.casefold()
    for prefix, prefix_contract in _METHOD_PREFIX_CONTRACTS.items():
        if folded_name.startswith(prefix.casefold()):
            return prefix_contract
    return None


def _method_entry_from_payload(
    payload: Mapping[str, Any],
    filename: str,
) -> dict[str, Any] | None:
    contract = _method_contract(payload, filename)
    if contract is None:
        return None
    method_type, source_kind, data_format = contract
    if method_type == METHOD_TYPE_DFM:
        details = _json_tab(payload, "details_tab")
        dataset_name = normalize_cached_dataset_name(
            details.get("output_dataset")
            or details.get("name")
            or details.get("output_type")
        )
        dataset_type = normalize_cached_dataset_name(details.get("output_type"))
        method_name = normalize_cached_dataset_name(
            details.get("name")
        ) or cached_dataset_name_from_filename(filename)
        category = _clean_text(details.get("output_category"))
    else:
        details = _json_tab(payload, "details_tab")
        dataset_name = normalize_cached_dataset_name(details.get("name"))
        dataset_type = normalize_cached_dataset_name(details.get("output_type"))
        method_name = dataset_name
        category = _clean_text(
            details.get("dataset_category") or details.get("output_category")
        )
    if not dataset_name:
        return None
    entry: dict[str, Any] = {
        "dataset_name": dataset_name,
        "dataset_type": dataset_type or dataset_name,
        "method_type": method_type,
        "source_kind": source_kind,
        "data_format": data_format,
    }
    if method_name and method_name.casefold() != dataset_name.casefold():
        entry["method_name"] = method_name
    if category:
        entry["dataset_category"] = category
    # A method computes its output at its own period, so what it publishes is
    # stored at the shape it is displayed at.
    if data_format == "Triangle":
        for key, stored_key in (
            ("origin_length", "stored_origin_length"),
            ("development_length", "stored_development_length"),
        ):
            if _nonempty_scalar(details.get(key)):
                entry[key] = details[key]
                entry[stored_key] = details[key]
    elif _nonempty_scalar(details.get("period_length")):
        entry["origin_length"] = details["period_length"]
        entry["stored_origin_length"] = details["period_length"]
    return entry


def _metadata_dataset_type(metadata: Mapping[str, Any]) -> str:
    return normalize_cached_dataset_name(metadata.get("dataset_type"))


def _metadata_row(
    file_stat: _FileStat,
    metadata: Mapping[str, Any],
    *,
    metadata_is_sidecar: bool,
) -> dict[str, Any] | None:
    method_entry = (
        _method_entry_from_payload(metadata, file_stat.name)
        if file_stat.folder == METHOD_DIR_NAME
        else None
    )
    if method_entry:
        dataset_name = _clean_name(method_entry["dataset_name"])
        priority = 40
    else:
        metadata_name = normalize_cached_dataset_name(metadata.get("dataset_name"))
        dataset_name = metadata_name or cached_dataset_name_from_filename(file_stat.name)
        priority = 30 if metadata_name else 10
    if not dataset_name:
        return None

    row: dict[str, Any] = {
        "dataset_name": dataset_name,
        "last_modified": _file_datetime(file_stat.mtime),
        "last_modified_timestamp": file_stat.mtime,
        "_modified_priority": 10,
        "_field_priority": priority,
    }
    if metadata:
        dataset_type = _metadata_dataset_type(metadata)
        category = _clean_text(
            metadata.get("dataset_category") or metadata.get("category")
        )
        source_kind = _clean_text(metadata.get("source_kind"))
        data_format = _clean_text(metadata.get("data_format"))
        formula = _clean_text(metadata.get("formula"))
        user = _first_text(metadata, _USER_KEYS)
        # The table names the last person's write, not a background refresh.
        person_write = latest_audit_entry(metadata, skip_automatic=True)
        user = person_write.get("user") or user
        for key, value in (
            ("dataset_type", dataset_type),
            ("dataset_category", category),
            ("source_kind", source_kind),
            ("data_format", data_format),
            ("formula", formula),
            ("user", user),
        ):
            if value:
                row[key] = value
        # A vector keeps one length under the triangle's origin column, so a
        # row reads the same whichever format it describes. The stored pair
        # beside it is the granularity of the CSV, which a coarser display
        # shape is only a roll-up of.
        if data_format.casefold() == "vector":
            origin_length = metadata.get("period_length")
            if not _nonempty_scalar(origin_length):
                origin_length = metadata.get("origin_length")
            stored_origin_length = metadata.get("stored_period_length")
            stored_development_length = None
        else:
            origin_length = metadata.get("origin_length")
            stored_origin_length = metadata.get("stored_origin_length")
            stored_development_length = metadata.get("stored_development_length")
        for field, value in (
            ("origin_length", origin_length),
            ("development_length", metadata.get("development_length")),
            ("stored_origin_length", stored_origin_length),
            ("stored_development_length", stored_development_length),
        ):
            if _nonempty_scalar(value):
                row[field] = value
        row["method_type"] = _normalize_method_type(
            metadata.get("method_type"),
            source_kind,
        )
        if "status" in metadata:
            row["status"] = _normalize_status(metadata.get("status"))

        modified_text = person_write.get("at") or _first_text(metadata, _MODIFIED_KEYS)
        modified, modified_timestamp = _canonical_datetime(modified_text)
        if modified:
            row["last_modified"] = modified
            if modified_timestamp:
                row["last_modified_timestamp"] = modified_timestamp
            row["_modified_priority"] = 30 if metadata_is_sidecar else 20
        created_text = _first_text(metadata, _CREATED_KEYS)
        created, created_timestamp = _canonical_datetime(created_text)
        if created and metadata_is_sidecar:
            row["created"] = created
            row["created_timestamp"] = created_timestamp
            row["_created_priority"] = 30
    if method_entry:
        row.update(method_entry)
        row["_field_priority"] = 40
    return row


def _set_by_priority(
    state: dict[str, Any],
    priorities: dict[str, int],
    key: str,
    value: Any,
    priority: int,
) -> None:
    if not _nonempty_scalar(value):
        return
    if priority > priorities.get(key, -1):
        state[key] = value
        priorities[key] = priority


def _merge_rows(
    physical_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name: dict[str, tuple[dict[str, Any], dict[str, int]]] = {}
    for source in physical_rows:
        dataset_name = _clean_name(source.get("dataset_name"))
        key = dataset_name.casefold()
        if not key:
            continue
        if key not in by_name:
            by_name[key] = (
                {
                    "name": dataset_name,
                    "last_modified": "",
                    "last_modified_timestamp": 0.0,
                    "created": "",
                    "created_timestamp": 0.0,
                    "user": "",
                },
                {"name": int(source.get("_field_priority") or 0)},
            )
        state, priorities = by_name[key]
        field_priority = int(source.get("_field_priority") or 0)
        _set_by_priority(state, priorities, "name", dataset_name, field_priority)
        for field in (
            "dataset_type",
            "dataset_category",
            "source_kind",
            "data_format",
            "origin_length",
            "development_length",
            "stored_origin_length",
            "stored_development_length",
            "method_type",
            "method_name",
            "status",
            "formula",
            "user",
        ):
            _set_by_priority(
                state,
                priorities,
                field,
                source.get(field),
                field_priority,
            )

        modified_priority = int(source.get("_modified_priority") or 0)
        modified_timestamp = _numeric_timestamp(
            source.get("last_modified_timestamp")
        )
        current_modified_priority = priorities.get("last_modified", -1)
        if modified_timestamp and (
            modified_priority > current_modified_priority
            or (
                modified_priority == current_modified_priority
                and modified_timestamp
                > _numeric_timestamp(state.get("last_modified_timestamp"))
            )
        ):
            state["last_modified"] = _clean_text(source.get("last_modified"))
            state["last_modified_timestamp"] = modified_timestamp
            priorities["last_modified"] = modified_priority

        created_priority = int(source.get("_created_priority") or 0)
        created_timestamp = _numeric_timestamp(source.get("created_timestamp"))
        current_created_priority = priorities.get("created", -1)
        if created_timestamp and (
            created_priority > current_created_priority
            or (
                created_priority == current_created_priority
                and (
                    not _numeric_timestamp(state.get("created_timestamp"))
                    or created_timestamp
                    < _numeric_timestamp(state.get("created_timestamp"))
                )
            )
        ):
            state["created"] = _clean_text(source.get("created"))
            state["created_timestamp"] = created_timestamp
            priorities["created"] = created_priority

    output: list[dict[str, Any]] = []
    for state, _priorities in by_name.values():
        state["dataset_type"] = (
            _clean_name(state.get("dataset_type")) or state["name"]
        )
        state["method_type"] = _normalize_method_type(
            state.get("method_type"),
            state.get("source_kind"),
        )
        state["status"] = _normalize_status(state.get("status"))
        output.append(canonicalize_index_row(state))
    output.sort(key=lambda item: (_clean_text(item["name"]).casefold(), item["name"]))
    return output


def canonicalize_index_row(source: Mapping[str, Any]) -> dict[str, Any]:
    """Project a row onto the exact scalar-only index schema."""

    name = _clean_name(source.get("name") or source.get("dataset_name"))
    row: dict[str, Any] = {}
    for field in INDEX_ROW_FIELDS:
        value = source.get(field)
        if field == "name":
            value = name
        elif field == "dataset_type":
            value = _clean_name(value) or name
        elif field in {
            "dataset_category",
            "source_kind",
            "data_format",
            "formula",
            "last_modified",
            "created",
            "user",
        }:
            value = _clean_text(value)
        elif field == "method_name":
            value = _clean_name(value)
            if value.casefold() == name.casefold():
                value = ""
        elif field == "method_type":
            value = _normalize_method_type(value, source.get("source_kind"))
        elif field == "status":
            value = _normalize_status(value)
        elif field in {"last_modified_timestamp", "created_timestamp"}:
            value = _numeric_timestamp(value)

        always_include = field in _REQUIRED_ROW_FIELDS
        if _scalar(value) and (always_include or value not in (None, "")):
            row[field] = value
    return row


def make_folder_signature(
    files: Iterable[Mapping[str, Any] | _FileStat],
    folder_exists: Mapping[str, Any],
) -> str:
    """Hash only relative folder/name/stat data and folder existence."""

    signature_files: list[dict[str, Any]] = []
    for item in files:
        if isinstance(item, _FileStat):
            folder, name, size, mtime_ns = (
                item.folder,
                item.name,
                item.size,
                item.mtime_ns,
            )
        else:
            folder = _clean_text(item.get("folder"))
            name = _clean_text(item.get("name"))
            size = int(item.get("size") or 0)
            mtime_ns = int(item.get("mtime_ns") or 0)
        signature_files.append(
            {
                "folder": folder,
                "name": name,
                "size": size,
                "mtime_ns": mtime_ns,
            }
        )
    signature_files.sort(
        key=lambda item: (
            item["folder"].casefold(),
            item["name"].casefold(),
            item["name"],
        )
    )
    source = {
        "folders": {
            key: bool(folder_exists.get(key))
            for key in FOLDER_PATH_FIELDS
        },
        "files": signature_files,
    }
    serialized = json.dumps(source, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


folder_signature = make_folder_signature


def migrate_legacy_notes_files(rc_dir: str | os.PathLike[str]) -> int:
    """Move legacy standalone notes into existing dataset sidecars, then remove them."""
    sidecar_dir = Path(rc_dir) / SIDECAR_DIR_NAME
    if not sidecar_dir.is_dir():
        return 0
    migrated = 0
    for legacy_path in sorted(sidecar_dir.glob(f"{LEGACY_NOTES_FILE_PREFIX}*.json"), key=lambda item: item.name.casefold()):
        target_name = legacy_path.name[len(LEGACY_NOTES_FILE_PREFIX):]
        target_path = sidecar_dir / target_name
        if not target_path.is_file():
            continue
        legacy_payload = _safe_read_json(legacy_path)
        sidecar_payload = _safe_read_json(target_path)
        if not isinstance(legacy_payload, Mapping) or not isinstance(sidecar_payload, Mapping):
            continue
        updated = dict(sidecar_payload)
        if "notes" not in updated:
            updated["notes"] = str(legacy_payload.get("notes") or "")
            tmp_path = target_path.with_name(f"{target_path.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp_path.write_text(persisted_json_text(updated), encoding="utf-8", newline="\n")
                os.replace(tmp_path, target_path)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass
        legacy_path.unlink()
        migrated += 1
    return migrated


def build_dataset_index_payload(
    project_name: str,
    reserving_class: str,
    rc_dir: str | os.PathLike[str],
    *,
    max_workers: int = 12,
) -> dict[str, Any]:
    """Build the one canonical persisted ``index.json`` payload.

    The enumeration happens here, inside whatever lock the caller holds, so the
    payload and its signature always describe the same observation of the folder.
    """

    root = Path(rc_dir)
    scan = scan_folder_signature(root, max_workers=max_workers)
    if scan.has_legacy_notes:
        # Migrating rewrites sidecars and removes the legacy files, so the
        # enumeration that saw them no longer describes the folder.
        migrate_legacy_notes_files(root)
        scan = scan_folder_signature(root, max_workers=max_workers)

    worker_count = max(1, min(int(max_workers or 1), 32))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="arcrho-index-contract",
    ) as executor:
        payloads = _read_payloads(scan.files, executor)

    physical_rows: list[dict[str, Any]] = []
    for file_stat in scan.files:
        if file_stat.path.suffix.casefold() == ".csv":
            metadata_path = dataset_sidecar_path_for_cached_csv(file_stat.path)
            metadata = payloads.get(_path_key(metadata_path), {})
            metadata = metadata if isinstance(metadata, Mapping) else {}
            if not metadata:
                # A data file with no sidecar is a runtime cache, not a dataset.
                continue
            metadata_is_sidecar = True
        else:
            metadata = payloads.get(_path_key(file_stat.path), {})
            metadata = metadata if isinstance(metadata, Mapping) else {}
            metadata_is_sidecar = file_stat.folder == SIDECAR_DIR_NAME
        row = _metadata_row(
            file_stat,
            metadata,
            metadata_is_sidecar=metadata_is_sidecar,
        )
        if row:
            physical_rows.append(row)

    return {
        "ok": True,
        "version": DATASET_INDEX_VERSION,
        "exists": bool(scan.folder_exists.get("data")),
        "project_name": _clean_text(project_name),
        "reserving_class": _clean_text(reserving_class),
        "folder_signature": scan.signature,
        "files": _merge_rows(physical_rows),
    }


def index_rebuild_reason(
    data: Any,
    *,
    expected_project_name: str | None = None,
    expected_reserving_class: str | None = None,
    expected_folder_signature: str | None = None,
) -> str:
    """Return a stable reason code when persisted index data is not current."""

    if not isinstance(data, Mapping):
        return "not-an-object"
    if set(data) != set(INDEX_TOP_LEVEL_FIELDS):
        return "top-level-fields"
    if data.get("version") != DATASET_INDEX_VERSION:
        return "version"
    if data.get("ok") is not True or not isinstance(data.get("exists"), bool):
        return "top-level-values"
    if not isinstance(data.get("project_name"), str) or not isinstance(
        data.get("reserving_class"), str
    ):
        return "identity"
    if (
        expected_project_name is not None
        and data["project_name"] != _clean_text(expected_project_name)
    ):
        return "project-name"
    if (
        expected_reserving_class is not None
        and data["reserving_class"] != _clean_text(expected_reserving_class)
    ):
        return "reserving-class"
    signature = data.get("folder_signature")
    if not isinstance(signature, str) or not _SIGNATURE_RE.fullmatch(signature):
        return "folder-signature"
    if (
        expected_folder_signature is not None
        and signature != expected_folder_signature
    ):
        return "folder-signature-changed"
    files = data.get("files")
    if not isinstance(files, list):
        return "files"
    names: list[str] = []
    allowed_fields = set(INDEX_ROW_FIELDS)
    for row in files:
        if not isinstance(row, Mapping):
            return "row-object"
        fields = set(row)
        if fields.intersection(FORBIDDEN_INDEX_ROW_FIELDS):
            return "row-forbidden-fields"
        if not _REQUIRED_ROW_FIELDS.issubset(fields) or not fields.issubset(
            allowed_fields
        ):
            return "row-fields"
        if any(not _scalar(value) for value in row.values()):
            return "row-nonscalar"
        name = row.get("name")
        if not isinstance(name, str) or not _clean_name(name):
            return "row-name"
        if not isinstance(row.get("dataset_type"), str):
            return "row-dataset-type"
        if isinstance(row.get("status"), bool) or not isinstance(
            row.get("status"), int
        ):
            return "row-status"
        if any(
            isinstance(row.get(field), bool)
            or not isinstance(row.get(field), (int, float))
            for field in ("last_modified_timestamp", "created_timestamp")
        ):
            return "row-timestamp"
        if dict(row) != canonicalize_index_row(row):
            return "row-noncanonical"
        names.append(name)
    expected_order = sorted(names, key=lambda value: (value.casefold(), value))
    if names != expected_order:
        return "row-order"
    if len({name.casefold() for name in names}) != len(names):
        return "row-duplicate"
    return ""


def is_current_index(
    data: Any,
    *,
    expected_project_name: str | None = None,
    expected_reserving_class: str | None = None,
    expected_folder_signature: str | None = None,
) -> bool:
    return not index_rebuild_reason(
        data,
        expected_project_name=expected_project_name,
        expected_reserving_class=expected_reserving_class,
        expected_folder_signature=expected_folder_signature,
    )


def serialize_index_json(payload: Mapping[str, Any]) -> str:
    """Return deterministic UTF-8 JSON text for a canonical index payload."""

    return persisted_json_text(payload)


def _is_lock_error(error: OSError) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in (
        _WINDOWS_LOCK_ERRORS
    )


@contextmanager
def index_update_lock(
    path: str | os.PathLike[str],
    *,
    project_name: str = "",
    reserving_class: str = "",
    timeout_seconds: float = _INDEX_UPDATE_LOCK_TIMEOUT_SECONDS,
):
    """Serialize a complete index scan/write transaction across processes."""

    logical_identity = "\0".join(
        (_clean_text(project_name).casefold(), _clean_text(reserving_class).casefold())
    )
    identity = logical_identity.strip("\0") or _path_key(Path(path))
    lock_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    with _PROCESS_INDEX_LOCKS_GUARD:
        process_lock = _PROCESS_INDEX_LOCKS.setdefault(lock_key, threading.Lock())
    lock_path = Path(path).with_name(f".{Path(path).name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not process_lock.acquire(timeout=max(0.001, float(timeout_seconds))):
        raise TimeoutError(f"Timed out waiting for dataset index update lock: {path}")
    try:
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            deadline = time.monotonic() + max(0.001, float(timeout_seconds))
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError as error:
                        if not _is_lock_error(error) or time.monotonic() >= deadline:
                            if _is_lock_error(error):
                                raise TimeoutError(
                                    f"Timed out waiting for dataset index update lock: {path}"
                                ) from error
                            raise
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(
                            lock_file.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError as error:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(
                                f"Timed out waiting for dataset index update lock: {path}"
                            ) from error
                        time.sleep(0.05)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        process_lock.release()


def write_index_json_unlocked(
    path: str | os.PathLike[str],
    payload: Mapping[str, Any],
) -> bool:
    """Write inside :func:`index_update_lock`; return ``False`` if unchanged."""

    destination = Path(path)
    text = serialize_index_json(payload)
    try:
        if destination.read_text(encoding="utf-8") == text:
            return False
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{threading.get_ident()}."
        f"{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        for delay in (*_INDEX_REPLACE_RETRY_DELAYS, None):
            try:
                os.replace(temporary, destination)
                return True
            except OSError as error:
                if delay is None or not _is_lock_error(error):
                    raise
                time.sleep(delay)
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass
    return True


def write_index_json(
    path: str | os.PathLike[str],
    payload: Mapping[str, Any],
) -> bool:
    """Atomically write one payload under the shared cross-process lock."""

    with index_update_lock(
        path,
        project_name=_clean_text(payload.get("project_name")),
        reserving_class=_clean_text(payload.get("reserving_class")),
    ):
        return write_index_json_unlocked(path, payload)
