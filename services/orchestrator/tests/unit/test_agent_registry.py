import asyncio
from datetime import UTC, datetime

import pytest

from app.agents.reference import EchoReferenceAgent, FailingReferenceAgent
from app.agents.registry import (
    AgentRegistrationError,
    AgentRegistry,
    UnknownAgentError,
    build_agent_registry,
)
from app.core.auth import Principal
from app.db.models import PrincipalRole
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


class _ToolUsingAgent(EchoReferenceAgent):
    descriptor = EchoReferenceAgent.descriptor.model_copy(
        update={"agent_id": "tool-agent", "allowed_tools": ("github.open_pr",)}
    )


def test_an_agent_with_tool_access_is_refused_without_a_dispatch_permission_check():
    registry = AgentRegistry()
    with pytest.raises(AgentRegistrationError, match=r"tools github.open_pr") as raised:
        registry.register(_ToolUsingAgent())
    assert "no dispatch permission check" in str(raised.value)
    with pytest.raises(UnknownAgentError):
        registry.get("tool-agent")


def test_an_agent_with_tool_access_registers_once_a_permission_check_exists():
    registry = AgentRegistry(permission_check=lambda principal, agent: False)
    registry.register(_ToolUsingAgent())
    assert registry.get("tool-agent").descriptor.allowed_tools == ("github.open_pr",)


def test_no_registered_agent_declares_tool_access_today():
    assert all(not agent.allowed_tools for agent in build_agent_registry().list())


def test_may_dispatch_defers_to_the_check_when_one_exists():
    allowed = AgentRegistry(
        permission_check=lambda principal, agent: principal.principal_id == "owner"
    )
    allowed.register(_ToolUsingAgent())
    agent = allowed.get("tool-agent")
    assert allowed.may_dispatch(_principal("owner"), agent)
    assert not allowed.may_dispatch(_principal("someone-else"), agent)
    assert build_agent_registry().may_dispatch(_principal("anyone"), EchoReferenceAgent())


class _ModelAgent(EchoReferenceAgent):
    descriptor = EchoReferenceAgent.descriptor.model_copy(
        update={"agent_id": "model-agent", "model_access": True}
    )


class _ModelAndToolAgent(EchoReferenceAgent):
    descriptor = EchoReferenceAgent.descriptor.model_copy(
        update={"agent_id": "both-agent", "model_access": True, "allowed_tools": ("web.fetch",)}
    )


def test_an_agent_with_model_access_is_refused_without_a_dispatch_permission_check():
    registry = AgentRegistry()
    with pytest.raises(AgentRegistrationError, match="can reach a model but"):
        registry.register(_ModelAgent())
    with pytest.raises(UnknownAgentError):
        registry.get("model-agent")


def test_an_agent_with_model_and_tool_access_names_both():
    with pytest.raises(AgentRegistrationError, match=r"tools web.fetch and a model"):
        AgentRegistry().register(_ModelAndToolAgent())


@pytest.mark.parametrize("agent", [_ModelAgent(), _ToolUsingAgent(), _ModelAndToolAgent()])
def test_agents_with_model_or_tool_access_register_once_a_check_exists(agent):
    registry = AgentRegistry(permission_check=lambda principal, descriptor: True)
    registry.register(agent)
    assert registry.get(agent.descriptor.agent_id) is agent


def test_an_agent_with_no_access_registers_without_a_check():
    registry = AgentRegistry()
    registry.register(EchoReferenceAgent())
    assert registry.may_dispatch(_principal("anyone"), registry.get("echo-reference-agent"))


def test_without_a_check_may_dispatch_refuses_anything_that_needs_one():
    registry = AgentRegistry()
    assert not registry.may_dispatch(_principal("anyone"), _ModelAgent())


def test_the_default_registry_uses_the_permission_model_check():
    from app.permissions import dispatch as dispatch_permission

    assert build_agent_registry()._permission_check is dispatch_permission.may_dispatch


def _principal(principal_id: str, role: PrincipalRole = PrincipalRole.USER) -> Principal:
    return Principal(principal_id=principal_id, display_name=principal_id, role=role)
