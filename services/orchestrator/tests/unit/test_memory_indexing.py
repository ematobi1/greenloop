"""Embedding on write never blocks a memory write, tombstones and empty records are not
embedded, the chat engine hands its query vector and model to retrieval, and the CLI
backfill refuses to run without an embedder."""

import asyncio
import time

import pytest
from sqlalchemy import select
from tests.conftest import FakeProvider

from app import cli
from app.ai import engine as engine_module
from app.ai.engine import ChatEngine
from app.ai.providers.registry import ProviderRegistry
from app.conversations.store import ConversationStore
from app.core.config import Settings
from app.core.redaction import Redactor
from app.db.models import MemoryEmbeddingRow, PrincipalRow
from app.memory import indexing, provenance
from app.memory.embeddings import EmbeddingError, FakeEmbedder
from app.memory.store import MemoryStore


class DownEmbedder:
    model = "down"

    async def embed(self, texts):
        raise EmbeddingError("down")


def _embeddings(session):
    return session.scalars(select(MemoryEmbeddingRow)).all()


def _committed(session_factory, record):
    with session_factory() as session:
        session.add(PrincipalRow(principal_id=record.principal_id, display_name="User"))
        MemoryStore(session, "req-1").create(record)
        session.commit()
    return record


def test_a_committed_record_gets_its_vector_in_a_new_transaction(session_factory, make_record):
    record = _committed(session_factory, make_record("Prefers tea."))
    with session_factory() as session:
        assert indexing.index_committed(session, FakeEmbedder(), record) is True
        assert not session.in_transaction()
    with session_factory() as session:
        [row] = _embeddings(session)
    assert (row.record_id, row.model) == (record.record_id, FakeEmbedder.model)


def test_no_embedder_or_a_failing_one_embeds_nothing(session_factory, make_record):
    record = _committed(session_factory, make_record())
    with session_factory() as session:
        assert indexing.index_committed(session, None, record) is False
        assert indexing.index_committed(session, DownEmbedder(), record) is False
        assert _embeddings(session) == []


def test_tombstones_and_empty_records_are_not_embedded(session_factory, make_record):
    tombstone = provenance.tombstone(make_record(), "user-1")
    with session_factory() as session:
        assert indexing.index_committed(session, FakeEmbedder(), tombstone) is False
        assert _embeddings(session) == []


class SlowEmbedder:
    model = "slow"

    async def embed(self, texts):
        await asyncio.sleep(5)
        return [[0.0]]


def test_a_slow_query_embedding_falls_back_to_recency_quickly():
    started = time.monotonic()
    assert asyncio.run(indexing.embed_query(SlowEmbedder(), "x", timeout_seconds=0.05)) is None
    assert time.monotonic() - started < 2


def test_sync_embedding_works_outside_an_event_loop():
    vectors = indexing.embed_texts_sync(FakeEmbedder(), ["a", "b"])
    assert len(vectors) == 2
    assert indexing.embed_texts_sync(DownEmbedder(), ["a"]) is None


@pytest.fixture
def conversation_id(session_factory):
    with session_factory() as session:
        session.add(PrincipalRow(principal_id="user-1", display_name="User"))
        row = ConversationStore(session, "user-1", "req-0").create("Test")
        session.commit()
        return row.conversation_id


def test_the_engine_passes_its_query_vector_and_model_to_retrieval(
    session_factory, conversation_id, monkeypatch
):
    seen = {}

    def fake_retrieve(session, principal_id, query, **kwargs):
        seen.update(kwargs, query=query)
        return []

    monkeypatch.setattr(engine_module.retrieval, "retrieve", fake_retrieve)
    embedder = FakeEmbedder()
    engine = ChatEngine(
        session_factory,
        ProviderRegistry({"fake": FakeProvider(["ok"])}, "fake"),
        Redactor(),
        Settings(_env_file=None),
        embedder=embedder,
    )
    vector = asyncio.run(engine.embed_query("my dog"))
    assert vector == FakeEmbedder.vector("my dog")
    engine.prepare("user-1", conversation_id, "my dog", "req-1", query_vector=vector)
    assert seen["query_vector"] == vector
    assert seen["model"] == FakeEmbedder.model
    assert seen["query"] == "my dog"


def test_without_an_embedder_the_engine_uses_recency(session_factory):
    engine = ChatEngine(
        session_factory, ProviderRegistry({}, None), Redactor(), Settings(_env_file=None)
    )
    assert asyncio.run(engine.embed_query("anything")) is None


def test_embed_memory_needs_an_embedder(session_factory, capsys):
    assert cli.run(["embed-memory"], session_factory, None) == 1
    assert "EMBEDDING_PROVIDER" in capsys.readouterr().err


def test_a_vector_that_can_not_be_stored_never_fails_the_write(session_factory, make_record):
    record = _committed(session_factory, make_record("Prefers tea."))
    with session_factory() as session:
        assert indexing.index_committed(session, FakeEmbedder(), record) is True
    with session_factory() as session:
        # A concurrent backfill already stored this (record, model): the insert clashes.
        assert indexing.index_committed(session, FakeEmbedder(), record) is False
        assert not session.in_transaction()


def test_embedding_after_a_write_is_time_bounded(monkeypatch):
    monkeypatch.setattr(indexing, "WRITE_TIMEOUT_SECONDS", 0.05)
    started = time.monotonic()
    assert indexing.embed_texts_sync(SlowEmbedder(), ["x"]) is None
    assert time.monotonic() - started < 2
