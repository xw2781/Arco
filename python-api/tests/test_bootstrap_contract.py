"""Bootstrap contract parity against live ResQ output.

``fixtures/resq_bootstrap_f72a.json`` was captured read-only over the ResQ COM
API from project ``NJ_Annual_Prod_202605_Fake``, reserving class
``PRNJ - PA\\PA\\All States\\Direct Group\\COL``.  It pins both Over-dispersed
Poisson models plus one full ``Simulate()`` run so the stochastic layer has a
reference distribution to be checked against.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from arcrho_api.bootstrap_contract import (
    BST_JSON_FORMAT,
    BootstrapContractError,
    apply_owned_patch,
    bootstrap_output_variants,
    bootstrap_percentile_ladder,
    bootstrap_precedent_names,
    bootstrap_simulated_reserves,
    build_bootstrap_output_sidecar,
    normalize_bootstrap_method,
    recalculate_bootstrap_method,
    summarize_bootstrap_simulations,
)
from arcrho_api.bootstrap_simulation import (
    BootstrapCalculationError,
    BootstrapSimulationOptions,
    calculate_residuals,
    fit_dfm_projection,
    observed_triangle,
    percentile_key,
    reserve_histogram,
    scale_simulated_reserves,
    simulate_bootstrap,
    summarize_reserves,
    total_reserve_ranks,
)
from arcrho_api.io import persisted_json_text


FIXTURE = Path(__file__).parent / "fixtures" / "resq_bootstrap_f72a.json"
RESIDUAL_KEYS = (
    "unscaled",
    "unscaled_bias_adjusted",
    "scaled",
    "scaled_bias_adjusted",
    "scaled_bias_adjusted_zero_average",
)


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _case(fixture: dict, key: str) -> dict:
    return fixture["methods"][key]


def _fit_for(case: dict):
    return fit_dfm_projection(
        observed_triangle(case["observed_triangle"]),
        case["selected_ratios"],
        case["total_development_periods"],
    )


def _relative(actual: float, expected: float) -> float:
    return abs(actual - expected) / max(abs(expected), 1e-9)


# ---------------------------------------------------------------------------
# Deterministic layer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["odp_single_scale", "odp_varying_scale"])
def test_fitted_cumulative_matches_resq_predicted_values(fixture, key):
    case = _case(fixture, key)
    fit = _fit_for(case)
    for origin, row in enumerate(case["predicted_values"]):
        for column, expected in enumerate(row):
            if expected is None:
                continue
            assert _relative(fit.fitted_cumulative[origin][column], expected) <= 1e-12


@pytest.mark.parametrize("key", ["odp_single_scale", "odp_varying_scale"])
def test_residual_grids_match_resq_residuals_by_type(fixture, key):
    case = _case(fixture, key)
    residuals = calculate_residuals(_fit_for(case), model_type=case["model_type"])
    for index, name in enumerate(RESIDUAL_KEYS):
        expected_grid = case["residuals_by_type"][str(index)]
        compared = 0
        for origin, row in enumerate(expected_grid):
            for column, expected in enumerate(row):
                actual = residuals.grids[name][origin][column]
                if expected is None:
                    assert actual is None, f"{name} ({origin},{column}) should be excluded"
                    continue
                assert actual is not None, f"{name} ({origin},{column}) missing"
                assert _relative(actual, expected) <= 1e-9
                compared += 1
        assert compared == 53, f"{name} should cover the 53 usable residuals"


@pytest.mark.parametrize("key", ["odp_single_scale", "odp_varying_scale"])
def test_scale_parameters_and_counts_match_resq(fixture, key):
    case = _case(fixture, key)
    residuals = calculate_residuals(_fit_for(case), model_type=case["model_type"])
    # ResQ counts observed data cells, not usable residuals: 55 rather than 53.
    assert residuals.data_point_count == case["data_point_count"]
    assert residuals.parameter_count == case["parameter_count"]
    assert _relative(residuals.bias_factor, math.sqrt(55 / 36)) <= 1e-12
    for column, expected in enumerate(case["scale_values_residuals_unsmoothed"]):
        assert _relative(residuals.scale_unsmoothed[column], expected) <= 1e-9
    assert abs(residuals.residual_adjustment - case["residual_adjustment"]) <= 1e-12


def test_zero_residuals_are_excluded_not_counted(fixture):
    """The saturated cells drop out of the residual pool but stay data points."""

    case = _case(fixture, "odp_single_scale")
    fit = _fit_for(case)
    residuals = calculate_residuals(fit, model_type=case["model_type"])
    assert len(residuals.pool) == 53
    assert residuals.data_point_count == 55
    oldest_last = len(case["observed_triangle"][0]) - 1
    assert residuals.unscaled[0][oldest_last] is None
    assert residuals.unscaled[-1][0] is None


def test_varying_scale_uses_column_data_cell_count(fixture):
    """The first column divides by 10 observed cells, not by its 9 residuals."""

    case = _case(fixture, "odp_varying_scale")
    fit = _fit_for(case)
    residuals = calculate_residuals(fit, model_type="odp_varying_scale")
    column = [residuals.unscaled[w][0] for w in range(fit.origin_count)]
    usable = [value for value in column if value is not None]
    assert len(usable) == 9
    cells = sum(1 for row in case["observed_triangle"] if len(row) > 0)
    assert cells == 10
    expected = math.sqrt(sum(v * v for v in usable) / cells * (55 / 36))
    assert _relative(residuals.scale_unsmoothed[0], expected) <= 1e-12
    assert _relative(residuals.scale_unsmoothed[0], case["scale_values_residuals_unsmoothed"][0]) <= 1e-9


def test_varying_scale_tail_falls_back_to_lower_of_previous_two(fixture):
    case = _case(fixture, "odp_varying_scale")
    residuals = calculate_residuals(_fit_for(case), model_type="odp_varying_scale")
    scale = residuals.scale_unsmoothed
    assert scale[9] == pytest.approx(min(scale[7], scale[8]))
    assert scale[10] == pytest.approx(min(scale[7], scale[8]))


def test_zero_cells_are_observations_not_blanks(fixture):
    """An origin with zero losses, or zeros before its first loss, keeps every cell."""

    case = _case(fixture, "odp_single_scale")
    rows = deepcopy(case["observed_triangle"])
    rows[0] = [0.0] * len(rows[0])
    rows[1][:2] = [0.0, 0.0]
    triangle = observed_triangle(rows + [[None]])
    assert [len(row) for row in triangle[:-1]] == [len(row) for row in rows]
    assert triangle[-1] == []

    fit = fit_dfm_projection(triangle[:-1], case["selected_ratios"], case["total_development_periods"])
    assert fit.fitted_cumulative[0] == [0.0] * case["total_development_periods"]
    residuals = calculate_residuals(fit, model_type=case["model_type"])
    # As in ResQ: no residual where the cumulative, or the one before it, is zero.
    assert all(residuals.excluded[0][: len(rows[0])])
    assert residuals.excluded[1][:3] == [True, True, True]
    assert residuals.unscaled[1][3] is not None
    # The zero origin has no fitted level, and the last period, observed only in
    # that origin, keeps no data point: neither carries a parameter.
    assert residuals.parameter_count == (len(rows) - 1) + (len(rows[0]) - 1) - 1
    assert residuals.data_point_count == sum(len(row) for row in rows) - len(rows[0]) - 3

    options = BootstrapSimulationOptions(simulation_count=200, random_seed=7)
    run = simulate_bootstrap(fit, residuals, options)
    assert all(reserve[0] == 0.0 for reserve in run.reserves)
    assert all(math.isfinite(total) for total in run.totals)


def test_an_excluded_link_ratio_drops_the_cell_it_leads_into(fixture):
    case = _case(fixture, "odp_single_scale")
    fit = _fit_for(case)
    plain = calculate_residuals(fit, model_type=case["model_type"])
    excluded = [[False] * 10 for _ in range(10)]
    excluded[2][4] = True
    residuals = calculate_residuals(fit, model_type=case["model_type"], excluded_ratios=excluded)
    assert residuals.excluded[2][5] and residuals.unscaled[2][5] is None
    assert not residuals.excluded[2][4]
    assert residuals.data_point_count == plain.data_point_count - 1
    assert residuals.parameter_count == plain.parameter_count


def test_mack_model_is_rejected_until_implemented(fixture):
    case = _case(fixture, "odp_single_scale")
    with pytest.raises(BootstrapCalculationError, match="Mack"):
        calculate_residuals(_fit_for(case), model_type="mack")


# ---------------------------------------------------------------------------
# Simulation layer
# ---------------------------------------------------------------------------


def _run(fixture, count: int, seed: int):
    case = _case(fixture, "odp_single_scale")
    reference = fixture["simulation_reference"]
    fit = _fit_for(case)
    residuals = calculate_residuals(fit, model_type=case["model_type"])
    options = BootstrapSimulationOptions(
        simulation_count=count,
        random_seed=seed,
        estimation_variance=reference["estimation_variance"],
        process_variance=reference["process_variance"],
        prevent_negative_data=reference["prevent_negative_data"],
        negative_mean_action=reference["negative_mean_action"],
    )
    return fit, residuals, simulate_bootstrap(fit, residuals, options)


def test_simulation_is_deterministic_for_a_seed(fixture):
    _, _, first = _run(fixture, 200, 4242)
    _, _, second = _run(fixture, 200, 4242)
    assert first.reserves == second.reserves
    _, _, other = _run(fixture, 200, 4243)
    assert other.reserves != first.reserves


def test_simulated_total_matches_resq_within_sampling_error(fixture):
    """ResQ's own 10,000-simulation run is itself a sample; compare on z."""

    reference = fixture["simulation_reference"]
    _, _, run = _run(fixture, 20000, 20260805)
    summary = summarize_reserves(run.reserves)
    resq_mean = reference["unscaled"]["mean"][0]
    resq_sd = reference["unscaled"]["standard_error"][0]
    resq_count = reference["simulation_count"]

    combined = math.sqrt(
        resq_sd**2 / resq_count + summary["standard_error"][0] ** 2 / len(run.reserves)
    )
    assert abs(summary["mean"][0] - resq_mean) / combined <= 3.0
    assert _relative(summary["standard_error"][0], resq_sd) <= 0.05


