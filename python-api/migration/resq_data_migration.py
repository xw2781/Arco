"""
resq_data_migration.py

Migrate ResQ triangles, vectors, Result Selections, Bornhuetter Ferguson methods, Cape Cod methods, Bootstrap methods, Stochastic Consolidations, and DFM methods to ArcRho dataset files.
Scope: ProjectName = '{PROJECT_NAME}'
Output: E:\\Arco Server\\projects\\{PROJECT_NAME}\\data\\<ReservingClassFolder>\\

Run:
  python resq_data_migration.py
  python resq_data_migration.py --no-cleanup-target
  python resq_dfm_export.py --export triangles
  python resq_dfm_export.py --export vectors
  python resq_dfm_export.py --export dfm
  python resq_dfm_export.py --export all
"""
from __future__ import annotations

PROJECT_NAME = "NJ_Annual_Prod_202605_Fake"
# PROJECT_NAME = "NJ_Annual_Prod_2026 Q3-Aug"
# PROJECT_NAME = "NJ_Annual_Prod_2026 Q2-May"
# PROJECT_NAME = "NJ_Annual_Prod_2026 Q2-May Test"
# PROJECT_NAME = "NJ_Annual_Prod_2026 Q1-Feb"

# RC_PATH may be a string or a list of reserving-class paths.
RC_PATH = [
    r"PRNJ - PA\PA\NY\Direct Group\BI Total",
    r"PRNJ - PA\PA\NY\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\BI Total",
    r"PRNJ - PA\PA\Penn+CT\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\All States\Direct Group\PD+UMPD",
    r"PRNJ - PA\PA\All States\Direct Group\COL",
    r"PRNJ - PA\PA\All States\Direct Group\CMPxCAT",
    r"PRNJ - PA\PA\NJ\Direct Group\MP+PIP",
    r"PRNJ - PA\PA\NJ\Direct Group\BIR51+UMBIR51",
    r"PRNJ - PA\PA\NJ\Direct Group\BIx51+UMBIx51",
    r"HPPREF\HO+DF\NJ\Legacy\HOL",
    r"HPPREF\HO+DF\NJ\Legacy\HOPxCAT",
    r"Rider\MC\All States\Direct Group\BI+PIP",
    r"Rider\MC\All States\Direct Group\PD+UMPD",
    r"Rider\MC\All States\Direct Group\PhysDxCat",
    r"PRNJ - PA\PA\MA\Direct Group\BI Total",
    r"PRNJ - PA\PA\MA\Direct Group\MP+PIP",
]


import argparse
import json
import re
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_MIGRATION_DIR = Path(__file__).resolve().parent
_PYTHON_API_SRC = _MIGRATION_DIR.parent / "src"
if str(_PYTHON_API_SRC) not in sys.path:
    sys.path.insert(0, str(_PYTHON_API_SRC))
if str(_MIGRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATION_DIR))

from arcrho_log_retention_contract import apply_log_retention  # noqa: E402
from arcrho_api.bornhuetter_ferguson_contract import BF_JSON_FORMAT  # noqa: E402
from arcrho_api.cape_cod_contract import CC_JSON_FORMAT  # noqa: E402
from arcrho_api.dfm_contract import DFM_JSON_FORMAT  # noqa: E402
from arcrho_api.client import ArcRhoClient  # noqa: E402
from arcrho_api.dfm_propagation import (  # noqa: E402
    DfmPropagationResult,
    refresh_dfm_dependents_for_sources,
)

from resq_migration.catalog import (  # noqa: E402
    _dataset_type_rows,
    _dataset_type_keys,
    _is_calculated_dataset_type,
    _is_engine_generated_instance,
    _is_generated_dataset_type,
    _is_known_dataset_type,
    _is_unreviewed_dataset,
    _triangle_source_kind,
    _unknown_dataset_type_skip_detail,
    configure_catalog,
    rebuild_dataset_instance_index,
    refresh_sidecar_graphs_for_rc,
    engine_knows_reserving_class,
    resq_class_scope,
)
from resq_migration.engine_parity import (  # noqa: E402
    compare_import_values,
    describe_import_mismatch,
    read_engine_csv,
)
from resq_migration.core import (  # noqa: E402
    BS_CRA_FILE_PREFIX,
    BS_CRA_JSON_FORMAT,
    BS_CRA_METHOD_TYPE,
    BS_CRA_SOURCE_KIND,
    BS_SR_FILE_PREFIX,
    BS_SR_JSON_FORMAT,
    BS_SR_METHOD_TYPE,
    BS_SR_SOURCE_KIND,
    DATASET_CACHE_DIR,
    DATASET_INDEX_FILE_NAME,
    DATASET_INDEX_VERSION,
    DATASET_SIDECAR_DIR,
    METHOD_TYPE_BF_CODE,
    METHOD_TYPE_BOOTSTRAP_CODE,
    METHOD_TYPE_BS_CRA_CODE,
    METHOD_TYPE_BS_SR_CODE,
    METHOD_TYPE_CAPE_COD_CODE,
    METHOD_TYPE_DFM_CODE,
    METHOD_TYPE_NONE_CODE,
    METHOD_TYPE_RESULT_SELECTION_CODE,
    METHOD_TYPE_STOCHASTIC_CONSOLIDATION_CODE,
    _bool_value,
    _cached_dataset_names_from_file,
    _clean_name,
    _dataset_cache_csv_file_name,
    _encode_name_part,
    _encode_rc_folder,
    _json_sidecar_name,
    _normalize_cached_dataset_name,
    _normalize_import_name,
    _safe_attr,
    _safe_int_attr,
    _safe_read_json,
    _iso_or_text,
    _method_type_name,
    _vector_cache_csv_file_name,
)
from resq_migration.dfm import (  # noqa: E402
    configure_dfm,
    dfm_methods_by_output_name as _dfm_methods_by_output_name,
    export_dfm_output_dataset as _export_dfm_output_dataset,
    arcrho_average_rows_as_resq,
    average_formula_key,
    resq_average_row_labels,
    resq_average_rows_as_arcrho,
)
from resq_migration.extractors import (  # noqa: E402
    BS_CRA_AVERAGE_CASE_RESERVE_TYPES,
    BS_CRA_INFLATION_TYPES,
    _apply_berquist_sherman_triangle_metadata,
    _apply_bornhuetter_ferguson_vector_metadata,
    _apply_cape_cod_vector_metadata,
    _apply_result_selection_vector_metadata,
    _find_berquist_sherman_for_triangle,
    _find_bootstrap_for_vector,
    _find_bornhuetter_ferguson_for_vector,
    _find_cape_cod_for_vector,
    _find_result_selection_for_vector,
    _find_stochastic_consolidation_for_vector,
    _result_selection_source_payload,
    configure_extractors,
    defer_sidecar_graph_enrichment,
    export_bootstrap,
    export_bornhuetter_ferguson,
    export_berquist_sherman,
    export_cape_cod,
    export_stochastic_consolidation,
    export_result_selection,
    export_triangle,
    export_vector,
    resq_stored_lengths,
    write_bornhuetter_ferguson_export,
    write_berquist_sherman_export,
    write_bootstrap_export,
    write_cape_cod_export,
    write_engine_generated_export,
    write_result_selection_export,
    write_stochastic_consolidation_export,
    write_triangle_export,
    write_vector_export,
)
from resq_migration.number_formats import (  # noqa: E402
    configure_number_formats_path,
)
from resq_migration.merge import (  # noqa: E402
    merge_preserved_arcrho_artifacts,
    snapshot_reserving_class_artifacts,
)
from resq_migration.transfer_selection import (  # noqa: E402
    DIRECTION_IMPORT,
    save_selection as save_transfer_selection,
)
from resq_migration.engine import (  # noqa: E402
    EngineGenerationError,
    EngineRequestJob,
    EngineUnavailableError,
    cleanup_engine_request_job,
    create_engine_request_job,
    discover_fresh_engine_heartbeats,
    finalize_engine_request,
    get_engine_processing_provenance,
    import_user_identity_service,
    publish_engine_request,
    require_engine_workers,
    wait_for_engine_request,
)

# Public preflight used by the saved migration macro before it opens progress UI
# or connects to ResQ.
require_running_engine_instances = require_engine_workers
def _configured_rc_paths(value: object) -> list[str]:
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _normalize_import_name(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out

# ── Configuration ──────────────────────────────────────────────────────────────


CONNECTION_NAME = "JGO_CO1SQLWPV22"
USER_NAME = ""
PASSWORD = ""

SERVER_ROOT = Path(r"E:\Arco Server")
PROJECT_DATA_DIR = SERVER_ROOT / "projects" / PROJECT_NAME / "data"
RS_JSON_FORMAT = "arcrho-result-selection-v4"
INDEX_FILE_NAME = DATASET_INDEX_FILE_NAME
INDEX_VERSION = DATASET_INDEX_VERSION
METHOD_DATA_DIR = "methods"
DEBUG_LOG_PATH = Path(__file__).resolve().parent / "logs" / "resq_data_migration_debug.log"

# Stop probing average formula rows after this many consecutive misses
MAX_AVERAGE_FORMULA_PROBE = 30
ENGINE_DATASET_TIMEOUT_SEC = 60.0

# Dataset export controls. CLI --export can override these.
EXPORT_DFMS = True
EXPORT_TRIANGLES = True
EXPORT_VECTORS = True
CLEAN_TARGET_RC = True
TRIANGLE_NAMES: list[str] = []  # Empty means export all triangles in RC_PATH
VECTOR_NAMES: list[str] = []  # Empty means export all vectors in RC_PATH
DFM_NAMES: list[str] = []  # Empty means export all DFM methods in RC_PATH

ProgressCallback = Callable[[dict], None]


def _configure_migration_modules() -> None:
    configure_number_formats_path(SERVER_ROOT)
    configure_catalog(
        server_root=SERVER_ROOT,
        project_name=PROJECT_NAME,
        rs_json_format=RS_JSON_FORMAT,
        method_data_dir=METHOD_DATA_DIR,
    )
    configure_extractors(
        project_name=PROJECT_NAME,
        rs_json_format=RS_JSON_FORMAT,
        bf_json_format=BF_JSON_FORMAT,
        cc_json_format=CC_JSON_FORMAT,
        method_data_dir=METHOD_DATA_DIR,
    )
    configure_dfm(dfm_json_format=DFM_JSON_FORMAT)


_configure_migration_modules()


# ── JSON formatting ────────────────────────────────────────────────────────────

_debug_log_retention_applied = False


def _debug_log(event: str, **fields: object) -> None:
    global _debug_log_retention_applied
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _debug_log_retention_applied:
            _debug_log_retention_applied = True
            apply_log_retention(
                DEBUG_LOG_PATH.parent, appended_files=(DEBUG_LOG_PATH,)
            )
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        with DEBUG_LOG_PATH.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str))
            fh.write("\n")
    except Exception:
        pass


# ── Path / filename encoding ───────────────────────────────────────────────────

# ── Average formula helpers ────────────────────────────────────────────────────

def _require_safe_target_rc_dir(rc_dir: Path) -> Path:
    target = rc_dir.resolve(strict=False)
    project_data = PROJECT_DATA_DIR.resolve(strict=False)
    if target == project_data or target.parent != project_data:
        raise ValueError(
            "Refusing to clean target reserving-class folder outside the configured project data directory: "
            f"{target}"
        )
    if not target.name:
        raise ValueError("Refusing to clean target reserving-class folder with an empty folder name.")
    return target


