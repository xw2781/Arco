"""App-server behaviour for Stochastic Consolidation methods.

A consolidation lives in one reserving class and names its segments, Bootstrap
methods in other classes, by class path and method name.  These tests pin that
the service reads each segment from its own class, reports a changed or
vanished segment on load, runs without writing, and publishes a run that
matches its saved inputs.  The numbers themselves are pinned in
``python-api/tests/test_stochastic_consolidation_contract.py``.

Run as a script (``python tests/test_stochastic_consolidation_service.py``):
the propagation stub is imported by bare name.
"""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from fastapi import HTTPException


REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_TEMP_ROOT = REPO_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
FRONTEND_ROOT = REPO_ROOT / "frontend"
PYTHON_API_SRC = REPO_ROOT / "python-api" / "src"
for path in (FRONTEND_ROOT, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_api.bootstrap_contract import (
    BST_JSON_FORMAT,
    dfm_snapshot_from_method,
    recalculate_bootstrap_method,
)
from arcrho_api.dfm_contract import normalize_dfm_method
from arcrho_api.io import persisted_json_text
from arcrho_api.stochastic_consolidation_contract import SCON_JSON_FORMAT
from arcrho_engine_save_contract import SAVE_JOB_KINDS, SAVE_JOB_PLAN_ROOT_FUNCTION
from arcrho_hosted_save_http_contract import HTTP_SAVE_KINDS
from arcrho_workspace_read_contract import HTTP_WORKSPACE_READ_KINDS, WORKSPACE_READ_KINDS
from app_server import config
import app_server.api  # noqa: F401  (registers the route submodules)
from app_server.schemas.stochastic_consolidation import (
    StochasticConsolidationClassRequest,
    StochasticConsolidationIdentityRequest,
    StochasticConsolidationRunRequest,
    StochasticConsolidationSaveRequest,
)
from app_server.services import (
    calculated_dataset_service,
    dataset_sidecar_status_service,
    stochastic_consolidation_service as service,
)
from dependent_propagation_workspace_stub import IsolatedPropagationWorkspace

router = sys.modules["app_server.api.stochastic_consolidation_router"]

RESQ_FIXTURE_PATH = REPO_ROOT / "python-api" / "tests" / "fixtures" / "resq_bootstrap_f72a.json"
PROJECT = "Project"
OTHER_PROJECT = "Project Oil"
GROUP = "PA\\All States\\Direct Group"
HOST = f"{GROUP}\\Total"
CLASS_A = f"{GROUP}\\BI Total"
CLASS_B = f"{GROUP}\\COL"
# The same name in both classes, as in the reference model: segments are told
# apart by their class.
BOOTSTRAP_NAME = "F 72 A - Bootstrap Net Incurred with PV"
DFM_NAME = "F 25 - Incurred DFM Bootstrap"
BASE_TYPE = "F 10 - Incurred"
CONSOLIDATION_NAME = "F 72 A - Bootstrap Consolidation"
SIMULATIONS = 200
STAMP = "2026-09-23T00:00:00Z"


class StochasticConsolidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        root = Path(self.temp.name)
        self.data = root / "data"
        self.data.mkdir()
        self.other_data = root / "other" / "data"
        self.other_data.mkdir(parents=True)
        settings = root / "general_settings.json"
        settings.write_text(
            '{"origin_start_date":"201501","origin_end_date":"202412","development_end_date":"202412"}',
            encoding="utf-8",
        )
        self.patchers = [
            IsolatedPropagationWorkspace(),
            mock.patch.object(config, "get_project_data_dir", side_effect=self._project_data_dir),
            mock.patch.object(config, "get_general_settings_path", return_value=str(settings)),
            mock.patch.object(calculated_dataset_service, "_dataset_type_rows", return_value=[]),
            mock.patch.object(calculated_dataset_service, "_existing_dataset_keys", return_value=set()),
            mock.patch.object(
                calculated_dataset_service,
                "recalculate_dependents",
                return_value={"ok": True, "updated": [], "index_ok": True, "index_error": ""},
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        fixture = json.loads(RESQ_FIXTURE_PATH.read_text(encoding="utf-8"))
        self.case = fixture["methods"]["odp_single_scale"]
        self.reference = fixture["simulation_reference"]
        self.origin_labels = list(self.case["origin_labels"])
        self.write_bootstrap(CLASS_A, seed=11)
        self.write_bootstrap(CLASS_B, seed=22, scale=0.6)

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    # -- fixtures ---------------------------------------------------------

    def _project_data_dir(self, project_name: str) -> str:
        return str(self.other_data if project_name == OTHER_PROJECT else self.data)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(persisted_json_text(payload), encoding="utf-8", newline="\n")

    def _method_file(self, reserving_class: str, method_type: str, name: str, project: str = PROJECT) -> Path:
        return Path(dataset_sidecar_status_service.method_json_path(project, reserving_class, method_type, name))

    def _dfm(self, scale: float) -> dict:
        triangle = [
            [None if value is None else value * scale for value in row]
            for row in self.case["observed_triangle"]
        ]
        development = [str(12 * (index + 1)) for index in range(len(self.origin_labels))]
        ratios = list(self.case["selected_ratios"])
        return normalize_dfm_method(
            {
                "json_format": "arcrho-dfm-v4",
                "details_tab": {
                    "name": DFM_NAME,
                    "output_type": "F 00 - Ultimate Net Loss",
                    "output_dataset": DFM_NAME,
                    "input_triangle": BASE_TYPE,
                    "origin_length": 12,
                    "development_length": 12,
                },
                "data_tab": {
                    "origin_labels": self.origin_labels,
                    "development_labels": development,
                    "input_data_triangle_values": triangle,
                },
                "ratios_tab": {
                    "ratio_triangle": {"development_labels": development},
                    "average_formulas": {
                        "values": [ratios],
                        "selected": [[1] * len(ratios)],
                        "custom_average_formula_settings": {
                            "average_type": ["user_entry"],
                            "base": ["volume"],
                            "periods": ["all"],
                            "exclude": [0],
                        },
                    },
                },
                "results_tab": {},
                "method_metadata": {},
            },
            require_complete=False,
        )

    def write_bootstrap(self, reserving_class: str, *, seed: int, scale: float = 1.0,
                        name: str = BOOTSTRAP_NAME, simulations: int = SIMULATIONS,
                        project: str = PROJECT) -> dict:
        dfm = self._dfm(scale)
        self._write_json(self._method_file(reserving_class, "DFM", DFM_NAME, project), dfm)
        targets = [
            (target + latest) * scale
            for target, latest in zip(
                self.reference["target_reserve_values"], self.reference["dfm_latest_values"]
            )
        ]
        payload = {
            "json_format": BST_JSON_FORMAT,
            "details_tab": {
                "name": name,
                "output_type": "F 00 - Ultimate Net Loss",
                "origin_length": 12,
                "development_length": 12,
                "model_type": self.case["model_type"],
                "dfm_method": DFM_NAME,
            },
            "residuals_tab": {},
            "simulation_tab": {
                "estimation_variance": self.reference["estimation_variance"],
                "process_variance": self.reference["process_variance"],
                "simulation_count": simulations,
                "random_seed": seed,
                "prevent_negative_data": self.reference["prevent_negative_data"],
                "negative_mean_action": self.reference["negative_mean_action"],
            },
            "results_tab": {
                "target_ultimate": "Target",
                "target_scaling_methods": list(self.reference["target_scaling_methods"]),
            },
            "output_tab": {},
            "method_metadata": {},
        }
        method = recalculate_bootstrap_method(
            payload,
            dfm_snapshot=dfm_snapshot_from_method(dfm),
            target_snapshot={"name": "Target", "origin_labels": self.origin_labels, "values": targets},
            timestamp=STAMP,
        )
        self._write_json(self._method_file(reserving_class, "Bootstrap", name, project), method)
        return method

    def consolidation(self, **details) -> dict:
        return {
            "json_format": SCON_JSON_FORMAT,
            "details_tab": {
                "name": CONSOLIDATION_NAME,
                "output_type": "F 00 - Ultimate Net Loss",
                "base_triangle_type": BASE_TYPE,
                "origin_length": 12,
                "development_length": 12,
                "random_seed": 1514684455,
                **details,
            },
            "segments_tab": {
                "segments": [
                    {"reserving_class": CLASS_A, "method_name": BOOTSTRAP_NAME, "factor": 1},
                    {"reserving_class": CLASS_B, "method_name": BOOTSTRAP_NAME, "factor": 1},
                ]
            },
            "correlation_tab": {
                "correlation_option": "specified",
                "dependency_type": "normal",
                "target_correlations": [[1, 0.4], [0.4, 1]],
            },
        }

    def save(self, payload: dict | None = None, **kwargs) -> dict:
        return service.save_stochastic_consolidation_method(
            PROJECT, HOST, payload if payload is not None else self.consolidation(), **kwargs
        )

    def host_files(self) -> list[Path]:
        host_dir = Path(config.get_project_reserving_class_data_dir(PROJECT, HOST))
        return sorted(path for path in host_dir.rglob("*") if path.is_file()) if host_dir.exists() else []

    # -- load, run, save --------------------------------------------------

    def test_consolidate_reads_both_classes_and_writes_nothing(self) -> None:
        response = service.consolidate_stochastic_consolidation_method(PROJECT, HOST, self.consolidation())

        method = response["method"]
        self.assertEqual(method["details_tab"]["simulation_count"], SIMULATIONS)
        self.assertEqual(method["results_tab"]["origin_labels"], self.origin_labels)
        self.assertTrue(all(value is not None for value in method["results_tab"]["consolidation_ultimate"]))
        self.assertEqual([row["status"] for row in response["segments"]], ["current", "current"])
        self.assertEqual([row["reserving_class"] for row in response["segments"]], [CLASS_A, CLASS_B])
        self.assertEqual([row["base_triangle_type"] for row in response["segments"]], [BASE_TYPE, BASE_TYPE])
        self.assertTrue(all(row["has_run"] and row["problems"] == [] for row in response["segments"]))
        self.assertEqual(response["run_state"], service.STATE_UP_TO_DATE)
        self.assertFalse(response["sidecar"]["exists"])
        self.assertEqual(self.host_files(), [])
        # The run's finest ladder comes back beside the method, never inside it.
        ladder = response["finer_ladder"]
        self.assertEqual(ladder["interval"], 0.01)
        self.assertEqual(len(ladder["scaled"]), 10001)
        self.assertEqual(ladder["scaled"]["99.5"], method["results_tab"]["simulation_summary"]["scaled"]["percentiles"]["99.5"])
        self.assertNotIn("finer_ladder", method["results_tab"])

    def test_save_publishes_the_run_and_reopens_up_to_date(self) -> None:
        run = service.consolidate_stochastic_consolidation_method(PROJECT, HOST, self.consolidation())
        saved = self.save()

        self.assertTrue(saved["consolidated"])
        # Save re-runs from the seed, so it publishes exactly what Consolidate showed.
        self.assertEqual(
            saved["method"]["results_tab"]["consolidation_ultimate"],
            run["method"]["results_tab"]["consolidation_ultimate"],
        )
        names = {path.name for path in self.host_files()}
        self.assertIn(f"SCON@{CONSOLIDATION_NAME}.json", names)
        self.assertIn(f"{CONSOLIDATION_NAME}@12.csv", names)
        self.assertIn(f"{CONSOLIDATION_NAME}.json", names)
        sidecar = saved["sidecar"]
        self.assertEqual(sidecar["method_type"], "Stochastic Consolidation")
        self.assertEqual(
            [(entry["dataset_name"], entry.get("reserving_class")) for entry in sidecar["precedents"]],
            [(BOOTSTRAP_NAME, CLASS_A), (BOOTSTRAP_NAME, CLASS_B)],
        )
        # Propagation across classes is deferred: no bootstrap gains a reverse edge.
        bootstrap_sidecar = Path(dataset_sidecar_status_service.sidecar_path(PROJECT, CLASS_A, BOOTSTRAP_NAME))
        self.assertFalse(bootstrap_sidecar.exists())

        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(loaded["publication_revision"], saved["publication_revision"])
        self.assertEqual(persisted_json_text(loaded["method"]), persisted_json_text(saved["method"]))
        self.assertEqual(loaded["stale_segments"], [])
        self.assertEqual(loaded["run_state"], service.STATE_UP_TO_DATE)
        self.assertTrue(loaded["sidecar"]["exists"])

    def test_a_changed_segment_is_reported_on_load_and_consolidated_on_save(self) -> None:
        self.save()
        self.write_bootstrap(CLASS_B, seed=23, scale=0.6)

        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(
            loaded["stale_segments"],
            [{"project_name": "", "reserving_class": CLASS_B, "method_name": BOOTSTRAP_NAME, "status": "changed"}],
        )
        self.assertEqual(loaded["run_state"], service.STATE_SEGMENT_CHANGED)

        resaved = self.save(loaded["method"], expected_owned_revision=loaded["owned_revision"])
        self.assertTrue(resaved["consolidated"])
        self.assertEqual(resaved["stale_segments"], [])
        self.assertEqual(resaved["run_state"], service.STATE_UP_TO_DATE)

    def test_a_notes_only_save_keeps_the_stored_run(self) -> None:
        saved = self.save()

        again = self.save(saved["method"], notes="Reviewed", expected_owned_revision=saved["owned_revision"])

        self.assertFalse(again["consolidated"])
        self.assertEqual(again["derived_revision"], saved["derived_revision"])
        self.assertEqual(again["sidecar"]["notes"], "Reviewed")

    def test_changed_settings_are_reported_and_a_stale_owned_revision_conflicts(self) -> None:
        saved = self.save()
        edited = deepcopy(saved["method"])
        edited["details_tab"]["random_seed"] = 7

        with self.assertRaises(HTTPException) as conflict:
            self.save(edited, expected_owned_revision="sha256:stale")
        self.assertEqual(conflict.exception.status_code, 409)

        resaved = self.save(edited, expected_owned_revision=saved["owned_revision"])
        self.assertTrue(resaved["consolidated"])
        self.assertEqual(resaved["method"]["details_tab"]["random_seed"], 7)

    def test_a_missing_segment_is_reported_and_refuses_the_save(self) -> None:
        self.save()
        self._method_file(CLASS_A, "Bootstrap", BOOTSTRAP_NAME).unlink()

        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(loaded["segments"][0]["status"], "missing")
        self.assertEqual(loaded["segments"][0]["problems"], [service.PROBLEM_MISSING])

        with self.assertRaises(HTTPException) as refused:
            self.save(loaded["method"])
        self.assertEqual(refused.exception.status_code, 404)
        self.assertIn(f"{CLASS_A} / {BOOTSTRAP_NAME}", str(refused.exception.detail))

    def test_a_mismatched_base_type_is_refused_with_the_segment_named(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            service.consolidate_stochastic_consolidation_method(
                PROJECT, HOST, self.consolidation(base_triangle_type="Net Loss--Paid")
            )
        self.assertEqual(refused.exception.status_code, 422)
        self.assertIn(f"{CLASS_A} / {BOOTSTRAP_NAME}", str(refused.exception.detail))

    def test_a_mismatched_simulation_count_is_flagged_on_the_row(self) -> None:
        self.save()
        self.write_bootstrap(CLASS_B, seed=22, scale=0.6, simulations=100)

        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertIn(service.PROBLEM_SIMULATION_COUNT, loaded["segments"][1]["problems"])

    def test_load_rejects_a_missing_method_and_a_missing_sidecar(self) -> None:
        with self.assertRaises(HTTPException) as missing:
            service.load_stochastic_consolidation_method(PROJECT, HOST, "Nope")
        self.assertEqual(missing.exception.status_code, 404)

        self.save()
        Path(dataset_sidecar_status_service.sidecar_path(PROJECT, HOST, CONSOLIDATION_NAME)).unlink()
        with self.assertRaises(HTTPException) as orphan:
            service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(orphan.exception.status_code, 409)

    def test_candidates_list_bootstraps_in_the_other_classes(self) -> None:
        # One in the host class too: the picker offers only other classes.
        self.write_bootstrap(HOST, seed=5, name="Host Bootstrap")
        self.write_bootstrap(CLASS_B, seed=6, name="Another Bootstrap")

        response = service.list_stochastic_consolidation_candidates(PROJECT, HOST)

        self.assertEqual(
            [(row["reserving_class"], row["method_name"]) for row in response["candidates"]],
            [(CLASS_A, BOOTSTRAP_NAME), (CLASS_B, "Another Bootstrap"), (CLASS_B, BOOTSTRAP_NAME)],
        )
        first = response["candidates"][0]
        self.assertEqual(first["simulation_count"], SIMULATIONS)
        self.assertEqual(first["base_triangle_type"], BASE_TYPE)
        self.assertTrue(first["has_run"])
        self.assertIsNotNone(first["mean"])
        self.assertAlmostEqual(first["cv"], first["standard_error"] / first["mean"])

    def test_a_segment_is_read_from_the_project_it_names(self) -> None:
        self.write_bootstrap(CLASS_B, seed=33, scale=0.4, project=OTHER_PROJECT)
        payload = self.consolidation()
        payload["segments_tab"]["segments"][1]["project_name"] = OTHER_PROJECT

        response = service.consolidate_stochastic_consolidation_method(PROJECT, HOST, payload)
        local = service.consolidate_stochastic_consolidation_method(PROJECT, HOST, self.consolidation())
        self.assertEqual([row["project_name"] for row in response["segments"]], ["", OTHER_PROJECT])
        self.assertEqual(response["segments"][1]["random_seed"], 33)
        self.assertNotEqual(
            response["method"]["results_tab"]["consolidation_ultimate"],
            local["method"]["results_tab"]["consolidation_ultimate"],
        )

        saved = self.save(payload)
        self.assertEqual(saved["sidecar"]["precedents"][1]["project"], OTHER_PROJECT)
        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(loaded["run_state"], service.STATE_UP_TO_DATE)

        Path(self._method_file(CLASS_B, "Bootstrap", BOOTSTRAP_NAME, OTHER_PROJECT)).unlink()
        loaded = service.load_stochastic_consolidation_method(PROJECT, HOST, CONSOLIDATION_NAME)
        self.assertEqual(
            loaded["stale_segments"],
            [{"project_name": OTHER_PROJECT, "reserving_class": CLASS_B, "method_name": BOOTSTRAP_NAME,
              "status": "missing"}],
        )

    def test_candidates_from_another_project_list_every_class_there(self) -> None:
        self.write_bootstrap(HOST, seed=5, name="Oil Bootstrap", project=OTHER_PROJECT)

        response = service.list_stochastic_consolidation_candidates(PROJECT, HOST, OTHER_PROJECT)

        self.assertEqual(
            [(row["project_name"], row["reserving_class"], row["method_name"]) for row in response["candidates"]],
            [(OTHER_PROJECT, HOST, "Oil Bootstrap")],
        )
        self.assertEqual(response["candidates"][0]["base_triangle_type"], BASE_TYPE)
        # Naming the host project is the same as naming none.
        own = service.list_stochastic_consolidation_candidates(PROJECT, HOST, PROJECT)
        self.assertEqual({row["project_name"] for row in own["candidates"]}, {""})

    def test_save_propagation_roots_name_the_output(self) -> None:
        self.assertEqual(
            service.save_propagation_roots(PROJECT, HOST, self.consolidation()),
            [(CONSOLIDATION_NAME, "F 00 - Ultimate Net Loss")],
        )


class _CaptureRead:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, kind, kwargs, *, local):
        self.calls.append((kind, dict(kwargs)))
        return local()


class TransportTests(unittest.TestCase):
    """The load, run and picker are hosted reads; the save is a hosted save."""

    READS = {
        "stochastic_consolidation_load": "load_stochastic_consolidation_method",
        "stochastic_consolidation_consolidate": "consolidate_stochastic_consolidation_method",
        "stochastic_consolidation_candidates": "list_stochastic_consolidation_candidates",
    }

    def test_the_reads_are_registered_with_the_service_signatures(self) -> None:
        for kind, function in self.READS.items():
            self.assertIn(kind, HTTP_WORKSPACE_READ_KINDS)
            spec = WORKSPACE_READ_KINDS[kind]
            self.assertEqual((spec.module, spec.function), ("stochastic_consolidation_service", function))
            # A contract argument the service does not take breaks the read
            # only on the Gateway, never locally.
            parameters = inspect.signature(getattr(service, function)).parameters
            self.assertEqual(set(spec.required) | set(spec.optional), set(parameters))
            for name in spec.optional:
                self.assertIsNot(parameters[name].default, inspect.Parameter.empty)

    def test_the_save_is_registered_and_can_report_its_roots(self) -> None:
        self.assertEqual(
            SAVE_JOB_KINDS["stochastic_consolidation_method"],
            ("stochastic_consolidation_service", "save_stochastic_consolidation_method"),
        )
        self.assertIn("stochastic_consolidation_method", HTTP_SAVE_KINDS)
        self.assertTrue(callable(getattr(service, SAVE_JOB_PLAN_ROOT_FUNCTION, None)))

    def test_routes_select_the_hosted_transport(self) -> None:
        capture = _CaptureRead()
        method = {"json_format": SCON_JSON_FORMAT, "details_tab": {"name": "M"}, "results_tab": {"big": 1}}
        with (
            mock.patch.object(router.workspace_read_client, "run_workspace_read", capture),
            mock.patch.object(router.stochastic_consolidation_service, "load_stochastic_consolidation_method",
                              return_value={"ok": True}) as load,
            mock.patch.object(router.stochastic_consolidation_service, "consolidate_stochastic_consolidation_method",
                              return_value={"ok": True}) as run,
            mock.patch.object(router.stochastic_consolidation_service, "list_stochastic_consolidation_candidates",
                              return_value={"ok": True}) as candidates,
        ):
            router.load_stochastic_consolidation(
                StochasticConsolidationIdentityRequest(project_name="Demo", reserving_class="Total", method_name="M")
            )
            router.consolidate_stochastic_consolidation(
                StochasticConsolidationRunRequest(project_name="Demo", reserving_class="Total", method=method)
            )
            router.list_stochastic_consolidation_candidates(
                StochasticConsolidationClassRequest(project_name="Demo", reserving_class="Total")
            )
        load.assert_called_once_with("Demo", "Total", "M")
        run.assert_called_once_with("Demo", "Total", {"json_format": SCON_JSON_FORMAT, "details_tab": {"name": "M"}})
        candidates.assert_called_once_with("Demo", "Total", "")
        self.assertEqual([kind for kind, _ in capture.calls], list(self.READS))
        # The stored results never travel with a run request.
        self.assertNotIn("results_tab", capture.calls[1][1]["method"])
        for kind, kwargs in capture.calls:
            spec = WORKSPACE_READ_KINDS[kind]
            self.assertTrue(set(kwargs) <= spec.allowed)
            self.assertTrue(set(spec.required) <= set(kwargs))

    def test_save_and_plan_go_to_the_engine(self) -> None:
        request = StochasticConsolidationSaveRequest(
            project_name="Demo", reserving_class="Total", method={"details_tab": {"name": "M"}},
            notes="n", plan_fingerprint="fp",
        )
        with (
            mock.patch.object(router.engine_hosted_save_service, "run_hosted_save",
                              return_value={"ok": True}) as save,
            mock.patch.object(router.engine_hosted_save_service, "run_hosted_save_plan",
                              return_value={"ok": True}) as plan,
        ):
            router.plan_stochastic_consolidation_save(request)
            router.save_stochastic_consolidation(request)
        projection = {
            "args": ["Demo", "Total", {"details_tab": {"name": "M"}}],
            "kwargs": {"notes": "n", "expected_owned_revision": None, "expected_derived_revision": None},
        }
        plan.assert_called_once_with("stochastic_consolidation_method", "Demo", "Total", **projection)
        save.assert_called_once_with(
            "stochastic_consolidation_method", "Demo", "Total", plan_fingerprint="fp", **projection
        )


if __name__ == "__main__":
    unittest.main()
