from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app_server.schemas.stochastic_consolidation import (
    StochasticConsolidationClassRequest,
    StochasticConsolidationIdentityRequest,
    StochasticConsolidationRunRequest,
    StochasticConsolidationSaveRequest,
)
from app_server.services import (
    engine_hosted_save_service,
    stochastic_consolidation_service,
    workspace_read_client,
)


router = APIRouter()


def _run_inputs(method: Dict[str, Any]) -> Dict[str, Any]:
    # A run rebuilds every result from the settings and the segments, so the
    # stored results the page holds never travel with the request.
    return {key: value for key, value in method.items() if key != "results_tab"}


@router.post("/stochastic-consolidation/load")
def load_stochastic_consolidation(req: StochasticConsolidationIdentityRequest) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "stochastic_consolidation_load",
        {
            "project_name": req.project_name,
            "reserving_class": req.reserving_class,
            "method_name": req.method_name,
        },
        local=lambda: stochastic_consolidation_service.load_stochastic_consolidation_method(
            req.project_name,
            req.reserving_class,
            req.method_name,
        ),
    )


@router.post("/stochastic-consolidation/consolidate")
def consolidate_stochastic_consolidation(req: StochasticConsolidationRunRequest) -> Dict[str, Any]:
    # Runs where the segment bootstraps live and writes nothing; Save
    # publishes the same run.
    method = _run_inputs(req.method)
    return workspace_read_client.run_workspace_read(
        "stochastic_consolidation_consolidate",
        {
            "project_name": req.project_name,
            "reserving_class": req.reserving_class,
            "method": method,
        },
        local=lambda: stochastic_consolidation_service.consolidate_stochastic_consolidation_method(
            req.project_name,
            req.reserving_class,
            method,
        ),
    )


@router.post("/stochastic-consolidation/segments/candidates")
def list_stochastic_consolidation_candidates(req: StochasticConsolidationClassRequest) -> Dict[str, Any]:
    return workspace_read_client.run_workspace_read(
        "stochastic_consolidation_candidates",
        {
            "project_name": req.project_name,
            "reserving_class": req.reserving_class,
            **({"source_project_name": req.source_project_name} if req.source_project_name else {}),
        },
        local=lambda: stochastic_consolidation_service.list_stochastic_consolidation_candidates(
            req.project_name,
            req.reserving_class,
            req.source_project_name,
        ),
    )


def _save_call(req: StochasticConsolidationSaveRequest) -> Dict[str, Any]:
    """The one argument projection the plan and the save both run against."""

    return {
        "args": [req.project_name, req.reserving_class, req.method],
        "kwargs": {
            "notes": req.notes,
            "expected_owned_revision": req.expected_owned_revision,
            "expected_derived_revision": req.expected_derived_revision,
        },
    }


@router.post("/stochastic-consolidation/save/plan")
def plan_stochastic_consolidation_save(req: StochasticConsolidationSaveRequest) -> Dict[str, Any]:
    # Step one of the two-step save: name the dependent objects this save
    # would refresh. Nothing is written and no lease is taken.
    return engine_hosted_save_service.run_hosted_save_plan(
        "stochastic_consolidation_method",
        req.project_name,
        req.reserving_class,
        **_save_call(req),
    )


@router.post("/stochastic-consolidation/save")
def save_stochastic_consolidation(req: StochasticConsolidationSaveRequest) -> Dict[str, Any]:
    # The save runs on Arco Engine next to the data, segments included.
    return engine_hosted_save_service.run_hosted_save(
        "stochastic_consolidation_method",
        req.project_name,
        req.reserving_class,
        plan_fingerprint=req.plan_fingerprint,
        **_save_call(req),
    )
