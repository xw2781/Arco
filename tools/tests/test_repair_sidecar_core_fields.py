"""The one-off repair that fills the core fields old ResQ imports left out of a sidecar."""

from __future__ import annotations

import importlib.util
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
MODULE_PATH = REPO_ROOT / "tools" / "repair_sidecar_core_fields.py"
SPEC = importlib.util.spec_from_file_location("repair_sidecar_core_fields", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
repair_tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = repair_tool
SPEC.loader.exec_module(repair_tool)

from arcrho_api.io import persisted_json_text  # noqa: E402
from arcrho_api.sidecar_core_contract import finalize_sidecar, validate_sidecar_core  # noqa: E402

PROJECT = "Fixture_Project"


def _sidecar(name: str, **overrides) -> dict:
    payload = {
        "dataset_name": name,
        "dataset_type": name,
        "reserving_class": "Line\\State",
        "project_name": PROJECT,
        "source_kind": "input",
        "calculated": False,
        "method_type": "None",
        "data_format": "Vector",
        "number_format": "0,000",
        "decimal_places": 0,
        "show_subtotal": True,
        "period_length": 12,
        "stored_period_length": 12,
        "csv_file": f"{name}@12.csv",
        "created": "2026-09-05T00:00:00.000Z",
        "modified_by": "Moore, Kelly",
        "updated_at": "2026-09-05T00:00:00.000Z",
        "status": 0,
        "precedents": [],
        "dependents": [],
        "audit_log": [],
    }
    payload.update(overrides)
    for key in [key for key, value in overrides.items() if value is None]:
        payload.pop(key)
    return finalize_sidecar(payload)


class RepairSidecarCoreFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sidecars = self.root / "projects" / PROJECT / "data" / "Line_%5C_State" / "sidecars"
        sidecars.mkdir(parents=True)
        self.files: dict[str, Path] = {}
        for payload in (
            _sidecar("Clean"),
            _sidecar("No Status", status=None),
            _sidecar("No Type Or Status", status=None, method_type=None),
            _sidecar("BS Out", method_name="BS Out", method_type="B&S Case Reserve Adequacy Adjustment"),
        ):
            path = sidecars / f"{payload['dataset_name']}.json"
            path.write_text(persisted_json_text(payload), encoding="utf-8")
            self.files[payload["dataset_name"]] = path

    def run_tool(self, *extra: str) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            code = repair_tool.main(["--root", str(self.root), "--project", PROJECT, *extra])
        self.assertEqual(code, 0)
        return out.getvalue()

    def read(self, name: str) -> dict:
        return json.loads(self.files[name].read_text(encoding="utf-8"))

    def test_a_dry_run_writes_nothing(self) -> None:
        before = {name: path.read_text(encoding="utf-8") for name, path in self.files.items()}
        report = self.run_tool()

        self.assertIn("Sidecars repaired: 3", report)
        self.assertEqual(before, {name: path.read_text(encoding="utf-8") for name, path in self.files.items()})

    def test_missing_fields_take_the_reader_defaults_in_the_builder_slots(self) -> None:
        clean = self.files["Clean"].read_text(encoding="utf-8")
        self.run_tool("--apply")

        for name in ("No Status", "No Type Or Status", "BS Out"):
            validate_sidecar_core(self.read(name))
        no_status = self.read("No Status")
        self.assertEqual(no_status["status"], 0)
        keys = list(no_status)
        self.assertEqual(keys[keys.index("updated_at") + 1], "status")
        no_type = self.read("No Type Or Status")
        self.assertEqual(no_type["method_type"], "")
        keys = list(no_type)
        self.assertEqual(keys[keys.index("data_format") - 1], "method_type")
        self.assertIs(self.read("BS Out")["calculated"], True)
        # Nothing else moves: no timestamp, no audit entry, no other field.
        self.assertEqual(no_status["updated_at"], "2026-09-05T00:00:00.000Z")
        self.assertEqual(no_status["audit_log"], [])
        self.assertEqual(self.files["Clean"].read_text(encoding="utf-8"), clean)

    def test_a_second_run_changes_nothing(self) -> None:
        self.run_tool("--apply")
        self.assertIn("Sidecars repaired: 0", self.run_tool("--apply"))


if __name__ == "__main__":
    unittest.main()
