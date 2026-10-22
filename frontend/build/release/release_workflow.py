"""Canonical local build, pending-release, and GitHub release workflow helpers.

The local release manager and the local-repository batch entry point both use this
module.  A build-only run records an immutable-enough description of the installer
and the release fragments it was built from outside the repository.  Publishing
later verifies that record before it creates a GitHub Release and hands the
repository bookkeeping back to ``sync_published_release.py``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import release_notes
import version_manager


FRONTEND_ROOT = Path(__file__).resolve().parents[2]
BUILD_ROOT = FRONTEND_ROOT / "build"
RELEASE_ROOT = BUILD_ROOT / "release"
PUBLISH_SCRIPT = RELEASE_ROOT / "publish_github_release.ps1"
UPDATE_MANIFEST_SCRIPT = RELEASE_ROOT / "publish_update_manifest.ps1"
SYNC_SCRIPT = RELEASE_ROOT / "sync_published_release.py"

PRODUCTS = ("Arco", "Arcode")
MANIFEST_SCHEMA_VERSION = 1
VERSION_SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_RECENT_RELEASE_LIMIT = 20
MAX_RELEASE_HISTORY_LIMIT = 100
DEFAULT_PYTHON_API_PACKAGE_DIR = Path(r"E:\ArcRho Server\packages")

# These are the only files version_manager.update_version_metadata owns.  Keeping
# the list here makes the temporary build-only version change reversible without
# duplicating a list in the GUI or batch files.
VERSION_METADATA_FILES = (
    "package.json",
    "package-lock.json",
    "ui/index.html",
    "ui/splash.html",
)


class ReleaseWorkflowError(RuntimeError):
    """A clear, expected workflow failure that should be shown to the operator."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_product(value: str) -> str:
    text = str(value or "").strip()
    for product in PRODUCTS:
        if product.casefold() == text.casefold():
            return product
    raise ReleaseWorkflowError(
        f"Unsupported product '{value}'. Expected one of: {', '.join(PRODUCTS)}."
    )


def validate_version(value: str) -> str:
    version = str(value or "").strip()
    try:
        version_manager.parse_version(version)
    except ValueError as exc:
        raise ReleaseWorkflowError(str(exc)) from exc
    return version


