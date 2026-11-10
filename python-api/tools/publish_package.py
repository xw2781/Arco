"""Build and publish the arcrho-api wheel for notebook users."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from build_wheel import ROOT, build_wheel


DEFAULT_PACKAGE_DIR = Path(r"E:\Arco Server\packages")
LATEST_WHEEL_NAME = "arcrho_api-latest.whl"


def _default_package_dir() -> Path:
    return Path(os.environ.get("PYTHON_API_PACKAGE_DIR") or DEFAULT_PACKAGE_DIR)


def publish_package(package_dir: Path, *, version: str | None = None, latest_name: str = LATEST_WHEEL_NAME) -> Path:
    dist_dir = ROOT / "dist"
    wheel_path = build_wheel(dist_dir, version_override=version)

    package_dir.mkdir(parents=True, exist_ok=True)
    versioned_target = package_dir / wheel_path.name
    latest_target = package_dir / latest_name

    shutil.copy2(wheel_path, versioned_target)
    shutil.copy2(wheel_path, latest_target)
    return versioned_target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the arcrho-api wheel to a shared package folder.")
    parser.add_argument(
        "--package-dir",
        default=str(_default_package_dir()),
        help="Shared folder for published wheels. Defaults to PYTHON_API_PACKAGE_DIR or E:\\Arco Server\\packages.",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Optional API package version override. If omitted, python-api/pyproject.toml is used.",
    )
    parser.add_argument(
        "--latest-name",
        default=LATEST_WHEEL_NAME,
        help=f"Alias wheel filename to overwrite. Defaults to {LATEST_WHEEL_NAME}.",
    )
    args = parser.parse_args(argv)

    package_dir = Path(args.package_dir).resolve()
    version = args.version.strip() or None
    versioned_target = publish_package(package_dir, version=version, latest_name=args.latest_name)
    latest_target = package_dir / args.latest_name

    print(f"Published versioned wheel: {versioned_target}")
    print(f"Published latest alias:    {latest_target}")
    print()
    print("User install/update command:")
    print(f'  {sys.executable} -m pip install --upgrade "{latest_target}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
