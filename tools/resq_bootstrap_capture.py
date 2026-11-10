"""Run and capture ResQ's bootstrap consolidation reference model over COM.

The reference model is the Total class of ``PRNJ - PA\\PA\\All States\\Direct
Group`` in the fake project: five segment bootstraps (``F 72 A``) and the Total
Stochastic Consolidation that combines them. Everything Arco's bootstrap and
consolidation are compared against is read from ResQ here and written to one
gzip JSON fixture, ``python-api/tests/fixtures/resq_bootstrap_consolidation_total.json.gz``.

Three modes, Server PC only (ResQ COM), run outside the sandbox::

    py -3.10 tools/resq_bootstrap_capture.py targets    # point each F 92 at the F 25 DFM, Save
    py -3.10 tools/resq_bootstrap_capture.py run        # Simulate+Save bootstraps, Consolidate+Save
    py -3.10 tools/resq_bootstrap_capture.py capture [--out PATH]   # read only

``targets`` makes the segments' data realistic (plan decision "The model stays
as built; the data is made realistic"): the Result Selection that writes
``F 92 - Current Qtr Selected `` loses its overridden ultimates and selects the
incurred DFM ``F 25 - Incurred DFM Bootstrap`` with weight 1 for every origin.
``run`` calls only ``Simulate``, ``Consolidate`` and ``Save``. ``capture``
changes nothing persisted: it consolidates once more in memory, never saved,
because a reloaded consolidation reads its achieved correlations and its
reserves by class as zero. Writing is allowed only in the fake project; ``PROJECT`` must
never name a production project. Early binding throughout (late binding returns
wrong values for some ResQ properties).

COM conventions this tool relies on, pinned on 2026-09-23: simulation indices
run 1..n (index 0 and n+1 return garbage rather than raising); ``TotalRank`` is
a permutation of 1..n with rank 1 the smallest total; reserve summaries use
origin 0 for the total; ``PercentileValue`` takes a fraction (0.995, not 99.5);
the consolidation's method index is 1-based (index 0 access-violates), and
``SimulatedReservesByClass`` takes origins 1..n with n+1 for the total
(origin 0 access-violates). On a
bootstrap, origin and development indices are 1-based except
``DevelopmentCount``, which takes the 0-based origin index.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import math
import sys
import time
from pathlib import Path

from win32com.client import gencache

PROJECT = "NJ_Annual_Prod_202605_Fake"
BASE = r"PRNJ - PA\PA\All States\Direct Group"
SEGMENTS = {
    "BI Total": "F 72 A - Bootstrap Net Incurred with PV",
    "CMPxCAT": "F 72 A - Bootstrap Net Incurred with PV",
    "COL": "F 72 A - Bootstrap Net incurred with PV",
    "MP+PIP": "F 72 A - Bootstrap Net Incurred with PV",
    "PD+UMPD": "F 72 A - Bootstrap Net Incurred with PV",
}
TOTAL_CLASS = "Total"
CONSOLIDATION = "F 72 A - Bootstrap Consolidation Net Incurred with PV"
TARGET_VECTOR = "F 92 - Current Qtr Selected "
DFM_VECTOR = "F 25 - Incurred DFM Bootstrap"
CONFIG = r"E:/Arco Server/config/config.json"
REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "python-api" / "tests" / "fixtures" / "resq_bootstrap_consolidation_total.json.gz"

PERCENTILES = [round(0.05 * k, 2) for k in range(21)] + [0.99, 0.995]
NO_RESIDUAL = -9.9e10      # ResQ's marker for a cell without a residual
ORIGIN_SIMS = 500          # simulations captured origin by origin
DISTRIBUTIONS = {0: "none", 1: "resampled", 2: "normal", 3: "log_normal", 4: "gamma", 5: "odp"}
MODELS = {0: "mack", 1: "odp_varying_scale", 2: "odp_single_scale"}
SCALING = {0: "unscaled", 1: "additive", 2: "multiplicative", 3: "user_defined", 4: "from_target"}
CORRELATION = {0: "independent", 1: "fully_correlated", 2: "specified", 3: "as_it_comes"}
DEPENDENCY = {0: "normal", 1: "uniform", 2: "gamma", 3: "students_t"}


def connect():
    cfg = json.load(open(CONFIG))["resq"]
    app = gencache.EnsureDispatch("ResQ3Automation.ResQApplication")
    app.ConnectByName(cfg["connection_name"], cfg["user_name"], cfg["password"])
    return app


def reserving_class(project, name):
    return project.ReservingClasses().Item(BASE + "\\" + name)


def find(collection, predicate):
    for i in range(1, collection.Count + 1):
        item = collection.Item(i)
        if predicate(item):
            return item
    return None


def target_selection(rc):
    """The Result Selection whose output vector is F 92."""
    return find(rc.ResultSelections(),
                lambda r: r.OutputVector is not None and str(r.OutputVector.Name) == TARGET_VECTOR)


def vector_values(v):
    return [float(v.ValuesByIndex(k)) for k in range(1, int(v.Count) + 1)]


# ----- targets ----------------------------------------------------------------------

def point_targets_at_dfm(project):
    """Make every segment's F 92 select the F 25 DFM ultimate; return what changed."""
    changes = {}
    for seg in SEGMENTS:
        rc = reserving_class(project, seg)
        rs = target_selection(rc)
        n = int(rs.OriginCount)
        before = [float(rs.Ultimates(o, rs.OriginLength)) for o in range(1, n + 1)]
        overridden = [bool(rs.UltimateOverridden(o)) for o in range(1, n + 1)]
        dfm_vector = find(rc.Vectors(), lambda v: str(v.Name) == DFM_VECTOR)
        names = [str(rs.Dataset(d).Name) for d in range(1, int(rs.DatasetCount) + 1)]
        added = False
        if DFM_VECTOR not in names:
            rs.AddDataset(dfm_vector)
            added = True
            names = [str(rs.Dataset(d).Name) for d in range(1, int(rs.DatasetCount) + 1)]
        rs.ClearOverriddenUltimates()
        for d, name in enumerate(names, start=1):
            for o in range(1, n + 1):
                rs.SetWeights(d, o, 1.0 if name == DFM_VECTOR else 0.0)
        after = [float(rs.Ultimates(o, rs.OriginLength)) for o in range(1, n + 1)]
        dfm = vector_values(dfm_vector)
        worst = max(abs(a - b) for a, b in zip(after, dfm))
        print(f"{seg}: overridden={sum(overridden)} added F 25={added}; max |F 92 - F 25| = {worst:.3g}")
        if worst > 1e-6 * max(abs(x) for x in dfm):
            raise RuntimeError(f"{seg}: the selection does not reproduce F 25; nothing saved")
        rs.Save()
        changes[seg] = {"datasets": names, "added_dfm_dataset": added,
                        "overridden_before": overridden, "f92_before": before, "f92_after": after}
        rc.UnloadChildren()
    return changes


