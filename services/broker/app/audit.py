"""Writes broker audit events (ADR 0009 rule 3): create, decide, consume and every
refused attempt. Each event is validated as an AuditRecord before it is stored, and
stamped with the database clock. audit_events is append-only in the database.

Call `record` in the same transaction as the change it describes, so a change and
its audit row commit together. A refusal changes nothing, so its row commits alone.
"""

import uuid

from pydantic import JsonValue
from sqlalchemy import Connection, insert

from app.db.tables import audit_events
from greenloop_contracts import AuditOutcome, AuditRecord


def record(
    connection: Connection,
    *,
    principal_id: str,
    actor: str,
    action: str,
    outcome: AuditOutcome,
    correlation_id: str,
    resource_type: str = "approval",
    resource_id: str | None = None,
    approval_id: str | None = None,
    operation_hash: str | None = None,
    details: dict[str, JsonValue] | None = None,
) -> str:
    event = AuditRecord(
        audit_id=f"aud-{uuid.uuid4().hex}",
        principal_id=principal_id,
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        correlation_id=correlation_id,
        operation_hash=operation_hash,
        approval_id=approval_id,
        details=details or {},
    )
    values = event.model_dump(mode="json", exclude={"occurred_at"})
    connection.execute(insert(audit_events).values(**values))
    return event.audit_id
