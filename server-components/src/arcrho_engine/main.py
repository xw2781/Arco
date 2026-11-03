import os
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

# Resolve packaged, deployed src layout, and repo src layout.
_MODULE_ROOT = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_ROOT.parent
_REPO_CANONICAL_ROOT = _SOURCE_ROOT.parent.parent / "python-api" / "src"
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", _MODULE_ROOT)).resolve()

for _path in (_SOURCE_ROOT, _REPO_CANONICAL_ROOT, _BUNDLE_ROOT):
    if not _path.exists():
        continue
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from arcrho_data_processing_rules_job_contract import DATA_PROCESSING_RULES_JOB_FUNCTION
from arcrho_dataset_types_change_contract import DATASET_TYPES_CHANGE_FUNCTION
from arcrho_dependent_propagation_contract import DEPENDENT_PROPAGATION_FUNCTION
from arcrho_engine_save_contract import SAVE_JOB_FUNCTION
from arcrho_project_dates_job_contract import PROJECT_DATES_JOB_FUNCTION
from arcrho_project_duplication_contract import PROJECT_DUPLICATION_FUNCTION
from arcrho_source_refresh_contract import SOURCE_REFRESH_FUNCTION
from utils import get_config_value, get_project_root, normalize_function_name

os.environ.setdefault("ARCRHO_ROOT", str(get_project_root()))

from arcrho_engine.data_processing import (
    PROJECT_CONFIG,
    PROJECT_CONFIG_LOCK,
    ProjectSettingsError,
    UDF_ADASHeaders,
    UDF_ADASProjectSettings,
    UDF_ADASTri,
    _get_vps_last_modified_time,
    debug_mode,
    get_project_table_path,
    id_path,
    load_to_PROJECT_CONFIG,
    project_exists,
    remove_old_instances,
    robot_id,
)
from arcrho_engine.data_processing_rules import (
    DataProcessingConfigurationError,
    DataProcessingRulesError,
)
from arcrho_engine.general_utils import (
    get_current_time,
    read_json,
    safe_remove,
    write_json,
    write_lists_to_csv,
)
from arcrho_engine.data_processing_rules_jobs import (
    process_durable_data_processing_rules_request,
)
from arcrho_engine.dataset_types_change import (
    process_durable_dataset_types_change_request,
)
from arcrho_engine.dependent_propagation import (
    process_durable_dependent_propagation_request,
)
from arcrho_engine.project_dates_jobs import (
    process_durable_project_dates_request,
)
from arcrho_engine.project_duplication import (
    process_durable_project_duplication_request,
)
from arcrho_engine.source_table_refresh import (
    process_durable_source_refresh_request,
)
from arcrho_engine.save_jobs import process_hosted_save_request
from arcrho_engine.runtime_log import (
    ENGINE_REQUEST_LOG_FILENAME,
    append_runtime_log,
    prune_runtime_logs,
)


class _DurableJobDispatcher:
    """One bounded background worker for a durable, retained-queue job type.

    Long jobs must never block the legacy calculation queue, so each durable
    job type (project duplication, dependent propagation) gets its own daemon
    thread. Requests that cannot be admitted are simply dropped here — the
    retained queue file is re-offered by the 5 s rescan cycle.
    """

    def __init__(self, *, thread_name: str, execute, queue_capacity: int = 1):
        self._thread_name = thread_name
        self._execute = execute
        self._state_lock = Lock()
        self._pending: set[tuple[str, str]] = set()
        self.queue: Queue[tuple[tuple[str, str], str, dict]] = Queue(
            maxsize=max(1, int(queue_capacity))
        )
        self._stop = Event()
        self._thread: Thread | None = None

    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        thread = Thread(target=self._run, name=self._thread_name, daemon=True)
        self._thread = thread
        thread.start()

    def schedule(self, key: tuple[str, str], file_path, arg) -> bool:
        with self._state_lock:
            if self._stop.is_set():
                return False
            if key in self._pending:
                return True
            if self.queue.full():
                return False
            self._pending.add(key)
            self._ensure_worker()
            try:
                self.queue.put_nowait((key, os.fspath(file_path), dict(arg)))
            except Full:
                self._pending.discard(key)
                return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                key, file_path, arg = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                if not self._stop.is_set():
                    self._execute(file_path, arg)
            finally:
                with self._state_lock:
                    self._pending.discard(key)
                self.queue.task_done()

    def shutdown(self, *, wait: bool = True, timeout: float | None = None) -> bool:
        with self._state_lock:
            self._stop.set()
        while True:
            try:
                key, _file_path, _arg = self.queue.get_nowait()
            except Empty:
                break
            with self._state_lock:
                self._pending.discard(key)
            self.queue.task_done()

        thread = self._thread
        if wait and thread is not None:
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()


