from __future__ import annotations

import importlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


_TMP_ROOT = Path(__file__).resolve().parent / "logs" / "tmp"
_MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migration" / "resq_data_migration.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Named:
    def __init__(self, name: str):
        self.Name = name


class _DatasetType:
    Name = "Gross Loss - ad hoc"
    DataFormat = 0

    def __init__(self):
        self.Category = _Named("Loss")


class _Triangle:
    OriginLength = 12
    DevelopmentLength = 12
    OriginCount = 3
    User = "tester"
    Created = "2026-07-01T10:00:00"
    Modified = "2026-07-24T10:00:00"

    def __init__(self, name: str, method_type: int, base_value: float):
        self.Name = name
        self.MethodType = method_type
        self.Status = 2
        self.DatasetType = _DatasetType()
        self._base_value = base_value

    def OriginLabel(self, index: int):
        return str(2022 + index)

    def DevelopmentCount(self, index: int):
        return 4 - index

    def DevelopmentLabel(self, index: int):
        return f"{index * 12 - 7}m"

    def ValuesByIndex(self, origin_index: int, dev_index: int):
        return self._base_value + origin_index * 10 + dev_index


class _SettlementRateMethod:
    Notes = "Settlement rate migration note"
    LoessSpan = 5

    def __init__(self, output):
        self.Name = output.Name
        self.OutputTriangle = output
        self.PaidClaims = _Named("Gross Loss--Paid ")
        self.ClosedClaimNos = _Named("Claim Counts--CWP")
        self.UltimateClaimNos = _Named("C 92 - Current Qtr Selected")

    def SelectedProportionSettled(self, dev_index: int):
        return [0.35, 0.75, 1.0][dev_index - 1]

    def IsDefaultProportionSettled(self, dev_index: int):
        return dev_index != 2

    def SelectedAdjustment(self, origin_index: int, dev_index: int):
        return 0 if origin_index == 3 and dev_index == 1 else 1


class _CaseReserveMethod:
    Notes = "Case reserve migration note"
    LoessSpan = 9

    def __init__(self, output):
        self.Name = output.Name
        self.OutputTriangle = output
        self.ReportedClaimNos = _Named("Reported Claim Counts--Reported")
        self.ClosedClaimNos = _Named("Closed Claim Counts--Total Closed")
        self.IncurredClaims = _Named("Incurred Gross Loss--Incurred")
        self.PaidClaims = _Named("Paid Gross Loss--Paid ")

    def SelectedAvgInflation(self, dev_index: int):
        return [4, 3, 3][dev_index - 1]

    def UserAvgInflation(self, dev_index: int):
        return [0.1, 0.0, 0.0][dev_index - 1]

    def SelectedAvgCaseReserves(self, dev_index: int):
        return 0

    def UserAvgCaseReserves(self, dev_index: int):
        return 0.0


class _Collection:
    def __init__(self, items):
        self.items = {item.Name: item for item in items}

    def __iter__(self):
        return iter(self.items.values())

    def Item(self, name):
        return self.items[name]


class _ReservingClass:
    def __init__(self, sr_code: int, cra_code: int):
        self.sr_triangle = _Triangle(
            "Gross Loss--Paid - B&S Settlement Rate Adjustment",
            sr_code,
            100.0,
        )
        self.cra_triangle = _Triangle(
            "Gross Loss--Paid - B&S Case Reserve Adequacy Adjustment",
            cra_code,
            200.0,
        )
        self.sr = _SettlementRateMethod(self.sr_triangle)
        self.cra = _CaseReserveMethod(self.cra_triangle)
        self.triangles = _Collection([self.sr_triangle, self.cra_triangle])

    def Triangles(self):
        return self.triangles

    def GetBerquistShermanSR(self, name):
        if name != self.sr_triangle.Name:
            raise KeyError(name)
        return self.sr

    def GetBerquistShermanCRA(self, name):
        if name != self.cra_triangle.Name:
            raise KeyError(name)
        return self.cra

    def DFMMethods(self):
        return _Collection([])

    def Vectors(self):
        return _Collection([])

    def BFMethods(self):
        return _Collection([])


