"""The ordered dependent walk: what a save reaches, and the one pass over it.

:func:`ordered_closure` answers two questions and writes nothing: *what* does
a save reach, and *in which order* must those objects be refreshed so each
one is built from final inputs. :func:`run_pass` then walks that order once,
handing every node to its domain's ``refresh_output``, so an object reachable
by several paths is republished once instead of once per path. The domain
refreshers themselves live beside their methods; this module never knows how
a method is calculated.

Two edge sources are read, both of which the walk already reads today:

- each sidecar's persisted ``dependents`` list, through
  :func:`dataset_sidecar_status_service.entry_names`, and
- the dataset-type formula graph
  (:func:`calculated_dataset_service._dependency_map`) restricted to the
  instances that exist in this reserving class
  (:func:`calculated_dataset_service._existing_dataset_keys`, which is served
  from the walk-scoped snapshot while a walk is open).

The order is Kahn's algorithm over those edges: a node is ready once every
precedent of it *inside the closure* has been emitted, and ties are broken by
the order the node was first seen. Only links can make a cycle; a cycle is
broken by emitting its first-seen node once, refreshed from whatever is final
by then, so a candidate ultimate that reads the Result Selection it feeds
converges instead of looping.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from app_server.helpers import _canon_dataset_name
from app_server.services import dataset_sidecar_status_service

KIND_DFM = "dfm"
KIND_RESULT_SELECTION = "result_selection"
KIND_BERQUIST_SHERMAN = "berquist_sherman"
KIND_BORNHUETTER_FERGUSON = "bornhuetter_ferguson"
KIND_CAPE_COD = "cape_cod"
KIND_BOOTSTRAP = "bootstrap"
KIND_CALCULATED = "calculated"
KIND_LINKED_INPUT = "linked_input"
KIND_INPUT = "input"

_KIND_BY_METHOD_TYPE = {
    dataset_sidecar_status_service.METHOD_TYPE_DFM: KIND_DFM,
    dataset_sidecar_status_service.METHOD_TYPE_RESULT_SELECTION: KIND_RESULT_SELECTION,
    dataset_sidecar_status_service.METHOD_TYPE_BORN_HUETTER_FERGUSON: KIND_BORNHUETTER_FERGUSON,
    dataset_sidecar_status_service.METHOD_TYPE_CAPE_COD: KIND_CAPE_COD,
    dataset_sidecar_status_service.METHOD_TYPE_BOOTSTRAP: KIND_BOOTSTRAP,
    dataset_sidecar_status_service.METHOD_TYPE_BERQUIST_SHERMAN_SR: KIND_BERQUIST_SHERMAN,
    dataset_sidecar_status_service.METHOD_TYPE_BERQUIST_SHERMAN_CRA: KIND_BERQUIST_SHERMAN,
}

# Worded as Result Selection's own cap is, because the pass takes that
# traversal over and a user must not see two names for one limit.
GRAPH_LIMIT_MESSAGE = "Dependency graph exceeds the safe refresh limit."


def _clean_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _max_graph_nodes() -> int:
    """Result Selection owns the cap; read it late so nothing imports in a ring."""
    from app_server.services import result_selection_service

    return result_selection_service.MAX_REFRESH_GRAPH_NODES


def walk_cache(caches: Dict[str, Any] | None, name: str) -> Dict[Any, Any]:
    """One walk-scoped cache, named by the domain that owns it.

    The pass hands every refresher the same ``caches`` dict so a sidecar or a
    source snapshot is read once per walk. Each domain keeps its own entry
    under its own name because the domains do not normalise a dataset name the
    same way, so one shared cache could answer with another domain's key.
    """

    store = caches if caches is not None else {}
    cache = store.get(name)
    if not isinstance(cache, dict):
        cache = {}
        store[name] = cache
    return cache


def forget_cached(cache: Dict[Any, Any], keys: Iterable[str]) -> None:
    """Drop what a just-republished object owns, so the next read is fresh.

    A walk-scoped cache is only safe while its entries describe the current
    publication. Every cache the refreshers share is keyed either by a
    dataset's normalised name or by a tuple that starts with one, so dropping
    by that leading key covers both.
    """

    stale = {key for key in keys if key}
    if not stale:
        return
    for entry in list(cache):
        head = entry[0] if isinstance(entry, tuple) and entry else entry
        if head in stale:
            cache.pop(entry, None)


@dataclass(frozen=True)
class WalkNode:
    """One object the walk crosses, with everything a refresher needs."""

    key: str
    name: str
    kind: str
    method_type: str
    precedents: Tuple[str, ...]
    is_root: bool


@dataclass(frozen=True)
class WalkClosure:
    """Every object a save reaches, in the order it must be refreshed."""

    nodes: Tuple[WalkNode, ...]
    names_by_key: Mapping[str, str] = field(default_factory=dict)

    @property
    def refresh_order(self) -> Tuple[WalkNode, ...]:
        """The nodes the pass refreshes: the closure without the saved roots."""
        return tuple(node for node in self.nodes if not node.is_root)

    def name_of(self, key: str) -> str:
        return self.names_by_key.get(key, key)


def _node_kind(sidecar: Mapping[str, Any], key: str, calculated_keys: Set[str]) -> Tuple[str, str]:
    method_type = dataset_sidecar_status_service.normalize_method_type(
        sidecar.get("method_type"),
        sidecar.get("source_kind"),
    )
    kind = _KIND_BY_METHOD_TYPE.get(method_type)
    if kind:
        return kind, method_type
    source_kind = _clean_text(sidecar.get("source_kind")).casefold()
    if source_kind == "input" and (sidecar.get("internal_links") or sidecar.get("formula_links")):
        return KIND_LINKED_INPUT, method_type
    if key in calculated_keys:
        return KIND_CALCULATED, method_type
    return KIND_INPUT, method_type


def _formula_graph_edges(
    project_name: str,
    reserving_class: str,
    dataset_type_rows: List[Dict[str, Any]] | None,
) -> Tuple[Dict[str, List[str]], Set[str]]:
    """Formula-graph dependents by key, restricted to instances that exist here."""
    from app_server.services import calculated_dataset_service

    rows = (
        dataset_type_rows
        if dataset_type_rows is not None
        else calculated_dataset_service._dataset_type_rows(project_name)
    )
    dependency_map = calculated_dataset_service._dependency_map(project_name, rows)
    calculated_keys = {
        _canon_dataset_name(row.get("name"))
        for row in calculated_dataset_service._app_calculated_rows(rows)
        if _canon_dataset_name(row.get("name"))
    }
    if not dependency_map:
        return {}, calculated_keys
    existing_keys = calculated_dataset_service._existing_dataset_keys(project_name, reserving_class)
    names_by_key = {
        _canon_dataset_name(row.get("name")): _clean_text(row.get("name"))
        for row in rows
        if _canon_dataset_name(row.get("name"))
    }
    edges: Dict[str, List[str]] = {}
    for source_key, target_keys in dependency_map.items():
        targets = [
            names_by_key.get(target_key, target_key)
            for target_key in sorted(target_keys)
            if target_key in existing_keys
        ]
        if targets:
            edges[source_key] = targets
    return edges, calculated_keys


def ordered_closure(
    project_name: str,
    reserving_class: str,
    root_names: Iterable[str],
    *,
    sidecar_snapshot: Dict[str, Dict[str, Any]] | None = None,
    dataset_type_rows: List[Dict[str, Any]] | None = None,
    skip_missing_sidecars: bool = False,
) -> WalkClosure:
    """Name every object the roots reach and order it after its precedents.

    ``sidecar_snapshot`` is a walk-scoped cache keyed by canonical dataset
    name; pass the same dict the pass uses so each sidecar is read once. A
    missing sidecar on anything but a root is an error, as it is today.

    ``skip_missing_sidecars`` drops such a node from the closure instead,
    which is what :func:`run_pass` asks for: a dataset that was deleted can
    still be named in a precedent's ``dependents`` list, and one stale edge
    must not fail every save in the class. There is nothing there to refresh,
    so the pass crosses it in silence exactly as the domain waves did.
    """

    snapshot = sidecar_snapshot if sidecar_snapshot is not None else {}
    formula_edges, calculated_keys = _formula_graph_edges(
        project_name, reserving_class, dataset_type_rows
    )

    roots: List[str] = []
    root_keys: Set[str] = set()
    for raw in root_names or []:
        name = _clean_text(raw)
        key = _canon_dataset_name(name)
        if not key or key in root_keys:
            continue
        root_keys.add(key)
        roots.append(name)

    names_by_key: Dict[str, str] = {}
    kinds: Dict[str, Tuple[str, str]] = {}
    dependents: Dict[str, List[str]] = {}
    queue = list(roots)
    while queue:
        frontier: List[str] = []
        seen_frontier: Set[str] = set()
        for name in queue:
            key = _canon_dataset_name(name)
            if not key or key in dependents or key in seen_frontier:
                continue
            seen_frontier.add(key)
            frontier.append(name)
        queue = []
        if not frontier:
            break
        if len(dependents) + len(frontier) > _max_graph_nodes():
            raise RuntimeError(GRAPH_LIMIT_MESSAGE)
        sidecars = _read_sidecars_cached(project_name, reserving_class, frontier, snapshot)
        for name in frontier:
            key = _canon_dataset_name(name)
            names_by_key.setdefault(key, name)
            sidecar = sidecars.get(key) or {}
            if not sidecar and key not in root_keys:
                if not skip_missing_sidecars:
                    raise RuntimeError(f"Dependency graph sidecar is missing for '{name}'.")
                continue
            kinds[key] = _node_kind(sidecar, key, calculated_keys)
            edges: List[str] = []
            edge_keys: Set[str] = set()
            for dependent_name in [
                *dataset_sidecar_status_service.entry_names(sidecar.get("dependents")),
                *formula_edges.get(key, []),
            ]:
                dependent_key = _canon_dataset_name(dependent_name)
                if not dependent_key or dependent_key in edge_keys:
                    continue
                edge_keys.add(dependent_key)
                names_by_key.setdefault(dependent_key, _clean_text(dependent_name))
                edges.append(dependent_key)
                if dependent_key not in dependents:
                    queue.append(dependent_name)
            dependents[key] = edges

    return _ordered_nodes(dependents, names_by_key, kinds, root_keys)


def _read_sidecars_cached(
    project_name: str,
    reserving_class: str,
    names: Sequence[str],
    snapshot: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    missing = [name for name in names if _canon_dataset_name(name) not in snapshot]
    if missing:
        loaded = dataset_sidecar_status_service.read_sidecars(project_name, reserving_class, missing)
        for name in missing:
            key = _canon_dataset_name(name)
            snapshot[key] = loaded.get(key) or {}
    return {_canon_dataset_name(name): snapshot.get(_canon_dataset_name(name), {}) for name in names}


def _ordered_nodes(
    dependents: Dict[str, List[str]],
    names_by_key: Dict[str, str],
    kinds: Dict[str, Tuple[str, str]],
    root_keys: Set[str],
) -> WalkClosure:
    keys_in_order = list(dependents)
    # An edge can name a node the closure dropped (a deleted dataset a stale
    # ``dependents`` entry still points at); it is not part of the order.
    dependents = {key: [item for item in edges if item in dependents] for key, edges in dependents.items()}
    index_by_key = {key: index for index, key in enumerate(keys_in_order)}
    precedents: Dict[str, List[str]] = {key: [] for key in keys_in_order}
    waiting: Dict[str, Set[str]] = {key: set() for key in keys_in_order}
    for key in keys_in_order:
        for dependent_key in dependents[key]:
            precedents[dependent_key].append(key)
            waiting[dependent_key].add(key)

    ready = [index_by_key[key] for key in keys_in_order if not waiting[key]]
    heapq.heapify(ready)
    emitted: Set[str] = set()
    ordered: List[str] = []
    while len(ordered) < len(keys_in_order):
        key = ""
        while ready:
            candidate = keys_in_order[heapq.heappop(ready)]
            if candidate not in emitted:
                key = candidate
                break
        if not key:
            # Only a link can close a ring. Break it on its first-seen node,
            # which is refreshed once from what is final so far.
            key = next(item for item in keys_in_order if item not in emitted)
        emitted.add(key)
        ordered.append(key)
        for dependent_key in dependents[key]:
            waiting[dependent_key].discard(key)
            if not waiting[dependent_key] and dependent_key not in emitted:
                heapq.heappush(ready, index_by_key[dependent_key])

    nodes = tuple(
        WalkNode(
            key=key,
            name=names_by_key.get(key, key),
            kind=kinds.get(key, (KIND_INPUT, dataset_sidecar_status_service.METHOD_TYPE_NONE))[0],
            method_type=kinds.get(key, (KIND_INPUT, dataset_sidecar_status_service.METHOD_TYPE_NONE))[1],
            precedents=tuple(precedents[key]),
            is_root=key in root_keys,
        )
        for key in ordered
    )
    return WalkClosure(nodes=nodes, names_by_key=dict(names_by_key))


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

# The progress stage each kind reports under. The names are the ones the save
# popup and the hosted-save log already know; what changed is that a stage is
# now announced per object instead of once per wave.
_STAGE_BY_KIND = {
    KIND_DFM: "dfm",
    KIND_LINKED_INPUT: "linked_datasets",
    KIND_CALCULATED: "calculated_datasets",
    KIND_RESULT_SELECTION: "result_selection",
    KIND_BERQUIST_SHERMAN: "berquist_sherman",
    KIND_BORNHUETTER_FERGUSON: "bornhuetter_ferguson",
    KIND_CAPE_COD: "cape_cod",
    KIND_BOOTSTRAP: "bootstrap",
}

# What each method kind reports: the walk-result field it fills, whether its
# entries name a ``dataset_type`` beside the dataset, whether it reports the
# other objects the pass moved around it, and which index fields its report
# carries. The shapes are the ones every caller already reads.
_METHOD_BUCKETS = {
    KIND_DFM: ("dfm_updates", True, False, ""),
    KIND_RESULT_SELECTION: ("result_selection_updates", False, True, "error"),
    KIND_BERQUIST_SHERMAN: ("berquist_sherman_updates", True, True, "both"),
    KIND_BORNHUETTER_FERGUSON: ("bornhuetter_ferguson_updates", True, False, "both"),
    KIND_CAPE_COD: ("cape_cod_updates", True, False, "both"),
    KIND_BOOTSTRAP: ("bootstrap_updates", True, False, "both"),
}

_REFRESHABLE_KINDS = tuple(_STAGE_BY_KIND)

BLOCKED_REASON = "Precedent refresh failed: "
SKIPPED_REASON = "Skipped because an upstream calculated dependency did not refresh: "


def _domain_module(kind: str) -> Any:
    """The service that owns one kind, imported late so nothing imports in a ring."""

    from app_server.services import (
        berquist_sherman_service,
        bootstrap_service,
        bornhuetter_ferguson_service,
        calculated_dataset_service,
        cape_cod_service,
        dataset_link_refresh_service,
        dfm_service,
        result_selection_service,
    )

    return {
        KIND_DFM: dfm_service,
        KIND_RESULT_SELECTION: result_selection_service,
        KIND_BERQUIST_SHERMAN: berquist_sherman_service,
        KIND_BORNHUETTER_FERGUSON: bornhuetter_ferguson_service,
        KIND_CAPE_COD: cape_cod_service,
        KIND_BOOTSTRAP: bootstrap_service,
        KIND_CALCULATED: calculated_dataset_service,
        KIND_LINKED_INPUT: dataset_link_refresh_service,
    }[kind]


def _new_method_bucket(
    project_name: str,
    reserving_class: str,
    changed_names: Sequence[str],
    *,
    downstream_names: bool,
    index_fields: str,
) -> Dict[str, Any]:
    bucket: Dict[str, Any] = {
        "ok": True,
        "project_name": project_name,
        "reserving_class": reserving_class,
        "changed_dataset_names": list(changed_names),
        "updated": [],
        "status_refreshed": [],
        "skipped": [],
        "errors": [],
    }
    if downstream_names:
        bucket["downstream_fresh_names"] = []
        bucket["downstream_blocked_names"] = []
    bucket["review_status_updates"] = []
    if index_fields == "both":
        bucket["index_ok"] = True
    if index_fields:
        bucket["index_error"] = ""
    return bucket


def run_pass(
    project_name: str,
    reserving_class: str,
    root_names: Sequence[Any],
    *,
    changed_dataset_name: str = "",
    changed_dataset_type_name: str = "",
    kinds: Iterable[str] | None = None,
    blocked_precedent_names: Iterable[Any] = (),
    finalize_method_review_status: bool = True,
    rebuild_index: bool = True,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> Dict[str, Any]:
    """Refresh everything the roots reach, once each, in dependency order.

    The closure is ordered first, then every node in it is handed to its
    domain's ``refresh_output`` with the precedents this walk has already
    refreshed. A node whose precedent failed is recorded blocked and blocks
    its own descendants in turn, so one failure stops one branch and leaves
    the others running. The report is the walk shape the save response, the
    hosted-save log and the queued job status read.

    ``kinds`` restricts which objects are refreshed; a node of any other kind
    is crossed, so the walk still reaches what lies below it without
    rewriting it. The roots are crossed the same way: they were just saved,
    not refreshed.
    """

    from app_server.services import calculated_dataset_service, dataset_instance_index_service

    project = _clean_text(project_name)
    reserving = _clean_text(reserving_class)
    active_kinds = set(kinds) if kinds is not None else set(_REFRESHABLE_KINDS)

    roots: List[str] = []
    root_keys: Set[str] = set()
    for raw in root_names or []:
        name = _clean_text(raw)
        key = _canon_dataset_name(name)
        if not key or key in root_keys:
            continue
        root_keys.add(key)
        roots.append(name)

    def notify(stage: str, completed: int, total: int, label: str) -> None:
        if progress_callback is not None:
            progress_callback(stage, completed, total, label)

    caches: Dict[str, Any] = {}
    sidecar_snapshot = walk_cache(caches, "walk_sidecars")
    dataset_type_rows = calculated_dataset_service._dataset_type_rows(project)
    caches["dataset_type_rows"] = dataset_type_rows

    method_buckets: Dict[str, Dict[str, Any]] = {
        kind: _new_method_bucket(
            project,
            reserving,
            roots,
            downstream_names=spec[2],
            index_fields=spec[3],
        )
        for kind, spec in _METHOD_BUCKETS.items()
        if kind in active_kinds
    }
    link_updates: Dict[str, List[Any]] = {
        "refreshed": [],
        "failed": [],
        "warnings": [],
        "errors": [],
    }
    steps: List[Dict[str, Any]] = []
    targets: List[str] = []

    # A saved root is final already; everything else becomes final only once
    # this pass has refreshed it, and that is what a node's
    # ``changed_precedents`` is drawn from. ``failed_keys`` carries the other
    # half: a precedent that failed here, or one the caller declared blocked.
    refreshed_keys: Set[str] = set(root_keys)
    failed_keys: Set[str] = set()
    failed_names: List[str] = []
    for raw in blocked_precedent_names or []:
        name = _clean_text(raw)
        key = _canon_dataset_name(name)
        if key and key not in failed_keys:
            failed_keys.add(key)
            failed_names.append(name)

    index_error = ""
    # How many objects this pass set out to refresh. The hosted-save log reads
    # it beside the names it actually rewrote, so a walk that stopped on a
    # failed branch says so ("refreshed 12 of 26 reachable") instead of
    # reporting a small number that looks like a small chain.
    reachable = 0
    with dataset_sidecar_status_service.reserving_class_io_lock(project, reserving):
        closure = ordered_closure(
            project,
            reserving,
            roots,
            sidecar_snapshot=sidecar_snapshot,
            dataset_type_rows=dataset_type_rows,
            skip_missing_sidecars=True,
        )
        kind_by_key = {node.key: node.kind for node in closure.nodes}
        order = [node for node in closure.refresh_order if node.kind in active_kinds]
        total = len(order)
        reachable = total
        for completed, node in enumerate(order):
            notify(_STAGE_BY_KIND[node.kind], completed, total, node.name)
            if node.kind == KIND_CALCULATED:
                targets.append(node.name)
            sidecar = sidecar_snapshot.get(node.key) or {}
            blocked = [closure.name_of(key) for key in node.precedents if key in failed_keys]
            if blocked:
                _record_blocked(node, sidecar, blocked, method_buckets, link_updates, steps)
                failed_keys.add(node.key)
                failed_names.append(node.name)
                continue
            changed_precedents = [
                closure.name_of(key) for key in node.precedents if key in refreshed_keys
            ]
            result = _domain_module(node.kind).refresh_output(
                project,
                reserving,
                node.name,
                sidecar,
                changed_precedents,
                caches,
            )
            # The refresher owns its object's files and status; the walk only
            # reads what its outcome means for everything below it. The
            # snapshot entry is dropped because the publication moved it on.
            sidecar_snapshot.pop(node.key, None)
            if _record_result(node, sidecar, result, method_buckets, link_updates, steps):
                refreshed_keys.add(node.key)
            elif not result.get("ok", True):
                failed_keys.add(node.key)
                failed_names.append(node.name)

        for kind, bucket in method_buckets.items():
            bucket["ok"] = not bucket["errors"]
            if "downstream_fresh_names" not in bucket:
                continue
            bucket["downstream_fresh_names"] = [
                closure.name_of(key)
                for key in refreshed_keys
                if key not in root_keys and kind_by_key.get(key) != kind
            ]
            bucket["downstream_blocked_names"] = [
                name
                for name in failed_names
                if kind_by_key.get(_canon_dataset_name(name), KIND_INPUT) != kind
            ]

        if failed_names:
            # Everything under a failure keeps its last valid publication and
            # is flagged for review, which is how the dataset table shows the
            # branch that stopped.
            dataset_sidecar_status_service.refresh_method_statuses_for_dependents(
                project, reserving, failed_names,
            )
        if finalize_method_review_status:
            notify("finalize", total, total, "Review statuses finalized during publication")

        if rebuild_index:
            notify("index", total, total, "Rebuilding the dataset index")
            try:
                dataset_instance_index_service.rebuild_index(project, reserving)
            except Exception as err:
                index_error = str(err)
        for bucket in method_buckets.values():
            if "index_error" in bucket:
                bucket["index_error"] = index_error
            if "index_ok" in bucket:
                bucket["index_ok"] = not index_error

    overall_ok = (
        all(item.get("ok") for item in steps)
        and not link_updates["failed"]
        and all(bucket["ok"] for bucket in method_buckets.values())
    )
    report: Dict[str, Any] = {
        "ok": overall_ok,
        "project_name": project,
        "reserving_class": reserving,
        "changed_dataset_name": changed_dataset_name,
        "changed_dataset_type_name": changed_dataset_type_name,
        "targets": targets,
        "steps": steps,
        "updated": [item for item in steps if item.get("ok")],
        "skipped": [item for item in steps if not item.get("ok")],
        "link_updates": link_updates,
        "reachable_count": reachable,
        "index_ok": not index_error,
        "index_error": index_error,
    }
    for kind, spec in _METHOD_BUCKETS.items():
        report[spec[0]] = method_buckets.get(kind)
    return report


def _dataset_type_of(node: WalkNode, sidecar: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    """The output's dataset type, however the domain reports it."""

    refreshed_sidecar = result.get("sidecar") if isinstance(result, Mapping) else None
    for source in (result, refreshed_sidecar, sidecar):
        if isinstance(source, Mapping):
            value = _clean_text(source.get("dataset_type"))
            if value:
                return value
    return node.name


