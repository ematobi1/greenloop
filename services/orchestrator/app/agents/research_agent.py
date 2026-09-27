"""Research agent: gathers and summarizes information with read-only tools."""

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, Dispatch, ExecutionResult


class ResearchAgent(BaseAgent):
    descriptor = Agent(
        agent_id="research-agent",
        name="Research",
        capabilities=("search", "summarize"),
        allowed_tools=("fetch",),
    )

    async def run(self, item: Dispatch) -> ExecutionResult:
        raise NotImplementedError("TODO(phase-4)")