def test_simulated_percentiles_track_resq_across_the_body(fixture):
    reference = fixture["simulation_reference"]
    _, _, run = _run(fixture, 20000, 20260805)
    summary = summarize_reserves(run.reserves)
    resq_sd = reference["unscaled"]["standard_error"][0]
    for step in range(5, 100, 5):
        expected = reference["unscaled"]["percentiles"][f"{step / 100:.2f}"][0]
        actual = summary["percentiles"][str(step)][0]
        assert abs(actual - expected) <= 0.12 * resq_sd, f"percentile {step}%"


def test_expected_reserve_tracks_the_dfm_reserve(fixture):
    fit, _, run = _run(fixture, 20000, 7)
    summary = summarize_reserves(run.reserves)
    for origin, dfm_reserve in enumerate(fit.dfm_reserves):
        error = summary["standard_error"][origin + 1] / math.sqrt(len(run.reserves))
        assert abs(summary["mean"][origin + 1] - dfm_reserve) <= max(6.0 * error, 1.0)


def test_projection_anchors_on_the_pseudo_latest_diagonal(fixture):
    """The observed diagonal would understate the newest origin's variance."""

    case = _case(fixture, "odp_single_scale")
    reference = fixture["simulation_reference"]
    fit = _fit_for(case)
    residuals = calculate_residuals(fit, model_type=case["model_type"])
    options = BootstrapSimulationOptions(
        simulation_count=4000, random_seed=11, negative_mean_action="normal"
    )
    run = simulate_bootstrap(fit, residuals, options)
    summary = summarize_reserves(run.reserves)
    newest = summary["standard_error"][fit.origin_count]
    assert newest == pytest.approx(reference["unscaled"]["standard_error"][-1], rel=0.06)


