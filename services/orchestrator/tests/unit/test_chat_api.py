import json

import pytest
from sqlalchemy import select
from tests.conftest import FakeProvider

from app.ai.errors import AiError
from app.ai.providers.registry import ProviderRegistry
from app.conversations.store import ConversationStore
from app.db.models import AuditRecordRow, MessageRow

URL = "/v1/conversations"
SSE = {"Accept": "text/event-stream"}


@pytest.fixture
def auth(issue_token):
    return {"Authorization": f"Bearer {issue_token('user-1')}"}


@pytest.fixture
def other_auth(issue_token):
    return {"Authorization": f"Bearer {issue_token('user-2')}"}


@pytest.fixture
def conversation_id(client, auth):
    response = client.post(URL, headers=auth, json={"title": "Plans"})
    assert response.status_code == 201, response.text
    return response.json()["conversation_id"]


def _send(client, auth, conversation_id, content="Hi", headers=None, **body):
    return client.post(
        f"{URL}/{conversation_id}/messages",
        headers=auth | (headers or {}),
        json={"content": content} | body,
    )


def _events(response):
    events = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def _stored(session_factory):
    with session_factory() as session:
        return session.scalars(select(MessageRow).order_by(MessageRow.sequence)).all()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", URL),
        ("POST", URL),
        ("GET", f"{URL}/conv-1"),
        ("DELETE", f"{URL}/conv-1"),
        ("GET", f"{URL}/conv-1/messages"),
        ("POST", f"{URL}/conv-1/messages"),
    ],
)
def test_every_chat_route_requires_a_token(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_create_defaults_and_strips_the_title(client, auth):
    assert client.post(URL, headers=auth, json={}).json()["title"] == "New conversation"
    assert client.post(URL, headers=auth, json={"title": "  Trip  "}).json()["title"] == "Trip"


@pytest.mark.parametrize("body", [{"title": "   "}, {"title": "x" * 201}, {"owner": "user-2"}])
def test_create_rejects_bad_bodies(client, auth, body):
    response = client.post(URL, headers=auth, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_list_get_and_delete(client, auth, conversation_id):
    listed = client.get(URL, headers=auth).json()
    assert [item["conversation_id"] for item in listed["data"]] == [conversation_id]
    assert listed["meta"]["total"] == 1
    assert client.get(f"{URL}/{conversation_id}", headers=auth).json()["title"] == "Plans"

    assert client.delete(f"{URL}/{conversation_id}", headers=auth).status_code == 204
    assert client.get(f"{URL}/{conversation_id}", headers=auth).status_code == 404
    assert client.get(URL, headers=auth).json()["meta"]["total"] == 0


def test_someone_elses_conversation_is_not_found(
    client, other_auth, conversation_id, use_provider, session_factory
):
    use_provider(FakeProvider())
    for response in (
        client.get(f"{URL}/{conversation_id}", headers=other_auth),
        client.delete(f"{URL}/{conversation_id}", headers=other_auth),
        client.get(f"{URL}/{conversation_id}/messages", headers=other_auth),
        _send(client, other_auth, conversation_id),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert client.get(URL, headers=other_auth).json()["meta"]["total"] == 0
    assert _stored(session_factory) == []


def test_a_json_turn_returns_and_stores_both_messages(
    client, auth, conversation_id, use_provider, session_factory
):
    use_provider(FakeProvider(["Hello", " there."]))
    response = _send(client, auth, conversation_id, "Hi")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["user_message"]["content"], body["user_message"]["sequence"]) == ("Hi", 1)
    assert body["assistant_message"]["content"] == "Hello there."
    assert body["assistant_message"]["status"] == "complete"
    assert "input_tokens" not in body["assistant_message"]
    listed = client.get(f"{URL}/{conversation_id}/messages", headers=auth).json()
    assert [m["role"] for m in listed["data"]] == ["user", "assistant"]
    with session_factory() as session:
        [audit] = session.scalars(
            select(AuditRecordRow).where(AuditRecordRow.action == "chat.turn")
        ).all()
    assert audit.correlation_id == response.headers["X-Request-ID"]


def test_an_sse_turn_streams_message_deltas_and_done(client, auth, conversation_id, use_provider):
    use_provider(FakeProvider(["Hel", "lo"]))
    response = _send(client, auth, conversation_id, headers=SSE)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _events(response)
    assert events[0][0] == "message"
    assert events[0][1]["user_message"]["content"] == "Hi"
    assert "".join(data["text"] for name, data in events if name == "delta") == "Hello"
    assert events[-1][0] == "done"
    assert events[-1][1]["assistant_message"]["content"] == "Hello"


def test_an_sse_failure_sends_a_safe_error_with_the_partial_reply(
    client, auth, conversation_id, use_provider
):
    use_provider(FakeProvider(["partial"], error=AiError("unavailable"), error_after=1))
    events = _events(_send(client, auth, conversation_id, headers=SSE))

    name, data = events[-1]
    assert name == "error"
    assert data["code"] == "AI_UNAVAILABLE"
    assert data["message"] == "The model provider is unavailable. Try again shortly."
    assert data["partial_message"]["content"] == "partial"
    assert data["partial_message"]["status"] == "incomplete"


@pytest.mark.parametrize(
    ("error", "status"),
    [("unavailable", 503), ("timeout", 504), ("rejected", 502), ("refused", 422)],
)
def test_a_json_failure_maps_to_a_safe_error(
    client, auth, conversation_id, use_provider, error, status
):
    use_provider(FakeProvider(error=AiError(error), error_after=0))
    response = _send(client, auth, conversation_id)

    assert response.status_code == status
    assert response.json()["error"]["code"] == f"AI_{error.upper()}"


def test_an_overlong_message_is_rejected_before_anything_is_stored(
    client, auth, conversation_id, use_provider, session_factory
):
    provider = use_provider(FakeProvider())
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"ai_max_message_chars": 10}
    )
    response = _send(client, auth, conversation_id, "x" * 11)

    assert response.status_code == 422
    assert response.json()["error"]["fields"] == {"content": "At most 10 characters."}
    assert provider.requests == []
    assert _stored(session_factory) == []