def local_release_work_dir() -> Path:
    configured = str(os.environ.get("ARCRHO_LOCAL_RELEASE_WORK_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "ArcRho Local Build"


def pending_releases_dir(work_dir: Path | None = None) -> Path:
    return (work_dir or local_release_work_dir()) / "pending_releases"


def installer_name(product: str, version: str) -> str:
    return f"{normalize_product(product)}-Setup-{validate_version(version)}.exe"


def resolve_release_channel(product: str, version: str) -> tuple[str, str]:
    product = normalize_product(product)
    version = validate_version(version)
    try:
        repository, tag_format = version_manager.load_release_channel(
            version_manager.DEFAULT_RELEASE_CHANNEL_PATH
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowError(f"Could not read the release channel: {exc}") from exc
    tag = tag_format.replace("{product}", product).replace("{version}", version)
    return repository, tag


def pending_manifest_path(
    product: str,
    version: str,
    work_dir: Path | None = None,
) -> Path:
    return pending_releases_dir(work_dir) / f"{normalize_product(product)}-v{validate_version(version)}.json"


def configured_python_api_package_dir() -> Path:
    configured = str(os.environ.get("PYTHON_API_PACKAGE_DIR", "")).strip()
    return Path(configured).expanduser() if configured else DEFAULT_PYTHON_API_PACKAGE_DIR


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReleaseWorkflowError(f"Could not hash {path}: {exc}") from exc
    return digest.hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    except OSError as exc:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise ReleaseWorkflowError(f"Could not write {path}: {exc}") from exc


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseWorkflowError(f"Pending release record was not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowError(f"Could not read pending release record {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseWorkflowError(f"Pending release record must be a JSON object: {path}")
    return payload


def _metadata_file_paths() -> tuple[tuple[str, Path], ...]:
    return tuple((relative, FRONTEND_ROOT / relative) for relative in VERSION_METADATA_FILES)


def snapshot_version_metadata(snapshot_path: Path) -> Path:
    """Store byte-exact frontend version files before a build-only run changes them."""
    files: dict[str, str] = {}
    for relative, path in _metadata_file_paths():
        try:
            files[relative] = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise ReleaseWorkflowError(f"Could not snapshot version metadata file {path}: {exc}") from exc

    _write_json(
        snapshot_path,
        {
            "schema_version": VERSION_SNAPSHOT_SCHEMA_VERSION,
            "created_at": _utc_now(),
            "files": files,
        },
    )
    return snapshot_path


def _snapshot_version(snapshot_path: Path) -> str | None:
    try:
        payload = _read_json(snapshot_path)
        encoded = payload.get("files", {}).get("package.json")
        if not isinstance(encoded, str):
            return None
        package_json = json.loads(base64.b64decode(encoded).decode("utf-8"))
        version = package_json.get("version")
        return str(version).strip() if version is not None else None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def restore_version_metadata(snapshot_path: Path, delete_snapshot: bool = False) -> None:
    """Restore the exact version files captured by snapshot_version_metadata."""
    payload = _read_json(snapshot_path)
    if payload.get("schema_version") != VERSION_SNAPSHOT_SCHEMA_VERSION:
        raise ReleaseWorkflowError(f"Unsupported version snapshot format: {snapshot_path}")
    files = payload.get("files")
    if not isinstance(files, dict) or set(files) != set(VERSION_METADATA_FILES):
        raise ReleaseWorkflowError(f"Version snapshot has an unexpected file set: {snapshot_path}")

    restored: list[tuple[Path, bytes]] = []
    for relative, path in _metadata_file_paths():
        encoded = files.get(relative)
        if not isinstance(encoded, str):
            raise ReleaseWorkflowError(f"Version snapshot is missing {relative}: {snapshot_path}")
        try:
            restored.append((path, base64.b64decode(encoded, validate=True)))
        except ValueError as exc:
            raise ReleaseWorkflowError(f"Version snapshot has invalid content for {relative}.") from exc

    # Replace each file through a same-directory temporary file, retaining the
    # original byte content (including JSON formatting) instead of reconstructing it.
    for path, content in restored:
        temp_path = path.with_name(f".{path.name}.{os.getpid()}.restore.tmp")
        try:
            temp_path.write_bytes(content)
            os.replace(temp_path, path)
        except OSError as exc:
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise ReleaseWorkflowError(f"Could not restore version metadata file {path}: {exc}") from exc

    if delete_snapshot:
        try:
            snapshot_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ReleaseWorkflowError(f"Version metadata was restored but snapshot cleanup failed: {exc}") from exc


def capture_built_release(
    product: str,
    version: str,
    installer_path: Path,
    *,
    work_dir: Path | None = None,
    version_snapshot_path: Path | None = None,
    python_api_wheel_path: Path | None = None,
    python_api_package_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Record a completed local installer and the exact release fragments it used."""
    product = normalize_product(product)
    version = validate_version(version)
    installer_path = installer_path.resolve()
    expected_name = installer_name(product, version)
    if installer_path.name != expected_name:
        raise ReleaseWorkflowError(
            f"Installer must be named {expected_name}; received {installer_path.name}."
        )
    if not installer_path.is_file():
        raise ReleaseWorkflowError(f"Built installer was not found: {installer_path}")

    try:
        fragments = release_notes.load_unreleased_fragments()
    except (OSError, ValueError) as exc:
        raise ReleaseWorkflowError(f"Could not capture release fragments: {exc}") from exc
    repository, tag = resolve_release_channel(product, version)
    source_version_before_build = (
        _snapshot_version(version_snapshot_path)
        if version_snapshot_path is not None and version_snapshot_path.is_file()
        else None
    )

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "built",
        "built_at": _utc_now(),
        "product": product,
        "version": version,
        "repository": repository,
        "tag": tag,
        "installer": {
            "path": str(installer_path),
            "name": installer_path.name,
            "sha256": sha256_file(installer_path),
        },
        "fragments": [
            {"name": fragment.path.name, "sha256": sha256_file(fragment.path)}
            for fragment in fragments
        ],
    }
    if source_version_before_build:
        manifest["source_version_before_build"] = source_version_before_build
    if python_api_wheel_path is not None:
        wheel_path = python_api_wheel_path.resolve()
        if not wheel_path.is_file() or wheel_path.suffix.lower() != ".whl":
            raise ReleaseWorkflowError(f"Built Python API wheel was not found: {wheel_path}")
        destination = python_api_package_dir or configured_python_api_package_dir()
        manifest["python_api_wheel"] = {
            "path": str(wheel_path),
            "name": wheel_path.name,
            "sha256": sha256_file(wheel_path),
            "package_dir": str(destination),
        }

    path = pending_manifest_path(product, version, work_dir)
    _write_json(path, manifest)
    return path, manifest


def _load_manifest(product: str, version: str, work_dir: Path | None = None) -> tuple[Path, dict[str, Any]]:
    product = normalize_product(product)
    version = validate_version(version)
    path = pending_manifest_path(product, version, work_dir)
    manifest = _read_json(path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ReleaseWorkflowError(f"Unsupported pending release record format: {path}")
    if manifest.get("product") != product or manifest.get("version") != version:
        raise ReleaseWorkflowError(f"Pending release record does not match {product} {version}: {path}")
    expected_repo, expected_tag = resolve_release_channel(product, version)
    if manifest.get("repository") != expected_repo or manifest.get("tag") != expected_tag:
        raise ReleaseWorkflowError(
            f"Pending release record does not match the current release channel: {path}"
        )
    return path, manifest


def _manifest_fragments(manifest: dict[str, Any]) -> list[release_notes.Fragment]:
    expected = manifest.get("fragments")
    if not isinstance(expected, list):
        raise ReleaseWorkflowError("Pending release record has no valid fragment list.")

    try:
        available = {fragment.path.name: fragment for fragment in release_notes.load_unreleased_fragments()}
    except (OSError, ValueError) as exc:
        raise ReleaseWorkflowError(f"Could not read current release fragments: {exc}") from exc

    fragments: list[release_notes.Fragment] = []
    names: set[str] = set()
    for item in expected:
        if not isinstance(item, dict):
            raise ReleaseWorkflowError("Pending release record has an invalid fragment entry.")
        name = str(item.get("name", "")).strip()
        expected_hash = str(item.get("sha256", "")).strip().lower()
        if not name or not expected_hash or name in names:
            raise ReleaseWorkflowError("Pending release record has an invalid fragment entry.")
        names.add(name)
        fragment = available.get(name)
        if fragment is None:
            raise ReleaseWorkflowError(
                f"Release fragment {name} is no longer unreleased. Rebuild before publishing."
            )
        if sha256_file(fragment.path).lower() != expected_hash:
            raise ReleaseWorkflowError(
                f"Release fragment {name} changed after the installer was built. Rebuild before publishing."
            )
        fragments.append(fragment)
    return fragments


def _validate_installer(manifest: dict[str, Any]) -> Path:
    installer = manifest.get("installer")
    if not isinstance(installer, dict):
        raise ReleaseWorkflowError("Pending release record has no valid installer information.")
    path = Path(str(installer.get("path", ""))).expanduser()
    expected_name = installer_name(str(manifest["product"]), str(manifest["version"]))
    if path.name != expected_name or not path.is_file():
        raise ReleaseWorkflowError(f"Built installer is unavailable: {path}")
    expected_hash = str(installer.get("sha256", "")).strip().lower()
    if not expected_hash or sha256_file(path).lower() != expected_hash:
        raise ReleaseWorkflowError(
            "The built installer changed after it was recorded. Rebuild before publishing."
        )
    return path.resolve()


def _validate_python_api_wheel(manifest: dict[str, Any]) -> tuple[Path, Path]:
    wheel = manifest.get("python_api_wheel")
    if not isinstance(wheel, dict):
        raise ReleaseWorkflowError("Pending Arco release has no valid Python API wheel.")
    wheel_path = Path(str(wheel.get("path", ""))).expanduser()
    package_dir = Path(str(wheel.get("package_dir", ""))).expanduser()
    expected_hash = str(wheel.get("sha256", "")).strip().lower()
    if not wheel_path.is_file() or wheel_path.suffix.lower() != ".whl":
        raise ReleaseWorkflowError(f"Built Python API wheel is unavailable: {wheel_path}")
    if not expected_hash or sha256_file(wheel_path).lower() != expected_hash:
        raise ReleaseWorkflowError(
            "The built Python API wheel changed after it was recorded. Rebuild before publishing."
        )
    if not str(package_dir):
        raise ReleaseWorkflowError("Pending Arco release has no Python API package destination.")
    return wheel_path.resolve(), package_dir


def _copy_file_if_changed(source: Path, destination: Path) -> None:
    if destination.is_file() and sha256_file(destination) == sha256_file(source):
        return
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReleaseWorkflowError(
            f"Could not create Python API package directory {destination.parent}: {exc}"
        ) from exc
    temp_path = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temp_path)
        os.replace(temp_path, destination)
    except OSError as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise ReleaseWorkflowError(f"Could not publish Python API wheel to {destination}: {exc}") from exc


def publish_python_api_wheel(wheel_path: Path, package_dir: Path) -> tuple[Path, Path]:
    """Publish the versioned wheel and canonical latest wheel through one owner."""
    wheel_path = wheel_path.resolve()
    if not wheel_path.is_file() or wheel_path.suffix.lower() != ".whl":
        raise ReleaseWorkflowError(f"Built Python API wheel was not found: {wheel_path}")
    package_dir = package_dir.expanduser()
    versioned_target = package_dir / wheel_path.name
    latest_target = package_dir / "arcrho_api-latest.whl"
    _copy_file_if_changed(wheel_path, versioned_target)
    _copy_file_if_changed(wheel_path, latest_target)
    return versioned_target, latest_target


def _gh_path() -> str:
    executable = shutil.which("gh")
    if executable is None:
        raise ReleaseWorkflowError("GitHub CLI (gh) was not found on PATH. Run gh auth login first.")
    return executable


def _run_checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    output: Callable[[str], None] | None = None,
) -> str:
    if output is None:
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except OSError as exc:
            raise ReleaseWorkflowError(f"Could not start {' '.join(command)}: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise ReleaseWorkflowError(
                f"Command failed with exit code {completed.returncode}: {' '.join(command)}\n{detail}".strip()
            )
        return completed.stdout

    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as exc:
        raise ReleaseWorkflowError(f"Could not start {' '.join(command)}: {exc}") from exc
    lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        text = line.rstrip()
        lines.append(text)
        output(text)
    exit_code = process.wait()
    if exit_code != 0:
        raise ReleaseWorkflowError(
            f"Command failed with exit code {exit_code}: {' '.join(command)}\n" + "\n".join(lines[-20:])
        )
    return "\n".join(lines)


def next_version(product: str) -> str:
    product = normalize_product(product)
    try:
        package_json = version_manager.load_json(FRONTEND_ROOT / "package.json")
        current_version = str(package_json.get("version", "")).strip()
        # collect_github_release_versions takes product before tag format.  Spell
        # the parameters out so future changes cannot silently swap them.
        repository, tag_format = version_manager.load_release_channel(
            version_manager.DEFAULT_RELEASE_CHANNEL_PATH
        )
        published_versions = version_manager.collect_github_release_versions(
            repository, product, tag_format
        )
        return version_manager.resolve_target_version(
            current_version,
            None,
            published_versions=published_versions,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowError(str(exc)) from exc


def _release_history_sort_key(record: dict[str, Any]) -> tuple[bool, str]:
    """Order releases newest first.

    GitHub returns RFC 3339 UTC timestamps, so their string order is already
    chronological.  A draft that was never published has no timestamp at all;
    reversing on the presence flag keeps those at the end instead of the top.
    """

    published_at = str(record.get("published_at", ""))
    return (bool(published_at), published_at)


def list_release_history(product: str, limit: int = DEFAULT_RECENT_RELEASE_LIMIT) -> list[dict[str, Any]]:
    product = normalize_product(product)
    limit = max(1, min(int(limit), MAX_RELEASE_HISTORY_LIMIT))
    repository, _ = resolve_release_channel(product, "0.0.0")
    output = _run_checked(
        [
            _gh_path(),
            "api",
            f"repos/{repository}/releases?per_page={limit}",
        ]
    )
    try:
        payload = json.loads(output or "[]")
    except json.JSONDecodeError as exc:
        raise ReleaseWorkflowError(f"GitHub returned invalid release history JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ReleaseWorkflowError("GitHub returned an unexpected release history payload.")

    _, tag_format = version_manager.load_release_channel(version_manager.DEFAULT_RELEASE_CHANNEL_PATH)
    tag_re = version_manager.build_release_tag_re(tag_format, product)
    history: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag_name", "")).strip()
        match = tag_re.fullmatch(tag)
        if not match:
            continue
        history.append(
            {
                "product": product,
                "version": match.group(1),
                "tag": tag,
                "name": str(item.get("name") or f"{product} {match.group(1)}"),
                "published_at": str(item.get("published_at") or item.get("created_at") or ""),
                "draft": bool(item.get("draft")),
                "prerelease": bool(item.get("prerelease")),
                "url": str(item.get("html_url") or ""),
            }
        )
    history.sort(key=_release_history_sort_key, reverse=True)
    return history


def _ensure_version_is_publishable(product: str, version: str) -> None:
    history = list_release_history(product, MAX_RELEASE_HISTORY_LIMIT)
    tag = resolve_release_channel(product, version)[1]
    if any(item["tag"] == tag for item in history):
        raise ReleaseWorkflowError(
            f"GitHub already has {tag}. Refusing to replace an existing release."
        )
    published_versions = [item["version"] for item in history]
    if published_versions and version_manager.parse_version(version) <= max(
        (version_manager.parse_version(item) for item in published_versions)
    ):
        highest = max(published_versions, key=version_manager.parse_version)
        raise ReleaseWorkflowError(
            f"{version} is not newer than the highest published {product} version {highest}."
        )


def _fragment_list_path(manifest_path: Path) -> Path:
    return manifest_path.with_suffix(".fragments.json")


def _release_notes_preview_path(manifest_path: Path) -> Path:
    return manifest_path.with_suffix(".release-notes.md")


def _write_release_notes_preview(
    manifest_path: Path,
    manifest: dict[str, Any],
    fragments: list[release_notes.Fragment],
) -> Path:
    path = _release_notes_preview_path(manifest_path)
    rendered = release_notes.render_release_notes(
        str(manifest["version"]), date.today().isoformat(), fragments
    )
    _atomic_write_text(path, rendered)
    return path


def _run_repository_bookkeeping(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    commit: bool,
    output: Callable[[str], None] | None,
) -> None:
    fragment_names = [item["name"] for item in manifest["fragments"]]
    fragment_list_path = _fragment_list_path(manifest_path)
    _write_json(fragment_list_path, fragment_names)
    command = [
        sys.executable,
        str(SYNC_SCRIPT),
        str(manifest["version"]),
        "--product",
        str(manifest["product"]),
        "--fragment-list",
        str(fragment_list_path),
    ]
    if commit:
        command.append("--commit")
    _run_checked(command, cwd=FRONTEND_ROOT, output=output)


def publish_pending_release(
    product: str,
    version: str,
    *,
    work_dir: Path | None = None,
    commit: bool = True,
    output: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Publish a verified pending installer, then apply canonical repository bookkeeping."""
    manifest_path, manifest = _load_manifest(product, version, work_dir)
    status = str(manifest.get("status", ""))
    if status == "published":
        raise ReleaseWorkflowError(f"{product} {version} is already marked as published locally.")
    if status == "revoked":
        raise ReleaseWorkflowError(f"{product} {version} was revoked locally. Rebuild before publishing it again.")
    if status not in {"built", "remote_published"}:
        raise ReleaseWorkflowError(f"Pending release has an unsupported status '{status}'.")

    if status == "built":
        installer_path = _validate_installer(manifest)
        fragments = _manifest_fragments(manifest)
        _ensure_version_is_publishable(str(manifest["product"]), str(manifest["version"]))
        notes_path = _write_release_notes_preview(manifest_path, manifest, fragments)
        if output:
            output(f"Publishing {manifest['product']} {manifest['version']} to GitHub Releases...")
        _run_checked(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PUBLISH_SCRIPT),
                "-InstallerPath",
                str(installer_path),
                "-ReleaseNotesPath",
                str(notes_path),
                "-ProductName",
                str(manifest["product"]),
            ],
            cwd=FRONTEND_ROOT,
            output=output,
        )
        manifest["status"] = "remote_published"
        manifest["remote_published_at"] = _utc_now()
        manifest["release_url"] = (
            f"https://github.com/{manifest['repository']}/releases/tag/{manifest['tag']}"
        )
        _write_json(manifest_path, manifest)

    if manifest["product"] == "Arco":
        wheel_path, package_dir = _validate_python_api_wheel(manifest)
        if output:
            output(f"Publishing Python API wheel to {package_dir}...")
        publish_python_api_wheel(wheel_path, package_dir)
        manifest["python_api_published_at"] = _utc_now()
        _write_json(manifest_path, manifest)

    # A failed bookkeeping step must be recoverable without attempting to upload
    # the installer a second time.  Validate fragments again before consuming them.
    _manifest_fragments(manifest)
    if output:
        output("Recording the published release in the local repository...")
    try:
        _run_repository_bookkeeping(manifest_path, manifest, commit=commit, output=output)
    except ReleaseWorkflowError:
        manifest["status"] = "remote_published"
        manifest["bookkeeping_error_at"] = _utc_now()
        _write_json(manifest_path, manifest)
        raise

    manifest["status"] = "published"
    manifest["published_at"] = _utc_now()
    _write_json(manifest_path, manifest)
    return manifest


def list_pending_releases(work_dir: Path | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    directory = pending_releases_dir(work_dir)
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*-v*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if path.name.endswith(".fragments.json"):
            continue
        try:
            manifest = _read_json(path)
        except ReleaseWorkflowError:
            continue
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            continue
        manifest["manifest_path"] = str(path)
        records.append(manifest)
    return records


def revoke_remote_release(
    product: str,
    version: str,
    *,
    work_dir: Path | None = None,
    output: Callable[[str], None] | None = None,
) -> None:
    """Delete a GitHub Release and its release tag after explicit UI/CLI confirmation."""
    product = normalize_product(product)
    version = validate_version(version)
    repository, tag = resolve_release_channel(product, version)
    history = list_release_history(product, MAX_RELEASE_HISTORY_LIMIT)
    if not any(item["tag"] == tag for item in history):
        raise ReleaseWorkflowError(f"GitHub does not list a {product} release tagged {tag}.")

    if output:
        output(f"Revoking GitHub Release {tag} and deleting its tag...")
    _run_checked(
        [
            _gh_path(),
            "release",
            "delete",
            tag,
            "--repo",
            repository,
            "--cleanup-tag",
            "--yes",
        ],
        output=output,
    )

    # Installed apps find their update through the feed, which would otherwise
    # keep offering the installer just deleted.
    if output:
        output(f"Rebuilding the {product} update feed...")
    _run_checked(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UPDATE_MANIFEST_SCRIPT),
            "-ProductName",
            product,
        ],
        cwd=FRONTEND_ROOT,
        output=output,
    )

    try:
        manifest_path, manifest = _load_manifest(product, version, work_dir)
    except ReleaseWorkflowError:
        return
    manifest["status"] = "revoked"
    manifest["revoked_at"] = _utc_now()
    _write_json(manifest_path, manifest)


def _print_output(line: str) -> None:
    print(line, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage local Arco installers before and after GitHub publication."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot-version", help="Save current version metadata.")
    snapshot.add_argument("--snapshot-path", required=True)

    restore = subparsers.add_parser("restore-version", help="Restore saved version metadata.")
    restore.add_argument("--snapshot-path", required=True)
    restore.add_argument("--delete", action="store_true", help="Delete the snapshot after restoration.")

    capture = subparsers.add_parser("capture-built", help="Record a locally built installer.")
    capture.add_argument("--product", required=True)
    capture.add_argument("--version", required=True)
    capture.add_argument("--installer-path", required=True)
    capture.add_argument("--work-dir")
    capture.add_argument("--version-snapshot-path")
    capture.add_argument("--python-api-wheel-path")
    capture.add_argument("--python-api-package-dir")

    python_api = subparsers.add_parser("publish-python-api", help="Publish a built Python API wheel.")
    python_api.add_argument("--wheel-path", required=True)
    python_api.add_argument("--destination", required=True)

    next_version_parser = subparsers.add_parser("next-version", help="Print the suggested next version.")
    next_version_parser.add_argument("--product", required=True)

    pending = subparsers.add_parser("pending", help="List recorded local installers.")
    pending.add_argument("--work-dir")
    pending.add_argument("--json", action="store_true")

    history = subparsers.add_parser("history", help="List recent GitHub Releases.")
    history.add_argument("--product", required=True)
    history.add_argument("--limit", type=int, default=DEFAULT_RECENT_RELEASE_LIMIT)
    history.add_argument("--json", action="store_true")

    publish = subparsers.add_parser("publish", help="Publish a verified local installer.")
    publish.add_argument("--product", required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--work-dir")
    publish.add_argument("--no-commit", action="store_true")

    revoke = subparsers.add_parser("revoke", help="Delete a GitHub Release and its tag.")
    revoke.add_argument("--product", required=True)
    revoke.add_argument("--version", required=True)
    revoke.add_argument(
        "--confirm-version",
        required=True,
        help="Must exactly match --version to authorize this destructive action.",
    )
    revoke.add_argument("--work-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot-version":
            path = snapshot_version_metadata(Path(args.snapshot_path))
            print(path)
            return 0
        if args.command == "restore-version":
            restore_version_metadata(Path(args.snapshot_path), delete_snapshot=args.delete)
            print("Version metadata restored.")
            return 0
        if args.command == "capture-built":
            path, manifest = capture_built_release(
                args.product,
                args.version,
                Path(args.installer_path),
                work_dir=Path(args.work_dir) if args.work_dir else None,
                version_snapshot_path=(
                    Path(args.version_snapshot_path) if args.version_snapshot_path else None
                ),
                python_api_wheel_path=(
                    Path(args.python_api_wheel_path) if args.python_api_wheel_path else None
                ),
                python_api_package_dir=(
                    Path(args.python_api_package_dir) if args.python_api_package_dir else None
                ),
            )
            print(f"Recorded pending {manifest['product']} {manifest['version']}: {path}")
            return 0
        if args.command == "publish-python-api":
            versioned_target, latest_target = publish_python_api_wheel(
                Path(args.wheel_path), Path(args.destination)
            )
            print(f"Published Python API wheel: {versioned_target}")
            print(f"Updated Python API latest wheel: {latest_target}")
            return 0
        if args.command == "next-version":
            print(next_version(args.product))
            return 0
        if args.command == "pending":
            records = list_pending_releases(Path(args.work_dir) if args.work_dir else None)
            if args.json:
                print(json.dumps(records, indent=2))
            else:
                for record in records:
                    print(f"{record.get('product')} {record.get('version')} - {record.get('status')}")
            return 0
        if args.command == "history":
            records = list_release_history(args.product, args.limit)
            if args.json:
                print(json.dumps(records, indent=2))
            else:
                for record in records:
                    print(
                        f"{record['version']}  {record['published_at']}  "
                        f"{record['tag']}  {record['url']}"
                    )
            return 0
        if args.command == "publish":
            publish_pending_release(
                args.product,
                args.version,
                work_dir=Path(args.work_dir) if args.work_dir else None,
                commit=not args.no_commit,
                output=_print_output,
            )
            print(f"Published {normalize_product(args.product)} {validate_version(args.version)}.")
            return 0
        if args.command == "revoke":
            if args.confirm_version != args.version:
                raise ReleaseWorkflowError(
                    "--confirm-version must exactly match --version before a release can be revoked."
                )
            revoke_remote_release(
                args.product,
                args.version,
                work_dir=Path(args.work_dir) if args.work_dir else None,
                output=_print_output,
            )
            print(f"Revoked {normalize_product(args.product)} {validate_version(args.version)}.")
            return 0
    except ReleaseWorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
