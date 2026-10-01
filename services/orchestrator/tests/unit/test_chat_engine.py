import asyncio

import pytest
from sqlalchemy import select
from tests.conftest import FakeProvider

from app.ai import engine as engine_module
from app.ai.engine import ChatEngine, Delta, Failed, Finished
from app.ai.errors import AiError
from app.ai.providers.registry import ProviderRegistry
from app.conversations.store import (
    ConversationBusyError,
    ConversationNotFoundError,
    ConversationStore,
)
from app.core.config import Settings
from app.core.redaction import REDACTED, Redactor
from app.db.models import AuditRecordRow, ConversationRow, MessageRow, PrincipalRow
from app.memory.store import MemoryStore

SECRET = "sk-ant-api03-synthetic-secret-value-0000000000"


@pytest.fixture
def conversation_id(session_factory):
    with session_factory() as session:
        session.add(PrincipalRow(principal_id="user-1", display_name="User"))
        row = ConversationStore(session, "user-1", "req-0").create("Test")
        session.commit()
        return row.conversation_id


def _engine(session_factory, provider, **settings):
    return ChatEngine(
        session_factory,
        ProviderRegistry({"fake": provider}, "fake"),
        Redactor(known_secrets=[SECRET]),
        Settings(_env_file=None, ai_timeout_seconds=0.5, **settings),
    )


def _events(engine, turn):
    async def collect():
        return [event async for event in engine.run(turn)]

    return asyncio.run(collect())


def _messages(session_factory, conversation_id):
    with session_factory() as session:
        return session.scalars(
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.sequence)
        ).all()


def _audits(session_factory, action="chat.turn"):
    with session_factory() as session:
        return session.scalars(select(AuditRecordRow).where(AuditRecordRow.action == action)).all()


def test_a_turn_streams_stores_both_messages_and_audits(session_factory, conversation_id):
    provider = FakeProvider(["Hello", " there."])
    engine = _engine(session_factory, provider)
    turn = engine.prepare("user-1", conversation_id, "Hi", "req-1")
    events = _events(engine, turn)

    assert "".join(e.text for e in events if isinstance(e, Delta)) == "Hello there."
    assert isinstance(events[-1], Finished)
    stored = _messages(session_factory, conversation_id)
    assert [(m.sequence, m.role, m.content, m.status) for m in stored] == [
        (1, "user", "Hi", "complete"),
        (2, "assistant", "Hello there.", "complete"),
    ]
    assert (stored[1].provider, stored[1].model) == ("fake", "fake-1")
    assert (stored[1].input_tokens, stored[1].output_tokens) == (12, 3)
    [audit] = _audits(session_factory)
    assert audit.outcome == "executed"
    assert audit.correlation_id == "req-1"
    assert audit.details["assistant_message_id"] == stored[1].message_id
    assert audit.details["output_tokens"] == 3
    assert audit.details["latency_ms"] >= 0
    assert "Hi" not in str(audit.details)


def test_history_and_memory_reach_the_request(session_factory, conversation_id, make_record):
    with session_factory() as session:
        MemoryStore(session, "req-0").create(make_record("Prefers tea.", record_id="mem-tea"))
        session.commit()
    provider = FakeProvider(["ok"])
    engine = _engine(session_factory, provider)
    for text in ("first", "second"):
        _events(engine, engine.prepare("user-1", conversation_id, text, "req"))
    request = provider.requests[-1]
    assert [(m.role, m.content) for m in request.messages] == [
        ("user", "first"),
        ("assistant", "ok"),
        ("user", "second"),
    ]
    assert 'id="mem-tea"' in request.system
    assert "Prefers tea." in request.system


def test_secrets_are_redacted_outbound_and_in_the_streamed_reply(session_factory, conversation_id):
    half = len(SECRET) // 2
    provider = FakeProvider(["Your key is ", SECRET[:half], SECRET[half:], " ok."])
    engine = _engine(session_factory, provider)
    events = _events(engine, engine.prepare("user-1", conversation_id, f"use {SECRET}", "req"))

    assert SECRET not in provider.requests[0].messages[-1].content
    streamed = "".join(e.text for e in events if isinstance(e, Delta))
    assert SECRET not in streamed and REDACTED in streamed
    assert SECRET not in _messages(session_factory, conversation_id)[1].content


