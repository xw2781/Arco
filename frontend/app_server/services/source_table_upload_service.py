"""Uploading a source table only this PC can read into the project on the server.

A SQL Server import authenticates as the user's own Windows login, and a CSV
source may sit on a drive only this PC has, so both are read here (decision 3
of docs/plans/client_smb_retirement.md). Only the master-table write moves: the
rows travel to the Gateway in numbered chunks and the server writes the table,
so a Client PC never writes the share.

One upload is:

* **Chunks.** Raw CSV bytes, cut into blocks of ``RAW_CHUNK_BYTES``, each sent
  compressed as one ``source_table_upload_chunk`` mutation, well inside the
  mutation size limit. A chunk is stored as its numbered part under
  ``requests\\source_table_upload\\<user>\\<upload id>`` on the server, so a
  resent chunk overwrites the same part and a repeat is harmless.
* **Status.** ``source_table_upload_status`` answers which parts the server
  holds, so an interrupted CSV upload resumes where it stopped.
* **Commit.** ``source_table_upload_commit`` names the chunk count, the byte
  total and the row count the client read. The server assembles the parts
  into the master table's staging file, refuses anything short or different
  (decision 5: counts, no checksum), swaps it in atomically, writes the import
  record, remembers the SQL Server pair, appends the audit entry and removes
  the parts. The outcome is kept with the upload, so a repeated commit answers
  from it. Uploads older than the Gateway's receipt window are removed when a
  new one starts.

Both halves live in this module: the client functions call the server ones
through the Gateway, and a server process calls them directly.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import shutil
import threading
import time
import uuid
import zlib
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from fastapi import HTTPException

from arcrho_api.source_table_contract import (
    SOURCE_TYPE_COMBINED,
    SOURCE_TYPE_CSV,
    SOURCE_TYPE_MSSQL,
    combined_source_label,
    csv_identity,
    mssql_source_label,
)
from arcrho_hosted_save_http_contract import DEFAULT_RECEIPT_RETENTION_HOURS, user_path_segment
from arcrho_project_duplication_contract import validate_request_id
from arcrho_workspace_mutation_contract import MAX_WORKSPACE_MUTATION_REQUEST_BYTES

from arcrho_api.timestamps import utc_now_text
from app_server import config
from app_server.services import (
    source_refresh_service,
    source_table_service,
    workspace_mutation_client,
    workspace_read_client,
)
from app_server.services.audit_service import safe_append_project_audit_log
from app_server.services.user_identity_service import get_windows_login_name


# Raw CSV bytes per chunk. The Fake project's table compresses about 2.4 times
# at level 1 (measured 2026-09-27), so a block of this size is one request of
# at most about 145 KiB; a block that does not compress enough is halved until
# each piece fits. Level 1 compresses the whole table in about a second, four
# times faster than the default for a few percent more bytes.
RAW_CHUNK_BYTES = 256 * 1024
_COMPRESSION_LEVEL = 1
# The compressed, base64-encoded chunk text; the rest of a signed mutation
# request is a few hundred bytes.
MAX_ENCODED_CHUNK_CHARS = MAX_WORKSPACE_MUTATION_REQUEST_BYTES - 16 * 1024
# A SQL Server block ends at the row that crosses RAW_CHUNK_BYTES, so a chunk
# expands back to a little more than that; anything past this bound is refused.
MAX_DECODED_CHUNK_BYTES = 4 * RAW_CHUNK_BYTES
UPLOAD_RETENTION_HOURS = DEFAULT_RECEIPT_RETENTION_HOURS

_PART_PREFIX = "part-"
_COMMIT_FILE = "commit.json"


# --- Shared by both halves --------------------------------------------------

class RowCounter:
    """Data rows in a CSV stream fed as bytes: lines after the header.

    The client counts what it sends and the server counts what it assembled
    with this same rule, so the commit compares like with like.
    """

    def __init__(self) -> None:
        self.bytes = 0
        self._newlines = 0
        self._last = b""

    def feed(self, data: bytes) -> None:
        if data:
            self.bytes += len(data)
            self._newlines += data.count(b"\n")
            self._last = data[-1:]

    @property
    def rows(self) -> int:
        lines = self._newlines + (1 if self._last not in (b"", b"\n") else 0)
        return max(0, lines - 1)


def encode_chunk(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data, _COMPRESSION_LEVEL)).decode("ascii")


def decode_chunk(text: str) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        data = decompressor.decompress(base64.b64decode(str(text or ""), validate=True), MAX_DECODED_CHUNK_BYTES)
        if decompressor.unconsumed_tail or not decompressor.eof:
            raise ValueError("chunk is too large or truncated")
    except (ValueError, zlib.error) as error:
        raise HTTPException(400, f"The uploaded chunk could not be read: {error}") from error
    return data


# --- Server half ------------------------------------------------------------

def _upload_id(upload_id: Any) -> str:
    try:
        return validate_request_id(upload_id)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


def _uploads_root() -> Path:
    return Path(config.get_root_path()) / "requests" / "source_table_upload"


def _upload_dir(upload_id: Any) -> Path:
    return _uploads_root() / user_path_segment(get_windows_login_name()) / _upload_id(upload_id)


def _part_path(folder: Path, index: int) -> Path:
    return folder / f"{_PART_PREFIX}{index:06d}"


def _held_parts(folder: Path) -> Dict[int, int]:
    held: Dict[int, int] = {}
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return held
    for entry in entries:
        suffix = entry.name[len(_PART_PREFIX):]
        if entry.name.startswith(_PART_PREFIX) and suffix.isdigit():
            held[int(suffix)] = entry.stat().st_size
    return held


def _read_commit(folder: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads((folder / _COMMIT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _prune_abandoned_uploads() -> None:
    """Remove every user's uploads older than the receipt window; best effort."""
    cutoff = time.time() - UPLOAD_RETENTION_HOURS * 3600
    root = _uploads_root()
    try:
        users = [entry for entry in os.scandir(root) if entry.is_dir()]
    except OSError:
        return
    for user in users:
        try:
            uploads = [entry for entry in os.scandir(user.path) if entry.is_dir()]
        except OSError:
            continue
        for upload in uploads:
            try:
                if upload.stat().st_mtime < cutoff:
                    shutil.rmtree(upload.path, ignore_errors=True)
            except OSError:
                continue


