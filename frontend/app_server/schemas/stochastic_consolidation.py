from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class StochasticConsolidationIdentityRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    reserving_class: str = Field(..., min_length=1)
    method_name: str = Field(..., min_length=1)


class StochasticConsolidationClassRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    reserving_class: str = Field(..., min_length=1)
    # The project to list bootstraps from, when a segment is taken from
    # another project; blank lists the consolidation's own project.
    source_project_name: str = ""


class StochasticConsolidationRunRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    reserving_class: str = Field(..., min_length=1)
    method: Dict[str, Any]


class StochasticConsolidationSaveRequest(BaseModel):
    project_name: str = Field(..., min_length=1)
    reserving_class: str = Field(..., min_length=1)
    method: Dict[str, Any]
    notes: str | None = None
    expected_owned_revision: str | None = None
    expected_derived_revision: str | None = None
    # Fingerprint of the dependent-update plan the user confirmed. The Engine
    # rechecks it under the reserving-class lease and refuses with 409 if the
    # class changed while the plan was on screen.
    plan_fingerprint: str = ""
