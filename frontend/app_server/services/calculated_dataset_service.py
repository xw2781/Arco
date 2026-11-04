from __future__ import annotations

import ast
import contextvars
import getpass
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from arcrho_api.dataset_display_contract import normalize_show_subtotal
from arcrho_api.dataset_link_contract import link_precedent_names
from arcrho_api.dataset_type_contract import (
    dataset_type_formula_graph,
    dataset_type_key,
    dataset_type_keys,
    formula_references,
    generated_formula_refresh_names,
    is_app_calculated_dataset_type,
    is_generated_formula_dataset_type,
)
from arcrho_api.sidecar_core_contract import (
    apply_display_length_fields,
    display_lengths,
    is_vector_format,
    stored_length_fields,
    stored_lengths,
)
from arcrho_api.timestamps import utc_now_text
from app_server import config
from app_server.helpers import (
    _canon_dataset_name,
    atomic_write_csv,
    build_dataset_cache_file_name,
    read_dataset_csv,
    sanitize_dataset_file_name,
)
from app_server.services import (
    class_folder_scan_cache,
    dataset_instance_index_service,
    dependent_walk_service,
    dataset_number_format_service,
    dataset_sidecar_status_service,
    dataset_types_service,
    file_read_cache,
    precedent_cache_service,
    runtime_cache_provenance_service,
    user_identity_service,
)

if TYPE_CHECKING:
    from app_server.services import dataset_types_plan_service

_METHOD_DEPENDENT_READ_EXECUTOR = ThreadPoolExecutor(
    max_workers=6,
    thread_name_prefix="arcrho-method-dependent-read",
)

def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"true", "1", "yes", "y"}


def _now_utc_iso() -> str:
    return utc_now_text()


def _current_user_name() -> str:
    display_name = user_identity_service.get_current_display_name()
    if display_name:
        return display_name
    for value in (os.environ.get("USERNAME"), os.environ.get("USER")):
        text = _clean_text(value)
        if text:
            return text
    try:
        return _clean_text(getpass.getuser()) or "calculated"
    except Exception:
        return "calculated"


def _dataset_type_rows(project_name: str) -> List[Dict[str, Any]]:
    data = dataset_types_service.load_dataset_types_data(
        project_name,
        strict=True,
    )
    rows = []
    for row in data.get("rows") or []:
        if not isinstance(row, list):
            continue
        name = _clean_text(row[0] if len(row) > 0 else "")
        if not name:
            continue
        rows.append({
            "name": name,
            "data_format": _clean_text(row[1] if len(row) > 1 else "Triangle") or "Triangle",
            "category": _clean_text(row[2] if len(row) > 2 else ""),
            "calculated": _bool_value(row[3] if len(row) > 3 else False),
            "formula": _clean_text(row[4] if len(row) > 4 else ""),
            "source": _clean_text(row[5] if len(row) > 5 else ""),
            "generated": _bool_value(row[6] if len(row) > 6 else False),
        })
    return rows


def _dataset_type_name_by_key(project_name: str) -> Dict[str, str]:
    return {
        _canon_dataset_name(row["name"]): row["name"]
        for row in _dataset_type_rows(project_name)
        if _canon_dataset_name(row.get("name"))
    }


def _formula_components(formula: str, known_names: List[str]) -> List[str]:
    """The type names a formula reads, by the one rule in ``arcrho_api.dataset_type_contract``."""
    return formula_references(formula, known_names)


def _app_calculated_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rows ArcRho computes itself, by the one rule in ``arcrho_api.dataset_type_contract``."""
    known_keys = dataset_type_keys(rows)
    return [row for row in rows if is_app_calculated_dataset_type(row, known_keys)]


def _calculated_dataset_contract_from_rows(
    rows: List[Dict[str, Any]],
    dataset_type_name: str,
) -> Dict[str, Any] | None:
    known_names = [row["name"] for row in rows]
    known_keys = dataset_type_keys(rows)
    target_key = _canon_dataset_name(dataset_type_name)
    for row in rows:
        if _canon_dataset_name(row["name"]) != target_key:
            continue
        if not is_app_calculated_dataset_type(row, known_keys):
            return None
        precedents = _formula_components(row["formula"], known_names)
        rows_by_key = {
            _canon_dataset_name(item.get("name")): dict(item)
            for item in rows
            if _canon_dataset_name(item.get("name"))
        }
        return {
            **row,
            "precedents": precedents,
            "precedent_contracts": {
                _canon_dataset_name(name): rows_by_key.get(
                    _canon_dataset_name(name),
                    {},
                )
                for name in precedents
            },
        }
    return None


def calculated_dataset_contract(
    project_name: str,
    dataset_type_name: str,
) -> Dict[str, Any] | None:
    contract = _calculated_dataset_contract_from_rows(
        _dataset_type_rows(project_name),
        dataset_type_name,
    )
    return dict(contract) if contract else None


def _generated_formula_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rows the Engine builds from a formula over other dataset types.

    The Engine evaluates such a type against the source table, so it is never
    the evaluator's to rebuild, but its formula names other types exactly as an
    app-calculated one does. Those names are the links a user sees in Details
    and the chain a source refresh follows.
    """
    return [row for row in rows if is_generated_formula_dataset_type(row)]


def _is_generated_formula_type(rows: List[Dict[str, Any]], dataset_type_name: str) -> bool:
    key = dataset_type_key(dataset_type_name)
    return bool(key) and any(
        dataset_type_key(row.get("name")) == key for row in _generated_formula_rows(rows)
    )


def _direct_precedent_names(project_name: str, dataset_type_name: str) -> List[str]:
    rows = _dataset_type_rows(project_name)
    contract = _calculated_dataset_contract_from_rows(rows, dataset_type_name)
    if contract:
        return list(contract.get("precedents") or [])
    if not _is_generated_formula_type(rows, dataset_type_name):
        return []
    graph = dataset_type_formula_graph(rows)
    return [
        graph.names.get(key, key)
        for key in graph.precedents.get(dataset_type_key(dataset_type_name), ())
    ]


def calculated_dataset_dependency_names(
    project_name: str,
    dataset_type_name: str,
) -> List[str] | None:
    """Return direct inputs for an app-calculated type, or ``None`` otherwise."""
    contract = calculated_dataset_contract(project_name, dataset_type_name)
    return list(contract.get("precedents") or []) if contract else None


def _direct_dependent_names(project_name: str, dataset_type_name: str) -> List[str]:
    rows = _dataset_type_rows(project_name)
    target_key = dataset_type_key(dataset_type_name)
    if not target_key:
        return []
    # Both kinds of formula reader: ArcRho evaluates an app-calculated type and
    # the Engine builds a generated one, and each reads the types its formula
    # names. A calculated type whose formula names a type the table lacks is
    # neither, so it reads nothing.
    reader_keys = {
        dataset_type_key(row["name"])
        for row in (*_app_calculated_rows(rows), *_generated_formula_rows(rows))
    }
    graph = dataset_type_formula_graph(rows)
    return [
        graph.names.get(key, key)
        for key in graph.dependents.get(target_key, ())
        if key in reader_keys
    ]


def generated_formula_refresh_types(
    project_name: str,
    dataset_type_names: Sequence[Any],
) -> List[str]:
    """The requested types plus the Engine-built formulas that read them.

    A source refresh narrowed to a type must rebuild the generated formulas
    over it as well, and the formulas over those. The expansion is the
    project's dataset-type table read once through the shared rule, so the
    Engine job and the rules job both ask the same question here.
    """
    return generated_formula_refresh_names(
        _dataset_type_rows(project_name),
        list(dataset_type_names or []),
    )


def _name_entries(names: List[str]) -> List[Dict[str, str]]:
    return dataset_sidecar_status_service.name_entries(names)