def test_forecast_cells_do_not_build_on_earlier_simulated_cells(fixture):
    """ResQ takes each future cell's mean from the chain ladder, not the simulated cumulative.

    With no estimation noise every origin's variance is then exactly the sum of
    phi * |mean| over the deterministic chain ladder; building each mean on the
    cells already simulated misses it by about 4% on the newest origin.
    """

    case = _case(fixture, "odp_single_scale")
    fit = _fit_for(case)
    residuals = calculate_residuals(fit, model_type=case["model_type"])
    options = BootstrapSimulationOptions(
        simulation_count=20000,
        random_seed=5,
        estimation_variance="none",
        process_variance="gamma",
        prevent_negative_data=False,
        negative_mean_action="normal",
    )
    summary = summarize_reserves(simulate_bootstrap(fit, residuals, options).reserves)
    phi = [value * value for value in residuals.scale_unsmoothed]
    for origin in range(fit.origin_count):
        expected = fit.observed_cumulative[origin][fit.latest_column[origin]]
        variance = 0.0
        for column in range(fit.latest_column[origin], fit.total_development_periods - 1):
            mean = expected * (fit.selected_ratios[column] - 1.0)
            expected += mean
            variance += phi[column + 1] * abs(mean)
        if variance:
            assert summary["standard_error"][origin + 1] == pytest.approx(
                math.sqrt(variance), rel=0.03
            ), f"origin {origin + 1}"


