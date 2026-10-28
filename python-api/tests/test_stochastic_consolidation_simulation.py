"""Arco's Stochastic Consolidation calculation against ResQ's Total consolidation.

``fixtures/resq_bootstrap_consolidation_total.json.gz`` holds the five segment
bootstraps and the Total consolidation of the fake project, saved in ResQ
(plan step 1).  Fed ResQ's own segment simulations and ranks, Arco's
combination reproduces ResQ exactly.  With Arco's own ranks (ResQ's random
stream is not reproducible, plan step 2) the achieved correlations and the
consolidated spread match within sampling error.
"""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

import pytest

from arcrho_api.bootstrap_contract import bootstrap_simulated_reserves, recalculate_bootstrap_method
from arcrho_api.bootstrap_simulation import BST_HISTOGRAM_BINS, BST_SUMMARY_PERCENTILES, percentile_key
from arcrho_api.stochastic_consolidation_simulation import (
    SCON_CORRELATION_OPTIONS,
    SCON_DEPENDENCY_TYPES,
    ConsolidationOptions,
    StochasticConsolidationError,
    adjusted_correlation_matrix,
    cholesky_lower,
    consolidate_simulations,
    generate_consolidation_ranks,
    repair_correlation_matrix,
    run_stochastic_consolidation,
    summarize_consolidated_simulations,
    symmetric_eigen,
    target_correlation_matrix,
)


FIXTURE = Path(__file__).parent / "fixtures" / "resq_bootstrap_consolidation_total.json.gz"
REL_TOL = 1e-9
Z_LIMIT = 3.0


@pytest.fixture(scope="module")
def fixture() -> dict:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def reference(fixture) -> dict:
    """The consolidation, its segments in included order as consolidation inputs, and its options."""

    consolidation = fixture["consolidation"]
    by_class = {seg["reserving_class"].rsplit("\\", 1)[-1]: seg for seg in fixture["segments"]}
    segments = [by_class[m["reserving_class"]] for m in consolidation["included_methods"]]
    settings = consolidation["settings"]
    options = ConsolidationOptions(
        simulation_count=settings["simulation_count"],
        random_seed=settings["random_seed"],
        correlation_option=settings["correlation_type"],
        dependency_type=settings["dependency_type"],
        degrees_of_freedom=settings["degrees_of_freedom"],
        target_correlations=consolidation["target_correlations"],
        factors=[m["factor"] for m in consolidation["included_methods"]],
    )
    # Only each simulation's total is captured for all 10,000 runs, so each
    # segment enters as a one-column reserve array: rule 3 is the same per column.
    inputs = [
        {
            "scaled": {
                "reserves": [[value] for value in seg["scaled_total_by_simulation"]],
                "total_ranks": seg["scaled_total_rank"],
            }
        }
        for seg in segments
    ]
    return {"consolidation": consolidation, "segments": segments, "inputs": inputs, "options": options}


def _moments(values):
    n = len(values)
    mean = math.fsum(values) / n
    m2 = math.fsum((v - mean) ** 2 for v in values) / n
    m4 = math.fsum((v - mean) ** 4 for v in values) / n
    se_sd = math.sqrt(max(m4 - m2 * m2, 0.0) / (4.0 * m2 * n)) if m2 > 0 else 0.0
    return mean, math.sqrt(m2), se_sd


def _synthetic_segments(count: int, origins: int = 3, seed: int = 7) -> list[dict]:
    """Three independent segments with distinct origin vectors, shaped like bootstrap output."""

    import random

    rng = random.Random(seed)
    segments = []
    for index in range(3):
        reserves = [
            [rng.gammavariate(2.0 + index + w, 100.0 * (index + 1)) for w in range(origins)]
            for _ in range(count)
        ]
        totals = [sum(row) for row in reserves]
        order = sorted(range(count), key=lambda s: (totals[s], s))
        ranks = [0] * count
        for rank, s in enumerate(order, start=1):
            ranks[s] = rank
        segments.append({
            "origin_labels": [str(2020 + w) for w in range(origins)],
            "latest_values": [1000.0 * (w + 1) for w in range(origins)],
            "scaled": {"reserves": reserves, "totals": totals, "total_ranks": ranks},
        })
    return segments