# ----- run --------------------------------------------------------------------------

def run(project):
    for seg, name in SEGMENTS.items():
        rc = reserving_class(project, seg)
        b = rc.GetBootStrapMethod(name)
        t = time.time(); b.Simulate(); simulated = time.time() - t
        t = time.time(); b.Save(); saved = time.time() - t
        print(f"{seg}: simulated in {simulated:.1f} s, saved in {saved:.1f} s; "
              f"scaled mean {float(b.ScaledReserves.Mean(0)):,.0f}")
        rc.UnloadChildren()
    rc = reserving_class(project, TOTAL_CLASS)
    c = rc.GetBootStrapConsolidation(CONSOLIDATION)
    t = time.time(); c.Consolidate(); consolidated = time.time() - t
    t = time.time(); c.Save(); saved = time.time() - t
    print(f"Total: consolidated in {consolidated:.1f} s, saved in {saved:.1f} s; "
          f"scaled mean {float(c.ScaledReserves.Mean(0)):,.0f}")
    rc.UnloadChildren()


# ----- capture ----------------------------------------------------------------------

def summary(reserves, origins):
    return {
        "mean": [float(reserves.Mean(o)) for o in range(origins + 1)],
        "standard_error": [float(reserves.StandardError(o)) for o in range(origins + 1)],
        "percentiles": {f"{p:.3f}": [float(reserves.PercentileValue(o, p)) for o in range(origins + 1)]
                        for p in PERCENTILES},
    }


