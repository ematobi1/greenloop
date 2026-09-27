"""Dispatcher: send each ready Task to an agent as a Dispatch and collect the result.

Tool use inside an agent still goes permission check, approval, broker, audit.
"""

from greenloop_contracts import Dispatch, ExecutionResult


async def dispatch(item: Dispatch) -> ExecutionResult:
    raise NotImplementedError("TODO(phase-4): resolve agent from registry and run it")