class RequestHandler(FileSystemEventHandler):

    def __init__(
        self,
        *,
        duplication_queue_capacity: int = 1,
        propagation_queue_capacity: int = 1,
        hosted_save_queue_capacity: int = 4,
        source_refresh_queue_capacity: int = 1,
        dataset_types_change_queue_capacity: int = 1,
        data_processing_rules_queue_capacity: int = 1,
        project_dates_queue_capacity: int = 1,
    ):
        super().__init__()
        self._processing_lock = Lock()
        # Loose request files this instance could not read, logged once each:
        # the 5 s rescan re-offers such a file until the orchestrator sweeps
        # it, and every Engine sees it, so per-attempt logging would flood.
        self._unreadable_requests: set[str] = set()
        self._duplication = _DurableJobDispatcher(
            thread_name="arcrho-project-duplication-worker",
            execute=self._execute_project_duplication,
            queue_capacity=duplication_queue_capacity,
        )
        self._propagation = _DurableJobDispatcher(
            thread_name="arcrho-dependent-propagation-worker",
            execute=self._execute_dependent_propagation,
            queue_capacity=propagation_queue_capacity,
        )
        # Hosted saves are interactive: they get their own worker so a long
        # propagation walk queued on this instance never delays a user's save.
        self._hosted_save = _DurableJobDispatcher(
            thread_name="arcrho-hosted-save-worker",
            execute=self._execute_hosted_save,
            queue_capacity=hosted_save_queue_capacity,
        )
        # A source refresh regenerates every engine dataset in a project and
        # then walks each class's dependents. It gets its own worker so that
        # long job never occupies the propagation slot a user's save needs.
        self._source_refresh = _DurableJobDispatcher(
            thread_name="arcrho-source-refresh-worker",
            execute=self._execute_source_refresh,
            queue_capacity=source_refresh_queue_capacity,
        )
        # A dataset-type change holds the whole project while it rebuilds every
        # sidecar's dependency graph. It gets its own worker for the same
        # reason a source refresh does: that long job must never occupy the
        # propagation slot a user's save needs.
        self._dataset_types_change = _DurableJobDispatcher(
            thread_name="arcrho-dataset-types-change-worker",
            execute=self._execute_dataset_types_change,
            queue_capacity=dataset_types_change_queue_capacity,
        )
        # A rules save is short but interactive: its own worker keeps it from
        # queueing behind a long dataset-type change or source refresh.
        self._data_processing_rules = _DurableJobDispatcher(
            thread_name="arcrho-data-processing-rules-worker",
            execute=self._execute_data_processing_rules,
            queue_capacity=data_processing_rules_queue_capacity,
        )
        # A project dates change regenerates and reshapes the whole project,
        # so it gets its own worker like a source refresh does.
        self._project_dates = _DurableJobDispatcher(
            thread_name="arcrho-project-dates-worker",
            execute=self._execute_project_dates,
            queue_capacity=project_dates_queue_capacity,
        )

    @property
    def _duplication_queue(self) -> Queue:
        return self._duplication.queue

    @property
    def _propagation_queue(self) -> Queue:
        return self._propagation.queue

    @staticmethod
    def _duplication_key(file_path, arg) -> tuple[str, str]:
        request_id = str(arg.get("RequestId") or "").strip()
        if request_id:
            return ("request_id", request_id)
        return (
            "request_path",
            os.path.normcase(os.path.abspath(os.fspath(file_path))),
        )

    def _schedule_project_duplication(self, file_path, arg) -> bool:
        """Schedule one durable request without blocking legacy calculations."""

        return self._duplication.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _schedule_dependent_propagation(self, file_path, arg) -> bool:
        return self._propagation.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_project_duplication(self, file_path, arg) -> None:
        try:
            process_durable_project_duplication_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(project duplication request error: {exc})")

    def _execute_dependent_propagation(self, file_path, arg) -> None:
        try:
            process_durable_dependent_propagation_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(dependent propagation request error: {exc})")

    def _schedule_hosted_save(self, file_path, arg) -> bool:
        return self._hosted_save.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_hosted_save(self, file_path, arg) -> None:
        try:
            process_hosted_save_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(hosted save request error: {exc})")

    def _schedule_source_refresh(self, file_path, arg) -> bool:
        return self._source_refresh.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_source_refresh(self, file_path, arg) -> None:
        try:
            process_durable_source_refresh_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(source refresh request error: {exc})")

    def _schedule_dataset_types_change(self, file_path, arg) -> bool:
        return self._dataset_types_change.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_dataset_types_change(self, file_path, arg) -> None:
        try:
            process_durable_dataset_types_change_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(dataset types change request error: {exc})")

    def _schedule_data_processing_rules(self, file_path, arg) -> bool:
        return self._data_processing_rules.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_data_processing_rules(self, file_path, arg) -> None:
        try:
            process_durable_data_processing_rules_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(data processing rules job request error: {exc})")

    def _schedule_project_dates(self, file_path, arg) -> bool:
        return self._project_dates.schedule(
            self._duplication_key(file_path, arg), file_path, arg
        )

    def _execute_project_dates(self, file_path, arg) -> None:
        try:
            process_durable_project_dates_request(
                get_project_root(),
                file_path,
                arg,
            )
        except Exception as exc:
            print(f"(project dates job request error: {exc})")

    def shutdown(self, *, wait: bool = True, timeout: float | None = None) -> bool:
        """Stop accepting durable jobs and optionally wait for active work."""

        duplication_stopped = self._duplication.shutdown(wait=wait, timeout=timeout)
        propagation_stopped = self._propagation.shutdown(wait=wait, timeout=timeout)
        hosted_save_stopped = self._hosted_save.shutdown(wait=wait, timeout=timeout)
        source_refresh_stopped = self._source_refresh.shutdown(
            wait=wait, timeout=timeout
        )
        dataset_types_change_stopped = self._dataset_types_change.shutdown(
            wait=wait, timeout=timeout
        )
        data_processing_rules_stopped = self._data_processing_rules.shutdown(
            wait=wait, timeout=timeout
        )
        project_dates_stopped = self._project_dates.shutdown(wait=wait, timeout=timeout)
        return (
            duplication_stopped
            and propagation_stopped
            and hosted_save_stopped
            and source_refresh_stopped
            and dataset_types_change_stopped
            and data_processing_rules_stopped
            and project_dates_stopped
        )

    def _process_event_path(self, event, file_path):
        if event.is_directory:
            return
        if not str(file_path).lower().endswith(".json"):
            return

        # Process request immediately in the watchdog event thread.
        self.process_file_debug(file_path)

    def on_created(self, event):
        # Excel normally publishes with an atomic move, but its compatibility
        # fallback copies directly to the final .json path.
        self._process_event_path(event, event.src_path)

    def on_moved(self, event):
        self._process_event_path(event, event.dest_path)

    def process_file_debug(self, file_path):
        if debug_mode == 0:
            try:
                self.process_file(file_path, dispatch_duplication=True)
            except Exception as e:
                print(e)
        else:
            self.process_file(file_path, dispatch_duplication=True)

    def _note_unreadable_request(self, file_path, exc: BaseException) -> None:
        """Log a request file that exists but cannot be read, once per file.

        A file that is gone was claimed by another Engine and is not news. One
        that stays but will not parse is: no instance will ever claim it, its
        publisher waits out the whole timeout, and until now nothing recorded
        why.
        """

        key = os.path.normcase(os.path.abspath(os.fspath(file_path)))
        try:
            if not os.path.exists(file_path):
                self._unreadable_requests.discard(key)
                return
        except OSError:
            return
        if key in self._unreadable_requests:
            return
        self._unreadable_requests.add(key)
        # Forget files that have since been swept so the set cannot grow
        # without bound on a long-running instance.
        for stale in [
            item for item in self._unreadable_requests if not os.path.exists(item)
        ]:
            self._unreadable_requests.discard(stale)
        message = (
            f"unreadable request left unclaimed: {os.path.basename(str(file_path))}: "
            f"{type(exc).__name__}: {exc}"
        )
        print(f"(error: {message})")
        append_runtime_log(get_project_root(), ENGINE_REQUEST_LOG_FILENAME, message)

    def process_file(self, file_path, *, dispatch_duplication: bool = False):
        try:
            arg = read_json(file_path)
        except FileNotFoundError:
            # Another Engine claimed the request first.
            return
        except Exception as exc:
            self._note_unreadable_request(file_path, exc)
            return

        # Durable jobs retain their queue file until a validated terminal
        # status exists. Their renewable leases own cross-Engine claiming and
        # crash recovery; legacy requests continue to use delete-to-claim
        # below. The ``dispatch_duplication`` flag selects async dispatch for
        # every durable job type; direct callers remain synchronous for
        # deterministic tests and administrative one-shot processing.
        function_name_raw = str(arg.get("Function") or "").strip()
        if function_name_raw == PROJECT_DUPLICATION_FUNCTION:
            if dispatch_duplication:
                self._schedule_project_duplication(file_path, arg)
            else:
                self._execute_project_duplication(file_path, arg)
            return
        if function_name_raw == DEPENDENT_PROPAGATION_FUNCTION:
            if dispatch_duplication:
                self._schedule_dependent_propagation(file_path, arg)
            else:
                self._execute_dependent_propagation(file_path, arg)
            return
        if function_name_raw == SOURCE_REFRESH_FUNCTION:
            if dispatch_duplication:
                self._schedule_source_refresh(file_path, arg)
            else:
                self._execute_source_refresh(file_path, arg)
            return
        if function_name_raw == DATASET_TYPES_CHANGE_FUNCTION:
            if dispatch_duplication:
                self._schedule_dataset_types_change(file_path, arg)
            else:
                self._execute_dataset_types_change(file_path, arg)
            return
        if function_name_raw == DATA_PROCESSING_RULES_JOB_FUNCTION:
            if dispatch_duplication:
                self._schedule_data_processing_rules(file_path, arg)
            else:
                self._execute_data_processing_rules(file_path, arg)
            return
        if function_name_raw == PROJECT_DATES_JOB_FUNCTION:
            if dispatch_duplication:
                self._schedule_project_dates(file_path, arg)
            else:
                self._execute_project_dates(file_path, arg)
            return
        if function_name_raw == SAVE_JOB_FUNCTION:
            # Hosted saves claim by delete inside the executor; scheduling
            # keeps the watchdog event thread free like other durable jobs.
            if dispatch_duplication:
                self._schedule_hosted_save(file_path, arg)
            else:
                self._execute_hosted_save(file_path, arg)
            return

        with self._processing_lock:
            self._process_legacy_request(file_path, arg)

    def calculate_in_process(self, arg) -> None:
        """Run one calculation request for the canonical runtime on this Engine.

        A durable job on this instance (a source refresh materialising a
        precedent at another period, a hosted save) used to publish a request
        file to the shared folder and wait for an Engine -- possibly this one
        -- to claim it, paying the watchdog round trip and the whole timeout
        whenever no instance picked the file up. The canonical runtime calls
        this instead. It runs the same functions under the same serialisation
        the legacy path uses and raises where that path would write an error
        CSV; the caller turns the exception into the outcome it reports.
        """

        function_name = normalize_function_name(arg.get("Function"))
        project_name = str(arg.get("ProjectName") or "").strip()
        with self._processing_lock:
            if not project_name or not project_exists(project_name):
                raise FileNotFoundError(f"project not found: {project_name or 'unnamed'}")
            get_project_table_path(project_name)
            _refresh_project_config(project_name)
            if function_name in ("ADASTri", "ADASVec"):
                UDF_ADASTri(arg)
            elif function_name == "ADASProjectSettings":
                UDF_ADASProjectSettings(arg)
            elif function_name == "ADASHeaders":
                UDF_ADASHeaders(arg)
            else:
                raise ValueError(f"invalid function name: {arg.get('Function')!r}")

    def _process_legacy_request(self, file_path, arg):

        # Every engine sees the same filesystem event.  Reading is safe, but
        # exactly one engine must atomically remove (claim) the request before
        # doing validation or writing any output.
        try:
            if not safe_remove(file_path):
                return
        except Exception:  # Already removed by another engine.
            return

        if not _write_request_status(arg, "processing"):
            # A caller that supplied StatusPath relies on the processing marker
            # to distinguish this worker from the legacy CSV-only protocol.
            return

        project_name = str(arg.get("ProjectName") or "").strip()
        try:
            if not project_name:
                raise FileNotFoundError("ProjectName is missing")
            if not project_exists(project_name):
                raise FileNotFoundError(project_name)
            get_project_table_path(project_name)
        except Exception as exc:
            message = f"(project not found: {project_name or exc})"
            _finish_request_error(arg, message, [[message]])
            return

        if debug_mode == 1:
            print(arg)

        print(
            f"\n> {get_current_time()} \n> new request # {robot_id} "
            f"# user [{arg.get('UserName', '')}]"
        )

        # Check project configuration updates (guarded).
        try:
            _refresh_project_config(project_name)
        except DataProcessingConfigurationError as e:
            print(str(e))
            message = f"(data processing configuration error: {e})"
            _finish_request_error(
                arg,
                message,
                [[f"(data processing configuration error: {e})"]],
            )
            return
        except Exception as e:
            if debug_mode:
                import traceback
                traceback.print_exc()
            message = f"(error: {str(e).upper()})"
            _finish_request_error(arg, message, [[0]])
            return

        # Go to Functions
        try:
            function_name = normalize_function_name(arg.get('Function'))
            if function_name in ['ADASTri', 'ADASVec']:
                UDF_ADASTri(arg)
            elif function_name == 'ADASProjectSettings':
                UDF_ADASProjectSettings(arg)
            elif function_name == 'ADASHeaders':
                UDF_ADASHeaders(arg)
            else:
                message = "(invalid function name)"
                _finish_request_error(arg, message, [[message]])
                return

        except DataProcessingRulesError as e:
            print(str(e))
            message = f"(data processing rules error: {e})"
            _finish_request_error(
                arg,
                message,
                [[f"(data processing rules error: {e})"]],
            )
            return

        except DataProcessingConfigurationError as e:
            print(str(e))
            message = f"(data processing configuration error: {e})"
            _finish_request_error(
                arg,
                message,
                [[f"(data processing configuration error: {e})"]],
            )
            return

        except ProjectSettingsError as e:
            print(str(e))
            _finish_request_error(
                arg,
                f"project settings not defined: {e}",
                [['project settings not defined']],
            )
            return

        except Exception as e:
            if debug_mode:
                import traceback
                traceback.print_exc()
                print(arg)
            message = f"(error: {str(e).upper()})"
            print(message)
            _finish_request_error(arg, message, [[0]])
            return

        _write_request_status(arg, "success")
        print(f"> request completed @ {get_current_time().split(' ')[1]}")


