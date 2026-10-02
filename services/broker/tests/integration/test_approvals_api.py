"""The broker approvals API on Postgres: service-token auth, owner scoping, the
human-only decision rule, idempotency, error shapes and audit (ADR 0009)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.integration.pg import TEST_DATABASE_URL

from app import service_tokens
from app.config import BrokerSettings
from app.db.tables import audit_events
from app.main import create_app
from greenloop_contracts import Approval, operation_hash

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set; Postgres integration skipped"
)


@pytest.fixture
def client(engine) -> TestClient:
    return TestClient(create_app(BrokerSettings(_env_file=None), engine=engine))


@pytest.fixture
def token(engine) -> str:
    return service_tokens.issue(engine, "orchestrator")[1]


@pytest.fixture
def owner() -> str:
    return f"user-{uuid.uuid4().hex[:12]}"


def headers(token: str | None, key: str | None = "auto", correlation: str | None = None) -> dict:
    result = {}
    if token is not None:
        result["Authorization"] = f"Bearer {token}"
    if key is not None:
        result["Idempotency-Key"] = f"idem-{uuid.uuid4().hex}" if key == "auto" else key
    if correlation is not None:
        result["X-Correlation-ID"] = correlation
    return result


def actor(principal_id: str, kind: str = "user", in_dispatch: bool = False) -> dict:
    return {"principal_id": principal_id, "kind": kind, "in_dispatch": in_dispatch}


def operation(principal_id: str, **arguments) -> dict:
    return {
        "principal_id": principal_id,
        "tool": "github",
        "operation": "create_issue",
        "consequence": "write",
        "arguments": arguments or {"repo": "greenloop", "title": "Bug"},
    }


def create(client, token, owner, key="auto", **arguments):
    return client.post(
        "/v1/approvals",
        json={"operation": operation(owner, **arguments), "actor": actor(owner, "system", True)},
        headers=headers(token, key),
    )


def decide(client, token, approval_id, who, approved=True, key="auto", **actor_fields):
    return client.post(
        f"/v1/approvals/{approval_id}/decisions",
        json={"approved": approved, "actor": actor(who, **actor_fields)},
        headers=headers(token, key),
    )


def events(engine, **where):
    statement = select(audit_events).order_by(audit_events.c.created_at)
    for column, value in where.items():
        statement = statement.where(audit_events.c[column] == value)
    with engine.connect() as connection:
        return list(connection.execute(statement).mappings())


# authentication


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Bearer glsvc_wrong", "Basic abc", "glsvc_no-scheme"],
)
def test_every_route_needs_a_valid_service_token(client, engine, owner, authorization):
    correlation = f"corr-{uuid.uuid4().hex}"
    request_headers = {"X-Correlation-ID": correlation, "Idempotency-Key": "idem-1"}
    if authorization is not None:
        request_headers["Authorization"] = authorization
    calls = [
        ("post", "/v1/approvals", {"json": {"operation": operation(owner), "actor": actor(owner)}}),
        ("get", "/v1/approvals", {"params": {"principal_id": owner}}),
        ("get", "/v1/approvals/apr-1", {"params": {"principal_id": owner}}),
        (
            "post",
            "/v1/approvals/apr-1/decisions",
            {"json": {"approved": True, "actor": actor(owner)}},
        ),
    ]
    for method, path, kwargs in calls:
        response = getattr(client, method)(path, headers=request_headers, **kwargs)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    refused = events(engine, correlation_id=correlation)
    assert len(refused) == len(calls)
    assert {(e["action"], e["outcome"]) for e in refused} == {
        ("service_token.authenticate", "denied")
    }


def test_authentication_comes_before_body_validation(client):
    response = client.post("/v1/approvals", json={"nonsense": True}, headers=headers(None))
    assert response.status_code == 401


def test_a_revoked_token_is_refused(client, engine, owner):
    token_id, token = service_tokens.issue(engine, "orchestrator")
    assert create(client, token, owner).status_code == 201
    service_tokens.revoke(engine, token_id)
    assert create(client, token, owner).status_code == 401


def test_the_token_never_appears_in_audit_or_responses(client, engine, token, owner):
    response = create(client, token, owner)
    assert token not in response.text
    assert all(token not in str(dict(e)) for e in events(engine))


# create


def test_create_returns_a_pending_approval_bound_to_the_operation(client, engine, token, owner):
    response = create(client, token, owner)
    assert response.status_code == 201
    approval = Approval.model_validate(response.json())
    assert approval.status == "pending"
    assert approval.operation_hash == operation_hash(approval.operation)
    [event] = events(engine, approval_id=approval.approval_id)
    assert event["actor"] == "service:orchestrator"
    assert event["principal_id"] == owner


def test_create_needs_an_idempotency_key(client, token, owner):
    for key in (None, "", "has space", "x" * 129):
        response = create(client, token, owner, key=key)
        assert response.status_code == 400, key
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_a_repeated_create_returns_the_same_approval(client, token, owner):
    first = create(client, token, owner, key="idem-same").json()
    second = create(client, token, owner, key="idem-same").json()
    assert second == first


def test_a_reused_key_for_another_operation_is_a_conflict(client, token, owner):
    assert create(client, token, owner, key="idem-reuse", n=1).status_code == 201
    response = create(client, token, owner, key="idem-reuse", n=2)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "approved"},
        {"approval_id": "apr-chosen"},
        {"summary": "harmless"},
        {"operation_hash": "0" * 64},
    ],
)
def test_create_refuses_caller_supplied_approval_fields(client, token, owner, extra):
    body = {"operation": operation(owner), "actor": actor(owner), **extra}
    response = client.post("/v1/approvals", json=body, headers=headers(token))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_create_refuses_an_actor_who_does_not_own_the_operation(client, token, owner):
    body = {"operation": operation(owner), "actor": actor("someone-else")}
    response = client.post("/v1/approvals", json=body, headers=headers(token))
    assert response.status_code == 422


def test_validation_errors_never_echo_request_values(client, token, owner):
    secret_looking = "sk-should-not-come-back"
    body = {"operation": operation(owner), "actor": actor(owner, kind=secret_looking)}
    response = client.post("/v1/approvals", json=body, headers=headers(token))
    assert response.status_code == 422
    assert secret_looking not in response.text
    assert "actor.kind" in response.json()["error"]["fields"]


# read


def test_get_and_list_are_owner_scoped(client, token, owner):
    approval = create(client, token, owner).json()
    path = f"/v1/approvals/{approval['approval_id']}"
    assert (
        client.get(path, params={"principal_id": owner}, headers=headers(token)).json() == approval
    )
    other = client.get(path, params={"principal_id": "someone-else"}, headers=headers(token))
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "APPROVAL_NOT_FOUND"
    listed = client.get("/v1/approvals", params={"principal_id": owner}, headers=headers(token))
    assert listed.json() == {"data": [approval], "meta": {"total": 1}}
    empty = client.get(
        "/v1/approvals", params={"principal_id": "someone-else"}, headers=headers(token)
    )
    assert empty.json() == {"data": [], "meta": {"total": 0}}


def test_list_filters_by_status_and_bounds_the_limit(client, token, owner):
    first = create(client, token, owner, n=1).json()
    create(client, token, owner, n=2)
    decide(client, token, first["approval_id"], owner)
    approved = client.get(
        "/v1/approvals",
        params={"principal_id": owner, "status": "approved"},
        headers=headers(token),
    ).json()
    assert [a["approval_id"] for a in approved["data"]] == [first["approval_id"]]
    for limit in (0, 101):
        response = client.get(
            "/v1/approvals", params={"principal_id": owner, "limit": limit}, headers=headers(token)
        )
        assert response.status_code == 422


def test_read_routes_need_a_principal_id(client, token):
    assert client.get("/v1/approvals", headers=headers(token)).status_code == 422


# decide


def test_the_owner_approves(client, engine, token, owner):
    approval = create(client, token, owner).json()
    response = decide(client, token, approval["approval_id"], owner)
    assert response.status_code == 201
    assert response.json()["status"] == "approved"
    assert response.json()["decided_by"] == owner


@pytest.mark.parametrize(
    ("kind", "in_dispatch"), [("system", False), ("system", True), ("user", True)]
)
def test_only_a_human_outside_a_dispatch_may_decide(
    client, engine, token, owner, kind, in_dispatch
):
    approval = create(client, token, owner).json()
    response = decide(
        client, token, approval["approval_id"], owner, kind=kind, in_dispatch=in_dispatch
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DECIDER_NOT_HUMAN"
    [denied] = events(
        engine, resource_id=approval["approval_id"], action="approval.decide", outcome="denied"
    )
    assert denied["details"] == {
        "reason": "decider_not_human",
        "kind": kind,
        "in_dispatch": in_dispatch,
    }
    current = client.get(
        f"/v1/approvals/{approval['approval_id']}",
        params={"principal_id": owner},
        headers=headers(token),
    )
    assert current.json()["status"] == "pending"


def test_someone_else_cannot_decide(client, token, owner):
    approval = create(client, token, owner).json()
    response = decide(client, token, approval["approval_id"], "someone-else")
    assert response.status_code == 404


def test_decisions_need_an_idempotency_key(client, token, owner):
    approval = create(client, token, owner).json()
    response = decide(client, token, approval["approval_id"], owner, key=None)
    assert response.status_code == 400


def test_a_repeated_decision_returns_the_stored_result(client, token, owner):
    approval = create(client, token, owner).json()
    first = decide(client, token, approval["approval_id"], owner, key="idem-decide")
    second = decide(client, token, approval["approval_id"], owner, key="idem-decide")
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json()


def test_deciding_twice_or_after_expiry_is_a_conflict(client, db_roles, token, owner):
    approval = create(client, token, owner).json()
    decide(client, token, approval["approval_id"], owner)
    again = decide(client, token, approval["approval_id"], owner, approved=False)
    assert (again.status_code, again.json()["error"]["code"]) == (409, "APPROVAL_NOT_PENDING")

    expiring = create(client, token, owner, n=3).json()
    with db_roles.admin_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE broker.approvals SET created_at = now() - interval '20 minutes',"
            " expires_at = now() - interval '5 minutes' WHERE approval_id = %s",
            (expiring["approval_id"],),
        )
    late = decide(client, token, expiring["approval_id"], owner)
    assert (late.status_code, late.json()["error"]["code"]) == (409, "APPROVAL_EXPIRED")


def test_decision_body_cannot_smuggle_a_status(client, token, owner):
    approval = create(client, token, owner).json()
    response = client.post(
        f"/v1/approvals/{approval['approval_id']}/decisions",
        json={"approved": True, "actor": actor(owner), "status": "consumed"},
        headers=headers(token),
    )
    assert response.status_code == 422


def test_a_malformed_approval_id_is_refused(client, token, owner):
    response = decide(client, token, "bad id!", owner)
    assert response.status_code in (404, 422)


def test_the_correlation_id_is_carried_into_audit(client, engine, token, owner):
    correlation = f"corr-{uuid.uuid4().hex}"
    body = {"operation": operation(owner), "actor": actor(owner)}
    client.post("/v1/approvals", json=body, headers=headers(token, correlation=correlation))
    [event] = events(engine, correlation_id=correlation)
    assert event["action"] == "approval.create"
