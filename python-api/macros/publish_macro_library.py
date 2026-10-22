"""Publish active ArcRho macros to the shared server macro library.

Copies active ``*.py`` macros in this folder to the shared library that the
ArcRho app's "Macro Library" window reads (default
``E:\\ArcRho Server\\shared\\macros``, override with ``--library-dir`` or the
``ARCRHO_MACRO_LIBRARY_DIR`` environment variable). Use ``--only`` to publish
selected macros.

For each macro it:
- validates the ``<arcrho-macro>`` metadata block has a semantic ``Version``
  and a non-empty single-line ``Release Note`` (see README.md);
- archives the library copy it replaces to
  ``<library>/archive/<macro-stem>/<old-version>/<macro-file>``;
- replaces the library file atomically (temp file + ``os.replace``) so
  readers never observe a half-written macro.

It also publishes the canonical ResQ migration Python runtime as an immutable
release under ``<shared>/python-api/releases`` and atomically switches
``<shared>/python-api/current.json``. ResQ macros load that read-only support
bundle on client PCs that do not have the ArcRho development checkout.

Run by deployers only; the library folder should be read-only for users.

``--check`` writes nothing and exits 1 when the library is behind this folder,
so an agent can confirm a macro or support change reached users.

Usage:
    python publish_macro_library.py [--library-dir PATH] [--dry-run | --check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_LIBRARY_DIR = r"E:\ArcRho Server\shared\macros"
LIBRARY_DIR_ENV = "ARCRHO_MACRO_LIBRARY_DIR"
ARCHIVE_DIR_NAME = "archive"
META_BEGIN = "# <arcrho-macro>"
META_END = "# </arcrho-macro>"
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

SOURCE_DIR = Path(__file__).resolve().parent
MIGRATION_SOURCE_DIR = SOURCE_DIR.parent / "migration"
SYNC_EXPORTER_SOURCE = SOURCE_DIR / "export_reserving_class_to_resq.py"
SUPPORT_RELEASES_DIR = Path("python-api") / "releases"
SUPPORT_POINTER = Path("python-api") / "current.json"
SUPPORT_MANIFEST = "manifest.json"


def parse_meta_field(text: str, field: str) -> str:
    in_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == META_BEGIN:
            in_block = True
            continue
        if line == META_END:
            break
        if not in_block:
            continue
        if line.startswith("#"):
            line = line[1:].strip()
        if ":" in line:
            key, value = line.split(":", 1)
            if key.strip().lower() == field.lower():
                return value.strip()
    return ""


def validate_macro(path: Path, text: str) -> list[str]:
    problems: list[str] = []
    if META_BEGIN not in text:
        problems.append("missing <arcrho-macro> metadata block")
        return problems
    version = parse_meta_field(text, "Version")
    if not SEMVER_PATTERN.match(version):
        problems.append(f"Version must be major.minor.patch, found: {version or '(empty)'}")
    if not parse_meta_field(text, "Release Note"):
        problems.append("Release Note is missing or empty")
    return problems


def atomic_write(target: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".publish_", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.remove(temp_name)
        except OSError:
            pass
        raise


def archive_replaced_copy(library_dir: Path, target: Path, dry_run: bool) -> str:
    old_text = target.read_text(encoding="utf-8-sig")
    old_version = parse_meta_field(old_text, "Version") or "unversioned"
    archive_path = library_dir / ARCHIVE_DIR_NAME / target.stem / old_version / target.name
    if archive_path.exists():
        return f"archive already holds v{old_version}"
    if not dry_run:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(archive_path, target.read_bytes())
    return f"archived previous v{old_version}"


def publish_migration_support(library_dir: Path, dry_run: bool) -> tuple[int, int]:
    """Publish an immutable support release, then atomically switch its pointer."""

    sources = sorted(
        (path for path in MIGRATION_SOURCE_DIR.rglob("*.py") if "references" not in path.parts),
        key=lambda path: str(path.relative_to(MIGRATION_SOURCE_DIR)).casefold(),
    )
    if not sources:
        raise FileNotFoundError(f"No migration support modules found in {MIGRATION_SOURCE_DIR}")
    digest_builder = hashlib.sha256()
    payloads: list[tuple[Path, bytes]] = []
    for source in sources:
        relative = Path("migration") / source.relative_to(MIGRATION_SOURCE_DIR)
        data = source.read_bytes()
        digest_builder.update(str(relative).replace("\\", "/").encode("utf-8"))
        digest_builder.update(b"\0")
        digest_builder.update(data)
        payloads.append((relative, data))
    if not SYNC_EXPORTER_SOURCE.is_file():
        raise FileNotFoundError(f"Sync exporter not found: {SYNC_EXPORTER_SOURCE}")
    exporter_relative = Path("macros") / SYNC_EXPORTER_SOURCE.name
    exporter_data = SYNC_EXPORTER_SOURCE.read_bytes()
    digest_builder.update(str(exporter_relative).replace("\\", "/").encode("utf-8"))
    digest_builder.update(b"\0")
    digest_builder.update(exporter_data)
    payloads.append((exporter_relative, exporter_data))
    sync_macro_source = SOURCE_DIR / "sync_reserving_class_with_resq.py"
    if not sync_macro_source.is_file():
        raise FileNotFoundError(f"Sync macro not found: {sync_macro_source}")
    sync_macro_data = sync_macro_source.read_bytes()
    sync_macro_version = parse_meta_field(
        sync_macro_data.decode("utf-8-sig"), "Version"
    )
    digest_builder.update(b"sync-macro-contract\0")
    digest_builder.update(sync_macro_data)
    release_id = digest_builder.hexdigest()[:20]
    release_root = library_dir.parent / SUPPORT_RELEASES_DIR / release_id
    target_root = release_root
    changed = 0
    unchanged = 0
    for relative, data in payloads:
        target = target_root / relative
        if target.is_file() and target.read_bytes() == data:
            unchanged += 1
            continue
        changed += 1
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(target, data)
    if not dry_run:
        for relative, data in payloads:
            target = target_root / relative
            if not target.is_file() or target.read_bytes() != data:
                raise RuntimeError(f"Published migration support failed verification: {target}")
        manifest = {
            "version": 1,
            "runtime_api_version": 1,
            "release_id": release_id,
            "sync_macro_version": sync_macro_version,
            "sync_macro_sha256": hashlib.sha256(sync_macro_data).hexdigest(),
            "files": {
                str(relative).replace("\\", "/"): hashlib.sha256(data).hexdigest()
                for relative, data in payloads
            },
        }
        manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        atomic_write(release_root / SUPPORT_MANIFEST, manifest_bytes)
        pointer = {
            "version": 1,
            "release_id": release_id,
            "relative_root": str(Path("releases") / release_id).replace("\\", "/"),
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        }
        atomic_write(
            library_dir.parent / SUPPORT_POINTER,
            (json.dumps(pointer, indent=2) + "\n").encode("utf-8"),
        )
    return changed, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--library-dir",
        default=os.environ.get(LIBRARY_DIR_ENV) or DEFAULT_LIBRARY_DIR,
        help="Shared macro library folder (default: %(default)s)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report actions without writing")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report actions without writing; exit 1 if anything is unpublished",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="MACRO_FILE",
        help="Publish only the named macro file(s); repeatable (default: all active macros)",
    )
    args = parser.parse_args()

    library_dir = Path(args.library_dir)
    dry_run = args.dry_run or args.check
    macros = sorted(
        (p for p in SOURCE_DIR.glob("*.py") if p.name != Path(__file__).name),
        key=lambda p: p.name.lower(),
    )
    if args.only:
        wanted = {name.lower() for name in args.only}
        macros = [p for p in macros if p.name.lower() in wanted]
        missing = wanted - {p.name.lower() for p in macros}
        if missing:
            print(f"Unknown macro file(s): {', '.join(sorted(missing))}")
            return 1
    if not macros:
        print(f"No macro files found in {SOURCE_DIR}")
        return 1

    failures = 0
    for path in macros:
        text = path.read_text(encoding="utf-8-sig")
        problems = validate_macro(path, text)
        if problems:
            failures += 1
            print(f"FAIL  {path.name}: {'; '.join(problems)}")
            continue
    if failures:
        print(f"\n{failures} macro(s) failed validation; nothing was published.")
        return 1

    support_changed, support_unchanged = publish_migration_support(library_dir, dry_run)
    pending = 1 if support_changed else 0
    support_action = "WOULD PUBLISH" if dry_run else "PUBLISH"
    print(
        f"{support_action}  ResQ migration support: {support_changed} changed, "
        f"{support_unchanged} unchanged"
    )

    if not dry_run:
        library_dir.mkdir(parents=True, exist_ok=True)

    for path in macros:
        data = path.read_bytes()
        text = path.read_text(encoding="utf-8-sig")
        version = parse_meta_field(text, "Version")
        target = library_dir / path.name
        notes: list[str] = []
        if target.exists():
            if target.read_bytes() == data:
                print(f"SKIP  {path.name}: library already has v{version}")
                continue
            notes.append(archive_replaced_copy(library_dir, target, dry_run))
        pending += 1
        if not dry_run:
            atomic_write(target, data)
        action = "WOULD PUBLISH" if dry_run else "PUBLISH"
        suffix = f" ({'; '.join(notes)})" if notes else ""
        print(f"{action}  {path.name} v{version}{suffix}")

    print(f"\nLibrary: {library_dir}")
    if args.check and pending:
        print(f"{pending} item(s) are not published; run publish_macro_library.py to publish them.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
