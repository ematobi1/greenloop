"""Audit records: read-only view of consequential decisions and actions.

TODO(phase-3): serve AuditRecords for the principal, filtered and paginated by query params.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/audit-records", tags=["audit"])


@router.get("")
async def list_audit_records() -> None:
    raise not_implemented("Audit listing", phase=3)
