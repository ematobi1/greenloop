from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import AuditRecordRow, MemoryRecordRow
from app.memory import provenance
from app.memory.context_builder import build_memory_context
from app.memory.store import MemoryConflictError, MemoryNotFoundError, MemoryStore
from greenloop_contracts import MemoryCategory, MemoryConfidence, MemoryScope


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def store(session):
    return MemoryStore(session, "req-1")


@pytest.fixture
def create(store, make_record):
    counter = iter(range(1000))

    def factory(content="Prefers morning summaries.", *, principal_id="user-1", **changes):
        record = make_record(content, record_id=f"mem-{next(counter)}", principal_id=principal_id)
        return store.create(record.model_copy(update=changes))

    return factory


def _supersede(content):
    return lambda original: provenance.supersede(original, content, original.principal_id)


def test_created_record_reads_back_equal(store, create):
    record = create()
    assert store.get("user-1", record.record_id) == record


def test_create_rejects_a_non_create_record(store, make_record):
    successor = provenance.supersede(make_record(), "v2", "user-1")
    with pytest.raises(ValueError, match="create"):
        store.create(successor)


def test_another_principals_record_looks_missing(store, create):
    record = create(principal_id="user-2")
    with pytest.raises(MemoryNotFoundError):
        store.get("user-1", record.record_id)
    with pytest.raises(MemoryNotFoundError):
        store.history("user-1", record.record_id)
    with pytest.raises(MemoryNotFoundError):
        store.revise("user-1", record.record_id, _supersede("mine now"))
    with pytest.raises(MemoryNotFoundError):
        store.delete("user-1", record.record_id, "user-1")


def test_shared_scope_is_still_owner_only(store, create):
    record = create(principal_id="user-2", scope=MemoryScope.SHARED)
    with pytest.raises(MemoryNotFoundError):
        store.get("user-1", record.record_id)
    assert store.list_current("user-1", limit=10, offset=0) == ([], 0)


def test_revise_appends_and_leaves_the_original_untouched(store, create):
    original = create("v1")
    successor = store.revise("user-1", original.record_id, _supersede("v2"))
    assert store.get("user-1", original.record_id).content == "v1"
    assert store.get("user-1", successor.record_id).content == "v2"
    assert [r.content for r in store.history("user-1", original.record_id)] == ["v1", "v2"]


def test_only_the_head_can_be_revised(store, create):
    original = create("v1")
    store.revise("user-1", original.record_id, _supersede("v2"))
    with pytest.raises(MemoryConflictError):
        store.revise("user-1", original.record_id, _supersede("v2 again"))


def test_revise_rejects_a_builder_that_does_not_revise(store, create):
    original = create("v1")
    with pytest.raises(ValueError, match="supersede or correct"):
        store.revise("user-1", original.record_id, lambda o: provenance.tombstone(o, "user-1"))


def test_history_follows_links_from_any_version_oldest_first(store, create):
    v1 = create("v1")
    v2 = store.revise("user-1", v1.record_id, _supersede("v2"))
    v3 = store.revise("user-1", v2.record_id, lambda o: provenance.correct(o, "v3", "user-1"))
    for record_id in (v1.record_id, v2.record_id, v3.record_id):
        chain = store.history("user-1", record_id)
        assert [r.record_id for r in chain] == [v1.record_id, v2.record_id, v3.record_id]


def test_list_returns_only_live_heads_newest_first(store, create):
    older = create("older", created_at=datetime(2026, 9, 1, tzinfo=UTC))
    newer = create("newer", created_at=datetime(2026, 9, 2, tzinfo=UTC))
    revised = store.revise("user-1", older.record_id, _supersede("older, revised"))
    deleted = create("deleted", created_at=datetime(2026, 9, 3, tzinfo=UTC))
    store.delete("user-1", deleted.record_id, "user-1")
    records, total = store.list_current("user-1", limit=10, offset=0)
    assert [r.record_id for r in records] == [revised.record_id, newer.record_id]
    assert total == 2


