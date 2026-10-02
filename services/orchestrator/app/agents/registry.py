"""Agent registry: the one place agents are registered and looked up by id.

Agents register in code at startup (see build_agent_registry), not through the API:
adding an agent is a reviewed code change, like adding a domain to the Agent contract.

An agent that declares model access (`Agent.model_access`) or tool access
(`Agent.allowed_tools`) can only be registered on a registry that has a dispatch
permission check, and every dispatch of it asks that check. The check belongs to the
one permission model (`app/permissions/dispatch.py`); build_agent_registry installs it.
"""

from typing import TYPE_CHECKING, Protocol

from app.agents.base import BaseAgent
from app.permissions.dispatch import needs_dispatch_permission
from greenloop_contracts import Agent, AgentDomain, AgentStatus

if TYPE_CHECKING:
    from app.core.auth import Principal


class UnknownAgentError(LookupError):
    pass


class AgentRegistrationError(ValueError):
    pass


class DispatchPermissionCheck(Protocol):
    """May `principal` dispatch `agent`? app/permissions/dispatch.py supplies it."""

    def __call__(self, principal: "Principal", agent: Agent) -> bool: ...


class AgentRegistry:
    def __init__(self, permission_check: DispatchPermissionCheck | None = None) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._permission_check = permission_check

    def register(self, agent: BaseAgent) -> None:
        descriptor = agent.descriptor
        if descriptor.agent_id in self._agents:
            raise AgentRegistrationError(f"agent {descriptor.agent_id!r} is already registered")
        if needs_dispatch_permission(descriptor) and self._permission_check is None:
            access = (
                [f"tools {', '.join(descriptor.allowed_tools)}"] if descriptor.allowed_tools else []
            )
            access += ["a model"] if descriptor.model_access else []
            raise AgentRegistrationError(
                f"agent {descriptor.agent_id!r} can reach {' and '.join(access)} but this "
                "registry has no dispatch permission check (ADR 0008)"
            )
        self._agents[descriptor.agent_id] = agent

    def may_dispatch(self, principal: "Principal", agent: BaseAgent) -> bool:
        """Without a check, only agents that reach no model or tool can be registered,
        so there is nothing to permit. With one, the check decides."""
        if self._permission_check is None:
            return not needs_dispatch_permission(agent.descriptor)
        return self._permission_check(principal, agent.descriptor)

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
    from app.permissions.dispatch import may_dispatch

    registry = AgentRegistry(permission_check=may_dispatch)
    registry.register(EchoReferenceAgent())
    registry.register(FailingReferenceAgent())
    return registry
