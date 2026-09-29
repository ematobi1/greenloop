"""Postgres-only memory guarantees: append-only triggers, chain constraints, races, e2e API."""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.integration.pg import TEST_DATABASE_URL

from app.core import tokens
from app.core.config import Settings
from app.db.models import AuditRecordRow, MemoryRecordRow
from app.main import create_app
from app.memory import provenance
from app.memory.store import MemoryConflictError, MemoryStore
from greenloop_contracts import MemoryScope

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


@pytest.fixture
def stored(pg_session_factory, principal_id, make_record):
    """A committed create record owned by `principal_id`."""
    record = make_record("original", record_id=f"mem-{uuid.uuid4().hex}", principal_id=principal_id)
    with pg_session_factory() as session:
        MemoryStore(session, "it").create(record)
        session.commit()
    return record


def _insert_raw(pg_session_factory, record, chain_id):
    with pg_session_factory() as session:
        session.add(MemoryRecordRow.from_contract(record, chain_id))
        session.commit()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE memory_records SET content = 'tampered' WHERE principal_id = :principal_id",
        "DELETE FROM memory_records WHERE principal_id = :principal_id",
        "TRUNCATE memory_records CASCADE",
    ],
)
def test_memory_records_are_append_only(engine, stored, statement):
    with (
        engine.begin() as connection,
        pytest.raises(DBAPIError, match="memory_records is append-only"),
    ):
        connection.execute(text(statement), {"principal_id": stored.principal_id})
    with engine.connect() as connection:
        content = connection.scalar(
            text("SELECT content FROM memory_records WHERE record_id = :id"),
            {"id": stored.record_id},
        )
    assert content == "original"


def test_a_record_can_have_only_one_successor(pg_session_factory, stored):
    _insert_raw(pg_session_factory, provenance.supersede(stored, "v2", "x"), stored.record_id)
    with pytest.raises(IntegrityError, match="uq_memory_records_supersedes"):
        _insert_raw(pg_session_factory, provenance.supersede(stored, "v2b", "x"), stored.record_id)


def test_a_successor_cannot_move_to_another_principal(pg_session_factory, stored, new_principal):
    hijack = provenance.supersede(stored, "mine now", "x").model_copy(
        update={"principal_id": new_principal()}
    )
    with pytest.raises(IntegrityError, match="fk_memory_records_predecessor"):
        _insert_raw(pg_session_factory, hijack, stored.record_id)


def test_a_successor_cannot_change_scope(pg_session_factory, stored):
    widened = provenance.supersede(stored, "v2", "x").model_copy(
        update={"scope": MemoryScope.SHARED}
    )
    with pytest.raises(IntegrityError, match="fk_memory_records_predecessor"):
        _insert_raw(pg_session_factory, widened, stored.record_id)


def test_a_successor_cannot_claim_another_chain(pg_session_factory, stored):
    with pytest.raises(IntegrityError, match="fk_memory_records_predecessor"):
        _insert_raw(pg_session_factory, provenance.supersede(stored, "v2", "x"), "mem-elsewhere")


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"content": ""}, "ck_memory_records_tombstone"),
        ({"operation": "create", "supersedes": "mem-x"}, "ck_memory_records_supersedes"),
        ({"chain_id": "mem-not-me"}, "ck_memory_records_chain_root"),
        ({"source": "rumor"}, "ck_memory_records_source"),
        ({"category": "gossip"}, "ck_memory_records_category"),
    ],
)
def test_check_constraints_back_the_contract(
    pg_session_factory, principal_id, make_record, changes, constraint
):
    record = make_record("x", record_id=f"mem-{uuid.uuid4().hex}", principal_id=principal_id)
    row = MemoryRecordRow.from_contract(record, record.record_id)
    for name, value in changes.items():
        setattr(row, name, value)
    with pg_session_factory() as session, pytest.raises(IntegrityError, match=constraint):
        session.add(row)
        session.commit()


def test_a_tombstone_cannot_keep_content(pg_session_factory, stored):
    row = MemoryRecordRow.from_contract(provenance.tombstone(stored, "x"), stored.record_id)
    row.content = "still here"
    with (
        pg_session_factory() as session,
        pytest.raises(IntegrityError, match="ck_memory_records_tombstone"),
    ):
        session.add(row)
        session.commit()


def _api_client(pg_session_factory, principal_id):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    app = create_app(Settings(_env_file=None, environment="test", allowed_hosts=["testserver"]))
    app.state.session_factory = pg_session_factory
    return app, {"Authorization": f"Bearer {token}"}