def test_list_filters_and_paginates(store, create):
    create("alpha decision", category=MemoryCategory.DECISION)
    create("beta decision", category=MemoryCategory.DECISION, scope=MemoryScope.SHARED)
    create("gamma", confidence=MemoryConfidence.VERIFIED)
    assert (
        store.list_current("user-1", limit=10, offset=0, category=MemoryCategory.DECISION)[1] == 2
    )
    assert store.list_current("user-1", limit=10, offset=0, scope=MemoryScope.SHARED)[1] == 1
    verified = store.list_current(
        "user-1", limit=10, offset=0, confidence=MemoryConfidence.VERIFIED
    )
    assert [r.content for r in verified[0]] == ["gamma"]
    page, total = store.list_current("user-1", limit=1, offset=1)
    assert (len(page), total) == (1, 3)


def test_text_query_is_case_insensitive_and_treats_wildcards_literally(store, create):
    create("Uses 100% of the budget")
    create("Uses 1000 of the budget")
    assert [
        r.content for r in store.list_current("user-1", limit=10, offset=0, query="100%")[0]
    ] == ["Uses 100% of the budget"]
    assert store.list_current("user-1", limit=10, offset=0, query="BUDGET")[1] == 2
    assert store.list_current("user-1", limit=10, offset=0, query="_")[1] == 0


def test_expired_records_are_hidden_but_still_deletable(store, create):
    past = datetime.now(UTC) - timedelta(days=1)
    record = create(created_at=past - timedelta(days=1), expires_at=past)
    with pytest.raises(MemoryNotFoundError):
        store.get("user-1", record.record_id)
    with pytest.raises(MemoryNotFoundError):
        store.revise("user-1", record.record_id, _supersede("v2"))
    assert store.list_current("user-1", limit=10, offset=0)[1] == 0
    assert store.delete("user-1", record.record_id, "user-1") is not None


def test_delete_hides_the_whole_chain_and_is_idempotent(store, create):
    v1 = create("v1")
    v2 = store.revise("user-1", v1.record_id, _supersede("v2"))
    tombstone = store.delete("user-1", v1.record_id, "user-1")
    assert tombstone.provenance.supersedes == v2.record_id
    assert tombstone.content == ""
    for record_id in (v1.record_id, v2.record_id):
        with pytest.raises(MemoryNotFoundError):
            store.get("user-1", record_id)
        with pytest.raises(MemoryNotFoundError):
            store.history("user-1", record_id)
    assert store.delete("user-1", v2.record_id, "user-1") is None


def test_every_write_is_audited_in_the_same_session(store, session, create):
    v1 = create("v1")
    v2 = store.revise("user-1", v1.record_id, _supersede("v2"))
    tombstone = store.delete("user-1", v1.record_id, "user-1")
    store.delete("user-1", v1.record_id, "user-1")
    rows = session.scalars(select(AuditRecordRow).order_by(AuditRecordRow.created_at)).all()
    assert sorted((row.action, row.resource_id) for row in rows) == sorted(
        [
            ("memory.create", v1.record_id),
            ("memory.supersede", v2.record_id),
            ("memory.delete", tombstone.record_id),
        ]
    )
    assert {row.correlation_id for row in rows} == {"req-1"}
    assert all(row.details["chain_id"] == v1.record_id for row in rows)


def test_rollback_discards_both_the_record_and_its_audit(session_factory, make_record):
    with session_factory() as session:
        MemoryStore(session, "req-1").create(make_record())
        session.rollback()
    with session_factory() as session:
        assert session.scalars(select(MemoryRecordRow)).all() == []
        assert session.scalars(select(AuditRecordRow)).all() == []


def test_stored_heads_feed_the_context_builder(store, create):
    create("Prefers <b>bold</b> summaries.")
    records, _ = store.list_current("user-1", limit=10, offset=0)
    context = build_memory_context(records, principal_id="user-1")
    assert context.included_ids == (records[0].record_id,)
    assert "&lt;b&gt;bold&lt;/b&gt;" in context.text