# ---------------------------------------------------------------------------
# Scaling
# ---------------------------------------------------------------------------


def test_additive_scaling_hits_the_target_and_preserves_dispersion(fixture):
    reference = fixture["simulation_reference"]
    _, _, run = _run(fixture, 3000, 99)
    targets = reference["target_reserve_values"]
    scaled = scale_simulated_reserves(
        run.reserves,
        target_means=targets,
        scaling_methods=reference["target_scaling_methods"],
    )
    unscaled_summary = summarize_reserves(run.reserves)
    scaled_summary = summarize_reserves(scaled)
    for origin, target in enumerate(targets):
        assert scaled_summary["mean"][origin + 1] == pytest.approx(target, abs=1e-6)
        assert scaled_summary["standard_error"][origin + 1] == pytest.approx(
            unscaled_summary["standard_error"][origin + 1], rel=1e-12
        )


def test_multiplicative_scaling_preserves_the_coefficient_of_variation(fixture):
    _, _, run = _run(fixture, 2000, 5)
    origins = len(run.reserves[0])
    targets = [-1000.0] * origins
    scaled = scale_simulated_reserves(
        run.reserves, target_means=targets, scaling_methods=["multiplicative"] * origins
    )
    unscaled_summary = summarize_reserves(run.reserves)
    scaled_summary = summarize_reserves(scaled)
    for origin in range(origins):
        mean = unscaled_summary["mean"][origin + 1]
        if abs(mean) < 1e-6 or unscaled_summary["standard_error"][origin + 1] == 0:
            continue
        expected = abs(unscaled_summary["standard_error"][origin + 1] / mean * targets[origin])
        assert scaled_summary["standard_error"][origin + 1] == pytest.approx(expected, rel=1e-9)


def test_unscaled_scaling_is_a_passthrough(fixture):
    _, _, run = _run(fixture, 500, 3)
    origins = len(run.reserves[0])
    scaled = scale_simulated_reserves(
        run.reserves, target_means=[0.0] * origins, scaling_methods=["unscaled"] * origins
    )
    assert scaled == [list(row) for row in run.reserves]


# ---------------------------------------------------------------------------
# Payload contract
# ---------------------------------------------------------------------------


