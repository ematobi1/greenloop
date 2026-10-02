import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.agents import registry as registry_module
from app.agents.base import BaseAgent
from app.audit import recorder
from app.db.models import AuditRecordRow, MemoryRecordRow
from app.memory import execution
from app.orchestration import dispatcher
from greenloop_contracts import Agent, AgentDomain, AgentStatus, ExecutionResult

SENTINEL = "SENTINEL-INPUT-9Z"


@pytest.fixture
def auth(issue_token):
    return {"Authorization": f"Bearer {issue_token()}"}


def _dispatch(client, auth, agent_id="echo-reference-agent", **extra):
    body = {"agent_id": agent_id, "task_id": "task-1", "inputs": {"note": SENTINEL}} | extra
    return client.post("/v1/dispatches", json=body, headers=auth)


def _audits(session_factory):
    with session_factory() as session:
        return session.scalars(
            select(AuditRecordRow).where(AuditRecordRow.action == "agent.dispatch")
        ).all()


def _memory_rows(session_factory):
    with session_factory() as session:
        return session.scalars(select(MemoryRecordRow)).all()


def test_dispatch_requires_a_token(client):
    response = client.post(
        "/v1/dispatches", json={"agent_id": "echo-reference-agent", "task_id": "t"}
    )
    assert response.status_code == 401


def test_an_echo_dispatch_returns_the_result_and_records_memory_and_audit(
    client, auth, session_factory
):
    response = _dispatch(client, auth)

    assert response.status_code == 200
    result = ExecutionResult.model_validate(response.json())
    assert result.status == "succeeded"
    assert result.output == {"echo": {"note": SENTINEL}}
    assert result.agent_id == "echo-reference-agent"
    assert result.task_id == "task-1"
    assert response.headers["X-Execution-Memory"] == "recorded"
    assert "X-Audit-Persistence" not in response.headers

    [audit] = _audits(session_factory)
    assert audit.outcome == "executed"
    assert audit.principal_id == "user-1"
    assert audit.resource_id == result.dispatch_id
    assert audit.correlation_id == response.headers["X-Request-ID"]
    assert audit.details == {
        "agent_id": "echo-reference-agent",
        "task_id": "task-1",
        "status": "succeeded",
        "error_code": None,
        "execution_memory": "recorded",
    }

    [memory] = _memory_rows(session_factory)
    assert memory.record_id == execution.execution_record_id(result.dispatch_id)
    assert (memory.principal_id, memory.scope, memory.category, memory.confidence) == (
        "user-1",
        "private",
        "task_execution_history",
        "verified",
    )
    assert memory.related_task_id == "task-1"
    content = json.loads(memory.content)
    assert content["status"] == "succeeded"
    assert content["dispatch_id"] == result.dispatch_id
    assert SENTINEL not in memory.content
    assert SENTINEL not in json.dumps(audit.details)


def test_a_failing_agent_is_a_200_with_a_failed_result_and_a_failed_audit(
    client, auth, session_factory
):
    response = _dispatch(client, auth, agent_id="failing-reference-agent")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "REFERENCE_AGENT_FAILED"
    [audit] = _audits(session_factory)
    assert audit.outcome == "failed"
    assert audit.details["error_code"] == "REFERENCE_AGENT_FAILED"
    assert json.loads(_memory_rows(session_factory)[0].content)["error_code"] == (
        "REFERENCE_AGENT_FAILED"
    )


def test_execution_memory_is_private_to_the_dispatching_principal(client, auth, issue_token):
    _dispatch(client, auth)
    other = {"Authorization": f"Bearer {issue_token('user-2')}"}
    assert client.get("/v1/memory-records", headers=other).json()["meta"]["total"] == 0
    mine = client.get("/v1/memory-records", headers=auth).json()
    assert [r["category"] for r in mine["data"]] == ["task_execution_history"]


