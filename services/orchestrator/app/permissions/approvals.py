"""Approval requests: ask a human to allow one exact consequential operation.

The operation's SHA256 is greenloop_contracts.operation_hash; storage and single-use
consumption live in the broker (ADR 0009). This module will create the request and
record the human decision through the broker (PR5b-2).
"""

from greenloop_contracts import ToolPermission


async def request_approval(permission: ToolPermission) -> str:
    raise NotImplementedError("TODO(phase-3): persist request, notify UI, return approval id")


async def record_decision(approval_id: str, principal_id: str, approved: bool) -> None:
    raise NotImplementedError("TODO(phase-3): only the owning principal may decide")
