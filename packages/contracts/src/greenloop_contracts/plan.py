"""Plan: a drafted, ordered list of steps for a goal. Drafting never executes anything.

Steps refer to the steps they depend on by index, and only to earlier ones, so a plan
is acyclic by construction and its order is always a valid execution order. A plan is
a `draft` until the user discards it; approving and running plans arrives with the
workflow engine (roadmap phase 4), which turns steps into Tasks.
"""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from greenloop_contracts.base import ContractModel, Identifier, LongText, ShortText, Timestamp

MAX_PLAN_STEPS = 20

Goal = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class PlanStatus(StrEnum):
    DRAFT = "draft"
    DISCARDED = "discarded"


class PlanStep(ContractModel):
    schema_version = "1"

    title: ShortText
    description: LongText = ""
    depends_on: tuple[Annotated[int, Field(ge=0)], ...] = ()


class Plan(ContractModel):
    schema_version = "1"

    plan_id: Identifier
    principal_id: Identifier
    goal: Goal
    status: PlanStatus = PlanStatus.DRAFT
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    conversation_id: Identifier | None = None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def _dependencies_point_backwards(self) -> "Plan":
        for index, step in enumerate(self.steps):
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError(f"step {index} lists a dependency twice")
            if any(dependency >= index for dependency in step.depends_on):
                raise ValueError(f"step {index} may only depend on earlier steps")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        return self