# ---------------------------------------------------------------------------
# Rule 3 against ResQ, exactly


def test_resq_ranks_reproduce_resq_consolidated_totals_exactly(reference):
    consolidation = reference["consolidation"]
    run = consolidate_simulations(reference["inputs"], reference["options"], ranks=consolidation["consolidation_ranks"])
    want = consolidation["scaled_total_by_simulation"]
    assert len(run["totals"]) == len(want)
    for s, (got, expected) in enumerate(zip(run["totals"], want)):
        assert abs(got - expected) <= REL_TOL * max(1.0, abs(expected)), f"simulation {s + 1}"
    assert run["total_ranks"] == consolidation["scaled_total_rank"]


def test_resq_ranks_reproduce_resq_summary_and_achieved_correlations(reference):
    consolidation = reference["consolidation"]
    summary = run_stochastic_consolidation(
        reference["inputs"], reference["options"], ranks=consolidation["consolidation_ranks"]
    )
    resq = consolidation["scaled"]
    assert summary["scaled"]["mean"][0] == pytest.approx(resq["mean"][0], rel=1e-12)
    assert summary["scaled"]["standard_error"][0] == pytest.approx(resq["standard_error"][0], rel=1e-12)
    for key, values in resq["percentiles"].items():
        got = summary["scaled"]["percentiles"].get(percentile_key(100 * float(key)))
        if got is not None:
            assert got[0] == pytest.approx(values[0], rel=1e-12), key
    for name in ("achieved_rank_correlations", "achieved_linear_correlations"):
        for got_row, want_row in zip(summary[name], consolidation[name]):
            for got, want in zip(got_row, want_row):
                assert got == pytest.approx(want, abs=1e-9), name


def test_adjusted_matrix_for_the_reference_target_equals_resq(reference):
    adjusted = adjusted_correlation_matrix(
        target_correlation_matrix("specified", 5, reference["consolidation"]["target_correlations"])
    )
    for got_row, want_row in zip(adjusted, reference["consolidation"]["adjusted_correlations"]):
        for got, want in zip(got_row, want_row):
            assert got == pytest.approx(want, abs=1e-12)


# ---------------------------------------------------------------------------
# Arco's own ranks, within sampling error


def test_arco_ranks_achieve_the_reference_target_rank_correlations(reference):
    options = reference["options"]
    target = target_correlation_matrix("specified", 5, options.target_correlations)
    ranks = generate_consolidation_ranks(adjusted_correlation_matrix(target), options.simulation_count, options.random_seed)
    summary = summarize_consolidated_simulations(
        consolidate_simulations(reference["inputs"], options, ranks=ranks)
    )
    limit = Z_LIMIT / math.sqrt(options.simulation_count - 1)
    for i in range(5):
        assert sorted(ranks[i]) == list(range(1, options.simulation_count + 1))
        for j in range(i + 1, 5):
            assert abs(summary["achieved_rank_correlations"][i][j] - target[i][j]) <= limit, (i, j)


def test_arco_consolidated_spread_matches_resq_within_sampling_error(reference):
    """Plan step 5 "Done when": ResQ's segment simulations with Arco's ranks."""

    consolidation = reference["consolidation"]
    run = consolidate_simulations(reference["inputs"], reference["options"])
    arco_mean, arco_sd, arco_se = _moments(run["totals"])
    resq_mean, resq_sd, resq_se = _moments(consolidation["scaled_total_by_simulation"])
    # Every rank row is a permutation, so the mean does not depend on the ranks.
    assert arco_mean == pytest.approx(resq_mean, rel=1e-12)
    assert resq_sd == pytest.approx(consolidation["scaled"]["standard_error"][0], rel=1e-9)
    assert abs(arco_sd - resq_sd) / math.hypot(arco_se, resq_se) <= Z_LIMIT


