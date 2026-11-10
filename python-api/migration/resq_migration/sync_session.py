"""Run one ArcRho/ResQ reserving-class synchronization session.

This module owns every step of a synchronization that touches ResQ COM or
reserving-class files: the two inventories, the plan comparison, and the
apply pass that writes each accepted row.  It deliberately owns no user
interface.  The only supported host is a ResQ-connected Arco Bridge worker,
which runs it from the shared request queue on behalf of a client macro that
may sit on a machine without ResQ installed at all.

The session is split into the two phases that queue transport requires:

``preview_sync``
    Collect both inventories, build the plan, and return display-ready rows
    plus the immutable ``signature`` of each row.

``apply_sync``
    Recheck those signatures against a freshly observed plan and, only when
    every reviewed row still matches, apply the accepted actions.

Splitting the phases this way keeps the guarantee the single-process macro
used to get for free: nothing is written when an observation changed while a
person was reading the review table.  The reviewed signature travels with the
apply request rather than being recomputed beside the write, so the check now
covers the whole review window instead of a few seconds inside one call.

``runtime`` is supplied by the host rather than discovered here, so the Bridge
can bind its frozen bundle and a test can bind stubs.  Build one with
``build_runtime``.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_api.bootstrap_contract import BST_FILE_PREFIX
from arcrho_api.stochastic_consolidation_contract import SCON_FILE_PREFIX
from arcrho_api.timestamps import format_display_timestamp

_NAME_SPACE_RE = re.compile(r"\s+")


def _name_key(value: object) -> str:
    """Map an ArcRho or ResQ display name onto their shared logical identity.

    ArcRho keeps every name whitespace-normalized. ResQ names can carry stray
    double spaces that stay as they are, so every comparison of a ResQ name
    against an ArcRho name goes through this one key. It is the same rule the
    sync contract's ``logical_key`` applies when pairing rows, so one ResQ
    object maps onto exactly one ArcRho item whatever its spacing; the ResQ
    spelling itself is only ever used to address or name the ResQ object.
    """

    return _NAME_SPACE_RE.sub(" ", str(value or "").strip()).casefold()


# Host contract version. The Bridge refuses a bundle whose session API it was
# not built against, the same way the macro used to pin the support release.
# 2: ``build_runtime`` takes the ResQ account the session connects with.
# 3: ``export_reserving_class`` pushes a whole class from ArcRho without a review.
# 4: ``preview_transfer`` reviews either direction and the export honours a
#    ticked selection, which is remembered for the next run.
SYNC_SESSION_API_VERSION = 4

MAX_JSON_READ_WORKERS = 8

KIND_DATASET = "Dataset"
KIND_DFM = "DFM"
KIND_BF = "Bornhuetter Ferguson"
KIND_CC = "Cape Cod"
KIND_RS = "Result Selection"
KIND_BS_SR = "B&S Settlement Rate"
KIND_BS_CRA = "B&S Case Reserve Adequacy"
KIND_BOOTSTRAP = "Bootstrap"
KIND_STOCHASTIC_CONSOLIDATION = "Stochastic Consolidation"

_METHOD_KINDS = {
    KIND_DFM,
    KIND_BF,
    KIND_CC,
    KIND_RS,
    KIND_BS_SR,
    KIND_BS_CRA,
    KIND_BOOTSTRAP,
    KIND_STOCHASTIC_CONSOLIDATION,
}
_EXPORTABLE_METHOD_KINDS = {KIND_DFM, KIND_BF, KIND_CC, KIND_RS}
# Methods the ResQ inventory meets as a triangle or vector and then resolves
# to their method object, which a ResQ-to-ArcRho import needs.
_OUTPUT_LOOKUP_METHOD_KINDS = {KIND_BS_SR, KIND_BS_CRA, KIND_BOOTSTRAP, KIND_STOCHASTIC_CONSOLIDATION}
# ArcRho method file prefix per kind, so a selective import replaces only its own method file.
_METHOD_FILE_PREFIXES = {
    KIND_DFM: "DFM@",
    KIND_BF: "BF@",
    KIND_CC: "CC@",
    KIND_RS: "RS@",
    KIND_BOOTSTRAP: BST_FILE_PREFIX,
    KIND_STOCHASTIC_CONSOLIDATION: SCON_FILE_PREFIX,
}
# Methods the export phase writes Notes for and then saves in ResQ without
# writing another field: ResQ recalculates each from the datasets and DFMs
# exported before it and re-stamps it. Keyed by the ResQ method-type code the
# exporter looks it up by. A BF is not one of them: the export writes its
# output type, origin length, latest, percentage developed and priors.
_SAVE_ONLY_METHOD_CODES = {KIND_CC: 3, KIND_BS_SR: 8}
# Methods whose export review row is offered even where the sync's own
# support refuses it: the save-only kinds, B&S Case Reserve Adequacy, whose
# Avg. Selections the exporter writes, and BF, which kept this override when
# it left the save-only group. The sync's field-level apply and read-back do
# not cover the save-only kinds or B&S Case Reserve Adequacy, so those stay
# out of ``_EXPORTABLE_METHOD_KINDS`` and the review offers them for export
# alone.
_EXPORT_PHASE_METHOD_KINDS = set(_SAVE_ONLY_METHOD_CODES) | {KIND_BF, KIND_BS_CRA}

# Tie-break rank inside one write direction. The dependency walk decides the
# order wherever one accepted row reads another; rows with no such link fall
# back to this rank so plain datasets precede the methods that read them, DFMs
# and Berquist Sherman adjustments precede the BF and Cape Cod methods that
# read their output, and Result Selections, which only consume other outputs,
# come last.
_WRITE_KIND_RANK = {
    KIND_DATASET: 0,
    KIND_DFM: 1,
    KIND_BS_SR: 1,
    KIND_BS_CRA: 1,
    KIND_BF: 2,
    KIND_CC: 2,
    KIND_RS: 3,
}


def _dependency_names(entries: object) -> list[str]:
    """Return the dataset names in a sidecar ``precedents``/``dependents`` list."""

    names: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        name = entry.get("dataset_name") if isinstance(entry, Mapping) else entry
        text = " ".join(str(name or "").split())
        if text:
            names.append(text)
    return names


def _row_precedent_names(row: Mapping[str, Any]) -> list[str]:
    """Name every ArcRho dataset this row's ArcRho side reads.

    A row carries the sidecar ``precedents`` of its dataset, the same graph
    ArcRho's own recompute walk follows: a dataset row's payload is its
    sidecar, and a method row carries the precedents of its output sidecar
    beside its method JSON. A method row also names its linked datasets in
    its method tabs; the ResQ writer resolves those links by name, so they
    are dependencies of the ResQ write as well. Calculated datasets never
    reach the plan, so in practice the edges run from plain datasets to the
    methods that read them and between methods.
    """

    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    kind = str(row.get("kind") or KIND_DATASET)
    details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
    method_tab = payload.get("method_tab") if isinstance(payload.get("method_tab"), Mapping) else {}
    names: list[object] = list(_dependency_names(payload.get("precedents")))
    names.extend(_dependency_names(item.get("precedents")))
    if kind == KIND_DFM:
        names.append(details.get("input_triangle"))
    elif kind == KIND_BF:
        names.extend((method_tab.get("latest_dataset"), method_tab.get("dfm_dataset")))
        priors = method_tab.get("prior_datasets") if isinstance(method_tab.get("prior_datasets"), list) else []
        names.extend(prior.get("name") for prior in priors if isinstance(prior, Mapping))
    elif kind == KIND_CC:
        names.extend((
            method_tab.get("exposure_dataset"),
            method_tab.get("latest_dataset"),
            method_tab.get("prior_ultimate_dataset"),
        ))
    elif kind == KIND_RS:
        loaded = method_tab.get("loaded_datasets") if isinstance(method_tab.get("loaded_datasets"), list) else []
        names.extend(source.get("name") for source in loaded if isinstance(source, Mapping))
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        text = " ".join(str(name or "").split())
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def _dependency_ordered_rows(
    sync_contract,
    rows: list[dict[str, Any]],
    edges: Mapping[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Order rows so every dependency accepted in the same batch is written first.

    This is the topological walk ArcRho's own recompute uses, restricted to
    the accepted rows: a row is emitted only after each row it reads. Rows
    with no dependency between them keep the kind rank and then the review
    order, and a cycle, which ArcRho's graph never contains, is broken at its
    back edge instead of failing.

    ``edges`` is the whole reserving class's graph from
    ``_reserving_class_edges``. A dependency that is not a row -- a
    calculated dataset, which never reaches a batch -- is looked through to
    the rows it reads in turn, so a Result Selection that loads a calculated
    vector derived from a DFM is written after that DFM. Without it, a row
    that reads a calculated dataset is ordered as if it read nothing.
    """

    def seed_order(index: int, row: Mapping[str, Any]) -> tuple[int, int]:
        return _WRITE_KIND_RANK.get(str(row.get("kind") or ""), len(_WRITE_KIND_RANK)), index

    reads: dict[str, set[str]] = {}
    for source_key, target_keys in (edges or {}).items():
        for target_key in target_keys:
            reads.setdefault(target_key, set()).add(source_key)

    indexed = sorted(enumerate(rows), key=lambda pair: seed_order(*pair))
    by_key: dict[str, tuple[int, dict[str, Any]]] = {}
    key_of_index: dict[int, str] = {}
    for index, row in indexed:
        key = str(row.get("key") or "")
        if not key or key in by_key:
            key = f"#{index}"
        by_key[key] = (index, row)
        key_of_index[index] = key
    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def row_dependencies(key: str, row: Mapping[str, Any]) -> list[tuple[str, tuple[int, dict[str, Any]]]]:
        dependencies: list[tuple[str, tuple[int, dict[str, Any]]]] = []
        seen: set[str] = {key}
        frontier = [sync_contract.logical_key(name) for name in _row_precedent_names(row)]
        frontier.extend(reads.get(key, ()))
        while frontier:
            dependency_key = frontier.pop()
            if not dependency_key or dependency_key in seen:
                continue
            seen.add(dependency_key)
            if dependency_key in by_key:
                dependencies.append((dependency_key, by_key[dependency_key]))
            else:
                frontier.extend(reads.get(dependency_key, ()))
        return dependencies

    def visit(key: str) -> None:
        if key in visited or key in visiting:
            return
        visiting.add(key)
        _index, row = by_key[key]
        for dependency_key, _pair in sorted(row_dependencies(key, row), key=lambda item: seed_order(*item[1])):
            visit(dependency_key)
        visiting.discard(key)
        visited.add(key)
        ordered.append(row)

    for index, _row in indexed:
        visit(key_of_index[index])
    return ordered


def _reserving_class_edges(
    runtime: Mapping[str, Any],
    rc_dir: Path,
    plan_rows: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """ArcRho's dependency graph for one reserving class, as source key -> the keys that read it.

    The edges are the sidecar ``precedents``/``dependents`` across the whole
    reserving class, calculated datasets included, plus the links in the
    rows' method tabs. It is the graph ArcRho's own recompute walks, and ResQ
    holds the same one once the inputs match, so it decides both the order
    rows are written in and what ResQ recalculates after the writes.
    """

    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    edges: dict[str, set[str]] = {}

    def add_edge(source: object, target: object) -> None:
        source_key = sync_contract.logical_key(source)
        target_key = sync_contract.logical_key(target)
        if source_key and target_key and source_key != target_key:
            edges.setdefault(source_key, set()).add(target_key)

    sidecar_entries = _read_json_entries(
        _directory_files(rc_dir / migration.DATASET_SIDECAR_DIR, ".json")
    )
    for path, _modified, payload in sidecar_entries:
        name = sync_contract.clean_name(
            payload.get("dataset_name") or migration._normalize_cached_dataset_name(path.stem)
        )
        for precedent in _dependency_names(payload.get("precedents")):
            add_edge(precedent, name)
        for dependent in _dependency_names(payload.get("dependents")):
            add_edge(name, dependent)
    for row in plan_rows:
        for precedent in _row_precedent_names(row):
            add_edge(precedent, row.get("key"))
    return edges


def _downstream_keys(
    edges: Mapping[str, set[str]],
    plan_rows: list[dict[str, Any]],
    source_keys: set[str],
) -> set[str]:
    """Name every review row downstream of ``source_keys`` in ``edges``.

    A Result Selection that reads a calculated dataset derived from a written
    DFM is reached through that dataset, so the result names what ResQ
    recalculates after the writes.
    """

    reached: set[str] = set()
    frontier = list(source_keys)
    while frontier:
        current = frontier.pop()
        for target in edges.get(current, ()):
            if target not in reached and target not in source_keys:
                reached.add(target)
                frontier.append(target)
    row_keys = {str(row.get("key") or "") for row in plan_rows}
    return reached & row_keys


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read Arco metadata {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Arco metadata must contain a JSON object: {path}")
    return payload


def _directory_files(directory: Path, suffix: str) -> list[tuple[Path, float]]:
    rows: list[tuple[Path, float]] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.name.casefold().endswith(suffix) or not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    modified = float(entry.stat(follow_symlinks=False).st_mtime)
                except OSError as exc:
                    raise RuntimeError(f"Could not read Arco file metadata {entry.path}: {exc}") from exc
                rows.append((Path(entry.path), modified))
    except (FileNotFoundError, NotADirectoryError):
        return []
    rows.sort(key=lambda item: item[0].name.casefold())
    return rows


def _read_json_entries(entries: list[tuple[Path, float]]) -> list[tuple[Path, float, dict[str, Any]]]:
    if not entries:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_JSON_READ_WORKERS, len(entries))) as executor:
        payloads = list(executor.map(lambda item: _read_json(item[0]), entries))
    return [(path, modified, payload) for (path, modified), payload in zip(entries, payloads)]


