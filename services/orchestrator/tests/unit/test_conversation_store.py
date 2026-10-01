import pytest
from sqlalchemy import select

from app.conversations.store import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationStore,
    SequenceConflictError,
)
from app.db.models import AuditRecordRow, MessageRole, MessageStatus, PrincipalRow


@pytest.fixture
def session(session_factory):
    with session_factory() as session:
        session.add_all(
            [
                PrincipalRow(principal_id="user-1", display_name="One"),
                PrincipalRow(principal_id="user-2", display_name="Two"),
            ]
        )
        session.commit()
        yield session


def _store(session, principal_id="user-1"):
    return ConversationStore(session, principal_id, "req-1")


def _audit_actions(session):
    return [row.action for row in session.scalars(select(AuditRecordRow))]


def test_create_audits_and_lists_newest_activity_first(session):
    store = _store(session)
    older = store.create("Older")
    newer = store.create("Newer")
    store.append(older.conversation_id, MessageRole.USER, "bump")
    session.commit()

    rows, total = store.list_active(limit=10, offset=0)
    assert total == 2
    assert [row.conversation_id for row in rows] == [older.conversation_id, newer.conversation_id]
    assert _audit_actions(session) == ["conversation.create", "conversation.create"]


def test_another_principals_conversation_looks_missing(session):
    row = _store(session).create("Mine")
    session.commit()
    other = _store(session, "user-2")

    assert other.list_active(limit=10, offset=0) == ([], 0)
    for action in (
        lambda: other.get(row.conversation_id),
        lambda: other.delete(row.conversation_id),
        lambda: other.messages(row.conversation_id, limit=10, offset=0),
        lambda: other.append(row.conversation_id, MessageRole.USER, "hi"),
    ):
        with pytest.raises(ConversationNotFoundError):
            action()


def test_soft_delete_hides_the_conversation_and_repeats_as_a_no_op(session):
    store = _store(session)
    row = store.create("Doomed")
    store.delete(row.conversation_id)
    store.delete(row.conversation_id)
    session.commit()

    assert row.deleted_at is not None
    assert store.list_active(limit=10, offset=0) == ([], 0)
    with pytest.raises(ConversationNotFoundError):
        store.get(row.conversation_id)
    with pytest.raises(ConversationNotFoundError):
        store.append(row.conversation_id, MessageRole.USER, "too late")
    assert _audit_actions(session).count("conversation.delete") == 1


def test_messages_are_numbered_in_order_and_paginated(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    for text in ("a", "b", "c"):
        store.append(conversation_id, MessageRole.USER, text)
    session.commit()

    rows, total = store.messages(conversation_id, limit=2, offset=1)
    assert total == 3
    assert [(row.sequence, row.content) for row in rows] == [(2, "b"), (3, "c")]
    assert all(row.correlation_id == "req-1" for row in rows)


def test_history_is_the_newest_answered_turns_oldest_first(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.append(conversation_id, MessageRole.USER, "one")
    store.append(conversation_id, MessageRole.ASSISTANT, "cut off", status=MessageStatus.INCOMPLETE)
    store.append(conversation_id, MessageRole.USER, "two")
    store.append(conversation_id, MessageRole.ASSISTANT, "reply")
    session.commit()

    assert [row.content for row in store.history(conversation_id, 2)] == ["two", "reply"]
    assert [row.content for row in store.history(conversation_id, 10)] == ["two", "reply"]
    assert store.history(conversation_id, 0) == []


def test_a_taken_sequence_number_is_retried(session, monkeypatch):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.append(conversation_id, MessageRole.USER, "first")
    real_next = store._next_sequence
    handed_out = iter([1])
    monkeypatch.setattr(
        store, "_next_sequence", lambda cid: next(handed_out, None) or real_next(cid)
    )

    row = store.append(conversation_id, MessageRole.USER, "second")
    session.commit()
    assert row.sequence == 2


def test_a_sequence_that_never_frees_up_raises_conflict(session, monkeypatch):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.append(conversation_id, MessageRole.USER, "first")
    monkeypatch.setattr(store, "_next_sequence", lambda _cid: 1)

    with pytest.raises(SequenceConflictError):
        store.append(conversation_id, MessageRole.USER, "second")


def _lease(session, conversation_id):
    session.expire_all()
    row = _store(session).get(conversation_id)
    return row.active_turn_id, row.turn_lease_expires_at


def test_a_held_turn_lease_makes_the_conversation_busy_until_released(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.claim_turn(conversation_id, "turn-a", 60)
    with pytest.raises(ConversationBusyError):
        store.claim_turn(conversation_id, "turn-b", 60)

    store.release_turn(conversation_id, "turn-a")
    store.claim_turn(conversation_id, "turn-b", 60)
    assert _lease(session, conversation_id)[0] == "turn-b"


def test_an_expired_lease_can_be_taken_over(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.claim_turn(conversation_id, "turn-crashed", -1)
    store.claim_turn(conversation_id, "turn-next", 60)
    assert _lease(session, conversation_id)[0] == "turn-next"


def test_only_the_holder_can_renew_or_release(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.claim_turn(conversation_id, "turn-a", 60)
    _, first_expiry = _lease(session, conversation_id)

    assert store.renew_turn(conversation_id, "turn-a", 600)
    assert _lease(session, conversation_id)[1] > first_expiry
    assert not store.renew_turn(conversation_id, "turn-other", 600)
    store.release_turn(conversation_id, "turn-other")
    assert _lease(session, conversation_id)[0] == "turn-a"


def test_another_principal_cannot_claim_or_release(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.claim_turn(conversation_id, "turn-a", 60)
    other = _store(session, "user-2")

    with pytest.raises(ConversationNotFoundError):
        other.claim_turn(conversation_id, "turn-b", 60)
    other.release_turn(conversation_id, "turn-a")
    assert not other.renew_turn(conversation_id, "turn-a", 60)
    assert _lease(session, conversation_id)[0] == "turn-a"


def test_a_deleted_conversation_cannot_be_claimed(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.delete(conversation_id)
    with pytest.raises(ConversationNotFoundError):
        store.claim_turn(conversation_id, "turn-a", 60)


def test_history_keeps_only_answered_turns(session):
    store = _store(session)
    conversation_id = store.create("Chat").conversation_id
    store.append(conversation_id, MessageRole.USER, "answered")
    store.append(conversation_id, MessageRole.ASSISTANT, "reply")
    store.append(conversation_id, MessageRole.USER, "refused or rejected")
    store.append(conversation_id, MessageRole.USER, "cut off")
    store.append(conversation_id, MessageRole.ASSISTANT, "partial", status=MessageStatus.INCOMPLETE)
    store.append(conversation_id, MessageRole.USER, "answered again")
    store.append(conversation_id, MessageRole.ASSISTANT, "second reply")
    store.append(conversation_id, MessageRole.USER, "pending")
    session.commit()

    assert [(m.role, m.content) for m in store.history(conversation_id, 10)] == [
        ("user", "answered"),
        ("assistant", "reply"),
        ("user", "answered again"),
        ("assistant", "second reply"),
    ]
    assert [m.content for m in store.history(conversation_id, 2)] == [
        "answered again",
        "second reply",
    ]