def cleanup_target_reserving_class_dir(rc_dir: Path) -> tuple[int, int]:
    """Remove the existing target reserving-class folder contents before export."""
    target = _require_safe_target_rc_dir(rc_dir)
    if not target.exists():
        return 0, 0
    if target.is_symlink():
        raise ValueError(f"Refusing to clean symlinked reserving-class folder: {target}")

    files = 0
    dirs = 0
    lock_file_name = f".{INDEX_FILE_NAME}.lock"
    for item in target.rglob("*"):
        if item.parent == target and item.name.casefold() == lock_file_name.casefold():
            continue
        if item.is_dir():
            dirs += 1
        else:
            files += 1
    for item in list(target.iterdir()):
        if item.name.casefold() == lock_file_name.casefold():
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    return files, dirs


def _normalized_name_keys(values: object) -> set[str]:
    raw = values if isinstance(values, (list, tuple, set)) else [values]
    out: set[str] = set()
    for value in raw:
        text = _normalize_import_name(value)
        if text:
            out.add(text.casefold())
    return out


def _matches_cleanup_names(values: object, target_keys: set[str]) -> bool:
    if not target_keys:
        return False
    return bool(_normalized_name_keys(values) & target_keys)


def _method_file_names(path: Path) -> set[str]:
    stem = path.stem
    for prefix in ("DFM@", "RS@", "BF@", "CC@", BS_SR_FILE_PREFIX, BS_CRA_FILE_PREFIX):
        if stem.startswith(prefix):
            name = _normalize_cached_dataset_name(stem[len(prefix):])
            return {name} if name else set()
    return set()


def _dict_field(source: dict, key: str) -> dict:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _method_payload_dataset_names(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, dict):
        return set()

    names: set[str] = set()
    if path.name.startswith("DFM@"):
        details = _dict_field(payload, "details_tab")
        for key in ("output_dataset", "output_type"):
            name = _normalize_import_name(details.get(key))
            if name:
                names.add(name)
    elif path.name.startswith("RS@"):
        details = _dict_field(payload, "details_tab")
        for key in ("name", "output_type"):
            name = _normalize_import_name(details.get(key))
            if name:
                names.add(name)
    elif path.name.startswith("BF@"):
        details = _dict_field(payload, "details_tab")
        method = _dict_field(payload, "method_tab")
        for key in ("name", "output_type"):
            name = _normalize_import_name(details.get(key))
            if name:
                names.add(name)
        for key in ("latest_dataset", "dfm_dataset", "percentage_developed_dataset"):
            name = _normalize_import_name(method.get(key))
            if name:
                names.add(name)
        prior_datasets_value = method.get("prior_datasets")
        prior_datasets = prior_datasets_value if isinstance(prior_datasets_value, list) else []
        for prior in prior_datasets:
            name = _normalize_import_name(prior.get("name")) if isinstance(prior, dict) else ""
            if name:
                names.add(name)
        if not prior_datasets:
            legacy_prior_name = _normalize_import_name(method.get("prior_dataset"))
            if legacy_prior_name:
                names.add(legacy_prior_name)
    elif path.name.startswith("CC@"):
        details = _dict_field(payload, "details_tab")
        method = _dict_field(payload, "method_tab")
        for key in ("name", "output_type"):
            name = _normalize_import_name(details.get(key))
            if name:
                names.add(name)
        for key in ("latest_dataset", "exposure_dataset", "prior_ultimate_dataset"):
            name = _normalize_import_name(method.get(key))
            if name:
                names.add(name)
    elif path.name.startswith((BS_SR_FILE_PREFIX, BS_CRA_FILE_PREFIX)):
        details = _dict_field(payload, "details_tab")
        for key in ("name", "output_type"):
            name = _normalize_import_name(details.get(key))
            if name:
                names.add(name)
    return names


def cleanup_target_dataset_artifacts(
    rc_dir: Path,
    *,
    dataset_names: list[str] | tuple[str, ...] | set[str] | None = None,
    method_names: list[str] | tuple[str, ...] | set[str] | None = None,
    match_method_dependencies: bool = True,
    method_prefixes: list[str] | tuple[str, ...] | set[str] | None = None,
) -> tuple[int, int]:
    """Remove stale cached files for selected datasets/methods before single-item export.

    ``match_method_dependencies`` retains the historical single-item-import
    invalidation behavior by default. Selective synchronization disables it so
    replacing one precedent does not delete unrelated dependent method JSON;
    the canonical propagation walk refreshes those dependents after import.
    """
    target = _require_safe_target_rc_dir(rc_dir)
    if not target.exists():
        return 0, 0
    if target.is_symlink():
        raise ValueError(f"Refusing to clean symlinked reserving-class folder: {target}")

    dataset_keys = _normalized_name_keys(dataset_names or [])
    method_keys = _normalized_name_keys(method_names or [])
    allowed_prefixes = tuple(str(value) for value in (method_prefixes or []) if str(value))
    files = 0

    dataset_dir = target / DATASET_CACHE_DIR
    if dataset_dir.is_dir():
        for path in sorted(dataset_dir.glob("*.csv"), key=lambda item: item.name.lower()):
            if _matches_cleanup_names(_cached_dataset_names_from_file(path.name), dataset_keys):
                path.unlink()
                files += 1

    sidecar_dir = target / DATASET_SIDECAR_DIR
    if sidecar_dir.is_dir():
        for path in sorted(sidecar_dir.glob("*.json"), key=lambda item: item.name.lower()):
            if _matches_cleanup_names(_cached_dataset_names_from_file(path.name), dataset_keys):
                path.unlink()
                files += 1

    method_dir = target / METHOD_DATA_DIR
    if method_dir.is_dir():
        for path in sorted(method_dir.glob("*.json"), key=lambda item: item.name.lower()):
            if allowed_prefixes and not path.name.startswith(allowed_prefixes):
                continue
            method_file_names = _method_file_names(path)
            if (
                _matches_cleanup_names(method_file_names, method_keys)
                or (
                    match_method_dependencies
                    and (
                        _matches_cleanup_names(method_file_names, dataset_keys)
                        or _matches_cleanup_names(_method_payload_dataset_names(path), dataset_keys)
                    )
                )
            ):
                path.unlink()
                files += 1

    return files, 0


# ── Development-label helpers ──────────────────────────────────────────────────

# ── Cell-notes parsing ─────────────────────────────────────────────────────────

# ── Core extraction ────────────────────────────────────────────────────────────

def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def _report_progress(progress_callback: ProgressCallback | None, **payload: object) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(dict(payload))
    except Exception:
        pass


def _report_inventory_item(
    progress_callback: ProgressCallback | None,
    *,
    kind: str,
    noun: str,
    name: str,
    discovered: int,
) -> None:
    _report_progress(
        progress_callback,
        event="inventory",
        kind=kind,
        name=name,
        discovered=discovered,
        message=f"Scanning ResQ {noun}: {discovered} found",
    )


def _record_skipped(progress_state: dict) -> None:
    progress_state["skipped"] = int(progress_state.get("skipped") or 0) + 1


def _record_error_detail(progress_state: dict, *, kind: str, name: str, detail: str) -> None:
    _record_detail(progress_state, "error_details", kind=kind, name=name, detail=detail)


def _record_detail(progress_state: dict, field: str, *, kind: str, name: str, detail: str) -> None:
    details = progress_state.setdefault(field, [])
    if isinstance(details, list) and len(details) < 12:
        details.append({
            "kind": kind,
            "name": name,
            "message": detail,
        })


def _triangle_export_inventory(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[str], dict[str, object], dict[str, int]]:
    triangle_collection = reserving_class.Triangles()
    requested_names = [name.strip() for name in TRIANGLE_NAMES if str(name or "").strip()]
    source_items = (
        ((name, triangle_collection.Item(name)) for name in requested_names)
        if requested_names
        else (
            (_clean_name(_safe_attr(item, "Name", "")), item)
            for item in triangle_collection
        )
    )
    names: list[str] = []
    items: dict[str, object] = {}
    method_types: dict[str, int] = {}
    for name, item in source_items:
        clean_name = _clean_name(name)
        if not clean_name:
            continue
        key = clean_name.casefold()
        names.append(clean_name)
        items[key] = item
        method_types[key] = _safe_int_attr(item, "MethodType", METHOD_TYPE_NONE_CODE)
        _report_inventory_item(
            progress_callback,
            kind="triangle_inventory",
            noun="triangles",
            name=clean_name,
            discovered=len(names),
        )
    return names, items, method_types


def _triangle_export_names(reserving_class) -> list[str]:
    """Return triangle names through the canonical cached inventory reader."""

    names, _items, _method_types = _triangle_export_inventory(reserving_class)
    return names


def _vector_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    vector_collection = reserving_class.Vectors()
    if VECTOR_NAMES:
        return [name.strip() for name in VECTOR_NAMES if str(name or "").strip()]
    names: list[str] = []
    for item in vector_collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="vector_inventory",
            noun="vectors",
            name=name,
            discovered=len(names),
        )
    return names


def _dfm_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    dfm_collection = reserving_class.DFMMethods()
    if DFM_NAMES:
        return [_clean_name(name) for name in DFM_NAMES if _clean_name(name)]
    names: list[str] = []
    for item in dfm_collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="dfm_inventory",
            noun="DFM methods",
            name=name,
            discovered=len(names),
        )
    return names


def _bf_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    try:
        bf_collection = reserving_class.BFMethods()
    except Exception:
        return []
    names: list[str] = []
    for item in bf_collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="bf_inventory",
            noun="BF methods",
            name=name,
            discovered=len(names),
        )
    return names


def _cc_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    try:
        cc_collection = reserving_class.CapeCodMethods()
    except Exception:
        return []
    names: list[str] = []
    for item in cc_collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="cc_inventory",
            noun="Cape Cod methods",
            name=name,
            discovered=len(names),
        )
    return names


def _bootstrap_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    try:
        bootstrap_collection = reserving_class.BootstrapMethods()
    except Exception:
        return []
    names: list[str] = []
    for item in bootstrap_collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="bootstrap_inventory",
            noun="Bootstrap methods",
            name=name,
            discovered=len(names),
        )
    return names


