"""Agent registry: the one place agents are registered and looked up by id."""

from app.agents.base import BaseAgent


class AgentRegistry:
    def register(self, agent: BaseAgent) -> None:
        raise NotImplementedError("TODO(phase-4): reject duplicate ids and disabled agents")

    def get(self, agent_id: str) -> BaseAgent:
        raise NotImplementedError("TODO(phase-4)")

    def list(self) -> list[BaseAgent]:
        raise NotImplementedError("TODO(phase-4)")
