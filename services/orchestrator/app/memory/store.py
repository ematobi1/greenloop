"""Append-only memory store in Postgres.

Records are never updated in place. Supersede, correct and delete append a new
MemoryRecord that points at the one it replaces (see provenance.py). Every query
filters by principal server-side.
"""

from greenloop_contracts import MemoryRecord


class MemoryStore:
    async def append(self, record: MemoryRecord) -> MemoryRecord:
        raise NotImplementedError("TODO(phase-2): insert the record in one transaction")

    async def get_current(self, principal_id: str, record_id: str) -> MemoryRecord | None:
        raise NotImplementedError("TODO(phase-2): latest non-superseded version for principal")

    async def history(self, principal_id: str, record_id: str) -> list[MemoryRecord]:
        raise NotImplementedError("TODO(phase-2): full supersede chain, oldest first")
