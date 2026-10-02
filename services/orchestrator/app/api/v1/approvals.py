"""Approvals: consequential operations awaiting the principal's decision (ADR 0009).

A thin adapter over app/permissions/approvals.py and the broker, which stores the
approvals. The principal always comes from the auth token; the caller can never name
another principal or send an actor. There is no create route (decision E): approvals
are requested by the tool path.

    GET  /v1/approvals                       the principal's approvals, newest first
    GET  /v1/approvals/{approval_id}         one approval
    POST /v1/approvals/{approval_id}/decisions   {"approved": true|false}

A decision needs a human user acting directly: system principals get 403. An
optional Idempotency-Key header makes a retried decision safe; without one, each
request is a new attempt. Broker failures become 502 with no broker detail.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, StrictBool, TypeAdapter, ValidationError

from app.api.v1.pagination import Limit
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.permissions import approvals as service
from app.tools.broker_client import BrokerClient, BrokerError
from greenloop_contracts import Approval, ApprovalStatus
from greenloop_contracts.base import Identifier

router = APIRouter(prefix="/approvals", tags=["approvals"])

_identifier = TypeAdapter(Identifier)

PASSED_THROUGH = {
    "APPROVAL_NOT_FOUND": (404, "No such approval."),
    "APPROVAL_NOT_PENDING": (409, "The approval was already decided."),
    "APPROVAL_EXPIRED": (409, "The approval has expired."),
    "IDEMPOTENCY_CONFLICT": (
        409,
        "The idempotency key was already used for a different request.",
    ),
}


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: StrictBool


class ApprovalList(BaseModel):
    data: list[Approval]
    meta: dict[str, int]


def _broker(request: Request) -> BrokerClient:
    client: BrokerClient | None = request.app.state.broker_client
    if client is None:
        raise ApiError(503, "BROKER_UNAVAILABLE", "Approvals are not configured.")
    return client


def _session_factory(request: Request) -> service.SessionFactory:
    factory = request.app.state.session_factory
    if factory is None:
        raise ApiError(503, "DATABASE_UNAVAILABLE", "The database is not configured.")
    return factory


def _broker_failed(error: BrokerError) -> ApiError:
    if error.code in PASSED_THROUGH:
        status, message = PASSED_THROUGH[error.code]
        return ApiError(status, error.code, message)
    return ApiError(502, "BROKER_FAILED", "The approval service could not complete the request.")


def _idempotency_key(value: str | None) -> str:
    if value is None:
        return f"decide-{uuid.uuid4().hex}"
    try:
        return _identifier.validate_python(value)
    except ValidationError:
        raise ApiError(
            400, "INVALID_IDEMPOTENCY_KEY", "Idempotency-Key must be 1-128 letters, digits, . _ : -"
        ) from None


@router.get("")
async def list_approvals(
    request: Request,
    principal: CurrentPrincipal,
    status: Annotated[ApprovalStatus | None, Query()] = None,
    limit: Limit = 50,
) -> ApprovalList:
    try:
        items = await _broker(request).list_approvals(
            principal_id=principal.principal_id,
            status=status,
            limit=limit,
            correlation_id=request.state.correlation_id,
        )
    except BrokerError as error:
        raise _broker_failed(error) from None
    return ApprovalList(data=items, meta={"total": len(items), "limit": limit})


@router.get("/{approval_id}")
async def get_approval(
    approval_id: Identifier, request: Request, principal: CurrentPrincipal
) -> Approval:
    try:
        return await _broker(request).get_approval(
            approval_id,
            principal_id=principal.principal_id,
            correlation_id=request.state.correlation_id,
        )
    except BrokerError as error:
        raise _broker_failed(error) from None


@router.post("/{approval_id}/decisions", status_code=201)
async def decide_approval(
    approval_id: Identifier,
    body: ApprovalDecision,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> Approval:
    client = _broker(request)
    session_factory = _session_factory(request)
    try:
        return await service.decide(
            client,
            session_factory,
            principal,
            approval_id,
            approved=body.approved,
            idempotency_key=_idempotency_key(idempotency_key),
            correlation_id=request.state.correlation_id,
        )
    except service.DeciderNotHumanError:
        raise ApiError(
            403,
            "DECIDER_NOT_HUMAN",
            "Only a human user, acting directly, can decide an approval.",
        ) from None
    except BrokerError as error:
        raise _broker_failed(error) from None
