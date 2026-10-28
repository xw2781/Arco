"""Contract for Arco Server-hosted workspace reads.

A Client PC that opens a reserving class, a cached dataset, a method window, or
the Project Settings table summary pays one SMB round trip per file it touches,
and a stale reserving-class index makes it open every sidecar and method JSON in
the class over the mapped drive. The app server can instead ask the machine-wide
Arco Gateway to run the very same ``app_server`` service function on the
server host, where the workspace is local disk, and return the service's
response verbatim.

Only the allowlisted kinds below may execute remotely. Each kind names the
canonical service function and the keyword arguments a client may pass, so the
Gateway needs no second table of its own and a new read reaches HTTP the moment
it is registered here. The read kinds are pure functions of the workspace plus
their arguments: a repeated request is safe, so this transport keeps no
idempotency receipt.

Reads run under the submitting user's identity for the same reason hosted saves
do: a load that performs a one-time on-disk upgrade stamps that user, not the
Gateway's service profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from arcrho_dependent_propagation_contract import (
    DependentPropagationContractError,
    validate_project_name,
    validate_request_id,
    validate_reserving_class_path,
)
from arcrho_hosted_save_http_contract import MAX_REQUEST_BYTES as MAX_HOSTED_SAVE_REQUEST_BYTES


WORKSPACE_READ_FUNCTION = "ArcRhoWorkspaceRead"
WORKSPACE_READ_CONTRACT_VERSION = 1
WORKSPACE_READ_PATH = "/api/workspace-reads"
# The response header naming the workspace root the read ran against, so the
# client can rebase any machine-local path in the payload onto its own root.
WORKSPACE_ROOT_HEADER = "X-ArcRho-Workspace-Root"
# A read either serves a persisted file or, at worst, rebuilds one index or
# summary on local disk; a cached-dataset load may also wait on one Engine
# header request.
WORKSPACE_READ_TIMEOUT_SECONDS = 120.0
# The dependents preview sends the whole edited grid, the same grid a dataset
# save sends, so a read gets the hosted save's request budget.
MAX_WORKSPACE_READ_REQUEST_BYTES = MAX_HOSTED_SAVE_REQUEST_BYTES


class WorkspaceReadContractError(ValueError):
    """Raised when a workspace-read payload violates this contract."""


@dataclass(frozen=True)
class WorkspaceReadKind:
    """One remotely executable ``app_server.services`` read."""

    module: str
    function: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.required + self.optional)


# kind -> canonical service read. The Gateway resolves reads only through this
# table; a request naming anything else, or passing an argument not listed
# here, is rejected before any import happens.
WORKSPACE_READ_KINDS: dict[str, WorkspaceReadKind] = {
    "resq_class_inventory": WorkspaceReadKind(
        "resq_class_inventory_service", "existing_class_counts", ("project_name",),
    ),
    "project_instance_json": WorkspaceReadKind(
        "project_json_service", "read_project_json",
        ("project_name", "reserving_class", "folder", "filename"),
    ),
    "propagation_preflight": WorkspaceReadKind(
        "dependent_propagation_service", "check_propagation_preflight",
        ("scope",), ("project_name", "reserving_class"),
    ),
    "propagation_busy": WorkspaceReadKind(
        "dependent_propagation_service", "get_reserving_class_busy",
        ("project_name", "reserving_class"),
    ),
    "propagation_status": WorkspaceReadKind(
        "dependent_propagation_service", "get_dependent_propagation_status",
        ("request_id",),
    ),
    "dataset_index": WorkspaceReadKind(
        "dataset_service",
        "list_cached_dataset_names",
        ("project_name", "reserving_class"),
        ("refresh",),
    ),
    "dataset_cache_load": WorkspaceReadKind(
        "dataset_service",
        "load_cached_dataset_values",
        ("project_name", "reserving_class", "dataset_name"),
        ("csv_file", "origin_length", "development_length", "cumulative", "calendar", "at_display_shape"),
    ),
    # The cells a triangle has at a pair of period lengths, read from the
    # project's General Settings. A hand-entered grid is drawn before there is
    # a file to load, so the window asks for this shape instead.
    "triangle_grid_shape": WorkspaceReadKind(
        "dataset_service",
        "triangle_grid_shape",
        ("project_name", "origin_length", "development_length"),
    ),
    # Handles are process-local. A client also sends the workspace-relative
    # CSV location so a restarted Gateway can resolve a hosted run's result.
    "dataset_grid_load": WorkspaceReadKind(
        "dataset_service", "get_dataset",
        ("ds_id", "project_name", "origin_length"), ("dataset_path",),
    ),
    "dfm_method_load": WorkspaceReadKind(
        "dfm_service",
        "load_dfm_method",
        ("project_name", "reserving_class", "method_name"),
        ("output_dataset",),
    ),
    "result_selection_load": WorkspaceReadKind(
        "result_selection_service",
        "load_result_selection",
        ("project_name", "reserving_class", "method_name"),
        ("include_method",),
    ),
    "bornhuetter_ferguson_load": WorkspaceReadKind(
        "bornhuetter_ferguson_service",
        "load_bornhuetter_ferguson_method",
        ("project_name", "reserving_class", "method_name"),
    ),
    "cape_cod_load": WorkspaceReadKind(
        "cape_cod_service",
        "load_cape_cod_method",
        ("project_name", "reserving_class", "method_name"),
    ),
    "bootstrap_load": WorkspaceReadKind(
        "bootstrap_service",
        "load_bootstrap_method",
        ("project_name", "reserving_class", "method_name"),
    ),
    # Simulate re-fits the DFM and re-simulates from the seed where the DFM
    # and the target are local disk, and writes nothing; Save publishes the
    # same run.
    "bootstrap_simulate": WorkspaceReadKind(
        "bootstrap_service",
        "simulate_bootstrap_method",
        ("project_name", "reserving_class", "method"),
    ),
    # A Stochastic Consolidation's segments are bootstraps in other reserving
    # classes. The load checks each one's freshness, the run re-simulates each
    # one, and the picker scans every class of the project (or of the other
    # project a segment is taken from), so all three are hosted where those
    # files are local disk. The run writes nothing; Save
    # publishes the same run.
    "stochastic_consolidation_load": WorkspaceReadKind(
        "stochastic_consolidation_service",
        "load_stochastic_consolidation_method",
        ("project_name", "reserving_class", "method_name"),
    ),
    "stochastic_consolidation_consolidate": WorkspaceReadKind(
        "stochastic_consolidation_service",
        "consolidate_stochastic_consolidation_method",
        ("project_name", "reserving_class", "method"),
    ),
    "stochastic_consolidation_candidates": WorkspaceReadKind(
        "stochastic_consolidation_service",
        "list_stochastic_consolidation_candidates",
        ("project_name", "reserving_class"),
        ("source_project_name",),
    ),
    # B&S keeps its method JSON on the host API rather than an app-server save
    # path, so this read exists to pair that file with the output sidecar in one
    # visit. ``method_type`` picks the variant's filename prefix.
    "berquist_sherman_load": WorkspaceReadKind(
        "berquist_sherman_service",
        "load_berquist_sherman_method",
        ("project_name", "reserving_class", "method_type", "method_name"),
    ),
    # The whole listing is hosted, including whether each linked workbook can
    # be opened. That answer is deliberately the server host's: a workbook a
    # Client PC can see but Arco Server cannot is one no retarget or refresh
    # can read, so reporting it as found would be a lie.
    "excel_link_listing": WorkspaceReadKind(
        "excel_link_service",
        "list_reserving_class_excel_links",
        ("project_name", "reserving_class"),
    ),
    # The same listing with every usage's status settled by reading the
    # linked cells and comparing them with the stored values. The workbooks
    # are opened on the server host, where the retarget and the refresh open
    # them too; a Client PC reads them over its mapped drive only when no
    # gateway offers the read.
    "excel_link_value_check": WorkspaceReadKind(
        "excel_link_service",
        "check_reserving_class_excel_link_values",
        ("project_name", "reserving_class"),
    ),
    # Every linked workbook cell a window reads: the freshness check an
    # opening Dataset or DFM window runs, a Links-tab refresh, a formula
    # committed in the formula bar. The workbooks open on the server host for
    # the same reason the manager's check opens them there - that host is the
    # one a retarget and a refresh have to be able to read them on. This kind
    # names no project: an item carries the workbook path it asks about, and
    # the read touches no workspace file at all.
    "excel_cell_values": WorkspaceReadKind(
        "excel_service",
        "excel_read_cells_batch",
        ("items",),
    ),
    # The Dependency Graph window's whole diagram: the class index for its
    # nodes plus every sidecar for its edges, assembled where the files are.
    "dataset_dependency_graph": WorkspaceReadKind(
        "dataset_dependency_graph_service",
        "build_reserving_class_dependency_graph",
        ("project_name", "reserving_class"),
    ),
    # Which reserving classes hold data, for the tree's "Hide paths with no
    # data" filter: one listing of the project's data folder plus a check per
    # class, which from a Client PC would be one round trip each.
    "reserving_classes_with_data": WorkspaceReadKind(
        "reserving_class_service",
        "list_reserving_classes_with_data",
        ("project_name",),
    ),
    "table_summary": WorkspaceReadKind(
        "table_summary_service",
        "get_table_summary",
        ("project_name",),
    ),
    # The project's dataset-type table. The Excel add-in's dataset picker is
    # the caller: it lists the types a project defines and has no other way to
    # reach them now that the add-in opens nothing on the share.
    "project_dataset_types": WorkspaceReadKind(
        "dataset_types_service",
        "load_dataset_types_data",
        ("project_name",),
    ),
    # The project names, one project's reserving classes, and its dataset
    # types in one round trip: the Excel add-in's Insert Function panel, Select
    # Datasets, and Load Reserving Classes pick from these and keep them for the
    # Excel session. With no project it answers the project names alone.
    "excel_formula_choices": WorkspaceReadKind(
        "excel_formula_choices_service",
        "list_formula_choices",
        (),
        ("project_name",),
    ),
    # The dataset-type change job and a project duplication are polled while
    # they run. The server reads the status the Engine wrote on its own disk;
    # a Client PC never opens a status file over the share, and a poll the
    # Gateway cannot answer is "unknown" rather than a failed job.
    "dataset_types_change_status": WorkspaceReadKind(
        "dataset_types_change_service",
        "get_dataset_types_change_status",
        ("project_name",),
        ("job_id",),
    ),
    "project_duplication_status": WorkspaceReadKind(
        "project_settings_service",
        "get_duplicate_project_folder_status",
        ("source", "request_id"),
    ),
    # Polling a source-refresh job over the mapped drive reads a file the
    # server rewrote seconds ago, and Windows' directory cache can keep serving
    # the previous copy for several seconds after a terminal status lands. The
    # hosted read answers from the file the Engine actually wrote.
    "source_refresh_status": WorkspaceReadKind(
        "source_refresh_service",
        "get_source_table_refresh_status",
        ("project_name",),
        ("job_id",),
    ),
    # The rules-save job is polled the same way, for the same reason.
    "data_processing_rules_job_status": WorkspaceReadKind(
        "data_processing_rules_job_service",
        "get_data_processing_rules_job_status",
        ("project_name",),
        ("job_id",),
    ),
    # The DFM and Result Selection sync dialogs compare the local method JSON
    # against the copy the Bridge exported from ResQ. Both files live in the
    # workspace, so from a Client PC rendering the review window costs several
    # whole-file SMB reads before anything appears. The kwargs are the route
    # schema's own fields; the service rebuilds its request model from them so
    # validation keeps one owner.
    "dfm_rpc_bridge_compare": WorkspaceReadKind(
        "dfm_rpc_bridge_service",
        "hosted_compare",
        (
            "project_name",
            "reserving_class",
            "method_name",
            "output_vector",
            "input_triangle",
            "origin_length",
            "development_length",
        ),
        ("decimal_places", "timeout_sec"),
    ),
    # Resolving a Dataset window's internal cell links reads one cached
    # dataset per unique referenced name; on the server host those reads are
    # local disk, so a Client PC pays one HTTP round trip instead of one SMB
    # visit per referenced dataset. The optional pair is the period lengths of
    # the grid the references are written in, at which every source is read.
    "dataset_internal_links_resolve": WorkspaceReadKind(
        "dataset_internal_link_service",
        "resolve_dataset_internal_links",
        ("project_name", "reserving_class", "references"),
        ("origin_length", "development_length"),
    ),
    # The ResQ import and sync macros poll the Bridge worker's heartbeat, and
    # the status file of the request it is running, while they wait. Over the
    # mapped drive Windows serves those timestamps from a cache that can lag a
    # heartbeat written every second by ten seconds, so the look is taken on
    # the server host, where it is exact.
    "bridge_worker_liveness": WorkspaceReadKind(
        "bridge_liveness_service",
        "get_bridge_worker_liveness",
        (),
        ("queue", "request_id"),
    ),
    # The Server tab's component panel: every heartbeat under the runtime
    # folder and each role's stop switch, read on the server host so a
    # Client PC never lists the runtime folder over the share.
    "server_component_status": WorkspaceReadKind(
        "server_component_status_service",
        "get_server_component_status",
        (),
    ),
    # The Project Settings audit log table, read from the file the server
    # host's appends write rather than over the share.
    "project_audit_log": WorkspaceReadKind(
        "audit_service",
        "read_audit_log",
        ("project_name",),
        ("limit",),
    ),
    # Project Settings and the project pickers: each is one route's whole
    # response, read where the configuration files are local disk. A Client
    # PC never opens them over the share.
    "project_settings_sources": WorkspaceReadKind(
        "project_settings_service",
        "list_project_settings_sources",
        (),
    ),
    "project_folders": WorkspaceReadKind(
        "project_settings_service",
        "get_project_folders",
        ("source",),
    ),
    "project_registry": WorkspaceReadKind(
        "project_settings_service",
        "get_project_settings",
        ("source",),
    ),
    "project_names": WorkspaceReadKind(
        "arcrho_runtime_service",
        "arcrho_projects",
        (),
    ),
    "general_settings": WorkspaceReadKind(
        "project_settings_service",
        "get_general_settings",
        ("project_name",),
    ),
    "project_lock": WorkspaceReadKind(
        "project_lock_service",
        "get_project_lock",
        ("project_name",),
    ),
    # The grid's own shape of the dataset-type table (``project_dataset_types``
    # above answers the Excel add-in's shape).
    "dataset_types_table": WorkspaceReadKind(
        "dataset_types_service",
        "get_dataset_types_table",
        ("project_name",),
    ),
    "field_mapping": WorkspaceReadKind(
        "field_mapping_service",
        "get_field_mapping",
        ("project_name",),
    ),
    # The import record and master-table status. Whether this PC has a SQL
    # Server driver, and the live stat of an external CSV, stay on the client:
    # the SQL Server import runs there and the CSV may be on a drive only it has.
    "source_table_settings": WorkspaceReadKind(
        "source_table_service",
        "read_source_table_settings",
        ("project_name",),
    ),
    "mssql_connections": WorkspaceReadKind(
        "source_table_service",
        "load_mssql_connections",
        (),
    ),
    # Which parts of a client-only source upload the server holds, so an
    # interrupted upload resumes where it stopped.
    "source_table_upload_status": WorkspaceReadKind(
        "source_table_upload_service",
        "get_source_table_upload_status",
        ("project_name", "upload_id"),
    ),
    "dataset_number_format_defaults": WorkspaceReadKind(
        "dataset_number_format_service",
        "get_preferences",
        (),
        ("dataset_type_name",),
    ),
    # The login comes from the signed request; the display name from the
    # server's username index.
    "user_identity": WorkspaceReadKind(
        "user_identity_service",
        "get_current_identity",
        (),
    ),
    # Both read the master table and the vocabulary cache as they stand and
    # write neither; the source refresh job owns those writes.
    "data_processing_rules": WorkspaceReadKind(
        "data_processing_rules_service",
        "read_data_processing_rules",
        ("project_name",),
    ),
    "data_processing_rules_validate": WorkspaceReadKind(
        "data_processing_rules_service",
        "check_data_processing_rules",
        ("project_name",),
        ("data",),
    ),
    # The reserving-class picker, path tree and types table. Each is one
    # route's whole answer read where the project files are local disk, and
    # none writes: the combinations and the types file are rebuilt by their
    # writers (the source refresh job, a field mapping or types save), never
    # by a read.
    "reserving_class_combinations": WorkspaceReadKind(
        "reserving_class_service",
        "read_reserving_class_combinations",
        ("project_name",),
    ),
    "reserving_class_path_tree_children": WorkspaceReadKind(
        "reserving_class_service",
        "read_reserving_class_path_tree_children",
        ("project_name",),
        ("prefix",),
    ),
    "reserving_class_types": WorkspaceReadKind(
        "reserving_class_service",
        "read_reserving_class_types",
        ("project_name",),
    ),
    # The signed-in user's own preferences: the login is the one the request
    # is signed with, never an argument.
    "reserving_class_hidden_paths": WorkspaceReadKind(
        "reserving_class_service",
        "read_hidden_paths",
        ("project_name",),
    ),
    "reserving_class_filter_spec": WorkspaceReadKind(
        "reserving_class_service",
        "read_filter_spec",
        ("project_name",),
    ),
    "project_user_preferences": WorkspaceReadKind(
        "project_user_preferences_service",
        "get_preferences",
        ("project_name",),
    ),
    # The dataset and method side panels: the sidecar panel, the unsaved
    # dependents preview (it carries the edited grid, which is why the request
    # budget above matches a hosted save's), the DFM's dataset-cell
    # references, and the two development-pattern reads BF, Cape Cod and the
    # % Developed curve window make of a DFM.
    "dataset_sidecar_load": WorkspaceReadKind(
        "dataset_service",
        "load_dataset_sidecar",
        ("project_name", "reserving_class", "dataset_name"),
    ),
    "dataset_calculated_preview": WorkspaceReadKind(
        "calculated_dataset_service",
        "preview_dependents",
        ("project_name", "reserving_class", "changed_dataset_name"),
        ("changed_dataset_type_name", "values", "mask", "origin_labels", "development_labels"),
    ),
    "dfm_dataset_references_resolve": WorkspaceReadKind(
        "dfm_service",
        "resolve_dfm_dataset_references",
        ("project_name", "reserving_class", "references"),
    ),
    "dfm_percent_developed_curve": WorkspaceReadKind(
        "dataset_instance_index_service",
        "get_percent_developed_curve",
        ("project_name", "reserving_class", "method_name"),
    ),
    "dfm_development_pattern": WorkspaceReadKind(
        "dataset_instance_index_service",
        "get_development_pattern",
        ("project_name", "reserving_class", "dataset_name"),
    ),
    # Change detection: an open window's stat-only fingerprint, the writer it
    # names once the fingerprint moved, and the Project Instance table's
    # index.json signature. Each is polled, and a stat over the mapped drive
    # can be seconds stale after a server write, so the server stats its own
    # disk instead.
    "object_change_fingerprint": WorkspaceReadKind(
        "object_change_watch_service",
        "object_change_fingerprint",
        ("project_name", "reserving_class", "kind", "name"),
        ("method_type", "output_dataset"),
    ),
    "object_change_attribution": WorkspaceReadKind(
        "object_change_watch_service",
        "object_change_attribution",
        ("project_name", "reserving_class", "kind", "name"),
        ("method_type", "output_dataset"),
    ),
    "dataset_index_signature": WorkspaceReadKind(
        "dataset_service",
        "get_cached_dataset_index_signature",
        ("project_name", "reserving_class"),
    ),
    # A project's period headings. The settings check, the cache lookup and,
    # on a miss, the Engine run all happen on the server host, so a Client PC
    # neither publishes a request file nor reads the heading CSV.
    "arcrho_headers": WorkspaceReadKind(
        "arcrho_runtime_service",
        "get_project_headers",
        ("project_name", "period_length", "timeout_sec"),
        ("period_type", "transposed", "calendar", "stored_period_length"),
    ),
    # The shared macro library: every published macro's text for the Macro
    # Library window and the automatic update, and one macro's text for a
    # load or the check before a run. The install writes only to this PC's
    # own macros folder.
    "macro_library_listing": WorkspaceReadKind(
        "macro_library_service",
        "read_library_files",
        (),
    ),
    "macro_library_file": WorkspaceReadKind(
        "macro_library_service",
        "read_library_file",
        ("macro_id",),
    ),
    # ArcBot's entry prompt and the team's instruction files, read where the
    # server keeps them; a Client PC neither reads nor seeds them on the share.
    "arcbot_prompt_files": WorkspaceReadKind(
        "arcbot_prompt_service",
        "read_arcbot_prompt_files",
        (),
    ),
    # ArcBot's skills under shared\agent-skills: every skill's menu entry, and
    # with ``skill_id`` that one skill's instructions and reference files.
    "agent_skills": WorkspaceReadKind(
        "agent_skill_service",
        "read_agent_skills",
        (),
        ("skill_id",),
    ),
}

HTTP_WORKSPACE_READ_KINDS: tuple[str, ...] = tuple(sorted(WORKSPACE_READ_KINDS))


def build_workspace_read_request(
    *,
    request_id: str,
    read_kind: str,
    kwargs: Mapping[str, Any],
    user_name: str,
    user_display_name: str = "",
) -> dict[str, Any]:
    return validate_workspace_read_request(
        {
            "Function": WORKSPACE_READ_FUNCTION,
            "ContractVersion": WORKSPACE_READ_CONTRACT_VERSION,
            "RequestId": request_id,
            "ReadKind": read_kind,
            "Kwargs": dict(kwargs),
            "UserName": user_name,
            "UserDisplayName": user_display_name,
        }
    )


def validate_workspace_read_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise WorkspaceReadContractError("A workspace-read request must be a JSON object.")
    if str(payload.get("Function") or "") != WORKSPACE_READ_FUNCTION:
        raise WorkspaceReadContractError("Not a workspace-read request.")
    version = payload.get("ContractVersion")
    if version != WORKSPACE_READ_CONTRACT_VERSION:
        raise WorkspaceReadContractError(
            f"Unsupported workspace-read contract version: {version!r}"
        )
    kind = str(payload.get("ReadKind") or "").strip()
    spec = WORKSPACE_READ_KINDS.get(kind)
    if spec is None:
        raise WorkspaceReadContractError(f"Unknown workspace-read kind: {kind!r}")
    kwargs = payload.get("Kwargs")
    if not isinstance(kwargs, Mapping):
        raise WorkspaceReadContractError("Workspace-read Kwargs must be an object.")
    unexpected = sorted(set(kwargs) - spec.allowed)
    if unexpected:
        raise WorkspaceReadContractError(
            f"Workspace read {kind!r} does not accept: {', '.join(unexpected)}."
        )
    missing = [name for name in spec.required if not str(kwargs.get(name) or "").strip()]
    if missing:
        raise WorkspaceReadContractError(
            f"Workspace read {kind!r} requires: {', '.join(missing)}."
        )
    try:
        request_id = validate_request_id(payload.get("RequestId"))
        # Only logical identifiers travel; a machine-local project folder or a
        # drive-letter reserving-class path is refused before any lookup. A kind
        # that names no project at all — the Bridge-worker liveness look reads
        # only the runtime folder — has nothing to check here, and the required
        # -field check above already refused an empty name where one is needed.
        if "project_name" in spec.allowed and kwargs.get("project_name"):
            validate_project_name(kwargs["project_name"], "project_name")
        if "reserving_class" in spec.allowed and kwargs.get("reserving_class"):
            validate_reserving_class_path(kwargs["reserving_class"])
    except DependentPropagationContractError as exc:
        raise WorkspaceReadContractError(str(exc)) from exc
    return {
        "Function": WORKSPACE_READ_FUNCTION,
        "ContractVersion": WORKSPACE_READ_CONTRACT_VERSION,
        "RequestId": request_id,
        "ReadKind": kind,
        "Kwargs": dict(kwargs),
        "UserName": str(payload.get("UserName") or "").strip(),
        "UserDisplayName": str(payload.get("UserDisplayName") or "").strip(),
    }
