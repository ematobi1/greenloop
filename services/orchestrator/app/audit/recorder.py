"""Audit recorder: append an AuditRecord for every consequential decision and action."""

from greenloop_contracts import AuditRecord


async def record(entry: AuditRecord) -> None:
    raise NotImplementedError("TODO(phase-3): append-only insert; never update or delete")
