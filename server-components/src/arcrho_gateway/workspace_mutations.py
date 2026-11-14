"""Server-hosted execution of allowlisted ``app_server`` workspace mutations.

The Gateway freezes the same canonical ``python-api/src`` and
``frontend/app_server`` trees the Engine does, so a registered mutation runs the
exact service function a Client PC would have run over the mapped drive — here
against local disk, where a delete plus an index rebuild costs a handful of
milliseconds rather than one network round trip per file. The gateway performs
no mutation-specific work of its own: the request names a kind, the contract
maps the kind to the service, and the service's response goes back verbatim.

A kind the contract marks ``receipt`` is not idempotent, so its outcome is kept
in the Gateway's receipt store under the signed user and request id: a repeat
of the same request answers from the receipt, and a different request under
that id is refused with 409 (see ``arcrho_gateway.receipts``).
"""

from __future__ import annotations

import importlib
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping

from arcrho_engine.project_duplication import _redact_machine_paths
from arcrho_hosted_save_http_contract import (
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_USER_HEADER,
    canonical_request_bytes,
    mutation_receipt_path,
    normalize_user,
    request_sha256,
    verify_request_signature,
)
from arcrho_workspace_mutation_contract import (
    HTTP_WORKSPACE_MUTATION_KINDS,
    WORKSPACE_MUTATION_CAPABILITY_FIELD,
    WORKSPACE_MUTATION_KINDS,
    WORKSPACE_MUTATION_PATH,
    WorkspaceMutationContractError,
    validate_workspace_mutation_request,
)
from arcrho_gateway.receipts import (
    TERMINAL_STATES,
    ReceiptReadError,
    now_iso,
    read_json,
    receipt_lock,
    write_json_atomic,
)
from arcrho_gateway.workspace_reads import (
    WorkspaceReadHttpError,
    WorkspaceReadRefusal,
)


class WorkspaceMutationExecutor:
    """Runs registered mutations in-process against the gateway's server root."""

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
        return {WORKSPACE_MUTATION_CAPABILITY_FIELD: list(HTTP_WORKSPACE_MUTATION_KINDS)}

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
            path=WORKSPACE_MUTATION_PATH,
            body=body,
        ):
            raise WorkspaceReadHttpError(401, "Gateway authentication failed.")
        return user

    def execute(self, authenticated_user: str, raw_payload: Any) -> dict[str, Any]:
        try:
            request = validate_workspace_mutation_request(raw_payload)
        except WorkspaceMutationContractError as exc:
            raise WorkspaceReadHttpError(400, str(exc)) from exc
        if normalize_user(request["UserName"]) != normalize_user(authenticated_user):
            raise WorkspaceReadHttpError(
                403, "Authenticated user does not match the mutation user."
            )

        try:
            self._ensure_runtime()
        except Exception as exc:
            self._log(self.root, f"workspace mutation runtime unavailable: {exc!r}")
            raise WorkspaceReadHttpError(
                503, "The Arco Server cannot run workspace mutations right now."
            ) from exc

        spec = WORKSPACE_MUTATION_KINDS[request["MutationKind"]]
        if len(canonical_request_bytes(request)) > spec.max_request_bytes:
            raise WorkspaceReadHttpError(413, "Workspace-mutation request is too large.")
        if not spec.receipt:
            return self._run(authenticated_user, request)

        path = mutation_receipt_path(self.root, authenticated_user, request["RequestId"])
        with receipt_lock(str(path)):
            try:
                receipt = read_json(path)
            except ReceiptReadError as exc:
                raise WorkspaceReadHttpError(500, str(exc)) from exc
            digest = request_sha256(request)
            if receipt is not None:
                if receipt.get("request_sha256") != digest:
                    raise WorkspaceReadRefusal(
                        409, "This request id was already used for a different change."
                    )
                self._log(
                    self.root,
                    f"mutation={request['RequestId']} user={authenticated_user} "
                    f"kind={request['MutationKind']} replay={receipt.get('state')}",
                )
                return _receipt_outcome(receipt)
            receipt = {
                "receipt_version": 1,
                "user": normalize_user(authenticated_user),
                "request_id": request["RequestId"],
                "mutation_kind": request["MutationKind"],
                "request_sha256": digest,
                "state": "accepted",
                "accepted_at": now_iso(),
                "updated_at": now_iso(),
            }
            write_json_atomic(path, receipt)
            try:
                response = self._run(authenticated_user, request)
            except WorkspaceReadRefusal as exc:
                receipt.update(state="error", status_code=exc.status_code, detail=exc.detail)
                receipt["updated_at"] = now_iso()
                write_json_atomic(path, receipt)
                raise
            except Exception:
                receipt.update(
                    state="error", status_code=500, detail="The Gateway failed unexpectedly."
                )
                receipt["updated_at"] = now_iso()
                write_json_atomic(path, receipt)
                raise
            receipt.update(state="success", status_code=200, response=response)
            receipt["updated_at"] = now_iso()
            write_json_atomic(path, receipt)
            return response

    def _run(self, authenticated_user: str, request: Mapping[str, Any]) -> dict[str, Any]:
        from fastapi import HTTPException
        from fastapi.encoders import jsonable_encoder

        from app_server.services import project_lock_service, user_identity_service

        spec = WORKSPACE_MUTATION_KINDS[request["MutationKind"]]
        module = importlib.import_module(f"app_server.services.{spec.module}")
        mutate = getattr(module, spec.function)
        try:
            project_lock_service.require_mutation_allowed(
                request["MutationKind"], request["Kwargs"]
            )
            # Whatever the mutation stamps on disk names the user who asked,
            # not the gateway's service profile.
            with user_identity_service.acting_identity(
                request["UserName"], request["UserDisplayName"]
            ):
                response = mutate(**request["Kwargs"])
        except HTTPException as exc:
            self._log(
                self.root,
                f"mutation={request['RequestId']} user={authenticated_user} "
                f"kind={request['MutationKind']} refusal={exc.status_code}",
            )
            raise WorkspaceReadRefusal(
                int(exc.status_code), _redacted_detail(exc.detail)
            ) from exc
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
            f"mutation={request['RequestId']} user={authenticated_user} "
            f"kind={request['MutationKind']} ok={response.get('ok')}",
        )
        return response


def _receipt_outcome(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Answer a repeated request the way its first run was answered."""

    if receipt.get("state") not in TERMINAL_STATES:
        # The run that wrote this receipt held its lock until it finished, so
        # an unfinished receipt means the Gateway stopped part way.
        raise WorkspaceReadRefusal(
            409,
            "The Arco Server stopped before finishing this change. "
            "Refresh to see whether it was applied.",
        )
    if receipt.get("state") == "error":
        raise WorkspaceReadRefusal(int(receipt.get("status_code") or 500), receipt.get("detail"))
    return dict(receipt.get("response") or {})


def _redact_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    try:
        return _redact_machine_paths(text)
    except Exception:
        return text


def _redacted_detail(detail: Any) -> Any:
    """Redact server paths without flattening a structured refusal.

    A refusal the client acts on rather than merely displays — the delete that
    lists the dependents blocking it — carries a mapping, and the local route
    would have delivered that mapping under ``detail`` unchanged. Only its free
    text can contain a server path, so only its free text is rewritten.
    """

    if isinstance(detail, Mapping):
        return {
            key: _redact_text(value) if isinstance(value, str) else value
            for key, value in detail.items()
        }
    return _redact_text(detail)