def _snapshot_from_fixture(case: dict) -> dict:
    ratio_count = case["total_development_periods"] - 1
    return {
        "name": "F 25 - Incurred DFM Bootstrap",
        "origin_labels": case["origin_labels"],
        "development_labels": [f"{5 + 12 * index}m" for index in range(ratio_count)],
        "origin_length": 12,
        "development_length": 12,
        "total_development_periods": case["total_development_periods"],
        "observed_triangle": case["observed_triangle"],
        "selected_ratios": case["selected_ratios"],
        "refit_ratios": [index < ratio_count - 1 for index in range(ratio_count)],
        "ratio_average_base": ["volume"] * ratio_count,
        "ratio_average_periods": [None] * ratio_count,
        "ratio_exclude_high_low": [False] * ratio_count,
        "excluded_ratios": [],
        "dfm_ultimate_values": [],
    }


def _seed_payload(case: dict, reference: dict) -> dict:
    return {
        "json_format": BST_JSON_FORMAT,
        "details_tab": {
            "name": case["name"],
            "output_type": "F 00 - Ultimate Net Loss",
            "dataset_category": "F Net Loss",
            "origin_length": 12,
            "development_length": 12,
            "model_type": case["model_type"],
            "dfm_method": "F 25 - Incurred DFM Bootstrap",
        },
        "residuals_tab": {},
        "simulation_tab": {
            "estimation_variance": reference["estimation_variance"],
            "process_variance": reference["process_variance"],
            "simulation_count": 400,
            "random_seed": reference["random_seed"],
            "prevent_negative_data": reference["prevent_negative_data"],
            "negative_mean_action": reference["negative_mean_action"],
        },
        "results_tab": {
            "target_ultimate": "F 92 - Current Qtr Selected",
            "target_scaling_methods": reference["target_scaling_methods"],
        },
        "output_tab": {},
        "method_metadata": {},
    }


def _target_snapshot(case: dict, reference: dict) -> dict:
    return {
        "name": "F 92 - Current Qtr Selected",
        "origin_labels": case["origin_labels"],
        "values": [
            target + latest
            for target, latest in zip(
                reference["target_reserve_values"], reference["dfm_latest_values"]
            )
        ],
    }


@pytest.fixture(scope="module")
def method(fixture) -> dict:
    case = _case(fixture, "odp_single_scale")
    reference = fixture["simulation_reference"]
    return recalculate_bootstrap_method(
        _seed_payload(case, reference),
        dfm_snapshot=_snapshot_from_fixture(case),
        target_snapshot=_target_snapshot(case, reference),
        timestamp="2026-08-05T00:00:00Z",
    )


def test_recalculate_is_deterministic_and_normalization_is_idempotent(fixture, method):
    case = _case(fixture, "odp_single_scale")
    reference = fixture["simulation_reference"]
    again = recalculate_bootstrap_method(
        _seed_payload(case, reference),
        dfm_snapshot=_snapshot_from_fixture(case),
        target_snapshot=_target_snapshot(case, reference),
        timestamp="2026-08-05T00:00:00Z",
    )
    assert persisted_json_text(again) == persisted_json_text(method)
    assert persisted_json_text(normalize_bootstrap_method(method)) == persisted_json_text(method)


def test_recalculated_residuals_and_counts_match_resq(fixture, method):
    case = _case(fixture, "odp_single_scale")
    residuals = method["residuals_tab"]
    assert residuals["data_point_count"] == 55
    assert residuals["parameter_count"] == 19
    assert residuals["scale_values_residuals"]["selected"][0] == pytest.approx(
        case["scale_values_residuals_unsmoothed"][0], rel=1e-6
    )
    grid = residuals["residual_values"]["scaled_bias_adjusted_zero_average"]
    expected = case["residuals_by_type"]["4"]
    for origin, row in enumerate(expected):
        for column, value in enumerate(row):
            if value is None:
                continue
            # The persisted grid is stored at the canonical six-decimal
            # precision; the calculation behind it is exact.
            assert grid[origin][column] == pytest.approx(value, abs=1e-6)


