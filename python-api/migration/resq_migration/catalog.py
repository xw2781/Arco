from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from arcrho_api.bornhuetter_ferguson_contract import (
    BF_METHOD_TYPE,
    BF_SOURCE_KIND,
)
from arcrho_api.bootstrap_contract import (
    BST_METHOD_TYPE,
    BST_SOURCE_KIND,
)
from arcrho_api.cape_cod_contract import (
    CC_METHOD_TYPE,
    CC_SOURCE_KIND,
)
from arcrho_api.dataset_index_contract import (
    build_dataset_index_payload,
    index_update_lock,
    resolve_canonical_index_identity,
    write_index_json_unlocked,
)
from arcrho_api.dataset_link_contract import link_precedent_names
from arcrho_api.stochastic_consolidation_contract import (
    SCON_METHOD_TYPE,
    SCON_SOURCE_KIND,
)
from arcrho_api.dataset_type_contract import (
    dataset_type_formula_graph,
    dataset_type_key,
    dataset_type_keys,
    formula_references,
    is_app_calculated_dataset_type,
    is_generated_formula_dataset_type,
)

from .core import (
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
    METHOD_STATUS_NEEDS_REVIEW,
    METHOD_STATUS_OK,
    _add_cached_dataset_name,
    _bool_value,
    _cached_dataset_names_from_file,
    _clean_name,
    _dataset_sidecar_path_for_cached_csv,
    _has_legacy_length_only_suffix,
    _normalize_cached_dataset_name,
    _normalize_import_name,
    normalize_method_status,
    _safe_read_json,
    _write_sidecar_json,
)
from arcrho_api.sidecar_core_contract import finalize_sidecar
from arcrho_reserving_class_type_contract import reserving_class_path_is_known


SERVER_ROOT = Path(r"E:\ArcRho Server")
PROJECT_NAME = "NJ_Annual_Prod_202605_Fake"
RS_JSON_FORMAT = "arcrho-result-selection-v4"
INDEX_FILE_NAME = DATASET_INDEX_FILE_NAME
INDEX_VERSION = DATASET_INDEX_VERSION
METHOD_DATA_DIR = "methods"


def configure_catalog(
    *,
    server_root: str | Path,
    project_name: str,
    rs_json_format: str,
    method_data_dir: str,
) -> None:
    global SERVER_ROOT, PROJECT_NAME, RS_JSON_FORMAT, METHOD_DATA_DIR

    SERVER_ROOT = Path(server_root)
    PROJECT_NAME = str(project_name)
    RS_JSON_FORMAT = str(rs_json_format)
    METHOD_DATA_DIR = str(method_data_dir)


def _dataset_type_rows() -> list[dict]:
    path = SERVER_ROOT / "projects" / PROJECT_NAME / "dataset_types.json"
    data = _safe_read_json(path)
    rows = data.get("rows") if isinstance(data, dict) else []
    columns = data.get("columns") if isinstance(data, dict) else []
    col_idx: dict[str, int] = {}
    if isinstance(columns, list):
        for idx, column in enumerate(columns):
            text = _clean_name(column)
            if text:
                col_idx[text.casefold()] = idx

    def row_value(row: list, column: str, fallback_idx: int, default: object = "") -> object:
        idx = col_idx.get(column.casefold(), fallback_idx)
        if 0 <= idx < len(row):
            return row[idx]
        return default

    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, list):
            continue
        name = _clean_name(row_value(row, "Name", 0))
        if not name:
            continue
        out.append({
            "name": name,
            "data_format": _clean_name(row_value(row, "Data Format", 1, "Triangle")) or "Triangle",
            "category": _clean_name(row_value(row, "Category", 2)),
            "calculated": _bool_value(row_value(row, "Calculated", 3, False)),
            "formula": _clean_name(row_value(row, "Formula", 4)),
            "source": _clean_name(row_value(row, "Source", 5)),
            "generated": _bool_value(row_value(row, "Generated", 6, False)),
        })
    return out

def _canon_dataset_name(value: object) -> str:
    return re.sub(r"\s+", " ", _clean_name(value)).casefold()

def _formula_components(formula: str, known_names: list[str]) -> list[str]:
    """The type names a formula reads, by the one rule in ``arcrho_api.dataset_type_contract``."""
    return formula_references(formula, known_names)

def _dataset_type_rows_by_key(rows: list[dict]) -> dict[str, dict]:
    return {
        _canon_dataset_name(row.get("name")): row
        for row in rows
        if _canon_dataset_name(row.get("name"))
    }

def _dataset_type_lookup_key(value: object) -> str:
    return _canon_dataset_name(_normalize_cached_dataset_name(value))