def test_no_configured_provider_is_503_and_stores_nothing(
    client, auth, conversation_id, session_factory
):
    client.app.state.provider_registry = ProviderRegistry({}, "anthropic")
    response = _send(client, auth, conversation_id)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert _stored(session_factory) == []


def test_an_unknown_provider_name_is_422(client, auth, conversation_id, use_provider):
    use_provider(FakeProvider())
    response = _send(client, auth, conversation_id, provider="gpt")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_UNKNOWN_PROVIDER"


def test_a_busy_conversation_is_409_and_stores_nothing(
    client, auth, conversation_id, use_provider, session_factory
):
    provider = use_provider(FakeProvider())
    with session_factory() as session:
        ConversationStore(session, "user-1", "req").claim_turn(conversation_id, "turn-live", 60)
        session.commit()

    for headers in (None, SSE):
        response = _send(client, auth, conversation_id, headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONVERSATION_BUSY"
    assert provider.requests == []
    assert _stored(session_factory) == []


@pytest.mark.parametrize("stream", [False, True], ids=["json", "sse"])
def test_deleting_the_conversation_mid_turn_is_reported_as_not_found(
    client, auth, conversation_id, use_provider, session_factory, stream
):
    class DeletingProvider(FakeProvider):
        async def stream(self, request):
            with session_factory() as session:
                ConversationStore(session, "user-1", "req").delete(conversation_id)
                session.commit()
            async for event in super().stream(request):
                yield event

    use_provider(DeletingProvider(["gone"]))
    response = _send(client, auth, conversation_id, headers=SSE if stream else None)

    if stream:
        name, data = _events(response)[-1]
        assert (name, data["code"], data["partial_message"]) == (
            "error",
            "CONVERSATION_NOT_FOUND",
            None,
        )
    else:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert [m.role for m in _stored(session_factory)] == ["user"]


def test_a_truncated_json_turn_is_502_ai_truncated(client, auth, conversation_id, use_provider):
    use_provider(FakeProvider(["cut"], truncated=True))
    response = _send(client, auth, conversation_id)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AI_TRUNCATED"
