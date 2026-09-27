"""Task: a unit of planned work owned by a principal.

The task's own status is the source of truth for progress; Dispatch and
ExecutionResult records are the history of attempts to complete it.
"""

from enum import StrEnum

from pydantic import model_validator

from greenloop_contracts.base import (
    AgentIdentifier,
    ContractModel,
    Identifier,
    LongText,
    ShortText,
    Timestamp,
)


class TaskStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(ContractModel):
    schema_version = "2"

    task_id: Identifier
    principal_id: Identifier
    title: ShortText
    description: LongText = ""
    status: TaskStatus = TaskStatus.PENDING
    parent_task_id: Identifier | None = None
    depends_on: tuple[Identifier, ...] = ()
    assigned_agent_id: AgentIdentifier | None = None
    created_at: Timestamp
    updated_at: Timestamp

    @model_validator(mode="after")
    def _consistent(self) -> "Task":
        if self.parent_task_id == self.task_id:
            raise ValueError("a task cannot be its own parent")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on entries must be unique")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        return self