def _file_timestamp_text(value: float) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _first_text(container: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(container.get(key) or "").strip()
        if value:
            return value
    return ""


def _parsed_timestamp(parser, value: object) -> float | None:
    try:
        parsed = parser(value)
    except Exception:
        return None
    try:
        number = float(parsed)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _method_kind(method_type: object) -> str:
    normalized = str(method_type or "").strip().casefold().replace("_", " ")
    if normalized in {"", "none"}:
        # A plain dataset's sidecar says ``method_type: "None"``.
        return KIND_DATASET
    if normalized == "dfm":
        return KIND_DFM
    if normalized in {"bornhuetter ferguson", "bf"}:
        return KIND_BF
    if normalized in {"cape cod", "cc"}:
        return KIND_CC
    if normalized in {"result selection", "rs"}:
        return KIND_RS
    if "settlement" in normalized or normalized in {"berquist sherman sr", "b&s sr"}:
        return KIND_BS_SR
    if "case reserve" in normalized or normalized in {"berquist sherman cra", "b&s cra"}:
        return KIND_BS_CRA
    if normalized in {"bootstrap", "bst"}:
        return KIND_BOOTSTRAP
    if normalized in {"stochastic consolidation", "scon"}:
        return KIND_STOCHASTIC_CONSOLIDATION
    return str(method_type or "").strip() or KIND_DATASET


def _payload_is_triangle(payload: Mapping[str, Any]) -> bool:
    """A sidecar names its shape in ``data_format``; there is no numeric twin."""
    return str(payload.get("data_format") or "").strip().casefold() == "triangle"


def _kind_from_code(code: object, fallback: object = "") -> str:
    value = _safe_int(code, -1)
    return {
        0: KIND_DATASET,
        1: KIND_DFM,
        2: KIND_BF,
        3: KIND_CC,
        4: KIND_RS,
        6: KIND_BOOTSTRAP,
        7: KIND_STOCHASTIC_CONSOLIDATION,
        8: KIND_BS_SR,
        9: KIND_BS_CRA,
    }.get(value, _method_kind(fallback) if fallback else f"ResQ Method {value}")


def _method_modified(payload: Mapping[str, Any]) -> str:
    for key in ("method_metadata", "method_metadata"):
        metadata = payload.get(key)
        if isinstance(metadata, Mapping):
            value = _first_text(metadata, "last_modified", "last_modified", "modified_at", "modified", "updated_at")
            if value:
                return value
    return ""


def _sidecar_modified(payload: Mapping[str, Any]) -> str:
    if str(payload.get("source_kind") or "").strip().casefold() == "engine":
        source_modified = str(payload.get("source_modified") or "").strip()
        if source_modified:
            return source_modified
    return _first_text(payload, "updated_at", "last_modified", "modified_at", "modified", "updated")


def collect_arcrho_inventory(runtime: Mapping[str, Any], rc_dir: Path) -> list[dict[str, Any]]:
    """Read each ArcRho artifact folder once and return logical datasets/method outputs."""

    migration = runtime["migration"]
    parser = runtime["parse_timestamp"]
    method_entry_from_payload = runtime["method_entry"]
    sync_contract = runtime["sync_contract"]

    sidecar_entries = _read_json_entries(_directory_files(rc_dir / migration.DATASET_SIDECAR_DIR, ".json"))
    method_entries = _read_json_entries(_directory_files(rc_dir / migration.METHOD_DATA_DIR, ".json"))
    csv_entries = _directory_files(rc_dir / migration.DATASET_CACHE_DIR, ".csv")
    csv_by_name = {path.name.casefold(): (path, modified) for path, modified in csv_entries}
    sidecar_names = [
        (
            path,
            modified,
            payload,
            sync_contract.clean_name(payload.get("dataset_name") or migration._normalize_cached_dataset_name(path.stem)),
        )
        for path, modified, payload in sidecar_entries
    ]
    # Method Notes live in a method's output sidecar, not in its method JSON.
    sidecar_by_key = {sync_contract.logical_key(name): payload for _path, _modified, payload, name in sidecar_names}

    items: list[dict[str, Any]] = []
    method_keys: set[str] = set()
    for path, fallback_modified, payload in method_entries:
        entry = method_entry_from_payload(payload, path.name)
        if not isinstance(entry, Mapping):
            continue
        name = sync_contract.clean_name(entry.get("dataset_name"))
        if not name:
            continue
        kind = _method_kind(entry.get("method_type"))
        modified_text = _method_modified(payload)
        timestamp_source = "Method metadata"
        if not modified_text:
            modified_text = _file_timestamp_text(fallback_modified)
            timestamp_source = "File modified"
        can_export = kind in _EXPORTABLE_METHOD_KINDS
        reason = ""
        if not can_export:
            reason = (
                "Arco-to-ResQ write-back is not supported for Berquist Sherman or Bootstrap methods."
                if kind in {KIND_BS_SR, KIND_BS_CRA, KIND_BOOTSTRAP}
                else f"Arco-to-ResQ write-back is not supported for {kind}."
            )
        item = {
            "name": name,
            "kind": kind,
            "data_format": str(entry.get("data_format") or ""),
            "dataset_type": str(entry.get("dataset_type") or name),
            "modified": modified_text,
            "modified_timestamp": _parsed_timestamp(parser, modified_text),
            "timestamp_source": timestamp_source,
            "can_export_to_resq": can_export,
            "export_block_reason": reason,
            "export_scope_note": (
                "Only the fields supported by the existing ResQ writer are applied; "
                "see the sync documentation for method-specific limits."
                if can_export else ""
            ),
            "payload": payload,
            "method_name": sync_contract.clean_name(entry.get("method_name") or name),
            "method_file": path.name,
        }
        sidecar = sidecar_by_key.get(sync_contract.logical_key(name))
        if sidecar is not None:
            item["notes"] = str(sidecar.get("notes") or "")
            item["precedents"] = _dependency_names(sidecar.get("precedents"))
        items.append(item)
        method_keys.add(sync_contract.logical_key(name))

    sidecar_keys: set[str] = set()
    for path, fallback_modified, payload, name in sidecar_names:
        key = sync_contract.logical_key(name)
        if not key:
            continue
        sidecar_keys.add(key)
        if key in method_keys:
            continue
        kind = _method_kind(payload.get("method_type"))
        if kind == KIND_DATASET and bool(payload.get("calculated")):
            # A calculated dataset is recomputed by propagation on both sides
            # and nobody edits it directly, so there is nothing to reconcile.
            continue
        if kind == KIND_DATASET and str(payload.get("source_kind") or "").strip().casefold() == "engine":
            # An engine dataset is rebuilt from source data on both sides, so
            # neither side holds a hand-edited copy to reconcile either.
            continue
        modified_text = _sidecar_modified(payload)
        timestamp_source = "Dataset metadata"
        if not modified_text:
            modified_text = _file_timestamp_text(fallback_modified)
            timestamp_source = "File modified"
        csv_file = str(payload.get("csv_file") or "").strip()
        csv_available = bool(csv_file and csv_file.casefold() in csv_by_name)
        can_export = kind == KIND_DATASET and csv_available
        if kind != KIND_DATASET:
            block_reason = f"The {kind} method JSON is missing; only its output sidecar is present."
        elif not csv_available:
            block_reason = "The Arco dataset CSV cache is missing; open the dataset once to build it."
        else:
            block_reason = ""
        item = {
            "name": name,
            "kind": kind,
            "data_format": str(payload.get("data_format") or ""),
            "dataset_type": str(payload.get("dataset_type") or name),
            "modified": modified_text,
            "modified_timestamp": _parsed_timestamp(parser, modified_text),
            "timestamp_source": timestamp_source,
            "can_export_to_resq": can_export,
            "export_block_reason": block_reason,
            "payload": payload,
            "sidecar_file": path.name,
            "csv_file": csv_file,
        }
        if "notes" in payload:
            item["notes"] = str(payload.get("notes") or "")
        items.append(item)

    # A cache with no sidecar still belongs in the review inventory, but it is
    # deliberately not exportable because the sidecar owns its data contract.
    for path, fallback_modified in csv_entries:
        names = migration._cached_dataset_names_from_file(path.name)
        for raw_name in sorted(names, key=str.casefold):
            name = sync_contract.clean_name(raw_name)
            key = sync_contract.logical_key(name)
            if not key or key in sidecar_keys or key in method_keys:
                continue
            modified_text = _file_timestamp_text(fallback_modified)
            items.append({
                "name": name,
                "kind": KIND_DATASET,
                "data_format": "",
                "dataset_type": "",
                "modified": modified_text,
                "modified_timestamp": _parsed_timestamp(parser, modified_text),
                "timestamp_source": "File modified",
                "can_export_to_resq": False,
                "export_block_reason": "The Arco dataset sidecar is missing.",
                "payload": {},
                "csv_file": path.name,
            })
    return items


def _safe_attr(migration, item: object, name: str, default=None):
    return migration._safe_attr(item, name, default)


def _required_resq_attr(item: object, name: str, label: str):
    try:
        return getattr(item, name)
    except Exception as exc:
        raise RuntimeError(f"Could not read ResQ {label} {name}: {exc}") from exc


def _resq_modified_item(runtime: Mapping[str, Any], value: object) -> tuple[str, float | None]:
    text = str(runtime["migration"]._iso_or_text(value) or "").strip()
    return text, _parsed_timestamp(runtime["parse_timestamp"], text)


def _resq_object_timestamp(runtime: Mapping[str, Any], migration, value: object) -> tuple[str, float | None, str]:
    """Return the best database-owned timestamp without inventing a fallback."""

    modified = _safe_attr(migration, value, "Modified", "")
    modified_text, modified_timestamp = _resq_modified_item(runtime, modified)
    if modified_timestamp is not None:
        return modified_text, modified_timestamp, "ResQ Modified"
    created = _safe_attr(migration, value, "Created", "")
    created_text, created_timestamp = _resq_modified_item(runtime, created)
    if created_timestamp is not None:
        # Created is useful context for the required two-column display, but it
        # is not a last-modified timestamp and must never decide sync direction.
        return created_text, None, "ResQ Created (Modified unavailable)"
    return modified_text or created_text, None, "ResQ timestamp"


def _iter_resq_collection(collection: object, label: str):
    """Enumerate a COM collection completely or fail the whole preview."""

    try:
        count = int(getattr(collection, "Count"))
    except Exception as exc:
        raise RuntimeError(f"Could not read the ResQ {label} count: {exc}") from exc
    for index in range(1, count + 1):
        try:
            item = collection.Item(index)
        except Exception as exc:
            raise RuntimeError(f"Could not read ResQ {label} item {index}: {exc}") from exc
        if item is None:
            raise RuntimeError(f"ResQ {label} item {index} is unavailable.")
        yield item


def _resq_method_items(runtime: Mapping[str, Any], exporter) -> list[dict[str, Any]]:
    migration = runtime["migration"]
    exporter_module = runtime["exporter_module"]
    rows: list[dict[str, Any]] = []
    collections = (
        (KIND_DFM, exporter.reserving_class.DFMMethods),
        (KIND_BF, exporter.reserving_class.BFMethods),
        (KIND_CC, exporter.reserving_class.CapeCodMethods),
        (KIND_RS, exporter.reserving_class.ResultSelections),
    )
    for kind, factory in collections:
        try:
            collection = factory()
        except Exception as exc:
            raise RuntimeError(f"Could not enumerate ResQ {kind} methods: {exc}") from exc
        for method in _iter_resq_collection(collection, f"{kind} method"):
            output = _required_resq_attr(method, "OutputVector", f"{kind} method")
            raw_output_name = str(_required_resq_attr(output, "Name", f"{kind} output") or "")
            output_name = exporter_module._clean_label(raw_output_name)
            if not output_name:
                raise RuntimeError(f"A ResQ {kind} method has no readable output dataset name.")
            raw_method_name = str(_required_resq_attr(method, "Name", f"{kind} method") or "")
            dataset_type_obj = _required_resq_attr(output, "DatasetType", f"{kind} output")
            dataset_type = exporter_module._clean_label(
                _required_resq_attr(dataset_type_obj, "Name", f"{kind} output Dataset Type")
            ) or output_name
            known_type = bool(migration._is_known_dataset_type(dataset_type))
            modified_text, modified_timestamp, timestamp_source = _resq_object_timestamp(
                runtime, migration, output
            )
            rows.append({
                "name": output_name,
                "kind": kind,
                "data_format": "Vector",
                "modified": modified_text,
                "modified_timestamp": modified_timestamp,
                "timestamp_source": timestamp_source.replace("ResQ ", "ResQ output ", 1),
                "can_import_to_arcrho": known_type,
                "import_block_reason": (
                    "" if known_type else f"Dataset Type {dataset_type} is not configured in Arco."
                ),
                "can_receive_from_arcrho": kind in _EXPORTABLE_METHOD_KINDS,
                "receive_block_reason": "" if kind in _EXPORTABLE_METHOD_KINDS else f"Arco cannot write {kind} methods to ResQ.",
                "resq_collection": "vector",
                "resq_object_name": raw_output_name,
                "resq_method_name": raw_method_name or raw_output_name,
                "method_name": exporter_module._clean_label(raw_method_name or raw_output_name),
                "dataset_type": dataset_type,
                "resq_object": output,
                "resq_method": method,
            })
    return rows


def collect_resq_inventory(runtime: Mapping[str, Any], exporter) -> list[dict[str, Any]]:
    """Inventory ResQ datasets and supported method outputs with database timestamps."""

    migration = runtime["migration"]
    exporter_module = runtime["exporter_module"]
    sync_contract = runtime["sync_contract"]
    items = _resq_method_items(runtime, exporter)
    method_keys = {sync_contract.logical_key(item["name"]) for item in items}

    collections = (
        ("triangle", exporter.reserving_class.Triangles),
        ("vector", exporter.reserving_class.Vectors),
    )
    for collection_kind, factory in collections:
        try:
            collection = factory()
        except Exception as exc:
            raise RuntimeError(f"Could not enumerate ResQ {collection_kind} datasets: {exc}") from exc
        for obj in _iter_resq_collection(collection, collection_kind):
            raw_name = str(_required_resq_attr(obj, "Name", f"{collection_kind} dataset") or "")
            name = exporter_module._clean_label(raw_name)
            if not name:
                raise RuntimeError(f"A ResQ {collection_kind} dataset has no readable name.")
            if sync_contract.logical_key(name) in method_keys:
                continue
            method_code = _safe_int(
                _required_resq_attr(obj, "MethodType", f"{collection_kind} dataset"),
                -1,
            )
            kind = _kind_from_code(method_code)
            resq_method_name = raw_name
            resq_method = None
            if kind in {KIND_BS_SR, KIND_BS_CRA}:
                bs_entry = migration._find_berquist_sherman_for_triangle(
                    exporter.reserving_class,
                    raw_name,
                    method_code,
                )
                if bs_entry is not None:
                    _variant, resq_method = bs_entry
            elif kind == KIND_BOOTSTRAP:
                resq_method = migration._find_bootstrap_for_vector(exporter.reserving_class, raw_name)
            elif kind == KIND_STOCHASTIC_CONSOLIDATION:
                resq_method = migration._find_stochastic_consolidation_for_vector(
                    exporter.reserving_class, raw_name
                )
            if resq_method is not None:
                resq_method_name = exporter_module._clean_label(
                    _required_resq_attr(resq_method, "Name", f"{kind} method")
                )
            modified_text, modified_timestamp, timestamp_source = _resq_object_timestamp(
                runtime, migration, obj
            )
            dataset_type_obj = _required_resq_attr(obj, "DatasetType", f"{collection_kind} dataset")
            dataset_type = exporter_module._clean_label(
                _required_resq_attr(dataset_type_obj, "Name", f"{collection_kind} Dataset Type")
            ) or name
            known_type = bool(migration._is_known_dataset_type(dataset_type))
            calculated = bool(_required_resq_attr(obj, "Calculated", f"{collection_kind} dataset"))
            if kind == KIND_DATASET and migration._is_unreviewed_dataset(name, dataset_type):
                # Calculated in ArcRho's own dataset-types library, or generated
                # by the Engine: both sides rebuild it, so the row would only
                # ever report rebuild times. ResQ's Calculated flag does not
                # decide this: a type ResQ derives but ArcRho lists as an input
                # is an editable input in ArcRho and stays in the review. The
                # import still carries every such dataset, ticked or not.
                continue
            import_supported = (
                (kind == KIND_DATASET or kind in _OUTPUT_LOOKUP_METHOD_KINDS)
                and known_type
                and (kind not in _OUTPUT_LOOKUP_METHOD_KINDS or bool(resq_method and resq_method_name))
            )
            if kind in {KIND_DFM, KIND_BF, KIND_CC, KIND_RS}:
                # A method-coded output with no matching method object is unsafe
                # to import as a complete method.
                import_supported = False
                import_reason = f"The matching {kind} method object was not found in ResQ."
            elif kind in _OUTPUT_LOOKUP_METHOD_KINDS and resq_method is None:
                import_reason = f"The matching {kind} method object was not found in ResQ."
            elif kind in _OUTPUT_LOOKUP_METHOD_KINDS and not resq_method_name:
                import_reason = f"The matching {kind} method has no stable name in ResQ."
            elif not known_type:
                import_reason = f"Dataset Type {dataset_type} is not configured in Arco."
            elif kind != KIND_DATASET and kind not in _OUTPUT_LOOKUP_METHOD_KINDS:
                import_reason = f"ResQ-to-Arco import is not supported for {kind}."
            else:
                import_reason = ""
            can_receive = kind == KIND_DATASET
            receive_reason = ""
            if kind in _OUTPUT_LOOKUP_METHOD_KINDS:
                can_receive = False
                receive_reason = f"Arco-to-ResQ write-back is not supported for {kind}."
            elif kind == KIND_DATASET and calculated:
                # ResQ derives this one from its own formula and would only
                # recompute over whatever ArcRho wrote.
                can_receive = False
                receive_reason = "ResQ computes this dataset from its own formula, so Arco values cannot be written to it."
            items.append({
                "name": name,
                "kind": kind,
                "data_format": "Triangle" if collection_kind == "triangle" else "Vector",
                "modified": modified_text,
                "modified_timestamp": modified_timestamp,
                "timestamp_source": timestamp_source,
                "can_import_to_arcrho": import_supported,
                "import_block_reason": import_reason,
                "can_receive_from_arcrho": can_receive,
                "receive_block_reason": receive_reason,
                "resq_collection": collection_kind,
                "resq_object_name": raw_name,
                "resq_method_name": resq_method_name,
                "dataset_type": dataset_type,
                "calculated": calculated,
                "resq_object": obj,
                "resq_method": resq_method,
            })
    return items


def _timestamp_cell(item: Mapping[str, Any]) -> str:
    """Every review row gets an explicit timestamp value for each side.

    Both sides are shown in this machine's local time, the form ResQ's own
    windows and the ArcRho method list use; the comparison itself runs on the
    epoch seconds and never on this text.
    """

    value = str(item.get("modified") or "").strip()
    shown = format_display_timestamp(value, default=value)
    source = str(item.get("timestamp_source") or "").strip()
    if item.get("modified_timestamp") is None:
        if value and source.startswith("ResQ Created"):
            return f"Unknown Modified; Created {shown}"
        return "Unknown"
    return f"{shown} ({source})" if source == "File modified" else shown


def _direction_label(direction: object) -> str:
    normalized = str(direction or "")
    if normalized == "arcrho_to_resq":
        return "Arco -> ResQ"
    if normalized == "resq_to_arcrho":
        return "ResQ -> Arco"
    return ""


def _direction_payload(direction: Mapping[str, Any]) -> dict[str, Any]:
    """The reserving class's direction and the two timestamps that decided it, display-ready."""

    def shown(value: object) -> str:
        if value is None:
            return "Unknown"
        return format_display_timestamp(datetime.fromtimestamp(float(value), timezone.utc).isoformat())

    return {
        "action": str(direction.get("direction") or ""),
        "label": _direction_label(direction.get("direction")),
        "arcrho_timestamp": shown(direction.get("arcrho_timestamp")),
        "resq_timestamp": shown(direction.get("resq_timestamp")),
    }


def _resq_credentials(runtime: Mapping[str, Any]) -> Mapping[str, str]:
    """The ResQ account this session connects with.

    The host supplies it through ``build_runtime``. Without one, the migration
    module's own constants apply, which with empty user and password means the
    process's Windows identity -- right for a person running the migration
    directly, wrong for a Bridge worker, whose identity is whichever user's
    session claimed the request.
    """

    credentials = runtime.get("resq_credentials")
    if credentials:
        return credentials
    migration = runtime["migration"]
    return {
        "connection_name": migration.CONNECTION_NAME,
        "user_name": migration.USER_NAME,
        "password": migration.PASSWORD,
    }


def _new_exporter(runtime: Mapping[str, Any], project_name: str, rc_path: str, server_root: Path):
    migration = runtime["migration"]
    exporter_module = runtime["exporter_module"]
    credentials = _resq_credentials(runtime)
    return exporter_module.ResQReservingClassExporter(
        migration,
        arcrho_project_name=project_name,
        rc_path=rc_path,
        server_root=server_root,
        resq_project_name=project_name,
        connection_name=credentials["connection_name"],
        resq_user_name=credentials["user_name"],
        resq_password=credentials["password"],
        progress_callback=None,
    )


def _plan_context(runtime: Mapping[str, Any], project_name: str, rc_path: str, server_root: Path, exporter=None):
    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    rc_dir = migration.PROJECT_DATA_DIR / migration._encode_rc_folder(rc_path)
    local = collect_arcrho_inventory(runtime, rc_dir)
    owns_exporter = exporter is None
    session = exporter or _new_exporter(runtime, project_name, rc_path, server_root)
    if owns_exporter:
        session.connect()
    try:
        remote = collect_resq_inventory(runtime, session)
    finally:
        if owns_exporter:
            session.disconnect()
    connection_name = _resq_credentials(runtime)["connection_name"]
    state_path = sync_contract.sync_state_path(server_root, project_name, rc_path, connection_name)
    state = sync_contract.read_sync_state(state_path, project_name, rc_path, connection_name)
    plan = sync_contract.build_sync_plan(local, remote, state)
    return {
        "rc_dir": rc_dir,
        "arcrho": local,
        "resq": remote,
        "state": state,
        "state_path": state_path,
        "plan": plan,
        "direction": sync_contract.plan_direction(plan),
    }


_WRITTEN_COUNT_FIELDS = {
    KIND_DATASET: "datasets_written",
    KIND_DFM: "dfms_written",
    KIND_BF: "bfs_written",
    KIND_CC: "ccs_written",
    KIND_RS: "result_selections_written",
    KIND_BS_CRA: "bs_cras_written",
}
OUTCOME_WRITTEN = "written"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"


def _exporter_snapshot(exporter) -> dict[str, Any]:
    before = dict(exporter.counts)
    before["_skipped"] = dict(exporter.skipped)
    before["_written_details"] = len(_written_details(exporter))
    return before


def _written_details(exporter) -> list:
    details = getattr(exporter, "written_details", None)
    return details if isinstance(details, list) else []


def _created_count(exporter) -> int:
    """How many methods the exporter has created in ResQ so far."""
    return int(exporter.counts.get("methods_created") or 0)


def _created_since(exporter, before: Mapping[str, Any]) -> bool:
    return _created_count(exporter) > int(before.get("methods_created") or 0)


def _export_result_delta(exporter, before: Mapping[str, Any], count_field: str) -> tuple[str, str]:
    """What the exporter did since ``before`` -- written, skipped, or failed -- and why."""

    before_errors = int(before.get("errors") or 0)
    if int(exporter.counts.get("errors") or 0) > before_errors and exporter.error_details:
        return OUTCOME_FAILED, str(exporter.error_details[-1].get("message") or "ResQ write failed.")
    skipped_before = before.get("_skipped") if isinstance(before.get("_skipped"), Mapping) else {}
    for reason, count in exporter.skipped.items():
        if int(count or 0) > int(skipped_before.get(reason) or 0):
            detail = exporter.skip_details[-1] if exporter.skip_details else {}
            return OUTCOME_SKIPPED, str(detail.get("message") or str(reason).replace("_", " "))
    if count_field and int(exporter.counts.get(count_field) or 0) > int(before.get(count_field) or 0):
        # A writer that changed more than values -- a DFM's rows, input or
        # lengths -- says what, and the results window shows it. A method the
        # export created says so instead, with anything else it had to create.
        verb = "Created in ResQ" if _created_since(exporter, before) else "Written to ResQ"
        details = _written_details(exporter)
        if len(details) > int(before.get("_written_details") or 0):
            message = str(details[-1].get("message") or "").strip()
            if message:
                return OUTCOME_WRITTEN, f"{verb}: {message}."
        return OUTCOME_WRITTEN, f"{verb}."
    return OUTCOME_FAILED, "ResQ did not report the item as written."


def _writer_entry(item: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """The entry a method writer takes: name, payload, and the sidecar notes when readable."""

    entry = {
        "name": str(item.get("method_name") or row.get("name") or ""),
        "payload": item.get("payload") or {},
    }
    if "notes" in item:
        entry["notes"] = item["notes"]
    return entry


def _export_one_to_resq(exporter, row: Mapping[str, Any]) -> tuple[bool, str]:
    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    kind = str(row.get("kind") or KIND_DATASET)
    before = _exporter_snapshot(exporter)
    if kind == KIND_DATASET:
        expected_values = _preflight_dataset_export(exporter, row)
        payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
        is_triangle = _payload_is_triangle(payload)
        target = exporter._find_triangle(str(row.get("name") or "")) if is_triangle else None
        if target is not None:
            # The general exporter historically tolerates ClearData failures.
            # Selective sync must fail closed because otherwise ArcRho blanks or
            # a shorter triangle could leave stale ResQ cells and be baselined.
            try:
                target.ClearData()
            except Exception as exc:
                raise RuntimeError(
                    "ResQ could not clear the target triangle before synchronization."
                ) from exc
        exporter.export_datasets([payload])
        _verify_dataset_export(exporter, row, expected_values)
    else:
        _preflight_method_export(exporter, row)
        entry = _writer_entry(item, row)
        if kind == KIND_DFM:
            exporter.export_dfms([entry])
        elif kind == KIND_BF:
            exporter.export_bfs([entry])
        elif kind == KIND_CC:
            exporter.export_ccs([entry])
        elif kind == KIND_RS:
            existing = exporter._find_method_by_output(
                exporter.reserving_class.ResultSelections(), str(row.get("name") or "")
            )
            if existing is not None:
                try:
                    existing.ClearOverriddenUltimates()
                except Exception as exc:
                    raise RuntimeError(
                        "ResQ could not clear existing Result Selection ultimate overrides."
                    ) from exc
            exporter.export_result_selections([entry])
        else:
            return False, f"Arco-to-ResQ write-back is not supported for {kind}."
        _verify_method_export(exporter, row)
    outcome, message = _export_result_delta(exporter, before, _WRITTEN_COUNT_FIELDS.get(kind, ""))
    return outcome == OUTCOME_WRITTEN, message


# The export phase reports each item as one of these.
EXPORT_OUTCOME_EXPORTED = "exported"
EXPORT_OUTCOME_SAVED = "saved"
_EXPORT_PROGRESS_STATUS = {
    EXPORT_OUTCOME_EXPORTED: "success",
    EXPORT_OUTCOME_SAVED: "success",
    OUTCOME_SKIPPED: "skipped",
    OUTCOME_FAILED: "error",
}


def _export_rows(runtime: Mapping[str, Any], inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ArcRho items an export pushes, as rows the dependency walk can order.

    Calculated and engine datasets never reach the inventory; Bootstrap and
    Stochastic Consolidation are left out here because ResQ has no write path
    for them yet.
    """

    sync_contract = runtime["sync_contract"]
    rows: list[dict[str, Any]] = []
    for item in inventory:
        kind = str(item.get("kind") or KIND_DATASET)
        if kind in {KIND_BOOTSTRAP, KIND_STOCHASTIC_CONSOLIDATION}:
            continue
        key = sync_contract.logical_key(item.get("name"))
        rows.append({"id": key, "key": key, "kind": kind, "name": str(item.get("name") or ""), "arcrho": item})
    return rows


def _push_row_to_resq(exporter, row: Mapping[str, Any]) -> tuple[str, str]:
    """Write one export row and say what became of it: exported, saved, skipped, or failed.

    Input datasets, DFMs, BFs, Result Selections, and B&S Case Reserve
    Adequacy methods go through the exporter's writers; every other supported method
    has its Notes written and is then saved, so ResQ recalculates it from the
    inputs written before it. Notes reach ResQ for every kind either way.
    A DFM, BF or Result Selection ResQ does not hold is created by its writer
    when the exporter was told to (``create_missing_methods``), and its row
    then reads "Created in ResQ". There is no preflight and no read-back: an
    export is a push, not a reconciliation.
    """

    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    kind = str(row.get("kind") or KIND_DATASET)
    before = _exporter_snapshot(exporter)
    if kind in _SAVE_ONLY_METHOD_CODES:
        exporter.save_method(
            _SAVE_ONLY_METHOD_CODES[kind],
            str(row.get("name") or ""),
            _writer_entry(item, row),
        )
        outcome, message = _export_result_delta(exporter, before, "methods_saved")
        return (EXPORT_OUTCOME_SAVED if outcome == OUTCOME_WRITTEN else outcome), message
    if kind == KIND_BS_CRA:
        # Offered for export ahead of the sync's own support, like the save-only kinds.
        exporter.export_bs_cras([_writer_entry(item, row)])
        outcome, message = _export_result_delta(exporter, before, _WRITTEN_COUNT_FIELDS[kind])
        return (EXPORT_OUTCOME_EXPORTED if outcome == OUTCOME_WRITTEN else outcome), message
    reason = str(item.get("export_block_reason") or "")
    if reason:
        return OUTCOME_SKIPPED, reason
    if kind == KIND_DATASET:
        exporter.export_datasets([item.get("payload") or {}])
    elif kind == KIND_DFM:
        exporter.export_dfms([_writer_entry(item, row)])
    elif kind == KIND_BF:
        exporter.export_bfs([_writer_entry(item, row)])
    elif kind == KIND_RS:
        exporter.export_result_selections([_writer_entry(item, row)])
    else:
        return OUTCOME_SKIPPED, f"{kind} methods are not exported."
    outcome, message = _export_result_delta(exporter, before, _WRITTEN_COUNT_FIELDS.get(kind, ""))
    return (EXPORT_OUTCOME_EXPORTED if outcome == OUTCOME_WRITTEN else outcome), message


def _dataset_export_values(exporter, row: Mapping[str, Any]) -> list[list[float | None]]:
    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    csv_file = str(payload.get("csv_file") or "").strip()
    csv_path = (
        exporter.server_root
        / "projects"
        / exporter.arcrho_project_name
        / "data"
        / exporter.migration._encode_rc_folder(exporter.rc_path)
        / exporter.migration.DATASET_CACHE_DIR
        / csv_file
    )
    if not csv_file or not csv_path.is_file():
        raise RuntimeError("The Arco dataset CSV cache is missing.")
    values: list[list[float | None]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for raw_row in csv.reader(stream):
            row_values: list[float | None] = []
            for raw in raw_row:
                text = str(raw or "").strip()
                row_values.append(float(text) if text else None)
            values.append(row_values)
    return values


def _preflight_dataset_export(exporter, row: Mapping[str, Any]) -> list[list[float | None]]:
    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    values = _dataset_export_values(exporter, row)
    is_triangle = _payload_is_triangle(payload)
    if is_triangle:
        return values
    flat = [source[0] if source else None for source in values]
    if any(value is None for value in flat):
        raise RuntimeError(
            "Vector write-back is blocked because Arco contains blank values and "
            "the ResQ COM API has no verified blank-cell writer."
        )
    target = exporter._find_vector(str(row.get("name") or ""))
    if target is not None and int(getattr(target, "Count")) != len(flat):
        raise RuntimeError(
            f"Vector length mismatch: Arco has {len(flat)} values; ResQ has {int(getattr(target, 'Count'))}."
        )
    return values


def _verify_notes(exporter, target, item: Mapping[str, Any], label: str) -> None:
    """Read ResQ Notes back when the ArcRho row carried notes to write."""

    if "notes" not in item:
        return
    if str(getattr(target, "Notes", "") or "") != exporter._resq_notes_text(item["notes"]):
        raise RuntimeError(f"ResQ {label} notes verification failed.")


def _verify_dataset_export(
    exporter,
    row: Mapping[str, Any],
    values: list[list[float | None]],
) -> None:
    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    is_triangle = _payload_is_triangle(payload)
    name = str(row.get("name") or "")
    if is_triangle:
        target = exporter._find_triangle(name)
        if target is None:
            raise RuntimeError("ResQ did not expose the triangle after the write.")
        origin_count = int(getattr(target, "OriginCount"))
        if origin_count != len(values):
            raise RuntimeError(
                f"ResQ triangle row count did not match Arco after the write "
                f"({origin_count} versus {len(values)})."
            )
        for origin_index in range(1, origin_count + 1):
            source_row = values[origin_index - 1]
            width = exporter._triangle_row_width(target, origin_index)
            if width < len(source_row):
                trailing = source_row[width:]
                if any(value is not None for value in trailing):
                    raise RuntimeError("ResQ triangle truncated nonblank Arco development values.")
            for development_index in range(1, width + 1):
                expected = source_row[development_index - 1] if development_index <= len(source_row) else None
                if expected is None:
                    try:
                        actual_blank = target.ValuesByIndex(origin_index, development_index)
                    except Exception:
                        # ResQ commonly exposes cleared cells as an unreadable
                        # empty value. ClearData already succeeded before write.
                        continue
                    if actual_blank is not None and abs(float(actual_blank)) > 1e-9:
                        raise RuntimeError(
                            f"ResQ triangle retained a value in Arco blank cell "
                            f"({origin_index}, {development_index})."
                        )
                    continue
                actual = float(target.ValuesByIndex(origin_index, development_index))
                if abs(actual - expected) > 1e-9:
                    raise RuntimeError(
                        f"ResQ triangle verification failed at ({origin_index}, {development_index})."
                    )
        _verify_notes(exporter, target, item, "triangle")
        return

    flat = [source[0] for source in values]
    target = exporter._find_vector(name)
    if target is None or int(getattr(target, "Count")) != len(flat):
        raise RuntimeError("ResQ vector length did not match Arco after the write.")
    for index, expected in enumerate(flat, start=1):
        actual = float(target.ValuesByIndex(index))
        if expected is None or abs(actual - expected) > 1e-9:
            raise RuntimeError(f"ResQ vector verification failed at position {index}.")
    _verify_notes(exporter, target, item, "vector")


def _preflight_method_export(
    exporter,
    row: Mapping[str, Any],
    *,
    satisfied: Callable[[str], bool] | None = None,
) -> None:
    """Block known lossy dependency failures before mutating a ResQ method.

    ``satisfied`` names datasets an earlier row of the same batch will have
    created by the time this row is written; the strict check without it runs
    again immediately before the write.
    """

    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    kind = str(row.get("kind") or "")
    method_tab = payload.get("method_tab") if isinstance(payload.get("method_tab"), Mapping) else {}

    def require(name: object, finder, role: str) -> None:
        clean = str(name or "").strip()
        if not clean or finder(clean) is not None:
            return
        if satisfied is not None and satisfied(clean):
            return
        raise RuntimeError(f"Required {role} dataset is not present in ResQ: {clean}")

    def require_present(name: object, finder, role: str) -> None:
        clean = str(name or "").strip()
        if not clean:
            raise RuntimeError(
                f"The Arco {role} link is blank; ResQ link clearing is not supported safely."
            )
        require(clean, finder, role)

    def find_triangle_or_vector(name: str):
        triangle = exporter._find_triangle(name)
        return triangle if triangle is not None else exporter._find_vector(name)

    if kind == KIND_DFM:
        details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
        method_name = str(details.get("name") or item.get("method_name") or row.get("name") or "").strip()
        target = exporter._find_in("dfm_methods", exporter.reserving_class.DFMMethods, method_name)
        require_present(details.get("input_triangle"), exporter._find_triangle, "DFM input triangle")
        if target is None:
            return
        expected_input = _name_key(details.get("input_triangle"))
        actual_input = _name_key(getattr(getattr(target, "InputTriangle"), "Name"))
        if actual_input != expected_input:
            raise RuntimeError(
                "Existing ResQ DFM input triangle differs from Arco; safe retargeting is not supported."
            )
        expected_origin_length = int(details.get("origin_length") or 0)
        expected_development_length = int(details.get("development_length") or 0)
        if expected_origin_length and int(getattr(target, "OriginLength")) != expected_origin_length:
            raise RuntimeError("Existing ResQ DFM origin length differs from Arco.")
        if expected_development_length and int(getattr(target, "DevelopmentLength")) != expected_development_length:
            raise RuntimeError("Existing ResQ DFM development length differs from Arco.")
        ratios_tab = payload.get("ratios_tab") if isinstance(payload.get("ratios_tab"), Mapping) else {}
        ratio_triangle = ratios_tab.get("ratio_triangle") if isinstance(ratios_tab.get("ratio_triangle"), Mapping) else {}
        excluded = ratio_triangle.get("excluded") if isinstance(ratio_triangle.get("excluded"), list) else []
        origin_count = int(getattr(target, "OriginCount", 0) or 0)
        for origin_index, source_row in enumerate(excluded, start=1):
            if not isinstance(source_row, list):
                continue
            meaningful = [
                index for index, value in enumerate(source_row, start=1)
                if value in (0, 1, False, True, "0", "1")
            ]
            if not meaningful:
                continue
            if origin_index > origin_count:
                raise RuntimeError("ResQ DFM has fewer origin rows than the Arco exclusion pattern.")
            ratio_count = max(int(target.DevelopmentCount(origin_index)) - 1, 0)
            if max(meaningful) > ratio_count:
                raise RuntimeError("ResQ DFM has fewer ratio columns than the Arco exclusion pattern.")

        averages = ratios_tab.get("average_formulas") if isinstance(ratios_tab.get("average_formulas"), Mapping) else {}
        labels = averages.get("label") if isinstance(averages.get("label"), list) else []
        selected = averages.get("selected") if isinstance(averages.get("selected"), list) else []
        available = exporter._average_formula_display_indexes(target)
        columns = exporter._dfm_development_column_count(target)
        for development_index in range(1, columns + 1):
            selected_label = ""
            for row_index, source_row in enumerate(selected):
                if row_index < len(labels) and isinstance(source_row, list) and development_index - 1 < len(source_row):
                    if source_row[development_index - 1] in (1, True, "1"):
                        selected_label = str(labels[row_index])
                        break
            if selected_label and selected_label not in available:
                raise RuntimeError(f"ResQ DFM has no selected-average label: {selected_label}")
        for row_index, source_row in enumerate(selected):
            if not isinstance(source_row, list):
                continue
            if any(value in (1, True, "1") for value in source_row[columns:]):
                raise RuntimeError("ResQ DFM has fewer selection columns than Arco.")

        values = averages.get("values") if isinstance(averages.get("values"), list) else []
        user_row = exporter._user_entry_payload_row_index(averages)
        if user_row is not None and user_row < len(values) and isinstance(values[user_row], list):
            positive_indexes = []
            for index, value in enumerate(values[user_row], start=1):
                try:
                    positive = not isinstance(value, bool) and float(value) > 0
                except (TypeError, ValueError):
                    positive = False
                if positive:
                    positive_indexes.append(index)
            if positive_indexes:
                has_user_entry = any(
                    str(label or "").strip().casefold().startswith("user entry")
                    for label in available
                )
                if not has_user_entry:
                    raise RuntimeError("ResQ DFM has no User Entry average row.")
                if max(positive_indexes) > columns:
                    raise RuntimeError("ResQ DFM has fewer User Entry columns than Arco.")
    elif kind == KIND_BF:
        require_present(method_tab.get("latest_dataset"), find_triangle_or_vector, "latest")
        require_present(method_tab.get("dfm_dataset"), exporter._find_vector, "percentage-developed")
        priors = method_tab.get("prior_datasets") if isinstance(method_tab.get("prior_datasets"), list) else []
        if len(priors) > 1:
            raise RuntimeError("ResQ write-back supports only one BF prior dataset; this method has multiple priors.")
        prior = priors[0] if priors and isinstance(priors[0], Mapping) else {}
        require_present(prior.get("name"), exporter._find_vector, "prior")
    elif kind == KIND_CC:
        require_present(method_tab.get("exposure_dataset"), exporter._find_vector, "exposure")
        require_present(method_tab.get("latest_dataset"), exporter._find_triangle, "latest")
        require_present(method_tab.get("prior_ultimate_dataset"), exporter._find_vector, "prior-ultimate")
    elif kind == KIND_RS:
        loaded = method_tab.get("loaded_datasets") if isinstance(method_tab.get("loaded_datasets"), list) else []
        desired = {
            _name_key(source.get("name"))
            for source in loaded
            if isinstance(source, Mapping) and str(source.get("name") or "").strip()
        }
        for source in loaded:
            if isinstance(source, Mapping):
                require(source.get("name"), exporter._find_dataset, "Result Selection source")
        target = exporter._find_method_by_output(
            exporter.reserving_class.ResultSelections(), str(row.get("name") or "")
        )
        if target is not None:
            # The comparison runs on the shared key so a stray double space in
            # ResQ does not read as a source ArcRho would have to remove; the
            # ResQ spelling is kept only to name a genuine extra.
            existing: dict[str, str] = {}
            count = int(getattr(target, "DatasetCount", 0) or 0)
            for index in range(1, count + 1):
                resq_name = str(target.Dataset(index).Name or "").strip()
                existing.setdefault(_name_key(resq_name), resq_name)
            extras = sorted(name for key, name in existing.items() if key not in desired)
            if extras:
                raise RuntimeError(
                    "ResQ Result Selection has source datasets Arco cannot remove: "
                    + ", ".join(extras)
                )
            origin_count = int(getattr(target, "OriginCount", 0) or 0)
            for source in loaded:
                if not isinstance(source, Mapping):
                    continue
                weights = source.get("weights") if isinstance(source.get("weights"), list) else []
                if len(weights) > origin_count:
                    raise RuntimeError(
                        "Arco Result Selection has more weights than the ResQ origin count."
                    )
            overrides = method_tab.get("ultimate_overrides")
            if isinstance(overrides, list) and len(overrides) > origin_count:
                raise RuntimeError(
                    "Arco Result Selection has more ultimate overrides than the ResQ origin count."
                )


def _verify_method_export(exporter, row: Mapping[str, Any]) -> None:
    """Read back every method field the ArcRho-to-ResQ writer claims to apply."""

    item = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
    payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
    kind = str(row.get("kind") or "")
    method_tab = payload.get("method_tab") if isinstance(payload.get("method_tab"), Mapping) else {}

    def key(value: object) -> str:
        return _name_key(value)

    def assert_link(actual: object, expected: object, role: str) -> None:
        actual_name = key(getattr(actual, "Name"))
        if actual_name != key(expected):
            raise RuntimeError(f"ResQ {role} link did not match Arco after the write.")

    if kind == KIND_DFM:
        details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
        name = str(details.get("name") or item.get("method_name") or row.get("name") or "").strip()
        target = exporter._find_in("dfm_methods", exporter.reserving_class.DFMMethods, name)
        if target is None:
            raise RuntimeError("ResQ did not expose the DFM after the write.")
        _preflight_method_export(exporter, row)
        ratios_tab = payload.get("ratios_tab") if isinstance(payload.get("ratios_tab"), Mapping) else {}
        ratio_triangle = ratios_tab.get("ratio_triangle") if isinstance(ratios_tab.get("ratio_triangle"), Mapping) else {}
        excluded = ratio_triangle.get("excluded") if isinstance(ratio_triangle.get("excluded"), list) else []
        for origin_index, source_row in enumerate(excluded, start=1):
            if not isinstance(source_row, list):
                continue
            ratio_count = max(int(target.DevelopmentCount(origin_index)) - 1, 0)
            for development_index, expected in enumerate(source_row[:ratio_count], start=1):
                if expected not in (0, 1, False, True, "0", "1"):
                    continue
                actual = 1 if int(target.ExcludedRatios(origin_index, development_index)) == 1 else 0
                if actual != int(expected):
                    raise RuntimeError(
                        f"ResQ DFM exclusion verification failed at ({origin_index}, {development_index})."
                    )

        averages = ratios_tab.get("average_formulas") if isinstance(ratios_tab.get("average_formulas"), Mapping) else {}
        labels = averages.get("label") if isinstance(averages.get("label"), list) else []
        selected = averages.get("selected") if isinstance(averages.get("selected"), list) else []
        available = exporter._average_formula_display_indexes(target)
        columns = exporter._dfm_development_column_count(target)
        for development_index in range(1, columns + 1):
            expected_label = ""
            for row_index, source_row in enumerate(selected):
                if row_index < len(labels) and isinstance(source_row, list) and development_index - 1 < len(source_row):
                    if source_row[development_index - 1] in (1, True, "1"):
                        expected_label = str(labels[row_index])
                        break
            if expected_label:
                expected_index = int(available[expected_label])
                if int(target.SelectedRatios(DevIndex=development_index)) != expected_index:
                    raise RuntimeError(
                        f"ResQ DFM selected-average verification failed at column {development_index}."
                    )

        values = averages.get("values") if isinstance(averages.get("values"), list) else []
        # The last column is each row's "- Ult" tail factor, kept on the ResQ row.
        tail_index = columns - 1
        for row_index, label in enumerate(labels):
            source_row = values[row_index] if row_index < len(values) else None
            if tail_index < 0 or not isinstance(source_row, list) or tail_index >= len(source_row):
                continue
            expected_tail = _safe_float(source_row[tail_index])
            display_index = available.get(str(label))
            if expected_tail is None or expected_tail <= 0 or display_index is None:
                continue
            if abs(float(target.CustomAverages(int(display_index)).TailFactor) - expected_tail) > 1e-9:
                raise RuntimeError(f"ResQ DFM tail factor verification failed for average row {label}.")
        curves = payload.get("curves_tab") if isinstance(payload.get("curves_tab"), Mapping) else {}
        if curves:
            column_limit = 5 + int(getattr(target, "CurveUserValueColCount", 0) or 0)
            selected_estimates = curves.get("selected_estimates") if isinstance(curves.get("selected_estimates"), list) else []
            for development_index, expected in enumerate(selected_estimates[: max(columns - 1, 0)], start=1):
                number = _safe_float(expected)
                if number is None or not 1 <= int(number) <= column_limit:
                    continue
                if int(target.SelectedEstimates(development_index)) != int(number):
                    raise RuntimeError(
                        f"ResQ DFM selected-estimate verification failed at period {development_index}."
                    )
            tail_number = _safe_float(curves.get("selected_tail_factor"))
            if tail_number is not None and 1 <= int(tail_number) <= column_limit:
                if int(target.SelectedTailFactor) != int(tail_number):
                    raise RuntimeError("ResQ DFM selected tail factor verification failed.")
            future = _safe_float(curves.get("future_development_periods"))
            if future is not None and future >= 1 and int(target.FutureDevelopmentPeriods) != int(future):
                raise RuntimeError("ResQ DFM future development periods verification failed.")
        user_row = exporter._user_entry_payload_row_index(averages)
        if user_row is not None and user_row < len(values) and isinstance(values[user_row], list):
            user_indexes = [
                int(display_index)
                for label, display_index in available.items()
                if key(label).startswith("user entry")
            ]
            if user_indexes:
                user_index = user_indexes[0]
                for development_index, expected in enumerate(values[user_row][: max(columns - 1, 0)], start=1):
                    try:
                        expected_value = float(expected)
                    except (TypeError, ValueError):
                        continue
                    if expected_value <= 0:
                        continue
                    actual_value = float(target.AverageRatioValues(development_index, user_index))
                    if abs(actual_value - expected_value) > 1e-9:
                        raise RuntimeError(
                            f"ResQ DFM User Entry verification failed at column {development_index}."
                        )

        _verify_notes(exporter, target, item, "DFM")
        return

    if kind == KIND_BF:
        target = exporter._find_method_by_output(
            exporter.reserving_class.BFMethods(), str(row.get("name") or "")
        )
        if target is None:
            raise RuntimeError("ResQ did not expose the BF method after the write.")
        details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
        expected_origin_length = int(details.get("origin_length") or 0)
        if expected_origin_length and int(getattr(target, "OriginLength")) != expected_origin_length:
            raise RuntimeError("ResQ BF origin length did not match Arco after the write.")
        assert_link(getattr(target, "Latest"), method_tab.get("latest_dataset"), "BF latest")
        expected_latest = exporter._find_triangle(str(method_tab.get("latest_dataset") or ""))
        expected_latest_type = 0 if expected_latest is not None else 1
        if int(getattr(target, "LatestType")) != expected_latest_type:
            raise RuntimeError("ResQ BF latest data format did not match Arco after the write.")
        assert_link(getattr(target, "PercentageDeveloped"), method_tab.get("dfm_dataset"), "BF percentage-developed")
        expected_pd_type = method_tab.get("percentage_developed_type_code")
        expected_pd_type = 2 if expected_pd_type is None else int(expected_pd_type)
        if int(getattr(target, "PercentageDevelopedType")) != expected_pd_type:
            raise RuntimeError("ResQ BF percentage-developed type did not match Arco after the write.")
        priors = method_tab.get("prior_datasets") if isinstance(method_tab.get("prior_datasets"), list) else []
        prior = priors[0] if priors and isinstance(priors[0], Mapping) else {}
        assert_link(getattr(target, "Prior"), prior.get("name"), "BF prior")
        expected_prior_type = method_tab.get("prior_type_code")
        expected_prior_type = 0 if expected_prior_type is None else int(expected_prior_type)
        if int(getattr(target, "PriorType")) != expected_prior_type:
            raise RuntimeError("ResQ BF prior type did not match Arco after the write.")
        _verify_notes(exporter, target, item, "BF")
        return

    if kind == KIND_CC:
        target = exporter._find_method_by_output(
            exporter.reserving_class.CapeCodMethods(), str(row.get("name") or "")
        )
        if target is None:
            raise RuntimeError("ResQ did not expose the Cape Cod method after the write.")
        details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
        expected_origin_length = int(details.get("origin_length") or 0)
        if expected_origin_length and int(getattr(target, "OriginLength")) != expected_origin_length:
            raise RuntimeError("ResQ Cape Cod origin length did not match Arco after the write.")
        assert_link(getattr(target, "Exposure"), method_tab.get("exposure_dataset"), "Cape Cod exposure")
        assert_link(getattr(target, "Latest"), method_tab.get("latest_dataset"), "Cape Cod latest")
        if int(getattr(target, "LatestType")) != 0:
            raise RuntimeError("ResQ Cape Cod latest data format did not match Arco after the write.")
        assert_link(
            getattr(target, "PercentageDeveloped"),
            method_tab.get("prior_ultimate_dataset"),
            "Cape Cod prior-ultimate",
        )
        expected_pd_type = 1 if key(method_tab.get("prior_ultimate_mode")) == "pattern" else 2
        if int(getattr(target, "PercentageDevelopedType")) != expected_pd_type:
            raise RuntimeError(
                "ResQ Cape Cod prior-ultimate mode did not match Arco after the write."
            )
        for member, field in (
            ("AutoTrendFit", "auto_trend_fit"),
            ("DecayFactor", "decay_factor"),
            ("AltUltimateCalc", "alternative_ultimate_calculation"),
        ):
            expected = method_tab.get(field)
            if expected is not None and getattr(target, member) != expected:
                raise RuntimeError(f"ResQ Cape Cod {field} did not match Arco after the write.")
        if method_tab.get("trend_rate") is not None and not bool(method_tab.get("auto_trend_fit")):
            if abs(float(getattr(target, "TrendRate")) - float(method_tab["trend_rate"])) > 1e-9:
                raise RuntimeError("ResQ Cape Cod trend rate did not match Arco after the write.")
        _verify_notes(exporter, target, item, "Cape Cod")
        return

    if kind == KIND_RS:
        target = exporter._find_method_by_output(
            exporter.reserving_class.ResultSelections(), str(row.get("name") or "")
        )
        if target is None:
            raise RuntimeError("ResQ did not expose the Result Selection after the write.")
        details = payload.get("details_tab") if isinstance(payload.get("details_tab"), Mapping) else {}
        expected_origin_length = int(details.get("origin_length") or 0)
        if expected_origin_length and int(getattr(target, "OriginLength")) != expected_origin_length:
            raise RuntimeError("ResQ Result Selection origin length did not match Arco after the write.")
        loaded = method_tab.get("loaded_datasets") if isinstance(method_tab.get("loaded_datasets"), list) else []
        expected_names = [key(source.get("name")) for source in loaded if isinstance(source, Mapping)]
        actual_names = [key(target.Dataset(index).Name) for index in range(1, int(target.DatasetCount) + 1)]
        if set(actual_names) != set(expected_names):
            raise RuntimeError("ResQ Result Selection source datasets did not match Arco after the write.")
        origin_count = int(getattr(target, "OriginCount", 0) or 0)
        for source in loaded:
            if not isinstance(source, Mapping):
                continue
            source_key = key(source.get("name"))
            dataset_index = actual_names.index(source_key) + 1
            weights = source.get("weights") if isinstance(source.get("weights"), list) else []
            for origin_index, expected in enumerate(weights[:origin_count], start=1):
                expected_value = 0.0 if expected is None else float(expected)
                if abs(float(target.Weights(dataset_index, origin_index)) - expected_value) > 1e-9:
                    raise RuntimeError("ResQ Result Selection weight verification failed.")
        overrides = method_tab.get("ultimate_overrides") if isinstance(method_tab.get("ultimate_overrides"), list) else []
        rs_origin_length = int(getattr(target, "OriginLength", 0) or 0)
        for origin_index, expected in enumerate(overrides[:origin_count], start=1):
            overridden = bool(target.UltimateOverridden(origin_index))
            if expected is None:
                if overridden:
                    raise RuntimeError("ResQ Result Selection retained a cleared ultimate override.")
                continue
            if not overridden:
                raise RuntimeError("ResQ Result Selection did not retain an Arco ultimate override.")
            actual = float(target.Ultimates(origin_index, rs_origin_length))
            if abs(actual - float(expected)) > 1e-9:
                raise RuntimeError("ResQ Result Selection ultimate override verification failed.")
        _verify_notes(exporter, target, item, "Result Selection")


def _resq_import_target(row: Mapping[str, Any]) -> dict[str, Any]:
    item = row.get("resq") if isinstance(row.get("resq"), Mapping) else {}
    kind = str(row.get("kind") or KIND_DATASET)
    collection = str(item.get("resq_collection") or "")
    name = str(item.get("resq_object_name") or row.get("name") or "")
    method_name = str(item.get("resq_method_name") or "").strip()
    if collection not in {"triangle", "vector"}:
        raise ValueError(f"Unsupported ResQ collection for {row.get('name')}: {collection or '<missing>'}")
    return {
        "export_kind": collection,
        "names": [name],
        "include_dfm_methods": kind == KIND_DFM,
        "include_bf_methods": kind == KIND_BF,
        "include_cc_methods": kind == KIND_CC,
        "include_bootstrap_methods": kind == KIND_BOOTSTRAP,
        "include_stochastic_consolidations": kind == KIND_STOCHASTIC_CONSOLIDATION,
        "dfm_names": [str(item.get("resq_method_name") or "")] if kind == KIND_DFM else None,
        "method_names": [method_name] if kind != KIND_DATASET and method_name else [],
        "display_kind": kind,
    }


def _method_file_prefix(migration, kind: str) -> str:
    if kind == KIND_BS_SR:
        return migration.BS_SR_FILE_PREFIX
    if kind == KIND_BS_CRA:
        return migration.BS_CRA_FILE_PREFIX
    return _METHOD_FILE_PREFIXES.get(kind, "")


def _cleanup_sync_target_artifacts(
    runtime: Mapping[str, Any],
    rc_dir: Path,
    target: Mapping[str, Any],
) -> tuple[int, int]:
    """Delete only the selected logical group, leaving dependents for propagation."""

    migration = runtime["migration"]
    method_prefix = _method_file_prefix(migration, str(target.get("display_kind") or ""))
    return migration.cleanup_target_dataset_artifacts(
        rc_dir,
        dataset_names=list(target.get("names") or []),
        method_names=list(target.get("method_names") or []),
        match_method_dependencies=False,
        method_prefixes=[method_prefix] if method_prefix else [],
    )


def _snapshot_groups(runtime: Mapping[str, Any], rc_dir: Path, keys: set[str], backup_root: Path) -> dict[str, list[Path]]:
    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    groups: dict[str, list[Path]] = {}
    sidecars = _read_json_entries(_directory_files(rc_dir / migration.DATASET_SIDECAR_DIR, ".json"))
    for path, _modified, payload in sidecars:
        name = payload.get("dataset_name") or migration._normalize_cached_dataset_name(path.stem)
        key = sync_contract.logical_key(name)
        if key:
            groups.setdefault(key, []).append(path)
    methods = _read_json_entries(_directory_files(rc_dir / migration.METHOD_DATA_DIR, ".json"))
    for path, _modified, payload in methods:
        entry = runtime["method_entry"](payload, path.name)
        key = sync_contract.logical_key(entry.get("dataset_name")) if isinstance(entry, Mapping) else ""
        if key:
            groups.setdefault(key, []).append(path)
    for path, _modified in _directory_files(rc_dir / migration.DATASET_CACHE_DIR, ".csv"):
        for name in migration._cached_dataset_names_from_file(path.name):
            key = sync_contract.logical_key(name)
            if key:
                groups.setdefault(key, []).append(path)

    copied: dict[str, list[Path]] = {}
    for key in keys:
        paths = sorted(set(groups.get(key, [])), key=lambda path: str(path).casefold())
        for source in paths:
            relative = source.relative_to(rc_dir)
            target = backup_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.setdefault(key, []).append(relative)
    return copied


def _preflight_import_method_filename_collision(
    runtime: Mapping[str, Any],
    rc_dir: Path,
    row: Mapping[str, Any],
) -> None:
    """Fail before cleanup if the target method filename belongs to another output."""

    if str(row.get("kind") or KIND_DATASET) == KIND_DATASET:
        return
    target = _resq_import_target(row)
    method_names = [str(value).strip() for value in target.get("method_names") or [] if str(value).strip()]
    if not method_names:
        raise RuntimeError("The ResQ method has no stable method name for selective import.")
    prefix = _method_file_prefix(runtime["migration"], str(row.get("kind") or ""))
    if not prefix:
        return
    method_name = method_names[0]
    method_path = rc_dir / runtime["migration"].METHOD_DATA_DIR / (
        f"{prefix}{runtime['migration']._encode_name_part(method_name)}.json"
    )
    if not method_path.is_file():
        return
    payload = _read_json(method_path)
    entry = runtime["method_entry"](payload, method_path.name)
    existing_output = str(entry.get("dataset_name") or "").strip() if isinstance(entry, Mapping) else ""
    if not existing_output:
        raise RuntimeError(
            f"Existing target method file {method_path.name} has no readable output identity."
        )
    if runtime["sync_contract"].logical_key(existing_output) != str(row.get("key") or ""):
        raise RuntimeError(
            f"Method filename collision: {method_path.name} currently belongs to output "
            f"{existing_output!r}, not {row.get('name')!r}."
        )


def _restore_group(
    runtime: Mapping[str, Any],
    exporter,
    rc_dir: Path,
    row: Mapping[str, Any],
    backup_root: Path,
    backup_paths: Mapping[str, list[Path]],
) -> None:
    migration = runtime["migration"]
    target = _resq_import_target(row)
    _cleanup_sync_target_artifacts(runtime, rc_dir, target)
    key = str(row.get("key") or "")
    for relative in backup_paths.get(key, []):
        source = backup_root / relative
        destination = rc_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.restore.tmp")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _import_one_from_resq(
    runtime: Mapping[str, Any],
    exporter,
    rc_path: str,
    rc_dir: Path,
    row: Mapping[str, Any],
    progress_callback,
) -> tuple[bool, str]:
    migration = runtime["migration"]
    target = _resq_import_target(row)
    names = list(target["names"])
    _cleanup_sync_target_artifacts(runtime, rc_dir, target)
    progress_state = {"completed": 0, "total": 1, "skipped": 0, "count_methods": False}
    method_counts = {
        "dfms_written": 0,
        "bfs_written": 0,
        "ccs_written": 0,
        "result_selections_written": 0,
        "bssr_written": 0,
        "bscra_written": 0,
        "bootstraps_written": 0,
        "scons_written": 0,
    }
    if target["export_kind"] == "triangle":
        written, errors = migration.export_triangles_for_rc(
            exporter.reserving_class,
            rc_path,
            rc_dir,
            progress_callback=progress_callback,
            progress_state=progress_state,
            triangle_names=names,
            method_counts=method_counts,
            strict_extraction=True,
            verbose=False,
        )
    else:
        written, errors = migration.export_vectors_for_rc(
            exporter.reserving_class,
            rc_path,
            rc_dir,
            progress_callback=progress_callback,
            progress_state=progress_state,
            vector_names=names,
            include_dfm_methods=bool(target.get("include_dfm_methods")),
            include_bf_methods=bool(target.get("include_bf_methods")),
            include_cc_methods=bool(target.get("include_cc_methods")),
            include_bootstrap_methods=bool(target.get("include_bootstrap_methods")),
            include_stochastic_consolidations=bool(target.get("include_stochastic_consolidations")),
            dfm_names=target.get("dfm_names"),
            method_counts=method_counts,
            preserve_local_dfm_owned_state=False,
            strict_extraction=True,
            verbose=False,
        )
    if errors:
        details = progress_state.get("error_details") if isinstance(progress_state.get("error_details"), list) else []
        message = str(details[-1].get("message") or "ResQ import failed.") if details else "ResQ import failed."
        return False, message
    if int(progress_state.get("skipped") or 0) or written < 1:
        return False, "The canonical ResQ importer skipped this item."
    expected_count = {
        KIND_DFM: "dfms_written",
        KIND_BF: "bfs_written",
        KIND_CC: "ccs_written",
        KIND_RS: "result_selections_written",
        KIND_BS_SR: "bssr_written",
        KIND_BS_CRA: "bscra_written",
        KIND_BOOTSTRAP: "bootstraps_written",
        KIND_STOCHASTIC_CONSOLIDATION: "scons_written",
    }.get(str(row.get("kind") or ""))
    if expected_count and int(method_counts.get(expected_count) or 0) < 1:
        return False, f"The ResQ output was read, but its {row.get('kind')} method was not imported."
    return True, "Imported into Arco."


def _plan_by_id(plan: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id") or ""): row for row in plan if str(row.get("id") or "")}


def _selected_rows(plan: list[dict[str, Any]], selected_ids: list[str]) -> list[dict[str, Any]]:
    by_id = _plan_by_id(plan)
    rows = []
    seen: set[str] = set()
    for row_id in selected_ids:
        if row_id in seen:
            continue
        seen.add(row_id)
        row = by_id.get(row_id)
        if row is not None and not row.get("disabled") and row.get("action"):
            rows.append(row)
    return rows


def _reviewed_signature(sync_contract, reviewed: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Return the observation a row must still match, or None when it has none.

    A row echoed back from the review table carries the ``signature`` it was
    shown with. A plan row this session observed itself is its own
    observation, so the write phase can recheck the rows it selected from an
    earlier plan even though those rows never left the process and were never
    given a separate ``signature`` field.
    """

    signature = reviewed.get("signature")
    if isinstance(signature, Mapping):
        return signature
    if isinstance(reviewed.get("state_signature"), Mapping):
        return sync_contract.plan_signature(reviewed)
    return None


def _stale_selected_rows(
    runtime: Mapping[str, Any],
    reviewed_rows: list[Mapping[str, Any]],
    current_plan: list[dict[str, Any]],
) -> list[str]:
    """Name every reviewed row whose observation changed before the write.

    ``reviewed_rows`` carries the signature the person actually saw, taken
    from the preview phase, so a change made while the review table was open
    is caught here rather than being silently written over. The write phase
    runs this once more under the reserving-class lock before its first
    write; the per-row check inside the batch is ``_row_moved_before_write``.
    """

    sync_contract = runtime["sync_contract"]
    current = _plan_by_id(current_plan)
    stale: list[str] = []
    for reviewed in reviewed_rows:
        row_id = str(reviewed.get("id") or "")
        observed = current.get(row_id)
        reviewed_signature = _reviewed_signature(sync_contract, reviewed)
        if reviewed_signature is None:
            # A reviewed row without its signature cannot be proven unchanged.
            stale.append(str(reviewed.get("name") or row_id or "item"))
            continue
        if observed is None or not sync_contract.signatures_equal(
            reviewed_signature,
            sync_contract.plan_signature(observed),
        ):
            stale.append(str(reviewed.get("name") or row_id or "item"))
    return stale


def _row_moved_before_write(
    runtime: Mapping[str, Any],
    row: Mapping[str, Any],
    current_row: Mapping[str, Any] | None,
) -> bool:
    """Tell whether the side a row is written from moved since the batch began.

    ``row`` is the plan row selected under the reserving-class lock and
    ``current_row`` its fresh observation taken right before the write. Only
    the source side's timestamp and both sides' identity count: an earlier
    write in the same batch re-stamps the target side of everything
    downstream of it, which is the batch doing its job, not a change to
    refuse.
    """

    sync_contract = runtime["sync_contract"]
    if current_row is None:
        return True
    source_side = (
        "arcrho"
        if row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ
        else "resq"
    )
    return not sync_contract.write_signatures_equal(
        sync_contract.plan_signature(row),
        sync_contract.plan_signature(current_row),
        source_side=source_side,
    )


def apply_sync_plan(
    runtime: Mapping[str, Any],
    *,
    project_name: str,
    rc_path: str,
    server_root: Path,
    exporter,
    selected_rows: list[dict[str, Any]],
    state: Mapping[str, Any],
    state_path: Path,
    progress_callback,
) -> dict[str, Any]:
    """Apply selected actions in dependency-safe phases and record successful baselines."""

    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    rc_dir = migration.PROJECT_DATA_DIR / migration._encode_rc_folder(rc_path)

    from app_server.services.dataset_sidecar_status_service import reserving_class_io_lock
    from arcrho_api.client import ArcRhoClient
    from arcrho_api.dfm_propagation import _refresh_dfm_dependents_for_sources_locked
    from arcrho_dependent_propagation_contract import held_reserving_class_lease

    results: list[dict[str, Any]] = []
    successful_keys: list[str] = []
    local_mutated_names: list[str] = []
    post_write_observations: dict[str, dict[str, Any]] = {}
    total = len(selected_rows)
    completed = 0

    def record(row: Mapping[str, Any], success: bool, message: str) -> None:
        nonlocal completed
        completed += 1
        if success:
            successful_keys.append(str(row.get("key") or ""))
        results.append({
            "id": row.get("id"),
            "name": row.get("name"),
            "kind": row.get("kind"),
            "action": row.get("action"),
            "success": success,
            "message": message,
        })
        try:
            progress_callback({
                "completed": completed,
                "total": total,
                "status": "success" if success else "error",
                "message": f"{row.get('name')}: {message}",
            })
        except Exception:
            # A row may already be durable; UI/activity reporting must not turn
            # that success into an un-baselined half-completion.
            pass

    def plan_with_baseline(baseline_state: Mapping[str, Any]) -> dict[str, Any]:
        observation = _plan_context(
            runtime, project_name, rc_path, server_root, exporter=exporter
        )
        observation["plan"] = sync_contract.build_sync_plan(
            observation["arcrho"], observation["resq"], baseline_state
        )
        return observation

    def observation_signature(row: Mapping[str, Any]) -> dict[str, Any]:
        signature = sync_contract.plan_signature(row)
        signature["action"] = ""
        signature["disabled"] = False
        return signature

    def remember_post_write(
        row: Mapping[str, Any],
        baseline_state: Mapping[str, Any],
        before_row: Mapping[str, Any],
    ) -> tuple[bool, str]:
        current = _plan_by_id(plan_with_baseline(baseline_state)["plan"])
        observed = current.get(str(row.get("id") or ""))
        key = str(row.get("key") or "")
        if observed is None:
            post_write_observations[key] = {}
            return False, "The item disappeared while its write was being verified."
        source_side = (
            "arcrho"
            if row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ
            else "resq"
        )
        before_source = sync_contract.plan_signature(before_row).get(source_side)
        after_source = sync_contract.plan_signature(observed).get(source_side)
        if before_source != after_source:
            post_write_observations[key] = {}
            return False, (
                f"The authoritative {source_side.title()} source changed during the write; "
                "the result was not baselined. Rerun the review."
            )
        post_write_observations[key] = observation_signature(observed)
        return True, ""

    runtime_dir = server_root / "r"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    io_lock = reserving_class_io_lock(project_name, rc_path)
    lease_context = held_reserving_class_lease(
        server_root, project_name, rc_path, timeout_seconds=60.0
    )
    with io_lock, lease_context, tempfile.TemporaryDirectory(
        prefix="resq-sync-", dir=str(runtime_dir)
    ) as temp_name:
        locked_observation = _plan_context(
            runtime, project_name, rc_path, server_root, exporter=exporter
        )
        locked_stale = _stale_selected_rows(
            runtime, selected_rows, locked_observation["plan"]
        )
        if locked_stale:
            return {
                "successes": 0,
                "failures": 0,
                "results": [],
                "successful_keys": [],
                "stale_items": locked_stale,
            }
        selected_rows = _selected_rows(
            locked_observation["plan"],
            [str(row.get("id") or "") for row in selected_rows],
        )
        state = locked_observation["state"]
        state_path = locked_observation["state_path"]
        # Each direction is written in ArcRho's dependency order: a row comes
        # after every accepted row it reads, whether that is a formula input,
        # a method's linked dataset, another method's output, or a calculated
        # dataset derived from one of those.
        edges = _reserving_class_edges(runtime, rc_dir, locked_observation["plan"])
        local_to_remote = _dependency_ordered_rows(sync_contract, [
            row for row in selected_rows
            if row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ
        ], edges)
        remote_to_local = _dependency_ordered_rows(sync_contract, [
            row for row in selected_rows
            if row.get("action") == sync_contract.ACTION_RESQ_TO_ARCRHO
        ], edges)

        preflight_failed_ids: set[str] = set()
        for row in remote_to_local:
            try:
                _preflight_import_method_filename_collision(runtime, rc_dir, row)
            except Exception as exc:
                preflight_failed_ids.add(str(row.get("id") or ""))
                record(row, False, f"Preflight blocked the import: {exc}")
        # A link may point at an earlier accepted row rather than at an object
        # ResQ already holds. A row whose own preflight failed never joins the
        # batch, so anything that reads it is blocked here as well.
        batch_keys: set[str] = set()

        def satisfied_by_batch(name: str) -> bool:
            return sync_contract.logical_key(name) in batch_keys

        for row in local_to_remote:
            try:
                if row.get("kind") == KIND_DATASET:
                    _preflight_dataset_export(exporter, row)
                else:
                    _preflight_method_export(exporter, row, satisfied=satisfied_by_batch)
            except Exception as exc:
                preflight_failed_ids.add(str(row.get("id") or ""))
                record(row, False, f"Preflight blocked the write: {exc}")
                continue
            batch_keys.add(str(row.get("key") or ""))
        if preflight_failed_ids:
            selected_rows = [
                row for row in selected_rows
                if str(row.get("id") or "") not in preflight_failed_ids
            ]
            local_to_remote = [row for row in local_to_remote if str(row.get("id") or "") not in preflight_failed_ids]
            remote_to_local = [row for row in remote_to_local if str(row.get("id") or "") not in preflight_failed_ids]
        write_order = local_to_remote + remote_to_local

        rc_dir.mkdir(parents=True, exist_ok=True)
        (rc_dir / migration.DATASET_CACHE_DIR).mkdir(parents=True, exist_ok=True)
        (rc_dir / migration.METHOD_DATA_DIR).mkdir(parents=True, exist_ok=True)
        (rc_dir / migration.DATASET_SIDECAR_DIR).mkdir(parents=True, exist_ok=True)
        backup_root = Path(temp_name) / "previous"
        backup_paths = _snapshot_groups(
            runtime,
            rc_dir,
            {str(row.get("key") or "") for row in remote_to_local},
            backup_root,
        )
        with nullcontext():
            # Writes are deliberately sequential and follow the dependency
            # order above: every ArcRho-to-ResQ row, each after the rows it
            # reads, then every ResQ-to-ArcRho row the same way. A ResQ Save
            # or an ArcRho dependency refresh can recalculate a later selected
            # row, so each row is re-inventoried immediately before its own
            # mutation and local propagation runs before the next row.
            for row in write_order:
                current = plan_with_baseline(locked_observation["state"])
                current_row = _plan_by_id(current["plan"]).get(str(row.get("id") or ""))
                if _row_moved_before_write(runtime, row, current_row):
                    source = (
                        "Arco"
                        if row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ
                        else "ResQ"
                    )
                    record(
                        row,
                        False,
                        f"The {source} source changed during synchronization; rerun the review.",
                    )
                    continue
                if row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ:
                    try:
                        ok, message = _export_one_to_resq(exporter, row)
                    except Exception as exc:
                        ok, message = False, str(exc)
                else:
                    with migration.defer_sidecar_graph_enrichment():
                        try:
                            ok, message = _import_one_from_resq(
                                runtime, exporter, rc_path, rc_dir, row, progress_callback
                            )
                        except Exception as exc:
                            ok, message = False, str(exc)
                    if not ok:
                        try:
                            _restore_group(runtime, exporter, rc_dir, row, backup_root, backup_paths)
                        except Exception as restore_error:
                            message = f"{message} Rollback also failed: {restore_error}"
                    else:
                        stable, stability_message = remember_post_write(
                            row, locked_observation["state"], current_row
                        )
                        if not stable:
                            ok, message = False, f"{message} {stability_message}".strip()
                            try:
                                _restore_group(runtime, exporter, rc_dir, row, backup_root, backup_paths)
                            except Exception as restore_error:
                                message = f"{message} Rollback also failed: {restore_error}"
                        else:
                            local_mutated_names.append(str(row.get("name") or ""))
                            migration.refresh_sidecar_graphs_for_rc(rc_dir)
                            reserving_class = ArcRhoClient(server_root).project(project_name).reserving_class(rc_path)
                            propagation = _refresh_dfm_dependents_for_sources_locked(
                                reserving_class, [str(row.get("name") or "")]
                            )
                            for warning in propagation.warnings:
                                results.append({
                                    "id": "",
                                    "name": "Dependent refresh",
                                    "kind": "Warning",
                                    "action": "",
                                    "success": False,
                                    "message": str(warning),
                                })
                if ok and row.get("action") == sync_contract.ACTION_ARCRHO_TO_RESQ:
                    stable, stability_message = remember_post_write(
                        row, locked_observation["state"], current_row
                    )
                    if not stable:
                        ok, message = False, f"{message} {stability_message}".strip()
                record(row, ok, message)
            if local_mutated_names:
                migration.rebuild_dataset_instance_index(project_name, rc_path, rc_dir)

            final_local = collect_arcrho_inventory(runtime, rc_dir)
            final_remote = collect_resq_inventory(runtime, exporter)
            final_plan = sync_contract.build_sync_plan(
                final_local, final_remote, locked_observation["state"]
            )
            final_by_id = _plan_by_id(final_plan)
            unstable_keys: set[str] = set()
            for row in selected_rows:
                key = str(row.get("key") or "")
                remembered = post_write_observations.get(key)
                final_row = final_by_id.get(str(row.get("id") or ""))
                if key not in successful_keys:
                    continue
                if not remembered or final_row is None or not sync_contract.signatures_equal(
                    remembered, observation_signature(final_row)
                ):
                    unstable_keys.add(key)
            if unstable_keys:
                successful_keys = [key for key in successful_keys if key not in unstable_keys]
                for item in results:
                    if str(item.get("id") or "") and any(
                        str(row.get("id") or "") == str(item.get("id") or "")
                        and str(row.get("key") or "") in unstable_keys
                        for row in selected_rows
                    ):
                        item["success"] = False
                        item["message"] = (
                            f"{item.get('message')} The item changed again later in this batch; "
                            "its baseline was not recorded. Rerun the review."
                        )
            updated_state = sync_contract.record_synced_items(
                state,
                successful_keys,
                final_local,
                final_remote,
            )
            recorded_keys = {
                str(key) for key in updated_state.get("_recorded_keys", [])
            }
            unrecorded_keys = {
                key for key in successful_keys if key not in recorded_keys
            }
            if unrecorded_keys:
                successful_keys = [
                    key for key in successful_keys if key not in unrecorded_keys
                ]
                selected_key_by_id = {
                    str(row.get("id") or ""): str(row.get("key") or "")
                    for row in selected_rows
                }
                for item in results:
                    if selected_key_by_id.get(str(item.get("id") or "")) in unrecorded_keys:
                        item["success"] = False
                        item["message"] = (
                            f"{item.get('message')} The final ArcRho/ResQ timestamps "
                            "could not be recorded; the row remains in recovery state."
                        )
            if successful_keys:
                # The writes ripple: both systems recalculate and re-stamp
                # whatever reads a written row, so those rows are baselined
                # here rather than shown as changes at the next review.
                selected_keys = {str(row.get("key") or "") for row in selected_rows}
                ripple_keys = _downstream_keys(
                    edges, locked_observation["plan"], set(successful_keys)
                ) - selected_keys
                updated_state, absorbed = sync_contract.absorb_propagated_changes(
                    updated_state,
                    locked_observation["plan"],
                    final_plan,
                    keys=sorted(ripple_keys),
                )
                locked_by_key = {
                    str(row.get("key") or ""): row for row in locked_observation["plan"]
                }
                for item in absorbed:
                    sides = " and ".join(
                        "Arco" if side == "arcrho" else "ResQ" for side in item["sides"]
                    )
                    results.append({
                        "id": str((locked_by_key.get(item["key"]) or {}).get("id") or ""),
                        "name": item["name"],
                        "kind": item["kind"],
                        "action": "",
                        "success": True,
                        "absorbed": True,
                        "message": (
                            f"Recalculated on the {sides} side by this run's writes; "
                            "the baseline was updated and nothing was written."
                        ),
                    })
            sync_contract.write_sync_state(state_path, updated_state)

    written = [item for item in results if item.get("id") and not item.get("absorbed")]
    successes = sum(bool(item.get("success")) for item in written)
    failures = sum(not bool(item.get("success")) for item in written)
    return {
        "successes": successes,
        "failures": failures,
        "results": results,
        "successful_keys": successful_keys,
    }


def _emit_progress(progress_callback, event: Mapping[str, Any]) -> None:
    if callable(progress_callback):
        progress_callback(dict(event))


def _public_plan_rows(runtime: Mapping[str, Any], plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a serializable preview without COM objects or full JSON payloads.

    Each row carries its ``signature``: the observation the review table was
    drawn from. The apply request sends the signatures of the accepted rows
    back, which is how a queued session proves nothing moved underneath a
    person while they were reviewing.
    """

    sync_contract = runtime["sync_contract"]
    rows = []
    for row in plan:
        arcrho = row.get("arcrho") if isinstance(row.get("arcrho"), Mapping) else {}
        resq = row.get("resq") if isinstance(row.get("resq"), Mapping) else {}
        baseline = row.get("state_signature") if isinstance(row.get("state_signature"), Mapping) else {}
        # Only a paired row whose two sides agree on identity has timestamps
        # that mean the same thing, so only such a row gets an export verdict;
        # everything else keeps the plan's own status and detail.
        export_review = (
            sync_contract.export_review(arcrho, resq, baseline) if row.get("comparable") else {}
        )
        rows.append({
            "id": str(row.get("id") or ""),
            "signature": sync_contract.plan_signature(row),
            "name": str(row.get("name") or ""),
            "kind": str(row.get("kind") or KIND_DATASET),
            # The ArcRho identity a client needs to open the item in a Project
            # Instance page: the dataset type, and the method name for a DFM.
            "dataset_type": str(arcrho.get("dataset_type") or ""),
            "method_name": str(arcrho.get("method_name") or ""),
            "arcrho_timestamp": _timestamp_cell(row.get("arcrho")),
            "resq_timestamp": _timestamp_cell(row.get("resq")),
            # Per-item facts the Export macro's timestamp check reads, decided
            # by the same contract as the plan itself. ``newer_side`` states
            # which timestamp is later; ``export_review`` says what that means
            # against the baseline the last export or synchronization saved,
            # which is the only way a ResQ edit is told apart from the stamp
            # the last export left behind.
            "newer_side": sync_contract.newer_side(arcrho, resq),
            "export_supported": sync_contract.export_supported(arcrho, resq),
            "export_review": export_review,
            "status": str(row.get("status") or ""),
            "action": str(row.get("action") or ""),
            "detail": str(row.get("detail") or ""),
            "selected": bool(row.get("selected")),
            "disabled": bool(row.get("disabled")),
            "review": bool(row.get("review")),
        })
    return rows



def _inventory_groups(sync_contract, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """One side's items keyed by the logical identity both sides are paired on."""

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = sync_contract.logical_key(item.get("name"))
        if key:
            groups.setdefault(key, []).append(item)
    return groups


def _transfer_row(
    sync_contract,
    direction: str,
    key: str,
    arcrho: Mapping[str, Any] | None,
    resq: Mapping[str, Any] | None,
    baseline: Mapping[str, Any] | None,
    detail: str,
    *,
    name: str = "",
    presence: str = "",
) -> dict[str, Any]:
    """One tickable row of the shared review table, from either or both sides.

    The row id is the logical key itself, so an accepted row leads straight
    back to the name the request and the saved selection are written with.
    ``name`` and ``presence`` are given where the sides cannot supply them --
    an ambiguous plan row holds neither side, yet both systems do have the
    name, and it must still be named in the table.
    """

    arcrho = arcrho if isinstance(arcrho, Mapping) else None
    resq = resq if isinstance(resq, Mapping) else None
    kind = str((arcrho or resq or {}).get("kind") or KIND_DATASET)
    supported, block_reason = sync_contract.transfer_support(direction, arcrho, resq)
    if not (arcrho and resq) and (presence == "both" or not (arcrho or resq)):
        # A side the caller says exists but that did not resolve to a single
        # item: an ambiguous name. Nothing can be written either way, and the
        # caller's own sentence explains it better than a missing-copy reason.
        supported, block_reason = False, detail
    elif (
        not supported
        and direction == sync_contract.DIRECTION_EXPORT
        and arcrho
        and resq
        and kind in _EXPORT_PHASE_METHOD_KINDS
    ):
        # The export saves these methods so ResQ recalculates each from the
        # datasets written before it, and writes the B&S Case Reserve Adequacy
        # selections on the way. That is a real export, so the row is offered
        # rather than greyed out -- but only where ResQ holds the method: the
        # export never creates a Cape Cod or a Berquist Sherman method.
        supported, block_reason = True, ""
    return {
        "id": key,
        "key": key,
        "name": name or str((arcrho or resq or {}).get("name") or ""),
        "kind": kind,
        "dataset_type": str((arcrho or resq or {}).get("dataset_type") or ""),
        "method_name": str((arcrho or {}).get("method_name") or ""),
        "presence": presence or ("both" if arcrho and resq else ("arcrho" if arcrho else "resq")),
        "arcrho_timestamp": _timestamp_cell(arcrho) if arcrho else "",
        "resq_timestamp": _timestamp_cell(resq) if resq else "",
        "newer_side": sync_contract.newer_side(arcrho or {}, resq or {}),
        # The baseline verdict only means something where both sides are
        # present and paired; elsewhere there is no pair to measure.
        "export_review": (
            sync_contract.export_review(arcrho, resq, baseline) if arcrho and resq else {}
        ),
        "transfer_supported": supported,
        # A supported row can still carry a reason -- "Creates the method in
        # ResQ." for an Arco-only DFM, BF or Result Selection -- which is its
        # detail, not a block.
        "transfer_block_reason": "" if supported else block_reason,
        "selected": False,
        "disabled": not supported,
        "detail": block_reason or detail,
    }


def _transfer_rows(
    runtime: Mapping[str, Any],
    context: Mapping[str, Any],
    direction: str,
) -> list[dict[str, Any]]:
    """Every dataset and method output either side holds, ready to be ticked.

    The synchronization plan pairs what both systems have; an item only one
    side holds never becomes a plan row, yet it is exactly what an import
    brings across, so it is added here with the missing side left blank.
    """

    sync_contract = runtime["sync_contract"]
    rows = [
        _transfer_row(
            sync_contract,
            direction,
            str(row.get("key") or ""),
            row.get("arcrho"),
            row.get("resq"),
            row.get("state_signature") if row.get("comparable") else None,
            str(row.get("detail") or ""),
            # The plan only pairs items both systems hold, and an ambiguous
            # row holds neither side yet is still named on both.
            name=str(row.get("name") or ""),
            presence="both",
        )
        for row in context["plan"]
    ]
    paired = {row["key"] for row in rows}
    sides = (("arcrho", context["arcrho"]), ("resq", context["resq"]))
    for side, items in sides:
        for key, candidates in _inventory_groups(sync_contract, items).items():
            if key in paired:
                continue
            paired.add(key)
            if len(candidates) > 1:
                row = _transfer_row(
                    sync_contract,
                    direction,
                    key,
                    None,
                    None,
                    None,
                    f"Found {len(candidates)} {side} items with the same normalized name.",
                    name=sync_contract.clean_name(candidates[0].get("name")),
                    presence=side,
                )
                row["kind"] = str(candidates[0].get("kind") or KIND_DATASET)
                rows.append(row)
                continue
            item = candidates[0]
            other_side = "ResQ" if side == "arcrho" else "Arco"
            rows.append(
                _transfer_row(
                    sync_contract,
                    direction,
                    key,
                    item if side == "arcrho" else None,
                    item if side == "resq" else None,
                    None,
                    f"{other_side} has no dataset or method with this name.",
                )
            )
    rows.sort(key=lambda row: (str(row.get("name") or "").casefold(), row["key"]))
    return rows


def _tick_saved_rows(rows: list[dict[str, Any]], saved_keys: set[str]) -> int:
    """Tick the rows the last run in this direction covered, or every row.

    With nothing saved yet, every row the direction supports is ticked, which
    is the whole-class behaviour both macros had before selection existed.
    """

    ticked = 0
    for row in rows:
        if row.get("transfer_supported") and (not saved_keys or row["key"] in saved_keys):
            row["selected"] = True
            ticked += 1
    return ticked


def _session_scope(project_name: str, rc_path: str, server_root: object) -> tuple[str, str, Path]:
    """Validate the logical identifiers one session is allowed to touch."""

    project = str(project_name or "").strip()
    path = str(rc_path or "").strip()
    if not project:
        raise ValueError("project_name is required.")
    if not path:
        raise ValueError("rc_path is required.")
    if server_root is None:
        raise ValueError("server_root is required.")
    return project, path, Path(server_root).expanduser().resolve()


def preview_sync(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    *,
    server_root: object,
    progress_callback=None,
) -> dict[str, Any]:
    """Compare one same-named project/RC scope without writing anything.

    The returned ``preview`` rows are display-ready and carry the signature
    the apply phase rechecks, so the caller never needs the plan's internal
    rows or a ResQ session of its own. ``direction`` is the one way the whole
    reserving class is pushed, with the two latest timestamps that decided it.
    """

    migration = runtime["migration"]
    project_name, rc_path, root = _session_scope(project_name, rc_path, server_root)
    previous_scope = migration._apply_runtime_scope(project_name, root)
    try:
        _emit_progress(progress_callback, {
            "event": "scan",
            "completed": 0,
            "total": 0,
            "message": f"Comparing Arco and ResQ: {rc_path}",
        })
        preview = _plan_context(runtime, project_name, rc_path, root)
        rows = _public_plan_rows(runtime, preview["plan"])
        _emit_progress(progress_callback, {
            "event": "review",
            "completed": 0,
            "total": len(rows),
            "message": f"Review {len(rows)} dataset/method output(s)",
        })
        return {
            "status": "review_required",
            "project_name": project_name,
            "rc_path": rc_path,
            "connection_name": _resq_credentials(runtime)["connection_name"],
            "direction": _direction_payload(preview["direction"]),
            "preview": rows,
        }
    finally:
        migration._restore_runtime_scope(previous_scope)


def _saved_selection(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    server_root: Path,
    connection_name: str,
    direction: str,
) -> dict[str, Any]:
    """The names the last run in this direction covered, with who saved them."""

    selection_contract = runtime["transfer_selection"]
    path = selection_contract.selection_path(server_root, project_name, rc_path, connection_name)
    document = selection_contract.read_selection(path, project_name, rc_path, connection_name)
    entry = document["selections"][direction]
    return {
        "names": list(entry.get("names") or []),
        "updated_at": str(entry.get("updated_at") or ""),
        "updated_by": str(entry.get("updated_by") or ""),
    }


def preview_transfer(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    *,
    direction: str,
    server_root: object,
    progress_callback=None,
) -> dict[str, Any]:
    """Compare both sides for a whole-class import or export, without writing anything.

    Import and export review the same table: every dataset and method output
    either system holds, its two timestamps, and what the run would do to it.
    Only what the direction can carry is tickable, and the rows the last run
    in that direction covered come back already ticked.
    """

    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    direction = sync_contract.transfer_direction(direction)
    project_name, rc_path, root = _session_scope(project_name, rc_path, server_root)
    previous_scope = migration._apply_runtime_scope(project_name, root)
    try:
        _emit_progress(progress_callback, {
            "event": "scan",
            "completed": 0,
            "total": 0,
            "message": f"Comparing Arco and ResQ: {rc_path}",
        })
        context = _plan_context(runtime, project_name, rc_path, root)
        connection_name = _resq_credentials(runtime)["connection_name"]
        selection = _saved_selection(
            runtime, project_name, rc_path, root, connection_name, direction
        )
        rows = _transfer_rows(runtime, context, direction)
        ticked = _tick_saved_rows(
            rows, runtime["transfer_selection"].selection_keys(selection["names"])
        )
        _emit_progress(progress_callback, {
            "event": "review",
            "completed": 0,
            "total": len(rows),
            "message": f"Review {len(rows)} dataset/method output(s); {ticked} selected",
        })
        return {
            "status": "review_required",
            "project_name": project_name,
            "rc_path": rc_path,
            "connection_name": connection_name,
            "direction": direction,
            "class_direction": _direction_payload(context["direction"]),
            "selection": selection,
            "preview": rows,
        }
    finally:
        migration._restore_runtime_scope(previous_scope)


def apply_sync(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    *,
    server_root: object,
    reviewed_rows: list[Mapping[str, Any]],
    progress_callback=None,
) -> dict[str, Any]:
    """Apply the reviewed rows, or apply nothing if any observation moved.

    ``reviewed_rows`` are the accepted rows exactly as the preview phase
    returned them, each with its ``id`` and ``signature``.
    """

    migration = runtime["migration"]
    project_name, rc_path, root = _session_scope(project_name, rc_path, server_root)
    accepted = [row for row in reviewed_rows or [] if isinstance(row, Mapping) and str(row.get("id") or "").strip()]
    previous_scope = migration._apply_runtime_scope(project_name, root)
    exporter = None
    try:
        base = {
            "project_name": project_name,
            "rc_path": rc_path,
            "connection_name": _resq_credentials(runtime)["connection_name"],
        }
        if not accepted:
            return {**base, "status": "no_changes", "successes": 0, "failures": 0, "results": []}

        _emit_progress(progress_callback, {
            "event": "revalidate",
            "completed": 0,
            "total": len(accepted),
            "message": "Rechecking selected timestamps before writing",
        })
        exporter = _new_exporter(runtime, project_name, rc_path, root)
        exporter.connect()
        current = _plan_context(runtime, project_name, rc_path, root, exporter=exporter)
        stale = _stale_selected_rows(runtime, accepted, current["plan"])
        if stale:
            return {
                **base,
                "status": "stale",
                "stale_items": stale,
                "successes": 0,
                "failures": 0,
                "results": [],
            }

        selected_ids = [str(row.get("id") or "") for row in accepted]
        current_rows = _selected_rows(current["plan"], selected_ids)
        if not current_rows:
            return {**base, "status": "no_changes", "successes": 0, "failures": 0, "results": []}

        result = apply_sync_plan(
            runtime,
            project_name=project_name,
            rc_path=rc_path,
            server_root=root,
            exporter=exporter,
            selected_rows=current_rows,
            state=current["state"],
            state_path=current["state_path"],
            progress_callback=progress_callback or (lambda event: None),
        )
        if result.get("stale_items"):
            return {**result, **base, "status": "stale"}
        return {
            **result,
            **base,
            "status": "completed_with_errors" if result.get("failures") else "completed",
        }
    finally:
        if exporter is not None:
            try:
                exporter.disconnect()
            except Exception:
                pass
        migration._restore_runtime_scope(previous_scope)


def _open_export_baseline(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    server_root: Path,
    exporter,
    arcrho_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read the saved baseline and observe both sides before the export writes.

    The baseline is the timestamp pair each item carried the last time it was
    exported or synchronized. It belongs to the project on the ArcRho server,
    one document per reserving class and ResQ connection, so every user's
    review measures from the same pair rather than from a private copy.
    """

    sync_contract = runtime["sync_contract"]
    connection_name = _resq_credentials(runtime)["connection_name"]
    state_path = sync_contract.sync_state_path(server_root, project_name, rc_path, connection_name)
    state = sync_contract.read_sync_state(state_path, project_name, rc_path, connection_name)
    remote = collect_resq_inventory(runtime, exporter)
    return {
        "state": state,
        "state_path": state_path,
        "plan": sync_contract.build_sync_plan(arcrho_inventory, remote, state),
    }


def _record_export_baseline(
    runtime: Mapping[str, Any],
    opening: Mapping[str, Any],
    arcrho_inventory: list[dict[str, Any]],
    exporter,
    written_keys: list[str],
    edges: Mapping[str, set[str]],
) -> dict[str, Any]:
    """Save the timestamp pair every written item now carries on both sides.

    Only an item ResQ confirmed as written is baselined; a skipped or failed
    one keeps its old pair, so the next review still reports the difference.
    The ArcRho side is baselined at the values the export actually pushed and
    not at a fresh read, so an ArcRho edit made while the export ran stays
    pending instead of being recorded as already delivered.

    ResQ recalculates whatever reads a written item, which re-stamps rows the
    export never wrote. Those moves are the export's own doing, so they are
    absorbed into the baseline here rather than surfacing as ResQ edits at the
    next review.
    """

    sync_contract = runtime["sync_contract"]
    final_remote = collect_resq_inventory(runtime, exporter)
    final_plan = sync_contract.build_sync_plan(arcrho_inventory, final_remote, opening["state"])
    updated = sync_contract.record_synced_items(
        opening["state"], written_keys, arcrho_inventory, final_remote
    )
    recorded = {str(key) for key in updated.get("_recorded_keys") or []}
    absorbed: list[dict[str, Any]] = []
    if recorded:
        ripple = _downstream_keys(edges, opening["plan"], set(recorded)) - recorded
        updated, absorbed = sync_contract.absorb_propagated_changes(
            updated, opening["plan"], final_plan, keys=sorted(ripple)
        )
    sync_contract.write_sync_state(opening["state_path"], updated)
    return {
        "recorded": len(recorded),
        "absorbed": len(absorbed),
        "path": str(opening["state_path"]),
        "error": "",
    }


def _remember_selection(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    server_root: Path,
    connection_name: str,
    direction: str,
    selected_names: list[str] | None,
    requested_by: str,
) -> dict[str, Any]:
    """Save what this run covered as the next run's default in this direction.

    Nothing is saved for a run that carried no selection: it covered the whole
    class, which is what an empty saved list already means. The run's writes
    are durable by the time this is called, so a document that cannot be
    written is reported beside them and never fails the run.
    """

    if selected_names is None:
        return {"saved": 0, "path": "", "error": ""}
    try:
        path = runtime["transfer_selection"].save_selection(
            server_root,
            project_name,
            rc_path,
            connection_name,
            direction,
            selected_names,
            updated_by=requested_by,
        )
    except Exception as exc:
        return {"saved": 0, "path": "", "error": f"The selection could not be saved: {exc}"}
    return {"saved": len(selected_names), "path": str(path), "error": ""}


def export_reserving_class(
    runtime: Mapping[str, Any],
    project_name: str,
    rc_path: str,
    *,
    server_root: object,
    selected_names: list[str] | None = None,
    requested_by: str = "",
    progress_callback=None,
) -> dict[str, Any]:
    """Push one reserving class from ArcRho into ResQ, in ArcRho's dependency order.

    Every input dataset with a CSV cache is written with its Notes; every
    DFM, Bornhuetter Ferguson and Result Selection has its settings, inputs,
    selections and Notes written, and is created first when ResQ does not
    hold it; every Cape Cod and Berquist Sherman method has its Notes written
    and is then saved so ResQ recalculates it from those writes. Notes reach
    ResQ for every exported kind. Calculated and engine datasets are left
    out, as is Bootstrap, and no dataset is ever created.

    ``selected_names`` narrows that to the rows a person ticked in the review
    table; without it the whole class is pushed. A selection is remembered for
    the next export of this reserving class once the writes are done.

    Nothing is compared or verified before a write -- the export pushes
    everything it supports. What it does record afterwards is the timestamp
    pair each written item ends up with on both sides, so the next review can
    tell a real ResQ edit from the stamp this export just left behind. A
    baseline that cannot be read or written never stops the export: the writes
    are already durable, so the failure is reported beside them.
    """

    migration = runtime["migration"]
    sync_contract = runtime["sync_contract"]
    project_name, rc_path, root = _session_scope(project_name, rc_path, server_root)
    previous_scope = migration._apply_runtime_scope(project_name, root)
    exporter = None
    try:
        base = {
            "project_name": project_name,
            "rc_path": rc_path,
            "connection_name": _resq_credentials(runtime)["connection_name"],
        }
        rc_dir = migration.PROJECT_DATA_DIR / migration._encode_rc_folder(rc_path)
        if not rc_dir.is_dir():
            raise RuntimeError(f"Arco reserving-class folder not found: {rc_dir}")
        _emit_progress(progress_callback, {
            "event": "scan",
            "completed": 0,
            "total": 0,
            "message": f"Reading the Arco reserving class: {rc_path}",
        })
        local = collect_arcrho_inventory(runtime, rc_dir)
        rows = _export_rows(runtime, local)
        if selected_names is not None:
            chosen = runtime["transfer_selection"].selection_keys(selected_names)
            rows = [row for row in rows if row["key"] in chosen]
        edges = _reserving_class_edges(runtime, rc_dir, rows)
        rows = _dependency_ordered_rows(sync_contract, rows, edges)
        _emit_progress(progress_callback, {
            "event": "connect",
            "completed": 0,
            "total": len(rows),
            "message": f"Connecting to ResQ: {base['connection_name']}",
        })
        exporter = _new_exporter(runtime, project_name, rc_path, root)
        # Only the export creates the DFMs, BFs and Result Selections ResQ
        # lacks; the Sync macro's apply phase drives the same writers and
        # never does.
        exporter.create_missing_methods = True
        exporter.connect()
        opening = None
        baseline = {"recorded": 0, "absorbed": 0, "path": "", "error": ""}
        try:
            opening = _open_export_baseline(runtime, project_name, rc_path, root, exporter, local)
        except Exception as exc:
            baseline["error"] = f"The saved baseline could not be read: {exc}"
        results: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            created_before = _created_count(exporter)
            try:
                outcome, message = _push_row_to_resq(exporter, row)
            except Exception as exc:
                outcome, message = OUTCOME_FAILED, str(exc)
            results.append({
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "outcome": outcome,
                "message": message,
                # A created method is baselined like any written one: the
                # closing inventory reads it on the same connection, so the
                # next review pairs it instead of calling it new again.
                "created": _created_count(exporter) > created_before,
            })
            _emit_progress(progress_callback, {
                "event": "write",
                "completed": index,
                "total": len(rows),
                "status": _EXPORT_PROGRESS_STATUS[outcome],
                "message": f"{row['name']}: {message}",
            })
        if opening is not None:
            _emit_progress(progress_callback, {
                "event": "baseline",
                "completed": len(rows),
                "total": len(rows),
                "message": "Recording the Arco and ResQ timestamps",
            })
            # "Exported" and "saved" both mean ResQ took the write; only those
            # two leave the two sides agreeing, so only those are baselined.
            written_keys = [
                str(row["key"])
                for row, item in zip(rows, results)
                if item["outcome"] in (EXPORT_OUTCOME_EXPORTED, EXPORT_OUTCOME_SAVED)
            ]
            try:
                baseline = _record_export_baseline(
                    runtime, opening, local, exporter, written_keys, edges
                )
            except Exception as exc:
                baseline = {
                    "recorded": 0,
                    "absorbed": 0,
                    "path": str(opening["state_path"]),
                    "error": f"The timestamps could not be recorded: {exc}",
                }
        selection = _remember_selection(
            runtime,
            project_name,
            rc_path,
            root,
            base["connection_name"],
            sync_contract.DIRECTION_EXPORT,
            selected_names,
            requested_by,
        )
        failed = any(item["outcome"] == OUTCOME_FAILED for item in results)
        return {
            **base,
            "status": "completed_with_errors" if failed else "completed",
            "results": results,
            "baseline": baseline,
            "selection": selection,
        }
    finally:
        if exporter is not None:
            try:
                exporter.disconnect()
            except Exception:
                pass
        migration._restore_runtime_scope(previous_scope)


def build_runtime(migration, exporter_module, *, resq_credentials=None) -> dict[str, Any]:
    """Bind one session to its ResQ migration runtime and exporter.

    Every host builds the runtime the same way, so a Bridge worker running
    from its frozen bundle and a test running from the working tree observe
    identical timestamp parsing and plan comparison rules.

    ``resq_credentials`` is the account every ResQ session opens with, as
    ``connection_name``, ``user_name`` and ``password``. The Bridge passes the
    shared service account from its server config, so which user's worker
    claimed the request cannot change what ResQ shows the session.
    """

    from arcrho_api.dataset_index_contract import _method_entry_from_payload
    from resq_migration import sync as sync_contract
    from resq_migration import transfer_selection as selection_contract

    try:
        from app_server.helpers import parse_method_last_modified_timestamp
    except ImportError:
        # A host without the bundled app server falls back to the same parser
        # the plan contract itself uses, rather than to a private copy.
        parse_method_last_modified_timestamp = sync_contract.parse_timestamp

    return {
        "migration": migration,
        "exporter_module": exporter_module,
        "parse_timestamp": parse_method_last_modified_timestamp,
        "method_entry": _method_entry_from_payload,
        "sync_contract": sync_contract,
        "transfer_selection": selection_contract,
        "resq_credentials": dict(resq_credentials) if resq_credentials else None,
    }
