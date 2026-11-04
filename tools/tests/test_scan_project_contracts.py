from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
MODULE_PATH = REPO_ROOT / "tools" / "scan_project_contracts.py"
SPEC = importlib.util.spec_from_file_location("scan_project_contracts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
scan_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scan_tool
SPEC.loader.exec_module(scan_tool)

from arcrho_api import bornhuetter_ferguson_contract as bf_contract  # noqa: E402
from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.sidecar_core_contract import finalize_sidecar  # noqa: E402

PROJECT = "Fixture_Project"
CLASS = "Line_%5C_State"


def _sidecar(name: str, **overrides) -> dict:
    payload = {
        "dataset_name": name,
        "dataset_type": "Paid",
        "reserving_class": "Line\\State",
        "project_name": PROJECT,
        "source_kind": "input",
        "calculated": False,
        "data_format": "Vector",
        "method_type": "None",
        "status": 0,
        "number_format": "number",
        "decimal_places": 0,
        "show_subtotal": False,
        "period_length": 12,
        "stored_period_length": 12,
        "csv_file": f"{name}@12.csv",
        "created": "2026-11-04T00:00:00.000Z",
        "updated_at": "2026-11-04T00:00:00.000Z",
        "modified_by": "tester",
        "precedents": [],
        "dependents": [],
        "audit_log": [],
    }
    payload.update(overrides)
    for key in [key for key, value in overrides.items() if value is None]:
        payload.pop(key)
    return finalize_sidecar(payload)


def _bf_method() -> dict:
    method = bf_contract.normalize_bornhuetter_ferguson_method(
        {
            "json_format": bf_contract.BF_JSON_FORMAT,
            "details_tab": {"name": "BF Out", "output_type": "Ultimate", "origin_length": 12},
            "method_tab": {
                "latest_dataset": "Latest",
                "latest_values": [100.0],
                "dfm_dataset": "DFM",
                "dfm_ultimate_values": [200.0],
                "percentage_developed": [0.5],
                "prior_datasets": [{"name": "Prior", "values": [300.0], "weights": [1]}],
                "origin_labels": ["2025"],
                "selected_prior_values": [None],
                "new_ultimate": [None],
            },
        },
        require_complete=False,
    )
    selected, _ultimate = bf_contract._calculate_vectors(method["method_tab"])
    method["method_tab"]["selected_prior_values"] = selected
    method["method_tab"]["new_ultimate"] = [12345.0]  # disagrees with the snapshots
    return method


class ScanProjectContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.root = Path(self.temp.name)
        self.project = self.root / "projects" / PROJECT
        rc = self.project / "data" / CLASS
        for folder in ("datasets", "methods", "sidecars"):
            (rc / folder).mkdir(parents=True)

        def write_json(path: Path, payload: dict, text: str | None = None) -> None:
            path.write_text(text if text is not None else persisted_json_text(payload), encoding="utf-8")

        sidecars = rc / "sidecars"
        for name in ("Clean", "No Status", "Bad Layout"):
            (rc / "datasets" / f"{name}@12.csv").write_text("2025,1\n", encoding="utf-8")
        write_json(sidecars / "Clean.json", _sidecar("Clean"))
        write_json(sidecars / "No Status.json", _sidecar("No Status", status=None))
        write_json(sidecars / "Bad Layout.json", {}, json.dumps(_sidecar("Bad Layout")))
        write_json(sidecars / "No Csv.json", _sidecar("No Csv"))
        (rc / "datasets" / "BF Out@12.csv").write_text("2025,1\n", encoding="utf-8")
        write_json(
            sidecars / "BF Out.json",
            _sidecar("BF Out", method_name="BF Out", method_type="Bornhuetter Ferguson", calculated=False),
        )
        write_json(rc / "methods" / "BF@BF Out.json", _bf_method())
        write_json(
            rc / "methods" / "BF@Dead.json",
            {"json_format": "arcrho-bornhuetter-ferguson-method-by-tab-v2"},
        )
        write_json(rc / "methods" / "DFM@No Curves.json", {"json_format": "arcrho-dfm-v4"})
        (rc / ".index.json.lock").write_text("", encoding="utf-8")

        staging = self.project / "data" / ".arcrho-resq-import-staging" / "abc" / "data" / CLASS / "sidecars"
        staging.mkdir(parents=True)
        write_json(staging / "Clean.json", _sidecar("Clean"))
        stray = self.project / "data" / "tmp"
        stray.mkdir()
        (stray / "index.json").write_text("{}\n", encoding="utf-8")
        (self.project / "dataset_types.json.before-x.bak").write_text("{}", encoding="utf-8")
        (self.project / "users").mkdir()
        (self.project / "users" / "prefs.json.123.tmp").write_bytes(b"")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _findings(self) -> tuple[dict, dict]:
        data = scan_tool.scan_project(str(self.project), max_workers=4).as_dict(10)
        problems = {(row["kind"], row["problem"]): row["examples"] for row in data["problems"]}
        notices = {(row["kind"], row["problem"]): row["examples"] for row in data["notices"]}
        return problems, notices

    def test_each_problem_is_reported_once_with_its_file(self) -> None:
        problems, notices = self._findings()
        sidecars = f"data\\{CLASS}\\sidecars\\" if sys.platform == "win32" else f"data/{CLASS}/sidecars/"
        expected = {
            ("sidecar", "Sidecar is missing core fields: status"): [sidecars + "No Status.json"],
            ("sidecar", "text is not in the persisted JSON layout"): [sidecars + "Bad Layout.json"],
            ("sidecar", "csv_file names a CSV that does not exist"): [sidecars + "No Csv.json"],
            ("sidecar", "A method-output sidecar is always calculated."): [sidecars + "BF Out.json"],
        }
        for key, paths in expected.items():
            self.assertEqual(problems.get(key), paths, key)
        self.assertIn(("BF method", "BF new_ultimate does not match the embedded source snapshots."), problems)
        self.assertIn(("BF method", "dead format arcrho-bornhuetter-ferguson-method-by-tab-v2"), problems)
        self.assertEqual(len(problems[("leftover", "ResQ-import staging folder")]), 1)
        self.assertEqual(problems[("leftover", "class folder with no datasets, methods or sidecars")], [str(Path("data/tmp"))])
        self.assertEqual(problems[("leftover", "backup at the project root")], ["dataset_types.json.before-x.bak"])
        self.assertEqual(len(problems[("leftover", "lock file")]), 1)
        self.assertEqual(problems[("leftover", "empty file")], [str(Path("users/prefs.json.123.tmp"))])
        flagged = {path for paths in problems.values() for path in paths}
        self.assertNotIn(sidecars + "Clean.json", flagged)
        self.assertIn(("DFM method", "no curves_tab (filled on next save)"), notices)
        self.assertIn(("index", "missing (rebuilt on read)"), notices)

    def test_exit_code_reflects_problems_not_notices(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(scan_tool.main(["--root", str(self.root), "--project", PROJECT]), 1)
        clean = self.root / "projects" / "Clean_Project" / "data" / CLASS / "sidecars"
        clean.mkdir(parents=True)
        (clean.parent / "datasets").mkdir()
        (clean.parent / "datasets" / "Clean@12.csv").write_text("2025,1\n", encoding="utf-8")
        (clean / "Clean.json").write_text(persisted_json_text(_sidecar("Clean")), encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(scan_tool.main(["--root", str(self.root), "--project", "Clean_Project"]), 0)
        self.assertIn("Notices (self-healing): 1 findings", output.getvalue())


if __name__ == "__main__":
    unittest.main()
