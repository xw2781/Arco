"""Durable, server-local ArcRho dependent propagation.

The Engine runs the canonical dependent cascade
(``app_server.services.calculated_dataset_service.recalculate_dependents``)
where ``E:\\ArcRho Server`` is a local drive. Requests queue under
``requests/dependent_propagation/requests`` and are retained until a validated
terminal status exists; the reserving-class lease serializes Engine instances
per class; concurrent queued requests for the same class are drained and
merged into one walk at claim time.

Failed walks are not auto-retried (policy confirmed 2026-08-06): a terminal
``error`` status is published, downstream objects stay review-needed, and the
next save or manual refresh enqueues a fresh walk. Crash recovery is distinct
from retry — a request whose worker died before publishing a terminal status
is re-claimed after the lease goes stale.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from arcrho_dependent_propagation_contract import (
    DEPENDENT_PROPAGATION_STATUS_HEARTBEAT_SECONDS,
    DependentPropagationContractError,
    acquire_reserving_class_lease,
    dependent_propagation_request_path,
    dependent_propagation_requests_directory,
    dependent_propagation_status_path,
    describe_failed_dependents,
    release_reserving_class_lease,
    reserving_class_identity,
    start_reserving_class_lease_heartbeat,
    stop_reserving_class_lease_heartbeat,
    validate_dependent_propagation_request,
    validate_dependent_propagation_status,
    validate_request_id,
    write_dependent_propagation_status,
)
from arcrho_engine_job_lease import EngineJobLease, engine_job_lease_is_owned

# Path-redaction for shared status text is owned by the sibling durable-job
# module; propagation reuses it rather than growing a second redactor.
from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_engine.bundled_sources import ENGINE_BUNDLED_SOURCES, BUNDLE_DIR_NAME
from arcrho_engine.runtime_log import append_runtime_log

# Wall-clock diary of every walk this instance runs. A propagation that takes
# far longer than its work should is otherwise invisible: the status file keeps
# only the latest progress snapshot, so a phase that stalls leaves nothing
# behind but file timestamps. Each stage transition is stamped with the time
# the previous stage took, which is what localizes a stall to one phase.
DEPENDENT_PROPAGATION_LOG_FILENAME = "dependent_propagation.log"


def _log(server_root: Any, message: str, *, exc: BaseException | None = None) -> None:
    append_runtime_log(
        server_root, DEPENDENT_PROPAGATION_LOG_FILENAME, message, exc=exc
    )


def _walk_outcome_summary(result: Mapping[str, Any]) -> str:
    """Name what the walk touched, per bucket, for the log line.

    The status message a client sees is deliberately redacted and truncated;
    this is the server-local record that keeps the dataset names and the
    unshortened reason for each failure.
    """

    parts: list[str] = []
    updated = [
        str(item.get("dataset_name") or item.get("dataset_type_name") or "").strip()
        for item in result.get("updated") or []
        if isinstance(item, Mapping)
    ]
    skipped = [
        f"{str(item.get('dataset_name') or '').strip()}"
        f"({str(item.get('reason') or '').strip()})"
        for item in result.get("skipped") or []
        if isinstance(item, Mapping)
    ]
    if updated:
        parts.append(f"updated=[{', '.join(name for name in updated if name)}]")
    if skipped:
        parts.append(f"skipped=[{', '.join(skipped)}]")
    for bucket in _METHOD_UPDATE_BUCKETS:
        updates = result.get(bucket)
        if not isinstance(updates, Mapping):
            continue
        refreshed = [str(name).strip() for name in updates.get("refreshed") or []]
        if refreshed:
            parts.append(f"{bucket}=[{', '.join(refreshed)}]")
        for error in updates.get("errors") or []:
            if not isinstance(error, Mapping):
                continue
            name = str(
                error.get("dataset_name") or error.get("method_name") or ""
            ).strip()
            parts.append(f"{bucket} FAILED {name}: {error.get('reason')}")
    index_error = str(result.get("index_error") or "").strip()
    if index_error:
        parts.append(f"index_error={index_error}")
    return " ".join(parts) if parts else "(nothing to refresh)"


Progress = dict[str, Any]


class DependentPropagationJobError(RuntimeError):
    """Raised when a dependent-propagation job cannot run safely."""


class DependentPropagationLeaseLost(DependentPropagationJobError):
    """Raised when another Engine has taken ownership of the reserving class."""


def _progress(stage: str, completed: int, total: int, label: str) -> Progress:
    return {
        "stage": str(stage or "working"),
        "completed": max(0, int(completed)),
        "total": max(0, int(total), int(completed)),
        "label": str(label or stage or "Working"),
    }


def _safe_status_message(exc: Exception) -> str:
    if isinstance(
        exc, (DependentPropagationJobError, DependentPropagationContractError)
    ):
        return _redact_machine_paths(exc) or "Dependent propagation failed."
    if isinstance(exc, OSError):
        return (
            "The Arco Server filesystem could not complete dependent propagation."
        )
    return "Dependent propagation failed."


def canonical_runtime_import_roots() -> tuple[Path, ...]:
    """Return the ``sys.path`` roots holding the bundled canonical sources."""

    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", ".")) / BUNDLE_DIR_NAME
        return tuple(
            bundle_root / bundled.relative_target.parent
            if bundled.is_package
            else bundle_root / bundled.relative_target
            for bundled in ENGINE_BUNDLED_SOURCES
        )
    return tuple(bundled.import_root for bundled in ENGINE_BUNDLED_SOURCES)


def configure_canonical_runtime(server_root: str | os.PathLike[str]) -> None:
    """Point the bundled canonical ``app_server`` at the Engine's server root.

    Mirrors ``resq_import_runner.configure_canonical_runtime``: the runtime
    server-root override must be set before the app-server config is
    (re)loaded, and the bundled source roots must precede any developer
    checkout on ``sys.path`` in a frozen Engine.
    """

    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    os.environ["ARCRHO_RUNTIME_SERVER_ROOT"] = str(root)
    for import_root in reversed(canonical_runtime_import_roots()):
        text = str(import_root)
        if import_root.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
    from app_server import config as app_server_config

    app_server_config.refresh_runtime_paths()
    app_server_config.clear_runtime_path_caches()


def dependent_refresh_failure_reasons(report: Mapping[str, Any]) -> list[str]:
    """Flatten a failed dependent walk into redacted ``"<name>: <reason>"`` lines.

    A walk that is not ``ok`` names every dependent that declined, and why,
    but only inside its nested domain buckets. The durable jobs used to reduce
    that to "the dependent refresh reported errors", which left the real
    reason nowhere a person could read it. The canonical
    ``cascade_failure_reasons`` unwinds those buckets; the lines are redacted
    because they end up in a status file the client shows verbatim.
    """

    flattened: list[str] = []
    for _name, text in dependent_refresh_failures(report):
        if text not in flattened:
            flattened.append(text)
    return flattened


def dependent_refresh_failures(report: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Each declined dependent's name beside its redacted ``"<name>: <reason>"`` line."""

    try:
        from app_server.services import calculated_dataset_service

        pairs = calculated_dataset_service.cascade_failures(report)
    except Exception:
        pairs = []
    failures: list[tuple[str, str]] = []
    for name, reason in pairs:
        line = f"{name}: {reason}" if name and reason else (name or reason)
        text = _redact_machine_paths(str(line))
        if text:
            failures.append((name, text))
    return failures


