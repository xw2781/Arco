from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .core import _normalize_import_name


DEFAULT_NUMBER_FORMAT = "0,000"
DEFAULT_DECIMAL_PLACES = 0
NUMBER_FORMATS_PATH_ENV = "ARCRHO_DATASET_NUMBER_FORMATS_PATH"
DEFAULT_NUMBER_FORMATS_PATH = Path(r"E:\Arco Server\config\dataset_number_formats.json")
_configured_number_formats_path: Path | None = None


def configure_number_formats_path(server_root: object | None = None) -> None:
    """Use the active ArcRho Server's shared number-format configuration.

    ResQ imports run both from the command line and from macros.  The latter
    supplies the server root at runtime, so the module must not retain a
    previous server's preferences between macro executions.
    """
    global _configured_number_formats_path
    root_text = str(server_root or "").strip()
    _configured_number_formats_path = (
        Path(root_text) / "config" / "dataset_number_formats.json"
        if root_text
        else None
    )
    _load_number_format_preferences_from_path.cache_clear()


def _number_formats_path() -> Path:
    configured = str(os.environ.get(NUMBER_FORMATS_PATH_ENV) or "").strip()
    if configured:
        return Path(configured)
    return _configured_number_formats_path or DEFAULT_NUMBER_FORMATS_PATH


@lru_cache(maxsize=4)
def _load_number_format_preferences_from_path(path_text: str) -> dict[str, Any]:
    try:
        with Path(path_text).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        return {"default_number_format": DEFAULT_NUMBER_FORMAT, "overrides": []}
    if not isinstance(raw, dict):
        return {"default_number_format": DEFAULT_NUMBER_FORMAT, "overrides": []}
    overrides = raw.get("overrides")
    return {
        "default_number_format": _normalize_number_format(raw.get("default_number_format")),
        "overrides": overrides if isinstance(overrides, list) else [],
    }


def _load_number_format_preferences() -> dict[str, Any]:
    return _load_number_format_preferences_from_path(str(_number_formats_path()))


def dataset_type_number_format(rc_path: object, dataset_type_name: object) -> str:
    preferences = _load_number_format_preferences()
    dataset_type_key = _normalize_import_name(dataset_type_name).casefold()
    for item in preferences["overrides"]:
        if not isinstance(item, dict):
            continue
        configured_name = _normalize_import_name(item.get("dataset_type_name")).casefold()
        if configured_name == dataset_type_key:
            return _normalize_number_format(item.get("number_format"))
    return preferences["default_number_format"]


def dataset_type_decimal_places(rc_path: object, dataset_type_name: object) -> int:
    return number_format_decimal_places(dataset_type_number_format(rc_path, dataset_type_name))


def number_format_entry(number_format: object, decimal_places: object = None) -> dict:
    """One recorded number format, written the same way by every producer.

    Mirrors ``normalizeNumberFormatEntry`` in
    ``frontend/ui/method_pages/berquist_sherman/berquist_sherman_main.js`` so a
    method JSON the migration writes and one the frontend saves cannot differ.
    """
    pattern = _normalize_number_format(number_format)
    try:
        places = int(decimal_places)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        places = number_format_decimal_places(pattern)
    places = max(0, min(6, places))
    return {
        "number_format": apply_decimal_places_to_number_format(pattern, places),
        "decimal_places": places,
    }


def apply_decimal_places_to_number_format(value: object, decimal_places: int) -> str:
    """Rewrite the fraction of every section of an Excel-style pattern.

    Mirrors ``applyDecimalPlacesToDatasetNumberFormat`` in
    ``frontend/ui/shared/dataset/dataset_number_format.js``; the two must keep
    producing the same text, so a pattern such as ``#,##0;(#,##0)`` cannot end
    up with its two halves disagreeing on one side and not the other.
    """
    pattern = _normalize_number_format(value)
    places = max(0, min(6, int(decimal_places)))
    rebuilt = ";".join(
        _apply_decimal_places_to_section(section, places)
        for section in _split_sections(pattern)
    )
    return _normalize_number_format(rebuilt)


def _apply_decimal_places_to_section(section: str, places: int) -> str:
    match = re.search(r"[0#,]+(?:\.[0#?]+)?", section)
    if not match:
        return section
    numeric = match.group(0)
    integer_pattern = numeric.split(".", 1)[0] or "0"
    rebuilt = f"{integer_pattern}.{'0' * places}" if places > 0 else integer_pattern
    return f"{section[: match.start()]}{rebuilt}{section[match.end():]}"


def _split_sections(pattern: str) -> list[str]:
    """Split on ``;``, skipping escapes, quoted text and bracketed blocks."""
    sections: list[str] = []
    current = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            current += pattern[index : index + 2]
            index += 2
            continue
        if char in '"[':
            closer = '"' if char == '"' else "]"
            end = pattern.find(closer, index + 1)
            stop = len(pattern) - 1 if end < 0 else end
            current += pattern[index : stop + 1]
            index = stop + 1
            continue
        if char == ";":
            sections.append(current)
            current = ""
        else:
            current += char
        index += 1
    sections.append(current)
    return sections


def number_format_decimal_places(value: object) -> int:
    text = _normalize_number_format(value)
    numeric = _numeric_pattern(text)
    dot_index = numeric.find(".")
    if dot_index < 0:
        return DEFAULT_DECIMAL_PLACES
    return max(0, min(6, len(numeric[dot_index + 1 :])))


def _normalize_number_format(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    return (text or DEFAULT_NUMBER_FORMAT)[:64]


def _numeric_pattern(value: str) -> str:
    match = re.search(r"[0#,]+(?:\.[0#]+)?", value)
    return match.group(0) if match else DEFAULT_NUMBER_FORMAT