class ResqBerquistShermanMigrationTests(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.root = Path(self.tmp.name) / "Arco Server"
        self.project_dir = self.root / "projects" / "Demo"
        self.rc_dir = self.project_dir / "data" / "Auto_%5C_PP"
        for folder in ("datasets", "methods", "sidecars"):
            (self.rc_dir / folder).mkdir(parents=True, exist_ok=True)

        self.migration = _load_module(
            _MIGRATION_PATH,
            "resq_data_migration_bs_under_test",
        )
        self.migration.SERVER_ROOT = self.root
        self.migration.PROJECT_NAME = "Demo"
        self.migration.PROJECT_DATA_DIR = self.project_dir / "data"
        self.migration._configure_migration_modules()
        self.catalog = importlib.import_module("resq_migration.catalog")
        (self.project_dir / "dataset_types.json").write_text(
            json.dumps(
                {
                    "columns": [
                        "Formula",
                        "Generated",
                        "Name",
                        "Calculated",
                        "Data Format",
                        "Category",
                        "Source",
                    ],
                    "rows": [
                        ["", False, "Gross Loss - ad hoc", False, "Triangle", "Loss", ""],
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.reserving_class = _ReservingClass(
            self.migration.METHOD_TYPE_BS_SR_CODE,
            self.migration.METHOD_TYPE_BS_CRA_CODE,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _export(self, triangle):
        counts = {"bssr_written": 0, "bscra_written": 0}
        written, errors = self.migration.export_triangles_for_rc(
            self.reserving_class,
            r"Auto\PP",
            self.rc_dir,
            triangle_names=[triangle.Name],
            method_counts=counts,
            verbose=False,
        )
        self.assertEqual((written, errors), (1, 0))
        return counts

    def test_settlement_rate_export_writes_minimal_method_and_calculated_sidecar(self):
        counts = self._export(self.reserving_class.sr_triangle)
        self.assertEqual(counts, {"bssr_written": 1, "bscra_written": 0})

        method_path = (
            self.rc_dir
            / "methods"
            / "BSSR@Gross Loss--Paid - B&S Settlement Rate Adjustment.json"
        )
        payload = json.loads(method_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["json_format"], self.migration.BS_SR_JSON_FORMAT)
        self.assertNotIn("notes_tab", payload)
        self.assertNotIn("variant", payload)
        self.assertNotIn("data_format", payload["details_tab"])
        self.assertEqual(
            payload["details_tab"]["method_type"],
            "B&S Settlement Rate Adjustment",
        )
        method_tab = payload["method_tab"]
        self.assertEqual(method_tab["paid_claims"], "Gross Loss--Paid")
        self.assertEqual(method_tab["selected_proportion_settled"], [0.35, 0.75, 1.0])
        self.assertEqual(method_tab["selected_proportion_is_default"], [True, False, True])
        self.assertEqual(
            method_tab["selected_adjustment"],
            [
                ["pairs", "pairs", "pairs"],
                ["pairs", "pairs", None],
                ["unadjusted", None, None],
            ],
        )
        self.assertEqual(method_tab["loess_span"], 5)
        self.assertNotIn("adjusted_paid_claims", method_tab)

        sidecar = json.loads(
            (
                self.rc_dir
                / "sidecars"
                / "Gross Loss--Paid - B&S Settlement Rate Adjustment.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(sidecar["calculated"])
        self.assertEqual(sidecar["source_kind"], "berquist_sherman_sr")
        self.assertEqual(sidecar["method_type"], "B&S Settlement Rate Adjustment")
        self.assertNotIn("method_type_code", sidecar)
        self.assertEqual(sidecar["status"], 2)
        self.assertEqual(sidecar["notes"], "Settlement rate migration note")
        self.assertEqual(
            sidecar["precedents"],
            [
                {"dataset_name": "Gross Loss--Paid"},
                {"dataset_name": "Claim Counts--CWP"},
                {"dataset_name": "C 92 - Current Qtr Selected"},
            ],
        )

        self.catalog.refresh_sidecar_graphs_for_rc(self.rc_dir)
        refreshed = json.loads(
            (
                self.rc_dir
                / "sidecars"
                / "Gross Loss--Paid - B&S Settlement Rate Adjustment.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(refreshed["precedents"], sidecar["precedents"])

    def test_settlement_rate_export_backfills_only_missing_precedent_origin_labels(self):
        paid_path = self.rc_dir / "sidecars" / "Gross Loss--Paid.json"
        closed_path = self.rc_dir / "sidecars" / "Claim Counts--CWP.json"
        paid_path.write_text(
            json.dumps({"name": "Gross Loss--Paid", "data_format": "Triangle"}),
            encoding="utf-8",
        )
        closed_path.write_text(
            json.dumps(
                {
                    "name": "Claim Counts--CWP",
                    "data_format": "Triangle",
                    "origin_labels": ["existing"],
                }
            ),
            encoding="utf-8",
        )

        self._export(self.reserving_class.sr_triangle)

        paid = json.loads(paid_path.read_text(encoding="utf-8"))
        closed = json.loads(closed_path.read_text(encoding="utf-8"))
        self.assertEqual(paid["origin_labels"], ["2023", "2024", "2025"])
        self.assertEqual(closed["origin_labels"], ["existing"])

    def test_export_records_the_number_format_of_every_source_and_the_output(self):
        # A restyled source must be recorded from its sidecar, not from the
        # shared dataset-type preference, because that is what the method page
        # renders the input view with.
        sidecar_dir = self.rc_dir / "sidecars"
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        (sidecar_dir / "Gross Loss--Paid.json").write_text(
            json.dumps(
                {
                    "name": "Gross Loss--Paid",
                    "data_format": "Triangle",
                    "number_format": "0,000.00",
                    "decimal_places": 2,
                }
            ),
            encoding="utf-8",
        )

        self._export(self.reserving_class.sr_triangle)
        method_path = (
            self.rc_dir
            / "methods"
            / "BSSR@Gross Loss--Paid - B&S Settlement Rate Adjustment.json"
        )
        formats = json.loads(method_path.read_text(encoding="utf-8"))["method_tab"]["number_formats"]
        self.assertEqual(
            sorted(formats["sources"]),
            ["closed_claim_numbers", "paid_claims", "ultimate_claim_numbers"],
        )
        self.assertEqual(
            formats["sources"]["paid_claims"],
            {"number_format": "0,000.00", "decimal_places": 2},
        )
        # A source with no sidecar of its own falls back to the shared default.
        self.assertEqual(
            formats["sources"]["closed_claim_numbers"],
            {"number_format": "0,000", "decimal_places": 0},
        )
        self.assertEqual(formats["derived"], {"number_format": "0,000", "decimal_places": 0})

    def test_case_reserve_export_and_index_use_canonical_identity(self):
        counts = self._export(self.reserving_class.cra_triangle)
        self.assertEqual(counts, {"bssr_written": 0, "bscra_written": 1})

        method_path = (
            self.rc_dir
            / "methods"
            / "BSCRA@Gross Loss--Paid - B&S Case Reserve Adequacy Adjustment.json"
        )
        payload = json.loads(method_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["json_format"], self.migration.BS_CRA_JSON_FORMAT)
        self.assertNotIn("notes_tab", payload)
        self.assertNotIn("variant", payload)
        method_tab = payload["method_tab"]
        self.assertEqual(
            method_tab["inflation_selection"],
            ["user", "paid_all", "paid_all"],
        )
        self.assertEqual(method_tab["user_inflation"], [0.1, 0.0, 0.0])
        self.assertEqual(
            method_tab["average_case_reserve_selection"],
            ["latest", "latest", "latest"],
        )
        self.assertEqual(method_tab["loess_span"], 9)
        self.assertNotIn("avg_case_reserve_exclusions", method_tab)
        self.assertNotIn("avg_paid_claims_exclusions", method_tab)
        self.assertNotIn("adjusted_incurred_claims", method_tab)

        index_path = self.catalog.rebuild_dataset_instance_index(
            "Demo",
            r"Auto\PP",
            self.rc_dir,
        )
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["version"], self.migration.DATASET_INDEX_VERSION)
        item = next(
            row
            for row in index["files"]
            if row["name"] == self.reserving_class.cra_triangle.Name
        )
        self.assertEqual(item["method_type"], "B&S Case Reserve Adequacy Adjustment")
        self.assertEqual(item["source_kind"], "berquist_sherman_cra")
        self.assertEqual(item["data_format"], "Triangle")
        self.assertEqual(item["origin_length"], 12)
        self.assertEqual(item["development_length"], 12)
        self.assertNotIn("origin_labels", item)

    def test_nonannual_method_is_rejected_by_mvp_extractor(self):
        output = self.migration.export_triangle(self.reserving_class.sr_triangle)
        output["origin_length"] = 3

        with self.assertRaisesRegex(ValueError, "annual triangles only"):
            self.migration.export_berquist_sherman(
                self.reserving_class.sr,
                "sr",
                output,
            )


if __name__ == "__main__":
    unittest.main()
