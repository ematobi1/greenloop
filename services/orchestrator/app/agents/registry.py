"""Agent registry: the one place agents are registered and looked up by id.

Agents register in code at startup (see build_agent_registry), not through the API:
adding an agent is a reviewed code change, like adding a domain to the Agent contract.

An agent that declares tool access (`Agent.allowed_tools`) can only be registered on a
registry that has a dispatch permission check. None exists yet: the per-principal
check arrives in PR5b through the one permission model (`app/permissions/`), beside
approvals (ADR 0008). Until then such agents are refused at startup.
"""

from typing import Protocol

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, AgentDomain, AgentStatus


class UnknownAgentError(LookupError):
    pass


class AgentRegistrationError(ValueError):
    pass


class DispatchPermissionCheck(Protocol):
    """May `principal_id` dispatch `agent`? Supplied by app/permissions in PR5b."""

    def __call__(self, principal_id: str, agent: Agent) -> bool: ...


class AgentRegistry:
    def __init__(self, permission_check: DispatchPermissionCheck | None = None) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._permission_check = permission_check

    def register(self, agent: BaseAgent) -> None:
        descriptor = agent.descriptor
        if descriptor.agent_id in self._agents:
            raise AgentRegistrationError(f"agent {descriptor.agent_id!r} is already registered")
        if descriptor.allowed_tools and self._permission_check is None:
            raise AgentRegistrationError(
                f"agent {descriptor.agent_id!r} declares tool access "
                f"({', '.join(descriptor.allowed_tools)}) but this registry has no dispatch "
                "permission check; tool-using agents wait for PR5b (ADR 0008)"
            )
        self._agents[descriptor.agent_id] = agent

    def may_dispatch(self, principal_id: str, agent: BaseAgent) -> bool:
        """Without a check, only agents with no tool access can be registered, so
        there is nothing to permit. With one, the check decides."""
        if self._permission_check is None:
            return not agent.descriptor.allowed_tools
        return self._permission_check(principal_id, agent.descriptor)

    def get(self, agent_id: str) -> BaseAgent:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise UnknownAgentError(agent_id) from None

    def list(
        self, *, domain: AgentDomain | None = None, status: AgentStatus | None = None
    ) -> list[Agent]:
        """Descriptors sorted by agent id."""
        return [
            agent.descriptor
            for agent_id, agent in sorted(self._agents.items())
            if (domain is None or agent.descriptor.domain is domain)
            and (status is None or agent.descriptor.status is status)
        ]


def build_agent_registry() -> AgentRegistry:
    from app.agents.reference import EchoReferenceAgent, FailingReferenceAgent

    registry = AgentRegistry()
    registry.register(EchoReferenceAgent())
    registry.register(FailingReferenceAgent())
    return registry
