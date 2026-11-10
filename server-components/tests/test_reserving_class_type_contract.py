"""The ResQ import and the Engine agree on which reserving-class paths resolve.

The import hands a class to the Engine only when the canonical rule in
``arcrho_reserving_class_type_contract`` says every level of its path is a
defined type, and the Engine's catalog resolves type names on the same key.
These tests pin that the two answer alike, path for path.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPOSITORY_ROOT / "server-components" / "src", REPOSITORY_ROOT / "python-api" / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from arcrho_engine.data_processing_rules import (  # noqa: E402
    ReservingClassConfigurationError,
    build_reserving_class_catalog,
    resolve_request_path,
)
from arcrho_reserving_class_type_contract import reserving_class_path_is_known  # noqa: E402

FAKE_PROJECT_DIR = Path(r"E:\Arco Server\projects\NJ_Annual_Prod_202605_Fake")
DIRECT_GROUP = "PRNJ - PA\\PA\\All States\\Direct Group"
SEGMENTS = ("BI Total", "CMPxCAT", "COL", "MP+PIP", "PD+UMPD")


def _engine_resolves(catalog, path: str) -> bool:
    try:
        resolve_request_path(catalog, path)
    except ReservingClassConfigurationError:
        return False
    return True


def _field_mapping(*fields: str) -> dict:
    return {"rows": [
        {"field_name": field, "significance": "Reserving Class", "level": level}
        for level, field in enumerate(fields, start=1)
    ]}


class ReservingClassTypeContractTests(unittest.TestCase):
    def assert_agree(self, field_mapping: dict, types_payload: dict, paths) -> None:
        catalog = build_reserving_class_catalog(field_mapping, types_payload)
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(
                    reserving_class_path_is_known(path, field_mapping, types_payload),
                    _engine_resolves(catalog, path),
                )

    def test_doubled_spaces_and_case_resolve_alike(self) -> None:
        field_mapping = _field_mapping("LOB", "SUBLINE")
        types_payload = {
            "columns": ["Name", "Level", "Formula", "Source"],
            "rows": [
                ["Auto  Liability", "1", "", "\"Auto  Liability\""],
                ["PP", "2", "", "\"PP\""],
                ["PP+CA", "2", "PP + CA", "\"PP\" + \"CA\""],
                ["CA", "2", "", "\"CA\""],
            ],
        }
        paths = [
            "Auto  Liability\\PP",
            "Auto Liability\\PP",
            " auto   LIABILITY \\pp+ca",
            "Auto Liability\\Total",
            "Motor\\PP",
            "Auto Liability",
            "Auto Liability\\PP\\Extra",
        ]
        self.assert_agree(field_mapping, types_payload, paths)
        self.assertTrue(reserving_class_path_is_known("Auto Liability\\PP", field_mapping, types_payload))
        self.assertFalse(reserving_class_path_is_known("Auto Liability\\Total", field_mapping, types_payload))

    @unittest.skipUnless(FAKE_PROJECT_DIR.is_dir(), "the fake project is only on the ArcRho server share")
    def test_the_fake_project_agrees_and_only_its_total_keeps_resqs_values(self) -> None:
        field_mapping = json.loads((FAKE_PROJECT_DIR / "field_mapping.json").read_text(encoding="utf-8"))
        types_payload = json.loads((FAKE_PROJECT_DIR / "reserving_class_types.json").read_text(encoding="utf-8"))
        names_by_level: dict[int, list[str]] = {}
        for name, level, *_rest in types_payload["rows"]:
            names_by_level.setdefault(int(level), []).append(name)
        # Every defined type at its own level, spelled with a doubled space as ResQ may.
        variants = [
            "\\".join(["PRNJ - PA", "PA", "All States", "Direct Group"][: level - 1] + [name.replace(" ", "  ")])
            for level, names in names_by_level.items()
            for name in names
        ]
        segments = ["\\".join((DIRECT_GROUP, segment)) for segment in SEGMENTS]
        total = "\\".join((DIRECT_GROUP, "Total"))
        self.assert_agree(field_mapping, types_payload, segments + [total] + variants)
        for path in segments:
            self.assertTrue(reserving_class_path_is_known(path, field_mapping, types_payload), path)
        self.assertFalse(reserving_class_path_is_known(total, field_mapping, types_payload))


if __name__ == "__main__":
    unittest.main()