def receive_source_table_chunk(
    project_name: str,
    upload_id: str,
    data: str,
    index: Optional[int] = None,
) -> Dict[str, Any]:
    """Store one numbered chunk; a resent chunk overwrites the same part."""
    source_table_service._require_project_name(project_name)
    try:
        position = int(index)
    except (TypeError, ValueError):
        raise HTTPException(400, "The chunk index is required.")
    if position < 0:
        raise HTTPException(400, "The chunk index must not be negative.")
    raw = decode_chunk(data)
    folder = _upload_dir(upload_id)
    if not folder.is_dir():
        _prune_abandoned_uploads()
        folder.mkdir(parents=True, exist_ok=True)
    part = _part_path(folder, position)
    temporary = part.with_name(f"{part.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, part)
    return {"ok": True, "upload_id": folder.name, "index": position, "bytes": len(raw)}


def get_source_table_upload_status(project_name: str, upload_id: str) -> Dict[str, Any]:
    """Which parts the server holds, and the outcome once committed."""
    source_table_service._require_project_name(project_name)
    folder = _upload_dir(upload_id)
    return {
        "ok": True,
        "upload_id": folder.name,
        "parts": {str(index): size for index, size in sorted(_held_parts(folder).items())},
        "committed": _read_commit(folder) is not None,
    }


def _refuse(staging_path: str, status: int, detail: str) -> None:
    source_table_service._discard_staging(staging_path)
    raise HTTPException(status, detail)


def commit_source_table_upload(
    project_name: str,
    upload_id: str,
    source_type: str,
    chunk_count: int,
    byte_count: int,
    row_count: Optional[int] = None,
    csv_path: str = "",
    csv_mtime_ns: Optional[int] = None,
    csv_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Swap the uploaded parts in as the master table, checked by counts.

    The previous master table stays untouched until every part is present and
    the assembled bytes and rows match what the client read; the swap itself
    is one rename, so no reader ever sees a half-written table. A combined
    source must already be saved; its label comes from that saved record.
    """
    name = source_table_service._require_project_name(project_name)
    kind = str(source_type or "").strip().lower()
    if kind not in (SOURCE_TYPE_CSV, SOURCE_TYPE_MSSQL, SOURCE_TYPE_COMBINED):
        raise HTTPException(400, f"Unknown source type: {source_type}")
    try:
        expected_chunks, expected_bytes, expected_rows = int(chunk_count), int(byte_count), int(row_count)
    except (TypeError, ValueError):
        raise HTTPException(400, "The commit must name the chunk count, the byte total and the row count.")
    folder = _upload_dir(upload_id)
    master_path = source_table_service.resolve_master_table_path(name)
    staging_path = source_table_service._staging_path(master_path)

    with source_table_service._project_lock(name):
        committed = _read_commit(folder)
        if committed is not None:
            return committed
        if source_refresh_service.get_source_table_refresh_status(name).get("busy"):
            raise HTTPException(423, source_refresh_service.SOURCE_REFRESH_BUSY_MESSAGE)
        record = source_table_service.read_source_import(name)
        profile = None
        if kind == SOURCE_TYPE_MSSQL:
            profile = source_table_service._require_complete_mssql_profile(record.get("mssql"))
        elif kind == SOURCE_TYPE_COMBINED and record.get("source_type") != SOURCE_TYPE_COMBINED:
            raise HTTPException(400, "Save the combined source before importing it.")
        held = _held_parts(folder)
        if set(held) != set(range(expected_chunks)):
            arrived = len(set(held) & set(range(expected_chunks)))
            raise HTTPException(
                409, f"The upload is incomplete: {arrived} of {expected_chunks} parts reached the server."
            )

        os.makedirs(os.path.dirname(master_path), exist_ok=True)
        counter = RowCounter()
        try:
            with open(staging_path, "wb") as target:
                for index in range(expected_chunks):
                    data = _part_path(folder, index).read_bytes()
                    counter.feed(data)
                    target.write(data)
        except OSError as error:
            _refuse(staging_path, 500, f"Failed to assemble the uploaded table: {error}")
        if counter.bytes != expected_bytes or counter.rows != expected_rows:
            _refuse(
                staging_path,
                409,
                f"The uploaded table does not match what was read: {counter.bytes:,} bytes and "
                f"{counter.rows:,} rows arrived, {expected_bytes:,} bytes and {expected_rows:,} rows were sent.",
            )
        try:
            source_table_service._commit_master(master_path, staging_path)
        except PermissionError:
            _refuse(staging_path, 423, "The imported table file is locked. Another user may have it open.")
        except OSError as error:
            _refuse(staging_path, 500, f"Failed to write the imported table: {error}")

        last_import: Dict[str, Any] = {
            "source_type": kind,
            "imported_at": utc_now_text(),
            "imported_by": get_windows_login_name(),
            "row_count": counter.rows,
            "column_count": source_table_service._master_column_count(master_path),
        }
        if profile is not None:
            last_import["source_label"] = mssql_source_label(profile)
            updates: Dict[str, Any] = {"source_type": kind, "mssql": profile}
        elif kind == SOURCE_TYPE_COMBINED:
            last_import["source_label"] = combined_source_label(record.get("combined"))
            updates = {"source_type": kind}
        else:
            last_import.update(
                source_label=csv_path, csv_path=csv_path, csv_mtime_ns=csv_mtime_ns, csv_size=csv_size
            )
            updates = {"source_type": kind}
        record = source_table_service._write_source_import(
            name, {**record, **updates, "project_name": name, "last_import": last_import}
        )
        response = {
            "ok": True,
            "upload_id": folder.name,
            **source_table_service._master_status(name, master_path, record, refreshed=True),
        }
        temporary = folder / f"{_COMMIT_FILE}.tmp"
        temporary.write_text(json.dumps(response), encoding="utf-8")
        os.replace(temporary, folder / _COMMIT_FILE)
        for index in held:
            _part_path(folder, index).unlink(missing_ok=True)

    if profile is not None:
        try:
            source_table_service.remember_mssql_connection(profile["server"], profile["database"])
        except HTTPException:
            pass
        action = f"Imported source table from SQL Server ({last_import['source_label']}, {counter.rows:,} rows)"
    elif kind == SOURCE_TYPE_COMBINED:
        action = f"Imported combined source ({last_import['source_label']}, {counter.rows:,} rows)"
    else:
        action = f"Imported source table from CSV ({csv_path}, {counter.rows:,} rows)"
    safe_append_project_audit_log(project_name=name, action=action)
    return response


# --- Client half ------------------------------------------------------------

_STATE_LOCK = threading.Lock()
# project key -> progress the page polls while its import request is open.
_PROGRESS: Dict[str, Dict[str, Any]] = {}
# project key -> (upload id, CSV identity) of an upload that did not finish,
# so the next attempt on an unchanged file resumes it.
_PENDING: Dict[str, Tuple[str, Tuple[Any, ...]]] = {}


def _project_key(project_name: str) -> str:
    return str(project_name or "").strip().casefold()


def get_upload_progress(project_name: str) -> Dict[str, Any]:
    with _STATE_LOCK:
        progress = dict(_PROGRESS.get(_project_key(project_name)) or {})
    return {"ok": True, "active": bool(progress), **progress}


def _set_progress(key: str, **values: Any) -> None:
    with _STATE_LOCK:
        _PROGRESS.setdefault(key, {}).update(values)


def _csv_blocks(csv_path: str) -> Iterator[bytes]:
    try:
        with open(csv_path, "rb") as handle:
            while True:
                block = handle.read(RAW_CHUNK_BYTES)
                if not block:
                    return
                yield block
    except PermissionError:
        raise HTTPException(423, f"Source table file is locked: {csv_path}")
    except FileNotFoundError:
        raise HTTPException(404, f"Source table file was not found: {csv_path}")


def _mssql_blocks(profile: Dict[str, str]) -> Iterator[bytes]:
    """The whole SQL Server table as CSV bytes, read as the user's Windows login."""
    driver = source_table_service._require_driver()
    statement = f"SELECT * FROM {source_table_service._quote_object_name(profile['table'])}"
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    try:
        with driver.connect(source_table_service._connection_string(profile), autocommit=True) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(statement)
                writer.writerow([str(item[0]) for item in (cursor.description or [])])
                while True:
                    batch = cursor.fetchmany(source_table_service._MSSQL_FETCH_BATCH)
                    if not batch:
                        break
                    for row in batch:
                        writer.writerow([source_table_service._csv_safe_cell(cell) for cell in row])
                        if buffer.tell() >= RAW_CHUNK_BYTES:
                            yield buffer.getvalue().encode("utf-8")
                            buffer.seek(0)
                            buffer.truncate()
            finally:
                cursor.close()
    except HTTPException:
        raise
    except Exception as error:  # pyodbc.Error and driver-specific subclasses.
        raise HTTPException(502, f"SQL Server import failed: {error}") from error
    if buffer.tell():
        yield buffer.getvalue().encode("utf-8")


def _chunks(blocks: Iterator[bytes]) -> Iterator[Tuple[bytes, str]]:
    """(raw, encoded) pieces, halving a block whose encoding would not fit."""
    for block in blocks:
        pending = [block]
        while pending:
            piece = pending.pop(0)
            encoded = encode_chunk(piece)
            if len(encoded) > MAX_ENCODED_CHUNK_CHARS and len(piece) > 1:
                middle = len(piece) // 2
                pending[:0] = [piece[:middle], piece[middle:]]
                continue
            yield piece, encoded


def _mutate(kind: str, kwargs: Dict[str, Any], local) -> Dict[str, Any]:
    return workspace_mutation_client.run_workspace_mutation(
        kind, kwargs, local=local
    )


def upload_source_table(project_name: str, source_type: str) -> Dict[str, Any]:
    """Read the project's client-only source here and upload it as the master table."""
    name = source_table_service._require_project_name(project_name)
    key = _project_key(name)
    settings = workspace_read_client.run_workspace_read(
        "source_table_settings",
        {"project_name": name},
        local=lambda: source_table_service.read_source_table_settings(name),
    )
    commit_extras: Dict[str, Any] = {}
    signature: Optional[Tuple[Any, ...]] = None
    total_bytes: Optional[int] = None
    if source_type == SOURCE_TYPE_MSSQL:
        blocks = _mssql_blocks(source_table_service._require_complete_mssql_profile(settings.get("mssql")))
    else:
        csv_path = str(settings.get("csv_path") or "").strip()
        if not csv_path:
            raise HTTPException(400, f"No source table is configured for project '{name}'.")
        try:
            identity = csv_identity(csv_path)
        except FileNotFoundError:
            raise HTTPException(404, f"Source table file was not found: {csv_path}")
        except PermissionError:
            raise HTTPException(423, f"Source table file is locked: {csv_path}")
        commit_extras = {key_: identity[key_] for key_ in ("csv_path", "csv_mtime_ns", "csv_size")}
        signature = (identity["csv_path"], identity["csv_mtime_ns"], identity["csv_size"])
        total_bytes = identity["csv_size"]
        blocks = _csv_blocks(csv_path)

    with _STATE_LOCK:
        pending = _PENDING.get(key)
        upload_id = pending[0] if pending and signature is not None and pending[1] == signature else ""
        upload_id = upload_id or f"srcup_{uuid.uuid4().hex}"
        _PENDING[key] = (upload_id, signature or ())
        _PROGRESS[key] = {
            "upload_id": upload_id,
            "phase": "uploading",
            "bytes_sent": 0,
            "total_bytes": total_bytes,
            "rows_sent": 0,
            "chunks_sent": 0,
            "chunks_resumed": 0,
        }
    try:
        held: Dict[str, int] = {}
        committed = False
        if pending and pending[0] == upload_id:
            status_kwargs = {"project_name": name, "upload_id": upload_id}
            status = workspace_read_client.run_workspace_read(
                "source_table_upload_status",
                status_kwargs,
                local=lambda: get_source_table_upload_status(**status_kwargs),
            )
            held = status.get("parts") or {}
            # The last attempt's commit landed but its answer was lost: the
            # commit below answers from that outcome, so nothing is resent.
            committed = bool(status.get("committed"))
        counter = RowCounter()
        index = -1
        resumed = 0
        for index, (raw, encoded) in enumerate(_chunks(blocks)):
            counter.feed(raw)
            if committed or held.get(str(index)) == len(raw):
                resumed += 1
            else:
                chunk_kwargs = {"project_name": name, "upload_id": upload_id, "index": index, "data": encoded}
                _mutate(
                    "source_table_upload_chunk",
                    chunk_kwargs,
                    lambda kwargs=chunk_kwargs: receive_source_table_chunk(**kwargs),
                )
            _set_progress(
                key, bytes_sent=counter.bytes, rows_sent=counter.rows, chunks_sent=index + 1, chunks_resumed=resumed
            )
        if index < 0:
            raise HTTPException(400, "The source table is empty.")
        _set_progress(key, phase="committing")
        commit_kwargs = {
            "project_name": name,
            "upload_id": upload_id,
            "source_type": SOURCE_TYPE_MSSQL if source_type == SOURCE_TYPE_MSSQL else SOURCE_TYPE_CSV,
            "chunk_count": index + 1,
            "byte_count": counter.bytes,
            "row_count": counter.rows,
            **commit_extras,
        }
        result = _mutate(
            "source_table_upload_commit",
            commit_kwargs,
            lambda: commit_source_table_upload(**commit_kwargs),
        )
        with _STATE_LOCK:
            _PENDING.pop(key, None)
        return result
    finally:
        with _STATE_LOCK:
            _PROGRESS.pop(key, None)
