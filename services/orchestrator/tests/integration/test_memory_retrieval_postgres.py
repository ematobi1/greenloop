"""Semantic memory retrieval on real pgvector: ranking, principal scope, superseded,
deleted and expired records never return, recency fills the gaps, and the write
path and backfill add embeddings without touching memory_records."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.integration.pg import TEST_DATABASE_URL

from app.core import tokens
from app.core.config import Settings
from app.db.models import MemoryEmbeddingRow
from app.main import create_app
from app.memory import indexing, provenance, retrieval
from app.memory.embeddings import EmbeddingError, FakeEmbedder
from app.memory.store import MemoryStore

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

EMBEDDER = FakeEmbedder()


def _store(session_factory, make_record, principal_id, content, *, embed=True, expires_at=None):
    record = make_record(content, record_id=f"mem-{uuid.uuid4().hex}", principal_id=principal_id)
    if expires_at is not None:
        record = record.model_validate(record.model_dump() | {"expires_at": expires_at})
    with session_factory() as session:
        MemoryStore(session, "it").create(record)
        if embed:
            indexing.index_record(session, EMBEDDER, record)
        session.commit()
    return record


def _retrieve(session_factory, principal_id, query, limit=5):
    with session_factory() as session:
        return retrieval.retrieve(
            session,
            principal_id,
            query,
            limit=limit,
            correlation_id="it",
            query_vector=FakeEmbedder.vector(query),
            model=EMBEDDER.model,
        )


def test_the_closest_memory_ranks_first(pg_session_factory, make_record, principal_id):
    _store(pg_session_factory, make_record, principal_id, "Quarterly tax filing is due in April.")
    dog = _store(pg_session_factory, make_record, principal_id, "My dog is called Rex.")
    _store(pg_session_factory, make_record, principal_id, "Favourite colour is green.")
    results = _retrieve(pg_session_factory, principal_id, "what is my dog called", limit=1)
    assert [record.record_id for record in results] == [dog.record_id]


def test_other_principals_superseded_deleted_and_expired_never_return(
    pg_session_factory, make_record, new_principal
):
    owner, other = new_principal(), new_principal()
    foreign = _store(pg_session_factory, make_record, other, "My dog is called Max.")
    old = _store(pg_session_factory, make_record, owner, "My dog is called Fido.")
    gone = _store(pg_session_factory, make_record, owner, "My dog is called Spot.")
    expired = _store(
        pg_session_factory,
        make_record,
        owner,
        "My dog is called Old Yeller.",
        expires_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    with pg_session_factory() as session:
        store = MemoryStore(session, "it")
        newer = store.revise(
            owner, old.record_id, lambda r: provenance.supersede(r, "My dog is called Rex.", owner)
        )
        indexing.index_record(session, EMBEDDER, newer)
        store.delete(owner, gone.record_id, owner)
        session.commit()
    asyncio.run(asyncio.sleep(1.1))

    ids = {record.record_id for record in _retrieve(pg_session_factory, owner, "dog called", 10)}
    assert newer.record_id in ids
    assert ids.isdisjoint({foreign.record_id, old.record_id, gone.record_id, expired.record_id})


def test_unembedded_records_fill_the_remaining_slots(pg_session_factory, make_record, principal_id):
    embedded = _store(pg_session_factory, make_record, principal_id, "Prefers green tea.")
    plain = _store(pg_session_factory, make_record, principal_id, "Lives in Leeds.", embed=False)
    ids = [record.record_id for record in _retrieve(pg_session_factory, principal_id, "tea", 5)]
    assert ids[0] == embedded.record_id
    assert plain.record_id in ids
    assert len(ids) == len(set(ids))


def test_vectors_from_another_model_are_ignored(pg_session_factory, make_record, principal_id):
    record = _store(pg_session_factory, make_record, principal_id, "x", embed=False)
    with pg_session_factory() as session:
        session.add(
            MemoryEmbeddingRow(
                record_id=record.record_id, model="other-model", embedding=FakeEmbedder.vector("x")
            )
        )
        session.commit()
        ranked = retrieval.semantic(
            session, principal_id, FakeEmbedder.vector("x"), EMBEDDER.model, limit=5
        )
    assert record.record_id not in {r.record_id for r in ranked}


def test_backfill_embeds_only_live_records_missing_a_vector(
    pg_session_factory, make_record, principal_id
):
    missing = _store(pg_session_factory, make_record, principal_id, "Backfill me.", embed=False)
    deleted = _store(pg_session_factory, make_record, principal_id, "Deleted.", embed=False)
    with pg_session_factory() as session:
        MemoryStore(session, "it").delete(principal_id, deleted.record_id, principal_id)
        session.commit()
        asyncio.run(indexing.backfill(session, EMBEDDER))
        models = dict(
            session.execute(
                select(MemoryEmbeddingRow.record_id, MemoryEmbeddingRow.model).where(
                    MemoryEmbeddingRow.record_id.in_([missing.record_id, deleted.record_id])
                )
            ).all()
        )
        assert indexing.unembedded_live_records(session, EMBEDDER.model, 1000) == []
    assert models == {missing.record_id: EMBEDDER.model}


class _Down:
    model = "down"

    async def embed(self, texts):
        raise EmbeddingError("down")


def test_the_memory_api_indexes_on_write_and_survives_a_down_embedder(engine, db_roles):
    principal_id = f"it-{uuid.uuid4().hex[:12]}"
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=["testserver"],
        database_url=db_roles.url("greenloop_orchestrator").render_as_string(hide_password=False),
    )
    app = create_app(settings)
    with app.state.session_factory() as session:
        tokens.create_principal(session, principal_id, "Indexing")
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    body = {"scope": "private", "category": "user_context", "content": "Allergic to peanuts."}
    with TestClient(app) as client:
        app.state.embedder = EMBEDDER
        response = client.post("/v1/memory-records", json=body, headers=headers)
        assert response.status_code == 201, response.text
        created = response.json()
        revised = client.post(
            f"/v1/memory-records/{created['record_id']}/revisions",
            json={"operation": "correct", "content": "Allergic to peanuts and cashews."},
            headers=headers,
        ).json()
        app.state.embedder = _Down()
        unembedded = client.post("/v1/memory-records", json=body, headers=headers)
    assert unembedded.status_code == 201
    with app.state.session_factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(MemoryEmbeddingRow)
            .where(
                MemoryEmbeddingRow.record_id.in_(
                    [created["record_id"], revised["record_id"], unembedded.json()["record_id"]]
                )
            )
        )
    assert count == 2


def test_a_tombstone_never_ranks_even_with_a_stray_vector(
    pg_session_factory, make_record, principal_id
):
    record = _store(pg_session_factory, make_record, principal_id, "My cat is called Tom.")
    with pg_session_factory() as session:
        tombstone = MemoryStore(session, "it").delete(principal_id, record.record_id, principal_id)
        session.add(
            MemoryEmbeddingRow(
                record_id=tombstone.record_id,
                model=EMBEDDER.model,
                embedding=FakeEmbedder.vector("my cat is called"),
            )
        )
        session.commit()
        ranked = retrieval.semantic(
            session, principal_id, FakeEmbedder.vector("my cat is called"), EMBEDDER.model, limit=5
        )
    assert tombstone.record_id not in {r.record_id for r in ranked}
