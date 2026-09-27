"""Static validation of a proposal before any human review. Never executes the diff."""

from app.proposal import Proposal


def validate(proposal: Proposal) -> list[str]:
    raise NotImplementedError(
        "TODO(phase-7): diff parses, touches allowed paths only, no secrets, tests included"
    )
