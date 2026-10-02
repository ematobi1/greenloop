"""Orchestrator approvals: actor built from the authenticated Principal only, human-only
decisions refused before the broker is called, both outcomes audited, broker errors
mapped without detail, and the dispatch flag (ADR 0009 rules 3, 6, 9)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.auth import Principal
from app.db.models import AuditRecordRow, PrincipalRole
from app.orchestration.dispatch_context import dispatch_scope, in_dispatch
from app.permissions import approvals as service
from app.tools.broker_client import BrokerError
from greenloop_contracts import Approval, ToolPermission, operation_hash

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def make_approval(principal_id: str = "user-1", status: str = "pending") -> Approval:
    operation = ToolPermission(
        principal_id=principal_id,
        tool="github",
        operation="create_issue",
        consequence="write",
        arguments={"repo": "greenloop"},
    )
    decided = {} if status == "pending" else {"decided_by": principal_id, "decided_at": NOW}
    return Approval(
        approval_id="apr-1",
        principal_id=principal_id,
        operation=operation,
        operation_hash=operation_hash(operation),
        summary="write: github.create_issue",
        status=status,
        expires_at=NOW + timedelta(minutes=15),
        created_at=NOW,
        updated_at=NOW,
        **decided,
    )


class FakeBroker:
    def __init__(self, error: BrokerError | None = None):
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def _answer(self, name, approval, **kwargs):
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error
        return approval

    async def create_approval(self, operation, actor, **kwargs):
        return await self._answer(
            "create", make_approval(operation.principal_id), actor=actor, **kwargs
        )

    async def decide_approval(self, approval_id, actor, *, approved, **kwargs):
        status = "approved" if approved else "rejected"
        return await self._answer(
            "decide",
            make_approval(actor.principal_id, status),
            approval_id=approval_id,
            actor=actor,
            approved=approved,
            **kwargs,
        )

    async def get_approval(self, approval_id, **kwargs):
        return await self._answer(
            "get", make_approval(kwargs["principal_id"]), approval_id=approval_id, **kwargs
        )

    async def list_approvals(self, **kwargs):
        return [await self._answer("list", make_approval(kwargs["principal_id"]), **kwargs)]


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def api(client, broker):
    client.app.state.broker_client = broker
    return client


def auth(token: str, **extra) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


def audits(session_factory, action: str) -> list[AuditRecordRow]:
    with session_factory() as session:
        return list(session.scalars(select(AuditRecordRow).where(AuditRecordRow.action == action)))


# routes


def test_routes_need_a_token(api, broker):
    for method, path in (
        ("get", "/v1/approvals"),
        ("get", "/v1/approvals/apr-1"),
        ("post", "/v1/approvals/apr-1/decisions"),
    ):
        assert api.request(method, path, json={"approved": True}).status_code == 401
    assert broker.calls == []


def test_there_is_no_create_route(api, issue_token):
    response = api.post("/v1/approvals", json={}, headers=auth(issue_token()))
    assert response.status_code == 405


def test_list_and_get_use_the_principal_from_the_token(api, broker, issue_token):
    token = issue_token("user-1")
    listed = api.get(
        "/v1/approvals",
        params={"principal_id": "someone-else", "status": "pending", "limit": 7},
        headers=auth(token),
    )
    assert listed.status_code == 200
    assert listed.json()["meta"] == {"total": 1, "limit": 7}
    got = api.get(
        "/v1/approvals/apr-1", params={"principal_id": "someone-else"}, headers=auth(token)
    )
    assert got.status_code == 200
    assert [kwargs["principal_id"] for _, kwargs in broker.calls] == ["user-1", "user-1"]
    assert broker.calls[0][1]["status"] == "pending"


def test_a_user_decides_and_both_sides_are_told_who(api, broker, issue_token, session_factory):
    response = api.post(
        "/v1/approvals/apr-1/decisions",
        json={"approved": True},
        headers=auth(issue_token("user-1"), **{"Idempotency-Key": "idem-7"}),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "approved"
    [(name, kwargs)] = broker.calls
    assert name == "decide"
    assert kwargs["actor"].model_dump(mode="json") == {
        "principal_id": "user-1",
        "kind": "user",
        "in_dispatch": False,
    }
    assert kwargs["idempotency_key"] == "idem-7"
    [entry] = audits(session_factory, "approval.decide")
    assert (entry.outcome, entry.approval_id) == ("approved", "apr-1")
    assert entry.operation_hash == make_approval().operation_hash


def test_the_body_cannot_name_an_actor_or_principal(api, broker, issue_token):
    response = api.post(
        "/v1/approvals/apr-1/decisions",
        json={"approved": True, "actor": {"principal_id": "user-2", "kind": "user"}},
        headers=auth(issue_token("user-1")),
    )
    assert response.status_code == 422
    assert broker.calls == []


def test_a_missing_idempotency_key_gets_a_fresh_one(api, broker, issue_token):
    token = issue_token("user-1")
    for _ in range(2):
        api.post("/v1/approvals/apr-1/decisions", json={"approved": True}, headers=auth(token))
    keys = [kwargs["idempotency_key"] for _, kwargs in broker.calls]
    assert len(set(keys)) == 2
    assert all(key.startswith("decide-") for key in keys)


def test_a_malformed_idempotency_key_is_refused(api, broker, issue_token):
    response = api.post(
        "/v1/approvals/apr-1/decisions",
        json={"approved": True},
        headers=auth(issue_token(), **{"Idempotency-Key": "has space"}),
    )
    assert response.status_code == 400
    assert broker.calls == []


def test_a_system_principal_cannot_decide(api, broker, issue_token, session_factory):
    token = issue_token("verifier", PrincipalRole.SYSTEM)
    response = api.post(
        "/v1/approvals/apr-1/decisions", json={"approved": True}, headers=auth(token)
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DECIDER_NOT_HUMAN"
    assert broker.calls == []
    [entry] = audits(session_factory, "approval.decide")
    assert (entry.outcome, entry.resource_id) == ("denied", "apr-1")
    assert entry.details == {"reason": "decider_not_human", "kind": "system", "in_dispatch": False}


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("APPROVAL_NOT_FOUND", 404),
        ("APPROVAL_NOT_PENDING", 409),
        ("APPROVAL_EXPIRED", 409),
        ("IDEMPOTENCY_CONFLICT", 409),
    ],
)
def test_broker_refusals_pass_through_and_are_audited(
    api, broker, issue_token, session_factory, code, status
):
    broker.error = BrokerError(status, code)
    response = api.post(
        "/v1/approvals/apr-1/decisions", json={"approved": True}, headers=auth(issue_token())
    )
    assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    [entry] = audits(session_factory, "approval.decide")
    assert (entry.outcome, entry.details) == ("denied", {"reason": code})


@pytest.mark.parametrize(
    "error",
    [
        BrokerError(None, "BROKER_UNREACHABLE"),
        BrokerError(401, "UNAUTHENTICATED"),
        BrokerError(500, "INTERNAL"),
        BrokerError(None, "BROKER_BAD_RESPONSE"),
        BrokerError(403, "DECIDER_NOT_HUMAN"),
    ],
)
def test_other_broker_failures_are_a_502_without_detail(api, broker, issue_token, error):
    broker.error = error
    response = api.get("/v1/approvals", headers=auth(issue_token()))
    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "code": "BROKER_FAILED",
            "message": "The approval service could not complete the request.",
        }
    }


def test_approvals_are_unavailable_without_a_broker(client, issue_token):
    client.app.state.broker_client = None
    response = client.get("/v1/approvals", headers=auth(issue_token()))
    assert (response.status_code, response.json()["error"]["code"]) == (503, "BROKER_UNAVAILABLE")


def test_no_broker_client_without_a_service_token(settings):
    from app.main import create_app

    configured = settings.model_copy(update={"broker_url": "http://broker:8100"})
    assert create_app(configured).state.broker_client is None


# service: actor and dispatch flag


def test_the_actor_comes_from_the_principal():
    user = service.actor_for(Principal("user-1", "User"))
    system = service.actor_for(Principal("svc", "Svc", PrincipalRole.SYSTEM))
    assert (user.kind, user.in_dispatch, user.may_decide) == ("user", False, True)
    assert (system.kind, system.may_decide) == ("system", False)


def test_inside_a_dispatch_even_a_user_cannot_decide(session_factory, broker, issue_token):
    issue_token("user-1")

    async def attempt():
        with dispatch_scope():
            assert in_dispatch()
            await service.decide(
                broker,
                session_factory,
                Principal("user-1", "User"),
                "apr-1",
                approved=True,
                idempotency_key="k",
                correlation_id="c",
            )

    with pytest.raises(service.DeciderNotHumanError):
        asyncio.run(attempt())
    assert not in_dispatch()
    assert broker.calls == []
    [entry] = audits(session_factory, "approval.decide")
    assert entry.details["in_dispatch"] is True


def test_the_dispatch_flag_reaches_tasks_started_inside_it():
    async def child() -> bool:
        return in_dispatch()

    async def run() -> tuple[bool, bool]:
        with dispatch_scope():
            inside = await asyncio.create_task(child())
        return inside, await asyncio.create_task(child())

    assert asyncio.run(run()) == (True, False)


async def test_request_approval_creates_and_audits(session_factory, broker, issue_token):
    issue_token("user-1")
    principal = Principal("user-1", "User")
    approval = await service.request_approval(
        broker, session_factory, principal, make_approval().operation, correlation_id="c"
    )
    [(_, kwargs)] = broker.calls
    assert kwargs["actor"].principal_id == "user-1"
    assert kwargs["idempotency_key"].startswith("create-")
    [entry] = audits(session_factory, "approval.create")
    assert (entry.outcome, entry.approval_id) == ("approval_required", approval.approval_id)


async def test_request_approval_refusals_are_audited(session_factory, broker, issue_token):
    issue_token("user-1")
    broker.error = BrokerError(409, "IDEMPOTENCY_CONFLICT")
    with pytest.raises(BrokerError):
        await service.request_approval(
            broker,
            session_factory,
            Principal("user-1", "User"),
            make_approval().operation,
            correlation_id="c",
        )
    [entry] = audits(session_factory, "approval.create")
    assert (entry.outcome, entry.details) == ("denied", {"reason": "IDEMPOTENCY_CONFLICT"})


async def test_request_approval_is_only_for_the_principals_own_operation(session_factory, broker):
    with pytest.raises(ValueError, match="own operation"):
        await service.request_approval(
            broker,
            session_factory,
            Principal("user-2", "User"),
            make_approval("user-1").operation,
            correlation_id="c",
        )
    assert broker.calls == []


async def test_an_audit_failure_never_hides_the_brokers_result(broker):
    def broken_session():
        raise RuntimeError("database down")

    approval = await service.decide(
        broker,
        broken_session,
        Principal("user-1", "User"),
        "apr-1",
        approved=True,
        idempotency_key="k",
        correlation_id="c",
    )
    assert approval.status == "approved"