def per_simulation(reserves, n):
    ranks = [int(reserves.TotalRank(s)) for s in range(1, n + 1)]
    if sorted(ranks) != list(range(1, n + 1)):
        raise RuntimeError("TotalRank over 1..n is not a permutation of 1..n")
    return ranks, [float(reserves.SimulatedValue(0, s)) for s in range(1, n + 1)]


def fitted_cumulative(observed, ratios):
    """The ODP fit: each row's latest value run back by the selected ratios and forward to ultimate."""
    width = len(ratios) + 1
    rows = []
    for row in observed:
        fit = [0.0] * width
        last = len(row) - 1
        fit[last] = row[last]
        for j in range(last - 1, -1, -1):
            fit[j] = fit[j + 1] / ratios[j]
        for j in range(last, width - 1):
            fit[j + 1] = fit[j] * ratios[j]
        rows.append(fit)
    return rows


def plausibility(latest, dfm_ultimates, target_reserves, scaled):
    mean, se = scaled["mean"][0], scaled["standard_error"][0]
    cv = se / mean if mean else math.inf
    origins = []
    for lat, ult, tgt in zip(latest, dfm_ultimates, target_reserves):
        dfm_res = ult - lat
        if abs(tgt - dfm_res) <= 1e-6 * max(1.0, abs(dfm_res)):
            ok = True
        else:
            ok = dfm_res > 0 and 0.5 * dfm_res <= tgt <= 2.0 * dfm_res
        origins.append({"dfm_reserve": dfm_res, "target_reserve": tgt, "ok": ok})
    checks = {"mean_positive": mean > 0, "cv_between_2_and_60_percent": 0.02 <= cv <= 0.60,
              "targets_within_half_to_double_of_dfm": all(o["ok"] for o in origins)}
    return {"total_scaled_mean": mean, "total_scaled_cv": cv, "origins": origins,
            "checks": checks, "passed": all(checks.values())}


def residual(value):
    """ResQ marks a cell with no residual by -99000000000; the fixture writes None."""
    value = float(value)
    return None if value <= NO_RESIDUAL else value