def test_a_mid_stream_failure_keeps_the_partial_reply_as_incomplete(
    session_factory, conversation_id
):
    provider = FakeProvider(["partial ", "answer"], error=AiError("unavailable"), error_after=1)
    engine = _engine(session_factory, provider)
    events = _events(engine, engine.prepare("user-1", conversation_id, "Hi", "req"))

    failed = events[-1]
    assert isinstance(failed, Failed) and failed.error.code == "unavailable"
    assert failed.partial_message.content == "partial "
    assert failed.partial_message.status == "incomplete"
    [audit] = _audits(session_factory)
    assert audit.outcome == "failed"
    assert audit.details["error"] == "AI_UNAVAILABLE"


def test_incomplete_replies_are_left_out_of_later_history(session_factory, conversation_id):
    failing = FakeProvider(["half"], error=AiError("unavailable"), error_after=1)
    _events(
        _engine(session_factory, failing),
        _engine(session_factory, failing).prepare("user-1", conversation_id, "first", "req"),
    )
    provider = FakeProvider(["ok"])
    engine = _engine(session_factory, provider)
    _events(engine, engine.prepare("user-1", conversation_id, "second", "req"))
    assert [m.content for m in provider.requests[0].messages] == ["first", "second"]


def test_an_empty_reply_is_invalid_and_stores_nothing(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider([]))
    events = _events(engine, engine.prepare("user-1", conversation_id, "Hi", "req"))
    assert isinstance(events[-1], Failed)
    assert events[-1].error.code == "invalid_response"
    assert events[-1].partial_message is None
    assert [m.role for m in _messages(session_factory, conversation_id)] == ["user"]


def test_a_stalled_provider_times_out(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider(hang=True))
    events = _events(engine, engine.prepare("user-1", conversation_id, "Hi", "req"))
    assert isinstance(events[-1], Failed)
    assert events[-1].error.code == "timeout"


def test_a_client_disconnect_keeps_the_partial_reply(session_factory, conversation_id):
    provider = FakeProvider(["one ", "two ", "three"])
    engine = _engine(session_factory, provider)
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")

    async def read_one_then_disconnect():
        stream = engine.run(turn)
        first = await stream.__anext__()
        await stream.aclose()
        return first

    first = asyncio.run(read_one_then_disconnect())
    assert isinstance(first, Delta)
    stored = _messages(session_factory, conversation_id)
    assert stored[-1].role == "assistant" and stored[-1].status == "incomplete"
    assert _audits(session_factory)[0].outcome == "failed"


def test_prepare_stores_nothing_when_no_provider_is_configured(session_factory, conversation_id):
    engine = ChatEngine(
        session_factory,
        ProviderRegistry({}, "anthropic"),
        Redactor(),
        Settings(_env_file=None),
    )
    with pytest.raises(AiError) as err:
        engine.prepare("user-1", conversation_id, "Hi", "req")
    assert err.value.code == "not_configured"
    assert _messages(session_factory, conversation_id) == []


def test_prepare_rejects_someone_elses_conversation(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider())
    with pytest.raises(ConversationNotFoundError):
        engine.prepare("user-2", conversation_id, "Hi", "req")
    assert _messages(session_factory, conversation_id) == []


def test_run_to_completion_raises_the_ai_error(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider(error=AiError("rejected"), error_after=0))
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")
    with pytest.raises(AiError) as err:
        asyncio.run(engine.run_to_completion(turn))
    assert err.value.code == "rejected"


def _lease_holder(session_factory, conversation_id):
    with session_factory() as session:
        return session.get(ConversationRow, conversation_id).active_turn_id


def test_a_second_turn_is_busy_until_the_first_finishes(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider(["ok"]))
    first = engine.prepare("user-1", conversation_id, "one", "req")
    with pytest.raises(ConversationBusyError):
        engine.prepare("user-1", conversation_id, "two", "req")
    assert [m.content for m in _messages(session_factory, conversation_id)] == ["one"]

    _events(engine, first)
    assert _lease_holder(session_factory, conversation_id) is None
    _events(engine, engine.prepare("user-1", conversation_id, "two", "req"))
    assert [(m.role, m.content) for m in _messages(session_factory, conversation_id)] == [
        ("user", "one"),
        ("assistant", "ok"),
        ("user", "two"),
        ("assistant", "ok"),
    ]


