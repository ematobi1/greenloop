"""Planner: draft an ordered set of Tasks for review. Drafting never executes anything."""

from greenloop_contracts import Task


async def draft_plan(principal_id: str, goal: str) -> list[Task]:
    raise NotImplementedError("TODO(phase-2): draft tasks with dependencies via the AI engine")