def _dataset_type_keys(rows: list[dict] | None = None) -> set[str]:
    dataset_type_rows = _dataset_type_rows() if rows is None else rows
    return {
        _dataset_type_lookup_key(row.get("name"))
        for row in dataset_type_rows
        if _dataset_type_lookup_key(row.get("name"))
    }

def _is_known_dataset_type(dataset_type_name: object, known_keys: set[str] | None = None) -> bool:
    key = _dataset_type_lookup_key(dataset_type_name)
    if not key:
        return False
    return key in (_dataset_type_keys() if known_keys is None else known_keys)

def _dataset_type_row(dataset_type_name: object, rows: list[dict] | None = None) -> dict | None:
    key = _dataset_type_lookup_key(dataset_type_name)
    if not key:
        return None
    for row in (_dataset_type_rows() if rows is None else rows):
        if _dataset_type_lookup_key(row.get("name")) == key:
            return row
    return None

def _is_generated_dataset_type(dataset_type_name: object, rows: list[dict] | None = None) -> bool:
    row = _dataset_type_row(dataset_type_name, rows)
    return bool(row and row.get("generated"))

def _is_calculated_dataset_type(dataset_type_name: object, rows: list[dict] | None = None) -> bool:
    """True when ArcRho's own dataset-types library computes this type from a formula.

    The rule is ``arcrho_api.dataset_type_contract``, the same one the app
    server applies. ResQ's own ``Calculated`` flag or ``Formula`` on a dataset
    is never consulted: when the two libraries disagree, ArcRho's wins, so a
    type ResQ derives (a prior-quarter lookup, say) that ArcRho lists as a
    plain input imports as an editable input. A type ArcRho flags calculated
    whose formula names a type ArcRho does not have imports the same way: its
    values are copied and kept as hand-entered input.
    """
    rows = _dataset_type_rows() if rows is None else rows
    row = _dataset_type_row(dataset_type_name, rows)
    return bool(row) and is_app_calculated_dataset_type(row, dataset_type_keys(rows))

# False while a reserving class the Engine cannot build is imported: one with
# a path level the project's reserving-class types do not define, such as a
# ResQ total class. Every dataset it would generate imports ResQ's values.
_ENGINE_BUILDS_CLASS: ContextVar[bool] = ContextVar("resq_engine_builds_class", default=True)


def engine_knows_reserving_class(rc_path: str) -> bool:
    """True when the project's reserving-class types define every level of *rc_path*.

    Arco's own configuration decides; ResQ's ``Calculated`` flag on the class
    is never consulted.
    """

    project_dir = SERVER_ROOT / "projects" / PROJECT_NAME
    return reserving_class_path_is_known(
        rc_path,
        _safe_read_json(project_dir / "field_mapping.json"),
        _safe_read_json(project_dir / "reserving_class_types.json"),
    )


@contextmanager
def resq_class_scope(*, engine_builds: bool):
    """Import one ResQ reserving class; a class the Engine cannot build keeps ResQ's values.

    Such a class imports as an ordinary Arco class: its datasets arrive as
    values, none is handed to the Engine, and ResQ's cross-class formulas are
    ignored.
    """

    token = _ENGINE_BUILDS_CLASS.set(engine_builds)
    try:
        yield
    finally:
        _ENGINE_BUILDS_CLASS.reset(token)


def engine_builds_class() -> bool:
    """False inside the import of a class the Engine cannot build (see ``resq_class_scope``)."""

    return _ENGINE_BUILDS_CLASS.get()


def _is_engine_generated_instance(payload: dict) -> bool:
    """True for a generated single-instance dataset that the data-engine should build.

    The accepted rule is: the dataset type is flagged ``Generated=true`` and the
    instance name equals its dataset type (matching the app's single-instance
    generated behavior). Method outputs (DFM/RS/BF), manual, and non-generated
    calculated datasets are excluded and continue to import from ResQ, and so
    does every dataset of a class the Engine cannot build.
    """
    if not engine_builds_class():
        return False
    name = _normalize_import_name(payload.get("name"))
    dataset_type = _normalize_import_name(payload.get("dataset_type")) or name
    if not name or _clean_name(name) != _clean_name(dataset_type):
        return False
    return _is_generated_dataset_type(dataset_type)

def _triangle_source_kind(name: object, dataset_type: object) -> str:
    """Decide an imported plain dataset's source kind from ArcRho's dataset types.

    Only a single-instance dataset of a ``Generated`` type is one the Engine
    rebuilds from source data, and only a type ArcRho itself computes is
    calculated. Everything else -- including a ResQ triangle whose name happens
    to match its Dataset Type, such as an adjusted incurred triangle -- is an
    editable input that both sides hold and the transfer review must show.
    """
    if _is_engine_generated_instance({"name": name, "dataset_type": dataset_type}):
        return "engine"
    if _is_calculated_dataset_type(dataset_type):
        return "calculated"
    return "input"