def test_an_unknown_agent_is_404_and_the_refusal_is_audited(client, auth, session_factory):
    response = _dispatch(client, auth, agent_id="nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"
    [audit] = _audits(session_factory)
    assert (audit.outcome, audit.resource_type, audit.resource_id) == ("denied", "agent", "nope")
    assert audit.details == {"reason": "agent_unknown"}
    assert _memory_rows(session_factory) == []


class _DisabledAgent(BaseAgent):
    descriptor = Agent(
        agent_id="disabled-agent",
        name="Disabled",
        domain=AgentDomain.OTHER,
        version="1",
        capabilities=("x",),
        status=AgentStatus.DISABLED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    ran = False

    async def run(self, item):
        _DisabledAgent.ran = True
        raise AssertionError("a disabled agent must not run")


def test_an_inactive_agent_is_refused_and_the_refusal_is_audited(client, auth, session_factory):
    _DisabledAgent.ran = False
    client.app.state.agent_registry.register(_DisabledAgent())

    response = _dispatch(client, auth, agent_id="disabled-agent")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_NOT_ACTIVE"
    assert not _DisabledAgent.ran
    [audit] = _audits(session_factory)
    assert (audit.outcome, audit.resource_type, audit.resource_id) == (
        "denied",
        "agent",
        "disabled-agent",
    )
    assert audit.details == {"reason": "agent_disabled"}
    assert _memory_rows(session_factory) == []


@pytest.mark.parametrize(
    "body",
    [
        {"agent_id": "echo-reference-agent", "task_id": "t", "principal_id": "user-2"},
        {"agent_id": "echo-reference-agent", "task_id": "t", "dispatch_id": "dsp-mine"},
        {"agent_id": "Echo Agent", "task_id": "t"},
        {"agent_id": "echo-reference-agent", "task_id": "bad id"},
        {"agent_id": "echo-reference-agent", "task_id": "t", "timeout_ms": 0},
        {"agent_id": "echo-reference-agent", "task_id": "t", "timeout_ms": 120_001},
        {"agent_id": "echo-reference-agent", "task_id": "t", "timeout_ms": "5"},
        {"agent_id": "echo-reference-agent", "task_id": "t", "inputs": {"x": "y" * 70_000}},
    ],
)
def test_invalid_dispatch_requests_are_refused_before_running(client, auth, session_factory, body):
    response = client.post("/v1/dispatches", json=body, headers=auth)
    assert response.status_code == 422
    assert _audits(session_factory) == []


def test_a_memory_write_failure_still_returns_the_result_and_audits_it(
    client, auth, session_factory, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(dispatcher, "record_execution", broken)

    response = _dispatch(client, auth)

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.headers["X-Execution-Memory"] == "failed"
    assert "X-Audit-Persistence" not in response.headers
    [audit] = _audits(session_factory)
    assert audit.details["execution_memory"] == "failed"
    assert _memory_rows(session_factory) == []
    assert "disk full" not in response.text


def test_when_nothing_can_be_written_the_result_is_still_returned(
    client, auth, session_factory, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(recorder, "record", broken)

    response = _dispatch(client, auth)

    assert response.status_code == 200
    assert response.json()["output"] == {"echo": {"note": SENTINEL}}
    assert response.headers["X-Execution-Memory"] == "failed"
    assert response.headers["X-Audit-Persistence"] == "failed"
    assert _memory_rows(session_factory) == []
    assert "database gone" not in response.text


def test_no_database_is_503_before_any_agent_runs(client, auth, monkeypatch):
    ran = []

    async def spy(agent, item):
        ran.append(item)

    monkeypatch.setattr(dispatcher, "run", spy)
    session_factory = client.app.state.session_factory
    token_headers = auth
    client.app.state.session_factory = None
    try:
        response = _dispatch(client, token_headers)
    finally:
        client.app.state.session_factory = session_factory
    assert ran == []
    assert response.status_code == 503


def test_the_default_registry_is_installed_on_the_app(client):
    assert isinstance(client.app.state.agent_registry, registry_module.AgentRegistry)


def test_a_refusal_whose_audit_fails_still_refuses_and_says_so(
    client, auth, session_factory, monkeypatch
):
    def broken(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(recorder, "record", broken)

    response = _dispatch(client, auth, agent_id="nope")

    assert response.status_code == 404
    assert response.headers["X-Audit-Persistence"] == "failed"
    assert "database gone" not in response.text


def test_the_input_cap_counts_utf8_bytes_not_escaped_json():
    from app.api.v1.dispatches import MAX_INPUT_BYTES, DispatchCreate

    text = "é" * (MAX_INPUT_BYTES // 2 - 20)
    assert DispatchCreate(agent_id="echo-reference-agent", task_id="t", inputs={"t": text})


def test_the_dispatch_headers_are_documented_in_openapi(client):
    operation = client.app.openapi()["paths"]["/v1/dispatches"]["post"]
    assert set(operation["responses"]["200"]["headers"]) == {
        "X-Execution-Memory",
        "X-Audit-Persistence",
    }
