from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import subprocess
import sys
import warnings
from pathlib import Path


BUILD_DIR = Path(__file__).resolve().parent
FRONTEND_ROOT = BUILD_DIR.parent
MONOREPO_ROOT = FRONTEND_ROOT.parent
PYTHON_API_SRC = MONOREPO_ROOT / "python-api" / "src"

for path in (FRONTEND_ROOT, PYTHON_API_SRC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from app_server.services.sql_formatting.version import SQLFLUFF_REQUIREMENT

REQUIRED_MODULES = {
    "PyInstaller": "pyinstaller",
    "uvicorn": "uvicorn",
    "fastapi": "fastapi",
    "starlette": "starlette",
    "pydantic": "pydantic",
    "pydantic_core": "pydantic-core",
    "pandas": "pandas",
    "numpy": "numpy",
    "openpyxl": "openpyxl",
    "snowflake.connector": "snowflake-connector-python",
    # server.spec and arcode_server.spec list pyodbc as a hidden import for the
    # managed source-table import and the Arcode SQL Server console. It is
    # optional at runtime, so PyInstaller only logs an error and ships a bundle
    # whose SQL Server access always reports the missing driver.
    "pyodbc": "pyodbc",
    "watchdog": "watchdog",
    "arcrho_api": None,
    "sqlfluff": SQLFLUFF_REQUIREMENT,
}
# pywin32 exists only on Windows; the macOS build ships without Excel COM and
# the Windows Gateway sign-in.
if sys.platform == "win32":
    REQUIRED_MODULES.update({
        "pythoncom": "pywin32",
        "pywintypes": "pywin32",
        "win32com": "pywin32",
        "sspi": "pywin32",
    })


def find_missing_modules() -> list[tuple[str, str | None]]:
    missing: list[tuple[str, str | None]] = []
    for module_name, package_name in REQUIRED_MODULES.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                importlib.import_module(module_name)
            if package_name and "==" in package_name:
                distribution_name, expected_version = package_name.split("==", 1)
                installed_version = importlib.metadata.version(distribution_name)
                if installed_version != expected_version:
                    missing.append((module_name, package_name))
        except Exception:
            missing.append((module_name, package_name))
    return missing


def print_missing_modules(missing: list[tuple[str, str | None]]) -> list[str]:
    print("ERROR: Missing Python build dependencies for the packaged app server.")
    print()
    for module_name, package_name in missing:
        if package_name:
            print(f"- {module_name} (install package: {package_name})")
        else:
            print(f"- {module_name}")

    packages = sorted({package for _, package in missing if package})
    if packages:
        print()
        print("Install missing packages for the selected Python 3.10 interpreter:")
        print(f"  {sys.executable} -m pip install {' '.join(packages)}")
    return packages


def install_missing_packages(packages: list[str]) -> int:
    if not packages:
        print()
        print("ERROR: Missing modules do not have installable package mappings.")
        return 1

    print()
    print("Installing missing Python build dependencies...")
    return subprocess.call([sys.executable, "-m", "pip", "install", *packages])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ArcRho Python build dependencies.")
    parser.add_argument(
        "--install-missing",
        action="store_true",
        help="Install missing package-mapped dependencies with pip, then validate again.",
    )
    args = parser.parse_args()

    missing = find_missing_modules()

    if not missing:
        print("Python build dependencies validated.")
        return 0

    packages = print_missing_modules(missing)
    if not args.install_missing:
        return 1

    result = install_missing_packages(packages)
    if result != 0:
        return result

    missing = find_missing_modules()
    if not missing:
        print()
        print("Python build dependencies validated.")
        return 0

    print()
    print("ERROR: Python build dependencies are still missing after pip install.")
    print_missing_modules(missing)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