def test_independent_gives_near_zero_and_fully_correlated_near_one():
    count = 10000
    limit = Z_LIMIT / math.sqrt(count - 1)
    for option, expected in (("independent", 0.0), ("as_generated", 0.0)):
        adjusted = adjusted_correlation_matrix(target_correlation_matrix(option, 4))
        ranks = generate_consolidation_ranks(adjusted, count, 11)
        summary = summarize_consolidated_simulations({
            "simulation_count": count, "random_seed": 11, "correlation_option": option,
            "dependency_type": "normal", "degrees_of_freedom": 20, "factors": [1.0] * 4,
            "target_correlations": [], "adjusted_correlations": adjusted, "ranks": ranks,
            "reserves": [[0.0]] * count, "totals": [0.0] * count, "segment_totals": [[float(r) for r in row] for row in ranks],
        })
        for i in range(4):
            for j in range(i + 1, 4):
                assert abs(summary["achieved_rank_correlations"][i][j] - expected) <= limit
    adjusted = adjusted_correlation_matrix(target_correlation_matrix("fully_correlated", 4))
    ranks = generate_consolidation_ranks(adjusted, count, 11)
    from arcrho_api.stochastic_consolidation_simulation import _correlation_matrix

    achieved = _correlation_matrix(ranks)
    for i in range(4):
        for j in range(i + 1, 4):
            assert achieved[i][j] > 0.999


def test_fully_correlated_is_the_all_ones_matrix_through_the_repair():
    adjusted = adjusted_correlation_matrix(target_correlation_matrix("fully_correlated", 5))
    for i in range(5):
        assert adjusted[i][i] == 1.0
        for j in range(5):
            if i != j:
                # ResQ reported 0.9999990000008 for every off-diagonal cell.
                assert adjusted[i][j] == pytest.approx(0.9999990000008, abs=1e-13)


def test_student_t_with_few_degrees_of_freedom_moves_together_more_in_the_upper_tail():
    count = 20000
    target = [[1.0, 0.38], [0.38, 1.0]]
    adjusted = adjusted_correlation_matrix(target)
    threshold = int(0.95 * count)

    def co_exceedance(ranks):
        return sum(1 for a, b in zip(ranks[0], ranks[1]) if a > threshold and b > threshold) / count

    normal = co_exceedance(generate_consolidation_ranks(adjusted, count, 5))
    student = co_exceedance(
        generate_consolidation_ranks(adjusted, count, 5, dependency_type="student_t", degrees_of_freedom=3)
    )
    assert student > normal + 3.0 * math.sqrt(normal / count)


def test_gamma_ranks_reverse_uniform_ranks_for_an_identity_matrix():
    identity = [[1.0, 0.0], [0.0, 1.0]]
    uniform = generate_consolidation_ranks(identity, 500, 3, dependency_type="uniform")
    gamma = generate_consolidation_ranks(identity, 500, 3, dependency_type="gamma")
    for u_row, g_row in zip(uniform, gamma):
        assert [501 - rank for rank in u_row] == g_row


@pytest.mark.parametrize("dependency_type", ("uniform", "gamma"))
def test_uniform_and_gamma_achieve_positive_correlation_near_the_target(dependency_type):
    adjusted = adjusted_correlation_matrix([[1.0, 0.38], [0.38, 1.0]])
    ranks = generate_consolidation_ranks(adjusted, 10000, 9, dependency_type=dependency_type)
    from arcrho_api.stochastic_consolidation_simulation import _correlation_matrix

    # ResQ's own runs gave 0.376 (Uniform) and 0.424 (Gamma) for this target.
    assert abs(_correlation_matrix(ranks)[0][1] - 0.38) < 0.08