def dependent_refresh_failure_message(
    reserving_class: str, reasons: Sequence[str]
) -> str:
    """One failure line for a class whose dependent walk reported errors.

    The first reason is spelled out because the client shows the first
    failure as the job message; the count of the rest says whether the log
    holds more.
    """

    prefix = f"{reserving_class}: " if reserving_class else ""
    if not reasons:
        return (
            f"{prefix}the dependent refresh reported errors."
            if prefix
            else "A dependent refresh reported errors."
        )
    suffix = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
    return f"{prefix}{reasons[0]}{suffix}"


def _require_lease(lease: EngineJobLease) -> None:
    if lease.heartbeat_failed.is_set() or not engine_job_lease_is_owned(lease):
        raise DependentPropagationLeaseLost(
            "Dependent propagation reserving-class ownership was lost."
        )


def _read_validated_status(
    server_root: Path, request_id: str
) -> dict[str, Any] | None:
    path = dependent_propagation_status_path(server_root, request_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise DependentPropagationJobError(
            "Existing dependent propagation status could not be validated."
        ) from exc
    try:
        return validate_dependent_propagation_status(
            payload, expected_request_id=request_id
        )
    except DependentPropagationContractError as exc:
        raise DependentPropagationJobError(
            "Existing dependent propagation status could not be validated."
        ) from exc


def _terminal_status(server_root: Path, request_id: str) -> dict[str, Any] | None:
    status = _read_validated_status(server_root, request_id)
    if status is not None and status["status"] in {"success", "error"}:
        return status
    return None


def _terminal_status_or_none(server_root: Path, request_id: str) -> dict[str, Any] | None:
    """Terminal-status check that treats validation trouble as "not terminal"."""

    try:
        return _terminal_status(server_root, request_id)
    except DependentPropagationJobError:
        return None


def _remove_request_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"(dependent propagation queue cleanup error: {exc})")


