"""One appender for every Arco Engine runtime log.

The Engine is packaged with ``--noconsole``, so a bare ``print`` is lost on
every deployed machine: whatever a job does not write here leaves no trace at
all, and a failure can only be reconstructed from file timestamps afterwards.

Logging must never change what a job does. Every error is swallowed, including
a failed rotation, so a full disk or a locked log can never fail the work the
log was only meant to describe.
"""

from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from arcrho_log_retention_contract import prune_aged_log_files

RUNTIME_LOG_RELATIVE_DIR = ("runtime", "logs")
# Where a calculation request records what the Engine could not take, and what
# it read that disagreed with the project's own record.
ENGINE_REQUEST_LOG_FILENAME = "engine_requests.log"
# One megabyte keeps a busy day readable in an editor while still covering far
# more than the handful of jobs anyone diagnoses at once. One rotation is kept.
RUNTIME_LOG_MAX_BYTES = 1024 * 1024


def runtime_log_directory(server_root: str | os.PathLike[str]) -> Path:
    return Path(os.fspath(server_root)).joinpath(*RUNTIME_LOG_RELATIVE_DIR)


def runtime_log_path(server_root: str | os.PathLike[str], filename: str) -> Path:
    return runtime_log_directory(server_root) / filename


def prune_runtime_logs(server_root: str | os.PathLike[str]) -> int:
    """Drop the runtime logs no one has written to inside the retention window.

    Size rotation keeps one live log small; this is what removes the file of a
    job kind that stopped running months ago. Call it once as a component
    starts.
    """

    return prune_aged_log_files(runtime_log_directory(server_root))


def append_runtime_log(
    server_root: str | os.PathLike[str],
    filename: str,
    message: str,
    *,
    exc: BaseException | None = None,
) -> None:
    """Append one timestamped line, rotating at :data:`RUNTIME_LOG_MAX_BYTES`.

    ``exc`` appends the full traceback. Timestamps are UTC so lines from
    several machines sort against each other.
    """

    try:
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        line = f"{stamp} {message}\n"
        if exc is not None:
            line += "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        path = runtime_log_path(server_root, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size > RUNTIME_LOG_MAX_BYTES:
                os.replace(path, path.with_name(f"{path.name}.1"))
        except OSError:
            pass
        with open(path, mode="a", encoding="utf-8") as stream:
            stream.write(line)
    except Exception:
        pass
