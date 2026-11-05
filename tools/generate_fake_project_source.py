"""Write a synthetic source table for the NJ_Annual_Prod_202605_Fake project.

The table keeps the shape of the project's current source extract, which is
read as a template for its structure only: the 34 columns, every key
combination, and for each combination the months its loss, earned-premium and
remaining-budget rows cover. Every figure is new, simulated claim by claim with
the ABC demo generator's model (``arcrho_api.demo_data.abc_group``): Poisson
frequency, lognormal severity with trend and large losses, report and
settlement lags, case reserves, salvage and subrogation, shared shocks, COVID-19
and catastrophe months.

The figures hold together by construction, on cumulative values per key and
accident month:

- incurred = paid + case reserve, recovery = salvage + subrogation (both
  negative), net incurred = gross incurred + recovery;
- net capped at 50K <= 100K <= 1M <= net, for incurred and for paid;
- counts are whole numbers; pending (reported - CWP - CWOP) never goes
  negative, and every excess count is at most its total;
- a "Cat" coverage holds a subset of its parent coverage's claims.

Rates target a loss ratio of about 0.55-0.72 per key combination, moved by the
demo's rate-adequacy cycle. Remaining budget premium and exposure for an
aggregate key (a "PRNJ - " company, an "HO+DF" product, an "MP+PIP" category)
is the projected premium of the keys it adds up, zero up to the valuation.

Run ``py -3.10 tools/generate_fake_project_source.py --template <current csv>
--output <new csv>``. The same template and seed always write the same file.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "python-api" / "src"))

from arcrho_api.demo_data import abc_group as model  # noqa: E402

DEFAULT_SEED = 20261104
VALUATION_MONTH = 202605

KEY_COLUMNS = ("CO_CD", "PROD_CD", "STATE_CD", "CHANNEL", "IBNRCAT")
PREMIUM_COLUMNS = ("Earned_Premium", "Earned_Exposure")
BUDGET_COLUMNS = ("Remaining_Budget_Premium", "Remaining_Budget_Exposure")
HEADER = (*KEY_COLUMNS, "acc_yrmo", "sys_yrmo", *model.LOSS_COLUMNS, *model.COUNT_COLUMNS,
          *PREMIUM_COLUMNS, *BUDGET_COLUMNS)
PREMIUM_ROW_SYS = "0"  # premium and budget rows carry this development month
BASE_LOSS = ("gross_paid", "expense", "salvage", "subro", "reserve")

# ---------------------------------------------------------------- coverages

CAT_PARENT = {"CMP_CAT": "CMP", "HOP_CAT": "HOP"}
EXTRA_COVERAGES = {row[0]: model.Coverage(*row) for row in (
    ("Oil Tank", 0.0008, 32000, 1.00, 6.0, 1.2, 10, 0.30, 0.15, 0.0, 0.0, 0.04, "property", 0.55),
    ("Foundation", 0.0020, 60000, 0.70, 18.0, 1.0, 8, 0.50, 0.08, 0.0, 0.0, 0.05, "property", 0.55),
    ("Umbrella", 0.0006, 120000, 1.30, 6.0, 1.4, 30, 0.45, 0.20, 0.0, 0.010, 0.06, "liability", 0.50),
)}
COVERAGE_NAME = {
    "BI": "Bodily Injury", "BIR51": "Bodily Injury Limited Tort", "UMBI": "Uninsured Motorist BI",
    "UMBIR51": "Uninsured Motorist BI Limited Tort", "PD": "Property Damage", "UMPD": "Uninsured Motorist PD",
    "MP": "Medical Payments", "MP_HCP": "Medical Payments", "PIP": "Personal Injury Protection",
    "PIP_HCP": "Personal Injury Protection", "COL": "Collision", "CMP": "Comprehensive",
    "HOP": "Home Property", "HOL": "Home Liability", "OIL": "Oil Tank", "FNDTN": "Foundation",
    "UMBR": "Umbrella", "ALN_UMBR": "Umbrella",
}
# Health-care-primary policies: the health insurer pays first.
HCP_CATEGORIES = {"MP_HCP", "PIP_HCP"}
HCP_FREQUENCY, HCP_SEVERITY = 0.7, 0.45
# Commercial auto against personal auto.
COMMERCIAL_FREQUENCY, COMMERCIAL_SEVERITY = 1.4, 1.8
# The demo's simulation line for each product: it decides COVID-19 and shocks.
SIMULATION_LINE = {"PA": "PPA", "CA": "PPA", "MC": "MC", "HO": "HO", "DF": "DF", "HO+DF": "HO", "PCAT": "PCAT"}
STATE_ALIAS = {"Penn": "PA"}

# Aggregate keys that appear only on remaining-budget rows: what they add up.
BUDGET_CATEGORY_MEMBERS = {
    "BI Total": ("BI", "BIR51", "UMBI", "UMBIR51"),
    "BIx51+UMBIx51": ("BI", "UMBI"),
    "BIR51+UMBIR51": ("BIR51", "UMBIR51"),
    "MP+PIP": ("MP", "MP_HCP", "PIP", "PIP_HCP"),
    "PD+UMPD": ("PD", "UMPD"),
    "CMPxCAT": ("CMP",),
    "HOPxCAT": ("HOP",),
}
BUDGET_PRODUCT_MEMBERS = {"HO+DF": ("HO", "DF")}
AGGREGATE_COMPANY_PREFIX = "PRNJ - "
BUDGET_DEVIATION_SIGMA = 0.05

# ---------------------------------------------------------------- book size

PRODUCT_UNITS = {"PA": 18000, "CA": 2500, "HO": 12000, "DF": 2000, "HO+DF": 12000, "MC": 3000, "PCAT": 12000}
STATE_WEIGHT = {"NJ": 1.0, "Penn": 0.5, "NY": 0.4, "MA": 0.35, "CT": 0.3, "NH": 0.12}
OTHER_STATE_WEIGHT = 0.05
CHANNEL_WEIGHT = {"Partners": 1.0, "Independent": 0.8, "Core Direct": 0.5, "Legacy": 0.5, "Direct": 0.3,
                  "Prudential Agent": 0.2}
OTHER_CHANNEL_WEIGHT = 0.1
COMPANY_SIGMA = 0.6
GROWTH_RANGE = (-0.03, 0.06)
TARGET_LOSS_RATIO = (0.55, 0.72)
# Share of each category's policies that carry it, where it is optional.
CATEGORY_TAKE_UP = {"COL": 0.78, "CMP": 0.78, "PIP": 0.7, "PIP_HCP": 0.3, "MP_HCP": 0.3}
DEFAULT_LIMITED_TORT = 0.3
# Minor storms: chance a state-month is coded as a catastrophe, and the claim
# rates such a month adds per comprehensive / home exposure-year.
MINOR_CAT_CHANCE = 0.25
MINOR_CAT_RATES = (0.01, 0.03)


@dataclass
class KeyShape:
    """The months one key combination's rows cover in the template."""

    loss: tuple[int, int] | None = None
    premium: tuple[int, int] | None = None
    budget: tuple[int, int] | None = None


