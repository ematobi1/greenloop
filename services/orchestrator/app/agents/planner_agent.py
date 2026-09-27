"""Planner agent: breaks a goal into sub-tasks during workflow execution."""

from app.agents.base import BaseAgent
from greenloop_contracts import Agent, Dispatch, ExecutionResult


class PlannerAgent(BaseAgent):
    descriptor = Agent(agent_id="planner-agent", name="Planner", capabilities=("plan",))

    async def run(self, item: Dispatch) -> ExecutionResult:
        raise NotImplementedError("TODO(phase-4)")
