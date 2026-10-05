"""Adds embeddings for memory records. Never blocks a memory write: if no embedder is
configured or it fails, the record is stored without one and `embed-memory` can
backfill it later (ADR 0011)."""

import asyncio

import anyio.from_thread
import structlog
from sqlalchemy import exists, select
from sqlalchemy.orm import Session, aliased

from app.db.models import MemoryEmbeddingRow, MemoryRecordRow
from app.memory.embeddings import Embedder, EmbeddingError
from greenloop_contracts import MemoryOperation, MemoryRecord

logger = structlog.get_logger(__name__)


async def embed_texts(embedder: Embedder | None, texts: list[str]) -> list[list[float]] | None:
    if embedder is None or not texts:
        return None
    try:
        return await embedder.embed(texts)
    except EmbeddingError as err:
        logger.warning("memory_embedding_failed", model=embedder.model, reason=str(err))
        return None


def embed_texts_sync(embedder: Embedder | None, texts: list[str]) -> list[list[float]] | None:
    """For sync code; FastAPI runs sync endpoints in a worker thread that can call the loop."""
    if embedder is None or not texts:
        return None
    try:
        return anyio.from_thread.run(embed_texts, embedder, texts)
    except RuntimeError:
        return asyncio.run(embed_texts(embedder, texts))


def index_record(session: Session, embedder: Embedder | None, record: MemoryRecord) -> bool:
    """Embed one just-written record into the same session. Returns whether it was embedded."""
    if record.provenance.operation is MemoryOperation.DELETE or not record.content.strip():
        return False
    vectors = embed_texts_sync(embedder, [record.content])
    if vectors is None or embedder is None:
        return False
    session.add(
        MemoryEmbeddingRow(record_id=record.record_id, model=embedder.model, embedding=vectors[0])
    )
    return True


def unembedded_live_records(session: Session, model: str, limit: int) -> list[MemoryRecordRow]:
    """Live heads with content and no embedding for `model`, oldest first."""
    successor = aliased(MemoryRecordRow)
    return list(
        session.scalars(
            select(MemoryRecordRow)
            .where(
                MemoryRecordRow.operation != MemoryOperation.DELETE.value,
                MemoryRecordRow.content != "",
                ~exists().where(successor.supersedes == MemoryRecordRow.record_id),
                ~exists().where(
                    MemoryEmbeddingRow.record_id == MemoryRecordRow.record_id,
                    MemoryEmbeddingRow.model == model,
                ),
            )
            .order_by(MemoryRecordRow.created_at, MemoryRecordRow.record_id)
            .limit(limit)
        )
    )


async def backfill(session: Session, embedder: Embedder, batch_size: int = 50) -> int:
    """Embed every live record missing a vector for this model. Returns how many were added."""
    added = 0
    while rows := unembedded_live_records(session, embedder.model, batch_size):
        vectors = await embed_texts(embedder, [row.content for row in rows])
        if vectors is None:
            break
        for row, vector in zip(rows, vectors, strict=True):
            session.add(
                MemoryEmbeddingRow(record_id=row.record_id, model=embedder.model, embedding=vector)
            )
        session.commit()
        added += len(rows)
    return added
