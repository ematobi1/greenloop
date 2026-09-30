"""Postgres-only chat guarantees: write-once messages, sequence races, e2e turn."""

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from tests.conftest import FakeProvider
from tests.integration.pg import TEST_DATABASE_URL

from app.ai.engine import ChatEngine
from app.ai.providers.registry import ProviderRegistry
from app.conversations.store import ConversationBusyError, ConversationStore
from app.core import tokens
from app.core.config import Settings
from app.core.redaction import Redactor
from app.db.models import AuditRecordRow, MessageRole, MessageRow
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)

IDLE_IN_TRANSACTION = text(
    "SELECT count(*) FROM pg_stat_activity"
    " WHERE datname = current_database() AND state = 'idle in transaction'"
)


@pytest.fixture
def conversation_id(pg_session_factory, principal_id):
    with pg_session_factory() as session:
        store = ConversationStore(session, principal_id, "it")
        conversation_id = store.create("It").conversation_id
        store.append(conversation_id, MessageRole.USER, "original")
        session.commit()
    return conversation_id


def test_messages_reject_update(engine, conversation_id):
    with (
        engine.begin() as connection,
        pytest.raises(DBAPIError, match="messages is append-only \\(UPDATE rejected\\)"),
    ):
        connection.execute(
            text("UPDATE messages SET content = 'tampered' WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
    with engine.connect() as connection:
        content = connection.scalar(
            text("SELECT content FROM messages WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
    assert content == "original"


def test_messages_can_be_erased_with_their_conversation(engine, conversation_id):
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM messages WHERE conversation_id = :id"), {"id": conversation_id}
        )
        connection.execute(
            text("DELETE FROM conversations WHERE conversation_id = :id"), {"id": conversation_id}
        )


def test_concurrent_appends_get_distinct_sequences(
    pg_session_factory, principal_id, conversation_id, monkeypatch
):
    """Both writers read the same max sequence before either inserts; the unique
    constraint rejects the loser, which retries and takes the next number."""
    both_read = threading.Barrier(2, timeout=10)
    first_call = threading.local()
    real_next = ConversationStore._next_sequence

    def next_after_both_read(self, cid):
        number = real_next(self, cid)
        if not getattr(first_call, "done", False):
            first_call.done = True
            both_read.wait()
        return number

    monkeypatch.setattr(ConversationStore, "_next_sequence", next_after_both_read)
    errors = []

    def append(content):
        try:
            with pg_session_factory() as session:
                ConversationStore(session, principal_id, "race").append(
                    conversation_id, MessageRole.USER, content
                )
                session.commit()
        except Exception as err:  # surfaced by the assertion below
            errors.append(err)

    threads = [threading.Thread(target=append, args=(f"racer-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    with pg_session_factory() as session:
        sequences = session.scalars(
            select(MessageRow.sequence)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.sequence)
        ).all()
    assert sequences == [1, 2, 3]


def test_concurrent_prepares_let_exactly_one_turn_in(
    pg_session_factory, principal_id, conversation_id, monkeypatch
):
    """Both claims reach the conditional UPDATE together; Postgres serializes them on
    the row lock and the loser re-checks the WHERE after the winner commits."""
    both_claiming = threading.Barrier(2, timeout=10)
    real_claim = ConversationStore.claim_turn

    def claim_together(self, *args):
        both_claiming.wait()
        return real_claim(self, *args)

    monkeypatch.setattr(ConversationStore, "claim_turn", claim_together)
    engine = ChatEngine(
        pg_session_factory,
        ProviderRegistry({"fake": FakeProvider()}, "fake"),
        Redactor(),
        Settings(_env_file=None),
    )
    outcomes = []

    def prepare(content):
        try:
            engine.prepare(principal_id, conversation_id, content, "race")
            outcomes.append("prepared")
        except ConversationBusyError:
            outcomes.append("busy")

    threads = [threading.Thread(target=prepare, args=(f"racer-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["busy", "prepared"]
    with pg_session_factory() as session:
        users = session.scalars(
            select(MessageRow.content).where(
                MessageRow.conversation_id == conversation_id, MessageRow.content != "original"
            )
        ).all()
    assert len(users) == 1


class GatedProvider(FakeProvider):
    """Holds the reply until `release` is set, so a turn stays in flight."""

    def __init__(self):
        super().__init__(["held ", "reply"])
        self.streaming = threading.Event()
        self.release = threading.Event()

    async def stream(self, request):
        self.streaming.set()
        await asyncio.to_thread(self.release.wait, 10)
        async for event in super().stream(request):
            yield event


def test_a_second_request_during_a_live_stream_gets_409(pg_session_factory, principal_id):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    app = create_app(Settings(_env_file=None, environment="test", allowed_hosts=["testserver"]))
    app.state.session_factory = pg_session_factory
    provider = GatedProvider()
    app.state.provider_registry = ProviderRegistry({"fake": provider}, "fake")
    auth = {"Authorization": f"Bearer {token}"}
    conversation_id = (
        TestClient(app).post("/v1/conversations", headers=auth, json={}).json()["conversation_id"]
    )
    url = f"/v1/conversations/{conversation_id}/messages"
    streamed = []

    def first_turn():
        streamed.append(
            TestClient(app).post(
                url, headers=auth | {"Accept": "text/event-stream"}, json={"content": "first"}
            )
        )

    thread = threading.Thread(target=first_turn)
    thread.start()
    assert provider.streaming.wait(10)
    busy = TestClient(app).post(url, headers=auth, json={"content": "second"})
    provider.release.set()
    thread.join(timeout=30)

    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "CONVERSATION_BUSY"
    assert "event: done" in streamed[0].text
    after = TestClient(app).post(url, headers=auth, json={"content": "third"})
    assert after.status_code == 201, after.text
    listed = TestClient(app).get(url, headers=auth).json()["data"]
    assert [(m["role"], m["content"]) for m in listed] == [
        ("user", "first"),
        ("assistant", "held reply"),
        ("user", "third"),
        ("assistant", "held reply"),
    ]


class ProbingProvider(FakeProvider):
    """Counts idle-in-transaction connections while the reply is streaming."""

    def __init__(self, engine):
        super().__init__(["Hello", " there."])
        self._engine = engine
        self.idle_in_transaction = None

    async def stream(self, request):
        with self._engine.connect() as connection:
            self.idle_in_transaction = connection.scalar(IDLE_IN_TRANSACTION)
        async for event in super().stream(request):
            yield event


def test_end_to_end_chat_turn_on_postgres(engine, pg_session_factory, principal_id):
    with pg_session_factory() as session:
        _, token = tokens.issue_token(session, principal_id, "it")
        session.commit()
    app = create_app(Settings(_env_file=None, environment="test", allowed_hosts=["testserver"]))
    app.state.session_factory = pg_session_factory
    provider = ProbingProvider(engine)
    app.state.provider_registry = ProviderRegistry({"fake": provider}, "fake")
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {token}"}

    conversation_id = client.post("/v1/conversations", headers=auth, json={}).json()[
        "conversation_id"
    ]
    json_turn = client.post(
        f"/v1/conversations/{conversation_id}/messages", headers=auth, json={"content": "Hi"}
    )
    assert json_turn.status_code == 201, json_turn.text
    assert provider.idle_in_transaction == 0
    sse_turn = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        headers=auth | {"Accept": "text/event-stream"},
        json={"content": "Again"},
    )
    assert "event: done" in sse_turn.text

    listed = client.get(f"/v1/conversations/{conversation_id}/messages", headers=auth).json()
    assert [(m["sequence"], m["role"]) for m in listed["data"]] == [
        (1, "user"),
        (2, "assistant"),
        (3, "user"),
        (4, "assistant"),
    ]
    with pg_session_factory() as session:
        turns = session.scalars(
            select(AuditRecordRow).where(
                AuditRecordRow.action == "chat.turn",
                AuditRecordRow.principal_id == principal_id,
            )
        ).all()
    assert len(turns) == 2
    assert all(turn.details["provider"] == "fake" for turn in turns)