def _widen(span: tuple[int, int] | None, month: int) -> tuple[int, int]:
    return (month, month) if span is None else (min(span[0], month), max(span[1], month))


def read_template(path: Path) -> dict[tuple, KeyShape]:
    """Key combination -> the month spans its rows cover. Figures are not read."""
    shapes: dict[tuple, KeyShape] = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        if tuple(header) != HEADER:
            raise ValueError(f"{path} does not have the expected 34 columns")
        acc, sys_col = header.index("acc_yrmo"), header.index("sys_yrmo")
        premium, budget = header.index(PREMIUM_COLUMNS[0]), header.index(BUDGET_COLUMNS[0])
        for row in reader:
            shape = shapes.setdefault(tuple(row[:len(KEY_COLUMNS)]), KeyShape())
            month = model.month_index(int(float(row[acc])))
            if row[sys_col] != PREMIUM_ROW_SYS:
                shape.loss = _widen(shape.loss, month)
            elif row[premium] != "":
                shape.premium = _widen(shape.premium, month)
            elif row[budget] != "":
                shape.budget = _widen(shape.budget, month)
    return shapes


# ---------------------------------------------------------------- one key's book


def _keyed_random(seed: int, *key) -> random.Random:
    return random.Random(f"{seed}|{'|'.join(map(str, key))}")


