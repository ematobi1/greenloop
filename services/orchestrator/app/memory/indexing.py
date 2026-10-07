"""Adds embeddings for memory records. Never blocks a memory write: if no embedder is
configured or it fails, the record is stored without one and `embed-memory` can
backfill it later (ADR 0011)."""

import asyncio

import anyio.from_thread
import structlog
from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased

from app.db.models import MemoryEmbeddingRow, MemoryRecordRow
from app.memory.embeddings import Embedder, EmbeddingError
from greenloop_contracts import MemoryOperation, MemoryRecord

logger = structlog.get_logger(__name__)

QUERY_TIMEOUT_SECONDS = 3.0
WRITE_TIMEOUT_SECONDS = 5.0


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
        return anyio.from_thread.run(_bounded, embedder, texts)
    except RuntimeError:
        return asyncio.run(_bounded(embedder, texts))


async def _bounded(embedder: Embedder, texts: list[str]) -> list[list[float]] | None:
    """Embedding after a write gets WRITE_TIMEOUT_SECONDS at most, so a slow embedder never
    holds a request thread for its full client timeout."""
    try:
        async with asyncio.timeout(WRITE_TIMEOUT_SECONDS):
            return await embed_texts(embedder, texts)
    except TimeoutError:
        logger.warning("memory_embedding_timed_out", model=embedder.model)
        return None


def index_committed(session: Session, embedder: Embedder | None, record: MemoryRecord) -> bool:
    """Embed a record that is already committed, then store the vector in its own short
    transaction. The embedder is called with no transaction open, so a slow embedder never
    holds a connection or locks. Returns whether the vector was stored."""
    if record.provenance.operation is MemoryOperation.DELETE or not record.content.strip():
        return False
    vectors = embed_texts_sync(embedder, [record.content])
    if vectors is None or embedder is None:
        return False
    try:
        session.add(
            MemoryEmbeddingRow(
                record_id=record.record_id, model=embedder.model, embedding=vectors[0]
            )
        )
        session.commit()
    except SQLAlchemyError:
        # The record is already saved; a concurrent backfill or a database blip must not
        # turn that into an error for the caller.
        session.rollback()
        logger.warning("memory_embedding_not_stored", record_id=record.record_id)
        return False
    return True


async def embed_query(
    embedder: Embedder | None, text: str, timeout_seconds: float = QUERY_TIMEOUT_SECONDS
) -> list[float] | None:
    """The vector to rank memory against `text`, or None (recency only) on any failure or
    after `timeout_seconds`, so a slow embedder never holds up a chat turn or a plan."""
    if embedder is None:
        return None
    try:
        async with asyncio.timeout(timeout_seconds):
            vectors = await embed_texts(embedder, [text])
    except TimeoutError:
        logger.warning("memory_query_embedding_timed_out", model=embedder.model)
        return None
    return vectors[0] if vectors else None


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