def _is_unreviewed_dataset(name: object, dataset_type: object) -> bool:
    """True for a dataset the transfer review never offers: calculated or engine-generated.

    Both systems rebuild these from their inputs, so the review lists them on
    neither side and nobody can tick them. An import therefore carries them
    whatever was ticked, and the commit treats them as requested; otherwise a
    reserving class imported through the review would never receive them.
    """
    return _is_calculated_dataset_type(dataset_type) or _is_engine_generated_instance(
        {"name": name, "dataset_type": dataset_type}
    )

def _unknown_dataset_type_skip_detail(kind: str, name: object, dataset_type_name: object) -> str:
    display_type = _clean_name(dataset_type_name) or "<blank>"
    return f"    SKIP {kind} {_clean_name(name) or '<unnamed>'}: dataset type {display_type!r} not found in dataset_types.json"

def _generated_formula_rows(rows: list[dict]) -> list[dict]:
    """The rows the Engine builds from a formula over other dataset types.

    The Engine evaluates such a type against the source table, so it is never
    the formula evaluator's to rebuild, but its formula names other types
    exactly as an app-calculated one does. Those names are the links a user
    sees in Details, and the import must write them the way the app does.
    """
    return [row for row in rows if is_generated_formula_dataset_type(row)]

def _is_generated_formula_type(rows: list[dict], dataset_type_name: object) -> bool:
    key = dataset_type_key(dataset_type_name)
    return bool(key) and any(
        dataset_type_key(row.get("name")) == key for row in _generated_formula_rows(rows)
    )

def _direct_precedent_names(rows: list[dict], dataset_type_name: str) -> list[str]:
    known_names = [row["name"] for row in rows]
    known_keys = dataset_type_keys(rows)
    target_key = _canon_dataset_name(dataset_type_name)
    for row in rows:
        if _canon_dataset_name(row.get("name")) != target_key:
            continue
        if is_app_calculated_dataset_type(row, known_keys):
            return _formula_components(_clean_name(row.get("formula")), known_names)
        break
    if not _is_generated_formula_type(rows, dataset_type_name):
        return []
    graph = dataset_type_formula_graph(rows)
    return [
        graph.names.get(key, key)
        for key in graph.precedents.get(dataset_type_key(dataset_type_name), ())
    ]

def _direct_dependent_names(rows: list[dict], dataset_type_name: str) -> list[str]:
    target_key = dataset_type_key(dataset_type_name)
    if not target_key:
        return []
    # Both kinds of formula reader: ArcRho evaluates an app-calculated type and
    # the Engine builds a generated one, and each reads the types its formula
    # names. A calculated type whose formula names a type the table lacks is
    # neither, so it reads nothing.
    known_keys = dataset_type_keys(rows)
    reader_keys = {
        dataset_type_key(row.get("name"))
        for row in rows
        if is_app_calculated_dataset_type(row, known_keys)
    } | {
        dataset_type_key(row.get("name")) for row in _generated_formula_rows(rows)
    }
    graph = dataset_type_formula_graph(rows)
    return [
        graph.names.get(key, key)
        for key in graph.dependents.get(target_key, ())
        if key in reader_keys
    ]


@dataclass
class _PhysicalDatasetInventory:
    available: bool
    items: list[dict]
    items_by_dataset_key: dict[str, list[dict]]
    dependency_info_by_dataset_key: dict[str, dict] = field(default_factory=dict)


def _physical_item_dataset_keys(item: dict) -> set[str]:
    names: set[str] = set()
    _add_cached_dataset_name(names, item.get("dataset_name"))
    _add_cached_dataset_name(names, item.get("dataset_type"))
    for value in item.get("dataset_names") or []:
        _add_cached_dataset_name(names, value)
    return {
        key
        for key in (_canon_dataset_name(name) for name in names)
        if key
    }


def _build_physical_dataset_inventory(rc_dir: Path | None) -> _PhysicalDatasetInventory:
    available = bool(rc_dir is not None and rc_dir.is_dir())
    items = _scan_physical_dataset_files(rc_dir) if available and rc_dir is not None else []
    items_by_dataset_key: dict[str, list[dict]] = {}
    for item in items:
        for key in _physical_item_dataset_keys(item):
            items_by_dataset_key.setdefault(key, []).append(item)
    return _PhysicalDatasetInventory(
        available=available,
        items=items,
        items_by_dataset_key=items_by_dataset_key,
    )


def _rc_existing_dataset_keys(
    rc_dir: Path | None,
    *,
    physical_inventory: _PhysicalDatasetInventory | None = None,
) -> set[str] | None:
    inventory = physical_inventory or _build_physical_dataset_inventory(rc_dir)
    if not inventory.available:
        return None
    return set(inventory.items_by_dataset_key)