def test_additive_target_scaling_publishes_the_target_ultimate(fixture, method):
    reference = fixture["simulation_reference"]
    for origin, latest in enumerate(reference["dfm_latest_values"]):
        target_ultimate = reference["target_reserve_values"][origin] + latest
        assert method["results_tab"]["bootstrap_ultimate"][origin] == pytest.approx(
            target_ultimate, abs=1e-4
        )


def test_precedents_cover_the_dfm_and_the_target(method):
    assert bootstrap_precedent_names(method) == [
        "F 25 - Incurred DFM Bootstrap",
        "F 92 - Current Qtr Selected",
    ]


def test_output_sidecar_matches_the_canonical_dataset_sidecar_shape(method):
    sidecar = build_bootstrap_output_sidecar(
        method,
        project_name="NJ",
        reserving_class="COL",
        csv_file="F 72 A@12.csv",
        notes="hello",
        user="tester",
        timestamp="2026-08-05T00:00:00Z",
    )
    assert sidecar["method_type"] == "Bootstrap"
    assert sidecar["source_kind"] == "bootstrap"
    assert sidecar["data_format"] == "Vector"
    assert sidecar["calculated"] is True
    assert sidecar["notes"] == "hello"
    assert sidecar["csv_file"] == "F 72 A@12.csv"
    assert sidecar["period_length"] == method["details_tab"]["origin_length"]
    assert sidecar["development_labels"] == ["Ultimate"]
    assert sidecar["publication_revision"] == method["method_metadata"]["publication_revision"]
    # The dependency graph is keyed by dataset name, so precedents are stored in
    # the same {"dataset_type_name": ...} shape every other method writes.
    assert sidecar["precedents"] == [
        {"dataset_name": "F 25 - Incurred DFM Bootstrap"},
        {"dataset_name": "F 92 - Current Qtr Selected"},
    ]
    assert sidecar["audit_log"][-1]["action"] == "Insert"


def test_output_sidecar_accepts_resolved_graph_precedents(method):
    # A DFM that publishes under a different dataset name must reach the graph
    # by that dataset name, not by its method name.
    sidecar = build_bootstrap_output_sidecar(
        method,
        project_name="NJ",
        reserving_class="COL",
        csv_file="F 72 A@12.csv",
        precedents=["F 25 Ultimate", "F 92 - Current Qtr Selected"],
    )
    assert sidecar["precedents"] == [
        {"dataset_name": "F 25 Ultimate"},
        {"dataset_name": "F 92 - Current Qtr Selected"},
    ]


def test_output_variants_expose_the_native_length(method):
    variants = bootstrap_output_variants(method)
    assert set(variants) == {12}
    assert len(variants[12]) == len(method["results_tab"]["origin_labels"])


def test_persisted_payload_stays_small_enough_for_a_network_drive(method):
    text = persisted_json_text(method)
    assert len(text) < 200 * 1024
    assert "simulation_summary" in text
    # The simulated reserve array itself must never be persisted: no stored
    # list is as long as the simulation count.
    count = method["simulation_tab"]["simulation_count"]

    def _longest(node) -> int:
        if isinstance(node, dict):
            return max((_longest(value) for value in node.values()), default=0)
        if isinstance(node, list):
            return max([len(node)] + [_longest(value) for value in node])
        return 0

    assert _longest(method) < count


def test_changing_the_dfm_clears_the_embedded_snapshot(method):
    patch = dict(method)
    patch["details_tab"] = {**method["details_tab"], "dfm_method": "Another DFM"}
    rebased = apply_owned_patch(method, patch)
    assert rebased["details_tab"]["dfm_method"] == "Another DFM"
    assert rebased["details_tab"]["dfm_snapshot"]["observed_triangle"] == []
    assert rebased["details_tab"]["dfm_source_revision"] == ""


