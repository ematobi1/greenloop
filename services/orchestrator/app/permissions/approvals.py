"""Approvals: ask a human to allow one exact consequential operation (ADR 0009).

The broker stores and consumes approvals; this module is the orchestrator's side. It
builds the actor only from the authenticated Principal and the dispatch context,
never from request data. It refuses a decision by a system principal or from inside
a dispatch before calling the broker (the broker refuses it again), and it audits
create, decide and every refusal in the orchestrator's own audit log.

Audit writes are best effort once the broker has acted: a failure is logged, never
allowed to hide the broker's result.
"""

import asyncio
import uuid
from collections.abc import Callable

import structlog
from pydantic import JsonValue
from sqlalchemy.orm import Session

from app.audit import recorder
from app.core.auth import Principal
from app.orchestration.dispatch_context import in_dispatch
from app.tools.broker_client import BrokerClient, BrokerError
from greenloop_contracts import (
    ActorKind,
    Approval,
    ApprovalActor,
    AuditOutcome,
    AuditRecord,
    ToolPermission,
)

logger = structlog.get_logger(__name__)

SessionFactory = Callable[[], Session]


class DeciderNotHumanError(Exception):
    pass


def actor_for(principal: Principal) -> ApprovalActor:
    return ApprovalActor(
        principal_id=principal.principal_id,
        kind=ActorKind.SYSTEM if principal.is_system else ActorKind.USER,
        in_dispatch=in_dispatch(),
    )


async def request_approval(
    client: BrokerClient,
    session_factory: SessionFactory,
    principal: Principal,
    permission: ToolPermission,
    *,
    correlation_id: str,
) -> Approval:
    """Asks the broker for a pending approval of `permission`. Used by the tool path
    (phase 3); there is no public create route (decision E)."""
    if permission.principal_id != principal.principal_id:
        raise ValueError("an approval can only be requested for the principal's own operation")
    try:
        approval = await client.create_approval(
            permission,
            actor_for(principal),
            idempotency_key=f"create-{uuid.uuid4().hex}",
            correlation_id=correlation_id,
        )
    except BrokerError as error:
        await _audit(
            session_factory,
            principal,
            "approval.create",
            AuditOutcome.DENIED,
            correlation_id,
            details={"reason": error.code},
        )
        raise
    await _audit(
        session_factory,
        principal,
        "approval.create",
        AuditOutcome.APPROVAL_REQUIRED,
        correlation_id,
        approval=approval,
    )
    return approval


async def decide(
    client: BrokerClient,
    session_factory: SessionFactory,
    principal: Principal,
    approval_id: str,
    *,
    approved: bool,
    idempotency_key: str,
    correlation_id: str,
) -> Approval:
    actor = actor_for(principal)
    if not actor.may_decide:
        await _audit(
            session_factory,
            principal,
            "approval.decide",
            AuditOutcome.DENIED,
            correlation_id,
            resource_id=approval_id,
            details={
                "reason": "decider_not_human",
                "kind": actor.kind.value,
                "in_dispatch": actor.in_dispatch,
            },
        )
        raise DeciderNotHumanError
    try:
        approval = await client.decide_approval(
            approval_id,
            actor,
            approved=approved,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
    except BrokerError as error:
        await _audit(
            session_factory,
            principal,
            "approval.decide",
            AuditOutcome.DENIED,
            correlation_id,
            resource_id=approval_id,
            details={"reason": error.code},
        )
        raise
    await _audit(
        session_factory,
        principal,
        "approval.decide",
        AuditOutcome.APPROVED if approved else AuditOutcome.REJECTED,
        correlation_id,
        approval=approval,
    )
    return approval


async def _audit(
    session_factory: SessionFactory,
    principal: Principal,
    action: str,
    outcome: AuditOutcome,
    correlation_id: str,
    *,
    approval: Approval | None = None,
    resource_id: str | None = None,
    details: dict[str, JsonValue] | None = None,
) -> None:
    entry = AuditRecord(
        audit_id=f"aud-{uuid.uuid4().hex}",
        principal_id=principal.principal_id,
        actor=principal.principal_id,
        action=action,
        resource_type="approval",
        resource_id=approval.approval_id if approval else resource_id,
        outcome=outcome,
        correlation_id=correlation_id,
        operation_hash=approval.operation_hash if approval else None,
        approval_id=approval.approval_id if approval else None,
        details=details or {},
    )
    await asyncio.to_thread(_write, session_factory, entry)


def _write(session_factory: SessionFactory, entry: AuditRecord) -> None:
    try:
        with session_factory() as session:
            recorder.record(session, entry)
            session.commit()
    except Exception:
        logger.error("approval_audit_failed", action=entry.action, outcome=entry.outcome.value)
