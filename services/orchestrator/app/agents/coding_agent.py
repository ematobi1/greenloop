"""Coding agent: proposes code changes. Writes go through the broker and need approval."""

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, Dispatch, ExecutionResult


class CodingAgent(BaseAgent):
    descriptor = Agent(
        agent_id="coding-agent",
        name="Coding",
        capabilities=("code",),
        allowed_tools=("github",),
    )

    async def run(self, item: Dispatch) -> ExecutionResult:
        raise NotImplementedError("TODO(phase-4)")
