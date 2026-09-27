"""MemoryRecord: one append-only memory entry with provenance.

Records are never edited in place. Supersede, correct and delete each append a
new record that points at the one it replaces. A delete is a tombstone and
carries no content, so deleted personal data is not retained in the new row.
"""

from enum import StrEnum

from pydantic import Field, model_validator

from greenloop_contracts.base import ContractModel, Identifier, Timestamp


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


class Provenance(ContractModel):
    source: MemorySource
    source_ref: str | None = Field(default=None, max_length=500)
    created_by: Identifier
    operation: MemoryOperation = MemoryOperation.CREATE
    supersedes: Identifier | None = None


class MemoryRecord(ContractModel):
    record_id: Identifier
    principal_id: Identifier
    scope: Identifier
    content: str = Field(default="", max_length=20000)
    tags: tuple[Identifier, ...] = ()
    provenance: Provenance
    created_at: Timestamp

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
        return self