def coverage_for(key: tuple) -> model.Coverage:
    company, product, state, channel, category = key
    category = CAT_PARENT.get(category, category)
    name = COVERAGE_NAME[category]
    tables = {"MC": (model.MOTORCYCLE_COVERAGES, model.AUTO_COVERAGES),
              "PA": (model.AUTO_COVERAGES,), "CA": (model.AUTO_COVERAGES,)}.get(product, (model.HOME_COVERAGES,))
    coverage = next((table[name] for table in (*tables, EXTRA_COVERAGES) if name in table), None)
    if coverage is None:
        coverage = model.AUTO_COVERAGES[name]
    if category in HCP_CATEGORIES:
        coverage = dataclasses.replace(coverage, name=f"{name} HCP", frequency=coverage.frequency * HCP_FREQUENCY,
                                       severity=coverage.severity * HCP_SEVERITY)
    if product == "CA":
        coverage = dataclasses.replace(coverage, frequency=coverage.frequency * COMMERCIAL_FREQUENCY,
                                       severity=coverage.severity * COMMERCIAL_SEVERITY)
    return coverage


def _take_up(category: str, state: str) -> float:
    tort = model.LIMITED_TORT_SHARE.get(STATE_ALIAS.get(state, state), DEFAULT_LIMITED_TORT)
    if category in ("BIR51", "UMBIR51"):
        return tort
    if category in ("BI", "UMBI"):
        return 1.0 - tort
    return CATEGORY_TAKE_UP.get(category, 1.0)


