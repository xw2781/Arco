from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Mapping

from arcrho_api.dataset_index_contract import (
    DATASET_INDEX_VERSION,
    INDEX_FILE_NAME as DATASET_INDEX_FILE_NAME,
    METHOD_TYPE_BF,
    METHOD_TYPE_BOOTSTRAP,
    METHOD_TYPE_BS_CRA,
    METHOD_TYPE_BS_SR,
    METHOD_TYPE_CAPE_COD,
    METHOD_TYPE_DFM,
    METHOD_TYPE_NONE,
    METHOD_TYPE_RESULT_SELECTION,
)
# The one owner of persisted JSON layout, shared with the app server and the
# Python API so a migrated file and a re-saved file are byte-identical.
from arcrho_api.io import persisted_json_text
from arcrho_api.sidecar_core_contract import finalize_sidecar, validate_sidecar_core
from arcrho_api.timestamps import format_persisted_timestamp


# ResQ owns the numeric `MethodType` codes, so this module is their one ArcRho
# definition. Every consumer compares against these names, never a bare literal.
METHOD_TYPE_NONE_CODE = 0
METHOD_TYPE_DFM_CODE = 1
METHOD_TYPE_BF_CODE = 2
METHOD_TYPE_CAPE_COD_CODE = 3
METHOD_TYPE_RESULT_SELECTION_CODE = 4
METHOD_TYPE_BOOTSTRAP_CODE = 6
METHOD_TYPE_STOCHASTIC_CONSOLIDATION_CODE = 7
METHOD_TYPE_BS_SR_CODE = 8
METHOD_TYPE_BS_CRA_CODE = 9
METHOD_TYPE_GLM_CODE = 19
METHOD_STATUS_OK = 0
METHOD_STATUS_NEEDS_REVIEW = 2
# Display names for ArcRho-supported method types belong to the canonical index
# contract imported above; these two exist only in ResQ, so migration names them.
METHOD_TYPE_STOCHASTIC_CONSOLIDATION = "Stochastic Consolidation"
METHOD_TYPE_GLM = "GLM"
# Migration-facing aliases for the canonical Berquist-Sherman method-type names.
BS_SR_METHOD_TYPE = METHOD_TYPE_BS_SR
BS_CRA_METHOD_TYPE = METHOD_TYPE_BS_CRA
BS_SR_SOURCE_KIND = "berquist_sherman_sr"
BS_CRA_SOURCE_KIND = "berquist_sherman_cra"
BS_SR_JSON_FORMAT = "arcrho-berquist-sherman-sr-v4"
BS_CRA_JSON_FORMAT = "arcrho-berquist-sherman-cra-v4"
BS_SR_FILE_PREFIX = "BSSR@"
BS_CRA_FILE_PREFIX = "BSCRA@"
METHOD_TYPE_NAMES = {
    METHOD_TYPE_NONE_CODE: METHOD_TYPE_NONE,
    METHOD_TYPE_DFM_CODE: METHOD_TYPE_DFM,
    METHOD_TYPE_BF_CODE: METHOD_TYPE_BF,
    METHOD_TYPE_CAPE_COD_CODE: METHOD_TYPE_CAPE_COD,
    METHOD_TYPE_RESULT_SELECTION_CODE: METHOD_TYPE_RESULT_SELECTION,
    METHOD_TYPE_BOOTSTRAP_CODE: METHOD_TYPE_BOOTSTRAP,
    METHOD_TYPE_STOCHASTIC_CONSOLIDATION_CODE: METHOD_TYPE_STOCHASTIC_CONSOLIDATION,
    METHOD_TYPE_BS_SR_CODE: BS_SR_METHOD_TYPE,
    METHOD_TYPE_BS_CRA_CODE: BS_CRA_METHOD_TYPE,
    METHOD_TYPE_GLM_CODE: METHOD_TYPE_GLM,
}


def _clean_name(value) -> str:
    return str(value if value is not None else "").strip()


def _normalize_import_name(value) -> str:
    return re.sub(r"\s+", " ", _clean_name(value)).strip()


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _clean_name(value).lower() in {"true", "1", "yes", "y"}


