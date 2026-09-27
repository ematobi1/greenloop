"""Approvals: pending consequential operations awaiting a human decision.

TODO(phase-3): list pending approvals for the principal and record decisions. The
decision binds to the operation's SHA256 and is consumed once by the broker.
"""

from fastapi import APIRouter

from app.core.errors import not_implemented

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("")
async def list_approvals() -> None:
    raise not_implemented("Approval listing", phase=3)


@router.post("/{approval_id}/decisions", status_code=201)
async def decide_approval(approval_id: str) -> None:
    raise not_implemented("Approval decisions", phase=3)