def test_concurrent_revisions_of_one_head_return_201_and_409(
    pg_session_factory, stored, monkeypatch
):
    """Both requests pass the head check before either inserts, so the loser only
    finds out from the unique `supersedes` constraint. It must get 409, never 500."""
    app, auth = _api_client(pg_session_factory, stored.principal_id)
    both_checked_head = threading.Barrier(2, timeout=10)
    real_supersede = provenance.supersede

    def supersede_after_both_checked(*args, **kwargs):
        both_checked_head.wait()
        return real_supersede(*args, **kwargs)

    monkeypatch.setattr(provenance, "supersede", supersede_after_both_checked)
    responses = []

    def revise(content: str) -> None:
        responses.append(
            TestClient(app).post(
                f"/v1/memory-records/{stored.record_id}/revisions",
                headers=auth,
                json={"operation": "supersede", "content": content},
            )
        )

    threads = [threading.Thread(target=revise, args=(f"v2-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(response.status_code for response in responses) == [201, 409]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "MEMORY_RECORD_CONFLICT"
    with pg_session_factory() as session:
        successors = session.scalars(
            select(MemoryRecordRow).where(MemoryRecordRow.supersedes == stored.record_id)
        ).all()
        revise_audits = session.scalars(
            select(AuditRecordRow).where(
                AuditRecordRow.action == "memory.supersede",
                AuditRecordRow.principal_id == stored.principal_id,
            )
        ).all()
    assert len(successors) == 1
    assert [row.resource_id for row in revise_audits] == [successors[0].record_id]


def test_store_race_raises_conflict_not_integrity_error(pg_session_factory, stored):
    both_checked_head = threading.Barrier(2, timeout=10)
    outcomes: list[str] = []

    def revise(content: str) -> None:
        def build(original):
            both_checked_head.wait()
            return provenance.supersede(original, content, original.principal_id)

        with pg_session_factory() as session:
            try:
                MemoryStore(session, "race").revise(stored.principal_id, stored.record_id, build)
                session.commit()
                outcomes.append("won")
            except MemoryConflictError:
                outcomes.append("conflict")

    threads = [threading.Thread(target=revise, args=(f"v2-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["conflict", "won"]


def test_end_to_end_memory_api_on_postgres(pg_session_factory, principal_id):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    app = create_app(Settings(_env_file=None, environment="test", allowed_hosts=["testserver"]))
    app.state.session_factory = pg_session_factory
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {token}"}

    created = client.post(
        "/v1/memory-records",
        headers=auth,
        json={
            "scope": "private",
            "category": "decision",
            "content": "Use 100% Postgres",
            "tags": ["infra"],
        },
    )
    assert created.status_code == 201
    record_id = created.json()["record_id"]
    revised = client.post(
        f"/v1/memory-records/{record_id}/revisions",
        headers=auth,
        json={"operation": "correct", "content": "Use Postgres with pgvector"},
    )
    assert revised.status_code == 201
    listed = client.get("/v1/memory-records", headers=auth, params={"q": "pgvector"}).json()
    assert [item["record_id"] for item in listed["data"]] == [revised.json()["record_id"]]
    assert listed["data"][0]["tags"] == ["infra"]
    assert (
        client.get("/v1/memory-records", headers=auth, params={"q": "100%"}).json()["meta"]["total"]
        == 0
    )
    history = client.get(f"/v1/memory-records/{record_id}/history", headers=auth).json()
    assert [item["provenance"]["operation"] for item in history["data"]] == ["create", "correct"]
    assert client.delete(f"/v1/memory-records/{record_id}", headers=auth).status_code == 204
    tombstone_id = next(
        a["resource_id"]
        for a in client.get("/v1/audit-records", headers=auth, params={"limit": 100}).json()["data"]
        if a["action"] == "memory.delete"
    )
    for version in (record_id, revised.json()["record_id"], tombstone_id):
        assert client.get(f"/v1/memory-records/{version}", headers=auth).status_code == 404
    shared = client.post(
        "/v1/memory-records",
        headers=auth,
        json={"scope": "shared", "category": "decision", "content": "x"},
    )
    assert shared.status_code == 422
    audit = client.get("/v1/audit-records", headers=auth, params={"limit": 100}).json()["data"]
    assert {"memory.create", "memory.correct", "memory.delete"} <= {a["action"] for a in audit}