def _filter_existing_dependents(names: list[str], existing_dataset_keys: set[str] | None) -> list[str]:
    if existing_dataset_keys is None:
        return names
    return [
        name
        for name in names
        if _canon_dataset_name(name) in existing_dataset_keys
    ]

def _dependency_item_score(item: dict, dataset_key: str) -> tuple[int, float]:
    path = Path(_clean_name(item.get("path")))
    score = 0
    if path.suffix.lower() == ".csv":
        score += 30
    elif _clean_name(item.get("method_type")).lower() == "dfm":
        score += 25
    elif path.parent.name == DATASET_SIDECAR_DIR:
        score += 10
    if _canon_dataset_name(item.get("dataset_name")) == dataset_key:
        score += 4
    if _canon_dataset_name(item.get("dataset_type")) == dataset_key:
        score += 2
    return score, _numeric_timestamp(item.get("last_modified_timestamp") or item.get("mtime"))

def _dependency_entry(
    name: str,
    rows_by_key: dict[str, dict],
    rc_dir: Path | None,
    *,
    include_formula: bool = False,
    physical_inventory: _PhysicalDatasetInventory | None = None,
) -> dict:
    # The persisted graph names a dataset and nothing else: no path, no
    # modification time, no formula copy (``arcrho_api.sidecar_core_contract``).
    return {"dataset_name": name}


def _entry_names(entries: object) -> list[str]:
    """The same-class dataset names a graph list holds.

    An entry that carries a ``reserving_class`` or ``project`` names a dataset
    somewhere else (a Stochastic Consolidation's segment bootstraps), so it is
    never matched against a same-named dataset in this class.
    """
    if not isinstance(entries, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in entries:
        if isinstance(item, dict) and (
            _clean_name(item.get("reserving_class")) or _clean_name(item.get("project"))
        ):
            continue
        name = _clean_name(item.get("dataset_name")) if isinstance(item, dict) else _clean_name(item)
        key = _canon_dataset_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _merge_dependency_entries(existing: object, additions: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in (existing if isinstance(existing, list) else []):
        name = _clean_name(item.get("dataset_name")) if isinstance(item, dict) else _clean_name(item)
        key = _canon_dataset_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"dataset_name": name})
    for item in additions:
        name = _clean_name(item.get("dataset_name"))
        key = _canon_dataset_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"dataset_name": name})
    return out


def _dataset_type_graph_fields(
    dataset_type_name: str,
    rc_dir: Path | None = None,
    *,
    existing_dataset_keys: set[str] | None = None,
    physical_inventory: _PhysicalDatasetInventory | None = None,
    dataset_type_rows: list[dict] | None = None,
) -> dict:
    rows = _dataset_type_rows() if dataset_type_rows is None else dataset_type_rows
    rows_by_key = _dataset_type_rows_by_key(rows)
    inventory = physical_inventory or _build_physical_dataset_inventory(rc_dir)
    rc_dataset_keys = (
        _rc_existing_dataset_keys(rc_dir, physical_inventory=inventory)
        if existing_dataset_keys is None
        else existing_dataset_keys
    )
    precedent_names = _direct_precedent_names(rows, dataset_type_name)
    if _is_generated_formula_type(rows, dataset_type_name):
        # The Engine rebuilds a generated formula from the source table rather
        # than from its inputs' caches, so a type with no instance in this class
        # is simply not a link here. An app-calculated dataset keeps naming a
        # missing input, because for it that is a real problem.
        precedent_names = _filter_existing_dependents(precedent_names, rc_dataset_keys)
    precedents = [
        _dependency_entry(
            name,
            rows_by_key,
            rc_dir,
            physical_inventory=inventory,
        )
        for name in precedent_names
    ]
    dependents = [
        _dependency_entry(
            name,
            rows_by_key,
            rc_dir,
            include_formula=True,
            physical_inventory=inventory,
        )
        for name in _filter_existing_dependents(
            _direct_dependent_names(rows, dataset_type_name),
            rc_dataset_keys,
        )
    ]
    return {"precedents": precedents, "dependents": dependents}