def _record_blocked(
    node: WalkNode,
    sidecar: Mapping[str, Any],
    blocked: Sequence[str],
    method_buckets: Dict[str, Dict[str, Any]],
    link_updates: Dict[str, List[Any]],
    steps: List[Dict[str, Any]],
) -> None:
    """Record a node whose precedent did not refresh, in its domain's words."""

    if node.kind == KIND_CALCULATED:
        steps.append({
            "ok": False,
            "dataset_type_name": node.name,
            "skipped": True,
            "status": "skipped",
            "reason": "upstream_calculation_failed",
            "errors": [SKIPPED_REASON + ", ".join(blocked)],
        })
        return
    if node.kind == KIND_LINKED_INPUT:
        link_updates["failed"].append(node.name)
        link_updates["errors"].append({
            "dataset_name": node.name,
            "reason": "upstream_refresh_failed",
            "errors": [BLOCKED_REASON + ", ".join(blocked)],
        })
        return
    error: Dict[str, Any] = {
        "dataset_name": node.name,
        "reason": BLOCKED_REASON + ", ".join(blocked),
    }
    if _METHOD_BUCKETS[node.kind][1]:
        error["dataset_type"] = _dataset_type_of(node, sidecar, {})
    method_buckets[node.kind]["errors"].append(error)


