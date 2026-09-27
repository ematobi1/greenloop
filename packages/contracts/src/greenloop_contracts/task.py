"""Task: a unit of planned work owned by a principal."""

from enum import StrEnum

from pydantic import model_validator

from greenloop_contracts.base import ContractModel, Identifier, LongText, ShortText, Timestamp


class TaskStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task(ContractModel):
    task_id: Identifier
    principal_id: Identifier
    title: ShortText
    description: LongText = ""
    status: TaskStatus = TaskStatus.PENDING
    parent_task_id: Identifier | None = None
    depends_on: tuple[Identifier, ...] = ()
    created_at: Timestamp

    @model_validator(mode="after")
    def _no_self_reference(self) -> "Task":
        if self.parent_task_id == self.task_id:
            raise ValueError("a task cannot be its own parent")
        if self.task_id in self.depends_on:
            raise ValueError("a task cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on entries must be unique")
        return self
