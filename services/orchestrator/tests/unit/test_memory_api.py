import pytest
from sqlalchemy import select

from app.db.models import AuditRecordRow
from greenloop_contracts import MemoryRecord

URL = "/v1/memory-records"


@pytest.fixture
def auth(issue_token):
    return {"Authorization": f"Bearer {issue_token('user-1')}"}


@pytest.fixture
def other_auth(issue_token):
    return {"Authorization": f"Bearer {issue_token('user-2')}"}


@pytest.fixture
def create(client, auth):
    def post(content="Prefers morning summaries.", headers=None, **fields):
        body = {"scope": "private", "category": "user_context", "content": content} | fields
        response = client.post(URL, headers=headers or auth, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return post


def _revise(client, auth, record_id, **body):
    return client.post(f"{URL}/{record_id}/revisions", headers=auth, json=body)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", URL),
        ("POST", URL),
        ("GET", f"{URL}/mem-1"),
        ("GET", f"{URL}/mem-1/history"),
        ("POST", f"{URL}/mem-1/revisions"),
        ("DELETE", f"{URL}/mem-1"),
    ],
)
def test_every_memory_route_requires_a_token(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_create_forces_owner_provenance_and_unverified(create):
    record = MemoryRecord.model_validate(create(source_ref="notes/2026-09-28"))
    assert record.principal_id == "user-1"
    assert record.confidence.value == "unverified"
    assert record.provenance.source.value == "user"
    assert record.provenance.created_by == "user-1"
    assert record.provenance.operation.value == "create"
    assert record.provenance.source_ref == "notes/2026-09-28"


@pytest.mark.parametrize(
    "extra",
    [
        {"principal_id": "user-2"},
        {"confidence": "verified"},
        {"provenance": {"source": "system"}},
        {"record_id": "mem-chosen"},
    ],
)
def test_create_rejects_fields_the_server_owns(client, auth, extra):
    body = {"scope": "private", "category": "user_context", "content": "x"} | extra
    response = client.post(URL, headers=auth, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"content": ""}, "content"),
        ({"content": "x" * 20001}, "content"),
        ({"category": "gossip"}, "category"),
        ({"scope": "public"}, "scope"),
        ({"tags": ["has space"]}, "tags.0"),
        ({"expires_at": "2026-09-28T12:00:00"}, "expires_at"),
    ],
)
def test_create_validates_input(client, auth, body, field):
    base = {"scope": "private", "category": "user_context", "content": "x"}
    response = client.post(URL, headers=auth, json=base | body)
    assert response.status_code == 422
    assert field in response.json()["error"]["fields"]


