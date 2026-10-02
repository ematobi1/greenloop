"""Agent registry: the one place agents are registered and looked up by id.

Agents register in code at startup (see build_agent_registry), not through the API:
adding an agent is a reviewed code change, like adding a domain to the Agent contract.
"""

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, AgentDomain, AgentStatus


class UnknownAgentError(LookupError):
    pass


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        agent_id = agent.descriptor.agent_id
        if agent_id in self._agents:
            raise ValueError(f"agent {agent_id!r} is already registered")
        self._agents[agent_id] = agent

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