def _apply_sidecar_graph_meta(
    meta: dict,
    dataset_type_name: str,
    rc_dir: Path | None = None,
    *,
    preserve_precedents: bool = False,
    existing_dataset_keys: set[str] | None = None,
    physical_inventory: _PhysicalDatasetInventory | None = None,
    dataset_type_rows: list[dict] | None = None,
) -> None:
    fields = _dataset_type_graph_fields(
        dataset_type_name,
        rc_dir,
        existing_dataset_keys=existing_dataset_keys,
        physical_inventory=physical_inventory,
        dataset_type_rows=dataset_type_rows,
    )
    if preserve_precedents:
        meta["dependents"] = fields["dependents"]
    else:
        meta.update(fields)
        # ArcRho cell links are instance-level precedent edges on top of the
        # dataset-type formula graph, exactly as the app server's
        # ``apply_sidecar_graph_fields`` merges them; ``_reconcile_sidecar_dependents``
        # then writes the matching dependents entry on each linked source.
        own_key = _canon_dataset_name(meta.get("dataset_name") or dataset_type_name)
        linked_names = [
            name
            for name in link_precedent_names(
                meta.get("internal_links"),
                meta.get("formula_links"),
            )
            if _canon_dataset_name(name) != own_key
        ]
        if linked_names:
            meta["precedents"] = _merge_dependency_entries(
                meta.get("precedents"),
                [{"dataset_name": name} for name in linked_names],
            )
    meta.pop("dependencies", None)


def _reconcile_sidecar_dependents(
    sidecars: list[tuple[Path, dict]],
    rc_dir: Path,
    *,
    physical_inventory: _PhysicalDatasetInventory | None = None,
    dataset_type_rows: list[dict] | None = None,
) -> int:
    rows = _dataset_type_rows() if dataset_type_rows is None else dataset_type_rows
    rows_by_key = _dataset_type_rows_by_key(rows)
    inventory = physical_inventory or _build_physical_dataset_inventory(rc_dir)
    by_key: dict[str, tuple[Path, dict]] = {}
    additions_by_key: dict[str, list[dict]] = {}
    for path, meta in sidecars:
        dataset_identity = _clean_name(meta.get("dataset_name") or meta.get("dataset_type") or path.stem)
        dataset_type = _clean_name(meta.get("dataset_type") or dataset_identity)
        dataset_key = _canon_dataset_name(dataset_identity)
        if dataset_key:
            by_key.setdefault(dataset_key, (path, meta))
        type_key = _canon_dataset_name(dataset_type)
        if type_key:
            by_key.setdefault(type_key, (path, meta))
        for precedent_name in _entry_names(meta.get("precedents")):
            precedent_key = _canon_dataset_name(precedent_name)
            if not precedent_key or not dataset_identity:
                continue
            additions_by_key.setdefault(precedent_key, []).append(
                _dependency_entry(
                    dataset_identity,
                    rows_by_key,
                    rc_dir,
                    include_formula=True,
                    physical_inventory=inventory,
                )
            )

    updated = 0
    for key, additions in additions_by_key.items():
        target = by_key.get(key)
        if not target:
            continue
        _path, meta = target
        before = json.dumps(meta.get("dependents"), sort_keys=True, ensure_ascii=False, default=str)
        meta["dependents"] = _merge_dependency_entries(meta.get("dependents"), additions)
        after = json.dumps(meta.get("dependents"), sort_keys=True, ensure_ascii=False, default=str)
        if before != after:
            updated += 1
    return updated


def _sidecar_status_timestamp(path: Path, meta: dict) -> float:
    # source_modified is when the data last changed at its source system;
    # updated_at on an engine cache is merely when the cache file was produced.
    for key in ("source_modified", "updated_at", "updated", "modified_at", "modified", "last_modified"):
        parsed = _parse_metadata_datetime(meta.get(key))
        if parsed is not None:
            try:
                return parsed.timestamp()
            except Exception:
                pass
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _sidecar_is_method(meta: dict) -> bool:
    source_kind = _clean_name(meta.get("source_kind")).lower()
    if source_kind in {
        "dfm",
        "result_selection",
        BF_SOURCE_KIND,
        CC_SOURCE_KIND,
        BST_SOURCE_KIND,
        SCON_SOURCE_KIND,
        BS_SR_SOURCE_KIND,
        BS_CRA_SOURCE_KIND,
    }:
        return True
    method_type = _clean_name(meta.get("method_type")).lower().replace("_", " ")
    return method_type in {
        "dfm",
        "result selection",
        BF_METHOD_TYPE.lower(),
        CC_METHOD_TYPE.lower(),
        BST_METHOD_TYPE.lower(),
        SCON_METHOD_TYPE.lower(),
        BS_SR_METHOD_TYPE.lower(),
        BS_CRA_METHOD_TYPE.lower(),
    }


def _is_berquist_sherman_payload(payload: dict) -> bool:
    json_format = _clean_name(payload.get("json_format")).lower()
    return json_format in {BS_SR_JSON_FORMAT, BS_CRA_JSON_FORMAT}


