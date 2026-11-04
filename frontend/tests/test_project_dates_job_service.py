"""Project dates change in the app server: submit, status, preview and routes."""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = FRONTEND_ROOT.parent
SERVER_COMPONENTS_SRC = REPOSITORY_ROOT / "server-components" / "src"
PYTHON_API_SRC = REPOSITORY_ROOT / "python-api" / "src"
TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
for path in (FRONTEND_ROOT, SERVER_COMPONENTS_SRC, PYTHON_API_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from arcrho_dependent_propagation_contract import ENGINE_UNAVAILABLE_MESSAGE
from arcrho_project_dates_job_contract import (
    find_queued_project_dates_job,
    project_dates_job_request_path,
    project_dates_job_status_path,
    write_pending_record,
    write_project_dates_job_status,
)
from arcrho_workspace_mutation_contract import WORKSPACE_MUTATION_KINDS
from arcrho_workspace_read_contract import WORKSPACE_READ_KINDS

from app_server import config
from app_server.schemas.project_settings import ProjectDatesChangeRequest
from app_server.services import (
    dataset_instance_index_service,
    dependent_propagation_service,
    project_dates_job_service,
)

project_settings_router = import_module("app_server.api.project_settings_router")


PROJECT = "Demo Project"
CLASS = "A\\One"
REQUEST_ID = "abcdef0123456789abcdef0123456789"
OTHER_ID = "0123456789abcdef0123456789abcdef"
PREVIOUS = {"origin_start_date": "202001", "origin_end_date": "202512", "development_end_date": "202605"}
NEW = {"origin_start_date": "202101", "origin_end_date": "202612", "development_end_date": "202612"}
# Annual ages from Jan 2020 to May 2026, and from Jan 2021 to Dec 2026.
PREVIOUS_AGES = ["5m", "17m", "29m", "41m", "53m", "65m", "77m"]


class _Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(TEST_TEMP_ROOT))
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.project_dir = self.root / "projects" / PROJECT
        self.project_dir.mkdir(parents=True)
        (self.project_dir / "general_settings.json").write_text(
            json.dumps({"project_name": PROJECT, **PREVIOUS}), encoding="utf-8"
        )
        self.instances_dir = self.root / "runtime" / "instances" / "arcrho_engine"
        workspace = {
            "workspace_root": str(self.root),
            "paths": {"projects_dir": "projects", "requests_dir": "requests"},
        }
        self.index_rows: list[dict] = []
        patches = [
            patch.object(config, "load_workspace_paths", return_value=workspace),
            patch.object(config, "PROJECT_SETTINGS_DIR", str(self.root / "projects")),
            patch.object(
                project_dates_job_service.user_identity_service,
                "get_windows_login_name",
                return_value="Test User",
            ),
            # A test run has no Gateway (arcrho_api.gateway_test_guard), so the
            # propagation checks run as the Gateway runs them on the server.
            patch.object(
                dependent_propagation_service.propagation_gateway_client,
                "is_server_process",
                return_value=True,
            ),
            patch.object(
                dataset_instance_index_service,
                "get_index",
                side_effect=lambda project, rc, refresh=False: {"files": list(self.index_rows)},
            ),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def _write_heartbeat(self) -> None:
        self.instances_dir.mkdir(parents=True, exist_ok=True)
        (self.instances_dir / "engine.json").write_text(
            json.dumps({"Server": "engine", "Last seen": "2026-08-20 12:00:00"}), encoding="utf-8"
        )

    def _add_dataset(self, name: str, sidecar: dict, rows: list[list[str]] | None = None, **row) -> None:
        sidecar_dir = Path(config.get_project_dataset_sidecar_dir(PROJECT, CLASS))
        data_dir = Path(config.get_project_dataset_cache_dir(PROJECT, CLASS))
        sidecar_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        class_dir = Path(config.get_project_reserving_class_data_dir(PROJECT, CLASS))
        (class_dir / "index.json").write_text("{}", encoding="utf-8")
        csv_file = f"{name}.csv"
        payload = {"dataset_name": name, "csv_file": csv_file, **sidecar}
        (sidecar_dir / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
        if rows is not None:
            (data_dir / csv_file).write_text(
                "".join(",".join(row) + "\n" for row in rows), encoding="utf-8"
            )
        self.index_rows.append({"name": name, "source_kind": sidecar.get("source_kind"), **row})


class RegisteredKindsTests(unittest.TestCase):
    def test_hosted_kinds_name_this_service_with_its_own_arguments(self) -> None:
        kinds = (
            WORKSPACE_MUTATION_KINDS["project_dates_change_submit"],
            WORKSPACE_READ_KINDS["project_dates_job_status"],
            WORKSPACE_READ_KINDS["project_dates_preview"],
        )
        for kind in kinds:
            self.assertEqual(kind.module, "project_dates_job_service")
            parameters = inspect.signature(getattr(project_dates_job_service, kind.function)).parameters
            self.assertTrue(set(kind.required) | set(kind.optional) <= set(parameters), kind.function)
        self.assertEqual(WORKSPACE_MUTATION_KINDS["project_dates_change_submit"].locked_project_arg, "project_name")


class SubmitAndStatusTests(_Workspace):
    def _submit(self, request_id: str = REQUEST_ID, dates: dict = NEW):
        return project_dates_job_service.submit_project_dates_job(PROJECT, request_id, **dates)

    def test_no_live_engine_is_a_503_before_anything_is_published(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._submit()
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, ENGINE_UNAVAILABLE_MESSAGE)
        self.assertFalse(project_dates_job_request_path(self.root, REQUEST_ID).exists())

    def test_dates_that_break_the_rule_are_refused(self) -> None:
        self._write_heartbeat()
        with self.assertRaises(HTTPException) as raised:
            self._submit(dates={**NEW, "origin_end_date": "202701"})
        self.assertEqual(raised.exception.status_code, 400)

    def test_submission_publishes_the_queued_status_then_the_request(self) -> None:
        self._write_heartbeat()
        self.assertEqual(
            self._submit(), {"ok": True, "job_id": REQUEST_ID, "status": "queued", "resumed": False}
        )
        request = json.loads(project_dates_job_request_path(self.root, REQUEST_ID).read_text(encoding="utf-8"))
        self.assertEqual(request["DevelopmentEndDate"], "202612")
        self.assertEqual(request["UserName"], "Test User")
        status = json.loads(project_dates_job_status_path(self.root, REQUEST_ID).read_text(encoding="utf-8"))
        self.assertEqual(status["status"], "queued")
        self.assertEqual(
            find_queued_project_dates_job(self.root, PROJECT), {"reason": "queued", "job_id": REQUEST_ID}
        )

    def test_a_resubmitted_id_resumes_and_a_second_change_waits(self) -> None:
        self._write_heartbeat()
        self._submit()
        self.assertTrue(self._submit()["resumed"])
        with self.assertRaises(HTTPException) as raised:
            self._submit(request_id=OTHER_ID)
        self.assertEqual(raised.exception.status_code, 423)
        self.assertEqual(raised.exception.detail, project_dates_job_service.DATES_JOB_BUSY_MESSAGE)

    def test_other_dates_are_refused_while_a_change_is_unfinished(self) -> None:
        self._write_heartbeat()
        write_pending_record(
            self.root, project_name=PROJECT, request_id=OTHER_ID, previous_dates=PREVIOUS, dates=NEW
        )
        with self.assertRaises(HTTPException) as raised:
            self._submit(dates={**NEW, "development_end_date": "202701"})
        self.assertEqual(raised.exception.status_code, 409)
        # The same dates resume the unfinished change.
        self.assertEqual(self._submit()["status"], "queued")

    def test_status_reports_the_published_job_and_the_project_hold(self) -> None:
        self._write_heartbeat()
        self._submit()
        write_project_dates_job_status(
            self.root,
            REQUEST_ID,
            "processing",
            progress={"stage": "classes", "completed": 1, "total": 3, "label": "Reshaping A\\One (2 of 3)"},
            previous_dates=PREVIOUS,
        )
        status = project_dates_job_service.get_project_dates_job_status(PROJECT, REQUEST_ID)
        self.assertTrue(status["found"])
        self.assertEqual(status["progress"]["total"], 3)
        self.assertEqual(status["previous_dates"], PREVIOUS)
        with self.assertRaises(HTTPException) as raised:
            project_dates_job_service.get_project_dates_job_status(PROJECT, OTHER_ID)
        self.assertEqual(raised.exception.status_code, 404)


class PreviewTests(_Workspace):
    def setUp(self) -> None:
        super().setUp()
        triangle = [["1"] * len(PREVIOUS_AGES) for _ in range(6)]
        self._add_dataset(
            "Prem Vec",
            {"source_kind": "input", "data_format": "Vector", "period_length": 12,
             "origin_labels": [str(i) for i in range(1, 7)]},
            [["1"] for _ in range(6)],
            origin_length=12,
        )
        self._add_dataset(
            "Off Vec",
            {"source_kind": "input", "data_format": "Vector", "period_length": 12, "origin_labels": ["1", "2"]},
            [["1"], ["2"]],
            origin_length=12,
        )
        self._add_dataset(
            "Hand Tri",
            {"source_kind": "input", "data_format": "Triangle", "origin_length": 12, "development_length": 12,
             "origin_labels": [str(year) for year in range(2020, 2026)], "development_labels": PREVIOUS_AGES},
            triangle,
            origin_length=12,
        )
        self._add_dataset(
            "ResQ Tri",
            {"source_kind": "engine", "source": "resq_triangle", "data_format": "Triangle",
             "origin_length": 3, "development_length": 3,
             "origin_labels": [f"{year} Q{q}" for year in range(2020, 2026) for q in range(1, 5)]},
            [["1"] for _ in range(24)],
            origin_length=3,
        )
        self._add_dataset("Paid", {"source_kind": "engine", "data_format": "Triangle"}, origin_length=12)
        self._add_dataset("Ratio", {"source_kind": "calculated", "calculated": True})
        self.index_rows.append({"name": "Paid DFM", "source_kind": "dfm", "origin_length": 12})
        self.index_rows.append({"name": "Selected", "source_kind": "result_selection"})

    def _preview(self, dates: dict = NEW):
        return project_dates_job_service.preview_project_dates_change(PROJECT, **dates)

    def test_counts_what_the_change_touches_without_writing(self) -> None:
        before = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        preview = self._preview()
        self.assertEqual(preview["previous_dates"], PREVIOUS)
        self.assertFalse(preview["unchanged"])
        self.assertEqual(
            {key: preview[key] for key in ("classes", "engine_datasets", "calculated_datasets", "methods",
                                           "imported_datasets", "imported_reshaped")},
            {"classes": 1, "engine_datasets": 1, "calculated_datasets": 1, "methods": 2,
             "imported_datasets": 4, "imported_reshaped": 3},
        )
        by_name = {item["name"]: item for item in preview["imported"]}
        self.assertEqual(by_name["Prem Vec"], {"reserving_class": CLASS, "name": "Prem Vec", "reshaped": True,
                                               "off_grid": False, "origins_dropped": 1})
        self.assertTrue(by_name["Off Vec"]["off_grid"])
        self.assertFalse(by_name["Off Vec"]["reshaped"])
        self.assertEqual(by_name["ResQ Tri"]["origins_dropped"], 4)
        self.assertEqual(
            preview["origin_changes"],
            [{"origin_length": 12, "before": 6, "after": 6, "dropped": 1, "dropped_before": 1,
              "dropped_after": 0, "added": 1},
             {"origin_length": 3, "before": 24, "after": 24, "dropped": 4, "dropped_before": 4,
              "dropped_after": 0, "added": 4}],
        )
        after = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_dropped_origins_say_which_side_of_the_new_range_they_fall_on(self) -> None:
        changes = project_dates_job_service._origin_changes
        shrink = changes([12, 3], {"origin_start_date": "201801", "origin_end_date": "202704"},
                         {"origin_start_date": "201801", "origin_end_date": "202701"})
        self.assertEqual([(c["dropped"], c["dropped_before"], c["dropped_after"]) for c in shrink],
                         [(0, 0, 0), (1, 0, 1)])
        # A start moved by one quarter regroups every annual origin: none falls outside the range.
        regroup = changes([12], {"origin_start_date": "201801", "origin_end_date": "202612"},
                          {"origin_start_date": "201804", "origin_end_date": "202612"})
        self.assertEqual((regroup[0]["dropped"], regroup[0]["dropped_before"], regroup[0]["dropped_after"]),
                         (9, 1, 0))

    def test_the_preview_names_the_datasets_the_job_then_reshapes(self) -> None:
        from arcrho_engine import project_dates_jobs

        preview = self._preview()
        for item in preview["imported"]:
            outcome = project_dates_jobs.reshape_input_dataset_file(PROJECT, CLASS, item["name"], PREVIOUS, NEW)
            self.assertEqual(outcome["changed"], item["reshaped"], item["name"])

    def test_every_review_row_names_its_method_type(self) -> None:
        # The panel opens a review row in the project the way the tree does,
        # which needs the row's method type.
        from arcrho_engine import project_dates_jobs

        result = {"review": [], "failures": [], "datasets_reshaped": 0, "methods_reshaped": 0}
        project_dates_jobs._reshape_class(
            PROJECT, CLASS, PREVIOUS, NEW, result,
            inputs_done=set(), mark_input_done=lambda _key: None, mark_new_diagonal=lambda _key: None,
        )
        self.assertTrue(result["review"])
        for item in result["review"]:
            self.assertEqual(
                set(item) - {"needs_new_diagonal"}, {"reserving_class", "name", "kind", "method_type", "reasons"}
            )
            if item["kind"] == "dataset":
                self.assertEqual(item["method_type"], "None")

    def test_an_excel_link_past_the_shrunken_grid_is_counted_on_its_review_row(self) -> None:
        from arcrho_engine import project_dates_jobs

        self._add_dataset(
            "Cutoff",
            {"source_kind": "input", "data_format": "Vector", "period_length": 12,
             "origin_labels": [str(i) for i in range(1, 7)],
             "external_links": [{"reference": "='[Inputs.xlsx]Cutoff'!B2:B7",
                                 "target_cells": [[0, 0, 6, 1, "B2"]]}]},
            [["1"] for _ in range(6)],
            origin_length=12,
        )
        shrink = {**PREVIOUS, "origin_end_date": "202412"}
        result = {"review": [], "failures": [], "datasets_reshaped": 0, "methods_reshaped": 0}
        project_dates_jobs._reshape_class(
            PROJECT, CLASS, PREVIOUS, shrink, result,
            inputs_done=set(), mark_input_done=lambda _key: None, mark_new_diagonal=lambda _key: None,
        )
        by_name = {item["name"]: item for item in result["review"]}
        self.assertEqual(by_name["Cutoff"]["link_rows_past_grid"], 1)
        self.assertNotIn("link_rows_past_grid", by_name["Prem Vec"])

    def test_the_current_dates_change_nothing(self) -> None:
        preview = self._preview(PREVIOUS)
        self.assertTrue(preview["unchanged"])
        self.assertEqual(preview["imported"], [])

    def test_an_unfinished_change_is_previewed_from_its_recorded_dates(self) -> None:
        write_pending_record(
            self.root, project_name=PROJECT, request_id=OTHER_ID, previous_dates=PREVIOUS, dates=NEW
        )
        # The settings already hold the new dates; the pending record keeps the old.
        (self.project_dir / "general_settings.json").write_text(
            json.dumps({"project_name": PROJECT, **NEW}), encoding="utf-8"
        )
        preview = self._preview()
        self.assertTrue(preview["resumed"])
        self.assertFalse(preview["unchanged"])
        self.assertEqual(preview["previous_dates"], PREVIOUS)
        with self.assertRaises(HTTPException) as raised:
            self._preview({**NEW, "development_end_date": "202701"})
        self.assertEqual(raised.exception.status_code, 409)


class NewDiagonalTests(PreviewTests):
    """A hand-entered triangle cannot gain the new diagonal; what reads it waits for it."""

    def _reshape(self, dates=NEW):
        from arcrho_engine import project_dates_jobs

        marked: list = []
        result = {"review": [], "failures": [], "datasets_reshaped": 0, "methods_reshaped": 0}
        project_dates_jobs._reshape_class(
            PROJECT, CLASS, PREVIOUS, dates, result,
            inputs_done=set(), mark_input_done=lambda _key: None, mark_new_diagonal=marked.append,
        )
        return result, marked

    def test_new_cells_stay_blank_never_zero(self) -> None:
        # A zero diagonal would let Berquist-Sherman calculate silently wrong.
        self._reshape()
        csv_path = Path(config.get_project_dataset_cache_dir(PROJECT, CLASS)) / "Hand Tri.csv"
        rows = [line.split(",") for line in csv_path.read_text(encoding="utf-8").splitlines()]
        cells = [cell for row in rows for cell in row]
        self.assertEqual(set(cells), {"1", ""})
        self.assertEqual(rows[-1], [""] * len(rows[-1]))

    def test_a_triangle_that_gains_a_diagonal_is_marked_and_says_so(self) -> None:
        from arcrho_project_dates_job_contract import pending_item_key

        result, marked = self._reshape()
        self.assertEqual(marked, [pending_item_key(CLASS, "Hand Tri"), pending_item_key(CLASS, "ResQ Tri")])
        by_name = {item["name"]: item for item in result["review"]}
        self.assertTrue(by_name["Hand Tri"]["needs_new_diagonal"])
        # A vector has no diagonal; its new origin is listed as before.
        self.assertNotIn("needs_new_diagonal", by_name["Prem Vec"])

    def test_no_diagonal_is_gained_when_the_development_end_stays(self) -> None:
        result, marked = self._reshape({**NEW, "development_end_date": PREVIOUS["development_end_date"]})
        self.assertEqual(marked, [])
        self.assertFalse(any(item.get("needs_new_diagonal") for item in result["review"]))


class RerunTests(PreviewTests):
    """Running the same change again (resume) through the Engine's per-class step.

    A ResQ triangle stored as engine kind cannot be rebuilt from the source
    table, so neither run sends it to the Engine; the rerun leaves anything
    already reshaped exactly as it is and reshapes only what the first run
    never reached.
    """

    def setUp(self) -> None:
        super().setUp()
        from app_server.services import calculated_dataset_service
        from arcrho_engine import source_table_refresh

        self.regenerated: list = []
        self.walk_roots: list = []

        def regenerate(_root, _project, _class, name):
            self.regenerated.append(name)

        def walk(_project, _class, first, _ref, *, additional_roots=(), rebuild_index=False):
            self.walk_roots.append([first, *(name for name, _ in additional_roots)])
            return {"ok": True}

        for item in (
            patch.object(source_table_refresh, "acquire_reserving_class_lease", return_value=object()),
            patch.object(source_table_refresh, "start_reserving_class_lease_heartbeat", return_value=(None, None)),
            patch.object(source_table_refresh, "stop_reserving_class_lease_heartbeat"),
            patch.object(source_table_refresh, "release_reserving_class_lease"),
            patch.object(source_table_refresh, "_regenerate_engine_dataset", side_effect=regenerate),
            patch.object(calculated_dataset_service, "recalculate_dependents", side_effect=walk),
        ):
            item.start()
            self.addCleanup(item.stop)

    def _run_class(self, inputs_done: set):
        from arcrho_engine import project_dates_jobs, source_table_refresh

        result = {"review": [], "failures": [], "datasets_reshaped": 0, "methods_reshaped": 0,
                  "datasets_failed": 0, "datasets_regenerated": 0, "methods_updated": 0,
                  "dependent_problems": [], "expected_problems": []}
        self.regenerated.clear()
        source_table_refresh._refresh_one_reserving_class(
            self.root, PROJECT, CLASS, result,
            on_dataset=lambda _name: None,
            prepare=lambda: project_dates_jobs._reshape_class(
                PROJECT, CLASS, PREVIOUS, NEW, result,
                inputs_done=inputs_done, mark_input_done=inputs_done.add, mark_new_diagonal=lambda _key: None,
            ),
        )
        return result

    def _stored(self) -> dict:
        return {
            path.relative_to(self.project_dir).as_posix(): path.read_bytes()
            for path in self.project_dir.rglob("*")
            if path.is_file() and path.suffix in {".csv", ".json"} and path.name != "index.json"
        }

    def _csv(self, name: str) -> str:
        return (Path(config.get_project_dataset_cache_dir(PROJECT, CLASS)) / f"{name}.csv").read_text(encoding="utf-8")

    def test_an_already_reshaped_resq_triangle_is_left_alone_and_never_regenerated(self) -> None:
        from arcrho_project_dates_job_contract import pending_item_key

        inputs_done: set = set()
        first = self._run_class(inputs_done)
        self.assertEqual(self.regenerated, ["Paid"])
        self.assertEqual(first["failures"], [])
        self.assertIn(pending_item_key(CLASS, "ResQ Tri"), inputs_done)
        after_first = self._stored()

        second = self._run_class(inputs_done)
        # The rerun regenerates only the real engine dataset and moves nothing twice.
        self.assertEqual(self.regenerated, ["Paid"])
        self.assertEqual(second["failures"], [])
        self.assertEqual(second["datasets_failed"], 0)
        self.assertEqual((second["datasets_reshaped"], second["methods_reshaped"]), (0, 0))
        self.assertEqual(self._stored(), after_first)
        self.assertEqual(self.walk_roots[-1], ["Paid"])

    def test_a_resq_triangle_the_first_run_never_reached_is_reshaped_once(self) -> None:
        from arcrho_project_dates_job_contract import pending_item_key

        before = self._csv("ResQ Tri")
        # The first run stopped after the hand-entered triangle.
        inputs_done = {pending_item_key(CLASS, "Hand Tri")}
        hand_before = self._csv("Hand Tri")
        resumed = self._run_class(inputs_done)
        self.assertEqual(self.regenerated, ["Paid"])
        self.assertEqual(resumed["failures"], [])
        self.assertNotEqual(self._csv("ResQ Tri"), before)
        self.assertEqual(self._csv("Hand Tri"), hand_before)
        self.assertIn("ResQ Tri", self.walk_roots[-1])
        # Dropped origins go; the new ones start blank, never zero.
        rows = self._csv("ResQ Tri").splitlines()
        self.assertEqual(len(rows), 24)
        self.assertEqual(rows[:20], ["1"] * 20)
        self.assertEqual(rows[20:], [""] * 4)
        once = self._stored()

        again = self._run_class(inputs_done)
        self.assertEqual(self.regenerated, ["Paid"])
        self.assertEqual(again["datasets_reshaped"], 0)
        self.assertEqual(self._stored(), once)


class ExpectedWalkFailureTests(_Workspace):
    """Which declined dependents of a class walk the dates change expects."""

    def setUp(self) -> None:
        super().setUp()
        from arcrho_project_dates_job_contract import pending_item_key

        self.blank = {pending_item_key(CLASS, "Hand Tri")}
        self._add_dataset("Tri B&S", {"source_kind": "berquist_sherman_cra",
                                      "precedents": [{"dataset_name": "Hand Tri"}, {"dataset_name": "Paid"}]})
        self._add_dataset("Other B&S", {"source_kind": "berquist_sherman_cra",
                                        "precedents": [{"dataset_name": "Other Tri"}, {"dataset_name": "Paid"}]})

    def _expected(self, walk, blank=None):
        from arcrho_engine import project_dates_jobs

        return project_dates_jobs.expected_walk_failures(
            PROJECT, CLASS, walk, self.blank if blank is None else blank
        )

    def test_a_shape_refusal_over_a_blank_diagonal_and_what_it_alone_stopped(self) -> None:
        shape = "paid_claims[0] must match the primary triangle row length."
        walk = {
            "ok": False,
            "skipped": [
                {"dataset_type_name": "Severity", "errors": [
                    "Skipped because an upstream calculated dependency did not refresh: Net, Adjusted DFM"]},
            ],
            "berquist_sherman_updates": {"ok": False, "errors": [
                {"dataset_name": "Tri B&S", "reason": shape},
                # The same refusal over a triangle this change did not leave blank is real.
                {"dataset_name": "Other B&S", "reason": shape},
            ]},
            "dfm_updates": {"ok": False, "errors": [
                {"dataset_name": "Net, Adjusted DFM", "reason": "Precedent refresh failed: Tri B&S"},
                {"dataset_name": "BS DFM 2", "reason": "Precedent refresh failed: Other B&S"},
                {"dataset_name": "H 02 DFM", "reason": "422: DFM input values are missing for previously excluded ratio cells."},
            ]},
            "result_selection_updates": {"ok": False, "errors": [
                {"dataset_name": "F 92 Selected", "reason": "Precedent refresh failed: Net, Adjusted DFM"},
                # Stopped by an expected and by a real failure: still a problem.
                {"dataset_name": "F 91 Indicated", "reason": "Precedent refresh failed: Net, Adjusted DFM, H 02 DFM"},
            ]},
        }
        self.assertEqual(
            self._expected(walk),
            {"Tri B&S", "Net, Adjusted DFM", "F 92 Selected", "Severity"},
        )

    def test_another_refusal_over_the_same_triangle_is_not_expected(self) -> None:
        walk = {"ok": False, "berquist_sherman_updates": {"ok": False, "errors": [
            {"dataset_name": "Tri B&S", "reason": "422: BF new_ultimate does not match the embedded source snapshots."},
        ]}}
        self.assertEqual(self._expected(walk), set())

    def test_nothing_is_expected_in_a_class_with_no_blank_diagonal(self) -> None:
        walk = {"ok": False, "berquist_sherman_updates": {"ok": False, "errors": [
            {"dataset_name": "Tri B&S", "reason": "paid_claims[0] must match the primary triangle row length."},
        ]}}
        self.assertEqual(self._expected(walk, blank={"a\\two|hand tri"}), set())


class PrecedentOriginLabelTests(_Workspace):
    """Methods read their precedents on the new origins while a change is unfinished."""

    OLD_YEARS = [str(year) for year in range(2020, 2026)]
    NEW_YEARS = [str(year) for year in range(2021, 2027)]

    def _labels(self, labels, rows):
        from app_server.services import precedent_cache_service

        return precedent_cache_service.precedent_origin_labels(PROJECT, labels, 12, rows)

    def test_a_method_keeps_its_saved_labels_when_no_change_is_unfinished(self) -> None:
        self.assertEqual(self._labels(self.OLD_YEARS, 6), self.OLD_YEARS)

    def test_mid_change_the_rows_take_the_new_origins_at_the_same_count(self) -> None:
        write_pending_record(
            self.root, project_name=PROJECT, request_id=OTHER_ID, previous_dates=PREVIOUS, dates=NEW
        )
        self.assertEqual(self._labels(self.OLD_YEARS, 6), self.NEW_YEARS)
        # Already moved, or not the previous grid: the saved labels stand.
        self.assertEqual(self._labels(self.NEW_YEARS, 6), self.NEW_YEARS)
        self.assertEqual(self._labels(["1", "2", "3", "4", "5", "6"], 6), ["1", "2", "3", "4", "5", "6"])


class RouteTransportTests(unittest.TestCase):
    def test_the_preview_and_status_go_through_hosted_reads(self) -> None:
        calls = []

        def run_workspace_read(kind, kwargs, *, local):
            calls.append((kind, dict(kwargs)))
            return {"ok": True}

        with patch.object(
            project_settings_router.workspace_read_client, "run_workspace_read", side_effect=run_workspace_read
        ):
            project_settings_router.preview_project_dates_change(PROJECT, "202101", "202612", "202612")
            project_settings_router.get_project_dates_change_status(PROJECT, REQUEST_ID)
        self.assertEqual(
            calls,
            [
                ("project_dates_preview", {"project_name": PROJECT, **NEW}),
                ("project_dates_job_status", {"project_name": PROJECT, "job_id": REQUEST_ID}),
            ],
        )

    def test_the_submit_goes_through_the_hosted_mutation(self) -> None:
        captured = {}

        def run_workspace_mutation(kind, kwargs, *, local, request_id=None):
            captured.update(kind=kind, kwargs=dict(kwargs))
            return {"ok": True, "job_id": kwargs["request_id"], "status": "queued", "resumed": False}

        with patch.object(
            project_settings_router.workspace_mutation_client,
            "run_workspace_mutation",
            side_effect=run_workspace_mutation,
        ):
            response = project_settings_router.submit_project_dates_change(
                ProjectDatesChangeRequest(project_name=PROJECT, request_id=REQUEST_ID, **NEW)
            )
        self.assertEqual(response["job_id"], REQUEST_ID)
        self.assertEqual(captured["kind"], "project_dates_change_submit")
        self.assertEqual(captured["kwargs"], {"project_name": PROJECT, "request_id": REQUEST_ID, **NEW})


if __name__ == "__main__":
    unittest.main()
