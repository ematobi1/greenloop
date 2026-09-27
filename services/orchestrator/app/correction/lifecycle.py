"""Self-correction: validate a result, and on failure record an ErrorReport and choose
retry, replan, escalate or abandon."""

from greenloop_contracts import CorrectionAction, Dispatch, ErrorReport, ExecutionResult


async def validate(item: Dispatch, result: ExecutionResult) -> ErrorReport | None:
    raise NotImplementedError("TODO(phase-4): check result against the task's expectations")


def choose_action(report: ErrorReport, item: Dispatch) -> CorrectionAction:
    raise NotImplementedError("TODO(phase-4): retry within max_attempts, else escalate")