def _precedent_entries(
    project_name: str,
    dataset_type_name: str,
    dependency_info: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    # The persisted graph is location-independent: a precedent is named, never
    # pathed. ``dependency_info`` (paths, stats) is runtime state for the
    # calculation that produced the output and is not written to the sidecar.
    return _name_entries(_direct_precedent_names(project_name, dataset_type_name))


_DEPENDENCY_RECORD_FIELDS = (
    "source_kind",
    "data_format",
    "origin_length",
    "development_length",
    "period_length",
    "cumulative",
    "calendar",
    "size",
    "mtime_ns",
    "sha256",
    "input_path",
    "input_size",
    "input_mtime_ns",
    "input_sha256",
)


def _dependency_fingerprints(dependency_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project the components a calculation read into its technical record.

    Each entry names the dependency and the exact file it was read from with
    that file's fingerprint, plus the input a DFM method output was rebuilt
    from. A live-preview component has no file and is left out.
    """
    entries: List[Dict[str, Any]] = []
    for item in dependency_info:
        if not isinstance(item, dict):
            continue
        path = _clean_text(item.get("path"))
        if not path:
            continue
        entry: Dict[str, Any] = {
            "dataset_type": _clean_text(item.get("dataset_type_name")),
            "dataset_name": _clean_text(item.get("dataset_name") or item.get("dataset_type_name")),
            "path": path,
        }
        for key in _DEPENDENCY_RECORD_FIELDS:
            value = item.get(key)
            if value not in (None, ""):
                entry[key] = value
        entries.append(entry)
    return entries


def sidecar_graph_fields(
    project_name: str,
    dataset_type_name: str,
    dependency_info: List[Dict[str, Any]] | None = None,
    reserving_class: str = "",
) -> Dict[str, Any]:
    precedents = _precedent_entries(project_name, dataset_type_name, dependency_info)
    dependent_names = _direct_dependent_names(project_name, dataset_type_name)
    rc = _clean_text(reserving_class)
    if rc:
        existing_keys = _existing_dataset_keys(project_name, rc)
        dependent_names = [
            name
            for name in dependent_names
            if _canon_dataset_name(name) in existing_keys
        ]
        if _is_generated_formula_type(_dataset_type_rows(project_name), dataset_type_name):
            # The Engine rebuilds a generated formula from the source table
            # rather than from its inputs' caches, so a type with no instance in
            # this class is simply not a link here. An app-calculated dataset
            # keeps naming a missing input, because for it that is a real
            # problem.
            precedents = [
                entry
                for entry in precedents
                if _canon_dataset_name(entry.get("dataset_name")) in existing_keys
            ]
    return {
        "precedents": precedents,
        "dependents": _name_entries(dependent_names),
    }


def apply_sidecar_graph_fields(
    payload: Dict[str, Any],
    project_name: str = "",
    dataset_type_name: str = "",
    dependency_info: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    project = _clean_text(project_name or payload.get("project_name"))
    dataset_type = _clean_text(
        dataset_type_name
        or payload.get("dataset_type")
        or payload.get("dataset_name")
    )
    if not project or not dataset_type:
        payload["precedents"] = []
        payload["dependents"] = []
        payload.pop("dependencies", None)
        return payload

    rows_by_key = {
        _canon_dataset_name(row["name"]): row
        for row in _dataset_type_rows(project)
        if _canon_dataset_name(row.get("name"))
    }
    row = rows_by_key.get(_canon_dataset_name(dataset_type))
    if row:
        formula = _clean_text(row.get("formula"))
        payload["calculated"] = bool(row.get("calculated") and not row.get("generated") and formula)

    existing_dependent_names = dataset_sidecar_status_service.entry_names(payload.get("dependents"))
    existing_precedents = payload.get("precedents")
    owning_method_type = dataset_sidecar_status_service.normalize_method_type(
        payload.get("method_type"),
        payload.get("source_kind"),
    )
    graph_fields = sidecar_graph_fields(
        project,
        dataset_type,
        dependency_info,
        _clean_text(payload.get("reserving_class")),
    )
    reserving_class = _clean_text(payload.get("reserving_class"))
    own_dataset_name = _clean_text(payload.get("dataset_name")) or dataset_type
    own_key = _canon_dataset_name(own_dataset_name)
    preserved_method_dependents: List[str] = []
    if reserving_class and existing_dependent_names:
        futures = {
            name: _METHOD_DEPENDENT_READ_EXECUTOR.submit(
                dataset_sidecar_status_service.read_sidecar,
                dataset_sidecar_status_service.sidecar_path(project, reserving_class, name),
            )
            for name in existing_dependent_names
        }
        for name in existing_dependent_names:
            dependent = futures[name].result()
            # A dependent survives the type-graph rebuild when it is a method
            # (the graph cannot re-derive a method edge) or when its own
            # sidecar still names this dataset as a precedent -- the
            # instance-level edge an Arco cell link put there.
            if not dependent or dataset_sidecar_status_service.normalize_method_type(
                dependent.get("method_type"),
                dependent.get("source_kind"),
            ) != dataset_sidecar_status_service.METHOD_TYPE_NONE or own_key in {
                _canon_dataset_name(entry_name)
                for entry_name in dataset_sidecar_status_service.entry_names(dependent.get("precedents"))
            }:
                preserved_method_dependents.append(name)
    graph_fields["dependents"] = dataset_sidecar_status_service.merge_name_entries(
        graph_fields.get("dependents"),
        dataset_sidecar_status_service.name_entries(preserved_method_dependents),
    )
    if owning_method_type != dataset_sidecar_status_service.METHOD_TYPE_NONE:
        graph_fields["precedents"] = existing_precedents if isinstance(existing_precedents, list) else []
    else:
        # Arco cell links are instance-level precedent edges on top of the
        # dataset-type formula graph: the dependent-propagation walk follows
        # them to re-evaluate the linked cells when a source dataset changes.
        # Excel references contribute no edge, and a self-reference never
        # records one.
        linked_names = [
            name
            for name in link_precedent_names(
                payload.get("internal_links"),
                payload.get("formula_links"),
                project_name=project, reserving_class=payload.get("reserving_class", ""),
            )
            if _canon_dataset_name(name) != own_key
        ]
        if linked_names:
            graph_fields["precedents"] = dataset_sidecar_status_service.merge_name_entries(
                graph_fields.get("precedents"),
                dataset_sidecar_status_service.name_entries(linked_names),
            )
    payload.update(graph_fields)
    payload.pop("dependencies", None)
    return payload


def _replace_formula_refs(formula: str, known_names: List[str]) -> Tuple[str, Dict[str, str]]:
    text = _clean_text(formula)
    refs: Dict[str, str] = {}
    by_key = {
        _canon_dataset_name(name): str(name or "").strip()
        for name in known_names
        if _canon_dataset_name(name)
    }

    def new_var(name: str) -> str:
        key = _canon_dataset_name(name)
        if not key:
            return ""
        for var, ref_name in refs.items():
            if _canon_dataset_name(ref_name) == key:
                return var
        var = f"_d{len(refs)}"
        refs[var] = by_key.get(key) or name
        return var

    def quoted_repl(match: re.Match[str]) -> str:
        var = new_var(_clean_text(match.group(1)))
        return var or "0"

    expr = re.sub(r'"([^"]+)"', quoted_repl, text)
    for name in sorted(
        {str(item or "").strip() for item in known_names if str(item or "").strip()},
        key=len,
        reverse=True,
    ):
        key = _canon_dataset_name(name)
        if not key:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", flags=re.IGNORECASE)
        if pattern.search(expr):
            var = new_var(name)
            expr = pattern.sub(var, expr)
    return expr, refs


def _eval_ast(node: ast.AST, values: Dict[str, np.ndarray]) -> np.ndarray | float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, values)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(f"Unknown formula variable: {node.id}")
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand, values)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
    if isinstance(node, ast.BinOp):
        left = _eval_ast(node.left, values)
        right = _eval_ast(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    raise ValueError("Formula contains unsupported syntax.")


def _evaluate_formula_expression(
    expression: str,
    values: Dict[str, np.ndarray],
    scalar_template: np.ndarray | None = None,
) -> np.ndarray:
    """Evaluate the shared dataset grammar without publishing any artifacts."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = _eval_ast(ast.parse(expression, mode="eval"), values)
    arr = np.asarray(result, dtype="float64")
    if arr.ndim == 0:
        template = next(iter(values.values()), scalar_template)
        shape = template.shape if template is not None else (1, 1)
        arr = np.full(shape, float(arr), dtype="float64")
    if arr.ndim == 1:
        arr = arr.reshape((-1, 1))
    return arr


def evaluate_formula(
    formula: str, known_names: List[str], components: Mapping[str, np.ndarray]
) -> np.ndarray:
    """Calculate from already resolved components, with no filesystem reads."""
    expression, references = _replace_formula_refs(formula, known_names)
    values = {
        variable: components[_canon_dataset_name(name)]
        for variable, name in references.items()
    }
    result = _evaluate_formula_expression(expression, values)
    if result.ndim != 2:
        raise ValueError("Unsupported calculated dataset result shape.")
    return result


def _read_sidecar(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _csv_base_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return dataset_instance_index_service._normalize_cached_dataset_name(stem)


def _cached_csv_data_format(path: str, sidecar: Dict[str, Any]) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    parts = stem.split("@")
    if (
        len(parts) >= 5
        and parts[-4].strip().isdigit()
        and parts[-3].strip().isdigit()
        and parts[-2].strip().lower() in {"cum", "inc"}
        and parts[-1].strip().lower() in {"dev", "cal"}
    ):
        return "Triangle"
    if len(parts) >= 2 and parts[-1].strip().isdigit():
        return "Vector"
    return _clean_text(sidecar.get("data_format"))


class _DatasetCacheScan(NamedTuple):
    """One observation of a reserving class's cached CSV folder and sidecars.

    Dependency resolution asks the same folder about several dependencies in a
    row, so callers enumerate once and hand this snapshot down instead of
    re-reading every sidecar per dependency. ``mtime`` comes from the directory
    listing that found the file, so no path is stat-ed twice. ``csv_stats``
    keeps the listing's ``(mtime_ns, size)`` identity per normalized CSV path
    so component value reads can validate the in-memory matrix cache without
    another stat.
    """

    exists: bool
    csv_files: Tuple[Tuple[str, float], ...]
    sidecars: Dict[str, Dict[str, Any]]
    csv_stats: Dict[str, Tuple[int, int]] = {}


class _MethodFolderScan(NamedTuple):
    """One observation of a reserving class's method JSON folder."""

    exists: bool
    method_files: Tuple[Tuple[str, float], ...]
    payloads: Dict[str, Dict[str, Any]]


def _scan_dataset_cache_folder(project_name: str, reserving_class: str) -> _DatasetCacheScan:
    return _scan_dataset_cache_folder_at(
        config.get_project_dataset_cache_dir(project_name, reserving_class)
    )


def _scan_dataset_cache_folder_at(folder: str) -> _DatasetCacheScan:
    """Observe one cached CSV folder given its path (the runtime derives it from a CSV)."""
    exists, csv_entries = class_folder_scan_cache.scan_files_with_stats(folder, ".csv")
    if not exists:
        return _DatasetCacheScan(exists=False, csv_files=(), sidecars={}, csv_stats={})
    # Sidecars are validated against their own folder's listing, so repeat
    # scans cost two directory enumerations instead of one read per file. The
    # folder is derived from the cache folder exactly like the per-CSV mapping
    # in _dataset_sidecar_path_for_cached_csv resolves it.
    if os.path.basename(folder).lower() == config.DATASET_CACHE_DIR.lower():
        sidecar_folder = os.path.join(os.path.dirname(folder), config.DATASET_SIDECAR_DIR)
    else:
        sidecar_folder = os.path.join(folder, config.DATASET_SIDECAR_DIR)
    _sidecar_folder_exists, sidecar_entries = class_folder_scan_cache.scan_files_with_stats(
        sidecar_folder,
        ".json",
    )
    sidecars = class_folder_scan_cache.read_json_files_cached(
        (
            dataset_instance_index_service._dataset_sidecar_path_for_cached_csv(entry.path)
            for entry in csv_entries
        ),
        class_folder_scan_cache.stats_by_normcase_path(sidecar_entries),
    )
    return _DatasetCacheScan(
        exists=True,
        csv_files=tuple((entry.path, entry.mtime) for entry in csv_entries),
        sidecars=sidecars,
        csv_stats=class_folder_scan_cache.stats_by_normcase_path(csv_entries),
    )


def _scan_dfm_method_folder(project_name: str, reserving_class: str) -> _MethodFolderScan:
    return _scan_dfm_method_folder_at(
        config.get_project_method_data_dir(project_name, reserving_class)
    )


def _scan_dfm_method_folder_at(folder: str) -> _MethodFolderScan:
    """Observe one DFM method folder given its path."""
    exists, method_entries = class_folder_scan_cache.scan_files_with_stats(
        folder, ".json", name_prefix="DFM@"
    )
    if not exists:
        return _MethodFolderScan(exists=False, method_files=(), payloads={})
    payloads = class_folder_scan_cache.read_json_files_cached(
        (entry.path for entry in method_entries),
        class_folder_scan_cache.stats_by_normcase_path(method_entries),
    )
    return _MethodFolderScan(
        exists=True,
        method_files=tuple((entry.path, entry.mtime) for entry in method_entries),
        payloads=payloads,
    )


def _sidecar_for_csv(path: str, scan: _DatasetCacheScan | None = None) -> Dict[str, Any]:
    sidecar_path = dataset_instance_index_service._dataset_sidecar_path_for_cached_csv(path)
    payload = scan.sidecars.get(sidecar_path) if scan is not None else None
    if payload is None:
        payload = _read_sidecar(sidecar_path)
    return {**payload, "_sidecar_path": sidecar_path}


def _json_tab(source: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, dict) else {}


def _method_output_names(payload: Dict[str, Any], path: str = "") -> Set[str]:
    names: Set[str] = set()
    details = _json_tab(payload, "details_tab")
    for key in ("output_type", "name"):
        text = _clean_text(details.get(key))
        if text:
            names.add(text)
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem.startswith("DFM@"):
        text = _clean_text(config.decode_filename_segment(stem[len("DFM@"):]))
        if text:
            names.add(text)
    return names


def _candidate_dfm_methods(
    project_name: str,
    reserving_class: str,
    dataset_type_name: str,
    scan: _MethodFolderScan | None = None,
) -> List[Dict[str, Any]]:
    folder = config.get_project_method_data_dir(project_name, reserving_class)
    dep_key = _canon_dataset_name(dataset_type_name)
    if not dep_key:
        return []
    scan = scan if scan is not None else _scan_dfm_method_folder(project_name, reserving_class)
    if not scan.exists:
        return []

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add_candidate(path: str, mtime: float) -> None:
        norm = os.path.abspath(path)
        if norm in seen:
            return
        payload = scan.payloads.get(path)
        if payload is None:
            return
        seen.add(norm)
        names = _method_output_names(payload, path)
        if dep_key not in {_canon_dataset_name(name) for name in names}:
            return
        details = _json_tab(payload, "details_tab")
        output_type = _clean_text(details.get("output_type"))
        method_name = _clean_text(details.get("name"))
        score = 0
        if _canon_dataset_name(output_type) == dep_key:
            score += 8
        if _canon_dataset_name(method_name) == dep_key:
            score += 4
        out.append({
            "path": path,
            "payload": payload,
            "score": score,
            "mtime": mtime,
        })

    # The exact-name file keeps its historical priority among equal scores.
    direct_path = os.path.join(folder, f"DFM@{sanitize_dataset_file_name(dataset_type_name)}.json")
    mtime_by_path = dict(scan.method_files)
    if direct_path in mtime_by_path:
        add_candidate(direct_path, mtime_by_path[direct_path])
    for path, mtime in scan.method_files:
        add_candidate(path, mtime)

    out.sort(key=lambda item: (int(item.get("score") or 0), float(item.get("mtime") or 0)), reverse=True)
    best_score = int(out[0].get("score") or 0) if out else 0
    return [item for item in out if int(item.get("score") or 0) == best_score]


def _path_in_dir(path: str, folder: str) -> bool:
    try:
        child = os.path.normcase(os.path.realpath(os.path.abspath(path)))
        parent = os.path.normcase(os.path.realpath(os.path.abspath(folder)))
        return os.path.commonpath([child, parent]) == parent
    except Exception:
        return False


def _existing_path_in_dir(path: str, folder: str) -> str:
    recorded_path = _clean_text(path)
    if not recorded_path:
        return ""
    candidates = [recorded_path]
    relocated_path = os.path.join(
        folder,
        os.path.basename(recorded_path),
    )
    if os.path.normcase(relocated_path) != os.path.normcase(recorded_path):
        candidates.append(relocated_path)
    for candidate in candidates:
        if _path_in_dir(candidate, folder) and os.path.isfile(candidate):
            return candidate
    return ""


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _read_numeric_csv(path: str) -> np.ndarray:
    df = read_dataset_csv(path, dtype="float64", keep_default_na=True)
    return df.to_numpy(dtype="float64")


def _read_dfm_input_triangle(
    project_name: str,
    reserving_class: str,
    payload: Dict[str, Any],
    target_settings: Dict[str, Any],
    exact_input_path: str = "",
    scan: _DatasetCacheScan | None = None,
) -> Tuple[np.ndarray | None, str, str]:
    data_tab = _json_tab(payload, "data_tab")
    details = _json_tab(payload, "details_tab")
    dataset_folder = config.get_project_dataset_cache_dir(project_name, reserving_class)
    if exact_input_path:
        if (
            not _path_in_dir(exact_input_path, dataset_folder)
            or not os.path.isfile(exact_input_path)
        ):
            return None, exact_input_path, "Recorded DFM input triangle path is invalid."
        try:
            return _read_numeric_csv(exact_input_path), exact_input_path, ""
        except Exception as exc:
            return None, exact_input_path, str(exc)

    path = _clean_text(data_tab.get("input data triangle csv path"))
    if path and os.path.isfile(path) and _path_in_dir(path, dataset_folder):
        try:
            return _read_numeric_csv(path), path, ""
        except Exception as exc:
            return None, path, str(exc)

    input_name = _clean_text(details.get("input_triangle"))
    if not input_name:
        return None, "", "DFM method is missing an input triangle name."
    candidates = _candidate_csvs(project_name, reserving_class, input_name, target_settings, scan=scan)
    if not candidates:
        return None, "", f"Missing DFM input triangle: {input_name}"
    if len(candidates) > 1:
        return None, "", f"Ambiguous DFM input triangle: {input_name}"
    path = str(candidates[0]["path"])
    try:
        return _read_numeric_csv(path), path, ""
    except Exception as exc:
        return None, path, str(exc)


def _selected_dfm_ratio_values(payload: Dict[str, Any], dev_count: int) -> List[float]:
    ratios_tab = _json_tab(payload, "ratios_tab")
    formulas = _json_tab(ratios_tab, "average_formulas")
    selected = formulas.get("selected") if isinstance(formulas.get("selected"), list) else []
    values = formulas.get("values") if isinstance(formulas.get("values"), list) else []
    ratio_count = max(0, int(dev_count or 0))
    out: List[float] = []
    for col in range(ratio_count):
        if dev_count and col >= dev_count - 1:
            out.append(1.0)
            continue
        selected_row = None
        for row_index, row in enumerate(selected):
            row_values = row if isinstance(row, list) else []
            if col < len(row_values) and _finite_float(row_values[col]) == 1.0:
                selected_row = row_index
                break
        if selected_row is None:
            selected_row = 0
        source_row = values[selected_row] if selected_row < len(values) and isinstance(values[selected_row], list) else []
        ratio = _finite_float(source_row[col] if col < len(source_row) else None)
        out.append(ratio if ratio is not None else 1.0)
    return out


def _cumulative_factors(ratio_values: List[float]) -> List[float | None]:
    cumulative: List[float | None] = [None] * len(ratio_values)
    running: float | None = None
    for index in range(len(ratio_values) - 1, -1, -1):
        value = ratio_values[index]
        if not np.isfinite(value):
            cumulative[index] = None
            running = None
            continue
        if index == len(ratio_values) - 1:
            running = value
        elif running is not None and np.isfinite(running):
            running = value * running
        else:
            cumulative[index] = None
            running = None
            continue
        cumulative[index] = running
    return cumulative


def _build_dfm_method_vector(
    project_name: str,
    reserving_class: str,
    payload: Dict[str, Any],
    target_settings: Dict[str, Any],
    exact_input_path: str = "",
    scan: _DatasetCacheScan | None = None,
) -> Tuple[np.ndarray | None, str, str]:
    data_tab = _json_tab(payload, "data_tab")
    input_values, input_path, error = _read_dfm_input_triangle(
        project_name,
        reserving_class,
        payload,
        target_settings,
        exact_input_path=exact_input_path,
        scan=scan,
    )
    if error:
        return None, input_path, error
    if input_values is None or input_values.ndim != 2:
        return None, input_path, "DFM input triangle could not be loaded."

    dev_labels = data_tab.get("development_labels") if isinstance(data_tab.get("development_labels"), list) else []
    origin_labels = data_tab.get("origin_labels") if isinstance(data_tab.get("origin_labels"), list) else []
    dev_count = len(dev_labels) or input_values.shape[1]
    if dev_count <= 0:
        return None, input_path, "DFM method is missing development periods."

    cumulative = _cumulative_factors(_selected_dfm_ratio_values(payload, dev_count))
    row_count = len(origin_labels) or input_values.shape[0]
    out: List[float] = []
    for row_index in range(row_count):
        latest_value = None
        latest_col = None
        if row_index < input_values.shape[0]:
            max_col = min(dev_count - 1, input_values.shape[1] - 1)
            for col in range(max_col, -1, -1):
                value = _finite_float(input_values[row_index, col])
                if value is not None:
                    latest_value = value
                    latest_col = col
                    break
        factor = cumulative[latest_col] if latest_col is not None and latest_col < len(cumulative) else None
        out.append(latest_value * factor if latest_value is not None and factor is not None else np.nan)
    return np.asarray(out, dtype="float64").reshape((-1, 1)), input_path, ""


def _candidate_csvs(
    project_name: str,
    reserving_class: str,
    dataset_type_name: str,
    target_settings: Dict[str, Any],
    expected_data_format: str = "",
    scan: _DatasetCacheScan | None = None,
    current_copies_only: bool = False,
) -> List[Dict[str, Any]]:
    dep_key = _canon_dataset_name(dataset_type_name)
    out: List[Dict[str, Any]] = []
    scan = scan if scan is not None else _scan_dataset_cache_folder(project_name, reserving_class)
    if not scan.exists:
        return []
    for path, mtime in scan.csv_files:
        sidecar = _sidecar_for_csv(path, scan)
        candidate_data_format = _cached_csv_data_format(path, sidecar)
        if (
            _clean_text(expected_data_format)
            and candidate_data_format
            and candidate_data_format.lower() != _clean_text(expected_data_format).lower()
        ):
            continue
        dataset_name = _clean_text(sidecar.get("dataset_name") or _csv_base_name(path))
        type_name = _clean_text(sidecar.get("dataset_type") or _csv_base_name(path))
        if dep_key not in {_canon_dataset_name(dataset_name), _canon_dataset_name(type_name), _canon_dataset_name(_csv_base_name(path))}:
            continue
        if (
            current_copies_only
            and _clean_text(sidecar.get("source_kind")).lower() in {"engine", "input"}
            and _clean_text(sidecar.get("csv_file"))
            and not _is_sidecar_named_csv({"path": path, "sidecar": sidecar})
        ):
            # Only the file an Engine or hand-entered sidecar names is kept
            # current; an ``@n`` sibling beside it is a view an older release
            # wrote down, and a source refresh or a save leaves it stale. The
            # caller brings the named copy to the formula's shape instead.
            continue
        score = 0
        if _canon_dataset_name(type_name) == dep_key:
            score += 8
        if _canon_dataset_name(dataset_name) == dep_key:
            score += 4
        for key in ("origin_length", "development_length"):
            if str(sidecar.get(key) or "").strip() and str(sidecar.get(key)) == str(target_settings.get(key)):
                score += 1
        for key in ("cumulative", "calendar"):
            if key in sidecar and bool(sidecar.get(key)) == bool(target_settings.get(key)):
                score += 1
        if _candidate_matches_target_shape(path, candidate_data_format, target_settings):
            score += 3
        out.append({
            "path": path,
            "sidecar": sidecar,
            "data_format": candidate_data_format,
            "score": score,
            "mtime": mtime,
        })
    out.sort(key=lambda item: (int(item.get("score") or 0), float(item.get("mtime") or 0)), reverse=True)
    best_score = int(out[0].get("score") or 0) if out else 0
    best = [item for item in out if int(item.get("score") or 0) == best_score]
    if len(best) > 1:
        # A sidecar names the copy it owns, and the sibling ``@n`` files beside
        # it are coarser views of the same figures. The scoring above can never
        # separate them: they share that one sidecar, and a vector states its
        # period under ``period_length`` rather than the length keys scored
        # here, so every view ties and the caller calls the dependency
        # ambiguous. Let the sidecar's own file decide, as the runtime resolver
        # does; ``_component_at_target_shape`` rolls it up afterwards.
        named = [item for item in best if _is_sidecar_named_csv(item)]
        if named:
            return named
    return best


def _candidate_matches_target_shape(
    path: str,
    data_format: str,
    target_settings: Mapping[str, Any],
) -> bool:
    if _clean_text(data_format).lower() != "vector":
        return False
    try:
        target_period = int(target_settings.get("origin_length") or 0)
    except (TypeError, ValueError):
        return False
    if target_period <= 0:
        return False
    return os.path.splitext(os.path.basename(path))[0].endswith(f"@{target_period}")


def _is_sidecar_named_csv(candidate: Mapping[str, Any]) -> bool:
    sidecar = candidate.get("sidecar")
    named = _clean_text(sidecar.get("csv_file")) if isinstance(sidecar, Mapping) else ""
    if not named:
        return False
    return os.path.normcase(os.path.basename(str(candidate.get("path") or ""))) == os.path.normcase(
        os.path.basename(named)
    )


def _engine_cache_at_target_shape(
    path: str,
    sidecar: Mapping[str, Any],
    target_settings: Mapping[str, Any],
) -> bool:
    """Whether an Engine-generated cache is already at the formula's lengths.

    The file name is the only record of a generated cache's shape: the
    sidecar's stored pair is the source table's granularity.
    """

    expected = build_dataset_cache_file_name(
        _clean_text(sidecar.get("dataset_name")) or _csv_base_name(path),
        sidecar.get("data_format") or "Triangle",
        int(target_settings.get("origin_length") or 12),
        int(target_settings.get("development_length") or 12),
        sidecar.get("cumulative", True),
        sidecar.get("calendar", False),
    )
    return os.path.normcase(os.path.splitext(os.path.basename(path))[0]) == os.path.normcase(expected)


def _target_paths(
    project_name: str,
    reserving_class: str,
    dataset_name: str,
    settings: Dict[str, Any],
    data_format: Any = "",
) -> Tuple[str, str]:
    folder = config.get_project_dataset_cache_dir(project_name, reserving_class)
    csv_name = build_dataset_cache_file_name(
        dataset_name,
        data_format or "Triangle",
        settings.get("origin_length") or 12,
        settings.get("development_length") or 12,
        settings.get("cumulative", True),
        settings.get("calendar", False),
    )
    csv_path = os.path.join(folder, f"{csv_name}.csv")
    sidecar_path = os.path.join(
        config.get_project_dataset_sidecar_dir(project_name, reserving_class),
        f"{sanitize_dataset_file_name(dataset_name)}.json",
    )
    return csv_path, sidecar_path


def _load_component_matrix(path: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Read one component CSV and its content fingerprint (cache-miss loader)."""

    df = read_dataset_csv(path, dtype="float64", keep_default_na=True)
    return df.to_numpy(dtype="float64"), runtime_cache_provenance_service.file_fingerprint(path)


def _component_at_target_shape(
    project_name: str,
    sidecar: Mapping[str, Any],
    values: np.ndarray,
    target_settings: Mapping[str, Any],
) -> np.ndarray:
    """Aggregate a hand-entered component to the shape the formula runs at.

    A formula is evaluated at its output's own display shape, and a
    hand-entered precedent may be stored finer than that: its CSV then holds a
    column for every stored period, and every cell the coarse view does not
    read is a cumulative 0. Rolling it up here is the same in-memory read the
    methods' precedent resolver already does, so the formula sees the values
    the Dataset window shows rather than the finer grid underneath them.
    """

    target_origin = int(target_settings.get("origin_length") or 12)
    target_development = int(target_settings.get("development_length") or 12)
    if (target_origin, target_development) == stored_lengths(sidecar):
        return values
    if precedent_cache_service.rollup_reason(sidecar, target_origin, target_development):
        return values
    rows = precedent_cache_service.rollup_rows(
        project_name,
        sidecar,
        values.tolist(),
        target_origin,
        target_development,
    )
    return np.array(
        [[np.nan if value is None else float(value) for value in row] for row in rows],
        dtype="float64",
    )


def _existing_target_settings(project_name: str, reserving_class: str, dataset_name: str) -> Dict[str, Any]:
    sidecar_path = os.path.join(
        config.get_project_dataset_sidecar_dir(project_name, reserving_class),
        f"{sanitize_dataset_file_name(dataset_name)}.json",
    )
    # The mtime-validated cache turns the repeat read into one stat round trip.
    try:
        payload = file_read_cache.read_json_file_cached(sidecar_path)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Display, not stored: these settings are what the output is regenerated
    # at, and a calculated output is written at the shape it is shown at.
    origin_length, development_length = display_lengths(payload)
    return {
        "origin_length": origin_length or 12,
        "development_length": development_length or 12,
        "cumulative": bool(payload.get("cumulative", True)),
        "calendar": bool(payload.get("calendar", False)),
        "created": _clean_text(payload.get("created")),
    }


def _existing_vector_cache_periods(
    project_name: str,
    reserving_class: str,
    dataset_name: str,
    scan: _DatasetCacheScan | None = None,
) -> List[int]:
    prefix = re.escape(sanitize_dataset_file_name(dataset_name))
    pattern = re.compile(rf"^{prefix}@(\d+)\.csv$", re.IGNORECASE)
    dataset_scan = scan if scan is not None else _scan_dataset_cache_folder(project_name, reserving_class)
    if not dataset_scan.exists:
        return []
    periods = {
        int(match.group(1))
        for path, _mtime in dataset_scan.csv_files
        if (match := pattern.match(os.path.basename(path))) and int(match.group(1)) > 0
    }
    return sorted(periods)


def _calculated_cache_settings(
    project_name: str,
    reserving_class: str,
    dataset_name: str,
    data_format: Any,
    scan: _DatasetCacheScan | None = None,
) -> List[Dict[str, Any]]:
    settings = _existing_target_settings(project_name, reserving_class, dataset_name)
    if _clean_text(data_format).lower() != "vector":
        return [settings]
    periods = _existing_vector_cache_periods(project_name, reserving_class, dataset_name, scan)
    if not periods:
        periods = [int(settings.get("origin_length") or 12)]
    return [
        {
            **settings,
            "origin_length": period,
            "development_length": period,
        }
        for period in periods
    ]


def _rollup_calculated_vector(
    project_name: str,
    values: np.ndarray,
    source_period: int,
    target_period: int,
) -> np.ndarray:
    if source_period == target_period:
        return values
    rows = precedent_cache_service.rollup_rows(
        project_name,
        {
            "source_kind": "input",
            "data_format": "Vector",
            "stored_period_length": source_period,
        },
        _jsonable_matrix(values),
        target_period,
        source_period,
    )
    return np.array(
        [[np.nan if value is None else float(value) for value in row] for row in rows],
        dtype="float64",
    )


def _load_components(
    project_name: str,
    reserving_class: str,
    components: List[str],
    target_settings: Dict[str, Any],
    component_overrides: Dict[str, np.ndarray] | None = None,
    component_paths: Dict[str, str] | None = None,
    component_formats: Dict[str, str] | None = None,
    component_method_sources: Dict[str, Dict[str, str]] | None = None,
    dataset_scan: _DatasetCacheScan | None = None,
) -> Tuple[Dict[str, np.ndarray], List[Dict[str, Any]], List[str]]:
    values: Dict[str, np.ndarray] = {}
    dependency_info: List[Dict[str, Any]] = []
    errors: List[str] = []
    overrides = component_overrides or {}
    exact_paths = component_paths or {}
    expected_formats = component_formats or {}
    exact_method_sources = component_method_sources or {}
    # Every component resolves against the same two folders and this loop only
    # reads, so each folder is enumerated at most once per call instead of once
    # per component. On a network drive that removes one full sidecar sweep per
    # extra dependency.
    method_scan: _MethodFolderScan | None = None

    def cached_dataset_scan() -> _DatasetCacheScan:
        nonlocal dataset_scan
        if dataset_scan is None:
            dataset_scan = _scan_dataset_cache_folder(project_name, reserving_class)
        return dataset_scan

    def cached_method_scan() -> _MethodFolderScan:
        nonlocal method_scan
        if method_scan is None:
            method_scan = _scan_dfm_method_folder(project_name, reserving_class)
        return method_scan

    for index, component in enumerate(components):
        component_key = _canon_dataset_name(component)
        expected_format = _clean_text(expected_formats.get(component_key))
        override = overrides.get(_canon_dataset_name(component))
        if override is not None:
            arr = np.asarray(override, dtype="float64")
            if arr.ndim == 1:
                arr = arr.reshape((-1, 1))
            if arr.ndim != 2:
                errors.append(f"Unsupported live preview shape for dependency: {component}")
                continue
            values[f"_d{index}"] = arr
            dependency_info.append({
                "dataset_type_name": component,
                "path": "",
                "source_kind": "live_preview",
            })
            continue
        exact_method_source = exact_method_sources.get(component_key)
        exact_method = (
            exact_method_source
            if isinstance(exact_method_source, dict)
            else {}
        )
        exact_method_path = _clean_text(exact_method.get("path"))
        exact_method_input_path = _clean_text(exact_method.get("input_path"))
        validated_method_input_path = ""
        exact_path = _clean_text(exact_paths.get(component_key))
        candidates: List[Dict[str, Any]]
        method_candidates: List[Dict[str, Any]] | None = None
        if exact_method_path:
            method_folder = config.get_project_method_data_dir(
                project_name,
                reserving_class,
            )
            dataset_folder = config.get_project_dataset_cache_dir(
                project_name,
                reserving_class,
            )
            resolved_method_path = _existing_path_in_dir(
                exact_method_path,
                method_folder,
            )
            method_payload = (
                _read_sidecar(resolved_method_path)
                if resolved_method_path
                else {}
            )
            method_output_matches = component_key in {
                _canon_dataset_name(name)
                for name in _method_output_names(
                    method_payload,
                    resolved_method_path,
                )
            }
            if resolved_method_path and method_output_matches:
                if exact_method_input_path:
                    data_tab = _json_tab(method_payload, "data_tab")
                    details = _json_tab(method_payload, "details_tab")
                    current_input_path = _clean_text(
                        data_tab.get("input data triangle csv path")
                    )
                    resolved_recorded_input = _existing_path_in_dir(
                        exact_method_input_path,
                        dataset_folder,
                    )
                    resolved_current_input = _existing_path_in_dir(
                        current_input_path,
                        dataset_folder,
                    )
                    if (
                        resolved_recorded_input
                        and resolved_current_input
                        and os.path.normcase(os.path.realpath(resolved_recorded_input))
                        == os.path.normcase(os.path.realpath(resolved_current_input))
                    ):
                        validated_method_input_path = resolved_current_input
                    elif resolved_recorded_input and not current_input_path:
                        input_name = _clean_text(details.get("input_triangle"))
                        input_sidecar = _sidecar_for_csv(resolved_recorded_input, dataset_scan)
                        exact_input_names = {
                            _canon_dataset_name(input_sidecar.get("dataset_name")),
                            _canon_dataset_name(input_sidecar.get("dataset_type")),
                            _canon_dataset_name(
                                _csv_base_name(resolved_recorded_input)
                            ),
                        }
                        if _canon_dataset_name(input_name) in exact_input_names:
                            validated_method_input_path = resolved_recorded_input
                method_candidates = [{
                    "path": resolved_method_path,
                    "payload": method_payload,
                    "score": 1,
                    "mtime": os.stat(resolved_method_path).st_mtime,
                }]
                candidates = []
            else:
                candidates = _candidate_csvs(
                    project_name,
                    reserving_class,
                    component,
                    target_settings,
                    expected_data_format=expected_format,
                    scan=cached_dataset_scan(),
                    current_copies_only=True,
                )
        elif exact_path:
            # An exact path needs one sidecar, so reuse a folder observation only
            # when an earlier component already paid for it.
            sidecar = _sidecar_for_csv(exact_path, dataset_scan)
            exact_data_format = _cached_csv_data_format(exact_path, sidecar)
            exact_names = {
                _canon_dataset_name(sidecar.get("dataset_name")),
                _canon_dataset_name(sidecar.get("dataset_type")),
                _canon_dataset_name(_csv_base_name(exact_path)),
            }
            if (
                not os.path.isfile(exact_path)
                or component_key not in exact_names
                or (
                    expected_format
                    and exact_data_format
                    and exact_data_format.lower() != expected_format.lower()
                )
            ):
                errors.append(f"Invalid exact dependency path: {component}")
                continue
            candidates = [{
                "path": exact_path,
                "sidecar": sidecar,
                "data_format": exact_data_format,
                "score": 1,
                "mtime": os.stat(exact_path).st_mtime,
            }]
        else:
            candidates = _candidate_csvs(
                project_name,
                reserving_class,
                component,
                target_settings,
                expected_data_format=expected_format,
                scan=cached_dataset_scan(),
                current_copies_only=True,
            )
        if not candidates:
            if method_candidates is None:
                method_candidates = _candidate_dfm_methods(
                    project_name,
                    reserving_class,
                    component,
                    scan=cached_method_scan(),
                )
            if not method_candidates:
                errors.append(f"Missing dependency: {component}")
                continue
            if len(method_candidates) > 1:
                errors.append(f"Ambiguous DFM dependency: {component}")
                continue
            method_item = method_candidates[0]
            method_path = str(method_item["path"])
            arr, input_path, error = _build_dfm_method_vector(
                project_name,
                reserving_class,
                method_item.get("payload") if isinstance(method_item.get("payload"), dict) else {},
                target_settings,
                exact_input_path=validated_method_input_path,
                scan=dataset_scan,
            )
            if error or arr is None:
                errors.append(f"Failed to rebuild DFM dependency {component}: {error or 'unknown error'}")
                continue
            var = f"_d{index}"
            values[var] = arr
            fingerprint = runtime_cache_provenance_service.file_fingerprint(method_path)
            dependency_entry = {
                "dataset_type_name": component,
                "path": method_path,
                "source_kind": "dfm_method",
                "input_path": input_path,
                "mtime": fingerprint["mtime_ns"] / 1_000_000_000,
                **fingerprint,
            }
            if input_path:
                input_fingerprint = runtime_cache_provenance_service.file_fingerprint(
                    input_path
                )
                dependency_entry["input_mtime_ns"] = input_fingerprint["mtime_ns"]
                dependency_entry["input_size"] = input_fingerprint["size"]
                dependency_entry["input_sha256"] = input_fingerprint["sha256"]
            dependency_info.append(dependency_entry)
            continue
        if len(candidates) > 1:
            errors.append(f"Ambiguous dependency: {component}")
            continue
        item = candidates[0]
        path = str(item["path"])
        sidecar = item.get("sidecar") if isinstance(item.get("sidecar"), dict) else {}
        if _clean_text(sidecar.get("source_kind")).lower() == "engine" and not _engine_cache_at_target_shape(
            path, sidecar, target_settings
        ):
            # An Engine-generated precedent cannot be rolled up in memory: its
            # stored pair is the source table's granularity, not its file's
            # shape, so ``_component_at_target_shape`` leaves it alone. Rebuild
            # it at the formula's own lengths, as the method services do. The
            # runtime reuses a copy already at those lengths only while its
            # provenance still matches the source table.
            target_origin = int(target_settings.get("origin_length") or 12)
            try:
                path = precedent_cache_service.materialize_engine_source(
                    project_name,
                    reserving_class,
                    _clean_text(sidecar.get("dataset_name")) or component,
                    sidecar,
                    target_origin,
                    development_length=int(target_settings.get("development_length") or 12),
                )
            except RuntimeError as exc:
                errors.append(f"{component} could not be generated at {target_origin} months: {exc}")
                continue
        try:
            arr, fingerprint = class_folder_scan_cache.read_matrix_cached(
                path,
                _load_component_matrix,
                stat_hint=(
                    dataset_scan.csv_stats.get(os.path.normcase(path))
                    if dataset_scan is not None
                    else None
                ),
            )
        except Exception as exc:
            errors.append(f"Failed to read dependency {component}: {exc}")
            continue
        try:
            arr = _component_at_target_shape(project_name, sidecar, arr, target_settings)
        except ValueError as exc:
            errors.append(f"Failed to read dependency {component}: {exc}")
            continue
        var = f"_d{index}"
        values[var] = arr
        # Stored, not displayed: this records what was read from ``path``.
        stored_origin, stored_development = stored_lengths(sidecar)
        dependency_info.append({
            "dataset_type_name": component,
            "dataset_name": _clean_text(sidecar.get("dataset_name") or component),
            "path": path,
            "source_kind": _clean_text(sidecar.get("source_kind")),
            "data_format": _clean_text(sidecar.get("data_format")),
            "stored_origin_length": stored_origin,
            "stored_development_length": stored_development,
            "cumulative": sidecar.get("cumulative"),
            "calendar": sidecar.get("calendar"),
            "mtime": fingerprint["mtime_ns"] / 1_000_000_000,
            **fingerprint,
        })
    return values, dependency_info, errors


def _array_from_preview_values(
    values: List[List[Any]] | None,
    mask: List[List[bool]] | None = None,
) -> np.ndarray:
    rows = values if isinstance(values, list) else []
    out: List[List[float]] = []
    for r, row in enumerate(rows):
        source_row = row if isinstance(row, list) else []
        mask_row = mask[r] if isinstance(mask, list) and r < len(mask) and isinstance(mask[r], list) else None
        converted: List[float] = []
        for c, value in enumerate(source_row):
            if mask_row is not None and c < len(mask_row) and not bool(mask_row[c]):
                converted.append(np.nan)
                continue
            number = _finite_float(value)
            converted.append(number if number is not None else np.nan)
        out.append(converted)
    return np.asarray(out, dtype="float64")


def _jsonable_matrix(arr: np.ndarray) -> List[List[float | None]]:
    matrix = np.asarray(arr, dtype="float64")
    if matrix.ndim == 1:
        matrix = matrix.reshape((-1, 1))
    return [
        [float(value) if np.isfinite(value) else None for value in row]
        for row in matrix.tolist()
    ]


def _matrix_mask(arr: np.ndarray) -> List[List[bool]]:
    matrix = np.asarray(arr, dtype="float64")
    if matrix.ndim == 1:
        matrix = matrix.reshape((-1, 1))
    return [
        [bool(np.isfinite(value)) for value in row]
        for row in matrix.tolist()
    ]


def _latest_diagonal_or_vector_values(arr: np.ndarray, data_format: str) -> List[float | None]:
    matrix = np.asarray(arr, dtype="float64")
    if matrix.ndim == 1:
        matrix = matrix.reshape((-1, 1))
    if _clean_text(data_format).lower() == "vector":
        return [
            float(row[0]) if len(row) and np.isfinite(row[0]) else None
            for row in matrix
        ]
    out: List[float | None] = []
    for row in matrix:
        picked: float | None = None
        for value in reversed(row):
            if np.isfinite(value):
                picked = float(value)
                break
        out.append(picked)
    return out


def _calculated_rows_by_key(project_name: str) -> Dict[str, Dict[str, Any]]:
    return {
        _canon_dataset_name(row["name"]): row
        for row in _app_calculated_rows(_dataset_type_rows(project_name))
    }


def _dependency_map(project_name: str, rows: List[Dict[str, Any]] | None = None) -> Dict[str, Set[str]]:
    rows = rows if rows is not None else _dataset_type_rows(project_name)
    known_names = [row["name"] for row in rows]
    out: Dict[str, Set[str]] = {}
    for row in _app_calculated_rows(rows):
        target_key = _canon_dataset_name(row["name"])
        for component in _formula_components(row["formula"], known_names):
            comp_key = _canon_dataset_name(component)
            if comp_key:
                out.setdefault(comp_key, set()).add(target_key)
    return out


def _target_dependency_map(project_name: str, rows: List[Dict[str, Any]] | None = None) -> Dict[str, Set[str]]:
    rows = rows if rows is not None else _dataset_type_rows(project_name)
    known_names = [row["name"] for row in rows]
    out: Dict[str, Set[str]] = {}
    for row in _app_calculated_rows(rows):
        target_key = _canon_dataset_name(row["name"])
        deps = {
            _canon_dataset_name(component)
            for component in _formula_components(row["formula"], known_names)
            if _canon_dataset_name(component)
        }
        out[target_key] = deps
    return out


# One dependent walk reads the class's existing dataset names once. Every
# nested walk a method wave opens asks the same question, and answering it
# through ``get_index`` after the walk's own writes have moved the folder
# signature rebuilds the whole index each time. A walk only rewrites instances
# that already exist, so the set cannot change while it runs; the outermost
# ``recalculate_dependents`` opens the snapshot and the final index rebuild
# still runs after the walk.
_existing_dataset_keys_snapshot: contextvars.ContextVar[Dict[Tuple[str, str], Set[str]] | None] = (
    contextvars.ContextVar("existing_dataset_keys_snapshot", default=None)
)


def _existing_dataset_keys(project_name: str, reserving_class: str) -> Set[str]:
    snapshot = _existing_dataset_keys_snapshot.get()
    snapshot_key = (_clean_text(project_name).casefold(), _clean_text(reserving_class).casefold())
    if snapshot is not None and snapshot_key in snapshot:
        return snapshot[snapshot_key]
    index = dataset_instance_index_service.get_index(project_name, reserving_class, refresh=False)
    keys: Set[str] = set()
    for item in index.get("files", []) if isinstance(index.get("files"), list) else []:
        for value in [item.get("name"), item.get("dataset_type")]:
            key = _canon_dataset_name(value)
            if key:
                keys.add(key)
    if snapshot is not None:
        snapshot[snapshot_key] = keys
    return keys


def _downstream_keys(
    project_name: str,
    changed_names: List[str],
    rows: List[Dict[str, Any]] | None = None,
) -> List[str]:
    dep_map = _dependency_map(project_name, rows)
    seen: Set[str] = set()
    out: List[str] = []
    queue = [_canon_dataset_name(name) for name in changed_names if _canon_dataset_name(name)]
    while queue:
        key = queue.pop(0)
        for target in sorted(dep_map.get(key, set())):
            if target in seen:
                continue
            seen.add(target)
            out.append(target)
            queue.append(target)

    target_set = set(out)
    deps_by_target = _target_dependency_map(project_name, rows)
    ordered: List[str] = []
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            return
        visiting.add(key)
        for dep in sorted(deps_by_target.get(key, set())):
            if dep in target_set:
                visit(dep)
        visiting.remove(key)
        visited.add(key)
        ordered.append(key)

    for key in out:
        visit(key)
    return ordered


def _existing_downstream_keys(
    project_name: str,
    reserving_class: str,
    changed_names: List[str],
    rows: List[Dict[str, Any]] | None = None,
) -> List[str]:
    existing_keys = _existing_dataset_keys(project_name, reserving_class)
    if not existing_keys:
        return []
    return [
        key
        for key in _downstream_keys(project_name, changed_names, rows)
        if key in existing_keys
    ]


def existing_downstream_dataset_types(
    project_name: str,
    reserving_class: str,
    changed_names: List[str],
) -> List[Dict[str, Any]]:
    """Name every calculated dataset a walk from ``changed_names`` can reach.

    Read-only view of the same formula graph ``_recalculate_dependents_impl``
    walks, in the same dependency order, restricted to instances that exist in
    this reserving class. The two-step save shows this list before it writes
    anything; it is a superset of what a walk ultimately rewrites, because
    only the walk itself can tell whether an intermediate output changed.
    """

    rows = _dataset_type_rows(project_name)
    rows_by_key = {_canon_dataset_name(row.get("name")): row for row in rows}
    out: List[Dict[str, Any]] = []
    for key in _existing_downstream_keys(project_name, reserving_class, changed_names, rows):
        row = rows_by_key.get(key)
        if not row:
            continue
        out.append({
            "dataset_name": str(row.get("name") or ""),
            "data_format": str(row.get("data_format") or ""),
            "formula": str(row.get("formula") or ""),
        })
    return out


def dataset_type_graph_signature(project_name: str) -> List[List[Any]]:
    """Project the dataset-type rows that decide the calculated dependency graph.

    The two-step save fingerprints this so a formula edited between the plan
    the user reviewed and the commit is caught before the save lands.
    """

    return sorted(
        (
            [
                _canon_dataset_name(row.get("name")),
                bool(row.get("calculated")),
                bool(row.get("generated")),
                _clean_text(row.get("formula")),
            ]
            for row in _dataset_type_rows(project_name)
            if _canon_dataset_name(row.get("name"))
        ),
        key=lambda item: item[0],
    )


def _recalculate_dataset_impl(
    project_name: str,
    reserving_class: str,
    dataset_type_name: str,
    *,
    component_paths: Dict[str, str] | None = None,
    component_method_sources: Dict[str, Dict[str, str]] | None = None,
    dataset_type_rows: List[Dict[str, Any]] | None = None,
    target_settings: Mapping[str, Any] | None = None,
    dataset_scan: _DatasetCacheScan | None = None,
) -> Dict[str, Any]:
    all_rows = _dataset_type_rows(project_name) if dataset_type_rows is None else dataset_type_rows
    rows_by_key = {
        _canon_dataset_name(item.get("name")): item
        for item in _app_calculated_rows(all_rows)
    }
    row = rows_by_key.get(_canon_dataset_name(dataset_type_name))
    if not row:
        return {"ok": False, "dataset_type_name": dataset_type_name, "skipped": True, "reason": "not_calculated"}

    known_names = [item["name"] for item in all_rows]
    expr, refs = _replace_formula_refs(row["formula"], known_names)
    ordered_components = [refs[key] for key in sorted(refs.keys(), key=lambda item: int(item[2:]))]

    settings = dict(target_settings or _existing_target_settings(project_name, reserving_class, row["name"]))
    values, precedents, errors = _load_components(
        project_name,
        reserving_class,
        ordered_components,
        settings,
        component_paths=component_paths,
        component_method_sources=component_method_sources,
        component_formats={
            _canon_dataset_name(item.get("name")): _clean_text(item.get("data_format"))
            for item in all_rows
            if _canon_dataset_name(item.get("name"))
        },
        dataset_scan=dataset_scan,
    )
    if errors:
        missing_prefix = "Missing dependency: "
        return {
            "ok": False,
            "dataset_type_name": row["name"],
            "skipped": True,
            "reason": "dependency_error",
            "errors": errors,
            "missing_dependencies": [
                error[len(missing_prefix):]
                for error in errors
                if error.startswith(missing_prefix)
            ],
        }

    eval_values: Dict[str, np.ndarray] = {}
    for var, ref_name in refs.items():
        try:
            idx = ordered_components.index(ref_name)
        except ValueError:
            return {"ok": False, "dataset_type_name": row["name"], "skipped": True, "reason": f"missing_reference:{ref_name}"}
        eval_values[var] = values[f"_d{idx}"]

    try:
        arr = _evaluate_formula_expression(expr, eval_values)
    except Exception as exc:
        return {
            "ok": False,
            "dataset_type_name": row["name"],
            "skipped": True,
            "reason": "formula_error",
            "errors": [str(exc)],
        }

    if arr.ndim != 2:
        return {"ok": False, "dataset_type_name": row["name"], "skipped": True, "reason": "unsupported_result_shape"}

    csv_path, sidecar_path = _target_paths(
        project_name,
        reserving_class,
        row["name"],
        settings,
        row.get("data_format") or "Triangle",
    )
    now = _now_utc_iso()
    existing_sidecar = _read_sidecar(sidecar_path)
    created = existing_sidecar.get("created") or settings.get("created") or now
    user_name = _current_user_name()
    action_value = "Update" if existing_sidecar else "Insert"
    default_format_settings = dataset_number_format_service.dataset_type_number_format_settings(
        row["name"],
    )
    number_format = dataset_number_format_service.normalize_number_format(
        existing_sidecar.get("number_format") or default_format_settings["number_format"]
    )
    decimal_places = existing_sidecar.get("decimal_places")
    if decimal_places is None:
        decimal_places = dataset_number_format_service.number_format_decimal_places(number_format)
    data_format = row.get("data_format") or "Triangle"
    stored_origin = settings.get("origin_length") or 12
    stored_development = settings.get("development_length") or 12
    display_origin = stored_origin
    if is_vector_format(data_format):
        # A vector is written at its finest cache period, and the period it is
        # shown at is the user's choice, kept while it is still a whole
        # multiple of the store.
        kept_period, _ = display_lengths(existing_sidecar)
        if kept_period and kept_period % stored_origin == 0:
            display_origin = kept_period
    payload = {
        **({"audit_log": existing_sidecar.get("audit_log")} if existing_sidecar else {}),
        "dataset_name": row["name"],
        "dataset_type": row["name"],
        "reserving_class": reserving_class,
        "project_name": project_name,
        "source_kind": "calculated",
        "data_format": data_format,
        # The formula was evaluated at these lengths and the CSV written at
        # them, so they are the shape this output is stored at.
        **stored_length_fields(data_format, stored_origin, stored_development),
        "show_subtotal": normalize_show_subtotal(existing_sidecar.get("show_subtotal")),
        "csv_file": os.path.basename(csv_path),
        "created": created,
        "updated_at": now,
        "modified_by": user_name,
        "calculated": True,
        "method_type": dataset_sidecar_status_service.METHOD_TYPE_NONE,
        "status": dataset_sidecar_status_service.STATUS_CURRENT,
        "dependents": existing_sidecar.get("dependents", []),
        "number_format": number_format,
        "decimal_places": dataset_number_format_service.normalize_decimal_places(
            decimal_places,
            default_format_settings["decimal_places"],
        ),
    }
    apply_display_length_fields(
        payload,
        data_format,
        display_origin,
        stored_development,
        cumulative=settings.get("cumulative", True),
        calendar=settings.get("calendar", False),
    )
    apply_sidecar_graph_fields(payload, project_name, row["name"], precedents)
    from app_server.services.dataset_service import (
        _append_dataset_audit_entry,
        _write_dataset_csv_and_sidecar,
    )

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    os.makedirs(os.path.dirname(sidecar_path), exist_ok=True)
    _append_dataset_audit_entry(payload, action_value, event_date=now, user_name=user_name)
    _write_dataset_csv_and_sidecar(pd.DataFrame(arr), csv_path, sidecar_path, payload)
    # The sidecar names the precedents and nothing else. What this output was
    # built from -- the formula and each dependency's file and fingerprint --
    # is the technical record beside the CSV, which the exact-cache check reads.
    runtime_cache_provenance_service.record_calculated(
        csv_path,
        identity=runtime_cache_provenance_service.calculated_cache_identity(
            csv_path,
            project_name=project_name,
            reserving_class=reserving_class,
            dataset_name=row["name"],
            dataset_type=row["name"],
        ),
        formula=row["formula"],
        dependencies=_dependency_fingerprints(precedents),
    )
    status_updates = []
    config.DATASETS["arcrhotri_" + hashlib.sha1(csv_path.encode("utf-8")).hexdigest()[:16]] = csv_path

    return {
        "ok": True,
        "dataset_type_name": row["name"],
        "path": csv_path,
        "sidecar_path": sidecar_path,
        "precedents": payload.get("precedents", []),
        "dependents": payload.get("dependents", []),
        "status_updates": status_updates,
        "_calculated_matrix": arr,
        "_precedent_fingerprints": _dependency_fingerprints(precedents),
    }


def recalculate_dataset(
    project_name: str,
    reserving_class: str,
    dataset_type_name: str,
    *,
    component_paths: Dict[str, str] | None = None,
    component_method_sources: Dict[str, Dict[str, str]] | None = None,
    dataset_type_rows: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    with dataset_sidecar_status_service.reserving_class_io_lock(project_name, reserving_class):
        all_rows = _dataset_type_rows(project_name) if dataset_type_rows is None else dataset_type_rows
        calculated_rows = {
            _canon_dataset_name(item.get("name")): item
            for item in _app_calculated_rows(all_rows)
        }
        row = calculated_rows.get(_canon_dataset_name(dataset_type_name))
        if not row:
            return _recalculate_dataset_impl(
                project_name,
                reserving_class,
                dataset_type_name,
                component_paths=component_paths,
                component_method_sources=component_method_sources,
                dataset_type_rows=all_rows,
            )
        dataset_scan = (
            _scan_dataset_cache_folder(project_name, reserving_class)
            if _clean_text(row.get("data_format")).lower() == "vector"
            else None
        )
        cache_settings = _calculated_cache_settings(
            project_name,
            reserving_class,
            row["name"],
            row.get("data_format"),
            dataset_scan,
        )
        result = _recalculate_dataset_impl(
            project_name,
            reserving_class,
            row["name"],
            component_paths=component_paths,
            component_method_sources=component_method_sources,
            dataset_type_rows=all_rows,
            target_settings=cache_settings[0],
            dataset_scan=dataset_scan,
        )
        if result.get("ok"):
            source_period = int(cache_settings[0]["origin_length"])
            values = result.pop("_calculated_matrix")
            dependencies = result.pop("_precedent_fingerprints")
            cache_paths = [str(result.get("path") or "")]
            for settings in cache_settings[1:]:
                target_period = int(settings["origin_length"])
                values_at_target = _rollup_calculated_vector(
                    project_name,
                    values,
                    source_period,
                    target_period,
                )
                csv_path, _sidecar_path = _target_paths(
                    project_name,
                    reserving_class,
                    row["name"],
                    settings,
                    row.get("data_format") or "Triangle",
                )
                atomic_write_csv(pd.DataFrame(values_at_target), csv_path)
                runtime_cache_provenance_service.record_calculated(
                    csv_path,
                    identity=runtime_cache_provenance_service.calculated_cache_identity(
                        csv_path,
                        project_name=project_name,
                        reserving_class=reserving_class,
                        dataset_name=row["name"],
                        dataset_type=row["name"],
                    ),
                    formula=row["formula"],
                    dependencies=dependencies,
                )
                config.DATASETS["arcrhotri_" + hashlib.sha1(csv_path.encode("utf-8")).hexdigest()[:16]] = csv_path
                cache_paths.append(csv_path)
            result["cache_paths"] = cache_paths
        return result


def refresh_output(
    project_name: str,
    reserving_class: str,
    dataset_name: str,
    sidecar: Mapping[str, Any] | None = None,
    changed_precedents: Iterable[Any] = (),
    caches: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Recalculate one calculated dataset and report instead of raising.

    The ordered walk in :mod:`dependent_walk_service` calls this for a node
    whose precedents it has already refreshed, so nothing is cascaded from
    here. A calculated dataset carries no review flag of its own — the walk
    flags the methods below it — so a failure comes back as the same
    ``calculation_error`` step the wave records today, which is what blocks
    its descendants. ``sidecar`` and ``changed_precedents`` belong to the one
    refresher signature and are not read here: the formula names its own
    precedents.
    """

    name = _clean_text(dataset_name)
    store = caches if caches is not None else {}
    rows = store.get("dataset_type_rows")
    if rows is None:
        rows = _dataset_type_rows(project_name)
        store["dataset_type_rows"] = rows
    try:
        return recalculate_dataset(
            project_name,
            reserving_class,
            name,
            dataset_type_rows=rows,
        )
    except Exception as exc:
        return {
            "ok": False,
            "dataset_type_name": name,
            "skipped": True,
            "reason": "calculation_error",
            "errors": [str(exc)],
        }


def _recalculate_dependents_impl(
    project_name: str,
    reserving_class: str,
    changed_dataset_name: str,
    changed_dataset_type_name: str = "",
    *,
    include_dfm: bool = True,
    include_result_selection: bool = True,
    include_berquist_sherman: bool = True,
    include_bornhuetter_ferguson: bool = True,
    include_cape_cod: bool = True,
    include_bootstrap: bool = True,
    finalize_method_review_status: bool = True,
    rebuild_index: bool = True,
    additional_roots: Sequence[Tuple[str, str]] | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict[str, Any]:
    """Order everything the save reaches and refresh each object once.

    The waves this used to run are gone: one ordered pass in
    :mod:`dependent_walk_service` visits every reachable object after its
    precedents, so an object several branches reach is republished once
    instead of once per branch. The ``include_*`` flags now say which kinds
    the pass refreshes; a kind it is told to leave alone is crossed, so the
    walk still reaches what lies below it.
    """

    # Extra roots let one Engine-hosted walk cover several coalesced saves.
    # A progress callback exception (for example a lost reserving-class
    # lease) intentionally aborts the walk; the follow-up walk self-heals.
    root_names = [changed_dataset_name, changed_dataset_type_name]
    for extra_root in additional_roots or []:
        root_names.extend(extra_root)

    kinds = {dependent_walk_service.KIND_CALCULATED, dependent_walk_service.KIND_LINKED_INPUT}
    for included, kind in (
        (include_dfm, dependent_walk_service.KIND_DFM),
        (include_result_selection, dependent_walk_service.KIND_RESULT_SELECTION),
        (include_berquist_sherman, dependent_walk_service.KIND_BERQUIST_SHERMAN),
        (include_bornhuetter_ferguson, dependent_walk_service.KIND_BORNHUETTER_FERGUSON),
        (include_cape_cod, dependent_walk_service.KIND_CAPE_COD),
        (include_bootstrap, dependent_walk_service.KIND_BOOTSTRAP),
    ):
        if included:
            kinds.add(kind)

    return dependent_walk_service.run_pass(
        project_name,
        reserving_class,
        root_names,
        changed_dataset_name=changed_dataset_name,
        changed_dataset_type_name=changed_dataset_type_name,
        kinds=kinds,
        finalize_method_review_status=finalize_method_review_status,
        rebuild_index=rebuild_index,
        progress_callback=progress_callback,
    )


_CASCADE_DOMAIN_FIELDS = (
    "dfm_updates",
    "result_selection_updates",
    "berquist_sherman_updates",
    "bornhuetter_ferguson_updates",
    "cape_cod_updates",
    "bootstrap_updates",
)


def cascade_failure_reasons(report: Mapping[str, Any]) -> List[str]:
    """Name every dependent that declined inside a walk report, and why.

    A method wave reports a failed downstream walk as a single line per
    output ("Downstream refresh failed after BF publication.") and tucks the
    walk itself under ``cascade``, which the flattened save message drops.
    Flattening the walk's own failures into ``"<dataset>: <reason>"`` lines
    lets that message say which dependent declined instead of only that one
    did. Nested cascades are unwound the same way so the innermost reason
    surfaces.
    """
    reasons: List[str] = []
    for name, reason in cascade_failures(report):
        text = f"{name}: {reason}" if name and reason else (name or reason)
        if text not in reasons:
            reasons.append(text)
    return reasons


def cascade_failures(report: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """The walk's declined dependents as ``(name, reason)`` pairs, in order.

    The structured half of :func:`cascade_failure_reasons`, for a caller that
    has to tell the dependents apart rather than only show them.
    """
    failures: List[Tuple[str, str]] = []
    if not isinstance(report, Mapping):
        return failures

    def add(name: Any, reason: Any) -> None:
        pair = (_clean_text(name), _clean_text(reason))
        if (pair[0] or pair[1]) and pair not in failures:
            failures.append(pair)

    for item in report.get("skipped") or []:
        if not isinstance(item, Mapping):
            continue
        details = [_clean_text(error) for error in item.get("errors") or [] if _clean_text(error)]
        add(item.get("dataset_type_name") or item.get("dataset_name"), "; ".join(details) or item.get("reason"))
    link_domain = report.get("link_updates")
    if isinstance(link_domain, Mapping):
        for error in link_domain.get("errors") or []:
            if not isinstance(error, Mapping):
                continue
            details = [_clean_text(text) for text in error.get("errors") or [] if _clean_text(text)]
            add(error.get("dataset_name"), "; ".join(details) or error.get("reason"))
    for field in _CASCADE_DOMAIN_FIELDS:
        domain = report.get(field)
        if not isinstance(domain, Mapping) or domain.get("ok", True):
            continue
        for error in domain.get("errors") or []:
            if not isinstance(error, Mapping):
                continue
            nested = cascade_failures(error.get("cascade")) if isinstance(error.get("cascade"), Mapping) else []
            if nested:
                for pair in nested:
                    add(*pair)
                continue
            add(error.get("dataset_name") or error.get("method_name"), error.get("reason"))
    return failures


def recalculate_dependents(
    project_name: str,
    reserving_class: str,
    changed_dataset_name: str,
    changed_dataset_type_name: str = "",
    *,
    include_dfm: bool = True,
    include_result_selection: bool = True,
    include_berquist_sherman: bool = True,
    include_bornhuetter_ferguson: bool = True,
    include_cape_cod: bool = True,
    include_bootstrap: bool = True,
    finalize_method_review_status: bool = True,
    rebuild_index: bool = True,
    additional_roots: Sequence[Tuple[str, str]] | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict[str, Any]:
    from app_server.services.method_review_service import review_flag_collector

    keys_token = (
        _existing_dataset_keys_snapshot.set({}) if _existing_dataset_keys_snapshot.get() is None else None
    )
    try:
        with (
            review_flag_collector() as review_flagged,
            dataset_sidecar_status_service.reserving_class_io_lock(project_name, reserving_class),
        ):
            result = _recalculate_dependents_impl(
                project_name,
                reserving_class,
                changed_dataset_name,
                changed_dataset_type_name,
                include_dfm=include_dfm,
                include_result_selection=include_result_selection,
                include_berquist_sherman=include_berquist_sherman,
                include_bornhuetter_ferguson=include_bornhuetter_ferguson,
                include_cape_cod=include_cape_cod,
                include_bootstrap=include_bootstrap,
                finalize_method_review_status=finalize_method_review_status,
                rebuild_index=rebuild_index,
                additional_roots=additional_roots,
                progress_callback=progress_callback,
            )
            # The outputs this walk turned from OK to Needs Review: what
            # the user is shown after a save.
            result["review_flagged"] = list(review_flagged)
            return result
    except Exception:
        roots = [changed_dataset_name, changed_dataset_type_name]
        roots.extend(name for pair in additional_roots or [] for name in pair)
        dataset_sidecar_status_service.refresh_method_statuses_for_dependents(
            project_name, reserving_class, roots,
        )
        raise
    finally:
        if keys_token is not None:
            _existing_dataset_keys_snapshot.reset(keys_token)


def preview_dependents(
    project_name: str,
    reserving_class: str,
    changed_dataset_name: str,
    changed_dataset_type_name: str = "",
    values: List[List[Any]] | None = None,
    mask: List[List[bool]] | None = None,
    origin_labels: List[str] | None = None,
    development_labels: List[str] | None = None,
) -> Dict[str, Any]:
    source_arr = _array_from_preview_values(values, mask)
    if source_arr.ndim != 2 or source_arr.size == 0:
        return {"ok": False, "skipped": True, "reason": "empty_preview_values", "steps": []}

    changed = [changed_dataset_name, changed_dataset_type_name]
    targets = _downstream_keys(project_name, changed)
    rows_by_key = _calculated_rows_by_key(project_name)
    overrides: Dict[str, np.ndarray] = {
        _canon_dataset_name(name): source_arr
        for name in changed
        if _canon_dataset_name(name)
    }
    steps: List[Dict[str, Any]] = []

    all_rows = _dataset_type_rows(project_name)
    known_names = [item["name"] for item in all_rows]
    for key in targets:
        row = rows_by_key.get(key)
        if not row:
            continue

        expr, refs = _replace_formula_refs(row["formula"], known_names)
        ordered_components = [refs[var] for var in sorted(refs.keys(), key=lambda item: int(item[2:]))]
        settings = _existing_target_settings(project_name, reserving_class, row["name"])
        component_values, _precedents, errors = _load_components(
            project_name,
            reserving_class,
            ordered_components,
            settings,
            component_overrides=overrides,
        )
        if errors:
            steps.append({
                "ok": False,
                "status": "skipped",
                "dataset_type_name": row["name"],
                "reason": "dependency_error",
                "errors": errors,
            })
            continue

        eval_values: Dict[str, np.ndarray] = {}
        for var, ref_name in refs.items():
            try:
                idx = ordered_components.index(ref_name)
            except ValueError:
                continue
            if f"_d{idx}" in component_values:
                eval_values[var] = component_values[f"_d{idx}"]
        try:
            arr = _evaluate_formula_expression(expr, eval_values, source_arr)
        except Exception as exc:
            steps.append({
                "ok": False,
                "status": "skipped",
                "dataset_type_name": row["name"],
                "reason": "formula_error",
                "errors": [str(exc)],
            })
            continue

        if arr.ndim != 2:
            steps.append({
                "ok": False,
                "status": "skipped",
                "dataset_type_name": row["name"],
                "reason": "unsupported_result_shape",
            })
            continue

        overrides[_canon_dataset_name(row["name"])] = arr
        data_format = row.get("data_format") or "Triangle"
        steps.append({
            "ok": True,
            "status": "preview",
            "dataset_type_name": row["name"],
            "dataset_name": row["name"],
            "source_kind": "calculated_preview",
            "data_format": data_format,
            "values": _latest_diagonal_or_vector_values(arr, data_format),
            "matrix_values": _jsonable_matrix(arr),
            "mask": _matrix_mask(arr),
            "origin_labels": [str(item) for item in (origin_labels or [])],
            "development_labels": [str(item) for item in (development_labels or [])],
        })

    return {
        "ok": True,
        "project_name": project_name,
        "reserving_class": reserving_class,
        "changed_dataset_name": changed_dataset_name,
        "changed_dataset_type_name": changed_dataset_type_name,
        "targets": [
            rows_by_key[key]["name"]
            for key in targets
            if key in rows_by_key
        ],
        "steps": steps,
        "updated": [item for item in steps if item.get("ok")],
        "skipped": [item for item in steps if not item.get("ok")],
    }


def _rows_by_key_from_normalized_rows(rows: List[List[Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, list):
            continue
        name = _clean_text(row[0] if len(row) > 0 else "")
        key = _canon_dataset_name(name)
        if not key:
            continue
        out[key] = {
            "name": name,
            "calculated": _bool_value(row[3] if len(row) > 3 else False),
            "formula": _clean_text(row[4] if len(row) > 4 else ""),
            "generated": _bool_value(row[6] if len(row) > 6 else False),
        }
    return out


def changed_formula_dataset_type_names(previous_rows: List[List[Any]], next_rows: List[List[Any]]) -> List[str]:
    previous = _rows_by_key_from_normalized_rows(previous_rows)
    current = _rows_by_key_from_normalized_rows(next_rows)
    names_by_key = _dataset_type_name_by_key_from_rows(next_rows)
    changed: List[str] = []
    for key, row in current.items():
        prev = previous.get(key)
        if (
            prev is None
            or bool(prev.get("calculated")) != bool(row.get("calculated"))
            or bool(prev.get("generated")) != bool(row.get("generated"))
            or _clean_text(prev.get("formula")) != _clean_text(row.get("formula"))
        ):
            name = names_by_key.get(key) or row.get("name")
            if _clean_text(name):
                changed.append(str(name))
    return changed


def _dataset_type_name_by_key_from_rows(rows: List[List[Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in rows or []:
        if not isinstance(row, list):
            continue
        name = _clean_text(row[0] if len(row) > 0 else "")
        key = _canon_dataset_name(name)
        if key:
            out[key] = name
    return out


def _write_sidecar_json(path: str, payload: Dict[str, Any]) -> None:
    payload = dict(payload)
    payload.pop("instance_name", None)
    payload.pop("dataset_type_name", None)
    dataset_sidecar_status_service.write_sidecar(path, payload)


def _sidecar_method_type(project_name: str, reserving_class: str, dataset_name: str) -> str:
    payload = dataset_sidecar_status_service.read_sidecar(
        dataset_sidecar_status_service.sidecar_path(project_name, reserving_class, dataset_name)
    )
    return dataset_sidecar_status_service.normalize_method_type(
        payload.get("method_type"), payload.get("source_kind")
    )


def find_dataset_type_removal_blockers(
    project_name: str,
    planned: "dataset_types_plan_service.DatasetTypesChangePlan",
) -> List[Dict[str, Any]]:
    """Instances of disappearing dataset types that other objects still read.

    Deleting a dataset type deletes the definition its instances are described
    by, so it may only happen once nothing downstream reads those instances --
    the same rule that already governs deleting one dataset. A dependent that
    is itself an instance of a type being removed in the same change is not a
    blocker: it is leaving too.

    Only the instances the plan already found are opened: the plan knows which
    classes hold a departing type, so no other class is visited.

    Returns one entry per blocked type, each naming the instances still read
    and, for each, the datasets or methods reading them.
    """

    removed_keys = {
        key
        for key in (_canon_dataset_name(name) for name in planned.removed_types)
        if key
    }
    if not removed_keys:
        return []

    blocked_by_type: Dict[str, Dict[str, Any]] = {}
    for affected in planned.classes:
        departing = [
            instance
            for instance in affected.instances
            if _canon_dataset_name(instance.dataset_type) in removed_keys
        ]
        leaving = {_canon_dataset_name(instance.name) for instance in departing}
        for instance in departing:
            payload = dataset_sidecar_status_service.read_sidecar(
                dataset_sidecar_status_service.sidecar_path(
                    project_name, affected.reserving_class, instance.name
                )
            )
            dependents = [
                {
                    "dataset_name": dependent_name,
                    "method_type": _sidecar_method_type(
                        project_name, affected.reserving_class, dependent_name
                    ),
                }
                for dependent_name in dataset_sidecar_status_service.entry_names(
                    payload.get("dependents")
                )
                if _canon_dataset_name(dependent_name)
                and _canon_dataset_name(dependent_name) not in leaving
            ]
            if not dependents:
                continue
            entry = blocked_by_type.setdefault(
                _canon_dataset_name(instance.dataset_type),
                {"dataset_type": instance.dataset_type, "instances": []},
            )
            entry["instances"].append({
                "reserving_class": affected.reserving_class,
                "dataset_name": instance.name,
                "dependents": dependents,
            })

    return [blocked_by_type[key] for key in sorted(blocked_by_type)]


def _rename_dataset_instance(
    project_name: str,
    reserving_class: str,
    sidecar_path: str,
    payload: Dict[str, Any],
    new_name: str,
) -> str:
    """Move one plain dataset instance to a new name; return its new sidecar path.

    The CSV keeps everything after the name in its file name, the old sidecar
    file goes, and each precedent's ``dependents`` entry follows the name. The
    runtime cache provenance is dropped rather than moved: its record is bound
    to the dataset name, so the next open re-validates the cache exactly as it
    does for a cache with no record. The caller holds the class I/O lock and
    writes the returned path itself.
    """

    old_name = _clean_text(payload.get("dataset_name")) or _sidecar_instance_name(sidecar_path)
    old_stem = sanitize_dataset_file_name(old_name)
    new_stem = sanitize_dataset_file_name(new_name)

    csv_file = _clean_text(payload.get("csv_file"))
    if csv_file:
        cache_dir = config.get_project_dataset_cache_dir(project_name, reserving_class)
        old_csv = os.path.join(cache_dir, csv_file)
        if os.path.isfile(old_csv) and csv_file.lower().startswith(old_stem.lower()):
            new_csv_file = new_stem + csv_file[len(old_stem):]
            os.replace(old_csv, os.path.join(cache_dir, new_csv_file))
            runtime_cache_provenance_service.remove(old_csv)
            payload["csv_file"] = new_csv_file

    new_path = dataset_sidecar_status_service.sidecar_path(project_name, reserving_class, new_name)
    if os.path.normcase(os.path.abspath(new_path)) != os.path.normcase(os.path.abspath(sidecar_path)):
        try:
            os.remove(sidecar_path)
        except FileNotFoundError:
            pass
    payload["dataset_name"] = new_name

    precedents = dataset_sidecar_status_service.entry_names(payload.get("precedents"))
    for precedent_name in precedents:
        precedent_path = dataset_sidecar_status_service.sidecar_path(
            project_name, reserving_class, precedent_name
        )
        with dataset_sidecar_status_service.sidecar_write_lock(precedent_path):
            precedent = _read_sidecar(precedent_path)
            if not precedent:
                continue
            if dataset_sidecar_status_service._remove_dependent(precedent, old_name):
                dataset_sidecar_status_service._add_dependent(precedent, new_name)
                _write_sidecar_json(precedent_path, precedent)
    return new_path


def _sidecar_instance_name(path: str) -> str:
    """The dataset instance a sidecar file describes, decoded from its name."""

    stem = os.path.splitext(os.path.basename(path))[0]
    return dataset_instance_index_service._normalize_cached_dataset_name(stem)


def apply_planned_dataset_types_change(
    project_name: str,
    planned: "dataset_types_plan_service.DatasetTypesChangePlan",
    *,
    on_progress: Callable[[str, str, int, int], None] | None = None,
) -> Dict[str, Any]:
    """Rewrite the instances a plan named, then rebuild what changed.

    Runs after the table is written, class by class under each class's I/O
    lock. Every instance the plan listed has its sidecar re-derived from the
    new table: a renamed type's instances take the new type name, and the
    ones the plan marked for renaming move with it. The calculated datasets
    whose formula or kind changed are then recalculated and one Engine
    propagation job per class walks their dependents.

    ``on_progress`` receives ``(stage, label, completed, total)``. The unit is
    one dataset instance, then one reserving class for each class the change
    makes the walk revisit, so the count a caller shows is work done rather
    than stages passed.
    """

    def report(stage: str, label: str, completed: int, total: int) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, label, completed, total)
        except Exception:
            # Progress is telemetry. A publisher that cannot write its status
            # must not abort a rebuild that is already under way.
            pass

    changed_keys = {
        _canon_dataset_name(name)
        for name in planned.changed_types
        if _canon_dataset_name(name)
    }
    rows_by_key = _calculated_rows_by_key(project_name)
    sidecars_updated = 0
    datasets_renamed = 0
    recalc_seeds: Set[Tuple[str, str]] = set()
    errors: List[str] = []

    datasets_total = sum(len(affected.instances) for affected in planned.classes)
    total_units = datasets_total
    completed_units = 0
    report("graphs", "Rebuilding dataset dependency graphs", 0, total_units)

    for affected in planned.classes:
        reserving_class = affected.reserving_class
        with dataset_sidecar_status_service.reserving_class_io_lock(project_name, reserving_class):
            for instance in affected.instances:
                completed_units += 1
                path = dataset_sidecar_status_service.sidecar_path(
                    project_name, reserving_class, instance.name
                )
                try:
                    with dataset_sidecar_status_service.sidecar_write_lock(path):
                        payload = _read_sidecar(path)
                        if not payload:
                            raise RuntimeError("Dataset sidecar is missing.")
                        before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                        payload.pop("instance_name", None)
                        payload.pop("dataset_type_name", None)
                        if instance.new_dataset_type != instance.dataset_type:
                            payload["dataset_type"] = instance.new_dataset_type
                        moved = False
                        if instance.rename_to:
                            path = _rename_dataset_instance(
                                project_name, reserving_class, path, payload, instance.rename_to
                            )
                            moved = True
                            datasets_renamed += 1
                        apply_sidecar_graph_fields(payload, project_name, instance.new_dataset_type)
                        after = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                        if moved or before != after:
                            _write_sidecar_json(path, payload)
                            sidecars_updated += 1
                except Exception as exc:
                    errors.append(f"{reserving_class} / {instance.name}: {exc}")
                    continue
                report(
                    "graphs",
                    f"Rebuilding dependency graphs: {reserving_class}",
                    completed_units,
                    total_units,
                )
                type_key = _canon_dataset_name(instance.new_dataset_type)
                if type_key in changed_keys and type_key in rows_by_key:
                    recalc_seeds.add((reserving_class, rows_by_key[type_key]["name"]))

    # Recalculate each changed-formula dataset itself (the saved objects),
    # then enqueue one Engine propagation job per reserving class covering all
    # of that class's changed roots; the job walks the dependents and rebuilds
    # the index on the server host.
    from app_server.services import dependent_propagation_service

    seeds_by_reserving_class: Dict[str, List[str]] = {}
    for reserving_class, dataset_type in sorted(recalc_seeds):
        seeds_by_reserving_class.setdefault(reserving_class, []).append(dataset_type)

    # The classes the change makes the walk revisit are only known now, so the
    # denominator grows once here rather than being guessed up front.
    total_units = datasets_total + len(seeds_by_reserving_class)
    chains: List[Dict[str, Any]] = []
    for reserving_class, dataset_types in seeds_by_reserving_class.items():
        report(
            "recalculate",
            f"Recalculating {reserving_class}",
            completed_units,
            total_units,
        )
        steps: List[Dict[str, Any]] = []
        for dataset_type in dataset_types:
            try:
                first = recalculate_dataset(project_name, reserving_class, dataset_type)
            except Exception as exc:
                first = {
                    "ok": False,
                    "dataset_type_name": dataset_type,
                    "reason": str(exc),
                }
            steps.append(
                {**first, "status": "updated" if first.get("ok") else "skipped"}
            )
        propagation = dependent_propagation_service.enqueue_save_propagation(
            project_name,
            reserving_class,
            [
                dependent_propagation_service.changed_root(dataset_type, dataset_type)
                for dataset_type in dataset_types
            ],
        )
        chains.append({
            "ok": all(step.get("ok") for step in steps) and bool(propagation.get("ok")),
            "reserving_class": reserving_class,
            "changed_dataset_type_name": ", ".join(dataset_types),
            "steps": steps,
            "updated": [step for step in steps if step.get("ok")],
            "skipped": [step for step in steps if not step.get("ok")],
            "propagation": propagation,
        })
        completed_units += 1

    # Every class the plan named had sidecars rewritten -- a type name or a
    # rename is index content -- so each one's index is rebuilt.
    for affected in planned.classes:
        report(
            "index",
            f"Rebuilding the dataset index: {affected.reserving_class}",
            completed_units,
            total_units,
        )
        try:
            dataset_instance_index_service.rebuild_index(project_name, affected.reserving_class)
        except Exception as exc:
            errors.append(f"{affected.reserving_class} index rebuild: {exc}")

    return {
        "ok": not errors and all(chain.get("ok") for chain in chains),
        "project_name": project_name,
        "changed_dataset_types": list(planned.changed_types),
        "sidecars_updated": sidecars_updated,
        "datasets_renamed": datasets_renamed,
        "datasets_total": datasets_total,
        "classes_total": planned.class_count,
        "chains": chains,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# One-off repair of the persisted link lists
# ---------------------------------------------------------------------------


def project_reserving_classes(project_name: str) -> List[str]:
    """Every reserving class of *project_name* that owns persisted data.

    The folder name is an encoded form of the class path, so the canonical
    spelling is taken from the class's own ``index.json`` when it has one and
    only decoded from the folder name when it does not. This is the one
    enumeration; the Engine's source-refresh job asks it the same question.
    The import staging and scratch folders beside the classes are not classes.
    """

    from arcrho_api.dataset_index_contract import INDEX_FILE_NAME
    from arcrho_project_duplication_contract import PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES

    transient = {name.casefold() for name in PROJECT_DUPLICATION_TRANSIENT_DATA_DIR_NAMES}
    data_dir = config.get_project_data_dir(project_name)
    try:
        entries = sorted(
            (
                entry
                for entry in os.scandir(data_dir)
                if entry.is_dir() and entry.name.casefold() not in transient
            ),
            key=lambda entry: (entry.name.casefold(), entry.name),
        )
    except FileNotFoundError:
        return []

    classes: List[str] = []
    seen: Set[str] = set()
    for entry in entries:
        name = ""
        try:
            with open(os.path.join(entry.path, INDEX_FILE_NAME), "r", encoding="utf-8-sig") as fh:
                payload = json.load(fh)
            if isinstance(payload, Mapping):
                name = _clean_text(payload.get("reserving_class"))
        except (OSError, ValueError, TypeError):
            name = ""
        if not name:
            name = _clean_text(config.decode_filename_segment(entry.name))
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            classes.append(name)
    return classes


def repair_reserving_class_graph_fields(
    project_name: str,
    reserving_class: str,
    *,
    apply: bool = True,
) -> Dict[str, Any]:
    """Recompute the two link lists of every Engine dataset in one class.

    A sidecar written before a generated formula's links were derived keeps
    whichever lists it was first written with, and a regeneration only repairs
    the ones it rebuilds, so the projects that already exist are repaired once
    by hand. This is the dataset-type change job's "graphs" stage over every
    Engine instance of a class rather than the ones a plan named.

    Nothing but ``precedents`` and ``dependents`` moves: the payload is read,
    handed to :func:`apply_sidecar_graph_fields`, and written only when it
    differs, so no ``updated_at`` and no audit record is stamped and a second
    run writes nothing. The reserving-class index carries no link field, so it
    is not rebuilt either. ``apply=False`` reports what would be written.
    """

    project = _clean_text(project_name)
    rc = _clean_text(reserving_class)
    result: Dict[str, Any] = {
        "project_name": project,
        "reserving_class": rc,
        "sidecars_read": 0,
        "sidecars_written": 0,
        "written": [],
        "unreadable": [],
    }
    folder = config.get_project_dataset_sidecar_dir(project, rc)
    try:
        with os.scandir(folder) as iterator:
            paths = sorted(
                entry.path
                for entry in iterator
                if entry.name.lower().endswith(".json") and entry.is_file()
            )
    except FileNotFoundError:
        return result

    with dataset_sidecar_status_service.reserving_class_io_lock(project, rc):
        for path in paths:
            name = _sidecar_instance_name(path)
            try:
                with dataset_sidecar_status_service.sidecar_write_lock(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        payload = json.load(fh)
                    if not isinstance(payload, dict):
                        raise ValueError("A dataset sidecar must hold a JSON object.")
                    result["sidecars_read"] += 1
                    if _clean_text(payload.get("source_kind")).casefold() != "engine":
                        continue
                    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                    apply_sidecar_graph_fields(payload, project)
                    after = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                    if before == after:
                        continue
                    if apply:
                        _write_sidecar_json(path, payload)
                    result["sidecars_written"] += 1
                    result["written"].append(name)
            except Exception as exc:
                result["unreadable"].append({"dataset_name": name, "detail": str(exc)})
    return result
