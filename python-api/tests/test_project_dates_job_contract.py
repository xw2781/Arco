"""The project dates job contract and the date-to-label rules it relies on
(docs/plans/project_dates_panel.md, step 4)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api.period_reshape import (  # noqa: E402
    development_ages,
    origin_start_months,
    project_dates_development_labels,
    project_dates_origin_plan,
    reshape_input_dataset,
)
from arcrho_project_dates_job_contract import (  # noqa: E402
    ProjectDatesJobContractError,
    build_project_dates_job_request,
    build_project_dates_job_status,
    read_pending_record,
    validate_project_dates_job_status,
    write_pending_record,
)


FAKE = {"origin_start_date": "201701", "origin_end_date": "202612", "development_end_date": "202605"}
LATER = {"origin_start_date": "201701", "origin_end_date": "202612", "development_end_date": "202612"}
JANUARY = {"origin_start_date": "201801", "origin_end_date": "202712", "development_end_date": "202801"}


def _request(**dates):
    values = {"origin_start_date": "201701", "origin_end_date": "202612", "development_end_date": "202612"}
    values.update(dates)
    return build_project_dates_job_request(
        request_id="abc123",
        project_name="Demo Project",
        origin_start_date=values["origin_start_date"],
        origin_end_date=values["origin_end_date"],
        development_end_date=values["development_end_date"],
        user_name="Test User",
    )


class DateRuleTests(unittest.TestCase):
    def test_start_end_and_development_end_must_be_in_order(self) -> None:
        self.assertEqual(_request()["DevelopmentEndDate"], "202612")
        self.assertEqual(_request(origin_start_date="202612")["OriginStartDate"], "202612")
        for dates, message in (
            ({"origin_start_date": "202701"}, "Origin Start Date must not be after Origin End Date"),
            ({"development_end_date": "202611"}, "Origin End Date must not be after Development End Date"),
            ({"origin_end_date": "202613"}, "Origin End Date must be a month"),
        ):
            with self.subTest(dates=dates):
                with self.assertRaisesRegex(ProjectDatesJobContractError, message):
                    _request(**dates)

    def test_a_status_records_previous_dates_that_predate_the_rule(self) -> None:
        # The Fake project ends its origins after its development end; that is
        # what it is moved from, so the status records it as it was.
        status = build_project_dates_job_status(
            "abc123",
            "processing",
            progress={"stage": "saving", "completed": 0, "total": 0, "label": "Saving"},
            previous_dates=FAKE,
        )
        self.assertEqual(validate_project_dates_job_status(status)["previous_dates"], FAKE)

    def test_the_pending_record_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(read_pending_record(temp, "Demo Project"))
            write_pending_record(
                temp,
                project_name="Demo Project",
                request_id="abc123",
                previous_dates=FAKE,
                dates=LATER,
                classes_done=["A\\One"],
                inputs_done=["a\\two|c 82"],
            )
            record = read_pending_record(temp, "demo project")
        self.assertEqual(record["previous_dates"], FAKE)
        self.assertEqual(record["dates"], LATER)
        self.assertEqual((record["classes_done"], record["inputs_done"]), (["A\\One"], ["a\\two|c 82"]))


class DateLabelTests(unittest.TestCase):
    def test_a_quarter_boundary_adds_development_columns_and_keeps_the_origins(self) -> None:
        old = [f"{age}m" for age in development_ages("201701", "202605", 3)]
        self.assertEqual((len(old), old[0], old[-1]), (38, "2m", "113m"))
        new = project_dates_development_labels(old, 3, FAKE, LATER)
        self.assertEqual((len(new), new[0], new[-1]), (40, "3m", "120m"))
        # An annual triangle keeps its count and moves its ages.
        annual = [f"{age}m" for age in development_ages("201701", "202605", 12)]
        self.assertEqual(project_dates_development_labels(annual, 12, FAKE, LATER)[:2], ["12m", "24m"])
        # Columns that are not the old dates' ages are left alone.
        self.assertIsNone(project_dates_development_labels(old[:-1], 3, FAKE, LATER))

    def test_origins_match_by_true_origin_in_their_own_spelling(self) -> None:
        quarters = [f"{year} Q{quarter}" for year in range(2017, 2027) for quarter in range(1, 5)]
        plan = project_dates_origin_plan(quarters, 3, FAKE, JANUARY)
        self.assertEqual(plan["style"], "quarter")
        self.assertEqual(plan["dropped"], 4)
        self.assertEqual(plan["labels"][0], "2018 Q1")
        self.assertEqual(plan["labels"][-1], "2027 Q4")
        months = [f"{name} 2017" for name in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")]
        self.assertEqual(project_dates_origin_plan(months, 1, {**FAKE, "origin_end_date": "201712"}, {**FAKE, "origin_end_date": "201712"})["style"], "month_name")

    def test_index_labels_find_their_true_origin_from_the_previous_dates(self) -> None:
        stored = [str(index + 1) for index in range(len(origin_start_months("201701", "202612", 1)))]
        plan = project_dates_origin_plan(stored, 1, FAKE, JANUARY)
        self.assertEqual(plan["style"], "index")
        # Row 13 (Jan 2018) is the first row under the new dates.
        self.assertEqual(plan["old"][12], plan["new"][0])
        self.assertEqual(plan["labels"], [str(index + 1) for index in range(120)])
        self.assertEqual(plan["dropped"], 12)

    def test_labels_off_the_old_grid_are_not_guessed(self) -> None:
        self.assertIsNone(project_dates_origin_plan(["1", "2", "3"], 3, FAKE, LATER))
        self.assertIsNone(project_dates_origin_plan(["2016", "2017"], 12, FAKE, LATER))

    def test_a_finer_stored_grid_is_widened_not_cut_to_its_display_labels(self) -> None:
        # A triangle labelled at 12 months whose CSV holds monthly columns.
        sidecar = {"origin_labels": ["2017", "2018"], "development_labels": ["5m", "17m"]}
        values = [["1"] * 113, ["2"] * 101]
        out = reshape_input_dataset(
            sidecar, values, ["2017", "2018"], ["2017", "2018"], ["12m", "24m"], column_count=120
        )
        self.assertEqual([len(row) for row in out["values"]], [120, 120])
        self.assertEqual(out["values"][0][112:114], ["1", None])
        self.assertEqual(out["sidecar"]["development_labels"], ["12m", "24m"])


if __name__ == "__main__":
    unittest.main()
