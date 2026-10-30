"""Build a pure-Python arcrho-api wheel with only the standard library."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 build runtime.
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SRC = ROOT / "src"
PACKAGES = ("arcrho_api", "arcrho_mcp")
STANDALONE_MODULES = (
    SRC / "arcrho_project_duplication_contract.py",
    SRC / "arcrho_engine_job_lease.py",
    SRC / "arcrho_dependent_propagation_contract.py",
    SRC / "arcrho_engine_save_contract.py",
    SRC / "arcrho_hosted_save_http_contract.py",
    SRC / "arcrho_workspace_read_contract.py",
    SRC / "arcrho_workspace_mutation_contract.py",
)


def _wheel_escape(value: str) -> str:
    return value.replace("-", "_").replace(".", "_")


def _hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _toml_string(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _toml_string_list(value: str) -> list[str]:
    text = value.strip()
    if not text.startswith("[") or not text.endswith("]"):
        return []
    return [_toml_string(item) for item in text[1:-1].split(",") if item.strip()]


def _load_pyproject() -> dict:
    text = PYPROJECT.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(text)

    project: dict[str, object] = {}
    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project or "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if key in {"dependencies"}:
            project[key] = _toml_string_list(raw_value)
        elif key in {"authors"}:
            names = re.findall(r'name\s*=\s*"([^"]+)"', raw_value)
            project[key] = [{"name": name} for name in names]
        else:
            project[key] = _toml_string(raw_value)
    return {"project": project}


def _metadata(project: dict) -> str:
    lines = [
        "Metadata-Version: 2.3",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project.get('description', '')}",
        f"Requires-Python: {project.get('requires-python', '>=3.10')}",
    ]
    license_value = project.get("license", {})
    if isinstance(license_value, dict) and license_value.get("text"):
        lines.append(f"License: {license_value['text']}")
    for author in project.get("authors", []):
        if author.get("name"):
            lines.append(f"Author: {author['name']}")
    for dependency in project.get("dependencies", []):
        lines.append(f"Requires-Dist: {dependency}")
    lines.append("")
    readme = ROOT / str(project.get("readme", "README.md"))
    if readme.exists():
        lines.append(readme.read_text(encoding="utf-8"))
    return "\n".join(lines).rstrip() + "\n"


def _wheel_file() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: arcrho-api standard-library wheel builder",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def build_wheel(out_dir: Path, *, version_override: str | None = None) -> Path:
    config = _load_pyproject()
    project = dict(config["project"])
    if version_override:
        project["version"] = version_override
    name = str(project["name"])
    version = str(project["version"])
    dist = _wheel_escape(name)
    dist_info = f"{dist}-{version}.dist-info"
    wheel_name = f"{dist}-{version}-py3-none-any.whl"
    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = out_dir / wheel_name

    files: dict[str, bytes] = {}
    for package in PACKAGES:
        for path in sorted((SRC / package).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".pyi"}:
                files[path.relative_to(SRC).as_posix()] = path.read_bytes()
    for path in STANDALONE_MODULES:
        if not path.is_file():
            raise FileNotFoundError(f"Required standalone module is missing: {path}")
        files[path.name] = path.read_bytes()

    files[f"{dist_info}/METADATA"] = _metadata(project).encode("utf-8")
    files[f"{dist_info}/WHEEL"] = _wheel_file().encode("utf-8")

    record_rows: list[list[str]] = []
    for name_in_wheel, data in files.items():
        record_rows.append([name_in_wheel, _hash(data), str(len(data))])
    record_path = f"{dist_info}/RECORD"
    record_rows.append([record_path, "", ""])
    record_io = io.StringIO()
    writer = csv.writer(record_io, lineterminator="\n")
    writer.writerows(record_rows)
    files[record_path] = record_io.getvalue().encode("utf-8")

    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name_in_wheel, data in files.items():
            zf.writestr(name_in_wheel, data)
    return wheel_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the arcrho-api wheel.")
    parser.add_argument("--out-dir", default=str(ROOT / "dist"), help="Directory where the wheel is written.")
    parser.add_argument("--version", default="", help="Optional wheel version override.")
    args = parser.parse_args(argv)
    wheel_path = build_wheel(Path(args.out_dir).resolve(), version_override=args.version.strip() or None)
    print(wheel_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
