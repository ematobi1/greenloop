"""Audit records: read-only view of the authenticated principal's audit ledger."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit import recorder
from app.core.auth import CurrentPrincipal
from app.db.session import get_session
from greenloop_contracts import AuditOutcome, AuditRecord
from greenloop_contracts.base import Identifier

router = APIRouter(prefix="/audit-records", tags=["audit"])

MAX_PAGE_SIZE = 100


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class AuditRecordPage(BaseModel):
    data: list[AuditRecord]
    meta: PageMeta


@router.get("")
def list_audit_records(
    principal: CurrentPrincipal,
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
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