def test_same_seed_same_ranks_different_seed_different_ranks():
    adjusted = adjusted_correlation_matrix([[1.0, 0.5], [0.5, 1.0]])
    assert generate_consolidation_ranks(adjusted, 200, 42) == generate_consolidation_ranks(adjusted, 200, 42)
    assert generate_consolidation_ranks(adjusted, 200, 42) != generate_consolidation_ranks(adjusted, 200, 43)


# ---------------------------------------------------------------------------
# Matrix repair


def test_a_non_positive_definite_target_is_repaired_by_eigenvalue_clipping():
    numpy = pytest.importorskip("numpy")
    target = [[1.0, 0.9, 0.9], [0.9, 1.0, -0.9], [0.9, -0.9, 1.0]]
    converted = numpy.array([[1.0 if i == j else 2.0 * math.sin(math.pi * target[i][j] / 6.0) for j in range(3)] for i in range(3)])
    assert numpy.linalg.eigvalsh(converted).min() < 0.0
    values, vectors = numpy.linalg.eigh(converted)
    rebuilt = vectors @ numpy.diag(numpy.maximum(values, 1e-6)) @ vectors.T
    scale = numpy.sqrt(numpy.diag(rebuilt))
    expected = rebuilt / numpy.outer(scale, scale)

    adjusted = adjusted_correlation_matrix(target)
    for i in range(3):
        assert adjusted[i][i] == 1.0
        for j in range(3):
            assert adjusted[i][j] == pytest.approx(float(expected[i][j]), abs=1e-12)
            assert adjusted[i][j] == adjusted[j][i]
    cholesky_lower(adjusted)  # positive definite now
    assert min(symmetric_eigen(adjusted)[0]) > 0.0


def test_a_positive_definite_matrix_passes_through_unchanged():
    matrix = [[1.0, 0.3, 0.1], [0.3, 1.0, 0.2], [0.1, 0.2, 1.0]]
    assert repair_correlation_matrix(matrix) == matrix


def test_cholesky_reproduces_the_matrix():
    matrix = adjusted_correlation_matrix([[1.0, 0.38, 0.1], [0.38, 1.0, -0.2], [0.1, -0.2, 1.0]])
    lower = cholesky_lower(matrix)
    for i in range(3):
        for j in range(3):
            assert math.fsum(lower[i][k] * lower[j][k] for k in range(3)) == pytest.approx(matrix[i][j], abs=1e-14)


def test_the_upper_triangle_of_a_target_is_authoritative():
    target = target_correlation_matrix("specified", 3, [[9, 0.2, 0.3], [0.7, 9, 0.4], [0.8, 0.9, 9]])
    assert target == [[1.0, 0.2, 0.3], [0.2, 1.0, 0.4], [0.3, 0.4, 1.0]]


# ---------------------------------------------------------------------------
# Combination and summary


@pytest.mark.parametrize("option", SCON_CORRELATION_OPTIONS)
@pytest.mark.parametrize("dependency_type", SCON_DEPENDENCY_TYPES)
def test_consolidated_mean_is_the_factor_weighted_sum_of_segment_means(option, dependency_type):
    count = 400
    segments = _synthetic_segments(count)
    factors = [1.0, 0.5, 2.0]
    options = ConsolidationOptions(
        simulation_count=count,
        random_seed=17,
        correlation_option=option,
        dependency_type=dependency_type,
        degrees_of_freedom=4,
        target_correlations=[[1, 0.5, 0.2], [0, 1, 0.3], [0, 0, 1]],
        factors=factors,
    )
    run = consolidate_simulations(segments, options)
    summary = summarize_consolidated_simulations(run)
    origins = len(segments[0]["scaled"]["reserves"][0])
    for w in range(origins):
        expected = math.fsum(
            f * math.fsum(row[w] for row in seg["scaled"]["reserves"]) / count for f, seg in zip(factors, segments)
        )
        assert summary["scaled"]["mean"][w + 1] == pytest.approx(expected, rel=1e-12)
    expected_total = math.fsum(f * math.fsum(seg["scaled"]["totals"]) / count for f, seg in zip(factors, segments))
    assert summary["scaled"]["mean"][0] == pytest.approx(expected_total, rel=1e-12)
    assert math.fsum(seg["share_of_mean"] for seg in summary["segments"]) == pytest.approx(1.0, rel=1e-12)