def test_a_first_calculation_keeps_owned_lists_given_before_the_snapshot(fixture):
    # A first save and a ResQ import both hand over owned per-origin and
    # per-period lists before any DFM snapshot is embedded; none may be cut.
    case = _case(fixture, "odp_single_scale")
    reference = fixture["simulation_reference"]
    seed = _seed_payload(case, reference)
    origins = len(case["origin_labels"])
    periods = case["total_development_periods"]
    seed["results_tab"]["target_scaling_methods"] = ["multiplicative"] * origins
    seed["results_tab"]["target_cvs"] = [0.25] * origins
    seed["residuals_tab"]["user_scale_values_residuals"] = [None, 30.0] + [None] * (periods - 2)
    method = recalculate_bootstrap_method(
        seed,
        dfm_snapshot=_snapshot_from_fixture(case),
        target_snapshot=_target_snapshot(case, reference),
        timestamp="2026-08-05T00:00:00Z",
    )
    assert method["results_tab"]["target_scaling_methods"] == ["multiplicative"] * origins
    assert method["results_tab"]["target_cvs"] == [0.25] * origins
    assert method["residuals_tab"]["user_scale_values_residuals"][1] == 30.0
    assert method["residuals_tab"]["scale_values_residuals"]["selected"][1] == 30.0


def test_owned_patch_preserves_derived_state_when_only_owned_values_change(method):
    patch = dict(method)
    patch["simulation_tab"] = {**method["simulation_tab"], "simulation_count": 5000}
    rebased = apply_owned_patch(method, patch)
    assert rebased["simulation_tab"]["simulation_count"] == 5000
    assert (
        rebased["method_metadata"]["owned_revision"]
        != method["method_metadata"]["owned_revision"]
    )
    assert (
        rebased["residuals_tab"]["residual_values"]
        == method["residuals_tab"]["residual_values"]
    )


def test_unknown_json_format_is_rejected(method):
    bad = dict(method)
    bad["json_format"] = "arcrho-bootstrap-method-by-tab-v0"
    with pytest.raises(BootstrapContractError):
        normalize_bootstrap_method(bad)


# ---------------------------------------------------------------------------
# Summary for every Results view, and the per-simulation output
# ---------------------------------------------------------------------------


HALF_PERCENT_KEYS = [percentile_key(step / 2) for step in range(0, 201)]


def test_percentile_keys_are_percent_text():
    assert HALF_PERCENT_KEYS[:3] == ["0", "0.5", "1"]
    assert "99.5" in HALF_PERCENT_KEYS
    assert HALF_PERCENT_KEYS[-1] == "100"
    assert len(HALF_PERCENT_KEYS) == 201


def test_summary_carries_the_half_percent_ladder_ultimates_and_histogram(method):
    results = method["results_tab"]
    summary = results["simulation_summary"]
    count = summary["simulation_count"]
    latest = results["latest_values"]
    width = len(results["origin_labels"]) + 1
    for block_name in ("unscaled", "scaled"):
        block = summary[block_name]
        assert list(block["percentiles"]) == HALF_PERCENT_KEYS
        for key in HALF_PERCENT_KEYS:
            assert len(block["percentiles"][key]) == width
        total_ladder = [block["percentiles"][key][0] for key in HALF_PERCENT_KEYS]
        assert total_ladder == sorted(total_ladder)
        assert block["percentiles"]["0"] == block["minimum"]
        assert block["percentiles"]["100"] == block["maximum"]
        # Ultimate = latest + reserve, so its mean shifts and its spread does not.
        assert block["ultimate_mean"][0] == pytest.approx(sum(latest) + block["mean"][0], abs=1e-5)
        for origin, value in enumerate(latest):
            assert block["ultimate_mean"][origin + 1] == pytest.approx(
                value + block["mean"][origin + 1], abs=1e-5
            )
        for got, want in zip(block["ultimate_standard_error"], block["standard_error"]):
            assert got == pytest.approx(want, abs=1e-5)
        histogram = block["histogram"]
        assert len(histogram["counts"]) == 40
        assert sum(histogram["counts"]) == count
        assert histogram["lower"] == block["minimum"][0]
        assert histogram["upper"] == block["maximum"][0]


