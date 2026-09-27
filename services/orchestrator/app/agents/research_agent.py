"""Research agent: gathers and summarizes information with read-only tools."""

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, AgentDomain, Dispatch, ExecutionResult


class ResearchAgent(BaseAgent):
    descriptor = Agent(
        agent_id="research-agent",
        name="Research",
        domain=AgentDomain.RESEARCH,
        version="0.1.0",
        capabilities=("search", "summarize"),
        allowed_tools=("fetch",),
    )

    async def run(self, item: Dispatch) -> ExecutionResult:
        raise NotImplementedError("TODO(phase-4)")
