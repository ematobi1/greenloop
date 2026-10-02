import asyncio
from datetime import UTC, datetime

import pytest

from app.agents.reference import EchoReferenceAgent, FailingReferenceAgent
from app.agents.registry import AgentRegistry, UnknownAgentError, build_agent_registry
from greenloop_contracts import AgentDomain, AgentStatus, Dispatch, ExecutionStatus


def _dispatch(agent_id: str, inputs=None) -> Dispatch:
    return Dispatch(
        dispatch_id="dsp-1",
        task_id="task-1",
        agent_id=agent_id,
        principal_id="user-1",
        correlation_id="req-1",
        inputs=inputs or {},
        dispatched_at=datetime.now(UTC),
    )


def test_the_default_registry_holds_the_two_active_reference_agents():
    registry = build_agent_registry()
    agents = registry.list()
    assert [a.agent_id for a in agents] == ["echo-reference-agent", "failing-reference-agent"]
    assert {a.status for a in agents} == {AgentStatus.ACTIVE}


def test_duplicate_registration_is_refused():
    registry = AgentRegistry()
    registry.register(EchoReferenceAgent())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(EchoReferenceAgent())


def test_an_unknown_agent_raises():
    with pytest.raises(UnknownAgentError):
        build_agent_registry().get("nope")


def test_list_filters_by_domain_and_status():
    registry = build_agent_registry()
    assert len(registry.list(domain=AgentDomain.OTHER, status=AgentStatus.ACTIVE)) == 2
    assert registry.list(domain=AgentDomain.RESEARCH) == []
    assert registry.list(status=AgentStatus.DISABLED) == []


def test_the_echo_agent_returns_its_inputs():
    result = asyncio.run(EchoReferenceAgent().run(_dispatch("echo-reference-agent", {"a": [1]})))
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.output == {"echo": {"a": [1]}}
    assert (result.result_id, result.dispatch_id, result.task_id) == ("res-1", "dsp-1", "task-1")


def test_the_failing_agent_fails_with_a_user_safe_error():
    result = asyncio.run(FailingReferenceAgent().run(_dispatch("failing-reference-agent")))
    assert result.status is ExecutionStatus.FAILED
    assert result.error.code == "REFERENCE_AGENT_FAILED"
    assert result.output is None