def test_simulated_reserves_carry_totals_and_a_rank_permutation(method):
    simulations = bootstrap_simulated_reserves(method)
    count = method["simulation_tab"]["simulation_count"]
    origins = len(method["results_tab"]["origin_labels"])
    assert simulations["simulation_count"] == count
    assert simulations["random_seed"] == method["simulation_tab"]["random_seed"]
    assert simulations["origin_labels"] == method["results_tab"]["origin_labels"]
    for block_name in ("unscaled", "scaled"):
        block = simulations[block_name]
        assert len(block["reserves"]) == count
        assert all(len(row) == origins for row in block["reserves"])
        assert block["totals"] == [sum(row) for row in block["reserves"]]
        assert sorted(block["total_ranks"]) == list(range(1, count + 1))
        by_rank = sorted(range(count), key=lambda sim: block["total_ranks"][sim])
        ordered = [block["totals"][sim] for sim in by_rank]
        assert ordered == sorted(ordered)
    # Deterministic: a consolidation rebuilding the run gets the same simulations.
    assert bootstrap_simulated_reserves(method) == simulations


def test_stored_summary_equals_one_recomputed_from_the_simulations(method):
    summary = summarize_bootstrap_simulations(bootstrap_simulated_reserves(method))
    patch = deepcopy(method)
    patch["results_tab"]["simulation_summary"] = summary
    recomputed = normalize_bootstrap_method(patch)["results_tab"]["simulation_summary"]
    assert persisted_json_text(recomputed) == persisted_json_text(
        method["results_tab"]["simulation_summary"]
    )


def test_a_finer_ladder_extends_the_stored_one(method):
    ladder = bootstrap_percentile_ladder(method, 0.01)
    summary = method["results_tab"]["simulation_summary"]
    keys = [percentile_key(index * 100 / 10000) for index in range(10001)]
    assert keys[:3] == ["0", "0.01", "0.02"] and keys[-2:] == ["99.99", "100"]
    for block_name in ("scaled", "unscaled"):
        assert list(ladder[block_name]) == keys
        # Every half percent the stored summary holds reads the same.
        for key in HALF_PERCENT_KEYS:
            assert ladder[block_name][key] == summary[block_name]["percentiles"][key]


def test_a_finer_ladder_refuses_a_run_it_cannot_reproduce(method):
    drifted = deepcopy(method)
    drifted["results_tab"]["simulation_summary"]["scaled"]["mean"][0] += 1
    with pytest.raises(BootstrapContractError, match="simulate again"):
        bootstrap_percentile_ladder(drifted, 0.1)
    with pytest.raises(BootstrapContractError, match="divides 100"):
        bootstrap_percentile_ladder(method, 0.03)


def test_a_summary_saved_before_the_half_percent_ladder_still_opens(method):
    patch = deepcopy(method)
    old = patch["results_tab"]["simulation_summary"]
    for block_name in ("unscaled", "scaled"):
        block = old[block_name]
        block["percentiles"] = {str(step): block["percentiles"][str(step)] for step in range(0, 101, 5)}
        for key in ("ultimate_mean", "ultimate_standard_error", "histogram"):
            block.pop(key)
    normalized = normalize_bootstrap_method(patch)["results_tab"]["simulation_summary"]
    for block_name in ("unscaled", "scaled"):
        block = normalized[block_name]
        assert list(block["percentiles"]) == [str(step) for step in range(0, 101, 5)]
        assert block["ultimate_mean"] == []
        assert block["histogram"] == {"lower": 0, "upper": 0, "counts": []}


def test_histogram_closes_its_last_bin_and_handles_a_degenerate_sample():
    histogram = reserve_histogram([0.0, 1.0, 2.0, 4.0], bins=4)
    assert histogram == {"lower": 0.0, "upper": 4.0, "counts": [1, 1, 1, 1]}
    flat = reserve_histogram([5.0, 5.0, 5.0], bins=40)
    assert flat["counts"][0] == 3 and sum(flat["counts"]) == 3


def test_tied_totals_rank_by_simulation_order():
    assert total_reserve_ranks([3.0, 1.0, 3.0, 2.0]) == [3, 1, 4, 2]