def _refresh_sidecar_statuses(sidecars: list[tuple[Path, dict]]) -> None:
    by_key: dict[str, tuple[Path, dict]] = {}
    for path, meta in sidecars:
        for name in (
            meta.get("dataset_name"),
            meta.get("dataset_type"),
            path.stem,
        ):
            key = _canon_dataset_name(name)
            if key:
                by_key.setdefault(key, (path, meta))

    for path, meta in sidecars:
        if not _sidecar_is_method(meta):
            continue
        current_ts = _sidecar_status_timestamp(path, meta)
        status = normalize_method_status(meta.get("status"))
        if status == METHOD_STATUS_OK and current_ts > 0:
            for precedent_name in _entry_names(meta.get("precedents")):
                source = by_key.get(_canon_dataset_name(precedent_name))
                if not source:
                    continue
                source_path, source_meta = source
                if _sidecar_status_timestamp(source_path, source_meta) > current_ts + 0.000001:
                    status = METHOD_STATUS_NEEDS_REVIEW
                    break
        meta["status"] = status


def _cached_dataset_names_from_payload(payload: dict) -> set[str]:
    names: set[str] = set()
    _add_cached_dataset_name(names, payload.get("dataset_name"))
    if names:
        return names
    if _clean_name(payload.get("json_format")).lower() == RS_JSON_FORMAT:
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        _add_cached_dataset_name(names, details_tab.get("name"))
        return names
    if _is_berquist_sherman_payload(payload):
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        _add_cached_dataset_name(names, details_tab.get("name"))
        return names
    details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
    _add_cached_dataset_name(names, details_tab.get("output_dataset") or details_tab.get("output_type"))
    return names

def _dataset_type_from_payload(payload: dict) -> str:
    if _clean_name(payload.get("json_format")).lower() == RS_JSON_FORMAT:
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        text = _normalize_cached_dataset_name(details_tab.get("output_type"))
        if text:
            return text
        return _normalize_cached_dataset_name(details_tab.get("name"))
    if _is_berquist_sherman_payload(payload):
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        return (
            _normalize_cached_dataset_name(details_tab.get("output_type"))
            or _normalize_cached_dataset_name(details_tab.get("name"))
        )
    text = _normalize_cached_dataset_name(payload.get("dataset_type"))
    if text:
        return text
    details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
    return _normalize_cached_dataset_name(details_tab.get("output_type"))


def _category_from_payload(payload: dict) -> str:
    if _clean_name(payload.get("json_format")).lower() == RS_JSON_FORMAT:
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        return _clean_name(details_tab.get("dataset_category") or details_tab.get("output_category"))
    if _is_berquist_sherman_payload(payload):
        details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
        return _clean_name(details_tab.get("dataset_category") or details_tab.get("output_category"))
    text = _clean_name(payload.get("dataset_category") or payload.get("category"))
    if text:
        return text
    details_tab = payload.get("details_tab") if isinstance(payload.get("details_tab"), dict) else {}
    return _clean_name(details_tab.get("output dataset_category") or details_tab.get("output_category"))