def _drain_coalescible_requests(
    server_root: Path,
    primary_path: Path,
    primary: Mapping[str, Any],
) -> list[tuple[Path, dict[str, Any]]]:
    """Collect queued sibling requests for the same reserving class.

    Requests arriving after this scan simply run next; the lease serializes
    them, so the drain does not need to be exhaustive — only never wrong.
    """

    identity = reserving_class_identity(primary["ProjectName"], primary["Path"])
    requests_dir = dependent_propagation_requests_directory(server_root)
    try:
        candidates = sorted(
            (item for item in requests_dir.iterdir() if item.is_file()),
            key=lambda item: (item.name.casefold(), item.name),
        )
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        return []

    primary_identity = os.path.normcase(os.path.abspath(os.fspath(primary_path)))
    drained: list[tuple[Path, dict[str, Any]]] = []
    for candidate in candidates:
        if os.path.normcase(os.path.abspath(str(candidate))) == primary_identity:
            continue
        if candidate.suffix.casefold() != ".json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            request = validate_dependent_propagation_request(payload)
        except (OSError, ValueError, TypeError, DependentPropagationContractError):
            continue
        if (
            reserving_class_identity(request["ProjectName"], request["Path"])
            != identity
        ):
            continue
        try:
            if _terminal_status(server_root, request["RequestId"]) is not None:
                continue
        except DependentPropagationJobError:
            continue
        drained.append((candidate, request))
    return drained


def execute_dependent_propagation(
    server_root: str | os.PathLike[str],
    request: Mapping[str, Any],
    *,
    additional_roots: list[Mapping[str, Any]] | None = None,
    progress_callback: Callable[[Progress], None] | None = None,
) -> dict[str, Any]:
    """Run one merged canonical walk for a validated request and return it."""

    normalized = validate_dependent_propagation_request(request)
    configure_canonical_runtime(server_root)
    from app_server.services import calculated_dataset_service, user_identity_service

    roots = list(normalized["ChangedRoots"])
    for extra in additional_roots or []:
        roots.append(
            {
                "dataset_name": str(extra.get("dataset_name") or "").strip(),
                "dataset_type": str(extra.get("dataset_type") or "").strip(),
            }
        )
    first, *rest = [root for root in roots if root.get("dataset_name")]

    request_id = normalized["RequestId"]
    root_names = ", ".join(
        str(root.get("dataset_name") or "") for root in roots if root.get("dataset_name")
    )
    _log(
        server_root,
        f"{request_id} walk start class={normalized['Path']!r} roots=[{root_names}]",
    )
    # Each transition reports how long the stage that just ended took, so a
    # phase that stalls names itself instead of hiding inside one total.
    stage_started = time.monotonic()
    walk_started = stage_started
    previous_stage = "starting"

    def on_tier(stage: str, completed: int, total: int, label: str) -> None:
        nonlocal stage_started, previous_stage
        now = time.monotonic()
        _log(
            server_root,
            f"{request_id} stage {previous_stage} took {now - stage_started:.2f}s"
            f" -> {stage} ({completed}/{total})",
        )
        stage_started = now
        previous_stage = stage
        if progress_callback is not None:
            progress_callback(_progress(stage, completed, total, label))

    # The walk re-saves every dependent dataset it recalculates, and this
    # instance runs under its own service profile: act as the user whose save
    # queued the walk so those sidecars — and the index rows built from them —
    # name the person who made the change. The request carries only the login,
    # so the display name resolves here against the workspace username index,
    # which is local disk for this process.
    with user_identity_service.acting_identity(normalized["UserName"]):
        result = calculated_dataset_service.recalculate_dependents(
            normalized["ProjectName"],
            normalized["Path"],
            first["dataset_name"],
            first["dataset_type"],
            additional_roots=[
                (root["dataset_name"], root["dataset_type"]) for root in rest
            ],
            progress_callback=on_tier,
            rebuild_index=True,
        )
        _log(
            server_root,
            f"{request_id} stage {previous_stage} took"
            f" {time.monotonic() - stage_started:.2f}s (final)",
        )
        _log(
            server_root,
            f"{request_id} walk done in {time.monotonic() - walk_started:.2f}s"
            f" {_walk_outcome_summary(result)}",
        )
        return result