def capture_segment(project, seg, name):
    rc = reserving_class(project, seg)
    b = rc.GetBootStrapMethod(name)
    dfm = b.DFMMethod
    n_orig = int(b.OriginCount)
    n = int(b.SimulationCount)
    total_dev = int(b.TotalDevelopmentPeriods)
    observed = [[float(b.TriangleValues(o, d)) for d in range(1, int(b.DevelopmentCount(o - 1)) + 1)]
                for o in range(1, n_orig + 1)]
    ratios = [float(dfm.SelectedRatioValues(d)) for d in range(1, total_dev)]
    unscaled, scaled = b.UnscaledReserves, b.ScaledReserves
    if not (unscaled.HaveReserves and scaled.HaveReserves):
        raise RuntimeError(f"{seg}: no saved reserves; run the 'run' mode first")
    latest = [float(b.LatestValues(o)) for o in range(1, n_orig + 1)]
    dfm_ult = [float(b.UltimateValues(o)) for o in range(1, n_orig + 1)]
    targets = [float(b.TargetReserveValues(o)) for o in range(1, n_orig + 1)]
    scaled_summary = summary(scaled, n_orig)
    scaled_ranks, scaled_totals = per_simulation(scaled, n)
    unscaled_ranks, unscaled_totals = per_simulation(unscaled, n)
    out = {
        "reserving_class": BASE + "\\" + seg,
        "name": str(b.Name),
        "settings": {
            "model_type": MODELS.get(int(b.ModelType), int(b.ModelType)),
            "estimation_variance": DISTRIBUTIONS.get(int(b.EstimationVariance), int(b.EstimationVariance)),
            "process_variance": DISTRIBUTIONS.get(int(b.ProcessVariance), int(b.ProcessVariance)),
            "prevent_negative_data": bool(b.PreventNegativeData),
            "use_normal_on_negative_mean": bool(b.UseNormalOnNegMean),
            "bias_adjustment": int(b.BiasAdjustment),
            "random_seed": int(b.RandomSeed),
            "simulation_count": n,
            "target_ultimate": str(b.TargetUltimate.Name) if b.TargetUltimate else None,
            "dfm": str(dfm.Name),
            "origin_length": int(b.OriginLength),
            "development_length": int(b.DevelopmentLength),
            "total_development_periods": total_dev,
        },
        "origin_labels": [str(b.OriginLabel(o)) for o in range(1, n_orig + 1)],
        "observed_triangle": observed,
        "selected_ratios": ratios,
        "predicted_values": fitted_cumulative(observed, ratios),
        "residuals_by_type": {str(t): [[residual(b.ResidualsByType(o, d, t)) for d in range(1, total_dev + 1)]
                                       for o in range(1, n_orig + 1)] for t in range(5)},
        "residual_adjustment": float(b.ResidualAdjustment),
        "scale_values_residuals_unsmoothed": [float(b.ScaleValues_Residuals(d, 0)) for d in range(1, total_dev + 1)],
        "latest_values": latest,
        "dfm_ultimates": dfm_ult,
        "target_ultimates": vector_values(b.TargetUltimate),
        "target_reserve_values": targets,
        "target_scaling_methods": [SCALING.get(int(b.TargetScalingMethods(o)), int(b.TargetScalingMethods(o)))
                                   for o in range(1, n_orig + 1)],
        "unscaled": summary(unscaled, n_orig),
        "scaled": scaled_summary,
        "scaled_total_rank": scaled_ranks,
        "scaled_total_by_simulation": scaled_totals,
        "unscaled_total_rank": unscaled_ranks,
        "unscaled_total_by_simulation": unscaled_totals,
        "scaled_by_origin_first_simulations": [[float(scaled.SimulatedValue(o, s)) for o in range(1, n_orig + 1)]
                                               for s in range(1, min(n, ORIGIN_SIMS) + 1)],
        "plausibility": plausibility(latest, dfm_ult, targets, scaled_summary),
    }
    rc.UnloadChildren()
    return out


def capture_consolidation(project):
    rc = reserving_class(project, TOTAL_CLASS)
    c = rc.GetBootStrapConsolidation(CONSOLIDATION)
    m = int(c.IncludedMethodCount)
    n = int(c.SimulationCount)
    n_orig = int(c.OriginCount)
    methods = []
    for i in range(1, m + 1):
        meth = c.IncludedMethods(i)
        methods.append({"reserving_class": str(meth.ReservingClass.Name) if meth.ReservingClass else None,
                        "method": str(meth.Name), "factor": float(c.Factors(i))})

    def matrix(getter):
        return [[float(getter(i, j)) for j in range(1, m + 1)] for i in range(1, m + 1)]

    scaled = c.ScaledReserves
    if not scaled.HaveReserves:
        raise RuntimeError("Total: no saved consolidated reserves; run the 'run' mode first")
    ranks = [[int(c.ConsolidationRanks(i, s)) for s in range(1, n + 1)] for i in range(1, m + 1)]
    for i, row in enumerate(ranks, start=1):
        if sorted(row) != list(range(1, n + 1)):
            raise RuntimeError(f"ConsolidationRanks({i}, 1..n) is not a permutation of 1..n")
    totals_rank, totals = per_simulation(scaled, n)
    saved_summary = summary(scaled, n_orig)
    # A reloaded consolidation keeps its ranks and consolidated reserves but not
    # the achieved correlations or the reserves by class, which read as zero.
    # Consolidate again in memory (never saved) and prove it reproduces the
    # saved run before reading them.
    c.Consolidate()
    scaled = c.ScaledReserves
    again_rank, again = per_simulation(scaled, n)
    again_ranks = [[int(c.ConsolidationRanks(i, s)) for s in range(1, n + 1)] for i in range(1, m + 1)]
    if again != totals or again_rank != totals_rank or again_ranks != ranks:
        raise RuntimeError("Total: an in-memory Consolidate did not reproduce the saved run")
    out = {
        "reserving_class": BASE + "\\" + TOTAL_CLASS,
        "name": str(c.Name),
        "settings": {
            "base_triangle_type": str(c.BaseTriangleType.Name) if c.BaseTriangleType else None,
            "output_vector": str(c.OutputVector.Name) if c.OutputVector else None,
            "consolidate_based_on_scaled": bool(c.ConsolidateBasedOnScaled),
            "consolidate_reserve_cashflows": bool(c.ConsolidateReserveCashflows),
            "correlation_type": CORRELATION.get(int(c.CorrelationType), int(c.CorrelationType)),
            "dependency_type": DEPENDENCY.get(int(c.DependencyType), int(c.DependencyType)),
            "degrees_of_freedom": int(c.DegreesOfFreedom),
            "random_seed": int(c.RandomSeed),
            "simulation_count": n,
        },
        "included_methods": methods,
        "origin_labels": [str(c.OriginLabel(o)) for o in range(1, n_orig + 1)],
        "target_correlations": matrix(c.MethodCorrelations),
        "adjusted_correlations": matrix(c.MethodCorrelations_Adjusted),
        "achieved_rank_correlations": matrix(c.MethodCorrelations_AchievedRank),
        "achieved_linear_correlations": matrix(c.MethodCorrelations_AchievedLinear),
        "consolidation_ranks": ranks,
        "scaled_total_by_simulation": totals,
        "scaled_total_rank": totals_rank,
        "scaled": saved_summary,
        "reserves_by_class_first_simulations": [
            [[float(c.SimulatedReservesByClass(i, o, s)) for o in range(1, n_orig + 2)] for i in range(1, m + 1)]
            for s in range(1, min(n, ORIGIN_SIMS) + 1)],
    }
    rc.UnloadChildren()
    return out