def test_the_whole_origin_vector_moves_with_the_rank():
    count = 300
    segments = _synthetic_segments(count)
    factors = [1.0, -1.0, 3.0]
    options = ConsolidationOptions(simulation_count=count, random_seed=5, correlation_option="specified",
                                   target_correlations=[[1, 0.4, 0], [0, 1, 0.2], [0, 0, 1]], factors=factors)
    run = consolidate_simulations(segments, options)
    at_rank = []
    for seg in segments:
        lookup = [0] * (count + 1)
        for s, rank in enumerate(seg["scaled"]["total_ranks"]):
            lookup[rank] = s
        at_rank.append(lookup)
    for s in range(count):
        for w in range(3):
            expected = math.fsum(
                f * seg["scaled"]["reserves"][at_rank[c][run["ranks"][c][s]]][w]
                for c, (f, seg) in enumerate(zip(factors, segments))
            )
            assert run["reserves"][s][w] == pytest.approx(expected, rel=1e-12, abs=1e-9)
        assert run["totals"][s] == pytest.approx(math.fsum(run["reserves"][s]), rel=1e-12)


def test_summary_has_the_bootstrap_summary_shape_and_a_diversification_view():
    count = 500
    segments = _synthetic_segments(count)
    options = ConsolidationOptions(simulation_count=count, random_seed=1, correlation_option="specified",
                                   target_correlations=[[1, 0.3, 0.3], [0, 1, 0.3], [0, 0, 1]], factors=[1, 1, 1])
    summary = run_stochastic_consolidation(segments, options)
    scaled = summary["scaled"]
    assert len(scaled["mean"]) == 4
    assert set(scaled["percentiles"]) == {percentile_key(step) for step in BST_SUMMARY_PERCENTILES}
    assert len(scaled["histogram"]["counts"]) == BST_HISTOGRAM_BINS
    assert sum(scaled["histogram"]["counts"]) == count
    # Ultimates are the factor-weighted latest diagonal plus the reserve.
    assert scaled["ultimate_mean"][1] == pytest.approx(3000.0 + scaled["mean"][1], rel=1e-12)
    assert len(summary["segments"]) == 3
    for seg in summary["segments"]:
        assert seg["cv"] == pytest.approx(seg["standard_error"] / seg["mean"])
    diversification = summary["diversification"]
    assert diversification["total_standard_error"] == pytest.approx(scaled["standard_error"][0], rel=1e-12)
    assert diversification["sum_of_standalone_standard_errors"] > diversification["total_standard_error"]
    assert diversification["benefit"] > 0.0


def test_two_real_bootstraps_consolidate_end_to_end(fixture):
    """A consolidation takes its segments straight from step 4's per-simulation function."""

    from test_bootstrap_segment_parity import _dfm_snapshot, _payload, _target_snapshot

    by_class = {seg["reserving_class"].rsplit("\\", 1)[-1]: seg for seg in fixture["segments"]}
    count = 1000
    inputs = []
    for name in ("CMPxCAT", "COL"):
        segment = by_class[name]
        payload = _payload(segment)
        payload["simulation_tab"]["simulation_count"] = count
        method = recalculate_bootstrap_method(
            payload,
            dfm_snapshot=_dfm_snapshot(segment),
            target_snapshot=_target_snapshot(segment),
            timestamp="2026-09-23T00:00:00Z",
            simulate=False,
        )
        inputs.append(bootstrap_simulated_reserves(method))
    options = ConsolidationOptions(simulation_count=count, random_seed=1514684455, correlation_option="specified",
                                   target_correlations=[[1, 0.34], [0.34, 1]], factors=[1.0, 1.0])
    summary = run_stochastic_consolidation(inputs, options)
    assert len(summary["scaled"]["mean"]) == 1 + len(by_class["COL"]["origin_labels"])
    expected = math.fsum(math.fsum(seg["scaled"]["totals"]) / count for seg in inputs)
    assert summary["scaled"]["mean"][0] == pytest.approx(expected, rel=1e-12)
    assert summary["latest_values"] == pytest.approx(
        [a + b for a, b in zip(inputs[0]["latest_values"], inputs[1]["latest_values"])]
    )


