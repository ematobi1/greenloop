"""Memory retrieval for a chat turn, scoped to one principal.

Today this returns the principal's most recent live records (recency only); the
query is not used yet. Semantic ranking with pgvector replaces it once an
embedding provider is chosen (see embeddings.py). Results are untrusted and go
straight to context_builder.build_memory_context.
"""

from sqlalchemy.orm import Session

from app.memory.store import MemoryStore
from greenloop_contracts import MemoryRecord


def retrieve(
    session: Session, principal_id: str, query: str, *, limit: int, correlation_id: str
) -> list[MemoryRecord]:
    if limit == 0:
        return []
    records, _ = MemoryStore(session, correlation_id).list_current(
        principal_id, limit=limit, offset=0
    )
    return records
