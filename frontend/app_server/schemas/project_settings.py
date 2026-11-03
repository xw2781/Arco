from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ProjectSettingsUpdateRequest(BaseModel):
    """Authoritative project registry write: virtual folders plus project paths.

    ``expected_revision`` is the registry revision the caller read. The
    optional ``request_id`` on this and the folder and General Settings writes
    names the user's action, so a repeat under it answers with the first
    outcome instead of applying the change twice.
    """

    folders: List[str] = Field(default_factory=list)
    project_paths: List[str] = Field(default_factory=list)
    expected_revision: int = 0
    request_id: Optional[str] = None


class RenameProjectFolderRequest(BaseModel):
    old_name: str
    new_name: str
    request_id: Optional[str] = None


class DuplicateProjectFolderRequest(BaseModel):
    old_name: str
    new_name: str
    request_id: Optional[str] = None


ProjectDuplicationStatusValue = Literal[
    "queued", "processing", "success", "error", "cancelled"
]


class DuplicateProjectFolderJobResponse(BaseModel):
    ok: Literal[True]
    job_id: str
    status: ProjectDuplicationStatusValue


class DuplicateProjectFolderCancelResponse(BaseModel):
    """Outcome of a cancel request: whether the Engine will be asked to stop."""

    ok: Literal[True]
    job_id: str
    status: ProjectDuplicationStatusValue
    cancel_requested: bool


class ProjectDuplicationProgress(BaseModel):
    stage: str
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    label: str


class ProjectDuplicationJobStatusResponse(BaseModel):
    ok: Literal[True]
    job_id: str
    contract_version: int
    status: ProjectDuplicationStatusValue
    updated_at: str
    request_id: str
    progress: ProjectDuplicationProgress
    message: Optional[str] = None


class ProjectDuplicationUnknownStatusResponse(BaseModel):
    """A status poll the Gateway could not answer: ask again, the copy runs on."""

    ok: Literal[True]
    job_id: str
    unknown: Literal[True]


class CreateProjectFolderRequest(BaseModel):
    name: str
    request_id: Optional[str] = None


class DeleteProjectFolderRequest(BaseModel):
    name: str
    request_id: Optional[str] = None


class OpenProjectFolderRequest(BaseModel):
    project_name: str


class GeneratedDatasetCacheClearRequest(BaseModel):
    project_name: str


class ProjectLockUpdateRequest(BaseModel):
    project_name: str
    locked: bool = False
    request_id: Optional[str] = None


class ProjectDatesChangeRequest(BaseModel):
    """Move the project to new dates: one Engine job saves and reshapes.

    The client owns ``request_id`` so a retry after a lost response resumes
    the same job instead of queuing a second change.
    """

    project_name: str
    origin_start_date: str
    origin_end_date: str
    development_end_date: str
    request_id: str = ""


class GeneralSettingsUpdateRequest(BaseModel):
    project_name: str
    origin_start_date: Optional[str] = ""
    origin_end_date: Optional[str] = ""
    development_end_date: Optional[str] = ""
    auto_generated: Optional[bool] = False
    request_id: Optional[str] = None
