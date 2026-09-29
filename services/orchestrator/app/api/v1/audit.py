"""Audit records: read-only view of the authenticated principal's audit ledger."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.pagination import Limit, Offset, PageMeta
from app.audit import recorder
from app.core.auth import CurrentPrincipal
from app.db.session import get_session
from greenloop_contracts import AuditOutcome, AuditRecord
from greenloop_contracts.base import Identifier

router = APIRouter(prefix="/audit-records", tags=["audit"])


class AuditRecordPage(BaseModel):
    data: list[AuditRecord]
    meta: PageMeta


@router.get("")
def list_audit_records(
    principal: CurrentPrincipal,
    session: Annotated[Session, Depends(get_session)],
    limit: Limit = 50,
    offset: Offset = 0,
    outcome: AuditOutcome | None = None,
    correlation_id: Annotated[Identifier | None, Query()] = None,
) -> AuditRecordPage:
    records, total = recorder.list_for_principal(
        session,
        principal.principal_id,
        limit=limit,
        offset=offset,
        outcome=outcome,
        correlation_id=correlation_id,
    )
    return AuditRecordPage(data=records, meta=PageMeta(total=total, limit=limit, offset=offset))
