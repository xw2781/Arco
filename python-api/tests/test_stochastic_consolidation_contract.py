"""The persisted contract of a Stochastic Consolidation method.

Segments are the fake project's five reference bootstraps from
``fixtures/resq_bootstrap_consolidation_total.json.gz`` (plan step 1), built
the way ``test_bootstrap_segment_parity`` builds them but run at a small
simulation count so the whole module stays fast.
"""

from __future__ import annotations

import gzip
import json
import math
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest

from arcrho_api.bootstrap_contract import bootstrap_simulated_reserves, recalculate_bootstrap_method
from arcrho_api.dataset_index_contract import build_dataset_index_payload
from arcrho_api.io import persisted_json_text
from arcrho_api.sidecar_core_contract import dependency_entries, finalize_sidecar
from arcrho_api.stochastic_consolidation_contract import (
    SCON_JSON_FORMAT,
    StochasticConsolidationContractError,
    apply_owned_patch,
    bootstrap_segment_revision,
    build_stochastic_consolidation_output_sidecar,
    consolidate_stochastic_method,
    consolidate_stochastic_method_with_ladder,
    normalize_stochastic_consolidation_method,
    run_input_revision,
    stale_segments,
    stochastic_consolidation_output_variants,
)
from arcrho_api.stochastic_consolidation_simulation import (
    ConsolidationOptions,
    consolidate_simulations,
    summarize_consolidated_simulations,
)
from test_bootstrap_segment_parity import _dfm_snapshot, _payload, _target_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "resq_bootstrap_consolidation_total.json.gz"
SIMULATIONS = 300
STAMP = "2026-09-23T00:00:00Z"
GROUP = "PRNJ - PA\\PA\\All States\\Direct Group"
HOST = f"{GROUP}\\Total"
BASE_TYPE = "Net Loss--Incurred"
TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / "test"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="module")
def reference() -> dict:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as handle:
        fixture = json.load(handle)
    by_class = {seg["reserving_class"].rsplit("\\", 1)[-1]: seg for seg in fixture["segments"]}
    consolidation = fixture["consolidation"]
    return {
        "consolidation": consolidation,
        "segments": [by_class[m["reserving_class"]] for m in consolidation["included_methods"]],
    }


@pytest.fixture(scope="module")
def bootstraps(reference) -> list[dict]:
    methods = []
    for segment in reference["segments"]:
        payload = _payload(segment)
        payload["simulation_tab"]["simulation_count"] = SIMULATIONS
        methods.append(
            recalculate_bootstrap_method(
                payload,
                dfm_snapshot=_dfm_snapshot(segment),
                target_snapshot=_target_snapshot(segment),
                timestamp=STAMP,
                simulate=False,
            )
        )
    return methods


def _consolidation(reference) -> dict:
    source = reference["consolidation"]
    settings = source["settings"]
    return {
        "json_format": SCON_JSON_FORMAT,
        "details_tab": {
            "name": source["name"],
            "output_type": "F 00 - Ultimate Net Loss",
            "base_triangle_type": BASE_TYPE,
            "origin_length": 12,
            "development_length": 12,
            "random_seed": settings["random_seed"],
        },
        "segments_tab": {
            "segments": [
                {
                    "reserving_class": f"{GROUP}\\{item['reserving_class']}",
                    "method_name": segment["name"],
                    "factor": item["factor"],
                }
                for item, segment in zip(source["included_methods"], reference["segments"])
            ]
        },
        "correlation_tab": {
            "correlation_option": settings["correlation_type"],
            "dependency_type": settings["dependency_type"],
            "degrees_of_freedom": settings["degrees_of_freedom"],
            "target_correlations": deepcopy(source["target_correlations"]),
        },
    }


def _inputs(bootstraps: list[dict]) -> list[dict]:
    return [{"bootstrap": method, "base_triangle_type": BASE_TYPE} for method in bootstraps]


@pytest.fixture(scope="module")
def consolidated(reference, bootstraps) -> dict:
    return consolidate_stochastic_method(_consolidation(reference), _inputs(bootstraps), timestamp=STAMP)


def test_normalization_round_trips_byte_identically(consolidated):
    text = persisted_json_text(consolidated)
    again = normalize_stochastic_consolidation_method(json.loads(text))
    assert persisted_json_text(again) == text


def test_revisions_do_not_depend_on_layout_or_key_order(consolidated):
    reordered = json.loads(json.dumps(consolidated, sort_keys=True, separators=(",", ":")))
    reordered["details_tab"] = dict(reversed(list(reordered["details_tab"].items())))
    again = normalize_stochastic_consolidation_method(reordered)
    for key in ("owned_revision", "derived_revision", "publication_revision"):
        assert again["method_metadata"][key] == consolidated["method_metadata"][key]


