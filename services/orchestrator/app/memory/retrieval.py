"""Memory retrieval for a chat turn, scoped to one principal.

With a query vector, live records with an embedding from the same model are ranked by
cosine distance; any slots left over are filled with the most recent live records, so
records not embedded yet (embedder down, not backfilled) still reach the context.
Without a query vector, retrieval is recency only.

Live means: owned by the principal, the head of its chain (superseded versions never
come back), not a tombstone and not expired. Results are untrusted and go straight to
context_builder.build_memory_context.
"""

from datetime import UTC, datetime

from sqlalchemy import exists, select, text
from sqlalchemy.orm import Session, aliased

from app.db.models import MemoryEmbeddingRow, MemoryRecordRow
from app.memory.store import MemoryStore
from greenloop_contracts import MemoryOperation, MemoryRecord

EF_SEARCH = 400


def semantic(
    session: Session, principal_id: str, query_vector: list[float], model: str, *, limit: int
) -> list[MemoryRecord]:
    successor = aliased(MemoryRecordRow)
    now = datetime.now(UTC)
    if session.get_bind().dialect.name == "postgresql":
        # HNSW returns ef_search candidates across all principals before the filters run;
        # the default (40) can leave a principal with few or no semantic hits.
        session.execute(text(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}"))
    rows = session.scalars(
        select(MemoryRecordRow)
        .join(
            MemoryEmbeddingRow,
            (MemoryEmbeddingRow.record_id == MemoryRecordRow.record_id)
            & (MemoryEmbeddingRow.model == model),
        )
        .where(
            MemoryRecordRow.principal_id == principal_id,
            MemoryRecordRow.operation != MemoryOperation.DELETE.value,
            ~exists().where(successor.supersedes == MemoryRecordRow.record_id),
            MemoryRecordRow.expires_at.is_(None) | (MemoryRecordRow.expires_at > now),
        )
        .order_by(MemoryEmbeddingRow.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    return [row.to_contract() for row in rows]


def retrieve(
    session: Session,
    principal_id: str,
    query: str,
    *,
    limit: int,
    correlation_id: str,
    query_vector: list[float] | None = None,
    model: str | None = None,
) -> list[MemoryRecord]:
    if limit == 0:
        return []
    ranked = (
        semantic(session, principal_id, query_vector, model, limit=limit)
        if query_vector is not None and model is not None
        else []
    )
    if len(ranked) >= limit:
        return ranked
    seen = {record.record_id for record in ranked}
    recent, _ = MemoryStore(session, correlation_id).list_current(
        principal_id, limit=limit, offset=0
    )
    return (
        ranked
        + [record for record in recent if record.record_id not in seen][: limit - len(ranked)]
    )