@pytest.mark.parametrize(
    "provider",
    [
        FakeProvider(["partial"], error=AiError("unavailable"), error_after=1),
        FakeProvider(hang=True),
        FakeProvider([]),
    ],
    ids=["provider-error", "timeout", "empty-reply"],
)
def test_a_failed_turn_releases_the_lease(session_factory, conversation_id, provider):
    engine = _engine(session_factory, provider)
    events = _events(engine, engine.prepare("user-1", conversation_id, "Hi", "req"))
    assert isinstance(events[-1], Failed)
    assert _lease_holder(session_factory, conversation_id) is None


def test_a_client_disconnect_releases_the_lease(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider(["one ", "two"]))
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")

    async def read_one_then_disconnect():
        stream = engine.run(turn)
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(read_one_then_disconnect())
    assert _lease_holder(session_factory, conversation_id) is None


def test_a_request_too_large_keeps_no_lease(session_factory, conversation_id):
    tight = _engine(
        session_factory,
        FakeProvider(),
        ai_context_token_limit=4000,
        ai_max_output_tokens=3990,
    )
    with pytest.raises(AiError, match="too large"):
        tight.prepare("user-1", conversation_id, "Hi", "req")
    assert _lease_holder(session_factory, conversation_id) is None
    assert _messages(session_factory, conversation_id) == []


def test_the_lease_is_renewed_while_the_reply_streams(
    session_factory, conversation_id, monkeypatch
):
    monkeypatch.setattr(engine_module, "RENEW_INTERVAL_SECONDS", 0)
    renewals = []
    real_renew = ConversationStore.renew_turn

    def counting_renew(self, *args):
        renewals.append(real_renew(self, *args))
        return renewals[-1]

    monkeypatch.setattr(ConversationStore, "renew_turn", counting_renew)
    engine = _engine(session_factory, FakeProvider(["a", "b", "c"]))
    _events(engine, engine.prepare("user-1", conversation_id, "Hi", "req"))
    assert len(renewals) >= 3
    assert all(renewals)


def test_a_lost_lease_still_stores_the_reply_and_frees_nothing_it_does_not_hold(
    session_factory, conversation_id, monkeypatch
):
    monkeypatch.setattr(engine_module, "RENEW_INTERVAL_SECONDS", 0)
    engine = _engine(session_factory, FakeProvider(["late ", "reply"]))
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")
    with session_factory() as session:
        session.get(ConversationRow, conversation_id).active_turn_id = "turn-taken-over"
        session.commit()

    events = _events(engine, turn)
    assert isinstance(events[-1], Finished)
    assert _messages(session_factory, conversation_id)[-1].content == "late reply"
    assert _lease_holder(session_factory, conversation_id) == "turn-taken-over"


def _delete(session_factory, conversation_id):
    with session_factory() as session:
        ConversationStore(session, "user-1", "req-del").delete(conversation_id)
        session.commit()


def test_a_conversation_deleted_mid_turn_drops_the_reply_but_audits_it(
    session_factory, conversation_id
):
    provider = FakeProvider(["never ", "stored"])
    engine = _engine(session_factory, provider)
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")
    _delete(session_factory, conversation_id)

    events = _events(engine, turn)

    assert isinstance(events[-1], engine_module.Abandoned)
    assert [m.role for m in _messages(session_factory, conversation_id)] == ["user"]
    [audit] = _audits(session_factory)
    assert audit.outcome == "failed"
    assert audit.details["error"] == "CONVERSATION_DELETED"
    assert audit.details["assistant_message_id"] is None
    assert audit.details["output_tokens"] == 3


def test_run_to_completion_reports_a_deleted_conversation_as_not_found(
    session_factory, conversation_id
):
    engine = _engine(session_factory, FakeProvider(["x"]))
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")
    _delete(session_factory, conversation_id)
    with pytest.raises(ConversationNotFoundError):
        asyncio.run(engine.run_to_completion(turn))
    assert _audits(session_factory)[0].details["error"] == "CONVERSATION_DELETED"


def test_a_disconnect_after_deletion_does_not_raise_from_cleanup(session_factory, conversation_id):
    engine = _engine(session_factory, FakeProvider(["one ", "two"]))
    turn = engine.prepare("user-1", conversation_id, "Hi", "req")
    _delete(session_factory, conversation_id)

    async def read_one_then_disconnect():
        stream = engine.run(turn)
        await stream.__anext__()
        await stream.aclose()

    asyncio.run(read_one_then_disconnect())
    assert _audits(session_factory)[0].details["error"] == "CONVERSATION_DELETED"
