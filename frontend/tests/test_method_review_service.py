from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
for root in (REPO_ROOT / "frontend", REPO_ROOT / "python-api" / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from app_server.services import calculated_dataset_service
from app_server.services.method_review_service import refreshed_status, review_flag_collector
import test_dfm_service
import test_bornhuetter_ferguson_service
import test_cape_cod_service
import test_bootstrap_service
import test_berquist_sherman_service


class MethodReviewTests(unittest.TestCase):
    def test_content_comparison_ignores_only_audit_changes_and_csv_number_format(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            method_path = str(Path(folder) / "method.json")
            csv_path = str(Path(folder) / "output@3.csv")
            annual_path = str(Path(folder) / "output@12.csv")
            method = {
                "inputs": {"values": [10, 20], "formula": "Paid * 2"},
                "method_metadata": {"data_refreshed": "old", "last_modified": "old"},
                "audit_log": [{"user": "old"}],
            }
            Path(method_path).write_text(json.dumps(method), encoding="utf-8")
            Path(csv_path).write_text("10\n20\n", encoding="utf-8")
            Path(annual_path).write_text("30\n", encoding="utf-8")
            newer = copy.deepcopy(method)
            newer["method_metadata"].update(data_refreshed="new", last_modified="new")
            newer["audit_log"] = [{"user": "new"}]
            files = {method_path: json.dumps(newer), csv_path: "10.0\n20.00\n", annual_path: "30.0\n"}
            self.assertEqual(refreshed_status({"status": 0}, files), 0)
            self.assertEqual(refreshed_status({"status": 2}, files), 2)
            for changed_files in (
                {**files, annual_path: "31\n"},
                {**files, csv_path: "11\n20\n"},
                {**files, method_path: json.dumps({**newer, "inputs": {"values": [11, 20]}})},
                {**files, str(Path(folder) / "new@6.csv"): "30\n"},
            ):
                with self.subTest(files=changed_files):
                    self.assertEqual(refreshed_status({"status": 0}, changed_files), 2)

    def test_floating_point_noise_is_not_a_change_but_a_real_difference_is(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            method_path = str(Path(folder) / "method.json")
            csv_path = str(Path(folder) / "output@12.csv")
            Path(method_path).write_text(json.dumps({"values": [55690.69753793477, 0.0]}), encoding="utf-8")
            Path(csv_path).write_text("55690.69753793477\n", encoding="utf-8")
            noisy = {method_path: json.dumps({"values": [55690.69753793479, 0.0]}), csv_path: "55690.69753793479\n"}
            self.assertEqual(refreshed_status({"status": 0}, noisy), 0)
            moved = {**noisy, method_path: json.dumps({"values": [55690.70753793479, 0.0]})}
            self.assertEqual(refreshed_status({"status": 0}, moved), 2)

    def test_walk_collects_only_the_outputs_that_turn_from_ok_to_needs_review(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
            csv_path = str(Path(folder) / "output@12.csv")
            Path(csv_path).write_text("10\n", encoding="utf-8")
            same = {csv_path: "10.0\n"}
            changed = {csv_path: "11\n"}
            # Without a walk the comparison records nothing and still answers.
            self.assertEqual(refreshed_status({"status": 0, "dataset_name": "Loose"}, changed), 2)
            with review_flag_collector() as flagged:
                self.assertEqual(refreshed_status({"status": 0, "dataset_name": "Green Same"}, same), 0)
                self.assertEqual(refreshed_status({"status": 2, "dataset_name": "Already Yellow"}, changed), 2)
                self.assertEqual(refreshed_status({"status": 0, "dataset_name": "C 91"}, changed), 2)
                # A nested walk shares the outer list, and a repeat is one entry.
                with review_flag_collector() as nested:
                    self.assertIs(nested, flagged)
                    refreshed_status({"status": 0, "dataset_name": "c 91"}, changed)
                    refreshed_status({"status": 0, "dataset_name": "D 92"}, changed)
                self.assertEqual(flagged, ["C 91", "D 92"])
            # The walk wrapper hands the collected names back on its result.
            def fake_walk(*_args, **_kwargs):
                refreshed_status({"status": 0, "dataset_name": "E1 92"}, changed)
                return {"ok": True}
            with mock.patch.object(calculated_dataset_service, "_recalculate_dependents_impl", fake_walk):
                result = calculated_dataset_service.recalculate_dependents("Project", "Class", "Paid")
            self.assertEqual(result["review_flagged"], ["E1 92"])

    def test_all_method_publishers_preserve_green_and_existing_yellow(self):
        cases = (
            (test_dfm_service.DfmServiceTests, test_dfm_service.dfm_service, "Development Output", "Paid"),
            (test_bornhuetter_ferguson_service.BornhuetterFergusonServiceTests,
             test_bornhuetter_ferguson_service.bornhuetter_ferguson_service, "BF Method", "Paid"),
            (test_cape_cod_service.CapeCodServiceTests, test_cape_cod_service.cape_cod_service, "CC Method", "Paid"),
            (test_bootstrap_service.BootstrapServiceTests, test_bootstrap_service.bootstrap_service,
             test_bootstrap_service.BOOTSTRAP_NAME, test_bootstrap_service.DFM_OUTPUT_DATASET),
            (test_berquist_sherman_service.BerquistShermanRefreshTests,
             test_berquist_sherman_service.berquist_sherman_service, test_berquist_sherman_service.OUTPUT, "Ultimate Counts"),
        )
        for fixture_type, service, output, source in cases:
            with self.subTest(method=service.__name__):
                fixture = fixture_type()
                fixture.setUp()
                try:
                    if service is test_dfm_service.dfm_service:
                        fixture.write_method_pair()
                        fixture.write_source("Paid", "100,150\n200,\n", data_format="Triangle",
                                             dependents=[output])
                    elif service is test_bootstrap_service.bootstrap_service:
                        fixture.save()
                        source_path = fixture.sidecars / f"{source}.json"
                        source_sidecar = json.loads(source_path.read_text(encoding="utf-8"))
                        source_sidecar["dependents"] = [output]
                        source_path.write_text(json.dumps(source_sidecar), encoding="utf-8")
                    elif service is test_berquist_sherman_service.berquist_sherman_service:
                        fixture.write_workspace(saved_ultimate=[20, 20, 20], current_ultimate=[20, 20, 20])
                    else:
                        fixture.write_method_pair()
                        fixture.write_all_sources()
                    sidecar_path = fixture.sidecars / f"{output}.json"
                    with mock.patch("app_server.services.calculated_dataset_service.recalculate_dependents",
                                    return_value={"ok": True, "updated": [], "skipped": []}), \
                         mock.patch("app_server.services.dataset_instance_index_service.rebuild_index"):
                        first = service.refresh_dependents("Project", "Class", [source])
                        self.assertTrue(first["ok"], first)
                        for status in (0, 2):
                            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                            sidecar["status"] = status
                            sidecar["updated_at"] = "2000-01-01T00:00:00.000Z"
                            sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
                            refreshed = service.refresh_dependents("Project", "Class", [source])
                            self.assertTrue(refreshed["ok"], refreshed)
                            self.assertTrue(refreshed["updated"], refreshed)
                            persisted = json.loads(sidecar_path.read_text(encoding="utf-8"))
                            self.assertEqual(persisted["status"], status)
                            self.assertNotEqual(persisted["updated_at"], sidecar["updated_at"])
                            self.assertTrue(persisted["modified_by"])
                finally:
                    fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
