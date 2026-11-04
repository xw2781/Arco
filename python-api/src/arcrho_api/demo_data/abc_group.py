"""ABC Insurance Group: the fake source tables behind ArcRho's demo project.

ABC Insurance Group is a fictional regional personal-lines insurer. It writes
private passenger auto (PPA), homeowners (HO), dwelling fire (DF) and
motorcycle (MC) through five companies, five channels and seven states. Three
states have written since before 2017; the others were entered later, so their
triangles are short and sparse.

Every figure comes from a claim-by-claim simulation driven by one seeded random
generator, so the same seed always writes byte-identical files:

- claim counts are Poisson, severities lognormal with an annual trend and a
  2021-2023 inflation spike, and each claim has a report lag, a settlement lag,
  case reserves, ALAE, salvage and subrogation;
- liability case reserves are set below ultimate until a case-reserve
  strengthening review in January 2024, which re-sets every open reserve;
- a few catastrophe months add Comprehensive and Home Property claims, which
  are also reported under the "Cat" coverages so that ex-Cat classes can be
  formed by subtraction;
- rates target a plan loss ratio per coverage; the plan runs hot for 2022-2023
  accident years and in a newly entered state's first two years.

Run ``python -m arcrho_api.demo_data.abc_group --output <folder>`` to write the
four import tables: ``Loss.csv``, ``Claim_Counts.csv``, ``Premium.csv`` and
``Exposure.csv``. Losses and counts are incremental monthly movements by
accident month (``acc_yrmo``) and evaluation month (``sys_yrmo``); premium and
exposure are full-year earned amounts by accident month, through December of
the valuation year.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_SEED = 20260831
FIRST_MONTH = 201701
VALUATION_MONTH = 202608
LAST_PREMIUM_MONTH = 202612
STRENGTHENING_MONTH = 202401

KEY_COLUMNS = ("CO_CD", "PROD_CD", "STATE_CD", "CHANNEL", "Coverage", "acc_yrmo")
DEVELOPMENT_COLUMN = "sys_yrmo"
CAPS = (("50k", 50_000.0), ("100k", 100_000.0), ("1000k", 1_000_000.0))
LOSS_COLUMNS = (
    "gross_paid",
    "expense",
    "salvage",
    "subro",
    "reserve",
    "recovery",
    "net_incurred",
    "gross_incurred",
    *(f"net_{basis}_capped_{label}" for label, _cap in CAPS for basis in ("incurred", "paid")),
)
COUNT_COLUMNS = (
    "CWP",
    "CWOP",
    *(f"CWP_ex_{label}" for label, _cap in CAPS),
    "reported",
    *(f"reported_ex_{label}" for label, _cap in CAPS),
)
TABLE_FILES = {
    "Loss": "Loss.csv",
    "Claim Counts": "Claim_Counts.csv",
    "Premium": "Premium.csv",
    "Exposure": "Exposure.csv",
}

# Channels the group controls; independent agents also sell other insurers.
EXCLUSIVE_CHANNELS = ("Direct", "Captive Agent", "Partner", "Legacy")
ALL_CHANNELS = (*EXCLUSIVE_CHANNELS, "Independent Agent")
ALL_STATES = ("NJ", "NY", "PA", "CT", "MA", "NH", "DE")


@dataclass(frozen=True)
class Coverage:
    name: str
    frequency: float  # claims per exposure-year
    severity: float  # mean ultimate loss of a paid claim at January 2017 cost
    sigma: float  # lognormal shape of the severity
    report_median: float  # median months from accident to report
    report_sigma: float  # lognormal shape of the report lag
    settle_months: float  # median months from report to close
    closed_without_payment: float
    alae_ratio: float
    salvage: float  # expected salvage as a share of loss
    subrogation: float  # expected subrogation as a share of loss
    trend: float  # annual severity trend
    family: str  # liability, physical or property
    loss_ratio: float  # plan loss ratio the rates target


def _coverages(*rows: tuple) -> dict[str, Coverage]:
    return {row[0]: Coverage(*row) for row in rows}


#   name, frequency, severity, sigma, report median, report sigma, settle, CWOP, ALAE, salvage, subro,
#   trend, family, plan loss ratio
AUTO_COVERAGES = _coverages(
    ("Bodily Injury", 0.0090, 17000, 1.15, 1.0, 1.4, 16, 0.22, 0.14, 0.0, 0.010, 0.05, "liability", 0.66),
    ("Bodily Injury Limited Tort", 0.0060, 12500, 1.10, 1.0, 1.4, 13, 0.30, 0.12, 0.0, 0.010, 0.05, "liability", 0.64),
    ("Uninsured Motorist BI", 0.0018, 23000, 1.20, 2.5, 1.5, 21, 0.25, 0.12, 0.0, 0.030, 0.05, "liability", 0.62),
    ("Uninsured Motorist BI Limited Tort", 0.0012, 18000, 1.15, 2.5, 1.5, 18, 0.30, 0.11, 0.0, 0.030, 0.05, "liability", 0.60),
    ("Property Damage", 0.0330, 4300, 0.80, 0.3, 1.0, 2, 0.12, 0.03, 0.0, 0.040, 0.04, "physical", 0.62),
    ("Uninsured Motorist PD", 0.0040, 3600, 0.85, 0.5, 1.0, 3, 0.20, 0.02, 0.0, 0.100, 0.04, "physical", 0.55),
    ("Medical Payments", 0.0070, 3300, 0.90, 0.8, 1.2, 5, 0.18, 0.04, 0.0, 0.020, 0.03, "liability", 0.58),
    ("Personal Injury Protection", 0.0140, 7600, 1.10, 0.8, 1.2, 12, 0.12, 0.10, 0.0, 0.020, 0.04, "liability", 0.68),
    ("Collision", 0.0520, 4800, 0.70, 0.2, 0.8, 1.5, 0.12, 0.015, 0.070, 0.090, 0.04, "physical", 0.60),
    ("Comprehensive", 0.0360, 2100, 0.90, 0.2, 0.8, 1.2, 0.14, 0.010, 0.060, 0.020, 0.04, "physical", 0.52),
)
MOTORCYCLE_COVERAGES = _coverages(
    ("Bodily Injury", 0.0110, 24000, 1.20, 1.0, 1.4, 18, 0.20, 0.15, 0.0, 0.010, 0.05, "liability", 0.65),
    ("Uninsured Motorist BI", 0.0020, 26000, 1.20, 2.5, 1.5, 21, 0.25, 0.12, 0.0, 0.030, 0.05, "liability", 0.60),
    ("Property Damage", 0.0090, 3200, 0.80, 0.3, 1.0, 2, 0.12, 0.03, 0.0, 0.040, 0.04, "physical", 0.60),
    ("Medical Payments", 0.0060, 5000, 0.95, 0.8, 1.2, 6, 0.15, 0.05, 0.0, 0.020, 0.03, "liability", 0.58),
    ("Collision", 0.0220, 6500, 0.75, 0.2, 0.8, 1.8, 0.12, 0.015, 0.080, 0.070, 0.04, "physical", 0.58),
    ("Comprehensive", 0.0120, 3000, 0.95, 0.2, 0.8, 1.2, 0.15, 0.010, 0.060, 0.020, 0.04, "physical", 0.50),
)
HOME_COVERAGES = _coverages(
    ("Home Property", 0.0400, 9500, 1.00, 0.4, 1.0, 3, 0.20, 0.03, 0.010, 0.030, 0.05, "property", 0.48),
    ("Home Liability", 0.0040, 26000, 1.30, 2.0, 1.6, 24, 0.35, 0.22, 0.0, 0.010, 0.05, "liability", 0.45),
)
COVERAGES_BY_LINE = {"PPA": AUTO_COVERAGES, "MC": MOTORCYCLE_COVERAGES, "HO": HOME_COVERAGES, "DF": HOME_COVERAGES}
CAT_COVERAGE = {"Comprehensive": "Comprehensive Cat", "Home Property": "Home Property Cat"}


@dataclass(frozen=True)
class Book:
    """One line written in one state by one company, split across channels."""

    line: str
    state: str
    company: str
    entry_month: int
    units: float  # policies in force per year at entry (or in 2017)
    growth: float  # annual growth in policies
    channels: tuple[tuple[str, float], ...]


BOOKS = (
    Book("PPA", "NJ", "ABC Casualty Co", 201701, 42000, 0.020,
         (("Direct", .38), ("Captive Agent", .22), ("Independent Agent", .18), ("Partner", .10), ("Legacy", .12))),
    Book("PPA", "NY", "ABC Casualty Co", 201701, 28000, 0.015,
         (("Direct", .45), ("Captive Agent", .25), ("Independent Agent", .20), ("Partner", .10))),
    Book("PPA", "PA", "ABC Insurance Co", 201701, 22000, 0.030,
         (("Direct", .50), ("Captive Agent", .30), ("Independent Agent", .20))),
    Book("PPA", "CT", "ABC Insurance Co", 202101, 7000, 0.040, (("Direct", .70), ("Independent Agent", .30))),
    Book("PPA", "MA", "ABC Insurance Co", 202304, 5000, 0.060, (("Direct", .60), ("Partner", .40))),
    Book("PPA", "NH", "ABC Insurance Co", 202501, 2500, 0.080, (("Direct", 1.0),)),
    Book("PPA", "DE", "ABC Insurance Co", 202602, 2000, 0.080, (("Direct", 1.0),)),
    Book("HO", "NJ", "ABC Property Co", 201701, 30000, 0.010,
         (("Legacy", .55), ("Direct", .20), ("Captive Agent", .15), ("Independent Agent", .10))),
    Book("HO", "NY", "ABC Property Co", 201701, 9000, 0.020, (("Direct", .50), ("Captive Agent", .30), ("Legacy", .20))),
    Book("HO", "PA", "ABC Property Co", 202201, 5000, 0.050, (("Direct", .60), ("Independent Agent", .40))),
    Book("DF", "NJ", "ABC Property Co", 201701, 3500, 0.000, (("Legacy", .70), ("Captive Agent", .30))),
    Book("DF", "NY", "ABC Property Co", 201701, 2000, 0.000, (("Legacy", 1.0),)),
    Book("MC", "NJ", "ABC Specialty Co", 201701, 4500, 0.020, (("Direct", .60), ("Partner", .40))),
    Book("MC", "NY", "ABC Specialty Co", 201701, 3000, 0.020, (("Direct", .70), ("Partner", .30))),
    Book("MC", "PA", "ABC Specialty Co", 201701, 2500, 0.030, (("Direct", 1.0),)),
    Book("MC", "CT", "ABC Select Co", 202104, 1000, 0.050, (("Direct", 1.0),)),
    Book("MC", "MA", "ABC Select Co", 202304, 900, 0.050, (("Partner", 1.0),)),
)
LEGACY_RUNOFF = 0.07  # the Legacy channel is closed to new business and shrinks each year
NEW_STATE_RAMP_MONTHS = 30
NEW_STATE_PRICING_MONTHS = 24
NEW_STATE_LOSS_RATIO_LOAD = 1.15
LIMITED_TORT_SHARE = {"NJ": 0.55, "PA": 0.40}
PIP_STATES = {"NJ", "NY", "PA", "MA", "DE"}
PHYSICAL_DAMAGE_TAKE_UP = {"PPA": 0.78, "MC": 0.65}

# The plan loss ratio is the coverage's loss ratio times this rate-adequacy index:
# rates lagged the 2021-2023 severity spike and were caught up in 2024-2026.
RATE_ADEQUACY = {2017: 1.00, 2018: 0.98, 2019: 1.00, 2020: 1.00, 2021: 1.03, 2022: 1.12,
                 2023: 1.10, 2024: 1.02, 2025: 0.96, 2026: 0.94}

# (month, states, comprehensive claims per comprehensive exposure-year in that month,
#  home property claims per home exposure-year, comprehensive severity multiple)
CAT_EVENTS = (
    (201803, ("NJ", "NY"), 0.05, 0.12, 1.0),
    (202008, ("NJ", "NY", "PA", "CT"), 0.07, 0.20, 1.2),
    (202109, ("NJ", "NY", "PA"), 0.12, 0.14, 3.0),
    (202306, ("PA", "NJ"), 0.14, 0.10, 1.4),
    (202407, ("NJ", "NY", "MA"), 0.10, 0.12, 1.3),
    (202605, ("NJ", "PA", "DE"), 0.11, 0.09, 1.3),
)

# Reserving-class aggregates: (name, level, formula over members of the same level).
RESERVING_CLASS_AGGREGATES = (
    ("ABC Auto", 1, '"ABC Casualty Co" + "ABC Insurance Co"'),
    ("ABC Home", 1, '"ABC Property Co"'),
    ("ABC Moto", 1, '"ABC Specialty Co" + "ABC Select Co"'),
    ("ABC Group", 1, '"ABC Auto" + "ABC Home" + "ABC Moto"'),
    ("HO+DF", 2, "HO + DF"),
    ("PA+CT", 3, "PA + CT"),
    ("NJ+NY", 3, "NJ + NY"),
    ("All States", 3, " + ".join(ALL_STATES)),
    ("Exclusive", 4, " + ".join(f'"{name}"' for name in EXCLUSIVE_CHANNELS)),
    ("All Channels", 4, 'Exclusive + "Independent Agent"'),
    ("BI Full Tort", 5, '"Bodily Injury" + "Uninsured Motorist BI"'),
    ("BI Limited Tort", 5, '"Bodily Injury Limited Tort" + "Uninsured Motorist BI Limited Tort"'),
    ("BI Total", 5, '"BI Full Tort" + "BI Limited Tort"'),
    ("Medical and PIP", 5, '"Medical Payments" + "Personal Injury Protection"'),
    ("Injury Total", 5, '"BI Total" + "Medical and PIP"'),
    ("PD Total", 5, '"Property Damage" + "Uninsured Motorist PD"'),
    ("Comp ex Cat", 5, 'Comprehensive - "Comprehensive Cat"'),
    ("Phys Dmg ex Cat", 5, 'Collision + "Comp ex Cat"'),
    ("Auto Liability Total", 5, '"BI Total" + "Medical and PIP" + "PD Total"'),
    ("Home Property ex Cat", 5, '"Home Property" - "Home Property Cat"'),
    ("Home Total ex Cat", 5, '"Home Property ex Cat" + "Home Liability"'),
)


# ---------------------------------------------------------------- calendar


def month_index(yyyymm: int) -> int:
    return (int(yyyymm) // 100 - FIRST_MONTH // 100) * 12 + int(yyyymm) % 100 - 1


def month_label(index: int) -> int:
    year, month = divmod(int(index), 12)
    return (FIRST_MONTH // 100 + year) * 100 + month + 1


def _year(index: int) -> int:
    return month_label(index) // 100


# ---------------------------------------------------------------- the book


def coverages_written(line: str, state: str) -> dict[str, float]:
    """Coverage name -> exposure per policy-year for one line in one state."""
    if line in ("HO", "DF"):
        return {"Home Property": 1.0, "Home Liability": 1.0}
    if line == "MC":
        take_up = PHYSICAL_DAMAGE_TAKE_UP["MC"]
        return {"Bodily Injury": 1.0, "Uninsured Motorist BI": 1.0, "Property Damage": 1.0,
                "Medical Payments": 1.0, "Collision": take_up, "Comprehensive": take_up}
    tort = LIMITED_TORT_SHARE.get(state, 0.0)
    take_up = PHYSICAL_DAMAGE_TAKE_UP["PPA"]
    written = {"Bodily Injury": 1.0 - tort, "Uninsured Motorist BI": 1.0 - tort}
    if tort:
        written["Bodily Injury Limited Tort"] = tort
        written["Uninsured Motorist BI Limited Tort"] = tort
    written.update({"Property Damage": 1.0, "Uninsured Motorist PD": 1.0})
    written["Personal Injury Protection" if state in PIP_STATES else "Medical Payments"] = 1.0
    written.update({"Collision": take_up, "Comprehensive": take_up})
    return written


def policies_in_force(book: Book, channel_share: float, channel: str, index: int) -> float:
    entry = month_index(book.entry_month)
    if index < entry:
        return 0.0
    years = (index - entry) / 12.0
    units = book.units * channel_share * (1.0 + book.growth) ** years
    if channel == "Legacy":
        units *= (1.0 - LEGACY_RUNOFF) ** (index / 12.0)
    if book.entry_month > FIRST_MONTH:
        units *= min(1.0, (index - entry + 1) / NEW_STATE_RAMP_MONTHS)
    if book.line == "MC":
        units *= (0.35, 0.35, 0.6, 0.9, 1.3, 1.5, 1.6, 1.6, 1.4, 1.1, 0.6, 0.4)[index % 12]
    return units


def _frequency_index(coverage: Coverage, line: str, index: int) -> float:
    label = month_label(index)
    factor = 1.0
    if line != "HO" and line != "DF":
        if 202004 <= label <= 202005:
            factor = 0.70
        elif 202006 <= label <= 202012:
            factor = 0.85
        elif 202101 <= label <= 202106:
            factor = 0.93
    winter = index % 12 in (0, 1, 11)
    if winter and coverage.name in ("Collision", "Property Damage", "Home Property"):
        factor *= 1.15
    return factor


def severity_mean(coverage: Coverage, index: int) -> float:
    """Mean ultimate loss of a paid claim that occurs in this month."""
    years = index / 12.0
    mean = coverage.severity * (1.0 + coverage.trend) ** years
    spike_start, spike_end = month_index(202107), month_index(202306)
    if coverage.family in ("physical", "property"):
        mean *= 1.10 ** (max(0, min(index, spike_end) - spike_start) / 12.0)
    elif coverage.family == "liability":
        mean *= 1.03 ** (max(0, index - month_index(202201)) / 12.0)
    return mean


def plan_loss_ratio(line: str, coverage_name: str, state: str, yyyymm: int) -> float:
    """The loss ratio ABC's rates were set to produce for a month of business."""
    coverage = COVERAGES_BY_LINE[line][coverage_name]
    ratio = coverage.loss_ratio * RATE_ADEQUACY[int(yyyymm) // 100]
    book = next(b for b in BOOKS if b.line == line and b.state == state)
    since_entry = month_index(yyyymm) - month_index(book.entry_month)
    if book.entry_month > FIRST_MONTH and since_entry < NEW_STATE_PRICING_MONTHS:
        ratio *= NEW_STATE_LOSS_RATIO_LOAD
    return ratio


def plan_frequency(line: str, coverage_name: str) -> float:
    """Expected reported claims per exposure-year, before seasonality."""
    return COVERAGES_BY_LINE[line][coverage_name].frequency


def _premium_per_exposure(book: Book, coverage: Coverage, index: int) -> float:
    pure_premium = coverage.frequency * severity_mean(coverage, index) * (1.0 - coverage.closed_without_payment)
    return pure_premium / plan_loss_ratio(book.line, coverage.name, book.state, month_label(index))


# ---------------------------------------------------------------- randomness


def _poisson(rng: random.Random, mean: float) -> int:
    if mean <= 0:
        return 0
    if mean > 30:
        return max(0, int(round(rng.gauss(mean, math.sqrt(mean)))))
    limit, k, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        k += 1
        product *= rng.random()
    return k


def _lognormal(rng: random.Random, mean: float, sigma: float) -> float:
    return rng.lognormvariate(math.log(mean) - sigma * sigma / 2.0, sigma)


# ---------------------------------------------------------------- claims


# Case reserves as a share of the outstanding loss, at report and at the two
# reviews of a long claim. Liability reserves were set low until the January
# 2024 strengthening review; physical damage and property reserves are close.
CASE_ADEQUACY = {
    "liability": ((0.65, 0.80, 0.92), (0.85, 0.95, 1.00)),
    "physical": ((0.95, 1.00, 1.00), (0.95, 1.00, 1.00)),
    "property": ((0.90, 0.97, 1.00), (0.90, 0.97, 1.00)),
}
EVENT_ORDER = {"report": 0, "review": 1, "close": 2, "recovery": 3}


def _case_adequacy(coverage: Coverage, stage: int, index: int) -> float:
    before, after = CASE_ADEQUACY[coverage.family]
    return (after if index >= month_index(STRENGTHENING_MONTH) else before)[stage]


def _claim_events(rng: random.Random, coverage: Coverage, accident: int, cat_multiple: float):
    """Events of one claim in time order: (month, kind, paid, case after, alae, salvage, subro)."""
    cat = cat_multiple != 1.0
    severity = severity_mean(coverage, accident) * cat_multiple
    paid_claim = rng.random() >= coverage.closed_without_payment
    report_median = 0.3 if cat else coverage.report_median
    report = accident + int(rng.lognormvariate(math.log(report_median), coverage.report_sigma))
    settle_median = coverage.settle_months * (0.6 if cat else 1.0)
    settle_sigma = 0.6 if coverage.family == "physical" else 0.85
    close = report + max(0, int(round(rng.lognormvariate(math.log(settle_median), settle_sigma))))
    loss = _lognormal(rng, severity, coverage.sigma) if paid_claim else 0.0
    life = close - report
    reviews = [report + life // 3, report + 2 * life // 3] if life >= 6 else ([report + life // 2] if life >= 3 else [])
    shares = (rng.uniform(0.05, 0.20), rng.uniform(0.20, 0.40)) if len(reviews) == 2 else (rng.uniform(0.2, 0.5),)
    alae_total = coverage.alae_ratio * (loss if paid_claim else severity * 0.25) * _lognormal(rng, 1.0, 0.4)
    alae_shares = (0.2, 0.3, 0.5) if len(reviews) == 2 else ((0.4, 0.6) if reviews else (1.0,))

    def case_reserve(stage: int, month: int, outstanding: float) -> float:
        base = outstanding if paid_claim else severity * (0.25 if coverage.family == "liability" else 0.4)
        return max(50.0, base * _case_adequacy(coverage, stage, month) * _lognormal(rng, 1.0, 0.25))

    events = [(report, "report", 0.0, case_reserve(0, report, loss), 0.0, 0.0, 0.0)]
    paid = 0.0
    stage_at = {report: 0}
    for stage, (month, share) in enumerate(zip(reviews, shares), start=1):
        payment = loss * share
        paid += payment
        events.append((month, "review", payment, case_reserve(stage, month, loss - paid), alae_total * alae_shares[stage - 1], 0.0, 0.0))
        stage_at[month] = stage
    strengthening = month_index(STRENGTHENING_MONTH)
    if coverage.family == "liability" and report < strengthening < close and strengthening not in stage_at:
        stage = max(s for m, s in stage_at.items() if m < strengthening)
        paid_before = sum(e[2] for e in events if e[0] < strengthening)
        events.append((strengthening, "review", 0.0, case_reserve(stage, strengthening, loss - paid_before), 0.0, 0.0, 0.0))
    events.append((close, "close", loss - paid, 0.0, alae_total * alae_shares[-1], 0.0, 0.0))
    if paid_claim and coverage.salvage and rng.random() < 0.45:
        amount = loss * coverage.salvage / 0.45 * rng.uniform(0.6, 1.4)
        events.append((close + 1 + int(rng.expovariate(1 / 2.5)), "recovery", 0.0, 0.0, 0.0, -amount, 0.0))
    if paid_claim and coverage.subrogation and rng.random() < 0.25:
        amount = loss * coverage.subrogation / 0.25 * rng.uniform(0.5, 1.5)
        events.append((close + 2 + int(rng.expovariate(1 / 6.0)), "recovery", 0.0, 0.0, 0.0, 0.0, -amount))
    events.sort(key=lambda event: (event[0], EVENT_ORDER[event[1]]))
    return paid_claim, report, events


LOSS_INDEX = {name: i for i, name in enumerate(LOSS_COLUMNS)}
COUNT_INDEX = {name: i for i, name in enumerate(COUNT_COLUMNS)}


ULTIMATE_FIELDS = ("gross_loss", "net_loss", "alae", "salvage", "subro", "reported", "cwp", "cwop")


def _post_ultimate(ultimates: dict, keys: Iterable[tuple], accident: int, claim) -> None:
    """Add one claim's settled totals, whether or not they are known yet."""
    paid_claim, _report, events = claim
    totals = [
        sum(e[2] for e in events),
        sum(e[2] + e[5] + e[6] for e in events),
        sum(e[4] for e in events),
        sum(e[5] for e in events),
        sum(e[6] for e in events),
        1.0,
        1.0 if paid_claim else 0.0,
        0.0 if paid_claim else 1.0,
    ]
    for key in keys:
        target = ultimates.setdefault((*key, accident), [0.0] * len(ULTIMATE_FIELDS))
        for i, value in enumerate(totals):
            target[i] += value


def _post_claim(cells: dict, keys: Iterable[tuple], accident: int, valuation: int, claim) -> None:
    paid_claim, report, events = claim
    if report > valuation:
        return
    paid = case = recovered = 0.0
    capped_incurred = [0.0] * len(CAPS)
    capped_paid = [0.0] * len(CAPS)
    over = [False] * len(CAPS)
    rows: dict[int, tuple[list[float], list[float]]] = {}
    for month, kind, pay, case_after, alae, salvage, subro in events:
        if month > valuation:
            break
        loss_row, count_row = rows.setdefault(month, ([0.0] * len(LOSS_COLUMNS), [0.0] * len(COUNT_COLUMNS)))
        loss_row[LOSS_INDEX["gross_paid"]] += pay
        loss_row[LOSS_INDEX["expense"]] += alae
        loss_row[LOSS_INDEX["salvage"]] += salvage
        loss_row[LOSS_INDEX["subro"]] += subro
        loss_row[LOSS_INDEX["reserve"]] += case_after - case
        paid += pay
        recovered += salvage + subro
        case = case_after
        net_paid = paid + recovered
        net_incurred = net_paid + case
        for i, (label, cap) in enumerate(CAPS):
            incurred_now, paid_now = min(net_incurred, cap), min(net_paid, cap)
            loss_row[LOSS_INDEX[f"net_incurred_capped_{label}"]] += incurred_now - capped_incurred[i]
            loss_row[LOSS_INDEX[f"net_paid_capped_{label}"]] += paid_now - capped_paid[i]
            capped_incurred[i], capped_paid[i] = incurred_now, paid_now
            is_over = net_incurred > cap
            if is_over != over[i]:
                count_row[COUNT_INDEX[f"reported_ex_{label}"]] += 1 if is_over else -1
                over[i] = is_over
        if kind == "report":
            count_row[COUNT_INDEX["reported"]] += 1
        elif kind == "close":
            count_row[COUNT_INDEX["CWP" if paid_claim else "CWOP"]] += 1
            if paid_claim:
                for label, cap in CAPS:
                    if net_paid > cap:
                        count_row[COUNT_INDEX[f"CWP_ex_{label}"]] += 1
    for key in keys:
        for month, (loss_row, count_row) in rows.items():
            target = cells.setdefault((*key, accident, month), ([0.0] * len(LOSS_COLUMNS), [0.0] * len(COUNT_COLUMNS)))
            for i, value in enumerate(loss_row):
                target[0][i] += value
            for i, value in enumerate(count_row):
                target[1][i] += value


# ---------------------------------------------------------------- tables


@dataclass
class GeneratedTables:
    loss: list[list]
    claim_counts: list[list]
    premium: list[list]
    exposure: list[list]
    # Settled totals per (company, line, state, channel, coverage, accident
    # month index) in ULTIMATE_FIELDS order, including what is not yet known
    # at the valuation. Not written; the demo builder derives priors from it.
    ultimates: dict

    def summary(self) -> dict[str, int]:
        return {
            "loss_rows": len(self.loss),
            "claim_count_rows": len(self.claim_counts),
            "premium_rows": len(self.premium),
            "exposure_rows": len(self.exposure),
        }


def generate(seed: int = DEFAULT_SEED, valuation_month: int = VALUATION_MONTH) -> GeneratedTables:
    rng = random.Random(seed)
    valuation = month_index(valuation_month)
    last_premium = month_index(valuation_month // 100 * 100 + 12)
    cells: dict[tuple, tuple[list[float], list[float]]] = {}
    premium: dict[tuple, float] = {}
    exposure: dict[tuple, float] = {}
    ultimates: dict[tuple, list[float]] = {}
    cat_by_month = {month_index(event[0]): event for event in CAT_EVENTS}

    for book in BOOKS:
        coverages = COVERAGES_BY_LINE[book.line]
        for channel, share in book.channels:
            for coverage_name, exposure_factor in coverages_written(book.line, book.state).items():
                coverage = coverages[coverage_name]
                key = (book.company, book.line, book.state, channel, coverage_name)
                cat_key = (book.company, book.line, book.state, channel, CAT_COVERAGE.get(coverage_name, ""))
                for index in range(0, last_premium + 1):
                    units = policies_in_force(book, share, channel, index)
                    if units <= 0:
                        continue
                    earned = units * exposure_factor / 12.0
                    exposure[(*key, index)] = earned
                    premium[(*key, index)] = earned * _premium_per_exposure(book, coverage, index)
                    if index > valuation:
                        continue
                    expected = earned * coverage.frequency * _frequency_index(coverage, book.line, index)
                    for _ in range(_poisson(rng, expected)):
                        claim = _claim_events(rng, coverage, index, 1.0)
                        _post_claim(cells, (key,), index, valuation, claim)
                        _post_ultimate(ultimates, (key,), index, claim)
                    event = cat_by_month.get(index)
                    if event and coverage_name in CAT_COVERAGE and book.state in event[1]:
                        rate = event[2] if coverage_name == "Comprehensive" else event[3]
                        multiple = event[4] if coverage_name == "Comprehensive" else 1.0
                        for _ in range(_poisson(rng, earned * rate)):
                            claim = _claim_events(rng, coverage, index, multiple)
                            _post_claim(cells, (key, cat_key), index, valuation, claim)
                            _post_ultimate(ultimates, (key, cat_key), index, claim)

    loss_rows, count_rows = [], []
    for cell_key in sorted(cells):
        *key, accident, month = cell_key
        loss_values, count_values = cells[cell_key]
        prefix = [*key, month_label(accident), month_label(month)]
        loss_out = _rounded_loss(loss_values)
        if any(loss_out):
            loss_rows.append(prefix + loss_out)
        counts_out = [int(round(value)) for value in count_values]
        if any(counts_out):
            count_rows.append(prefix + counts_out)
    premium_rows = [[*k[:5], month_label(k[5]), round(v, 2)] for k, v in sorted(premium.items()) if round(v, 2)]
    exposure_rows = [[*k[:5], month_label(k[5]), round(v, 4)] for k, v in sorted(exposure.items()) if round(v, 4)]
    return GeneratedTables(loss_rows, count_rows, premium_rows, exposure_rows, ultimates)


def _rounded_loss(values: list[float]) -> list[float]:
    """Round each movement to cents so the identities hold on the written figures."""
    out = [round(value, 2) for value in values]
    index = LOSS_INDEX
    out[index["recovery"]] = round(out[index["salvage"]] + out[index["subro"]], 2)
    out[index["gross_incurred"]] = round(out[index["gross_paid"]] + out[index["reserve"]], 2)
    out[index["net_incurred"]] = round(out[index["gross_incurred"]] + out[index["recovery"]], 2)
    return [0.0 if value == 0 else value for value in out]


def write_tables(tables: GeneratedTables, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "Loss": (*KEY_COLUMNS, DEVELOPMENT_COLUMN, *LOSS_COLUMNS),
        "Claim Counts": (*KEY_COLUMNS, DEVELOPMENT_COLUMN, *COUNT_COLUMNS),
        "Premium": (*KEY_COLUMNS, "Earned_Premium"),
        "Exposure": (*KEY_COLUMNS, "Earned_Exposure"),
    }
    rows = {"Loss": tables.loss, "Claim Counts": tables.claim_counts,
            "Premium": tables.premium, "Exposure": tables.exposure}
    written = {}
    for name, file_name in TABLE_FILES.items():
        path = output_dir / file_name
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers[name])
            writer.writerows(rows[name])
        written[name] = path
    return written


# ---------------------------------------------------------------- members


def reserving_class_signed_members(level: int, name: str) -> dict[str, int]:
    """Atomic source value -> +1 or -1 for what a reserving-class name adds up at one level."""
    formulas = {(lvl, n): f for n, lvl, f in RESERVING_CLASS_AGGREGATES}
    if (level, name) not in formulas:
        return {name: 1}
    members: dict[str, int] = {}
    sign = 1
    for token in _formula_tokens(formulas[(level, name)]):
        if token in "+-":
            sign = 1 if token == "+" else -1
            continue
        for member, inner in reserving_class_signed_members(level, token).items():
            members[member] = members.get(member, 0) + sign * inner
    return {member: value for member, value in members.items() if value}


def reserving_class_members(level: int, name: str) -> set[str]:
    """The atomic source values a reserving-class name adds.

    A subtracted member (a "Cat" coverage) is a reporting subset of an added
    one and carries no premium or exposure, so it is left out.
    """
    return {member for member, sign in reserving_class_signed_members(level, name).items() if sign > 0}


def _formula_tokens(formula: str) -> list[str]:
    tokens, i = [], 0
    while i < len(formula):
        ch = formula[i]
        if ch.isspace():
            i += 1
        elif ch in "+-":
            tokens.append(ch)
            i += 1
        elif ch == '"':
            end = formula.index('"', i + 1)
            tokens.append(formula[i + 1:end])
            i = end + 1
        else:
            end = i
            while end < len(formula) and formula[end] not in "+-" and not formula[end].isspace():
                end += 1
            tokens.append(formula[i:end])
            i = end
    return tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write ABC Insurance Group's four demo import tables.")
    parser.add_argument("--output", type=Path, required=True, help="Folder for the four CSV files.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--valuation", type=int, default=VALUATION_MONTH, help="Last evaluation month, yyyymm.")
    args = parser.parse_args(argv)
    tables = generate(args.seed, args.valuation)
    for name, path in write_tables(tables, args.output).items():
        print(f"{name}: {path}")
    print(tables.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
