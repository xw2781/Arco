from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import arcrho_api.config as api_config
from arcrho_api.agent import main as agent_main
from arcrho_api import (
    ArcRhoApiError,
    ArcRhoClient,
    ArcRhoUI,
    DfmDataError,
    InvalidArcRhoServerError,
    ReadOnlyError,
    get_config_path,
    get_server_root,
    reload_project_instance_dataset_table,
    reload_server_root,
    set_server_root,
)
from arcrho_api.paths import dfm_filename, parse_dfm_filename
from arcrho_api.dataset_index_contract import (
    DATASET_INDEX_VERSION,
    FORBIDDEN_INDEX_ROW_FIELDS,
    INDEX_ROW_FIELDS,
)
from arcrho_api.migration import ArcRhoSession


_LOG_DIR = Path(__file__).resolve().parent / "logs"
_TMP_ROOT = _LOG_DIR / "tmp"
_LOG_PATH = _LOG_DIR / f"{Path(__file__).stem}_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.log"
_LOG_READY = False


def _prune_logs() -> None:
    logs = sorted(
        _LOG_DIR.glob(f"{Path(__file__).stem}_*.log"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0,
        reverse=True,
    )
    for old_log in logs[3:]:
        try:
            old_log.unlink()
        except OSError:
            pass


def test_log(message: str) -> None:
    global _LOG_READY
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        if not _LOG_READY:
            _prune_logs()
            _LOG_READY = True
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with _LOG_PATH.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{timestamp} | {message}\n")
    except OSError:
        pass


def sample_payload() -> dict:
    return {
        "json_format": "arcrho-dfm-method-by-tab-v1",
        "details_tab": {
            "name": "Paid DFM",
            "output_type": "Paid Ultimate",
            "input_triangle": "Paid Loss",
            "origin_length": 12,
            "development_length": 12,
            "decimal_places": 4,
        },
        "data_tab": {
            "origin_labels": ["2019", "2020", "2021"],
            "development_labels": ["12m", "24m", "36m"],
            "input data triangle csv path": "",
        },
        "ratios_tab": {
            "ratio_triangle": {
                "origin_labels": ["2019", "2020", "2021"],
                "development_labels": ["(1) 12-24", "(2) 24-36"],
                "ratio_values": [[1.1, 1.2], [1.5, 1.1], [0.9, 1.4]],
                "excluded": [[0, 0], [0, 0], [0, 0]],
            },
            "average_formulas": {
                "label": ["Volume - all", "Simple - 3", "User Entry"],
                "custom_average_formula_settings": {
                    "average_type": ["custom", "custom", "user_entry"],
                    "base": ["volume", "simple", ""],
                    "periods": ["all", 3, "all"],
                    "exclude": [0, 0, 0],
                },
                "selected": [[0, 0], [0, 0], [0, 0]],
                "values": [[1.0, 1.0], [1.2, 1.3], [None, None]],
            },
        },
        "results_tab": {
            "ratio_basis_dataset": "",
            "ultimate_ratio_decimal_places": 2,
            "ultimate vector csv path": "",
        },
        "method_metadata": {"last_modified": "2026-01-01T00:00:00"},
        "unknown section": {"preserve": True},
    }


class ArcRhoApiTests(unittest.TestCase):
    def setUp(self) -> None:
        test_log(f"START {self.id()}")
        test_log(f"SETUP_STEP ensure_tmp_root={_TMP_ROOT}")
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        test_log("SETUP_STEP create_temporary_directory")
        self.tmp = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        test_log(f"SETUP_STEP temporary_directory_created={self.tmp.name}")
        self.root = Path(self.tmp.name) / "ArcRho Server"
        self.project_dir = self.root / "projects" / "Demo"
        self.data_dir = self.project_dir / "data"
        self.rc_data_dir = self.data_dir / "Auto_%5C_PP"
        self.datasets_dir = self.rc_data_dir / "datasets"
        self.methods_dir = self.rc_data_dir / "methods"
        self.sidecars_dir = self.rc_data_dir / "sidecars"
        test_log(f"SETUP_STEP mkdir_datasets={self.datasets_dir}")
        self.datasets_dir.mkdir(parents=True)
        test_log(f"SETUP_STEP mkdir_methods={self.methods_dir}")
        self.methods_dir.mkdir(parents=True)
        test_log(f"SETUP_STEP mkdir_sidecars={self.sidecars_dir}")
        self.sidecars_dir.mkdir(parents=True)
        self.method_path = self.methods_dir / dfm_filename("Paid DFM")
        self.sidecar_path = self.sidecars_dir / "Paid DFM.json"
        self.sidecar_path.write_text(json.dumps({
            "dataset_name": "Paid DFM",
            "method_name": "Paid DFM",
            "method_type": "DFM",
            "source_kind": "dfm",
            "notes": "original",
        }), encoding="utf-8")
        self.input_csv = self.datasets_dir / "input.csv"
        test_log(f"SETUP_STEP write_input_csv={self.input_csv}")
        self.input_csv.write_text("10,20,30\n11,22,\n12,,\n", encoding="utf-8")
        (self.sidecars_dir / "Paid Loss.json").write_text(json.dumps({
            "dataset_name": "Paid Loss",
            "data_format": "Triangle",
            "csv_file": self.input_csv.name,
            "origin_labels": ["2019", "2020", "2021"],
            "development_labels": ["12m", "24m", "36m"],
            "number_format": "#,##0",
            "decimal_places": 0,
            "dependents": [],
        }), encoding="utf-8")
        self.ultimate_csv = self.datasets_dir / "ultimate.csv"
        test_log(f"SETUP_STEP write_ultimate_csv={self.ultimate_csv}")
        self.ultimate_csv.write_text("100\n200\n300\n", encoding="utf-8")
        test_log("SETUP_STEP build_payload")
        payload = sample_payload()
        payload["data_tab"]["input data triangle csv path"] = str(self.input_csv)
        payload["results_tab"]["ultimate vector csv path"] = str(self.ultimate_csv)
        test_log(f"SETUP_STEP write_method={self.method_path}")
        self.method_path.write_text(json.dumps(payload), encoding="utf-8")
        test_log(
            "SETUP "
            f"root={self.root} rc_data_dir={self.rc_data_dir} "
            f"method_path={self.method_path} input_csv={self.input_csv} ultimate_csv={self.ultimate_csv}"
        )

    def tearDown(self) -> None:
        test_log(f"TEARDOWN {self.id()} root={getattr(self, 'root', '')}")
        try:
            self.tmp.cleanup()
            test_log(f"END {self.id()}")
        except Exception as err:
            test_log(f"TEARDOWN_ERROR {self.id()} {err!r}")
            raise

    def test_client_project_and_index(self) -> None:
        client = ArcRhoClient(self.root)
        self.assertEqual(client.list_projects(), ["Demo"])
        project = client.project("demo")
        refs = project.rebuild_dfm_index()
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].name, "Paid DFM")
        index = json.loads((self.rc_data_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["version"], DATASET_INDEX_VERSION)
        self.assertEqual(index["reserving_class"], r"Auto\PP")
        self.assertEqual(
            [row["name"] for row in index["files"]],
            ["Paid DFM", "Paid Loss"],
        )
        dfm_row = next(row for row in index["files"] if row["name"] == "Paid DFM")
        self.assertEqual(dfm_row["dataset_type"], "Paid Ultimate")
        self.assertNotIn("method_name", dfm_row)
        for row in index["files"]:
            self.assertLessEqual(set(row), set(INDEX_ROW_FIELDS))
            self.assertTrue(set(row).isdisjoint(FORBIDDEN_INDEX_ROW_FIELDS))
            self.assertFalse(any(isinstance(value, (dict, list)) for value in row.values()))

    def test_dfm_filename_uses_reversible_display_name_encoding(self) -> None:
        method_name = r"Paid/DFM\Selected"
        file_name = dfm_filename(method_name)
        self.assertEqual(file_name, "DFM@Paid_%2F_DFM_%5C_Selected.json")
        self.assertEqual(parse_dfm_filename(file_name), method_name)

        method_path = self.methods_dir / file_name
        payload = sample_payload()
        payload["details_tab"]["name"] = method_name
        method_path.write_text(json.dumps(payload), encoding="utf-8")

        dfm = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP").dfm(method_name)
        self.assertEqual(dfm.name, method_name)
        self.assertEqual(dfm.ratio(1, 1), 1.1)

    def test_default_server_root_uses_host_workspace_config(self) -> None:
        original_explicit = api_config._explicit_server_root
        original_root = api_config._server_root
        with tempfile.TemporaryDirectory(dir=str(_TMP_ROOT)) as appdata, patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
            try:
                config_path = Path(appdata) / "ArcRho" / "workspace_paths.json"
                config_path.parent.mkdir(parents=True)
                config_path.write_text(json.dumps({"workspace_root": str(self.root)}), encoding="utf-8")
                api_config._explicit_server_root = None
                api_config._server_root = None
                self.assertEqual(get_server_root(), self.root.resolve())
                self.assertEqual(ArcRhoClient().server_root, self.root.resolve())
                self.assertEqual(get_config_path(), config_path)
            finally:
                api_config._explicit_server_root = original_explicit
                api_config._server_root = original_root

    def test_set_server_root_writes_host_workspace_config(self) -> None:
        original_explicit = api_config._explicit_server_root
        original_root = api_config._server_root
        with tempfile.TemporaryDirectory(dir=str(_TMP_ROOT)) as appdata, patch.dict(os.environ, {"APPDATA": appdata}, clear=False):
            try:
                api_config._explicit_server_root = None
                api_config._server_root = None
                config_path = Path(appdata) / "ArcRho" / "workspace_paths.json"
                configured = set_server_root(self.root)
                self.assertEqual(configured, self.root.resolve())
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["workspace_root"], str(self.root.resolve()))
                self.assertEqual(saved["paths"], {"projects_dir": "projects", "requests_dir": "requests"})
            finally:
                api_config._explicit_server_root = original_explicit
                api_config._server_root = original_root

    def test_dfm_helpers_upgrade_to_canonical_v2(self) -> None:
        payload = json.loads(self.method_path.read_text(encoding="utf-8"))
        payload["ratios_tab"]["percent developed curve"] = {"x-axis label": "Development Month", "selected curves": []}
        self.method_path.write_text(json.dumps(payload), encoding="utf-8")
        dfm = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP").dfm("Paid DFM")
        dfm.clear()
        dfm.ex_COVID_AY()
        dfm.ex_AY(2020, "exclude accident year")
        dfm.ex_hi(1, 1, "high ratio")
        dfm.select_low(2, 1)
        dfm.set_selected_estimate("Simple - 3", "all")
        dfm.set_user_formula('="Simple - 3" * 0.961538', 1.25, 2)
        dfm.add_notes("reviewed")
        dfm.save()
        saved_text = self.method_path.read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        self.assertEqual(saved["json_format"], "arcrho-dfm-v4")
        self.assertNotIn("unknown section", saved)
        self.assertIn("input_data_triangle_values", saved["data_tab"])
        self.assertNotIn("input data triangle csv path", saved["data_tab"])
        self.assertNotIn("percent developed curve", saved["ratios_tab"])
        self.assertIn("ultimate_vector", saved["results_tab"])
        self.assertNotIn("ultimate vector csv path", saved["results_tab"])
        self.assertEqual(saved["ratios_tab"]["ratio_triangle"]["excluded"][1], [1])
        self.assertIn('["", "", ""]', saved_text)
        self.assertEqual(saved["ratios_tab"]["average_formulas"]["selected"][1][0], 1)
        self.assertEqual(saved["ratios_tab"]["average_formulas"]["selected"][2][1], 1)
        self.assertEqual(saved["ratios_tab"]["average_formulas"]["inputs"][2][1], '="Simple - 3" * 0.961538')
        self.assertEqual(saved["ratios_tab"]["average_formulas"]["values"][2][1], 0.961538)
        self.assertNotIn("notes tab", saved)
        self.assertIn("reviewed", json.loads(self.sidecar_path.read_text(encoding="utf-8"))["notes"])
        self.assertNotEqual(saved["method_metadata"]["last_modified"], "2026-01-01T00:00:00")

    def test_dfm_add_notes_keeps_the_placeholder_source_and_update_notes_drops_it(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        rc.new_dfm(
            "Notes DFM",
            output_vector="Notes Ultimate",
            input_triangle="Paid Loss",
            origin_length=12,
            development_length=12,
        ).save()
        # The app renders placeholders into ``notes`` at save time and keeps
        # the raw text beside it; the macro API reads both.
        sidecar_path = self.sidecars_dir / "Notes DFM.json"
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar["notes"] = "Latest origin 2021."
        sidecar["notes_source"] = "Latest origin {origin_label(-1)}."
        sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
        dfm = rc.dfm("Notes DFM")
        self.assertEqual(dfm.notes, "Latest origin 2021.")
        self.assertEqual(dfm.notes_source, "Latest origin {origin_label(-1)}.")
        dfm.add_notes("reviewed")
        dfm.save()
        saved = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["notes"], "Latest origin 2021.\n\nreviewed")
        self.assertEqual(saved["notes_source"], "Latest origin {origin_label(-1)}.\n\nreviewed")

        dfm.update_notes("rewritten")
        dfm.save()
        saved = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["notes"], "rewritten")
        self.assertEqual(saved["notes_source"], "")

    def test_dfm_save_rebuilds_only_its_reserving_class_index(self) -> None:
        project = ArcRhoClient(self.root).project("Demo")
        dfm = project.reserving_class(r"Auto\PP").dfm("Paid DFM")
        with (
            patch.object(
                project,
                "rebuild_reserving_class_index",
                wraps=project.rebuild_reserving_class_index,
            ) as scoped_rebuild,
            patch.object(
                project,
                "rebuild_dfm_index",
                side_effect=AssertionError("DFM save must not scan every reserving class"),
            ),
        ):
            dfm.save()

        scoped_rebuild.assert_called_once_with(r"Auto\PP")

    def test_read_only_blocks_save(self) -> None:
        dfm = ArcRhoClient(self.root, read_only=True).project("Demo").reserving_class(r"Auto\PP").dfm("Paid DFM")
        dfm.add_notes("blocked")
        with self.assertRaises(ReadOnlyError):
            dfm.save()

    def test_new_dfm_minimum_payload(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        dfm = rc.new_dfm(
            "New DFM",
            output_vector="New Ultimate",
            input_triangle="Paid Loss",
            origin_length=12,
            development_length=12,
        )
        dfm.save()
        self.assertTrue((self.methods_dir / dfm_filename("New DFM")).exists())

    def test_project_reads_dataset_type_category(self) -> None:
        (self.project_dir / "dataset_types.json").write_text(json.dumps({
            "columns": ["Name", "Data Format", "Category", "Calculated", "Formula", "Source"],
            "rows": [["Odd Output", "Vector", "C Claim Count", False, "", ""]],
        }), encoding="utf-8")
        project = ArcRhoClient(self.root).project("Demo")
        info = project.dataset_type("Odd Output")
        self.assertIsNotNone(info)
        self.assertEqual(info.category, "C Claim Count")
        self.assertEqual(project.dataset_type_category("Odd Output"), "C Claim Count")

    def test_migration_session(self) -> None:
        session = ArcRhoSession(self.root)
        session.set_project("Demo")
        session.set_reserving_class(r"Auto\PP")
        dfm = session.DFM("Paid DFM")
        self.assertEqual(dfm.name, "Paid DFM")

    def test_csv_backed_components_and_agent_edits(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        self.assertEqual(rc.list_datasets(), ["input", "ultimate"])
        self.assertEqual(rc.dataset_path("input"), self.input_csv)
        self.assertEqual(rc.read_triangle("input")[0], [10.0, 20.0, 30.0])
        dfm = rc.dfm("Paid DFM")
        self.assertEqual(dfm.input_data_triangle()[0], [10.0, 20.0, 30.0])
        self.assertEqual(dfm.ultimate_vector(), [100.0, 200.0, 300.0])
        summary = dfm.agent_summary()
        self.assertEqual(summary["api method"], "DfmMethod.agent_summary")
        dfm.exclude_ratio("2020", "(1) 12-24").set_selected_average_by_label("Simple - 3", "(2) 24-36").save()
        saved = json.loads(self.method_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["ratios_tab"]["ratio_triangle"]["excluded"][1][0], 1)
        self.assertEqual(saved["ratios_tab"]["average_formulas"]["selected"][1][1], 1)

    def test_add_triangle_reuses_existing_generated_cache(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        cache_path = rc.triangle_cache_path("Paid/Loss", origin_length=12, development_length=12)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("1,2\n3,\n", encoding="utf-8")

        result = rc.add_triangle("Paid/Loss", origin_length=12, development_length=12)

        self.assertTrue(result.from_cache)
        self.assertEqual(result.file_path, cache_path)
        self.assertIsNone(result.request_path)
        sidecar = self.sidecars_dir / "Paid_%2F_Loss.json"
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_name"], "Paid/Loss")
        self.assertEqual(payload["csv_file"], "Paid_%2F_Loss@12@12@cum@dev.csv")

    def test_add_triangle_requests_missing_generated_cache(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        requests_dir = self.root / "requests"
        test_log(f"ARC_TRI_REQUEST_TEST requests_dir={requests_dir}")

        def write_requested_csv() -> None:
            test_log("ARC_TRI_WRITER start")
            deadline = time.time() + 5
            while time.time() < deadline:
                request_files = sorted(requests_dir.glob("request-*.json")) if requests_dir.exists() else []
                if request_files:
                    test_log(f"ARC_TRI_WRITER found_request={request_files[0]}")
                    payload = json.loads(request_files[0].read_text(encoding="utf-8"))
                    data_path = Path(payload["DataPath"])
                    data_path.parent.mkdir(parents=True, exist_ok=True)
                    data_path.write_text("4,5\n6,\n", encoding="utf-8")
                    test_log(f"ARC_TRI_WRITER wrote_csv={data_path}")
                    return
                time.sleep(0.05)
            test_log("ARC_TRI_WRITER timeout_waiting_for_request")

        writer = threading.Thread(target=write_requested_csv)
        writer.start()
        test_log("ARC_TRI_MAIN calling_add_triangle")
        result = rc.add_triangle("Missing Triangle", timeout_sec=3)
        test_log(f"ARC_TRI_MAIN add_triangle_returned file_path={result.file_path} from_cache={result.from_cache}")
        writer.join(timeout=1)
        test_log(f"ARC_TRI_MAIN writer_alive_after_join={writer.is_alive()}")

        self.assertFalse(result.from_cache)
        self.assertIsNotNone(result.request_path)
        self.assertEqual(result.file_path.read_text(encoding="utf-8"), "4,5\n6,\n")
        request_payload = json.loads(result.request_path.read_text(encoding="utf-8"))
        self.assertEqual(request_payload["Function"], "ArcRhoTri")
        self.assertEqual(request_payload["Path"], r"Auto\PP")
        self.assertEqual(request_payload["DatasetName"], "Missing Triangle")
        self.assertEqual(request_payload["ProjectName"], "Demo")
        self.assertEqual(request_payload["DataPath"], str(result.file_path))

    def test_dfm_cell_note_helpers_use_display_labels_and_clear_summary_column(self) -> None:
        payload = sample_payload()
        payload["ratios_tab"]["cell_notes"] = {
            "ratio_main_table": {"2019": {"(1) 12-24": "keep"}},
            "ratio_summary_table": {
                "Old Average": {"(1) 12-24": "stale"},
                "(1) 12-24": {"Legacy Old Average": "legacy stale"},
            },
        }
        self.method_path.write_text(json.dumps(payload), encoding="utf-8")
        dfm = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP").dfm("Paid DFM")
        dfm.set_selected_average("Simple - 3", 1)
        dfm.set_selected_average_cell_note(1, "Selected before adjustments.", clear_column=True)
        dfm.set_cell_note("1: Volume - all", "(2) 24-36", "other note")
        saved = dfm.to_dict()
        self.assertEqual(saved["ratios_tab"]["cell_notes"]["ratio_main_table"]["2019"], {"(1) 12-24": "keep"})
        self.assertNotIn("Old Average", saved["ratios_tab"]["cell_notes"]["ratio_summary_table"])
        self.assertNotIn("(1) 12-24", saved["ratios_tab"]["cell_notes"]["ratio_summary_table"])
        self.assertEqual(
            saved["ratios_tab"]["cell_notes"]["ratio_summary_table"]["Simple - 3"],
            {"(1) 12-24": "Selected before adjustments."},
        )
        self.assertEqual(
            saved["ratios_tab"]["cell_notes"]["ratio_summary_table"]["Volume - all"],
            {"(2) 24-36": "other note"},
        )
        dfm.clear_cell_notes_for_development("(2) 24-36")
        self.assertNotIn("Volume - all", dfm.to_dict()["ratios_tab"]["cell_notes"]["ratio_summary_table"])

    def test_agent_inspect_bundles_summary_components_and_ratio_rows(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = agent_main([
                "--file",
                str(self.method_path),
                "inspect",
                "--include",
                "summary,average-formulas,ratio-triangle",
                "--origin",
                "2020",
            ])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["api method"], "DfmMethod.agent_inspect")
        self.assertEqual(payload["included"], ["summary", "average-formulas", "ratio-triangle"])
        self.assertEqual(payload["components"]["summary"]["api method"], "DfmMethod.agent_summary")
        self.assertEqual(payload["components"]["average_formulas"]["api method"], "DfmMethod.average_formula_summary")
        self.assertEqual(payload["components"]["ratio_triangle"]["values"][0], [1.1, 1.2])
        self.assertEqual(payload["ratio rows"][0]["origin label"], "2020")

    def test_reload_project_instance_dataset_table_command(self) -> None:
        calls: list[tuple[str, dict, float, str | None]] = []

        def fake_post_json(path: str, payload: dict, timeout_sec: float, *, app_url=None):
            calls.append((path, payload, timeout_sec, app_url))
            return {"ok": True, "result": {"refreshed": True, "selectedPath": "Auto\\PP"}}

        with patch("arcrho_api.ui._post_json", fake_post_json):
            result = reload_project_instance_dataset_table(timeout_sec=12, app_url="http://127.0.0.1:28765")

        self.assertTrue(result.ok)
        self.assertEqual(result.result["refreshed"], True)
        self.assertEqual(calls[0][0], "/ui_automation/commands")
        self.assertEqual(calls[0][1]["command"], "projectInstance.refreshDatasets")
        self.assertEqual(calls[0][1]["target"], {"scope": "activeProjectInstance"})
        self.assertEqual(calls[0][3], "http://127.0.0.1:28765")

    def test_project_instance_reload_dataset_table_object_api(self) -> None:
        ui = ArcRhoUI()

        with patch.object(
            ui,
            "reload_project_instance_dataset_table",
            return_value=type("Result", (), {"result": {"refreshed": True}})(),
        ) as mocked:
            result = ui.project_instance.reload_dataset_table(timeout_sec=7)

        self.assertEqual(result, {"refreshed": True})
        mocked.assert_called_once_with(timeout_sec=7)

    def test_macro_source_object_api_checks_arcrho_and_posts_current_buffer(self) -> None:
        ui = ArcRhoUI(app_url="http://127.0.0.1:28765")
        with (
            patch("arcrho_api.ui.get_app_health", return_value={"ok": True, "app": "arcrho"}),
            patch(
                "arcrho_api.ui._post_json",
                return_value={"success": True, "applied": True},
            ) as post,
        ):
            result = ui.macros.run_source(
                "def main(): pass",
                filename="draft.py",
                source_path=r"E:\drafts\draft.py",
                timeout_sec=15,
            )

        self.assertTrue(result["applied"])
        post.assert_called_once_with(
            "/scripting/run-in-arcrho",
            {
                "source": "def main(): pass",
                "filename": "draft.py",
                "source_path": r"E:\drafts\draft.py",
            },
            15,
            app_url="http://127.0.0.1:28765",
        )

    def test_macro_source_object_api_rejects_arcode_server(self) -> None:
        ui = ArcRhoUI(app_url="http://127.0.0.1:28766")
        with patch("arcrho_api.ui.get_app_health", return_value={"ok": True, "app": "arcode"}):
            with self.assertRaises(ArcRhoApiError):
                ui.macros.run_source("def main(): pass")

    def test_missing_ratio_data_raises(self) -> None:
        rc = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP")
        dfm = rc.new_dfm(
            "Empty",
            output_vector="Output",
            input_triangle="Input",
            origin_length=12,
            development_length=12,
        )
        with self.assertRaises(DfmDataError):
            dfm.ex_hi(1)

    def test_save_uses_row_compact_json_for_canonical_triangles(self) -> None:
        payload = sample_payload()
        payload["ratios_tab"]["ratio_triangle"]["ratio_values"] = [[1.2, None, None]]
        payload["ratios_tab"]["ratio_triangle"]["excluded"] = [[1, 0, 2, 2]]
        payload["ratios_tab"]["average_formulas"]["values"] = [[1.2, None], [None, None], [1.3, None]]
        self.method_path.write_text(json.dumps(payload), encoding="utf-8")
        dfm = ArcRhoClient(self.root).project("Demo").reserving_class(r"Auto\PP").dfm("Paid DFM")
        dfm.save()
        saved_text = self.method_path.read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        ratio_values = saved["ratios_tab"]["ratio_triangle"]["ratio_values"]
        excluded = saved["ratios_tab"]["ratio_triangle"]["excluded"]
        self.assertEqual(ratio_values, [[2.0, 1.5], [2.0], []])
        self.assertEqual([len(row) for row in excluded], [len(row) for row in ratio_values])
        self.assertTrue(all(not row or row[-1] is not None for row in ratio_values))
        self.assertIn("[2.0, 1.5]", saved_text)
        self.assertIn("[2.0]", saved_text)


class AppUrlResolutionTests(unittest.TestCase):
    """Cover arcrho_api.ui._base_url discovery of the desktop app endpoint."""

    def setUp(self) -> None:
        test_root = Path(__file__).resolve().parents[2] / "test"
        test_root.mkdir(parents=True, exist_ok=True)
        self._tempdir = tempfile.TemporaryDirectory(dir=str(test_root))
        self.appdata = Path(self._tempdir.name)
        self.addCleanup(self._tempdir.cleanup)

    def _write_endpoint(self, payload) -> None:
        endpoint_dir = self.appdata / "ArcRho"
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        (endpoint_dir / "app_endpoint.json").write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )

    def _env(self, **extra: str) -> dict[str, str]:
        return {"APPDATA": str(self.appdata), **extra}

    def test_explicit_app_url_wins(self) -> None:
        from arcrho_api import ui as ui_module

        self._write_endpoint({"app": "arcrho", "url": "http://127.0.0.1:29123"})
        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url("http://127.0.0.1:29001/"), "http://127.0.0.1:29001")

    def test_env_overrides_win_over_discovery_file(self) -> None:
        from arcrho_api import ui as ui_module

        self._write_endpoint({"app": "arcrho", "url": "http://127.0.0.1:29123"})
        with patch.dict(os.environ, self._env(ARCRHO_APP_URL="http://127.0.0.1:29002/"), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:29002")
        with patch.dict(os.environ, self._env(ARCRHO_PORT="29003"), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:29003")
        with patch.dict(os.environ, self._env(ARCRHO_HOST="localhost"), clear=True):
            self.assertEqual(ui_module._base_url(), "http://localhost:28765")

    def test_discovery_file_used_when_no_overrides(self) -> None:
        from arcrho_api import ui as ui_module

        self._write_endpoint({"app": "arcrho", "url": "http://127.0.0.1:29123/"})
        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:29123")

    def test_invalid_or_foreign_discovery_file_falls_back_to_default(self) -> None:
        from arcrho_api import ui as ui_module

        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:28765")

        self._write_endpoint({"app": "arcode", "url": "http://127.0.0.1:29124"})
        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:28765")

        self._write_endpoint({"app": "arcrho", "url": "file://not-http"})
        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:28765")

        self._write_endpoint("{not valid json")
        with patch.dict(os.environ, self._env(), clear=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:28765")

    def _write_two_apps(self) -> None:
        apps = [
            {"app": "arcrho", "url": "http://127.0.0.1:31001", "port": 31001, "pid": 101},
            {"app": "arcrho", "url": "http://127.0.0.1:31002", "port": 31002, "pid": 102},
            {"app": "arcrho", "url": "http://127.0.0.1:28765", "port": 28765, "pid": 103},
        ]
        self._write_endpoint({**apps[0], "apps": apps})

    def test_list_picks_newest_live_app_by_default(self) -> None:
        from arcrho_api import ui as ui_module

        self._write_two_apps()
        with patch.dict(os.environ, self._env(), clear=True), \
                patch.object(ui_module, "_pid_alive", side_effect=lambda pid: pid != 101):
            self.assertEqual([app["pid"] for app in ui_module.running_apps()], [102, 103])
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:31002")

    def test_list_picks_the_named_app(self) -> None:
        from arcrho_api import ui as ui_module

        self._write_two_apps()
        with patch.dict(os.environ, self._env(), clear=True), \
                patch.object(ui_module, "_pid_alive", return_value=True):
            self.assertEqual(ui_module.ArcRhoUI(pid=103).base_url, "http://127.0.0.1:28765")
            self.assertEqual(ui_module.ArcRhoUI(port=31002).base_url, "http://127.0.0.1:31002")
            with self.assertRaises(ui_module.ArcRhoApiError):
                ui_module.ArcRhoUI(pid=999)
        with patch.dict(os.environ, self._env(ARCRHO_APP_PID="102"), clear=True), \
                patch.object(ui_module, "_pid_alive", return_value=True):
            self.assertEqual(ui_module._base_url(), "http://127.0.0.1:31002")


class ServerRootResolutionTests(unittest.TestCase):
    """Cover the ArcRho Server root resolution chain used by macros and clients.

    A fresh client PC has no ``workspace_paths.json`` because that file is only
    written when a user saves ArcRho Server Connection, so resolution must still
    reach the running desktop app and the packaged default.
    """

    def setUp(self) -> None:
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self._tempdir = tempfile.TemporaryDirectory(dir=str(_TMP_ROOT))
        self.addCleanup(self._tempdir.cleanup)
        base = Path(self._tempdir.name)
        self.appdata = base / "appdata"
        (self.appdata / "ArcRho").mkdir(parents=True)
        self.file_root = self._make_root(base / "file server")
        self.env_root = self._make_root(base / "env server")
        self.app_root = self._make_root(base / "app server")
        self.default_root = self._make_root(base / "default server")
        self.missing_root = base / "no server"

        original_explicit = api_config._explicit_server_root
        original_root = api_config._server_root
        original_attempted = api_config._discovery_attempted

        def restore() -> None:
            api_config._explicit_server_root = original_explicit
            api_config._server_root = original_root
            api_config._discovery_attempted = original_attempted

        self.addCleanup(restore)

    @staticmethod
    def _make_root(path: Path) -> Path:
        (path / "projects").mkdir(parents=True)
        return path.resolve()

    def _reset(self) -> None:
        api_config._explicit_server_root = None
        api_config._server_root = None
        api_config._discovery_attempted = False

    def _write_host_config(self, root: Path) -> None:
        (self.appdata / "ArcRho" / "workspace_paths.json").write_text(
            json.dumps({"workspace_root": str(root)}), encoding="utf-8"
        )

    def _env(self, **extra: str) -> dict[str, str]:
        return {"APPDATA": str(self.appdata), **extra}

    def test_env_override_wins_over_host_config(self) -> None:
        self._write_host_config(self.file_root)
        for name in api_config.SERVER_ROOT_ENV_VARS:
            with self.subTest(env=name):
                with patch.dict(os.environ, self._env(**{name: str(self.env_root)}), clear=True):
                    self._reset()
                    self.assertEqual(get_server_root(), self.env_root)

    def test_env_override_applies_after_a_root_is_already_cached(self) -> None:
        """The ArcRho Bridge exports its runtime root into a running process."""

        self._write_host_config(self.file_root)
        with patch.dict(os.environ, self._env(), clear=True):
            self._reset()
            self.assertEqual(get_server_root(), self.file_root)
            os.environ[api_config.RUNTIME_SERVER_ROOT_ENV] = str(self.env_root)
            self.assertEqual(get_server_root(), self.env_root)

    def test_explicit_set_server_root_outranks_env_override(self) -> None:
        with patch.dict(
            os.environ, self._env(**{api_config.SERVER_ROOT_ENV: str(self.env_root)}), clear=True
        ):
            self._reset()
            set_server_root(self.file_root, persist=False)
            self.assertEqual(get_server_root(), self.file_root)

    def test_host_config_wins_over_running_app(self) -> None:
        self._write_host_config(self.file_root)
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "arcrho_api.ui._request_json"
        ) as request_json:
            self._reset()
            self.assertEqual(get_server_root(), self.file_root)
            request_json.assert_not_called()

    def test_running_app_supplies_root_when_host_config_missing(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "arcrho_api.ui._request_json",
            return_value={"ok": True, "config": {"workspace_root": str(self.app_root)}},
        ) as request_json:
            self._reset()
            self.assertEqual(get_server_root(), self.app_root)
            request_json.assert_called_once()
            self.assertEqual(request_json.call_args.args[0], "/workspace_paths")

    def test_packaged_default_used_when_app_is_not_running(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "arcrho_api.ui._request_json", side_effect=ArcRhoApiError("not reachable")
        ), patch.object(api_config, "DEFAULT_WORKSPACE_ROOT", str(self.default_root)):
            self._reset()
            self.assertEqual(get_server_root(), self.default_root)

    def test_unusable_packaged_default_is_rejected(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "arcrho_api.ui._request_json", side_effect=ArcRhoApiError("not reachable")
        ), patch.object(api_config, "DEFAULT_WORKSPACE_ROOT", str(self.missing_root)):
            self._reset()
            self.assertIsNone(get_server_root())
            with self.assertRaises(InvalidArcRhoServerError) as caught:
                get_server_root(required=True)
        self.assertIn(api_config.SERVER_ROOT_ENV, str(caught.exception))

    def test_discovery_runs_once_until_reloaded(self) -> None:
        with patch.dict(os.environ, self._env(), clear=True), patch(
            "arcrho_api.ui._request_json", side_effect=ArcRhoApiError("not reachable")
        ) as request_json, patch.object(
            api_config, "DEFAULT_WORKSPACE_ROOT", str(self.missing_root)
        ):
            self._reset()
            self.assertIsNone(get_server_root())
            self.assertIsNone(get_server_root())
            self.assertEqual(request_json.call_count, 1)

            request_json.side_effect = None
            request_json.return_value = {"config": {"workspace_root": str(self.app_root)}}
            self.assertEqual(reload_server_root(), self.app_root)
            self.assertEqual(request_json.call_count, 2)


if __name__ == "__main__":
    unittest.main()