def test_consolidation_stores_the_run_it_describes(reference, bootstraps, consolidated):
    source = reference["consolidation"]
    method = consolidated
    assert method["details_tab"]["simulation_count"] == SIMULATIONS
    segments = method["segments_tab"]["segments"]
    assert [s["bootstrap_revision"] for s in segments] == [bootstrap_segment_revision(b) for b in bootstraps]
    assert method["results_tab"]["input_revision"] == run_input_revision(method)
    assert method["results_tab"]["origin_labels"] == reference["segments"][0]["origin_labels"]

    # The stored summary is what the step-5 calculation gives for the same inputs.
    options = ConsolidationOptions(
        simulation_count=SIMULATIONS,
        random_seed=source["settings"]["random_seed"],
        correlation_option=source["settings"]["correlation_type"],
        dependency_type=source["settings"]["dependency_type"],
        degrees_of_freedom=source["settings"]["degrees_of_freedom"],
        target_correlations=source["target_correlations"],
        factors=[m["factor"] for m in source["included_methods"]],
    )
    expected = summarize_consolidated_simulations(
        consolidate_simulations([bootstrap_simulated_reserves(b) for b in bootstraps], options)
    )
    summary = method["results_tab"]["simulation_summary"]
    assert summary["scaled"]["mean"][0] == pytest.approx(expected["scaled"]["mean"][0], rel=1e-9)
    assert summary["scaled"]["standard_error"][0] == pytest.approx(
        expected["scaled"]["standard_error"][0], rel=1e-9
    )
    assert len(summary["segments"]) == 5
    assert summary["diversification"]["benefit"] > 0

    adjusted = method["correlation_tab"]["adjusted_correlations"]
    assert adjusted[0][4] == pytest.approx(2 * math.sin(math.pi * 0.38 / 6), abs=1e-6)
    assert adjusted[4][0] == adjusted[0][4]

    # The output is the combined latest diagonal plus the consolidated mean reserve.
    latest = method["results_tab"]["latest_values"]
    ultimate = method["results_tab"]["consolidation_ultimate"]
    for index, value in enumerate(ultimate):
        assert value == pytest.approx(latest[index] + summary["scaled"]["mean"][index + 1], abs=1e-5)


def test_a_run_with_its_ladder_stores_the_same_run_and_every_finer_step(reference, bootstraps, consolidated):
    # The ladder comes from the run's own simulations and is never stored: the
    # payload is the plain run's, and the ladder holds every stored half-percent
    # step with the stored values, so a page can serve every finer interval.
    method, ladder = consolidate_stochastic_method_with_ladder(
        _consolidation(reference), _inputs(bootstraps), timestamp=STAMP
    )
    assert persisted_json_text(method) == persisted_json_text(consolidated)
    assert ladder["interval"] == 0.01
    steps = ladder["scaled"]
    assert len(steps) == 10001
    stored = consolidated["results_tab"]["simulation_summary"]["scaled"]["percentiles"]
    for key, values in stored.items():
        assert steps[key] == values
    assert len(steps["99.99"]) == len(stored["50"])


def test_a_mismatched_base_type_is_refused_with_the_method_named(reference, bootstraps):
    inputs = _inputs(bootstraps)
    inputs[2] = {"bootstrap": bootstraps[2], "base_triangle_type": "Net Loss--Paid"}
    with pytest.raises(StochasticConsolidationContractError, match=r"All States\\Direct Group\\COL / F 72 A"):
        consolidate_stochastic_method(_consolidation(reference), inputs, timestamp=STAMP)


def test_a_mismatched_simulation_count_is_refused_with_the_method_named(reference, bootstraps):
    other = deepcopy(bootstraps[3])
    other["simulation_tab"]["simulation_count"] = SIMULATIONS + 1
    inputs = _inputs(bootstraps)
    inputs[3] = {"bootstrap": other}
    with pytest.raises(StochasticConsolidationContractError, match=r"MP\+PIP / F 72 A.* runs 301 simulations"):
        consolidate_stochastic_method(_consolidation(reference), inputs, timestamp=STAMP)


def test_a_bootstrap_supplied_for_the_wrong_segment_is_refused(reference, bootstraps):
    other = deepcopy(bootstraps[0])
    other["details_tab"]["name"] = "F 72B - Bootstrap Net Incurred no PV"
    inputs = _inputs(bootstraps)
    inputs[0] = {"bootstrap": other}
    with pytest.raises(StochasticConsolidationContractError, match="BI Total / F 72 A.*is 'F 72B"):
        consolidate_stochastic_method(_consolidation(reference), inputs, timestamp=STAMP)