def _record_result(
    node: WalkNode,
    sidecar: Mapping[str, Any],
    result: Mapping[str, Any],
    method_buckets: Dict[str, Dict[str, Any]],
    link_updates: Dict[str, List[Any]],
    steps: List[Dict[str, Any]],
) -> bool:
    """File one refresher's outcome; report whether the object is now fresh."""

    if node.kind == KIND_CALCULATED:
        steps.append({**result, "status": "updated" if result.get("ok") else "skipped"})
        return bool(result.get("ok"))
    if node.kind == KIND_LINKED_INPUT:
        for warning in result.get("warnings") or []:
            link_updates["warnings"].append({
                "dataset_name": node.name,
                "reference": str(warning.get("reference") or ""),
                "reason": str(warning.get("reason") or ""),
            })
        if not result.get("ok"):
            link_updates["failed"].append(node.name)
            link_updates["errors"].append({
                "dataset_name": node.name,
                "reason": _clean_text(result.get("reason")) or "link_error",
                "errors": [str(item) for item in result.get("errors") or []],
            })
            return False
        if result.get("refreshed"):
            link_updates["refreshed"].append(node.name)
            return True
        return False
    bucket = method_buckets[node.kind]
    with_type = _METHOD_BUCKETS[node.kind][1]
    if not result.get("ok", True):
        error: Dict[str, Any] = {
            "dataset_name": node.name,
            "reason": _clean_text(result.get("reason")) or "refresh_failed",
        }
        if with_type:
            error["dataset_type"] = _dataset_type_of(node, sidecar, result)
        bucket["errors"].append(error)
        return False
    if result.get("updated"):
        entry: Dict[str, Any] = {"dataset_name": node.name}
        if with_type:
            entry["dataset_type"] = _dataset_type_of(node, sidecar, result)
            entry["output_changed"] = bool(result.get("output_changed"))
        bucket["updated"].append(entry)
        return True
    if result.get("status_refreshed"):
        bucket["status_refreshed"].append({"dataset_name": node.name})
        return True
    bucket["skipped"].append({
        "dataset_name": node.name,
        "reason": _clean_text(result.get("reason")) or "not_updated",
    })
    return False
