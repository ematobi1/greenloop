"""Reasoning: interpret the user's request and decide whether it needs a plan, memory or tools."""

from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    ANSWER = "answer"
    REMEMBER = "remember"
    PLAN = "plan"


@dataclass(frozen=True)
class ReasoningResult:
    intent: Intent
    needs_memory: bool
    rationale: str


async def reason(principal_id: str, user_message: str) -> ReasoningResult:
    raise NotImplementedError("TODO(phase-2): classify intent with the AI engine")
