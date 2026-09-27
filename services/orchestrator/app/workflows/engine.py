"""Workflow engine: run a multi-step plan, respecting task dependencies and approvals."""

from greenloop_contracts import ExecutionResult, Task


async def run_workflow(tasks: list[Task]) -> list[ExecutionResult]:
    raise NotImplementedError("TODO(phase-4): topological order, pause on awaiting_approval")