def _metadata_text(metadata: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        text = _clean_name(metadata.get(key))
        if text:
            return text
    return ""

def _format_file_timestamp(value: float) -> str:
    try:
        return datetime.fromtimestamp(float(value)).isoformat(timespec="seconds")
    except Exception:
        return ""

def _numeric_timestamp(value: object) -> float:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else 0.0
    except Exception:
        return 0.0

def _parse_metadata_datetime(value: object) -> datetime | None:
    text = _clean_name(value)
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    try:
        return parsed.replace(tzinfo=None)
    except Exception:
        return parsed

def _metadata_modified_timestamp(metadata: dict) -> tuple[str, float]:
    raw = _metadata_text(metadata, (
        "last_modified",
        "last_modified",
        "updated_at",
        "updated",
        "modified_at",
        "modified",
    ))
    parsed = _parse_metadata_datetime(raw)
    if parsed is None:
        return raw, 0.0
    return parsed.isoformat(), parsed.timestamp()

def _metadata_created_timestamp(metadata: dict) -> tuple[str, float]:
    raw = _metadata_text(metadata, (
        "created_at",
        "created",
        "creation_time",
    ))
    parsed = _parse_metadata_datetime(raw)
    if parsed is None:
        return raw, 0.0
    return parsed.isoformat(), parsed.timestamp()

def _scan_physical_dataset_files(folder_path: Path) -> list[dict]:
    files: list[dict] = []
    if not folder_path.is_dir():
        return files

    metadata_cache: dict[Path, dict] = {}
    entries: list[Path] = []
    dataset_dir = folder_path / DATASET_CACHE_DIR
    if dataset_dir.is_dir():
        entries.extend(entry for entry in dataset_dir.iterdir())
    method_dir = folder_path / METHOD_DATA_DIR
    if method_dir.is_dir():
        entries.extend(entry for entry in method_dir.iterdir())
    sidecar_dir = folder_path / DATASET_SIDECAR_DIR
    if sidecar_dir.is_dir():
        entries.extend(entry for entry in sidecar_dir.iterdir())

    for entry in sorted(entries, key=lambda item: str(item).lower()):
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if ext not in {".csv", ".json"} or entry.name == INDEX_FILE_NAME:
            continue

        stat = entry.stat()
        file_names: set[str] = set()
        metadata: dict = {}
        method_type = ""
        method_dataset_name = ""
        method_dataset_type = ""
        method_data_format = ""
        method_origin_length: object = ""
        method_development_length: object = ""
        legacy_length_only_name = _has_legacy_length_only_suffix(entry.stem)

        if ext == ".csv":
            file_names = _cached_dataset_names_from_file(entry.name)
            metadata_path = _dataset_sidecar_path_for_cached_csv(entry)
            metadata = metadata_cache.setdefault(metadata_path, _safe_read_json(metadata_path))
            metadata_is_sidecar = True
            legacy_length_only_name = legacy_length_only_name or _has_legacy_length_only_suffix(metadata_path.stem)
        else:
            metadata = metadata_cache.setdefault(entry, _safe_read_json(entry))
            is_sidecar = entry.parent.name == DATASET_SIDECAR_DIR
            metadata_is_sidecar = is_sidecar
            if not is_sidecar and entry.name.startswith("DFM@"):
                details_tab = metadata.get("details_tab") if isinstance(metadata.get("details_tab"), dict) else {}
                output_dataset = details_tab.get("output_dataset")
                _add_cached_dataset_name(file_names, output_dataset or details_tab.get("output_type"))
                method_dataset_name = _normalize_cached_dataset_name(output_dataset)
                method_dataset_type = _normalize_cached_dataset_name(details_tab.get("output_type"))
                if not method_dataset_name:
                    method_dataset_name = method_dataset_type
                method_type = "DFM" if file_names else ""
            elif not is_sidecar and entry.name.startswith("RS@"):
                details_tab = metadata.get("details_tab") if isinstance(metadata.get("details_tab"), dict) else {}
                _add_cached_dataset_name(file_names, details_tab.get("name"))
                method_dataset_name = _normalize_cached_dataset_name(details_tab.get("name"))
                method_dataset_type = _normalize_cached_dataset_name(details_tab.get("output_type")) or method_dataset_name
                method_type = "Result Selection" if file_names else ""
            elif not is_sidecar and entry.name.startswith((BS_SR_FILE_PREFIX, BS_CRA_FILE_PREFIX)):
                details_tab = metadata.get("details_tab") if isinstance(metadata.get("details_tab"), dict) else {}
                _add_cached_dataset_name(file_names, details_tab.get("name"))
                method_dataset_name = _normalize_cached_dataset_name(details_tab.get("name"))
                method_dataset_type = _normalize_cached_dataset_name(details_tab.get("output_type")) or method_dataset_name
                method_data_format = "Triangle"
                method_origin_length = details_tab.get("origin_length")
                method_development_length = details_tab.get("development_length")
                if file_names:
                    method_type = (
                        BS_SR_METHOD_TYPE
                        if entry.name.startswith(BS_SR_FILE_PREFIX)
                        else BS_CRA_METHOD_TYPE
                    )
            else:
                payload_names = set() if legacy_length_only_name else _cached_dataset_names_from_payload(metadata)
                file_names = payload_names or _cached_dataset_names_from_file(entry.name)

        if metadata and not entry.name.startswith("DFM@") and not legacy_length_only_name:
            file_names.update(_cached_dataset_names_from_payload(metadata))

        file_info = {
            "name": entry.name,
            "path": str(entry),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "mtime_ns": stat.st_mtime_ns,
            "last_modified": _format_file_timestamp(stat.st_mtime),
            "last_modified_timestamp": stat.st_mtime,
        }
        if file_names:
            file_info["dataset_names"] = sorted(file_names, key=lambda item: item.lower())
            first_name = file_info["dataset_names"][0]
            file_info["dataset_name"] = first_name
        if metadata:
            metadata_dataset_name = _normalize_cached_dataset_name(metadata.get("dataset_name"))
            dataset_type = _dataset_type_from_payload(metadata)
            category = _category_from_payload(metadata)
            if not legacy_length_only_name:
                if metadata_dataset_name:
                    file_info["dataset_name"] = metadata_dataset_name
                if dataset_type:
                    file_info["dataset_type"] = dataset_type
            if category:
                file_info["dataset_category"] = category
            file_info["source_kind"] = _clean_name(metadata.get("source_kind"))
            file_info["data_format"] = _clean_name(metadata.get("data_format"))
            file_info["method_type"] = _clean_name(metadata.get("method_type"))
            if "status" in metadata:
                file_info["status"] = metadata.get("status")
            if file_info["data_format"].lower() == "vector":
                file_info["origin_length"] = metadata.get("period_length")
            else:
                file_info["origin_length"] = metadata.get("origin_length")
            file_info["development_length"] = metadata.get("development_length")
            if "calculated" in metadata:
                file_info["calculated"] = metadata.get("calculated")
            file_info["user"] = _metadata_text(metadata, (
                "user",
                "user_name",
                "username",
                "UserName",
                "created_by",
                "modified_by",
                "updated_by",
                "owner",
                "author",
            ))
            metadata_modified, metadata_modified_ts = _metadata_modified_timestamp(metadata)
            if metadata_modified:
                file_info["last_modified"] = metadata_modified
                if metadata_is_sidecar:
                    file_info["_last_modified_from_sidecar"] = True
                if metadata_modified_ts > 0:
                    file_info["last_modified_timestamp"] = metadata_modified_ts
            metadata_created, metadata_created_ts = _metadata_created_timestamp(metadata)
            if metadata_created and metadata_is_sidecar:
                file_info["created"] = metadata_created
                file_info["_created_from_sidecar"] = True
                if metadata_created_ts > 0:
                    file_info["created_timestamp"] = metadata_created_ts
        if method_type:
            if method_dataset_name:
                file_info["dataset_name"] = method_dataset_name
            if method_dataset_type:
                file_info["dataset_type"] = method_dataset_type
            file_info["method_type"] = method_type
            if method_data_format:
                file_info["data_format"] = method_data_format
            if method_origin_length not in (None, ""):
                file_info["origin_length"] = method_origin_length
            if method_development_length not in (None, ""):
                file_info["development_length"] = method_development_length
            if method_type == BS_SR_METHOD_TYPE:
                file_info["source_kind"] = BS_SR_SOURCE_KIND
            elif method_type == BS_CRA_METHOD_TYPE:
                file_info["source_kind"] = BS_CRA_SOURCE_KIND
        files.append(file_info)
    return files

def rebuild_dataset_instance_index(project_name: str, rc_path: str, rc_dir: Path) -> Path:
    rc_dir.mkdir(parents=True, exist_ok=True)
    project_name, rc_path = resolve_canonical_index_identity(
        project_name,
        rc_path,
        rc_dir,
    )
    index_path = rc_dir / INDEX_FILE_NAME
    with index_update_lock(
        index_path,
        project_name=project_name,
        reserving_class=rc_path,
    ):
        payload = build_dataset_index_payload(project_name, rc_path, rc_dir)
        write_index_json_unlocked(index_path, payload)
    print(
        f"    OK  {INDEX_FILE_NAME} "
        f"({len(payload['files'])} entries, version {INDEX_VERSION})"
    )
    return index_path

def refresh_sidecar_graphs_for_rc(rc_dir: Path) -> int:
    """Refresh formula-derived graph metadata for all dataset sidecars in one RC folder."""
    sidecar_dir = rc_dir / DATASET_SIDECAR_DIR
    if not sidecar_dir.is_dir():
        return 0
    sidecars: list[tuple[Path, dict]] = []
    physical_inventory = _build_physical_dataset_inventory(rc_dir)
    dataset_type_rows = _dataset_type_rows()
    existing_dataset_keys = _rc_existing_dataset_keys(
        rc_dir,
        physical_inventory=physical_inventory,
    )
    for path in sorted(sidecar_dir.glob("*.json"), key=lambda item: item.name.lower()):
        meta = _safe_read_json(path)
        if not meta:
            continue
        dataset_type = _clean_name(meta.get("dataset_type") or meta.get("dataset_name"))
        if not dataset_type:
            continue
        _apply_sidecar_graph_meta(
            meta,
            dataset_type,
            rc_dir,
            preserve_precedents=_sidecar_is_method(meta),
            existing_dataset_keys=existing_dataset_keys,
            physical_inventory=physical_inventory,
            dataset_type_rows=dataset_type_rows,
        )
        sidecars.append((path, meta))
    _reconcile_sidecar_dependents(
        sidecars,
        rc_dir,
        physical_inventory=physical_inventory,
        dataset_type_rows=dataset_type_rows,
    )
    _refresh_sidecar_statuses(sidecars)
    updated = 0
    for path, meta in sidecars:
        before = _safe_read_json(path)
        after = finalize_sidecar(meta)
        if json.dumps(before, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(after, sort_keys=True, ensure_ascii=False, default=str):
            continue
        _write_sidecar_json(path, after, in_place=True)
        updated += 1
    return updated
