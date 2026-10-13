"""Contract for Arco Server-hosted workspace mutations.

``arcrho_workspace_read_contract`` hosts reads, whose defining property is that
they are pure functions of the workspace: an uncertain answer may simply be
asked again, or answered locally instead. A mutation cannot borrow that
reasoning, so it gets its own registry and its own route rather than being
smuggled into the read table.

Only allowlisted kinds may execute remotely, and every registered kind must
either be **idempotent** -- running it twice against the same workspace leaves
the end state of running it once, so an answer the client never saw is either
already applied or safe to ask for again -- or be marked ``receipt``. A receipt
kind (create, rename or delete a project folder, a registry save checked
against the revision it read) could not be run twice safely, so the Gateway
keeps one receipt per signed user and request id: the first run records its
outcome, and a repeat of the same request under that id answers from the
receipt instead of running again, while a different request under the same id
is refused with 409. For a receipt kind the request id names the user's action,
not the HTTP attempt, so a retry after a lost answer reuses it. Receipts live
beside the hosted-save receipts and expire with them. Anything that needs an
Engine claim belongs on the hosted-save path
(``arcrho_hosted_save_http_contract``).

What the client may *not* do is fall back to its own mapped drive after the
server may already have acted. Reads fall back freely; a mutation whose outcome
is unknown must be reported, not repeated somewhere else, because the second
run would answer about a workspace the first one already changed.

Mutations run under the submitting user's identity so the audit trail, sidecar
stamps, and log lines name the person who asked rather than the Gateway's
service profile.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from arcrho_dependent_propagation_contract import (
    DependentPropagationContractError,
    validate_project_name,
    validate_request_id,
    validate_reserving_class_path,
)


WORKSPACE_MUTATION_FUNCTION = "ArcRhoWorkspaceMutation"
WORKSPACE_MUTATION_CONTRACT_VERSION = 1
WORKSPACE_MUTATION_PATH = "/api/workspace-mutations"
WORKSPACE_MUTATION_CAPABILITY_FIELD = "workspace_mutation_kinds"
# A mutation removes or rewrites files in one reserving class and rebuilds that
# class's index; it never waits on the Engine, so it needs no save-sized budget.
WORKSPACE_MUTATION_TIMEOUT_SECONDS = 180.0
MAX_WORKSPACE_MUTATION_REQUEST_BYTES = 256 * 1024


class WorkspaceMutationContractError(ValueError):
    """Raised when a workspace-mutation payload violates this contract."""


@dataclass(frozen=True)
class WorkspaceMutationKind:
    """One remotely executable, idempotent ``app_server.services`` mutation."""

    module: str
    function: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    # Arguments whose value is a list of names rather than a single string.
    # Named here so validation checks the right shape instead of coercing a
    # list to ``str`` and silently accepting "['a', 'b']" as one dataset.
    list_args: tuple[str, ...] = field(default_factory=tuple)
    # True for a kind that is not idempotent: the Gateway answers a repeated
    # request id from its stored receipt instead of running the kind again.
    receipt: bool = False
    # The argument naming the project whose shared data this kind changes.
    # Set, the kind is refused while that project is locked
    # (``project_lock_service``); empty for kinds that leave project data
    # alone, such as a user's own preferences or a regenerable cache.
    locked_project_arg: str = ""

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.required + self.optional)


# The RPC-bridge kinds take their route schema's own fields, so the service can
# rebuild its request model from them and pydantic stays the single validator.
_DFM_RPC_BRIDGE_REQUIRED: tuple[str, ...] = (
    "project_name",
    "reserving_class",
    "method_name",
    "output_vector",
    "input_triangle",
    "origin_length",
    "development_length",
)
_DFM_RPC_BRIDGE_OPTIONAL: tuple[str, ...] = ("decimal_places", "timeout_sec")

# A hosted mutation that waits for the Bridge holds a Gateway worker thread for
# the duration, so the caller's budget is clamped into this range rather than
# trusted. The frontend asks for 8 s today; the ceiling exists so a client
# cannot pin a thread for minutes.
MIN_RPC_BRIDGE_WAIT_SECONDS = 0.1
MAX_RPC_BRIDGE_WAIT_SECONDS = 60.0


def clamp_rpc_bridge_wait(timeout_sec: Any) -> float:
    """Return the wait a hosted RPC-bridge exchange may hold a thread for."""

    try:
        wait = float(timeout_sec)
    except (TypeError, ValueError) as exc:
        raise WorkspaceMutationContractError("timeout_sec must be a number.") from exc
    if wait != wait:  # NaN
        raise WorkspaceMutationContractError("timeout_sec must be a number.")
    return min(MAX_RPC_BRIDGE_WAIT_SECONDS, max(MIN_RPC_BRIDGE_WAIT_SECONDS, wait))


# kind -> canonical service mutation. The Gateway resolves mutations only
# through this table; a request naming anything else, or passing an argument
# not listed here, is rejected before any import happens.
WORKSPACE_MUTATION_KINDS: dict[str, WorkspaceMutationKind] = {
    "propagation_submit": WorkspaceMutationKind(
        "dependent_propagation_service", "submit_dependent_propagation_job",
        ("project_name", "reserving_class", "changed_roots", "request_id"),
    ),
    # Deleting a cached dataset removes its files and rebuilds the reserving
    # class index. It is idempotent because a file that is already gone is
    # skipped rather than failed, and the rebuild derives the index from
    # whatever survives; a repeat therefore reports "nothing matched" against
    # an end state identical to the first run's.
    "cached_dataset_delete": WorkspaceMutationKind(
        "dataset_service",
        "delete_cached_datasets",
        ("project_name", "reserving_class", "dataset_names"),
        list_args=("dataset_names",),
        locked_project_arg="project_name",
    ),
    # Setting the review flag of method outputs rewrites one sidecar per
    # selected object, so from a Client PC it is a read and a write per object
    # over the share; hosted, it is local disk. It changes no values and
    # propagates nothing, which is why it is a mutation rather than a save.
    #
    # Idempotent because an object already carrying the requested flag is
    # reported unchanged rather than rewritten, so a repeat leaves the same
    # status, timestamp, user and audit record the first run wrote. The one
    # audit entry a real change appends names the decision itself rather than
    # the default "Values", since the sign-off moved nothing. ``status`` is optional
    # because the required check reads an integer 0 as absent; a request that
    # omits it marks for review, which is the direction that can never
    # silently clear someone's sign-off.
    "dataset_review_status_set": WorkspaceMutationKind(
        "dataset_service",
        "set_dataset_review_status",
        ("project_name", "reserving_class", "dataset_names"),
        ("status",),
        list_args=("dataset_names",),
        locked_project_arg="project_name",
    ),
    # Submitting a source-table refresh publishes two small files into the
    # Engine's queue. It is idempotent because the client owns the request id:
    # an id that already has a published status is returned as-is rather than
    # queued a second time, so a lost response can never start a second import.
    # ``reserving_class_types`` is a list of ``{Name, Level}`` objects rather
    # than names, so it is not a list arg; the source-refresh contract
    # validates its shape when the request is built.
    "source_table_refresh_submit": WorkspaceMutationKind(
        "source_refresh_service",
        "submit_source_table_refresh_job",
        ("project_name", "request_id"),
        (
            "import_source",
            "force",
            "refresh_dependents",
            "dataset_types",
            "reserving_class_types",
        ),
        list_args=("dataset_types",),
        locked_project_arg="project_name",
    ),
    # Submitting a data-processing-rules save publishes two small files into
    # the Engine's queue, idempotent by the client-owned request id exactly as
    # the source refresh above. ``expected_revision`` may be 0 and ``rules``
    # may be an empty list (the user removed every rule), and the required
    # check reads both as absent, so they are listed as optional here and the
    # rules-job contract enforces their shape when the request is built.
    "data_processing_rules_save_submit": WorkspaceMutationKind(
        "data_processing_rules_job_service",
        "submit_data_processing_rules_job",
        ("project_name", "request_id"),
        ("expected_revision", "rules"),
        locked_project_arg="project_name",
    ),
    # The DFM sync dialog publishes a request file the Arco Bridge claims,
    # then waits for the JSON the Bridge exports from ResQ. Both halves are
    # server-local for the Bridge and both cross SMB for a Client PC, where the
    # publish is several round trips and every wait tick writes and deletes a
    # probe file so the redirector cannot serve a cached "not found". Hosted,
    # the request lands on local disk and the wait is a file-system event.
    #
    # Idempotent: the stale response and status files are deleted first, and a
    # repeat regenerates the same export from the same ResQ method. A second
    # run costs a duplicate ResQ export, never a divergent workspace.
    "dfm_rpc_bridge_sync": WorkspaceMutationKind(
        "dfm_rpc_bridge_service",
        "hosted_send_sync_request",
        _DFM_RPC_BRIDGE_REQUIRED,
        _DFM_RPC_BRIDGE_OPTIONAL,
    ),
    # Deleting the temporary response and status JSON. Idempotent because a
    # file that is already gone is skipped rather than failed.
    "dfm_rpc_bridge_cleanup": WorkspaceMutationKind(
        "dfm_rpc_bridge_service",
        "hosted_cleanup_tmp",
        _DFM_RPC_BRIDGE_REQUIRED,
        _DFM_RPC_BRIDGE_OPTIONAL,
    ),
    # Keeping the local method and discarding the remote export: the same
    # delete, with the message the dialog reports.
    "dfm_rpc_bridge_keep_local": WorkspaceMutationKind(
        "dfm_rpc_bridge_service",
        "hosted_keep_local",
        _DFM_RPC_BRIDGE_REQUIRED,
        _DFM_RPC_BRIDGE_OPTIONAL,
    ),
    # Writing the local method's owned settings back into the RPC server. This
    # is the one kind whose effect lands outside the workspace, so it carries
    # the transport rule most strictly: once the Gateway has accepted the
    # request, an ambiguous outcome is reported, never retried over SMB.
    # Idempotent in the sense the contract requires: a repeat writes the same
    # values from the same local method and saves again. The confirmation flag
    # is optional here on purpose: a false value must reach the service so both
    # transports refuse it with the same message.
    "dfm_rpc_bridge_update_remote": WorkspaceMutationKind(
        "dfm_rpc_bridge_service",
        "hosted_update_remote",
        _DFM_RPC_BRIDGE_REQUIRED,
        _DFM_RPC_BRIDGE_OPTIONAL + ("rpc_server_write_confirmed",),
    ),
    # The Sync and Export Reserving Class with ResQ macros publish one request
    # file into the Bridge's sync queue. Hosted, that write lands on the
    # server's local disk instead of crossing the share from a Client PC.
    # Idempotent because the client owns the request id: an id that already
    # has a request or a status file is returned as-is rather than published
    # again, so a lost response can never queue a second run. A reviewed
    # synchronization sends back the rows exactly as the preview reported them;
    # a whole-class transfer sends the direction it is reviewing, or the names
    # that review ticked.
    "resq_sync_request_publish": WorkspaceMutationKind(
        "resq_sync_queue_service",
        "publish_resq_sync_request",
        ("project_name", "reserving_class", "request_id", "phase"),
        ("selected_rows", "selected_names", "direction"),
    ),
    # The ResQ import macros hand their request to the Bridge the same way.
    # The macro owns the request it builds; the server only checks that the
    # request names this project, class and id, stamps the signed user, and
    # writes it into the import queue. Idempotent by request id, like the sync
    # publish.
    "resq_review_request_publish": WorkspaceMutationKind(
        "resq_import_queue_service", "publish_resq_review_request",
        ("project_name", "reserving_class", "request_id", "request"),
    ),
    "resq_import_request_publish": WorkspaceMutationKind(
        "resq_import_queue_service",
        "publish_resq_import_request",
        ("project_name", "reserving_class", "request_id", "request"),
        locked_project_arg="project_name",
    ),
    # Both ResQ import macros copy the reserving class they are about to
    # rewrite into the server's pre-import backups. That copy is one file per
    # method, sidecar and data file, so from a Client PC it is a round trip
    # each; hosted, the whole copy is local disk and the macro pays one
    # request.
    #
    # Idempotent because the client owns the backup id: an id whose copy this
    # host already finished -- which its manifest records -- is reported as it
    # stands rather than copied again under a second folder. A copy that died
    # part way leaves no manifest and is never presented as a restore point.
    "resq_import_backup": WorkspaceMutationKind(
        "resq_import_backup_service",
        "back_up_reserving_class_for_import",
        ("project_name", "reserving_class", "backup_id"),
        ("import_policy",),
    ),
    # Appending one entry to the project's audit log. Over the share each PC
    # read, changed and rewrote the whole file under a lock that covered only
    # its own process, so two PCs lost each other's entries; hosted, every
    # append passes the Gateway's one lock. Idempotent because the client owns
    # the entry id: an id already in the log is answered from the log rather
    # than appended again.
    "project_audit_log_append": WorkspaceMutationKind(
        "audit_service",
        "append_project_audit_log",
        ("project_name", "action", "entry_id"),
        ("user_name",),
    ),
    # The signed-in user's own project preferences. The login is the one the
    # request is signed with, never an argument, so a user can only write
    # their own file. Idempotent because each is a whole-value write: hidden
    # paths and the filter spec (with the tree preferences when sent) replace
    # the stored value outright, and a preferences patch sets each value it
    # names, so a repeat lands the same state and only ``updated_at`` moves.
    # The lists and objects may be empty (the user cleared them), so they are
    # optional rather than required.
    "reserving_class_hidden_paths_save": WorkspaceMutationKind(
        "reserving_class_service",
        "save_hidden_paths",
        ("project_name",),
        ("hidden_paths",),
    ),
    "reserving_class_filter_spec_save": WorkspaceMutationKind(
        "reserving_class_service",
        "save_filter_spec",
        ("project_name",),
        ("filter_spec", "preferences"),
    ),
    "project_user_preferences_update": WorkspaceMutationKind(
        "project_user_preferences_service",
        "update_preferences",
        ("project_name",),
        ("patch",),
    ),
    # Deleting a project's period-heading caches so the Engine rebuilds them.
    # Idempotent: a repeat finds the files already gone.
    "arcrho_headers_cache_clear": WorkspaceMutationKind(
        "arcrho_runtime_service",
        "clear_arcrho_headers_cache",
        ("project_name",),
        ("origin_length", "development_length"),
    ),
    # Project Settings writes. Creating, renaming and deleting a project
    # folder and saving the registry are not idempotent -- a repeated create
    # or rename meets the folder the first run made and refuses with 409, and
    # a repeated registry save meets the revision the first run moved -- so
    # they carry a receipt and a repeat answers with the first outcome. The
    # General Settings save is a whole-value write but appends an audit entry
    # each run, so it carries one too. Clearing the generated CSV caches is
    # idempotent: a repeat finds nothing left to clear and writes no audit
    # entry. ``source`` is the registry key (``project_map``); the lists and
    # the revision may be empty or 0, so they are optional.
    "project_folder_create": WorkspaceMutationKind(
        "project_settings_service",
        "create_project_folder",
        ("source", "name"),
        receipt=True,
    ),
    "project_folder_rename": WorkspaceMutationKind(
        "project_settings_service",
        "rename_project_folder",
        ("source", "old_name", "new_name"),
        receipt=True,
        locked_project_arg="old_name",
    ),
    "project_folder_delete": WorkspaceMutationKind(
        "project_settings_service",
        "delete_project_folder",
        ("source", "name"),
        receipt=True,
        locked_project_arg="name",
    ),
    "project_registry_save": WorkspaceMutationKind(
        "project_settings_service",
        "update_project_settings",
        ("source",),
        ("folders", "project_paths", "expected_revision"),
        receipt=True,
    ),
    "general_settings_save": WorkspaceMutationKind(
        "project_settings_service",
        "update_general_settings",
        ("project_name",),
        ("origin_start_date", "origin_end_date", "development_end_date", "auto_generated"),
        receipt=True,
        locked_project_arg="project_name",
    ),
    # Locking or unlocking the project. A whole-value write that appends an
    # audit entry each run, so it carries a receipt like General Settings.
    "project_lock_set": WorkspaceMutationKind(
        "project_lock_service",
        "set_project_lock",
        ("project_name",),
        ("locked",),
        receipt=True,
    ),
    "generated_dataset_cache_clear": WorkspaceMutationKind(
        "project_settings_service",
        "clear_generated_dataset_csv_caches",
        ("source", "project_name"),
    ),
    # The workspace-wide dataset number-format defaults. The save is checked
    # against the revision the window read and moves it, so a repeat would
    # meet its own revision and refuse with 409: it carries a receipt. The
    # revision may be 0 and the overrides empty, so both are optional.
    "dataset_number_format_defaults_save": WorkspaceMutationKind(
        "dataset_number_format_service",
        "save_preferences",
        ("default_number_format",),
        ("expected_revision", "overrides"),
        receipt=True,
    ),
    # Saving the dataset-type table. The server decides what the change needs:
    # a plan to confirm (a read), a direct write of a presentation-only change,
    # or a queued Engine job. It needs no receipt: the job is keyed by the
    # client's request id, so a replay returns the job already queued, and the
    # direct write is a whole-table write that skips an unchanged table, so a
    # replay writes nothing and appends no second audit entry. The request id
    # is also the mutation's own. The rows, renames and plan may be empty.
    "dataset_types_save": WorkspaceMutationKind(
        "dataset_types_change_service",
        "save_dataset_types",
        ("project_name", "request_id"),
        ("rows", "renames", "plan"),
        locked_project_arg="project_name",
    ),
    # Submitting a project duplication is idempotent by its request id through
    # the duplication's own submission receipt, which binds the id to one
    # source and target, so it needs no Gateway receipt on top. Cancelling
    # writes an advisory marker; a repeat writes the same marker, and a job
    # already finished is reported as it is.
    "project_duplication_submit": WorkspaceMutationKind(
        "project_settings_service",
        "duplicate_project_folder",
        ("source", "old_name", "new_name", "request_id"),
    ),
    "project_duplication_cancel": WorkspaceMutationKind(
        "project_settings_service",
        "cancel_duplicate_project_folder",
        ("source", "request_id"),
    ),
    # Source Data writes. The field mapping, import profile and reserving
    # class types saves each append an audit entry, so they carry a receipt.
    # A CSV path reaches the server already translated from this PC's drive
    # letter into the share it stands for: the translation needs the client's
    # own drive mapping, so it is done there and sent as data. The path
    # rewrite changes the stored path only while it still reads ``from_path``,
    # so a repeat finds it done and writes nothing. Rebuilding the table
    # summary and reserving-class values derives both from the imported table
    # alone, and remembering or forgetting a SQL Server pair sets the same
    # list again, so those are idempotent. The rows and columns may be empty.
    "field_mapping_save": WorkspaceMutationKind(
        "field_mapping_service",
        "save_field_mapping",
        ("project_name",),
        ("table_path", "rows"),
        receipt=True,
        locked_project_arg="project_name",
    ),
    "source_profile_save": WorkspaceMutationKind(
        "source_table_service",
        "save_source_profile",
        ("project_name", "source_type"),
        ("mssql", "csv_path"),
        receipt=True,
        locked_project_arg="project_name",
    ),
    # A combined source (several tables joined into one) is saved whole; its
    # CSV paths arrive translated to the share, like ``csv_path`` above.
    "source_combined_save": WorkspaceMutationKind(
        "source_table_service",
        "save_combined_source",
        ("project_name", "combined"),
        receipt=True,
        locked_project_arg="project_name",
    ),
    # The Import Scope choice saved without an import. Setting the same scope
    # again records the same lists, so it needs no receipt; an empty scope is
    # sent as absent arguments and records "everything".
    "source_scope_save": WorkspaceMutationKind(
        "source_table_service",
        "record_refresh_scope",
        ("project_name",),
        ("dataset_types", "reserving_class_types"),
        locked_project_arg="project_name",
    ),
    "source_csv_path_rewrite": WorkspaceMutationKind(
        "source_table_service",
        "rewrite_source_csv_path",
        ("project_name", "from_path", "csv_path"),
        locked_project_arg="project_name",
    ),
    "reserving_class_types_save": WorkspaceMutationKind(
        "reserving_class_service",
        "save_reserving_class_types",
        ("project_name",),
        ("columns", "rows"),
        receipt=True,
        locked_project_arg="project_name",
    ),
    "table_summary_rebuild": WorkspaceMutationKind(
        "table_summary_service",
        "rebuild_table_summary",
        ("project_name",),
        ("refresh_reserving",),
    ),
    "mssql_connection_remember": WorkspaceMutationKind(
        "source_table_service",
        "remember_mssql_connection",
        ("server", "database"),
    ),
    "mssql_connection_forget": WorkspaceMutationKind(
        "source_table_service",
        "forget_mssql_connection",
        ("server",),
        ("database",),
    ),
    # Uploading a source table only the client can read (a SQL Server import
    # run as the user's own login, or a CSV on a drive only that PC has). Each
    # chunk is stored as its numbered part of the upload, so a resent chunk
    # overwrites the same part. The commit checks the chunk count, byte total
    # and row count, swaps the master table in atomically and keeps its
    # outcome with the upload, so a repeated commit answers from it rather
    # than importing twice. ``index`` and ``row_count`` may be 0, which the
    # required check reads as absent, so they are optional here and the
    # service requires them.
    "source_table_upload_chunk": WorkspaceMutationKind(
        "source_table_upload_service",
        "receive_source_table_chunk",
        ("project_name", "upload_id", "data"),
        ("index",),
        locked_project_arg="project_name",
    ),
    "source_table_upload_commit": WorkspaceMutationKind(
        "source_table_upload_service",
        "commit_source_table_upload",
        ("project_name", "upload_id", "source_type", "chunk_count", "byte_count"),
        ("row_count", "csv_path", "csv_mtime_ns", "csv_size"),
        locked_project_arg="project_name",
    ),
}

HTTP_WORKSPACE_MUTATION_KINDS: tuple[str, ...] = tuple(sorted(WORKSPACE_MUTATION_KINDS))


def build_workspace_mutation_request(
    *,
    request_id: str,
    mutation_kind: str,
    kwargs: Mapping[str, Any],
    user_name: str,
    user_display_name: str = "",
) -> dict[str, Any]:
    return validate_workspace_mutation_request(
        {
            "Function": WORKSPACE_MUTATION_FUNCTION,
            "ContractVersion": WORKSPACE_MUTATION_CONTRACT_VERSION,
            "RequestId": request_id,
            "MutationKind": mutation_kind,
            "Kwargs": dict(kwargs),
            "UserName": user_name,
            "UserDisplayName": user_display_name,
        }
    )


def _validate_list_arg(kind: str, name: str, value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise WorkspaceMutationContractError(
            f"Workspace mutation {kind!r} expects {name!r} to be a list of names."
        )
    names = [str(item or "").strip() for item in value]
    names = [item for item in names if item]
    if not names:
        raise WorkspaceMutationContractError(
            f"Workspace mutation {kind!r} requires at least one {name!r} entry."
        )
    return names


def validate_workspace_mutation_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise WorkspaceMutationContractError("A workspace-mutation request must be a JSON object.")
    if str(payload.get("Function") or "") != WORKSPACE_MUTATION_FUNCTION:
        raise WorkspaceMutationContractError("Not a workspace-mutation request.")
    version = payload.get("ContractVersion")
    if version != WORKSPACE_MUTATION_CONTRACT_VERSION:
        raise WorkspaceMutationContractError(
            f"Unsupported workspace-mutation contract version: {version!r}"
        )
    kind = str(payload.get("MutationKind") or "").strip()
    spec = WORKSPACE_MUTATION_KINDS.get(kind)
    if spec is None:
        raise WorkspaceMutationContractError(f"Unknown workspace-mutation kind: {kind!r}")
    kwargs = payload.get("Kwargs")
    if not isinstance(kwargs, Mapping):
        raise WorkspaceMutationContractError("Workspace-mutation Kwargs must be an object.")
    unexpected = sorted(set(kwargs) - spec.allowed)
    if unexpected:
        raise WorkspaceMutationContractError(
            f"Workspace mutation {kind!r} does not accept: {', '.join(unexpected)}."
        )

    normalized_kwargs = dict(kwargs)
    missing = [
        name
        for name in spec.required
        if name not in spec.list_args and not str(kwargs.get(name) or "").strip()
    ]
    if missing:
        raise WorkspaceMutationContractError(
            f"Workspace mutation {kind!r} requires: {', '.join(missing)}."
        )
    for name in spec.list_args:
        if name in spec.required or name in kwargs:
            normalized_kwargs[name] = _validate_list_arg(kind, name, kwargs.get(name))

    try:
        request_id = validate_request_id(payload.get("RequestId"))
        # Only logical identifiers travel; a machine-local project folder or a
        # drive-letter reserving-class path is refused before any lookup.
        if "project_name" in spec.allowed:
            validate_project_name(normalized_kwargs.get("project_name"), "project_name")
        if "reserving_class" in spec.allowed and normalized_kwargs.get("reserving_class"):
            validate_reserving_class_path(normalized_kwargs["reserving_class"])
    except DependentPropagationContractError as exc:
        raise WorkspaceMutationContractError(str(exc)) from exc
    return {
        "Function": WORKSPACE_MUTATION_FUNCTION,
        "ContractVersion": WORKSPACE_MUTATION_CONTRACT_VERSION,
        "RequestId": request_id,
        "MutationKind": kind,
        "Kwargs": normalized_kwargs,
        "UserName": str(payload.get("UserName") or "").strip(),
        "UserDisplayName": str(payload.get("UserDisplayName") or "").strip(),
    }
