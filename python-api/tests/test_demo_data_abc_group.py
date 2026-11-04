"""The ABC Insurance Group demo tables: reproducible, internally consistent, plausible.

``arcrho_api.demo_data.abc_group`` writes the four import tables of the demo
project. These tests pin what makes them usable as a demo: the same seed gives
the same files, every written row keeps the loss and count identities, the
newly entered states start when the book says they do, and the loss ratios and
development look like insurance data.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arcrho_api.demo_data import abc_group  # noqa: E402

TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
KEYS = len(abc_group.KEY_COLUMNS) + 1
LOSS = {name: KEYS + i for i, name in enumerate(abc_group.LOSS_COLUMNS)}
COUNT = {name: KEYS + i for i, name in enumerate(abc_group.COUNT_COLUMNS)}


class AbcGroupTablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = abc_group.generate()

    def test_same_seed_writes_identical_files(self) -> None:
        again = abc_group.generate()
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as first, \
                tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as second:
            one = abc_group.write_tables(self.tables, Path(first))
            two = abc_group.write_tables(again, Path(second))
            for name in abc_group.TABLE_FILES:
                self.assertEqual(one[name].read_bytes(), two[name].read_bytes(), name)
        self.assertNotEqual(abc_group.generate(seed=7).loss[:50], self.tables.loss[:50])

    def test_every_loss_row_keeps_the_identities(self) -> None:
        for row in self.tables.loss:
            self.assertAlmostEqual(row[LOSS["recovery"]], row[LOSS["salvage"]] + row[LOSS["subro"]], places=2)
            self.assertAlmostEqual(row[LOSS["gross_incurred"]], row[LOSS["gross_paid"]] + row[LOSS["reserve"]], places=2)
            self.assertAlmostEqual(row[LOSS["net_incurred"]], row[LOSS["gross_incurred"]] + row[LOSS["recovery"]], places=2)
            self.assertLessEqual(row[LOSS["salvage"]], 0)
            self.assertLessEqual(row[LOSS["subro"]], 0)
            self.assertGreaterEqual(row[LOSS["gross_paid"]], 0)

    def test_cumulative_counts_and_capped_losses_stay_consistent(self) -> None:
        reported = defaultdict(int)
        closed = defaultdict(int)
        for row in sorted(self.tables.claim_counts, key=lambda r: (r[:KEYS - 1], r[KEYS - 1])):
            key = tuple(row[:KEYS - 1])
            reported[key] += row[COUNT["reported"]]
            closed[key] += row[COUNT["CWP"]] + row[COUNT["CWOP"]]
            self.assertGreaterEqual(reported[key], closed[key], key)
            self.assertTrue(all(isinstance(row[i], int) for i in COUNT.values()))
        net = defaultdict(float)
        capped = defaultdict(float)
        for row in sorted(self.tables.loss, key=lambda r: (r[:KEYS - 1], r[KEYS - 1])):
            key = tuple(row[:KEYS - 1])
            net[key] += row[LOSS["net_incurred"]]
            capped[key] += row[LOSS["net_incurred_capped_50k"]]
        for key in net:
            self.assertLessEqual(capped[key], net[key] + 1.0, key)

    def test_new_states_start_at_entry_and_losses_stop_at_the_valuation(self) -> None:
        entry = {(book.line, book.state): book.entry_month for book in abc_group.BOOKS}
        for row in self.tables.loss + self.tables.premium:
            self.assertGreaterEqual(row[5], entry[(row[1], row[2])])
        self.assertEqual(max(row[6] for row in self.tables.loss), abc_group.VALUATION_MONTH)
        self.assertEqual(max(row[5] for row in self.tables.premium), abc_group.LAST_PREMIUM_MONTH)
        massachusetts = {row[5] // 100 for row in self.tables.loss if row[2] == "MA"}
        self.assertEqual(min(massachusetts), 2023)

    def test_loss_ratios_and_development_look_like_insurance(self) -> None:
        premium = defaultdict(float)
        for row in self.tables.premium:
            premium[(row[1], row[5] // 100)] += row[-1]
        incurred = defaultdict(float)
        paid_by_age = defaultdict(float)
        incurred_by_age = defaultdict(float)
        for row in self.tables.loss:
            if row[4].endswith("Cat"):
                continue
            year = row[5] // 100
            incurred[(row[1], year)] += row[LOSS["net_incurred"]]
            if row[1] == "PPA" and row[4] == "Bodily Injury" and year <= 2020:
                age = (row[6] // 100 - year) * 12 + row[6] % 100
                for horizon in (12, 24):
                    if age <= horizon:
                        paid_by_age[horizon] += row[LOSS["gross_paid"]]
                        incurred_by_age[horizon] += row[LOSS["net_incurred"]]
        for year in range(2017, 2024):
            ratio = incurred[("PPA", year)] / premium[("PPA", year)]
            self.assertTrue(0.45 < ratio < 0.85, (year, ratio))
        self.assertTrue(1.6 < paid_by_age[24] / paid_by_age[12] < 4.0)
        self.assertTrue(1.05 < incurred_by_age[24] / incurred_by_age[12] < 1.4)

    def test_aggregate_members_leave_out_reporting_subsets(self) -> None:
        self.assertEqual(abc_group.reserving_class_members(5, "Comp ex Cat"), {"Comprehensive"})
        self.assertEqual(
            abc_group.reserving_class_members(5, "BI Total"),
            {"Bodily Injury", "Uninsured Motorist BI", "Bodily Injury Limited Tort",
             "Uninsured Motorist BI Limited Tort"},
        )
        self.assertEqual(abc_group.reserving_class_members(1, "ABC Auto"), {"ABC Casualty Co", "ABC Insurance Co"})


if __name__ == "__main__":
    unittest.main()
