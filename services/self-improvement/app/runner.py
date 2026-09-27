"""Runner for proposed code. Two independent locks keep it from executing anything:

1. SELF_IMPROVEMENT_EXECUTION_ENABLED defaults to false.
2. Even when the flag is true, execution is refused until Slice B gates 1-3 are
   approved and an isolation mechanism exists.
"""

from app.config import SelfImprovementSettings
from app.proposal import Proposal


class ExecutionDisabledError(RuntimeError):
    pass


class GatesNotApprovedError(RuntimeError):
    pass


def run(proposal: Proposal, settings: SelfImprovementSettings) -> None:
    if not settings.self_improvement_execution_enabled:
        raise ExecutionDisabledError(
            "Self-improvement execution is disabled (SELF_IMPROVEMENT_EXECUTION_ENABLED=false)."
        )
    raise GatesNotApprovedError("Slice B gates 1-3 are not approved; execution stays blocked.")
