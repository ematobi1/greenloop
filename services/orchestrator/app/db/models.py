"""ORM models. The Alembic migrations in app/db/migrations must match `Base.metadata`.

Every table has created_at and updated_at. audit_records is append-only: a
database trigger rejects UPDATE, DELETE and TRUNCATE (see the baseline migration).

TODO(phase-3): memory_records. TODO(phase-4): jobs.
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from greenloop_contracts import AuditOutcome, AuditRecord


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


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), onupdate=func.now()
    )


class PrincipalRow(TimestampMixin, Base):
    __tablename__ = "principals"

    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
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


AUDIT_OUTCOMES = ", ".join(f"'{outcome.value}'" for outcome in AuditOutcome)


class AuditRecordRow(TimestampMixin, Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        CheckConstraint(f"outcome IN ({AUDIT_OUTCOMES})", name="ck_audit_records_outcome"),
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
    details: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime())

    @classmethod
    def from_contract(cls, record: AuditRecord) -> "AuditRecordRow":
        return cls(**record.model_dump())

    def to_contract(self) -> AuditRecord:
        return AuditRecord(**{name: getattr(self, name) for name in AuditRecord.model_fields})
