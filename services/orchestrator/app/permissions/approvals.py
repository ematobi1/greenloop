"""Approval requests: ask a human to allow one exact consequential operation.

The canonical SHA256 binding and single-use consumption live in the broker
(services/broker/app/approval_binding.py). This module creates the request and
records the human decision.
"""

from greenloop_contracts import ToolPermission


async def request_approval(permission: ToolPermission) -> str:
    raise NotImplementedError("TODO(phase-3): persist request, notify UI, return approval id")


async def record_decision(approval_id: str, principal_id: str, approved: bool) -> None:
    raise NotImplementedError("TODO(phase-3): only the owning principal may decide")