def capture(project, out_path, data_changes):
    segments = []
    for seg, name in SEGMENTS.items():
        t = time.time()
        segments.append(capture_segment(project, seg, name))
        p = segments[-1]["plausibility"]
        print(f"{seg}: captured in {time.time() - t:.1f} s; scaled mean {p['total_scaled_mean']:,.0f}, "
              f"CV {p['total_scaled_cv']:.1%}, plausible={p['passed']} {p['checks']}")
    t = time.time()
    consolidation = capture_consolidation(project)
    print(f"Total: captured in {time.time() - t:.1f} s; scaled mean {consolidation['scaled']['mean'][0]:,.0f}, "
          f"SE {consolidation['scaled']['standard_error'][0]:,.0f}")
    fixture = {
        "source": f"ResQ project {PROJECT}, {BASE}; captured over COM by tools/resq_bootstrap_capture.py",
        "captured_on": datetime.date.today().isoformat(),
        "conventions": {
            "summary_index_0": "total; 1..n are origins in order",
            "simulation_index": "1-based in ResQ; lists here hold simulation s at position s-1",
            "rank": "1..n, rank 1 is the smallest total reserve",
            "percentile_keys": "fractions, as PercentileValue takes them",
            "predicted_values": "cumulative ODP fit computed from observed_triangle and selected_ratios",
            "reserves_by_class_first_simulations": "[simulation][method][origins 1..n, then the total]",
        },
        "data_changes": data_changes,
        "segments": segments,
        "consolidation": consolidation,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8") as handle:
        json.dump(fixture, handle, separators=(",", ":"))
    print(f"wrote {out_path} ({out_path.stat().st_size:,} bytes)")
    return fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["targets", "run", "capture"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixture path for capture")
    parser.add_argument("--changes", type=Path, help="JSON written by 'targets' to embed as data_changes")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    app = connect()
    try:
        project = app.Projects().Item(PROJECT)
        if str(project.Name) != PROJECT:
            raise RuntimeError("refusing to run outside the fake project")
        if args.mode == "targets":
            changes = point_targets_at_dfm(project)
            print(json.dumps({"f92_after": {k: [round(x) for x in v["f92_after"]] for k, v in changes.items()}}))
            if args.changes:
                args.changes.write_text(json.dumps(changes, indent=1), encoding="utf-8")
        elif args.mode == "run":
            run(project)
        else:
            changes = json.loads(args.changes.read_text(encoding="utf-8")) if args.changes else None
            capture(project, args.out, changes)
    finally:
        app.Disconnect()


if __name__ == "__main__":
    main()