def test_out_of_range_target_and_duplicate_segment_are_refused(reference):
    payload = _consolidation(reference)
    payload["correlation_tab"]["target_correlations"][0][1] = 1.5
    with pytest.raises(StochasticConsolidationContractError, match="between -1 and 1"):
        normalize_stochastic_consolidation_method(payload)
    payload = _consolidation(reference)
    payload["segments_tab"]["segments"].append(dict(payload["segments_tab"]["segments"][0]))
    with pytest.raises(StochasticConsolidationContractError, match="more than once"):
        normalize_stochastic_consolidation_method(payload)


def test_target_matrix_keeps_the_upper_triangle_and_mirrors_it(reference):
    payload = _consolidation(reference)
    target = payload["correlation_tab"]["target_correlations"]
    target[3][1] = 0.9  # below the diagonal: ignored
    method = normalize_stochastic_consolidation_method(payload)
    matrix = method["correlation_tab"]["target_correlations"]
    assert matrix[1][3] == matrix[3][1] == target[1][3]
    assert all(matrix[i][i] == 1 for i in range(5))


def test_a_changed_or_missing_bootstrap_is_reported_stale(bootstraps, consolidated):
    assert stale_segments(consolidated, bootstraps) == []
    changed = deepcopy(bootstraps[1])
    changed["simulation_tab"]["random_seed"] += 1
    current = [bootstraps[0], changed, None, *bootstraps[3:]]
    assert [(s["method_name"], s["reason"]) for s in stale_segments(consolidated, current)] == [
        (bootstraps[1]["details_tab"]["name"], "changed"),
        (bootstraps[2]["details_tab"]["name"], "missing"),
    ]
    # A display-only change on the bootstrap page does not make it stale.
    shown = deepcopy(bootstraps[0])
    shown["residuals_tab"]["show_scale_values"] = not shown["residuals_tab"]["show_scale_values"]
    assert bootstrap_segment_revision(shown) == bootstrap_segment_revision(bootstraps[0])


def test_owned_patch_keeps_consumed_revisions_only_for_the_same_segment(consolidated):
    patch = deepcopy(consolidated)
    segments = patch["segments_tab"]["segments"]
    segments[0]["factor"] = 2
    segments[4] = {"reserving_class": f"{GROUP}\\Other", "method_name": "Another Bootstrap", "factor": 1}
    patched = apply_owned_patch(consolidated, patch, timestamp=STAMP)
    revisions = [s["bootstrap_revision"] for s in patched["segments_tab"]["segments"]]
    original = [s["bootstrap_revision"] for s in consolidated["segments_tab"]["segments"]]
    assert revisions[:4] == original[:4]
    assert revisions[4] == ""
    assert patched["segments_tab"]["segments"][0]["factor"] == 2
    assert patched["results_tab"] == consolidated["results_tab"]
    assert run_input_revision(patched) != patched["results_tab"]["input_revision"]
    assert patched["method_metadata"]["owned_revision"] != consolidated["method_metadata"]["owned_revision"]


def test_output_sidecar_links_each_segment_across_classes(consolidated):
    sidecar = build_stochastic_consolidation_output_sidecar(
        consolidated,
        project_name="NJ_Annual_Prod_202605_Fake",
        reserving_class=HOST,
        csv_file="ArcRhoVec@consolidation.csv",
        timestamp=STAMP,
        user="tester",
    )
    assert sidecar["method_type"] == "Stochastic Consolidation"
    assert sidecar["source_kind"] == "stochastic_consolidation"
    assert sidecar["calculated"] is True
    assert sidecar["publication_revision"] == consolidated["method_metadata"]["publication_revision"]
    assert sidecar["precedents"] == [
        {"dataset_name": s["method_name"], "method_type": "Bootstrap", "reserving_class": s["reserving_class"]}
        for s in consolidated["segments_tab"]["segments"]
    ]
    assert finalize_sidecar(sidecar) == sidecar

    # A segment in the consolidation's own class is a plain same-class link.
    local = build_stochastic_consolidation_output_sidecar(
        consolidated,
        project_name="NJ_Annual_Prod_202605_Fake",
        reserving_class=consolidated["segments_tab"]["segments"][0]["reserving_class"].lower(),
        csv_file="x.csv",
        timestamp=STAMP,
    )
    assert "reserving_class" not in local["precedents"][0]
    assert len(local["precedents"]) == 5