def _iso_or_text(value) -> str:
    """A ResQ ``Modified`` as the persisted timestamp, or other text unchanged.

    COM hands the DATE back as a datetime labelled UTC although ResQ keeps a
    local wall-clock reading; the label is dropped and the value is converted
    from this machine's zone (``arcrho_api.timestamps``), which is why the
    migration runs on the Server PC.
    """
    if value is None:
        return ""
    if hasattr(value, "replace") and hasattr(value, "isoformat"):
        try:
            return format_persisted_timestamp(value.replace(tzinfo=None))
        except Exception:
            return value.isoformat()
    return str(value)


def _safe_attr(obj, attr: str, default=None):
    try:
        return getattr(obj, attr)
    except Exception:
        return default


def _safe_int_attr(obj, attr: str, default: int = 0) -> int:
    value = _safe_attr(obj, attr, default)
    try:
        return int(value)
    except Exception:
        return default


def normalize_method_status(value: object) -> int:
    """Map ResQ method output status to ArcRho's canonical 0/2 review status."""
    try:
        return (
            METHOD_STATUS_NEEDS_REVIEW
            if int(value) == METHOD_STATUS_NEEDS_REVIEW
            else METHOD_STATUS_OK
        )
    except (TypeError, ValueError):
        return METHOD_STATUS_OK


def _method_type_name(value: object) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        text = _clean_name(value)
        return text or "None"
    return METHOD_TYPE_NAMES.get(code, str(code))


def _method_type_code(value: object, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        text = _clean_name(value).lower().replace("_", " ")
        for code, name in METHOD_TYPE_NAMES.items():
            if text == name.lower():
                return code
        return default


def _is_result_selection_method_type(method_type: object) -> bool:
    return _method_type_code(method_type) == METHOD_TYPE_RESULT_SELECTION_CODE or (
        _clean_name(method_type).lower().replace("_", " ") == "result selection"
    )


def _call_member(obj, name: str, *args, **kwargs):
    member = getattr(obj, name)
    if callable(member):
        return member(*args, **kwargs)
    if args or kwargs:
        raise TypeError(f"{name} is not callable")
    return member


def _try_call_member(obj, name: str, call_shapes: list[tuple[tuple, dict]]):
    for args, kwargs in call_shapes:
        try:
            return _call_member(obj, name, *args, **kwargs)
        except Exception:
            continue
    raise AttributeError(name)



def _safe_read_json(path: Path) -> dict:
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(persisted_json_text(payload))


def _write_sidecar_json(path: Path, meta: Mapping[str, Any], *, in_place: bool = False) -> None:
    """Write a dataset sidecar through the shared core.

    Every sidecar writer lands the file stamped first, stripped of retired
    fields and with ``audit_log`` last (``arcrho_api.sidecar_core_contract``);
    the migration's hand-built metadata is no exception. A sidecar the import
    produces must pass the core check or is refused; *in_place* marks a patch
    of one field on a file already on disk (graph refresh, label backfill),
    which writes back whatever else that file held.
    """
    payload = finalize_sidecar(meta)
    _write_json(path, payload if in_place else validate_sidecar_core(payload))


def _csv_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "nan"} else text