def _stochastic_consolidation_export_names(
    reserving_class,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    try:
        collection = reserving_class.BootstrapConsolidations()
    except Exception:
        return []
    names: list[str] = []
    for item in collection:
        name = _clean_name(_safe_attr(item, "Name", ""))
        if not name:
            continue
        names.append(name)
        _report_inventory_item(
            progress_callback,
            kind="stochastic_consolidation_inventory",
            noun="Stochastic Consolidations",
            name=name,
            discovered=len(names),
        )
    return names


def _berquist_sherman_export_names(
    triangle_names: list[str],
    triangle_method_types: dict[str, int],
) -> tuple[list[str], list[str]]:
    sr_names: list[str] = []
    cra_names: list[str] = []
    for name in triangle_names:
        method_type = triangle_method_types.get(name.casefold(), METHOD_TYPE_NONE_CODE)
        if method_type == METHOD_TYPE_BS_SR_CODE:
            sr_names.append(name)
        elif method_type == METHOD_TYPE_BS_CRA_CODE:
            cra_names.append(name)
    return sr_names, cra_names


def resq_export_dataset_counts(
    reserving_class,
    *,
    run_triangles: bool = True,
    run_vectors: bool = True,
    run_dfms: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Return ResQ dataset counts plus method counts for one reserving class."""

    _report_progress(
        progress_callback,
        event="inventory",
        kind="resq_inventory",
        message="Scanning ResQ datasets and methods...",
    )
    triangle_names, triangle_items, triangle_method_types = (
        _triangle_export_inventory(reserving_class, progress_callback)
        if run_triangles
        else ([], {}, {})
    )
    vector_names = _vector_export_names(reserving_class, progress_callback) if run_vectors else []
    dfm_names = _dfm_export_names(reserving_class, progress_callback) if run_dfms else []
    bf_names = _bf_export_names(reserving_class, progress_callback) if run_dfms else []
    cc_names = _cc_export_names(reserving_class, progress_callback) if run_dfms else []
    bootstrap_names = _bootstrap_export_names(reserving_class, progress_callback) if run_dfms else []
    scon_names = _stochastic_consolidation_export_names(reserving_class, progress_callback) if run_dfms else []
    bssr_names, bscra_names = (
        _berquist_sherman_export_names(triangle_names, triangle_method_types)
        if run_triangles
        else ([], [])
    )
    return {
        "triangles": len(triangle_names),
        "vectors": len(vector_names),
        "dfms": len(dfm_names),
        "bfs": len(bf_names),
        "ccs": len(cc_names),
        "bootstraps": len(bootstrap_names),
        "stochastic_consolidations": len(scon_names),
        "bssrs": len(bssr_names),
        "bscras": len(bscra_names),
        "methods": (
            len(dfm_names)
            + len(bf_names)
            + len(cc_names)
            + len(bootstrap_names)
            + len(scon_names)
            + len(bssr_names)
            + len(bscra_names)
        ),
        "total": len(triangle_names) + len(vector_names),
        "triangle_names": triangle_names,
        "triangle_items": triangle_items,
        "triangle_method_types": triangle_method_types,
        "vector_names": vector_names,
        "dfm_names": dfm_names,
        "bf_names": bf_names,
        "cc_names": cc_names,
        "bootstrap_names": bootstrap_names,
        "stochastic_consolidation_names": scon_names,
        "bssr_names": bssr_names,
        "bscra_names": bscra_names,
    }


def _select_export_inventory(dataset_counts: dict, selected_names: list[str] | None, reserving_class=None) -> dict:
    """Narrow a ResQ inventory to the dataset and method outputs a person ticked.

    Every method is imported through its output dataset, so narrowing the two
    dataset lists narrows the methods with them: the method name lists stay as
    they are and simply stop matching anything that was left unticked.

    A dataset the review never offers -- calculated or engine-generated -- is
    kept whether or not it was ticked, since nobody could have ticked it. Its
    Dataset Type is read from ResQ only for a name that was not ticked.
    """

    if selected_names is None:
        return dataset_counts
    chosen = {_normalize_import_name(name).casefold() for name in selected_names}
    chosen.discard("")
    triangle_items = dataset_counts.get("triangle_items") or {}
    vector_collection = reserving_class.Vectors() if reserving_class is not None else None

    def wanted(field: str, name: str) -> bool:
        key = _normalize_import_name(name).casefold()
        if key in chosen:
            return True
        item = triangle_items.get(name.casefold()) if field == "triangle_names" else None
        if item is None and field == "vector_names" and vector_collection is not None:
            item = vector_collection.Item(name)
        dataset_type_obj = _safe_attr(item, "DatasetType", None)
        dataset_type = _normalize_import_name(_safe_attr(dataset_type_obj, "Name", "")) or name
        return _is_unreviewed_dataset(name, dataset_type)

    narrowed = dict(dataset_counts)
    for field in ("triangle_names", "vector_names"):
        narrowed[field] = [name for name in dataset_counts.get(field) or [] if wanted(field, name)]
    narrowed["triangles"] = len(narrowed["triangle_names"])
    narrowed["vectors"] = len(narrowed["vector_names"])
    narrowed["total"] = narrowed["triangles"] + narrowed["vectors"]
    sr_names, cra_names = _berquist_sherman_export_names(
        narrowed["triangle_names"],
        dataset_counts.get("triangle_method_types") or {},
    )
    narrowed["bssr_names"], narrowed["bscra_names"] = sr_names, cra_names
    narrowed["bssrs"], narrowed["bscras"] = len(sr_names), len(cra_names)
    return narrowed


def _engine_generated_metadata_payload(
    item,
    *,
    name: str,
    dataset_type: str,
    is_vector: bool,
    strict: bool = False,
) -> dict:
    """Read only the ResQ metadata needed for an engine-owned sidecar."""

    def read(source, member: str, default=None) -> Any:
        if not strict:
            return _safe_attr(source, member, default)
        try:
            return getattr(source, member)
        except Exception as exc:
            raise RuntimeError(
                f"Could not read generated ResQ dataset {name!r} {member}."
            ) from exc

    def read_int(source, member: str, default: int = 0) -> int:
        value = read(source, member, default)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Generated ResQ dataset {name!r} has invalid {member}: {value!r}."
            ) from exc

    dataset_type_obj = read(item, "DatasetType", None)
    resolved_name = _normalize_import_name(read(item, "Name", "")) or _normalize_import_name(name)
    resolved_type = (
        _normalize_import_name(dataset_type)
        or _normalize_import_name(read(dataset_type_obj, "Name", ""))
        or resolved_name
    )
    if is_vector:
        period_length = read_int(item, "PeriodLength", 0)
        if period_length <= 0:
            period_length = read_int(item, "OriginLength", 12)
        origin_length = development_length = period_length
    else:
        origin_length = read_int(item, "OriginLength", 12)
        development_length = read_int(item, "DevelopmentLength", 12)
        period_length = 0
    if strict and (origin_length <= 0 or development_length <= 0):
        raise RuntimeError(
            f"Generated ResQ dataset {name!r} has non-positive display dimensions."
        )
    # ResQ's stored lengths say how fine the dataset's data really is. A
    # generated dataset is stored at the source data's granularity (monthly in
    # a monthly project) however coarsely ResQ displays it, and that is the
    # shape the Engine can rebuild it at, so the sidecar records it as such.
    stored_origin, stored_development = resq_stored_lengths(
        item,
        is_vector=is_vector,
        origin_length=origin_length,
        development_length=development_length,
    )

    category_obj = read(dataset_type_obj, "Category", None)

    payload = {
        "name": resolved_name,
        "dataset_type": resolved_type,
        "category": _normalize_import_name(
            read(category_obj, "Name", "") if category_obj is not None else ""
        ),
        "data_format": read_int(dataset_type_obj, "DataFormat", 1 if is_vector else 0),
        "origin_length": origin_length,
        "development_length": development_length,
        "stored_origin_length": stored_origin,
        "stored_development_length": stored_development,
        "user": _normalize_import_name(read(item, "User", "")),
        "created": _iso_or_text(read(item, "Created", "")),
        "modified": _iso_or_text(read(item, "Modified", "")),
    }
    if is_vector:
        payload["period_length"] = period_length
        payload["stored_period_length"] = stored_origin
    return payload


def _create_engine_generated_task(
    payload: dict,
    rc_path: str,
    rc_dir: Path,
    *,
    is_vector: bool,
    resq_item=None,
) -> dict:
    """Create, but do not publish, one external worker request.

    ``resq_item`` is the ResQ dataset the Engine result is compared with once
    it has been written; its values are never read before then.
    """

    name = _normalize_import_name(payload["name"])
    dataset_type = _normalize_import_name(payload.get("dataset_type")) or name
    if is_vector:
        period_length = int(payload.get("period_length") or payload.get("origin_length") or 0)
        origin_length = development_length = period_length
        csv_name = _vector_cache_csv_file_name(name, period_length)
    else:
        origin_length = int(payload["origin_length"])
        development_length = int(payload["development_length"])
        csv_name = _dataset_cache_csv_file_name(name, origin_length, development_length)
    csv_path = rc_dir / DATASET_CACHE_DIR / csv_name
    job = create_engine_request_job(
        project_name=PROJECT_NAME,
        rc_path=rc_path,
        dataset_type=dataset_type,
        data_path=csv_path,
        origin_length=origin_length,
        development_length=development_length,
        is_vector=is_vector,
        server_root=SERVER_ROOT,
    )
    return {
        "job": job,
        "payload": payload,
        "rc_path": rc_path,
        "rc_dir": rc_dir,
        "is_vector": is_vector,
        "kind": "vector" if is_vector else "triangle",
        "name": name,
        "csv_name": csv_name,
        "resq_item": resq_item,
    }


def _compare_engine_result_with_resq(task: dict, csv_path: Path) -> str:
    """Return a warning when the written Engine dataset disagrees with ResQ, else ``""``.

    ArcRho keeps the Engine result either way; the comparison only tells the
    person importing that ResQ would show different numbers. A comparison that
    cannot be made is reported the same way rather than failing the import.
    """

    item = task.get("resq_item")
    if item is None:
        return ""
    try:
        payload = export_vector(item) if task["is_vector"] else export_triangle(item)
        comparison = compare_import_values(
            payload.get("values") if isinstance(payload.get("values"), list) else [],
            read_engine_csv(csv_path),
        )
    except Exception as exc:
        return f"Could not be compared with ResQ: {exc}"
    return describe_import_mismatch(comparison)


def _complete_engine_generated_tasks(
    tasks: list[dict],
    *,
    provenance: dict,
    progress_callback: ProgressCallback | None,
    progress_state: dict,
    verbose: bool,
) -> tuple[int, int]:
    """Publish the whole batch first, then finalize each completed worker result."""

    if not tasks:
        return 0, 0

    published: list[dict] = []
    written = errors = 0
    try:
        require_running_engine_instances(tasks[0]["job"].server_root)
        _report_progress(
            progress_callback,
            event="engine_submit",
            kind="engine_batch",
            completed=int(progress_state.get("completed") or 0),
            total=int(progress_state.get("total") or len(tasks)),
            engine_completed=0,
            engine_total=len(tasks),
            message=f"Submitting {len(tasks)} generated dataset(s) to Arco Engine...",
        )
        for engine_index, task in enumerate(tasks, start=1):
            job = task["job"]
            try:
                publish_engine_request(job, check_workers=False)
                published.append(task)
                _report_progress(
                    progress_callback,
                    event="engine_submit",
                    kind="engine_batch",
                    name=task["name"],
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(tasks)),
                    engine_position=engine_index,
                    engine_total=len(tasks),
                    message=f"Submitted generated dataset {engine_index} of {len(tasks)}: {task['name']}",
                )
            except EngineUnavailableError:
                raise
            except Exception as exc:
                detail = f"    ERR {task['kind']} {task['name']}: {exc}"
                _log(verbose, detail)
                _record_error_detail(
                    progress_state,
                    kind=str(task["kind"]),
                    name=str(task["name"]),
                    detail=str(exc),
                )
                errors += 1
                progress_state["engine_errors"] = int(progress_state.get("engine_errors") or 0) + 1
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind=task["kind"],
                    name=task["name"],
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(tasks)),
                    status="error",
                    message=detail.strip(),
                )
                cleanup_engine_request_job(job)

        for engine_index, task in enumerate(published, start=1):
            job = task["job"]
            try:
                wait_message = (
                    f"Waiting for Arco Engine result {engine_index} of "
                    f"{len(published)}: {task['name']}"
                )
                _report_progress(
                    progress_callback,
                    event="engine_wait",
                    kind="engine_wait",
                    name=task["name"],
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(tasks)),
                    engine_position=engine_index,
                    engine_total=len(published),
                    message=wait_message,
                )
                wait_for_engine_request(
                    job,
                    timeout_sec=ENGINE_DATASET_TIMEOUT_SEC,
                    on_poll=lambda task=task, engine_index=engine_index, wait_message=wait_message: _report_progress(
                        progress_callback,
                        event="engine_wait",
                        kind="engine_wait",
                        name=task["name"],
                        completed=int(progress_state.get("completed") or 0),
                        total=int(progress_state.get("total") or len(tasks)),
                        engine_position=engine_index,
                        engine_total=len(published),
                        message=wait_message,
                    ),
                )
                csv_path = finalize_engine_request(job)
                write_engine_generated_export(
                    task["payload"],
                    task["rc_path"],
                    task["rc_dir"],
                    is_vector=bool(task["is_vector"]),
                    provenance=provenance,
                    csv_name=str(task["csv_name"]),
                    csv_path=csv_path,
                )
                parity_warning = _compare_engine_result_with_resq(task, csv_path)
                if parity_warning:
                    detail = f"    WARN engine (data-engine worker) {task['csv_name']}: {parity_warning}"
                    _record_detail(
                        progress_state,
                        "engine_parity_warnings",
                        kind=str(task["kind"]),
                        name=str(task["name"]),
                        detail=parity_warning,
                    )
                    progress_state["engine_parity_mismatches"] = (
                        int(progress_state.get("engine_parity_mismatches") or 0) + 1
                    )
                else:
                    detail = f"    OK  engine (data-engine worker) {task['csv_name']}"
                _log(verbose, detail)
                written += 1
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind=task["kind"],
                    name=task["name"],
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(tasks)),
                    status="warning" if parity_warning else "success",
                    message=detail.strip(),
                )
            except Exception as exc:
                detail = f"    ERR {task['kind']} {task['name']}: {exc}"
                _log(verbose, detail)
                if verbose:
                    traceback.print_exc(file=sys.stdout)
                _record_error_detail(
                    progress_state,
                    kind=str(task["kind"]),
                    name=str(task["name"]),
                    detail=str(exc),
                )
                errors += 1
                progress_state["engine_errors"] = int(progress_state.get("engine_errors") or 0) + 1
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind=task["kind"],
                    name=task["name"],
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(tasks)),
                    status="error",
                    message=detail.strip(),
                )
            finally:
                cleanup_engine_request_job(job)
    finally:
        for task in tasks:
            job = task.get("job")
            if isinstance(job, EngineRequestJob):
                cleanup_engine_request_job(job)
    return written, errors


def _skip_engine_generated_tasks(
    tasks: list[dict],
    *,
    progress_callback: ProgressCallback | None,
    progress_state: dict,
    reason: str,
    verbose: bool,
) -> None:
    """Report engine-owned datasets as skipped without reading their ResQ values.

    The caller has already read the small amount of instance metadata needed to
    form an engine request.  When no engine is available, that metadata must not
    cause a fallback to ResQ values: the previous engine cache is retained by
    the bridge transaction instead.
    """

    for task in tasks:
        detail = f"    SKIP engine {task['kind']} {task['name']}: {reason}"
        _log(verbose, detail)
        _record_skipped(progress_state)
        progress_state["engine_skipped"] = int(progress_state.get("engine_skipped") or 0) + 1
        progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
        _report_progress(
            progress_callback,
            event="finish",
            kind=task["kind"],
            name=task["name"],
            completed=int(progress_state.get("completed") or 0),
            total=int(progress_state.get("total") or len(tasks)),
            status="skipped",
            message=detail.strip(),
        )


def _write_engine_generated_dataset(
    payload: dict,
    rc_path: str,
    rc_dir: Path,
    *,
    is_vector: bool,
    provenance: dict | None = None,
) -> Path:
    """Synchronously generate one dataset through the external worker queue."""

    task = _create_engine_generated_task(payload, rc_path, rc_dir, is_vector=is_vector)
    job = task["job"]
    resolved_provenance = provenance or get_engine_processing_provenance(PROJECT_NAME)
    try:
        publish_engine_request(job)
        wait_for_engine_request(job, timeout_sec=ENGINE_DATASET_TIMEOUT_SEC)
        csv_path = finalize_engine_request(job)
        return write_engine_generated_export(
            payload,
            rc_path,
            rc_dir,
            is_vector=is_vector,
            provenance=resolved_provenance,
            csv_name=str(task["csv_name"]),
            csv_path=csv_path,
        )
    finally:
        cleanup_engine_request_job(job)


def export_triangles_for_rc(
    reserving_class,
    rc_path: str,
    rc_dir: Path,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_state: dict | None = None,
    triangle_names: list[str] | None = None,
    triangle_items: dict[str, object] | None = None,
    triangle_method_types: dict[str, int] | None = None,
    method_counts: dict | None = None,
    engine_provenance: dict | None = None,
    engine_available: bool = True,
    strict_extraction: bool = False,
    verbose: bool = True,
) -> tuple[int, int]:
    """Export triangle datasets for one reserving class. Returns (written, errors)."""
    triangle_collection = reserving_class.Triangles()
    if triangle_names is None:
        discovered_names, discovered_items, discovered_method_types = _triangle_export_inventory(
            reserving_class,
            progress_callback,
        )
        triangle_names = discovered_names
        triangle_items = discovered_items
        triangle_method_types = discovered_method_types
    else:
        triangle_names = list(triangle_names)
        triangle_items = triangle_items if isinstance(triangle_items, dict) else {}
        triangle_method_types = triangle_method_types if isinstance(triangle_method_types, dict) else {}

    _log(verbose, f"Triangles: {len(triangle_names)}")
    written = errors = 0
    engine_tasks: list[dict] = []
    progress_state = progress_state if isinstance(progress_state, dict) else {"completed": 0, "total": len(triangle_names)}
    known_dataset_type_keys = _dataset_type_keys()
    for triangle_name in triangle_names:
        _report_progress(
            progress_callback,
            event="start",
            kind="triangle",
            name=triangle_name,
            completed=int(progress_state.get("completed") or 0),
            total=int(progress_state.get("total") or len(triangle_names)),
            message=f"Importing triangle: {triangle_name}",
        )
        try:
            triangle_key = triangle_name.casefold()
            triangle = triangle_items.get(triangle_key)
            if triangle is None:
                triangle = triangle_collection.Item(triangle_name)
            method_type = triangle_method_types.get(triangle_key)
            if method_type is None:
                method_type = (
                    int(getattr(triangle, "MethodType"))
                    if strict_extraction
                    else _safe_int_attr(triangle, "MethodType", METHOD_TYPE_NONE_CODE)
                )
            bs_entry = _find_berquist_sherman_for_triangle(
                reserving_class,
                triangle_name,
                method_type,
            )
            if method_type in {METHOD_TYPE_BS_SR_CODE, METHOD_TYPE_BS_CRA_CODE} and bs_entry is None:
                raise ValueError(
                    f"Could not find the ResQ Berquist Sherman method attached to {triangle_name!r}."
                )
            if strict_extraction:
                dataset_type_obj = getattr(triangle, "DatasetType")
                dataset_type = _normalize_import_name(getattr(dataset_type_obj, "Name"))
            else:
                dataset_type_obj = _safe_attr(triangle, "DatasetType", None)
                dataset_type = _normalize_import_name(_safe_attr(dataset_type_obj, "Name", ""))
            if not _is_known_dataset_type(dataset_type, known_dataset_type_keys):
                detail = _unknown_dataset_type_skip_detail("triangle", triangle_name, dataset_type)
                _log(verbose, detail)
                _record_skipped(progress_state)
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind="triangle",
                    name=triangle_name,
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(triangle_names)),
                    status="skipped",
                    message=detail.strip(),
                )
                continue
            if bs_entry is None and _is_engine_generated_instance({
                "name": triangle_name,
                "dataset_type": dataset_type,
            }):
                engine_payload = _engine_generated_metadata_payload(
                    triangle,
                    name=triangle_name,
                    dataset_type=dataset_type,
                    is_vector=False,
                    strict=strict_extraction,
                )
                engine_tasks.append(
                    _create_engine_generated_task(
                        engine_payload,
                        rc_path,
                        rc_dir,
                        is_vector=False,
                        resq_item=triangle,
                    )
                )
                continue
            payload = export_triangle(
                triangle,
                method_type_code=method_type,
                strict=strict_extraction,
                # A hand-entered triangle is copied at the shape ResQ stores it
                # at, the only way its finer figures leave ResQ; a calculated
                # one is rebuilt by ArcRho from its components, and a Berquist
                # Sherman output belongs to its method, so both keep the shape
                # ResQ displayed.
                at_stored_shape=bs_entry is None and not _is_calculated_dataset_type(dataset_type),
            )
            if not _is_known_dataset_type(payload.get("dataset_type"), known_dataset_type_keys):
                detail = _unknown_dataset_type_skip_detail("triangle", payload.get("name") or triangle_name, payload.get("dataset_type"))
                _log(verbose, detail)
                _record_skipped(progress_state)
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind="triangle",
                    name=payload.get("name") or triangle_name,
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(triangle_names)),
                    status="skipped",
                    message=detail.strip(),
                )
                continue
            bs_payload = None
            if bs_entry is not None:
                variant, bs_method = bs_entry
                bs_payload = export_berquist_sherman(
                    bs_method,
                    variant,
                    payload,
                    strict=strict_extraction,
                )
                _apply_berquist_sherman_triangle_metadata(payload, bs_payload)

            if bs_payload is not None:
                write_triangle_export(payload, rc_path, rc_dir)
                method_path = write_berquist_sherman_export(bs_payload, rc_path, rc_dir)
                _log(verbose, f"    OK  {method_path.name}")
                source_kind = _clean_name(payload.get("source_kind"))
                if isinstance(method_counts, dict):
                    count_key = "bssr_written" if payload.get("method_type_code") == METHOD_TYPE_BS_SR_CODE else "bscra_written"
                    method_counts[count_key] = int(method_counts.get(count_key) or 0) + 1
            else:
                write_triangle_export(payload, rc_path, rc_dir)
                source_kind = _triangle_source_kind(payload["name"], payload.get("dataset_type", ""))
            detail = (
                f"    OK  {source_kind} "
                f"{_dataset_cache_csv_file_name(payload['name'], payload.get('stored_origin_length') or payload['origin_length'], payload.get('stored_development_length') or payload['development_length'])}"
            )
            _log(verbose, detail)
            written += 1
            progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="finish",
                kind="triangle",
                name=payload.get("name") or triangle_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or len(triangle_names)),
                status="success",
                message=detail.strip(),
            )
        except Exception as exc:
            detail = f"    ERR triangle {triangle_name}: {exc}"
            _log(verbose, detail)
            if verbose:
                traceback.print_exc(file=sys.stdout)
            _record_error_detail(progress_state, kind="triangle", name=triangle_name, detail=str(exc))
            errors += 1
            progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="finish",
                kind="triangle",
                name=triangle_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or len(triangle_names)),
                status="error",
                message=detail.strip(),
            )
    if engine_tasks and not engine_available:
        _skip_engine_generated_tasks(
            engine_tasks,
            progress_callback=progress_callback,
            progress_state=progress_state,
            reason="no active Arco Engine worker was available",
            verbose=verbose,
        )
    elif engine_tasks:
        resolved_provenance = engine_provenance or get_engine_processing_provenance(PROJECT_NAME)
        engine_written, engine_errors = _complete_engine_generated_tasks(
            engine_tasks,
            provenance=resolved_provenance,
            progress_callback=progress_callback,
            progress_state=progress_state,
            verbose=verbose,
        )
        written += engine_written
        errors += engine_errors
    return written, errors


def _read_migrated_dfm_payload(rc_dir: Path, dfm_name: str) -> dict:
    """The Arco DFM method JSON this import wrote, which a Bootstrap is built from."""

    path = rc_dir / METHOD_DATA_DIR / f"DFM@{_encode_name_part(dfm_name)}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"its DFM {dfm_name!r} was not imported into Arco, so it cannot be built"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"its DFM {dfm_name!r} method file is not a JSON object")
    return payload


def _export_bootstrap_tasks(
    tasks: list[tuple[str, object]],
    rc_path: str,
    rc_dir: Path,
    *,
    progress_callback: ProgressCallback | None,
    progress_state: dict,
    method_counts: dict | None,
    strict_extraction: bool,
    verbose: bool,
) -> tuple[int, int]:
    """Build and publish each Bootstrap the vector loop deferred."""

    written = errors = 0
    total = int(progress_state.get("total") or 0)
    for vector_name, bootstrap in tasks:
        try:
            dfm_name = _normalize_import_name(
                _safe_attr(_safe_attr(bootstrap, "DFMMethod", None), "Name", "")
            )
            if not dfm_name:
                raise ValueError("it does not name its DFM")
            dfm_payload = _read_migrated_dfm_payload(rc_dir, dfm_name)
            payload = export_bootstrap(
                bootstrap,
                dfm_payload=dfm_payload,
                strict=strict_extraction,
            )
            method_path = write_bootstrap_export(
                payload,
                rc_path,
                rc_dir,
                dfm_payload=dfm_payload,
            )
            detail = f"    OK  Bootstrap vector {vector_name}; {method_path.name}"
            _log(verbose, detail)
            if isinstance(method_counts, dict):
                method_counts["bootstraps_written"] = int(method_counts.get("bootstraps_written") or 0) + 1
            written += 1
            status = "success"
        except Exception as exc:
            detail = f"    ERR Bootstrap vector {vector_name}: {exc}"
            _log(verbose, detail)
            if verbose:
                traceback.print_exc(file=sys.stdout)
            _record_error_detail(progress_state, kind="vector", name=vector_name, detail=str(exc))
            errors += 1
            status = "error"
        progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
        _report_progress(
            progress_callback,
            event="finish",
            kind="vector",
            name=vector_name,
            completed=int(progress_state.get("completed") or 0),
            total=total,
            status=status,
            message=detail.strip(),
        )
    return written, errors


def _export_stochastic_consolidation_tasks(
    tasks: list[tuple[str, object]],
    rc_path: str,
    rc_dir: Path,
    *,
    progress_callback: ProgressCallback | None,
    progress_state: dict,
    method_counts: dict | None,
    strict_extraction: bool,
    verbose: bool,
) -> tuple[int, int]:
    """Build and publish each Stochastic Consolidation the vector loop deferred.

    A consolidation reads its segment bootstraps from their own classes, so it
    runs after this class's bootstraps are written. One whose segments are not
    all in Arco yet is written unrun, and the import says which are missing.
    """

    written = errors = 0
    total = int(progress_state.get("total") or 0)
    for vector_name, consolidation in tasks:
        status = "success"
        try:
            payload = export_stochastic_consolidation(
                consolidation,
                project_data_dir=PROJECT_DATA_DIR,
                strict=strict_extraction,
            )
            problem = str(payload.get("_import_problem") or "")
            method_path = write_stochastic_consolidation_export(payload, rc_path, rc_dir)
            if problem:
                detail = (
                    f"    WARN Stochastic Consolidation vector {vector_name}; {method_path.name} "
                    f"written without a run: {problem}"
                )
                _record_detail(
                    progress_state,
                    "consolidation_warnings",
                    kind="vector",
                    name=vector_name,
                    detail=f"Written without a run: {problem}",
                )
                status = "warning"
            else:
                detail = f"    OK  Stochastic Consolidation vector {vector_name}; {method_path.name}"
            _log(verbose, detail)
            if isinstance(method_counts, dict):
                method_counts["scons_written"] = int(method_counts.get("scons_written") or 0) + 1
            written += 1
        except Exception as exc:
            detail = f"    ERR Stochastic Consolidation vector {vector_name}: {exc}"
            _log(verbose, detail)
            if verbose:
                traceback.print_exc(file=sys.stdout)
            _record_error_detail(progress_state, kind="vector", name=vector_name, detail=str(exc))
            errors += 1
            status = "error"
        progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
        _report_progress(
            progress_callback,
            event="finish",
            kind="vector",
            name=vector_name,
            completed=int(progress_state.get("completed") or 0),
            total=total,
            status=status,
            message=detail.strip(),
        )
    return written, errors


def export_vectors_for_rc(
    reserving_class,
    rc_path: str,
    rc_dir: Path,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_state: dict | None = None,
    vector_names: list[str] | None = None,
    include_dfm_methods: bool = False,
    include_bf_methods: bool = False,
    include_cc_methods: bool = False,
    include_bootstrap_methods: bool = False,
    include_stochastic_consolidations: bool = False,
    dfm_names: list[str] | None = None,
    method_counts: dict | None = None,
    engine_provenance: dict | None = None,
    engine_available: bool = True,
    preserve_local_dfm_owned_state: bool = True,
    strict_extraction: bool = False,
    verbose: bool = True,
) -> tuple[int, int]:
    """Export vector datasets for one reserving class. Returns (written, errors).

    A Bootstrap's output vector is exported after every other vector, because
    the Bootstrap is built from the Arco DFM method this same loop writes. A
    Stochastic Consolidation's comes last of all, because it may include this
    class's own bootstraps.
    """
    vector_collection = reserving_class.Vectors()
    vector_names = list(vector_names) if vector_names is not None else _vector_export_names(reserving_class)
    dfm_by_output = _dfm_methods_by_output_name(reserving_class, dfm_names) if include_dfm_methods else {}

    _log(verbose, "Vectors: " + str(len(vector_names)))
    written = errors = 0
    engine_tasks: list[dict] = []
    bootstrap_tasks: list[tuple[str, object]] = []
    scon_tasks: list[tuple[str, object]] = []
    progress_state = progress_state if isinstance(progress_state, dict) else {"completed": 0, "total": len(vector_names)}
    known_dataset_type_keys = _dataset_type_keys()
    for vector_name in vector_names:
        _report_progress(
            progress_callback,
            event="start",
            kind="vector",
            name=vector_name,
            completed=int(progress_state.get("completed") or 0),
            total=int(progress_state.get("total") or len(vector_names)),
            message=f"Importing vector: {vector_name}",
        )
        try:
            vector = vector_collection.Item(vector_name)
            method_type = (
                int(getattr(vector, "MethodType"))
                if strict_extraction
                else _safe_int_attr(vector, "MethodType", -1)
            )
            dfm_entry = dfm_by_output.get(_normalize_import_name(vector_name).lower()) if method_type == METHOD_TYPE_DFM_CODE else None
            if dfm_entry is not None:
                dfm_name, dfm = dfm_entry
                output_dataset_name, detail, skipped = _export_dfm_output_dataset(
                    dfm,
                    rc_path,
                    rc_dir,
                    project_name=PROJECT_NAME,
                    project_data_dir=PROJECT_DATA_DIR,
                    method_data_dir=METHOD_DATA_DIR,
                    debug_log=_debug_log,
                    log=_log,
                    known_dataset_type_keys=known_dataset_type_keys,
                    max_average_formula_probe=MAX_AVERAGE_FORMULA_PROBE,
                    preserve_local_owned_state=preserve_local_dfm_owned_state,
                    strict=strict_extraction,
                    verbose=verbose,
                )
                if skipped:
                    _record_skipped(progress_state)
                    progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                    _report_progress(
                        progress_callback,
                        event="finish",
                        kind="vector",
                        name=output_dataset_name or vector_name,
                        dataset_name=output_dataset_name or vector_name,
                        method_name=dfm_name,
                        completed=int(progress_state.get("completed") or 0),
                        total=int(progress_state.get("total") or len(vector_names)),
                        status="skipped",
                        message=detail.strip(),
                    )
                    continue
                if isinstance(method_counts, dict):
                    method_counts["dfms_written"] = int(method_counts.get("dfms_written") or 0) + 1
                written += 1
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind="vector",
                    name=output_dataset_name or vector_name,
                    dataset_name=output_dataset_name or vector_name,
                    method_name=dfm_name,
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(vector_names)),
                    status="success",
                    message=detail.strip(),
                )
                continue
            if method_type == METHOD_TYPE_DFM_CODE and include_dfm_methods:
                _log(verbose, f"    WARN DFM method not found for vector {vector_name}; exporting vector only")

            if strict_extraction:
                dataset_type_obj = getattr(vector, "DatasetType")
                dataset_type = _normalize_import_name(getattr(dataset_type_obj, "Name")) or vector_name
            else:
                dataset_type_obj = _safe_attr(vector, "DatasetType", None)
                dataset_type = _normalize_import_name(_safe_attr(dataset_type_obj, "Name", "")) or vector_name
            if not _is_known_dataset_type(dataset_type, known_dataset_type_keys):
                detail = _unknown_dataset_type_skip_detail("vector", vector_name, dataset_type)
                _log(verbose, detail)
                _record_skipped(progress_state)
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind="vector",
                    name=vector_name,
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(vector_names)),
                    status="skipped",
                    message=detail.strip(),
                )
                continue
            if method_type == METHOD_TYPE_BOOTSTRAP_CODE and include_bootstrap_methods:
                bootstrap = _find_bootstrap_for_vector(reserving_class, vector_name)
                if bootstrap is None:
                    _log(verbose, f"    WARN Bootstrap method not found for vector {vector_name}; exporting vector only")
                else:
                    bootstrap_tasks.append((vector_name, bootstrap))
                    continue
            if method_type == METHOD_TYPE_STOCHASTIC_CONSOLIDATION_CODE and include_stochastic_consolidations:
                consolidation = _find_stochastic_consolidation_for_vector(reserving_class, vector_name)
                if consolidation is None:
                    _log(
                        verbose,
                        f"    WARN Stochastic Consolidation not found for vector {vector_name}; exporting vector only",
                    )
                else:
                    scon_tasks.append((vector_name, consolidation))
                    continue
            bf_payload = None
            if method_type == METHOD_TYPE_BF_CODE and include_bf_methods:
                bf_method = _find_bornhuetter_ferguson_for_vector(reserving_class, vector_name)
                if bf_method is None:
                    _log(verbose, f"    WARN Bornhuetter Ferguson method not found for vector {vector_name}; exporting vector only")
                else:
                    bf_payload = export_bornhuetter_ferguson(
                        bf_method,
                        strict=strict_extraction,
                    )
            cc_payload = None
            if method_type == METHOD_TYPE_CAPE_COD_CODE and include_cc_methods:
                cc_method = _find_cape_cod_for_vector(reserving_class, vector_name)
                if cc_method is None:
                    _log(verbose, f"    WARN Cape Cod method not found for vector {vector_name}; exporting vector only")
                else:
                    cc_payload = export_cape_cod(
                        cc_method,
                        strict=strict_extraction,
                    )
            result_selection_payload = None
            if method_type == METHOD_TYPE_RESULT_SELECTION_CODE:
                result_selection = _find_result_selection_for_vector(reserving_class, vector_name)
                if result_selection is None:
                    _log(verbose, f"    WARN result selection method not found for vector {vector_name}; exporting vector only")
                else:
                    result_selection_payload = export_result_selection(
                        result_selection,
                        strict=strict_extraction,
                    )
            if (
                not result_selection_payload
                and not bf_payload
                and not cc_payload
                and _is_engine_generated_instance({
                    "name": vector_name,
                    "dataset_type": dataset_type,
                })
            ):
                engine_payload = _engine_generated_metadata_payload(
                    vector,
                    name=vector_name,
                    dataset_type=dataset_type,
                    is_vector=True,
                    strict=strict_extraction,
                )
                engine_tasks.append(
                    _create_engine_generated_task(
                        engine_payload,
                        rc_path,
                        rc_dir,
                        is_vector=True,
                        resq_item=vector,
                    )
                )
                continue
            payload = export_vector(
                vector,
                strict=strict_extraction,
                # A hand-entered vector is copied at the period ResQ stores it
                # at; a method output or a calculated vector keeps the period
                # ResQ displayed, since its method or formula owns its shape.
                at_stored_shape=(
                    not result_selection_payload
                    and not bf_payload
                    and not cc_payload
                    and not _is_calculated_dataset_type(dataset_type)
                ),
            )
            if not _is_known_dataset_type(payload.get("dataset_type"), known_dataset_type_keys):
                detail = _unknown_dataset_type_skip_detail("vector", payload.get("name") or vector_name, payload.get("dataset_type"))
                _log(verbose, detail)
                _record_skipped(progress_state)
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
                _report_progress(
                    progress_callback,
                    event="finish",
                    kind="vector",
                    name=payload.get("name") or vector_name,
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or len(vector_names)),
                    status="skipped",
                    message=detail.strip(),
                )
                continue
            if result_selection_payload:
                _apply_result_selection_vector_metadata(payload, result_selection_payload)
            if bf_payload:
                _apply_bornhuetter_ferguson_vector_metadata(payload, bf_payload)
            if cc_payload:
                _apply_cape_cod_vector_metadata(payload, cc_payload)
            write_vector_export(
                payload,
                rc_path,
                rc_dir,
                bf_method_payload=bf_payload,
                cc_method_payload=cc_payload,
                known_instance_names=vector_names,
            )
            detail = (
                f"    OK  {_method_type_name(method_type)} vector "
                f"{_vector_cache_csv_file_name(payload['name'], payload.get('stored_period_length') or payload['origin_length'])}"
            )
            _log(verbose, detail)
            if result_selection_payload:
                method_path = write_result_selection_export(result_selection_payload, rc_path, rc_dir)
                _log(verbose, f"    OK  {method_path.name}")
                if isinstance(method_counts, dict):
                    method_counts["result_selections_written"] = int(
                        method_counts.get("result_selections_written") or 0
                    ) + 1
            if bf_payload:
                method_path = write_bornhuetter_ferguson_export(bf_payload, rc_path, rc_dir)
                _log(verbose, f"    OK  {method_path.name}")
                if isinstance(method_counts, dict):
                    method_counts["bfs_written"] = int(method_counts.get("bfs_written") or 0) + 1
            if cc_payload:
                method_path = write_cape_cod_export(cc_payload, rc_path, rc_dir)
                _log(verbose, f"    OK  {method_path.name}")
                if isinstance(method_counts, dict):
                    method_counts["ccs_written"] = int(method_counts.get("ccs_written") or 0) + 1
            written += 1
            progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="finish",
                kind="vector",
                name=payload.get("name") or vector_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or len(vector_names)),
                status="success",
                message=detail.strip(),
            )
        except Exception as exc:
            detail = f"    ERR vector {vector_name}: {exc}"
            _log(verbose, detail)
            if verbose:
                traceback.print_exc(file=sys.stdout)
            _record_error_detail(progress_state, kind="vector", name=vector_name, detail=str(exc))
            errors += 1
            progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="finish",
                kind="vector",
                name=vector_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or len(vector_names)),
                status="error",
                message=detail.strip(),
            )
    if bootstrap_tasks:
        bootstrap_written, bootstrap_errors = _export_bootstrap_tasks(
            bootstrap_tasks,
            rc_path,
            rc_dir,
            progress_callback=progress_callback,
            progress_state=progress_state,
            method_counts=method_counts,
            strict_extraction=strict_extraction,
            verbose=verbose,
        )
        written += bootstrap_written
        errors += bootstrap_errors
    if scon_tasks:
        scon_written, scon_errors = _export_stochastic_consolidation_tasks(
            scon_tasks,
            rc_path,
            rc_dir,
            progress_callback=progress_callback,
            progress_state=progress_state,
            method_counts=method_counts,
            strict_extraction=strict_extraction,
            verbose=verbose,
        )
        written += scon_written
        errors += scon_errors
    if engine_tasks and not engine_available:
        _skip_engine_generated_tasks(
            engine_tasks,
            progress_callback=progress_callback,
            progress_state=progress_state,
            reason="no active Arco Engine worker was available",
            verbose=verbose,
        )
    elif engine_tasks:
        resolved_provenance = engine_provenance or get_engine_processing_provenance(PROJECT_NAME)
        engine_written, engine_errors = _complete_engine_generated_tasks(
            engine_tasks,
            provenance=resolved_provenance,
            progress_callback=progress_callback,
            progress_state=progress_state,
            verbose=verbose,
        )
        written += engine_written
        errors += engine_errors
    return written, errors


# Main

def export_dfms_for_rc(
    reserving_class,
    rc_path: str,
    rc_dir: Path,
    *,
    progress_callback: ProgressCallback | None = None,
    progress_state: dict | None = None,
    dfm_names: list[str] | None = None,
    verbose: bool = True,
) -> tuple[int, int]:
    """Export DFM method JSON/metadata for one reserving class. Returns (written, errors)."""
    dfm_collection = reserving_class.DFMMethods()
    dfm_names = list(dfm_names) if dfm_names is not None else _dfm_export_names(reserving_class)

    _log(verbose, f"DFMs: {len(dfm_names)}")
    written = errors = 0
    progress_state = progress_state if isinstance(progress_state, dict) else {"completed": 0, "total": len(dfm_names)}
    methods_increment_progress = progress_state.get("count_methods", True) is not False
    known_dataset_type_keys = _dataset_type_keys()
    for dfm_name in dfm_names:
        output_dataset_name = ""
        try:
            dfm = dfm_collection.Item(dfm_name)
            output_dataset_name, detail, skipped = _export_dfm_output_dataset(
                dfm,
                rc_path,
                rc_dir,
                project_name=PROJECT_NAME,
                project_data_dir=PROJECT_DATA_DIR,
                method_data_dir=METHOD_DATA_DIR,
                debug_log=_debug_log,
                log=_log,
                known_dataset_type_keys=known_dataset_type_keys,
                max_average_formula_probe=MAX_AVERAGE_FORMULA_PROBE,
                verbose=verbose,
            )
            if methods_increment_progress:
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="method",
                kind="dfm",
                name=output_dataset_name or dfm_name,
                dataset_name=output_dataset_name or dfm_name,
                method_name=dfm_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or 0),
                status="skipped" if skipped else "success",
                message=detail.strip(),
            )
            if skipped:
                _record_skipped(progress_state)
                continue
            written += 1
        except Exception as exc:
            detail = f"    ERR {dfm_name}: {exc}"
            _log(verbose, detail)
            if verbose:
                traceback.print_exc(file=sys.stdout)
            _record_error_detail(progress_state, kind="dfm", name=dfm_name, detail=str(exc))
            if methods_increment_progress:
                progress_state["completed"] = int(progress_state.get("completed") or 0) + 1
            _report_progress(
                progress_callback,
                event="method",
                kind="dfm",
                name=output_dataset_name or dfm_name,
                dataset_name=output_dataset_name or dfm_name,
                method_name=dfm_name,
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or 0),
                status="error",
                message=detail.strip(),
            )
            errors += 1

    return written, errors


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export ResQ triangles, vectors, Result Selections, Bornhuetter Ferguson methods, Cape Cod methods, and/or DFM methods to Arco dataset files.")
    parser.add_argument(
        "--export",
        choices=("configured", "all", "triangles", "vectors", "vector", "dfm", "dfms"),
        default="configured",
        help="Export phase to run. 'configured' uses EXPORT_TRIANGLES/EXPORT_VECTORS/EXPORT_DFMS constants.",
    )
    parser.add_argument(
        "--cleanup-target",
        dest="cleanup_target",
        action="store_true",
        default=CLEAN_TARGET_RC,
        help="Clean the target reserving-class data folder before export. Enabled by default.",
    )
    parser.add_argument(
        "--no-cleanup-target",
        dest="cleanup_target",
        action="store_false",
        help="Preserve existing files in the target reserving-class data folder before export.",
    )
    return parser.parse_args(argv)


def _selected_exports(export_mode: str) -> tuple[bool, bool, bool]:
    if export_mode == "all":
        return True, True, True
    if export_mode == "triangles":
        return True, False, False
    if export_mode in {"vector", "vectors"}:
        return False, True, False
    if export_mode in {"dfm", "dfms"}:
        return False, False, True
    return bool(EXPORT_TRIANGLES), bool(EXPORT_VECTORS), bool(EXPORT_DFMS)


def _apply_runtime_scope(
    project_name: str,
    server_root: str | Path | None = None,
    project_data_dir: str | Path | None = None,
) -> tuple[Path, str, Path]:
    global SERVER_ROOT, PROJECT_NAME, PROJECT_DATA_DIR

    previous = (SERVER_ROOT, PROJECT_NAME, PROJECT_DATA_DIR)
    clean_project_name = str(project_name or "").strip()
    if not clean_project_name:
        raise ValueError("project_name is required.")
    if server_root is not None:
        SERVER_ROOT = Path(server_root).expanduser().resolve()
    PROJECT_NAME = clean_project_name
    PROJECT_DATA_DIR = (
        Path(project_data_dir).expanduser().resolve()
        if project_data_dir is not None
        else SERVER_ROOT / "projects" / PROJECT_NAME / "data"
    )
    _configure_migration_modules()
    return previous


def _restore_runtime_scope(previous: tuple[Path, str, Path]) -> None:
    global SERVER_ROOT, PROJECT_NAME, PROJECT_DATA_DIR

    SERVER_ROOT, PROJECT_NAME, PROJECT_DATA_DIR = previous
    _configure_migration_modules()


def _imported_dataset_changed(previous_rc_dir: Path | None, rc_dir: Path, name: str) -> bool:
    """Whether an imported dataset's file differs from the class's copy before the import.

    An Engine rebuild of unchanged source data writes the same CSV again, and a
    dataset the import skipped still holds the copy the merge carried over, so
    neither is a change its dependents need to hear about.
    """
    sidecar_name = _json_sidecar_name(name)
    meta = _safe_read_json(rc_dir / DATASET_SIDECAR_DIR / sidecar_name)
    if not meta:
        return False
    if previous_rc_dir is None:
        return True
    previous_meta = _safe_read_json(previous_rc_dir / DATASET_SIDECAR_DIR / sidecar_name)
    csv_name = str(meta.get("csv_file") or "")
    if not csv_name or csv_name != str(previous_meta.get("csv_file") or ""):
        return True
    try:
        return (rc_dir / DATASET_CACHE_DIR / csv_name).read_bytes() != (
            previous_rc_dir / DATASET_CACHE_DIR / csv_name
        ).read_bytes()
    except OSError:
        return True


def refresh_import_dependents(
    previous_rc_dir: Path | None,
    rc_dir: Path,
    rc_path: str,
    imported_names: list[str],
) -> DfmPropagationResult:
    """Refresh what depends on the datasets an import actually changed.

    ``rc_dir`` is the folder the import wrote -- the Bridge's staged class once
    the untouched live groups are merged into it -- and ``previous_rc_dir``
    holds the class as it was before, or is None when there is no copy to
    compare against. The walk runs in ``rc_dir``, so it recalculates the
    dependents against the new inputs before anything is committed. What the
    import itself wrote came from ResQ and is left as ResQ gave it.
    """

    names: list[str] = []
    seen: set[str] = set()
    for raw_name in imported_names:
        name = _normalize_import_name(raw_name)
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    changed = [name for name in names if _imported_dataset_changed(previous_rc_dir, Path(rc_dir), name)]
    if not changed:
        return DfmPropagationResult()
    try:
        # The walk must work in the folder the import wrote, whatever its
        # location or folder-name encoding.
        project = ArcRhoClient(SERVER_ROOT).project(PROJECT_NAME)
        project.data_dir = Path(rc_dir).parent
        project.reserving_class_data_dir = lambda _reserving_class: Path(rc_dir)
        reserving_class = project.reserving_class(rc_path)
        return refresh_dfm_dependents_for_sources(reserving_class, changed, settled=names)
    except Exception as exc:
        return DfmPropagationResult((), (f"DFM propagation could not start: {exc}",))


def record_import_selection(
    project_name: str,
    rc_path: str,
    *,
    server_root,
    names,
    connection_name: str = CONNECTION_NAME,
    requested_by: str = "",
) -> str:
    """Remember what a committed import covered, as the next import's default.

    The document is the one the Export macro writes its own direction into, so
    both macros open their review table from the same saved answer.
    """

    return str(
        save_transfer_selection(
            server_root,
            project_name,
            rc_path,
            connection_name,
            DIRECTION_IMPORT,
            names,
            updated_by=requested_by,
        )
    )


def import_reserving_class_from_resq(
    project_name: str,
    rc_path: str,
    *,
    requested_by: str = "",
    **options,
) -> dict:
    """Import one ResQ reserving class into ArcRho using caller-provided UI context.

    ``requested_by`` is the Windows login of the person who asked for the
    import. The Bridge takes it from the request so a generated dataset is
    stamped with their configured full name rather than the account the
    claiming worker runs under; an empty login keeps the process identity.
    """

    with import_user_identity_service().acting_identity(requested_by):
        return _import_reserving_class_as_acting_user(project_name, rc_path, **options)


def _import_reserving_class_as_acting_user(
    project_name: str,
    rc_path: str,
    *,
    server_root: str | Path | None = None,
    project_data_dir: str | Path | None = None,
    export_mode: str = "configured",
    selected_names: list[str] | None = None,
    cleanup_target: bool | None = None,
    skip_unavailable_engine: bool = False,
    connection_name: str = CONNECTION_NAME,
    user_name: str = USER_NAME,
    password: str = PASSWORD,
    progress_callback: ProgressCallback | None = None,
    verbose: bool = True,
) -> dict:
    previous_scope = _apply_runtime_scope(project_name, server_root, project_data_dir)
    rc_dir: Path | None = None
    rc_mutation_started = False
    index_rebuilt = False
    try:
        rc_path = str(rc_path or "").strip()
        if not rc_path:
            raise ValueError("rc_path is required.")
        run_triangles, run_vectors, run_dfms = _selected_exports(str(export_mode or "configured"))
        should_cleanup = CLEAN_TARGET_RC if cleanup_target is None else bool(cleanup_target)
        worker_instances = (
            discover_fresh_engine_heartbeats(SERVER_ROOT)
            if skip_unavailable_engine
            else require_running_engine_instances(SERVER_ROOT)
        )
        engine_available = bool(worker_instances)
        engine_provenance = None
        engine_preflight_error = ""
        if engine_available:
            try:
                engine_provenance = get_engine_processing_provenance(PROJECT_NAME)
            except EngineGenerationError as exc:
                if not skip_unavailable_engine:
                    raise
                # The Bridge transaction can safely retain the previous engine
                # component, but it must never write generated values without
                # the app's authoritative provenance contract.
                engine_available = False
                engine_preflight_error = str(exc)
        _report_progress(
            progress_callback,
            event="activity",
            kind="engine_preflight",
            workers=len(worker_instances),
            status="success" if engine_available else "warning",
            message=(
                f"{len(worker_instances)} data-engine worker(s) available"
                if engine_available
                else (
                    "Arco Engine processing provenance is unavailable; "
                    "generated datasets will be skipped."
                    if engine_preflight_error
                    else "No Arco Engine worker is available; generated datasets will be skipped."
                )
            ),
        )
        try:
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("pywin32 is required: pip install pywin32") from exc

        _report_progress(
            progress_callback,
            event="connect",
            completed=0,
            total=0,
            message=f"Connecting to ResQ: {connection_name}",
        )
        _log(verbose, f"Connecting to ResQ: {connection_name}")
        ResQApp = win32com.client.Dispatch("ResQ3Automation.ResQApplication")
        try:
            ResQApp.ConnectByName(connection_name, user_name, password)
        except Exception as exc:
            raise RuntimeError(f"Could not connect to ResQ COM API ({connection_name}): {exc}") from exc
        _report_progress(progress_callback, event="connect", completed=0, total=0, message="Connected to ResQ.")
        _log(verbose, "Connected.\n")

        counts = {
            "triangles_written": 0,
            "vectors_written": 0,
            "dfms_written": 0,
            "bfs_written": 0,
            "ccs_written": 0,
            "bootstraps_written": 0,
            "scons_written": 0,
            "bssr_written": 0,
            "bscra_written": 0,
            "engine_skipped": 0,
            "engine_errors": 1 if engine_preflight_error else 0,
            "errors": 1 if engine_preflight_error else 0,
        }

        try:
            project = ResQApp.Projects().Item(PROJECT_NAME)
            _log(verbose, f"Project: {PROJECT_NAME}")
            PROJECT_DATA_DIR.mkdir(parents=True, exist_ok=True)

            rc_folder = _encode_rc_folder(rc_path)
            rc_dir = PROJECT_DATA_DIR / rc_folder

            reserving_class = project.ReservingClasses().Item(rc_path)
            dataset_counts = resq_export_dataset_counts(
                reserving_class,
                run_triangles=run_triangles,
                run_vectors=run_vectors,
                run_dfms=run_dfms,
                progress_callback=progress_callback,
            )
            dataset_counts = _select_export_inventory(dataset_counts, selected_names, reserving_class)
            method_only_progress = bool(run_dfms and not run_triangles and not run_vectors)
            progress_total = int(dataset_counts.get("dfms") or 0) if method_only_progress else int(dataset_counts.get("total") or 0)
            progress_state = {
                "completed": 0,
                "total": progress_total,
                "count_methods": method_only_progress,
                "skipped": 0,
                "engine_skipped": 0,
                "engine_errors": 1 if engine_preflight_error else 0,
            }
            if engine_preflight_error:
                _record_error_detail(
                    progress_state,
                    kind="engine_preflight",
                    name=PROJECT_NAME,
                    detail=engine_preflight_error,
                )
            total_message = (
                f"Found {progress_state['total']} DFM method(s)."
                if method_only_progress
                else (
                    f"Found {progress_state['total']} dataset(s) "
                    f"({dataset_counts.get('triangles', 0)} triangle(s), "
                    f"{dataset_counts.get('vectors', 0)} vector(s))."
                )
            )
            _report_progress(
                progress_callback,
                event="total",
                completed=0,
                total=progress_state["total"],
                triangles=dataset_counts.get("triangles", 0),
                vectors=dataset_counts.get("vectors", 0),
                dfms=dataset_counts.get("dfms", 0),
                methods=dataset_counts.get("methods", 0),
                message=total_message,
            )
            _log(verbose, f"RC: {rc_path}")
            _log(verbose, f"Export mode: {export_mode} (triangles={run_triangles}, vectors={run_vectors}, dfm={run_dfms})")
            rc_mutation_started = True
            if should_cleanup:
                cleaned_files, cleaned_dirs = cleanup_target_reserving_class_dir(rc_dir)
                _log(verbose, f"    OK  cleaned target RC folder ({cleaned_files} files, {cleaned_dirs} folders)")
            else:
                _log(verbose, "    SKIP target RC folder cleanup")
            rc_dir.mkdir(parents=True, exist_ok=True)
            (rc_dir / DATASET_CACHE_DIR).mkdir(parents=True, exist_ok=True)
            (rc_dir / METHOD_DATA_DIR).mkdir(parents=True, exist_ok=True)
            (rc_dir / DATASET_SIDECAR_DIR).mkdir(parents=True, exist_ok=True)

            rc_written = 0

            with defer_sidecar_graph_enrichment(), resq_class_scope(
                engine_builds=engine_knows_reserving_class(rc_path)
            ):
                if run_triangles:
                    written, errors = export_triangles_for_rc(
                        reserving_class,
                        rc_path,
                        rc_dir,
                        progress_callback=progress_callback,
                        progress_state=progress_state,
                        triangle_names=dataset_counts.get("triangle_names") if isinstance(dataset_counts.get("triangle_names"), list) else None,
                        triangle_items=dataset_counts.get("triangle_items") if isinstance(dataset_counts.get("triangle_items"), dict) else None,
                        triangle_method_types=dataset_counts.get("triangle_method_types") if isinstance(dataset_counts.get("triangle_method_types"), dict) else None,
                        method_counts=counts,
                        engine_provenance=engine_provenance,
                        engine_available=engine_available,
                        verbose=verbose,
                    )
                    rc_written += written
                    counts["triangles_written"] += written
                    counts["errors"] += errors

                if run_vectors:
                    written, errors = export_vectors_for_rc(
                        reserving_class,
                        rc_path,
                        rc_dir,
                        progress_callback=progress_callback,
                        progress_state=progress_state,
                        vector_names=dataset_counts.get("vector_names") if isinstance(dataset_counts.get("vector_names"), list) else None,
                        include_dfm_methods=run_dfms,
                        include_bf_methods=run_dfms,
                        include_cc_methods=run_dfms,
                        include_bootstrap_methods=run_dfms,
                        include_stochastic_consolidations=run_dfms,
                        dfm_names=dataset_counts.get("dfm_names") if isinstance(dataset_counts.get("dfm_names"), list) else None,
                        method_counts=counts,
                        engine_provenance=engine_provenance,
                        engine_available=engine_available,
                        verbose=verbose,
                    )
                    rc_written += written
                    counts["vectors_written"] += written
                    counts["errors"] += errors

                if run_dfms and not run_vectors:
                    written, errors = export_dfms_for_rc(
                        reserving_class,
                        rc_path,
                        rc_dir,
                        progress_callback=progress_callback,
                        progress_state=progress_state,
                        dfm_names=dataset_counts.get("dfm_names") if isinstance(dataset_counts.get("dfm_names"), list) else None,
                        verbose=verbose,
                    )
                    rc_written += written
                    counts["dfms_written"] += written
                    counts["errors"] += errors

            counts["engine_skipped"] = int(progress_state.get("engine_skipped") or 0)
            counts["engine_errors"] = int(progress_state.get("engine_errors") or 0)

            _report_progress(
                progress_callback,
                event="finalize",
                kind="sidecar_graph",
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or 0),
                message="Finalizing imported dataset metadata...",
            )
            if rc_written:
                _report_progress(
                    progress_callback,
                    event="finalize",
                    kind="sidecar_graph",
                    completed=int(progress_state.get("completed") or 0),
                    total=int(progress_state.get("total") or 0),
                    message="Refreshing dataset dependency metadata...",
                )
                refreshed = refresh_sidecar_graphs_for_rc(rc_dir)
                if refreshed:
                    _log(verbose, f"    OK  refreshed sidecar graph metadata ({refreshed} files)")
            # The caller walks their dependents once the import is merged with
            # the class it replaces; see refresh_import_dependents.
            imported_dataset_names: list[str] = []
            if rc_written:
                if run_triangles and isinstance(dataset_counts.get("triangle_names"), list):
                    imported_dataset_names.extend(dataset_counts["triangle_names"])
                if run_vectors and isinstance(dataset_counts.get("vector_names"), list):
                    imported_dataset_names.extend(dataset_counts["vector_names"])
            _report_progress(
                progress_callback,
                event="finalize",
                kind="dataset_index",
                completed=int(progress_state.get("completed") or 0),
                total=int(progress_state.get("total") or 0),
                message="Rebuilding the reserving-class dataset index...",
            )
            rebuild_dataset_instance_index(PROJECT_NAME, rc_path, rc_dir)
            index_rebuilt = True

            datasets_written = counts["triangles_written"] + counts["vectors_written"]
            total_written = (
                datasets_written
                + counts["dfms_written"]
                + counts.get("bfs_written", 0)
                + counts.get("ccs_written", 0)
                + counts.get("bootstraps_written", 0)
                + counts.get("scons_written", 0)
                + counts.get("bssr_written", 0)
                + counts.get("bscra_written", 0)
            )
            skipped = int(progress_state.get("skipped") or 0)
            result = {
                "project_name": PROJECT_NAME,
                "reserving_class": rc_path,
                "rc_dir": str(rc_dir),
                "engine_workers": len(worker_instances),
                "engine_available": engine_available,
                "engine_skipped": int(progress_state.get("engine_skipped") or 0),
                "engine_errors": int(progress_state.get("engine_errors") or 0),
                "engine_parity_mismatches": int(progress_state.get("engine_parity_mismatches") or 0),
                "engine_parity_warnings": progress_state.get("engine_parity_warnings", []),
                "datasets_imported": datasets_written,
                "total_written": total_written,
                "skipped": skipped,
                "datasets_total": progress_state["total"],
                "triangles_total": dataset_counts.get("triangles", 0),
                "vectors_total": dataset_counts.get("vectors", 0),
                "dfms_total": dataset_counts.get("dfms", 0),
                "bfs_total": dataset_counts.get("bfs", 0),
                "ccs_total": dataset_counts.get("ccs", 0),
                "bootstraps_total": dataset_counts.get("bootstraps", 0),
                "stochastic_consolidations_total": dataset_counts.get("stochastic_consolidations", 0),
                "bssrs_total": dataset_counts.get("bssrs", 0),
                "bscras_total": dataset_counts.get("bscras", 0),
                "methods_total": dataset_counts.get("methods", 0),
                "grand_total": progress_state["total"],
                "selected_names": None if selected_names is None else list(selected_names),
                "imported_dataset_names": imported_dataset_names,
                "error_details": progress_state.get("error_details", []),
                "consolidation_warnings": progress_state.get("consolidation_warnings", []),
                **counts,
            }
            _report_progress(
                progress_callback,
                event="complete",
                completed=progress_state["completed"],
                total=progress_state["total"],
                status="error" if counts["errors"] else "success",
                message=f"Finished - written: {total_written}, skipped: {skipped}, errors: {counts['errors']}",
            )
            _log(verbose, f"\nFinished - written: {total_written}, skipped: {skipped}, errors: {counts['errors']}")
            return result
        finally:
            active_error = sys.exc_info()[1]
            if rc_mutation_started and not index_rebuilt and rc_dir is not None:
                try:
                    rebuild_dataset_instance_index(PROJECT_NAME, rc_path, rc_dir)
                except Exception as rebuild_error:
                    if active_error is None:
                        raise
                    _log(
                        verbose,
                        "    WARN failed to rebuild index after interrupted import: "
                        f"{rebuild_error}",
                    )
            try:
                ResQApp.Disconnect()
            except Exception:
                pass
    finally:
        _restore_runtime_scope(previous_scope)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    run_triangles, run_vectors, run_dfms = _selected_exports(args.export)
    worker_instances = require_running_engine_instances(SERVER_ROOT)
    engine_provenance = get_engine_processing_provenance(PROJECT_NAME)
    print(f"Data-engine workers: {len(worker_instances)}")
    try:
        import win32com.client
    except ImportError:
        sys.exit("pywin32 is required: pip install pywin32")

    print(f"Connecting to ResQ: {CONNECTION_NAME}")
    ResQApp = win32com.client.Dispatch("ResQ3Automation.ResQApplication")
    ResQApp.ConnectByName(CONNECTION_NAME, USER_NAME, PASSWORD)
    print("Connected.\n")

    total_written = total_errors = 0
    active_index_context: tuple[str, Path] | None = None
    pending_snapshots: list[tuple[tempfile.TemporaryDirectory, Path, Path]] = []

    try:
        project = ResQApp.Projects().Item(PROJECT_NAME)
        print(f"Project: {PROJECT_NAME}")
        PROJECT_DATA_DIR.mkdir(parents=True, exist_ok=True)

        rc_paths = _configured_rc_paths(RC_PATH)
        if not rc_paths:
            sys.exit("No reserving-class paths configured in RC_PATH.")
        print(f"Reserving classes: {len(rc_paths)}")

        for rc_index, rc_path in enumerate(rc_paths, start=1):
            rc_folder = _encode_rc_folder(rc_path)
            rc_dir = PROJECT_DATA_DIR / rc_folder

            reserving_class = project.ReservingClasses().Item(rc_path)
            migrated_precedent_names: list[str] = []
            if run_triangles:
                migrated_precedent_names.extend(_triangle_export_names(reserving_class))
            if run_vectors:
                migrated_precedent_names.extend(_vector_export_names(reserving_class))
            print(f"\nRC {rc_index}/{len(rc_paths)}: {rc_path}")
            print(f"Export mode: {args.export} (triangles={run_triangles}, vectors={run_vectors}, dfm={run_dfms})")
            active_index_context = (rc_path, rc_dir)
            snapshot_entry = None
            if args.cleanup_target:
                runtime_root = SERVER_ROOT / "r"
                runtime_root.mkdir(parents=True, exist_ok=True)
                snapshot_temp = tempfile.TemporaryDirectory(
                    prefix="direct-resq-",
                    dir=str(runtime_root),
                )
                snapshot_rc_dir = Path(snapshot_temp.name) / rc_folder
                snapshot_entry = (snapshot_temp, snapshot_rc_dir, rc_dir)
                pending_snapshots.append(snapshot_entry)
                snapshot_reserving_class_artifacts(rc_dir, snapshot_rc_dir)
                cleaned_files, cleaned_dirs = cleanup_target_reserving_class_dir(rc_dir)
                print(f"    OK  cleaned target RC folder ({cleaned_files} files, {cleaned_dirs} folders)")
            else:
                print("    SKIP target RC folder cleanup (--no-cleanup-target)")
            rc_dir.mkdir(parents=True, exist_ok=True)
            (rc_dir / DATASET_CACHE_DIR).mkdir(parents=True, exist_ok=True)
            (rc_dir / METHOD_DATA_DIR).mkdir(parents=True, exist_ok=True)
            (rc_dir / DATASET_SIDECAR_DIR).mkdir(parents=True, exist_ok=True)

            rc_written = 0
            method_counts = {
                "dfms_written": 0,
                "bfs_written": 0,
                "ccs_written": 0,
                "bootstraps_written": 0,
                "scons_written": 0,
                "bssr_written": 0,
                "bscra_written": 0,
            }

            with defer_sidecar_graph_enrichment(), resq_class_scope(
                engine_builds=engine_knows_reserving_class(rc_path)
            ):
                if run_triangles:
                    written, errors = export_triangles_for_rc(
                        reserving_class,
                        rc_path,
                        rc_dir,
                        method_counts=method_counts,
                        engine_provenance=engine_provenance,
                    )
                    rc_written += written
                    total_written += (
                        written
                        + int(method_counts.get("bssr_written") or 0)
                        + int(method_counts.get("bscra_written") or 0)
                    )
                    total_errors += errors

                if run_vectors:
                    written, errors = export_vectors_for_rc(
                        reserving_class,
                        rc_path,
                        rc_dir,
                        include_dfm_methods=run_dfms,
                        include_bf_methods=run_dfms,
                        include_cc_methods=run_dfms,
                        include_bootstrap_methods=run_dfms,
                        include_stochastic_consolidations=run_dfms,
                        method_counts=method_counts,
                        engine_provenance=engine_provenance,
                    )
                    rc_written += written
                    total_written += (
                        written
                        + int(method_counts.get("dfms_written") or 0)
                        + int(method_counts.get("bfs_written") or 0)
                        + int(method_counts.get("ccs_written") or 0)
                        + int(method_counts.get("bootstraps_written") or 0)
                        + int(method_counts.get("scons_written") or 0)
                    )
                    total_errors += errors

                if run_dfms and not run_vectors:
                    written, errors = export_dfms_for_rc(reserving_class, rc_path, rc_dir)
                    rc_written += written
                    total_written += written
                    total_errors += errors

            snapshot_rc_dir = None
            if snapshot_entry is not None:
                _snapshot_temp, snapshot_rc_dir, _live_rc_dir = snapshot_entry
                merge_result = merge_preserved_arcrho_artifacts(snapshot_rc_dir, rc_dir)
                if merge_result["groups"]:
                    print(
                        "    OK  retained "
                        f"{merge_result['groups']} Arco-owned or newer dataset/method group(s)"
                    )

            if rc_written:
                refreshed = refresh_sidecar_graphs_for_rc(rc_dir)
                if refreshed:
                    print(f"    OK  refreshed sidecar graph metadata ({refreshed} files)")
            if rc_written and migrated_precedent_names:
                propagation = refresh_import_dependents(
                    snapshot_rc_dir, rc_dir, rc_path, migrated_precedent_names
                )
                for warning in propagation.warnings:
                    print(f"    WARN {warning}")
            if snapshot_entry is not None:
                snapshot_entry[0].cleanup()
                pending_snapshots.remove(snapshot_entry)
            rebuild_dataset_instance_index(PROJECT_NAME, rc_path, rc_dir)
            active_index_context = None

    finally:
        active_error = sys.exc_info()[1]
        try:
            for snapshot_temp, snapshot_rc_dir, live_rc_dir in pending_snapshots:
                try:
                    try:
                        merge_preserved_arcrho_artifacts(snapshot_rc_dir, live_rc_dir)
                    except Exception as merge_error:
                        if active_error is None:
                            raise
                        print(
                            "    WARN failed to restore preserved Arco artifacts "
                            f"after interrupted import: {merge_error}"
                        )
                finally:
                    snapshot_temp.cleanup()
            if active_index_context is not None:
                active_rc_path, active_rc_dir = active_index_context
                try:
                    rebuild_dataset_instance_index(
                        PROJECT_NAME,
                        active_rc_path,
                        active_rc_dir,
                    )
                except Exception as rebuild_error:
                    if active_error is None:
                        raise
                    print(
                        "    WARN failed to rebuild index after interrupted import: "
                        f"{rebuild_error}"
                    )
        finally:
            ResQApp.Disconnect()
            print(f"\nFinished — written: {total_written}, errors: {total_errors}")


if __name__ == "__main__":
    main()
