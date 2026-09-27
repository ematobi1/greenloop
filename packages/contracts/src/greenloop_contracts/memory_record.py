"""MemoryRecord: one append-only memory entry with provenance.

Records are never edited in place. Supersede, correct and delete each append a
new record that points at the one it replaces. A delete is a tombstone and
carries no content, so deleted personal data is not retained in the new row.

`category` keeps a personal preference apart from a general fact. `confidence`
keeps unverified model output from being treated as established: records start
unverified and move to verified or corrected only through an explicit write.
A private record is readable only by its principal; a shared record by any
principal the store allows.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from greenloop_contracts.base import ContractModel, Identifier, Timestamp, UtcDatetime


class MemoryOperation(StrEnum):
    CREATE = "create"
    SUPERSEDE = "supersede"
    CORRECT = "correct"
    DELETE = "delete"


class MemorySource(StrEnum):
    USER = "user"
    AGENT = "agent"
    TOOL = "tool"
    IMPORT = "import"
    SYSTEM = "system"


class MemoryCategory(StrEnum):
    GENERAL_KNOWLEDGE = "general_knowledge"
    PROJECT_CONTEXT = "project_context"
    TASK_EXECUTION_HISTORY = "task_execution_history"
    USER_CONTEXT = "user_context"
    ORGANIZATION_CONTEXT = "organization_context"
    DECISION = "decision"
    VERIFIED_OUTCOME = "verified_outcome"
    CORRECTION = "correction"
    AGENT_PERFORMANCE = "agent_performance"


class MemoryConfidence(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CORRECTED = "corrected"


class MemoryScope(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"


class Provenance(ContractModel):
    source: MemorySource
    source_ref: str | None = Field(default=None, max_length=500)
    created_by: Identifier
    operation: MemoryOperation = MemoryOperation.CREATE
    supersedes: Identifier | None = None


class MemoryRecord(ContractModel):
    schema_version = "2"

    record_id: Identifier
    principal_id: Identifier
    scope: MemoryScope
    category: MemoryCategory
    confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED
    content: str = Field(default="", max_length=20000)
    tags: tuple[Identifier, ...] = ()
    related_task_id: Identifier | None = None
    provenance: Provenance
    created_at: Timestamp
    expires_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _operation_rules(self) -> "MemoryRecord":
        operation = self.provenance.operation
        supersedes = self.provenance.supersedes
        if operation is MemoryOperation.CREATE and supersedes is not None:
            raise ValueError("a create cannot supersede another record")
        if operation is not MemoryOperation.CREATE and supersedes is None:
            raise ValueError(f"a {operation} must name the record it supersedes")
        if supersedes == self.record_id:
            raise ValueError("a record cannot supersede itself")
        if operation is MemoryOperation.DELETE and self.content:
            raise ValueError("a delete tombstone must not carry content")
        if operation is not MemoryOperation.DELETE and not self.content.strip():
            raise ValueError("content is required")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self
