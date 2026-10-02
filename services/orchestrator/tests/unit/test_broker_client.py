"""BrokerClient: service-token auth, GET-only retries with backoff, idempotency keys
on POSTs, contract validation of responses, and errors without broker detail."""

import json
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from app.tools.broker_client import BACKOFF_BASE_SECONDS, BrokerClient, BrokerError
from greenloop_contracts import (
    Approval,
    ApprovalActor,
    ApprovalStatus,
    ToolPermission,
    operation_hash,
)

TOKEN = "glsvc_synthetic-test-token"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
OPERATION = ToolPermission(
    principal_id="user-1",
    tool="github",
    operation="create_issue",
    consequence="write",
    arguments={"repo": "greenloop"},
)
ACTOR = ApprovalActor(principal_id="user-1", kind="user", in_dispatch=False)


def approval_json(**overrides) -> dict:
    approval = Approval(
        approval_id="apr-1",
        principal_id="user-1",
        operation=OPERATION,
        operation_hash=operation_hash(OPERATION),
        summary="write: github.create_issue",
        expires_at=NOW + timedelta(minutes=15),
        created_at=NOW,
        updated_at=NOW,
    )
    return approval.model_dump(mode="json") | overrides


class Broker:
    """A scripted broker: each request pops the next response (or exception)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx2.Response(status, json=body)

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def client(self) -> BrokerClient:
        return BrokerClient(
            "http://broker:8100/",
            TOKEN,
            transport=httpx2.MockTransport(self.handler),
            sleep=self.sleep,
        )


def error(code: str) -> dict:
    return {"error": {"code": code, "message": "x"}}


async def test_create_sends_the_operation_actor_token_and_idempotency_key():
    broker = Broker((201, approval_json()))
    approval = await broker.client().create_approval(
        OPERATION, ACTOR, idempotency_key="idem-1", correlation_id="corr-1"
    )
    assert approval.approval_id == "apr-1"
    [request] = broker.requests
    assert (request.method, request.url.path) == ("POST", "/v1/approvals")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["idempotency-key"] == "idem-1"
    assert request.headers["x-correlation-id"] == "corr-1"
    assert json.loads(request.content) == {
        "operation": OPERATION.model_dump(mode="json"),
        "actor": {"principal_id": "user-1", "kind": "user", "in_dispatch": False},
    }


async def test_decide_posts_only_the_answer_and_the_actor():
    broker = Broker((201, approval_json()))
    await broker.client().decide_approval(
        "apr-1", ACTOR, approved=False, idempotency_key="idem-2", correlation_id="c"
    )
    [request] = broker.requests
    assert request.url.path == "/v1/approvals/apr-1/decisions"
    assert json.loads(request.content)["approved"] is False
    assert request.headers["idempotency-key"] == "idem-2"


async def test_list_and_get_send_the_principal_and_validate_the_response():
    broker = Broker(
        (200, {"data": [approval_json()], "meta": {"total": 1}}), (200, approval_json())
    )
    client = broker.client()
    listed, total = await client.list_approvals(
        principal_id="user-1", status=ApprovalStatus.PENDING, limit=5, correlation_id="c"
    )
    got = await client.get_approval("apr-1", principal_id="user-1", correlation_id="c")
    assert (listed, total) == ([got], 1)
    assert dict(broker.requests[0].url.params) == {
        "principal_id": "user-1",
        "status": "pending",
        "limit": "5",
    }
    assert "idempotency-key" not in broker.requests[1].headers


@pytest.mark.parametrize("failure", [(503, error("X")), httpx2.ConnectError("down")])
async def test_gets_are_retried_with_growing_jittered_backoff(failure):
    broker = Broker(failure, failure, (200, approval_json()))
    await broker.client().get_approval("apr-1", principal_id="user-1", correlation_id="c")
    assert len(broker.requests) == 3
    first, second = broker.sleeps
    assert BACKOFF_BASE_SECONDS <= first <= 2 * BACKOFF_BASE_SECONDS
    assert 2 * BACKOFF_BASE_SECONDS <= second <= 4 * BACKOFF_BASE_SECONDS


async def test_gets_give_up_after_three_attempts():
    broker = Broker((503, error("A")), (503, error("B")), (503, error("C")))
    with pytest.raises(BrokerError) as raised:
        await broker.client().get_approval("apr-1", principal_id="user-1", correlation_id="c")
    assert (raised.value.status, raised.value.code) == (503, "C")
    assert len(broker.requests) == 3


async def test_gets_are_not_retried_on_4xx():
    broker = Broker((404, error("APPROVAL_NOT_FOUND")))
    with pytest.raises(BrokerError, match="APPROVAL_NOT_FOUND"):
        await broker.client().get_approval("apr-1", principal_id="user-1", correlation_id="c")
    assert len(broker.requests) == 1
    assert broker.sleeps == []


@pytest.mark.parametrize("failure", [(503, error("X")), httpx2.ConnectError("down")])
async def test_posts_are_never_retried(failure):
    broker = Broker(failure, (201, approval_json()))
    with pytest.raises(BrokerError):
        await broker.client().decide_approval(
            "apr-1", ACTOR, approved=True, idempotency_key="k", correlation_id="c"
        )
    assert len(broker.requests) == 1
    assert broker.sleeps == []


async def test_network_errors_name_no_details():
    broker = Broker(httpx2.ConnectError(f"cannot reach broker with {TOKEN}"))
    with pytest.raises(BrokerError) as raised:
        await broker.client().create_approval(
            OPERATION, ACTOR, idempotency_key="k", correlation_id="c"
        )
    assert (raised.value.status, raised.value.code) == (None, "BROKER_UNREACHABLE")
    assert TOKEN not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "body",
    [
        approval_json(operation_hash="0" * 64),
        approval_json(status="consumed"),
        {"unexpected": True},
        [],
    ],
)
async def test_an_invalid_approval_from_the_broker_is_refused(body):
    broker = Broker((200, body))
    with pytest.raises(BrokerError, match="BROKER_BAD_RESPONSE"):
        await broker.client().get_approval("apr-1", principal_id="user-1", correlation_id="c")


@pytest.mark.parametrize(
    "body",
    [
        {"items": []},
        {"data": []},
        {"data": [], "meta": {}},
        {"data": [], "meta": {"total": "3"}},
        {"data": [], "meta": {"total": True}},
        {"data": {}, "meta": {"total": 0}},
        [],
    ],
)
async def test_a_malformed_list_is_refused(body):
    broker = Broker((200, body))
    with pytest.raises(BrokerError, match="BROKER_BAD_RESPONSE"):
        await broker.client().list_approvals(principal_id="user-1", correlation_id="c")


async def test_an_error_without_the_error_shape_gets_a_generic_code():
    broker = Broker((400, {"detail": "secret broker internals"}))
    with pytest.raises(BrokerError) as raised:
        await broker.client().get_approval("apr-1", principal_id="user-1", correlation_id="c")
    assert raised.value.code == "BROKER_ERROR"


def test_repr_never_shows_the_token():
    assert TOKEN not in repr(BrokerClient("http://broker:8100", TOKEN))