def _write_csv_matrix(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows([[_csv_cell(cell) for cell in row] for row in rows])



DATASET_CACHE_DIR = "datasets"
DATASET_SIDECAR_DIR = "sidecars"
DEFAULT_CUMULATIVE = True
DEFAULT_CALENDAR = False


def _encode_filename_segment(value: object) -> str:
    """Match the frontend app-server reversible _%XX_ filename escaping rule."""
    replacements = {
        "\\": "_%5C_",
        "/": "_%2F_",
        ":": "_%3A_",
        "*": "_%2A_",
        "?": "_%3F_",
        '"': "_%22_",
        "<": "_%3C_",
        ">": "_%3E_",
        "|": "_%7C_",
    }
    out: list[str] = []
    for ch in str(value if value is not None else "").strip():
        if ch in replacements:
            out.append(replacements[ch])
        elif ord(ch) < 32:
            out.append(f"_%{ord(ch):02X}_")
        else:
            out.append(ch)
    return "".join(out)


def _decode_filename_segment(value: object) -> str:
    """Match the frontend app-server reversible _%XX_ filename decoding rule."""
    def repl(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return re.sub(r"_%([0-9A-Fa-f]{2})_", repl, str(value if value is not None else ""))


def _encode_rc_folder(rc_path: str) -> str:
    """Encode a reserving class path exactly like frontend config.sanitize_reserving_class_folder."""
    text = _encode_filename_segment(rc_path)
    text = re.sub(r"[. ]+$", lambda match: "^" * len(match.group(0)), text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "ReservingClass"


def _encode_name_part(name: str) -> str:
    """Encode a dataset / method name for use inside a filename."""
    text = _encode_filename_segment(name)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "Dataset"


def _mode_suffix(cumulative: bool = DEFAULT_CUMULATIVE, calendar: bool = DEFAULT_CALENDAR) -> str:
    cum_suffix = "cum" if cumulative else "inc"
    cal_suffix = "cal" if calendar else "dev"
    return f"@{cum_suffix}@{cal_suffix}"


def _dataset_cache_csv_file_name(
    name: str,
    origin_length: int,
    dev_length: int,
    *,
    cumulative: bool = DEFAULT_CUMULATIVE,
    calendar: bool = DEFAULT_CALENDAR,
) -> str:
    return f"{_encode_name_part(name)}@{origin_length}@{dev_length}{_mode_suffix(cumulative, calendar)}.csv"


def _vector_cache_csv_file_name(name: str, period_length: int) -> str:
    return f"{_encode_name_part(name)}@{period_length}.csv"


def _json_sidecar_name(name: str) -> str:
    return f"{_encode_name_part(name)}.json"


def _split_cache_variant_stem(stem: str) -> tuple[str, bool]:
    parts = str(stem or "").split("@")
    if (
        len(parts) >= 5
        and parts[-4].strip().isdigit()
        and parts[-3].strip().isdigit()
        and parts[-2].strip().lower() in {"cum", "inc", "cumulative", "incremental"}
        and parts[-1].strip().lower() in {"dev", "cal", "calendar"}
    ):
        return "@".join(parts[:-4]), True
    if len(parts) >= 2 and parts[-1].strip().isdigit():
        return "@".join(parts[:-1]), True
    return str(stem or ""), False


def _has_legacy_length_only_suffix(stem: str) -> bool:
    parts = str(stem or "").split("@")
    return len(parts) >= 3 and parts[-1].strip().isdigit() and parts[-2].strip().isdigit()


def _normalize_cached_dataset_name(value: object) -> str:
    text = _clean_name(value)
    stem, _is_cache_variant = _split_cache_variant_stem(text)
    return _normalize_import_name(_decode_filename_segment(stem.strip()))


def _add_cached_dataset_name(names: set[str], value: object) -> None:
    text = _normalize_cached_dataset_name(value)
    if text:
        names.add(text)


def _dataset_sidecar_path_for_cached_csv(csv_path: Path) -> Path:
    stem = csv_path.stem
    dataset_stem, is_cache_variant = _split_cache_variant_stem(stem)
    sidecar_dir = csv_path.parent.parent / DATASET_SIDECAR_DIR if csv_path.parent.name == DATASET_CACHE_DIR else csv_path.parent / DATASET_SIDECAR_DIR
    if is_cache_variant:
        return sidecar_dir / f"{dataset_stem}.json"
    return sidecar_dir / f"{stem}.json"


def _cached_dataset_names_from_file(filename: str) -> set[str]:
    path = Path(filename)
    stem = path.stem
    ext = path.suffix.lower()
    names: set[str] = set()
    if ext == ".csv":
        _add_cached_dataset_name(names, stem)
        return names
    if ext != ".json":
        return names
    for prefix in ("DFM@", BS_SR_FILE_PREFIX, BS_CRA_FILE_PREFIX):
        if stem.startswith(prefix):
            _add_cached_dataset_name(names, stem[len(prefix):])
            return names
    _add_cached_dataset_name(names, stem)
    return names
