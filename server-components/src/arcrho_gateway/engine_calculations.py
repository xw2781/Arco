"""Server-hosted execution of Arco Engine calculation requests.

A Client PC that needs an ``ArcRhoTri`` / ``ArcRhoVec`` / ``ArcRhoHeaders``
result posts the logical request here instead of writing the request file over
the mapped drive and polling the share for the Engine's CSV. The Gateway runs
the very same ``app_server`` publish-and-wait exchange the client would have
run — against the server-local ``requests`` root the Engine already watches —
and returns the completion. The gateway performs no calculation-specific work
of its own: the contract validates the request, the canonical service derives
the output path and publishes, and the Engine remains the only executor.
"""

from __future__ import annotations

import importlib
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_engine_calculation_contract import (
    ENGINE_CALCULATION_CAPABILITY_FIELD,
    ENGINE_CALCULATION_OPERATION_FIELD,
    ENGINE_CALCULATION_PATH,
    HTTP_ENGINE_CALCULATION_FUNCTIONS,
    HTTP_ENGINE_CALCULATION_OPERATIONS,
    EngineCalculationContractError,
    validate_engine_calculation_request,
)
from arcrho_hosted_save_http_contract import (
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    normalize_user,
    verify_request_signature,
)
from arcrho_gateway.workspace_reads import (
    WorkspaceReadHttpError,
    WorkspaceReadRefusal,
)


# The canonical service that runs the exchange on this host, and the route
# module the dataset operations delegate to; both are bundled by name.
EXECUTOR_MODULE = "engine_calculation_service"
EXECUTOR_FUNCTION = "execute_hosted_engine_calculation"
EXECUTOR_MODULES: tuple[str, ...] = (EXECUTOR_MODULE, "arcrho_runtime_service")


class EngineCalculationExecutor:
    """Runs hosted calculation exchanges in-process against the gateway's server root."""

    def __init__(
        self,
        root: Path,
        *,
        load_gateway_config: Callable[[Path], Mapping[str, Any]],
        log: Callable[[Path, str], None],
        ensure_runtime: Callable[[], None],
    ) -> None:
        self.root = root.resolve()
        self._load_gateway_config = load_gateway_config
        self._log = log
        # The workspace-read executor owns the one-time app_server import.
        self._ensure_runtime = ensure_runtime

    def capability_fields(self) -> dict[str, Any]:
        return {
            ENGINE_CALCULATION_CAPABILITY_FIELD: list(HTTP_ENGINE_CALCULATION_FUNCTIONS),
            ENGINE_CALCULATION_OPERATION_FIELD: list(HTTP_ENGINE_CALCULATION_OPERATIONS),
        }

    def authenticate(self, headers: Mapping[str, str], body: bytes) -> str:
        config = self._load_gateway_config(self.root)
        user = normalize_user(headers.get(AUTH_USER_HEADER))
        secret = config["users"].get(user)
        if not secret or not verify_request_signature(
            secret,
            headers.get(AUTH_SIGNATURE_HEADER, ""),
            user=user,
            timestamp=headers.get(AUTH_TIMESTAMP_HEADER, ""),
            method="POST",
            path=ENGINE_CALCULATION_PATH,
            body=body,
        ):
            raise WorkspaceReadHttpError(401, "Gateway authentication failed.")
        return user

    def execute(self, authenticated_user: str, raw_payload: Any) -> dict[str, Any]:
        try:
            request = validate_engine_calculation_request(raw_payload)
        except EngineCalculationContractError as exc:
            raise WorkspaceReadHttpError(400, str(exc)) from exc
        if normalize_user(request["UserName"]) != normalize_user(authenticated_user):
            raise WorkspaceReadHttpError(
                403, "Authenticated user does not match the calculation user."
            )

        try:
            self._ensure_runtime()
        except Exception as exc:
            self._log(self.root, f"engine calculation runtime unavailable: {exc!r}")
            raise WorkspaceReadHttpError(
                503, "The Arco Server cannot run engine calculations right now."
            ) from exc

        from fastapi import HTTPException
        from fastapi.encoders import jsonable_encoder

        from app_server.services import user_identity_service

        module = importlib.import_module(f"app_server.services.{EXECUTOR_MODULE}")
        execute = getattr(module, EXECUTOR_FUNCTION)
        try:
            # The request file and any sidecar the run later stamps carry the
            # user who asked, not the gateway's service profile.
            with user_identity_service.acting_identity(
                request["UserName"], request["UserDisplayName"]
            ):
                response = execute(
                    request["Pairs"],
                    request["TimeoutSeconds"],
                    request["OutputVariant"],
                    request["Operation"],
                    request["Options"],
                )
        except HTTPException as exc:
            detail = str(exc.detail or "").strip()
            if detail:
                try:
                    detail = _redact_machine_paths(detail)
                except Exception:
                    pass
            self._log(
                self.root,
                f"calculation={request['RequestId']} user={authenticated_user} "
                f"function={request['EngineFunction']} operation={request['Operation']} "
                f"refusal={exc.status_code}",
            )
            raise WorkspaceReadRefusal(int(exc.status_code), detail) from exc
        except Exception:
            self._log(self.root, traceback.format_exc())
            raise
        if not isinstance(response, dict):
            response = {"ok": True, "response": response}
        # The local route hands the same object to FastAPI's encoder; matching
        # it here keeps the wire payload identical for both transports.
        response = jsonable_encoder(response)
        self._log(
            self.root,
            f"calculation={request['RequestId']} user={authenticated_user} "
            f"function={request['EngineFunction']} operation={request['Operation']} "
            f"ok={response.get('ok')} status={response.get('status')} "
            f"wait_ms={response.get('wait_ms')}",
        )
        return response
