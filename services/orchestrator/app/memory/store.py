"""Append-only memory store in Postgres.

Records are never updated in place. Supersede, correct and delete append a new
MemoryRecord that names the one it replaces (see provenance.py). Only the head of
a chain, the version nobody supersedes, can be revised. Two writers racing on the
same head both pass the head check, but the unique `supersedes` constraint lets
only one insert through; the other gets MemoryConflictError.

Every query filters by principal server-side, and a record owned by someone else
looks exactly like a missing one. Until a sharing policy exists, creating a
shared-scope record is refused (a chain keeps its scope, so none can appear later).

Every write adds an AuditRecord to the same session, so the memory row and its
audit entry commit or roll back together. The caller commits.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.audit import recorder
from app.db.models import MemoryRecordRow
from app.memory import provenance
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


class MemoryNotFoundError(LookupError):
    pass


class MemoryConflictError(Exception):
    pass


class MemorySharingUnavailableError(Exception):
    pass


class MemoryAlreadyRememberedError(Exception):
    pass


_successor = aliased(MemoryRecordRow)
_has_no_successor = ~exists().where(_successor.supersedes == MemoryRecordRow.record_id)


def _not_expired(now: datetime) -> ColumnElement[bool]:
    return MemoryRecordRow.expires_at.is_(None) | (MemoryRecordRow.expires_at > now)


class MemoryStore:
    def __init__(self, session: Session, correlation_id: str) -> None:
        self._session = session
        self._correlation_id = correlation_id

    def create(self, record: MemoryRecord) -> MemoryRecord:
        if record.provenance.operation is not MemoryOperation.CREATE:
            raise ValueError("create takes a create record; use revise or delete")
        if record.scope is MemoryScope.SHARED:
            raise MemorySharingUnavailableError(record.record_id)
        self._insert(record, chain_id=record.record_id)
        return record

    def get(self, principal_id: str, record_id: str) -> MemoryRecord:
        """One version by id. Missing, foreign, expired and deleted chains are all not found."""
        row = self._visible_row(principal_id, record_id)
        if row.expires_at is not None and row.expires_at <= datetime.now(UTC):
            raise MemoryNotFoundError(record_id)
        return row.to_contract()

    def history(self, principal_id: str, record_id: str) -> list[MemoryRecord]:
        """Every version in the chain holding `record_id`, oldest first."""
        row = self._visible_row(principal_id, record_id)
        rows = self._session.scalars(
            self._owned(principal_id).where(MemoryRecordRow.chain_id == row.chain_id)
        ).all()
        return _chain_order([row.to_contract() for row in rows])

    def list_current(
        self,
        principal_id: str,
        *,
        limit: int,
        offset: int,
        scope: MemoryScope | None = None,
        category: MemoryCategory | None = None,
        confidence: MemoryConfidence | None = None,
        query: str | None = None,
    ) -> tuple[list[MemoryRecord], int]:
        """Live heads (not deleted, not expired), newest first, plus the filtered total."""
        conditions = [
            MemoryRecordRow.principal_id == principal_id,
            MemoryRecordRow.operation != MemoryOperation.DELETE.value,
            _has_no_successor,
            _not_expired(datetime.now(UTC)),
        ]
        if scope is not None:
            conditions.append(MemoryRecordRow.scope == scope.value)
        if category is not None:
            conditions.append(MemoryRecordRow.category == category.value)
        if confidence is not None:
            conditions.append(MemoryRecordRow.confidence == confidence.value)
        if query:
            conditions.append(MemoryRecordRow.content.icontains(query, autoescape=True))
        total = self._session.scalar(
            select(func.count()).select_from(MemoryRecordRow).where(*conditions)
        )
        rows = self._session.scalars(
            select(MemoryRecordRow)
            .where(*conditions)
            .order_by(MemoryRecordRow.created_at.desc(), MemoryRecordRow.record_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [row.to_contract() for row in rows], total or 0

    def remember(
        self,
        principal_id: str,
        source_ref: str,
        content: str,
        source: MemorySource,
        category: MemoryCategory,
    ) -> MemoryRecord:
        """Save one chat message as a private, unverified record citing `source_ref`.

        Raises MemoryAlreadyRememberedError if a live record already cites it. Writers for
        the same (principal, source_ref) are serialized, so concurrent saves store one.
        """
        self.lock_source_ref(principal_id, source_ref)
        if self.live_by_source_ref(principal_id, source_ref) is not None:
            raise MemoryAlreadyRememberedError(source_ref)
        return self.create(
            MemoryRecord(
                record_id=provenance.new_record_id(),
                principal_id=principal_id,
                scope=MemoryScope.PRIVATE,
                category=category,
                content=content,
                provenance=Provenance(
                    source=source,
                    source_ref=source_ref,
                    created_by=principal_id,
                    operation=MemoryOperation.CREATE,
                ),
                created_at=datetime.now(UTC),
            )
        )

    def lock_source_ref(self, principal_id: str, source_ref: str) -> None:
        """Serialize writers for one (principal, source_ref) until this transaction ends, so
        two concurrent "remember" calls can't both pass the duplicate check. Postgres only;
        a no-op elsewhere."""
        if self._session.get_bind().dialect.name != "postgresql":
            return
        self._session.execute(
            select(
                func.pg_advisory_xact_lock(func.hashtextextended(f"{principal_id}|{source_ref}", 0))
            )
        )

    def live_by_source_ref(self, principal_id: str, source_ref: str) -> MemoryRecord | None:
        """The principal's live record whose latest version cites `source_ref`, if any."""
        row = self._session.scalars(
            self._owned(principal_id)
            .where(
                MemoryRecordRow.source_ref == source_ref,
                MemoryRecordRow.operation != MemoryOperation.DELETE.value,
                _has_no_successor,
                _not_expired(datetime.now(UTC)),
            )
            .limit(1)
        ).one_or_none()
        return row.to_contract() if row is not None else None

    def revise(
        self,
        principal_id: str,
        record_id: str,
        build: Callable[[MemoryRecord], MemoryRecord],
    ) -> MemoryRecord:
        """Append `build(current)` after the live head `record_id`.

        Raises MemoryNotFoundError for a missing, foreign, expired or deleted record,
        and MemoryConflictError when `record_id` is no longer the head.
        """
        original = self.get(principal_id, record_id)
        if not self._is_head(record_id):
            raise MemoryConflictError(record_id)
        successor = build(original)
        if successor.provenance.operation not in (
            MemoryOperation.SUPERSEDE,
            MemoryOperation.CORRECT,
        ):
            raise ValueError("revise appends a supersede or correct record")
        self._insert(successor, chain_id=self._chain_id(record_id))
        return successor

    def delete(self, principal_id: str, record_id: str, actor_id: str) -> MemoryRecord | None:
        """Tombstone the chain holding `record_id`. Returns None if it was already deleted."""
        row = self._session.scalars(
            self._owned(principal_id).where(MemoryRecordRow.record_id == record_id)
        ).one_or_none()
        if row is None:
            raise MemoryNotFoundError(record_id)
        head = self._head(row.chain_id)
        if head.operation == MemoryOperation.DELETE.value:
            return None
        tombstone = provenance.tombstone(head.to_contract(), actor_id)
        self._insert(tombstone, chain_id=row.chain_id)
        return tombstone

    def _owned(self, principal_id: str) -> Select[tuple[MemoryRecordRow]]:
        return select(MemoryRecordRow).where(MemoryRecordRow.principal_id == principal_id)

    def _visible_row(self, principal_id: str, record_id: str) -> MemoryRecordRow:
        row = self._session.scalars(
            self._owned(principal_id).where(MemoryRecordRow.record_id == record_id)
        ).one_or_none()
        if row is None or self._head(row.chain_id).operation == MemoryOperation.DELETE.value:
            raise MemoryNotFoundError(record_id)
        return row

    def _head(self, chain_id: str) -> MemoryRecordRow:
        return self._session.scalars(
            select(MemoryRecordRow).where(MemoryRecordRow.chain_id == chain_id, _has_no_successor)
        ).one()

    def _is_head(self, record_id: str) -> bool:
        return not self._session.scalar(
            select(exists().where(MemoryRecordRow.supersedes == record_id))
        )

    def _chain_id(self, record_id: str) -> str:
        return self._session.scalars(
            select(MemoryRecordRow.chain_id).where(MemoryRecordRow.record_id == record_id)
        ).one()

    def _insert(self, record: MemoryRecord, *, chain_id: str) -> None:
        operation = record.provenance.operation
        try:
            with self._session.begin_nested():
                self._session.add(MemoryRecordRow.from_contract(record, chain_id))
        except IntegrityError as err:
            if operation is MemoryOperation.CREATE:
                raise
            raise MemoryConflictError(record.provenance.supersedes) from err
        recorder.record(
            self._session,
            AuditRecord(
                audit_id=f"aud-{uuid.uuid4().hex}",
                principal_id=record.principal_id,
                actor=record.provenance.created_by,
                action=f"memory.{operation.value}",
                resource_type="memory_record",
                resource_id=record.record_id,
                outcome=AuditOutcome.EXECUTED,
                correlation_id=self._correlation_id,
                details={"chain_id": chain_id, "supersedes": record.provenance.supersedes},
            ),
        )


def _chain_order(records: list[MemoryRecord]) -> list[MemoryRecord]:
    """Follow supersedes links from the create, so equal timestamps cannot reorder a chain."""
    successor_of = {record.provenance.supersedes: record for record in records}
    ordered = []
    current = successor_of.get(None)
    while current is not None:
        ordered.append(current)
        current = successor_of.get(current.record_id)
    return ordered
