"""Memory retrieval: rank current records for a query, scoped to one principal.

Results are untrusted and go straight to context_builder.build_memory_context.
"""

from greenloop_contracts import MemoryRecord


async def retrieve(principal_id: str, query: str, limit: int = 20) -> list[MemoryRecord]:
    raise NotImplementedError("TODO(phase-2): pgvector similarity plus recency, principal-scoped")
