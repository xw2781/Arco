"""Compare Arco's stored bootstrap and consolidation results with ResQ's.

Reads the scaled total-reserve summary Arco stored for the five ``F 72 A``
segment bootstraps and the Total ``F 72 A`` Stochastic Consolidation of the
fake project, and the ResQ run captured in plan step 1
(``python-api/tests/fixtures/resq_bootstrap_consolidation_total.json.gz``).
For each segment and for the total it prints mean, standard deviation, CV and
the 75/90/95/99/99.5 percentiles, Arco minus ResQ, and that difference in
ResQ standard errors.

The standard errors come from ResQ's own 10,000 captured totals, distribution
free: the mean's is sd/sqrt(n), the standard deviation's uses the fourth
moment, a percentile's is half the spread of the order statistics one binomial
standard deviation either side, and the CV's is the delta-method combination
of the mean's and the standard deviation's. Arco's run carries the same
sampling error, so a difference passes the plan's parity bar when it is within
three standard errors of the two runs combined, which is 3·sqrt(2) = 4.24 ResQ
standard errors.

It then compares each origin's mean and standard deviation the same way, so a
gap confined to a few origins (a lost tail factor, say) shows up even when the
totals agree. ResQ's per-origin figures are its full run's; the standard error
of a standard deviation takes the kurtosis of the first 500 simulations the
fixture keeps by origin, scaled to the full run's 10,000.

Reads only; run on any PC that sees the ArcRho Server share::

    py -3.10 tools/bootstrap_parity_report.py [--server-root PATH] [--project NAME]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "python-api" / "src"))

from arcrho_api.bootstrap_contract import BST_FILE_PREFIX  # noqa: E402
from arcrho_api.bootstrap_simulation import percentile_key  # noqa: E402
from arcrho_api.paths import sanitize_file_name_part, sanitize_reserving_class_folder  # noqa: E402
from arcrho_api.stochastic_consolidation_contract import SCON_FILE_PREFIX  # noqa: E402

FIXTURE = REPO / "python-api" / "tests" / "fixtures" / "resq_bootstrap_consolidation_total.json.gz"
PERCENTILES = (75, 90, 95, 99, 99.5)
PARITY_Z = 3.0 * math.sqrt(2.0)


def _moments(values: list[float]) -> tuple[float, float, float, float]:
    """Mean, standard deviation (divisor n, as ResQ), and their standard errors."""

    n = len(values)
    mean = math.fsum(values) / n
    m2 = math.fsum((v - mean) ** 2 for v in values) / n
    m4 = math.fsum((v - mean) ** 4 for v in values) / n
    sd = math.sqrt(m2)
    se_sd = math.sqrt(max(m4 - m2 * m2, 0.0) / (4.0 * m2 * n)) if m2 > 0 else 0.0
    return mean, sd, sd / math.sqrt(n), se_sd


def _percentile_error(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    n = len(ordered)
    position = min(n - 1, int(math.floor(fraction * n + 1e-9)))
    half = math.sqrt(n * fraction * (1 - fraction))
    low = ordered[max(0, int(math.floor(position - half)))]
    high = ordered[min(n - 1, int(math.ceil(position + half)))]
    return (high - low) / 2.0


def _method_file(data_dir: Path, class_path: str, prefix: str, name: str) -> dict:
    path = (
        data_dir
        / sanitize_reserving_class_folder(class_path)
        / "methods"
        / f"{prefix}{sanitize_file_name_part(name, 'Method')}.json"
    )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _rows(arco_scaled: dict, resq_scaled: dict, resq_totals: list[float]) -> list[tuple]:
    """(statistic, Arco, ResQ, difference, difference in ResQ standard errors)."""

    mean, sd, se_mean, se_sd = _moments(resq_totals)
    a_mean, a_sd = arco_scaled["mean"][0], arco_scaled["standard_error"][0]
    r_mean, r_sd = resq_scaled["mean"][0], resq_scaled["standard_error"][0]
    cv_error = (sd / mean) * math.hypot(se_sd / sd, se_mean / mean)
    rows = [
        ("Mean", a_mean, r_mean, se_mean),
        ("Std. dev.", a_sd, r_sd, se_sd),
        ("CV", a_sd / a_mean, r_sd / r_mean, cv_error),
    ]
    for step in PERCENTILES:
        fraction = step / 100.0
        rows.append(
            (
                f"{step:g}%",
                arco_scaled["percentiles"][percentile_key(step)][0],
                resq_scaled["percentiles"][f"{fraction:.3f}"][0],
                _percentile_error(resq_totals, fraction),
            )
        )
    return [
        (label, a, r, a - r, (a - r) / error if error else (0.0 if a == r else math.inf))
        for label, a, r, error in rows
    ]


def _z(diff: float, error: float) -> float:
    return diff / error if error else (0.0 if abs(diff) < 1e-6 else math.inf)


def _origin_rows(arco_scaled: dict, resq_scaled: dict, resq_origin_sims: list[list[float]], n: int) -> list[tuple]:
    """Per origin: (origin index, Arco mean, ResQ mean, z, Arco sd, ResQ sd, z).

    ``resq_origin_sims`` is the fixture's first simulations, one list of
    reserves by origin each. It only sets the shape of each origin's
    distribution (its kurtosis); ResQ's mean and standard deviation are the
    full run's.
    """

    rows = []
    for index in range(1, len(resq_scaled["mean"])):
        sample = [sim[index - 1] for sim in resq_origin_sims]
        _, sample_sd, _, sample_se_sd = _moments(sample)
        r_mean, r_sd = resq_scaled["mean"][index], resq_scaled["standard_error"][index]
        a_mean, a_sd = arco_scaled["mean"][index], arco_scaled["standard_error"][index]
        se_mean = r_sd / math.sqrt(n)
        # The sample's relative error of the sd, rescaled from its own size to n.
        se_sd = r_sd * (sample_se_sd / sample_sd) * math.sqrt(len(sample) / n) if sample_sd > 0 else 0.0
        rows.append((index, a_mean, r_mean, _z(a_mean - r_mean, se_mean), a_sd, r_sd, _z(a_sd - r_sd, se_sd)))
    return rows


def _consolidated_origin_sims(consolidation: dict) -> list[list[float]]:
    """Each first simulation's consolidated reserves by origin, the sum of its methods'."""

    sims = []
    for by_method in consolidation["reserves_by_class_first_simulations"]:
        origins = len(by_method[0]) - 1  # origins 1..n, then the total
        sims.append([math.fsum(method[k] for method in by_method) for k in range(origins)])
    return sims


def build_report(server_root: Path, project: str) -> list[dict]:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as handle:
        fixture = json.load(handle)
    data_dir = server_root / "projects" / project / "data"
    report = []
    for segment in fixture["segments"]:
        method = _method_file(data_dir, segment["reserving_class"], BST_FILE_PREFIX, segment["name"])
        summary = method["results_tab"]["simulation_summary"]
        report.append(
            {
                "name": segment["reserving_class"].rsplit("\\", 1)[-1],
                "rows": _rows(summary["scaled"], segment["scaled"], segment["scaled_total_by_simulation"]),
                "origins": segment["origin_labels"],
                "origin_rows": _origin_rows(
                    summary["scaled"],
                    segment["scaled"],
                    segment["scaled_by_origin_first_simulations"],
                    len(segment["scaled_total_by_simulation"]),
                ),
            }
        )
    consolidation = fixture["consolidation"]
    method = _method_file(data_dir, consolidation["reserving_class"], SCON_FILE_PREFIX, consolidation["name"])
    summary = method["results_tab"]["simulation_summary"]
    report.append(
        {
            "name": "Total consolidation",
            "rows": _rows(summary["scaled"], consolidation["scaled"], consolidation["scaled_total_by_simulation"]),
            "origins": consolidation["origin_labels"],
            "origin_rows": _origin_rows(
                summary["scaled"],
                consolidation["scaled"],
                _consolidated_origin_sims(consolidation),
                len(consolidation["scaled_total_by_simulation"]),
            ),
        }
    )
    return report


def _number(label: str, value: float) -> str:
    return f"{100 * value:.2f}%" if label == "CV" else f"{value:,.0f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--server-root", default=r"E:\Arco Server")
    parser.add_argument("--project", default="NJ_Annual_Prod_202605_Fake")
    args = parser.parse_args(argv)

    report = build_report(Path(args.server_root), args.project)
    failures = []
    print(f"Scaled total reserve, Arco against ResQ; parity bar |z| <= {PARITY_Z:.2f} ResQ standard errors.")
    for block in report:
        print(f"\n{block['name']}")
        print(f"  {'':<10}{'Arco':>12}{'ResQ':>12}{'Diff':>11}{'z (ResQ SE)':>13}")
        for label, arco, resq, diff, z in block["rows"]:
            diff_text = f"{100 * diff:+.2f}pt" if label == "CV" else f"{diff:+,.0f}"
            flag = "" if abs(z) <= PARITY_Z else "  outside"
            if flag:
                failures.append(f"{block['name']} {label}")
            print(f"  {label:<10}{_number(label, arco):>12}{_number(label, resq):>12}{diff_text:>11}{z:>+13.2f}{flag}")
        print(f"  {'By origin':<10}{'Mean Arco':>12}{'ResQ':>11}{'z':>8}{'Sd Arco':>11}{'ResQ':>11}{'z':>8}")
        for index, a_mean, r_mean, z_mean, a_sd, r_sd, z_sd in block["origin_rows"]:
            origin = block["origins"][index - 1]
            outside = [name for name, z in (("mean", z_mean), ("sd", z_sd)) if abs(z) > PARITY_Z]
            failures.extend(f"{block['name']} {origin} {name}" for name in outside)
            print(
                f"  {origin:<10}{a_mean:>12,.0f}{r_mean:>11,.0f}{z_mean:>+8.2f}"
                f"{a_sd:>11,.0f}{r_sd:>11,.0f}{z_sd:>+8.2f}{'  outside' if outside else ''}"
            )
    print("\nVerdict: " + ("every statistic, in total and by origin, within the parity bar." if not failures else "outside: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