def test_blank_content_fails_the_contract_rule(client, auth):
    response = client.post(
        URL,
        headers=auth,
        json={"scope": "private", "category": "user_context", "content": "   	  "},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_MEMORY_RECORD"
    assert "content is required" in str(error["fields"])


def test_past_expiry_is_rejected_without_echoing_content(client, auth):
    marker = "private-marker-4417"
    response = client.post(
        URL,
        headers=auth,
        json={
            "scope": "private",
            "category": "user_context",
            "content": marker,
            "expires_at": "2020-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MEMORY_RECORD"
    assert marker not in response.text


def test_get_and_list_are_scoped_to_the_caller(client, auth, other_auth, create):
    mine = create("mine")
    theirs = create("theirs", headers=other_auth, scope="shared")
    assert client.get(f"{URL}/{mine['record_id']}", headers=auth).status_code == 200
    hidden = client.get(f"{URL}/{theirs['record_id']}", headers=auth)
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "MEMORY_RECORD_NOT_FOUND"
    listed = client.get(URL, headers=auth).json()
    assert [item["record_id"] for item in listed["data"]] == [mine["record_id"]]
    assert listed["meta"] == {"total": 1, "limit": 50, "offset": 0}


def test_list_filters_and_query(client, auth, create):
    create("about brokers", category="decision")
    create("unrelated")
    by_category = client.get(URL, headers=auth, params={"category": "decision"}).json()
    assert by_category["meta"]["total"] == 1
    by_text = client.get(URL, headers=auth, params={"q": "BROKERS"}).json()
    assert [item["content"] for item in by_text["data"]] == ["about brokers"]


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": ""}, {"q": "x" * 201}]
)
def test_list_rejects_out_of_range_params(client, auth, params):
    assert client.get(URL, headers=auth, params=params).status_code == 422


def test_supersede_appends_and_history_shows_the_chain(client, auth, create):
    v1 = create("v1", tags=["a"])
    response = _revise(
        client, auth, v1["record_id"], operation="supersede", content="v2", confidence="verified"
    )
    assert response.status_code == 201
    v2 = response.json()
    assert v2["provenance"]["supersedes"] == v1["record_id"]
    assert v2["confidence"] == "verified"
    assert v2["tags"] == ["a"]
    assert client.get(f"{URL}/{v1['record_id']}", headers=auth).json()["content"] == "v1"
    history = client.get(f"{URL}/{v2['record_id']}/history", headers=auth).json()
    assert [item["content"] for item in history["data"]] == ["v1", "v2"]
    assert history["meta"]["total"] == 2
    listed = client.get(URL, headers=auth).json()
    assert [item["record_id"] for item in listed["data"]] == [v2["record_id"]]


def test_correct_sets_corrected_and_changes_content_only(client, auth, create):
    v1 = create("wrong")
    corrected = _revise(client, auth, v1["record_id"], operation="correct", content="right")
    assert corrected.status_code == 201
    assert corrected.json()["confidence"] == "corrected"
    refused = _revise(
        client,
        auth,
        corrected.json()["record_id"],
        operation="correct",
        content="x",
        category="decision",
    )
    assert refused.status_code == 422


def test_revising_a_stale_version_is_409(client, auth, create):
    v1 = create("v1")
    assert (
        _revise(client, auth, v1["record_id"], operation="supersede", content="v2").status_code
        == 201
    )
    stale = _revise(client, auth, v1["record_id"], operation="supersede", content="v2b")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "MEMORY_RECORD_CONFLICT"


def test_cannot_revise_someone_elses_record(client, auth, other_auth, create):
    theirs = create("theirs", headers=other_auth)
    response = _revise(client, auth, theirs["record_id"], operation="supersede", content="mine")
    assert response.status_code == 404


def test_delete_is_a_tombstone_hides_the_chain_and_is_idempotent(client, auth, create):
    v1 = create("personal detail")
    v2 = _revise(client, auth, v1["record_id"], operation="supersede", content="v2").json()
    assert client.delete(f"{URL}/{v1['record_id']}", headers=auth).status_code == 204
    for record_id in (v1["record_id"], v2["record_id"]):
        assert client.get(f"{URL}/{record_id}", headers=auth).status_code == 404
        assert client.get(f"{URL}/{record_id}/history", headers=auth).status_code == 404
    assert client.get(URL, headers=auth).json()["meta"]["total"] == 0
    assert client.delete(f"{URL}/{v2['record_id']}", headers=auth).status_code == 204


def test_delete_of_unknown_or_foreign_record_is_404(client, auth, other_auth, create):
    theirs = create("theirs", headers=other_auth)
    assert client.delete(f"{URL}/{theirs['record_id']}", headers=auth).status_code == 404
    assert client.delete(f"{URL}/mem-missing", headers=auth).status_code == 404
    assert client.get(f"{URL}/{theirs['record_id']}", headers=other_auth).status_code == 200


def test_writes_are_audited_with_the_request_correlation_id(client, auth, create, session_factory):
    v1 = create("v1")
    response = _revise(client, auth, v1["record_id"], operation="supersede", content="v2")
    client.delete(f"{URL}/{v1['record_id']}", headers=auth)
    with session_factory() as session:
        rows = session.scalars(
            select(AuditRecordRow).where(AuditRecordRow.resource_type == "memory_record")
        ).all()
    assert sorted(row.action for row in rows) == [
        "memory.create",
        "memory.delete",
        "memory.supersede",
    ]
    revise_row = next(row for row in rows if row.action == "memory.supersede")
    assert revise_row.correlation_id == response.headers["X-Request-ID"]
    assert revise_row.actor == "user-1"


def test_audit_details_never_contain_memory_content(client, auth, create, session_factory):
    create("my passport number is 123")
    with session_factory() as session:
        details = [row.details for row in session.scalars(select(AuditRecordRow))]
    assert "passport" not in str(details)
