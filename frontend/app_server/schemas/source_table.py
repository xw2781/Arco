from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from arcrho_api.source_table_contract import MSSQL_AUTH_WINDOWS


class MssqlProfilePayload(BaseModel):
    server: Optional[str] = ""
    database: Optional[str] = ""
    table: Optional[str] = ""
    # Only Windows authentication is supported today; the SQL login mode is
    # accepted by the shape and rejected by the service.
    authentication: Optional[str] = MSSQL_AUTH_WINDOWS


class SourceProfileSaveRequest(BaseModel):
    project_name: str
    source_type: str
    mssql: Optional[MssqlProfilePayload] = None
    # CSV source selection; omitted (None) leaves the stored path unchanged.
    csv_path: Optional[str] = None


class MssqlConnectionTestRequest(BaseModel):
    server: str
    database: str
    table: str
    authentication: Optional[str] = MSSQL_AUTH_WINDOWS


class MssqlTableListRequest(BaseModel):
    # Table listing only needs the server/database half of the profile.
    server: str
    database: str
    authentication: Optional[str] = MSSQL_AUTH_WINDOWS


class MssqlConnectionForgetRequest(BaseModel):
    # Omitting `database` drops every saved pair for the server.
    server: str
    database: Optional[str] = None


class SourceTableImportRequest(BaseModel):
    project_name: str


class SourceTableRefreshRequest(BaseModel):
    project_name: str
    force: bool = False


class SourceRefreshReservingClassType(BaseModel):
    Name: str
    Level: int


class SourceRefreshJobSubmitRequest(BaseModel):
    project_name: str
    # The client owns the request id so a retry after a lost response resumes
    # the same job instead of starting a second refresh.
    request_id: str
    # False when the client already replaced the master copy itself, which is
    # what a SQL Server profile or a CSV only this machine can reach requires.
    import_source: bool = True
    force: bool = True
    refresh_dependents: bool = True
    # The refresh scope. Empty means every engine-built dataset type and every
    # reserving class; the source-refresh contract owns the matching rule.
    dataset_types: List[str] = []
    reserving_class_types: List[SourceRefreshReservingClassType] = []


class SourceScopeSaveRequest(BaseModel):
    project_name: str
    # Same scope fields as the refresh job; empty means everything.
    dataset_types: List[str] = []
    reserving_class_types: List[SourceRefreshReservingClassType] = []


class CombinedTableDescribeRequest(BaseModel):
    # One table of a combined source, in the shape of decision 3 of
    # docs/plans/completed/combined_source_import.md (id optional here).
    table: Dict[str, Any]
    # Re-read a SQL Server table instead of answering from this session's copy.
    refresh: bool = False


class CombinedSourcePreviewRequest(BaseModel):
    project_name: str
    combined: Dict[str, Any]
    refresh: bool = False


class CombinedSourceSaveRequest(BaseModel):
    project_name: str
    combined: Dict[str, Any]


class CombinedSourceImportRequest(BaseModel):
    project_name: str
