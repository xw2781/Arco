"""Transactional installer runtime for ArcRho Server components."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.error import URLError
from urllib.request import Request, urlopen


MODULE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = MODULE_ROOT.parent
REPOSITORY_ROOT = SOURCE_ROOT.parents[1]
CANONICAL_API_SOURCE = REPOSITORY_ROOT / "python-api" / "src"
for import_root in (SOURCE_ROOT, CANONICAL_API_SOURCE):
    if import_root.is_dir() and str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.config import set_server_root  # noqa: E402
from server_config import (  # noqa: E402
    ensure_server_config,
    read_server_config,
    resolve_server_config_path,
    write_server_config,
)
from server_deployment_contract import (  # noqa: E402
    COMPONENT_BY_ROLE,
    DEPLOYMENT_LOCK_FILE_NAME,
    INSTALL_METADATA_RELATIVE_DIR,
    RECEIPT_FILE_NAME,
    build_receipt,
    compare_versions,
    normalize_manifest,
    normalize_receipt,
)


WORKSPACE_DIRECTORIES = ("apps", "config", "projects", "requests", "runtime")
SHUTDOWN_ROLES = (
    "engine",
    "bridge",
    "bridge_worker",
    "gateway",
    "orchestrator",
    "admin",
)
KILL_SWITCH_PATHS = (
    "apps.engine.kill_all",
    "apps.bridge.kill_all",
    "apps.bridge_worker.kill_all",
    "apps.orchestrator.kill_all",
    "apps.gateway.kill_all",
)
ADMIN_PORT = 28766
SHUTDOWN_TIMEOUT_SECONDS = 180.0
STARTUP_TIMEOUT_SECONDS = 60.0
POLL_SECONDS = 0.5
RENAME_ATTEMPTS = 10
RENAME_RETRY_SECONDS = 0.25
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
INVALID_PATH_CHARS = set('<>"|?*')
WINDOWS_MAX_SAFE_PATH = 259


class DeploymentError(RuntimeError):
    pass


class DeploymentLockError(DeploymentError):
    pass


class DeploymentRollbackError(DeploymentError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        raise DeploymentError(f"Required JSON file was not found: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"Could not read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeploymentError(f"JSON file must contain an object: {path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(persisted_json_text(payload))
        os.replace(temp, path)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(payload)
        os.replace(temp, path)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _snapshot_file(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_file(path: Path, snapshot: bytes | None) -> None:
    if snapshot is None:
        path.unlink(missing_ok=True)
    else:
        _write_bytes_atomic(path, snapshot)


def _drive_root(path: Path) -> str:
    drive = path.drive
    if not drive:
        raise DeploymentError("The workspace must use a local Windows drive.")
    return drive + "\\"


def _windows_drive_type(path: Path) -> int:
    if os.name != "nt":
        return DRIVE_FIXED
    return int(ctypes.windll.kernel32.GetDriveTypeW(_drive_root(path)))


def _has_invalid_segments(path: Path) -> bool:
    parts = path.parts[1:] if path.drive else path.parts
    return any(
        not part
        or part.rstrip(" .") != part
        or any(character in INVALID_PATH_CHARS for character in part)
        for part in parts
    )


def _probe_writable_directory(path: Path) -> None:
    cursor = path
    while not cursor.exists():
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    probe_parent = cursor if cursor.is_dir() else cursor.parent
    probe = probe_parent / f".arcrho-write-test-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"ArcRho")
        probe.unlink()
    except OSError as exc:
        raise DeploymentError(f"The workspace is not writable: {path} ({exc})") from exc


def validate_workspace_root(
    value: str | os.PathLike[str],
    *,
    drive_type_resolver: Callable[[Path], int] | None = None,
) -> Path:
    raw = os.fspath(value).strip()
    if not raw or raw.startswith(("\\\\", "//")):
        raise DeploymentError("Choose a folder on a local fixed disk, not a UNC path.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DeploymentError("The workspace path must be absolute.")
    if _has_invalid_segments(path):
        raise DeploymentError(f"The workspace path is invalid: {path}")
    if path.exists() and not path.is_dir():
        raise DeploymentError(f"The workspace path is a file: {path}")
    resolved = path.resolve(strict=False)
    resolver = drive_type_resolver or _windows_drive_type
    drive_type = resolver(resolved)
    if drive_type != DRIVE_FIXED:
        description = "mapped/network" if drive_type == DRIVE_REMOTE else "non-fixed"
        raise DeploymentError(
            f"The ArcRho Server workspace must be on a local fixed disk; {resolved} is {description}."
        )
    anchor = Path(resolved.anchor)
    if resolved == anchor:
        raise DeploymentError("The drive root itself cannot be used as the workspace.")
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve(strict=False)
    program_files = [
        Path(value).resolve(strict=False)
        for value in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        )
        if value
    ]
    unsafe_roots = [windows_dir, *program_files]
    for unsafe in unsafe_roots:
        if resolved == unsafe or unsafe in resolved.parents:
            raise DeploymentError(f"The workspace cannot be inside {unsafe}.")
    _probe_writable_directory(resolved)
    return resolved


def _metadata_dir(root: Path) -> Path:
    return root / INSTALL_METADATA_RELATIVE_DIR


def _receipt_path(root: Path) -> Path:
    return _metadata_dir(root) / RECEIPT_FILE_NAME


def _load_receipt(root: Path) -> dict[str, Any] | None:
    path = _receipt_path(root)
    if not path.exists():
        return None
    try:
        receipt = normalize_receipt(_read_json(path))
    except ValueError as exc:
        raise DeploymentError(f"The existing install receipt is invalid: {exc}") from exc
    recorded_root = Path(receipt["workspace_root"]).expanduser()
    if not recorded_root.is_absolute() or recorded_root.resolve(strict=False) != root.resolve(
        strict=False
    ):
        # A workspace copied to a different local folder is unowned on this
        # host until it is explicitly adopted.  Never let a foreign receipt
        # authorize repair or uninstall at a different root.
        return None
    return receipt


def _workspace_has_server_state(root: Path) -> bool:
    meaningful = ("config", "projects", "requests", "runtime")
    for name in meaningful:
        folder = root / name
        try:
            next(folder.iterdir())
            return True
        except (FileNotFoundError, StopIteration):
            continue
    return any((root / definition.relative_destination).exists() for definition in COMPONENT_BY_ROLE.values())


def _determine_mode(
    requested: str,
    root: Path,
    manifest: dict[str, Any],
    receipt: dict[str, Any] | None,
    *,
    workspace_has_state: bool | None = None,
) -> str:
    version = manifest["product_version"]
    if receipt is not None:
        comparison = compare_versions(version, receipt["installed_version"])
        if comparison < 0:
            raise DeploymentError(
                f"Downgrade blocked: installed {receipt['installed_version']}, payload {version}."
            )
    else:
        comparison = None

    has_state = (
        _workspace_has_server_state(root)
        if workspace_has_state is None
        else workspace_has_state
    )
    if requested == "auto":
        if receipt is not None:
            return "repair" if comparison == 0 else "upgrade"
        return "adopt" if has_state else "install"
    if requested == "install" and (receipt is not None or has_state):
        raise DeploymentError("Install mode requires a new, unowned workspace.")
    if requested == "adopt" and receipt is not None:
        raise DeploymentError("Adopt mode requires an unreceipted workspace.")
    if requested in ("upgrade", "repair") and receipt is None:
        raise DeploymentError(f"{requested.title()} mode requires an install receipt.")
    if requested == "upgrade" and comparison is not None and comparison <= 0:
        raise DeploymentError("Upgrade mode requires a newer payload version.")
    if requested == "repair" and comparison is not None and comparison != 0:
        raise DeploymentError("Repair mode requires the installed payload version.")
    return requested


@contextmanager
def deployment_lock(root: Path) -> Iterator[None]:
    metadata = _metadata_dir(root)
    metadata.mkdir(parents=True, exist_ok=True)
    lock_path = metadata / DEPLOYMENT_LOCK_FILE_NAME
    handle = lock_path.open("a+b")
    acquired = False
    try:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DeploymentLockError(
                f"Another ArcRho Server deployment is already using {root}."
            ) from exc
        acquired = True
        handle.seek(0)
        handle.truncate()
        handle.write(
            (
                f"pid={os.getpid()}\n"
                f"started={datetime.now(timezone.utc).isoformat()}\n"
            ).encode("utf-8")
        )
        handle.flush()
        yield
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                # File locking, not file existence, owns concurrency.  A
                # contender may briefly hold an open handle after its lock
                # attempt fails, so a stale unlocked marker is harmless.
                pass


def _manifest_component_source(payload_root: Path, component: dict[str, Any]) -> Path:
    return payload_root / Path(component["relative_destination"])


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_payload(payload_root: Path, manifest: dict[str, Any]) -> None:
    for component in manifest["components"]:
        component_root = _manifest_component_source(payload_root, component)
        if not component_root.is_dir():
            raise DeploymentError(f"Payload component is missing: {component_root}")
        expected = {entry["path"]: entry for entry in component["files"]}
        actual = {
            path.relative_to(component_root).as_posix(): path
            for path in component_root.rglob("*")
            if path.is_file()
        }
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            raise DeploymentError(
                f"Payload inventory mismatch for {component['app_name']}; "
                f"missing={missing[:3]}, extra={extra[:3]}."
            )
        for relative_path, path in actual.items():
            entry = expected[relative_path]
            if path.stat().st_size != entry["size"] or _hash_file(path) != entry["sha256"]:
                raise DeploymentError(f"Payload checksum mismatch: {path}")


def _validate_payload_destination_lengths(
    root: Path, manifest: dict[str, Any]
) -> None:
    if os.name != "nt":
        return
    longest: tuple[int, Path] | None = None
    for component in manifest["components"]:
        destination = root / Path(component["relative_destination"])
        for entry in component["files"]:
            path = destination / Path(entry["path"])
            candidate = (len(str(path)), path)
            if longest is None or candidate[0] > longest[0]:
                longest = candidate
    if longest is not None and longest[0] > WINDOWS_MAX_SAFE_PATH:
        raise DeploymentError(
            "The selected workspace path is too long for this component payload "
            f"({longest[0]} characters at {longest[1]}). Choose a shorter folder."
        )


def _nested_get(payload: dict[str, Any], key_path: str, default: Any = None) -> Any:
    value: Any = payload
    for key in key_path.split("."):
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def _nested_set(payload: dict[str, Any], key_path: str, value: Any) -> None:
    cursor = payload
    keys = key_path.split(".")
    for key in keys[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[keys[-1]] = value


def _snapshot_kill_switches(config: dict[str, Any]) -> dict[str, Any]:
    return {key: _nested_get(config, key, False) for key in KILL_SWITCH_PATHS}


def _apply_kill_switches(config: dict[str, Any], values: dict[str, Any]) -> None:
    for key, value in values.items():
        _nested_set(config, key, value)


def _request_admin_shutdown() -> None:
    request = Request(
        f"http://127.0.0.1:{ADMIN_PORT}/api/shutdown", data=b"", method="POST"
    )
    try:
        with urlopen(request, timeout=0.75):
            pass
    except (OSError, URLError):
        pass


def _heartbeat_files(root: Path, roles: tuple[str, ...] = SHUTDOWN_ROLES) -> list[Path]:
    result: list[Path] = []
    for role in roles:
        folder = root / "runtime" / "instances" / f"arcrho_{role}"
        try:
            result.extend(path for path in folder.iterdir() if path.is_file())
        except FileNotFoundError:
            continue
    return result


def _wait_for_shutdown(root: Path, timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = _heartbeat_files(root)
        if not remaining:
            return
        if time.monotonic() >= deadline:
            names = ", ".join(path.name for path in remaining[:5])
            raise DeploymentError(
                f"Server components did not stop within {timeout_seconds:g}s ({names}). "
                "Deployment aborted before replacing binaries."
            )
        time.sleep(POLL_SECONDS)


def _stop_components(
    root: Path,
    config_path: Path,
    timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    config = read_server_config(config_path, root)
    previous = _snapshot_kill_switches(config)
    _apply_kill_switches(config, {key: True for key in KILL_SWITCH_PATHS})
    write_server_config(config_path, config)
    _request_admin_shutdown()
    _wait_for_shutdown(root, timeout_seconds)
    return previous


def _restore_kill_switches(
    root: Path, config_path: Path, previous: dict[str, Any]
) -> None:
    config = read_server_config(config_path, root)
    _apply_kill_switches(config, previous)
    write_server_config(config_path, config)


def _new_transaction_directory(root: Path, kind: str) -> Path:
    """Allocate a same-volume transaction folder without lengthening app paths.

    Some bundled Bridge resources are deeply nested.  A four-character hidden
    name (the same length as ``apps``) keeps staged, backup, and uninstall paths
    no longer than their eventual live paths on Windows hosts that still apply
    the legacy MAX_PATH boundary.
    """

    if kind not in {"s", "b", "u"}:
        raise ValueError(f"Unknown transaction directory kind: {kind}")
    for _attempt in range(512):
        candidate = root / f".{kind}{uuid.uuid4().hex[:2]}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise DeploymentError(f"Could not allocate a deployment transaction folder in {root}.")


def _rename_transaction_path(source: Path, destination: Path) -> None:
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            source.rename(destination)
            return
        except OSError as exc:
            transient = isinstance(exc, PermissionError) or getattr(
                exc, "winerror", None
            ) in {5, 32, 33}
            if not transient or attempt == RENAME_ATTEMPTS:
                raise
            time.sleep(RENAME_RETRY_SECONDS * attempt)


def _remove_transaction_tree(path: Path) -> None:
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt == RENAME_ATTEMPTS:
                raise
            time.sleep(RENAME_RETRY_SECONDS * attempt)


def _prepare_staged_payload(
    root: Path, payload_root: Path, manifest: dict[str, Any]
) -> Path:
    transaction = _new_transaction_directory(root, "s")
    try:
        for component in manifest["components"]:
            source = _manifest_component_source(payload_root, component)
            shutil.copytree(source, transaction / component["app_name"])
    except Exception:
        try:
            _remove_transaction_tree(transaction)
        except OSError:
            pass
        raise
    return transaction


def _swap_components(
    root: Path,
    staged: Path,
    manifest: dict[str, Any],
    *,
    fail_after: int | None = None,
) -> tuple[Path, list[tuple[Path, Path | None]]]:
    backup_root = _new_transaction_directory(root, "b")
    swaps: list[tuple[Path, Path | None]] = []
    try:
        for index, component in enumerate(manifest["components"], start=1):
            live = root / Path(component["relative_destination"])
            replacement = staged / component["app_name"]
            backup = backup_root / component["app_name"] if live.exists() else None
            if backup is not None:
                _rename_transaction_path(live, backup)
            try:
                _rename_transaction_path(replacement, live)
            except Exception:
                if backup is not None and backup.exists() and not live.exists():
                    _rename_transaction_path(backup, live)
                raise
            swaps.append((live, backup))
            if fail_after is not None and index >= fail_after:
                raise OSError("Injected deployment swap failure.")
    except Exception as exc:
        rollback_errors: list[str] = []
        for live, backup in reversed(swaps):
            try:
                if live.exists():
                    _rename_transaction_path(live, staged / live.name)
                if backup is not None and backup.exists():
                    _rename_transaction_path(backup, live)
            except Exception as rollback_exc:
                rollback_errors.append(f"{live}: {rollback_exc}")
        if rollback_errors:
            raise DeploymentRollbackError(
                f"Deployment failed ({exc}) and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from exc
        try:
            _remove_transaction_tree(backup_root)
        except OSError:
            pass
        raise
    return backup_root, swaps


def _rollback_swaps(
    staged: Path,
    swaps: list[tuple[Path, Path | None]],
) -> None:
    errors: list[str] = []
    for live, backup in reversed(swaps):
        try:
            if live.exists():
                _rename_transaction_path(live, staged / live.name)
            if backup is not None and backup.exists():
                _rename_transaction_path(backup, live)
        except Exception as exc:
            errors.append(f"{live}: {exc}")
    if errors:
        raise DeploymentRollbackError(
            "Could not restore the previous server component deployment: "
            + "; ".join(errors)
        )


def _shortcut_folder(kind: str) -> Path:
    appdata = Path(os.environ["APPDATA"])
    if kind == "startup":
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "ArcRho Server"


def _create_shortcut(
    target: Path,
    destination: Path,
    *,
    arguments: str = "",
    description: str = "",
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        destination.write_text(str(target), encoding="utf-8")
        return
    destination_ps = str(destination).replace("'", "''")
    target_ps = str(target).replace("'", "''")
    arguments_ps = arguments.replace("'", "''")
    working_directory_ps = str(target.parent).replace("'", "''")
    description_ps = description.replace("'", "''")
    command = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut('{destination_ps}'); "
        f"$shortcut.TargetPath = '{target_ps}'; "
        f"$shortcut.Arguments = '{arguments_ps}'; "
        f"$shortcut.WorkingDirectory = '{working_directory_ps}'; "
        f"$shortcut.IconLocation = '{target_ps}'; "
        f"$shortcut.Description = '{description_ps}'; "
        "$shortcut.Save()"
    )
    completed = subprocess.run(
        [
            os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"),
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe",
            ),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        raise DeploymentError(
            f"Could not create shortcut {destination}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )


def _register_shortcuts(root: Path) -> None:
    launcher = root / "apps" / "Arco Launcher" / "Arco Launcher.exe"
    admin = root / "apps" / "Arco Admin Control" / "Arco Admin Control.exe"
    _create_shortcut(
        launcher,
        _shortcut_folder("startup") / "Arco Launcher.lnk",
        arguments="--silent",
        description="Start ArcRho Server components at login",
    )
    _create_shortcut(
        admin,
        _shortcut_folder("programs") / "Arco Admin Control.lnk",
        description="Open Arco Admin Control",
    )


def _remove_shortcuts() -> None:
    for path in (
        _shortcut_folder("startup") / "Arco Launcher.lnk",
        _shortcut_folder("startup") / "ADAS Shell.lnk",
        _shortcut_folder("programs") / "Arco Admin Control.lnk",
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        _shortcut_folder("programs").rmdir()
    except OSError:
        pass


def _start_launcher(root: Path) -> None:
    launcher = root / "apps" / "Arco Launcher" / "Arco Launcher.exe"
    if not launcher.is_file():
        raise DeploymentError(f"Installed launcher was not found: {launcher}")
    subprocess.Popen(
        [str(launcher), "--silent"],
        cwd=str(launcher.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=CREATE_NO_WINDOW,
    )


def _fresh_heartbeat_exists(root: Path, role: str, since: float) -> bool:
    folder = root / "runtime" / "instances" / f"arcrho_{role}"
    try:
        return any(path.is_file() and path.stat().st_mtime >= since for path in folder.iterdir())
    except FileNotFoundError:
        return False


def _wait_for_startup(root: Path, timeout_seconds: float = STARTUP_TIMEOUT_SECONDS) -> None:
    started = time.time() - 2
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _fresh_heartbeat_exists(root, "orchestrator", started) and _fresh_heartbeat_exists(
            root, "engine", started
        ):
            return
        if time.monotonic() >= deadline:
            raise DeploymentError(
                "Arco Launcher started, but fresh Orchestrator and Engine heartbeats "
                f"did not both appear within {timeout_seconds:g}s."
            )
        time.sleep(POLL_SECONDS)


def _configure_frontend(root: Path) -> None:
    set_server_root(root, persist=True, validate=True)


def deploy(
    *,
    mode: str,
    workspace_root: str | os.PathLike[str],
    payload_root: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    configure_frontend: bool = False,
    launch: bool = True,
    verify_startup: bool = True,
    shutdown_timeout: float = SHUTDOWN_TIMEOUT_SECONDS,
    startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    fail_after_swap: int | None = None,
) -> dict[str, Any]:
    root = validate_workspace_root(workspace_root)
    workspace_has_state = _workspace_has_server_state(root)
    payload = Path(payload_root).expanduser().resolve()
    try:
        manifest = normalize_manifest(_read_json(Path(manifest_path)))
    except ValueError as exc:
        raise DeploymentError(f"Payload manifest is invalid: {exc}") from exc
    _validate_payload_destination_lengths(root, manifest)
    verify_payload(payload, manifest)

    receipt = _load_receipt(root)
    effective_mode = _determine_mode(
        mode,
        root,
        manifest,
        receipt,
        workspace_has_state=workspace_has_state,
    )

    root.mkdir(parents=True, exist_ok=True)
    for name in WORKSPACE_DIRECTORIES:
        (root / name).mkdir(parents=True, exist_ok=True)

    with deployment_lock(root):
        # Re-read after taking the lock so a concurrent completed install can
        # never be treated using the unlocked observation above.
        locked_receipt = _load_receipt(root)
        if locked_receipt != receipt:
            receipt = locked_receipt
            effective_mode = _determine_mode(mode, root, manifest, receipt)
        config_path = resolve_server_config_path(root)
        config_snapshot = _snapshot_file(config_path)
        receipt_snapshot = _snapshot_file(_receipt_path(root))
        previous_switches: dict[str, Any] | None = None
        preserve_config_bytes = False
        staged: Path | None = None
        backup_root: Path | None = None
        swaps: list[tuple[Path, Path | None]] = []
        swapped = False
        warnings: list[str] = []
        try:
            # Staging must complete before configuration or live binaries are
            # touched.  This keeps copy/extraction failures outside the release
            # transaction.
            staged = _prepare_staged_payload(root, payload, manifest)
            config_path, merged_config = ensure_server_config(root)
            previous_switches = _snapshot_kill_switches(merged_config)
            if config_snapshot is not None:
                try:
                    existing_config = json.loads(config_snapshot.decode("utf-8-sig"))
                    preserve_config_bytes = existing_config == merged_config
                except (UnicodeDecodeError, json.JSONDecodeError):
                    preserve_config_bytes = False
            previous_switches = _stop_components(
                root, config_path, timeout_seconds=shutdown_timeout
            )
            backup_root, swaps = _swap_components(
                root, staged, manifest, fail_after=fail_after_swap
            )
            swapped = True
            installation_id = (
                receipt["installation_id"] if receipt else str(uuid.uuid4())
            )
            new_receipt = build_receipt(
                manifest,
                installation_id=installation_id,
                workspace_root=str(root),
                installed_at=datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            )
            _write_json_atomic(_receipt_path(root), new_receipt)
            _restore_kill_switches(root, config_path, previous_switches)
            if preserve_config_bytes:
                _restore_file(config_path, config_snapshot)
            if launch:
                _start_launcher(root)
                if verify_startup:
                    _wait_for_startup(root, startup_timeout)
            try:
                _register_shortcuts(root)
            except Exception as exc:
                warnings.append(f"Startup/Admin shortcuts could not be registered: {exc}")
            if configure_frontend:
                try:
                    _configure_frontend(root)
                except Exception as exc:
                    warnings.append(f"Frontend workspace could not be configured: {exc}")
            if backup_root is not None:
                try:
                    _remove_transaction_tree(backup_root)
                except OSError as exc:
                    warnings.append(
                        f"Previous component backup could not be removed: {backup_root} ({exc})"
                    )
            if staged is not None:
                try:
                    _remove_transaction_tree(staged)
                except OSError as exc:
                    warnings.append(
                        f"Deployment staging folder could not be removed: {staged} ({exc})"
                    )
            return {
                "ok": True,
                "mode": effective_mode,
                "workspace_root": str(root),
                "version": manifest["product_version"],
                "warnings": warnings,
            }
        except Exception as deployment_exc:
            if swapped and staged is not None:
                try:
                    config = read_server_config(config_path, root)
                    _apply_kill_switches(
                        config, {key: True for key in KILL_SWITCH_PATHS}
                    )
                    write_server_config(config_path, config)
                    _request_admin_shutdown()
                    _wait_for_shutdown(root, shutdown_timeout)
                    _rollback_swaps(staged, swaps)
                    _restore_file(_receipt_path(root), receipt_snapshot)
                    _restore_file(config_path, config_snapshot)
                    if launch and any(backup is not None for _, backup in swaps):
                        try:
                            _start_launcher(root)
                        except Exception:
                            pass
                except Exception as rollback_exc:
                    raise DeploymentRollbackError(
                        f"Deployment failed ({deployment_exc}) and rollback failed: {rollback_exc}"
                    ) from deployment_exc
            else:
                try:
                    _restore_file(_receipt_path(root), receipt_snapshot)
                    _restore_file(config_path, config_snapshot)
                except Exception as restore_exc:
                    raise DeploymentRollbackError(
                        f"Deployment failed ({deployment_exc}) and kill-switch restoration failed: {restore_exc}"
                    ) from deployment_exc
            if staged is not None:
                try:
                    _remove_transaction_tree(staged)
                except OSError:
                    pass
            if backup_root is not None and backup_root.exists():
                try:
                    _remove_transaction_tree(backup_root)
                except OSError:
                    pass
            raise deployment_exc


def uninstall(
    *,
    workspace_root: str | os.PathLike[str],
    shutdown_timeout: float = SHUTDOWN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    root = validate_workspace_root(workspace_root)
    result: dict[str, Any]
    with deployment_lock(root):
        receipt = _load_receipt(root)
        if receipt is None:
            raise DeploymentError("No ArcRho Server install receipt was found.")
        config_path = resolve_server_config_path(root)
        previous_switches = _stop_components(
            root, config_path, timeout_seconds=shutdown_timeout
        )
        removed: list[str] = []
        transaction = _new_transaction_directory(root, "u")
        moved: list[tuple[Path, Path]] = []
        try:
            for role in receipt["components"]:
                definition = COMPONENT_BY_ROLE[role]
                path = root / definition.relative_destination
                if path.exists():
                    parked = transaction / path.name
                    _rename_transaction_path(path, parked)
                    moved.append((path, parked))
                    removed.append(str(path))
            _restore_kill_switches(root, config_path, previous_switches)
        except Exception as uninstall_exc:
            rollback_errors: list[str] = []
            for live, parked in reversed(moved):
                try:
                    if parked.exists() and not live.exists():
                        _rename_transaction_path(parked, live)
                except Exception as rollback_exc:
                    rollback_errors.append(f"{live}: {rollback_exc}")
            _restore_kill_switches(root, config_path, previous_switches)
            if rollback_errors:
                raise DeploymentRollbackError(
                    f"Uninstall failed ({uninstall_exc}) and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from uninstall_exc
            raise
        try:
            _remove_transaction_tree(transaction)
        except OSError as cleanup_exc:
            raise DeploymentError(
                f"Component files could not be removed from {transaction}: {cleanup_exc}"
            ) from cleanup_exc
        _receipt_path(root).unlink(missing_ok=True)
        shortcut_warning = ""
        try:
            _remove_shortcuts()
        except Exception as exc:
            shortcut_warning = f"Installer shortcuts could not be fully removed: {exc}"
        result = {
            "ok": True,
            "workspace_root": str(root),
            "removed": removed,
            "warnings": [
                warning for warning in (shortcut_warning,) if warning
            ],
        }
    try:
        _metadata_dir(root).rmdir()
    except OSError:
        pass
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy ArcRho Server components.")
    parser.add_argument(
        "mode", choices=("auto", "install", "adopt", "upgrade", "repair", "uninstall")
    )
    parser.add_argument("--root", required=True, help="ArcRho Server workspace root.")
    parser.add_argument("--payload", help="Extracted release payload root.")
    parser.add_argument("--manifest", help="Payload manifest JSON path.")
    parser.add_argument("--configure-frontend", action="store_true")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--no-startup-verification", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.mode == "uninstall":
            result = uninstall(workspace_root=args.root)
        else:
            if not args.payload or not args.manifest:
                raise DeploymentError("--payload and --manifest are required for deployment.")
            result = deploy(
                mode=args.mode,
                workspace_root=args.root,
                payload_root=args.payload,
                manifest_path=args.manifest,
                configure_frontend=args.configure_frontend,
                launch=not args.no_launch,
                verify_startup=not args.no_startup_verification,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ArcRho Server deployment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
