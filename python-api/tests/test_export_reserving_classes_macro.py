from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


_MACROS_DIR = Path(__file__).resolve().parents[1] / "macros"
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
for path in (_SRC_DIR, _MACROS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api.resq_sync_queue import BridgeUnavailableError  # noqa: E402

_MACRO_PATH = _MACROS_DIR / "export_reserving_classes_to_resq.py"

CLASS_A = r"PRNJ - PA\PA\NY\Direct Group\BI Total"
CLASS_B = r"PRNJ - PA\PA\NY\Direct Group\MP+PIP"
CLASS_C = r"PRNJ - PA\PA\Penn+CT\Direct Group\BI Total"


def load_macro_module():
    spec = importlib.util.spec_from_file_location("export_reserving_classes_macro_under_test", _MACRO_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Progress:
    def update(self, **_kwargs):
        pass

    def close(self, **_kwargs):
        pass


class _UI:
    def __init__(self):
        self.messages = []
        self.project_instance = types.SimpleNamespace(context=lambda **_kwargs: {"projectName": "Demo"})

    def message_box(self, message, **kwargs):
        self.messages.append(message)
        return {"ok": True}

    def progress_bar(self, **_kwargs):
        return _Progress()


def _preview(*rows):
    return {"connection_name": "ResQ", "selection": {"names": ["T1"]}, "preview": list(rows)}


def _row(name, *, selected=True, supported=True, presence="both", newer=""):
    return {
        "id": name, "name": name, "selected": selected, "transfer_supported": supported,
        "presence": presence, "newer_side": newer,
    }


class ExportReservingClassesMacroTests(unittest.TestCase):
    def setUp(self):
        self.macro = load_macro_module()
        self.ui = _UI()
        self.tables = []
        self.calls = []
        self.table_answers = []
        self.bridge_answers = {}

    def _await_table(self, _ui, payload, **_kwargs):
        self.tables.append(payload)
        return self.table_answers.pop(0) if self.table_answers else {"accepted": True}

    def _bridge(self, **kwargs):
        self.calls.append(kwargs)
        answer = self.bridge_answers[(kwargs["phase"], kwargs["rc_path"])]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def _run(self):
        gateway = types.SimpleNamespace(read=lambda *_a, **_k: {CLASS_A.casefold(): 4, CLASS_B.casefold(): 2, CLASS_C.casefold(): 1})
        with patch.object(self.macro, "_load_class_list", return_value=[CLASS_A, CLASS_B, CLASS_C]), \
                patch("arcrho_api.ArcRhoUI", return_value=self.ui), \
                patch("arcrho_api.get_server_root", return_value="R"), \
                patch("arcrho_api.gateway.GatewayClient", return_value=gateway), \
                patch("arcrho_api.resq_sync_queue.require_live_bridge_workers", return_value=("w",)), \
                patch("arcrho_api.resq_sync_queue.run_bridge_phase", side_effect=self._bridge), \
                patch("arcrho_api.ui.await_review_table", side_effect=self._await_table):
            return self.macro.run_macro()

    def test_class_list_is_the_batch_import_list(self):
        import import_resq_reserving_classes as batch_import

        self.assertEqual(self.macro._load_class_list(), batch_import.RC_PATHS)

    def test_a_class_the_project_lacks_cannot_be_ticked(self):
        payload = self.macro.class_selection_payload(
            [{"path": CLASS_A, "exists": True, "dataset_count": 3}, {"path": CLASS_B, "exists": False, "dataset_count": None}],
            "Demo",
        )
        self.assertEqual([(row["selected"], row["disabled"]) for row in payload["rows"]], [(True, False), (False, True)])
        self.assertEqual(payload["rows"][1]["cells"]["datasets"], self.macro.NOT_IN_ARCRHO_LABEL)

    def test_each_class_exports_every_item_whatever_its_saved_selection(self):
        self.table_answers = [
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B]},
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B]},
        ]
        self.bridge_answers = {
            ("transfer_preview", CLASS_A): _preview(_row("T1", newer="resq"), _row("T2", selected=False), _row("X", supported=False)),
            ("transfer_preview", CLASS_B): _preview(_row("D 1", presence="arcrho")),
            ("export", CLASS_A): {"results": [{"name": "T1", "outcome": "exported"}]},
            ("export", CLASS_B): {"results": [{"name": "D 1", "outcome": "failed", "message": "refused"}]},
        }
        result = self._run()

        # No selection travels, so the whole class is pushed and the class's
        # saved single-class selection is left as it was.
        exports = [(call["rc_path"], call.get("selected_names")) for call in self.calls if call["phase"] == "export"]
        self.assertEqual(exports, [(CLASS_A, None), (CLASS_B, None)])
        plan_rows = {row["id"]: row["cells"] for row in self.tables[1]["rows"]}
        self.assertEqual(plan_rows[CLASS_A]["items"], "2")
        self.assertEqual(plan_rows[CLASS_A]["at_risk"]["text"], "1")
        self.assertEqual(plan_rows[CLASS_B]["created"], "1")
        outcomes = [row["cells"]["outcome"]["text"] for row in self.tables[2]["rows"]]
        self.assertEqual(outcomes, ["Exported", "Partly exported"])
        self.assertEqual(result["status"], "success")

    def test_a_failed_comparison_is_shown_and_never_exported(self):
        self.table_answers = [
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B]},
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B]},
        ]
        self.bridge_answers = {
            ("transfer_preview", CLASS_A): RuntimeError("class not in ResQ"),
            ("transfer_preview", CLASS_B): _preview(_row("T1")),
            ("export", CLASS_B): {"results": [{"name": "T1", "outcome": "exported"}]},
        }
        self._run()

        plan_rows = {row["id"]: row for row in self.tables[1]["rows"]}
        self.assertTrue(plan_rows[CLASS_A]["disabled"])
        self.assertEqual([call["rc_path"] for call in self.calls if call["phase"] == "export"], [CLASS_B])

    def test_a_silent_bridge_skips_the_remaining_classes(self):
        self.table_answers = [
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B, CLASS_C]},
            {"accepted": True, "selectedRowIds": [CLASS_A, CLASS_B, CLASS_C]},
        ]
        self.bridge_answers = {
            ("transfer_preview", CLASS_A): _preview(_row("T1")),
            ("transfer_preview", CLASS_B): _preview(_row("T1")),
            ("transfer_preview", CLASS_C): _preview(_row("T1")),
            ("export", CLASS_A): {"results": []},
            ("export", CLASS_B): BridgeUnavailableError("silent"),
        }
        result = self._run()

        self.assertEqual([call["rc_path"] for call in self.calls if call["phase"] == "export"], [CLASS_A, CLASS_B])
        self.assertIn("Skipped", result["results"][2]["error"])
        self.assertEqual(result["status"], "error")

    def test_cancelling_the_plan_writes_nothing(self):
        self.table_answers = [{"accepted": True, "selectedRowIds": [CLASS_A]}, {"accepted": False}]
        self.bridge_answers = {("transfer_preview", CLASS_A): _preview(_row("T1"))}
        result = self._run()

        self.assertEqual(result["status"], "cancelled")
        self.assertFalse([call for call in self.calls if call["phase"] == "export"])


if __name__ == "__main__":
    unittest.main()
