"""The Fake project's synthetic source table: its shape, its identities and its plausibility."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from collections import defaultdict
from contextlib import redirect_stdout
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.generate_fake_project_source import HEADER, generate, main, read_template  # noqa: E402

TEST_TEMP_ROOT = REPOSITORY_ROOT / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)

KEY_WIDTH = 5
CENT = 0.005
REGULAR_KEYS = [
    ("PIC2", "PA", "NJ", "Partners", category) for category in ("BI", "PD", "UMPD", "COL", "CMP")
] + [("HPPREF", "HO", "NJ", "Legacy", category) for category in ("HOP", "HOL")]
CAT_KEYS = [("PIC2", "PA", "NJ", "Partners", "CMP_CAT"), ("HPPREF", "HO", "NJ", "Legacy", "HOP_CAT")]
LOSS_ONLY_KEY = ("HPPROP2", "PA", "NJ", "Independent", "PIP")  # one stray month in the extract
BUDGET_KEYS = [("PRNJ - PA", "PA", "NJ", "Partners", "PD+UMPD"), ("PRNJ - HO+DF", "HO+DF", "NJ", "Legacy", "HOPxCAT")]


def _months(first: int, last: int) -> list[int]:
    months, month = [], first
    while month <= last:
        months.append(month)
        month = month + 1 if month % 100 < 12 else (month // 100 + 1) * 100 + 1
    return months


def write_template(path: Path) -> None:
    """A few key combinations laid out the way the real extract lays them out."""
    blank_losses = [""] * (len(HEADER) - 7 - 4)
    loss_row = lambda key, acc, dev: [*key, f"{acc}.0", str(dev), *["0.0"] * len(blank_losses), "", "", "", ""]
    rows = []
    for key in REGULAR_KEYS:
        rows += [loss_row(key, 201701, 201701), loss_row(key, 202605, 202605)]
    for key in CAT_KEYS:
        rows += [loss_row(key, 201803, 201803), loss_row(key, 202605, 202605)]
    rows.append(loss_row(LOSS_ONLY_KEY, 201802, 201802))
    for key in REGULAR_KEYS:
        rows += [[*key, f"{month}.0", "0", *blank_losses, "1.0", "1.0", "", ""] for month in _months(201701, 202605)]
    for key in BUDGET_KEYS:
        rows += [[*key, f"{month}.0", "0", *blank_losses, "", "", "0.0", "0.0"] for month in _months(202602, 202612)]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def identity_problems(rows: list[dict[str, str]]) -> list[str]:
    """Every identity the table must satisfy, row by row and on cumulative figures."""
    problems = []
    number = lambda row, name: float(row[name])
    by_origin = defaultdict(list)
    for row in rows:
        if row["sys_yrmo"] == "0":
            for name in ("Earned_Premium", "Earned_Exposure", "Remaining_Budget_Premium", "Remaining_Budget_Exposure"):
                if row[name] != "" and float(row[name]) < 0:
                    problems.append(f"negative {name}: {row}")
            continue
        by_origin[tuple(row[column] for column in HEADER[:6])].append(row)
    counts = ("CWP", "CWOP", "CWP_ex_50k", "CWP_ex_100k", "CWP_ex_1000k",
              "reported", "reported_ex_50k", "reported_ex_100k", "reported_ex_1000k")
    sums = ("gross_paid", "reserve", "salvage", "subro", "recovery", "net_incurred", "gross_incurred", *counts,
            *(f"net_{basis}_capped_{cap}" for basis in ("incurred", "paid") for cap in ("50k", "100k", "1000k")))
    for origin, origin_rows in by_origin.items():
        total = dict.fromkeys(sums, 0.0)
        for row in sorted(origin_rows, key=lambda r: int(r["sys_yrmo"])):
            where = f"{origin} {row['sys_yrmo']}"
            if abs(number(row, "gross_incurred") - number(row, "gross_paid") - number(row, "reserve")) > CENT:
                problems.append(f"incurred != paid + reserve at {where}")
            if abs(number(row, "recovery") - number(row, "salvage") - number(row, "subro")) > CENT:
                problems.append(f"recovery != salvage + subro at {where}")
            if abs(number(row, "net_incurred") - number(row, "gross_incurred") - number(row, "recovery")) > CENT:
                problems.append(f"net != gross + recovery at {where}")
            for name in counts:
                if not row[name].lstrip("-").isdigit():
                    problems.append(f"{name} is not a whole number at {where}")
            for name in ("CWP", "CWOP", "reported"):
                if number(row, name) < 0:
                    problems.append(f"{name} decreases at {where}")
            for name in sums:
                total[name] += number(row, name)
            net_paid = total["gross_paid"] + total["recovery"]
            chains = [
                (total["salvage"], 0.0, "salvage above zero"),
                (total["subro"], 0.0, "subrogation above zero"),
                (0.0, total["gross_paid"], "paid below zero"),
                (0.0, total["reserve"], "case reserve below zero"),
                (total["CWP"] + total["CWOP"], total["reported"], "pending below zero"),
                (total["net_incurred_capped_1000k"], total["net_incurred"], "1M capped incurred above net"),
                (total["net_paid_capped_1000k"], net_paid, "1M capped paid above net"),
                (total["CWP_ex_50k"], total["CWP"], "excess CWP above CWP"),
                (total["reported_ex_50k"], total["reported"], "excess reported above reported"),
            ]
            for basis in ("incurred", "paid"):
                chains += [(total[f"net_{basis}_capped_50k"], total[f"net_{basis}_capped_100k"], f"50K above 100K {basis}"),
                           (total[f"net_{basis}_capped_100k"], total[f"net_{basis}_capped_1000k"], f"100K above 1M {basis}")]
            for kind in ("CWP_ex", "reported_ex"):
                chains += [(total[f"{kind}_1000k"], total[f"{kind}_100k"], f"{kind} 1M above 100K"),
                           (total[f"{kind}_100k"], total[f"{kind}_50k"], f"{kind} 100K above 50K"),
                           (0.0, total[f"{kind}_1000k"], f"{kind} below zero")]
            problems += [f"{text} at {where}" for low, high, text in chains if low > high + CENT]
    return problems


def annual_figures(rows: list[dict[str, str]]):
    """Accident-year earned premium, and incurred and paid by age in months."""
    premium = defaultdict(float)
    losses = defaultdict(float)
    for row in rows:
        year = int(float(row["acc_yrmo"])) // 100
        if row["sys_yrmo"] == "0":
            premium[year] += float(row["Earned_Premium"] or 0)
            continue
        dev = int(row["sys_yrmo"])
        age = (dev // 100 - year) * 12 + dev % 100
        for name in ("gross_incurred", "gross_paid"):
            for limit in (12, 24, 10_000):
                if age <= limit:
                    losses[(name, year, limit)] += float(row[name])
    return premium, losses


class GenerateFakeProjectSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        root = Path(cls.temp.name)
        cls.template = root / "template.csv"
        write_template(cls.template)
        cls.output = root / "generated.csv"
        with redirect_stdout(io.StringIO()):
            main(["--template", str(cls.template), "--output", str(cls.output)])
        cls.rows = read_rows(cls.output)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_keeps_the_header_keys_and_months(self) -> None:
        with self.output.open(encoding="utf-8", newline="") as stream:
            self.assertEqual(tuple(next(csv.reader(stream))), HEADER)
        written = read_template(self.output)
        template = read_template(self.template)
        self.assertEqual(set(written), set(template))
        for key, shape in template.items():
            self.assertEqual(written[key].premium, shape.premium, key)
            self.assertEqual(written[key].budget, shape.budget, key)
            if shape.loss is None:
                self.assertIsNone(written[key].loss, key)
                continue
            self.assertTrue(written[key].loss and shape.loss[0] <= written[key].loss[0]
                            <= written[key].loss[1] <= shape.loss[1], key)

    def test_every_identity_holds(self) -> None:
        self.assertEqual(identity_problems(self.rows)[:5], [])

    def test_catastrophe_claims_are_a_subset_of_their_coverage(self) -> None:
        for cat_key in CAT_KEYS:
            parent = (*cat_key[:4], cat_key[4].replace("_CAT", ""))
            total = defaultdict(float)
            for row in self.rows:
                key = tuple(row[c] for c in HEADER[:KEY_WIDTH])
                if row["sys_yrmo"] != "0" and key in (cat_key, parent):
                    total[key] += float(row["reported"])
            self.assertGreater(total[cat_key], 0, cat_key)
            self.assertLess(total[cat_key], total[parent], cat_key)

    def test_budget_rows_project_the_members_premium_after_the_valuation(self) -> None:
        budget = [row for row in self.rows if row["Remaining_Budget_Premium"] != ""]
        self.assertTrue(all(float(row["Remaining_Budget_Premium"]) == 0 for row in budget
                            if float(row["acc_yrmo"]) <= 202605))
        self.assertTrue(all(float(row["Remaining_Budget_Premium"]) > 0 for row in budget
                            if float(row["acc_yrmo"]) > 202605))

    def test_same_seed_writes_the_same_file(self) -> None:
        again = Path(self.temp.name) / "again.csv"
        with redirect_stdout(io.StringIO()):
            main(["--template", str(self.template), "--output", str(again)])
        self.assertEqual(again.read_bytes(), self.output.read_bytes())
        self.assertNotEqual(generate(read_template(self.template), seed=1)[:50], generate(read_template(self.template))[:50])

    def test_a_roll_forward_keeps_every_earlier_row_and_adds_the_months_after(self) -> None:
        rolled_path = Path(self.temp.name) / "rolled.csv"
        with redirect_stdout(io.StringIO()):
            main(["--template", str(self.template), "--output", str(rolled_path),
                  "--roll-forward-from", "202605", "--valuation", "202608"])
        rolled = read_rows(rolled_path)
        row_key = lambda row: tuple(row[column] for column in HEADER)
        is_loss = lambda row: row["sys_yrmo"] != "0"
        is_premium = lambda row: row["sys_yrmo"] == "0" and row["Earned_Premium"] != ""

        # The earlier table's loss and premium rows are all still there, unchanged.
        self.assertEqual(
            sorted(row_key(row) for row in rolled if is_loss(row) and int(row["sys_yrmo"]) <= 202605),
            sorted(row_key(row) for row in self.rows if is_loss(row)),
        )
        self.assertEqual(
            sorted(row_key(row) for row in rolled if is_premium(row) and float(row["acc_yrmo"]) <= 202605),
            sorted(row_key(row) for row in self.rows if is_premium(row)),
        )

        # What is new is the three months after it: development, new accident months, and premium.
        later = [row for row in rolled if is_loss(row) and int(row["sys_yrmo"]) > 202605]
        self.assertEqual({row["sys_yrmo"] for row in later}, {"202606", "202607", "202608"})
        self.assertTrue(any(float(row["acc_yrmo"]) <= 202605 for row in later), "earlier claims keep developing")
        self.assertEqual({row["acc_yrmo"] for row in later if float(row["acc_yrmo"]) > 202605},
                         {"202606.0", "202607.0", "202608.0"})
        self.assertEqual({row["acc_yrmo"] for row in rolled if is_premium(row) and float(row["acc_yrmo"]) > 202605},
                         {"202606.0", "202607.0", "202608.0"})
        self.assertEqual(identity_problems(rolled)[:5], [])
        budget = [row for row in rolled if row["Remaining_Budget_Premium"] != ""]
        self.assertTrue(all(float(row["Remaining_Budget_Premium"]) == 0 for row in budget
                            if float(row["acc_yrmo"]) <= 202608))
        self.assertTrue(all(float(row["Remaining_Budget_Premium"]) > 0 for row in budget
                            if float(row["acc_yrmo"]) > 202608))

        with self.assertRaises(ValueError):
            generate(read_template(self.template), valuation_month=202605, roll_forward_from=202608)

    def test_loss_ratios_and_first_link_ratios_are_plausible(self) -> None:
        premium, losses = annual_figures(self.rows)
        for year in range(2017, 2024):
            ratio = losses[("gross_incurred", year, 10_000)] / premium[year]
            self.assertTrue(0.45 <= ratio <= 0.9, f"{year} loss ratio {ratio:.2f}")
            incurred = losses[("gross_incurred", year, 24)] / losses[("gross_incurred", year, 12)]
            paid = losses[("gross_paid", year, 24)] / losses[("gross_paid", year, 12)]
            self.assertTrue(0.95 <= incurred <= 1.4, f"{year} incurred 12-24 {incurred:.2f}")
            self.assertTrue(1.1 <= paid <= 2.0, f"{year} paid 12-24 {paid:.2f}")


if __name__ == "__main__":
    unittest.main()