_METHOD_UPDATE_BUCKETS = (
    "dfm_updates",
    "result_selection_updates",
    "berquist_sherman_updates",
    "bornhuetter_ferguson_updates",
    "cape_cod_updates",
    "bootstrap_updates",
)


def _summarize_walk_failure(result: Mapping[str, Any]) -> str:
    failed = describe_failed_dependents(result)
    method_failures: list[str] = []
    for bucket in _METHOD_UPDATE_BUCKETS:
        updates = result.get(bucket)
        if not isinstance(updates, Mapping) or updates.get("ok", True):
            continue
        for error in updates.get("errors") or []:
            if not isinstance(error, Mapping):
                continue
            name = str(
                error.get("dataset_name") or error.get("method_name") or ""
            ).strip()
            reason = str(error.get("reason") or "").strip()
            text = f"{name}: {reason}" if name and reason else (name or reason)
            if text:
                method_failures.append(text)
    parts = []
    if failed:
        parts.append(
            "Dependent update(s) did not refresh: " + "; ".join(failed)
        )
    if method_failures:
        parts.append(
            "Method refresh failure(s): "
            + "; ".join(sorted(set(method_failures)))
        )
    if result.get("index_error"):
        parts.append("The reserving-class index rebuild failed.")
    if not parts:
        parts.append("One or more dependent updates failed.")
    parts.append(
        "Downstream objects remain review-needed; save again or refresh to retry."
    )
    return _redact_machine_paths(" ".join(parts))


