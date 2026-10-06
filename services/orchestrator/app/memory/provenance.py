"""Provenance operations: build the successor record for supersede, correct and delete.

Each returns a new MemoryRecord linked to `original`; nothing is edited in place.
The successor keeps the original's principal and scope. Fields not given carry over.
"""

import uuid
from datetime import UTC, datetime

from greenloop_contracts import (
    MemoryCategory,
    MemoryConfidence,
    MemoryOperation,
    MemoryRecord,
    MemorySource,
    Provenance,
)


class _Unset:
    """Marks "keep the original's value", distinct from an explicit None."""


_UNSET = _Unset()


def new_record_id() -> str:
    return f"mem-{uuid.uuid4().hex}"


def _successor(
    original: MemoryRecord,
    *,
    operation: MemoryOperation,
    content: str,
    confidence: MemoryConfidence,
    actor_id: str,
    source: MemorySource,
    source_ref: str | None,
    category: MemoryCategory | None,
    tags: tuple[str, ...] | None,
    expires_at: datetime | _Unset | None,
) -> MemoryRecord:
    return MemoryRecord(
        record_id=new_record_id(),
        principal_id=original.principal_id,
        scope=original.scope,
        category=category or original.category,
        confidence=confidence,
        content=content,
        tags=original.tags if tags is None else tags,
        related_task_id=original.related_task_id,
        provenance=Provenance(
            source=source,
            source_ref=source_ref,
            created_by=actor_id,
            operation=operation,
            supersedes=original.record_id,
        ),
        created_at=datetime.now(UTC),
        expires_at=original.expires_at if isinstance(expires_at, _Unset) else expires_at,
    )


def _carried(original: MemoryRecord, source_ref: str | None) -> str | None:
    """A revision keeps where the memory came from unless the caller names a new source."""
    return source_ref if source_ref is not None else original.provenance.source_ref


def supersede(
    original: MemoryRecord,
    new_content: str,
    actor_id: str,
    *,
    source: MemorySource = MemorySource.USER,
    source_ref: str | None = None,
    category: MemoryCategory | None = None,
    confidence: MemoryConfidence = MemoryConfidence.UNVERIFIED,
    tags: tuple[str, ...] | None = None,
    expires_at: datetime | _Unset | None = _UNSET,
) -> MemoryRecord:
    return _successor(
        original,
        operation=MemoryOperation.SUPERSEDE,
        content=new_content,
        confidence=confidence,
        actor_id=actor_id,
        source=source,
        source_ref=_carried(original, source_ref),
        category=category,
        tags=tags,
        expires_at=expires_at,
    )


def correct(
    original: MemoryRecord,
    corrected_content: str,
    actor_id: str,
    *,
    source: MemorySource = MemorySource.USER,
    source_ref: str | None = None,
) -> MemoryRecord:
    return _successor(
        original,
        operation=MemoryOperation.CORRECT,
        content=corrected_content,
        confidence=MemoryConfidence.CORRECTED,
        actor_id=actor_id,
        source=source,
        source_ref=_carried(original, source_ref),
        category=None,
        tags=None,
        expires_at=_UNSET,
    )


def tombstone(original: MemoryRecord, actor_id: str) -> MemoryRecord:
    """An empty-content delete record. Tags and expiry are dropped with the content."""
    return _successor(
        original,
        operation=MemoryOperation.DELETE,
        content="",
        confidence=original.confidence,
        actor_id=actor_id,
        source=MemorySource.USER,
        source_ref=None,
        category=None,
        tags=(),
        expires_at=None,
    )
