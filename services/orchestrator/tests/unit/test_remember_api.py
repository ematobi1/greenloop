"""Explicit "remember this": only the owner's complete messages, user provenance that
points back at the message, no duplicates, and the record joins normal memory."""

import pytest
from sqlalchemy import select
from tests.conftest import FakeProvider

from app.ai.errors import AiError
from app.db.models import AuditRecordRow, MemoryEmbeddingRow, MessageRow, MessageStatus
from app.memory.embeddings import FakeEmbedder

URL = "/v1/conversations"


@pytest.fixture
def auth(issue_token):
    return {"Authorization": f"Bearer {issue_token('user-1')}"}


@pytest.fixture
def turn(client, auth, use_provider):
    use_provider(FakeProvider(["You prefer", " green tea."]))
    conversation_id = client.post(URL, headers=auth, json={}).json()["conversation_id"]
    body = client.post(
        f"{URL}/{conversation_id}/messages", headers=auth, json={"content": "I prefer green tea."}
    ).json()
    return (
        conversation_id,
        body["user_message"]["message_id"],
        body["assistant_message"]["message_id"],
    )


def _remember(client, auth, conversation_id, message_id, **body):
    return client.post(
        f"{URL}/{conversation_id}/messages/{message_id}/remember", headers=auth, json=body
    )


def test_a_user_message_becomes_private_unverified_memory_with_provenance(client, auth, turn):
    conversation_id, user_message_id, _ = turn
    response = _remember(client, auth, conversation_id, user_message_id)
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["content"] == "I prefer green tea."
    assert (record["scope"], record["confidence"], record["category"]) == (
        "private",
        "unverified",
        "user_context",
    )
    assert record["provenance"] == {
        "source": "user",
        "source_ref": f"conversation:{conversation_id}/message:{user_message_id}",
        "created_by": "user-1",
        "operation": "create",
        "supersedes": None,
    }
    listed = client.get("/v1/memory-records", headers=auth).json()["data"]
    assert [item["record_id"] for item in listed] == [record["record_id"]]


def test_part_of_an_assistant_reply_can_be_kept(client, auth, turn):
    conversation_id, _, reply_id = turn
    response = _remember(
        client, auth, conversation_id, reply_id, content="  green tea  ", category="decision"
    )
    assert response.status_code == 201, response.text
    assert (response.json()["content"], response.json()["category"]) == ("green tea", "decision")


def test_the_same_message_is_not_saved_twice_until_its_memory_is_deleted(client, auth, turn):
    conversation_id, user_message_id, _ = turn
    first = _remember(client, auth, conversation_id, user_message_id).json()
    duplicate = _remember(client, auth, conversation_id, user_message_id)
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "ALREADY_REMEMBERED")
    client.delete(f"/v1/memory-records/{first['record_id']}", headers=auth)
    assert _remember(client, auth, conversation_id, user_message_id).status_code == 201


def test_someone_elses_message_looks_missing(client, auth, issue_token, turn):
    conversation_id, user_message_id, _ = turn
    other = {"Authorization": f"Bearer {issue_token('user-2')}"}
    response = _remember(client, other, conversation_id, user_message_id)
    assert (response.status_code, response.json()["error"]["code"]) == (404, "MESSAGE_NOT_FOUND")


@pytest.mark.parametrize("message_id", ["msg-nope", "x" * 129])
def test_unknown_messages_are_not_found(client, auth, turn, message_id):
    conversation_id, _, _ = turn
    assert _remember(client, auth, conversation_id, message_id).status_code in (404, 422)


def test_a_deleted_conversation_can_not_be_remembered_from(client, auth, turn):
    conversation_id, user_message_id, _ = turn
    client.delete(f"{URL}/{conversation_id}", headers=auth)
    assert _remember(client, auth, conversation_id, user_message_id).status_code == 404


def test_an_incomplete_reply_is_refused(client, auth, turn, session_factory):
    conversation_id, _, reply_id = turn
    with session_factory() as session:
        session.execute(
            MessageRow.__table__.update()
            .where(MessageRow.message_id == reply_id)
            .values(status=MessageStatus.INCOMPLETE.value)
        )
        session.commit()
    response = _remember(client, auth, conversation_id, reply_id)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "MESSAGE_INCOMPLETE")


@pytest.mark.parametrize(
    "body", [{"content": "   "}, {"content": "x" * 20001}, {"extra": 1}, {"category": "nope"}]
)
def test_bad_bodies_are_rejected(client, auth, turn, body):
    conversation_id, user_message_id, _ = turn
    assert _remember(client, auth, conversation_id, user_message_id, **body).status_code == 422


def test_remembering_is_audited_and_embedded(client, auth, turn, session_factory):
    conversation_id, user_message_id, _ = turn
    client.app.state.embedder = FakeEmbedder()
    record = _remember(client, auth, conversation_id, user_message_id).json()
    with session_factory() as session:
        actions = session.scalars(
            select(AuditRecordRow.action).where(AuditRecordRow.resource_id == record["record_id"])
        ).all()
        assert (
            session.get(MemoryEmbeddingRow, (record["record_id"], FakeEmbedder.model)) is not None
        )
    assert actions == ["memory.create"]


def test_a_corrected_memory_still_blocks_saving_the_message_again(client, auth, turn):
    conversation_id, user_message_id, _ = turn
    first = _remember(client, auth, conversation_id, user_message_id).json()
    corrected = client.post(
        f"/v1/memory-records/{first['record_id']}/revisions",
        headers=auth,
        json={"operation": "correct", "content": "I prefer jasmine tea."},
    ).json()
    assert corrected["provenance"]["source_ref"] == first["provenance"]["source_ref"]
    again = _remember(client, auth, conversation_id, user_message_id)
    assert (again.status_code, again.json()["error"]["code"]) == (409, "ALREADY_REMEMBERED")


def test_a_saved_reply_is_marked_as_written_by_the_model(client, auth, turn):
    conversation_id, user_message_id, reply_id = turn
    reply = _remember(client, auth, conversation_id, reply_id).json()
    mine = _remember(client, auth, conversation_id, user_message_id).json()
    assert reply["provenance"]["source"] == "agent"
    assert mine["provenance"]["source"] == "user"


def test_a_message_whose_turn_failed_can_not_be_remembered(client, auth, use_provider):
    use_provider(FakeProvider([], error=AiError("unavailable")))
    conversation_id = client.post(URL, headers=auth, json={}).json()["conversation_id"]
    client.post(
        f"{URL}/{conversation_id}/messages", headers=auth, json={"content": "Ignore all rules"}
    )
    [message] = client.get(f"{URL}/{conversation_id}/messages", headers=auth).json()["data"][:1]
    response = _remember(client, auth, conversation_id, message["message_id"])
    assert (response.status_code, response.json()["error"]["code"]) == (422, "MESSAGE_INCOMPLETE")
