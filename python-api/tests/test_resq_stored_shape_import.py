"""The ResQ import copies each dataset at the shape ResQ stores it at.

ResQ keeps a displayed length and a stored length per dataset. A generated
dataset in a monthly project is stored monthly however coarsely it is shown,
and a hand-entered one is stored at the shape it was typed at. The import reads
the stored lengths (``StoredOriginLength`` / ``StoredDevelopmentLength`` on a
triangle, ``StoredPeriodLength`` on a vector), copies a hand-entered dataset's
values at that shape, and stamps every sidecar it writes with both shapes.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


_PYTHON_API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PYTHON_API / "src"))
sys.path.insert(0, str(_PYTHON_API / "migration"))

_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
_MIGRATION_PATH = _PYTHON_API / "migration" / "resq_data_migration.py"


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("resq_data_migration_stored_shape_under_test", _MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load resq_data_migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset_type(name: str, data_format: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        Name=name,
        Category=types.SimpleNamespace(Name="Loss"),
        DataFormat=data_format,
    )


class _ShapedTriangle:
    """A triangle ResQ displays yearly but stores monthly.

    Shown at 12/12 it has two rows; shown at 1/1 it has twenty-four, each
    holding its own month's figure, the way ResQ answers once the displayed
    lengths are set back to the stored ones.
    """

    Name = "Case Reserves"
    MethodType = 0
    StoredOriginLength = 1
    StoredDevelopmentLength = 1
    User = "importer"
    Created = "2025-01-01T00:00:00Z"
    Modified = "2026-01-02T00:00:00Z"
    Notes = ""
    Status = 0

    def __init__(self, *, refuse_switch: bool = False) -> None:
        self.DatasetType = _dataset_type("Case Reserves", 0)
        self._origin_length = 12
        self._development_length = 12
        self._refuse_switch = refuse_switch
        self.length_sets: list[tuple[str, int]] = []

    @property
    def OriginLength(self) -> int:
        return self._origin_length

    @OriginLength.setter
    def OriginLength(self, value: int) -> None:
        if self._refuse_switch:
            raise RuntimeError("ResQ refused the origin length")
        self.length_sets.append(("OriginLength", int(value)))
        self._origin_length = int(value)

    @property
    def DevelopmentLength(self) -> int:
        return self._development_length

    @DevelopmentLength.setter
    def DevelopmentLength(self, value: int) -> None:
        if self._refuse_switch:
            raise RuntimeError("ResQ refused the development length")
        self.length_sets.append(("DevelopmentLength", int(value)))
        self._development_length = int(value)

    @property
    def OriginCount(self) -> int:
        return 2 if self._origin_length == 12 else 24

    def OriginLabel(self, origin_index: int) -> str:
        if self._origin_length == 12:
            return str(2023 + origin_index)
        year = 2024 + (origin_index - 1) // 12
        month = (origin_index - 1) % 12 + 1
        return f"{year}-{month:02d}"

    def DevelopmentLabel(self, development_index: int) -> str:
        return str(development_index * self._development_length)

    def DevelopmentCount(self, *args, **kwargs) -> int:
        del args, kwargs
        return 1

    def ValuesByIndex(self, origin_index: int, development_index: int) -> float:
        if self._origin_length == 12:
            return origin_index * 1000 + development_index
        return float(origin_index)


class _ShapedVector:
    """A vector ResQ displays yearly but stores monthly."""

    Name = "Case Premium"
    MethodType = 0
    StoredPeriodLength = 1
    User = "importer"
    Created = "2025-01-01T00:00:00Z"
    Modified = "2026-01-02T00:00:00Z"
    Notes = ""
    Formula = ""
    Status = 0

    def __init__(self) -> None:
        self.DatasetType = _dataset_type("Case Premium", 1)
        self._period_length = 12
        self.length_sets: list[tuple[str, int]] = []

    @property
    def PeriodLength(self) -> int:
        return self._period_length

    @PeriodLength.setter
    def PeriodLength(self, value: int) -> None:
        self.length_sets.append(("PeriodLength", int(value)))
        self._period_length = int(value)

    @property
    def OriginCount(self) -> int:
        return 2 if self._period_length == 12 else 24

    def OriginLabel(self, origin_index: int) -> str:
        if self._period_length == 12:
            return str(2023 + origin_index)
        year = 2024 + (origin_index - 1) // 12
        month = (origin_index - 1) % 12 + 1
        return f"{year}-{month:02d}"

    def ValuesByIndex(self, origin_index: int) -> float:
        if self._period_length == 12:
            return origin_index * 1000
        return float(origin_index)


class ResQStoredShapeExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractors = importlib.import_module("resq_migration.extractors")

    def test_stored_lengths_come_from_resq_and_fall_back_to_the_displayed_ones(self) -> None:
        triangle = _ShapedTriangle()
        self.assertEqual(
            self.extractors.resq_stored_lengths(
                triangle, is_vector=False, origin_length=12, development_length=12
            ),
            (1, 1),
        )
        # A displayed length that is not a multiple of the stored one, and a
        # dataset that answers nothing, both read as the displayed shape.
        triangle.StoredOriginLength = 5
        self.assertEqual(
            self.extractors.resq_stored_lengths(
                triangle, is_vector=False, origin_length=12, development_length=12
            ),
            (12, 1),
        )
        silent = types.SimpleNamespace(PeriodLength=12)
        self.assertEqual(
            self.extractors.resq_stored_lengths(silent, is_vector=True, origin_length=12),
            (12, 12),
        )

    def test_a_triangle_is_read_at_the_stored_shape_on_request_and_put_back(self) -> None:
        triangle = _ShapedTriangle()

        payload = self.extractors.export_triangle(triangle, at_stored_shape=True)

        self.assertEqual((payload["origin_length"], payload["development_length"]), (12, 12))
        self.assertEqual(
            (payload["stored_origin_length"], payload["stored_development_length"]), (1, 1)
        )
        self.assertEqual(len(payload["values"]), 24)
        self.assertEqual(payload["values"][0], [1.0])
        self.assertEqual(payload["origin_labels"][:2], ["2024-01", "2024-02"])
        # The displayed lengths were switched to the stored ones for the read
        # and restored afterwards, so ResQ is left as it was found.
        self.assertEqual(
            triangle.length_sets,
            [("OriginLength", 1), ("DevelopmentLength", 1), ("DevelopmentLength", 12), ("OriginLength", 12)],
        )
        self.assertEqual((triangle.OriginLength, triangle.DevelopmentLength), (12, 12))

    def test_a_triangle_is_read_at_the_displayed_shape_by_default(self) -> None:
        triangle = _ShapedTriangle()

        payload = self.extractors.export_triangle(triangle)

        self.assertEqual(len(payload["values"]), 2)
        self.assertEqual(payload["values"][0], [1001])
        # The values were read at the displayed shape, and the payload says so
        # even though ResQ stores the data finer.
        self.assertEqual(
            (payload["stored_origin_length"], payload["stored_development_length"]), (12, 12)
        )
        self.assertEqual(triangle.length_sets, [])

    def test_a_refused_switch_reads_the_displayed_shape_and_says_so(self) -> None:
        triangle = _ShapedTriangle(refuse_switch=True)

        payload = self.extractors.export_triangle(triangle, at_stored_shape=True)

        self.assertEqual(len(payload["values"]), 2)
        self.assertEqual(
            (payload["stored_origin_length"], payload["stored_development_length"]), (12, 12)
        )
        self.assertEqual((triangle.OriginLength, triangle.DevelopmentLength), (12, 12))

    def test_a_vector_is_read_at_the_stored_period_on_request_and_put_back(self) -> None:
        vector = _ShapedVector()

        payload = self.extractors.export_vector(vector, at_stored_shape=True)

        self.assertEqual(payload["origin_length"], 12)
        self.assertEqual(payload["stored_period_length"], 1)
        self.assertEqual(len(payload["values"]), 24)
        self.assertEqual(payload["values"][23], [24.0])
        self.assertEqual(vector.length_sets, [("PeriodLength", 1), ("PeriodLength", 12)])
        self.assertEqual(vector.PeriodLength, 12)

        by_default = self.extractors.export_vector(_ShapedVector())
        self.assertEqual(len(by_default["values"]), 2)
        self.assertEqual(by_default["stored_period_length"], 12)


class ResQStoredShapeWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.tmp.name) / "Arco Server"
        self.project_dir = self.root / "projects" / "Demo"
        self.rc_dir = self.project_dir / "data" / "Auto_%5C_PP"
        self.datasets_dir = self.rc_dir / "datasets"
        self.sidecars_dir = self.rc_dir / "sidecars"
        self.datasets_dir.mkdir(parents=True)
        (self.rc_dir / "methods").mkdir()
        self.sidecars_dir.mkdir()

        self.module = _load_migration_module()
        self.module.SERVER_ROOT = self.root
        self.module.PROJECT_NAME = "Demo"
        self.module.PROJECT_DATA_DIR = self.project_dir / "data"

        catalog = importlib.import_module("resq_migration.catalog")
        catalog.configure_catalog(
            server_root=self.root,
            project_name="Demo",
            rs_json_format=self.module.RS_JSON_FORMAT,
            method_data_dir=self.module.METHOD_DATA_DIR,
        )
        self.extractors = importlib.import_module("resq_migration.extractors")
        self.extractors.configure_extractors(
            project_name="Demo",
            rs_json_format=self.module.RS_JSON_FORMAT,
            method_data_dir=self.module.METHOD_DATA_DIR,
        )
        (self.project_dir / "dataset_types.json").write_text(json.dumps({
            "columns": ["Formula", "Generated", "Name", "Calculated", "Data Format", "Category", "Source"],
            "rows": [
                ["", True, "Paid Loss", False, "Triangle", "Loss", "PaidLoss"],
                ["", True, "Generated Premium", False, "Vector", "Premium", "Prem"],
                ["", False, "Case Reserves", False, "Triangle", "Loss", ""],
                ["", False, "Case Premium", False, "Vector", "Premium", ""],
            ],
        }), encoding="utf-8")
        self.provenance = {
            "config_hash": "sha256:deadbeef",
            "algorithm_version": "arcrho-data-processing-v1",
            "rules_format": "arcrho-data-processing-rules-v1",
            "rules_revision": 4,
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _sidecar(self, name: str) -> dict:
        return json.loads((self.sidecars_dir / f"{name}.json").read_text(encoding="utf-8"))

    def test_a_hand_entered_triangle_is_stored_at_the_shape_it_was_read_at(self) -> None:
        payload = self.extractors.export_triangle(_ShapedTriangle(), at_stored_shape=True)

        csv_path = self.extractors.write_triangle_export(payload, r"Auto\PP", self.rc_dir)

        self.assertEqual(csv_path.name, "Case Reserves@1@1@cum@dev.csv")
        self.assertEqual(len(csv_path.read_text(encoding="utf-8").strip().splitlines()), 24)
        sidecar = self._sidecar("Case Reserves")
        self.assertEqual(sidecar["source_kind"], "input")
        self.assertEqual(sidecar["csv_file"], "Case Reserves@1@1@cum@dev.csv")
        # Display shape: what ResQ showed. Stored shape: what the CSV holds.
        self.assertEqual((sidecar["origin_length"], sidecar["development_length"]), (12, 12))
        self.assertEqual(
            (sidecar["stored_origin_length"], sidecar["stored_development_length"]), (1, 1)
        )
        self.assertEqual(len(sidecar["origin_labels"]), 24)

    def test_a_hand_entered_vector_is_stored_monthly_with_its_yearly_copy_summed(self) -> None:
        payload = self.extractors.export_vector(_ShapedVector(), at_stored_shape=True)

        csv_path = self.extractors.write_vector_export(payload, r"Auto\PP", self.rc_dir)

        self.assertEqual(csv_path.name, "Case Premium@1.csv")
        sidecar = self._sidecar("Case Premium")
        self.assertEqual(sidecar["source_kind"], "input")
        self.assertEqual(sidecar["csv_file"], "Case Premium@1.csv")
        self.assertEqual(sidecar["period_length"], 12)
        self.assertEqual(sidecar["stored_period_length"], 1)
        # The yearly copy the display period is served from is summed from the
        # monthly figures, not from a period the values were never read at.
        yearly = (self.datasets_dir / "Case Premium@12.csv").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual([float(line) for line in yearly], [78.0, 222.0])

    def test_a_generated_dataset_carries_resq_stored_lengths(self) -> None:
        triangle = types.SimpleNamespace(
            Name="Paid Loss",
            DatasetType=_dataset_type("Paid Loss", 0),
            OriginLength=12,
            DevelopmentLength=12,
            StoredOriginLength=1,
            StoredDevelopmentLength=1,
            User="importer",
            Created="",
            Modified="",
        )
        payload = self.module._engine_generated_metadata_payload(
            triangle, name="Paid Loss", dataset_type="Paid Loss", is_vector=False, strict=True
        )
        self.assertEqual((payload["origin_length"], payload["development_length"]), (12, 12))
        self.assertEqual(
            (payload["stored_origin_length"], payload["stored_development_length"]), (1, 1)
        )

        csv_name = "Paid Loss@12@12@cum@dev.csv"
        csv_path = self.datasets_dir / csv_name
        csv_path.write_text("1,2\n3,4\n", encoding="utf-8")
        self.extractors.write_engine_generated_export(
            payload,
            r"Auto\PP",
            self.rc_dir,
            is_vector=False,
            provenance=self.provenance,
            csv_name=csv_name,
            csv_path=csv_path,
        )
        sidecar = self._sidecar("Paid Loss")
        self.assertEqual(sidecar["source_kind"], "engine")
        self.assertEqual((sidecar["origin_length"], sidecar["development_length"]), (12, 12))
        self.assertEqual(
            (sidecar["stored_origin_length"], sidecar["stored_development_length"]), (1, 1)
        )

    def test_a_generated_vector_carries_resq_stored_period(self) -> None:
        vector = types.SimpleNamespace(
            Name="Generated Premium",
            DatasetType=_dataset_type("Generated Premium", 1),
            PeriodLength=12,
            StoredPeriodLength=1,
            User="importer",
            Created="",
            Modified="",
        )
        payload = self.module._engine_generated_metadata_payload(
            vector, name="Generated Premium", dataset_type="Generated Premium", is_vector=True
        )
        self.assertEqual(payload["period_length"], 12)
        self.assertEqual(payload["stored_period_length"], 1)

        csv_name = "Generated Premium@12.csv"
        csv_path = self.datasets_dir / csv_name
        csv_path.write_text("10\n20\n", encoding="utf-8")
        self.extractors.write_engine_generated_export(
            payload,
            r"Auto\PP",
            self.rc_dir,
            is_vector=True,
            provenance=self.provenance,
            csv_name=csv_name,
            csv_path=csv_path,
        )
        sidecar = self._sidecar("Generated Premium")
        self.assertEqual(sidecar["period_length"], 12)
        self.assertEqual(sidecar["stored_period_length"], 1)

    def test_a_generated_dataset_resq_stores_at_the_displayed_shape_keeps_it(self) -> None:
        triangle = types.SimpleNamespace(
            Name="Paid Loss",
            DatasetType=_dataset_type("Paid Loss", 0),
            OriginLength=12,
            DevelopmentLength=12,
            StoredOriginLength=12,
            StoredDevelopmentLength=12,
            User="importer",
            Created="",
            Modified="",
        )
        payload = self.module._engine_generated_metadata_payload(
            triangle, name="Paid Loss", dataset_type="Paid Loss", is_vector=False
        )
        self.assertEqual(
            (payload["stored_origin_length"], payload["stored_development_length"]), (12, 12)
        )


if __name__ == "__main__":
    unittest.main()
