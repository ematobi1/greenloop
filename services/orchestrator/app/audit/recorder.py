"""Audit recorder: append an AuditRecord for every consequential decision and action.

`record` only adds the row to the caller's session, so the audit entry commits or
rolls back together with the action it describes. Records are never updated or
deleted; the database enforces that with a trigger.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AuditRecordRow
from greenloop_contracts import AuditOutcome, AuditRecord


def record(session: Session, entry: AuditRecord) -> None:
    session.add(AuditRecordRow.from_contract(entry))


def list_for_principal(
    session: Session,
    principal_id: str,
    *,
    limit: int,
    offset: int,
    outcome: AuditOutcome | None = None,
    correlation_id: str | None = None,
) -> tuple[list[AuditRecord], int]:
    """Newest first. Returns one page and the total count matching the filters."""
    conditions = [AuditRecordRow.principal_id == principal_id]
    if outcome is not None:
        conditions.append(AuditRecordRow.outcome == outcome.value)
    if correlation_id is not None:
        conditions.append(AuditRecordRow.correlation_id == correlation_id)
    total = session.scalar(select(func.count()).select_from(AuditRecordRow).where(*conditions))
    rows = session.scalars(
        select(AuditRecordRow)
        .where(*conditions)
        .order_by(AuditRecordRow.occurred_at.desc(), AuditRecordRow.audit_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [row.to_contract() for row in rows], total or 0