@dataclass
class Book:
    key: tuple
    coverage: model.Coverage
    line: str
    units: float  # policies in force per year in January 2017
    growth: float
    start: int  # first month the book writes
    loss_ratio: float  # target loss ratio before the rate-adequacy cycle
    cat_load: float = 0.0  # expected catastrophe claims per regular claim
    cats: list = field(default_factory=list)

    def exposure(self, index: int) -> float:
        """Earned exposure-years in one month."""
        if index < self.start:
            return 0.0
        units = self.units * (1.0 + self.growth) ** (index / 12.0)
        if self.key[3] == "Legacy":
            units *= (1.0 - model.LEGACY_RUNOFF) ** (index / 12.0)
        if self.start > 0:
            units *= min(1.0, (index - self.start + 1) / model.NEW_STATE_RAMP_MONTHS)
        if self.line == "MC":
            units *= (0.35, 0.35, 0.6, 0.9, 1.3, 1.5, 1.6, 1.6, 1.4, 1.1, 0.6, 0.4)[index % 12]
        return units * _take_up(self.key[4], self.key[2]) / 12.0

    def premium(self, index: int) -> float:
        coverage = self.coverage
        pure = (coverage.frequency * (1.0 + self.cat_load) * model.severity_mean(coverage, index)
                * (1.0 - coverage.closed_without_payment))
        ratio = self.loss_ratio * model.RATE_ADEQUACY[model.month_label(index) // 100]
        payback = model.PREMIUM_PAYBACK.get(model.month_label(index), 0.0) if self.line in model.VEHICLE_LINES else 0.0
        return self.exposure(index) * pure / ratio * (1.0 - payback)


def make_book(seed: int, key: tuple, shape: KeyShape) -> Book:
    company, product, state, channel, category = key
    rng = _keyed_random(seed, "book", *key)
    company_factor = _keyed_random(seed, "company", company).lognormvariate(-COMPANY_SIGMA ** 2 / 2, COMPANY_SIGMA)
    units = (PRODUCT_UNITS[product] * STATE_WEIGHT.get(state, OTHER_STATE_WEIGHT)
             * CHANNEL_WEIGHT.get(channel, OTHER_CHANNEL_WEIGHT) * company_factor)
    spans = [span for span in (shape.premium, shape.loss) if span]
    return Book(key=key, coverage=coverage_for(key), line=SIMULATION_LINE[product], units=units,
                growth=rng.uniform(*GROWTH_RANGE), start=min(span[0] for span in spans),
                loss_ratio=rng.uniform(*TARGET_LOSS_RATIO))


def catastrophe_months(seed: int, state: str, last: int) -> dict[int, tuple[float, float, float]]:
    """Month index -> (comprehensive rate, home rate, comprehensive severity multiple)."""
    alias = STATE_ALIAS.get(state, state)
    months = {}
    rng = _keyed_random(seed, "minor cats", state)
    for index in range(last + 1):
        if rng.random() < MINOR_CAT_CHANCE:
            months[index] = (*MINOR_CAT_RATES, 1.0)
    for month, states, comprehensive, home, multiple in model.CAT_EVENTS:
        if alias in states and model.month_index(month) <= last:
            months[model.month_index(month)] = (comprehensive, home, multiple)
    return months


# ---------------------------------------------------------------- generation


def _in_span(span: tuple[int, int] | None, index: int) -> bool:
    return span is not None and span[0] <= index <= span[1]


def generate(shapes: dict[tuple, KeyShape], seed: int = DEFAULT_SEED,
             valuation_month: int = VALUATION_MONTH) -> list[list]:
    """Every row of the new table, in the template's column order."""
    rng = random.Random(seed)
    shocks = model.Shocks(seed)
    valuation = model.month_index(valuation_month)
    claim_keys = sorted(key for key, shape in shapes.items() if shape.premium or shape.loss)
    books = {key: make_book(seed, key, shapes[key]) for key in claim_keys}
    cat_months = {}
    for key, book in books.items():
        category = key[4]
        if category in CAT_PARENT.values() or category in CAT_PARENT:
            months = cat_months.setdefault(key[2], catastrophe_months(seed, key[2], valuation))
            rate_column = 0 if CAT_PARENT.get(category, category) == "CMP" else 1
            book.cats = [(index, rates[rate_column], rates[2] if rate_column == 0 else 1.0)
                         for index, rates in sorted(months.items())]
            # Rates are claims per exposure-year earned in the month.
            book.cat_load = sum(rate for _i, rate, _m in book.cats) / (valuation + 1) / book.coverage.frequency

    cells: dict[tuple, tuple[list[float], list[float]]] = {}

    def simulate(book: Book, index: int, expected: float, multiple: float, keys: list[tuple]) -> None:
        keys = [key for key in keys if _in_span(shapes[key].loss, index)]
        for _ in range(model.poisson(rng, expected)):
            claim = model.claim_events(rng, book.coverage, index, multiple, shocks, book.line)
            if keys:
                model.post_claim(cells, keys, index, valuation, claim)

    for key in claim_keys:
        book, category = books[key], key[4]
        if category in CAT_PARENT:
            parent = (*key[:4], CAT_PARENT[category])
            if parent in books:
                continue  # the parent posts its catastrophe claims here too
            for index, rate, multiple in book.cats:
                simulate(book, index, book.exposure(index) * rate, multiple, [key])
            continue
        if shapes[key].loss is None:
            continue
        coverage = book.coverage
        for index in range(shapes[key].loss[0], min(shapes[key].loss[1], valuation) + 1):
            expected = (book.exposure(index) * coverage.frequency * model.frequency_index(coverage, book.line, index)
                        * shocks.frequency(book.line, coverage, STATE_ALIAS.get(key[2], key[2]), index))
            simulate(book, index, expected, 1.0, [key])
        cat_key = next((cat for cat, parent in CAT_PARENT.items() if parent == category), None)
        for index, rate, multiple in book.cats:
            keys = [key] + ([(*key[:4], cat_key)] if (*key[:4], cat_key) in shapes else [])
            simulate(book, index, book.exposure(index) * rate, multiple, keys)

    # A key the template has losses for always gets at least one claim.
    posted = {cell[:len(KEY_COLUMNS)] for cell in cells}
    for key in claim_keys:
        span = shapes[key].loss
        if span is None or key in posted or span[0] > valuation:
            continue
        book, index = books[key], span[0]
        parent = (*key[:4], CAT_PARENT.get(key[4], key[4]))
        keys = [key] + ([parent] if parent != key and _in_span(shapes.get(parent, KeyShape()).loss, index) else [])
        while True:
            claim = model.claim_events(rng, book.coverage, index, 1.0, shocks, book.line)
            if claim[1] <= valuation:
                model.post_claim(cells, keys, index, valuation, claim)
                break

    rows = _loss_rows(cells)
    for key in claim_keys:
        span = shapes[key].premium
        if span:
            book = books[key]
            for index in range(span[0], span[1] + 1):
                rows.append([*key, _origin_text(index), PREMIUM_ROW_SYS, *[""] * _LOSS_WIDTH,
                             round(book.premium(index), 2), round(book.exposure(index), 4), "", ""])
    rows.extend(_budget_rows(shapes, books, seed, valuation))
    return rows


_LOSS_WIDTH = len(model.LOSS_COLUMNS) + len(model.COUNT_COLUMNS)


def _origin_text(index: int) -> str:
    return f"{model.month_label(index)}.0"  # the extract writes the origin month as a float


def _loss_rows(cells: dict) -> list[list]:
    """Monthly movements from cumulative figures rounded to cents, so every identity holds."""
    by_origin: dict[tuple, list[int]] = {}
    for *key, accident, month in cells:
        by_origin.setdefault((*key, accident), []).append(month)
    rows = []
    for origin in sorted(by_origin):
        *key, accident = origin
        running = [0.0] * len(model.LOSS_COLUMNS)
        previous_loss = [0.0] * len(model.LOSS_COLUMNS)
        for month in sorted(by_origin[origin]):
            loss, counts = cells[(*key, accident, month)]
            running = [a + b for a, b in zip(running, loss)]
            cumulative = _consistent_cumulative(running)
            movement = [_cents(now - before) for now, before in zip(cumulative, previous_loss)]
            previous_loss = cumulative
            count_movement = [int(round(value)) for value in counts]
            if any(movement) or any(count_movement):
                rows.append([*key, _origin_text(accident), str(model.month_label(month)), *movement, *count_movement,
                             "", "", "", ""])
    return rows


def _cents(value: float) -> float:
    value = round(value, 2)
    return 0.0 if value == 0 else value


def _consistent_cumulative(running: list[float]) -> list[float]:
    position = model.LOSS_INDEX
    out = [0.0] * len(running)
    for name in BASE_LOSS:
        out[position[name]] = round(running[position[name]], 2)
    out[position["recovery"]] = round(out[position["salvage"]] + out[position["subro"]], 2)
    out[position["gross_incurred"]] = round(out[position["gross_paid"]] + out[position["reserve"]], 2)
    out[position["net_incurred"]] = round(out[position["gross_incurred"]] + out[position["recovery"]], 2)
    ceilings = {"incurred": out[position["net_incurred"]],
                "paid": round(out[position["gross_paid"]] + out[position["recovery"]], 2)}
    for basis, ceiling in ceilings.items():
        for label, _cap in reversed(model.CAPS):
            name = f"net_{basis}_capped_{label}"
            ceiling = out[position[name]] = min(round(running[position[name]], 2), ceiling)
    return out


def _budget_rows(shapes: dict[tuple, KeyShape], books: dict[tuple, Book], seed: int, valuation: int) -> list[list]:
    """Remaining budget premium and exposure: the projected business of each aggregate key's members."""
    writing = [book for book in books.values()
               if shapes[book.key].premium and shapes[book.key].premium[1] >= valuation]
    rows = []
    for key in sorted(key for key, shape in shapes.items() if shape.budget):
        company, product, state, channel, category = key
        products = BUDGET_PRODUCT_MEMBERS.get(product, (product,))
        categories = BUDGET_CATEGORY_MEMBERS.get(category, (category,))
        members = [book for book in writing
                   if book.key[1] in products and book.key[2] == state and book.key[3] == channel
                   and book.key[4] in categories
                   and (company.startswith(AGGREGATE_COMPANY_PREFIX) or book.key[0] == company)]
        rng = _keyed_random(seed, "budget", *key)
        span = shapes[key].budget
        for index in range(span[0], span[1] + 1):
            premium = exposure = 0.0
            if index > valuation:
                deviation = rng.lognormvariate(-BUDGET_DEVIATION_SIGMA ** 2 / 2, BUDGET_DEVIATION_SIGMA)
                premium = sum(book.premium(index) for book in members) * deviation
                exposure = sum(book.exposure(index) for book in members) * deviation
            rows.append([*key, _origin_text(index), PREMIUM_ROW_SYS, *[""] * _LOSS_WIDTH, "", "",
                         round(premium, 2), round(exposure, 4)])
    return rows


def write_table(rows: list[list], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a synthetic source table for the Fake project.")
    parser.add_argument("--template", type=Path, required=True,
                        help="The current source CSV; only its keys and months are read.")
    parser.add_argument("--output", type=Path, required=True, help="The CSV to write.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--valuation", type=int, default=VALUATION_MONTH, help="Last evaluation month, yyyymm.")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    shapes = read_template(args.template)
    rows = generate(shapes, args.seed, args.valuation)
    write_table(rows, args.output)
    keys = {tuple(row[:len(KEY_COLUMNS)]) for row in rows}
    print(f"Wrote {len(rows):,} rows for {len(keys)} of {len(shapes)} key combinations to {args.output} "
          f"in {time.perf_counter() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
