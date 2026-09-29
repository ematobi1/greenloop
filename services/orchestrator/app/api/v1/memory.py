"""Memory records for the authenticated principal.

The owner is always the caller and provenance is always `source=user,
created_by=<caller>`; neither is accepted from the request body. New records
start unverified, and only a system principal may mark a revision verified.
Shared scope is refused until a sharing policy exists. A revision (supersede or
correct) and a delete (tombstone) each append a record; nothing is edited in
place. Every write is audited in the same transaction.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)
from sqlalchemy.orm import Session

from app.api.v1.pagination import Limit, Offset, PageMeta
from app.core.auth import CurrentPrincipal
from app.core.errors import ApiError
from app.db.session import get_session
from app.memory import provenance
from app.memory.store import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemorySharingUnavailableError,
    MemoryStore,
)
from greenloop_contracts import (
    MemoryCategory,
    MemoryConfidence,
    MemoryOperation,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    Provenance,
)
from greenloop_contracts.base import Identifier, UtcDatetime

router = APIRouter(prefix="/memory-records", tags=["memory"])

Content = Annotated[str, StringConstraints(min_length=1, max_length=20000)]
SourceRef = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Tags = Annotated[tuple[Identifier, ...], Field(max_length=32)]
RecordId = Annotated[str, Path(max_length=128)]


class MemoryRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MemoryScope
    category: MemoryCategory
    content: Content
    tags: Tags = ()
    related_task_id: Identifier | None = None
    source_ref: SourceRef | None = None
    expires_at: UtcDatetime | None = None


class MemoryRevisionCreate(BaseModel):
    """A supersede may change content, category, confidence, tags and expiry.
    A correct changes content only and always sets confidence to corrected."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["supersede", "correct"]
    content: Content
    source_ref: SourceRef | None = None
    category: MemoryCategory | None = None
    confidence: Literal["unverified", "verified"] | None = None
    tags: Tags | None = None
    expires_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _correct_changes_content_only(self) -> "MemoryRevisionCreate":
        supersede_only = {"category", "confidence", "tags", "expires_at"}
        if self.operation == "correct" and self.model_fields_set & supersede_only:
            raise ValueError("a correct changes content only")
        return self


class MemoryRecordPage(BaseModel):
    data: list[MemoryRecord]
    meta: PageMeta


def get_store(request: Request, session: Annotated[Session, Depends(get_session)]) -> MemoryStore:
    return MemoryStore(session, request.state.correlation_id)


Store = Annotated[MemoryStore, Depends(get_store)]
DbSession = Annotated[Session, Depends(get_session)]


def _not_found() -> ApiError:
    return ApiError(404, "MEMORY_RECORD_NOT_FOUND", "Memory record not found.")


def _conflict() -> ApiError:
    return ApiError(
        409,
        "MEMORY_RECORD_CONFLICT",
        "This is not the current version of the record. Revise the latest version.",
    )


def _invalid(error: ValidationError) -> ApiError:
    fields = {
        ".".join(str(part) for part in item["loc"]) or "record": item["msg"]
        for item in error.errors(include_input=False, include_url=False)
    }
    return ApiError(422, "INVALID_MEMORY_RECORD", "Memory record is invalid.", fields=fields)


@router.get("")
def list_memory_records(
    principal: CurrentPrincipal,
    store: Store,
    limit: Limit = 50,
    offset: Offset = 0,
    scope: MemoryScope | None = None,
    category: MemoryCategory | None = None,
    confidence: MemoryConfidence | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> MemoryRecordPage:
    records, total = store.list_current(
        principal.principal_id,
        limit=limit,
        offset=offset,
        scope=scope,
        category=category,
        confidence=confidence,
        query=q,
    )
    return MemoryRecordPage(data=records, meta=PageMeta(total=total, limit=limit, offset=offset))


@router.post("", status_code=201)
def create_memory_record(
    body: MemoryRecordCreate, principal: CurrentPrincipal, store: Store, session: DbSession
) -> MemoryRecord:
    try:
        record = MemoryRecord(
            record_id=provenance.new_record_id(),
            principal_id=principal.principal_id,
            scope=body.scope,
            category=body.category,
            content=body.content,
            tags=body.tags,
            related_task_id=body.related_task_id,
            provenance=Provenance(
                source=MemorySource.USER,
                source_ref=body.source_ref,
                created_by=principal.principal_id,
                operation=MemoryOperation.CREATE,
            ),
            created_at=datetime.now(UTC),
            expires_at=body.expires_at,
        )
    except ValidationError as err:
        raise _invalid(err) from None
    try:
        store.create(record)
    except MemorySharingUnavailableError:
        raise ApiError(
            422,
            "SHARED_SCOPE_UNAVAILABLE",
            "Shared memory is not available yet. Use scope 'private'.",
            fields={"scope": "Shared scope is disabled until a sharing policy exists."},
        ) from None
    session.commit()
    return record


@router.get("/{record_id}")
def get_memory_record(
    record_id: RecordId, principal: CurrentPrincipal, store: Store
) -> MemoryRecord:
    try:
        return store.get(principal.principal_id, record_id)
    except MemoryNotFoundError:
        raise _not_found() from None


@router.get("/{record_id}/history")
def get_memory_history(
    record_id: RecordId, principal: CurrentPrincipal, store: Store
) -> MemoryRecordPage:
    try:
        records = store.history(principal.principal_id, record_id)
    except MemoryNotFoundError:
        raise _not_found() from None
    meta = PageMeta(total=len(records), limit=len(records), offset=0)
    return MemoryRecordPage(data=records, meta=meta)


@router.post("/{record_id}/revisions", status_code=201)
def create_memory_revision(
    record_id: RecordId,
    body: MemoryRevisionCreate,
    principal: CurrentPrincipal,
    store: Store,
    session: DbSession,
) -> MemoryRecord:
    if body.confidence == "verified" and not principal.is_system:
        raise ApiError(
            403,
            "VERIFICATION_NOT_ALLOWED",
            "Only a system principal can mark memory verified.",
        )

    def build(original: MemoryRecord) -> MemoryRecord:
        if body.operation == "correct":
            return provenance.correct(
                original, body.content, principal.principal_id, source_ref=body.source_ref
            )
        changes = {
            name: getattr(body, name)
            for name in ("category", "tags", "expires_at")
            if name in body.model_fields_set
        }
        return provenance.supersede(
            original,
            body.content,
            principal.principal_id,
            source_ref=body.source_ref,
            confidence=MemoryConfidence(body.confidence or "unverified"),
            **changes,
        )

    try:
        revision = store.revise(principal.principal_id, record_id, build)
    except MemoryNotFoundError:
        raise _not_found() from None
    except MemoryConflictError:
        raise _conflict() from None
    except ValidationError as err:
        raise _invalid(err) from None
    session.commit()
    return revision


@router.delete("/{record_id}", status_code=204)
def delete_memory_record(
    record_id: RecordId, principal: CurrentPrincipal, store: Store, session: DbSession
) -> Response:
    try:
        store.delete(principal.principal_id, record_id, principal.principal_id)
    except MemoryNotFoundError:
        raise _not_found() from None
    except MemoryConflictError:
        raise _conflict() from None
    session.commit()
    return Response(status_code=204)
