"""ORM models. The Alembic migrations in app/db/migrations must match `Base.metadata`.

Every table has created_at and updated_at. audit_records and memory_records are
append-only: database triggers reject UPDATE, DELETE and TRUNCATE (see migrations).

Conversations are soft-deleted (deleted_at) and carry a turn lease (active_turn_id,
turn_lease_expires_at) so one chat turn runs at a time; a trigger rejects UPDATE on messages.

memory_embeddings holds one vector per (record, embedding model), kept apart from
memory_records so adding or backfilling an embedding never updates a memory row.

TODO(phase-4): jobs.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from greenloop_contracts import (
    AuditOutcome,
    AuditRecord,
    MemoryCategory,
    MemoryConfidence,
    MemoryOperation,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    Provenance,
)


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime that is always UTC on the way in and out."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not stored")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _in(column: str, values: type[StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(member.value) for member in values)})"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), onupdate=func.now()
    )


class PrincipalRole(StrEnum):
    """`system` principals are trusted services. Only they may mark memory verified."""

    USER = "user"
    SYSTEM = "system"


class PrincipalRow(TimestampMixin, Base):
    __tablename__ = "principals"
    __table_args__ = (CheckConstraint(_in("role", PrincipalRole), name="ck_principals_role"),)

    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), server_default=PrincipalRole.USER.value)
    disabled_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class ApiTokenRow(TimestampMixin, Base):
    """A bearer token. Only the SHA256 of the token is stored; the token itself never is."""

    __tablename__ = "api_tokens"

    token_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("principals.principal_id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(100))
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class UserCredentialRow(TimestampMixin, Base):
    """Username and argon2id password hash for a principal that signs in to the web app."""

    __tablename__ = "user_credentials"

    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("principals.principal_id"), primary_key=True
    )
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_changed_at: Mapped[datetime] = mapped_column(UtcDateTime())


class UserSessionRow(TimestampMixin, Base):
    """A signed-in browser session. Only the token's SHA256 is stored."""

    __tablename__ = "user_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("principals.principal_id"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class LoginThrottleRow(TimestampMixin, Base):
    """Failed sign-ins per username, known or not, so a lockout reveals nothing."""

    __tablename__ = "login_throttle"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(UtcDateTime())


class AuditRecordRow(TimestampMixin, Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        CheckConstraint(_in("outcome", AuditOutcome), name="ck_audit_records_outcome"),
        Index("ix_audit_records_principal_occurred", "principal_id", "occurred_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), ForeignKey("principals.principal_id"))
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[str | None] = mapped_column(String(500))
    outcome: Mapped[str] = mapped_column(String(32))
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_hash: Mapped[str | None] = mapped_column(String(64))
    approval_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict] = mapped_column(JsonDocument)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime())

    @classmethod
    def from_contract(cls, record: AuditRecord) -> "AuditRecordRow":
        return cls(**record.model_dump())

    def to_contract(self) -> AuditRecord:
        return AuditRecord(**{name: getattr(self, name) for name in AuditRecord.model_fields})


class MemoryRecordRow(TimestampMixin, Base):
    """One version of a memory. A chain is a create followed by supersede, correct or
    delete records, each naming its predecessor. The head of a chain is the version
    nobody supersedes.

    The database guarantees the chain shape: each record has at most one successor
    (unique `supersedes`), and a successor keeps its predecessor's principal, chain and
    scope (composite foreign key). `chain_id` is the record_id of the chain's create.
    """

    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint("supersedes", name="uq_memory_records_supersedes"),
        UniqueConstraint(
            "record_id", "principal_id", "chain_id", "scope", name="uq_memory_records_lineage"
        ),
        ForeignKeyConstraint(
            ["supersedes", "principal_id", "chain_id", "scope"],
            [
                "memory_records.record_id",
                "memory_records.principal_id",
                "memory_records.chain_id",
                "memory_records.scope",
            ],
            name="fk_memory_records_predecessor",
        ),
        CheckConstraint(_in("scope", MemoryScope), name="ck_memory_records_scope"),
        CheckConstraint(_in("category", MemoryCategory), name="ck_memory_records_category"),
        CheckConstraint(_in("confidence", MemoryConfidence), name="ck_memory_records_confidence"),
        CheckConstraint(_in("operation", MemoryOperation), name="ck_memory_records_operation"),
        CheckConstraint(_in("source", MemorySource), name="ck_memory_records_source"),
        CheckConstraint(
            "(operation = 'create') = (supersedes IS NULL)", name="ck_memory_records_supersedes"
        ),
        CheckConstraint(
            "(operation = 'create') = (chain_id = record_id)", name="ck_memory_records_chain_root"
        ),
        CheckConstraint(
            "(operation = 'delete') = (content = '')", name="ck_memory_records_tombstone"
        ),
        Index("ix_memory_records_principal_chain", "principal_id", "chain_id"),
        Index("ix_memory_records_principal_created", "principal_id", "created_at"),
    )

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), ForeignKey("principals.principal_id"))
    chain_id: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JsonDocument)
    related_task_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(128))
    operation: Mapped[str] = mapped_column(String(16))
    supersedes: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime())

    @classmethod
    def from_contract(cls, record: MemoryRecord, chain_id: str) -> "MemoryRecordRow":
        provenance = record.provenance
        return cls(
            record_id=record.record_id,
            principal_id=record.principal_id,
            chain_id=chain_id,
            scope=record.scope,
            category=record.category,
            confidence=record.confidence,
            content=record.content,
            tags=list(record.tags),
            related_task_id=record.related_task_id,
            source=provenance.source,
            source_ref=provenance.source_ref,
            created_by=provenance.created_by,
            operation=provenance.operation,
            supersedes=provenance.supersedes,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    def to_contract(self) -> MemoryRecord:
        return MemoryRecord(
            record_id=self.record_id,
            principal_id=self.principal_id,
            scope=MemoryScope(self.scope),
            category=MemoryCategory(self.category),
            confidence=MemoryConfidence(self.confidence),
            content=self.content,
            tags=tuple(self.tags),
            related_task_id=self.related_task_id,
            provenance=Provenance(
                source=MemorySource(self.source),
                source_ref=self.source_ref,
                created_by=self.created_by,
                operation=MemoryOperation(self.operation),
                supersedes=self.supersedes,
            ),
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    """`incomplete`: the stream stopped early (provider error, disconnect); partial text kept."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


EMBEDDING_DIMENSIONS = 768


class MemoryEmbeddingRow(TimestampMixin, Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (
        Index(
            "ix_memory_embeddings_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    record_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("memory_records.record_id", name="fk_memory_embeddings_record"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class ConversationRow(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_principal_updated", "principal_id", "updated_at"),)

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), ForeignKey("principals.principal_id"))
    title: Mapped[str] = mapped_column(String(200))
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    active_turn_id: Mapped[str | None] = mapped_column(String(128))
    turn_lease_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class MessageRow(TimestampMixin, Base):
    """One chat turn. (conversation_id, sequence) is unique, which orders the transcript and
    makes two writers racing for the same sequence number fail instead of interleaving."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        CheckConstraint(_in("role", MessageRole), name="ck_messages_role"),
        CheckConstraint(_in("status", MessageStatus), name="ck_messages_status"),
        CheckConstraint("sequence >= 1", name="ck_messages_sequence_positive"),
    )

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("conversations.conversation_id")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String(128))