def _queued_request_files(directory: Path) -> list[Path]:
    try:
        return sorted(
            (item for item in directory.iterdir() if item.is_file()),
            key=lambda item: (item.name.casefold(), item.name),
        )
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as exc:
        print(f"(existing request scan error: {exc})")
        return []


def process_existing_requests(
    path: str | os.PathLike[str],
    handler: RequestHandler,
) -> None:
    """Process requests that were queued while this Engine was offline.

    The dependent-propagation, source-refresh and dataset-type change queues
    live in subfolders (so the orchestrator's loose-file garbage collection
    cannot touch them) that the non-recursive watchdog observer never reports;
    this rescan is their only intake, on the same 5 s cycle that re-drives
    retained duplication files.
    """

    request_dir = Path(path)
    queued_paths = _queued_request_files(request_dir)
    queued_paths.extend(
        _queued_request_files(request_dir / "dependent_propagation" / "requests")
    )
    queued_paths.extend(
        _queued_request_files(request_dir / "source_table_refresh" / "requests")
    )
    queued_paths.extend(
        _queued_request_files(request_dir / "dataset_types_change" / "requests")
    )
    queued_paths.extend(
        _queued_request_files(request_dir / "data_processing_rules" / "requests")
    )
    queued_paths.extend(
        _queued_request_files(request_dir / "project_dates" / "requests")
    )
    for queued_path in queued_paths:
        if queued_path.suffix.casefold() == ".json":
            try:
                handler.process_file_debug(str(queued_path))
            except Exception as exc:
                print(f"(existing request recovery error: {exc})")


