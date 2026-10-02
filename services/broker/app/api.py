"""Broker approvals API (ADR 0009). Every route needs a service token.

    POST /v1/approvals                         create (Idempotency-Key required)
    GET  /v1/approvals?principal_id=...        list the principal's approvals
    GET  /v1/approvals/{id}?principal_id=...   one approval, owner only
    POST /v1/approvals/{id}/decisions          decide (Idempotency-Key required)

Consume has no route: it stays inside the broker for the phase 3 tool path. Requests
are greenloop_contracts models, so a caller can never send an Approval, a status or a
summary (rule 7). Only a human user outside a dispatch may decide (rule 6); anyone
else gets 403, audited. Errors use {"error": {"code", "message"}} and never echo
request values.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import StringConstraints, TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app import audit
from app.approval_store import ApprovalRefusal, ApprovalRefusedError, ApprovalStore
from app.service_tokens import ServiceTokenInfo, authenticate
from greenloop_contracts import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalStatus,
    AuditOutcome,
)
from greenloop_contracts.base import Identifier

IdentifierText = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")]
_identifier = TypeAdapter(Identifier)
logger = logging.getLogger(__name__)

REFUSAL_RESPONSES: dict[ApprovalRefusal, tuple[int, str, str]] = {
    ApprovalRefusal.NOT_FOUND: (404, "APPROVAL_NOT_FOUND", "No such approval."),
    ApprovalRefusal.NOT_PENDING: (409, "APPROVAL_NOT_PENDING", "The approval was already decided."),
    ApprovalRefusal.EXPIRED: (409, "APPROVAL_EXPIRED", "The approval has expired."),
    ApprovalRefusal.IDEMPOTENCY_CONFLICT: (
        409,
        "IDEMPOTENCY_CONFLICT",
        "The idempotency key was already used for a different request.",
    ),
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


def error_response(error: ApiError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message}},
        status_code=error.status,
        headers=error.headers,
    )


def correlation_id(x_correlation_id: Annotated[str | None, Header()] = None) -> str:
    try:
        return _identifier.validate_python(x_correlation_id)
    except ValidationError:
        return f"corr-{uuid.uuid4().hex}"


def require_service(
    request: Request, correlation: Annotated[str, Depends(correlation_id)]
) -> ServiceTokenInfo:
    engine = request.app.state.engine
    if engine is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The broker database is not configured.")
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    info = authenticate(engine, presented) if scheme.lower() == "bearer" and presented else None
    if info is not None:
        return info
    try:
        with engine.begin() as connection:
            audit.record(
                connection,
                principal_id="unknown",
                actor="unknown",
                action="service_token.authenticate",
                outcome=AuditOutcome.DENIED,
                correlation_id=correlation,
                resource_type="service_token",
                details={"reason": "invalid" if presented else "missing"},
            )
    except SQLAlchemyError:
        logger.error("auth_refusal_audit_failed correlation_id=%s", correlation)
    raise ApiError(
        401, "UNAUTHENTICATED", "A valid service token is required.", {"WWW-Authenticate": "Bearer"}
    )


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    try:
        return _identifier.validate_python(idempotency_key)
    except ValidationError:
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Send an Idempotency-Key header of 1-128 letters, digits, . _ : -",
        ) from None


def store(request: Request) -> ApprovalStore:
    return request.app.state.approval_store


Service = Annotated[ServiceTokenInfo, Depends(require_service)]
Store = Annotated[ApprovalStore, Depends(store)]
Correlation = Annotated[str, Depends(correlation_id)]
IdempotencyKey = Annotated[str, Depends(idempotency_key)]
ApprovalId = Annotated[IdentifierText, Path()]
PrincipalId = Annotated[IdentifierText, Query()]

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])


def _refused(error: ApprovalRefusedError) -> ApiError:
    status, code, message = REFUSAL_RESPONSES[error.reason]
    return ApiError(status, code, message)


def _actor_name(service: ServiceTokenInfo) -> str:
    return f"service:{service.name}"


@router.post("", status_code=201)
def create_approval(
    body: ApprovalCreateRequest,
    service: Service,
    approvals: Store,
    correlation: Correlation,
    key: IdempotencyKey,
) -> dict:
    try:
        approval = approvals.create(
            body.operation,
            idempotency_key=key,
            actor=_actor_name(service),
            correlation_id=correlation,
        )
    except ApprovalRefusedError as error:
        raise _refused(error) from None
    return approval.model_dump(mode="json")


@router.get("")
def list_approvals(
    service: Service,
    approvals: Store,
    principal_id: PrincipalId,
    status: Annotated[ApprovalStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    items, total = approvals.list_for(principal_id, status=status, limit=limit)
    return {
        "data": [a.model_dump(mode="json") for a in items],
        "meta": {"total": total, "limit": limit},
    }


@router.get("/{approval_id}")
def get_approval(
    approval_id: ApprovalId, principal_id: PrincipalId, service: Service, approvals: Store
) -> dict:
    approval = approvals.get(approval_id, principal_id=principal_id)
    if approval is None:
        raise _refused(ApprovalRefusedError(ApprovalRefusal.NOT_FOUND))
    return approval.model_dump(mode="json")


@router.post("/{approval_id}/decisions", status_code=201)
def decide_approval(
    approval_id: ApprovalId,
    body: ApprovalDecisionRequest,
    service: Service,
    approvals: Store,
    correlation: Correlation,
    key: IdempotencyKey,
    request: Request,
) -> dict:
    if not body.actor.may_decide:
        with request.app.state.engine.begin() as connection:
            audit.record(
                connection,
                principal_id=body.actor.principal_id,
                actor=_actor_name(service),
                action="approval.decide",
                outcome=AuditOutcome.DENIED,
                correlation_id=correlation,
                resource_id=approval_id,
                details={
                    "reason": "decider_not_human",
                    "kind": body.actor.kind.value,
                    "in_dispatch": body.actor.in_dispatch,
                },
            )
        raise ApiError(
            403, "DECIDER_NOT_HUMAN", "Only a human user, acting directly, can decide an approval."
        )
    try:
        approval = approvals.decide(
            approval_id,
            decided_by=body.actor.principal_id,
            approved=body.approved,
            idempotency_key=key,
            actor=_actor_name(service),
            correlation_id=correlation,
        )
    except ApprovalRefusedError as error:
        raise _refused(error) from None
    return approval.model_dump(mode="json")