def test_a_segment_from_another_project_is_named_and_linked_by_its_project(reference, bootstraps, consolidated):
    payload = _consolidation(reference)
    payload["segments_tab"]["segments"][2]["project_name"] = "NJ_Annual_Prod_2026 Q3-Aug Oil"
    method = consolidate_stochastic_method(payload, _inputs(bootstraps), timestamp=STAMP)
    segments = method["segments_tab"]["segments"]

    # Only the other project's segment carries a project, so a same-project
    # consolidation keeps the shape (and revisions) it always had.
    assert ["project_name" in segment for segment in segments] == [False, False, True, False, False]
    assert method["method_metadata"]["owned_revision"] != consolidated["method_metadata"]["owned_revision"]
    assert method["results_tab"]["output_origin_labels"] == method["results_tab"]["origin_labels"]
    assert method["results_tab"]["simulation_summary"] == consolidated["results_tab"]["simulation_summary"]

    sidecar = build_stochastic_consolidation_output_sidecar(
        method, project_name="NJ_Annual_Prod_2026 Q3-Aug", reserving_class=HOST, csv_file="x.csv", timestamp=STAMP
    )
    assert sidecar["precedents"][2] == {
        "dataset_name": segments[2]["method_name"],
        "method_type": "Bootstrap",
        "reserving_class": segments[2]["reserving_class"],
        "project": "NJ_Annual_Prod_2026 Q3-Aug Oil",
    }

    stale = stale_segments(method, [*bootstraps[:2], None, *bootstraps[3:]])
    assert [(s["project_name"], s["reason"]) for s in stale] == [("NJ_Annual_Prod_2026 Q3-Aug Oil", "missing")]

    # The same class and method in two projects are two segments.
    twice = deepcopy(payload)
    twice["segments_tab"]["segments"].append({**twice["segments_tab"]["segments"][2], "project_name": ""})
    twice["correlation_tab"]["target_correlations"] = []
    normalize_stochastic_consolidation_method(twice, timestamp=STAMP)


def test_the_output_vector_publishes_only_the_host_projects_origins(consolidated):
    method = deepcopy(consolidated)
    results = method["results_tab"]
    origins = results["origin_labels"]
    results["output_origin_labels"] = origins[-3:]
    method = normalize_stochastic_consolidation_method(method, timestamp=STAMP)
    ultimate = method["results_tab"]["consolidation_ultimate"]

    assert stochastic_consolidation_output_variants(method) == {12: ultimate[-3:]}
    sidecar = build_stochastic_consolidation_output_sidecar(
        method, project_name="P", reserving_class=HOST, csv_file="x.csv", timestamp=STAMP
    )
    assert sidecar["origin_labels"] == origins[-3:]
    # Labels that are not the run's latest origins fall back to every origin.
    method["results_tab"]["output_origin_labels"] = origins[:3]
    assert normalize_stochastic_consolidation_method(method)["results_tab"]["output_origin_labels"] == origins


def test_dependency_entries_keep_same_named_links_in_different_classes():
    entries = dependency_entries([
        {"dataset_name": "F 72 A", "reserving_class": "A"},
        {"dataset_name": "F 72 A", "reserving_class": "B"},
        {"dataset_name": "f 72 a", "reserving_class": "a"},
        "F 72 A",
    ])
    assert entries == [
        {"dataset_name": "F 72 A", "reserving_class": "A"},
        {"dataset_name": "F 72 A", "reserving_class": "B"},
        {"dataset_name": "F 72 A"},
    ]


def test_output_variants_hold_the_native_vector(consolidated):
    variants = stochastic_consolidation_output_variants(consolidated)
    assert list(variants) == [12]
    assert variants[12] == consolidated["results_tab"]["consolidation_ultimate"]


def test_an_unrun_consolidation_is_complete_and_publishes_an_empty_vector(reference):
    method = normalize_stochastic_consolidation_method(_consolidation(reference), timestamp=STAMP)
    assert method["results_tab"]["simulation_summary"]["scaled"] == {}
    assert method["results_tab"]["input_revision"] == ""
    assert stochastic_consolidation_output_variants(method) == {12: []}


def test_the_index_lists_a_consolidation_as_its_own_method_type(consolidated):
    name = consolidated["details_tab"]["name"]
    with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as folder:
        methods = Path(folder) / "methods"
        methods.mkdir()
        (methods / f"SCON@{name}.json").write_text(persisted_json_text(consolidated), encoding="utf-8")
        payload = build_dataset_index_payload("Project", HOST, folder)
    rows = [row for row in payload["files"] if row["name"] == name]
    assert len(rows) == 1
    assert rows[0]["method_type"] == "Stochastic Consolidation"
    assert rows[0]["source_kind"] == "stochastic_consolidation"
    assert rows[0]["dataset_type"] == "F 00 - Ultimate Net Loss"