# ---------------------------------------------------------------------------
# Refusals


def test_a_segment_with_a_different_simulation_count_is_refused():
    segments = _synthetic_segments(100)
    segments[1]["scaled"]["reserves"] = segments[1]["scaled"]["reserves"][:50]
    with pytest.raises(StochasticConsolidationError, match="Segment 2 has 50 simulations"):
        consolidate_simulations(segments, ConsolidationOptions(simulation_count=100, random_seed=1))


def test_segments_with_different_origins_are_refused():
    segments = _synthetic_segments(100)
    segments[2]["origin_labels"] = ["a", "b", "c"]
    with pytest.raises(StochasticConsolidationError, match="Segment 3's origin periods"):
        consolidate_simulations(segments, ConsolidationOptions(simulation_count=100, random_seed=1))


def test_a_shorter_segment_lines_up_at_the_latest_origin():
    """HO's ten years join Oil's full history: the short segment is zero in its missing years."""

    count = 100
    long_history = _synthetic_segments(count, origins=5, seed=3)[0]
    short = _synthetic_segments(count, origins=2, seed=5)[1]
    short["origin_labels"] = ["2023", "2024"]
    long_history["origin_labels"] = [str(2020 + w) for w in range(5)]
    options = ConsolidationOptions(simulation_count=count, random_seed=11, correlation_option="independent")
    combined = consolidate_simulations([long_history, short], options)

    assert combined["origin_labels"] == ["2020", "2021", "2022", "2023", "2024"]
    assert combined["origin_offsets"] == [0, 3]
    long_at = {rank: s for s, rank in enumerate(long_history["scaled"]["total_ranks"])}
    short_at = {rank: s for s, rank in enumerate(short["scaled"]["total_ranks"])}
    for s in range(count):
        a = long_history["scaled"]["reserves"][long_at[combined["ranks"][0][s]]]
        b = short["scaled"]["reserves"][short_at[combined["ranks"][1][s]]]
        assert combined["reserves"][s] == pytest.approx(a[:3] + [a[3] + b[0], a[4] + b[1]])
    assert combined["latest_values"] == pytest.approx([1000.0, 2000.0, 3000.0, 5000.0, 7000.0])


def test_a_shorter_segment_must_hold_the_latest_origins():
    segments = _synthetic_segments(10, origins=3)[:2]
    segments[1]["origin_labels"] = ["2020", "2021"]
    segments[1]["scaled"]["reserves"] = [row[:2] for row in segments[1]["scaled"]["reserves"]]
    segments[1]["latest_values"] = segments[1]["latest_values"][:2]
    with pytest.raises(StochasticConsolidationError, match="are not the latest origins"):
        consolidate_simulations(segments, ConsolidationOptions(simulation_count=10, random_seed=1))


def test_a_correlation_outside_minus_one_to_one_is_refused():
    with pytest.raises(StochasticConsolidationError, match="between -1 and 1"):
        target_correlation_matrix("specified", 2, [[1, 1.2], [1.2, 1]])


def test_ranks_that_are_not_permutations_are_refused():
    segments = _synthetic_segments(10)
    bad = [list(range(1, 11)), list(range(1, 11)), [1] * 10]
    with pytest.raises(StochasticConsolidationError, match="permutation"):
        consolidate_simulations(segments, ConsolidationOptions(simulation_count=10, random_seed=1), ranks=bad)