def process_durable_dependent_propagation_request(
    server_root: str | os.PathLike[str],
    request_file: str | os.PathLike[str],
    request: Mapping[str, Any],
) -> bool:
    """Process one retained queue file under the reserving-class lease."""

    root = Path(os.fspath(server_root)).expanduser().resolve(strict=False)
    raw_request_id = (
        request.get("RequestId") if isinstance(request, Mapping) else None
    )
    request_path = Path(os.fspath(request_file))
    try:
        request_id = validate_request_id(raw_request_id)
    except DependentPropagationContractError as exc:
        # A request without a safe id can never publish status; drop it so the
        # queue rescan does not reprocess it forever.
        print(f"(dependent propagation request error: {_safe_status_message(exc)})")
        _remove_request_file(request_path)
        return False

    expected_path = dependent_propagation_request_path(root, request_id)
    try:
        if request_path.resolve(strict=False) != expected_path.resolve(strict=False):
            print("(dependent propagation request filename does not match RequestId)")
            return False
    except OSError:
        return False

    try:
        terminal = _terminal_status(root, request_id)
    except DependentPropagationJobError as exc:
        print(f"(dependent propagation status validation will retry: {exc})")
        return False
    if terminal is not None:
        _remove_request_file(request_path)
        return terminal["status"] == "success"

    try:
        normalized = validate_dependent_propagation_request(request)
    except DependentPropagationContractError as exc:
        message = _safe_status_message(exc)
        try:
            write_dependent_propagation_status(
                root,
                request_id,
                "error",
                progress=_progress(
                    "rejected", 0, 0, "Dependent propagation request rejected"
                ),
                message=message,
            )
        except Exception as status_exc:
            print(
                "(error: could not publish rejected dependent propagation status: "
                f"{_redact_machine_paths(status_exc)})"
            )
            return False
        print(f"(dependent propagation request error: {message})")
        _remove_request_file(request_path)
        return False

    # How long a request waited before an instance could claim it. A failed
    # claim is silent otherwise, and the queue file is only re-driven by the
    # 5 s rescan, so a contended class shows up here as repeated claim misses
    # rather than as unexplained wall-clock time in the client.
    try:
        queued_seconds = max(0.0, time.time() - request_path.stat().st_mtime)
    except OSError:
        queued_seconds = float("nan")

    lease = acquire_reserving_class_lease(
        root, normalized["ProjectName"], normalized["Path"]
    )
    if lease is None:
        _log(
            root,
            f"{request_id} claim missed (class busy) after {queued_seconds:.2f}s queued",
        )
        return False
    _log(root, f"{request_id} claimed after {queued_seconds:.2f}s queued")
    claimed_at = time.monotonic()
    heartbeat_stop, heartbeat_thread = start_reserving_class_lease_heartbeat(lease)
    try:
        drained = _drain_coalescible_requests(root, request_path, normalized)
        merged_ids = [item[1]["RequestId"] for item in drained]
        additional_roots: list[dict[str, Any]] = []
        for _path, merged_request in drained:
            additional_roots.extend(merged_request["ChangedRoots"])

        # One lock serializes every status write: walk progress ticks and the
        # status heartbeat below both republish the same files, and a stale
        # heartbeat write must never land after a newer progress write.
        status_write_lock = threading.Lock()

        def publish(
            target_request_id: str,
            status: str,
            progress: Progress,
            *,
            message: str = "",
            merged_into: str | None = None,
        ) -> None:
            _require_lease(lease)
            with status_write_lock:
                write_dependent_propagation_status(
                    root,
                    target_request_id,
                    status,
                    progress=progress,
                    message=message,
                    merged_into=merged_into,
                )

        current_progress = _progress(
            "starting", 0, 0, "Preparing dependent propagation"
        )

        def publish_processing(progress: Progress) -> None:
            publish(request_id, "processing", progress)
            for merged_id in merged_ids:
                publish(
                    merged_id,
                    "processing",
                    progress,
                    merged_into=request_id,
                )

        def publish_progress(progress: Progress) -> None:
            nonlocal current_progress
            current_progress = progress
            publish(request_id, "processing", progress)

        # Remote pollers treat a status whose updated_at stops moving as an
        # abandoned job, so republish the current progress on the contract
        # heartbeat cadence even while one slow step is still running.
        heartbeat_stop_event = threading.Event()

        def status_heartbeat_loop() -> None:
            while not heartbeat_stop_event.wait(
                DEPENDENT_PROPAGATION_STATUS_HEARTBEAT_SECONDS
            ):
                try:
                    publish_processing(current_progress)
                except Exception:
                    # Lease loss or filesystem trouble ends the heartbeat; the
                    # walk thread surfaces the same condition on its next write.
                    return

        status_heartbeat_thread = threading.Thread(
            target=status_heartbeat_loop,
            name=f"arcrho-dependent-propagation-status-{request_id[:8]}",
            daemon=True,
        )

        try:
            publish_processing(current_progress)
            status_heartbeat_thread.start()
            try:
                result = execute_dependent_propagation(
                    root,
                    normalized,
                    additional_roots=additional_roots,
                    progress_callback=publish_progress,
                )
            finally:
                heartbeat_stop_event.set()
                status_heartbeat_thread.join(
                    timeout=DEPENDENT_PROPAGATION_STATUS_HEARTBEAT_SECONDS * 2
                )
            if result.get("ok"):
                terminal_state = "success"
                terminal_message = ""
                terminal_progress = _progress(
                    "complete", 1, 1, "Dependent updates complete"
                )
            else:
                terminal_state = "error"
                terminal_message = _summarize_walk_failure(result)
                terminal_progress = current_progress
        except DependentPropagationLeaseLost:
            _log(root, f"{request_id} reserving-class ownership was lost")
            return False
        except Exception as exc:
            terminal_state = "error"
            terminal_message = _safe_status_message(exc)
            terminal_progress = current_progress
            # The status message is redacted for the client; the log keeps the
            # real exception and its traceback.
            _log(root, f"{request_id} walk raised: {terminal_message}", exc=exc)

        _log(
            root,
            f"{request_id} {terminal_state} after {time.monotonic() - claimed_at:.2f}s"
            f" held (merged={len(drained)})"
            + (f": {terminal_message}" if terminal_message else ""),
        )
        try:
            publish(request_id, terminal_state, terminal_progress, message=terminal_message)
        except Exception as status_exc:
            _log(
                root,
                "could not publish dependent propagation status: "
                f"{_redact_machine_paths(status_exc)}",
                exc=status_exc,
            )
            return False
        if _terminal_status_or_none(root, request_id) is not None:
            _remove_request_file(request_path)

        for merged_path, merged_request in drained:
            merged_id = merged_request["RequestId"]
            try:
                publish(
                    merged_id,
                    terminal_state,
                    terminal_progress,
                    message=terminal_message,
                    merged_into=request_id,
                )
            except Exception as status_exc:
                print(
                    "(error: could not publish merged dependent propagation status: "
                    f"{_redact_machine_paths(status_exc)})"
                )
                continue
            if _terminal_status_or_none(root, merged_id) is not None:
                _remove_request_file(merged_path)
        return terminal_state == "success"
    except DependentPropagationLeaseLost:
        return False
    finally:
        stop_reserving_class_lease_heartbeat(heartbeat_stop, heartbeat_thread)
        release_reserving_class_lease(lease)