def recover_existing_requests(
    path: str | os.PathLike[str],
    handler: RequestHandler,
    stop_event: Event,
    *,
    interval_seconds: float = 5.0,
) -> None:
    """Rescan until shutdown so transient startup failures cannot strand jobs."""

    while not stop_event.is_set():
        try:
            process_existing_requests(path, handler)
        except Exception as exc:
            print(f"(existing request recovery error: {exc})")
        if stop_event.wait(max(0.1, float(interval_seconds))):
            return


def _refresh_project_config(project_name: str) -> None:
    """Reload the project's virtual settings when their signature has moved on.

    A project whose settings were never loaded is left alone: the first
    calculation loads them on demand.
    """

    with PROJECT_CONFIG_LOCK:
        if project_name + " - Version" in PROJECT_CONFIG:
            project_config_signature = _get_vps_last_modified_time(project_name)
            if PROJECT_CONFIG[project_name + " - Version"] != project_config_signature:
                load_to_PROJECT_CONFIG(project_name)
                print(
                    f">>> Virtual Project Settings Updated -> "
                    f"[{project_name} JSON]\n"
                )


def _write_request_status(arg, status, message=""):
    """Atomically publish optional request status without affecting legacy callers."""

    status_path = str(arg.get("StatusPath") or "").strip()
    if not status_path:
        return True

    payload = {
        "status": str(status),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    request_id = str(arg.get("RequestId") or "").strip()
    if request_id:
        payload["request_id"] = request_id
    if message:
        payload["message"] = str(message)

    try:
        if write_json(status_path, payload):
            return True
        print(f"(error: could not write request status to {status_path})")
    except Exception as exc:
        print(f"(error: could not write request status to {status_path}: {exc})")
    return False


def _finish_request_error(arg, message, csv_rows):
    """Preserve the legacy error CSV and publish terminal status when requested."""

    status_message = str(message)
    try:
        write_lists_to_csv(arg.get("DataPath"), csv_rows)
    except Exception as exc:
        status_message = f"{status_message}; failed to write error CSV: {exc}"
        print(status_message)
    finally:
        _write_request_status(arg, "error", status_message)


def _remove_instance_heartbeat():
    try:
        if os.path.exists(id_path):
            safe_remove(id_path)
    except Exception:
        pass


def _register_in_process_calculator(handler: RequestHandler) -> None:
    """Let the canonical runtime run local exchanges through this Engine itself."""

    try:
        from app_server.services import engine_calculation_service

        engine_calculation_service.set_in_process_calculator(handler.calculate_in_process)
        print("(in-process calculator registered)")
    except Exception as exc:
        print(f"(in-process calculator not registered: {exc})")


def _warm_canonical_runtime(handler: RequestHandler | None = None) -> None:
    """Pre-import the bundled app_server stack in the background at boot.

    The first hosted save or propagation walk on a cold frozen instance
    otherwise pays tens of seconds of one-time import cost (pandas plus the
    canonical services) while a user waits on the save popup. Once the stack
    is up, the Engine's own calculation entry point is registered with it so
    a job here never has to post a request file to itself.
    """

    try:
        from arcrho_engine.dependent_propagation import configure_canonical_runtime

        configure_canonical_runtime(get_project_root())
        if handler is not None:
            _register_in_process_calculator(handler)
        from app_server.services import (  # noqa: F401
            bootstrap_service,
            bornhuetter_ferguson_service,
            calculated_dataset_service,
            cape_cod_service,
            dataset_service,
            dependent_propagation_service,
            dfm_service,
            result_selection_service,
        )
        print('(canonical runtime warmed)')
    except Exception as exc:
        print(f'(canonical runtime warmup failed: {exc})')


def start_monitoring(path):
    prune_runtime_logs(get_project_root())
    event_handler = RequestHandler()
    observer = Observer()
    observer.schedule(event_handler, path, recursive=False)
    observer.start()
    print('Server ID: ' + robot_id + '\n')

    Thread(
        target=_warm_canonical_runtime,
        args=(event_handler,),
        name="arcrho-canonical-runtime-warmup",
        daemon=True,
    ).start()

    remove_old_instances()

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    write_json(id_path, {'Server': robot_id, 'Last seen': current_time})

    recovery_stop = Event()
    recovery_thread = Thread(
        target=recover_existing_requests,
        args=(path, event_handler, recovery_stop),
        name="arcrho-existing-request-recovery",
        daemon=True,
    )
    recovery_thread.start()

    try:
        while True:

            if not observer.is_alive():
                _remove_instance_heartbeat()
                break

            if not os.path.exists(id_path):
                observer.stop(); break

            if get_config_value('apps.engine.kill_all'):
                os.remove(id_path)
                observer.stop(); break

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Update Status
            arg_1 = read_json(id_path)
            arg_1['Last seen'] = current_time
            write_json(id_path, arg_1)

            time.sleep(5)

    except KeyboardInterrupt:
        observer.stop()
    finally:
        recovery_stop.set()
        observer.stop()
        observer.join()
        recovery_thread.join()
        event_handler.shutdown(wait=True, timeout=None)


if __name__ == "__main__":
    start_monitoring(str(get_project_root() / "requests"))
